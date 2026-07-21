# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Safety coverage for renderers that decline live transform previews."""

from __future__ import annotations

import numpy as np

from ovui_data_adapters.services.testing.mock_renderer import MockRendererAdapter


_MATRIX = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [4.0, 0.0, 0.0, 1.0],
]


def test_mock_renderer_declines_live_transform_preview() -> None:
    assert "supports_live_local_transform" not in MockRendererAdapter.__dict__
    assert "set_live_local_transform" not in MockRendererAdapter.__dict__
    assert "clear_live_local_transforms" not in MockRendererAdapter.__dict__

    renderer = MockRendererAdapter()

    assert renderer.supports_live_local_transform is False
    assert renderer.set_live_local_transform("/World/Cube", _MATRIX) is False
    assert renderer.clear_live_local_transforms(["/World/Cube"]) is None


def test_declined_live_transform_does_not_change_render_selection_or_pick() -> None:
    renderer = MockRendererAdapter(color=(10, 20, 30, 255))

    renderer.load_stage(None)
    renderer.set_resolution(320, 240)
    renderer.set_selection_highlight(["/World/Cube"])
    selected_before = list(renderer._selected_paths)
    frame_before = renderer.render_frame(4, 4, None, None).copy()
    render_count_before = renderer.render_call_count

    assert renderer.set_live_local_transform("/World/Cube", _MATRIX) is False
    assert renderer.clear_live_local_transforms(["/World/Cube"]) is None
    assert renderer.set_live_local_transform("/World/Sphere", _MATRIX) is False

    assert renderer._stage is None
    assert renderer._stage_paths == []
    assert renderer._selected_paths == selected_before
    assert renderer._shutdown_called is False
    assert renderer.render_call_count == render_count_before

    frame_after = renderer.render_frame(4, 4, None, None)
    assert renderer.render_call_count == render_count_before + 1
    assert np.array_equal(frame_after, frame_before)

    picked: list[tuple[str | None, tuple[float, float, float] | None]] = []
    renderer.pick(0.0, 0.0, lambda path, pos: picked.append((path, pos)), "declined-pick")
    assert picked == [(None, None)]

    rect_hits: list[list[str]] = []
    renderer.pick_rect(-1.0, -1.0, 1.0, 1.0, rect_hits.append)
    assert rect_hits == [[]]


def test_declined_live_transform_calls_are_safe_around_shutdown() -> None:
    renderer = MockRendererAdapter()

    assert renderer.set_live_local_transform("/World/Cube", _MATRIX) is False
    renderer.shutdown()
    assert renderer._shutdown_called is True
    assert renderer.clear_live_local_transforms(["/World/Cube"]) is None
    assert renderer.set_live_local_transform("/World/Cube", _MATRIX) is False
    renderer.shutdown()
    assert renderer._shutdown_called is True
