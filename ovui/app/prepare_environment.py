# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Prepare the CMake-owned Windows app environment using the existing packages."""

import argparse
import os
from pathlib import Path
import subprocess
import tomllib
import venv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument(
        "--build-env", action="append", default=[], metavar="NAME=VALUE",
        help="environment value for the package builds, for example the ovui SDK folder",
    )
    parser.add_argument(
        "--require-renderer-factory", default=None, metavar="NAME",
        help=(
            "verify the installed packages register exactly one "
            "ovui_data_adapters.native_renderer_factories entry point with this "
            "name. ovui names no provider; CMake passes the selected one."
        ),
    )
    parser.add_argument("projects", nargs="+")
    args = parser.parse_args()
    repo = args.repo.resolve()
    environment = args.environment.resolve()
    python = environment / "Scripts" / "python.exe"
    if not python.is_file():
        venv.create(environment, with_pip=True)

    # Do not let another checkout's PYTHONPATH supply package metadata to pip.
    child_env = os.environ.copy()
    child_env.pop("PYTHONPATH", None)
    child_env["PYTHONNOUSERSITE"] = "1"
    # A package with a native part reads these, for example the folder that
    # holds the ovui SDK its module is built against.
    for item in args.build_env:
        name, _, value = item.partition("=")
        if not name:
            raise SystemExit(f"--build-env needs NAME=VALUE, got {item!r}")
        child_env[name] = value
    projects = [repo / project for project in args.projects]
    build_requires = set()
    for project in [repo / "ovui", *projects]:
        metadata = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
        build_requires.update(metadata["build-system"]["requires"])
    subprocess.run(
        [str(python), "-m", "pip", "install", *sorted(build_requires)],
        env=child_env, check=True,
    )

    # CMake owns the in-place native ovui build. Generate its real setuptools
    # metadata so pip can resolve the app without installing a second ovui wheel
    # or recursively invoking the native build through setup.py's build_ext.
    native_metadata = environment / "native-metadata"
    native_metadata.mkdir(exist_ok=True)
    subprocess.run(
        [str(python), "setup.py", "egg_info", "--egg-base", str(native_metadata)],
        cwd=repo / "ovui", env=child_env, check=True,
    )
    child_env["PYTHONPATH"] = os.pathsep.join((str(native_metadata), str(repo / "ovui/python")))
    install_args = [str(python), "-m", "pip", "install", "--no-build-isolation"]
    for project in projects:
        install_args.extend(("--editable", str(project)))
    subprocess.run(install_args, env=child_env, check=True)
    subprocess.run([str(python), "-m", "pip", "check"], env=child_env, check=True)
    if args.require_renderer_factory:
        subprocess.run(
            [str(python), "-c", (
                "import sys; "
                "from importlib.metadata import entry_points; "
                "name = sys.argv[1]; "
                "points = entry_points(group='ovui_data_adapters.native_renderer_factories'); "
                "found = [p for p in points if p.name == name]; "
                "assert len(found) == 1, "
                "f'Expected exactly one {name} early-renderer factory, found {len(found)}'"
            ), args.require_renderer_factory],
            env=child_env, check=True,
        )


if __name__ == "__main__":
    main()
