---
name: datalayer-whoami
description: Read the profile of the Datalayer account the agent runs for — its handle, name, email, roles and avatar. Use it when the person asks who they are signed in as, or a task needs their identity. In a Datalayer runtime it needs no key.
license: BSD-3-Clause
version: 1.0.0
tags:
  - datalayer
  - iam
  - identity
  - authentication
author: Datalayer
env:
  optional:
    - AGENT_RUNTIMES_URL
    - AGENT_RUNTIMES_PORT
    - AGENT_RUNTIMES_AGENT_ID
    - DATALAYER_API_KEY
    - DATALAYER_RUN_URL
---

# Datalayer Whoami Skill

Says which Datalayer account the agent runs for. The script asks the agent
runtime it runs beside, on the pod's loopback (`GET /api/v1/owner`); the runtime
answers with the identity it holds for that account. No key is in the sandbox,
and none is needed.

## Required Environment Variables

- None in a Datalayer runtime.

## Optional Environment Variables

- `AGENT_RUNTIMES_URL` — another agent runtime's URL.
- `AGENT_RUNTIMES_PORT` — the runtime's port on the loopback (default 8765).
- `AGENT_RUNTIMES_AGENT_ID` — which of the runtime's agents asks, when it runs several.
- `DATALAYER_API_KEY` and `DATALAYER_RUN_URL` — only to run the script by hand
  outside a runtime: with both (or the `api_key` and `run_url` kwargs), it asks
  Datalayer's IAM itself (`GET /api/iam/v1/whoami`) and the runtime is not asked.

## Scope

- A runtime a person started from their account says their profile.
- A runtime that serves an application to other people says the application
  owner's public face: handle, name and avatar. `email` is `null` and `roles`
  is empty there, by design.
- A runtime that runs for nobody (a visitors' runtime, one started without an
  account) says so in a sentence; there is nobody to name.

## Invocation Contract

- Call `run_skill_script` with:
  - `skill_name`: `datalayer-whoami`
  - `script_name`: `whoami`
- No positional `args` required.
- Optional `kwargs`: `agent`, `runtime_url`; `run_url` and `api_key` outside a runtime.

## Scripts API

### `script_name: whoami`

Returns the profile as JSON.

- `args`: none required
- optional `kwargs`:
  - `agent` — which of the runtime's agents asks (default `$AGENT_RUNTIMES_AGENT_ID`)
  - `runtime_url` — the agent runtime (default `$AGENT_RUNTIMES_URL`, else the loopback)
  - `run_url` — override `DATALAYER_RUN_URL` (with a key)
  - `api_key` — override `DATALAYER_API_KEY` (outside a runtime)

**Output:** JSON object with user profile fields:

```json
{
  "handle": "johndoe",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "roles": ["user"],
  "uid": "...",
  "avatar_url": "https://..."
}
```

## Common Failure Modes

- Exit code `1` with `Error: ...` on stderr: why nobody was said, in the
  runtime's sentence — the runtime runs for nobody, the identity it holds is no
  longer accepted, the runtime cannot be reached. Say it to the person.
