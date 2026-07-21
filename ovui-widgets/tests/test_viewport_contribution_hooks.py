# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for generic viewport contribution hooks."""

from __future__ import annotations

from types import SimpleNamespace

from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
from ovui_widgets.viewport.viewport_hooks import (
    ViewportAnchoredPanel,
    ViewportContributionRegistry,
    ViewportFrameContext,
    ViewportOverlay,
    ViewportOutputPreset,
    ViewportPointCloudRenderer,
    ViewportProbeContext,
    ViewportProbeResult,
    ViewportProbeTool,
)
from ovui_widgets.viewport.viewport_widget import ViewportWidget


class _VisibleViewportImage:
    visible = True
    computed_width = 640
    computed_height = 360


def test_viewport_frame_contributions_order_capabilities_and_lifecycle():
    owner = object()
    lifecycle = []
    updates = []
    registry = ViewportContributionRegistry(owner)

    first = ViewportPointCloudRenderer(
        id="renderer.first",
        label="First",
        order=20,
        capabilities=("frame",),
        update_fn=lambda context: updates.append(("first", context.owner)),
        on_add=lambda received_owner: lifecycle.append(("add.first", received_owner)),
        on_remove=lambda received_owner: lifecycle.append(("remove.first", received_owner)),
    )
    before_first = ViewportPointCloudRenderer(
        id="renderer.before",
        label="Before",
        order=100,
        before="renderer.first",
        capabilities=("frame",),
        update_fn=lambda context: updates.append(("before", context.owner)),
    )
    blocked = ViewportPointCloudRenderer(
        id="renderer.blocked",
        label="Blocked",
        order=0,
        capabilities=("missing",),
        update_fn=lambda context: updates.append(("blocked", context.owner)),
    )

    handle = registry.add(first)
    second_handle = registry.add(first)
    registry.add(before_first)
    registry.add(blocked)

    assert handle.id == second_handle.id == "renderer.first"
    assert lifecycle == [("add.first", owner)]

    context = ViewportFrameContext(
        owner=owner,
        width=640,
        height=360,
        render_dt=0.1,
        view_matrix="view",
        projection_matrix="projection",
    )
    registry.update_frame(context)
    assert updates == []

    registry.set_capability("frame")
    registry.update_frame(context)
    assert updates == [("before", owner), ("first", owner)]

    assert handle.remove() is True
    assert handle.remove() is False
    assert lifecycle == [("add.first", owner), ("remove.first", owner)]


def test_viewport_output_preset_order_capabilities_and_failure_isolation():
    owner = object()
    registry = ViewportContributionRegistry(owner)
    updates = []

    registry.add(
        ViewportOutputPreset(
            id="output.blocked",
            label="Blocked",
            order=0,
            capabilities=("missing",),
            update_fn=lambda context: updates.append("blocked"),
        )
    )
    registry.add(
        ViewportOutputPreset(
            id="output.bad",
            label="Bad",
            order=10,
            capabilities=("display",),
            update_fn=lambda context: (_ for _ in ()).throw(RuntimeError("bad")),
        )
    )
    registry.add(
        ViewportOutputPreset(
            id="output.after",
            label="After",
            order=0,
            after="output.before",
            capabilities=("display",),
            update_fn=lambda context: updates.append(
                ("after", context.image_bridge, context.image_frame)
            ),
        )
    )
    registry.add(
        ViewportOutputPreset(
            id="output.before",
            label="Before",
            order=100,
            capabilities=("display",),
            update_fn=lambda context: updates.append(
                ("before", context.image_bridge, context.image_frame)
            ),
        )
    )
    context = ViewportFrameContext(
        owner=owner,
        width=320,
        height=180,
        render_dt=0.25,
        view_matrix="view",
        projection_matrix="projection",
        image_frame="frame",
        image_bridge="bridge",
    )

    registry.update_frame(context)
    assert updates == []

    registry.set_capability("display")
    registry.update_frame(context)

    assert updates == [
        ("before", "bridge", "frame"),
        ("after", "bridge", "frame"),
    ]
    assert "output.bad" in registry.failures


def test_viewport_overlay_and_panel_contexts_and_failure_isolation():
    owner = object()
    registry = ViewportContributionRegistry(owner)
    seen = []

    registry.add(
        ViewportOverlay(
            id="overlay.bad",
            label="Bad Overlay",
            order=0,
            build_fn=lambda context: (_ for _ in ()).throw(RuntimeError("overlay")),
        )
    )
    registry.add(
        ViewportOverlay(
            id="overlay.good",
            label="Good Overlay",
            order=1,
            build_fn=lambda context: seen.append(
                ("overlay", context.owner, context.scene_view, context.scene)
            ),
        )
    )
    registry.add(
        ViewportAnchoredPanel(
            id="panel.bad",
            label="Bad Panel",
            anchor="top_right",
            order=0,
            build_fn=lambda context: (_ for _ in ()).throw(RuntimeError("panel")),
        )
    )
    registry.add(
        ViewportAnchoredPanel(
            id="panel.good",
            label="Good Panel",
            anchor="bottom_right",
            order=1,
            build_fn=lambda context: seen.append(
                ("panel", context.owner, context.ui_module, context.anchor)
            ),
        )
    )

    scene_view = SimpleNamespace(scene="scene")
    ui_module = object()
    registry.build_overlays(scene_view)
    registry.build_anchored_panels(ui_module)

    assert "overlay.bad" in registry.failures
    assert "panel.bad" in registry.failures
    assert seen == [
        ("overlay", owner, scene_view, "scene"),
        ("panel", owner, ui_module, "bottom_right"),
    ]


def test_viewport_probe_tool_results_capabilities_order_and_failure_isolation():
    owner = object()
    registry = ViewportContributionRegistry(owner, capabilities=("probe",))
    seen = []

    registry.add(
        ViewportProbeTool(
            id="probe.blocked",
            label="Blocked",
            capabilities=("missing",),
            probe_fn=lambda context: seen.append("blocked"),
        )
    )
    registry.add(
        ViewportProbeTool(
            id="probe.bad",
            label="Bad",
            order=0,
            capabilities=("probe",),
            probe_fn=lambda context: (_ for _ in ()).throw(RuntimeError("probe")),
        )
    )
    registry.add(
        ViewportProbeTool(
            id="probe.second",
            label="Second",
            order=20,
            capabilities=("probe",),
            probe_fn=lambda context: [
                ViewportProbeResult(
                    id="readout.second",
                    label="Second",
                    text=f"{context.normalized_x:.1f}",
                )
            ],
        )
    )
    registry.add(
        ViewportProbeTool(
            id="probe.first",
            label="First",
            before="probe.second",
            order=100,
            capabilities=("probe",),
            probe_fn=lambda context: ViewportProbeResult(
                id="readout.first",
                label="First",
                text=f"{context.x:.0f},{context.y:.0f}",
            ),
        )
    )

    results = registry.probe(
        ViewportProbeContext(
            owner=owner,
            x=10,
            y=20,
            width=100,
            height=50,
            normalized_x=0.1,
            normalized_y=0.4,
        )
    )

    assert seen == []
    assert [result.id for result in results] == [
        "readout.first",
        "readout.second",
    ]
    assert [result.text for result in results] == ["10,20", "0.1"]
    assert "probe.bad" in registry.failures


def test_viewport_widget_exposes_isolated_hooks_and_runs_frame_contributions():
    first = ViewportWidget(services=None, renderer=MockRendererAdapter())
    second = ViewportWidget(services=None, renderer=MockRendererAdapter())
    first._image = _VisibleViewportImage()
    second._image = _VisibleViewportImage()
    updates = []
    lifecycle = []
    probe_contexts = []

    try:
        assert first.viewport_hooks is not second.viewport_hooks
        first.viewport_hooks.add(
            ViewportPointCloudRenderer(
                id="renderer.tick",
                label="Tick",
                update_fn=lambda context: updates.append(context),
                on_remove=lambda owner: lifecycle.append(("remove", owner)),
            )
        )
        first.viewport_hooks.add(
            ViewportOutputPreset(
                id="output.tick",
                label="Output Tick",
                update_fn=lambda context: updates.append(("output", context)),
                on_remove=lambda owner: lifecycle.append(("remove.output", owner)),
            )
        )
        first.viewport_hooks.add(
            ViewportProbeTool(
                id="probe.pixel",
                label="Probe",
                probe_fn=lambda context: (
                    probe_contexts.append(context)
                    or ViewportProbeResult(id="pixel", text="value")
                ),
            )
        )

        assert first.render(0.1) is True
        assert second.render(0.1) is True

        assert len(updates) == 2
        context = updates[0]
        assert context.owner is first
        assert context.width == 640
        assert context.height == 360
        assert context.render_dt == 0.1
        assert context.image_frame is not None
        assert context.image_bridge is first._bridge
        assert updates[1][0] == "output"
        assert updates[1][1].image_bridge is first._bridge

        results = first.probe_viewport(320, 180)
        assert [result.text for result in results] == ["value"]
        probe_context = probe_contexts[0]
        assert probe_context.owner is first
        assert probe_context.width == 640
        assert probe_context.height == 360
        assert probe_context.x == 320
        assert probe_context.y == 180
        assert probe_context.image_frame is context.image_frame
        assert 0.50 < probe_context.normalized_x < 0.51
        assert 0.50 < probe_context.normalized_y < 0.51
    finally:
        first.destroy()
        second.destroy()

    assert lifecycle == [("remove.output", first), ("remove", first)]
