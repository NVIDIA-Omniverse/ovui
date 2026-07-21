# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""NavigationModel — the content browser's left-pane nav tree.

See the content browser behavior and the content browser implementation step 42.

The navigation pane is structurally different from the tree and detail
panes: its roots are *collections* (Bookmarks / My Computer / Recent),
each of which enumerates its own children on demand. That contract
doesn't fit :class:`FileBrowserModel` — which assumes a single backend
URL root and recursive ``list_dir`` traversal — so the nav pane runs
on its own model.

Click semantics:

* **Collection root** (a :class:`CollectionItem`) — no detail-pane
  navigation. The user clicks to expand the collection; the detail
  pane keeps whatever it was showing.
* **Collection child** (a :class:`FileItem`) — activates the
  ``on_navigate`` callback with the child's URL. The hosting widget
  (:class:`FileBrowserWidget`) re-roots the detail pane at that URL.

Real enumeration for each collection lives in its own module under
:mod:`ovui_widgets.content.widget.collections`:

* :class:`MyComputerCollection` — ``collections/my_computer.py``
  (Step 43).
* :class:`BookmarksCollection` — ``collections/bookmarks.py`` (Step
  44). Manager-driven change fan-out lands on ``_item_changed``.
* :class:`RecentFilesCollection` — ``collections/recent.py`` (Step
  46). Settings-driven change fan-out lands on ``_item_changed``.
"""

from __future__ import annotations

import importlib.resources
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

import omni.ui as ui

from ovui_widgets.common.style.urls import get_icon_path
from ovui_widgets.content.widget.collections import CollectionItem
from ovui_widgets.content.widget.collections.bookmarks import (
    BookmarksCollection,
)
from ovui_widgets.content.widget.collections.my_computer import (
    MyComputerCollection,
)
from ovui_widgets.content.widget.collections.recent import (
    RecentFilesCollection,
)
from ovui_widgets.content.widget.file_item import FileItem

if TYPE_CHECKING:
    from ovui_widgets.common.recent_files import RecentFileList
    from ovui_widgets.common.settings import Settings
    from ovui_widgets.content.backends.backend_adapter import BackendAdapter
    from ovui_widgets.content.bookmarks import BookmarksManager


# ──────────────────────────────────────────────────────────────────────────────
# NavigationModel
# ──────────────────────────────────────────────────────────────────────────────


class NavigationModel(ui.AbstractItemModel):
    """Navigation-pane model — collections as virtual roots, FileItem children.

    The model holds a fixed list of :class:`CollectionItem` instances
    and dispatches tree queries through them:

    * ``get_item_children(None)`` → the collection roots in the order
      they were added.
    * ``get_item_children(CollectionItem)`` → the collection's
      :meth:`CollectionItem.get_children` output (always
      :class:`FileItem` instances).
    * ``get_item_children(FileItem)`` → the FileItem's existing
      children snapshot (empty on leaves; populated via
      :meth:`FileItem.populate` on folder children). The nav pane is
      a shallow drill-down — collection children rarely need deep
      expansion — so we populate lazily on demand without the
      :class:`FileBrowserModel`'s throttled-refresh or filter
      pipeline.

    Click semantics are exposed through :meth:`activate_item`:

    * :class:`CollectionItem` → no-op (the TreeView still expands /
      collapses the row; no detail-pane change).
    * :class:`FileItem` → fires the ``on_navigate`` callback with the
      item's URL so the hosting widget can re-root the detail pane.

    Single-column by design: the nav pane renders one Name column and
    :meth:`get_item_value_model_count` returns 1 so omni.ui allocates
    the pane's full width to that column.
    """

    def begin_edit(self, item: Any) -> None:
        """Terminate the Python virtual fallback for native model edits."""

    def end_edit(self, item: Any) -> None:
        """Terminate the Python virtual fallback for native model edits."""

    def __init__(
        self,
        backend: "BackendAdapter",
        bookmarks: Optional["BookmarksManager"] = None,
        recent_files: Optional["RecentFileList"] = None,
        settings: Optional["Settings"] = None,
        collections: Optional[List[CollectionItem]] = None,
    ) -> None:
        super().__init__()
        self._backend = backend
        if collections is not None:
            self._collections: List[CollectionItem] = list(collections)
        else:
            self._collections = [
                BookmarksCollection(manager=bookmarks),
                MyComputerCollection(),
                RecentFilesCollection(
                    recent_files=recent_files,
                    settings=settings,
                ),
            ]
        # Wire each collection's optional change hook so manager-driven
        # mutations emit ``_item_changed`` on the collection root. The
        # TreeView re-requests children on that event, so adding /
        # removing a bookmark (Step 44) or a recent file (Step 46)
        # repaints the nav pane without a full model rebuild.
        for collection in self._collections:
            setter = getattr(collection, "set_on_changed", None)
            if setter is None:
                continue
            setter(self._make_collection_changed_handler(collection))
        self._on_navigate: Optional[Callable[[str], None]] = None

    def _make_collection_changed_handler(
        self, collection: CollectionItem,
    ) -> Callable[[], None]:
        """Build the ``on_changed`` callback for ``collection``.

        Factored out so the closure captures ``collection`` by value
        (one handler per collection) rather than the loop variable —
        the plain ``lambda: self._item_changed(collection)`` in the
        constructor loop would all close over the last iteration's
        value. Each handler defers to the model's ``_item_changed``
        so a change notification does not depend on the collection
        knowing anything about ``ui.AbstractItemModel``.
        """

        def _handler() -> None:
            self._item_changed(collection)

        return _handler

    # ── AbstractItemModel API ─────────────────────────────────────────────────

    def get_item_children(
        self, item: Optional[ui.AbstractItem],
    ) -> List[ui.AbstractItem]:
        """Return the children of ``item`` (or the top-level collections).

        ``None`` / the virtual root → the collection list.
        :class:`CollectionItem` → :meth:`CollectionItem.get_children`
        (a fresh list each call, since stub collections return
        ``[]`` and real collections may recompute from live state like
        ``/proc/mounts``).
        :class:`FileItem` folder → its subfolder children, populating
        on demand. Collections hand back folder :class:`FileItem`
        instances with ``_populated=False`` and empty ``_children``,
        so the nav pane has to drive the backend ``list_dir`` itself
        or expansion beyond level 1 yields zero rows. The populate
        call is idempotent after success (:meth:`FileItem.populate`
        short-circuits on ``_populated``), so subsequent queries at
        the same depth are free. Files are filtered out — the nav
        pane is folder-only by contract; files belong in the detail
        pane. The folder-only filter applies recursively because it
        runs every time ``get_item_children`` is invoked on a
        :class:`FileItem`, at any depth.
        Non-:class:`FileItem` / leaves → empty list.
        """
        if item is None:
            return list(self._collections)
        if isinstance(item, CollectionItem):
            return list(item.get_children(self._backend))
        if isinstance(item, FileItem):
            if not item.is_folder:
                return []
            if not item.populated:
                item.populate(self._backend)
            return [c for c in item.children if c.is_folder]
        return []

    def can_item_have_children(self, item: ui.AbstractItem) -> bool:
        """Collections are always expandable; :class:`FileItem` branches
        on :attr:`FileItem.is_folder`; everything else is a leaf.

        The TreeView uses this for the expand-arrow branch without
        calling ``get_item_children`` — so it stays O(1) even for a
        collection that would enumerate a large list.
        """
        if isinstance(item, CollectionItem):
            return True
        if isinstance(item, FileItem):
            return item.is_folder
        return False

    def get_item_value_model_count(self, item: ui.AbstractItem) -> int:
        """Single Name column — nav pane is a compact drill-down."""
        return 1

    def get_item_value_model(
        self, item: ui.AbstractItem, column_id: int,
    ) -> Optional[ui.AbstractValueModel]:
        """Return the Name column's value model.

        Both :class:`CollectionItem` and :class:`FileItem` expose
        :meth:`get_name_model`; any other item type returns ``None``
        so the delegate renders an empty cell rather than crashing.
        """
        if column_id != 0:
            return None
        if isinstance(item, (CollectionItem, FileItem)):
            return item.get_name_model()
        return None

    # ── Click / activation ───────────────────────────────────────────────────

    def set_on_navigate(
        self, callback: Optional[Callable[[str], None]],
    ) -> None:
        """Install the callback fired by :meth:`activate_item` for
        :class:`FileItem` activation.

        ``None`` clears the callback. The model holds a single slot —
        the hosting widget is the one natural listener (it re-roots
        the detail pane). Multi-listener dispatch is not supported;
        callers that need it can fan out in their own callback.
        """
        self._on_navigate = callback

    def activate_item(self, item: Optional[ui.AbstractItem]) -> None:
        """Dispatch a user click on ``item``.

        * ``None`` — no-op (empty selection).
        * :class:`CollectionItem` — no-op; expand/collapse is handled
          by the TreeView's own branch-arrow path.
        * :class:`FileItem` — fire ``on_navigate`` with
          :attr:`FileItem.url` so the hosting widget re-roots the
          detail pane. Files (``is_folder=False``) are included — Step
          46's Recent collection has file children that the user can
          click to navigate into their parent folder; the actual
          file-open dispatch is the widget's job (Step 54), not the
          nav model's.
        """
        if item is None:
            return
        if isinstance(item, CollectionItem):
            return
        if isinstance(item, FileItem):
            callback = self._on_navigate
            if callback is not None:
                callback(item.url)

    # ── Introspection helpers for tests / widget wiring ──────────────────────

    @property
    def collections(self) -> List[CollectionItem]:
        """Return a shallow copy of the collection list.

        Exposed so :class:`FileBrowserWidget` / tests can iterate the
        nav roots without reaching into ``_collections`` directly. A
        copy (rather than the internal list) prevents accidental
        mutation — adding / removing collections at runtime is the job
        of explicit setters (to be added when a later step needs it).
        """
        return list(self._collections)

    def find_collection(
        self, identifier: str,
    ) -> Optional[CollectionItem]:
        """Return the collection whose :attr:`~CollectionItem.identifier`
        matches ``identifier``, or ``None`` if no such collection exists.
        """
        for collection in self._collections:
            if collection.identifier == identifier:
                return collection
        return None


# ──────────────────────────────────────────────────────────────────────────────
# NavigationDelegate — renders the nav tree (collection roots + file children)
# ──────────────────────────────────────────────────────────────────────────────

# Row geometry mirrors :class:`TreeFolderDelegate` (see
# :mod:`file_browser_delegate`) so collection roots and file children
# align pixel-identically with the rest of the content browser's rows
# when the nav pane sits next to the detail pane.
_ROW_HEIGHT = 22
_INDENT_PER_LEVEL = 14
_FILE_ICON_SIZE = 16
_CHEVRON_SIZE = 12

# Resolve once — the chevron images never move. Use
# :mod:`importlib.resources` so the path works both in the editable
# in-tree layout and in a built wheel of ``ovui-widgets-common``.
_CHEVRON_ICON_DIR = str(
    importlib.resources.files("ovui_widgets.common").joinpath("icons")
)
_CHEVRON_RIGHT_PATH = f"{_CHEVRON_ICON_DIR}/chevron_right.png"
_CHEVRON_DOWN_PATH = f"{_CHEVRON_ICON_DIR}/chevron_down.png"


_PROVIDER_CACHE: Dict[str, "ui.RasterImageProvider"] = {}


def _provider(path: str) -> "ui.RasterImageProvider":
    """Cache :class:`ui.RasterImageProvider` per icon path.

    omni.ui's ``ui.Image(source_url)`` goes through stb_image and
    intermittently drops the draw on raster-decode retry;
    :class:`ui.ImageWithProvider` with a cached provider is the reliable
    path. Duplicated from :mod:`file_browser_delegate` to keep this
    module self-contained — the caches do not share state but the
    per-icon cost is a single extra decode at first paint.
    """
    prov = _PROVIDER_CACHE.get(path)
    if prov is None:
        prov = ui.RasterImageProvider(path)
        _PROVIDER_CACHE[path] = prov
    return prov


class NavigationDelegate(ui.AbstractItemDelegate):
    """Single-column (Name only) delegate for :class:`NavigationModel`.

    Renders both :class:`CollectionItem` roots and their
    :class:`FileItem` children uniformly — icon + name — so the nav
    pane reads as a flat drill-down. Deliberately simpler than
    :class:`TreeFolderDelegate`: no rename support, no clipboard-cut
    variant, no drop-indicator wiring. Step 45 adds a single right-
    click hook used by :class:`FileBrowserWidget` to surface the
    "Remove Bookmark" menu on :class:`BookmarksCollection` child rows —
    every other row kind still consumes the right-click silently, so
    the nav pane remains a read-only dispatcher for everything except
    bookmark management.
    """

    def __init__(self) -> None:
        super().__init__()
        # Step 45 — optional right-click handler installed by
        # :class:`FileBrowserWidget`. ``None`` in every non-wired path
        # (tests that exercise the delegate standalone, pre-wire,
        # post-destroy); the mouse-pressed callback short-circuits in
        # that case so right-clicks are a visible no-op rather than a
        # crash on a dereferenced handler.
        self._on_right_click: Optional[
            Callable[[float, float, ui.AbstractItem], None]
        ] = None

    def set_on_right_click(
        self,
        handler: Optional[
            Callable[[float, float, ui.AbstractItem], None]
        ],
    ) -> None:
        """Install ``handler`` to receive right-click events on nav rows.

        ``handler(screen_x, screen_y, item)`` — ``item`` is the
        :class:`ui.AbstractItem` under the cursor (a
        :class:`CollectionItem` root or a :class:`FileItem` child).
        The handler is free to classify the item and pop a
        context-specific menu; the delegate does no filtering.

        ``None`` detaches the handler — used by
        :meth:`FileBrowserWidget.destroy` so a late mouse-pressed
        dispatch cannot reach a torn-down widget.
        """
        self._on_right_click = handler

    def build_header(self, column_id: Any) -> None:
        """No header — the nav pane's TreeView hides the header row."""
        return

    def build_branch(
        self,
        model: Any,
        item: Any,
        column_id: Any,
        level: Any,
        expanded: Any,
    ) -> None:
        """Draw the expand/collapse chevron for expandable items.

        Mirrors :func:`file_browser_delegate._render_branch_chevron`
        exactly so nav-pane branch glyphs line up with the detail
        pane's when both are rendered side-by-side.
        """
        if column_id != 0:
            return
        lvl = int(level) if level is not None else 0
        has_children = (
            isinstance(item, CollectionItem)
            or (isinstance(item, FileItem) and item.is_folder)
        )
        total_w = _INDENT_PER_LEVEL * (lvl + 1)

        with ui.ZStack(width=total_w, height=_ROW_HEIGHT):
            ui.Rectangle(
                width=total_w,
                height=_ROW_HEIGHT,
                style_type_name_override="Content.TreeView.BranchFill",
            )
            with ui.HStack(width=total_w, height=_ROW_HEIGHT):
                if lvl > 0:
                    ui.Spacer(width=_INDENT_PER_LEVEL * lvl)
                if has_children:
                    chevron_path = (
                        _CHEVRON_DOWN_PATH
                        if bool(expanded)
                        else _CHEVRON_RIGHT_PATH
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

    def build_widget(
        self,
        model: Any,
        item: Any,
        column_id: Any,
        level: Any,
        expanded: Any,
    ) -> None:
        """Render the Name column — icon + label for a collection or file.

        Collection roots are painted with the ``Content.Row.Name::collection``
        variant so the Step 42 screenshot (and future steps that want
        to visually separate the roots from their children) can theme
        them independently of the generic file-row name style. File
        children fall through to the default ``Content.Row.Name`` look
        so they read identically to the detail pane's rows. Step 46 —
        a :class:`RecentFileItem` whose ``is_missing`` flag is set is
        rendered via the ``Content.Row.Name::missing`` variant
        (grey) so stale recent entries read distinct from live ones.
        """
        if column_id != 0:
            return
        if not isinstance(item, (CollectionItem, FileItem)):
            return
        icon_path = get_icon_path(item.icon_key)
        value_model = model.get_item_value_model(item, 0)
        name_text = (
            value_model.as_string if value_model is not None else item.name
        )
        if isinstance(item, CollectionItem):
            variant = "collection"
        elif getattr(item, "is_missing", False):
            # Step 46 — :class:`RecentFileItem` that failed its backend
            # stat. ``getattr`` probe rather than ``isinstance`` keeps
            # the delegate module free of :class:`RecentFileItem`
            # imports and lets future item subclasses opt into the
            # same grey variant by exposing the flag.
            variant = "missing"
        else:
            variant = ""

        row = ui.HStack(height=_ROW_HEIGHT)
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
        # Step 45 — wire the row's right-button press. Binding the
        # handler at the outer :class:`ui.HStack` captures clicks
        # anywhere inside the row (icon, label, trailing flex) without
        # per-child wiring. The handler receives widget-local coords
        # + the item; the widget translates to screen coords and
        # dispatches a menu.
        self._wire_row_right_click(row, item)

    def _wire_row_right_click(
        self, widget: Any, item: ui.AbstractItem,
    ) -> None:
        """Mount a right-button mouse-pressed handler on ``widget``.

        Mirrors :meth:`FileBrowserDelegate._wire_row_right_click`
        (``button == 1`` is the right mouse button in ovui). Widget-
        local coords are offset by the widget's screen position before
        the handler fires, so the caller receives absolute coords
        compatible with :meth:`ui.Menu.show_at`.

        A missing handler (the widget did not install one, or detached
        it during destroy) falls through silently so delegate rows
        still build cleanly in tests that exercise the delegate in
        isolation.
        """

        def _on_pressed(
            x: Any, y: Any, button: Any, modifier: Any,
            it: ui.AbstractItem = item, w: Any = widget,
        ) -> None:
            if int(button) != 1:
                return
            handler = self._on_right_click
            if handler is None:
                return
            screen_x = float(x) + float(w.screen_position_x)
            screen_y = float(y) + float(w.screen_position_y)
            handler(screen_x, screen_y, it)

        widget.set_mouse_pressed_fn(_on_pressed)


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovui_widgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_PROVIDER_CACHE)
