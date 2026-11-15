# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""The email skill against a fake runtime, run as the sandbox runs it: a process of its own.

The runtime's ``POST /api/v1/configure/mail`` mails the person it runs for
through Datalayer's mailer (agent-runtimes 1.6.65, IAM's ``/social/mail``);
the script names no address and holds no mail credential.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from agent_skills import discover_entrypoint_skills

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "datalayer_skills"
    / "skills"
    / "email"
    / "scripts"
    / "send_email.py"
)


class Mailer:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.refusal: tuple[int, str] | None = None


@pytest.fixture
def mailer():
    state = Mailer()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"
            )
            state.requests.append((self.command, self.path, body))
            status, answer = (
                (state.refusal[0], {"detail": state.refusal[1]})
                if state.refusal
                else (200, {"sent": True, "to": "me"})
                if self.path == "/api/v1/configure/mail"
                else (404, {"detail": "Not Found"})
            )
            data = json.dumps(answer).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["AGENT_RUNTIMES_URL"] = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield state
    finally:
        os.environ.pop("AGENT_RUNTIMES_URL", None)
        server.shutdown()


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        check=False,
        text=True,
        env=dict(os.environ),
        timeout=60,
    )


def test_it_asks_the_runtime_to_mail_the_person_and_names_no_address(mailer) -> None:
    done = run("--subject", "Your week on X", "--text", "Three posts.\n\nTwelve replies.")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"sent": True, "to": "me"}
    assert mailer.requests == [
        (
            "POST",
            "/api/v1/configure/mail",
            {"subject": "Your week on X", "text": "Three posts.\n\nTwelve replies."},
        )
    ]


@pytest.mark.parametrize(
    "args, said",
    [
        (("--subject", " ", "--text", "t"), "a subject and some text"),
        (("--subject", "s" * 151, "--text", "t"), "at most 150"),
    ],
)
def test_what_it_cannot_send_asks_nothing(mailer, args, said) -> None:
    done = run(*args)
    assert done.returncode == 1 and said in done.stderr
    assert mailer.requests == []


def test_a_refusal_is_said_in_its_sentence(mailer) -> None:
    mailer.refusal = (
        409,
        "No more mail today: Datalayer sends at most 10 a day for one person's agents. Try again tomorrow.",
    )
    done = run("--subject", "s", "--text", "t")
    assert done.returncode == 1
    assert (
        done.stderr.strip()
        == "Error: No more mail today: Datalayer sends at most 10 a day for one person's agents. Try again tomorrow."
    )


def test_an_unreachable_runtime_is_said(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_RUNTIMES_URL", "http://127.0.0.1:9")
    done = run("--subject", "s", "--text", "t")
    assert (
        done.returncode == 1
        and "cannot be reached" in done.stderr
        and "Nothing was sent" in done.stderr
    )


def test_there_is_no_recipient_argument() -> None:
    done = run("--subject", "s", "--text", "t", "--to", "bob@example.com")
    assert done.returncode == 2


def test_agent_skills_discovers_it_with_its_script_and_no_secret() -> None:
    skill = {skill.name: skill for skill in discover_entrypoint_skills()}["datalayer-email"]
    assert [script.name for script in skill.scripts] == ["send_email"]
    assert skill.get_required_env_vars() == []
    assert "email" in skill.tags
