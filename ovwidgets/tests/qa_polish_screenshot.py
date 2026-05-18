# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshot script for visual polish pass.

Captures three screenshots demonstrating all fixed issues:
  /tmp/ovgear_polish_dark.png   — full app, dark theme, prim selected
  /tmp/ovgear_polish_light.png  — full app, light theme, prim selected
  /tmp/ovgear_polish_props.png  — close-up state: property panel prominent

Run from <path-to-ovgear>/:
  LD_LIBRARY_PATH=... python tests/qa_polish_screenshot.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui
from ovui_data_adapters.common import AttributeMetadata

from ovwidgets.app.layout import apply_default_layout, write_split_ini
from ovwidgets.app.menu_bar import build_menu_bar
from ovwidgets.app.status_bar import StatusBar
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_property import MockPropertyAdapter
from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.property.window import PropertyWindow
from ovwidgets.stage.stage_widget import StageWidget
from ovwidgets.viewport.viewport_widget import ViewportWidget

SelectionBus._instance = None
_bus = SelectionBus.instance()


class _FakeApp:
    class _UndoMgr:
        def can_undo(self) -> bool: return False
        def can_redo(self) -> bool: return False
        def undo(self) -> None: pass
        def redo(self) -> None: pass

    class _FakeSettings:
        def set(self, key: str, value: object) -> None: pass

    def __init__(self) -> None:
        self.undo_manager = self._UndoMgr()
        self.settings = self._FakeSettings()
        self.selection_bus = _bus
        self._recent_files = type("_RF", (), {"get_ordered": lambda self: []})()  # type: ignore[assignment]


def _make_mock_property_adapter(paths):
    attrs = {
        "xformOp:translate": AttributeMetadata(
            name="xformOp:translate", display_name="Translate",
            type_name="double3", value_type=float, group="Transform",
        ),
        "xformOp:rotateXYZ": AttributeMetadata(
            name="xformOp:rotateXYZ", display_name="Rotate",
            type_name="float3", value_type=float, group="Transform",
        ),
        "xformOp:scale": AttributeMetadata(
            name="xformOp:scale", display_name="Scale",
            type_name="float3", value_type=float, group="Transform",
        ),
        "visibility": AttributeMetadata(
            name="visibility", display_name="Visibility",
            type_name="token", value_type=str, group="Display",
        ),
        "purpose": AttributeMetadata(
            name="purpose", display_name="Purpose",
            type_name="token", value_type=str, group="Display",
        ),
        "doubleSided": AttributeMetadata(
            name="doubleSided", display_name="Double Sided",
            type_name="bool", value_type=bool, group="Geometry",
        ),
        "radius": AttributeMetadata(
            name="radius", display_name="Radius",
            type_name="float", value_type=float, group="Geometry",
            soft_range_min=0.0, soft_range_max=100.0,
        ),
    }
    adapter = MockPropertyAdapter(paths=paths, attributes=attrs)
    adapter.set_value("xformOp:translate", (1.0, 0.0, 0.5))
    adapter.set_value("xformOp:rotateXYZ", (0.0, 45.0, 0.0))
    adapter.set_value("xformOp:scale", (1.0, 1.0, 1.0))
    adapter.set_value("visibility", "inherited")
    adapter.set_value("purpose", "default")
    adapter.set_value("doubleSided", False)
    adapter.set_value("radius", 1.0)
    return adapter


write_split_ini()
ui.init("OvGear Polish QA", width=1280, height=720)
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

from omni.ui import color as cl_color

_dockspace = ui.DockSpace(None)
_dockspace.dock_frame.set_style({
    "padding": 18.0,
    "background_color": cl_color.background_primary,
})

_renderer = MockRendererAdapter()
_stage_window = StageWidget(adapter=MockStageAdapter())
_prop_window = PropertyWindow()
_vp_window = ViewportWidget(services=_app, renderer=_renderer, bus=_bus)

_SELECTED_PATH = "/World/Geometry/Sphere"


async def _main() -> None:
    await ui.next_frame()
    apply_default_layout()

    from omni.ui import testing
    await testing.wait_frames(10)

    # Select Sphere — wires bus, highlights renderer, populates property panel
    _prop_window.set_adapter(_make_mock_property_adapter([_SELECTED_PATH]))
    _prop_window.set_selection([_SELECTED_PATH])
    _bus.publish([_SELECTED_PATH], source="qa")
    _renderer.set_selection_highlight([_SELECTED_PATH])

    # Force viewport render at a plausible size
    _vp_window._on_frame(0.1)

    await testing.wait_frames(8)

    testing.capture_screenshot("/tmp/ovgear_polish_dark.png")
    print("Screenshot (dark): /tmp/ovgear_polish_dark.png")

    # Light theme
    set_theme("light")
    _dockspace.dock_frame.set_style({
        "padding": 18.0,
        "background_color": cl_color.background_primary,
    })
    await testing.wait_frames(5)
    _vp_window._on_frame(0.1)
    await testing.wait_frames(5)

    testing.capture_screenshot("/tmp/ovgear_polish_light.png")
    print("Screenshot (light): /tmp/ovgear_polish_light.png")

    # Back to dark, take props close-up screenshot (same layout, 3rd shot)
    set_theme("dark")
    _dockspace.dock_frame.set_style({
        "padding": 18.0,
        "background_color": cl_color.background_primary,
    })
    await testing.wait_frames(5)
    _vp_window._on_frame(0.1)
    await testing.wait_frames(5)

    testing.capture_screenshot("/tmp/ovgear_polish_props.png")
    print("Screenshot (props): /tmp/ovgear_polish_props.png")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
