# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot script for Property Window Step 3.1 — Vec2 + Vec4 rows.

Captures three screenshots that exercise the new ``Vec2FloatAttributeRow``
and ``Vec4FloatAttributeRow`` classes introduced in Step 3.1:

  /tmp/ovgear_step3_1_1.png — single-path vec2 / vec3 / vec4 rows side by
                              side. Demonstrates the same axis-colour
                              convention carries across all three row
                              widths, and the W channel (red) renders at
                              the vec4 row's end.

  /tmp/ovgear_step3_1_2.png — vec2 row with only Y ambiguous, vec4 row
                              with only W ambiguous. Pins Step 2.3
                              ``::mixed`` state flowing through the new
                              row widths — the ambiguity list's fourth
                              element actually lands on the fourth widget.

  /tmp/ovgear_step3_1_3.png — vec4 row with all four channels ambiguous.
                              Every label reads warning-orange and every
                              field shows the "Mixed" overlay — the
                              consistent mixed signal from Step 2.4
                              scales out to four channels.

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... python3.12 tests/qa_step3_1_screenshot.py
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
    Vec2FloatAttributeRow,
    Vec3FloatAttributeRow,
    Vec4FloatAttributeRow,
)
from ovwidgets.property.style import PROPERTY_STYLES


def _vec_meta(name: str, display: str, type_name: str) -> AttributeMetadata:
    return AttributeMetadata(
        name=name, display_name=display, type_name=type_name,
        value_type=tuple, group="Transform",
    )


def _build_all_widths_panel(header):
    """Vec2 / Vec3 / Vec4 rows single-path — axis colours across every width.

    Values chosen so each row is visually distinguishable:
      uv       → (0.25, 0.75)
      translate → (1.0, 2.0, 3.0)
      quat     → (0.0, 0.0, 0.0, 1.0)  — identity quaternion-ish for the W=red beat.
    """
    rows = [
        ("uv",       "UV (vec2)",     "float2", (0.25, 0.75),       Vec2FloatAttributeRow),
        ("translate", "Translate",    "float3", (1.0, 2.0, 3.0),    Vec3FloatAttributeRow),
        ("quat",     "Quat (vec4)",   "float4", (0.0, 0.0, 0.0, 1.0), Vec4FloatAttributeRow),
    ]
    metas = {name: _vec_meta(name, disp, tn) for name, disp, tn, _, _ in rows}
    adapter = MockPropertyAdapter(paths=["/Prim"], attributes=metas)
    for name, _, _, value, _ in rows:
        adapter.set_path_value("/Prim", name, value)

    win = ui.Window(header, width=560, height=200)
    with win.frame:
        with ui.VStack(spacing=6, style=PROPERTY_STYLES):
            ui.Label(header, height=24)
            ui.Spacer(height=4)
            for name, _, _, _, row_cls in rows:
                row_cls(metas[name], adapter)
            ui.Spacer(height=4)
            ui.Label(
                "X=blue  Y=green  Z=orange  W=red (property attribute builder behavior)",
                height=20,
            )
    return win


def _build_selective_mixed_panel(header):
    """Vec2 with Y ambiguous + Vec4 with W ambiguous.

    Confirms that Step 2.3's ``::mixed`` state selector flows through the
    new row widths: the Y overlay on the vec2 row and the W overlay on the
    vec4 row are both visible, while the other channels render clean axis
    colours.
    """
    uv = _vec_meta("uv", "UV (vec2, Y mixed)", "float2")
    quat = _vec_meta("quat", "Quat (vec4, W mixed)", "float4")
    adapter = MockPropertyAdapter(
        paths=["/P1", "/P2"],
        attributes={"uv": uv, "quat": quat},
    )
    adapter.set_path_value("/P1", "uv", (0.5, 0.25))
    adapter.set_path_value("/P2", "uv", (0.5, 0.9))
    adapter.set_path_value("/P1", "quat", (0.0, 0.0, 0.0, 0.0))
    adapter.set_path_value("/P2", "quat", (0.0, 0.0, 0.0, 1.0))

    win = ui.Window(header, width=560, height=180)
    with win.frame:
        with ui.VStack(spacing=6, style=PROPERTY_STYLES):
            ui.Label(header, height=24)
            ui.Spacer(height=4)
            Vec2FloatAttributeRow(uv, adapter)
            Vec4FloatAttributeRow(quat, adapter)
            ui.Spacer(height=4)
            ui.Label(
                "Y (vec2) + W (vec4) warning-orange; other channels keep axis colour.",
                height=20,
            )
    return win


def _build_all_w_mixed_panel(header):
    """Vec4 with all four channels ambiguous — every label warning-orange."""
    quat = _vec_meta("quat", "Quat (all mixed)", "float4")
    adapter = MockPropertyAdapter(paths=["/P1", "/P2"], attributes={"quat": quat})
    adapter.set_path_value("/P1", "quat", (0.0, 0.0, 0.0, 0.0))
    adapter.set_path_value("/P2", "quat", (1.0, 1.0, 1.0, 1.0))

    win = ui.Window(header, width=560, height=150)
    with win.frame:
        with ui.VStack(spacing=6, style=PROPERTY_STYLES):
            ui.Label(header, height=24)
            ui.Spacer(height=4)
            Vec4FloatAttributeRow(quat, adapter)
            ui.Spacer(height=4)
            ui.Label(
                "All four channels mixed — warning-orange wins over X/Y/Z/W axis colours.",
                height=20,
            )
    return win


ui.init("OvGear Step 3.1 QA", width=640, height=260)
apply_global_styles()
set_theme("dark")


async def _main() -> None:
    from omni.ui import testing

    win1 = _build_all_widths_panel(
        "Step 3.1 — vec2 / vec3 / vec4 rows (X blue, Y green, Z orange, W red)",
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step3_1_1.png")
    print("Screenshot 1 (all widths): /tmp/ovgear_step3_1_1.png")
    win1.visible = False
    await testing.wait_frames(2)

    win2 = _build_selective_mixed_panel(
        "Step 3.1 — vec2 (Y mixed) + vec4 (W mixed)",
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step3_1_2.png")
    print("Screenshot 2 (selective mixed): /tmp/ovgear_step3_1_2.png")
    win2.visible = False
    await testing.wait_frames(2)

    win3 = _build_all_w_mixed_panel(
        "Step 3.1 — vec4 with all four channels ambiguous",
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step3_1_3.png")
    print("Screenshot 3 (all four mixed): /tmp/ovgear_step3_1_3.png")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
