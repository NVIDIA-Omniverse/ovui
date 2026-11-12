# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The render check: expected colours, the studio, the verdicts, and a real renderer run."""

from __future__ import annotations

import json
import logging
import pathlib
import subprocess
import sys
import time

import pytest
from pxr import Gf, Sdf, Usd, UsdShade

from ovui_data_adapters.common import render_diagnostics as rd
from ovui_data_adapters.common import render_probe as probe

GENERATOR = pathlib.Path(__file__).resolve().parents[1] / "data" / "make_material_regression_scene.py"
POTATO = "/World/Kitchen/W4_FoodProduce_v1/Looks/PotatoRed"
RUNNER = "/World/Kitchen/W1_Looks/PeruReviewV2/CrimsonRunner"
GREENS = "/World/Kitchen/Looks/Greens"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(rd, "_DIAGNOSTICS", rd.RenderDiagnostics())
    monkeypatch.setattr(rd, "_VERIFICATION", {})


def _scene(path, *breaks):
    command = [sys.executable, str(GENERATOR), str(path)]
    for kind in breaks:
        command += ["--break", kind]
    subprocess.run(command, check=True, capture_output=True)
    return str(path / "kitchen.usda")


def test_expected_colour_of_a_textured_openpbr_material_is_the_decoded_image_mean(tmp_path):
    stage = Usd.Stage.Open(_scene(tmp_path))
    expected, reason = probe.expected_albedo(stage.GetPrimAtPath(POTATO))
    assert reason == "" and expected["family"] == "materialx" and expected["resources"] == ["./PotatoRed.png"]
    # PotatoRed.png is (170, 40, 45) and the file attribute says sRGB.
    assert expected["linear"] == pytest.approx(tuple(probe._srgb_to_linear(c / 255) for c in (170, 40, 45)), abs=0.01)


def test_an_image_without_a_colour_space_is_read_as_raw_like_the_renderer_does(tmp_path):
    stage = Usd.Stage.Open(_scene(tmp_path))
    attribute = stage.GetPrimAtPath(f"{GREENS}/albedo").GetAttribute("inputs:file")
    attribute.SetColorSpace("")
    expected, _ = probe.expected_albedo(stage.GetPrimAtPath(GREENS))
    assert expected["linear"] == pytest.approx((40 / 255, 190 / 255, 60 / 255), abs=0.01)


def test_expected_colour_of_a_native_mdl_material_is_its_authored_constant(tmp_path):
    stage = Usd.Stage.Open(_scene(tmp_path))
    expected, _ = probe.expected_albedo(stage.GetPrimAtPath(RUNNER))
    assert expected["family"] == "mdl" and expected["linear"] == pytest.approx((0.55, 0.02, 0.06))
    assert expected["resources"] == []


@pytest.mark.parametrize("breaks,reason", [
    (("missing-texture",), "albedo image is missing"),
    (("corrupt-texture",), "the albedo image cannot be read here"),
])
def test_a_material_whose_image_cannot_be_read_is_unverifiable_with_the_reason(tmp_path, breaks, reason):
    stage = Usd.Stage.Open(_scene(tmp_path, *breaks))
    expected, why = probe.expected_albedo(stage.GetPrimAtPath(POTATO))
    assert expected is None and reason in why


def test_materials_that_a_flat_reference_cannot_match_are_unverifiable():
    from pxr import Sdf

    stage = Usd.Stage.CreateInMemory()
    material = UsdShade.Material.Define(stage, "/M")
    shader = UsdShade.Shader.Define(stage, "/M/S")
    shader.CreateIdAttr("ND_open_pbr_surface_surfaceshader")
    shader.CreateInput("base_color", Sdf.ValueTypeNames.Color3f).Set((0.5, 0.5, 0.5))
    shader.CreateInput("emission_luminance", Sdf.ValueTypeNames.Float).Set(5.0)
    material.CreateSurfaceOutput("mtlx").ConnectToSource(shader.CreateOutput("out", Sdf.ValueTypeNames.Token))
    expected, reason = probe.expected_albedo(stage.GetPrimAtPath("/M"))
    assert expected is None and "emission_luminance" in reason
    assert probe.expected_albedo(UsdShade.Material.Define(stage, "/Empty").GetPrim())[1] == "no surface output is connected"


def test_the_studio_has_a_real_and_a_reference_cube_for_each_material(tmp_path):
    scene = _scene(tmp_path)
    todo, skipped = probe.plan(Usd.Stage.Open(scene))
    assert skipped == {} and len(todo) == 5
    studio = probe.studio_stage(scene, todo, str(tmp_path))
    bound = {}
    for index, item in enumerate(todo):
        real = UsdShade.MaterialBindingAPI(studio.GetPrimAtPath(f"/OvuiProbe/Real_{index}")).ComputeBoundMaterial()[0]
        ref = UsdShade.MaterialBindingAPI(studio.GetPrimAtPath(f"/OvuiProbe/Ref_{index}")).ComputeBoundMaterial()[0]
        bound[item["path"]] = (str(real.GetPath()), str(ref.GetPath()))
        assert str(real.GetPath()) == item["path"]  # the real cube uses the scene's own material
    # the reference is in the same shading family: OpenPBR for MaterialX, MDL for MDL
    ref_shader = lambda path: studio.GetPrimAtPath(bound[path][1] + "/Surface")  # noqa: E731
    assert ref_shader(POTATO).GetAttribute("info:id").Get() == "ND_open_pbr_surface_surfaceshader"
    assert ref_shader(RUNNER).GetAttribute("info:mdl:sourceAsset").Get().path.endswith("ovui_probe_flat.mdl")
    assert (tmp_path / "ovui_probe_flat.mdl").is_file()
    assert studio.GetMetadata("customLayerData")["ovuiProbeProducts"] == ["/OvuiProbe/Render_0"]


def test_scene_lights_are_switched_off_in_the_studio(tmp_path):
    scene = _scene(tmp_path)
    studio = probe.studio_stage(scene, probe.plan(Usd.Stage.Open(scene))[0], str(tmp_path))
    assert studio.GetPrimAtPath("/World/Dome").IsActive() is False
    assert studio.GetPrimAtPath("/OvuiProbe/Dome").IsActive() is True


def test_compare_uses_the_largest_channel_difference():
    assert probe.compare((10, 20, 30), (12, 18, 31)) == (True, 2)
    assert probe.compare((226, 82, 83), (205, 24, 61)) == (False, 58)


def test_a_mismatch_is_recorded_as_an_event_with_material_and_resource(caplog):
    result = {"materials": {
        POTATO: {"state": "mismatch", "difference": 77, "tolerance": 40, "rendered": [212, 131, 141],
                 "reference": [187, 59, 66], "resources": ["./PotatoRed.png"]},
        GREENS: {"state": "ok", "difference": 1, "resources": ["./Greens.png"]},
        "/M": {"state": "unverifiable", "reason": "the albedo image cannot be read here (E: bad)"},
    }, "events": [{"material": rd.SCENE, "resource": "file:/a/x.png", "kind": "texture", "message": "m", "context": "", "scope": "resource"}]}
    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        probe.record_result(result)
    assert result["mismatches"] == [POTATO]
    kinds = {(e["material"], e["kind"]) for e in rd.get_render_diagnostics().events()}
    assert (POTATO, "mismatch") in kinds and (rd.SCENE, "texture") in kinds
    # an image that this process cannot read is not a failure of the texture: the renderer log says that
    assert ("/M", "unverified") in kinds and ("/M", "texture") not in kinds and result["failures"] == [
        f"{POTATO}: shown wrong (77 off)", "file:/a/x.png: texture failure in the renderer log"]
    assert f"material {POTATO} resource ./PotatoRed.png (mismatch)" in caplog.text
    assert rd.get_verification()[GREENS]["state"] == "ok"


def test_the_automatic_check_is_off_unless_it_is_asked_for(monkeypatch):
    monkeypatch.delenv(probe.VERIFY_ENV, raising=False)
    assert probe.verify_mode() == "off"  # it draws extra frames after the first one: not by default
    for value, mode in (("0", "off"), ("off", "off"), ("1", "warn"), ("warn", "warn"), ("strict", "strict"), ("STRICT", "strict")):
        monkeypatch.setenv(probe.VERIFY_ENV, value)
        assert probe.verify_mode() == mode


def test_live_plan_copies_the_original_geometry_of_each_material_into_its_cell(tmp_path):
    from pxr import Gf

    scene = _scene(tmp_path)
    live = probe.live_plan(Usd.Stage.Open(scene))
    try:
        assert live.products == ["/OvuiProbe/Render_0"] and len(live.todo) == 5 and live.skipped == {}
        by_material = {item["path"]: clone for item, clone in zip(live.todo, live.clones)}
        target, source, matrix = by_material[GREENS]
        assert target.startswith("/OvuiProbe/Clone_") and source == "/World/Kitchen/Greens_geo"  # the ORIGINAL prim
        # the matrix puts the centre of the geometry into its cell and fits it into a unit cube
        item = next(i for i in live.todo if i["path"] == GREENS)
        index = live.todo.index(item)
        x, y = probe._cell(index)
        moved = Gf.Matrix4d(matrix).Transform(Gf.Vec3d(*item["centre"]))
        assert tuple(moved) == pytest.approx((x, y, probe.STUDIO_Z), abs=1e-6)
        assert Gf.Matrix4d(matrix).Transform(Gf.Vec3d(*item["centre"]) + Gf.Vec3d(item["size"], 0, 0)) - moved == pytest.approx(Gf.Vec3d(1, 0, 0), abs=1e-6)
        # the layer has the references and the cameras, and NO copy of a material: the materials are the scene's own
        layer = Usd.Stage.CreateInMemory()
        layer.GetRootLayer().ImportFromString(live.layer_text)
        assert layer.GetPrimAtPath("/P/Ref_0") and layer.GetPrimAtPath("/P/Camera_0")
        assert not layer.GetPrimAtPath("/P/Real_0") and not layer.GetPrimAtPath("/P/RealLook_0")
    finally:
        live.cleanup()
    assert not pathlib.Path(live.work_dir).exists()


def test_a_material_that_no_geometry_uses_is_unverifiable_and_never_dropped(tmp_path):
    stage = Usd.Stage.Open(_scene(tmp_path))
    UsdShade.Material.Define(stage, "/World/Looks/Unused").GetPrim().SetInstanceable(False)
    live = probe.live_plan(stage)
    try:
        assert live.skipped["/World/Looks/Unused"]["reason"].startswith("no ")
    finally:
        live.cleanup()
    only_unused = Usd.Stage.CreateInMemory()
    UsdShade.Material.Define(only_unused, "/Empty")
    nothing = probe.live_plan(only_unused)
    try:
        assert nothing.todo == [] and nothing.layer_text == "" and "/Empty" in nothing.skipped  # results are not lost
        result = probe.record_result(nothing.judge({}))
    finally:
        nothing.cleanup()
    assert result["unverified"] == ["/Empty"] and result["failures"] == []
    (event,) = rd.get_render_diagnostics().events()
    assert (event["material"], event["kind"]) == ("/Empty", "unverified") and "not checked" in event["message"]


def _cell_images(real, ref, covered_real=None, covered_ref=None, offset=0):
    """A picture and a distance image with the real shape and the reference of one cell drawn into it."""

    import numpy as np

    ldr = np.full((probe.HEIGHT, probe.WIDTH, 4), 238, dtype=np.uint8)  # the background
    depth = np.full((probe.HEIGHT, probe.WIDTH, 1), np.inf, dtype=np.float32)
    rx, ry, fx, fy = probe._pixel(offset)
    half = int(0.5 * probe._PER_UNIT)
    for (x, y), color, covered in (((rx, ry), real, covered_real), ((fx, fy), ref, covered_ref)):
        mask = np.ones((2 * half, 2 * half), dtype=bool) if covered is None else covered(half)
        window = (slice(y - half, y + half), slice(x - half, x + half))
        ldr[window][mask, :3] = color
        depth[window][mask] = 100.0
    return {probe.LDR_VAR: ldr, probe.DEPTH_VAR: depth}


def _ring(half):
    """What a frame covers: a ring with an opening in the middle (outer 1.0, opening 0.6)."""

    import numpy as np

    mask = np.ones((2 * half, 2 * half), dtype=bool)
    opening = int(half * 0.6)
    mask[half - opening:half + opening, half - opening:half + opening] = False
    return mask


TODO_ONE = [{"path": "/A", "source": "s", "resources": []}]
PRODUCT = "/OvuiProbe/Render_0"


def test_judge_compares_what_each_shape_covers():
    results = probe.judge(TODO_ONE, [PRODUCT], {PRODUCT: _cell_images((10, 20, 30), (12, 20, 30))})
    assert results["/A"]["state"] == "ok" and results["/A"]["difference"] == 2
    wrong = probe.judge(TODO_ONE, [PRODUCT], {PRODUCT: _cell_images((226, 82, 83), (205, 24, 61))})
    assert wrong["/A"]["state"] == "mismatch" and wrong["/A"]["difference"] == 58  # a real failure is still found


def test_a_frame_with_an_opening_is_judged_on_the_frame_and_not_on_the_background():
    """Regression: the middle of the cell of a frame is background (238), not the colour of the material."""

    images = _cell_images((239, 95, 97), (239, 95, 97), covered_real=_ring)  # a red frame beside a red cube
    result = probe.judge(TODO_ONE, [PRODUCT], {PRODUCT: images})["/A"]
    assert result["state"] == "ok" and result["difference"] == 0 and result["rendered"] == [239, 95, 97]
    # the middle of the old fixed patch really is background: a fixed 8x8 patch would have read (238, 238, 238)
    rx, ry, _fx, _fy = probe._pixel(0)
    assert tuple(images[probe.LDR_VAR][ry, rx, :3]) == (238, 238, 238)
    wrong = _cell_images((226, 82, 83), (205, 24, 61), covered_real=_ring)
    assert probe.judge(TODO_ONE, [PRODUCT], {PRODUCT: wrong})["/A"]["state"] == "mismatch"  # a wrong frame is still found


def test_a_shape_that_is_too_thin_or_not_drawn_is_unverifiable_not_ok():
    import numpy as np

    def sliver(half):
        mask = np.zeros((2 * half, 2 * half), dtype=bool)
        mask[:, half:half + 3] = True  # three pixels wide: nothing is left once the edge is cut away
        return mask

    thin = probe.judge(TODO_ONE, [PRODUCT], {PRODUCT: _cell_images((1, 2, 3), (1, 2, 3), covered_real=sliver)})["/A"]
    assert thin["state"] == "unverifiable" and "too little of the shape" in thin["reason"]
    images = _cell_images((1, 2, 3), (1, 2, 3))
    del images[probe.DEPTH_VAR]
    none = probe.judge(TODO_ONE, [PRODUCT], {PRODUCT: images})["/A"]
    assert none["state"] == "unverifiable" and "no DistanceToImagePlaneSD" in none["reason"]


def test_extract_images_copies_the_picture_and_the_distance_of_a_frame():
    import numpy as np

    class Var:
        def __init__(self, array):
            self.array, self.unmapped = array, False

        def map(self, device=None):
            class Mapped(np.ndarray):
                pass

            mapped = self.array.view(Mapped)
            mapped.unmap = lambda: setattr(self, "unmapped", True)
            return mapped

    ldr, depth, other = Var(np.zeros((4, 4, 4), np.uint8)), Var(np.ones((4, 4, 1), np.float32)), Var(np.zeros(3))
    frame = type("F", (), {"render_vars": {"/OvuiProbe/Render_0/LdrColor": ldr, "/OvuiProbe/Render_0/DistanceToImagePlaneSD": depth,
                                           "/OvuiProbe/Render_0/Other": other}})()
    images = probe.extract_images(frame, "cpu")
    assert set(images) == {"LdrColor", "DistanceToImagePlaneSD"} and ldr.unmapped and depth.unmapped and not other.unmapped


def test_the_studio_layer_text_is_valid_usd_without_a_material_copy(tmp_path):
    todo, _skipped = probe.plan(Usd.Stage.Open(_scene(tmp_path)))
    text, names = probe.studio_layer_text(todo, str(tmp_path), "/P")
    layer = Usd.Stage.CreateInMemory()
    layer.GetRootLayer().ImportFromString(text)
    assert names == ["Render_0"] and layer.GetDefaultPrim().GetPath() == "/P"
    product = layer.GetPrimAtPath("/P/Render_0")
    assert [str(t) for t in product.GetRelationship("orderedVars").GetTargets()] == [
        "/P/Render_0/LdrColor", "/P/Render_0/DistanceToImagePlaneSD"]
    assert not layer.GetPrimAtPath("/P/Real_0")  # the real shape is a copy of the original geometry, added by the adapter
    ref_shaders = {i: layer.GetPrimAtPath(f"/P/RefLook_{i}/Surface") for i in range(len(todo))}
    families = {t["family"] for t in todo}
    assert families == {"materialx", "mdl"} and all(s.IsValid() for s in ref_shaders.values())
    assert (tmp_path / "ovui_probe_flat.mdl").is_file()
    with_real, _ = probe.studio_layer_text(todo, str(tmp_path), "/OvuiProbe", real_cubes=True)
    study = Usd.Stage.CreateInMemory()
    study.GetRootLayer().ImportFromString(with_real)
    assert [str(t) for t in study.GetPrimAtPath("/OvuiProbe/Real_0").GetRelationship("material:binding").GetTargets()] == [todo[0]["path"]]


def _check_saved_file(scene, tmp_path):
    """Run the command line check (a fresh renderer of this install) on a saved scene file, and keep its result."""

    out = tmp_path / "result.json"
    done = subprocess.run([sys.executable, "-m", "ovui_data_adapters.common.render_probe", scene, "--json", str(out)],
                          capture_output=True, text=True, timeout=900, check=False)
    assert done.returncode in (0, 1), done.stderr[-2000:]
    return probe.record_result(json.loads(out.read_text()))


@pytest.mark.requires_ovrtx
def test_real_renderer_shows_a_broken_mdl_runner_as_a_mismatch_and_a_good_scene_as_ok(tmp_path):
    """The failing case before the fix: the renderer draws a fallback for the runner and says nothing."""

    good = _check_saved_file(_scene(tmp_path / "good"), tmp_path)
    assert good["mismatches"] == []
    assert {i["state"] for i in good["materials"].values()} == {"ok"}
    broken = _check_saved_file(_scene(tmp_path / "broken", "broken-mdl"), tmp_path)
    assert broken["mismatches"] == [RUNNER]
    events = rd.get_render_diagnostics().events()
    assert any(e["kind"] == "mdl" and e["resource"].endswith("peru_runner_diamond_v1.mdl") for e in events)
    assert any(e["kind"] == "mismatch" and e["material"] == RUNNER for e in events)
    assert json.dumps(broken["materials"][RUNNER])


def test_the_failure_summary_names_a_missing_image_and_each_failure_of_the_renderer_log():
    result = probe.record_result({
        "materials": {POTATO: {"state": "unverifiable", "reason": "albedo image is missing: ./PotatoRed.png"}},
        "events": [{"material": rd.SCENE, "resource": "file:/a/runner.mdl", "kind": "mdl", "message": "m", "context": "", "scope": "resource"},
                   {"material": rd.SCENE, "resource": "", "kind": "mdl", "message": "m2", "context": "", "scope": "scene"}]})
    summary = probe.failure_summary(result)
    assert "PotatoRed: albedo image is missing: ./PotatoRed.png" in summary
    assert "file:/a/runner.mdl: mdl failure in the renderer log" in summary
    assert "renderer log: mdl failure in the renderer log" in summary  # an unnamed event is not "(scene)"


@pytest.mark.requires_ovrtx
@pytest.mark.own_process
def test_real_adapter_checks_its_own_renderer_after_the_first_frame_when_asked(tmp_path, monkeypatch):
    """The reported failure, in the renderer that shows the scene: a fallback runner and a corrupt texture."""

    import numpy as np

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    monkeypatch.setenv(probe.VERIFY_ENV, "1")

    def run(path):
        adapter = OvRtxRendererAdapter()
        try:
            adapter.load_stage(Usd.Stage.Open(path))
            view = np.eye(4)
            view[3, 2] = -34.0
            proj = np.array([[2.4, 0, 0, 0], [0, 4.27, 0, 0], [0, 0, -1.0002, -1], [0, 0, -0.020002, 0]])
            for _ in range(4):
                adapter.render_frame(320, 180, view, proj)
            # Frames for two more seconds, as an application draws them: a texture failure that the renderer
            # writes to its log late is read and linked to its materials.
            end = time.monotonic() + 2.0
            while time.monotonic() < end:
                adapter.render_frame(320, 180, view, proj)
                time.sleep(0.1)
        finally:
            adapter.shutdown()
        return dict(rd.get_verification())

    good = run(_scene(tmp_path / "good"))
    assert {i["state"] for i in good.values()} == {"ok"}
    # a frame mesh (an opening in the middle) and a solid cube with the same shader and colour are both right
    framed = run(_scene(tmp_path / "frame", "frame"))
    assert {i["state"] for i in framed.values()} == {"ok"} and len(framed) == 7
    monkeypatch.setattr(rd, "_DIAGNOSTICS", rd.RenderDiagnostics())
    broken = run(_scene(tmp_path / "broken", "broken-mdl", "corrupt-texture"))
    assert broken[RUNNER]["state"] == "mismatch" and broken[POTATO]["state"] == "unverifiable"
    events = rd.get_render_diagnostics().events()
    kinds = {(e["material"], e["kind"]) for e in events}
    # the corrupt image is named by the renderer's own log, with the material that uses it
    assert (RUNNER, "mismatch") in kinds and (POTATO, "texture") in kinds
    status = __import__("ovui_data_adapters.common.render_diagnostics_service", fromlist=["x"]).inspector_status()
    assert status["degraded"] is True and RUNNER in status["materials_shown_wrong"]


def test_a_native_mdl_that_takes_the_module_defaults_is_unverifiable_in_the_live_plan(tmp_path):
    stage = Usd.Stage.Open(_scene(tmp_path, "module-defaults"))
    live = probe.live_plan(stage)
    try:
        assert live.skipped[RUNNER]["state"] == "unverifiable"
        assert "no albedo input" in live.skipped[RUNNER]["reason"]
        assert RUNNER not in {item["path"] for item in live.todo}
        result = probe.record_result({"materials": dict(live.skipped), "events": []})
    finally:
        live.cleanup()
    assert result["unverified"] == [RUNNER] and result["failures"] == []  # not a failure, and not silent
    assert (RUNNER, "unverified") in {(e["material"], e["kind"]) for e in rd.get_render_diagnostics().events()}


def _flat_items(count):
    return [{"path": f"/W/Looks/M{i}", "linear": (0.1, 0.2, 0.3), "resources": [], "source": f"/W/G{i}",
             "family": "preview", "centre": (0.0, 0.0, 0.0), "size": 1.0} for i in range(count)]


def test_two_blocks_of_the_check_are_out_of_each_others_view(tmp_path):
    """Each block of CHUNK materials has its own camera. A cell of one block must not be in the view of another
    block's camera: before the fix every block was at the same place, and a second block's copies and reference
    cubes were drawn on top of the first block's (Factory: six materials shown as wrong that were right)."""

    from pxr import Gf

    items = _flat_items(probe.CHUNK + 6)
    text, products = probe.studio_layer_text(items, str(tmp_path), "/P")
    assert products == ["Render_0", "Render_1"]
    stage = Usd.Stage.CreateInMemory()
    stage.GetRootLayer().ImportFromString(text)
    half_w = probe.APERTURE / probe.FOCAL * probe.CAMERA_DISTANCE / 2 + 1.0  # plus the size of one cube
    half_h = half_w * probe.HEIGHT / probe.WIDTH + 1.0
    cameras = [stage.GetPrimAtPath(f"/P/Camera_{i}").GetAttribute("xformOp:translate").Get() for i in (0, 1)]

    def seen_by(camera, point):
        return abs(point[0] - camera[0]) < half_w and abs(point[1] - camera[1]) < half_h

    for index, item in enumerate(items):
        block = index // probe.CHUNK
        reference = stage.GetPrimAtPath(f"/P/Ref_{index}").GetAttribute("xformOp:translate").Get()
        copy = Gf.Matrix4d(probe.clone_matrix(item, index)).Transform(Gf.Vec3d(0, 0, 0))
        for point in (reference, copy):
            assert seen_by(cameras[block], point), (index, point)
            assert not seen_by(cameras[1 - block], point), (index, point)


def test_materials_after_the_limit_are_reported_as_not_reached(tmp_path, caplog):
    stage = Usd.Stage.Open(_scene(tmp_path))
    todo, skipped = probe.plan(stage, limit=2)
    not_reached = sorted(p for p, i in skipped.items() if i["state"] == "not_reached")
    assert len(todo) + len(skipped) == 5 and len(not_reached) == 3
    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        result = probe.record_result({"materials": dict(skipped), "events": []})
    assert result["not_reached"] == not_reached and result["failures"] == []
    assert "3 material(s) were not checked" in caplog.text
    # counted, not one event each: a large scene has thousands
    assert not any(e["material"] in not_reached for e in rd.get_render_diagnostics().events())


def _many_flat_materials_scene(path, count):
    lines = ['#usda 1.0\n(\n    defaultPrim = "W"\n)\ndef Xform "W"\n{\n']
    for i in range(count):
        r, g, b = ((i * 37) % 100) / 100, ((i * 61) % 100) / 100, ((i * 83) % 100) / 100
        lines.append(
            f'    def Cube "G{i}" (prepend apiSchemas = ["MaterialBindingAPI"])\n    {{\n'
            f"        double3 xformOp:translate = ({i * 3}, 0, 0)\n        uniform token[] xformOpOrder = [\"xformOp:translate\"]\n"
            f"        rel material:binding = </W/Looks/M{i}>\n    }}\n"
        )
    lines.append('    def Scope "Looks"\n    {\n')
    for i in range(count):
        r, g, b = ((i * 37) % 100) / 100, ((i * 61) % 100) / 100, ((i * 83) % 100) / 100
        lines.append(
            f'        def Material "M{i}"\n        {{\n'
            f"            token outputs:surface.connect = </W/Looks/M{i}/S.outputs:surface>\n"
            f'            def Shader "S"\n            {{\n                uniform token info:id = "UsdPreviewSurface"\n'
            f"                color3f inputs:diffuseColor = ({r}, {g}, {b})\n                float inputs:roughness = 0.5\n"
            "                token outputs:surface\n            }\n        }\n"
        )
    lines.append("    }\n}\n")
    scene = path / "many.usda"
    scene.write_text("".join(lines))
    return str(scene)


@pytest.mark.requires_ovrtx
@pytest.mark.own_process
def test_real_adapter_with_a_compiler_session_limit_still_reads_its_renderer_log(tmp_path, monkeypatch, caplog):
    """A real adapter with the session limit: the limit is applied before the first renderer, and the adapter still
    reads its renderer's log, so a texture failure that only the log names is reported."""

    import numpy as np

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    monkeypatch.setenv("OVUI_SHADER_COMPILER_SESSIONS", "2")
    scene = _scene(tmp_path / "broken", "corrupt-texture")
    with caplog.at_level(logging.INFO, logger="ovui.render_diagnostics"):
        adapter = OvRtxRendererAdapter()
        try:
            adapter.load_stage(Usd.Stage.Open(scene))
            view = np.eye(4)
            view[3, 2] = -34.0
            proj = np.array([[2.4, 0, 0, 0], [0, 4.27, 0, 0], [0, 0, -1.0002, -1], [0, 0, -0.020002, 0]])
            end = time.monotonic() + 3.0
            while time.monotonic() < end:
                adapter.render_frame(320, 180, view, proj)
                time.sleep(0.1)
        finally:
            adapter.shutdown()
    assert "shader compiler sessions limited to 2" in caplog.text
    # The image file is on disk (corrupt), so only the renderer's log can name it.
    assert (POTATO, "texture") in {(e["material"], e["kind"]) for e in rd.get_render_diagnostics().events()}


@pytest.mark.requires_ovrtx
def test_real_renderer_checks_more_materials_than_one_block_without_false_mismatches(tmp_path):
    """30 right materials, more than one block of the check: every one is ok (before the fix, the second block
    was drawn on top of the first, and right materials were reported as shown wrong)."""

    result = _check_saved_file(_many_flat_materials_scene(tmp_path, probe.CHUNK + 6), tmp_path)
    assert result["mismatches"] == []
    assert {i["state"] for i in result["materials"].values()} == {"ok"} and len(result["materials"]) == probe.CHUNK + 6


def test_a_missing_albedo_image_is_a_failure_of_the_check_and_its_event_comes_from_the_file_check(tmp_path):
    from ovui_data_adapters.common.render_material_report import record_file_events, shader_files

    stage = Usd.Stage.Open(_scene(tmp_path, "missing-texture"))
    todo, skipped = probe.plan(stage)
    assert "albedo image is missing" in skipped[POTATO]["reason"]
    result = probe.record_result({"materials": dict(skipped), "events": []})
    assert any(f.startswith(POTATO) for f in result["failures"])
    record_file_events(shader_files(stage))  # the check of the scene's files runs after the first frame
    events = [(e["material"], e["kind"]) for e in rd.get_render_diagnostics().events()]
    assert events.count((POTATO, "texture")) == 1 and (POTATO, "unverified") in events  # recorded once


@pytest.mark.parametrize("metallic,checked", [(1.0, False), (None, True)])
def test_a_metal_is_not_checked_against_a_flat_reference(metallic, checked):
    """Factory: Brass_01 (OmniPBR, metallic 1, roughness 0.1) was reported as shown wrong: a metal shows what it reflects."""

    stage = Usd.Stage.CreateInMemory()
    material = UsdShade.Material.Define(stage, "/W/Looks/Brass")
    shader = UsdShade.Shader.Define(stage, "/W/Looks/Brass/Shader")
    shader.SetSourceAsset(Sdf.AssetPath("OmniPBR.mdl"), "mdl")
    shader.CreateInput("diffuse_color_constant", Sdf.ValueTypeNames.Color3f).Set((0.71, 0.65, 0.26))
    if metallic is not None:
        shader.CreateInput("metallic_constant", Sdf.ValueTypeNames.Float).Set(metallic)
    material.CreateSurfaceOutput("mdl").ConnectToSource(shader.CreateOutput("out", Sdf.ValueTypeNames.Token))
    expected, reason = probe.expected_albedo(material.GetPrim())
    if checked:
        assert expected is not None and expected["linear"] == pytest.approx((0.71, 0.65, 0.26))
    else:
        assert expected is None and "is a metal (metallic_constant 1)" in reason


def _greens_with_weights(tmp_path, base_weight=0.0, specular_weight=0.0):
    """The regression kitchen, where Greens (OpenPBR) has base_weight and specular_weight: valid controls (0 is black)."""

    scene = _scene(tmp_path)
    stage = Usd.Stage.Open(scene)
    shader = UsdShade.Shader.Get(stage, GREENS + "/OpenPBR")
    shader.CreateInput("base_weight", Sdf.ValueTypeNames.Float).Set(base_weight)
    shader.CreateInput("specular_weight", Sdf.ValueTypeNames.Float).Set(specular_weight)
    stage.GetRootLayer().Save()
    return scene


def test_the_reference_of_an_openpbr_material_keeps_its_shading_controls(tmp_path):
    """Review: a valid OpenPBR with base_weight 0 and specular_weight 0 renders black, and the reference without these
    controls was a coloured cube: the correct material was called shown wrong (difference 236)."""

    scene = _greens_with_weights(tmp_path)
    stage = Usd.Stage.Open(scene)
    expected, reason = probe.expected_albedo(stage.GetPrimAtPath(GREENS))
    assert reason == "" and expected["identifier"] == "ND_open_pbr_surface_surfaceshader"
    assert expected["colour_input"] == "base_color"
    assert ("float", "base_weight", "0.0") in expected["inputs"] and ("float", "specular_weight", "0.0") in expected["inputs"]
    todo, _skipped = probe.plan(stage)
    text, _names = probe.studio_layer_text(todo, str(tmp_path), "/P")
    studio = Usd.Stage.CreateInMemory()
    studio.GetRootLayer().ImportFromString(text)
    index = [item["path"] for item in todo].index(GREENS)
    reference = studio.GetPrimAtPath(f"/P/RefLook_{index}/Surface")
    assert reference.GetAttribute("info:id").Get() == "ND_open_pbr_surface_surfaceshader"
    assert reference.GetAttribute("inputs:base_weight").Get() == 0.0
    assert reference.GetAttribute("inputs:specular_weight").Get() == 0.0
    assert reference.GetAttribute("inputs:base_color").Get() == pytest.approx(expected["linear"])
    # A roughness or normal map stays out of the reference; the material is still checked.
    assert not reference.GetAttribute("inputs:specular_roughness") and not reference.GetAttribute("inputs:geometry_normal")


def _shader_material(stage, path, identifier=None, mdl=None):
    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, path + "/S")
    if mdl:
        shader.SetSourceAsset(Sdf.AssetPath(mdl), "mdl")
    else:
        shader.CreateIdAttr(identifier)
    output = shader.CreateOutput("out", Sdf.ValueTypeNames.Token)
    material.CreateSurfaceOutput("mdl" if mdl else "mtlx").ConnectToSource(output)
    return material, shader


def test_a_control_that_the_reference_cannot_reproduce_makes_the_material_not_checkable():
    stage = Usd.Stage.CreateInMemory()
    # OpenPBR whose base_weight comes from another shader: the reference cannot reproduce it.
    material, shader = _shader_material(stage, "/W/Mapped", "ND_open_pbr_surface_surfaceshader")
    shader.CreateInput("base_color", Sdf.ValueTypeNames.Color3f).Set((0.2, 0.6, 0.2))
    weight = UsdShade.Shader.Define(stage, "/W/Mapped/Weight")
    weight.CreateIdAttr("ND_constant_float")
    shader.CreateInput("base_weight", Sdf.ValueTypeNames.Float).ConnectToSource(weight.CreateOutput("out", Sdf.ValueTypeNames.Float))
    expected, reason = probe.expected_albedo(material.GetPrim())
    assert expected is None and reason == "base_weight comes from another shader; the reference cannot reproduce it"
    # An MDL shader that sets more than its colour: the flat MDL reference reproduces only the colour.
    material, shader = _shader_material(stage, "/W/Omni", mdl="OmniPBR.mdl")
    shader.CreateInput("diffuse_color_constant", Sdf.ValueTypeNames.Color3f).Set((0.5, 0.5, 0.5))
    shader.CreateInput("albedo_brightness", Sdf.ValueTypeNames.Float).Set(0.0)
    expected, reason = probe.expected_albedo(material.GetPrim())
    assert expected is None and "the MDL shader sets albedo_brightness" in reason
    # An OpenPBR control of a type that the reference cannot write.
    material, shader = _shader_material(stage, "/W/Odd", "ND_open_pbr_surface_surfaceshader")
    shader.CreateInput("base_color", Sdf.ValueTypeNames.Color3f).Set((0.5, 0.5, 0.5))
    shader.CreateInput("odd", Sdf.ValueTypeNames.Matrix4d).Set(Gf.Matrix4d(1))
    expected, reason = probe.expected_albedo(material.GetPrim())
    assert expected is None and reason == "the reference cannot copy odd (matrix4d)"


@pytest.mark.parametrize("type_name,value,text", [
    ("float", 0.0, "0.0"), ("int", 3, "3"), ("bool", True, "1"), ("token", 'a "b"', '"a \\"b\\""'),
    ("color3f", (0.1, 0.2, 0.3), "(0.1, 0.2, 0.3)"), ("float2", (1, 2), "(1.0, 2.0)"),
    ("float", float("nan"), None), ("color3f", (1, 2), None), ("matrix4d", 1, None), ("float", None, None),
])
def test_usda_value(type_name, value, text):
    assert probe.usda_value(type_name, value) == text


def test_without_pillow_the_colour_of_an_image_is_not_known_and_that_is_not_a_failure(tmp_path, monkeypatch):
    """Review: without the optional image library, a healthy textured material became a texture failure."""

    from ovui_data_adapters.common import render_diagnostics_service

    stage = Usd.Stage.Open(_scene(tmp_path))
    monkeypatch.setitem(sys.modules, "PIL", None)  # Pillow is not installed
    expected, reason = probe.expected_albedo(stage.GetPrimAtPath(POTATO))
    assert expected is None and reason.startswith("the optional image library Pillow is not installed")
    todo, skipped = probe.plan(stage)
    result = probe.record_result({"materials": dict(skipped), "events": []})
    assert result["failures"] == [] and POTATO in result["unverified"]
    assert {e["kind"] for e in rd.get_render_diagnostics().events()} == {"unverified"}
    assert render_diagnostics_service.inspector_status()["degraded"] is False


@pytest.mark.requires_ovrtx
def test_real_renderer_shows_a_black_openpbr_with_zero_weights_as_right(tmp_path):
    """The material renders black, and so does its reference with the same controls: no false 'shown wrong'."""

    result = _check_saved_file(_greens_with_weights(tmp_path), tmp_path)
    assert result["materials"][GREENS]["state"] == "ok", result["materials"][GREENS]
    assert result["materials"][GREENS]["rendered"] == pytest.approx([0, 0, 0], abs=5)
    assert result["mismatches"] == []


@pytest.mark.parametrize("source,srgb", [(None, True), ("auto", True), ("sRGB", True), ("raw", False)])
def test_a_usduvtexture_image_is_decoded_as_its_source_colour_space_says(tmp_path, source, srgb):
    """Measured with the renderer: a UsdUVTexture with no colour space draws an 8-bit image as sRGB ('auto')."""

    from PIL import Image

    Image.new("RGB", (8, 8), (200, 30, 30)).save(tmp_path / "red.png")
    stage = Usd.Stage.CreateInMemory()
    material = UsdShade.Material.Define(stage, "/W/Tex")
    surface = UsdShade.Shader.Define(stage, "/W/Tex/Surface")
    surface.CreateIdAttr("UsdPreviewSurface")
    image = UsdShade.Shader.Define(stage, "/W/Tex/Image")
    image.CreateIdAttr("UsdUVTexture")
    image.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(str(tmp_path / "red.png")))
    if source:
        image.CreateInput("sourceColorSpace", Sdf.ValueTypeNames.Token).Set(source)
    surface.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).ConnectToSource(
        image.CreateOutput("rgb", Sdf.ValueTypeNames.Float3))
    material.CreateSurfaceOutput().ConnectToSource(surface.CreateOutput("surface", Sdf.ValueTypeNames.Token))
    expected, reason = probe.expected_albedo(material.GetPrim())
    assert reason == "" and expected["family"] == "preview" and expected["colour_input"] == "diffuseColor"
    red = expected["linear"][0]
    assert red == pytest.approx(probe._srgb_to_linear(200 / 255) if srgb else 200 / 255)
