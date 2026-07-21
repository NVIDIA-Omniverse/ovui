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
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from ovui_data_adapters.common import (
    GpuFrame,
    PointCloudChannelDescriptor,
    PointCloudChannelSemantic,
    PointCloudColorMode,
    PointCloudCoordinateSpace,
    PointCloudFrame,
    PointCloudOutputCatalog,
    PointCloudOutputDescriptor,
    PointCloudRequest,
    RendererAdapter,
    RenderVarOutputCatalog,
    RenderVarOutputDescriptor,
    RenderVarOutputKind,
    RenderVarOutputRequest,
    RenderVarPresetKind,
    RenderSettingRequirement,
    RenderSettingValueType,
    ZeroCopyState,
    _Mode,
)
from ovui_data_adapters.common import ovrtx_import as resolver
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


@pytest.fixture
def isolated_ovrtx_probe(monkeypatch):
    sentinel = object()
    original_module = sys.modules.get("ovrtx", sentinel)
    env_names = (
        resolver.OVRTX_LIBRARY_PATH_HINT_ENV,
        "LD_LIBRARY_PATH",
        "PATH",
    )
    original_env = {name: os.environ.get(name) for name in env_names}
    sys.modules.pop("ovrtx", None)
    resolver.reset_ovrtx_import_cache()
    monkeypatch.setattr(mod, "_OVRTX_PROBED", False)
    monkeypatch.setattr(mod, "_ovrtx", None)
    monkeypatch.setattr(mod, "_OVRTX_IMPORT_ERROR", None)
    monkeypatch.delenv(resolver.OVRTX_ROOT_ENV, raising=False)
    monkeypatch.delenv(resolver.OVRTX_BIN_DIR_ENV, raising=False)
    monkeypatch.delenv(resolver.OVRTX_LIBRARY_PATH_HINT_ENV, raising=False)
    yield
    resolver.reset_ovrtx_import_cache()
    sys.modules.pop("ovrtx", None)
    if original_module is not sentinel:
        sys.modules["ovrtx"] = original_module
    for env_name, original_value in original_env.items():
        if original_value is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = original_value


class TestOvRtxImportResolver:
    def test_normal_import_wins_before_ovrtx_root(
        self,
        tmp_path,
        monkeypatch,
        isolated_ovrtx_probe,
    ):
        root = tmp_path / "external"
        (root / "python" / "ovrtx").mkdir(parents=True)
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))
        normal_module = ModuleType("ovrtx")
        calls: list[str] = []

        def fake_import(name: str):
            calls.append(name)
            assert name == "ovrtx"
            return normal_module

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)

        assert mod._probe_ovrtx() is True

        assert mod._ovrtx is normal_module
        assert mod._OVRTX_IMPORT_ERROR is None
        assert calls == ["ovrtx"]
        assert str(root / "python") not in sys.path

    def test_ovrtx_root_python_used_when_normal_import_fails(
        self,
        tmp_path,
        monkeypatch,
        isolated_ovrtx_probe,
    ):
        root = tmp_path / "external"
        candidate = root / "python"
        (candidate / "ovrtx").mkdir(parents=True)
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))
        external_module = ModuleType("ovrtx")
        calls: list[str] = []

        def fake_import(name: str):
            calls.append(name)
            assert name == "ovrtx"
            if len(calls) == 1:
                raise ImportError("active environment missing")
            assert sys.path[0] == str(candidate)
            return external_module

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)

        assert mod._probe_ovrtx() is True

        assert mod._ovrtx is external_module
        assert mod._OVRTX_IMPORT_ERROR is None
        assert calls == ["ovrtx", "ovrtx"]
        assert str(candidate) not in sys.path

    def test_ovrtx_root_direct_package_used_when_normal_import_fails(
        self,
        tmp_path,
        monkeypatch,
        isolated_ovrtx_probe,
    ):
        root = tmp_path / "external"
        (root / "ovrtx").mkdir(parents=True)
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))
        external_module = ModuleType("ovrtx")
        calls: list[str] = []

        def fake_import(name: str):
            calls.append(name)
            assert name == "ovrtx"
            if len(calls) == 1:
                raise ImportError("active environment missing")
            assert sys.path[0] == str(root)
            return external_module

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)

        assert mod._probe_ovrtx() is True

        assert mod._ovrtx is external_module
        assert mod._OVRTX_IMPORT_ERROR is None
        assert calls == ["ovrtx", "ovrtx"]
        assert str(root) not in sys.path

    def test_ovrtx_root_kit_layout_used_when_normal_import_fails(
        self,
        tmp_path,
        monkeypatch,
        isolated_ovrtx_probe,
    ):
        rendering_root = tmp_path / "rendering"
        root = rendering_root / "ovrtx"
        candidate = root / "public" / "python"
        build_dir = rendering_root / "_build" / "linux-x86_64" / "release"
        (candidate / "ovrtx").mkdir(parents=True)
        (build_dir / "plugins" / "rtx").mkdir(parents=True)
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))
        external_module = ModuleType("ovrtx")
        calls: list[str] = []

        def fake_import(name: str):
            calls.append(name)
            assert name == "ovrtx"
            if len(calls) == 1:
                raise ImportError("active environment missing")
            assert sys.path[0] == str(candidate)
            return external_module

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)

        assert mod._probe_ovrtx() is True

        assert mod._ovrtx is external_module
        assert mod._OVRTX_IMPORT_ERROR is None
        assert calls == ["ovrtx", "ovrtx"]
        assert resolver._ovrtx_python_path_candidates(str(root)) == (candidate,)
        assert resolver._ovrtx_runtime_dirs(str(root))[:3] == (
            build_dir,
            build_dir / "plugins",
            build_dir / "plugins" / "rtx",
        )
        assert os.environ[resolver.OVRTX_LIBRARY_PATH_HINT_ENV] == str(build_dir)
        runtime_path_env = "PATH" if sys.platform.startswith("win") else "LD_LIBRARY_PATH"
        assert os.environ[runtime_path_env].split(os.pathsep)[:3] == [
            str(build_dir),
            str(build_dir / "plugins"),
            str(build_dir / "plugins" / "rtx"),
        ]
        assert str(candidate) not in sys.path

    def test_invalid_ovrtx_root_sets_unavailable_reason(
        self,
        tmp_path,
        monkeypatch,
        isolated_ovrtx_probe,
    ):
        root = tmp_path / "missing"
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))

        def fake_import(name: str):
            assert name == "ovrtx"
            raise ImportError("active environment missing")

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)

        assert mod._probe_ovrtx() is False

        assert mod._ovrtx is None
        assert mod._OVRTX_IMPORT_ERROR is not None
        message = str(mod._OVRTX_IMPORT_ERROR)
        assert "active environment missing" in message
        assert resolver.OVRTX_ROOT_ENV in message
        assert f"{resolver.OVRTX_ROOT_ENV}={str(root)!r}" in message
        assert "no importable ovrtx package" in message


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
        self.added_usd = []
        self.opened_strings = []
        self.removed = []
        self.reset_calls = 0
        self.live_reset_calls = 0
        self.write_calls = []
        self.step_calls = []
        self.step_result = {}

    def add_usd(self, path):
        handle = f"root-{len(self.added_usd)}"
        self.added_usd.append((path, handle))
        return handle

    def add_usd_layer(self, usda, path_prefix=None):
        handle = f"session-{len(self.added_layers)}"
        self.added_layers.append((usda, path_prefix, handle))
        return handle

    def add_usd_reference_from_string(self, usda, prefix_path):
        handle = f"reference-{len(self.added_layers)}"
        self.added_layers.append((usda, prefix_path, handle))
        return handle

    def open_usd_from_string(self, usda):
        self.opened_strings.append(usda)

    def remove_usd(self, handle):
        self.removed.append(handle)

    def reset_stage(self):
        self.reset_calls += 1

    def reset(self):
        self.live_reset_calls += 1

    def write_attribute(self, *args, **kwargs):
        self.write_calls.append((args, kwargs))

    def step(self, render_products, delta_time):
        self.step_calls.append((set(render_products), delta_time))
        return self.step_result


class _ReferenceFailingFakeRenderer(_FakeRenderer):
    def add_usd_reference_from_string(self, usda, prefix_path):
        raise RuntimeError("reference add unavailable")


class _FakeSemantic:
    XFORM_MAT4x4 = "xform-mat4x4"


class _FakeDevice:
    CPU = "cpu"
    CUDA = "cuda"


class _FakeOvRtx:
    Semantic = _FakeSemantic
    Device = _FakeDevice
    OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP = "omni:selectionOutlineGroup"


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
    adapter._point_cloud_requests = {}
    adapter._latest_point_cloud_frames = {}
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


def _session_has_spec(stage, path):
    from pxr import Sdf

    return stage.GetSessionLayer().GetPrimAtPath(Sdf.Path(path)) is not None


def _usd_modules():
    pytest.importorskip("pxr")
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdRender

    return Gf, Sdf, Usd, UsdGeom, UsdRender


def _matrices(width: int = 4, height: int = 3):
    from ovui_widgets.viewport.camera_controller import CameraController

    return CameraController().get_matrices(width, height)


def _point_cloud_fixture_stage():
    _, _, Usd, _, _ = _usd_modules()
    path = Path(__file__).parent / "data" / "point_cloud_render_targets.usda"
    stage = Usd.Stage.Open(str(path))
    assert stage is not None
    return stage


def _render_var_fixture_stage():
    _, _, Usd, _, _ = _usd_modules()
    path = Path(__file__).parent / "data" / "render_var_outputs.usda"
    stage = Usd.Stage.Open(str(path))
    assert stage is not None
    return stage


def _livestream_fixture_stage():
    _, _, Usd, _, _ = _usd_modules()
    path = Path(__file__).parent / "data" / "multiple_render_targets.usda"
    stage = Usd.Stage.Open(str(path))
    assert stage is not None
    return stage


def _render_settings_fixture_stage():
    _, _, Usd, _, _ = _usd_modules()
    path = Path(__file__).parent / "data" / "render_settings_products.usda"
    stage = Usd.Stage.Open(str(path))
    assert stage is not None
    return stage


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

    @staticmethod
    def _stage_with_image_product():
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
        return stage

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

    def test_activate_render_target_rejects_without_renderer_backend(self):
        adapter = self._adapter()

        result = adapter.activate_render_target(render_product_path="/Render/Beauty")

        assert result.accepted is False
        assert result.warning_code == "unsupported"
        assert result.active_target_id == mod._RENDER_PRODUCT_PATH
        assert result.active_render_product_path == mod._RENDER_PRODUCT_PATH
        assert adapter.get_active_render_product_path() == mod._RENDER_PRODUCT_PATH
        assert adapter._sync_calls == []

    def test_activate_render_target_accepts_render_product_path(self):
        stage = self._stage_with_image_product()
        adapter = _live_adapter(stage)

        result = adapter.activate_render_target(render_product_path="/Render/Beauty")

        assert result.accepted is True
        assert result.warning_code is None
        assert result.active_target_id == "/Render/Beauty"
        assert result.active_render_product_path == "/Render/Beauty"
        assert adapter.get_active_render_product_path() == "/Render/Beauty"

    def test_activate_render_target_accepts_catalog_target_id(self):
        stage = self._stage_with_image_product()
        adapter = _live_adapter(stage)

        result = adapter.activate_render_target(target_id="/Render/Beauty")

        assert result.accepted is True
        assert result.active_target_id == "/Render/Beauty"
        assert result.active_render_product_path == "/Render/Beauty"
        assert adapter.get_active_render_product_path() == "/Render/Beauty"

    def test_activate_render_target_rejects_missing_target_without_mutation(self):
        _, _, Usd, _, _ = _usd_modules()
        adapter = _live_adapter(Usd.Stage.CreateInMemory())

        result = adapter.activate_render_target()

        assert result.accepted is False
        assert result.warning_code == "missing_target"
        assert result.active_target_id == mod._RENDER_PRODUCT_PATH
        assert result.active_render_product_path == mod._RENDER_PRODUCT_PATH
        assert adapter.get_active_render_product_path() == mod._RENDER_PRODUCT_PATH

    def test_activate_render_target_rejects_malformed_path_without_mutation(self):
        _, _, Usd, _, _ = _usd_modules()
        adapter = _live_adapter(Usd.Stage.CreateInMemory())

        result = adapter.activate_render_target(render_product_path="Render/Beauty")

        assert result.accepted is False
        assert result.warning_code == "unknown_target"
        assert result.active_target_id == mod._RENDER_PRODUCT_PATH
        assert result.active_render_product_path == mod._RENDER_PRODUCT_PATH
        assert adapter.get_active_render_product_path() == mod._RENDER_PRODUCT_PATH

    def test_activate_render_target_rejects_unknown_catalog_target(self):
        stage = self._stage_with_image_product()
        adapter = _live_adapter(stage)

        result = adapter.activate_render_target(render_product_path="/Render/Missing")

        assert result.accepted is False
        assert result.warning_code == "unknown_target"
        assert result.active_target_id == mod._RENDER_PRODUCT_PATH
        assert result.active_render_product_path == mod._RENDER_PRODUCT_PATH
        assert adapter.get_active_render_product_path() == mod._RENDER_PRODUCT_PATH

    def test_activate_render_target_rejects_disabled_catalog_target(self):
        Gf, Sdf, Usd, _, UsdRender = _usd_modules()
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World/Lidar", "OmniLidar")
        var = UsdRender.Var.Define(stage, "/Render/Vars/PointCloud")
        var.CreateSourceNameAttr().Set("PointCloud")
        product = UsdRender.Product.Define(stage, "/Render/LidarProduct")
        product.CreateCameraRel().SetTargets([Sdf.Path("/World/Lidar")])
        product.CreateOrderedVarsRel().SetTargets(
            [Sdf.Path("/Render/Vars/PointCloud")]
        )
        product.CreateResolutionAttr().Set(Gf.Vec2i(1, 1))
        adapter = _live_adapter(stage)

        result = adapter.activate_render_target(
            render_product_path="/Render/LidarProduct"
        )

        assert result.accepted is False
        assert result.warning_code == "unsupported_output"
        assert result.active_target_id == mod._RENDER_PRODUCT_PATH
        assert result.active_render_product_path == mod._RENDER_PRODUCT_PATH
        assert adapter.get_active_render_product_path() == mod._RENDER_PRODUCT_PATH
        assert (
            "PointCloud output requires point-cloud viewport support"
            in result.message
        )

    def test_activate_render_target_maps_backend_rejection(self, monkeypatch):
        stage = self._stage_with_image_product()
        adapter = _live_adapter(stage)
        monkeypatch.setattr(
            adapter, "set_active_render_product_path", lambda path: False
        )

        result = adapter.activate_render_target(render_product_path="/Render/Beauty")

        assert result.accepted is False
        assert result.warning_code == "backend_rejected"
        assert result.active_render_product_path == mod._RENDER_PRODUCT_PATH
        assert adapter.get_active_render_product_path() == mod._RENDER_PRODUCT_PATH

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

        from ovui_widgets.viewport.camera_controller import CameraController

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

    def test_runtime_camera_render_does_not_emit_usd_notices(self, monkeypatch):
        _, _, Usd, _, _ = _usd_modules()
        stage = Usd.Stage.CreateInMemory()
        from ovui_data_adapters.openusd._session_authoring import ensure_camera
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from ovui_widgets.viewport.camera_controller import CameraController

        ensure_camera(stage, mod._CAMERA_PATH)
        deferred = []
        events = []

        def call_later(_delay, callback):
            deferred.append(callback)

        stage_adapter = UsdStageAdapter(stage, call_later=call_later)
        sub = stage_adapter.subscribe_changes(events.append)
        adapter = _live_adapter(stage)
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)
        controller = CameraController()
        try:
            for _ in range(4):
                view, proj = controller.get_matrices(4, 3)
                adapter.render_frame(4, 3, view, proj)
                controller.orbit(0.05, 0.01)
                while deferred:
                    callback = deferred.pop(0)
                    callback()
            assert events == []
        finally:
            sub.cancel()

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

        from ovui_widgets.viewport.camera_controller import CameraController

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

        from ovui_widgets.viewport.camera_controller import CameraController

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

        from ovui_widgets.viewport.camera_controller import CameraController

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


class TestEmptyStageRenderPath:
    @staticmethod
    def _session_only_stage():
        _, _, Usd, _, _ = _usd_modules()
        stage = Usd.Stage.CreateInMemory()
        from ovui_data_adapters.openusd._session_authoring import (
            ensure_camera,
            ensure_dome_light,
            ensure_ldr_color_var,
            ensure_render_product,
            ensure_render_scope,
        )

        ensure_render_scope(stage)
        ensure_camera(stage, mod._CAMERA_PATH)
        ensure_ldr_color_var(stage, mod._LDR_VAR_PATH)
        ensure_render_product(
            stage,
            product_path=mod._RENDER_PRODUCT_PATH,
            camera_path=mod._CAMERA_PATH,
            ldr_var_path=mod._LDR_VAR_PATH,
            resolution=(4, 3),
            ensure_camera_prim=True,
        )
        ensure_dome_light(stage, mod._DOME_LIGHT_PATH)
        return stage

    @staticmethod
    def _with_fake_ovrtx(fn):
        previous = mod._ovrtx
        mod._ovrtx = _FakeOvRtx
        try:
            return fn()
        finally:
            mod._ovrtx = previous

    def test_session_only_stage_uses_normal_step_path(self):
        stage = self._session_only_stage()
        adapter = _live_adapter(stage)

        frame = self._with_fake_ovrtx(
            lambda: adapter.render_frame(4, 3, *_matrices())
        )

        assert len(adapter._renderer.step_calls) == 1
        assert adapter._renderer.step_calls[-1][0] == {mod._RENDER_PRODUCT_PATH}
        assert frame.shape == (3, 4, 4)
        assert np.count_nonzero(frame) == 0
        assert any(
            kwargs.get("prim_paths") == [mod._CAMERA_PATH]
            and kwargs.get("attribute_name") == "omni:xform"
            for _, kwargs in adapter._renderer.write_calls
        )

    def test_user_scene_content_uses_normal_step_path(self):
        _, _, _, UsdGeom, _ = _usd_modules()
        stage = self._session_only_stage()
        UsdGeom.Xform.Define(stage, "/World")
        adapter = _live_adapter(stage)

        self._with_fake_ovrtx(lambda: adapter.render_frame(4, 3, *_matrices()))

        assert len(adapter._renderer.step_calls) == 1


class TestLiveStageChangeSync:
    @staticmethod
    def _stage_with_cube():
        _, _, Usd, UsdGeom, _ = _usd_modules()
        stage = Usd.Stage.CreateInMemory()
        cube = UsdGeom.Cube.Define(stage, "/World/Cube")
        cube.CreateSizeAttr(1.0)
        cube.AddTranslateOp().Set((1.0, 2.0, 3.0))
        return stage, cube

    def test_geometry_property_change_reloads_current_root_snapshot(self):
        stage, cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        adapter._usd_handle = "old-root"
        adapter._session_handle = "old-session"
        adapter._scene_has_lights = mod._stage_has_any_light(stage)
        adapter._latest_point_cloud_frames[("viewport", "/Render/Products/Lidar")] = object()

        cube.GetSizeAttr().Set(4.0)
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=("/World/Cube.size",),
                resynced_paths=(),
            )
        )

        assert "old-session" in adapter._renderer.removed
        assert "old-root" in adapter._renderer.removed
        assert adapter._renderer.opened_strings
        assert "double size = 4" in adapter._renderer.opened_strings[-1]
        assert adapter._renderer.added_layers[-1][1] == mod._SESSION_ROOT_PATH
        assert adapter._renderer.write_calls == []
        assert adapter._latest_point_cloud_frames == {}

    def test_new_prim_resync_installs_root_snapshot_overlay_without_reload(self):
        _, _, _Usd, UsdGeom, _ = _usd_modules()
        stage, _cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        adapter._usd_handle = "old-root"
        adapter._session_handle = "old-session"
        adapter._scene_has_lights = mod._stage_has_any_light(stage)
        adapter._latest_point_cloud_frames[("viewport", "/Render/Products/Lidar")] = object()

        UsdGeom.Sphere.Define(stage, "/World/Sphere")
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=(),
                resynced_paths=("/World/Sphere",),
            )
        )

        assert adapter._renderer.removed == []
        assert adapter._renderer.opened_strings == []
        assert adapter._renderer.added_usd == []
        assert adapter._usd_handle == "old-root"
        assert adapter._session_handle == "old-session"
        assert adapter._live_resync_handles == ["session-0"]
        root_usda = adapter._renderer.added_layers[-1][0]
        assert adapter._renderer.added_layers[-1][1] is None
        assert 'def Cube "Cube"' in root_usda
        assert 'def Sphere "Sphere"' in root_usda
        assert adapter._latest_point_cloud_frames == {}

    def test_new_prim_resync_reapplies_current_selection_outline(self, monkeypatch):
        _, _, _Usd, UsdGeom, _ = _usd_modules()
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)
        stage, _cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        adapter._usd_handle = "old-root"
        adapter._session_handle = "old-session"
        adapter._scene_has_lights = mod._stage_has_any_light(stage)

        adapter.set_selection_highlight(["/World/Cube"])
        assert adapter._selection_outline_previous_paths == {"/World/Cube"}
        adapter._renderer.write_calls.clear()

        UsdGeom.Sphere.Define(stage, "/World/Sphere")
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=(),
                resynced_paths=("/World/Sphere",),
            )
        )

        outline_writes = [
            kwargs
            for _args, kwargs in adapter._renderer.write_calls
            if kwargs.get("attribute_name")
            == _FakeOvRtx.OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP
        ]
        assert outline_writes, "expected selected path outline rewrite after overlay"
        assert outline_writes[-1]["prim_paths"] == ["/World/Cube"]
        assert outline_writes[-1]["tensor"].tolist() == [1]
        assert adapter._selection_outline_last_write["force_reapply"] is True
        assert adapter._selection_outline_last_write["stale_reason"] == "live_resync_overlay"
        assert adapter._selection_outline_last_write["to_set"] == ["/World/Cube"]

    def test_deleted_prim_resync_still_reloads_current_root(self):
        _, _, _Usd, UsdGeom, _ = _usd_modules()
        stage, _cube = self._stage_with_cube()
        UsdGeom.Sphere.Define(stage, "/World/Sphere")
        adapter = _live_adapter(stage)
        adapter._usd_handle = "old-root"
        adapter._session_handle = "old-session"
        adapter._scene_has_lights = mod._stage_has_any_light(stage)
        adapter._live_resync_handles = ["old-overlay"]

        stage.RemovePrim("/World/Sphere")
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=(),
                resynced_paths=("/World/Sphere",),
            )
        )

        assert "old-overlay" in adapter._renderer.removed
        assert "old-session" in adapter._renderer.removed
        assert "old-root" in adapter._renderer.removed
        assert adapter._renderer.opened_strings
        assert 'def Sphere "Sphere"' not in adapter._renderer.opened_strings[-1]

    def test_root_reload_reapplies_current_selection_outline(self, monkeypatch):
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)
        stage, cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        adapter._usd_handle = "old-root"
        adapter._session_handle = "old-session"
        adapter._scene_has_lights = mod._stage_has_any_light(stage)

        adapter.set_selection_highlight(["/World/Cube"])
        assert adapter._selection_outline_previous_paths == {"/World/Cube"}
        adapter._renderer.write_calls.clear()

        cube.GetSizeAttr().Set(4.0)
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=("/World/Cube.size",),
                resynced_paths=(),
            )
        )

        outline_writes = [
            kwargs
            for _args, kwargs in adapter._renderer.write_calls
            if kwargs.get("attribute_name")
            == _FakeOvRtx.OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP
        ]
        assert outline_writes, "expected selected path outline rewrite after reload"
        assert outline_writes[-1]["prim_paths"] == ["/World/Cube"]
        assert outline_writes[-1]["tensor"].tolist() == [1]
        assert adapter._selection_outline_last_write["force_reapply"] is True
        assert adapter._selection_outline_last_write["to_set"] == ["/World/Cube"]

    def test_new_light_resync_reinjects_session_without_root_reload(self):
        _, _, _Usd, _UsdGeom, _ = _usd_modules()
        from pxr import UsdLux

        stage, _cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        adapter._usd_handle = "old-root"
        adapter._session_handle = "old-session"
        adapter._scene_has_lights = mod._stage_has_any_light(stage)

        UsdLux.DomeLight.Define(stage, "/World/DomeLight")
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=(),
                resynced_paths=("/World/DomeLight",),
            )
        )

        assert "old-root" not in adapter._renderer.removed
        assert "old-session" in adapter._renderer.removed
        assert adapter._renderer.opened_strings == []
        assert adapter._renderer.added_usd == []
        assert adapter._usd_handle == "old-root"
        assert adapter._session_handle.startswith("reference-")
        assert adapter._live_resync_handles == ["session-0"]
        assert 'def DomeLight "DomeLight"' in adapter._renderer.added_layers[0][0]
        assert adapter._renderer.added_layers[0][1] is None

    def test_repeated_geometry_property_changes_reload_each_snapshot(self):
        _, _, _Usd, UsdGeom, _ = _usd_modules()
        stage, _cube = self._stage_with_cube()
        adapter = _live_adapter(stage)

        UsdGeom.Sphere.Define(stage, "/World/Sphere")
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=(),
                resynced_paths=("/World/Sphere",),
            )
        )
        stage.GetPrimAtPath("/World/Sphere").GetAttribute("radius").Set(2.5)
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=("/World/Sphere.radius",),
                resynced_paths=(),
            )
        )

        assert len(adapter._renderer.opened_strings) == 1
        assert "double radius = 2.5" in adapter._renderer.opened_strings[0]
        assert 'def Sphere "Sphere"' in adapter._renderer.added_layers[0][0]

    def test_file_backed_stage_reload_uses_root_file_path(self, tmp_path):
        _, _, Usd, UsdGeom, _ = _usd_modules()
        stage_path = tmp_path / "file_backed_reload.usda"
        stage = Usd.Stage.CreateNew(str(stage_path))
        UsdGeom.Cube.Define(stage, "/World/Cube")
        stage.GetRootLayer().Save()
        adapter = _live_adapter(stage)
        adapter._usd_handle = "old-root"
        adapter._session_handle = "old-session"
        adapter._scene_has_lights = mod._stage_has_any_light(stage)

        UsdGeom.Sphere.Define(stage, "/World/Sphere")
        stage.GetRootLayer().Save()
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=(),
                resynced_paths=("/World/Sphere",),
            )
        )

        assert adapter._renderer.removed == []
        assert adapter._renderer.opened_strings == []
        assert adapter._renderer.added_usd == []
        assert adapter._renderer.added_layers[-1][1] is None
        assert 'def Sphere "Sphere"' in adapter._renderer.added_layers[-1][0]
        assert adapter._session_handle == "old-session"

    def test_dirty_file_backed_stage_reload_uses_live_snapshot(self, tmp_path):
        _, _, Usd, UsdGeom, _ = _usd_modules()
        stage_path = tmp_path / "dirty_file_backed_reload.usda"
        stage = Usd.Stage.CreateNew(str(stage_path))
        UsdGeom.Cube.Define(stage, "/World/Cube")
        stage.GetRootLayer().Save()
        adapter = _live_adapter(stage)
        adapter._usd_handle = "old-root"
        adapter._session_handle = "old-session"
        adapter._scene_has_lights = mod._stage_has_any_light(stage)

        UsdGeom.Sphere.Define(stage, "/World/UnsavedSphere")
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=(),
                resynced_paths=("/World/UnsavedSphere",),
            )
        )

        assert adapter._renderer.added_usd == []
        assert adapter._renderer.opened_strings == []
        assert adapter._renderer.added_layers[-1][1] is None
        assert 'def Sphere "UnsavedSphere"' in adapter._renderer.added_layers[-1][0]
        assert adapter._session_handle == "old-session"

    def test_session_layer_reinjection_falls_back_to_layer_add(self):
        stage, _cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        adapter._renderer = _ReferenceFailingFakeRenderer()

        handle = adapter._add_ovrtx_session_layer("#usda 1.0\n")

        assert handle == "session-0"
        assert adapter._renderer.added_layers == [
            ("#usda 1.0\n", mod._SESSION_ROOT_PATH, "session-0")
        ]

    def test_visibility_property_sync_keeps_existing_backend(self):
        stage, cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        adapter._usd_handle = mod._ROOT_STAGE_SENTINEL
        adapter._session_handle = "old-session"
        old_renderer = adapter._renderer

        _, _, _Usd, UsdGeom, _ = _usd_modules()
        UsdGeom.Imageable(cube.GetPrim()).CreateVisibilityAttr().Set(UsdGeom.Tokens.invisible)
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=("/World/Cube.visibility",),
                resynced_paths=(),
            )
        )

        assert old_renderer.reset_calls == 0
        assert old_renderer.removed == []
        assert adapter._renderer is old_renderer
        assert adapter._usd_handle is mod._ROOT_STAGE_SENTINEL
        assert adapter._session_handle == "old-session"
        assert any(
            args == (["/World/Cube"], "visibility", ["invisible"])
            for args, _kwargs in old_renderer.write_calls
        )

    def test_light_property_change_reloads_root_snapshot(self):
        _, _, _Usd, _UsdGeom, _ = _usd_modules()
        from pxr import UsdLux

        stage, _cube = self._stage_with_cube()
        light = UsdLux.DistantLight.Define(stage, "/World/Sun")
        light.CreateIntensityAttr(500.0)
        adapter = _live_adapter(stage)
        adapter._usd_handle = "old-root"

        light.GetIntensityAttr().Set(0.0)
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=("/World/Sun.inputs:intensity",),
                resynced_paths=(),
            )
        )

        assert adapter._renderer.opened_strings
        assert 'def DistantLight "Sun"' in adapter._renderer.opened_strings[-1]
        assert "float inputs:intensity = 0" in adapter._renderer.opened_strings[-1]
        assert adapter._renderer.write_calls == []

    def test_session_fallback_light_does_not_count_as_scene_light(self):
        _, Sdf, Usd, _UsdGeom, _ = _usd_modules()
        from pxr import UsdLux

        stage = Usd.Stage.CreateInMemory()
        UsdLux.DomeLight.Define(
            stage,
            Sdf.Path(f"{mod._SESSION_ROOT_PATH}/Lights/FallbackDome"),
        )

        assert mod._stage_has_any_light(stage) is False

        stage.SetEditTarget(stage.GetSessionLayer())
        UsdLux.DistantLight.Define(stage, "/World/SessionOnlyUserLight")

        assert mod._stage_has_any_light(stage) is False

        stage.SetEditTarget(stage.GetRootLayer())
        UsdLux.DistantLight.Define(stage, "/World/UserLight")

        assert mod._stage_has_any_light(stage) is True

    def test_transform_property_change_stays_on_live_write_path(self, monkeypatch):
        stage, cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)

        cube.GetPrim().GetAttribute("xformOp:translate").Set((4.0, 5.0, 6.0))
        adapter.notify_stage_changed(
            SimpleNamespace(
                changed_paths=("/World/Cube.xformOp:translate",),
                resynced_paths=(),
            )
        )

        assert adapter._renderer.added_usd == []
        assert adapter._renderer.removed == []
        assert any(
            kwargs.get("prim_paths") == ["/World/Cube"]
            and kwargs.get("attribute_name") == "omni:xform"
            for _args, kwargs in adapter._renderer.write_calls
        )


class TestLiveLocalTransformPreview:
    @staticmethod
    def _stage_with_cube():
        _, _, Usd, UsdGeom, _ = _usd_modules()
        stage = Usd.Stage.CreateInMemory()
        cube = UsdGeom.Cube.Define(stage, "/World/Cube")
        cube.CreateSizeAttr(1.0)
        cube.AddTranslateOp().Set((1.0, 2.0, 3.0))
        return stage, cube

    @staticmethod
    def _layer_state(stage):
        return (
            stage.GetRootLayer().ExportToString(),
            stage.GetSessionLayer().ExportToString(),
        )

    @staticmethod
    def _preview_matrix(x: float, y: float, z: float):
        matrix = np.eye(4, dtype=np.float64)
        matrix[3, 0] = x
        matrix[3, 1] = y
        matrix[3, 2] = z
        return matrix

    @staticmethod
    def _xform_writes(adapter):
        return [
            kwargs
            for _args, kwargs in adapter._renderer.write_calls
            if kwargs.get("attribute_name") == "omni:xform"
        ]

    def test_supports_live_local_transform_requires_ovrtx_writer(self, monkeypatch):
        stage, _cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)

        assert adapter.supports_live_local_transform is True

        adapter._renderer = None
        assert adapter.supports_live_local_transform is False

        adapter._renderer = _FakeRenderer()
        monkeypatch.setattr(mod, "_ovrtx", None)
        assert adapter.supports_live_local_transform is False

    def test_set_live_local_transform_writes_ovrtx_without_authoring_usd(
        self, monkeypatch
    ):
        stage, cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)
        before_layers = self._layer_state(stage)
        before_translate = cube.GetPrim().GetAttribute("xformOp:translate").Get()
        preview = self._preview_matrix(9.0, 8.0, 7.0)

        accepted = adapter.set_live_local_transform("/World/Cube", preview)

        assert accepted is True
        assert self._layer_state(stage) == before_layers
        assert cube.GetPrim().GetAttribute("xformOp:translate").Get() == before_translate
        writes = self._xform_writes(adapter)
        assert len(writes) == 1
        assert writes[-1]["prim_paths"] == ["/World/Cube"]
        assert writes[-1]["semantic"] == _FakeSemantic.XFORM_MAT4x4
        tensor = writes[-1]["tensor"]
        assert tensor.dtype == np.float64
        assert tensor.flags["C_CONTIGUOUS"] is True
        np.testing.assert_allclose(tensor[0], preview)

    def test_clear_live_local_transforms_restores_authoritative_usd_transform(
        self, monkeypatch
    ):
        stage, cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)
        before_layers = self._layer_state(stage)
        before_translate = cube.GetPrim().GetAttribute("xformOp:translate").Get()
        preview = self._preview_matrix(9.0, 8.0, 7.0)
        assert adapter.set_live_local_transform("/World/Cube", preview) is True

        result = adapter.clear_live_local_transforms(["/World/Cube"])

        assert result is None
        assert self._layer_state(stage) == before_layers
        assert cube.GetPrim().GetAttribute("xformOp:translate").Get() == before_translate
        writes = self._xform_writes(adapter)
        assert len(writes) == 2
        assert writes[-1]["prim_paths"] == ["/World/Cube"]
        assert writes[-1]["semantic"] == _FakeSemantic.XFORM_MAT4x4
        tensor = writes[-1]["tensor"]
        np.testing.assert_allclose(tensor[0, 3, :3], [1.0, 2.0, 3.0])

    def test_set_live_local_transform_declines_when_writer_unavailable(
        self, monkeypatch
    ):
        stage, _cube = self._stage_with_cube()
        adapter = _live_adapter(stage)
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)
        adapter._renderer = SimpleNamespace()

        assert adapter.supports_live_local_transform is False
        assert (
            adapter.set_live_local_transform(
                "/World/Cube", self._preview_matrix(9.0, 8.0, 7.0)
            )
            is False
        )


class TestPointCloudOutputCatalog:
    @staticmethod
    def _catalog_by_product():
        adapter = _live_adapter(_point_cloud_fixture_stage())
        catalog = adapter.list_point_cloud_outputs()
        return {output.render_product_path: output for output in catalog.outputs}

    @staticmethod
    def _warning_codes(output):
        return {warning.code for warning in output.warnings}

    def test_lists_lidar_and_radar_point_cloud_descriptors(self):
        by_product = self._catalog_by_product()

        assert set(by_product) == {
            "/Render/Products/LidarProduct",
            "/Render/Products/RadarProduct",
            "/Render/Products/CoordinatesOnlyProduct",
            "/Render/Products/UnknownChannelProduct",
            "/Render/Products/NoChannelsProduct",
            "/Render/Products/MissingSourceProduct",
        }
        lidar = by_product["/Render/Products/LidarProduct"]
        assert lidar.source_sensor_path == "/World/RoofLidar"
        assert lidar.source_sensor_name == "RoofLidar"
        assert lidar.source_sensor_type == "OmniLidar"
        assert lidar.coordinate_space is PointCloudCoordinateSpace.WORLD
        assert lidar.channel_names == (
            "Coordinates",
            "Intensity",
            "TimeOffsetNs",
            "Counts",
            "Flags",
        )
        assert (
            lidar.channel("Coordinates").semantic
            is PointCloudChannelSemantic.COORDINATES
        )
        assert lidar.channel("Coordinates").component_count == 3
        assert (
            lidar.channel("Intensity").color_modes
            == (PointCloudColorMode.INTENSITY,)
        )
        assert lidar.supports_color_mode(PointCloudColorMode.RANGE)
        assert lidar.supports_color_mode(PointCloudColorMode.INTENSITY)
        assert "point_cloud_world_points" in lidar.capabilities
        assert "point_cloud_validity" in lidar.capabilities
        assert lidar.enabled
        assert lidar.disabled_reason == ""

        radar = by_product["/Render/Products/RadarProduct"]
        assert radar.source_sensor_path == "/World/FrontRadar"
        assert radar.source_sensor_type == "OmniRadar"
        assert radar.coordinate_space is PointCloudCoordinateSpace.SENSOR
        assert radar.channel_names == (
            "Coordinates",
            "RCS",
            "RadialVelocityMs",
        )
        assert radar.channel("RCS").semantic is PointCloudChannelSemantic.RCS
        assert (
            radar.channel("RadialVelocityMs").semantic
            is PointCloudChannelSemantic.RADIAL_VELOCITY
        )
        assert radar.supports_color_mode(PointCloudColorMode.RCS)
        assert radar.supports_color_mode(PointCloudColorMode.VELOCITY)
        assert "point_cloud_sensor_frame" in radar.capabilities
        assert not radar.enabled
        assert radar.disabled_reason == (
            "Radar PointCloud output is disabled because the current ovrtx radar "
            "sensor runtime aborts during initialization."
        )
        assert "unsafe_sensor_runtime" in self._warning_codes(radar)

    def test_filtering_by_render_product_path_returns_one_output(self):
        adapter = _live_adapter(_point_cloud_fixture_stage())

        catalog = adapter.list_point_cloud_outputs("/Render/Products/RadarProduct")

        assert len(catalog.outputs) == 1
        assert catalog.outputs[0].render_product_path == "/Render/Products/RadarProduct"
        assert catalog.active_render_product_path == mod._RENDER_PRODUCT_PATH

    def test_malformed_product_does_not_abort_catalog(self, monkeypatch):
        adapter = _live_adapter(_point_cloud_fixture_stage())
        original_targets = mod._point_cloud_ordered_var_targets

        def raise_for_lidar(product):
            if str(product.GetPrim().GetPath()) == "/Render/Products/LidarProduct":
                raise RuntimeError("malformed product")
            return original_targets(product)

        monkeypatch.setattr(mod, "_point_cloud_ordered_var_targets", raise_for_lidar)

        catalog = adapter.list_point_cloud_outputs()
        by_product = {output.render_product_path: output for output in catalog.outputs}

        assert "/Render/Products/LidarProduct" not in by_product
        assert not by_product["/Render/Products/RadarProduct"].enabled
        assert not by_product["/Render/Products/CoordinatesOnlyProduct"].enabled

    def test_missing_optional_channels_keep_descriptor_metadata(self):
        output = self._catalog_by_product()["/Render/Products/CoordinatesOnlyProduct"]

        assert output.channel("Coordinates") is not None
        assert output.channel("Intensity") is None
        assert output.channel_names == ("Coordinates",)
        assert not output.enabled
        assert output.disabled_reason == "PointCloud output has no Counts channel."
        assert "missing_counts" in self._warning_codes(output)

    def test_unknown_channel_maps_to_unknown_semantic_with_warning(self):
        output = self._catalog_by_product()["/Render/Products/UnknownChannelProduct"]

        unknown = output.channel("MysterySignal")
        assert unknown is not None
        assert unknown.semantic is PointCloudChannelSemantic.UNKNOWN
        assert "unknown_channel" in self._warning_codes(output)
        assert not output.enabled
        assert output.disabled_reason == "PointCloud output has no Counts channel."
        assert "missing_counts" in self._warning_codes(output)

    def test_missing_channels_disable_descriptor_without_crashing(self):
        output = self._catalog_by_product()["/Render/Products/NoChannelsProduct"]

        assert output.channel_names == ()
        assert not output.enabled
        assert output.disabled_reason == "PointCloud output has no Coordinates channel."
        assert self._warning_codes(output) == {
            "missing_channels",
            "missing_coordinates",
        }

    def test_missing_source_metadata_disables_descriptor_with_warning(self):
        output = self._catalog_by_product()["/Render/Products/MissingSourceProduct"]

        assert output.source_sensor_path == "/World/MissingSensor"
        assert output.source_sensor_name == ""
        assert output.source_sensor_type == ""
        assert not output.enabled
        assert output.disabled_reason == "PointCloud output has no valid source sensor."
        assert "missing_source" in self._warning_codes(output)

    def test_livestream_scene_exposes_point_cloud_and_depth_outputs(self):
        _, _, _, UsdGeom, _ = _usd_modules()
        stage = _livestream_fixture_stage()
        adapter = _live_adapter(stage)

        lidar = stage.GetPrimAtPath("/World/RoofLidar")
        sensor = stage.GetPrimAtPath("/World/RoofLidar/Sensor")
        assert bool(UsdGeom.Xformable(lidar))
        assert not bool(UsdGeom.Xformable(sensor))

        point_cloud = adapter.list_point_cloud_outputs("/Render/Products/RoofLidar")
        assert len(point_cloud.outputs) == 1
        lidar_output = point_cloud.outputs[0]
        assert lidar_output.enabled
        assert lidar_output.source_sensor_path == "/World/RoofLidar/Sensor"
        assert lidar_output.source_sensor_type == "OmniLidar"
        assert lidar_output.channel_names == (
            "Coordinates",
            "Intensity",
            "Counts",
            "Flags",
            "TimeOffsetNs",
        )

        render_vars = adapter.list_render_var_outputs("/Render/Products/MainCamera")
        scalar_outputs = [
            output
            for output in render_vars.outputs
            if output.output_kind is RenderVarOutputKind.SCALAR_DEPTH
        ]
        assert [
            (output.render_product_path, output.render_var_name)
            for output in scalar_outputs
        ] == [
            ("/Render/Products/MainCamera", "DistanceToCameraSD"),
        ]
        assert scalar_outputs[0].enabled
        assert scalar_outputs[0].units == "m"

    def test_livestream_lidar_wrapper_is_movable(self):
        _, _, _, UsdGeom, _ = _usd_modules()
        stage = _livestream_fixture_stage()
        lidar = stage.GetPrimAtPath("/World/RoofLidar")
        sensor = stage.GetPrimAtPath("/World/RoofLidar/Sensor")
        lidar_xform = UsdGeom.Xformable(lidar)
        assert bool(lidar_xform)
        assert sensor and sensor.IsValid()
        assert sensor.GetTypeName() == "OmniLidar"

        before = lidar_xform.ComputeLocalToWorldTransform(0)
        translate_attr = lidar.GetAttribute("xformOp:translate")
        translate_attr.Set((2.0, 0.0, 1.0))

        after = lidar_xform.ComputeLocalToWorldTransform(0)
        assert before.ExtractTranslation() != after.ExtractTranslation()
        assert after.ExtractTranslation()[0] == pytest.approx(2.0)


class TestRenderVarOutputCatalog:
    @staticmethod
    def _catalog(render_product_path=None):
        adapter = _live_adapter(_render_var_fixture_stage())
        return adapter.list_render_var_outputs(render_product_path)

    @staticmethod
    def _outputs_by_name(catalog):
        return {
            (output.render_product_path, output.render_var_name): output
            for output in catalog.outputs
        }

    @staticmethod
    def _warning_codes(target):
        return {warning.code for warning in target.warnings}

    def test_lists_known_non_ldr_render_var_descriptors(self):
        catalog = self._catalog()
        by_name = self._outputs_by_name(catalog)

        assert ("/Render/Products/ImageOnlyProduct", "LdrColor") not in by_name
        hdr = by_name[("/Render/Products/HdrProduct", "HdrColor")]
        assert hdr.output_kind is RenderVarOutputKind.HDR_COLOR
        assert hdr.dtype == "float16"
        assert hdr.shape == (480, 640, 4)
        assert hdr.component_count == 4
        assert hdr.color_space == "linear"
        assert hdr.supports_preset(RenderVarPresetKind.HDR_TONEMAP)
        assert "render_var_hdr" in hdr.capabilities
        assert hdr.enabled

        albedo = by_name[("/Render/Products/AlbedoProduct", "DiffuseAlbedoSD")]
        assert albedo.output_kind is RenderVarOutputKind.HDR_COLOR
        assert albedo.dtype == "float16"
        assert albedo.shape == (480, 640, 4)
        assert albedo.color_space == "linear"
        assert albedo.supports_preset(RenderVarPresetKind.HDR_TONEMAP)
        assert "render_var_hdr" in albedo.capabilities
        assert albedo.enabled

        depth = by_name[("/Render/Products/ScalarProduct", "DepthSD")]
        assert depth.output_kind is RenderVarOutputKind.SCALAR_DEPTH
        assert depth.dtype == "float32"
        assert depth.shape == (480, 640, 1)
        assert depth.units == "unitless"
        assert depth.value_range == (0.0, 1.0)
        assert depth.supports_preset(RenderVarPresetKind.SCALAR_GRAYSCALE)

        distance = by_name[(
            "/Render/Products/ScalarProduct",
            "DistanceToCameraSD",
        )]
        assert distance.output_kind is RenderVarOutputKind.SCALAR_DEPTH
        assert distance.units == "m"

        normal = by_name[("/Render/Products/VectorProduct", "NormalSD")]
        assert normal.output_kind is RenderVarOutputKind.VECTOR_NORMAL
        assert normal.component_count == 4
        assert normal.value_range == (-1.0, 1.0)
        assert normal.supports_preset(RenderVarPresetKind.VECTOR_SIGNED)
        assert "render_var_vector" in normal.capabilities

        semantic = by_name[(
            "/Render/Products/CategoricalProduct",
            "SemanticSegmentation",
        )]
        assert semantic.output_kind is RenderVarOutputKind.CATEGORICAL_MASK
        assert semantic.dtype == "uint32"
        assert semantic.shape == (480, 640, 1)
        assert semantic.supports_preset(RenderVarPresetKind.CATEGORICAL_PALETTE)

        id_map = by_name[("/Render/Products/CategoricalProduct", "SemanticIdMap")]
        assert id_map.output_kind is RenderVarOutputKind.METADATA_MAP
        assert id_map.dtype == "uint8"
        assert id_map.shape == ()
        assert "render_var_metadata" in id_map.capabilities

    def test_filtering_by_render_product_path_returns_only_that_product(self):
        catalog = self._catalog("/Render/Products/ScalarProduct")

        assert [output.render_product_path for output in catalog.outputs] == [
            "/Render/Products/ScalarProduct",
            "/Render/Products/ScalarProduct",
            "/Render/Products/ScalarProduct",
        ]
        assert {
            output.render_var_name
            for output in catalog.outputs
        } == {
            "DepthSD",
            "DistanceToCameraSD",
            "DistanceToImagePlaneSD",
        }
        assert catalog.active_render_product_path == mod._RENDER_PRODUCT_PATH

    def test_ldr_only_product_returns_empty_catalog(self):
        catalog = self._catalog("/Render/Products/ImageOnlyProduct")

        assert catalog.outputs == ()
        assert catalog.warnings == ()

    def test_unknown_output_returns_disabled_unknown_descriptor(self):
        catalog = self._catalog("/Render/Products/MixedProduct")
        by_kind = {output.output_kind: output for output in catalog.outputs}

        assert RenderVarOutputKind.HDR_COLOR in by_kind
        unknown = by_kind[RenderVarOutputKind.UNKNOWN]
        assert unknown.render_var_name == "MysteryAov"
        assert not unknown.enabled
        assert unknown.disabled_reason == "RenderVar output 'MysteryAov' is not recognized."
        assert "unknown_output" in self._warning_codes(unknown)

    def test_missing_render_var_target_returns_disabled_descriptor(self):
        catalog = self._catalog("/Render/Products/MissingVarProduct")

        assert len(catalog.outputs) == 1
        missing = catalog.outputs[0]
        assert missing.output_kind is RenderVarOutputKind.UNKNOWN
        assert not missing.enabled
        assert "missing_render_var" in self._warning_codes(missing)
        assert missing.metadata["render_var_path"] == "/Render/Vars/DoesNotExist"

    def test_product_without_ordered_vars_returns_empty_catalog_warning(self):
        catalog = self._catalog("/Render/Products/EmptyProduct")

        assert catalog.outputs == ()
        assert "missing_output" in self._warning_codes(catalog)

    def test_malformed_output_does_not_abort_catalog(self, monkeypatch):
        adapter = _live_adapter(_render_var_fixture_stage())
        original_descriptor = mod._render_var_output_descriptor

        def raise_for_hdr(stage, product, product_path, var_path):
            if str(var_path) == "/Render/Vars/HdrColor":
                raise RuntimeError("malformed render var")
            return original_descriptor(stage, product, product_path, var_path)

        monkeypatch.setattr(mod, "_render_var_output_descriptor", raise_for_hdr)

        catalog = adapter.list_render_var_outputs("/Render/Products/MixedProduct")

        assert [output.render_var_name for output in catalog.outputs] == ["MysteryAov"]
        assert catalog.outputs[0].output_kind is RenderVarOutputKind.UNKNOWN

    def test_stage_without_render_vars_returns_empty_catalog(self):
        adapter = _live_adapter(None)

        catalog = adapter.list_render_var_outputs()

        assert catalog.outputs == ()
        assert catalog.active_render_product_path == ""


class TestRenderSettingsCatalog:
    @staticmethod
    def _adapter(active_path="/Render/Products/PrimaryProduct"):
        adapter = _live_adapter(_render_settings_fixture_stage())
        adapter._render_product_path = active_path
        return adapter

    @staticmethod
    def _settings_by_property(catalog):
        return {
            setting.property_name: setting
            for setting in catalog.settings
        }

    @staticmethod
    def _warning_codes(target):
        return {warning.code for warning in target.warnings}

    def test_lists_public_render_product_settings_for_active_target(self):
        catalog = self._adapter().list_render_settings()
        by_property = self._settings_by_property(catalog)

        assert catalog.active_render_product_path == "/Render/Products/PrimaryProduct"
        assert catalog.active_render_product_label == "PrimaryProduct"
        assert catalog.providers[0].provider_id == "openusd.render_product.public"
        assert catalog.providers[0].capabilities == (
            "render_settings_catalog",
            "render_settings_value_state",
        )
        assert [group.group_id for group in catalog.groups] == [
            "quality",
            "tone",
            "unsupported",
        ]
        assert set(by_property) == {
            "samples",
            "qualityMode",
            "exposure",
            "experimental",
            "badMatrix",
            "rtpt:maxBounces",
            "rendermode",
            "rt:ambientLight:intensity",
            "minimal:constantColor",
        }
        assert "debugOnly" not in by_property

    def test_authored_setting_has_value_state_default_constraints_and_requirement(self):
        catalog = self._adapter().list_render_settings()
        samples = self._settings_by_property(catalog)["samples"]

        assert samples.label == "Sample Count"
        assert samples.namespace == "omni:rtx:"
        assert samples.value_type is RenderSettingValueType.INT
        assert samples.units == "samples"
        assert samples.default_value == 4
        assert samples.has_default
        assert samples.requirement is RenderSettingRequirement.WARMUP
        assert samples.constraints.soft_range == (1.0, 128.0)
        assert samples.constraints.hard_range == (1.0, 4096.0)
        assert samples.value_state.current_value == 16
        assert samples.value_state.default_value == 4
        assert samples.value_state.authored
        assert not samples.value_state.inherited
        assert samples.value_state.resettable
        assert samples.resettable

    def test_token_setting_uses_allowed_tokens_as_enum_constraints(self):
        catalog = self._adapter().list_render_settings()
        quality = self._settings_by_property(catalog)["qualityMode"]

        assert quality.value_type is RenderSettingValueType.ENUM
        assert quality.constraints.allowed_values == ("draft", "balanced", "final")
        assert quality.value_state.current_value == "balanced"
        assert quality.value_state.authored

    def test_default_metadata_setting_reports_inherited_state(self):
        catalog = self._adapter().list_render_settings()
        exposure = self._settings_by_property(catalog)["exposure"]

        assert exposure.value_type is RenderSettingValueType.FLOAT
        assert exposure.default_value == 1.25
        assert exposure.has_default
        assert exposure.requirement is RenderSettingRequirement.RENDERER_RESTART
        assert exposure.value_state.current_value == 1.25
        assert exposure.value_state.default_value == 1.25
        assert not exposure.value_state.authored
        assert exposure.value_state.inherited
        assert not exposure.resettable

    def test_disabled_setting_reports_disabled_state_and_reason(self):
        catalog = self._adapter().list_render_settings()
        experimental = self._settings_by_property(catalog)["experimental"]

        assert experimental.value_type is RenderSettingValueType.BOOL
        assert not experimental.enabled
        assert experimental.disabled_reason == "Experimental setting is not public yet."
        assert experimental.value_state.disabled
        assert experimental.value_state.disabled_reason == (
            "Experimental setting is not public yet."
        )
        assert not experimental.value_state.resettable

    def test_unknown_schema_property_is_disabled_with_warning(self):
        catalog = self._adapter().list_render_settings()
        unknown = self._settings_by_property(catalog)["badMatrix"]

        assert unknown.value_type is RenderSettingValueType.UNKNOWN
        assert not unknown.enabled
        assert "unknown_value_type" in self._warning_codes(unknown)
        assert unknown.value_state.invalid
        assert unknown.value_state.disabled

    def test_valid_product_without_authored_settings_returns_builtin_defaults(self):
        catalog = self._adapter("/Render/Products/EmptyProduct").list_render_settings()
        by_property = self._settings_by_property(catalog)

        assert catalog.active_render_product_path == "/Render/Products/EmptyProduct"
        assert catalog.providers[0].provider_id == "openusd.render_product.public"
        assert [group.group_id for group in catalog.groups] == ["quality", "tone"]
        assert set(by_property) == {
            "rtpt:maxBounces",
            "rendermode",
            "rt:ambientLight:intensity",
            "minimal:constantColor",
        }
        max_bounces = by_property["rtpt:maxBounces"]
        assert max_bounces.value_state.current_value == 3
        assert max_bounces.value_state.default_value == 3
        assert not max_bounces.value_state.authored
        assert max_bounces.value_state.inherited
        assert not max_bounces.resettable
        assert max_bounces.constraints.hard_range == (0.0, 32.0)
        assert max_bounces.requirement is RenderSettingRequirement.WARMUP
        color = by_property["minimal:constantColor"]
        assert color.value_type is RenderSettingValueType.COLOR
        assert color.constraints.component_count == 3
        assert color.value_state.current_value == (0.0, 0.0, 0.0)

    def test_missing_targets_return_empty_catalogs(self):
        missing = self._adapter("/Render/Products/MissingProduct").list_render_settings()
        no_active = self._adapter("").list_render_settings()
        no_stage = _live_adapter(None).list_render_settings()

        assert missing.settings == ()
        assert missing.active_render_product_path == "/Render/Products/MissingProduct"
        assert no_active.settings == ()
        assert no_active.active_render_product_path == ""
        assert no_stage.settings == ()

    def test_malformed_product_resolution_returns_empty_catalog_without_raising(self):
        adapter = self._adapter("/Render/Products/PrimaryProduct")

        class RaisingStage:
            def GetPrimAtPath(self, path):
                raise RuntimeError("synthetic malformed path failure")

        adapter._stage = RaisingStage()

        catalog = adapter.list_render_settings("/Render/Products/PrimaryProduct")

        assert catalog.settings == ()
        assert catalog.active_render_product_path == "/Render/Products/PrimaryProduct"

    def test_explicit_render_product_path_overrides_active_target(self):
        adapter = self._adapter("/Render/Products/MissingProduct")

        catalog = adapter.list_render_settings("/Render/Products/PrimaryProduct")

        assert catalog.active_render_product_path == "/Render/Products/PrimaryProduct"
        assert {setting.property_name for setting in catalog.settings} >= {"samples"}

    def test_malformed_setting_does_not_abort_catalog(self, monkeypatch):
        adapter = self._adapter()
        original_descriptor = mod._render_setting_descriptor

        def raise_for_samples(product_path, attr):
            if str(attr.GetName()) == "omni:rtx:samples":
                raise RuntimeError("synthetic setting failure")
            return original_descriptor(product_path, attr)

        monkeypatch.setattr(mod, "_render_setting_descriptor", raise_for_samples)

        catalog = adapter.list_render_settings()
        by_property = self._settings_by_property(catalog)

        assert "samples" not in by_property
        assert "qualityMode" in by_property
        assert "setting_failed" in self._warning_codes(catalog)


class TestRenderSettingsWriteBehavior:
    @staticmethod
    def _adapter(active_path="/Render/Products/PrimaryProduct"):
        return TestRenderSettingsCatalog._adapter(active_path)

    @staticmethod
    def _settings_by_property(catalog):
        return TestRenderSettingsCatalog._settings_by_property(catalog)

    @staticmethod
    def _attr(adapter, attr_name, product_path="/Render/Products/PrimaryProduct"):
        prim = adapter._stage.GetPrimAtPath(product_path)
        assert prim.IsValid()
        attr = prim.GetAttribute(attr_name)
        assert attr.IsValid()
        return attr

    def test_validate_normalizes_without_writing(self):
        adapter = self._adapter()
        samples = self._settings_by_property(
            adapter.list_render_settings()
        )["samples"]
        attr = self._attr(adapter, "omni:rtx:samples")

        result = adapter.validate_render_setting(
            samples.setting_id,
            "32",
            render_product_path="/Render/Products/PrimaryProduct",
        )

        assert result.accepted
        assert result.normalized_value == 32
        assert result.requirement is RenderSettingRequirement.WARMUP
        assert attr.Get() == 16

    def test_apply_valid_value_authors_value_and_updates_state(self):
        adapter = self._adapter()
        samples = self._settings_by_property(
            adapter.list_render_settings()
        )["samples"]

        result = adapter.apply_render_setting(
            samples.setting_id,
            "32",
            render_product_path="/Render/Products/PrimaryProduct",
        )

        assert result.accepted
        assert result.current_value == 32
        assert result.value_state.current_value == 32
        assert result.value_state.authored
        assert not result.value_state.inherited
        assert self._attr(adapter, "omni:rtx:samples").Get() == 32
        args, kwargs = adapter._renderer.write_calls[-1]
        assert args == ()
        assert kwargs["prim_paths"] == ["/Render/Products/PrimaryProduct"]
        assert kwargs["attribute_name"] == "omni:rtx:samples"
        np.testing.assert_array_equal(kwargs["tensor"], np.asarray([32], dtype=np.int32))
        assert adapter._renderer.live_reset_calls == 1
        assert adapter._session_handle is not None

    def test_apply_builtin_default_setting_creates_public_attr(self):
        adapter = self._adapter("/Render/Products/EmptyProduct")
        ambient = self._settings_by_property(
            adapter.list_render_settings()
        )["rt:ambientLight:intensity"]
        prim = adapter._stage.GetPrimAtPath("/Render/Products/EmptyProduct")
        assert not prim.GetAttribute("omni:rtx:rt:ambientLight:intensity").IsValid()

        result = adapter.apply_render_setting(
            ambient.setting_id,
            "2500",
            render_product_path="/Render/Products/EmptyProduct",
        )

        attr = prim.GetAttribute("omni:rtx:rt:ambientLight:intensity")
        assert result.accepted
        assert attr.IsValid()
        assert attr.Get() == 2500.0
        assert attr.HasAuthoredValue()
        assert result.value_state.authored
        catalog = adapter.list_render_settings("/Render/Products/EmptyProduct")
        assert (
            self._settings_by_property(catalog)[
                "rt:ambientLight:intensity"
            ].default_value
            == 0.0
        )
        args, kwargs = adapter._renderer.write_calls[-1]
        assert args == ()
        assert kwargs["prim_paths"] == ["/Render/Products/EmptyProduct"]
        assert kwargs["attribute_name"] == "omni:rtx:rt:ambientLight:intensity"
        np.testing.assert_array_equal(
            kwargs["tensor"],
            np.asarray([2500.0], dtype=np.float32),
        )
        assert adapter._renderer.live_reset_calls == 1

    def test_apply_builtin_enum_setting_creates_attr_and_restarts_renderer(self):
        adapter = self._adapter("/Render/Products/EmptyProduct")
        render_mode = self._settings_by_property(
            adapter.list_render_settings()
        )["rendermode"]
        prim = adapter._stage.GetPrimAtPath("/Render/Products/EmptyProduct")
        assert not prim.GetAttribute("omni:rtx:rendermode").IsValid()

        result = adapter.apply_render_setting(
            render_mode.setting_id,
            "Minimal",
            render_product_path="/Render/Products/EmptyProduct",
        )

        attr = prim.GetAttribute("omni:rtx:rendermode")
        assert result.accepted
        assert attr.IsValid()
        assert attr.Get() == "Minimal"
        assert attr.HasAuthoredValue()
        assert adapter._renderer.write_calls == []
        assert adapter._renderer.opened_strings
        assert 'string omni:rtx:rendermode = "Minimal"' in (
            adapter._renderer.opened_strings[-1]
        )
        assert adapter._renderer.added_layers[-1][1] == mod._SESSION_ROOT_PATH

    def test_apply_builtin_color_setting_creates_attr_and_live_write(self):
        adapter = self._adapter("/Render/Products/EmptyProduct")
        color = self._settings_by_property(
            adapter.list_render_settings()
        )["minimal:constantColor"]
        prim = adapter._stage.GetPrimAtPath("/Render/Products/EmptyProduct")
        assert not prim.GetAttribute("omni:rtx:minimal:constantColor").IsValid()

        result = adapter.apply_render_setting(
            color.setting_id,
            (1.0, 0.0, 0.25),
            render_product_path="/Render/Products/EmptyProduct",
        )

        attr = prim.GetAttribute("omni:rtx:minimal:constantColor")
        assert result.accepted
        assert attr.IsValid()
        assert tuple(attr.Get()) == (1.0, 0.0, 0.25)
        assert attr.HasAuthoredValue()
        args, kwargs = adapter._renderer.write_calls[-1]
        assert args == ()
        assert kwargs["prim_paths"] == ["/Render/Products/EmptyProduct"]
        assert kwargs["attribute_name"] == "omni:rtx:minimal:constantColor"
        np.testing.assert_allclose(
            kwargs["tensor"],
            np.asarray([(1.0, 0.0, 0.25)], dtype=np.float32),
        )
        assert adapter._renderer.live_reset_calls == 1

    def test_apply_owned_render_product_setting_survives_live_reinject(self):
        _, Sdf, Usd, _UsdGeom, UsdRender = _usd_modules()
        stage = Usd.Stage.CreateInMemory()
        UsdRender.Product.Define(stage, mod._RENDER_PRODUCT_PATH)
        adapter = _live_adapter(stage)
        color = self._settings_by_property(
            adapter.list_render_settings(mod._RENDER_PRODUCT_PATH)
        )["minimal:constantColor"]

        result = adapter.apply_render_setting(
            color.setting_id,
            (1.0, 0.0, 0.25),
            render_product_path=mod._RENDER_PRODUCT_PATH,
        )

        assert result.accepted
        assert adapter._renderer.live_reset_calls == 1
        assert adapter._renderer.added_layers
        session_usda = adapter._renderer.added_layers[-1][0]
        assert (
            "color3f omni:rtx:minimal:constantColor = (1.0, 0.0, 0.25)"
            in session_usda
        )
        attr_path = Sdf.Path(
            f"{mod._RENDER_PRODUCT_PATH}.omni:rtx:minimal:constantColor"
        )
        assert stage.GetSessionLayer().GetAttributeAtPath(attr_path) is not None
        assert stage.GetRootLayer().GetAttributeAtPath(attr_path) is None

    def test_rejected_validation_and_apply_do_not_mutate(self):
        adapter = self._adapter()
        samples = self._settings_by_property(
            adapter.list_render_settings()
        )["samples"]
        attr = self._attr(adapter, "omni:rtx:samples")

        validation = adapter.validate_render_setting(
            samples.setting_id,
            5000,
            render_product_path="/Render/Products/PrimaryProduct",
        )
        apply = adapter.apply_render_setting(
            samples.setting_id,
            5000,
            render_product_path="/Render/Products/PrimaryProduct",
        )

        assert not validation.accepted
        assert validation.warning_code == "value_out_of_range"
        assert not apply.accepted
        assert apply.warning_code == "value_out_of_range"
        assert attr.Get() == 16

    def test_enum_validation_rejects_unknown_token_without_mutating(self):
        adapter = self._adapter()
        quality = self._settings_by_property(
            adapter.list_render_settings()
        )["qualityMode"]
        attr = self._attr(adapter, "omni:rtx:qualityMode")

        apply = adapter.apply_render_setting(
            quality.setting_id,
            "ultra",
            render_product_path="/Render/Products/PrimaryProduct",
        )

        assert not apply.accepted
        assert apply.warning_code == "value_not_allowed"
        assert attr.Get() == "balanced"

    def test_failed_backend_write_reports_failure_without_mutating(self, monkeypatch):
        adapter = self._adapter()
        samples = self._settings_by_property(
            adapter.list_render_settings()
        )["samples"]
        attr = self._attr(adapter, "omni:rtx:samples")

        def fail_set(attr, descriptor, normalized_value):
            raise RuntimeError("synthetic write failure")

        monkeypatch.setattr(mod, "_render_setting_set_attr", fail_set)

        result = adapter.apply_render_setting(
            samples.setting_id,
            32,
            render_product_path="/Render/Products/PrimaryProduct",
        )

        assert not result.accepted
        assert result.warning_code == "apply_failed"
        assert attr.Get() == 16

    def test_failed_live_renderer_write_rolls_back_usd_authoring(self):
        adapter = self._adapter("/Render/Products/EmptyProduct")
        ambient = self._settings_by_property(
            adapter.list_render_settings()
        )["rt:ambientLight:intensity"]
        prim = adapter._stage.GetPrimAtPath("/Render/Products/EmptyProduct")
        assert not prim.GetAttribute("omni:rtx:rt:ambientLight:intensity").IsValid()

        def fail_write_attribute(*args, **kwargs):
            raise RuntimeError("synthetic live write failure")

        adapter._renderer.write_attribute = fail_write_attribute

        result = adapter.apply_render_setting(
            ambient.setting_id,
            2500.0,
            render_product_path="/Render/Products/EmptyProduct",
        )

        assert not result.accepted
        assert result.warning_code == "apply_failed"
        attr = prim.GetAttribute("omni:rtx:rt:ambientLight:intensity")
        if attr.IsValid():
            assert not attr.HasAuthoredValue()

    def test_reset_clears_authored_opinion_and_restores_default_state(self):
        adapter = self._adapter()
        exposure = self._settings_by_property(
            adapter.list_render_settings()
        )["exposure"]
        attr = self._attr(adapter, "omni:rtx:exposure")

        apply = adapter.apply_render_setting(
            exposure.setting_id,
            2.5,
            render_product_path="/Render/Products/PrimaryProduct",
        )
        assert apply.accepted
        assert attr.Get() == 2.5
        assert attr.HasAuthoredValue()

        reset = adapter.reset_render_setting(
            exposure.setting_id,
            render_product_path="/Render/Products/PrimaryProduct",
        )

        assert attr.HasAuthoredValue() is False
        assert reset.accepted
        assert reset.reset_value == 1.25
        assert reset.value_state.current_value == 1.25
        assert not reset.value_state.authored
        assert reset.value_state.inherited

    def test_reset_disabled_setting_is_rejected_as_unsupported(self):
        adapter = self._adapter()
        experimental = self._settings_by_property(
            adapter.list_render_settings()
        )["experimental"]

        result = adapter.reset_render_setting(
            experimental.setting_id,
            render_product_path="/Render/Products/PrimaryProduct",
        )

        assert not result.accepted
        assert result.warning_code == "setting_disabled"
        assert self._attr(adapter, "omni:rtx:experimental").Get() is True

    def test_failed_reset_reports_failure_without_mutating(self, monkeypatch):
        adapter = self._adapter()
        exposure = self._settings_by_property(
            adapter.list_render_settings()
        )["exposure"]
        attr = self._attr(adapter, "omni:rtx:exposure")
        adapter.apply_render_setting(
            exposure.setting_id,
            2.5,
            render_product_path="/Render/Products/PrimaryProduct",
        )

        def fail_clear(attr):
            raise RuntimeError("synthetic clear failure")

        monkeypatch.setattr(mod, "_render_setting_clear_attr", fail_clear)

        result = adapter.reset_render_setting(
            exposure.setting_id,
            render_product_path="/Render/Products/PrimaryProduct",
        )

        assert not result.accepted
        assert result.warning_code == "reset_failed"
        assert attr.Get() == 2.5
        assert attr.HasAuthoredValue()

    def test_backend_unavailable_and_unknown_setting_are_typed_rejections(self):
        missing_backend = _live_adapter(None)
        adapter = self._adapter()

        validation = missing_backend.validate_render_setting("samples", 1)
        apply = missing_backend.apply_render_setting("samples", 1)
        reset = missing_backend.reset_render_setting("samples")
        unknown = adapter.apply_render_setting(
            "not-a-setting",
            1,
            render_product_path="/Render/Products/PrimaryProduct",
        )

        assert not validation.accepted
        assert validation.warning_code == "missing_render_product"
        assert not apply.accepted
        assert apply.warning_code == "missing_render_product"
        assert not reset.accepted
        assert reset.warning_code == "missing_render_product"
        assert not unknown.accepted
        assert unknown.warning_code == "unknown_setting"

    def test_soft_range_must_fit_inside_hard_range(self):
        _, Sdf, _, _, _ = _usd_modules()
        adapter = self._adapter()
        prim = adapter._stage.GetPrimAtPath("/Render/Products/PrimaryProduct")
        attr = prim.CreateAttribute(
            "omni:rtx:badSoftRange",
            Sdf.ValueTypeNames.Int,
            custom=True,
        )
        attr.Set(2)
        attr.SetCustomData({
            "renderSettings": {
                "group_id": "quality",
                "label": "Bad Soft Range",
                "range": {"min": 1.0, "max": 5.0},
                "soft_range": {"min": 0.0, "max": 10.0},
            },
        })
        setting = self._settings_by_property(
            adapter.list_render_settings()
        )["badSoftRange"]

        result = adapter.validate_render_setting(
            setting.setting_id,
            2,
            render_product_path="/Render/Products/PrimaryProduct",
        )

        assert not result.accepted
        assert result.warning_code == "invalid_constraints"


class TestRenderVarOutputFrameExtraction:
    @staticmethod
    def _descriptor(
        render_product_path="/Render/Products/HdrProduct",
        render_var_name="HdrColor",
        *,
        enabled=True,
        disabled_reason="",
        shape=(2, 3, 4),
    ):
        return RenderVarOutputDescriptor(
            render_product_path=render_product_path,
            render_var_name=render_var_name,
            output_kind=RenderVarOutputKind.HDR_COLOR,
            dtype="float16",
            shape=shape,
            component_count=4,
            color_space="linear",
            enabled=enabled,
            disabled_reason=disabled_reason,
        )

    @staticmethod
    def _rv(data, *, fail=False, poison_on_unmap=False):
        source = np.array(data, copy=True)
        maps = []

        class Tensor:
            def numpy(self):
                return source

        class Mapping:
            tensor = Tensor()

            def __enter__(self):
                if fail:
                    raise RuntimeError("synthetic map failure")
                return self

            def __exit__(self, exc_type, exc, tb):
                if poison_on_unmap:
                    source[...] = 0
                return False

        class RenderVar:
            def map(self, device=None):
                maps.append(device)
                return Mapping()

        return RenderVar(), maps, source

    @staticmethod
    def _product(render_vars, *, frame_index=17):
        frame_out = type(
            "RenderVarFrameOut",
            (),
            {
                "render_vars": render_vars,
                "frame_index": frame_index,
            },
        )()
        return type("RenderVarProduct", (), {"frames": [frame_out]})()

    @classmethod
    def _products(cls, *, output_vars, output_path="/Render/Products/HdrProduct", image_value=77):
        image = np.full((3, 4, 4), image_value, dtype=np.uint8)
        image_rv, _maps, _source = cls._rv(image)
        return {
            mod._RENDER_PRODUCT_PATH: cls._product(
                {mod._LDR_VAR_NAME: image_rv},
            ),
            output_path: cls._product(output_vars),
        }

    @staticmethod
    def _matrices():
        from ovui_widgets.viewport.camera_controller import CameraController

        return CameraController().get_matrices(4, 3)

    def _adapter_with_descriptors(self, monkeypatch, descriptors):
        adapter = _live_adapter(_render_var_fixture_stage())
        from ovui_data_adapters.openusd._session_authoring import ensure_camera

        ensure_camera(adapter._stage, mod._CAMERA_PATH)
        adapter._clock = lambda: 456.25
        catalog = RenderVarOutputCatalog(
            outputs=tuple(descriptors),
            active_render_product_path=mod._RENDER_PRODUCT_PATH,
        )
        monkeypatch.setattr(
            adapter,
            "list_render_var_outputs",
            lambda _path=None: catalog,
        )
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)
        return adapter

    def test_render_frame_extracts_requested_output_and_keeps_ldr_isolated(
        self,
        monkeypatch,
    ):
        descriptor = self._descriptor()
        adapter = self._adapter_with_descriptors(monkeypatch, (descriptor,))
        request = RenderVarOutputRequest(
            viewport_id="viewport",
            render_product_path=descriptor.render_product_path,
            render_var_name=descriptor.render_var_name,
        )
        result = adapter.set_render_var_output_request("viewport", request)
        assert result.accepted
        assert result.active_request.output_id == descriptor.output_id

        expected = np.arange(2 * 3 * 4, dtype=np.float16).reshape((2, 3, 4))
        output_rv, maps, source = self._rv(expected, poison_on_unmap=True)
        adapter._renderer.step_result = self._products(
            output_vars={"HdrColor": output_rv},
            image_value=9,
        )

        image = adapter.render_frame(4, 3, *self._matrices())
        frame = adapter.get_latest_render_var_output_frame("viewport")

        assert adapter._renderer.step_calls[-1][0] == {
            mod._RENDER_PRODUCT_PATH,
            descriptor.render_product_path,
        }
        assert maps == [_FakeDevice.CPU]
        assert np.all(image == 9)
        assert np.all(source == 0)
        assert frame is not None
        assert not frame.stale
        assert frame.render_product_path == descriptor.render_product_path
        assert frame.render_var_name == "HdrColor"
        assert frame.width == 3
        assert frame.height == 2
        assert frame.component_count == 4
        assert frame.dtype == "float16"
        assert frame.color_space == "linear"
        assert frame.frame_index == 17
        assert frame.timestamp == 456.25
        np.testing.assert_array_equal(frame.raw_data, expected)
        np.testing.assert_array_equal(frame.display_data, expected)

    def test_request_rejects_disabled_or_missing_output(self, monkeypatch):
        disabled = self._descriptor(
            enabled=False,
            disabled_reason="Output unavailable.",
        )
        adapter = self._adapter_with_descriptors(monkeypatch, (disabled,))

        result = adapter.set_render_var_output_request(
            "viewport",
            RenderVarOutputRequest(
                viewport_id="viewport",
                render_product_path=disabled.render_product_path,
                render_var_name=disabled.render_var_name,
            ),
        )
        assert not result.accepted
        assert result.warning_code == "disabled_output"
        assert result.message == "Output unavailable."

        missing = adapter.set_render_var_output_request(
            "viewport",
            RenderVarOutputRequest(
                viewport_id="viewport",
                render_product_path="/Render/Products/Missing",
                render_var_name="HdrColor",
            ),
        )
        assert not missing.accepted
        assert missing.warning_code == "missing_output"

    def test_missing_product_marks_previous_frame_stale(self, monkeypatch):
        descriptor = self._descriptor()
        adapter = self._adapter_with_descriptors(monkeypatch, (descriptor,))
        assert adapter.set_render_var_output_request(
            "viewport",
            RenderVarOutputRequest(
                viewport_id="viewport",
                render_product_path=descriptor.render_product_path,
                render_var_name=descriptor.render_var_name,
            ),
        ).accepted

        output_rv, _maps, _source = self._rv(np.ones((2, 3, 4), dtype=np.float16))
        adapter._renderer.step_result = self._products(output_vars={"HdrColor": output_rv})
        adapter.render_frame(4, 3, *self._matrices())
        fresh = adapter.get_latest_render_var_output_frame("viewport")
        assert fresh is not None
        assert not fresh.stale

        image_rv, _image_maps, _image_source = self._rv(
            np.full((3, 4, 4), 5, dtype=np.uint8)
        )
        adapter._renderer.step_result = {
            mod._RENDER_PRODUCT_PATH: self._product({mod._LDR_VAR_NAME: image_rv})
        }
        adapter.render_frame(4, 3, *self._matrices())
        stale = adapter.get_latest_render_var_output_frame("viewport")

        assert stale is not None
        assert stale.stale
        np.testing.assert_array_equal(stale.raw_data, fresh.raw_data)
        assert "missing_product" in {warning.code for warning in stale.warnings}

    def test_malformed_or_failed_mapping_produces_stale_warning(self, monkeypatch):
        descriptor = self._descriptor()
        adapter = self._adapter_with_descriptors(monkeypatch, (descriptor,))
        assert adapter.set_render_var_output_request(
            "viewport",
            RenderVarOutputRequest(
                viewport_id="viewport",
                render_product_path=descriptor.render_product_path,
                render_var_name=descriptor.render_var_name,
            ),
        ).accepted

        malformed_rv, _maps, _source = self._rv(np.array([1, 2, 3], dtype=np.float32))
        adapter._renderer.step_result = self._products(output_vars={"HdrColor": malformed_rv})
        adapter.render_frame(4, 3, *self._matrices())
        malformed = adapter.get_latest_render_var_output_frame("viewport")
        assert malformed is not None
        assert malformed.stale
        assert "mapping_failed" in {warning.code for warning in malformed.warnings}

        failing_rv, _maps, _source = self._rv(
            np.ones((2, 3, 4), dtype=np.float16),
            fail=True,
        )
        adapter._renderer.step_result = self._products(output_vars={"HdrColor": failing_rv})
        adapter.render_frame(4, 3, *self._matrices())
        failed = adapter.get_latest_render_var_output_frame("viewport")
        assert failed is not None
        assert failed.stale
        assert "mapping_failed" in {warning.code for warning in failed.warnings}

    def test_request_path_change_prunes_only_previous_viewport_cache(self, monkeypatch):
        path_a = "/Render/Products/HdrProduct"
        path_b = "/Render/Products/AlbedoProduct"
        descriptor_a = self._descriptor(path_a, "HdrColor")
        descriptor_b = self._descriptor(path_b, "DiffuseAlbedoSD")
        adapter = self._adapter_with_descriptors(
            monkeypatch,
            (descriptor_a, descriptor_b),
        )
        request_a = RenderVarOutputRequest(
            viewport_id="viewport",
            render_product_path=path_a,
            render_var_name="HdrColor",
        )
        request_b = RenderVarOutputRequest(
            viewport_id="viewport",
            render_product_path=path_b,
            render_var_name="DiffuseAlbedoSD",
        )
        assert adapter.set_render_var_output_request("viewport", request_a).accepted
        frame_a = adapter._stale_render_var_output_frame(
            "viewport",
            adapter._render_var_output_requests["viewport"],
            "seed",
            "seed frame",
            descriptor_a,
        )
        other_frame = adapter._stale_render_var_output_frame(
            "other-viewport",
            RenderVarOutputRequest(
                viewport_id="other-viewport",
                render_product_path=path_a,
                output_id=descriptor_a.output_id,
                render_var_name="HdrColor",
            ),
            "seed",
            "seed frame",
            descriptor_a,
        )
        adapter._latest_render_var_output_frames[
            ("viewport", path_a, descriptor_a.output_id)
        ] = frame_a
        adapter._latest_render_var_output_frames[
            ("other-viewport", path_a, descriptor_a.output_id)
        ] = other_frame

        assert adapter.set_render_var_output_request("viewport", request_b).accepted

        assert adapter.get_latest_render_var_output_frame("viewport", path_a) is None
        assert adapter.get_latest_render_var_output_frame(
            "other-viewport",
            path_a,
        ) is other_frame

    def test_clear_render_var_request_removes_request_and_cache(self, monkeypatch):
        descriptor = self._descriptor()
        adapter = self._adapter_with_descriptors(monkeypatch, (descriptor,))
        assert adapter.set_render_var_output_request(
            "viewport",
            RenderVarOutputRequest(
                viewport_id="viewport",
                render_product_path=descriptor.render_product_path,
                render_var_name=descriptor.render_var_name,
            ),
        ).accepted
        adapter._latest_render_var_output_frames[
            ("viewport", descriptor.render_product_path, descriptor.output_id)
        ] = adapter._stale_render_var_output_frame(
            "viewport",
            adapter._render_var_output_requests["viewport"],
            "seed",
            "seed frame",
            descriptor,
        )

        assert adapter.clear_render_var_output_request("viewport") is None

        assert adapter.get_latest_render_var_output_frame("viewport") is None
        assert "viewport" not in adapter._render_var_output_requests


class TestPointCloudFrameExtraction:
    @staticmethod
    def _channel(
        name,
        semantic,
        *,
        component_count=1,
    ):
        return PointCloudChannelDescriptor(
            name=name,
            semantic=semantic,
            dtype="float32",
            component_count=component_count,
        )

    @classmethod
    def _descriptor(cls, render_product_path="/Render/Products/RadarProduct"):
        return PointCloudOutputDescriptor(
            render_product_path=render_product_path,
            render_var_name="PointCloud",
            source_sensor_path="/World/FrontRadar",
            source_sensor_type="OmniRadar",
            coordinate_space=PointCloudCoordinateSpace.SENSOR,
            transform_to_world=(
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                10.0, 0.0, 0.0, 1.0,
            ),
            channels=(
                cls._channel(
                    "Coordinates",
                    PointCloudChannelSemantic.COORDINATES,
                    component_count=3,
                ),
                cls._channel("Counts", PointCloudChannelSemantic.COUNT),
                cls._channel("Flags", PointCloudChannelSemantic.FLAGS),
                cls._channel("RCS", PointCloudChannelSemantic.RCS),
                cls._channel(
                    "RadialVelocityMs",
                    PointCloudChannelSemantic.RADIAL_VELOCITY,
                ),
                cls._channel("Intensity", PointCloudChannelSemantic.INTENSITY),
            ),
        )

    @staticmethod
    def _rv(data, *, fail=False, poison_on_unmap=False):
        source = np.array(data, copy=True)
        maps = []

        class Tensor:
            def numpy(self):
                return source

        class Mapping:
            tensor = Tensor()

            def __enter__(self):
                if fail:
                    raise RuntimeError("synthetic map failure")
                return self

            def __exit__(self, exc_type, exc, tb):
                if poison_on_unmap:
                    source[...] = 0
                return False

        class RenderVar:
            def map(self, device=None):
                maps.append(device)
                return Mapping()

        return RenderVar(), maps, source

    @staticmethod
    def _composite_rv(channels):
        arrays = {name: np.array(data, copy=True) for name, data in channels.items()}
        maps = []

        class Tensor:
            def __init__(self, arr):
                self._arr = arr

            def numpy(self):
                return self._arr

        class Mapping:
            @property
            def tensor(self):
                raise RuntimeError("composite tensor requires channel access")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def __getitem__(self, name):
                return Tensor(arrays[name])

        class RenderVar:
            def map(self, device=None):
                maps.append(device)
                return Mapping()

        return RenderVar(), maps, arrays

    @staticmethod
    def _product(render_vars, *, frame_index=11):
        frame_out = type(
            "PointCloudFrameOut",
            (),
            {
                "render_vars": render_vars,
                "frame_index": frame_index,
            },
        )()
        return type("PointCloudProduct", (), {"frames": [frame_out]})()

    @classmethod
    def _products(cls, *, point_cloud_vars, image_value=77):
        image = np.full((3, 4, 4), image_value, dtype=np.uint8)
        image_rv, _maps, _source = cls._rv(image)
        return {
            mod._RENDER_PRODUCT_PATH: cls._product(
                {mod._LDR_VAR_NAME: image_rv},
            ),
            "/Render/Products/RadarProduct": cls._product(point_cloud_vars),
        }

    @staticmethod
    def _matrices():
        from ovui_widgets.viewport.camera_controller import CameraController

        return CameraController().get_matrices(4, 3)

    def _adapter_with_descriptor(self, monkeypatch, descriptor=None, descriptors=None):
        adapter = _live_adapter(_point_cloud_fixture_stage())
        from ovui_data_adapters.openusd._session_authoring import ensure_camera

        ensure_camera(adapter._stage, mod._CAMERA_PATH)
        adapter._clock = lambda: 123.5
        descriptors = tuple(descriptors or (descriptor or self._descriptor(),))
        catalog = PointCloudOutputCatalog(
            outputs=descriptors,
            active_render_product_path=mod._RENDER_PRODUCT_PATH,
        )
        monkeypatch.setattr(
            adapter,
            "list_point_cloud_outputs",
            lambda _path=None: catalog,
        )
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)
        return adapter

    def test_render_frame_extracts_world_points_bounded_by_counts(self, monkeypatch):
        adapter = self._adapter_with_descriptor(monkeypatch)
        request = PointCloudRequest(
            viewport_id="viewport",
            render_product_path="/Render/Products/RadarProduct",
            requested_channels=("RCS", "RadialVelocityMs", "Flags"),
        )
        assert adapter.set_point_cloud_request("viewport", request).accepted

        coords_rv, _coords_maps, coords_source = self._rv(
            np.array(
                [
                    [0.0, 0.0, 0.0],
                    [1.0, 0.0, 0.0],
                    [2.0, 0.0, 0.0],
                    [3.0, 0.0, 0.0],
                ],
                dtype=np.float32,
            ),
            poison_on_unmap=True,
        )
        counts_rv, _counts_maps, _counts_source = self._rv(np.array([3], dtype=np.int32))
        flags_rv, _flags_maps, flags_source = self._rv(
            np.array([0x40, 0x00, 0x40, 0x40], dtype=np.uint8),
            poison_on_unmap=True,
        )
        rcs_rv, _rcs_maps, rcs_source = self._rv(
            np.array([10.0, 11.0, 12.0, 13.0], dtype=np.float32),
            poison_on_unmap=True,
        )
        velocity_rv, _velocity_maps, _velocity_source = self._rv(
            np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32),
        )
        adapter._renderer.step_result = self._products(
            point_cloud_vars={
                "Coordinates": coords_rv,
                "Counts": counts_rv,
                "Flags": flags_rv,
                "RCS": rcs_rv,
                "RadialVelocityMs": velocity_rv,
            },
        )

        view, proj = self._matrices()
        image = adapter.render_frame(4, 3, view, proj)
        frame = adapter.get_latest_point_cloud_frame("viewport")

        assert image.shape == (3, 4, 4)
        assert np.all(image == 77)
        assert adapter._renderer.step_calls[-1][0] == {
            mod._RENDER_PRODUCT_PATH,
            "/Render/Products/RadarProduct",
        }
        assert frame is not None
        assert frame.point_count == 3
        assert frame.valid_point_count == 2
        assert frame.coordinate_space is PointCloudCoordinateSpace.WORLD
        assert frame.frame_index == 11
        assert frame.timestamp == 123.5
        assert not frame.stale
        np.testing.assert_allclose(
            frame.coordinates,
            np.array(
                [
                    [10.0, 0.0, 0.0],
                    [11.0, 0.0, 0.0],
                    [12.0, 0.0, 0.0],
                ],
                dtype=np.float32,
            ),
        )
        np.testing.assert_array_equal(
            frame.validity_mask,
            np.array([True, False, True]),
        )
        np.testing.assert_allclose(
            frame.channel_data("RCS"),
            np.array([10.0, 11.0, 12.0], dtype=np.float32),
        )
        assert np.all(coords_source == 0)
        assert np.all(flags_source == 0)
        assert np.all(rcs_source == 0)

    def test_world_pointcloud_coordinates_are_scaled_to_stage_units(self, monkeypatch):
        _Gf, _Sdf, Usd, UsdGeom, _UsdRender = _usd_modules()
        descriptor = PointCloudOutputDescriptor(
            render_product_path="/Render/Products/RadarProduct",
            render_var_name="PointCloud",
            source_sensor_path="/World/FrontRadar",
            source_sensor_type="OmniLidar",
            coordinate_space=PointCloudCoordinateSpace.WORLD,
            channels=(
                self._channel(
                    "Coordinates",
                    PointCloudChannelSemantic.COORDINATES,
                    component_count=3,
                ),
                self._channel("Counts", PointCloudChannelSemantic.COUNT),
            ),
        )
        stage = Usd.Stage.CreateInMemory()
        adapter = _live_adapter(stage)
        from ovui_data_adapters.openusd._session_authoring import ensure_camera

        ensure_camera(adapter._stage, mod._CAMERA_PATH)
        adapter._clock = lambda: 123.5
        catalog = PointCloudOutputCatalog(
            outputs=(descriptor,),
            active_render_product_path=mod._RENDER_PRODUCT_PATH,
        )
        monkeypatch.setattr(
            adapter,
            "list_point_cloud_outputs",
            lambda _path=None: catalog,
        )
        monkeypatch.setattr(mod, "_ovrtx", _FakeOvRtx)
        UsdGeom.SetStageMetersPerUnit(adapter._stage, 0.01)
        request = PointCloudRequest(
            viewport_id="viewport",
            render_product_path="/Render/Products/RadarProduct",
        )
        assert adapter.set_point_cloud_request("viewport", request).accepted
        coords_rv, _coords_maps, _coords_source = self._rv(
            np.array([[0.75, 0.25, -0.75]], dtype=np.float32),
        )
        counts_rv, _counts_maps, _counts_source = self._rv(np.array([1], dtype=np.int32))
        adapter._renderer.step_result = self._products(
            point_cloud_vars={
                "Coordinates": coords_rv,
                "Counts": counts_rv,
            },
        )

        view, proj = self._matrices()
        adapter.render_frame(4, 3, view, proj)
        frame = adapter.get_latest_point_cloud_frame("viewport")

        assert frame is not None
        np.testing.assert_allclose(
            frame.coordinates,
            np.array([[75.0, 25.0, -75.0]], dtype=np.float32),
        )

    def test_render_frame_extracts_real_composite_pointcloud_var(self, monkeypatch):
        adapter = self._adapter_with_descriptor(monkeypatch)
        request = PointCloudRequest(
            viewport_id="viewport",
            render_product_path="/Render/Products/RadarProduct",
            requested_channels=("Intensity",),
        )
        assert adapter.set_point_cloud_request("viewport", request).accepted
        pointcloud_rv, maps, _arrays = self._composite_rv({
            "Coordinates": np.array(
                [
                    [0.0, 1.0, 2.0, 3.0],
                    [0.0, 0.0, 0.0, 0.0],
                    [0.0, 0.0, 0.0, 0.0],
                ],
                dtype=np.float32,
            ),
            "Counts": np.array([3], dtype=np.int32),
            "Intensity": np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32),
        })
        adapter._renderer.step_result = self._products(
            point_cloud_vars={"PointCloud": pointcloud_rv},
        )

        view, proj = self._matrices()
        adapter.render_frame(4, 3, view, proj)
        frame = adapter.get_latest_point_cloud_frame("viewport")

        assert frame is not None
        assert not frame.stale
        assert frame.point_count == 3
        np.testing.assert_allclose(
            frame.coordinates,
            np.array(
                [
                    [10.0, 0.0, 0.0],
                    [11.0, 0.0, 0.0],
                    [12.0, 0.0, 0.0],
                ],
                dtype=np.float32,
            ),
        )
        np.testing.assert_allclose(
            frame.channel_data("Intensity"),
            np.array([0.1, 0.2, 0.3], dtype=np.float32),
        )
        assert maps

    def test_missing_optional_channel_warns_without_blocking_frame(self, monkeypatch):
        adapter = self._adapter_with_descriptor(monkeypatch)
        request = PointCloudRequest(
            viewport_id="viewport",
            render_product_path="/Render/Products/RadarProduct",
            requested_channels=("Intensity",),
        )
        assert adapter.set_point_cloud_request("viewport", request).accepted

        coords_rv, _maps, _source = self._rv(
            np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]], dtype=np.float32),
        )
        counts_rv, _maps, _source = self._rv(np.array([2], dtype=np.int32))
        adapter._renderer.step_result = self._products(
            point_cloud_vars={
                "Coordinates": coords_rv,
                "Counts": counts_rv,
            },
        )

        view, proj = self._matrices()
        adapter.render_frame(4, 3, view, proj)
        frame = adapter.get_latest_point_cloud_frame("viewport")

        assert frame is not None
        assert frame.point_count == 2
        assert frame.channel_data("Intensity") is None
        assert {warning.code for warning in frame.warnings} == {
            "missing_channel",
            "missing_validity",
        }

    def test_mapping_failure_marks_previous_frame_stale(self, monkeypatch):
        adapter = self._adapter_with_descriptor(monkeypatch)
        request = PointCloudRequest(
            viewport_id="viewport",
            render_product_path="/Render/Products/RadarProduct",
            requested_channels=("RCS",),
        )
        assert adapter.set_point_cloud_request("viewport", request).accepted

        coords_rv, _maps, _source = self._rv(
            np.array([[0.0, 0.0, 0.0]], dtype=np.float32),
        )
        counts_rv, _maps, _source = self._rv(np.array([1], dtype=np.int32))
        rcs_rv, _maps, _source = self._rv(np.array([5.0], dtype=np.float32))
        adapter._renderer.step_result = self._products(
            point_cloud_vars={
                "Coordinates": coords_rv,
                "Counts": counts_rv,
                "RCS": rcs_rv,
            },
        )
        view, proj = self._matrices()
        adapter.render_frame(4, 3, view, proj)
        fresh = adapter.get_latest_point_cloud_frame("viewport")
        assert fresh is not None
        assert not fresh.stale

        failing_coords, _maps, _source = self._rv(
            np.array([[99.0, 99.0, 99.0]], dtype=np.float32),
            fail=True,
        )
        adapter._renderer.step_result = self._products(
            point_cloud_vars={
                "Coordinates": failing_coords,
                "Counts": counts_rv,
                "RCS": rcs_rv,
            },
            image_value=9,
        )

        image = adapter.render_frame(4, 3, view, proj)
        stale = adapter.get_latest_point_cloud_frame("viewport")

        assert np.all(image == 9)
        assert stale is not None
        assert stale.stale
        np.testing.assert_allclose(stale.coordinates, fresh.coordinates)
        assert "mapping_failed" in {warning.code for warning in stale.warnings}

    def test_request_rejects_missing_descriptor_and_clear_removes_cache(self, monkeypatch):
        adapter = self._adapter_with_descriptor(monkeypatch)

        result = adapter.set_point_cloud_request(
            "viewport",
            PointCloudRequest(
                viewport_id="viewport",
                render_product_path="/Render/Products/Missing",
            ),
        )

        assert not result.accepted
        assert result.warning_code == "missing_output"

        request = PointCloudRequest(
            viewport_id="viewport",
            render_product_path="/Render/Products/RadarProduct",
        )
        assert adapter.set_point_cloud_request("viewport", request).accepted
        adapter._latest_point_cloud_frames[
            ("viewport", "/Render/Products/RadarProduct")
        ] = PointCloudFrame(
            render_product_path="/Render/Products/RadarProduct",
            point_count=0,
        )

        assert adapter.clear_point_cloud_request("viewport") is None
        assert adapter.get_latest_point_cloud_frame("viewport") is None

    def test_request_path_change_prunes_only_previous_viewport_cache(self, monkeypatch):
        path_a = "/Render/Products/RadarProduct"
        path_b = "/Render/Products/LidarProduct"
        adapter = self._adapter_with_descriptor(
            monkeypatch,
            descriptors=(
                self._descriptor(path_a),
                self._descriptor(path_b),
            ),
        )
        frame_a = PointCloudFrame(render_product_path=path_a, point_count=1)
        other_viewport_frame = PointCloudFrame(
            render_product_path=path_a,
            point_count=2,
        )

        assert adapter.set_point_cloud_request(
            "viewport",
            PointCloudRequest(viewport_id="viewport", render_product_path=path_a),
        ).accepted
        adapter._latest_point_cloud_frames[("viewport", path_a)] = frame_a
        adapter._latest_point_cloud_frames[
            ("other-viewport", path_a)
        ] = other_viewport_frame

        assert adapter.set_point_cloud_request(
            "viewport",
            PointCloudRequest(viewport_id="viewport", render_product_path=path_b),
        ).accepted

        assert adapter.get_latest_point_cloud_frame("viewport", path_a) is None
        assert adapter.get_latest_point_cloud_frame(
            "other-viewport",
            path_a,
        ) is other_viewport_frame


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
        from ovui_widgets.viewport.camera_controller import CameraController
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

    def test_byte_range_float_preserved(self):
        src = np.ones((5, 5, 4), dtype=np.float32) * 180.0
        src[:, :, 3] = 255.0
        out = mod._normalize_rgba(src, 5, 5)
        assert out.dtype == np.uint8
        assert int(out[0, 0, 0]) == 180
        assert int(out[0, 0, 3]) == 255

    def test_returns_contiguous(self):
        src = np.random.default_rng(1).integers(0, 256, size=(10, 10, 4), dtype=np.uint8)
        # Make non-contiguous view
        view = src[::1]
        out = mod._normalize_rgba(view, 10, 10)
        assert out.flags["C_CONTIGUOUS"]

    def test_downsizes_mismatched_frame_instead_of_cropping(self):
        src = np.zeros((100, 200, 4), dtype=np.uint8)
        src[:, :100] = 40
        src[:, 100:] = 180
        out = mod._normalize_rgba(src, 80, 60)
        assert out.shape == (60, 80, 4)
        # The right half survives the resize; a top-left crop would be all 40.
        assert int(out[:, -1, 0].mean()) == 180

    def test_upsizes_mismatched_frame_instead_of_padding(self):
        src = np.ones((40, 60, 4), dtype=np.uint8) * 77
        out = mod._normalize_rgba(src, 100, 80)
        assert out.shape == (80, 100, 4)
        # The whole requested frame is filled from the source; no black padding.
        assert np.all(out == 77)


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
        assert np.all(frame == 17)


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

    def test_camera_exposure_state_present(self):
        usda = mod._build_session_usda((1280, 720), False)
        assert 'prepend apiSchemas = ["OmniRtxCameraAutoExposureAPI_1", "OmniRtxCameraExposureAPI_1"]' in usda
        assert "exposure:responsivity = 1.1026709" in usda
        assert "exposure:time = 0.02" in usda
        assert "omni:rtx:autoExposure:enabled = 1" in usda

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
