# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 1.3 visual QA: confirm the property panel still renders after the
``build_attribute_row`` → ``WidgetBuilderTable.build`` swap.

Step 1.3 is labelled "not a visual step" in the property inspector implementation (the dispatch
swap preserves the exact same row classes). This script captures a single
screenshot as a smoke check that the panel rebuilds end-to-end through the
new dispatch path.

Also installs a spy on ``WidgetBuilderTable.build`` before the rebuild so
we can prove the new dispatch path actually fired (a regression would
still render the panel — the row classes are shared — but the spy would
see zero calls).

Run:
  LD_LIBRARY_PATH=<path-to-ovui>/python/omni/ui:<path-to-ovui>/python/omni/ui_scene \
    python3.12 tests/verify_step1_3.py
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
from ovwidgets.property.builders import WidgetBuilderTable
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


# Spy wrapper around WidgetBuilderTable.build to prove the new dispatch fires.
_build_calls: list = []
_original_build = WidgetBuilderTable.build.__func__  # underlying function


def _spy_build(cls, attr_name, metadata, adapter, **kwargs):
    _build_calls.append((attr_name, metadata.type_name))
    return _original_build(cls, attr_name, metadata, adapter, **kwargs)


WidgetBuilderTable.build = classmethod(_spy_build)

write_split_ini()
ui.init("OvGear Step 1.3 QA", width=1280, height=720)
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

    testing.capture_screenshot("/tmp/ovgear_step1_3_1.png")
    print("Screenshot: /tmp/ovgear_step1_3_1.png")

    # Invariant 1: the spy saw one WidgetBuilderTable.build call per attribute.
    # Seven attrs defined in _make_adapter (3 vec3 + 2 token + 1 bool + 1 float)
    # all go through the table now. The property panel would still render even
    # if we had reverted the swap (the row classes are shared), so this spy is
    # the test that catches a silent revert.
    names = [name for name, _ in _build_calls]
    types = [type_name for _, type_name in _build_calls]
    assert len(_build_calls) == 7, (
        f"Expected 7 WidgetBuilderTable.build calls (one per attr), "
        f"got {len(_build_calls)}: {_build_calls}"
    )
    assert "xformOp:translate" in names
    assert "radius" in names
    assert "double3" in types and "float3" in types and "float" in types
    print(
        f"OK: WidgetBuilderTable.build fired {len(_build_calls)} times; "
        f"types dispatched = {sorted(set(types))}"
    )

    # Invariant 2: the legacy _VEC3_TYPE_NAMES frozenset is gone from
    # attribute_row.py (Step 1.2 promised this; Step 1.3 executes the removal).
    import ovwidgets.property.attribute_row as _ar
    assert not hasattr(_ar, "_VEC3_TYPE_NAMES"), (
        "_VEC3_TYPE_NAMES should have been deleted in Step 1.3"
    )
    print("OK: attribute_row._VEC3_TYPE_NAMES removed")

    # Invariant 3: build_attribute_row still works as a forwarder.
    from ovwidgets.common.testing.mock_property import MockPropertyAdapter as _MPA
    forward_calls_before = len(_build_calls)
    meta = AttributeMetadata("foo", "Foo", "float", float, "G")
    # Off-screen — don't need a Window context; just confirm dispatch.
    # The row's _build_ui will try to build ui.Label/FloatDrag; skip it.
    import ovwidgets.property.attribute_row as _ar_module
    from ovwidgets.property.attribute_row import build_attribute_row
    _ar_module.FloatAttributeRow._build_ui = lambda self: None  # type: ignore[method-assign]
    build_attribute_row(meta, _MPA(paths=["/p"]))
    assert len(_build_calls) == forward_calls_before + 1, (
        "build_attribute_row forwarder did not route through WidgetBuilderTable.build"
    )
    print("OK: build_attribute_row forwarder routes through WidgetBuilderTable.build")

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
