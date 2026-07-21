# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Backend-neutral point-cloud contracts.

These contracts describe point-cloud outputs without exposing USD prims,
renderer handles, array library types, or UI objects. Concrete adapters own
backend extraction and conversion; optional UI packages consume these plain
Python snapshots and descriptors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional, Tuple


class _StableStringEnum(str, Enum):
    """String enum whose values are stable public contract tokens."""

    def __str__(self) -> str:
        return self.value


class PointCloudChannelSemantic(_StableStringEnum):
    """Normalized meaning of a point-cloud channel."""

    COORDINATES = "coordinates"
    COUNT = "count"
    INTENSITY = "intensity"
    RANGE = "range"
    VELOCITY = "velocity"
    RADIAL_VELOCITY = "radial_velocity"
    RCS = "rcs"
    MATERIAL_ID = "material_id"
    OBJECT_ID = "object_id"
    FLAGS = "flags"
    TIME_OFFSET = "time_offset"
    VALIDITY = "validity"
    UNKNOWN = "unknown"


class PointCloudColorMode(_StableStringEnum):
    """Color modes supported by point-cloud consumers."""

    FIXED = "fixed"
    INTENSITY = "intensity"
    RANGE = "range"
    VELOCITY = "velocity"
    RCS = "rcs"
    MATERIAL_ID = "material_id"
    OBJECT_ID = "object_id"


class PointCloudCoordinateSpace(_StableStringEnum):
    """Coordinate space of a point-cloud frame or output."""

    WORLD = "world"
    SENSOR = "sensor"
    LOCAL = "local"
    VIEW = "view"
    UNKNOWN = "unknown"


class PointCloudWarningSeverity(_StableStringEnum):
    """Severity for point-cloud descriptor and frame warnings."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


def _tuple_or_empty(value: Iterable[str] | str | None) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _warnings_tuple(
    value: Iterable["PointCloudWarning"] | "PointCloudWarning" | None,
) -> Tuple["PointCloudWarning", ...]:
    if value is None:
        return ()
    if isinstance(value, PointCloudWarning):
        return (value,)
    return tuple(value)


def _channels_tuple(
    value: Iterable["PointCloudChannelDescriptor"]
    | "PointCloudChannelDescriptor"
    | None,
) -> Tuple["PointCloudChannelDescriptor", ...]:
    if value is None:
        return ()
    if isinstance(value, PointCloudChannelDescriptor):
        return (value,)
    return tuple(value)


def _color_modes_tuple(
    value: Iterable[PointCloudColorMode | str] | PointCloudColorMode | str | None,
) -> Tuple[PointCloudColorMode, ...]:
    if value is None:
        return ()
    if isinstance(value, (PointCloudColorMode, str)):
        items = (value,)
    else:
        items = tuple(value)
    return tuple(
        item if isinstance(item, PointCloudColorMode) else PointCloudColorMode(str(item))
        for item in items
    )


def _coerce_range(value: Iterable[float] | None) -> Tuple[float, float] | None:
    if value is None:
        return None
    items = tuple(value)
    if len(items) != 2:
        raise ValueError("value_range must contain min and max")
    return (float(items[0]), float(items[1]))


def _coerce_transform(value: Iterable[float] | None) -> Tuple[float, ...] | None:
    if value is None:
        return None
    items = tuple(float(item) for item in value)
    if len(items) != 16:
        raise ValueError("transform_to_world must contain 16 values")
    return items


def _mapping_proxy(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    return MappingProxyType(dict(value))


@dataclass(frozen=True)
class PointCloudWarning:
    """Warning or disabled-state reason attached to point-cloud data."""

    code: str
    message: str
    severity: PointCloudWarningSeverity = PointCloudWarningSeverity.WARNING

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "message", str(self.message))
        if not isinstance(self.severity, PointCloudWarningSeverity):
            object.__setattr__(
                self,
                "severity",
                PointCloudWarningSeverity(str(self.severity)),
            )


@dataclass(frozen=True)
class PointCloudChannelDescriptor:
    """Backend-neutral metadata for one point-cloud channel."""

    name: str
    semantic: PointCloudChannelSemantic = PointCloudChannelSemantic.UNKNOWN
    dtype: str = ""
    component_count: int = 1
    units: str = ""
    value_range: Tuple[float, float] | None = None
    validity_semantics: str = ""
    color_modes: Tuple[PointCloudColorMode, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", str(self.name))
        if not self.name:
            raise ValueError("channel name is required")
        if not isinstance(self.semantic, PointCloudChannelSemantic):
            object.__setattr__(
                self,
                "semantic",
                PointCloudChannelSemantic(str(self.semantic)),
            )
        object.__setattr__(self, "dtype", str(self.dtype or ""))
        component_count = int(self.component_count)
        if component_count <= 0:
            raise ValueError("component_count must be positive")
        object.__setattr__(self, "component_count", component_count)
        object.__setattr__(self, "units", str(self.units or ""))
        object.__setattr__(self, "value_range", _coerce_range(self.value_range))
        object.__setattr__(self, "validity_semantics", str(self.validity_semantics or ""))
        object.__setattr__(self, "color_modes", _color_modes_tuple(self.color_modes))

    @property
    def supports_coloring(self) -> bool:
        """Whether this channel can directly drive a point color mode."""

        return bool(self.color_modes)


@dataclass(frozen=True)
class PointCloudOutputDescriptor:
    """Descriptor for one point-cloud-capable render output."""

    render_product_path: str = ""
    render_var_name: str = "PointCloud"
    source_sensor_path: Optional[str] = None
    source_sensor_name: str = ""
    source_sensor_type: str = ""
    coordinate_space: PointCloudCoordinateSpace = PointCloudCoordinateSpace.UNKNOWN
    transform_to_world: Tuple[float, ...] | None = None
    channels: Tuple[PointCloudChannelDescriptor, ...] = field(default_factory=tuple)
    capabilities: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[PointCloudWarning, ...] = field(default_factory=tuple)
    enabled: bool = True
    disabled_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "render_product_path", str(self.render_product_path or ""))
        object.__setattr__(self, "render_var_name", str(self.render_var_name or ""))
        if self.source_sensor_path is not None:
            object.__setattr__(self, "source_sensor_path", str(self.source_sensor_path))
        object.__setattr__(self, "source_sensor_name", str(self.source_sensor_name or ""))
        object.__setattr__(self, "source_sensor_type", str(self.source_sensor_type or ""))
        if not isinstance(self.coordinate_space, PointCloudCoordinateSpace):
            object.__setattr__(
                self,
                "coordinate_space",
                PointCloudCoordinateSpace(str(self.coordinate_space)),
            )
        object.__setattr__(
            self,
            "transform_to_world",
            _coerce_transform(self.transform_to_world),
        )
        object.__setattr__(self, "channels", _channels_tuple(self.channels))
        object.__setattr__(self, "capabilities", _tuple_or_empty(self.capabilities))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "disabled_reason", str(self.disabled_reason or ""))

    @property
    def channel_names(self) -> Tuple[str, ...]:
        """Stable channel-name tuple in descriptor order."""

        return tuple(channel.name for channel in self.channels)

    @property
    def is_available(self) -> bool:
        """Whether consumers should request frames for this output."""

        return bool(self.enabled and not self.disabled_reason)

    def channel(self, name: str) -> PointCloudChannelDescriptor | None:
        """Return one channel descriptor by name, if present."""

        for descriptor in self.channels:
            if descriptor.name == name:
                return descriptor
        return None

    def supports_color_mode(self, mode: PointCloudColorMode | str) -> bool:
        """Return true when any channel reports support for ``mode``."""

        color_mode = (
            mode
            if isinstance(mode, PointCloudColorMode)
            else PointCloudColorMode(str(mode))
        )
        if color_mode is PointCloudColorMode.FIXED:
            return True
        return any(color_mode in channel.color_modes for channel in self.channels)


@dataclass(frozen=True)
class PointCloudOutputCatalog:
    """Immutable snapshot of point-cloud outputs available to a renderer."""

    outputs: Tuple[PointCloudOutputDescriptor, ...] = field(default_factory=tuple)
    active_render_product_path: Optional[str] = None
    revision: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", tuple(self.outputs))
        if self.active_render_product_path is not None:
            object.__setattr__(
                self,
                "active_render_product_path",
                str(self.active_render_product_path),
            )
        if self.revision is not None:
            object.__setattr__(self, "revision", str(self.revision))

    @property
    def is_empty(self) -> bool:
        """True when no point-cloud outputs are available."""

        return not self.outputs


@dataclass(frozen=True)
class PointCloudRequest:
    """Per-viewport request for point-cloud extraction."""

    viewport_id: str = ""
    render_product_path: str = ""
    render_var_name: str = "PointCloud"
    requested_channels: Tuple[str, ...] = field(default_factory=tuple)
    max_points: Optional[int] = None
    decimation_stride: int = 1
    include_validity: bool = True
    color_mode: PointCloudColorMode = PointCloudColorMode.FIXED
    desired_coordinate_space: PointCloudCoordinateSpace = PointCloudCoordinateSpace.WORLD

    def __post_init__(self) -> None:
        object.__setattr__(self, "viewport_id", str(self.viewport_id or ""))
        object.__setattr__(
            self,
            "render_product_path",
            str(self.render_product_path or ""),
        )
        object.__setattr__(self, "render_var_name", str(self.render_var_name or ""))
        object.__setattr__(
            self,
            "requested_channels",
            _tuple_or_empty(self.requested_channels),
        )
        if self.max_points is not None:
            max_points = int(self.max_points)
            if max_points <= 0:
                raise ValueError("max_points must be positive")
            object.__setattr__(self, "max_points", max_points)
        decimation_stride = int(self.decimation_stride)
        if decimation_stride <= 0:
            raise ValueError("decimation_stride must be positive")
        object.__setattr__(self, "decimation_stride", decimation_stride)
        object.__setattr__(self, "include_validity", bool(self.include_validity))
        if not isinstance(self.color_mode, PointCloudColorMode):
            object.__setattr__(
                self,
                "color_mode",
                PointCloudColorMode(str(self.color_mode)),
            )
        if not isinstance(self.desired_coordinate_space, PointCloudCoordinateSpace):
            object.__setattr__(
                self,
                "desired_coordinate_space",
                PointCloudCoordinateSpace(str(self.desired_coordinate_space)),
            )


@dataclass(frozen=True)
class PointCloudFrame:
    """Immutable point-cloud snapshot safe for UI consumption."""

    render_product_path: str = ""
    render_var_name: str = "PointCloud"
    point_count: int = 0
    valid_point_count: Optional[int] = None
    coordinates: Any = None
    channels: Mapping[str, Any] = field(default_factory=dict)
    validity_mask: Any = None
    coordinate_space: PointCloudCoordinateSpace = PointCloudCoordinateSpace.UNKNOWN
    transform_to_world: Tuple[float, ...] | None = None
    frame_index: Optional[int] = None
    timestamp: Optional[float] = None
    stale: bool = False
    source_sensor_path: Optional[str] = None
    source_sensor_type: str = ""
    channel_descriptors: Tuple[PointCloudChannelDescriptor, ...] = field(default_factory=tuple)
    warnings: Tuple[PointCloudWarning, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "render_product_path", str(self.render_product_path or ""))
        object.__setattr__(self, "render_var_name", str(self.render_var_name or ""))
        point_count = int(self.point_count)
        if point_count < 0:
            raise ValueError("point_count must not be negative")
        object.__setattr__(self, "point_count", point_count)
        valid_point_count = (
            point_count
            if self.valid_point_count is None
            else int(self.valid_point_count)
        )
        if valid_point_count < 0:
            raise ValueError("valid_point_count must not be negative")
        if valid_point_count > point_count:
            raise ValueError("valid_point_count must not exceed point_count")
        object.__setattr__(self, "valid_point_count", valid_point_count)
        object.__setattr__(self, "channels", _mapping_proxy(self.channels))
        if not isinstance(self.coordinate_space, PointCloudCoordinateSpace):
            object.__setattr__(
                self,
                "coordinate_space",
                PointCloudCoordinateSpace(str(self.coordinate_space)),
            )
        object.__setattr__(
            self,
            "transform_to_world",
            _coerce_transform(self.transform_to_world),
        )
        if self.frame_index is not None:
            object.__setattr__(self, "frame_index", int(self.frame_index))
        if self.timestamp is not None:
            object.__setattr__(self, "timestamp", float(self.timestamp))
        object.__setattr__(self, "stale", bool(self.stale))
        if self.source_sensor_path is not None:
            object.__setattr__(self, "source_sensor_path", str(self.source_sensor_path))
        object.__setattr__(self, "source_sensor_type", str(self.source_sensor_type or ""))
        object.__setattr__(
            self,
            "channel_descriptors",
            _channels_tuple(self.channel_descriptors),
        )
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))

    @property
    def is_empty(self) -> bool:
        """True when the frame has no valid points."""

        return self.valid_point_count == 0

    def channel_data(self, name: str) -> Any:
        """Return a channel payload by name, if present."""

        return self.channels.get(name)


@dataclass(frozen=True)
class PointCloudRequestResult:
    """Result of requesting point-cloud extraction for a viewport."""

    accepted: bool = False
    active_request: Optional[PointCloudRequest] = None
    message: str = ""
    warning_code: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted", bool(self.accepted))
        object.__setattr__(self, "message", str(self.message or ""))
        if self.warning_code is not None:
            object.__setattr__(self, "warning_code", str(self.warning_code))

    @classmethod
    def accepted_result(
        cls,
        *,
        active_request: PointCloudRequest | None = None,
        message: str = "",
    ) -> "PointCloudRequestResult":
        """Build a successful request result."""

        return cls(
            accepted=True,
            active_request=active_request,
            message=message,
        )

    @classmethod
    def rejected_result(
        cls,
        message: str = "",
        *,
        warning_code: str = "",
        active_request: PointCloudRequest | None = None,
    ) -> "PointCloudRequestResult":
        """Build a rejected request result."""

        return cls(
            accepted=False,
            active_request=active_request,
            message=message,
            warning_code=warning_code or None,
        )


__all__ = [
    "PointCloudChannelDescriptor",
    "PointCloudChannelSemantic",
    "PointCloudColorMode",
    "PointCloudCoordinateSpace",
    "PointCloudFrame",
    "PointCloudOutputCatalog",
    "PointCloudOutputDescriptor",
    "PointCloudRequest",
    "PointCloudRequestResult",
    "PointCloudWarning",
    "PointCloudWarningSeverity",
]
