# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Keep a file in the person's Datalayer Space: a video, a GIF, a thumbnail.

Sends the file to the agent runtime's ``POST /api/v1/spaces/files`` on the pod's
loopback. The runtime keeps it with the identity it holds for the person whose
runtime it is, in a Dataset of their Space (``Videos`` when unsaid), listed on
the Space's page under Contents: the script names no token and can reach no one
else's Space. The local file stays where it is.

Usage:
    python save_to_space.py <file> [--name NAME] [--folder FOLDER] [--space SPACE]
        [--collection DATASET] [--runtime-url URL]
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys

# ---- The Space (the same block in save_to_space and record_and_zoom) ----
#
# A skill script is sent to the sandbox as its own source and run there, so it
# imports nothing of this package: this block is repeated in each script that
# keeps a file in the Space, and a test holds the copies identical.

SPACE_FILES_API = "/api/v1/spaces/files"
SPACE_COLLECTION = "Videos"


class SpaceRefused(Exception):
    """Why the file was not kept in the Space, in the runtime's sentence."""


def runtime_url(explicit=""):
    """The agent runtime's URL: given, AGENT_RUNTIMES_URL, else its port on the loopback."""
    import os

    url = (explicit or os.environ.get("AGENT_RUNTIMES_URL", "")).strip()
    if not url:
        port = os.environ.get("AGENT_RUNTIMES_PORT", "").strip() or "8765"
        url = f"http://127.0.0.1:{port}"
    return url.rstrip("/")


def save_to_space(
    path, name="", folder="", space="", collection=SPACE_COLLECTION, runtime="", timeout=600
):
    """Send the file to the runtime, which keeps it in the person's Space; its answer."""
    import mimetypes
    import os
    import urllib.error
    import urllib.parse
    import urllib.request

    if not os.path.isfile(path):
        raise SpaceRefused(f"There is no file at {path}.")
    size = os.path.getsize(path)
    if size == 0:
        raise SpaceRefused(f"{path} is empty: nothing to keep.")
    name = name or os.path.basename(path)
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    query = {"name": name, "folder": folder, "collection": collection, "media_type": media_type}
    if space:
        query["space"] = space
    base = runtime_url(runtime)
    url = f"{base}{SPACE_FILES_API}?{urllib.parse.urlencode(query)}"
    # Never through a proxy: the runtime is in this pod.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with open(path, "rb") as stream:
        request = urllib.request.Request(
            url,
            data=stream,
            method="POST",
            headers={
                "Content-Type": media_type,
                "Content-Length": str(size),
                "Accept": "application/json",
            },
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                detail = json.loads(raw or b"{}").get("detail") or ""
            except ValueError:
                detail = raw.decode(errors="replace").strip()
            if not isinstance(detail, str):
                detail = json.dumps(detail)
            raise SpaceRefused(detail or f"The runtime answered {error.code}.") from error
        except urllib.error.URLError as error:
            raise SpaceRefused(
                f"The agent runtime at {base} cannot be reached: {error.reason}."
            ) from error
        except (OSError, http.client.HTTPException) as error:
            # A runtime that stalls while answering, or drops the connection before
            # it does (TimeoutError, RemoteDisconnected, IncompleteRead): refused
            # like any other, so the local file is kept and said.
            raise SpaceRefused(
                f"The agent runtime at {base} did not answer: {type(error).__name__}."
            ) from error
    try:
        return json.loads(raw or b"{}")
    except ValueError as error:
        raise SpaceRefused(
            f"The agent runtime at {base} answered something that is not JSON."
        ) from error


# ---- End of the Space ----


def main():
    parser = argparse.ArgumentParser(description="Keep a file in the person's Datalayer Space.")
    parser.add_argument("file", help="the file to keep")
    parser.add_argument("--name", default="", help="its name in the Space (its own when unsaid)")
    parser.add_argument(
        "--folder", default="", help="a folder in the Dataset (its root when unsaid)"
    )
    parser.add_argument(
        "--space", default="", help="a Space's uid or handle (the default Space when unsaid)"
    )
    parser.add_argument(
        "--collection",
        default=SPACE_COLLECTION,
        help=f"the Dataset of the Space it goes in ({SPACE_COLLECTION} when unsaid)",
    )
    parser.add_argument(
        "--runtime-url",
        "--runtime_url",
        dest="runtime_url",
        default="",
        help="the agent runtime (default: $AGENT_RUNTIMES_URL, else http://127.0.0.1:8765)",
    )
    options = parser.parse_args()
    try:
        saved = save_to_space(
            options.file,
            options.name,
            options.folder,
            options.space,
            options.collection,
            options.runtime_url,
        )
    except SpaceRefused as refused:
        print(f"Error: {refused} The file is still at {options.file}.", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(saved, indent=2))


if __name__ == "__main__":
    main()
