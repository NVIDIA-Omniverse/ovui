# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""SnapSystem — pluggable snap providers for transform operations.

See stage browser behavior "Snap": GridSnapProvider rounds to grid increments,
SurfaceSnapProvider is a stub. SnapSystem chains providers in insertion order.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import List, Optional


class SnapProvider(ABC):
    """Abstract snap provider."""

    @abstractmethod
    def snap(
        self,
        position: List[float],
        constraint_axis: Optional[str],
    ) -> Optional[List[float]]:
        """Return snapped position, or None to defer to the next provider."""


class GridSnapProvider(SnapProvider):
    """Snaps each coordinate to the nearest grid increment."""

    def __init__(self, grid_size: float) -> None:
        self._grid_size = 1.0
        self.set_grid_size(grid_size)

    @property
    def grid_size(self) -> float:
        """Current positive, finite grid increment."""

        return self._grid_size

    def set_grid_size(self, grid_size: float) -> None:
        """Replace the grid increment used by subsequent snap calls.

        Settings can also be populated from JSON or another integration,
        bypassing the Settings dialog's ``FloatDrag`` bounds.  Reject invalid
        values here so a zero increment cannot turn a viewport drag into a
        division-by-zero failure.
        """

        value = float(grid_size)
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("grid_size must be a positive finite value")
        self._grid_size = value

    def snap(
        self,
        position: List[float],
        constraint_axis: Optional[str],
    ) -> List[float]:
        g = self._grid_size
        return [round(v / g) * g for v in position]


class SurfaceSnapProvider(SnapProvider):
    """Stub surface-snap provider — always defers to the next provider."""

    def snap(
        self,
        position: List[float],
        constraint_axis: Optional[str],
    ) -> None:
        return None


class SnapSystem:
    """Chains snap providers; first non-None result wins."""

    def __init__(self) -> None:
        self._enabled = False
        self._providers: List[SnapProvider] = []

    def enable(self, enabled: bool) -> None:
        self._enabled = enabled

    def add_provider(self, provider: SnapProvider) -> None:
        self._providers.append(provider)

    def snap(
        self,
        position: List[float],
        constraint_axis: Optional[str] = None,
    ) -> List[float]:
        if not self._enabled:
            return list(position)
        for provider in self._providers:
            result = provider.snap(position, constraint_axis)
            if result is not None:
                return result
        return list(position)
