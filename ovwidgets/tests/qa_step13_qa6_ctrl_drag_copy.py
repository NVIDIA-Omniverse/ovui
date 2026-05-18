# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA #6 (Ctrl+drag copy) -- Step 13 strict screenshot proof.

Plan Rev 2 §5 lists path #6 (Ctrl+drag copy) -- proves Step 10's local
modifier-bit tracking refactor (``Application.forward_modifier_bits ->
ContentBrowserWindow.forward_modifier_bits ->
FileBrowserWidget.set_modifier_bits -> _is_ctrl_drop -> model.drop(
is_copy=True)``).

omni.ui standalone limitation
-----------------------------
The high-level facade ``omni.ui.testing.press_key(key_code)`` is
one-shot (press+release atomically); it has no ``key_down``/``key_up``
to *hold* a modifier across a multi-step ``mouse_drag``.

The lower-level escape hatch ``omni.ui._ui._inject_key_event(key,
pressed)`` queues an ``io.AddKeyEvent`` consumed by ``ImGui::NewFrame``.
We verified empirically (``/tmp/_probe_ctrl_inject.py``) that the
ImGui event reaches ``io.KeyCtrl`` but does **not** propagate to
``ovui.Window`` panels' ``set_key_pressed_fn`` callback because
``Window::_updateWindow`` gates the dispatch loop on
``ImGui::IsWindowFocused(ImGuiFocusedFlags_ChildWindows)``, which
returns ``false`` for injected-only input even after explicit
``win.focus()`` (see ``omni/ui/_ui.cpp`` Window::_updateWindow,
lines 1188-1213). This is an ovui standalone-backend limitation,
out of scope for the ovgear refactor and unfixable from ovgear.

Workaround chosen, justified by Victor's directive
("lower-level event injection is acceptable only to overcome
``omni.ui.testing`` facade lacking key hold, and must still exercise
the real UI path"): we dispatch ``Application._on_key_pressed(
GLFW_KEY_LEFT_CONTROL=341, modifiers=MOD_CTRL=2, pressed=True)``
directly. This is the **same callback** ovui's ``Window`` invokes
when the user physically holds Ctrl on a focused panel; calling it
with the same arguments enters the production chain at the first
real-user-action step, preserving every downstream production code
path: ``Application.forward_modifier_bits`` ->
``ContentBrowserWindow.forward_modifier_bits`` ->
``FileBrowserWidget.set_modifier_bits``. The drag itself is a real
``omni.ui.testing.mouse_drag``; the drop fires through the
production ``_on_card_drop`` -> ``_dispatch_drop`` -> ``model.drop``
chain, which reads ``_modifier_bits`` and resolves
``is_copy = True``.

What this proof shows visibly
-----------------------------
1. ``/tmp/ovgear_qa6_test/src.txt`` exists; ``target_dir/`` is empty.
2. App boots; content browser navigated to ``/tmp/ovgear_qa6_test/``.
3. Baseline screenshot: detail pane shows ``src.txt`` and
   ``target_dir/`` siblings.
4. Ctrl-down dispatched via the production callback chain.
5. Real ``mouse_drag`` from ``src.txt`` row coords to ``target_dir``
   row coords.
6. Mid-/post-drag screenshot.
7. Navigate into ``target_dir`` via UI double-click.
8. Final screenshot: detail pane now shows the copied ``src.txt``
   inside ``target_dir/``; breadcrumb shows the new path.
9. Filesystem assertion: BOTH ``src.txt`` and
   ``target_dir/src.txt`` exist (i.e., copy not move).

Required env (per Victor's documented aarch64 launch config):
    OVRTX_SKIP_USD_CHECK=1
    PYTHONPATH=<path-to-usd-build>/install/lib/python:$PYTHONPATH
    LD_LIBRARY_PATH=<path-to-usd-build>/install/lib:$LD_LIBRARY_PATH

Outputs:
    /tmp/ovgear_step13_qa06_01_baseline.png
    /tmp/ovgear_step13_qa06_02_after_drag.png
    /tmp/ovgear_step13_qa06_03_inside_target.png
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from omni.ui import testing as uitesting

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles
from ovwidgets.common.selection import SelectionBus

# GLFW key code + modifier bits as documented in
# ovwidgets/app/application.py:60-72 (the same values ovui's
# Window::_updateWindow forwards via ``imguiKeyToGlfwKey``).
GLFW_KEY_LEFT_CONTROL = 341
MOD_CTRL = 2

TEST_ROOT = "/tmp/ovgear_qa6_test"
SRC_FILE = os.path.join(TEST_ROOT, "src.txt")
TARGET_DIR = os.path.join(TEST_ROOT, "target_dir")
COPIED_FILE = os.path.join(TARGET_DIR, "src.txt")

USD_PATH = os.path.join(os.path.dirname(__file__), "data", "simple_scene.usda")
OUT_DIR = "/tmp"


# Coordinates derived from screenshot 01 at 1280x720 with
# write_split_ini layout and content browser navigated to
# /tmp/ovgear_qa6_test/. The detail pane (bottom dock, right half)
# shows the two items as a horizontal pair of icon-cards:
#
#   target_dir (FD folder icon) at ~(660, 582)
#   src.txt    (TXT file icon)  at ~(732, 582)
COORD_DETAIL_PANE_HOME = (635, 580)
COORD_SRC_FILE_ROW     = (732, 582)
COORD_TARGET_DIR_ROW   = (660, 582)


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _shot(name: str) -> str:
    path = f"{OUT_DIR}/ovgear_step13_qa06_{name}.png"
    uitesting.capture_screenshot(path)
    print(f"[qa6] {name}: {path}")
    return path


def _setup_test_files() -> None:
    """Recreate the test fixture so each run starts deterministic."""
    if os.path.isdir(TEST_ROOT):
        shutil.rmtree(TEST_ROOT)
    os.makedirs(TARGET_DIR)
    with open(SRC_FILE, "w", encoding="utf-8") as f:
        f.write("QA #6 Ctrl+drag copy proof file.\n")


async def _main() -> None:
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    # Open simple_scene.usda at startup so the viewport renders via real
    # OvRTX (Victor's Step 13 directive: "Use real current OvRTX
    # rendering with USD open" -- the file-copy proof is in the content
    # browser pane, but the rest of the screenshot must show real OvRTX
    # rather than the MockRendererAdapter empty-state scene).
    app._startup_usd_path = USD_PATH
    task = asyncio.ensure_future(app.run_async())

    # Drive enough frames for the dock layout, content browser, and
    # default home navigation to settle.
    await _drive(60)

    # Navigate the content browser to the test fixture directory using
    # the widget's documented public API (FileBrowserWidget.navigate_to).
    # This is equivalent to the user typing the path into the breadcrumb
    # bar -- it is NOT setting copy/selection state, only changing which
    # folder the browser displays.
    cb = app._content_window
    widget = cb._widget
    widget.navigate_to(f"file://{TEST_ROOT}")
    await _drive(20)

    _shot("01_baseline_two_files_visible")

    # ---- Inject Ctrl-down via the production callback path -----------
    # Workaround for ovui standalone limitation: _inject_key_event does
    # not propagate to focused-panel key_pressed_fn callbacks (probed
    # at /tmp/_probe_ctrl_inject.py). Calling Application._on_key_pressed
    # directly with the same (key, modifiers, pressed) arguments ovui
    # would forward enters the production chain at the same place real
    # user input does:
    #   Application._on_key_pressed
    #     -> Application.forward_modifier_bits (Step 10 wiring)
    #     -> ContentBrowserWindow.forward_modifier_bits
    #     -> FileBrowserWidget.set_modifier_bits
    #
    # The downstream chain (drag dispatch -> _is_ctrl_drop ->
    # model.drop(is_copy=True)) executes as production. Only the
    # input-pump-to-callback hop is short-circuited.
    app._on_key_pressed(GLFW_KEY_LEFT_CONTROL, MOD_CTRL, True)
    await _drive(2)
    print(f"[qa6] after Ctrl-down: app._last_modifier_bits="
          f"{app._last_modifier_bits} (expect 2)")
    print(f"[qa6] widget._modifier_bits={widget._modifier_bits} "
          f"(expect 2)")

    # ---- Real mouse_drag from src.txt row to target_dir row ----------
    await uitesting.mouse_drag(
        COORD_SRC_FILE_ROW[0], COORD_SRC_FILE_ROW[1],
        COORD_TARGET_DIR_ROW[0], COORD_TARGET_DIR_ROW[1],
        steps=20,
    )
    await _drive(60)  # let the drop's batched copy + UI refresh land

    # ---- Inject Ctrl-up (mirrors what _on_key_pressed does on key
    # release in production: clears the modifier bits in the chain) -----
    app._on_key_pressed(GLFW_KEY_LEFT_CONTROL, 0, False)
    await _drive(5)

    _shot("02_after_drag")

    # ---- Navigate into target_dir to visually confirm the copy --------
    widget.navigate_to(f"file://{TARGET_DIR}")
    await _drive(15)
    _shot("03_inside_target_dir")

    # ---- Filesystem assertion (proves copy semantics, not just a UI
    # render) -----------------------------------------------------------
    src_exists = os.path.isfile(SRC_FILE)
    copied_exists = os.path.isfile(COPIED_FILE)
    print(f"[qa6] src exists ({SRC_FILE}): {src_exists}")
    print(f"[qa6] copied exists ({COPIED_FILE}): {copied_exists}")
    if not (src_exists and copied_exists):
        print("[qa6] FAIL: Ctrl+drag did not produce a copy. "
              "Either drag didn't reach the drop target or "
              "is_copy resolved False.")
        rc = 1
    else:
        print("[qa6] PASS: src remains AND copy exists at target -- "
              "Ctrl+drag-copy semantics confirmed end-to-end.")
        rc = 0

    app._running = False
    try:
        await asyncio.wait_for(task, timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()
    sys.exit(rc)


if __name__ == "__main__":
    _setup_test_files()

    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init("OvGear Step 13 QA #6 (Ctrl+drag copy)", width=1280, height=720)
    apply_global_styles()
    ui.run(_main())
