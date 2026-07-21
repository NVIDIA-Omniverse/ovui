# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Native OVStage provider-stream delivery contracts (runtime-free).

Converted from the backing-USD visibility transaction suite: the bridge
machinery (notice ledgers, delivery debt, dispatch probes, layer
baselines) was deleted with the native-only port, but the provider-stream
guarantees are substrate-independent and keep their coverage here:

- one publication reaches BOTH channels with every applicable subscriber
  attempted exactly once;
- an interrupting subscriber (KeyboardInterrupt) cannot starve later
  subscribers or the other channel, and re-raises only after all were
  attempted;
- ordinary observer failures follow native post-commit semantics: they
  are recorded on the stream's ``delivery_failures`` ledger and never
  turn an already-committed native mutation into a reported failure;
- provider-owned acceptance receipts are issued exactly when a
  publication is genuinely accepted under that policy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ovui_data_adapters.common._command import command_edge, in_command_edge
from ovui_data_adapters.ovstage.change_stream import OvstageChangeStream


def _stream() -> OvstageChangeStream:
    return OvstageChangeStream(SimpleNamespace(_stage=None, is_open=True))


class TestProviderStreamIsolation:
    """Provider delivery under BaseException: attempt all, then report."""

    def test_interrupting_first_subscriber_never_starves_later(self):
        stream = _stream()
        later: list = []

        def first(_event):
            raise KeyboardInterrupt("first provider subscriber")

        sub1 = stream.subscribe_stage(first)          # noqa: F841
        sub2 = stream.subscribe_stage(later.append)   # noqa: F841
        with pytest.raises(KeyboardInterrupt):
            stream.publish_visibility_change(["/World/A"])
        assert len(later) == 1
        # A later independent event reaches every remaining subscriber.
        with pytest.raises(KeyboardInterrupt):
            stream.publish_visibility_change(["/World/B"])
        assert len(later) == 2

    def test_ordinary_failures_are_recorded_not_raised(self):
        # Post-commit policy: native state and undo history are already
        # committed when subscribers run, so an observer Exception must
        # not fail the publication — it is attempted-all, recorded on the
        # provider ledger, and the event still counts as delivered.
        stream = _stream()
        calls: list = []

        def bad(_event):
            calls.append("bad")
            raise RuntimeError("subscriber boom")

        sub1 = stream.subscribe_stage(bad)                           # noqa: F841
        sub2 = stream.subscribe_stage(lambda e: calls.append("ok"))  # noqa: F841
        event = stream.publish_visibility_change(["/World/A"])
        assert event is not None
        assert calls == ["bad", "ok"]
        failures = getattr(stream, "delivery_failures", [])
        assert failures and isinstance(failures[-1], RuntimeError)

    def test_scheduled_delivery_records_failures_without_breaking(self):
        stream = _stream()
        scheduled: list = []

        def call_later(_delay, fn):
            scheduled.append(fn)

        received: list = []

        def bad(_event):
            raise KeyboardInterrupt("scheduled interrupt")

        sub1 = stream.subscribe_stage(bad, call_later=call_later)  # noqa: F841
        sub2 = stream.subscribe_stage(                              # noqa: F841
            received.append, call_later=call_later)
        stream.publish_visibility_change(["/World/A"])
        # Both subscriber callbacks were scheduled (the stream may add its
        # own internal poll entries); running them is scheduler-owned.
        assert len(scheduled) >= 2
        for fn in list(scheduled):   # snapshot: internal polls re-schedule
            fn()   # the scheduler loop must survive the interrupt
        assert len(received) == 1
        failures = getattr(stream, "delivery_failures", [])
        assert failures and isinstance(failures[0], KeyboardInterrupt)


class TestCrossChannelPublication:
    """One publication reaches stage AND property channels."""

    def test_stage_interrupt_does_not_starve_property_channel(self):
        stream = _stream()
        calls: list = []

        def bad(_event):
            calls.append("stage_bad")
            raise KeyboardInterrupt("stage")

        s1 = stream.subscribe_stage(bad)                                    # noqa: F841
        s2 = stream.subscribe_stage(lambda e: calls.append("stage_later"))  # noqa: F841
        p1 = stream.subscribe_property(                                     # noqa: F841
            ["/World/A"], lambda: calls.append("property"))
        with pytest.raises(KeyboardInterrupt):
            stream.publish_visibility_change(["/World/A"])
        assert calls == ["stage_bad", "stage_later", "property"]

    def test_property_failure_does_not_starve_and_is_recorded(self):
        stream = _stream()
        calls: list = []

        def bad_property():
            calls.append("property_bad")
            raise RuntimeError("property boom")

        p1 = stream.subscribe_property(["/World/A"], bad_property)    # noqa: F841
        s1 = stream.subscribe_stage(lambda e: calls.append("stage"))  # noqa: F841
        p2 = stream.subscribe_property(                               # noqa: F841
            ["/World/A"], lambda: calls.append("property_later"))
        event = stream.publish_visibility_change(["/World/A"])
        assert event is not None
        assert calls == ["stage", "property_bad", "property_later"]
        failures = getattr(stream, "delivery_failures", [])
        assert failures and isinstance(failures[-1], RuntimeError)
        # Later independent publications continue normally.
        calls.clear()
        assert stream.publish_visibility_change(["/World/A"]) is not None
        assert calls == ["stage", "property_bad", "property_later"]


class TestProviderOwnedDeliveryReceipts:
    """Acceptance receipts truthfully match the final delivery policy."""

    def test_receipts_only_for_accepted_publications(self):
        stream = OvstageChangeStream(
            SimpleNamespace(is_open=True, current_ordinal=None)
        )
        before = stream.accepted_visibility_ordinal
        # Closed/suppressed publications are NOT accepted: no receipt.
        stream._closed = True
        assert stream.publish_visibility_change(["/World/A"]) is None
        assert stream.accepted_visibility_ordinal == before
        stream._closed = False
        stream._suppressed = 1
        assert stream.publish_visibility_change(["/World/A"]) is None
        assert stream.accepted_visibility_ordinal == before
        stream._suppressed = 0
        assert stream.publish_visibility_change(["/World/A"]) is not None
        assert stream.accepted_visibility_ordinal == before + 1
        assert stream.accepted_visibility_publications[-1][1] == frozenset(
            {"/World/A"})

    def test_observer_exception_still_receipts_interrupt_does_not(self):
        stream = _stream()
        before = stream.accepted_visibility_ordinal

        def bad(_event):
            raise RuntimeError("observer boom")

        sub = stream.subscribe_stage(bad)  # noqa: F841
        # Under the post-commit policy the publication IS accepted even
        # though an observer failed — the receipt stays truthful.
        assert stream.publish_visibility_change(["/World/A"]) is not None
        assert stream.accepted_visibility_ordinal == before + 1
        sub.cancel()

        def interrupt(_event):
            raise KeyboardInterrupt("interrupt")

        sub2 = stream.subscribe_stage(interrupt)  # noqa: F841
        with pytest.raises(KeyboardInterrupt):
            stream.publish_visibility_change(["/World/B"])
        # An interrupted publication is not proven accepted: no receipt.
        assert stream.accepted_visibility_ordinal == before + 1

    def test_visibility_source_is_canonical_and_classifiable(self):
        stream = _stream()
        events: list = []
        sub = stream.subscribe_stage(events.append)  # noqa: F841
        stream.publish_visibility_change(["/World/A"])
        assert events[-1].source == "ovstage:visibility"
        stream.publish_visibility_change(["/World/B"], source="property:set")
        assert events[-1].source == "property:set"

    def test_every_visibility_publication_carries_canonical_delta(self):
        # Canonical classification is provenance-independent: a Property
        # Inspector write ("property:set") and an adapter toggle both mark
        # the event as a proven, precise visibility change so consumers
        # never fall back to a structural rebuild.
        stream = _stream()
        events: list = []
        sub = stream.subscribe_stage(events.append)  # noqa: F841
        for provenance in (None, "property:set"):
            stream.publish_visibility_change(["/World/A"], source=provenance)
            delta = events[-1].visibility_delta
            assert delta is not None
            assert delta.get("proven") is True
            assert delta.get("precise") is True
            assert tuple(delta.get("authored") or ()) == ("/World/A",)
            assert tuple(delta.get("operation_resyncs") or ()) == ()


class TestCommittedEdgePublication:
    """Interrupt deferral while a history edge is pending."""

    def test_interrupts_deferred_to_scope_exit_marked_consistent(self):
        stream = _stream()
        later: list = []
        published: list = []

        def interrupting(_event):
            raise KeyboardInterrupt("observer")

        sub1 = stream.subscribe_stage(interrupting)   # noqa: F841
        sub2 = stream.subscribe_stage(later.append)   # noqa: F841
        # The publication itself completes inside the scope — the caller
        # (a command edge inside UndoManager push/undo/redo) can finish
        # its state work — and the interrupt re-raises AT SCOPE EXIT,
        # marked history-consistent (only while a command edge executes)
        # so the command service records the entry before letting it
        # reach the caller. Never hidden.
        with pytest.raises(KeyboardInterrupt) as interrupt:
            with command_edge():
                with stream.committed_edge_publication():
                    published.append(
                        stream.publish_visibility_change(["/World/A"])
                    )
        assert getattr(
            interrupt.value, "_ovui_history_consistent", False
        ) is True
        assert published[0] is not None
        assert len(later) == 1
        failures = getattr(stream, "delivery_failures", [])
        assert failures and isinstance(failures[-1], KeyboardInterrupt)
        # The publication was genuinely dispatched: receipt issued.
        assert stream.accepted_visibility_publications[-1][1] == frozenset(
            {"/World/A"})
        # Outside the scope the default policy is untouched (unmarked).
        with pytest.raises(KeyboardInterrupt) as raw:
            stream.publish_visibility_change(["/World/B"])
        assert not getattr(raw.value, "_ovui_history_consistent", False)

    def test_nested_scopes_defer_to_the_innermost_exit(self):
        stream = _stream()

        def interrupting(_event):
            raise SystemExit("observer")

        sub = stream.subscribe_stage(interrupting)  # noqa: F841
        with pytest.raises(SystemExit) as interrupt:
            with command_edge():
                with stream.committed_edge_publication():
                    with stream.committed_edge_publication():
                        assert (
                            stream.publish_visibility_change(["/A"])
                            is not None
                        )
        assert getattr(interrupt.value, "_ovui_history_consistent", False)
        # Scopes fully unwound: the default policy is restored.
        with pytest.raises(SystemExit) as raw:
            stream.publish_visibility_change(["/C"])
        assert not getattr(raw.value, "_ovui_history_consistent", False)

    def test_edge_ownership_is_not_inherited_by_async_children(self):
        """Edge membership belongs to the pending edge, never to snapshots.

        Contexts captured inside an edge (what asyncio tasks/callbacks
        inherit) stop counting as in-edge the moment the edge ends;
        contexts captured before an edge never count; synchronous
        re-entrant work inside the edge still counts; threads never
        inherit an edge; and nested edges restore the outer edge's
        ownership on exit.
        """
        import contextvars
        import threading

        before_snapshot = contextvars.copy_context()
        during_snapshot: list = []
        thread_result: list = []
        with command_edge():
            assert in_command_edge() is True
            during_snapshot.append(contextvars.copy_context())
            # A task created BEFORE the edge, were it to run now, is not
            # part of this edge's synchronous chain.
            assert before_snapshot.run(in_command_edge) is False
            # Synchronous re-entrancy and nested edges stay owned.
            with command_edge():
                assert in_command_edge() is True
            assert in_command_edge() is True
            # Threads get fresh contexts: never inside anyone's edge.
            thread = threading.Thread(
                target=lambda: thread_result.append(in_command_edge())
            )
            thread.start()
            thread.join()
            assert thread_result == [False]
            # Delayed execution DURING the edge (same synchronous chain's
            # snapshot) still counts — the owning edge is still pending.
            assert during_snapshot[0].run(in_command_edge) is True
        # Delayed execution AFTER the edge completed: the inherited
        # snapshot's edge token is dead — no longer inside the edge.
        assert in_command_edge() is False
        assert during_snapshot[0].run(in_command_edge) is False

    def test_post_edge_async_child_publication_is_unmarked(self):
        # The full stream-level shape of the async-child defect: the
        # publication happens in a context snapshot inherited from inside
        # an edge, but runs after the edge ended — delivered clean.
        import contextvars

        stream = _stream()

        def interrupting(_event):
            raise KeyboardInterrupt("child observer")

        sub = stream.subscribe_stage(interrupting)  # noqa: F841
        holder: list = []
        with command_edge():
            holder.append(contextvars.copy_context())

        def child_publish():
            with pytest.raises(KeyboardInterrupt) as caught:
                with stream.committed_edge_publication():
                    stream.publish_visibility_change(["/World/A"])
            return caught.value

        delivered = holder[0].run(child_publish)
        assert not getattr(delivered, "_ovui_history_consistent", False)

    def test_no_mark_outside_a_command_edge(self):
        # A public direct adapter write (caller-managed undo) publishes
        # through the same scope but with NO command-service edge active:
        # the delivered interrupt is a fresh chained copy carrying no
        # internal per-edge state, safe for the application to reuse.
        stream = _stream()
        shared = KeyboardInterrupt("direct-write observer")

        def interrupting(_event):
            raise shared

        sub = stream.subscribe_stage(interrupting)  # noqa: F841
        with pytest.raises(KeyboardInterrupt) as caught:
            with stream.committed_edge_publication():
                stream.publish_visibility_change(["/World/A"])
        assert caught.value is not shared
        assert caught.value.__cause__ is shared
        assert not getattr(caught.value, "_ovui_history_consistent", False)
        assert not getattr(shared, "_ovui_history_consistent", False)
