# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared driver for the wheel-install end-to-end golden tests.

This module launches the *installed* USD Viewer application, headless
(``python -m ovui_widgets.app.headless``) or as the regular windowed app
(``python -m ovui_widgets.app``), always at exactly 1000x720, with the ovui
inspector skill attached. It opens a checked-in scene and drives it through
the documented ``ovui-inspect`` CLI (screenshot / click / move / state) the way
a user would. It is deliberately independent of the application source tree:
it only needs the installed ``ovui_widgets`` package (as a user would have it
from the wheels) plus the inspector skill scripts, which live in this
repository checkout.

* Windowed (:mod:`test_wheel_app_window_golden_e2e`, openusd and ovstage): close
  the Content browser with the mouse, click the cube, and capture the whole
  1000x720 window.
* Headless (:mod:`test_wheel_app_golden_e2e`): click the cube and capture what
  the headless app outputs, the viewport's rendered frame (the frame its
  viewport stream sends), rendered at 1000x720 — no editor UI.

Every capture is 1000x720. It is compared with one golden shared by all
platforms, stored at half size (500x360); see ``check_*`` below.
``OMNI_UI_GENERATE_GOLDEN=1`` writes the golden instead.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# --- Fixed capture geometry -----------------------------------------------
#
# Every app (headless or windowed) is started at exactly this size, on every
# platform, and every compared screenshot is the whole frame at this size —
# never cropped or scaled. 1000 px wide also fits the Windows runner's
# 1024x768 screen with the window frame.
APP_WINDOW_SIZE = (1000, 720)

# The prim we select, and how the inspector /state reports the result.
SELECTED_PRIM = "/World/Cube"


def repo_root() -> Path:
    """Return the ovui repository root (the checkout that holds this file)."""
    # .../ovui-widgets/tests/e2e/driver.py -> repo root is 4 parents up.
    return Path(__file__).resolve().parents[3]


def scene_path() -> Path:
    return repo_root() / "ovui-widgets" / "tests" / "data" / "simple_scene.usda"


def inspector_cli() -> Path:
    return (
        repo_root()
        / "skills"
        / "omniverse-ui-inspector"
        / "scripts"
        / "ovui-inspect"
    )


def inspector_pythonpath() -> str:
    return str(repo_root() / "skills" / "omniverse-ui-inspector")


def platform_key() -> str:
    """Stable per-platform golden key, e.g. ``linux_x86_64``/``windows_amd64``."""
    import platform

    return f"{platform.system().lower()}_{platform.machine().lower()}"


def golden_dir() -> Path:
    """One golden folder for every platform (see GOLDEN_SCALE)."""
    return Path(__file__).resolve().parent / "golden"


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def nvidia_gpu_present() -> tuple[bool, str]:
    """Return whether an NVIDIA GPU is visible, via ``nvidia-smi -L``.

    This is independent of ovrtx so the test can tell apart two cases:
      * no GPU at all  -> an honest environment limit (skip is allowed), and
      * a GPU is present but the renderer fails to initialize -> a real break
        (the imgui.dll-collision class of bug), which must FAIL, not skip.
    """
    try:
        proc = subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=30
        )
    except FileNotFoundError:
        return False, "nvidia-smi not found"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"nvidia-smi could not run: {exc!r}"
    out = (proc.stdout or "").strip()
    if proc.returncode == 0 and "GPU 0" in out:
        return True, out.splitlines()[0]
    return False, f"nvidia-smi listed no GPU (rc={proc.returncode}): {out or proc.stderr.strip()}"


def _probe_text(text: str | None, limit: int = 8000) -> str:
    """Return the end of a probe stream, bounded so a failure message stays readable."""
    text = (text or "").strip()
    if not text:
        return "(empty)"
    return text if len(text) <= limit else "...(truncated)...\n" + text[-limit:]


def ovrtx_device_available() -> tuple[bool, str]:
    """Probe for a working ovrtx renderer *without* importing omni.ui.

    Constructs an ``ovrtx.Renderer`` in a clean subprocess. This is the ovrtx
    renderer the bug report says works *in isolation*; it fails on software
    Vulkan (no ray-tracing device) and on a broken/missing renderer install.

    Returns ``(available, detail)``. The caller combines this with
    :func:`nvidia_gpu_present` to decide skip-vs-fail.
    """
    probe = (
        "import ovrtx\n"
        "r = ovrtx.Renderer()\n"
        "print('OVRTX_DEVICE_OK')\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return False, "ovrtx renderer probe timed out"
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"ovrtx renderer probe could not start: {exc!r}"
    if "OVRTX_DEVICE_OK" in proc.stdout:
        return True, "ovrtx renderer constructed"
    # Report everything the probe printed. The last stderr line alone can be the
    # tail of a longer native error (ovrtx appends ``config: RendererConfig()``
    # after the native message), which hides the real cause.
    return False, (
        f"ovrtx renderer unavailable: probe exit status {proc.returncode}\n"
        f"--- probe stdout ---\n{_probe_text(proc.stdout)}\n"
        f"--- probe stderr ---\n{_probe_text(proc.stderr)}"
    )


# Product import packages that MUST come from the installed wheels, never the
# source checkout. (The inspector skill is tooling, not product, so it is
# allowed on PYTHONPATH and excluded here.)
PRODUCT_MODULES = (
    "omni.ui",
    "omni.ui_scene",
    "ovui_widgets.app.application",
    "ovui_data_adapters.common",
    "ovui_data_adapters.openusd",
)


def assert_installed_provenance(modules: tuple = PRODUCT_MODULES) -> dict:
    """Prove the product packages resolve to installed wheels, not the checkout.

    Runs a subprocess with the *same* environment the app is launched with, so
    it reflects the app's real import resolution. Raises ``RuntimeError`` with
    the offending path if any product module imports from the repo checkout.
    Returns a ``{module: path}`` map on success.
    """
    # Installed wheel code always lives in a site-packages directory; the source
    # checkout never does (its packages sit at <repo>/ovui-widgets/ovui_widgets,
    # <repo>/ovui/python/omni, etc.). Checking for site-packages is correct even
    # when the venv itself is created inside the checkout (as in CI), where a
    # naive "under the repo root" test would wrongly flag installed packages.
    probe = (
        "import json, importlib, os\n"
        f"mods = {list(modules)!r}\n"
        "out = {}\n"
        "for name in mods:\n"
        "    m = importlib.import_module(name)\n"
        "    f = getattr(m, '__file__', None)\n"
        "    if f is None:\n"
        "        raise SystemExit('NOFILE:' + name)\n"
        "    out[name] = f\n"
        "bad = {n: p for n, p in out.items() if 'site-packages' not in os.path.realpath(p).replace(os.sep, '/')}\n"
        "print('PROVENANCE:' + json.dumps({'paths': out, 'bad': bad}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=300,
        env=app_env(),
    )
    marker = "PROVENANCE:"
    line = next(
        (ln for ln in proc.stdout.splitlines() if ln.startswith(marker)), None
    )
    if line is None:
        raise RuntimeError(
            "provenance probe failed to import installed product modules:\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    data = json.loads(line[len(marker):])
    if data["bad"]:
        raise RuntimeError(
            "product modules imported from the source checkout instead of the "
            f"installed wheels: {data['bad']}"
        )
    return data["paths"]


# The ovstage install has no OpenUSD at all, so it proves the ovstage adapter
# instead of the OpenUSD one.
OVSTAGE_PRODUCT_MODULES = tuple(
    m for m in PRODUCT_MODULES if m != "ovui_data_adapters.openusd"
) + ("ovui_data_adapters.ovstage",)


def app_env() -> dict:
    """Build the environment the app (and provenance probe) run under.

    Crucially, PYTHONPATH is reset to *only* the inspector skill, so the
    checkout package roots that the widgets ``conftest`` mirrors onto
    PYTHONPATH cannot leak into the child and shadow the installed wheels.
    """
    env = dict(os.environ)
    env["OMNIUI_HEADLESS"] = "1"
    env["OMNIUI_BACKEND"] = "vulkan"
    # Real renderer is mandatory: if ovrtx fails to load (the bug), the app
    # exits non-zero and the test fails instead of silently falling back.
    env["OVUI_WIDGETS_REQUIRE_OVRTX"] = "1"
    env["OVUIINSPECT_ENABLE_STATE"] = "1"
    env["OVUIINSPECT_HOST"] = "127.0.0.1"
    env["PYTHONUNBUFFERED"] = "1"
    # Only installed wheel code for the product; only the inspector skill is
    # added to PYTHONPATH.
    env["PYTHONPATH"] = inspector_pythonpath()
    env["PYTHONNOUSERSITE"] = "1"
    env["OVUI_TEST_INSTALLED_RELEASE"] = "1"
    return env


def selection_overlay_pixels(image_path: Path) -> int:
    """Count strongly-coloured pixels — the selection gizmo arrows and outline.

    A selected prim draws saturated red/green/blue translate handles and a blue
    outline; an unselected or blank viewport has none. This catches a renderer
    that reports a selection but omits the visual highlight, which the greyscale
    scene makes invisible to a loose whole-image mean-error tolerance.
    """
    from PIL import Image

    img = Image.open(image_path).convert("RGB")
    px = img.load()
    w, h = img.size
    count = 0
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            mx = max(r, g, b)
            mn = min(r, g, b)
            if mx - mn > 60 and mx > 90:
                count += 1
    return count


class AppSession:
    """A running USD Viewer driven through the inspector CLI (see FullAppSession)."""

    def __init__(self, workdir: Path, log_path: Path, capture_frames: bool = True):
        self.workdir = workdir
        self.log_path = log_path
        # True: the frame-loop warm-up and the click pumps take screenshots
        # (``_warmup.png``, ``_pump.png``). False: they ask for the app state
        # instead, so the session takes no screenshot of its own. A test that
        # has no reference image sets False.
        self.capture_frames = capture_frames
        self.port = _free_port()
        self.proc: Optional[subprocess.Popen] = None
        self._log_fh = None

    # -- lifecycle --------------------------------------------------------
    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            with contextlib.suppress(Exception):
                self._cli("shutdown", timeout=10)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    self.proc.wait(timeout=10)
                if self.proc.poll() is None:
                    self.proc.kill()
        if self._log_fh:
            self._log_fh.close()

    def log_tail(self, n: int = 40) -> str:
        try:
            return "\n".join(self.log_path.read_text().splitlines()[-n:])
        except OSError:
            return "<no log>"

    # -- inspector CLI ----------------------------------------------------
    def _cli(self, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["OVUIINSPECT_HOST"] = "127.0.0.1"
        env["OVUIINSPECT_PORT"] = str(self.port)
        return subprocess.run(
            [sys.executable, str(inspector_cli()) + ".py", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

    def _assert_alive(self) -> None:
        if self.proc is not None and self.proc.poll() is not None:
            raise RuntimeError(
                "app process exited early with code "
                f"{self.proc.returncode}\n--- app log ---\n{self.log_tail()}"
            )

    # The ovui frame loop can take a while to begin pumping after the inspector
    # reports healthy — the first real ovrtx frames compile shaders, and on a
    # shared/MIG GPU that is slow. The inspector then answers an action with
    # "timed out before the ovui frame loop started it". That is transient:
    # retry the action until the loop is actually servicing commands. When the
    # loop reaches the command just after its deadline, the inspector answers
    # "timed out before it started" instead. Both end with "it was not run".
    _TRANSIENT = "it was not run"
    _WARMUP_TRANSIENT = (_TRANSIENT, "timed out after it started")

    def _cli_retry(
        self, *args: str, attempts: int = 50, settle: float = 5.0, timeout: float = 30.0
    ) -> subprocess.CompletedProcess:
        last = None
        for _ in range(attempts):
            self._assert_alive()
            res = self._cli(*args, timeout=timeout)
            if res.returncode == 0:
                return res
            last = res
            if self._TRANSIENT in (res.stdout or "") + (res.stderr or ""):
                time.sleep(settle)
                continue
            break
        return last

    def _frame_command(self, out: Path, timeout: str, cli_timeout: float):
        """A command that the frame loop must service: a screenshot, or the
        app state when this session takes no screenshots."""
        if self.capture_frames:
            return self._cli("screenshot", "--out", str(out), "--timeout", timeout,
                             timeout=cli_timeout)
        return self._cli("state", "--timeout", timeout, timeout=cli_timeout)

    def wait_ready(self, timeout: float = 120.0) -> None:
        """Wait for the inspector server, then for the frame loop to service a
        real command. The gate is a warm-up *screenshot* retried over a long
        window — not status polling — because the first ovrtx frames compile
        shaders, and on a slow/large GPU that can take minutes, during which the
        inspector answers "before the ovui frame loop started it". A successful
        screenshot proves the loop is live and the pipeline is hot, so the
        following click is reliable.
        """
        self._assert_alive()
        res = self._cli("wait", "--timeout", str(int(timeout)), timeout=timeout + 10)
        if res.returncode != 0:
            self._assert_alive()
            raise RuntimeError(
                f"inspector did not become healthy: {res.stdout}\n{res.stderr}\n"
                f"--- app log ---\n{self.log_tail()}"
            )
        warm = self.workdir / "_warmup.png"
        # ~6 min budget for the first frame. Besides "not started yet", the
        # first screenshot can also outlast its own timeout while the first
        # frames compile ("timed out after it started"; seen when several GPU
        # jobs start at once): give it 60 s and retry that answer too.
        res = None
        for _ in range(30):
            self._assert_alive()
            res = self._frame_command(warm, "60", 90)
            if res.returncode == 0:
                return
            if not any(t in (res.stdout or "") + (res.stderr or "") for t in self._WARMUP_TRANSIENT):
                break
            time.sleep(6.0)
        raise RuntimeError(
            "frame loop did not start servicing commands within the warm-up "
            f"window.\n{getattr(res, 'stdout', '')}\n{getattr(res, 'stderr', '')}\n"
            f"--- app log ---\n{self.log_tail()}"
        )

    def status(self) -> dict:
        res = self._cli("status", timeout=20)
        try:
            return json.loads(res.stdout)
        except json.JSONDecodeError:
            return {}

    def state(self) -> dict:
        res = self._cli_retry("state")
        try:
            return json.loads(res.stdout).get("state", {})
        except (json.JSONDecodeError, AttributeError):
            return {}

    def click(self, x: int, y: int, double: bool = False) -> None:
        # A click is a frame-paced "steps" command (press+move+release). On a GPU
        # whose headless loop only ticks in bursts, the steps can time out while
        # the loop is idle. Drive a frame with a screenshot immediately before
        # each click attempt so the loop is awake when the steps are queued.
        last = None
        pump = self.workdir / "_pump.png"
        for _ in range(40):
            self._assert_alive()
            if self.capture_frames:
                self._cli("screenshot", "--out", str(pump), timeout=30)
            else:
                self._cli("state", timeout=30)
            res = self._cli(
                "click", str(x), str(y), *(("--double",) if double else ()), timeout=30
            )
            if res.returncode == 0:
                return
            last = res
            if self._TRANSIENT not in (res.stdout or "") + (res.stderr or ""):
                break
            time.sleep(2.0)
        raise RuntimeError(
            f"click failed: {getattr(last, 'stdout', '')}\n"
            f"{getattr(last, 'stderr', '')}\n--- app log ---\n{self.log_tail()}"
        )

    def move(self, x: int, y: int) -> None:
        self._cli_retry("move", str(x), str(y))

    def press(self, key: str, modifiers: str = "") -> None:
        """One key press (down, one frame, up), as a user presses a key."""
        args = ("press", key, *(("--modifiers", modifiers) if modifiers else ()))
        res = self._cli_retry(*args, "--timeout", "30", timeout=60)
        if res is None or res.returncode != 0:
            raise RuntimeError(
                f"press {key} failed: {getattr(res, 'stdout', '')}\n"
                f"{getattr(res, 'stderr', '')}\n--- app log ---\n{self.log_tail()}"
            )

    def type_text(self, text: str) -> None:
        res = self._cli_retry("type", text, "--timeout", "30", timeout=60)
        if res is None or res.returncode != 0:
            raise RuntimeError(
                f"type {text!r} failed: {getattr(res, 'stdout', '')}\n"
                f"{getattr(res, 'stderr', '')}\n--- app log ---\n{self.log_tail()}"
            )

    def screenshot(self, out: Path) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        res = self._cli_retry("screenshot", "--out", str(out))
        if res is None or res.returncode != 0 or not out.exists():
            raise RuntimeError(
                f"screenshot failed: {getattr(res, 'stdout', '')}\n"
                f"{getattr(res, 'stderr', '')}\n--- app log ---\n{self.log_tail()}"
            )


def renderer_selection_paths(state: dict) -> list:
    """Extract the renderer's highlighted selection paths from /state."""
    renderer = state.get("renderer", {})
    paths = renderer.get("selected_paths")
    if paths is None:
        outline = renderer.get("selection_outline", {})
        paths = outline.get("applied_paths", [])
    return list(paths or [])


def selection_sources(state: dict) -> list:
    return list(state.get("selection", {}).get("sources", []) or [])


# --- The user flow shared by the headless and the windowed test -------------
#
# The windowed test launches the *regular* USD Viewer exactly as a user does
# (``python -m ovui_widgets.app``: a real GLFW window, the full app chrome); on
# Linux CI the window lives on an Xvfb display and the NVIDIA Vulkan driver
# still renders it on the GPU. The headless test runs the same flow on the
# offscreen app. Both screenshot the whole 1000x720 frame.

WINDOW_PROVIDERS = ("openusd", "ovstage")

# The Window menu draws its entries as 22 px rows starting 15 px below the menu
# bar item. Which row "Content Browser" sits on is NOT hard-coded: the app grows
# Window-menu entries over time, and when one lands above Content Browser a
# stale row number quietly clicks a different command instead of failing.
# The row comes from the live menu, reported by the inspector's read-only
# ``menus.top_levels[].items``; the visibility probe afterwards proves the click
# hit it, since every other window must stay visible.
WINDOW_MENU_ROW_HEIGHT = 22
WINDOW_MENU_FIRST_ROW_OFFSET = 15

# The viewport HUD's FPS value (e.g. "451/512") is the only live text left in
# the window once the Content browser is closed. Its 72x18 cell, relative to
# the viewport image's top-left corner, is painted black before comparing.
FPS_VALUE_BOX = (46, 43, 118, 61)

# Read-only probe of the windows the user can toggle from the Window menu.
WINDOW_VISIBILITY_PROBE = (
    "result = {name: bool(getattr(getattr(application, attr, None), 'visible', False))"
    " for name, attr in ("
    "('Stage Browser', '_stage_window'), ('Property Inspector', '_property_window'),"
    " ('Viewport', '_viewport_window'), ('Content', '_content_window'),"
    " ('Layers', '_layer_window'))}"
)


def menu_row(menu: dict, label: str) -> int:
    """Row index of ``label`` in a top-level menu from the inspector state.

    Fails loudly — with the menu as the app actually built it — rather than
    letting a stale row number click whatever entry moved into its place.
    """
    items = list(menu.get("items") or ())
    assert items, (
        f"the inspector reported no entries for the {menu.get('label')!r} menu; "
        "cannot locate a row to click"
    )
    assert label in items, (
        f"{label!r} is not in the {menu.get('label')!r} menu: {items}"
    )
    return items.index(label)


def window_golden_name(provider: str) -> str:
    return f"app_window_{provider}.png"


HEADLESS_GOLDEN_NAME = "headless_viewport_openusd.png"

# The viewport's fixed render resolution (Viewport settings > Resolution).
HEADLESS_RESOLUTION_SETTING = "viewport.instances.main.resolution"


def mask_fps(src: Path, dst: Path, viewport_rect: dict) -> None:
    """Paint the live FPS value black so the window image is reproducible."""
    from PIL import Image, ImageDraw

    left, top, right, bottom = FPS_VALUE_BOX
    vx, vy = int(viewport_rect["x"]), int(viewport_rect["y"])
    img = Image.open(src).convert("RGB")
    ImageDraw.Draw(img).rectangle(
        (vx + left, vy + top, vx + right - 1, vy + bottom - 1), fill=(0, 0, 0)
    )
    img.save(dst)


def viewport_box(rect: dict) -> tuple:
    """(left, top, right, bottom) of the viewport image, exclusive right/bottom."""
    x, y = int(rect["x"]), int(rect["y"])
    return (x, y, x + int(rect["width"]), y + int(rect["height"]))


def viewport_mask(size: tuple, rect: dict):
    """An L-mode mask of ``size``: 255 inside the viewport image, 0 elsewhere."""
    from PIL import Image, ImageDraw

    mask = Image.new("L", size, 0)
    left, top, right, bottom = viewport_box(rect)
    ImageDraw.Draw(mask).rectangle((left, top, right - 1, bottom - 1), fill=255)
    return mask


class FullAppSession(AppSession):
    """The USD Viewer at 1000x720, headless or windowed, via the inspector CLI.

    The provider (``openusd`` or ``ovstage``) is selected the documented way,
    with ``OVUI_DATA_ADAPTER_PROVIDER``. The size is set through the app's own
    ``OVGEAR_HEADLESS_WIDTH``/``OVGEAR_HEADLESS_HEIGHT`` (read by ``ui.init``
    for both the windowed and the headless app; the headless app also gets
    ``--width``/``--height``). Settings and the saved layout go to files inside
    the test's own directory, so every run starts from the default layout
    (Content browser open) no matter what an earlier run or the machine's user
    profile saved. The headless app's settings file also sets the viewport's
    render resolution to a fixed APP_WINDOW_SIZE (the viewport's Resolution
    setting), so its rendered output is 1000x720 whatever the panel size.
    """

    def __init__(self, workdir: Path, log_path: Path, provider: str, headless: bool,
                 scene: Optional[Path] = None, capture_frames: bool = True):
        super().__init__(workdir, log_path, capture_frames)
        self.provider = provider
        self.headless = headless
        self.scene = scene or scene_path()

    def start(self) -> None:
        env = app_env()
        width, height = APP_WINDOW_SIZE
        env["OVGEAR_HEADLESS_WIDTH"] = str(width)
        env["OVGEAR_HEADLESS_HEIGHT"] = str(height)
        if self.headless:
            # This flow reads the presented frame back in Python through
            # ViewportWidget.get_presentation_image(). On the default tier-2
            # zero-copy path the renderer hands ovui a CUDA device pointer and
            # never materialises a CPU image, so that call returns None *by
            # design* — see ovui_data_adapters.common._gpu_frame. Pin this one
            # session to the tier-1 CPU ingest path so the viewport's own
            # output is readable; the pixels the renderer produces are the
            # same either way, and the six windowed golden jobs keep covering
            # the default zero-copy path (they screenshot through ovui).
            env["OVGEAR_ZERO_COPY"] = "0"
            module = ["ovui_widgets.app.headless", "--width", str(width), "--height", str(height)]
        else:
            # A real window: drop the headless switches app_env() sets.
            env.pop("OMNIUI_HEADLESS", None)
            env.pop("OMNIUI_BACKEND", None)
            module = ["ovui_widgets.app"]
        env["OVUI_DATA_ADAPTER_PROVIDER"] = self.provider
        env["OVUIINSPECT_PORT"] = str(self.port)
        # Only for the read-only window-visibility probe.
        env["OVUIINSPECT_ENABLE_EXECUTE"] = "1"
        settings = self.workdir / "settings.json"
        env["OVUI_WIDGETS_SETTINGS_PATH"] = str(settings)
        if self.headless:
            settings.write_text(json.dumps({HEADLESS_RESOLUTION_SETTING: [width, height]}))
        if sys.platform.startswith("linux"):
            env.setdefault("XDG_RUNTIME_DIR", str(self.workdir / "xdg"))
            Path(env["XDG_RUNTIME_DIR"]).mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                os.chmod(env["XDG_RUNTIME_DIR"], 0o700)

        self._log_fh = open(self.log_path, "w")
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                *module,
                f"--/layout/save_path={(self.workdir / 'layout.json').as_posix()}",
                str(self.scene),
            ],
            cwd=str(self.workdir),
            env=env,
            stdout=self._log_fh,
            stderr=subprocess.STDOUT,
        )

    # Later screenshots and state snapshots can also outlast the
    # inspector's default 5 s (seen on the Windows and ARM64 runners), so
    # they allow 60 s.
    _SCREENSHOT_TIMEOUT = "60"

    def screenshot(self, out: Path) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        res = self._cli_retry(
            "screenshot", "--out", str(out), "--timeout", self._SCREENSHOT_TIMEOUT,
            timeout=90,
        )
        if res is None or res.returncode != 0 or not out.exists():
            raise RuntimeError(
                f"screenshot failed: {getattr(res, 'stdout', '')}\n"
                f"{getattr(res, 'stderr', '')}\n--- app log ---\n{self.log_tail()}"
            )

    def state(self) -> dict:
        """Slow first frames (seen on the ARM64 runner) get a 60 s snapshot
        timeout and retries; an unavailable state raises."""
        last = ""
        for _ in range(10):
            self._assert_alive()
            res = self._cli("state", "--timeout", self._SCREENSHOT_TIMEOUT, timeout=90)
            try:
                snapshot = json.loads(res.stdout).get("state")
            except (json.JSONDecodeError, AttributeError):
                snapshot = None
            if res.returncode == 0 and isinstance(snapshot, dict) and snapshot:
                return snapshot
            last = f"{res.stdout}\n{res.stderr}"
            time.sleep(3.0)
        raise RuntimeError(
            f"inspector state unavailable: {last}\n--- app log ---\n{self.log_tail()}"
        )

    def execute(self, code: str) -> object:
        res = self._cli_retry(
            "execute", code, "--timeout", self._SCREENSHOT_TIMEOUT, timeout=90
        )
        try:
            data = json.loads(res.stdout)
        except (json.JSONDecodeError, AttributeError):
            data = {}
        if not data.get("success"):
            raise RuntimeError(
                f"inspector execute failed: {getattr(res, 'stdout', '')}\n"
                f"{getattr(res, 'stderr', '')}"
            )
        return data.get("result")

    def window_visibility(self) -> dict:
        return dict(self.execute(WINDOW_VISIBILITY_PROBE) or {})

    def wait_stable(self, out: Path, viewport_rect: dict, frames: int = 3,
                    timeout: float = 120.0) -> int:
        """Screenshot until ``frames`` consecutive FPS-masked captures are
        bit-identical; leave the last one at ``out``. Returns the number of
        captures taken. Raises if the window never settles.
        """
        from PIL import Image, ImageChops

        deadline = time.monotonic() + timeout
        previous = None
        same = 0
        taken = 0
        raw = self.workdir / "_stable_raw.png"
        while time.monotonic() < deadline:
            self.screenshot(raw)
            taken += 1
            mask_fps(raw, out, viewport_rect)
            current = Image.open(out).convert("RGB")
            if previous is not None and ImageChops.difference(previous, current).getbbox() is None:
                same += 1
                if same >= frames - 1:
                    return taken
            else:
                same = 0
            previous = current
            time.sleep(1.0)
        raise RuntimeError(
            f"window did not settle: no {frames} identical consecutive frames "
            f"within {timeout:.0f}s ({taken} captures)"
        )


def assert_zero_copy_tier(session: "FullAppSession", expected: str, where: str) -> None:
    """The app must still be on the zero-copy tier the session asked for.

    ``ZeroCopyState`` retires tier-2 permanently on the first GPU map that
    raises, and the viewport keeps rendering from a CPU readback instead —
    correct pixels, so every golden still matches and nothing else in this
    suite notices. That is how an ovrtx 0.5 mapping change silently took all
    three ovstage jobs off the GPU ingest path. The windowed sessions must
    therefore end on ``enabled``, and the headless session — deliberately
    pinned to tier-1 with ``OVGEAR_ZERO_COPY=0`` — on ``disabled``;
    ``fallback`` is always a failure.
    """
    zero = dict(session.state().get("renderer", {}).get("zero_copy", {}) or {})
    mode = str(zero.get("mode", ""))
    assert mode == expected, (
        f"{where}: the viewport ingests frames on the {mode!r} zero-copy tier, "
        f"expected {expected!r}. Reported state: {zero}."
        + (
            f"\nIt started on the GPU path and retired it: "
            f"{zero.get('fallback_reason')!r}."
            if mode == "fallback" else ""
        )
        + f"\n--- app log ---\n{session.log_tail()}"
    )
    assert bool(zero.get("enabled")) is (expected == "enabled"), (
        f"{where}: zero_copy.mode is {mode!r} but enabled={zero.get('enabled')!r}"
    )
    print(f"[zero-copy] {where}: mode={mode}")


def _assert_cube_selected(session: AppSession, where: str) -> None:
    state = session.state()
    highlight = renderer_selection_paths(state)
    sources = selection_sources(state)
    assert highlight == [SELECTED_PRIM], (
        f"{where}: renderer highlight is {highlight}, expected [{SELECTED_PRIM}]. "
        f"Sources: {sources}.\n--- app log ---\n{session.log_tail()}"
    )
    assert "viewport" in sources, f"{where}: selection not from the viewport: {sources}"


def _start_and_check(session: FullAppSession, first: Path) -> dict:
    """Wait for the app, check provider and frame size; return /state."""
    from PIL import Image

    session.wait_ready(timeout=180)
    state = session.state()
    assert state.get("provider") == session.provider, (
        f"app runs provider {state.get('provider')!r}, expected {session.provider!r}"
    )
    session.wait_stable(first, state["viewport"]["image_rect"])
    size = Image.open(first).size
    print(f"[window] {size[0]}x{size[1]}")
    assert size == APP_WINDOW_SIZE, (
        f"the app frame is {size[0]}x{size[1]}, expected exactly "
        f"{APP_WINDOW_SIZE[0]}x{APP_WINDOW_SIZE[1]}"
    )
    return state


def _click_cube(session: FullAppSession) -> None:
    cube_xy = session.state()["viewport"]["prim_screen_centers"][SELECTED_PRIM]
    session.click(*cube_xy)
    _assert_cube_selected(session, f"after the viewport click at {cube_xy}")


def close_content_browser(session: FullAppSession, state: dict, menu_shot: Path,
                          closed_shot: Path) -> dict:
    """Close the Content browser with two mouse clicks; return the new viewport rect.

    Click the *Window* menu, then *Content Browser*. Prove only Content was
    hidden and the viewport grew into the freed space, then keep the stable
    frame at ``closed_shot``.
    """
    viewport_before = state["viewport"]["image_rect"]
    menu = next(m for m in state["menus"]["top_levels"] if m["label"] == "Window")
    row = menu_row(menu, "Content Browser")
    session.click(*menu["point"])
    session.screenshot(menu_shot)
    rect = menu["rect"]
    item_xy = (
        int(rect["x"]) + 60,
        int(rect["y"] + rect["height"]) + WINDOW_MENU_FIRST_ROW_OFFSET
        + row * WINDOW_MENU_ROW_HEIGHT,
    )
    print(f"[menu] Window entries {menu['items']}; 'Content Browser' is row {row}")
    session.click(*item_xy)

    shown = session.window_visibility()
    assert shown.get("Content") is False, (
        f"Content browser still shown after the mouse clicks: {shown}"
    )
    others = {k: v for k, v in shown.items() if k != "Content"}
    assert all(others.values()), f"the click closed the wrong window(s): {shown}"
    viewport = session.state()["viewport"]["image_rect"]
    assert viewport["height"] > viewport_before["height"], (
        "viewport did not grow into the space the Content browser left: "
        f"{viewport_before} -> {viewport}"
    )
    session.wait_stable(closed_shot, viewport)
    return viewport


def run_user_flow(session: FullAppSession, workdir: Path) -> tuple:
    """Drive the windowed app the way a user does and capture the window.

    1. Check the frame is exactly APP_WINDOW_SIZE and every window, the
       Content browser included, is shown (fresh settings + layout).
    2. Close the Content browser with two mouse clicks — the *Window* menu,
       then *Content Browser* — and prove only Content was hidden and the
       viewport grew into the freed space.
    3. Click the cube in the resized viewport; assert the renderer highlight
       and that the selection came from the viewport.
    4. Park the cursor and wait for a stable frame (live FPS value masked).
    5. The stable render right after the resize (step 2) must already match
       the final render apart from the selection overlay: the viewport must
       not keep a stale image until the user interacts.

    Returns ``(frame_path, viewport_rect)``.
    """
    from PIL import Image

    with_content = workdir / "1_with_content.png"
    menu_open = workdir / "2_window_menu_open.png"
    content_closed = workdir / "3_content_closed.png"
    frame = workdir / "full_window.png"

    state = _start_and_check(session, with_content)
    shown = session.window_visibility()
    assert all(shown.values()) and len(shown) == 5, (
        f"expected every window shown at start, got {shown}"
    )

    viewport = close_content_browser(session, state, menu_open, content_closed)

    _click_cube(session)

    # Park the cursor in the empty bottom-right corner.
    session.move(APP_WINDOW_SIZE[0] - 4, APP_WINDOW_SIZE[1] - 4)
    captures = session.wait_stable(frame, viewport)
    print(f"[stable] settled after {captures} captures; viewport {viewport}")
    assert session.window_visibility().get("Content") is False
    assert Image.open(frame).size == APP_WINDOW_SIZE
    stale = render_mean_difference(content_closed, frame, viewport)
    print(f"[resize] render after the resize vs final render: MEAN_ERROR={stale:.3f} "
          f"(max {POST_RESIZE_MEAN_LIMIT})")
    assert stale <= POST_RESIZE_MEAN_LIMIT, (
        f"the viewport render right after the resize differs from the final render "
        f"(MEAN_ERROR={stale:.3f} > {POST_RESIZE_MEAN_LIMIT}): it kept a stale image "
        f"until the click. See {content_closed} and {frame}."
    )
    assert_zero_copy_tier(session, "enabled", "after the windowed flow")
    return frame, viewport


# --- Camera pan flow ---------------------------------------------------------

EMPTY_SCENE = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Y"
)

def Xform "World"
{
}
"""

# Create menu entries the user clicks to add a cube: Create > Shape > Cube.
CREATED_PRIM = "/World/Cube"
CREATE_SHAPE_ENTRY = "Shape"
# The Shape submenu opens to the right of the Create menu, its rows 22 px
# apart. The Cube row is the third one (Capsule, Cone, Cube).
CREATE_SUBMENU_X_OFFSET = 130
CREATE_CUBE_ROW_IN_SUBMENU = 2

# The middle-mouse drag that pans the camera: right and down, in screenshot
# pixels, with an exact number of move steps so every run drags the same way.
PAN_DRAG_PIXELS = (80, 40)
PAN_DRAG_STEPS = 20
# A pan moves the cube on screen by the drag distance. Allow for rounding of the
# camera gesture and the width of the gizmo line.
PAN_MOVE_TOLERANCE = 12
# The pan must change the viewport render: the cube moves by tens of pixels.
MIN_PAN_RENDER_CHANGE = 1.0


def create_cube_from_menu(session: FullAppSession) -> None:
    """Create a cube with the mouse: Create > Shape > Cube. Assert it exists."""
    menu = next(m for m in session.state()["menus"]["top_levels"] if m["label"] == "Create")
    shape_row = menu_row(menu, CREATE_SHAPE_ENTRY)
    rect = menu["rect"]
    first_row_y = (
        int(rect["y"] + rect["height"]) + WINDOW_MENU_FIRST_ROW_OFFSET
    )
    session.click(*menu["point"])
    shape_y = first_row_y + shape_row * WINDOW_MENU_ROW_HEIGHT
    session.move(int(rect["x"]) + 40, shape_y)
    # Cube is the third row of the Shape submenu; the submenu starts level
    # with the Shape row.
    cube_xy = (
        int(rect["x"]) + CREATE_SUBMENU_X_OFFSET,
        shape_y + CREATE_CUBE_ROW_IN_SUBMENU * WINDOW_MENU_ROW_HEIGHT,
    )
    session.click(*cube_xy)
    state = session.state()
    selected = state["selection"]["paths"]
    assert selected == [CREATED_PRIM], (
        f"after Create > Shape > Cube the selection is {selected}, expected "
        f"[{CREATED_PRIM!r}]"
    )


def pan_camera(session: FullAppSession, viewport: dict) -> tuple:
    """Pan with the middle mouse button; return the drag start and end points."""
    start = (int(viewport["x"] + viewport["width"] / 2), int(viewport["y"] + viewport["height"] / 2))
    end = (start[0] + PAN_DRAG_PIXELS[0], start[1] + PAN_DRAG_PIXELS[1])
    last = None
    for _ in range(20):
        session._assert_alive()
        res = session._cli(
            "drag", str(start[0]), str(start[1]), str(end[0]), str(end[1]),
            "--button", "middle", "--steps", str(PAN_DRAG_STEPS), timeout=60,
        )
        if res.returncode == 0:
            return start, end
        last = res
        if session._TRANSIENT not in (res.stdout or "") + (res.stderr or ""):
            break
        time.sleep(2.0)
    raise RuntimeError(
        f"middle-button drag failed: {getattr(last, 'stdout', '')}\n"
        f"{getattr(last, 'stderr', '')}\n--- app log ---\n{session.log_tail()}"
    )


def gizmo_origin(frame: Path, viewport: dict) -> tuple:
    """Screen position of the move gizmo's origin, where the selected cube is.

    The gizmo is drawn at the cube's centre, so it moves with the cube when the
    camera pans. Read from the pixels, so it works for every data provider.
    """
    gizmo = gizmo_arrows(frame, viewport)
    assert gizmo["drawn"], f"the move gizmo of the new cube is not drawn: {gizmo} ({frame})"
    return gizmo["y"]["bbox"][0], gizmo["y"]["bbox"][3]


def run_camera_pan_flow(session: FullAppSession, workdir: Path) -> tuple:
    """Create a cube, pan the camera, and capture the window.

    1. Start the app on an empty stage; check the frame is APP_WINDOW_SIZE.
    2. Close the Content browser with the mouse (as the window flow does).
    3. Create a cube with the mouse (Create > Shape > Cube); it is selected.
    4. Park the cursor and wait for a stable frame (``before_pan.png``).
    5. Pan the camera: drag with the middle mouse button inside the viewport.
    6. Park the cursor and wait for a stable frame (the capture). Assert the
       cube (its move gizmo) moved on screen by the drag distance and the
       render changed.

    Returns ``(frame_path, viewport_rect)``.
    """
    from PIL import Image

    start_shot = workdir / "1_start.png"
    menu_shot = workdir / "2_window_menu_open.png"
    closed_shot = workdir / "3_content_closed.png"
    before = workdir / "4_before_pan.png"
    frame = workdir / "5_after_pan.png"

    state = _start_and_check(session, start_shot)
    assert not state["selection"]["paths"], (
        f"the stage must start with nothing selected, got {state['selection']['paths']}"
    )
    viewport = close_content_browser(session, state, menu_shot, closed_shot)

    create_cube_from_menu(session)
    park = (APP_WINDOW_SIZE[0] - 4, APP_WINDOW_SIZE[1] - 4)
    session.move(*park)
    session.wait_stable(before, viewport)
    origin_before = gizmo_origin(before, viewport)

    start, end = pan_camera(session, viewport)
    session.move(*park)
    captures = session.wait_stable(frame, viewport)
    origin_after = gizmo_origin(frame, viewport)
    moved = (origin_after[0] - origin_before[0], origin_after[1] - origin_before[1])
    expected = PAN_DRAG_PIXELS
    print(f"[pan] drag {start} -> {end}; gizmo origin {origin_before} -> {origin_after} "
          f"(moved {moved}, drag {expected}); settled after {captures} captures")
    assert abs(moved[0] - expected[0]) <= PAN_MOVE_TOLERANCE and (
        abs(moved[1] - expected[1]) <= PAN_MOVE_TOLERANCE
    ), (
        f"the cube moved {moved} on screen, expected about {expected} for a "
        f"middle-button pan of {expected}. See {before} and {frame}."
    )
    changed = render_mean_difference(before, frame, viewport)
    print(f"[pan] render before vs after the pan: MEAN_ERROR={changed:.3f} "
          f"(min {MIN_PAN_RENDER_CHANGE})")
    assert changed >= MIN_PAN_RENDER_CHANGE, (
        f"the viewport render did not change after the pan (MEAN_ERROR={changed:.3f}). "
        f"See {before} and {frame}."
    )
    assert session.window_visibility().get("Content") is False
    assert Image.open(frame).size == APP_WINDOW_SIZE
    assert_zero_copy_tier(session, "enabled", "after the camera pan flow")
    return frame, viewport


def camera_pan_golden_name(provider: str) -> str:
    return f"camera_pan_{provider}.png"


# --- Camera zoom flow --------------------------------------------------------

# One scroll-wheel gesture over the viewport centre. Each notch scales the
# distance to the surface under the cursor by 1.2 (wheel down) or 1 / 1.2
# (wheel up). Wheel down by 2 moves the camera to 1.44 times its distance. The
# test zooms out because the ovstage provider frames the new cube so close that
# it fills the viewport, and zoom in would clip it on every side.
ZOOM_SCROLL_DIRECTION = "down"
ZOOM_SCROLL_AMOUNT = 2
# After the zoom the lit cube area must be at most this share of the area before.
# The ideal ratio is about 0.55; a missed zoom gives 1.0.
MAX_ZOOM_AREA_RATIO = 0.85
MIN_ZOOM_RENDER_CHANGE = 1.0


def zoom_camera(session: FullAppSession, viewport: dict) -> tuple:
    """Zoom out with the mouse wheel over the viewport centre; return that point."""
    point = (int(viewport["x"] + viewport["width"] / 2), int(viewport["y"] + viewport["height"] / 2))
    last = None
    for _ in range(20):
        session._assert_alive()
        res = session._cli(
            "scroll", ZOOM_SCROLL_DIRECTION, "--amount", str(ZOOM_SCROLL_AMOUNT),
            "--x", str(point[0]), "--y", str(point[1]), timeout=60,
        )
        if res.returncode == 0:
            return point
        last = res
        if session._TRANSIENT not in (res.stdout or "") + (res.stderr or ""):
            break
        time.sleep(2.0)
    raise RuntimeError(
        f"mouse wheel scroll failed: {getattr(last, 'stdout', '')}\n"
        f"{getattr(last, 'stderr', '')}\n--- app log ---\n{session.log_tail()}"
    )


def cube_area(frame: Path, viewport: dict) -> int:
    """Count the light grey cube pixels inside the viewport, below its HUD band.

    The background is dark blue and the outline and gizmo are saturated, so
    light, nearly grey pixels come from the cube faces.
    """
    import numpy as np
    from PIL import Image

    left, top, right, bottom = viewport_box(viewport)
    top += VIEWPORT_CHROME_HEIGHT
    a = np.asarray(Image.open(frame).convert("RGB"), dtype=np.int16)[top:bottom, left:right]
    spread = a.max(axis=2) - a.min(axis=2)
    area = int(((a.min(axis=2) >= 150) & (spread <= 25)).sum())
    assert area >= 1000, f"no cube faces are visible in {frame} (area {area})"
    return area


def run_camera_zoom_flow(session: FullAppSession, workdir: Path) -> tuple:
    """Create a cube, zoom the camera out, and capture the window.

    Same start as the pan flow: empty stage, Content browser closed with the
    mouse, cube made with Create > Shape > Cube. Then scroll the mouse wheel down
    over the viewport, wait for a stable frame (the capture), and assert the
    cube area shrank and the render changed.

    Returns ``(frame_path, viewport_rect)``.
    """
    from PIL import Image

    start_shot = workdir / "1_start.png"
    menu_shot = workdir / "2_window_menu_open.png"
    closed_shot = workdir / "3_content_closed.png"
    before = workdir / "4_before_zoom.png"
    frame = workdir / "5_after_zoom.png"

    state = _start_and_check(session, start_shot)
    assert not state["selection"]["paths"], (
        f"the stage must start with nothing selected, got {state['selection']['paths']}"
    )
    viewport = close_content_browser(session, state, menu_shot, closed_shot)

    create_cube_from_menu(session)
    park = (APP_WINDOW_SIZE[0] - 4, APP_WINDOW_SIZE[1] - 4)
    session.move(*park)
    session.wait_stable(before, viewport)
    area_before = cube_area(before, viewport)

    point = zoom_camera(session, viewport)
    session.move(*park)
    captures = session.wait_stable(frame, viewport)
    area_after = cube_area(frame, viewport)
    ratio = area_after / area_before
    print(f"[zoom] wheel {ZOOM_SCROLL_DIRECTION} {ZOOM_SCROLL_AMOUNT} at {point}; cube area "
          f"{area_before} -> {area_after} px (ratio {ratio:.2f}, max {MAX_ZOOM_AREA_RATIO}); "
          f"settled after {captures} captures")
    assert ratio <= MAX_ZOOM_AREA_RATIO, (
        f"the cube area changed by {ratio:.2f}x after the zoom out, expected at most "
        f"{MAX_ZOOM_AREA_RATIO}x. See {before} and {frame}."
    )
    changed = render_mean_difference(before, frame, viewport)
    print(f"[zoom] render before vs after the zoom: MEAN_ERROR={changed:.3f} "
          f"(min {MIN_ZOOM_RENDER_CHANGE})")
    assert changed >= MIN_ZOOM_RENDER_CHANGE, (
        f"the viewport render did not change after the zoom (MEAN_ERROR={changed:.3f}). "
        f"See {before} and {frame}."
    )
    assert session.window_visibility().get("Content") is False
    assert Image.open(frame).size == APP_WINDOW_SIZE
    assert_zero_copy_tier(session, "enabled", "after the camera zoom flow")
    return frame, viewport


def camera_zoom_golden_name(provider: str) -> str:
    return f"camera_zoom_{provider}.png"


# The selection overlay (outline + gizmo) alone changes the viewport render by
# MEAN_ERROR 0.6-1.1; a render left at the pre-resize aspect changes it by 6.5.
POST_RESIZE_MEAN_LIMIT = 2.5


def render_mean_difference(a: Path, b: Path, viewport: dict) -> float:
    """MEAN_ERROR of two full frames inside the viewport below its HUD band."""
    import numpy as np
    from PIL import Image

    left, top, right, bottom = viewport_box(viewport)
    top += VIEWPORT_CHROME_HEIGHT
    x = np.asarray(Image.open(a).convert("RGB"), dtype=np.int16)[top:bottom, left:right]
    y = np.asarray(Image.open(b).convert("RGB"), dtype=np.int16)[top:bottom, left:right]
    return float(np.abs(x - y).mean())


# Saves the frame the viewport presents — the renderer's image, which is also
# what the headless app's viewport stream sends — read-only, as a PNG.
VIEWPORT_OUTPUT_PROBE = """
from PIL import Image
image = application._viewport_window.get_presentation_image()
if image is None:
    result = None
else:
    Image.fromarray(image[..., :3]).save(OUT)
    result = list(image.shape)
"""


def capture_viewport_output(session: FullAppSession, out: Path) -> tuple:
    shape = session.execute(VIEWPORT_OUTPUT_PROBE.replace("OUT", repr(str(out))))
    assert shape, (
        "the viewport presented no image (a GPU-only presentation has no CPU "
        "image — this session must run with OVGEAR_ZERO_COPY=0)"
    )
    return tuple(shape)


def run_headless_flow(session: FullAppSession, workdir: Path) -> Path:
    """Drive the headless app and capture its output: the viewport render.

    1. Check the offscreen frame is APP_WINDOW_SIZE and the viewport renders
       at exactly APP_WINDOW_SIZE (the fixed Resolution setting).
    2. Click the cube in the viewport (injected input through the offscreen
       UI, the same path a remote user's click takes); assert the selection.
    3. Wait until three consecutive viewport outputs are identical and return
       the last one. The editor UI is saved only as ``ui_frame.png`` for
       reference; it is not compared.
    """
    from PIL import Image, ImageChops

    _start_and_check(session, workdir / "ui_start.png")
    _click_cube(session)
    session.move(APP_WINDOW_SIZE[0] - 4, APP_WINDOW_SIZE[1] - 4)

    out = workdir / "viewport_output.png"
    previous, same, taken = None, 0, 0
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        shape = capture_viewport_output(session, out)
        taken += 1
        assert shape[:2] == (APP_WINDOW_SIZE[1], APP_WINDOW_SIZE[0]), (
            f"the viewport renders {shape[1]}x{shape[0]}, expected "
            f"{APP_WINDOW_SIZE[0]}x{APP_WINDOW_SIZE[1]}"
        )
        current = Image.open(out).convert("RGB")
        if previous is not None and ImageChops.difference(previous, current).getbbox() is None:
            same += 1
            if same >= 2:
                break
        else:
            same = 0
        previous = current
        time.sleep(1.0)
    else:
        raise RuntimeError(f"viewport output did not settle ({taken} captures)")
    print(f"[stable] viewport output settled after {taken} captures")
    # The CPU readback here must be the OVGEAR_ZERO_COPY=0 pin, not a tier-2
    # path that failed and retired itself.
    assert_zero_copy_tier(session, "disabled", "after the headless flow")
    session.screenshot(workdir / "ui_frame.png")
    return out


# --- Golden compare --------------------------------------------------------
#
# Every capture is a full 1000x720 frame (window tests: the whole window, FPS
# value masked; headless test: the viewport output). It is compared with ONE
# golden shared by Linux x86_64, Windows x64 and Linux ARM64, stored at half
# size: the capture is reduced by a 2x2 box average (GOLDEN_SCALE) to 500x360
# before it is written or compared. Measured cross-platform differences and the
# failure cases these limits must catch are in the README ("Goldens").
#
# Window frames are judged in two regions (headless output: render only):
#  * strict: the UI around the viewport plus the viewport's top band
#    (VIEWPORT_CHROME_HEIGHT px: tool buttons and the SCENE / FPS / RES HUD).
#    The UI is drawn bit-identically on every platform: at most
#    STRICT_PIXEL_LIMIT pixels may differ by more than STRICT_PIXEL_DELTA. A
#    reopened Content browser, a wrong provider's panels, or a missing toolbar
#    or HUD label exceeds it.
#  * render: the rest of the viewport. Its mean error must stay within
#    RENDER_MEAN_LIMIT, and after a 3x3 box blur of both images at most
#    RENDER_PIXEL_LIMIT pixels may differ by more than RENDER_PIXEL_DELTA.
#    The blur absorbs sub-pixel rasterization differences (Linux draws the
#    gizmo with OpenGL, Windows with ovui's default SceneView); the pixel
#    count catches a local change such as a missing, moved or squashed gizmo
#    or outline, which barely moves the mean of the whole viewport.
GOLDEN_SCALE = 2
GOLDEN_SIZE = (APP_WINDOW_SIZE[0] // GOLDEN_SCALE, APP_WINDOW_SIZE[1] // GOLDEN_SCALE)
STRICT_PIXEL_LIMIT = int(os.environ.get("OVUI_E2E_UI_PIXEL_LIMIT", "10"))
STRICT_PIXEL_DELTA = 16
RENDER_MEAN_LIMIT = float(os.environ.get("OVUI_E2E_RENDER_MEAN_LIMIT", "1.0"))
RENDER_PIXEL_DELTA = 32
RENDER_PIXEL_LIMIT = int(os.environ.get("OVUI_E2E_RENDER_PIXEL_LIMIT", "40"))
VIEWPORT_CHROME_HEIGHT = 64
MIN_VIEWPORT_STDDEV = 3.0
MIN_SELECTION_OVERLAY_PIXELS = 300
# The x and y arrows of the move gizmo (observed ~300 pixels each).
MIN_GIZMO_ARROW_PIXELS = 80
GIZMO_ORIGIN_TOLERANCE = 12
# The blue selection outline of the cube in the viewport output.
MIN_OUTLINE_PIXELS = 150


def is_generating() -> bool:
    return os.environ.get("OMNI_UI_GENERATE_GOLDEN", "").strip() == "1"


def to_golden_size(frame: Path):
    """The capture at golden size (2x2 box average), RGB."""
    from PIL import Image

    img = Image.open(frame).convert("RGB")
    assert img.size == APP_WINDOW_SIZE, f"frame is {img.size}, expected {APP_WINDOW_SIZE}"
    return img.reduce(GOLDEN_SCALE)


def render_mask(size: tuple, viewport: Optional[dict]):
    """L-mode mask (golden size) of the render region; None = whole image.

    Boundary pixels that mix UI and render belong to the render region.
    """
    from PIL import Image, ImageDraw

    mask = Image.new("L", size, 0 if viewport else 255)
    if viewport:
        left, top, right, bottom = viewport_box(viewport)
        top += VIEWPORT_CHROME_HEIGHT
        k = GOLDEN_SCALE
        ImageDraw.Draw(mask).rectangle(
            (left // k, top // k, -(-right // k) - 1, -(-bottom // k) - 1), fill=255
        )
    return mask


def golden_metrics(golden, captured, viewport: Optional[dict], workdir: Path) -> dict:
    """Compare two golden-size images; save amplified diffs when they differ."""
    import numpy as np
    from PIL import Image, ImageFilter

    g = np.asarray(golden, dtype=np.int16)
    c = np.asarray(captured, dtype=np.int16)
    diff = np.abs(g - c)
    biggest = diff.max(axis=2)
    blurred = np.abs(
        np.asarray(golden.filter(ImageFilter.BoxBlur(1)), dtype=np.int16)
        - np.asarray(captured.filter(ImageFilter.BoxBlur(1)), dtype=np.int16)
    ).max(axis=2)
    render = np.asarray(render_mask(golden.size, viewport)) > 0
    strict = ~render
    out = {
        "strict_changed": int((biggest[strict] > STRICT_PIXEL_DELTA).sum()),
        "render_mean": float(diff[render].mean()) if render.any() else 0.0,
        "render_changed": int((blurred[render] > RENDER_PIXEL_DELTA).sum()),
    }
    if biggest.any():
        Image.fromarray(np.clip(diff * 10, 0, 255).astype(np.uint8)).save(workdir / "diff_x10.png")
    return out


def gizmo_arrows(frame: Path, viewport: dict) -> dict:
    """Find the move gizmo's x (red) and y (green) arrows in the viewport.

    The scene is grey and the selection outline is blue, so saturated red and
    green pixels in the viewport come only from the gizmo. Returns, per
    arrow, its pixel count and bounding box, and whether the two form a gizmo:
    enough pixels, the red arrow horizontal, the green arrow vertical, and the
    red arrow starting where the green arrow ends (the gizmo origin).
    """
    from PIL import Image

    left, top, right, bottom = viewport_box(viewport)
    img = Image.open(frame).convert("RGB")
    px = img.load()
    found = {"x": [], "y": []}
    for yy in range(top + VIEWPORT_CHROME_HEIGHT, bottom):
        for xx in range(left, right):
            r, g, b = px[xx, yy]
            if r - max(g, b) >= 50 and r >= 130:
                found["x"].append((xx, yy))
            elif g - max(r, b) >= 40 and g >= 110:
                found["y"].append((xx, yy))
    out = {}
    for axis, pts in found.items():
        box = (
            (min(p[0] for p in pts), min(p[1] for p in pts),
             max(p[0] for p in pts), max(p[1] for p in pts)) if pts else None
        )
        out[axis] = {"pixels": len(pts), "bbox": box}
    rx, gy = out["x"]["bbox"], out["y"]["bbox"]
    ok = (
        out["x"]["pixels"] >= MIN_GIZMO_ARROW_PIXELS
        and out["y"]["pixels"] >= MIN_GIZMO_ARROW_PIXELS
        and rx is not None and gy is not None
        # x arrow runs sideways (slanted by the perspective in some views),
        # y arrow is vertical
        and (rx[2] - rx[0]) >= 1.5 * (rx[3] - rx[1] + 1)
        and (gy[3] - gy[1]) >= 3 * (gy[2] - gy[0] + 1)
        # they meet at the gizmo origin: the x arrow starts at the y arrow's
        # foot (allowing for the arrow line width)
        and abs(rx[0] - gy[2]) <= GIZMO_ORIGIN_TOLERANCE
        and gy[1] < rx[1] <= gy[3] + GIZMO_ORIGIN_TOLERANCE
    )
    out["drawn"] = bool(ok)
    return out


def outline_pixels(frame: Path) -> int:
    """Pixels of the blue selection outline (the scene itself is grey)."""
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(frame).convert("RGB"), dtype=np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return int(((b - np.maximum(r, g) >= 40) & (b >= 150) & (g > 100)).sum())


def _compare_or_generate(frame: Path, viewport: Optional[dict], golden: Path,
                         workdir: Path, label: str) -> None:
    from PIL import Image

    small = to_golden_size(frame)
    small.save(workdir / "capture_golden_size.png")
    if is_generating():
        golden.parent.mkdir(parents=True, exist_ok=True)
        small.save(golden)
        print(f"[golden] wrote {golden} ({small.size[0]}x{small.size[1]})")
        return
    assert golden.exists(), (
        f"No golden image for {label} at {golden}. Generate it with "
        "OMNI_UI_GENERATE_GOLDEN=1 (CI: workflow_dispatch mode=generate)."
    )
    reference = Image.open(golden).convert("RGB")
    assert reference.size == GOLDEN_SIZE, (
        f"the golden {golden} is {reference.size}, expected {GOLDEN_SIZE}"
    )
    m = golden_metrics(reference, small, viewport, workdir)
    print(
        f"[compare] {label} on {platform_key()}: strict changed={m['strict_changed']} "
        f"(max {STRICT_PIXEL_LIMIT}); render MEAN_ERROR={m['render_mean']:.4f} "
        f"(max {RENDER_MEAN_LIMIT}), render changed={m['render_changed']} "
        f"(max {RENDER_PIXEL_LIMIT})"
    )
    if (m["strict_changed"] > STRICT_PIXEL_LIMIT or m["render_mean"] > RENDER_MEAN_LIMIT
            or m["render_changed"] > RENDER_PIXEL_LIMIT):
        raise AssertionError(
            f"Golden mismatch for {label} on {platform_key()}: {m}.\n"
            f"  golden:   {golden}\n  captured: {frame}\n  diffs:    {workdir}"
        )


def check_frame_and_golden(frame: Path, viewport: dict, golden: Path, workdir: Path,
                           label: str) -> None:
    """Window frame: render guards, then generate the golden or compare."""
    from PIL import Image, ImageStat

    img = Image.open(frame).convert("RGB")
    assert img.size == APP_WINDOW_SIZE, f"frame is {img.size}, expected {APP_WINDOW_SIZE}"
    stat = ImageStat.Stat(img, viewport_mask(img.size, viewport))
    stddev = sum(stat.stddev) / len(stat.stddev)
    assert stddev >= MIN_VIEWPORT_STDDEV, f"viewport looks blank (stddev={stddev:.3f})"
    region = workdir / "_viewport_region.png"
    img.crop(viewport_box(viewport)).save(region)
    overlay_px = selection_overlay_pixels(region)
    assert overlay_px >= MIN_SELECTION_OVERLAY_PIXELS, (
        f"selection highlight not visible: {overlay_px} coloured overlay pixels "
        f"(need >= {MIN_SELECTION_OVERLAY_PIXELS})"
    )
    gizmo = gizmo_arrows(frame, viewport)
    print(f"[gizmo] {gizmo}")
    assert gizmo["drawn"], (
        f"the move gizmo of the selected cube is not drawn: {gizmo} (need a red "
        f"horizontal x arrow and a green vertical y arrow of >= "
        f"{MIN_GIZMO_ARROW_PIXELS} px each, meeting at the gizmo origin)"
    )
    _compare_or_generate(frame, viewport, golden, workdir, label)


def check_viewport_output_and_golden(frame: Path, golden: Path, workdir: Path,
                                     label: str) -> None:
    """Headless viewport output: render guards, then generate or compare."""
    from PIL import Image, ImageStat

    img = Image.open(frame).convert("RGB")
    assert img.size == APP_WINDOW_SIZE, f"output is {img.size}, expected {APP_WINDOW_SIZE}"
    stddev = sum(ImageStat.Stat(img).stddev) / 3
    assert stddev >= MIN_VIEWPORT_STDDEV, f"viewport output looks blank (stddev={stddev:.3f})"
    outline = outline_pixels(frame)
    print(f"[outline] {outline} px")
    assert outline >= MIN_OUTLINE_PIXELS, (
        f"the selection outline of the cube is not drawn: {outline} outline pixels "
        f"(need >= {MIN_OUTLINE_PIXELS})"
    )
    _compare_or_generate(frame, None, golden, workdir, label)
