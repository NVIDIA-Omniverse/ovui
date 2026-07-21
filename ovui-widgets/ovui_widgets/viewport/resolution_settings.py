# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""SRD section 6 viewport resolution settings schema and resolver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

DEFAULT_SETTINGS_VIEWPORT_ID = "main"

SETTING_RESOLUTION_PRESETS = "viewport.resolution.presets"
SETTING_CUSTOM_RESOLUTION_LIST = "viewport.resolution.custom.list"
SETTING_MIN_RESOLUTION = "viewport.resolution.min"
SETTING_RENDER_SCALE_LIST = "viewport.resolution.render_scale_list"
SETTING_DEFAULT_RESOLUTION = "viewport.defaults.resolution"
SETTING_DEFAULT_RESOLUTION_SCALE = "viewport.defaults.resolution_scale"
SETTING_DEFAULT_FILL_VIEWPORT = "viewport.defaults.fill_viewport"
SETTING_VIEWPORT_INSTANCE_ID = "viewport.instances.{viewport_id}.id"
SETTING_VIEWPORT_INSTANCE_RESOLUTION = (
    "viewport.instances.{viewport_id}.resolution"
)
SETTING_VIEWPORT_INSTANCE_RESOLUTION_SCALE = (
    "viewport.instances.{viewport_id}.resolution_scale"
)
SETTING_VIEWPORT_INSTANCE_FILL_VIEWPORT = (
    "viewport.instances.{viewport_id}.fill_viewport"
)
SETTING_VIEWPORT_INSTANCE_RESOLUTION_USES_DPI = (
    "viewport.instances.{viewport_id}.resolution_uses_dpi"
)

DEFAULT_RESOLUTION_PRESETS = (
    3840,
    2160,
    2560,
    1440,
    2048,
    1080,
    1920,
    1080,
    1280,
    720,
    1024,
    1024,
    512,
    512,
)
DEFAULT_CUSTOM_RESOLUTION_LIST: tuple[dict[str, Any], ...] = ()
DEFAULT_MIN_RESOLUTION = (64, 64)
DEFAULT_RENDER_SCALE_LIST = (
    2.0,
    1.0,
    0.666666666666,
    0.5,
    0.333333333333,
    0.25,
)
DEFAULT_VIEWPORT_RESOLUTION = (0, 0)
DEFAULT_VIEWPORT_RESOLUTION_SCALE = 1.0
DEFAULT_VIEWPORT_FILL_VIEWPORT = False

PERSISTENCE_SHARED_DEFAULT = "shared_default"
PERSISTENCE_PERSISTENT = "persistent"
PERSISTENCE_STABLE_IDENTITY = "stable_identity"

SHAPE_FLAT_SIZE_LIST = "flat_size_list"
SHAPE_CUSTOM_RESOLUTION_LIST = "custom_resolution_list"
SHAPE_SIZE_PAIR = "size_pair"
SHAPE_RENDER_SCALE_LIST = "render_scale_list"
SHAPE_FLOAT = "float"
SHAPE_BOOL = "bool"
SHAPE_VIEWPORT_ID = "viewport_id"

VALUE_SOURCE_SCHEMA_DEFAULT = "schema default"
VALUE_SOURCE_SHARED_DEFAULT = "shared default"
VALUE_SOURCE_INHERITED_SHARED_DEFAULT = "inherited from shared default"
VALUE_SOURCE_INSTANCE_OVERRIDE = "instance override"
VALUE_SOURCE_DPI_UNAVAILABLE = "dpi unavailable"

_MISSING = object()


@dataclass(frozen=True)
class ResolutionSettingsChange:
    """Normalized Area-1 settings change notification payload."""

    key: str
    value: Any
    viewport_id: str


ResolutionSettingsChangeCallback = Callable[[ResolutionSettingsChange], None]


def _copy_resolution_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_copy_resolution_value(item) for item in value]
    if isinstance(value, list):
        return [_copy_resolution_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _copy_resolution_value(key): _copy_resolution_value(item)
            for key, item in value.items()
        }
    return value


@dataclass(frozen=True)
class ResolutionSettingSpec:
    """Schema fact for one SRD section 6 resolution setting."""

    key: str
    default: Any
    shape: str
    persistence: str
    inherited_from: Optional[str] = None

    def default_value(self) -> Any:
        """Return a caller-owned copy of the SRD default value."""

        return _copy_resolution_value(self.default)


RESOLUTION_SETTINGS_SCHEMA: tuple[ResolutionSettingSpec, ...] = (
    ResolutionSettingSpec(
        key=SETTING_RESOLUTION_PRESETS,
        default=DEFAULT_RESOLUTION_PRESETS,
        shape=SHAPE_FLAT_SIZE_LIST,
        persistence=PERSISTENCE_SHARED_DEFAULT,
    ),
    ResolutionSettingSpec(
        key=SETTING_CUSTOM_RESOLUTION_LIST,
        default=DEFAULT_CUSTOM_RESOLUTION_LIST,
        shape=SHAPE_CUSTOM_RESOLUTION_LIST,
        persistence=PERSISTENCE_PERSISTENT,
    ),
    ResolutionSettingSpec(
        key=SETTING_MIN_RESOLUTION,
        default=DEFAULT_MIN_RESOLUTION,
        shape=SHAPE_SIZE_PAIR,
        persistence=PERSISTENCE_SHARED_DEFAULT,
    ),
    ResolutionSettingSpec(
        key=SETTING_RENDER_SCALE_LIST,
        default=DEFAULT_RENDER_SCALE_LIST,
        shape=SHAPE_RENDER_SCALE_LIST,
        persistence=PERSISTENCE_SHARED_DEFAULT,
    ),
    ResolutionSettingSpec(
        key=SETTING_DEFAULT_RESOLUTION,
        default=DEFAULT_VIEWPORT_RESOLUTION,
        shape=SHAPE_SIZE_PAIR,
        persistence=PERSISTENCE_SHARED_DEFAULT,
    ),
    ResolutionSettingSpec(
        key=SETTING_DEFAULT_RESOLUTION_SCALE,
        default=DEFAULT_VIEWPORT_RESOLUTION_SCALE,
        shape=SHAPE_FLOAT,
        persistence=PERSISTENCE_SHARED_DEFAULT,
    ),
    ResolutionSettingSpec(
        key=SETTING_DEFAULT_FILL_VIEWPORT,
        default=DEFAULT_VIEWPORT_FILL_VIEWPORT,
        shape=SHAPE_BOOL,
        persistence=PERSISTENCE_SHARED_DEFAULT,
    ),
    ResolutionSettingSpec(
        key=SETTING_VIEWPORT_INSTANCE_RESOLUTION,
        default=DEFAULT_VIEWPORT_RESOLUTION,
        shape=SHAPE_SIZE_PAIR,
        persistence=PERSISTENCE_PERSISTENT,
        inherited_from=SETTING_DEFAULT_RESOLUTION,
    ),
    ResolutionSettingSpec(
        key=SETTING_VIEWPORT_INSTANCE_RESOLUTION_SCALE,
        default=DEFAULT_VIEWPORT_RESOLUTION_SCALE,
        shape=SHAPE_FLOAT,
        persistence=PERSISTENCE_PERSISTENT,
        inherited_from=SETTING_DEFAULT_RESOLUTION_SCALE,
    ),
    ResolutionSettingSpec(
        key=SETTING_VIEWPORT_INSTANCE_FILL_VIEWPORT,
        default=DEFAULT_VIEWPORT_FILL_VIEWPORT,
        shape=SHAPE_BOOL,
        persistence=PERSISTENCE_PERSISTENT,
        inherited_from=SETTING_DEFAULT_FILL_VIEWPORT,
    ),
    ResolutionSettingSpec(
        key=SETTING_VIEWPORT_INSTANCE_RESOLUTION_USES_DPI,
        default=True,
        shape=SHAPE_BOOL,
        persistence=PERSISTENCE_PERSISTENT,
    ),
    ResolutionSettingSpec(
        key=SETTING_VIEWPORT_INSTANCE_ID,
        default=DEFAULT_SETTINGS_VIEWPORT_ID,
        shape=SHAPE_VIEWPORT_ID,
        persistence=PERSISTENCE_STABLE_IDENTITY,
    ),
)


@dataclass(frozen=True)
class ViewportResolutionSettings:
    """Resolved SRD section 6 settings for one viewport identity."""

    viewport_id: str
    presets: list[int]
    custom_list: list[Any]
    min_resolution: list[int]
    render_scale_list: list[float]
    default_resolution: list[int]
    default_resolution_scale: float
    default_fill_viewport: bool
    resolution: list[int]
    resolution_scale: float
    fill_viewport: bool
    resolution_uses_dpi: bool
    dpi_scale: float
    default_resolution_source: str
    default_resolution_scale_source: str
    default_fill_viewport_source: str
    resolution_source: str
    resolution_scale_source: str
    fill_viewport_source: str
    resolution_uses_dpi_source: str


@dataclass(frozen=True)
class _ResolvedSetting:
    value: Any
    source: str


def iter_resolution_setting_specs() -> tuple[ResolutionSettingSpec, ...]:
    """Return the complete SRD section 6 setting schema."""

    return RESOLUTION_SETTINGS_SCHEMA


def resolution_settings_persistent_keys() -> tuple[str, ...]:
    """Return keys normal persistence can save for resolution controls."""

    return tuple(
        spec.key
        for spec in RESOLUTION_SETTINGS_SCHEMA
        if spec.persistence == PERSISTENCE_PERSISTENT
    )


def resolution_settings_shared_default_keys() -> tuple[str, ...]:
    """Return shared/app default keys that normal resolution UI does not write."""

    return tuple(
        spec.key
        for spec in RESOLUTION_SETTINGS_SCHEMA
        if spec.persistence == PERSISTENCE_SHARED_DEFAULT
    )


def viewport_instance_key(viewport_id: Optional[str], suffix: str) -> str:
    """Build a per-viewport settings key using the stable viewport identity."""

    return f"viewport.instances.{normalize_settings_viewport_id(viewport_id)}.{suffix}"


def viewport_resolution_key(viewport_id: Optional[str]) -> str:
    return viewport_instance_key(viewport_id, "resolution")


def viewport_resolution_scale_key(viewport_id: Optional[str]) -> str:
    return viewport_instance_key(viewport_id, "resolution_scale")


def viewport_fill_viewport_key(viewport_id: Optional[str]) -> str:
    return viewport_instance_key(viewport_id, "fill_viewport")


def viewport_resolution_uses_dpi_key(viewport_id: Optional[str]) -> str:
    return viewport_instance_key(viewport_id, "resolution_uses_dpi")


def viewport_id_key(viewport_id: Optional[str]) -> str:
    return viewport_instance_key(viewport_id, "id")


def normalize_settings_viewport_id(viewport_id: Optional[str]) -> str:
    """Use the SRD single-viewport ``main`` fallback for missing IDs."""

    if viewport_id is None:
        return DEFAULT_SETTINGS_VIEWPORT_ID
    normalized = str(viewport_id).strip()
    return normalized or DEFAULT_SETTINGS_VIEWPORT_ID


def _read_raw_setting(settings: Any, key: str) -> tuple[bool, Any]:
    value = _MISSING
    if settings is not None:
        getter = getattr(settings, "get", None)
        if callable(getter):
            try:
                value = getter(key, _MISSING)
            except TypeError:
                try:
                    value = getter(key)
                except (AttributeError, KeyError, TypeError):
                    value = _MISSING
            except (AttributeError, KeyError):
                value = _MISSING
    if value is _MISSING:
        return False, None
    return True, _copy_resolution_value(value)


def _read_setting(settings: Any, key: str, default: Any) -> Any:
    present, value = _read_raw_setting(settings, key)
    if not present:
        value = default
    return _copy_resolution_value(value)


def _coerce_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    return None


def _coerce_size_pair(value: Any) -> Optional[list[int]]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    width = _coerce_int(value[0])
    height = _coerce_int(value[1])
    if width is None or height is None:
        return None
    return [width, height]


def _coerce_int_list(value: Any) -> Optional[list[int]]:
    if not isinstance(value, (list, tuple)):
        return None
    result: list[int] = []
    for item in value:
        coerced = _coerce_int(item)
        if coerced is None:
            return None
        result.append(coerced)
    return result


def _coerce_float_list(value: Any) -> Optional[list[float]]:
    if not isinstance(value, (list, tuple)):
        return None
    result: list[float] = []
    for item in value:
        coerced = _coerce_float(item)
        if coerced is None:
            return None
        result.append(coerced)
    return result


def _coerce_list(value: Any) -> Optional[list[Any]]:
    if not isinstance(value, (list, tuple)):
        return None
    return list(_copy_resolution_value(value))


def _normalize_custom_resolution_dimension(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"custom resolution {field_name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"custom resolution {field_name} must be a positive integer")
    return value


def normalize_custom_resolution_entry(entry: Any) -> dict[str, Any]:
    """Normalize one SRD section 6.1 saved custom-resolution entry."""

    if not isinstance(entry, dict):
        raise ValueError("custom resolution entry must be a dict")
    name = entry.get("name")
    if not isinstance(name, str):
        raise ValueError("custom resolution entry name must be a string")
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("custom resolution entry name must be non-empty")
    width = _normalize_custom_resolution_dimension(entry.get("width"), "width")
    height = _normalize_custom_resolution_dimension(entry.get("height"), "height")
    return {"name": normalized_name, "width": width, "height": height}


def normalize_custom_resolution_list(custom_list: Any) -> list[dict[str, Any]]:
    """Normalize the shared saved-custom list while preserving entry order."""

    if not isinstance(custom_list, (list, tuple)):
        raise ValueError("custom_list must be a list")
    return [normalize_custom_resolution_entry(entry) for entry in custom_list]


def normalize_loaded_custom_resolution_list(
    custom_list: Any,
) -> list[dict[str, Any]]:
    """Tolerantly normalize a persisted custom-resolution list for reads."""

    if not isinstance(custom_list, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_dimensions: set[tuple[int, int]] = set()
    for entry in custom_list:
        try:
            normalized = normalize_custom_resolution_entry(entry)
        except ValueError:
            continue
        name = normalized["name"]
        dimensions = (normalized["width"], normalized["height"])
        if name in seen_names or dimensions in seen_dimensions:
            continue
        seen_names.add(name)
        seen_dimensions.add(dimensions)
        result.append(normalized)
    return result


def _read_int_list_setting(settings: Any, key: str, default: Any) -> list[int]:
    present, value = _read_raw_setting(settings, key)
    coerced = _coerce_int_list(value) if present else None
    if coerced is not None:
        return coerced
    return list(_copy_resolution_value(default))


def _read_float_list_setting(settings: Any, key: str, default: Any) -> list[float]:
    present, value = _read_raw_setting(settings, key)
    coerced = _coerce_float_list(value) if present else None
    if coerced is not None:
        return coerced
    return list(_copy_resolution_value(default))


def _read_list_setting(settings: Any, key: str, default: Any) -> list[Any]:
    present, value = _read_raw_setting(settings, key)
    coerced = _coerce_list(value) if present else None
    if coerced is not None:
        return coerced
    return list(_copy_resolution_value(default))


def _read_custom_resolution_list_setting(
    settings: Any,
    key: str,
    default: Any,
) -> list[dict[str, Any]]:
    present, value = _read_raw_setting(settings, key)
    if present:
        return normalize_loaded_custom_resolution_list(value)
    return normalize_loaded_custom_resolution_list(_copy_resolution_value(default))


def _read_shared_size_pair(
    settings: Any,
    key: str,
    default: Any,
) -> _ResolvedSetting:
    present, value = _read_raw_setting(settings, key)
    coerced = _coerce_size_pair(value) if present else None
    if coerced is not None:
        return _ResolvedSetting(coerced, VALUE_SOURCE_SHARED_DEFAULT)
    return _ResolvedSetting(
        list(_copy_resolution_value(default)),
        VALUE_SOURCE_SCHEMA_DEFAULT,
    )


def _read_shared_float(
    settings: Any,
    key: str,
    default: float,
) -> _ResolvedSetting:
    present, value = _read_raw_setting(settings, key)
    coerced = _coerce_float(value) if present else None
    if coerced is not None:
        return _ResolvedSetting(coerced, VALUE_SOURCE_SHARED_DEFAULT)
    return _ResolvedSetting(float(default), VALUE_SOURCE_SCHEMA_DEFAULT)


def _read_shared_bool(
    settings: Any,
    key: str,
    default: bool,
) -> _ResolvedSetting:
    present, value = _read_raw_setting(settings, key)
    coerced = _coerce_bool(value) if present else None
    if coerced is not None:
        return _ResolvedSetting(coerced, VALUE_SOURCE_SHARED_DEFAULT)
    return _ResolvedSetting(bool(default), VALUE_SOURCE_SCHEMA_DEFAULT)


def _read_instance_size_pair(
    settings: Any,
    key: str,
    inherited: _ResolvedSetting,
) -> _ResolvedSetting:
    present, value = _read_raw_setting(settings, key)
    coerced = _coerce_size_pair(value) if present else None
    if coerced is not None:
        return _ResolvedSetting(coerced, VALUE_SOURCE_INSTANCE_OVERRIDE)
    return _ResolvedSetting(
        _copy_resolution_value(inherited.value),
        VALUE_SOURCE_INHERITED_SHARED_DEFAULT,
    )


def _read_instance_float(
    settings: Any,
    key: str,
    inherited: _ResolvedSetting,
) -> _ResolvedSetting:
    present, value = _read_raw_setting(settings, key)
    coerced = _coerce_float(value) if present else None
    if coerced is not None:
        return _ResolvedSetting(coerced, VALUE_SOURCE_INSTANCE_OVERRIDE)
    return _ResolvedSetting(
        float(inherited.value),
        VALUE_SOURCE_INHERITED_SHARED_DEFAULT,
    )


def _read_instance_bool(
    settings: Any,
    key: str,
    inherited: _ResolvedSetting,
) -> _ResolvedSetting:
    present, value = _read_raw_setting(settings, key)
    coerced = _coerce_bool(value) if present else None
    if coerced is not None:
        return _ResolvedSetting(coerced, VALUE_SOURCE_INSTANCE_OVERRIDE)
    return _ResolvedSetting(
        bool(inherited.value),
        VALUE_SOURCE_INHERITED_SHARED_DEFAULT,
    )


def _read_instance_dpi_policy(
    settings: Any,
    key: str,
    *,
    dpi_scale_available: bool,
) -> _ResolvedSetting:
    if not dpi_scale_available:
        return _ResolvedSetting(False, VALUE_SOURCE_DPI_UNAVAILABLE)
    present, value = _read_raw_setting(settings, key)
    coerced = _coerce_bool(value) if present else None
    if coerced is not None:
        return _ResolvedSetting(coerced, VALUE_SOURCE_INSTANCE_OVERRIDE)
    return _ResolvedSetting(True, VALUE_SOURCE_SCHEMA_DEFAULT)


def _require_settings_writer(settings: Any) -> Any:
    setter = getattr(settings, "set", None)
    if not callable(setter):
        raise ValueError("settings must provide set(key, value)")
    return setter


def _require_settings_subscriber(settings: Any) -> Any:
    subscriber = getattr(settings, "subscribe", None)
    if not callable(subscriber):
        raise ValueError("settings must provide subscribe(key, callback)")
    return subscriber


def resolution_settings_observed_keys(
    viewport_id: Optional[str] = None,
) -> tuple[str, ...]:
    """Return all concrete Area-1 keys watched for one viewport identity."""

    normalized_viewport_id = normalize_settings_viewport_id(viewport_id)
    return (
        SETTING_RESOLUTION_PRESETS,
        SETTING_CUSTOM_RESOLUTION_LIST,
        SETTING_MIN_RESOLUTION,
        SETTING_RENDER_SCALE_LIST,
        SETTING_DEFAULT_RESOLUTION,
        SETTING_DEFAULT_RESOLUTION_SCALE,
        SETTING_DEFAULT_FILL_VIEWPORT,
        viewport_resolution_key(normalized_viewport_id),
        viewport_resolution_scale_key(normalized_viewport_id),
        viewport_fill_viewport_key(normalized_viewport_id),
        viewport_resolution_uses_dpi_key(normalized_viewport_id),
    )


def _normalize_resolution_setting_raw_value(
    settings: Any,
    key: str,
    raw_value: Any,
    *,
    viewport_id: Optional[str],
    dpi_scale_available: bool,
) -> Any:
    normalized_viewport_id = normalize_settings_viewport_id(viewport_id)
    if key == SETTING_RESOLUTION_PRESETS:
        normalized_presets = _coerce_int_list(raw_value)
        return (
            normalized_presets
            if normalized_presets is not None
            else list(DEFAULT_RESOLUTION_PRESETS)
        )
    if key == SETTING_CUSTOM_RESOLUTION_LIST:
        return normalize_loaded_custom_resolution_list(raw_value)
    if key == SETTING_MIN_RESOLUTION:
        normalized_min = _coerce_int_list(raw_value)
        return (
            normalized_min
            if normalized_min is not None
            else list(DEFAULT_MIN_RESOLUTION)
        )
    if key == SETTING_RENDER_SCALE_LIST:
        normalized_scales = _coerce_float_list(raw_value)
        return (
            normalized_scales
            if normalized_scales is not None
            else list(DEFAULT_RENDER_SCALE_LIST)
        )
    if key == SETTING_DEFAULT_RESOLUTION:
        normalized_default_resolution = _coerce_size_pair(raw_value)
        return (
            normalized_default_resolution
            if normalized_default_resolution is not None
            else list(DEFAULT_VIEWPORT_RESOLUTION)
        )
    if key == SETTING_DEFAULT_RESOLUTION_SCALE:
        normalized_default_scale = _coerce_float(raw_value)
        return (
            normalized_default_scale
            if normalized_default_scale is not None
            else DEFAULT_VIEWPORT_RESOLUTION_SCALE
        )
    if key == SETTING_DEFAULT_FILL_VIEWPORT:
        normalized_default_fill = _coerce_bool(raw_value)
        return (
            normalized_default_fill
            if normalized_default_fill is not None
            else DEFAULT_VIEWPORT_FILL_VIEWPORT
        )

    default_resolution = _read_shared_size_pair(
        settings,
        SETTING_DEFAULT_RESOLUTION,
        DEFAULT_VIEWPORT_RESOLUTION,
    )
    default_resolution_scale = _read_shared_float(
        settings,
        SETTING_DEFAULT_RESOLUTION_SCALE,
        DEFAULT_VIEWPORT_RESOLUTION_SCALE,
    )
    default_fill_viewport = _read_shared_bool(
        settings,
        SETTING_DEFAULT_FILL_VIEWPORT,
        DEFAULT_VIEWPORT_FILL_VIEWPORT,
    )
    if key == viewport_resolution_key(normalized_viewport_id):
        normalized_resolution = _coerce_size_pair(raw_value)
        return (
            normalized_resolution
            if normalized_resolution is not None
            else list(default_resolution.value)
        )
    if key == viewport_resolution_scale_key(normalized_viewport_id):
        normalized_scale = _coerce_float(raw_value)
        return (
            normalized_scale
            if normalized_scale is not None
            else float(default_resolution_scale.value)
        )
    if key == viewport_fill_viewport_key(normalized_viewport_id):
        normalized_fill = _coerce_bool(raw_value)
        return (
            normalized_fill
            if normalized_fill is not None
            else bool(default_fill_viewport.value)
        )
    if key == viewport_resolution_uses_dpi_key(normalized_viewport_id):
        if not dpi_scale_available:
            return False
        normalized_dpi = _coerce_bool(raw_value)
        return normalized_dpi if normalized_dpi is not None else True
    raise ValueError(f"unsupported resolution setting key: {key}")


def normalize_resolution_setting_change_value(
    settings: Any,
    key: str,
    *,
    viewport_id: Optional[str] = None,
    dpi_scale_available: bool = True,
) -> Any:
    """Return the normalized notification payload for one concrete key."""

    present, raw_value = _read_raw_setting(settings, key)
    if not present:
        raw_value = _MISSING
    if raw_value is _MISSING:
        if key == SETTING_CUSTOM_RESOLUTION_LIST:
            raw_value = DEFAULT_CUSTOM_RESOLUTION_LIST
        elif key == SETTING_RESOLUTION_PRESETS:
            raw_value = DEFAULT_RESOLUTION_PRESETS
        elif key == SETTING_MIN_RESOLUTION:
            raw_value = DEFAULT_MIN_RESOLUTION
        elif key == SETTING_RENDER_SCALE_LIST:
            raw_value = DEFAULT_RENDER_SCALE_LIST
        elif key == SETTING_DEFAULT_RESOLUTION:
            raw_value = DEFAULT_VIEWPORT_RESOLUTION
        elif key == SETTING_DEFAULT_RESOLUTION_SCALE:
            raw_value = DEFAULT_VIEWPORT_RESOLUTION_SCALE
        elif key == SETTING_DEFAULT_FILL_VIEWPORT:
            raw_value = DEFAULT_VIEWPORT_FILL_VIEWPORT
    return _copy_resolution_value(
        _normalize_resolution_setting_raw_value(
            settings,
            key,
            raw_value,
            viewport_id=viewport_id,
            dpi_scale_available=dpi_scale_available,
        )
    )


class ResolutionSettingsChangeSubscription:
    """Cancellable normalized settings watcher for one viewport scope."""

    def __init__(
        self,
        settings: Any,
        viewport_id: Optional[str],
        callback: ResolutionSettingsChangeCallback,
        *,
        dpi_scale_available: bool = True,
    ) -> None:
        if not callable(callback):
            raise TypeError("callback must be callable")
        self._settings = settings
        self._viewport_id = normalize_settings_viewport_id(viewport_id)
        self._callback = callback
        self._dpi_scale_available = bool(dpi_scale_available)
        self._handles: list[Any] = []
        self._last_values: dict[str, Any] = {}
        self._closed = False

        subscriber = _require_settings_subscriber(settings)
        for key in resolution_settings_observed_keys(self._viewport_id):
            self._last_values[key] = normalize_resolution_setting_change_value(
                settings,
                key,
                viewport_id=self._viewport_id,
                dpi_scale_available=self._dpi_scale_available,
            )
            self._handles.append(subscriber(key, self._on_raw_setting_changed))

    @property
    def active(self) -> bool:
        return not self._closed

    def cancel(self) -> None:
        if self._closed:
            return
        self._closed = True
        for handle in tuple(self._handles):
            cancel = getattr(handle, "cancel", None)
            if callable(cancel):
                cancel()
        self._handles.clear()
        self._last_values.clear()
        self._callback = lambda _change: None

    def unsubscribe(self) -> None:
        self.cancel()

    def _on_raw_setting_changed(self, key: str, _raw_value: Any) -> None:
        if self._closed:
            return
        normalized = normalize_resolution_setting_change_value(
            self._settings,
            key,
            viewport_id=self._viewport_id,
            dpi_scale_available=self._dpi_scale_available,
        )
        previous = self._last_values.get(key, _MISSING)
        if previous is not _MISSING and previous == normalized:
            return
        self._last_values[key] = _copy_resolution_value(normalized)
        self._callback(
            ResolutionSettingsChange(
                key=key,
                value=_copy_resolution_value(normalized),
                viewport_id=self._viewport_id,
            )
        )


def subscribe_resolution_settings_changes(
    settings: Any,
    viewport_id: Optional[str],
    callback: ResolutionSettingsChangeCallback,
    *,
    dpi_scale_available: bool = True,
) -> ResolutionSettingsChangeSubscription:
    """Subscribe to normalized Area-1 setting changes for one viewport."""

    return ResolutionSettingsChangeSubscription(
        settings,
        viewport_id,
        callback,
        dpi_scale_available=dpi_scale_available,
    )


def _write_viewport_instance_value(
    settings: Any,
    viewport_id: Optional[str],
    suffix: str,
    value: Any,
) -> str:
    setter = _require_settings_writer(settings)
    key = viewport_instance_key(viewport_id, suffix)
    setter(key, _copy_resolution_value(value))
    return key


def write_viewport_instance_resolution(
    settings: Any,
    viewport_id: Optional[str],
    resolution: Any,
) -> str:
    value = _coerce_size_pair(resolution)
    if value is None:
        raise ValueError("resolution must be a two-item integer size pair")
    return _write_viewport_instance_value(settings, viewport_id, "resolution", value)


def write_viewport_instance_resolution_scale(
    settings: Any,
    viewport_id: Optional[str],
    scale: Any,
) -> str:
    value = _coerce_float(scale)
    if value is None:
        raise ValueError("scale must be a float")
    return _write_viewport_instance_value(
        settings,
        viewport_id,
        "resolution_scale",
        value,
    )


def write_viewport_instance_fill_viewport(
    settings: Any,
    viewport_id: Optional[str],
    fill_viewport: Any,
) -> str:
    value = _coerce_bool(fill_viewport)
    if value is None:
        raise ValueError("fill_viewport must be a bool")
    return _write_viewport_instance_value(
        settings,
        viewport_id,
        "fill_viewport",
        value,
    )


def write_viewport_instance_resolution_uses_dpi(
    settings: Any,
    viewport_id: Optional[str],
    uses_dpi: Any,
) -> str:
    value = _coerce_bool(uses_dpi)
    if value is None:
        raise ValueError("uses_dpi must be a bool")
    return _write_viewport_instance_value(
        settings,
        viewport_id,
        "resolution_uses_dpi",
        value,
    )


def write_shared_custom_resolution_list(settings: Any, custom_list: Any) -> str:
    """Write the shared custom-resolution list without per-viewport scoping."""

    value = normalize_custom_resolution_list(custom_list)
    setter = _require_settings_writer(settings)
    setter(SETTING_CUSTOM_RESOLUTION_LIST, value)
    return SETTING_CUSTOM_RESOLUTION_LIST


def add_shared_custom_resolution_entry(settings: Any, entry: Any) -> str:
    """Append one normalized SRD section 6.1 custom entry to the shared list."""

    current = _read_list_setting(
        settings,
        SETTING_CUSTOM_RESOLUTION_LIST,
        DEFAULT_CUSTOM_RESOLUTION_LIST,
    )
    normalized = normalize_custom_resolution_list(current)
    normalized.append(normalize_custom_resolution_entry(entry))
    return write_shared_custom_resolution_list(settings, normalized)


def resolve_viewport_resolution_settings(
    settings: Any,
    viewport_id: Optional[str] = None,
    *,
    dpi_scale_available: bool = True,
    dpi_scale: float = 1.0,
) -> ViewportResolutionSettings:
    """Resolve SRD section 6 values from ``settings`` without writing defaults."""

    resolved_viewport_id = normalize_settings_viewport_id(viewport_id)
    presets = _read_int_list_setting(
        settings,
        SETTING_RESOLUTION_PRESETS,
        DEFAULT_RESOLUTION_PRESETS,
    )
    custom_list = _read_custom_resolution_list_setting(
        settings,
        SETTING_CUSTOM_RESOLUTION_LIST,
        DEFAULT_CUSTOM_RESOLUTION_LIST,
    )
    min_resolution = _read_int_list_setting(
        settings,
        SETTING_MIN_RESOLUTION,
        DEFAULT_MIN_RESOLUTION,
    )
    render_scale_list = _read_float_list_setting(
        settings,
        SETTING_RENDER_SCALE_LIST,
        DEFAULT_RENDER_SCALE_LIST,
    )
    default_resolution = _read_shared_size_pair(
        settings,
        SETTING_DEFAULT_RESOLUTION,
        DEFAULT_VIEWPORT_RESOLUTION,
    )
    default_resolution_scale = _read_shared_float(
        settings,
        SETTING_DEFAULT_RESOLUTION_SCALE,
        DEFAULT_VIEWPORT_RESOLUTION_SCALE,
    )
    default_fill_viewport = _read_shared_bool(
        settings,
        SETTING_DEFAULT_FILL_VIEWPORT,
        DEFAULT_VIEWPORT_FILL_VIEWPORT,
    )
    resolution = _read_instance_size_pair(
        settings,
        viewport_resolution_key(resolved_viewport_id),
        default_resolution,
    )
    resolution_scale = _read_instance_float(
        settings,
        viewport_resolution_scale_key(resolved_viewport_id),
        default_resolution_scale,
    )
    fill_viewport = _read_instance_bool(
        settings,
        viewport_fill_viewport_key(resolved_viewport_id),
        default_fill_viewport,
    )
    resolution_uses_dpi = _read_instance_dpi_policy(
        settings,
        viewport_resolution_uses_dpi_key(resolved_viewport_id),
        dpi_scale_available=dpi_scale_available,
    )

    if dpi_scale_available:
        try:
            resolved_dpi_scale = float(dpi_scale)
        except (TypeError, ValueError):
            resolved_dpi_scale = 1.0
        if resolved_dpi_scale <= 0.0:
            resolved_dpi_scale = 1.0
    else:
        resolved_dpi_scale = 1.0

    return ViewportResolutionSettings(
        viewport_id=resolved_viewport_id,
        presets=presets,
        custom_list=custom_list,
        min_resolution=min_resolution,
        render_scale_list=render_scale_list,
        default_resolution=list(default_resolution.value),
        default_resolution_scale=float(default_resolution_scale.value),
        default_fill_viewport=bool(default_fill_viewport.value),
        resolution=list(resolution.value),
        resolution_scale=float(resolution_scale.value),
        fill_viewport=bool(fill_viewport.value),
        resolution_uses_dpi=bool(resolution_uses_dpi.value),
        dpi_scale=resolved_dpi_scale,
        default_resolution_source=default_resolution.source,
        default_resolution_scale_source=default_resolution_scale.source,
        default_fill_viewport_source=default_fill_viewport.source,
        resolution_source=resolution.source,
        resolution_scale_source=resolution_scale.source,
        fill_viewport_source=fill_viewport.source,
        resolution_uses_dpi_source=resolution_uses_dpi.source,
    )


def _format_list(values: Iterable[Any]) -> str:
    return "[" + ", ".join(repr(value) for value in values) + "]"


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _format_custom_list_summary(values: Iterable[Any]) -> str:
    entries: list[str] = []
    for value in values:
        if isinstance(value, dict):
            name = value.get("name")
            width = value.get("width")
            height = value.get("height")
            if name is not None and width is not None and height is not None:
                entries.append(f"{name} {width}x{height}")
                continue
        entries.append(repr(value))
    return ", ".join(entries) if entries else "none"


def format_resolution_settings_qa_lines(
    resolved: ViewportResolutionSettings,
    *,
    profile_label: str,
) -> tuple[str, ...]:
    """Format real resolver output for the env-gated Area 1 QA scaffold."""

    mode = (
        "Viewport"
        if resolved.resolution == [0, 0]
        else f"{resolved.resolution[0]}x{resolved.resolution[1]}"
    )
    scale_percent = int(round(resolved.resolution_scale * 100.0))
    min_text = (
        f"{resolved.min_resolution[0]}x{resolved.min_resolution[1]}"
        if len(resolved.min_resolution) >= 2
        else _format_list(resolved.min_resolution)
    )
    area_2_note = (
        "Area 2 later maps [1280,720] to HD720P row"
        if resolved.resolution == [1280, 720]
        else "Area 2 later maps fixed sizes to catalog rows"
    )
    return (
        "A1 Settings Schema QA Scaffold",
        f"Profile: {profile_label}",
        f"Viewport ID: {resolved.viewport_id}",
        f"Resolution: {_format_list(resolved.resolution)} ({mode})",
        f"Resolution Source: {resolved.resolution_source}",
        f"Scale: {resolved.resolution_scale!r} ({scale_percent}%)",
        f"Scale Source: {resolved.resolution_scale_source}",
        f"Fill Viewport: {_format_bool(resolved.fill_viewport)}",
        f"Fill Source: {resolved.fill_viewport_source}",
        f"Custom List: {_format_list(resolved.custom_list)}",
        f"Shared Custom Items: {_format_custom_list_summary(resolved.custom_list)}",
        f"Min: {min_text}",
        f"Presets: {_format_list(resolved.presets)}",
        f"Render Scale List: {_format_list(resolved.render_scale_list)}",
        "DPI Uses Scale: "
        f"{_format_bool(resolved.resolution_uses_dpi)} "
        f"(scale {resolved.dpi_scale!r})",
        f"DPI Source: {resolved.resolution_uses_dpi_source}",
        area_2_note,
        "Area 3 later computes effective render size",
        "QA scaffold only; product menu is Area 4; save dialog is Area 5",
    )


__all__ = [
    "DEFAULT_CUSTOM_RESOLUTION_LIST",
    "DEFAULT_MIN_RESOLUTION",
    "DEFAULT_RENDER_SCALE_LIST",
    "DEFAULT_RESOLUTION_PRESETS",
    "DEFAULT_SETTINGS_VIEWPORT_ID",
    "DEFAULT_VIEWPORT_FILL_VIEWPORT",
    "DEFAULT_VIEWPORT_RESOLUTION",
    "DEFAULT_VIEWPORT_RESOLUTION_SCALE",
    "PERSISTENCE_PERSISTENT",
    "PERSISTENCE_SHARED_DEFAULT",
    "PERSISTENCE_STABLE_IDENTITY",
    "RESOLUTION_SETTINGS_SCHEMA",
    "SHAPE_BOOL",
    "SHAPE_CUSTOM_RESOLUTION_LIST",
    "SHAPE_FLAT_SIZE_LIST",
    "SHAPE_FLOAT",
    "SHAPE_RENDER_SCALE_LIST",
    "SHAPE_SIZE_PAIR",
    "SHAPE_VIEWPORT_ID",
    "SETTING_CUSTOM_RESOLUTION_LIST",
    "SETTING_DEFAULT_FILL_VIEWPORT",
    "SETTING_DEFAULT_RESOLUTION",
    "SETTING_DEFAULT_RESOLUTION_SCALE",
    "SETTING_MIN_RESOLUTION",
    "SETTING_RENDER_SCALE_LIST",
    "SETTING_RESOLUTION_PRESETS",
    "SETTING_VIEWPORT_INSTANCE_FILL_VIEWPORT",
    "SETTING_VIEWPORT_INSTANCE_ID",
    "SETTING_VIEWPORT_INSTANCE_RESOLUTION",
    "SETTING_VIEWPORT_INSTANCE_RESOLUTION_SCALE",
    "SETTING_VIEWPORT_INSTANCE_RESOLUTION_USES_DPI",
    "VALUE_SOURCE_DPI_UNAVAILABLE",
    "VALUE_SOURCE_INHERITED_SHARED_DEFAULT",
    "VALUE_SOURCE_INSTANCE_OVERRIDE",
    "VALUE_SOURCE_SCHEMA_DEFAULT",
    "VALUE_SOURCE_SHARED_DEFAULT",
    "ResolutionSettingsChange",
    "ResolutionSettingsChangeCallback",
    "ResolutionSettingsChangeSubscription",
    "ResolutionSettingSpec",
    "ViewportResolutionSettings",
    "add_shared_custom_resolution_entry",
    "format_resolution_settings_qa_lines",
    "iter_resolution_setting_specs",
    "normalize_custom_resolution_entry",
    "normalize_custom_resolution_list",
    "normalize_loaded_custom_resolution_list",
    "normalize_resolution_setting_change_value",
    "normalize_settings_viewport_id",
    "resolution_settings_observed_keys",
    "resolution_settings_persistent_keys",
    "resolution_settings_shared_default_keys",
    "resolve_viewport_resolution_settings",
    "subscribe_resolution_settings_changes",
    "viewport_fill_viewport_key",
    "viewport_id_key",
    "viewport_instance_key",
    "viewport_resolution_key",
    "viewport_resolution_scale_key",
    "viewport_resolution_uses_dpi_key",
    "write_shared_custom_resolution_list",
    "write_viewport_instance_fill_viewport",
    "write_viewport_instance_resolution",
    "write_viewport_instance_resolution_scale",
    "write_viewport_instance_resolution_uses_dpi",
]
