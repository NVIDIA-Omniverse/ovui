# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Save As of the authoring layer on a real ``Usd.Stage``.

The parent swap of :class:`SaveLayerAsCommand` takes the source out of
the stack. The viewport camera writer then edits through a
``Usd.EditContext`` on the session layer; that context cannot restore a
target on a layer that left the stack, so the session layer stayed the
authoring layer and Save All lost the next edits.

These tests need OpenUSD. They are in their own module so that
``test_layers_step36_save_as.py`` still loads where OpenUSD is not
installed.
"""

from __future__ import annotations

from pxr import Sdf, Usd

from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter

from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import LayerModel
from ovui_widgets.layers.commands import SaveLayerAsCommand


class _App:
    """Minimal :class:`Application` stand-in: the undo manager and the
    selection bus are the only attributes these paths read.
    """

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


def _build(tmp_path):
    (tmp_path / "project" / "layers").mkdir(parents=True)
    (tmp_path / "out").mkdir()
    lighting = Sdf.Layer.CreateNew(
        str(tmp_path / "project" / "layers" / "lighting.usda")
    )
    lighting.Save()
    root = Sdf.Layer.CreateNew(str(tmp_path / "project" / "main.usda"))
    root.subLayerPaths.append("./layers/lighting.usda")
    Sdf.CreatePrimInLayer(root, "/World/Table").specifier = Sdf.SpecifierDef
    root.Save()

    stage = Usd.Stage.Open(str(tmp_path / "project" / "main.usda"))
    adapter = UsdLayerStackAdapter(stage, UndoManager())
    adapter.get_sublayer_identifiers(adapter.get_root_layer())
    return stage, adapter, lighting.identifier, str(tmp_path / "out" / "k1.usda")


class TestSaveAsAuthoringLayerOnUsdStage:
    def test_edit_after_save_as_goes_to_new_file(self, tmp_path) -> None:
        stage, adapter, lighting_id, new_path = _build(tmp_path)
        app = _App()
        adapter.set_edit_target(lighting_id)

        app.undo_manager.push(SaveLayerAsCommand(
            adapter, app.selection_bus, lighting_id, new_path,
        ))

        new_layer = Sdf.Layer.Find(new_path)
        assert adapter.get_edit_target_identifier() == new_layer.identifier
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            pass
        stage.GetPrimAtPath("/World/Table").CreateAttribute(
            "userMove", Sdf.ValueTypeNames.Double,
        ).Set(1.0)
        assert new_layer.GetAttributeAtPath("/World/Table.userMove") is not None
        assert stage.GetSessionLayer().GetAttributeAtPath(
            "/World/Table.userMove"
        ) is None

        # Save All of the Layers window, then read the file from disk.
        model = LayerModel(adapter, services=app)
        try:
            model._request_save_all()
        finally:
            model.destroy()
        on_disk = Sdf.Layer.OpenAsAnonymous(new_path)
        assert on_disk.GetAttributeAtPath("/World/Table.userMove").default == 1.0

    def test_undo_and_redo_move_authoring_layer(self, tmp_path) -> None:
        stage, adapter, lighting_id, new_path = _build(tmp_path)
        app = _App()
        adapter.set_edit_target(lighting_id)
        app.undo_manager.push(SaveLayerAsCommand(
            adapter, app.selection_bus, lighting_id, new_path,
        ))
        new_id = Sdf.Layer.Find(new_path).identifier

        app.undo_manager.undo()
        assert adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        ) == [lighting_id]
        assert adapter.get_edit_target_identifier() == lighting_id

        app.undo_manager.redo()
        assert adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        ) == [new_id]
        assert adapter.get_edit_target_identifier() == new_id

    def test_save_as_of_other_layer_keeps_authoring_layer(self, tmp_path) -> None:
        stage, adapter, lighting_id, new_path = _build(tmp_path)
        app = _App()
        root_id = adapter.get_root_layer().identifier
        adapter.set_edit_target(root_id)

        app.undo_manager.push(SaveLayerAsCommand(
            adapter, app.selection_bus, lighting_id, new_path,
        ))

        assert adapter.get_edit_target_identifier() == root_id

    def test_save_as_without_parent_swap_keeps_authoring_layer(
        self, tmp_path,
    ) -> None:
        # The session layer is the sublayer of no layer, so its Save As
        # swaps no parent entry and the new file is not in the stack.
        stage, adapter, lighting_id, new_path = _build(tmp_path)
        app = _App()
        session_id = stage.GetSessionLayer().identifier
        adapter.set_edit_target(session_id)

        app.undo_manager.push(SaveLayerAsCommand(
            adapter, app.selection_bus, session_id, new_path,
        ))

        assert Sdf.Layer.Find(new_path) is not None
        assert adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        ) == [lighting_id]
        assert adapter.get_edit_target_identifier() == session_id
