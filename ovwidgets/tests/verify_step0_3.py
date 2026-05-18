# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 0.3 visual QA: capture property panel with CollapsableFrame groups.

Three screenshots:
  /tmp/ovgear_step0_3_1.png — groups all expanded, hover-free
  /tmp/ovgear_step0_3_2.png — Transform group collapsed (arrow rotated)
  /tmp/ovgear_step0_3_3.png — Transform expanded again + Geometry collapsed

Run:
  LD_LIBRARY_PATH=... python3.12 tests/verify_step0_3.py
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


def _make_adapter(paths):
    attrs = {
        "xformOp:translate": AttributeMetadata(
            "xformOp:translate", "Translate", "double3", float, "Transform"
        ),
        "xformOp:rotateXYZ": AttributeMetadata(
            "xformOp:rotateXYZ", "Rotate", "float3", float, "Transform"
        ),
        "xformOp:scale": AttributeMetadata(
            "xformOp:scale", "Scale", "float3", float, "Transform"
        ),
        "visibility": AttributeMetadata(
            "visibility", "Visibility", "token", str, "Display"
        ),
        "purpose": AttributeMetadata(
            "purpose", "Purpose", "token", str, "Display"
        ),
        "doubleSided": AttributeMetadata(
            "doubleSided", "Double Sided", "bool", bool, "Geometry"
        ),
        "radius": AttributeMetadata(
            "radius", "Radius", "float", float, "Geometry",
            soft_range_min=0.0, soft_range_max=100.0,
        ),
    }
    a = MockPropertyAdapter(paths=paths, attributes=attrs)
    a.set_value("xformOp:translate", (1.0, 0.0, 0.5))
    a.set_value("xformOp:rotateXYZ", (0.0, 45.0, 0.0))
    a.set_value("xformOp:scale", (1.0, 1.0, 1.0))
    a.set_value("visibility", "inherited")
    a.set_value("purpose", "default")
    a.set_value("doubleSided", False)
    a.set_value("radius", 1.0)
    return a


write_split_ini()
ui.init("OvGear Step 0.3 QA", width=1280, height=720)
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

# Capture the AttributeGroupWidget instances as they are built so the QA
# script can drive them from the outside without reaching into omni.ui.
_captured_groups: dict = {}
_orig_build_groups = _prop_window._build_groups


def _capturing_build_groups() -> None:
    from ovwidgets.property.group_widget import AttributeGroupWidget as _AGW
    _orig_ctor = _AGW.__init__

    def _wrapped_ctor(self, name, initially_collapsed=False, on_collapse_change=None):
        _orig_ctor(self, name, initially_collapsed, on_collapse_change)
        _captured_groups[name] = self

    _AGW.__init__ = _wrapped_ctor  # type: ignore[method-assign]
    try:
        _orig_build_groups()
    finally:
        _AGW.__init__ = _orig_ctor  # type: ignore[method-assign]


_prop_window._build_groups = _capturing_build_groups  # type: ignore[method-assign]

_SELECTED_PATH = "/World/Geometry/Sphere"


async def _main() -> None:
    await ui.next_frame()
    apply_default_layout()

    from omni.ui import testing
    await testing.wait_frames(10)

    _prop_window.set_adapter(_make_adapter([_SELECTED_PATH]))
    _prop_window.set_selection([_SELECTED_PATH])
    _bus.publish([_SELECTED_PATH], source="qa")
    _renderer.set_selection_highlight([_SELECTED_PATH])
    _vp_window._on_frame(0.1)
    await testing.wait_frames(8)

    testing.capture_screenshot("/tmp/ovgear_step0_3_1.png")
    print("Screenshot 1 (all expanded): /tmp/ovgear_step0_3_1.png")

    # Action 2: collapse Transform via the public API — goes through
    # AttributeGroupWidget.set_collapsed → ui.CollapsableFrame.collapsed setter,
    # which is the same notify-path a user header click exercises.
    transform_widget = _captured_groups.get("Transform")
    assert transform_widget is not None, f"Transform group missing; captured={list(_captured_groups)}"
    transform_widget.set_collapsed(True)
    assert transform_widget.is_collapsed is True
    await testing.wait_frames(5)

    testing.capture_screenshot("/tmp/ovgear_step0_3_2.png")
    print("Screenshot 2 (Transform collapsed): /tmp/ovgear_step0_3_2.png")

    # Action 3: re-expand Transform + collapse Geometry
    transform_widget.set_collapsed(False)
    geometry_widget = _captured_groups.get("Geometry")
    assert geometry_widget is not None, f"Geometry group missing; captured={list(_captured_groups)}"
    geometry_widget.set_collapsed(True)
    await testing.wait_frames(5)

    testing.capture_screenshot("/tmp/ovgear_step0_3_3.png")
    print("Screenshot 3 (Transform expanded, Geometry collapsed): /tmp/ovgear_step0_3_3.png")

    # Structural invariants
    assert _prop_window._group_collapse_state.get("Geometry") is True, \
        "Geometry collapse state should have persisted via on_collapse_change"
    print("OK: on_collapse_change fired through CollapsableFrame NOTIFY hook")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
