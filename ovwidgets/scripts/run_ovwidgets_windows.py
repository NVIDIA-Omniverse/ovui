# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Windows launcher for OvWidgets / OvGear.

On Linux the README relies on LD_LIBRARY_PATH + PYTHONPATH to point at the
custom USD build. On Windows, Python 3.8+ ignores PATH for extension-module
DLL resolution — we have to call os.add_dll_directory() explicitly. This
shim does that bootstrap before handing off to ovwidgets.app.__main__.

Usage (via the ovwidgets-win.bat or ovgear-win.bat wrapper, or directly inside _venv312):

    python scripts/run_ovgear_windows.py [usd_file]

Env vars honored (all optional, sensible defaults):
    USD_INSTALL_ROOT   root of the custom OpenUSD 25.11 install
                       (default: C:\\dev\\usd-build\\install)
    OVRTX_ROOT         root of the local ovrtx checkout
                       (default: C:\\dev\\ovrtx)
    OVRTX_BIN_DIR      optional directory containing ovrtx-dynamic.dll
    OVRTX_SKIP_USD_CHECK  forced to "1" (required by ovrtx + pxr coexistence)
"""

import os
import runpy
import sys
from pathlib import Path


def _prepend_env_paths(name: str, paths: list[Path]) -> None:
    existing = [p for p in os.environ.get(name, "").split(os.pathsep) if p]
    new_paths = [str(p) for p in paths if p.exists()]
    seen: set[str] = set()
    merged: list[str] = []
    for p in new_paths + existing:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key)
            merged.append(p)
    if merged:
        os.environ[name] = os.pathsep.join(merged)


def _usd_plugin_dirs(runtime_dir: Path) -> list[Path]:
    plugin_root = runtime_dir / "usd_plugins"
    if not plugin_root.is_dir():
        return []
    return [p for p in plugin_root.iterdir() if p.is_dir()]


def _bootstrap() -> None:
    # ovrtx refuses to import if pxr is already loaded unless this is set.
    os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")

    ovrtx_root = Path(os.environ.get("OVRTX_ROOT", r"C:\dev\ovrtx"))
    ovrtx_python = ovrtx_root / "python"
    if ovrtx_python.is_dir():
        sys.path.insert(0, str(ovrtx_python))
        os.environ["PYTHONPATH"] = str(ovrtx_python) + os.pathsep + os.environ.get("PYTHONPATH", "")

    ovrtx_bin_dirs = []
    if os.environ.get("OVRTX_BIN_DIR"):
        ovrtx_bin_dirs.append(Path(os.environ["OVRTX_BIN_DIR"]))
    ovrtx_bin_dirs.extend([ovrtx_root / "bin", ovrtx_python / "ovrtx" / "bin"])
    ovrtx_runtime_dirs = []
    for d in ovrtx_bin_dirs:
        if d.is_dir():
            os.add_dll_directory(str(d))
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            if (d / "ovrtx-dynamic.dll").is_file():
                ovrtx_runtime_dirs.append(d)

    if ovrtx_runtime_dirs:
        runtime_dir = ovrtx_runtime_dirs[0]
        os.environ.setdefault("OMNI_PLUGINS_BASE_PATH", str(runtime_dir))
        os.environ.setdefault("OMNI_USD_PLUGINS_BASE_PATH", str(runtime_dir))
        _prepend_env_paths(
            "PXR_PLUGINPATH_NAME",
            [plugin_dir for d in ovrtx_runtime_dirs for plugin_dir in _usd_plugin_dirs(d)],
        )

    usd_root = Path(os.environ.get("USD_INSTALL_ROOT", r"C:\dev\usd-build\install"))
    if not usd_root.is_dir():
        sys.stderr.write(
            f"USD_INSTALL_ROOT ({usd_root}) does not exist. "
            "Build OpenUSD first (see WINDOWS-BUILD.md).\n"
        )
        sys.exit(1)

    # 1. Make the pxr python package importable.
    python_pkg = usd_root / "lib" / "python"
    sys.path.insert(0, str(python_pkg))

    # 2. Register the native USD DLL directories with the Windows loader so
    # pxr/_tf.pyd etc. can resolve their dependencies. This is the Windows
    # equivalent of LD_LIBRARY_PATH=<root>/lib on Linux.
    for sub in ("lib", "bin"):
        d = usd_root / sub
        if d.is_dir():
            os.add_dll_directory(str(d))
            # Mirror into PATH too, so child processes (if any) inherit it.
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")


def main() -> None:
    _bootstrap()
    sys.argv[0] = "ovgear"
    runpy.run_module("ovwidgets.app", run_name="__main__")


if __name__ == "__main__":
    main()
