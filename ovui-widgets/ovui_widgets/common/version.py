# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Version helpers shared by ovui-widgets packages."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def package_version(distribution_name: str) -> str:
    repo_version = _read_repo_version()
    if repo_version is not None:
        return repo_version
    try:
        return version(distribution_name)
    except PackageNotFoundError as exc:
        raise RuntimeError("VERSION.md was not found in this source checkout") from exc


def _read_repo_version() -> str | None:
    for parent in Path(__file__).resolve().parents:
        version_file = parent / "VERSION.md"
        if version_file.is_file():
            version_text = version_file.read_text(encoding="utf-8").strip()
            if version_text:
                return version_text
            raise RuntimeError(f"{version_file} is empty")
    return None
