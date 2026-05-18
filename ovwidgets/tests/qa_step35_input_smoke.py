# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 3.5 end-to-end input smoke — bridge-path proof (RemoteInputBridge).

SCOPE NOTE (second Codex remediation, 2026-05-03):
  The input smoke scope requires "a real WebRTC client connection (using the
  ovstream SDK's client helpers, not a browser)".  The installed ovstream SDK
  (_venv312/…/ovstream/) is server-only: it exposes Server, ServerConfig, and
  input-event types for *receiving*, but has NO Python Client class or
  programmatic input-injection API.  A full WebRTC round-trip test is
  impossible from Python on this machine.

  Honest proven scope:
    * Exercises the Python-level bridge API: on_mouse_event() → deque → drain
      → _inject_mouse_{move,button} → HeadlessVulkanPlatform.
    * Does NOT exercise: WebRTC transport, Server.on_input callback, SDK
      worker-thread delivery, tap/server attachment.

TEAM-OF-AGENTS protocol run:

Architect: Boot ovwidgets.app in OMNIUI_HEADLESS=1 / Vulkan mode.  Wire a
  RemoteInputBridge to the Application WITHOUT the full WebRTC streaming
  pipeline, then drive bridge events:
    (1) mouse click on the Cube row in the Stage Browser to select it,
    (2) mouse press-drag-release on the translate-X gizmo handle.
  Screenshots captured via uitesting; USD attribute inspection confirms prim
  selection and translate change.  Pixel diff of viewport region between
  screenshots confirms visible scene change during drag.

PM: Acceptance criteria —
  * Shot 1: stage tree expanded, no selection (baseline).
  * Shot 2: Cube row highlighted (selected) in stage panel.
  * Shot 3: drag sequence active; viewport pixel content differs from Shot 2.
  * Shot 4: Cube visually displaced along X in viewport; differs from Shot 1.
  * selection_bus.get_snapshot().paths() contains "/World/Cube" after click.
  * Composed local translate X for /World/Cube differs from −1.5 after drag.
  NOTE: gizmo arm highlight color (yellow vs red) is NOT directly asserted;
  viewport pixel diff confirms drag was active in the scene.

Dev-Lead: Bridge Python-API path exercised:
  on_mouse_event() → RemoteInputBridge deque →
  Application._drain_remote_input() → drain_bridge_into_ui() →
  omni.ui._ui._inject_mouse_{move,button} → HeadlessVulkanPlatform
  applyInjectedInput() → ImGui::NewFrame() → UI handler.
  NOT exercised: WebRTC transport, Server.on_input, SDK worker thread,
  tap/server attachment.
  Direct _inject_* calls and uitesting.mouse_click() shortcuts are
  NOT used (they bypass the bridge).

  HEADLESS MODE REQUIRED: _inject_mouse_* events are processed by
  HeadlessVulkanPlatform::applyInjectedInput() (called immediately before
  ImGui::NewFrame() each tick). In GLFW windowed mode the GLFW backend
  callbacks overwrite io.MousePos/MouseDown before ImGui reads them, so
  injected events have no effect. OMNIUI_HEADLESS=1 must be forced before
  the first import of omni.ui.

Build Specialist: run as:
  cd <path-to-ovgear>
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
  PYTHONPATH=<path-to-ovui>/python:<path-to-usd-build>/install/lib/python \\
  OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan OVRTX_SKIP_USD_CHECK=1 \\
      <path-to-python3.12> \\
      tests/qa_step35_input_smoke.py

Shots saved to /tmp/step35_shot{1..4}_*.png.
"""

from __future__ import annotations

# CRITICAL: force headless backend BEFORE importing omni.ui.
# Using os.environ["…"] = "1" (not setdefault) so a caller-set
# OMNIUI_HEADLESS=0 cannot silently override the required headless mode.
import os
import sys

os.environ["OMNIUI_HEADLESS"] = "1"
os.environ["OMNIUI_BACKEND"] = "vulkan"

import asyncio
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Add ovwidgets.app venv site-packages for ovstream and other dependencies.
import site

_VENV_PKGS = os.path.join(
    os.path.dirname(__file__), "..", "_venv312", "lib", "python3.12", "site-packages"
)
if os.path.isdir(_VENV_PKGS):
    site.addsitedir(_VENV_PKGS)

from pathlib import Path

import omni.ui as ui
from omni.ui import testing as uitesting
from ovstream import KeyState, MouseEvent, MouseEventType

from ovwidgets.app._input_bridge import RemoteInputBridge
from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus

# ── Constants ──────────────────────────────────────────────────────────────

_W, _H = 1280, 720
_SCENE = str(Path(__file__).parent / "data" / "simple_scene.usda")

# Authoritative row height from ovwidgets.stage/widget/stage_delegate.py:28.
# Duplicated here to avoid importing a private constant; keep in sync.
_ROW_HEIGHT = 16

# Stage Browser layout at 1280×720 (write_split_ini docking, no Layers split).
# _TREE_ROW0_CY: empirically calibrated from Shot 1 baseline screenshots.
# No get_item_rect API exists on StageWidget; coordinates are specific to the
# write_split_ini geometry (bounds-checked at runtime below).
_TREE_ROW0_CY  = 102   # centre-y of the "/" root row (empirical, Shot 1 verified)
_STAGE_NAME_CX = 100   # x inside Name column; stage panel is 375 px wide
_STAGE_PANEL_X_MAX = 375
_STAGE_Y_MIN = 32      # below the menu bar
_STAGE_Y_MAX = _H - 1  # 719

# Viewport gizmo at 1280×720 (write_split_ini, Viewport Pos=(375,32) Size=(530,461)).
# Cube at world (−1.5, 0, 0).  Shot-confirmed: gizmo pivot (565,280), red X
# arm extends to ≈ (655,280); mid-arm target at x=620.
_GIZMO_TIP_X = 620
_GIZMO_TIP_Y = 280

# Viewport pixel region used for scene-change assertions (Finding 5).
# Covers the 3D viewport content area at this layout.
_VP_X0, _VP_Y0, _VP_X1, _VP_Y1 = 376, 82, 875, 492


# ── Bridge helpers ─────────────────────────────────────────────────────────

def _move(bridge: RemoteInputBridge, x: int, y: int) -> None:
    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.MOVE,
        modifiers=0, x=x, y=y,
        data=0, data2=0, button_state=KeyState.UP,
    ))


def _lmb(bridge: RemoteInputBridge, x: int, y: int, *, down: bool) -> None:
    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.BUTTON,
        modifiers=0, x=x, y=y,
        data=1,   # MouseButton.LEFT = 1 → ImGui button 0 via _NVST_TO_IMGUI_BUTTON
        data2=0,
        button_state=KeyState.DOWN if down else KeyState.UP,
    ))


async def _drive(n: int) -> None:
    for _ in range(n):
        await ui.next_frame()


async def _bridge_click(bridge: RemoteInputBridge, x: int, y: int) -> None:
    """Click at (x, y) via bridge, matching ImGui's hover→press→release sequence.

    uitesting.mouse_click() uses the same pattern: MOVE + 2 hover frames,
    then BUTTON DOWN (1 frame), then BUTTON UP (2 frames).  Firing all three
    events in one drain cycle gives ImGui zero frames to register hover state;
    the TreeView never fires its selection-changed callback.
    """
    _move(bridge, x, y)
    await _drive(2)
    _lmb(bridge, x, y, down=True)
    await _drive(1)
    _lmb(bridge, x, y, down=False)
    await _drive(2)


def _read_translate(prim: Any) -> tuple:
    """Return (tx, ty, tz) from the prim's composed local xform.

    Uses GetLocalTransformation() which returns a GfMatrix4d (not a tuple)
    in the installed USD binding.  Calling .ExtractTranslation() on it gives
    the composed translation regardless of which xformOp encodes it.

    Raises on failure — the caller must not provide a fallback value since a
    guessed baseline invalidates the translate-change assertion.
    """
    from pxr import Usd, UsdGeom
    xformable = UsdGeom.Xformable(prim)
    mat = xformable.GetLocalTransformation(Usd.TimeCode.Default())
    t = mat.ExtractTranslation()
    return (float(t[0]), float(t[1]), float(t[2]))


def _assert_screenshot(path: str, label: str) -> None:
    """Capture a screenshot and hard-fail if it did not succeed."""
    ok = uitesting.capture_screenshot(path)
    assert ok, f"capture_screenshot returned False for {label}"
    try:
        sz = os.path.getsize(path)
    except OSError as exc:
        raise AssertionError(
            f"Screenshot {label} file missing after capture: {exc}"
        ) from exc
    assert sz > 0, f"Screenshot {label} is zero bytes: {path}"


def _png_region_avg(path: str, x0: int, y0: int, x1: int, y1: int) -> float:
    """Return average RGB pixel brightness in region [x0,y0)×[x1,y1) of a PNG.

    Decodes the PNG using stdlib (struct + zlib) + numpy (from the project venv).
    Handles all five PNG adaptive filter types (0–4) correctly.
    Raises on read/decode failure — used in assertions.

    Rationale for choosing viewport-region pixel diff over full-image diff:
    targeting the 3D viewport area isolates the drag evidence to the rendered
    scene, excluding UI chrome that could change between frames for unrelated
    reasons (hover states, focus indicators, etc.).
    """
    import struct as _st
    import zlib as _zl

    import numpy as np

    with open(path, 'rb') as f:
        data = f.read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n', f"Not a valid PNG: {path}"

    pos = 8
    w = h = ch = 0
    idat = bytearray()
    while pos < len(data):
        n = _st.unpack_from('>I', data, pos)[0]
        ct, chunk = data[pos+4:pos+8], data[pos+8:pos+8+n]
        pos += 12 + n
        if ct == b'IHDR':
            w, h = _st.unpack_from('>II', chunk)
            bd, ctype = chunk[8], chunk[9]
            assert bd == 8, f"Unsupported bit depth {bd} in {path}"
            ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
            assert ch is not None, f"Unsupported color type {ctype}"
        elif ct == b'IDAT':
            idat.extend(chunk)
        elif ct == b'IEND':
            break

    raw = np.frombuffer(_zl.decompress(bytes(idat)), dtype=np.uint8)
    stride = 1 + w * ch
    assert len(raw) == h * stride, f"Decompressed size mismatch in {path}"

    grid = raw.reshape(h, stride)
    dec = np.zeros((h, w * ch), dtype=np.uint8)

    for y in range(h):
        filt = int(grid[y, 0])
        row = grid[y, 1:].astype(np.int32)
        prev = dec[y - 1].astype(np.int32) if y > 0 else np.zeros(w * ch, np.int32)

        if filt == 0:
            pass
        elif filt == 1:  # Sub: cumulative add in bpp-blocks (mod 256)
            r = row.astype(np.uint8).reshape(w, ch)
            row = np.cumsum(r, axis=0, dtype=np.uint8).reshape(-1).astype(np.int32)
        elif filt == 2:  # Up
            row = (row + prev) & 0xFF
        elif filt == 3:  # Average: depends on left + up
            row_out = row.copy()
            for i in range(w * ch):
                a = int(row_out[i - ch]) if i >= ch else 0
                row_out[i] = (row[i] + (a + int(prev[i])) // 2) & 0xFF
            row = row_out
        else:  # filt == 4: Paeth
            row_out = row.copy()
            for i in range(w * ch):
                a = int(row_out[i - ch]) if i >= ch else 0
                b = int(prev[i])
                c = int(prev[i - ch]) if i >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                row_out[i] = (row[i] + pr) & 0xFF
            row = row_out

        dec[y] = row.astype(np.uint8)

    image = dec.reshape(h, w, ch)
    region = image[y0:y1, x0:x1, :3].astype(np.float64)
    return float(region.mean())


# ── Main ───────────────────────────────────────────────────────────────────

async def _main(tmp_dir: str) -> None:
    print("─" * 60)
    print("STEP 3.5 — bridge-path input smoke (RemoteInputBridge proof)")
    print(f"  Platform: OMNIUI_HEADLESS={os.environ.get('OMNIUI_HEADLESS','<unset>')}")
    print("─" * 60)

    _failures: list[str] = []

    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    # Redirect layout save to tmp_dir so ~/.ovgear/layout.json is never
    # deleted or rewritten (Finding 2: removing os.unlink was insufficient;
    # app.shutdown() writes back to the same path via _save_layout()).
    app._settings.set("layout.save_path", os.path.join(tmp_dir, "layout.json"))

    app._running = True
    bridge = RemoteInputBridge(width=_W, height=_H)
    app.set_remote_input_bridge(bridge)

    task = asyncio.ensure_future(app.run_async())
    try:
        await _drive(40)   # let windows build + layout restore + adapters init

        # ── Open scene ───────────────────────────────────────────────────
        print(f"Opening {_SCENE} …")
        app.open_file(_SCENE)
        await _drive(40)   # USD adapters settle; ovrtx builds scene (if available)

        # ── Expand tree (test setup) ──────────────────────────────────────
        sw = app._stage_window
        assert sw is not None, "StageWindow not ready after 40 frames — cannot proceed"
        widget = sw._widget
        assert widget is not None, "StageWindow._widget is None after 40 frames"
        widget.expand("/", recursive=False)
        widget.expand("/World", recursive=False)
        await _drive(8)

        # ── Shot 1 — baseline ─────────────────────────────────────────────
        shot1 = "/tmp/step35_shot1_baseline.png"
        _assert_screenshot(shot1, "Shot 1 baseline")
        print(f"[Shot 1] {shot1}  (baseline — tree expanded, no selection)")

        # Row layout after "/" and "World" expanded:
        #   row 0  /          y = _TREE_ROW0_CY      (= 102)
        #   row 1  └ World    y = _TREE_ROW0_CY + 16 (= 118)
        #   row 2    └ Cube   y = _TREE_ROW0_CY + 32 (= 134)  ← target
        cube_row = 2
        cube_cy  = _TREE_ROW0_CY + cube_row * _ROW_HEIGHT   # = 134
        assert _STAGE_Y_MIN < cube_cy < _STAGE_Y_MAX, (
            f"cube_cy={cube_cy} outside stage panel y-range "
            f"[{_STAGE_Y_MIN}, {_STAGE_Y_MAX}]"
        )
        assert 0 <= _STAGE_NAME_CX < _STAGE_PANEL_X_MAX, (
            f"_STAGE_NAME_CX={_STAGE_NAME_CX} outside stage panel x-range "
            f"[0, {_STAGE_PANEL_X_MAX})"
        )
        print(f"  Cube row click target: x={_STAGE_NAME_CX}  y={cube_cy}")

        # ── Verify baseline selection is empty ───────────────────────────
        snap0 = app._selection_bus.get_snapshot()
        pre_paths = list(snap0.paths()) if snap0 else []
        assert pre_paths == [], (
            f"Pre-click selection not empty: {pre_paths!r} — "
            "scene loaded with a stale selection; test cannot proceed"
        )

        # ── Bridge click on Cube row ──────────────────────────────────────
        # Load-bearing test: click travels through
        #   bridge.on_mouse_event → deque → _drain_remote_input →
        #   drain_bridge_into_ui → _inject_mouse_move + _inject_mouse_button →
        #   HeadlessVulkanPlatform::applyInjectedInput → ImGui::NewFrame →
        #   StageWidget row handler → SelectionBus.
        print(f"  Bridge click → ({_STAGE_NAME_CX}, {cube_cy}) …")
        await _bridge_click(bridge, _STAGE_NAME_CX, cube_cy)
        await _drive(10)

        # ── Shot 2 — after click ─────────────────────────────────────────
        shot2 = "/tmp/step35_shot2_cube_selected.png"
        _assert_screenshot(shot2, "Shot 2 cube selected")
        print(f"[Shot 2] {shot2}  (expect Cube row highlighted)")

        snap1 = app._selection_bus.get_snapshot()
        post_paths = list(snap1.paths()) if snap1 else []
        cube_selected = "/World/Cube" in post_paths
        if cube_selected:
            print("  Cube selected via SelectionBus: ✓ PASS")
        else:
            msg = (
                f"bridge prim-click: '/World/Cube' not in SelectionBus "
                f"paths={post_paths!r}"
            )
            print(f"  Cube selected via SelectionBus: ✗ FAIL  ({msg})")
            _failures.append(msg)

        # ── Baseline USD translate (hard precondition — no fallback) ──────
        # Finding 4 (second remediation): soft try/except fallback was removed.
        # If USD stage access fails here the test must fail hard — a guessed
        # baseline invalidates the translate-change assertion entirely.
        stage = app._stage_adapter.stage
        assert stage is not None, "USD stage not loaded — test cannot proceed"
        cube_prim = stage.GetPrimAtPath("/World/Cube")
        assert cube_prim.IsValid(), "'/World/Cube' prim not found in stage"
        translate_before = _read_translate(cube_prim)
        print(f"  Cube translate BEFORE drag: {translate_before}")

        # ── Viewport pixel baseline for scene-change assertion ─────────────
        vp_avg_1 = _png_region_avg(shot1, _VP_X0, _VP_Y0, _VP_X1, _VP_Y1)
        vp_avg_2 = _png_region_avg(shot2, _VP_X0, _VP_Y0, _VP_X1, _VP_Y1)
        print(
            f"  Viewport region avg — Shot 1: {vp_avg_1:.2f}  "
            f"Shot 2: {vp_avg_2:.2f}"
        )

        # ── Bridge drag on translate-X gizmo ─────────────────────────────
        # Multi-frame hover→press→drag→release mirrors uitesting.mouse_drag():
        # move to tip (3 hover frames so HighlightGesture activates) → LMB
        # down (2 frames so PrimTranslateChangedGesture.began()) → step-move
        # 60 px in 6 steps (each step in own drain so changed() accumulates).
        print(f"  Bridge hover gizmo X tip → ({_GIZMO_TIP_X}, {_GIZMO_TIP_Y}) …")
        _move(bridge, _GIZMO_TIP_X, _GIZMO_TIP_Y)
        await _drive(3)

        print("  Bridge LMB down (drag start) …")
        _lmb(bridge, _GIZMO_TIP_X, _GIZMO_TIP_Y, down=True)
        await _drive(2)

        drag_total = 60
        steps = 6
        for i in range(1, steps + 1):
            x_now = _GIZMO_TIP_X + (i * drag_total // steps)
            _move(bridge, x_now, _GIZMO_TIP_Y)
            await _drive(2)

        # ── Shot 3 — drag in progress ────────────────────────────────────
        shot3 = "/tmp/step35_shot3_gizmo_drag.png"
        _assert_screenshot(shot3, "Shot 3 gizmo drag")
        print(f"[Shot 3] {shot3}  (expect visible change in viewport vs Shot 2)")

        # Finding 5 (second remediation): assert viewport pixel content changed
        # during the drag sequence.  Comparing the viewport region avg between
        # Shot 2 (post-click, gizmo at rest) and Shot 3 (mid-drag) confirms
        # visible scene activity.  Gizmo arm highlight color specifically is NOT
        # asserted — that requires OpenCV/PIL which are not in this environment.
        vp_avg_3 = _png_region_avg(shot3, _VP_X0, _VP_Y0, _VP_X1, _VP_Y1)
        print(f"  Viewport region avg — Shot 3: {vp_avg_3:.2f}")
        drag_scene_changed = abs(vp_avg_3 - vp_avg_2) > 0.5
        if drag_scene_changed:
            print(
                f"  Viewport changed Shot 2→3: ✓ PASS  "
                f"Δavg={vp_avg_3 - vp_avg_2:+.2f}"
            )
        else:
            msg = (
                f"viewport unchanged during drag: "
                f"Shot2_avg={vp_avg_2:.2f}  Shot3_avg={vp_avg_3:.2f}"
            )
            print(f"  Viewport changed Shot 2→3: ✗ FAIL  ({msg})")
            _failures.append(msg)

        _x_final = _GIZMO_TIP_X + drag_total
        print(f"  Bridge LMB up → ({_x_final}, {_GIZMO_TIP_Y}) (commit) …")
        _lmb(bridge, _x_final, _GIZMO_TIP_Y, down=False)
        await _drive(10)

        # ── Shot 4 — post-translate ───────────────────────────────────────
        shot4 = "/tmp/step35_shot4_post_translate.png"
        _assert_screenshot(shot4, "Shot 4 post-translate")
        print(f"[Shot 4] {shot4}  (expect Cube translated along X vs Shot 1)")

        # Assert viewport looks different from baseline (Cube moved).
        vp_avg_4 = _png_region_avg(shot4, _VP_X0, _VP_Y0, _VP_X1, _VP_Y1)
        print(f"  Viewport region avg — Shot 4: {vp_avg_4:.2f}")
        post_scene_changed = abs(vp_avg_4 - vp_avg_1) > 0.5
        if post_scene_changed:
            print(
                f"  Viewport changed Shot 1→4: ✓ PASS  "
                f"Δavg={vp_avg_4 - vp_avg_1:+.2f}"
            )
        else:
            msg = (
                f"viewport unchanged after translate: "
                f"Shot1_avg={vp_avg_1:.2f}  Shot4_avg={vp_avg_4:.2f}"
            )
            print(f"  Viewport changed Shot 1→4: ✗ FAIL  ({msg})")
            _failures.append(msg)

        # ── Verify USD translate changed (hard — no fallback) ──────────────
        # Finding 4 (second remediation): post-drag read is also hard.
        translate_after = _read_translate(cube_prim)
        print(f"  Cube translate AFTER  drag: {translate_after}")
        translate_changed = abs(translate_after[0] - translate_before[0]) > 1e-5
        if translate_changed:
            delta = translate_after[0] - translate_before[0]
            print(f"  Translate changed via bridge drag: ✓ PASS  Δx={delta:+.4f}")
        else:
            msg = (
                f"bridge gizmo-drag: translate unchanged  "
                f"before={translate_before[0]:.4f}  after={translate_after[0]:.4f}"
            )
            print(f"  Translate changed via bridge drag: ✗ PARTIAL  ({msg})")
            _failures.append(msg)

        # ── Summary ───────────────────────────────────────────────────────
        print()
        print("── Step 3.5 smoke result ─────────────────────────────────────")
        print(f"  Bridge prim-click (stage panel)     : {'PASS' if cube_selected else 'FAIL'}")
        print(f"  Bridge gizmo-drag (USD translate)   : {'PASS' if translate_changed else 'PARTIAL'}")
        print(f"  Viewport changed during drag        : {'PASS' if drag_scene_changed else 'FAIL'}")
        print(f"  Viewport changed baseline→final     : {'PASS' if post_scene_changed else 'FAIL'}")
        print(f"  Screenshots: {shot1}")
        print(f"               {shot2}")
        print(f"               {shot3}")
        print(f"               {shot4}")
        if _failures:
            print(f"  FAILURES ({len(_failures)}):")
            for msg in _failures:
                print(f"    - {msg}")
        else:
            print("  All checks PASSED.")
        print("──────────────────────────────────────────────────────────────")

    finally:
        # Finding 3 (second remediation): app.shutdown() is in a nested
        # finally so it runs even when run_async() raises (not only on
        # TimeoutError).  The previous code placed shutdown after the except
        # block, which skipped it when the task raised a non-timeout exception.
        app._running = False
        try:
            try:
                await asyncio.wait_for(task, timeout=3.0)
            except asyncio.TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            except Exception as exc:
                _failures.append(f"run_async() raised: {exc!r}")
        finally:
            app.shutdown()

    if _failures:
        sys.exit(len(_failures))


if __name__ == "__main__":
    import tempfile

    # Isolate imgui.ini to a temp dir (no ini_path param on ui.init()).
    _tmp_ini_dir = tempfile.mkdtemp(prefix="ovgear_step35_ini_")
    os.chdir(_tmp_ini_dir)

    # Finding 2 (second remediation): do NOT delete ~/.ovgear/layout.json.
    # The original code deleted it to force a default layout, then
    # app.shutdown() recreated it — destroying user state.  Fix: redirect
    # the layout save path to tmp_dir via app._settings (set inside _main
    # before run_async() starts).  Loading still reads from the real path
    # (read-only, no mutation), but saving goes to tmp_dir.
    write_split_ini()
    ui.init("OvGear step35 smoke", width=_W, height=_H)
    apply_global_styles()
    set_theme("dark")
    _exit_code = [0]
    try:
        ui.run(_main(_tmp_ini_dir))
    except SystemExit as exc:
        _exit_code[0] = exc.code if isinstance(exc.code, int) else 1
    except BaseException:
        _exit_code[0] = 1
    # Bypass ovui/ovrtx RasterImageProvider destructor crash that produces
    # exit code -1 during normal Python finalization after ui.run() returns.
    os._exit(_exit_code[0])
