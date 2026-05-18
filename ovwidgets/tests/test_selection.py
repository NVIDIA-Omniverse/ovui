# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for SelectionBus — OvGear Step 6."""

import gc

import pytest

from ovwidgets.common.selection import (
    SelectionBus,
    SelectionBusError,
    SelectionChangedEvent,
    SelectionItem,
    SelectionSnapshot,
)


@pytest.fixture(autouse=True)
def reset_singleton():
    SelectionBus._instance = None
    yield
    SelectionBus._instance = None


# ---------------------------------------------------------------------------
# SelectionItem
# ---------------------------------------------------------------------------


class TestSelectionItem:
    def test_path_and_source(self):
        item = SelectionItem(path="/World/Cube", source="stage")
        assert item.path == "/World/Cube"
        assert item.source == "stage"

    def test_frozen_rejects_mutation(self):
        item = SelectionItem(path="/World/Cube", source="stage")
        with pytest.raises(Exception):
            item.path = "/other"  # type: ignore[misc]

    def test_equality_same_fields(self):
        a = SelectionItem("/World/Cube", "stage")
        b = SelectionItem("/World/Cube", "stage")
        assert a == b

    def test_inequality_different_path(self):
        a = SelectionItem("/World/Cube", "stage")
        b = SelectionItem("/World/Sphere", "stage")
        assert a != b

    def test_inequality_different_source(self):
        a = SelectionItem("/World/Cube", "stage")
        b = SelectionItem("/World/Cube", "viewport")
        assert a != b

    def test_hashable(self):
        item = SelectionItem("/World/Cube", "stage")
        s = {item}
        assert item in s


# ---------------------------------------------------------------------------
# SelectionSnapshot
# ---------------------------------------------------------------------------


class TestSelectionSnapshot:
    def test_empty_snapshot_len(self):
        snap = SelectionSnapshot(items=())
        assert len(snap) == 0

    def test_empty_snapshot_bool(self):
        snap = SelectionSnapshot(items=())
        assert not snap

    def test_empty_snapshot_paths(self):
        snap = SelectionSnapshot(items=())
        assert snap.paths() == []

    def test_single_item(self):
        items = (SelectionItem("/World/Cube", "stage"),)
        snap = SelectionSnapshot(items=items)
        assert len(snap) == 1
        assert bool(snap)
        assert snap.paths() == ["/World/Cube"]

    def test_multiple_items(self):
        items = (
            SelectionItem("/World/Cube", "stage"),
            SelectionItem("/World/Sphere", "stage"),
        )
        snap = SelectionSnapshot(items=items)
        assert len(snap) == 2
        assert snap.paths() == ["/World/Cube", "/World/Sphere"]

    def test_default_layer_is_primary(self):
        snap = SelectionSnapshot(items=())
        assert snap.layer == "primary"

    def test_custom_layer(self):
        snap = SelectionSnapshot(items=(), layer="tool")
        assert snap.layer == "tool"

    def test_frozen_rejects_mutation(self):
        snap = SelectionSnapshot(items=())
        with pytest.raises(Exception):
            snap.layer = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# SelectionChangedEvent
# ---------------------------------------------------------------------------


class TestSelectionChangedEvent:
    def test_has_snapshot_and_source(self):
        snap = SelectionSnapshot(items=())
        event = SelectionChangedEvent(snapshot=snap, source="stage")
        assert event.snapshot is snap
        assert event.source == "stage"

    def test_mutable(self):
        snap = SelectionSnapshot(items=())
        event = SelectionChangedEvent(snapshot=snap, source="stage")
        event.source = "updated"
        assert event.source == "updated"


# ---------------------------------------------------------------------------
# Basic publish/subscribe
# ---------------------------------------------------------------------------


class TestBasicPublishSubscribe:
    def test_subscribe_and_receive(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e))  # noqa: F841
        bus.publish(["/World/Cube"], source="stage")
        assert len(received) == 1
        assert received[0].source == "stage"
        assert received[0].snapshot.paths() == ["/World/Cube"]

    def test_event_snapshot_layer(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e))  # noqa: F841
        bus.publish(["/A"], source="test", layer="primary")
        assert received[0].snapshot.layer == "primary"

    def test_multiple_subscribers_all_called(self):
        bus = SelectionBus()
        calls = []
        s1 = bus.subscribe(lambda e: calls.append(1))  # noqa: F841
        s2 = bus.subscribe(lambda e: calls.append(2))  # noqa: F841
        s3 = bus.subscribe(lambda e: calls.append(3))  # noqa: F841
        bus.publish(["/X"], source="api")
        assert calls == [1, 2, 3]

    def test_multiple_publishes(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e.snapshot.paths()))  # noqa: F841
        bus.publish(["/A"], source="s")
        bus.publish(["/B", "/C"], source="s")
        assert received == [["/A"], ["/B", "/C"]]

    def test_items_carry_publisher_source(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e))  # noqa: F841
        bus.publish(["/World/Cube"], source="viewport")
        items = received[0].snapshot.items
        assert all(item.source == "viewport" for item in items)

    def test_no_subscribers_publish_is_silent(self):
        bus = SelectionBus()
        bus.publish(["/A"], source="test")  # must not raise

    def test_publish_empty_paths(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e))  # noqa: F841
        bus.publish([], source="test")
        assert len(received) == 1
        assert received[0].snapshot.paths() == []


# ---------------------------------------------------------------------------
# get_snapshot
# ---------------------------------------------------------------------------


class TestGetSnapshot:
    def test_empty_before_publish(self):
        bus = SelectionBus()
        snap = bus.get_snapshot()
        assert len(snap) == 0
        assert not snap

    def test_reflects_last_publish(self):
        bus = SelectionBus()
        bus.publish(["/A", "/B"], source="stage")
        snap = bus.get_snapshot()
        assert snap.paths() == ["/A", "/B"]

    def test_nonexistent_layer_returns_empty(self):
        bus = SelectionBus()
        snap = bus.get_snapshot("nonexistent")
        assert len(snap) == 0

    def test_nonexistent_layer_has_correct_layer_field(self):
        bus = SelectionBus()
        snap = bus.get_snapshot("nonexistent")
        assert snap.layer == "nonexistent"

    def test_snapshot_layer_field(self):
        bus = SelectionBus()
        bus.push_layer("tool")
        bus.publish(["/Tool"], source="tool", layer="tool")
        snap = bus.get_snapshot("tool")
        assert snap.layer == "tool"
        assert snap.paths() == ["/Tool"]


# ---------------------------------------------------------------------------
# clear
# ---------------------------------------------------------------------------


class TestClear:
    def test_clear_empties_selection(self):
        bus = SelectionBus()
        bus.publish(["/A", "/B"], source="stage")
        bus.clear()
        snap = bus.get_snapshot()
        assert len(snap) == 0
        assert not snap

    def test_clear_notifies_subscribers(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e))  # noqa: F841
        bus.publish(["/A"], source="stage")
        bus.clear()
        assert len(received) == 2
        assert len(received[1].snapshot) == 0

    def test_get_snapshot_after_clear(self):
        bus = SelectionBus()
        bus.publish(["/A"], source="stage")
        bus.clear()
        assert not bus.get_snapshot()

    def test_clear_specific_layer(self):
        bus = SelectionBus()
        bus.push_layer("tool")
        bus.publish(["/A"], source="stage", layer="primary")
        bus.publish(["/T"], source="tool", layer="tool")
        bus.clear(layer="tool")
        assert bus.get_snapshot("primary").paths() == ["/A"]
        assert not bus.get_snapshot("tool")

    def test_clear_empty_bus_fires_event(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e))  # noqa: F841
        bus.clear()
        assert len(received) == 1  # fires even if already empty


# ---------------------------------------------------------------------------
# Reentrancy guard
# ---------------------------------------------------------------------------


class TestReentrancyGuard:
    def test_reentrant_publish_raises(self):
        bus = SelectionBus()
        errors = []

        def reentrant_sub(event):
            try:
                bus.publish(["/bad"], "bad")
            except SelectionBusError as e:
                errors.append(e)

        sub = bus.subscribe(reentrant_sub)  # noqa: F841
        bus.publish(["/foo"], "test")
        assert len(errors) == 1
        assert isinstance(errors[0], SelectionBusError)

    def test_other_subscribers_called_after_reentrant_sub(self):
        bus = SelectionBus()
        called = []

        def bad_sub(event):
            try:
                bus.publish(["/bad"], "bad")
            except SelectionBusError:
                pass

        def good_sub(event):
            called.append(True)

        sub1 = bus.subscribe(bad_sub)  # noqa: F841
        sub2 = bus.subscribe(good_sub)  # noqa: F841
        bus.publish(["/foo"], "test")
        assert len(called) == 1

    def test_publishing_flag_reset_after_reentrancy(self):
        bus = SelectionBus()

        def sub(event):
            try:
                bus.publish(["/bad"], "bad")
            except SelectionBusError:
                pass

        s1 = bus.subscribe(sub)  # noqa: F841
        bus.publish(["/foo"], "test")
        # Flag must be reset — a second publish must succeed
        received = []
        s2 = bus.subscribe(lambda e: received.append(e))  # noqa: F841
        bus.publish(["/bar"], "test")
        assert len(received) == 1

    def test_reentrant_clear_raises(self):
        bus = SelectionBus()
        errors = []

        def sub(event):
            try:
                bus.clear()
            except SelectionBusError as e:
                errors.append(e)

        s = bus.subscribe(sub)  # noqa: F841
        bus.publish(["/foo"], "test")
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# Source tracking
# ---------------------------------------------------------------------------


class TestSourceTracking:
    def test_source_stored_in_items(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e))  # noqa: F841
        bus.publish(["/A", "/B"], source="stage")
        items = received[0].snapshot.items
        assert items[0].source == "stage"
        assert items[1].source == "stage"

    def test_source_in_event(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e))  # noqa: F841
        bus.publish(["/A"], source="viewport")
        assert received[0].source == "viewport"

    def test_multiple_sources_tracked(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e.source))  # noqa: F841
        bus.publish(["/A"], source="stage")
        bus.publish(["/B"], source="viewport")
        bus.publish(["/C"], source="external")
        assert received == ["stage", "viewport", "external"]

    def test_clear_event_source_is_api(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e.source))  # noqa: F841
        bus.clear()
        assert received == ["api"]


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


class TestLayers:
    def test_push_layer_creates_empty(self):
        bus = SelectionBus()
        bus.push_layer("tool")
        snap = bus.get_snapshot("tool")
        assert len(snap) == 0

    def test_tool_layer_doesnt_affect_primary(self):
        bus = SelectionBus()
        bus.publish(["/Primary"], source="stage", layer="primary")
        bus.push_layer("tool")
        bus.publish(["/Tool"], source="tool", layer="tool")
        assert bus.get_snapshot("primary").paths() == ["/Primary"]
        assert bus.get_snapshot("tool").paths() == ["/Tool"]

    def test_pop_layer_removes_it(self):
        bus = SelectionBus()
        bus.push_layer("tool")
        bus.publish(["/T"], source="tool", layer="tool")
        bus.pop_layer("tool")
        snap = bus.get_snapshot("tool")
        assert len(snap) == 0  # gone → returns empty

    def test_pop_primary_raises_value_error(self):
        bus = SelectionBus()
        with pytest.raises(ValueError):
            bus.pop_layer("primary")

    def test_pop_nonexistent_layer_is_silent(self):
        bus = SelectionBus()
        bus.pop_layer("nonexistent")  # must not raise

    def test_primary_always_present(self):
        bus = SelectionBus()
        snap = bus.get_snapshot("primary")
        assert snap.layer == "primary"

    def test_push_layer_idempotent(self):
        bus = SelectionBus()
        bus.push_layer("tool")
        bus.publish(["/T"], source="tool", layer="tool")
        bus.push_layer("tool")  # must not reset contents
        assert bus.get_snapshot("tool").paths() == ["/T"]

    def test_subscribers_called_for_tool_layer(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e.snapshot.layer))  # noqa: F841
        bus.push_layer("tool")
        bus.publish(["/T"], source="tool", layer="tool")
        assert "tool" in received

    def test_publish_auto_creates_layer(self):
        bus = SelectionBus()
        bus.publish(["/X"], source="test", layer="dynamic")
        assert bus.get_snapshot("dynamic").paths() == ["/X"]


# ---------------------------------------------------------------------------
# Subscription cancellation
# ---------------------------------------------------------------------------


class TestSubscriptionCancellation:
    def test_cancel_stops_notifications(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e))
        bus.publish(["/A"], source="test")
        sub.cancel()
        bus.publish(["/B"], source="test")
        assert len(received) == 1

    def test_double_cancel_doesnt_crash(self):
        bus = SelectionBus()
        sub = bus.subscribe(lambda e: None)
        sub.cancel()
        sub.cancel()  # must not raise

    def test_cancel_doesnt_affect_other_subscribers(self):
        bus = SelectionBus()
        calls1 = []
        calls2 = []
        sub1 = bus.subscribe(lambda e: calls1.append(1))
        sub2 = bus.subscribe(lambda e: calls2.append(2))  # noqa: F841
        sub1.cancel()
        bus.publish(["/A"], source="test")
        assert calls1 == []
        assert calls2 == [2]

    def test_subscription_del_auto_cancels(self):
        bus = SelectionBus()
        received = []

        def cb(event):
            received.append(event)

        sub = bus.subscribe(cb)
        bus.publish(["/A"], source="test")
        del sub
        gc.collect()
        bus.publish(["/B"], source="test")
        assert len(received) == 1


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_instance_returns_same_object(self):
        a = SelectionBus.instance()
        b = SelectionBus.instance()
        assert a is b

    def test_instance_creates_if_none(self):
        assert SelectionBus._instance is None
        bus = SelectionBus.instance()
        assert bus is not None
        assert isinstance(bus, SelectionBus)

    def test_reset_gives_fresh_instance(self):
        bus1 = SelectionBus.instance()
        SelectionBus._instance = None
        bus2 = SelectionBus.instance()
        assert bus1 is not bus2

    def test_singleton_retains_state(self):
        bus = SelectionBus.instance()
        bus.publish(["/A"], source="test")
        assert SelectionBus.instance().get_snapshot().paths() == ["/A"]
