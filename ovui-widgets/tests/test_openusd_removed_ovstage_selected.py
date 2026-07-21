# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 24: OpenUSD-removal and ovstage-provider swap validation."""

from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest


MONOREPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
OVSTAGE_STATIC_SCENE_PATH = (
    MONOREPO_ROOT
    / "ovui-data-adapters"
    / "tests"
    / "data"
    / "ovstage_static_scene.usda"
)


def _run_isolated_python(
    code: str,
    *,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    env.setdefault("OVRTX_SKIP_USD_CHECK", "1")
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=MONOREPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    assert proc.returncode == 0, (
        f"subprocess exited {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    return proc


def test_widget_and_app_imports_survive_openusd_and_pxr_absence() -> None:
    child_dll_preamble = sys.modules[
        "tests.conftest"
    ].CHILD_PROCESS_VULKAN_DLL_PREAMBLE

    _run_isolated_python(
        child_dll_preamble
        + textwrap.dedent(
            """
        import importlib
        import importlib.abc
        import sys

        blocked_prefixes = ("ovui_data_adapters.openusd", "pxr")
        leaked_at_start = [
            name for name in sys.modules
            if any(name == prefix or name.startswith(prefix + ".")
                   for prefix in blocked_prefixes)
        ]
        if leaked_at_start:
            sys.stderr.write(
                "blocked modules already loaded at subprocess start: "
                + ",".join(sorted(leaked_at_start))
                + "\\n"
            )
            sys.exit(3)

        class Blocker(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                for prefix in blocked_prefixes:
                    if fullname == prefix or fullname.startswith(prefix + "."):
                        raise ImportError(f"blocked Step 24 import: {fullname}")
                return None

        sys.meta_path.insert(0, Blocker())
        modules = (
            "ovui_widgets.app.application",
            "ovui_widgets.stage.window",
            "ovui_widgets.property",
            "ovui_widgets.layers",
            "ovui_widgets.viewport.viewport_widget",
            "ovui_widgets.content",
        )
        for module_name in modules:
            importlib.import_module(module_name)

        leaked_after = [
            name for name in sys.modules
            if any(name == prefix or name.startswith(prefix + ".")
                   for prefix in blocked_prefixes)
        ]
        if leaked_after:
            sys.stderr.write(
                "widget imports loaded blocked modules: "
                + ",".join(sorted(leaked_after))
                + "\\n"
            )
            sys.exit(1)
        """
        ),
    )


def test_app_selects_ovstage_and_loads_fixture_with_openusd_entry_point_absent() -> None:
    missing_runtime = [
        module_name
        for module_name in ("ovstage", "ovhierarchy", "ovphysx", "ovrtx")
        if importlib.util.find_spec(module_name) is None
    ]
    if missing_runtime:
        pytest.skip(
            "missing ovstage runtime modules: " + ", ".join(missing_runtime)
        )

    _run_isolated_python(
        f"""
        from dataclasses import dataclass
        import importlib
        import importlib.abc
        import importlib.util
        import os
        import pathlib
        import sys

        scene_path = pathlib.Path({str(OVSTAGE_STATIC_SCENE_PATH)!r})
        assert scene_path.is_file(), scene_path
        missing = [
            module_name
            for module_name in ("ovstage", "ovhierarchy", "ovphysx", "ovrtx")
            if importlib.util.find_spec(module_name) is None
        ]
        assert not missing, "missing ovstage runtime modules: " + ", ".join(missing)

        @dataclass(frozen=True)
        class FakeEntryPoint:
            name: str
            value: str
            group: str

            def load(self):
                module_name, attr_name = self.value.split(":", 1)
                module = importlib.import_module(module_name)
                return getattr(module, attr_name)

        class ImportBlocker(importlib.abc.MetaPathFinder):
            def __init__(self, prefixes):
                self._prefixes = tuple(prefixes)
                self.attempts = []

            def find_spec(self, fullname, path=None, target=None):
                for prefix in self._prefixes:
                    if fullname == prefix or fullname.startswith(prefix + "."):
                        self.attempts.append(fullname)
                        raise ImportError(f"blocked Step 24 import: {{fullname}}")
                return None

        def purge_modules(prefixes):
            for module_name in list(sys.modules):
                if any(
                    module_name == prefix or module_name.startswith(prefix + ".")
                    for prefix in prefixes
                ):
                    del sys.modules[module_name]

        from ovui_data_adapters.common import (
            ADAPTER_ENTRY_POINT_GROUP,
            discover_adapter_modules,
        )
        import ovui_data_adapters.common._adapter_registry as registry_module

        ovstage_entry = FakeEntryPoint(
            name="ovstage",
            value="ovui_data_adapters.ovstage.register:register",
            group=ADAPTER_ENTRY_POINT_GROUP,
        )

        def fake_entry_points(*, group):
            assert group == ADAPTER_ENTRY_POINT_GROUP
            return (ovstage_entry,)

        registry_module.entry_points = fake_entry_points
        os.environ["OVUI_DATA_ADAPTER_PROVIDER"] = "ovstage"
        os.environ["OVRTX_SKIP_USD_CHECK"] = "1"
        os.environ.pop("OVUI_DATA_ADAPTER_PROVIDER", None)
        purge_modules(("ovui_data_adapters.openusd",))

        blocker = ImportBlocker(("ovui_data_adapters.openusd",))
        sys.meta_path.insert(0, blocker)
        try:
            from ovui_widgets.app.application import Application

            registry = discover_adapter_modules()
            assert [provider.name for provider in registry.available_adapters()] == [
                "ovstage"
            ], registry.load_failures
            assert registry.load_failures == ()

            app = Application()
            try:
                app._startup_prebuilt_renderer = None
                app.open_file(str(scene_path))

                assert app._adapter_provider is not None
                assert app._adapter_provider.name == "ovstage"
                assert app._adapter_registry is not None
                assert [
                    provider.name
                    for provider in app._adapter_registry.available_adapters()
                ] == ["ovstage"]
                assert app._stage_adapter is not None
                assert (
                    app._stage_adapter.get_item_at_path(
                        "/World/Hierarchy/GroupA/BoxA"
                    )
                    is not None
                )
                assert app._layer_adapter is not None
                assert app._layer_adapter.get_layer_stack_identifiers() == []
                assert app._layer_adapter.save_layer("missing") is False
                assert app._current_file_path == str(scene_path)
            finally:
                session = getattr(app, "_adapter_session", None)
                shutdown_scene = getattr(session, "shutdown_scene", None)
                if callable(shutdown_scene):
                    shutdown_scene()
                app.shutdown()
        finally:
            try:
                sys.meta_path.remove(blocker)
            except ValueError:
                pass

        assert blocker.attempts == []
        assert not any(
            name == "ovui_data_adapters.openusd"
            or name.startswith("ovui_data_adapters.openusd.")
            for name in sys.modules
        )
        """,
        timeout=120.0,
    )


def test_unavailable_selected_ovstage_provider_records_structured_failure() -> None:
    _run_isolated_python(
        """
        from dataclasses import dataclass
        import importlib
        import importlib.abc
        import sys

        from ovui_data_adapters.common import (
            ADAPTER_ENTRY_POINT_GROUP,
            AdapterModuleLoadFailure,
            AdapterProviderNotFoundError,
            discover_adapter_modules,
            select_adapter,
        )
        import ovui_data_adapters.common._adapter_registry as registry_module
        import ovui_data_adapters.ovstage.provider as provider_module
        from ovui_data_adapters.ovstage.runtime_preflight import (
            OVSTAGE_INSTALL_MESSAGE,
            OvstageRuntimePreflightError,
        )

        @dataclass(frozen=True)
        class FakeEntryPoint:
            name: str
            value: str
            group: str

            def load(self):
                module_name, attr_name = self.value.split(":", 1)
                module = importlib.import_module(module_name)
                return getattr(module, attr_name)

        class ImportBlocker(importlib.abc.MetaPathFinder):
            def __init__(self, prefixes):
                self._prefixes = tuple(prefixes)
                self.attempts = []

            def find_spec(self, fullname, path=None, target=None):
                for prefix in self._prefixes:
                    if fullname == prefix or fullname.startswith(prefix + "."):
                        self.attempts.append(fullname)
                        raise ImportError(f"blocked Step 24 import: {fullname}")
                return None

        def purge_modules(prefixes):
            for module_name in list(sys.modules):
                if any(
                    module_name == prefix or module_name.startswith(prefix + ".")
                    for prefix in prefixes
                ):
                    del sys.modules[module_name]

        ovstage_entry = FakeEntryPoint(
            name="ovstage",
            value="ovui_data_adapters.ovstage.register:register",
            group=ADAPTER_ENTRY_POINT_GROUP,
        )

        def fake_entry_points(*, group):
            assert group == ADAPTER_ENTRY_POINT_GROUP
            return (ovstage_entry,)

        def fail_preflight(**kwargs):
            raise OvstageRuntimePreflightError(
                module_name="ovstage",
                entry_point_value="ovui_data_adapters.ovstage.register:register",
                requirement_name="ovstage",
                exception=ModuleNotFoundError("No module named 'ovstage'"),
            )

        registry_module.entry_points = fake_entry_points
        provider_module.load_required_runtimes = fail_preflight
        sys.modules.pop("ovui_data_adapters.ovstage.register", None)
        purge_modules(("ovui_data_adapters.openusd",))

        blocker = ImportBlocker(("ovui_data_adapters.openusd",))
        sys.meta_path.insert(0, blocker)
        try:
            registry = discover_adapter_modules()
        finally:
            try:
                sys.meta_path.remove(blocker)
            except ValueError:
                pass

        assert registry.available_adapters() == (), registry.load_failures
        assert len(registry.load_failures) == 1
        failure = registry.load_failures[0]
        assert isinstance(failure, AdapterModuleLoadFailure)
        assert failure.name == "ovstage"
        assert failure.value == "ovui_data_adapters.ovstage.register:register"
        assert failure.exception_type == "OvstageRuntimePreflightError"
        assert failure.module_name == "ovstage"
        assert (
            failure.entry_point_value
            == "ovui_data_adapters.ovstage.register:register"
        )
        assert failure.requirement_name == "ovstage"
        assert "ModuleNotFoundError" in failure.exception_text
        assert failure.message == OVSTAGE_INSTALL_MESSAGE

        try:
            select_adapter(registry, requested_name="ovstage")
        except AdapterProviderNotFoundError as exc:
            assert str(exc) == OVSTAGE_INSTALL_MESSAGE
        else:
            raise AssertionError("selected unavailable ovstage provider")
        assert blocker.attempts == []
        """,
    )


def test_common_selection_swaps_openusd_and_ovstage_by_request_and_priority() -> None:
    from ovui_data_adapters.common import (
        AdapterFactories,
        AdapterRegistry,
        select_adapter,
    )

    registry = AdapterRegistry()
    registry.register_adapter(
        name="openusd",
        priority=0,
        factories=AdapterFactories(stage=lambda: "openusd-stage"),
    )
    registry.register_adapter(
        name="ovstage",
        priority=100,
        factories=AdapterFactories(stage=lambda: "ovstage-stage"),
    )

    priority_selected = select_adapter(registry)
    openusd_selected = select_adapter(registry, requested_name="openusd")
    ovstage_selected = select_adapter(registry, requested_name="ovstage")

    assert priority_selected.name == "ovstage"
    assert priority_selected.factories.stage() == "ovstage-stage"
    assert openusd_selected.name == "openusd"
    assert openusd_selected.factories.stage() == "openusd-stage"
    assert ovstage_selected.name == "ovstage"
    assert ovstage_selected.factories.stage() == "ovstage-stage"
    assert registry.active_provider is ovstage_selected


def test_ovui_widgets_app_distribution_does_not_force_openusd_provider() -> None:
    try:
        import tomllib
    except ImportError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]

    path = MONOREPO_ROOT / "ovui-widgets" / "dist" / "app" / "pyproject.toml"
    with path.open("rb") as file:
        project = tomllib.load(file)["project"]

    dependencies = tuple(project["dependencies"])
    concrete_adapter_deps = [
        dep
        for dep in dependencies
        if dep.startswith("ovui-data-adapters-openusd")
        or dep.startswith("ovui-data-adapters-ovstage")
    ]

    assert "ovui-data-adapters-common>=0.1.0" in dependencies
    assert concrete_adapter_deps == []
