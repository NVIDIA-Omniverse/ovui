# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Help > About component versions."""

from __future__ import annotations

from importlib import metadata

import pytest

from ovui_widgets.app import about_dialog


@pytest.fixture
def no_ovrtx_distribution(monkeypatch):
    real_version = metadata.version

    def version(distribution):
        if distribution == "ovrtx":
            raise metadata.PackageNotFoundError(distribution)
        return real_version(distribution)

    monkeypatch.setattr(about_dialog.metadata, "version", version)


def test_ovrtx_version_comes_from_ovrtx_root(tmp_path, monkeypatch, no_ovrtx_distribution):
    package_dir = tmp_path / "python" / "ovrtx"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(
        'import _native_runtime_not_loaded\n__version__ = "9.8.7"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("OVRTX_ROOT", str(tmp_path))

    assert dict(about_dialog.installed_component_versions())["ovrtx"] == "9.8.7"

