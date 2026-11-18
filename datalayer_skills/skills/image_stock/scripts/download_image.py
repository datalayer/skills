# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Download a stock image into the workspace, as its provider's terms allow.

Takes the image's provider and id, and the full_url search_images returned
(Freepik: the id alone, the file is asked for by id). An Unsplash download is
reported to Unsplash, as its guidelines ask, with the download_location
search_images returned. The file is written under the working directory.

Usage:
    python download_image.py --provider pexels --id 123 --url https://images.pexels.com/... \
        [--output images/lake.jpg] [--download-location URL]
"""

from __future__ import annotations

import argparse
import contextlib
import email.utils
import fcntl
import html
import http.client
import ipaddress
import json
import os
import secrets
import socket
import ssl
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# ---- The stock image providers (the same block in every image-stock script) ----
#
# A skill script is sent to the sandbox as its own source and run there, so
# it imports nothing of this package: this block is repeated in each script,
# and a test holds the copies identical. Standard library only.

USER_AGENT = "image-stock-skill/1.0"
MAX_JSON_BYTES = 5 * 1024 * 1024

#: What each provider is, the variable that holds its key, and what its terms ask.
PROVIDERS = {
    "unsplash": {
        "label": "Unsplash",
        "key": "UNSPLASH_ACCESS_KEY",
        "home": "https://unsplash.com",
        "license": "Unsplash License: free to use, commercially too.",
        "credit": "required",
        "terms": (
            "Credit the photographer and Unsplash, each with its link. Show a photo from the "
            "URL returned, unchanged; download it only to use it, with download_image, which "
            "reports the download to Unsplash."
        ),
        "max_per_page": 30,
    },
    "pexels": {
        "label": "Pexels",
        "key": "PEXELS_API_KEY",
        "home": "https://www.pexels.com",
        "license": "Pexels License: free to use, commercially too.",
        "credit": "required",
        "terms": (
            "Show a link to Pexels wherever results are shown, and credit the photographer "
            "with a link to the photo's page."
        ),
        "max_per_page": 80,
    },
    "pixabay": {
        "label": "Pixabay",
        "key": "PIXABAY_API_KEY",
        "home": "https://pixabay.com",
        "license": "Pixabay Content License: free to use, commercially too.",
        "credit": "appreciated",
        "terms": (
            "Say that results come from Pixabay wherever they are shown. Its image URLs are "
            "for showing results only and stop working: download an image to use it, never "
            "link to it for good."
        ),
        "max_per_page": 200,
    },
    "freepik": {
        "label": "Freepik",
        "key": "FREEPIK_API_KEY",
        "home": "https://www.freepik.com",
        "license": "Freepik License: free resources with a credit, premium ones with a plan.",
        "credit": "required for free resources",
        "terms": (
            "Credit Freepik and the author for a free resource. A premium one downloads only "
            "with a plan that allows it. The file itself comes from download_image, by id."
        ),
        "max_per_page": 50,
    },
}

ORIENTATIONS = ("landscape", "portrait", "square")


class StockRefused(Exception):
    """Why it was not done, in a sentence that names no key's value and no request URL."""


def setting(name: str, default: str = "") -> str:
    return (os.environ.get(name) or "").strip() or default


def whole_number(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(setting(name, str(default)))))
    except ValueError:
        return default


def configured() -> list:
    """The providers whose key is set, in a fixed order: the only ones offered."""
    return [name for name, provider in PROVIDERS.items() if setting(provider["key"])]


def provider_named(name: str) -> str:
    """A configured provider by name, or the refusal that says which ones are."""
    wanted = (name or "").strip().lower()
    offered = configured()
    if wanted in offered:
        return wanted
    known = f"{wanted} has no key set here" if wanted in PROVIDERS else f"unknown provider {name!r}"
    raise StockRefused(
        f"{known}. Configured: {', '.join(offered) or 'none'}."
        + ("" if offered else " Set one provider's key, then try again.")
    )


def rate_limit(provider: str) -> tuple:
    """(requests, seconds): the provider's published limit, or a polite one of ours."""
    if provider == "unsplash":
        production = setting("UNSPLASH_TIER").lower() == "production"
        return (1000 if production else 50), 3600
    if provider == "pexels":
        return 200, 3600
    if provider == "pixabay":
        return 100, 60
    return whole_number("FREEPIK_REQUESTS_PER_MINUTE", 30, 1, 600), 60


def state_file(name: str) -> str:
    folder = setting("IMAGE_STOCK_STATE_DIR") or os.path.join(
        os.path.expanduser("~"), ".cache", "image-stock"
    )
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = tempfile.gettempdir()
    return os.path.join(folder, name)


def read_state(name: str) -> dict:
    try:
        with open(state_file(name), encoding="utf-8") as handle:
            kept = json.load(handle)
        return kept if isinstance(kept, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(name: str, state: dict) -> None:
    """Keep a state file, or refuse: a request whose count cannot be kept is not sent."""
    path = state_file(name)
    temporary = f"{path}.{os.getpid()}.{threading.get_ident()}"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(temporary, path)
    except OSError as error:
        raise StockRefused(
            f"the image-stock state could not be saved ({type(error).__name__}): set "
            "IMAGE_STOCK_STATE_DIR to a folder that can be written."
        ) from None


#: A search of every provider asks them at once: one thread at a time in a state file.
COUNTING = threading.RLock()


@contextlib.contextmanager
def state_locked(name: str):
    """One read, check and write of a state file at a time, across threads and processes."""
    with COUNTING:
        try:
            lock = os.open(state_file(f"{name}.lock"), os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as error:
            raise StockRefused(
                f"the image-stock state could not be locked ({type(error).__name__}): set "
                "IMAGE_STOCK_STATE_DIR to a folder that can be written."
            ) from None
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
        finally:
            os.close(lock)  # Closing it releases the lock.


def take_request(provider: str) -> None:
    """Count one request to a provider, or refuse it when its limit is reached."""
    with state_locked("rate.json"):
        count_request(provider)


def count_request(provider: str) -> None:
    limit, window = rate_limit(provider)
    state = read_state("rate.json")
    entry = state.get(provider) if isinstance(state.get(provider), dict) else {}
    now = time.time()
    calls = [
        at for at in entry.get("calls", []) if isinstance(at, (int, float)) and now - at < window
    ]
    wait = float(entry.get("blocked_until") or 0) - now
    if wait <= 0 and len(calls) >= limit:
        wait = window - (now - calls[0])
    if wait > 0:
        raise StockRefused(
            f"{PROVIDERS[provider]['label']} rate limit reached ({limit} requests per "
            f"{window} s): try again in {int(wait) + 1} s, or use another provider."
        )
    state[provider] = {"calls": calls + [now]}
    write_state("rate.json", state)


def block_until(provider: str, seconds: float) -> None:
    """Ask a provider nothing for ``seconds``, its whole deadline; a later one kept is kept."""
    with state_locked("rate.json"):
        state = read_state("rate.json")
        entry = state.get(provider) if isinstance(state.get(provider), dict) else {}
        until = time.time() + max(1.0, seconds)
        entry["blocked_until"] = max(until, float(entry.get("blocked_until") or 0))
        state[provider] = entry
        write_state("rate.json", state)


def wait_asked(headers, default: float) -> float:
    """The wait a provider asks for: its Retry-After (seconds or a date), else its reset."""
    retry = str((headers or {}).get("Retry-After") or "").strip()
    if retry.isdigit():
        return float(retry)
    if retry:
        try:
            return email.utils.parsedate_to_datetime(retry).timestamp() - time.time()
        except (TypeError, ValueError, IndexError):
            pass
    reset = str((headers or {}).get("X-Ratelimit-Reset") or "").strip()
    if reset.isdigit():
        seconds = float(reset)
        # A date, in seconds since 1970, and not a delay.
        return seconds - time.time() if seconds > 10_000_000 else seconds
    return default


def note_remaining(provider: str, headers) -> None:
    """Stop asking a provider that says no request is left, until it has some again."""
    if str(headers.get("X-Ratelimit-Remaining") or "").strip() != "0":
        return
    block_until(provider, wait_asked(headers, 900.0))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """An API call follows no redirect: its key goes to the provider's host alone."""

    def redirect_request(self, *args, **kwargs):
        return None


def open_url(request, timeout: float, handlers=()):
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)


def timeout_seconds() -> float:
    return float(whole_number("IMAGE_STOCK_TIMEOUT_SECONDS", 10, 1, 25))


def refusal_of(provider: str, status: int) -> str:
    about = PROVIDERS[provider]
    if status in (401, 403):
        return f"{about['label']} refused the key in {about['key']} (HTTP {status}): check it."
    if status == 429:
        return f"{about['label']} says its rate limit is reached (HTTP 429): try again later."
    if status >= 500:
        return f"{about['label']} is not answering (HTTP {status}): try again later."
    return f"{about['label']} refused the request (HTTP {status})."


def api_get(provider: str, url: str, headers: dict) -> dict:
    """One counted GET to a provider's API, its JSON answer; a refusal in a sentence."""
    take_request(provider)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **headers}
    )
    label = PROVIDERS[provider]["label"]
    try:
        with open_url(request, timeout_seconds(), (NoRedirect(),)) as response:
            note_remaining(provider, response.headers)
            body = response.read(MAX_JSON_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            block_until(provider, wait_asked(error.headers, 60.0))
        raise StockRefused(refusal_of(provider, error.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", None) or type(error).__name__
        raise StockRefused(f"{label} could not be reached ({reason}).") from None
    try:
        answer = json.loads(body[:MAX_JSON_BYTES].decode("utf-8"))
    except ValueError:
        raise StockRefused(f"{label} answered something that is no JSON.") from None
    if not isinstance(answer, dict):
        raise StockRefused(f"{label} answered something unexpected.")
    return answer


def with_referral(url: str) -> str:
    """A link back to Unsplash, with the referral parameters its guidelines ask for."""
    if not url:
        return url
    app = urllib.parse.quote(setting("UNSPLASH_APP_NAME", "image-stock-skill"), safe="")
    return f"{url}{'&' if '?' in url else '?'}utm_source={app}&utm_medium=referral"


def credit(
    provider: str,
    author: str = "",
    author_url: str = "",
    page_url: str = "",
    license_type: str = "",
) -> dict:
    """The credit line a provider's terms ask for: as text, Markdown and HTML."""
    about = PROVIDERS[provider]
    label, home = about["label"], about["home"]
    author = (author or "").strip()
    required = provider in ("unsplash", "pexels")
    if provider == "unsplash":
        words, who_url, where_url = "Photo by", with_referral(author_url), with_referral(home)
    elif provider == "pexels":
        words, who_url, where_url = "Photo by", author_url, page_url or home
    elif provider == "pixabay":
        words, who_url, where_url = "Image by", author_url, page_url or home
    else:
        required = (license_type or "freemium").lower() != "premium"
        words, who_url, where_url = "Image by", author_url, page_url or home
    joiner = "from" if provider == "pixabay" else "on"

    def linked(kind: str, text: str, url: str) -> str:
        if not url or kind == "text":
            return html.escape(text) if kind == "html" else text
        if kind == "markdown":
            return f"[{text}]({url})"
        return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'

    lines = {}
    for kind in ("text", "markdown", "html"):
        where = linked(kind, label, where_url)
        lines[kind] = (
            f"{words} {linked(kind, author, who_url)} {joiner} {where}"
            if author
            else (f"{words.split()[0]} {joiner} {where}")
        )
    if lines["text"] and (who_url or where_url):
        links = " ".join(url for url in (who_url, where_url) if url)
        lines["text"] = f"{lines['text']} ({links})"
    return {"provider": provider, "required": required, "rule": about["credit"], **lines}


def run(main) -> None:
    """Run ``main``, printing its JSON; a refusal is said on stderr with exit code 1."""
    try:
        print(json.dumps(main(), indent=2, default=str))
    except StockRefused as refusal:
        print(f"Error: {refusal}", file=sys.stderr)
        sys.exit(1)


# ---- End of the stock image providers ----


MAX_IMAGE_BYTES = 40 * 1024 * 1024

#: Where each provider serves its images from: a download, and every redirect of it, goes
#: nowhere else. A name starting with a dot stands for that domain's hosts: Freepik hands out
#: signed links on its own hosts (img.freepik.com, downloadscdn5.freepik.com…), under
#: either of its two names.
IMAGE_HOSTS = {
    "unsplash": ("images.unsplash.com", "plus.unsplash.com"),
    "pexels": ("images.pexels.com",),
    "pixabay": ("pixabay.com", "cdn.pixabay.com"),
    "freepik": (".freepik.com", ".magnific.com"),
}

EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/svg+xml": ".svg",
}


def on_hosts(host: str, hosts: tuple) -> bool:
    """Whether ``host`` is one of ``hosts``; a name starting with a dot is a whole domain."""
    return any(
        host.endswith(allowed) if allowed.startswith(".") else host == allowed for allowed in hosts
    )


def public_address(host: str, port: int = 443) -> str:
    """The address ``host`` resolves to, when every address it has is public; else refused."""
    try:
        addresses = [info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)]
    except OSError:
        raise StockRefused(f"{host} could not be found.") from None
    if not addresses:
        raise StockRefused(f"{host} could not be found.")
    for address in addresses:
        if not ipaddress.ip_address(address.split("%")[0]).is_global:
            raise StockRefused(f"{host} is not a public address.")
    return addresses[0]


def public_https(url: str, hosts: tuple) -> str:
    """The URL when it is https, on one of ``hosts``, and at a public address."""
    parts = urllib.parse.urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise StockRefused("an image is downloaded from an https address alone.")
    if not on_hosts(host, hosts):
        raise StockRefused(
            f"{host} is not where this provider serves its images ({', '.join(hosts)}): "
            "give the full_url search_images returned."
        )
    public_address(host, parts.port or 443)
    return url


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connects to the address it checked, resolving the name once; TLS still checks the name.

    The name is resolved, every address checked public, and the socket opened to the address
    checked: a second answer of the name (DNS rebinding) is never asked for. No proxy.
    """

    def connect(self) -> None:
        address = public_address(self.host, self.port)
        sock = socket.create_connection((address, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """Every https connection of a download, its redirects too, through PinnedHTTPSConnection."""

    def https_open(self, req):
        return self.do_open(PinnedHTTPSConnection, req, context=ssl.create_default_context())


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """A download follows a redirect only to another address it would have accepted."""

    def __init__(self, hosts: tuple) -> None:
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_https(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_handlers(hosts: tuple) -> tuple:
    """No proxy, every connection pinned to its checked address, redirects checked."""
    return (urllib.request.ProxyHandler({}), PinnedHTTPSHandler(), CheckedRedirect(hosts))


OUTSIDE = "the image is written under the working directory: give a relative path."


def under(workspace: str, path: str) -> bool:
    return os.path.commonpath([workspace, path]) == workspace


def inside_workspace(output: str, provider: str, image_id: str) -> str:
    """Where the file goes, before anything is asked: the path given, or one named after the
    image, under the workspace. Checked again, for good, when the file is written."""
    workspace = os.path.realpath(os.getcwd())
    if not output:
        safe_id = "".join(c for c in image_id if c.isalnum() or c in "-_")[:80] or "image"
        folder = setting("IMAGE_STOCK_DOWNLOAD_DIR", "images")
        output = os.path.join(folder, f"{provider}-{safe_id}")
    path = os.path.normpath(os.path.join(workspace, output))
    if not under(workspace, path) or path == workspace:
        raise StockRefused(OUTSIDE)
    return path


def open_folder_inside(workspace: str, folder: str) -> int:
    """The folder, opened from the workspace one name at a time, each made when missing and
    none a link: the descriptor returned is under the workspace, whatever is swapped meanwhile.
    """
    relative = os.path.relpath(folder, workspace)
    names = [] if relative == "." else relative.split(os.sep)
    if any(name in ("", ".", "..") for name in names):
        raise StockRefused(OUTSIDE)
    directory = os.O_RDONLY | os.O_DIRECTORY
    held = os.open(workspace, directory)
    try:
        for name in names:
            try:
                os.mkdir(name, 0o755, dir_fd=held)
            except FileExistsError:
                pass
            # A link here is refused, not followed.
            inner = os.open(name, directory | os.O_NOFOLLOW, dir_fd=held)
            os.close(held)
            held = inner
    except OSError:
        os.close(held)
        raise StockRefused(OUTSIDE) from None
    return held


def write_inside_workspace(path: str, body: bytes) -> str:
    """Write ``body`` at ``path``, its final name, never outside the workspace.

    The folder is reached through descriptors from the workspace, never following a link; the
    file is written in it under a name of this call's own and renamed over ``path``: a link
    there is replaced, not followed.
    """
    workspace = os.path.realpath(os.getcwd())
    folder, name = os.path.split(os.path.normpath(path))
    if not name or name in (".", "..") or not under(workspace, folder):
        raise StockRefused(OUTSIDE)
    folder_fd = open_folder_inside(workspace, folder)
    try:
        part = f".{name}.{os.getpid()}.{secrets.token_hex(8)}.part"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            file_fd = os.open(part, flags, 0o644, dir_fd=folder_fd)
        except OSError as error:
            raise StockRefused(
                f"the image could not be written ({type(error).__name__})."
            ) from None
        try:
            with os.fdopen(file_fd, "wb") as handle:
                handle.write(body)
            os.replace(part, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
        except OSError as error:
            # Only the file this call made is removed.
            try:
                os.unlink(part, dir_fd=folder_fd)
            except OSError:
                pass
            raise StockRefused(
                f"the image could not be written ({type(error).__name__})."
            ) from None
    finally:
        os.close(folder_fd)
    return os.path.join(folder, name)


def fetch(provider: str, url: str, path: str, hosts: tuple) -> dict:
    """Write the image at ``url`` to ``path`` (its extension added when it has none)."""
    request = urllib.request.Request(
        public_https(url, hosts), headers={"User-Agent": USER_AGENT, "Accept": "image/*"}
    )
    label = PROVIDERS[provider]["label"]
    try:
        with open_url(request, timeout_seconds(), download_handlers(hosts)) as response:
            kind = str(response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if not kind.startswith("image/"):
                raise StockRefused(f"{label} did not answer with an image ({kind or 'no type'}).")
            body = response.read(MAX_IMAGE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise StockRefused(f"{label} refused the download (HTTP {error.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", None) or type(error).__name__
        raise StockRefused(f"{label} could not be reached for the download ({reason}).") from None
    if len(body) > MAX_IMAGE_BYTES:
        raise StockRefused(f"the image is over {MAX_IMAGE_BYTES // (1024 * 1024)} MB: not kept.")
    if not body:
        raise StockRefused(f"{label} answered an empty file.")
    if not os.path.splitext(path)[1]:
        path += EXTENSIONS.get(kind, ".img")
    written = write_inside_workspace(path, body)
    return {"path": os.path.relpath(written), "bytes": len(body), "content_type": kind}


def report_unsplash_download(key: str, image_id: str, download_location: str) -> bool:
    """Tell Unsplash the photo was downloaded, as its guidelines ask: an event, no file."""
    url = download_location or (
        f"https://api.unsplash.com/photos/{urllib.parse.quote(image_id, safe='')}/download"
    )
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() != "api.unsplash.com":
        raise StockRefused(
            "download_location is the one search_images returned, on api.unsplash.com."
        )
    api_get("unsplash", url, {"Authorization": f"Client-ID {key}", "Accept-Version": "v1"})
    return True


def freepik_file_url(key: str, image_id: str) -> str:
    """The address Freepik gives for a resource's file, asked by id."""
    if not image_id.isdigit():
        raise StockRefused("a Freepik id is a number, as search_images returned it.")
    answer = api_get(
        "freepik",
        f"https://api.magnific.com/v1/resources/{image_id}/download",
        {"x-magnific-api-key": key, "x-freepik-api-key": key},
    )
    data = answer.get("data")
    if isinstance(data, list):
        data = data[0] if data else {}
    url = (data or {}).get("url") if isinstance(data, dict) else ""
    if not url:
        raise StockRefused("Freepik gave no file for this resource.")
    return str(url)


def main() -> dict:
    parser = argparse.ArgumentParser(description="Download a stock image into the workspace")
    parser.add_argument("--provider", required=True, help="unsplash, pexels, pixabay or freepik")
    parser.add_argument("--id", required=True, help="The image's id, as search_images gave it")
    parser.add_argument(
        "--url", default="", help="The full_url search_images gave (not needed for freepik)"
    )
    parser.add_argument(
        "--output",
        default="",
        help="Where to write it, under the working directory (default: images/<provider>-<id>)",
    )
    parser.add_argument(
        "--download-location",
        "--download_location",
        dest="download_location",
        default="",
        help="Unsplash only: the download_location search_images gave",
    )
    args = parser.parse_args()
    provider = provider_named(args.provider)
    key = setting(PROVIDERS[provider]["key"])
    image_id = str(args.id).strip()
    path = inside_workspace(args.output.strip(), provider, image_id)
    if provider != "freepik" and not args.url.strip():
        raise StockRefused("give the image's full_url, as search_images returned it.")
    reported = {}
    if provider == "unsplash":
        # Unsplash is told first, as its guidelines ask: untold, the image is not downloaded.
        try:
            report_unsplash_download(key, image_id, args.download_location.strip())
        except StockRefused as refusal:
            raise StockRefused(
                f"the download could not be reported to Unsplash, so the image was not "
                f"downloaded: {refusal}"
            ) from None
        reported = {"reported_to_unsplash": True}
    url = freepik_file_url(key, image_id) if provider == "freepik" else args.url.strip()
    saved = fetch(provider, url, path, IMAGE_HOSTS[provider])
    result = {"provider": provider, "id": image_id, **saved, **reported}
    result["credit"] = PROVIDERS[provider]["credit"]
    result["next"] = (
        "Get the credit line with image_attribution and put it where the image is used."
    )
    return result


if __name__ == "__main__":
    run(main)
