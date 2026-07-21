# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Three-column row renderer for :class:`FileBrowserModel`."""

from __future__ import annotations

import importlib.resources
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple

import omni.ui as ui

from ovui_widgets.common.style.urls import get_icon_path
from ovui_widgets.content.widget import clipboard
from ovui_widgets.content.widget.column_delegate import (
    ColumnDelegateRegistry,
)
from ovui_widgets.content.widget.file_browser_model import (
    FileBrowserModel,
    FileBrowserSortPolicy,
)
from ovui_widgets.content.widget.file_item import FileItem
from ovui_widgets.content.widget.highlight_label import HighlightLabel

if TYPE_CHECKING:
    from ovui_widgets.content.widget.drop_indicator import DropIndicator
    from ovui_widgets.content.widget.rename_controller import (
        RenameController,
    )


# Row geometry mirrors StageDelegate so Stage and Content rows line up
# visually when both panels are docked side-by-side. Indent, chevron
# size, and vertical-centre VStack width all match
# ``ovui_widgets.stage.widget.stage_delegate`` to keep the expand/collapse
# arrow visually identical between the two browsers.
_ROW_HEIGHT = 22
_HEADER_HEIGHT = 22
_INDENT_PER_LEVEL = 14
_FILE_ICON_SIZE = 16
_CHEVRON_SIZE = 12
_SORT_ARROW_SIZE = 10
_COLUMN_RIGHT_PAD = 6

# The Stage and Content browsers share chevron assets from
# ``ovui_widgets/common/icons/``. Resolving the absolute path once at
# import via :mod:`importlib.resources` lines up with
# StageDelegate's constant-at-top-of-module pattern and keeps the
# build_branch hot-path free of filesystem joins. Wheel-safe because
# the icons are package data of ``ovui-widgets-common``.
_CHEVRON_ICON_DIR = str(
    importlib.resources.files("ovui_widgets.common").joinpath("icons")
)
_CHEVRON_RIGHT_PATH = f"{_CHEVRON_ICON_DIR}/chevron_right.png"
_CHEVRON_DOWN_PATH = f"{_CHEVRON_ICON_DIR}/chevron_down.png"

_DISABLED_VARIANT = "disabled"

# Step 36 — style-variant name applied to the Name cell's label when the
# row's URL is in the clipboard and the clipboard is in Cut mode. Paints
# via the ``Content.Row.Name::cut`` selector (see
# :mod:`ovui_widgets.content.style`) which dims the row to
# ``text_disabled``. Takes precedence over the ``disabled`` variant for
# a cut-but-readable row — a cut is a transient state the user needs
# feedback on, while readability is a permanent attribute; if the row
# is both cut and unreadable the cut variant reads "marked for move"
# which is the more important signal.
_CUT_VARIANT = "cut"

# Step 33: GLFW keycode for Escape — cancels an in-flight rename when
# pressed while the rename :class:`ui.StringField` has focus. Matches
# the value already used by :mod:`simple_input_dialog` and the
# ovui_widgets.stage :class:`StageDelegate` rename path.
_KEY_ESCAPE = 256

_COLUMN_HEADERS: Tuple[str, str, str] = ("Name", "Size", "Date")

_COLUMN_SORT_POLICIES: Dict[int, Tuple[str, str]] = {
    0: (FileBrowserSortPolicy.NAME_ASC, FileBrowserSortPolicy.NAME_DESC),
    1: (FileBrowserSortPolicy.SIZE_ASC, FileBrowserSortPolicy.SIZE_DESC),
    2: (FileBrowserSortPolicy.DATE_ASC, FileBrowserSortPolicy.DATE_DESC),
}

# Resolved once at import — icon URLs never move at runtime.
_ARROW_UP_PATH = get_icon_path("content_arrow_up")
_ARROW_DOWN_PATH = get_icon_path("content_arrow_down")


# The standalone ovui build's ``ui.Image(source_url)`` path goes through
# stb_image and intermittently drops the draw on raster-decode retry;
# ``ui.ImageWithProvider`` with a cached ``RasterImageProvider`` is the
# reliable path. Identical duplicated pattern in ovui_widgets.stage.stage_icons
# and ovui_widgets.property.window — see review follow-up for a shared extractor.
_PROVIDER_CACHE: Dict[str, "ui.RasterImageProvider"] = {}


def _provider(path: str) -> "ui.RasterImageProvider":
    prov = _PROVIDER_CACHE.get(path)
    if prov is None:
        prov = ui.RasterImageProvider(path)
        _PROVIDER_CACHE[path] = prov
    return prov


def _render_branch_chevron(item: Any, level: Any, expanded: Any) -> None:
    """Render the expand/collapse chevron for a branch cell.

    Mirrors :func:`ovui_widgets.stage.widget.stage_delegate.StageDelegate.build_branch`
    exactly so Stage and Content rows read identically when docked
    side-by-side: a 12-px chevron PNG centred in a 14-px VStack with
    Spacers above and below, right-pointing when collapsed and
    down-pointing when expanded. Non-folder rows get a bare Spacer of
    the same indent width so Name cells still align across leaf/folder
    siblings.
    """
    lvl = int(level) if level is not None else 0
    has_children = isinstance(item, FileItem) and item.is_folder
    total_w = _INDENT_PER_LEVEL * (lvl + 1)

    with ui.HStack(width=total_w, height=_ROW_HEIGHT):
        if lvl > 0:
            ui.Spacer(width=_INDENT_PER_LEVEL * lvl)
        if has_children:
            chevron_path = (
                _CHEVRON_DOWN_PATH if bool(expanded) else _CHEVRON_RIGHT_PATH
            )
            with ui.VStack(width=_INDENT_PER_LEVEL):
                ui.Spacer()
                ui.ImageWithProvider(
                    _provider(chevron_path),
                    width=_CHEVRON_SIZE,
                    height=_CHEVRON_SIZE,
                    style_type_name_override="Content.BranchGlyph",
                )
                ui.Spacer()
        else:
            ui.Spacer(width=_INDENT_PER_LEVEL)


def _build_name_rename_field(
    controller: "RenameController", item: FileItem,
) -> None:
    """Render an inline :class:`ui.StringField` seeded with ``item.name``.

    Step 33 / the content browser behavior Shared between
    :class:`FileBrowserDelegate` and :class:`TreeFolderDelegate` so the
    detail pane and the tree pane produce identical rename UX. The row
    carries the same ``Spacer(2) | icon(16) | Spacer(4)`` prefix as the
    non-rename branch so the field lines up with where the label was;
    the user's eye does not jump when the mode flips.

    Keybindings:

    * **Enter / end-edit** → :meth:`RenameController.commit_rename`
      with the current field value. omni.ui's
      :meth:`ui.StringField.model.add_end_edit_fn` fires for Enter AND
      for focus loss, so a click outside the field commits the rename
      rather than dropping the user's input silently.
    * **Escape** → :meth:`RenameController.cancel_rename`.
    """
    icon_path = get_icon_path(item.icon_key)
    with ui.HStack(height=_ROW_HEIGHT):
        ui.Spacer(width=2)
        with ui.VStack(width=_FILE_ICON_SIZE):
            ui.Spacer()
            ui.ImageWithProvider(
                _provider(icon_path),
                width=_FILE_ICON_SIZE,
                height=_FILE_ICON_SIZE,
                style_type_name_override="Content.FileIcon",
            )
            ui.Spacer()
        ui.Spacer(width=4)
        field = ui.StringField(
            style_type_name_override="Content.RenameField",
        )
        field.model.set_value(item.name)
        # Default-arg binding pins ``controller`` / ``field`` to these
        # exact instances so a later rename on a fresh field routes to
        # its own controller rather than the most-recently-bound one.
        field.model.add_end_edit_fn(
            lambda m, ctrl=controller: ctrl.commit_rename(
                m.get_value_as_string(),
            ),
        )
        field.set_key_pressed_fn(
            lambda key, mod, pressed, ctrl=controller:
            ctrl.cancel_rename() if (pressed and key == _KEY_ESCAPE)
            else None,
        )
        ui.Spacer()


class FileBrowserDelegate(ui.AbstractItemDelegate):
    """Name / Size / Date column renderer for :class:`FileBrowserModel`.

    The delegate is model-agnostic at construction; the hosting widget
    calls :meth:`set_model` once the tree view is built so header
    clicks can reach the right ``set_sort_policy`` target. Until that
    call lands, header clicks are a silent no-op.
    """

    def __init__(self) -> None:
        super().__init__()
        self._model: Optional[FileBrowserModel] = None
        # Step 31: right-click handler injected by the widget. ``None``
        # until :meth:`set_on_right_click` is called; delegate-built
        # rows mount their :meth:`set_mouse_pressed_fn` against this
        # slot so a widget without a context menu still renders rows
        # that respond to left-clicks as before.
        self._on_right_click: Optional[
            Callable[[float, float, FileItem], None]
        ] = None
        # Step 33: rename controller reference. ``None`` until the
        # widget calls :meth:`set_rename_controller`; the name-cell
        # builder consults it to decide between Label and StringField
        # rendering. Held as a weak-attribute (the controller is owned
        # by the widget; dropping our ref here does not affect its
        # lifecycle).
        self._rename_controller: Optional["RenameController"] = None
        # Step 41: drop-indicator coordinator. ``None`` until the
        # widget calls :meth:`set_drop_indicator`. Delegates use the
        # controller to tint a row on drag-over / clear on drag-leave.
        # The reference is weak-semantics (owned by the widget); the
        # delegate only mutates controller state, never lifecycle.
        self._drop_indicator: Optional["DropIndicator"] = None

    def set_model(self, model: Optional[FileBrowserModel]) -> None:
        """Bind the model whose sort policy the header toggles."""
        self._model = model

    def set_drop_indicator(
        self, indicator: Optional["DropIndicator"],
    ) -> None:
        """Inject the widget's :class:`DropIndicator` (Step 41).

        Invoked by :class:`FileBrowserWidget` after the controller is
        constructed so the delegate's row-build path can call
        :meth:`DropIndicator.show_row_highlight` during a drag-over.
        Passing ``None`` detaches the indicator — used by
        :meth:`FileBrowserWidget.destroy` to drop the reference before
        the controller / widget refs are nulled.
        """
        self._drop_indicator = indicator

    def set_rename_controller(
        self, controller: Optional["RenameController"],
    ) -> None:
        """Inject the widget's :class:`RenameController`.

        Step 33. Invoked by :class:`FileBrowserWidget` after the
        controller is constructed so the delegate's name-cell builder
        can branch between the default Label and the inline
        :class:`ui.StringField` when an item is being renamed. Passing
        ``None`` detaches the controller — used by
        :meth:`FileBrowserWidget.destroy` to drop the reference before
        the controller / widget refs are nulled.
        """
        self._rename_controller = controller

    def set_on_right_click(
        self,
        handler: Optional[Callable[[float, float, FileItem], None]],
    ) -> None:
        """Inject the widget's right-click handler for delegate rows.

        Called by :class:`FileBrowserWidget` after constructing its
        :class:`FileContextMenu` so every row the delegate builds
        mounts a :meth:`set_mouse_pressed_fn` that routes the
        right-button press back through the widget. Passing ``None``
        detaches the handler — used by :meth:`FileBrowserWidget.destroy`
        to drop the bound-method reference before the model / widget
        refs are nulled.
        """
        self._on_right_click = handler

    # ── Header ────────────────────────────────────────────────────────────

    def build_header(self, column_id: Any) -> None:
        if not self._is_builtin_column(column_id):
            return

        header_text = _COLUMN_HEADERS[column_id]
        arrow_path = self._sort_arrow_path_for(column_id)

        with ui.ZStack(height=_HEADER_HEIGHT):
            ui.Button(
                "",
                clicked_fn=lambda cid=column_id: self._on_header_clicked(cid),
                style_type_name_override="Content.ColumnHeader.ClickArea",
            )
            with ui.HStack():
                ui.Spacer(width=4)
                ui.Label(
                    header_text,
                    style_type_name_override="Content.ColumnHeader",
                    alignment=ui.Alignment.LEFT_CENTER,
                )
                ui.Spacer()
                if arrow_path is not None:
                    with ui.VStack(width=_SORT_ARROW_SIZE + 2):
                        ui.Spacer()
                        ui.ImageWithProvider(
                            _provider(arrow_path),
                            width=_SORT_ARROW_SIZE,
                            height=_SORT_ARROW_SIZE,
                            style_type_name_override="Content.SortArrow",
                        )
                        ui.Spacer()
                ui.Spacer(width=_COLUMN_RIGHT_PAD)

    # ── Branch ────────────────────────────────────────────────────────────

    def build_branch(
        self,
        model: Any,
        item: Any,
        column_id: Any,
        level: Any,
        expanded: Any,
    ) -> None:
        if column_id != 0:
            return
        _render_branch_chevron(item, level, expanded)

    # ── Body ──────────────────────────────────────────────────────────────

    def build_widget(
        self,
        model: Any,
        item: Any,
        column_id: Any,
        level: Any,
        expanded: Any,
    ) -> None:
        if item is None or not isinstance(item, FileItem):
            return
        readable = self._is_readable(item)
        if column_id == 0:
            self._build_name_cell(model, item, readable)
        elif column_id == 1:
            self._build_size_cell(model, item, readable)
        elif column_id == 2:
            self._build_date_cell(model, item, readable)
        else:
            self._build_plugin_cell(item, column_id)

    # ── Plug-in column dispatch (Step 30) ─────────────────────────────────
    @staticmethod
    def _build_plugin_cell(item: FileItem, column_id: Any) -> None:
        """Dispatch ``column_id`` past the built-ins to the registry.

        ``column_id`` is offset by :attr:`FileBrowserModel.BUILTIN_COLUMN_COUNT`
        into the registry's registration-order name list (Step 30 /
        the content browser behavior — "plug-in columns start at
        ``column_id >= builtin_count``"). A missing registration renders
        nothing so a registry that drained mid-render does not leave a
        half-drawn cell behind.

        A fresh delegate instance is constructed per cell — see
        :mod:`ovui_widgets.content.widget.column_delegate` for why
        v1 does not cache instances per view.
        """
        if not isinstance(column_id, int):
            return
        plugin_index = column_id - FileBrowserModel.BUILTIN_COLUMN_COUNT
        if plugin_index < 0:
            return
        names = ColumnDelegateRegistry.instance().get_registered_names()
        if plugin_index >= len(names):
            return
        delegate_class = ColumnDelegateRegistry.instance().get_delegate_class(
            names[plugin_index]
        )
        if delegate_class is None:
            return
        delegate_class().build_widget(item)

    def _build_name_cell(
        self, model: Any, item: FileItem, readable: bool,
    ) -> None:
        # Step 33: short-circuit the default Label / HighlightLabel
        # rendering when the controller flags this item as actively
        # being renamed. The field replaces the label in-place so row
        # alignment (icon + spacers) stays identical between display
        # and edit modes.
        if (
            self._rename_controller is not None
            and self._rename_controller.is_renaming(item)
        ):
            _build_name_rename_field(
                self._rename_controller, item,
            )
            return
        icon_path = get_icon_path(item.icon_key)
        value_model = model.get_item_value_model(item, 0)
        name_text = (
            value_model.as_string if value_model is not None else item.name
        )
        # Step 36: cut state takes precedence over disabled for the
        # Name cell's variant. See ``_CUT_VARIANT`` comment above.
        if clipboard.is_path_cut(item.url):
            variant = _CUT_VARIANT
        elif not readable:
            variant = _DISABLED_VARIANT
        else:
            variant = ""
        # Step 29: when the model carries a non-empty text filter, the
        # Name column paints a :class:`HighlightLabel` instead of a
        # plain :class:`ui.Label` so matching substrings glow yellow.
        # The filter string is read off the model directly because the
        # delegate already holds a ``set_model`` ref for sort-policy
        # cycling — no new wiring needed. Disabled rows keep the plain
        # label so the ``::disabled`` variant still dims the whole
        # name; the highlight would otherwise paint over the dim. Cut
        # rows also bypass the highlight for the same reason — the
        # ``::cut`` dim is the salient signal.
        search_term = ""
        if readable and variant != _CUT_VARIANT and self._model is not None:
            search_term = self._model.text_filter

        row = ui.HStack(height=_ROW_HEIGHT)
        self._wire_row_right_click(row, item)
        with row:
            ui.Spacer(width=2)
            # VStack + Spacer top/bottom keeps the 16-px icon centred on
            # the 22-px row (matches StageDelegate's type-icon pattern).
            with ui.VStack(width=_FILE_ICON_SIZE):
                ui.Spacer()
                ui.ImageWithProvider(
                    _provider(icon_path),
                    width=_FILE_ICON_SIZE,
                    height=_FILE_ICON_SIZE,
                    style_type_name_override="Content.FileIcon",
                )
                ui.Spacer()
            ui.Spacer(width=4)
            if search_term:
                HighlightLabel(
                    text=name_text,
                    search_term=search_term,
                    height=_ROW_HEIGHT,
                    alignment=ui.Alignment.LEFT_CENTER,
                )
            else:
                ui.Label(
                    name_text,
                    style_type_name_override="Content.Row.Name",
                    name=variant,
                    alignment=ui.Alignment.LEFT_CENTER,
                )
                ui.Spacer()

    def _build_size_cell(
        self, model: Any, item: FileItem, readable: bool,
    ) -> None:
        # Folders render blank (FileItem.size_model already returns "").
        # Short-circuiting here avoids allocating the value model at all.
        if item.is_folder:
            size_text = ""
        else:
            value_model = model.get_item_value_model(item, 1)
            size_text = (
                value_model.as_string if value_model is not None else ""
            )
        self._build_right_aligned_cell(
            size_text, "Content.Row.Size", readable, item=item,
        )

    def _build_date_cell(
        self, model: Any, item: FileItem, readable: bool,
    ) -> None:
        value_model = model.get_item_value_model(item, 2)
        date_text = (
            value_model.as_string if value_model is not None else ""
        )
        self._build_right_aligned_cell(
            date_text, "Content.Row.Date", readable, item=item,
        )

    def _build_right_aligned_cell(
        self,
        text: str,
        style_type: str,
        readable: bool,
        item: Optional[FileItem] = None,
    ) -> None:
        variant = "" if readable else _DISABLED_VARIANT
        row = ui.HStack(height=_ROW_HEIGHT)
        if item is not None:
            self._wire_row_right_click(row, item)
        with row:
            ui.Spacer()
            ui.Label(
                text,
                style_type_name_override=style_type,
                name=variant,
                alignment=ui.Alignment.RIGHT_CENTER,
            )
            ui.Spacer(width=_COLUMN_RIGHT_PAD)

    def _wire_row_right_click(self, widget: Any, item: FileItem) -> None:
        """Mount the row's right-button press → widget handler.

        Step 31 / the content browser behavior ``widget`` is the
        cell's outer :class:`ui.HStack` — a hit target that catches
        mouse presses anywhere inside the cell. On ``button == 1`` the
        handler forwards the event ``(x, y)`` plus the item to
        :attr:`_on_right_click`; the caller pops the menu there.

        ovui's mouse-pressed callback already delivers ``(x, y)`` in
        the DPI-scaled-points coordinate system :meth:`ui.Menu.show_at`
        consumes (``Widget.cpp`` divides by ``dpiScale`` before
        dispatch; ``Menu.cpp`` multiplies back on show). Adding the
        widget's :attr:`screen_position_*` on top was the Bug 4 cause
        — the menu landed offset from the cursor. Forward the event
        coords verbatim.

        A missing handler slot (the widget hasn't injected one yet, or
        detached it during destroy) falls through silently so delegate
        rows still build cleanly in tests that don't wire the context
        menu.
        """

        def _on_pressed(
            x: Any, y: Any, button: Any, modifier: Any, it: FileItem = item,
        ) -> None:
            if int(button) != 1:
                return
            handler = self._on_right_click
            if handler is None:
                return
            handler(float(x), float(y), it)

        widget.set_mouse_pressed_fn(_on_pressed)

    # ── Header click ──────────────────────────────────────────────────────

    def _on_header_clicked(self, column_id: int) -> None:
        """Cycle ``column_id``'s sort policy on the bound model.

        Clicking the currently-ascending column flips to descending;
        any other click (including clicks on a different column)
        lands on this column's ASC policy — matches Kit's
        ``FileBrowserTreeView._on_column_clicked`` behaviour.
        """
        if self._model is None:
            return
        if not self._is_builtin_column(column_id):
            return
        asc_policy, desc_policy = _COLUMN_SORT_POLICIES[column_id]
        current = self._current_sort_policy()
        next_policy = desc_policy if current == asc_policy else asc_policy
        self._model.set_sort_policy(next_policy)

    def _sort_arrow_path_for(self, column_id: int) -> Optional[str]:
        current = self._current_sort_policy()
        if current is None:
            return None
        asc_policy, desc_policy = _COLUMN_SORT_POLICIES[column_id]
        if current == asc_policy:
            return _ARROW_UP_PATH
        if current == desc_policy:
            return _ARROW_DOWN_PATH
        return None

    def _current_sort_policy(self) -> Optional[str]:
        if self._model is None:
            return None
        return self._model.sort_policy

    @staticmethod
    def _is_builtin_column(column_id: Any) -> bool:
        return (
            isinstance(column_id, int)
            and 0 <= column_id < FileBrowserModel.BUILTIN_COLUMN_COUNT
        )

    @staticmethod
    def _is_readable(item: FileItem) -> bool:
        # ``is_readable`` lands on FileItem in a later backend-flag
        # plumbing step; defaulting to True keeps every existing row
        # rendering at full contrast until that flag exists.
        return bool(getattr(item, "is_readable", True))


class TreeFolderDelegate(ui.AbstractItemDelegate):
    """Single-column (Name only) delegate for the folder-tree pane.

    Step 13 splits :class:`FileBrowserWidget` into two panes: a folder
    hierarchy on the left and a three-column file detail on the right
    (the content browser behavior). The left pane renders folder
    names only — no Size, no Date, no header — so the hierarchy reads
    as a compact drill-down rather than a columnar table.

    The delegate reuses :class:`FileBrowserDelegate`'s icon cache /
    row geometry / branch glyph rendering via module-level helpers;
    only the cell set (name only) and the header (hidden) differ.
    Sort-policy cycling is irrelevant here — folders always sort by
    name — so there is no header click-area and no
    ``set_model`` sort-policy plumbing.
    """

    def __init__(self) -> None:
        super().__init__()
        self._model: Optional[FileBrowserModel] = None
        # Step 31: shared with :class:`FileBrowserDelegate` — the
        # widget injects its right-click handler here so tree-pane
        # rows open the same :class:`FileContextMenu` the detail pane
        # does. ``None`` means "no context menu wired"; the row builds
        # without a mouse-pressed subscription in that case.
        self._on_right_click: Optional[
            Callable[[float, float, FileItem], None]
        ] = None
        # Step 33: rename controller — shared surface with
        # :class:`FileBrowserDelegate`. The tree-pane rename field reuses
        # the same :func:`_build_name_rename_field` helper so tree and
        # detail panes produce pixel-identical rename UX.
        self._rename_controller: Optional["RenameController"] = None
        # Step 41: drop-indicator coordinator. Mirrors
        # :attr:`FileBrowserDelegate._drop_indicator` so the tree-pane
        # folder rows participate in the same drop-hover state as the
        # detail-pane rows.
        self._drop_indicator: Optional["DropIndicator"] = None

    def set_model(self, model: Optional[FileBrowserModel]) -> None:
        """Bind the model; stored for parity with :class:`FileBrowserDelegate`.

        The tree pane never cycles sort policy (folders are always
        name-ascending), so this setter is retained only so callers can
        use the two delegate classes interchangeably through a uniform
        ``set_model`` surface.
        """
        self._model = model

    def set_rename_controller(
        self, controller: Optional["RenameController"],
    ) -> None:
        """Inject the widget's :class:`RenameController` (Step 33)."""
        self._rename_controller = controller

    def set_drop_indicator(
        self, indicator: Optional["DropIndicator"],
    ) -> None:
        """Inject the widget's :class:`DropIndicator` (Step 41).

        Mirrors :meth:`FileBrowserDelegate.set_drop_indicator` so the
        tree and detail panes share one controller. The tree-pane
        folder rows route drag-over highlights through the same
        instance as the detail-pane rows and grid cards.
        """
        self._drop_indicator = indicator

    def set_on_right_click(
        self,
        handler: Optional[Callable[[float, float, FileItem], None]],
    ) -> None:
        """Inject the widget's right-click handler for tree-pane rows."""
        self._on_right_click = handler

    def build_header(self, column_id: Any) -> None:
        # No header — the tree pane's ``header_visible=False`` on the
        # owning TreeView already suppresses the header row, so this
        # method is never reached. Keeping it as an explicit no-op
        # matches :class:`FileBrowserDelegate`'s surface for tooling
        # that enumerates delegate methods.
        return

    def build_branch(
        self,
        model: Any,
        item: Any,
        column_id: Any,
        level: Any,
        expanded: Any,
    ) -> None:
        # Identical to FileBrowserDelegate.build_branch — tree-view
        # branch rendering is invariant across column count.
        if column_id != 0:
            return
        _render_branch_chevron(item, level, expanded)

    def build_widget(
        self,
        model: Any,
        item: Any,
        column_id: Any,
        level: Any,
        expanded: Any,
    ) -> None:
        if item is None or not isinstance(item, FileItem):
            return
        if column_id != 0:
            # Defensive: a single-column TreeView should never query
            # column_id >= 1, but guarding keeps the delegate safe if
            # the owning widget is ever re-parented to a multi-column
            # view.
            return
        # Step 33: route rename-mode items through the shared inline
        # StringField builder before the default label path. Applies to
        # folder-only tree rows — the rename surface is uniform across
        # the two delegates.
        if (
            self._rename_controller is not None
            and self._rename_controller.is_renaming(item)
        ):
            _build_name_rename_field(self._rename_controller, item)
            return
        readable = bool(getattr(item, "is_readable", True))
        icon_path = get_icon_path(item.icon_key)
        value_model = model.get_item_value_model(item, 0)
        name_text = (
            value_model.as_string if value_model is not None else item.name
        )
        # Step 36: cut state takes precedence over disabled — same
        # ordering as :meth:`FileBrowserDelegate._build_name_cell` so
        # the two delegates' Name column reads identically.
        if clipboard.is_path_cut(item.url):
            variant = _CUT_VARIANT
        elif not readable:
            variant = _DISABLED_VARIANT
        else:
            variant = ""

        row = ui.HStack(height=_ROW_HEIGHT)
        self._wire_row_right_click(row, item)
        # Step 41 — wire the row's drag-over highlight. Folders are
        # the only valid tree-pane drop targets; wiring the indicator
        # on non-folder rows would mean a file row tints on drag-over
        # even though the actual drop gets refused by the model.
        if item.is_folder:
            self._wire_row_drop_highlight(row, item)
        with row:
            ui.Spacer(width=2)
            with ui.VStack(width=_FILE_ICON_SIZE):
                ui.Spacer()
                ui.ImageWithProvider(
                    _provider(icon_path),
                    width=_FILE_ICON_SIZE,
                    height=_FILE_ICON_SIZE,
                    style_type_name_override="Content.FileIcon",
                )
                ui.Spacer()
            ui.Spacer(width=4)
            ui.Label(
                name_text,
                style_type_name_override="Content.Row.Name",
                name=variant,
                alignment=ui.Alignment.LEFT_CENTER,
            )
            ui.Spacer()

    def _wire_row_drop_highlight(self, widget: Any, item: FileItem) -> None:
        """Tint the tree row during a compatible drag-over (Step 41).

        Mounts a lightweight ``accept_drop_fn`` on the row's hit
        :class:`ui.HStack`. The row's TreeView already carries a
        widget-level ``set_drop_fn`` that runs the actual drop — the
        per-row handler is purely for visual feedback. Returns
        ``False`` unconditionally so ovui's drop dispatch keeps
        routing through the parent TreeView: returning ``True`` here
        would let the row consume the drop event and bypass the
        widget's ``_dispatch_drop`` path.

        The indicator is idempotent on repeat frames — ovui calls
        ``accept_drop_fn`` on every cursor-move so the highlight
        naturally follows the cursor, and entering a different row
        reverts the previous one because the controller permits at
        most one row at a time.
        """
        if not hasattr(widget, "set_accept_drop_fn"):
            return

        def _on_over(mime: str, w: Any = widget) -> bool:
            if not mime:
                return False
            if self._drop_indicator is None:
                return False
            self._drop_indicator.show_row_highlight(w)
            return False

        try:
            widget.set_accept_drop_fn(_on_over)
        except Exception:  # noqa: BLE001
            # ovui test builds may stub HStack without the drop
            # setters; absorb so row rendering stays clean.
            pass

    def _wire_row_right_click(self, widget: Any, item: FileItem) -> None:
        """Mirror :meth:`FileBrowserDelegate._wire_row_right_click` for tree rows.

        ovui's mouse-pressed callback delivers ``(x, y)`` in DPI-scaled
        points, which is the coordinate system :meth:`ui.Menu.show_at`
        consumes; forwarding those verbatim lands the menu at the
        cursor (Bug 4).
        """

        def _on_pressed(
            x: Any, y: Any, button: Any, modifier: Any, it: FileItem = item,
        ) -> None:
            if int(button) != 1:
                return
            handler = self._on_right_click
            if handler is None:
                return
            handler(float(x), float(y), it)

        widget.set_mouse_pressed_fn(_on_pressed)


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovui_widgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_PROVIDER_CACHE)
