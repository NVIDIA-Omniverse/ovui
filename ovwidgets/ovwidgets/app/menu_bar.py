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
from pathlib import Path
from typing import Any, List

import omni.ui as ui

from ovwidgets.app.layout import MENU_BAR_HEIGHT
from ovwidgets.common.menu import create_flat_menu

PRODUCT_LABEL = "USD Viewer"
TOP_LEVEL_MENU_LABELS = ("File", "Edit", "Layer", "Create", "Tools", "View", "Window", "Help")
TOP_LEVEL_MENU_STYLE = "MenuBar.Menu"

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


def build_menu_bar(app: Any) -> None:
    """Populate menus inside the current ui.MenuBar context.

    app: Application instance (for undo_manager access).
    """
    _build_product_identity()

    with create_flat_menu(
        "File",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
    ):
        ui.MenuItem("New", triggered_fn=lambda: print("[OvGear] New"))
        ui.MenuItem("Open...", triggered_fn=lambda: _on_open_clicked(app))
        with create_flat_menu(
            "Recent Files",
            ui_module=ui,
            on_build_fn=lambda: _build_recent_items(app),
        ):
            pass
        ui.Separator()
        ui.MenuItem("Save", triggered_fn=lambda: _on_save_clicked(app))
        ui.MenuItem("Save As...", triggered_fn=lambda: _on_save_as_clicked(app))
        ui.Separator()
        ui.MenuItem("Exit", triggered_fn=_on_exit)

    _menu_gap()
    edit_menu = create_flat_menu(
        "Edit",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
        on_build_fn=lambda: _build_edit_menu(app),
    )
    _wire_edit_menu_invalidation(app, edit_menu)
    with edit_menu:
        pass

    _menu_gap()
    with create_flat_menu(
        "Layer",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
        on_build_fn=lambda: _build_layer_menu(app),
    ):
        pass

    _menu_gap()
    from ovwidgets.app import create_menu
    with create_flat_menu(
        "Create",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
        on_build_fn=lambda: create_menu.build_create_menu(app),
    ):
        pass

    _menu_gap()
    with create_flat_menu(
        "Tools",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
        on_build_fn=lambda: _build_tools_menu(app),
    ):
        pass

    _menu_gap()
    with create_flat_menu(
        "View",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
        on_build_fn=lambda: _build_view_menu(app),
    ):
        pass

    _menu_gap()
    with create_flat_menu(
        "Window",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
    ):
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

    _menu_gap()
    with create_flat_menu(
        "Help",
        ui_module=ui,
        style_type_name_override=TOP_LEVEL_MENU_STYLE,
    ):
        ui.MenuItem("About USD Viewer", triggered_fn=lambda: print("[OvGear] v0.1.0"))


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
        from ovwidgets.common.style.urls import get_icon_path

        _LOGO_PROVIDER = ui.RasterImageProvider(get_icon_path("app_logo"))
    return _LOGO_PROVIDER


def _menu_gap() -> None:
    ui.Spacer(width=_MENU_ITEM_GAP)


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


def _wire_edit_menu_invalidation(app: Any, edit_menu: Any) -> None:
    """Invalidate the Edit menu whenever undo/redo availability changes."""
    invalidate = getattr(edit_menu, "invalidate", None)
    undo_manager = getattr(app, "undo_manager", None)
    subscribe_change = getattr(undo_manager, "subscribe_change", None)
    if not callable(invalidate) or not callable(subscribe_change):
        return

    previous_sub = vars(app).get("_edit_menu_undo_subscription")
    if previous_sub is not None:
        cancel = getattr(previous_sub, "cancel", None)
        if callable(cancel):
            cancel()

    app._edit_menu = edit_menu
    app._edit_menu_undo_subscription = subscribe_change(invalidate)


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
    adapter = getattr(app, "_layer_adapter", None)
    has_stage = adapter is not None
    target = _current_layer_target(app)
    has_target = target is not None
    is_not_root = has_target and _target_is_not_root(app, target)
    is_writable = has_target and bool(getattr(target, "is_writable", False))
    is_dirty = has_target and bool(getattr(target, "is_dirty", False))
    is_not_anonymous = has_target and not bool(
        getattr(target, "is_anonymous", False)
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
        enabled=has_stage and has_target and is_dirty,
    )
    ui.MenuItem(
        "Save All",
        hotkey_text="Ctrl+S",
        triggered_fn=lambda: _on_save_all(app),
        enabled=has_stage,
    )
    ui.MenuItem(
        "Save As...",
        hotkey_text="Ctrl+Shift+S",
        triggered_fn=lambda: _on_save_as(app),
        enabled=has_stage and has_target,
    )
    ui.Separator()
    ui.MenuItem(
        "Create Sublayer",
        triggered_fn=lambda: _on_create_sublayer(app),
        enabled=has_stage and has_target and is_writable,
    )
    ui.MenuItem(
        "Insert Sublayer",
        triggered_fn=lambda: _on_insert_sublayer(app),
        enabled=has_stage and has_target and is_writable,
    )
    ui.Separator()
    ui.MenuItem(
        "Remove Layer",
        triggered_fn=lambda: _on_remove_layer(app),
        enabled=has_stage and has_target and is_not_root,
    )
    ui.MenuItem(
        "Reload Layer",
        triggered_fn=lambda: _on_reload_layer(app),
        enabled=has_stage and has_target and is_not_anonymous,
    )


def _build_set_authoring_submenu(app: Any) -> None:
    """Populate the dynamic "Set Authoring Layer" submenu.

    Lists every non-session layer in the stack (anonymous layers
    included — they are legitimate authoring targets). Capped at
    50 entries so a pathological asset with hundreds of sublayers
    doesn't blow out the menu (LAYERS-PLAN risk #13); an overflow
    sentinel row makes the truncation visible to the user.
    """
    adapter = getattr(app, "_layer_adapter", None)
    if adapter is None:
        ui.MenuItem("(no stage open)", enabled=False)
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
    cap = 50
    for identifier in identifiers[:cap]:
        handle = adapter.find_layer(identifier)
        display = (
            adapter.get_display_name(handle) if handle is not None else identifier
        )
        ui.MenuItem(
            display,
            checkable=True,
            checked=(identifier == current_target),
            triggered_fn=lambda i=identifier: _on_set_authoring(app, i),
        )
    if len(identifiers) > cap:
        ui.MenuItem(
            f"(+{len(identifiers) - cap} more — narrow selection in Layers window)",
            enabled=False,
        )


def _current_layer_target(app: Any) -> Any:
    """Return the layer the Layer menu acts on, or ``None``.

    Mirrors :meth:`LayerWindow._footer_target_and_delete_spec`: a single
    :class:`LayerItem` selection in the Layers tree wins; otherwise
    falls back to the tree's root layer. Returns ``None`` when the
    Layers window isn't up yet or the model has no root (pre-stage /
    torn-down states).
    """
    layer_window = getattr(app, "_layer_window", None)
    if layer_window is None:
        return None
    model = getattr(layer_window, "_model", None)
    if model is None:
        return None
    try:
        from ovwidgets.layers.layer_item import LayerItem
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
    ``check app._layer_adapter is not None first; show an error toast``
    contract from LAYERS-PLAN Step 58.
    """
    if getattr(app, "_layer_adapter", None) is None:
        try:
            from ovwidgets.common.error_reporter import ErrorReporter
            ErrorReporter.show_error("No stage open")
        except Exception:
            pass
        return False
    return True


def _require_target(app: Any) -> Any:
    """Return the current menu target LayerItem, or ``None`` after a toast."""
    target = _current_layer_target(app)
    if target is None:
        try:
            from ovwidgets.common.error_reporter import ErrorReporter
            ErrorReporter.show_warning("No layer selected")
        except Exception:
            pass
    return target


def _on_set_authoring(app: Any, identifier: str) -> None:
    """Switch the edit target to ``identifier`` via undoable command."""
    if not _require_stage(app):
        return
    adapter = app._layer_adapter
    try:
        from ovwidgets.layers.commands import SetEditTargetCommand
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
        from ovwidgets.layers.commands import CreateSublayerCommand
    except Exception:
        return
    cmd = CreateSublayerCommand(
        app._layer_adapter,
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
        from ovwidgets.common.file_dialogs import save_file_dialog
        from ovwidgets.layers.commands import InsertSublayerCommand
    except Exception:
        return
    parent_id = target.identifier
    adapter = app._layer_adapter

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
            from ovwidgets.common.error_reporter import ErrorReporter
            ErrorReporter.show_warning("Cannot remove the root layer")
        except Exception:
            pass
        return
    parent = getattr(target, "_parent", None)
    if parent is None:
        return
    adapter = app._layer_adapter
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
            from ovwidgets.common.error_reporter import ErrorReporter
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
    from ovwidgets.viewport.manipulator_registry import ACTIVE_TOOL_SETTING
    from ovwidgets.viewport.transform_manipulator import (
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
    from ovwidgets.app.layout import apply_default_layout
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
    from ovwidgets.content.file_importer import FileImporterHelper

    def on_import(filename: str, dirname: str, selections: List[str]) -> None:
        if selections:
            path = selections[0]
        elif filename:
            path = os.path.join(dirname.rstrip("/"), filename)
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
    """Save the current stage — the content browser implementation step 55.

    Routes through :meth:`Application.save_stage_to` using the path
    stored at :attr:`Application._current_file_path` when a stage was
    opened from disk. When no path is tracked (e.g. the app booted
    with the default mock stage, or a stage was loaded via
    :meth:`open_stage`), falls through to :func:`_on_save_as_clicked`
    so the user picks a destination. Matches Kit's
    ``omni.kit.window.file.save`` semantics (architecture §23): Save
    with no known path is Save As.
    """
    current = getattr(app, "_current_file_path", None)
    if current:
        app.save_stage_to(current)
        return
    _on_save_as_clicked(app)


def _on_save_as_clicked(app: Any) -> None:
    """Show the File > Save As picker — the content browser implementation step 55.

    Wraps :class:`FileExporterHelper` with an ``on_export`` closure
    that joins the typed ``filename`` with the combo-selected
    ``extension`` (e.g. ``".usd"``), composes the full path, and
    routes through :meth:`Application.save_stage_to`. When the
    composed path already exists on disk, spawns a
    :class:`ConfirmOverwriteDialog` in save mode (architecture §23.9)
    and defers the save until the user confirms — matches Kit's
    ``_show_file_existed_prompt``.
    """
    from ovwidgets.content.file_exporter import FileExporterHelper
    from ovwidgets.content.widget.confirm_overwrite_dialog import (
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
        # Local-filesystem backends surface their URLs as ``file://``
        # strings. :func:`os.path.exists` wants a plain filesystem
        # path, so strip the scheme when present.
        check_path = (
            path[len("file://") :] if path.startswith("file://") else path
        )
        if os.path.exists(check_path):
            ConfirmOverwriteDialog(
                path,
                on_yes=lambda: app.save_stage_to(path),
            ).show()
        else:
            app.save_stage_to(path)

    FileExporterHelper.instance().show(
        title="Save Stage As",
        export_button_label="Save",
        file_extension_types=_SAVE_EXTENSION_TYPES,
        export_handler=on_export,
        should_validate=True,
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
    top-level ``from ovwidgets.app.application import Application`` would
    create a circular import. By the time ``_on_exit`` fires the user
    has clicked File → Exit on a running Application instance, so the
    module is already fully imported — the lazy import is essentially
    free and avoids the cycle.
    """
    from ovwidgets.app.application import Application  # lazy — avoids cycle
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
from ovwidgets.common.icon_caches import register_singleton as _register_singleton_for_shutdown

_register_singleton_for_shutdown(sys.modules[__name__], "_LOGO_PROVIDER")
