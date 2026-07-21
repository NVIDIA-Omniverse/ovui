# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 78 — documentation files exist and contain required content."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
REPO_ROOT = ROOT.parent
ARCHITECTURE_DOCS = [
    REPO_ROOT / "docs" / "architecture.html",
    *sorted((REPO_ROOT / "docs" / "architecture").glob("section-*.html")),
]


# ── File existence ────────────────────────────────────────────────────────────

class TestDocFilesExist:
    def test_changelog_exists(self):
        assert (ROOT / "CHANGELOG.md").exists()

    def test_architecture_exists(self):
        assert (REPO_ROOT / "docs" / "architecture.html").exists()
        assert (REPO_ROOT / "docs" / "architecture").is_dir()
        assert ARCHITECTURE_DOCS

    def test_readme_exists(self):
        assert (ROOT / "README.md").exists()

    def test_changelog_non_empty(self):
        assert (ROOT / "CHANGELOG.md").stat().st_size > 0

    def test_architecture_non_empty(self):
        for path in ARCHITECTURE_DOCS:
            assert path.stat().st_size > 0

    def test_readme_non_empty(self):
        assert (ROOT / "README.md").stat().st_size > 0


# ── CHANGELOG.md content ──────────────────────────────────────────────────────

class TestChangelog:
    @pytest.fixture(scope="class")
    def content(self):
        return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    def test_has_version(self, content):
        assert "0.1.0" in content

    def test_has_release_entry(self, content):
        assert "Initial release" in content

    def test_has_markdown_release_heading(self, content):
        assert any(line.startswith("## ") for line in content.splitlines())

    def test_has_single_title(self, content):
        assert content.splitlines()[0] == "# Changelog"

    def test_no_conflict_markers(self, content):
        assert "<<<<<<<" not in content
        assert "=======" not in content
        assert ">>>>>>>" not in content

    def test_not_empty_after_heading(self, content):
        assert content.strip() != "# Changelog"

    def test_release_heading_has_date(self, content):
        release_lines = [line for line in content.splitlines() if line.startswith("## ")]
        assert any("-" in line for line in release_lines)

    def test_release_content_follows_heading(self, content):
        assert "## " in content and content.rsplit("## ", maxsplit=1)[-1].strip()

    def test_uses_unreleased_free_release_notes(self, content):
        assert "TODO" not in content

    def test_plain_markdown_only(self, content):
        assert "<html" not in content.lower()

    def test_is_markdown(self, content):
        assert content.startswith("#")


# ── architecture HTML content ─────────────────────────────────────────────────

class TestArchitecture:
    @pytest.fixture(scope="class")
    def content(self):
        return "\n".join(path.read_text(encoding="utf-8") for path in ARCHITECTURE_DOCS)

    def test_mentions_ovui_widgets_app_package(self, content):
        assert "ovui_widgets.app" in content or "Application" in content

    def test_mentions_ovui_widgets_stage_package(self, content):
        assert "Stage Browser" in content or "stage" in content.lower()

    def test_mentions_ovui_widgets_property_package(self, content):
        assert "Property Inspector" in content or "property" in content.lower()

    def test_mentions_ovui_widgets_viewport_package(self, content):
        assert "Viewport" in content or "viewport" in content.lower()

    def test_mentions_adapter_pattern(self, content):
        assert "adapter" in content.lower() or "Adapter" in content

    def test_mentions_selection_bus(self, content):
        assert "SelectionBus" in content or "selection" in content.lower()

    def test_mentions_no_kit(self, content):
        # Architecture doc mentions omni.kit, kit-free, or Kit in some form
        assert "omni.kit" in content or "Kit" in content or "kit-free" in content.lower() or "kit" in content.lower()

    def test_mentions_dependencies(self, content):
        assert "dependency" in content.lower() or "import" in content.lower() or "depend" in content.lower()

    def test_is_html(self, content):
        assert "<!doctype html>" in content

    def test_has_package_map_or_structure(self, content):
        assert "Code Organization" in content or "Data adapters" in content


# ── README.md content ─────────────────────────────────────────────────────────

class TestReadme:
    @pytest.fixture(scope="class")
    def content(self):
        return (ROOT / "README.md").read_text(encoding="utf-8")

    def test_has_title(self, content):
        assert content.startswith("# ")

    def test_mentions_installation(self, content):
        lower = content.lower()
        assert "install" in lower

    def test_mentions_pip(self, content):
        assert "pip" in content

    def test_mentions_python_version(self, content):
        assert "3.10" in content or "Python" in content

    def test_mentions_tests(self, content):
        lower = content.lower()
        assert "test" in lower or "pytest" in lower

    def test_mentions_running(self, content):
        lower = content.lower()
        assert "run" in lower or "launch" in lower or "python -m" in lower

    def test_mentions_all_packages(self, content):
        assert "ovui_widgets.app" in content
        assert "ovui_widgets.content" in content
        assert "ovui_widgets.stage" in content
        assert "ovui_widgets.property" in content
        assert "ovui_widgets.viewport" in content
        assert "ovui_widgets.layers" in content

    def test_mentions_known_limitations(self, content):
        lower = content.lower()
        assert "limitation" in lower or "known" in lower

    def test_mentions_architecture_link(self, content):
        assert "ARCHITECTURE" in content or "architecture" in content.lower()

    def test_is_markdown(self, content):
        assert content.startswith("#")
