# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Forget one memory of the person, by its id.

Calls the agent runtime's ``DELETE /api/v1/agents/{agent}/memory/{id}``. An id
that is not one of this agent's memories of the runtime owner is not found:
the id alone never reaches across the scope.

Usage:
    python delete.py --id MEMORY_ID [--agent NAME] [--runtime-url URL]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# ---- The runtime's memory API (the same block in every memory script) ----
#
# A skill script is sent to the sandbox as its own source and run there, so
# it imports nothing of this package: this block is repeated in each script,
# and a test holds the copies identical.

API = "/api/v1/agents"


class MemoryRefused(Exception):
    """What the runtime answered instead of the memory, in its sentence."""


def runtime_url(explicit: str = "") -> str:
    """The agent runtime's URL: given, AGENT_RUNTIMES_URL, else its port on the loopback."""
    url = (explicit or os.environ.get("AGENT_RUNTIMES_URL", "")).strip()
    if not url:
        port = os.environ.get("AGENT_RUNTIMES_PORT", "").strip() or "8765"
        url = f"http://127.0.0.1:{port}"
    return url.rstrip("/")


def call(method: str, url: str, body: dict | None = None) -> dict:
    """One request to the runtime, never through a proxy: it runs in this pod."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            detail = json.loads(raw or b"{}").get("detail") or ""
        except ValueError:
            detail = raw.decode(errors="replace").strip()
        if not isinstance(detail, str):
            detail = json.dumps(detail)
        raise MemoryRefused(detail or f"The runtime answered {error.code}.") from error
    except urllib.error.URLError as error:
        raise MemoryRefused(
            f"The agent runtime at {url.split('/api/')[0]} cannot be reached: {error.reason}."
        ) from error
    return json.loads(raw or b"{}")


def agent_name(base: str, explicit: str = "") -> str:
    """The agent whose memory this is: given, AGENT_RUNTIMES_AGENT_ID, else the runtime's only agent."""
    name = (explicit or os.environ.get("AGENT_RUNTIMES_AGENT_ID", "")).strip()
    if name:
        return name
    agents = call("GET", f"{base}{API}").get("agents") or []
    ids = [str(agent.get("id")) for agent in agents if isinstance(agent, dict) and agent.get("id")]
    if len(ids) == 1:
        return ids[0]
    if not ids:
        raise MemoryRefused("No agent runs on this runtime: there is no memory to reach.")
    raise MemoryRefused(
        f"Several agents run on this runtime ({', '.join(sorted(ids))}): say which with --agent."
    )


def memory_url(base: str, agent: str, suffix: str = "") -> str:
    """The URL of the agent's memory, or of what is under it."""
    return f"{base}{API}/{urllib.parse.quote(agent, safe='')}/memory{suffix}"


def common_arguments(parser: argparse.ArgumentParser) -> None:
    """The runtime and the agent, both found on their own when not given."""
    parser.add_argument(
        "--agent",
        default="",
        help="The agent's name on the runtime (default: $AGENT_RUNTIMES_AGENT_ID, else its only agent)",
    )
    parser.add_argument(
        "--runtime-url",
        "--runtime_url",
        dest="runtime_url",
        default="",
        help="The agent runtime (default: $AGENT_RUNTIMES_URL, else http://127.0.0.1:8765)",
    )


def run(main) -> None:
    """Run ``main``, printing its JSON; a refusal is said on stderr with exit code 1."""
    try:
        print(json.dumps(main(), indent=2, default=str))
    except MemoryRefused as refusal:
        print(f"Error: {refusal}", file=sys.stderr)
        sys.exit(1)


# ---- End of the runtime's memory API ----


def main() -> dict:
    parser = argparse.ArgumentParser(description="Forget one memory of the person")
    parser.add_argument(
        "--id", required=True, help="The memory's id, as the list or search skill gives it"
    )
    common_arguments(parser)
    args = parser.parse_args()
    base = runtime_url(args.runtime_url)
    agent = agent_name(base, args.agent)
    suffix = "/" + urllib.parse.quote(args.id, safe="")
    forgotten = call("DELETE", memory_url(base, agent, suffix))
    return {"agent": agent, "id": args.id, "forgotten": forgotten.get("forgotten", 0)}


if __name__ == "__main__":
    run(main)
