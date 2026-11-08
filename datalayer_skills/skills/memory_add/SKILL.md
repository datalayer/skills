---
name: datalayer-memory-add
description: Keep one thing in the person's durable memory of this agent (mem0), in their words — a preference, a fact about them or their work. Use it when the person asks you to remember something, or states a lasting preference you will need in later sessions.
license: BSD-3-Clause
version: 1.0.0
tags:
  - datalayer
  - memory
  - mem0
author: Datalayer
---

# Datalayer Memory: Add

Keeps one memory in the agent's durable memory of the person. It outlives the
runtime: a later session of the same agent, on any runtime, reads it back.

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
  - `skill_name`: `datalayer-memory-add`
  - `script_name`: `add`
- Required `kwargs`: `content`.
- Optional `kwargs`: `agent`, `runtime_url`.

## Scripts API

### `script_name: add`

- Purpose: keep one thing, in the person's words (at most 2,000 characters).
- Positional `args`: none.
- Supported `kwargs`:
  - `content`: what to remember, one fact or preference per call.
  - `agent`: the agent's name on the runtime (found on its own when one agent runs there).
  - `runtime_url`: the agent runtime (default `$AGENT_RUNTIMES_URL`, else the loopback).
- Prints JSON: `{"agent": ..., "added": 1, "content": "..."}`.

## Common Failure Modes

- Exit code `1` with `Error: ...` on stderr: what the runtime answered instead,
  in its sentence. "has no durable memory": the agent was not made with
  `memory: mem0`. "Memories cannot be kept on this runtime: ...": the runtime
  has no store for them. "Several agents run on this runtime": pass `agent`.
- Exit code `2`: an unknown `kwargs` key or a missing one.
