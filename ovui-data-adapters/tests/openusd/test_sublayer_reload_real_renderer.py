# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Layers > Reload of a sublayer that another program changed must reach the renderer.

The ovrtx file loader keeps each USD file that it reads for the life of the
process. Before the fix, the reload after Layers > Reload gave ovrtx a copy of
the root layer that names the sublayer file, and ovrtx drew its first read of
that file: the old color. The Property Inspector showed the new color.

Each test runs in a process of its own, because the ovrtx cache and the
adapter's record of the files that ovrtx read are process-wide. The tests read
the value back from the real renderer, which is the value that it draws.

A stage edit that loads the scene again (the Reload of a sublayer, an edit of
the root layer) makes the next frame start the step that builds the scene
again, and the edits of that time reach the renderer when the step is done
(the regression). So after each such edit, the tests run frames as the viewport
does until the scene is built, and then read the renderer.
"""

from __future__ import annotations

import os
import pathlib
import statistics
import tempfile
import time

import pytest
from pxr import Sdf, Usd, UsdGeom, Vt

from ovui_data_adapters.common.adapters import ChangeEvent, ChangeEventType

pytestmark = [pytest.mark.requires_ovrtx, pytest.mark.own_process]

_GREEN = (0.1, 0.8, 0.2)
_MAGENTA = (0.9, 0.1, 0.9)
_BLUE = (0.1, 0.2, 0.9)

_MAIN = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 0.01
    upAxis = "Y"
    subLayers = [@./%s@]
)

def Xform "World"
{
    def Cube "MainCube"
    {
        double size = 100
        color3f[] primvars:displayColor = [(0.2, 0.4, 0.9)]
    }
}
"""

_MID = """#usda 1.0
(
    subLayers = [@./sub_a.usda@]
)

over "World"
{
    def Cube "MidCube"
    {
        double size = 10
    }
}
"""

_SUB_A = """#usda 1.0
(
    defaultPrim = "World"
)

over "World"
{
    def Sphere "SubSphere"
    {
        double radius = 50
        color3f[] primvars:displayColor = [%s]
    }
}
"""

_PACKED = """#usda 1.0

over "World"
{
    def Cube "Packed"
    {
        double size = 5
    }
}
"""

_TIMED_SUB_A = """#usda 1.0
(
    defaultPrim = "World"
)

over "World"
{
    def Sphere "SubSphere"
    {
        double radius.timeSamples = {-1000: -900, 1000: 1100}
        color3f[] primvars:displayColor = [%s]
    }
}
"""

_TIMED = """#usda 1.0

over "World"
{
    def Cube "TimedCube"
    {
        double size.timeSamples = {-1000: -900, 1000: 1100}
    }
}
"""

_BOX = """#usda 1.0
(
    defaultPrim = "Box"
)

def Xform "Box"
{
    def Cube "Body"
    {
        double size = 7
    }
}
"""

_PACKAGE_ROOT = """#usda 1.0
(
    defaultPrim = "World"
    subLayers = [@%s@]
)

def Xform "World"
{
    def Xform "Box" (
        prepend references = @./box.usda@
    )
    {
    }
}
"""


def _renderer_value(adapter, attribute: str, prim_path: str) -> float:
    """Return the value of a scalar attribute that the renderer of ``adapter`` has for the prim."""

    import numpy as np

    values = np.from_dlpack(adapter._renderer.read_attribute(attribute, [prim_path])).tolist()
    assert len(values) == 1, values
    return float(values[0])


def _renderer_color(adapter, prim_path: str) -> tuple[float, ...]:
    """Return the display color that the ovrtx renderer of ``adapter`` has for the prim."""

    import numpy as np

    values = np.from_dlpack(
        adapter._renderer.read_attribute("primvars:displayColor", [prim_path])
    ).tolist()
    assert len(values) == 1, values
    return tuple(round(float(channel), 3) for channel in values[0])


def _render_until_the_scene_is_built(adapter, timeout: float = 300.0) -> None:
    """Run frames as the viewport does until the renderer has built the scene again after a stage edit."""

    import numpy as np

    view = np.identity(4)
    view[3, 2] = -200.0
    projection = np.array(
        [[1.0, 0.0, 0.0, 0.0], [0.0, 2.0, 0.0, 0.0], [0.0, 0.0, -1.0, -1.0], [0.0, 0.0, -2.0, 0.0]]
    )
    deadline = time.monotonic() + timeout
    while adapter.scene_update_pending():
        assert time.monotonic() < deadline, "the renderer did not finish building the scene"
        adapter.render_frame(64, 32, view, projection)
        time.sleep(0.01)


def _write_sub_a(folder: pathlib.Path, color: tuple[float, ...]) -> None:
    (folder / "sub_a.usda").write_text(_SUB_A % (color,))


def _changed(*paths: str) -> ChangeEvent:
    """The event that the stage adapter sends when the stage changes these paths."""

    return ChangeEvent(
        changed_paths=paths,
        resynced_paths=(),
        event_type=ChangeEventType.INFO_CHANGE,
    )


def _reload_sub_a(adapter, folder: pathlib.Path, stage, color: tuple[float, ...]) -> None:
    """Another program writes ``color`` into sub_a.usda; then Layers > Reload reads the file again."""

    _write_sub_a(folder, color)
    assert Sdf.Layer.Find(str(folder / "sub_a.usda")).Reload()
    attribute = stage.GetAttributeAtPath("/World/SubSphere.primvars:displayColor")
    assert tuple(attribute.Get()[0]) == pytest.approx(color)
    adapter.notify_stage_changed(_changed("/", "/World/SubSphere.primvars:displayColor"))
    _render_until_the_scene_is_built(adapter)


def _edit_main_cube(adapter, stage, color: tuple[float, ...]) -> float:
    """A later edit in the root layer that makes the renderer load the stage again.

    Returns the time of the edit and of that load, without the frames that
    build the scene again.
    """

    start = time.perf_counter()
    stage.GetAttributeAtPath("/World/MainCube.primvars:displayColor").Set([color])
    adapter.notify_stage_changed(_changed("/World/MainCube.primvars:displayColor"))
    seconds = time.perf_counter() - start
    _render_until_the_scene_is_built(adapter)
    assert _renderer_color(adapter, "/World/MainCube") == color
    return seconds


def _layer_copies(folder: pathlib.Path) -> list[str]:
    """The names of the layer copies in the folders of layer copies that the adapter made in ``folder``."""

    return sorted(
        copy.name
        for copies in folder.iterdir()
        if copies.name.startswith("ovui_widgets_layer_copies_")
        for copy in copies.iterdir()
    )


def _sub_a_copy(adapter) -> str:
    """The path of the copy of sub_a.usda that the root layer copy of the renderer names."""

    path, root_usda = adapter._root_open_payload
    assert root_usda is None and path is not None
    root_copy = Sdf.Layer.OpenAsAnonymous(path)
    return root_copy.subLayerPaths[0]


def test_reload_of_a_sublayer_changed_by_another_program_shows_its_new_color(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    (tmp_path / "main.usda").write_text(_MAIN % "sub_a.usda")
    _write_sub_a(tmp_path, _GREEN)
    stage = Usd.Stage.Open(str(tmp_path / "main.usda"))

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        assert _renderer_color(adapter, "/World/SubSphere") == _GREEN

        _reload_sub_a(adapter, tmp_path, stage, _MAGENTA)
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA

        # A later edit that loads the stage again keeps the new color: ovrtx
        # still has its first read of the sublayer file.
        _edit_main_cube(adapter, stage, (1.0, 1.0, 0.0))
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
    finally:
        adapter.shutdown()


def test_reload_of_a_changed_sublayer_of_a_sublayer_shows_its_new_color(tmp_path):
    """ovrtx also keeps its read of the unchanged sublayer that names the changed file."""

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    (tmp_path / "main.usda").write_text(_MAIN % "mid.usda")
    (tmp_path / "mid.usda").write_text(_MID)
    _write_sub_a(tmp_path, _GREEN)
    stage = Usd.Stage.Open(str(tmp_path / "main.usda"))

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        assert _renderer_color(adapter, "/World/SubSphere") == _GREEN

        _reload_sub_a(adapter, tmp_path, stage, _MAGENTA)
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
    finally:
        adapter.shutdown()


def test_the_same_content_gives_the_same_copy_and_shutdown_removes_the_copies(
    tmp_path, monkeypatch, caplog
):
    """ovrtx keeps each file that it reads, so a load must not give it a new file for content it has."""

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "scene"
    scene.mkdir()
    temp_folder = tmp_path / "temp"
    temp_folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp_folder))
    (scene / "main.usda").write_text(_MAIN % "sub_a.usda")
    _write_sub_a(scene, _GREEN)
    stage = Usd.Stage.Open(str(scene / "main.usda"))

    adapter = OvRtxRendererAdapter()
    try:
        with caplog.at_level("WARNING", logger="ovui.render_diagnostics"):
            adapter.load_stage(stage)
            assert _layer_copies(temp_folder) == []

            _reload_sub_a(adapter, scene, stage, _MAGENTA)
            assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
            magenta_copy = _sub_a_copy(adapter)
            # The temp folder has the copy of the layer and the copy of the
            # root layer that names it, and nothing else.
            assert _layer_copies(temp_folder) == sorted(
                [os.path.basename(magenta_copy), os.path.basename(adapter._root_open_payload[0])]
            )
            # The root layer that names the copy is not written beside the
            # user's files either.
            assert sorted(os.listdir(scene)) == ["main.usda", "sub_a.usda"]

            for cube_color in ((1.0, 1.0, 0.0), (0.0, 1.0, 1.0)):
                _edit_main_cube(adapter, stage, cube_color)
                assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
                assert _sub_a_copy(adapter) == magenta_copy
                assert _layer_copies(temp_folder) == sorted(
                    [os.path.basename(magenta_copy), os.path.basename(adapter._root_open_payload[0])]
                )

            _reload_sub_a(adapter, scene, stage, _BLUE)
            assert _renderer_color(adapter, "/World/SubSphere") == _BLUE
            blue_copy = _sub_a_copy(adapter)
            assert blue_copy != magenta_copy
            assert os.path.basename(blue_copy) in _layer_copies(temp_folder)

            # The magenta content again: ovrtx gets the magenta copy again.
            _reload_sub_a(adapter, scene, stage, _MAGENTA)
            assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
            assert _sub_a_copy(adapter) == magenta_copy
        reports = [
            record.getMessage()
            for record in caplog.records
            if "changed after the renderer read them" in record.getMessage()
        ]
        assert len(reports) == 1, reports
        assert str(scene / "sub_a.usda") in reports[0]
    finally:
        adapter.shutdown()
    assert not [name for name in os.listdir(temp_folder) if name.startswith("ovui_widgets_layer_copies_")]
    assert sorted(os.listdir(scene)) == ["main.usda", "sub_a.usda"]


def test_later_loads_after_a_large_layer_file_changed_do_not_write_its_copy_again(tmp_path):
    """A changed large layer is copied once for each change, not at each later load.

    Another program touches a large binary sublayer, and Layers > Reload reads
    it again. The renderer then needs a copy of the layer. Later loads (each
    root edit) use that copy again while the layer does not change: they take
    about as long as before the change, much less than a conversion of the
    layer to text.
    """
    import numpy as np

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    big_path = tmp_path / "big.usdc"
    big_stage = Usd.Stage.CreateNew(str(big_path))
    big_stage.OverridePrim("/World")
    mesh = UsdGeom.Mesh.Define(big_stage, "/World/BigMesh")
    count = 1_400_000  # about 32 MB of points and normals
    rng = np.random.default_rng(732)
    mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(rng.random((count, 3), dtype=np.float32) * 100.0))
    mesh.CreateNormalsAttr(Vt.Vec3fArray.FromNumpy(rng.random((count, 3), dtype=np.float32)))
    mesh.CreateFaceVertexCountsAttr(Vt.IntArray([3] * (count // 3)))
    mesh.CreateFaceVertexIndicesAttr(
        Vt.IntArray.FromNumpy(np.arange(count // 3 * 3, dtype=np.int32))
    )
    big_stage.GetRootLayer().Save()
    del big_stage, mesh
    (tmp_path / "main.usda").write_text(_MAIN % "big.usdc")
    stage = Usd.Stage.Open(str(tmp_path / "main.usda"))
    big_layer = Sdf.Layer.Find(str(big_path))
    colors = [(1.0, 1.0, 0.0), (0.0, 1.0, 1.0), (1.0, 0.0, 1.0), (0.5, 0.5, 0.0)]

    def timed_root_edits() -> list[float]:
        times = []
        for color in colors:
            # Each timed edit loads the stage itself: no earlier edit waits
            # for a frame.
            assert not adapter.scene_update_pending()
            times.append(_edit_main_cube(adapter, stage, color))
        return times

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        before = timed_root_edits()

        os.utime(big_path, None)
        assert big_layer.Reload()
        adapter.notify_stage_changed(_changed("/", "/World/BigMesh.points"))
        _render_until_the_scene_is_built(adapter)
        after = timed_root_edits()
    finally:
        adapter.shutdown()

    start = time.perf_counter()
    big_layer.ExportToString()
    text_conversion = time.perf_counter() - start
    assert statistics.median(after) < statistics.median(before) + text_conversion / 2, (
        before,
        after,
        text_conversion,
    )


def test_a_layer_file_that_cannot_be_read_for_its_state_is_reported_once_and_drawn_from_memory(
    tmp_path, capsys
):
    """A moved layer file keeps the content that the stage has in the renderer, with one report.

    Another program changes sub_a.usda, and Layers > Reload reads it. Then the
    file is moved away (as a file manager or a Git checkout does), while the
    stage keeps its layer. A later load cannot read the state of the file.
    Before the fix, that file left the check with no report, and ovrtx drew
    its first read of the file: the old color. A layer in a .usdz package is
    not a file of its own and gives no report.
    """
    from pxr import UsdUtils

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    (tmp_path / "packed.usda").write_text(_PACKED)
    assert UsdUtils.CreateNewUsdzPackage(
        Sdf.AssetPath(str(tmp_path / "packed.usda")), str(tmp_path / "package.usdz")
    )
    (tmp_path / "main.usda").write_text(_MAIN % "sub_a.usda@, @./package.usdz[packed.usda]")
    _write_sub_a(tmp_path, _GREEN)
    sub_a = tmp_path / "sub_a.usda"
    stage = Usd.Stage.Open(str(tmp_path / "main.usda"))
    assert stage.GetPrimAtPath("/World/Packed")

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        _reload_sub_a(adapter, tmp_path, stage, _MAGENTA)
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA

        (tmp_path / "moved").mkdir()
        sub_a.rename(tmp_path / "moved" / "sub_a.usda")
        for cube_color in ((1.0, 1.0, 0.0), (0.0, 1.0, 1.0)):
            _edit_main_cube(adapter, stage, cube_color)
            assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
    finally:
        adapter.shutdown()
    reports = [
        line
        for line in capsys.readouterr().err.splitlines()
        if "cannot read the state of the layer file" in line
    ]
    assert len(reports) == 1, reports
    assert str(sub_a) in reports[0]
    assert "FileNotFoundError" in reports[0]


def test_the_same_file_opened_again_shows_the_layer_content_that_its_stage_has(tmp_path):
    """File > Open of the same file, and a load by path, after another program changed a sublayer.

    The clean root file has the content that ovrtx read. A new stage of the
    same file uses the layers that USD keeps in memory: the reloaded magenta
    sublayer. Without a copy of the root layer that names the layer copy,
    ovrtx would draw its first read of both files: the old color. After the
    old stage is closed, another program changes the file again, and a new
    open reads that content.
    """
    import gc

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    main_path = str(tmp_path / "main.usda")
    sub_a_path = str(tmp_path / "sub_a.usda")
    (tmp_path / "main.usda").write_text(_MAIN % "sub_a.usda")
    _write_sub_a(tmp_path, _GREEN)
    stage = Usd.Stage.Open(main_path)

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        _reload_sub_a(adapter, tmp_path, stage, _MAGENTA)
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA

        adapter.load_stage(Usd.Stage.Open(main_path))
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
        adapter.load_stage(main_path)
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA

        adapter.load_stage(Usd.Stage.CreateInMemory())
        del stage
        gc.collect()
        assert Sdf.Layer.Find(sub_a_path) is None
        _write_sub_a(tmp_path, _BLUE)
        adapter.load_stage(Usd.Stage.Open(main_path))
        assert _renderer_color(adapter, "/World/SubSphere") == _BLUE
    finally:
        adapter.shutdown()


def test_copied_layers_keep_the_time_offset_and_scale_of_their_sublayers(tmp_path):
    """The renderer composes copied sublayers with the time offset and scale of their parents.

    The radius of the sphere and the size of the cube change with time.
    Before the change, ovrtx composes the original files with the authored
    offsets and scales. After another program changes sub_a.usda (named by
    the root layer) and timed.usda (named by mid.usda), and Layers > Reload
    reads them, ovrtx composes copies. It must have the same radius and size.
    """
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    (tmp_path / "main.usda").write_text(_MAIN % "sub_a.usda@ (offset = 10; scale = 2), @./mid.usda")
    (tmp_path / "mid.usda").write_text(
        _MID.replace("@./sub_a.usda@", "@./timed.usda@ (offset = 30; scale = 0.5)")
    )
    (tmp_path / "timed.usda").write_text(_TIMED)
    (tmp_path / "sub_a.usda").write_text(_TIMED_SUB_A % (_GREEN,))
    stage = Usd.Stage.Open(str(tmp_path / "main.usda"))

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        radius = _renderer_value(adapter, "radius", "/World/SubSphere")
        size = _renderer_value(adapter, "size", "/World/TimedCube")

        (tmp_path / "sub_a.usda").write_text(_TIMED_SUB_A % (_MAGENTA,))
        (tmp_path / "timed.usda").write_text(_TIMED + "\n")
        for name in ("sub_a.usda", "timed.usda"):
            assert Sdf.Layer.Find(str(tmp_path / name)).Reload()
        adapter.notify_stage_changed(_changed("/", "/World/SubSphere.primvars:displayColor"))
        _render_until_the_scene_is_built(adapter)
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA

        assert _renderer_value(adapter, "radius", "/World/SubSphere") == pytest.approx(radius)
        assert _renderer_value(adapter, "size", "/World/TimedCube") == pytest.approx(size)
    finally:
        adapter.shutdown()


def test_a_package_scene_keeps_the_files_in_its_package_when_an_outside_sublayer_changed(tmp_path):
    """A .usdz scene whose outside sublayer changed keeps the objects of the files in the package.

    The root layer of the package loads through a copy that names the copy of
    the changed sublayer. A relative path in that copy must still name the
    file in the package.
    """
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    _write_sub_a(tmp_path, _GREEN)
    members = tmp_path / "members"
    members.mkdir()
    (members / "box.usda").write_text(_BOX)
    (members / "root.usda").write_text(_PACKAGE_ROOT % (tmp_path / "sub_a.usda").as_posix())
    scene = tmp_path / "scene.usdz"
    writer = Sdf.ZipFileWriter.CreateNew(str(scene))
    writer.AddFile(str(members / "root.usda"), "root.usda")
    writer.AddFile(str(members / "box.usda"), "box.usda")
    assert writer.Save()
    stage = Usd.Stage.Open(str(scene))

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        assert _renderer_color(adapter, "/World/SubSphere") == _GREEN
        assert _renderer_value(adapter, "size", "/World/Box/Body") == 7.0

        _reload_sub_a(adapter, tmp_path, stage, _MAGENTA)
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
        assert _renderer_value(adapter, "size", "/World/Box/Body") == 7.0
    finally:
        adapter.shutdown()


def test_a_reload_that_leaves_a_changed_layer_the_same_writes_no_new_copy(tmp_path, monkeypatch):
    """Another program only touches a changed layer file, and Layers > Reload reads it again.

    The layer then has the content of its copy, so the adapter writes no new
    copy: a copy of a large layer written again at each Reload costs time and,
    with the renderer, memory. A new content in the file, and an edit of the
    layer in memory, still give a new copy.
    """
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    writes = []
    write_layer_copy = OvRtxRendererAdapter._write_layer_copy

    def counted_write_layer_copy(self, layer, copies):
        path = write_layer_copy(self, layer, copies)
        writes.append(path)
        return path

    monkeypatch.setattr(OvRtxRendererAdapter, "_write_layer_copy", counted_write_layer_copy)
    (tmp_path / "main.usda").write_text(_MAIN % "sub_a.usda")
    _write_sub_a(tmp_path, _GREEN)
    sub_a = tmp_path / "sub_a.usda"
    stage = Usd.Stage.Open(str(tmp_path / "main.usda"))
    layer = Sdf.Layer.Find(str(sub_a))

    def touch_and_reload(seconds: int) -> None:
        stamp = sub_a.stat().st_mtime_ns + seconds * 1_000_000_000
        os.utime(sub_a, ns=(stamp, stamp))
        assert layer.Reload()
        adapter.notify_stage_changed(_changed("/", "/World/SubSphere.primvars:displayColor"))
        _render_until_the_scene_is_built(adapter)
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        _reload_sub_a(adapter, tmp_path, stage, _MAGENTA)
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA

        touch_and_reload(1)
        written = len(writes)
        for seconds in (2, 3):
            touch_and_reload(seconds)
        assert len(writes) == written
        assert set(writes) == {writes[0]}

        _reload_sub_a(adapter, tmp_path, stage, _BLUE)
        assert _renderer_color(adapter, "/World/SubSphere") == _BLUE
        assert len(writes) == written + 1

        with Usd.EditContext(stage, layer):
            stage.GetAttributeAtPath("/World/SubSphere.primvars:displayColor").Set([_GREEN])
        adapter.notify_stage_changed(_changed("/World/SubSphere.primvars:displayColor"))
        _render_until_the_scene_is_built(adapter)
        _edit_main_cube(adapter, stage, (1.0, 1.0, 0.0))
        assert _renderer_color(adapter, "/World/SubSphere") == _GREEN
        assert len(writes) == written + 2
    finally:
        adapter.shutdown()


def test_the_root_layer_copy_is_written_again_only_after_a_change(tmp_path, monkeypatch):
    """A load with nothing new changed uses the root layer copy again; a real change writes a new one.

    After a Reload of a changed sublayer, each load gives ovrtx a copy of the
    root layer that names the layer copy. Converting a large root layer to
    text at each later load (File > Open of the same file) is slow, so the
    copy is used again while the root layer has no change and names the same
    layer copies. An edit of the root layer, a new sublayer content and a
    removed copy file each give a new copy, and the renderer draws them.
    """
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    writes = []
    copy_of_layer = OvRtxRendererAdapter._ovrtx_copy_of_layer

    def counted_copy_of_layer(self, layer, layer_copies, **options):
        path = copy_of_layer(self, layer, layer_copies, **options)
        writes.append(path)
        return path

    monkeypatch.setattr(OvRtxRendererAdapter, "_ovrtx_copy_of_layer", counted_copy_of_layer)
    main_path = str(tmp_path / "main.usda")
    (tmp_path / "main.usda").write_text(_MAIN % "sub_a.usda")
    _write_sub_a(tmp_path, _GREEN)
    stage = Usd.Stage.Open(main_path)

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        _reload_sub_a(adapter, tmp_path, stage, _MAGENTA)
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
        assert len(writes) == 1

        # File > Open of the same file, two times, with nothing changed.
        for _ in range(2):
            adapter.load_stage(Usd.Stage.Open(main_path))
            assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
            assert adapter._root_open_payload[0] == writes[0]
        assert len(writes) == 1

        # An edit of the root layer in memory.
        _edit_main_cube(adapter, stage, (1.0, 1.0, 0.0))
        assert len(writes) == 2

        # A new content of the sublayer: the root copy names another layer copy.
        _reload_sub_a(adapter, tmp_path, stage, _BLUE)
        assert _renderer_color(adapter, "/World/SubSphere") == _BLUE
        assert len(writes) == 3

        # The root copy file is removed.
        os.unlink(adapter._root_open_payload[0])
        adapter.load_stage(Usd.Stage.Open(main_path))
        assert len(writes) == 4
        assert os.path.isfile(adapter._root_open_payload[0])
        assert _renderer_color(adapter, "/World/SubSphere") == _BLUE
        assert _renderer_color(adapter, "/World/MainCube") == (1.0, 1.0, 0.0)
    finally:
        adapter.shutdown()


_RENDER_PRODUCT_MAIN = """#usda 1.0
(
    defaultPrim = "World"
    subLayers = [@./sub_a.usda@]
)

def Xform "World"
{
}

def Camera "Cam"
{
}

def RenderProduct "Product"
{
    rel camera = </Cam>
    uniform int2 resolution = (64, 64)
}
"""

# A global render setting of the renderer (RenderSettings scope): the adapter
# writes it into the root layer copy, on the owner prim that ovrtx reads.
_GLOBAL_SETTING = "omni:rtx:scenePartitioning:showAllPartitionsByDefault"


def _renderer_global_setting(adapter):
    """The value of the global render setting that the renderer has, or None when it has none."""

    import numpy as np

    from ovui_data_adapters.openusd import renderer_adapter as module

    try:
        values = np.from_dlpack(
            adapter._renderer.read_attribute(
                _GLOBAL_SETTING, [module._RENDER_SETTINGS_OWNER_PATH]
            )
        ).tolist()
    except RuntimeError:
        return None
    assert len(values) == 1, values
    return bool(values[0])


def test_a_root_layer_copy_with_a_render_setting_is_not_used_again_after_a_reset_or_for_another_document(tmp_path):
    """A reset global render setting, or one of another document, does not come back from an earlier root copy.

    The adapter writes a global render setting (RenderSettings scope, for
    example Rendering color space of the RTX Tools window) into the copy of the
    root layer, not into the root layer, so the change notices of the root
    layer do not see it. After the reset of the last such setting, and for
    another document of the same file, the renderer must not get the earlier
    root copy that still has the setting.
    """
    from ovui_data_adapters.common.render_settings import RenderSettingValueType
    from ovui_data_adapters.openusd import OvRtxRendererAdapter
    from ovui_data_adapters.openusd import renderer_adapter as module

    module.configure_render_settings_schema(
        provider_id="test.global_settings",
        provider_label="Global settings",
        public_namespaces=("omni:rtx:",),
        metadata_key="renderSettings",
        group_fallback="omni_rtx",
        group_label_fallback="Omni RTX",
        builtin_specs=(
            {
                "attr_name": _GLOBAL_SETTING,
                "usd_type": "bool",
                "value_type": RenderSettingValueType.BOOL,
                "requirement": "warmup",
                "default": False,
                "label": "Show all partitions by default",
                "owner_scope": "RenderSettings",
            },
        ),
    )
    main_path = str(tmp_path / "main.usda")
    (tmp_path / "main.usda").write_text(_RENDER_PRODUCT_MAIN)
    _write_sub_a(tmp_path, _GREEN)
    stage = Usd.Stage.Open(main_path)
    setting = f"/Product:{_GLOBAL_SETTING}"

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        adapter._render_product_path = "/Product"
        # From here on, the root layer goes to the renderer as a copy.
        _reload_sub_a(adapter, tmp_path, stage, _MAGENTA)
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
        assert _renderer_global_setting(adapter) is None

        assert adapter.apply_render_setting(setting, True).accepted
        assert _renderer_global_setting(adapter) is True

        # Reset of the last such setting: the renderer does not keep it.
        assert adapter.reset_render_setting(setting).accepted
        assert not adapter._has_render_settings_owner_opinions()
        assert _renderer_global_setting(adapter) is None
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA

        # Another document of the same file does not get the setting of the first one.
        assert adapter.apply_render_setting(setting, True).accepted
        assert _renderer_global_setting(adapter) is True
        adapter.load_stage(Usd.Stage.Open(main_path))
        assert _renderer_global_setting(adapter) is None
        assert _renderer_color(adapter, "/World/SubSphere") == _MAGENTA
    finally:
        adapter.shutdown()
