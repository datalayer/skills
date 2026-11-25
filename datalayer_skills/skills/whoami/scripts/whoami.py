# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Whoami script — the profile of the Datalayer account the agent runs for.

In a Datalayer runtime the script holds no key: it asks the agent runtime it
runs beside (``GET /api/v1/owner`` on the pod's loopback), which answers with
the identity it holds for the account it runs for. No credential reaches the
sandbox.

Run by hand outside a runtime, with a key (``--api-key`` or
``DATALAYER_API_KEY``), it asks Datalayer's IAM itself through the
``datalayer_core`` client, as it always did.

Usage:
    python whoami.py                                  # in a runtime
    python whoami.py --run-url URL --api-key KEY      # by hand, with a key

Environment:
    AGENT_RUNTIMES_URL       The agent runtime (default: the loopback).
    AGENT_RUNTIMES_PORT      Its port on the loopback (default 8765).
    AGENT_RUNTIMES_AGENT_ID  Which of the runtime's agents asks.
    DATALAYER_API_KEY        A key, when run by hand outside a runtime.
    DATALAYER_RUN_URL        The platform the key is of.
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

#: The runtime's route that says who it runs for.
ROUTE = "/api/v1/owner"


class WhoamiRefused(Exception):
    """Why nobody was said, in the runtime's sentence."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """The runtime is asked where it is: a redirect elsewhere is not followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = urllib.parse.urlsplit(newurl).netloc or "another address"
        raise WhoamiRefused(
            f"The agent runtime answered with a redirect to {host} ({code}), which is not followed."
        )


def timeout_seconds() -> float:
    """How long to wait for the runtime: $DATALAYER_WHOAMI_TIMEOUT_SECONDS, else 30."""
    raw = os.environ.get("DATALAYER_WHOAMI_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 30.0
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 0.0
    if not 0 < seconds < float("inf"):
        raise WhoamiRefused(
            f"DATALAYER_WHOAMI_TIMEOUT_SECONDS is {raw!r}: give a number of seconds above 0."
        )
    return seconds


def runtime_url(explicit: str = "") -> str:
    """The agent runtime's URL: given, AGENT_RUNTIMES_URL, else its port on the loopback."""
    url = (explicit or os.environ.get("AGENT_RUNTIMES_URL", "")).strip()
    if not url:
        port = os.environ.get("AGENT_RUNTIMES_PORT", "").strip() or "8765"
        url = f"http://127.0.0.1:{port}"
    return url.rstrip("/")


def whoami_from_runtime(base: str, agent: str = "") -> dict:
    """Ask the agent runtime who it runs for; raise ``WhoamiRefused`` with its sentence."""
    agent = (agent or os.environ.get("AGENT_RUNTIMES_AGENT_ID", "")).strip()
    url = f"{base}{ROUTE}"
    if agent:
        url += "?" + urllib.parse.urlencode({"agent": agent})
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    # Never through a proxy, and never through a redirect: the runtime is in this pod.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    timeout = timeout_seconds()
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        try:
            raw = error.read()
        except (OSError, http.client.HTTPException) as cut:
            raise WhoamiRefused(
                f"The agent runtime at {base} answered {error.code} and its answer was cut "
                f"short ({type(cut).__name__})."
            ) from cut
        try:
            detail = json.loads(raw or b"{}").get("detail") or ""
        except (ValueError, AttributeError):
            detail = raw.decode(errors="replace").strip()
        if not isinstance(detail, str):
            detail = json.dumps(detail)
        raise WhoamiRefused(detail or f"The runtime answered {error.code}.") from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, ConnectionRefusedError):
            raise WhoamiRefused(
                f"The agent runtime at {base} cannot be reached ({error.reason}), and no key "
                "was given: run it in a Datalayer runtime, or pass --api-key and --run-url."
            ) from error
        raise WhoamiRefused(
            f"The agent runtime at {base} did not answer ({error.reason})."
        ) from error
    except (OSError, http.client.HTTPException) as error:
        # A timeout, a dropped connection, an answer cut short.
        raise WhoamiRefused(
            f"The connection to the agent runtime at {base} ended before its answer "
            f"({type(error).__name__})."
        ) from error
    try:
        profile = json.loads(raw or b"{}")
    except ValueError as error:
        raise WhoamiRefused("The runtime's answer is not JSON.") from error
    if not isinstance(profile, dict):
        raise WhoamiRefused("The runtime's answer is not a profile.")
    return {
        "handle": profile.get("handle"),
        "email": profile.get("email"),
        "first_name": profile.get("first_name"),
        "last_name": profile.get("last_name"),
        "uid": profile.get("uid"),
        "roles": profile.get("roles") or [],
        "avatar_url": profile.get("avatar_url"),
    }


def whoami(run_url: str, api_key: str) -> dict:
    """Fetch the current user's profile from Datalayer IAM, with a key.

    Uses ``datalayer_core.client.client.DatalayerClient`` to call the
    IAM whoami endpoint.

    Args:
        run_url: Base URL of the Datalayer platform
            (e.g. ``https://prod1.datalayer.run``).
        api_key: API key for IAM authentication.

    Returns:
        Profile dict with keys: handle, email, first_name,
        last_name, uid, roles, avatar_url.
    """
    from datalayer_core.client.client import DatalayerClient
    from datalayer_core.utils.urls import DatalayerURLs

    urls = DatalayerURLs.from_environment(run_url=run_url)
    client = DatalayerClient(urls=urls, token=api_key)
    user = client.get_profile()

    return {
        "handle": user.handle,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "uid": user.uid,
        "roles": user.roles,
        "avatar_url": user.avatar_url_s,
    }


def arguments(argv=None) -> argparse.Namespace:
    """The command line; `run_skill_script` sends its kwargs with underscores (`--run_url`)."""
    parser = argparse.ArgumentParser(description="Fetch Datalayer user profile")
    parser.add_argument(
        "--run-url",
        "--run_url",
        dest="run_url",
        default=os.environ.get("DATALAYER_RUN_URL", ""),
        help="Datalayer platform URL, with a key (default: $DATALAYER_RUN_URL)",
    )
    parser.add_argument(
        "--api-key",
        "--api_key",
        dest="api_key",
        default=os.environ.get("DATALAYER_API_KEY", ""),
        help="API key, outside a runtime (default: $DATALAYER_API_KEY)",
    )
    parser.add_argument(
        "--runtime-url",
        "--runtime_url",
        dest="runtime_url",
        default="",
        help="The agent runtime (default: $AGENT_RUNTIMES_URL, else http://127.0.0.1:8765)",
    )
    parser.add_argument(
        "--agent",
        default="",
        help="Which of the runtime's agents asks (default: $AGENT_RUNTIMES_AGENT_ID)",
    )
    return parser.parse_args(argv)


def main(argv=None) -> dict:
    """The profile: from IAM with a key and its platform when both are given, else from the runtime."""
    args = arguments(argv)
    if args.api_key and args.run_url:
        return whoami(args.run_url, args.api_key)
    return whoami_from_runtime(runtime_url(args.runtime_url), args.agent)


if __name__ == "__main__":
    try:
        print(json.dumps(main(), indent=2))
    except WhoamiRefused as refusal:
        print(f"Error: {refusal}", file=sys.stderr)
        sys.exit(1)
