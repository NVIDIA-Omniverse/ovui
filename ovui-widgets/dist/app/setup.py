# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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


_VERSION = _read_project_version()

# First-party packages are released together from one VERSION.md. Pin them
# to this version so that pip cannot install a mix of releases.
setup(
    version=_VERSION,
    install_requires=[
        f"ovui=={_VERSION}",
        f"ovui-widgets-common[testing]=={_VERSION}",
        f"ovui-widgets-stage=={_VERSION}",
        f"ovui-widgets-layers=={_VERSION}",
        f"ovui-widgets-content=={_VERSION}",
        f"ovui-widgets-property=={_VERSION}",
        f"ovui-widgets-viewport=={_VERSION}",
        f"ovui-data-adapters-common=={_VERSION}",
    ],
    cmdclass={"build_py": BuildPyWithAgentSkills},
)
