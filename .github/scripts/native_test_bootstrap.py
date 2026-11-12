# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run pytest on Windows after the native ovui modules load with the Vulkan loader registered.

Usage: python native_test_bootstrap.py <pytest arguments>
"""

import importlib
import os
from pathlib import Path
import sys

import pytest


def fail(message):
    print(f"[native-test-bootstrap] ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(2)


if sys.platform != "win32":
    fail(f"Windows is required, but sys.platform is {sys.platform!r}")

add_dll_directory = getattr(os, "add_dll_directory", None)
if not callable(add_dll_directory):
    fail("callable os.add_dll_directory is required")

raw_vulkan_dir = os.environ.get("Vulkan_DLL_DIR")
if raw_vulkan_dir is None or not raw_vulkan_dir.strip():
    fail("Vulkan_DLL_DIR must name the directory containing vulkan-1.dll")

try:
    vulkan_dir = Path(raw_vulkan_dir).expanduser().resolve(strict=True)
except OSError as exc:
    fail(f"Vulkan_DLL_DIR does not resolve to an existing directory: {raw_vulkan_dir!r}: {exc}")
if not vulkan_dir.is_dir():
    fail(f"Vulkan_DLL_DIR is not a directory: {vulkan_dir}")

vulkan_dll = vulkan_dir / "vulkan-1.dll"
if not vulkan_dll.is_file():
    fail(f"Vulkan loader DLL is missing: {vulkan_dll}")
vulkan_dll = vulkan_dll.resolve(strict=True)

try:
    _DLL_DIRECTORY_HANDLES = [add_dll_directory(str(vulkan_dir))]
except OSError as exc:
    fail(f"could not register Vulkan DLL directory {vulkan_dir}: {exc}")

# A script normally puts its own directory at sys.path[0]. Match
# `python -m pytest` by restoring the invocation's working directory.
if sys.path:
    sys.path[0] = os.getcwd()
else:
    sys.path.append(os.getcwd())

print(f"[native-test-bootstrap] registered Vulkan DLL directory: {vulkan_dir}", flush=True)
print(f"[native-test-bootstrap] verified Vulkan loader: {vulkan_dll}", flush=True)
print(f"[native-test-bootstrap] pytest working directory: {os.getcwd()}", flush=True)

try:
    ui = importlib.import_module("omni.ui")
    ui_native = importlib.import_module("omni.ui._ui")
    ui_scene = importlib.import_module("omni.ui_scene")
    scene_native = importlib.import_module("omni.ui_scene._scene")
except Exception as exc:
    fail(
        "native ovui preflight failed after registering "
        f"{vulkan_dir}: {type(exc).__name__}: {exc}"
    )

print(f"[native-test-bootstrap] omni.ui package: {ui.__file__}", flush=True)
print(f"[native-test-bootstrap] omni.ui._ui native module: {ui_native.__file__}", flush=True)
print(f"[native-test-bootstrap] omni.ui_scene package: {ui_scene.__file__}", flush=True)
print(f"[native-test-bootstrap] omni.ui_scene._scene native module: {scene_native.__file__}", flush=True)

raise SystemExit(pytest.main(sys.argv[1:]))
