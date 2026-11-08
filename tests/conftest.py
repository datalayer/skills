# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""A fake agent runtime: agent-runtimes' memory routes over an in-memory store.

It answers what agent-runtimes answers (``agent_runtimes/routes/agents.py``):
``GET /api/v1/agents``, and under ``/api/v1/agents/{agent}/memory`` the list
(GET), keep (POST), search (POST ``/search``), forget one (DELETE ``/{id}``)
and forget everything up to the confirmed ``count`` (DELETE ``?count=N``).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pytest

PREFIX = "/api/v1/agents"


class FakeRuntime:
    """The runtime's agents, each with its memory, and the requests it was sent."""

    def __init__(self) -> None:
        self.memories: dict[str, list[dict[str, Any]]] = {}
        self.requests: list[tuple[str, str, Any]] = []
        self.refusal: str = ""
        self._next = 0
        self.lock = threading.Lock()

    def agent(self, name: str) -> None:
        self.memories.setdefault(name, [])

    def keep(self, agent: str, content: str, metadata: dict | None = None) -> dict[str, Any]:
        self._next += 1
        entry = {
            "id": f"mem-{self._next}",
            "content": content,
            "score": 0.0,
            "metadata": metadata or {},
            "created_at": f"2026-11-08T00:00:{self._next:02d}Z",
            "updated_at": None,
        }
        self.memories[agent].append(entry)
        return entry

    def answer(self, method: str, url: str, body: Any) -> tuple[int, dict[str, Any]]:
        self.requests.append((method, url, body))
        parsed = urlparse(url)
        path = parsed.path
        if path == PREFIX and method == "GET":
            return 200, {"agents": [{"id": name} for name in self.memories]}
        if not path.startswith(PREFIX + "/"):
            return 404, {"detail": "Not Found"}
        parts = path[len(PREFIX) + 1 :].split("/")
        agent = unquote(parts[0])
        rest = parts[1:]
        if not rest or rest[0] != "memory":
            return 404, {"detail": "Not Found"}
        if agent not in self.memories:
            return 404, {"detail": f"The agent {agent} has no durable memory on this runtime."}
        memories = self.memories[agent]
        if self.refusal:
            return 409, {"detail": self.refusal}
        if rest == ["memory"] and method == "GET":
            return 200, {"memories": sorted(memories, key=lambda e: e["created_at"], reverse=True)}
        if rest == ["memory"] and method == "POST":
            words = " ".join(str(body.get("content", "")).split())
            if not words:
                return 422, {"detail": "A memory says what to remember: it is empty."}
            self.keep(agent, words, body.get("metadata"))
            return 200, {"added": 1, "content": words}
        if rest == ["memory", "search"] and method == "POST":
            query = str(body.get("query", "")).lower()
            found = [e for e in memories if any(w in e["content"].lower() for w in query.split())]
            return 200, {"results": found}
        if len(rest) == 2 and method == "DELETE":
            memory_id = unquote(rest[1])
            kept = [e for e in memories if e["id"] != memory_id]
            if len(kept) == len(memories):
                return 404, {"detail": f"{agent} remembers nothing as {memory_id}."}
            self.memories[agent] = kept
            return 200, {"forgotten": 1}
        if rest == ["memory"] and method == "DELETE":
            counts = parse_qs(parsed.query).get("count")
            if not counts:
                return 422, {"detail": "count is required"}
            count = int(counts[0])
            if len(memories) > count:
                return 409, {
                    "detail": f"It remembers more than the {count} you confirmed now. "
                    "Nothing was forgotten."
                }
            self.memories[agent] = []
            return 200, {"forgotten": len(memories)}
        return 405, {"detail": "Method Not Allowed"}


def _handler(runtime: FakeRuntime) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw else None
            with runtime.lock:
                status, answer = runtime.answer(self.command, self.path, body)
            data = json.dumps(answer).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_DELETE = _serve

        def log_message(self, *args: Any) -> None:  # quiet
            pass

    return Handler


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch):
    """A fake runtime on a free loopback port, named by AGENT_RUNTIMES_URL."""
    fake = FakeRuntime()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake.url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("AGENT_RUNTIMES_URL", fake.url)
    monkeypatch.delenv("AGENT_RUNTIMES_AGENT_ID", raising=False)
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
