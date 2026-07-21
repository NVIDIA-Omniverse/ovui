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


def test_import_ovui_widgets_app():
    import ovui_widgets.app  # noqa: F401


def test_import_ovui_widgets_content():
    import ovui_widgets.content  # noqa: F401


def test_import_ovui_widgets_stage():
    import ovui_widgets.stage  # noqa: F401


def test_import_ovui_widgets_property():
    import ovui_widgets.property  # noqa: F401


def test_import_ovui_widgets_viewport():
    import ovui_widgets.viewport  # noqa: F401


def test_application_importable():
    from ovui_widgets.app import Application
    assert Application is not None


def test_selection_bus_importable():
    from ovui_widgets.common.selection import SelectionBus
    assert SelectionBus is not None


def test_undo_manager_importable():
    from ovui_widgets.common.undo import UndoManager
    assert UndoManager is not None


def test_settings_importable():
    from ovui_widgets.common.settings import Settings
    assert Settings is not None


def test_error_reporter_importable():
    from ovui_widgets.common.error_reporter import ErrorReporter
    assert ErrorReporter is not None


def test_adapters_importable():
    from ovui_data_adapters.common import RendererAdapter, StageAdapter
    assert StageAdapter is not None
    assert RendererAdapter is not None


def test_stage_widget_importable():
    from ovui_widgets.stage import StageWidget
    assert StageWidget is not None


def test_property_widget_importable():
    from ovui_widgets.property import PropertyWidget
    assert PropertyWidget is not None


def test_viewport_widget_importable():
    from ovui_widgets.viewport import ViewportWidget
    assert ViewportWidget is not None


def test_style_subpackage_importable():
    import ovui_widgets.app
    import ovui_widgets.app.style  # noqa: F401
    from ovui_widgets.app.style import constants, palette, styles, urls  # noqa: F401


def test_content_browser_window_importable():
    from ovui_widgets.content import ContentBrowserWindow
    assert ContentBrowserWindow is not None


def test_content_browser_window_in_all():
    """``ContentBrowserWindow`` is part of the ovui_widgets.content package public API."""
    import ovui_widgets.content
    assert "ContentBrowserWindow" in ovui_widgets.content.__all__
