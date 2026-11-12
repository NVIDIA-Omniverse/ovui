# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A cancelled number edit leaves a saved layer unmodified, with no reload.

Escape in a Property Inspector number field undoes the edit. The
Layers window (Save All and the modified dot) must then show a layer that had
no unsaved change as not modified. Reading the file again and reloading the
layer did that, but the reload rebuilds the whole stage and stopped the
window for seconds in a large scene. So the cancel must not resync the stage.

A layer must still show as modified whenever it can have an unsaved change:
after a later change, when something else changed it during the edit (also a
listener that writes while the edit writes), and when it was already modified
before the edit. Save All and File > Exit read this state, so a hidden change
would be lost.
"""

from __future__ import annotations

import pytest

from pxr import Gf, Sdf, Tf, Usd, UsdGeom  # noqa: E402

from ovui_data_adapters.common import LayerEventType, LayerHandle  # noqa: E402
from ovui_data_adapters.openusd.layer_stack_adapter import (  # noqa: E402
    UsdLayerStackAdapter,
)
from ovui_data_adapters.openusd.property_adapter import (  # noqa: E402
    UsdPropertyAdapter,
)
from ovui_data_adapters.services.undo import UndoManager  # noqa: E402

_TRANSLATE = "xformOp:translate"
_START = (-932.1000138893723, -1500.2240890559156, 0.3500151634072495)


@pytest.fixture()
def scene(tmp_path):
    """A saved stage with /Ramp and /Other, its Layers adapter and a record
    of what the Layers window is told and of every stage resync."""
    stage = Usd.Stage.CreateNew(str(tmp_path / "ramp.usd"))
    UsdGeom.Xform.Define(stage, "/Ramp").AddTranslateOp().Set(Gf.Vec3d(*_START))
    UsdGeom.Xform.Define(stage, "/Other").AddTranslateOp().Set(Gf.Vec3d(1, 2, 3))
    stage.Save()
    undo = UndoManager()
    layers = UsdLayerStackAdapter(stage, undo)
    layers.attach_stage()
    events = []
    subscription = layers.subscribe_events(events.append)
    resynced = []
    key = Tf.Notice.Register(
        Usd.Notice.ObjectsChanged,
        lambda notice, _sender: resynced.extend(notice.GetResyncedPaths()),
        stage,
    )
    adapter = UsdPropertyAdapter(stage, ["/Ramp"], undo_manager=undo)
    root = LayerHandle(stage.GetRootLayer().identifier)
    yield stage, undo, layers, adapter, root, events, resynced
    key.Revoke()
    subscription.cancel()
    layers.detach_stage()


def _translate(stage, path="/Ramp"):
    return tuple(stage.GetPrimAtPath(path).GetAttribute(_TRANSLATE).Get())


def _type(adapter, z):
    adapter.begin_edit(_TRANSLATE)
    adapter.set_value(_TRANSLATE, (_START[0], _START[1], z))


def _dirty_events(events):
    return [e for e in events if e.event_type == LayerEventType.DIRTY_STATE_CHANGED]


@pytest.mark.parametrize("finish", ["cancel_edit", "end_edit_with_start_value"])
def test_undone_edit_shows_a_saved_layer_unmodified_without_a_reload(scene, finish):
    stage, undo, layers, adapter, root, events, resynced = scene
    _type(adapter, 50.0)
    assert layers.is_dirty(root)  # the typed value is written live
    events.clear()

    if finish == "cancel_edit":  # Escape in a decimal number field
        adapter.cancel_edit(_TRANSLATE)
    else:  # Escape in an integer field writes the start value back
        adapter.set_value(_TRANSLATE, _START)
        adapter.end_edit(_TRANSLATE)

    assert _translate(stage) == _START
    assert not undo.can_undo()
    assert not layers.is_dirty(root)
    # The Layers window is told, so Save All and the dot go off.
    assert root.identifier in _dirty_events(events)[-1].identifiers
    # No reload: a reload resyncs the whole stage.
    assert resynced == []


def test_a_later_change_shows_the_layer_modified_again(scene):
    stage, _undo, layers, adapter, root, events, _resynced = scene
    _type(adapter, 50.0)
    adapter.cancel_edit(_TRANSLATE)
    assert not layers.is_dirty(root)
    events.clear()

    stage.GetPrimAtPath("/Other").GetAttribute(_TRANSLATE).Set(Gf.Vec3d(7, 8, 9))

    assert layers.is_dirty(root)
    assert root.identifier in _dirty_events(events)[-1].identifiers


def test_a_change_by_others_during_the_edit_keeps_the_layer_modified(scene):
    stage, _undo, layers, adapter, root, _events, _resynced = scene
    _type(adapter, 50.0)
    stage.GetPrimAtPath("/Other").GetAttribute(_TRANSLATE).Set(Gf.Vec3d(7, 8, 9))

    adapter.cancel_edit(_TRANSLATE)

    assert _translate(stage) == _START
    assert _translate(stage, "/Other") == (7, 8, 9)
    assert layers.is_dirty(root)


def test_a_layer_modified_before_the_edit_stays_modified(scene):
    stage, _undo, layers, adapter, root, _events, _resynced = scene
    stage.GetPrimAtPath("/Other").GetAttribute(_TRANSLATE).Set(Gf.Vec3d(7, 8, 9))
    assert layers.is_dirty(root)

    _type(adapter, 50.0)
    adapter.cancel_edit(_TRANSLATE)

    assert _translate(stage) == _START
    assert layers.is_dirty(root)


class _WriteWhenThePreviewReaches50:
    """A listener of the stage, as an extension can have: when the edited
    value reaches 50, it writes at once, before the edit's write returns.
    OpenUSD keeps only a weak reference to the callback, so this object
    keeps it until ``Revoke``."""

    def __init__(self, stage, write):
        self._stage = stage
        self._write = write
        self.wrote = False
        self._key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._on_change, stage)

    def _on_change(self, _notice, _sender):
        if not self.wrote and _translate(self._stage)[2] == 50.0:
            self.wrote = True
            self._write()

    def Revoke(self):
        self._key.Revoke()


def test_a_listener_write_to_another_prim_keeps_the_layer_modified_and_saved(scene, tmp_path):
    stage, undo, layers, adapter, root, _events, _resynced = scene
    other = stage.GetPrimAtPath("/Other").GetAttribute(_TRANSLATE)
    key = _WriteWhenThePreviewReaches50(stage, lambda: other.Set(Gf.Vec3d(7, 8, 9)))
    try:
        _type(adapter, 50.0)
        adapter.cancel_edit(_TRANSLATE)
    finally:
        key.Revoke()

    assert key.wrote
    assert _translate(stage) == _START
    assert _translate(stage, "/Other") == (7, 8, 9)
    assert not undo.can_undo()
    # Save All and File > Exit see the unsaved change of /Other.
    assert layers.is_dirty(root)
    assert layers.save_layer(root.identifier)
    on_disk = Sdf.Layer.OpenAsAnonymous(stage.GetRootLayer().realPath)
    assert tuple(on_disk.GetAttributeAtPath("/Other.xformOp:translate").default) == (7, 8, 9)


def test_a_listener_change_to_the_edited_prim_keeps_the_layer_modified(scene):
    stage, _undo, layers, adapter, root, _events, _resynced = scene
    ramp = stage.GetPrimAtPath("/Ramp")
    key = _WriteWhenThePreviewReaches50(stage, lambda: ramp.SetMetadata("kind", "component"))
    try:
        _type(adapter, 50.0)
        adapter.cancel_edit(_TRANSLATE)
    finally:
        key.Revoke()

    assert key.wrote
    assert _translate(stage) == _START
    assert ramp.GetMetadata("kind") == "component"
    assert layers.is_dirty(root)


def test_an_edit_of_a_prim_with_no_spec_in_the_layer_shows_it_unmodified_again(tmp_path):
    # The prim comes from a sublayer: the edit's write creates its prim spec
    # in the root layer, and the cancel removes it again.
    sub = Usd.Stage.CreateNew(str(tmp_path / "sub.usda"))
    UsdGeom.Xform.Define(sub, "/Ramp").AddTranslateOp().Set(Gf.Vec3d(*_START))
    sub.Save()
    stage = Usd.Stage.CreateNew(str(tmp_path / "root.usda"))
    stage.GetRootLayer().subLayerPaths.append("sub.usda")
    stage.Save()
    undo = UndoManager()
    layers = UsdLayerStackAdapter(stage, undo)
    layers.attach_stage()
    try:
        root = LayerHandle(stage.GetRootLayer().identifier)
        adapter = UsdPropertyAdapter(stage, ["/Ramp"], undo_manager=undo)
        _type(adapter, 50.0)
        assert stage.GetRootLayer().GetPrimAtPath("/Ramp") is not None

        adapter.cancel_edit(_TRANSLATE)

        assert _translate(stage) == _START
        assert stage.GetRootLayer().GetPrimAtPath("/Ramp") is None
        assert not layers.is_dirty(root)
    finally:
        layers.detach_stage()


def test_an_edit_of_a_prim_with_a_payload_shows_the_layer_unmodified_again(tmp_path):
    # Car_Lift_Adjust of the Factory scene has a payload. Its metadata must be
    # compared by value: the text of a payload list differs for each read.
    asset = Usd.Stage.CreateNew(str(tmp_path / "asset.usda"))
    UsdGeom.Xform.Define(asset, "/Asset")
    asset.GetRootLayer().defaultPrim = "Asset"
    asset.Save()
    stage = Usd.Stage.CreateNew(str(tmp_path / "root.usd"))
    ramp = UsdGeom.Xform.Define(stage, "/Ramp")
    ramp.AddTranslateOp().Set(Gf.Vec3d(*_START))
    ramp.GetPrim().GetPayloads().AddPayload("asset.usda")
    stage.Save()
    undo = UndoManager()
    layers = UsdLayerStackAdapter(stage, undo)
    layers.attach_stage()
    try:
        root = LayerHandle(stage.GetRootLayer().identifier)
        adapter = UsdPropertyAdapter(stage, ["/Ramp"], undo_manager=undo)
        _type(adapter, 50.0)

        adapter.cancel_edit(_TRANSLATE)

        assert _translate(stage) == _START
        assert not layers.is_dirty(root)
    finally:
        layers.detach_stage()
