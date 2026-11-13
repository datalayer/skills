# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Record a web page and zoom in and out on it, as an MP4 ready to share.

One flow, in three steps:

1. **Record** the page with a headless Chromium (Playwright), from the moment it
   has loaded: the blank seconds of its loading are cut, second 0 is the page.
2. **Zoom** in on a point and back out, once or several times, the moves eased
   (`smooth` when unsaid). With no zoom given, one zoom on the centre, to 1.5x,
   in from a quarter of the recording, held, and out by three quarters.
3. **Encode** an MP4 anyone can play: H.264, yuv420p, the index first
   (`+faststart`) so it starts playing before it is downloaded, at a constant
   frame rate (30 when unsaid) so the zooms move smoothly.

With `--save`, the MP4 is then kept in the person's Datalayer Space through the
agent runtime on the pod's loopback (see `save_to_space`); the local file stays.

Usage:
    python record_and_zoom.py <url> <output.mp4> [--seconds 10] [--width 1280]
        [--height 800] [--zoom auto|none|s1-s2-s3-s4-f-x-y|...] [--ease smooth]
        [--fps 30] [--crf 20] [--preset medium] [--wait-until networkidle]
        [--save] [--space SPACE] [--folder FOLDER] [--name NAME] [--collection Videos]
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

# ---- The zoom (the same block in zoom_video and record_and_zoom) ----
#
# A skill script is sent to the sandbox as its own source and run there, so it
# imports nothing of this package: this block is repeated in each script that
# zooms, and a test holds the copies identical.

EASES = ("linear", "smooth")


def ffmpeg_binary():
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        found = shutil.which("ffmpeg")
        if not found:
            raise RuntimeError(
                "ffmpeg is not installed: pip install imageio-ffmpeg, or install ffmpeg"
            )
        return found


def number(value):
    """A number as ffmpeg's expressions read it: no exponent, no trailing zeros."""
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def parse_zooms(spec):
    """The zooms of `s1-s2-s3-s4-f-x-y|…`, each checked; a ValueError says what is wrong."""
    zooms = []
    for item in [part.strip() for part in str(spec).split("|") if part.strip()]:
        parts = item.split("-")
        if len(parts) != 7:
            raise ValueError(f"Invalid zoom {item!r}: expected s1-s2-s3-s4-f-x-y")
        try:
            s1, s2, s3, s4, factor, x, y = (float(part) for part in parts)
        except ValueError:
            raise ValueError(f"Invalid zoom {item!r}: every value is a number") from None
        if not (0 <= s1 < s2 <= s3 < s4):
            raise ValueError(f"Invalid zoom {item!r}: the times must be 0 <= s1 < s2 <= s3 < s4")
        if factor < 1:
            raise ValueError(f"Invalid zoom {item!r}: the factor must be 1 or more")
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"Invalid zoom {item!r}: x and y go from 0 to 1")
        zooms.append({"s1": s1, "s2": s2, "s3": s3, "s4": s4, "factor": factor, "x": x, "y": y})
    if not zooms:
        raise ValueError("No zoom given: expected s1-s2-s3-s4-f-x-y, several separated by |")
    return zooms


def parse_trim(spec):
    """The (start, end) of `START-END` in seconds, or None when there is no trim."""
    if spec is None or str(spec).strip() == "":
        return None
    parts = str(spec).split("-")
    try:
        start, end = (float(part) for part in parts)
    except ValueError:
        raise ValueError(f"Invalid trim {spec!r}: expected START-END in seconds") from None
    if start < 0 or end <= start:
        raise ValueError(f"Invalid trim {spec!r}: expected END > START and START >= 0")
    return start, end


def progress(start, end, ease):
    """How far the time is between start and end, from 0 to 1, as an ffmpeg expression."""
    linear = f"(t-{number(start)})/({number(end)}-{number(start)})"
    if ease == "linear":
        return linear
    if ease == "smooth":
        # Smoothstep: starts and ends slowly, 3p^2 - 2p^3.
        return f"({linear})*({linear})*(3-2*({linear}))"
    raise ValueError(f"Invalid ease {ease!r}: one of {', '.join(EASES)}")


def zoom_expression(zoom, ease="linear"):
    """The zoom factor at time t: 1 before s1, up to the factor between s1 and s2, the factor
    until s3, back to 1 between s3 and s4, 1 after."""
    s1, s2, s3, s4 = (number(zoom[key]) for key in ("s1", "s2", "s3", "s4"))
    factor = number(zoom["factor"])
    zoom_in = f"1+({factor}-1)*{progress(zoom['s1'], zoom['s2'], ease)}"
    zoom_out = f"{factor}-({factor}-1)*{progress(zoom['s3'], zoom['s4'], ease)}"
    return (
        f"if(between(t,{s1},{s2}),{zoom_in},"
        f"if(between(t,{s2},{s3}),{factor},"
        f"if(between(t,{s3},{s4}),{zoom_out},1)))"
    )


def escape(expression):
    """ffmpeg's filter parser reads a comma as the next filter unless it is escaped."""
    return expression.replace(",", "\\,")


def build_filter(width, height, zooms, ease="linear"):
    """The -vf filter: for each zoom, the frame scaled by its factor, then cropped back to the
    video's size around the point."""
    segments = []
    for zoom in zooms:
        z = zoom_expression(zoom, ease)
        scaled_w = f"{width}*{z}"
        scaled_h = f"{height}*{z}"
        # The point is given from the bottom-left corner; ffmpeg counts y from the top.
        x = f"({number(zoom['x'])}*{scaled_w})-({width}/2)"
        y = f"({number(1 - zoom['y'])}*{scaled_h})-({height}/2)"
        # The crop never leaves the scaled frame.
        x = f"max(0,min({x},{scaled_w}-{width}))"
        y = f"max(0,min({y},{scaled_h}-{height}))"
        segments.append(
            f"scale=w={escape(scaled_w)}:h={escape(scaled_h)}:eval=frame,"
            f"crop=w={width}:h={height}:x={escape(x)}:y={escape(y)}"
        )
    return ",".join(segments)


# ---- End of the zoom ----


# ---- The Space (the same block in save_to_space and record_and_zoom) ----
#
# A skill script is sent to the sandbox as its own source and run there, so it
# imports nothing of this package: this block is repeated in each script that
# keeps a file in the Space, and a test holds the copies identical.

SPACE_FILES_API = "/api/v1/spaces/files"
SPACE_COLLECTION = "Videos"


class SpaceRefused(Exception):
    """Why the file was not kept in the Space, in the runtime's sentence."""


def runtime_url(explicit=""):
    """The agent runtime's URL: given, AGENT_RUNTIMES_URL, else its port on the loopback."""
    import os

    url = (explicit or os.environ.get("AGENT_RUNTIMES_URL", "")).strip()
    if not url:
        port = os.environ.get("AGENT_RUNTIMES_PORT", "").strip() or "8765"
        url = f"http://127.0.0.1:{port}"
    return url.rstrip("/")


def save_to_space(
    path, name="", folder="", space="", collection=SPACE_COLLECTION, runtime="", timeout=600
):
    """Send the file to the runtime, which keeps it in the person's Space; its answer."""
    import mimetypes
    import os
    import urllib.error
    import urllib.parse
    import urllib.request

    if not os.path.isfile(path):
        raise SpaceRefused(f"There is no file at {path}.")
    size = os.path.getsize(path)
    if size == 0:
        raise SpaceRefused(f"{path} is empty: nothing to keep.")
    name = name or os.path.basename(path)
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    query = {"name": name, "folder": folder, "collection": collection, "media_type": media_type}
    if space:
        query["space"] = space
    base = runtime_url(runtime)
    url = f"{base}{SPACE_FILES_API}?{urllib.parse.urlencode(query)}"
    # Never through a proxy: the runtime is in this pod.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with open(path, "rb") as stream:
        request = urllib.request.Request(
            url,
            data=stream,
            method="POST",
            headers={
                "Content-Type": media_type,
                "Content-Length": str(size),
                "Accept": "application/json",
            },
        )
        try:
            with opener.open(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                detail = json.loads(raw or b"{}").get("detail") or ""
            except ValueError:
                detail = raw.decode(errors="replace").strip()
            if not isinstance(detail, str):
                detail = json.dumps(detail)
            raise SpaceRefused(detail or f"The runtime answered {error.code}.") from error
        except urllib.error.URLError as error:
            raise SpaceRefused(
                f"The agent runtime at {base} cannot be reached: {error.reason}."
            ) from error
        except (OSError, http.client.HTTPException) as error:
            # A runtime that stalls while answering, or drops the connection before
            # it does (TimeoutError, RemoteDisconnected, IncompleteRead): refused
            # like any other, so the local file is kept and said.
            raise SpaceRefused(
                f"The agent runtime at {base} did not answer: {type(error).__name__}."
            ) from error
    try:
        return json.loads(raw or b"{}")
    except ValueError as error:
        raise SpaceRefused(
            f"The agent runtime at {base} answered something that is not JSON."
        ) from error


# ---- End of the Space ----


WAIT_UNTIL = ("load", "domcontentloaded", "networkidle", "commit")

#: The zoom given when none is: on the centre, to 1.5x, over the middle half.
AUTO_FACTOR = 1.5


def even(value):
    """yuv420p halves the colour planes: the picture's sides are even."""
    return max(2, int(value) // 2 * 2)


def auto_zoom(seconds):
    """One zoom on the centre: in from a quarter of the recording to 35 %, held until
    65 %, out by three quarters."""
    marks = [round(seconds * share, 3) for share in (0.25, 0.35, 0.65, 0.75)]
    return "-".join(number(value) for value in [*marks, AUTO_FACTOR, 0.5, 0.5])


def zooms_for(spec, seconds):
    """The zooms of the spec: `auto` the centre zoom, `none` (or empty) none at all."""
    text = (spec or "").strip().lower()
    if text in ("", "none", "no", "off"):
        return []
    if text == "auto":
        return parse_zooms(auto_zoom(seconds))
    zooms = parse_zooms(spec)
    for zoom in zooms:
        if zoom["s4"] > seconds:
            raise ValueError(
                f"A zoom ends at {number(zoom['s4'])} s, after the recording's {number(seconds)} s"
            )
    return zooms


def record(url, webm_path, seconds, width, height, wait_until="networkidle"):
    """The page recorded as a WebM; answers the second it had loaded at, in the recording."""
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as folder, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                record_video_dir=folder,
                record_video_size={"width": width, "height": height},
            )
            page = context.new_page()
            started = time.monotonic()
            page.goto(url, wait_until=wait_until)
            loaded = time.monotonic() - started
            page.wait_for_timeout(int(seconds * 1000))
            recorded = page.video.path() if page.video else None
            context.close()
        finally:
            browser.close()
        if not recorded or not os.path.exists(recorded):
            raise RuntimeError("No video was recorded")
        shutil.move(recorded, webm_path)
    return loaded


def encode_arguments(
    input_path, output_path, start, seconds, width, height, zooms, ease, fps, crf, preset
):
    """ffmpeg's arguments: from `start` for `seconds`, at a constant frame rate, zoomed,
    as an H.264 MP4 in yuv420p with its index first, without sound."""
    filters = [f"fps={int(fps)}"]
    if zooms:
        filters.append(build_filter(width, height, zooms, ease))
    return [
        "-ss",
        number(start),
        "-i",
        input_path,
        "-t",
        number(seconds),
        "-vf",
        ",".join(filters),
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        output_path,
    ]


def encode(input_path, output_path, start, seconds, width, height, zooms, ease, fps, crf, preset):
    command = [
        ffmpeg_binary(),
        "-y",
        *encode_arguments(
            input_path, output_path, start, seconds, width, height, zooms, ease, fps, crf, preset
        ),
    ]
    completed = subprocess.run(command, capture_output=True, check=False, text=True)
    if completed.returncode != 0:
        lines = completed.stderr.strip().splitlines()
        raise RuntimeError(lines[-1] if lines else "ffmpeg failed")


def record_and_zoom(
    url,
    output_path,
    seconds=10.0,
    width=1280,
    height=800,
    zoom="auto",
    ease="smooth",
    fps=30,
    crf=20,
    preset="medium",
    wait_until="networkidle",
):
    """Record, zoom and encode; what was made."""
    if not output_path.lower().endswith(".mp4"):
        raise ValueError(f"The output is an .mp4, not {os.path.basename(output_path)}")
    if seconds <= 0:
        raise ValueError("The recording lasts more than 0 seconds")
    if ease not in EASES:
        raise ValueError(f"Invalid ease {ease!r}: one of {', '.join(EASES)}")
    if wait_until not in WAIT_UNTIL:
        raise ValueError(f"Invalid --wait-until {wait_until!r}: one of {', '.join(WAIT_UNTIL)}")
    width, height = even(width), even(height)
    zooms = zooms_for(zoom, seconds)
    with tempfile.TemporaryDirectory() as folder:
        webm = os.path.join(folder, "recording.webm")
        loaded = record(url, webm, seconds, width, height, wait_until)
        encode(webm, output_path, loaded, seconds, width, height, zooms, ease, fps, crf, preset)
    return {
        "output": output_path,
        "url": url,
        "seconds": seconds,
        "width": width,
        "height": height,
        "fps": int(fps),
        "zooms": [
            "-".join(number(z[key]) for key in ("s1", "s2", "s3", "s4", "factor", "x", "y"))
            for z in zooms
        ],
        "ease": ease,
        "load_cut_seconds": round(loaded, 3),
        "bytes": os.path.getsize(output_path),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Record a web page and zoom in and out on it, as an MP4 ready to share."
    )
    parser.add_argument("url", help="the page to record")
    parser.add_argument("output", help="the MP4 to write")
    parser.add_argument("--seconds", type=float, default=10.0, help="how long, 10 when unsaid")
    parser.add_argument("--width", type=int, default=1280, help="1280 when unsaid")
    parser.add_argument("--height", type=int, default=800, help="800 when unsaid")
    parser.add_argument(
        "--zoom",
        default="auto",
        help="auto (the centre, 1.5x, over the middle half), none, or s1-s2-s3-s4-f-x-y "
        "zooms separated by |, their seconds counted from the page loaded",
    )
    parser.add_argument("--ease", default="smooth", choices=EASES, help="smooth when unsaid")
    parser.add_argument("--fps", type=int, default=30, help="frames per second, 30 when unsaid")
    parser.add_argument("--crf", type=int, default=20, help="constant quality, 20 when unsaid")
    parser.add_argument("--preset", default="medium", help="H.264 preset, medium when unsaid")
    parser.add_argument(
        "--wait-until",
        "--wait_until",
        dest="wait_until",
        default="networkidle",
        choices=WAIT_UNTIL,
        help="when the page counts as loaded, networkidle when unsaid",
    )
    parser.add_argument("--save", action="store_true", help="keep the MP4 in the Space")
    parser.add_argument("--space", default="", help="a Space's uid or handle (default Space)")
    parser.add_argument("--folder", default="", help="a folder in the Dataset (its root)")
    parser.add_argument("--name", default="", help="its name in the Space (the output's)")
    parser.add_argument(
        "--collection", default=SPACE_COLLECTION, help=f"the Dataset ({SPACE_COLLECTION})"
    )
    parser.add_argument(
        "--runtime-url", "--runtime_url", dest="runtime_url", default="", help="the agent runtime"
    )
    options = parser.parse_args()
    try:
        made = record_and_zoom(
            options.url,
            options.output,
            options.seconds,
            options.width,
            options.height,
            options.zoom,
            options.ease,
            options.fps,
            options.crf,
            options.preset,
            options.wait_until,
        )
    except (ValueError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f"Error: the page could not be recorded: {error}", file=sys.stderr)
        sys.exit(1)
    if options.save:
        try:
            made["saved"] = save_to_space(
                options.output,
                options.name,
                options.folder,
                options.space,
                options.collection,
                options.runtime_url,
            )
        except SpaceRefused as refused:
            print(json.dumps(made, indent=2))
            print(
                f"Error: {refused} The video is still at {options.output}.",
                file=sys.stderr,
            )
            sys.exit(1)
    print(json.dumps(made, indent=2))


if __name__ == "__main__":
    main()
