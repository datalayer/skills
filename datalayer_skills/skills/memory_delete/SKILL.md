---
name: datalayer-memory-delete
description: Forget what the agent durably remembers of the person (mem0) — one memory by its id, or everything once the person confirmed how many. Use it when the person asks you to forget something, or to forget everything about them.
license: BSD-3-Clause
version: 1.0.0
tags:
  - datalayer
  - memory
  - mem0
author: Datalayer
---

# Datalayer Memory: Delete

Forgets one memory of the person, by its id, or all of them. Forgetting cannot
be undone.

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

- One memory: call `run_skill_script` with `skill_name` `datalayer-memory-delete`,
  `script_name` `delete` and `kwargs` `{"id": "<memory id>"}`. Find the id with
  `datalayer-memory-search` or `datalayer-memory-list` first.
- Everything: list the memories with `datalayer-memory-list`, tell the person
  how many there are, and ask them to confirm. Only once they confirmed, call
  `script_name` `delete_all` with `kwargs` `{"count": <the number they confirmed>}`.
  Never call it without their explicit confirmation.

## Scripts API

### `script_name: delete`

- Purpose: forget one memory.
- Positional `args`: none.
- Supported `kwargs`:
  - `id`: the memory's id, as the list or search skill gives it.
  - `agent`, `runtime_url`: as in every memory skill.
- Prints JSON: `{"agent", "id", "forgotten": 1}`. An id that is not one of
  this agent's memories of the person is not found (exit code `1`).

### `script_name: delete_all`

- Purpose: forget everything the agent remembers of the person.
- Positional `args`: none.
- Supported `kwargs`:
  - `count`: how many memories the person was shown and confirmed to forget.
    When the agent remembers more by now, nothing is forgotten (exit code `1`,
    "It remembers more than the N you confirmed now"): list again and ask again.
  - `agent`, `runtime_url`: as in every memory skill.
- Prints JSON: `{"agent", "forgotten": N}`.

## Common Failure Modes

- Exit code `1` with `Error: ...` on stderr: what the runtime answered instead,
  in its sentence. "has no durable memory": the agent was not made with
  `memory: mem0`. "Memories cannot be kept on this runtime: ...": the runtime
  has no store for them. "Several agents run on this runtime": pass `agent`.
- Exit code `2`: an unknown `kwargs` key or a missing one.
