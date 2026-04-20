# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Datalayer Skills — agent skills for the Datalayer platform.

This package provides skills that integrate with Datalayer platform services
(IAM, runtimes, etc.) and registers them via Python entrypoints so that
``agent-skills`` discovers them automatically when this package is installed.

Available skills:

- **whoami** — Query the authenticated user's profile from Datalayer IAM.
"""
