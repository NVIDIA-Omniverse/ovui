# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FileBrowserWidget — two-pane nav+detail layout over the content model.

See the content browser behavior (two-model pattern), §13
(navigation collections), §24 (two-pane layout), plus the content browser implementation steps 13 / 14 / 42. Step 9 shipped the widget as a single-pane tree;
Step 13 split it into a folder-tree / file-detail pair; Step 42
replaces the folder-tree left pane with a navigation pane showing
top-level collections (Bookmarks, My Computer, Recent):

* **Left pane** — :class:`NavigationModel` rendered by
  :class:`NavigationDelegate` in a single-column ``ui.TreeView``.
  Roots are :class:`CollectionItem` instances; children are
  :class:`FileItem` entries the collection enumerates on demand.
  Clicking a collection child re-roots the detail pane; clicking a
  collection root expands/collapses but does not navigate.
* **Right pane** — file + folder detail, driven by a
  :class:`FileBrowserModel` with the full three-column
  :class:`FileBrowserDelegate` (Name / Size / Date).
* **Splitter** — a ``ui.Placer(draggable=True, drag_axis=ui.Axis.X)``
  between them, 4px wide, styled ``Content.Splitter``.

Step 14 wires the primary browsing loop:

* **Nav-child click → detail re-root.** Selecting a :class:`FileItem`
  under a collection fires :class:`NavigationModel`'s ``on_navigate``
  callback with the child's URL; the widget re-roots the detail pane.
* **Detail double-click → drill-in.** Double-clicking a folder in
  the detail pane re-roots the detail pane only; the nav pane stays
  on whatever collection the user last selected. Double-clicking a
  file is a no-op at this step; Step 54 will dispatch the file-open
  handler.

Selection is **not** published to the :class:`SelectionBus` — file
URLs are not prim paths (the content browser behavior).

Instantiate inside an active ovui build context — the constructor
builds the UI immediately into the surrounding ``with`` block::

    with ui.VStack():
        widget = FileBrowserWidget(backend, "file:///home/user")

Mirrors :class:`ovwidgets.stage.widget.StageWidget` in both lifecycle (no
window chrome; the caller owns the window) and the "construct in a
live build context" contract.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Set

import omni.ui as ui

from ovwidgets.common.asset_types import AssetCategory
from ovwidgets.common.error_reporter import ErrorReporter
from ovwidgets.content.backends.backend_adapter import (
    BackendAdapter,
    BackendFileFlags,
    BackendResult,
)
from ovwidgets.content.widget.bookmark_button import BookmarkButton
from ovwidgets.content.widget.browser_bar import BrowserBar
from ovwidgets.content.widget.context_menu import FileContextMenu
from ovwidgets.content.widget.drop_indicator import DropIndicator
from ovwidgets.content.widget.file_browser_delegate import (
    FileBrowserDelegate,
)
from ovwidgets.content.widget.file_browser_model import (
    FileBrowserModel,
    FileBrowserSortPolicy,
)
from ovwidgets.content.widget.file_grid_view import FileGridView
from ovwidgets.content.widget.file_item import FileItem
from ovwidgets.content.widget.filter_button import FilterButton
from ovwidgets.content.widget.navigation_model import (
    NavigationDelegate,
    NavigationModel,
)
from ovwidgets.content.widget.options_menu import OptionsButton
from ovwidgets.content.widget.rename_controller import RenameController
from ovwidgets.content.widget.search_field import SearchField
from ovwidgets.content.widget.zoom_bar import SCALE_MAP, ZoomBar

if TYPE_CHECKING:
    from ovwidgets.common.recent_files import RecentFileList
    from ovwidgets.common.settings import Settings
    from ovwidgets.content.bookmarks import BookmarksManager


# Detail-pane column split. 60/20/20 keeps Name dominant (file/folder
# names are the primary affordance) while Size and Date get equal
# slices. Mirrors Kit's non-single-column ratio (``[.75, .15, .1]``)
# widened for Size/Date so timestamps read cleanly at standard DPIs.
# See the content browser behavior
_DETAIL_COLUMN_WIDTHS = (
    ui.Fraction(0.6),
    ui.Fraction(0.2),
    ui.Fraction(0.2),
)

# Tree pane renders one column (Name) only.
_TREE_COLUMN_WIDTHS = (ui.Fraction(1.0),)

# Splitter visual width in pixels. 4px matches ovui's default dock
# separator thickness — wide enough to grab with a mouse, narrow
# enough to feel like a handle rather than a panel divider.
_SPLITTER_WIDTH = 4

# Initial tree-pane width in pixels. Sized so the default 800×400
# Content window gives the tree ~30% of the horizontal space (the
# the content browser implementation step 13 fraction). Step 57 will restore this from
# persistent settings.
_DEFAULT_TREE_PANE_WIDTH = 240

# Minimum tree-pane width during drag. Prevents the user from
# collapsing the pane past the icon + "A" label glyph width.
_MIN_PANE_WIDTH = 80

# Step 15: empty-state / error-overlay messages. Kept as module-level
# constants so the test module can import and assert against them
# verbatim rather than duplicating the strings (which would let them
# drift).
_EMPTY_FOLDER_MESSAGE = "This folder is empty"
_ACCESS_DENIED_MESSAGE = "Access denied — check permissions"
_NOT_FOUND_MESSAGE = "Folder no longer exists — refreshing..."

# File extensions the detail double-click treats as "open as a USD
# stage". Mirrors :attr:`ovwidgets.app.application.Application._USD_EXTENSIONS`
# — kept in sync manually because importing the Application class at
# module scope would drag the full application wiring into the widget's
# import path (and break the unit-test harness that stands the widget
# up without a running singleton).
_USD_EXTENSIONS = (".usd", ".usda", ".usdc", ".usdz")


def _to_open_path(url: str) -> str:
    """Strip the ``file://`` scheme from ``url`` for :func:`Usd.Stage.Open`.

    :func:`pxr.Usd.Stage.Open` does not accept a ``file://`` URL — it
    raises ``Failed to open layer @file://...@``. Local-filesystem
    backends (:class:`LocalFSBackend`) surface URLs as ``file://``
    strings, so the widget strips the scheme before handing the path to
    :meth:`Application.open_file`. Remote schemes (``omniverse://``,
    ``http://``, ...) are left untouched so the USD resolver handles
    them. Mirrors the Windows-aware strip in
    :func:`ovwidgets.content.widget.file_card._file_url_to_path`.
    """
    if not url.lower().startswith("file://"):
        return url
    path = url[len("file://"):]
    if (
        sys.platform == "win32"
        and len(path) >= 3
        and path[0] == "/"
        and path[2] == ":"
    ):
        path = path[1:]
    return path

# Vertical offset before the overlay's label, in pixels. Pushes the
# label below the detail-pane header so an error message does not
# collide with the "Name / Size / Date" row. The trailing
# ``ui.Spacer()`` below the button consumes the rest, vertically
# centring the label + button as a group slightly above the middle of
# the pane — matches the Stage Browser's empty-state placement.
_OVERLAY_TOP_SPACER = 48

# Retry button fixed size. 80×28 matches Content.ToolBar.Button's
# standard touch target and reads as a real affordance at default DPI.
_RETRY_BUTTON_WIDTH = 80
_RETRY_BUTTON_HEIGHT = 28

# Step 20: browser-bar row height. 34px = 32px content search bar height +
# 2px Content.ToolBar padding slack so the nav-button icon glyph has
# the same optical centring as the retry button inside the empty-state
# overlay. Setting an explicit height on the wrapping frame prevents
# the VStack from giving the toolbar row equal share with the pane
# HStack below (which would make the toolbar consume half the window).
_BROWSER_BAR_HEIGHT = 34

# Step 20: user-facing error message when ``_on_apply_path`` stat fails
# or the path exists but is not a folder. Kept as a module constant so
# the test module can import and assert against the string verbatim
# rather than duplicating the literal.
_FOLDER_NOT_FOUND_MESSAGE = "Folder not found"

# Step 24: zoom-bar row height. 22 px matches
# :data:`zoom_bar._BAR_HEIGHT`; kept as a local constant rather than
# importing the private value so the widget's layout is self-contained.
# The wrapping ``ui.HStack`` pins the row so the VStack above does not
# give the zoom bar equal share with the pane content.
_ZOOM_BAR_ROW_HEIGHT = 22

# Step 24: zoom-bar width. The zoom bar's internal HStack has a fixed
# 22-px button, a 36-px percent label, and 3-px spacing between the
# three children. The shorter travel reads closer to the compact
# reference chrome at the bottom-right of the detail pane.
_ZOOM_BAR_WIDTH = 220

# Step 28: toolbar gap between the :class:`BrowserBar` slot, the
# :class:`SearchField`, and the :class:`FilterButton`. 4 px matches the
# Stage Browser toolbar gutter and the internal 4-px spacing inside
# :class:`BrowserBar` so the whole row reads as a single strip without
# a visible seam at the BrowserBar/SearchField boundary.
_TOOLBAR_GAP = 4

# Step 28: SearchField fixed width in pixels. Wide enough to show a
# typical search substring plus the clear-X on its right (the field's
# own magnifier + padding consume ~28 px), narrow enough to let the
# :class:`BrowserBar`'s :class:`PathField` keep the remaining flex
# space for a long breadcrumb trail. 220 px lands between the
# "too-cramped" 160-px and "steals-path-space" 320-px extremes.
_SEARCH_FIELD_WIDTH = 220

# Step 28: asset categories surfaced in the :class:`FilterButton`
# dropdown. The six-category set mirrors architecture §25 (which in
# turn mirrors Kit's default content-browser filter options). Order
# matters — the dropdown renders items in this order. FOLDER is
# intentionally omitted because folders always pass the whitelist
# (see :meth:`FileBrowserModel.set_asset_type_whitelist`); TEXT /
# ARCHIVE / MODEL / UNKNOWN are deliberately not exposed because the
# Kit reference UI skips them too, and every toolbar toggle is a
# permanent piece of UI clutter that has to justify itself.
_FILTER_CATEGORIES: List[AssetCategory] = [
    AssetCategory.USD,
    AssetCategory.IMAGE,
    AssetCategory.MATERIAL,
    AssetCategory.SOUND,
    AssetCategory.SCRIPT,
    AssetCategory.VOLUME,
]

# Step 38 — GLFW modifier bit for Ctrl. Matches :mod:`ovwidgets.app.application`
# and :mod:`file_grid_view`. Internal drag-drop reads this at drop-time
# to branch move vs copy semantics (Ctrl-drop = copy, per
# the content browser behavior). Duplicated rather than imported
# so the widget stays decoupled from the :class:`Application` singleton
# for the constant lookup alone.
_MOD_CTRL = 2

# Step 56-57 — persistent :class:`Settings` keys for user-facing browser
# preferences. Values mirror the content browser implementation step 57 verbatim so the key
# namespace reads identically to ``ui.content.last_{open,save}_dir`` set
# by :mod:`file_importer` / :mod:`file_exporter` and to
# ``ui.content.bookmarks`` set by :mod:`bookmarks`.
SETTING_SHOW_GRID_VIEW = "ui.content.show_grid_view"
SETTING_GRID_VIEW_SCALE = "ui.content.grid_view_scale"
SETTING_SPLITTER = "ui.content.splitter"
SETTING_SHOW_HIDDEN = "ui.content.show_hidden"
SETTING_SORT_POLICY = "ui.content.sort_policy"
SETTING_SHOW_DETAIL_PANE = "ui.content.show_detail_pane"

# Default values — the content browser implementation step 57 spec. ``grid_view_scale=2`` maps
# to :data:`SCALE_MAP[2]` = 1.0 (100%). ``splitter=0.3`` matches the
# 240-of-800-pixel proportion Step 13 ships with
# (:data:`_DEFAULT_TREE_PANE_WIDTH` / :data:`_DEFAULT_TOTAL_WIDTH`).
_DEFAULT_GRID_VIEW_SCALE_INDEX = 1
_DEFAULT_SPLITTER_FRACTION = 0.3
_DEFAULT_SHOW_DETAIL_PANE = True

# Total widget width used to convert the splitter fraction to a pixel
# width when the widget hasn't been rendered yet. 800 matches the
# default :class:`ContentBrowserWindow` width so the first-paint
# splitter position matches the spec's 0.3 default regardless of how
# the window eventually resizes.
_DEFAULT_TOTAL_WIDTH = 800


class FileBrowserWidget:
    """Embeddable two-pane content browser (folder tree + file detail).

    Composes two :class:`FileBrowserModel` instances — one folder-only
    for the tree pane, one full-view for the detail pane — with
    their respective delegates in a horizontal layout separated by a
    draggable splitter. Both models share the same backend and start
    at the same root URL.

    The widget is *pure widget* — it does not own a window. Callers
    embed it in any ovui build context; window chrome (title bar,
    dock preferences, layout save/restore) is the window layer's job
    (Step 10 → :class:`ovwidgets.content.window.ContentBrowserWindow`).
    """

    def __init__(
        self,
        backend: BackendAdapter,
        root_url: str,
        bookmarks: Optional["BookmarksManager"] = None,
        recent_files: Optional["RecentFileList"] = None,
        settings: Optional["Settings"] = None,
        on_selection_changed: Optional[
            Callable[[List[FileItem]], None]
        ] = None,
        on_file_double_clicked: Optional[
            Callable[[FileItem], None]
        ] = None,
        open_file_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        # Step 11.4/13: explicit ``open_file_fn`` callback replaces
        # the pre-Step-11.4 lazy ``Application.instance().open_file(url)``
        # lookup in :meth:`_on_file_item_double_clicked`. The
        # callback receives a single ``str`` (the resolved on-disk
        # path, after :func:`_to_open_path` strips any ``file://``
        # prefix). When ``None`` (e.g., bare-test harness without an
        # Application), :meth:`_on_file_item_double_clicked` is a
        # silent no-op -- the user still sees the row click, just no
        # stage opens. ``open_file`` is intentionally NOT a member of
        # the Step 11.1 :class:`WidgetServices` Protocol; this is a
        # per-widget explicit callback per Plan Rev 2 §5.20.
        self._open_file_fn: Optional[Callable[[str], None]] = open_file_fn
        self._backend = backend
        # Step 51 — optional callbacks the enclosing :class:`FilePickerDialog`
        # wires to populate the :class:`FileBar` filename field on single-
        # click and fire Apply on a file double-click. Both are ``None``
        # when the widget is embedded in :class:`ContentBrowserWindow`
        # (which owns no filename field and treats double-click as an
        # open stub per Step 54's future USD dispatch). ``list[FileItem]``
        # is the full post-click selection (grid or tree — whichever view
        # is active) so the caller can branch on single / multi / folder.
        self._on_selection_changed: Optional[
            Callable[[List[FileItem]], None]
        ] = on_selection_changed
        self._on_file_double_clicked: Optional[
            Callable[[FileItem], None]
        ] = on_file_double_clicked
        # Step 45 — optional :class:`BookmarksManager`. Held as a plain
        # attribute (not a property) so the context menu can reach it
        # through the widget reference with a single ``getattr``. A
        # ``None`` manager is valid (tests that exercise the widget
        # without a persistent settings layer); the toolbar star + the
        # context-menu Add Bookmark surface a user-visible warning when
        # the click lands with no manager attached.
        self._bookmarks: Optional["BookmarksManager"] = bookmarks
        # Step 46 — optional :class:`RecentFileList` + :class:`Settings`
        # for the nav pane's Recent collection. The list is the in-memory
        # source of truth (:meth:`Application.open_file` writes to it
        # first); the :class:`Settings` subscription makes out-of-process
        # writes (settings-file reload, future "clear recent files"
        # action) repaint the nav pane. Both ``None`` is valid — the
        # Recent collection renders as an empty but present nav root.
        self._recent_files: Optional["RecentFileList"] = recent_files
        self._settings: Optional["Settings"] = settings

        # Step 42 — navigation model for the left pane (Bookmarks, My
        # Computer, Recent). Each collection enumerates its own children
        # on demand; clicking a child fires ``on_navigate`` which the
        # widget wires to re-root the detail model. The nav pane does
        # not track a "folder hierarchy" root — it is a fixed list of
        # virtual roots — so there is no shared-root invariant between
        # the two models.
        self._navigation_model = NavigationModel(
            backend,
            bookmarks=bookmarks,
            recent_files=recent_files,
            settings=settings,
        )
        self._navigation_model.set_on_navigate(self._navigate_to_url)

        # Detail-pane model (Step 13 right pane). Full view (files +
        # folders) rooted at the constructor URL.
        self._detail_model = FileBrowserModel(
            backend, root_url, folder_only=False,
        )

        self._navigation_delegate: Optional[NavigationDelegate] = (
            NavigationDelegate()
        )
        self._detail_delegate: Optional[FileBrowserDelegate] = (
            FileBrowserDelegate()
        )
        self._detail_delegate.set_model(self._detail_model)

        # Step 31 — right-click context menu. Wired into the detail
        # pane's delegate (and, later steps, the grid) so the file-row
        # context menu still fires. Step 45 also wires the nav pane's
        # delegate: a right-click on a :class:`BookmarksCollection`
        # child row opens a dedicated "Remove Bookmark" menu via
        # :meth:`FileContextMenu.show_bookmark_menu`.
        self._context_menu: Optional[FileContextMenu] = FileContextMenu(self)
        if self._detail_delegate is not None:
            self._detail_delegate.set_on_right_click(self._on_row_right_click)
        if self._navigation_delegate is not None:
            self._navigation_delegate.set_on_right_click(
                self._on_nav_right_click,
            )

        # Step 33 — inline rename. Controller coordinates the rename
        # state machine across the detail delegate and the grid view.
        # Built before :meth:`build` so the grid view (constructed inside
        # :meth:`_build_detail_pane`) can receive the controller
        # reference at its own construction time. The nav pane does not
        # support rename — collection roots aren't user-editable and
        # their :class:`FileItem` children represent already-named real
        # paths whose rename flows through the detail pane instead.
        self._rename_controller: Optional[RenameController] = (
            RenameController(self)
        )
        if self._detail_delegate is not None:
            self._detail_delegate.set_rename_controller(
                self._rename_controller,
            )

        # Step 41 — drop-indicator coordinator. Tracks visual feedback
        # during a drag (card drop-hover variant, between-rows line).
        # The nav pane does not participate in drag-drop in Step 42
        # (drops always target the detail pane / its cards), so the
        # indicator is threaded only to the detail delegate and the
        # grid view.
        self._drop_indicator: Optional[DropIndicator] = DropIndicator()
        if self._detail_delegate is not None:
            self._detail_delegate.set_drop_indicator(self._drop_indicator)

        # Step 10/13 — modifier-bit snapshot from the most recent key
        # event routed by :class:`ContentBrowserWindow._on_key_pressed`.
        # Replaces the pre-Step-10 ``Application.instance()
        # ._last_modifier_bits`` read in :meth:`_is_drag_copy`. The
        # widget tracks Ctrl-during-drag locally so the drop handler
        # (which has no modifier info on the event itself) can still
        # branch move-vs-copy from a fresh value. ``set_modifier_bits``
        # is the public seam that ContentBrowserWindow updates each
        # key event; tests can call it directly.
        self._modifier_bits: int = 0

        # Lazily-built widgets — populated by :meth:`build`.
        self._tree_tree_view: Optional[ui.TreeView] = None
        self._detail_tree_view: Optional[ui.TreeView] = None
        self._tree_frame: Optional[ui.Frame] = None
        self._detail_frame: Optional[ui.Frame] = None
        self._tree_scrolling_frame: Optional[ui.ScrollingFrame] = None
        self._detail_scrolling_frame: Optional[ui.ScrollingFrame] = None
        self._splitter: Optional[ui.Placer] = None
        # Step 20 — navigation bar above the two-pane split. Owned by
        # the widget so back / forward / apply-path / tree-click flows
        # all converge on the same :class:`VisitedHistory` cursor.
        self._browser_bar: Optional[BrowserBar] = None

        # Step 28 — search field + filter button, added to the toolbar
        # row to the right of the :class:`BrowserBar`. The search field
        # drives :meth:`FileBrowserModel.set_text_filter`; the filter
        # button drives :meth:`FileBrowserModel.set_asset_type_whitelist`.
        # Both filters land on the detail model only — the tree-pane
        # model stays unfiltered so the user can still navigate into
        # folders that contain only filtered-out leaves.
        self._search_field: Optional[SearchField] = None
        self._filter_button: Optional[FilterButton] = None

        # Step 45 — star bookmark button in the toolbar. Lives to the
        # right of the :class:`BrowserBar` and left of the
        # :class:`SearchField` so the three toolbar slots read as
        # Path | Star | Search | Filter. Icon flips between hollow
        # (``content_bookmark``) and filled (``content_bookmark_filled``)
        # based on whether the detail pane's current folder is
        # bookmarked. Built in :meth:`build`; ``None`` pre-build and
        # post-destroy.
        self._bookmark_button: Optional[BookmarkButton] = None

        # Step 56 — options gear button in the toolbar. Sits to the
        # right of the :class:`FilterButton` so the toolbar row reads
        # Path | Star | Search | Filter | Gear left-to-right. Surfaces
        # the three persistent prefs (show_hidden / show_detail_pane /
        # sort_policy) whose values Step 57 also round-trips through
        # :class:`Settings`. Built in :meth:`build`; ``None`` pre-build
        # and post-destroy.
        self._options_button: Optional[OptionsButton] = None

        # Step 24 — grid-view sibling of the detail TreeView. Lives
        # inside the detail pane's :class:`ui.ZStack`, visibility
        # toggled by the zoom bar. Wrapped in a dedicated
        # ``_detail_grid_frame`` so the widget can flip the grid's
        # visibility without reaching into :class:`FileGridView`'s
        # internal :class:`ui.ScrollingFrame`.
        self._detail_grid_view: Optional[FileGridView] = None
        self._detail_grid_frame: Optional[ui.Frame] = None

        # Step 24 — zoom-bar row at the bottom of the detail pane.
        # Drives :meth:`FileGridView.set_scale` on slider moves and
        # flips tree / grid visibility on toggle-button clicks.
        self._zoom_bar: Optional[ZoomBar] = None

        # Step 56-57 — read persistent prefs early so the
        # construction-time defaults we already apply to the detail
        # model / view-mode flag / splitter pixel width match whatever
        # the user left the last session in. Reads tolerate missing /
        # malformed values by falling through to the spec defaults.
        self._show_hidden: bool = bool(
            self._read_setting(SETTING_SHOW_HIDDEN, False)
        )
        stored_policy = self._read_setting(
            SETTING_SORT_POLICY, FileBrowserSortPolicy.NAME_ASC,
        )
        self._sort_policy: str = (
            stored_policy
            if isinstance(stored_policy, str)
            else FileBrowserSortPolicy.NAME_ASC
        )
        self._show_detail_pane: bool = bool(
            self._read_setting(
                SETTING_SHOW_DETAIL_PANE, _DEFAULT_SHOW_DETAIL_PANE,
            )
        )
        self._grid_view_scale_index: int = self._coerce_scale_index(
            self._read_setting(
                SETTING_GRID_VIEW_SCALE, _DEFAULT_GRID_VIEW_SCALE_INDEX,
            )
        )

        # Apply show_hidden / sort_policy to the detail model BEFORE
        # the first populate runs in :meth:`_update_empty_state`. A
        # later apply would trigger a redundant refresh of the same
        # root because :meth:`FileBrowserModel.set_show_hidden` /
        # :meth:`set_sort_policy` both dispatch item-changed.
        self._detail_model.set_show_hidden(self._show_hidden)
        self._detail_model.set_sort_policy(self._sort_policy)

        # Step 24 — current detail-pane view mode. ``True`` renders the
        # grid; ``False`` renders the tree. Step 57 seeds from
        # :data:`SETTING_SHOW_GRID_VIEW`; when the stored scale index
        # falls below the 0.75 grid threshold the grid flag follows so
        # the visibility swap applied after build matches the slider
        # position.
        stored_show_grid = self._read_setting(SETTING_SHOW_GRID_VIEW, True)
        self._is_grid_view: bool = bool(
            stored_show_grid
            if stored_show_grid is not None
            else True
        )

        # Splitter drag state. ``_tree_pane_width`` is the current
        # tree-frame width in pixels; ``_suppress_splitter_cb`` guards
        # against re-entry when the drag handler resets ``offset_x``
        # to zero to avoid compounding drags. Step 57 restores from
        # the :data:`SETTING_SPLITTER` fraction, clamped to the
        # minimum pane width so a hostile stored value cannot render
        # the nav pane unusable.
        splitter_fraction = self._read_splitter_fraction()
        self._tree_pane_width: int = max(
            _MIN_PANE_WIDTH,
            int(splitter_fraction * _DEFAULT_TOTAL_WIDTH),
        )
        self._suppress_splitter_cb: bool = False

        # Step 57 — suppress the bounce-back that a Settings read
        # would trigger when we write during :meth:`build` (the zoom
        # bar's slider callback fires ``on_scale`` at build time if
        # the stored index differs from the default). Set to True for
        # the duration of :meth:`build` + initial settings apply.
        self._suppress_persist: bool = False

        # Step 15 — detail-pane overlay slots (filled in :meth:`build`).
        # The overlay is a :class:`ui.VStack` layered over the detail
        # ``ScrollingFrame`` in a :class:`ui.ZStack`. It surfaces three
        # states: empty folder (OK + 0 children), access denied, and
        # not found. The retry button is part of the overlay but only
        # visible for ACCESS_DENIED — the "refreshing..." NOT_FOUND
        # path schedules a one-shot fallback to the parent URL instead.
        self._empty_state_container: Optional[ui.VStack] = None
        self._empty_state_label: Optional[ui.Label] = None
        self._empty_state_retry_button: Optional[ui.Button] = None

        # Subscription handle for ``_detail_model.subscribe_item_changed_fn``
        # → ``_on_detail_model_item_changed``. Held so the callback stays
        # wired until :meth:`destroy`; setting the attribute back to
        # ``None`` during destroy drops the only strong reference and
        # the subscription is released.
        self._detail_model_change_sub: Optional[Any] = None

        # Guard flag for the NOT_FOUND → parent-URL fallback. Set while
        # a ``call_later`` is in flight to prevent :meth:`_update_empty_state`
        # from scheduling duplicate fallbacks if it fires again before
        # the re-root completes.
        self._parent_fallback_scheduled: bool = False

        self._suppress_persist = True
        self.build()
        # Step 57 — apply stored view / scale / detail-pane state now
        # that the zoom-bar + detail-frame refs are populated. The
        # ``_suppress_persist`` latch keeps the zoom-bar's on_scale
        # / on_toggle_grid callbacks (fired by ``set_slider_index``)
        # from writing the same values back through to Settings —
        # which would be a harmless no-op per :meth:`Settings.set`'s
        # equality guard but churns every subscribed consumer.
        self._apply_restored_view_state()
        self._suppress_persist = False
        # Step 20 — seed the browser bar's path field + visited history
        # with the initial detail root so (a) the breadcrumb row shows
        # the starting folder on the first rendered frame and (b) the
        # very first navigation has a "back target" to return to.
        # Both models start at the same constructor root, so reading
        # the detail model's URL is equivalent to reading the tree
        # model's URL.
        if self._browser_bar is not None and self._detail_model is not None:
            self._browser_bar.set_path(self._detail_model.root_url)
        # Initial overlay evaluation. The models are freshly constructed
        # and unpopulated; this call drives the first populate on the
        # detail root and renders the empty-state label if the root
        # came up empty or errored on open.
        self._update_empty_state()

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build the widget UI into the current ovui build context.

        Step 20 wraps the Step 13 two-pane ``ui.HStack`` in an outer
        ``ui.VStack`` so the new navigation :class:`BrowserBar` row sits
        above the splitter. Layout:

        1. Fixed-height ``ui.Frame`` (=:data:`_BROWSER_BAR_HEIGHT`)
           wrapping a :class:`BrowserBar`. The explicit pixel height
           prevents the VStack from distributing vertical space evenly
           between the toolbar and the pane row (which would collapse
           the tree / detail panes).
        2. ``ui.HStack(spacing=0)`` — the Step 13 pane row with the
           same three children as before: tree-pane frame, draggable
           splitter, detail-pane frame.

        Both panes host their own ``ui.ScrollingFrame`` + ``ui.TreeView``
        so scroll state is per-pane.
        """
        with ui.VStack(spacing=0):
            # Step 20 — browser bar row. Constructed inside a fixed-
            # height frame so the VStack gives it exactly that many
            # pixels and the pane HStack below takes the rest.
            # Step 28 extends the row into a composite
            # ``HStack(BrowserBar | SearchField | FilterButton)`` so
            # navigation and filtering share one toolbar strip — the
            # :class:`BrowserBar` slot keeps the flex share so long
            # breadcrumb trails scale with the window width, while the
            # :class:`SearchField` and :class:`FilterButton` stay
            # anchored to the right at their fixed widths.
            with ui.Frame(height=ui.Pixel(_BROWSER_BAR_HEIGHT)):
                with ui.HStack(spacing=_TOOLBAR_GAP):
                    # BrowserBar inside a flex Frame so it consumes
                    # whatever horizontal space the fixed-width
                    # SearchField + FilterButton do not. The BrowserBar
                    # builds its own inner HStack; the wrapping Frame
                    # is just the slot that participates in the outer
                    # toolbar row.
                    with ui.Frame():
                        self._browser_bar = BrowserBar(
                            apply_path_handler=self._on_apply_path,
                            autocomplete_handler=self._path_autocomplete,
                            begin_edit_handler=self._on_begin_edit,
                        )
                    # Step 45 — bookmark star button. Self-sized via its
                    # internal :class:`ui.ZStack(width=28, height=28)`
                    # so no outer Frame is needed, same pattern as
                    # :class:`FilterButton`. Slot lands between the
                    # BrowserBar and the SearchField so the
                    # the content browser behavior row reads
                    # Path | Star | Search | Filter left-to-right.
                    self._bookmark_button = BookmarkButton(
                        manager=self._bookmarks,
                        backend=self._backend,
                        current_url=self._detail_model.root_url,
                    )
                    # SearchField wrapped in a fixed-width Frame so the
                    # outer HStack allocates it a stable slot rather
                    # than letting omni.ui decide its width from the
                    # inner :class:`ui.StringField`'s content. Keeping
                    # the search pill the same width as the user types
                    # is a UX stability concern — a field that resizes
                    # as characters are typed reads as visually noisy.
                    with ui.Frame(width=ui.Pixel(_SEARCH_FIELD_WIDTH)):
                        self._search_field = SearchField(
                            on_search=self._on_search_changed,
                        )
                    # FilterButton is a self-sized widget — its own
                    # :class:`ui.ZStack(width=28, height=28)` pins the
                    # slot width, so no outer Frame is needed. The
                    # button's funnel-icon reads as the natural right
                    # anchor of the toolbar row.
                    self._filter_button = FilterButton(
                        categories=_FILTER_CATEGORIES,
                        on_filter_changed=self._on_filter_changed,
                    )
                    # Step 56 — options gear button. Self-sized via its
                    # internal :class:`ui.ZStack(width=28, height=28)`
                    # (same pattern as :class:`FilterButton` +
                    # :class:`BookmarkButton`). Initial checkbox /
                    # radio state comes from the constructor-read
                    # settings so the dropdown reflects whatever the
                    # user left the last session in.
                    self._options_button = OptionsButton(
                        show_hidden=self._show_hidden,
                        show_detail_pane=self._show_detail_pane,
                        sort_policy=self._sort_policy,
                        on_show_hidden_changed=(
                            self._on_show_hidden_changed
                        ),
                        on_show_detail_pane_changed=(
                            self._on_show_detail_pane_changed
                        ),
                        on_sort_policy_changed=(
                            self._on_sort_policy_changed
                        ),
                    )

            with ui.HStack(spacing=0):
                self._tree_frame = ui.Frame(
                    width=ui.Pixel(self._tree_pane_width),
                )
                with self._tree_frame:
                    self._build_tree_pane()

                # Splitter. ``draggable=True`` + ``drag_axis=X``
                # restricts motion to the horizontal axis; the offset-
                # changed callback absorbs the drag into
                # ``_tree_pane_width`` and resets the placer to zero so
                # the next drag stroke also starts at zero (avoids
                # compounding).
                self._splitter = ui.Placer(
                    draggable=True,
                    drag_axis=ui.Axis.X,
                    width=ui.Pixel(_SPLITTER_WIDTH),
                )
                with self._splitter:
                    ui.Rectangle(
                        style_type_name_override="Content.Splitter",
                    )
                self._splitter.set_offset_x_changed_fn(
                    self._on_splitter_dragged,
                )

                # Right pane: no explicit width → takes remaining
                # space inside the HStack. Using ``ui.Frame()`` (no
                # width) is equivalent to ``ui.Fraction(1.0)`` in an
                # HStack slot.
                self._detail_frame = ui.Frame()
                with self._detail_frame:
                    self._build_detail_pane()

    def _build_tree_pane(self) -> None:
        """Build the navigation-pane scrolling frame + TreeView (Step 42).

        The left pane now renders collection roots (Bookmarks, My
        Computer, Recent) via :class:`NavigationModel` +
        :class:`NavigationDelegate`. The TreeView's header is hidden
        (the nav pane has no columns) and ``root_visible=False`` so
        ovui draws the collection roots as top-level rows rather than
        children of a single virtual ``None`` root.
        """
        self._tree_scrolling_frame = ui.ScrollingFrame(
            horizontal_scrollbar_policy=(
                ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED
            ),
            vertical_scrollbar_policy=(
                ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED
            ),
            style_type_name_override="Content.TreeView.ScrollingFrame",
        )
        with self._tree_scrolling_frame:
            self._tree_tree_view = ui.TreeView(
                self._navigation_model,
                delegate=self._navigation_delegate,
                root_visible=False,
                header_visible=False,
                column_widths=list(_TREE_COLUMN_WIDTHS),
                style_type_name_override="Content.TreeView",
            )
        # Step 42: a click in the nav pane dispatches through the
        # NavigationModel. Collection roots are no-op; FileItem
        # children fire ``on_navigate`` which routes into
        # :meth:`_navigate_to_url` (set in the constructor).
        self._tree_tree_view.set_selection_changed_fn(self._on_tree_selection)

    def _build_detail_pane(self) -> None:
        """Build the file-detail ZStack(tree, grid, overlay) + zoom-bar row.

        Step 15 introduced a shared :class:`ui.ZStack` holding the
        detail TreeView's scrolling frame plus an empty-state overlay
        (only one visible at a time). Step 24 extends that stack with
        a :class:`FileGridView` sibling and wraps the whole thing in a
        :class:`ui.VStack` so a :class:`ZoomBar` sits below — wired to
        flip between grid and list view, and to rescale the grid's
        cards.

        Layout::

            VStack(spacing=0)
            ├── ZStack
            │   ├── ScrollingFrame (TreeView, list view)
            │   ├── Frame (FileGridView, grid view)
            │   └── VStack (empty-state overlay)
            └── HStack(height=24)
                ├── Spacer
                └── Frame(width=280)
                    └── ZoomBar

        Initial visibility: grid view shown, tree view hidden (matches
        :attr:`_is_grid_view` default — architecture §25.4 says scale
        ≥ 0.75 renders grid, and the zoom bar defaults to scale 1.0).

        The overlay's ``_hide()`` path reads :attr:`_is_grid_view` to
        restore the correct view; ``_show()`` hides both the tree and
        grid so the overlay paints cleanly.
        """
        with ui.VStack(spacing=0):
            with ui.ZStack():
                self._detail_scrolling_frame = ui.ScrollingFrame(
                    horizontal_scrollbar_policy=(
                        ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED
                    ),
                    vertical_scrollbar_policy=(
                        ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED
                    ),
                    style_type_name_override="Content.ScrollingFrame",
                )
                with self._detail_scrolling_frame:
                    self._detail_tree_view = ui.TreeView(
                        self._detail_model,
                        delegate=self._detail_delegate,
                        root_visible=True,
                        header_visible=True,
                        column_widths=list(_DETAIL_COLUMN_WIDTHS),
                        drop_between_items=True,
                    )
                # Step 24 — grid view wrapped in a frame so the widget
                # can flip its visibility via ``_detail_grid_frame.visible``
                # rather than reaching into :class:`FileGridView`'s
                # internal ``_scrolling_frame``.
                self._detail_grid_frame = ui.Frame()
                with self._detail_grid_frame:
                    self._detail_grid_view = FileGridView(
                        self._detail_model,
                        on_click=self._on_grid_click,
                        on_double_click=self._on_grid_double_click,
                        on_right_click=self._on_grid_right_click,
                        on_empty_right_click=self._on_grid_empty_right_click,
                        on_card_drag=self._detail_drag_payload,
                        on_card_drop=self._on_card_drop,
                        drop_indicator=self._drop_indicator,
                    )
                # Step 33: hand the rename controller to the grid so
                # cards constructed in :meth:`FileGridView._build_card_in_frame`
                # receive it. Done after grid construction because the
                # controller is widget-owned and has to exist before
                # any card builds — the card captures the reference at
                # construction rather than re-reading it per build.
                if self._rename_controller is not None:
                    self._detail_grid_view.set_rename_controller(
                        self._rename_controller,
                    )
                self._build_empty_state_overlay()

            # Step 24 — zoom-bar row. A left Spacer pushes the bar to
            # the right; the bar itself is wrapped in a fixed-width
            # Frame so the slider + label + button read tight rather
            # than stretching across the full pane width. The row's
            # explicit height pins it at the zoom-bar row height so the ZStack above
            # takes all remaining vertical space.
            with ui.HStack(height=ui.Pixel(_ZOOM_BAR_ROW_HEIGHT)):
                ui.Spacer()
                with ui.Frame(width=ui.Pixel(_ZOOM_BAR_WIDTH)):
                    self._zoom_bar = ZoomBar(
                        on_scale=self._on_zoom_bar_scale,
                        on_toggle_grid=self._on_zoom_bar_toggle_grid,
                    )

        # Step 24 / 57 — flip default visibility to match the restored
        # view mode. Pre-Step-57 this hardcoded the grid view on at
        # build time; Step 57 reads the persisted value first so the
        # initial frame matches whatever the user left the last
        # session in.
        if self._detail_scrolling_frame is not None:
            self._detail_scrolling_frame.visible = not self._is_grid_view
        if self._detail_grid_frame is not None:
            self._detail_grid_frame.visible = self._is_grid_view

        # Step 14: double-click on a folder in the detail pane drills
        # into it (re-roots both panes + mirrors the selection in the
        # tree pane). Double-click on a file is stubbed until Step 54
        # wires the USD-open handler.
        self._detail_tree_view.set_mouse_double_clicked_fn(
            self._on_detail_double_click,
        )
        # Step 51 — detail-pane selection change fans out to the
        # ``on_selection_changed`` callback so the enclosing
        # :class:`FilePickerDialog` can populate its :class:`FileBar`
        # filename field. List view only; the grid view reports its
        # selection through :meth:`_on_grid_click` instead.
        self._detail_tree_view.set_selection_changed_fn(
            self._on_detail_tree_selection,
        )
        # Step 38 — drop targets on the detail list-view TreeView.
        #
        # Bug 2 — the Step-38 design also wired
        # ``set_drag_fn(self._detail_drag_payload)`` on the TreeView to
        # source drags from list-view rows. That call routed through
        # ovui's Widget-level drag machinery (``Widget::_performDrag``
        # in ``Widget.cpp`` line 543-550) which registers an
        # ``ImGui::InvisibleButton`` the size of the full tree
        # rectangle on every draw whenever ``hasDragFn()`` is true.
        # That button absorbed *every* left-button press before the
        # TreeView's own per-row selection / expand-chevron
        # ``InvisibleButton``s could see it, so zoom-0 list-view rows
        # silently failed to select and chevrons silently failed to
        # toggle. Right-clicks still worked because they route
        # through the row delegate's per-cell ``set_mouse_pressed_fn``,
        # which registers its hit regions inside each row — inside
        # the absorbing InvisibleButton's area but ordered earlier in
        # the ImGui stream. Dropping ``set_drag_fn`` here lifts the
        # overlay and clicks land on the TreeView's per-row buttons
        # as they always did in the grid view. Drag-source support
        # from list-view rows regresses to "not supported" — the grid
        # view's per-card :meth:`FileCard._dispatch_drop` path still
        # sources drags, and users typically drag from the grid
        # anyway (the thumbnails are the affordance). List-view drag
        # source can come back via an override of
        # :meth:`FileBrowserModel.get_drag_mime_data` (TreeView-
        # internal drag at TreeView.cpp:1686-1704, which does not
        # install the full-rectangle InvisibleButton) in a follow-up
        # step once the drop-side parser is taught to read the
        # pointer-packed payload ovui builds from that path.
        self._detail_tree_view.set_accept_drop_fn(self._accept_drop_mime)
        self._detail_tree_view.set_drop_fn(self._on_detail_drop)
        # Step 38 — empty-space drops in the detail pane land on the
        # ScrollingFrame around the TreeView and on the Frame that
        # wraps the FileGridView. Both route into the same handler so
        # "drop below the last row" / "drop into the grid gap" both
        # mean "drop into the current detail root". The grid-view side
        # targets the outer :attr:`_detail_grid_frame` rather than the
        # inner :class:`FileGridView`'s ScrollingFrame so the outer
        # widget-owned Frame (which the widget can always reach post-
        # build) takes the drop regardless of card tile hit-testing.
        if self._detail_scrolling_frame is not None:
            self._detail_scrolling_frame.set_accept_drop_fn(
                self._accept_drop_mime,
            )
            self._detail_scrolling_frame.set_drop_fn(
                self._on_detail_empty_drop,
            )
        if self._detail_grid_frame is not None:
            self._detail_grid_frame.set_accept_drop_fn(
                self._accept_drop_mime,
            )
            self._detail_grid_frame.set_drop_fn(
                self._on_detail_empty_drop,
            )
        # Step 15: subscribe to the detail model's ``item_changed``
        # dispatch so a re-root / refresh / external update re-runs
        # the overlay evaluation. The subscription handle is held as
        # an instance attribute so the model keeps firing callbacks
        # until :meth:`destroy` drops it.
        self._detail_model_change_sub = (
            self._detail_model.subscribe_item_changed_fn(
                self._on_detail_model_item_changed,
            )
        )

    def _build_empty_state_overlay(self) -> None:
        """Build the hidden overlay VStack (label + optional retry button).

        Layout mirrors ``ovwidgets.stage.StageWidget._empty_state_container``
        (stage_widget.py lines 188–196) with a retry button added for
        the ACCESS_DENIED case: top spacer → centred label → small
        gap → retry-button row (button-visibility is toggled per
        state) → trailing flex spacer. The container starts hidden;
        :meth:`_update_empty_state` shows it (and hides the sibling
        ScrollingFrame) when the detail pane has no populated
        children or the backend returned an error. Initial label text
        is the empty-folder message so omni.ui measures a real glyph
        run during the build pass; subsequent ``label.text``
        assignments replace the string without needing another layout
        round-trip.
        """
        self._empty_state_container = ui.VStack(visible=False)
        with self._empty_state_container:
            ui.Spacer(height=_OVERLAY_TOP_SPACER)
            self._empty_state_label = ui.Label(
                _EMPTY_FOLDER_MESSAGE,
                style_type_name_override="Content.EmptyState",
                alignment=ui.Alignment.CENTER_TOP,
            )
            ui.Spacer(height=12)
            # Retry button inside an HStack so flanking Spacers centre
            # it horizontally. A plain ``ui.Button`` in a VStack would
            # stretch to the full pane width, reading as a banner
            # rather than an affordance.
            with ui.HStack(height=_RETRY_BUTTON_HEIGHT):
                ui.Spacer()
                self._empty_state_retry_button = ui.Button(
                    "Retry",
                    width=_RETRY_BUTTON_WIDTH,
                    height=_RETRY_BUTTON_HEIGHT,
                    visible=False,
                    clicked_fn=self._on_retry_clicked,
                )
                ui.Spacer()
            ui.Spacer()

    # ── Settings helpers (Step 57) ───────────────────────────────────────────

    def _read_setting(self, key: str, default: Any) -> Any:
        """Read a setting value with a safe fallback.

        Returns ``default`` when no :class:`Settings` was wired or the
        store raises. The ``getattr`` + ``callable`` check lets tests
        pass a mock or a plain dict that only implements a subset of
        the real :class:`Settings` surface.
        """
        if self._settings is None:
            return default
        getter = getattr(self._settings, "get", None)
        if not callable(getter):
            return default
        try:
            return getter(key, default)
        except Exception:  # noqa: BLE001
            return default

    def _write_setting(self, key: str, value: Any) -> None:
        """Persist a setting value; swallow failures so the UI survives."""
        if self._suppress_persist:
            return
        if self._settings is None:
            return
        setter = getattr(self._settings, "set", None)
        if not callable(setter):
            return
        try:
            setter(key, value)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _coerce_scale_index(raw: Any) -> int:
        """Clamp an arbitrary stored value onto ``SCALE_MAP``'s index range.

        Out-of-range or non-integer values fall back to the Step-57
        default (``3`` = 1.25×). Keeps a corrupted settings file from
        propagating an IndexError into :meth:`FileGridView.set_scale`.
        """
        try:
            idx = int(raw)
        except (TypeError, ValueError):
            return _DEFAULT_GRID_VIEW_SCALE_INDEX
        if idx not in SCALE_MAP:
            return _DEFAULT_GRID_VIEW_SCALE_INDEX
        return idx

    def _read_splitter_fraction(self) -> float:
        """Read and clamp the persisted splitter fraction (Step 57)."""
        raw = self._read_setting(
            SETTING_SPLITTER, _DEFAULT_SPLITTER_FRACTION,
        )
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return _DEFAULT_SPLITTER_FRACTION
        # Clamp to (0, 0.9] — a stored 0 or negative would collapse the
        # nav pane past :data:`_MIN_PANE_WIDTH` which the constructor
        # already guards, but keeping the splitter visible pre-widget-
        # build is friendlier to the test harness that reads the
        # fraction back without going through the widget.
        if value < 0.0 or value > 0.9:
            return _DEFAULT_SPLITTER_FRACTION
        return value

    def _apply_restored_view_state(self) -> None:
        """Apply Step-57 restored view state after :meth:`build`.

        Fires on construction only — subsequent changes route through
        the per-control callbacks below. Ordering matters:

        1. Snap the zoom-bar slider to the stored index. The bar's
           own ``on_scale`` + ``on_toggle_grid`` callbacks fire during
           the snap; ``_suppress_persist`` keeps them from writing
           back through to Settings during the restore.
        2. Apply ``show_detail_pane`` visibility to the right frame +
           splitter. The zoom-bar snap above may have crossed the
           grid/list threshold and already set :attr:`_is_grid_view`;
           hiding the detail pane is independent of view mode.
        """
        if self._zoom_bar is not None:
            self._zoom_bar.set_slider_index(self._grid_view_scale_index)
        self._apply_show_detail_pane(self._show_detail_pane)

    def _apply_show_detail_pane(self, visible: bool) -> None:
        """Hide or reveal the right detail frame + splitter.

        The left (nav) pane stays visible either way — the user always
        has a way to re-surface the detail pane, even with the splitter
        hidden, by toggling the options menu back on. When the detail
        pane is hidden, the nav frame gets a flex width (via
        ``ui.Fraction(1.0)``) so it consumes the whole widget width
        rather than staying pinned at :data:`_tree_pane_width`; when
        re-shown, the nav frame reverts to the stored pixel width.
        """
        if self._detail_frame is not None:
            self._detail_frame.visible = bool(visible)
        if self._splitter is not None:
            self._splitter.visible = bool(visible)
        if self._tree_frame is not None:
            if visible:
                self._tree_frame.width = ui.Pixel(self._tree_pane_width)
            else:
                self._tree_frame.width = ui.Fraction(1.0)

    # ── Options-menu wiring (Step 56) ────────────────────────────────────────

    def _on_show_hidden_changed(self, show_hidden: bool) -> None:
        """Fan a "Show hidden files" toggle into the model + Settings."""
        self._show_hidden = bool(show_hidden)
        if self._detail_model is not None:
            self._detail_model.set_show_hidden(self._show_hidden)
        self._write_setting(SETTING_SHOW_HIDDEN, self._show_hidden)

    def _on_show_detail_pane_changed(self, visible: bool) -> None:
        """Fan a "Show detail pane" toggle into the layout + Settings."""
        self._show_detail_pane = bool(visible)
        self._apply_show_detail_pane(self._show_detail_pane)
        self._write_setting(
            SETTING_SHOW_DETAIL_PANE, self._show_detail_pane,
        )

    def _on_sort_policy_changed(self, policy: str) -> None:
        """Fan a sort-policy radio toggle into the model + Settings."""
        self._sort_policy = policy
        if self._detail_model is not None:
            self._detail_model.set_sort_policy(policy)
        self._write_setting(SETTING_SORT_POLICY, policy)

    # ── Splitter drag ────────────────────────────────────────────────────────

    def _on_splitter_dragged(self, offset: Any) -> None:
        """Absorb the splitter's offset into the tree-pane width.

        The Placer's ``offset_x`` reports the current drag distance
        from its natural slot. We fold that distance into
        ``_tree_pane_width`` (clamped to :data:`_MIN_PANE_WIDTH`),
        reassign the tree frame's width, and reset the Placer back to
        zero so subsequent drag strokes also start from zero — without
        that reset, ``offset_x`` would accumulate and the Placer would
        visually drift out of its slot.

        The ``_suppress_splitter_cb`` flag guards against the callback
        re-entering on the programmatic reset. Invalid / non-numeric
        offsets (e.g. a ``None`` delivered during teardown) fall
        through silently — the drag would be a no-op anyway.
        """
        if self._suppress_splitter_cb:
            return
        if self._tree_frame is None or self._splitter is None:
            return
        try:
            dx = float(offset)
        except (TypeError, ValueError):
            return
        if dx == 0.0:
            return

        new_width = max(_MIN_PANE_WIDTH, self._tree_pane_width + dx)
        if new_width != self._tree_pane_width:
            self._tree_pane_width = int(new_width)
            self._tree_frame.width = ui.Pixel(self._tree_pane_width)
            # Step 57 — persist as a fraction against the default
            # widget width. Using a fixed denominator keeps the
            # stored value stable across window resizes; a future
            # step that swaps to a measured width can compute
            # ``tree_pane_width / total_width`` at drag-time.
            self._write_setting(
                SETTING_SPLITTER,
                round(self._tree_pane_width / _DEFAULT_TOTAL_WIDTH, 4),
            )

        self._suppress_splitter_cb = True
        try:
            self._splitter.offset_x = ui.Pixel(0)
        finally:
            self._suppress_splitter_cb = False

    # ── Selection sync (Step 14) ─────────────────────────────────────────────

    def _on_tree_selection(self, items: List[ui.AbstractItem]) -> None:
        """Dispatch a nav-pane click through :class:`NavigationModel` (Step 42).

        Wired via :meth:`omni.ui.TreeView.set_selection_changed_fn` in
        :meth:`_build_tree_pane`. omni.ui passes the full selection
        list; the nav pane is single-select in practice so we use the
        first item.

        :class:`CollectionItem` roots are no-op — the TreeView handles
        expand / collapse on its own; the detail pane keeps whatever it
        was showing. :class:`FileItem` children fire ``on_navigate``
        via :meth:`NavigationModel.activate_item`, which routes through
        :meth:`_navigate_to_url` and re-roots the detail model.

        Post-:meth:`destroy` the model ref is ``None`` and the call
        falls through silently. No :class:`SelectionBus` publish: file
        URLs are not prim paths (the content browser behavior).
        """
        if not items:
            return
        if self._navigation_model is None:
            return
        self._navigation_model.activate_item(items[0])

    def _navigate_to_url(self, url: str) -> None:
        """Re-root the detail pane on ``url`` — the nav-model callback target.

        Wired via :meth:`NavigationModel.set_on_navigate` in the
        widget constructor. Fires when the user clicks a
        :class:`FileItem` child under any collection (a bookmark, a
        drive, a recent file's parent folder). Re-roots the detail
        model, updates the browser bar breadcrumb, records the URL
        in the visited history, and pushes the URL into the bookmark
        star so its filled / hollow glyph tracks the new folder.

        No :class:`SelectionBus` publish — same invariant as
        :meth:`_on_tree_selection`.
        """
        if self._detail_model is None:
            return
        self._detail_model.set_root_url(url)
        if self._browser_bar is not None:
            self._browser_bar.set_path(url)
        if self._bookmark_button is not None:
            self._bookmark_button.set_current_url(url)

    def _on_detail_double_click(
        self, x: Any, y: Any, button: Any, modifier: Any,
    ) -> None:
        """Drill into a folder / log a file-open stub on detail double-click.

        Wired via :meth:`omni.ui.TreeView.set_mouse_double_clicked_fn`
        in :meth:`_build_detail_pane`. omni.ui's double-click callback
        signature is ``(x, y, button, modifier)`` — the widget-under-
        cursor's *item* is not passed, so we read it back from the
        TreeView's current ``selection`` (a mouse-press-first-of-the-
        double-click already selected the row).

        Behaviour:

        * **Folder double-click.** Re-root the detail pane at the
          folder and mirror the selection in the tree pane via
          :meth:`FileBrowserModel.resolve`. When the tree model's
          walk cannot reach the folder (e.g. the folder is filtered
          out), the tree selection is left unchanged.
        * **File double-click.** No-op at Step 14 —
          :meth:`ErrorReporter.log_info` writes a diagnostic stub to
          stderr. Step 54 replaces this with the file-open dispatch.
        * **Empty / non-``FileItem`` selection.** Silent no-op; an
          accidental double-click on empty whitespace must not crash.
        * **Post-:meth:`destroy`.** ``_detail_tree_view`` is ``None``
          and the early return avoids a dereference.
        """
        if self._detail_tree_view is None:
            return
        selection = self._detail_tree_view.selection
        if not selection:
            return
        item = selection[0]
        if not isinstance(item, FileItem):
            return

        if item.is_folder:
            self._drill_into_folder(item)
            return

        # Step 51 — fan out to the enclosing dialog's file-double-click
        # callback when wired. The :class:`FilePickerDialog` uses this
        # to fire Apply on a file double-click (standard "double-click
        # to open" dialog UX). When no callback is wired (e.g. the
        # Content Browser window), fall through to the file-open
        # dispatch.
        if self._on_file_double_clicked is not None:
            self._on_file_double_clicked(item)
            return

        self._dispatch_file_open(item)

    def _drill_into_folder(self, folder: FileItem) -> None:
        """Re-root the detail pane on a folder drill-in.

        Split out of :meth:`_on_detail_double_click` so the folder
        path is testable without simulating a mouse event. Called
        with a :class:`FileItem` that is known to be a folder.

        Step 42 drops the tree-side selection mirror: the nav pane
        renders collections, not the detail-pane folder hierarchy, so
        there is no tree row to mirror into. Drill-in affects the
        detail pane only; the nav pane's selection is untouched.
        """
        if self._detail_model is not None:
            self._detail_model.set_root_url(folder.url)
        if self._browser_bar is not None:
            self._browser_bar.set_path(folder.url)
        if self._bookmark_button is not None:
            self._bookmark_button.set_current_url(folder.url)

    def _dispatch_file_open(self, item: FileItem) -> None:
        """Open ``item`` as the active USD stage via :class:`Application`.

        Shared by the tree- and grid-pane double-click handlers so a
        user double-clicking a USD card in either view routes through
        the same :meth:`Application.open_file` call that File > Open
        uses. Only ``.usd`` / ``.usda`` / ``.usdc`` / ``.usdz`` extensions
        dispatch; non-USD rows surface a status-bar warning so the user
        sees why the click did nothing.

        ``item.url`` surfaces the backend's URL form (``file:///...`` for
        :class:`LocalFSBackend`); :meth:`Application.open_file` hands the
        string straight to :func:`pxr.Usd.Stage.Open`, which rejects the
        ``file://`` scheme and wants a native filesystem path — so the
        scheme is stripped here for local URLs. Remote URLs
        (``omniverse://``, ``http://``, ...) pass through untouched so
        the USD resolver handles them.

        The :class:`Application` import is late-bound with a
        ``RuntimeError`` guard so the widget stays usable under the
        unit-test harness (which stands the widget up without a running
        singleton). When no application is live the method no-ops.
        """
        url = item.url
        if not any(url.lower().endswith(ext) for ext in _USD_EXTENSIONS):
            ErrorReporter.show_status(
                f"Cannot open: {item.name} is not a USD file",
                level="warning",
            )
            return
        # Step 11.4/13: route the open-file action through the
        # explicit ``open_file_fn`` callback. ``None`` means no
        # Application is wired (bare-test harness) -- silent no-op
        # matches the previous ``except RuntimeError: return``
        # behavior.
        if self._open_file_fn is not None:
            self._open_file_fn(_to_open_path(url))

    # ── Empty-state overlay (Step 15) ────────────────────────────────────────

    def _on_detail_model_item_changed(
        self, model: Any, item: Any,
    ) -> None:
        """Re-run overlay + grid refresh on any detail-model change.

        :meth:`omni.ui.AbstractItemModel._item_changed` dispatches with
        two arguments — the model and the item whose children changed
        (``None`` for a top-level re-query). We react to every
        dispatch rather than filtering on ``item is None`` because
        :meth:`FileBrowserModel.refresh_item` dispatches with
        ``self._root`` as the item, and a root refresh is also
        something the overlay should react to.

        Step 24: the grid view also refreshes so card tiles track
        re-roots, drill-ins, and back-navigations. :class:`FileGridView`
        does not subscribe to the model itself — the widget is the
        single point that fans out model changes to every view that
        needs to react.

        Post-:meth:`destroy` the overlay refs have been cleared and
        :meth:`_update_empty_state` short-circuits; the grid-view
        ``None`` guard protects the rest.
        """
        self._update_empty_state()
        if self._detail_grid_view is not None:
            self._detail_grid_view.refresh()

    def _update_empty_state(self) -> None:
        """Show / hide / retitle the overlay from the detail model's state.

        Forces a populate on the detail root by calling
        :meth:`FileBrowserModel.get_item_children` so
        :attr:`FileBrowserModel.last_error` is synchronised with the
        root's most recent populate attempt. Then dispatches on the
        combination of ``last_error`` + child count:

        * ``ERROR_ACCESS_DENIED`` → "Access denied — check permissions"
          with the Retry button visible.
        * ``ERROR_NOT_FOUND`` → "Folder no longer exists — refreshing..."
          and a one-shot fallback to the parent URL (bounded by URL
          depth — there is always an eventual root that exists).
        * ``OK`` + 0 children → "This folder is empty".
        * Otherwise → overlay hidden (root has children, no error).

        Post-:meth:`destroy` every participating field is ``None`` and
        the early returns short-circuit cleanly.
        """
        container = self._empty_state_container
        label = self._empty_state_label
        retry_button = self._empty_state_retry_button
        if container is None or label is None or retry_button is None:
            return
        if self._detail_model is None:
            return

        # Force a populate on the root so ``last_error`` reflects the
        # current root's populate attempt. Calling with the root item
        # explicitly (rather than ``None``) is equivalent per the
        # model's contract but reads more clearly at the call site —
        # the overlay is about the root pane's state, not about an
        # implicit "top-level children" query.
        children = self._detail_model.get_item_children(self._detail_model.root)
        error = self._detail_model.last_error

        def _show(text: str, retry: bool) -> None:
            label.text = text
            retry_button.visible = retry
            container.visible = True
            # Hide the ScrollingFrame while the overlay is up so the
            # TreeView's header row + root row don't bleed through.
            # Using explicit visibility rather than relying on the
            # ZStack's z-order because omni.ui's layering + the
            # TreeView's self-drawn header don't cooperate to fully
            # obscure the header behind the overlay.
            if self._detail_scrolling_frame is not None:
                self._detail_scrolling_frame.visible = False
            # Step 24 — the grid view is the other sibling in the
            # ZStack; hide it too while the overlay is up so the
            # card tiles don't render behind the "empty" label.
            if self._detail_grid_frame is not None:
                self._detail_grid_frame.visible = False

        def _hide() -> None:
            container.visible = False
            retry_button.visible = False
            # Step 24 — restore whichever view mode is currently active;
            # the overlay may have hidden both siblings so both need
            # attention here. ``_is_grid_view`` tracks the last
            # user-selected mode via the zoom bar's toggle callback.
            if self._is_grid_view:
                if self._detail_grid_frame is not None:
                    self._detail_grid_frame.visible = True
                if self._detail_scrolling_frame is not None:
                    self._detail_scrolling_frame.visible = False
            else:
                if self._detail_grid_frame is not None:
                    self._detail_grid_frame.visible = False
                if self._detail_scrolling_frame is not None:
                    self._detail_scrolling_frame.visible = True

        if error is BackendResult.ERROR_ACCESS_DENIED:
            _show(_ACCESS_DENIED_MESSAGE, retry=True)
            return
        if error is BackendResult.ERROR_NOT_FOUND:
            _show(_NOT_FOUND_MESSAGE, retry=False)
            self._schedule_parent_fallback()
            return
        if not children:
            _show(_EMPTY_FOLDER_MESSAGE, retry=False)
            return
        _hide()

    def _on_retry_clicked(self) -> None:
        """Retry the detail root's populate — wired to the Retry button.

        The overlay's Retry button fires this callback when the user
        wants to re-attempt a failed populate (typically after the
        permissions issue that caused ``ERROR_ACCESS_DENIED`` has been
        addressed out-of-band). :meth:`FileBrowserModel.refresh_all`
        marks the root dirty and schedules an ``item_changed`` dispatch;
        the subscription round-trips back into :meth:`_update_empty_state`
        on the next frame with the fresh populate result.

        Post-:meth:`destroy` the model is ``None`` and the call is a
        silent no-op.
        """
        self.refresh()

    def refresh(self) -> None:
        """Re-populate the detail pane from the backend.

        Step 58 entry point for the F5 keyboard shortcut. Drives the
        same code path as the ACCESS_DENIED retry button so the
        repopulate runs through :meth:`FileBrowserModel.refresh_all` —
        that method marks the root dirty and schedules an
        ``item_changed`` dispatch; the subscription round-trips back
        into :meth:`_update_empty_state` on the next frame with the
        fresh populate result.

        Post-:meth:`destroy` the detail-model ref is ``None`` and the
        call is a silent no-op.
        """
        if self._detail_model is None:
            return
        self._detail_model.refresh_all()

    def _schedule_parent_fallback(self) -> None:
        """Schedule a one-shot re-root to the parent URL for NOT_FOUND.

        When the detail root errors with ``ERROR_NOT_FOUND`` the folder
        the user was viewing is gone. The visible message is
        "refreshing..."; the actual refresh action is to drop the
        user back to the parent folder (which, by filesystem invariant,
        still exists above the missing child). We defer the re-root
        one frame via :meth:`ovwidgets.app.application.Application.call_later`
        so the overlay paints the message before the re-root fires —
        the user briefly sees "refreshing..." rather than a silent
        redirect. The :attr:`_parent_fallback_scheduled` flag keeps a
        burst of ``item_changed`` dispatches from queueing duplicate
        fallbacks.

        The fallback terminates naturally: re-rooting to the parent
        resets ``last_error`` to ``OK`` and the next populate either
        succeeds or cascades to the parent's parent. URL depth is
        finite, so the walk eventually reaches a folder that does
        populate.
        """
        if self._detail_model is None:
            return
        if self._parent_fallback_scheduled:
            return
        current_url = self._detail_model.root_url
        parent_url = self._backend.parent_url(current_url)
        if parent_url is None or parent_url == current_url:
            # At the top of the URL space — nowhere to fall back to.
            return
        # Late-bind the scheduler import: the widget is testable
        # without a live scheduler (tests exercise the fallback path
        # synchronously via ``_do_parent_fallback``), and the import
        # would otherwise pull a heavy module into the widget's
        # construction path.
        from ovwidgets.common import scheduler as _scheduler

        try:
            handle = _scheduler.call_later(0.0, self._do_parent_fallback)
        except RuntimeError:
            # No scheduler registered — no deferred dispatch available.
            # Leave the overlay showing; tests drive
            # ``_do_parent_fallback`` directly when they want to observe
            # the re-root.
            return
        self._parent_fallback_scheduled = True
        # ``handle`` is intentionally not retained: the parent-fallback
        # scheduler call is fire-and-forget; the latch is reset inside
        # ``_do_parent_fallback`` itself.
        del handle

    def _do_parent_fallback(self) -> None:
        """Execute the deferred NOT_FOUND → parent-URL fallback.

        Split out of :meth:`_schedule_parent_fallback` so tests can
        drive the re-root without a running :class:`Application`
        singleton. Resets the ``_parent_fallback_scheduled`` latch
        unconditionally — the re-root cycles back through
        :meth:`_update_empty_state` and may immediately schedule a
        fresh fallback if the parent is also missing.
        """
        self._parent_fallback_scheduled = False
        if self._detail_model is None:
            return
        current_url = self._detail_model.root_url
        parent_url = self._backend.parent_url(current_url)
        if parent_url is None or parent_url == current_url:
            return
        self._detail_model.set_root_url(parent_url)

    # ── Navigation ───────────────────────────────────────────────────────────

    def navigate_to(self, url: str) -> None:
        """Swap both models' roots to ``url``.

        Both tree and detail panes re-root together so the user's
        "navigate to X" action behaves as a whole-widget reset.
        Step 14 adds the selection-sync path where the tree's
        selection drives only the detail pane's root. Step 20 also
        pushes the normalised URL into the :class:`BrowserBar` so the
        breadcrumb row + visited history track external navigations
        (e.g. the Step 11 startup bootstrap).

        The URL is normalised through the backend before being handed
        to the browser bar. Both :class:`FileBrowserModel.set_root_url`
        calls already normalise internally; passing the un-normalised
        form to the browser bar would make the breadcrumb display
        drift out of sync with the detail-pane root on the first call
        with a trailing-slash or similar un-canonical URL.

        No-op after :meth:`destroy` — the models are ``None`` and
        there is nothing to navigate.
        """
        if self._backend is not None:
            normalized = self._backend.normalize_url(url)
        else:
            normalized = url
        if self._detail_model is not None:
            self._detail_model.set_root_url(normalized)
        if self._browser_bar is not None:
            self._browser_bar.set_path(normalized)
        if self._bookmark_button is not None:
            self._bookmark_button.set_current_url(normalized)

    # ── BrowserBar apply-path / begin-edit / nav (Step 20) ───────────────────

    def _on_apply_path(self, url: str) -> None:
        """Validate ``url`` and navigate — the :class:`BrowserBar` apply handler.

        the content browser implementation step 20. Fired by:

        * :class:`PathField` on Enter in the typing popup.
        * :class:`PathField` on a click of an individual breadcrumb
          segment.
        * :meth:`BrowserBar.go_back` / :meth:`BrowserBar.go_forward`
          when the user steps the visited-history cursor.

        Flow: normalise through the backend, :meth:`BackendAdapter.stat`
        the canonical URL, and:

        * On any non-OK stat or a stat that returns an entry without
          :attr:`BackendFileFlags.IS_FOLDER` — post the "Folder not
          found" status via :class:`ErrorReporter` and leave the panes
          where they are. The browser bar is *not* reverted: the user
          keeps their typed input in the field so they can correct it
          in place, and the failed apply does not pollute the visited
          history.
        * On success — re-root the detail model, mirror the tree
          selection, and call :meth:`BrowserBar.set_path` to record the
          normalised URL in the visited history and refresh the
          breadcrumb display. ``set_path`` is a no-op insert when this
          call originated from a back/forward click (the history's
          ``_is_navigating`` latch consumes it).

        Post-:meth:`destroy` — every participating field is ``None`` and
        the early returns short-circuit cleanly.
        """
        if self._backend is None or self._detail_model is None:
            return
        if not url:
            return
        normalized = self._backend.normalize_url(url)
        result, entry = self._backend.stat(normalized)
        is_folder = (
            entry is not None
            and bool(entry.flags & BackendFileFlags.IS_FOLDER)
        )
        if result is not BackendResult.OK or not is_folder:
            # Log + status-bar so the user sees the failure even if the
            # status label has not been initialised (Step 11 wires it
            # during app startup; unit tests run without it).
            ErrorReporter.log_warning(
                "FileBrowserWidget",
                f"Apply path failed: {normalized} "
                f"(result={result.name}, is_folder={is_folder})",
            )
            ErrorReporter.show_warning(_FOLDER_NOT_FOUND_MESSAGE)
            return

        # Re-root the detail pane. ``set_root_url`` is a no-op if the
        # URL matches the current root, so consecutive applies on the
        # same folder do not churn the populate cache.
        self._detail_model.set_root_url(normalized)

        # Step 42 — no tree-side mirror: the nav pane shows
        # collections, not the detail-pane folder hierarchy, so
        # there's no corresponding row to select. Future steps may
        # auto-expand the collection that owns the applied path
        # (e.g. scroll to the bookmark that matches the typed URL);
        # Step 42's nav pane is a dispatcher only.

        # Record the successful navigation in the browser bar's history
        # + refresh the breadcrumb display. When the apply originated
        # from go_back / go_forward the ``_is_navigating`` latch inside
        # the history consumes this insert so the history trail stays
        # linear rather than growing a loop.
        if self._browser_bar is not None:
            self._browser_bar.set_path(normalized)
        if self._bookmark_button is not None:
            self._bookmark_button.set_current_url(normalized)

    def _on_begin_edit(self) -> None:
        """Hook fired when the user opens the :class:`PathField` popup.

        Step 20 reserves the slot but has nothing to cancel — later
        steps may use it to kill an in-flight navigation task or pause
        the auto-refresh timer so a typed path does not race a
        background populate. Kept as a named method (rather than a
        lambda at the BrowserBar construction site) so the test module
        can patch it and the future-step additions have an obvious
        home.
        """
        return None

    def go_back(self) -> None:
        """Step the visited-history cursor back via the :class:`BrowserBar`.

        Public entry point for the Alt+Left shortcut dispatched by
        :class:`ovwidgets.app.application.Application`. Delegates to
        :meth:`BrowserBar.go_back`, which (1) pulls the previous URL
        from the history, (2) echoes it into the :class:`PathField`,
        (3) fires :meth:`_on_apply_path` to navigate the backend.

        No-op after :meth:`destroy`, before :meth:`build`, or when the
        history has no older entries — each layer is defensive against
        the case the layer above it did not check.
        """
        if self._browser_bar is not None:
            self._browser_bar.go_back()

    def go_forward(self) -> None:
        """Step the visited-history cursor forward via the :class:`BrowserBar`.

        Mirror of :meth:`go_back` — Alt+Right shortcut target.
        """
        if self._browser_bar is not None:
            self._browser_bar.go_forward()

    # ── PathField autocomplete (Step 18) ─────────────────────────────────────

    def _path_autocomplete(
        self,
        prefix: str,
        callback: Callable[[List[str]], None],
    ) -> None:
        """Provider for :class:`PathField`'s ``autocomplete_handler``.

        the content browser implementation step 18 / the content browser behavior The
        path bar edits a *directory* URL, so the dropdown only surfaces
        sub-folders — files are filtered out. Each returned name keeps
        its trailing ``/`` so committing a suggestion extends the typed
        path into a well-formed directory URL rather than a bare leaf.

        ``prefix`` is the directory URL the caller wants listed (the
        path bar's committed portion — everything up to the last
        separator). On any non-OK backend result the callback fires
        with an empty list so the dropdown simply stays empty; the
        user can still type a full path and commit via Enter.

        No-op after :meth:`destroy` — the backend reference is gone;
        we fire the callback with ``[]`` to keep the widget's state
        machine unstuck rather than silently swallowing the call.
        """
        if self._backend is None:
            callback([])
            return
        result, entries = self._backend.list_dir(prefix)
        if result is not BackendResult.OK:
            callback([])
            return
        callback([
            entry.name + "/"
            for entry in entries
            if entry.flags & BackendFileFlags.IS_FOLDER
        ])

    # ── Search + filter wiring (Step 28) ─────────────────────────────────────

    def _on_search_changed(self, text: str) -> None:
        """Forward a :class:`SearchField` change to the detail model.

        :class:`SearchField` fires this 200 ms after the user stops
        typing (debounced via :meth:`ovwidgets.app.application.Application.call_later`)
        and immediately on a clear-button click. The filter is applied
        to the detail pane only — the tree pane stays unfiltered so the
        user can still navigate into folders whose only leaves the
        filter would hide.

        Post-:meth:`destroy` — the detail model ref is ``None`` and the
        call falls through. A late fire from a pending debounce handle
        is defended against by :class:`SearchField.destroy` itself,
        which cancels the handle before the widget nulls its refs.
        """
        if self._detail_model is None:
            return
        self._detail_model.set_text_filter(text)

    def _on_filter_changed(
        self, categories: Set[AssetCategory],
    ) -> None:
        """Forward a :class:`FilterButton` change to the detail model.

        :class:`FilterButton` fires this every time a dropdown item is
        toggled. The empty set (every category unchecked) is the
        "show all" signal — :meth:`FileBrowserModel.set_asset_type_whitelist`
        folds empty-set into None so the whitelist pipeline stops
        rejecting everything.

        The filter lands on the detail model only. Folders always pass
        the whitelist regardless, so the tree pane staying unfiltered
        is a no-op for UX consistency rather than a deliberate split.

        Post-:meth:`destroy` — the detail model ref is ``None`` and the
        call falls through.
        """
        if self._detail_model is None:
            return
        self._detail_model.set_asset_type_whitelist(categories)

    # ── Zoom bar + grid view wiring (Step 24) ────────────────────────────────

    def _on_zoom_bar_scale(self, scale: float) -> None:
        """Forward a zoom-bar slider scale change to the grid view.

        :class:`ZoomBar` fires this on every slider move with the
        mapped float (0.5 / 0.75 / 1.0 / 1.25 / 1.5 / 2.0). The grid
        view rebuilds its cards at the new edge size — selection
        survives the rebuild because :class:`FileGridView` keys its
        selection by URL rather than by :class:`FileItem` identity.

        Ordered before the zoom bar's own ``on_toggle_grid`` callback
        — see :mod:`zoom_bar`'s slider-dispatch docstring — so when a
        slider drag crosses the 0.75 threshold the grid has already
        rescaled by the time the visibility swap flips it in.

        Post-:meth:`destroy` — the grid ref is ``None`` and the call
        falls through.

        Step 57: the zoom bar's current slider index is also persisted
        to :data:`SETTING_GRID_VIEW_SCALE` so the next session's
        widget constructor can replay it.
        """
        if self._detail_grid_view is None:
            return
        self._detail_grid_view.set_scale(scale)
        if self._zoom_bar is not None:
            self._grid_view_scale_index = (
                self._zoom_bar.current_slider_index
            )
            self._write_setting(
                SETTING_GRID_VIEW_SCALE, self._grid_view_scale_index,
            )

    def _on_zoom_bar_toggle_grid(self, show_grid: bool) -> None:
        """Swap the detail pane between grid and list view.

        Triggered from two zoom-bar pathways (see §25.4):

        * **Explicit toggle-button click** — the user hits the grid /
          list icon to switch modes.
        * **Slider threshold crossing** — dragging the slider across
          the 0.75 scale boundary implicitly flips the mode.

        Selection preservation contract: the active view's selected
        items are stashed before the visibility flip and re-applied
        to the destination view after. Both views address the same
        :class:`FileBrowserModel` root, so their items share URLs;
        :class:`FileGridView.set_selection` matches by URL, and the
        tree view's ``selection`` assignment takes the :class:`FileItem`
        list directly. A toggle with nothing selected is a clean no-op
        on the selection side.

        Empty-state overlay invariant: if the overlay is currently up,
        the visible-frame flips below are still safe because the
        overlay's ``_show()`` path has both frames already set hidden;
        the first post-overlay-hide call to ``_hide()`` reads the
        freshly-updated :attr:`_is_grid_view` and restores the right
        frame.

        Post-:meth:`destroy` — every participating field is ``None``
        and the guards short-circuit cleanly.
        """
        if (
            self._detail_grid_view is None
            or self._detail_grid_frame is None
            or self._detail_tree_view is None
            or self._detail_scrolling_frame is None
        ):
            return

        # Stash the active view's selection before swapping visibility.
        # Tree-view ``.selection`` returns a :class:`ui.AbstractItem`
        # list; we cast to ``list`` so the subsequent reassignment is
        # against a Python-owned container (avoids aliasing ovui's
        # internal vector, which could shift under us during the swap).
        if self._is_grid_view:
            stashed: List[Any] = self._detail_grid_view.get_selection()
        else:
            stashed = list(self._detail_tree_view.selection)

        self._is_grid_view = show_grid
        # Step 57 — persist the active view mode so the next session
        # opens in the same grid / list state.
        self._write_setting(SETTING_SHOW_GRID_VIEW, self._is_grid_view)
        # Hide the outgoing frame first, then show the incoming one.
        # This ordering keeps both frames from painting in the same
        # frame — a brief visual double-paint is otherwise possible
        # depending on omni.ui's draw-order heuristics.
        if show_grid:
            self._detail_scrolling_frame.visible = False
            self._detail_grid_frame.visible = True
        else:
            self._detail_grid_frame.visible = False
            self._detail_scrolling_frame.visible = True

        # Re-apply the stashed selection to the destination view.
        # :meth:`FileGridView.set_selection` filters to matching URLs
        # under the hood; the tree-view assignment takes the list
        # verbatim, which is safe because the items came from the
        # same ``_detail_model`` and so are still valid tree nodes.
        if show_grid:
            self._detail_grid_view.set_selection(list(stashed))
        else:
            self._detail_tree_view.selection = list(stashed)

    def _on_grid_click(
        self, item: FileItem, button: int, modifier: int,
    ) -> None:
        """Post-click hook from :class:`FileGridView`.

        :class:`FileGridView` updates its own selection before firing
        this callback. Step 51 fans the post-click selection out to the
        ``on_selection_changed`` callback so the enclosing
        :class:`FilePickerDialog` can populate its :class:`FileBar`
        filename field with the single selected file. Left-button clicks
        are the only ones that update selection; right-clicks hit
        :meth:`_on_grid_right_click` separately.
        """
        self._emit_detail_selection_changed()

    def _on_grid_double_click(self, item: FileItem) -> None:
        """Drill into / open a grid card on double-click.

        Mirror of :meth:`_on_detail_double_click`'s folder-vs-file
        branch, lifted out of the tree-view path so the grid and tree
        share the same drill-in semantics. The grid already resolved
        the clicked item via its own :class:`FileItem` snapshot; no
        selection-read gymnastics required.

        * **Folder** — re-root the detail pane and mirror the tree
          selection (Step 14 :meth:`_drill_into_folder`).
        * **File** — fan out to ``on_file_double_clicked`` when wired
          (Step 51 — :class:`FilePickerDialog` fires Apply from there);
          otherwise dispatch through :meth:`_dispatch_file_open` so a
          USD card opens as the active stage.
        """
        if not isinstance(item, FileItem):
            return
        if item.is_folder:
            self._drill_into_folder(item)
            return
        if self._on_file_double_clicked is not None:
            self._on_file_double_clicked(item)
            return
        self._dispatch_file_open(item)

    def _on_detail_tree_selection(
        self, items: List[ui.AbstractItem],
    ) -> None:
        """Dispatch a detail-tree selection change through the Step-51 callback.

        Wired via :meth:`omni.ui.TreeView.set_selection_changed_fn` in
        :meth:`_build_detail_pane`. The delivered ``items`` list is the
        new selection; we route through :meth:`_emit_detail_selection_changed`
        which reads the authoritative current selection from the active
        view (tree or grid) so multi-select paths stay consistent with
        :meth:`FilePickerDialog.get_selection`.
        """
        self._emit_detail_selection_changed()

    def _emit_detail_selection_changed(self) -> None:
        """Fire ``on_selection_changed`` with the current detail-pane selection.

        Reads the selection from the active view — grid when
        :attr:`_is_grid_view`, else the detail :class:`ui.TreeView`.
        Mirrors the resolution order :meth:`FilePickerDialog.get_selection`
        uses (grid-first, tree-fallback) so the callback sees the same
        shape a caller would get from the public accessor.

        No-op when no callback is wired. Returns a fresh list on every
        fire so a caller that stores the list cannot mutate the internal
        selection state by writing to it.
        """
        if self._on_selection_changed is None:
            return
        items: List[FileItem] = []
        grid = self._detail_grid_view
        if self._is_grid_view and grid is not None:
            try:
                for sel in grid.get_selection():
                    if isinstance(sel, FileItem):
                        items.append(sel)
            except Exception:  # noqa: BLE001
                pass
        else:
            tree = self._detail_tree_view
            if tree is not None:
                try:
                    for sel in tree.selection:
                        if isinstance(sel, FileItem):
                            items.append(sel)
                except Exception:  # noqa: BLE001
                    pass
        self._on_selection_changed(items)

    # ── Context menu dispatch (Step 31) ──────────────────────────────────────

    def _on_row_right_click(
        self, x: float, y: float, item: FileItem,
    ) -> None:
        """Open the :class:`FileContextMenu` for a delegate-row right-click.

        Wired into :class:`FileBrowserDelegate` (detail pane) via its
        ``set_on_right_click`` setter. The menu classifies ``item`` on
        its own (file / folder) and pops the corresponding entry set
        at the supplied screen coords. The nav pane's
        :class:`NavigationDelegate` (Step 42) does not surface row
        context menus — collection-root context menus land in Step 45.

        Post-:meth:`destroy` the menu ref is ``None`` and the call
        falls through — a late callback from a still-live TreeView
        cannot crash into a torn-down menu.
        """
        if self._context_menu is None:
            return
        self._context_menu.show(float(x), float(y), item)

    def _on_grid_right_click(
        self, item: FileItem, x: float, y: float,
    ) -> None:
        """Open the context menu for a right-clicked card (Step 31)."""
        if self._context_menu is None:
            return
        self._context_menu.show(float(x), float(y), item)

    def _on_grid_empty_right_click(self, x: float, y: float) -> None:
        """Open the empty-space context menu on a grid background right-click.

        Fires when the user right-clicks in a gap between cards or the
        trailing empty area below the last grid row. The menu pops
        with ``item=None`` so :class:`FileContextMenu` surfaces the
        empty-space entry set (Create Folder / Paste / Refresh).
        """
        if self._context_menu is None:
            return
        self._context_menu.show(float(x), float(y), None)

    def _on_nav_right_click(
        self, x: float, y: float, item: Any,
    ) -> None:
        """Open the bookmark-remove menu for a right-clicked bookmark row.

        Step 45. Wired into :class:`NavigationDelegate.set_on_right_click`.
        The nav pane has heterogeneous rows — :class:`CollectionItem`
        roots (Bookmarks / My Computer / Recent) and their
        :class:`FileItem` children. We react only when the right-click
        lands on a bookmark-collection child: that row has a named
        bookmark in the :class:`BookmarksManager` and the architecture
        surfaces "Remove Bookmark" exclusively. Collection roots and
        non-bookmark children silently consume the right-click (the
        nav pane has no other context menus in Step 45 — Recent /
        My Computer remove affordances land in future steps).

        Resolving the bookmark's name from the row goes through the
        manager's current mapping so a stale :class:`FileItem` (e.g.
        the collection cached an item with an older name) still
        resolves to the live bookmark.
        """
        if self._context_menu is None:
            return
        if self._bookmarks is None:
            return
        if not isinstance(item, FileItem):
            return
        # The nav pane's FileItem children under BookmarksCollection
        # carry the bookmark's name in :attr:`FileItem.name`. Any row
        # whose name does not correspond to a live bookmark is ignored
        # — that screens out :class:`MyComputerCollection` children
        # and the (Step 46) recent-file rows without a shared parent
        # lookup. A bookmark that was renamed through another surface
        # between the row build and the right-click is likewise
        # filtered out; the user's next right-click on the rebuilt
        # row picks up the new name.
        name = item.name
        if not name:
            return
        manager_map = self._bookmarks.list()
        if name not in manager_map or manager_map[name] != item.url:
            return
        self._context_menu.show_bookmark_menu(float(x), float(y), name)

    # ── Rename dispatch (Step 33) ────────────────────────────────────────────

    def begin_rename(self, item: FileItem) -> None:
        """Enter inline rename mode for ``item``.

        Entry point for the :class:`FileContextMenu` Rename entry and
        for the application-level F2 shortcut via
        :meth:`begin_rename_selected`. Routes straight into
        :meth:`RenameController.begin_rename`.

        Post-:meth:`destroy` the controller ref is ``None`` and the
        call is a silent no-op.
        """
        if self._rename_controller is None:
            return
        if not isinstance(item, FileItem):
            return
        self._rename_controller.begin_rename(item)

    def begin_rename_selected(self) -> None:
        """Rename the first currently-selected item — wired to F2.

        Resolution order (matches the selection surfaces the user sees):

        * **Grid view selection** (active when ``_is_grid_view`` is
          ``True``) — the first selected :class:`FileItem` becomes the
          rename target.
        * **Detail tree-view selection** (list mode) — the first
          selected row.
        * **Tree-pane selection** — the currently-selected folder in
          the left pane as a final fallback.

        A silent no-op when nothing is selected, the widget is
        destroyed, or the controller has been torn down.
        """
        if self._rename_controller is None:
            return
        target: Optional[FileItem] = None
        # Grid mode: prefer the grid's selection.
        if self._is_grid_view and self._detail_grid_view is not None:
            grid_selection = self._detail_grid_view.get_selection()
            if grid_selection:
                first = grid_selection[0]
                if isinstance(first, FileItem):
                    target = first
        # List mode (or grid with no selection): fall back to the
        # detail tree-view's selection.
        if target is None and self._detail_tree_view is not None:
            detail_selection = self._detail_tree_view.selection
            if detail_selection:
                first = detail_selection[0]
                if isinstance(first, FileItem):
                    target = first
        # Last resort: the tree pane's selected folder.
        if target is None and self._tree_tree_view is not None:
            tree_selection = self._tree_tree_view.selection
            if tree_selection:
                first = tree_selection[0]
                if isinstance(first, FileItem):
                    target = first
        if target is None:
            return
        self._rename_controller.begin_rename(target)

    # ── Delete dispatch (Step 34) ────────────────────────────────────────────

    def delete_selected(self) -> None:
        """Show the confirm-delete dialog for the current multi-selection.

        Selection resolution mirrors :meth:`begin_rename_selected`
        (grid → detail tree → tree pane) but preserves the **entire**
        selection rather than picking the first item. The dialog lists
        every resolved :class:`FileItem` so the user sees the full
        blast radius before confirming.

        The right pane's selection (grid or detail tree depending on
        view mode) wins when it has entries, because that is where the
        user's visual focus is for a multi-select drag. The tree pane
        is a last-resort single-item fallback — a user who has only
        the left pane selected (e.g. a folder) still gets a working
        Del shortcut.

        A silent no-op when nothing is selected, the widget is
        destroyed, or the context menu has been torn down.
        """
        if self._context_menu is None:
            return
        targets: List[FileItem] = []
        # Right pane first — grid mode vs list mode.
        if self._is_grid_view and self._detail_grid_view is not None:
            grid_selection = self._detail_grid_view.get_selection()
            for sel in grid_selection:
                if isinstance(sel, FileItem):
                    targets.append(sel)
        if not targets and self._detail_tree_view is not None:
            for sel in self._detail_tree_view.selection:
                if isinstance(sel, FileItem):
                    targets.append(sel)
        # Last resort: the tree pane's selection.
        if not targets and self._tree_tree_view is not None:
            for sel in self._tree_tree_view.selection:
                if isinstance(sel, FileItem):
                    targets.append(sel)
        if not targets:
            return
        self._context_menu._open_confirm_delete_dialog(targets)

    # ── Clipboard dispatch (Step 36) ─────────────────────────────────────────

    def copy_selected(self) -> None:
        """Copy the current multi-selection to the clipboard — wired to Ctrl+C.

        Selection resolution mirrors :meth:`delete_selected` (grid →
        detail tree → tree pane) so Ctrl+C fires against whatever pane
        the user is working in. Silent no-op when nothing is selected,
        the context menu was torn down, or the widget is destroyed.
        """
        if self._context_menu is None:
            return
        targets = self._resolve_multi_selection()
        if not targets:
            return
        self._context_menu._copy_items(targets)

    def cut_selected(self) -> None:
        """Cut the current multi-selection to the clipboard — wired to Ctrl+X."""
        if self._context_menu is None:
            return
        targets = self._resolve_multi_selection()
        if not targets:
            return
        self._context_menu._cut_items(targets)

    def paste_into_current(self) -> None:
        """Paste the clipboard into the detail pane's current folder — Ctrl+V.

        Empty-space destination (the detail root) so the paste lands in
        whatever folder the user is currently browsing. No-op when the
        menu or detail model is missing — an empty clipboard surfaces
        a user-visible warning inside
        :meth:`FileContextMenu._begin_paste_into`, so the menu's own
        guard handles that case.
        """
        if self._context_menu is None:
            return
        self._context_menu._begin_paste_into(None)

    def duplicate_selected(self) -> None:
        """Duplicate the current multi-selection — wired to Ctrl+D (Step 37).

        Same selection-resolution path as
        :meth:`copy_selected` / :meth:`delete_selected` (grid →
        detail tree → tree pane) so Ctrl+D fires against whichever
        pane the user is working in. Silent no-op when nothing is
        selected, the context menu was torn down, or the widget is
        destroyed.
        """
        if self._context_menu is None:
            return
        targets = self._resolve_multi_selection()
        if not targets:
            return
        self._context_menu._duplicate_items(targets)

    def refresh_cut_style(self) -> None:
        """Repaint cards + rows so clipboard-mode changes take effect.

        Called by the context menu after Copy / Cut / clear-clipboard so
        the ``::Cut`` style variant (applied at build time by reading
        :func:`clipboard.is_path_cut`) refreshes against the new state.
        Grid rebuilds via :meth:`FileGridView.refresh`; list-mode rows
        rebuild via :meth:`FileBrowserModel.refresh_all` on the detail
        pane. The nav pane has no clipboard state — collection roots
        and their virtual children don't participate in Cut / Copy —
        so no refresh is dispatched there.
        """
        if self._detail_grid_view is not None:
            self._detail_grid_view.refresh()
        if self._detail_model is not None:
            refresh_all = getattr(self._detail_model, "refresh_all", None)
            if refresh_all is not None:
                refresh_all()

    def _resolve_multi_selection(self) -> List[FileItem]:
        """Return the current multi-selection across the detail pane.

        Mirror of the selection-resolution logic inside
        :meth:`delete_selected` — grid first (when in grid view), then
        the detail tree-view. Step 42 drops the nav-pane fallback: the
        nav pane selects collection roots (not deletable) and their
        :class:`FileItem` children represent navigation targets (drive
        roots, bookmarks, recent files) that the user does not expect
        a Delete / Cut invocation from the detail-pane to operate on.

        Returned list is fresh so callers can mutate freely.
        """
        targets: List[FileItem] = []
        if self._is_grid_view and self._detail_grid_view is not None:
            grid_selection = self._detail_grid_view.get_selection()
            for sel in grid_selection:
                if isinstance(sel, FileItem):
                    targets.append(sel)
        if not targets and self._detail_tree_view is not None:
            for sel in self._detail_tree_view.selection:
                if isinstance(sel, FileItem):
                    targets.append(sel)
        return targets

    # ── Drag-drop dispatch (Step 38 / 42) ────────────────────────────────────

    def _detail_drag_payload(self) -> str:
        """Return the MIME payload for a detail-pane drag.

        Step 42 drops the tree-pane drag source — the left pane now
        renders collections, not draggable folder items. Drags
        originate from the detail pane only. In grid-view mode the
        payload comes from the grid's URL-keyed selection; in
        list-view mode it comes from the detail TreeView's
        :attr:`selection`. The ``"\\n"`` separator matches
        the content browser behavior (newline-joined URLs).
        """
        urls: List[str] = []
        if self._is_grid_view and self._detail_grid_view is not None:
            for sel in self._detail_grid_view.get_selection():
                if isinstance(sel, FileItem):
                    urls.append(sel.url)
        elif self._detail_tree_view is not None:
            for sel in self._detail_tree_view.selection:
                if isinstance(sel, FileItem):
                    urls.append(sel.url)
        return "\n".join(urls)

    @staticmethod
    def _accept_drop_mime(mime: str) -> bool:
        """Return True if ``mime`` carries one or more non-empty URLs.

        ovui calls this predicate during drag-over to decide whether
        to paint the "can drop here" cursor. Any ``"\\n"``-separated
        payload with at least one non-empty segment passes — finer
        validation (self-drop, ancestor-of-target) happens on the drop
        itself inside :meth:`FileBrowserModel.drop`. The split here is
        deliberate: early rejection during drag-over would need the
        target item, which ovui does not hand us at accept-time.
        """
        if not mime:
            return False
        return any(u for u in mime.split("\n"))

    def _is_ctrl_drop(self) -> bool:
        """Return ``True`` when the user is holding Ctrl at drop time.

        ovui's :class:`WidgetMouseDropEvent` does not carry modifier
        bits, so we read Ctrl state from the widget-local
        :attr:`_modifier_bits` snapshot that
        :class:`ContentBrowserWindow._on_key_pressed` updates on every
        key event (see :meth:`set_modifier_bits`). Step 10/13 replaced
        the pre-Step-10 ``Application.instance()._last_modifier_bits``
        read with this widget-local tracker. Tests without a live key
        dispatch fall through to ``False`` — the test module drives
        the copy vs move branch by calling
        :meth:`FileBrowserModel.drop` with ``is_copy=True`` directly,
        or by calling :meth:`set_modifier_bits` to seed the snapshot.
        """
        return bool(self._modifier_bits & _MOD_CTRL)

    def set_modifier_bits(self, bits: int) -> None:
        """Update the widget-local modifier-bit snapshot (Step 10/13).

        Called by :class:`ContentBrowserWindow._on_key_pressed` at the
        top of every key event so the widget always sees the current
        modifier mask without reaching into
        ``Application._last_modifier_bits``. Tests can call this
        directly to drive Ctrl-during-drop behavior.
        """
        self._modifier_bits = int(bits)

    def _dispatch_drop(
        self, target_item: Optional[FileItem], mime: str,
    ) -> None:
        """Route a drop event into the detail model with cross-pane refresh.

        Single point where tree / detail-tree / empty-space / card drops
        converge. The detail model owns the backend, so every drop
        variant routes through :meth:`FileBrowserModel.drop` on the
        detail model regardless of which pane fired the drop — a drop
        onto a tree folder and a drop onto a grid card both relocate
        the underlying filesystem entries exactly the same way; the
        visual pane split is a presentation concern, not a data one.

        ``on_complete`` cascades the refresh to the sibling tree model.
        The detail model has already refreshed its own affected parents
        by the time :meth:`_drop_finalize` fires this callback; the
        tree model is refreshed independently so the folder counts in
        the left pane track the move.

        Post-:meth:`destroy` both models are ``None`` — the early
        return keeps a late drop event from touching torn-down state.

        Step 41 — clears the :class:`DropIndicator` before returning,
        whether the drop actually ran (model / backend live) or bailed
        out early. A drop event always ends the drag; any highlight
        surviving the dispatch would read as a stuck hover.
        """
        if self._drop_indicator is not None:
            self._drop_indicator.clear()
        if self._detail_model is None or self._backend is None:
            return
        if not mime:
            return
        is_copy = self._is_ctrl_drop()
        self._detail_model.drop(
            target_item=target_item,
            urls_str=mime,
            is_copy=is_copy,
            on_complete=self._on_drop_complete,
        )

    def _on_drop_complete(self) -> None:
        """Cascade post-drop refresh to the grid view (Step 42).

        Fires after :meth:`FileBrowserModel._drop_finalize` has already
        refreshed the detail model's affected parents. Pre-Step-42 this
        also refreshed a sibling tree model; the Step 42 nav pane is a
        collection list, not a folder cache, so there's nothing to
        refresh there. The grid view refreshes — tile selection is
        URL-keyed so it survives the rebuild.
        """
        if self._detail_grid_view is not None:
            self._detail_grid_view.refresh()

    def _on_detail_drop(self, event: Any) -> None:
        """Drop handler for the detail-pane list-view :class:`ui.TreeView`.

        Resolves the drop target to the detail-pane's current selection
        if it names a folder; otherwise falls back to the detail root
        (the empty-space drop case). Delegates to :meth:`_dispatch_drop`.
        """
        if self._detail_tree_view is None:
            return
        target: Optional[FileItem] = None
        for sel in self._detail_tree_view.selection:
            if isinstance(sel, FileItem) and sel.is_folder:
                target = sel
                break
        self._dispatch_drop(target, getattr(event, "mime_data", "") or "")

    def _on_detail_empty_drop(self, event: Any) -> None:
        """Drop handler for the detail-pane empty-space area.

        Handles drops that land in the :class:`ui.ScrollingFrame`
        whitespace (list view) or the :class:`FileGridView`'s gap
        regions. ``target_item=None`` makes
        :meth:`FileBrowserModel.drop` route to the detail model's
        current root.
        """
        self._dispatch_drop(None, getattr(event, "mime_data", "") or "")

    def _on_card_drop(
        self, item: FileItem, mime: str,
    ) -> None:
        """Drop handler fired by a :class:`FileCard` (grid tile).

        Dispatched from :meth:`FileCard._dispatch_drop` with the card's
        own :class:`FileItem` as ``item``. Non-folder targets fall
        through to :meth:`_dispatch_drop` which refuses them — a file
        card should not paint a "drop accepted" cursor, but a runtime
        guard here belts the braces if the accept predicate
        ever diverges from the drop handler.
        """
        if not isinstance(item, FileItem) or not item.is_folder:
            return
        self._dispatch_drop(item, mime or "")

    # ── External drag-drop (Step 39) ─────────────────────────────────────────

    @property
    def detail_root_url(self) -> Optional[str]:
        """URL of the folder currently shown in the detail pane.

        Surface for the window-layer :meth:`ContentBrowserWindow._on_external_drop`
        hook (the content browser implementation step 39): an OS drag-drop lands on the
        whole window, but the "drop target" is always the folder the
        user is currently browsing. Returns ``None`` after
        :meth:`destroy` — the detail model is the single source of
        truth while alive and cleared on teardown.
        """
        if self._detail_model is None:
            return None
        return self._detail_model.root_url

    def accept_external_drop(self, urls: List[str]) -> int:
        """Copy each URL in ``urls`` into the current detail folder.

        Entry point for OS-originated drops (the content browser implementation step 39).
        The window parses :attr:`WidgetMouseDropEvent.mime_data` — a
        newline-joined payload matching the internal-drag MIME format
        (the content browser behavior) — and forwards the URL list
        here. Each surviving source is copied with ``overwrite=False``
        into the detail model's current root via
        :meth:`BackendAdapter.copy`.

        After the batch the detail pane refreshes via
        :meth:`FileBrowserModel.refresh_all` and the widget-level
        :meth:`_on_drop_complete` cascades the refresh to the tree
        pane and grid view. Returns the number of successful copies
        so the caller (the window) can decide the status-bar
        vocabulary.

        Silent no-ops:

        * ``urls`` empty or every entry whitespace-only.
        * :meth:`destroy` already fired (backend / detail model None).
        * A source whose :meth:`BackendAdapter.basename` is empty
          (can happen for degenerate URLs like ``"file:///"``).

        Per-source failures (``ERROR_ALREADY_EXISTS``, ``ERROR_NOT_FOUND``,
        ``ERROR_PERMISSION``) are logged via :class:`ErrorReporter` but
        do not stop the batch — a drop of three files where the middle
        one collides still lands the first and third, matching the
        user's "drop everything I dragged" mental model.
        """
        if self._backend is None or self._detail_model is None:
            return 0
        clean = [u for u in urls if u and u.strip()]
        if not clean:
            return 0
        target_url = self._detail_model.root_url
        success = 0
        for src in clean:
            name = self._backend.basename(src)
            if not name:
                continue
            dst = self._backend.join_url(target_url, name)
            result = self._backend.copy(src, dst, overwrite=False)
            if result == BackendResult.OK:
                success += 1
            else:
                ErrorReporter.show_warning(
                    f"External drop: failed to copy '{src}' → '{dst}' "
                    f"({result.name})",
                )
        if success:
            self._detail_model.refresh_all()
            self._on_drop_complete()
        return success

    # ── Backend swap ─────────────────────────────────────────────────────────

    def set_backend(self, backend: BackendAdapter) -> None:
        """Replace the backend on the detail model + navigation model.

        Constructs a fresh :class:`FileBrowserModel` for the detail
        pane against the new backend (the Step 7 model does not expose
        an in-place backend setter), rebuilds the :class:`NavigationModel`
        (its collections enumerate backend URLs — drives, bookmarks —
        so the new backend has to reach them), and reassigns each
        view's ``model``. The previous detail model is released via
        :meth:`FileBrowserModel.destroy` so its
        :meth:`BackendAdapter.subscribe_changes` handle is cancelled
        cleanly; the nav model has no backend subscription and is just
        dropped.

        No-op after :meth:`destroy` — the widget is in a consumed
        state and has no models to read root URLs from.
        """
        if self._navigation_model is None or self._detail_model is None:
            return
        self._backend = backend

        old_detail_model = self._detail_model

        # Step 42 — rebuild the navigation model against the new
        # backend. The nav pane's collections don't have a "root URL"
        # to preserve the way a filesystem folder tree does; their
        # children are enumerated on demand from whatever backend the
        # model currently holds. Step 46 — thread the existing
        # bookmarks / recent-files / settings refs through so the
        # backend swap doesn't silently drop the nav pane's persistent
        # roots.
        new_nav = NavigationModel(
            backend,
            bookmarks=self._bookmarks,
            recent_files=self._recent_files,
            settings=self._settings,
        )
        new_nav.set_on_navigate(self._navigate_to_url)
        self._navigation_model = new_nav
        if self._tree_tree_view is not None:
            self._tree_tree_view.model = new_nav

        detail_root = old_detail_model.root_url
        new_detail = FileBrowserModel(
            backend, detail_root, folder_only=False,
        )
        self._detail_model = new_detail
        if self._detail_delegate is not None:
            self._detail_delegate.set_model(new_detail)
        if self._detail_tree_view is not None:
            self._detail_tree_view.model = new_detail
        # Step 24: rebind the grid view to the new detail model. The
        # grid's model is private; reassigning it directly + calling
        # :meth:`FileGridView.refresh` rebuilds cards against the new
        # backend. An alternative — destroy + reconstruct the grid —
        # would require re-entering the detail-pane's :class:`ui.ZStack`
        # build context, which we cannot do outside :meth:`build`.
        if self._detail_grid_view is not None:
            self._detail_grid_view._model = new_detail
            self._detail_grid_view.refresh()
        # Step 15: the old model's subscription is stale (fires on the
        # old model's events); rebind the empty-state callback to the
        # fresh model and re-run the overlay check against the new
        # root. Dropping the old subscription handle to ``None``
        # releases the bound method — the old model is about to be
        # garbage collected once this function returns.
        self._detail_model_change_sub = (
            new_detail.subscribe_item_changed_fn(
                self._on_detail_model_item_changed,
            )
        )
        # Step 16: cancel the outgoing detail model's backend
        # subscription. The old model has no remaining strong
        # references in the widget after the reassignment above, but
        # the old backend's subscriber list still holds its
        # ``_on_backend_change`` bound method — dropping it is what
        # finally lets the old model be garbage-collected.
        old_detail_model.destroy()
        self._update_empty_state()

    # ── Accessors ────────────────────────────────────────────────────────────

    def get_model(self) -> Optional[FileBrowserModel]:
        """Legacy single-pane accessor — returns the detail model.

        Kept so Step 10/11's :class:`ContentBrowserWindow` and the
        Step 11 QA script can address "the" model without knowing
        about the two-pane split. New callers should prefer
        :meth:`get_tree_model` / :meth:`get_detail_model`.
        """
        return self._detail_model

    def get_tree_model(self) -> Optional[NavigationModel]:
        """Return the left pane's :class:`NavigationModel` (Step 42).

        Pre-Step-42 this returned a folder-only :class:`FileBrowserModel`;
        Step 42 replaces the folder-tree left pane with a collection
        navigation model. The accessor name is kept for backward
        compatibility with older QA scripts that address "the tree
        model", but the returned type is now a :class:`NavigationModel`
        with collection roots instead of folder children.
        """
        return self._navigation_model

    def get_navigation_model(self) -> Optional[NavigationModel]:
        """Return the left pane's :class:`NavigationModel` (Step 42).

        Named accessor for new callers; mirrors
        :meth:`get_detail_model` for the right pane. Prefer this over
        :meth:`get_tree_model` in newly-written code.
        """
        return self._navigation_model

    def get_detail_model(self) -> Optional[FileBrowserModel]:
        """Return the right pane's full :class:`FileBrowserModel`."""
        return self._detail_model

    # Backward-compat aliases for QA scripts and other callers that
    # grew against the Step 9 single-pane widget. Map to the detail
    # pane — the one that renders the three-column file list.
    @property
    def _model(self) -> Optional[FileBrowserModel]:
        return self._detail_model

    @property
    def _tree_view(self) -> Optional[ui.TreeView]:
        return self._detail_tree_view

    @property
    def _delegate(self) -> Optional[FileBrowserDelegate]:
        return self._detail_delegate

    @property
    def _scrolling_frame(self) -> Optional[ui.ScrollingFrame]:
        return self._detail_scrolling_frame

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Release views, models, delegates, and splitter references.

        Idempotent — the ``is not None`` guards below short-circuit a
        second call, and every other assignment is a no-op once the
        fields are already ``None``. The Step 14 selection / double-
        click callbacks are bound methods holding ``self``; clear them
        before nulling the TreeView refs so the C++ side does not keep
        the widget (and the models through it) alive via the callback
        slot.
        """
        if self._tree_tree_view is not None:
            self._tree_tree_view.set_selection_changed_fn(None)
        if self._detail_tree_view is not None:
            self._detail_tree_view.set_mouse_double_clicked_fn(None)
            # Step 51 — drop the detail-selection callback too so a late
            # TreeView firing post-destroy cannot route into the
            # soon-to-be-nulled dialog. ``hasattr`` guard keeps test
            # fakes (``_FakeTreeView`` in test_clipboard_ops,
            # ``_FakeSelection`` in test_delete) — which only implement
            # the subset of the TreeView API the test needs — from
            # crashing the destroy path.
            if hasattr(
                self._detail_tree_view, "set_selection_changed_fn",
            ):
                self._detail_tree_view.set_selection_changed_fn(None)
        # Step 51 — clear the fan-out callbacks so a caller-side drop
        # of the widget does not leak the dialog's bound methods.
        self._on_selection_changed = None
        self._on_file_double_clicked = None
        if self._splitter is not None:
            self._splitter.set_offset_x_changed_fn(None)
        # Step 42 — detach the navigation model's on_navigate callback
        # first so a late selection change from the nav TreeView cannot
        # route into the widget's soon-to-be-nulled detail model.
        if self._navigation_model is not None:
            self._navigation_model.set_on_navigate(None)
        # Step 45 — detach the navigation delegate's right-click handler
        # before the widget refs that back it go away. A late press
        # reaching the delegate finds a ``None`` handler and returns.
        if self._navigation_delegate is not None:
            self._navigation_delegate.set_on_right_click(None)
        if self._detail_delegate is not None:
            self._detail_delegate.set_on_right_click(None)
            self._detail_delegate.set_rename_controller(None)
            self._detail_delegate.set_drop_indicator(None)
            self._detail_delegate.set_model(None)
        # Step 33 — detach the grid view's controller ref before the
        # grid itself is destroyed a few lines below.
        if self._detail_grid_view is not None:
            self._detail_grid_view.set_rename_controller(None)
        if self._rename_controller is not None:
            self._rename_controller.destroy()
            self._rename_controller = None
        # Step 31 — tear down the context menu after the delegates have
        # dropped their handler refs but before the models / views are
        # nulled. :meth:`FileContextMenu.destroy` hides any live popup
        # and drops the plug-in registration list.
        if self._context_menu is not None:
            self._context_menu.destroy()
            self._context_menu = None
        # Step 20 — tear down the browser bar first so its
        # :class:`PathField` popup / subscription cleanup runs while
        # every upstream ref is still live. :meth:`BrowserBar.destroy`
        # is idempotent, so a second destroy call falls through safely.
        if self._browser_bar is not None:
            self._browser_bar.destroy()
            self._browser_bar = None
        # Step 28 — tear down the search field and filter button. The
        # search field's :meth:`destroy` cancels any pending debounce
        # handle before nulling its refs, so a late frame tick cannot
        # reach a half-nulled widget. The filter button hides and
        # drops its :class:`ui.Menu` so a click-outside that fires
        # after teardown finds no live popup. Both are idempotent.
        if self._search_field is not None:
            self._search_field.destroy()
            self._search_field = None
        if self._filter_button is not None:
            self._filter_button.destroy()
            self._filter_button = None
        # Step 56 — tear down the options gear button. Idempotent;
        # hides + drops its live :class:`ui.Menu` so a click-outside
        # that fires after teardown finds no live popup.
        if self._options_button is not None:
            self._options_button.destroy()
            self._options_button = None
        # Step 45 — tear down the bookmark star. :meth:`BookmarkButton.destroy`
        # dismisses any live Add / Remove dialog, cancels the manager
        # subscription, and drops every ovui ref; idempotent.
        if self._bookmark_button is not None:
            self._bookmark_button.destroy()
            self._bookmark_button = None
        # Step 24 — tear down the zoom bar and grid view. Zoom bar
        # first so its slider subscription stops firing into the grid
        # view's :meth:`set_scale` before the grid is destroyed.
        # Both destroy methods are idempotent.
        if self._zoom_bar is not None:
            self._zoom_bar.destroy()
            self._zoom_bar = None
        if self._detail_grid_view is not None:
            self._detail_grid_view.destroy()
            self._detail_grid_view = None
        self._detail_grid_frame = None
        # Step 15: drop the detail-model ``item_changed`` subscription
        # before nulling the model — releases the bound method so the
        # model's subscriber set does not keep the widget alive via a
        # strong ref to ``_on_detail_model_item_changed``.
        self._detail_model_change_sub = None
        self._tree_tree_view = None
        self._detail_tree_view = None
        self._tree_frame = None
        self._detail_frame = None
        self._tree_scrolling_frame = None
        self._detail_scrolling_frame = None
        self._splitter = None
        self._empty_state_container = None
        self._empty_state_label = None
        self._empty_state_retry_button = None
        self._navigation_delegate = None
        self._detail_delegate = None
        # Step 41 — release the drop indicator. The controller is a
        # pure-Python state holder with no backend subscriptions, so
        # dropping the reference is enough; any lingering highlight
        # becomes moot because the widgets it tracked have just been
        # nulled above.
        if self._drop_indicator is not None:
            self._drop_indicator.clear()
            self._drop_indicator = None
        # Step 16: release the detail model's backend ``subscribe_changes``
        # handle before nulling. Without this, the backend's subscriber
        # list keeps the model alive via the bound ``_on_backend_change``
        # reference for as long as the backend lives — a real leak in
        # the common case where the backend is shared across widgets.
        # The navigation model has no backend subscription in Step 42
        # (its stub collections enumerate lazily with no watch), so
        # dropping the reference is enough.
        self._navigation_model = None
        if self._detail_model is not None:
            self._detail_model.destroy()
        self._detail_model = None
        # Step 45 — drop the bookmark manager ref so a post-destroy
        # getattr from a stale context-menu handler returns ``None``
        # and the method short-circuits cleanly.
        self._bookmarks = None
        # Step 46 — drop the recent-files / settings refs. The
        # :class:`RecentFilesCollection`'s RAII :class:`Subscription`
        # was already released when the nav model was nulled above.
        self._recent_files = None
        self._settings = None
