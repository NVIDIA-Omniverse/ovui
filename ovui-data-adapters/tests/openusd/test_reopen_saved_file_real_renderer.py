# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A file that ovrtx read before must load with its saved content.

The ovrtx file loader keeps each USD file that it reads for the life of the
process. Before the fix, the steps "open a scene, change a value, Layers > Save
All, File > Open of the same file" gave ovrtx the path of the clean root layer
again, and ovrtx drew its first read of the file: the old value. The Property
Inspector showed the saved value.

A root file with the content that ovrtx read opens by its path again, as on
its first open: a .usdz package keeps the files inside it, and no copy is
written. A copy for changed content goes to the temp folder, not to the folder
of the user's file.

Each test runs in a process of its own, because the ovrtx cache and the
adapter's record of the files that ovrtx read are process-wide. The tests read
the value back from the real renderer, which is the value that it draws.
"""

from __future__ import annotations

import os
import pathlib
import tempfile

import pytest
from pxr import Sdf, Usd, UsdUtils

pytestmark = [pytest.mark.requires_ovrtx, pytest.mark.own_process]

_SCENE = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 0.01
    upAxis = "Y"
)

def Xform "World"
{
    def Cube "Inheritor"
    {
        double size = 40
        double3 xformOp:translate = (150, 20, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
}
"""

_PART = """#usda 1.0
(
    defaultPrim = "Part"
)

def Xform "Part"
{
    def Cube "Box"
    {
        double size = 30
    }
}
"""

_TOP = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "Prop" (
        prepend references = @./part.usda@
    )
    {
    }
}
"""


_PACKAGE_ROOT = """#usda 1.0
(
    defaultPrim = "World"
    subLayers = [@./layers/extra.usda@]
)

def Xform "World"
{
    def Cube "Own"
    {
        double size = %s
    }

    def Xform "Referenced" (
        prepend references = @./parts/red.usda@
    )
    {
    }

    def Xform "Payloaded" (
        prepend payload = @./parts/blue.usda@
    )
    {
    }
}
"""

_PACKAGE_MEMBER = """#usda 1.0
(
    defaultPrim = "Part"
)

def Xform "Part"
{
    def Cube "Geom"
    {
        double size = %s
    }
}
"""

_PACKAGE_SUBLAYER = """#usda 1.0

over "World"
{
    def Cube "SubCube"
    {
        double size = 12
    }
}
"""


def _write_package(package: pathlib.Path, own_size: float) -> None:
    """Write a .usdz whose root layer uses a sublayer, a reference and a payload inside the package."""

    source = package.parent / f"src-{package.stem}-{own_size}"
    (source / "parts").mkdir(parents=True)
    (source / "layers").mkdir()
    (source / "root.usda").write_text(_PACKAGE_ROOT % own_size)
    (source / "parts" / "red.usda").write_text(_PACKAGE_MEMBER % 21)
    (source / "parts" / "blue.usda").write_text(_PACKAGE_MEMBER % 22)
    (source / "layers" / "extra.usda").write_text(_PACKAGE_SUBLAYER)
    staged = package.parent / f"staged-{package.name}"
    assert UsdUtils.CreateNewUsdzPackage(Sdf.AssetPath(str(source / "root.usda")), str(staged))
    os.replace(staged, package)


def _usd_files(folder: pathlib.Path) -> list[str]:
    """The USD files in ``folder`` (the renderer also writes its log file to the temp folder)."""

    return sorted(name for name in os.listdir(folder) if name.endswith((".usd", ".usda", ".usdc")))


def _package_values(adapter) -> dict[str, float]:
    return {
        prim: _renderer_value(adapter, "size", prim)
        for prim in ("/World/Own", "/World/Referenced/Geom", "/World/Payloaded/Geom", "/World/SubCube")
    }


def _renderer_value(adapter, attribute: str, prim_path: str) -> float:
    """Return the value that the ovrtx renderer of ``adapter`` has for the attribute."""

    import numpy as np

    values = np.from_dlpack(adapter._renderer.read_attribute(attribute, [prim_path])).tolist()
    assert len(values) == 1, values
    return float(values[0])


def _save_size(layer_path: pathlib.Path, prim_path: str, size: float) -> None:
    """Author ``size`` in the file's layer and save it, as Layers > Save All does."""

    layer = Sdf.Layer.FindOrOpen(str(layer_path))
    assert layer is not None, layer_path
    stage = Usd.Stage.Open(layer)
    stage.GetPrimAtPath(prim_path).GetAttribute("size").Set(size)
    assert layer.dirty
    assert layer.Save(), layer_path
    assert not layer.dirty


@pytest.mark.parametrize("load_with", ["stage", "path"])
def test_the_same_file_opened_again_after_save_shows_the_saved_value(tmp_path, load_with):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "states.usda"
    scene.write_text(_SCENE)

    def load(adapter):
        adapter.load_stage(Usd.Stage.Open(str(scene)) if load_with == "stage" else str(scene))

    adapter = OvRtxRendererAdapter()
    try:
        load(adapter)
        assert _renderer_value(adapter, "size", "/World/Inheritor") == 40.0

        _save_size(scene, "/World/Inheritor", 80.0)
        assert "double size = 80" in scene.read_text()

        load(adapter)
        assert _renderer_value(adapter, "size", "/World/Inheritor") == 80.0
    finally:
        adapter.shutdown()


def test_a_file_that_ovrtx_read_as_a_reference_shows_its_saved_value_when_it_is_opened(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "part.usda"
    part.write_text(_PART)
    top = tmp_path / "top.usda"
    top.write_text(_TOP)

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(Usd.Stage.Open(str(top)))
        assert _renderer_value(adapter, "size", "/World/Prop/Box") == 30.0

        _save_size(part, "/Part/Box", 45.0)

        adapter.load_stage(Usd.Stage.Open(str(part)))
        assert _renderer_value(adapter, "size", "/Part/Box") == 45.0
    finally:
        adapter.shutdown()


def test_an_unchanged_package_opened_again_keeps_the_objects_inside_the_package(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    package = tmp_path / "parts.usdz"
    _write_package(package, 10)
    expected = {
        "/World/Own": 10.0,
        "/World/Referenced/Geom": 21.0,
        "/World/Payloaded/Geom": 22.0,
        "/World/SubCube": 12.0,
    }

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(Usd.Stage.Open(str(package)))
        assert _package_values(adapter) == expected

        adapter.load_stage(Usd.Stage.Open(str(package)))
        assert _package_values(adapter) == expected
    finally:
        adapter.shutdown()


@pytest.mark.parametrize("package_folder", ["own folder", "temp folder"])
def test_a_changed_package_opened_again_shows_its_new_root_and_keeps_its_members(
    tmp_path, monkeypatch, package_folder
):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    if package_folder == "temp folder":
        # The package is in the temp folder itself, for example a downloaded file.
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    package = tmp_path / "parts.usdz"
    _write_package(package, 10)
    other = tmp_path / "other.usda"
    other.write_text(_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(Usd.Stage.Open(str(package)))
        assert _renderer_value(adapter, "size", "/World/Own") == 10.0
        # Another file is opened, so that no stage keeps the old package
        # layers; then another program replaces the package.
        adapter.load_stage(Usd.Stage.Open(str(other)))
        _write_package(package, 11)

        adapter.load_stage(Usd.Stage.Open(str(package)))
        assert _package_values(adapter) == {
            "/World/Own": 11.0,
            "/World/Referenced/Geom": 21.0,
            "/World/Payloaded/Geom": 22.0,
            "/World/SubCube": 12.0,
        }
    finally:
        adapter.shutdown()


def test_opening_the_same_file_again_writes_no_copy_beside_it_and_one_copy_for_each_saved_content(
    tmp_path, monkeypatch
):
    """ovrtx keeps each file that it reads. The same content must not give it one more file at each open."""

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scenes = tmp_path / "scenes"
    scenes.mkdir()
    scene = scenes / "states.usda"
    scene.write_text(_SCENE)
    other = scenes / "other.usda"
    other.write_text(_PART)
    temp_folder = tmp_path / "temp"
    temp_folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_folder))

    def open_scene():
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        assert sorted(os.listdir(scenes)) == ["other.usda", "states.usda"]
        return _renderer_value(adapter, "size", "/World/Inheritor")

    adapter = OvRtxRendererAdapter()
    try:
        assert open_scene() == 40.0
        assert open_scene() == 40.0
        assert _usd_files(temp_folder) == []

        _save_size(scene, "/World/Inheritor", 80.0)
        assert open_scene() == 80.0
        copy_of_80 = _usd_files(temp_folder)
        assert len(copy_of_80) == 1
        assert open_scene() == 80.0
        assert _usd_files(temp_folder) == copy_of_80

        _save_size(scene, "/World/Inheritor", 60.0)
        assert open_scene() == 60.0
        copy_of_60 = _usd_files(temp_folder)
        assert len(copy_of_60) == 1 and copy_of_60 != copy_of_80

        adapter.load_stage(Usd.Stage.Open(str(other)))
        assert _usd_files(temp_folder) == []
        assert open_scene() == 60.0
        assert _usd_files(temp_folder) == copy_of_60
    finally:
        adapter.shutdown()
    assert _usd_files(temp_folder) == []


def test_a_root_file_that_cannot_be_read_for_the_comparison_loads_from_the_live_layer_with_a_warning(
    tmp_path, caplog
):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "states.usda"
    scene.write_text(_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        stage = Usd.Stage.Open(str(scene))
        adapter.load_stage(stage)
        # Another program removes the file while the scene is open. The
        # adapter cannot compare it with the read that ovrtx keeps, so it
        # loads the live root layer and says why.
        scene.unlink()
        with caplog.at_level("WARNING", logger="ovui.render_diagnostics"):
            adapter.load_stage(stage)
        assert _renderer_value(adapter, "size", "/World/Inheritor") == 40.0
        assert f"cannot read {scene} to compare it with the renderer's earlier read" in caplog.text
    finally:
        adapter.shutdown()
