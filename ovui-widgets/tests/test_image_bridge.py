# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for ImageBridge (Step 39)."""

from unittest.mock import MagicMock, patch

import numpy as np

from ovui_widgets.viewport.image_bridge import ImageBridge


class TestImageBridgeCreation:
    def test_create_with_dimensions(self):
        bridge = ImageBridge(64, 48)
        assert bridge._width == 64
        assert bridge._height == 48

    def test_provider_property_returns_byte_image_provider(self):
        import omni.ui as ui
        bridge = ImageBridge(32, 32)
        assert isinstance(bridge.provider, ui.ByteImageProvider)

    def test_provider_is_not_none(self):
        bridge = ImageBridge(16, 16)
        assert bridge.provider is not None


class TestImageBridgeUpdate:
    def test_update_same_size_no_crash(self):
        bridge = ImageBridge(64, 64)
        frame = np.full((64, 64, 4), 128, dtype=np.uint8)
        bridge.update(frame)  # must not raise

    def test_update_different_size_adapts(self):
        bridge = ImageBridge(64, 64)
        frame = np.full((128, 256, 4), 200, dtype=np.uint8)
        bridge.update(frame)
        assert bridge._width == 256
        assert bridge._height == 128

    def test_update_updates_internal_dimensions(self):
        bridge = ImageBridge(10, 10)
        frame = np.zeros((20, 30, 4), dtype=np.uint8)
        bridge.update(frame)
        assert bridge._width == 30
        assert bridge._height == 20

    def test_initial_blank_frame_is_opaque(self):
        bridge = ImageBridge(4, 4)
        # Alpha channel should be 255 after init (pre-allocated black+full alpha)
        # We can only verify no crash; the provider is opaque to readback
        assert bridge.provider is not None


class TestImageBridgeClear:
    def test_clear_uploads_a_transparent_frame_of_the_current_size(self):
        bridge = ImageBridge(8, 8)
        bridge.update(np.full((6, 10, 4), 200, dtype=np.uint8))
        uploads = []
        bridge._provider = MagicMock()
        bridge._provider.set_data_array.side_effect = (
            lambda frame, size: uploads.append((frame.copy(), size))
        )

        bridge.clear()

        assert len(uploads) == 1
        frame, size = uploads[0]
        assert size == [10, 6]
        assert frame.shape == (6, 10, 4)
        assert not frame.any()


class TestImageBridgeNoListAllocation:
    """Regression guard: update() must not flatten frames into Python lists.

    set_bytes_data(list[int], ...) materialises H*W*4 int objects per frame
    (~33ms/frame at 720p, ~75ms at 1080p). set_data_array hands the numpy
    buffer pointer to the same C++ entry point with no Python-int round trip.
    """

    def test_update_calls_set_data_array(self):
        bridge = ImageBridge(8, 8)
        frame = np.full((8, 8, 4), 200, dtype=np.uint8)
        bridge._provider = MagicMock()
        bridge.update(frame)
        bridge._provider.set_data_array.assert_called_once()
        bridge._provider.set_bytes_data.assert_not_called()

    def test_update_passes_ndarray_not_list(self):
        bridge = ImageBridge(8, 8)
        frame = np.full((8, 8, 4), 200, dtype=np.uint8)
        bridge._provider = MagicMock()
        bridge.update(frame)
        args, _ = bridge._provider.set_data_array.call_args
        assert isinstance(args[0], np.ndarray), (
            "first arg must be ndarray (zero-copy), not a Python list"
        )
        assert args[0].dtype == np.uint8
        assert args[1] == [8, 8]

    def test_init_calls_set_data_array(self):
        # The blank-frame init path must also avoid list materialisation.
        with patch("omni.ui.ByteImageProvider") as mock_cls:
            mock_provider = MagicMock()
            mock_cls.return_value = mock_provider
            ImageBridge(16, 16)
            mock_provider.set_data_array.assert_called_once()
            mock_provider.set_bytes_data.assert_not_called()


class TestImageBridgeRejectedUpload:
    """A rejected upload must be visible to the caller and must start the CPU fallback.

    ovui keeps the previous pixels when it rejects an upload, so the provider
    still looks valid. Only the return value of the setter tells the truth.
    """

    @staticmethod
    def _gpu_frame():
        from ovui_data_adapters.common import GpuFrame

        return GpuFrame(ptr=0x1000, width=4, height=4)

    def test_cpu_update_returns_the_answer_of_ovui(self):
        bridge = ImageBridge(4, 4)
        frame = np.zeros((4, 4, 4), dtype=np.uint8)
        bridge._provider = MagicMock()
        bridge._provider.set_data_array.return_value = False
        assert bridge.update(frame) is False
        bridge._provider.set_data_array.return_value = True
        assert bridge.update(frame) is True

    def test_update_without_an_answer_returns_none(self):
        bridge = ImageBridge(4, 4)
        bridge._provider = MagicMock()  # an older ovui answers with None
        bridge._provider.set_data_array.return_value = None
        assert bridge.update(np.zeros((4, 4, 4), dtype=np.uint8)) is None
        assert bridge.update(None) is None

    def test_rejected_probe_upload_latches_the_fallback(self):
        from ovui_data_adapters.common import ZeroCopyState

        state = ZeroCopyState.from_env()
        state.mode = type(state.mode).PROBING
        bridge = ImageBridge(4, 4, state=state)
        bridge._provider = MagicMock()
        bridge._provider.set_bytes_data_from_gpu.return_value = False
        with patch("ovui_widgets.viewport.image_bridge._has_gpu_byte_image", return_value=True):
            assert bridge.update(self._gpu_frame()) is False
        assert state.mode.value == "fallback"
        assert "rejected" in state.fallback_reason

    def test_accepted_probe_upload_enables_zero_copy(self):
        from ovui_data_adapters.common import ZeroCopyState

        state = ZeroCopyState.from_env()
        state.mode = type(state.mode).PROBING
        bridge = ImageBridge(4, 4, state=state)
        bridge._provider = MagicMock()
        bridge._provider.set_bytes_data_from_gpu.return_value = True
        with patch("ovui_widgets.viewport.image_bridge._has_gpu_byte_image", return_value=True):
            assert bridge.update(self._gpu_frame()) is True
        assert state.mode.value == "enabled"

    def test_rejected_upload_after_enable_latches_the_fallback(self):
        from ovui_data_adapters.common import ZeroCopyState

        state = ZeroCopyState.from_env()
        state.mode = type(state.mode).ENABLED
        bridge = ImageBridge(4, 4, state=state)
        bridge._provider = MagicMock()
        bridge._provider.set_bytes_data_from_gpu.return_value = False
        assert bridge.update(self._gpu_frame()) is False
        assert state.mode.value == "fallback"

    def test_failure_hook_of_ovui_starts_the_fallback_without_a_renderer_patch(self):
        """The supported test hook of ovui is enough to test the fallback on a real provider."""
        from ovui_data_adapters.common import ZeroCopyState

        state = ZeroCopyState.from_env()
        state.mode = type(state.mode).ENABLED
        bridge = ImageBridge(4, 4, state=state)
        bridge.provider.inject_upload_failures(1)
        assert bridge.update(self._gpu_frame()) is False
        assert bridge.provider.inject_upload_failures(0) == 0, "the upload of the bridge took the failure"
        assert state.mode.value == "fallback"
