# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""DEEP QA harness for the Property Window.

Drives a real ``Usd.Stage`` through :class:`UsdPropertyAdapter` and the
:class:`PropertyWindow`. Each scenario performs USD mutations via the pxr
API, pumps ovui frames so the adapter's deferred flush runs, then captures
a screenshot. Scenarios cover:

* Programmatic attribute writes (Area 1)
* Large array handling (Area 2, 10K–100K elements)
* Mouse edits → USD persistence (Area 3)
* ControlStateIndicator interaction (Area 4)
* Rapid change stress (Area 5)
* Edge cases: NaN/Inf, empty strings, long strings, unicode (Area 6)

Runs one scenario per invocation:
    LD_LIBRARY_PATH=... python3.12 tests/qa_property_deep.py <scenario>

Where ``<scenario>`` is one of the keys in ``_SCENARIOS`` below. Screenshots
land under ``/tmp/qa-property-deep/NNN_<scenario>_<label>.png``.
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import omni.ui as ui
from omni.ui import testing as uitesting
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, Vt

from ovwidgets.app.application import Application
from ovwidgets.app.layout import write_split_ini
from ovwidgets.app.style import apply_global_styles, set_theme
from ovwidgets.common.selection import SelectionBus

SCENARIO = sys.argv[1] if len(sys.argv) > 1 else "area1_scalar"
SHOT_DIR = Path("/tmp/qa-property-deep")
SHOT_DIR.mkdir(parents=True, exist_ok=True)
_counter = [0]


def shoot(label: str) -> str:
    _counter[0] += 1
    path = SHOT_DIR / f"{SCENARIO}_{_counter[0]:03d}_{label}.png"
    ok = uitesting.capture_screenshot(str(path))
    size = path.stat().st_size if path.exists() else -1
    print(f"  shot {_counter[0]:03d} {label:<40}  ok={ok}  size={size:>8}  -> {path}")
    return str(path)


async def _drive(frames: int = 10) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _get_attr(stage: Usd.Stage, prim_path: str, attr_name: str):
    return stage.GetPrimAtPath(prim_path).GetAttribute(attr_name).Get()


def _log(msg: str) -> None:
    print(f"    {msg}")


# ── Stage builders ────────────────────────────────────────────────────────

def _stage_one_cube() -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    cube = UsdGeom.Cube.Define(stage, "/World/Cube")
    UsdGeom.XformCommonAPI(cube.GetPrim()).SetTranslate((0.0, 0.0, 0.0))
    return stage


def _stage_one_sphere() -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdGeom.Sphere.Define(stage, "/World/Sphere")
    return stage


def _stage_domelight() -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    return stage


def _stage_big_mesh(n_points: int) -> Usd.Stage:
    """Mesh with ``n_points`` points + matching faceVertexCounts/Indices.

    Generates a flat grid of tris so the counts/indices arrays scale with
    the point count — exercises the big-array path for multiple VtArray
    types simultaneously.
    """
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    mesh = UsdGeom.Mesh.Define(stage, "/World/BigMesh")
    side = max(2, int(math.sqrt(n_points)))
    pts = []
    for i in range(n_points):
        row, col = divmod(i, side)
        pts.append(Gf.Vec3f(float(col), 0.0, float(row)))
    mesh.GetPointsAttr().Set(Vt.Vec3fArray(pts))
    # Generate matching normals
    normals = [Gf.Vec3f(0.0, 1.0, 0.0)] * n_points
    mesh.GetNormalsAttr().Set(Vt.Vec3fArray(normals))
    # Flat tri strip: counts and indices roughly the same size
    counts = [3] * (n_points // 3)
    indices = [i % n_points for i in range(3 * (n_points // 3))]
    mesh.GetFaceVertexCountsAttr().Set(Vt.IntArray(counts))
    mesh.GetFaceVertexIndicesAttr().Set(Vt.IntArray(indices))
    return stage


def _stage_deep(depth: int) -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    path = "/World"
    for i in range(depth):
        path = f"{path}/L{i}"
        UsdGeom.Xform.Define(stage, path)
    # Bottom prim is a Cube so there are attributes to show.
    UsdGeom.Cube.Define(stage, path + "/Leaf")
    return stage, f"{path}/Leaf"


# ── Driver ────────────────────────────────────────────────────────────────

async def _bootstrap(stage: Usd.Stage):
    """Create a running Application, swap in our stage, return (app, win)."""
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    task = asyncio.ensure_future(app.run_async())
    await _drive(30)

    # Swap in the in-memory stage.
    app.open_stage(stage)
    await _drive(15)

    return app, task


async def _teardown(app, task):
    app._running = False
    try:
        await asyncio.wait_for(task, timeout=1.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
    app.shutdown()


# ── Area 1: Programmatic USD changes ──────────────────────────────────────

async def area1_scalar(stage: Usd.Stage, app) -> None:
    _log("Area 1 — scalar attribute changes (float/int/bool/string/token/color)")
    pw = app._property_window
    app.selection_bus.publish(["/World/Sphere"], source="qa")
    await _drive(10)
    shoot("A1_01_sphere_initial")

    # float: radius
    sphere = stage.GetPrimAtPath("/World/Sphere")
    sphere.GetAttribute("radius").Set(3.14159)
    await _drive(10)
    shoot("A1_02_radius_set_3.14159")
    assert _get_attr(stage, "/World/Sphere", "radius") == 3.14159

    sphere.GetAttribute("radius").Set(0.001)
    await _drive(10)
    shoot("A1_03_radius_set_0.001")

    # bool: visibility via UsdGeom.Imageable API
    UsdGeom.Imageable(sphere).MakeInvisible()
    await _drive(10)
    shoot("A1_04_visibility_invisible")

    UsdGeom.Imageable(sphere).MakeVisible()
    await _drive(10)
    shoot("A1_05_visibility_visible")

    # color3f: displayColor on sphere
    sphere.GetAttribute("primvars:displayColor").Set(
        Vt.Vec3fArray([Gf.Vec3f(1.0, 0.0, 0.0)])
    )
    await _drive(10)
    shoot("A1_06_displayColor_red")

    # Switch to DomeLight for a light color3f
    app.selection_bus.publish([], source="qa")
    await _drive(5)

    UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    await _drive(10)

    app.selection_bus.publish(["/World/DomeLight"], source="qa")
    await _drive(10)
    shoot("A1_07_domelight_selected")

    dl = stage.GetPrimAtPath("/World/DomeLight")
    dl.GetAttribute("inputs:color").Set(Gf.Vec3f(0.2, 0.8, 0.1))
    await _drive(10)
    shoot("A1_08_domelight_color_green")

    dl.GetAttribute("inputs:intensity").Set(50000.0)
    await _drive(10)
    shoot("A1_09_domelight_intensity_50k")


async def area1_vec(stage: Usd.Stage, app) -> None:
    _log("Area 1 — vec3/vec4/matrix4d")
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(10)
    shoot("A1V_01_cube_initial")

    cube = stage.GetPrimAtPath("/World/Cube")
    cube.GetAttribute("xformOp:translate").Set(Gf.Vec3d(10.0, 20.0, 30.0))
    await _drive(10)
    shoot("A1V_02_translate_10_20_30")
    actual = _get_attr(stage, "/World/Cube", "xformOp:translate")
    assert tuple(actual) == (10.0, 20.0, 30.0), f"expected 10,20,30 got {actual}"

    cube.GetAttribute("xformOp:translate").Set(Gf.Vec3d(-5.0, 0.0, 100.0))
    await _drive(10)
    shoot("A1V_03_translate_neg5_0_100")

    # Add scale op with a new op attribute and wire via xformOpOrder
    api = UsdGeom.XformCommonAPI(cube)
    api.SetScale(Gf.Vec3f(2.0, 3.0, 0.5))
    await _drive(10)
    shoot("A1V_04_scale_added")

    # Test a custom vec4 attribute
    custom = cube.CreateAttribute("custom:quat", Sdf.ValueTypeNames.Float4)
    custom.Set(Gf.Vec4f(0.1, 0.2, 0.3, 0.95))
    await _drive(10)
    shoot("A1V_05_custom_vec4_added")

    # Test a matrix4d custom attribute
    m = cube.CreateAttribute("custom:transform", Sdf.ValueTypeNames.Matrix4d)
    m.Set(Gf.Matrix4d(
        1.0, 2.0, 3.0, 4.0,
        5.0, 6.0, 7.0, 8.0,
        9.0, 10.0, 11.0, 12.0,
        13.0, 14.0, 15.0, 16.0,
    ))
    await _drive(10)
    shoot("A1V_06_matrix4d_set")

    # Test a string attribute
    s = cube.CreateAttribute("custom:label", Sdf.ValueTypeNames.String)
    s.Set("Hello, World!")
    await _drive(10)
    shoot("A1V_07_string_set")


async def area1_token(stage: Usd.Stage, app) -> None:
    _log("Area 1 — token/visibility/purpose")
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(10)
    shoot("A1T_01_cube_initial")

    cube = stage.GetPrimAtPath("/World/Cube")
    UsdGeom.Imageable(cube).CreatePurposeAttr("render")
    await _drive(10)
    shoot("A1T_02_purpose_render")

    UsdGeom.Imageable(cube).CreatePurposeAttr("guide")
    await _drive(10)
    shoot("A1T_03_purpose_guide")


# ── Area 2: Large arrays ──────────────────────────────────────────────────

async def area2_10k(stage: Usd.Stage, app) -> None:
    _log("Area 2 — 10K-point mesh")
    # Selecting the 10K-point mesh is the key test. Measure wall-clock
    # to detect UI freezes.
    t0 = time.perf_counter()
    app.selection_bus.publish(["/World/BigMesh"], source="qa")
    await _drive(10)
    t1 = time.perf_counter()
    _log(f"selection → property render: {(t1 - t0)*1000:.0f} ms")
    shoot("A2_10K_01_selected")

    # Write a new points array — verify no stall
    stage_mesh = stage.GetPrimAtPath("/World/BigMesh")
    new_pts = Vt.Vec3fArray(
        [Gf.Vec3f(float(i), float(i * 2), float(i * 3)) for i in range(10000)]
    )
    t0 = time.perf_counter()
    stage_mesh.GetAttribute("points").Set(new_pts)
    await _drive(10)
    t1 = time.perf_counter()
    _log(f"write 10K points + flush: {(t1 - t0)*1000:.0f} ms")
    shoot("A2_10K_02_after_write")


async def area2_100k(stage: Usd.Stage, app) -> None:
    _log("Area 2 — 100K-point mesh")
    t0 = time.perf_counter()
    app.selection_bus.publish(["/World/BigMesh"], source="qa")
    await _drive(10)
    t1 = time.perf_counter()
    _log(f"selection → property render: {(t1 - t0)*1000:.0f} ms")
    shoot("A2_100K_01_selected")

    # Stress: write a bigger array
    stage_mesh = stage.GetPrimAtPath("/World/BigMesh")
    bigger = Vt.Vec3fArray(
        [Gf.Vec3f(float(i), 0.0, 0.0) for i in range(100000)]
    )
    t0 = time.perf_counter()
    stage_mesh.GetAttribute("points").Set(bigger)
    await _drive(10)
    t1 = time.perf_counter()
    _log(f"write 100K points + flush: {(t1 - t0)*1000:.0f} ms")
    shoot("A2_100K_02_after_write")


async def area2_50k_custom(stage: Usd.Stage, app) -> None:
    _log("Area 2 — 50K float custom array attribute")
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(10)

    cube = stage.GetPrimAtPath("/World/Cube")
    arr_attr = cube.CreateAttribute("custom:bigFloats", Sdf.ValueTypeNames.FloatArray)
    arr_attr.Set(Vt.FloatArray([float(i) * 0.1 for i in range(50000)]))
    await _drive(15)
    shoot("A2_50K_01_custom_float_array")

    # Rewrite a smaller version of the array
    arr_attr.Set(Vt.FloatArray([1.0, 2.0, 3.0, 4.0, 5.0]))
    await _drive(15)
    shoot("A2_50K_02_shrunk_to_5")

    # Back to big again
    arr_attr.Set(Vt.FloatArray([float(i) for i in range(50000)]))
    await _drive(15)
    shoot("A2_50K_03_back_to_50k")


# ── Area 3: Mouse edits → USD ──────────────────────────────────────────────

async def area3_mouse_edit(stage: Usd.Stage, app) -> None:
    """Simulate a mouse interaction on a float field and verify USD persistence.

    We can't reliably hit-test the property field by screen coordinates
    from a scenario harness without inspecting the layout. Instead, we
    exercise the model path directly (that's what the mouse event
    callbacks do): attribute_row → model.begin_edit → model.set_value →
    model.end_edit → adapter.set_value.
    """
    _log("Area 3 — simulate a mouse edit through the row's model path")
    app.selection_bus.publish(["/World/Sphere"], source="qa")
    await _drive(10)
    shoot("A3_01_sphere_initial")

    pw = app._property_window
    widget = pw._default_attributes
    # Drive a float row edit: begin → set → end on the attribute model
    # through the adapter. That matches what widget.model.add_value_changed_fn
    # does on a FloatDrag drag-release.
    adapter = pw._adapter
    adapter.begin_edit("radius")
    adapter.set_value("radius", 5.0)
    adapter.end_edit("radius")
    await _drive(10)
    shoot("A3_02_after_model_set_5.0")

    # Read it back via USD API
    actual = _get_attr(stage, "/World/Sphere", "radius")
    assert actual == 5.0, f"expected 5.0, got {actual}"
    _log(f"USD radius after edit = {actual} (expected 5.0)")

    # Now switch to Cube and edit translate vec3
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(10)
    adapter = pw._adapter
    adapter.begin_edit("xformOp:translate")
    adapter.set_value("xformOp:translate", (7.0, 8.0, 9.0))
    adapter.end_edit("xformOp:translate")
    await _drive(10)
    shoot("A3_03_translate_via_model")
    actual = _get_attr(stage, "/World/Cube", "xformOp:translate")
    assert tuple(actual) == (7.0, 8.0, 9.0), f"expected 7,8,9 got {actual}"


# ── Area 4: ControlStateIndicator ─────────────────────────────────────────

async def area4_not_default(stage: Usd.Stage, app) -> None:
    _log("Area 4 — NotDefault ControlState")
    app.selection_bus.publish(["/World/Sphere"], source="qa")
    await _drive(10)
    shoot("A4_01_sphere_pre_author")

    # Write an authored radius
    sphere = stage.GetPrimAtPath("/World/Sphere")
    sphere.GetAttribute("radius").Set(2.0)
    await _drive(10)
    shoot("A4_02_radius_authored")

    # Now trigger the NotDefault indicator's on_click — exercise reset
    pw = app._property_window
    pw._adapter.clear_value("radius")
    await _drive(10)
    shoot("A4_03_after_clear")

    # Verify the attribute has no authored value (the spec scaffolding
    # remains after Clear() — see BUG-D004 for the IsAuthored vs
    # HasAuthoredValue distinction).
    ra = sphere.GetAttribute("radius")
    assert not ra.HasAuthoredValue(), \
        f"radius should have no authored value after clear, has_val={ra.HasAuthoredValue()}"
    assert ra.Get() == 1.0, f"radius should be back to schema default 1.0, got {ra.Get()}"


async def area4_time_sampled(stage: Usd.Stage, app) -> None:
    _log("Area 4 — TimeSampled ControlState")
    sphere = stage.GetPrimAtPath("/World/Sphere")
    ra = sphere.GetAttribute("radius")
    ra.Set(1.0, Usd.TimeCode(0.0))
    ra.Set(2.0, Usd.TimeCode(24.0))
    await _drive(10)

    app.selection_bus.publish(["/World/Sphere"], source="qa")
    await _drive(10)
    shoot("A4T_01_time_sampled")


async def area4_locked(stage: Usd.Stage, app) -> None:
    _log("Area 4 — Locked ControlState (via customData)")
    sphere = stage.GetPrimAtPath("/World/Sphere")
    ra = sphere.GetAttribute("radius")
    ra.SetCustomData({"locked": True})
    ra.Set(1.7)
    await _drive(10)
    app.selection_bus.publish(["/World/Sphere"], source="qa")
    await _drive(10)
    shoot("A4L_01_locked")


# ── Area 5: Rapid stress ──────────────────────────────────────────────────

async def area5_rapid(stage: Usd.Stage, app) -> None:
    _log("Area 5 — 50 rapid writes")
    app.selection_bus.publish(["/World/Sphere"], source="qa")
    await _drive(10)
    shoot("A5_01_before")

    sphere = stage.GetPrimAtPath("/World/Sphere")
    t0 = time.perf_counter()
    for i in range(50):
        sphere.GetAttribute("radius").Set(float(i) * 0.1)
    t1 = time.perf_counter()
    _log(f"50 writes in {(t1 - t0)*1000:.1f} ms")
    await _drive(20)
    shoot("A5_02_after_50_writes")

    final = _get_attr(stage, "/World/Sphere", "radius")
    _log(f"final radius = {final} (expected 4.9)")
    assert abs(final - 4.9) < 1e-6


# ── Area 6: Edge cases ─────────────────────────────────────────────────────

async def area6_nan_inf(stage: Usd.Stage, app) -> None:
    _log("Area 6 — NaN/Inf float values")
    app.selection_bus.publish(["/World/Sphere"], source="qa")
    await _drive(10)
    shoot("A6N_01_before")

    sphere = stage.GetPrimAtPath("/World/Sphere")
    sphere.GetAttribute("radius").Set(float("nan"))
    await _drive(10)
    shoot("A6N_02_nan")

    sphere.GetAttribute("radius").Set(float("inf"))
    await _drive(10)
    shoot("A6N_03_inf")

    sphere.GetAttribute("radius").Set(float("-inf"))
    await _drive(10)
    shoot("A6N_04_neg_inf")


async def area6_empty_string(stage: Usd.Stage, app) -> None:
    _log("Area 6 — empty string")
    cube = stage.GetPrimAtPath("/World/Cube")
    s = cube.CreateAttribute("custom:label", Sdf.ValueTypeNames.String)
    s.Set("")
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(10)
    shoot("A6S_01_empty_string")


async def area6_long_string(stage: Usd.Stage, app) -> None:
    _log("Area 6 — 10000-char string")
    cube = stage.GetPrimAtPath("/World/Cube")
    s = cube.CreateAttribute("custom:label", Sdf.ValueTypeNames.String)
    s.Set("x" * 10000)
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(10)
    shoot("A6L_01_10k_chars")


async def area6_unicode(stage: Usd.Stage, app) -> None:
    _log("Area 6 — unicode")
    cube = stage.GetPrimAtPath("/World/Cube")
    s = cube.CreateAttribute("custom:label", Sdf.ValueTypeNames.String)
    s.Set("こんにちは 🎮 مرحبا Ω αβγ")
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(10)
    shoot("A6U_01_unicode")


async def area6_empty_array(stage: Usd.Stage, app) -> None:
    _log("Area 6 — empty array attribute")
    cube = stage.GetPrimAtPath("/World/Cube")
    arr = cube.CreateAttribute("custom:empty_arr", Sdf.ValueTypeNames.FloatArray)
    arr.Set(Vt.FloatArray([]))
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(10)
    shoot("A6E_01_empty_array")


async def area6_negative(stage: Usd.Stage, app) -> None:
    _log("Area 6 — large negative values")
    cube = stage.GetPrimAtPath("/World/Cube")
    cube.GetAttribute("xformOp:translate").Set(Gf.Vec3d(-999.0, -999.0, -999.0))
    app.selection_bus.publish(["/World/Cube"], source="qa")
    await _drive(10)
    shoot("A6Neg_01_negative_translate")


async def area6_deep(app, leaf_path: str) -> None:
    _log("Area 6 — 20-deep nested prim select")
    app.selection_bus.publish([leaf_path], source="qa")
    await _drive(10)
    shoot("A6D_01_deep_select")


# ── Dispatch table ────────────────────────────────────────────────────────

_SCENARIOS = {
    "area1_scalar":   ("sphere", area1_scalar),
    "area1_vec":      ("cube", area1_vec),
    "area1_token":    ("cube", area1_token),
    "area2_10k":      ("big10k", area2_10k),
    "area2_100k":     ("big100k", area2_100k),
    "area2_50k_custom": ("cube", area2_50k_custom),
    "area3_mouse":    ("cube_sphere", area3_mouse_edit),
    "area4_not_default": ("sphere", area4_not_default),
    "area4_time_sampled": ("sphere", area4_time_sampled),
    "area4_locked":   ("sphere", area4_locked),
    "area5_rapid":    ("sphere", area5_rapid),
    "area6_nan":      ("sphere", area6_nan_inf),
    "area6_empty_string": ("cube", area6_empty_string),
    "area6_long_string": ("cube", area6_long_string),
    "area6_unicode":  ("cube", area6_unicode),
    "area6_empty_array": ("cube", area6_empty_array),
    "area6_negative": ("cube", area6_negative),
    "area6_deep":     ("deep", None),
}


async def _main() -> None:
    if SCENARIO not in _SCENARIOS:
        print(f"Unknown scenario: {SCENARIO}")
        print(f"Available: {sorted(_SCENARIOS.keys())}")
        sys.exit(1)

    stage_kind, handler = _SCENARIOS[SCENARIO]
    leaf_path = None
    if stage_kind == "sphere":
        stage = _stage_one_sphere()
    elif stage_kind == "cube":
        stage = _stage_one_cube()
    elif stage_kind == "cube_sphere":
        stage = _stage_one_cube()
        UsdGeom.Sphere.Define(stage, "/World/Sphere")
    elif stage_kind == "big10k":
        stage = _stage_big_mesh(10000)
    elif stage_kind == "big100k":
        stage = _stage_big_mesh(100000)
    elif stage_kind == "deep":
        stage, leaf_path = _stage_deep(20)
    else:
        raise RuntimeError(f"Unknown stage_kind: {stage_kind}")

    app, task = await _bootstrap(stage)
    shoot("boot")

    try:
        if SCENARIO == "area6_deep":
            await area6_deep(app, leaf_path)
        else:
            await handler(stage, app)
    finally:
        await _teardown(app, task)

    sys.exit(0)


if __name__ == "__main__":
    # Strip any stale layout so a re-run gets the default panel arrangement.
    layout_path = os.path.expanduser("~/.ovgear/layout.json")
    if os.path.exists(layout_path):
        os.unlink(layout_path)
    write_split_ini()
    ui.init(f"OvGear Property Deep QA — {SCENARIO}", width=1280, height=720)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())
