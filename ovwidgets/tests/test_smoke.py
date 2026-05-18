# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Smoke tests: verify that all OvGear packages and public symbols import cleanly.

These tests require no ovui runtime — they only check that the package
structure and __init__ exports are wired up correctly.
"""


def test_import_ovwidgets_app():
    import ovwidgets.app  # noqa: F401


def test_import_ovwidgets_content():
    import ovwidgets.content  # noqa: F401


def test_import_ovwidgets_stage():
    import ovwidgets.stage  # noqa: F401


def test_import_ovwidgets_property():
    import ovwidgets.property  # noqa: F401


def test_import_ovwidgets_viewport():
    import ovwidgets.viewport  # noqa: F401


def test_application_importable():
    from ovwidgets.app import Application
    assert Application is not None


def test_selection_bus_importable():
    from ovwidgets.common.selection import SelectionBus
    assert SelectionBus is not None


def test_undo_manager_importable():
    from ovwidgets.common.undo import UndoManager
    assert UndoManager is not None


def test_settings_importable():
    from ovwidgets.common.settings import Settings
    assert Settings is not None


def test_error_reporter_importable():
    from ovwidgets.common.error_reporter import ErrorReporter
    assert ErrorReporter is not None


def test_adapters_importable():
    from ovui_data_adapters.common import RendererAdapter, StageAdapter
    assert StageAdapter is not None
    assert RendererAdapter is not None


def test_stage_widget_importable():
    from ovwidgets.stage import StageWidget
    assert StageWidget is not None


def test_property_widget_importable():
    from ovwidgets.property import PropertyWidget
    assert PropertyWidget is not None


def test_viewport_widget_importable():
    from ovwidgets.viewport import ViewportWidget
    assert ViewportWidget is not None


def test_style_subpackage_importable():
    import ovwidgets.app
    import ovwidgets.app.style  # noqa: F401
    from ovwidgets.app.style import constants, palette, styles, urls  # noqa: F401


def test_content_browser_window_importable():
    from ovwidgets.content import ContentBrowserWindow
    assert ContentBrowserWindow is not None


def test_content_browser_window_in_all():
    """``ContentBrowserWindow`` is part of the ovwidgets.content package public API."""
    import ovwidgets.content
    assert "ContentBrowserWindow" in ovwidgets.content.__all__
