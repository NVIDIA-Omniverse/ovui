# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Viewport-owned resolution state contract.

This module is deliberately UI-free and settings-free. It defines the small
immutable state shape that later viewport resolution tickets can read and
change without coupling to private render-loop fields.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass, field, replace
from math import isfinite
from numbers import Integral, Real
from typing import Any, Callable, Literal, Optional

RESOLUTION_MODE_VIEWPORT = "viewport"
RESOLUTION_MODE_FIXED = "fixed"
ResolutionMode = Literal["viewport", "fixed"]
ResolutionStateChangedCallback = Callable[
    ["ViewportResolutionState", "ViewportResolutionState"],
    None,
]
AvailabilityChangedCallback = Callable[
    ["ViewportAvailabilitySnapshot", "ViewportAvailabilitySnapshot"],
    None,
]

DEFAULT_REQUESTED_SIZE: tuple[int, int] = (0, 0)
DEFAULT_SCALE = 1.0
DEFAULT_SELECTED_LABEL = "Viewport"
DEFAULT_FIXED_SELECTED_LABEL = "Custom"
DEFAULT_MIN_WIDTH = 64
DEFAULT_MIN_HEIGHT = 64
DEFAULT_MAX_WIDTH = 3840
DEFAULT_MAX_HEIGHT = 2160

PRIVATE_RENDER_SIZE_ACCESS_RULE = (
    "Viewport resolution feature consumers outside the viewport foundation "
    "must read ViewportWidget.get_resolution_state() and must not read "
    "ViewportWidget._last_resolution directly."
)
AVAILABILITY_REASON_NO_RENDERER = "no renderer"
AVAILABILITY_REASON_NO_SETTINGS_SERVICE = "no settings service"
AVAILABILITY_REASON_OWNER_DESTROYED = "owner destroyed"
RESOLUTION_SETTINGS_PATH_CAPABILITY_GATE: Optional[str] = None


class ViewportResolutionStateError(ValueError):
    """Raised when a resolution state value cannot be accepted."""


class ViewportResolutionStateSubscription:
    """Unsubscribe handle returned by viewport resolution-state observation."""

    def __init__(self, owner: Any, token: int) -> None:
        self._owner_ref: Optional["weakref.ReferenceType[Any]"] = weakref.ref(owner)
        self._token = token
        self._active = True

    @property
    def active(self) -> bool:
        """Whether this handle can still remove a live observer."""

        return self._active

    def unsubscribe(self) -> bool:
        """Remove the observer. Safe to call more than once."""

        if not self._active:
            return False
        self._active = False
        owner_ref = self._owner_ref
        self._owner_ref = None
        owner = owner_ref() if owner_ref is not None else None
        if owner is None:
            return False
        unsubscribe = getattr(owner, "_unsubscribe_resolution_state", None)
        if not callable(unsubscribe):
            return False
        return bool(unsubscribe(self._token))

    def cancel(self) -> bool:
        """Alias for code that follows the existing settings subscription shape."""

        return self.unsubscribe()

    def _deactivate(self) -> None:
        self._active = False
        self._owner_ref = None

    def __del__(self) -> None:
        self.unsubscribe()


class ViewportAvailabilitySubscription:
    """Unsubscribe handle returned by viewport availability observation."""

    def __init__(self, owner: Any, token: int) -> None:
        self._owner_ref: Optional["weakref.ReferenceType[Any]"] = weakref.ref(owner)
        self._token = token
        self._active = True

    @property
    def active(self) -> bool:
        """Whether this handle can still remove a live observer."""

        return self._active

    def unsubscribe(self) -> bool:
        """Remove the observer. Safe to call more than once."""

        if not self._active:
            return False
        self._active = False
        owner_ref = self._owner_ref
        self._owner_ref = None
        owner = owner_ref() if owner_ref is not None else None
        if owner is None:
            return False
        unsubscribe = getattr(owner, "_unsubscribe_resolution_availability", None)
        if not callable(unsubscribe):
            return False
        return bool(unsubscribe(self._token))

    def cancel(self) -> bool:
        """Alias for code that follows the existing settings subscription shape."""

        return self.unsubscribe()

    def _deactivate(self) -> None:
        self._active = False
        self._owner_ref = None

    def __del__(self) -> None:
        self.unsubscribe()


def _coerce_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ViewportResolutionStateError(f"{field_name} must be an integer")
    return int(value)


def _coerce_size_pair(value: Any, field_name: str) -> tuple[int, int]:
    if isinstance(value, (str, bytes)):
        raise ViewportResolutionStateError(
            f"{field_name} must be a two-item integer sequence"
        )
    try:
        width, height = value
    except (TypeError, ValueError) as exc:
        raise ViewportResolutionStateError(
            f"{field_name} must be a two-item integer sequence"
        ) from exc
    return (
        _coerce_int(width, f"{field_name}.width"),
        _coerce_int(height, f"{field_name}.height"),
    )


def _coerce_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ViewportResolutionStateError(f"{field_name} must be a bool")
    return value


def _coerce_scale(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ViewportResolutionStateError("scale must be a positive finite number")
    scale = float(value)
    if not isfinite(scale) or scale <= 0.0:
        raise ViewportResolutionStateError("scale must be a positive finite number")
    return scale


def _coerce_mode(value: Any) -> ResolutionMode:
    if value == RESOLUTION_MODE_VIEWPORT:
        return RESOLUTION_MODE_VIEWPORT
    if value == RESOLUTION_MODE_FIXED:
        return RESOLUTION_MODE_FIXED
    raise ViewportResolutionStateError(
        "mode must be 'viewport' or 'fixed'"
    )


def _default_label(mode: ResolutionMode) -> str:
    if mode == RESOLUTION_MODE_VIEWPORT:
        return DEFAULT_SELECTED_LABEL
    return DEFAULT_FIXED_SELECTED_LABEL


def _normalize_label(value: Any, mode: ResolutionMode) -> str:
    if value is None:
        return _default_label(mode)
    if not isinstance(value, str):
        raise ViewportResolutionStateError("selected_label must be a string")
    label = value.strip()
    return label or _default_label(mode)


@dataclass(frozen=True)
class ResolutionClampLimits:
    """Accepted render-size bounds for the viewport resolution contract."""

    min_width: int = DEFAULT_MIN_WIDTH
    min_height: int = DEFAULT_MIN_HEIGHT
    max_width: int = DEFAULT_MAX_WIDTH
    max_height: int = DEFAULT_MAX_HEIGHT

    def __post_init__(self) -> None:
        min_width = _coerce_int(self.min_width, "min_width")
        min_height = _coerce_int(self.min_height, "min_height")
        max_width = _coerce_int(self.max_width, "max_width")
        max_height = _coerce_int(self.max_height, "max_height")
        if min_width <= 0 or min_height <= 0:
            raise ViewportResolutionStateError("minimum clamp must be positive")
        if max_width < min_width or max_height < min_height:
            raise ViewportResolutionStateError(
                "maximum clamp must be greater than or equal to minimum clamp"
            )
        object.__setattr__(self, "min_width", min_width)
        object.__setattr__(self, "min_height", min_height)
        object.__setattr__(self, "max_width", max_width)
        object.__setattr__(self, "max_height", max_height)

    def clamp_size(self, size: tuple[int, int]) -> tuple[int, int]:
        width, height = _coerce_size_pair(size, "size")
        if width <= 0 or height <= 0:
            raise ViewportResolutionStateError("size must be positive")
        return (
            max(self.min_width, min(self.max_width, width)),
            max(self.min_height, min(self.max_height, height)),
        )

    def clamp_minimum(self, size: tuple[int, int]) -> tuple[int, int]:
        width, height = _coerce_size_pair(size, "size")
        if width <= 0 or height <= 0:
            raise ViewportResolutionStateError("size must be positive")
        return (
            max(self.min_width, width),
            max(self.min_height, height),
        )


@dataclass(frozen=True)
class ViewportResolutionState:
    """Canonical per-viewport resolution state record.

    ``mode='viewport'`` preserves current ovui behavior: the visible image
    widget size remains the render-size source. ``mode='fixed'`` stores a
    positive requested full-resolution size for later tickets to apply.
    """

    mode: ResolutionMode = RESOLUTION_MODE_VIEWPORT
    requested_size: tuple[int, int] = DEFAULT_REQUESTED_SIZE
    scale: float = DEFAULT_SCALE
    fill_viewport: bool = False
    uses_dpi: bool = False
    clamp_limits: ResolutionClampLimits = field(
        default_factory=ResolutionClampLimits
    )
    selected_label: str = DEFAULT_SELECTED_LABEL
    effective_size: Optional[tuple[int, int]] = None

    def __post_init__(self) -> None:
        mode = _coerce_mode(self.mode)
        limits = self.clamp_limits
        if not isinstance(limits, ResolutionClampLimits):
            try:
                limits = ResolutionClampLimits(*limits)
            except TypeError as exc:
                raise ViewportResolutionStateError(
                    "clamp_limits must be ResolutionClampLimits or a four-item sequence"
                ) from exc

        requested_size = _normalize_requested_size(
            mode, self.requested_size, limits
        )
        fill_viewport = _coerce_bool(self.fill_viewport, "fill_viewport")
        if mode == RESOLUTION_MODE_VIEWPORT:
            fill_viewport = False
        effective_size = _normalize_effective_size(self.effective_size, limits)

        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "requested_size", requested_size)
        object.__setattr__(self, "scale", _coerce_scale(self.scale))
        object.__setattr__(self, "fill_viewport", fill_viewport)
        object.__setattr__(self, "uses_dpi", _coerce_bool(self.uses_dpi, "uses_dpi"))
        object.__setattr__(self, "clamp_limits", limits)
        object.__setattr__(
            self,
            "selected_label",
            _normalize_label(self.selected_label, mode),
        )
        object.__setattr__(self, "effective_size", effective_size)

    @classmethod
    def default(
        cls,
        *,
        clamp_limits: Optional[ResolutionClampLimits] = None,
    ) -> "ViewportResolutionState":
        return cls(
            clamp_limits=clamp_limits
            if clamp_limits is not None
            else ResolutionClampLimits()
        )

    @property
    def is_viewport_mode(self) -> bool:
        return self.mode == RESOLUTION_MODE_VIEWPORT

    @property
    def is_fixed_mode(self) -> bool:
        return self.mode == RESOLUTION_MODE_FIXED

    def with_changes(self, **changes: Any) -> "ViewportResolutionState":
        """Return a validated copy with ``changes`` applied."""

        return replace(self, **changes)


@dataclass(frozen=True)
class ViewportAvailabilitySnapshot:
    """Foundation availability facts for later resolution UI consumers.

    The snapshot reports source facts only. A missing renderer or settings
    service never encodes a hidden Settings-path capability gate; later UI
    tickets decide disabled presentation from these facts.
    """

    renderer_available: bool = False
    settings_available: bool = False
    owner_alive: bool = True
    settings_path_hidden_by_capability_gate: bool = False
    unavailable_reasons: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        renderer_available = _coerce_bool(
            self.renderer_available,
            "renderer_available",
        )
        settings_available = _coerce_bool(
            self.settings_available,
            "settings_available",
        )
        owner_alive = _coerce_bool(self.owner_alive, "owner_alive")
        _coerce_bool(
            self.settings_path_hidden_by_capability_gate,
            "settings_path_hidden_by_capability_gate",
        )
        reasons: list[str] = []
        if not renderer_available:
            reasons.append(AVAILABILITY_REASON_NO_RENDERER)
        if not settings_available:
            reasons.append(AVAILABILITY_REASON_NO_SETTINGS_SERVICE)
        if not owner_alive:
            reasons.append(AVAILABILITY_REASON_OWNER_DESTROYED)

        object.__setattr__(self, "renderer_available", renderer_available)
        object.__setattr__(self, "settings_available", settings_available)
        object.__setattr__(self, "owner_alive", owner_alive)
        object.__setattr__(
            self,
            "settings_path_hidden_by_capability_gate",
            False,
        )
        object.__setattr__(self, "unavailable_reasons", tuple(reasons))


def _normalize_requested_size(
    mode: ResolutionMode,
    requested_size: tuple[int, int],
    limits: ResolutionClampLimits,
) -> tuple[int, int]:
    if mode == RESOLUTION_MODE_VIEWPORT:
        return DEFAULT_REQUESTED_SIZE
    return limits.clamp_minimum(_coerce_size_pair(requested_size, "requested_size"))


def _normalize_effective_size(
    effective_size: Optional[tuple[int, int]],
    limits: ResolutionClampLimits,
) -> Optional[tuple[int, int]]:
    if effective_size is None:
        return None
    return limits.clamp_size(_coerce_size_pair(effective_size, "effective_size"))
