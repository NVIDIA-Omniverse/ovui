# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Settled pictures of render-settings states, for one unchanged scene.

Undo and Redo of Render Settings > Reset Settings move between the same
render-settings states. ovrtx keeps memory for each frame that it renders and
for each renderer restart, so rendering the same states again and again grows
the app without end. The renderer adapter keeps the settled picture of each
state here and shows it again when the settings return to that state, with no
frame rendered.

A picture is valid only for the scene key it was stored with: the camera, the
size, the render product, the renderer, the stage and a generation counter
that the adapter increases at every other change. A new scene key forgets all
pictures. A picture is "settled" when the renderer finished it, else partial
(the settings changed before); a partial picture never replaces a settled one.
A settled picture keeps the settle frames that it was finished with: it counts
as settled only for a target of at most that many frames.
The memory is bounded: at most ``limit`` pictures and ``max_bytes`` bytes; the
least recently used picture goes first.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Hashable, Optional

import numpy as np


class SettledPictures:
    """A bounded memory of settled pictures keyed by render-settings state."""

    def __init__(self, limit: int, max_bytes: int) -> None:
        self._limit = max(1, int(limit))
        self._max_bytes = max(0, int(max_bytes))
        self._scene: Any = None
        self._pictures: "OrderedDict[Hashable, np.ndarray]" = OrderedDict()
        # Settings of the settled pictures, and the settle frames of each.
        self._settled: dict = {}

    def __len__(self) -> int:
        return len(self._pictures)

    @property
    def nbytes(self) -> int:
        return sum(int(picture.nbytes) for picture in self._pictures.values())

    def clear(self) -> None:
        self._scene = None
        self._pictures.clear()
        self._settled.clear()

    def keep_scene(self, scene: Hashable) -> None:
        """Forget the pictures of another scene: they can never be shown again."""

        if self._pictures and scene != self._scene:
            self.clear()

    def get(self, scene: Hashable, settings: Hashable) -> Optional[np.ndarray]:
        """The picture stored for ``settings`` in ``scene``, or ``None``."""

        if scene != self._scene:
            return None
        picture = self._pictures.get(settings)
        if picture is not None:
            self._pictures.move_to_end(settings)
        return picture

    def settled(self, scene: Hashable, settings: Hashable, frames: int = 0) -> bool:
        """Whether the stored picture for ``settings`` in ``scene`` was finished with at least ``frames`` settle frames."""

        return (
            scene == self._scene
            and settings in self._pictures
            and self._settled.get(settings, -1) >= int(frames)
        )

    def put(
        self,
        scene: Hashable,
        settings: Hashable,
        picture: np.ndarray,
        *,
        settled: bool = True,
        frames: int = 0,
    ) -> bool:
        """Store a copy of ``picture``; False when it is not kept.

        ``frames``: the settle frames that a settled picture was finished
        with. It is not kept when it is too large, or when it is partial and
        the stored picture of ``settings`` is settled.
        """

        if scene != self._scene:
            self.clear()
            self._scene = scene
        if not settled and settings in self._settled and settings in self._pictures:
            return False
        if int(picture.nbytes) > self._max_bytes:
            self._pictures.pop(settings, None)
            self._settled.pop(settings, None)
            return False
        self._pictures[settings] = np.array(picture, copy=True)
        self._pictures.move_to_end(settings)
        if settled:
            self._settled[settings] = int(frames)
        else:
            self._settled.pop(settings, None)
        while len(self._pictures) > self._limit or self.nbytes > self._max_bytes:
            evicted, _picture = self._pictures.popitem(last=False)
            self._settled.pop(evicted, None)
        return True
