# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 3.6 end-to-end keyboard + IME smoke — bridge-path proof (RemoteInputBridge).

SCOPE (consistent with step 3.5 narrowed scope, 2026-05-03):
  The installed ovstream SDK is server-only (no Python WebRTC client).
  This smoke proves the Python-level bridge keyboard + unicode paths only:
    bridge.on_keyboard_event() → deque → drain_bridge_into_ui()
      → omni.ui._ui._inject_key_event(imgui_key, pressed)
    bridge.on_unicode() → deque → drain_bridge_into_ui()
      → omni.ui._ui._inject_text_input(text)
  Exercised against a live headless ovui Vulkan context.

EXPLICITLY NOT IN SCOPE FOR STEP 3.6:
  - Mouse wheel / scroll: bridge.on_mouse_event(WHEEL) is a mouse-path event;
    it is tested via step 3.5's mouse infrastructure, not here.
  - Supplementary-plane emoji (U+10000+): ovui build limitation — see below.
  - WebRTC transport, Server.on_input, SDK worker-thread delivery.

UNICODE PAYLOAD:
  "测试☺" — two CJK characters (U+6D4B U+8BD5) + BMP smiley (U+263A).
  All are in the Basic Multilingual Plane (≤U+FFFF), 3-byte UTF-8.
  Supplementary-plane emoji (4-byte UTF-8, e.g. 🎮 U+1F3AE) produce U+FFFD
  in this ovui build's _inject_text_input path; that limitation is NOT in
  scope here.

HONESTY NOTE — Ctrl+S / shortcut dispatch:
  The shortcut scope states "Ctrl+S → save dialog".  In ovwidgets.app, Ctrl+S
  calls Application.save_stage() via Application._on_key_pressed, which is an
  ovui/GLFW window callback — NOT part of ImGui's IO processing.

  The bridge injects keys via omni.ui._ui._inject_key_event(), which puts them
  into ImGui's IO buffer.  That buffer drives ImGui widgets (InputText cursor,
  Escape revert, etc.).  It does NOT fire ovui's key_pressed_fn callbacks.
  Those callbacks require a real GLFW KeyEvent from the OS window system.

  Consequence: Ctrl+S (and all other app-level shortcuts) are NOT reachable
  via the bridge in this ovui headless build — save_stage() never fires.
  Verified by monkeypatch in this smoke test (count == 0 confirmed).
  This is a known architectural limitation of the bridge-injection path;
  fixing it (e.g. via a second ovui-level keyboard hook) is out of scope for
  step 3.6.

TEAM-OF-AGENTS protocol run:

Architect: Same headless Vulkan boot as step 3.5.  Bridge wired to
  Application via set_remote_input_bridge().  Key events via
  bridge.on_keyboard_event(); unicode text via bridge.on_unicode().
  Filter field focus via direct StageWidget API (test setup, not proved).

PM: Hard assertions —
  * filter_model.get_value_as_string() == "测试☺" after on_unicode() [FAIL if not]
  * Filter pixel diff Shot 1→2 > _FILTER_DIFF_THRESHOLD [FAIL if not]
  * filter_model.get_value_as_string() == "" after Escape [FAIL if not]
  Path exercises (no observable state assertion):
  * Tab key sent through bridge without exception
  * Arrow keys LEFT/RIGHT/UP/DOWN sent through bridge without exception
  * Ctrl+S key sequence sent; monkeypatch confirms save_stage() NOT called
    (bridge injects into ImGui IO — ovui key_pressed_fn callbacks don't fire)
  NOT asserted: cursor position, Tab focus-move, save dialog, Ctrl+S dispatch,
                scroll.

Dev-Lead: Bridge keyboard path end-to-end:
  on_keyboard_event() → RemoteInputBridge deque →
  Application._drain_remote_input() → drain_bridge_into_ui() →
  _inject_key_event(imgui_key, pressed) →
  HeadlessVulkanPlatform::applyInjectedInput() → ImGui::NewFrame().
  on_unicode() → deque → drain → _inject_text_input() →
  ImGui::AddInputCharactersUTF8 → StringField model updated.
  Direct _inject_* calls NOT used — they bypass the bridge.

Build Specialist: run as:
  cd <path-to-ovgear>
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \\
  PYTHONPATH=<path-to-ovui>/python:<path-to-usd-build>/install/lib/python \\
  OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan OVRTX_SKIP_USD_CHECK=1 \\
      <path-to-python3.12> \\
      tests/qa_step36_keyboard_smoke.py

Shots saved to /tmp/step36_shot{1..6}_*.png.
"""

from __future__ import annotations

import os
import sys

# CRITICAL: force headless backend BEFORE importing omni.ui.
# Using os.environ["…"] = "1" (not setdefault) so a caller-set value
# cannot silently override the required headless mode.
os.environ["OMNIUI_HEADLESS"] = "1"
os.environ["OMNIUI_BACKEND"] = "vulkan"

import asyncio
import traceback
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Add ovwidgets.app venv site-packages for ovstream and other dependencies.
import site

_VENV_PKGS = os.path.join(
    os.path.dirname(__file__), "..", "_venv312", "lib", "python3.12", "site-packages"
)
if os.path.isdir(_VENV_PKGS):
    site.addsitedir(_VENV_PKGS)

import omni.ui as ui
from omni.ui import testing as uitesting
from ovstream import KeyboardEvent, KeyState

from ovwidgets.app._input_bridge import RemoteInputBridge
from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus

# ── Constants ──────────────────────────────────────────────────────────────

_W, _H = 1280, 720
_SCENE = str(Path(__file__).parent / "data" / "simple_scene.usda")

# NVST key codes used in this smoke test.
# Full table in ovwidgets.app/_input_keymap.py and ovwidgets.app._input_keymap.
_NVST_ESC   = 0x0100  # NVST_KEY_ESCAPE   → ImGuiKey_Escape (526)
_NVST_TAB   = 0x0101  # NVST_KEY_TAB      → ImGuiKey_Tab (512)
_NVST_LEFT  = 0x0202  # NVST_KEY_LEFT     → ImGuiKey_LeftArrow (513)
_NVST_UP    = 0x0203  # NVST_KEY_UP       → ImGuiKey_UpArrow (515)
_NVST_RIGHT = 0x0204  # NVST_KEY_RIGHT    → ImGuiKey_RightArrow (514)
_NVST_DOWN  = 0x0205  # NVST_KEY_DOWN     → ImGuiKey_DownArrow (516)
_NVST_LCTRL = 0x0305  # NVST_KEY_LCONTROL → ImGuiKey_LeftCtrl (527)
_NVST_S     = 0x0053  # ASCII 'S'         → ImGuiKey_S (564)

# Stage panel filter-field region at 1280×720 (write_split_ini docking).
# The filter field is between the panel header (y≈32..50) and the tree-row
# column headers.  Step 3.5 calibrated the first tree row at y=102.
# A conservative region covering the whole header+filter area is used so
# text appearance (or absence) registers in the pixel diff regardless of
# the exact filter field pixel location.
_FILTER_X0, _FILTER_X1 = 0, 375
_FILTER_Y0, _FILTER_Y1 = 35, 100

# Hard lower bound for filter-region pixel diff (Shot 1 → Shot 2 after typing).
# Observed on 2026-05-03 run: Δavg = +16.79.  Threshold of 5.0 leaves
# significant headroom while ruling out noise (< 0.5) and failed injection (0).
_FILTER_DIFF_THRESHOLD = 5.0

# Unicode payload: CJK "test" (U+6D4B U+8BD5) + BMP smiley emoji (U+263A).
# All BMP (≤U+FFFF), 3-byte UTF-8.  Supplementary-plane emoji (4-byte UTF-8,
# e.g. 🎮 U+1F3AE) are NOT used — this ovui build's _inject_text_input
# path replaces them with U+FFFD.  Scroll/wheel events are NOT tested in this
# file — see step 3.5 and the explicit NOT-IN-SCOPE notice in the module header
# above.
_CJK_EMOJI = "测试☺"


# ── Helpers ────────────────────────────────────────────────────────────────

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
    """Average RGB brightness for region [x0,y0)→(x1,y1) inside a PNG.

    Stdlib+numpy decoder handling all five PNG adaptive filter types (0–4).
    Shared pattern with qa_step35_input_smoke.py; kept inline to avoid
    cross-test imports.
    """
    import struct as _st
    import zlib as _zl

    import numpy as np

    with open(path, "rb") as f:
        data = f.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"Not a valid PNG: {path}"

    pos = 8
    w = h = ch = 0
    idat = bytearray()
    while pos < len(data):
        n = _st.unpack_from(">I", data, pos)[0]
        ct, chunk = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + n]
        pos += 12 + n
        if ct == b"IHDR":
            w, h = _st.unpack_from(">II", chunk)
            bd, ctype = chunk[8], chunk[9]
            assert bd == 8, f"Unsupported bit depth {bd} in {path}"
            ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
            assert ch is not None, f"Unsupported color type {ctype}"
        elif ct == b"IDAT":
            idat.extend(chunk)
        elif ct == b"IEND":
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
        elif filt == 1:
            r = row.astype(np.uint8).reshape(w, ch)
            row = np.cumsum(r, axis=0, dtype=np.uint8).reshape(-1).astype(np.int32)
        elif filt == 2:
            row = (row + prev) & 0xFF
        elif filt == 3:
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


async def _drive(n: int) -> None:
    for _ in range(n):
        await ui.next_frame()


def _key_dn(bridge: RemoteInputBridge, code: int, mods: int = 0) -> None:
    bridge.on_keyboard_event(KeyboardEvent(
        key_code=code, scan_code=0, modifiers=mods, key_state=KeyState.DOWN,
    ))


def _key_up(bridge: RemoteInputBridge, code: int, mods: int = 0) -> None:
    bridge.on_keyboard_event(KeyboardEvent(
        key_code=code, scan_code=0, modifiers=mods, key_state=KeyState.UP,
    ))


async def _bridge_key(bridge: RemoteInputBridge, code: int, mods: int = 0) -> None:
    """Send key DOWN (1 frame) + UP (1 frame) through bridge."""
    _key_dn(bridge, code, mods)
    await _drive(1)
    _key_up(bridge, code, mods)
    await _drive(1)


async def _bridge_ctrl_s(bridge: RemoteInputBridge) -> None:
    """Send Ctrl+S sequence through bridge.

    Sequence: LControl DOWN → S DOWN (Ctrl held) → S UP → LControl UP.
    Whether Application._on_key_pressed dispatches to save_stage() is
    verified by the caller via a monkeypatched counter, not asserted here.
    """
    _key_dn(bridge, _NVST_LCTRL, 0)
    await _drive(1)
    _key_dn(bridge, _NVST_S, 0x0002)  # 0x0002 = Ctrl modifier bitmask
    await _drive(2)
    _key_up(bridge, _NVST_S, 0x0002)
    await _drive(1)
    _key_up(bridge, _NVST_LCTRL, 0)
    await _drive(3)


# ── Main ───────────────────────────────────────────────────────────────────

async def _main(tmp_dir: str) -> None:
    print("─" * 60)
    print("STEP 3.6 — bridge keyboard + IME smoke (RemoteInputBridge proof)")
    print(f"  Platform: OMNIUI_HEADLESS={os.environ.get('OMNIUI_HEADLESS', '<unset>')}")
    print("─" * 60)

    _failures: list[str] = []
    # Pre-initialize summary state so the post-finally summary never
    # raises NameError if the try block exits early (assertion, exception).
    unicode_ok = False
    filter_avg_1 = filter_avg_2 = 0.0
    escape_clears = False
    shot1 = shot2 = shot3 = shot4 = shot5 = shot6 = "(not captured)"

    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._settings.set("layout.save_path", os.path.join(tmp_dir, "layout.json"))
    app._running = True
    bridge = RemoteInputBridge(width=_W, height=_H)
    app.set_remote_input_bridge(bridge)

    task = asyncio.ensure_future(app.run_async())
    try:
        await _drive(40)

        # ── Open scene ────────────────────────────────────────────────────
        print(f"Opening {_SCENE} …")
        app.open_file(_SCENE)
        await _drive(40)

        # ── Tree expand (test setup) ──────────────────────────────────────
        sw = app._stage_window
        assert sw is not None, "StageWindow not ready after 40 frames — cannot proceed"
        widget = sw._widget
        assert widget is not None, "StageWindow._widget is None — cannot proceed"
        widget.expand("/", recursive=False)
        widget.expand("/World", recursive=False)
        await _drive(8)

        # ── Shot 1 — baseline ─────────────────────────────────────────────
        shot1 = "/tmp/step36_shot1_baseline.png"
        _assert_screenshot(shot1, "Shot 1 baseline")
        filter_avg_1 = _png_region_avg(
            shot1, _FILTER_X0, _FILTER_Y0, _FILTER_X1, _FILTER_Y1
        )
        print(f"[Shot 1] {shot1}  (baseline — stage loaded, filter empty)")
        print(f"  Filter region avg: {filter_avg_1:.2f}")

        # ── Focus filter field ────────────────────────────────────────────
        # Direct API call — test setup only, not the path being proved.
        # focus_keyboard() calls ImGui::SetKeyboardFocusHere() so the
        # subsequent _inject_text_input characters land in this widget.
        assert widget._filter_field is not None, (
            "StageWidget._filter_field not built — cannot test text input"
        )
        widget._focus_filter_field()
        await _drive(5)

        # ── Proof 1 — unicode text input via bridge.on_unicode() ──────────
        # Proved path:
        #   bridge.on_unicode(_CJK_EMOJI)
        #   → RemoteInputBridge._events deque (appended)
        #   → Application._drain_remote_input() (pre-tick, main thread)
        #   → drain_bridge_into_ui() → _inject_text_input(_CJK_EMOJI)
        #   → HeadlessVulkanPlatform::applyInjectedInput()
        #   → ImGui::GetIO().AddInputCharactersUTF8
        #   → ImGui InputText processes chars → StringField model updated.
        print(f"  bridge.on_unicode({_CJK_EMOJI!r}) …")
        bridge.on_unicode(_CJK_EMOJI)
        await _drive(8)

        shot2 = "/tmp/step36_shot2_unicode_typed.png"
        _assert_screenshot(shot2, "Shot 2 unicode typed")
        filter_avg_2 = _png_region_avg(
            shot2, _FILTER_X0, _FILTER_Y0, _FILTER_X1, _FILTER_Y1
        )
        print(f"[Shot 2] {shot2}  (expect CJK+emoji text in filter field)")
        print(f"  Filter region avg: {filter_avg_2:.2f}")

        # Primary assertion: StringField model reflects the typed text.
        model_val = widget._filter_field.model.get_value_as_string()
        print(f"  Filter model value after on_unicode: {model_val!r}")
        unicode_ok = (model_val == _CJK_EMOJI)
        if unicode_ok:
            print("  Unicode text input via bridge: ✓ PASS")
        else:
            msg = (
                f"bridge on_unicode: filter model={model_val!r} "
                f"≠ expected={_CJK_EMOJI!r}"
            )
            print(f"  Unicode text input via bridge: ✗ FAIL  ({msg})")
            _failures.append(msg)

        # Hard visual assertion: typing text must change pixel brightness in the
        # filter region.  Both the model check AND the pixel diff must pass.
        filter_diff = filter_avg_2 - filter_avg_1
        if abs(filter_diff) > _FILTER_DIFF_THRESHOLD:
            print(
                f"  Filter region pixel diff Shot 1→2: ✓ PASS  "
                f"Δavg={filter_diff:+.2f} (threshold {_FILTER_DIFF_THRESHOLD})"
            )
        else:
            msg = (
                f"filter region pixel diff too small: "
                f"Δavg={filter_diff:+.2f} ≤ threshold {_FILTER_DIFF_THRESHOLD} — "
                "text did not render visibly"
            )
            print(f"  Filter region pixel diff Shot 1→2: ✗ FAIL  ({msg})")
            _failures.append(msg)

        # ── Path exercise — arrow keys via bridge.on_keyboard_event() ────
        # Proved: on_keyboard_event() → drain → _inject_key_event(code, down/up)
        # completes without exception for four arrow key codes.
        # Cursor position is NOT asserted — it is not exposed by the model API.
        print("  bridge arrow keys LEFT RIGHT UP DOWN …")
        await _bridge_key(bridge, _NVST_LEFT)
        await _bridge_key(bridge, _NVST_RIGHT)
        await _bridge_key(bridge, _NVST_UP)
        await _bridge_key(bridge, _NVST_DOWN)
        await _drive(4)

        shot3 = "/tmp/step36_shot3_after_arrows.png"
        _assert_screenshot(shot3, "Shot 3 after arrow keys")
        print(
            f"[Shot 3] {shot3}  "
            "(arrow keys sent; no cursor-position assertion)"
        )

        # ── Path exercise — Tab key via bridge ────────────────────────────
        # Proved: Tab key event travels bridge → drain → _inject_key_event
        # without exception.  Whether focus moves is NOT asserted — ImGui
        # headless does not fire the StringField end_edit callback on Tab
        # injection in this build, so _filter_rect.name is not observable.
        print("  bridge Tab …")
        await _bridge_key(bridge, _NVST_TAB)
        await _drive(5)

        shot4 = "/tmp/step36_shot4_after_tab.png"
        _assert_screenshot(shot4, "Shot 4 after Tab")
        rect_name_after_tab = (
            getattr(widget._filter_rect, "name", None)
            if widget._filter_rect is not None else None
        )
        print(
            f"[Shot 4] {shot4}  "
            f"(Tab sent; _filter_rect.name={rect_name_after_tab!r} — "
            "focus-move not observable in headless; path exercised without exception)"
        )

        # ── Proof 4 — Escape via bridge (reverts/clears filter text) ──────
        # Re-focus the filter field (Tab may have shifted focus away).
        widget._focus_filter_field()
        await _drive(3)

        print("  bridge Escape …")
        await _bridge_key(bridge, _NVST_ESC)
        await _drive(5)

        shot5 = "/tmp/step36_shot5_after_escape.png"
        _assert_screenshot(shot5, "Shot 5 after Escape")
        filter_avg_5 = _png_region_avg(
            shot5, _FILTER_X0, _FILTER_Y0, _FILTER_X1, _FILTER_Y1
        )
        print(f"[Shot 5] {shot5}  (expect filter text cleared by Escape)")
        print(f"  Filter region avg: {filter_avg_5:.2f}")

        # Hard assertion: ImGui InputText reverts to the activation-time value
        # on Escape.  We called focus_keyboard() when the field was empty, so
        # the activation value is ""; Escape must restore it.
        model_val_after_esc = widget._filter_field.model.get_value_as_string()
        print(f"  Filter model after Escape: {model_val_after_esc!r}")
        escape_clears = (model_val_after_esc == "")
        if escape_clears:
            print("  Escape clears filter field: ✓ PASS")
        else:
            msg = (
                f"Escape did not clear filter field: "
                f"model={model_val_after_esc!r} after Escape (expected '')"
            )
            print(f"  Escape clears filter field: ✗ FAIL  ({msg})")
            _failures.append(msg)

        # ── Path exercise — Ctrl+S via bridge (shortcut dispatch NOT proven) ──
        # Monkeypatch app.save_stage to measure whether it fires.
        # Known result: it does NOT fire.  The bridge uses _inject_key_event
        # (ImGui IO path).  ovui's key_pressed_fn callbacks (including
        # Application._on_key_pressed) require a real GLFW KeyEvent; injected
        # ImGui keys do not raise that event.  The count will be 0; that is
        # expected and documented, not a test failure.
        _ctrl_s_save_count = [0]
        _orig_save_stage = app.save_stage

        def _counted_save_stage(*args: object, **kwargs: object) -> object:
            _ctrl_s_save_count[0] += 1
            return _orig_save_stage(*args, **kwargs)

        app.save_stage = _counted_save_stage  # type: ignore[method-assign]
        try:
            print("  bridge Ctrl+S …")
            await _bridge_ctrl_s(bridge)
            await _drive(5)
        finally:
            app.save_stage = _orig_save_stage  # type: ignore[method-assign]

        shot6 = "/tmp/step36_shot6_after_ctrl_s.png"
        _assert_screenshot(shot6, "Shot 6 after Ctrl+S")
        print(
            f"[Shot 6] {shot6}  "
            f"(Ctrl+S sent; save_stage() count={_ctrl_s_save_count[0]} — "
            "known: key_pressed_fn does not fire from ImGui-injected keys)"
        )
        print(
            f"  Ctrl+S key injection path             : SENT "
            f"(save_stage count={_ctrl_s_save_count[0]}; "
            "key_pressed_fn not triggered by injection — documented limitation)"
        )

    finally:
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
                # Print immediately so the failure is visible even if exit follows.
                print(f"  run_async() raised: {exc!r}", file=sys.stderr)
                _failures.append(f"run_async() raised: {exc!r}")
        finally:
            app.shutdown()

    # ── Summary ─────────────────────────────────────────────────────────
    # Printed AFTER cleanup so task-exception failures appear here too.
    print()
    print("── Step 3.6 keyboard smoke result ───────────────────────────")
    # Hard assertions:
    print(
        f"  bridge.on_unicode() → filter model       : "
        f"{'PASS' if unicode_ok else 'FAIL'}"
    )
    filter_diff_ok = abs(filter_avg_2 - filter_avg_1) > _FILTER_DIFF_THRESHOLD
    print(
        f"  filter pixel diff Shot1→2 > {_FILTER_DIFF_THRESHOLD}      : "
        f"{'PASS' if filter_diff_ok else 'FAIL'}"
    )
    print(
        f"  Escape clears filter field               : "
        f"{'PASS' if escape_clears else 'FAIL'}"
    )
    # Path exercises (no observable state assertion):
    print(
        "  Tab key via bridge                       : SENT (headless: no end_edit signal)"
    )
    print(
        "  Arrow keys LEFT/RIGHT/UP/DOWN via bridge : SENT (no cursor-pos assertion)"
    )
    print(
        "  Ctrl+S key sequence via bridge           : SENT "
        "(save_stage NOT called — key_pressed_fn requires GLFW event, not ImGui injection)"
    )
    print(
        "  Scroll/wheel events                      : NOT IN SCOPE (step 3.5)"
    )
    print(f"  Screenshots: {shot1}")
    for s in (shot2, shot3, shot4, shot5, shot6):
        print(f"               {s}")
    if _failures:
        print(f"  FAILURES ({len(_failures)}):")
        for msg in _failures:
            print(f"    - {msg}")
    else:
        print("  All hard checks PASSED.")
    print("─────────────────────────────────────────────────────────────")

    if _failures:
        sys.exit(len(_failures))


if __name__ == "__main__":
    import tempfile

    _tmp_ini_dir = tempfile.mkdtemp(prefix="ovgear_step36_ini_")
    os.chdir(_tmp_ini_dir)

    write_split_ini()
    ui.init("OvGear step36 smoke", width=_W, height=_H)
    apply_global_styles()
    set_theme("dark")
    _exit_code = [0]
    try:
        ui.run(_main(_tmp_ini_dir))
    except SystemExit as exc:
        _exit_code[0] = exc.code if isinstance(exc.code, int) else 1
    except BaseException:
        # Unexpected top-level failure: print full traceback to stderr so the
        # failure is diagnosable even though os._exit() follows immediately.
        traceback.print_exc()
        _exit_code[0] = 1
    # Bypass ovui/ovrtx RasterImageProvider destructor crash that produces
    # exit code -1 during normal Python finalization after ui.run() returns.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_exit_code[0])
