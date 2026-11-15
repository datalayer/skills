---
name: datalayer-email
description: Send the person whose agent this is one email — a summary, a report, a draft they asked to receive — through Datalayer's own mailer. It mails the person alone, never another address, a few a day. Use it only when the person asks to get something by email.
license: BSD-3-Clause
version: 1.0.0
tags:
  - datalayer
  - email
  - mail
author: Datalayer
---

# Datalayer Email

Sends one email to the person this agent runs for, at the address of their
Datalayer account. The mail goes through Datalayer's own mailer: the script
asks the agent runtime it runs beside, which asks Datalayer's IAM with the
runtime's own short-lived token. No mail password or provider key is in the
sandbox or the runtime.

## Required Environment Variables

- None required. The script reaches the agent runtime it runs beside on the
  pod's loopback (`http://127.0.0.1:8765`).

## Optional Environment Variables

- `AGENT_RUNTIMES_URL`: another agent runtime's URL.
- `AGENT_RUNTIMES_PORT`: the runtime's port on the loopback (default 8765).

## Required Software

- None beyond Python: the script uses the standard library only.

## Scope

- The recipient is always the person whose runtime this is: the script names
  no address, and Datalayer refuses one.
- At most a few mails a day for one person's agents (ten, Datalayer's limit);
  past it the mail is refused and the script says so.
- A runtime launched for a visitor, or for a deployment, sends no mail.
- Write the mail as plain text; paragraphs separated by a blank line.

## Invocation Contract

- Call `run_skill_script` with:
  - `skill_name`: `datalayer-email`
  - `script_name`: `send_email`
- Required `kwargs`: `subject`, `text`.
- Optional `kwargs`: `runtime_url`.

## Scripts API

### `script_name: send_email`

- Purpose: send the person one email.
- Positional `args`: none.
- Supported `kwargs`:
  - `subject`: the subject, at most 150 characters.
  - `text`: the body, plain text, at most 20,000 characters.
  - `runtime_url`: the agent runtime (default `$AGENT_RUNTIMES_URL`, else the loopback).
- Prints JSON: `{"sent": true, "to": "me"}`.

## Common Failure Modes

- Exit code `1` with `Error: ...` on stderr: why it was not sent, in Datalayer's
  sentence — no more mail today, no social token on this runtime (a visitor's
  or a deployment's), the account has no email address, the mailer could not
  send it just now. Say it to the person; never retry in a loop.
- Exit code `2`: an unknown `kwargs` key or a missing one.
