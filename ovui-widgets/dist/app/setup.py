# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


def _read_project_version() -> str:
    for parent in Path(__file__).resolve().parents:
        version_file = parent / "VERSION.md"
        if version_file.is_file():
            version = version_file.read_text(encoding="utf-8").strip()
            if version:
                return version
            raise RuntimeError(f"{version_file} is empty")
    raise RuntimeError("VERSION.md was not found")


def _find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "skills").is_dir() and (parent / "VERSION.md").is_file():
            return parent
    raise RuntimeError("ovui repository root was not found")


class BuildPyWithAgentSkills(build_py):
    """Bundle application skills while preserving the repo's skill layout."""

    def run(self) -> None:
        super().run()
        repo_root = _find_repo_root()
        target_root = Path(self.build_lib) / "ovui_widgets_agent_skills" / "skills"
        for skill_name in (
            "omniverse-ui-widgets",
            "omniverse-ui-styling",
            "omniverse-ui-widgets-app",
        ):
            source = repo_root / "skills" / skill_name
            target = target_root / skill_name
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)


setup(
    version=_read_project_version(),
    cmdclass={"build_py": BuildPyWithAgentSkills},
)
