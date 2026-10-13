# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Validate one clean-install package contract from built wheels."""

from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path
from types import ModuleType

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _assert_requirement(distribution: str, requirement: str) -> None:
    requirements = metadata.requires(distribution) or []
    assert requirement in requirements, (
        f"{distribution} does not declare {requirement!r}: {requirements!r}"
    )


def _assert_installed_module(module: ModuleType) -> Path:
    module_path = Path(module.__file__).resolve()
    assert not module_path.is_relative_to(_REPOSITORY_ROOT), (
        f"{module.__name__} was imported from the source checkout: {module_path}"
    )
    return module_path


def _validate_common() -> None:
    import numpy
    import ovui_data_adapters.common as common
    import ovui_data_adapters.common._livestream_tap as livestream

    _assert_requirement("ovui-data-adapters-common", "numpy>=1.20")
    assert "ovstream" not in sys.modules, (
        "common import eagerly loaded optional ovstream"
    )

    try:
        metadata.version("ovui-data-adapters-openusd")
    except metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError(
            "common-only environment unexpectedly contains the OpenUSD adapter"
        )

    print(
        "common clean install OK:",
        _assert_installed_module(common),
        _assert_installed_module(livestream),
        _assert_installed_module(numpy),
    )


def _validate_aggregate() -> None:
    import ovui_data_adapters.openusd as openusd
    import ovui_widgets.app as app
    import ovui_widgets.common.keyboard as keyboard
    import ovui_widgets.viewport.inspector as viewport_inspector
    from pxr import Usd

    _assert_requirement(
        "ovui-widgets-all",
        f"ovui-data-adapters-openusd[standalone]=={metadata.version('ovui-widgets-all')}",
    )
    assert metadata.version("usd-core") == "25.11"
    # Inspector commands need pydantic, which the Inspector skill installs; the
    # Viewer packages neither require nor import it.
    for distribution in ("ovui-widgets-app", "ovui-widgets-viewport"):
        requirements = metadata.requires(distribution) or []
        assert not any(r.split(";")[0].strip().startswith("pydantic") for r in requirements), (
            f"{distribution} requires pydantic: {requirements!r}"
        )
    assert "pydantic" not in sys.modules, "importing the Viewer loaded pydantic"
    assert Usd.Stage.CreateInMemory() is not None

    print(
        "ovui-widgets-all clean install OK:",
        _assert_installed_module(openusd),
        _assert_installed_module(app),
        _assert_installed_module(keyboard),
        _assert_installed_module(viewport_inspector),
        Path(Usd.__file__).resolve(),
    )
    # Import-only checks miss packages imported lazily by run_async(). Exercise
    # the installed app's real window construction and frame loop in isolation.
    if sys.platform == "win32":
        # The hosted Windows runner has the Vulkan loader but no Vulkan driver,
        # so the app cannot start there.
        return
    with tempfile.TemporaryDirectory(prefix="ovui-wheel-startup-") as workdir:
        env = dict(os.environ)
        env.update(
            OMNIUI_HEADLESS="1",
            OMNIUI_BACKEND="vulkan",
            OVUIINSPECT_ENABLED="0",
            OVUI_DATA_ADAPTER_PROVIDER="openusd",
            # The aggregate install has no ovrtx; start without a renderer.
            OVUI_WIDGETS_REQUIRE_OVRTX="0",
            PYTHONPATH="",
            OVUI_WIDGETS_SETTINGS_PATH=str(Path(workdir) / "settings.json"),
            OVUI_CHECK_LAYOUT_PATH=str(Path(workdir) / "layout.json"),
        )
        startup = subprocess.run(
            [sys.executable, "-c", r'''
import os
import sys
from pathlib import Path

vulkan_dir = os.environ.get("Vulkan_DLL_DIR")
if vulkan_dir and hasattr(os, "add_dll_directory"):
    dll_directory = os.add_dll_directory(vulkan_dir)

import ovui_widgets.app.application as application

assert not Path(application.__file__).resolve().is_relative_to(Path(sys.argv[1]))
# Keep every file this check writes inside its temporary folder.
app = application.Application(
    headless=True,
    settings_overrides={"layout.save_path": os.environ["OVUI_CHECK_LAYOUT_PATH"]},
)
frames = 0
original = app._run_headless_export_hook

def after_frame():
    global frames
    original()
    frames += 1
    if frames == 3:
        print("INSTALLED_APP_STARTUP_OK", flush=True)
        app.request_exit()

app._run_headless_export_hook = after_frame
app.run()
''', str(_REPOSITORY_ROOT)],
            cwd=workdir, env=env, capture_output=True, text=True, timeout=90,
        )
    assert startup.returncode == 0 and "INSTALLED_APP_STARTUP_OK" in startup.stdout, (
        f"installed app startup failed ({startup.returncode})\n"
        f"{startup.stdout}\n{startup.stderr}"
    )
    print("installed app startup smoke OK")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract", choices=("common", "aggregate"))
    args = parser.parse_args()

    if args.contract == "common":
        _validate_common()
    else:
        # The Windows runner has the Vulkan loader installed outside the wheel.
        # Match the native-test bootstrap and retain the directory handle through
        # imports; Python 3.8+ does not search PATH for extension dependencies.
        with contextlib.ExitStack() as stack:
            if sys.platform == "win32":
                loader_dir = Path(os.environ["Vulkan_DLL_DIR"]).resolve(strict=True)
                assert (loader_dir / "vulkan-1.dll").is_file(), loader_dir
                stack.enter_context(os.add_dll_directory(str(loader_dir)))
            _validate_aggregate()


if __name__ == "__main__":
    main()
