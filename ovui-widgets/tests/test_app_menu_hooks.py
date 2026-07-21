# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for optional app menu contributions."""

from __future__ import annotations

import inspect

from ovui_widgets.app import menu_hooks
from ovui_widgets.app.menu_hooks import (
    AppMenuContribution,
    AppMenuContributionProvider,
    AppMenuRegistry,
)


class _FakeMenuItem:
    def __init__(self):
        self.tooltip = ""
        self.screen_position_x = 120
        self.screen_position_y = 48
        self.computed_width = 180
        self.computed_height = 22
        self.visible = True


class _MenuContext:
    def __init__(self, ui, label):
        self._ui = ui
        self._label = label

    def __enter__(self):
        self._ui.events.append(("Menu:enter", self._label, {}))
        return self

    def __exit__(self, exc_type, exc, tb):
        self._ui.events.append(("Menu:exit", self._label, {}))
        return False


class _FakeUi:
    def __init__(self):
        self.events = []

    def Menu(self, label, **kwargs):
        self.events.append(("Menu", label, kwargs))
        return _MenuContext(self, label)

    def MenuItem(self, label, **kwargs):
        item = _FakeMenuItem()
        self.events.append(("MenuItem", label, kwargs, item))
        return item

    def Separator(self):
        self.events.append(("Separator", "", {}))


def test_menu_hook_add_remove_capability_gating_and_lifecycle():
    lifecycle = []
    triggered = []
    app = object()
    registry = AppMenuRegistry(app)
    contribution = AppMenuContribution(
        id="tools.export",
        label="Export",
        parent_path=("Tools",),
        capabilities=("export",),
        callback=lambda received_app: triggered.append(received_app),
        on_add=lambda received_app: lifecycle.append(("add", received_app)),
        on_remove=lambda received_app: lifecycle.append(("remove", received_app)),
    )

    handle = registry.add(contribution)
    second_handle = registry.add(contribution)

    assert handle.id == second_handle.id == "tools.export"
    assert lifecycle == [("add", app)]

    ui = _FakeUi()
    registry.build_path(("Tools",), ui)
    assert [event[1] for event in ui.events if event[0] == "MenuItem"] == []

    registry.set_capability("export", True)
    ui = _FakeUi()
    registry.build_path(("Tools",), ui)
    items = [event for event in ui.events if event[0] == "MenuItem"]
    assert [event[1] for event in items] == ["Export"]

    items[0][2]["triggered_fn"]()
    assert triggered == [app]

    assert handle.remove() is True
    assert lifecycle == [("add", app), ("remove", app)]

    ui = _FakeUi()
    registry.build_path(("Tools",), ui)
    assert [event[1] for event in ui.events if event[0] == "MenuItem"] == []


def test_menu_hook_supports_nested_paths_and_top_level_roots():
    app = object()
    registry = AppMenuRegistry(app)
    registry.add(
        AppMenuContribution(
            id="custom.child",
            label="Child",
            parent_path="Custom/Sub",
        )
    )

    roots = registry.iter_top_level_menus(exclude=("File", "Edit"))
    assert [(root.label, root.path) for root in roots] == [("Custom", ("Custom",))]

    ui = _FakeUi()
    registry.build_path(("Custom",), ui)
    assert ("Menu", "Sub", {}) in ui.events
    items = _menu_items(ui)
    assert len(items) == 1
    assert items[0][1] == "Child"
    assert items[0][2] == {
        "enabled": True,
        "name": "app_menu_custom_child",
        "triggered_fn": None,
    }


def _menu_items(ui):
    return [event for event in ui.events if event[0] == "MenuItem"]


def test_dynamic_menu_provider_builds_ordered_parented_disabled_items():
    triggered = []
    app = object()
    registry = AppMenuRegistry(app)

    registry.add_provider(
        AppMenuContributionProvider(
            id="tools.dynamic",
            contributions_fn=lambda received_app: (
                AppMenuContribution(
                    id="dynamic.third",
                    label="Third",
                    parent_path=("Tools", "Dynamic"),
                    order=30,
                    callback=lambda callback_app: triggered.append(("third", callback_app)),
                ),
                AppMenuContribution(
                    id="dynamic.first",
                    label="First",
                    parent_path=("Tools", "Dynamic"),
                    order=10,
                ),
                AppMenuContribution(
                    id="dynamic.disabled",
                    label="Disabled",
                    parent_path=("Tools", "Dynamic"),
                    order=20,
                    enabled=False,
                    disabled_reason="Disabled by context.",
                ),
            ),
        )
    )

    root_ui = _FakeUi()
    registry.build_path(("Tools",), root_ui)
    assert [event[1] for event in root_ui.events if event[0] == "Menu"] == ["Dynamic"]

    ui = _FakeUi()
    registry.build_path(("Tools", "Dynamic"), ui)

    items = _menu_items(ui)
    assert [event[1] for event in items] == ["First", "Disabled", "Third"]
    assert [event[2]["name"] for event in items] == [
        "app_menu_dynamic_first",
        "app_menu_dynamic_disabled",
        "app_menu_dynamic_third",
    ]
    assert items[1][2]["enabled"] is False
    assert items[1][3].tooltip == "Disabled by context."
    items[2][2]["triggered_fn"]()
    assert triggered == [("third", app)]


def test_built_menu_item_geometry_is_stable_read_only_state():
    registry = AppMenuRegistry(object())
    registry.add(
        AppMenuContribution(
            id="physics.play_stop",
            label="Play Simulation",
            parent_path=("Physics",),
            enabled=False,
        )
    )

    registry.build_path(("Physics",), _FakeUi())

    assert registry.built_item_geometry() == (
        {
            "id": "physics.play_stop",
            "label": "Play Simulation",
            "parent_path": ("Physics",),
            "kind": "item",
            "enabled": False,
            "visible": True,
            "rect": {
                "x": 120.0,
                "y": 48.0,
                "width": 180.0,
                "height": 22.0,
            },
            "point": [210, 59],
        },
    )

    assert registry.remove("physics.play_stop") is True
    assert registry.built_item_geometry() == ()


def test_dynamic_provider_idempotent_remove_and_lifecycle_cleanup():
    lifecycle = []
    app = object()
    registry = AppMenuRegistry(app)
    provider = AppMenuContributionProvider(
        id="lifecycle.provider",
        contributions_fn=lambda _app: (
            AppMenuContribution(
                id="lifecycle.item",
                label="Lifecycle",
                parent_path=("Tools",),
            ),
        ),
        on_add=lambda received_app: lifecycle.append(("add", received_app)),
        on_remove=lambda received_app: lifecycle.append(("remove", received_app)),
    )

    handle = registry.add_provider(provider)
    duplicate = registry.add_provider(provider)

    assert handle.id == duplicate.id == "lifecycle.provider"
    assert lifecycle == [("add", app)]
    assert registry.remove("lifecycle.provider") is True
    assert lifecycle == [("add", app), ("remove", app)]
    assert registry.remove("lifecycle.provider") is False

    ui = _FakeUi()
    registry.build_path(("Tools",), ui)
    assert _menu_items(ui) == []


def test_dynamic_provider_failure_isolation_keeps_other_entries():
    app = object()
    registry = AppMenuRegistry(app)
    registry.add_provider(
        AppMenuContributionProvider(
            id="bad.provider",
            contributions_fn=lambda _app: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    )
    registry.add_provider(
        AppMenuContributionProvider(
            id="good.provider",
            contributions_fn=lambda _app: (
                AppMenuContribution(
                    id="good.item",
                    label="Good",
                    parent_path=("Tools",),
                ),
            ),
        )
    )

    ui = _FakeUi()
    registry.build_path(("Tools",), ui)

    assert [event[1] for event in _menu_items(ui)] == ["Good"]
    assert "bad.provider" in registry.failures


def test_dynamic_item_failure_isolation_for_visible_enabled_and_trigger():
    app = object()
    registry = AppMenuRegistry(app)
    triggered = []
    registry.add_provider(
        AppMenuContributionProvider(
            id="mixed.provider",
            contributions_fn=lambda _app: (
                AppMenuContribution(
                    id="bad.visible",
                    label="Hidden",
                    parent_path=("Tools",),
                    visible_fn=lambda _received: (_ for _ in ()).throw(RuntimeError("visible")),
                ),
                AppMenuContribution(
                    id="bad.enabled",
                    label="Disabled",
                    parent_path=("Tools",),
                    enabled_fn=lambda _received: (_ for _ in ()).throw(RuntimeError("enabled")),
                ),
                AppMenuContribution(
                    id="bad.trigger",
                    label="Trigger",
                    parent_path=("Tools",),
                    callback=lambda _received: (_ for _ in ()).throw(RuntimeError("trigger")),
                ),
                AppMenuContribution(
                    id="good.trigger",
                    label="Good",
                    parent_path=("Tools",),
                    callback=lambda _received: triggered.append("good"),
                ),
            ),
        )
    )

    ui = _FakeUi()
    registry.build_path(("Tools",), ui)
    items = _menu_items(ui)
    assert [event[1] for event in items] == ["Disabled", "Trigger", "Good"]
    assert items[0][2]["enabled"] is False
    assert "bad.visible" in registry.failures
    assert "bad.enabled" in registry.failures

    items[1][2]["triggered_fn"]()
    items[2][2]["triggered_fn"]()
    assert "bad.trigger" in registry.failures
    assert triggered == ["good"]


def test_menu_hooks_stay_generic_and_backend_free():
    source = inspect.getsource(menu_hooks)

    assert "pxr" not in source
    assert "ovrtx" not in source
    assert "ovui_data_adapters" not in source
    assert "CreateAction" not in source
    assert "prim_kind" not in source
    assert "Usd" not in source
