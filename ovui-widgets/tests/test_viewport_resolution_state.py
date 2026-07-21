# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the viewport resolution state contract."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
from ovui_widgets.viewport import (
    AVAILABILITY_REASON_NO_RENDERER,
    AVAILABILITY_REASON_NO_SETTINGS_SERVICE,
    AVAILABILITY_REASON_OWNER_DESTROYED,
    DEFAULT_VIEWPORT_ID,
    PRIVATE_RENDER_SIZE_ACCESS_RULE,
    RESOLUTION_MODE_FIXED,
    RESOLUTION_MODE_VIEWPORT,
    RESOLUTION_SETTINGS_PATH_CAPABILITY_GATE,
    ResolutionClampLimits,
    ViewportAvailabilitySnapshot,
    ViewportResolutionState,
    ViewportResolutionStateError,
    ViewportWidget,
)


def _services_with_settings(settings: object | None) -> SimpleNamespace:
    return SimpleNamespace(settings=settings, selection_bus=None)


def _destroy_viewports(*viewports: ViewportWidget) -> None:
    for viewport in reversed(viewports):
        viewport.destroy()


def test_default_state_shape_preserves_current_viewport_behavior() -> None:
    state = ViewportResolutionState.default()

    assert state.mode == RESOLUTION_MODE_VIEWPORT
    assert state.requested_size == (0, 0)
    assert state.scale == 1.0
    assert state.fill_viewport is False
    assert state.uses_dpi is False
    assert state.clamp_limits == ResolutionClampLimits(64, 64, 3840, 2160)
    assert state.selected_label == "Viewport"
    assert state.effective_size is None
    assert state.is_viewport_mode is True
    assert state.is_fixed_mode is False


def test_viewport_widget_owns_one_default_resolution_state_record() -> None:
    vp = ViewportWidget(services=None, renderer=None)
    try:
        state = vp.get_resolution_state()

        assert state is vp.resolution_state
        assert state.mode == RESOLUTION_MODE_VIEWPORT
        assert state.requested_size == (0, 0)
        assert state.scale == 1.0
        assert state.fill_viewport is False
        assert state.uses_dpi is False
        assert state.clamp_limits == ResolutionClampLimits(
            vp.MIN_RENDER_WIDTH,
            vp.MIN_RENDER_HEIGHT,
            vp.MAX_RENDER_WIDTH,
            vp.MAX_RENDER_HEIGHT,
        )
        assert state.effective_size is None
    finally:
        vp.destroy()


def test_default_viewport_identity_uses_main_fallback() -> None:
    vp = ViewportWidget(services=None, renderer=None)
    try:
        assert vp.get_viewport_id() == DEFAULT_VIEWPORT_ID
        assert vp.viewport_id == DEFAULT_VIEWPORT_ID
    finally:
        vp.destroy()


def test_explicit_viewport_identity_is_retained_and_readable() -> None:
    vp = ViewportWidget(services=None, renderer=None, viewport_id="review")
    try:
        assert vp.get_viewport_id() == "review"
        assert vp.viewport_id == "review"
    finally:
        vp.destroy()


@pytest.mark.parametrize("viewport_id", ["", "  "])
def test_empty_explicit_viewport_identity_is_rejected(viewport_id) -> None:
    with pytest.raises(ValueError):
        ViewportWidget(services=None, renderer=None, viewport_id=viewport_id)


def test_duplicate_default_viewport_identities_are_disambiguated() -> None:
    first = ViewportWidget(services=None, renderer=None)
    second = ViewportWidget(services=None, renderer=None)
    try:
        assert first.viewport_id == DEFAULT_VIEWPORT_ID
        assert second.viewport_id == f"{DEFAULT_VIEWPORT_ID}_2"
        assert first.viewport_id != second.viewport_id
        assert first.title == "Viewport"
        assert second.title == f"Viewport###{DEFAULT_VIEWPORT_ID}_2"
    finally:
        _destroy_viewports(first, second)


def test_duplicate_explicit_viewport_identities_are_disambiguated() -> None:
    first = ViewportWidget(services=None, renderer=None, viewport_id="review")
    second = ViewportWidget(services=None, renderer=None, viewport_id="review")
    try:
        assert first.viewport_id == "review"
        assert second.viewport_id == "review_2"
        assert first.viewport_id != second.viewport_id
    finally:
        _destroy_viewports(first, second)


def test_viewport_identity_is_stable_for_lifetime() -> None:
    first = ViewportWidget(services=None, renderer=None)
    second = ViewportWidget(services=None, renderer=None)
    third = None
    try:
        second_identity = second.viewport_id

        first.destroy()
        third = ViewportWidget(services=None, renderer=None)

        assert second.viewport_id == second_identity
        assert third.viewport_id == DEFAULT_VIEWPORT_ID
        assert second.viewport_id != third.viewport_id
    finally:
        if third is not None:
            third.destroy()
        second.destroy()


def test_availability_snapshot_reports_renderer_settings_and_owner_facts() -> None:
    renderer = MockRendererAdapter()
    settings = object()
    vp = ViewportWidget(
        services=_services_with_settings(settings),
        renderer=renderer,
    )
    try:
        snapshot = vp.get_resolution_availability()

        assert isinstance(snapshot, ViewportAvailabilitySnapshot)
        assert snapshot is vp.resolution_availability
        assert snapshot.renderer_available is True
        assert snapshot.settings_available is True
        assert snapshot.owner_alive is True
        assert snapshot.unavailable_reasons == ()
        assert snapshot.settings_path_hidden_by_capability_gate is False
    finally:
        vp.destroy()


def test_availability_snapshot_reports_missing_renderer_and_settings_reasons(
    monkeypatch,
) -> None:
    from ovui_widgets.common.settings import Settings

    monkeypatch.setattr(Settings, "_instance", None)
    vp = ViewportWidget(
        services=_services_with_settings(None),
        renderer=None,
    )
    try:
        snapshot = vp.get_resolution_availability()

        assert snapshot.renderer_available is False
        assert snapshot.settings_available is False
        assert snapshot.owner_alive is True
        assert snapshot.unavailable_reasons == (
            AVAILABILITY_REASON_NO_RENDERER,
            AVAILABILITY_REASON_NO_SETTINGS_SERVICE,
        )
    finally:
        vp.destroy()


def test_availability_change_notifications_are_ordered_once() -> None:
    vp = ViewportWidget(
        services=_services_with_settings(object()),
        renderer=None,
    )
    calls = []
    try:
        previous = vp.get_resolution_availability()
        first = vp.subscribe_resolution_availability(
            lambda old, new: calls.append(("first", old, new))
        )
        second = vp.subscribe_resolution_availability(
            lambda old, new: calls.append(("second", old, new))
        )

        vp.set_renderer(MockRendererAdapter())
        current = vp.get_resolution_availability()

        assert first.active is True
        assert second.active is True
        assert current.renderer_available is True
        assert [call[0] for call in calls] == ["first", "second"]
        assert [call[1] for call in calls] == [previous, previous]
        assert [call[2] for call in calls] == [current, current]
    finally:
        vp.destroy()


def test_availability_unchanged_refresh_does_not_notify() -> None:
    vp = ViewportWidget(
        services=_services_with_settings(object()),
        renderer=MockRendererAdapter(),
    )
    calls = []
    try:
        previous = vp.get_resolution_availability()
        handle = vp.subscribe_resolution_availability(
            lambda old, new: calls.append((old, new))
        )

        current = vp.refresh_resolution_availability()

        assert handle.active is True
        assert current == previous
        assert calls == []
    finally:
        vp.destroy()


def test_availability_unsubscribe_handle_removes_observer() -> None:
    vp = ViewportWidget(
        services=_services_with_settings(object()),
        renderer=None,
    )
    calls = []
    try:
        first = vp.subscribe_resolution_availability(
            lambda old, new: calls.append("first")
        )
        second = vp.subscribe_resolution_availability(
            lambda old, new: calls.append("second")
        )

        assert first.unsubscribe() is True
        assert first.unsubscribe() is False
        vp.set_renderer(MockRendererAdapter())

        assert calls == ["second"]
        assert first.active is False
        assert second.cancel() is True

        vp.set_renderer(None)

        assert calls == ["second"]
        assert second.active is False
    finally:
        vp.destroy()


def test_availability_destroy_publishes_owner_dead_then_blocks_late_events() -> None:
    vp = ViewportWidget(
        services=_services_with_settings(object()),
        renderer=MockRendererAdapter(),
    )
    calls = []

    handle = vp.subscribe_resolution_availability(
        lambda old, new: calls.append((old, new))
    )
    assert handle.active is True

    vp.destroy()

    assert handle.active is False
    assert len(calls) == 1
    previous, current = calls[0]
    assert previous.owner_alive is True
    assert current.owner_alive is False
    assert current.renderer_available is False
    assert current.settings_available is False
    assert current.unavailable_reasons == (
        AVAILABILITY_REASON_NO_RENDERER,
        AVAILABILITY_REASON_NO_SETTINGS_SERVICE,
        AVAILABILITY_REASON_OWNER_DESTROYED,
    )

    assert handle.unsubscribe() is False
    late_handle = vp.subscribe_resolution_availability(
        lambda old, new: calls.append((old, new))
    )
    assert late_handle.active is False

    vp.refresh_resolution_availability()

    assert len(calls) == 1


def test_availability_contract_does_not_hide_future_settings_path(monkeypatch) -> None:
    from ovui_widgets.common.settings import Settings

    monkeypatch.setattr(Settings, "_instance", None)
    vp = ViewportWidget(
        services=_services_with_settings(None),
        renderer=None,
    )
    try:
        snapshot = vp.get_resolution_availability()

        assert RESOLUTION_SETTINGS_PATH_CAPABILITY_GATE is None
        assert snapshot.renderer_available is False
        assert snapshot.settings_available is False
        assert snapshot.settings_path_hidden_by_capability_gate is False
    finally:
        vp.destroy()


def test_missing_renderer_pick_actions_do_not_crash(monkeypatch) -> None:
    from ovui_widgets.common.settings import Settings

    monkeypatch.setattr(Settings, "_instance", None)
    vp = ViewportWidget(
        services=_services_with_settings(None),
        renderer=None,
    )
    try:
        vp._on_pick(0.5, 0.5)
        vp._on_pick_rect(0.0, 0.0, 1.0, 1.0)
    finally:
        vp.destroy()


def test_viewport_widget_accepts_and_stores_valid_state_changes() -> None:
    vp = ViewportWidget(services=None, renderer=None)
    try:
        state = vp.set_resolution_state(
            mode=RESOLUTION_MODE_FIXED,
            requested_size=(1920, 1080),
            scale=0.5,
            fill_viewport=True,
            uses_dpi=True,
            selected_label="HD1080P",
        )

        assert state is vp.get_resolution_state()
        assert state.mode == RESOLUTION_MODE_FIXED
        assert state.requested_size == (1920, 1080)
        assert state.scale == 0.5
        assert state.fill_viewport is True
        assert state.uses_dpi is True
        assert state.selected_label == "HD1080P"
    finally:
        vp.destroy()


def test_resolution_state_subscribers_notify_in_order_once_for_accepted_change() -> None:
    vp = ViewportWidget(services=None, renderer=None)
    calls = []
    try:
        previous = vp.get_resolution_state()

        first = vp.subscribe_resolution_state(
            lambda old, new: calls.append(("first", old, new))
        )
        second = vp.subscribe_resolution_state(
            lambda old, new: calls.append(("second", old, new))
        )
        state = vp.set_resolution_state(
            mode=RESOLUTION_MODE_FIXED,
            requested_size=(1920, 1080),
            selected_label="HD1080P",
        )

        assert first.active is True
        assert second.active is True
        assert [call[0] for call in calls] == ["first", "second"]
        assert [call[1] for call in calls] == [previous, previous]
        assert [call[2] for call in calls] == [state, state]
    finally:
        vp.destroy()


def test_resolution_state_unchanged_values_do_not_notify() -> None:
    vp = ViewportWidget(services=None, renderer=None)
    calls = []
    try:
        previous = vp.get_resolution_state()
        handle = vp.subscribe_resolution_state(lambda old, new: calls.append((old, new)))

        state = vp.set_resolution_state(
            mode=RESOLUTION_MODE_VIEWPORT,
            requested_size=(1920, 1080),
            fill_viewport=True,
        )

        assert handle.active is True
        assert state is previous
        assert calls == []
    finally:
        vp.destroy()


def test_resolution_state_unsubscribe_handle_removes_observer() -> None:
    vp = ViewportWidget(services=None, renderer=None)
    calls = []
    try:
        first = vp.subscribe_resolution_state(lambda old, new: calls.append("first"))
        second = vp.subscribe_resolution_state(lambda old, new: calls.append("second"))

        assert first.unsubscribe() is True
        assert first.unsubscribe() is False
        vp.set_resolution_state(
            mode=RESOLUTION_MODE_FIXED,
            requested_size=(1920, 1080),
        )

        assert calls == ["second"]
        assert first.active is False
        assert second.cancel() is True

        vp.set_resolution_state(scale=0.5)

        assert calls == ["second"]
        assert second.active is False
    finally:
        vp.destroy()


def test_resolution_state_unsubscribe_during_notification_skips_removed_callback() -> None:
    vp = ViewportWidget(services=None, renderer=None)
    calls = []
    try:
        second = None

        def first_callback(_old, _new):
            calls.append("first")
            assert second is not None
            assert second.unsubscribe() is True

        def second_callback(_old, _new):
            calls.append("second")

        first = vp.subscribe_resolution_state(first_callback)
        second = vp.subscribe_resolution_state(second_callback)

        vp.set_resolution_state(
            mode=RESOLUTION_MODE_FIXED,
            requested_size=(1920, 1080),
        )

        assert first.active is True
        assert second.active is False
        assert calls == ["first"]
    finally:
        vp.destroy()


def test_resolution_state_destroy_cleans_observers_and_blocks_late_events() -> None:
    vp = ViewportWidget(services=None, renderer=None)
    calls = []

    previous = vp.get_resolution_state()
    handle = vp.subscribe_resolution_state(lambda old, new: calls.append((old, new)))
    assert handle.active is True

    vp.destroy()

    assert handle.active is False
    assert handle.unsubscribe() is False
    state = vp.set_resolution_state(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(1920, 1080),
    )
    late_handle = vp.subscribe_resolution_state(lambda old, new: calls.append((old, new)))

    assert state is previous
    assert late_handle.active is False
    assert calls == []


def test_invalid_viewport_widget_state_update_does_not_replace_existing_state() -> None:
    vp = ViewportWidget(services=None, renderer=None)
    try:
        original = vp.get_resolution_state()

        with pytest.raises(ViewportResolutionStateError):
            vp.set_resolution_state(scale=0.0)

        assert vp.get_resolution_state() is original
    finally:
        vp.destroy()


def test_fixed_requested_size_clamps_to_minimum_but_not_maximum() -> None:
    state = ViewportResolutionState(
        mode=RESOLUTION_MODE_FIXED,
        requested_size=(12, 5000),
        selected_label="",
    )

    assert state.requested_size == (64, 5000)
    assert state.selected_label == "Custom"


def test_viewport_mode_normalizes_requested_size_and_fill() -> None:
    state = ViewportResolutionState(
        mode=RESOLUTION_MODE_VIEWPORT,
        requested_size=(1920, 1080),
        fill_viewport=True,
        selected_label="  ",
    )

    assert state.requested_size == (0, 0)
    assert state.fill_viewport is False
    assert state.selected_label == "Viewport"


def test_effective_size_slot_clamps_to_limits_when_supplied() -> None:
    state = ViewportResolutionState(
        effective_size=(20, 5000),
    )

    assert state.effective_size == (64, 2160)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "invalid"},
        {"mode": RESOLUTION_MODE_FIXED, "requested_size": (0, 0)},
        {"scale": 0.0},
        {"scale": float("inf")},
        {"fill_viewport": 1},
        {"uses_dpi": 1},
        {"selected_label": object()},
        {"effective_size": (-1, 720)},
    ],
)
def test_invalid_state_values_are_rejected_at_contract_boundary(kwargs) -> None:
    with pytest.raises(ViewportResolutionStateError):
        ViewportResolutionState(**kwargs)


def test_invalid_clamp_limits_are_rejected() -> None:
    with pytest.raises(ViewportResolutionStateError):
        ResolutionClampLimits(min_width=64, min_height=64, max_width=32, max_height=2160)


def test_state_is_immutable_after_read() -> None:
    state = ViewportResolutionState.default()

    with pytest.raises(FrozenInstanceError):
        state.scale = 2.0  # type: ignore[misc]


def test_no_private_render_size_access_rule_points_to_state_api() -> None:
    assert "get_resolution_state()" in PRIVATE_RENDER_SIZE_ACCESS_RULE
    assert "_last_resolution" in PRIVATE_RENDER_SIZE_ACCESS_RULE
    assert "_last_resolution" in (ViewportWidget.get_resolution_state.__doc__ or "")
