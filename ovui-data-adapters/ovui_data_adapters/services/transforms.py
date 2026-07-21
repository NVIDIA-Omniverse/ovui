# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Frontend-neutral transform operation commands.

This service intentionally contains only document/data transform command
behavior. Manipulator geometry, snap policy, drag gesture state, viewport
handles, and per-frame interaction code stay in ``ovui_widgets``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ovui_data_adapters.services.undo import Command

if TYPE_CHECKING:
    from ovui_data_adapters.common import TransformAdapter


class BatchTransformCommand(Command):
    """Single undo entry for a completed transform operation on one prim."""

    def __init__(
        self,
        adapter: "TransformAdapter",
        path: str,
        initial: list[list[float]],
        final: list[list[float]],
    ) -> None:
        self._adapter = adapter
        self._path = path
        self._initial = [row[:] for row in initial]
        self._final = [row[:] for row in final]

    def do(self) -> None:
        self._adapter.set_local_transform(self._path, self._final)

    def undo(self) -> None:
        self._adapter.set_local_transform(self._path, self._initial)


__all__ = ["BatchTransformCommand"]
