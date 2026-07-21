# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Property Inspector edit transactions restore the exact authored opinion.

The begin/set/end edit transaction is anchored on pre/post property-spec
snapshots of the edit-target layer: undo restores the exact prior opinion
(including its ABSENCE), redo replays the exact post state, "changed" is
decided from the target layer's truth (shadowed edits stay undoable), and
same-value commits never pollute history.
"""

import gc

import pytest

pxr = pytest.importorskip("pxr")
from pxr import Usd, UsdGeom  # noqa: E402

from ovui_data_adapters.openusd.property_adapter import UsdPropertyAdapter  # noqa: E402
from ovui_data_adapters.services.undo import UndoManager  # noqa: E402


def _fixture():
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Cube.Define(stage, "/World/Leaf")
    undo = UndoManager()
    adapter = UsdPropertyAdapter(stage, ["/World/Leaf"], undo_manager=undo)
    attr = stage.GetPrimAtPath("/World/Leaf").GetAttribute("visibility")
    return stage, undo, adapter, attr


def _edit(adapter, value):
    adapter.begin_edit("visibility")
    adapter.set_value("visibility", value)
    adapter.end_edit("visibility")


class TestPropertyEditTransactions:
    def test_undo_restores_exact_unauthored_state(self):
        _stage, undo, adapter, attr = _fixture()
        assert not attr.HasAuthoredValueOpinion()
        _edit(adapter, "invisible")
        assert attr.HasAuthoredValueOpinion()
        assert attr.Get() == "invisible"
        assert undo.can_undo()
        undo.undo()
        # EXACT restore: no residual authored opinion, not a fabricated
        # 'inherited' spec carrying the previously resolved value.
        assert not attr.HasAuthoredValueOpinion()
        assert attr.Get() == "inherited"

    def test_redo_replays_exact_authored_state(self):
        _stage, undo, adapter, attr = _fixture()
        _edit(adapter, "invisible")
        undo.undo()
        undo.redo()
        assert attr.HasAuthoredValueOpinion()
        assert attr.Get() == "invisible"
        undo.undo()
        assert not attr.HasAuthoredValueOpinion()

    def test_shadowed_target_layer_edit_stays_undoable(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Leaf")
        with Usd.EditContext(stage, Usd.EditTarget(stage.GetSessionLayer())):
            UsdGeom.Imageable(
                stage.GetPrimAtPath("/World/Leaf")).MakeInvisible()
        stage.SetEditTarget(Usd.EditTarget(stage.GetRootLayer()))
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/Leaf"], undo_manager=undo)
        _edit(adapter, "inherited")   # authors ROOT; resolved stays invisible
        root = stage.GetRootLayer()
        spec = root.GetAttributeAtPath("/World/Leaf.visibility")
        # The target layer genuinely changed: NOT a no-op — one undoable
        # transaction exists even though the resolved value is unchanged.
        assert spec is not None and spec.HasDefaultValue()
        assert undo.can_undo()
        undo.undo()
        spec = root.GetAttributeAtPath("/World/Leaf.visibility")
        # Exact root-layer restore: the created spec is gone; the session
        # opinion still governs the resolved value.
        assert spec is None or not spec.HasDefaultValue()
        assert stage.GetPrimAtPath(
            "/World/Leaf").GetAttribute("visibility").Get() == "invisible"

    def test_same_value_commit_never_pollutes_history(self):
        _stage, undo, adapter, attr = _fixture()
        _edit(adapter, "invisible")
        depth = len(undo._undo_stack)
        _edit(adapter, "invisible")   # same value: target layer untouched
        assert len(undo._undo_stack) == depth
        undo.undo()
        assert not attr.HasAuthoredValueOpinion()
        assert not undo.can_undo()

    def test_pre_authored_value_round_trips_exactly(self):
        stage, undo, adapter, attr = _fixture()
        attr.Set("invisible")   # pre-existing authored opinion
        _edit(adapter, "inherited")
        assert attr.Get() == "inherited"
        undo.undo()
        assert attr.HasAuthoredValueOpinion()
        assert attr.Get() == "invisible"

    def test_undo_lands_in_the_recorded_layer_after_target_change(self):
        stage, undo, adapter, attr = _fixture()
        _edit(adapter, "invisible")   # authored with the ROOT target
        # The user then moves the edit target: undo must still restore
        # the ROOT layer, not author into the session layer.
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        undo.undo()
        assert not attr.HasAuthoredValueOpinion()
        session_spec = stage.GetSessionLayer().GetAttributeAtPath(
            "/World/Leaf.visibility")
        assert session_spec is None


class TestTransactionModesAndOwnership:
    """Round-25 blockers: mode freezing, atomic replay, drift, ownership."""

    def test_direct_variant_edit_is_tracked_with_exact_undo(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        prim = UsdGeom.Cube.Define(stage, "/World/Leaf").GetPrim()
        vs = prim.GetVariantSets().AddVariantSet("look")
        vs.AddVariant("A")
        vs.SetVariantSelection("A")
        stage.SetEditTarget(vs.GetVariantEditTarget())
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/Leaf"], undo_manager=undo)
        _edit(adapter, "invisible")
        mapped = stage.GetRootLayer().GetAttributeAtPath(
            "/World/Leaf{look=A}.visibility")
        assert mapped is not None and mapped.HasDefaultValue()
        assert undo.can_undo()
        undo.undo()
        mapped = stage.GetRootLayer().GetAttributeAtPath(
            "/World/Leaf{look=A}.visibility")
        assert mapped is None or not mapped.HasDefaultValue()
        assert prim.GetAttribute("visibility").Get() == "inherited"
        undo.redo()
        assert prim.GetAttribute("visibility").Get() == "invisible"

    def test_offset_mapping_uses_whole_layer_mode(self):
        from pxr import Sdf

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Leaf")
        sub = Sdf.Layer.CreateAnonymous("offset-sub")
        stage.GetRootLayer().subLayerPaths.append(sub.identifier)
        stage.GetRootLayer().subLayerOffsets[0] = Sdf.LayerOffset(offset=5.0)
        stage.SetEditTarget(stage.GetEditTargetForLocalLayer(sub))
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/Leaf"], undo_manager=undo)
        _edit(adapter, "invisible")
        assert undo.can_undo()
        undo.undo()
        assert sub.GetAttributeAtPath("/World/Leaf.visibility") is None

    def test_failed_undo_replay_restores_invocation_baseline(self, monkeypatch):
        from pxr import Sdf

        import ovui_data_adapters.openusd.commands as commands_mod

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        for name in ("A", "B"):
            prim = UsdGeom.Cube.Define(stage, f"/World/{name}").GetPrim()
            prim.GetAttribute("visibility").Set("inherited")
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/A", "/World/B"], undo_manager=undo)
        _edit(adapter, "invisible")
        real_copy = Sdf.CopySpec
        calls = {"n": 0}

        def failing_copy(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise RuntimeError("injected CopySpec failure")
            return real_copy(*args, **kwargs)

        monkeypatch.setattr(commands_mod.Sdf, "CopySpec", failing_copy)
        with pytest.raises(RuntimeError):
            undo.undo()
        monkeypatch.setattr(commands_mod.Sdf, "CopySpec", real_copy)
        # ATOMIC: the failed replay restored the exact invocation baseline
        # (both prims still invisible) and never moved the history cursor.
        for name in ("A", "B"):
            assert stage.GetPrimAtPath(
                f"/World/{name}").GetAttribute("visibility").Get() == "invisible"
        assert undo.can_undo() and not undo.can_redo()
        undo.undo()   # a later retry succeeds exactly
        for name in ("A", "B"):
            assert stage.GetPrimAtPath(
                f"/World/{name}").GetAttribute("visibility").Get() == "inherited"

    def test_edit_target_drift_authors_into_frozen_target(self):
        stage, undo, adapter, attr = _fixture()
        adapter.begin_edit("visibility")
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        adapter.set_value("visibility", "invisible")
        adapter.end_edit("visibility")
        assert stage.GetRootLayer().GetAttributeAtPath(
            "/World/Leaf.visibility") is not None
        assert stage.GetSessionLayer().GetAttributeAtPath(
            "/World/Leaf.visibility") is None
        assert undo.can_undo()
        undo.undo()
        assert stage.GetRootLayer().GetAttributeAtPath(
            "/World/Leaf.visibility") is None

    def test_unmatched_end_edit_is_inert(self):
        _stage, undo, adapter, _attr = _fixture()
        undo.begin_group("FOREIGN")
        adapter.end_edit("visibility")
        assert len(undo._group_stack) == 1
        undo.end_group()

    def test_nested_begin_refused_first_transaction_intact(self):
        _stage, undo, adapter, attr = _fixture()
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        with pytest.raises(RuntimeError):
            adapter.begin_edit("visibility")
        adapter.end_edit("visibility")
        assert len(undo._undo_stack) == 1
        undo.undo()
        assert not attr.HasAuthoredValueOpinion()

    def test_post_capture_failure_restores_baseline(self, monkeypatch):
        import ovui_data_adapters.openusd.commands as commands_mod

        _stage, undo, adapter, attr = _fixture()
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        orig = commands_mod._TargetedVisibilitySnapshot.__init__
        state = {"fail": True}

        def failing(self, layer, paths, prop_name="visibility",
                    prop_spec_paths=None):
            if state["fail"]:
                raise RuntimeError("injected post-capture failure")
            return orig(self, layer, paths, prop_name,
                        prop_spec_paths=prop_spec_paths)

        monkeypatch.setattr(
            commands_mod._TargetedVisibilitySnapshot, "__init__", failing)
        with pytest.raises(RuntimeError):
            adapter.end_edit("visibility")
        state["fail"] = False
        assert not attr.HasAuthoredValueOpinion()
        assert len(undo._undo_stack) == 0
        assert len(undo._group_stack) == 0
        assert not adapter._edit_snapshots

    def test_cancel_edit_removes_partial_authorship(self):
        _stage, undo, adapter, attr = _fixture()
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        adapter.cancel_edit("visibility")
        assert not attr.HasAuthoredValueOpinion()
        assert len(undo._undo_stack) == 0
        assert not adapter._edit_snapshots
        adapter.cancel_edit("visibility")   # idempotent without a token

    def test_foreign_change_without_owned_write_records_nothing(self):
        from pxr import Sdf

        from ovui_data_adapters.openusd.commands import DeletePrimCommand

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/A")
        UsdGeom.Cube.Define(stage, "/World/B")
        undo = UndoManager()
        adapter = UsdPropertyAdapter(stage, ["/World/A"], undo_manager=undo)
        adapter.begin_edit("visibility")
        undo.push(DeletePrimCommand(stage, Sdf.Path("/World/B")))
        adapter.end_edit("visibility")
        assert len(undo._undo_stack) == 1
        assert "Set visibility" not in str(
            getattr(undo._undo_stack[-1], "label", ""))

    def test_deleted_target_prim_closes_without_entry(self):
        from pxr import Sdf

        stage, undo, adapter, _attr = _fixture()
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        stage.RemovePrim(Sdf.Path("/World/Leaf"))
        depth = len(undo._undo_stack)
        adapter.end_edit("visibility")
        assert len(undo._undo_stack) == depth
        assert not adapter._edit_snapshots


class TestTransactionClosure:
    """Round-26 closure blockers: re-entrant drift, foreign-content
    ownership, namespace settlement, and cross-adapter overlap."""

    def test_reentrant_drift_keeps_every_member_in_frozen_target(self):
        from pxr import Tf

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/A")
        UsdGeom.Cube.Define(stage, "/World/B")
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/A", "/World/B"], undo_manager=undo)
        switched = {"done": False}

        def on_notice(notice, sender):
            # GENUINE synchronous notice: switch the target between the
            # members of one multi-prim edit.
            if not switched["done"]:
                switched["done"] = True
                stage.SetEditTarget(
                    Usd.EditTarget(stage.GetSessionLayer()))

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, on_notice, stage)
        try:
            _edit(adapter, "invisible")
        finally:
            key.Revoke()
        root = stage.GetRootLayer()
        assert root.GetAttributeAtPath("/World/A.visibility") is not None
        assert root.GetAttributeAtPath("/World/B.visibility") is not None
        assert stage.GetSessionLayer().GetAttributeAtPath(
            "/World/B.visibility") is None
        # The foreign callback's own target choice is preserved.
        assert stage.GetEditTarget().GetLayer() == stage.GetSessionLayer()
        assert len(undo._undo_stack) == 1
        undo.undo()
        for name in ("A", "B"):
            assert not stage.GetPrimAtPath(
                f"/World/{name}").GetAttribute(
                "visibility").HasAuthoredValueOpinion()

    def test_variant_undo_redo_never_owns_foreign_same_layer_content(self):
        from pxr import Sdf

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        prim = UsdGeom.Cube.Define(stage, "/World/Leaf").GetPrim()
        vs = prim.GetVariantSets().AddVariantSet("look")
        vs.AddVariant("A")
        vs.SetVariantSelection("A")
        stage.SetEditTarget(vs.GetVariantEditTarget())
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/Leaf"], undo_manager=undo)
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        layer = stage.GetRootLayer()
        foreign = Sdf.CreatePrimInLayer(layer, "/Foreign")
        foreign.customData = {"owner": "someone-else"}
        adapter.end_edit("visibility")
        undo.undo()
        spec = layer.GetPrimAtPath("/Foreign")
        assert spec is not None
        assert dict(spec.customData) == {"owner": "someone-else"}
        assert prim.GetAttribute("visibility").Get() == "inherited"
        undo.redo()
        spec = layer.GetPrimAtPath("/Foreign")
        assert spec is not None
        assert dict(spec.customData) == {"owner": "someone-else"}
        assert prim.GetAttribute("visibility").Get() == "invisible"

    def test_undoable_rename_settles_active_edit_first(self):
        from pxr import Sdf

        from ovui_data_adapters.openusd.commands import NamespaceEditCommand

        stage, undo, adapter, _attr = _fixture()
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        undo.push(NamespaceEditCommand(
            stage.GetRootLayer(),
            Sdf.Path("/World/Leaf"), Sdf.Path("/World/Renamed")))
        adapter.end_edit("visibility")   # already settled: inert
        labels = [str(getattr(c, "label", "")) for c in undo._undo_stack]
        assert len(undo._undo_stack) == 2
        assert "Set visibility" in labels[0]
        assert stage.GetPrimAtPath("/World/Renamed").GetAttribute(
            "visibility").Get() == "invisible"
        undo.undo()   # rename back
        undo.undo()   # visibility back
        assert not stage.GetPrimAtPath("/World/Leaf").GetAttribute(
            "visibility").HasAuthoredValueOpinion()

    def test_undoable_delete_settles_first_and_never_resurrects(self):
        from pxr import Sdf

        from ovui_data_adapters.openusd.commands import DeletePrimCommand

        stage, undo, adapter, _attr = _fixture()
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        undo.push(DeletePrimCommand(stage, Sdf.Path("/World/Leaf")))
        adapter.end_edit("visibility")
        labels = [str(getattr(c, "label", "")) for c in undo._undo_stack]
        assert len(undo._undo_stack) == 2 and "Set visibility" in labels[0]
        assert not stage.GetPrimAtPath("/World/Leaf").IsValid()
        undo.undo()
        assert stage.GetPrimAtPath("/World/Leaf").GetAttribute(
            "visibility").Get() == "invisible"
        undo.undo()
        assert not stage.GetPrimAtPath("/World/Leaf").GetAttribute(
            "visibility").HasAuthoredValueOpinion()
        undo.redo()
        undo.redo()
        assert not stage.GetPrimAtPath("/World/Leaf").IsValid()

    def test_delete_group_never_absorbs_settled_property_edit(self):
        from pxr import Sdf

        from ovui_data_adapters.common import Command
        from ovui_data_adapters.openusd.commands import DeletePrimCommand

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Other")
        UsdGeom.Cube.Define(stage, "/World/Leaf")
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/Other"], undo_manager=undo)

        class _SelectionDuringDelete(Command):
            def do(self):
                pass

            def undo(self):
                pass

        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        undo.begin_group("Delete")
        undo.push(_SelectionDuringDelete())
        undo.push(DeletePrimCommand(stage, Sdf.Path("/World/Leaf")))
        undo.end_group()
        adapter.end_edit("visibility")

        assert len(undo._undo_stack) == 2
        assert "Set visibility" in str(undo._undo_stack[0].label)
        assert str(undo._undo_stack[1].label) == "Delete"
        undo.undo()
        assert stage.GetPrimAtPath("/World/Leaf").IsValid()
        other = stage.GetPrimAtPath(
            "/World/Other").GetAttribute("visibility")
        assert other.Get() == "invisible"
        assert other.HasAuthoredValueOpinion()
        undo.undo()
        assert other.Get() == "inherited"
        assert not other.HasAuthoredValueOpinion()

    def test_reparent_group_never_absorbs_settled_property_edit(self):
        from pxr import Sdf

        from ovui_data_adapters.openusd.commands import NamespaceEditCommand

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Other")
        UsdGeom.Xform.Define(stage, "/World/Group")
        UsdGeom.Cube.Define(stage, "/World/Leaf")
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/Other"], undo_manager=undo)
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        undo.begin_group("Reparent")
        undo.push(NamespaceEditCommand(
            stage.GetRootLayer(),
            Sdf.Path("/World/Leaf"),
            Sdf.Path("/World/Group/Leaf"),
        ))
        undo.end_group()
        adapter.end_edit("visibility")

        assert len(undo._undo_stack) == 2
        undo.undo()
        assert stage.GetPrimAtPath("/World/Leaf").IsValid()
        assert not stage.GetPrimAtPath("/World/Group/Leaf").IsValid()
        other = stage.GetPrimAtPath(
            "/World/Other").GetAttribute("visibility")
        assert other.Get() == "invisible"
        undo.undo()
        assert other.Get() == "inherited"
        assert not other.HasAuthoredValueOpinion()

    def test_dead_pre_namespace_settlers_are_pruned_without_namespace_work(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Leaf")
        undo = UndoManager()
        for _ in range(500):
            adapter = UsdPropertyAdapter(
                stage, ["/World/Leaf"], undo_manager=undo)
            del adapter
        gc.collect()
        assert undo._pre_namespace_settlers == []

    def test_cancel_after_out_of_band_delete_never_resurrects(self):
        from pxr import Sdf

        stage, undo, adapter, _attr = _fixture()
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        # NON-undoable out-of-band deletion (no command, no settle).
        batch = Sdf.BatchNamespaceEdit()
        batch.Add(Sdf.Path("/World/Leaf"), Sdf.Path.emptyPath)
        stage.GetRootLayer().Apply(batch)
        adapter.cancel_edit("visibility")
        assert stage.GetRootLayer().GetPrimAtPath("/World/Leaf") is None
        assert len(undo._undo_stack) == 0

    def test_cross_adapter_overlap_refused_before_mutation(self):
        stage, undo, a1, attr = _fixture()
        a2 = UsdPropertyAdapter(stage, ["/World/Leaf"], undo_manager=undo)
        a1.begin_edit("visibility")
        a1.set_value("visibility", "invisible")
        with pytest.raises(RuntimeError, match="overlapping edit refused"):
            a2.begin_edit("visibility")
        a1.end_edit("visibility")
        assert len(undo._undo_stack) == 1
        undo.undo()
        assert not attr.HasAuthoredValueOpinion()
        # Released claim: the second adapter retries cleanly.
        a2.begin_edit("visibility")
        a2.set_value("visibility", "invisible")
        a2.end_edit("visibility")
        assert len(undo._undo_stack) == 1
        assert attr.Get() == "invisible"

    def test_different_property_and_path_edits_do_not_overlap(self):
        stage, undo, a1, _attr = _fixture()
        UsdGeom.Cube.Define(stage, "/World/Other")
        a2 = UsdPropertyAdapter(stage, ["/World/Other"], undo_manager=undo)
        a3 = UsdPropertyAdapter(stage, ["/World/Leaf"], undo_manager=undo)
        a1.begin_edit("visibility")
        a2.begin_edit("visibility")   # different path: independent
        a3.begin_edit("size")         # different property: independent
        a1.cancel_edit("visibility")
        a2.cancel_edit("visibility")
        a3.cancel_edit("size")
        assert len(undo._undo_stack) == 0

    def test_discarded_adapter_releases_its_claim(self):
        import gc

        stage, undo, a1, _attr = _fixture()
        a1.begin_edit("visibility")
        del a1
        gc.collect()
        # The dead token releases the claim: a new adapter may edit.
        a2 = UsdPropertyAdapter(stage, ["/World/Leaf"], undo_manager=undo)
        a2.begin_edit("visibility")
        a2.cancel_edit("visibility")


class TestEmptyTargetVariantClosure:
    """Round-27: a direct-variant edit into an initially EMPTY target must
    round-trip exactly — variant-set spec, owner list-op, created
    ancestors, and the property — through repeated undo/redo, without
    owning unrelated same-layer content."""

    @staticmethod
    def _variant_stage(nested=False):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        prim = UsdGeom.Cube.Define(stage, "/World/Leaf").GetPrim()
        vs = prim.GetVariantSets().AddVariantSet("look")
        vs.AddVariant("A")
        vs.SetVariantSelection("A")
        if nested:
            with vs.GetVariantEditContext():
                inner = prim.GetVariantSets().AddVariantSet("deep")
                inner.AddVariant("D")
                inner.SetVariantSelection("D")
            return stage, prim, prim.GetVariantSets().GetVariantSet("deep")
        return stage, prim, vs

    def _round_trip(self, stage, prim, target_vs, target_layer):
        empty_text = target_layer.ExportToString()
        stage.SetEditTarget(target_vs.GetVariantEditTarget(target_layer))
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/Leaf"], undo_manager=undo)
        _edit(adapter, "invisible")
        assert len(undo._undo_stack) == 1
        assert prim.GetAttribute("visibility").Get() == "invisible"
        post_text = target_layer.ExportToString()
        for _ in range(3):
            undo.undo()
            assert target_layer.ExportToString() == empty_text
            assert prim.GetAttribute("visibility").Get() == "inherited"
            undo.redo()
            assert target_layer.ExportToString() == post_text
            assert prim.GetAttribute("visibility").Get() == "invisible"
        undo.undo()
        assert target_layer.ExportToString() == empty_text

    def test_empty_session_target_round_trips_exactly(self):
        stage, prim, vs = self._variant_stage()
        self._round_trip(stage, prim, vs, stage.GetSessionLayer())

    def test_empty_target_nested_variant_round_trips_exactly(self):
        stage, prim, inner = self._variant_stage(nested=True)
        self._round_trip(stage, prim, inner, stage.GetSessionLayer())

    def test_empty_file_backed_target_round_trips_exactly(self, tmp_path):
        from pxr import Sdf

        stage, prim, vs = self._variant_stage()
        layer = Sdf.Layer.CreateNew(str(tmp_path / "target.usda"))
        stage.GetRootLayer().subLayerPaths.append(layer.identifier)
        self._round_trip(stage, prim, vs, layer)

    def test_closure_never_owns_foreign_same_owner_content(self):
        from pxr import Sdf

        stage, prim, vs = self._variant_stage()
        session = stage.GetSessionLayer()
        stage.SetEditTarget(vs.GetVariantEditTarget(session))
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/Leaf"], undo_manager=undo)
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        # FOREIGN content: an unrelated prim AND a foreign variant set on
        # the SAME owner prim spec, added mid-edit.
        foreign = Sdf.CreatePrimInLayer(session, "/Foreign")
        foreign.customData = {"owner": "someone-else"}
        owner = session.GetPrimAtPath("/World/Leaf")
        fset = Sdf.VariantSetSpec(owner, "foreignSet")
        Sdf.VariantSpec(fset, "X")
        owner.variantSetNameList.appendedItems.append("foreignSet")
        adapter.end_edit("visibility")
        undo.undo()
        owner = session.GetPrimAtPath("/World/Leaf")
        assert session.GetPrimAtPath("/Foreign") is not None
        assert "foreignSet" in dict(owner.variantSets)
        assert "look" not in dict(owner.variantSets)
        assert "look" not in list(owner.variantSetNameList.prependedItems)
        assert "foreignSet" in list(owner.variantSetNameList.appendedItems)
        undo.redo()
        owner = session.GetPrimAtPath("/World/Leaf")
        assert "foreignSet" in dict(owner.variantSets)
        assert session.GetAttributeAtPath(
            "/World/Leaf{look=A}.visibility") is not None

    def test_existing_scaffold_variant_still_round_trips(self):
        stage, prim, vs = self._variant_stage()
        # Scaffold pre-exists in the ROOT layer (the ordinary case).
        stage.SetEditTarget(vs.GetVariantEditTarget())
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/Leaf"], undo_manager=undo)
        root_text = stage.GetRootLayer().ExportToString()
        _edit(adapter, "invisible")
        undo.undo()
        assert stage.GetRootLayer().ExportToString() == root_text
        undo.redo()
        assert prim.GetAttribute("visibility").Get() == "invisible"


class TestForeignContentInsideOwnedVariant:
    """Round-28: undo of an empty-target variant edit must NEVER destroy
    foreign content authored inside the command-created variant. The
    closure removal is gated on spec inertness; a foreign-carrying
    variant survives (with its set and list-op membership, staying
    composable) while the owned visibility property is still undone."""

    @staticmethod
    def _empty_variant_edit(nested=False, target="session"):
        from pxr import Sdf

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        prim = UsdGeom.Cube.Define(stage, "/World/Leaf").GetPrim()
        vs = prim.GetVariantSets().AddVariantSet("look")
        vs.AddVariant("A")
        vs.SetVariantSelection("A")
        target_vs = vs
        if nested:
            with vs.GetVariantEditContext():
                inner = prim.GetVariantSets().AddVariantSet("deep")
                inner.AddVariant("D")
                inner.SetVariantSelection("D")
            target_vs = prim.GetVariantSets().GetVariantSet("deep")
        layer = stage.GetSessionLayer()
        stage.SetEditTarget(target_vs.GetVariantEditTarget(layer))
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/Leaf"], undo_manager=undo)
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        return stage, prim, layer, undo, adapter

    def test_reviewer_scenario_foreign_float_preserved(self):
        from pxr import Sdf

        stage, prim, layer, undo, adapter = self._empty_variant_edit()
        prim.CreateAttribute(
            "foreignValue", Sdf.ValueTypeNames.Float, custom=True).Set(7.25)
        adapter.end_edit("visibility")
        assert undo.undo() is True
        foreign = layer.GetAttributeAtPath(
            "/World/Leaf{look=A}.foreignValue")
        assert foreign is not None and foreign.default == 7.25
        assert layer.GetAttributeAtPath(
            "/World/Leaf{look=A}.visibility") is None
        assert prim.GetAttribute("visibility").Get() == "inherited"
        # Foreign work stays COMPOSABLE (set + list-op survive with it).
        assert prim.GetAttribute("foreignValue").Get() == 7.25
        assert len(undo._undo_stack) == 0 and len(undo._redo_stack) == 1
        undo.redo()
        assert prim.GetAttribute("visibility").Get() == "invisible"
        assert prim.GetAttribute("foreignValue").Get() == 7.25
        undo.undo()
        assert prim.GetAttribute("foreignValue").Get() == 7.25
        assert prim.GetAttribute("visibility").Get() == "inherited"

    def test_foreign_metadata_time_samples_children_relationships(self):
        from pxr import Sdf

        stage, prim, layer, undo, adapter = self._empty_variant_edit()
        attr = prim.CreateAttribute(
            "foreignAnim", Sdf.ValueTypeNames.Float, custom=True)
        attr.Set(1.0, time=Usd.TimeCode(1.0))
        attr.Set(2.0, time=Usd.TimeCode(2.0))
        attr.SetMetadata("documentation", "foreign-docs")
        rel = prim.CreateRelationship("foreignRel", custom=True)
        rel.SetTargets([Sdf.Path("/World")])
        stage.DefinePrim("/World/Leaf/ForeignChild", "Scope")
        adapter.end_edit("visibility")
        assert undo.undo() is True
        spec = layer.GetAttributeAtPath("/World/Leaf{look=A}.foreignAnim")
        assert spec is not None
        assert dict(spec.GetInfo("timeSamples")) == {1.0: 1.0, 2.0: 2.0}
        assert spec.GetInfo("documentation") == "foreign-docs"
        assert layer.GetRelationshipAtPath(
            "/World/Leaf{look=A}.foreignRel") is not None
        assert layer.GetPrimAtPath(
            "/World/Leaf{look=A}ForeignChild") is not None
        assert layer.GetAttributeAtPath(
            "/World/Leaf{look=A}.visibility") is None
        assert prim.GetAttribute("visibility").Get() == "inherited"

    def test_foreign_added_between_completion_and_undo(self):
        from pxr import Sdf

        stage, prim, layer, undo, adapter = self._empty_variant_edit()
        adapter.end_edit("visibility")
        # Foreign content lands AFTER the command completed.
        prim.CreateAttribute(
            "lateForeign", Sdf.ValueTypeNames.Float, custom=True).Set(3.5)
        assert undo.undo() is True
        assert layer.GetAttributeAtPath(
            "/World/Leaf{look=A}.lateForeign") is not None
        assert prim.GetAttribute("lateForeign").Get() == 3.5
        assert prim.GetAttribute("visibility").Get() == "inherited"

    def test_nested_variant_foreign_content_preserved(self):
        from pxr import Sdf

        stage, prim, layer, undo, adapter = self._empty_variant_edit(
            nested=True)
        prim.CreateAttribute(
            "foreignNested", Sdf.ValueTypeNames.Float, custom=True).Set(9.0)
        adapter.end_edit("visibility")
        assert undo.undo() is True
        assert prim.GetAttribute("foreignNested").Get() == 9.0
        assert prim.GetAttribute("visibility").Get() == "inherited"

    def test_file_backed_target_foreign_content_preserved(self, tmp_path):
        from pxr import Sdf

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        prim = UsdGeom.Cube.Define(stage, "/World/Leaf").GetPrim()
        vs = prim.GetVariantSets().AddVariantSet("look")
        vs.AddVariant("A")
        vs.SetVariantSelection("A")
        layer = Sdf.Layer.CreateNew(str(tmp_path / "target.usda"))
        stage.GetRootLayer().subLayerPaths.append(layer.identifier)
        stage.SetEditTarget(vs.GetVariantEditTarget(layer))
        undo = UndoManager()
        adapter = UsdPropertyAdapter(
            stage, ["/World/Leaf"], undo_manager=undo)
        adapter.begin_edit("visibility")
        adapter.set_value("visibility", "invisible")
        prim.CreateAttribute(
            "foreignFile", Sdf.ValueTypeNames.Float, custom=True).Set(4.5)
        adapter.end_edit("visibility")
        assert undo.undo() is True
        assert layer.GetAttributeAtPath(
            "/World/Leaf{look=A}.foreignFile") is not None
        assert prim.GetAttribute("visibility").Get() == "inherited"
