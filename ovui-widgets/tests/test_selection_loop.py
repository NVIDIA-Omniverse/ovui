# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 52: SelectionBus re-entrancy and three-way loop validation.

Validates that the stage-browser ↔ bus ↔ viewport selection loop cannot
produce circular updates or infinite recursion.
"""
import pytest

from ovui_widgets.common.selection import SelectionBus, SelectionBusError


@pytest.fixture(autouse=True)
def reset_singleton():
    SelectionBus._instance = None
    yield
    SelectionBus._instance = None


class TestReentrancyProtection:
    def test_reentrant_push_no_infinite_loop(self):
        """Subscriber pushing back during dispatch does not cause infinite recursion."""
        bus = SelectionBus()
        call_count = [0]

        def sub(event):
            call_count[0] += 1
            try:
                bus.publish(["/back"], source="sub")  # reentrant — blocked
            except SelectionBusError:
                pass  # expected; no infinite loop

        s = bus.subscribe(sub)  # noqa: F841 — keep ref to prevent RAII cancel
        bus.publish(["/A"], source="test")
        assert call_count[0] == 1  # fired exactly once, not recursively

    def test_subscriber_pushback_fires_each_subscriber_once(self):
        """Subscriber A pushes back; all subscribers fire exactly once per publish."""
        bus = SelectionBus()
        calls = []

        def sub_a(event):
            calls.append("a")
            try:
                bus.publish(["/back"], source="a")
            except SelectionBusError:
                pass

        def sub_b(event):
            calls.append("b")

        sa = bus.subscribe(sub_a)  # noqa: F841
        sb = bus.subscribe(sub_b)  # noqa: F841
        bus.publish(["/A"], source="test")
        assert calls.count("a") == 1
        assert calls.count("b") == 1

    def test_multiple_subscribers_fire_exactly_once(self):
        """All N subscribers fire in order exactly once per publish call."""
        bus = SelectionBus()
        calls = []
        subs = [bus.subscribe(lambda e, n=i: calls.append(n)) for i in range(5)]  # noqa: F841
        bus.publish(["/X"], source="test")
        assert calls == [0, 1, 2, 3, 4]

    def test_empty_selection_push_works(self):
        """Publishing an empty path list succeeds and notifies subscribers."""
        bus = SelectionBus()
        received = []
        s = bus.subscribe(lambda e: received.append(e.snapshot.paths()))  # noqa: F841
        bus.publish([], source="test")
        assert received == [[]]

    def test_dispatch_flag_resets_after_subscriber_exception(self):
        """_publishing resets in finally so next publish succeeds after subscriber error."""
        bus = SelectionBus()
        raised = [False]

        def bad_sub(event):
            raised[0] = True
            raise ValueError("subscriber error")

        sub = bus.subscribe(bad_sub)
        try:
            bus.publish(["/A"], source="test")
        except ValueError:
            pass

        assert raised[0]
        assert bus._publishing is False  # finally block reset it

        # Cancel bad subscriber; verify subsequent publish reaches good subscriber
        sub.cancel()
        received = []
        s2 = bus.subscribe(lambda e: received.append(e))  # noqa: F841
        bus.publish(["/B"], source="test")
        assert len(received) == 1


class TestThreeWayLoopValidation:
    """Validate that source-based filtering prevents circular selection updates."""

    def test_hierarchy_subscriber_skips_own_source(self):
        """Stage-browser widget ignores events it originated (source='hierarchy')."""
        bus = SelectionBus()
        update_count = [0]

        def hierarchy_sub(event):
            if event.source == "hierarchy":
                return  # skip own events, no re-publish
            update_count[0] += 1

        s = bus.subscribe(hierarchy_sub)  # noqa: F841
        bus.publish(["/World/Cube"], source="hierarchy")
        assert update_count[0] == 0  # own event was filtered out

    def test_viewport_subscriber_skips_own_source(self):
        """Viewport widget ignores events it originated (source='viewport')."""
        bus = SelectionBus()
        highlight_count = [0]

        def viewport_sub(event):
            if event.source == "viewport":
                return
            highlight_count[0] += 1

        s = bus.subscribe(viewport_sub)  # noqa: F841
        bus.publish(["/World/Sphere"], source="viewport")
        assert highlight_count[0] == 0  # own event was filtered out

    def test_property_panel_is_read_only(self):
        """Property panel subscribes but never publishes — receives all events safely."""
        bus = SelectionBus()
        highlights = []

        def property_sub(event):
            highlights.append(event.snapshot.paths())
            # property panel does NOT publish back

        s = bus.subscribe(property_sub)  # noqa: F841
        bus.publish(["/World/Cube"], source="stage")
        bus.publish(["/World/Sphere"], source="viewport")
        assert highlights == [["/World/Cube"], ["/World/Sphere"]]

    def test_cross_source_events_reach_other_subscribers(self):
        """Event from hierarchy reaches viewport and property subscribers."""
        bus = SelectionBus()
        viewport_received = []
        property_received = []

        def hierarchy_sub(event):
            if event.source == "hierarchy":
                return

        def viewport_sub(event):
            if event.source != "viewport":
                viewport_received.append(event.snapshot.paths())

        def property_sub(event):
            property_received.append(event.snapshot.paths())

        sh = bus.subscribe(hierarchy_sub)  # noqa: F841
        sv = bus.subscribe(viewport_sub)   # noqa: F841
        sp = bus.subscribe(property_sub)   # noqa: F841

        bus.publish(["/World/Cube"], source="hierarchy")
        assert viewport_received == [["/World/Cube"]]
        assert property_received == [["/World/Cube"]]

    def test_reentrant_guard_resets_between_publishes(self):
        """After a publish completes, the guard clears so the next publish works."""
        bus = SelectionBus()
        received = []
        s = bus.subscribe(lambda e: received.append(e.snapshot.paths()))  # noqa: F841
        bus.publish(["/A"], source="s")
        bus.publish(["/B"], source="s")
        assert received == [["/A"], ["/B"]]
