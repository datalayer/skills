---
name: events
description: Create, read, list and update the agent's events on Datalayer, through the AI Agents events API. Use it when a task must record an event or follow the state of one. In a Datalayer runtime it needs no key.
license: Proprietary. LICENSE.txt has complete terms
version: 1.0.0
tags:
  - events
  - orchestration
  - scheduling
author: Datalayer
env:
  optional:
    - AGENT_RUNTIMES_URL
    - AGENT_RUNTIMES_PORT
    - AGENT_RUNTIMES_AGENT_ID
    - DATALAYER_API_KEY
    - DATALAYER_AI_AGENTS_URL
---

# Events Skill

The script asks the agent runtime it runs beside, on the pod's loopback
(`/api/v1/owner/events`); the runtime asks Datalayer's AI Agents events API with
the identity it holds for the account it runs for. No key is in the sandbox,
and none is needed.

## Required Environment Variables

- None in a Datalayer runtime.

## Optional Environment Variables

- `AGENT_RUNTIMES_URL`: another agent runtime's URL.
- `AGENT_RUNTIMES_PORT`: the runtime's port on the loopback (default 8765).
- `AGENT_RUNTIMES_AGENT_ID`: the agent the events are of, when none is named.
- `DATALAYER_API_KEY`: only to run the script by hand outside a runtime. With
  it, the script calls the events API itself
  (`/api/ai-agents/v1/agents/{agent_id}/events`) and the runtime is not asked;
  `get` and `update` then need `agent_id` too.
- `DATALAYER_AI_AGENTS_URL`: where AI Agents runs, with a key (default
  `https://r1.datalayer.run`).

## Scope

- The events are those of the account the runtime runs for; a runtime that
  serves an application records them as that application.
- A runtime that runs for nobody says so in a sentence and records nothing.

## Invocation Contract

- Call `run_skill_script` with:
  - `skill_name`: `events`
  - `script_name`: `event`
- This script uses subcommands, so put the subcommand in `args[0]`.
- Use `args` for required positional items (for example, `event_id`).
- Use `kwargs` for optional and named flags.

## Script API

### `script_name: event`

Subcommands and parameters:

1. `create`

- `args`: `["create"]`
- required `kwargs`: `agent_id`, `title`
- optional `kwargs`: `kind`, `status`, `payload`, `metadata`
- `payload` and `metadata` must be JSON object strings.

2. `get`

- `args`: `["get", "<event_id>"]`
- optional `kwargs`: `agent_id`

3. `list`

- `args`: `["list"]`
- optional `kwargs`: `agent_id`, `kind`, `status`, `limit`, `offset`

4. `update`

- `args`: `["update", "<event_id>"]`
- optional `kwargs`: `agent_id`, `title`, `kind`, `status`, `payload`, `metadata`
- `payload` and `metadata` must be JSON object strings.

## Common Failure Modes

- Exit code `1` with `Error: ...` on stderr: why the events were not reached, in
  the runtime's or the API's sentence — the runtime runs for nobody, the
  identity it holds is no longer accepted, the event is not found, the runtime
  cannot be reached. Say it to the person; never retry in a loop.

## `run_skill_script` Examples

- Create:

```json
{
  "skill_name": "events",
  "script_name": "event",
  "args": ["create"],
  "kwargs": {
    "agent_id": "data-acquisition",
    "title": "New dataset",
    "kind": "dataset_ingested",
    "payload": "{\"dataset\":\"imerg\"}"
  }
}
```

- Update:

```json
{
  "skill_name": "events",
  "script_name": "event",
  "args": ["update", "evt_123"],
  "kwargs": {
    "status": "completed"
  }
}
```

## Direct CLI Examples

```bash
python datalayer_skills/skills/events/scripts/event.py create --agent-id data-acquisition --title "New dataset" --kind dataset_ingested --payload '{"dataset":"imerg"}'
python datalayer_skills/skills/events/scripts/event.py get evt_123
python datalayer_skills/skills/events/scripts/event.py list --agent-id data-acquisition --status pending --limit 20
python datalayer_skills/skills/events/scripts/event.py update evt_123 --status completed
```
