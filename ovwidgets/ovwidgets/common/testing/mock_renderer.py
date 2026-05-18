# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""In-memory MockRendererAdapter for testing without GPU or ovrtx."""

from typing import Any, Callable, List, Optional, Tuple

import numpy as np
from ovui_data_adapters.common import RendererAdapter

# Scene objects: (norm_cx, norm_cy, norm_radius, color_rgba, path_suffix)
# norm_cx in [-0.5, 0.5], norm_cy in [0, 1] from top, norm_radius relative to min(w,h)
_SCENE_SHAPES = [
    (-0.22, 0.50, 0.090, (80,  140, 220, 255), "Cube"),
    ( 0.20, 0.46, 0.065, (220, 140,  80, 255), "Sphere"),
    ( 0.40, 0.30, 0.038, (255, 245, 160, 255), "DomeLight"),
    (-0.38, 0.36, 0.028, (160, 200, 255, 255), "Camera"),
]


class MockRendererAdapter(RendererAdapter):
    """Returns rendered frames; pick stubs call callbacks immediately.

    For frames smaller than 16×16 (unit tests) the original solid-color fill is
    used so existing test assertions on pixel values still pass.
    """

    def __init__(self, color: Tuple[int, int, int, int] = (128, 64, 32, 255)):
        self._color = color
        self._width = 1280
        self._height = 720
        self._shutdown_called = False
        self.render_call_count = 0
        self._selected_paths: List[str] = []
        self._stage: Any = None
        self._stage_paths: list[str] = []

    def load_stage(self, stage: Any) -> None:
        self._stage = stage
        self._stage_paths = self._collect_stage_paths(stage)

    def _collect_stage_paths(self, stage: Any) -> list[str]:
        if stage is None:
            return []
        resolved_stage = stage
        if isinstance(stage, str):
            try:
                from pxr import Usd
                resolved_stage = Usd.Stage.Open(stage)
            except Exception:
                return []
            if resolved_stage is None:
                return []
            self._stage = resolved_stage
        traverse = getattr(resolved_stage, "TraverseAll", None)
        if not callable(traverse):
            traverse = getattr(resolved_stage, "Traverse", None)
        if not callable(traverse):
            return []
        paths: list[str] = []
        try:
            for prim in traverse():
                get_path = getattr(prim, "GetPath", None)
                if callable(get_path):
                    paths.append(str(get_path()))
        except Exception:
            return []
        return paths

    def render_frame(self, width: int, height: int, view_matrix: Any, proj_matrix: Any) -> np.ndarray:
        self.render_call_count += 1
        frame = np.zeros((height, width, 4), dtype=np.uint8)

        # Small frames (unit tests) → solid color for backward-compatible assertions
        if width < 16 or height < 16:
            frame[:, :] = self._color
            return frame

        # ── Sky / background gradient ─────────────────────────────────────────
        # Anchored to ``cl.background_primary`` (``#17181C``) so the mock
        # viewport blends with the dock panels instead of reading as a
        # bright light-theme island.
        y_norm = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, np.newaxis]
        frame[:, :, 0] = (23 + 6 * y_norm).astype(np.uint8)
        frame[:, :, 1] = (24 + 6 * y_norm).astype(np.uint8)
        frame[:, :, 2] = (28 + 8 * y_norm).astype(np.uint8)
        frame[:, :, 3] = 255

        # ── Ground grid ───────────────────────────────────────────────────────
        cx = width // 2
        horizon = int(height * 0.65)
        grid_c = np.array([44, 44, 48, 255], dtype=np.uint8)

        # Horizontal lines below horizon
        grid_rows = 7
        for i in range(1, grid_rows + 1):
            gy = horizon + i * (height - horizon) // (grid_rows + 1)
            if gy < height:
                frame[gy] = grid_c

        # Vertical lines below horizon
        for i in range(-6, 7):
            gx = cx + i * width // 12
            if 0 <= gx < width:
                frame[horizon:, gx] = grid_c

        # Horizon line
        if 0 < horizon < height:
            frame[horizon] = (55, 55, 60, 255)

        # ── Prim shapes ───────────────────────────────────────────────────────
        y_idx, x_idx = np.ogrid[:height, :width]

        for nx, ny, nr, color, suffix in _SCENE_SHAPES:
            scx = int((0.5 + nx) * width)
            scy = int(ny * height)
            sr = max(4, int(nr * min(width, height)))

            selected = any(p.endswith(f"/{suffix}") for p in self._selected_paths)

            dist_sq = (x_idx - scx) ** 2 + (y_idx - scy) ** 2

            if selected:
                sel_r = sr + max(4, sr // 4)
                ring = (dist_sq <= sel_r ** 2) & (dist_sq > (sel_r - 3) ** 2)
                frame[ring] = (255, 155, 40, 255)

            # Main circle
            mask = dist_sq <= sr ** 2
            frame[mask] = color

            # Bottom-half shadow for slight depth
            shadow = mask & (y_idx > scy)
            c = np.array(color, dtype=np.float32)
            c[:3] *= 0.62
            frame[shadow] = c.astype(np.uint8)

        return frame

    def set_resolution(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    def pick(
        self,
        x: float,
        y: float,
        callback: Callable[[Optional[str], Optional[Tuple[float, float, float]]], None],
        query_name: str,
    ) -> None:
        hit = self._pick_shape_path(float(x), float(y))
        callback(hit, (0.0, 0.0, 0.0) if hit is not None else None)

    def cancel_pick(self, query_name: str) -> None:
        pass

    def pick_rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        callback: Callable[[List[str]], None],
    ) -> None:
        callback(self._pick_rect_shape_paths(float(x0), float(y0), float(x1), float(y1)))

    def set_selection_highlight(self, paths: List[str]) -> None:
        self._selected_paths = list(paths)

    def shutdown(self) -> None:
        self._shutdown_called = True

    def _path_for_suffix(self, suffix: str) -> Optional[str]:
        needle = f"/{suffix}"
        for path in self._stage_paths:
            if path.endswith(needle):
                return path
        return None

    def _shape_bounds_px(
        self,
        width: int,
        height: int,
        nx: float,
        ny: float,
        nr: float,
    ) -> tuple[float, float, float]:
        cx = (0.5 + nx) * float(width)
        cy = ny * float(height)
        radius = max(4.0, nr * float(min(width, height)))
        return cx, cy, radius

    def _ndc_to_px(self, x: float, y: float) -> tuple[float, float]:
        return (
            (x + 1.0) * 0.5 * float(self._width),
            (1.0 - y) * 0.5 * float(self._height),
        )

    def _pick_shape_path(self, x: float, y: float) -> Optional[str]:
        if not self._stage_paths:
            return None
        px, py = self._ndc_to_px(x, y)
        best: tuple[float, str] | None = None
        for nx, ny, nr, _color, suffix in _SCENE_SHAPES:
            path = self._path_for_suffix(suffix)
            if path is None:
                continue
            cx, cy, radius = self._shape_bounds_px(self._width, self._height, nx, ny, nr)
            dist_sq = (px - cx) ** 2 + (py - cy) ** 2
            if dist_sq <= radius ** 2 and (best is None or dist_sq < best[0]):
                best = (dist_sq, path)
        return best[1] if best is not None else None

    def _pick_rect_shape_paths(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> list[str]:
        if not self._stage_paths:
            return []
        ax, ay = self._ndc_to_px(x0, y0)
        bx, by = self._ndc_to_px(x1, y1)
        left, right = sorted((ax, bx))
        top, bottom = sorted((ay, by))
        hits: list[str] = []
        for nx, ny, nr, _color, suffix in _SCENE_SHAPES:
            path = self._path_for_suffix(suffix)
            if path is None:
                continue
            cx, cy, radius = self._shape_bounds_px(self._width, self._height, nx, ny, nr)
            if (
                cx + radius >= left
                and cx - radius <= right
                and cy + radius >= top
                and cy - radius <= bottom
            ):
                hits.append(path)
        return hits
