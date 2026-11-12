# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The per-material report: authored data and renderer state are kept apart."""

from __future__ import annotations

import logging
import pathlib
import subprocess
import sys

import pytest
from pxr import Usd

from ovui_data_adapters.common import render_diagnostics as rd
from ovui_data_adapters.common import render_material_report as report_module
from ovui_data_adapters.common import render_native_log as nl

GENERATOR = pathlib.Path(__file__).resolve().parents[1] / "data" / "make_material_regression_scene.py"
WHITEWASH = "/World/Kitchen/W1_Looks/PeruSurfaceV1/Whitewash"
RUNNER = "/World/Kitchen/W1_Looks/PeruReviewV2/CrimsonRunner"
POTATO = "/World/Kitchen/W4_FoodProduce_v1/Looks/PotatoRed"
GREENS = "/World/Kitchen/Looks/Greens"
BLUES = "/World/Kitchen/Looks/Blues"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(rd, "_DIAGNOSTICS", rd.RenderDiagnostics())
    monkeypatch.setattr(rd, "_VERIFICATION", {})
    monkeypatch.setattr(nl, "_GENERATED_DIRS", [])


def _scene(tmp_path, *breaks):
    command = [sys.executable, str(GENERATOR), str(tmp_path)]
    for kind in breaks:
        command += ["--break", kind]
    subprocess.run(command, check=True, capture_output=True)
    return Usd.Stage.Open(str(tmp_path / "kitchen.usda"))


def _by_path(report):
    return {m["path"]: m for m in report["materials"]}


def test_without_a_renderer_nothing_is_reported_as_compiled(tmp_path):
    """The authored block is not the renderer's state: with no renderer, the renderer block is empty."""

    materials = _by_path(report_module.describe_materials(_scene(tmp_path)))
    whitewash, potato = materials[WHITEWASH], materials[POTATO]
    assert whitewash["authored"]["context"] == potato["authored"]["context"] == "materialx"
    assert whitewash["authored"]["shader_identifier"] == "ND_open_pbr_surface_surfaceshader"
    for entry in materials.values():
        assert entry["renderer"] == {"observed_context": None, "compiled_module": None, "inferred_compiled_module": None}
        assert entry["render_check"] == {"state": "not_run"}
        assert all(t["residency"] == "not_reported" for t in entry["textures"])
    runner = materials[RUNNER]
    assert runner["authored"]["context"] == "mdl"
    assert runner["authored"]["shader_identifier"] == "./peru_runner_diamond_v1.mdl#peru_runner"
    assert any("all connect to one shader" in w for w in runner["warnings"])


def test_the_generated_module_names_its_origin_and_the_equal_graphs_that_share_it(tmp_path):
    stage = _scene(tmp_path)
    module = tmp_path / "modules" / "module_a"
    module.mkdir(parents=True)
    origins = "".join(f'    materialx::core::origin("{GREENS}/{n}.file")\n' for n in ("albedo", "normal_tex"))
    (module / "materialx.mdl").write_text("export material omniMaterial()\n" + origins)
    nl.register_generated_modules_dir(str(tmp_path / "modules"))
    materials = _by_path(report_module.describe_materials(stage))
    owner = materials[GREENS]["renderer"]
    assert owner["observed_context"] == "materialx"
    assert owner["compiled_module"]["id"] == "module_a"
    assert owner["compiled_module"]["origin_materials"] == [GREENS]
    assert owner["compiled_module"]["how"].startswith("origin annotation")
    shared = materials[POTATO]["renderer"]
    # an equal graph is not an observation: the module is shown apart, and the context stays unobserved
    assert shared["compiled_module"] is None and shared["observed_context"] is None
    assert shared["inferred_compiled_module"]["id"] == "module_a" and shared["inferred_compiled_module"]["how"].startswith("inferred")
    assert any("Whether this material uses it is not reported" in w for w in materials[POTATO]["warnings"])
    assert materials[RUNNER]["renderer"]["compiled_module"] is None  # native MDL: no generated module


def test_a_material_with_no_surface_output_is_logged_and_recorded(caplog):
    stage = Usd.Stage.CreateInMemory()
    from pxr import UsdShade

    UsdShade.Material.Define(stage, "/World/Looks/NoSurface")
    with caplog.at_level(logging.WARNING, logger="ovui.render_diagnostics"):
        entry = report_module.describe_materials(stage)["materials"][0]
    assert any("fallback" in w for w in entry["warnings"])
    assert "material /World/Looks/NoSurface" in caplog.text and "(select)" in caplog.text
    assert [(e["material"], e["kind"]) for e in rd.get_render_diagnostics().events()] == [("/World/Looks/NoSurface", "select")]
    assert entry["events"][0]["kind"] == "select"


def test_a_failure_that_names_a_file_is_linked_to_each_material_that_uses_it(tmp_path):
    stage = _scene(tmp_path)
    rd.get_render_diagnostics().record(
        rd.SCENE, f"file:{tmp_path}/PotatoRed.png", "texture", "Couldn't process file: STB Failed to load image info")
    rd.get_render_diagnostics().record(
        rd.SCENE, f"file:{tmp_path}/peru_runner_diamond_v1.mdl", "mdl", "[MDLC:COMPILER] error: C109")
    materials = _by_path(report_module.describe_materials(stage))
    assert [e["kind"] for e in materials[POTATO]["events"]] == ["texture"]
    assert [e["kind"] for e in materials[RUNNER]["events"]] == ["mdl"]
    assert materials[WHITEWASH]["events"] == [] and materials[GREENS]["events"] == []
    assert [t["residency"] for t in materials[POTATO]["textures"] if t["uri"] == "./PotatoRed.png"] == ["failed"]
    other = [t["residency"] for t in materials[GREENS]["textures"]]
    assert "failed" not in other


def test_a_file_event_does_not_match_a_file_of_the_same_name_in_another_folder(tmp_path):
    stage = _scene(tmp_path)
    rd.get_render_diagnostics().record(rd.SCENE, "file:/elsewhere/PotatoRed.png", "texture", "failed")
    assert _by_path(report_module.describe_materials(stage))[POTATO]["events"] == []


def test_a_memory_failure_marks_every_material_unknown_and_attributes_none(tmp_path):
    """Nothing in the event names a material: do not invent one (decision recorded in the docs)."""

    stage = _scene(tmp_path)
    nl.parse_native_log_line(
        "2026-10-24T16:40:00Z [9,000ms] [Error] [omni.rtx] Failed to allocate 4096 MB: out of memory",
        context=f"{GREENS}/OpenPBR")
    report = report_module.describe_materials(stage)
    assert [(e["kind"], e["scope"], e["context"]) for e in report["scene_events"]] == [("memory", "scene", f"{GREENS}/OpenPBR")]
    assert "not attributed" in report["scene_event_note"]
    for entry in report["materials"]:
        assert entry["events"] == [] and entry["scene_wide_failures"] == 1
        assert any("scene-wide failure" in w for w in entry["warnings"])
        assert all(t["residency"] == "unknown" for t in entry["textures"])


def test_a_failed_step_is_scene_wide_too(tmp_path):
    stage = _scene(tmp_path)
    rd.get_render_diagnostics().record(rd.SCENE, "", "step", "Renderer.step failed: RuntimeError: x", context="")
    report = report_module.describe_materials(stage)
    assert report["scene_events"][0]["kind"] == "step"
    assert all(e["scene_wide_failures"] == 1 for e in report["materials"])


def test_the_render_check_result_is_part_of_the_report_and_is_not_residency(tmp_path):
    stage = _scene(tmp_path)
    rd.set_verification({
        GREENS: {"state": "ok", "resources": ["./Greens.png"], "difference": 1},
        BLUES: {"state": "mismatch", "resources": ["./Blues.png"], "difference": 80},
    })
    materials = _by_path(report_module.describe_materials(stage))
    assert materials[GREENS]["render_check"]["state"] == "ok"
    assert materials[BLUES]["render_check"]["state"] == "mismatch"
    # a matching colour shows that the picture is right; it does not say that a texture is resident
    for path in (GREENS, BLUES):
        assert {t["residency"] for t in materials[path]["textures"]} == {"not_reported"}


def test_graphs_that_are_equal_but_have_other_textures_point_to_the_render_check(tmp_path):
    materials = _by_path(report_module.describe_materials(_scene(tmp_path)))
    assert any("run the material_verify command" in w for w in materials[GREENS]["warnings"])
    assert not any("share one graph" in w for w in materials[RUNNER]["warnings"])


@pytest.mark.parametrize("event,uri,resolved,expected", [
    ("file:/a/b/c.png", "./c.png", "", True),
    ("/a/b/c.png", "c.png", "", True),
    ("/a/b/c.png", "x/c.png", "", False),
    ("/a/b/c.png", "./c.png", "/a/b/c.png", True),
    ("/a/other/c.png", "./c.png", "/a/b/c.png", False),
    ("", "./c.png", "", False),
    ("https://h/c.png", "https://h/c.png", "", False),
])
def test_same_resource(event, uri, resolved, expected):
    assert report_module.same_resource(event, uri, resolved) is expected


def test_the_report_says_what_the_renderer_does_not_report(tmp_path):
    """Without the material messages (no renderer here) the module of each material is listed as not reported."""

    report = report_module.describe_materials(_scene(tmp_path))
    not_reported = report["renderer_reports"]["not_reported"]
    assert any("the module and the output that each material uses" in item for item in not_reported)
    assert any("resident" in item for item in not_reported)
    assert report["renderer_reports"]["material_messages"]["active"] is False


# The two forms of the material messages, with made-up module names and times.
_WHITEWASH_STORED = (
    "Stored MdlEntitySnapshot to DB: usd::rtx_scope0::/World/Kitchen/W1_Looks/PeruSurfaceV1/Whitewash/OpenPBR::::"
    "omni_mtlx_whitewash::materialx::omniMaterial((10))"
)
_RUNNER_GENERATED = (
    "Generation of /scene/peru_runner_diamond_v1.mdl//World/Kitchen/W1_Looks/PeruReviewV2/CrimsonRunner/mdl "
    "took 0.5 sec (in task queue for 0.25 sec)"
)


@pytest.fixture
def messages(monkeypatch):
    from ovui_data_adapters.common import render_telemetry as rt

    store = rt.MaterialMessages()
    monkeypatch.setattr(rt, "_MESSAGES", store)
    monkeypatch.setitem(rt._STATE, "installed", True)
    monkeypatch.setitem(rt._STATE, "reason", "")
    return store


def test_the_renderer_block_comes_from_the_renderer_messages(tmp_path, messages):
    """The compiled module and the output used are what the renderer named, not the authored data."""

    stage = _scene(tmp_path)
    assert messages.take(_WHITEWASH_STORED) and messages.take(_RUNNER_GENERATED)
    report = report_module.describe_materials(stage)
    materials = _by_path(report)
    whitewash = materials[WHITEWASH]["renderer"]
    assert whitewash["generation"] == "reported"
    assert whitewash["compiled_module"]["id"] == "omni_mtlx_whitewash::materialx::omniMaterial"
    assert whitewash["observed_context"] == "materialx"
    # CrimsonRunner: the universal, MDL and MaterialX outputs all connect to the one MDL shader prim, so the
    # renderer's message names the module but not the output.
    runner = materials[RUNNER]
    assert runner["renderer"]["compiled_module"]["id"] == "/scene/peru_runner_diamond_v1.mdl"
    assert runner["renderer"]["observed_context"] is None
    assert set(runner["renderer"]["candidate_contexts"]) == set(runner["authored"]["outputs"]) and len(runner["authored"]["outputs"]) > 1
    assert any("does not say which output" in w for w in runner["warnings"])
    # A material that the renderer named nothing for is not filled from an equal graph.
    potato = materials[POTATO]["renderer"]
    assert potato["generation"] == "not_reported" and potato["compiled_module"] is None
    assert potato["inferred_compiled_module"] is None
    assert any("module that the renderer generated code from" in item for item in report["renderer_reports"]["reported"])


def test_the_report_counts_the_materials_after_its_limit(tmp_path):
    report = report_module.describe_materials(_scene(tmp_path), limit=2)
    assert report["count"] == 2 and report["total"] == 5 and report["truncated"] is True


def test_every_missing_file_is_an_event_with_its_material_without_a_limit(tmp_path):
    """The renderer does not always report a missing texture (it can draw a fallback and write no line)."""

    healthy = report_module.record_file_events(report_module.shader_files(_scene(tmp_path / "good")))
    assert healthy == {"missing": 0, "linked": 0} and rd.get_render_diagnostics().events() == []
    files = report_module.shader_files(_scene(tmp_path / "broken", "missing-texture"))
    assert report_module.record_file_events(files) == {"missing": 1, "linked": 0}
    (event,) = rd.get_render_diagnostics().events()
    assert (event["material"], event["kind"], event["scope"]) == (POTATO, "texture", "material")
    assert event["resource"].endswith("PotatoRed.png") and "texture" in event["message"]


def test_a_renderer_failure_that_names_only_a_file_is_recorded_for_each_material_that_uses_it(tmp_path):
    """``Couldn't process file:...`` names no prim: the warning and health then name the material too."""

    stage = _scene(tmp_path)
    files = report_module.shader_files(stage)
    potato_albedo = next(f for f in files if f["material"] == POTATO and f["uri"].endswith("PotatoRed.png"))
    message = f"[omni.rtx] Couldn't process file:{potato_albedo['resolved']}, it might not have written completely."
    rd.get_render_diagnostics().record(rd.SCENE, f"file:{potato_albedo['resolved']}", "texture", message)
    assert report_module.record_file_events(files) == {"missing": 0, "linked": 1}
    linked = [e for e in rd.get_render_diagnostics().events() if e["scope"] == "material"]
    assert [(e["material"], e["resource"], e["kind"], e["message"]) for e in linked] == [
        (POTATO, potato_albedo["uri"], "texture", message)
    ]


def test_a_file_that_many_materials_use_names_only_some_of_them(tmp_path):
    """Factory: one broken MDL module used by 712 materials filled the event list and pushed out other failures."""

    files = [{"material": f"/W/Looks/M{i:02d}", "uri": "./grid.mdl", "resolved": "/s/grid.mdl", "kind": "mdl",
              "missing": None} for i in range(15)]
    files += [{"material": f"/W/Looks/T{i:02d}", "uri": "./gone.png", "resolved": "", "kind": "texture",
               "missing": "unresolved"} for i in range(12)]
    rd.get_render_diagnostics().record(rd.SCENE, "file:/s/grid.mdl", "mdl", "[MDLC:COMPILER] error: file:/s/grid.mdl(12,49)")
    counts = report_module.record_file_events(files)
    limit = report_module.FILE_EVENT_MATERIALS
    assert counts == {"missing": limit, "linked": limit}
    events = rd.get_render_diagnostics().events()
    linked = [e for e in events if e["scope"] == "material" and e["kind"] == "mdl"]
    assert len(linked) == limit and all(e["message"].endswith("(15 materials use this file)") for e in linked)
    missing = [e for e in events if e["kind"] == "texture"]
    assert len(missing) == limit and missing[0]["message"] == "texture unresolved: ./gone.png (12 materials use this file)"
