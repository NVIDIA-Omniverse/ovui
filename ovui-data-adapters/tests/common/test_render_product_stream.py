# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ovui_data_adapters.common._render_product_stream import (
    attach,
    detach,
    for_current_product,
)


def test_product_binding_never_streams_another_camera_and_preserves_owner():
    adapter = SimpleNamespace(
        product="/Front",
        _livestream=None,
        _stop_native_frame_pacing=Mock(),
        _release_retained_output=Mock(),
    )
    adapter.get_active_render_product_path = lambda: adapter.product
    tap = object()
    attach(adapter, tap, "/Front")
    assert for_current_product(adapter) is tap
    adapter.product = "/Left"
    assert for_current_product(adapter) is None
    detach(adapter, object())
    assert adapter._livestream is tap
    with pytest.raises(ValueError, match="already"):
        attach(adapter, object(), "/Left")
    adapter.product = "/Front"
    assert for_current_product(adapter) is tap
    detach(adapter, tap)
    assert adapter._livestream is None
    with pytest.raises(ValueError, match="Select"):
        attach(adapter, tap, "/Missing")
    assert adapter._livestream is None


def test_authored_product_switch_does_not_recompose_owned_session():
    from unittest.mock import Mock
    from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    adapter._stage = object()
    adapter._renderer = object()
    adapter._usd_handle = object()
    adapter._render_product_path = "/Render/Front"
    adapter._default_render_product_path = "/Owned/Product"
    adapter._reinject_session_layer = Mock()
    adapter._reset_render_timing_state = Mock()
    adapter._sync_active_selector_state()
    adapter._apply_resolution_if_allowed((640, 360))
    adapter._apply_camera_projection(None)
    adapter._reinject_session_layer.assert_not_called()
    adapter._reset_render_timing_state.assert_called_once()
    adapter._render_product_path = "/Owned/Product"
    adapter._sync_active_selector_state()
    adapter._reinject_session_layer.assert_called_once()


def test_renderer_shutdown_releases_a_borrowed_stream_without_closing_it():
    from ovui_data_adapters.common._render_product_stream import (
        is_attached,
        release_for_shutdown,
    )

    adapter = SimpleNamespace(
        product="/Front",
        _livestream=None,
        _stop_native_frame_pacing=Mock(),
        _release_retained_output=Mock(),
    )
    adapter.get_active_render_product_path = lambda: adapter.product
    borrowed = SimpleNamespace(close=Mock())
    attach(adapter, borrowed, "/Front")
    assert is_attached(adapter, borrowed)
    # Media owns this tap; the renderer only releases its binding.
    assert release_for_shutdown(adapter) is None
    borrowed.close.assert_not_called()
    assert adapter._livestream is None and not is_attached(adapter, borrowed)
    owned = SimpleNamespace(close=Mock())
    adapter._livestream = owned
    assert release_for_shutdown(adapter) is owned
