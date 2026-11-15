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
import json
import os
import sys
import urllib.error
import urllib.request

#: The runtime's route that mails the person it runs for.
ROUTE = "/api/v1/configure/mail"
MAX_SUBJECT = 150
MAX_TEXT = 20_000


class MailRefused(Exception):
    """Why the mail was not sent, in the runtime's or Datalayer's sentence."""


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
        with opener.open(request, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            detail = json.loads(raw or b"{}").get("detail") or ""
        except ValueError:
            detail = raw.decode(errors="replace").strip()
        if not isinstance(detail, str):
            detail = json.dumps(detail)
        raise MailRefused(
            detail or f"The runtime answered {error.code}; nothing was sent."
        ) from error
    except urllib.error.URLError as error:
        raise MailRefused(
            f"The agent runtime at {base} cannot be reached: {error.reason}. Nothing was sent."
        ) from error
    answer = json.loads(raw or b"{}")
    return {"sent": bool(answer.get("sent")), "to": answer.get("to", "me")}


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
