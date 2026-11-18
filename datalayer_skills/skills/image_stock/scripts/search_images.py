# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Search stock images on one provider, or on every provider configured here.

Results are in one shape whatever the provider: id, provider, title, author,
author_url, page_url, preview_url, full_url, width, height, license, and the
credit line its terms ask for. Only providers whose key is set are searched.

Usage:
    python search_images.py "mountain lake at dawn" [--provider all] [--per-page 5]
        [--page 1] [--orientation landscape]
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


def clean(value) -> str:
    return " ".join(str(value or "").split())


def image(provider: str, **fields) -> dict:
    """One result in the shape every provider's results take."""
    about = PROVIDERS[provider]
    line = credit(
        provider,
        fields.get("author", ""),
        fields.get("author_url", ""),
        fields.get("page_url", ""),
        fields.get("license_type", ""),
    )
    result = {
        "id": str(fields.get("id", "")),
        "provider": provider,
        "title": clean(fields.get("title"))[:200],
        "author": clean(fields.get("author")),
        "author_url": fields.get("author_url") or "",
        "page_url": fields.get("page_url") or "",
        "preview_url": fields.get("preview_url") or "",
        "full_url": fields.get("full_url") or "",
        "width": fields.get("width"),
        "height": fields.get("height"),
        "license": about["license"],
        "credit_required": line["required"],
        "credit": line["text"],
    }
    for extra in ("license_type", "download_location"):
        if fields.get(extra):
            result[extra] = fields[extra]
    return result


def search_unsplash(key: str, query: str, per_page: int, page: int, orientation: str) -> list:
    params = {"query": query, "page": page, "per_page": per_page, "content_filter": "high"}
    if orientation:
        params["orientation"] = "squarish" if orientation == "square" else orientation
    answer = api_get(
        "unsplash",
        "https://api.unsplash.com/search/photos?" + urllib.parse.urlencode(params),
        {"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
    )
    found = []
    for photo in answer.get("results") or []:
        user, links, urls = (
            photo.get("user") or {},
            photo.get("links") or {},
            photo.get("urls") or {},
        )
        found.append(
            image(
                "unsplash",
                id=photo.get("id"),
                title=photo.get("description") or photo.get("alt_description"),
                author=user.get("name"),
                author_url=(user.get("links") or {}).get("html"),
                page_url=links.get("html"),
                preview_url=urls.get("small"),
                full_url=urls.get("full"),
                width=photo.get("width"),
                height=photo.get("height"),
                download_location=links.get("download_location"),
            )
        )
    return found


def search_pexels(key: str, query: str, per_page: int, page: int, orientation: str) -> list:
    params = {"query": query, "page": page, "per_page": per_page}
    if orientation:
        params["orientation"] = orientation
    answer = api_get(
        "pexels",
        "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(params),
        {"Authorization": key},
    )
    found = []
    for photo in answer.get("photos") or []:
        src = photo.get("src") or {}
        found.append(
            image(
                "pexels",
                id=photo.get("id"),
                title=photo.get("alt"),
                author=photo.get("photographer"),
                author_url=photo.get("photographer_url"),
                page_url=photo.get("url"),
                preview_url=src.get("medium"),
                full_url=src.get("original"),
                width=photo.get("width"),
                height=photo.get("height"),
            )
        )
    return found


PIXABAY_DAY = 86400.0


def pixabay_window(per_page: int, page: int) -> tuple:
    """(Pixabay's page size, its page, where ours starts in it) for our ``page`` of ``per_page``.

    Pixabay takes no fewer than 3 a page: below that, its page is a multiple of ours (3 or 6),
    so that each of our pages lies whole in one of its, and none is skipped.
    """
    size = per_page if per_page >= 3 else per_page * 3
    offset = (page - 1) * per_page
    return size, offset // size + 1, offset % size


def pixabay_fresh(cache: dict, now: float) -> dict:
    """Every answer kept less than a day: all of them, however many."""
    return {
        asked: entry
        for asked, entry in cache.items()
        if isinstance(entry, dict) and now - float(entry.get("at") or 0) < PIXABAY_DAY
    }


def search_pixabay(key: str, query: str, per_page: int, page: int, orientation: str) -> list:
    size, their_page, start = pixabay_window(per_page, page)
    params = {
        "q": query[:100],
        "image_type": "photo",
        "safesearch": "true",
        "page": their_page,
        "per_page": size,
    }
    if orientation in ("landscape", "portrait"):  # It has no square.
        params["orientation"] = "horizontal" if orientation == "landscape" else "vertical"
    asked = urllib.parse.urlencode(params)
    # Pixabay asks that an answer be kept for 24 hours: the same search is answered from here.
    with state_locked("pixabay-cache.json"):
        kept = pixabay_fresh(read_state("pixabay-cache.json"), time.time()).get(asked)
    if kept:
        answer = kept.get("answer") or {}
    else:
        answer = api_get(
            "pixabay",
            "https://pixabay.com/api/?" + urllib.parse.urlencode({"key": key}) + "&" + asked,
            {},
        )
        # Read again under the lock: what another search kept meanwhile is kept too.
        with state_locked("pixabay-cache.json"):
            fresh = pixabay_fresh(read_state("pixabay-cache.json"), time.time())
            fresh[asked] = {"at": time.time(), "answer": answer}
            write_state("pixabay-cache.json", fresh)
    found = []
    for hit in (answer.get("hits") or [])[start : start + per_page]:
        user, user_id = hit.get("user"), hit.get("user_id")
        found.append(
            image(
                "pixabay",
                id=hit.get("id"),
                title=hit.get("tags"),
                author=user,
                author_url=f"https://pixabay.com/users/{user}-{user_id}/"
                if user and user_id
                else "",
                page_url=hit.get("pageURL"),
                preview_url=hit.get("webformatURL"),
                full_url=hit.get("largeImageURL"),
                width=hit.get("imageWidth"),
                height=hit.get("imageHeight"),
            )
        )
    return found


def search_freepik(key: str, query: str, per_page: int, page: int, orientation: str) -> list:
    params = {
        "term": query,
        "page": page,
        "limit": per_page,
        "order": "relevance",
        "filters[content_type][photo]": 1,
    }
    if orientation:
        params[f"filters[orientation][{orientation}]"] = 1
    answer = api_get(
        "freepik",
        "https://api.magnific.com/v1/resources?" + urllib.parse.urlencode(params),
        # Freepik's API is served under both names; the key is the same.
        {"x-magnific-api-key": key, "x-freepik-api-key": key},
    )
    found = []
    for resource in answer.get("data") or []:
        author = resource.get("author") or {}
        source = (resource.get("image") or {}).get("source") or {}
        kinds = {str((entry or {}).get("type") or "") for entry in resource.get("licenses") or []}
        slug = author.get("slug")
        found.append(
            image(
                "freepik",
                id=resource.get("id"),
                title=resource.get("title"),
                author=author.get("name"),
                author_url=f"https://www.freepik.com/author/{slug}" if slug else "",
                page_url=resource.get("url"),
                preview_url=source.get("url"),
                # The file itself is fetched by id, by download_image.
                full_url="",
                license_type="premium" if kinds == {"premium"} else "freemium",
            )
        )
    return found


SEARCHES = {
    "unsplash": search_unsplash,
    "pexels": search_pexels,
    "pixabay": search_pixabay,
    "freepik": search_freepik,
}


def search_one(provider: str, query: str, per_page: int, page: int, orientation: str) -> list:
    about = PROVIDERS[provider]
    count = max(1, min(per_page, about["max_per_page"]))
    return SEARCHES[provider](setting(about["key"]), query, count, page, orientation)


def search_all(providers: list, query: str, per_page: int, page: int, orientation: str) -> tuple:
    """Every given provider at once; one that fails is said and the others still answer."""
    found, failed = {}, {}

    def ask(provider: str) -> None:
        try:
            found[provider] = search_one(provider, query, per_page, page, orientation)
        except StockRefused as refusal:
            failed[provider] = str(refusal)
        except Exception as error:  # A provider's surprise stays its own.
            failed[provider] = f"{PROVIDERS[provider]['label']} failed ({type(error).__name__})."

    threads = [
        threading.Thread(target=ask, args=(provider,), daemon=True) for provider in providers
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout_seconds() + 2)
    for provider in providers:
        if provider not in found and provider not in failed:
            failed[provider] = f"{PROVIDERS[provider]['label']} did not answer in time."
    # One result of each provider in turn, so that none is pushed out of sight.
    merged, rank = [], 0
    while any(rank < len(found.get(provider, [])) for provider in providers):
        merged.extend(
            found[provider][rank] for provider in providers if rank < len(found.get(provider, []))
        )
        rank += 1
    return merged, failed


def main() -> dict:
    parser = argparse.ArgumentParser(description="Search stock images on the configured providers")
    parser.add_argument("query", help="What to look for, in a few words")
    parser.add_argument(
        "--provider",
        default="",
        help="unsplash, pexels, pixabay, freepik, or all (default: $IMAGE_STOCK_DEFAULT_PROVIDER, else all)",
    )
    parser.add_argument(
        "--per-page",
        "--per_page",
        dest="per_page",
        type=int,
        default=5,
        help="Results per provider, 1 to 30 (default 5)",
    )
    parser.add_argument("--page", type=int, default=1, help="The page of results (default 1)")
    parser.add_argument(
        "--orientation", default="", help="landscape, portrait or square (default: any)"
    )
    args = parser.parse_args()
    query = clean(args.query)
    if not query:
        raise StockRefused("say what to look for: the query is empty.")
    orientation = (args.orientation or "").strip().lower()
    if orientation in ("any", "all"):
        orientation = ""
    if orientation and orientation not in ORIENTATIONS:
        raise StockRefused(f"orientation is one of {', '.join(ORIENTATIONS)}.")
    per_page, page = max(1, min(args.per_page, 30)), max(1, args.page)
    offered = configured()
    if not offered:
        raise StockRefused(
            "no stock image provider is configured: set one of "
            + ", ".join(about["key"] for about in PROVIDERS.values())
            + "."
        )
    wanted = (args.provider or "").strip().lower()
    if not wanted:
        # The person's usual provider when it is configured here, else all of them.
        usual = setting("IMAGE_STOCK_DEFAULT_PROVIDER").lower()
        wanted = usual if usual in offered else "all"
    if wanted == "all":
        providers = offered
        results, failed = search_all(providers, query, per_page, page, orientation)
        if failed and len(failed) == len(providers):
            raise StockRefused(" ".join(failed[provider] for provider in providers))
    else:
        providers = [provider_named(wanted)]
        results, failed = search_one(providers[0], query, per_page, page, orientation), {}
    return {
        "query": query,
        "page": page,
        "providers": providers,
        "count": len(results),
        "results": results,
        "failed": failed,
        "terms": {provider: PROVIDERS[provider]["terms"] for provider in providers},
    }


if __name__ == "__main__":
    run(main)
