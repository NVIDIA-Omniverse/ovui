# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for A3-T08 effective-dimension coordinate mapping."""

from __future__ import annotations

import numpy as np
import pytest

from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
from ovui_widgets.viewport import (
    AREA3_INTERACTION_QA_ENV,
    RESOLUTION_MODE_FIXED,
    ViewportResolutionStateError,
    ViewportWidget,
    apply_aspect_fit_projection_transform,
    compute_aspect_fit_display_rect,
    compute_aspect_fit_ndc_transform,
    map_widget_ndc_rect_to_render_ndc_rect,
    map_widget_ndc_to_render_ndc,
    render_ndc_to_widget_ndc,
)


class _VisibleImage:
    visible = True

    def __init__(self, width: int, height: int) -> None:
        self.computed_width = width
        self.computed_height = height


class _FakeSceneView:
    view = None
    projection = None


class _RecordingPickRenderer(MockRendererAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.pick_calls: list[tuple[float, float, str]] = []
        self.pick_rect_calls: list[tuple[float, float, float, float]] = []
        self.cancel_pick_calls: list[str] = []
        self.highlight_calls: list[list[str]] = []
        self.next_pick_path = "/World/Cube"
        self.next_rect_paths = ["/World/Cube"]

    def render_frame(self, width, height, view_matrix, proj_matrix):
        self.set_resolution(int(width), int(height))
        return np.zeros((int(height), int(width), 4), dtype=np.uint8)

    def pick(self, x, y, callback, query_name):
        self.pick_calls.append((float(x), float(y), str(query_name)))
        callback(self.next_pick_path, (0.0, 0.0, 0.0))

    def pick_rect(self, x0, y0, x1, y1, callback):
        self.pick_rect_calls.append((float(x0), float(y0), float(x1), float(y1)))
        callback(list(self.next_rect_paths))

    def cancel_pick(self, query_name):
        self.cancel_pick_calls.append(str(query_name))

    def set_selection_highlight(self, paths):
        self.highlight_calls.append(list(paths))
        super().set_selection_highlight(paths)


def _widget_ndc_from_pixel(
    x: float,
    y: float,
    frame_size: tuple[int, int],
) -> tuple[float, float]:
    return (
        x / frame_size[0] * 2.0 - 1.0,
        1.0 - y / frame_size[1] * 2.0,
    )


def _rendered_square_viewport() -> tuple[ViewportWidget, _RecordingPickRenderer]:
    renderer = _RecordingPickRenderer()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(1600, 900)
    viewport.set_resolution_state(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1024, 1024),
        scale=1.0,
        fill_viewport=False,
        selected_label="Square",
    )
    assert viewport.render(0.1) is True
    assert viewport.get_resolution_state().effective_size == (1024, 1024)
    return viewport, renderer


def test_square_render_in_wide_widget_uses_centered_pillarbox_rect() -> None:
    rect = compute_aspect_fit_display_rect((1600, 900), (1024, 1024))

    assert rect.width == pytest.approx(900.0)
    assert rect.height == pytest.approx(900.0)
    assert rect.x == pytest.approx(350.0)
    assert rect.y == pytest.approx(0.0)
    assert rect.pillarbox_left == pytest.approx(350.0)
    assert rect.pillarbox_right == pytest.approx(350.0)
    assert rect.letterbox_top == pytest.approx(0.0)
    assert rect.letterbox_bottom == pytest.approx(0.0)


def test_widget_center_maps_to_effective_render_center() -> None:
    mapping = map_widget_ndc_to_render_ndc(0.0, 0.0, (1600, 900), (1024, 1024))

    assert mapping is not None
    assert mapping.widget_pixel == pytest.approx((800.0, 450.0))
    assert mapping.render_pixel == pytest.approx((512.0, 512.0))
    assert mapping.render_ndc == pytest.approx((0.0, 0.0))


@pytest.mark.parametrize("pixel_x", [100.0, 1300.0])
def test_pillarbox_clicks_are_outside_the_effective_render(pixel_x: float) -> None:
    ndc = _widget_ndc_from_pixel(pixel_x, 450.0, (1600, 900))

    assert map_widget_ndc_to_render_ndc(*ndc, (1600, 900), (1024, 1024)) is None


def test_wide_render_in_tall_widget_uses_letterbox_offsets() -> None:
    rect = compute_aspect_fit_display_rect((900, 1600), (1920, 1080))

    assert rect.width == pytest.approx(900.0)
    assert rect.height == pytest.approx(506.25)
    assert rect.x == pytest.approx(0.0)
    assert rect.y == pytest.approx(546.875)
    assert rect.letterbox_top == pytest.approx(546.875)
    assert rect.letterbox_bottom == pytest.approx(546.875)


def test_marquee_rect_is_clipped_to_aspect_fit_display_rect() -> None:
    left_ndc = _widget_ndc_from_pixel(300.0, 100.0, (1600, 900))
    right_ndc = _widget_ndc_from_pixel(800.0, 800.0, (1600, 900))

    mapped = map_widget_ndc_rect_to_render_ndc_rect(
        left_ndc[0],
        left_ndc[1],
        right_ndc[0],
        right_ndc[1],
        (1600, 900),
        (1024, 1024),
    )

    assert mapped is not None
    assert mapped[0] == pytest.approx(-1.0)
    assert mapped[1] == pytest.approx(1.0 - (100.0 / 900.0) * 2.0)
    assert mapped[2] == pytest.approx(0.0)
    assert mapped[3] == pytest.approx(1.0 - (800.0 / 900.0) * 2.0)


def test_marquee_rect_outside_display_rect_does_not_map_to_render() -> None:
    a = _widget_ndc_from_pixel(10.0, 100.0, (1600, 900))
    b = _widget_ndc_from_pixel(100.0, 800.0, (1600, 900))

    assert (
        map_widget_ndc_rect_to_render_ndc_rect(
            a[0],
            a[1],
            b[0],
            b[1],
            (1600, 900),
            (1024, 1024),
        )
        is None
    )


def test_render_ndc_to_widget_ndc_places_annotations_in_aspect_fit_rect() -> None:
    center = render_ndc_to_widget_ndc(0.0, 0.0, (1600, 900), (1024, 1024))
    left_edge = render_ndc_to_widget_ndc(-1.0, 0.0, (1600, 900), (1024, 1024))
    right_edge = render_ndc_to_widget_ndc(1.0, 0.0, (1600, 900), (1024, 1024))

    assert center == pytest.approx((0.0, 0.0))
    assert left_edge[0] == pytest.approx(350.0 / 1600.0 * 2.0 - 1.0)
    assert right_edge[0] == pytest.approx(1250.0 / 1600.0 * 2.0 - 1.0)


def test_aspect_fit_ndc_transform_compresses_overlay_into_display_rect() -> None:
    transform = compute_aspect_fit_ndc_transform((1600, 900), (1024, 1024))
    projection = np.identity(4, dtype=np.float64)
    transformed = apply_aspect_fit_projection_transform(
        projection,
        (1600, 900),
        (1024, 1024),
    )

    assert transform.scale_x == pytest.approx(900.0 / 1600.0)
    assert transform.scale_y == pytest.approx(1.0)
    assert transform.offset_x == pytest.approx(0.0)
    assert transform.offset_y == pytest.approx(0.0)
    assert transformed[0, 0] == pytest.approx(900.0 / 1600.0)
    assert transformed[1, 1] == pytest.approx(1.0)
    assert transformed[0, 3] == pytest.approx(0.0)
    assert transformed[1, 3] == pytest.approx(0.0)


def test_invalid_coordinate_sizes_raise() -> None:
    with pytest.raises(ViewportResolutionStateError):
        compute_aspect_fit_display_rect((1600, 900), (0, 1024))


def test_viewport_camera_and_handle_size_use_effective_dimensions() -> None:
    viewport, _renderer = _rendered_square_viewport()
    try:
        assert viewport._get_raw_viewport_frame_size() == (1600, 900)
        assert viewport._get_viewport_size() == (1024, 1024)
    finally:
        viewport.destroy()


def test_scene_overlay_projection_uses_aspect_fit_display_rect() -> None:
    viewport, _renderer = _rendered_square_viewport()
    try:
        view, projection = viewport._camera.get_matrices(1024, 1024)
        transformed = apply_aspect_fit_projection_transform(
            projection,
            (1600, 900),
            (1024, 1024),
        )

        assert transformed[0, 0] == pytest.approx(
            projection[0, 0] * (900.0 / 1600.0)
        )
        assert transformed[1, 1] == pytest.approx(projection[1, 1])
        assert viewport._get_viewport_size() == (1024, 1024)
        assert view.shape == (4, 4)
    finally:
        viewport.destroy()


def test_render_sets_scene_overlay_projection_for_aspect_fit_rect() -> None:
    renderer = _RecordingPickRenderer()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(1600, 900)
    viewport._scene_view = _FakeSceneView()
    viewport.set_resolution_state(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1024, 1024),
        scale=1.0,
        fill_viewport=False,
        selected_label="Square",
    )
    try:
        assert viewport.render(0.1) is True
        assert viewport._scene_view.projection is not None

        _view, projection = viewport._camera.get_matrices(1024, 1024)
        expected = apply_aspect_fit_projection_transform(
            projection,
            (1600, 900),
            (1024, 1024),
        )
        observed = np.array(viewport._scene_view.projection).reshape(4, 4).T

        assert observed[0, 0] == pytest.approx(expected[0, 0])
        assert observed[1, 1] == pytest.approx(expected[1, 1])
        assert observed[0, 3] == pytest.approx(expected[0, 3])
        assert observed[1, 3] == pytest.approx(expected[1, 3])
    finally:
        viewport.destroy()


def test_point_pick_inside_square_maps_to_effective_render_ndc() -> None:
    bus = SelectionBus()
    renderer = _RecordingPickRenderer()
    viewport = ViewportWidget(services=None, renderer=renderer, bus=bus)
    viewport._image = _VisibleImage(1600, 900)
    viewport.set_resolution_state(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1024, 1024),
        scale=1.0,
        fill_viewport=False,
        selected_label="Square",
    )
    try:
        assert viewport.render(0.1) is True
        viewport._on_pick(0.0, 0.0, "replace")

        assert renderer.pick_calls == [(0.0, 0.0, "viewport_click")]
        assert [item.path for item in bus.get_snapshot().items] == ["/World/Cube"]
        assert renderer.highlight_calls[-1] == ["/World/Cube"]
    finally:
        viewport.destroy()


def test_point_pick_in_side_spacing_does_not_reach_renderer_or_clear_selection() -> None:
    bus = SelectionBus()
    renderer = _RecordingPickRenderer()
    viewport = ViewportWidget(services=None, renderer=renderer, bus=bus)
    viewport._image = _VisibleImage(1600, 900)
    viewport.set_resolution_state(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1024, 1024),
        scale=1.0,
        fill_viewport=False,
        selected_label="Square",
    )
    side_ndc = _widget_ndc_from_pixel(100.0, 450.0, (1600, 900))
    try:
        assert viewport.render(0.1) is True
        viewport._on_pick(0.0, 0.0, "replace")
        assert [item.path for item in bus.get_snapshot().items] == ["/World/Cube"]

        viewport._on_pick(side_ndc[0], side_ndc[1], "replace")

        assert len(renderer.pick_calls) == 1
        assert [item.path for item in bus.get_snapshot().items] == ["/World/Cube"]
    finally:
        viewport.destroy()


def test_rect_pick_uses_clipped_effective_render_bounds() -> None:
    bus = SelectionBus()
    renderer = _RecordingPickRenderer()
    viewport = ViewportWidget(services=None, renderer=renderer, bus=bus)
    viewport._image = _VisibleImage(1600, 900)
    viewport.set_resolution_state(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1024, 1024),
        scale=1.0,
        fill_viewport=False,
        selected_label="Square",
    )
    a = _widget_ndc_from_pixel(300.0, 100.0, (1600, 900))
    b = _widget_ndc_from_pixel(800.0, 800.0, (1600, 900))
    try:
        assert viewport.render(0.1) is True
        viewport._on_pick_rect(a[0], a[1], b[0], b[1], "replace")

        assert len(renderer.pick_rect_calls) == 1
        x0, y0, x1, y1 = renderer.pick_rect_calls[0]
        assert (x0, y0, x1, y1) == pytest.approx(
            (
                -1.0,
                1.0 - (100.0 / 900.0) * 2.0,
                0.0,
                1.0 - (800.0 / 900.0) * 2.0,
            )
        )
        assert [item.path for item in bus.get_snapshot().items] == ["/World/Cube"]
    finally:
        viewport.destroy()


def test_area3_interaction_qa_controls_are_env_gated(monkeypatch) -> None:
    monkeypatch.setenv(AREA3_INTERACTION_QA_ENV, "1")
    renderer = _RecordingPickRenderer()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(1600, 900)
    monkeypatch.setattr(viewport, "_detect_resolution_dpi_scale", lambda: (True, 1.0))
    try:
        viewport._apply_resolution_render_qa_interaction_square_fill_off()
        assert viewport.render(0.1) is True
        assert viewport.get_resolution_state().effective_size == (1024, 1024)
        assert viewport._resolution_render_qa_frame_size == (1600, 900)
        assert "aspect-fit display" in viewport._resolution_render_qa_status_message

        viewport._apply_resolution_render_qa_interaction_fill_on()
        assert viewport.render(0.1) is True
        state = viewport.get_resolution_state()
        expected_fill_size = (int(1024 * (1600 / 900)), 1024)
        assert state.requested_size == (1024, 1024)
        assert state.fill_viewport is True
        assert state.uses_dpi is False
        assert state.effective_size == expected_fill_size == (1820, 1024)
    finally:
        viewport.destroy()
