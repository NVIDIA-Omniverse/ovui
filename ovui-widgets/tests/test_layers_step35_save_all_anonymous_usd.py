# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Save All of anonymous sublayers on a real ``Usd.Stage``.

The Save-As dialogs are answered by the test; the layers, the files and
the edits are real OpenUSD data. These tests need OpenUSD, so they are
in their own module and ``test_layers_step35_save_all.py`` still loads
where OpenUSD is not installed.
"""

from __future__ import annotations

import os

import pytest
from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter
from pxr import Sdf, Usd, UsdGeom

from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import LayerModel


class _App:
    """Minimal :class:`Application` stand-in: the undo manager and the
    selection bus are the only attributes these paths read.
    """

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


def _open_scene(tmp_path):
    """Open root.usda with base.usda (Box, Ball, Dome) as its sublayer."""
    base = Sdf.Layer.CreateNew(str(tmp_path / "base.usda"))
    for name in ("Box", "Ball", "Dome"):
        Sdf.CreatePrimInLayer(base, f"/World/{name}").specifier = Sdf.SpecifierDef
    base.Save()
    root = Sdf.Layer.CreateNew(str(tmp_path / "root.usda"))
    root.subLayerPaths.append("./base.usda")
    root.Save()
    stage = Usd.Stage.Open(str(tmp_path / "root.usda"))
    adapter = UsdLayerStackAdapter(stage, UndoManager())
    return stage, adapter


def _add_anonymous_layer(stage, adapter) -> str:
    """Add an anonymous sublayer as the Layers row menu does."""
    root_id = adapter.get_root_layer().identifier
    return adapter.create_sublayer(root_id, -1, "")


def _hide(stage, layer_id: str, prim_path: str) -> None:
    with Usd.EditContext(stage, Sdf.Layer.Find(layer_id)):
        UsdGeom.Imageable(stage.GetPrimAtPath(prim_path)).MakeInvisible()


def _accept_default_paths(monkeypatch) -> list:
    """Answer each Save-As dialog with its default path."""
    titles: list = []

    def _dialog(title, default_name, on_selected, default_dir=None, **kw):
        titles.append(title)
        on_selected(os.path.join(default_dir, default_name))

    monkeypatch.setattr(
        "ovui_widgets.common.file_dialogs.save_file_dialog", _dialog,
    )
    return titles


def _visibility_on_disk(path: str, prim_path: str):
    layer = Sdf.Layer.OpenAsAnonymous(path)
    spec = layer.GetAttributeAtPath(f"{prim_path}.visibility")
    return None if spec is None else spec.default


_ASSET_TEXT = '#usda 1.0\n(\n    defaultPrim = "World"\n)\n\ndef Xform "World"\n{\n    def Cube "Box"\n    {\n    }\n}\n'


def _open_scene_with_used_files(tmp_path):
    """Open a root that uses five files outside its sublayers.

    asset.usda is a reference, payload.usda a loaded payload,
    unloaded.usda an unloaded payload, muted.usda a muted sublayer,
    session.usda a sublayer of the session layer, and held.usda a file
    that is open in memory only (as a removed sublayer that Undo can
    bring back). The returned layer keeps held.usda open.
    """
    for name in ("asset", "payload", "unloaded", "muted", "session", "held"):
        (tmp_path / f"{name}.usda").write_text(_ASSET_TEXT)
    (tmp_path / "root.usda").write_text(
        "#usda 1.0\n"
        "(\n    subLayers = [@./muted.usda@]\n)\n"
        'def Xform "Ref" (prepend references = @./asset.usda@</World>) {}\n'
        'def Xform "Pay" (prepend payload = @./payload.usda@</World>) {}\n'
        'def Xform "Off" (prepend payload = @./unloaded.usda@</World>) {}\n'
    )
    stage = Usd.Stage.Open(str(tmp_path / "root.usda"))
    stage.Unload("/Off")
    stage.MuteLayer(str(tmp_path / "muted.usda"))
    stage.GetSessionLayer().subLayerPaths.append(str(tmp_path / "session.usda"))
    held = Sdf.Layer.FindOrOpen(str(tmp_path / "held.usda"))
    adapter = UsdLayerStackAdapter(stage, UndoManager())
    return stage, adapter, held


@pytest.mark.parametrize(
    "used_file", ["asset", "payload", "unloaded", "muted", "session", "held"],
)
def test_file_that_the_scene_uses_is_refused(
    tmp_path, monkeypatch, used_file,
) -> None:
    # Review 2: Replace wrote the anonymous layer over a referenced file,
    # and the scene lost the content of that file.
    stage, adapter, held = _open_scene_with_used_files(tmp_path)
    _add_anonymous_layer(stage, adapter)
    used_path = str(tmp_path / f"{used_file}.usda")
    answers = iter([used_path, str(tmp_path / "new.usda")])
    dialogs: list = []

    def _dialog(title, default_name, on_selected, **kw):
        dialogs.append(dict(kw, default_name=default_name))
        on_selected(next(answers))

    monkeypatch.setattr(
        "ovui_widgets.common.file_dialogs.save_file_dialog", _dialog,
    )
    prompts: list = []
    monkeypatch.setattr(
        "ovui_widgets.common.dialogs.confirm_dialog",
        lambda **kw: prompts.append(kw),
    )
    model = LayerModel(adapter, services=_App())
    try:
        model._request_save_all()
    finally:
        model.destroy()

    # No Replace question: the file is refused, and the question asks again.
    assert prompts == []
    assert len(dialogs) == 2
    assert "the open scene uses this file" in dialogs[1]["message"]
    assert (tmp_path / f"{used_file}.usda").read_text() == _ASSET_TEXT
    root_on_disk = Sdf.Layer.OpenAsAnonymous(str(tmp_path / "root.usda"))
    assert [os.path.basename(path) for path in root_on_disk.subLayerPaths] == [
        "muted.usda", "new.usda",
    ]


def test_two_anonymous_layers_keep_their_edits_on_disk(
    tmp_path, monkeypatch,
) -> None:
    # The review steps: two anonymous layers, Box hidden in the first and
    # Ball hidden in the second, Save All, Save with the default twice.
    stage, adapter = _open_scene(tmp_path)
    first = _add_anonymous_layer(stage, adapter)
    second = _add_anonymous_layer(stage, adapter)
    _hide(stage, first, "/World/Box")
    _hide(stage, second, "/World/Ball")
    titles = _accept_default_paths(monkeypatch)
    model = LayerModel(adapter, services=_App())
    try:
        model._request_save_all()
    finally:
        model.destroy()

    assert len(titles) == 2
    first_file = str(tmp_path / "anonymous.usda")
    second_file = str(tmp_path / "anonymous_1.usda")
    assert _visibility_on_disk(first_file, "/World/Box") == "invisible"
    assert _visibility_on_disk(second_file, "/World/Ball") == "invisible"
    root_on_disk = Sdf.Layer.OpenAsAnonymous(str(tmp_path / "root.usda"))
    assert [os.path.basename(path) for path in root_on_disk.subLayerPaths] == [
        "base.usda", "anonymous.usda", "anonymous_1.usda",
    ]


def test_edit_after_save_all_of_authoring_layer_lands_in_saved_file(
    tmp_path, monkeypatch,
) -> None:
    stage, adapter = _open_scene(tmp_path)
    anonymous = _add_anonymous_layer(stage, adapter)
    adapter.set_edit_target(anonymous)
    _accept_default_paths(monkeypatch)
    app = _App()

    def _persist_layer_state() -> bool:
        # What the application hook does before Save All writes a file.
        adapter.persist_layer_state_before_save(stage)
        return True

    model = LayerModel(
        adapter, services=app, before_save_all_fn=_persist_layer_state,
    )
    try:
        model._request_save_all()
        saved = Sdf.Layer.Find(str(tmp_path / "anonymous.usda"))
        assert adapter.get_edit_target_identifier() == saved.identifier
        # The root file names the saved file as the authoring layer, not
        # the ``anon:`` identifier that exists only in this session.
        root_on_disk = Sdf.Layer.OpenAsAnonymous(str(tmp_path / "root.usda"))
        stored = root_on_disk.customLayerData["ovgear_layer"]["authoring_layer"]
        assert stored == saved.identifier

        # The edit goes into the saved file, and Save All writes it.
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Dome")).MakeInvisible()
        assert saved.dirty
        model._request_save_all()
    finally:
        model.destroy()

    assert _visibility_on_disk(saved.identifier, "/World/Dome") == "invisible"

    # Undo puts the anonymous layer back as the authoring layer; Redo
    # makes the saved file the authoring layer again.
    app.undo_manager.undo()
    assert adapter.get_edit_target_identifier() == anonymous
    app.undo_manager.redo()
    assert adapter.get_edit_target_identifier() == saved.identifier
