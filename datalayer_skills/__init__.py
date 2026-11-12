# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Datalayer Skills — agent skills for the Datalayer platform.

This package provides skills that integrate with Datalayer platform services
(IAM, runtimes, etc.) and registers them via Python entrypoints so that
``agent-skills`` discovers them automatically when this package is installed.

Available skills:

- **whoami** — Query the authenticated user's profile from Datalayer IAM.
- **memory-add**, **memory-search**, **memory-list**, **memory-delete** — keep,
  search, list and forget the person's durable (mem0) memory of the agent,
  through the agent runtime the skill runs beside.
- **accounting**, **crawl**, **events**, **github**, **image**, **pdf**,
  **text-summarizer**, **video** — the catalogue's skills, each with the
  dependencies its scripts need in an extra (``skills-<name>``, ``skills`` for all).
"""
