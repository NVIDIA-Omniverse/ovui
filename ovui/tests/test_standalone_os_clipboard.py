# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The standalone clipboard helpers must write to the OS clipboard.

An in-process read-back cannot show this: a private string returns the text
that was just set. The test reads the OS clipboard with a separate process
(``xsel``), so it runs on X11 with a GLFW window. It skips only when the
computer has no X11 display or no GLFW window. A missing ``xsel`` is a fault of
the test setup, so it fails and names the cause.

A headless run has no window, so it must keep a clipboard inside the process
and never touch the OS clipboard. ``TestClipboardIsolation`` checks this on
every platform, headless or windowed, and needs no separate reader.
"""

import os
import shutil
import subprocess
import sys
import time
import unittest

import pytest

from omni.ui import _ui, standalone

_HEADLESS = os.environ.get("OMNIUI_HEADLESS", "").lower() in ("1", "true")
_X11 = sys.platform.startswith("linux") and bool(os.environ.get("DISPLAY")) and not os.environ.get("WAYLAND_DISPLAY")


def _xsel_path() -> str:
    """Return the path of ``xsel``; fail with the cause when it is missing."""
    path = shutil.which("xsel")
    if path is None:
        raise AssertionError(
            "xsel is not installed, so the test cannot read the OS clipboard in a separate process. "
            "Install it (for example: apt-get install xsel)."
        )
    return path


def _read_os_clipboard() -> str:
    """Read the X11 clipboard in another process while the app keeps ticking.

    GLFW answers the selection request only when the app handles events.
    """
    proc = subprocess.Popen([_xsel_path(), "-b", "-o"], stdout=subprocess.PIPE, text=True)
    deadline = time.time() + 10
    while proc.poll() is None and time.time() < deadline:
        standalone._tick_one_frame()
        time.sleep(0.02)
    if proc.poll() is None:
        proc.kill()
        proc.wait()
        raise TimeoutError("xsel did not read the clipboard")
    return proc.stdout.read()


@pytest.mark.requires_glfw
@unittest.skipIf(_HEADLESS, "needs a GLFW window; headless has no OS clipboard")
@unittest.skipUnless(_X11, "needs an X11 display (Linux, DISPLAY set, no Wayland)")
class TestStandaloneOsClipboard(unittest.TestCase):
    def setUp(self):
        _xsel_path()
        standalone.init(width=320, height=240)
        for _ in range(3):
            standalone._tick_one_frame()

    def test_set_clipboard_text_reaches_os_clipboard(self):
        subprocess.run([_xsel_path(), "-b", "-i"], input="SENTINEL", text=True, check=True, timeout=5)
        self.assertEqual(_read_os_clipboard(), "SENTINEL")

        _ui._set_clipboard_text("hello from ovui")

        self.assertEqual(_ui._get_clipboard_text(), "hello from ovui")
        self.assertEqual(_read_os_clipboard(), "hello from ovui")

    def test_get_clipboard_text_reads_os_clipboard(self):
        _ui._set_clipboard_text("inside")
        subprocess.run([_xsel_path(), "-b", "-i"], input="outside", text=True, check=True, timeout=5)
        for _ in range(3):
            standalone._tick_one_frame()

        self.assertEqual(_ui._get_clipboard_text(), "outside")


_NO_DISPLAY = sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and not _HEADLESS


@unittest.skipIf(_NO_DISPLAY, "needs a display for the GLFW window (Linux, DISPLAY not set)")
class TestClipboardIsolation(unittest.TestCase):
    """The helpers use the OS clipboard in a window and a private one when headless."""

    def setUp(self):
        standalone.init(width=320, height=240)
        for _ in range(3):
            standalone._tick_one_frame()

    def test_clipboard_is_private_only_when_headless(self):
        self.assertEqual(
            _ui._is_clipboard_process_private(),
            _HEADLESS,
            "headless runs must keep the clipboard inside the process; windows must use the OS clipboard",
        )
