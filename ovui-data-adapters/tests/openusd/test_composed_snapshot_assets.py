# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""The composed renderer snapshot resolves assets exactly as the authored stage."""

import os
from pathlib import Path

import pytest
from pxr import Sdf, Usd, UsdLux, UsdShade

from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter


@pytest.fixture
def scene(tmp_path):
    root = tmp_path / "scene"
    for asset in ("env/sky.hdr", "tex/wood.png", "mdl/Glaze.mdl", "env/file.hdr"):
        (root / asset).parent.mkdir(parents=True, exist_ok=True)
        (root / asset).write_bytes(b"x")
    stage = Usd.Stage.CreateNew(str(root / "root.usda"))
    UsdLux.DomeLight.Define(stage, "/World/FileDome").CreateTextureFileAttr("./env/file.hdr")
    live = Sdf.Layer.CreateAnonymous("live_worker1")  # Stands in for an ovlive layer.
    stage.GetSessionLayer().subLayerPaths.append(live.identifier)
    with Usd.EditContext(stage, live):
        UsdLux.DomeLight.Define(stage, "/World/Dome").CreateTextureFileAttr("./env/sky.hdr")
        shader = UsdShade.Shader.Define(stage, "/World/Looks/Glaze/Shader")
        shader.GetPrim().CreateAttribute(
            "info:mdl:sourceAsset", Sdf.ValueTypeNames.Asset
        ).Set("./mdl/Glaze.mdl")
        UsdLux.DomeLight.Define(stage, "/World/Remote").CreateTextureFileAttr(
            "https://example.com/sky.hdr"
        )
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        texture = UsdShade.Shader.Define(stage, "/World/Looks/Wood/Tex")
        texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set("./tex/wood.png")
    return stage, root, live


def snapshot(stage):
    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    path = adapter._export_composed_stage_snapshot(stage)
    try:
        # Copy it into memory and release the file: Windows cannot delete a
        # Crate file that USD still has open (memory-mapped).
        crate = Sdf.Layer.OpenAsAnonymous(path)
        layer = Sdf.Layer.CreateAnonymous("snapshot.usda")
        layer.TransferContent(crate)
        del crate
        return path, layer
    finally:
        os.unlink(path)


def value(layer, attribute):
    return layer.GetAttributeAtPath(attribute).default.path


def test_session_and_live_layer_assets_resolve_like_the_stage(scene):
    stage, root, live = scene
    before = (live.ExportToString(), stage.GetSessionLayer().ExportToString())
    _path, layer = snapshot(stage)
    for attribute in (
        "/World/Dome.inputs:texture:file",
        "/World/Looks/Glaze/Shader.info:mdl:sourceAsset",
        "/World/Looks/Wood/Tex.inputs:file",
        "/World/FileDome.inputs:texture:file",
    ):
        expected = stage.GetAttributeAtPath(attribute).Get().resolvedPath
        assert expected and Path(value(layer, attribute)) == Path(expected)
    assert value(layer, "/World/Remote.inputs:texture:file") == "https://example.com/sky.hdr"
    # Only the disposable snapshot is rewritten.
    assert (live.ExportToString(), stage.GetSessionLayer().ExportToString()) == before


def test_in_memory_root_keeps_relative_paths_instead_of_failing():
    stage = Usd.Stage.CreateInMemory()
    live = Sdf.Layer.CreateAnonymous("live")
    stage.GetSessionLayer().subLayerPaths.append(live.identifier)
    with Usd.EditContext(stage, live):
        UsdLux.DomeLight.Define(stage, "/Dome").CreateTextureFileAttr("./sky.hdr")
    _path, layer = snapshot(stage)
    assert value(layer, "/Dome.inputs:texture:file") == "./sky.hdr"
