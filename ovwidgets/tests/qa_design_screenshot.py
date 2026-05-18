# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA screenshots for the Stage design iteration (feature/stage-design).

Captures three screenshots exercising different states:
  /tmp/ovgear_design_NNN_default.png   — tree fully expanded, default layout
  /tmp/ovgear_design_NNN_selected.png  — a prim selected, property panel populated
  /tmp/ovgear_design_NNN_filtered.png  — filter bar with "Sphere" typed in

Usage:
  LD_LIBRARY_PATH=... python3.12 tests/qa_design_screenshot.py <NNN>
where NNN is a 3-digit prefix (e.g. 010, 020) used for grouped iterations.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui
from omni.ui import color as cl_color
from ovui_data_adapters.common import AttributeMetadata
from ovwidgets.property.property_widget import PropertyWidget

from ovwidgets.app.layout import apply_default_layout, write_split_ini
from ovwidgets.app.menu_bar import build_menu_bar
from ovwidgets.app.status_bar import StatusBar
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_property import MockPropertyAdapter
from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.stage.window import StageWindow
from ovwidgets.viewport.viewport_widget import ViewportWidget

TAG = sys.argv[1] if len(sys.argv) > 1 else "000"


SelectionBus._instance = None
_bus = SelectionBus.instance()


class _FakeApp:
    class _UndoMgr:
        def can_undo(self) -> bool:
            return False

        def can_redo(self) -> bool:
            return False

        def undo(self) -> None:
            pass

        def redo(self) -> None:
            pass

    class _FakeSettings:
        def set(self, key: str, value: object) -> None:
            pass

    def __init__(self) -> None:
        self.undo_manager = self._UndoMgr()
        self.settings = self._FakeSettings()
        self.selection_bus = _bus
        self._recent_files = type("_RF", (), {"get_ordered": lambda self: []})()


def _make_mock_property_adapter(paths):
    attrs = {
        "xformOp:translate": AttributeMetadata(
            name="xformOp:translate", display_name="Translate",
            type_name="double3", value_type=float, group="Transform",
        ),
        "xformOp:scale": AttributeMetadata(
            name="xformOp:scale", display_name="Scale",
            type_name="float3", value_type=float, group="Transform",
        ),
        "visibility": AttributeMetadata(
            name="visibility", display_name="Visibility",
            type_name="token", value_type=str, group="Display",
        ),
    }
    adapter = MockPropertyAdapter(paths=paths, attributes=attrs)
    adapter.set_value("xformOp:translate", (1.0, 0.0, 0.5))
    adapter.set_value("xformOp:scale", (1.0, 1.0, 1.0))
    adapter.set_value("visibility", "inherited")
    return adapter


write_split_ini()
ui.init("OvGear Design QA", width=1280, height=720)
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

_dockspace = ui.DockSpace(None)
_dockspace.dock_frame.set_style({
    "padding": 18.0,
    "background_color": cl_color.background_primary,
})

_renderer = MockRendererAdapter()

# Build a mock adapter with richer state so screenshots exercise the
# composition-badge / inactive / default-prim / class branches. Badge and
# flag overrides are test-only API on MockStageAdapter.
from ovui_data_adapters.common import BadgeFlags, ItemFlags

_mock_adapter = MockStageAdapter()
_mock_adapter._item_flags_overrides = {
    "/World/Geometry/Ground": ItemFlags.IS_DEFAULT_PRIM,
    "/World/Geometry/Cube":   ItemFlags.IS_INACTIVE,
    "/World/Lights/DomeLight": ItemFlags.IS_CLASS,
}
_mock_adapter._badge_flags_overrides = {
    "/World/Geometry/Sphere":  BadgeFlags.REFERENCE,
    "/World/Geometry/Ground":  BadgeFlags.PAYLOAD,
    "/World/Camera":           BadgeFlags.INSTANCE,
    "/World/Lights/DomeLight": BadgeFlags.INHERITS,
}
_stage_win = StageWindow(adapter=_mock_adapter)
_prop_window = PropertyWidget()
_vp_window = ViewportWidget(services=_app, renderer=_renderer, bus=_bus)

_SELECTED_PATH = "/World/Geometry/Sphere"


def _expand_all() -> None:
    """Expand every node in the tree so screenshots reveal row styling."""
    widget = _stage_win._widget
    if widget is None:
        return
    for path in ("/World", "/World/Geometry", "/World/Lights"):
        try:
            widget.expand(path)
        except Exception:
            pass


async def _main() -> None:
    from omni.ui import testing

    await ui.next_frame()
    apply_default_layout()
    await testing.wait_frames(10)
    _vp_window._on_frame(0.1)
    await testing.wait_frames(4)

    # 1. Default layout, fully expanded tree.
    _expand_all()
    await testing.wait_frames(6)
    path1 = f"/tmp/ovgear_design_{TAG}_default.png"
    testing.capture_screenshot(path1)
    print(f"Screenshot 1: default expanded — {path1}")

    # 2. Select a prim — highlight + property panel.
    _prop_window.set_adapter(_make_mock_property_adapter([_SELECTED_PATH]))
    _prop_window.set_selection([_SELECTED_PATH])
    _bus.publish([_SELECTED_PATH], source="qa")
    _renderer.set_selection_highlight([_SELECTED_PATH])
    _vp_window._on_frame(0.1)
    await testing.wait_frames(6)
    path2 = f"/tmp/ovgear_design_{TAG}_selected.png"
    testing.capture_screenshot(path2)
    print(f"Screenshot 2: selected Sphere — {path2}")

    # 3. Type a filter — exercises the filter bar + match highlighting.
    widget = _stage_win._widget
    if widget is not None:
        widget.filter_by_text("Sphere")
    await testing.wait_frames(6)
    path3 = f"/tmp/ovgear_design_{TAG}_filtered.png"
    testing.capture_screenshot(path3)
    print(f"Screenshot 3: filtered on 'Sphere' — {path3}")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
