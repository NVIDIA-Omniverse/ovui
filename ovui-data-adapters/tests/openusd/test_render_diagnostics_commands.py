# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The render diagnostics Inspector commands with an application that shows an OpenUSD stage."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pxr import Sdf, Usd, UsdShade

from ovui_data_adapters.common import render_diagnostics as rd
from ovui_data_adapters.common import render_diagnostics_service as service_module

GENERATOR = Path(__file__).resolve().parents[1] / "data" / "make_material_regression_scene.py"
POTATO = "/World/Kitchen/W4_FoodProduce_v1/Looks/PotatoRed"


@pytest.fixture(autouse=True)
def _inspector(monkeypatch, request):
    monkeypatch.setenv("OVUIINSPECT_ENABLED", "0")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "skills" / "omniverse-ui-inspector"))
    request.addfinalizer(lambda: [sys.modules.pop(n) for n in [n for n in sys.modules if n.split(".")[0] == "ovuiinspect"]])
    monkeypatch.setattr(rd, "_DIAGNOSTICS", rd.RenderDiagnostics())
    monkeypatch.setattr(rd, "_VERIFICATION", {})
    monkeypatch.setattr(rd, "_RESOURCE_REPORT", {"checked": False, "warnings": []})


@pytest.fixture
def scene(tmp_path):
    subprocess.run([sys.executable, str(GENERATOR), str(tmp_path)], check=True, capture_output=True)
    return str(tmp_path / "kitchen.usda")


def test_the_report_describes_the_open_stage_with_its_unsaved_edit_and_never_opens_the_file_again(scene, monkeypatch):
    stage = Usd.Stage.Open(scene)
    albedo = UsdShade.Shader.Get(stage, POTATO + "/albedo").GetInput("file")
    albedo.Set(Sdf.AssetPath("./edited_not_saved.png"))  # an unsaved edit: the file on disk still names PotatoRed.png
    application = SimpleNamespace(_stage_adapter=SimpleNamespace(stage=stage), _current_file_path=scene)

    def no_second_copy(*_args, **_kwargs):
        raise AssertionError("the command opened the scene file a second time")

    monkeypatch.setattr(Usd.Stage, "Open", no_second_copy)
    commands = {c.name: c for c in service_module.inspector_commands(application)}
    assert set(commands) == {"render_diagnostics", "material_verify", "gpu_memory"}
    assert all(c.read_only for c in commands.values())
    report = commands["render_diagnostics"].handler(path_prefix="/World/Kitchen/W4")
    [potato] = report["materials"]
    assert potato["path"] == POTATO
    uris = [t["uri"] for t in potato["textures"]]
    assert "./edited_not_saved.png" in uris and "./PotatoRed.png" not in uris
    assert "texture unresolved: ./edited_not_saved.png" in potato["warnings"]
