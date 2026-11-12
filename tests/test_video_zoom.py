# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""The video skill's zoom: the zooms read and refused, the filter and the ffmpeg arguments
built, and, where ffmpeg is installed, a zoom run on a small generated clip."""

from __future__ import annotations

import importlib.util
import math
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "datalayer_skills"
    / "skills"
    / "video"
    / "scripts"
    / "zoom_video.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("zoom_video", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


zoom_video = _load()


def _ffmpeg() -> str | None:
    try:
        return zoom_video.ffmpeg_binary()
    except RuntimeError:
        return None


def evaluate(expression: str, t: float) -> float:
    """An ffmpeg expression of t, computed as ffmpeg computes it."""
    names = {
        "t": t,
        "between": lambda value, low, high: 1.0 if low <= value <= high else 0.0,
        "max": max,
        "min": min,
    }
    # ffmpeg's if(c,a,b) is not Python's: a function of its own here.
    python = expression.replace("if(", "_if(")
    names["_if"] = lambda condition, then, otherwise: then if condition else otherwise
    return float(eval(python, {"__builtins__": {}}, names))


def test_a_zoom_is_seven_numbers_and_several_are_separated_by_a_bar() -> None:
    zooms = zoom_video.parse_zooms("2-3-6-7-1.8-0.5-0.5|10-11-14-15-2.2-0.8-0.25")
    assert zooms == [
        {"s1": 2, "s2": 3, "s3": 6, "s4": 7, "factor": 1.8, "x": 0.5, "y": 0.5},
        {"s1": 10, "s2": 11, "s3": 14, "s4": 15, "factor": 2.2, "x": 0.8, "y": 0.25},
    ]


@pytest.mark.parametrize(
    ("spec", "says"),
    [
        ("", "No zoom given"),
        ("1-2-3-2-0.5-0.5", "expected s1-s2-s3-s4-f-x-y"),
        ("1-2-3-4-two-0.5-0.5", "every value is a number"),
        ("2-2-3-4-2-0.5-0.5", "s1 < s2 <= s3 < s4"),
        ("1-2-3-3-2-0.5-0.5", "s1 < s2 <= s3 < s4"),
        ("3-2-4-5-2-0.5-0.5", "s1 < s2 <= s3 < s4"),
        ("1-2-3-4-0.5-0.5-0.5", "factor must be 1 or more"),
        ("1-2-3-4-2-1.5-0.5", "x and y go from 0 to 1"),
    ],
)
def test_a_zoom_that_cannot_be_read_is_refused(spec: str, says: str) -> None:
    with pytest.raises(ValueError, match=re.escape(says)):
        zoom_video.parse_zooms(spec)


def test_the_trim_is_a_start_and_an_end() -> None:
    assert zoom_video.parse_trim(None) is None
    assert zoom_video.parse_trim("1-13") == (1.0, 13.0)
    for bad in ("13-1", "1", "a-b", "1-2-3"):
        with pytest.raises(ValueError, match="Invalid trim"):
            zoom_video.parse_trim(bad)


def test_the_factor_rises_holds_and_falls_at_a_constant_speed() -> None:
    (zoom,) = zoom_video.parse_zooms("2-4-6-8-3-0.5-0.5")
    expression = zoom_video.zoom_expression(zoom)
    assert expression == (
        "if(between(t,2,4),1+(3-1)*(t-2)/(4-2),"
        "if(between(t,4,6),3,"
        "if(between(t,6,8),3-(3-1)*(t-6)/(8-6),1)))"
    )
    at = {t: evaluate(expression, t) for t in (0, 2, 2.5, 3, 4, 5, 6, 7, 7.5, 8, 9)}
    assert at == {0: 1, 2: 1, 2.5: 1.5, 3: 2, 4: 3, 5: 3, 6: 3, 7: 2, 7.5: 1.5, 8: 1, 9: 1}


def test_a_smooth_zoom_starts_and_ends_slowly_and_meets_the_same_ends() -> None:
    (zoom,) = zoom_video.parse_zooms("2-4-6-8-3-0.5-0.5")
    linear = zoom_video.zoom_expression(zoom, "linear")
    smooth = zoom_video.zoom_expression(zoom, "smooth")
    for t in (0, 2, 3, 4, 5, 6, 7, 8, 9):
        assert math.isclose(evaluate(smooth, t), evaluate(linear, t)), t
    # A quarter in, the smooth move has covered less; three quarters in, more.
    assert evaluate(smooth, 2.5) < evaluate(linear, 2.5)
    assert evaluate(smooth, 3.5) > evaluate(linear, 3.5)
    assert evaluate(smooth, 6.5) > evaluate(linear, 6.5)
    with pytest.raises(ValueError, match="Invalid ease"):
        zoom_video.zoom_expression(zoom, "bounce")


def test_the_filter_scales_each_frame_and_crops_it_back_around_the_point() -> None:
    zooms = zoom_video.parse_zooms("1-2-3-4-2-0.8-0.25")
    video_filter = zoom_video.build_filter(640, 360, zooms)
    scale, crop = video_filter.split(",crop=")
    assert scale.startswith("scale=w=640*if(between(t\\,1\\,2)\\,")
    assert scale.endswith(":eval=frame")
    assert crop.startswith("w=640:h=360:x=max(0\\,min((0.8*640*if(")
    # Every comma inside an expression is escaped: the only bare one joins scale to crop.
    assert len(re.findall(r"(?<!\\),", video_filter)) == 1
    # y counts from the bottom for the person, from the top for ffmpeg: 0.25 up is 0.75 down.
    assert ":y=max(0\\,min((0.75*360*if(" in crop


def test_the_crop_follows_the_point_and_never_leaves_the_frame() -> None:
    def crop_at(x: float, y: float, t: float) -> tuple[float, float]:
        zooms = zoom_video.parse_zooms(f"1-2-3-4-2-{x}-{y}")
        video_filter = zoom_video.build_filter(640, 360, zooms).replace("\\,", ",")
        found = re.search(r":x=(.*):y=(.*)$", video_filter)
        return evaluate(found.group(1), t), evaluate(found.group(2), t)

    # Fully zoomed (the frame is 1280x720): the crop is centred on the point.
    assert crop_at(0.5, 0.5, 2.5) == (320, 180)
    assert crop_at(0.75, 0.25, 2.5) == (640, 360)
    # A corner: the crop stops at the frame's edge.
    assert crop_at(1, 0, 2.5) == (640, 360)
    assert crop_at(0, 1, 2.5) == (0, 0)
    # Outside the zoom the frame is whole.
    assert crop_at(0.75, 0.25, 0) == (0, 0)
    assert crop_at(0.75, 0.25, 9) == (0, 0)


def test_several_zooms_follow_each_other_in_one_filter() -> None:
    zooms = zoom_video.parse_zooms("1-2-3-4-2-0.5-0.5|5-6-7-8-3-0.1-0.9")
    video_filter = zoom_video.build_filter(640, 360, zooms)
    assert video_filter.count("scale=w=") == 2
    assert video_filter.count("crop=w=640:h=360") == 2


def test_the_arguments_trim_before_the_input_and_encode_by_the_extension() -> None:
    plain = zoom_video.build_arguments("in.mp4", "out.mp4", "FILTER")
    assert plain == [
        "-i",
        "in.mp4",
        "-vf",
        "FILTER",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "copy",
        "out.mp4",
    ]
    trimmed = zoom_video.build_arguments("in.mp4", "out.mp4", "FILTER", (1.0, 13.0), 23, "slow")
    assert trimmed[:6] == ["-ss", "1", "-to", "13", "-i", "in.mp4"]
    assert trimmed[trimmed.index("-preset") + 1] == "slow"
    assert trimmed[trimmed.index("-crf") + 1] == "23"
    webm = zoom_video.build_arguments("in.mp4", "out.webm", "FILTER")
    assert webm[webm.index("-c:v") + 1] == "libvpx-vp9"
    assert webm[webm.index("-c:a") + 1] == "libopus"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        check=False,
        text=True,
        timeout=120,
    )


def test_the_script_refuses_a_zoom_it_cannot_read_before_any_ffmpeg(tmp_path: Path) -> None:
    done = run(str(tmp_path / "none.mp4"), str(tmp_path / "out.mp4"), "1-2-3")
    assert done.returncode == 1
    assert "expected s1-s2-s3-s4-f-x-y" in done.stdout


@pytest.mark.skipif(
    _ffmpeg() is None,
    reason="ffmpeg is not installed here (neither imageio-ffmpeg nor a system ffmpeg)",
)
def test_a_zoom_on_a_generated_clip_keeps_its_size_and_shows_the_point(tmp_path: Path) -> None:
    ffmpeg = _ffmpeg()
    clip = tmp_path / "clip.mp4"
    # Four seconds, 320x240: black, with a white square in the lower-right quarter.
    made = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=10:d=4",
            "-vf",
            "drawbox=x=220:y=160:w=40:h=40:color=white:t=fill",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=120,
    )
    if made.returncode != 0:
        pytest.skip(f"this ffmpeg cannot generate the clip: {made.stderr.strip()[-200:]}")
    assert zoom_video.video_size(str(clip)) == (320, 240)

    out = tmp_path / "zoomed.mp4"
    # The square's centre is 75 % across and 25 % up: zoom to 4x on it from 1 s to 2 s.
    done = run(str(clip), str(out), "1-2-3-3.5-4-0.75-0.25", "--ease", "smooth")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 zoom" in done.stdout
    assert zoom_video.video_size(str(out)) == (320, 240)

    def white(seconds: float) -> float:
        """The share of the frame at that time that is white."""
        frame = subprocess.run(
            [
                ffmpeg,
                "-ss",
                str(seconds),
                "-i",
                str(out),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                "-",
            ],
            capture_output=True,
            check=True,
            timeout=120,
        ).stdout
        assert len(frame) == 320 * 240
        return sum(1 for value in frame if value > 128) / len(frame)

    before, zoomed, after = white(0.5), white(2.5), white(3.8)
    # The 40x40 square is 2 % of the frame; at 4x it is 160x160, a third of it.
    assert 0.01 < before < 0.03
    assert 0.3 < zoomed < 0.37
    assert 0.01 < after < 0.03

    trimmed = tmp_path / "trimmed.mp4"
    done = run(str(clip), str(trimmed), "0.2-0.5-1-1.5-2-0.5-0.5", "--trim", "1-3")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "trimmed to 1-3 s" in done.stdout
