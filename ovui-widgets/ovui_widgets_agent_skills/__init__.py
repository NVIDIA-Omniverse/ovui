# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Agent Skill resource providers for the ``ovui-widgets-app`` wheel."""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable


def get_omniverse_ui_widgets_skill() -> Traversable:
    """Return the packaged ``omniverse-ui-widgets`` skill directory."""

    return files(__package__).joinpath("skills", "omniverse-ui-widgets")


def get_omniverse_ui_styling_skill() -> Traversable:
    """Return the packaged ``omniverse-ui-styling`` skill directory."""

    return files(__package__).joinpath("skills", "omniverse-ui-styling")


def get_omniverse_ui_widgets_app_skill() -> Traversable:
    """Return the packaged ``omniverse-ui-widgets-app`` skill directory."""

    return files(__package__).joinpath("skills", "omniverse-ui-widgets-app")


def main(argv: list[str] | None = None) -> int:
    """Run the shared ovui skill installer for the installed widget skills."""

    from ovui_agent_skills import main as install_main

    return install_main(argv)


__all__ = [
    "get_omniverse_ui_styling_skill",
    "get_omniverse_ui_widgets_app_skill",
    "get_omniverse_ui_widgets_skill",
    "main",
]
