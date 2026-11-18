---
name: image-stock
description: Find stock photos on Unsplash, Pexels, Pixabay and Freepik (the ones the person has a key for), get the credit line each provider asks for, and download a photo into the workspace. Use it when a post, a page or a document needs a picture.
license: BSD-3-Clause
version: 1.0.0
tags:
  - image
  - photo
  - stock
  - media
author: Datalayer
env:
  optional:
    - UNSPLASH_TIER
    - UNSPLASH_APP_NAME
    - FREEPIK_REQUESTS_PER_MINUTE
    - IMAGE_STOCK_DEFAULT_PROVIDER
    - IMAGE_STOCK_DOWNLOAD_DIR
    - IMAGE_STOCK_TIMEOUT_SECONDS
  any_of:
    - UNSPLASH_ACCESS_KEY
    - PEXELS_API_KEY
    - PIXABAY_API_KEY
    - FREEPIK_API_KEY
---

# Stock Images

Searches stock photos on the providers the person has a key for, in one shape
whatever the provider, writes the credit line a provider's terms ask for, and
downloads a photo into the workspace.

## Providers and their keys

Each provider is offered only when its key is set. The skill itself is
activated when one key at least is set; with none it is not offered at all.

| Provider | Key | Limit | Credit |
| --- | --- | --- | --- |
| Unsplash | `UNSPLASH_ACCESS_KEY` | 50 requests an hour (1000 with `UNSPLASH_TIER=production`) | required |
| Pexels | `PEXELS_API_KEY` | 200 requests an hour | required |
| Pixabay | `PIXABAY_API_KEY` | 100 requests a minute | appreciated |
| Freepik | `FREEPIK_API_KEY` | 30 requests a minute unless set | required for free resources |

Run `list_providers` first: it says which providers are configured in this
run. `search_images` with `provider: all` searches exactly those.

## Optional Environment Variables

- `UNSPLASH_ACCESS_KEY`, `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `FREEPIK_API_KEY`: one key per provider; one is enough.
- `UNSPLASH_TIER`: `production` when Unsplash approved the application (1000 requests an hour); `demo` otherwise (50).
- `UNSPLASH_APP_NAME`: the application's name at Unsplash, written in the links back to Unsplash.
- `FREEPIK_REQUESTS_PER_MINUTE`: the limit kept for Freepik (30 unless set).
- `IMAGE_STOCK_DEFAULT_PROVIDER`: the provider searched when none is named and it is configured; all of them otherwise.
- `IMAGE_STOCK_DOWNLOAD_DIR`: the folder downloads go to, under the working directory (`images` unless set).
- `IMAGE_STOCK_TIMEOUT_SECONDS`: the wait for a provider, 1 to 25 (10 unless set).

## Required Software

- None beyond Python: the scripts use the standard library only.

## What you must do with a picture

- **Credit it.** When `credit_required` is true (Unsplash, Pexels, a free
  Freepik resource), put the credit line where the picture is used: under it,
  in the post's text, or in the page's credits. Get the line from
  `image_attribution` (text, Markdown or HTML) and keep its links. For Pixabay
  the credit is appreciated: add it unless the person says not to.
- **Say where results come from.** When you show search results, name the
  provider of each (Pexels and Pixabay ask for it) with its link.
- **Unsplash: show from its URL, download to use.** To show an Unsplash photo
  in a page, use the URL returned, unchanged. Download it only when the
  picture is actually used (attached to a post, inserted in a document), with
  `download_image`, which reports the download to Unsplash as its guidelines
  ask. Pass the result's `download_location`.
- **Pixabay: download, never link for good.** Its image URLs are for showing
  results and stop working after a day: download the picture to use it.
- **Freepik: by id.** The file comes from `download_image` with the id; a
  premium resource downloads only with a plan that allows it.
- **Do not collect.** Search for what the task needs; never download results
  in bulk, and never work around a provider's limit: when one is reached, say
  so or use another provider.
- Never show or log a key. The scripts never print one.

## Invocation Contract

- Call `run_skill_script` with `skill_name`: `image-stock` and `script_name`: one of `list_providers`, `search_images`, `image_attribution`, `download_image`.
- Pass the search query as the one positional `args` item; everything else through `kwargs`, with the keys documented below.
- Each script prints JSON. A refusal is `Error: ...` on stderr with exit code `1`.

## Scripts API

### `script_name: list_providers`

- Purpose: which providers are configured here, with their limits and terms.
- `args`: none. `kwargs`: none.
- Prints `{"configured": [...], "not_configured": [{"provider", "set"}], "providers": [{"provider", "name", "license", "credit", "terms", "rate_limit", "max_per_page"}]}`.

### `script_name: search_images`

- Purpose: search one provider, or every configured provider with the results merged.
- Positional `args`: `["<query>"]`.
- Supported `kwargs`:
  - `provider`: `unsplash | pexels | pixabay | freepik | all` (default: all configured).
  - `per_page`: results per provider, 1 to 30 (default 5).
  - `page`: the page of results (default 1).
  - `orientation`: `landscape | portrait | square` (Pixabay has no square and ignores it).
- Prints `{"query", "page", "providers", "count", "results": [...], "failed": {provider: reason}, "terms": {provider: text}}`.
- Each result: `id`, `provider`, `title`, `author`, `author_url`, `page_url`, `preview_url`, `full_url`, `width`, `height`, `license`, `credit_required`, `credit`; an Unsplash result also has `download_location`, a Freepik one `license_type` (`freemium` or `premium`) and no `full_url`, `width` or `height`.
- With `all`, results alternate between providers; a provider that fails is named under `failed` and the others still answer.

### `script_name: image_attribution`

- Purpose: the credit line for one image, in the form its provider asks for.
- Positional `args`: none.
- Supported `kwargs`: `provider` (required), `author`, `author_url`, `page_url`, `license_type` (Freepik), each as `search_images` returned it.
- Prints `{"provider", "required", "rule", "text", "markdown", "html", "terms"}`.

### `script_name: download_image`

- Purpose: download one image into the workspace.
- Positional `args`: none.
- Supported `kwargs`:
  - `provider` (required), `id` (required).
  - `url`: the result's `full_url` (not needed for Freepik).
  - `output`: a relative path under the working directory (default `images/<provider>-<id>` with the image's extension).
  - `download_location`: Unsplash only, the result's `download_location`.
- Prints `{"provider", "id", "path", "bytes", "content_type", "credit", "next"}`, and `reported_to_unsplash` for Unsplash.
- An Unsplash download is reported to Unsplash first: when it cannot be, the image is not downloaded and the refusal says why.
- An image is fetched over https from the provider's own image hosts alone (Freepik's on `freepik.com` or `magnific.com`), redirects included, each connection made to the public address checked, up to 40 MB.
- The file is written under the working directory alone: a link at the path is replaced, never followed, and a folder that is a link is refused, even one pointing inside it: give a real folder. A folder moved out of it while the image is written gets a refusal. The image's bytes are then destroyed through the file's own descriptor when they can be, so an empty or zero-filled file may remain in that folder; when they cannot be, the refusal says so, and the image itself may remain there. A refusal is not a promise that no image data is left outside the working directory: read its sentence.

## Common Failure Modes

- `Error: <provider> has no key set here. Configured: ...`: use a configured provider, or `all`.
- `Error: <Provider> rate limit reached ...: try again in N s`: wait, or use another provider. Do not retry in a loop.
- `Error: <Provider> refused the key in <NAME> (HTTP 401)`: the person's key is wrong or revoked; tell them which variable, never its value.
- `Error: ... is not where this provider serves its images`: pass the `full_url` exactly as `search_images` returned it.
- `Error: the download could not be reported to Unsplash, so the image was not downloaded ...`: try again later, or use another provider.
- `Error: the image-stock state could not be saved ...`: the counts of requests cannot be kept, so none is sent; `IMAGE_STOCK_STATE_DIR` must name a folder that can be written.
- Exit code `2`: an unknown `kwargs` key or a missing one.
