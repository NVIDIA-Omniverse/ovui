# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the SRD section 6 viewport resolution settings schema."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from ovui_widgets.viewport import (
    DEFAULT_MIN_RESOLUTION,
    DEFAULT_RENDER_SCALE_LIST,
    DEFAULT_RESOLUTION_PRESETS,
    DEFAULT_SETTINGS_VIEWPORT_ID,
    DEFAULT_VIEWPORT_FILL_VIEWPORT,
    DEFAULT_VIEWPORT_ID,
    DEFAULT_VIEWPORT_RESOLUTION,
    DEFAULT_VIEWPORT_RESOLUTION_SCALE,
    PERSISTENCE_PERSISTENT,
    PERSISTENCE_SHARED_DEFAULT,
    PERSISTENCE_STABLE_IDENTITY,
    SHAPE_BOOL,
    SHAPE_CUSTOM_RESOLUTION_LIST,
    SHAPE_FLAT_SIZE_LIST,
    SHAPE_FLOAT,
    SHAPE_RENDER_SCALE_LIST,
    SHAPE_SIZE_PAIR,
    SHAPE_VIEWPORT_ID,
    SETTING_CUSTOM_RESOLUTION_LIST,
    SETTING_DEFAULT_FILL_VIEWPORT,
    SETTING_DEFAULT_RESOLUTION,
    SETTING_DEFAULT_RESOLUTION_SCALE,
    SETTING_MIN_RESOLUTION,
    SETTING_RENDER_SCALE_LIST,
    SETTING_RESOLUTION_PRESETS,
    SETTING_VIEWPORT_INSTANCE_FILL_VIEWPORT,
    SETTING_VIEWPORT_INSTANCE_ID,
    SETTING_VIEWPORT_INSTANCE_RESOLUTION,
    SETTING_VIEWPORT_INSTANCE_RESOLUTION_SCALE,
    SETTING_VIEWPORT_INSTANCE_RESOLUTION_USES_DPI,
    VALUE_SOURCE_DPI_UNAVAILABLE,
    VALUE_SOURCE_INHERITED_SHARED_DEFAULT,
    VALUE_SOURCE_INSTANCE_OVERRIDE,
    VALUE_SOURCE_SCHEMA_DEFAULT,
    VALUE_SOURCE_SHARED_DEFAULT,
    AREA1_PERSISTENCE_QA_ENV,
    AREA1_SETTINGS_NOTIFICATION_QA_ENV,
    AREA1_SETTINGS_SCHEMA_QA_ENV,
    ResolutionSettingsChange,
    ViewportWidget,
    add_shared_custom_resolution_entry,
    format_resolution_settings_qa_lines,
    iter_resolution_setting_specs,
    normalize_custom_resolution_entry,
    normalize_custom_resolution_list,
    normalize_loaded_custom_resolution_list,
    normalize_resolution_setting_change_value,
    resolution_settings_persistent_keys,
    resolution_settings_observed_keys,
    resolution_settings_shared_default_keys,
    resolve_viewport_resolution_settings,
    subscribe_resolution_settings_changes,
    viewport_fill_viewport_key,
    viewport_resolution_key,
    viewport_resolution_scale_key,
    viewport_resolution_uses_dpi_key,
    write_shared_custom_resolution_list,
    write_viewport_instance_fill_viewport,
    write_viewport_instance_resolution,
    write_viewport_instance_resolution_scale,
    write_viewport_instance_resolution_uses_dpi,
)


class RecordingSettings:
    def __init__(self, data=None) -> None:
        self.data = dict(data or {})
        self.get_calls: list[tuple[str, object]] = []
        self.set_calls: list[tuple[str, object]] = []

    def get(self, key, default=None):
        self.get_calls.append((key, default))
        return self.data.get(key, default)

    def set(self, key, value):
        self.set_calls.append((key, value))
        self.data[key] = value


class _ObservableSubscription:
    def __init__(self, settings, key, callback) -> None:
        self._settings = settings
        self._key = key
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        callbacks = self._settings.subscribers.get(self._key, [])
        if self._callback in callbacks:
            callbacks.remove(self._callback)


class ObservableRecordingSettings(RecordingSettings):
    def __init__(self, data=None) -> None:
        super().__init__(data)
        self.subscribers: dict[str, list] = {}

    def set(self, key, value):
        old = self.data.get(key, object())
        if key in self.data and old == value:
            return
        super().set(key, value)
        for callback in list(self.subscribers.get(key, [])):
            callback(key, value)

    def subscribe(self, key, callback):
        self.subscribers.setdefault(key, []).append(callback)
        return _ObservableSubscription(self, key, callback)


def _schema_by_key():
    return {spec.key: spec for spec in iter_resolution_setting_specs()}


def test_schema_matches_srd_section_6_defaults_shapes_and_persistence() -> None:
    schema = _schema_by_key()

    assert tuple(schema) == (
        SETTING_RESOLUTION_PRESETS,
        SETTING_CUSTOM_RESOLUTION_LIST,
        SETTING_MIN_RESOLUTION,
        SETTING_RENDER_SCALE_LIST,
        SETTING_DEFAULT_RESOLUTION,
        SETTING_DEFAULT_RESOLUTION_SCALE,
        SETTING_DEFAULT_FILL_VIEWPORT,
        SETTING_VIEWPORT_INSTANCE_RESOLUTION,
        SETTING_VIEWPORT_INSTANCE_RESOLUTION_SCALE,
        SETTING_VIEWPORT_INSTANCE_FILL_VIEWPORT,
        SETTING_VIEWPORT_INSTANCE_RESOLUTION_USES_DPI,
        SETTING_VIEWPORT_INSTANCE_ID,
    )
    assert schema[SETTING_RESOLUTION_PRESETS].default_value() == list(
        DEFAULT_RESOLUTION_PRESETS
    )
    assert schema[SETTING_RESOLUTION_PRESETS].shape == SHAPE_FLAT_SIZE_LIST
    assert schema[SETTING_RESOLUTION_PRESETS].persistence == PERSISTENCE_SHARED_DEFAULT

    assert schema[SETTING_CUSTOM_RESOLUTION_LIST].default_value() == []
    assert schema[SETTING_CUSTOM_RESOLUTION_LIST].shape == SHAPE_CUSTOM_RESOLUTION_LIST
    assert schema[SETTING_CUSTOM_RESOLUTION_LIST].persistence == PERSISTENCE_PERSISTENT

    assert schema[SETTING_MIN_RESOLUTION].default_value() == list(
        DEFAULT_MIN_RESOLUTION
    )
    assert schema[SETTING_MIN_RESOLUTION].shape == SHAPE_SIZE_PAIR
    assert schema[SETTING_MIN_RESOLUTION].persistence == PERSISTENCE_SHARED_DEFAULT

    assert schema[SETTING_RENDER_SCALE_LIST].default_value() == list(
        DEFAULT_RENDER_SCALE_LIST
    )
    assert schema[SETTING_RENDER_SCALE_LIST].shape == SHAPE_RENDER_SCALE_LIST
    assert schema[SETTING_RENDER_SCALE_LIST].persistence == PERSISTENCE_SHARED_DEFAULT

    assert schema[SETTING_DEFAULT_RESOLUTION].default_value() == list(
        DEFAULT_VIEWPORT_RESOLUTION
    )
    assert schema[SETTING_DEFAULT_RESOLUTION].shape == SHAPE_SIZE_PAIR
    assert schema[SETTING_DEFAULT_RESOLUTION].persistence == PERSISTENCE_SHARED_DEFAULT

    assert (
        schema[SETTING_DEFAULT_RESOLUTION_SCALE].default_value()
        == DEFAULT_VIEWPORT_RESOLUTION_SCALE
    )
    assert schema[SETTING_DEFAULT_RESOLUTION_SCALE].shape == SHAPE_FLOAT
    assert (
        schema[SETTING_DEFAULT_RESOLUTION_SCALE].persistence
        == PERSISTENCE_SHARED_DEFAULT
    )

    assert (
        schema[SETTING_DEFAULT_FILL_VIEWPORT].default_value()
        is DEFAULT_VIEWPORT_FILL_VIEWPORT
    )
    assert schema[SETTING_DEFAULT_FILL_VIEWPORT].shape == SHAPE_BOOL
    assert (
        schema[SETTING_DEFAULT_FILL_VIEWPORT].persistence
        == PERSISTENCE_SHARED_DEFAULT
    )

    assert schema[SETTING_VIEWPORT_INSTANCE_RESOLUTION].default_value() == list(
        DEFAULT_VIEWPORT_RESOLUTION
    )
    assert schema[SETTING_VIEWPORT_INSTANCE_RESOLUTION].shape == SHAPE_SIZE_PAIR
    assert (
        schema[SETTING_VIEWPORT_INSTANCE_RESOLUTION].persistence
        == PERSISTENCE_PERSISTENT
    )
    assert (
        schema[SETTING_VIEWPORT_INSTANCE_RESOLUTION].inherited_from
        == SETTING_DEFAULT_RESOLUTION
    )

    assert (
        schema[SETTING_VIEWPORT_INSTANCE_RESOLUTION_SCALE].default_value()
        == DEFAULT_VIEWPORT_RESOLUTION_SCALE
    )
    assert schema[SETTING_VIEWPORT_INSTANCE_RESOLUTION_SCALE].shape == SHAPE_FLOAT
    assert (
        schema[SETTING_VIEWPORT_INSTANCE_RESOLUTION_SCALE].persistence
        == PERSISTENCE_PERSISTENT
    )
    assert (
        schema[SETTING_VIEWPORT_INSTANCE_RESOLUTION_SCALE].inherited_from
        == SETTING_DEFAULT_RESOLUTION_SCALE
    )

    assert (
        schema[SETTING_VIEWPORT_INSTANCE_FILL_VIEWPORT].default_value()
        is DEFAULT_VIEWPORT_FILL_VIEWPORT
    )
    assert schema[SETTING_VIEWPORT_INSTANCE_FILL_VIEWPORT].shape == SHAPE_BOOL
    assert (
        schema[SETTING_VIEWPORT_INSTANCE_FILL_VIEWPORT].persistence
        == PERSISTENCE_PERSISTENT
    )
    assert (
        schema[SETTING_VIEWPORT_INSTANCE_FILL_VIEWPORT].inherited_from
        == SETTING_DEFAULT_FILL_VIEWPORT
    )

    assert schema[SETTING_VIEWPORT_INSTANCE_RESOLUTION_USES_DPI].default_value() is True
    assert schema[SETTING_VIEWPORT_INSTANCE_RESOLUTION_USES_DPI].shape == SHAPE_BOOL
    assert (
        schema[SETTING_VIEWPORT_INSTANCE_RESOLUTION_USES_DPI].persistence
        == PERSISTENCE_PERSISTENT
    )

    assert (
        schema[SETTING_VIEWPORT_INSTANCE_ID].default_value()
        == DEFAULT_SETTINGS_VIEWPORT_ID
    )
    assert schema[SETTING_VIEWPORT_INSTANCE_ID].shape == SHAPE_VIEWPORT_ID
    assert schema[SETTING_VIEWPORT_INSTANCE_ID].persistence == PERSISTENCE_STABLE_IDENTITY


def test_persistence_classification_limits_normal_resolution_writes() -> None:
    assert resolution_settings_persistent_keys() == (
        SETTING_CUSTOM_RESOLUTION_LIST,
        SETTING_VIEWPORT_INSTANCE_RESOLUTION,
        SETTING_VIEWPORT_INSTANCE_RESOLUTION_SCALE,
        SETTING_VIEWPORT_INSTANCE_FILL_VIEWPORT,
        SETTING_VIEWPORT_INSTANCE_RESOLUTION_USES_DPI,
    )
    assert resolution_settings_shared_default_keys() == (
        SETTING_RESOLUTION_PRESETS,
        SETTING_MIN_RESOLUTION,
        SETTING_RENDER_SCALE_LIST,
        SETTING_DEFAULT_RESOLUTION,
        SETTING_DEFAULT_RESOLUTION_SCALE,
        SETTING_DEFAULT_FILL_VIEWPORT,
    )


def test_empty_store_resolves_every_srd_default_without_writing() -> None:
    settings = RecordingSettings()

    resolved = resolve_viewport_resolution_settings(
        settings,
        viewport_id=None,
        dpi_scale_available=True,
        dpi_scale=1.0,
    )

    assert resolved.viewport_id == DEFAULT_SETTINGS_VIEWPORT_ID
    assert resolved.presets == list(DEFAULT_RESOLUTION_PRESETS)
    assert resolved.custom_list == []
    assert resolved.min_resolution == list(DEFAULT_MIN_RESOLUTION)
    assert resolved.render_scale_list == list(DEFAULT_RENDER_SCALE_LIST)
    assert resolved.default_resolution == list(DEFAULT_VIEWPORT_RESOLUTION)
    assert resolved.default_resolution_scale == DEFAULT_VIEWPORT_RESOLUTION_SCALE
    assert resolved.default_fill_viewport is DEFAULT_VIEWPORT_FILL_VIEWPORT
    assert resolved.resolution == list(DEFAULT_VIEWPORT_RESOLUTION)
    assert resolved.resolution_scale == DEFAULT_VIEWPORT_RESOLUTION_SCALE
    assert resolved.fill_viewport is DEFAULT_VIEWPORT_FILL_VIEWPORT
    assert resolved.resolution_uses_dpi is True
    assert resolved.dpi_scale == 1.0
    assert settings.set_calls == []
    assert settings.data == {}


def test_instance_values_inherit_shared_defaults_without_writing() -> None:
    settings = RecordingSettings(
        {
            SETTING_DEFAULT_RESOLUTION: [1920, 1080],
            SETTING_DEFAULT_RESOLUTION_SCALE: 0.5,
            SETTING_DEFAULT_FILL_VIEWPORT: True,
        }
    )

    resolved = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )

    assert resolved.default_resolution == [1920, 1080]
    assert resolved.default_resolution_scale == 0.5
    assert resolved.default_fill_viewport is True
    assert resolved.resolution == [1920, 1080]
    assert resolved.resolution_scale == 0.5
    assert resolved.fill_viewport is True
    assert resolved.default_resolution_source == VALUE_SOURCE_SHARED_DEFAULT
    assert resolved.default_resolution_scale_source == VALUE_SOURCE_SHARED_DEFAULT
    assert resolved.default_fill_viewport_source == VALUE_SOURCE_SHARED_DEFAULT
    assert resolved.resolution_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert resolved.resolution_scale_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert resolved.fill_viewport_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert settings.set_calls == []


def test_per_viewport_persistent_values_override_shared_defaults() -> None:
    settings = RecordingSettings(
        {
            SETTING_DEFAULT_RESOLUTION: [0, 0],
            SETTING_DEFAULT_RESOLUTION_SCALE: 1.0,
            SETTING_DEFAULT_FILL_VIEWPORT: False,
            viewport_resolution_key("review"): [2560, 1440],
            viewport_resolution_scale_key("review"): 0.666666666666,
            viewport_fill_viewport_key("review"): True,
            viewport_resolution_uses_dpi_key("review"): False,
        }
    )

    resolved = resolve_viewport_resolution_settings(
        settings,
        viewport_id="review",
        dpi_scale_available=True,
        dpi_scale=2.0,
    )

    assert resolved.viewport_id == "review"
    assert resolved.resolution == [2560, 1440]
    assert resolved.resolution_scale == 0.666666666666
    assert resolved.fill_viewport is True
    assert resolved.resolution_uses_dpi is False
    assert resolved.dpi_scale == 2.0
    assert resolved.resolution_source == VALUE_SOURCE_INSTANCE_OVERRIDE
    assert resolved.resolution_scale_source == VALUE_SOURCE_INSTANCE_OVERRIDE
    assert resolved.fill_viewport_source == VALUE_SOURCE_INSTANCE_OVERRIDE
    assert resolved.resolution_uses_dpi_source == VALUE_SOURCE_INSTANCE_OVERRIDE
    assert settings.set_calls == []


def test_dpi_unavailable_defaults_false_and_scale_one() -> None:
    settings = RecordingSettings({viewport_resolution_uses_dpi_key("main"): True})

    resolved = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main",
        dpi_scale_available=False,
        dpi_scale=2.0,
    )

    assert resolved.resolution_uses_dpi is False
    assert resolved.dpi_scale == 1.0
    assert resolved.resolution_uses_dpi_source == VALUE_SOURCE_DPI_UNAVAILABLE
    assert settings.set_calls == []


def test_default_to_instance_lookup_order_and_source_reporting() -> None:
    settings = RecordingSettings(
        {
            SETTING_DEFAULT_RESOLUTION: [1280, 720],
            SETTING_DEFAULT_RESOLUTION_SCALE: 0.5,
            SETTING_DEFAULT_FILL_VIEWPORT: True,
            viewport_resolution_scale_key("main"): 1.0,
        }
    )

    resolved = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )

    assert resolved.resolution == [1280, 720]
    assert resolved.resolution_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert resolved.resolution_scale == 1.0
    assert resolved.resolution_scale_source == VALUE_SOURCE_INSTANCE_OVERRIDE
    assert resolved.fill_viewport is True
    assert resolved.fill_viewport_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert settings.set_calls == []


def test_single_key_scale_write_does_not_touch_unrelated_keys() -> None:
    existing_resolution = [1280, 720]
    settings = RecordingSettings({viewport_resolution_key("main"): existing_resolution})

    written_key = write_viewport_instance_resolution_scale(settings, "main", 1.0)

    assert written_key == viewport_resolution_scale_key("main")
    assert settings.set_calls == [(viewport_resolution_scale_key("main"), 1.0)]
    assert settings.data[viewport_resolution_key("main")] == existing_resolution
    assert settings.data[viewport_resolution_scale_key("main")] == 1.0
    assert viewport_fill_viewport_key("main") not in settings.data
    assert SETTING_DEFAULT_RESOLUTION not in settings.data
    assert SETTING_DEFAULT_RESOLUTION_SCALE not in settings.data
    assert SETTING_DEFAULT_FILL_VIEWPORT not in settings.data


def test_identity_scoped_instance_writes_do_not_touch_other_viewports() -> None:
    settings = RecordingSettings()

    resolution_key = write_viewport_instance_resolution(
        settings,
        "main",
        [1920, 1080],
    )
    scale_key = write_viewport_instance_resolution_scale(settings, "main", 0.5)
    fill_key = write_viewport_instance_fill_viewport(settings, "main", True)
    dpi_key = write_viewport_instance_resolution_uses_dpi(settings, "main", False)

    assert settings.set_calls == [
        (resolution_key, [1920, 1080]),
        (scale_key, 0.5),
        (fill_key, True),
        (dpi_key, False),
    ]
    assert viewport_resolution_key("main_2") not in settings.data
    assert viewport_resolution_scale_key("main_2") not in settings.data
    assert viewport_fill_viewport_key("main_2") not in settings.data
    assert viewport_resolution_uses_dpi_key("main_2") not in settings.data

    first = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )
    second = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main_2",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )

    assert first.resolution == [1920, 1080]
    assert first.resolution_scale == 0.5
    assert first.fill_viewport is True
    assert first.resolution_uses_dpi is False
    assert first.resolution_source == VALUE_SOURCE_INSTANCE_OVERRIDE
    assert second.resolution == [0, 0]
    assert second.resolution_scale == 1.0
    assert second.fill_viewport is False
    assert second.resolution_uses_dpi is True
    assert second.resolution_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT


def test_shared_lists_fan_out_to_all_viewport_identities() -> None:
    settings = RecordingSettings(
        {
            SETTING_RESOLUTION_PRESETS: [1920, 1080, 1280, 720],
            SETTING_MIN_RESOLUTION: [64, 64],
            SETTING_RENDER_SCALE_LIST: [1.0, 0.5],
        }
    )
    custom_item = {"name": "Shared Review", "width": 1500, "height": 1000}

    written_key = write_shared_custom_resolution_list(settings, [custom_item])

    assert written_key == SETTING_CUSTOM_RESOLUTION_LIST
    assert settings.set_calls == [
        (SETTING_CUSTOM_RESOLUTION_LIST, [custom_item]),
    ]
    first = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )
    second = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main_2",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )

    assert first.custom_list == [custom_item]
    assert second.custom_list == [custom_item]
    assert first.custom_list is not second.custom_list
    assert first.presets == [1920, 1080, 1280, 720]
    assert second.presets == [1920, 1080, 1280, 720]
    assert first.render_scale_list == [1.0, 0.5]
    assert second.render_scale_list == [1.0, 0.5]


def test_resolution_settings_observed_keys_cover_area_1_surface() -> None:
    assert resolution_settings_observed_keys("main") == (
        SETTING_RESOLUTION_PRESETS,
        SETTING_CUSTOM_RESOLUTION_LIST,
        SETTING_MIN_RESOLUTION,
        SETTING_RENDER_SCALE_LIST,
        SETTING_DEFAULT_RESOLUTION,
        SETTING_DEFAULT_RESOLUTION_SCALE,
        SETTING_DEFAULT_FILL_VIEWPORT,
        viewport_resolution_key("main"),
        viewport_resolution_scale_key("main"),
        viewport_fill_viewport_key("main"),
        viewport_resolution_uses_dpi_key("main"),
    )


def test_resolution_settings_subscription_notifies_changed_key_and_value() -> None:
    settings = ObservableRecordingSettings()
    events: list[ResolutionSettingsChange] = []
    subscription = subscribe_resolution_settings_changes(
        settings,
        "main",
        events.append,
    )

    try:
        write_viewport_instance_resolution_scale(settings, "main", 0.5)
    finally:
        subscription.cancel()

    assert len(events) == 1
    assert events[0].key == viewport_resolution_scale_key("main")
    assert events[0].value == 0.5
    assert events[0].viewport_id == "main"


def test_resolution_settings_notification_payload_is_post_normalization() -> None:
    valid = {"name": "Review", "width": 1500, "height": 1000}
    settings = ObservableRecordingSettings()
    events: list[ResolutionSettingsChange] = []
    subscription = subscribe_resolution_settings_changes(
        settings,
        "main",
        events.append,
    )

    try:
        settings.set(
            SETTING_CUSTOM_RESOLUTION_LIST,
            [
                valid,
                {"name": "Review", "width": 1700, "height": 1000},
                {"name": "Duplicate Dims", "width": 1500, "height": 1000},
                {"name": "", "width": 1200, "height": 800},
            ],
        )
    finally:
        subscription.cancel()

    assert len(events) == 1
    assert events[0].key == SETTING_CUSTOM_RESOLUTION_LIST
    assert events[0].value == [valid]


def test_resolution_settings_subscription_suppresses_unchanged_normalized_writes() -> None:
    valid = {"name": "Review", "width": 1500, "height": 1000}
    settings = ObservableRecordingSettings({SETTING_CUSTOM_RESOLUTION_LIST: [valid]})
    events: list[ResolutionSettingsChange] = []
    subscription = subscribe_resolution_settings_changes(
        settings,
        "main",
        events.append,
    )

    try:
        settings.set(
            SETTING_CUSTOM_RESOLUTION_LIST,
            [
                valid,
                {"name": "Duplicate Name", "width": 1500, "height": 1000},
                {"name": "", "width": 1200, "height": 800},
            ],
        )
        settings.set(
            SETTING_CUSTOM_RESOLUTION_LIST,
            [
                valid,
                ["Unsupported", 1200, 800],
            ],
        )
    finally:
        subscription.cancel()

    assert events == []


def test_resolution_settings_subscription_unsubscribe_stops_later_events() -> None:
    settings = ObservableRecordingSettings()
    events: list[ResolutionSettingsChange] = []
    subscription = subscribe_resolution_settings_changes(
        settings,
        "main",
        events.append,
    )
    subscription.unsubscribe()

    write_viewport_instance_resolution_scale(settings, "main", 0.5)

    assert events == []


def test_resolution_settings_subscription_scopes_instance_keys_per_viewport() -> None:
    settings = ObservableRecordingSettings()
    events: list[ResolutionSettingsChange] = []
    subscription = subscribe_resolution_settings_changes(
        settings,
        "main",
        events.append,
    )

    try:
        write_viewport_instance_resolution_scale(settings, "main_2", 0.5)
        write_viewport_instance_resolution_scale(settings, "main", 0.5)
    finally:
        subscription.cancel()

    assert [(event.key, event.value) for event in events] == [
        (viewport_resolution_scale_key("main"), 0.5)
    ]


def test_resolution_settings_subscription_notifies_shared_keys_to_viewport_scope() -> None:
    settings = ObservableRecordingSettings()
    events: list[ResolutionSettingsChange] = []
    subscription = subscribe_resolution_settings_changes(
        settings,
        "main_2",
        events.append,
    )

    try:
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Shared", "width": 1200, "height": 800}],
        )
    finally:
        subscription.cancel()

    assert len(events) == 1
    assert events[0].key == SETTING_CUSTOM_RESOLUTION_LIST
    assert events[0].value == [{"name": "Shared", "width": 1200, "height": 800}]
    assert events[0].viewport_id == "main_2"


def test_resolution_settings_subscription_does_not_require_recursive_writeback() -> None:
    settings = ObservableRecordingSettings()
    events: list[ResolutionSettingsChange] = []
    subscription = subscribe_resolution_settings_changes(
        settings,
        "main",
        events.append,
    )

    try:
        write_viewport_instance_fill_viewport(settings, "main", True)
    finally:
        subscription.cancel()

    assert len(events) == 1
    assert settings.set_calls == [(viewport_fill_viewport_key("main"), True)]


def test_viewport_destroy_cancels_notification_qa_subscription(monkeypatch) -> None:
    monkeypatch.setenv(AREA1_SETTINGS_SCHEMA_QA_ENV, "1")
    monkeypatch.setenv(AREA1_PERSISTENCE_QA_ENV, "1")
    monkeypatch.setenv(AREA1_SETTINGS_NOTIFICATION_QA_ENV, "1")
    settings = ObservableRecordingSettings()
    services = SimpleNamespace(settings=settings, selection_bus=None)
    viewport = ViewportWidget(services=services, renderer=None)
    viewport_id = viewport.viewport_id

    viewport._open_resolution_settings_notification_qa_window()
    assert viewport._resolution_settings_notification_qa_subscription is not None

    viewport.destroy()
    write_viewport_instance_resolution_scale(settings, viewport_id, 0.5)

    assert viewport._resolution_settings_notification_qa_window is None
    assert all(not callbacks for callbacks in settings.subscribers.values())


def test_normalize_resolution_setting_change_value_handles_malformed_raw_data() -> None:
    settings = RecordingSettings(
        {
            SETTING_DEFAULT_RESOLUTION: [1280, 720],
            viewport_resolution_key("main"): ["bad"],
        }
    )

    assert normalize_resolution_setting_change_value(
        settings,
        viewport_resolution_key("main"),
        viewport_id="main",
    ) == [1280, 720]


def test_custom_resolution_list_storage_normalizes_valid_entries() -> None:
    settings = RecordingSettings()
    entries = [
        {"name": "  Preview Square  ", "width": 1500, "height": 1500},
        {"name": "Client 4K", "width": 3840, "height": 2160},
    ]

    written_key = write_shared_custom_resolution_list(settings, entries)

    normalized = [
        {"name": "Preview Square", "width": 1500, "height": 1500},
        {"name": "Client 4K", "width": 3840, "height": 2160},
    ]
    assert written_key == SETTING_CUSTOM_RESOLUTION_LIST
    assert settings.set_calls == [(SETTING_CUSTOM_RESOLUTION_LIST, normalized)]
    assert settings.data[SETTING_CUSTOM_RESOLUTION_LIST] == normalized
    assert resolve_viewport_resolution_settings(settings).custom_list == normalized


def test_add_custom_resolution_entry_appends_in_stable_order() -> None:
    settings = RecordingSettings(
        {
            SETTING_CUSTOM_RESOLUTION_LIST: [
                {"name": "Preview Square", "width": 1500, "height": 1500},
            ]
        }
    )

    written_key = add_shared_custom_resolution_entry(
        settings,
        {"name": "Client 4K", "width": 3840, "height": 2160},
    )

    expected = [
        {"name": "Preview Square", "width": 1500, "height": 1500},
        {"name": "Client 4K", "width": 3840, "height": 2160},
    ]
    assert written_key == SETTING_CUSTOM_RESOLUTION_LIST
    assert settings.data[SETTING_CUSTOM_RESOLUTION_LIST] == expected
    assert settings.set_calls == [(SETTING_CUSTOM_RESOLUTION_LIST, expected)]


@pytest.mark.parametrize(
    "entry",
    [
        {"name": "", "width": 1500, "height": 1500},
        {"name": "   ", "width": 1500, "height": 1500},
        {"name": "Preview Square", "width": 0, "height": 1500},
        {"name": "Preview Square", "width": 1500, "height": -1},
        {"name": "Preview Square", "width": "1500", "height": 1500},
        {"name": "Preview Square", "width": 1500, "height": 1500.0},
        {"name": "Preview Square", "width": True, "height": 1500},
        ["Preview Square", 1500, 1500],
    ],
)
def test_custom_resolution_entries_reject_empty_or_non_positive_values(entry) -> None:
    existing = [{"name": "Existing", "width": 800, "height": 600}]
    settings = RecordingSettings({SETTING_CUSTOM_RESOLUTION_LIST: existing})

    with pytest.raises(ValueError):
        add_shared_custom_resolution_entry(settings, entry)

    assert settings.set_calls == []
    assert settings.data[SETTING_CUSTOM_RESOLUTION_LIST] == existing


def test_custom_resolution_normalized_output_is_json_compatible() -> None:
    normalized = normalize_custom_resolution_entry(
        {
            "name": "  Preview Square  ",
            "width": 1500,
            "height": 1500,
            "ignored": object(),
        }
    )

    assert normalized == {"name": "Preview Square", "width": 1500, "height": 1500}
    assert list(normalized) == ["name", "width", "height"]
    assert json.loads(json.dumps(normalized)) == normalized


def test_custom_resolution_list_normalization_stays_shared_across_identities() -> None:
    settings = RecordingSettings()
    normalized = normalize_custom_resolution_list(
        [
            {"name": "Preview Square", "width": 1500, "height": 1500},
            {"name": "Client 4K", "width": 3840, "height": 2160},
        ]
    )
    write_shared_custom_resolution_list(settings, normalized)

    first = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )
    second = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main_2",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )

    assert first.custom_list == normalized
    assert second.custom_list == normalized
    assert first.custom_list is not second.custom_list


@pytest.mark.parametrize(
    ("case", "custom_list"),
    [
        ("missing name", [{"width": 1200, "height": 800}]),
        ("missing width", [{"name": "Missing Width", "height": 800}]),
        ("missing height", [{"name": "Missing Height", "width": 1200}]),
        ("blank name", [{"name": "   ", "width": 1200, "height": 800}]),
        ("non-string name", [{"name": 123, "width": 1200, "height": 800}]),
        ("string width", [{"name": "String Width", "width": "1200", "height": 800}]),
        ("float height", [{"name": "Float Height", "width": 1200, "height": 800.0}]),
        ("bool width", [{"name": "Bool Width", "width": True, "height": 800}]),
        ("zero width", [{"name": "Zero Width", "width": 0, "height": 800}]),
        ("negative height", [{"name": "Negative Height", "width": 1200, "height": -1}]),
        ("unsupported list", [["Unsupported", 1200, 800]]),
        ("unsupported string", ["Unsupported"]),
    ],
)
def test_loaded_custom_resolution_list_drops_malformed_entries(
    case,
    custom_list,
) -> None:
    valid = {"name": "Only Valid", "width": 1600, "height": 900}

    assert normalize_loaded_custom_resolution_list([valid, *custom_list]) == [valid]


def test_loaded_custom_resolution_list_suppresses_duplicate_names_keep_first() -> None:
    first = {"name": "Review", "width": 1600, "height": 900}
    duplicate_name = {"name": "  Review  ", "width": 1700, "height": 900}
    later = {"name": "Second", "width": 1800, "height": 1000}

    assert normalize_loaded_custom_resolution_list(
        [first, duplicate_name, later]
    ) == [first, later]


def test_loaded_custom_resolution_list_suppresses_duplicate_dimensions_keep_first() -> None:
    first = {"name": "Review", "width": 1600, "height": 900}
    duplicate_dimensions = {"name": "Duplicate Dims", "width": 1600, "height": 900}
    later = {"name": "Second", "width": 1800, "height": 1000}

    assert normalize_loaded_custom_resolution_list(
        [first, duplicate_dimensions, later]
    ) == [first, later]


def test_loaded_custom_resolution_list_preserves_valid_order_while_dropping_bad() -> None:
    first = {"name": "First", "width": 1111, "height": 777}
    second = {"name": "Second", "width": 2222, "height": 888}
    third = {"name": "Third", "width": 3333, "height": 999}

    assert normalize_loaded_custom_resolution_list(
        [
            first,
            {"name": "", "width": 1200, "height": 800},
            second,
            ["Unsupported", 1200, 800],
            third,
        ]
    ) == [first, second, third]


def test_loaded_custom_resolution_list_all_invalid_returns_empty_without_raising() -> None:
    assert normalize_loaded_custom_resolution_list(
        [
            {"name": "", "width": 1200, "height": 800},
            {"name": "Missing Width", "height": 800},
            {"name": "Bool Height", "width": 1200, "height": False},
            ["Unsupported", 1200, 800],
        ]
    ) == []
    assert normalize_loaded_custom_resolution_list({"name": "Not A List"}) == []


def test_resolver_uses_tolerant_loaded_custom_list_without_writing() -> None:
    valid = {"name": "Only Valid", "width": 1600, "height": 900}
    settings = RecordingSettings(
        {
            SETTING_CUSTOM_RESOLUTION_LIST: [
                valid,
                {"name": "Only Valid", "width": 1700, "height": 900},
                {"name": "Duplicate Dimensions", "width": 1600, "height": 900},
                {"name": "Zero Width", "width": 0, "height": 900},
                ["Unsupported", 1600, 900],
            ]
        }
    )

    resolved = resolve_viewport_resolution_settings(settings)

    assert resolved.custom_list == [valid]
    assert settings.set_calls == []


def test_strict_custom_add_path_still_raises_on_malformed_current_list() -> None:
    settings = RecordingSettings(
        {
            SETTING_CUSTOM_RESOLUTION_LIST: [
                {"name": "", "width": 1200, "height": 800},
            ]
        }
    )

    with pytest.raises(ValueError):
        add_shared_custom_resolution_entry(
            settings,
            {"name": "New Valid", "width": 1200, "height": 800},
        )

    assert settings.set_calls == []


def test_default_inheritance_is_scoped_per_viewport() -> None:
    settings = RecordingSettings(
        {
            SETTING_DEFAULT_RESOLUTION: [1280, 720],
            SETTING_DEFAULT_RESOLUTION_SCALE: 0.5,
            SETTING_DEFAULT_FILL_VIEWPORT: True,
        }
    )
    write_viewport_instance_resolution_scale(settings, "main", 1.0)

    first = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )
    second = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main_2",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )

    assert first.resolution == [1280, 720]
    assert first.resolution_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert first.resolution_scale == 1.0
    assert first.resolution_scale_source == VALUE_SOURCE_INSTANCE_OVERRIDE
    assert first.fill_viewport is True
    assert first.fill_viewport_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert second.resolution == [1280, 720]
    assert second.resolution_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert second.resolution_scale == 0.5
    assert second.resolution_scale_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert second.fill_viewport is True
    assert second.fill_viewport_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT


def test_viewport_teardown_does_not_delete_shared_custom_list() -> None:
    custom_item = {"name": "Shared Review", "width": 1500, "height": 1000}
    settings = RecordingSettings({SETTING_CUSTOM_RESOLUTION_LIST: [custom_item]})
    services = SimpleNamespace(settings=settings, selection_bus=None)
    first = ViewportWidget(services=services, renderer=None, viewport_id="review")
    second = ViewportWidget(services=services, renderer=None, viewport_id="review")
    try:
        assert first.viewport_id == "review"
        assert second.viewport_id == "review_2"
        assert first.get_resolution_settings().custom_list == [custom_item]
        assert second.get_resolution_settings().custom_list == [custom_item]

        second.destroy()

        assert settings.data[SETTING_CUSTOM_RESOLUTION_LIST] == [custom_item]
        assert first.get_resolution_settings().custom_list == [custom_item]
    finally:
        first.destroy()
        second.destroy()


def test_malformed_shared_defaults_fall_back_to_schema_defaults() -> None:
    settings = RecordingSettings(
        {
            SETTING_DEFAULT_RESOLUTION: ["bad"],
            SETTING_DEFAULT_RESOLUTION_SCALE: "bad",
            SETTING_DEFAULT_FILL_VIEWPORT: "bad",
        }
    )

    resolved = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )

    assert resolved.default_resolution == [0, 0]
    assert resolved.default_resolution_source == VALUE_SOURCE_SCHEMA_DEFAULT
    assert resolved.default_resolution_scale == 1.0
    assert resolved.default_resolution_scale_source == VALUE_SOURCE_SCHEMA_DEFAULT
    assert resolved.default_fill_viewport is False
    assert resolved.default_fill_viewport_source == VALUE_SOURCE_SCHEMA_DEFAULT
    assert resolved.resolution == [0, 0]
    assert resolved.resolution_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert resolved.resolution_scale == 1.0
    assert resolved.resolution_scale_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert resolved.fill_viewport is False
    assert resolved.fill_viewport_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert settings.set_calls == []


def test_malformed_instance_values_fall_back_to_shared_defaults() -> None:
    settings = RecordingSettings(
        {
            SETTING_DEFAULT_RESOLUTION: [1280, 720],
            SETTING_DEFAULT_RESOLUTION_SCALE: 0.5,
            SETTING_DEFAULT_FILL_VIEWPORT: True,
            viewport_resolution_key("main"): ["bad"],
            viewport_resolution_scale_key("main"): "bad",
            viewport_fill_viewport_key("main"): "bad",
        }
    )

    resolved = resolve_viewport_resolution_settings(
        settings,
        viewport_id="main",
        dpi_scale_available=True,
        dpi_scale=1.0,
    )

    assert resolved.resolution == [1280, 720]
    assert resolved.resolution_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert resolved.resolution_scale == 0.5
    assert resolved.resolution_scale_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert resolved.fill_viewport is True
    assert resolved.fill_viewport_source == VALUE_SOURCE_INHERITED_SHARED_DEFAULT
    assert settings.set_calls == []


def test_viewport_widget_read_accessor_uses_main_identity_fallback() -> None:
    vp = ViewportWidget(services=None, renderer=None)
    try:
        resolved = vp.get_resolution_settings(
            dpi_scale_available=True,
            dpi_scale=1.0,
        )

        assert vp.viewport_id == DEFAULT_VIEWPORT_ID
        assert resolved.viewport_id == DEFAULT_SETTINGS_VIEWPORT_ID
        assert resolved.resolution == [0, 0]
        assert resolved.resolution_scale == 1.0
        assert resolved.fill_viewport is False
    finally:
        vp.destroy()


def test_qa_formatter_exposes_resolved_schema_values() -> None:
    resolved = resolve_viewport_resolution_settings(
        RecordingSettings(),
        viewport_id="main",
        dpi_scale_available=False,
        dpi_scale=2.0,
    )

    lines = format_resolution_settings_qa_lines(
        resolved,
        profile_label="DPI unavailable",
    )

    assert "Resolution: [0, 0] (Viewport)" in lines
    assert "Scale: 1.0 (100%)" in lines
    assert f"Scale Source: {VALUE_SOURCE_INHERITED_SHARED_DEFAULT}" in lines
    assert "Fill Viewport: false" in lines
    assert f"Fill Source: {VALUE_SOURCE_INHERITED_SHARED_DEFAULT}" in lines
    assert "Custom List: []" in lines
    assert "Shared Custom Items: none" in lines
    assert "Min: 64x64" in lines
    assert (
        "Render Scale List: [2.0, 1.0, 0.666666666666, 0.5, "
        "0.333333333333, 0.25]"
    ) in lines
    assert "DPI Uses Scale: false (scale 1.0)" in lines
    assert f"DPI Source: {VALUE_SOURCE_DPI_UNAVAILABLE}" in lines


def _reset_application_singletons() -> None:
    from ovui_widgets.app.application import Application
    from ovui_widgets.common.selection import SelectionBus

    Application._instance = None
    SelectionBus._instance = None


def _new_persistence_app(monkeypatch, settings_path):
    from ovui_widgets.app.application import Application

    _reset_application_singletons()
    monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(settings_path))
    return Application()


def test_application_loads_resolution_settings_before_viewport_init(
    tmp_path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "settings.json"
    persisted_custom = {"name": "Review", "width": 1500, "height": 1000}
    settings_path.write_text(
        json.dumps(
            {
                SETTING_CUSTOM_RESOLUTION_LIST: [persisted_custom],
                viewport_resolution_key("main"): [1920, 1080],
                viewport_resolution_scale_key("main"): 0.5,
                viewport_fill_viewport_key("main"): True,
            }
        ),
        encoding="utf-8",
    )

    app = _new_persistence_app(monkeypatch, settings_path)
    viewport = ViewportWidget(services=app, renderer=None)
    try:
        resolved = viewport.get_resolution_settings()

        assert resolved.resolution == [1920, 1080]
        assert resolved.resolution_scale == 0.5
        assert resolved.fill_viewport is True
        assert resolved.custom_list == [persisted_custom]
    finally:
        viewport.destroy()
        app.shutdown()
        _reset_application_singletons()


def test_application_shutdown_saves_resolution_persistent_keys(
    tmp_path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "settings.json"
    app = _new_persistence_app(monkeypatch, settings_path)
    try:
        write_viewport_instance_resolution(app.settings, "main", [1920, 1080])
        write_viewport_instance_resolution_scale(app.settings, "main", 0.5)
        write_viewport_instance_fill_viewport(app.settings, "main", True)
        add_shared_custom_resolution_entry(
            app.settings,
            {"name": "Review", "width": 1500, "height": 1000},
        )

        app.shutdown()

        data = json.loads(settings_path.read_text(encoding="utf-8"))
        assert data[viewport_resolution_key("main")] == [1920, 1080]
        assert data[viewport_resolution_scale_key("main")] == 0.5
        assert data[viewport_fill_viewport_key("main")] is True
        assert data[SETTING_CUSTOM_RESOLUTION_LIST] == [
            {"name": "Review", "width": 1500, "height": 1000}
        ]
    finally:
        app.shutdown()
        _reset_application_singletons()


def test_application_restart_restores_resolution_persistent_keys(
    tmp_path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "settings.json"
    first = _new_persistence_app(monkeypatch, settings_path)
    try:
        write_viewport_instance_resolution(first.settings, "main", [1920, 1080])
        write_viewport_instance_resolution_scale(first.settings, "main", 0.5)
        write_viewport_instance_fill_viewport(first.settings, "main", True)
        add_shared_custom_resolution_entry(
            first.settings,
            {"name": "Review", "width": 1500, "height": 1000},
        )
        first.shutdown()
    finally:
        first.shutdown()
        _reset_application_singletons()

    second = _new_persistence_app(monkeypatch, settings_path)
    try:
        resolved = resolve_viewport_resolution_settings(
            second.settings,
            viewport_id="main",
            dpi_scale_available=True,
            dpi_scale=1.0,
        )

        assert resolved.resolution == [1920, 1080]
        assert resolved.resolution_scale == 0.5
        assert resolved.fill_viewport is True
        assert resolved.custom_list == [
            {"name": "Review", "width": 1500, "height": 1000}
        ]
    finally:
        second.shutdown()
        _reset_application_singletons()


def test_application_missing_persistent_data_falls_back_to_defaults(
    tmp_path,
    monkeypatch,
) -> None:
    app = _new_persistence_app(monkeypatch, tmp_path / "missing.json")
    try:
        resolved = resolve_viewport_resolution_settings(
            app.settings,
            viewport_id="main",
            dpi_scale_available=True,
            dpi_scale=1.0,
        )

        assert resolved.resolution == [0, 0]
        assert resolved.resolution_scale == 1.0
        assert resolved.fill_viewport is False
        assert resolved.custom_list == []
    finally:
        app.shutdown()
        _reset_application_singletons()


def test_application_load_applies_custom_list_normalization_and_invalid_fallback(
    tmp_path,
    monkeypatch,
) -> None:
    valid = {"name": "Valid Persisted", "width": 1600, "height": 900}
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            {
                SETTING_CUSTOM_RESOLUTION_LIST: [
                    valid,
                    {"name": "Valid Persisted", "width": 1700, "height": 900},
                    {"name": "Duplicate Dims", "width": 1600, "height": 900},
                    {"name": "", "width": 1200, "height": 800},
                    ["Unsupported", 1200, 800],
                ],
                viewport_resolution_key("main"): ["invalid"],
                viewport_resolution_scale_key("main"): "invalid",
                viewport_fill_viewport_key("main"): "invalid",
            }
        ),
        encoding="utf-8",
    )

    app = _new_persistence_app(monkeypatch, settings_path)
    try:
        resolved = resolve_viewport_resolution_settings(
            app.settings,
            viewport_id="main",
            dpi_scale_available=True,
            dpi_scale=1.0,
        )

        assert resolved.custom_list == [valid]
        assert resolved.resolution == [0, 0]
        assert resolved.resolution_scale == 1.0
        assert resolved.fill_viewport is False
    finally:
        app.shutdown()
        _reset_application_singletons()
