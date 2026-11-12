# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

import argparse
import re
import shutil
import subprocess
import sys

# Zooms in on a point of a video and back out, once or several times.
#
# A zoom is `s1-s2-s3-s4-f-x-y`: the zoom-in starts at s1 seconds and is complete at s2, the
# picture stays zoomed until s3, and the zoom-out is complete at s4; f is the zoom factor
# (2 doubles the picture), and (x, y) the point zoomed on, each from 0 to 1, from the
# bottom-left corner (x: 0 left, 1 right; y: 0 bottom, 1 top). Several zooms are separated by
# "|". Each frame is scaled by the zoom's factor at its time, then cropped back to the video's
# size around the point, the crop held inside the scaled frame.

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


def build_arguments(input_path, output_path, video_filter, trim=None, crf=18, preset="medium"):
    """ffmpeg's arguments: the trim before the input (the zooms' times then count from the
    trim's start), the filter, H.264 with the audio copied (VP9 and Opus for a .webm)."""
    arguments = []
    if trim:
        arguments += ["-ss", number(trim[0]), "-to", number(trim[1])]
    arguments += ["-i", input_path, "-vf", video_filter]
    if output_path.lower().endswith(".webm"):
        arguments += ["-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0", "-c:a", "libopus"]
    else:
        arguments += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-c:a", "copy"]
    arguments.append(output_path)
    return arguments


def video_size(path):
    """The width and height of the video's first video stream, read off ffmpeg."""
    completed = subprocess.run(
        [ffmpeg_binary(), "-i", path], capture_output=True, check=False, text=True
    )
    for line in completed.stderr.splitlines():
        if "Stream #" in line and "Video:" in line:
            size = re.search(r"[ ,](\d{2,5})x(\d{2,5})[ ,\[]", line + " ")
            if size:
                return int(size.group(1)), int(size.group(2))
    raise RuntimeError(f"No video stream found in {path}")


def run(arguments):
    command = [ffmpeg_binary(), "-y", *arguments]
    completed = subprocess.run(command, capture_output=True, check=False, text=True)
    if completed.returncode != 0:
        print(
            completed.stderr.strip().splitlines()[-1]
            if completed.stderr.strip()
            else "ffmpeg failed"
        )
        sys.exit(completed.returncode)
    return completed


def zoom(input_path, output_path, zooms, trim=None, ease="linear", crf=18, preset="medium"):
    parsed = parse_zooms(zooms)
    cut = parse_trim(trim)
    width, height = video_size(input_path)
    run(
        build_arguments(
            input_path, output_path, build_filter(width, height, parsed, ease), cut, crf, preset
        )
    )
    trimmed = f", trimmed to {number(cut[0])}-{number(cut[1])} s" if cut else ""
    print(
        f"Saved {output_path} ({len(parsed)} zoom{'s' if len(parsed) > 1 else ''} on "
        f"{input_path}, {width}x{height}, {ease}{trimmed})"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Zoom in on a point of a video and back out, once or several times."
    )
    parser.add_argument("input", help="the input video")
    parser.add_argument("output", help="the output video (.mp4 H.264, .webm VP9)")
    parser.add_argument(
        "zooms",
        help="s1-s2-s3-s4-f-x-y, several separated by |: zoom-in from s1 to s2 seconds, held "
        "until s3, zoom-out done at s4; f the factor; x, y the point, 0 to 1 from bottom-left",
    )
    parser.add_argument("--trim", default=None, help="START-END in seconds, cut first")
    parser.add_argument("--ease", default="linear", choices=EASES, help="how the zoom moves")
    parser.add_argument("--crf", type=int, default=18, help="constant quality, 18 when unsaid")
    parser.add_argument("--preset", default="medium", help="H.264 preset, medium when unsaid")
    options = parser.parse_args()
    try:
        zoom(
            options.input,
            options.output,
            options.zooms,
            options.trim,
            options.ease,
            options.crf,
            options.preset,
        )
    except (ValueError, RuntimeError) as error:
        print(error)
        sys.exit(1)
