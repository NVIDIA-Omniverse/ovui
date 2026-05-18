# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Headless entrypoint for OvGear — `python -m ovwidgets.app.headless`.

This module sets ``OMNIUI_HEADLESS=1`` and ``OMNIUI_BACKEND=vulkan`` in the
process environment **before** :mod:`ovwidgets.app.application` is imported. ovui
reads these env vars at module-load time (e.g. ``settings_dialog`` imports
``omni.ui`` which initialises the platform); flipping them inside the
``Application`` constructor would be too late and the GLFW platform would
already be active.

The file is named ``headless.py`` (not ``__headless__.py``) so that
``python -m ovwidgets.app.headless`` resolves to it — a dunder-named module is not
a valid ``-m`` target.

Resolution is read from ``OVGEAR_HEADLESS_WIDTH`` /
``OVGEAR_HEADLESS_HEIGHT`` (or ``--width`` / ``--height`` CLI flags, which
take precedence by writing into the same env vars). The windowed default
(``ovwidgets.app.__main__``) is unaffected.
"""

import argparse
import os
import sys
from typing import List, Optional


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OvGear — headless (offscreen Vulkan) launch.",
    )
    parser.add_argument("--width", type=int, default=None,
                        help="Frame width in pixels (overrides OVGEAR_HEADLESS_WIDTH).")
    parser.add_argument("--height", type=int, default=None,
                        help="Frame height in pixels (overrides OVGEAR_HEADLESS_HEIGHT).")
    parser.add_argument("usd_file", nargs="?", default=None,
                        help="Optional USD file to open on startup.")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    os.environ["OMNIUI_HEADLESS"] = "1"
    os.environ["OMNIUI_BACKEND"] = "vulkan"

    width = args.width if args.width is not None else int(
        os.environ.get("OVGEAR_HEADLESS_WIDTH", 1920))
    height = args.height if args.height is not None else int(
        os.environ.get("OVGEAR_HEADLESS_HEIGHT", 1080))
    os.environ["OVGEAR_HEADLESS_WIDTH"] = str(width)
    os.environ["OVGEAR_HEADLESS_HEIGHT"] = str(height)

    from ovwidgets.app.application import Application
    app = Application()
    app.run(usd_path=args.usd_file)


if __name__ == "__main__":
    main()
