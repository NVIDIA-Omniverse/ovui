# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot script for Property Window Step 2.3 — Vec3 per-component ambiguity.

Captures three screenshots of isolated Vec3FloatAttributeRow panels, each
driving a different per-component ambiguity pattern so the mixed-channel
styling is visible in isolation:

  /tmp/ovgear_step2_3_1.png — only Z differs → Z label reads warning colour
  /tmp/ovgear_step2_3_2.png — only X differs → X label reads warning colour
  /tmp/ovgear_step2_3_3.png — all three differ → all labels read warning colour

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... python3.12 tests/qa_step2_3_screenshot.py
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


def _build_panel(paths_and_values, attr_name, display_name, header):
    """Build a small window containing a single Vec3FloatAttributeRow."""
    meta = AttributeMetadata(
        name=attr_name,
        display_name=display_name,
        type_name="float3",
        value_type=float,
        group="Transform",
    )
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


ui.init("OvGear Step 2.3 QA", width=640, height=200)
apply_global_styles()
set_theme("dark")


async def _main() -> None:
    from omni.ui import testing

    # ── Shot 1: only Z differs ────────────────────────────────────────────
    win1 = _build_panel(
        [("/Prim1", (1.0, 2.0, 3.0)), ("/Prim2", (1.0, 2.0, 7.0))],
        "translate",
        "Translate",
        "Step 2.3 — only Z differs (mixed on Z label)",
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step2_3_1.png")
    print("Screenshot 1 (Z mixed): /tmp/ovgear_step2_3_1.png")
    win1.visible = False
    await testing.wait_frames(2)

    # ── Shot 2: only X differs ────────────────────────────────────────────
    win2 = _build_panel(
        [("/Prim1", (1.0, 5.0, 0.0)), ("/Prim2", (9.0, 5.0, 0.0))],
        "scale",
        "Scale",
        "Step 2.3 — only X differs (mixed on X label)",
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step2_3_2.png")
    print("Screenshot 2 (X mixed): /tmp/ovgear_step2_3_2.png")
    win2.visible = False
    await testing.wait_frames(2)

    # ── Shot 3: all three differ ──────────────────────────────────────────
    win3 = _build_panel(
        [("/Prim1", (1.0, 2.0, 3.0)), ("/Prim2", (9.0, 8.0, 7.0))],
        "rotateXYZ",
        "Rotate",
        "Step 2.3 — all channels differ (mixed on X, Y, Z)",
    )
    await testing.wait_frames(12)
    testing.capture_screenshot("/tmp/ovgear_step2_3_3.png")
    print("Screenshot 3 (X+Y+Z mixed): /tmp/ovgear_step2_3_3.png")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
