# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Verify Step 36: PropertyWindow full integration — shows USD attributes for selected prim.

Creates an in-memory stage with a Sphere, wires PropertyWindow to UsdPropertyAdapter,
selects the Sphere, and screenshots the property inspector showing real USD attributes.

Run:
    DISPLAY=:99 python tests/verify_step36.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import omni.ui as ui
from ovui_data_adapters.openusd import UsdPropertyAdapter
from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
from pxr import Gf, Usd, UsdGeom

from ovwidgets.app.layout import apply_default_layout, write_split_ini
from ovwidgets.app.menu_bar import build_menu_bar
from ovwidgets.app.status_bar import StatusBar
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.common.undo import UndoManager
from ovwidgets.property.window import PropertyWindow
from ovwidgets.stage.stage_widget import StageWidget
from ovwidgets.viewport.viewport_widget import ViewportWidget


class _FakeApp:
    class _UndoMgr:
        def can_undo(self): return False
        def can_redo(self): return False
        def undo(self): pass
        def redo(self): pass

    def __init__(self):
        self.undo_manager = self._UndoMgr()
        self._stage_window = None
        self._property_window = None
        self._viewport_window = None


write_split_ini()

ui.init("OvGear Step36 Verify", width=1280, height=720)
apply_global_styles()
set_theme("dark")

_app = _FakeApp()

main_win = ui.Window(
    "OvGear",
    flags=(
        ui.WINDOW_FLAGS_NO_TITLE_BAR
        | ui.WINDOW_FLAGS_NO_RESIZE
        | ui.WINDOW_FLAGS_NO_MOVE
        | ui.WINDOW_FLAGS_NO_SCROLLBAR
        | ui.WINDOW_FLAGS_MENU_BAR
        | ui.WINDOW_FLAGS_NO_DOCKING
        | ui.WINDOW_FLAGS_NO_BACKGROUND
    ),
    fill_app_window=True,
)

with main_win.frame:
    with ui.VStack(spacing=0):
        with ui.MenuBar():
            build_menu_bar(_app)
        ui.Spacer()
        _sf = ui.Frame(height=24)
        _sb = StatusBar(_sf)
        _sb.show_message("Step 36: Property Inspector — /Sphere attributes", 0, "success")

_dockspace = ui.DockSpace(None)
_dockspace.dock_frame.set_style({"padding": 18})

# Create the USD stage with a Sphere
stage = Usd.Stage.CreateInMemory()
sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
sphere.GetRadiusAttr().Set(2.5)
UsdGeom.XformCommonAPI(sphere).SetTranslate(Gf.Vec3d(1.0, 2.0, 3.0))

undo = UndoManager()
stage_adapter = UsdStageAdapter(stage, undo)
prop_adapter = UsdPropertyAdapter(stage, ["/Sphere"], undo, stage_adapter)

_app._stage_window = StageWidget(adapter=MockStageAdapter())
_app._property_window = PropertyWindow()
_app._viewport_window = ViewportWidget()


async def _main():
    await ui.next_frame()

    apply_default_layout()

    # Wire PropertyWindow to the real USD adapter
    pw = _app._property_window
    pw.set_property_adapter_factory(lambda paths: prop_adapter)
    pw.set_stage_adapter(stage_adapter, undo)
    pw.set_selection(["/Sphere"])

    from omni.ui import testing
    await testing.wait_frames(10)

    # Verify attributes are present
    names = pw._adapter.get_attribute_names() if pw._adapter else []
    print(f"Adapter attribute names: {names}")
    assert "radius" in names, f"radius not found in {names}"

    testing.capture_screenshot("/tmp/ovgear_step36.png")
    print("Screenshot saved: /tmp/ovgear_step36.png")
    print("PASS: PropertyWindow shows real USD attributes for /Sphere")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
