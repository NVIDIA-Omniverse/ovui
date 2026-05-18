# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot script for Property Window Step 2.5 — channel colour coding.

Captures three screenshots showing property attribute builder behavior channel colouring applied to
``Vec3FloatAttributeRow`` via the ``Property.ChannelLabel.{X,Y,Z}`` style
types:

  /tmp/ovgear_step2_5_1.png — clean vec3 rows (single path): X blue, Y green,
                              Z orange channel labels across translate /
                              rotate / scale / colour rows.
  /tmp/ovgear_step2_5_2.png — mixed Z channel: Z label warning-orange, X/Y
                              keep their axis colours. Pins the interaction
                              between Step 2.3 (``::mixed`` state) and Step
                              2.5 (``ChannelLabel.{Z}`` base).
  /tmp/ovgear_step2_5_3.png — all three channels mixed: every label reads
                              warning-orange (Step 2.3 ``::mixed`` wins over
                              every axis colour).

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... python3.12 tests/qa_step2_5_screenshot.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui
from ovui_data_adapters.common import AttributeMetadata

from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.testing.mock_property import MockPropertyAdapter
from ovwidgets.property.attribute_row import Vec3FloatAttributeRow
from ovwidgets.property.style import PROPERTY_STYLES


def _vec3_meta(name: str, display: str) -> AttributeMetadata:
    return AttributeMetadata(
        name=name, display_name=display, type_name="float3",
        value_type=float, group="Transform",
    )


def _build_clean_panel(header):
    """Four vec3 rows, all single-path → axis colours only, no mixed."""
    rows = [
        ("translate", "Translate", (0.0, 0.0, 0.0)),
        ("rotateXYZ", "Rotate",    (0.0, 90.0, 0.0)),
        ("scale",     "Scale",     (1.0, 1.0, 1.0)),
        ("color",     "Color",     (0.8, 0.4, 0.2)),
    ]
    metas = {name: _vec3_meta(name, disp) for name, disp, _ in rows}
    adapter = MockPropertyAdapter(paths=["/Prim"], attributes=metas)
    for name, _, value in rows:
        adapter.set_path_value("/Prim", name, value)

    win = ui.Window(header, width=520, height=200)
    with win.frame:
        with ui.VStack(spacing=6, style=PROPERTY_STYLES):
            ui.Label(header, height=24)
            ui.Spacer(height=4)
            for name, _, _ in rows:
                Vec3FloatAttributeRow(metas[name], adapter)
            ui.Spacer(height=4)
            ui.Label(
                "X=blue (#4060AA)  Y=green (#60A371)  Z=orange (#A07D4F)",
                height=20,
            )
    return win


def _build_mixed_panel(paths_and_values, header, caption):
    meta = _vec3_meta("translate", "Translate")
    adapter = MockPropertyAdapter(
        paths=[p for p, _ in paths_and_values],
        attributes={"translate": meta},
    )
    for path, value in paths_and_values:
        adapter.set_path_value(path, "translate", value)

    win = ui.Window(header, width=520, height=130)
    with win.frame:
        with ui.VStack(spacing=6, style=PROPERTY_STYLES):
            ui.Label(header, height=24)
            ui.Spacer(height=4)
            Vec3FloatAttributeRow(meta, adapter)
            ui.Spacer(height=4)
            ui.Label(caption, height=20)
    return win


ui.init("OvGear Step 2.5 QA", width=640, height=260)
apply_global_styles()
set_theme("dark")


async def _main() -> None:
    from omni.ui import testing

    win1 = _build_clean_panel(
        "Step 2.5 — channel colour coding (clean rows: X blue, Y green, Z orange)",
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step2_5_1.png")
    print("Screenshot 1 (axis colours): /tmp/ovgear_step2_5_1.png")
    win1.visible = False
    await testing.wait_frames(2)

    win2 = _build_mixed_panel(
        [("/P1", (1.0, 2.0, 3.0)), ("/P2", (1.0, 2.0, 9.0))],
        "Step 2.5 — only Z ambiguous (Z warning-orange, X blue, Y green)",
        "Step 2.3 ::mixed overrides Step 2.5 axis colour for the Z channel only.",
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step2_5_2.png")
    print("Screenshot 2 (Z mixed override): /tmp/ovgear_step2_5_2.png")
    win2.visible = False
    await testing.wait_frames(2)

    win3 = _build_mixed_panel(
        [("/P1", (1.0, 2.0, 3.0)), ("/P2", (9.0, 8.0, 7.0))],
        "Step 2.5 — all three ambiguous (every label warning-orange)",
        "Step 2.3 ::mixed wins over X/Y/Z axis colours; mixed signal stays consistent.",
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step2_5_3.png")
    print("Screenshot 3 (all mixed): /tmp/ovgear_step2_5_3.png")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
