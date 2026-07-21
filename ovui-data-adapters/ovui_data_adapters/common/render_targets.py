# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Backend-neutral render target contracts.

These plain-data contracts describe viewport-selectable render targets without
exposing USD prims, renderer handles, or UI objects. Concrete adapters can build
the richer catalogs in backend-specific packages while optional UI modules
consume only these common types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Tuple


class _StableStringEnum(str, Enum):
    """String enum whose values are stable public contract tokens."""

    def __str__(self) -> str:
        return self.value


class RenderTargetKind(_StableStringEnum):
    """High-level group for a selectable render target."""

    CAMERA = "camera"
    SENSOR = "sensor"
    RENDER_PRODUCT = "render_product"
    UNKNOWN = "unknown"


class RenderTargetOutputKind(_StableStringEnum):
    """Output family produced by a target."""

    IMAGE = "image"
    POINT_CLOUD = "point_cloud"
    GENERIC_MODEL_OUTPUT = "generic_model_output"
    MULTI_OUTPUT = "multi_output"
    UNKNOWN = "unknown"


class RenderTargetWarningSeverity(_StableStringEnum):
    """Severity for target catalog and activation warnings."""

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
    value: Iterable["RenderTargetWarning"] | "RenderTargetWarning" | None,
) -> Tuple["RenderTargetWarning", ...]:
    if value is None:
        return ()
    if isinstance(value, RenderTargetWarning):
        return (value,)
    return tuple(value)


def _coerce_resolution(value: Iterable[int] | None) -> Tuple[int, int] | None:
    if value is None:
        return None
    items = tuple(value)
    if len(items) != 2:
        raise ValueError("resolution must contain width and height")
    return (int(items[0]), int(items[1]))


@dataclass(frozen=True)
class RenderTargetWarning:
    """Warning or disabled-state reason attached to a render target."""

    code: str
    message: str
    severity: RenderTargetWarningSeverity = RenderTargetWarningSeverity.WARNING

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", str(self.code))
        object.__setattr__(self, "message", str(self.message))
        if not isinstance(self.severity, RenderTargetWarningSeverity):
            object.__setattr__(
                self,
                "severity",
                RenderTargetWarningSeverity(str(self.severity)),
            )


@dataclass(frozen=True)
class RenderTargetDescriptor:
    """Backend-neutral descriptor for one viewport-selectable target."""

    target_id: str = ""
    render_product_path: str = ""
    display_name: str = ""
    kind: RenderTargetKind = RenderTargetKind.UNKNOWN
    source_path: Optional[str] = None
    source_display_name: str = ""
    source_type: str = ""
    output_kind: RenderTargetOutputKind = RenderTargetOutputKind.UNKNOWN
    output_names: Tuple[str, ...] = field(default_factory=tuple)
    resolution: Tuple[int, int] | None = None
    capabilities: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[RenderTargetWarning, ...] = field(default_factory=tuple)
    enabled: bool = True
    disabled_reason: str = ""

    def __post_init__(self) -> None:
        target_id = str(self.target_id or self.render_product_path or "")
        display_name = str(
            self.display_name
            or self.source_display_name
            or self.render_product_path
            or target_id
        )
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "render_product_path", str(self.render_product_path or ""))
        object.__setattr__(self, "display_name", display_name)
        if self.source_path is not None:
            object.__setattr__(self, "source_path", str(self.source_path))
        object.__setattr__(self, "source_display_name", str(self.source_display_name or ""))
        object.__setattr__(self, "source_type", str(self.source_type or ""))
        if not isinstance(self.kind, RenderTargetKind):
            object.__setattr__(self, "kind", RenderTargetKind(str(self.kind)))
        if not isinstance(self.output_kind, RenderTargetOutputKind):
            object.__setattr__(
                self,
                "output_kind",
                RenderTargetOutputKind(str(self.output_kind)),
            )
        object.__setattr__(self, "output_names", _tuple_or_empty(self.output_names))
        object.__setattr__(self, "resolution", _coerce_resolution(self.resolution))
        object.__setattr__(self, "capabilities", _tuple_or_empty(self.capabilities))
        object.__setattr__(self, "warnings", _warnings_tuple(self.warnings))
        object.__setattr__(self, "enabled", bool(self.enabled))
        object.__setattr__(self, "disabled_reason", str(self.disabled_reason or ""))

    @property
    def display_label(self) -> str:
        """User-facing label fallback used by menu models."""

        return self.display_name or self.render_product_path or self.target_id

    @property
    def is_selectable(self) -> bool:
        """Whether the target should be activatable by UI code."""

        return bool(self.enabled and not self.disabled_reason)


@dataclass(frozen=True)
class RenderTargetCatalog:
    """Immutable snapshot of available render targets."""

    targets: Tuple[RenderTargetDescriptor, ...] = field(default_factory=tuple)
    active_target_id: Optional[str] = None
    active_render_product_path: Optional[str] = None
    revision: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "targets", tuple(self.targets))
        if self.active_target_id is not None:
            object.__setattr__(self, "active_target_id", str(self.active_target_id))
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
        """True when the catalog has no target descriptors."""

        return not self.targets


@dataclass(frozen=True)
class RenderTargetActivationResult:
    """Result of requesting an active render target change."""

    accepted: bool = False
    active_target_id: Optional[str] = None
    active_render_product_path: Optional[str] = None
    message: str = ""
    warning_code: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "accepted", bool(self.accepted))
        if self.active_target_id is not None:
            object.__setattr__(self, "active_target_id", str(self.active_target_id))
        if self.active_render_product_path is not None:
            object.__setattr__(
                self,
                "active_render_product_path",
                str(self.active_render_product_path),
            )
        object.__setattr__(self, "message", str(self.message or ""))
        if self.warning_code is not None:
            object.__setattr__(self, "warning_code", str(self.warning_code))

    @classmethod
    def accepted_result(
        cls,
        *,
        active_target_id: str = "",
        active_render_product_path: str = "",
        message: str = "",
    ) -> "RenderTargetActivationResult":
        """Build a successful activation result."""

        return cls(
            accepted=True,
            active_target_id=active_target_id or None,
            active_render_product_path=active_render_product_path or None,
            message=message,
        )

    @classmethod
    def rejected_result(
        cls,
        message: str = "",
        *,
        warning_code: str = "",
        active_target_id: str = "",
        active_render_product_path: str = "",
    ) -> "RenderTargetActivationResult":
        """Build a rejected activation result."""

        return cls(
            accepted=False,
            active_target_id=active_target_id or None,
            active_render_product_path=active_render_product_path or None,
            message=message,
            warning_code=warning_code or None,
        )


__all__ = [
    "RenderTargetActivationResult",
    "RenderTargetCatalog",
    "RenderTargetDescriptor",
    "RenderTargetKind",
    "RenderTargetOutputKind",
    "RenderTargetWarning",
    "RenderTargetWarningSeverity",
]
