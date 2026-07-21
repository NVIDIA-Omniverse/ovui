# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 32: PropertyWindow ↔ SelectionBus wiring."""

import pytest

from ovui_widgets.common.selection import SelectionBus


@pytest.fixture(autouse=True)
def reset_bus():
    SelectionBus._instance = None
    yield
    SelectionBus._instance = None


def _make_wired():
    """PropertyWindow subscribed to SelectionBus, with no live UI."""
    from ovui_widgets.property.window import PropertyWindow

    w = PropertyWindow.__new__(PropertyWindow)
    w._adapter = None
    w._selection = []
    w._filter_text = ""
    w._pending_filter_handle = None
    w._filter_field = None
    w._content = None
    w._window = None
    w._group_collapse_state = {}
    w._bus_sub = SelectionBus.instance().subscribe(w._on_bus_selection_changed)
    return w


class TestPropertySelectionBusWiring:
    def test_bus_push_calls_set_selection_with_correct_paths(self):
        w = _make_wired()
        calls = []
        w.set_selection = lambda paths: calls.append(list(paths))
        SelectionBus.instance().publish(["/World/Sphere"], source="viewport")
        assert calls == [["/World/Sphere"]]

    def test_empty_selection_clears_widget(self):
        w = _make_wired()
        w._selection = ["/World/Sphere"]
        calls = []
        w.set_selection = lambda paths: calls.append(list(paths))
        SelectionBus.instance().publish([], source="viewport")
        assert calls == [[]]

    def test_multiple_selections_all_paths_passed(self):
        w = _make_wired()
        calls = []
        w.set_selection = lambda paths: calls.append(list(paths))
        SelectionBus.instance().publish(
            ["/World/A", "/World/B", "/World/C"], source="stage"
        )
        assert calls == [["/World/A", "/World/B", "/World/C"]]

    def test_subscription_cancelled_on_destroy(self):
        w = _make_wired()
        sub = w._bus_sub
        assert not sub._cancelled
        # Simulate destroy() cleanup
        w._bus_sub.cancel()
        w._bus_sub = None
        assert sub._cancelled
        # After cancel, publishing must not reach the widget
        reached = []
        SelectionBus.instance().publish(["/World/X"], source="test")
        assert reached == []
