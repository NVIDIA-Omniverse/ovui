# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Testing utilities for ovui - programmatic input injection.

Provides high-level async helpers that handle the multi-frame dance required
by ImGui for hover->click transitions, text input focus, etc.

Usage::

    from omni.ui.testing import mouse_click, type_text, capture_screenshot

    async def my_test():
        await mouse_click(200, 80)
        await type_text("Hello!")
        capture_screenshot("/tmp/result.png")
"""

from __future__ import annotations

import asyncio
from . import _ui
from .standalone import _tick_one_frame


async def next_frame() -> None:
    """Tick one frame and yield.

    ``ui.testing`` is used from tests and ad-hoc scripts that drive frames
    manually (no ``standalone.run()`` loop). ``standalone.next_frame()`` in
    that bare mode deadlocks because nothing pumps the futures it awaits,
    so we tick explicitly here instead.
    """
    _tick_one_frame()
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Mouse helpers
# ---------------------------------------------------------------------------

async def mouse_click(x: float, y: float, button: int = 0) -> None:
    """Click at position (*x*, *y*).

    Handles the multi-frame hover -> press -> release sequence that ImGui
    requires in order to properly register widget interactions (hover state
    must be established before a click is recognised).
    """
    _ui._inject_mouse_move(x, y)
    await next_frame()
    await next_frame()  # Let ImGui register hover
    _ui._inject_mouse_button(button, True)
    await next_frame()
    _ui._inject_mouse_button(button, False)
    await next_frame()
    await next_frame()  # Let ImGui process the full click


async def mouse_double_click(x: float, y: float, button: int = 0) -> None:
    """Double-click at position (*x*, *y*)."""
    await mouse_click(x, y, button)
    # ImGui detects double-click from timing; the second click must happen
    # within io.MouseDoubleClickTime (default 0.3 s) -- at typical frame
    # rates a single-frame gap is well within that window.
    _ui._inject_mouse_button(button, True)
    await next_frame()
    _ui._inject_mouse_button(button, False)
    await next_frame()
    await next_frame()


async def mouse_move(x: float, y: float) -> None:
    """Move the injected mouse cursor to (*x*, *y*)."""
    _ui._inject_mouse_move(x, y)
    await next_frame()


async def mouse_drag(
    x0: float, y0: float, x1: float, y1: float,
    button: int = 0, steps: int = 10,
) -> None:
    """Drag from (*x0*, *y0*) to (*x1*, *y1*) over *steps* intermediate frames."""
    _ui._inject_mouse_move(x0, y0)
    await next_frame()
    await next_frame()
    _ui._inject_mouse_button(button, True)
    await next_frame()

    for i in range(1, steps + 1):
        t = i / steps
        _ui._inject_mouse_move(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)
        await next_frame()

    _ui._inject_mouse_button(button, False)
    await next_frame()
    await next_frame()


async def mouse_scroll(x: float, y: float, dx: float = 0, dy: float = 0) -> None:
    """Scroll at position (*x*, *y*).

    Moves the cursor to the target position first, waits for ImGui to
    register the hover, then injects a scroll event.
    """
    _ui._inject_mouse_move(x, y)
    await next_frame()
    await next_frame()  # Let ImGui register hover
    _ui._inject_mouse_scroll(dx, dy)
    await next_frame()


# ---------------------------------------------------------------------------
# Keyboard / text helpers
# ---------------------------------------------------------------------------

async def type_text(text: str) -> None:
    """Type *text* into the currently focused widget.

    Two frames are allowed so that ImGui has time to process the input
    characters and update the widget model.
    """
    _ui._inject_text_input(text)
    await next_frame()
    await next_frame()


async def press_key(key_code: int) -> None:
    """Press and release a key identified by its ImGui key code."""
    _ui._inject_key_event(key_code, True)
    await next_frame()
    _ui._inject_key_event(key_code, False)
    await next_frame()


def get_clipboard_text() -> str:
    """Return the current standalone clipboard text."""
    return _ui._get_clipboard_text()


def set_clipboard_text(text: str) -> None:
    """Set the standalone clipboard text."""
    _ui._set_clipboard_text(text)


# ---------------------------------------------------------------------------
# Frame / timing helpers
# ---------------------------------------------------------------------------

async def wait_frames(n: int = 1) -> None:
    """Wait for *n* frames to elapse."""
    for _ in range(n):
        await next_frame()


# ---------------------------------------------------------------------------
# Screenshot capture
# ---------------------------------------------------------------------------

def capture_screenshot(filepath: str) -> bool:
    """Capture the current framebuffer to an image file.

    Supported formats (chosen by file extension): ``.png``, ``.jpg``/``.jpeg``,
    ``.bmp``.  Returns ``True`` on success.

    .. note::

       This is a synchronous convenience wrapper. It schedules a pre-swap
       capture so that the screenshot is taken from the fully-rendered back
       buffer (before ``glfwSwapBuffers``). Internally it ticks one extra
       frame so the caller does **not** need to ``await next_frame()``
       afterwards.
    """
    # Try the scheduled (pre-swap) path first for reliable captures.
    try:
        if _ui._schedule_screenshot(filepath):
            # We need to tick one frame so the pre-swap callback fires.
            from .standalone import _tick_one_frame, _pump_asyncio
            import asyncio
            _tick_one_frame()
            # Pump asyncio so next_frame futures resolve
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon(loop.stop)
                loop.run_forever()
            except RuntimeError:
                pass
            return _ui._poll_screenshot_done()
    except AttributeError:
        pass
    # Fallback to direct capture (may return blank due to buffer timing)
    return _ui._capture_screenshot(filepath)
