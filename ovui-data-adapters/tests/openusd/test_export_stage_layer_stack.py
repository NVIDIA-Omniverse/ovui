# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""File > Save and Save As keep the layer stack of the stage."""

from __future__ import annotations

import pathlib

import pytest
from ovui_data_adapters.openusd.provider import OpenUSDProviderSession
from pxr import Sdf, Usd, UsdGeom

_SUBLAYER_PATH = "./SubUSDs/Car_Lift.usda"


def _write_sublayer(path) -> Sdf.Layer:
    """A sublayer with an instance, as the car lift of the issue has."""
    layer = Sdf.Layer.CreateNew(str(path))
    stage = Usd.Stage.Open(layer)
    UsdGeom.Xform.Define(stage, "/World/Prototypes/Post")
    UsdGeom.Cube.Define(stage, "/World/Prototypes/Post/Mesh")
    instance = UsdGeom.Xform.Define(stage, "/World/Geometry/Post_A").GetPrim()
    instance.GetReferences().AddInternalReference("/World/Prototypes/Post")
    instance.SetInstanceable(True)
    assert layer.Save()
    return layer


def _stage_with_sublayer(tmp_path, sublayer_path: str):
    session = OpenUSDProviderSession()
    source_dir = tmp_path / "source"
    (source_dir / "SubUSDs").mkdir(parents=True)
    sublayer = _write_sublayer(source_dir / "SubUSDs" / "Car_Lift.usda")
    stage = session.create_stage(str(source_dir / "NewStage.usda"))
    UsdGeom.Mesh.Define(stage, "/World/Cube")
    stage.GetRootLayer().subLayerPaths.append(sublayer_path)
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        UsdGeom.Scope.Define(stage, "/OvGearSession")
    return session, stage, sublayer


def _file_paths(asset_paths) -> list[pathlib.Path]:
    """The asset paths as file paths of this platform.

    On Windows, USD writes an anchored path with "/", and ``realPath`` has
    "\\". Paths of the same file are equal as ``pathlib.Path`` objects. A
    relative path is not equal to an absolute path.
    """
    return [pathlib.Path(asset_path) for asset_path in asset_paths]


def test_save_as_keeps_the_sublayer_and_writes_only_root_layer_prims(tmp_path) -> None:
    session, stage, sublayer = _stage_with_sublayer(tmp_path, _SUBLAYER_PATH)
    saved_dir = tmp_path / "saved"
    saved_dir.mkdir()
    saved_path = saved_dir / "lift.usd"

    session.export_stage(stage, str(saved_path))

    saved = Sdf.Layer.FindOrOpen(str(saved_path))
    # The relative sublayer path is anchored to the directory of the source
    # root, so the saved file in another directory uses the same file.
    assert _file_paths(saved.subLayerPaths) == _file_paths([sublayer.realPath])
    assert [prim.name for prim in saved.rootPrims] == ["World"]
    world = saved.GetPrimAtPath("/World")
    assert [prim.name for prim in world.nameChildren] == ["Cube"]

    reopened = Usd.Stage.Open(str(saved_path))
    assert reopened.GetPrimAtPath("/World/Geometry/Post_A").IsInstance()


def test_save_as_into_another_folder_keeps_the_sublayer_timing(tmp_path) -> None:
    session, stage, sublayer = _stage_with_sublayer(tmp_path, _SUBLAYER_PATH)
    stage.GetRootLayer().subLayerOffsets[0] = Sdf.LayerOffset(3, 2)
    timed = Sdf.CreatePrimInLayer(sublayer, "/World/Geometry/Timed")
    timed.specifier = Sdf.SpecifierDef
    value = Sdf.AttributeSpec(timed, "value", Sdf.ValueTypeNames.Double)
    sublayer.SetTimeSample(value.path, 1, 10.0)
    sublayer.SetTimeSample(value.path, 2, 20.0)
    saved_dir = tmp_path / "saved"
    saved_dir.mkdir()
    saved_path = saved_dir / "timing.usd"

    session.export_stage(stage, str(saved_path))

    saved = Sdf.Layer.FindOrOpen(str(saved_path))
    assert _file_paths(saved.subLayerPaths) == _file_paths([sublayer.realPath])
    assert list(saved.subLayerOffsets) == [Sdf.LayerOffset(3, 2)]
    reopened = Usd.Stage.Open(str(saved_path))
    timed_value = reopened.GetPrimAtPath("/World/Geometry/Timed").GetAttribute("value")
    assert timed_value.GetTimeSamples() == [5.0, 7.0]
    assert timed_value.Get(5) == 10.0


def test_save_in_the_root_directory_keeps_relative_sublayer_paths(tmp_path) -> None:
    session, stage, _sublayer = _stage_with_sublayer(tmp_path, _SUBLAYER_PATH)
    saved_path = tmp_path / "source" / "Saved.usda"

    session.export_stage(stage, str(saved_path))

    saved = Sdf.Layer.FindOrOpen(str(saved_path))
    assert list(saved.subLayerPaths) == [_SUBLAYER_PATH]


def test_save_as_first_saves_a_changed_sublayer(tmp_path) -> None:
    session, stage, sublayer = _stage_with_sublayer(tmp_path, _SUBLAYER_PATH)
    with Usd.EditContext(stage, sublayer):
        UsdGeom.Xform.Define(stage, "/World/Geometry/MovedInSublayer")
    assert sublayer.dirty
    saved_path = tmp_path / "lift.usda"

    session.export_stage(stage, str(saved_path))

    assert not sublayer.dirty
    on_disk = Sdf.Layer.OpenAsAnonymous(sublayer.realPath)
    assert on_disk.GetPrimAtPath("/World/Geometry/MovedInSublayer") is not None
    reopened = Usd.Stage.Open(str(saved_path))
    assert reopened.GetPrimAtPath("/World/Geometry/MovedInSublayer").IsValid()


def test_save_as_refuses_an_anonymous_sublayer_and_writes_nothing(tmp_path) -> None:
    session, stage, _sublayer = _stage_with_sublayer(tmp_path, _SUBLAYER_PATH)
    anonymous = Sdf.Layer.CreateAnonymous("unsaved.usda")
    Sdf.CreatePrimInLayer(anonymous, "/World/OnlyInMemory")
    stage.GetRootLayer().subLayerPaths.append(anonymous.identifier)
    saved_path = tmp_path / "lift.usda"

    with pytest.raises(RuntimeError, match="anonymous layers") as raised:
        session.export_stage(stage, str(saved_path))

    # The error names the rows of the Layers window, not the identifier.
    assert "'anonymous' under 'NewStage.usda'" in str(raised.value)
    assert anonymous.identifier not in str(raised.value)
    assert not saved_path.exists()


def test_save_as_of_an_in_memory_root_keeps_its_relative_sublayers(
    tmp_path, monkeypatch
) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    sublayers = []
    for name, prim_path in (("strong", "/World/Strong"), ("weak", "/World/Weak")):
        layer = Sdf.Layer.CreateNew(str(source_dir / f"{name}.usda"))
        Sdf.CreatePrimInLayer(layer, prim_path).specifier = Sdf.SpecifierDef
        assert layer.Save()
        sublayers.append(layer)
    # The relative sublayer paths of an in-memory root resolve from the
    # current directory.
    monkeypatch.chdir(source_dir)
    stage = Usd.Stage.CreateInMemory()
    stage.GetRootLayer().subLayerPaths.append("./strong.usda")
    stage.GetRootLayer().subLayerPaths.append("./weak.usda")
    saved_dir = tmp_path / "saved"
    saved_dir.mkdir()
    saved_path = saved_dir / "in_memory.usd"

    OpenUSDProviderSession().export_stage(stage, str(saved_path))

    saved = Sdf.Layer.FindOrOpen(str(saved_path))
    assert _file_paths(saved.subLayerPaths) == _file_paths(
        [layer.realPath for layer in sublayers]
    )
    reopened = Usd.Stage.Open(str(saved_path))
    assert reopened.GetPrimAtPath("/World/Strong").IsValid()
    assert reopened.GetPrimAtPath("/World/Weak").IsValid()


def test_save_as_refuses_the_file_of_a_sublayer(tmp_path) -> None:
    session, stage, sublayer = _stage_with_sublayer(tmp_path, _SUBLAYER_PATH)
    before = pathlib.Path(sublayer.realPath).read_text(encoding="utf-8")

    with pytest.raises(RuntimeError, match="is the file of the sublayer"):
        session.export_stage(stage, sublayer.realPath)

    assert pathlib.Path(sublayer.realPath).read_text(encoding="utf-8") == before
