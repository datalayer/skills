# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Send the person whose agent this is one email, through Datalayer's mailer.

The script asks the agent runtime it runs beside (``POST /api/v1/configure/mail``);
the runtime sends it with its own short-lived token through Datalayer's IAM,
to the person alone. No address is named here and no mail credential is used.

Usage:
    python send_email.py --subject "Your week on X" --text "Three posts went out..." [--runtime-url URL]
"""

from __future__ import annotations

import argparse
import errno
import http.client
import json
import os
import sys
import urllib.error
import urllib.request

#: The runtime's route that mails the person it runs for.
ROUTE = "/api/v1/configure/mail"
MAX_SUBJECT = 150
MAX_TEXT = 20_000


def timeout_seconds() -> float:
    """How long to wait for the runtime: $DATALAYER_EMAIL_TIMEOUT_SECONDS, else 60."""
    raw = os.environ.get("DATALAYER_EMAIL_TIMEOUT_SECONDS", "").strip()
    return float(raw) if raw else 60.0


class MailRefused(Exception):
    """Why the mail was not sent, in the runtime's or Datalayer's sentence."""


class MailUnconfirmed(Exception):
    """The runtime may have sent the mail, but did not confirm it either way.

    A gateway can answer 502 after the runtime sent the mail, the connection
    can drop after the POST arrived, an answer can be cut short: none of these
    proves nothing was sent, so none is a refusal, and the mail is never sent
    again on its own.
    """


#: Said after every unconfirmed outcome, so the agent does not send it twice.
UNCONFIRMED = (
    "The mail may have been sent. Do not send it again; "
    "tell the person and let them check their inbox."
)

#: Connection errors that happen before the request reaches the runtime.
NOT_CONNECTED = (ConnectionRefusedError,)


def _unconfirmed(why: str) -> MailUnconfirmed:
    return MailUnconfirmed(f"Delivery could not be confirmed: {why}. {UNCONFIRMED}")


def runtime_url(explicit: str = "") -> str:
    """The agent runtime's URL: given, AGENT_RUNTIMES_URL, else its port on the loopback."""
    url = (explicit or os.environ.get("AGENT_RUNTIMES_URL", "")).strip()
    if not url:
        port = os.environ.get("AGENT_RUNTIMES_PORT", "").strip() or "8765"
        url = f"http://127.0.0.1:{port}"
    return url.rstrip("/")


def send_email(subject: str, text: str, base: str) -> dict:
    """Ask the runtime to send the person one mail; raise ``MailRefused`` with its sentence."""
    subject = " ".join(str(subject or "").split())
    text = str(text or "").strip()
    if not subject or not text:
        raise MailRefused("A mail needs a subject and some text.")
    if len(subject) > MAX_SUBJECT:
        raise MailRefused(f"A mail's subject is at most {MAX_SUBJECT} characters.")
    if len(text) > MAX_TEXT:
        raise MailRefused(f"A mail's text is at most {MAX_TEXT:,} characters.")
    request = urllib.request.Request(
        f"{base}{ROUTE}",
        data=json.dumps({"subject": subject, "text": text}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    # Never through a proxy: the runtime is in this pod.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout_seconds()) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        try:
            raw = error.read()
        except (OSError, http.client.HTTPException):
            raw = b""
        try:
            body = json.loads(raw or b"null")
        except ValueError:
            body = None
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, str) and detail.strip():
            # The runtime's own sentence: a refusal it confirms.
            raise MailRefused(detail.strip()) from error
        raise _unconfirmed(f"the runtime answered {error.code} without saying why") from error
    except urllib.error.URLError as error:
        if (
            isinstance(error.reason, NOT_CONNECTED)
            or getattr(error.reason, "errno", None) == errno.ECONNREFUSED
        ):
            raise MailRefused(
                f"The agent runtime at {base} cannot be reached: {error.reason}. Nothing was sent."
            ) from error
        raise _unconfirmed(
            f"the agent runtime at {base} did not answer ({error.reason})"
        ) from error
    except (OSError, http.client.HTTPException) as error:
        # The connection dropped, timed out or was cut short after the POST left.
        raise _unconfirmed(
            f"the connection to the agent runtime ended before its answer ({type(error).__name__})"
        ) from error
    try:
        answer = json.loads(raw)
    except ValueError as error:
        raise _unconfirmed("the runtime's answer is not JSON") from error
    if not isinstance(answer, dict) or not isinstance(answer.get("sent"), bool):
        raise _unconfirmed("the runtime's answer does not say whether it was sent")
    if not answer["sent"]:
        raise MailRefused("The runtime says the mail was not sent.")
    to = answer.get("to")
    return {"sent": True, "to": to if isinstance(to, str) and to else "me"}


def main() -> dict:
    parser = argparse.ArgumentParser(description="Send the person whose agent this is one email")
    parser.add_argument("--subject", required=True, help="The subject, at most 150 characters")
    parser.add_argument("--text", required=True, help="The body, plain text")
    parser.add_argument(
        "--runtime-url",
        "--runtime_url",
        dest="runtime_url",
        default="",
        help="The agent runtime (default: $AGENT_RUNTIMES_URL, else http://127.0.0.1:8765)",
    )
    args = parser.parse_args()
    return send_email(args.subject, args.text, runtime_url(args.runtime_url))


if __name__ == "__main__":
    try:
        print(json.dumps(main(), indent=2))
    except MailRefused as refusal:
        print(f"Error: {refusal}", file=sys.stderr)
        sys.exit(1)
    except MailUnconfirmed as unconfirmed:
        print(f"Error: {unconfirmed}", file=sys.stderr)
        sys.exit(3)
