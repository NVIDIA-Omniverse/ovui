# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Delete/Backspace in a Property Inspector text field, dropdown or checkbox keeps the prim.

Issue 498: with ``/World/Cube`` selected, a click in a text field (Display
Color, Extent), in a dropdown (Purpose) or on a checkbox (Double Sided) of the
Property Inspector, then Backspace or Delete, deleted the cube. None of these
fields is an editing text input, so the text-input check of the delete
shortcut did not stop the delete.

The installed windowed USD Viewer (real ovrtx renderer, OpenUSD provider) is
driven only with injected mouse and keyboard input through the ovui inspector:

1. Click the cube in the viewport.
2. For each field, with Backspace and with Delete: click the field and press
   the key. ``/World/Cube`` must still exist. Escape then closes the list of
   the dropdown.
3. Intentional deletion still works after the Property Inspector had focus:
   select the cube in the Stage Browser and press Delete (the cube is
   removed), Ctrl+Z (it comes back), then select it in the viewport and press
   Backspace (it is removed).

The test checks ``/World/Cube`` in the app state after every click and key.
The test takes no screenshot: a reference image of this flow would only test
how the app looks, not what the keys do. The session is made with
``capture_frames=False``, so the frame-loop warm-up and the click pumps ask for
the app state instead of a screenshot.
"""

from __future__ import annotations

import importlib.util
import os
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
driver = _load_by_path("ovui_e2e_driver_property_field_keys", _HERE / "driver.py")
pytestmark = pytest.mark.requires_ovrtx

CUBE = driver.SELECTED_PRIM
# The attribute and the widget type of its field. The two text fields are
# read-only array fields; the dropdown and the checkbox take no text.
FIELDS = (
    ("primvars:displayColor", "StringField"),
    ("extent", "StringField"),
    ("purpose", "ComboBox"),
    ("doubleSided", "CheckBox"),
)
# A key acts on the frame loop; wait this long before a check that a key
# deleted nothing.
SETTLE = 0.5


def _require_renderer_and_display() -> None:
    """Skip only when this host has no ovrtx-capable NVIDIA GPU; else run or fail.

    A missing display is not missing hardware: on a host with the GPU and the
    renderer, a missing ``DISPLAY`` fails the test and names the cause.
    """
    require_render = os.environ.get("OVUI_E2E_REQUIRE_RENDER", "").strip() == "1"
    gpu_present, gpu_detail = driver.nvidia_gpu_present()
    ovrtx_ok, ovrtx_detail = driver.ovrtx_device_available()
    if not ovrtx_ok:
        detail = f"nvidia-smi: {gpu_detail}. ovrtx probe: {ovrtx_detail}"
        if require_render or gpu_present:
            pytest.fail(f"The ovrtx renderer could not run. {detail}")
        pytest.skip(f"No ovrtx-capable NVIDIA GPU on this host. {detail}")
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        pytest.fail("This host has an ovrtx-capable NVIDIA GPU, but DISPLAY is not "
                    "set: the windowed app needs an X display (CI runs Xvfb).")


class _Flow:
    def __init__(self, session):
        self.session = session

    def state(self) -> dict:
        return self.session.state()

    def stage_paths(self) -> list:
        usd = self.state().get("usd") or {}
        assert "paths" in usd, (
            f"the app state has no stage paths\n--- app log ---\n{self.session.log_tail()}"
        )
        return usd["paths"]

    def assert_cube_kept(self, where: str) -> None:
        """Check that ``/World/Cube`` still exists, after ``SETTLE`` so that a late delete is seen."""
        time.sleep(SETTLE)
        paths = self.stage_paths()
        assert CUBE in paths, (
            f"{CUBE} missing {where}; stage paths: {paths}\n"
            f"--- app log ---\n{self.session.log_tail()}"
        )

    def wait_cube(self, exists: bool, where: str, timeout: float = 20.0) -> None:
        """Wait until ``/World/Cube`` exists (``exists``) or is gone."""
        deadline = time.monotonic() + timeout
        paths = self.stage_paths()
        while (CUBE in paths) is not exists and time.monotonic() < deadline:
            time.sleep(0.5)
            paths = self.stage_paths()
        assert (CUBE in paths) is exists, (
            f"{CUBE} {'missing' if exists else 'still present'} {where}; "
            f"stage paths: {paths}\n--- app log ---\n{self.session.log_tail()}"
        )

    def field_point(self, attr: str, widget_type: str, timeout: float = 60.0) -> list:
        """Return the centre of the field of ``attr`` inside the visible panel."""
        deadline = time.monotonic() + timeout
        while True:
            property_ui = self.state().get("property_ui") or {}
            row = (property_ui.get("rows") or {}).get(attr)
            if row and row.get("field_points"):
                break
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"Property Inspector has no '{attr}' row: {sorted(property_ui.get('rows') or {})}"
                )
            time.sleep(1.0)
        assert row["field_widget_types"] == [widget_type], (attr, row)
        x, y = row["field_points"][0]
        panel = property_ui.get("scroll_rect") or {}
        assert panel.get("y", 0) <= y < panel.get("y", 0) + panel.get("height", 0), (
            f"the '{attr}' field at ({x}, {y}) is outside the visible panel {panel}"
        )
        return [x, y]

    def key_in_field(self, attr: str, widget_type: str, key: str) -> None:
        x, y = self.field_point(attr, widget_type)
        self.session.click(x, y)
        self.assert_cube_kept(f"after the click on the '{attr}' field")
        self.session.press(key)
        self.assert_cube_kept(f"after {key} in the '{attr}' field")
        if widget_type == "ComboBox":
            self.session.press("Escape")


# The CI window jobs select tests with ``-k <provider>``; the fault is in the
# app's key dispatch, not in a data provider, so one provider is enough.
@pytest.mark.parametrize("provider", ["openusd"])
def test_property_field_delete_keys_keep_prim_and_shortcut_still_deletes(provider, tmp_path):
    _require_renderer_and_display()
    driver.assert_installed_provenance(driver.PRODUCT_MODULES)

    session = driver.FullAppSession(
        workdir=tmp_path, log_path=tmp_path / "app.log", provider=provider,
        headless=False, capture_frames=False,
    )
    session.start()
    try:
        flow = _Flow(session)
        session.wait_ready(timeout=180)
        assert session.state().get("provider") == provider
        driver._click_cube(session)

        for attr, widget_type in FIELDS:
            for key in ("Backspace", "Delete"):
                flow.key_in_field(attr, widget_type, key)

        # Intentional deletion still works after the Property Inspector had
        # the keyboard focus.
        rows = flow.state()["stage_ui"]["rows"]
        cube_row = next(r for r in rows if r["path"] == CUBE)
        session.click(*cube_row["select_point"])
        session.press("Delete")
        flow.wait_cube(False, "after Delete with the cube selected in the Stage Browser")
        session.press("z", modifiers="ctrl")
        flow.wait_cube(True, "after Ctrl+Z")
        driver._click_cube(session)
        session.press("Backspace")
        flow.wait_cube(False, "after Backspace with the cube selected in the viewport")
    finally:
        session.stop()
