# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Depth-one retained-LdrColor overlap shared by the renderer adapters.

ovrtx's ``Renderer.step()`` waits only for operation acceptance; the actual
GPU frame completes later, and mapping the LdrColor render var immediately
after ``step()`` busy-waits ~one GPU frame (~11 ms at 1370x737 on the
reference host, ~57 FPS end to end). This module implements the measured
fix: retain the just-submitted step result for exactly one frame and present
the PREVIOUS frame's image instead, so the GPU renders frame N while the
CPU presents frame N-1 (~82 FPS measured; Kit's own async-rendering model
uses the same producer/consumer overlap with up to 3+1 frames in flight).

Only the normal CPU LdrColor image consumption is delayed. Pick results,
point-cloud frames, and render-var outputs are dispatched from the CURRENT
step result before the image is consumed, so request/response timing is
unchanged. The retained unit is the whole step-result container: ovrtx
output handles become invalid once their container is released, so nothing
narrower can be retained (measured: "Invalid output handle for map").

Ownership rule: the retained container must be released BEFORE any native
mutation (layer add/remove, root open, renderer reset, product switch,
stage attach/detach, teardown). Each adapter's ``_release_retained_output``
performs the release and every mutation boundary calls it after its cheap
early-return guards, immediately before the native call. The static
ownership audit (``tests/openusd/test_renderer_ownership_audit.py``) rejects
any native-renderer access outside the audited exempt/boundary sets,
including attribute writes, handle escapes, aliases, and dynamic access.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

import numpy as np

__all__ = [
    "CameraSnapshot",
    "LdrOverlapState",
    "camera_state_differs",
]


@dataclass(frozen=True)
class CameraSnapshot:
    """Complete presentation-camera state travelling with a retained frame.

    ``view``/``projection`` are defensive 4x4 float copies of the matrices
    actually submitted to ovrtx for the frame; ``size`` is the requested
    extract size. All three participate in monotonicity decisions: a pick
    substitution that changes ANY component (orbit/pan/dolly, FOV/aspect,
    resolution) marks the frame presentation-skipped.
    """

    view: np.ndarray
    projection: np.ndarray
    size: Tuple[int, int]

    @classmethod
    def capture(cls, view: Any, projection: Any, size: Tuple[int, int]) -> "CameraSnapshot":
        return cls(
            view=np.array(np.asarray(view, dtype=float).reshape(4, 4), copy=True),
            projection=np.array(np.asarray(projection, dtype=float).reshape(4, 4), copy=True),
            size=(int(size[0]), int(size[1])),
        )


def camera_state_differs(a: "CameraSnapshot", view: Any, projection: Any,
                         size: Tuple[int, int]) -> bool:
    """True when the complete camera state (view, projection, size) differs.

    View-only comparison is NOT sufficient: production FOV animation changes
    only the projection and caused presented-frame rewinds until the full
    state was compared (measured: 6/6 rewinds view-only, 0 with full state).
    """
    if a.size != (int(size[0]), int(size[1])):
        return True
    if float(np.max(np.abs(a.view - np.asarray(view, dtype=float).reshape(4, 4)))) > 1e-12:
        return True
    return float(np.max(np.abs(
        a.projection - np.asarray(projection, dtype=float).reshape(4, 4)))) > 1e-12


class LdrOverlapState:
    """Depth-one retained-output state machine.

    States are expressed by ``(retained_products, retained_consumed)``:

    * empty            -> :meth:`consume` extracts synchronously (correct
                          image, no black flash) and retains the fresh
                          container marked *consumed* (an ovrtx render var
                          must not be mapped twice);
    * retained+consumed-> re-present the cached image once (pipeline fill /
                          pick-skip duplicate) and retain fresh unconsumed;
    * retained         -> steady overlap: extract the retained container,
                          retain the fresh one.

    Presented images can therefore only ever be (a) the frame just rendered
    (sync fill) or (b) a strictly newer frame than the previous presentation,
    or (c) an exact duplicate of the currently visible frame — the visual
    stream cannot rewind.

    Any exception raised while consuming invalidates the retained container,
    the cached image, and the presented snapshot exactly once before it
    propagates; the next frame re-enters through the synchronous fill.
    """

    def __init__(self) -> None:
        self.retained_products: Any = None
        self.retained_key: Any = None
        self.retained_consumed: bool = False
        self.retained_snapshot: Optional[CameraSnapshot] = None
        self.last_image: Optional[np.ndarray] = None
        self.presented_snapshot: Optional[CameraSnapshot] = None

    # -- ownership -----------------------------------------------------

    def release(self, *, clear_presentation: bool = True) -> bool:
        """Drop the retained container; return whether one was held.

        With ``clear_presentation`` (the default, used at every native
        mutation boundary and on consumption failure) the cached image and
        presented snapshot are invalidated too, so nothing rendered before
        the mutation can be re-presented after it.
        """
        had = self.retained_products is not None
        self.retained_products = None
        self.retained_key = None
        self.retained_consumed = False
        self.retained_snapshot = None
        if clear_presentation:
            self.last_image = None
            self.presented_snapshot = None
        return had

    # -- per-frame consumption ------------------------------------------

    def consume(
        self,
        products: Any,
        key: Any,
        snapshot: CameraSnapshot,
        extract: Callable[[Any], Any],
        expected_hw: Tuple[int, int],
        pick_skip: bool,
    ) -> Any:
        """Present one frame; retain ``products`` for the next call.

        ``extract`` maps a step-result container to an image; it is invoked
        on the RETAINED container in steady state and on ``products`` for
        the synchronous fill. ``expected_hw`` is ``(height, width)`` for the
        duplicate-path size check. ``pick_skip`` marks ``products`` as
        rendered with an already-presented camera (moving-camera pick): its
        image must never be shown, so it is retained pre-consumed.
        """
        try:
            if (self.retained_products is not None
                    and self.retained_key == key
                    and not self.retained_consumed):
                image = extract(self.retained_products)
                presented = self.retained_snapshot
                self._retain(products, key, snapshot, consumed=pick_skip)
                if isinstance(image, np.ndarray):
                    self.last_image = image
                self.presented_snapshot = presented
                return image

            if (self.retained_products is not None
                    and self.retained_key == key
                    and self.retained_consumed):
                image = self.last_image
                if (isinstance(image, np.ndarray)
                        and image.shape[0] == expected_hw[0]
                        and image.shape[1] == expected_hw[1]):
                    # presented_snapshot intentionally unchanged: it still
                    # describes the cached image being re-presented.
                    self._retain(products, key, snapshot, consumed=pick_skip)
                    return image.copy()

            # empty, key change, or unusable cache: synchronous fill.
            self.retained_products = None
            self.retained_key = None
            self.retained_snapshot = None
            image = extract(products)
            self._retain(products, key, snapshot, consumed=True)
            if isinstance(image, np.ndarray):
                self.last_image = image
            self.presented_snapshot = snapshot
            return image
        except Exception:
            # exactly-once invalidation: nothing stale may survive a failed
            # consumption, and the exception must still propagate.
            self.release(clear_presentation=True)
            raise

    def _retain(self, products: Any, key: Any, snapshot: CameraSnapshot,
                *, consumed: bool) -> None:
        self.retained_products = products
        self.retained_key = key
        self.retained_consumed = consumed
        self.retained_snapshot = snapshot
