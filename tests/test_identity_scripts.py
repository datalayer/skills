# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""The whoami and events scripts against a fake runtime, run as the sandbox runs them.

No key is in the environment: each script asks the runtime on the loopback
(``/api/v1/owner``, ``/api/v1/owner/events``), and says the runtime's sentence
when it runs for nobody.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

SKILLS = Path(__file__).resolve().parents[1] / "datalayer_skills" / "skills"
WHOAMI = SKILLS / "whoami" / "scripts" / "whoami.py"
EVENT = SKILLS / "events" / "scripts" / "event.py"

PROFILE = {
    "handle": "ada",
    "email": "ada@example.org",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "uid": "u-1",
    "roles": ["platform_member"],
    "avatar_url": "https://example.org/ada.png",
}

NOBODY = (
    "This runtime runs for nobody: it holds no identity of a Datalayer account. "
    "Sign in and start it from your account."
)


class FakeOwner:
    """What agent-runtimes answers under ``/api/v1/owner``, and what it was sent."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, list[str]], Any, dict[str, str]]] = []
        self.nobody = False
        self.events: dict[str, dict[str, Any]] = {}

    def answer(self, method: str, url: str, body: Any, headers: dict[str, str]):
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.requests.append((method, parsed.path, query, body, headers))
        if self.nobody:
            return 409, {"detail": NOBODY}
        if parsed.path == "/api/v1/owner" and method == "GET":
            return 200, PROFILE
        if parsed.path == "/api/v1/owner/events" and method == "POST":
            event = {"id": f"evt-{len(self.events) + 1}", **body}
            self.events[event["id"]] = event
            return 200, {"event": event}
        if parsed.path == "/api/v1/owner/events" and method == "GET":
            return 200, {"total": len(self.events), "events": list(self.events.values())}
        if parsed.path.startswith("/api/v1/owner/events/"):
            event = self.events.get(parsed.path.rsplit("/", 1)[1])
            if event is None:
                return 404, {"detail": "Event not found"}
            if method == "PATCH":
                event.update({k: v for k, v in body.items() if k != "agent_id"})
            return 200, {"event": event}
        return 404, {"detail": "Not Found"}


@pytest.fixture
def owner(monkeypatch: pytest.MonkeyPatch):
    """A fake runtime on a free loopback port, and an environment with no key."""
    fake = FakeOwner()

    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            status, answer = fake.answer(
                self.command,
                self.path,
                json.loads(raw) if raw else None,
                {key.lower(): value for key, value in self.headers.items()},
            )
            data = json.dumps(answer).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PATCH = _serve

        def log_message(self, *args: Any) -> None:  # quiet
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("AGENT_RUNTIMES_URL", f"http://127.0.0.1:{server.server_address[1]}")
    for name in ("AGENT_RUNTIMES_AGENT_ID", "DATALAYER_API_KEY", "DATALAYER_RUN_URL"):
        monkeypatch.delenv(name, raising=False)
    try:
        yield fake
    finally:
        server.shutdown()


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        check=False,
        text=True,
        env=dict(os.environ),
        timeout=60,
    )


def ok(script: Path, *args: str) -> Any:
    done = run(script, *args)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# ---- whoami ----------------------------------------------------------------------------------


def test_whoami_asks_the_runtime_and_holds_no_key(owner) -> None:
    assert ok(WHOAMI) == PROFILE
    method, path, query, _, headers = owner.requests[-1]
    assert (method, path, query) == ("GET", "/api/v1/owner", {})
    assert "authorization" not in headers


def test_whoami_names_the_agent_that_asks(owner, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_RUNTIMES_AGENT_ID", "shopper")
    ok(WHOAMI)
    assert owner.requests[-1][2] == {"agent": ["shopper"]}
    ok(WHOAMI, "--agent", "traveller")
    assert owner.requests[-1][2] == {"agent": ["traveller"]}


def test_whoami_says_the_runtimes_sentence_when_it_runs_for_nobody(owner) -> None:
    owner.nobody = True
    done = run(WHOAMI)
    assert done.returncode == 1
    assert done.stderr.strip() == f"Error: {NOBODY}"
    assert done.stdout == ""


def test_whoami_without_a_runtime_or_a_key_says_what_to_do(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_RUNTIMES_URL", "http://127.0.0.1:9")
    for name in ("DATALAYER_API_KEY", "DATALAYER_RUN_URL"):
        monkeypatch.delenv(name, raising=False)
    done = run(WHOAMI)
    assert done.returncode == 1
    assert "cannot be reached" in done.stderr and "--api-key" in done.stderr


def test_whoami_with_a_key_asks_the_platform_itself(owner, monkeypatch) -> None:
    """By hand outside a runtime: the key and its platform, and the runtime is not asked."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("whoami_script", WHOAMI)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(module, "whoami", lambda url, key: asked.append((url, key)) or PROFILE)
    said = module.main(["--run-url", "https://example.datalayer.run", "--api-key", "k"])
    assert said == PROFILE and asked == [("https://example.datalayer.run", "k")]
    assert owner.requests == []
    # A key with no platform named is no way to ask IAM: the runtime is asked.
    assert module.main(["--api-key", "k"]) == PROFILE
    assert len(owner.requests) == 1 and asked == [("https://example.datalayer.run", "k")]


# ---- events ----------------------------------------------------------------------------------


def test_events_are_created_read_listed_and_updated_through_the_runtime(owner) -> None:
    created = ok(
        EVENT,
        "create",
        "--agent-id",
        "data-acquisition",
        "--title",
        "New dataset",
        "--kind",
        "dataset_ingested",
        "--payload",
        '{"dataset": "imerg"}',
    )
    assert created["id"] == "evt-1" and created["title"] == "New dataset"
    method, path, _, body, headers = owner.requests[-1]
    assert (method, path) == ("POST", "/api/v1/owner/events")
    assert body == {
        "agent_id": "data-acquisition",
        "title": "New dataset",
        "kind": "dataset_ingested",
        "status": "pending",
        "payload": {"dataset": "imerg"},
        "metadata": {},
    }
    assert "authorization" not in headers

    assert ok(EVENT, "get", "evt-1")["title"] == "New dataset"
    assert owner.requests[-1][:3] == ("GET", "/api/v1/owner/events/evt-1", {})

    listed = ok(EVENT, "list", "--agent_id", "data-acquisition", "--status", "pending")
    assert listed["total"] == 1
    assert owner.requests[-1][2] == {
        "limit": ["50"],
        "offset": ["0"],
        "status": ["pending"],
        "agent_id": ["data-acquisition"],
    }

    updated = ok(EVENT, "update", "evt-1", "--status", "completed")
    assert updated["status"] == "completed"
    assert owner.requests[-1][0] == "PATCH" and owner.requests[-1][3] == {"status": "completed"}


def test_events_say_the_runtimes_sentence(owner) -> None:
    missing = run(EVENT, "get", "evt-9")
    assert missing.returncode == 1 and missing.stderr.strip() == "Error: Event not found"
    owner.nobody = True
    refused = run(EVENT, "list")
    assert refused.returncode == 1 and refused.stderr.strip() == f"Error: {NOBODY}"


def test_events_with_a_key_call_the_events_api_by_agent(owner, monkeypatch) -> None:
    """By hand outside a runtime: the key goes to AI Agents, at the agent's events."""
    monkeypatch.setenv("DATALAYER_API_KEY", "k")
    monkeypatch.setenv("DATALAYER_AI_AGENTS_URL", os.environ["AGENT_RUNTIMES_URL"])
    done = run(EVENT, "list", "--agent-id", "data acquisition")
    # The fake runtime is no events API: what matters is where the key was sent.
    assert done.returncode == 1
    method, path, _, _, headers = owner.requests[-1]
    assert (method, path) == ("GET", "/api/ai-agents/v1/agents/data%20acquisition/events")
    assert headers["authorization"] == "Bearer k"
    unnamed = run(EVENT, "get", "evt-1")
    assert unnamed.returncode == 1 and "--agent-id" in unnamed.stderr


def test_neither_skill_requires_a_variable_of_the_sandbox() -> None:
    for skill in ("whoami", "events"):
        front = (SKILLS / skill / "SKILL.md").read_text().split("---")[1]
        assert "required:" not in front, skill
        assert "DATALAYER_API_KEY" in front, skill


# ---- a key goes to one host, and a failure is a sentence (review of 0.7.10) --------------------


class _Recorder:
    """A local server: what it was sent, and what it answers."""

    def __init__(self, respond) -> None:
        self.seen: list[dict[str, str]] = []
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                recorder.seen.append({key.lower(): value for key, value in self.headers.items()})
                respond(self)

            do_GET = do_POST = do_PATCH = _serve

            def log_message(self, *args: Any) -> None:  # quiet
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()


def _json(handler, status: int, body: dict) -> None:
    data = json.dumps(body).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


@pytest.fixture
def two_servers():
    """A server that redirects every request to a second one, which records what reaches it."""
    second = _Recorder(lambda handler: _json(handler, 200, {"event": {"id": "stolen"}, **PROFILE}))

    def redirect(handler) -> None:
        handler.send_response(307)
        handler.send_header("Location", second.url + handler.path)
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    first = _Recorder(redirect)
    try:
        yield first, second
    finally:
        first.close()
        second.close()


def test_a_keyed_events_request_follows_no_redirect(two_servers, monkeypatch) -> None:
    """The key was sent to the first host: it reaches no other, whatever that host answers."""
    first, second = two_servers
    monkeypatch.setenv("DATALAYER_API_KEY", "the-key")
    monkeypatch.setenv("DATALAYER_AI_AGENTS_URL", first.url)
    for args in (
        ("list", "--agent-id", "a"),
        ("get", "evt-1", "--agent-id", "a"),
        ("create", "--agent-id", "a", "--title", "t"),
        ("update", "evt-1", "--agent-id", "a", "--status", "completed"),
    ):
        done = run(EVENT, *args)
        assert done.returncode == 1, args
        assert "redirect" in done.stderr and "not followed" in done.stderr, done.stderr
        assert "the-key" not in done.stderr and "Traceback" not in done.stderr
    assert len(first.seen) == 4 and all(h["authorization"] == "Bearer the-key" for h in first.seen)
    assert second.seen == []


def test_a_runtime_call_follows_no_redirect_either(two_servers, monkeypatch) -> None:
    first, second = two_servers
    monkeypatch.setenv("AGENT_RUNTIMES_URL", first.url)
    for name in ("DATALAYER_API_KEY", "DATALAYER_RUN_URL", "AGENT_RUNTIMES_AGENT_ID"):
        monkeypatch.delenv(name, raising=False)
    for script, args in ((WHOAMI, ()), (EVENT, ("list",))):
        done = run(script, *args)
        assert done.returncode == 1 and "not followed" in done.stderr, done.stderr
        assert "Traceback" not in done.stderr
    assert second.seen == []


def test_a_key_is_never_sent_over_plain_http_to_another_machine(monkeypatch) -> None:
    monkeypatch.setenv("DATALAYER_API_KEY", "the-key")
    monkeypatch.setenv("DATALAYER_AI_AGENTS_URL", "http://ai-agents.example")
    done = run(EVENT, "list", "--agent-id", "a")
    assert done.returncode == 1
    assert "is not sent over http" in done.stderr and "https://" in done.stderr
    assert "the-key" not in done.stderr


def _stalled(handler) -> None:
    import time

    time.sleep(3)


def _cut_short(handler) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", "500")
    handler.end_headers()
    handler.wfile.write(b'{"event": ')
    handler.wfile.flush()
    handler.connection.close()


def _cut_short_refusal(handler) -> None:
    handler.send_response(409)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", "500")
    handler.end_headers()
    handler.wfile.write(b'{"detail": ')
    handler.wfile.flush()
    handler.connection.close()


@pytest.mark.parametrize("respond", [_stalled, _cut_short, _cut_short_refusal])
def test_a_stalled_or_truncated_answer_is_a_sentence_never_a_traceback(
    respond, monkeypatch
) -> None:
    server = _Recorder(respond)
    try:
        monkeypatch.setenv("AGENT_RUNTIMES_URL", server.url)
        monkeypatch.setenv("DATALAYER_EVENTS_TIMEOUT_SECONDS", "1")
        monkeypatch.setenv("DATALAYER_WHOAMI_TIMEOUT_SECONDS", "1")
        for name in ("DATALAYER_API_KEY", "DATALAYER_RUN_URL", "AGENT_RUNTIMES_AGENT_ID"):
            monkeypatch.delenv(name, raising=False)
        who = run(WHOAMI)
        assert who.returncode == 1 and who.stderr.startswith("Error: "), who.stderr
        assert "Traceback" not in who.stderr
        read = run(EVENT, "list")
        assert read.returncode == 1 and read.stderr.startswith("Error: "), read.stderr
        assert "Traceback" not in read.stderr and "may already" not in read.stderr
        # A write whose answer never came may have been made: said, and not sent again.
        before = len(server.seen)
        for args in (
            ("create", "--agent-id", "a", "--title", "t"),
            ("update", "evt-1", "--status", "completed"),
        ):
            wrote = run(EVENT, *args)
            assert wrote.returncode == 1 and "Traceback" not in wrote.stderr, wrote.stderr
            assert "may already have been" in wrote.stderr, wrote.stderr
        assert len(server.seen) == before + 2
    finally:
        server.close()


def test_every_script_that_sends_a_credential_follows_no_redirect() -> None:
    """Each script is its own file in the sandbox: each one that puts a key in a header with
    urllib builds its opener with a handler that follows no redirect."""
    import re

    keyed = re.compile(r"Authorization|api-key|Bearer |Client-ID ")
    checked = []
    for script in sorted(SKILLS.glob("*/scripts/*.py")):
        text = script.read_text()
        if "urllib.request" not in text or not keyed.search(text):
            continue
        checked.append(script.parent.parent.name)
        assert "HTTPRedirectHandler" in text, script
        for found in re.finditer(r"build_opener\(", text):
            opener = text[found.end() : found.end() + 200].split("\n\n")[0]
            assert re.search(r"NoRedirect|handlers|Checked", opener), (script, opener)
    assert "events" in checked and "image_stock" in checked
