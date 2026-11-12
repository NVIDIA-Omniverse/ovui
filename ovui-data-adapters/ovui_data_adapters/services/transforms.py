# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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
        self._initial_state = (
            adapter.capture_local_transform_state(path)
            if adapter.get_local_transform(path) == self._initial
            else None
        )
        self._final_state = None
        # The note of the adapter for the last write of ``final``: ``None``,
        # or the cause when the adapter stored the transform in another form.
        self.write_note: str | None = None

    def do(self) -> None:
        if self._final_state is not None and self._adapter.restore_local_transform_state(
            self._path, self._final_state
        ):
            return
        self.write_note = self._adapter.set_local_transform(self._path, self._final)
        if self._initial_state is not None:
            self._final_state = self._adapter.capture_local_transform_state(self._path)

    def undo(self) -> None:
        if self._initial_state is not None and self._adapter.restore_local_transform_state(
            self._path, self._initial_state
        ):
            return
        self._adapter.set_local_transform(self._path, self._initial)


__all__ = ["BatchTransformCommand"]
