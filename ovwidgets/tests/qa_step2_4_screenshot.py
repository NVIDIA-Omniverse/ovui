# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot script for Property Window Step 2.4 — Mixed overlay.

Captures three screenshots showing the ``Property.MixedOverlay`` label
appearing on top of ambiguous value widgets:

  /tmp/ovgear_step2_4_1.png — Vec3 with only Z ambiguous (one channel overlay)
  /tmp/ovgear_step2_4_2.png — Vec3 with all three ambiguous (three overlays)
  /tmp/ovgear_step2_4_3.png — mixed row types: float + int + bool + string, all
                              ambiguous (one overlay per row), plus an
                              unambiguous float row for comparison.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... python3.12 tests/qa_step2_4_screenshot.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui
from ovui_data_adapters.common import AttributeMetadata

from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.testing.mock_property import MockPropertyAdapter
from ovwidgets.property.attribute_row import (
    BoolAttributeRow,
    FloatAttributeRow,
    IntAttributeRow,
    StringAttributeRow,
    Vec3FloatAttributeRow,
)
from ovwidgets.property.style import PROPERTY_STYLES


def _vec3_meta(name: str, display: str) -> AttributeMetadata:
    return AttributeMetadata(
        name=name, display_name=display, type_name="float3",
        value_type=float, group="Transform",
    )


def _scalar_meta(name: str, display: str, type_name: str, value_type) -> AttributeMetadata:
    return AttributeMetadata(
        name=name, display_name=display, type_name=type_name,
        value_type=value_type, group="Test",
    )


def _build_vec3_panel(paths_and_values, attr_name, display_name, header):
    meta = _vec3_meta(attr_name, display_name)
    adapter = MockPropertyAdapter(
        paths=[p for p, _ in paths_and_values],
        attributes={attr_name: meta},
    )
    for path, value in paths_and_values:
        adapter.set_path_value(path, attr_name, value)

    win = ui.Window(header, width=520, height=140)
    with win.frame:
        with ui.VStack(spacing=6, style=PROPERTY_STYLES):
            ui.Label(header, height=24)
            ui.Spacer(height=4)
            Vec3FloatAttributeRow(meta, adapter)
            ui.Spacer(height=4)
            labels = ", ".join(f"{p}={v}" for p, v in paths_and_values)
            ui.Label(f"selected: {labels}", height=20)
    return win


def _build_mixed_row_panel(header):
    float_meta = _scalar_meta("radius", "Radius", "float", float)
    int_meta = _scalar_meta("count", "Count", "int", int)
    bool_meta = _scalar_meta("enabled", "Enabled", "bool", bool)
    str_meta = _scalar_meta("name", "Name", "string", str)
    clean_meta = _scalar_meta("clean", "Clean", "float", float)

    paths = ["/A", "/B"]
    adapter = MockPropertyAdapter(
        paths=paths,
        attributes={
            "radius": float_meta, "count": int_meta,
            "enabled": bool_meta, "name": str_meta, "clean": clean_meta,
        },
    )
    adapter.set_path_value("/A", "radius", 1.0)
    adapter.set_path_value("/B", "radius", 2.0)
    adapter.set_path_value("/A", "count", 1)
    adapter.set_path_value("/B", "count", 42)
    adapter.set_path_value("/A", "enabled", True)
    adapter.set_path_value("/B", "enabled", False)
    adapter.set_path_value("/A", "name", "sphere")
    adapter.set_path_value("/B", "name", "cube")
    adapter.set_path_value("/A", "clean", 3.14)
    adapter.set_path_value("/B", "clean", 3.14)

    win = ui.Window(header, width=520, height=220)
    with win.frame:
        with ui.VStack(spacing=6, style=PROPERTY_STYLES):
            ui.Label(header, height=24)
            ui.Spacer(height=4)
            FloatAttributeRow(float_meta, adapter)
            IntAttributeRow(int_meta, adapter)
            BoolAttributeRow(bool_meta, adapter)
            StringAttributeRow(str_meta, adapter)
            FloatAttributeRow(clean_meta, adapter)
            ui.Spacer(height=4)
            ui.Label("First four rows mixed → overlay visible. Last row clean.", height=20)
    return win


ui.init("OvGear Step 2.4 QA", width=640, height=260)
apply_global_styles()
set_theme("dark")


async def _main() -> None:
    from omni.ui import testing

    # Shot 1: Vec3 only Z differs — single channel overlay
    win1 = _build_vec3_panel(
        [("/Prim1", (1.0, 2.0, 3.0)), ("/Prim2", (1.0, 2.0, 7.0))],
        "translate", "Translate",
        'Step 2.4 — only Z ambiguous ("Mixed" over Z only)',
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step2_4_1.png")
    print("Screenshot 1 (Z overlay): /tmp/ovgear_step2_4_1.png")
    win1.visible = False
    await testing.wait_frames(2)

    # Shot 2: Vec3 all three differ — three overlays
    win2 = _build_vec3_panel(
        [("/Prim1", (1.0, 2.0, 3.0)), ("/Prim2", (9.0, 8.0, 7.0))],
        "rotateXYZ", "Rotate",
        'Step 2.4 — all three ambiguous ("Mixed" over X, Y, Z)',
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step2_4_2.png")
    print("Screenshot 2 (X+Y+Z overlays): /tmp/ovgear_step2_4_2.png")
    win2.visible = False
    await testing.wait_frames(2)

    # Shot 3: mixed row types — float/int/bool/string all ambiguous + one clean row
    win3 = _build_mixed_row_panel(
        'Step 2.4 — scalar rows: "Mixed" overlay on ambiguous widgets',
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step2_4_3.png")
    print("Screenshot 3 (scalar overlays): /tmp/ovgear_step2_4_3.png")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
