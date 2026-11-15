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
import time
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


#: The script's wait for the runtime in these tests; the subprocess deadline is far above it.
CLIENT_TIMEOUT = 1.0
SUBPROCESS_DEADLINE = 60


class Mailer:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict]] = []
        self.refusal: tuple[int, str] | None = None
        #: A raw answer (status, body bytes); "drop" closes after the POST arrived,
        #: "slow" sends the headers and holds the body past the client's timeout,
        #: "short" announces more body than it sends, then closes.
        self.raw: tuple[int, bytes] | str | None = None


@pytest.fixture
def mailer():
    state = Mailer()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"
            )
            state.requests.append((self.command, self.path, body))
            if state.raw == "drop":
                self.close_connection = True
                self.connection.shutdown(2)
                return
            if state.raw in ("slow", "short"):
                data = b'{"sent": true, "to": "me"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header(
                    "Content-Length", str(len(data) * (4 if state.raw == "short" else 1))
                )
                self.end_headers()
                self.wfile.flush()
                if state.raw == "slow":
                    time.sleep(CLIENT_TIMEOUT * 3)
                self.wfile.write(data)
                self.wfile.flush()
                self.close_connection = True
                self.connection.shutdown(2)
                return
            if state.raw:
                status, data = state.raw
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
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
        env={**os.environ, "DATALAYER_EMAIL_TIMEOUT_SECONDS": str(CLIENT_TIMEOUT)},
        timeout=SUBPROCESS_DEADLINE,
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


UNCONFIRMED = "Delivery could not be confirmed"
NOT_AGAIN = "Do not send it again"


@pytest.mark.parametrize(
    "raw, why",
    [
        # A gateway's 502 after the runtime may have sent it: no reason given.
        ((502, b"<html>Bad Gateway</html>"), "answered 502 without saying why"),
        ((500, b""), "answered 500 without saying why"),
        # The runtime took the POST and closed the connection.
        ("drop", "connection to the agent runtime ended"),
        # The answer's headers came, its body not within the client's timeout.
        ("slow", "ended before its answer (TimeoutError)"),
        # The body is shorter than its Content-Length says.
        ("short", "ended before its answer (IncompleteRead)"),
        # A success whose body cannot be read.
        ((200, b"{not json"), "is not JSON"),
        ((200, b"null"), "does not say whether it was sent"),
        ((200, b"[]"), "does not say whether it was sent"),
        ((200, b'{"to": "me"}'), "does not say whether it was sent"),
    ],
)
def test_an_unconfirmed_delivery_is_said_without_a_traceback_and_never_retried(
    mailer, raw, why
) -> None:
    mailer.raw = raw
    done = run("--subject", "s", "--text", "t")
    assert done.returncode == 3, done.stderr
    assert "Traceback" not in done.stderr
    assert done.stderr.startswith(f"Error: {UNCONFIRMED}")
    assert why in done.stderr and NOT_AGAIN in done.stderr
    assert "Nothing was sent" not in done.stderr
    assert len(mailer.requests) == 1


def test_a_runtime_that_says_not_sent_is_a_refusal(mailer) -> None:
    mailer.raw = (200, b'{"sent": false}')
    done = run("--subject", "s", "--text", "t")
    assert done.returncode == 1 and "was not sent" in done.stderr


def test_there_is_no_recipient_argument() -> None:
    done = run("--subject", "s", "--text", "t", "--to", "bob@example.com")
    assert done.returncode == 2


def test_agent_skills_discovers_it_with_its_script_and_no_secret() -> None:
    skill = {skill.name: skill for skill in discover_entrypoint_skills()}["datalayer-email"]
    assert [script.name for script in skill.scripts] == ["send_email"]
    assert skill.get_required_env_vars() == []
    assert "email" in skill.tags
