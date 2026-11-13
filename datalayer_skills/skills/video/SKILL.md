---
name: video
description: Video toolkit for recordings of web pages zoomed in and out as an MP4 ready to share and kept in the person's Datalayer Space, and videos read, trimmed, zoomed in and out on a point, transcoded, optimized for the web, thumbnailed, turned to GIF and joined.
license: BSD 3-Clause. LICENSE has complete terms
version: 1.2.0
tags:
  - video
  - recording
  - ffmpeg
  - zoom
  - optimize
  - space
author: Datalayer
metadata:
  visibility: public
---

# Video Skill

Recordings of pages, and what is done to a video afterwards: read what it is,
trim it, zoom in on a point and back out, transcode it, optimize it for the web,
take its thumbnail, turn a clip into a GIF, join several, and keep it in the
person's Datalayer Space. ffmpeg does the videos (`imageio-ffmpeg` brings a
binary, or the system's is used); a page recording runs a headless Chromium
through Playwright.

## Record a page, zoom, share: the flow

To show a page, use `record_and_zoom`: it records the page, zooms in and out on
it, and writes an MP4 anyone can play, in one call.

1. **Record** — a headless Chromium opens the page and records it. The seconds
   of its loading are cut: second 0 of the video is the page loaded.
2. **Zoom** — in on a point and back out, the moves eased (`smooth`). With no
   `--zoom`, one zoom on the centre to 1.5x: in from a quarter of the
   recording, held, out by three quarters. Name your own to show a button, a
   chart or a line: the same `s1-s2-s3-s4-f-x-y` as `zoom_video`, its seconds
   counted from the page loaded.
3. **Encode** — H.264 in yuv420p with its index first (`+faststart`), at a
   constant 30 frames a second: plays in every browser, phone and chat, and
   starts before it is downloaded.
4. **Keep** (with `--save`) — the MP4 goes into the person's Space (below); the
   answer gives its link.

To find a point, record once with `--zoom none`, take a frame with
`video_thumbnail`, read where the subject is, and record again with the zoom.
To zoom on a video you already have, use `zoom_video`.

## Keep it in the person's Space

`save_to_space` (or `--save` on `record_and_zoom`) keeps a file in the person's
Datalayer Space: a Dataset of the Space (`Videos` when unsaid), created with
its first file, listed on the Space's page under **Contents**. Each file saved
makes a new revision of the Dataset that keeps the files already in it; a file
saved again under the same name is its new version.

- The script sends the file to the agent runtime on the pod's loopback
  (`POST /api/v1/spaces/files`), which keeps it with the identity it holds for
  the person whose runtime it is. No token is asked for or sent: the script can
  reach only that person's Spaces.
- The default Space when none is named; `--space` takes a Space's uid or
  handle, `--folder` a folder in the Dataset, `--name` the file's name there,
  `--collection` another Dataset.
- When no Space can be reached — no default Space, a runtime without the
  person's identity, Contents refusing — the script says why and exits with 1.
  The local file stays where it is: say so, and give its path.

## Required Environment Variables

- None required.

## Required Software

- `pip install "datalayer-skills[skills-video]"` — imageio-ffmpeg and Playwright.
- `python -m playwright install chromium` once, for `record_page` (the runtime image carries it).
- ffmpeg on the system is used when `imageio-ffmpeg` is not installed.

## Invocation Contract

- Call `run_skill_script` with:
  - `skill_name`: `video`
  - `script_name`: one of `record_and_zoom`, `save_to_space`, `video_info`, `record_page`, `trim_video`, `zoom_video`, `transcode_video`, `optimize_video`, `video_thumbnail`, `video_to_gif`, `concat_videos`
- These scripts are positional-argument based. Use `args`, not `kwargs`; `record_and_zoom`, `save_to_space` and `zoom_video` also read options (`--zoom`, `--save`, `--trim`…), written in `args` after the positional ones.
- Times are in seconds; the output container follows the output file's extension (`.mp4`, `.webm`, `.gif`, `.png`).

## Scripts API

### `script_name: record_and_zoom`

- `args`: `["<url>", "<output mp4>"]`, then the options:
  - `"--seconds", "<10 when unsaid>"`, `"--width", "<1280>"`, `"--height", "<800>"` (made even)
  - `"--zoom", "<auto when unsaid, none, or s1-s2-s3-s4-f-x-y zooms separated by |>"`
  - `"--ease", "<smooth when unsaid, or linear>"`, `"--fps", "<30>"`, `"--crf", "<20>"`, `"--preset", "<medium>"`
  - `"--wait-until", "<networkidle when unsaid, load, domcontentloaded or commit>"`
  - `"--save"` to keep it in the Space, with `"--space", "<uid or handle>"`, `"--folder", "<folder>"`, `"--name", "<name>"`, `"--collection", "<Videos when unsaid>"`
- Output: JSON — `output`, `seconds`, `width`, `height`, `fps`, `zooms`, `ease`, `load_cut_seconds`, `bytes`, and with `--save` `saved`: the Space, the Dataset, the `path` and the `url` to open it.
- A zoom must end within the recording (`s4` at most `--seconds`).

Examples:

- Ten seconds of a page, the centre zoom, kept in the default Space:
  `args`: `["https://datalayer.ai", "datalayer.mp4", "--save"]`
- Eight seconds, a zoom to 2x on the upper-left quarter from 2 to 3 s, held until 5, out by 6, in a folder:
  `args`: `["https://datalayer.ai", "hero.mp4", "--seconds", "8", "--zoom", "2-3-5-6-2-0.25-0.75", "--save", "--folder", "launch"]`
- No zoom, a phone-sized recording:
  `args`: `["https://datalayer.ai", "phone.mp4", "--width", "390", "--height", "844", "--zoom", "none"]`

### `script_name: save_to_space`

- `args`: `["<file>"]`, then the options: `"--name", "<its own when unsaid>"`, `"--folder", "<the Dataset's root when unsaid>"`, `"--space", "<uid or handle; the default Space when unsaid>"`, `"--collection", "<Videos when unsaid>"`
- Output: JSON — `space` (`uid`, `handle`, `name`), `dataset` (`uid`, `name`), `path`, `object_uid`, `version_uid`, `revision_uid`, `bytes`, `media_type`, `url`.
- Any file the skill made: an MP4, a GIF, a PNG thumbnail.

### `script_name: video_info`

- `args`: `["<video>"]`
- Output: JSON — `seconds`, `bytes`, and each stream's `kind`, `codec`, `width`, `height`, `fps`.

### `script_name: record_page`

- `args`: `["<url>", "<output webm>", "<seconds, 10 when unsaid>", "<width, 1280 when unsaid>", "<height, 800 when unsaid>"]`
- Output: a WebM of the page from its load, for that many seconds. To share it, prefer `record_and_zoom`, which writes an MP4.

### `script_name: trim_video`

- `args`: `["<input video>", "<output video>", "<start seconds>", "<duration seconds>"]`
- Output: that clip, re-encoded so the cut is exact.

### `script_name: zoom_video`

- `args`: `["<input video>", "<output video>", "<zooms>"]`, then the options: `"--trim", "<START-END>"`, `"--ease", "<linear or smooth>"`, `"--crf", "<18 when unsaid>"`, `"--preset", "<medium when unsaid>"`
- Output: the video at its own size, zoomed in on a point and back out, once or several times; an `.mp4` (H.264, the audio copied) or a `.webm` (VP9, Opus).

A zoom is seven numbers joined by `-`: `s1-s2-s3-s4-f-x-y`. Several zooms are separated by `|`.

| Part | What it is |
|------|------------|
| `s1` | The second the zoom-in starts |
| `s2` | The second the zoom-in is complete |
| `s3` | The second the zoom-out starts (the picture stays zoomed from `s2` to `s3`) |
| `s4` | The second the zoom-out is complete |
| `f` | The zoom factor, 1 or more: `2` doubles the picture |
| `x` | The point zoomed on, across: `0` the left edge, `1` the right edge |
| `y` | The point zoomed on, up: `0` the bottom edge, `1` the top edge |

- The times must be `0 <= s1 < s2 <= s3 < s4`. Outside a zoom the picture is whole.
- The point is counted from the bottom-left corner. Near an edge the picture stops at the edge: nothing outside the video is shown.
- `--ease linear` (when unsaid) moves at a constant speed; `--ease smooth` starts and ends each move slowly.
- `--trim START-END` cuts the video to those seconds first. The zooms' times then count from the trim's start: with `--trim 10-25`, a zoom starting at `2` starts at second 12 of the input.
- `--crf` is the quality (lower is better and larger); `--preset` is H.264's (`medium`, `slow`, `fast`…).

Examples:

- Zoom to twice the size on the centre from second 2 to 3, hold until 6, back out by 7:
  `args`: `["demo.mp4", "demo_zoom.mp4", "2-3-6-7-2-0.5-0.5"]`
- Two zooms, the first on the centre, the second on the lower right:
  `args`: `["demo.mp4", "demo_zoom.mp4", "2-3-6-7-1.8-0.5-0.5|10-11-14-15-2.2-0.8-0.25"]`
- Keep seconds 1 to 13 only, and zoom smoothly on the top-left quarter:
  `args`: `["demo.mp4", "demo_zoom.mp4", "1-2-3-7-2-0.25-0.75", "--trim", "1-13", "--ease", "smooth"]`

To find the point, take a frame with `video_thumbnail` and read where the subject is: a subject 80 % across and a quarter up is `x` `0.8`, `y` `0.25`.

### `script_name: transcode_video`

- `args`: `["<input video>", "<output video>", "<width in pixels, kept when unsaid>", "<crf, 23 when unsaid>"]`
- Output: an `.mp4` (H.264, AAC, fast start) or a `.webm` (VP9, Opus), scaled to the width when one is given.

### `script_name: optimize_video`

- `args`: `["<input video>", "<output mp4>", "<crf, 28 when unsaid>", "<preset, slow when unsaid>"]`
- Output: a smaller H.264 at constant quality; says the bytes before and after.

### `script_name: video_thumbnail`

- `args`: `["<input video>", "<seconds>", "<output png>"]`
- Output: the frame at that time, as a PNG.

### `script_name: video_to_gif`

- `args`: `["<input video>", "<output gif>", "<start seconds>", "<duration seconds>", "<fps, 12 when unsaid>", "<width, 480 when unsaid>"]`
- Output: an optimized GIF of that clip, a palette made from it first.

### `script_name: concat_videos`

- `args`: `["<output video>", "<input video>", "<input video>", ...]`
- Output: the videos one after the other, re-encoded to one codec.
