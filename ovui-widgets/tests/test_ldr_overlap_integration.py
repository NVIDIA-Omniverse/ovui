# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Integration tests for the depth-one LdrColor overlap in production paths.

Covers the review-requested integration surface: viewport opt-in at
construction and renderer swap, the one-shot synchronous default, every
overlap gate (kill switch, livestream, zero-copy, LdrColor output request),
current-frame request dispatch ordering relative to image retention,
pick-camera substitution, presented-camera wiring into the SceneView overlay
(with the synchronous fallback), and retained release on shutdown with a
clean successor state.
"""

from __future__ import annotations

import collections
import math

import numpy as np
import pytest

import ovui_data_adapters.openusd.renderer_adapter as mod
from ovui_data_adapters.common import ZeroCopyState
from ovui_data_adapters.common.render_vars import RenderVarOutputRequest
from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
from ovui_widgets.viewport.viewport_widget import ViewportWidget

pytest.importorskip("pxr")
from pxr import Usd  # noqa: E402


# ── fake native plumbing (mirrors test_ovrtx_adapter conventions) ─────────


class _FakeSemantic:
    XFORM_MAT4x4 = "xform-mat4x4"


class _FakeDevice:
    CPU = "cpu"
    CUDA = "cuda"


class _FakeOvRtx:
    Semantic = _FakeSemantic
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

    def __enter__(self) -> "_FakeMapping":
        return self

    def __exit__(self, *_exc) -> bool:
        return False


class _FakeRenderVar:
    def __init__(self, array: np.ndarray) -> None:
        self._array = array
        self.map_count = 0

    def map(self, device=None):
        self.map_count += 1
        return _FakeMapping(self._array)


class _FakeFrameOutput:
    def __init__(self, array: np.ndarray) -> None:
        self.render_vars = {mod._LDR_VAR_NAME: _FakeRenderVar(array)}


class _FakeProductOutput:
    def __init__(self, array: np.ndarray) -> None:
        self.frames = [_FakeFrameOutput(array)]


def _products(seq: int, product_path: str) -> dict:
    """Step-result container whose LdrColor pixels encode the frame number."""
    array = np.full((3, 4, 4), seq % 251, dtype=np.uint8)
    return {product_path: _FakeProductOutput(array)}


class _FakeRenderer:
    def __init__(self) -> None:
        self.step_result: dict = {}
        self.step_calls: list = []
        self.write_calls: list = []
        self.removed: list = []

    def step(self, render_products, delta_time):
        self.step_calls.append((set(render_products), delta_time))
        return self.step_result

    def write_attribute(self, *args, **kwargs):
        self.write_calls.append((args, kwargs))

    def add_usd_reference_from_string(self, usda, prefix_path):
        return f"session-{len(self.step_calls)}"

    def remove_usd(self, handle):
        self.removed.append(handle)


class _FakeLivestream:
    """Livestream tap satisfying the tee_and_d2h/close contract on CPU."""

    def tee_and_d2h(self, tensor, width, height, host_buf=None):
        return tensor.numpy()

    def close(self) -> None:
        pass


def _live_adapter() -> mod.OvRtxRendererAdapter:
    """Adapter with the live-render field set (mirrors the established
    ``_live_adapter`` harness in test_ovrtx_adapter)."""
    stage = Usd.Stage.CreateInMemory()
    from ovui_data_adapters.openusd._session_authoring import ensure_camera

    ensure_camera(stage, mod._CAMERA_PATH)
    adapter = mod.OvRtxRendererAdapter.__new__(mod.OvRtxRendererAdapter)
    adapter._default_camera_path = mod._CAMERA_PATH
    adapter._default_render_product_path = mod._RENDER_PRODUCT_PATH
    adapter._camera_path = mod._CAMERA_PATH
    adapter._render_product_path = mod._RENDER_PRODUCT_PATH
    adapter._stage = stage
    adapter._renderer = _FakeRenderer()
    adapter._usd_handle = object()
    adapter._session_handle = "old-session"
    adapter._last_resolution = (4, 3)
    adapter._pending_resolution = (4, 3)
    adapter._dt_clock = 0.0
    adapter._clock = lambda: 0.0
    adapter._last_big_delta_time = -math.inf
    adapter._last_reinject_time = -math.inf
    adapter._scene_has_lights = True
    adapter._zero_copy_state = None
    adapter._livestream = None
    adapter._last_view = None
    adapter._last_proj = None
    adapter._point_cloud_requests = {}
    adapter._latest_point_cloud_frames = {}
    adapter._render_var_output_requests = {}
    adapter._latest_render_var_output_frames = {}
    adapter._in_flight_pick_queries = collections.deque()
    adapter._owned_tmp_path = None
    adapter._live_resync_handles = []
    adapter._selected_paths = []
    adapter._selection_outline_previous_paths = set()
    adapter._selection_outline_styles_configured = False
    adapter._selection_outline_style_calls = 0
    adapter._selection_outline_attribute_writes = 0
    adapter._selection_outline_generation = 0
    adapter._selection_outline_last_write = {}
    return adapter


def _matrices(offset: float = 0.0):
    from ovui_widgets.viewport.camera_controller import CameraController

    camera = CameraController()
    if offset:
        camera.orbit(offset, 0.0)
    return camera.get_matrices(4, 3)


def _render(adapter, seq: int, *, offset: float = 0.0) -> np.ndarray:
    adapter._renderer.step_result = _products(seq, adapter._render_product_path)
    view, proj = _matrices(offset)
    return adapter.render_frame(4, 3, view, proj)


@pytest.fixture
def fake_ovrtx(monkeypatch):
    monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)
    # hermetic: an ambient kill-switch export must not flip opt-in behavior
    monkeypatch.delenv(mod._LDR_OVERLAP_ENV_VAR, raising=False)


# ── one-shot default stays synchronous; opt-in switches to overlap ────────


class TestOptInSemantics:
    def test_default_adapter_is_synchronous(self, fake_ovrtx):
        adapter = _live_adapter()
        assert _render(adapter, 1)[0, 0, 0] == 1
        assert _render(adapter, 2)[0, 0, 0] == 2   # current frame every call
        assert adapter.presented_camera_snapshot is None

    def test_opt_in_enables_depth_one_overlap(self, fake_ovrtx):
        adapter = _live_adapter()
        assert adapter.set_ldr_overlap_enabled(True) is True
        assert _render(adapter, 1)[0, 0, 0] == 1   # sync fill
        assert _render(adapter, 2)[0, 0, 0] == 1   # pipeline-fill duplicate
        assert _render(adapter, 3)[0, 0, 0] == 2   # steady: presents N-1
        assert _render(adapter, 4)[0, 0, 0] == 3

    def test_kill_switch_vetoes_opt_in(self, fake_ovrtx, monkeypatch):
        monkeypatch.setenv(mod._LDR_OVERLAP_ENV_VAR, "0")
        adapter = _live_adapter()
        assert adapter.set_ldr_overlap_enabled(True) is False
        assert adapter._ldr_overlap is None
        assert _render(adapter, 1)[0, 0, 0] == 1
        assert _render(adapter, 2)[0, 0, 0] == 2   # synchronous

    def test_disable_releases_retained(self, fake_ovrtx):
        adapter = _live_adapter()
        adapter.set_ldr_overlap_enabled(True)
        _render(adapter, 1)
        assert adapter._ldr_overlap.retained_products is not None
        assert adapter.set_ldr_overlap_enabled(False) is False
        assert adapter._ldr_overlap is None


# ── gates keep the synchronous path and drop retention ────────────────────


class TestOverlapGates:
    @pytest.fixture
    def overlapped(self, fake_ovrtx):
        adapter = _live_adapter()
        adapter.set_ldr_overlap_enabled(True)
        _render(adapter, 1)
        _render(adapter, 2)
        assert adapter._ldr_overlap.retained_products is not None
        return adapter

    def test_livestream_gate(self, overlapped):
        overlapped._livestream = _FakeLivestream()
        assert _render(overlapped, 3)[0, 0, 0] == 3   # synchronous
        assert overlapped._ldr_overlap.retained_products is None

    def test_zero_copy_gate(self, overlapped, monkeypatch):
        monkeypatch.setenv("OVGEAR_ZERO_COPY", "1")
        state = ZeroCopyState.from_env()
        assert state.gpu_pending
        overlapped._zero_copy_state = state
        result = _render(overlapped, 3)
        assert overlapped._ldr_overlap.retained_products is None
        # the fake tensor has no CUDA pointer, so the probe falls back to
        # the CPU path — but crucially with the CURRENT (synchronous) frame
        assert result[0, 0, 0] == 3

    def test_ldr_output_request_gate(self, overlapped):
        overlapped._render_var_output_requests["qa"] = RenderVarOutputRequest(
            viewport_id="qa",
            render_product_path=overlapped._render_product_path,
            output_id="ldr-preview",
            render_var_name=mod._LDR_VAR_NAME,
        )
        assert _render(overlapped, 3)[0, 0, 0] == 3
        assert overlapped._ldr_overlap.retained_products is None

    def test_non_ldr_request_keeps_overlap(self, overlapped):
        overlapped._render_var_output_requests["qa"] = RenderVarOutputRequest(
            viewport_id="qa",
            render_product_path=overlapped._render_product_path,
            output_id="depth-preview",
            render_var_name="DistanceToCamera",
        )
        assert _render(overlapped, 3)[0, 0, 0] == 2   # still presents N-1
        assert overlapped._ldr_overlap.retained_products is not None


# ── request dispatch precedes image retention ─────────────────────────────


class TestRequestDispatchOrdering:
    def test_extraction_hooks_see_current_products_while_image_is_previous(
            self, fake_ovrtx, monkeypatch):
        adapter = _live_adapter()
        adapter.set_ldr_overlap_enabled(True)
        seen_pc: list = []
        seen_rv: list = []
        monkeypatch.setattr(adapter, "_extract_requested_point_cloud_frames",
                            seen_pc.append)
        monkeypatch.setattr(adapter, "_extract_requested_render_var_output_frames",
                            seen_rv.append)
        _render(adapter, 1)
        image = _render(adapter, 2)
        current = adapter._renderer.step_result
        # dispatch always receives THIS step's container...
        assert seen_pc[-1] is current and seen_rv[-1] is current
        # ...while the returned image is the previous frame's
        assert image[0, 0, 0] == 1


# ── pick-camera substitution under overlap ────────────────────────────────


class TestPickCameraSubstitution:
    def test_pick_frame_submits_presented_camera(self, fake_ovrtx, monkeypatch):
        adapter = _live_adapter()
        adapter.set_ldr_overlap_enabled(True)
        _render(adapter, 1, offset=0.0)
        presented = adapter.presented_camera_snapshot
        assert presented is not None

        monkeypatch.setattr(adapter, "_dispatch_pending_pick_results",
                            lambda products: None)
        adapter._in_flight_pick_queries.append(object())  # pick this frame
        adapter._renderer.write_calls.clear()
        _render(adapter, 2, offset=5.0)                    # camera moved

        xform_writes = [
            kwargs for _args, kwargs in adapter._renderer.write_calls
            if kwargs.get("attribute_name") == "omni:xform"
        ]
        assert xform_writes, "camera xform must still be pushed"
        expected = mod._view_to_ovrtx_transform(presented.view)
        np.testing.assert_allclose(
            np.asarray(xform_writes[0]["tensor"], dtype=float),
            np.asarray(expected, dtype=float),
        )

    def test_static_pick_keeps_live_camera(self, fake_ovrtx, monkeypatch):
        adapter = _live_adapter()
        adapter.set_ldr_overlap_enabled(True)
        _render(adapter, 1, offset=0.0)
        monkeypatch.setattr(adapter, "_dispatch_pending_pick_results",
                            lambda products: None)
        adapter._in_flight_pick_queries.append(object())
        _render(adapter, 2, offset=0.0)                    # camera unchanged
        # static pick: substituted camera equals the live one, no skip, so
        # the next frame advances normally past the fill duplicate
        assert _render(adapter, 3, offset=0.0)[0, 0, 0] == 2


# ── presented-camera snapshot: adapter property and SceneView wiring ──────


class TestPresentedCamera:
    def test_snapshot_travels_with_presented_image(self, fake_ovrtx):
        adapter = _live_adapter()
        adapter.set_ldr_overlap_enabled(True)
        view1, _ = _matrices(0.0)
        _render(adapter, 1, offset=0.0)
        _render(adapter, 2, offset=5.0)     # camera moved; still presents frame 1
        snap = adapter.presented_camera_snapshot
        assert snap is not None
        np.testing.assert_allclose(
            snap.view, np.asarray(view1, dtype=float).reshape(4, 4))
        assert snap.size == (4, 3)

    def test_scene_view_receives_presented_matrices_with_sync_fallback(self):
        class _Recorder:
            view = None
            projection = None

        class _SnapshotRenderer(MockRendererAdapter):
            presented_camera_snapshot = None

        renderer = _SnapshotRenderer()
        vp = ViewportWidget(services=None, renderer=renderer)
        try:
            vp._image = type("I", (), {"visible": True, "computed_width": 4,
                                       "computed_height": 3})()
            vp._scene_view = _Recorder()

            # synchronous fallback: overlay uses the just-submitted camera
            assert vp.render(0.1) is True
            fallback_view = list(vp._scene_view.view)
            assert len(fallback_view) == 16

            # presented snapshot differs from the live camera: the overlay
            # must follow the SNAPSHOT so gizmos match the visible pixels
            from ovui_data_adapters.common._ldr_overlap import CameraSnapshot

            view, proj = _matrices(9.0)
            snap = CameraSnapshot.capture(view, proj, (4, 3))
            _SnapshotRenderer.presented_camera_snapshot = snap
            assert vp.render(0.1) is True
            presented_view = list(vp._scene_view.view)
            expected = snap.view.T.flatten().tolist()
            assert presented_view == pytest.approx(expected)
            assert presented_view != pytest.approx(fallback_view)
        finally:
            _SnapshotRenderer.presented_camera_snapshot = None
            vp.destroy()


# ── viewport opt-in wiring and lifecycle release ──────────────────────────


class _OptInRecorder(MockRendererAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.opt_in_calls: list = []

    def set_ldr_overlap_enabled(self, enabled: bool) -> bool:
        self.opt_in_calls.append(bool(enabled))
        return bool(enabled)


class TestViewportOptInWiring:
    def test_opt_in_at_construction(self):
        renderer = _OptInRecorder()
        vp = ViewportWidget(services=None, renderer=renderer)
        try:
            assert renderer.opt_in_calls == [True]
        finally:
            vp.destroy()

    def test_opt_in_at_renderer_swap(self):
        first = _OptInRecorder()
        vp = ViewportWidget(services=None, renderer=first)
        try:
            second = _OptInRecorder()
            vp.set_renderer(second)
            assert second.opt_in_calls == [True]
        finally:
            vp.destroy()

    def test_renderer_without_capability_is_tolerated(self):
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            assert vp.render(0.0) in (True, False)  # construction survived
        finally:
            vp.destroy()


class TestLifecycleRelease:
    def test_shutdown_releases_retained_and_successor_starts_empty(
            self, fake_ovrtx):
        adapter = _live_adapter()
        adapter.set_ldr_overlap_enabled(True)
        _render(adapter, 1)
        _render(adapter, 2)
        assert adapter._ldr_overlap.retained_products is not None

        adapter.shutdown()
        assert adapter._ldr_overlap.retained_products is None
        assert adapter._ldr_overlap.presented_snapshot is None
        assert adapter._renderer is None

        successor = _live_adapter()
        successor.set_ldr_overlap_enabled(True)
        assert successor._ldr_overlap.retained_products is None
        assert _render(successor, 7)[0, 0, 0] == 7     # sync fill, no stale

    def test_noop_product_switch_keeps_retained(self, fake_ovrtx):
        adapter = _live_adapter()
        adapter.set_ldr_overlap_enabled(True)
        _render(adapter, 1)
        _render(adapter, 2)
        assert adapter._ldr_overlap.retained_products is not None
        # switching to the already-active product is a guarded no-op and
        # must NOT flush the pipeline (the strict-guard ordering contract)
        adapter.set_active_render_product_path(adapter._render_product_path)
        assert adapter._ldr_overlap.retained_products is not None
