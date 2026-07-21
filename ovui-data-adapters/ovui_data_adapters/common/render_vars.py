# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Backend-neutral RenderVar output visualization contracts.

These contracts describe non-LDR RenderVar outputs, visualization presets,
display snapshots, and raw-value probe results without exposing USD prims,
renderer handles, array-library types, or UI objects. Concrete adapters own
backend extraction and conversion; optional UI packages consume these plain
Python descriptors and snapshots.
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


class RenderVarOutputKind(_StableStringEnum):
    """Normalized family for a RenderVar output."""

    LDR_COLOR = "ldr_color"
    HDR_COLOR = "hdr_color"
    SCALAR_DEPTH = "scalar_depth"
    VECTOR_NORMAL = "vector_normal"
    CATEGORICAL_MASK = "categorical_mask"
    METADATA_MAP = "metadata_map"
    UNKNOWN = "unknown"


class RenderVarPresetKind(_StableStringEnum):
    """Visualization preset family for a RenderVar output."""

    RAW = "raw"
    LDR_COLOR = "ldr_color"
    HDR_TONEMAP = "hdr_tonemap"
    SCALAR_GRAYSCALE = "scalar_grayscale"
    VECTOR_SIGNED = "vector_signed"
    CATEGORICAL_PALETTE = "categorical_palette"


class RenderVarToneMap(_StableStringEnum):
    """Stable tonemap identifiers for HDR visualization presets."""

    LINEAR = "linear"
    REINHARD = "reinhard"
    ACES = "aces"


class RenderVarWarningSeverity(_StableStringEnum):
    """Severity for RenderVar descriptor, frame, and probe warnings."""

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
    value: Iterable["RenderVarWarning"] | "RenderVarWarning" | None,
) -> Tuple["RenderVarWarning", ...]:
    if value is None:
        return ()
    if isinstance(value, RenderVarWarning):
        return (value,)
    return tuple(value)


def _presets_tuple(
    value: Iterable["RenderVarVisualizationPreset"]
    | "RenderVarVisualizationPreset"
    | None,
) -> Tuple["RenderVarVisualizationPreset", ...]:
    if value is None:
        return ()
    if isinstance(value, RenderVarVisualizationPreset):
        return (value,)
    return tuple(value)


def _int_tuple(value: Iterable[int] | None) -> Tuple[int, ...]:
    if value is None:
        return ()
    items = tuple(int(item) for item in value)
    if any(item < 0 for item in items):
        raise ValueError("shape dimensions must be non-negative")
    return items


def _coerce_range(value: Iterable[float] | None) -> Tuple[float, float] | None:
    if value is None:
        return None
    items = tuple(value)
    if len(items) != 2:
        raise ValueError("value_range must contain min and max")
    lo, hi = float(items[0]), float(items[1])
    if hi < lo:
        raise ValueError("value_range max must be greater than or equal to min")
    return (lo, hi)


def _mapping_proxy(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    return MappingProxyType(dict(value))


def _rgba_tuple(value: Iterable[float]) -> Tuple[float, float, float, float]:
    items = tuple(float(item) for item in value)
    if len(items) != 4:
        raise ValueError("RGBA colors must contain four components")
    return items  # type: ignore[return-value]


def _palette_proxy(
    value: Mapping[int, Iterable[float]] | None,
) -> Mapping[int, Tuple[float, float, float, float]]:
    if value is None:
        return MappingProxyType({})
    return MappingProxyType({int(key): _rgba_tuple(color) for key, color in value.items()})


def _label_proxy(value: Mapping[int, str] | None) -> Mapping[int, str]:
    if value is None:
        return MappingProxyType({})
    return MappingProxyType({int(key): str(label) for key, label in value.items()})


@dataclass(frozen=True)
class RenderVarWarning:
    """Warning or disabled-state reason attached to RenderVar data."""

    code: str
    message: str
    severity: RenderVarWarningSeverity = RenderVarWarningSeverity.WARNING

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "message", str(self.message))
        if not isinstance(self.severity, RenderVarWarningSeverity):
            object.__setattr__(
                self,
                "severity",
                RenderVarWarningSeverity(str(self.severity)),
            )


@dataclass(frozen=True)
class RenderVarScalarRangeSettings:
    """Scalar/depth range mapping for grayscale visualization."""

    min_value: Optional[float] = None
    max_value: Optional[float] = None
    auto_range: bool = True
    invert: bool = False
    clamp: bool = True
    ramp: str = "grayscale"

    def __post_init__(self) -> None:
        min_value = None if self.min_value is None else float(self.min_value)
        max_value = None if self.max_value is None else float(self.max_value)
        if min_value is not None and max_value is not None and max_value < min_value:
            raise ValueError("max_value must be greater than or equal to min_value")
        object.__setattr__(self, "min_value", min_value)
        object.__setattr__(self, "max_value", max_value)
        object.__setattr__(self, "auto_range", bool(self.auto_range))
        object.__setattr__(self, "invert", bool(self.invert))
        object.__setattr__(self, "clamp", bool(self.clamp))
        object.__setattr__(self, "ramp", str(self.ramp or "grayscale"))


@dataclass(frozen=True)
class RenderVarHdrSettings:
    """HDR exposure and tonemap visualization settings."""

    exposure: float = 0.0
    tonemap: RenderVarToneMap = RenderVarToneMap.REINHARD
    gamma: float = 2.2

    def __post_init__(self) -> None:
        object.__setattr__(self, "exposure", float(self.exposure))
        if not isinstance(self.tonemap, RenderVarToneMap):
            object.__setattr__(self, "tonemap", RenderVarToneMap(str(self.tonemap)))
        gamma = float(self.gamma)
        if gamma <= 0.0:
            raise ValueError("gamma must be positive")
        object.__setattr__(self, "gamma", gamma)


@dataclass(frozen=True)
class RenderVarVectorSettings:
    """Vector/normal channel and signed-remap visualization settings."""

    channel_indices: Tuple[int, ...] = (0, 1, 2)
    signed_remap: bool = True
    normalize: bool = False
    component_labels: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        indices = tuple(int(item) for item in self.channel_indices)
        if not indices:
            raise ValueError("channel_indices must not be empty")
        if any(item < 0 for item in indices):
            raise ValueError("channel_indices must be non-negative")
        object.__setattr__(self, "channel_indices", indices)
        object.__setattr__(self, "signed_remap", bool(self.signed_remap))
        object.__setattr__(self, "normalize", bool(self.normalize))
        object.__setattr__(
            self,
            "component_labels",
            _tuple_or_empty(self.component_labels),
        )


@dataclass(frozen=True)
class RenderVarCategoricalSettings:
    """Categorical palette and legend metadata for ID/mask outputs."""

    palette: Mapping[int, Tuple[float, float, float, float]] = field(default_factory=dict)
    labels: Mapping[int, str] = field(default_factory=dict)
    unknown_color: Tuple[float, float, float, float] = (1.0, 0.0, 1.0, 1.0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "palette", _palette_proxy(self.palette))
        object.__setattr__(self, "labels", _label_proxy(self.labels))
        object.__setattr__(self, "unknown_color", _rgba_tuple(self.unknown_color))


@dataclass(frozen=True)
class RenderVarVisualizationPreset:
    """Typed visualization settings bundle for one output preset."""

    kind: RenderVarPresetKind = RenderVarPresetKind.RAW
    label: str = ""
    scalar_range: RenderVarScalarRangeSettings | None = None
    hdr: RenderVarHdrSettings | None = None
    vector: RenderVarVectorSettings | None = None
    categorical: RenderVarCategoricalSettings | None = None
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RenderVarPresetKind):
            object.__setattr__(self, "kind", RenderVarPresetKind(str(self.kind)))
        object.__setattr__(self, "label", str(self.label or self.kind.value))
        object.__setattr__(self, "options", _mapping_proxy(self.options))


@dataclass(frozen=True)
class RenderVarOutputDescriptor:
    """Backend-neutral descriptor for one visualizable RenderVar output."""

    output_id: str = ""
    render_product_path: str = ""
    render_var_name: str = ""
    display_name: str = ""
    output_kind: RenderVarOutputKind = RenderVarOutputKind.UNKNOWN
    dtype: str = ""
    shape: Tuple[int, ...] = field(default_factory=tuple)
    component_count: int = 1
    units: str = ""
    value_range: Tuple[float, float] | None = None
    color_space: str = ""
    validity_semantics: str = ""
    presets: Tuple[RenderVarVisualizationPreset, ...] = field(default_factory=tuple)
    capabilities: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[RenderVarWarning, ...] = field(default_factory=tuple)
    enabled: bool = True
    disabled_reason: str = ""
    revision_token: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        render_product_path = str(self.render_product_path or "")
        render_var_name = str(self.render_var_name or "")
        output_id = str(self.output_id or f"{render_product_path}:{render_var_name}")
        object.__setattr__(self, "output_id", output_id)
        object.__setattr__(self, "render_product_path", render_product_path)
        object.__setattr__(self, "render_var_name", render_var_name)
        object.__setattr__(
            self,
            "display_name",
            str(self.display_name or render_var_name or output_id),
        )
        if not isinstance(self.output_kind, RenderVarOutputKind):
            object.__setattr__(
                self,
                "output_kind",
                RenderVarOutputKind(str(self.output_kind)),
            )
        object.__setattr__(self, "dtype", str(self.dtype or ""))
        object.__setattr__(self, "shape", _int_tuple(self.shape))
        component_count = int(self.component_count)
        if component_count <= 0:
            raise ValueError("component_count must be positive")
        object.__setattr__(self, "component_count", component_count)
        object.__setattr__(self, "units", str(self.units or ""))
        object.__setattr__(self, "value_range", _coerce_range(self.value_range))
        object.__setattr__(self, "color_space", str(self.color_space or ""))
        object.__setattr__(
            self,
            "validity_semantics",
            str(self.validity_semantics or ""),
        )
        object.__setattr__(self, "presets", _presets_tuple(self.presets))
        object.__setattr__(self, "capabilities", _tuple_or_empty(self.capabilities))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "disabled_reason", str(self.disabled_reason or ""))
        object.__setattr__(self, "revision_token", str(self.revision_token or ""))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def is_available(self) -> bool:
        """Whether this output can currently be requested."""

        return bool(self.enabled and not self.disabled_reason)

    def supports_preset(self, kind: RenderVarPresetKind | str) -> bool:
        """Return true when the descriptor exposes a preset kind."""

        preset_kind = (
            kind if isinstance(kind, RenderVarPresetKind) else RenderVarPresetKind(str(kind))
        )
        return any(preset.kind is preset_kind for preset in self.presets)


@dataclass(frozen=True)
class RenderVarOutputCatalog:
    """Immutable snapshot of RenderVar outputs for a renderer/target."""

    outputs: Tuple[RenderVarOutputDescriptor, ...] = field(default_factory=tuple)
    active_render_product_path: str = ""
    active_output_id: str = ""
    selected_output_id: str = ""
    revision: str = ""
    warnings: Tuple[RenderVarWarning, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "outputs", tuple(self.outputs or ()))
        object.__setattr__(
            self,
            "active_render_product_path",
            str(self.active_render_product_path or ""),
        )
        object.__setattr__(self, "active_output_id", str(self.active_output_id or ""))
        object.__setattr__(self, "selected_output_id", str(self.selected_output_id or ""))
        object.__setattr__(self, "revision", str(self.revision or ""))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))

    @property
    def is_empty(self) -> bool:
        return not self.outputs

    def output(self, output_id: str) -> RenderVarOutputDescriptor | None:
        for descriptor in self.outputs:
            if descriptor.output_id == output_id:
                return descriptor
        return None


@dataclass(frozen=True)
class RenderVarOutputRequest:
    """Request to activate or update a RenderVar visualization."""

    viewport_id: str = ""
    render_product_path: str = ""
    output_id: str = ""
    render_var_name: str = ""
    preset: RenderVarVisualizationPreset | None = None
    enable_probe: bool = False
    options: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "viewport_id", str(self.viewport_id or ""))
        object.__setattr__(
            self,
            "render_product_path",
            str(self.render_product_path or ""),
        )
        object.__setattr__(self, "output_id", str(self.output_id or ""))
        object.__setattr__(self, "render_var_name", str(self.render_var_name or ""))
        object.__setattr__(self, "enable_probe", bool(self.enable_probe))
        object.__setattr__(self, "options", _mapping_proxy(self.options))


@dataclass(frozen=True)
class RenderVarOutputRequestResult:
    """Result returned by adapter RenderVar visualization request methods."""

    accepted: bool = False
    message: str = ""
    warning_code: Optional[str] = None
    active_request: RenderVarOutputRequest | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted", bool(self.accepted))
        object.__setattr__(self, "message", str(self.message or ""))
        if self.warning_code is not None:
            object.__setattr__(self, "warning_code", str(self.warning_code))

    @classmethod
    def accepted_result(
        cls,
        active_request: RenderVarOutputRequest | None = None,
        message: str = "",
    ) -> "RenderVarOutputRequestResult":
        return cls(True, message=message, active_request=active_request)

    @classmethod
    def rejected_result(
        cls,
        message: str,
        *,
        warning_code: str = "unsupported",
        active_request: RenderVarOutputRequest | None = None,
    ) -> "RenderVarOutputRequestResult":
        return cls(
            False,
            message=message,
            warning_code=warning_code,
            active_request=active_request,
        )


@dataclass(frozen=True)
class RenderVarOutputFrame:
    """Display-ready snapshot and optional raw data for one RenderVar output."""

    render_product_path: str = ""
    output_id: str = ""
    render_var_name: str = ""
    width: int = 0
    height: int = 0
    dtype: str = ""
    component_count: int = 4
    color_space: str = ""
    units: str = ""
    value_range: Tuple[float, float] | None = None
    display_data: Any = None
    raw_data: Any = None
    frame_index: Optional[int] = None
    timestamp: Optional[float] = None
    stale: bool = False
    warnings: Tuple[RenderVarWarning, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        width = int(self.width)
        height = int(self.height)
        if width < 0 or height < 0:
            raise ValueError("frame dimensions must be non-negative")
        component_count = int(self.component_count)
        if component_count <= 0:
            raise ValueError("component_count must be positive")
        object.__setattr__(self, "render_product_path", str(self.render_product_path or ""))
        object.__setattr__(self, "output_id", str(self.output_id or ""))
        object.__setattr__(self, "render_var_name", str(self.render_var_name or ""))
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "height", height)
        object.__setattr__(self, "dtype", str(self.dtype or ""))
        object.__setattr__(self, "component_count", component_count)
        object.__setattr__(self, "color_space", str(self.color_space or ""))
        object.__setattr__(self, "units", str(self.units or ""))
        object.__setattr__(self, "value_range", _coerce_range(self.value_range))
        if self.frame_index is not None:
            object.__setattr__(self, "frame_index", int(self.frame_index))
        if self.timestamp is not None:
            object.__setattr__(self, "timestamp", float(self.timestamp))
        object.__setattr__(self, "stale", bool(self.stale))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))
        object.__setattr__(self, "metadata", _mapping_proxy(self.metadata))

    @property
    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0 or self.display_data is None


@dataclass(frozen=True)
class RenderVarProbeRequest:
    """Request to read a raw RenderVar value at an image-space location."""

    viewport_id: str = ""
    render_product_path: str = ""
    output_id: str = ""
    render_var_name: str = ""
    pixel_x: int = 0
    pixel_y: int = 0
    normalized_x: Optional[float] = None
    normalized_y: Optional[float] = None
    frame_index: Optional[int] = None

    def __post_init__(self) -> None:
        pixel_x = int(self.pixel_x)
        pixel_y = int(self.pixel_y)
        if pixel_x < 0 or pixel_y < 0:
            raise ValueError("probe pixel coordinates must be non-negative")
        object.__setattr__(self, "viewport_id", str(self.viewport_id or ""))
        object.__setattr__(
            self,
            "render_product_path",
            str(self.render_product_path or ""),
        )
        object.__setattr__(self, "output_id", str(self.output_id or ""))
        object.__setattr__(self, "render_var_name", str(self.render_var_name or ""))
        object.__setattr__(self, "pixel_x", pixel_x)
        object.__setattr__(self, "pixel_y", pixel_y)
        if self.normalized_x is not None:
            x = float(self.normalized_x)
            if not 0.0 <= x <= 1.0:
                raise ValueError("normalized_x must be between 0 and 1")
            object.__setattr__(self, "normalized_x", x)
        if self.normalized_y is not None:
            y = float(self.normalized_y)
            if not 0.0 <= y <= 1.0:
                raise ValueError("normalized_y must be between 0 and 1")
            object.__setattr__(self, "normalized_y", y)
        if self.frame_index is not None:
            object.__setattr__(self, "frame_index", int(self.frame_index))


@dataclass(frozen=True)
class RenderVarProbeResult:
    """Raw-value probe result for scalar, vector, HDR, or categorical outputs."""

    accepted: bool = False
    render_product_path: str = ""
    output_id: str = ""
    render_var_name: str = ""
    pixel_x: int = 0
    pixel_y: int = 0
    raw_value: Any = None
    normalized_value: Any = None
    display_value: str = ""
    category_id: Optional[int] = None
    category_label: str = ""
    units: str = ""
    message: str = ""
    warning_code: Optional[str] = None
    frame_index: Optional[int] = None
    stale: bool = False
    warnings: Tuple[RenderVarWarning, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted", bool(self.accepted))
        object.__setattr__(self, "render_product_path", str(self.render_product_path or ""))
        object.__setattr__(self, "output_id", str(self.output_id or ""))
        object.__setattr__(self, "render_var_name", str(self.render_var_name or ""))
        object.__setattr__(self, "pixel_x", int(self.pixel_x))
        object.__setattr__(self, "pixel_y", int(self.pixel_y))
        object.__setattr__(self, "display_value", str(self.display_value or ""))
        if self.category_id is not None:
            object.__setattr__(self, "category_id", int(self.category_id))
        object.__setattr__(self, "category_label", str(self.category_label or ""))
        object.__setattr__(self, "units", str(self.units or ""))
        object.__setattr__(self, "message", str(self.message or ""))
        if self.warning_code is not None:
            object.__setattr__(self, "warning_code", str(self.warning_code))
        if self.frame_index is not None:
            object.__setattr__(self, "frame_index", int(self.frame_index))
        object.__setattr__(self, "stale", bool(self.stale))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))

    @classmethod
    def value_result(
        cls,
        *,
        raw_value: Any,
        normalized_value: Any = None,
        display_value: str = "",
        render_product_path: str = "",
        output_id: str = "",
        render_var_name: str = "",
        pixel_x: int = 0,
        pixel_y: int = 0,
        units: str = "",
        category_id: int | None = None,
        category_label: str = "",
    ) -> "RenderVarProbeResult":
        return cls(
            True,
            render_product_path=render_product_path,
            output_id=output_id,
            render_var_name=render_var_name,
            pixel_x=pixel_x,
            pixel_y=pixel_y,
            raw_value=raw_value,
            normalized_value=normalized_value,
            display_value=display_value,
            units=units,
            category_id=category_id,
            category_label=category_label,
        )

    @classmethod
    def unsupported_result(
        cls,
        message: str = "RenderVar probing is not supported.",
        warning_code: str = "unsupported",
    ) -> "RenderVarProbeResult":
        return cls(False, message=message, warning_code=warning_code)


__all__ = [
    "RenderVarCategoricalSettings",
    "RenderVarHdrSettings",
    "RenderVarOutputCatalog",
    "RenderVarOutputDescriptor",
    "RenderVarOutputFrame",
    "RenderVarOutputKind",
    "RenderVarOutputRequest",
    "RenderVarOutputRequestResult",
    "RenderVarPresetKind",
    "RenderVarProbeRequest",
    "RenderVarProbeResult",
    "RenderVarScalarRangeSettings",
    "RenderVarToneMap",
    "RenderVarVectorSettings",
    "RenderVarVisualizationPreset",
    "RenderVarWarning",
    "RenderVarWarningSeverity",
]
