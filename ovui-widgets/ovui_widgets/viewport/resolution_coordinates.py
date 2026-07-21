# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Coordinate mapping for effective-resolution viewport interaction."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Real
from typing import Any

from ovui_widgets.viewport.resolution_state import ViewportResolutionStateError

_EPSILON = 1e-6


@dataclass(frozen=True)
class AspectFitDisplayRect:
    """Visible preserve-aspect-fit rectangle for a render inside a widget."""

    frame_size: tuple[int, int]
    render_size: tuple[int, int]
    x: float
    y: float
    width: float
    height: float
    scale: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def pillarbox_left(self) -> float:
        return self.x

    @property
    def pillarbox_right(self) -> float:
        return self.frame_size[0] - self.right

    @property
    def letterbox_top(self) -> float:
        return self.y

    @property
    def letterbox_bottom(self) -> float:
        return self.frame_size[1] - self.bottom

    def contains_widget_pixel(self, x: float, y: float) -> bool:
        return (
            self.x - _EPSILON <= x <= self.right + _EPSILON
            and self.y - _EPSILON <= y <= self.bottom + _EPSILON
        )


@dataclass(frozen=True)
class RenderNdcMapping:
    """Mapping result from full-widget NDC into effective render coordinates."""

    widget_ndc: tuple[float, float]
    widget_pixel: tuple[float, float]
    render_ndc: tuple[float, float]
    render_pixel: tuple[float, float]
    display_rect: AspectFitDisplayRect


@dataclass(frozen=True)
class AspectFitNdcTransform:
    """Clip-space transform that places render NDC in the aspect-fit rect."""

    frame_size: tuple[int, int]
    render_size: tuple[int, int]
    scale_x: float
    scale_y: float
    offset_x: float
    offset_y: float
    display_rect: AspectFitDisplayRect


def _coerce_positive_dimension(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ViewportResolutionStateError(f"{field_name} must be a positive number")
    dimension = float(value)
    if not isfinite(dimension) or dimension <= 0.0:
        raise ViewportResolutionStateError(f"{field_name} must be a positive number")
    return int(dimension)


def _coerce_size(value: Any, field_name: str) -> tuple[int, int]:
    if isinstance(value, (str, bytes)):
        raise ViewportResolutionStateError(
            f"{field_name} must be a two-item positive numeric sequence"
        )
    try:
        width, height = value
    except (TypeError, ValueError) as exc:
        raise ViewportResolutionStateError(
            f"{field_name} must be a two-item positive numeric sequence"
        ) from exc
    return (
        _coerce_positive_dimension(width, f"{field_name}.width"),
        _coerce_positive_dimension(height, f"{field_name}.height"),
    )


def compute_aspect_fit_display_rect(
    frame_size: Any,
    render_size: Any,
) -> AspectFitDisplayRect:
    """Return the on-screen CONTAIN rect for an effective render size."""

    frame_w, frame_h = _coerce_size(frame_size, "frame_size")
    render_w, render_h = _coerce_size(render_size, "render_size")
    scale = min(frame_w / render_w, frame_h / render_h)
    display_w = render_w * scale
    display_h = render_h * scale
    x = (frame_w - display_w) * 0.5
    y = (frame_h - display_h) * 0.5
    return AspectFitDisplayRect(
        frame_size=(frame_w, frame_h),
        render_size=(render_w, render_h),
        x=x,
        y=y,
        width=display_w,
        height=display_h,
        scale=scale,
    )


def compute_aspect_fit_ndc_transform(
    frame_size: Any,
    render_size: Any,
) -> AspectFitNdcTransform:
    """Return render-NDC → widget-NDC scale/offset for SceneView overlays."""

    rect = compute_aspect_fit_display_rect(frame_size, render_size)
    frame_w, frame_h = rect.frame_size
    scale_x = rect.width / frame_w
    scale_y = rect.height / frame_h
    offset_x = ((rect.x + rect.width * 0.5) / frame_w) * 2.0 - 1.0
    offset_y = 1.0 - ((rect.y + rect.height * 0.5) / frame_h) * 2.0
    return AspectFitNdcTransform(
        frame_size=rect.frame_size,
        render_size=rect.render_size,
        scale_x=scale_x,
        scale_y=scale_y,
        offset_x=offset_x,
        offset_y=offset_y,
        display_rect=rect,
    )


def apply_aspect_fit_projection_transform(
    projection: Any,
    frame_size: Any,
    render_size: Any,
) -> Any:
    """Transform a render projection so overlays land in the displayed image."""

    transform = compute_aspect_fit_ndc_transform(frame_size, render_size)
    try:
        import numpy as np
    except Exception:
        return projection

    matrix = np.asarray(projection)
    clip = np.identity(4, dtype=matrix.dtype if hasattr(matrix, "dtype") else float)
    clip[0, 0] = transform.scale_x
    clip[1, 1] = transform.scale_y
    clip[0, 3] = transform.offset_x
    clip[1, 3] = transform.offset_y
    return clip @ matrix


def widget_ndc_to_pixel(
    x: Any,
    y: Any,
    frame_size: Any,
) -> tuple[float, float]:
    """Convert ovui SceneView NDC (+Y up) to widget pixels (+Y down)."""

    frame_w, frame_h = _coerce_size(frame_size, "frame_size")
    ndc_x = float(x)
    ndc_y = float(y)
    if not isfinite(ndc_x) or not isfinite(ndc_y):
        raise ViewportResolutionStateError("widget NDC must be finite")
    return (
        ((ndc_x + 1.0) * 0.5) * frame_w,
        ((1.0 - ndc_y) * 0.5) * frame_h,
    )


def render_ndc_to_widget_ndc(
    x: Any,
    y: Any,
    frame_size: Any,
    render_size: Any,
) -> tuple[float, float]:
    """Map render-space NDC to full-widget NDC through the aspect-fit rect."""

    rect = compute_aspect_fit_display_rect(frame_size, render_size)
    render_x = float(x)
    render_y = float(y)
    if not isfinite(render_x) or not isfinite(render_y):
        raise ViewportResolutionStateError("render NDC must be finite")
    render_px = ((render_x + 1.0) * 0.5) * rect.render_size[0]
    render_py = ((1.0 - render_y) * 0.5) * rect.render_size[1]
    widget_px = rect.x + render_px * rect.scale
    widget_py = rect.y + render_py * rect.scale
    return (
        (widget_px / rect.frame_size[0]) * 2.0 - 1.0,
        1.0 - (widget_py / rect.frame_size[1]) * 2.0,
    )


def map_widget_ndc_to_render_ndc(
    x: Any,
    y: Any,
    frame_size: Any,
    render_size: Any,
) -> RenderNdcMapping | None:
    """Map a widget click to render NDC, or return ``None`` outside the image."""

    rect = compute_aspect_fit_display_rect(frame_size, render_size)
    widget_px, widget_py = widget_ndc_to_pixel(x, y, rect.frame_size)
    if not rect.contains_widget_pixel(widget_px, widget_py):
        return None

    u = (widget_px - rect.x) / rect.width
    v = (widget_py - rect.y) / rect.height
    u = max(0.0, min(1.0, u))
    v = max(0.0, min(1.0, v))
    render_ndc = (u * 2.0 - 1.0, 1.0 - v * 2.0)
    render_pixel = (u * rect.render_size[0], v * rect.render_size[1])
    return RenderNdcMapping(
        widget_ndc=(float(x), float(y)),
        widget_pixel=(widget_px, widget_py),
        render_ndc=render_ndc,
        render_pixel=render_pixel,
        display_rect=rect,
    )


def map_widget_ndc_rect_to_render_ndc_rect(
    x0: Any,
    y0: Any,
    x1: Any,
    y1: Any,
    frame_size: Any,
    render_size: Any,
) -> tuple[float, float, float, float] | None:
    """Clip a widget NDC marquee to the aspect-fit rect and return render NDC."""

    rect = compute_aspect_fit_display_rect(frame_size, render_size)
    px0, py0 = widget_ndc_to_pixel(x0, y0, rect.frame_size)
    px1, py1 = widget_ndc_to_pixel(x1, y1, rect.frame_size)
    left = max(min(px0, px1), rect.x)
    right = min(max(px0, px1), rect.right)
    top = max(min(py0, py1), rect.y)
    bottom = min(max(py0, py1), rect.bottom)
    if left > right + _EPSILON or top > bottom + _EPSILON:
        return None

    u0 = max(0.0, min(1.0, (left - rect.x) / rect.width))
    u1 = max(0.0, min(1.0, (right - rect.x) / rect.width))
    v0 = max(0.0, min(1.0, (top - rect.y) / rect.height))
    v1 = max(0.0, min(1.0, (bottom - rect.y) / rect.height))
    return (
        u0 * 2.0 - 1.0,
        1.0 - v0 * 2.0,
        u1 * 2.0 - 1.0,
        1.0 - v1 * 2.0,
    )
