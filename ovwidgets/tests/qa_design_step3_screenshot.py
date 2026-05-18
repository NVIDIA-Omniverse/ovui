# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot harness for Design Step 3 (filter field redesign).

Captures four screenshots demonstrating the Stage + Property filter pills:

  /tmp/ovgear_design_step3_before.png   — pre-change layout (unchanged here)
  /tmp/ovgear_design_step3_empty.png    — both pills at rest
  /tmp/ovgear_design_step3_focused.png  — Stage pill focused (accent border)
  /tmp/ovgear_design_step3_typed.png    — text entered, clear-x visible

To keep the pills legible without spinning up the full OvGear layout
(which keeps the Stage panel collapsed to a 20% strip on 1280-wide
windows), this harness builds a small dedicated window that docks the
Stage + Property filter bars side-by-side at a generous size.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... python tests/qa_design_step3_screenshot.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui
from ovui_data_adapters.common import AttributeMetadata

from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_property import MockPropertyAdapter
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.property.window import PropertyWindow
from ovwidgets.stage.window.stage_window import StageWindow

OUT_EMPTY = "/tmp/ovgear_design_step3_empty.png"
OUT_FOCUSED = "/tmp/ovgear_design_step3_focused.png"
OUT_TYPED = "/tmp/ovgear_design_step3_typed.png"
OUT_AFTER = "/tmp/ovgear_design_step3_after.png"


SelectionBus._instance = None
_bus = SelectionBus.instance()


def _mock_property_adapter(paths):
    attrs = {
        "xformOp:translate": AttributeMetadata(
            name="xformOp:translate", display_name="Translate",
            type_name="double3", value_type=float, group="Transform",
        ),
        "radius": AttributeMetadata(
            name="radius", display_name="Radius",
            type_name="float", value_type=float, group="Geometry",
            soft_range_min=0.0, soft_range_max=100.0,
        ),
        "doubleSided": AttributeMetadata(
            name="doubleSided", display_name="Double Sided",
            type_name="bool", value_type=bool, group="Geometry",
        ),
    }
    adapter = MockPropertyAdapter(paths=paths, attributes=attrs)
    adapter.set_value("xformOp:translate", (0.0, 0.0, 0.0))
    adapter.set_value("radius", 1.0)
    adapter.set_value("doubleSided", False)
    return adapter


ui.init("OvGear Design Step 3 QA", width=1280, height=720)
apply_global_styles()
set_theme("dark")

_stage_win = StageWindow(adapter=MockStageAdapter())
_prop_win = PropertyWindow()

# Dock Stage LEFT and Property RIGHT in a 50/50 split so both filter
# bars get a generous visible width (~600 px each), well above what the
# default 20/60/20 layout provides.
_stage_win.window.dock_order = 0
_prop_win.window.dock_order = 1
_prop_win.window.width = 640
_prop_win.window.height = 720
_stage_win.window.width = 640
_stage_win.window.height = 720


async def _main() -> None:
    # Let ImGui assign dock nodes and wire up mock selection.
    await ui.next_frame()
    _SELECTED = "/World/Geometry/Sphere"
    _prop_win.set_adapter(_mock_property_adapter([_SELECTED]))
    _prop_win.set_selection([_SELECTED])
    _bus.publish([_SELECTED], source="qa")

    from omni.ui import testing
    await testing.wait_frames(12)

    # Side-by-side dock: Property to the RIGHT of Stage, 50/50.
    stage_handle = ui.Workspace.get_window("Stage Browser")
    if stage_handle is not None:
        _prop_win.window.dock_in(stage_handle, ui.DockPosition.RIGHT, ratio=0.50)
    await testing.wait_frames(8)

    # Resize so the two pills dominate the frame.
    stage_inner = _stage_win._widget
    prop_field = _prop_win._filter_field
    stage_field = stage_inner._filter_field

    testing.capture_screenshot(OUT_EMPTY)
    testing.capture_screenshot(OUT_AFTER)
    print(f"Screenshot (empty): {OUT_EMPTY}")

    # Focus the Stage field — call the widget's own handler directly to
    # swap ``_filter_rect.name`` to ``"focused"``. omni.ui doesn't expose
    # a public way to fire a StringField's begin-edit callback list from
    # Python, so we drive the hook imperatively (same code path that the
    # live UI runs when the user clicks into the field).
    stage_inner._on_filter_begin_edit(stage_field.model)
    await testing.wait_frames(5)
    testing.capture_screenshot(OUT_FOCUSED)
    print(f"Screenshot (focused): {OUT_FOCUSED}")
    # Return to the unfocused state before typing so the typed screenshot
    # doesn't inherit the focus ring.
    stage_inner._on_filter_end_edit(stage_field.model)
    await testing.wait_frames(2)

    # Type "Sphere" into Stage and "radius" into Property. Models emit
    # value-changed → filter kicks in → clear-x becomes visible and the
    # magnifier flips to the ``::active`` accent tint.
    if stage_field is not None:
        stage_field.model.set_value("Sphere")
    if prop_field is not None:
        prop_field.model.set_value("radius")
    await testing.wait_frames(6)
    testing.capture_screenshot(OUT_TYPED)
    print(f"Screenshot (typed): {OUT_TYPED}")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
