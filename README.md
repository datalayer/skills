<!--
  ~ Copyright (c) 2025-2026 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

[![Datalayer](https://images.datalayer.io/legacy/datalayer-25.svg)](https://datalayer.ai)

[![Become a Sponsor](https://img.shields.io/static/v1?label=Become%20a%20Sponsor&message=%E2%9D%A4&logo=GitHub&style=flat&color=1ABC9C)](https://github.com/sponsors/datalayer)

# ☰ 🧰 Datalayer Skills

Agent skills for the [Datalayer](https://datalayer.ai) platform, discovered by
[agent-skills](https://github.com/datalayer/agent-skills) through Python entry
points: install the package, and the skills are there.

## Installation

```bash
pip install datalayer-skills
```

The skills' scripts run where the agent's sandbox runs. What a skill's scripts
import is in an extra of its own, and `skills` brings them all:

```bash
pip install "datalayer-skills[skills]"            # every skill's dependencies
pip install "datalayer-skills[skills-video]"      # one skill's
python -m playwright install chromium             # once, for page snapshots and recordings
```

| Extra | Brings |
|-------|--------|
| `skills-accounting` | pandas |
| `skills-crawl` | httpx, beautifulsoup4 |
| `skills-github` | httpx |
| `skills-pdf` | pypdf, pdf2image, Pillow |
| `skills-image` | Pillow, Playwright |
| `skills-video` | imageio-ffmpeg (an ffmpeg binary; the system's is used when present), Playwright |

The Datalayer agent runtime image installs it, so an agent spec names these
skills by their names (for example `datalayer-memory-add`) and the runtime
loads them from the entry points, with no skill spec of their own.

## Available Skills

| Skill | Scripts | What it does |
|-------|---------|--------------|
| `datalayer-whoami` | `whoami` | The authenticated user's profile from Datalayer IAM |
| `datalayer-memory-add` | `add` | Keep one thing in the person's memory of the agent, in their words |
| `datalayer-memory-search` | `search` | The memories closest to a query |
| `datalayer-memory-list` | `list_memories` | Every memory, newest first, with its id |
| `datalayer-memory-delete` | `delete`, `delete_all` | Forget one memory by id, or everything once the person confirmed how many |
| `accounting` | `reconcile`, `variance`, `aging`, `close_summary` | Two ledgers reconciled, two periods compared, open invoices aged, a trial balance closed, over CSV exports |
| `crawl` | `fetch_page`, `fetch_js_page`, `extract_links`, `extract_tables`, `crawl_site`, `check_robots` | Pages fetched (rendered when they need JavaScript), their links and tables, a site walked within its robots.txt |
| `events` | `event` | Events of an agent created, read, listed and updated |
| `github` | `list_repos`, `get_repo`, `list_issues`, `list_prs`, `search_repos` | Repositories, issues and pull requests read from GitHub (needs a token) |
| `image` | `image_info`, `resize_image`, `crop_image`, `convert_image`, `optimize_image`, `thumbnail_image`, `snapshot_page`, `snapshot_video_frame` | Snapshots of pages and video frames; images read, resized, cropped, converted, optimized and thumbnailed |
| `pdf` | `check_fillable_fields`, `extract_form_field_info`, `fill_fillable_fields`, `fill_pdf_form_with_annotations`, `convert_pdf_to_images`, `check_bounding_boxes`, `create_validation_image` | PDF forms checked, their fields read and filled, pages turned to images |
| `text-summarizer` | `summarize` | A text shortened to its key sentences or points |
| `video` | `record_and_zoom`, `save_to_space`, `video_info`, `record_page`, `trim_video`, `zoom_video`, `transcode_video`, `optimize_video`, `video_thumbnail`, `video_to_gif`, `concat_videos` | Pages recorded and zoomed as an MP4 to share, kept in the person's Space; videos read, trimmed, zoomed in and out, transcoded, optimized, framed, turned to GIF and joined |

The eight last ones were bundled with agent-skills until its 1.3.0, as
`agent_skills.skills.<name>`. They are `datalayer_skills.skills.<name>` now,
under the same skill names, and agent-skills is the framework alone.

## Recording a page, zoomed, to share

`record_and_zoom` records a page with a headless Chromium (from the moment it
has loaded), zooms in and out on it with eased moves, and writes an MP4 anyone
can play — H.264, yuv420p, `+faststart`, 30 frames a second:

```bash
python datalayer_skills/skills/video/scripts/record_and_zoom.py https://datalayer.ai hero.mp4 \
  --seconds 8 --zoom "2-3-5-6-2-0.25-0.75"
```

With no `--zoom`, one zoom on the centre to 1.5x over the middle half of the
recording; `--zoom none` keeps the page whole. The zooms are written as for
`zoom_video` (below), their seconds counted from the page loaded.

With `--save` (or `save_to_space <file>` for any file the skill made), the file
is kept in the person's Datalayer Space: the script sends it to the agent
runtime on the pod's loopback (`POST /api/v1/spaces/files`, agent-runtimes),
which keeps it, with the identity it holds for the runtime's owner, in a Dataset
of their default Space (`Videos` when unsaid; `--space`, `--folder`, `--name`,
`--collection` choose others), listed under the Space's Contents. No token is
asked for or sent. When no Space can be reached, the script says why and the
local file stays.

## Zooming a video

`zoom_video` zooms in on a point of a video and back out, once or several
times, and keeps the video's size:

```bash
python datalayer_skills/skills/video/scripts/zoom_video.py demo.mp4 demo_zoom.mp4 \
  "2-3-6-7-1.8-0.5-0.5|10-11-14-15-2.2-0.8-0.25" --ease smooth
```

A zoom is `s1-s2-s3-s4-f-x-y`: the zoom-in runs from `s1` to `s2` seconds, the
picture stays zoomed until `s3`, the zoom-out is complete at `s4`; `f` is the
factor (`2` doubles the picture), and `x`, `y` the point zoomed on, each from 0
to 1 from the bottom-left corner. Several zooms are separated by `|`.

| Option | What it does |
|--------|--------------|
| `--ease linear` | The zoom moves at a constant speed (when unsaid) |
| `--ease smooth` | Each move starts and ends slowly |
| `--trim START-END` | Cuts the video to those seconds first; the zooms' times then count from the trim's start |
| `--crf N` | The quality, 18 when unsaid (lower is better and larger) |
| `--preset NAME` | H.264's preset, `medium` when unsaid |

Each frame is scaled by the factor of its time, then cropped back to the
video's size around the point; near an edge the picture stops at the edge. An
`.mp4` is H.264 with the audio copied, a `.webm` VP9 with Opus. Through an
agent: `run_skill_script` with `skill_name` `video`, `script_name`
`zoom_video`, and the same values in `args`.

## The memory skills

An agent whose spec says `memory: mem0` keeps a durable memory of the person
whose runtime it is: mem0, in PostgreSQL (pgvector) on a Datalayer runtime,
embedded through ai-inference with the runtime's token. The memory skills let
the person keep, read, list and delete it on request.

**How the scripts reach the memory.** A skill script runs in the agent's
sandbox, the Jupyter container beside the agent runtime in the same pod. It
calls the runtime's memory routes on the pod's loopback (by default
`http://127.0.0.1:8765`), with the Python standard library only:

| Script | Route |
|--------|-------|
| `add` | `POST /api/v1/agents/{agent}/memory` with `{"content", "metadata"}` |
| `search` | `POST /api/v1/agents/{agent}/memory/search` with `{"query"}` |
| `list_memories` | `GET /api/v1/agents/{agent}/memory` |
| `delete` | `DELETE /api/v1/agents/{agent}/memory/{id}` |
| `delete_all` | `DELETE /api/v1/agents/{agent}/memory?count=N` |

The scripts do not use mem0's client directly. That would need the PostgreSQL
password and the ai-inference token in the sandbox, which holds neither, and
it would let the script choose whose memory it opens. Going through the
runtime needs no egress (the call stays in the pod) and no secret, and keeps
the scope where agent-runtimes keeps it.

**Scope.** The runtime keeps the memory under the composite key (user, agent):
the user is the runtime owner's personal account, read from the runtime's
trusted environment (`DATALAYER_USER_UID`), and the agent is the agent's own
id. The scripts send neither. An id that is not one of this agent's memories
of the person is not found, and `delete_all` forgets nothing when the agent
remembers more than the `count` the person confirmed.

**Which agent.** `--agent` (the agent's name on the runtime), else
`AGENT_RUNTIMES_AGENT_ID`, else the runtime's only agent. When several agents
run on the runtime, the script asks for `--agent`.

**Optional environment.** `AGENT_RUNTIMES_URL` (another runtime),
`AGENT_RUNTIMES_PORT` (its port on the loopback).

## How It Works

The package declares each skill in the `agent_skills.skills` entry-point group
of `pyproject.toml`:

```toml
[project.entry-points."agent_skills.skills"]
datalayer-whoami = "datalayer_skills.skills.whoami"
datalayer-memory-add = "datalayer_skills.skills.memory_add"
datalayer-memory-search = "datalayer_skills.skills.memory_search"
datalayer-memory-list = "datalayer_skills.skills.memory_list"
datalayer-memory-delete = "datalayer_skills.skills.memory_delete"
video = "datalayer_skills.skills.video"
# … and one line per other skill
```

Each value is a module that holds a `SKILL.md` and a `scripts/` directory.
`agent_skills.discover_entrypoint_skills()` loads them, and
`AgentSkillsToolset(discover_entrypoints=True)` offers them to an agent.
An agent runtime loads the ones its agent spec names.

## Development

```bash
pip install -e ".[test]"
pytest
```

The tests run each memory script against a fake agent runtime on the
loopback, and through agent-skills' toolset with an eval sandbox; the
accounting scripts on small books; the video zoom's filter and arguments, and
a zoom on a small generated clip where ffmpeg is installed; `record_and_zoom`'s
encode of a generated recording, a real page recorded where Playwright's
Chromium is installed, and `save_to_space` against a fake agent runtime.

## Release

Set the version in `datalayer_skills/__version__.py`, say what changed in
`CHANGELOG.md`, merge to `main`, then
push the tag `v<version>`. The Release workflow runs the tests, builds, and
publishes to PyPI through trusted publishing (the `pypi` environment).
