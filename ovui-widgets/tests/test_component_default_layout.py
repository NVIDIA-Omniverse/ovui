# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Optional components take part in Window > Reset Layout."""

from types import SimpleNamespace

from ovui_widgets.app.components import ComponentManager


class _EntryPoint:
    def __init__(self, name, register):
        self.name = name
        self._register = register

    def load(self):
        return self._register


def test_default_layout_reaches_every_loaded_component_and_isolates_failures(monkeypatch):
    calls = []

    def failing():
        calls.append("failing")
        raise RuntimeError("layout failed")

    handles = {
        "a_failing": SimpleNamespace(apply_default_layout=failing),
        "b_docking": SimpleNamespace(apply_default_layout=lambda: calls.append("docking")),
        "c_no_layout": SimpleNamespace(),
    }
    manager = ComponentManager(SimpleNamespace())
    monkeypatch.setattr(
        manager,
        "discover",
        lambda: tuple(_EntryPoint(name, lambda app, h=handle: h) for name, handle in handles.items()),
    )
    manager.load_all()

    manager.apply_default_layout()

    assert calls == ["failing", "docking"]
    assert "a_failing:apply_default_layout" in manager.failures


def test_component_window_state_survives_the_unload_that_shutdown_does_first(monkeypatch):
    """Shutdown unloads components before it saves the layout."""

    window = SimpleNamespace(
        visible=True,
        window=SimpleNamespace(position_x=980.0, position_y=21.0, width=300.0, height=675.0),
    )
    handle = SimpleNamespace(
        layout_windows=lambda: {"Tool Window": window},
        unload=lambda: None,
    )
    manager = ComponentManager(SimpleNamespace())
    monkeypatch.setattr(
        manager, "discover", lambda: (_EntryPoint("tool", lambda app: handle),)
    )
    manager.load_all()

    manager.unload_all()

    assert manager.layout_state() == {
        "Tool Window": {
            "visible": True,
            "position_x": 980.0,
            "position_y": 21.0,
            "width": 300.0,
            "height": 675.0,
        }
    }


def test_saved_window_state_goes_back_to_the_component_that_owns_the_title(monkeypatch):
    restored = []

    def restore(title, data):
        if title != "Tool Window":
            return False
        restored.append((title, data))
        return True

    handle = SimpleNamespace(restore_layout_window=restore)
    manager = ComponentManager(SimpleNamespace())
    monkeypatch.setattr(
        manager, "discover", lambda: (_EntryPoint("tool", lambda app: handle),)
    )
    manager.load_all()

    assert manager.restore_layout_window("Tool Window", {"visible": True}) is True
    assert manager.restore_layout_window("Other Window", {"visible": True}) is False
    assert restored == [("Tool Window", {"visible": True})]
