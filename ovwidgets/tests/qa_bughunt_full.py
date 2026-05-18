# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Full interactive QA bug-hunt for OvGear.

Runs one of 12 QA sessions per invocation, driving the real Application
with a real USD stage, capturing before/after screenshots for every
interaction.  Screenshots land under ``/tmp/qa-hunt/`` tagged with the
session name + sequential index.

Usage::

    LD_LIBRARY_PATH=... python3.12 tests/qa_bughunt_full.py <session>

Sessions:
    s01_basic_attrs      — Basic Scene Property Inspector
    s02_complex_attrs    — Multi-type attribute coverage
    s03_selection        — Rapid selection changes
    s04_tree_ops         — Tree expand / collapse
    s05_create_delete    — Prim create / delete
    s06_sublayers        — Sublayer add / remove / readd
    s07_resize           — Window resize + split drag
    s08_large_stage      — 100+ prim stress
    s09_default_prim     — Default prim operations
    s10_multi_select     — Multi-selection property display
    s11_prop_filter      — Property filter / search
    s12_group_collapse   — Group collapse / expand
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

import omni.ui as ui
from omni.ui import testing as uitesting
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus

SESSION = sys.argv[1] if len(sys.argv) > 1 else "s01_basic_attrs"
SHOT_DIR = Path("/tmp/qa-hunt")
SHOT_DIR.mkdir(parents=True, exist_ok=True)
_counter = [0]


def shoot(label: str) -> str:
    _counter[0] += 1
    path = SHOT_DIR / f"{SESSION}_{_counter[0]:03d}_{label}.png"
    ok = uitesting.capture_screenshot(str(path))
    print(f"  shot {_counter[0]:03d} {label:>36}  ok={ok}  -> {path}")
    return str(path)


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


# ---------------------------------------------------------------------------
# USD scene builders — return path to a saved .usda file
# ---------------------------------------------------------------------------

_tmpdir = Path(tempfile.mkdtemp(prefix="qa_bughunt_"))


def _save(stage: Usd.Stage, name: str) -> str:
    path = str(_tmpdir / f"{name}.usda")
    stage.Export(path)
    return path


def _build_basic_scene() -> str:
    """Cube + Sphere + Camera under /World."""
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    cube = UsdGeom.Cube.Define(stage, "/World/Cube")
    cube.GetPrim().CreateAttribute("size", Sdf.ValueTypeNames.Double).Set(2.0)
    UsdGeom.XformCommonAPI(cube).SetTranslate(Gf.Vec3d(-2.0, 0.0, 0.0))

    sphere = UsdGeom.Sphere.Define(stage, "/World/Sphere")
    sphere.GetPrim().CreateAttribute("radius", Sdf.ValueTypeNames.Double).Set(1.0)
    UsdGeom.XformCommonAPI(sphere).SetTranslate(Gf.Vec3d(2.0, 0.0, 0.0))

    cam = UsdGeom.Camera.Define(stage, "/World/Camera")
    UsdGeom.XformCommonAPI(cam).SetTranslate(Gf.Vec3d(0.0, 2.0, 5.0))

    return _save(stage, "basic")


def _build_complex_scene() -> str:
    """Scene covering most attribute types under /World."""
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    # Mesh with attributes.
    mesh = UsdGeom.Mesh.Define(stage, "/World/Mesh")
    mesh.CreatePointsAttr([
        Gf.Vec3f(0, 0, 0), Gf.Vec3f(1, 0, 0),
        Gf.Vec3f(1, 1, 0), Gf.Vec3f(0, 1, 0),
    ])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    mesh.GetPrim().CreateAttribute(
        "custom:label", Sdf.ValueTypeNames.String
    ).Set("my mesh")
    mesh.GetPrim().CreateAttribute(
        "custom:count", Sdf.ValueTypeNames.Int
    ).Set(42)
    mesh.GetPrim().CreateAttribute(
        "custom:color3f", Sdf.ValueTypeNames.Color3f
    ).Set(Gf.Vec3f(0.8, 0.2, 0.4))
    mesh.GetPrim().CreateAttribute(
        "custom:color4f", Sdf.ValueTypeNames.Color4f
    ).Set(Gf.Vec4f(0.2, 0.4, 0.8, 1.0))
    mesh.GetPrim().CreateAttribute(
        "custom:vec2", Sdf.ValueTypeNames.Float2
    ).Set(Gf.Vec2f(0.3, 0.7))
    mesh.GetPrim().CreateAttribute(
        "custom:vec4", Sdf.ValueTypeNames.Float4
    ).Set(Gf.Vec4f(1, 2, 3, 4))
    mesh.GetPrim().CreateAttribute(
        "custom:matrix", Sdf.ValueTypeNames.Matrix4d
    ).Set(Gf.Matrix4d(1.0))
    mesh.GetPrim().CreateAttribute(
        "custom:flag", Sdf.ValueTypeNames.Bool
    ).Set(True)
    mesh.GetPrim().CreateAttribute(
        "custom:tokenval", Sdf.ValueTypeNames.Token
    ).Set("alpha")
    mesh.GetPrim().CreateAttribute(
        "custom:assetpath", Sdf.ValueTypeNames.Asset
    ).Set(Sdf.AssetPath("textures/brick.png"))
    mesh.GetPrim().CreateAttribute(
        "custom:intarr", Sdf.ValueTypeNames.IntArray
    ).Set([1, 2, 3, 4, 5])

    # Light with color.
    light = UsdLux.SphereLight.Define(stage, "/World/Light")
    light.CreateColorAttr(Gf.Vec3f(1.0, 0.9, 0.8))
    light.CreateIntensityAttr(500.0)

    # Camera.
    cam = UsdGeom.Camera.Define(stage, "/World/Cam")
    UsdGeom.XformCommonAPI(cam).SetTranslate(Gf.Vec3d(0.0, 2.0, 5.0))

    # Xform wrapper with a scope.
    wrapper = UsdGeom.Xform.Define(stage, "/World/Wrapper")
    UsdGeom.Scope.Define(stage, "/World/Wrapper/Scope")

    # Relationship — mesh → light.
    mesh.GetPrim().CreateRelationship("custom:look_at").AddTarget("/World/Light")

    return _save(stage, "complex")


def _build_nested_scene(depth: int = 4) -> str:
    """Deep hierarchy so tree operations have meaningful depth."""
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    path = "/World"
    for i in range(depth):
        path = f"{path}/Level{i}"
        UsdGeom.Xform.Define(stage, path)
        UsdGeom.Cube.Define(stage, f"{path}/Cube{i}")
        UsdGeom.Sphere.Define(stage, f"{path}/Sphere{i}")
    return _save(stage, "nested")


def _build_large_scene(n: int = 150) -> str:
    """150 prims for large-stage stress."""
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    groups = 10
    per = n // groups
    for g in range(groups):
        gpath = f"/World/Group_{g}"
        UsdGeom.Xform.Define(stage, gpath)
        for i in range(per):
            UsdGeom.Cube.Define(stage, f"{gpath}/Cube_{i:03d}")
    return _save(stage, "large")


def _build_multiselect_scene() -> str:
    """Set of prims with mixed types for multi-select tests."""
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    # Same-type group.
    for i in range(3):
        c = UsdGeom.Cube.Define(stage, f"/World/Cube{i}")
        UsdGeom.XformCommonAPI(c).SetTranslate(Gf.Vec3d(i * 2.0, 0, 0))
    # Different-type group.
    UsdGeom.Sphere.Define(stage, "/World/Sphere0")
    UsdLux.SphereLight.Define(stage, "/World/Light0")
    UsdGeom.Camera.Define(stage, "/World/Cam0")
    # A bag of prims for large-selection tests.
    bag = UsdGeom.Xform.Define(stage, "/World/Bag")
    for i in range(150):
        UsdGeom.Cube.Define(stage, f"/World/Bag/B_{i:03d}")
    return _save(stage, "multiselect")


def _build_group_scene() -> str:
    """Scene with grouped xformOps — exercises nested property groups."""
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    x = UsdGeom.Xform.Define(stage, "/World/Target")
    api = UsdGeom.XformCommonAPI(x)
    api.SetTranslate(Gf.Vec3d(1, 2, 3))
    api.SetRotate(Gf.Vec3f(15, 30, 45))
    api.SetScale(Gf.Vec3f(1.5, 2.0, 2.5))
    # Add a few extras for filter / grouping behavior.
    x.GetPrim().CreateAttribute("custom:alpha", Sdf.ValueTypeNames.Float).Set(0.5)
    x.GetPrim().CreateAttribute("custom:beta", Sdf.ValueTypeNames.Int).Set(7)
    x.GetPrim().CreateAttribute("custom:label", Sdf.ValueTypeNames.String).Set("tag")
    return _save(stage, "group_scene")


# ---------------------------------------------------------------------------
# Harness bootstrap
# ---------------------------------------------------------------------------

async def _launch(usd_path: Optional[str] = None) -> Application:
    Application._instance = None
    SelectionBus._instance = None
    app = Application()
    app._running = True
    app._startup_usd_path = usd_path
    asyncio.ensure_future(app.run_async())
    await _drive(40)
    return app


async def _expand_all(app: Application) -> None:
    """Expand the Stage Browser tree to several levels."""
    sw = app._stage_window
    if sw is None or sw._widget is None:
        return
    widget = sw._widget
    adapter = widget._adapter
    if adapter is None:
        return
    try:
        root = adapter.get_root()
        widget.expand(adapter.get_item_path(root))
        # World is first child, expand it and descendants for a few levels.
        for _ in range(6):
            # Snapshot the currently materialised paths and expand them.
            paths = list(widget._model._expanded_paths)
            more = []
            for p in paths:
                for child in adapter.get_children(adapter.get_item(p)) if hasattr(adapter, "get_item") else []:
                    cp = adapter.get_item_path(child)
                    widget.expand(cp)
                    more.append(cp)
            if not more:
                break
    except Exception:
        pass


async def _expand_via_model(app: Application) -> None:
    """Alternate expander walking the model's tree nodes."""
    sw = app._stage_window
    if sw is None or sw._widget is None:
        return
    widget = sw._widget
    adapter = widget._adapter
    if adapter is None:
        return
    try:
        root_item = widget._model._root
        # Root is always auto-expanded; expand named root via path too.
        widget.expand(adapter.get_item_path(adapter.get_root()))
        queue = [root_item]
        depth = 0
        while queue and depth < 8:
            nextq = []
            for node in queue:
                try:
                    for ch in widget._model.get_item_children(node):
                        p = adapter.get_item_path(ch.adapter_item)
                        widget.expand(p)
                        nextq.append(ch)
                except Exception:
                    pass
            queue = nextq
            depth += 1
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

async def session_01_basic_attrs() -> None:
    """Select Cube / Sphere / Camera and verify property inspector updates."""
    app = await _launch(_build_basic_scene())
    await _expand_via_model(app)
    await _drive(15)
    shoot("initial")

    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(15)
    shoot("cube_selected")

    app.selection_bus.publish(["/World/Sphere"], source="qa")
    await _drive(15)
    shoot("sphere_selected")

    app.selection_bus.publish(["/World/Camera"], source="qa")
    await _drive(15)
    shoot("camera_selected")

    app.selection_bus.publish([], source="qa")
    await _drive(10)
    shoot("selection_cleared")


async def session_02_complex_attrs() -> None:
    """Verify every attribute type renders in the inspector."""
    app = await _launch(_build_complex_scene())
    await _expand_via_model(app)
    await _drive(15)
    shoot("initial")

    app.selection_bus.publish(["/World/Mesh"], source="qa")
    await _drive(20)
    shoot("mesh_selected_all_types")

    app.selection_bus.publish(["/World/Light"], source="qa")
    await _drive(15)
    shoot("light_selected")

    app.selection_bus.publish(["/World/Cam"], source="qa")
    await _drive(15)
    shoot("camera_selected")

    app.selection_bus.publish(["/World/Wrapper/Scope"], source="qa")
    await _drive(15)
    shoot("scope_selected")


async def session_03_selection() -> None:
    """Rapid selection changes — ensure inspector refreshes cleanly."""
    app = await _launch(_build_nested_scene(depth=4))
    await _expand_via_model(app)
    await _drive(15)
    shoot("initial")

    targets = [
        "/World/Level0",
        "/World/Level0/Cube0",
        "/World/Level0/Level1",
        "/World/Level0/Level1/Sphere1",
        "/World/Level0/Level1/Level2",
        "/World/Level0/Level1/Level2/Cube2",
        "/World/Level0/Level1/Level2/Level3",
    ]
    for t in targets:
        app.selection_bus.publish([t], source="qa")
        await _drive(10)
        label = t.replace("/", "_").strip("_")
        shoot(f"sel_{label}")

    app.selection_bus.publish([], source="qa")
    await _drive(10)
    shoot("cleared")


async def session_04_tree_ops() -> None:
    """Expand / collapse root, nested expansions, verify tree fidelity."""
    app = await _launch(_build_nested_scene(depth=4))
    await _drive(15)
    shoot("initial_collapsed")

    await _expand_via_model(app)
    await _drive(10)
    shoot("all_expanded")

    sw = app._stage_window
    widget = sw._widget
    # Collapse at /World.
    widget.collapse("/World")
    await _drive(8)
    shoot("world_collapsed")

    widget.expand("/World")
    await _drive(8)
    shoot("world_reexpanded")

    # Collapse deep.
    widget.collapse("/World/Level0/Level1/Level2")
    await _drive(8)
    shoot("level2_collapsed")

    widget.expand("/World/Level0/Level1/Level2")
    await _drive(8)
    shoot("level2_reexpanded")


async def session_05_create_delete() -> None:
    """Create and delete prims via USD, verify tree reflects changes."""
    app = await _launch(_build_basic_scene())
    await _expand_via_model(app)
    await _drive(15)
    shoot("initial")

    stage = app._stage_adapter.stage

    UsdGeom.Cone.Define(stage, "/World/NewCone")
    await _drive(15)
    shoot("cone_added")

    UsdGeom.Xform.Define(stage, "/World/Group")
    UsdGeom.Cube.Define(stage, "/World/Group/Child1")
    UsdGeom.Sphere.Define(stage, "/World/Group/Child2")
    await _drive(15)
    await _expand_via_model(app)
    await _drive(10)
    shoot("group_with_children_added")

    stage.RemovePrim("/World/NewCone")
    await _drive(15)
    shoot("cone_removed")

    stage.RemovePrim("/World/Group")
    await _drive(15)
    shoot("group_removed")


async def session_06_sublayers() -> None:
    """Sublayer add / remove / re-add."""
    app = await _launch(_build_basic_scene())
    await _expand_via_model(app)
    await _drive(15)
    shoot("initial")

    stage = app._stage_adapter.stage

    sub_path = str(_tmpdir / "sublayer.usda")
    sub_stage = Usd.Stage.CreateNew(sub_path)
    UsdGeom.Xform.Define(sub_stage, "/World")
    UsdGeom.Cone.Define(sub_stage, "/World/SubCone")
    UsdGeom.Cylinder.Define(sub_stage, "/World/SubCylinder")
    sub_stage.GetRootLayer().Save()
    del sub_stage

    stage.GetRootLayer().subLayerPaths.append(sub_path)
    await _drive(15)
    await _expand_via_model(app)
    await _drive(10)
    shoot("sublayer_added")

    stage.GetRootLayer().subLayerPaths.clear()
    await _drive(15)
    shoot("sublayer_removed")

    stage.GetRootLayer().subLayerPaths.append(sub_path)
    await _drive(15)
    await _expand_via_model(app)
    await _drive(10)
    shoot("sublayer_readded")


async def session_07_resize() -> None:
    """Window resize — drag splitters, resize app window."""
    app = await _launch(_build_basic_scene())
    await _expand_via_model(app)
    await _drive(15)
    shoot("initial_1280x720")

    # Drag vertical splitter (between stage browser and viewport) inward.
    await uitesting.mouse_drag(360, 380, 210, 380, steps=16)
    await _drive(8)
    shoot("splitter_narrowed")

    await uitesting.mouse_drag(210, 380, 540, 380, steps=16)
    await _drive(8)
    shoot("splitter_widened")

    # Drag horizontal splitter (between viewport and property).
    await uitesting.mouse_drag(900, 420, 900, 240, steps=16)
    await _drive(8)
    shoot("property_enlarged_vertically")

    await uitesting.mouse_drag(900, 240, 900, 600, steps=16)
    await _drive(8)
    shoot("property_shrunk_vertically")

    # Reset.
    await uitesting.mouse_drag(540, 380, 360, 380, steps=12)
    await uitesting.mouse_drag(900, 600, 900, 420, steps=12)
    await _drive(8)
    shoot("reset_split")


async def session_08_large_stage() -> None:
    """150 prims — verify tree + inspector hold up."""
    app = await _launch(_build_large_scene(150))
    await _expand_via_model(app)
    await _drive(20)
    shoot("large_expanded")

    # Select a mid-depth prim.
    app.selection_bus.publish(["/World/Group_5/Cube_007"], source="qa")
    await _drive(15)
    shoot("mid_selected")

    # Select a deep-bottom prim.
    app.selection_bus.publish(["/World/Group_9/Cube_014"], source="qa")
    await _drive(15)
    shoot("bottom_selected")

    # Scroll inside the stage browser.
    await uitesting.mouse_scroll(180, 400, dx=0, dy=-10)
    await _drive(8)
    shoot("scrolled_down")

    # Filter via the widget API.
    sw = app._stage_window
    if sw and sw._widget:
        sw._widget.filter_by_text("Cube_005")
    await _drive(12)
    shoot("filter_cube_005")

    if sw and sw._widget:
        sw._widget.filter_by_text("")
    await _drive(12)
    shoot("filter_cleared")


async def session_09_default_prim() -> None:
    """Default prim — change, clear, set."""
    app = await _launch(_build_basic_scene())
    await _expand_via_model(app)
    await _drive(15)
    shoot("initial_default_world")

    stage = app._stage_adapter.stage
    stage.ClearDefaultPrim()
    await _drive(15)
    shoot("default_cleared")

    stage.SetDefaultPrim(stage.GetPrimAtPath("/World"))
    await _drive(15)
    shoot("default_set_world_again")


async def session_10_multi_select() -> None:
    """Multi-select — same type, different types, large selection."""
    app = await _launch(_build_multiselect_scene())
    await _expand_via_model(app)
    await _drive(15)
    shoot("initial")

    # Same-type (3 cubes).
    app.selection_bus.publish(
        ["/World/Cube0", "/World/Cube1", "/World/Cube2"], source="qa",
    )
    await _drive(15)
    shoot("three_cubes_selected")

    # Different types (cube + sphere + light).
    app.selection_bus.publish(
        ["/World/Cube0", "/World/Sphere0", "/World/Light0"], source="qa",
    )
    await _drive(15)
    shoot("three_mixed_types_selected")

    # Large selection — 120 cubes from the bag.
    big = [f"/World/Bag/B_{i:03d}" for i in range(120)]
    app.selection_bus.publish(big, source="qa")
    await _drive(15)
    shoot("large_selection_gate")

    # Click "Load Anyway" programmatically.
    pw = app._property_window
    if pw is not None and getattr(pw, "_large_selection_override", False) is False:
        pw._on_ignore_threshold_clicked()
    await _drive(15)
    shoot("large_selection_loaded_anyway")


async def session_11_prop_filter() -> None:
    """Property filter / search."""
    app = await _launch(_build_group_scene())
    await _expand_via_model(app)
    await _drive(15)
    app.selection_bus.publish(["/World/Target"], source="qa")
    await _drive(15)
    shoot("target_selected")

    pw = app._property_window
    if pw is None or pw._filter_field is None:
        return

    pw._filter_field.model.set_value("Transl")
    await _drive(25)
    shoot("filter_transl")

    pw._filter_field.model.set_value("alpha")
    await _drive(25)
    shoot("filter_alpha")

    pw._filter_field.model.set_value("zzzzz_no_match")
    await _drive(25)
    shoot("filter_no_match")

    pw._filter_field.model.set_value("")
    await _drive(25)
    shoot("filter_cleared")


async def session_12_group_collapse() -> None:
    """Collapse / expand property groups."""
    app = await _launch(_build_group_scene())
    await _expand_via_model(app)
    await _drive(15)
    app.selection_bus.publish(["/World/Target"], source="qa")
    await _drive(15)
    shoot("target_all_groups_expanded")

    pw = app._property_window
    if pw is None:
        return

    # Collapse 'Transform' group via the persisted state map.
    pw._group_collapse_state["Transform"] = True
    pw._rebuild_content()
    await _drive(15)
    shoot("transform_group_collapsed")

    # Collapse everything.
    pw._group_collapse_state["Transform"] = True
    pw._group_collapse_state["Geometry"] = True
    pw._group_collapse_state["Display"] = True
    pw._rebuild_content()
    await _drive(15)
    shoot("all_groups_collapsed")

    # Re-expand all.
    for k in list(pw._group_collapse_state.keys()):
        pw._group_collapse_state[k] = False
    pw._rebuild_content()
    await _drive(15)
    shoot("all_groups_reexpanded")


_SESSIONS: dict[str, Callable] = {
    "s01_basic_attrs":     session_01_basic_attrs,
    "s02_complex_attrs":   session_02_complex_attrs,
    "s03_selection":       session_03_selection,
    "s04_tree_ops":        session_04_tree_ops,
    "s05_create_delete":   session_05_create_delete,
    "s06_sublayers":       session_06_sublayers,
    "s07_resize":          session_07_resize,
    "s08_large_stage":     session_08_large_stage,
    "s09_default_prim":    session_09_default_prim,
    "s10_multi_select":    session_10_multi_select,
    "s11_prop_filter":     session_11_prop_filter,
    "s12_group_collapse":  session_12_group_collapse,
}


async def _main() -> None:
    fn = _SESSIONS.get(SESSION)
    if fn is None:
        print(f"ERROR: unknown session {SESSION}. known={list(_SESSIONS)}")
        ui.shutdown()
        sys.exit(1)
    try:
        await fn()
    except Exception as e:
        import traceback
        print(f"SESSION FAILED: {e}")
        traceback.print_exc()
        try:
            shoot("failure")
        except Exception:
            pass
        ui.shutdown()
        sys.exit(2)

    ui.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init(f"OvGear QA Bug-Hunt [{SESSION}]", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())
