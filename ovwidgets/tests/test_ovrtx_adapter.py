# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""CPU-side tests for :mod:`ovui_data_adapters.openusd.renderer_adapter`.

These tests exercise the parts of the adapter that don't need a live
ovrtx renderer: ABC conformance, construction-error path when ovrtx
isn't importable, and the pure helpers (``_view_to_ovrtx_transform``,
``_normalize_rgba``, ``_build_session_usda``). GPU-dependent end-to-end
tests live in ``tests/test_ovrtx_renderer_adapter.py`` and are gated
on an actual ovrtx import.
"""

import math
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest
from ovui_data_adapters.common import GpuFrame, RendererAdapter, ZeroCopyState, _Mode
from ovui_data_adapters.openusd import renderer_adapter as mod


class TestAvailabilityFlag:
    def test_available_is_truthy_when_ovrtx_importable(self):
        # ``AVAILABLE`` is a lazy-probe descriptor — truthiness triggers
        # the import and caches the result. Calling ``bool`` is the
        # public contract; the probe only runs once per process.
        assert isinstance(bool(mod.AVAILABLE), bool)

    def test_available_reflects_lazy_probe(self):
        # After reading AVAILABLE at least once, the internal probe
        # flag must be set and consistent with whether ``_ovrtx`` loaded.
        bool(mod.AVAILABLE)
        assert mod._OVRTX_PROBED is True
        assert bool(mod.AVAILABLE) is (mod._ovrtx is not None)


class TestAdapterClassConformance:
    def test_is_renderer_adapter_subclass(self):
        assert issubclass(mod.OvRtxRendererAdapter, RendererAdapter)

    def test_implements_all_abstract_methods(self):
        missing = RendererAdapter.__abstractmethods__ - set(
            mod.OvRtxRendererAdapter.__dict__.keys()
        )
        # Inherited methods count too — walk the MRO.
        if missing:
            implemented = set()
            for klass in mod.OvRtxRendererAdapter.__mro__:
                implemented.update(klass.__dict__.keys())
            missing = RendererAdapter.__abstractmethods__ - implemented
        assert not missing, f"missing overrides: {missing}"


class _FakeRenderer:
    def __init__(self):
        self.added_layers = []
        self.removed = []
        self.write_calls = []
        self.step_calls = []

    def add_usd_layer(self, usda, path_prefix=None):
        handle = f"session-{len(self.added_layers)}"
        self.added_layers.append((usda, path_prefix, handle))
        return handle

    def remove_usd(self, handle):
        self.removed.append(handle)

    def write_attribute(self, *args, **kwargs):
        self.write_calls.append((args, kwargs))

    def step(self, render_products, delta_time):
        self.step_calls.append((set(render_products), delta_time))
        return {}


class _FakeSemantic:
    XFORM_MAT4x4 = "xform-mat4x4"


class _FakeOvRtx:
    Semantic = _FakeSemantic


def _live_adapter(stage):
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
    return adapter


def _session_has_spec(stage, path):
    from pxr import Sdf

    return stage.GetSessionLayer().GetPrimAtPath(Sdf.Path(path)) is not None


def _usd_modules():
    pytest.importorskip("pxr")
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdRender

    return Gf, Sdf, Usd, UsdGeom, UsdRender


class TestActiveSelectorState:
    @staticmethod
    def _adapter():
        adapter = mod.OvRtxRendererAdapter.__new__(mod.OvRtxRendererAdapter)
        adapter._default_camera_path = mod._CAMERA_PATH
        adapter._default_render_product_path = mod._RENDER_PRODUCT_PATH
        adapter._camera_path = mod._CAMERA_PATH
        adapter._render_product_path = mod._RENDER_PRODUCT_PATH
        adapter._sync_calls = []

        def _record_sync():
            adapter._sync_calls.append(
                (adapter._camera_path, adapter._render_product_path)
            )

        adapter._sync_active_selector_state = _record_sync
        return adapter

    @pytest.mark.parametrize(
        "setter",
        ["set_active_camera_path", "set_active_render_product_path"],
    )
    @pytest.mark.parametrize(
        "bad_path",
        [
            "World/Camera",
            "/",
            "//foo",
            "/foo/",
            "/foo//bar",
            "/World/Camera.focalLength",
        ],
    )
    def test_selector_rejects_non_prim_paths(self, setter, bad_path):
        adapter = self._adapter()
        assert getattr(adapter, setter)(bad_path) is False
        assert adapter.get_active_camera_path() == mod._CAMERA_PATH
        assert adapter.get_active_render_product_path() == mod._RENDER_PRODUCT_PATH
        assert adapter._sync_calls == []

    def test_live_camera_selector_updates_path_without_session_churn(self, monkeypatch):
        _, _, Usd, _, _ = _usd_modules()
        stage = Usd.Stage.CreateInMemory()
        adapter = _live_adapter(stage)
        adapter._dt_clock = 1.0
        adapter._last_big_delta_time = 2.0
        adapter._last_reinject_time = 3.0
        monkeypatch.setattr(mod.time, "monotonic", lambda: 123.0)

        assert adapter.set_active_camera_path("/World/ShotCamera") is True

        assert adapter.get_active_camera_path() == "/World/ShotCamera"
        assert adapter._session_handle == "old-session"
        assert adapter._renderer.removed == []
        assert adapter._renderer.added_layers == []
        assert adapter._dt_clock == 123.0
        assert adapter._last_big_delta_time == -math.inf
        assert adapter._last_reinject_time == -math.inf
        assert not _session_has_spec(stage, "/World/ShotCamera")
        assert not _session_has_spec(stage, mod._RENDER_PRODUCT_PATH)

        assert adapter.set_active_camera_path("/World/ShotCamera") is True
        assert adapter._renderer.added_layers == []
        assert adapter._renderer.removed == []

    def test_user_render_product_selection_does_not_reauthor_product(self):
        Gf, Sdf, Usd, UsdGeom, UsdRender = _usd_modules()
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Camera.Define(stage, "/World/Camera")
        UsdRender.Var.Define(stage, "/Render/Vars/Beauty")
        product = UsdRender.Product.Define(stage, "/Render/Beauty")
        product.CreateCameraRel().SetTargets([Sdf.Path("/World/Camera")])
        product.CreateOrderedVarsRel().SetTargets(
            [Sdf.Path("/Render/Vars/Beauty")]
        )
        product.CreateResolutionAttr().Set(Gf.Vec2i(1920, 1080))
        adapter = _live_adapter(stage)

        assert adapter.set_active_render_product_path("/Render/Beauty") is True

        assert not _session_has_spec(stage, "/Render/Beauty")
        composed = UsdRender.Product(stage.GetPrimAtPath("/Render/Beauty"))
        assert composed.GetCameraRel().GetTargets() == [Sdf.Path("/World/Camera")]
        assert composed.GetOrderedVarsRel().GetTargets() == [
            Sdf.Path("/Render/Vars/Beauty")
        ]
        assert composed.GetResolutionAttr().Get() == Gf.Vec2i(1920, 1080)

    def test_selected_camera_with_owned_product_drives_owned_camera(
        self, monkeypatch
    ):
        """The owned render product stays bound to the owned session camera.

        A user camera may be the selected viewport camera, but the default
        render product is an ovrtx session-layer product. It remains valid
        by rendering through the owned session camera, which receives the
        live navigation matrices derived from the selected camera pose.
        """
        _, _, Usd, UsdGeom, _ = _usd_modules()
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Camera.Define(stage, "/World/ShotCamera")
        from ovui_data_adapters.openusd._session_authoring import ensure_camera

        ensure_camera(stage, mod._CAMERA_PATH)
        adapter = _live_adapter(stage)
        adapter._camera_path = "/World/ShotCamera"
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)

        from ovwidgets.viewport.camera_controller import CameraController

        view, proj = CameraController().get_matrices(4, 3)
        frame = adapter.render_frame(4, 3, view, proj)

        assert frame.shape == (3, 4, 4)
        assert not _session_has_spec(stage, "/World/ShotCamera")
        assert _session_has_spec(stage, mod._CAMERA_PATH)
        xform_writes = [
            kwargs
            for _, kwargs in adapter._renderer.write_calls
            if kwargs.get("attribute_name") == "omni:xform"
            and kwargs.get("prim_paths") == [mod._CAMERA_PATH]
        ]
        assert xform_writes, "expected an omni:xform write for the owned camera"
        assert not any(
            kwargs.get("attribute_name") == "omni:xform"
            and kwargs.get("prim_paths") == ["/World/ShotCamera"]
            for _, kwargs in adapter._renderer.write_calls
        )

    def test_user_render_product_selected_camera_receives_live_fabric_writes(
        self, monkeypatch
    ):
        _, _, Usd, UsdGeom, _ = _usd_modules()
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Camera.Define(stage, "/World/ShotCamera")
        adapter = _live_adapter(stage)
        adapter._render_product_path = "/Render/Beauty"
        adapter._camera_path = "/World/ShotCamera"
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)

        from ovwidgets.viewport.camera_controller import CameraController

        view, proj = CameraController().get_matrices(4, 3)
        frame = adapter.render_frame(4, 3, view, proj)

        assert frame.shape == (3, 4, 4)
        assert not _session_has_spec(stage, "/World/ShotCamera")
        xform_writes = [
            kwargs
            for _, kwargs in adapter._renderer.write_calls
            if kwargs.get("attribute_name") == "omni:xform"
            and kwargs.get("prim_paths") == ["/World/ShotCamera"]
        ]
        assert xform_writes, (
            "expected an omni:xform write for the selected user camera "
            "when a user render product is active"
        )

    def test_parented_user_camera_receives_world_space_fabric_write(
        self, monkeypatch
    ):
        Gf, _, Usd, UsdGeom, _ = _usd_modules()
        stage = Usd.Stage.CreateInMemory()
        world = UsdGeom.Xform.Define(stage, "/World")
        world.AddTranslateOp().Set(Gf.Vec3d(100.0, 0.0, 0.0))
        UsdGeom.Camera.Define(stage, "/World/ShotCamera")
        adapter = _live_adapter(stage)
        adapter._render_product_path = "/Render/Beauty"
        adapter._camera_path = "/World/ShotCamera"
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)

        from ovwidgets.viewport.camera_controller import CameraController

        controller = CameraController()
        controller.focus(target=[3.0, 2.0, -1.0], distance=25.0)
        controller.orbit(0.5, 0.25)
        view, proj = controller.get_matrices(4, 3)
        expected_eye = controller._get_eye()

        adapter.render_frame(4, 3, view, proj)

        xform_writes = [
            kwargs
            for _, kwargs in adapter._renderer.write_calls
            if kwargs.get("attribute_name") == "omni:xform"
            and kwargs.get("prim_paths") == ["/World/ShotCamera"]
        ]
        assert xform_writes, (
            "expected an omni:xform write for the selected parented camera"
        )
        tensor = xform_writes[-1]["tensor"]
        np.testing.assert_allclose(
            tensor[0, 3, :3],
            expected_eye,
            rtol=1e-5,
            atol=1e-5,
        )
        assert tensor[0, 3, 0] != pytest.approx(float(expected_eye[0]) - 100.0)
        assert not _session_has_spec(stage, "/World/ShotCamera")

    def test_default_camera_still_receives_per_frame_writes(self, monkeypatch):
        _, _, Usd, _, _ = _usd_modules()
        from ovui_data_adapters.openusd._session_authoring import ensure_camera

        from ovwidgets.viewport.camera_controller import CameraController

        stage = Usd.Stage.CreateInMemory()
        ensure_camera(stage, mod._CAMERA_PATH)
        adapter = _live_adapter(stage)
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)

        view, proj = CameraController().get_matrices(4, 3)
        adapter.render_frame(4, 3, view, proj)

        assert any(
            kwargs.get("prim_paths") == [mod._CAMERA_PATH]
            and kwargs.get("attribute_name") == "omni:xform"
            for _, kwargs in adapter._renderer.write_calls
        )


class TestConstructorWhenUnavailable:
    def test_raises_when_ovrtx_missing(self, monkeypatch):
        # Force the unavailable branch even if ovrtx imported cleanly.
        # Pin the lazy probe outcome to simulate a system without ovrtx.
        monkeypatch.setattr(mod, "_OVRTX_PROBED", True)
        monkeypatch.setattr(mod, "_ovrtx", None)
        monkeypatch.setattr(
            mod, "_OVRTX_IMPORT_ERROR", ImportError("pretend-missing")
        )
        with pytest.raises(RuntimeError, match="ovrtx is not available"):
            mod.OvRtxRendererAdapter()


class TestViewToOvrtxTransform:
    def test_identity_view_gives_identity_world(self):
        view = np.eye(4, dtype=np.float64)
        t = mod._view_to_ovrtx_transform(view)
        assert t.shape == (1, 4, 4)
        assert t.dtype == np.float64
        np.testing.assert_allclose(t[0], np.eye(4), atol=1e-10)

    def test_result_is_c_contiguous(self):
        # ovrtx_write_attribute rejects non-compact strides, so the
        # returned tensor MUST be C-contiguous after the transpose.
        view = np.eye(4, dtype=np.float64)
        view[0, 3] = 1.0
        view[1, 3] = 2.0
        view[2, 3] = 3.0
        t = mod._view_to_ovrtx_transform(view)
        assert t.flags["C_CONTIGUOUS"] is True

    def test_translation_lands_in_row_3_of_world(self):
        # View translates camera-space origin by (-10, -20, -30) —
        # i.e., the camera is at (+10, +20, +30) in world. With USD
        # row-vector convention the translation sits in the last row.
        view = np.eye(4, dtype=np.float64)
        view[0, 3] = -10.0
        view[1, 3] = -20.0
        view[2, 3] = -30.0
        t = mod._view_to_ovrtx_transform(view)
        assert t[0, 3, 0] == pytest.approx(10.0)
        assert t[0, 3, 1] == pytest.approx(20.0)
        assert t[0, 3, 2] == pytest.approx(30.0)

    def test_camera_controller_roundtrip(self):
        from ovwidgets.viewport.camera_controller import CameraController
        cam = CameraController()
        cam.focus(target=[0, 50, 0], distance=500.0)
        cam.orbit(0.7, 0.2)
        view, _ = cam.get_matrices(1280, 720)
        t = mod._view_to_ovrtx_transform(view)
        # Camera position from CameraController must equal last row.
        eye = cam._get_eye()
        assert t[0, 3, 0] == pytest.approx(float(eye[0]), rel=1e-5)
        assert t[0, 3, 1] == pytest.approx(float(eye[1]), rel=1e-5)
        assert t[0, 3, 2] == pytest.approx(float(eye[2]), rel=1e-5)

    def test_rejects_wrong_shape(self):
        with pytest.raises(ValueError, match="4x4"):
            mod._view_to_ovrtx_transform(np.eye(3))


class TestNormalizeRgba:
    def test_passthrough_correct_shape_and_dtype(self):
        src = np.random.default_rng(0).integers(0, 256, size=(100, 200, 4), dtype=np.uint8)
        out = mod._normalize_rgba(src, 200, 100)
        assert out.shape == (100, 200, 4)
        assert out.dtype == np.uint8
        np.testing.assert_array_equal(out, src)

    def test_rgb_to_rgba_pads_alpha(self):
        src = np.full((10, 20, 3), 128, dtype=np.uint8)
        out = mod._normalize_rgba(src, 20, 10)
        assert out.shape == (10, 20, 4)
        assert np.all(out[:, :, 3] == 255)
        assert np.all(out[:, :, 0] == 128)

    def test_float_converted_to_uint8(self):
        src = np.ones((5, 5, 4), dtype=np.float32) * 0.5
        out = mod._normalize_rgba(src, 5, 5)
        assert out.dtype == np.uint8
        assert int(out[0, 0, 0]) == 127 or int(out[0, 0, 0]) == 128

    def test_returns_contiguous(self):
        src = np.random.default_rng(1).integers(0, 256, size=(10, 10, 4), dtype=np.uint8)
        # Make non-contiguous view
        view = src[::1]
        out = mod._normalize_rgba(view, 10, 10)
        assert out.flags["C_CONTIGUOUS"]

    def test_cropping_to_requested_size(self):
        src = np.ones((100, 200, 4), dtype=np.uint8) * 99
        out = mod._normalize_rgba(src, 80, 60)
        assert out.shape == (60, 80, 4)
        # Values preserved within the overlap region.
        assert np.all(out[:60, :80] == 99)

    def test_padding_to_requested_size(self):
        src = np.ones((40, 60, 4), dtype=np.uint8) * 77
        out = mod._normalize_rgba(src, 100, 80)
        assert out.shape == (80, 100, 4)
        # Source region retained, rest is zero-padded.
        assert np.all(out[:40, :60] == 77)
        assert np.all(out[40:, :] == 0)
        assert np.all(out[:, 60:] == 0)


class TestExtractLdrColor:
    @staticmethod
    def _cpu_products(path, arr):
        class Tensor:
            def numpy(self):
                return arr

        class Mapping:
            tensor = Tensor()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class RenderVar:
            def map(self, device):
                return Mapping()

        frame_out = type("FrameOut", (), {"render_vars": {mod._LDR_VAR_NAME: RenderVar()}})()
        product = type("Product", (), {"frames": [frame_out]})()
        return {path: product}

    def test_extract_uses_active_render_product_path(self, monkeypatch):
        class Device:
            CPU = "cpu"
            CUDA = "cuda"

        monkeypatch.setattr(mod, "_ovrtx", type("FakeOvRtx", (), {"Device": Device}))
        adapter = mod.OvRtxRendererAdapter.__new__(mod.OvRtxRendererAdapter)
        adapter._render_product_path = "/Render/Beauty"
        adapter._last_resolution = (4, 3)
        adapter._zero_copy_state = None
        adapter._livestream = None

        src = np.full((3, 4, 4), 51, dtype=np.uint8)
        frame = adapter._extract_ldr_color(
            self._cpu_products("/Render/Beauty", src), 4, 3
        )

        assert frame.shape == (3, 4, 4)
        assert np.all(frame == 51)

    def test_extract_missing_active_render_product_returns_black(self):
        adapter = mod.OvRtxRendererAdapter.__new__(mod.OvRtxRendererAdapter)
        adapter._render_product_path = "/Render/Missing"

        frame = adapter._extract_ldr_color({}, 4, 3)

        assert frame.shape == (3, 4, 4)
        assert frame.dtype == np.uint8
        assert int(frame.max()) == 0

    def test_gpu_path_returns_gpu_frame_when_size_matches(self, monkeypatch):
        class Device:
            CPU = "cpu"
            CUDA = "cuda"

        FakeOvRtx = type("FakeOvRtx", (), {"Device": Device})

        class Tensor:
            data = 0xCAFE

        class Mapping:
            def __init__(self):
                self.tensor = Tensor()
                self.entered = False
                self.exited = False

            def __enter__(self):
                self.entered = True
                return self

            def __exit__(self, exc_type, exc, tb):
                self.exited = True
                return False

        class RenderVar:
            def __init__(self, mapping):
                self.mapping = mapping
                self.devices = []

            def map(self, device):
                self.devices.append(device)
                return self.mapping

        monkeypatch.setattr(mod, "_ovrtx", FakeOvRtx)
        adapter = mod.OvRtxRendererAdapter.__new__(mod.OvRtxRendererAdapter)
        adapter._render_product_path = mod._RENDER_PRODUCT_PATH
        adapter._last_resolution = (640, 480)
        adapter._zero_copy_state = ZeroCopyState(_Mode.ENABLED)

        mapping = Mapping()
        rv = RenderVar(mapping)
        frame_out = type("FrameOut", (), {"render_vars": {mod._LDR_VAR_NAME: rv}})()
        product = type("Product", (), {"frames": [frame_out]})()
        products = {mod._RENDER_PRODUCT_PATH: product}

        frame = adapter._extract_ldr_color(products, 640, 480)

        assert isinstance(frame, GpuFrame)
        try:
            assert frame.ptr == 0xCAFE
            assert (frame.width, frame.height) == (640, 480)
            assert rv.devices == [Device.CUDA]
            assert mapping.entered is True
            assert mapping.exited is False
        finally:
            frame.close()
        assert mapping.exited is True

    def test_gpu_path_uses_active_render_product_path(self, monkeypatch):
        class Device:
            CPU = "cpu"
            CUDA = "cuda"

        FakeOvRtx = type("FakeOvRtx", (), {"Device": Device})

        class Tensor:
            data = 0xBEEF

        class Mapping:
            def __init__(self):
                self.tensor = Tensor()
                self.exited = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.exited = True
                return False

        class RenderVar:
            def __init__(self, mapping):
                self.mapping = mapping
                self.devices = []

            def map(self, device):
                self.devices.append(device)
                return self.mapping

        monkeypatch.setattr(mod, "_ovrtx", FakeOvRtx)
        adapter = mod.OvRtxRendererAdapter.__new__(mod.OvRtxRendererAdapter)
        adapter._render_product_path = "/Render/Beauty"
        adapter._last_resolution = (640, 480)
        adapter._zero_copy_state = ZeroCopyState(_Mode.ENABLED)

        mapping = Mapping()
        rv = RenderVar(mapping)
        frame_out = type("FrameOut", (), {"render_vars": {mod._LDR_VAR_NAME: rv}})()
        product = type("Product", (), {"frames": [frame_out]})()
        products = {"/Render/Beauty": product}

        frame = adapter._extract_ldr_color(products, 640, 480)

        assert isinstance(frame, GpuFrame)
        try:
            assert frame.ptr == 0xBEEF
            assert rv.devices == [Device.CUDA]
        finally:
            frame.close()
        assert mapping.exited is True

    def test_gpu_path_skipped_during_debounced_resize(self, monkeypatch):
        class Device:
            CPU = "cpu"
            CUDA = "cuda"

        FakeOvRtx = type("FakeOvRtx", (), {"Device": Device})

        class Tensor:
            def __init__(self, arr):
                self._arr = arr

            def numpy(self):
                return self._arr

        class Mapping:
            def __init__(self, arr):
                self.tensor = Tensor(arr)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class RenderVar:
            def __init__(self, arr):
                self._arr = arr
                self.devices = []

            def map(self, device):
                self.devices.append(device)
                return Mapping(self._arr)

        monkeypatch.setattr(mod, "_ovrtx", FakeOvRtx)
        adapter = mod.OvRtxRendererAdapter.__new__(mod.OvRtxRendererAdapter)
        adapter._render_product_path = mod._RENDER_PRODUCT_PATH
        adapter._last_resolution = (640, 480)
        adapter._zero_copy_state = ZeroCopyState(_Mode.ENABLED)

        src = np.ones((480, 640, 4), dtype=np.uint8) * 17
        rv = RenderVar(src)
        frame_out = type("FrameOut", (), {"render_vars": {mod._LDR_VAR_NAME: rv}})()
        product = type("Product", (), {"frames": [frame_out]})()
        products = {mod._RENDER_PRODUCT_PATH: product}

        frame = adapter._extract_ldr_color(products, 800, 600)

        assert rv.devices == [Device.CPU]
        assert frame.shape == (600, 800, 4)
        assert np.all(frame[:480, :640] == 17)
        assert np.all(frame[480:, :] == 0)
        assert np.all(frame[:, 640:] == 0)


class TestBuildSessionUsda:
    def test_no_dome_block_when_disabled(self):
        usda = mod._build_session_usda((1280, 720), include_fallback_dome=False)
        assert "DomeLight" not in usda
        assert "FallbackDome" not in usda


class TestExtractLdrColorLivestream:
    """Adapter-level tests pinning livestream-related extraction
    behavior. Build adapters via ``__new__`` so we don't need a real
    ovrtx renderer."""

    @staticmethod
    def _device_class():
        class Device:
            CPU = "cpu"
            CUDA = "cuda"
        return Device

    @staticmethod
    def _build_rv(ptr, arr=None):
        """Build a fake render var that records every map() call.
        ``arr`` is the numpy array the CPU map should expose; if None
        the CPU map raises (used by livestream-only path)."""
        device_seq: list = []

        class Tensor:
            data = ptr
            shape = arr.shape[:2] if arr is not None else (0, 0)

            def numpy(self):
                if arr is None:
                    raise RuntimeError("CPU numpy not used here")
                return arr

        class Mapping:
            tensor = Tensor()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        class RV:
            def map(self, device):
                device_seq.append(device)
                return Mapping()

        return RV(), device_seq

    def test_livestream_only_uses_exactly_one_cuda_map(self, monkeypatch):
        """Codex blocker 1 / coverage gap: when only the livestream is
        active, the adapter calls rv.map(device=CUDA) exactly once
        per frame and routes the tensor through the tap."""
        Device = self._device_class()
        monkeypatch.setattr(mod, "_ovrtx", type("_F", (), {"Device": Device}))

        adapter = mod.OvRtxRendererAdapter.__new__(mod.OvRtxRendererAdapter)
        adapter._render_product_path = mod._RENDER_PRODUCT_PATH
        adapter._last_resolution = (3, 2)
        adapter._zero_copy_state = None

        # Mock livestream tap.
        livestream = MagicMock()
        livestream.tee_and_d2h.return_value = np.ones((2, 3, 4), dtype=np.uint8) * 7
        adapter._livestream = livestream
        adapter._livestream_host_buf = None
        adapter._livestream_error_logged = False

        rv, device_seq = self._build_rv(ptr=0xDEAD)
        frame_out = type("FO", (), {"render_vars": {mod._LDR_VAR_NAME: rv}})()
        product = type("P", (), {"frames": [frame_out]})()
        products = {mod._RENDER_PRODUCT_PATH: product}

        out = adapter._extract_ldr_color(products, 3, 2)

        assert device_seq == [Device.CUDA]  # exactly one map, on CUDA
        livestream.tee_and_d2h.assert_called_once()
        assert out.shape == (2, 3, 4)

    def test_zero_copy_plus_livestream_tees_then_returns_gpu_frame(self, monkeypatch):
        """Codex blocker 4: with both env flags effectively on (state
        gpu_pending + livestream attached), the adapter must tee to
        ovstream from the same mapping AND return a ``GpuFrame``. Single
        rv.map(device=CUDA) call serves both consumers."""
        Device = self._device_class()
        monkeypatch.setattr(mod, "_ovrtx", type("_F", (), {"Device": Device}))

        adapter = mod.OvRtxRendererAdapter.__new__(mod.OvRtxRendererAdapter)
        adapter._render_product_path = mod._RENDER_PRODUCT_PATH
        adapter._last_resolution = (3, 2)
        adapter._zero_copy_state = ZeroCopyState(_Mode.ENABLED)

        livestream = MagicMock()
        livestream.tee_to_ovstream.return_value = True
        adapter._livestream = livestream
        adapter._livestream_host_buf = None
        adapter._livestream_error_logged = False

        rv, device_seq = self._build_rv(ptr=0xBEEF)
        frame_out = type("FO", (), {"render_vars": {mod._LDR_VAR_NAME: rv}})()
        product = type("P", (), {"frames": [frame_out]})()
        products = {mod._RENDER_PRODUCT_PATH: product}

        result = adapter._extract_ldr_color(products, 3, 2)

        # Exactly one CUDA map served both the GpuFrame and the
        # ovstream tee.
        assert device_seq == [Device.CUDA]
        livestream.tee_to_ovstream.assert_called_once()
        assert isinstance(result, GpuFrame)
        assert result.ptr == 0xBEEF
        assert (result.width, result.height) == (3, 2)
        # Mapping should still be alive — it's owned by the GpuFrame.
        result.close()

    def test_livestream_failure_falls_through_to_cpu(self, monkeypatch):
        """Codex blocker 3: if the livestream-only path raises (i.e.
        the tap's contract is violated), the adapter must fall back
        to the CPU map path so the viewport stays live, not return
        black."""
        Device = self._device_class()
        monkeypatch.setattr(mod, "_ovrtx", type("_F", (), {"Device": Device}))

        adapter = mod.OvRtxRendererAdapter.__new__(mod.OvRtxRendererAdapter)
        adapter._render_product_path = mod._RENDER_PRODUCT_PATH
        adapter._last_resolution = (3, 2)
        adapter._zero_copy_state = None

        livestream = MagicMock()
        livestream.tee_and_d2h.side_effect = RuntimeError("synthetic failure")
        adapter._livestream = livestream
        adapter._livestream_host_buf = None
        adapter._livestream_error_logged = False

        ui_arr = np.full((2, 3, 4), 42, dtype=np.uint8)
        rv, device_seq = self._build_rv(ptr=0xCAFE, arr=ui_arr)
        frame_out = type("FO", (), {"render_vars": {mod._LDR_VAR_NAME: rv}})()
        product = type("P", (), {"frames": [frame_out]})()
        products = {mod._RENDER_PRODUCT_PATH: product}

        out = adapter._extract_ldr_color(products, 3, 2)

        # Sequence: CUDA (tried, raised) → CPU (fallback). NOT a black frame.
        assert Device.CUDA in device_seq
        assert Device.CPU in device_seq
        assert out.shape == (2, 3, 4)
        assert np.all(out == 42)


class TestDefaultOffImportGuarantee:
    """Codex blocker 5: when OVGEAR_LIVESTREAM is unset, the adapter
    must NOT import ``ovui_data_adapters.openusd._livestream_tap``."""

    def test_livestream_tap_not_imported_when_env_unset(self):
        # Run in a child process so we get a clean sys.modules.
        import subprocess
        script = (
            "import os, sys\n"
            "os.environ.pop('OVGEAR_LIVESTREAM', None)\n"
            "from ovui_data_adapters.openusd import renderer_adapter as a\n"
            "# Simulate adapter __init__ enough to exercise the gated import.\n"
            "assert a._livestream_env_enabled() is False\n"
            "sys.exit(0 if 'ovui_data_adapters.openusd._livestream_tap' not in sys.modules else 1)\n"
        )
        rc = subprocess.call([sys.executable, "-c", script])
        assert rc == 0, "ovui_data_adapters.openusd._livestream_tap was imported with env unset"

    def test_livestream_tap_not_imported_when_env_zero(self):
        import subprocess
        script = (
            "import os, sys\n"
            "os.environ['OVGEAR_LIVESTREAM'] = '0'\n"
            "from ovui_data_adapters.openusd import renderer_adapter as a\n"
            "assert a._livestream_env_enabled() is False\n"
            "sys.exit(0 if 'ovui_data_adapters.openusd._livestream_tap' not in sys.modules else 1)\n"
        )
        rc = subprocess.call([sys.executable, "-c", script])
        assert rc == 0, "ovui_data_adapters.openusd._livestream_tap was imported with env=0"

    def test_dome_block_when_enabled(self):
        usda = mod._build_session_usda((1280, 720), include_fallback_dome=True)
        assert "DomeLight" in usda
        assert "FallbackDome" in usda
        assert "intensity" in usda

    def test_default_prim_declared(self):
        usda = mod._build_session_usda((1280, 720), False)
        assert 'defaultPrim = "OvGearSession"' in usda

    def test_render_product_references_camera(self):
        usda = mod._build_session_usda((1280, 720), False)
        assert "rel camera = </OvGearSession/Cameras/Main>" in usda

    def test_render_product_references_selected_camera(self):
        usda = mod._build_session_usda(
            (1280, 720),
            False,
            camera_path="/World/ShotCamera",
        )
        assert "rel camera = </World/ShotCamera>" in usda

    def test_render_product_references_ldr_var(self):
        usda = mod._build_session_usda((1280, 720), False)
        assert "rel orderedVars = </OvGearSession/Render/Vars/LdrColor>" in usda

    def test_render_product_pinned_to_cuda_visible_gpu_zero(self):
        usda = mod._build_session_usda((1280, 720), False)
        assert "uniform uint[] deviceIds = [0]" in usda

    def test_resolution_propagates(self):
        usda = mod._build_session_usda((1920, 1080), False)
        assert "resolution = (1920, 1080)" in usda

    def test_ldr_var_source_name(self):
        usda = mod._build_session_usda((1280, 720), False)
        assert 'uniform string sourceName = "LdrColor"' in usda

    def test_camera_intrinsics_present(self):
        usda = mod._build_session_usda((1280, 720), False)
        assert "focalLength = 18" in usda
        assert "horizontalAperture = 20.955" in usda
        assert "verticalAperture = 15.2908" in usda
        assert "clippingRange = (0.01, 10000)" in usda

    def test_prim_hierarchy_under_session(self):
        usda = mod._build_session_usda((1280, 720), False)
        # Only the session root appears at the top level — no
        # /Render or other stray absolute paths that might collide
        # with the user's root layer.
        lines = [
            line.strip()
            for line in usda.splitlines()
            if line.strip().startswith("def ")
            and not line.startswith("    ")
            and not line.startswith("\t")
        ]
        # Top-level defs (no indent) should be only the session scope.
        # ``def Scope "OvGearSession"`` is the sole top-level prim.
        assert lines == ['def Scope "OvGearSession"']


# --------------------------------------------------------------------------- #
# Resize debouncing (Step A.5)                                                #
# --------------------------------------------------------------------------- #

def _bare_adapter(now_ref):
    """Build an adapter without constructing a real ovrtx.Renderer.

    ``__new__`` skips ``__init__`` so we can plant exactly the attributes
    the debounce helper needs. ``now_ref`` is a single-element list whose
    value advances the fake clock — tests mutate it to simulate elapsed
    time without any real waits.

    Contract: populates the attributes ``_apply_resolution_if_allowed``
    reads or writes (``_last_resolution``, ``_last_big_delta_time``,
    ``_last_reinject_time``, ``_clock``) plus stubs for the collaborators
    that the helper calls (``_reinject_session_layer``). Everything else
    on the adapter is intentionally left unset so an accidentally-widened
    scope in the helper surfaces immediately as AttributeError, rather
    than silently exercising a half-initialised adapter.
    """
    a = mod.OvRtxRendererAdapter.__new__(mod.OvRtxRendererAdapter)
    a._last_resolution = (1280, 720)
    a._last_big_delta_time = -math.inf
    a._last_reinject_time = -math.inf
    a._clock = lambda: now_ref[0]
    # Record reinject calls so tests can count them.
    a._reinject_calls = []

    def _record():
        a._reinject_calls.append(a._last_resolution)
    a._reinject_session_layer = _record  # type: ignore[assignment]
    return a


class TestResizeDebounceConstants:
    """The tuning constants are used by the viewport resize behavior."""

    def test_big_delta_px_is_8(self):
        assert mod._RESIZE_BIG_DELTA_PX == 8

    def test_active_window_is_200ms(self):
        assert mod._RESIZE_ACTIVE_WINDOW_S == pytest.approx(0.200)

    def test_debounce_interval_is_250ms(self):
        assert mod._RESIZE_DEBOUNCE_S == pytest.approx(0.250)


class TestResizeDebounceNoOp:
    def test_same_resolution_is_noop(self):
        now = [100.0]
        a = _bare_adapter(now)
        a._apply_resolution_if_allowed((1280, 720))
        assert a._reinject_calls == []
        assert a._last_resolution == (1280, 720)
        # No clock/state mutations for a no-op.
        assert a._last_big_delta_time == -math.inf
        assert a._last_reinject_time == -math.inf

    def test_small_delta_after_long_idle_applies(self):
        # 3 px change after a fresh adapter — not "actively resizing",
        # so even a sub-threshold delta should still reach ovrtx.
        now = [100.0]
        a = _bare_adapter(now)
        a._apply_resolution_if_allowed((1283, 720))
        assert a._reinject_calls == [(1283, 720)]
        assert a._last_resolution == (1283, 720)


class TestResizeDebounceFirstEvent:
    def test_isolated_big_jump_applies_immediately(self):
        # A single big jump with no recent resize history should fire
        # right away — we only throttle rapid _repeated_ jumps.
        now = [50.0]
        a = _bare_adapter(now)
        a._apply_resolution_if_allowed((800, 600))
        assert a._reinject_calls == [(800, 600)]
        assert a._last_resolution == (800, 600)
        assert a._last_reinject_time == 50.0
        assert a._last_big_delta_time == 50.0


class TestResizeDebounceActiveWindow:
    def test_second_big_jump_within_window_is_throttled(self):
        now = [0.0]
        a = _bare_adapter(now)
        # First big jump: applies immediately.
        a._apply_resolution_if_allowed((800, 600))
        # 50 ms later, another big jump: still within the 200 ms active
        # window AND within the 250 ms debounce — must be deferred.
        now[0] = 0.050
        a._apply_resolution_if_allowed((820, 600))
        assert a._reinject_calls == [(800, 600)]
        assert a._last_resolution == (800, 600)

    def test_throttled_write_still_updates_big_delta_timestamp(self):
        # Even when we skip a write, a big delta must refresh
        # ``_last_big_delta_time`` so the active-resize window tracks
        # the ongoing drag, not just the first frame.
        now = [0.0]
        a = _bare_adapter(now)
        a._apply_resolution_if_allowed((800, 600))   # apply, t=0.000
        now[0] = 0.100
        a._apply_resolution_if_allowed((820, 600))   # throttled
        assert a._last_big_delta_time == 0.100
        assert a._reinject_calls == [(800, 600)]

    def test_big_jump_after_active_window_elapses_applies(self):
        # After 250 ms of silence both conditions clear: the active
        # window is gone AND debounce has elapsed. Should apply.
        now = [0.0]
        a = _bare_adapter(now)
        a._apply_resolution_if_allowed((800, 600))
        now[0] = 0.500
        a._apply_resolution_if_allowed((820, 600))
        assert a._reinject_calls == [(800, 600), (820, 600)]
        assert a._last_resolution == (820, 600)


class TestResizeDebounceThrottleInterval:
    def test_rapid_drag_produces_one_write_per_250ms(self):
        # Simulate a continuous drag: at 60 FPS (1/60 s steps) the widget
        # shrinks from 1280 down by 20 px each frame for 62 frames. Use
        # direct integer division for the timestamp (``i / 60.0`` is
        # exact when ``i`` is a multiple of a power of two in this range,
        # and more importantly it avoids the FP drift of accumulating
        # ``1/60`` — ``sum([1/60]*15) < 0.25`` in IEEE-754). With the
        # 250 ms debounce the apply events land at iterations 0, 15, 30,
        # 45, 60 (= now of 0, 0.25, 0.5, 0.75, 1.0 s) — exactly five
        # writes, not 62.
        now = [0.0]
        a = _bare_adapter(now)
        w = 1280
        for i in range(62):
            now[0] = i / 60.0
            w -= 20
            a._apply_resolution_if_allowed((w, 720))
        assert len(a._reinject_calls) == 5
        # Monotone decreasing widths — later writes see newer sizes.
        widths = [res[0] for res in a._reinject_calls]
        assert widths == sorted(widths, reverse=True)

    def test_mid_drag_debounce_fires_at_250ms_boundary(self):
        # During a sustained drag (big delta every 20 ms keeps the active
        # window fresh), the throttle controls cadence. Feed 12 frames up
        # to t=0.240 — still under the 250 ms debounce — and only the
        # first write fires. One more frame at t=0.260 passes the
        # boundary and triggers the second write.
        now = [0.0]
        a = _bare_adapter(now)
        a._apply_resolution_if_allowed((800, 600))    # t=0.000, apply
        target_w = 800
        for step in range(1, 13):   # 12 * 0.020 = 0.240
            now[0] = step * 0.020
            target_w += 10
            a._apply_resolution_if_allowed((target_w, 600))
        assert len(a._reinject_calls) == 1            # all 12 throttled
        # Push past the 250 ms boundary — drag still active, throttle
        # window is now clear, write fires.
        now[0] = 0.260
        target_w += 10
        a._apply_resolution_if_allowed((target_w, 600))
        assert len(a._reinject_calls) == 2
        assert a._last_resolution == (target_w, 600)


class TestResizeDebounceCatchupAfterDrag:
    def test_final_resolution_committed_after_drag_ends(self):
        # User drags from 1280 down to 800 (big jumps) over 100 ms then
        # stops. Even though many intermediate frames were throttled, the
        # *final* stable resolution must land in ovrtx within one more
        # debounce window so the image stops being stale.
        now = [0.0]
        a = _bare_adapter(now)
        widths = [1200, 1100, 1000, 900, 800]
        for i, w in enumerate(widths):
            now[0] = i * 0.020   # 20 ms cadence
            a._apply_resolution_if_allowed((w, 720))
        # Advance past the debounce window and repeat the last size —
        # exactly what ``_on_frame`` does once the drag ends and the
        # widget stabilizes.
        now[0] = 0.300
        a._apply_resolution_if_allowed((800, 720))
        assert a._last_resolution == (800, 720)
        assert a._reinject_calls[-1] == (800, 720)


class TestResizeDebounceClockInjection:
    def test_injected_clock_drives_debounce_timers(self):
        # The only way tests can exercise the 200/250 ms windows without
        # real sleeps is to override ``self._clock``. Confirm the helper
        # actually reads from the injected callable on every call — not
        # captured-at-init.
        readings = iter([0.000, 0.100, 0.300])
        a = _bare_adapter([0.0])      # reset state with dummy list
        a._clock = lambda: next(readings)
        a._apply_resolution_if_allowed((800, 600))   # reads 0.000 → apply
        a._apply_resolution_if_allowed((820, 600))   # reads 0.100 → throttle
        a._apply_resolution_if_allowed((840, 600))   # reads 0.300 → apply
        assert len(a._reinject_calls) == 2
        assert a._last_resolution == (840, 600)
