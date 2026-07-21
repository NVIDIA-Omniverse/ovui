# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Discovery and filesystem installation for Agent Skills shipped with ovui."""

from __future__ import annotations

import argparse
import shutil
from collections.abc import Iterable
from importlib.metadata import EntryPoint, entry_points
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path


ENTRY_POINT_GROUP = "ovui.skills"


def get_omniverse_ui_apis_skill() -> Traversable:
    """Return the packaged ``omniverse-ui-apis`` skill directory."""

    return files(__package__).joinpath("skills", "omniverse-ui-apis")


def get_omniverse_ui_inspector_skill() -> Traversable:
    """Return the packaged ``omniverse-ui-inspector`` skill directory."""

    return files(__package__).joinpath("skills", "omniverse-ui-inspector")


def _installed_skill_entry_points() -> dict[str, EntryPoint]:
    discovered: dict[str, EntryPoint] = {}
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        if entry_point.name in discovered:
            raise ValueError(f"duplicate installed skill name: {entry_point.name}")
        discovered[entry_point.name] = entry_point
    return discovered


def _copy_resource_tree(source: Traversable, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            _copy_resource_tree(child, target)
        else:
            target.write_bytes(child.read_bytes())


def _validate_skill_name(name: str) -> None:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise ValueError(f"invalid skill name: {name!r}")


def default_skill_root() -> Path:
    """Return the default filesystem skill root used by Agent Skills clients."""

    return Path.home() / ".agents" / "skills"


def install_skills(
    target_root: Path,
    names: Iterable[str] | None = None,
    *,
    force: bool = False,
) -> list[Path]:
    """Copy selected installed ovui skills into ``target_root``."""

    providers = _installed_skill_entry_points()
    selected_names = sorted(providers) if names is None else list(names)
    if not selected_names:
        selected_names = sorted(providers)

    target_root = target_root.expanduser().resolve()
    prepared: list[tuple[str, Traversable, Path]] = []
    for name in selected_names:
        _validate_skill_name(name)
        entry_point = providers.get(name)
        if entry_point is None:
            available = ", ".join(sorted(providers)) or "none"
            raise ValueError(f"unknown skill {name!r}; installed skills: {available}")

        provider = entry_point.load()
        if not callable(provider):
            raise TypeError(f"skill provider {name!r} is not callable")
        source = provider()
        if not source.joinpath("SKILL.md").is_file():
            raise ValueError(f"skill provider {name!r} does not contain SKILL.md")

        destination = target_root / name
        if destination.exists() and not force:
            raise FileExistsError(
                f"{destination} already exists. Use --force to replace it."
            )
        prepared.append((name, source, destination))

    installed: list[Path] = []
    for _name, source, destination in prepared:
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        _copy_resource_tree(source, destination)
        installed.append(destination)
    return installed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ovui-skill",
        description="List or install Agent Skills provided by ovui wheels.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list", help="List installed ovui skill providers.")

    install_parser = subparsers.add_parser(
        "install",
        help="Copy installed skills to an Agent Skills directory.",
    )
    install_parser.add_argument(
        "skills",
        nargs="*",
        help="Skill names to install. The default is every installed ovui skill.",
    )
    install_parser.add_argument(
        "--target",
        type=Path,
        default=default_skill_root(),
        help="Root skill directory. Default: ~/.agents/skills",
    )
    install_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing skill directories.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "list":
        for name, entry_point in sorted(_installed_skill_entry_points().items()):
            distribution = entry_point.dist.name if entry_point.dist is not None else "unknown"
            print(f"{name}\t{distribution}")
        return 0

    try:
        destinations = install_skills(
            args.target,
            args.skills or None,
            force=args.force,
        )
    except (FileExistsError, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))

    for destination in destinations:
        print(f"Installed {destination.name} at {destination}")
    return 0


__all__ = [
    "ENTRY_POINT_GROUP",
    "default_skill_root",
    "get_omniverse_ui_apis_skill",
    "get_omniverse_ui_inspector_skill",
    "install_skills",
    "main",
]
