# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Unit tests for SelectionBus — Step 58.

Focus areas not covered exhaustively by test_selection.py / test_selection_loop.py:
  - Core publish/subscribe/cancel contract (sketch cases)
  - SelectionItem path + source attributes
  - SelectionSnapshot with multiple items
  - Re-entrancy raises SelectionBusError (not silently dropped)
  - Subscribe DURING a notification callback
  - Unsubscribe DURING a notification callback (self-cancel and cancel-other)
  - get_snapshot reflects last publish
  - Layer push/pop lifecycle

The actual SelectionBus API uses publish(paths, source, layer) — not push(snapshot).
SelectionItem(path, source) — 'source' not 'type_name'.
"""

import gc

import pytest

from ovui_widgets.common.selection import (
    SelectionBus,
    SelectionBusError,
    SelectionChangedEvent,
    SelectionItem,
    SelectionSnapshot,
)
from ovui_data_adapters.services.selection import Subscription


@pytest.fixture(autouse=True)
def reset_singleton():
    SelectionBus._instance = None
    yield
    SelectionBus._instance = None


# ---------------------------------------------------------------------------
# SelectionItem attributes
# ---------------------------------------------------------------------------


class TestSelectionItemAttributes:
    def test_path_attribute(self):
        item = SelectionItem(path="/World/Sphere", source="stage")
        assert item.path == "/World/Sphere"

    def test_source_attribute(self):
        item = SelectionItem(path="/World/Sphere", source="stage")
        assert item.source == "stage"

    def test_positional_construction(self):
        item = SelectionItem("/A", "Mesh")
        assert item.path == "/A"
        assert item.source == "Mesh"

    def test_frozen_rejects_path_mutation(self):
        item = SelectionItem("/A", "stage")
        with pytest.raises(Exception):
            item.path = "/B"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SelectionSnapshot with multiple items
# ---------------------------------------------------------------------------


class TestSelectionSnapshotMultipleItems:
    def test_empty_snapshot(self):
        snap = SelectionSnapshot(items=())
        assert len(snap) == 0
        assert not snap
        assert snap.paths() == []

    def test_multiple_items_paths(self):
        items = (
            SelectionItem("/A", "stage"),
            SelectionItem("/B", "stage"),
            SelectionItem("/C", "stage"),
        )
        snap = SelectionSnapshot(items=items)
        assert len(snap) == 3
        assert snap.paths() == ["/A", "/B", "/C"]

    def test_default_layer(self):
        snap = SelectionSnapshot(items=())
        assert snap.layer == "primary"


# ---------------------------------------------------------------------------
# publish() notifies subscribers (core cases, real API)
# ---------------------------------------------------------------------------


class TestPublishNotifiesSubscribers:
    def test_push_notifies_subscriber(self):
        """Analogue of test_push_notifies_subscribers — real API."""
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(received.append)  # noqa: F841
        bus.publish(["/A"], source="stage")
        assert len(received) == 1
        assert received[0].snapshot.items[0].path == "/A"

    def test_event_snapshot_items_have_correct_attributes(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(received.append)  # noqa: F841
        bus.publish(["/A", "/B"], source="viewport")
        snap = received[0].snapshot
        assert snap.items[0].path == "/A"
        assert snap.items[1].path == "/B"
        assert all(item.source == "viewport" for item in snap.items)

    def test_multiple_subscribers_all_receive(self):
        bus = SelectionBus()
        r1, r2, r3 = [], [], []
        s1 = bus.subscribe(r1.append)  # noqa: F841
        s2 = bus.subscribe(r2.append)  # noqa: F841
        s3 = bus.subscribe(r3.append)  # noqa: F841
        bus.publish(["/X"], source="test")
        assert len(r1) == len(r2) == len(r3) == 1

    def test_event_is_selection_changed_event(self):
        bus = SelectionBus()
        events = []
        sub = bus.subscribe(events.append)  # noqa: F841
        bus.publish(["/test"], source="api")
        assert isinstance(events[0], SelectionChangedEvent)


# ---------------------------------------------------------------------------
# subscribe() returns Subscription
# ---------------------------------------------------------------------------


class TestSubscribeReturnsSubscription:
    def test_subscribe_returns_subscription_instance(self):
        bus = SelectionBus()
        sub = bus.subscribe(lambda e: None)
        assert isinstance(sub, Subscription)

    def test_must_hold_reference_to_prevent_auto_cancel(self):
        """RAII: losing the Subscription ref triggers GC auto-cancel."""
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(received.append)
        bus.publish(["/A"], source="test")
        del sub
        gc.collect()
        bus.publish(["/B"], source="test")
        assert len(received) == 1  # /B not received after GC


# ---------------------------------------------------------------------------
# Subscription.cancel() — test_cancel_subscription
# ---------------------------------------------------------------------------


class TestSubscriptionCancel:
    def test_cancel_stops_future_notifications(self):
        """Analogue of test_cancel_subscription — real API."""
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(received.append)
        bus.publish(["/A"], source="test")
        sub.cancel()
        bus.publish(["/B"], source="test")
        assert len(received) == 1

    def test_cancel_does_not_affect_other_subscribers(self):
        bus = SelectionBus()
        r1, r2 = [], []
        s1 = bus.subscribe(r1.append)
        s2 = bus.subscribe(r2.append)  # noqa: F841
        s1.cancel()
        bus.publish(["/X"], source="test")
        assert r1 == []
        assert len(r2) == 1

    def test_double_cancel_does_not_crash(self):
        bus = SelectionBus()
        sub = bus.subscribe(lambda e: None)
        sub.cancel()
        sub.cancel()  # must not raise


# ---------------------------------------------------------------------------
# Re-entrancy: SelectionBusError (not silently dropped)
# ---------------------------------------------------------------------------


class TestReentrancySafety:
    def test_reentrant_publish_raises_selection_bus_error(self):
        """test_reentrancy_safe: re-entrant call raises, not causes infinite loop."""
        bus = SelectionBus()
        errors = []

        def reentrant_cb(event):
            try:
                bus.publish(["/inner"], source="inner")
            except SelectionBusError as e:
                errors.append(e)

        sub = bus.subscribe(reentrant_cb)  # noqa: F841
        bus.publish(["/outer"], source="outer")
        assert len(errors) == 1
        assert isinstance(errors[0], SelectionBusError)

    def test_reentrant_publish_does_not_cause_infinite_recursion(self):
        bus = SelectionBus()
        call_count = [0]

        def cb(event):
            call_count[0] += 1
            try:
                bus.publish(["/x"], source="x")
            except SelectionBusError:
                pass

        sub = bus.subscribe(cb)  # noqa: F841
        bus.publish(["/start"], source="start")
        assert call_count[0] == 1  # not infinite

    def test_publishing_flag_resets_in_finally(self):
        """Even if a subscriber raises, _publishing resets so next call works."""
        bus = SelectionBus()

        def bad_cb(event):
            raise RuntimeError("deliberate")

        sub = bus.subscribe(bad_cb)  # noqa: F841
        try:
            bus.publish(["/A"], source="test")
        except RuntimeError:
            pass
        assert bus._publishing is False

        sub.cancel()
        received = []
        s2 = bus.subscribe(received.append)  # noqa: F841
        bus.publish(["/B"], source="test")
        assert len(received) == 1


# ---------------------------------------------------------------------------
# Subscribe DURING a notification callback
# ---------------------------------------------------------------------------


class TestSubscribeDuringNotification:
    def test_subscriber_added_during_dispatch_is_not_in_current_snapshot(self):
        """New subscriber added inside a callback does NOT receive the current event.

        SelectionBus uses list(self._subscribers) snapshot before iterating,
        so any subscriber added mid-dispatch is not in the snapshot.
        """
        bus = SelectionBus()
        late_calls = []

        def first_cb(event):
            bus.subscribe(late_calls.append)  # add during dispatch

        s1 = bus.subscribe(first_cb)  # noqa: F841
        bus.publish(["/A"], source="test")
        # late_calls must be empty — snapshot was taken before subscribe
        assert len(late_calls) == 0

    def test_subscriber_added_during_dispatch_receives_next_publish(self):
        """Subscriber added during dispatch IS registered for future events."""
        bus = SelectionBus()
        late_calls = []
        subs = []  # hold refs so RAII doesn't auto-cancel

        def first_cb(event):
            subs.append(bus.subscribe(late_calls.append))  # keep reference

        s1 = bus.subscribe(first_cb)  # noqa: F841
        bus.publish(["/A"], source="test")  # late sub added here
        bus.publish(["/B"], source="test")  # late sub should receive this
        assert len(late_calls) == 1
        assert late_calls[0].snapshot.paths() == ["/B"]


# ---------------------------------------------------------------------------
# Unsubscribe DURING a notification callback
# ---------------------------------------------------------------------------


class TestUnsubscribeDuringNotification:
    def test_subscriber_can_cancel_itself_during_notification(self):
        """A subscriber may cancel itself inside its callback without error."""
        bus = SelectionBus()
        received = []
        sub = [None]

        def cb(event):
            received.append(event)
            sub[0].cancel()  # self-cancel during dispatch

        sub[0] = bus.subscribe(cb)
        bus.publish(["/A"], source="test")
        bus.publish(["/B"], source="test")
        assert len(received) == 1  # only the first event was received

    def test_cancelling_sibling_subscriber_during_dispatch_prevents_future_events(self):
        """After cancellation during dispatch, the cancelled subscriber gets no future events."""
        bus = SelectionBus()
        b_calls = []
        sub_b = [None]

        def cb_a(event):
            sub_b[0].cancel()  # cancel cb_b during dispatch

        def cb_b(event):
            b_calls.append(event.snapshot.paths())

        sa = bus.subscribe(cb_a)  # noqa: F841
        sub_b[0] = bus.subscribe(cb_b)

        bus.publish(["/A"], source="test")  # cb_b may or may not receive /A
        bus.publish(["/B"], source="test")  # cb_b must NOT receive /B (was cancelled)

        assert not any(paths == ["/B"] for paths in b_calls)

    def test_cancel_during_dispatch_no_exception(self):
        """Cancelling any subscriber during dispatch must not raise any exception."""
        bus = SelectionBus()
        sub_to_cancel = [None]

        def canceller(event):
            sub_to_cancel[0].cancel()

        def victim(event):
            pass

        sc_ = bus.subscribe(canceller)  # noqa: F841
        sub_to_cancel[0] = bus.subscribe(victim)

        bus.publish(["/X"], source="test")  # must complete without exception


# ---------------------------------------------------------------------------
# get_snapshot
# ---------------------------------------------------------------------------


class TestGetSnapshot:
    def test_empty_before_any_publish(self):
        bus = SelectionBus()
        snap = bus.get_snapshot()
        assert len(snap) == 0

    def test_reflects_last_publish(self):
        bus = SelectionBus()
        bus.publish(["/A"], source="test")
        bus.publish(["/B", "/C"], source="test")
        snap = bus.get_snapshot()
        assert snap.paths() == ["/B", "/C"]

    def test_default_layer_is_primary(self):
        bus = SelectionBus()
        bus.publish(["/X"], source="test")
        snap = bus.get_snapshot()
        assert snap.layer == "primary"

    def test_named_layer_snapshot(self):
        bus = SelectionBus()
        bus.publish(["/T"], source="tool", layer="tool")
        snap = bus.get_snapshot("tool")
        assert snap.paths() == ["/T"]

    def test_nonexistent_layer_returns_empty(self):
        bus = SelectionBus()
        snap = bus.get_snapshot("nonexistent")
        assert len(snap) == 0
        assert snap.layer == "nonexistent"


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


class TestLayers:
    def test_push_layer_and_publish(self):
        bus = SelectionBus()
        bus.push_layer("temp")
        bus.publish(["/T"], source="tool", layer="temp")
        assert bus.get_snapshot("temp").paths() == ["/T"]

    def test_pop_layer_removes_entries(self):
        bus = SelectionBus()
        bus.push_layer("temp")
        bus.publish(["/T"], source="tool", layer="temp")
        bus.pop_layer("temp")
        assert bus.get_snapshot("temp").paths() == []

    def test_primary_layer_always_present(self):
        bus = SelectionBus()
        snap = bus.get_snapshot("primary")
        assert snap.layer == "primary"

    def test_pop_primary_raises_value_error(self):
        bus = SelectionBus()
        with pytest.raises(ValueError):
            bus.pop_layer("primary")

    def test_layers_are_independent(self):
        bus = SelectionBus()
        bus.publish(["/Primary"], source="stage", layer="primary")
        bus.publish(["/Tool"], source="tool", layer="tool")
        assert bus.get_snapshot("primary").paths() == ["/Primary"]
        assert bus.get_snapshot("tool").paths() == ["/Tool"]

    def test_push_layer_idempotent(self):
        bus = SelectionBus()
        bus.push_layer("tool")
        bus.publish(["/T"], source="tool", layer="tool")
        bus.push_layer("tool")  # must not reset contents
        assert bus.get_snapshot("tool").paths() == ["/T"]
