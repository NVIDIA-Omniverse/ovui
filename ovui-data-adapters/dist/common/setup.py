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


setup(version=_read_project_version())
