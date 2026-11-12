# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The memory check of a pxr stage: only the prims of the application make no scene content."""

from __future__ import annotations

import pytest
from pxr import Sdf, Usd

from ovui_data_adapters.common import render_diagnostics as rd


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """The report of the last check and the reading before the renderer are module state: start empty."""

    monkeypatch.setattr(rd, "_RESOURCE_REPORT", {"checked": False, "warnings": []})
    monkeypatch.setattr(rd, "_GPU_BEFORE_RENDERER", None)


def test_only_the_application_prims_make_no_scene_content_also_in_session_layers(tmp_path, monkeypatch):
    """The viewport scaffolding under /OvGearSession is no content; scene prims in a session sublayer are."""

    monkeypatch.setenv(rd.MIN_GPU_MEMORY_ENV, "64")
    monkeypatch.delenv(rd.STRICT_ENV, raising=False)
    gpu = rd.GpuMemory(int(47.4 * rd.GIB), 0, int(47.4 * rd.GIB), "RTX PRO 6000", True, "nvml")
    monkeypatch.setattr(rd, "read_gpu_memory", lambda index=0: gpu)
    monkeypatch.setattr(rd, "read_host_memory", lambda: rd.HostMemory(128 * rd.GIB, 0, "cgroup2"))
    path = tmp_path / "empty.usda"
    path.write_text("#usda 1.0\n")
    stage = Usd.Stage.Open(str(path))
    live = Sdf.Layer.CreateAnonymous("live-session.usda")
    stage.GetSessionLayer().subLayerPaths.append(live.identifier)
    stage.SetEditTarget(stage.GetSessionLayer())
    stage.DefinePrim("/OvGearSession/Cameras/Main", "Camera")
    stage.SetEditTarget(Usd.EditTarget(live))
    stage.DefinePrim("/OvGearSession/Lights/FallbackDome", "DomeLight")
    own = ("/OvGearSession",)
    assert not rd.scene_has_prims(stage, own) and rd.scene_has_prims(stage)
    assert rd.check_stage_resources(stage, own) == [] and rd.last_resource_report()["scene_empty"] is True
    stage.DefinePrim("/World/Cube", "Cube")  # live scene content in the session sublayer, over an empty root
    assert rd.scene_has_prims(stage, own)
    (warning,) = rd.check_stage_resources(stage, own)
    assert "below the minimum of 64 GiB" in warning and rd.last_resource_report()["scene_empty"] is False
