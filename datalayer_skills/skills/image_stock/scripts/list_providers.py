# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Say which stock image providers can be searched here, and what each one's terms ask.

A provider is offered when its key is set: UNSPLASH_ACCESS_KEY, PEXELS_API_KEY,
PIXABAY_API_KEY, FREEPIK_API_KEY. Prints names, limits and terms; never a key.

Usage:
    python list_providers.py
"""

from __future__ import annotations

import argparse
import contextlib
import email.utils
import fcntl
import html
import json
import os
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


#: A thread lock per state file, so a slow one (Pixabay's cache, while it asks Pixabay)
#: never holds up another provider's count; the guard is held only to look a lock up.
LOCKS_GUARD = threading.Lock()
LOCKS: dict = {}


def thread_lock(name: str):
    with LOCKS_GUARD:
        return LOCKS.setdefault(name, threading.RLock())


@contextlib.contextmanager
def state_locked(name: str):
    """One read, check and write of a state file at a time, across threads and processes."""
    with thread_lock(name):
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


def main() -> dict:
    argparse.ArgumentParser(
        description="List the stock image providers configured here"
    ).parse_args()
    offered = configured()
    providers = []
    for name in offered:
        about = PROVIDERS[name]
        limit, window = rate_limit(name)
        providers.append(
            {
                "provider": name,
                "name": about["label"],
                "license": about["license"],
                "credit": about["credit"],
                "terms": about["terms"],
                "rate_limit": f"{limit} requests per {window} s",
                "max_per_page": about["max_per_page"],
            }
        )
    return {
        "configured": offered,
        "not_configured": [
            {"provider": name, "set": about["key"]}
            for name, about in PROVIDERS.items()
            if name not in offered
        ],
        "providers": providers,
    }


if __name__ == "__main__":
    run(main)
