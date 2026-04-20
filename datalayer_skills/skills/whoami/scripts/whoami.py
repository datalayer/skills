# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Whoami script — fetch the authenticated user's Datalayer profile.

Uses the ``datalayer_core`` high-level client to call the Datalayer IAM
whoami endpoint and prints the user profile as JSON.

Usage:
    python whoami.py [--run-url URL] [--api-key KEY]

Environment:
    DATALAYER_RUN_URL  Base URL of the Datalayer platform.
    DATALAYER_API_KEY  API key for authentication.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def whoami(run_url: str, api_key: str) -> dict:
    """Fetch the current user's profile from Datalayer IAM.

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Datalayer user profile")
    parser.add_argument(
        "--run-url",
        default=os.environ.get("DATALAYER_RUN_URL", ""),
        help="Datalayer platform URL (default: $DATALAYER_RUN_URL)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("DATALAYER_API_KEY", ""),
        help="API key (default: $DATALAYER_API_KEY)",
    )
    args = parser.parse_args()

    if not args.run_url:
        print(
            "Error: --run-url or DATALAYER_RUN_URL is required",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.api_key:
        print(
            "Error: --api-key or DATALAYER_API_KEY is required",
            file=sys.stderr,
        )
        sys.exit(1)

    result = whoami(args.run_url, args.api_key)
    print(json.dumps(result, indent=2))
