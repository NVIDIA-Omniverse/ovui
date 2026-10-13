# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Data-only ``BoundCameraPose`` dataclass.

Part of ``ovui-data-adapters-common``; this module is stdlib-only at runtime.

Carries the world-space pose for a stage's authored ``boundCamera``.
The USD/pxr parser that produces this value (``read_bound_camera``)
lives in ``ovui_widgets.viewport.usd_camera`` because it depends on
``pxr``; only the result type lives here so that future
``ovui_data_adapters.openusd`` consumers can return it without
forcing a widget back-edge.
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class BoundCameraPose:
    """World-space pose for the stage's ``boundCamera``."""

    eye: Tuple[float, float, float]
    target: Tuple[float, float, float]
    up_axis: str  # "Y" or "Z"
    fov_degrees: float
    prim_path: str
    projection: str = "perspective"
    orthographic_height: float | None = None  # full aperture in stage units
