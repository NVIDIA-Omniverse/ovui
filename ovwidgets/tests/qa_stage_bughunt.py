# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""QA bug-hunt driver for the Stage window (qa/stage-bug-hunt).

Drives each scenario as a standalone omni.ui run so the harness stays
shaped like tests/qa_design_screenshot.py.  Each invocation:

    LD_LIBRARY_PATH=... python3.12 tests/qa_stage_bughunt.py <scenario>

Where <scenario> is one of the names in _SCENARIOS.  Screenshots are
written to /tmp/ovgear_qa_<scenario>_*.png.

The scenarios emulate a real user by injecting mouse/keyboard events
via omni.ui.testing.*; they take before/after screenshots for each
action so bugs are visible in the PNG stream.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui
from omni.ui import color as cl_color
from omni.ui import testing
from ovui_data_adapters.common import AttributeMetadata, BadgeFlags, ItemFlags
from ovwidgets.property.property_widget import PropertyWidget

from ovwidgets.app.layout import apply_default_layout, write_split_ini
from ovwidgets.app.menu_bar import build_menu_bar
from ovwidgets.app.status_bar import StatusBar
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_property import MockPropertyAdapter
from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.common.testing.mock_stage import MockStageAdapter, _MockItem
from ovwidgets.stage.window import StageWindow
from ovwidgets.viewport.viewport_widget import ViewportWidget

SCENARIO = sys.argv[1] if len(sys.argv) > 1 else "s1_basic"
SHOT_DIR = Path("/tmp")
_counter = [0]


def shoot(label: str) -> str:
    _counter[0] += 1
    path = SHOT_DIR / f"ovgear_qa_{SCENARIO}_{_counter[0]:03d}_{label}.png"
    ok = testing.capture_screenshot(str(path))
    print(f"  shot {_counter[0]:03d} {label:>30}  ok={ok}  -> {path}")
    return str(path)


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
        self._recent_files = type("_RF", (), {"get_ordered": lambda self: []})()


# ── Scene builders ───────────────────────────────────────────────────────

def _build_basic_adapter() -> MockStageAdapter:
    """~10 prims: default tree + a few extras."""
    a = MockStageAdapter()
    root = a.get_root()
    a.add_child("/World", "Extra1", "Mesh")
    a.add_child("/World", "Extra2", "Scope")
    return a


def _build_large_adapter(n: int = 250) -> MockStageAdapter:
    """Deep nested hierarchy with n leaf prims."""
    a = MockStageAdapter()
    # Wipe and rebuild.
    a._root = _MockItem(path="/World", name="World", prim_type="Xform")
    # Build a branching hierarchy: 5 groups, each with nested sub-groups.
    GROUPS = 5
    PER_GROUP = n // GROUPS
    for g in range(GROUPS):
        grp = _MockItem(
            path=f"/World/Group_{g}",
            name=f"Group_{g}",
            prim_type="Xform",
            parent=a._root,
        )
        a._root.children.append(grp)
        # Create a nested sub-group for depth.
        sub = _MockItem(
            path=f"/World/Group_{g}/Sub",
            name="Sub",
            prim_type="Xform",
            parent=grp,
        )
        grp.children.append(sub)
        for i in range(PER_GROUP):
            leaf = _MockItem(
                path=f"/World/Group_{g}/Sub/Leaf_{i:03d}",
                name=f"Leaf_{i:03d}",
                prim_type="Mesh" if i % 3 else "Light",
                parent=sub,
            )
            sub.children.append(leaf)
    return a


def _build_varied_names_adapter() -> MockStageAdapter:
    """Scene with varied prim names for filter tests."""
    a = MockStageAdapter()
    a._root = _MockItem(path="/World", name="World", prim_type="Xform")
    names = [
        ("HeroCharacter",   "Mesh"),
        ("HeroWeapon",      "Mesh"),
        ("VillainCharacter","Mesh"),
        ("KeyLight",        "Light"),
        ("FillLight",       "Light"),
        ("RimLight",        "Light"),
        ("MainCam",         "Camera"),
        ("WideCam",         "Camera"),
        ("Props",           "Scope"),
        ("Environment",     "Xform"),
    ]
    for nm, tp in names:
        it = _MockItem(
            path=f"/World/{nm}",
            name=nm,
            prim_type=tp,
            parent=a._root,
        )
        a._root.children.append(it)
    return a


def _build_complex_adapter() -> MockStageAdapter:
    """Scene exercising every composition badge + state flag."""
    a = MockStageAdapter()
    a._item_flags_overrides = {
        "/World/Geometry/Ground": ItemFlags.IS_DEFAULT_PRIM,
        "/World/Geometry/Cube":   ItemFlags.IS_INACTIVE,
        "/World/Lights/DomeLight": ItemFlags.IS_CLASS,
        "/World/Camera":          ItemFlags.IS_INSTANCE_PROXY,
    }
    a._badge_flags_overrides = {
        "/World/Geometry/Sphere":  BadgeFlags.REFERENCE,
        "/World/Geometry/Ground":  BadgeFlags.PAYLOAD,
        "/World/Camera":           BadgeFlags.INSTANCE,
        "/World/Lights/DomeLight": BadgeFlags.INHERITS,
    }
    return a


def _build_empty_adapter() -> MockStageAdapter:
    """A 'World' root with no children — empty scene."""
    a = MockStageAdapter()
    a._root = _MockItem(path="/World", name="World", prim_type="Xform")
    return a


# ── Bootstrap ────────────────────────────────────────────────────────────

_app = _FakeApp()
write_split_ini()
ui.init("OvGear QA", width=1280, height=720)
apply_global_styles()
set_theme("dark")

_main_win = ui.Window(
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

with _main_win.frame:
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

# Choose adapter based on scenario.
if SCENARIO.startswith("s1"):
    _adapter = _build_basic_adapter()
elif SCENARIO.startswith("s2"):
    _adapter = _build_large_adapter(250)
elif SCENARIO.startswith("s3"):
    _adapter = _build_varied_names_adapter()
elif SCENARIO.startswith("s4"):
    _adapter = _build_basic_adapter()
elif SCENARIO.startswith("s5"):
    _adapter = _build_complex_adapter()
elif SCENARIO.startswith("s6"):
    _adapter = _build_basic_adapter()
elif SCENARIO.startswith("s7"):
    _adapter = _build_basic_adapter()
else:
    _adapter = MockStageAdapter()

_stage_win = StageWindow(adapter=_adapter)
_prop_window = PropertyWidget()
_vp_window = ViewportWidget(services=_app, renderer=_renderer, bus=_bus)


def _make_mock_property_adapter(paths):
    attrs = {
        "xformOp:translate": AttributeMetadata(
            name="xformOp:translate", display_name="Translate",
            type_name="double3", value_type=float, group="Transform",
        ),
        "visibility": AttributeMetadata(
            name="visibility", display_name="Visibility",
            type_name="token", value_type=str, group="Display",
        ),
    }
    return MockPropertyAdapter(paths=paths, attributes=attrs)


def _expand_first_levels() -> None:
    widget = _stage_win._widget
    if widget is None:
        return
    # Expand root and its immediate children.
    widget.expand("/World")
    root = widget._model._root
    # Force children to load
    for ch in widget._model.get_item_children(root):
        try:
            path = widget._adapter.get_item_path(ch.adapter_item)
            widget.expand(path)
        except Exception:
            pass


# ── Scenario routines ───────────────────────────────────────────────────

async def scenario_s1_basic(app) -> None:
    """Basic USD file — render, selection, visibility toggle, expand/collapse."""
    _expand_first_levels()
    await testing.wait_frames(10)
    shoot("initial_expanded")

    # Collapse World.
    _stage_win._widget.collapse("/World")
    await testing.wait_frames(5)
    shoot("world_collapsed")

    # Re-expand.
    _stage_win._widget.expand("/World")
    await testing.wait_frames(5)
    shoot("world_reexpanded")

    _expand_first_levels()
    await testing.wait_frames(5)

    # Click on Sphere row. From the baseline screenshot the tree starts at
    # x~=16 (name column) and y=90 is the "World" row. Each row is 22 px,
    # so Sphere is at row index 4 (World, Geometry, Ground, Sphere).
    await testing.mouse_click(80, 158)
    await testing.wait_frames(5)
    shoot("clicked_sphere")

    # Click on DomeLight.
    await testing.mouse_click(110, 224)
    await testing.wait_frames(5)
    shoot("clicked_domelight")

    # Toggle visibility eye on Sphere (column ~x=298).
    await testing.mouse_click(298, 158)
    await testing.wait_frames(5)
    shoot("toggled_sphere_vis")

    # Toggle it back.
    await testing.mouse_click(298, 158)
    await testing.wait_frames(5)
    shoot("toggled_sphere_vis_back")

    # Click on DomeLight eye.
    await testing.mouse_click(298, 224)
    await testing.wait_frames(5)
    shoot("toggled_domelight_vis")


async def scenario_s2_large(app) -> None:
    """200+ prim scene — stress render + scroll."""
    _expand_first_levels()
    # Expand each sub-group to reveal leaves.
    widget = _stage_win._widget
    for g in range(5):
        widget.expand(f"/World/Group_{g}")
        widget.expand(f"/World/Group_{g}/Sub")
    await testing.wait_frames(10)
    shoot("large_initial")

    # Scroll down inside the tree — stage browser lives in left column,
    # so scroll at x=160, y=300.
    await testing.mouse_scroll(160, 300, dx=0, dy=-10)
    await testing.wait_frames(5)
    shoot("scrolled_down_1")

    await testing.mouse_scroll(160, 300, dx=0, dy=-10)
    await testing.wait_frames(5)
    shoot("scrolled_down_2")

    await testing.mouse_scroll(160, 300, dx=0, dy=-15)
    await testing.wait_frames(5)
    shoot("scrolled_down_3")

    # Click a visible item (whatever is currently on screen at y=200).
    await testing.mouse_click(160, 200)
    await testing.wait_frames(5)
    shoot("selected_mid_scroll")

    # Scroll back up.
    await testing.mouse_scroll(160, 300, dx=0, dy=30)
    await testing.wait_frames(5)
    shoot("scrolled_back_up")


async def scenario_s3_filter(app) -> None:
    """Filter/search — varied prim names."""
    _expand_first_levels()
    await testing.wait_frames(8)
    shoot("filter_initial")

    # Use the public API so we exercise the filter pipeline directly.
    _stage_win._widget.filter_by_text("Light")
    await testing.wait_frames(8)
    shoot("filter_light")

    _stage_win._widget.filter_by_text("Hero")
    await testing.wait_frames(8)
    shoot("filter_hero")

    # Filter with no matches.
    _stage_win._widget.filter_by_text("ZZZZZ")
    await testing.wait_frames(8)
    shoot("filter_no_match")

    # Clear
    _stage_win._widget.filter_by_text("")
    await testing.wait_frames(8)
    shoot("filter_cleared")

    # Now do it via clicking the filter field and typing (clicks).
    await testing.mouse_click(120, 38)
    await testing.wait_frames(3)
    shoot("filter_focused")
    await testing.type_text("Cam")
    await testing.wait_frames(8)
    shoot("filter_typed_cam")

    # Click the clear button (x icon at right side of filter bar).
    await testing.mouse_click(296, 38)
    await testing.wait_frames(6)
    shoot("filter_clicked_clear")


async def scenario_s4_resize(app) -> None:
    """Resize scenarios — change the overall window size by drag-resizing the split."""
    _expand_first_levels()
    await testing.wait_frames(8)
    shoot("resize_initial")

    # Drag the vertical split between Stage Browser and Viewport from x=320
    # to x=160 (make stage narrower).
    await testing.mouse_drag(320, 300, 160, 300, steps=16)
    await testing.wait_frames(5)
    shoot("narrow_stage")

    # Drag the split back to the right — make stage wider.
    await testing.mouse_drag(160, 300, 500, 300, steps=16)
    await testing.wait_frames(5)
    shoot("wide_stage")

    # Extremely narrow.
    await testing.mouse_drag(500, 300, 40, 300, steps=20)
    await testing.wait_frames(5)
    shoot("extreme_narrow")

    # Drag horizontal split (between Stage and Property) down — make Stage taller.
    # Default horizontal split is at y=440 (from layout.py).
    await testing.mouse_drag(40, 440, 40, 700, steps=16)
    await testing.wait_frames(5)
    shoot("tall_stage")

    # Shrink Stage vertically.
    await testing.mouse_drag(40, 700, 40, 100, steps=16)
    await testing.wait_frames(5)
    shoot("short_stage")

    # Reset to default.
    await testing.mouse_drag(40, 100, 40, 440, steps=16)
    await testing.mouse_drag(40, 300, 320, 300, steps=16)
    await testing.wait_frames(5)
    shoot("resize_reset")


async def scenario_s5_complex(app) -> None:
    """Complex USD features — badges, inactive, default, class."""
    _expand_first_levels()
    await testing.wait_frames(10)
    shoot("complex_initial")

    # Click on Cube (inactive).
    await testing.mouse_click(100, 180)
    await testing.wait_frames(5)
    shoot("clicked_cube_inactive")

    # Try to toggle eye on Cube (inactive — should be disabled).
    await testing.mouse_click(298, 180)
    await testing.wait_frames(5)
    shoot("toggled_cube_eye_inactive")

    # Click on DomeLight (class).
    await testing.mouse_click(110, 224)
    await testing.wait_frames(5)
    shoot("clicked_domelight_class")

    # Click on Camera (instance proxy).
    await testing.mouse_click(100, 245)
    await testing.wait_frames(5)
    shoot("clicked_camera_instance_proxy")

    # Click on Sphere (reference badge).
    await testing.mouse_click(100, 158)
    await testing.wait_frames(5)
    shoot("clicked_sphere_reference")

    # Click on Ground (default + payload).
    await testing.mouse_click(100, 135)
    await testing.wait_frames(5)
    shoot("clicked_ground_default")


async def scenario_s6_file_switch(app) -> None:
    """Multiple file switching via set_adapter."""
    _expand_first_levels()
    await testing.wait_frames(8)
    shoot("switch_basic")

    # Switch to complex.
    _stage_win.set_adapter(_build_complex_adapter())
    await testing.wait_frames(5)
    _expand_first_levels()
    await testing.wait_frames(8)
    shoot("switch_complex")

    # Switch to large.
    _stage_win.set_adapter(_build_large_adapter(100))
    await testing.wait_frames(5)
    _expand_first_levels()
    await testing.wait_frames(8)
    shoot("switch_large")

    # Switch to empty.
    _stage_win.set_adapter(_build_empty_adapter())
    await testing.wait_frames(5)
    shoot("switch_empty")

    # Switch back to basic.
    _stage_win.set_adapter(_build_basic_adapter())
    await testing.wait_frames(5)
    _expand_first_levels()
    await testing.wait_frames(8)
    shoot("switch_back_to_basic")


async def scenario_s7_rapid(app) -> None:
    """Rapid interaction."""
    _expand_first_levels()
    await testing.wait_frames(8)
    shoot("rapid_initial")

    # Rapid clicks on different rows.
    for i, y in enumerate([90, 113, 135, 158, 180, 201, 224, 245]):
        await testing.mouse_click(100, y)
    await testing.wait_frames(5)
    shoot("rapid_clicked_rows")

    # Rapid eye toggles on Sphere.
    for _ in range(6):
        await testing.mouse_click(298, 158)
    await testing.wait_frames(5)
    shoot("rapid_eye_toggles")

    # Rapid typing in filter via clicking and typing fast.
    await testing.mouse_click(120, 38)
    await testing.wait_frames(2)
    await testing.type_text("Light")
    await testing.wait_frames(1)
    await testing.type_text("Camera")
    await testing.wait_frames(1)
    await testing.type_text("xxxxx")
    await testing.wait_frames(5)
    shoot("rapid_typed")


_SCENARIOS: dict[str, Callable] = {
    "s1_basic":       scenario_s1_basic,
    "s2_large":       scenario_s2_large,
    "s3_filter":      scenario_s3_filter,
    "s4_resize":      scenario_s4_resize,
    "s5_complex":     scenario_s5_complex,
    "s6_fileswitch":  scenario_s6_file_switch,
    "s7_rapid":       scenario_s7_rapid,
}


async def _main() -> None:
    await ui.next_frame()
    apply_default_layout()
    await testing.wait_frames(30)
    _vp_window._on_frame(0.1)
    await testing.wait_frames(4)

    fn = _SCENARIOS.get(SCENARIO)
    if fn is None:
        print(f"ERROR: unknown scenario {SCENARIO}. known={list(_SCENARIOS)}")
        ui.shutdown()
        sys.exit(1)
    try:
        await fn(_app)
    except Exception as e:
        import traceback
        print(f"SCENARIO FAILED: {e}")
        traceback.print_exc()
        shoot("failure")
        ui.shutdown()
        sys.exit(2)

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    ui.run(_main())
