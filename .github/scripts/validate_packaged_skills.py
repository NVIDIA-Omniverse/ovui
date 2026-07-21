# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Validate Agent Skills from installed ovui-family wheels."""

from __future__ import annotations

import argparse
import re
import tempfile
from importlib import metadata
from pathlib import Path


ENTRY_POINT_GROUP = "ovui.skills"
EXPECTED_SKILLS = {
    "omniverse-ui-apis": {
        "distribution": "ovui",
        "files": (
            "SKILL.md",
            "references/inputs-windows-viewport.md",
            "references/layout.md",
            "references/model-view-tree.md",
            "references/recipes.md",
        ),
    },
    "omniverse-ui-widgets": {
        "distribution": "ovui-widgets-app",
        "files": (
            "SKILL.md",
            "references/app-skeleton.md",
            "references/menu-and-qa.md",
            "references/runtime-environment.md",
            "references/source-map.md",
            "references/usd-and-dataflow.md",
        ),
    },
    "omniverse-ui-styling": {
        "distribution": "ovui-widgets-app",
        "files": (
            "SKILL.md",
            "references/centralized-style-module.md",
            "references/developer-guide.md",
            "references/global-styles-and-startup.md",
            "references/naming-constants.md",
            "references/naming-selectors.md",
            "references/style-hierarchy.md",
            "references/style-mechanics.md",
            "references/target-architecture.md",
        ),
    },
    "omniverse-ui-widgets-app": {
        "distribution": "ovui-widgets-app",
        "files": ("SKILL.md",),
    },
    "omniverse-ui-inspector": {
        "distribution": "ovui",
        "files": (
            "SKILL.md",
            "requirements.txt",
            "ovuiinspect/__init__.py",
            "references/api-endpoints.md",
            "references/coordinate-system.md",
            "scripts/ovui-inspect",
            "scripts/ovui-inspect.py",
        ),
    },
}
EXPECTED_CONSOLE_SCRIPTS = {
    "ovui-skill": "ovui",
    "ovui-widgets-skill": "ovui-widgets-app",
}


def _canonicalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _front_matter_value(content: str, key: str, *, indented: bool = False) -> str:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise AssertionError("SKILL.md has no YAML front matter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise AssertionError("SKILL.md front matter is not terminated") from exc

    indentation = r"\s+" if indented else ""
    pattern = re.compile(rf"^{indentation}{re.escape(key)}:\s*(.+?)\s*$")
    for line in lines[1:end]:
        match = pattern.match(line)
        if match:
            return _unquote(match.group(1))
    raise AssertionError(f"SKILL.md front matter has no {key!r} value")


def _entry_points(group: str) -> list[metadata.EntryPoint]:
    return list(metadata.entry_points(group=group))


def _select_unique(
    entry_points: list[metadata.EntryPoint],
    name: str,
) -> metadata.EntryPoint:
    matches = [entry_point for entry_point in entry_points if entry_point.name == name]
    assert len(matches) == 1, f"expected one {name!r} entry point, found {len(matches)}"
    return matches[0]


def _validate_skill(name: str, entry_point: metadata.EntryPoint) -> None:
    expectation = EXPECTED_SKILLS[name]
    expected_distribution = str(expectation["distribution"])
    actual_distribution = entry_point.dist.name if entry_point.dist is not None else ""
    assert _canonicalize(actual_distribution) == _canonicalize(expected_distribution), (
        f"{name}: expected distribution {expected_distribution!r}, got {actual_distribution!r}"
    )

    provider = entry_point.load()
    assert callable(provider), f"{name}: entry-point provider is not callable"
    root = provider()
    assert root.name == name, f"{name}: provider returned directory {root.name!r}"

    for relative_path in expectation["files"]:
        resource = root.joinpath(*str(relative_path).split("/"))
        assert resource.is_file(), f"{name}: missing packaged file {relative_path}"

    skill_text = root.joinpath("SKILL.md").read_text(encoding="utf-8")
    assert _front_matter_value(skill_text, "name") == name
    assert _canonicalize(
        _front_matter_value(skill_text, "python-distribution", indented=True)
    ) == _canonicalize(expected_distribution)

    skill_version = _front_matter_value(skill_text, "version", indented=True)
    wheel_version = metadata.version(expected_distribution)
    assert skill_version == wheel_version, (
        f"{name}: skill version {skill_version!r} does not match "
        f"{expected_distribution} {wheel_version!r}"
    )


def _validate_console_scripts(expected_skills: list[str]) -> dict[str, metadata.EntryPoint]:
    required_distributions = {
        str(EXPECTED_SKILLS[name]["distribution"]) for name in expected_skills
    }
    scripts = _entry_points("console_scripts")
    selected: dict[str, metadata.EntryPoint] = {}
    for script_name, distribution in EXPECTED_CONSOLE_SCRIPTS.items():
        if distribution not in required_distributions:
            continue
        entry_point = _select_unique(scripts, script_name)
        actual_distribution = entry_point.dist.name if entry_point.dist is not None else ""
        assert _canonicalize(actual_distribution) == _canonicalize(distribution), (
            f"{script_name}: expected distribution {distribution!r}, "
            f"got {actual_distribution!r}"
        )
        assert callable(entry_point.load()), f"{script_name}: entry point is not callable"
        selected[script_name] = entry_point
    return selected


def _validate_installers(
    expected_skills: list[str],
    scripts: dict[str, metadata.EntryPoint],
) -> None:
    with tempfile.TemporaryDirectory(prefix="ovui-packaged-skills-") as temp_dir:
        target = Path(temp_dir) / "all"
        if "ovui-skill" in scripts:
            result = scripts["ovui-skill"].load()(
                ["install", *expected_skills, "--target", str(target)]
            )
            assert result == 0, f"ovui-skill returned {result!r}"
            for name in expected_skills:
                assert (target / name / "SKILL.md").is_file(), name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--expected",
        nargs="+",
        choices=sorted(EXPECTED_SKILLS),
        default=sorted(EXPECTED_SKILLS),
        help="Packaged skills expected in the current environment.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    expected_skills = list(dict.fromkeys(args.expected))
    skill_entry_points = _entry_points(ENTRY_POINT_GROUP)
    for name in expected_skills:
        _validate_skill(name, _select_unique(skill_entry_points, name))

    scripts = _validate_console_scripts(expected_skills)
    _validate_installers(expected_skills, scripts)
    print(f"packaged skills OK: {', '.join(expected_skills)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
