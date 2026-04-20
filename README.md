<!--
  ~ Copyright (c) 2025-2026 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

[![Datalayer](https://assets.datalayer.tech/datalayer-25.svg)](https://datalayer.io)

[![Become a Sponsor](https://img.shields.io/static/v1?label=Become%20a%20Sponsor&message=%E2%9D%A4&logo=GitHub&style=flat&color=1ABC9C)](https://github.com/sponsors/datalayer)

# ☰ 🧰 Datalayer Skills

Agent skills for the [Datalayer](https://datalayer.io) platform, automatically
discovered by [agent-skills](https://github.com/datalayer/agent-skills) via
Python entrypoints.

## Installation

```bash
pip install datalayer_skills
```

Once installed, `agent-skills` discovers the skills in this package
automatically — no configuration needed.

## Available Skills

| Skill | Description |
|-------|-------------|
| **whoami** | Query the authenticated user's profile from Datalayer IAM |

## How It Works

This package registers itself via the `agent_skills.skills` entrypoint group
in `pyproject.toml`:

```toml
[project.entry-points."agent_skills.skills"]
whoami = "datalayer_skills.skills.whoami"
```

When `AgentSkillsToolset` initialises it scans installed packages for this
entrypoint group and loads each skill module automatically.

## Development

```bash
# Install in editable mode
pip install -e ".[test]"

# Run tests
pytest
```
