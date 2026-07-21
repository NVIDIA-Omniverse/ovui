# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Optional Physics menu contribution for ovstage-backed UI sessions."""

from __future__ import annotations

from typing import Any


ENTRY_POINT_NAME = "ovstage_physics_controls"
ENTRY_POINT_VALUE = "ovui_widgets_physx_controls:register"
MENU_REGISTRATION_VALUE = "register_menu_item"


def register(app: Any) -> None:
    """Register Physics menu rows when the ovui_widgets menu subsystem exists."""
    try:
        from ovui_widgets.app.menu_bar import MenuContribution, register_menu_item
    except ImportError:
        return

    try:
        register_menu_item(
            MenuContribution(
                menu_path=("Physics",),
                stable_id="physics.enable",
                label=lambda: _control_label(app, "enable_label", "Enable PhysX"),
                order=10,
                enabled=lambda: _has_physics_controls(app),
                visible=lambda: _has_physics_controls(app),
                action=lambda: _invoke_physics_control(app, "toggle_enabled"),
            )
        )
        register_menu_item(
            MenuContribution(
                menu_path=("Physics",),
                stable_id="physics.play_stop",
                label=lambda: _control_label(app, "play_label", "Play Simulation"),
                order=20,
                enabled=lambda: _control_enabled(app, "can_toggle_playing"),
                visible=lambda: _has_physics_controls(app),
                action=lambda: _invoke_physics_control(
                    app,
                    "toggle_playing",
                    guard_method_name="can_toggle_playing",
                ),
            )
        )
    except Exception as exc:
        report = getattr(app, "report_module_load_failure", None)
        if callable(report):
            report(ENTRY_POINT_NAME, MENU_REGISTRATION_VALUE, exc)
            return
        raise


def _invoke_physics_control(
    app: Any,
    method_name: str,
    *,
    guard_method_name: str | None = None,
) -> None:
    try:
        controls = _physics_controls(app)
        if guard_method_name is not None:
            guard = getattr(controls, guard_method_name, None)
            if callable(guard) and not bool(guard()):
                return
        method = getattr(controls, method_name, None)
        if not callable(method):
            raise RuntimeError(f"physics_controls does not expose {method_name}")
        method()
    except Exception as exc:
        report = getattr(app, "report_module_load_failure", None)
        if callable(report):
            report(ENTRY_POINT_NAME, method_name, exc)
        raise


def _physics_controls(app: Any) -> Any:
    session = app.get_adapter_session()
    controls = getattr(session, "physics_controls", None)
    if controls is None:
        raise RuntimeError("active adapter session does not expose physics_controls")
    return controls


def _has_physics_controls(app: Any) -> bool:
    try:
        _physics_controls(app)
    except Exception:
        return False
    return True


def _control_label(app: Any, method_name: str, fallback: str) -> str:
    try:
        controls = _physics_controls(app)
        method = getattr(controls, method_name, None)
        if callable(method):
            return str(method())
    except Exception:
        return fallback
    return fallback


def _control_enabled(app: Any, method_name: str) -> bool:
    try:
        controls = _physics_controls(app)
        method = getattr(controls, method_name, None)
        if callable(method):
            return bool(method())
    except Exception:
        return False
    return False
