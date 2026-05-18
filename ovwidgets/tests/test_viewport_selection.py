# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ViewportWidget ↔ SelectionBus wiring (Step 44)."""

from omni.ui_scene import scene as sc

from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.viewport.viewport_widget import ViewportWidget


class TrackingRenderer(MockRendererAdapter):
    """MockRendererAdapter that records set_selection_highlight calls."""

    def __init__(self):
        super().__init__()
        self.highlight_calls = []

    def set_selection_highlight(self, paths):
        self.highlight_calls.append(list(paths))


class TestExternalSelectionHighlight:
    def test_bus_selection_calls_set_highlight(self):
        bus = SelectionBus()
        renderer = TrackingRenderer()
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        bus.publish(["/World/Sphere"], source="test")
        assert len(renderer.highlight_calls) == 1
        assert renderer.highlight_calls[0] == ["/World/Sphere"]
        vp.destroy()

    def test_empty_selection_clears_highlight(self):
        bus = SelectionBus()
        renderer = TrackingRenderer()
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        bus.publish([], source="test")
        assert len(renderer.highlight_calls) == 1
        assert renderer.highlight_calls[0] == []
        vp.destroy()

    def test_multiple_paths_passed_to_highlight(self):
        bus = SelectionBus()
        renderer = TrackingRenderer()
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        bus.publish(["/A", "/B", "/C"], source="test")
        assert renderer.highlight_calls[-1] == ["/A", "/B", "/C"]
        vp.destroy()


class TestPickResultToBus:
    def test_pick_result_publishes_to_bus(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e))

        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        # _on_pick → renderer.pick → callback(None, None) → _on_pick_result →
        # bus.publish([], source="viewport")
        vp._on_pick(100.0, 200.0)
        # At least one event received on the bus
        assert len(received) >= 1
        vp.destroy()
        sub.cancel()

    def test_pick_rect_result_publishes_to_bus(self):
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e))

        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick_rect(0.0, 0.0, 10.0, 10.0)
        assert len(received) >= 1
        vp.destroy()
        sub.cancel()


class TestGuardsPreventCircularUpdates:
    def test_pushing_to_bus_skips_highlight(self):
        bus = SelectionBus()
        renderer = TrackingRenderer()
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._pushing_to_bus = True
        bus.publish(["/World/Sphere"], source="test")
        # Guard prevents set_selection_highlight from being called
        assert len(renderer.highlight_calls) == 0
        vp._pushing_to_bus = False
        vp.destroy()

    def test_receiving_from_bus_skips_pick(self):
        bus = SelectionBus()
        renderer = TrackingRenderer()
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._receiving_from_bus = True

        # Intercept bus.publish to detect if viewport pushes
        published = []
        original_publish = bus.publish
        bus.publish = lambda *a, **kw: published.append(a)
        try:
            vp._on_pick(100.0, 200.0)
        finally:
            bus.publish = original_publish

        # Guard should have prevented any bus publish from this pick
        assert published == []
        vp._receiving_from_bus = False
        vp.destroy()

    def test_pushing_flag_resets_after_pick_result(self):
        bus = SelectionBus()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick(100.0, 200.0)
        # Flag must be False after the synchronous pick callback completes
        assert vp._pushing_to_bus is False
        vp.destroy()


class TestViewportHasSceneViewLayer:
    def test_scene_view_none_before_build(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        assert vp._scene_view is None
        vp.destroy()

    def test_scene_view_created_after_build(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert vp._scene_view is not None
        vp.destroy()

    def test_scene_view_is_scene_view_type(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert isinstance(vp._scene_view, sc.SceneView)
        vp.destroy()
