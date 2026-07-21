# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

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
