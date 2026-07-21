# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for RendererAdapter ABC and MockRendererAdapter."""

import numpy as np
import pytest
from ovui_data_adapters.common import GpuFrame, RendererAdapter

from ovui_widgets.common.testing.mock_renderer import (
    FALLBACK_NOTICE_TEXT,
    FALLBACK_NOTICE_TEXT_COLOR,
    MockRendererAdapter,
)

REQUIRED_METHODS = [
    "load_stage",
    "render_frame",
    "set_resolution",
    "pick",
    "cancel_pick",
    "pick_rect",
    "set_selection_highlight",
    "shutdown",
]

SELECTOR_METHODS = [
    "get_active_camera_path",
    "set_active_camera_path",
    "get_active_render_product_path",
    "set_active_render_product_path",
]


class TestRendererAdapterABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            RendererAdapter()  # type: ignore[abstract]

    @pytest.mark.parametrize("method_name", REQUIRED_METHODS)
    def test_method_exists(self, method_name):
        assert hasattr(RendererAdapter, method_name)

    @pytest.mark.parametrize("method_name", SELECTOR_METHODS)
    def test_selector_method_exists(self, method_name):
        assert hasattr(RendererAdapter, method_name)

    @pytest.mark.parametrize("method_name", SELECTOR_METHODS)
    def test_selector_method_is_not_abstract(self, method_name):
        assert method_name not in RendererAdapter.__abstractmethods__

    @pytest.mark.parametrize("method_name", REQUIRED_METHODS)
    def test_method_is_abstract(self, method_name):
        assert method_name in RendererAdapter.__abstractmethods__

    def test_abstract_method_count(self):
        assert len(RendererAdapter.__abstractmethods__) == len(REQUIRED_METHODS)


class TestMockRendererAdapter:
    def test_instantiates(self):
        adapter = MockRendererAdapter()
        assert isinstance(adapter, RendererAdapter)

    def test_render_frame_returns_supported_frame_type(self):
        adapter = MockRendererAdapter()
        frame = adapter.render_frame(320, 240, None, None)
        assert isinstance(frame, (np.ndarray, GpuFrame))
        if isinstance(frame, GpuFrame):
            frame.close()

    def test_render_frame_correct_shape(self):
        adapter = MockRendererAdapter()
        frame = adapter.render_frame(320, 240, None, None)
        if isinstance(frame, GpuFrame):
            try:
                assert (frame.width, frame.height) == (320, 240)
            finally:
                frame.close()
        else:
            assert frame.shape == (240, 320, 4)

    def test_render_frame_correct_dtype(self):
        adapter = MockRendererAdapter()
        frame = adapter.render_frame(320, 240, None, None)
        if isinstance(frame, GpuFrame):
            try:
                assert isinstance(frame.ptr, int)
            finally:
                frame.close()
        else:
            assert frame.dtype == np.uint8

    def test_render_frame_solid_color(self):
        color = (10, 20, 30, 255)
        adapter = MockRendererAdapter(color=color)
        frame = adapter.render_frame(4, 4, None, None)
        assert np.all(frame[:, :, 0] == 10)
        assert np.all(frame[:, :, 1] == 20)
        assert np.all(frame[:, :, 2] == 30)
        assert np.all(frame[:, :, 3] == 255)

    def test_fallback_notice_text_is_exact(self):
        assert FALLBACK_NOTICE_TEXT == "ovrtx is not loaded"

    def test_fallback_notice_is_drawn_into_frame(self):
        adapter = MockRendererAdapter()
        frame = adapter.render_frame(320, 240, None, None)

        text_color = np.array(FALLBACK_NOTICE_TEXT_COLOR[:3], dtype=np.uint8)
        text_pixels = np.all(frame[:80, :, :3] == text_color, axis=2)

        assert int(text_pixels.sum()) > 20

    def test_render_frame_varies_with_size(self):
        adapter = MockRendererAdapter()
        f1 = adapter.render_frame(100, 50, None, None)
        f2 = adapter.render_frame(200, 100, None, None)
        assert f1.shape == (50, 100, 4)
        assert f2.shape == (100, 200, 4)

    def test_load_stage_does_not_raise(self):
        adapter = MockRendererAdapter()
        adapter.load_stage("/path/to/stage.usda")
        adapter.load_stage(None)

    def test_set_resolution_does_not_raise(self):
        adapter = MockRendererAdapter()
        adapter.set_resolution(1920, 1080)
        assert adapter._width == 1920
        assert adapter._height == 1080

    def test_pick_calls_callback_with_none(self):
        adapter = MockRendererAdapter()
        results = []
        adapter.pick(10.0, 20.0, lambda path, pos: results.append((path, pos)), "q1")
        assert len(results) == 1
        assert results[0] == (None, None)

    def test_pick_callback_path_is_none(self):
        adapter = MockRendererAdapter()
        paths = []
        adapter.pick(0, 0, lambda path, pos: paths.append(path), "q2")
        assert paths[0] is None

    def test_pick_rect_calls_callback_with_empty_list(self):
        adapter = MockRendererAdapter()
        results = []
        adapter.pick_rect(0, 0, 100, 100, lambda p: results.append(p))
        assert len(results) == 1
        assert results[0] == []

    def test_cancel_pick_does_not_raise(self):
        adapter = MockRendererAdapter()
        adapter.cancel_pick("nonexistent-query")

    def test_set_selection_highlight_does_not_raise(self):
        adapter = MockRendererAdapter()
        adapter.set_selection_highlight(["/World/Cube", "/World/Sphere"])
        adapter.set_selection_highlight([])

    def test_shutdown_is_safe(self):
        adapter = MockRendererAdapter()
        adapter.shutdown()
        assert adapter._shutdown_called is True

    def test_shutdown_twice_is_safe(self):
        adapter = MockRendererAdapter()
        adapter.shutdown()
        adapter.shutdown()

    def test_active_selector_defaults_are_noop(self):
        adapter = MockRendererAdapter()
        assert adapter.get_active_camera_path() is None
        assert adapter.get_active_render_product_path() is None
        assert adapter.set_active_camera_path("/World/Camera") is False
        assert adapter.set_active_camera_path(None) is False
        assert adapter.set_active_render_product_path("/Render/Viewport") is False
        assert adapter.set_active_render_product_path(None) is False
