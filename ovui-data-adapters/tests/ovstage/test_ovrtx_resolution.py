# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage coverage for the shared ovrtx import resolver."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
from types import ModuleType

import pytest

from ovui_data_adapters.common import AdapterRegistry, select_adapter
from ovui_data_adapters.common import ovrtx_import as resolver
from ovui_data_adapters.ovstage import runtime_preflight as preflight_module
from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage.register import register
from ovui_data_adapters.ovstage.runtime_preflight import (
    REQUIRED_RUNTIME_REQUIREMENTS,
    load_required_runtimes,
)
from ovui_data_adapters.ovstage import renderer_adapter as renderer_module


def _fake_ovrtx_module() -> ModuleType:
    module = ModuleType("ovrtx")
    module.__version__ = "test"

    class AttachMode:
        BORROW = object()

    class RendererConfig:
        def __init__(self, **kwargs) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    class Renderer:
        version = "fake-renderer"

        def __init__(self, config) -> None:
            self.config = config

        def attach_ovstage(self, _stage) -> None:
            return None

        def detach_ovstage(self) -> None:
            return None

        def step(self, **_kwargs):
            return {}

    module.AttachMode = AttachMode
    module.RendererConfig = RendererConfig
    module.Renderer = Renderer
    return module


def _fake_current_ovrtx_module() -> ModuleType:
    module = _fake_ovrtx_module()
    del module.AttachMode

    class RendererConfig:
        def __init__(
            self,
            *,
            keep_system_alive,
            log_level,
            use_vulkan,
            selection_outline_enabled,
            selection_outline_width,
        ) -> None:
            self.keep_system_alive = keep_system_alive
            self.log_level = log_level
            self.use_vulkan = use_vulkan
            self.selection_outline_enabled = selection_outline_enabled
            self.selection_outline_width = selection_outline_width

    module.RendererConfig = RendererConfig
    return module


@pytest.fixture
def isolated_shared_ovrtx(monkeypatch):
    sentinel = object()
    original_module = sys.modules.get("ovrtx", sentinel)
    sys.modules.pop("ovrtx", None)
    resolver.reset_ovrtx_import_cache()
    env_names = (
        resolver.OVRTX_ROOT_ENV,
        resolver.OVRTX_BIN_DIR_ENV,
        resolver.OVRTX_LIBRARY_PATH_HINT_ENV,
        "LD_LIBRARY_PATH",
        "PATH",
    )
    original_env = {name: os.environ.get(name) for name in env_names}
    monkeypatch.delenv(resolver.OVRTX_ROOT_ENV, raising=False)
    monkeypatch.delenv(resolver.OVRTX_BIN_DIR_ENV, raising=False)
    monkeypatch.delenv(resolver.OVRTX_LIBRARY_PATH_HINT_ENV, raising=False)
    monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)
    monkeypatch.delenv("PATH", raising=False)
    monkeypatch.setattr(renderer_module, "_detect_gpu_device_name", lambda: "Fake GPU")
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


def _patch_non_ovrtx_preflight_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    requirements_by_module = {
        requirement.module_name: requirement
        for requirement in REQUIRED_RUNTIME_REQUIREMENTS
        if requirement.module_name != "ovrtx"
    }

    def fake_import_module(name: str, package: str | None = None) -> ModuleType:
        requirement = requirements_by_module.get(name)
        if requirement is None:
            return importlib.import_module(name, package)
        module = ModuleType(requirement.module_name)
        for attribute_name in requirement.expected_attributes:
            setattr(module, attribute_name, object())
        for callable_name in requirement.expected_callables:
            setattr(module, callable_name, lambda: None)
        return module

    monkeypatch.setattr(preflight_module, "import_module", fake_import_module)


class TestOvstageRendererOvRtxResolution:
    def test_renderer_uses_current_default_borrow_config_without_obsolete_keyword(
        self,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        module = _fake_current_ovrtx_module()
        monkeypatch.setattr(
            resolver.importlib,
            "import_module",
            lambda _name: module,
        )

        adapter = renderer_module.OvstageRendererAdapter()

        assert adapter._ovrtx is module
        assert adapter._renderer.config.use_vulkan is True
        assert not hasattr(adapter._renderer.config, "attach_mode")

    def test_renderer_uses_active_env_ovrtx_first(
        self,
        tmp_path,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        root = tmp_path / "external"
        (root / "python" / "ovrtx").mkdir(parents=True)
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))
        normal_module = _fake_ovrtx_module()
        calls: list[str] = []

        def fake_import(name: str):
            calls.append(name)
            assert name == "ovrtx"
            return normal_module

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)

        adapter = renderer_module.OvstageRendererAdapter()

        assert adapter._ovrtx is normal_module
        assert adapter._renderer.config.use_vulkan is True
        assert adapter._renderer.config.attach_mode is normal_module.AttachMode.BORROW
        assert calls == ["ovrtx"]
        assert str(root / "python") not in sys.path

    def test_renderer_uses_ovrtx_root_when_active_env_import_fails(
        self,
        tmp_path,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        root = tmp_path / "external"
        candidate = root / "python"
        (candidate / "ovrtx").mkdir(parents=True)
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))
        external_module = _fake_ovrtx_module()
        calls: list[str] = []

        def fake_import(name: str):
            calls.append(name)
            assert name == "ovrtx"
            if len(calls) == 1:
                raise ImportError("active environment missing")
            assert sys.path[0] == str(candidate)
            return external_module

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)

        adapter = renderer_module.OvstageRendererAdapter()

        assert adapter._ovrtx is external_module
        assert adapter._renderer.config.attach_mode is external_module.AttachMode.BORROW
        assert calls == ["ovrtx", "ovrtx"]
        assert str(candidate) not in sys.path

    def test_renderer_rejects_active_ovrtx_that_shadows_configured_root(
        self,
        tmp_path,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        root = tmp_path / "kit-ovrtx"
        (root / "public" / "python" / "ovrtx").mkdir(parents=True)
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))
        shadowed = _fake_ovrtx_module()
        shadowed.__file__ = str(tmp_path / "stale-wheel" / "ovrtx" / "__init__.py")
        monkeypatch.setattr(
            resolver.importlib,
            "import_module",
            lambda _name: shadowed,
        )

        with pytest.raises(RuntimeError, match="different installation"):
            renderer_module.OvstageRendererAdapter()

    def test_renderer_uses_kit_ovrtx_root_when_active_env_import_fails(
        self,
        tmp_path: Path,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        rendering_root = tmp_path / "rendering"
        root = rendering_root / "ovrtx"
        candidate = root / "public" / "python"
        build_dir = rendering_root / "_build" / "linux-x86_64" / "release"
        (candidate / "ovrtx").mkdir(parents=True)
        (build_dir / "plugins" / "rtx").mkdir(parents=True)
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))
        external_module = _fake_ovrtx_module()
        calls: list[str] = []

        def fake_import(name: str):
            calls.append(name)
            assert name == "ovrtx"
            if len(calls) == 1:
                raise ImportError("active environment missing")
            assert sys.path[0] == str(candidate)
            return external_module

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)

        adapter = renderer_module.OvstageRendererAdapter()

        assert adapter._ovrtx is external_module
        assert adapter._renderer.config.attach_mode is external_module.AttachMode.BORROW
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

    def test_renderer_invalid_ovrtx_root_reports_useful_failure(
        self,
        tmp_path,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        root = tmp_path / "missing"
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))

        def fake_import(name: str):
            assert name == "ovrtx"
            raise ImportError("active environment missing")

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)

        with pytest.raises(RuntimeError) as exc_info:
            renderer_module.OvstageRendererAdapter()

        message = str(exc_info.value)
        assert "ovrtx is not available" in message
        assert "active environment missing" in message
        assert resolver.OVRTX_ROOT_ENV in message
        assert f"{resolver.OVRTX_ROOT_ENV}={str(root)!r}" in message

    def test_renderer_rejects_missing_borrow_method_before_native_construction(
        self,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        module = _fake_ovrtx_module()
        module.Renderer.step = None
        construction_calls: list[None] = []
        original_init = module.Renderer.__init__

        def record_init(self, config) -> None:
            construction_calls.append(None)
            original_init(self, config)

        module.Renderer.__init__ = record_init
        monkeypatch.setattr(
            resolver.importlib,
            "import_module",
            lambda _name: module,
        )

        with pytest.raises(
            RuntimeError,
            match=r"ovrtx\.Renderer\.step",
        ):
            renderer_module.OvstageRendererAdapter()

        assert construction_calls == []

    def test_renderer_rejects_legacy_enum_when_config_rejects_attach_mode(
        self,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        module = _fake_ovrtx_module()
        current_config_type = _fake_current_ovrtx_module().RendererConfig
        module.RendererConfig = current_config_type
        construction_calls: list[None] = []

        class Renderer(module.Renderer):
            def __init__(self, config) -> None:
                construction_calls.append(None)
                super().__init__(config)

        module.Renderer = Renderer
        monkeypatch.setattr(
            resolver.importlib,
            "import_module",
            lambda _name: module,
        )

        with pytest.raises(RuntimeError) as exc_info:
            renderer_module.OvstageRendererAdapter()

        assert str(exc_info.value) == (
            "incompatible public OVRTX attachment contract: public "
            "ovrtx.AttachMode.BORROW is present but ovrtx.RendererConfig "
            "does not accept attach_mode"
        )
        assert isinstance(exc_info.value.__cause__, TypeError)
        assert construction_calls == []

    def test_renderer_preserves_current_config_type_error(
        self,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        module = _fake_current_ovrtx_module()

        class RendererConfig:
            def __init__(self, **_kwargs) -> None:
                raise TypeError("current config failed")

        module.RendererConfig = RendererConfig
        monkeypatch.setattr(
            resolver.importlib,
            "import_module",
            lambda _name: module,
        )

        with pytest.raises(TypeError, match="^current config failed$") as exc_info:
            renderer_module.OvstageRendererAdapter()

        assert exc_info.value.__cause__ is None


class TestOvstagePreflightOvRtxResolution:
    def test_preflight_does_not_require_ovrtx(
        self,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        _patch_non_ovrtx_preflight_modules(monkeypatch)

        def fake_import(name: str):
            assert name == "ovrtx"
            raise ImportError("active environment missing")

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)

        runtime = load_required_runtimes(
            module_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        )

        assert "ovrtx" not in runtime.requirement_names

    def test_provider_registration_succeeds_when_ovrtx_root_is_valid(
        self,
        tmp_path,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        _patch_non_ovrtx_preflight_modules(monkeypatch)
        root = tmp_path / "external"
        (root / "python" / "ovrtx").mkdir(parents=True)
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))
        external_module = _fake_ovrtx_module()
        calls: list[str] = []

        def fake_import(name: str):
            calls.append(name)
            if len(calls) == 1:
                raise ImportError("active environment missing")
            return external_module

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)
        registry = AdapterRegistry()

        register(registry)

        assert registry.load_failures == ()
        provider = select_adapter(registry, requested_name=PROVIDER_NAME)
        assert "ovrtx" in provider.requirements
        session = provider.factories.session()
        session.prepare_runtime_imports()
        assert session.renderer_available() is True
        assert session.renderer_unavailable_reason() == ""

    def test_provider_registration_succeeds_when_ovrtx_is_missing(
        self,
        tmp_path,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        _patch_non_ovrtx_preflight_modules(monkeypatch)
        root = tmp_path / "missing"
        monkeypatch.setenv(resolver.OVRTX_ROOT_ENV, str(root))

        def fake_import(name: str):
            assert name == "ovrtx"
            raise ImportError("active environment missing")

        monkeypatch.setattr(resolver.importlib, "import_module", fake_import)

        registry = AdapterRegistry()

        register(registry)

        assert registry.load_failures == ()
        provider = select_adapter(registry, requested_name=PROVIDER_NAME)
        session = provider.factories.session()
        assert session.allows_renderer_fallback is False
        assert session.renderer_available() is False
        reason = session.renderer_unavailable_reason()
        assert "active environment missing" in reason
        assert resolver.OVRTX_ROOT_ENV in reason
        assert f"{resolver.OVRTX_ROOT_ENV}={str(root)!r}" in reason

    def test_provider_reports_exact_incompatible_ovrtx_api(
        self,
        monkeypatch,
        isolated_shared_ovrtx,
    ) -> None:
        _patch_non_ovrtx_preflight_modules(monkeypatch)
        module = _fake_ovrtx_module()
        module.Renderer.attach_ovstage = None
        monkeypatch.setattr(
            resolver.importlib,
            "import_module",
            lambda _name: module,
        )
        registry = AdapterRegistry()

        register(registry)

        provider = select_adapter(registry, requested_name=PROVIDER_NAME)
        session = provider.factories.session()
        assert session.renderer_available() is False
        assert "ovrtx.Renderer.attach_ovstage" in session.renderer_unavailable_reason()
