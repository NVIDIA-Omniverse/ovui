# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Stage Browser selection bus path handoff."""

from __future__ import annotations

import pytest

from ovui_widgets.common.selection import SelectionBus, SelectionItem
from ovui_widgets.common.testing.mock_stage import MockStageAdapter
from ovui_widgets.stage.stage_widget import StageWidget


@pytest.fixture(autouse=True)
def reset_selection_bus():
    SelectionBus._instance = None
    yield
    SelectionBus._instance = None


def test_stage_row_selection_publishes_only_common_selection_records() -> None:
    adapter = MockStageAdapter()
    bus = SelectionBus.instance()
    widget = StageWidget(adapter=adapter, selection_bus=bus)
    events = []
    sub = bus.subscribe(events.append)

    try:
        root = widget._model.get_item_children(None)[0]
        geometry = widget._model.get_item_children(root)[0]

        widget._on_tree_selection_changed([geometry])

        snapshot = events[-1].snapshot
        assert snapshot.paths() == ["/World/Geometry"]
        assert snapshot.items == (
            SelectionItem(path="/World/Geometry", source="stage"),
        )
        assert not hasattr(snapshot.items[0], "adapter_item")
    finally:
        sub.cancel()
        widget.destroy()


def test_programmatic_selection_publishes_only_paths_that_resolve() -> None:
    adapter = MockStageAdapter()
    bus = SelectionBus.instance()
    widget = StageWidget(adapter=adapter, selection_bus=bus)
    events = []
    sub = bus.subscribe(events.append)

    try:
        widget.set_selection([
            "/World/Geometry/Sphere",
            "/World/Geometry/Missing",
        ])

        assert widget.get_selection() == ["/World/Geometry/Sphere"]
        assert events[-1].snapshot.paths() == ["/World/Geometry/Sphere"]
        assert events[-1].snapshot.items == (
            SelectionItem(path="/World/Geometry/Sphere", source="stage"),
        )
    finally:
        sub.cancel()
        widget.destroy()


def test_external_saved_path_reselects_stage_row_when_it_still_exists() -> None:
    adapter = MockStageAdapter()
    bus = SelectionBus.instance()
    widget = StageWidget(adapter=adapter, selection_bus=bus)

    try:
        bus.publish(["/World/Geometry/Cube"], source="viewport")

        assert widget.get_selection() == ["/World/Geometry/Cube"]
        assert widget._model._selected_items[0].adapter_item is adapter.get_item_at_path(
            "/World/Geometry/Cube"
        )
    finally:
        widget.destroy()


def test_external_stale_saved_path_does_not_leave_selected_row() -> None:
    adapter = MockStageAdapter()
    bus = SelectionBus.instance()
    widget = StageWidget(adapter=adapter, selection_bus=bus)

    try:
        bus.publish(["/World/Geometry/Missing"], source="viewport")

        assert widget.get_selection() == []
        assert widget._model._selected_items == []
    finally:
        widget.destroy()
