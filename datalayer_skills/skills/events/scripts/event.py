# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Executable helper for the events skill.

In a Datalayer runtime the script holds no key: it asks the agent runtime it
runs beside (``/api/v1/owner/events`` on the pod's loopback), which asks
Datalayer's AI Agents events API with the identity it holds for the account
it runs for. No credential reaches the sandbox.

Run by hand outside a runtime, with a key (``DATALAYER_API_KEY``), it calls
``/api/ai-agents/v1/agents/{agent_id}/events`` itself.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

#: The AI Agents events API, by agent.
API_PATH = "/api/ai-agents/v1/agents/{agent_id}/events"

#: The runtime's route for its agent's events.
RUNTIME_ROUTE = "/api/v1/owner/events"

#: Where AI Agents runs when DATALAYER_AI_AGENTS_URL names no other.
DEFAULT_AI_AGENTS_URL = "https://r1.datalayer.run"


class EventsRefused(Exception):
    """Why the events were not reached, in the runtime's or the API's sentence."""


#: The longest a script waits for an answer, in seconds.
MAX_TIMEOUT_SECONDS = 600.0


def timeout_seconds() -> float:
    """How long to wait for an answer: $DATALAYER_EVENTS_TIMEOUT_SECONDS, else 30."""
    raw = os.environ.get("DATALAYER_EVENTS_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 30.0
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 0.0
    if not 0 < seconds <= MAX_TIMEOUT_SECONDS:
        raise EventsRefused(
            f"DATALAYER_EVENTS_TIMEOUT_SECONDS is {raw!r}: give a number of seconds above 0, 600 at most. "
            "Nothing was sent."
        )
    return seconds


def _base_url() -> str:
    return os.environ.get("DATALAYER_AI_AGENTS_URL", DEFAULT_AI_AGENTS_URL).rstrip("/")


def _key() -> str:
    """A key given by hand, ``""`` in a runtime: there the runtime is asked."""
    return os.environ.get("DATALAYER_API_KEY", "").strip()


def runtime_url() -> str:
    """The agent runtime's URL: AGENT_RUNTIMES_URL, else its port on the loopback."""
    url = os.environ.get("AGENT_RUNTIMES_URL", "").strip()
    if not url:
        port = os.environ.get("AGENT_RUNTIMES_PORT", "").strip() or "8765"
        url = f"http://127.0.0.1:{port}"
    return url.rstrip("/")


def _agent(agent_id: str | None) -> str:
    """The agent the events are of: given, else AGENT_RUNTIMES_AGENT_ID, else ``""``."""
    return (agent_id or os.environ.get("AGENT_RUNTIMES_AGENT_ID", "")).strip()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """No request follows a redirect: a key goes to the host it was sent to alone."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).netloc or "another address"
        raise EventsRefused(
            f"{urllib.parse.urlsplit(req.full_url).netloc} answered with a redirect to {host} "
            f"({code}), which is not followed: nothing was sent there."
        )


#: The hosts a request may reach over plain HTTP: this machine alone.
LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _checked(url: str, key: str) -> None:
    """A key travels over HTTPS alone; plain HTTP is for the runtime on the loopback."""
    parts = urllib.parse.urlsplit(url)
    if key and parts.scheme != "https" and (parts.hostname or "") not in LOOPBACK:
        raise EventsRefused(
            f"DATALAYER_API_KEY is not sent over {parts.scheme or 'an unknown scheme'} to "
            f"{parts.netloc}: name an https:// address in DATALAYER_AI_AGENTS_URL."
        )


def _unconfirmed(method: str, why: str) -> EventsRefused:
    """A transport failure, said; a write may have been made all the same."""
    if method in ("POST", "PATCH"):
        return EventsRefused(
            f"{why} The event may already have been "
            f"{'created' if method == 'POST' else 'updated'}: check with `list` or `get` "
            "before doing it again."
        )
    return EventsRefused(why)


def _call(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    key: str = "",
) -> dict[str, Any]:
    """One request, with a key when one is given; a refusal raises ``EventsRefused``.

    Never followed through a redirect, and never retried: a key reaches the
    one host it was sent to, and a write is made once.
    """
    _checked(url, key)
    timeout = timeout_seconds()
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers=headers,
    )
    where = url.split("/api/")[0]
    # The runtime is in this pod: never through a proxy. With a key, as the
    # environment says.
    handlers: list[Any] = [NoRedirect()]
    if not key:
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        try:
            raw = error.read()
        except (OSError, http.client.HTTPException) as cut:
            raise _unconfirmed(
                method,
                f"{where} answered {error.code} and its answer was cut short "
                f"({type(cut).__name__}).",
            ) from cut
        try:
            detail = json.loads(raw or b"{}").get("detail") or ""
        except (ValueError, AttributeError):
            detail = raw.decode(errors="replace").strip()
        if not isinstance(detail, str):
            detail = json.dumps(detail)
        raise EventsRefused(detail or f"The events API answered {error.code}.") from error
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, ConnectionRefusedError):
            # Nothing was sent: the connection was never made.
            if key:
                raise EventsRefused(f"{where} cannot be reached: {reason}.") from error
            raise EventsRefused(
                f"The agent runtime at {where} cannot be reached ({reason}), and no key was "
                "given: run it in a Datalayer runtime, or set DATALAYER_API_KEY."
            ) from error
        raise _unconfirmed(method, f"{where} did not answer ({reason}).") from error
    except (OSError, http.client.HTTPException) as error:
        # A timeout, a dropped connection, an answer cut short.
        raise _unconfirmed(
            method, f"The connection to {where} ended before its answer ({type(error).__name__})."
        ) from error
    try:
        answer = json.loads(raw or b"{}")
    except ValueError as error:
        raise _unconfirmed(method, f"The answer of {where} is not JSON.") from error
    if not isinstance(answer, dict):
        raise _unconfirmed(method, f"The answer of {where} is not what was asked for.")
    return answer


def _event(answer: dict[str, Any], method: str) -> dict[str, Any]:
    """The event of an answer, refused when the answer holds none."""
    event = answer.get("event")
    if not isinstance(event, dict):
        raise _unconfirmed(method, "The answer names no event.")
    return event


def _direct_url(agent_id: str, event_id: str = "") -> str:
    if not agent_id:
        raise EventsRefused(
            "With a key, name the agent the event is of: --agent-id (or AGENT_RUNTIMES_AGENT_ID)."
        )
    url = _base_url() + API_PATH.format(agent_id=urllib.parse.quote(agent_id, safe=""))
    return f"{url}/{urllib.parse.quote(event_id, safe='')}" if event_id else url


def _runtime_event_url(event_id: str = "") -> str:
    url = runtime_url() + RUNTIME_ROUTE
    return f"{url}/{urllib.parse.quote(event_id, safe='')}" if event_id else url


def create_event(
    agent_id: str,
    title: str,
    kind: str = "generic",
    status: str = "pending",
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": title,
        "kind": kind,
        "status": status,
        "payload": payload or {},
        "metadata": metadata or {},
    }
    key = _key()
    if key:
        return _event(_call("POST", _direct_url(_agent(agent_id)), body=body, key=key), "POST")
    return _event(
        _call("POST", _runtime_event_url(), body={**body, "agent_id": _agent(agent_id)}), "POST"
    )


def get_event(event_id: str, agent_id: str | None = None) -> dict[str, Any]:
    key = _key()
    if key:
        return _event(_call("GET", _direct_url(_agent(agent_id), event_id), key=key), "GET")
    agent = _agent(agent_id)
    return _event(
        _call("GET", _runtime_event_url(event_id), params={"agent_id": agent} if agent else None),
        "GET",
    )


def list_events(
    *,
    agent_id: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if kind:
        params["kind"] = kind
    if status:
        params["status"] = status
    key = _key()
    agent = _agent(agent_id)
    if key:
        return _call("GET", _direct_url(agent), params=params, key=key)
    if agent:
        params["agent_id"] = agent
    return _call("GET", _runtime_event_url(), params=params)


def update_event(
    event_id: str,
    *,
    agent_id: str | None = None,
    title: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if title is not None:
        body["title"] = title
    if kind is not None:
        body["kind"] = kind
    if status is not None:
        body["status"] = status
    if payload is not None:
        body["payload"] = payload
    if metadata is not None:
        body["metadata"] = metadata
    key = _key()
    agent = _agent(agent_id)
    if key:
        return _event(_call("PATCH", _direct_url(agent, event_id), body=body, key=key), "PATCH")
    if agent:
        body["agent_id"] = agent
    return _event(_call("PATCH", _runtime_event_url(event_id), body=body), "PATCH")


def _json_arg(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("JSON argument must decode to an object")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Events skill helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create an event")
    create_parser.add_argument("--agent-id", "--agent_id", dest="agent_id", required=True)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--kind", default="generic")
    create_parser.add_argument("--status", default="pending")
    create_parser.add_argument("--payload", default="{}")
    create_parser.add_argument("--metadata", default="{}")

    get_parser = subparsers.add_parser("get", help="Get one event")
    get_parser.add_argument("event_id")
    get_parser.add_argument("--agent-id", "--agent_id", dest="agent_id")

    list_parser = subparsers.add_parser("list", help="List events")
    list_parser.add_argument("--agent-id", "--agent_id", dest="agent_id")
    list_parser.add_argument("--kind")
    list_parser.add_argument("--status")
    list_parser.add_argument("--limit", type=int, default=50)
    list_parser.add_argument("--offset", type=int, default=0)

    update_parser = subparsers.add_parser("update", help="Update one event")
    update_parser.add_argument("event_id")
    update_parser.add_argument("--agent-id", "--agent_id", dest="agent_id")
    update_parser.add_argument("--title")
    update_parser.add_argument("--kind")
    update_parser.add_argument("--status")
    update_parser.add_argument("--payload")
    update_parser.add_argument("--metadata")

    args = parser.parse_args()

    if args.command == "create":
        event = create_event(
            agent_id=args.agent_id,
            title=args.title,
            kind=args.kind,
            status=args.status,
            payload=_json_arg(args.payload),
            metadata=_json_arg(args.metadata),
        )
        print(json.dumps(event, indent=2, sort_keys=True))
        return

    if args.command == "get":
        event = get_event(args.event_id, args.agent_id)
        print(json.dumps(event, indent=2, sort_keys=True))
        return

    if args.command == "list":
        data = list_events(
            agent_id=args.agent_id,
            kind=args.kind,
            status=args.status,
            limit=args.limit,
            offset=args.offset,
        )
        print(json.dumps(data, indent=2, sort_keys=True))
        return

    if args.command == "update":
        event = update_event(
            args.event_id,
            agent_id=args.agent_id,
            title=args.title,
            kind=args.kind,
            status=args.status,
            payload=_json_arg(args.payload) if args.payload is not None else None,
            metadata=_json_arg(args.metadata) if args.metadata is not None else None,
        )
        print(json.dumps(event, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except EventsRefused as refusal:
        print(f"Error: {refusal}", file=sys.stderr)
        sys.exit(1)
