# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for viewport toolbar contributions."""

from __future__ import annotations

from ovui_widgets.viewport.toolbar_hooks import (
    ViewportStatusBadge,
    ViewportToolbarAction,
    ViewportToolbarMenu,
    ViewportToolbarRegistry,
)


class _Button:
    def __init__(self):
        self.tooltip = ""
        self.clicked_fn = None

    def set_clicked_fn(self, clicked_fn):
        self.clicked_fn = clicked_fn


class _Label:
    def __init__(self):
        self.tooltip = ""


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False


class _FakeUi:
    def __init__(self, *, fail_labels=()):
        self.events = []
        self._fail_labels = set(fail_labels)

    def Button(self, label, **kwargs):
        if label in self._fail_labels:
            raise RuntimeError(f"failed to build {label}")
        self.events.append(("Button", label, kwargs))
        return _Button()

    def Label(self, text, **kwargs):
        self.events.append(("Label", text, kwargs))
        return _Label()

    def RasterImageProvider(self, path):
        self.events.append(("RasterImageProvider", path, {}))
        return f"provider:{path}"

    def ZStack(self, **kwargs):
        self.events.append(("ZStack", "", kwargs))
        return _Context()

    def VStack(self, **kwargs):
        self.events.append(("VStack", "", kwargs))
        return _Context()

    def HStack(self, **kwargs):
        self.events.append(("HStack", "", kwargs))
        return _Context()

    def Rectangle(self, **kwargs):
        self.events.append(("Rectangle", "", kwargs))

    def ImageWithProvider(self, provider, **kwargs):
        self.events.append(("ImageWithProvider", provider, kwargs))

    def InvisibleButton(self, **kwargs):
        self.events.append(("InvisibleButton", "", kwargs))
        return _Button()

    def Spacer(self, **kwargs):
        self.events.append(("Spacer", "", kwargs))


def test_toolbar_hook_add_remove_capability_gating_and_lifecycle():
    owner = object()
    lifecycle = []
    triggered = []
    registry = ViewportToolbarRegistry(owner)
    contribution = ViewportToolbarAction(
        id="render.capture",
        label="C",
        order=10,
        capabilities=("capture",),
        callback=lambda received_owner: triggered.append(received_owner),
        on_add=lambda received_owner: lifecycle.append(("add", received_owner)),
        on_remove=lambda received_owner: lifecycle.append(("remove", received_owner)),
    )

    handle = registry.add(contribution)
    second_handle = registry.add(contribution)

    assert handle.id == second_handle.id == "render.capture"
    assert lifecycle == [("add", owner)]

    ui = _FakeUi()
    registry.build_toolbar(ui, button_size=20)
    assert [event for event in ui.events if event[0] == "Button"] == []

    registry.set_capability("capture", True)
    ui = _FakeUi()
    registry.build_toolbar(ui, button_size=20)
    buttons = [event for event in ui.events if event[0] == "Button"]
    assert [event[1] for event in buttons] == ["C"]
    assert buttons[0][2]["identifier"] == "viewport_toolbar_action_render_capture"

    buttons[0][2]["clicked_fn"]()
    assert triggered == [owner]

    assert handle.remove() is True
    assert lifecycle == [("add", owner), ("remove", owner)]

    ui = _FakeUi()
    registry.build_toolbar(ui, button_size=20)
    assert [event for event in ui.events if event[0] == "Button"] == []


def test_toolbar_hook_menu_and_status_badge_render_named_widgets():
    owner = object()
    registry = ViewportToolbarRegistry(owner, capabilities=("ready",))
    registry.add(
        ViewportToolbarMenu(
            id="display.menu",
            label="D",
            capabilities=("ready",),
        )
    )
    registry.add(
        ViewportStatusBadge(
            id="status.ready",
            label="READY",
            capabilities=("ready",),
            text_fn=lambda received_owner: "ON",
        )
    )

    ui = _FakeUi()
    registry.build_toolbar(ui, button_size=20)

    buttons = [event for event in ui.events if event[0] == "Button"]
    labels = [event for event in ui.events if event[0] == "Label"]
    assert buttons[0][2]["identifier"] == "viewport_toolbar_menu_display_menu"
    assert labels[0][1] == "ON"
    assert labels[0][2]["name"] == "viewport_status_badge_status_ready"
    assert labels[0][2]["style_type_name_override"] == "Viewport.HUD.Value"


def test_toolbar_hook_icon_menu_renders_icon_only_toolbar_button():
    owner = object()
    registry = ViewportToolbarRegistry(owner)
    registry.add(
        ViewportToolbarMenu(
            id="display.render_target",
            label="Render Target",
            tooltip="Choose render target",
            icon_path="/tmp/render_target.png",
        )
    )

    ui = _FakeUi()
    registry.build_toolbar(ui, button_size=20)

    assert [event for event in ui.events if event[0] == "Button"] == []
    images = [event for event in ui.events if event[0] == "ImageWithProvider"]
    buttons = [event for event in ui.events if event[0] == "InvisibleButton"]
    assert len(images) == 1
    assert len(buttons) == 1
    assert images[0][1] == "provider:/tmp/render_target.png"
    assert images[0][2]["width"] == 13
    assert images[0][2]["height"] == 13
    assert images[0][2]["enabled"] is False
    assert images[0][2]["opaque_for_mouse_events"] is False
    assert images[0][2]["style_type_name_override"] == "Viewport.Toolbar.Icon"
    assert buttons[0][2]["width"] == 20
    assert buttons[0][2]["height"] == 20
    assert buttons[0][2]["identifier"] == "viewport_toolbar_menu_display_render_target"
    assert buttons[0][2]["tooltip"] == "Choose render target"


def test_toolbar_hook_failure_isolation_keeps_later_contributions_building():
    owner = object()
    registry = ViewportToolbarRegistry(owner)
    registry.add(ViewportToolbarAction(id="bad", label="BAD", order=0))
    registry.add(ViewportToolbarAction(id="good", label="GOOD", order=1))

    ui = _FakeUi(fail_labels=("BAD",))
    registry.build_toolbar(ui, button_size=20)

    assert "bad" in registry.failures
    assert [event[1] for event in ui.events if event[0] == "Button"] == ["GOOD"]
