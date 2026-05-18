# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""DEEP QA bug-hunt for the Stage window (round 2).

Drives a real ``Usd.Stage`` through ``UsdStageAdapter`` and performs USD
mutations via the ``pxr`` API. After each mutation the driver pumps ovui
frames so the adapter's deferred ``_schedule_flush`` runs, then captures
a screenshot. Scenarios cover create/delete/rename/reparent/sublayer/
references, payloads, instancing, default prims, visibility, selection,
inactive prims, classes, stress, and edge cases.

Run one scenario per invocation:
    LD_LIBRARY_PATH=... python3.12 tests/qa_stage_deepbughunt.py <scenario>

Where ``<scenario>`` is one of the keys in ``_SCENARIOS`` below. Screenshots
land under ``/tmp/ovgear_qa2_<scenario>_NNN_<label>.png``.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui
from omni.ui import color as cl_color
from omni.ui import testing
from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
from pxr import Sdf, Usd, UsdGeom, UsdLux

from ovwidgets.app.application import Application
from ovwidgets.app.layout import apply_default_layout, write_split_ini
from ovwidgets.app.menu_bar import build_menu_bar
from ovwidgets.app.status_bar import StatusBar
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.undo import UndoManager
from ovwidgets.stage.window import StageWindow

SCENARIO = sys.argv[1] if len(sys.argv) > 1 else "a_crud"
SHOT_DIR = Path("/tmp")
_counter = [0]


def shoot(label: str) -> str:
    _counter[0] += 1
    path = SHOT_DIR / f"ovgear_qa2_{SCENARIO}_{_counter[0]:03d}_{label}.png"
    ok = testing.capture_screenshot(str(path))
    print(f"  shot {_counter[0]:03d} {label:>40}  ok={ok}  -> {path}")
    return str(path)


# ── Bootstrap ──────────────────────────────────────────────────────────────

SelectionBus._instance = None
_bus = SelectionBus.instance()
_undo = UndoManager()


class _FakeApp:
    """Minimal Application stand-in. Owns call_later so the adapter can
    schedule its flush against a real frame tick."""

    def __init__(self) -> None:
        self.undo_manager = _undo
        self.selection_bus = _bus
        self._pending: list = []
        self._stage_window = None
        self._property_window = None
        self._viewport_window = None
        self._recent_files = type("_RF", (), {"get_ordered": lambda self: []})()

        class _Settings:
            def set(self, k, v): pass

        self.settings = _Settings()

    def call_later(self, delay_secs: float, cb: Callable) -> Any:
        handle = type("_H", (), {"_cb": cb, "_cancelled": False})()
        def _cancel(self=handle): self._cancelled = True
        handle.cancel = _cancel
        self._pending.append(handle)
        return handle

    def pump(self) -> None:
        """Fire all queued call_later callbacks."""
        pending = self._pending
        self._pending = []
        for h in pending:
            if not h._cancelled:
                try:
                    h._cb()
                except Exception as e:
                    print(f"call_later error: {e}")


_app = _FakeApp()
# Application singleton must exist for UsdStageAdapter._schedule_flush.
Application._instance = _app  # type: ignore[assignment]

write_split_ini()
ui.init("OvGear Deep QA", width=1280, height=720)
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

# ── Stage builders ─────────────────────────────────────────────────────────

def _build_basic_stage() -> Usd.Stage:
    """World with a small hierarchy — Geometry/Lights/Camera."""
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdGeom.Xform.Define(stage, "/World/Geometry")
    UsdGeom.Cube.Define(stage, "/World/Geometry/Cube")
    UsdGeom.Sphere.Define(stage, "/World/Geometry/Sphere")
    UsdGeom.Xform.Define(stage, "/World/Lights")
    UsdLux.DomeLight.Define(stage, "/World/Lights/DomeLight")
    UsdGeom.Camera.Define(stage, "/World/Camera")
    return stage


def _build_empty_stage() -> Usd.Stage:
    """No prims at all."""
    return Usd.Stage.CreateInMemory()


def _build_world_only_stage() -> Usd.Stage:
    """A single World root with no children."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    return stage


def _build_deep_stage(depth: int = 20) -> Usd.Stage:
    """Linear hierarchy /World/L0/L1/.../L{depth-1}."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    path = "/World"
    for i in range(depth):
        path = f"{path}/L{i}"
        UsdGeom.Xform.Define(stage, path)
    return stage


def _build_wide_stage(n: int = 120) -> Usd.Stage:
    """World with n direct children."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    for i in range(n):
        UsdGeom.Cube.Define(stage, f"/World/Child_{i:03d}")
    return stage


def _build_large_stage(n: int = 500) -> Usd.Stage:
    """Branching stage with n total leaves."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    groups = 10
    per = n // groups
    for g in range(groups):
        gpath = f"/World/Group_{g}"
        UsdGeom.Xform.Define(stage, gpath)
        for i in range(per):
            UsdGeom.Cube.Define(stage, f"{gpath}/Leaf_{i:03d}")
    return stage


# ── Driver harness ─────────────────────────────────────────────────────────

_stage: Optional[Usd.Stage] = None
_adapter: Optional[UsdStageAdapter] = None
_stage_win: Optional[StageWindow] = None


async def _mount(stage: Usd.Stage) -> None:
    global _stage, _adapter, _stage_win
    _stage = stage
    _adapter = UsdStageAdapter(stage, undo_manager=_undo, call_later=_app.call_later)
    if _stage_win is None:
        _stage_win = StageWindow(adapter=_adapter)
        _app._stage_window = _stage_win
    else:
        _stage_win.set_adapter(_adapter)
    # ManagedWindow lazy-builds via set_build_fn on first frame — wait it out.
    for _ in range(40):
        if _stage_win and _stage_win._widget is not None:
            break
        await testing.next_frame()


async def _settle(frames: int = 10) -> None:
    """Pump ovui frames + Application call_later so adapter flushes propagate."""
    for _ in range(frames):
        _app.pump()
        await testing.next_frame()


def _expand(path: str) -> None:
    if _stage_win and _stage_win._widget:
        _stage_win._widget.expand(path)


def _expand_all_levels(levels: int = 3) -> None:
    """Expand root + first ``levels`` layers of the tree."""
    if not _stage_win or not _stage_win._widget:
        return
    widget = _stage_win._widget
    widget.expand(_adapter.get_item_path(_adapter.get_root()))
    # World is the first real child.
    root = widget._model._root
    widget.expand(_adapter.get_item_path(root.adapter_item))
    queue = list(widget._model.get_item_children(root))
    for _ in range(levels):
        next_layer = []
        for ch in queue:
            try:
                p = _adapter.get_item_path(ch.adapter_item)
                widget.expand(p)
                next_layer.extend(widget._model.get_item_children(ch))
            except Exception:
                pass
        queue = next_layer


def _collapse_all() -> None:
    if not _stage_win or not _stage_win._widget:
        return
    widget = _stage_win._widget
    # Collapse everything by wiping _expanded_paths and issuing a model rebuild.
    widget._model._expanded_paths.clear()
    widget.collapse(_adapter.get_item_path(_adapter.get_root()))


# ── Scenarios ──────────────────────────────────────────────────────────────

async def scenario_a_crud(app) -> None:
    """A. Create and delete prims, with undo."""
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("initial")

    # A1. Create new Xform at root level.
    UsdGeom.Xform.Define(_stage, "/World/Group")
    await _settle()
    shoot("a1_xform_added")

    # A2. Create a mesh under it.
    UsdGeom.Mesh.Define(_stage, "/World/Group/Plate")
    _expand("/World/Group")
    await _settle()
    shoot("a2_mesh_added")

    # A3. Create a camera.
    UsdGeom.Camera.Define(_stage, "/World/Cam2")
    await _settle()
    shoot("a3_camera_added")

    # A4. Create a DistantLight.
    UsdLux.DistantLight.Define(_stage, "/World/SunLight")
    await _settle()
    shoot("a4_distantlight_added")

    # A5. Remove leaf.
    _stage.RemovePrim("/World/Cam2")
    await _settle()
    shoot("a5_camera_removed")

    # A6. Remove parent with children.
    _stage.RemovePrim("/World/Group")
    await _settle()
    shoot("a6_group_removed_with_child")

    # A7. Mutation while collapsed.
    _collapse_all()
    await _settle()
    shoot("a7_collapsed_before_mutation")
    UsdGeom.Cone.Define(_stage, "/World/Geometry/HiddenCone")
    await _settle()
    shoot("a7_collapsed_after_mutation")
    _expand_all_levels()
    await _settle()
    shoot("a7_expanded_shows_cone")


async def scenario_b_rename(app) -> None:
    """B. Rename prims via adapter (NamespaceEdit) and directly via Sdf."""
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("initial")

    # B1. Rename via adapter.
    sphere = _stage.GetPrimAtPath("/World/Geometry/Sphere")
    _adapter.rename(sphere, "BigSphere")
    await _settle()
    shoot("b1_renamed_via_adapter")

    # B2. Very long name.
    cube = _stage.GetPrimAtPath("/World/Geometry/Cube")
    _adapter.rename(cube, "ThisIsAnExceptionallyLongPrimName_abcdef")
    await _settle()
    shoot("b2_long_name")

    # B3. Rename with mixed case and underscores (adapter's normalize_name
    # should be identity for legal chars — nothing to sanitise).
    dome = _stage.GetPrimAtPath("/World/Lights/DomeLight")
    _adapter.rename(dome, "Studio_Dome_01")
    await _settle()
    shoot("b3_mixed_case_name")

    # B4. Rename back to normal.
    _adapter.rename(_stage.GetPrimAtPath("/World/Geometry/BigSphere"), "Sphere")
    await _settle()
    shoot("b4_renamed_back")


async def scenario_c_reparent(app) -> None:
    """C. Reparent via adapter.reparent."""
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("initial")

    # C1. Move Sphere from Geometry to Lights.
    from ovui_data_adapters.common import ReparentPosition
    sphere = _stage.GetPrimAtPath("/World/Geometry/Sphere")
    lights = _stage.GetPrimAtPath("/World/Lights")
    _adapter.reparent([sphere], lights, ReparentPosition.CHILD)
    await _settle()
    _expand_all_levels()
    await _settle()
    shoot("c1_moved_sphere_to_lights")

    # C2. Move deeply-nested DomeLight to root (/World).
    dome = _stage.GetPrimAtPath("/World/Lights/DomeLight")
    world = _stage.GetPrimAtPath("/World")
    _adapter.reparent([dome, ], world, ReparentPosition.CHILD)
    await _settle()
    _expand_all_levels()
    await _settle()
    shoot("c2_moved_dome_to_root")

    # C3. Move a root-level child (Camera) under Geometry.
    camera = _stage.GetPrimAtPath("/World/Camera")
    geometry = _stage.GetPrimAtPath("/World/Geometry")
    _adapter.reparent([camera], geometry, ReparentPosition.CHILD)
    await _settle()
    _expand_all_levels()
    await _settle()
    shoot("c3_moved_camera_into_geometry")


async def scenario_d_sublayers(app) -> None:
    """D. Sublayer add/remove."""
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("initial")

    # Create a sublayer file in temp with a new prim.
    tmpdir = tempfile.mkdtemp()
    sub_path = os.path.join(tmpdir, "sub.usda")
    sub_stage = Usd.Stage.CreateNew(sub_path)
    UsdGeom.Xform.Define(sub_stage, "/World")
    UsdGeom.Cone.Define(sub_stage, "/World/SubLayerCone")
    sub_stage.GetRootLayer().Save()
    del sub_stage

    # D1. Add sublayer.
    _stage.GetRootLayer().subLayerPaths.append(sub_path)
    await _settle()
    _expand_all_levels()
    await _settle()
    shoot("d1_sublayer_added")

    # D2. Remove sublayer.
    _stage.GetRootLayer().subLayerPaths.clear()
    await _settle()
    _expand_all_levels()
    await _settle()
    shoot("d2_sublayer_removed")

    # D3. Add sublayer back.
    _stage.GetRootLayer().subLayerPaths.append(sub_path)
    await _settle()
    _expand_all_levels()
    await _settle()
    shoot("d3_sublayer_readded")


async def scenario_e_refs_payloads(app) -> None:
    """E. References and payloads."""
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("initial")

    # Create an external USD file to reference.
    tmpdir = tempfile.mkdtemp()
    ref_path = os.path.join(tmpdir, "ref.usda")
    ref_stage = Usd.Stage.CreateNew(ref_path)
    UsdGeom.Sphere.Define(ref_stage, "/Payload")
    ref_stage.GetRootLayer().Save()
    del ref_stage

    # E1. Add a reference.
    target = UsdGeom.Xform.Define(_stage, "/World/RefTarget").GetPrim()
    target.GetReferences().AddReference(ref_path, "/Payload")
    await _settle()
    shoot("e1_reference_added")

    # E2. Add a payload to a separate prim.
    pay_target = UsdGeom.Xform.Define(_stage, "/World/PayloadTarget").GetPrim()
    pay_target.GetPayloads().AddPayload(ref_path, "/Payload")
    await _settle()
    shoot("e2_payload_added")

    # E3. Remove the reference.
    target.GetReferences().ClearReferences()
    await _settle()
    shoot("e3_reference_removed")

    # E4. Unload the payload.
    _stage.Unload(Sdf.Path("/World/PayloadTarget"))
    await _settle()
    shoot("e4_payload_unloaded")

    # E5. Reload.
    _stage.Load(Sdf.Path("/World/PayloadTarget"))
    await _settle()
    shoot("e5_payload_reloaded")


async def scenario_f_instances(app) -> None:
    """F. Instanceable prims."""
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("initial")

    # Create an external asset with something to instance.
    tmpdir = tempfile.mkdtemp()
    asset_path = os.path.join(tmpdir, "asset.usda")
    asset_stage = Usd.Stage.CreateNew(asset_path)
    UsdGeom.Sphere.Define(asset_stage, "/Asset")
    asset_stage.GetRootLayer().Save()
    del asset_stage

    # F1. Create a prim with an instanceable reference.
    a = UsdGeom.Xform.Define(_stage, "/World/InstanceA").GetPrim()
    a.GetReferences().AddReference(asset_path, "/Asset")
    a.SetInstanceable(True)
    await _settle()
    shoot("f1_instance_a")

    # F2. Create a second instance.
    b = UsdGeom.Xform.Define(_stage, "/World/InstanceB").GetPrim()
    b.GetReferences().AddReference(asset_path, "/Asset")
    b.SetInstanceable(True)
    await _settle()
    shoot("f2_two_instances")


async def scenario_g_default_prim(app) -> None:
    """G. Default prim pill add/move/remove."""
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("initial_world_is_default")

    # G1. Clear default prim.
    _stage.ClearDefaultPrim()
    await _settle()
    shoot("g1_cleared_default")

    # G2. Set /World/Lights as default.
    _stage.SetDefaultPrim(_stage.GetPrimAtPath("/World/Lights"))
    await _settle()
    _expand_all_levels()
    await _settle()
    shoot("g2_lights_default")

    # G3. Change default to a deeper prim — USD will accept it even if
    # conventions prefer root-level defaults.
    _stage.SetDefaultPrim(_stage.GetPrimAtPath("/World"))
    await _settle()
    shoot("g3_world_default_again")


async def scenario_h_visibility(app) -> None:
    """H. Visibility toggling via adapter and USD API."""
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("initial")

    # H1. Toggle leaf via adapter (uses UndoManager).
    sphere = _stage.GetPrimAtPath("/World/Geometry/Sphere")
    _adapter.set_visibility(sphere, False)
    await _settle()
    shoot("h1_sphere_hidden")

    # H2. Toggle parent → children inherit inherited-invisible state.
    geometry = _stage.GetPrimAtPath("/World/Geometry")
    _adapter.set_visibility(geometry, False)
    await _settle()
    shoot("h2_geometry_hidden_children_ghosted")

    # H3. Toggle geometry back, toggle cube independently.
    _adapter.set_visibility(geometry, True)
    cube = _stage.GetPrimAtPath("/World/Geometry/Cube")
    _adapter.set_visibility(cube, False)
    await _settle()
    shoot("h3_cube_only_hidden")

    # H4. Toggle while collapsed, then expand.
    _collapse_all()
    await _settle()
    shoot("h4_collapsed_before")
    _adapter.set_visibility(sphere, True)
    _adapter.set_visibility(cube, True)
    await _settle()
    _expand_all_levels()
    await _settle()
    shoot("h4_expanded_after_toggle")


async def scenario_i_selection(app) -> None:
    """I. Selection via bus."""
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("initial")

    # I1. Select via widget API.
    _stage_win._widget.set_selection(["/World/Geometry/Sphere"])
    await _settle()
    shoot("i1_select_sphere")

    # I2. Select multiple.
    _stage_win._widget.set_selection([
        "/World/Geometry/Cube", "/World/Lights/DomeLight",
    ])
    await _settle()
    shoot("i2_multi_select")

    # I3. Clear.
    _stage_win._widget.set_selection([])
    await _settle()
    shoot("i3_cleared")

    # I4. Select deep prim when the branch is collapsed first, then verify
    # the widget does / does not auto-expand to it.
    _collapse_all()
    await _settle()
    shoot("i4_pre_select_collapsed")
    _stage_win._widget.set_selection(["/World/Lights/DomeLight"])
    await _settle()
    shoot("i4_after_deep_select")

    # I5. Select then delete selected prim.
    _expand_all_levels()
    await _settle()
    _stage_win._widget.set_selection(["/World/Camera"])
    await _settle()
    shoot("i5_pre_delete_selected")
    _stage.RemovePrim("/World/Camera")
    await _settle()
    shoot("i5_after_delete_selected")
    print(f"  [i5] selection after delete: {_stage_win._widget.get_selection()}")


async def scenario_j_inactive(app) -> None:
    """J. Inactive / active."""
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("initial")

    # J1. Deactivate a leaf.
    cube = _stage.GetPrimAtPath("/World/Geometry/Cube")
    cube.SetActive(False)
    await _settle()
    shoot("j1_cube_inactive")

    # J2. Reactivate.
    cube.SetActive(True)
    await _settle()
    shoot("j2_cube_reactivated")

    # J3. Deactivate a parent — children should disappear from traversal
    # (inactive prims hide their children) — verify tree reflects this.
    UsdGeom.Cube.Define(_stage, "/World/Geometry/ChildUnderInactive")
    geometry = _stage.GetPrimAtPath("/World/Geometry")
    geometry.SetActive(False)
    await _settle()
    shoot("j3_parent_inactive_children_pruned")

    geometry.SetActive(True)
    await _settle()
    _expand_all_levels()
    await _settle()
    shoot("j3_reactivated_parent")


async def scenario_k_class(app) -> None:
    """K. Class prims."""
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("initial")

    # K1. Create a class prim (typed as Xform so USD lets us set the spec).
    class_spec = Sdf.CreatePrimInLayer(_stage.GetRootLayer(), "/World/_LightTemplate")
    class_spec.specifier = Sdf.SpecifierClass
    class_spec.typeName = "Xform"
    await _settle()
    shoot("k1_class_created")

    # K2. Add a child to the class.
    child_spec = Sdf.CreatePrimInLayer(
        _stage.GetRootLayer(), "/World/_LightTemplate/ChildInClass"
    )
    child_spec.specifier = Sdf.SpecifierDef
    child_spec.typeName = "SphereLight"
    await _settle()
    _expand_all_levels()
    await _settle()
    shoot("k2_class_with_child")


async def scenario_l_large(app) -> None:
    """L. Large-scene stress."""
    await _mount(_build_large_stage(500))
    _expand("/World")
    widget = _stage_win._widget
    for g in range(10):
        widget.expand(f"/World/Group_{g}")
    await _settle(frames=20)
    shoot("l1_large_expanded")

    # L2. Select a deep leaf to exercise the path-cache lookup path.
    widget.set_selection(["/World/Group_5/Leaf_025"])
    await _settle(frames=5)
    shoot("l2_selected_mid")

    widget.set_selection(["/World/Group_9/Leaf_049"])
    await _settle(frames=5)
    shoot("l2_selected_bottom")

    # L3. Filter at scale.
    widget.filter_by_text("Leaf_045")
    await _settle(frames=10)
    shoot("l3_filter_at_scale")

    widget.filter_by_text("")
    await _settle(frames=10)
    shoot("l3_filter_cleared")


async def scenario_m_edges(app) -> None:
    """M. Edge cases."""
    # M1. Empty stage.
    await _mount(_build_empty_stage())
    await _settle()
    shoot("m1_empty_stage")

    # M2. World-only stage.
    await _mount(_build_world_only_stage())
    _expand_all_levels()
    await _settle()
    shoot("m2_world_only")

    # M3. Very deep nesting (20 levels).
    await _mount(_build_deep_stage(20))
    _expand_all_levels(levels=22)
    await _settle()
    shoot("m3_deep_nesting")

    # M4. Very wide (120 direct children).
    await _mount(_build_wide_stage(120))
    _expand_all_levels()
    await _settle()
    shoot("m4_wide_children")

    # M5. Open+close+open.
    await _mount(_build_basic_stage())
    _expand_all_levels()
    await _settle()
    shoot("m5_reopened_basic")


_SCENARIOS: dict[str, Callable] = {
    "a_crud":        scenario_a_crud,
    "b_rename":      scenario_b_rename,
    "c_reparent":    scenario_c_reparent,
    "d_sublayers":   scenario_d_sublayers,
    "e_refs":        scenario_e_refs_payloads,
    "f_instances":   scenario_f_instances,
    "g_default":     scenario_g_default_prim,
    "h_visibility":  scenario_h_visibility,
    "i_selection":   scenario_i_selection,
    "j_inactive":    scenario_j_inactive,
    "k_class":       scenario_k_class,
    "l_large":       scenario_l_large,
    "m_edges":       scenario_m_edges,
}


async def _main() -> None:
    await ui.next_frame()
    apply_default_layout()
    await testing.wait_frames(30)

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
