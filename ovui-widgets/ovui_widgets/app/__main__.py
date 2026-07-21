# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

import argparse
import sys
from typing import List, Optional


async def _main_async() -> None:
    """Cooperative entry point for embedding OvGear in an existing asyncio loop.

    Callers are responsible for the synchronous bootstrap (write_split_ini,
    ui.init, style setup) before awaiting this coroutine. For a standalone
    launch use :func:`main`, which delegates to :meth:`Application.run`.
    """
    from ovui_widgets.app.application import Application

    app = Application()
    app._running = True
    try:
        await app.run_async()
    finally:
        app._running = False


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    from ovui_widgets.app.cli_settings import extract_setting_overrides

    parser = argparse.ArgumentParser(
        description="OvGear — standalone 3D USD viewer",
        epilog=(
            "Settings overrides: any --/path/to/key=value argument sets the "
            "corresponding dotted setting at launch (e.g. --/ui/theme=light "
            "sets ui.theme). Overrides take precedence over persisted settings."
        ),
    )
    parser.add_argument(
        "usd_file",
        nargs="?",
        default=None,
        help="Optional path to a USD file (.usd/.usda/.usdc/.usdz) to open on startup.",
    )
    if argv is None:
        argv = sys.argv[1:]
    try:
        overrides, remaining = extract_setting_overrides(list(argv))
    except ValueError as exc:
        parser.error(str(exc))
    args = parser.parse_args(remaining)
    args.settings_overrides = overrides
    return args


def main(argv: Optional[List[str]] = None) -> None:
    """Launch OvGear. Used by both `python -m ovui_widgets.app` and the `ovui-widgets` console script."""
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    from ovui_widgets.app.native_runtime_bootstrap import (
        install_preconstructed_renderer,
        preconstruct_selected_native_renderer,
    )

    bootstrap = preconstruct_selected_native_renderer()
    from ovui_widgets.app.application import Application

    app = Application(settings_overrides=args.settings_overrides)
    install_preconstructed_renderer(app, bootstrap)
    app.run(usd_path=args.usd_file)


def main_sync() -> None:
    """Console script entry point declared in pyproject.toml. Delegates to main()."""
    main()


if __name__ == "__main__":
    main()
