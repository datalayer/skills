# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""The video skill's record-then-zoom flow and its keeping in the person's Space.

`record_and_zoom`: the zooms it gives (auto, none, given), the ffmpeg arguments of
a shareable MP4, an encode of a generated clip, and, where Playwright's Chromium
is installed, a real page recorded. `save_to_space`: the file sent to a fake
agent runtime's ``POST /api/v1/spaces/files``, as the sandbox sends it.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "datalayer_skills" / "skills" / "video" / "scripts"
RECORD = SCRIPTS / "record_and_zoom.py"
SAVE = SCRIPTS / "save_to_space.py"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


record_and_zoom = _load(RECORD)


def _ffmpeg() -> str | None:
    try:
        return record_and_zoom.ffmpeg_binary()
    except RuntimeError:
        return None


def _chromium() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as playwright:
            playwright.chromium.launch().close()
    except Exception:  # noqa: BLE001 - any failure to launch is no Chromium here
        return False
    return True


def _block(path: Path, start: str, end: str) -> str:
    text = path.read_text()
    return text[text.index(start) : text.index(end)]


def test_the_zoom_is_the_same_block_as_zoom_videos() -> None:
    start, end = "# ---- The zoom (", "# ---- End of the zoom ----"
    assert _block(RECORD, start, end) == _block(SCRIPTS / "zoom_video.py", start, end)


def test_the_space_is_the_same_block_as_save_to_spaces() -> None:
    start, end = "# ---- The Space (", "# ---- End of the Space ----"
    assert _block(RECORD, start, end) == _block(SAVE, start, end)


def test_with_no_zoom_given_one_zooms_on_the_centre_over_the_middle_half() -> None:
    assert record_and_zoom.auto_zoom(10) == "2.5-3.5-6.5-7.5-1.5-0.5-0.5"
    (zoom,) = record_and_zoom.zooms_for("auto", 10)
    assert zoom == {"s1": 2.5, "s2": 3.5, "s3": 6.5, "s4": 7.5, "factor": 1.5, "x": 0.5, "y": 0.5}
    for none in ("none", "", "off"):
        assert record_and_zoom.zooms_for(none, 10) == []


def test_given_zooms_are_read_and_one_past_the_recording_is_refused() -> None:
    zooms = record_and_zoom.zooms_for("1-2-3-4-2-0.8-0.25|5-6-7-8-3-0.5-0.5", 8)
    assert [z["factor"] for z in zooms] == [2, 3]
    with pytest.raises(ValueError, match="after the recording's 6 s"):
        record_and_zoom.zooms_for("1-2-3-7-2-0.5-0.5", 6)
    with pytest.raises(ValueError, match="expected s1-s2-s3-s4-f-x-y"):
        record_and_zoom.zooms_for("1-2-3", 6)


def test_the_sides_are_even_for_yuv420p() -> None:
    assert [record_and_zoom.even(v) for v in (1280, 1281, 801, 1)] == [1280, 1280, 800, 2]


def test_the_mp4_is_h264_yuv420p_with_its_index_first_from_the_page_loaded() -> None:
    zooms = record_and_zoom.zooms_for("1-2-3-4-2-0.5-0.5", 5)
    arguments = record_and_zoom.encode_arguments(
        "in.webm", "out.mp4", 0.84, 5, 640, 360, zooms, "smooth", 30, 20, "medium"
    )
    assert arguments[:6] == ["-ss", "0.84", "-i", "in.webm", "-t", "5"]
    video_filter = arguments[arguments.index("-vf") + 1]
    # The frame rate first: the zooms are computed on every frame of the output.
    assert video_filter.startswith("fps=30,scale=w=640*")
    assert "crop=w=640:h=360" in video_filter
    assert arguments[arguments.index("-c:v") + 1] == "libx264"
    assert arguments[arguments.index("-pix_fmt") + 1] == "yuv420p"
    assert arguments[arguments.index("-movflags") + 1] == "+faststart"
    assert "-an" in arguments
    assert arguments[-1] == "out.mp4"
    plain = record_and_zoom.encode_arguments(
        "in.webm", "out.mp4", 0, 5, 640, 360, [], "smooth", 25, 20, "fast"
    )
    assert plain[plain.index("-vf") + 1] == "fps=25"


def run(script: Path, *args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )


def test_the_script_refuses_an_output_that_is_not_an_mp4_before_recording(tmp_path: Path) -> None:
    done = run(RECORD, "https://example.com", str(tmp_path / "out.webm"))
    assert done.returncode == 1
    assert "The output is an .mp4" in done.stderr


@pytest.mark.skipif(
    _ffmpeg() is None,
    reason="ffmpeg is not installed here (neither imageio-ffmpeg nor a system ffmpeg)",
)
def test_a_generated_recording_is_cut_zoomed_and_encoded_to_share(tmp_path: Path) -> None:
    ffmpeg = _ffmpeg()
    clip = tmp_path / "recording.mp4"
    # Five seconds, 320x240: black, with a white square in the lower-right quarter.
    made = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x240:r=25:d=5",
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
    out = tmp_path / "shared.mp4"
    zooms = record_and_zoom.zooms_for("1-2-3-3.5-4-0.75-0.25", 4)
    # The first second is the page loading: cut.
    record_and_zoom.encode(str(clip), str(out), 1, 4, 320, 240, zooms, "smooth", 30, 20, "veryfast")
    probe = subprocess.run(
        [ffmpeg, "-i", str(out)], capture_output=True, check=False, text=True
    ).stderr
    assert "h264" in probe
    assert "yuv420p" in probe
    assert "320x240" in probe
    assert "30 fps" in probe
    assert "Duration: 00:00:04.0" in probe
    data = out.read_bytes()
    # +faststart: the index before the frames.
    assert data.index(b"moov") < data.index(b"mdat")

    def white(seconds: float) -> float:
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
        return sum(1 for value in frame if value > 128) / len(frame)

    assert 0.01 < white(0.5) < 0.03
    assert 0.3 < white(2.5) < 0.37
    assert 0.01 < white(3.9) < 0.03


@pytest.mark.skipif(
    _ffmpeg() is None or not _chromium(),
    reason="Playwright's Chromium or ffmpeg is not installed here",
)
def test_a_real_page_is_recorded_zoomed_encoded_and_kept_in_the_space(
    runtime: FakeRuntime, tmp_path: Path
) -> None:
    page = tmp_path / "page.html"
    page.write_text(
        '<html><body style="margin:0;background:#000">'
        '<div style="position:absolute;left:75%;top:75%;width:40px;height:40px;'
        'margin:-20px;background:#fff"></div></body></html>'
    )
    out = tmp_path / "page.mp4"
    done = run(
        RECORD,
        page.as_uri(),
        str(out),
        "--seconds",
        "3",
        "--width",
        "321",
        "--height",
        "240",
        "--preset",
        "veryfast",
        "--save",
        "--folder",
        "pages",
    )
    assert done.returncode == 0, done.stderr
    made = json.loads(done.stdout)
    assert made["width"] == 320
    assert made["zooms"] == ["0.75-1.05-1.95-2.25-1.5-0.5-0.5"]
    assert made["bytes"] == out.stat().st_size > 0
    assert made["saved"]["path"] == "pages/page.mp4"
    (request,) = runtime.requests
    assert request["body"] == out.read_bytes()
    assert request["query"]["media_type"] == "video/mp4"


# ---- save_to_space, against a fake runtime ----


class FakeRuntime:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.refusal: tuple[int, str] | None = None


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch):
    fake = FakeRuntime()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            parsed = urlparse(self.path)
            query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
            fake.requests.append(
                {
                    "path": parsed.path,
                    "query": query,
                    "body": body,
                    "content_type": self.headers.get("Content-Type"),
                    "authorization": self.headers.get("Authorization"),
                }
            )
            if fake.refusal:
                status, answer = fake.refusal[0], {"detail": fake.refusal[1]}
            else:
                status, answer = (
                    200,
                    {
                        "space": {"uid": "S1", "handle": "library", "name": "Library"},
                        "dataset": {"uid": "D1", "name": query.get("collection")},
                        "path": "/".join(p for p in (query.get("folder"), query["name"]) if p),
                        "bytes": len(body),
                        "url": "https://datalayer.app/contents/D1",
                    },
                )
            data = json.dumps(answer).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("AGENT_RUNTIMES_URL", f"http://127.0.0.1:{server.server_address[1]}")
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()


def test_save_sends_the_file_to_the_runtime_without_any_token(
    runtime: FakeRuntime, tmp_path: Path
) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"\x00\x01video")
    done = run(SAVE, str(video), "--folder", "launches", timeout=60)
    assert done.returncode == 0, done.stderr
    saved = json.loads(done.stdout)
    assert saved["url"] == "https://datalayer.app/contents/D1"
    assert saved["path"] == "launches/demo.mp4"
    (request,) = runtime.requests
    assert request["path"] == "/api/v1/spaces/files"
    assert request["query"] == {
        "name": "demo.mp4",
        "folder": "launches",
        "collection": "Videos",
        "media_type": "video/mp4",
    }
    assert request["body"] == b"\x00\x01video"
    assert request["content_type"] == "video/mp4"
    assert request["authorization"] is None


def test_save_names_the_space_the_name_and_the_dataset_when_asked(
    runtime: FakeRuntime, tmp_path: Path
) -> None:
    gif = tmp_path / "clip.gif"
    gif.write_bytes(b"GIF89a")
    done = run(
        SAVE,
        str(gif),
        "--name",
        "teaser.gif",
        "--space",
        "research",
        "--collection",
        "Teasers",
        timeout=60,
    )
    assert done.returncode == 0, done.stderr
    (request,) = runtime.requests
    assert request["query"]["space"] == "research"
    assert request["query"]["name"] == "teaser.gif"
    assert request["query"]["collection"] == "Teasers"
    assert request["query"]["media_type"] == "image/gif"


def test_a_refusal_is_said_and_the_file_stays(runtime: FakeRuntime, tmp_path: Path) -> None:
    runtime.refusal = (409, "You have no default Space to keep it in: name one.")
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    done = run(SAVE, str(video), timeout=60)
    assert done.returncode == 1
    assert "You have no default Space to keep it in" in done.stderr
    assert f"The file is still at {video}" in done.stderr
    assert video.read_bytes() == b"video"


def test_a_runtime_out_of_reach_is_said(tmp_path: Path) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    done = run(SAVE, str(video), "--runtime-url", "http://127.0.0.1:9", timeout=60)
    assert done.returncode == 1
    assert "cannot be reached" in done.stderr
    assert video.exists()


def test_a_missing_or_empty_file_is_refused_before_any_call(tmp_path: Path) -> None:
    done = run(SAVE, str(tmp_path / "none.mp4"), "--runtime-url", "http://127.0.0.1:9")
    assert done.returncode == 1
    assert "There is no file at" in done.stderr
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    done = run(SAVE, str(empty), "--runtime-url", "http://127.0.0.1:9")
    assert done.returncode == 1
    assert "is empty" in done.stderr


def _broken_runtime(behaviour: str):
    """A runtime that reads the request, then drops the line or stalls before its answer is whole."""
    import socket

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    stop = threading.Event()

    def serve() -> None:
        connection, _ = server.accept()
        connection.settimeout(5)
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                data += connection.recv(65536)
            if behaviour == "stall":
                # A status and headers promising a body that never comes.
                connection.sendall(
                    b"HTTP/1.1 201 Created\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{"
                )
                stop.wait(10)
            elif behaviour == "not-json":
                body = b"<html>a proxy page</html>"
                connection.sendall(
                    b"HTTP/1.1 201 Created\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body)
                )
            # "drop": closes with no answer at all.
        finally:
            connection.close()
            server.close()

    threading.Thread(target=serve, daemon=True).start()
    return f"http://127.0.0.1:{server.getsockname()[1]}", stop


@pytest.mark.parametrize(
    "behaviour, said",
    [("drop", "did not answer"), ("stall", "did not answer"), ("not-json", "not JSON")],
)
@pytest.mark.parametrize("script", [SAVE, RECORD], ids=["save_to_space", "record_and_zoom"])
def test_a_runtime_that_drops_stalls_or_garbles_its_answer_is_a_refusal(
    tmp_path: Path, behaviour: str, said: str, script: Path
) -> None:
    module = _load(script)
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"video")
    url, stop = _broken_runtime(behaviour)
    try:
        with pytest.raises(module.SpaceRefused, match=said):
            module.save_to_space(str(video), runtime=url, timeout=1)
    finally:
        stop.set()
    assert video.read_bytes() == b"video"
