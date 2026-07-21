# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for SRD section 9.3 effective render size."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from ovui_widgets.viewport import (
    AREA3_RENDER_QA_ENV,
    RESOLUTION_MODE_FIXED,
    FixedModeEffectiveResolution,
    ResolutionClampLimits,
    ViewportResolutionState,
    ViewportResolutionStateError,
    ViewportWidget,
    compute_dpi_adjusted_frame_full_dimensions,
    compute_fixed_mode_effective_resolution,
    compute_fixed_mode_effective_resolution_for_state,
    compute_viewport_mode_effective_resolution,
    compute_viewport_mode_effective_resolution_for_state,
    ensure_safe_renderer_request_size,
    format_viewport_effective_resolution_qa_lines,
    select_resolution_catalog_row_for_state,
)


class _VisibleImage:
    visible = True

    def __init__(self, width: int, height: int) -> None:
        self.computed_width = width
        self.computed_height = height


def _renderer_returning_frame() -> MagicMock:
    renderer = MagicMock()

    def _render(width, height, _view, _proj):
        return np.zeros((int(height), int(width), 4), dtype=np.uint8)

    renderer.render_frame.side_effect = _render
    return renderer


def test_viewport_mode_d1_s1_uses_visible_frame_as_effective_size() -> None:
    effective = compute_viewport_mode_effective_resolution(
        (1280, 720),
        dpi_scale=1.0,
        render_scale=1.0,
        clamp_limits=ResolutionClampLimits(64, 64, 3840, 2160),
    )

    assert effective.visible_frame_size == (1280, 720)
    assert effective.full_size == (1280, 720)
    assert effective.scaled_size == (1280, 720)
    assert effective.effective_size == (1280, 720)
    assert effective.clamped is False


@pytest.mark.parametrize(
    ("scale", "expected"),
    [
        (0.5, (640, 360)),
        (0.25, (320, 180)),
        (2.0, (2560, 1440)),
    ],
)
def test_viewport_mode_applies_render_scale_with_floor(
    scale: float,
    expected: tuple[int, int],
) -> None:
    effective = compute_viewport_mode_effective_resolution(
        (1280, 720),
        dpi_scale=1.0,
        render_scale=scale,
        clamp_limits=ResolutionClampLimits(64, 64, 3840, 2160),
    )

    assert effective.full_size == (1280, 720)
    assert effective.scaled_size == expected
    assert effective.effective_size == expected


def test_viewport_mode_clamps_after_scale_not_before() -> None:
    below_min = compute_viewport_mode_effective_resolution(
        (40, 40),
        dpi_scale=1.0,
        render_scale=0.5,
        clamp_limits=ResolutionClampLimits(64, 64, 3840, 2160),
    )
    above_max = compute_viewport_mode_effective_resolution(
        (2000, 1200),
        dpi_scale=1.0,
        render_scale=2.0,
        clamp_limits=ResolutionClampLimits(64, 64, 3840, 2160),
    )

    assert below_min.full_size == (40, 40)
    assert below_min.scaled_size == (20, 20)
    assert below_min.effective_size == (64, 64)
    assert below_min.clamped is True
    assert above_max.full_size == (2000, 1200)
    assert above_max.scaled_size == (4000, 2400)
    assert above_max.effective_size == (3840, 2160)
    assert above_max.clamped is True


def test_viewport_mode_missing_settings_defaults_preserve_current_behavior() -> None:
    effective = compute_viewport_mode_effective_resolution((800, 450))

    assert effective.dpi_scale == 1.0
    assert effective.render_scale == 1.0
    assert effective.clamp_limits == ResolutionClampLimits()
    assert effective.full_size == (800, 450)
    assert effective.scaled_size == (800, 450)
    assert effective.effective_size == (800, 450)


def test_default_clamp_limits_match_srd_min_and_current_ovui_max() -> None:
    limits = ResolutionClampLimits()

    assert (limits.min_width, limits.min_height) == (64, 64)
    assert (limits.max_width, limits.max_height) == (3840, 2160)


def test_viewport_mode_state_uses_dpi_policy_only_when_enabled() -> None:
    disabled = compute_viewport_mode_effective_resolution_for_state(
        (800, 450),
        ViewportResolutionState(scale=1.0, uses_dpi=False),
        dpi_scale=2.0,
    )
    enabled = compute_viewport_mode_effective_resolution_for_state(
        (800, 450),
        ViewportResolutionState(scale=1.0, uses_dpi=True),
        dpi_scale=2.0,
    )

    assert disabled.full_size == (800, 450)
    assert disabled.effective_size == (800, 450)
    assert enabled.full_size == (1600, 900)
    assert enabled.effective_size == (1600, 900)


def test_viewport_mode_dpi_enabled_applies_d_to_full_dimensions() -> None:
    state = ViewportResolutionState(scale=1.0, uses_dpi=True)

    effective = compute_viewport_mode_effective_resolution_for_state(
        (800, 450),
        state,
        dpi_scale=2.0,
        dpi_available=True,
    )

    assert effective.visible_frame_size == (800, 450)
    assert effective.dpi_enabled is True
    assert effective.dpi_available is True
    assert effective.requested_dpi_scale == 2.0
    assert effective.dpi_scale == 2.0
    assert effective.full_size == (1600, 900)
    assert effective.scaled_size == (1600, 900)
    assert effective.effective_size == (1600, 900)


def test_viewport_mode_dpi_unavailable_falls_back_to_one() -> None:
    state = ViewportResolutionState(scale=1.0, uses_dpi=True)

    effective = compute_viewport_mode_effective_resolution_for_state(
        (800, 450),
        state,
        dpi_scale=2.0,
        dpi_available=False,
    )

    assert effective.dpi_enabled is True
    assert effective.dpi_available is False
    assert effective.requested_dpi_scale == 2.0
    assert effective.dpi_scale == 1.0
    assert effective.full_size == (800, 450)
    assert effective.effective_size == (800, 450)


def test_dpi_adjusted_full_dimensions_feeds_future_fill_mode_path() -> None:
    enabled = compute_dpi_adjusted_frame_full_dimensions(
        (800, 450),
        dpi_enabled=True,
        dpi_available=True,
        dpi_scale=2.0,
    )
    unavailable = compute_dpi_adjusted_frame_full_dimensions(
        (800, 450),
        dpi_enabled=True,
        dpi_available=False,
        dpi_scale=2.0,
    )

    assert enabled.full_size == (1600, 900)
    assert enabled.applied_dpi_scale == 2.0
    assert unavailable.full_size == (800, 450)
    assert unavailable.applied_dpi_scale == 1.0


def test_viewport_mode_state_rejects_fixed_mode() -> None:
    state = ViewportResolutionState(mode="fixed", requested_size=(1920, 1080))

    with pytest.raises(ViewportResolutionStateError):
        compute_viewport_mode_effective_resolution_for_state((1280, 720), state)


def test_fixed_mode_100_percent_uses_requested_full_size() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (1920, 1080),
        render_scale=1.0,
        clamp_limits=ResolutionClampLimits(64, 64, 3840, 2160),
    )

    assert effective.requested_full_size == (1920, 1080)
    assert effective.full_size == (1920, 1080)
    assert effective.scaled_size == (1920, 1080)
    assert effective.effective_size == (1920, 1080)
    assert effective.clamped is False


@pytest.mark.parametrize(
    ("scale", "expected"),
    [
        (0.5, (960, 540)),
        (0.25, (480, 270)),
        (0.333, (639, 359)),
    ],
)
def test_fixed_mode_applies_render_scale_with_floor(
    scale: float,
    expected: tuple[int, int],
) -> None:
    effective = compute_fixed_mode_effective_resolution(
        (1920, 1080),
        render_scale=scale,
        clamp_limits=ResolutionClampLimits(64, 64, 3840, 2160),
    )

    assert effective.full_size == (1920, 1080)
    assert effective.scaled_size == expected
    assert effective.effective_size == expected


def test_fixed_mode_fractional_scale_truncates_toward_zero_before_clamp() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (1501, 1001),
        render_scale=0.5,
        clamp_limits=ResolutionClampLimits(64, 64, 3840, 2160),
    )

    assert effective.full_size == (1501, 1001)
    assert effective.scaled_size == (750, 500)
    assert effective.effective_size == (750, 500)


def test_fixed_mode_clamps_after_scale_not_before() -> None:
    below_min = compute_fixed_mode_effective_resolution(
        (100, 100),
        render_scale=0.5,
        clamp_limits=ResolutionClampLimits(64, 64, 3840, 2160),
    )
    above_max = compute_fixed_mode_effective_resolution(
        (3000, 2000),
        render_scale=2.0,
        clamp_limits=ResolutionClampLimits(64, 64, 3840, 2160),
    )

    assert below_min.full_size == (100, 100)
    assert below_min.scaled_size == (50, 50)
    assert below_min.effective_size == (64, 64)
    assert below_min.clamped is True
    assert above_max.full_size == (3000, 2000)
    assert above_max.scaled_size == (6000, 4000)
    assert above_max.effective_size == (3840, 2160)
    assert above_max.clamped is True


def test_fixed_fill_square_in_wide_viewport_extends_width_from_requested_size() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (1024, 1024),
        render_scale=1.0,
        fill_viewport=True,
        visible_frame_size=(1600, 900),
    )

    assert effective.fill_viewport is True
    assert effective.requested_full_size == (1024, 1024)
    assert effective.visible_frame_size == (1600, 900)
    assert effective.selected_aspect_ratio == 1.0
    assert effective.viewport_aspect_ratio == pytest.approx(1600 / 900)
    assert effective.expanded_size == pytest.approx((1820.444444, 1024.0))
    assert effective.full_size == pytest.approx((1820.444444, 1024.0))
    assert effective.scaled_size == (1820, 1024)
    assert effective.effective_size == (1820, 1024)


def test_fixed_fill_hd720_in_taller_viewport_extends_height_not_shrink_to_viewport() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (1280, 720),
        render_scale=1.0,
        fill_viewport=True,
        visible_frame_size=(806, 659),
    )

    assert effective.selected_aspect_ratio == pytest.approx(16 / 9)
    assert effective.viewport_aspect_ratio == pytest.approx(806 / 659)
    assert effective.full_size == pytest.approx((1280.0, 1046.550868))
    assert effective.scaled_size == (1280, 1046)
    assert effective.effective_size == (1280, 1046)


def test_fixed_fill_uses_dpi_adjusted_visible_frame_dimensions() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (1024, 1024),
        render_scale=1.0,
        fill_viewport=True,
        visible_frame_size=(800, 450),
        dpi_enabled=True,
        dpi_available=True,
        dpi_scale=2.0,
    )

    assert effective.dpi_enabled is True
    assert effective.dpi_available is True
    assert effective.requested_dpi_scale == 2.0
    assert effective.dpi_scale == 2.0
    assert effective.visible_frame_size == (800, 450)
    assert effective.full_size == pytest.approx((1820.444444, 1024.0))
    assert effective.effective_size == (1820, 1024)


def test_fixed_fill_applies_render_scale_after_fill_expansion() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (1024, 1024),
        render_scale=0.5,
        fill_viewport=True,
        visible_frame_size=(1600, 900),
    )

    assert effective.full_size == pytest.approx((1820.444444, 1024.0))
    assert effective.scaled_size == (910, 512)
    assert effective.effective_size == (910, 512)


def test_fixed_fill_clamps_after_fill_and_scale() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (3840, 2160),
        render_scale=2.0,
        fill_viewport=True,
        visible_frame_size=(5000, 3000),
    )

    assert effective.full_size == pytest.approx((3840.0, 2304.0))
    assert effective.scaled_size == (7680, 4608)
    assert effective.effective_size == (3840, 2160)
    assert effective.clamped is True


def test_viewport_mode_ignores_fill_viewport_state() -> None:
    state = ViewportResolutionState(
        mode="viewport",
        requested_size=(1024, 1024),
        scale=1.0,
        fill_viewport=True,
    )

    effective = compute_viewport_mode_effective_resolution_for_state(
        (1600, 900),
        state,
    )

    assert state.is_viewport_mode
    assert state.fill_viewport is False
    assert state.requested_size == (0, 0)
    assert effective.full_size == (1600, 900)
    assert effective.effective_size == (1600, 900)


def test_fixed_mode_respects_configured_bounds_after_scale() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (900, 700),
        render_scale=2.0,
        clamp_limits=ResolutionClampLimits(100, 90, 1000, 800),
    )

    assert effective.scaled_size == (1800, 1400)
    assert effective.effective_size == (1000, 800)
    assert effective.clamped is True


def test_fixed_mode_icon_at_25_percent_stays_above_default_minimum() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (512, 512),
        render_scale=0.25,
    )

    assert effective.full_size == (512, 512)
    assert effective.scaled_size == (128, 128)
    assert effective.effective_size == (128, 128)
    assert effective.clamped is False


def test_fixed_mode_uhd_at_200_percent_clamps_after_scale_to_default_max() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (3840, 2160),
        render_scale=2.0,
    )

    assert effective.scaled_size == (7680, 4320)
    assert effective.effective_size == (3840, 2160)
    assert effective.clamped is True


def test_fixed_mode_tiny_custom_clamps_to_default_minimum() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (50, 40),
        render_scale=1.0,
    )

    assert effective.full_size == (50, 40)
    assert effective.scaled_size == (50, 40)
    assert effective.effective_size == (64, 64)
    assert effective.clamped is True


def test_invalid_zero_negative_sizes_are_rejected_before_fixed_math() -> None:
    with pytest.raises(ViewportResolutionStateError):
        compute_fixed_mode_effective_resolution((0, -1), render_scale=1.0)


def test_final_renderer_request_guard_blocks_below_one_dimensions() -> None:
    guarded = ensure_safe_renderer_request_size((0, -1))

    assert guarded == (1, 1)


def test_fixed_mode_state_uses_requested_size_and_scale() -> None:
    state = ViewportResolutionState(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1920, 1080),
        scale=0.5,
        selected_label="HD1080P",
    )

    effective = compute_fixed_mode_effective_resolution_for_state(state)

    assert effective.requested_full_size == (1920, 1080)
    assert effective.scaled_size == (960, 540)
    assert effective.effective_size == (960, 540)


def test_fixed_mode_state_rejects_viewport_mode() -> None:
    state = ViewportResolutionState()

    with pytest.raises(ViewportResolutionStateError):
        compute_fixed_mode_effective_resolution_for_state(state)


def test_fixed_mode_selection_is_keyed_to_requested_size_not_effective_size() -> None:
    state = ViewportResolutionState(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1920, 1080),
        scale=0.5,
        selected_label="HD1080P",
        effective_size=(960, 540),
    )
    effective = compute_fixed_mode_effective_resolution_for_state(state)

    selection = select_resolution_catalog_row_for_state(
        state,
        render_scale=state.scale,
        effective_size=effective.effective_size,
    )

    assert selection.current_label == "HD1080P"
    assert selection.label == "HD1080P"
    assert effective.effective_size == (960, 540)


def test_selection_is_unchanged_by_dpi_or_scale_effective_size() -> None:
    viewport_state = ViewportResolutionState(
        scale=1.0,
        uses_dpi=True,
        effective_size=(1600, 900),
    )
    fixed_state = ViewportResolutionState(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1501, 1001),
        scale=0.5,
        selected_label="Custom",
        effective_size=(750, 500),
    )

    viewport_selection = select_resolution_catalog_row_for_state(
        viewport_state,
        render_scale=viewport_state.scale,
        effective_size=viewport_state.effective_size,
    )
    fixed_selection = select_resolution_catalog_row_for_state(
        fixed_state,
        render_scale=fixed_state.scale,
        effective_size=fixed_state.effective_size,
    )

    assert viewport_selection.current_label == "Viewport"
    assert viewport_selection.key == "sentinel:Viewport"
    assert fixed_selection.current_label == "Custom"
    assert fixed_selection.key == "sentinel:Custom"


def test_viewport_render_commits_effective_size_to_renderer_state_and_hud() -> None:
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(1280, 720)
    try:
        assert viewport.render(0.1) is True

        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1280, 720)
        assert viewport.get_resolution_state().effective_size == (1280, 720)
        assert viewport._last_resolution == (1280, 720)
    finally:
        viewport.destroy()


def test_viewport_render_uses_state_scale_for_viewport_mode_effective_size() -> None:
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(1280, 720)
    viewport.set_resolution_state(scale=0.5)
    try:
        assert viewport.render(0.1) is True

        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (640, 360)
        assert viewport.get_resolution_state().effective_size == (640, 360)
        assert viewport._last_resolution == (640, 360)
    finally:
        viewport.destroy()


def test_viewport_render_uses_fixed_requested_size_not_visible_frame() -> None:
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(800, 450)
    viewport.set_resolution_state(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1920, 1080),
        scale=1.0,
        fill_viewport=False,
        selected_label="HD1080P",
    )
    try:
        assert viewport.render(0.1) is True

        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1920, 1080)
        state = viewport.get_resolution_state()
        assert state.mode == RESOLUTION_MODE_FIXED
        assert state.requested_size == (1920, 1080)
        assert state.effective_size == (1920, 1080)
        assert viewport._last_resolution == (1920, 1080)
    finally:
        viewport.destroy()


def test_viewport_render_fixed_scale_stays_fixed_when_frame_resizes() -> None:
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(1280, 720)
    viewport.set_resolution_state(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1920, 1080),
        scale=0.5,
        fill_viewport=False,
        selected_label="HD1080P",
    )
    try:
        assert viewport.render(0.1) is True
        first_args, _kwargs = renderer.render_frame.call_args
        assert first_args[:2] == (960, 540)

        viewport._image.computed_width = 800
        viewport._image.computed_height = 450
        assert viewport.render(0.1) is True
        second_args, _kwargs = renderer.render_frame.call_args
        assert second_args[:2] == (960, 540)
        assert viewport.get_resolution_state().requested_size == (1920, 1080)
        assert viewport.get_resolution_state().effective_size == (960, 540)
    finally:
        viewport.destroy()


def test_viewport_render_fixed_fill_uses_visible_frame_before_scale() -> None:
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(1600, 900)
    viewport.set_resolution_state(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1024, 1024),
        scale=1.0,
        fill_viewport=True,
        selected_label="Square",
    )
    try:
        assert viewport.render(0.1) is True

        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1820, 1024)
        state = viewport.get_resolution_state()
        assert state.requested_size == (1024, 1024)
        assert state.selected_label == "Square"
        assert state.effective_size == (1820, 1024)
        assert viewport._last_resolution == (1820, 1024)
    finally:
        viewport.destroy()


def test_render_loop_requests_committed_effective_size_for_mode_scale_and_fill() -> None:
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(1280, 720)
    try:
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1280, 720)
        assert viewport.get_resolution_state().effective_size == (1280, 720)

        viewport.set_resolution_state(
            mode=RESOLUTION_MODE_FIXED,
            requested_size=(1920, 1080),
            scale=1.0,
            fill_viewport=False,
            selected_label="HD1080P",
            effective_size=None,
        )
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1920, 1080)
        assert viewport.get_resolution_state().effective_size == (1920, 1080)

        viewport.set_resolution_state(scale=0.5, effective_size=None)
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (960, 540)
        assert viewport.get_resolution_state().effective_size == (960, 540)

        viewport.set_resolution_state(
            requested_size=(1024, 1024),
            scale=1.0,
            fill_viewport=True,
            selected_label="Square",
            effective_size=None,
        )
        viewport._image.computed_width = 1600
        viewport._image.computed_height = 900
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1820, 1024)
        assert viewport.get_resolution_state().effective_size == (1820, 1024)
        assert viewport._last_resolution == (1820, 1024)
    finally:
        viewport.destroy()


def test_render_loop_fixed_resize_does_not_use_raw_widget_or_write_settings() -> None:
    renderer = _renderer_returning_frame()
    settings = MagicMock()
    viewport = ViewportWidget(
        services=SimpleNamespace(settings=settings, selection_bus=None),
        renderer=renderer,
    )
    viewport._image = _VisibleImage(1280, 720)
    viewport.set_resolution_state(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1920, 1080),
        scale=0.5,
        fill_viewport=False,
        selected_label="HD1080P",
    )
    try:
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (960, 540)
        settings.set.assert_not_called()

        viewport._image.computed_width = 800
        viewport._image.computed_height = 600
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (960, 540)
        state = viewport.get_resolution_state()
        assert state.requested_size == (1920, 1080)
        assert state.scale == 0.5
        assert state.fill_viewport is False
        assert state.effective_size == (960, 540)
        settings.set.assert_not_called()
    finally:
        viewport.destroy()


def test_render_loop_unchanged_effective_size_does_not_notify_but_renders() -> None:
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(1280, 720)
    changes = []
    handle = viewport.subscribe_resolution_state(
        lambda old, new: changes.append((old.effective_size, new.effective_size))
    )
    try:
        assert viewport.render(0.1) is True
        assert changes == [(None, (1280, 720))]

        assert viewport.render(0.1) is True
        assert changes == [(None, (1280, 720))]
        assert renderer.render_frame.call_count == 2
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1280, 720)
    finally:
        handle.unsubscribe()
        viewport.destroy()


def test_render_loop_blocks_synchronous_reentrant_render_feedback() -> None:
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(1280, 720)
    reentrant_results = []

    def _attempt_reentrant_render(_old, _new) -> None:
        reentrant_results.append(viewport.render(0.1))

    handle = viewport.subscribe_resolution_state(_attempt_reentrant_render)
    try:
        assert viewport.render(0.1) is True

        assert reentrant_results == [False]
        assert renderer.render_frame.call_count == 1
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1280, 720)
        assert viewport.get_resolution_state().effective_size == (1280, 720)
    finally:
        handle.unsubscribe()
        viewport.destroy()


def test_area3_qa_frame_control_is_visible_and_env_gated(monkeypatch) -> None:
    monkeypatch.setenv(AREA3_RENDER_QA_ENV, "1")
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(640, 360)
    try:
        viewport._apply_resolution_render_qa_frame_800_450()
        assert viewport.render(0.1) is True

        assert viewport._last_resolution == (800, 450)
        assert viewport.get_resolution_state().effective_size == (800, 450)

        viewport._apply_resolution_render_qa_frame_800_600()
        assert viewport.render(0.1) is True

        assert viewport._last_resolution == (800, 600)
        assert viewport.get_resolution_state().effective_size == (800, 600)

        viewport._apply_resolution_render_qa_openusd_session()
        assert viewport.render(0.1) is True

        assert viewport._last_resolution == (1280, 720)
        assert viewport.get_resolution_state().effective_size == (1280, 720)
        assert "OpenUSD-backed profile" in (
            viewport._resolution_render_qa_status_message
        )
    finally:
        viewport.destroy()


def test_area3_qa_fixed_controls_are_visible_and_env_gated(monkeypatch) -> None:
    monkeypatch.setenv(AREA3_RENDER_QA_ENV, "1")
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(640, 360)
    try:
        viewport._apply_resolution_render_qa_fixed_hd1080p_100()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1920, 1080)
        assert viewport.get_resolution_state().selected_label == "HD1080P"

        viewport._apply_resolution_render_qa_fixed_hd1080p_50()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (960, 540)
        assert viewport.get_resolution_state().selected_label == "HD1080P"

        viewport._apply_resolution_render_qa_frame_800_600()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (960, 540)
        assert viewport.get_resolution_state().requested_size == (1920, 1080)
        assert viewport.get_resolution_state().selected_label == "HD1080P"

        viewport._apply_resolution_render_qa_fixed_resized_frame()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (960, 540)
        assert viewport.get_resolution_state().requested_size == (1920, 1080)
    finally:
        viewport.destroy()


def test_area3_qa_dpi_and_fractional_controls_are_visible_and_env_gated(
    monkeypatch,
) -> None:
    monkeypatch.setenv(AREA3_RENDER_QA_ENV, "1")
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(640, 360)
    try:
        viewport._apply_resolution_render_qa_dpi_enabled_d2()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1600, 900)
        state = viewport.get_resolution_state()
        assert state.selected_label == "Viewport"
        assert state.uses_dpi is True

        viewport._apply_resolution_render_qa_dpi_unavailable()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (800, 450)
        effective = viewport._last_viewport_mode_effective_resolution
        assert effective is not None
        assert effective.dpi_available is False
        assert effective.dpi_scale == 1.0

        viewport._apply_resolution_render_qa_fixed_fractional_50()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (750, 500)
        assert viewport.get_resolution_state().requested_size == (1501, 1001)
        assert viewport.get_resolution_state().selected_label == "Custom"

        viewport._apply_resolution_render_qa_dpi_enabled_d2()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1600, 900)
        assert viewport.get_resolution_state().effective_size == (1600, 900)
    finally:
        viewport.destroy()


def test_area3_qa_bounds_controls_are_visible_and_env_gated(monkeypatch) -> None:
    monkeypatch.setenv(AREA3_RENDER_QA_ENV, "1")
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(640, 360)
    try:
        viewport._apply_resolution_render_qa_icon_25()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (128, 128)
        assert viewport.get_resolution_state().selected_label == "Icon"

        viewport._apply_resolution_render_qa_tiny_50_40()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (64, 64)
        assert viewport.get_resolution_state().requested_size == (64, 64)
        assert viewport.get_resolution_state().selected_label == "Custom"

        viewport._apply_resolution_render_qa_uhd_200()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (3840, 2160)
        assert viewport.get_resolution_state().selected_label == "UHD"

        previous_state = viewport.get_resolution_state()
        previous_calls = renderer.render_frame.call_count
        viewport._apply_resolution_render_qa_invalid_size()
        assert viewport.get_resolution_state() == previous_state
        assert "Invalid 0x-1 request rejected" in (
            viewport._resolution_render_qa_status_message
        )
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (3840, 2160)
        assert renderer.render_frame.call_count == previous_calls + 1
    finally:
        viewport.destroy()


def test_area3_qa_fill_controls_are_visible_and_env_gated(monkeypatch) -> None:
    monkeypatch.setenv(AREA3_RENDER_QA_ENV, "1")
    renderer = _renderer_returning_frame()
    viewport = ViewportWidget(services=None, renderer=renderer)
    viewport._image = _VisibleImage(640, 360)
    try:
        viewport._apply_resolution_render_qa_square_fill_off()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1024, 1024)
        state = viewport.get_resolution_state()
        assert state.selected_label == "Square"
        assert state.fill_viewport is False

        viewport._apply_resolution_render_qa_square_fill_on()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1820, 1024)
        state = viewport.get_resolution_state()
        assert state.selected_label == "Square"
        assert state.fill_viewport is True

        viewport._apply_resolution_render_qa_square_fill_on_50()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (910, 512)
        state = viewport.get_resolution_state()
        assert state.selected_label == "Square"
        assert state.fill_viewport is True
        assert state.scale == 0.5

        viewport._apply_resolution_render_qa_viewport_after_fill()
        assert viewport.render(0.1) is True
        args, _kwargs = renderer.render_frame.call_args
        assert args[:2] == (1600, 900)
        state = viewport.get_resolution_state()
        assert state.selected_label == "Viewport"
        assert state.fill_viewport is False
    finally:
        viewport.destroy()


def test_area3_qa_lines_show_committed_effective_size_and_hud_proof() -> None:
    effective = compute_viewport_mode_effective_resolution((1280, 720))
    lines = format_viewport_effective_resolution_qa_lines(
        profile_label="Viewport frame 1280x720",
        requested_label="Viewport",
        effective=effective,
    )
    text = "\n".join(lines)

    assert "A3 Effective Resolution QA Scaffold" in text
    assert "Requested Resolution Selection: Viewport" in text
    assert "Visible Frame: 1280x720" in text
    assert (
        "DPI Policy: enabled=True | available=True | requested D=1 | applied D=1"
        in text
    )
    assert "Full Size: 1280x720" in text
    assert "Scaled Size: 1280x720" in text
    assert "Committed Effective Size: 1280x720" in text
    assert "HUD Proof: normal RES line shows the committed effective size" in text


def test_area3_qa_lines_show_dpi_unavailable_fallback_branch() -> None:
    effective = compute_viewport_mode_effective_resolution(
        (800, 450),
        dpi_enabled=True,
        dpi_available=False,
        dpi_scale=2.0,
    )
    lines = format_viewport_effective_resolution_qa_lines(
        profile_label="DPI unavailable",
        requested_label="Viewport",
        effective=effective,
    )
    text = "\n".join(lines)

    assert "Profile: DPI unavailable" in text
    assert (
        "DPI Policy: enabled=True | available=False | requested D=2 | applied D=1"
        in text
    )
    assert "Full Size: 800x450" in text
    assert "Committed Effective Size: 800x450" in text


def test_area3_qa_lines_show_fixed_mode_selection_and_effective_size() -> None:
    effective: FixedModeEffectiveResolution = compute_fixed_mode_effective_resolution(
        (1920, 1080),
        render_scale=0.5,
    )
    lines = format_viewport_effective_resolution_qa_lines(
        profile_label="Fixed HD1080P 50%",
        requested_label="HD1080P",
        effective=effective,
    )
    text = "\n".join(lines)

    assert "A3 Effective Resolution QA Scaffold" in text
    assert "Requested Resolution Selection: HD1080P" in text
    assert "Requested Full Size: 1920x1080" in text
    assert "Render Scale S: 0.5" in text
    assert "Fill Viewport: off" in text
    assert "Full Size: 1920x1080" in text
    assert "Scaled Size: 960x540" in text
    assert "Committed Effective Size: 960x540" in text


def test_area3_qa_lines_show_fixed_fill_formula_details() -> None:
    effective = compute_fixed_mode_effective_resolution(
        (1024, 1024),
        render_scale=0.5,
        fill_viewport=True,
        visible_frame_size=(1600, 900),
    )
    lines = format_viewport_effective_resolution_qa_lines(
        profile_label="Square Fill on 50%",
        requested_label="Square",
        effective=effective,
    )
    text = "\n".join(lines)

    assert "Profile: Square Fill on 50%" in text
    assert "Requested Resolution Selection: Square" in text
    assert "Mode Formula: Fixed Fill aspect-expand" in text
    assert "Visible Frame: 1600x900" in text
    assert "Fill Viewport: on; expands toward visible frame before scale" in text
    assert "Aspect: selected=1.000 | viewport=1.778" in text
    assert "Full Size: 1820.44x1024" in text
    assert "Scaled Size: 910x512" in text
    assert "Committed Effective Size: 910x512" in text
