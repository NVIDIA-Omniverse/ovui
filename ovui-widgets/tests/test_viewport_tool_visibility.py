# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""An agent's selection mode never permanently hides the user's transform gizmo."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ovui_widgets.viewport.inspector import ViewportInspector
from ovui_widgets.viewport.manipulator_registry import ToolRegistry
from ovui_widgets.viewport.viewport_widget import ViewportSurface


def surface():
    view = ViewportSurface.__new__(ViewportSurface)
    view._transform_manipulator = SimpleNamespace(visible=True, tool="translate")
    view._transform_manipulator_visible = True
    view._tool_registry = ToolRegistry(manipulator=view._transform_manipulator)
    view._refresh_toolbar_state = Mock()
    return view


def test_toolbar_choice_restores_the_gizmo_hidden_by_inspector_select():
    view = surface()
    api = ViewportInspector(lambda: {"primary": view}, lambda: None)
    api.tool("select")
    assert view._transform_manipulator.visible is False
    # The user clicks the already active Move button in the desktop toolbar.
    view._on_toolbar_tool_clicked("translate")
    assert view._transform_manipulator.visible is True
    api.tool("select")
    view._on_toolbar_tool_clicked("rotate")
    assert view._transform_manipulator.visible is True
    assert view._tool_registry.active_tool == "rotate"


def test_desktop_hotkey_restores_the_gizmo_hidden_by_inspector_select():
    from ovui_widgets.app.application import Application

    view = surface()
    view._flight_keyboard = SimpleNamespace(rmb_held=False)
    ViewportInspector(lambda: {"primary": view}, lambda: None).tool("select")
    app = SimpleNamespace(_viewport_window=view)
    Application._dispatch_tool_hotkey(app, ord("w"), 0)
    assert view._transform_manipulator.visible is True


def test_rejected_tool_leaves_visibility_unchanged():
    view = SimpleNamespace(
        set_active_tool=Mock(return_value=False), set_transform_manipulator_visible=Mock()
    )
    api = ViewportInspector(lambda: {"primary": view}, lambda: None)
    with pytest.raises(ValueError, match="Cannot activate"):
        api.tool("rotate")
    view.set_transform_manipulator_visible.assert_not_called()


@pytest.mark.parametrize(
    "visible, active_tool, reported",
    [(False, "translate", "select"), (True, "translate", "move"), (True, "rotate", "rotate"),
     (True, "scale", "scale")],
)
def test_viewport_list_reports_the_inspector_tool_including_select(visible, active_tool, reported):
    from dataclasses import dataclass

    @dataclass
    class Snapshot:
        active_tool: str
        transform_manipulator_visible: bool

    view = SimpleNamespace(
        get_viewport_state_snapshot=lambda: Snapshot(active_tool, visible)
    )
    listed = ViewportInspector(lambda: {"primary": view}, lambda: None).list()["views"][0]
    assert listed["tool"] == reported
    assert listed["transform_manipulator_visible"] is visible

