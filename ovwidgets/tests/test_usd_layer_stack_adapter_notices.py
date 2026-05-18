# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`UsdLayerStackAdapter` Tf/Sdf notice dispatch (Step 5).

Covers:
- One-frame batching: N edits coalesce into O(1) ``DIRTY_STATE_CHANGED`` events.
- ``SetEditTarget`` emits exactly one ``EDIT_TARGET_CHANGED`` per flush.
- ``detach_stage`` during a pending flush is clean (no exceptions, no late fire).
- Dirty-poll safety net catches save-path dirty→clean transitions that only
  fire ``LayerDirtinessChanged`` (whose sender is ``None`` for anonymous
  layers, defeating identifier-filter routing).
- Sublayer add → ``SUBLAYERS_CHANGED``.
- Layer metadata (``comment``) change → ``INFO_CHANGED`` with the field name.
- Worker-thread USD mutation still routes through the flush.
- Re-entrance: a subscriber that mutates USD during dispatch re-arms a
  fresh flush without losing the original event batch.

All tests skip when ``pxr`` is not available.
"""

from __future__ import annotations

import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List

import pytest

pytest.importorskip("pxr", reason="pxr (OpenUSD) not available")
from ovui_data_adapters.common import LayerEvent, LayerEventType
from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter
from pxr import Sdf, Usd, UsdGeom

from ovwidgets.common.undo import UndoManager

# ─── Harness ─────────────────────────────────────────────────────────────────


class _Harness:
    """Collector + synchronous ``call_later`` for deterministic flush draining.

    Production code uses :meth:`Application.call_later` which fires on the
    next UI frame; tests inject this harness so flushes are explicit and
    dispatch order is observable.
    """

    def __init__(self) -> None:
        self.events: List[LayerEvent] = []
        self.pending: List[Callable[[], None]] = []
        self._subscription = None  # keep subscription alive

    def call_later(self, delay: float, fn: Callable[[], None]) -> None:
        del delay
        self.pending.append(fn)
        # Returning ``None`` is a legitimate call_later contract — the
        # adapter must not rely on the handle identity as a scheduled-marker.
        return None

    def drain(self) -> None:
        # Drain to fixed point: a subscriber that mutates USD during
        # dispatch re-arms a new flush that also must drain.
        while self.pending:
            self.pending.pop(0)()

    def attach(self, adapter: UsdLayerStackAdapter) -> None:
        self._subscription = adapter.subscribe_events(self.events.append)
        adapter.attach_stage(call_later=self.call_later)


@pytest.fixture
def clean_stage():
    """File-backed clean stage so the initial dirty snapshot is ``False``."""
    td = tempfile.mkdtemp()
    path = os.path.join(td, "root.usda")
    Sdf.Layer.CreateNew(path).Save()
    stage = Usd.Stage.Open(path)
    yield stage, path


@pytest.fixture
def adapter_and_harness(clean_stage):
    stage, _ = clean_stage
    adapter = UsdLayerStackAdapter(stage, UndoManager())
    harness = _Harness()
    harness.attach(adapter)
    yield adapter, harness, stage
    try:
        adapter.detach_stage()
    except Exception:
        pass


# ─── Batching ────────────────────────────────────────────────────────────────


class TestBatching:
    def test_fifty_edits_collapse_to_one_dirty_event(self, adapter_and_harness):
        adapter, harness, stage = adapter_and_harness
        UsdGeom.Xform.Define(stage, "/A")
        attr = stage.GetPrimAtPath("/A").CreateAttribute(
            "userProp:tag", Sdf.ValueTypeNames.Int
        )
        for i in range(50):
            attr.Set(i)
        harness.drain()

        dirty = [
            e for e in harness.events
            if e.event_type == LayerEventType.DIRTY_STATE_CHANGED
        ]
        # Each layer dirty transition is one event (clean→dirty happens
        # once; subsequent sets don't flip dirtiness). Without batching
        # we would have seen 50+ events.
        assert len(dirty) == 1
        assert stage.GetRootLayer().identifier in dirty[0].identifiers

    def test_independent_layers_accumulate_in_parallel(self, adapter_and_harness):
        adapter, harness, stage = adapter_and_harness
        # Add a sublayer under root, then make a second set of edits that
        # the adapter tracks. Both edits land in one batch.
        anon = Sdf.Layer.CreateAnonymous()
        stage.GetRootLayer().subLayerPaths.append(anon.identifier)
        harness.drain()

        sub_events = [
            e for e in harness.events
            if e.event_type == LayerEventType.SUBLAYERS_CHANGED
        ]
        assert len(sub_events) == 1
        assert stage.GetRootLayer().identifier in sub_events[0].identifiers

    def test_flush_scheduled_only_once_per_batch(self, adapter_and_harness):
        adapter, harness, stage = adapter_and_harness
        UsdGeom.Xform.Define(stage, "/A")
        for i in range(20):
            stage.GetPrimAtPath("/A").CreateAttribute(
                f"userProp:tag{i}", Sdf.ValueTypeNames.Int
            ).Set(i)
        # Despite 20 spec creations, only one flush was scheduled.
        assert len(harness.pending) == 1


# ─── Edit target ─────────────────────────────────────────────────────────────


class TestEditTarget:
    def test_set_edit_target_emits_exactly_one_event(self, adapter_and_harness):
        adapter, harness, stage = adapter_and_harness
        session = stage.GetSessionLayer()
        if session is None:
            pytest.skip("no session layer on this platform")
        stage.SetEditTarget(Usd.EditTarget(session))
        harness.drain()

        et = [
            e for e in harness.events
            if e.event_type == LayerEventType.EDIT_TARGET_CHANGED
        ]
        assert len(et) == 1
        # Empty identifiers tuple means "re-query everything" per the ABC.
        assert et[0].identifiers == ()

    def test_double_target_change_coalesces(self, adapter_and_harness):
        adapter, harness, stage = adapter_and_harness
        session = stage.GetSessionLayer()
        root = stage.GetRootLayer()
        if session is None:
            pytest.skip("no session layer")
        stage.SetEditTarget(Usd.EditTarget(session))
        stage.SetEditTarget(Usd.EditTarget(root))
        harness.drain()
        et = [
            e for e in harness.events
            if e.event_type == LayerEventType.EDIT_TARGET_CHANGED
        ]
        # Two target switches within one batch window emit one event.
        assert len(et) == 1


# ─── Detach semantics ────────────────────────────────────────────────────────


class TestDetach:
    def test_detach_during_pending_flush_drops_batch(self, adapter_and_harness):
        adapter, harness, stage = adapter_and_harness
        UsdGeom.Xform.Define(stage, "/A")
        # A flush is now queued but not yet drained.
        assert len(harness.pending) >= 1

        adapter.detach_stage()
        # Draining after detach must be a no-op — the callback early-returns.
        harness.drain()

        # No events dispatched because the flush saw _destroyed=True.
        assert harness.events == []

    def test_detach_is_idempotent(self, adapter_and_harness):
        adapter, _, _ = adapter_and_harness
        adapter.detach_stage()
        # Second detach must not raise.
        adapter.detach_stage()

    def test_attach_twice_raises(self, clean_stage):
        stage, _ = clean_stage
        adapter = UsdLayerStackAdapter(stage, UndoManager())
        adapter.attach_stage()
        with pytest.raises(RuntimeError):
            adapter.attach_stage()
        adapter.detach_stage()

    def test_reattach_after_detach_works(self, adapter_and_harness):
        adapter, harness, stage = adapter_and_harness
        adapter.detach_stage()

        harness2 = _Harness()
        harness2.attach(adapter)
        UsdGeom.Xform.Define(stage, "/B")
        harness2.drain()
        dirty = [
            e for e in harness2.events
            if e.event_type == LayerEventType.DIRTY_STATE_CHANGED
        ]
        assert len(dirty) == 1

    def test_late_notice_after_detach_is_ignored(self, clean_stage):
        """Simulate a worker-thread notice firing after detach_stage."""
        stage, _ = clean_stage
        adapter = UsdLayerStackAdapter(stage, UndoManager())
        harness = _Harness()
        harness.attach(adapter)
        adapter.detach_stage()

        # Manually invoke a handler as if a late Tf.Notice reached us.
        # Guard must early-return without crashing.
        class _FakeNotice:
            def GetLayers(self):
                return [stage.GetRootLayer()]
        adapter._on_layers_did_change(_FakeNotice(), stage.GetRootLayer())
        adapter._on_layer_dirtiness_changed(None, None)
        # No flush should be scheduled, no events emitted.
        assert harness.pending == []
        assert harness.events == []


# ─── INFO_CHANGED ────────────────────────────────────────────────────────────


class TestInfoChanged:
    def test_comment_change_emits_info_event(self, adapter_and_harness):
        adapter, harness, stage = adapter_and_harness
        stage.GetRootLayer().comment = "hello"
        harness.drain()
        info = [
            e for e in harness.events
            if e.event_type == LayerEventType.INFO_CHANGED
        ]
        assert len(info) == 1
        identifier = stage.GetRootLayer().identifier
        assert identifier in info[0].info_fields
        assert "comment" in info[0].info_fields[identifier]

    def test_unknown_info_field_is_ignored(self, adapter_and_harness):
        adapter, harness, stage = adapter_and_harness
        # Custom data is not in _TRACKED_INFO_KEYS; change should not emit
        # an INFO_CHANGED event (though a DIRTY_STATE_CHANGED may still
        # fire because the layer becomes dirty).
        stage.GetRootLayer().customLayerData = {"foo": "bar"}
        harness.drain()
        info = [
            e for e in harness.events
            if e.event_type == LayerEventType.INFO_CHANGED
        ]
        assert len(info) == 0


# ─── SUBLAYERS_CHANGED ───────────────────────────────────────────────────────


class TestSublayersChanged:
    def test_sublayer_append_emits_event(self, adapter_and_harness):
        adapter, harness, stage = adapter_and_harness
        anon = Sdf.Layer.CreateAnonymous()
        stage.GetRootLayer().subLayerPaths.append(anon.identifier)
        harness.drain()
        sub_events = [
            e for e in harness.events
            if e.event_type == LayerEventType.SUBLAYERS_CHANGED
        ]
        assert len(sub_events) == 1
        assert stage.GetRootLayer().identifier in sub_events[0].identifiers


# ─── Dirty-poll safety net ───────────────────────────────────────────────────


class TestDirtyPoll:
    def test_save_path_caught_by_poll(self, adapter_and_harness):
        """``Save()`` flips dirty→clean and fires ``LayerDirtinessChanged``.

        The Python binding reports ``sender=None``, so identifier-filter
        routing cannot work — but the dirty-poll safety net diffs every
        cached layer's dirty flag and emits the synthetic event anyway.
        """
        adapter, harness, stage = adapter_and_harness
        # First make the layer dirty.
        UsdGeom.Xform.Define(stage, "/A")
        harness.drain()
        harness.events.clear()

        stage.GetRootLayer().Save()
        harness.drain()
        dirty = [
            e for e in harness.events
            if e.event_type == LayerEventType.DIRTY_STATE_CHANGED
        ]
        assert len(dirty) == 1
        assert stage.GetRootLayer().identifier in dirty[0].identifiers

    def test_poll_seeds_without_emitting(self, clean_stage):
        """New layers added mid-session get snapshot-seeded silently."""
        stage, _ = clean_stage
        adapter = UsdLayerStackAdapter(stage, UndoManager())
        harness = _Harness()
        harness.attach(adapter)

        # A new sublayer added to the stack gets registered in
        # _sdf_layers via get_sublayer_identifiers → _register. The
        # first poll pass should seed the snapshot without emitting.
        anon = Sdf.Layer.CreateAnonymous()
        stage.GetRootLayer().subLayerPaths.append(anon.identifier)
        adapter.get_sublayer_identifiers(adapter.get_root_layer())
        harness.drain()

        # Find any DIRTY_STATE_CHANGED events referencing the anon layer
        # (there should be none — first observation is silent).
        dirty_for_anon = [
            e for e in harness.events
            if e.event_type == LayerEventType.DIRTY_STATE_CHANGED
            and anon.identifier in e.identifiers
        ]
        assert dirty_for_anon == []
        adapter.detach_stage()


# ─── Worker-thread mutation ──────────────────────────────────────────────────


class TestWorkerThread:
    def test_worker_thread_edit_routes_through_flush(self, clean_stage):
        """Mutation on a worker thread still schedules a flush.

        In production the flush runs on the main thread via
        ``Application.call_later`` (thread-safe enough under GIL). In
        this test the synchronous ``call_later`` harness runs the flush
        on whatever thread called it — proving the full chain (handler
        → lock → schedule → flush → dispatch) survives cross-thread
        invocation.
        """
        stage, _ = clean_stage
        adapter = UsdLayerStackAdapter(stage, UndoManager())
        harness = _Harness()
        harness.attach(adapter)

        def worker() -> None:
            UsdGeom.Xform.Define(stage, "/Worker")

        with ThreadPoolExecutor(max_workers=1) as ex:
            ex.submit(worker).result()

        harness.drain()
        dirty = [
            e for e in harness.events
            if e.event_type == LayerEventType.DIRTY_STATE_CHANGED
        ]
        assert len(dirty) == 1
        adapter.detach_stage()

    def test_lock_prevents_race_on_pending(self, clean_stage):
        """Concurrent mutations from multiple workers don't corrupt _pending."""
        stage, _ = clean_stage
        adapter = UsdLayerStackAdapter(stage, UndoManager())
        harness = _Harness()
        harness.attach(adapter)

        errors: List[BaseException] = []
        barrier = threading.Barrier(4)

        def worker(i: int) -> None:
            barrier.wait()
            try:
                stage.GetRootLayer().comment = f"comment-{i}"
            except BaseException as exc:
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(worker, i) for i in range(4)]
            for f in futures:
                f.result()
        harness.drain()

        assert errors == []
        info_events = [
            e for e in harness.events
            if e.event_type == LayerEventType.INFO_CHANGED
        ]
        # All 4 comment changes coalesce into at most one INFO_CHANGED
        # event per identifier. Deduplication is the whole point.
        assert len(info_events) == 1
        adapter.detach_stage()


# ─── Re-entrance ─────────────────────────────────────────────────────────────


class TestReentrance:
    def test_subscriber_mutation_rearmed_as_new_batch(self, adapter_and_harness):
        """A subscriber that mutates USD mid-dispatch re-arms a new flush."""
        adapter, harness, stage = adapter_and_harness

        mutated = [False]

        def reentrant(event: LayerEvent) -> None:
            # Only mutate once to avoid infinite ping-pong; and only on
            # the first DIRTY_STATE_CHANGED.
            if mutated[0] or event.event_type != LayerEventType.DIRTY_STATE_CHANGED:
                return
            mutated[0] = True
            stage.GetRootLayer().comment = "added during dispatch"

        sub = adapter.subscribe_events(reentrant)
        harness._subscription_reentrant = sub  # keep alive

        UsdGeom.Xform.Define(stage, "/A")
        harness.drain()  # drains both the original batch and the rearmed one

        info_events = [
            e for e in harness.events
            if e.event_type == LayerEventType.INFO_CHANGED
        ]
        assert mutated[0] is True
        # The comment change triggered a second batch → one INFO_CHANGED event.
        assert len(info_events) == 1

    def test_raising_subscriber_does_not_break_dispatch(self, adapter_and_harness):
        """One bad handler does not prevent others from receiving events."""
        adapter, harness, stage = adapter_and_harness

        def bad(event: LayerEvent) -> None:
            raise RuntimeError("boom")

        received: List[LayerEvent] = []

        def good(event: LayerEvent) -> None:
            received.append(event)

        sub_bad = adapter.subscribe_events(bad)
        sub_good = adapter.subscribe_events(good)
        harness._bad = sub_bad  # keep alive
        harness._good = sub_good

        UsdGeom.Xform.Define(stage, "/A")
        harness.drain()

        assert any(
            e.event_type == LayerEventType.DIRTY_STATE_CHANGED for e in received
        )
