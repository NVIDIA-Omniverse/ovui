# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The installed USD Viewer streams and records red and blue in their places.

Issue 510: at stream start the red/blue swap kernel did not load (Windows:
``nvrtcCompileProgram rc=7``, the NVRTC builtins DLL was not found; Linux:
``cuModuleLoadData rc=222``, a CUDA toolkit newer than the driver). The app
logged "falling back to legacy R/B-swapped stream" and every client showed red
and blue exchanged, while ``stream_start`` reported success.

The scene has a red cube on the left and a blue cube on the right
(``tests/data/livestream_red_green_blue.usda``). The installed app (real ovrtx
renderer, OpenUSD provider) is controlled the way a user streams it, through
the ovui inspector media commands, and real clients decode the stream:

* windowed app, viewport source (the default zero-copy GPU-to-NVENC path),
  protocols ``webrtc``, ``native`` and ``rtsp``: the app log at
  ``stream_start`` has no R/B failure, the stream status has no error, and the
  decoded frame has the red cube left of the blue cube. The native client is
  ``ovstream.Client`` (NATIVE); the RTSP client is ffmpeg (from
  ``imageio-ffmpeg``); the WebRTC client is the ovstream browser client
  (``examples/webrtc_client`` of the ovstream repository, in
  ``OVSTREAM_WEBRTC_CLIENT_DIR``) in a browser that decodes H.264 (Google
  Chrome or Microsoft Edge). Where no such browser exists (Linux ARM64), the
  WebRTC decode is not possible; ``OVUI_E2E_REQUIRE_WEBRTC_DECODE=1`` makes a
  missing browser a failure.
* headless app: an MP4 recording of the composed window, then the
  application source (the composed window) with the native and the RTSP
  client: every decoded frame has red left of blue. This needs the
  CUDA-Vulkan frame export, which a partitioned (MIG) GPU cannot give; the
  test skips only for that reason.

Every protocol of a test must start: a ``stream_start`` that fails, fails the
test with its cause, after the other protocols are checked. The WebRTC and
native servers of StreamSDK need a Direct3D device on Windows, which a
Windows service session (session 0) cannot give
(``NVST_DISCONN_SERVER_VIDEO_ADAPTER_INITIALIZE_D3D_FAILED``). So on Windows
the test runs in a logged-on desktop session; CI starts it there with
``.github/scripts/run_in_console_session.py``.

The tests skip only on a computer without the hardware (an NVIDIA GPU that
ovrtx can use, and on Linux an X display). On a computer with the hardware,
a missing ``ovstream`` or ``imageio-ffmpeg`` fails the test with the install
command.

The windowed app renders its viewport at a fixed 1000x720 (the viewport
Resolution setting), so the stream has the same size on every platform.
Every decoded frame is kept in the test directory.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HERE = Path(__file__).resolve().parent
driver = _load_by_path("ovui_e2e_driver_livestream", _HERE / "driver.py")
field_delete = _load_by_path(
    "ovui_e2e_field_delete_helpers_livestream", _HERE / "test_wheel_app_field_delete_e2e.py"
)
pytestmark = pytest.mark.requires_ovrtx

SCENE = driver.repo_root() / "ovui-widgets" / "tests" / "data" / "livestream_red_green_blue.usda"
STREAM_SIZE = driver.APP_WINDOW_SIZE
# Fewer pixels than this of one color means the cube is not in the frame.
MIN_CUBE_PIXELS = 500
EXPORT_UNAVAILABLE = "no CUDA device corresponds to the Vulkan adapter"

_NATIVE_CLIENT = r"""
import json, sys, time
import numpy as np
from PIL import Image
import ovstream

port, out = int(sys.argv[1]), sys.argv[2]
result = {"frames": 0}
ovstream.initialize()
try:
    with ovstream.Client(ovstream.ClientType.NATIVE, server_ip="127.0.0.1",
                         signal_port=port) as client:
        deadline = time.monotonic() + 90
        last = None
        while time.monotonic() < deadline and result["frames"] < 60:
            frame = client.wait_frame(timeout_ms=1000)
            if frame is None:
                continue
            bgra = np.array(frame.as_numpy()[:, :frame.width, :])
            client.release_frame()
            result["frames"] += 1
            last = (frame, bgra)
        if last is not None:
            frame, bgra = last
            Image.fromarray(bgra[:, :, [2, 1, 0]], "RGB").save(out)
            result.update(width=frame.width, height=frame.height, format=frame.format)
finally:
    ovstream.shutdown()
print("CLIENT:" + json.dumps(result))
"""

_WEBRTC_CLIENT = r"""
import base64, functools, json, sys, threading, time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from playwright.sync_api import sync_playwright

client_dir, port, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=client_dir))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
result = {"browser": None, "decoded": False, "console": []}
with sync_playwright() as p:
    browser = None
    for channel in ("chrome", "msedge"):
        try:
            browser = p.chromium.launch(headless=True, channel=channel,
                                        args=["--autoplay-policy=no-user-gesture-required"])
            result["browser"] = channel
            break
        except Exception as exc:
            result.setdefault("launch_errors", []).append(f"{channel}: {exc}"[:300])
    if browser is not None:
        page = browser.new_page()
        page.on("console", lambda m: result["console"].append(m.text[:300]))
        page.goto(f"http://127.0.0.1:{httpd.server_address[1]}/index.html", wait_until="load")
        page.fill("#server-ip", "127.0.0.1")
        page.fill("#signal-port", str(port))
        page.click("#connect-button")
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            info = page.evaluate("() => { const v = document.getElementById('remote-video');"
                                 " return {w: v.videoWidth, t: v.currentTime, rs: v.readyState}; }")
            if info["w"] > 0 and info["rs"] >= 2 and info["t"] > 0:
                result["decoded"] = True
                break
            time.sleep(0.5)
        if result["decoded"]:
            page.wait_for_timeout(3000)
            url = page.evaluate("() => { const v = document.getElementById('remote-video');"
                                " const c = document.createElement('canvas');"
                                " c.width = v.videoWidth; c.height = v.videoHeight;"
                                " c.getContext('2d').drawImage(v, 0, 0);"
                                " return c.toDataURL('image/png'); }")
            open(out, "wb").write(base64.b64decode(url.split(",", 1)[1]))
        browser.close()
httpd.shutdown()
print("CLIENT:" + json.dumps(result))
"""


def _require_module(name: str, package: str) -> None:
    """Fail when a client package is missing.

    The hardware check runs first, so this computer can run the test: a missing
    package is an install fault, not a reason to skip.
    """
    if importlib.util.find_spec(name) is None:
        pytest.fail(
            f"{name} is not installed; this livestream test needs it to decode the "
            f"stream. Install it: python -m pip install {package}"
        )


def _call(session, name: str, arguments: dict | None = None) -> dict:
    """Send one inspector media command; return its result or raise with the cause."""
    res = session._cli(
        "call", name, "--arguments", json.dumps(arguments or {}), "--timeout", "120",
        timeout=150,
    )
    try:
        reply = json.loads(res.stdout)
    except json.JSONDecodeError:
        reply = {}
    if res.returncode != 0 or not reply.get("success"):
        raise RuntimeError(
            f"inspector {name} failed: {res.stdout}\n{res.stderr}\n"
            f"--- app log ---\n{session.log_tail()}"
        )
    return reply["result"]


def _log_text(session) -> str:
    try:
        return session.log_path.read_text(errors="replace")
    except OSError:
        return ""


def _run_client(script: str, *args: str) -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", script, *args], capture_output=True, text=True, timeout=180,
    )
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("CLIENT:")), None)
    if line is None:
        raise RuntimeError(f"stream client failed:\n{proc.stdout}\n{proc.stderr}")
    return json.loads(line[len("CLIENT:"):])


def _red_and_blue(image: Path, box: tuple | None = None) -> dict:
    """Pixel count and mean x position of the saturated red and blue areas."""
    import numpy as np
    from PIL import Image

    rgb = np.asarray(Image.open(image).convert("RGB")).astype(int)
    if box is not None:
        x0, y0, x1, y1 = box
        rgb = rgb[y0:y1, x0:x1]
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    masks = {
        "red": (r > 120) & (r > 2 * g) & (r > 2 * b),
        "blue": (b > 120) & (b > 2 * r) & (b > 2 * g),
    }
    xs = np.broadcast_to(np.arange(rgb.shape[1]), rgb.shape[:2])
    return {
        name: (int(mask.sum()), float(xs[mask].mean()) if mask.any() else None)
        for name, mask in masks.items()
    }


def _assert_red_left_of_blue(image: Path, where: str, box: tuple | None = None) -> None:
    found = _red_and_blue(image, box)
    print(f"[colors] {where}: {found}")
    (red_n, red_x), (blue_n, blue_x) = found["red"], found["blue"]
    assert red_n >= MIN_CUBE_PIXELS and blue_n >= MIN_CUBE_PIXELS, (
        f"{where}: the red or the blue cube is missing in {image.name}: {found}"
    )
    assert red_x < blue_x, (
        f"{where}: red and blue are exchanged in {image.name} (the red area is right "
        f"of the blue area; the scene has red on the left): {found}"
    )


def _start_stream(session, arguments: dict, where: str) -> tuple[dict | None, list]:
    """``stream_start``; return its status and the problems seen at the start.

    The status is None when the stream did not start; its cause is then one of
    the problems, because every protocol of the test is required. The problems
    are checked after the other protocols, so a failing run still keeps the
    decoded frames that show the colors.
    """
    before = len(_log_text(session))
    start_error = None
    try:
        status = _call(session, "stream_start", arguments)
    except RuntimeError as exc:
        status, start_error = None, str(exc)
    time.sleep(2.0)
    started = _log_text(session)[before:]
    rb_lines = [ln for ln in started.splitlines() if "R/B" in ln]
    problems = []
    if rb_lines:
        problems.append(f"the app log at stream_start reports an R/B failure: {rb_lines}")
    if status is None:
        print(f"[stream_start] {where}: the stream did not start; r/b lines={rb_lines}")
        problems.append(f"stream_start failed: {start_error}")
        return None, problems
    print(f"[stream_start] {where}: state={status.get('state')} error={status.get('error')} "
          f"extent={status.get('extent')} source={status.get('pixel_source')} r/b lines={rb_lines}")
    if status.get("state") not in ("LISTENING", "STREAMING") or status.get("error"):
        problems.append(f"stream_start returned {status}")
    if list(status.get("extent") or []) != list(STREAM_SIZE):
        problems.append(f"the stream is {status.get('extent')}, expected {list(STREAM_SIZE)}")
    return status, problems


def _colors_problem(image: Path, where: str, box: tuple | None = None) -> list:
    try:
        _assert_red_left_of_blue(image, where, box)
    except AssertionError as exc:
        return [str(exc)]
    return []


def _stream_arguments(protocol: str, **extra) -> tuple[dict, int, int]:
    signal_port, media_port = driver._free_port(), driver._free_port()
    arguments = {"protocol": protocol, "signal_port": signal_port, "media_port": media_port}
    arguments.update(extra)
    return arguments, signal_port, media_port


def _decode(protocol: str, signal_port: int, media_port: int, out: Path, where: str) -> bool:
    """Decode one stream frame to ``out`` with a real client; False when WebRTC cannot decode here."""
    if protocol == "native":
        result = _run_client(_NATIVE_CLIENT, str(signal_port), str(out))
        print(f"[client] {where}: {result}")
        assert result["frames"] > 0 and out.exists(), f"{where}: the native client decoded nothing"
        return True
    if protocol == "rtsp":
        import imageio_ffmpeg

        # ffmpeg reads the RTSP stream like a player and keeps its last decoded frame.
        proc = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
             "-rtsp_transport", "tcp", "-i", f"rtsp://127.0.0.1:{media_port}/stream",
             "-frames:v", "30", "-update", "1", "-y", str(out)],
            capture_output=True, text=True, timeout=120,
        )
        print(f"[client] {where}: ffmpeg exit {proc.returncode} {proc.stderr.strip()[:300]}")
        assert proc.returncode == 0 and out.exists(), f"{where}: ffmpeg decoded nothing"
        return True
    client_dir = os.environ.get("OVSTREAM_WEBRTC_CLIENT_DIR", "")
    required = os.environ.get("OVUI_E2E_REQUIRE_WEBRTC_DECODE", "").strip() == "1"
    reason = None
    if not client_dir or not (Path(client_dir) / "index.html").exists():
        reason = "OVSTREAM_WEBRTC_CLIENT_DIR does not name the ovstream webrtc_client folder"
    elif importlib.util.find_spec("playwright") is None:
        reason = "playwright is not installed"
    else:
        result = _run_client(_WEBRTC_CLIENT, client_dir, str(signal_port), str(out))
        print(f"[client] {where}: browser={result.get('browser')} decoded={result['decoded']} "
              f"launch_errors={result.get('launch_errors')}")
        if result["decoded"] and out.exists():
            return True
        if result.get("browser") is not None:
            raise AssertionError(f"{where}: the browser did not decode the stream: {result}")
        reason = f"no browser with H.264 decode: {result.get('launch_errors')}"
    if required:
        pytest.fail(f"{where}: WebRTC decode is required here, but {reason}")
    print(f"[client] {where}: WebRTC decode not possible on this host: {reason}")
    return False


def _stream_protocols(session, protocols: tuple, label: str, tmp_path: Path,
                      box: tuple | None = None, **extra) -> list:
    """Stream with each protocol and check its start and decoded colors; return the decoded ones.

    Every protocol must start. Every protocol runs before the check, so one failing
    protocol does not hide the others.
    """
    decoded = []
    all_problems = []
    for protocol in protocols:
        where = f"{label} {protocol}"
        arguments, signal_port, media_port = _stream_arguments(protocol, **extra)
        status, problems = _start_stream(session, arguments, where)
        if status is None:
            all_problems += [f"{where}: {problem}" for problem in problems]
            continue
        frame = tmp_path / f"decoded-{label}-{protocol}.png"
        if _decode(protocol, signal_port, media_port, frame, where):
            decoded.append(protocol)
            problems += _colors_problem(frame, where, box)
        status = _call(session, "stream_status")
        print(f"[stream_status] {where}: state={status.get('state')} "
              f"submitted={status.get('submitted_frames')} error={status.get('error')}")
        if status.get("error"):
            problems.append(f"stream_status {status}")
        if protocol in decoded and status.get("submitted_frames", 0) <= 0:
            problems.append(f"a client decoded, but stream_status counts no frame: {status}")
        _call(session, "stream_stop")
        all_problems += [f"{where}: {problem}" for problem in problems]
    print(f"[decoded] {label}: {decoded}")
    assert not all_problems, "; ".join(all_problems)
    return decoded


@pytest.mark.parametrize("provider", ["openusd"])
def test_windowed_viewport_stream_decodes_red_and_blue_in_place(provider, tmp_path):
    field_delete._require_renderer_and_display()
    _require_module("ovstream", "ovstream")
    _require_module("imageio_ffmpeg", "imageio-ffmpeg")
    driver.assert_installed_provenance(driver.PRODUCT_MODULES)

    # The viewport renders at a fixed size, so the stream is 1000x720 whatever the panel size.
    (tmp_path / "settings.json").write_text(
        json.dumps({driver.HEADLESS_RESOLUTION_SETTING: list(STREAM_SIZE)})
    )
    session = driver.FullAppSession(
        workdir=tmp_path, log_path=tmp_path / "app.log", provider=provider,
        headless=False, scene=SCENE,
    )
    session.start()
    try:
        session.wait_ready(timeout=180)
        state = session.state()
        assert state.get("provider") == provider
        window = tmp_path / "window.png"
        session.screenshot(window)
        _assert_red_left_of_blue(
            window, "the app window", driver.viewport_box(state["viewport"]["image_rect"])
        )
        decoded = _stream_protocols(session, ("webrtc", "native", "rtsp"), "windowed", tmp_path)
        assert decoded, "windowed: no protocol could stream on this computer"
        # Streaming must leave the viewport on the zero-copy GPU ingest path.
        driver.assert_zero_copy_tier(session, "enabled", "after streaming")
    finally:
        session.stop()


@pytest.mark.parametrize("provider", ["openusd"])
def test_headless_application_stream_and_recording_keep_red_and_blue(provider, tmp_path):
    field_delete._require_renderer_and_display()
    _require_module("ovstream", "ovstream")
    _require_module("imageio_ffmpeg", "imageio-ffmpeg")
    driver.assert_installed_provenance(driver.PRODUCT_MODULES)

    session = driver.FullAppSession(
        workdir=tmp_path, log_path=tmp_path / "app.log", provider=provider,
        headless=True, scene=SCENE,
    )
    session.start()
    try:
        session.wait_ready(timeout=180)
        box = driver.viewport_box(session.state()["viewport"]["image_rect"])
        frame0 = tmp_path / "app-frame.png"
        session.screenshot(frame0)
        _assert_red_left_of_blue(frame0, "the headless app frame", box)

        # The recording first: it needs no stream encoder, only the frame export.
        try:
            _call(session, "recording_start", {"fps": 15, "max_seconds": 8})
        except RuntimeError as exc:
            if EXPORT_UNAVAILABLE in _log_text(session):
                pytest.skip(f"This GPU cannot export frames to CUDA (partitioned GPU): {exc}"[:400])
            raise
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if _call(session, "recording_status").get("captured_frames", 0) >= 15:
                break
            time.sleep(1.0)
        receipt = _call(session, "recording_stop")
        print(f"[recording] { {k: v for k, v in receipt.items() if k != 'artifacts'} }")
        assert receipt.get("ok"), f"recording failed: {receipt}"
        video = next(Path(a["path"]) for a in receipt["artifacts"] if a["kind"] == "video")

        import imageio_ffmpeg
        import numpy as np
        from PIL import Image

        reader = imageio_ffmpeg.read_frames(str(video))
        meta = next(reader)
        width, height = meta["size"]
        last = None
        for raw in reader:
            last = raw
        assert last is not None, f"{video.name} has no frame"
        recorded = tmp_path / "recording-last-frame.png"
        Image.fromarray(np.frombuffer(last, np.uint8).reshape(height, width, 3), "RGB").save(recorded)
        _assert_red_left_of_blue(recorded, "MP4 recording", box)

        decoded = _stream_protocols(session, ("native", "rtsp"), "application", tmp_path,
                                    box, source="application")
        assert decoded, "application: no protocol could stream on this computer"
    finally:
        session.stop()
