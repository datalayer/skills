---
name: datalayer-library-publish
description: Publish one of the person's existing Datalayer items in the public Library after explicit confirmation, including notebooks, documents, decks, spreadsheets, cells, learning content, datasets, benchmarks, applications and environments.
license: BSD 3-Clause
version: 1.0.0
tags:
  - datalayer
  - library
  - publish
  - artifact
author: Datalayer
---

# Publish to the public Library

Publish an item the person already owns to Datalayer's public Library. This is
not a file uploader and does not create an item: obtain the item uid and its
kind from the current application, tool result or the person.

Publishing makes the item visible to everyone and gives it a public page. Ask
the person for explicit approval immediately before the call. Never infer
approval from a request to create, edit, save or share privately. Pass
`--confirm` only after that approval. If they have not approved, explain the
effect and ask; do not run the script.

Supported kinds are the current Library kinds: `notebook`, `document`, `deck`,
`spreadsheet`, `cell`, `lesson`, `exercise`, `assignment`, `course`, `evalset`
(benchmark), `dataset`, `agent`, `dataserver`, `environment`, `report`,
`investigation`, `evaluator`, and `app`.

## Required Environment Variables

- None. The script calls the agent runtime on the pod loopback. The runtime
  publishes with the identity it already holds for its owner; no credential is
  exposed to the skill.

## Invocation Contract

- `skill_name`: `datalayer-library-publish`
- `script_name`: `publish_item`
- `args`: `['<item uid>', '<item type>', '--confirm']`
- Optional: `--description '<public description>'`, repeated `--tag '<tag>'`,
  and `--video` for a deck whose saved video should be its public form.
- Output: JSON with `published`, `item_uid`, `item_type`, and `public_url`.

After success, give the person `public_url`. On refusal, repeat the runtime's
reason without claiming the item was published.
