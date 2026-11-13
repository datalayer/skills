<!--
  ~ Copyright (c) 2025-2026 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Changelog

## 0.4.0

13 November 2026.

- **Video: record a page, zoom, share.** The `video` skill's new `record_and_zoom` script records a page with a headless Chromium from the moment it has loaded (the blank seconds of its loading cut), zooms in and out on it with eased moves (`--zoom`: `auto` when unsaid, one zoom on the centre to 1.5x over the middle half; `none`; or `zoom_video`'s `s1-s2-s3-s4-f-x-y` zooms), and writes an MP4 anyone can play: H.264, yuv420p, `+faststart`, at a constant frame rate (`--fps`, 30). Options `--seconds`, `--width`, `--height`, `--ease` (`smooth`), `--crf`, `--preset`, `--wait-until`. It prints what it made as JSON.
- **Video: kept in the person's Space.** `save_to_space <file>`, or `--save` on `record_and_zoom`, keeps a file in the person's Datalayer Space: it is sent to the agent runtime on the pod's loopback (`POST /api/v1/spaces/files`, agent-runtimes), which keeps it with the identity it holds for the runtime's owner in a Dataset of their default Space (`Videos` when unsaid; `--space`, `--folder`, `--name`, `--collection`), each file a new revision of the Dataset; the answer gives the Space, the Dataset, the path and the link. No token is asked for or sent. When no Space can be reached the script says why, exits with 1, and the local file stays.

## 0.3.0

12 November 2026.

- **The catalogue's skills live here.** `accounting`, `crawl`, `events`, `github`, `image`, `pdf`, `text-summarizer` and `video` move from agent-skills (where they were `agent_skills.skills.<name>` until 1.3.0) to `datalayer_skills.skills.<name>`, under the same skill names, each declared as an `agent_skills.skills` entry point like the memory skills. Their dependencies move with them, as the extras `skills-accounting`, `skills-crawl`, `skills-github`, `skills-pdf`, `skills-image`, `skills-video`, and `skills` for all. Whoever named a module names the new one: nothing is left behind in agent-skills, which from 1.4.0 is the framework alone.
- **Video: zoom in and out.** The `video` skill's new `zoom_video` script zooms in on a point of a video and back out, once or several times, at the video's own size. A zoom is `s1-s2-s3-s4-f-x-y` (zoom-in from `s1` to `s2` seconds, held until `s3`, zoom-out complete at `s4`; the factor; the point from 0 to 1 from the bottom-left corner), several separated by `|`. Options: `--ease linear` or `smooth`, `--trim START-END`, `--crf`, `--preset`. An `.mp4` is H.264 with the audio copied, a `.webm` VP9 with Opus.

## 0.2.0

8 November 2026.

- **Memory skills.** `datalayer-memory-add`, `-search`, `-list` and `-delete` keep, search, list and forget the person's memory of the agent, through the agent runtime's memory routes on the pod's loopback.
