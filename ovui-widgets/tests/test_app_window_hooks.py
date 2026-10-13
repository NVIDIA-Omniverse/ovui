# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for generic lazy app window contributions."""

from __future__ import annotations

from ovui_widgets.app.menu_hooks import AppMenuRegistry
from ovui_widgets.app.window_hooks import AppWindowContribution, AppWindowRegistry


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
        self.events.append(("MenuItem", label, kwargs))

    def Separator(self):
        self.events.append(("Separator", "", {}))


class _FakeWindow:
    def __init__(self):
        self.visible = False
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


def _menu_items(menu_registry, path=("Window",)):
    ui = _FakeUi()
    menu_registry.build_path(path, ui)
    return [event for event in ui.events if event[0] == "MenuItem"]


def test_lazy_window_registers_menu_toggles_and_unloads_cleanly():
    lifecycle = []
    created = []
    app = object()
    menus = AppMenuRegistry(app)
    registry = AppWindowRegistry(app, menu_registry=menus)

    def factory(received_app):
        created.append(received_app)
        return _FakeWindow()

    contribution = AppWindowContribution(
        id="tools.panel",
        title="Tools Panel",
        factory=factory,
        menu_label="Tools Panel",
        menu_parent_path=("Window",),
        on_add=lambda received_app: lifecycle.append(("add", received_app)),
        on_remove=lambda received_app: lifecycle.append(("remove", received_app)),
    )

    handle = registry.add(contribution)
    second_handle = registry.add(contribution)

    assert handle.id == second_handle.id == "tools.panel"
    assert lifecycle == [("add", app)]
    assert created == []

    items = _menu_items(menus)
    assert [item[1] for item in items] == ["Tools Panel"]

    items[0][2]["triggered_fn"]()
    window = registry.get("tools.panel")
    assert created == [app]
    assert window.visible is True

    registry.toggle("tools.panel")
    assert window.visible is False

    registry.open("tools.panel")
    assert created == [app]
    assert window.visible is True

    assert handle.remove() is True
    assert lifecycle == [("add", app), ("remove", app)]
    assert window.destroyed is True
    assert registry.get("tools.panel") is None
    assert _menu_items(menus) == []
    assert handle.remove() is False


def test_lazy_window_gates_capabilities_and_isolates_failures():
    app = object()
    menus = AppMenuRegistry(app)
    registry = AppWindowRegistry(app, menu_registry=menus)
    hidden = AppWindowContribution(
        id="hidden",
        title="Hidden",
        factory=lambda received_app: _FakeWindow(),
        menu_label="Hidden",
        capabilities=("advanced",),
    )
    broken = AppWindowContribution(
        id="broken",
        title="Broken",
        factory=lambda received_app: (_ for _ in ()).throw(RuntimeError("boom")),
        menu_label="Broken",
    )
    good = AppWindowContribution(
        id="good",
        title="Good",
        factory=lambda received_app: _FakeWindow(),
        menu_label="Good",
    )

    registry.add(hidden)
    registry.add(broken)
    registry.add(good)

    assert [item[1] for item in _menu_items(menus)] == ["Broken", "Good"]
    assert registry.open("hidden") is None

    registry.set_capability("advanced", True)
    assert [item[1] for item in _menu_items(menus)] == ["Broken", "Good", "Hidden"]

    assert registry.open("broken") is None
    assert "broken" in registry.failures

    good_window = registry.open("good")
    assert good_window is not None
    assert good_window.visible is True


def test_window_registration_ownership_is_generation_bound():
    """same-ID foreign contributions are rejected,
    and a stale handle no-ops on an independent replacement instead of
    removing it."""
    import pytest

    app = object()
    registry = AppWindowRegistry(app)

    original = AppWindowContribution(
        id="tools.panel", title="Original", factory=lambda a: object()
    )
    handle = registry.add(original)

    # A different contribution under an existing ID is never silently
    # granted ownership.
    foreign = AppWindowContribution(
        id="tools.panel", title="Foreign", factory=lambda a: object()
    )
    with pytest.raises(ValueError, match="already registered"):
        registry.add(foreign)

    # Original removed and independently replaced: the stale handle
    # no-ops and the replacement survives.
    assert registry.remove("tools.panel") is True
    replacement_handle = registry.add(foreign)
    assert handle.remove() is False
    assert registry._records["tools.panel"].contribution is foreign

    # Identity-conditional removal removes only the exact owner.
    assert registry.remove_if_matches("tools.panel", original) is False
    assert registry.remove_if_matches("tools.panel", foreign) is True
    assert registry._records == {}
    assert replacement_handle.remove() is False


def test_window_handle_is_generation_bound_across_same_object_readd():
    """removing and re-adding the very same contribution
    starts a new generation; the stale handle no-ops on it."""
    registry = AppWindowRegistry(object())
    contribution = AppWindowContribution(
        id="tools.gen", title="Gen", factory=lambda a: object()
    )
    stale = registry.add(contribution)
    assert registry.remove("tools.gen") is True
    fresh = registry.add(contribution)

    assert stale.remove() is False
    assert registry._records["tools.gen"].contribution is contribution
    assert fresh.remove() is True
    assert registry._records == {}
