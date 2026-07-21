# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Mock TransformAdapter for testing (no USD required).

Stores transforms in memory as path → 4×4 list-of-lists.
"""

from __future__ import annotations

from typing import List, Set

from ovui_data_adapters.common import TransformAdapter

_IDENTITY: List[List[float]] = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


class MockTransformAdapter(TransformAdapter):
    """In-memory TransformAdapter for unit tests."""

    def __init__(self, blocked: Set[str] | None = None) -> None:
        self._transforms: dict[str, List[List[float]]] = {}
        self._blocked: Set[str] = blocked or set()

    def get_local_transform(self, path: str) -> List[List[float]]:
        mat = self._transforms.get(path)
        if mat is None:
            return [row[:] for row in _IDENTITY]
        return [row[:] for row in mat]

    def get_world_transform(self, path: str) -> List[List[float]]:
        return self.get_local_transform(path)

    def set_local_transform(self, path: str, matrix: List[List[float]]) -> None:
        self._transforms[path] = [row[:] for row in matrix]

    def can_transform(self, path: str) -> bool:
        return path not in self._blocked
