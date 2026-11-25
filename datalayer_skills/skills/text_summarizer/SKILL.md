---
name: text-summarizer
description: Summarize a text or a file into a few sentences or its key points. Use it when the person asks for a summary, the key points or a shorter version of a text.
license: BSD-3-Clause
version: 1.0.0
tags:
  - nlp
  - summarization
  - text-processing
author: Datalayer
compatibility: Requires Python 3.10+
allowed-tools: Read
metadata:
  visibility: public
  category: nlp
---

# Text Summarizer Skill

## Required Environment Variables

- None required.

## Invocation Contract

- Call `run_skill_script` with:
  - `skill_name`: `text-summarizer`
  - `script_name`: `summarize`
- This script requires one input source, passed as `--file` or `--text`.
- Pass those options in `kwargs`.

## Script API

### `script_name: summarize`

- required input (exactly one):
  - `file`: path to text file, or
  - `text`: inline text to summarize
- optional `kwargs`:
  - `max_sentences`: integer
  - `method`: `extractive | key_points`

## `run_skill_script` Examples

- Summarize a file:

```json
{
  "skill_name": "text-summarizer",
  "script_name": "summarize",
  "kwargs": {
    "file": "document.txt",
    "max_sentences": 5,
    "method": "extractive"
  }
}
```

- Summarize inline text:

```json
{
  "skill_name": "text-summarizer",
  "script_name": "summarize",
  "kwargs": {
    "text": "Long text here",
    "method": "key_points",
    "max_sentences": 3
  }
}
```

## Direct CLI Examples

```bash
python datalayer_skills/skills/text_summarizer/scripts/summarize.py --file document.txt --max-sentences 5
python datalayer_skills/skills/text_summarizer/scripts/summarize.py --text "Long text here" --method key_points --max-sentences 3
```
