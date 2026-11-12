# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Backspace and Delete in the Property Inspector filter must not delete the prim.

Issue 203: with a prim selected, the user clicks the "Filter properties..."
field, types a character and presses Backspace. The filter used to rebuild
itself after the first character, lost the keyboard focus, and the key went to
the app-wide delete shortcut. The selected prim was deleted.

The installed windowed USD Viewer (real ovrtx renderer, OpenUSD provider) is
driven only with injected mouse and keyboard input through the ovui inspector:

1. Click the cube in the viewport.
2. Click the filter field and type "a", wait, type "b", wait, type "c". The
   filter must hold "abc".
3. Press Backspace. The filter must hold "ab". Press Home and Delete. The
   filter must hold "b". After every key press ``/World/Cube`` must exist.
4. Intentional deletion still works: with focus outside the filter, select the
   cube in the Stage Browser and press Delete. The cube is removed.

The test checks the filter text and the prim in the app state after every key.
The test takes no screenshot: a reference image of this flow would only test
how the app looks, not what the keys do. The session is made with
``capture_frames=False``, so the frame-loop warm-up and the click pumps ask for
the app state instead of a screenshot.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HERE = Path(__file__).resolve().parent
driver = _load_by_path("ovui_e2e_driver_property_filter_keys", _HERE / "driver.py")
field_delete = _load_by_path(
    "ovui_e2e_field_delete_helpers", _HERE / "test_wheel_app_field_delete_e2e.py"
)
pytestmark = pytest.mark.requires_ovrtx

CUBE = driver.SELECTED_PRIM


class _Flow(field_delete._Flow):
    def filter_state(self) -> dict:
        return self.state()["property_ui"]

    def wait_filter_text(self, expected: str, where: str, timeout: float = 20.0) -> None:
        """Wait until the filter holds ``expected``; the filter applies after a short delay."""
        deadline = time.monotonic() + timeout
        while True:
            actual = self.filter_state()["filter_text"]
            if actual == expected:
                return
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"{where}: the filter holds {actual!r}, expected {expected!r}; "
                    f"stage paths: {(self.state().get('usd') or {}).get('paths')}\n"
                    f"--- app log ---\n{self.session.log_tail()}"
                )
            time.sleep(0.5)

    def settle(self) -> None:
        # The filter applies its text after a short delay, then rebuilds the
        # rows below it. Wait longer than that delay.
        time.sleep(1.0)

    def press_in_filter(self, key: str, expected_text: str) -> None:
        self.session.press(key)
        self.settle()
        self.assert_cube(True, f"after {key} in the Property Inspector filter")
        self.wait_filter_text(expected_text, f"after {key}")


@pytest.mark.parametrize("provider", ["openusd"])
def test_property_filter_keys_edit_text_and_keep_prim(provider, tmp_path):
    field_delete._require_renderer_and_display()
    driver.assert_installed_provenance(driver.PRODUCT_MODULES)

    session = driver.FullAppSession(
        workdir=tmp_path, log_path=tmp_path / "app.log", provider=provider,
        headless=False, capture_frames=False,
    )
    session.start()
    try:
        flow = _Flow(session, tmp_path)
        session.wait_ready(timeout=180)
        assert session.state().get("provider") == provider
        driver._click_cube(session)

        rect = flow.filter_state()["filter_rect"]
        session.click(int(rect["x"] + rect["width"] / 2), int(rect["y"] + rect["height"] / 2))

        for char, expected in (("a", "a"), ("b", "ab"), ("c", "abc")):
            session.type_text(char)
            flow.settle()
            flow.wait_filter_text(expected, f"after typing {char!r}")
            flow.assert_cube(True, f"after typing {char!r} in the filter")

        flow.press_in_filter("Backspace", "ab")
        session.press("Home")
        flow.press_in_filter("Delete", "b")

        # Intentional deletion outside the filter still works.
        rows = flow.state()["stage_ui"]["rows"]
        cube_row = next(r for r in rows if r["path"] == CUBE)
        session.click(*cube_row["select_point"])
        session.press("Delete")
        flow.assert_cube(False, "after Delete with the cube selected in the Stage Browser")
    finally:
        session.stop()
