# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Small state machine for viewport camera navigation settle detection."""

from __future__ import annotations

from typing import Any, Optional


class CameraNavigationState:
    """Track active camera navigation from deterministic signature samples."""

    def __init__(self, stable_frame_threshold: int = 2) -> None:
        self._stable_frame_threshold = max(1, int(stable_frame_threshold))
        self._last_signature: Optional[tuple[Any, ...]] = None
        self._settled_signature: Optional[tuple[Any, ...]] = None
        self._dirty_signature: Optional[tuple[Any, ...]] = None
        self._stable_frames = 0
        self._active = False
        self._dirty = False

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @property
    def stable_frames(self) -> int:
        return self._stable_frames

    @property
    def last_signature(self) -> Optional[tuple[Any, ...]]:
        return self._last_signature

    @property
    def settled_signature(self) -> Optional[tuple[Any, ...]]:
        return self._settled_signature

    @property
    def dirty_signature(self) -> Optional[tuple[Any, ...]]:
        return self._dirty_signature

    def reset(self, signature: Optional[tuple[Any, ...]] = None) -> None:
        self._last_signature = signature
        self._settled_signature = signature
        self._dirty_signature = None
        self._stable_frames = 0
        self._active = False
        self._dirty = False

    def clear_dirty(self) -> None:
        self._dirty = False
        self._dirty_signature = None
        self._settled_signature = self._last_signature

    def observe(self, signature: Optional[tuple[Any, ...]]) -> bool:
        """Observe one render-frame camera signature.

        Returns True only when this sample differs from the previous sample.
        """
        if signature is None:
            self.reset(None)
            return False
        if self._last_signature is None:
            self.reset(signature)
            return False
        if signature != self._last_signature:
            self._last_signature = signature
            self._dirty_signature = signature
            self._stable_frames = 0
            self._active = True
            self._dirty = True
            return True
        if self._active:
            self._stable_frames += 1
            if self._stable_frames >= self._stable_frame_threshold:
                self._active = False
                self._settled_signature = signature
                self._stable_frames = 0
        return False
