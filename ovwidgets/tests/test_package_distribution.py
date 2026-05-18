# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Issue #31 Step 2 — ovwidgets packaging distribution metadata.

Verifies that:
- The installed distribution is named ``ovwidgets-app``
- All four console scripts are registered
- main_sync() is callable without launching the UI
- Build system is still setuptools-backed (pyproject.toml [build-system] check)
- Package-data icon directories exist on disk

This test module was rewritten in Step 2 to use ``importlib.metadata`` instead
of reading raw ``pyproject.toml`` sections, since the ``[project]``,
``[project.scripts]``, ``[project.optional-dependencies]``,
``[tool.setuptools.packages.find]``, and ``[tool.setuptools.package-data]``
sections were removed from pyproject.toml in Step 2 (packaging is now
declared exclusively in setup.py).
"""

from __future__ import annotations

import importlib
import importlib.metadata
from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pyproject() -> dict:
    """Load pyproject.toml — only [build-system] and [tool.*] remain after Step 2."""
    path = Path(__file__).parent.parent / "pyproject.toml"
    with path.open("rb") as f:
        return tomllib.load(f)


@pytest.fixture(scope="module")
def dist() -> importlib.metadata.Distribution:
    """Return the installed ovwidgets-app distribution metadata."""
    return importlib.metadata.distribution("ovwidgets-app")


# ── Distribution metadata (via importlib.metadata) ────────────────────────────

class TestDistributionMetadata:
    """Verify the installed ovwidgets-app distribution via importlib.metadata."""

    def test_distribution_name(self, dist):
        assert dist.metadata["Name"] == "ovwidgets-app"

    def test_description_set(self, dist):
        desc = dist.metadata["Summary"]
        assert isinstance(desc, str) and len(desc) > 0


# ── Console scripts (via importlib.metadata) ──────────────────────────────────

class TestConsoleScripts:
    """Verify all four console scripts are registered for ovwidgets."""

    @pytest.fixture(scope="class")
    def script_names(self, dist):
        """Set of console-script names registered by ovwidgets."""
        return {ep.name for ep in dist.entry_points if ep.group == "console_scripts"}

    def test_ovwidgets_registered(self, script_names):
        assert "ovwidgets" in script_names

    def test_ovgear_registered(self, script_names):
        """'ovgear' console-script must remain as a compat alias."""
        assert "ovgear" in script_names

    def test_ovwidgets_headless_registered(self, script_names):
        assert "ovwidgets-headless" in script_names

    def test_ovgear_headless_registered(self, script_names):
        """ovgear-headless must remain as a compat alias."""
        assert "ovgear-headless" in script_names

    def test_ovwidgets_points_to_main_sync(self, dist):
        ep = next(
            ep for ep in dist.entry_points
            if ep.group == "console_scripts" and ep.name == "ovwidgets"
        )
        assert ep.value == "ovwidgets.app.__main__:main_sync"

    def test_ovgear_points_to_main_sync(self, dist):
        ep = next(
            ep for ep in dist.entry_points
            if ep.group == "console_scripts" and ep.name == "ovgear"
        )
        assert ep.value == "ovwidgets.app.__main__:main_sync"

    def test_ovwidgets_headless_points_to_headless_main(self, dist):
        ep = next(
            ep for ep in dist.entry_points
            if ep.group == "console_scripts" and ep.name == "ovwidgets-headless"
        )
        assert ep.value == "ovwidgets.app.headless:main"

    def test_ovgear_headless_points_to_headless_main(self, dist):
        ep = next(
            ep for ep in dist.entry_points
            if ep.group == "console_scripts" and ep.name == "ovgear-headless"
        )
        assert ep.value == "ovwidgets.app.headless:main"


# ── Build system (pyproject.toml [build-system] is still present) ─────────────

class TestBuildSystem:
    """Verify [build-system] in pyproject.toml is still correctly configured."""

    def test_build_system_requires_setuptools(self, pyproject):
        requires = pyproject["build-system"]["requires"]
        assert any("setuptools" in r for r in requires)

    def test_build_backend_is_setuptools(self, pyproject):
        backend = pyproject["build-system"]["build-backend"]
        assert "setuptools" in backend

    def test_no_project_section(self, pyproject):
        """[project] must have been removed from pyproject.toml in Step 2."""
        assert "project" not in pyproject

    def test_no_tool_setuptools_section(self, pyproject):
        """[tool.setuptools.*] must have been removed from pyproject.toml in Step 2."""
        tool = pyproject.get("tool", {})
        assert "setuptools" not in tool


# ── Package data (filesystem checks — independent of pyproject.toml) ──────────

class TestPackageData:
    """Verify that icon and SVG asset directories exist on disk."""

    def test_style_icons_directory_exists(self):
        # Step 8/13: icon directories moved from ``ovwidgets/app/style/icons``
        # to ``ovwidgets/common/style/icons``; package-data ownership
        # transferred to ``dist/common/pyproject.toml``.
        icons_dir = Path(__file__).parent.parent / "ovwidgets" / "common" / "style" / "icons"
        assert icons_dir.is_dir()

    def test_style_icons_have_svg_files(self):
        icons_dir = Path(__file__).parent.parent / "ovwidgets" / "common" / "style" / "icons"
        svgs = list(icons_dir.glob("*.svg"))
        assert len(svgs) >= 8


# ── Entry point (module importability) ────────────────────────────────────────

class TestEntryPoint:
    def test_entry_point_module_importable(self):
        mod = importlib.import_module("ovwidgets.app.__main__")
        assert mod is not None

    def test_main_sync_exists(self):
        mod = importlib.import_module("ovwidgets.app.__main__")
        assert hasattr(mod, "main_sync")

    def test_main_sync_is_callable(self):
        mod = importlib.import_module("ovwidgets.app.__main__")
        assert callable(mod.main_sync)

    def test_main_exists_for_backward_compat(self):
        mod = importlib.import_module("ovwidgets.app.__main__")
        assert hasattr(mod, "main")

    def test_main_is_callable(self):
        mod = importlib.import_module("ovwidgets.app.__main__")
        assert callable(mod.main)

    def test_main_sync_is_not_coroutine(self):
        """main_sync must be a regular function (not async) for console_scripts."""
        import asyncio
        mod = importlib.import_module("ovwidgets.app.__main__")
        assert not asyncio.iscoroutinefunction(mod.main_sync)

    def test_main_is_not_coroutine(self):
        import asyncio
        mod = importlib.import_module("ovwidgets.app.__main__")
        assert not asyncio.iscoroutinefunction(mod.main)


# ── __main__.py structure ─────────────────────────────────────────────────────

class TestMainModule:
    def test_module_has_main_async_helper(self):
        mod = importlib.import_module("ovwidgets.app.__main__")
        assert hasattr(mod, "_main_async")

    def test_main_async_is_coroutine_function(self):
        import asyncio
        mod = importlib.import_module("ovwidgets.app.__main__")
        assert asyncio.iscoroutinefunction(mod._main_async)

    def test_module_docstring_or_file_comment(self):
        """Module file must be readable (basic sanity check)."""
        path = Path(__file__).parent.parent / "ovwidgets" / "app" / "__main__.py"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "main_sync" in content
        assert "main" in content

    def test_main_sync_target_in_file(self):
        # The canonical definition lives in ovwidgets.app/__main__.py (Step 3 rename).
        # The ovwidgets.app/__main__.py shim re-exports it.
        path = Path(__file__).parent.parent / "ovwidgets" / "app" / "__main__.py"
        content = path.read_text(encoding="utf-8")
        assert "def main_sync" in content

    def test_dunder_main_guard_exists(self):
        path = Path(__file__).parent.parent / "ovwidgets" / "app" / "__main__.py"
        content = path.read_text(encoding="utf-8")
        assert '__name__ == "__main__"' in content


# ── CLI argument parsing ──────────────────────────────────────────────────────

class TestCliArgs:
    def test_parse_args_no_file(self):
        from ovwidgets.app.__main__ import _parse_args
        ns = _parse_args([])
        assert ns.usd_file is None

    def test_parse_args_positional_file(self):
        from ovwidgets.app.__main__ import _parse_args
        ns = _parse_args(["/tmp/scene.usda"])
        assert ns.usd_file == "/tmp/scene.usda"

    def test_parse_args_help_exits(self):
        from ovwidgets.app.__main__ import _parse_args
        with pytest.raises(SystemExit):
            _parse_args(["--help"])


# ── Windows launcher (scripts/run_ovwidgets_windows.py) ──────────────────────

class TestWindowsLauncher:
    """Verify the Windows bootstrap launcher dispatches to ovwidgets.app, not ovgear."""

    @pytest.fixture(scope="class")
    def launcher_source(self) -> str:
        path = Path(__file__).parent.parent / "scripts" / "run_ovwidgets_windows.py"
        assert path.exists(), "scripts/run_ovwidgets_windows.py must exist"
        return path.read_text(encoding="utf-8")

    def test_launcher_exists(self):
        path = Path(__file__).parent.parent / "scripts" / "run_ovwidgets_windows.py"
        assert path.exists()

    def test_dispatches_to_ovwidgets_app(self, launcher_source):
        assert 'run_module("ovwidgets.app"' in launcher_source

    def test_does_not_dispatch_to_deleted_ovgear(self, launcher_source):
        assert 'run_module("ovgear"' not in launcher_source

    def test_references_ovwidgets_app_in_docstring(self, launcher_source):
        assert "ovwidgets.app.__main__" in launcher_source

    def test_main_function_exists(self, launcher_source):
        assert "def main()" in launcher_source

    def test_bootstrap_function_exists(self, launcher_source):
        assert "def _bootstrap()" in launcher_source


# ── Windows BAT launcher (scripts/ovwidgets-win.bat) ─────────────────────────

class TestWindowsBatFiles:
    """Verify the Windows .bat launcher structure after the ovwidgets rename."""

    @pytest.fixture(scope="class")
    def ovwidgets_bat(self) -> str:
        path = Path(__file__).parent.parent / "scripts" / "ovwidgets-win.bat"
        assert path.exists(), "scripts/ovwidgets-win.bat must exist"
        return path.read_text(encoding="utf-8")

    def test_ovwidgets_bat_exists(self):
        path = Path(__file__).parent.parent / "scripts" / "ovwidgets-win.bat"
        assert path.exists()

    def test_ovwidgets_bat_invokes_python_bootstrap(self, ovwidgets_bat):
        assert "run_ovwidgets_windows.py" in ovwidgets_bat
        assert "run_ovgear_windows.py" not in ovwidgets_bat

    def test_ovwidgets_bat_sets_usd_install_root(self, ovwidgets_bat):
        assert "USD_INSTALL_ROOT" in ovwidgets_bat

    def test_ovwidgets_bat_sets_skip_usd_check(self, ovwidgets_bat):
        assert "OVRTX_SKIP_USD_CHECK" in ovwidgets_bat
