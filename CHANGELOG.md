<!--
  ~ Copyright (c) 2025-2026 Datalayer, Inc.
  ~
  ~ BSD 3-Clause License
-->

# Changelog

## 0.7.12

25 November 2026.

- **`datalayer-email`'s timeout setting is held to a number too.** `DATALAYER_EMAIL_TIMEOUT_SECONDS` set to something that is no number of seconds above 0 ended in a traceback; it is refused in a sentence before anything is sent, as the events and whoami settings are since 0.7.11.

## 0.7.11

25 November 2026. Review of 0.7.10.

- **A key reaches the one host it was sent to.** With `DATALAYER_API_KEY`, `events` built urllib's default opener, which follows a redirect and keeps the `Authorization` header when the destination is another host or plain HTTP. No request of `events` or `datalayer-whoami` follows a redirect any more, with a key or to the runtime: the script says where the redirect pointed and sends nothing there. A key is not sent over plain HTTP to another machine either (the runtime on the loopback, which is sent no key, stays reachable over HTTP). A test holds every script that puts a credential in a header with urllib to an opener that follows no redirect.
- **A stalled or truncated answer is a sentence, never a traceback.** A timeout, a dropped connection or an answer cut short, on the answer or on a refusal's body, is said as the script's own refusal (exit code 1) in `events`, `datalayer-whoami` and the five memory scripts. After a `create` or an `update` of `events`, the sentence says the write may already have been made and how to check; nothing is sent twice. `datalayer-library-publish` says the same of a publication the runtime did not confirm. `DATALAYER_EVENTS_TIMEOUT_SECONDS` and `DATALAYER_WHOAMI_TIMEOUT_SECONDS` set how long each waits (30 seconds); a value that is no number of seconds above 0 is refused in a sentence before anything is sent.
- **An answer that is not what was asked for is refused, not read as an empty success.** `null`, a list or an object without its event from the runtime or the events API ended a memory command or an events command with exit code 0 and nothing in it; each is the script's refusal now. A publication whose refusal arrives cut short says the item may be public already.

## 0.7.10

25 November 2026.

- **The skills that act as the account ask the runtime, not the sandbox, for the identity.** `datalayer-whoami` and `events` read `DATALAYER_API_KEY` from the sandbox's environment, where a Datalayer runtime puts none: the key is the platform's, and a runtime handed to a hosted application or kept running holds no key at all. Their scripts now ask the agent runtime they run beside, on the pod's loopback (`GET /api/v1/owner`, `/api/v1/owner/events`, agent-runtimes 1.8.7), as `datalayer-email` and `datalayer-library-publish` already did; the runtime acts with the identity it holds, and no credential reaches the sandbox. Neither skill requires a variable any more (`env.required` is gone from their `SKILL.md`), so both are offered in a runtime without a key, and a runtime that runs for nobody answers a sentence saying so. A runtime that serves an application to other people says its owner's public face: no email, no roles.
- **By hand, the key still works.** With `DATALAYER_API_KEY` (and, for `datalayer-whoami`, `DATALAYER_RUN_URL`), a script run outside a runtime calls the platform itself, as before.
- **`events` calls the events API where it is.** With a key it called `/api/ai-agents/v1/events` on a host AI Agents no longer runs on; it calls `/api/ai-agents/v1/agents/{agent_id}/events` on `https://r1.datalayer.run` (or `DATALAYER_AI_AGENTS_URL`), `get` and `update` take `agent_id`, and the script uses the standard library alone.

## 0.7.9

25 November 2026.

- **Every skill says what it does and when to use it.** `crawl`, `events`, `github`, `image`, `pdf`, `text-summarizer`, `video` and `datalayer-whoami` get a description in the shape of the others: what the skill does, in a sentence a person can read in a list of skills, then when to use it. `datalayer-whoami` names what its script returns (handle, name, email, roles, avatar). `pdf` gets the version, tags and author every other skill has. A page that lists an agent's skills takes each one's display name, icon and menu description from the agentspecs skills catalogue, which now has an entry for all nineteen, the four memory skills and `datalayer-whoami` included. A test holds each of the nineteen to a description of a sentence or two, tags, a version and an author.

## 0.7.8

23 November 2026.

- **Publish owned items to the public Library.** `datalayer-library-publish` publishes an existing notebook, document, cell, spreadsheet, deck, learning item, dataset, benchmark, agent, data server, environment, report, investigation, evaluator or application through the owning agent runtime. It requires the person's explicit confirmation immediately before publishing, exposes no credential to the sandbox and returns the public Library URL.

## 0.7.7

18 November 2026.

- **Stock images, the doc says every outcome.** When the folder is moved out while the image is written, an empty or zero-filled file may remain in it, or, when its bytes cannot be removed, the image itself, as the refusal says: a refusal is not a promise that no image data is left outside the working directory.

## 0.7.6

18 November 2026.

- **Stock images, nothing removed by name.** When the folder is moved out of the working directory while the image is written, the image's bytes are destroyed through its own descriptor (emptied, or overwritten with zeros when it cannot be emptied), and no name is removed or renamed, since another writer may have put its own file under it. The refusal says what may remain in the moved folder, the case where the bytes could not be removed included; it is always a refusal, never a traceback.

## 0.7.5

18 November 2026.

- **Stock images, the written file held until checked.** The image's descriptor stays open until the check and any cleanup are done, so its inode cannot pass to a file made in its place. A cleanup empties the image through its own descriptor, then moves its name aside to a name of its own and removes it only there, once proven to be it; another writer's file, even one that ignored the folder's lock, is put back under its name, never deleted.

## 0.7.4

18 November 2026.

- **Stock images, only its own bytes.** A download knows the file it wrote by its own descriptor, and holds the folder's lock from the rename to the check: when another writer replaced or removed the image meanwhile, it says so instead of reporting their bytes as its own, and a cleanup removes only the file it wrote. A destination gone after the rename is a refusal, never a traceback.

## 0.7.3

18 November 2026.

- **Stock images, a folder moved while open.** Before the write, the open folder must still be the one at its path; after it, the file written must be the one at the path returned, else it is removed through the open folder and the download refused, so nothing is left outside the workspace and no path is returned where no file is.
- **A lock per state file.** Each state file has a thread lock of its own: a slow Pixabay request, which holds its cache's lock, no longer holds up another provider's count in a search of every provider.

## 0.7.2

18 November 2026.

- **Stock images, the folder reached by descriptors.** A download's folder is opened from the workspace one name at a time, each made when missing and none a link, so where the file lands no longer depends on `/proc` (macOS too) and a folder swapped for a link meanwhile is refused. Every symlinked folder is refused, even one pointing inside the workspace.
- **A temporary file of its own.** Each write draws a name of its own and removes only the file it made.
- **Pixabay asked once.** The lookup, the request on a miss and the answer kept run under one lock: two searches of the same page ask Pixabay once, and the answer kept keeps its first day.
- **`datalayer-whoami`** takes `--run_url` and `--api_key`, as `run_skill_script` sends them.

## 0.7.1

18 November 2026.

- **Stock images, safer downloads.** A download connects to the public address it checked, the name resolved once (no second answer of the name is asked for), redirects included and no proxy; a Freepik file and its redirects come from Freepik's own hosts alone (`freepik.com`, `magnific.com`). The file is written under the working directory for good: its final name (extension included) checked, written beside it and renamed, so a link at the path is replaced and never followed, and a folder leading out of it is refused.
- **Unsplash told first.** An Unsplash download is reported before the image is fetched: when it cannot be, the image is not downloaded and the refusal says why (no file with a warning any more).
- **Credits.** An author's name without a link is escaped in the HTML line too. `image_attribution` takes `author_url`, `page_url` and `license_type` as `run_skill_script` sends them, with underscores.
- **Limits kept whole.** A request whose count cannot be saved is not sent. Every count, and the Pixabay answers kept, are read and written under a lock shared by the skill's processes. A provider's wait is kept whole: its `Retry-After` or reset on a 429, and a reset of more than an hour too.
- **Pixabay.** Pages of 1 or 2 results follow each other with none skipped. Every answer of the day is kept, however many searches.
- **`datalayer-whoami`** is activated with `DATALAYER_API_KEY`; `DATALAYER_RUN_URL` is optional, as the `run_url` kwarg gives it too.

## 0.7.0

18 November 2026.

- **Stock images.** `image-stock` searches stock photos on Unsplash, Pexels, Pixabay and Freepik: `search_images "<query>"` on one provider or on every configured one (results merged, one of each provider in turn, in one shape: `id`, `provider`, `title`, `author`, `author_url`, `page_url`, `preview_url`, `full_url`, `width`, `height`, `license`, `credit_required`, `credit`), `list_providers` (which are configured, with their limits and terms), `image_attribution` (the credit line a provider asks for, as text, Markdown and HTML) and `download_image` (a photo into the workspace). Every variable is optional and one key is enough: `UNSPLASH_ACCESS_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `FREEPIK_API_KEY`; a provider without its key is not offered, and with no key the skill is not activated. It keeps to each provider's terms: its published rate limit counted between runs (50 or 1000 an hour for Unsplash by `UNSPLASH_TIER`, 200 an hour for Pexels, 100 a minute for Pixabay, `FREEPIK_REQUESTS_PER_MINUTE` or 30 for Freepik), the credit in the provider's form, an Unsplash download reported to Unsplash, a Pixabay answer kept a day and its images downloaded rather than linked. A key goes to its provider's API host alone, with no redirect followed; an image comes over https from the provider's image hosts, up to 40 MB, under the working directory; no message carries a key or a request's address. Standard library only.
- **Skills say the environment they need.** `github` (`GITHUB_TOKEN`), `events` (`DATALAYER_API_KEY`; `DATALAYER_AI_AGENTS_URL` is optional and no longer read as required) and `datalayer-whoami` declare it in their frontmatter's `env`, as `image-stock` declares its keys under `env.any_of`. With `agent_skills>=1.5.0`, now required, a skill without its environment is not offered to the agent: not listed, not run.

## 0.6.1

15 November 2026.

- **Email: an unconfirmed delivery is said, never reported as a failure.** `send_email` exits `3` with *Delivery could not be confirmed … Do not send it again* when the runtime may have sent the mail without confirming it: a gateway error with no reason of the runtime's, a dropped connection, a timeout, a body cut short or unreadable, an answer that does not say `sent`. Only the runtime's own refusal or a refused connection says nothing was sent (exit `1`). Never a traceback, never retried. The wait is `DATALAYER_EMAIL_TIMEOUT_SECONDS` (60 unless set). Review of #5 and #6.

## 0.6.0

15 November 2026.

- **Email, through Datalayer's mailer.** `datalayer-email`'s `send_email --subject … --text …` sends the person whose agent this is one email (the user: "for email, you can create a skill in the datalayer-skill repo and use it"). It asks the agent runtime on the pod's loopback (`POST /api/v1/configure/mail`, agent-runtimes 1.6.65), which sends it with the runtime's own short-lived token through Datalayer's IAM (`/social/mail`, IAM 1.1.124): to the person alone, at their account's address, never an address the agent names, at most ten a day for one person's agents. No mail credential is in the sandbox or the runtime. A refusal is said in its sentence, with exit code 1. Standard library only.

## 0.5.0

15 November 2026.

- **Travel skills, for the Voyager.** `travel-planning` (what to ask before searching — dates, places, travellers, preferences, budget — then three trip options, each with its transport, stay, daily schedule and travel times, a Google Maps link, a budget with its total and per person, and the booking links), `fare-and-stay-comparison` (flights by route, times, fare, baggage, fare with bags and risks; stays by place, price per night and in total, rating, amenities and cancellation; one recommendation) and `dining` (restaurants, sights and stops along a route placed in the day, with their Maps links). Instructions alone, no scripts, public. Each says never to book or pay, to hand over the booking links, that a price is a quote that can change, and to quote only what the tools returned.

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
