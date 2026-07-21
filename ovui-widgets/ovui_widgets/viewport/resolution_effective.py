# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Effective render-size formulas for viewport resolution state."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite
from numbers import Integral, Real
from typing import Any

from ovui_widgets.viewport.resolution_state import (
    ResolutionClampLimits,
    ViewportResolutionState,
    ViewportResolutionStateError,
)


@dataclass(frozen=True)
class DpiAdjustedFullDimensions:
    """Frame-derived full dimensions after the Area 3 DPI policy branch."""

    visible_frame_size: tuple[int, int]
    dpi_enabled: bool
    dpi_available: bool
    requested_dpi_scale: float
    applied_dpi_scale: float
    full_size: tuple[int, int]


@dataclass(frozen=True)
class ViewportModeEffectiveResolution:
    """Committed SRD section 9.3 Viewport-mode render-size details."""

    visible_frame_size: tuple[int, int]
    dpi_scale: float
    render_scale: float
    clamp_limits: ResolutionClampLimits
    full_size: tuple[int, int]
    scaled_size: tuple[int, int]
    effective_size: tuple[int, int]
    dpi_enabled: bool = True
    dpi_available: bool = True
    requested_dpi_scale: float = 1.0

    @property
    def width(self) -> int:
        return self.effective_size[0]

    @property
    def height(self) -> int:
        return self.effective_size[1]

    @property
    def clamped(self) -> bool:
        return self.effective_size != self.scaled_size


@dataclass(frozen=True)
class FixedModeEffectiveResolution:
    """Committed SRD section 9.3 fixed-mode render-size details."""

    requested_full_size: tuple[int, int]
    render_scale: float
    clamp_limits: ResolutionClampLimits
    full_size: tuple[float, float]
    scaled_size: tuple[int, int]
    effective_size: tuple[int, int]
    fill_viewport: bool = False
    visible_frame_size: tuple[int, int] | None = None
    dpi_scale: float = 1.0
    dpi_enabled: bool = False
    dpi_available: bool = True
    requested_dpi_scale: float = 1.0
    selected_aspect_ratio: float | None = None
    viewport_aspect_ratio: float | None = None
    expanded_size: tuple[float, float] | None = None

    @property
    def width(self) -> int:
        return self.effective_size[0]

    @property
    def height(self) -> int:
        return self.effective_size[1]

    @property
    def clamped(self) -> bool:
        return self.effective_size != self.scaled_size


def _coerce_visible_dimension(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ViewportResolutionStateError(
            f"{field_name} must be a non-negative finite number"
        )
    dimension = float(value)
    if not isfinite(dimension) or dimension < 0.0:
        raise ViewportResolutionStateError(
            f"{field_name} must be a non-negative finite number"
        )
    return dimension


def _coerce_positive_float(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ViewportResolutionStateError(
            f"{field_name} must be a positive finite number"
        )
    result = float(value)
    if not isfinite(result) or result <= 0.0:
        raise ViewportResolutionStateError(
            f"{field_name} must be a positive finite number"
        )
    return result


def _coerce_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ViewportResolutionStateError(f"{field_name} must be a bool")
    return value


def _coerce_selected_dimension(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ViewportResolutionStateError(f"{field_name} must be a positive integer")
    dimension = int(value)
    if dimension <= 0:
        raise ViewportResolutionStateError(f"{field_name} must be a positive integer")
    return dimension


def _coerce_visible_frame_size(value: Any) -> tuple[float, float]:
    if isinstance(value, (str, bytes)):
        raise ViewportResolutionStateError(
            "visible_frame_size must be a two-item numeric sequence"
        )
    try:
        width, height = value
    except (TypeError, ValueError) as exc:
        raise ViewportResolutionStateError(
            "visible_frame_size must be a two-item numeric sequence"
        ) from exc
    return (
        _coerce_visible_dimension(width, "visible_frame_size.width"),
        _coerce_visible_dimension(height, "visible_frame_size.height"),
    )


def _coerce_selected_full_size(value: Any) -> tuple[int, int]:
    if isinstance(value, (str, bytes)):
        raise ViewportResolutionStateError(
            "selected_size must be a two-item positive integer sequence"
        )
    try:
        width, height = value
    except (TypeError, ValueError) as exc:
        raise ViewportResolutionStateError(
            "selected_size must be a two-item positive integer sequence"
        ) from exc
    return (
        _coerce_selected_dimension(width, "selected_size.width"),
        _coerce_selected_dimension(height, "selected_size.height"),
    )


def _coerce_clamp_limits(
    clamp_limits: ResolutionClampLimits | None,
) -> ResolutionClampLimits:
    limits = clamp_limits or ResolutionClampLimits()
    if not isinstance(limits, ResolutionClampLimits):
        raise ViewportResolutionStateError(
            "clamp_limits must be ResolutionClampLimits"
        )
    return limits


def _clamp_after_scale(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _coerce_renderer_request_dimension(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ViewportResolutionStateError(f"{field_name} must be a finite number")
    dimension = float(value)
    if not isfinite(dimension):
        raise ViewportResolutionStateError(f"{field_name} must be a finite number")
    return int(dimension)


def ensure_safe_renderer_request_size(size: Any) -> tuple[int, int]:
    """Final guard so renderer calls never receive zero or negative dimensions."""

    if isinstance(size, (str, bytes)):
        raise ViewportResolutionStateError(
            "renderer request size must be a two-item numeric sequence"
        )
    try:
        width, height = size
    except (TypeError, ValueError) as exc:
        raise ViewportResolutionStateError(
            "renderer request size must be a two-item numeric sequence"
        ) from exc
    guarded_width = max(1, _coerce_renderer_request_dimension(width, "width"))
    guarded_height = max(1, _coerce_renderer_request_dimension(height, "height"))
    return (guarded_width, guarded_height)


def compute_dpi_adjusted_frame_full_dimensions(
    visible_frame_size: Any,
    *,
    dpi_enabled: Any = True,
    dpi_available: Any = True,
    dpi_scale: Any = 1.0,
) -> DpiAdjustedFullDimensions:
    """Compute frame-derived full dimensions with the SRD DPI branch.

    Viewport mode and the later Fill Viewport full-dimension path both start
    from visible frame dimensions. DPI is applied only when the requested
    policy is enabled and a scale is available; otherwise Area 3 falls back to
    D=1.0 without asking the menu layer to guess.
    """

    visible_width, visible_height = _coerce_visible_frame_size(visible_frame_size)
    enabled = _coerce_bool(dpi_enabled, "dpi_enabled")
    available = _coerce_bool(dpi_available, "dpi_available")
    requested_dpi = _coerce_positive_float(dpi_scale, "dpi_scale")
    applied_dpi = requested_dpi if enabled and available else 1.0
    full_width = max(1, floor(visible_width * applied_dpi))
    full_height = max(1, floor(visible_height * applied_dpi))

    return DpiAdjustedFullDimensions(
        visible_frame_size=(int(visible_width), int(visible_height)),
        dpi_enabled=enabled,
        dpi_available=available,
        requested_dpi_scale=requested_dpi,
        applied_dpi_scale=applied_dpi,
        full_size=(full_width, full_height),
    )


def compute_viewport_mode_effective_resolution(
    visible_frame_size: Any,
    *,
    dpi_enabled: Any = True,
    dpi_available: Any = True,
    dpi_scale: Any = 1.0,
    render_scale: Any = 1.0,
    clamp_limits: ResolutionClampLimits | None = None,
) -> ViewportModeEffectiveResolution:
    """Compute SRD section 9.3 Viewport-mode effective render size.

    Viewport mode derives the full resolution from the visible frame in UI
    pixels and the DPI policy, applies Render Scale, then clamps the renderer
    request after scale. It does not inspect preset rows.
    """

    dpi_full = compute_dpi_adjusted_frame_full_dimensions(
        visible_frame_size,
        dpi_enabled=dpi_enabled,
        dpi_available=dpi_available,
        dpi_scale=dpi_scale,
    )
    scale = _coerce_positive_float(render_scale, "render_scale")
    limits = _coerce_clamp_limits(clamp_limits)

    full_width, full_height = dpi_full.full_size
    scaled_width = floor(full_width * scale)
    scaled_height = floor(full_height * scale)
    effective_width = _clamp_after_scale(
        scaled_width,
        limits.min_width,
        limits.max_width,
    )
    effective_height = _clamp_after_scale(
        scaled_height,
        limits.min_height,
        limits.max_height,
    )

    effective_size = ensure_safe_renderer_request_size(
        (effective_width, effective_height)
    )

    return ViewportModeEffectiveResolution(
        visible_frame_size=dpi_full.visible_frame_size,
        dpi_scale=dpi_full.applied_dpi_scale,
        render_scale=scale,
        clamp_limits=limits,
        full_size=(full_width, full_height),
        scaled_size=(scaled_width, scaled_height),
        effective_size=effective_size,
        dpi_enabled=dpi_full.dpi_enabled,
        dpi_available=dpi_full.dpi_available,
        requested_dpi_scale=dpi_full.requested_dpi_scale,
    )


def compute_fixed_mode_effective_resolution(
    selected_size: Any,
    *,
    render_scale: Any = 1.0,
    clamp_limits: ResolutionClampLimits | None = None,
    fill_viewport: Any = False,
    visible_frame_size: Any | None = None,
    dpi_enabled: Any = True,
    dpi_available: Any = True,
    dpi_scale: Any = 1.0,
) -> FixedModeEffectiveResolution:
    """Compute SRD section 9.3 fixed-mode effective render size.

    Fixed mode uses the accepted requested full resolution selected by Area 2,
    optionally expands that full resolution toward the visible frame when Fill
    Viewport is accepted, applies Render Scale, then clamps the renderer
    request after scale.
    """

    selected_width, selected_height = _coerce_selected_full_size(selected_size)
    scale = _coerce_positive_float(render_scale, "render_scale")
    limits = _coerce_clamp_limits(clamp_limits)
    fill = _coerce_bool(fill_viewport, "fill_viewport")

    full_width: float = float(selected_width)
    full_height: float = float(selected_height)
    dpi_full: DpiAdjustedFullDimensions | None = None
    selected_aspect: float | None = None
    viewport_aspect: float | None = None
    expanded_size: tuple[float, float] | None = None
    if fill:
        if visible_frame_size is None:
            raise ViewportResolutionStateError(
                "visible_frame_size is required when Fill Viewport is on"
            )
        dpi_full = compute_dpi_adjusted_frame_full_dimensions(
            visible_frame_size,
            dpi_enabled=dpi_enabled,
            dpi_available=dpi_available,
            dpi_scale=dpi_scale,
        )
        selected_aspect = selected_width / selected_height
        frame_width, frame_height = dpi_full.full_size
        viewport_aspect = frame_width / frame_height
        if selected_aspect < viewport_aspect:
            expanded_width = selected_width * (viewport_aspect / selected_aspect)
            expanded_height = float(selected_height)
        else:
            expanded_width = float(selected_width)
            expanded_height = selected_height * (selected_aspect / viewport_aspect)
        expanded_size = (expanded_width, expanded_height)
        full_width = expanded_width
        full_height = expanded_height

    scaled_width = floor(full_width * scale)
    scaled_height = floor(full_height * scale)
    effective_width = _clamp_after_scale(
        scaled_width,
        limits.min_width,
        limits.max_width,
    )
    effective_height = _clamp_after_scale(
        scaled_height,
        limits.min_height,
        limits.max_height,
    )

    effective_size = ensure_safe_renderer_request_size(
        (effective_width, effective_height)
    )

    return FixedModeEffectiveResolution(
        requested_full_size=(selected_width, selected_height),
        render_scale=scale,
        clamp_limits=limits,
        full_size=(full_width, full_height),
        scaled_size=(scaled_width, scaled_height),
        effective_size=effective_size,
        fill_viewport=fill,
        visible_frame_size=dpi_full.visible_frame_size if dpi_full is not None else None,
        dpi_scale=dpi_full.applied_dpi_scale if dpi_full is not None else 1.0,
        dpi_enabled=dpi_full.dpi_enabled if dpi_full is not None else False,
        dpi_available=dpi_full.dpi_available if dpi_full is not None else True,
        requested_dpi_scale=(
            dpi_full.requested_dpi_scale if dpi_full is not None else 1.0
        ),
        selected_aspect_ratio=selected_aspect,
        viewport_aspect_ratio=viewport_aspect,
        expanded_size=expanded_size,
    )


def compute_viewport_mode_effective_resolution_for_state(
    visible_frame_size: Any,
    state: ViewportResolutionState,
    *,
    dpi_scale: Any = 1.0,
    dpi_available: Any = True,
) -> ViewportModeEffectiveResolution:
    """Compute Viewport-mode effective size from the accepted viewport state."""

    if not isinstance(state, ViewportResolutionState):
        raise ViewportResolutionStateError(
            "state must be a ViewportResolutionState"
        )
    if not state.is_viewport_mode:
        raise ViewportResolutionStateError("state must be in Viewport mode")
    return compute_viewport_mode_effective_resolution(
        visible_frame_size,
        dpi_enabled=state.uses_dpi,
        dpi_available=dpi_available,
        dpi_scale=dpi_scale,
        render_scale=state.scale,
        clamp_limits=state.clamp_limits,
    )


def compute_fixed_mode_effective_resolution_for_state(
    state: ViewportResolutionState,
    *,
    visible_frame_size: Any | None = None,
    dpi_scale: Any = 1.0,
    dpi_available: Any = True,
) -> FixedModeEffectiveResolution:
    """Compute fixed-mode effective size from the accepted viewport state."""

    if not isinstance(state, ViewportResolutionState):
        raise ViewportResolutionStateError(
            "state must be a ViewportResolutionState"
        )
    if not state.is_fixed_mode:
        raise ViewportResolutionStateError("state must be in fixed mode")
    return compute_fixed_mode_effective_resolution(
        state.requested_size,
        render_scale=state.scale,
        clamp_limits=state.clamp_limits,
        fill_viewport=state.fill_viewport,
        visible_frame_size=visible_frame_size,
        dpi_enabled=state.uses_dpi,
        dpi_scale=dpi_scale,
        dpi_available=dpi_available,
    )


def _format_size_text(size: tuple[float, float] | tuple[int, int]) -> str:
    def _format_part(value: float | int) -> str:
        if isinstance(value, Integral):
            return str(int(value))
        if float(value).is_integer():
            return str(int(value))
        return f"{float(value):.2f}"

    return f"{_format_part(size[0])}x{_format_part(size[1])}"


def format_viewport_effective_resolution_qa_lines(
    *,
    profile_label: str,
    requested_label: str,
    effective: ViewportModeEffectiveResolution | FixedModeEffectiveResolution | None,
    missing_settings_profile: bool = False,
    status_message: str = "",
) -> tuple[str, ...]:
    """Visible QA scaffold text for Area 3 effective render math."""

    lines = [
        "A3 Effective Resolution QA Scaffold",
        f"Profile: {profile_label}",
        f"Requested Resolution Selection: {requested_label}",
    ]
    if missing_settings_profile:
        lines.append("Missing resolution settings profile: defaults active")
    if status_message:
        lines.append(f"Status: {status_message}")
    if effective is None:
        lines.extend(
            [
                "Committed Effective Size: pending render",
                "HUD Proof: normal RES line updates after render",
            ]
        )
    else:
        if isinstance(effective, ViewportModeEffectiveResolution):
            lines.extend(
                [
                    "Mode Formula: Viewport full=max(1,floor(U*D)); scaled=floor(full*S)",
                    "Source: visible viewport frame, DPI policy, Render Scale, clamp bounds",
                    (
                        "Visible Frame: "
                        f"{effective.visible_frame_size[0]}x{effective.visible_frame_size[1]}"
                    ),
                    (
                        "DPI Policy: "
                        f"enabled={effective.dpi_enabled} | "
                        f"available={effective.dpi_available} | "
                        f"requested D={effective.requested_dpi_scale:g} | "
                        f"applied D={effective.dpi_scale:g} | "
                        f"Render Scale S: {effective.render_scale:g}"
                    ),
                ]
            )
        else:
            if effective.fill_viewport:
                lines.extend(
                    [
                        (
                            "Mode Formula: Fixed Fill aspect-expand; "
                            "scaled=floor(full*S)"
                        ),
                        (
                            "Source: requested full size, visible frame, DPI policy, "
                            "Render Scale, clamp bounds"
                        ),
                        (
                            "Requested Full Size: "
                            f"{effective.requested_full_size[0]}x{effective.requested_full_size[1]}"
                        ),
                        (
                            "Visible Frame: "
                            f"{effective.visible_frame_size[0]}x{effective.visible_frame_size[1]}"
                            if effective.visible_frame_size is not None
                            else "Visible Frame: unavailable"
                        ),
                        (
                            "DPI Policy: "
                            f"enabled={effective.dpi_enabled} | "
                            f"available={effective.dpi_available} | "
                            f"requested D={effective.requested_dpi_scale:g} | "
                            f"applied D={effective.dpi_scale:g} | "
                            f"Render Scale S: {effective.render_scale:g}"
                        ),
                        (
                            "Fill Viewport: on; expands toward visible frame "
                            "before scale"
                        ),
                        (
                            "Aspect: "
                            f"selected={effective.selected_aspect_ratio:.3f} | "
                            f"viewport={effective.viewport_aspect_ratio:.3f}"
                        ),
                    ]
                )
            else:
                lines.extend(
                    [
                        "Mode Formula: Fixed full=selected; scaled=floor(full*S)",
                        "Source: requested full size, Render Scale, clamp bounds",
                        (
                            "Requested Full Size: "
                            f"{effective.requested_full_size[0]}x{effective.requested_full_size[1]}"
                        ),
                        f"Render Scale S: {effective.render_scale:g}",
                        "Fill Viewport: off; selection remains keyed to requested full size",
                    ]
                )
        lines.extend(
            [
                f"Full Size: {_format_size_text(effective.full_size)}",
                f"Scaled Size: {effective.scaled_size[0]}x{effective.scaled_size[1]}",
                (
                    "Clamp Bounds: "
                    f"{effective.clamp_limits.min_width}x{effective.clamp_limits.min_height}"
                    " .. "
                    f"{effective.clamp_limits.max_width}x{effective.clamp_limits.max_height}"
                ),
                (
                    "Committed Effective Size: "
                    f"{effective.effective_size[0]}x{effective.effective_size[1]}"
                ),
                "HUD Proof: normal RES line shows the committed effective size",
            ]
        )
    lines.extend(
        [
            "Area 3 owns effective-size math; Area 6 owns later menu/HUD synchronization policy.",
            "No product Settings menu, overlay panel, standalone Resolution button, or toolbar text mirror.",
        ]
    )
    return tuple(lines)
