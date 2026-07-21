# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Notice-derived visibility events and exact transactional undo/redo.

Covers the Stage Browser visibility synchronization contract: adapter event
paths derive exclusively from genuine ``Usd.Notice.ObjectsChanged`` payloads
(fan-out included), undo/redo restore the edit-target layer field-wise, a
no-op edge emits nothing, and grouped multi-edits merge into one event while
grouped undo emits truthful per-command events.
"""

from __future__ import annotations

import pytest

pxr = pytest.importorskip("pxr")
from pxr import Sdf, Usd, UsdGeom  # noqa: E402

from ovui_data_adapters.common import ChangeEventType, VisibilityState  # noqa: E402
from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter  # noqa: E402
from ovui_data_adapters.services.undo import UndoManager  # noqa: E402


def _make_stage():
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/World", "Xform")
    for name, kind in (("Cube", "Cube"), ("Sphere", "Sphere"), ("Pyramid", "Mesh")):
        stage.DefinePrim(f"/World/{name}", kind)
    stage.DefinePrim("/World/Group", "Xform")
    stage.DefinePrim("/World/Group/GC", "Cube")
    stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
    return stage


def _fixture():
    stage = _make_stage()
    undo = UndoManager()
    adapter = UsdStageAdapter(stage, undo_manager=undo)
    events: list = []
    sub = adapter.subscribe_changes(events.append)  # noqa: F841 — keep alive
    return stage, undo, adapter, events, sub


def _toggle(adapter, stage, path, visible):
    adapter.begin_undo_group("Toggle Visibility")
    adapter.set_visibility(stage.GetPrimAtPath(path), visible)
    adapter.end_undo_group()


class TestNoticeDerivedEvents:
    def test_leaf_hide_emits_property_path_and_delta(self):
        stage, _undo, adapter, events, _s = _fixture()
        _toggle(adapter, stage, "/World/Pyramid", False)
        assert len(events) == 1
        event = events[0]
        assert event.event_type is ChangeEventType.INFO_CHANGE
        # The verbatim genuine ledger also carries the eager session-layer
        # over-chain creation entries as bare changed-info survivors.
        assert "/World/Pyramid.visibility" in event.changed_paths
        assert all(
            path in ("/World", "/World/Pyramid", "/World/Pyramid.visibility")
            for path in event.changed_paths
        )
        assert event.resynced_paths == ()
        delta = event.visibility_delta
        assert delta["authored"] == ("/World/Pyramid",)
        old, new = delta["boundaries"]["/World/Pyramid"]
        assert old is VisibilityState.VISIBLE
        assert new is VisibilityState.INVISIBLE

    def test_fanout_event_names_every_touched_prim(self):
        stage, _undo, adapter, events, _s = _fixture()
        _toggle(adapter, stage, "/World", False)
        events.clear()
        _toggle(adapter, stage, "/World/Group", True)
        assert len(events) == 1
        authored = set(events[0].visibility_delta["authored"])
        # MakeVisible flipped /World and authored 'invisible' on the
        # imageable non-chain siblings; the clicked prim itself was
        # untouched and must not be fabricated into the roots.
        assert authored == {"/World", "/World/Cube", "/World/Sphere", "/World/Pyramid"}
        assert "/World/Group" not in authored
        # Boundary records exist for evaluated prims (metadata only).
        bounds = events[0].visibility_delta["boundaries"]
        old, new = bounds["/World/Cube"]
        assert old is VisibilityState.INHERITED_INVISIBLE
        assert new is VisibilityState.INVISIBLE

    def test_true_noop_emits_nothing(self):
        stage, _undo, adapter, events, _s = _fixture()
        _toggle(adapter, stage, "/World/Cube", False)  # authors the spec
        events.clear()
        _toggle(adapter, stage, "/World/Cube", False)  # value-gated, spec exists
        assert events == []

    def test_eager_makeinvisible_spec_creation_is_not_a_noop(self):
        stage, _undo, adapter, events, _s = _fixture()
        # invisible value supplied by the ROOT layer; session target empty.
        stage.SetEditTarget(Usd.EditTarget(stage.GetRootLayer()))
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Cube")).MakeInvisible()
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        session_before = stage.GetSessionLayer().ExportToString()
        events.clear()
        _toggle(adapter, stage, "/World/Cube", False)
        # CreateVisibilityAttr created a session spec: genuine notices fired.
        assert len(events) == 1
        assert "/World/Cube.visibility" in events[0].changed_paths
        # Exact undo restores true spec absence in the session layer.
        adapter._undo_manager.undo()
        assert stage.GetSessionLayer().ExportToString() == session_before

    def test_multi_selection_batch_merges_into_one_event(self):
        stage, undo, adapter, events, _s = _fixture()
        adapter.begin_undo_group("Toggle Visibility")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        adapter.set_visibility(stage.GetPrimAtPath("/World/Sphere"), False)
        adapter.end_undo_group()
        assert len(events) == 1
        assert {
            "/World/Cube.visibility",
            "/World/Sphere.visibility",
        } <= set(events[0].changed_paths)
        events.clear()
        undo.undo()
        # Grouped undo bypasses the batch: truthful per-command events.
        assert len(events) == 2
        assert all(e.visibility_delta is not None for e in events)


class TestExactTransactionalUndo:
    def test_fanout_undo_and_redo_restore_layer_fieldwise(self):
        stage, undo, adapter, events, _s = _fixture()
        baseline = stage.GetSessionLayer().ExportToString()
        _toggle(adapter, stage, "/World", False)
        _toggle(adapter, stage, "/World/Group", True)
        undo.undo()
        undo.undo()
        assert stage.GetSessionLayer().ExportToString() == baseline
        undo.redo()
        undo.redo()
        # Redo restores exact post-do state: /World inherited, siblings
        # authored invisible, Group untouched.
        layer = stage.GetSessionLayer()
        assert layer.GetPropertyAtPath("/World.visibility").default == "inherited"
        for name in ("Cube", "Sphere", "Pyramid"):
            assert (
                layer.GetPropertyAtPath(f"/World/{name}.visibility").default
                == "invisible"
            )
        assert layer.GetPropertyAtPath("/World/Group.visibility") is None
        undo.undo()
        undo.undo()
        assert stage.GetSessionLayer().ExportToString() == baseline

    def test_undo_emits_notice_derived_event(self):
        stage, undo, adapter, events, _s = _fixture()
        _toggle(adapter, stage, "/World", False)
        _toggle(adapter, stage, "/World/Group", True)
        events.clear()
        undo.undo()
        assert len(events) == 1
        assert set(events[0].visibility_delta["authored"]) == {
            "/World", "/World/Cube", "/World/Sphere", "/World/Pyramid",
        }

    def test_direct_variant_edit_target_uses_whole_layer_mode(self):
        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        vsets = world.GetVariantSets().AddVariantSet("model")
        vsets.AddVariant("A")
        vsets.SetVariantSelection("A")
        with vsets.GetVariantEditContext():
            stage.DefinePrim("/World/P", "Mesh")
        session = stage.GetSessionLayer()
        target = Usd.EditTarget.ForLocalDirectVariant(
            session, Sdf.Path("/World{model=A}")
        )
        stage.SetEditTarget(target)
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        baseline = session.ExportToString()
        adapter.set_visibility(stage.GetPrimAtPath("/World/P"), False)
        # Spec landed at the mapped variant path, not the scene path.
        assert session.GetPropertyAtPath("/World{model=A}P.visibility") is not None
        assert session.GetPropertyAtPath("/World/P.visibility") is None
        undo.undo()
        # Whole-layer restore: field-identical, including the created
        # VariantSetSpec/VariantSpec/list-op state being fully removed.
        assert session.ExportToString() == baseline

    def test_external_first_time_edit_classified_as_info_change(self):
        stage, _undo, adapter, events, _s = _fixture()
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Sphere")).MakeInvisible()
        assert events, "external edit must notify"
        for event in events:
            assert event.event_type is ChangeEventType.INFO_CHANGE
            assert event.resynced_paths == ()
        assert any(
            "/World/Sphere.visibility" in e.changed_paths for e in events
        )


class TestModeBReplayRoots:
    def _variant_fixture(self):
        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        vsets = world.GetVariantSets().AddVariantSet("model")
        vsets.AddVariant("A")
        vsets.SetVariantSelection("A")
        with vsets.GetVariantEditContext():
            stage.DefinePrim("/World/P", "Mesh")
        stage.SetEditTarget(
            Usd.EditTarget.ForLocalDirectVariant(
                stage.GetSessionLayer(), Sdf.Path("/World{model=A}")
            )
        )
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        return stage, undo, adapter, events, sub

    def test_direct_variant_undo_redo_emit_notice_derived_events(self):
        stage, undo, adapter, events, _s = self._variant_fixture()
        adapter.set_visibility(stage.GetPrimAtPath("/World/P"), False)
        assert len(events) == 1  # do
        events.clear()
        undo.undo()
        # Whole-layer replay resynced /World: that genuine root must be
        # retained and emitted, never dropped.
        assert len(events) == 1
        assert events[0].visibility_delta is not None
        assert "/World" in events[0].visibility_delta["authored"]
        events.clear()
        undo.redo()
        assert len(events) == 1
        assert "/World" in events[0].visibility_delta["authored"]


class TestScopeLifecycle:
    def test_member_failure_aborts_and_compensates_scope(self):
        stage, undo, adapter, events, _s = _fixture()
        baseline = stage.GetSessionLayer().ExportToString()
        with pytest.raises(RuntimeError, match="member B failed"):
            adapter.begin_undo_group("Toggle Visibility")
            try:
                adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
                raise RuntimeError("member B failed")
            except BaseException:
                adapter.abort_undo_group()
                raise
        assert stage.GetSessionLayer().ExportToString() == baseline
        assert events == []          # verified scope compensation: no event
        assert undo.can_undo() is False
        assert adapter._undo_group_depth == 0
        assert adapter._visibility_scope is None

    def test_adapter_visible_member_failure_poisons_scope(self):
        stage, undo, adapter, events, _s = _fixture()
        baseline = stage.GetSessionLayer().ExportToString()
        pseudo_root = stage.GetPseudoRoot()
        with pytest.raises(ValueError):
            adapter.begin_undo_group("Toggle Visibility")
            try:
                adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
                adapter.set_visibility(pseudo_root, False)  # not editable
            except BaseException:
                adapter.abort_undo_group()
                raise
        assert stage.GetSessionLayer().ExportToString() == baseline
        assert events == []
        assert undo.can_undo() is False

    def test_close_subscriber_failure_finalizes_and_delivers_to_rest(self):
        stage, _undo, adapter, events, _s = _fixture()

        def bad_subscriber(_event):
            raise RuntimeError("subscriber boom")

        bad = adapter.subscribe_changes(bad_subscriber)  # noqa: F841
        received: list = []
        good = adapter.subscribe_changes(received.append)  # noqa: F841
        with pytest.raises(RuntimeError):
            _toggle(adapter, stage, "/World/Cube", False)
        # Later subscribers still received the frozen event; adapter state
        # finalized (dead scope, depth zero).
        assert len(received) == 1
        assert adapter._undo_group_depth == 0
        assert adapter._visibility_scope is None

    def test_assembly_failure_flushes_conservative_paths_only_event(self):
        stage, _undo, adapter, events, _s = _fixture()
        original = adapter._attempt_event

        def boom(_attempt):
            raise RuntimeError("assembly boom")

        adapter._attempt_event = boom
        try:
            with pytest.raises(RuntimeError):
                adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            adapter._attempt_event = original
        # The surviving edit was reported through the conservative fallback.
        assert len(events) == 1
        assert "/World/Cube.visibility" in events[0].changed_paths
        assert events[0].visibility_delta["boundaries"] == {}


class TestModeACleanupSafety:
    def test_non_inert_created_spec_survives_undo(self):
        stage, undo, adapter, _events, _s = _fixture()
        _toggle(adapter, stage, "/World/Cube", False)
        spec = stage.GetSessionLayer().GetPrimAtPath("/World/Cube")
        spec.customData = {"mustSurvive": 7}
        undo.undo()   # completes; never deletes the non-inert spec
        after = stage.GetSessionLayer().GetPrimAtPath("/World/Cube")
        assert after is not None
        assert dict(after.customData).get("mustSurvive") == 7
        # The visibility opinion itself was exactly restored (spec absent).
        assert stage.GetSessionLayer().GetPropertyAtPath(
            "/World/Cube.visibility") is None


class TestScopeCloseFailures:
    """Second-review S3/S4: close/verification failures must not lose effects."""

    def test_merge_assembly_failure_flushes_conservative_event(self):
        stage, _undo, adapter, events, _s = _fixture()
        adapter.begin_undo_group("g")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        adapter.set_visibility(stage.GetPrimAtPath("/World/Sphere"), False)
        original = adapter._merged_scope_event
        adapter._merged_scope_event = lambda records: (_ for _ in ()).throw(
            RuntimeError("merge boom")
        )
        try:
            with pytest.raises(RuntimeError, match="merge boom"):
                adapter.end_undo_group()
        finally:
            adapter._merged_scope_event = original
        # Both authored edits survive and were reported conservatively (the
        # raw segments may add genuine bare resync roots on top).
        assert len(events) == 1
        assert {
            "/World/Cube.visibility", "/World/Sphere.visibility",
        } <= set(events[0].changed_paths)
        assert events[0].visibility_delta["precise"] is False
        assert adapter._undo_group_depth == 0
        assert adapter._visibility_scope is None

    def test_verification_failure_becomes_uncertain_conservative_flush(self):
        stage, _undo, adapter, events, _s = _fixture()
        adapter.begin_undo_group("g")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        adapter._visibility_scope["failed"] = True
        key = next(iter(adapter._visibility_scope["baselines"]))
        _layer, text = adapter._visibility_scope["baselines"][key]

        class BadVerify:
            def ExportToString(self):
                raise RuntimeError("verify boom")

            def ImportFromString(self, _text):
                raise RuntimeError("verify boom")

        adapter._visibility_scope["baselines"][key] = (BadVerify(), text)
        with pytest.raises(RuntimeError):
            adapter.end_undo_group()
        # Equality could not be proved: disposition is uncertain and the
        # retained genuine segments flushed as one conservative event.
        assert len(events) == 1
        assert "/World/Cube.visibility" in events[0].changed_paths
        assert events[0].visibility_delta["precise"] is False
        assert adapter._visibility_scope is None

    def test_begin_group_failure_leaks_no_scope_or_depth(self):
        class BeginFailUndo(UndoManager):
            def begin_group(self, label):
                raise RuntimeError("begin failed")

        stage = _make_stage()
        adapter = UsdStageAdapter(stage, undo_manager=BeginFailUndo())
        with pytest.raises(RuntimeError, match="begin failed"):
            adapter.begin_undo_group("x")
        assert adapter._undo_group_depth == 0
        assert adapter._visibility_scope is None

    def test_abort_keeps_original_error_primary_over_cancel_failure(self):
        stage, undo, adapter, events, _s = _fixture()
        baseline = stage.GetSessionLayer().ExportToString()
        adapter.begin_undo_group("g")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)

        def cancel_boom():
            raise RuntimeError("cancel failed")

        undo.cancel_group = cancel_boom
        with pytest.raises(ValueError, match="member original"):
            try:
                raise ValueError("member original")
            except BaseException:
                adapter.abort_undo_group()
                raise
        # The baseline replay compensated what cancel_group could not, so
        # suppression was proven and no event is owed.
        assert stage.GetSessionLayer().ExportToString() == baseline
        assert events == []
        assert adapter._visibility_scope is None

    def test_baseline_replay_compensates_unrecorded_member_effect(self):
        stage, _undo, adapter, events, _s = _fixture()
        baseline = stage.GetSessionLayer().ExportToString()
        adapter.begin_undo_group("g")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        # Simulate a partially-failed member: it authored during command
        # execution (in-mutation) but was never recorded in the manager, so
        # cancel_group cannot compensate this opinion — only the scope's
        # replayable baseline can.
        adapter._in_mutation = True
        try:
            UsdGeom.Imageable(
                stage.GetPrimAtPath("/World/Sphere")
            ).MakeInvisible()
        finally:
            adapter._in_mutation = False
        adapter.abort_undo_group()
        assert stage.GetSessionLayer().ExportToString() == baseline
        assert events == []  # equality re-proven after replay: suppressed

    def test_late_end_after_finalization_is_dead(self):
        stage, undo, adapter, _events, _s = _fixture()
        adapter.begin_undo_group("g")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        adapter.end_undo_group()
        stack_before = list(undo._undo_stack)
        adapter.end_undo_group()   # dead token: must not touch the manager
        adapter.abort_undo_group()
        assert undo._undo_stack == stack_before


class TestOutcomeNoOps:
    """Second-review S5: genuine outcome no-ops never enter undo history."""

    def test_repeat_invisible_adds_no_history_and_no_event(self):
        stage, undo, adapter, events, _s = _fixture()
        _toggle(adapter, stage, "/World/Cube", False)
        events.clear()
        depth_before = len(undo._undo_stack)
        _toggle(adapter, stage, "/World/Cube", False)   # outcome no-op
        assert len(undo._undo_stack) == depth_before
        assert events == []
        # The next undo consumes the REAL edit, not a no-op shell.
        assert undo.undo()
        attr = UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Cube")
        ).GetVisibilityAttr()
        assert not attr.HasAuthoredValue()

    def test_noop_preserves_redo_history(self):
        stage, undo, adapter, events, _s = _fixture()
        _toggle(adapter, stage, "/World/Cube", False)
        undo.undo()
        assert undo.can_redo()
        events.clear()
        # Already visible: MakeVisible on a visible prim with no authored
        # opinions changes nothing.
        _toggle(adapter, stage, "/World/Cube", True)
        assert undo.can_redo(), "a genuine no-op must not clear redo history"
        assert len(undo._undo_stack) == 0
        assert events == []

    def test_grouped_noops_leave_no_group_entry(self):
        stage, undo, adapter, events, _s = _fixture()
        _toggle(adapter, stage, "/World/Cube", False)
        events.clear()
        depth_before = len(undo._undo_stack)
        adapter.begin_undo_group("Toggle Visibility")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        adapter.end_undo_group()
        assert len(undo._undo_stack) == depth_before
        assert events == []


class TestAdapterDisposal:
    """Second-review S4: disposal finalizes and delivers before detach."""

    def test_dispose_flushes_open_scope_to_old_subscribers(self):
        stage, _undo, adapter, events, _s = _fixture()
        adapter.begin_undo_group("g")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        completed = adapter.dispose()
        # Round-6 contract: an open scope WITHOUT an in-flight attempt is
        # finalized IMMEDIATELY and boundedly (a never-closing owner can
        # never leak the manager group to a later adapter): one truthful
        # conservative disposition to the old subscribers, then teardown.
        assert completed is True
        assert adapter.disposal_pending is False
        assert len(events) == 1
        assert "/World/Cube.visibility" in events[0].changed_paths
        assert adapter._visibility_scope is None
        assert adapter._undo_group_depth == 0
        assert adapter._subscribers == []
        # The late owner close is a dead-token no-op: no split disposition.
        adapter.end_undo_group()
        assert len(events) == 1

    def test_dispose_detaches_notice_listeners_and_is_idempotent(self):
        stage, _undo, adapter, events, _s = _fixture()
        adapter.dispose()
        adapter.dispose()
        events.clear()
        # Post-dispose external edits reach no one: listener revoked and
        # subscribers dropped.
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Cube")).MakeInvisible()
        assert events == []

    def test_late_group_calls_after_dispose_are_dead(self):
        stage, undo, adapter, _events, _s = _fixture()
        adapter.begin_undo_group("g")
        adapter.dispose()
        adapter.end_undo_group()    # dead token: no manager interaction
        adapter.abort_undo_group()


class _RecordingRenderer:
    def __init__(self):
        self.writes = []

    def write_attribute(self, paths, name, values):
        self.writes.append((tuple(paths), name, tuple(values)))


class TestRendererCoarseRootFanOut:
    """Second-review S1: bare genuine roots reach renderer descendants."""

    def _renderer_for(self, stage):
        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
        )

        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._renderer = _RecordingRenderer()
        renderer._selected_paths = []
        return renderer

    def _variant_event_after_redo(self):
        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        vset = world.GetVariantSets().AddVariantSet("m")
        vset.AddVariant("A")
        vset.SetVariantSelection("A")
        with vset.GetVariantEditContext():
            stage.DefinePrim("/World/P", "Mesh")
        stage.SetEditTarget(
            Usd.EditTarget.ForLocalDirectVariant(
                stage.GetSessionLayer(), Sdf.Path("/World{m=A}")
            )
        )
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.set_visibility(stage.GetPrimAtPath("/World/P"), False)
        events.clear()
        undo.undo()
        events.clear()
        undo.redo()
        return stage, events[-1]

    def test_mode_b_replay_root_syncs_descendant_tokens(self):
        stage, event = self._variant_event_after_redo()
        renderer = self._renderer_for(stage)
        renderer.notify_stage_changed(event)
        writes = {p[0]: v[0] for p, _n, v in renderer._renderer.writes}
        # The bare /World root conservatively re-pushed the descendant's
        # own LOCAL opinion: P is explicitly invisible after redo.
        assert writes.get("/World/P") == "invisible"

    def test_property_roots_stay_per_prim(self):
        stage, _undo, adapter, events, _s = _fixture()
        _toggle(adapter, stage, "/World/Cube", False)
        renderer = self._renderer_for(stage)
        renderer.notify_stage_changed(events[-1])
        written = {p[0] for p, _n, _v in renderer._renderer.writes}
        assert "/World/Cube" in written
        # A precise property-path event does not fan out to the whole tree.
        assert "/World/Group/GC" not in written


class TestPredictionSupportGate:
    def test_unsupported_runtime_takes_whole_layer_mode(self, monkeypatch):
        from ovui_data_adapters.openusd import commands as commands_mod

        assert commands_mod.prediction_runtime_supported() is True
        monkeypatch.setattr(commands_mod, "_PREDICTION_SUPPORTED", False)
        stage, undo, adapter, _events, _s = _fixture()
        baseline = stage.GetSessionLayer().ExportToString()
        _toggle(adapter, stage, "/World/Cube", False)
        command = undo._undo_stack[-1]._commands[0]
        assert command._mode == "B"   # frozen decision: unsupported -> Mode B
        undo.undo()
        assert stage.GetSessionLayer().ExportToString() == baseline


class TestSharedManagerGroupOwnership:
    """Third-review B1: no UndoManager group may outlive its adapter scope."""

    def test_dispose_closes_manager_group_and_next_edit_is_undoable(self):
        stage, undo, adapter, events, _s = _fixture()
        adapter.begin_undo_group("g")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        adapter.dispose()   # deferred: the scope owner still closes it
        adapter.end_undo_group()
        assert undo.open_group_depth == 0
        # The user's grouped edit was committed as one undoable entry.
        assert undo.can_undo()
        assert len(undo._undo_stack) == 1
        # A NEXT adapter's edit must be independently undoable — never
        # silently appended to an abandoned accumulator.
        adapter2 = UsdStageAdapter(stage, undo_manager=undo)
        received: list = []
        sub2 = adapter2.subscribe_changes(received.append)  # noqa: F841
        adapter2.set_visibility(stage.GetPrimAtPath("/World/Sphere"), False)
        assert len(undo._undo_stack) == 2
        assert len(received) == 1
        assert undo.undo()   # undoes ONLY the new edit
        attr = UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/Sphere")
        ).GetVisibilityAttr()
        assert not attr.HasAuthoredValue()

    def test_end_group_failure_never_leaks_manager_group(self):
        stage, undo, adapter, events, _s = _fixture()
        adapter.begin_undo_group("g")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        undo.end_group = lambda: (_ for _ in ()).throw(RuntimeError("end boom"))
        with pytest.raises(RuntimeError, match="end boom"):
            adapter.end_undo_group()
        assert undo.open_group_depth == 0
        assert len(events) == 1  # surviving member edit still reported
        del undo.end_group       # restore the real method
        adapter.set_visibility(stage.GetPrimAtPath("/World/Sphere"), False)
        assert undo.can_undo()   # next edit independently undoable

    def test_cancel_group_failure_never_leaks_manager_group(self):
        stage, undo, adapter, events, _s = _fixture()
        baseline = stage.GetSessionLayer().ExportToString()
        adapter.begin_undo_group("g")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        adapter._visibility_scope["failed"] = True
        undo.cancel_group = lambda: (_ for _ in ()).throw(
            RuntimeError("cancel boom"))
        with pytest.raises(RuntimeError):
            adapter.end_undo_group()
        # Baseline replay compensated; equality proven; no event owed.
        assert stage.GetSessionLayer().ExportToString() == baseline
        assert undo.open_group_depth == 0
        del undo.cancel_group
        adapter.set_visibility(stage.GetPrimAtPath("/World/Sphere"), False)
        assert undo.can_undo()

    def test_manager_clear_drops_open_group_accumulators(self):
        undo = UndoManager()
        undo.begin_group("stale")
        undo.clear()
        assert undo.open_group_depth == 0


class TestBaseExceptionSafety:
    """Third-review B2: attempts finalize on EVERY exit path."""

    def test_keyboard_interrupt_after_write_finalizes_attempt(self):
        stage, undo, adapter, events, _s = _fixture()

        def interrupting_push(cmd):
            UsdGeom.Imageable(
                stage.GetPrimAtPath("/World/Cube")
            ).MakeInvisible()
            raise KeyboardInterrupt("interrupt after write")

        adapter._push = interrupting_push
        with pytest.raises(KeyboardInterrupt):
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        del adapter._push
        # The attempt reached a disposition: token dead, surviving genuine
        # write reported conservatively.
        assert adapter._visibility_attempts == []
        assert len(events) == 1
        assert "/World/Cube.visibility" in events[0].changed_paths
        assert events[0].visibility_delta["precise"] is False
        # A later INDEPENDENT edit is never swallowed by a dead attempt.
        events.clear()
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Sphere")).MakeInvisible()
        assert events, "independent external edit must emit its own event"
        assert any(
            "/World/Sphere" in str(p)
            for e in events
            for p in e.changed_paths + e.resynced_paths
        )

    def test_keyboard_interrupt_on_undo_edge_finalizes_attempt(self):
        stage, undo, adapter, events, _s = _fixture()

        class FakeCommand:
            def predicted_write_prims(self):
                return {"/World/Cube"}

        def edge():
            UsdGeom.Imageable(
                stage.GetPrimAtPath("/World/Cube")
            ).MakeInvisible()
            raise KeyboardInterrupt("interrupt mid-edge")

        with pytest.raises(KeyboardInterrupt):
            adapter.run_visibility_command_edge(FakeCommand(), edge)
        assert adapter._visibility_attempts == []
        assert len(events) == 1
        assert "/World/Cube.visibility" in events[0].changed_paths


class TestLosslessLedger:
    """Third-review B3: no genuine surviving path is dropped or reclassified."""

    def test_reentrant_survivor_reaches_consumers_with_segments(self):
        stage, undo, adapter, events, _s = _fixture()
        from pxr import Tf

        state = {"done": False}

        def reentrant(notice, sender):
            if state["done"]:
                return
            paths = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if any(str(p).endswith(".visibility") for p in paths):
                state["done"] = True
                stage.GetPrimAtPath("/World/Sphere").SetCustomDataByKey(
                    "reentrant", 7)

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        try:
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            key.Revoke()
        assert len(events) == 1
        event = events[0]
        # The surviving re-entrant metadata mutation is NOT dropped.
        assert "/World/Sphere" in event.changed_paths
        # The visibility annotation never absorbs the non-visibility path.
        assert "/World/Sphere" not in event.visibility_delta["authored"]
        # The ordered raw segments ride along for audit.
        segments = event.visibility_delta["segments"]
        assert any("/World/Sphere" in seg_changed
                   for _res, seg_changed in segments)

    def test_mode_b_replay_roots_are_truthfully_resynced(self):
        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        vset = world.GetVariantSets().AddVariantSet("m")
        vset.AddVariant("A")
        vset.SetVariantSelection("A")
        with vset.GetVariantEditContext():
            stage.DefinePrim("/World/P", "Mesh")
        stage.SetEditTarget(
            Usd.EditTarget.ForLocalDirectVariant(
                stage.GetSessionLayer(), Sdf.Path("/World{m=A}")
            )
        )
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.set_visibility(stage.GetPrimAtPath("/World/P"), False)
        events.clear()
        undo.undo()
        assert len(events) == 1
        event = events[0]
        # The genuine bare replay root keeps its RESYNC classification.
        assert "/World" in event.resynced_paths
        assert event.event_type is ChangeEventType.RESYNC
        assert "/World" in event.visibility_delta["authored"]
        assert event.visibility_delta["segments"]


class TestBaseExceptionCompensationAndDelivery:
    """Round-4 R1/R2: BaseException-safe compensation, assembly, delivery."""

    def test_compensation_interrupt_never_displaces_the_original_error(self):
        from ovui_data_adapters.openusd.commands import SetVisibilityCommand

        stage, _undo, adapter, events, _s = _fixture()

        class BadCompensation:
            def replay(self, layer):
                raise KeyboardInterrupt("compensation interrupt")

            def matches(self, layer):
                return False

        original = SetVisibilityCommand._capture

        def capture(self):
            count = getattr(self, "_probe_captures", 0)
            self._probe_captures = count + 1
            if count == 0:
                return BadCompensation()
            raise RuntimeError("post capture original")

        SetVisibilityCommand._capture = capture
        try:
            with pytest.raises(RuntimeError, match="post capture original") as info:
                adapter.set_visibility(
                    stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            SetVisibilityCommand._capture = original
        notes = getattr(info.value, "__notes__", []) or []
        assert any("KeyboardInterrupt" in n for n in notes)
        # Unproved surviving effect: the conservative genuine-notice event
        # reached consumers before the token died.
        assert len(events) == 1
        assert events[0].visibility_delta["precise"] is False
        assert adapter._visibility_attempts == []

    def test_interrupting_subscriber_never_starves_later_consumers(self):
        stage, _undo, adapter, _events, _s = _fixture()

        def interrupting(_event):
            raise KeyboardInterrupt("subscriber interrupt")

        later: list = []
        sub1 = adapter.subscribe_changes(interrupting)  # noqa: F841
        sub2 = adapter.subscribe_changes(later.append)  # noqa: F841
        with pytest.raises(KeyboardInterrupt):
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        assert len(later) == 1, "later subscriber must still be delivered"
        assert adapter._visibility_attempts == []

    def test_systemexit_assembly_still_delivers_raw_ledger_fallback(self):
        stage, _undo, adapter, events, _s = _fixture()
        original = adapter._attempt_event
        adapter._attempt_event = lambda attempt: (_ for _ in ()).throw(
            SystemExit("assembly exit"))
        try:
            with pytest.raises(SystemExit):
                adapter.set_visibility(
                    stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            adapter._attempt_event = original
        assert len(events) == 1
        assert "/World/Cube.visibility" in events[0].changed_paths
        assert adapter._visibility_attempts == []

    def test_cancel_interrupt_still_replays_baseline_and_closes(self):
        stage, undo, adapter, events, _s = _fixture()
        baseline = stage.GetSessionLayer().ExportToString()
        adapter.begin_undo_group("g")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        adapter._visibility_scope["failed"] = True
        undo.cancel_group = lambda: (_ for _ in ()).throw(
            KeyboardInterrupt("cancel interrupt"))
        with pytest.raises(KeyboardInterrupt):
            adapter.end_undo_group()
        del undo.cancel_group
        # Baseline replay compensated the member; suppression was proven,
        # the manager group did not leak, the token is dead.
        assert stage.GetSessionLayer().ExportToString() == baseline
        assert events == []
        assert undo.open_group_depth == 0
        assert adapter._visibility_scope is None
        # Subsequent independent edit behaves normally.
        adapter.set_visibility(stage.GetPrimAtPath("/World/Sphere"), False)
        assert undo.can_undo()
        assert len(events) == 1


class TestDisposalDuringActiveAttempt:
    """Round-4 R3: disposal resolves active attempts before detaching."""

    def test_reentrant_dispose_delivers_the_attempts_genuine_segments(self):
        stage, _undo, adapter, events, _s = _fixture()

        def author_then_dispose(cmd):
            UsdGeom.Imageable(
                stage.GetPrimAtPath("/World/Cube")).MakeInvisible()
            adapter.dispose()

        adapter._push = author_then_dispose
        try:
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            del adapter._push
        # The genuine notice captured by the active attempt was delivered
        # to the still-subscribed consumers BEFORE detachment. Round-5
        # deferral lets the attempt complete normally, so the event is the
        # ordinary truthful one (not a lossy conservative substitute).
        assert len(events) == 1
        assert "/World/Cube.visibility" in events[0].changed_paths
        assert events[0].visibility_delta is not None
        # Late completion did not revive/redeliver; tokens are dead.
        assert adapter._visibility_attempts == []
        assert adapter._subscribers == []
        adapter.dispose()   # idempotent
        assert len(events) == 1

    def test_next_adapter_after_reentrant_dispose_is_healthy(self):
        stage, undo, adapter, events, _s = _fixture()
        adapter._push = lambda cmd: adapter.dispose()
        try:
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            del adapter._push
        adapter2 = UsdStageAdapter(stage, undo_manager=undo)
        received: list = []
        sub = adapter2.subscribe_changes(received.append)  # noqa: F841
        adapter2.set_visibility(stage.GetPrimAtPath("/World/Sphere"), False)
        assert len(received) == 1
        assert undo.can_undo()


class TestStructuralResyncSemantics:
    """Round-4 R4: unrelated structural resyncs keep topology semantics."""

    def _reentrant_define_event(self):
        from pxr import Tf

        stage, _undo, adapter, events, sub = _fixture()
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if not fired["done"] and any(
                str(p) == "/World/Cube.visibility" for p in paths
            ):
                fired["done"] = True
                stage.DefinePrim("/World/Sphere/NewChild", "Cube")

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        try:
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            key.Revoke()
        return stage, events[-1]

    def test_unrelated_structural_resync_is_not_visibility_authored(self):
        stage, event = self._reentrant_define_event()
        # Lossless: the structural root survives with RESYNC classification.
        assert "/World/Sphere/NewChild" in event.resynced_paths
        # Truthful: it is NOT annotated as a visibility-authored root.
        authored = set(event.visibility_delta["authored"])
        assert "/World/Sphere/NewChild" not in authored
        assert "/World/Cube" in authored

    def test_renderer_takes_structural_sync_for_unrelated_resync(self):
        from pxr import Sdf as SdfMod

        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage, event = self._reentrant_define_event()
        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        decision = renderer._stage_change_sync_decision(
            event, event.changed_paths, event.resynced_paths, SdfMod)
        assert decision != _STAGE_CHANGE_SYNC_LIVE

    def test_mode_b_replay_root_still_annotated_and_live(self):
        from pxr import Sdf as SdfMod

        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        vset = world.GetVariantSets().AddVariantSet("m")
        vset.AddVariant("A")
        vset.SetVariantSelection("A")
        with vset.GetVariantEditContext():
            stage.DefinePrim("/World/P", "Mesh")
        stage.SetEditTarget(
            Usd.EditTarget.ForLocalDirectVariant(
                stage.GetSessionLayer(), Sdf.Path("/World{m=A}")))
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.set_visibility(stage.GetPrimAtPath("/World/P"), False)
        events.clear()
        undo.undo()
        event = events[-1]
        # A CLEAN replay (no surrounding edits) is PROVEN visibility-only
        # by the full-consequence layer proof, so the genuine resync stays
        # annotated and the renderer stays live. A replay whose actual
        # consequence includes anything else is structural — see
        # TestCoarseReplayConsequences.
        assert "/World" in event.resynced_paths
        assert "/World" in event.visibility_delta["authored"]
        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        decision = renderer._stage_change_sync_decision(
            event, event.changed_paths, event.resynced_paths, SdfMod)
        assert decision == _STAGE_CHANGE_SYNC_LIVE


class TestInSubtreeStructuralResync:
    """Round-5 P1: ambiguity INSIDE the predicted subtree stays structural."""

    def _reentrant_in_subtree_event(self):
        from pxr import Tf

        stage, _undo, adapter, events, sub = _fixture()
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if not fired["done"] and any(
                str(p) == "/World/Cube.visibility" for p in paths
            ):
                fired["done"] = True
                stage.DefinePrim("/World/Cube/NewChild", "Cube")

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        try:
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            key.Revoke()
        return stage, events[-1]

    def test_in_subtree_new_prim_is_not_visibility_authored(self):
        stage, event = self._reentrant_in_subtree_event()
        assert "/World/Cube/NewChild" in event.resynced_paths
        authored = set(event.visibility_delta["authored"])
        # Path overlap with the predicted target proves NOTHING: the new
        # prim under the edited target keeps structural semantics.
        assert "/World/Cube/NewChild" not in authored
        assert "/World/Cube" in authored  # its own genuine property change

    def test_renderer_takes_structural_path_for_in_subtree_resync(self):
        from pxr import Sdf as SdfMod

        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage, event = self._reentrant_in_subtree_event()
        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        decision = renderer._stage_change_sync_decision(
            event, event.changed_paths, event.resynced_paths, SdfMod)
        assert decision != _STAGE_CHANGE_SYNC_LIVE


class TestFallbackOfFallback:
    """Round-5 P2: the final raw fallback cannot throw or displace."""

    def test_fallback_assembly_interrupt_keeps_primary_and_delivers(self):
        stage, _undo, adapter, events, _s = _fixture()

        def author_then_fail(cmd):
            UsdGeom.Imageable(
                stage.GetPrimAtPath("/World/Cube")).MakeInvisible()
            raise RuntimeError("primary operation")

        adapter._push = author_then_fail
        adapter._attempt_fallback_event = lambda attempt: (
            (_ for _ in ()).throw(KeyboardInterrupt("fallback assembly")))
        try:
            with pytest.raises(RuntimeError, match="primary operation") as info:
                adapter.set_visibility(
                    stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            del adapter._push
            del adapter._attempt_fallback_event
        notes = getattr(info.value, "__notes__", []) or []
        assert any("KeyboardInterrupt" in n for n in notes)
        # The nonthrowing raw event still delivered the surviving root.
        assert len(events) == 1
        assert any(
            "/World/Cube" in str(p)
            for p in events[0].changed_paths + events[0].resynced_paths
        )
        assert adapter._visibility_attempts == []

    def test_assembly_systemexit_stays_primary_over_subscriber_failure(self):
        stage, _undo, adapter, _events, _s = _fixture()
        later: list = []

        def bad_subscriber(_event):
            raise RuntimeError("subscriber boom")

        sub1 = adapter.subscribe_changes(bad_subscriber)  # noqa: F841
        sub2 = adapter.subscribe_changes(later.append)    # noqa: F841
        adapter._attempt_event = lambda attempt: (
            (_ for _ in ()).throw(SystemExit("semantic assembly primary")))
        try:
            with pytest.raises(SystemExit, match="semantic assembly primary") as info:
                adapter.set_visibility(
                    stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            del adapter._attempt_event
        # Later subscriber still received the fallback; the subscriber
        # failure attached to the PRIMARY SystemExit instead of displacing.
        assert len(later) == 1
        notes = getattr(info.value, "__notes__", []) or []
        assert any("subscriber" in n for n in notes)


class TestDisposalDuringOuterScope:
    """Round-5 P3: one outer disposition under real TfNotice ordering."""

    def _run(self, register_external_first):
        from pxr import Tf

        stage = _make_stage()
        undo = UndoManager()
        holder: dict = {}
        events: list = []
        fired = {"done": False}

        def dispose_cb(notice, sender):
            paths = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if not fired["done"] and any(
                str(p) == "/World/Sphere.visibility" for p in paths
            ):
                fired["done"] = True
                holder["adapter"].dispose()

        key = None
        if register_external_first:
            key = Tf.Notice.Register(
                Usd.Notice.ObjectsChanged, dispose_cb, stage)
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        holder["adapter"] = adapter
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        if not register_external_first:
            key = Tf.Notice.Register(
                Usd.Notice.ObjectsChanged, dispose_cb, stage)
        adapter.begin_undo_group("outer")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        adapter.set_visibility(stage.GetPrimAtPath("/World/Sphere"), False)
        adapter.end_undo_group()
        key.Revoke()
        return stage, undo, adapter, events

    @pytest.mark.parametrize("external_first", (False, True))
    def test_dispose_during_member_keeps_one_disposition(self, external_first):
        stage, undo, adapter, events = self._run(external_first)
        # ONE merged event containing BOTH members, regardless of the
        # TfNotice callback ordering of the disposal trigger.
        assert len(events) == 1
        assert {
            "/World/Cube.visibility", "/World/Sphere.visibility",
        } <= set(events[0].changed_paths)
        # ONE history entry: the outer group; no split member entry.
        assert [type(x).__name__ for x in undo._undo_stack] == ["UndoGroup"]
        assert undo.open_group_depth == 0
        # Both member states genuinely applied; teardown completed after.
        for name in ("Cube", "Sphere"):
            attr = UsdGeom.Imageable(
                stage.GetPrimAtPath(f"/World/{name}")).GetVisibilityAttr()
            assert attr.Get() == UsdGeom.Tokens.invisible
        assert adapter._subscribers == []
        assert adapter._visibility_attempts == []

    def test_orphaned_attempt_defers_teardown_as_unresolved(self):
        stage, _undo, adapter, events, _s = _fixture()
        attempt = adapter._begin_visibility_attempt(("/World/Cube",))
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Cube")).MakeInvisible()
        adapter.dispose()
        # Explicit unresolved ownership: nothing lost, nothing detached.
        assert adapter._subscribers, "subscribers survive deferral"
        assert adapter._visibility_attempts == [attempt]
        assert events == []
        # The owner resolving the attempt completes the deferred teardown
        # with the truthful delivery.
        adapter._commit_visibility_attempt(attempt)
        assert len(events) == 1
        assert adapter._subscribers == []


class TestAmbiguousResyncMutations:
    """Round-6 Q1: unchanged shape never proves visibility semantics."""

    def _mutated_event(self, mutation):
        from pxr import Tf

        stage, _undo, adapter, events, sub = _fixture()
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if not fired["done"] and any(
                str(p) == "/World/Cube.visibility" for p in paths
            ):
                fired["done"] = True
                if mutation == "retype":
                    stage.OverridePrim("/World/Cube").SetTypeName("Sphere")
                elif mutation == "deactivate":
                    stage.OverridePrim("/World/Cube").SetActive(False)
                else:
                    stage.RemovePrim("/World/Cube")
                    stage.DefinePrim("/World/Cube", "Sphere")

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        try:
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            key.Revoke()
        return stage, events[-1]

    @pytest.mark.parametrize("mutation", ("retype", "deactivate", "recreate"))
    def test_mutation_resync_keeps_structural_semantics(self, mutation):
        from pxr import Sdf as SdfMod

        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage, event = self._mutated_event(mutation)
        assert "/World/Cube" in event.resynced_paths
        # The genuine structural resync is NEVER annotated as a visibility
        # replay consequence (operation-window + identity fingerprint).
        annotated = set(event.visibility_delta.get("operation_resyncs") or ())
        assert "/World/Cube" not in annotated
        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        decision = renderer._stage_change_sync_decision(
            event, event.changed_paths, event.resynced_paths, SdfMod)
        assert decision != _STAGE_CHANGE_SYNC_LIVE

    def test_mode_b_variant_do_and_replay_stay_annotated(self):
        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        vset = world.GetVariantSets().AddVariantSet("m")
        vset.AddVariant("A")
        vset.SetVariantSelection("A")
        with vset.GetVariantEditContext():
            stage.DefinePrim("/World/P", "Mesh")
        stage.SetEditTarget(
            Usd.EditTarget.ForLocalDirectVariant(
                stage.GetSessionLayer(), Sdf.Path("/World{m=A}")))
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.set_visibility(stage.GetPrimAtPath("/World/P"), False)
        do_delta = events[-1].visibility_delta
        assert "/World" in (do_delta.get("operation_resyncs") or ())
        events.clear()
        undo.undo()
        undo_delta = events[-1].visibility_delta
        assert "/World" in (undo_delta.get("operation_resyncs") or ())


class TestCoarseReplayConsequences:
    """Round-7: coarse/ambiguous resyncs keep structural semantics unless
    the operation's FULL actual consequence is proven visibility-only."""

    def _variant_stage(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        cube = UsdGeom.Cube.Define(stage, "/World/Cube")
        prim = cube.GetPrim()
        vset = prim.GetVariantSets().AddVariantSet("shape")
        for name, size in (("A", 1.0), ("B", 5.0)):
            vset.AddVariant(name)
            vset.SetVariantSelection(name)
            with vset.GetVariantEditContext():
                UsdGeom.Cube(prim).CreateSizeAttr(size)
        vset.SetVariantSelection("A")
        return stage, prim, vset

    def _renderer_probe(self, stage):
        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
        )

        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        calls: dict = {"writes": [], "structural": [], "transforms": []}

        class _Spy:
            def write_attribute(self, *args, **kw):
                calls["writes"].append(args)

        renderer._renderer = _Spy()
        renderer._sync_ovrtx_root_snapshot_overlay_from_stage = (
            lambda: calls["structural"].append("overlay")
        )
        renderer._reload_live_root_snapshot = (
            lambda: calls["structural"].append("reload")
        )
        renderer._write_prim_transform_to_ovrtx = (
            lambda prim, path: calls["transforms"].append(path) or True
        )
        return renderer, calls

    def test_reentrant_variant_switch_routes_structurally(self):
        # The reviewer's counterexample: a re-entrant variant switch during
        # the real visibility notice changes composed size while preserving
        # type/active/specifier/children. The genuine /World/Cube resync
        # must NOT be annotated; the actual renderer must take the
        # structural path (so the changed size reaches OVRTX).
        from pxr import Tf

        stage, prim, vset = self._variant_stage()
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if not fired["done"] and any(
                str(p) == "/World/Cube.visibility" for p in paths
            ):
                fired["done"] = True
                vset.SetVariantSelection("B")

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        try:
            adapter.set_visibility(prim, False)
        finally:
            key.Revoke()
        event = events[-1]
        assert "/World/Cube" in event.resynced_paths
        annotated = set(
            event.visibility_delta.get("operation_resyncs") or ())
        assert "/World/Cube" not in annotated
        renderer, calls = self._renderer_probe(stage)
        renderer.notify_stage_changed(event)
        # Structural synchronization ran — OVRTX is rebuilt from the live
        # composed stage (which holds the NEW size), not just visibility.
        assert calls["structural"]
        adapter.dispose()

    def test_whole_layer_replay_removing_descendant_edit_is_structural(self):
        # The reviewer's second counterexample: a Mode B whole-layer undo
        # whose replay ALSO removes a later surrounding descendant edit
        # (translate) — the genuine /World resync is NOT visibility-only
        # and every consumer must treat it structurally.
        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        vset = world.GetVariantSets().AddVariantSet("m")
        vset.AddVariant("A")
        vset.SetVariantSelection("A")
        with vset.GetVariantEditContext():
            stage.DefinePrim("/World/P", "Mesh")
        stage.SetEditTarget(
            Usd.EditTarget.ForLocalDirectVariant(
                stage.GetSessionLayer(), Sdf.Path("/World{m=A}")))
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        prim = stage.GetPrimAtPath("/World/P")
        adapter.set_visibility(prim, False)
        # Later surrounding edit in the SAME target: the whole-layer undo
        # replay will remove it.
        UsdGeom.Xformable(prim).AddTranslateOp().Set((10, 0, 0))
        events.clear()
        undo.undo()
        event = events[-1]
        assert UsdGeom.Xformable(prim).GetOrderedXformOps() == []
        annotated = set(
            (event.visibility_delta or {}).get("operation_resyncs") or ())
        assert "/World" not in annotated
        renderer, calls = self._renderer_probe(stage)
        renderer.notify_stage_changed(event)
        assert calls["structural"]  # descendant transform removal reaches it
        # The CLEAN redo (restoring exactly the visibility snapshot) is
        # proven visibility-only again.
        events.clear()
        undo.redo()
        redo_delta = events[-1].visibility_delta
        assert "/World" in (redo_delta.get("operation_resyncs") or ())
        adapter.dispose()

    @pytest.mark.parametrize("mutation", ("reference", "payload"))
    def test_reentrant_composition_arc_routes_structurally(self, mutation):
        # References/payloads added during the window preserve children
        # names on an empty target — composition must still veto.
        from pxr import Tf

        stage, _undo, adapter, events, sub = _fixture()
        other = Sdf.Layer.CreateAnonymous(".usda")
        other.ImportFromString("#usda 1.0\ndef Xform \"Ref\" {\n}\n")
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if not fired["done"] and any(
                str(p) == "/World/Cube.visibility" for p in paths
            ):
                fired["done"] = True
                prim = stage.GetPrimAtPath("/World/Cube")
                if mutation == "reference":
                    prim.GetReferences().AddReference(
                        other.identifier, "/Ref")
                else:
                    prim.GetPayloads().AddPayload(other.identifier, "/Ref")

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        try:
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            key.Revoke()
        event = events[-1]
        annotated = set(
            (event.visibility_delta or {}).get("operation_resyncs") or ())
        assert "/World/Cube" not in annotated
        adapter.dispose()

    def test_reentrant_edit_to_other_stage_layer_vetoes_annotation(self):
        # A re-entrant edit landing in a DIFFERENT stage layer (session,
        # while the operation targets the root layer) cannot be proven by
        # the target-layer baseline — the changed-layer veto keeps the
        # windowed bare resync structural.
        from pxr import Tf

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Group/Cube")
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if not fired["done"] and any(
                "/World/Group" in str(p) for p in paths
            ):
                fired["done"] = True
                # Session-layer structural opinion on a SIBLING (authored
                # via Sdf so the stage's edit target is untouched): the
                # bare /World/Other resync lands inside the operation
                # window but in a layer the operation never baselined.
                spec = Sdf.CreatePrimInLayer(
                    stage.GetSessionLayer(), "/World/Other")
                spec.specifier = Sdf.SpecifierDef
                spec.typeName = "Sphere"

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        try:
            adapter.set_visibility(
                stage.GetPrimAtPath("/World/Group/Cube"), False)
        finally:
            key.Revoke()
        event = events[-1]
        assert "/World/Other" in event.resynced_paths
        annotated = set(
            (event.visibility_delta or {}).get("operation_resyncs") or ())
        # The changed-layer veto refuses annotation for EVERY windowed bare
        # resync of this attempt — the proof cannot cover the session edit.
        assert not annotated
        adapter.dispose()


class TestSurvivingForeignSpecExactness:
    """Round-8 G1: a surviving foreign spec never proves exact/net-zero."""

    def test_in_attempt_failure_with_survivor_flushes_conservatively(self):
        from pxr import Tf

        from ovui_data_adapters.openusd.commands import SetVisibilityCommand

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/Cube", "Cube")
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        fired = {"done": False}

        def reentrant(notice, sender):
            ps = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if not fired["done"] and any(
                str(p) == "/World/Cube.visibility" for p in ps
            ):
                fired["done"] = True
                spec = Sdf.CreatePrimInLayer(
                    stage.GetSessionLayer(), "/World/Cube")
                spec.customData = {"survivor": 7}

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        original_capture = SetVisibilityCommand._capture

        def failing_second_capture(self):
            count = getattr(self, "_test_captures", 0)
            self._test_captures = count + 1
            if count == 0:
                return original_capture(self)
            raise RuntimeError("post capture failure")

        SetVisibilityCommand._capture = failing_second_capture
        try:
            with pytest.raises(RuntimeError, match="post capture failure") as info:
                adapter.set_visibility(
                    stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            SetVisibilityCommand._capture = original_capture
            key.Revoke()
        # The foreign opinion is PRESERVED but exactness fails: the
        # retained genuine segments flush conservatively, never suppressed.
        assert getattr(info.value, "_ovui_visibility_net_zero", None) is False
        layer = stage.GetSessionLayer()
        assert dict(layer.GetPrimAtPath("/World/Cube").customData) == {
            "survivor": 7}
        assert len(events) == 1
        assert "/World/Cube" in set(
            events[0].changed_paths + events[0].resynced_paths)
        # History correctness: the failed push recorded nothing.
        assert adapter._undo_manager._undo_stack == []
        notes = getattr(info.value, "__notes__", []) or []
        assert any("NOT field-exact" in n for n in notes)
        adapter.dispose()

    def test_noop_claim_fails_with_survivor(self):
        # A genuine outcome no-op claim also requires STRICT identity.
        from ovui_data_adapters.openusd.commands import (
            _TargetedVisibilitySnapshot,
        )

        layer = Sdf.Layer.CreateAnonymous(".usda")
        layer.ImportFromString("#usda 1.0\ndef Xform \"World\" {\n}\n")
        snap = _TargetedVisibilitySnapshot(layer, ["/World/New"])
        spec = Sdf.CreatePrimInLayer(layer, "/World/New")
        spec.customData = {"foreign": 1}
        assert snap.matches(layer) is True        # replay contract tolerant
        assert snap.matches_exactly(layer) is False  # exactness never


class TestDeferredTeardownPrimaryPreservation:
    """Round-8 G3: deferred disposal never displaces the active primary."""

    def test_primary_survives_disposal_delivery_baseexception(self):
        from pxr import Tf

        from ovui_data_adapters.openusd.commands import SetVisibilityCommand

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/A", "Cube")
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        good: list = []
        bad = adapter.subscribe_changes(  # noqa: F841
            lambda e: (_ for _ in ()).throw(SystemExit("delivery secondary")))
        ok = adapter.subscribe_changes(good.append)  # noqa: F841
        requested: list = []

        def ext(notice, sender):
            ps = tuple(notice.GetResyncedPaths()) + tuple(
                notice.GetChangedInfoOnlyPaths())
            if not requested and any(
                str(p) == "/World/A.visibility" for p in ps
            ):
                requested.append(adapter.dispose(force=True))

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, ext, stage)

        class BadSnapshot:
            def replay(self, layer):
                raise KeyboardInterrupt("comp secondary")

            def matches(self, layer):
                return False

        original_capture = SetVisibilityCommand._capture

        def capture(self):
            count = getattr(self, "_test_captures", 0)
            self._test_captures = count + 1
            if count == 0:
                return BadSnapshot()
            raise RuntimeError("PRIMARY")

        SetVisibilityCommand._capture = capture
        adapter.begin_undo_group("g")
        try:
            with pytest.raises(RuntimeError, match="PRIMARY") as info:
                adapter.set_visibility(stage.GetPrimAtPath("/World/A"), False)
        finally:
            SetVisibilityCommand._capture = original_capture
            key.Revoke()
        notes = getattr(info.value, "__notes__", []) or []
        assert any("comp secondary" in n for n in notes)
        assert any("delivery secondary" in n for n in notes)
        # Teardown completed and every subscriber was attempted.
        assert requested == [False]
        assert len(good) == 1
        assert adapter.disposal_pending is False
        assert adapter._notice_key is None
        assert adapter._subscribers == []
        assert undo.open_group_depth == 0

    def test_dead_group_token_close_is_noop(self):
        # Round-8 G2 support: a close after the accumulators were wiped is
        # a dead token — no IndexError, no command escapes.
        manager = UndoManager()
        manager.begin_group("g")
        manager.clear()
        manager.end_group()   # must not raise
        assert manager.open_group_depth == 0
        assert manager._undo_stack == []


class TestNonDefaultVisibilityConsequences:
    """Round-8 G5: only the command-owned default token may normalize away."""

    @pytest.mark.parametrize("kind", ("customData", "documentation",
                                      "timeSample", "connection"))
    def test_non_default_field_removal_routes_structurally(self, kind):
        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        world = stage.DefinePrim("/World", "Xform")
        vset = world.GetVariantSets().AddVariantSet("m")
        vset.AddVariant("A")
        vset.SetVariantSelection("A")
        with vset.GetVariantEditContext():
            stage.DefinePrim("/World/P", "Mesh")
        stage.SetEditTarget(
            Usd.EditTarget.ForLocalDirectVariant(
                stage.GetSessionLayer(), Sdf.Path("/World{m=A}")))
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.set_visibility(stage.GetPrimAtPath("/World/P"), False)
        attr = UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/P")).GetVisibilityAttr()
        if kind == "customData":
            attr.SetCustomDataByKey("survivor", 7)
        elif kind == "documentation":
            attr.SetDocumentation("survivor-doc")
        elif kind == "timeSample":
            attr.Set("invisible", 3.0)
        else:
            attr.AddConnection(Sdf.Path("/World.xformOpOrder"))
        events.clear()
        undo.undo()   # whole-layer replay REMOVES the later opinion
        event = events[-1]
        annotated = set(
            (event.visibility_delta or {}).get("operation_resyncs") or ())
        assert "/World" not in annotated
        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        decision = renderer._stage_change_sync_decision(
            event, event.changed_paths, event.resynced_paths, Sdf)
        assert decision != _STAGE_CHANGE_SYNC_LIVE
        # The clean redo (command-owned default only) stays proven.
        events.clear()
        undo.redo()
        redo_delta = events[-1].visibility_delta
        assert "/World" in (redo_delta.get("operation_resyncs") or ())
        adapter.dispose()


class TestDisposalCompletionContract:
    """Round-6 Q2: explicit completion; bounded never-closing recovery."""

    def test_never_closing_owner_cannot_capture_next_adapter(self):
        stage, undo, adapter, events, _s = _fixture()
        adapter.begin_undo_group("old-unclosed")
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        completed = adapter.dispose()
        # No in-flight attempt: bounded IMMEDIATE finalization.
        assert completed is True
        assert adapter.disposal_pending is False
        assert undo.open_group_depth == 0
        assert len(events) == 1     # one conservative outer disposition
        adapter2 = UsdStageAdapter(stage, undo_manager=undo)
        received: list = []
        sub2 = adapter2.subscribe_changes(received.append)  # noqa: F841
        adapter2.set_visibility(stage.GetPrimAtPath("/World/Sphere"), False)
        # Independent entry — never joins the abandoned group.
        assert [type(x).__name__ for x in undo._undo_stack] == [
            "UndoGroup", "SetVisibilityCommand"]
        assert undo._group_stack == []
        adapter.end_undo_group()   # late owner close: dead no-op
        assert [type(x).__name__ for x in undo._undo_stack] == [
            "UndoGroup", "SetVisibilityCommand"]

    def test_deferred_dispose_reports_pending_and_delivery_failure_completes(self):
        stage, _undo, adapter, events, _s = _fixture()

        def failing_subscriber(_event):
            raise RuntimeError("delivery fails")

        bad = adapter.subscribe_changes(failing_subscriber)  # noqa: F841
        attempt = adapter._begin_visibility_attempt(("/World/Cube",))
        completed = adapter.dispose()
        assert completed is False          # explicit: ownership unresolved
        assert adapter.disposal_pending is True
        UsdGeom.Imageable(stage.GetPrimAtPath("/World/Cube")).MakeInvisible()
        with pytest.raises(RuntimeError):
            adapter._commit_visibility_attempt(attempt)
        # A failing delivery still drove deferred finalization to done.
        assert adapter.disposal_pending is False
        assert adapter._subscribers == []
        assert adapter._notice_key is None
        assert len(events) == 1            # survivor was delivered

    @pytest.mark.parametrize("register_external_first", (True, False))
    def test_forced_dispose_during_real_authoring_notice_defers(
        self, register_external_first
    ):
        # Round-7: replacement/forced disposal requested by ANOTHER
        # Tf.Notice callback DURING a real visibility authoring notice —
        # under both callback registration orders — must NOT detach before
        # the adapter receives the same synchronous notice and the
        # command/history bookkeeping completes. The deferred completion
        # then delivers ONE truthful disposition to the old subscribers
        # and detaches with no listener/group/subscriber/history leak.
        from pxr import Tf

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/A", "Cube")
        stage.DefinePrim("/World/B", "Cube")
        undo = UndoManager()
        results: list = []
        holder: dict = {}

        def external(notice, sender):
            paths = tuple(str(p) for p in notice.GetResyncedPaths()) + tuple(
                str(p) for p in notice.GetChangedInfoOnlyPaths()
            )
            if "adapter" in holder and "/World/A.visibility" in paths and (
                not results
            ):
                adapter = holder["adapter"]
                results.append(("normal", adapter.dispose(),
                                adapter.disposal_pending,
                                undo.open_group_depth))
                results.append(("forced", adapter.dispose(force=True),
                                adapter.disposal_pending,
                                undo.open_group_depth))

        if register_external_first:
            key = Tf.Notice.Register(
                Usd.Notice.ObjectsChanged, external, stage)
            adapter = UsdStageAdapter(stage, undo_manager=undo)
        else:
            adapter = UsdStageAdapter(stage, undo_manager=undo)
            key = Tf.Notice.Register(
                Usd.Notice.ObjectsChanged, external, stage)
        holder["adapter"] = adapter
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.begin_undo_group("old")
        try:
            adapter.set_visibility(stage.GetPrimAtPath("/World/A"), False)
        finally:
            key.Revoke()
        # Both requests deferred: nothing detached mid-notice.
        assert results == [
            ("normal", False, True, 1),
            ("forced", False, True, 1),
        ]
        # Completion ran when the authoring call exited: one truthful
        # disposition with the genuine roots reached the OLD subscribers.
        assert len(events) == 1
        assert "/World/A" in set(
            events[0].visibility_delta["authored"])
        assert adapter.disposal_pending is False
        assert adapter._subscribers == []
        assert adapter._notice_key is None
        assert undo.open_group_depth == 0
        # The surviving command was committed INSIDE its owner's group —
        # never appended bare after a forced closure.
        assert [type(x).__name__ for x in undo._undo_stack] == ["UndoGroup"]
        # A later owner close is a dead no-op.
        adapter.end_undo_group()
        assert [type(x).__name__ for x in undo._undo_stack] == ["UndoGroup"]
        # The next adapter is fully independent and undo restores both.
        adapter2 = UsdStageAdapter(stage, undo_manager=undo)
        received: list = []
        sub2 = adapter2.subscribe_changes(received.append)  # noqa: F841
        adapter2.set_visibility(stage.GetPrimAtPath("/World/B"), False)
        assert [type(x).__name__ for x in undo._undo_stack] == [
            "UndoGroup", "SetVisibilityCommand"]
        assert len(received) == 1
        assert undo.undo() and undo.undo()
        assert not UsdGeom.Imageable(
            stage.GetPrimAtPath("/World/A")).GetVisibilityAttr(
        ).HasAuthoredValue()
        adapter2.dispose()

    def test_forced_dispose_defers_on_exceptional_delivery_exit(self):
        # Round-7: the deferred FORCED completion must also run on the
        # exceptional delivery exit of the in-flight attempt and still
        # produce the single truthful disposition before detaching.
        from pxr import Tf

        stage, undo, adapter, events, _s = _fixture()

        def failing_subscriber(_event):
            raise RuntimeError("delivery fails")

        bad = adapter.subscribe_changes(failing_subscriber)  # noqa: F841
        requested: list = []

        def external(notice, sender):
            paths = tuple(str(p) for p in notice.GetResyncedPaths()) + tuple(
                str(p) for p in notice.GetChangedInfoOnlyPaths()
            )
            if "/World/Cube.visibility" in paths and not requested:
                requested.append(adapter.dispose(force=True))

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, external, stage)
        try:
            with pytest.raises(RuntimeError, match="delivery fails"):
                adapter.set_visibility(
                    stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            key.Revoke()
        assert requested == [False]
        # The delivery failure still drove the deferred completion.
        assert adapter.disposal_pending is False
        assert adapter._subscribers == []
        assert adapter._notice_key is None
        assert len(events) == 1  # good subscriber saw the disposition


class TestPreExistingSpecStrictExactness:
    """Round-9 H1: foreign fields on PRE-EXISTING specs fail exactness."""

    @pytest.mark.parametrize("mutation", (
        "customData", "kind", "sibling_property", "new_child"))
    def test_in_attempt_failure_with_preexisting_spec_survivor(self, mutation):
        from pxr import Tf

        from ovui_data_adapters.openusd.commands import SetVisibilityCommand

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/Cube", "Cube")
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        pre = Sdf.CreatePrimInLayer(stage.GetSessionLayer(), "/World/Cube")
        pre.customData = {"before": 1}
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        fired = {"done": False}

        def reentrant(notice, sender):
            ps = [str(x) for x in tuple(notice.GetResyncedPaths())
                  + tuple(notice.GetChangedInfoOnlyPaths())]
            if not fired["done"] and "/World/Cube.visibility" in ps:
                fired["done"] = True
                spec = stage.GetSessionLayer().GetPrimAtPath("/World/Cube")
                if mutation == "customData":
                    spec.customData = {"before": 1, "survivor": 9}
                elif mutation == "kind":
                    spec.SetInfo("kind", "group")
                elif mutation == "sibling_property":
                    Sdf.AttributeSpec(
                        spec, "foreignAttr", Sdf.ValueTypeNames.Int)
                else:
                    Sdf.PrimSpec(spec, "ForeignChild", Sdf.SpecifierOver)

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        original_capture = SetVisibilityCommand._capture

        def failing_second_capture(self):
            count = getattr(self, "_test_caps", 0)
            self._test_caps = count + 1
            if count == 0:
                return original_capture(self)
            raise RuntimeError("POSTFAIL")

        SetVisibilityCommand._capture = failing_second_capture
        try:
            with pytest.raises(RuntimeError, match="POSTFAIL") as info:
                adapter.set_visibility(
                    stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            SetVisibilityCommand._capture = original_capture
            key.Revoke()
        # Exactness is FALSE, the foreign opinion survives, the retained
        # genuine roots flush conservatively, history stays empty, and the
        # original failure stays primary.
        assert getattr(info.value, "_ovui_visibility_net_zero", None) is False
        assert len(events) == 1
        delivered = set(events[0].changed_paths + events[0].resynced_paths)
        assert "/World/Cube.visibility" in delivered
        assert adapter._undo_manager._undo_stack == []
        spec = stage.GetSessionLayer().GetPrimAtPath("/World/Cube")
        if mutation == "customData":
            assert dict(spec.customData) == {"before": 1, "survivor": 9}
        adapter.dispose()

    def test_clean_in_attempt_failure_still_proves_net_zero(self):
        # Without any foreign edit the same failure shape stays a proven
        # net-zero: no event, layer byte-identical.
        from ovui_data_adapters.openusd.commands import SetVisibilityCommand

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/Cube", "Cube")
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        pre = Sdf.CreatePrimInLayer(stage.GetSessionLayer(), "/World/Cube")
        pre.customData = {"before": 1}
        baseline = stage.GetSessionLayer().ExportToString()
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        original_capture = SetVisibilityCommand._capture

        def failing_second_capture(self):
            count = getattr(self, "_test_caps", 0)
            self._test_caps = count + 1
            if count == 0:
                return original_capture(self)
            raise RuntimeError("POSTFAIL")

        SetVisibilityCommand._capture = failing_second_capture
        try:
            with pytest.raises(RuntimeError, match="POSTFAIL") as info:
                adapter.set_visibility(
                    stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            SetVisibilityCommand._capture = original_capture
        assert getattr(info.value, "_ovui_visibility_net_zero", None) is True
        assert events == []
        assert stage.GetSessionLayer().ExportToString() == baseline
        adapter.dispose()


class TestMixedChangedPathRendererRouting:
    """Round-9 H4: the live shortcut validates EVERY changed path."""

    def _mixed_event(self, mutation):
        from pxr import Tf

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/Cube", "Cube")
        sphere = stage.DefinePrim("/World/Sphere", "Sphere")
        if mutation in ("rel_remove", "rel_retarget"):
            rel = sphere.CreateRelationship("material:binding")
            rel.AddTarget("/World")
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        fired = {"done": False}

        def reentrant(notice, sender):
            ps = [str(x) for x in tuple(notice.GetResyncedPaths())
                  + tuple(notice.GetChangedInfoOnlyPaths())]
            if not fired["done"] and "/World/Cube.visibility" in ps:
                fired["done"] = True
                if mutation == "rel_create":
                    rel = sphere.CreateRelationship("material:binding")
                    rel.AddTarget("/World/Cube")
                elif mutation == "rel_remove":
                    sphere.RemoveProperty("material:binding")
                elif mutation == "rel_retarget":
                    sphere.GetRelationship(
                        "material:binding").SetTargets(["/World/Cube"])
                else:  # unsupported attribute form: foreign radius change
                    UsdGeom.Sphere(sphere).GetRadiusAttr().Set(9.0)

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        try:
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            key.Revoke()
        adapter.dispose()
        return stage, events[-1]

    @pytest.mark.parametrize("mutation", (
        "rel_create", "rel_remove", "rel_retarget", "foreign_attribute"))
    def test_mixed_consequence_routes_structurally(self, mutation):
        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage, event = self._mixed_event(mutation)
        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        renderer._latest_point_cloud_frames = {}
        decision = renderer._stage_change_sync_decision(
            event, tuple(event.changed_paths), tuple(event.resynced_paths),
            Sdf)
        assert decision != _STAGE_CHANGE_SYNC_LIVE
        # The structural path actually runs.
        calls = {"n": 0}

        class _Spy:
            def write_attribute(self, *args, **kw):
                pass

        renderer._renderer = _Spy()
        renderer._sync_ovrtx_root_snapshot_overlay_from_stage = (
            lambda: calls.__setitem__("n", calls["n"] + 1) or True)
        renderer._reload_live_root_snapshot = (
            lambda: calls.__setitem__("n", calls["n"] + 1) or True)
        renderer.notify_stage_changed(event)
        assert calls["n"] >= 1

    def test_pure_visibility_stays_live(self):
        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/Cube", "Cube")
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        event = events[-1]
        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        decision = renderer._stage_change_sync_decision(
            event, tuple(event.changed_paths), tuple(event.resynced_paths),
            Sdf)
        assert decision == _STAGE_CHANGE_SYNC_LIVE
        adapter.dispose()

    def test_over_chain_creation_click_stays_live(self):
        # Ordinary first-hide with created over ancestors (bare changed-info
        # prim entries) keeps the efficient live path.
        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/Group/Cube", "Cube")
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.set_visibility(
            stage.GetPrimAtPath("/World/Group/Cube"), False)
        event = events[-1]
        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        decision = renderer._stage_change_sync_decision(
            event, tuple(event.changed_paths), tuple(event.resynced_paths),
            Sdf)
        assert decision == _STAGE_CHANGE_SYNC_LIVE
        adapter.dispose()


class TestVisibilityNameShapeSemantics:
    """Round-10 I2: name shape never reclassifies; only proven attributes."""

    def _holder_stage(self, with_relationship: bool):
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/Cube", "Cube")
        holder = stage.DefinePrim("/World/Holder")
        if with_relationship:
            rel = holder.CreateRelationship("visibility")
            rel.AddTarget("/World/Cube")
        return stage, holder

    def _run_reentrant(self, stage, mutate):
        from pxr import Tf

        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        fired = {"done": False}

        def reentrant(notice, sender):
            ps = [str(p) for p in (*notice.GetResyncedPaths(),
                                   *notice.GetChangedInfoOnlyPaths())]
            if not fired["done"] and "/World/Cube.visibility" in ps:
                fired["done"] = True
                mutate()

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        try:
            adapter.set_visibility(stage.GetPrimAtPath("/World/Cube"), False)
        finally:
            key.Revoke()
        adapter.dispose()
        return events[-1]

    def _decision(self, stage, event):
        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
        )

        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        renderer._latest_point_cloud_frames = {}
        return renderer._stage_change_sync_decision(
            event, tuple(event.changed_paths), tuple(event.resynced_paths),
            Sdf)

    @pytest.mark.parametrize("mutation", ("remove", "create", "retarget"))
    def test_visibility_named_relationship_routes_structurally(self, mutation):
        from ovui_data_adapters.openusd.renderer_adapter import (
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage, holder = self._holder_stage(
            with_relationship=(mutation != "create"))

        def mutate():
            if mutation == "remove":
                holder.RemoveProperty("visibility")
            elif mutation == "create":
                rel = holder.CreateRelationship("visibility")
                rel.AddTarget("/World/Cube")
            else:
                holder.GetRelationship("visibility").SetTargets(["/World"])

        event = self._run_reentrant(stage, mutate)
        # Genuine notice path retained; NOT reclassified as visibility.
        assert "/World/Holder.visibility" in event.changed_paths
        authored = set((event.visibility_delta or {}).get("authored") or ())
        assert "/World/Holder" not in authored
        assert "/World/Cube" in authored
        assert self._decision(stage, event) != _STAGE_CHANGE_SYNC_LIVE

    def test_custom_attribute_lookalike_removal_routes_structurally(self):
        from ovui_data_adapters.openusd.renderer_adapter import (
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage, holder = self._holder_stage(with_relationship=False)
        holder.CreateAttribute("visibility", Sdf.ValueTypeNames.Float,
                               custom=True).Set(1.0)

        def mutate():
            holder.RemoveProperty("visibility")

        event = self._run_reentrant(stage, mutate)
        authored = set((event.visibility_delta or {}).get("authored") or ())
        # An ambiguous removed CUSTOM lookalike is not command-owned.
        assert "/World/Holder" not in authored
        assert self._decision(stage, event) != _STAGE_CHANGE_SYNC_LIVE

    def test_command_owned_removal_stays_annotated_and_live(self):
        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        cube = stage.DefinePrim("/World/Cube", "Cube")
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.set_visibility(cube, False)
        events.clear()
        undo.undo()   # command-owned removal of the schema attribute
        event = events[-1]
        assert "/World/Cube" in set(
            (event.visibility_delta or {}).get("authored") or ())
        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        assert renderer._stage_change_sync_decision(
            event, tuple(event.changed_paths), tuple(event.resynced_paths),
            Sdf) == _STAGE_CHANGE_SYNC_LIVE
        # Redo (attribute creation during replay) also stays live.
        events.clear()
        undo.redo()
        event = events[-1]
        assert renderer._stage_change_sync_decision(
            event, tuple(event.changed_paths), tuple(event.resynced_paths),
            Sdf) == _STAGE_CHANGE_SYNC_LIVE
        adapter.dispose()


class TestSchemaShapedVisibilityAuthority:
    """Round-11 J2: only schema-shaped attributes carry visibility authority;
    unproven annotation can never route live."""

    def _reentrant_lookalike_event(self, type_name, custom):
        from pxr import Tf

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        cube = stage.DefinePrim("/World/Cube", "Cube")
        holder = stage.DefinePrim("/World/Holder")
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = [str(p) for p in (*notice.GetResyncedPaths(),
                                      *notice.GetChangedInfoOnlyPaths())]
            if not fired["done"] and "/World/Cube.visibility" in paths:
                fired["done"] = True
                value = (1.0 if type_name == Sdf.ValueTypeNames.Float
                         else "lookalike")
                holder.CreateAttribute(
                    "visibility", type_name, custom=custom).Set(value)

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        try:
            adapter.set_visibility(cube, False)
        finally:
            key.Revoke()
        adapter.dispose()
        return stage, events[-1]

    def _decision(self, stage, event):
        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
        )

        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        renderer._latest_point_cloud_frames = {}
        return renderer._stage_change_sync_decision(
            event, tuple(event.changed_paths), tuple(event.resynced_paths),
            Sdf)

    @pytest.mark.parametrize("type_name,custom", (
        ("Float", True), ("String", False), ("Token", True)))
    def test_live_lookalike_attributes_route_structurally(
        self, type_name, custom
    ):
        from ovui_data_adapters.openusd.renderer_adapter import (
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage, event = self._reentrant_lookalike_event(
            getattr(Sdf.ValueTypeNames, type_name), custom)
        authored = set((event.visibility_delta or {}).get("authored") or ())
        # Genuine notice path retained; lookalike never authored.
        assert "/World/Holder.visibility" in event.changed_paths
        assert "/World/Holder" not in authored
        assert "/World/Cube" in authored
        assert self._decision(stage, event) != _STAGE_CHANGE_SYNC_LIVE

    def test_context_free_conservative_annotation_cannot_route_live(self):
        from pxr import Tf

        from ovui_data_adapters.openusd.renderer_adapter import (
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        cube = stage.DefinePrim("/World/Cube", "Cube")
        holder = stage.DefinePrim("/World/Holder")
        holder.CreateRelationship("visibility").AddTarget("/World/Cube")
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = [str(p) for p in (*notice.GetResyncedPaths(),
                                      *notice.GetChangedInfoOnlyPaths())]
            if not fired["done"] and "/World/Cube.visibility" in paths:
                fired["done"] = True
                holder.RemoveProperty("visibility")

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        adapter.begin_undo_group("g")
        try:
            adapter.set_visibility(cube, False)
        finally:
            key.Revoke()
        conservative = adapter._scope_conservative_event(
            adapter._visibility_scope["records"])
        # Context-free assembly: annotation is unproven delivery metadata.
        assert (conservative.visibility_delta or {}).get("proven") is None
        assert self._decision(
            stage, conservative) != _STAGE_CHANGE_SYNC_LIVE
        # The precise attempt event for the same operation stays proven.
        normal = adapter._visibility_scope["records"][0]["event"]
        assert (normal.visibility_delta or {}).get("proven") is True
        adapter.end_undo_group()
        adapter.dispose()

    def test_disposal_assembly_annotation_cannot_vouch_for_removals(self):
        # The context-free disposal assembly never carries the ``proven``
        # flag, so its annotation cannot vouch for a path the stage itself
        # cannot verify live (here: a REMOVED visibility-named
        # relationship retained in the disposition) — the renderer routes
        # structurally. A live genuine schema attribute in the same event
        # may still be handled live because the STAGE proves it, not the
        # annotation.
        from pxr import Tf

        from ovui_data_adapters.openusd.renderer_adapter import (
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        cube = stage.DefinePrim("/World/Cube", "Cube")
        holder = stage.DefinePrim("/World/Holder")
        holder.CreateRelationship("visibility").AddTarget("/World/Cube")
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = [str(p) for p in (*notice.GetResyncedPaths(),
                                      *notice.GetChangedInfoOnlyPaths())]
            if not fired["done"] and "/World/Cube.visibility" in paths:
                fired["done"] = True
                holder.RemoveProperty("visibility")

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        adapter.begin_undo_group("never-closed")
        try:
            adapter.set_visibility(cube, False)
        finally:
            key.Revoke()
        events.clear()
        adapter.dispose()   # context-free conservative disposition
        assert len(events) == 1
        delta = events[0].visibility_delta or {}
        assert delta.get("proven") is None
        assert "/World/Holder.visibility" in events[0].changed_paths
        assert self._decision(stage, events[0]) != _STAGE_CHANGE_SYNC_LIVE

    def test_genuine_flows_stay_proven_and_live(self):
        from ovui_data_adapters.openusd.renderer_adapter import (
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        cube = stage.DefinePrim("/World/Group/Cube", "Cube")
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.set_visibility(cube, False)   # over-chain creation click
        assert (events[-1].visibility_delta or {}).get("proven") is True
        assert self._decision(stage, events[-1]) == _STAGE_CHANGE_SYNC_LIVE
        events.clear()
        undo.undo()
        assert self._decision(stage, events[-1]) == _STAGE_CHANGE_SYNC_LIVE
        events.clear()
        undo.redo()
        assert self._decision(stage, events[-1]) == _STAGE_CHANGE_SYNC_LIVE
        adapter.dispose()


class TestConsumerBoundaryStructuralFloor:
    """PR review: unproven/imprecise events are structural at EVERY boundary."""

    def _decision(self, stage, event):
        from ovui_data_adapters.openusd.renderer_adapter import (
            OvRtxRendererAdapter,
        )

        renderer = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        renderer._stage = stage
        renderer._selected_paths = []
        renderer._latest_point_cloud_frames = {}
        return renderer._stage_change_sync_decision(
            event, tuple(event.changed_paths), tuple(event.resynced_paths),
            Sdf)

    def test_scope_conservative_event_routes_structurally(self):
        from ovui_data_adapters.openusd.renderer_adapter import (
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        cube = stage.DefinePrim("/World/Cube", "Cube")
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        adapter.begin_undo_group("g")
        adapter.set_visibility(cube, False)
        conservative = adapter._scope_conservative_event(
            adapter._visibility_scope["records"])
        assert self._decision(
            stage, conservative) != _STAGE_CHANGE_SYNC_LIVE
        adapter.end_undo_group()
        adapter.dispose()

    def test_precise_plus_imprecise_merge_routes_structurally(self):
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType
        from ovui_data_adapters.openusd.renderer_adapter import (
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        stage.DefinePrim("/World/Cube", "Cube")
        precise = ChangeEvent(
            changed_paths=("/World/Cube.visibility",), resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            visibility_delta={"authored": ("/World/Cube",), "boundaries": {},
                              "segments": (), "operation_resyncs": (),
                              "proven": True})
        imprecise = ChangeEvent(
            changed_paths=("/World/Cube.visibility",), resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            visibility_delta={"authored": ("/World/Cube",), "boundaries": {},
                              "segments": (), "operation_resyncs": (),
                              "precise": False})
        merged = UsdStageAdapter._merged_scope_event(
            [{"event": precise, "segments": []},
             {"event": imprecise, "segments": []}])
        assert (merged.visibility_delta or {}).get("proven") is None
        assert self._decision(stage, merged) != _STAGE_CHANGE_SYNC_LIVE

    def test_unresolved_disposal_event_routes_structurally(self):
        from ovui_data_adapters.openusd.renderer_adapter import (
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        cube = stage.DefinePrim("/World/Cube", "Cube")
        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.begin_undo_group("never-closed")
        adapter.set_visibility(cube, False)
        events.clear()
        adapter.dispose()
        assert self._decision(stage, events[0]) != _STAGE_CHANGE_SYNC_LIVE

    def test_non_imageable_token_lookalike_has_no_authority(self):
        from pxr import Tf

        from ovui_data_adapters.openusd.renderer_adapter import (
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        cube = stage.DefinePrim("/World/Cube", "Cube")
        bare = stage.DefinePrim("/World/Bare")   # typeless: NOT Imageable
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        fired = {"done": False}

        def reentrant(notice, sender):
            paths = [str(p) for p in (*notice.GetResyncedPaths(),
                                      *notice.GetChangedInfoOnlyPaths())]
            if not fired["done"] and "/World/Cube.visibility" in paths:
                fired["done"] = True
                bare.CreateAttribute(
                    "visibility", Sdf.ValueTypeNames.Token, custom=False
                ).Set("invisible")

        key = Tf.Notice.Register(Usd.Notice.ObjectsChanged, reentrant, stage)
        try:
            adapter.set_visibility(cube, False)
        finally:
            key.Revoke()
        event = events[-1]
        assert "/World/Bare" not in set(
            (event.visibility_delta or {}).get("authored") or ())
        assert self._decision(stage, event) != _STAGE_CHANGE_SYNC_LIVE
        adapter.dispose()

    def test_genuine_click_remains_live(self):
        from ovui_data_adapters.openusd.renderer_adapter import (
            _STAGE_CHANGE_SYNC_LIVE,
        )

        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World", "Xform")
        cube = stage.DefinePrim("/World/Cube", "Cube")
        adapter = UsdStageAdapter(stage, undo_manager=UndoManager())
        events: list = []
        sub = adapter.subscribe_changes(events.append)  # noqa: F841
        adapter.set_visibility(cube, False)
        assert self._decision(stage, events[-1]) == _STAGE_CHANGE_SYNC_LIVE
        adapter.dispose()
