# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Backspace and Delete with the Property Inspector focused must not delete the prim.

OMPE-118431 (issue 508): with a prim selected, a click on empty Property
Inspector space or on the read-only Proxy Prim field gave the panel the
keyboard focus while no text input was active. Backspace and Delete then ran
the app-wide delete shortcut: the selected prim was removed and the undo stack
had one more step, labelled "Delete". The Proxy Prim field also showed a text
cursor but took no typed text.

The installed windowed USD Viewer (real ovrtx renderer) is driven only with
injected mouse and keyboard input through the ovui inspector, once per data
provider:

1. Click the cube in the viewport.
2. Click empty Property Inspector space below the last attribute row and press
   Delete, then Backspace. After each key ``/World/Cube`` must exist and the
   undo stack must not grow.
3. Each relationship field (Proxy Prim with OpenUSD, Material Binding with
   OVStage) is read-only and must be disabled, so a click shows no text
   cursor. Click it and press Backspace, click it again and press Delete: the
   cube must exist and the undo stack must not grow.
4. Intentional deletion still works: select the cube in the Stage Browser and
   press Delete (one undo step, labelled "Delete"), Ctrl+Z (it comes back),
   then select it in the viewport and press Backspace (it is removed).

The test checks the app state after every key. It takes no screenshot: a
reference image of this flow would only test how the app looks, not what the
keys do.
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
driver = _load_by_path("ovui_e2e_driver_property_panel_keys", _HERE / "driver.py")
field_delete = _load_by_path(
    "ovui_e2e_field_delete_helpers_panel_keys", _HERE / "test_wheel_app_field_delete_e2e.py"
)
pytestmark = pytest.mark.requires_ovrtx

CUBE = driver.SELECTED_PRIM


class _Flow(field_delete._Flow):
    def prim_exists(self, state: dict) -> bool:
        # The stage adapter tree is the same for the openusd and the ovstage
        # provider; the ``usd`` snapshot is empty with ovstage.
        return CUBE in (state.get("adapter") or {}).get("paths", [])

    def assert_cube(self, exists: bool, where: str) -> dict:
        state = self.state()
        assert self.prim_exists(state) is exists, (
            f"{CUBE} {'missing' if exists else 'still present'} {where}; "
            f"stage paths: {(state.get('adapter') or {}).get('paths')}\n"
            f"--- app log ---\n{self.session.log_tail()}"
        )
        return state

    def undo_depth(self) -> int:
        return int(self.state()["undo"]["undo_depth"])

    def settle(self) -> None:
        # Let the key reach the app and a stage change, if any, reach the tree.
        time.sleep(1.0)

    def press_keeps_cube(self, key: str, undo_depth: int, where: str) -> None:
        self.session.press(key)
        self.settle()
        state = self.assert_cube(True, f"after {key} {where}")
        undo = state["undo"]
        assert undo["undo_depth"] == undo_depth, (
            f"{key} {where} added an undo step: depth {undo['undo_depth']} "
            f"(was {undo_depth}), label {undo['undo_label']!r}"
        )

    def empty_panel_point(self) -> tuple:
        """A point in the Property Inspector below the last attribute row."""
        panel = self.state()["property_ui"]
        area = panel["scroll_rect"]
        assert area, f"Property Inspector has no scroll area: {panel}"
        rows_bottom = max(
            rect["y"] + rect["height"]
            for row in panel["rows"].values()
            for rect in row["field_rects"]
            if rect is not None
        )
        area_bottom = area["y"] + area["height"]
        assert area_bottom - rows_bottom > 20, (
            f"no empty Property Inspector space below the rows: rows end at "
            f"{rows_bottom}, the panel ends at {area_bottom}"
        )
        return (
            int(area["x"] + area["width"] * 0.5),
            int((rows_bottom + area_bottom) * 0.5),
        )

    def relationship_rows(self) -> dict:
        self.property_row("visibility")  # wait for the rows of the cube
        rows = self.state()["property_ui"]["rows"]
        return {
            name: row for name, row in rows.items()
            if row["type_name"] == "relationship" and row["field_points"]
        }


@pytest.mark.parametrize("provider", ["openusd", "ovstage"])
def test_property_panel_keys_keep_prim_and_shortcut_still_deletes(provider, tmp_path):
    field_delete._require_renderer_and_display()
    modules = driver.OVSTAGE_PRODUCT_MODULES if provider == "ovstage" else driver.PRODUCT_MODULES
    driver.assert_installed_provenance(modules)

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
        undo_depth = flow.undo_depth()

        # Empty Property Inspector space.
        session.click(*flow.empty_panel_point())
        flow.settle()
        flow.press_keeps_cube("Delete", undo_depth, "in empty Property Inspector space")
        flow.press_keeps_cube("Backspace", undo_depth, "in empty Property Inspector space")

        # Read-only relationship fields.
        relationships = flow.relationship_rows()
        if provider == "openusd":
            assert "proxyPrim" in relationships, sorted(relationships)
        assert relationships, "the cube shows no relationship row"
        for name, row in relationships.items():
            assert row["field_enabled"] == [False], (
                f"read-only relationship field {name!r} is enabled: a click shows "
                f"a text cursor that takes no text"
            )
            session.click(*row["field_points"][0])
            flow.press_keeps_cube("Backspace", undo_depth, f"after a click on the {name!r} field")
            session.click(*row["field_points"][0])
            flow.press_keeps_cube("Delete", undo_depth, f"after a click on the {name!r} field")

        # Intentional deletion from the Stage Browser and the viewport.
        rows = flow.state()["stage_ui"]["rows"]
        cube_row = next(r for r in rows if r["path"] == CUBE)
        session.click(*cube_row["select_point"])
        session.press("Delete")
        flow.settle()
        state = flow.assert_cube(False, "after Delete with the cube selected in the Stage Browser")
        assert state["undo"]["undo_depth"] == undo_depth + 1, state["undo"]
        assert state["undo"]["undo_label"] == "Delete", state["undo"]
        session.press("z", modifiers="ctrl")
        flow.settle()
        flow.assert_cube(True, "after Ctrl+Z")
        driver._click_cube(session)
        session.press("Backspace")
        flow.settle()
        flow.assert_cube(False, "after Backspace with the cube selected in the viewport")
    finally:
        session.stop()
