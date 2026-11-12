<!--
  ~ Copyright (c) 2025-2026 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Changelog

## 0.3.0

12 November 2026.

- **The catalogue's skills live here.** `accounting`, `crawl`, `events`, `github`, `image`, `pdf`, `text-summarizer` and `video` move from agent-skills (where they were `agent_skills.skills.<name>` until 1.3.0) to `datalayer_skills.skills.<name>`, under the same skill names, each declared as an `agent_skills.skills` entry point like the memory skills. Their dependencies move with them, as the extras `skills-accounting`, `skills-crawl`, `skills-github`, `skills-pdf`, `skills-image`, `skills-video`, and `skills` for all. Whoever named a module names the new one: nothing is left behind in agent-skills, which from 1.4.0 is the framework alone.
- **Video: zoom in and out.** The `video` skill's new `zoom_video` script zooms in on a point of a video and back out, once or several times, at the video's own size. A zoom is `s1-s2-s3-s4-f-x-y` (zoom-in from `s1` to `s2` seconds, held until `s3`, zoom-out complete at `s4`; the factor; the point from 0 to 1 from the bottom-left corner), several separated by `|`. Options: `--ease linear` or `smooth`, `--trim START-END`, `--crf`, `--preset`. An `.mp4` is H.264 with the audio copied, a `.webm` VP9 with Opus.

## 0.2.0

8 November 2026.

- **Memory skills.** `datalayer-memory-add`, `-search`, `-list` and `-delete` keep, search, list and forget the person's memory of the agent, through the agent runtime's memory routes on the pod's loopback.
