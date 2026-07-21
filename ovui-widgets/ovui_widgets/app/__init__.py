# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OvGear: Kit-free 3D application built on standalone omni.ui.

Top-level imports are lazy so that ``import ovui_widgets.app`` does not pull in
``omni.ui`` (or anything that imports it). This is required by the
headless entrypoint (``python -m ovui_widgets.app.headless``), which must set
``OMNIUI_HEADLESS=1`` and ``OMNIUI_BACKEND=vulkan`` *before* the ovui
platform is initialised. Eagerly importing :class:`Application` here
would defeat that ordering, because Python imports the package
``ovui_widgets.app`` (and runs this file) before executing ``headless.py``.
"""

from ovui_widgets.common.version import package_version as _package_version

__version__ = _package_version("ovui-widgets-app")

__all__ = [
    "AppWindowContribution",
    "AppWindowHandle",
    "AppWindowRegistry",
    "Application",
    "ContentBrowserWindow",
    "ErrorReporter",
    "StatusBar",
]


def __getattr__(name):
    if name == "Application":
        from ovui_widgets.app.application import Application
        return Application
    if name in {"AppWindowContribution", "AppWindowHandle", "AppWindowRegistry"}:
        from ovui_widgets.app import window_hooks
        return getattr(window_hooks, name)
    if name == "ContentBrowserWindow":
        from ovui_widgets.content import ContentBrowserWindow
        return ContentBrowserWindow
    if name == "ErrorReporter":
        from ovui_widgets.common.error_reporter import ErrorReporter
        return ErrorReporter
    if name == "StatusBar":
        from ovui_widgets.app.status_bar import StatusBar
        return StatusBar
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
