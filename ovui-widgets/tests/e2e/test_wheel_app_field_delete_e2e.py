# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Delete/Backspace in a Property Inspector number field must not delete the prim.

Regression: with a prim selected, a double-click on a float or int field in
the Property Inspector puts the field in keyboard-edit mode. Delete and
Backspace then edited the field text and also ran the app-wide delete
shortcut, which removed the selected prim.

The installed windowed USD Viewer (real ovrtx renderer, OpenUSD provider) is
driven only with injected mouse and keyboard input through the ovui inspector:

1. Click the cube in the viewport.
2. For a float field (``size``) and an int field (``segmentCount``, a custom
   attribute in a copy of the test scene), with Backspace and with Delete:
   double-click the field, move the cursor (End or Home), press the key until
   the text is empty, type a new value and press Enter. After every key press
   ``/World/Cube`` must still exist; after Enter the attribute must hold the
   typed value.
3. Intentional deletion still works: select the cube in the Stage Browser and
   press Delete (the cube is removed), Ctrl+Z (it comes back), then select it
   in the viewport and press Backspace (it is removed).

Screenshots of every step are written to the test directory.
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
driver = _load_by_path("ovui_e2e_driver_field_delete", _HERE / "driver.py")
pytestmark = pytest.mark.requires_ovrtx

CUBE = driver.SELECTED_PRIM
INT_ATTR = "segmentCount"
FLOAT_ATTR = "size"

# Read-only probe: True/False while a text input owns the keyboard; None when
# the installed ovui has no such query (then the edit-mode precondition is
# checked only by the edited value).
_TEXT_INPUT_PROBE = (
    "result = (lambda f: None if f is None else bool(f()))("
    "getattr(__import__('omni.ui.standalone', fromlist=['_']), "
    "'is_text_input_active', None))"
)


def _require_renderer_and_display() -> None:
    """Skip only when this host honestly cannot run the app; else fail."""
    require_render = os.environ.get("OVUI_E2E_REQUIRE_RENDER", "").strip() == "1"
    gpu_present, gpu_detail = driver.nvidia_gpu_present()
    ovrtx_ok, ovrtx_detail = driver.ovrtx_device_available()
    if not ovrtx_ok:
        detail = f"nvidia-smi: {gpu_detail}. ovrtx probe: {ovrtx_detail}"
        if require_render or gpu_present:
            pytest.fail(f"The ovrtx renderer could not run. {detail}")
        pytest.skip(f"No ovrtx-capable NVIDIA GPU on this host. {detail}")
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        if require_render:
            pytest.fail("OVUI_E2E_REQUIRE_RENDER=1 but DISPLAY is not set; the "
                        "windowed app needs an X display (for example, Xvfb).")
        pytest.skip("No X display (DISPLAY unset) for the windowed app.")


def _scene_with_int_attribute(workdir: Path) -> Path:
    """Copy the test scene and give the cube an int attribute."""
    text = driver.scene_path().read_text()
    anchor = "        double size = 2.0\n"
    assert anchor in text, "simple_scene.usda changed; update the int-attribute anchor"
    text = text.replace(anchor, anchor + f"        custom int {INT_ATTR} = 42\n", 1)
    scene = workdir / "int_float_scene.usda"
    scene.write_text(text)
    return scene


class _Flow:
    def __init__(self, session, workdir: Path):
        self.session = session
        self.workdir = workdir
        self.step = 0

    def shot(self, name: str) -> None:
        self.step += 1
        self.session.screenshot(self.workdir / f"{self.step:02d}_{name}.png")

    def state(self) -> dict:
        return self.session.state()

    def prim_exists(self, state: dict) -> bool:
        return CUBE in (state.get("usd") or {}).get("paths", [])

    def assert_cube(self, exists: bool, where: str) -> dict:
        state = self.state()
        assert self.prim_exists(state) is exists, (
            f"{CUBE} {'missing' if exists else 'still present'} {where}; "
            f"stage paths: {(state.get('usd') or {}).get('paths')}\n"
            f"--- app log ---\n{self.session.log_tail()}"
        )
        return state

    def property_row(self, attr: str, timeout: float = 60.0) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            rows = (self.state().get("property_ui") or {}).get("rows") or {}
            row = rows.get(attr)
            if row and row.get("field_points"):
                return row
            if time.monotonic() > deadline:
                raise AssertionError(f"Property Inspector has no '{attr}' row: {sorted(rows)}")
            time.sleep(1.0)

    def begin_field_edit(self, attr: str, label: str) -> None:
        """Double-click the field until it is in keyboard-edit mode."""
        for attempt in range(3):
            x, y = self.property_row(attr)["field_points"][0]
            self.session.click(x, y, double=True)
            self.shot(f"{label}_double_click_{attr}")
            editing = self.session.execute(_TEXT_INPUT_PROBE)
            if editing is None or editing:
                return
            self.session.press("Escape")
        raise AssertionError(f"'{attr}' field did not enter keyboard-edit mode")

    def edit_with_key(self, attr: str, label: str, move_key: str, edit_key: str,
                      presses: int, typed: str) -> None:
        self.begin_field_edit(attr, label)
        self.session.press(move_key)
        for i in range(presses):
            self.session.press(edit_key)
            self.shot(f"{label}_{edit_key.lower()}_{i + 1}")
            self.assert_cube(True, f"after {edit_key} #{i + 1} in the '{attr}' field")
        self.session.type_text(typed)
        self.session.press("Enter")
        self.shot(f"{label}_typed_{typed}_enter")
        state = self.assert_cube(True, f"after committing '{typed}' in '{attr}'")
        value = state["property_ui"]["rows"][attr]["value"]
        assert float(value) == float(typed), (
            f"'{attr}' holds {value!r} after '{typed}' + Enter; the field did not "
            f"receive {edit_key} (or the typed text)"
        )


# Provider-specific runs may select tests with ``-k <provider>``; the fault is in the
# app's key dispatch, not in a data provider, so one provider is enough.
@pytest.mark.parametrize("provider", ["openusd"])
def test_field_delete_keys_keep_prim_and_shortcut_still_deletes(provider, tmp_path):
    _require_renderer_and_display()
    driver.assert_installed_provenance(driver.PRODUCT_MODULES)

    scene = _scene_with_int_attribute(tmp_path)
    session = driver.FullAppSession(
        workdir=tmp_path, log_path=tmp_path / "app.log", provider=provider,
        headless=False, scene=scene,
    )
    session.start()
    try:
        flow = _Flow(session, tmp_path)
        driver._start_and_check(session, tmp_path / "00_start.png")
        driver._click_cube(session)
        flow.shot("cube_selected")
        row = flow.property_row(INT_ATTR)
        assert row["field_widget_types"] == ["IntDrag"], row
        row = flow.property_row(FLOAT_ATTR)
        assert row["field_widget_types"] == ["FloatDrag"], row

        # Each press removes at least one character, so ``presses`` empties
        # the field ("2.0", "5.0", "42", "8"); one extra press hits an empty
        # field, which must also leave the prim alone.
        flow.edit_with_key(FLOAT_ATTR, "float_backspace", "End", "Backspace", 4, "5")
        flow.edit_with_key(FLOAT_ATTR, "float_delete", "Home", "Delete", 4, "7")
        flow.edit_with_key(INT_ATTR, "int_backspace", "End", "Backspace", 3, "8")
        flow.edit_with_key(INT_ATTR, "int_delete", "Home", "Delete", 2, "9")

        # Intentional deletion outside a field still works.
        rows = flow.state()["stage_ui"]["rows"]
        cube_row = next(r for r in rows if r["path"] == CUBE)
        session.click(*cube_row["select_point"])
        flow.shot("stage_browser_cube_selected")
        session.press("Delete")
        flow.shot("stage_browser_delete")
        flow.assert_cube(False, "after Delete with the cube selected in the Stage Browser")
        session.press("z", modifiers="ctrl")
        flow.shot("undo")
        flow.assert_cube(True, "after Ctrl+Z")
        driver._click_cube(session)
        flow.shot("viewport_cube_selected")
        session.press("Backspace")
        flow.shot("viewport_backspace")
        flow.assert_cube(False, "after Backspace with the cube selected in the viewport")
    finally:
        session.stop()
