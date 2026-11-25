# Copyright (c) 2025-2026 Datalayer, Inc.
# BSD 3-Clause License

"""Publish one owned artifact through the agent runtime's loopback route."""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def runtime_url(explicit: str = "") -> str:
    value = (explicit or os.environ.get("AGENT_RUNTIMES_URL", "")).strip()
    if not value:
        port = os.environ.get("AGENT_RUNTIMES_PORT", "").strip() or "8765"
        value = f"http://127.0.0.1:{port}"
    return value.rstrip("/")


def publish_item(
    item_uid: str,
    item_type: str,
    *,
    confirm: bool,
    tags: list[str] | None = None,
    description: str | None = None,
    video: bool = False,
    runtime: str = "",
) -> dict:
    base = runtime_url(runtime)
    uid = urllib.parse.quote(item_uid.strip(), safe="")
    url = f"{base}/api/v1/library/items/{uid}/publish"
    payload = {
        "item_type": item_type,
        "confirm": confirm,
        "tags": tags,
        "description": description,
        "video": video,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=45) as response:
            raw = response.read()
        try:
            answer = json.loads(raw or b"{}")
        except ValueError as error:
            raise http.client.HTTPException("the answer is not JSON") from error
        if not isinstance(answer, dict):
            raise http.client.HTTPException("the answer is not what was asked for")
        return answer
    except urllib.error.HTTPError as error:
        try:
            raw = error.read()
        except (OSError, http.client.HTTPException) as cut:
            raise RuntimeError(
                f"The agent runtime at {base} answered {error.code} and its answer was cut short "
                f"({type(cut).__name__}): the item may be public already. Check its public page "
                "before publishing it again."
            ) from cut
        try:
            detail = json.loads(raw or b"{}").get("detail") or ""
        except ValueError:
            detail = raw.decode(errors="replace").strip()
        if isinstance(detail, dict):
            detail = detail.get("message") or json.dumps(detail)
        raise RuntimeError(detail or f"The runtime answered {error.code}.") from error
    except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
        # A connection never made sent nothing; anything later may have published.
        never_sent = isinstance(getattr(error, "reason", None), ConnectionRefusedError)
        why = (
            f"The agent runtime at {base} cannot be reached: nothing was published."
            if never_sent
            else f"The agent runtime at {base} did not confirm the publication "
            f"({type(error).__name__}): the item may be public already. Check its public page "
            "before publishing it again."
        )
        raise RuntimeError(why) from error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish an owned item in Datalayer's public Library."
    )
    parser.add_argument("item_uid")
    parser.add_argument("item_type")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--tag", action="append", default=None, dest="tags")
    parser.add_argument("--description", default=None)
    parser.add_argument("--video", action="store_true")
    parser.add_argument("--runtime-url", default="")
    options = parser.parse_args()
    try:
        answer = publish_item(
            options.item_uid,
            options.item_type,
            confirm=options.confirm,
            tags=options.tags,
            description=options.description,
            video=options.video,
            runtime=options.runtime_url,
        )
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    print(json.dumps(answer, indent=2))


if __name__ == "__main__":
    main()
