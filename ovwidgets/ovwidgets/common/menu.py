# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Shared menu construction helpers for OvGear UI surfaces."""

from __future__ import annotations

from typing import Any

_FLAT_MENU_DELEGATE: Any | None = None
_BASE_MENU_DELEGATE: Any | None = None


def _build_no_title(_: Any) -> None:
    """Suppress omni.ui's detachable-menu title/status strip."""


def _get_base_menu_delegate() -> Any:
    """Return omni.ui's stock menu delegate for non-overridden rows."""
    global _BASE_MENU_DELEGATE
    if _BASE_MENU_DELEGATE is None:
        import omni.ui as ui

        _BASE_MENU_DELEGATE = ui.MenuDelegate()
    return _BASE_MENU_DELEGATE


def _build_menu_item(item: Any) -> None:
    """Build menu rows, only overriding shortcut text alignment."""
    import omni.ui as ui

    if not isinstance(item, ui.MenuItem) or isinstance(item, ui.Separator):
        _get_base_menu_delegate().build_item(item)
        return

    hotkey_text = getattr(item, "hotkey_text", "")
    if not hotkey_text:
        _get_base_menu_delegate().build_item(item)
        return

    icon_width = 20.0
    enabled = bool(getattr(item, "enabled", True))
    with ui.HStack():
        if bool(getattr(item, "checkable", False)):
            if bool(getattr(item, "checked", False)):
                check = ui.ImageWithProvider(
                    width=icon_width,
                    style_type_name_override="Menu.Item.CheckMark",
                )
                check.enabled = enabled
            else:
                ui.Spacer(width=icon_width)
        else:
            ui.Spacer(width=icon_width / 3.0)

        label = ui.Label(
            getattr(item, "text", ""),
            style_type_name_override="Menu.Item",
        )
        label.enabled = enabled
        hotkey = ui.Label(
            hotkey_text,
            width=100.0,
            alignment=ui.Alignment.RIGHT_CENTER,
            style_type_name_override="Menu.Item.Hotkey",
        )
        hotkey.enabled = enabled


def get_flat_menu_delegate() -> Any:
    """Return the shared delegate used by popup menus without title chrome."""
    global _FLAT_MENU_DELEGATE
    if _FLAT_MENU_DELEGATE is None:
        import omni.ui as ui

        _FLAT_MENU_DELEGATE = ui.MenuDelegate(
            on_build_item=_build_menu_item,
            on_build_title=_build_no_title,
            on_build_status=_build_no_title,
            propagate=True,
        )
    return _FLAT_MENU_DELEGATE


def create_flat_menu(
    text: str = "",
    *,
    ui_module: Any | None = None,
    **kwargs: Any,
) -> Any:
    """Create a menu using the shared no-title popup delegate."""
    if ui_module is None:
        import omni.ui as ui
    else:
        ui = ui_module

    if hasattr(ui, "MenuDelegate"):
        kwargs.setdefault("delegate", get_flat_menu_delegate())
    return ui.Menu(text, **kwargs)
