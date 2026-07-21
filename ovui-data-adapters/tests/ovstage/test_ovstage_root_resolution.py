# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OVSTAGE_ROOT runtime resolution coverage for the ovstage provider."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType

import pytest

from ovui_data_adapters.common import (
    AdapterFactories,
    AdapterProviderNotFoundError,
    AdapterRegistry,
    select_adapter,
)
from ovui_data_adapters.ovstage import runtime_import as resolver
from ovui_data_adapters.ovstage import runtime_preflight as preflight_module
from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage.register import register
from ovui_data_adapters.ovstage.runtime_preflight import (
    LEGACY_RUNTIME_REQUIREMENTS,
    OVSTAGE_INSTALL_MESSAGE,
    REQUIRED_RUNTIME_REQUIREMENTS,
    load_required_runtimes,
)


RUNTIME_MODULES = ("ovstage", "ovhierarchy", "ovpopulation", "ovphysx")
DATA_ADAPTERS_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = DATA_ADAPTERS_ROOT.parent


@pytest.fixture
def isolated_ovstage_runtime(monkeypatch: pytest.MonkeyPatch):
    sentinel = object()
    original_modules = {
        name: sys.modules.get(name, sentinel)
        for name in RUNTIME_MODULES
    }
    for module_name in RUNTIME_MODULES:
        sys.modules.pop(module_name, None)
    env_names = (
        resolver.OVSTAGE_ROOT_ENV,
        resolver.OVSTAGE_BUILD_DIR_ENV,
        resolver.OVSTAGE_LIBRARY_PATH_ENV,
        resolver.OVPOPULATION_LIBRARY_PATH_ENV,
        resolver.OVHIERARCHY_LIBRARY_PATH_ENV,
        resolver.OVSTAGE_LIBRARY_PATH_HINT_ENV,
        "LD_LIBRARY_PATH",
        "PATH",
    )
    original_env = {name: os.environ.get(name) for name in env_names}
    for env_name in env_names:
        monkeypatch.delenv(env_name, raising=False)
    yield
    for module_name in RUNTIME_MODULES:
        sys.modules.pop(module_name, None)
    for module_name, original in original_modules.items():
        if original is not sentinel:
            sys.modules[module_name] = original
    for env_name, original_value in original_env.items():
        if original_value is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = original_value


def _write_fake_root(root: Path, marker: str) -> Path:
    build_dir = root / "_build" / "linux-x86_64" / "release"
    build_dir.mkdir(parents=True)
    packages = {
        "ovstage": ("Stage",),
        "ovhierarchy": ("Hierarchy",),
        "ovpopulation": (),
        "ovphysx": ("PhysXConfig",),
    }
    for module_name, attrs in packages.items():
        package_dir = root / "src" / module_name / "python" / module_name
        package_dir.mkdir(parents=True)
        lines = [
            f"__version__ = {marker!r}",
            f"ROOT_MARKER = {marker!r}",
        ]
        for attr_name in attrs:
            lines.append(f"class {attr_name}:\n    pass")
        if module_name == "ovpopulation":
            lines.append("def populate_from_file(stage, path, ordinal):\n    return None")
        (package_dir / "__init__.py").write_text(
            "\n\n".join(lines) + "\n",
            encoding="utf-8",
        )
    return build_dir


def _write_fake_kit_root(rendering_root: Path, marker: str) -> tuple[Path, Path]:
    ovstage_root = rendering_root / "ovstage"
    build_dir = rendering_root / "_build" / "linux-x86_64" / "release"
    (build_dir / "plugins" / "rtx").mkdir(parents=True)
    packages = {
        "ovstage": ("Stage",),
        "ovhierarchy": ("Hierarchy",),
        "ovpopulation": (),
        "ovphysx": ("PhysXConfig",),
    }
    for module_name, attrs in packages.items():
        package_dir = ovstage_root / "public" / "python" / module_name
        package_dir.mkdir(parents=True)
        lines = [
            f"__version__ = {marker!r}",
            f"ROOT_MARKER = {marker!r}",
        ]
        for attr_name in attrs:
            lines.append(f"class {attr_name}:\n    pass")
        if module_name == "ovpopulation":
            lines.append("def populate_from_file(stage, path, ordinal):\n    return None")
        (package_dir / "__init__.py").write_text(
            "\n\n".join(lines) + "\n",
            encoding="utf-8",
        )
    return ovstage_root, build_dir


def _guarded_import_for_root(root: Path):
    def guarded_import(name: str, package: str | None = None) -> ModuleType:
        if name in RUNTIME_MODULES:
            root_paths = resolver.ovstage_python_path_candidates(str(root))
            if not any(str(path) in sys.path for path in root_paths):
                raise ModuleNotFoundError(f"active env missing {name}", name=name)
        return importlib.import_module(name, package)

    return guarded_import


def test_active_env_ovstage_imports_win_before_ovstage_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_ovstage_runtime,
) -> None:
    _write_fake_root(tmp_path / "external", "external")
    monkeypatch.setenv(resolver.OVSTAGE_ROOT_ENV, str(tmp_path / "external"))
    calls: list[str] = []

    def active_import(name: str, package: str | None = None) -> ModuleType:
        calls.append(name)
        module = ModuleType(name)
        module.__version__ = "active"
        if name == "ovstage":
            module.Stage = object
        if name == "ovhierarchy":
            module.Hierarchy = object
        return module

    monkeypatch.setattr(preflight_module, "import_module", active_import)

    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )

    assert calls == ["ovstage"]
    assert runtime.module("ovstage").__version__ == "active"
    assert str(tmp_path / "external" / "src" / "ovstage" / "python") not in sys.path


def test_ovstage_root_supplies_required_runtime_modules(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_ovstage_runtime,
) -> None:
    root = tmp_path / "root-a"
    build_dir = _write_fake_root(root, "root-a")
    monkeypatch.setenv(resolver.OVSTAGE_ROOT_ENV, str(root))
    monkeypatch.setattr(
        preflight_module,
        "import_module",
        _guarded_import_for_root(root),
    )

    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )

    assert runtime.module("ovstage").ROOT_MARKER == "root-a"
    for env_name in (
        resolver.OVSTAGE_LIBRARY_PATH_ENV,
        resolver.OVPOPULATION_LIBRARY_PATH_ENV,
        resolver.OVHIERARCHY_LIBRARY_PATH_ENV,
    ):
        assert os.environ[env_name] == str(build_dir)
    for candidate in resolver.ovstage_python_path_candidates(str(root)):
        assert str(candidate) not in sys.path


def test_ovstage_root_supports_kit_component_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_ovstage_runtime,
) -> None:
    root, build_dir = _write_fake_kit_root(tmp_path / "rendering", "kit")
    monkeypatch.setenv(resolver.OVSTAGE_ROOT_ENV, str(root))
    monkeypatch.setattr(
        preflight_module,
        "import_module",
        _guarded_import_for_root(root),
    )

    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )

    assert runtime.module("ovstage").ROOT_MARKER == "kit"
    assert resolver.ovstage_python_path_candidates(str(root)) == (
        root / "public" / "python",
    )
    runtime_dirs = resolver.ovstage_runtime_dirs(str(root))
    assert runtime_dirs[:3] == (
        build_dir,
        build_dir / "plugins",
        build_dir / "plugins" / "rtx",
    )
    for env_name in (
        resolver.OVSTAGE_LIBRARY_PATH_ENV,
        resolver.OVPOPULATION_LIBRARY_PATH_ENV,
        resolver.OVHIERARCHY_LIBRARY_PATH_ENV,
        resolver.OVSTAGE_LIBRARY_PATH_HINT_ENV,
    ):
        assert os.environ[env_name] == str(build_dir)
    runtime_path_env = "PATH" if sys.platform.startswith("win") else "LD_LIBRARY_PATH"
    assert os.environ[runtime_path_env].split(os.pathsep)[:3] == [
        str(build_dir),
        str(build_dir / "plugins"),
        str(build_dir / "plugins" / "rtx"),
    ]
    assert str(root / "public" / "python") not in sys.path


def test_ovstage_root_legacy_ovhierarchy_remains_available_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_ovstage_runtime,
) -> None:
    root = tmp_path / "root-legacy"
    _write_fake_root(root, "legacy")
    monkeypatch.setenv(resolver.OVSTAGE_ROOT_ENV, str(root))
    monkeypatch.setattr(
        preflight_module,
        "import_module",
        _guarded_import_for_root(root),
    )

    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        requirements=(*REQUIRED_RUNTIME_REQUIREMENTS, *LEGACY_RUNTIME_REQUIREMENTS),
    )

    assert runtime.module("ovstage").ROOT_MARKER == "legacy"
    assert runtime.module("ovhierarchy").ROOT_MARKER == "legacy"


def test_ovstage_root_supplies_lazy_population_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_ovstage_runtime,
) -> None:
    root = tmp_path / "root-population"
    _write_fake_root(root, "root-population")
    monkeypatch.setenv(resolver.OVSTAGE_ROOT_ENV, str(root))
    import ovui_data_adapters.ovstage._scene as scene_module

    monkeypatch.setattr(
        scene_module,
        "import_module",
        _guarded_import_for_root(root),
    )

    module = scene_module._load_population_module()

    assert module.ROOT_MARKER == "root-population"
    assert callable(module.populate_from_file)


def test_ovstage_root_supplies_integrated_kit_population_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_ovstage_runtime,
) -> None:
    root = tmp_path / "rendering" / "ovstage"
    package_dir = root / "public" / "python" / "ovstage"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        "\n".join(
            [
                "from . import population",
                "class Stage:",
                "    pass",
                "ROOT_MARKER = 'kit-integrated'",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (package_dir / "population.py").write_text(
        "ROOT_MARKER = 'kit-integrated'\n"
        "def open_usd(stage, path, ordinal):\n"
        "    return None\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(resolver.OVSTAGE_ROOT_ENV, str(root))
    import ovui_data_adapters.ovstage._scene as scene_module

    monkeypatch.setattr(
        scene_module,
        "import_module",
        _guarded_import_for_root(root),
    )

    stage_module = resolver.import_ovstage_runtime_module(
        "ovstage",
        import_module_fn=_guarded_import_for_root(root),
    )
    module = scene_module._load_population_module(stage_module)

    assert module.ROOT_MARKER == "kit-integrated"
    assert callable(module.open_usd)


def test_invalid_ovstage_root_preserves_requested_provider_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_ovstage_runtime,
) -> None:
    root = tmp_path / "invalid-root"
    root.mkdir()
    monkeypatch.setenv(resolver.OVSTAGE_ROOT_ENV, str(root))

    def missing_import(name: str, package: str | None = None) -> ModuleType:
        raise ModuleNotFoundError(f"active env missing {name}", name=name)

    monkeypatch.setattr(preflight_module, "import_module", missing_import)
    registry = AdapterRegistry()

    register(registry)

    assert registry.available_adapters() == ()
    assert len(registry.load_failures) == 1
    failure = registry.load_failures[0]
    assert failure.message == OVSTAGE_INSTALL_MESSAGE
    assert failure.requirement_name == "ovstage"
    assert resolver.OVSTAGE_ROOT_ENV in failure.exception_text
    assert f"{resolver.OVSTAGE_ROOT_ENV}={str(root)!r}" in failure.exception_text
    with pytest.raises(AdapterProviderNotFoundError) as exc_info:
        select_adapter(registry, requested_name=PROVIDER_NAME)
    assert str(exc_info.value) == OVSTAGE_INSTALL_MESSAGE


def test_missing_ovstage_does_not_block_default_adapter_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_ovstage_runtime,
) -> None:
    root = tmp_path / "invalid-root"
    monkeypatch.setenv(resolver.OVSTAGE_ROOT_ENV, str(root))

    def missing_import(name: str, package: str | None = None) -> ModuleType:
        raise ModuleNotFoundError(f"active env missing {name}", name=name)

    monkeypatch.setattr(preflight_module, "import_module", missing_import)
    registry = AdapterRegistry()
    registry.register_adapter(
        name="openusd",
        priority=0,
        factories=AdapterFactories(stage=lambda: "openusd"),
    )

    register(registry)
    provider = select_adapter(registry)

    assert provider.name == "openusd"
    assert len(registry.load_failures) == 1
    assert registry.load_failures[0].message == OVSTAGE_INSTALL_MESSAGE


def test_changing_ovstage_root_selects_different_runtime_in_subprocess(
    tmp_path: Path,
    isolated_ovstage_runtime,
) -> None:
    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    _write_fake_root(root_a, "root-a")
    _write_fake_root(root_b, "root-b")

    script = """
from __future__ import annotations
import importlib
import json
import os
import sys
from pathlib import Path

from ovui_data_adapters.ovstage import runtime_import as resolver
from ovui_data_adapters.ovstage import runtime_preflight as preflight_module
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes

root = Path(os.environ["OVSTAGE_ROOT"])
runtime_modules = ("ovstage", "ovhierarchy", "ovpopulation", "ovphysx")

def guarded_import(name, package=None):
    if name in runtime_modules:
        root_paths = resolver.ovstage_python_path_candidates(str(root))
        if not any(str(path) in sys.path for path in root_paths):
            raise ModuleNotFoundError(f"active env missing {name}", name=name)
    return importlib.import_module(name, package)

preflight_module.import_module = guarded_import
runtime = load_required_runtimes(module_name="ovstage", entry_point_value="test")
print(json.dumps({
    "root": str(root),
    "ovstage_marker": runtime.module("ovstage").ROOT_MARKER,
}))
"""

    markers = []
    for root in (root_a, root_b):
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = os.pathsep.join(
            entry
            for entry in (
                str(DATA_ADAPTERS_ROOT),
                env.get("PYTHONPATH", ""),
            )
            if entry
        )
        env["OVSTAGE_ROOT"] = str(root)
        for env_name in (
            resolver.OVSTAGE_BUILD_DIR_ENV,
            resolver.OVSTAGE_LIBRARY_PATH_ENV,
            resolver.OVPOPULATION_LIBRARY_PATH_ENV,
            resolver.OVHIERARCHY_LIBRARY_PATH_ENV,
        ):
            env.pop(env_name, None)
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        assert proc.returncode == 0, proc.stderr
        markers.append(json.loads(proc.stdout))

    assert [item["ovstage_marker"] for item in markers] == ["root-a", "root-b"]
