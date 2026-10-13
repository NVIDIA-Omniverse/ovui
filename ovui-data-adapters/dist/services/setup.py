# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from setuptools import setup


def _read_project_version() -> str:
    for parent in Path(__file__).resolve().parents:
        version_file = parent / "VERSION.md"
        if version_file.is_file():
            version = version_file.read_text(encoding="utf-8").strip()
            if version:
                return version
            raise RuntimeError(f"{version_file} is empty")
    raise RuntimeError("VERSION.md was not found")


_VERSION = _read_project_version()

# First-party packages are released together from one VERSION.md. Pin them
# to this version so that pip cannot install a mix of releases.
setup(
    version=_VERSION,
    install_requires=[
        f"ovui-data-adapters-common=={_VERSION}",
    ],
)
