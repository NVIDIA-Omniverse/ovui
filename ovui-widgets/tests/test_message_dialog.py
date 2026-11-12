# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The one-button message dialog works with the keyboard and a long text.

The app shows its "Settings Not Loaded" notice with
``message_dialog``. Its only button is OK, so Enter, keypad Enter and Escape
act as OK, and OK stays visible for any message length. The keys and the
mouse wheel go into ovui's input queue, the same path as a user's input, and
real frames are drawn in headless Vulkan mode.
"""

from __future__ import annotations

import omni.ui as ui
import pytest
from omni.ui import _ui

from ovui_widgets.common import dialogs

# ImGuiKey values, as the ovui input queue takes them.
_IMGUI_KEY_ENTER = 525
_IMGUI_KEY_ESCAPE = 526
_IMGUI_KEY_KEYPAD_ENTER = 627


@pytest.fixture(scope="module")
def frames():
    """One headless ovui start for the module; ``frames()`` draws frames."""
    from omni.ui import standalone

    from tests._vulkan_device import use_headless_vulkan

    patch = pytest.MonkeyPatch()
    use_headless_vulkan(patch)
    # An earlier test can leave the backend running with its own windows.
    standalone.shutdown()
    standalone.init("_test_message_dialog", 1280, 720)

    def tick(count=3):
        for _ in range(count):
            standalone._tick_one_frame()

    yield tick
    dialogs._clear_open_dialogs()
    standalone.shutdown()
    patch.undo()


@pytest.fixture
def show(frames):
    """Open a message dialog with a unique title; return its window."""

    def _show(title: str, message: str) -> ui.Window:
        assert dialogs.message_dialog(title, message) is not None
        frames()
        window = ui.Workspace.get_window(title)
        assert window is not None and window.visible
        return window

    yield _show
    dialogs._clear_open_dialogs()
    frames()


def _find(widget, kind):
    """The first widget of type ``kind`` in ``widget`` (depth first)."""
    if isinstance(widget, kind):
        return widget
    for child in ui.Inspector.get_children(widget):
        found = _find(child, kind)
        if found is not None:
            return found
    return None


def _bottom(widget) -> float:
    return widget.screen_position_y + widget.computed_height


@pytest.mark.parametrize(
    "key",
    [_IMGUI_KEY_ENTER, _IMGUI_KEY_KEYPAD_ENTER, _IMGUI_KEY_ESCAPE],
    ids=["enter", "keypad-enter", "escape"],
)
def test_a_key_closes_the_dialog_like_ok(show, frames, key) -> None:
    window = show(f"Settings Not Loaded {key}", "It uses the default settings.")

    _ui._inject_key_event(key, True)
    frames(1)
    _ui._inject_key_event(key, False)
    frames(2)

    assert not window.visible


def test_ok_stays_visible_and_the_wheel_scrolls_a_long_text(show, frames) -> None:
    # The owner's case: a home folder of five folders of 50 characters, named
    # twice in the text, because the copy next to the settings file failed.
    home = "/tmp/" + "/".join(letter * 50 for letter in "abcde")
    message = "\n".join(
        [
            "The app could not load the settings file. "
            "It uses the default settings.",
            f"File: {home}/.ovgear/settings.json",
            "Cause: Unterminated string starting at: line 31 column 5 (char 1099)",
            "The app could not keep a copy of the damaged file (PermissionError: "
            f"[Errno 13] Permission denied: '{home}/.ovgear/settings.damaged.json').",
            "The app does not save the settings at exit, so the damaged file "
            "stays as it is.",
        ]
    )
    window = show("Settings Not Loaded long", message)
    ok = _find(window.frame, ui.Button)
    text = _find(window.frame, ui.Label)
    window_bottom = window.position_y + window.height
    assert _bottom(text) > window_bottom, "the text must be longer than the dialog"
    assert _bottom(ok) <= window_bottom, "OK is outside the dialog"

    text_top = text.screen_position_y
    _ui._inject_mouse_move(text.screen_position_x + 40, text_top + 40)
    frames(2)
    _ui._inject_mouse_scroll(0.0, -5.0)  # the wheel down, as ovui-inspect sends it
    frames(3)

    assert text.screen_position_y < text_top, "the wheel did not scroll the text"
    assert _bottom(ok) <= window_bottom, "OK left the dialog after the scroll"


def test_the_full_text_reaches_stderr_when_the_window_cannot_be_built(
    monkeypatch, capsys
) -> None:
    from ovui_widgets.common.error_reporter import ErrorReporter

    def _no_window(**_kwargs):
        raise RuntimeError("no window")

    monkeypatch.setattr(dialogs, "_MessageDialog", _no_window)
    # The status bar itself (one line, at most 160 characters) has its own
    # tests in test_error_reporter.py; here only its input is recorded.
    shown = []
    monkeypatch.setattr(
        ErrorReporter,
        "show_warning",
        lambda message, duration_ms=4000: shown.append((message, duration_ms)),
    )
    message = "The app could not load the settings file. " + "x" * 300 + " END"

    assert dialogs.message_dialog("Settings Not Loaded", message) is None

    assert message in capsys.readouterr().err
    # The status bar gets the text and keeps it until the next message.
    assert shown == [(message, 0)]
