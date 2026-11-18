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
import html
import ipaddress
import json
import os
import socket
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
    path = state_file(name)
    try:
        with open(f"{path}.{os.getpid()}", "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(f"{path}.{os.getpid()}", path)
    except OSError:
        pass  # Counting is best effort where nothing can be written.


#: A search of every provider asks them at once: one at a time counts.
COUNTING = threading.Lock()


def take_request(provider: str) -> None:
    """Count one request to a provider, or refuse it when its limit is reached."""
    with COUNTING:
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
    with COUNTING:
        state = read_state("rate.json")
        entry = state.get(provider) if isinstance(state.get(provider), dict) else {}
        entry["blocked_until"] = time.time() + max(1.0, min(seconds, 3600.0))
        state[provider] = entry
        write_state("rate.json", state)


def note_remaining(provider: str, headers) -> None:
    """Stop asking a provider that says no request is left, until it has some again."""
    if str(headers.get("X-Ratelimit-Remaining") or "").strip() != "0":
        return
    reset = str(headers.get("X-Ratelimit-Reset") or "").strip()
    seconds = float(reset) if reset.isdigit() else 900.0
    if seconds > 10_000_000:  # A date, in seconds since 1970, and not a delay.
        seconds -= time.time()
    block_until(provider, seconds)


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
            block_until(provider, 60.0)
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
            return text
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

#: Where each provider serves its images from: a download goes nowhere else.
IMAGE_HOSTS = {
    "unsplash": ("images.unsplash.com", "plus.unsplash.com"),
    "pexels": ("images.pexels.com",),
    "pixabay": ("pixabay.com", "cdn.pixabay.com"),
}

EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
    "image/svg+xml": ".svg",
}


def public_https(url: str, hosts: tuple = ()) -> str:
    """The URL when it is https, on one of ``hosts`` when given, and at a public address."""
    parts = urllib.parse.urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        raise StockRefused("an image is downloaded from an https address alone.")
    if hosts and host not in hosts:
        raise StockRefused(
            f"{host} is not where this provider serves its images ({', '.join(hosts)}): "
            "give the full_url search_images returned."
        )
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError:
        raise StockRefused(f"{host} could not be found.") from None
    for address in addresses:
        if not ipaddress.ip_address(address.split("%")[0]).is_global:
            raise StockRefused(f"{host} is not a public address.")
    return url


class CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """A download follows a redirect only to another address it would have accepted."""

    def __init__(self, hosts: tuple) -> None:
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_https(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def inside_workspace(output: str, provider: str, image_id: str) -> str:
    """Where the file goes: the path given, or one named after the image, under the workspace."""
    workspace = os.path.realpath(os.getcwd())
    if not output:
        safe_id = "".join(c for c in image_id if c.isalnum() or c in "-_")[:80] or "image"
        folder = setting("IMAGE_STOCK_DOWNLOAD_DIR", "images")
        output = os.path.join(folder, f"{provider}-{safe_id}")
    path = os.path.realpath(os.path.join(workspace, output))
    if os.path.commonpath([workspace, path]) != workspace:
        raise StockRefused(
            "the image is written under the working directory: give a relative path."
        )
    return path


def fetch(provider: str, url: str, path: str, hosts: tuple) -> dict:
    """Write the image at ``url`` to ``path`` (its extension added when it has none)."""
    request = urllib.request.Request(
        public_https(url, hosts), headers={"User-Agent": USER_AGENT, "Accept": "image/*"}
    )
    label = PROVIDERS[provider]["label"]
    try:
        with open_url(request, timeout_seconds(), (CheckedRedirect(hosts),)) as response:
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(body)
    return {"path": os.path.relpath(path), "bytes": len(body), "content_type": kind}


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
    if provider == "freepik":
        saved = fetch(provider, freepik_file_url(key, image_id), path, ())
    else:
        if not args.url.strip():
            raise StockRefused("give the image's full_url, as search_images returned it.")
        saved = fetch(provider, args.url.strip(), path, IMAGE_HOSTS[provider])
    result = {"provider": provider, "id": image_id, **saved}
    if provider == "unsplash":
        try:
            result["reported_to_unsplash"] = report_unsplash_download(
                key, image_id, args.download_location.strip()
            )
        except StockRefused as refusal:
            # The file is kept; that Unsplash was not told is said, not hidden.
            result["reported_to_unsplash"] = False
            result["warning"] = f"The download could not be reported to Unsplash: {refusal}"
    result["credit"] = PROVIDERS[provider]["credit"]
    result["next"] = (
        "Get the credit line with image_attribution and put it where the image is used."
    )
    return result


if __name__ == "__main__":
    run(main)
