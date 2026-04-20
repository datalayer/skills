# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Whoami script — fetch the authenticated user's Datalayer profile.

Calls the Datalayer IAM ``GET /api/iam/v1/whoami`` endpoint and prints
the user profile as a normalised JSON object.

Usage:
    python whoami.py [--run-url URL] [--token TOKEN]

Environment:
    DATALAYER_RUN_URL  Base URL of the Datalayer platform.
    DATALAYER_TOKEN    Bearer token for authentication.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def whoami(run_url: str, token: str) -> dict:
    """Fetch the current user's profile from Datalayer IAM.

    Args:
        run_url: Base URL of the Datalayer platform
            (e.g. ``https://prod1.datalayer.run``).
        token: Bearer token for IAM authentication.

    Returns:
        Normalised profile dict with keys: handle, email, first_name,
        last_name, uid, roles, avatar_url.
    """
    import httpx

    response = httpx.get(
        f"{run_url.rstrip('/')}/api/iam/v1/whoami",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if not data or "profile" not in data:
        print("Error: Invalid response from whoami API", file=sys.stderr)
        sys.exit(1)

    profile = data["profile"]

    # Normalise Solr-style field names to human-friendly keys.
    return {
        "handle": profile.get("handle_s", ""),
        "email": profile.get("email_s", ""),
        "first_name": profile.get("first_name_t", ""),
        "last_name": profile.get("last_name_t", ""),
        "uid": profile.get("uid", profile.get("id", "")),
        "roles": profile.get("roles_ss", []),
        "avatar_url": profile.get("avatar_url_s", ""),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Datalayer user profile")
    parser.add_argument(
        "--run-url",
        default=os.environ.get("DATALAYER_RUN_URL", ""),
        help="Datalayer platform URL (default: $DATALAYER_RUN_URL)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("DATALAYER_TOKEN", ""),
        help="Bearer token (default: $DATALAYER_TOKEN)",
    )
    args = parser.parse_args()

    if not args.run_url:
        print(
            "Error: --run-url or DATALAYER_RUN_URL is required",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.token:
        print(
            "Error: --token or DATALAYER_TOKEN is required",
            file=sys.stderr,
        )
        sys.exit(1)

    result = whoami(args.run_url, args.token)
    print(json.dumps(result, indent=2))
