# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Depth-one LdrColor overlap behavior for the OVStage BORROW adapter.

Runs without the ovstage runtime: the adapter is assembled through the same
``__new__`` field harness the interaction tests use, with a fake renderer
whose step results carry a real mappable LdrColor render var, so the actual
``render_frame`` presentation path (substitution, gating, retention,
release) executes end to end.
"""

from __future__ import annotations

import time
from collections import deque
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from ovui_data_adapters.common.render_vars import RenderVarOutputRequest
from ovui_data_adapters.ovstage import renderer_adapter as mod
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter

H, W = 32, 64
PRODUCT = mod._RENDER_PRODUCT_LOCAL_PATH


class _FakeDevice:
    CPU = "cpu"
    CUDA = "cuda"


class _FakeOvrtx:
    Device = _FakeDevice
    OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP = "omni:selectionOutlineGroup"


class _FakeTensor:
    def __init__(self, array: np.ndarray) -> None:
        self._array = array

    def numpy(self) -> np.ndarray:
        return self._array


class _FakeMapping:
    def __init__(self, array: np.ndarray) -> None:
        self.tensor = _FakeTensor(array)
        self._array = array

    def __enter__(self) -> "_FakeMapping":
        return self

    def __exit__(self, *_exc) -> bool:
        return False

    # the adapter's CPU path reads the mapping through np.from_dlpack
    def __dlpack__(self, **kwargs):
        return self._array.__dlpack__(**kwargs)

    def __dlpack_device__(self):
        return self._array.__dlpack_device__()


class _FakeRenderVar:
    def __init__(self, array: np.ndarray) -> None:
        self._array = array

    def map(self, device=None):
        return _FakeMapping(self._array)


def _products(seq: int) -> dict:
    """Step-result container whose LdrColor pixels encode the frame number."""
    array = np.full((H, W, 4), seq % 251, dtype=np.uint8)
    frame = SimpleNamespace(render_vars={mod._LDR_VAR_NAME: _FakeRenderVar(array)})
    return {PRODUCT: SimpleNamespace(frames=[frame])}


class _FakeRenderer:
    def __init__(self) -> None:
        self.step_result: dict = {}
        self.step_calls = 0
        self.detached = 0

    def step(self, **kwargs: Any) -> dict:
        self.step_calls += 1
        return self.step_result

    def detach_ovstage(self) -> None:
        self.detached += 1


def _adapter() -> OvstageRendererAdapter:
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._scene = SimpleNamespace(_stage=object(), is_open=True,
                                     current_ordinal=1)
    adapter._ovrtx = _FakeOvrtx
    adapter._ovrtx_version = "kit"
    adapter._renderer = _FakeRenderer()
    adapter._attached_stage = adapter._scene._stage
    adapter._path_dictionary = None
    adapter._gpu_device_name = "test gpu"
    adapter._logged_first_step = True
    adapter._render_product_path = PRODUCT
    adapter._runtime_root_path = "/_OvuiRuntime"
    adapter._runtime_camera_local_path = mod._RENDER_CAMERA_LOCAL_PATH
    adapter._runtime_render_product_path = PRODUCT
    adapter._default_render_product_path = PRODUCT
    adapter._active_render_product_common_path = None
    adapter._camera_path = mod._RENDER_CAMERA_LOCAL_PATH
    adapter._active_camera_common_path = None
    adapter._last_resolution = (W, H)
    adapter._last_render_product_resolution = (W, H)
    adapter._dt_clock = time.monotonic()
    adapter._last_load_from_scene_context = False
    adapter._borrow_step_count = 0
    adapter._successful_frame_count = 0
    adapter._last_frame_nonblack_pixels = None
    adapter._last_frame_shape = None
    adapter._selected_paths = []
    adapter._selection_outline_previous_paths = set()
    adapter._selection_outline_styles_configured = False
    adapter._selection_outline_style_calls = 0
    adapter._selection_outline_attribute_writes = 0
    adapter._in_flight_pick_queries = deque()
    adapter._pick_seq = 0
    adapter._pick_enqueue_count = 0
    adapter._pick_result_count = 0
    adapter._last_pick_pixel_rect = None
    adapter._last_pick_path = None
    adapter._last_pick_world_point = None
    adapter._last_view_matrix = None
    adapter._last_proj_matrix = None
    adapter._last_pushed_camera_state = None
    adapter._zero_copy_state = None
    adapter._livestream = None
    adapter._livestream_error_logged = False
    adapter._livestream_host_buf = None
    adapter._point_cloud_requests = {}
    adapter._latest_point_cloud_frames = {}
    adapter._render_var_output_requests = {}
    adapter._latest_render_var_output_frames = {}
    adapter._runtime_population = None
    adapter._runtime_reference_handle = None
    adapter._live_preview_write_count = 0
    adapter._live_preview_clear_count = 0
    adapter._live_preview_paths = set()
    adapter._last_live_preview_path = None
    adapter._last_live_preview_matrix = None
    adapter._ldr_overlap = None
    # point-cloud catalog introspection needs stage records; the overlay
    # branch is exercised separately through _release_retained_output
    adapter._active_product_uses_point_cloud_overlay = lambda: False  # type: ignore[method-assign]
    return adapter


def _view(offset: float = 0.0) -> np.ndarray:
    view = np.eye(4)
    view[0, 3] = offset
    return view


def _render(adapter, seq: int, *, offset: float = 0.0) -> np.ndarray:
    adapter._renderer.step_result = _products(seq)
    return adapter.render_frame(W, H, _view(offset), np.eye(4))


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    monkeypatch.delenv(mod._LDR_OVERLAP_ENV_VAR, raising=False)
    monkeypatch.delenv("OVUI_WIDGETS_REQUIRE_OVRTX", raising=False)


def test_default_render_frame_is_synchronous() -> None:
    adapter = _adapter()
    assert _render(adapter, 1)[0, 0, 0] == 1
    assert _render(adapter, 2)[0, 0, 0] == 2
    assert adapter.presented_camera_snapshot is None


def test_opt_in_enables_depth_one_overlap() -> None:
    adapter = _adapter()
    assert adapter.set_ldr_overlap_enabled(True) is True
    assert _render(adapter, 1)[0, 0, 0] == 1   # sync fill
    assert _render(adapter, 2)[0, 0, 0] == 1   # pipeline-fill duplicate
    assert _render(adapter, 3)[0, 0, 0] == 2   # steady: presents N-1
    assert _render(adapter, 4)[0, 0, 0] == 3


def test_kill_switch_vetoes_opt_in(monkeypatch) -> None:
    monkeypatch.setenv(mod._LDR_OVERLAP_ENV_VAR, "0")
    adapter = _adapter()
    assert adapter.set_ldr_overlap_enabled(True) is False
    assert adapter._ldr_overlap is None
    assert _render(adapter, 1)[0, 0, 0] == 1
    assert _render(adapter, 2)[0, 0, 0] == 2


def test_disable_releases_retained() -> None:
    adapter = _adapter()
    adapter.set_ldr_overlap_enabled(True)
    _render(adapter, 1)
    assert adapter._ldr_overlap.retained_products is not None
    assert adapter.set_ldr_overlap_enabled(False) is False
    assert adapter._ldr_overlap is None


def _overlapped() -> OvstageRendererAdapter:
    adapter = _adapter()
    adapter.set_ldr_overlap_enabled(True)
    _render(adapter, 1)
    _render(adapter, 2)
    assert adapter._ldr_overlap.retained_products is not None
    return adapter


def test_livestream_gate_keeps_synchronous_path() -> None:
    adapter = _overlapped()
    adapter._livestream = SimpleNamespace(
        tee_and_d2h=lambda tensor, w, h, host_buf=None: tensor.numpy(),
        close=lambda: None,
    )
    assert _render(adapter, 3)[0, 0, 0] == 3
    assert adapter._ldr_overlap.retained_products is None


def test_zero_copy_gate_keeps_synchronous_path() -> None:
    adapter = _overlapped()
    adapter._zero_copy_state = SimpleNamespace(
        gpu_pending=True, mark_fallback=lambda reason: None)
    result = _render(adapter, 3)
    assert adapter._ldr_overlap.retained_products is None
    # the fake tensor has no CUDA pointer; the probe falls back to the CPU
    # path — crucially still with the CURRENT (synchronous) frame
    assert result[0, 0, 0] == 3


def test_ldr_output_request_gate_keeps_synchronous_path() -> None:
    adapter = _overlapped()
    adapter._render_var_output_requests["qa"] = RenderVarOutputRequest(
        viewport_id="qa",
        render_product_path=PRODUCT,
        output_id="ldr-preview",
        render_var_name=mod._LDR_VAR_NAME,
    )
    assert _render(adapter, 3)[0, 0, 0] == 3
    assert adapter._ldr_overlap.retained_products is None


def test_non_ldr_request_keeps_overlap() -> None:
    adapter = _overlapped()
    adapter._render_var_output_requests["qa"] = RenderVarOutputRequest(
        viewport_id="qa",
        render_product_path=PRODUCT,
        output_id="depth-preview",
        render_var_name="DistanceToCamera",
    )
    assert _render(adapter, 3)[0, 0, 0] == 2
    assert adapter._ldr_overlap.retained_products is not None


def test_pick_frame_submits_presented_camera_and_skips_presentation() -> None:
    adapter = _adapter()
    adapter.set_ldr_overlap_enabled(True)
    _render(adapter, 1, offset=0.0)
    presented = adapter.presented_camera_snapshot
    assert presented is not None

    adapter._in_flight_pick_queries.append([0, (0.0, 0.0), None, "pick", None])
    adapter._dispatch_pending_pick_results = lambda products: None  # type: ignore[method-assign]
    _render(adapter, 2, offset=5.0)                    # camera moved
    # the recorded (pick-resolving) camera is the PRESENTED one, not the
    # moved live camera
    np.testing.assert_allclose(
        np.asarray(adapter._last_view_matrix, dtype=float).reshape(4, 4),
        presented.view,
    )
    # the pick frame's color was rendered with an already-shown camera:
    # it is presentation-skipped (one explicit duplicate; never shown)
    adapter._in_flight_pick_queries.clear()
    assert _render(adapter, 3, offset=5.0)[0, 0, 0] == 1   # duplicate
    assert _render(adapter, 4, offset=5.0)[0, 0, 0] == 3   # pick frame skipped


def test_presented_snapshot_travels_with_presented_image() -> None:
    adapter = _adapter()
    adapter.set_ldr_overlap_enabled(True)
    _render(adapter, 1, offset=0.0)
    _render(adapter, 2, offset=7.0)     # camera moved; still presents frame 1
    snap = adapter.presented_camera_snapshot
    assert snap is not None
    np.testing.assert_allclose(snap.view, _view(0.0))
    assert snap.size == (W, H)


def test_resolution_change_releases_retained_and_same_size_does_not() -> None:
    adapter = _overlapped()
    adapter.set_resolution(W, H)                       # no-op guard path
    assert adapter._ldr_overlap.retained_products is not None
    # a real change reaches the mutation boundary; the stub stage makes the
    # native write fail AFTER the ownership release already happened
    adapter.set_resolution(W * 2, H * 2)
    assert adapter._ldr_overlap.retained_products is None


def test_remove_scene_and_shutdown_release_retained() -> None:
    adapter = _overlapped()
    adapter._runtime_population = None
    adapter._runtime_reference_handle = None
    adapter.shutdown()
    assert adapter._ldr_overlap.retained_products is None
    assert adapter._ldr_overlap.presented_snapshot is None
    assert adapter._renderer is None


def test_point_cloud_overlay_product_releases_retained() -> None:
    adapter = _overlapped()
    adapter._active_product_uses_point_cloud_overlay = lambda: True  # type: ignore[method-assign]
    output = _render(adapter, 3)
    assert output[0, 0, 3] == 255                      # synthetic canvas
    assert adapter._ldr_overlap.retained_products is None


def test_step_failure_releases_retained_and_recovers() -> None:
    adapter = _overlapped()

    def failing_step(**kwargs: Any) -> dict:
        raise RuntimeError("injected step failure")

    adapter._renderer.step = failing_step  # type: ignore[method-assign]
    assert _render(adapter, 3)[0, 0, 0] == 0           # black frame
    assert adapter._ldr_overlap.retained_products is None
    adapter._renderer = _FakeRenderer()
    assert _render(adapter, 4)[0, 0, 0] == 4           # sync refill


def _render_pixels(adapter, array: np.ndarray) -> None:
    frame = SimpleNamespace(
        render_vars={mod._LDR_VAR_NAME: _FakeRenderVar(array)})
    adapter._renderer.step_result = {PRODUCT: SimpleNamespace(frames=[frame])}
    adapter.render_frame(W, H, _view(), np.eye(4))


def test_nonblack_diagnostic_is_exact_for_sparse_and_black_frames() -> None:
    adapter = _adapter()

    black = np.zeros((H, W, 4), dtype=np.uint8)
    black[..., 3] = 255                     # opaque alpha must not count
    _render_pixels(adapter, black)
    assert adapter._last_frame_nonblack_pixels == 0

    off_grid = black.copy()
    off_grid[1, 1, 0] = 7                   # missed by any strided sampling
    _render_pixels(adapter, off_grid)
    assert adapter._last_frame_nonblack_pixels == 1

    on_grid = black.copy()
    on_grid[0, 0, 1] = 9                    # grid-aligned position: still 1
    _render_pixels(adapter, on_grid)
    assert adapter._last_frame_nonblack_pixels == 1

    dense = black.copy()
    dense[4:8, 10:20, :3] = 33              # exact region count
    _render_pixels(adapter, dense)
    assert adapter._last_frame_nonblack_pixels == 4 * 10
