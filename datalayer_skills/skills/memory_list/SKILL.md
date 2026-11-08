---
name: datalayer-memory-list
description: List everything the agent durably remembers of the person (mem0), newest first, with each memory's id. Use it when the person asks what you remember about them, and before deleting, to show them what would be forgotten and how many.
license: BSD-3-Clause
version: 1.0.0
tags:
  - datalayer
  - memory
  - mem0
author: Datalayer
---

# Datalayer Memory: List

Lists the agent's durable memory of the person, newest first: each memory's
id (what `datalayer-memory-delete` takes), its words and when it was learned.

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
  - `skill_name`: `datalayer-memory-list`
  - `script_name`: `list_memories`
- No required `kwargs`.
- Optional `kwargs`: `limit`, `agent`, `runtime_url`.

## Scripts API

### `script_name: list_memories`

- Purpose: what the agent remembers of the person.
- Positional `args`: none.
- Supported `kwargs`:
  - `limit`: at most this many shown, 1 or more (default `50`).
  - `agent`, `runtime_url`: as in every memory skill.
- Prints JSON: `{"agent", "count", "total", "memories": [{"id", "content", "metadata", "created_at", "updated_at"}]}`.
  `total` is how many the runtime listed, `count` how many are shown.

## Common Failure Modes

- Exit code `1` with `Error: ...` on stderr: what the runtime answered instead,
  in its sentence. "has no durable memory": the agent was not made with
  `memory: mem0`. "Memories cannot be kept on this runtime: ...": the runtime
  has no store for them. "Several agents run on this runtime": pass `agent`.
- Exit code `2`: an unknown `kwargs` key or a missing one.
