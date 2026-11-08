---
name: datalayer-memory-search
description: Search the person's durable memory of this agent (mem0) for what it remembers about a topic, closest first. Use it when the person asks what you remember about something, or before answering a question their earlier preferences bear on.
license: BSD-3-Clause
version: 1.0.0
tags:
  - datalayer
  - memory
  - mem0
author: Datalayer
---

# Datalayer Memory: Search

Reads the agent's durable memory of the person: the memories closest to a
query, by meaning, each with its id, words, score and when it was learned.

## Required Environment Variables

- None required. The script reaches the agent runtime it runs beside on the
  pod's loopback (`http://127.0.0.1:8765`), and the runtime scopes the memory itself.

## Optional Environment Variables

- `AGENT_RUNTIMES_URL`: another agent runtime's URL.
- `AGENT_RUNTIMES_PORT`: the runtime's port on the loopback (default 8765).
- `AGENT_RUNTIMES_AGENT_ID`: the agent's name on the runtime, when several agents run there.

## Required Software

- None beyond Python: the script uses the standard library only.

## Scope

The memory is the agent's mem0 memory of the person whose runtime it is, kept
under their account and the agent (user, agent). The runtime takes both from
its own trusted environment: the script names neither and cannot reach anybody
else's memory, nor another agent's.

## Invocation Contract

- Call `run_skill_script` with:
  - `skill_name`: `datalayer-memory-search`
  - `script_name`: `search`
- Required `kwargs`: `query`.
- Optional `kwargs`: `limit`, `agent`, `runtime_url`.

## Scripts API

### `script_name: search`

- Purpose: the memories closest to a query.
- Positional `args`: none.
- Supported `kwargs`:
  - `query`: what to look for, in a few words.
  - `limit`: at most this many, 1 or more (default `10`).
  - `agent`, `runtime_url`: as in every memory skill.
- Prints JSON: `{"agent", "query", "count", "memories": [{"id", "content", "score", "metadata", "created_at", "updated_at"}]}`.

## Common Failure Modes

- Exit code `1` with `Error: ...` on stderr: what the runtime answered instead,
  in its sentence. "has no durable memory": the agent was not made with
  `memory: mem0`. "Memories cannot be kept on this runtime: ...": the runtime
  has no store for them. "Several agents run on this runtime": pass `agent`.
- Exit code `2`: an unknown `kwargs` key or a missing one.
