# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Dockable window shell hosting :class:`FileBrowserWidget`.

See the content browser behavior (Content Browser window layer) and
the content browser implementation step 10. The window owns docking, title, module styles,
and lifecycle; the widget owns tree model, delegate, navigation, and
backend swap. Mirrors :class:`ovui_widgets.stage.window.StageWindow` so the
widget/window split is uniform across panels (widget-window split).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Callable, Optional, Tuple, Union

import omni.ui as ui

from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.common.managed_window import ManagedWindow
from ovui_widgets.content.backends.backend_adapter import BackendAdapter
from ovui_widgets.content.backends.local_fs_backend import LocalFSBackend
from ovui_widgets.content.bookmarks import BookmarksManager
from ovui_widgets.content.style import CONTENT_STYLES
from ovui_widgets.content.widget.file_browser_widget import (
    FileBrowserWidget,
)

if TYPE_CHECKING:
    from ovui_widgets.common.recent_files import RecentFileList
    from ovui_widgets.common.settings import Settings


# GLFW key / modifier codes for the Step-58 content-browser shortcuts
# that do not already live on :class:`Application._on_key_pressed`.
# Kept as module-level constants so the tests can import them and the
# dispatcher below matches on named symbols rather than magic ints.
_MOD_CTRL = 2
_MOD_SHIFT = 1
_MOD_ALT = 4
_REAL_MODS_MASK = _MOD_CTRL | _MOD_SHIFT | _MOD_ALT | 8  # 8 = super
_KEY_ESCAPE = 256
_KEY_F5 = 294
_KEY_ARROW_UP = 265
_KEY_HOME = 268


class ContentBrowserWindow(ManagedWindow):
    """Dockable window hosting a :class:`FileBrowserWidget`.

    The ``backend`` argument is auto-wrapped like UsdStageAdapter:
    :class:`UsdStageAdapter` convenience):

    - ``None``                → a fresh :class:`LocalFSBackend`.
    - :class:`BackendAdapter` → used as-is.
    - ``str``                 → a fresh :class:`LocalFSBackend`, with
      the string taken as ``start_url`` when no explicit
      ``start_url`` was supplied.

    ``start_url`` defaults to the user's home directory normalised
    through the backend. The :class:`FileBrowserWidget` is late-bound:
    it is constructed on the first rendered frame when ovui calls
    :meth:`_build_ui`, so :meth:`navigate_to` is a no-op before then.
    """

    def __init__(
        self,
        backend: Optional[Union[BackendAdapter, str]] = None,
        start_url: Optional[str] = None,
        bookmarks: Optional[BookmarksManager] = None,
        recent_files: Optional["RecentFileList"] = None,
        settings: Optional["Settings"] = None,
        open_file_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        if isinstance(backend, str):
            if start_url is None:
                start_url = backend
            backend = None
        self._backend: BackendAdapter = (
            backend if backend is not None else LocalFSBackend()
        )
        if start_url is None:
            default_start = os.path.expanduser("~")
            start_url = self._backend.normalize_url(f"file://{default_start}")
        self._start_url: str = start_url
        # Step 45 — optional :class:`BookmarksManager`. When ``None``,
        # the window lazy-constructs one against the live
        # :class:`Application`'s :class:`Settings` so bookmarks persist
        # across sessions automatically. The lazy construction goes
        # through a try / except on :class:`Application.instance` so a
        # test that stands up the window without a running application
        # (unit-test harness) still gets a bookmarkable widget: the
        # widget's ``bookmarks`` attribute just ends up ``None`` and
        # the toolbar star surfaces a warning on click.
        self._bookmarks: Optional[BookmarksManager] = (
            bookmarks if bookmarks is not None else self._resolve_bookmarks()
        )
        # Step 46 — optional :class:`RecentFileList` + :class:`Settings`
        # for the nav pane's Recent collection. Lazy-resolve both from
        # the live :class:`Application` singleton when not explicitly
        # passed (mirrors the ``_resolve_bookmarks`` path above).
        # Resolving both from the same source keeps the in-memory list
        # (:attr:`Application._recent_files`) and the persisted key
        # (``ui.recent_files`` on :attr:`Application.settings`) in sync
        # so an ``open_file`` write shows up live on both reads.
        resolved_recent, resolved_settings = self._resolve_recent_files(
            recent_files, settings,
        )
        self._recent_files: Optional["RecentFileList"] = resolved_recent
        self._settings: Optional["Settings"] = resolved_settings
        # Step 11.4/13: explicit open-file callback; plumbed into
        # ``FileBrowserWidget`` at ``_build_ui`` time. Replaces the
        # pre-Step-11.4 lazy ``Application.instance().open_file(url)``
        # lookup. ``None`` → bare-test harness no-op.
        self._open_file_fn: Optional[Callable[[str], None]] = open_file_fn
        self._widget: Optional[FileBrowserWidget] = None
        # NO_SCROLLBAR suppresses the parent ui.Window's built-in scrollbar;
        # the inner ui.ScrollingFrame in FileBrowserWidget owns all scrolling.
        super().__init__(
            "Content",
            width=800,
            height=400,
            flags=ui.WINDOW_FLAGS_NO_SCROLLBAR,
        )

    @staticmethod
    def _resolve_bookmarks() -> Optional[BookmarksManager]:
        """Build a :class:`BookmarksManager` from the live settings singleton.

        Returns ``None`` when no :class:`Settings` singleton is
        registered — tests that exercise the window in isolation may
        land here and the widget's bookmark surfaces (star button,
        context-menu Add Bookmark) surface a user-visible warning on
        click rather than silently failing.

        Step 10/13: switched from ``Application.instance().settings`` to
        :meth:`ovui_widgets.common.settings.Settings.instance` so the read
        no longer depends on the :class:`Application` singleton.
        """
        try:
            from ovui_widgets.common.settings import Settings
            settings = Settings.instance()
        except Exception:  # noqa: BLE001
            return None
        return BookmarksManager(settings)

    @staticmethod
    def _resolve_recent_files(
        recent_files: Optional["RecentFileList"],
        settings: Optional["Settings"],
    ) -> Tuple[Optional["RecentFileList"], Optional["Settings"]]:
        """Resolve the Recent collection's data sources.

        Explicit arguments override; otherwise the common-side
        singletons supply :class:`RecentFileList` and :class:`Settings`
        so :class:`RecentFilesCollection` sees the same in-memory list
        that :meth:`Application.open_file` writes into and the same
        :class:`Settings` that persists the ``ui.recent_files`` key.

        Returns the original ``(recent_files, settings)`` tuple
        unchanged when the singleton accessors fail (e.g., tests that
        exercise the window in isolation without registering the
        Application singletons) — the Recent collection then renders
        as an empty nav root.

        Step 10/13: switched from ``Application.instance().{settings,
        _recent_files}`` to
        :meth:`ovui_widgets.common.recent_files.RecentFileList.instance`
        and :meth:`ovui_widgets.common.settings.Settings.instance` so the
        read no longer depends on the :class:`Application` singleton.
        """
        if recent_files is not None and settings is not None:
            return recent_files, settings
        if recent_files is None:
            try:
                from ovui_widgets.common.recent_files import RecentFileList
                recent_files = RecentFileList.instance()
            except Exception:  # noqa: BLE001
                pass
        if settings is None:
            try:
                from ovui_widgets.common.settings import Settings
                settings = Settings.instance()
            except Exception:  # noqa: BLE001
                pass
        return recent_files, settings

    def _get_module_styles(self) -> dict:
        return CONTENT_STYLES

    def _build_ui(self) -> None:
        self._widget = FileBrowserWidget(
            backend=self._backend,
            root_url=self._start_url,
            bookmarks=self._bookmarks,
            recent_files=self._recent_files,
            settings=self._settings,
            open_file_fn=self._open_file_fn,
        )
        # Step 39 — per-window external drag-drop. ovui's
        # :meth:`ui.Window.set_drop_fn` fires once for each OS drop over
        # this window; the callback parses the newline-joined payload
        # and forwards the list to the widget. Wired here (and not in
        # ``__init__``) because ``self._window`` is constructed by
        # :meth:`ManagedWindow.__init__` but the drop should only fire
        # after the widget exists — otherwise a drop before first render
        # would crash on a None widget. The ``hasattr`` guard protects
        # against ovui builds that do not expose ``set_drop_fn`` (mirrors
        # the pattern at :meth:`Application._register_drop_handler`).
        if hasattr(self._window, "set_drop_fn"):
            self._window.set_drop_fn(self._on_external_drop)

    def navigate_to(self, url: str) -> None:
        """Forward a root-URL change to the inner widget.

        No-op before :meth:`_build_ui` has fired or after
        :meth:`destroy` — the widget is the only thing that can
        navigate, and it may not exist yet.
        """
        if self._widget is not None:
            self._widget.navigate_to(url)

    def go_back(self) -> None:
        """Forward Alt+Left to the widget's :class:`BrowserBar`.

        Step 20 — entry point for the application-level keyboard
        shortcut dispatch (see
        :meth:`ovui_widgets.app.application.Application._on_key_pressed`). No-op
        before :meth:`_build_ui` has fired or after :meth:`destroy`;
        the inner :meth:`FileBrowserWidget.go_back` is itself a no-op
        when the visited history is empty, so repeated presses at the
        start of a session are harmless.
        """
        if self._widget is not None:
            self._widget.go_back()

    def go_forward(self) -> None:
        """Forward Alt+Right to the widget's :class:`BrowserBar`."""
        if self._widget is not None:
            self._widget.go_forward()

    def begin_rename_selected(self) -> None:
        """Forward F2 to the widget's inline rename (Step 33).

        The application-level key dispatcher calls this when F2 is
        pressed with the Content window focused; the widget resolves
        the selected item across grid / detail-tree / tree panes and
        routes into the :class:`RenameController`. No-op before
        :meth:`_build_ui` fires or after :meth:`destroy`.
        """
        if self._widget is not None:
            self._widget.begin_rename_selected()

    def delete_selected(self) -> None:
        """Forward Del to the widget's confirm-delete dialog (Step 34).

        The application-level key dispatcher calls this on every Del
        press; the widget resolves the current selection across grid
        / detail-tree / tree panes and spawns a
        :class:`ConfirmDeleteDialog`. No-op before :meth:`_build_ui`
        fires or after :meth:`destroy`, and silently skips when the
        widget has no active selection.
        """
        if self._widget is not None:
            self._widget.delete_selected()

    def copy_selected(self) -> None:
        """Forward Ctrl+C to the widget's clipboard (Step 36).

        The widget resolves the current multi-selection across grid
        / detail-tree / tree panes and writes URLs into the
        in-process clipboard as a Copy selection. No-op before
        :meth:`_build_ui` fires or after :meth:`destroy`.
        """
        if self._widget is not None:
            self._widget.copy_selected()

    def cut_selected(self) -> None:
        """Forward Ctrl+X to the widget's clipboard (Step 36).

        Same resolution as :meth:`copy_selected` but writes URLs as a
        Cut selection, which applies the ``::Cut`` style variant to
        the source cards / rows.
        """
        if self._widget is not None:
            self._widget.cut_selected()

    def paste_into_current(self) -> None:
        """Forward Ctrl+V to the widget's paste-into-current-folder (Step 36).

        Paste always lands in the detail pane's current root — the
        keyboard shortcut has no target-disambiguation affordance, so
        the folder the user is browsing is the only sensible target.
        The context-menu Paste on a folder target supports pasting
        into a sibling folder — that is the path for that use case.
        """
        if self._widget is not None:
            self._widget.paste_into_current()

    def duplicate_selected(self) -> None:
        """Forward Ctrl+D to the widget's duplicate dispatch (Step 37).

        Same selection-resolution as :meth:`copy_selected` /
        :meth:`cut_selected`: the widget resolves the current multi-
        selection across grid / detail-tree / tree panes and dispatches
        :meth:`FileContextMenu._duplicate_items`. No-op before
        :meth:`_build_ui` fires or after :meth:`destroy`.
        """
        if self._widget is not None:
            self._widget.duplicate_selected()

    # ── Step 58 — keyboard-shortcut proxies ──────────────────────────────────

    def go_up(self) -> None:
        """Navigate to the parent of the detail pane's current folder.

        Alt+Up shortcut (Step 58). Reads
        :attr:`FileBrowserWidget.detail_root_url`, resolves the parent
        via :meth:`BackendAdapter.parent_url`, and routes through
        :meth:`FileBrowserWidget.navigate_to` so the
        :class:`BrowserBar` visited-history tracks the hop (same code
        path as a breadcrumb click). No-op at the URL root (parent
        resolves to ``None`` or the same URL), before
        :meth:`_build_ui` fires, or after :meth:`destroy`.
        """
        if self._widget is None:
            return
        current = self._widget.detail_root_url
        if not current:
            return
        parent = self._backend.parent_url(current)
        if not parent or parent == current:
            return
        self._widget.navigate_to(parent)

    def refresh(self) -> None:
        """Re-populate the detail pane from the backend (F5).

        Routes through :meth:`FileBrowserWidget.refresh` so the
        widget's existing retry path drives the repopulate (the
        ERROR_ACCESS_DENIED overlay's Retry button uses the same
        entry point). No-op before :meth:`_build_ui` fires or after
        :meth:`destroy`.
        """
        if self._widget is not None:
            self._widget.refresh()

    def focus_search(self) -> None:
        """Focus the toolbar search field (Ctrl+F).

        Reaches into the widget's :class:`SearchField` and calls its
        :meth:`ui.StringField.focus_keyboard` so the next keystroke
        lands in the filter input. Silent no-op when the search field
        has not been built (e.g. pre :meth:`_build_ui`), when the
        widget has been destroyed, or when the ovui build does not
        expose ``focus_keyboard`` on :class:`ui.StringField`.
        """
        if self._widget is None:
            return
        field = getattr(self._widget, "_search_field", None)
        if field is None:
            return
        inner = getattr(field, "_field", None)
        if inner is None:
            return
        focus_fn = getattr(inner, "focus_keyboard", None)
        if focus_fn is not None:
            focus_fn()

    def navigate_home(self) -> None:
        """Navigate the detail pane to the user's home directory (Ctrl+Home).

        Resolves ``~`` against the owning backend via
        :meth:`BackendAdapter.normalize_url` so the shortcut lands on a
        backend-specific home for non-local backends (the mock backend
        resolves ``file://~`` to ``mock://Home``). No-op before
        :meth:`_build_ui` fires or after :meth:`destroy`.
        """
        if self._widget is None:
            return
        default_start = os.path.expanduser("~")
        home_url = self._backend.normalize_url(f"file://{default_start}")
        self._widget.navigate_to(home_url)

    def clear_selection_or_dismiss(self) -> None:
        """Dismiss any live context menu OR clear the detail selection (Escape).

        Two-phase: if a :class:`FileContextMenu` popup is currently
        shown, dismiss it and return without touching selection (the
        user is cancelling the menu, not the selection behind it). If
        no menu is open, clear the detail-pane tree + grid selections
        so a subsequent Ctrl+C / Del is a no-op rather than acting on
        a stale target. No-op before :meth:`_build_ui` fires or after
        :meth:`destroy`.
        """
        if self._widget is None:
            return
        menu = getattr(self._widget, "_context_menu", None)
        live_popup = getattr(menu, "_menu", None) if menu is not None else None
        if live_popup is not None:
            try:
                live_popup.hide()
            except Exception:  # noqa: BLE001
                # ovui raises when the C++ popup was already torn down;
                # swallow so the dismiss path stays idempotent.
                pass
            menu._menu = None
            return
        tree = getattr(self._widget, "_detail_tree_view", None)
        if tree is not None:
            try:
                tree.selection = []
            except Exception:  # noqa: BLE001
                pass
        grid = getattr(self._widget, "_detail_grid_view", None)
        if grid is not None:
            set_selection = getattr(grid, "set_selection", None)
            if set_selection is not None:
                set_selection([])

    def forward_modifier_bits(self, bits: int) -> None:
        """Forward the live modifier mask to the file-browser widget.

        Called by :meth:`ovui_widgets.app.application.Application._on_key_pressed`
        on **every** key event (press AND release), before the
        ``not pressed`` early-return that gates the shortcut
        dispatcher. Step 10/13 introduced this seam so
        :meth:`FileBrowserWidget._is_ctrl_drop` can read a fresh
        modifier snapshot at drop-time without reaching into
        ``Application.instance()._last_modifier_bits`` -- in
        particular, a Ctrl release between drag-start and drop must
        clear the widget's local ``_modifier_bits`` so the drop falls
        back to ``move`` semantics. Kept separate from
        :meth:`_on_key_pressed` so that the shortcut-dispatch surface
        stays press-only.
        """
        widget = self._widget
        if widget is not None and hasattr(widget, "set_modifier_bits"):
            widget.set_modifier_bits(int(bits))

    def _on_key_pressed(
        self,
        key: int,
        modifiers: int,
        pressed: bool,
    ) -> bool:
        """Dispatch content-browser-scoped keyboard shortcuts (Step 58).

        Wired from :meth:`ovui_widgets.app.application.Application._on_key_pressed`
        as the content-browser tail of the app-wide dispatcher. Returns
        ``True`` when a shortcut was handled so a future app-level
        filter can short-circuit duplicate dispatch; every non-matching
        key falls through to ``False`` so the caller is free to keep
        routing. Mirrors the Step-53 pattern the top-level dispatcher
        uses for viewport-only keys.

        Handles only the Step-58 additions (Alt+Up, F5, Ctrl+F,
        Ctrl+Home, Escape); existing shortcuts (Ctrl+C / X / V / D,
        Del, F2, Alt+Left / Right) continue to dispatch directly from
        :meth:`Application._on_key_pressed` via the matching proxy
        methods on this class. Splitting the two keeps the historic
        dispatch paths untouched while giving the new shortcuts a
        single unit-testable home.

        Releases are ignored (``pressed=False`` returns ``False``) —
        matches the contract :meth:`Application._on_key_pressed`
        enforces before calling this hook. Modifier-bit forwarding
        for :meth:`FileBrowserWidget._is_ctrl_drop` lives on the
        sibling :meth:`forward_modifier_bits` (Step 10/13) so this
        shortcut-dispatch path stays press-only.
        """
        if not pressed:
            return False
        modifiers &= _REAL_MODS_MASK
        ctrl = bool(modifiers & _MOD_CTRL)
        shift = bool(modifiers & _MOD_SHIFT)
        alt = bool(modifiers & _MOD_ALT)
        # Alt+Up — up one level.
        if alt and not ctrl and not shift and key == _KEY_ARROW_UP:
            self.go_up()
            return True
        # F5 — refresh the current detail pane. Plain press; any
        # modifier drops through (F5 is not chorded).
        if key == _KEY_F5 and not ctrl and not shift and not alt:
            self.refresh()
            return True
        # Ctrl+F — focus the search field.
        if ctrl and not alt and not shift and key in (ord("F"), ord("f")):
            self.focus_search()
            return True
        # Ctrl+Home — navigate to the user's home directory.
        if ctrl and not alt and not shift and key == _KEY_HOME:
            self.navigate_home()
            return True
        # Escape — dismiss the context menu if open, else clear the
        # detail-pane selection. Plain press: chorded Escape (Shift+Esc
        # etc.) falls through so a future binding can own it.
        if key == _KEY_ESCAPE and not ctrl and not shift and not alt:
            self.clear_selection_or_dismiss()
            return True
        return False

    def _on_external_drop(self, event: Any) -> None:
        """Handle an OS drop onto the content browser window (Step 39).

        ovui fires :class:`WidgetMouseDropEvent` whose ``mime_data`` is
        the newline-joined payload the host OS produced for the drag —
        matches the MIME format used by the internal drag-drop flow
        (the content browser behavior). Each URL is copied into the
        folder currently shown in the detail pane via
        :meth:`FileBrowserWidget.accept_external_drop`.

        Silent no-op when:

        * ``event`` has no ``mime_data`` attribute or it is empty /
          whitespace-only (OS drops without a payload, test stubs).
        * The widget is not yet built (a drop in the first frame
          before :meth:`_build_ui` fired).
        * The drop payload contains only empty URL segments after the
          ``"\\n"`` split.

        Every successful copy surfaces a single aggregate status line
        ("Imported N items via drop") so the user sees one message
        per drop, not one per file — matches Step 34's delete status-
        bar vocabulary ("Deleted N items"). Per-URL failures are
        already logged inside :meth:`accept_external_drop`.
        """
        if self._widget is None:
            return
        raw = getattr(event, "mime_data", None)
        if not raw:
            return
        urls = [u for u in raw.split("\n") if u and u.strip()]
        if not urls:
            return
        success = self._widget.accept_external_drop(urls)
        if success == 1:
            ErrorReporter.show_status(
                "Imported 1 item via drop", level="success",
            )
        elif success > 1:
            ErrorReporter.show_status(
                f"Imported {success} items via drop", level="success",
            )

    def destroy(self) -> None:
        if self._widget is not None:
            self._widget.destroy()
            self._widget = None
        super().destroy()
