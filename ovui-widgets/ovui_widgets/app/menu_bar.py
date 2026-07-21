# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Application menu bar for USD Viewer."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List

import omni.ui as ui

from ovui_widgets.app.layout import MENU_BAR_HEIGHT
from ovui_widgets.app.menu_hooks import (
    AppMenuContribution,
    AppMenuContributionProvider,
    AppMenuRegistry,
)
from ovui_widgets.common.menu import create_flat_menu

PRODUCT_LABEL = "USD Viewer"
TOP_LEVEL_MENU_LABELS = ("File", "Edit", "Layer", "Create", "Tools", "View", "Window", "Help")
TOP_LEVEL_MENU_STYLE = "MenuBar.Menu"
INTEGRATED_TOP_LEVEL_CONTRIBUTION_MENUS = ("File",)

_LOGO_SIZE = 12
_LEADING_SPACE = 8
_ICON_LABEL_GAP = 4
_PRODUCT_LABEL_WIDTH = 48
_PRODUCT_SEPARATOR_GAP = 6
_MENU_GROUP_GAP = 10
_MENU_ITEM_GAP = 10
_SEPARATOR_HEIGHT = 10
_LOGO_OPTICAL_NUDGE_Y = 0
_LOGO_TOP_PADDING = max(
    0,
    ((MENU_BAR_HEIGHT - _LOGO_SIZE) // 2) + _LOGO_OPTICAL_NUDGE_Y,
)
_LOGO_BOTTOM_PADDING = max(0, MENU_BAR_HEIGHT - _LOGO_SIZE - _LOGO_TOP_PADDING)
_LOGO_PROVIDER: Any | None = None
_MENU_CONTRIBUTIONS: dict[str, "MenuContribution"] = {}
_CONTRIBUTED_MENUS: dict[tuple[str, ...], Any] = {}
_GLOBAL_MENU_PROVIDER_ID = "ovui_widgets.app.menu_bar.global_menu_contributions"


@dataclass(frozen=True)
class MenuContribution:
    """One optional menu item contributed by a wheel-packaged component."""

    menu_path: tuple[str, ...]
    stable_id: str
    label: str | Callable[[], str]
    order: int = 100
    action: Callable[[], None] | None = None
    enabled: bool | Callable[[], bool] = True
    visible: bool | Callable[[], bool] = True
    hotkey_text: str = ""

    def __post_init__(self) -> None:
        if not self.menu_path:
            raise ValueError("menu_path must contain at least one menu label")
        if not all(str(part).strip() for part in self.menu_path):
            raise ValueError("menu_path labels must not be empty")
        if not str(self.stable_id).strip():
            raise ValueError("stable_id must not be empty")
        if callable(self.label):
            return
        if not str(self.label).strip():
            raise ValueError("label must not be empty")


class _MenuContributionHandle:
    """Registration handle returned by :func:`register_menu_item`."""

    def __init__(self, contribution: MenuContribution) -> None:
        self._contribution = contribution

    def cancel(self) -> None:
        current = _MENU_CONTRIBUTIONS.get(self._contribution.stable_id)
        if current is self._contribution:
            _MENU_CONTRIBUTIONS.pop(self._contribution.stable_id, None)


def register_menu_item(contribution: MenuContribution) -> _MenuContributionHandle:
    """Register or replace a process-global menu contribution."""
    if not isinstance(contribution, MenuContribution):
        raise TypeError("contribution must be a MenuContribution")
    _MENU_CONTRIBUTIONS[contribution.stable_id] = contribution
    return _MenuContributionHandle(contribution)


def get_menu_contributions(
    menu_path: tuple[str, ...] | None = None,
) -> tuple[MenuContribution, ...]:
    """Return registered contributions, optionally filtered to one path."""
    contributions = tuple(_MENU_CONTRIBUTIONS.values())
    if menu_path is not None:
        contributions = tuple(
            contribution
            for contribution in contributions
            if contribution.menu_path == menu_path
        )
    return tuple(
        sorted(contributions, key=lambda item: (item.order, _resolve_contribution_label(item)))
    )


def build_menu_bar(app: Any) -> None:
    """Populate menus inside the current ui.MenuBar context.

    app: Application instance (for undo_manager access).
    """
    _ensure_global_menu_provider(app)
    app._inspector_top_level_menus = {}
    _build_product_identity()

    file_menu = create_flat_menu(
        "File",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
        on_build_fn=lambda: _build_file_menu(app),
    )
    _wire_file_menu_invalidation(app, file_menu)
    _remember_top_level_menu(app, "File", file_menu)
    with file_menu:
        pass

    _menu_gap()
    edit_menu = create_flat_menu(
        "Edit",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
        on_build_fn=lambda: _build_edit_menu(app),
    )
    _wire_edit_menu_invalidation(app, edit_menu)
    _remember_top_level_menu(app, "Edit", edit_menu)
    with edit_menu:
        pass

    _menu_gap()
    layer_menu = create_flat_menu(
        "Layer",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
        on_build_fn=lambda: _build_layer_menu(app),
    )
    _wire_layer_menu_invalidation(app, layer_menu)
    _remember_top_level_menu(app, "Layer", layer_menu)
    with layer_menu:
        pass

    _menu_gap()
    from ovui_widgets.app import create_menu
    create_menu_widget = create_flat_menu(
        "Create",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
        on_build_fn=lambda: create_menu.build_create_menu(app),
    )
    app._create_menu = create_menu_widget
    _remember_top_level_menu(app, "Create", create_menu_widget)
    with create_menu_widget:
        pass

    _menu_gap()
    tools_menu = create_flat_menu(
        "Tools",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
        on_build_fn=lambda: _build_tools_menu(app),
    )
    _remember_top_level_menu(app, "Tools", tools_menu)
    with tools_menu:
        pass

    if _app_menu_registry(app) is None:
        _build_contributed_top_level_menus(app)
    else:
        _build_hook_roots(app)

    _menu_gap()
    view_menu = create_flat_menu(
        "View",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
        on_build_fn=lambda: _build_view_menu(app),
    )
    _remember_top_level_menu(app, "View", view_menu)
    with view_menu:
        pass

    _menu_gap()
    window_menu = create_flat_menu(
        "Window",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
    )
    _remember_top_level_menu(app, "Window", window_menu)
    with window_menu:
        ui.MenuItem("Stage Browser", triggered_fn=lambda: _toggle_window(app._stage_window))
        ui.MenuItem("Property Inspector", triggered_fn=lambda: _toggle_window(app._property_window))
        ui.MenuItem("Viewport", triggered_fn=lambda: _toggle_window(app._viewport_window))
        ui.MenuItem("Content Browser", triggered_fn=lambda: _toggle_window(app._content_window))
        ui.MenuItem(
            "Layers",
            hotkey_text="Ctrl+L",
            checkable=True,
            checked=bool(app._layer_window is not None and app._layer_window.visible),
            triggered_fn=lambda: _toggle_window(app._layer_window),
        )
        ui.Separator()
        ui.MenuItem("Reset Layout", triggered_fn=_reset_layout)
        _build_hook_items(app, ("Window",))

    _menu_gap()
    help_menu = create_flat_menu(
        "Help",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
    )
    _remember_top_level_menu(app, "Help", help_menu)
    with help_menu:
        ui.MenuItem("About USD Viewer", triggered_fn=lambda: print("[OvGear] v0.1.0"))
        _build_hook_items(app, ("Help",))


def _remember_top_level_menu(app: Any, label: str, menu: Any) -> None:
    try:
        menus = vars(app).setdefault("_inspector_top_level_menus", {})
    except TypeError:
        return
    menus[str(label)] = menu


def _build_product_identity() -> None:
    """Render the static product mark before the interactive menus."""
    ui.Spacer(width=_LEADING_SPACE)
    with ui.VStack(width=_LOGO_SIZE, height=MENU_BAR_HEIGHT, spacing=0):
        ui.Spacer(height=_LOGO_TOP_PADDING)
        ui.ImageWithProvider(
            _get_logo_provider(),
            width=_LOGO_SIZE,
            height=_LOGO_SIZE,
            style_type_name_override="MenuBar.Logo",
        )
        ui.Spacer(height=_LOGO_BOTTOM_PADDING)
    ui.Spacer(width=_ICON_LABEL_GAP)
    ui.Label(
        PRODUCT_LABEL,
        width=_PRODUCT_LABEL_WIDTH,
        height=MENU_BAR_HEIGHT,
        style_type_name_override="MenuBar.ProductLabel",
    )
    ui.Spacer(width=_PRODUCT_SEPARATOR_GAP)
    ui.Rectangle(
        width=1,
        height=_SEPARATOR_HEIGHT,
        style_type_name_override="MenuBar.ProductSeparator",
    )
    ui.Spacer(width=_MENU_GROUP_GAP)


def _get_logo_provider() -> "ui.RasterImageProvider":
    """Return the cached raster provider for the menu-bar product logo."""
    global _LOGO_PROVIDER
    if _LOGO_PROVIDER is None:
        from ovui_widgets.common.style.urls import get_icon_path

        _LOGO_PROVIDER = ui.RasterImageProvider(get_icon_path("app_logo"))
    return _LOGO_PROVIDER


def _menu_gap() -> None:
    ui.Spacer(width=_MENU_ITEM_GAP)


def _ensure_global_menu_provider(app: Any) -> None:
    registry = _app_menu_registry(app)
    if registry is None:
        return
    try:
        app_state = vars(app)
    except TypeError:
        return
    handles = app_state.setdefault("_menu_bar_global_menu_handles", {})
    if _GLOBAL_MENU_PROVIDER_ID in handles:
        return
    handles[_GLOBAL_MENU_PROVIDER_ID] = registry.add_provider(
        AppMenuContributionProvider(
            id=_GLOBAL_MENU_PROVIDER_ID,
            contributions_fn=_global_menu_contributions,
        )
    )


def _global_menu_contributions(app: Any) -> tuple[AppMenuContribution, ...]:
    del app
    entries: list[AppMenuContribution] = []
    for contribution in _visible_menu_contributions(None):
        try:
            label = _resolve_contribution_label(contribution)
        except Exception:
            continue
        entries.append(
            AppMenuContribution(
                id=f"legacy_menu.{contribution.stable_id}",
                label=label,
                parent_path=contribution.menu_path,
                order=contribution.order,
                enabled=_resolve_contribution_enabled(contribution),
                hotkey_text=contribution.hotkey_text,
                callback=(
                    lambda _app, stable_id=contribution.stable_id: _run_registered_contribution(
                        stable_id
                    )
                ),
                widget_name=f"legacy_menu_{_safe_widget_name(contribution.stable_id)}",
            )
        )
    return tuple(entries)


def _run_registered_contribution(stable_id: str) -> None:
    contribution = _MENU_CONTRIBUTIONS.get(stable_id)
    if contribution is not None:
        _run_contribution_action(contribution)


def _safe_widget_name(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value))


def _app_menu_registry(app: Any) -> AppMenuRegistry | None:
    registry = getattr(app, "menus", None)
    return registry if isinstance(registry, AppMenuRegistry) else None


def _build_hook_items(app: Any, path: tuple[str, ...]) -> None:
    _ensure_global_menu_provider(app)
    registry = _app_menu_registry(app)
    if registry is not None:
        registry.build_path(path, ui)


def _build_hook_roots(app: Any) -> None:
    _ensure_global_menu_provider(app)
    registry = _app_menu_registry(app)
    if registry is None:
        return
    try:
        roots = registry.iter_top_level_menus(exclude=TOP_LEVEL_MENU_LABELS)
    except Exception:
        return
    for root in roots:
        _menu_gap()
        menu = create_flat_menu(
            root.label,
            ui_module=ui,
            style_type_name_override=TOP_LEVEL_MENU_STYLE,
            on_build_fn=lambda p=root.path: registry.build_path(p, ui),
        )
        _remember_top_level_menu(app, root.label, menu)
        _wire_contributed_menu_invalidation(root.path, menu)
        with menu:
            pass


def _build_file_menu(app: Any) -> None:
    """Build File menu entries from the current application state."""
    can_save_stage = _can_save_stage(app)
    create_new_stage = getattr(app, "new_stage", None)
    can_create_new_stage = callable(create_new_stage)
    can_create_query = getattr(app, "_can_create_empty_startup_stage", None)
    if can_create_new_stage and callable(can_create_query):
        try:
            can_create_new_stage = bool(can_create_query())
        except Exception:
            can_create_new_stage = False
    ui.MenuItem(
        "New",
        triggered_fn=(lambda: create_new_stage()) if can_create_new_stage else None,
        enabled=can_create_new_stage,
    )
    ui.MenuItem("Open...", triggered_fn=lambda: _on_open_clicked(app))
    with create_flat_menu(
        "Recent Files",
        ui_module=ui,
        on_build_fn=lambda: _build_recent_items(app),
    ):
        pass
    if _app_menu_registry(app) is None:
        _build_contribution_branch(app, ("File",))
    ui.Separator()
    ui.MenuItem(
        "Save",
        triggered_fn=lambda: _on_save_clicked(app),
        enabled=can_save_stage,
    )
    ui.MenuItem(
        "Save As...",
        triggered_fn=lambda: _on_save_as_clicked(app),
        enabled=can_save_stage,
    )
    ui.Separator()
    _build_hook_items(app, ("File",))
    ui.MenuItem("Exit", triggered_fn=_on_exit)


def _wire_file_menu_invalidation(app: Any, file_menu: Any) -> None:
    """Keep the File menu dirty so its state rebuilds on each open."""
    app._file_menu = file_menu
    set_shown_changed_fn = getattr(file_menu, "set_shown_changed_fn", None)
    if callable(set_shown_changed_fn):
        set_shown_changed_fn(lambda shown: _invalidate_file_menu(app))


def _invalidate_file_menu(app: Any) -> None:
    file_menu = getattr(app, "_file_menu", None)
    invalidate = getattr(file_menu, "invalidate", None)
    if callable(invalidate):
        invalidate()


def _wire_layer_menu_invalidation(app: Any, layer_menu: Any) -> None:
    """Keep the Layer menu dirty so loaded layer-stack state is fresh."""
    app._layer_menu = layer_menu
    set_shown_changed_fn = getattr(layer_menu, "set_shown_changed_fn", None)
    if callable(set_shown_changed_fn):
        set_shown_changed_fn(lambda shown: _invalidate_layer_menu(app))


def _invalidate_layer_menu(app: Any) -> None:
    layer_menu = getattr(app, "_layer_menu", None)
    invalidate = getattr(layer_menu, "invalidate", None)
    if callable(invalidate):
        invalidate()


def _can_save_stage(app: Any) -> bool:
    if _stage_adapter_from_app(app) is None:
        return False
    get_adapter_session = getattr(app, "get_adapter_session", None)
    session = get_adapter_session() if callable(get_adapter_session) else None
    if session is None:
        session = getattr(app, "_adapter_session", None)
    if session is None:
        return False
    try:
        capabilities = session.get_capabilities()
    except (AttributeError, RuntimeError):
        return False
    return bool(capabilities.stage.export_stage.is_supported)


def _active_layer_adapter(app: Any) -> Any | None:
    """Return only an explicitly installed application layer adapter.

    Reading through ``getattr`` would make permissive test doubles such as
    ``MagicMock`` look like a live adapter. The application stores this seam as
    a concrete instance field, so inspect its state dictionary directly.
    """

    try:
        return vars(app).get("_layer_adapter")
    except TypeError:
        return None


def _stage_adapter_from_app(app: Any) -> Any | None:
    getter = getattr(app, "get_stage_adapter", None)
    if callable(getter):
        try:
            adapter = getter()
        except Exception:
            adapter = None
        if adapter is not None:
            return adapter

    adapter = getattr(app, "stage_adapter", None)
    if adapter is not None:
        return adapter

    legacy_getter = getattr(app, "_get_stage_adapter", None)
    if callable(legacy_getter):
        try:
            adapter = legacy_getter()
        except Exception:
            adapter = None
        if adapter is not None:
            return adapter

    return getattr(app, "_stage_adapter", None)


def _build_contributed_top_level_menus(app: Any) -> None:
    visible = _visible_menu_contributions(app)
    labels = sorted(
        {
            contribution.menu_path[0]
            for contribution in visible
            if contribution.menu_path[0] not in INTEGRATED_TOP_LEVEL_CONTRIBUTION_MENUS
        }
    )
    for label in labels:
        _menu_gap()
        menu_path = (label,)
        menu = create_flat_menu(
            label,
            ui_module=ui,
            style_type_name_override=TOP_LEVEL_MENU_STYLE,
            on_build_fn=lambda menu_label=label: _build_contribution_branch(
                app, (menu_label,)
            ),
        )
        _remember_top_level_menu(app, label, menu)
        _wire_contributed_menu_invalidation(menu_path, menu)
        with menu:
            pass


def _build_contribution_branch(app: Any, prefix: tuple[str, ...]) -> None:
    visible = _visible_menu_contributions(app)
    children = sorted(
        {
            contribution.menu_path[len(prefix)]
            for contribution in visible
            if _menu_path_startswith(contribution.menu_path, prefix)
            and len(contribution.menu_path) > len(prefix)
        },
        key=lambda label: _contribution_group_sort_key(app, prefix, label),
    )
    direct_items = tuple(
        contribution
        for contribution in get_menu_contributions(prefix)
        if _resolve_contribution_visible(contribution)
    )
    for child in children:
        child_prefix = prefix + (child,)
        menu = create_flat_menu(
            child,
            ui_module=ui,
            on_build_fn=lambda item_prefix=child_prefix: _build_contribution_branch(
                app, item_prefix
            ),
        )
        _wire_contributed_menu_invalidation(child_prefix, menu)
        with menu:
            pass
    if children and direct_items:
        ui.Separator()
    for contribution in direct_items:
        _build_contribution_item(contribution)


def _build_contribution_item(contribution: MenuContribution) -> None:
    label = _resolve_contribution_label(contribution)
    kwargs: dict[str, Any] = {
        "triggered_fn": lambda item=contribution: _run_contribution_action(item),
        "enabled": _resolve_contribution_enabled(contribution),
    }
    if contribution.hotkey_text:
        kwargs["hotkey_text"] = contribution.hotkey_text
    ui.MenuItem(label, **kwargs)


def _wire_contributed_menu_invalidation(
    menu_path: tuple[str, ...],
    menu: Any,
) -> None:
    _CONTRIBUTED_MENUS[menu_path] = menu
    set_shown_changed_fn = getattr(menu, "set_shown_changed_fn", None)
    if callable(set_shown_changed_fn):
        set_shown_changed_fn(lambda shown, path=menu_path: _invalidate_contributed_menu(path))


def _invalidate_contributed_menu(menu_path: tuple[str, ...]) -> None:
    menu = _CONTRIBUTED_MENUS.get(menu_path)
    invalidate = getattr(menu, "invalidate", None)
    if callable(invalidate):
        invalidate()


def _invalidate_contributed_menus() -> None:
    for menu_path in tuple(_CONTRIBUTED_MENUS):
        _invalidate_contributed_menu(menu_path)


def _run_contribution_action(contribution: MenuContribution) -> None:
    try:
        action = contribution.action
        if callable(action):
            action()
    finally:
        _invalidate_contributed_menus()


def _resolve_contribution_label(contribution: MenuContribution) -> str:
    label = contribution.label() if callable(contribution.label) else contribution.label
    label_text = str(label).strip()
    if not label_text:
        raise ValueError(f"menu contribution {contribution.stable_id!r} label is empty")
    return label_text


def _resolve_contribution_enabled(contribution: MenuContribution) -> bool:
    enabled = contribution.enabled
    return bool(enabled()) if callable(enabled) else bool(enabled)


def _resolve_contribution_visible(contribution: MenuContribution) -> bool:
    visible = contribution.visible
    try:
        return bool(visible()) if callable(visible) else bool(visible)
    except Exception:
        return False


def _visible_menu_contributions(app: Any) -> tuple[MenuContribution, ...]:
    del app
    return tuple(
        contribution
        for contribution in _MENU_CONTRIBUTIONS.values()
        if _resolve_contribution_visible(contribution)
    )


def _menu_path_startswith(
    menu_path: tuple[str, ...],
    prefix: tuple[str, ...],
) -> bool:
    return len(menu_path) >= len(prefix) and menu_path[: len(prefix)] == prefix


def _contribution_group_sort_key(app: Any, prefix: tuple[str, ...], label: str) -> tuple[int, str]:
    child_prefix = prefix + (label,)
    matching = [
        contribution.order
        for contribution in _visible_menu_contributions(app)
        if _menu_path_startswith(contribution.menu_path, child_prefix)
    ]
    order = min(matching) if matching else 100
    return order, label


def _build_edit_menu(app: Any) -> None:
    """Build Edit menu children. Called on each menu open for live enabled state."""
    ui.MenuItem(
        "Undo",
        hotkey_text="Ctrl+Z",
        triggered_fn=lambda: app.undo_manager.undo(),
        enabled=app.undo_manager.can_undo(),
    )
    ui.MenuItem(
        "Redo",
        hotkey_text="Ctrl+Shift+Z",
        triggered_fn=lambda: app.undo_manager.redo(),
        enabled=app.undo_manager.can_redo(),
    )
    ui.Separator()
    ui.MenuItem("Settings...", triggered_fn=lambda: app._settings_dialog.show())
    _build_hook_items(app, ("Edit",))


def _wire_edit_menu_invalidation(app: Any, edit_menu: Any) -> None:
    """Invalidate the Edit menu whenever undo/redo availability changes."""
    invalidate = getattr(edit_menu, "invalidate", None)
    undo_manager = getattr(app, "undo_manager", None)
    subscribe_change = getattr(undo_manager, "subscribe_change", None)
    if not callable(invalidate) or not callable(subscribe_change):
        return

    stale = list(vars(app).get("_stale_edit_menu_subs") or ())
    previous_sub = vars(app).get("_edit_menu_undo_subscription")
    if previous_sub is not None:
        stale.append(previous_sub)
    app._edit_menu_undo_subscription = None
    remaining: list = []
    # Pre-assign retention so a BaseException mid-drain can never lose
    # ownership of the remaining handles.
    app._stale_edit_menu_subs = remaining
    pending_throwable = None
    for handle in stale:
        cancel = getattr(handle, "cancel", None)
        try:
            if callable(cancel):
                cancel()
        except BaseException as exc:  # noqa: BLE001 — retained + primary
            # Failed removal stays OWNED and retryable at the next
            # rewire; installing another authoritative callback while an
            # old one is live would double-notify.
            remaining.append(handle)
            if pending_throwable is None and not isinstance(
                exc, Exception
            ):
                pending_throwable = exc
    app._edit_menu = edit_menu
    if not remaining:
        app._edit_menu_undo_subscription = subscribe_change(invalidate)
    if pending_throwable is not None:
        raise pending_throwable


def _build_layer_menu(app: Any) -> None:
    """Build Layer menu children (LAYERS-PLAN Step 58).

    Seven entries, live-rebuilt on every open via ``on_build_fn`` so the
    enabled flags and the "Set Authoring Layer" submenu track the
    current adapter / selection state without us having to invalidate
    anything imperatively:

    - **Set Authoring Layer → submenu** — one item per layer in the
      stack, checkmark on the current edit target.
    - **Save Layer** — save the target layer (dirty concrete layers).
    - **Save All** — save every dirty non-anonymous layer (Ctrl+Shift+S).
    - **Save As...** — save the target layer under a new path
      (Ctrl+Shift+Alt+S).
    - **Create Sublayer** — mint an anonymous sublayer under the target.
    - **Insert Sublayer** — add an existing file as a sublayer under
      the target.
    - **Remove Layer** — detach the target sublayer from its parent.
    - **Reload Layer** — reload the target layer from disk.

    Each handler defensively re-validates the adapter and target when
    clicked (the enabled flag may have gone stale between menu open and
    click); on validation failure it surfaces the reason through
    :class:`ErrorReporter` rather than silently failing. The Ctrl+Shift+S
    / Ctrl+Shift+Alt+S hotkey hints are informational only — Step 59
    wires the actual keyboard routes in ``Application._on_key_pressed``.
    """
    adapter = _layer_menu_adapter(app)
    has_stage = adapter is not None
    has_layer_stack = _layer_stack_available(adapter)
    capabilities = _layer_stack_capabilities(adapter)
    target, delete_spec = _layer_menu_target_and_delete_spec(app)
    has_target = has_layer_stack and target is not None
    is_not_root = has_target and _target_is_not_root(app, target)
    is_writable = has_target and bool(getattr(target, "is_writable", False))
    is_dirty = has_target and bool(getattr(target, "is_dirty", False))
    is_anonymous = has_target and bool(getattr(target, "is_anonymous", False))
    is_not_anonymous = has_target and not bool(
        getattr(target, "is_anonymous", False)
    )
    can_save_target = _layer_capability_supported(
        capabilities,
        "save_layer_as" if is_anonymous else "save_layer",
    )

    with create_flat_menu(
        "Set Authoring Layer",
        ui_module=ui,
        on_build_fn=lambda: _build_set_authoring_submenu(app),
    ):
        pass
    ui.MenuItem(
        "Save Layer",
        hotkey_text="Ctrl+Alt+S",
        triggered_fn=lambda: _on_save_layer(app),
        enabled=(
            has_stage
            and has_layer_stack
            and has_target
            and is_dirty
            and can_save_target
        ),
    )
    ui.MenuItem(
        "Save All",
        hotkey_text="Ctrl+S",
        triggered_fn=lambda: _on_save_all(app),
        enabled=(
            has_stage
            and has_layer_stack
            and _layer_capability_supported(capabilities, "save_layer")
            and _layer_save_all_available(app)
        ),
    )
    ui.MenuItem(
        "Save As...",
        hotkey_text="Ctrl+Shift+S",
        triggered_fn=lambda: _on_save_as(app),
        enabled=(
            has_stage
            and has_layer_stack
            and has_target
            and is_not_root
            and _layer_capability_supported(capabilities, "save_layer_as")
        ),
    )
    ui.Separator()
    ui.MenuItem(
        "Create Sublayer",
        triggered_fn=lambda: _on_create_sublayer(app),
        enabled=(
            has_stage
            and has_layer_stack
            and has_target
            and is_writable
            and _layer_capability_supported(capabilities, "create_sublayer")
        ),
    )
    ui.MenuItem(
        "Insert Sublayer",
        triggered_fn=lambda: _on_insert_sublayer(app),
        enabled=(
            has_stage
            and has_layer_stack
            and has_target
            and is_writable
            and _layer_capability_supported(capabilities, "insert_sublayer")
        ),
    )
    ui.Separator()
    ui.MenuItem(
        "Remove Layer",
        triggered_fn=lambda: _on_remove_layer(app),
        enabled=(
            has_stage
            and has_layer_stack
            and delete_spec is not None
            and _layer_capability_supported(capabilities, "remove_sublayer")
        ),
    )
    ui.MenuItem(
        "Reload Layer",
        triggered_fn=lambda: _on_reload_layer(app),
        enabled=(
            has_stage
            and has_layer_stack
            and has_target
            and is_not_anonymous
            and _layer_capability_supported(capabilities, "reload_layer")
        ),
    )
    _build_hook_items(app, ("Layer",))


def _build_set_authoring_submenu(app: Any) -> None:
    """Populate the dynamic "Set Authoring Layer" submenu.

    Lists every non-session layer in the stack (anonymous layers
    included — they are legitimate authoring targets). Capped at
    50 entries so a pathological asset with hundreds of sublayers
    doesn't blow out the menu (LAYERS-PLAN risk #13); an overflow
    sentinel row makes the truncation visible to the user.
    """
    adapter = _layer_menu_adapter(app)
    if adapter is None:
        ui.MenuItem("(no stage open)", enabled=False)
        return
    if not _layer_stack_supported(adapter):
        ui.MenuItem("(layer stack unavailable)", enabled=False)
        return
    try:
        identifiers = adapter.get_layer_stack_identifiers(
            include_session=False, include_anonymous=True
        )
    except Exception:
        ui.MenuItem("(layer stack unavailable)", enabled=False)
        return
    if not identifiers:
        ui.MenuItem("(no layers)", enabled=False)
        return
    try:
        current_target = adapter.get_edit_target_identifier()
    except Exception:
        current_target = ""
    capabilities = _layer_stack_capabilities(adapter)
    cap = 50
    for identifier in identifiers[:cap]:
        handle = _find_layer(adapter, identifier)
        display = _layer_display_name(adapter, handle, identifier)
        ui.MenuItem(
            display,
            checkable=True,
            checked=(identifier == current_target),
            enabled=_authoring_layer_selectable(
                adapter,
                identifier,
                capabilities,
            ),
            triggered_fn=lambda i=identifier: _on_set_authoring(app, i),
        )
    if len(identifiers) > cap:
        ui.MenuItem(
            f"(+{len(identifiers) - cap} more — narrow selection in Layers window)",
            enabled=False,
        )


def _layer_stack_identifiers(adapter: Any) -> tuple[str, ...]:
    if adapter is None or not _layer_stack_supported(adapter):
        return ()
    try:
        return tuple(
            adapter.get_layer_stack_identifiers(
                include_session=False,
                include_anonymous=True,
            )
        )
    except Exception:
        return ()


def _layer_stack_available(adapter: Any) -> bool:
    return bool(_layer_stack_identifiers(adapter))


def _layer_model(app: Any) -> Any:
    layer_window = getattr(app, "_layer_window", None)
    if layer_window is None:
        return None
    return getattr(layer_window, "_model", None)


def _layer_menu_adapter(app: Any) -> Any:
    """Return the layer-stack adapter backing the visible Layers model.

    The Layers panel owns the model users can see and interact with. Prefer
    that adapter so the top menu cannot report a different loaded-stage state
    from the panel; fall back to the application slot before the model exists.
    """
    model = _layer_model(app)
    if model is not None:
        adapter = getattr(model, "adapter", None)
        if adapter is not None:
            return adapter
    # Application owns this as a concrete instance field. Respect an explicit
    # ``None`` before probing methods: permissive objects such as MagicMock can
    # synthesize a callable getter and a fake non-None return value, making an
    # unloaded document look as if it had a layer stack.
    try:
        app_state = vars(app)
    except TypeError:
        app_state = {}
    if "_layer_adapter" in app_state:
        return app_state["_layer_adapter"]
    getter = getattr(app, "get_layer_stack_adapter", None)
    if callable(getter):
        try:
            adapter = getter()
        except Exception:
            adapter = None
        if adapter is not None:
            return adapter
    adapter = getattr(app, "layer_stack_adapter", None)
    if adapter is not None:
        return adapter
    return getattr(app, "_layer_adapter", None)


def _layer_stack_supported(adapter: Any) -> bool:
    return _layer_capability_supported(
        _layer_stack_capabilities(adapter),
        "layer_stack",
    )


def _layer_stack_capabilities(adapter: Any) -> Any:
    try:
        return adapter.get_capabilities() if adapter is not None else None
    except Exception:
        return None


def _layer_capability_supported(capabilities: Any, capability_name: str) -> bool:
    try:
        return bool(getattr(capabilities, capability_name).is_supported)
    except Exception:
        return False


def _find_layer(adapter: Any, identifier: str) -> Any:
    try:
        return adapter.find_layer(identifier)
    except Exception:
        return None


def _layer_display_name(adapter: Any, handle: Any, fallback: str) -> str:
    if handle is None:
        return fallback
    try:
        return adapter.get_display_name(handle)
    except Exception:
        return fallback


def _authoring_layer_selectable(
    adapter: Any,
    identifier: str,
    capabilities: Any,
) -> bool:
    if not _layer_capability_supported(capabilities, "edit_target_write"):
        return False
    handle = _find_layer(adapter, identifier)
    if handle is None:
        return False
    try:
        return bool(adapter.is_writable(handle))
    except Exception:
        return False


def _layer_save_all_available(app: Any) -> bool:
    model = _layer_model(app)
    if model is None:
        return False
    try:
        save_all_model = model.get_save_all_model()
        return bool(save_all_model.get_value_as_bool())
    except Exception:
        return False


def _layer_menu_target_and_delete_spec(app: Any) -> tuple[Any, Any]:
    layer_window = getattr(app, "_layer_window", None)
    resolver = getattr(layer_window, "_footer_target_and_delete_spec", None)
    if callable(resolver):
        try:
            result = resolver()
        except Exception:
            result = None
        if isinstance(result, tuple) and len(result) == 2:
            return result
    target = _current_layer_target(app)
    return target, _delete_spec_for_target(app, target)


def _delete_spec_for_target(app: Any, target: Any) -> Any:
    # Fallback for tests and lightweight app surfaces that do not expose
    # LayerWindow._footer_target_and_delete_spec().
    if target is None or not _target_is_not_root(app, target):
        return None
    model = _layer_model(app)
    if model is None:
        return None
    parent = getattr(target, "_parent", None)
    adapter = getattr(model, "_adapter", None) or getattr(model, "adapter", None)
    if parent is None or adapter is None:
        return None
    try:
        parent_handle = adapter.find_layer(parent.identifier)
        if parent_handle is None:
            return None
        children = adapter.get_sublayer_identifiers(parent_handle)
        if target.identifier not in children:
            return None
        return parent.identifier, children.index(target.identifier)
    except Exception:
        return None


def _current_layer_target(app: Any) -> Any:
    """Return the layer the Layer menu acts on, or ``None``.

    Mirrors :meth:`LayerWindow._footer_target_and_delete_spec`: a single
    :class:`LayerItem` selection in the Layers tree wins; otherwise
    falls back to the tree's root layer. Returns ``None`` when the
    Layers window isn't up yet or the model has no root (pre-stage /
    torn-down states).
    """
    model = _layer_model(app)
    if model is None:
        return None
    try:
        from ovui_widgets.layers.layer_item import LayerItem
    except Exception:
        return None
    selected = [
        i for i in getattr(model, "selected_items", []) if isinstance(i, LayerItem)
    ]
    if len(selected) == 1:
        return selected[0]
    return getattr(model, "root_item", None)


def _target_is_not_root(app: Any, target: Any) -> bool:
    """``True`` iff ``target`` is not the Layers tree's root item."""
    layer_window = getattr(app, "_layer_window", None)
    model = getattr(layer_window, "_model", None) if layer_window else None
    root = getattr(model, "root_item", None) if model is not None else None
    if root is None:
        return False
    return getattr(target, "identifier", None) != getattr(root, "identifier", None)


def _require_stage(app: Any) -> bool:
    """Validate that a stage is loaded; surface a toast and return ``False`` if not.

    Defensive guard for every Layer-menu click handler — the enabled
    flag set at menu-build time may have gone stale between open and
    click (stage close race). Mirrors the
    ``check the active layer-stack adapter first; show an error toast``
    contract from LAYERS-PLAN Step 58.
    """
    adapter = _layer_menu_adapter(app)
    if adapter is None:
        try:
            from ovui_widgets.common.error_reporter import ErrorReporter
            ErrorReporter.show_error("No stage open")
        except Exception:
            pass
        return False
    if not _layer_stack_available(adapter):
        try:
            from ovui_widgets.common.error_reporter import ErrorReporter
            ErrorReporter.show_warning("Layer stack is unavailable")
        except Exception:
            pass
        return False
    return True


def _require_target(app: Any) -> Any:
    """Return the current menu target LayerItem, or ``None`` after a toast."""
    target = _current_layer_target(app)
    if target is None:
        try:
            from ovui_widgets.common.error_reporter import ErrorReporter
            ErrorReporter.show_warning("No layer selected")
        except Exception:
            pass
    return target


def _on_set_authoring(app: Any, identifier: str) -> None:
    """Switch the edit target to ``identifier`` via undoable command."""
    if not _require_stage(app):
        return
    adapter = _layer_menu_adapter(app)
    if not _authoring_layer_selectable(
        adapter,
        identifier,
        _layer_stack_capabilities(adapter),
    ):
        try:
            from ovui_widgets.common.error_reporter import ErrorReporter
            ErrorReporter.show_warning("Layer is not writable")
        except Exception:
            pass
        return
    try:
        from ovui_widgets.layers.commands import SetEditTargetCommand
    except Exception:
        return
    cmd = SetEditTargetCommand(adapter, app.selection_bus, identifier)
    app.undo_manager.push(cmd)


def _on_save_layer(app: Any) -> None:
    """Save the target layer through the shared LayerModel request path."""
    if not _require_stage(app):
        return
    target = _require_target(app)
    if target is None:
        return
    model = app._layer_window._model if app._layer_window else None
    if model is None:
        return
    model._request_save(target)


def _on_save_all(app: Any) -> None:
    """Save every dirty non-anonymous layer in a single undo group."""
    if not _require_stage(app):
        return
    model = app._layer_window._model if app._layer_window else None
    if model is None:
        return
    model._request_save_all()


def _on_save_as(app: Any) -> None:
    """Save the target layer under a new path; parent reference is updated."""
    if not _require_stage(app):
        return
    target = _require_target(app)
    if target is None:
        return
    model = app._layer_window._model if app._layer_window else None
    if model is None:
        return
    model._request_save_as(target)


def _on_create_sublayer(app: Any) -> None:
    """Mint a fresh anonymous sublayer under the target layer."""
    if not _require_stage(app):
        return
    target = _require_target(app)
    if target is None:
        return
    try:
        from ovui_widgets.layers.commands import CreateSublayerCommand
    except Exception:
        return
    adapter = _layer_menu_adapter(app)
    cmd = CreateSublayerCommand(
        adapter,
        app.selection_bus,
        target.identifier,
        -1,
        "",
        transfer_root_content=False,
    )
    app.undo_manager.push(cmd)


def _on_insert_sublayer(app: Any) -> None:
    """Open a picker and insert the chosen file as a sublayer under target."""
    if not _require_stage(app):
        return
    target = _require_target(app)
    if target is None:
        return
    try:
        from ovui_widgets.common.file_dialogs import save_file_dialog
        from ovui_widgets.layers.commands import InsertSublayerCommand
    except Exception:
        return
    parent_id = target.identifier
    adapter = _layer_menu_adapter(app)

    def _on_selected(chosen_path: str) -> None:
        cmd = InsertSublayerCommand(
            adapter,
            app.selection_bus,
            parent_id,
            -1,
            chosen_path,
        )
        app.undo_manager.push(cmd)

    save_file_dialog(
        title=f"Insert Sublayer into '{parent_id}'",
        default_name="",
        on_selected=_on_selected,
    )


def _on_remove_layer(app: Any) -> None:
    """Detach the target sublayer from its parent via the model flow."""
    if not _require_stage(app):
        return
    target = _require_target(app)
    if target is None:
        return
    if not _target_is_not_root(app, target):
        try:
            from ovui_widgets.common.error_reporter import ErrorReporter
            ErrorReporter.show_warning("Cannot remove the root layer")
        except Exception:
            pass
        return
    parent = getattr(target, "_parent", None)
    if parent is None:
        return
    adapter = _layer_menu_adapter(app)
    parent_handle = adapter.find_layer(parent.identifier)
    if parent_handle is None:
        return
    children = adapter.get_sublayer_identifiers(parent_handle)
    if target.identifier not in children:
        return
    position = children.index(target.identifier)
    model = app._layer_window._model if app._layer_window else None
    if model is None:
        return
    model._request_remove_sublayer(parent.identifier, position)


def _on_reload_layer(app: Any) -> None:
    """Reload the target layer from disk through the shared model flow."""
    if not _require_stage(app):
        return
    target = _require_target(app)
    if target is None:
        return
    if bool(getattr(target, "is_anonymous", False)):
        try:
            from ovui_widgets.common.error_reporter import ErrorReporter
            ErrorReporter.show_warning(
                "Anonymous layers cannot be reloaded"
            )
        except Exception:
            pass
        return
    model = app._layer_window._model if app._layer_window else None
    if model is None:
        return
    model._request_reload(target)


def _build_tools_menu(app: Any) -> None:
    """Build Tools menu children — transform-mode picker with checkmark state.

    Rebuilt on every open (``on_build_fn``) so the checkmark next to the
    currently-active tool stays in sync after a W/E/R hotkey or a
    toolbar-driven change; ``omni.ui`` does not support dynamic mutation
    of a once-built menu item's state.
    """
    from ovui_widgets.viewport.manipulator_registry import ACTIVE_TOOL_SETTING
    from ovui_widgets.viewport.transform_manipulator import (
        TOOL_ROTATE,
        TOOL_SCALE,
        TOOL_TRANSLATE,
    )

    current = app.settings.get(ACTIVE_TOOL_SETTING, TOOL_TRANSLATE)

    def _set_tool(tool: str) -> None:
        app.settings.set(ACTIVE_TOOL_SETTING, tool)

    ui.MenuItem(
        "Move",
        hotkey_text="W",
        checkable=True,
        checked=(current == TOOL_TRANSLATE),
        triggered_fn=lambda: _set_tool(TOOL_TRANSLATE),
    )
    ui.MenuItem(
        "Rotate",
        hotkey_text="E",
        checkable=True,
        checked=(current == TOOL_ROTATE),
        triggered_fn=lambda: _set_tool(TOOL_ROTATE),
    )
    ui.MenuItem(
        "Scale",
        hotkey_text="R",
        checkable=True,
        checked=(current == TOOL_SCALE),
        triggered_fn=lambda: _set_tool(TOOL_SCALE),
    )
    _build_hook_items(app, ("Tools",))


def _build_view_menu(app: Any) -> None:
    """Build View menu children — theme picker + Focus Selected action."""
    ui.MenuItem(
        "Focus Selected",
        hotkey_text="F",
        triggered_fn=lambda: _frame_selected(app),
    )
    ui.Separator()
    ui.MenuItem(
        "Light Theme",
        triggered_fn=lambda: app.settings.set("ui.theme", "light"),
    )
    ui.MenuItem(
        "Dark Theme",
        triggered_fn=lambda: app.settings.set("ui.theme", "dark"),
    )
    _build_hook_items(app, ("View",))


def _frame_selected(app: Any) -> None:
    """Frame the camera on the current selection — Tools/View menu fallback for F.

    Mirrors :meth:`Application._frame_selected` but is safe to call from a
    menu item (which omni.ui triggers synchronously on the UI thread). No-op
    when nothing is selected or the viewport is not up yet.
    """
    snap = app.selection_bus.get_snapshot()
    if snap is None or app._viewport_window is None:
        return
    paths = [item.path for item in snap.items]
    if not paths:
        return
    app._viewport_window.frame_paths(paths)


def _toggle_window(win: Any) -> None:
    """Toggle visibility of a ManagedWindow. No-op if win is None."""
    if win is not None:
        win.visible = not win.visible


def _reset_layout() -> None:
    """Reset all panel windows to the default docked layout."""
    from ovui_widgets.app.layout import apply_default_layout
    apply_default_layout()


def _build_recent_items(app: Any) -> None:
    """Populate Open Recent submenu items. Called on each menu open."""
    paths = app._recent_files.get_ordered()
    if paths:
        for path in paths:
            name = Path(path).name
            ui.MenuItem(name, triggered_fn=lambda p=path: app.open_file(p))
    else:
        ui.MenuItem("(empty)", enabled=False)


_USD_EXTENSION_TYPES = [
    ("*.usd, *.usda, *.usdc, *.usdz", "USD Files"),
    ("*.*", "All files"),
]

# Save As extension combo. Architecture §22.4 verbatim — USD Binary/Ascii,
# USD Ascii, USD Crate. Tighter than ``_USD_EXTENSION_TYPES`` because the
# exporter only writes to formats :meth:`pxr.Usd.Stage.Export` knows how
# to emit; ``.usdz`` (a package format) is intentionally omitted so the
# user cannot pick it and hit an opaque error at write time.
_SAVE_EXTENSION_TYPES = [
    ("*.usd", "USD Binary or Ascii"),
    ("*.usda", "USD Ascii"),
    ("*.usdc", "USD Crate"),
]


def _to_stage_open_path(url: str) -> str:
    """Convert local file:// picker URLs into paths OpenUSD accepts."""
    if not url.lower().startswith("file://"):
        return url
    path = url[len("file://") :]
    if (
        sys.platform == "win32"
        and len(path) >= 3
        and path[0] == "/"
        and path[2] == ":"
    ):
        path = path[1:]
    return path


def _join_picker_path(dirname: str, filename: str) -> str:
    """Join file-picker parts without changing the picker's slash style."""
    if not dirname:
        return filename

    dirname_lower = dirname.lower()
    if dirname_lower in {"file://", "file:///"} or dirname in {"/", "\\"}:
        base = dirname
    else:
        base = dirname.rstrip("/\\")

    if not base:
        return filename
    if base.endswith(("/", "\\")):
        return f"{base}{filename}"

    sep = "/" if base.lower().startswith("file://") else os.sep
    if "/" in base and "\\" not in base:
        sep = "/"
    elif "\\" in base and "/" not in base:
        sep = "\\"
    return f"{base}{sep}{filename}"


def _on_open_clicked(app: Any) -> None:
    """Show the File > Open picker — the content browser implementation step 54.

    The Step-53 :class:`FileImporterHelper` wraps the content-browser's
    :class:`FilePickerDialog` with the Kit-standard three-arg
    ``import_handler(filename, dirname, selections)`` contract. The
    selection list wins over the typed filename when non-empty so a user
    who double-clicks a row (or types the full path into the browser
    bar) routes through the exact URL they picked; otherwise the
    filename + dirname pair is joined per architecture §12.7.
    Local filesystem picker URLs are normalized back to native paths
    before calling :meth:`Application.open_file` because OpenUSD rejects
    ``file://`` URLs; the dirname fallback is normalized after joining.
    """
    from ovui_widgets.content.file_importer import FileImporterHelper

    def on_import(filename: str, dirname: str, selections: List[str]) -> None:
        if selections:
            path = selections[0]
        elif filename:
            path = _join_picker_path(dirname, filename)
        else:
            return
        app.open_file(_to_stage_open_path(path))

    FileImporterHelper.instance().show(
        title="Open USD File",
        import_button_label="Open",
        file_extension_types=_USD_EXTENSION_TYPES,
        import_handler=on_import,
        should_validate=True,
    )


def _on_save_clicked(app: Any) -> None:
    """Export the current composed persistent stage to its document path."""
    if not _can_save_stage(app):
        _show_save_unavailable_warning()
        return
    current = getattr(app, "_current_file_path", None)
    if current:
        app.save_stage_to(current)
        return
    _on_save_as_clicked(app)


def _on_save_as_clicked(app: Any) -> None:
    """Export the current composed persistent stage to a selected path.

    Layer-specific Save and Save As remain available from the Layer menu.
    This File-menu action preserves the ovui 0.1 stage-export contract through
    :class:`FileExporterHelper`, whose ``on_export`` closure
    that joins the typed ``filename`` with the combo-selected
    ``extension`` (e.g. ``".usd"``), composes the full path, and
    routes through :meth:`Application.save_stage_to`. When the
    composed path already exists on disk, spawns a
    :class:`ConfirmOverwriteDialog` in save mode (architecture §23.9)
    and defers the save until the user confirms — matches Kit's
    ``_show_file_existed_prompt``.
    """
    if not _can_save_stage(app):
        _show_save_unavailable_warning()
        return
    from ovui_widgets.content.file_exporter import FileExporterHelper
    from ovui_widgets.content.widget.confirm_overwrite_dialog import (
        ConfirmOverwriteDialog,
    )

    def on_export(
        filename: str,
        dirname: str,
        extension: str,
        selections: List[str],
    ) -> None:
        if not filename:
            return
        # Strip a trailing slash so the join never doubles up when the
        # browser is sitting on a root URL (``file:///`` etc.). Mirrors
        # the Step-54 open path.
        dirname = dirname.rstrip("/")
        # Append the combo-selected extension only when the user did
        # not already type one — matches Kit's
        # ``normalize_filename_parts``. An empty ``extension`` (e.g.
        # the combo is missing / unresolved) means "trust the typed
        # filename verbatim".
        if extension and not filename.lower().endswith(extension.lower()):
            composed = filename + extension
        else:
            composed = filename
        path = os.path.join(dirname, composed)
        # Local-filesystem backends surface their directories as
        # ``file://`` URLs. USD export and ``os.path.exists`` both need
        # plain filesystem paths.
        save_path = _to_stage_open_path(path)
        if os.path.exists(save_path):
            ConfirmOverwriteDialog(
                path,
                on_yes=lambda: app.save_stage_to(save_path),
            ).show()
        else:
            app.save_stage_to(save_path)

    FileExporterHelper.instance().show(
        title="Save Stage As",
        export_button_label="Save",
        file_extension_types=_SAVE_EXTENSION_TYPES,
        export_handler=on_export,
        should_validate=True,
    )


def _show_save_unavailable_warning() -> None:
    from ovui_widgets.common.error_reporter import ErrorReporter

    ErrorReporter.show_warning(
        "Save is unavailable for the active data adapter"
    )


def _on_exit() -> None:
    """Request application exit via the public ``request_exit()`` API.

    Issue #35 Step 6 — Codex Round 1 F8.

    Previously called ``ui.shutdown()`` directly, which broke ovui's run
    loop without giving :meth:`Application.shutdown` a chance to fire
    while the standalone backend was still alive — that's the whole
    issue-35 segfault path. Now flips ``_running = False`` via
    :meth:`Application.request_exit`, which lets ``run_async``'s loop
    exit at the next frame boundary and drives the ``finally:`` clause
    that calls :meth:`Application.shutdown` against a live ovui.

    Round 6 F1: the import of :class:`Application` is **inside** the
    function, not at module top. ``menu_bar`` is itself imported during
    :meth:`Application.run_async` (via :func:`build_menu_bar`), so a
    top-level ``from ovui_widgets.app.application import Application`` would
    create a circular import. By the time ``_on_exit`` fires the user
    has clicked File → Exit on a running Application instance, so the
    module is already fully imported — the lazy import is essentially
    free and avoids the cycle.
    """
    from ovui_widgets.app.application import Application  # lazy — avoids cycle
    try:
        inst = Application.instance()  # public classmethod, NOT _instance
    except RuntimeError:
        # Defensive: in practice the menu can only be active when an
        # Application exists, but if a stale callback fires after
        # shutdown has already torn down the singleton, just no-op.
        return
    inst.request_exit()


# ── Issue #35 Step 3: register the lazy-init module global so
# Application.shutdown() drops the live ui.RasterImageProvider before
# omni.ui.shutdown() runs. The registration uses
# register_singleton with sys.modules[__name__] for stable string-key
# dedup, matching the helper-classmethod registration pattern).
from ovui_widgets.common.icon_caches import register_singleton as _register_singleton_for_shutdown

_register_singleton_for_shutdown(sys.modules[__name__], "_LOGO_PROVIDER")
