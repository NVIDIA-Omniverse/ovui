# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Visual verification for Step 3: global styles applied to a real window.

Run:
    python tests/verify_styles.py
    python tests/verify_styles.py --screenshot   # save to /tmp/ovgear_step3_styles.png

Displays buttons (ok / cancel / destructive), label, checkbox, field,
collapsable frame, and tree view — all styled via GLOBAL_STYLES.
"""

import os
import sys

# Ensure project root on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui

from ovwidgets.app.style import apply_global_styles

_SCREENSHOT = "--screenshot" in sys.argv
_PATH = "/tmp/ovgear_step3_styles.png"

WIDTH = 520
HEIGHT = 600 if _SCREENSHOT else 520

ui.init("OvGear Step 3 — Style Verification", width=WIDTH, height=HEIGHT)
apply_global_styles()

# ---------------------------------------------------------------------------
# Minimal tree model
# ---------------------------------------------------------------------------

class _Item(ui.AbstractItem):
    def __init__(self, text):
        super().__init__()
        self.model = ui.SimpleStringModel(text)
        self.children = []

class _Model(ui.AbstractItemModel):
    def __init__(self, root):
        super().__init__()
        self._root = root

    def get_item_children(self, item):
        return self._root if item is None else item.children

    def get_item_value_model_count(self, item):
        return 1

    def get_item_value_model(self, item, column_id):
        return None if item is None else item.model


scene = _Item("Scene")
geo = _Item("Geometry")
geo.children = [_Item("Cube"), _Item("Sphere")]
lights = _Item("Lights")
lights.children = [_Item("Sun"), _Item("Fill")]
scene.children = [geo, lights]
_tree_model = _Model([scene])

# ---------------------------------------------------------------------------
# Build the window
# ---------------------------------------------------------------------------

win = ui.Window(
    "OvGear Step 3 — Style Verification",
    width=WIDTH, height=HEIGHT,
    flags=(
        ui.WINDOW_FLAGS_NO_SCROLLBAR
        | ui.WINDOW_FLAGS_NO_TITLE_BAR
        | ui.WINDOW_FLAGS_NO_RESIZE
        | ui.WINDOW_FLAGS_NO_MOVE
    ),
    position_x=0, position_y=0,
    fill_app_window=not _SCREENSHOT,
)

with win.frame:
    with ui.ScrollingFrame(
        horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
    ):
        with ui.VStack(spacing=6, style={"margin": 10}):
            ui.Spacer(height=4)
            ui.Label(
                "OvGear Global Style Verification",
                height=26,
                alignment=ui.Alignment.CENTER,
                style={"font_size": 18},
            )
            ui.Spacer(height=4)

            # ---- Buttons ----
            with ui.CollapsableFrame("Buttons", height=0):
                with ui.HStack(spacing=6, height=0):
                    ui.Button(
                        "OK",
                        height=28,
                        style_type_name_override="Button",
                        style={"Button": {"background_color": 0xFF8A8777}},
                    )
                    ui.Button(
                        "OK (::ok)",
                        height=28,
                        name="ok",
                    )
                    ui.Button(
                        "Cancel",
                        height=28,
                        name="cancel",
                    )
                    ui.Button(
                        "Delete",
                        height=28,
                        name="destructive",
                    )

            ui.Spacer(height=2)

            # ---- Label ----
            with ui.CollapsableFrame("Labels", height=0):
                with ui.VStack(spacing=4):
                    ui.Label("Primary text (default)")
                    ui.Label("Disabled text", enabled=False)

            ui.Spacer(height=2)

            # ---- CheckBox ----
            with ui.CollapsableFrame("CheckBox", height=0):
                with ui.VStack(spacing=4):
                    with ui.HStack(spacing=6, height=20):
                        cb = ui.CheckBox(width=18)
                        cb.model.set_value(True)
                        ui.Label("Checked")
                    with ui.HStack(spacing=6, height=20):
                        cb2 = ui.CheckBox(width=18)
                        cb2.model.set_value(False)
                        ui.Label("Unchecked")

            ui.Spacer(height=2)

            # ---- Fields ----
            with ui.CollapsableFrame("Input Fields", height=0):
                with ui.VStack(spacing=4):
                    sf = ui.StringField(height=22)
                    sf.model.set_value("Hello OvGear")
                    ff = ui.FloatField(height=22)
                    ff.model.set_value(3.14)

            ui.Spacer(height=2)

            # ---- Progress ----
            with ui.CollapsableFrame("Progress", height=0):
                pb = ui.ProgressBar(height=16)
                pb.model.set_value(0.65)

            ui.Spacer(height=2)

            # ---- TreeView ----
            with ui.CollapsableFrame("Scene Hierarchy", height=0):
                with ui.ScrollingFrame(
                    height=120,
                    horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                    vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
                ):
                    _tv = ui.TreeView(
                        _tree_model,
                        root_visible=False,
                        height=0,
                    )

            ui.Spacer(height=4)


# ---------------------------------------------------------------------------
# Screenshot / run
# ---------------------------------------------------------------------------

async def _capture(path: str):
    from omni.ui import testing
    await testing.wait_frames(10)
    _tv.set_expanded(scene, True, False)
    await testing.wait_frames(4)
    testing.capture_screenshot(path)
    print(f"Screenshot saved: {path}")


if __name__ == "__main__":
    if _SCREENSHOT:
        ui.run(_capture(_PATH))
    else:
        ui.run()
