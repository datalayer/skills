---
name: datalayer-whoami
description: Read the profile of the Datalayer account the agent runs for — its handle, name, email, roles and avatar — from Datalayer's IAM. Use it when the person asks who they are signed in as, or a task needs their identity. Requires DATALAYER_API_KEY.
license: BSD-3-Clause
version: 1.0.0
tags:
  - datalayer
  - iam
  - identity
  - authentication
author: Datalayer
env:
  required:
    - DATALAYER_API_KEY
  optional:
    - DATALAYER_RUN_URL
---

# Datalayer Whoami Skill

Retrieve the authenticated user's profile from the Datalayer IAM API.
An authenticated user on the Datalayer platform is required to use this skill.

## Environment Variables

- `DATALAYER_API_KEY` — API key for Datalayer IAM authentication.
- `DATALAYER_RUN_URL` — Base URL of the Datalayer platform (e.g. `https://prod1.datalayer.run`).
  Optional for activation: the `run_url` kwarg gives it as well. Either one is enough; with
  neither, the script says so.

## Invocation Contract

- Call `run_skill_script` with:
  - `skill_name`: `datalayer-whoami`
  - `script_name`: `whoami`
- No positional `args` required.
- Optional `kwargs`: `run_url`, `api_key` (override environment variables).

## Scripts API

### `script_name: whoami`

Calls the Datalayer IAM `GET /api/iam/v1/whoami` endpoint and returns the
user profile as JSON.

- `args`: none required
- optional `kwargs`:
  - `run_url` — override `DATALAYER_RUN_URL`
  - `api_key` — override `DATALAYER_API_KEY`

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
