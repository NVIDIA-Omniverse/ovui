# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Step 19 tests for guarded Physics menu registration."""

from __future__ import annotations

from types import SimpleNamespace


class _PhysicsControls:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.enabled = False
        self.playing = False

    def toggle_enabled(self) -> None:
        self.calls.append("toggle_enabled")
        self.enabled = not self.enabled
        if not self.enabled:
            self.playing = False

    def toggle_playing(self) -> None:
        self.calls.append("toggle_playing")
        self.playing = not self.playing

    def enable_label(self) -> str:
        return "Disable PhysX" if self.enabled else "Enable PhysX"

    def play_label(self) -> str:
        return "Stop Simulation" if self.playing else "Play Simulation"

    def can_toggle_enabled(self) -> bool:
        return True

    def can_toggle_playing(self) -> bool:
        return self.enabled


class _App:
    def __init__(self) -> None:
        self.physics_controls = _PhysicsControls()
        self.session = SimpleNamespace(physics_controls=self.physics_controls)

    def get_adapter_session(self) -> object:
        return self.session


def test_physics_component_registers_direct_physics_menu_items(monkeypatch) -> None:
    from ovui_widgets.app import menu_bar
    import ovui_widgets_physx_controls

    app = _App()
    captured = []

    def _capture(contribution):
        captured.append(contribution)
        return SimpleNamespace(cancel=lambda: None)

    monkeypatch.setattr(menu_bar, "register_menu_item", _capture)

    ovui_widgets_physx_controls.register(app)

    assert [
        (
            contribution.menu_path,
            contribution.stable_id,
            contribution.label(),
            contribution.order,
            contribution.enabled() if callable(contribution.enabled) else contribution.enabled,
        )
        for contribution in captured
    ] == [
        (
            ("Physics",),
            "physics.enable",
            "Enable PhysX",
            10,
            True,
        ),
        (
            ("Physics",),
            "physics.play_stop",
            "Play Simulation",
            20,
            False,
        ),
    ]

    captured[1].action()
    assert app.physics_controls.calls == []

    captured[0].action()
    assert captured[0].label() == "Disable PhysX"
    assert captured[1].enabled() is True

    captured[1].action()
    assert captured[1].label() == "Stop Simulation"

    assert app.physics_controls.calls == ["toggle_enabled", "toggle_playing"]

    captured[1].action()
    assert captured[1].label() == "Play Simulation"

    captured[0].action()
    assert captured[0].label() == "Enable PhysX"
    assert captured[1].enabled() is False


def test_menu_registry_replaces_by_stable_id_and_orders_by_path() -> None:
    from ovui_widgets.app.menu_bar import (
        MenuContribution,
        get_menu_contributions,
        register_menu_item,
    )

    first = register_menu_item(
        MenuContribution(
            menu_path=("Physics", "Simulation"),
            stable_id="physics.test.one",
            label="Later",
            order=20,
        )
    )
    second = register_menu_item(
        MenuContribution(
            menu_path=("Physics", "Simulation"),
            stable_id="physics.test.two",
            label="Earlier",
            order=10,
        )
    )
    replacement = register_menu_item(
        MenuContribution(
            menu_path=("Physics", "Simulation"),
            stable_id="physics.test.one",
            label="Replacement",
            order=30,
        )
    )
    try:
        labels = [
            contribution.label
            for contribution in get_menu_contributions(("Physics", "Simulation"))
            if contribution.stable_id.startswith("physics.test.")
        ]
        assert labels == ["Earlier", "Replacement"]
    finally:
        first.cancel()
        second.cancel()
        replacement.cancel()
