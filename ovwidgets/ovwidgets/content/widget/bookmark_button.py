# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""BookmarkButton — toolbar star toggle for the current folder.

Step 45 (the content browser implementation step G, the content browser behavior). A compact
star-icon button that sits in the content-browser toolbar row and
reflects whether the detail pane's current folder is bookmarked.
Clicking when the current folder is not yet bookmarked opens a
:class:`SimpleInputDialog` prompting for a display name and calls
:meth:`BookmarksManager.add`; clicking when it is already bookmarked
opens a :class:`ConfirmDeleteDialog`-style modal confirming removal
and calls :meth:`BookmarksManager.remove`.

The button is reactive in two directions:

* **URL changes.** :class:`FileBrowserWidget` calls
  :meth:`set_current_url` on every navigation (drill-in, back /
  forward, nav-pane click, apply-path). The icon flips between the
  hollow (``content_bookmark``) and filled (``content_bookmark_filled``)
  variants so the user sees at a glance whether the displayed folder
  is a bookmark.
* **Manager mutations.** The button subscribes to
  :meth:`BookmarksManager.subscribe_changed` at construction so an
  Add Bookmark / Remove Bookmark action taken through any other
  surface (context menu on a folder row, a REST service in a future
  step) still drives the star state for the currently-viewed folder.

The button owns no knowledge of the detail pane's model — it takes
the current URL as a plain string through :meth:`set_current_url`,
which is the same contract :class:`BrowserBar.set_path` uses. That
keeps the button testable in isolation without standing up a live
backend / model / widget harness.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional

import omni.ui as ui

from ovwidgets.common.error_reporter import ErrorReporter
from ovwidgets.common.style.urls import get_icon_path
from ovwidgets.content.widget.confirm_delete_dialog import (
    ConfirmDeleteDialog,
)
from ovwidgets.content.widget.simple_input_dialog import (
    SimpleInputDialog,
)

if TYPE_CHECKING:
    from ovwidgets.common.settings import Subscription
    from ovwidgets.content.backends.backend_adapter import BackendAdapter
    from ovwidgets.content.bookmarks import BookmarksManager


# Icon URLs resolved once at import time. ovui's ``ui.Image(source_url)``
# goes through stb_image and can drop draws on decode retry; the reliable
# path is a cached :class:`ui.RasterImageProvider` pointed at the
# absolute filesystem path returned by :func:`get_icon_path`. Mirrors
# :mod:`filter_button` / :mod:`browser_bar`.
_ICON_HOLLOW_PATH = get_icon_path("content_bookmark")
_ICON_FILLED_PATH = get_icon_path("content_bookmark_filled")


# Cached providers keyed by absolute path. Shared across button
# instances so a second widget build (e.g. tab switch) does not
# re-decode the PNGs. Duplicated from :mod:`filter_button` to keep the
# module boundary closed; a future extraction into
# :mod:`ovwidgets.app.ui_utils` would fold the caches together.
_PROVIDER_CACHE: Dict[str, "ui.RasterImageProvider"] = {}


def _provider(path: str) -> "ui.RasterImageProvider":
    """Return a cached :class:`ui.RasterImageProvider` for ``path``."""
    prov = _PROVIDER_CACHE.get(path)
    if prov is None:
        prov = ui.RasterImageProvider(path)
        _PROVIDER_CACHE[path] = prov
    return prov


# Button sizing. 28×28 matches :class:`BrowserBar`'s nav buttons and
# :class:`FilterButton` so the three toolbar buttons read as a single
# row. 16-px glyph inside a 28-px slot leaves ~6 px of padding around
# the icon — the Stage Browser toolbar convention.
_BUTTON_WIDTH = 28
_BUTTON_HEIGHT = 28
_BUTTON_ICON_SIZE = 16


# ``ConfirmDeleteDialog`` renders the listed URL under a destructive-
# red "This cannot be undone" banner. That reads too harshly for
# "remove this bookmark" — the user is not losing data; they are
# removing a shortcut. A dedicated prompt string overrides the banner
# via a :meth:`ConfirmDeleteDialog`-API extension would be cleaner, but
# the Step 45 scope keeps the dialog surface stable — we repurpose the
# dialog as-is because its Yes / No affordance is exactly what the
# remove flow needs. The URL list body doubles as the "what are you
# removing" preview. A future step can rename the dialog to
# ``ConfirmDestructiveDialog`` with a customisable banner once a third
# caller (e.g. Clear Recent Files) shows up.
_REMOVE_STATUS_REMOVED = "Removed bookmark '{name}'"
_ADD_STATUS_ADDED = "Added bookmark '{name}'"
_WARN_EMPTY_NAME = "Bookmark name cannot be empty"
_ADD_DIALOG_TITLE = "Add Bookmark"
_ADD_DIALOG_PROMPT = "Bookmark name:"


class BookmarkButton:
    """Toolbar star-icon button bound to the current folder's bookmark state.

    Constructor takes the optional :class:`BookmarksManager`, a
    backend reference (for the ``basename`` used as the default
    bookmark name), and the initial URL. The button builds itself
    immediately into the surrounding ``with`` block — same contract
    as :class:`BrowserBar` / :class:`FilterButton` / :class:`ZoomBar`.

    A ``None`` manager still renders the button so the toolbar layout
    stays pixel-identical across sessions with / without a manager,
    but the button disables its click handler (the click shows a
    warning via :class:`ErrorReporter`).
    """

    def __init__(
        self,
        manager: Optional["BookmarksManager"],
        backend: "BackendAdapter",
        current_url: str = "",
    ) -> None:
        self._manager: Optional["BookmarksManager"] = manager
        self._backend = backend
        self._current_url: str = current_url or ""

        # Widget refs — populated by :meth:`build`, cleared by
        # :meth:`destroy`. ``None`` before build / post-destroy so
        # callbacks guard defensively against teardown races.
        self._zstack: Optional[ui.ZStack] = None
        self._button: Optional[ui.Button] = None
        self._icon_image: Optional[ui.ImageWithProvider] = None

        # In-flight dialog refs. Held for the same strong-reference
        # reason as :attr:`FileContextMenu._input_dialog`: ovui GCs a
        # :class:`ui.Window` whose only Python reference was the
        # ``clicked_fn`` closure once that returns. Replaced on
        # subsequent invocations; :meth:`destroy` dismisses.
        self._input_dialog: Optional[SimpleInputDialog] = None
        self._confirm_dialog: Optional[ConfirmDeleteDialog] = None

        # Manager subscription. Held for the lifetime of the button so
        # the star icon keeps tracking the persisted mapping even when
        # the mutation came from another surface (context menu, a
        # future headless import). ``None`` when no manager is wired.
        self._subscription: Optional["Subscription"] = None
        if manager is not None:
            self._subscription = manager.subscribe_changed(
                self._on_manager_changed,
            )

        self.build()

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build the star button into the current build context.

        Mirrors :class:`FilterButton`'s ZStack(Button + icon) layout
        so the three toolbar buttons share a single visual rhythm —
        textless :class:`ui.Button` owns the click area,
        :class:`ui.ImageWithProvider` paints the glyph on top via a
        Spacer sandwich that centres the 16-px icon inside the 28-px
        button slot.
        """
        self._zstack = ui.ZStack(
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
        )
        with self._zstack:
            # V1 defers the bookmark UX: the add / remove dialog
            # flows work, but their on-click feedback is subtle (a
            # glyph swap + a status-bar line) and the context-menu
            # path on a folder row offers the same action with more
            # context. Ship the toolbar star disabled so the three
            # right-edge buttons (Bookmark / Filter / Options) read
            # as one deferred cluster — the context-menu "Add to
            # Bookmarks" remains the user's route to create one. The
            # ``:disabled`` styles wired in
            # :mod:`ovwidgets.content.style` gray the icon and
            # strip the hover tint.
            self._button = ui.Button(
                "",
                clicked_fn=self._on_button_clicked,
                style_type_name_override="Content.ToolBar.Button",
                enabled=False,
                tooltip="Bookmark — not yet implemented",
            )
            with ui.VStack():
                ui.Spacer()
                with ui.HStack(height=_BUTTON_ICON_SIZE):
                    ui.Spacer()
                    # Start with the icon matching the URL state so the
                    # very first frame reads correctly (no flicker from
                    # a default-then-update round-trip).
                    path = (
                        _ICON_FILLED_PATH
                        if self._is_current_bookmarked()
                        else _ICON_HOLLOW_PATH
                    )
                    self._icon_image = ui.ImageWithProvider(
                        _provider(path),
                        width=_BUTTON_ICON_SIZE,
                        height=_BUTTON_ICON_SIZE,
                        style_type_name_override=(
                            "Content.ToolBar.Button.Image"
                        ),
                    )
                    ui.Spacer()
                ui.Spacer()

    # ── Public API ───────────────────────────────────────────────────────────

    def set_current_url(self, url: str) -> None:
        """Update the URL the star reflects, repaint the icon if needed.

        Called by :class:`FileBrowserWidget` whenever the detail-pane
        root changes (drill-in, back / forward, nav-pane activation,
        apply-path). A re-entrant call with the same URL is a no-op.
        """
        next_url = url or ""
        if next_url == self._current_url:
            return
        self._current_url = next_url
        self._refresh_icon()

    @property
    def current_url(self) -> str:
        """The URL the button currently reflects (test-visible)."""
        return self._current_url

    @property
    def is_bookmarked(self) -> bool:
        """Whether :attr:`current_url` is present in the manager.

        Exposed so tests can assert the button's view of "bookmarked"
        matches the manager's authoritative mapping without peeking at
        the underlying dict.
        """
        return self._is_current_bookmarked()

    # ── Click handling ───────────────────────────────────────────────────────

    def _on_button_clicked(self) -> None:
        """Route the click to an Add or Remove flow based on current state.

        A no-manager button surfaces a user-visible warning so the
        click is not a silent no-op — the button exists in the layout
        to keep toolbar geometry stable, but the click has no
        underlying store to write to.

        A click against a blank :attr:`current_url` is a defensive
        refusal (the widget should always push a URL before the user
        can interact; the guard handles the pre-build edge).
        """
        if self._manager is None:
            ErrorReporter.show_warning(
                "Bookmarks are not available in this session",
            )
            return
        if not self._current_url:
            return
        if self._is_current_bookmarked():
            self._begin_remove_flow()
        else:
            self._begin_add_flow()

    def _begin_add_flow(self) -> None:
        """Open the name-override dialog, commit on OK.

        The default bookmark name is the backend's basename of the
        current URL — matches :meth:`FileContextMenu._begin_add_bookmark`
        so a context-menu Add and a toolbar-star Add produce the same
        result for a given folder. An empty basename (root URLs) falls
        back to the URL itself so the field is never blank on open.
        """
        if self._manager is None:
            return
        default_name = self._backend.basename(self._current_url) or (
            self._current_url
        )

        if self._input_dialog is not None:
            try:
                self._input_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._input_dialog = None

        url = self._current_url
        dialog = SimpleInputDialog(
            title=_ADD_DIALOG_TITLE,
            prompt=_ADD_DIALOG_PROMPT,
            initial_value=default_name,
            on_ok=lambda name, u=url: self._add_do(name, u),
        )
        self._input_dialog = dialog
        dialog.show()

    def _add_do(self, raw_name: str, url: str) -> None:
        """Validate ``raw_name`` and call :meth:`BookmarksManager.add`.

        Empty trimmed names are rejected with a status-bar warning;
        the user re-clicks the star to retry. Duplicate names are not
        rejected — :class:`BookmarksManager` treats ``add`` as
        "bind this name to this URL", so re-adding an existing name
        rebinds it. That matches the architecture's §13.3 intent (name
        is the primary key, URL is overwritten).
        """
        manager = self._manager
        if manager is None:
            return
        name = (raw_name or "").strip()
        if not name:
            ErrorReporter.show_warning(_WARN_EMPTY_NAME)
            return
        manager.add(name, url)
        ErrorReporter.show_success(_ADD_STATUS_ADDED.format(name=name))

    def _begin_remove_flow(self) -> None:
        """Open the confirm-remove dialog, commit on Yes.

        Looks up the name(s) bound to :attr:`current_url` in the
        manager — a URL may have been bookmarked under multiple names
        (the manager does not enforce URL uniqueness), in which case
        Yes removes every matching entry in a single click. The
        :class:`ConfirmDeleteDialog` surfaces the URL under its
        warning banner so the user sees what they are removing.
        """
        manager = self._manager
        if manager is None:
            return
        names = self._names_for_current_url()
        if not names:
            return
        if self._confirm_dialog is not None:
            try:
                self._confirm_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._confirm_dialog = None

        dialog = ConfirmDeleteDialog(
            urls=[self._current_url],
            on_yes=lambda ns=list(names): self._remove_do(ns),
        )
        self._confirm_dialog = dialog
        dialog.show()

    def _remove_do(self, names: list) -> None:
        """Remove every bookmark in ``names`` and post a status line.

        Each name fires an independent :meth:`BookmarksManager.remove`;
        the aggregate status-bar line names the first removed bookmark
        for a single-entry remove (the common case) and the count for
        a multi-entry remove.
        """
        manager = self._manager
        if manager is None:
            return
        removed = 0
        last_name = ""
        for name in names:
            if name in manager.list():
                manager.remove(name)
                removed += 1
                last_name = name
        if removed == 0:
            return
        if removed == 1:
            ErrorReporter.show_success(
                _REMOVE_STATUS_REMOVED.format(name=last_name),
            )
        else:
            ErrorReporter.show_success(
                f"Removed {removed} bookmarks",
            )

    # ── State queries ────────────────────────────────────────────────────────

    def _is_current_bookmarked(self) -> bool:
        """``True`` when :attr:`current_url` appears in the manager.

        URL comparison is straight equality — the architecture stores
        the URL exactly as the user / caller provided it, and the
        add-bookmark flows already push the normalised URL so the
        comparison is stable across surfaces.
        """
        if self._manager is None or not self._current_url:
            return False
        return self._current_url in self._manager.list().values()

    def _names_for_current_url(self) -> list:
        """Return every bookmark name bound to :attr:`current_url`.

        Multiple names may point at the same URL (the manager's API
        binds on name, not URL); the remove flow fires once per name.
        Returns a fresh list so callers cannot mutate the manager's
        internal state through the return value.
        """
        if self._manager is None or not self._current_url:
            return []
        return [
            name
            for name, url in self._manager.list().items()
            if url == self._current_url
        ]

    # ── Reactivity ───────────────────────────────────────────────────────────

    def _on_manager_changed(self) -> None:
        """Refresh the icon when the manager's mapping changes.

        Bound into the manager's subscription at construction. The
        subscription fires on every successful ``add`` / ``remove`` /
        ``rename`` — including a mutation against a URL that is not
        the one this button currently reflects. Dropping through to
        :meth:`_refresh_icon` unconditionally is cheaper than a
        diff check and avoids the "stale icon after indirect update"
        bug that a filter would invite.
        """
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        """Repaint the button with the current-state icon.

        Short-circuits when the button has not been built or has been
        destroyed. Replacing the image's provider is the cheapest way
        to swap glyph — ovui keeps the underlying :class:`ui.ImageWithProvider`
        alive and just re-reads from the new provider on the next frame.
        """
        image = self._icon_image
        if image is None:
            return
        path = (
            _ICON_FILLED_PATH
            if self._is_current_bookmarked()
            else _ICON_HOLLOW_PATH
        )
        try:
            image.set_image_provider(_provider(path))
        except AttributeError:
            # Older ovui builds expose ``source_url`` instead of a
            # provider-swap setter. Falling back keeps the widget
            # functional; the icon just re-decodes the PNG each swap.
            try:
                image.source_url = path
            except Exception:  # noqa: BLE001
                # No recoverable path — the icon stays on whatever
                # glyph it had, but the button's click handler still
                # reads from the manager so functionality is intact.
                pass

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Drop widget refs, dismiss any live dialogs, cancel the subscription.

        Idempotent — the ``is not None`` guards short-circuit a second
        call, and the subscription's :meth:`cancel` is itself
        idempotent (a cancelled :class:`Subscription` is a no-op on
        further cancels).
        """
        if self._input_dialog is not None:
            try:
                self._input_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._input_dialog = None
        if self._confirm_dialog is not None:
            try:
                self._confirm_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._confirm_dialog = None
        if self._subscription is not None:
            try:
                self._subscription.cancel()
            except Exception:  # noqa: BLE001
                pass
            self._subscription = None
        self._icon_image = None
        self._button = None
        self._zstack = None
        self._manager = None
        self._backend = None  # type: ignore[assignment]

    # ── Test hooks ───────────────────────────────────────────────────────────

    def _fire_click_for_test(self) -> None:
        """Drive the click handler without dispatching a real mouse event.

        Tests construct a fresh :class:`BookmarkButton` against a real
        :class:`BookmarksManager` + fake / real backend, then call this
        method to simulate a toolbar click. The resulting dialog
        (Add / Remove) lives on :attr:`_input_dialog` /
        :attr:`_confirm_dialog` where the test can fire its own
        OK / Yes hook to complete the flow.
        """
        self._on_button_clicked()


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovwidgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_PROVIDER_CACHE)
