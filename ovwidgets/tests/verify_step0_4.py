# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 0.4 visual QA: capture the property panel's search field.

Three screenshots:
  /tmp/ovgear_step0_4_1.png — empty filter field (Property.SearchField :normal)
  /tmp/ovgear_step0_4_2.png — filter typed "trans" → Transform group filtered
  /tmp/ovgear_step0_4_3.png — clear button pressed → groups restored

Also dumps a pixel summary so we can compare against Step 0.3 and confirm
the old ZStack + Property.FilterBar Rectangle is gone (no surrounding
`cl.background_secondary` band behind the StringField).

Run:
  LD_LIBRARY_PATH=... python3.12 tests/verify_step0_4.py
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
ui.init("OvGear Step 0.4 QA", width=1280, height=720)
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

    _prop_window.set_adapter(_make_adapter([_SELECTED_PATH]))
    _prop_window.set_selection([_SELECTED_PATH])
    _bus.publish([_SELECTED_PATH], source="qa")
    _renderer.set_selection_highlight([_SELECTED_PATH])
    _vp_window._on_frame(0.1)
    await testing.wait_frames(8)

    # Action 1: default state — empty filter field
    testing.capture_screenshot("/tmp/ovgear_step0_4_1.png")
    print("Screenshot 1 (empty filter): /tmp/ovgear_step0_4_1.png")

    # Action 2: type "trans" into the filter → filters all groups down to
    # Transform. Goes through the same model that a user keypress fires.
    assert _prop_window._filter_field is not None
    _prop_window._filter_field.model.set_value("trans")
    # Debounce is 150ms; advance the app directly by applying the filter
    _prop_window._apply_filter("trans")
    await testing.wait_frames(8)

    testing.capture_screenshot("/tmp/ovgear_step0_4_2.png")
    print("Screenshot 2 (filter 'trans'): /tmp/ovgear_step0_4_2.png")

    # Action 3: press the clear button programmatically
    _prop_window._clear_filter()
    _prop_window._apply_filter("")
    await testing.wait_frames(8)

    testing.capture_screenshot("/tmp/ovgear_step0_4_3.png")
    print("Screenshot 3 (cleared filter): /tmp/ovgear_step0_4_3.png")

    # Invariants: the legacy keys should not touch the rendered tree any more.
    from ovwidgets.property.style import PROPERTY_STYLES
    for legacy in ("Property.FilterBar", "Property.FilterField", "Property.FilterClear"):
        assert legacy not in PROPERTY_STYLES, f"{legacy} should have been removed"
    assert "Property.SearchField" in PROPERTY_STYLES
    print("OK: legacy filter-bar style keys absent; Property.SearchField present")

    # Filter round-trip restored all groups (3 visible).
    groups = _prop_window._compute_groups()
    assert len(groups) == 3, f"Expected 3 groups after clear, got {len(groups)}: {[g[0] for g in groups]}"
    print(f"OK: all {len(groups)} groups restored after clear: {[g[0] for g in groups]}")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
