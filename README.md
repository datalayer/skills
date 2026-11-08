<!--
  ~ Copyright (c) 2025-2026 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

[![Datalayer](https://images.datalayer.io/legacy/datalayer-25.svg)](https://datalayer.ai)

[![Become a Sponsor](https://img.shields.io/static/v1?label=Become%20a%20Sponsor&message=%E2%9D%A4&logo=GitHub&style=flat&color=1ABC9C)](https://github.com/sponsors/datalayer)

# ☰ 🧰 Datalayer Skills

Agent skills for the [Datalayer](https://datalayer.ai) platform, discovered by
[agent-skills](https://github.com/datalayer/agent-skills) through Python entry
points: install the package, and the skills are there.

## Installation

```bash
pip install datalayer-skills
```

The Datalayer agent runtime image installs it, so an agent spec names these
skills by their names (for example `datalayer-memory-add`) and the runtime
loads them from the entry points, with no skill spec of their own.

## Available Skills

| Skill | Scripts | What it does |
|-------|---------|--------------|
| `datalayer-whoami` | `whoami` | The authenticated user's profile from Datalayer IAM |
| `datalayer-memory-add` | `add` | Keep one thing in the person's memory of the agent, in their words |
| `datalayer-memory-search` | `search` | The memories closest to a query |
| `datalayer-memory-list` | `list_memories` | Every memory, newest first, with its id |
| `datalayer-memory-delete` | `delete`, `delete_all` | Forget one memory by id, or everything once the person confirmed how many |

## The memory skills

An agent whose spec says `memory: mem0` keeps a durable memory of the person
whose runtime it is: mem0, in PostgreSQL (pgvector) on a Datalayer runtime,
embedded through ai-inference with the runtime's token. The memory skills let
the person keep, read, list and delete it on request.

**How the scripts reach the memory.** A skill script runs in the agent's
sandbox, the Jupyter container beside the agent runtime in the same pod. It
calls the runtime's memory routes on the pod's loopback (by default
`http://127.0.0.1:8765`), with the Python standard library only:

| Script | Route |
|--------|-------|
| `add` | `POST /api/v1/agents/{agent}/memory` with `{"content", "metadata"}` |
| `search` | `POST /api/v1/agents/{agent}/memory/search` with `{"query"}` |
| `list_memories` | `GET /api/v1/agents/{agent}/memory` |
| `delete` | `DELETE /api/v1/agents/{agent}/memory/{id}` |
| `delete_all` | `DELETE /api/v1/agents/{agent}/memory?count=N` |

The scripts do not use mem0's client directly. That would need the PostgreSQL
password and the ai-inference token in the sandbox, which holds neither, and
it would let the script choose whose memory it opens. Going through the
runtime needs no egress (the call stays in the pod) and no secret, and keeps
the scope where agent-runtimes keeps it.

**Scope.** The runtime keeps the memory under the composite key (user, agent):
the user is the runtime owner's personal account, read from the runtime's
trusted environment (`DATALAYER_USER_UID`), and the agent is the agent's own
id. The scripts send neither. An id that is not one of this agent's memories
of the person is not found, and `delete_all` forgets nothing when the agent
remembers more than the `count` the person confirmed.

**Which agent.** `--agent` (the agent's name on the runtime), else
`AGENT_RUNTIMES_AGENT_ID`, else the runtime's only agent. When several agents
run on the runtime, the script asks for `--agent`.

**Optional environment.** `AGENT_RUNTIMES_URL` (another runtime),
`AGENT_RUNTIMES_PORT` (its port on the loopback).

## How It Works

The package declares each skill in the `agent_skills.skills` entry-point group
of `pyproject.toml`:

```toml
[project.entry-points."agent_skills.skills"]
datalayer-whoami = "datalayer_skills.skills.whoami"
datalayer-memory-add = "datalayer_skills.skills.memory_add"
datalayer-memory-search = "datalayer_skills.skills.memory_search"
datalayer-memory-list = "datalayer_skills.skills.memory_list"
datalayer-memory-delete = "datalayer_skills.skills.memory_delete"
```

Each value is a module that holds a `SKILL.md` and a `scripts/` directory.
`agent_skills.discover_entrypoint_skills()` loads them, and
`AgentSkillsToolset(discover_entrypoints=True)` offers them to an agent.
An agent runtime loads the ones its agent spec names.

## Development

```bash
pip install -e ".[test]"
pytest
```

The tests run each memory script against a fake agent runtime on the
loopback, and through agent-skills' toolset with an eval sandbox.

## Release

Set the version in `datalayer_skills/__version__.py`, merge to `main`, then
push the tag `v<version>`. The Release workflow runs the tests, builds, and
publishes to PyPI through trusted publishing (the `pypi` environment).
