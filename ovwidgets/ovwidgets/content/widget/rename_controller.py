# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""RenameController — inline rename for the content browser.

See the content browser behavior (rename surface) and the content browser implementation step 33. Mirrors the ovwidgets.stage :class:`RenameController` pattern
(``ovwidgets.stage/widget/rename_controller.py``): a single object owns the
"item currently being renamed" state and the begin / commit / cancel
lifecycle. Delegates (tree + detail) and :class:`FileGridView` cards
read the active item to branch between the default Label and an
editable :class:`ui.StringField`.

Entry points:

* :meth:`begin_rename` — enter rename mode for ``item``. Invoked by the
  Rename context-menu entry and by F2 (via
  :meth:`FileBrowserWidget.begin_rename_selected`).
* :meth:`commit_rename` — called from the StringField's Enter key or
  end-edit callback with the typed string. Validates, calls
  :meth:`BackendAdapter.move` with ``old_url`` → ``new_url``, and
  refreshes both pane models so the new name surfaces on the next
  render.
* :meth:`cancel_rename` — called from the StringField's Escape key.
  Exits rename mode without a backend round-trip.

Validation rejections and backend failures surface through
:class:`ovwidgets.common.error_reporter.ErrorReporter` using the same warning /
error split the Step 32 Create Folder flow landed: validation uses
``show_warning`` (user mistake, yellow status-bar line) and backend
failures use ``show_error`` (system-side problem, red).

The controller is backend-aware but widget-centric — it holds a
forward-typed ref to :class:`FileBrowserWidget` so it can reach both
models, both delegates, and the grid view. A backend-only rename path
is not exposed; the widget's composition gives us the refresh fan-out
we need for free and keeps the rename flow inside a single module
rather than plumbing callbacks through every view.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from ovwidgets.common.error_reporter import ErrorReporter
from ovwidgets.content.backends.backend_adapter import BackendResult
from ovwidgets.content.widget.file_item import FileItem

if TYPE_CHECKING:
    from ovwidgets.content.widget.file_browser_widget import (
        FileBrowserWidget,
    )


# Validation / error messages surfaced via :class:`ErrorReporter`.
# Kept as module constants so the test module can import them verbatim
# rather than duplicating the literals (same pattern as Step 32's
# Create Folder strings).
_WARN_EMPTY_NAME = "Name cannot be empty"
_WARN_ILLEGAL_CHARS = "Name cannot contain '/' or '\\'"
_WARN_DUPLICATE_NAME = "An item with that name already exists"
_ERROR_RENAME_FAILED = "Rename failed: {reason}"

# Characters rejected in an item name. Matches the Create Folder
# contract: forward/backslash would let the user inject a sub-path
# rather than a single leaf rename, which the backend either silently
# creates intermediate folders for (POSIX ``shutil.move``) or errors
# cryptically on (Windows).
_ILLEGAL_NAME_CHARS = ("/", "\\")


class RenameController:
    """Coordinates inline rename across tree delegate, detail delegate, and grid.

    Constructor takes the owning :class:`FileBrowserWidget`; forward-
    typed so importing this module does not pull the widget module in.
    The controller reads the widget's ``_backend`` / ``_tree_model`` /
    ``_detail_model`` / ``_tree_delegate`` / ``_detail_delegate`` /
    ``_detail_grid_view`` attributes — all of which exist for the
    lifetime of the widget and are nulled together on
    :meth:`FileBrowserWidget.destroy`.

    State machine:

    * **Idle** — ``_active_item is None``. :meth:`begin_rename` moves
      to Active.
    * **Active** — ``_active_item is <FileItem>``. The name column for
      that item paints a :class:`ui.StringField` instead of a label
      on the next render. :meth:`commit_rename` / :meth:`cancel_rename`
      / :meth:`destroy` move back to Idle.

    Only one rename can be in flight at a time — a second
    :meth:`begin_rename` while Active first cancels the existing one.
    """

    def __init__(self, widget: "FileBrowserWidget") -> None:
        self._widget: Optional["FileBrowserWidget"] = widget
        # The single item currently being renamed (``None`` when idle).
        # A set-based API would allow concurrent renames on multiple
        # items, but the plan (§27.2) specifies one-at-a-time: the
        # caller cancels an existing rename before starting a new one,
        # matching the ovwidgets.stage surface.
        self._active_item: Optional[FileItem] = None

    # ── Public API ──────────────────────────────────────────────────────

    @property
    def active_item(self) -> Optional[FileItem]:
        """The item currently being renamed, or ``None`` when idle."""
        return self._active_item

    def is_renaming(self, item: Any) -> bool:
        """``True`` if ``item`` is the active rename target.

        Delegates and cards call this on every build pass to decide
        whether to paint a :class:`ui.StringField` or the default label.
        Non-:class:`FileItem` arguments and the idle case both return
        ``False``.
        """
        if self._active_item is None:
            return False
        if not isinstance(item, FileItem):
            return False
        return item is self._active_item

    def begin_rename(self, item: FileItem) -> None:
        """Enter rename mode for ``item``.

        Refuses ``None`` / non-:class:`FileItem` arguments and
        post-destroy invocations silently. Cancels any in-flight
        rename first so the previous StringField closes before the new
        one opens — two live rename fields would race for focus and
        one would silently lose its typed content.

        After the state flip, every view that renders ``item`` is
        invalidated via :meth:`_invalidate_item` so the next draw picks
        up the new mode. The StringField materialises on that draw.
        """
        widget = self._widget
        if widget is None:
            return
        if not isinstance(item, FileItem):
            return
        # Cancel any prior rename before starting a new one.
        if self._active_item is not None and self._active_item is not item:
            self.cancel_rename()
        self._active_item = item
        self._invalidate_item(item)

    def commit_rename(self, raw_name: str) -> None:
        """Validate ``raw_name``, invoke :meth:`BackendAdapter.move`, refresh.

        Validation sequence (the content browser implementation step 33 / Step 32 parity):

        1. Strip leading / trailing whitespace.
        2. Empty → warn + exit rename mode.
        3. Contains ``/`` or ``\\`` → warn + exit rename mode.
        4. Same as current name → exit rename mode (no-op, no backend
           call — not an error).
        5. A sibling already carries this name → warn + exit rename mode.
        6. Call :meth:`BackendAdapter.move` with the source URL and the
           destination URL built by :meth:`BackendAdapter.join_url`
           against the parent. Non-``OK`` → error + exit rename mode.
        7. On ``OK`` → refresh both models so the renamed entry
           surfaces under its new name, then exit rename mode.

        The duplicate check is advisory — the backend's
        :attr:`BackendResult.ERROR_ALREADY_EXISTS` is the authoritative
        signal when the cache is stale (out-of-band rename on disk).
        Client-side detection just produces a snappier message for the
        common cached-hit case. Ordering is empty → illegal-char →
        same → duplicate → backend, matching specificity.
        """
        if self._active_item is None:
            return
        widget = self._widget
        if widget is None:
            self._active_item = None
            return

        item = self._active_item

        name = (raw_name or "").strip()
        if not name:
            ErrorReporter.show_warning(_WARN_EMPTY_NAME)
            self._end_rename(item)
            return
        if any(ch in name for ch in _ILLEGAL_NAME_CHARS):
            ErrorReporter.show_warning(_WARN_ILLEGAL_CHARS)
            self._end_rename(item)
            return
        if name == item.name:
            # No-op rename — exit cleanly without bothering the backend.
            self._end_rename(item)
            return

        backend = getattr(widget, "_backend", None)
        if backend is None:
            self._end_rename(item)
            return

        # Resolve the parent's cached :class:`FileItem` in the detail
        # model so the duplicate check sees the same set of siblings the
        # user sees on screen. Parent may be ``None`` when the item is
        # the cache root — rename on root is refused below by the
        # backend's ``move`` call (its ``parent_url`` returns ``None``).
        parent_item: Optional[FileItem] = item.parent
        if parent_item is not None:
            existing = {child.name for child in parent_item.children
                        if child is not item}
            if name in existing:
                ErrorReporter.show_warning(_WARN_DUPLICATE_NAME)
                self._end_rename(item)
                return

        src_url = item.url
        parent_url = backend.parent_url(src_url)
        if parent_url is None:
            # Cannot rename a storage root — no parent to build the new
            # URL against. Surface as a generic failure; the user
            # shouldn't be able to reach this state through the context
            # menu (the root is not a :class:`FileItem`) but F2 on a
            # scripted selection could.
            ErrorReporter.show_error(
                _ERROR_RENAME_FAILED.format(reason="ERROR"),
            )
            self._end_rename(item)
            return
        dst_url = backend.join_url(parent_url, name)

        result = backend.move(src_url, dst_url)
        if result != BackendResult.OK:
            ErrorReporter.show_error(
                _ERROR_RENAME_FAILED.format(reason=result.name),
            )
            self._end_rename(item)
            return

        # Success — exit rename mode first so the next refresh pass
        # paints the renamed row with its fresh label rather than a
        # still-live StringField that would repaint stale text. Then
        # refresh both models so the old :class:`FileItem` is replaced
        # by a fresh one bearing the new name / URL.
        self._end_rename(item)
        self._refresh_parent_after_rename(parent_url)

    def cancel_rename(self) -> None:
        """Exit rename mode without a backend round-trip.

        Wired to the Escape keypress on the StringField and to lifecycle
        teardown paths. Idempotent — a second call while idle is a no-op.
        """
        if self._active_item is None:
            return
        item = self._active_item
        self._end_rename(item)

    def destroy(self) -> None:
        """Release the widget ref and clear any active rename.

        Idempotent — a second call is a silent no-op via the ``None``
        guard on :attr:`_widget`. Called from
        :meth:`FileBrowserWidget.destroy` before the widget drops its
        own references so the controller's last call to
        :meth:`_invalidate_item` still reaches live delegates.
        """
        if self._active_item is not None and self._widget is not None:
            # Silent exit — a widget teardown mid-rename is a normal
            # shutdown sequence, not a user-visible cancel.
            self._invalidate_item(self._active_item)
        self._active_item = None
        self._widget = None

    # ── Internals ───────────────────────────────────────────────────────

    def _end_rename(self, item: FileItem) -> None:
        """Reset to idle and invalidate the item's views.

        Split out so the branches of :meth:`commit_rename` and
        :meth:`cancel_rename` share a single exit path. ``item`` is
        passed explicitly (rather than read from
        :attr:`_active_item`) because callers sometimes want to
        invalidate the pre-rename item after :attr:`_active_item` has
        already been nulled.
        """
        self._active_item = None
        self._invalidate_item(item)

    def _invalidate_item(self, item: FileItem) -> None:
        """Force every view to re-render ``item``'s row / card.

        Dispatches :meth:`ui.AbstractItemModel._item_changed` on both
        tree and detail models so each TreeView re-queries the row. For
        the grid view we rebuild the single card in place if we can
        find it; otherwise we fall back to a full grid refresh. The
        grid's ``_cards`` dict is keyed by URL, so a pre-rename lookup
        matches before the URL changes (rename success triggers a
        model-level refresh that rebuilds the grid from scratch).
        """
        widget = self._widget
        if widget is None:
            return
        tree_model = getattr(widget, "_tree_model", None)
        detail_model = getattr(widget, "_detail_model", None)
        if tree_model is not None:
            try:
                tree_model._item_changed(item)
            except Exception:  # noqa: BLE001
                # ovui may reject dispatches for items not currently in
                # the view; swallow so the invalidation is best-effort
                # across multi-pane setups.
                pass
        if detail_model is not None:
            try:
                detail_model._item_changed(item)
            except Exception:  # noqa: BLE001
                pass
        # Grid card invalidation — a full rebuild is the simplest path
        # and mirrors what the Step 29 search-filter repaint does. The
        # :meth:`FileGridView.refresh` call is cheap at typical card
        # counts (tens to low hundreds visible at once).
        grid = getattr(widget, "_detail_grid_view", None)
        if grid is not None:
            try:
                grid.refresh()
            except Exception:  # noqa: BLE001
                pass

    def _refresh_parent_after_rename(self, parent_url: str) -> None:
        """Mark the parent dirty in both models so the renamed child re-surfaces.

        Mirrors the Step 32 Create Folder refresh path. Tries each model
        independently — a miss in one (the tree may not have walked to
        the renamed folder's parent, or vice versa) does not
        short-circuit the other. Falls back to ``refresh_all()`` on the
        detail model when the parent cannot be resolved there (e.g. the
        rename happened in a folder outside the currently-rooted
        subtree after a race).
        """
        widget = self._widget
        if widget is None:
            return
        detail_model = getattr(widget, "_detail_model", None)
        if detail_model is not None:
            parent_item = detail_model.resolve(parent_url)
            if parent_item is not None:
                detail_model.refresh_item(parent_item)
            else:
                refresh_all = getattr(detail_model, "refresh_all", None)
                if refresh_all is not None:
                    refresh_all()
        tree_model = getattr(widget, "_tree_model", None)
        if tree_model is not None:
            tree_parent = tree_model.resolve(parent_url)
            if tree_parent is not None:
                tree_model.refresh_item(tree_parent)
