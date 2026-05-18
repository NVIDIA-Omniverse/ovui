# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the tier-2 zero-copy state machine and ImageBridge GPU dispatch."""

import os
from unittest.mock import MagicMock

import pytest
from ovui_data_adapters.common import GpuFrame, ZeroCopyState, _Mode

from ovwidgets.viewport.image_bridge import ImageBridge


class TestZeroCopyStateFromEnv:
    def test_disabled_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("OVGEAR_ZERO_COPY", raising=False)
        s = ZeroCopyState.from_env()
        assert s.mode is _Mode.DISABLED
        assert s.disabled is True
        assert s.gpu_pending is False

    def test_disabled_when_env_zero(self, monkeypatch):
        monkeypatch.setenv("OVGEAR_ZERO_COPY", "0")
        s = ZeroCopyState.from_env()
        assert s.mode is _Mode.DISABLED

    def test_probing_when_env_one(self, monkeypatch):
        monkeypatch.setenv("OVGEAR_ZERO_COPY", "1")
        s = ZeroCopyState.from_env()
        assert s.mode is _Mode.PROBING
        assert s.gpu_pending is True
        assert s.enabled is False


class TestZeroCopyStateTransitions:
    def test_mark_enabled_from_probing(self):
        s = ZeroCopyState(_Mode.PROBING)
        s.mark_enabled()
        assert s.mode is _Mode.ENABLED
        assert s.gpu_pending is True

    def test_mark_enabled_no_op_from_disabled(self):
        s = ZeroCopyState(_Mode.DISABLED)
        s.mark_enabled()
        assert s.mode is _Mode.DISABLED  # cannot upgrade DISABLED

    def test_mark_fallback_from_probing(self):
        s = ZeroCopyState(_Mode.PROBING)
        s.mark_fallback("test")
        assert s.mode is _Mode.FALLBACK
        assert s.fallback_reason == "test"
        assert s.gpu_pending is False

    def test_mark_fallback_from_enabled(self):
        # An already-enabled state can still be downgraded if the GPU
        # backend stops working mid-session.
        s = ZeroCopyState(_Mode.ENABLED)
        s.mark_fallback("late failure")
        assert s.mode is _Mode.FALLBACK


class TestImageBridgeGpuDispatch:
    """The bridge must route GpuFrame through set_bytes_data_from_gpu."""

    def test_gpu_frame_routes_to_set_bytes_data_from_gpu(self):
        state = ZeroCopyState(_Mode.ENABLED)  # skip the probe path
        bridge = ImageBridge(8, 8, state=state)
        bridge._provider = MagicMock()
        mapping = MagicMock()
        frame = GpuFrame(ptr=0xDEADBEEF, width=8, height=8, mapping=mapping)
        bridge.update(frame)
        bridge._provider.set_bytes_data_from_gpu.assert_called_once_with(
            0xDEADBEEF, [8, 8]
        )
        bridge._provider.set_data_array.assert_not_called()
        # Mapping must always be released after the GPU push.
        mapping.__exit__.assert_called_once()

    def test_probe_detects_standalone_no_op_and_falls_back(self):
        state = ZeroCopyState(_Mode.PROBING)
        bridge = ImageBridge(8, 8, state=state)

        def emit_warning(*args, **kwargs):
            os.write(2, b"OpenGLByteImageGpu: fromGpu not supported\n")

        bridge._provider = MagicMock()
        bridge._provider.set_bytes_data_from_gpu.side_effect = emit_warning
        mapping = MagicMock()
        frame = GpuFrame(ptr=0x1000, width=8, height=8, mapping=mapping)
        bridge.update(frame)
        assert state.mode is _Mode.FALLBACK
        assert "fromGpu not supported" in (state.fallback_reason or "")
        mapping.__exit__.assert_called_once()

    def test_probe_marks_enabled_when_no_warning(self):
        state = ZeroCopyState(_Mode.PROBING)
        bridge = ImageBridge(8, 8, state=state)
        bridge._provider = MagicMock()  # no stderr emission
        frame = GpuFrame(ptr=0x2000, width=8, height=8, mapping=MagicMock())
        bridge.update(frame)
        assert state.mode is _Mode.ENABLED

    def test_mapping_closed_even_when_provider_raises(self):
        state = ZeroCopyState(_Mode.ENABLED)
        bridge = ImageBridge(8, 8, state=state)
        bridge._provider = MagicMock()
        bridge._provider.set_bytes_data_from_gpu.side_effect = RuntimeError("boom")
        mapping = MagicMock()
        frame = GpuFrame(ptr=0x3000, width=8, height=8, mapping=mapping)
        with pytest.raises(RuntimeError):
            bridge.update(frame)
        mapping.__exit__.assert_called_once()


class TestGpuFrameLifecycle:
    def test_close_calls_mapping_exit(self):
        mapping = MagicMock()
        frame = GpuFrame(ptr=42, width=4, height=4, mapping=mapping)
        frame.close()
        mapping.__exit__.assert_called_once_with(None, None, None)

    def test_close_is_idempotent(self):
        mapping = MagicMock()
        frame = GpuFrame(ptr=42, width=4, height=4, mapping=mapping)
        frame.close()
        frame.close()
        mapping.__exit__.assert_called_once()

    def test_close_swallows_mapping_exit_exception(self):
        mapping = MagicMock()
        mapping.__exit__.side_effect = RuntimeError("late mapping fail")
        frame = GpuFrame(ptr=42, width=4, height=4, mapping=mapping)
        frame.close()  # must not raise
