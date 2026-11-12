# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The OVStage adapter has the same material check and report as the OpenUSD adapter, without OpenUSD."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ovui_data_adapters.common import render_diagnostics as rd
from ovui_data_adapters.common import render_probe as probe
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter

GENERATOR = Path(__file__).resolve().parents[1] / "data" / "make_material_regression_scene.py"
RUNNER = "/World/Kitchen/W1_Looks/PeruReviewV2/CrimsonRunner"
POTATO = "/World/Kitchen/W4_FoodProduce_v1/Looks/PotatoRed"


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


def _bare_adapter():
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._file_check_due, adapter._live_check_due, adapter._strict_refusal = False, True, None
    return adapter


def test_a_check_that_cannot_run_is_reported_and_only_strict_mode_raises(monkeypatch, caplog):
    adapter = _bare_adapter()
    adapter.verify_materials_live = lambda: (_ for _ in ()).throw(RuntimeError("the scene has no source file"))
    monkeypatch.setenv(probe.VERIFY_ENV, "1")
    with caplog.at_level("ERROR", logger="ovui.render_diagnostics"):
        adapter._after_first_frames()
    assert "the material check could not run: RuntimeError: the scene has no source file" in caplog.text
    (event,) = rd.get_render_diagnostics().events()
    assert (event["kind"], event["scope"]) == ("unverified", "scene")  # not silent: health is degraded
    monkeypatch.setenv(probe.VERIFY_ENV, "strict")
    adapter._live_check_due = True
    with pytest.raises(RuntimeError, match="no source file"):
        adapter._after_first_frames()


def test_strict_mode_keeps_the_refusal_for_every_frame(monkeypatch):
    adapter = _bare_adapter()
    wrong = {"materials": {}, "failures": ["/M: shown wrong (91 off)"], "unverified": [], "mismatches": ["/M"]}
    adapter.verify_materials_live = lambda: wrong
    monkeypatch.setenv(probe.VERIFY_ENV, "strict")
    with pytest.raises(probe.MaterialMismatchError, match="/M: shown wrong"):
        adapter._after_first_frames()
    assert isinstance(adapter._strict_refusal, probe.MaterialMismatchError)  # render_frame raises it at every frame


INSPECTOR = str(Path(__file__).resolve().parents[3] / "skills" / "omniverse-ui-inspector")

RUN_SCRIPT = """
import asyncio, json, sys, time
from types import SimpleNamespace
import numpy as np
class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name == "pxr" or name.startswith("pxr."):
            raise ImportError("OpenUSD is not installed in this environment: " + name)
        return None
sys.meta_path.insert(0, Blocker())  # a native-only install
from ovui_data_adapters.ovstage.provider import PROVIDER_ENTRY_POINT_VALUE, PROVIDER_NAME, create_provider_session
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.common import render_diagnostics as rd
runtime = load_required_runtimes(module_name=PROVIDER_NAME, entry_point_value=PROVIDER_ENTRY_POINT_VALUE)
session = create_provider_session(runtime=runtime)
scene = session.open_stage(sys.argv[1])
adapter = OvstageRendererAdapter()
adapter.load_stage(scene)
view = np.eye(4); view[3, 2] = -34.0
proj = np.array([[2.4, 0, 0, 0], [0, 4.27, 0, 0], [0, 0, -1.0002, -1], [0, 0, -0.020002, 0]])
def frames():
    for _ in range(4):
        adapter.render_frame(320, 180, view, proj); time.sleep(0.2)
frames()
out = {"after_first_frames": {p: [i["state"], i.get("difference")] for p, i in rd.get_verification().items()}}
if len(sys.argv) > 2:
    # The Inspector commands of an application whose renderer is this adapter, as USD Viewer gives it.
    from ovui_data_adapters.common.render_diagnostics_service import inspector_commands
    commands = {c.name: c for c in inspector_commands(SimpleNamespace(get_renderer_adapter=lambda: adapter))}
    path = "/World/Kitchen/W1_Looks/PeruReviewV2/CrimsonRunner/mdl"
    pa = OvstagePropertyAdapter(scene, [path])
    pa.begin_edit("inputs:diffuse_color_constant"); pa.set_value("inputs:diffuse_color_constant", (0.05, 0.2, 0.7)); pa.end_edit("inputs:diffuse_color_constant")
    frames()
    async def verify():
        task = asyncio.ensure_future(commands["material_verify"].handler(timeout=300))
        while not task.done():
            adapter.render_frame(320, 180, view, proj)
            await asyncio.sleep(0.05)
        return task.result()
    result = asyncio.run(verify())
    out["mode"] = result["mode"]
    out["after_edit"] = {p: [i["state"], i.get("difference")] for p, i in result["materials"].items()}
    report = commands["render_diagnostics"].handler()
    out["report"] = {m["path"]: [m["authored"]["context"], m["authored"]["shader_identifier"],
                                 [t["uri"] for t in m["textures"]], m["render_check"]["state"]] for m in report["materials"]}
out["pxr_imported"] = "pxr" in sys.modules and sys.modules["pxr"] is not None
adapter.shutdown(); session.shutdown_scene()
print("RESULT " + json.dumps(out))
"""


def _run_native(scene, *extra, verify=""):
    import json
    import os

    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [INSPECTOR, os.environ.get("PYTHONPATH", "")])),
               OVUIINSPECT_ENABLED="0")
    env.pop(probe.VERIFY_ENV, None)
    if verify:
        env[probe.VERIFY_ENV] = verify
    done = subprocess.run([sys.executable, "-c", RUN_SCRIPT, scene, *extra], capture_output=True, text=True,
                          timeout=900, env=env)
    lines = [line for line in done.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, (done.stdout[-800:], done.stderr[-800:])
    return json.loads(lines[-1][len("RESULT "):])


@pytest.mark.requires_ovrtx
@pytest.mark.requires_ovstage
def test_real_native_only_commands_run_without_openusd_on_the_scene_as_it_is_shown(tmp_path):
    """No OpenUSD in the process (the import is blocked). The report and the check of the Inspector commands come
    from the attached native scene, and an edit made after the scene was opened is judged as it is now."""

    result = _run_native(_scene(tmp_path / "flat", "flat-colors", "frame"), "edit", verify="1")
    assert result["pxr_imported"] is False
    after_first = result["after_first_frames"]
    assert {state for state, _ in after_first.values()} == {"ok"} and len(after_first) == 7  # the frame too
    assert result["mode"] == "in the application's renderer (OvstageRendererAdapter)"
    edited = result["after_edit"][RUNNER]
    assert edited[0] == "ok" and edited[1] <= 6  # expected colour = the edited colour, not the saved one
    context, identifier, uris, check = result["report"][RUNNER]
    assert context == "mdl" and identifier.endswith("peru_runner_diamond_v1.mdl#peru_runner")
    assert check == "ok" and any(uri.endswith("peru_runner_diamond_v1.mdl") for uri in uris)


@pytest.mark.requires_ovrtx
@pytest.mark.requires_ovstage
def test_real_native_check_runs_only_when_asked_and_finds_a_broken_mdl(tmp_path):
    scene = _scene(tmp_path / "broken", "broken-mdl", "corrupt-texture")
    assert _run_native(scene)["after_first_frames"] == {}  # by default no check draws extra frames
    result = _run_native(scene, verify="1")["after_first_frames"]
    assert result[RUNNER][0] == "mismatch"
    assert result[POTATO][0] == "unverifiable"  # its colour is an image: the native check reads constant colours only
