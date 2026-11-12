# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A scene opened again draws the saved content of the files that it uses.

The ovrtx file loader keeps the first read of each USD file for the life of the
process. Before the fix, the steps "open a scene that references a file, open
that file, change a value, File > Save, open the scene again" loaded the scene
by its path, and ovrtx composed its first read of the referenced file: the old
value. The Property Inspector showed the saved value.

Each test runs in a process of its own, because the ovrtx keep of each file and
the adapter's record of the files are process-wide. The tests read the value
back from the real renderer, which is the value that it draws.
"""

from __future__ import annotations

import pathlib

import pytest

pytestmark = [pytest.mark.requires_ovrtx, pytest.mark.own_process]

_PART = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Cone "Spike"
    {
        double height = 24
        double radius = 8
        uniform token axis = "Y"
    }
}
"""

_SCENE_WITH_ARC = {
    "reference": """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "RefObj" (
        prepend references = @./ref_part.usda@
    )
    {
    }
    def Xform "Box" (
        prepend references = @./box.usda@
    )
    {
    }
}
""",
    "payload": """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "RefObj" (
        prepend payload = @./ref_part.usda@
    )
    {
    }
    def Xform "Box" (
        prepend references = @./box.usda@
    )
    {
    }
}
""",
    "sublayer": """#usda 1.0
(
    defaultPrim = "World"
    subLayers = [
        @./ref_part.usda@
    ]
)

over "World"
{
    def Xform "Box" (
        prepend references = @./box.usda@
    )
    {
    }
}
""",
}

# A file of the scene that does not change. Its relative path must still
# resolve when the root layer goes to ovrtx as text.
_BOX = """#usda 1.0
(
    defaultPrim = "Box"
)

def Xform "Box"
{
    def Cube "Cube"
    {
        double size = 10
    }
}
"""

_SPIKE_IN_SCENE = {
    "reference": "/World/RefObj/Spike",
    "payload": "/World/RefObj/Spike",
    "sublayer": "/World/Spike",
}

# A file that references the changed file. A scene that references this file
# goes to ovrtx as a copy of its root layer that names a copy of this file,
# and that copy names the changed file anew.
_MIDDLE = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "Inner" (
        prepend references = @./ref_part.usda@
    )
    {
    }
}
"""

_NESTED_SCENE = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "Outer" (
        prepend references = @./middle.usda@
    )
    {
    }
}
"""


# The same changed file, referenced by the root layer and by middle.usda.
_BOTH_SCENE = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "RefObj" (
        prepend references = @./ref_part.usda@
    )
    {
    }
    def Xform "Outer" (
        prepend references = @./middle.usda@
    )
    {
    }
}
"""


def _renderer_value(adapter, attribute: str, prim_path: str) -> float:
    """Return the value that the ovrtx renderer of ``adapter`` has for the attribute."""

    import numpy as np

    values = np.from_dlpack(adapter._renderer.read_attribute(attribute, [prim_path])).tolist()
    assert len(values) == 1, values
    return float(values[0])


def _renderer_height(adapter, prim_path: str) -> float:
    """Return the height that the ovrtx renderer of ``adapter`` has for the cone."""

    return _renderer_value(adapter, "height", prim_path)


def _renderer_root(adapter) -> pathlib.Path:
    """Return the root file that the renderer of ``adapter`` opened last."""

    path, root_usda = adapter._root_open_payload
    assert root_usda is None and path is not None
    return pathlib.Path(path)


def _open(adapter, path: pathlib.Path):
    """Open a file as File > Open does: a new stage, loaded into the renderer."""

    from pxr import Usd

    stage = Usd.Stage.Open(str(path))
    adapter.load_stage(stage)
    return stage


def _edit_and_save_height(stage, prim_path: str, height: float) -> None:
    """Author the height in the root layer of the open stage and save it with File > Save.

    File > Save writes a copy of the root layer to the file. The layer in
    memory stays marked as changed, as in the app.
    """

    from ovui_data_adapters.openusd.provider import OpenUSDProviderSession

    stage.GetPrimAtPath(prim_path).GetAttribute("height").Set(height)
    root_layer = stage.GetRootLayer()
    OpenUSDProviderSession().export_stage(stage, root_layer.realPath)
    assert root_layer.dirty


@pytest.mark.parametrize("arc", ["reference", "payload", "sublayer"])
@pytest.mark.parametrize("first, saved", [(24.0, 48.0), (48.0, 24.0)])
def test_the_scene_opened_again_draws_the_saved_value_of_the_file_that_it_uses(tmp_path, arc, first, saved):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART.replace("double height = 24", f"double height = {first:g}"))
    (tmp_path / "box.usda").write_text(_BOX)
    scene = tmp_path / "consist.usda"
    scene.write_text(_SCENE_WITH_ARC[arc])
    spike = _SPIKE_IN_SCENE[arc]

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        assert _renderer_height(adapter, spike) == first

        part_stage = _open(adapter, part)
        assert _renderer_height(adapter, "/World/Spike") == first
        _edit_and_save_height(part_stage, "/World/Spike", saved)
        assert f"double height = {saved:g}" in part.read_text()

        _open(adapter, scene)
        assert _renderer_height(adapter, spike) == saved
        # Only the changed file goes as a copy: the root layer goes as a copy
        # that names a copy of the changed layer, beside it, and still names
        # the unchanged file of the scene, which is drawn.
        root_copy = _renderer_root(adapter)
        assert root_copy.parent != tmp_path
        root_text = root_copy.read_text()
        assert "ref_part.usda" not in root_text
        assert f"{root_copy.parent.as_posix()}/" in root_text
        assert f"{tmp_path.as_posix()}/box.usda" in root_text
        assert _renderer_value(adapter, "size", "/World/Box/Cube") == 10.0

        # A further open of the same scene, with no new change, keeps the saved
        # value and names the same copy, so the renderer reads no file again.
        _open(adapter, scene)
        assert _renderer_height(adapter, spike) == saved
        assert _renderer_root(adapter) == root_copy
    finally:
        adapter.shutdown()


def test_a_file_saved_twice_is_drawn_with_each_saved_value(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "box.usda").write_text(_BOX)
    scene = tmp_path / "consist.usda"
    scene.write_text(_SCENE_WITH_ARC["reference"])

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        for saved in (48.0, 36.0):
            part_stage = _open(adapter, part)
            _edit_and_save_height(part_stage, "/World/Spike", saved)
            _open(adapter, scene)
            assert _renderer_height(adapter, "/World/RefObj/Spike") == saved
    finally:
        adapter.shutdown()


def test_a_changed_file_that_another_file_references_is_drawn_with_its_saved_value(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "middle.usda").write_text(_MIDDLE)
    scene = tmp_path / "nested.usda"
    scene.write_text(_NESTED_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        assert _renderer_height(adapter, "/World/Outer/Inner/Spike") == 24.0

        part_stage = _open(adapter, part)
        _edit_and_save_height(part_stage, "/World/Spike", 48.0)

        _open(adapter, scene)
        assert _renderer_height(adapter, "/World/Outer/Inner/Spike") == 48.0
        # The arc to the changed file is in middle.usda: the root layer names
        # a copy of middle.usda that names the changed file anew.
        root_copy = _renderer_root(adapter)
        assert "middle.usda" not in root_copy.read_text()
        assert adapter._owned_tmp_path is None
    finally:
        adapter.shutdown()


def test_a_changed_file_that_the_root_layer_and_another_file_reference_is_drawn_with_its_saved_value(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "middle.usda").write_text(_MIDDLE)
    scene = tmp_path / "both.usda"
    scene.write_text(_BOTH_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        part_stage = _open(adapter, part)
        _edit_and_save_height(part_stage, "/World/Spike", 48.0)

        _open(adapter, scene)
        assert _renderer_height(adapter, "/World/RefObj/Spike") == 48.0
        assert _renderer_height(adapter, "/World/Outer/Inner/Spike") == 48.0
    finally:
        adapter.shutdown()


def test_a_package_scene_keeps_its_own_files_and_draws_the_saved_value_of_an_outside_file(tmp_path):
    from pxr import Sdf

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    members = tmp_path / "members"
    members.mkdir()
    (members / "box.usda").write_text(_BOX)
    (members / "root.usda").write_text(
        _SCENE_WITH_ARC["reference"].replace("@./ref_part.usda@", f"@{part.as_posix()}@")
    )
    scene = tmp_path / "scene.usdz"
    writer = Sdf.ZipFileWriter.CreateNew(str(scene))
    writer.AddFile(str(members / "root.usda"), "root.usda")
    writer.AddFile(str(members / "box.usda"), "box.usda")
    assert writer.Save()

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        assert _renderer_value(adapter, "size", "/World/Box/Cube") == 10.0

        part_stage = _open(adapter, part)
        _edit_and_save_height(part_stage, "/World/Spike", 48.0)

        _open(adapter, scene)
        assert _renderer_height(adapter, "/World/RefObj/Spike") == 48.0
        # The reference to a file in the package still resolves from the root copy.
        assert _renderer_value(adapter, "size", "/World/Box/Cube") == 10.0
    finally:
        adapter.shutdown()


def test_a_file_that_another_program_changed_is_drawn_as_the_other_panels_show_it(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "box.usda").write_text(_BOX)
    scene = tmp_path / "consist.usda"
    scene.write_text(_SCENE_WITH_ARC["reference"])

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        assert _renderer_height(adapter, "/World/RefObj/Spike") == 24.0

        # Another program writes the file. The layer of the open scene keeps
        # its content, so the stage that is opened next composes Height 24.
        part.write_text(_PART.replace("double height = 24", "double height = 48"))
        stage = _open(adapter, scene)
        assert stage.GetPrimAtPath("/World/RefObj/Spike").GetAttribute("height").Get() == 24.0
        assert _renderer_height(adapter, "/World/RefObj/Spike") == 24.0
    finally:
        adapter.shutdown()


def test_a_new_read_of_a_file_that_another_program_changed_is_drawn_as_the_other_panels_show_it(tmp_path):
    import gc

    from pxr import Sdf

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "box.usda").write_text(_BOX)
    scene = tmp_path / "consist.usda"
    scene.write_text(_SCENE_WITH_ARC["reference"])

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        part.write_text(_PART.replace("double height = 24", "double height = 48"))
        stage = _open(adapter, scene)
        assert stage.GetPrimAtPath("/World/RefObj/Spike").GetAttribute("height").Get() == 24.0
        assert _renderer_height(adapter, "/World/RefObj/Spike") == 24.0

        # Another file is opened, and OpenUSD releases the old layer of the
        # changed file. The next open of the scene reads the file anew.
        stage = None
        _open(adapter, tmp_path / "box.usda")
        gc.collect()
        assert Sdf.Layer.Find(str(part)) is None
        stage = _open(adapter, scene)
        assert stage.GetPrimAtPath("/World/RefObj/Spike").GetAttribute("height").Get() == 48.0
        assert _renderer_height(adapter, "/World/RefObj/Spike") == 48.0
    finally:
        adapter.shutdown()


def test_a_sublayer_keeps_its_time_offset_when_the_root_layer_names_its_saved_file(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    scene = tmp_path / "timed.usda"
    scene.write_text(
        _SCENE_WITH_ARC["sublayer"].replace("@./ref_part.usda@", "@./ref_part.usda@ (offset = 10; scale = 2)")
    )

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        part_stage = _open(adapter, part)
        _edit_and_save_height(part_stage, "/World/Spike", 48.0)

        stage = _open(adapter, scene)
        assert _renderer_height(adapter, "/World/Spike") == 48.0
        # The root layer that the renderer composes keeps the authored timing
        # of the sublayer, as the stage of the other panels does.
        from pxr import Sdf

        renderer_root = Sdf.Layer.OpenAsAnonymous(str(_renderer_root(adapter)))
        assert list(renderer_root.subLayerOffsets) == list(stage.GetRootLayer().subLayerOffsets)
        assert renderer_root.subLayerOffsets[0] == Sdf.LayerOffset(10, 2)
    finally:
        adapter.shutdown()


def test_a_scene_whose_files_did_not_change_loads_by_its_path(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "box.usda").write_text(_BOX)
    scene = tmp_path / "consist.usda"
    scene.write_text(_SCENE_WITH_ARC["reference"])

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        _open(adapter, part)
        _open(adapter, scene)
        # No file changed: the renderer opens the scene file itself, as before
        # this fix, and reads no file again.
        assert adapter._root_open_payload == (str(scene), None)
        assert _renderer_height(adapter, "/World/RefObj/Spike") == 24.0
    finally:
        adapter.shutdown()


def test_a_scene_that_the_renderer_read_only_as_a_copy_opens_by_its_path_after_a_save(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "box.usda").write_text(_BOX)
    scene = tmp_path / "consist.usda"
    scene.write_text(_SCENE_WITH_ARC["reference"])

    adapter = OvRtxRendererAdapter()
    try:
        # The referenced file is opened and saved first, so the first open of
        # the scene gives the renderer a copy of its root layer, not its file.
        part_stage = _open(adapter, part)
        _edit_and_save_height(part_stage, "/World/Spike", 48.0)
        stage = _open(adapter, scene)
        assert _renderer_root(adapter).parent != tmp_path

        # An unsaved edit of the referenced file, and a saved edit of the
        # scene that also removes its reference to that file, so that no
        # file of the scene changed after the renderer read it.
        part_stage.GetPrimAtPath("/World/Spike").GetAttribute("height").Set(24.0)
        stage.GetPrimAtPath("/World/Box/Cube").GetAttribute("size").Set(20.0)
        assert stage.RemovePrim("/World/RefObj")
        assert stage.GetRootLayer().Save()
        stage = _open(adapter, scene)
        # The renderer has not read the scene file, so it opens it by its path.
        assert adapter._root_open_payload == (str(scene), None)
        assert _renderer_value(adapter, "size", "/World/Box/Cube") == 20.0
    finally:
        adapter.shutdown()


def test_the_layer_copies_are_removed_at_shutdown(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "box.usda").write_text(_BOX)
    scene = tmp_path / "consist.usda"
    scene.write_text(_SCENE_WITH_ARC["reference"])

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        part_stage = _open(adapter, part)
        _edit_and_save_height(part_stage, "/World/Spike", 48.0)
        _open(adapter, scene)
        root_copy = _renderer_root(adapter)
        assert root_copy.exists()
    finally:
        adapter.shutdown()
    assert not root_copy.parent.exists()


def test_an_in_memory_scene_that_references_a_saved_file_draws_its_saved_value(tmp_path, capsys):
    from pxr import Usd

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)

    def in_memory_scene():
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World/RefObj", "Xform").GetReferences().AddReference(part.as_posix())
        return stage

    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(in_memory_scene())
        assert _renderer_height(adapter, "/World/RefObj/Spike") == 24.0
        part_stage = _open(adapter, part)
        _edit_and_save_height(part_stage, "/World/Spike", 48.0)

        capsys.readouterr()
        stage = in_memory_scene()
        adapter.load_stage(stage)
        assert _renderer_height(adapter, "/World/RefObj/Spike") == 48.0
        # The root layer has no file: the renderer loads a composed snapshot.
        assert adapter._owned_tmp_path is not None
        assert _renderer_root(adapter) == pathlib.Path(adapter._owned_tmp_path)

        # Each reload of the scene (for example after an edit) uses the same
        # fallback; it is reported once.
        stage.DefinePrim("/World/Marker", "Xform")
        adapter.load_stage(stage)
        assert _renderer_height(adapter, "/World/RefObj/Spike") == 48.0
        reports = [line for line in capsys.readouterr().err.splitlines() if "composed snapshot" in line]
        assert len(reports) == 1, reports
    finally:
        adapter.shutdown()


def test_a_changed_file_that_names_another_changed_file_is_drawn_with_both_saved_values(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    inner = tmp_path / "ref_part.usda"
    inner.write_text(_PART)
    middle = tmp_path / "middle.usda"
    middle.write_text(_MIDDLE.replace('def Xform "Inner" (', 'def Cone "Tip"\n    {\n        double height = 5\n    }\n\n    def Xform "Inner" ('))
    scene = tmp_path / "nested.usda"
    scene.write_text(_NESTED_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        assert _renderer_height(adapter, "/World/Outer/Inner/Spike") == 24.0
        assert _renderer_height(adapter, "/World/Outer/Tip") == 5.0

        inner_stage = _open(adapter, inner)
        _edit_and_save_height(inner_stage, "/World/Spike", 48.0)
        middle_stage = _open(adapter, middle)
        _edit_and_save_height(middle_stage, "/World/Tip", 7.0)

        _open(adapter, scene)
        assert _renderer_height(adapter, "/World/Outer/Inner/Spike") == 48.0
        assert _renderer_height(adapter, "/World/Outer/Tip") == 7.0
    finally:
        adapter.shutdown()


def test_an_unsaved_edit_of_the_scene_is_drawn_after_its_root_layer_was_copied(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "box.usda").write_text(_BOX)
    scene = tmp_path / "consist.usda"
    scene.write_text(_SCENE_WITH_ARC["reference"])

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        part_stage = _open(adapter, part)
        _edit_and_save_height(part_stage, "/World/Spike", 48.0)
        stage = _open(adapter, scene)
        first_copy = _renderer_root(adapter)

        # An unsaved edit of the scene: the same root file, other content.
        stage.GetPrimAtPath("/World/Box/Cube").GetAttribute("size").Set(20.0)
        adapter.load_stage(stage)
        edited_copy = _renderer_root(adapter)
        assert edited_copy != first_copy
        assert _renderer_value(adapter, "size", "/World/Box/Cube") == 20.0
        assert _renderer_height(adapter, "/World/RefObj/Spike") == 48.0

        # The same content again names the same copy, so the renderer reads
        # no file again for it.
        adapter.load_stage(stage)
        assert _renderer_root(adapter) == edited_copy
        assert _renderer_value(adapter, "size", "/World/Box/Cube") == 20.0
    finally:
        adapter.shutdown()


def test_an_unsaved_edit_after_the_save_is_drawn_as_the_other_panels_show_it(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "box.usda").write_text(_BOX)
    scene = tmp_path / "consist.usda"
    scene.write_text(_SCENE_WITH_ARC["reference"])
    spike = "/World/RefObj/Spike"

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        part_stage = _open(adapter, part)
        _edit_and_save_height(part_stage, "/World/Spike", 48.0)
        _open(adapter, scene)
        assert _renderer_height(adapter, spike) == 48.0

        # The referenced file again: Height back to 24, not saved. The file keeps 48.
        part_stage = _open(adapter, part)
        part_stage.GetPrimAtPath("/World/Spike").GetAttribute("height").Set(24.0)
        assert "double height = 48" in part.read_text()
        stage = _open(adapter, scene)
        assert stage.GetPrimAtPath(spike).GetAttribute("height").Get() == 24.0
        assert _renderer_height(adapter, spike) == 24.0
        # The file does not have the content of the layer in memory: the
        # renderer gets a copy of the layer in memory, not the file.
        assert _renderer_root(adapter).parent != tmp_path

        # An edit back to the saved value is drawn too.
        part_stage = _open(adapter, part)
        part_stage.GetPrimAtPath("/World/Spike").GetAttribute("height").Set(48.0)
        stage = _open(adapter, scene)
        assert stage.GetPrimAtPath(spike).GetAttribute("height").Get() == 48.0
        assert _renderer_height(adapter, spike) == 48.0
    finally:
        adapter.shutdown()


def test_the_copies_that_the_loaded_scene_does_not_name_are_removed(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "box.usda").write_text(_BOX)
    scene = tmp_path / "consist.usda"
    scene.write_text(_SCENE_WITH_ARC["reference"])

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        part_stage = _open(adapter, part)
        _edit_and_save_height(part_stage, "/World/Spike", 48.0)
        stage = _open(adapter, scene)
        copies = _renderer_root(adapter).parent
        (part_copy,) = [path for path in copies.iterdir() if path != _renderer_root(adapter)]

        # Each unsaved edit of the scene gives a new copy of its root layer.
        # Only the copies that the renderer loaded stay: that root copy and
        # the copy of the referenced layer that it names.
        for size in (20.0, 30.0, 40.0, 20.0):
            stage.GetPrimAtPath("/World/Box/Cube").GetAttribute("size").Set(size)
            adapter.load_stage(stage)
            assert _renderer_value(adapter, "size", "/World/Box/Cube") == size
            assert _renderer_height(adapter, "/World/RefObj/Spike") == 48.0
            assert sorted(copies.iterdir()) == sorted([_renderer_root(adapter), part_copy])
    finally:
        adapter.shutdown()


def test_a_file_whose_state_cannot_be_read_is_reported_once(tmp_path, capsys):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    part = tmp_path / "ref_part.usda"
    part.write_text(_PART)
    (tmp_path / "box.usda").write_text(_BOX)
    scene = tmp_path / "consist.usda"
    scene.write_text(_SCENE_WITH_ARC["reference"])

    adapter = OvRtxRendererAdapter()
    try:
        _open(adapter, scene)
        # The referenced file is removed; its layer stays in memory.
        part.unlink()
        capsys.readouterr()
        for _ in range(2):
            _open(adapter, scene)
            assert _renderer_height(adapter, "/World/RefObj/Spike") == 24.0
        reports = [
            line for line in capsys.readouterr().err.splitlines() if part.name in line and "state" in line
        ]
        assert len(reports) == 1, reports
    finally:
        adapter.shutdown()
