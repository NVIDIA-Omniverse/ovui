# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Viewport frame-selection, pick, and highlight sync through SelectionBus."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
from ovui_widgets.viewport.viewport_widget import ViewportWidget


class _Item:
    def __init__(
        self,
        path: str,
        category: str = "Mesh",
        children: tuple["_Item", ...] = (),
    ) -> None:
        self.path = path
        self.category = category
        self.children = tuple(children)


class _StageAdapter:
    def __init__(self) -> None:
        self.mesh = _Item("/World/Group/Cube", "Mesh")
        self.group = _Item("/World/Group", "Xform", (self.mesh,))
        self.items = {
            self.group.path: self.group,
            self.mesh.path: self.mesh,
        }
        self.compute_requests: list[list[str]] = []

    def get_item_at_path(self, path: str) -> Optional[_Item]:
        return self.items.get(str(path))

    def get_type_category(self, item: _Item) -> str:
        return item.category

    def get_item_path(self, item: _Item) -> str:
        return item.path

    def get_children(self, item: _Item) -> list[_Item]:
        return list(item.children)

    def compute_world_aabb(self, paths: list[str]) -> Any:
        self.compute_requests.append(list(paths))
        if paths == [self.group.path]:
            return ((-1.0, -2.0, -3.0), (3.0, 4.0, 5.0))
        return None


class _PickRenderer(MockRendererAdapter):
    def __init__(self, path: str | None) -> None:
        super().__init__()
        self.path = path
        self.highlight_calls: list[list[str]] = []

    def pick(self, x, y, callback, query_name):  # type: ignore[override]
        callback(self.path, (0.0, 0.0, 0.0) if self.path else None)

    def pick_rect(self, x0, y0, x1, y1, callback):  # type: ignore[override]
        callback([self.path] if self.path else [])

    def set_selection_highlight(self, paths):  # type: ignore[override]
        self.highlight_calls.append(list(paths))


def test_frame_paths_uses_stage_adapter_computed_selection_bounds() -> None:
    stage = _StageAdapter()
    renderer = _PickRenderer(None)
    viewport = ViewportWidget(
        services=None,
        renderer=renderer,
        stage_adapter_provider=lambda: stage,
    )
    try:
        assert viewport.frame_paths(["/World/Group"]) is True
        assert stage.compute_requests == [["/World/Group"]]
        assert viewport._camera.state.target == pytest.approx([1.0, 1.0, 1.0])
        assert viewport._camera.state.distance == pytest.approx(16.0)
    finally:
        viewport.destroy()


def test_pick_result_is_validated_before_entering_common_selection_bus() -> None:
    stage = _StageAdapter()
    bus = SelectionBus()
    renderer = _PickRenderer("/World/Missing")
    viewport = ViewportWidget(
        services=None,
        renderer=renderer,
        bus=bus,
        stage_adapter_provider=lambda: stage,
    )
    try:
        viewport._on_pick(0.0, 0.0)
        assert bus.get_snapshot().paths() == []
        assert renderer.highlight_calls[-1] == []

        renderer.path = "/World/Group/Cube"
        viewport._on_pick(0.0, 0.0)
        assert bus.get_snapshot().paths() == ["/World/Group/Cube"]
        assert renderer.highlight_calls[-1] == ["/World/Group/Cube"]
    finally:
        viewport.destroy()


def test_empty_point_pick_clears_common_selection_and_highlight() -> None:
    stage = _StageAdapter()
    bus = SelectionBus()
    renderer = _PickRenderer(None)
    viewport = ViewportWidget(
        services=None,
        renderer=renderer,
        bus=bus,
        stage_adapter_provider=lambda: stage,
    )
    try:
        bus.publish(["/World/Group/Cube"], source="stage-browser")
        assert bus.get_snapshot().paths() == ["/World/Group/Cube"]
        assert renderer.highlight_calls[-1] == ["/World/Group/Cube"]

        viewport._on_pick(0.0, 0.0)

        assert bus.get_snapshot().paths() == []
        assert renderer.highlight_calls[-1] == []
    finally:
        viewport.destroy()


def test_marquee_pick_validates_paths_and_common_bus_clears_highlight() -> None:
    stage = _StageAdapter()
    bus = SelectionBus()
    renderer = _PickRenderer("/World/Group/Cube")
    viewport = ViewportWidget(
        services=None,
        renderer=renderer,
        bus=bus,
        stage_adapter_provider=lambda: stage,
    )
    try:
        viewport._on_pick_rect(-0.25, 0.25, 0.25, -0.25)
        assert bus.get_snapshot().paths() == ["/World/Group/Cube"]
        assert renderer.highlight_calls[-1] == ["/World/Group/Cube"]

        bus.clear()
        assert bus.get_snapshot().paths() == []
        assert renderer.highlight_calls[-1] == []
    finally:
        viewport.destroy()


def test_group_selection_highlight_expands_to_renderable_mesh_children() -> None:
    stage = _StageAdapter()
    bus = SelectionBus()
    renderer = _PickRenderer(None)
    viewport = ViewportWidget(
        services=None,
        renderer=renderer,
        bus=bus,
        stage_adapter_provider=lambda: stage,
    )
    try:
        bus.publish(["/World/Group"], source="stage-browser")

        assert renderer.highlight_calls[-1] == ["/World/Group/Cube"]
    finally:
        viewport.destroy()
