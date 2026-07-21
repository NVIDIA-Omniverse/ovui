# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FileContextMenu — right-click menus for files, folders, empty space.

See the content browser behavior (menu dispatch rules) / §26
(registration API) and the content browser implementation step 31 / Step 32. The menu
replaces Kit's ``omni.kit.widget.context_menu`` service with a direct
:class:`ui.Menu` driver — ovgear's extension model is flat enough that
the service-layer indirection Kit uses doesn't buy us anything. The
callback shape (``onclick_fn(item)`` + ``show_fn(item) -> bool``)
mirrors what Kit exposes at the edges so a future port lands cleanly.

Menu items are grouped by the right-clicked target:

* **File** — Open, Copy URL, Cut, Copy, Paste (only when clipboard has
  items AND target is a folder — files receive Paste via their parent),
  Rename, Delete.
* **Folder** — Open (drill in), Create Folder, Cut, Copy, Paste (when
  clipboard has items), Add Bookmark, Rename, Delete.
* **Empty space** (right-click the grid background or the detail-pane
  overlay area when no item is under the cursor) — Create Folder,
  Paste (when clipboard has items), Refresh.

Most menu item click handlers are stubs at this step: the real file
ops arrive in Steps 33–37 (rename, delete, clipboard, paste).
Stubs route through :class:`ovui_widgets.common.error_reporter.ErrorReporter` so the
user sees a status-bar line when the action is invoked, giving a
visible signal that the wiring is live even before the backing ops
land.

**Step 32 — Create Folder** is the first stub replaced with a real
operation. Both the folder-target "Create Folder" entry and the empty-
space "Create Folder" entry now drive :class:`SimpleInputDialog` to
collect a name, validate it (empty / duplicate / illegal characters),
and call :meth:`BackendAdapter.create_folder` against the chosen parent
URL. The detail and tree models are refreshed on success so the new
folder appears without a manual reload.

Plug-in registration mirrors the architecture's ``add_context_menu``
surface (§26.1): :meth:`FileContextMenu.register_item` takes a name,
icon glyph / path (or ``None``), click callback, and optional
``show_fn`` predicate. Registered items always append to the end of
whichever target-specific menu they apply to — :meth:`register_item`
does not currently distinguish target kinds (file / folder / empty)
because the Step 31 caller surface is "show me on every menu"; a
future step can add a ``contexts`` kwarg when the first plug-in needs
to scope its entries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, List, Optional

import omni.ui as ui

from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.common.menu import create_flat_menu
from ovui_widgets.content.backends.backend_adapter import BackendResult
from ovui_widgets.content.widget import clipboard, file_ops
from ovui_widgets.content.widget.confirm_delete_dialog import (
    ConfirmDeleteDialog,
)
from ovui_widgets.content.widget.confirm_overwrite_dialog import (
    ConfirmOverwriteDialog,
    OverwriteChoice,
)
from ovui_widgets.content.widget.file_item import FileItem
from ovui_widgets.content.widget.simple_input_dialog import (
    SimpleInputDialog,
)

if TYPE_CHECKING:
    from ovui_widgets.content.widget.file_browser_widget import (
        FileBrowserWidget,
    )

# ``Create Folder`` dialog strings. Module constants so the test module
# can import and assert against them verbatim rather than duplicating
# the literals.
_NEW_FOLDER_DIALOG_TITLE = "New Folder"
_NEW_FOLDER_DIALOG_PROMPT = "Name:"
_NEW_FOLDER_DIALOG_DEFAULT = "New Folder"

# Validation / error messages surfaced via
# :class:`ErrorReporter`. Keeping them as constants makes the dialog
# flow + tests speak the same language without magic strings.
_WARN_EMPTY_NAME = "Folder name cannot be empty"
_WARN_DUPLICATE_NAME = "A folder with that name already exists"
_WARN_ILLEGAL_CHARS = "Folder name cannot contain '/' or '\\'"
_ERROR_CREATE_FAILED = "Create folder failed: {reason}"

# Step 34 — Delete messages surfaced via :class:`ErrorReporter`.
# ``_ERROR_DELETE_FAILED`` is formatted with the offending URL + the
# backend result name so the user sees exactly which item could not be
# deleted when a multi-delete partially succeeds. ``_STATUS_DELETE_DONE``
# reports the successful-count on a clean completion; the status-bar
# message closes the loop for the user without stacking an extra
# notification dialog.
_ERROR_DELETE_FAILED = "Delete failed: {url} ({reason})"
_STATUS_DELETE_DONE_SINGLE = "Deleted 1 item"
_STATUS_DELETE_DONE_MULTI = "Deleted {count} items"

# Step 36 — Copy / Cut / Paste messages. Each follows the Delete
# vocabulary so status-bar readouts across content-browser ops read
# consistently. The Paste paths branch on whether the clipboard was
# Copy (``Copied``) or Cut (``Moved``) because the user's mental model
# differs — Copy leaves the source; Cut removes it.
_STATUS_COPIED_SINGLE = "Copied 1 item"
_STATUS_COPIED_MULTI = "Copied {count} items"
_STATUS_MOVED_SINGLE = "Moved 1 item"
_STATUS_MOVED_MULTI = "Moved {count} items"
_STATUS_CUT_SINGLE = "Cut 1 item"
_STATUS_CUT_MULTI = "Cut {count} items"
_STATUS_CLIPBOARD_COPIED_SINGLE = "Copied 1 item to clipboard"
_STATUS_CLIPBOARD_COPIED_MULTI = "Copied {count} items to clipboard"
_ERROR_COPY_FAILED = "Copy failed: {url} ({reason})"
_ERROR_MOVE_FAILED = "Move failed: {url} ({reason})"
_WARN_NOTHING_TO_PASTE = "Clipboard is empty"
_WARN_NO_PASTE_DESTINATION = "No destination folder for paste"

# Step 37 — Duplicate / Open in Native / Copy URL. Same vocabulary
# convention as the other file-op status lines: single/plural templates,
# per-URL error lines on failure, and an end-of-batch success line on
# the happy path. ``_WARN_NATIVE_BROWSER_UNAVAILABLE`` fires when the
# OS launcher refuses (missing ``xdg-open``, non-local URL slipped past
# the ``show_fn`` gate, etc.) so the user sees a signal instead of a
# silent no-op.
_STATUS_DUPLICATED_SINGLE = "Duplicated 1 item"
_STATUS_DUPLICATED_MULTI = "Duplicated {count} items"
_ERROR_DUPLICATE_FAILED = "Duplicate failed: {url} ({reason})"
_WARN_NATIVE_BROWSER_UNAVAILABLE = (
    "Open in native browser is not available for this URL"
)

# Step 45 — Add / Remove Bookmark. The Add Bookmark dialog reuses the
# generic :class:`SimpleInputDialog` surface (create-folder / rename
# share the same chrome) with the bookmarks-specific title / prompt
# constants below. Status-bar lines follow the existing vocabulary
# convention — a short aggregate line on success, no per-bookmark
# detail (there is never more than one bookmark per click).
_ADD_BOOKMARK_DIALOG_TITLE = "Add Bookmark"
_ADD_BOOKMARK_DIALOG_PROMPT = "Bookmark name:"
_STATUS_BOOKMARK_ADDED = "Added bookmark '{name}'"
_STATUS_BOOKMARK_REMOVED = "Removed bookmark '{name}'"
_WARN_BOOKMARK_NO_MANAGER = "Bookmarks are not available in this session"
_WARN_BOOKMARK_EMPTY_NAME = "Bookmark name cannot be empty"

# Characters rejected in folder names. Forward slash and backslash are
# the universal path-separator pair — accepting either here would let
# the user inject a sub-path rather than a single folder name, which
# is either (a) a silent ``os.makedirs`` on POSIX if the parent exists
# or (b) a cryptic ``ERROR`` on Windows. Explicit rejection avoids both.
_ILLEGAL_NAME_CHARS = ("/", "\\")


# ──────────────────────────────────────────────────────────────────────────────
# Target classifications
# ──────────────────────────────────────────────────────────────────────────────

# Canonical target kinds. ``EMPTY`` fires when a right-click lands on
# empty space (no :class:`FileItem` under the cursor); ``FILE`` and
# ``FOLDER`` are branched from ``item.is_folder``. ``BOOKMARK`` is the
# Step-45 nav-pane-specific kind — it fires when the user right-clicks
# a :class:`BookmarksCollection` child row and surfaces the
# "Remove Bookmark" entry only; none of the file-op entries (Cut, Copy,
# Paste, Rename, Delete…) make sense against a bookmark row because the
# row is a pointer to a folder, not the folder itself. Kept as module-
# level constants so the test module can import and assert against the
# exact strings without duplicating literals.
TARGET_FILE = "file"
TARGET_FOLDER = "folder"
TARGET_EMPTY = "empty"
TARGET_BOOKMARK = "bookmark"

# Stable ordering of context target kinds. Iterated by
# :meth:`FileContextMenu.register_item` when a plug-in opts its entry
# into every context (the Step-31 default). ``TARGET_BOOKMARK`` is
# deliberately absent from the registration iteration — plug-ins that
# want to add entries to the bookmark nav menu need a different surface
# (the bookmarks API is narrow; a generic plug-in hook would dilute the
# menu into a general-purpose surface it isn't meant to be).
_ALL_CONTEXTS = (TARGET_FILE, TARGET_FOLDER, TARGET_EMPTY)


class _PasteState:
    """Mutable per-batch state for the iterative :meth:`FileContextMenu._paste_do`.

    Paste is **async** — each collision spawns a
    :class:`ConfirmOverwriteDialog` whose ``on_response`` callback
    drives the next iteration. That makes a pure-function loop
    unworkable; the loop state has to live somewhere that survives
    between dialog dismissals. Encapsulating it in a small dataclass-
    style helper keeps the state handoff explicit and gives the test
    module a single attribute to inspect (``menu._paste_state``) when
    it drives the flow step-by-step.

    Fields:

    * ``remaining`` — URLs still to process (popped from the left as
      each iteration completes).
    * ``dst_parent_url`` — the folder everything pastes into; kept
      fixed across the batch so all URLs resolve against the same
      parent (the Paste target at the moment the menu fired).
    * ``is_cut`` — clipboard mode snapshotted at batch start.
      :func:`clipboard.is_clipboard_cut` is read once so a
      ``save_to_clipboard`` call from outside mid-paste cannot flip
      the batch from Copy→Move mid-flight.
    * ``overwrite_all`` — tri-state per-batch decision:
      ``None`` = still asking on each collision, ``True`` = Yes-to-All
      chosen, ``False`` = No-to-All chosen.
    * ``success_count`` / ``errors`` — tallies for the post-batch
      status-bar message. Errors collect as ``(url, result_name)``
      pairs so the reporter can surface them verbatim at batch end.
    * ``refreshed_parents`` — URL set of folders whose detail-model /
      tree-model refresh has already been dispatched, so a multi-item
      paste only refreshes the parent once. Populated post-batch
      rather than per-iteration because a single folder's repaint can
      be expensive on a large tree; batching the refreshes to end-of-
      batch keeps the paste loop tight.
    """

    __slots__ = (
        "remaining",
        "dst_parent_url",
        "is_cut",
        "overwrite_all",
        "success_count",
        "errors",
        "refreshed_parents",
    )

    def __init__(
        self,
        remaining: List[str],
        dst_parent_url: str,
        is_cut: bool,
    ) -> None:
        self.remaining: List[str] = list(remaining)
        self.dst_parent_url: str = dst_parent_url
        self.is_cut: bool = bool(is_cut)
        self.overwrite_all: Optional[bool] = None
        self.success_count: int = 0
        self.errors: List[tuple] = []
        self.refreshed_parents: set = set()


class _MenuItemSpec:
    """Spec for a single menu entry — built-in or plug-in registered.

    Holds the display ``name``, optional ``icon`` glyph / URL (used by
    :class:`ui.MenuItem`'s ``glyph`` kwarg when non-``None``), a
    ``click_fn(item)`` invoked on activation, and an optional
    ``show_fn(item) -> bool`` predicate that hides the entry when it
    returns ``False``. ``item`` is the right-clicked :class:`FileItem`
    for the FILE / FOLDER contexts and ``None`` for EMPTY.

    Kept as a small class rather than a plain tuple so the four fields
    have stable names the test module can reach for (``spec.name``,
    ``spec.icon``, …) rather than positional indexes.
    """

    __slots__ = ("name", "icon", "click_fn", "show_fn")

    def __init__(
        self,
        name: str,
        icon: Optional[str],
        click_fn: Callable[[Optional[FileItem]], None],
        show_fn: Optional[Callable[[Optional[FileItem]], bool]] = None,
    ) -> None:
        self.name = name
        self.icon = icon
        self.click_fn = click_fn
        self.show_fn = show_fn


class FileContextMenu:
    """Right-click context-menu dispatcher for the content browser.

    Constructor takes the owning :class:`FileBrowserWidget` — forward-
    referenced via :mod:`typing.TYPE_CHECKING` so importing this module
    does not pull the widget module in. The widget reference is used
    by the built-in stub actions (e.g. Refresh invokes
    ``widget._detail_model.refresh_all()``) and by future-step ops.

    The menu is built fresh on every :meth:`show` call — the list of
    visible entries depends on the right-clicked target kind and on
    plug-in ``show_fn`` predicates. An always-rebuilt menu is cheap
    enough at human-click rates (tens of entries at most) and avoids
    the book-keeping a cached-menu approach would need for predicate
    re-evaluation.
    """

    def __init__(self, widget: "FileBrowserWidget") -> None:
        self._widget: Optional["FileBrowserWidget"] = widget
        # Plug-in registrations — :class:`_MenuItemSpec` list. Every
        # registered entry appends to each target's menu by default;
        # a future step can grow :meth:`register_item` a
        # ``contexts`` kwarg when a plug-in needs to scope its entry.
        self._plugin_items: List[_MenuItemSpec] = []
        # The live :class:`ui.Menu`. Held as an attribute so Python
        # doesn't GC the popup out from under the user — ovui closes a
        # menu whose last Python reference is dropped (same surface as
        # :class:`ovui_widgets.property.parts.attr_context_menu`). Replaced on
        # every :meth:`show` call; the prior menu's popup is already
        # dismissed by the time a new one is built.
        self._menu: Optional[ui.Menu] = None
        # Step 32: the live Create-Folder dialog (if any). Held so the
        # popup survives the ``clicked_fn`` dispatch that spawned it —
        # without a strong reference the :class:`ui.Window` would be
        # collected after the handler returns. Replaced on subsequent
        # invocations; ``destroy()`` clears it.
        self._input_dialog: Optional[SimpleInputDialog] = None
        # Step 34: the live Confirm Delete dialog (if any). Held for the
        # same strong-reference reason as ``_input_dialog`` — ovui GCs
        # a :class:`ui.Window` whose only Python reference was the
        # ``clicked_fn`` closure once that returns. Replaced on
        # subsequent Delete invocations; ``destroy()`` dismisses.
        self._confirm_delete_dialog: Optional[ConfirmDeleteDialog] = None
        # Step 36: the live Confirm Overwrite dialog (if any). Paste
        # spawns one instance per collision (once per item that
        # :attr:`BackendResult.ERROR_ALREADY_EXISTS`) until the user
        # picks a ``*_TO_ALL`` choice that short-circuits the prompt.
        # Held for the same strong-reference reason as
        # ``_confirm_delete_dialog``; ``destroy()`` dismisses.
        self._confirm_overwrite_dialog: Optional[ConfirmOverwriteDialog] = (
            None
        )
        # Step 36: paste iteration state. Populated when
        # :meth:`_paste_do` begins; mutated as the iterative flow
        # consumes URLs, dialogs, and user decisions. ``None`` when no
        # paste is in flight — guards against re-entrancy from a
        # context-menu click that lands mid-paste.
        self._paste_state: Optional[_PasteState] = None

    # ── Public surface ───────────────────────────────────────────────────

    def show(
        self,
        x: float,
        y: float,
        item: Optional[FileItem],
    ) -> Optional[ui.Menu]:
        """Build and pop the context menu at ``(x, y)`` for ``item``.

        ``item`` branches the dispatch:

        * ``None`` → empty-space menu (Create Folder, Paste, Refresh).
        * ``is_folder=True`` → folder menu.
        * ``is_folder=False`` → file menu.

        Returns the built :class:`ui.Menu` so callers (and tests) can
        hold onto it for the duration of the show. Post-:meth:`destroy`
        the call short-circuits to ``None`` so a late callback (e.g.
        a queued mouse-pressed dispatch from the delegate that fires
        after the widget tore down) cannot crash.
        """
        if self._widget is None:
            return None
        target = self._target_for(item)
        specs = self._specs_for(target, item)

        menu = create_flat_menu()
        with menu:
            for spec in specs:
                # Build a fresh :class:`ui.MenuItem` per spec. The
                # ``triggered_fn`` closure captures ``spec`` by default
                # argument so late binding in the loop cannot route a
                # click to the wrong entry. ``glyph`` is a keyword-only
                # arg on :class:`ui.MenuItem`; passing an empty string
                # would render an empty glyph slot, so the
                # conditional-kwargs dict pattern keeps the slot
                # absent when the spec carries no icon.
                kwargs: dict = {}
                if spec.icon:
                    kwargs["glyph"] = spec.icon
                ui.MenuItem(
                    spec.name,
                    triggered_fn=(
                        lambda s=spec, it=item: s.click_fn(it)
                    ),
                    **kwargs,
                )
        menu.show_at(float(x), float(y))
        self._menu = menu
        return menu

    def register_item(
        self,
        name: str,
        icon: Optional[str],
        click_fn: Callable[[Optional[FileItem]], None],
        show_fn: Optional[Callable[[Optional[FileItem]], bool]] = None,
    ) -> None:
        """Register a plug-in menu entry.

        ``name`` — display string. ``icon`` — optional glyph / URL
        passed through to :class:`ui.MenuItem.glyph`; ``None`` skips
        the glyph slot. ``click_fn(item)`` — invoked on activation;
        the clicked :class:`FileItem` or ``None`` for EMPTY context.
        ``show_fn(item) -> bool`` — optional predicate evaluated at
        :meth:`show` time; a falsy return hides the entry from that
        invocation without affecting subsequent shows.

        The entry appears in every target-kind menu by default
        (file / folder / empty) — Kit's ``add_context_menu`` has the
        same behaviour at §26.1. A future step can add a ``contexts``
        kwarg when the first plug-in needs to scope its entry to one
        target kind only.

        Duplicate ``name`` registrations are allowed — the menu simply
        renders two entries with the same label. The caller owns
        de-duplication if it matters to them; rejecting duplicates
        would couple plug-in authors to each other's entry names.
        """
        self._plugin_items.append(
            _MenuItemSpec(
                name=name,
                icon=icon,
                click_fn=click_fn,
                show_fn=show_fn,
            ),
        )

    def destroy(self) -> None:
        """Release the widget ref and drop any live menu.

        Idempotent — a second call is a silent no-op via the ``None``
        guard on :attr:`_widget`. The live menu (if any) is hidden
        first so an in-flight popup animation completes cleanly before
        the reference is dropped.
        """
        if self._menu is not None:
            try:
                self._menu.hide()
            except Exception:  # noqa: BLE001
                # ovui raises if the C++ menu was already torn down
                # under us; swallowing here keeps destroy idempotent.
                pass
            self._menu = None
        # Step 32: dismiss any in-flight input dialog before dropping
        # the widget ref so the dialog's teardown runs with a live
        # widget still reachable (some handlers may introspect it).
        if self._input_dialog is not None:
            try:
                self._input_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._input_dialog = None
        # Step 34: same teardown path for the confirm-delete dialog.
        if self._confirm_delete_dialog is not None:
            try:
                self._confirm_delete_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._confirm_delete_dialog = None
        # Step 36: tear down any live overwrite-confirm dialog and
        # cancel any in-flight paste. Dropping ``_paste_state`` clears
        # the iterative loop so a dialog callback that sneaks through
        # teardown finds ``_widget is None`` and short-circuits.
        if self._confirm_overwrite_dialog is not None:
            try:
                self._confirm_overwrite_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._confirm_overwrite_dialog = None
        self._paste_state = None
        self._plugin_items = []
        self._widget = None

    # ── Internals ────────────────────────────────────────────────────────

    @staticmethod
    def _target_for(item: Optional[FileItem]) -> str:
        """Classify ``item`` into one of the three target kinds."""
        if item is None:
            return TARGET_EMPTY
        if item.is_folder:
            return TARGET_FOLDER
        return TARGET_FILE

    def _specs_for(
        self, target: str, item: Optional[FileItem]
    ) -> List[_MenuItemSpec]:
        """Return the spec list for ``target``, filtered by ``show_fn``.

        Built-ins first, then every plug-in whose predicate passes
        (or lacks one) — registration order within each bucket is
        preserved so a plug-in author can rely on their entry
        appearing after whatever they registered previously.

        ``show_fn`` applies to **both** built-ins and plug-ins (Step 37
        onwards). The "Open in Native File Browser" folder entry uses
        a ``show_fn`` to hide itself for non-local URLs rather than
        adding per-target conditional branches in
        :meth:`_folder_specs`; honouring the predicate on built-ins
        keeps that spec a single self-contained declaration.
        """
        builtins: List[_MenuItemSpec] = []
        if target == TARGET_FILE:
            builtins = self._file_specs()
        elif target == TARGET_FOLDER:
            builtins = self._folder_specs()
        elif target == TARGET_EMPTY:
            builtins = self._empty_specs()

        visible: List[_MenuItemSpec] = []
        for spec in builtins:
            if spec.show_fn is None or bool(spec.show_fn(item)):
                visible.append(spec)
        # Plug-in entries attach to every target kind *except* the
        # bookmark nav menu — see the :data:`TARGET_BOOKMARK` comment
        # for the scoping rationale. ``_specs_for`` is not called with
        # ``TARGET_BOOKMARK`` from any current caller (the bookmark
        # menu path goes through :meth:`show_bookmark_menu`), but guard
        # defensively in case a future refactor unifies the entry points.
        if target != TARGET_BOOKMARK:
            for spec in self._plugin_items:
                if spec.show_fn is None or bool(spec.show_fn(item)):
                    visible.append(spec)
        return visible

    # ── Built-in menu specs (stubs — wired in Steps 33-37) ───────────────

    def _file_specs(self) -> List[_MenuItemSpec]:
        """File menu: Open, Copy URL, Cut, Copy, Duplicate, Rename, Delete.

        Step 36: Paste is intentionally absent on a file target — the
        user pastes *into* a folder, not onto a file. The
        the content browser behavior flow routes a file-target
        Paste through the parent folder (the same folder the file
        sits in), which is what the empty-space / folder entries
        cover. Hiding the Paste entry on files keeps the menu honest
        — a visible entry that did something surprising (paste into
        the containing folder) would surprise more users than the
        missing entry does.

        Step 37: ``Copy URL`` is now wired (was a stub) and
        ``Duplicate`` joins the file menu. Both sit next to ``Copy``
        because they share the "make a thing from this thing"
        semantics — Copy writes to the clipboard, Duplicate
        short-circuits Copy+Paste into the same folder, Copy URL
        exports the URL string.
        """
        return [
            _MenuItemSpec(
                "Open", None, lambda it: self._stub("Open", it),
            ),
            _MenuItemSpec(
                "Copy URL", None, lambda it: self._copy_url(it),
            ),
            _MenuItemSpec(
                "Cut", None, lambda it: self._cut_items([it] if it else []),
            ),
            _MenuItemSpec(
                "Copy", None, lambda it: self._copy_items([it] if it else []),
            ),
            _MenuItemSpec(
                "Duplicate", None,
                lambda it: self._duplicate_items([it] if it else []),
            ),
            _MenuItemSpec(
                "Rename", None, lambda it: self._begin_rename(it),
            ),
            _MenuItemSpec(
                "Delete", None, lambda it: self._begin_delete(it),
            ),
        ]

    def _folder_specs(self) -> List[_MenuItemSpec]:
        """Folder menu: Open, Open in Native File Browser (local only),
        Copy URL, Create Folder, Cut, Copy, Paste, Duplicate,
        Add Bookmark, Rename, Delete.

        Step 37: ``Open in Native File Browser`` appears only when the
        folder URL is a local-FS URL — the OS native file manager
        can't open a ``mock://`` or ``omniverse://`` URL, so hiding
        the entry avoids a user click that would silently refuse.
        ``Copy URL`` and ``Duplicate`` are added here too so a folder
        gets the same convenience pair as a file.
        """
        return [
            _MenuItemSpec(
                "Open", None,
                lambda it: self._drill_or_stub(it),
            ),
            _MenuItemSpec(
                "Open in Native File Browser", None,
                lambda it: self._open_in_native(it),
                show_fn=lambda it: self._can_open_in_native(it),
            ),
            _MenuItemSpec(
                "Copy URL", None, lambda it: self._copy_url(it),
            ),
            _MenuItemSpec(
                "Create Folder", None,
                lambda it: self._open_create_folder_dialog(it),
            ),
            _MenuItemSpec(
                "Cut", None, lambda it: self._cut_items([it] if it else []),
            ),
            _MenuItemSpec(
                "Copy", None, lambda it: self._copy_items([it] if it else []),
            ),
            _MenuItemSpec(
                "Paste", None, lambda it: self._begin_paste_into(it),
            ),
            _MenuItemSpec(
                "Duplicate", None,
                lambda it: self._duplicate_items([it] if it else []),
            ),
            _MenuItemSpec(
                "Add Bookmark", None,
                lambda it: self._begin_add_bookmark(it),
            ),
            _MenuItemSpec(
                "Rename", None, lambda it: self._begin_rename(it),
            ),
            _MenuItemSpec(
                "Delete", None, lambda it: self._begin_delete(it),
            ),
        ]

    def _empty_specs(self) -> List[_MenuItemSpec]:
        """Empty-space menu: Create Folder, Paste, Refresh."""
        return [
            _MenuItemSpec(
                "Create Folder", None,
                lambda it: self._open_create_folder_dialog(None),
            ),
            _MenuItemSpec(
                "Paste", None,
                lambda it: self._begin_paste_into(None),
            ),
            _MenuItemSpec(
                "Refresh", None, lambda it: self._refresh(),
            ),
        ]

    # ── Stub actions ─────────────────────────────────────────────────────

    @staticmethod
    def _stub(name: str, item: Optional[FileItem]) -> None:
        """Log-only stub for a menu action.

        The real file operations arrive in Steps 33–37 (create folder,
        rename, delete, clipboard, paste). Routing the stub through
        :class:`ErrorReporter.log_info` gives the user a visible
        status-bar line when they click the menu entry, confirming
        the click reached the dispatcher even before the backing op
        lands. An ``item=None`` EMPTY-context click renders as
        ``"(empty)"`` in the log so the message still reads cleanly.
        """
        target_label = item.url if item is not None else "(empty)"
        ErrorReporter.log_info(
            "FileContextMenu",
            f"Stub: {name} on {target_label} (wired in Steps 33-37)",
        )

    def _drill_or_stub(self, item: Optional[FileItem]) -> None:
        """Folder Open — drill into the folder via the widget.

        This is the one built-in entry that already has a real action:
        the widget's :meth:`FileBrowserWidget._drill_into_folder` is
        the same drill-in path a double-click uses, so hooking it here
        gives the user a working "Open" from the menu without waiting
        for Steps 33–37. Post-destroy / missing widget falls through
        to the log stub so the user still gets feedback.
        """
        widget = self._widget
        if (
            widget is None
            or item is None
            or not item.is_folder
        ):
            self._stub("Open", item)
            return
        drill = getattr(widget, "_drill_into_folder", None)
        if drill is None:
            self._stub("Open", item)
            return
        drill(item)

    def _refresh(self) -> None:
        """Empty-space Refresh — re-populate the detail pane's root.

        Calls :meth:`FileBrowserModel.refresh_all` on the detail
        model; the model's ``item_changed`` dispatch wakes the overlay
        + grid refresh paths. Post-destroy / missing widget is a
        silent no-op — a Refresh from a torn-down menu has nothing to
        refresh.
        """
        widget = self._widget
        if widget is None:
            return
        model = getattr(widget, "_detail_model", None)
        if model is None:
            return
        refresh_all = getattr(model, "refresh_all", None)
        if refresh_all is None:
            return
        refresh_all()

    # ── Rename (Step 33) ────────────────────────────────────────────────

    def _begin_rename(self, item: Optional[FileItem]) -> None:
        """Route the Rename menu entry to :meth:`FileBrowserWidget.begin_rename`.

        ``item`` is the right-clicked target — a file or a folder; an
        ``EMPTY`` context never surfaces the Rename entry so ``None``
        here indicates a defensive miss (a plug-in that wired Rename
        onto empty space). Post-destroy / missing widget falls through
        to the log stub so the user still gets feedback.
        """
        widget = self._widget
        if widget is None or item is None:
            self._stub("Rename", item)
            return
        begin = getattr(widget, "begin_rename", None)
        if begin is None:
            self._stub("Rename", item)
            return
        begin(item)

    # ── Create Folder (Step 32) ─────────────────────────────────────────

    def _open_create_folder_dialog(
        self, item: Optional[FileItem],
    ) -> None:
        """Show the :class:`SimpleInputDialog` for a Create Folder action.

        ``item`` is the right-clicked target — ``None`` for an empty-
        space invocation (create under the current detail root), or a
        folder :class:`FileItem` when the action fires from the folder
        menu (create inside the clicked folder). A file item is
        refused with a status warning (the folder context menu is the
        only one that carries this entry, but defensive on the plug-in
        side — a third-party ``register_item`` that points at this
        method with a file target needs to fail loudly, not write
        into whatever ``parent_url_for_create`` returns).

        Post-destroy (``_widget is None``) silently no-ops. A
        subsequent invocation replaces :attr:`_input_dialog`; the
        prior dialog is dismissed first so a user who clicked Create
        Folder twice in rapid succession doesn't stack modals.
        """
        widget = self._widget
        if widget is None:
            return
        parent_url = self._parent_url_for_create(item)
        if parent_url is None:
            return
        # Dismiss any already-live dialog before spawning a new one.
        if self._input_dialog is not None:
            try:
                self._input_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._input_dialog = None

        dialog = SimpleInputDialog(
            title=_NEW_FOLDER_DIALOG_TITLE,
            prompt=_NEW_FOLDER_DIALOG_PROMPT,
            initial_value=_NEW_FOLDER_DIALOG_DEFAULT,
            on_ok=lambda name, url=parent_url: (
                self._create_folder_do(url, name)
            ),
        )
        self._input_dialog = dialog
        dialog.show()

    def _parent_url_for_create(
        self, item: Optional[FileItem],
    ) -> Optional[str]:
        """Resolve the parent URL for a Create Folder invocation.

        Rules:

        * ``item is None`` (empty-space right-click) → the detail
          model's current root URL.
        * ``item.is_folder`` (folder right-click) → ``item.url``.
        * ``item`` is a file — unsupported; log a warning and return
          ``None`` so the caller short-circuits without opening the
          dialog.

        Returns ``None`` when the widget / detail model has been torn
        down so :meth:`_open_create_folder_dialog` can no-op rather
        than spawn a dialog with a dangling reference.
        """
        widget = self._widget
        if widget is None:
            return None
        if item is None:
            model = getattr(widget, "_detail_model", None)
            if model is None:
                return None
            return model.root_url
        if not item.is_folder:
            ErrorReporter.log_warning(
                "FileContextMenu",
                "Create Folder on a file target is not supported",
            )
            return None
        return item.url

    def _create_folder_do(self, parent_url: str, raw_name: str) -> None:
        """Validate ``raw_name``, invoke the backend, refresh on success.

        Validation sequence (the content browser implementation step 32):

        1. Strip leading / trailing whitespace.
        2. Empty → warn + return.
        3. Contains ``/`` or ``\\`` → warn + return.
        4. Resolve the parent's cached :class:`FileItem` in the detail
           model. If the parent's children list already contains a
           child of this name, warn + return (duplicate).
        5. Call :meth:`BackendAdapter.create_folder` with the joined
           URL. Non-``OK`` result → show the result name as an error.
        6. On ``OK``, refresh both the detail and tree models so the
           new folder appears without a manual reload.

        The duplicate check is advisory — the backend itself returns
        :attr:`BackendResult.ERROR_ALREADY_EXISTS` when the folder is
        present on disk but not yet materialised in the model's cache
        (e.g. an out-of-band ``mkdir`` from a terminal). We keep the
        client-side check because it produces a snappier user-visible
        message for the common case where the model has already
        populated the parent's children.
        """
        widget = self._widget
        if widget is None:
            return

        name = (raw_name or "").strip()
        if not name:
            ErrorReporter.show_warning(_WARN_EMPTY_NAME)
            return
        if any(ch in name for ch in _ILLEGAL_NAME_CHARS):
            ErrorReporter.show_warning(_WARN_ILLEGAL_CHARS)
            return

        # Duplicate check against the model's cached parent. Skips the
        # check if the parent isn't resolved (e.g. empty-space create on
        # a root that hasn't populated yet) — the backend's
        # ``ERROR_ALREADY_EXISTS`` still covers that case.
        detail_model = getattr(widget, "_detail_model", None)
        if detail_model is not None:
            parent_item = detail_model.resolve(parent_url)
            if parent_item is not None:
                existing = {
                    child.name for child in parent_item.children
                }
                if name in existing:
                    ErrorReporter.show_warning(_WARN_DUPLICATE_NAME)
                    return

        backend = getattr(widget, "_backend", None)
        if backend is None:
            return

        target_url = backend.join_url(parent_url, name)
        result = backend.create_folder(target_url)
        if result != BackendResult.OK:
            ErrorReporter.show_error(
                _ERROR_CREATE_FAILED.format(reason=result.name),
            )
            return

        # Success — refresh the parent in both panes so the new folder
        # surfaces immediately. The tree model may not have the parent
        # cached (the user navigated from the detail pane only); a
        # ``resolve`` miss falls through to a silent no-op rather than
        # refreshing the wrong node.
        self._refresh_parent_after_create(parent_url)

    def _refresh_parent_after_create(self, parent_url: str) -> None:
        """Mark the parent dirty in both models so the new child shows up.

        Tries each model independently — a miss in one (the tree may
        not have walked past the detail's root, or vice versa) does not
        short-circuit the other. Falls back to ``refresh_all()`` on the
        detail model when the parent cannot be resolved there (e.g.
        the create happened outside the currently-rooted subtree).
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

    # ── Delete (Step 34) ────────────────────────────────────────────────

    def _begin_delete(self, item: Optional[FileItem]) -> None:
        """Route the Delete context-menu entry to the confirm dialog.

        A defensive ``None``-item falls through to the log stub — a
        plug-in that wired Delete into empty space with no target
        needs to fail loudly, not write into whatever
        :meth:`FileBrowserWidget.delete_selected` would return.
        Post-destroy / missing widget silently no-ops.
        """
        widget = self._widget
        if widget is None or item is None:
            self._stub("Delete", item)
            return
        self._open_confirm_delete_dialog([item])

    def _open_confirm_delete_dialog(
        self, items: List[FileItem],
    ) -> None:
        """Show the :class:`ConfirmDeleteDialog` for ``items``.

        Callers (Delete menu entry on a single item; Del-key path on a
        multi-selection) hand in the already-resolved item list. The
        dialog is constructed with the URL list rendered verbatim and
        an ``on_yes`` closure that fires :meth:`_delete_do` against the
        URLs. The dialog's keyboard Escape / No button path dismisses
        without firing ``on_yes`` — no backend round-trip on cancel.

        An empty ``items`` list silently no-ops rather than opening a
        dialog with nothing to confirm — this path is reachable from
        the Del-key handler when the selection empties between the
        keypress and the dispatch.

        Any in-flight confirm dialog is dismissed first so a rapid
        second Delete press doesn't stack two modals.
        """
        widget = self._widget
        if widget is None:
            return
        if not items:
            return
        if self._confirm_delete_dialog is not None:
            try:
                self._confirm_delete_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._confirm_delete_dialog = None

        urls = [it.url for it in items]
        dialog = ConfirmDeleteDialog(
            urls=urls,
            on_yes=lambda u=list(urls): self._delete_do(u),
        )
        self._confirm_delete_dialog = dialog
        dialog.show()

    def _delete_do(self, urls: List[str]) -> None:
        """Invoke :meth:`BackendAdapter.delete` for every URL in ``urls``.

        Semantics:

        * Collects unique parent URLs across the batch so a multi-item
          delete only refreshes each affected parent once, rather than
          re-resolving the same parent for every item.
        * Per-URL failure surfaces via :class:`ErrorReporter.show_error`
          naming the offending URL + the :class:`BackendResult` enum
          name — matches the verbose contract the Create Folder path
          set. Subsequent URLs still fire (no short-circuit) because
          the dialog already said "Yes" to every item: aborting on
          the first failure would leave an inconsistent partial state
          the user didn't authorise.
        * Final success message is a status-bar line naming the count.
          Skipped when zero items succeed (every URL failed) so the
          user isn't told "Deleted 0 items" on top of the per-URL
          error lines.

        Post-destroy / missing widget silently no-ops.
        """
        widget = self._widget
        if widget is None:
            return
        backend = getattr(widget, "_backend", None)
        if backend is None:
            return

        parents_to_refresh: List[str] = []
        success_count = 0
        for url in urls:
            parent_url = backend.parent_url(url)
            result = backend.delete(url)
            if result != BackendResult.OK:
                ErrorReporter.show_error(
                    _ERROR_DELETE_FAILED.format(
                        url=url, reason=result.name,
                    ),
                )
                continue
            success_count += 1
            if (
                parent_url is not None
                and parent_url not in parents_to_refresh
            ):
                parents_to_refresh.append(parent_url)

        for parent_url in parents_to_refresh:
            self._refresh_parent_after_delete(parent_url)

        if success_count == 1:
            ErrorReporter.show_success(_STATUS_DELETE_DONE_SINGLE)
        elif success_count > 1:
            ErrorReporter.show_success(
                _STATUS_DELETE_DONE_MULTI.format(count=success_count),
            )

    def _refresh_parent_after_delete(self, parent_url: str) -> None:
        """Mark ``parent_url`` dirty in both panes so deleted rows drop out.

        Mirrors :meth:`_refresh_parent_after_create` — tries the detail
        model and the tree model independently, falling back to
        :meth:`FileBrowserModel.refresh_all` on the detail side when the
        parent isn't cached (the delete happened outside the currently-
        rooted subtree after a race).
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

    # ── Copy / Cut / Paste (Step 36) ────────────────────────────────────

    def _copy_items(self, items: List[FileItem]) -> None:
        """Save ``items`` to the clipboard as a Copy selection.

        Writes URLs into :mod:`clipboard` with ``is_cut=False`` so the
        source cards render unchanged (Copy leaves the source in place).
        An empty list is a silent no-op — a defensive guard matching
        the Delete path; the menu never fires Copy with an empty item
        list unless a plug-in wires it to EMPTY context.

        Refreshes the cut-style repaint so a previous Cut selection's
        ``::Cut`` styling drops off when Copy overwrites the clipboard.
        """
        widget = self._widget
        if widget is None:
            return
        if not items:
            return
        urls = [it.url for it in items if isinstance(it, FileItem)]
        if not urls:
            return
        clipboard.save_to_clipboard(urls, is_cut=False)
        self._refresh_cut_style()
        if len(urls) == 1:
            ErrorReporter.show_success(_STATUS_CLIPBOARD_COPIED_SINGLE)
        else:
            ErrorReporter.show_success(
                _STATUS_CLIPBOARD_COPIED_MULTI.format(count=len(urls)),
            )

    def _cut_items(self, items: List[FileItem]) -> None:
        """Save ``items`` to the clipboard as a Cut selection.

        Writes URLs into :mod:`clipboard` with ``is_cut=True`` so cards
        pointing at those URLs render the dimmed ``::Cut`` style
        variant (:class:`FileCard` reads :func:`clipboard.is_path_cut`
        on build). The cards are repainted via
        :meth:`_refresh_cut_style` immediately — the user needs
        feedback that the Cut was registered before a later Paste
        completes the move.
        """
        widget = self._widget
        if widget is None:
            return
        if not items:
            return
        urls = [it.url for it in items if isinstance(it, FileItem)]
        if not urls:
            return
        clipboard.save_to_clipboard(urls, is_cut=True)
        self._refresh_cut_style()
        if len(urls) == 1:
            ErrorReporter.show_success(_STATUS_CUT_SINGLE)
        else:
            ErrorReporter.show_success(
                _STATUS_CUT_MULTI.format(count=len(urls)),
            )

    def _refresh_cut_style(self) -> None:
        """Tell the host widget to repaint its cards / rows.

        The ``::Cut`` style variant is applied at card / row build time
        by reading :func:`clipboard.is_path_cut`. A clipboard change
        does not fire a model event on its own, so the repaint has to
        be driven from here. The widget surface (Step 36) exposes
        :meth:`FileBrowserWidget.refresh_cut_style`; a missing method
        falls through silently so tests with a minimal fake widget
        still exercise the clipboard side-effect cleanly.
        """
        widget = self._widget
        if widget is None:
            return
        refresh = getattr(widget, "refresh_cut_style", None)
        if refresh is None:
            return
        refresh()

    def _begin_paste_into(self, item: Optional[FileItem]) -> None:
        """Start an iterative paste into the folder represented by ``item``.

        Resolves the destination parent URL from ``item``:

        * ``item is None`` (empty-space Paste) → the detail model's
          current root URL.
        * ``item.is_folder`` → ``item.url``.
        * ``item`` is a file — defensive-refused: the file-target menu
          does not surface Paste, but a plug-in that wires Paste onto
          a file target cannot silently redirect into the containing
          folder (that would surprise the user).

        Clipboard-empty / no-destination cases surface as warnings and
        no-op. A live paste-in-flight (``_paste_state is not None``)
        also no-ops rather than queueing a second batch.
        """
        widget = self._widget
        if widget is None:
            return
        if self._paste_state is not None:
            # A paste is already walking through the URL list — spawning
            # a second batch under the same menu would interleave
            # dialogs and refreshes. Silently ignore until the first
            # batch finishes (the user can click Paste again).
            return
        urls = clipboard.get_clipboard_urls()
        if not urls:
            ErrorReporter.show_warning(_WARN_NOTHING_TO_PASTE)
            return
        dst_parent_url = self._paste_destination_url(item)
        if dst_parent_url is None:
            ErrorReporter.show_warning(_WARN_NO_PASTE_DESTINATION)
            return
        is_cut = clipboard.is_clipboard_cut()
        self._paste_state = _PasteState(
            remaining=urls,
            dst_parent_url=dst_parent_url,
            is_cut=is_cut,
        )
        self._paste_next()

    def _paste_destination_url(
        self, item: Optional[FileItem],
    ) -> Optional[str]:
        """Resolve the folder that receives a Paste.

        * ``item is None`` → detail model's ``root_url`` (empty-space
          Paste targets the current folder).
        * ``item.is_folder`` → ``item.url``.
        * ``item`` is a file — refuses with ``None``; a file cannot
          contain children.

        Returns ``None`` post-destroy so the caller can short-circuit
        cleanly without spawning dialogs against a dangling widget.
        """
        widget = self._widget
        if widget is None:
            return None
        if item is None:
            model = getattr(widget, "_detail_model", None)
            if model is None:
                return None
            return model.root_url
        if not item.is_folder:
            return None
        return item.url

    def _paste_next(self) -> None:
        """Process the next URL in :attr:`_paste_state` or finalize.

        Synchronous fast-path for collision-free / pre-decided batches
        — runs tight until the first collision or the end of the list.
        A collision that still needs a user decision hands off to
        :class:`ConfirmOverwriteDialog` whose ``on_response`` callback
        re-enters :meth:`_paste_next` to keep the batch moving.
        """
        widget = self._widget
        if widget is None:
            return
        state = self._paste_state
        if state is None:
            return
        backend = getattr(widget, "_backend", None)
        if backend is None:
            self._paste_finalize()
            return

        # Tight loop — consume URLs until one blocks on a dialog or
        # we run out. Using a while loop (rather than recursion) keeps
        # the call stack flat for a no-collision multi-paste.
        while state.remaining:
            src_url = state.remaining[0]
            name = backend.basename(src_url)
            if not name:
                # A URL with no basename (e.g. a root) cannot paste —
                # skip with a log and continue. The user sees the
                # error in the end-of-batch status line.
                state.errors.append((src_url, "ERROR_NOT_SUPPORTED"))
                state.remaining.pop(0)
                continue
            dst_url = backend.join_url(state.dst_parent_url, name)
            # Apply pre-decided overwrite-all state, or start with
            # overwrite=False so the first collision surfaces.
            overwrite = state.overwrite_all is True
            if state.is_cut:
                result = backend.move(src_url, dst_url, overwrite=overwrite)
            else:
                result = backend.copy(src_url, dst_url, overwrite=overwrite)
            if result == BackendResult.OK:
                state.success_count += 1
                self._record_refresh(backend, src_url, state)
                self._record_refresh_from_url(dst_url, backend, state)
                state.remaining.pop(0)
                continue
            if result == BackendResult.ERROR_ALREADY_EXISTS:
                if state.overwrite_all is True:
                    # Already retried with overwrite=True above — if it
                    # still fails with ALREADY_EXISTS the backend is
                    # misbehaving. Surface as an error and move on so
                    # the batch does not spin.
                    state.errors.append((src_url, result.name))
                    state.remaining.pop(0)
                    continue
                if state.overwrite_all is False:
                    # No-to-All — skip this one without asking.
                    state.remaining.pop(0)
                    continue
                # Still asking — pop the dialog and wait for the
                # response. The dialog callback re-enters
                # :meth:`_paste_next`.
                self._open_overwrite_dialog(dst_url)
                return
            # Any other non-OK result surfaces per-URL. The batch
            # keeps going (the user already authorised the paste;
            # aborting mid-batch would leave a partial state).
            state.errors.append((src_url, result.name))
            state.remaining.pop(0)

        self._paste_finalize()

    def _open_overwrite_dialog(self, dst_url: str) -> None:
        """Spawn a :class:`ConfirmOverwriteDialog` for ``dst_url``.

        Dismisses any in-flight dialog first (defensive against a
        rapid Paste that landed two spawns before the first dialog's
        response reached us). ``multi`` is derived from whether the
        batch still has items after this one — a single-item batch
        hides the Yes-to-All / No-to-All buttons for a tighter dialog.
        """
        state = self._paste_state
        if state is None:
            return
        if self._confirm_overwrite_dialog is not None:
            try:
                self._confirm_overwrite_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._confirm_overwrite_dialog = None

        # ``_multi`` = True only when more than one item is *still
        # remaining* in the batch (the current URL + at least one
        # more). A single-item paste or the last item of a multi-
        # paste renders with Yes / No only.
        multi = len(state.remaining) > 1
        dialog = ConfirmOverwriteDialog(
            url=dst_url,
            on_response=self._on_overwrite_choice,
            multi=multi,
        )
        self._confirm_overwrite_dialog = dialog
        dialog.show()

    def _on_overwrite_choice(self, choice: "OverwriteChoice") -> None:
        """Handle the user's response to a single overwrite prompt.

        ``YES`` retries the current URL with ``overwrite=True``.
        ``NO`` drops the current URL (skip this collision).
        ``YES_TO_ALL`` / ``NO_TO_ALL`` latch the batch decision and
        fall through to the same retry / skip logic — future
        collisions in the batch no longer open the dialog.
        """
        # The dialog has already dismissed itself (fire-then-dismiss
        # contract in :class:`ConfirmOverwriteDialog`); drop our
        # strong ref so a re-entrant Paste can spawn a fresh dialog.
        self._confirm_overwrite_dialog = None
        widget = self._widget
        state = self._paste_state
        if widget is None or state is None:
            return

        if choice == OverwriteChoice.YES_TO_ALL:
            state.overwrite_all = True
        elif choice == OverwriteChoice.NO_TO_ALL:
            state.overwrite_all = False

        if choice in (OverwriteChoice.YES, OverwriteChoice.YES_TO_ALL):
            self._retry_current_with_overwrite()
        else:
            # NO / NO_TO_ALL — skip the current URL.
            if state.remaining:
                state.remaining.pop(0)

        self._paste_next()

    def _retry_current_with_overwrite(self) -> None:
        """Re-issue the current URL's copy / move with ``overwrite=True``.

        Only invoked from :meth:`_on_overwrite_choice` — at that point
        we already know the first attempt hit ``ERROR_ALREADY_EXISTS``,
        so the retry skips the non-existence branches. A non-OK retry
        surfaces as an error and pops the URL; we do not re-open the
        dialog for the same URL because the user already answered.
        """
        widget = self._widget
        state = self._paste_state
        if widget is None or state is None:
            return
        if not state.remaining:
            return
        backend = getattr(widget, "_backend", None)
        if backend is None:
            state.remaining.pop(0)
            return
        src_url = state.remaining[0]
        name = backend.basename(src_url)
        dst_url = backend.join_url(state.dst_parent_url, name)
        if state.is_cut:
            result = backend.move(src_url, dst_url, overwrite=True)
        else:
            result = backend.copy(src_url, dst_url, overwrite=True)
        if result == BackendResult.OK:
            state.success_count += 1
            self._record_refresh(backend, src_url, state)
            self._record_refresh_from_url(dst_url, backend, state)
        else:
            state.errors.append((src_url, result.name))
        state.remaining.pop(0)

    def _record_refresh(
        self, backend: Any, src_url: str, state: _PasteState,
    ) -> None:
        """Queue the source's parent for refresh (Cut only, for
        now) so the source row drops out of the detail / tree views.

        Called on every successful iteration. Copy leaves the source
        in place so the source-parent refresh is technically a no-op
        — but the tree may still need it on a filesystem-watcher miss.
        We record both parents unconditionally; the refresh is cheap
        and the consistency guarantee outweighs the extra repaint.
        """
        if not state.is_cut:
            return
        parent = backend.parent_url(src_url)
        if parent is not None:
            state.refreshed_parents.add(parent)

    def _record_refresh_from_url(
        self, dst_url: str, backend: Any, state: _PasteState,
    ) -> None:
        """Queue the destination's parent for refresh so pasted rows show up."""
        parent = backend.parent_url(dst_url)
        if parent is not None:
            state.refreshed_parents.add(parent)

    def _paste_finalize(self) -> None:
        """End-of-batch: fire refreshes, clear clipboard, report status.

        Refreshes happen before the clipboard clears so the old Cut
        URLs still in ``_clipboard_urls`` can be checked if a card
        rebuild races the clear (a Cut paste from a folder into a
        nested folder would otherwise briefly repaint the moved card
        as cut before the clear lands). The clipboard clear fires only
        for a Cut batch; Copy leaves the clipboard alive so repeated
        pastes of the same source are a single clipboard write.

        Success / error reporting mirrors :meth:`_delete_do`'s
        vocabulary: per-URL error lines for each failure plus a single
        end-of-batch status-bar success line naming the count (skipped
        when zero items succeeded, on the same "don't shout 'Copied 0'"
        principle).
        """
        state = self._paste_state
        self._paste_state = None
        if state is None:
            return
        widget = self._widget
        if widget is None:
            return

        for parent_url in state.refreshed_parents:
            if state.is_cut:
                self._refresh_parent_after_delete(parent_url)
            else:
                self._refresh_parent_after_create(parent_url)

        if state.is_cut:
            # Successful Cut + Paste clears the clipboard so the source
            # cards drop the ``::Cut`` style. An all-failed Cut batch
            # also clears — a partial state where the clipboard still
            # holds URLs that no longer exist is more confusing than
            # the reset.
            clipboard.clear_clipboard()
            self._refresh_cut_style()

        for url, reason in state.errors:
            if state.is_cut:
                ErrorReporter.show_error(
                    _ERROR_MOVE_FAILED.format(url=url, reason=reason),
                )
            else:
                ErrorReporter.show_error(
                    _ERROR_COPY_FAILED.format(url=url, reason=reason),
                )

        if state.success_count == 0:
            return
        if state.is_cut:
            if state.success_count == 1:
                ErrorReporter.show_success(_STATUS_MOVED_SINGLE)
            else:
                ErrorReporter.show_success(
                    _STATUS_MOVED_MULTI.format(count=state.success_count),
                )
        else:
            if state.success_count == 1:
                ErrorReporter.show_success(_STATUS_COPIED_SINGLE)
            else:
                ErrorReporter.show_success(
                    _STATUS_COPIED_MULTI.format(count=state.success_count),
                )

    # ── Add / Remove Bookmark (Step 45) ──────────────────────────────────

    def show_bookmark_menu(
        self, x: float, y: float, bookmark_name: str,
    ) -> Optional[ui.Menu]:
        """Pop the bookmark-nav-pane context menu for ``bookmark_name``.

        Dedicated entry point for the Step 45 nav-pane right-click path:
        the navigation delegate (a :class:`BookmarksCollection` child)
        fires this with the bookmark's name when the user right-clicks a
        bookmark row. The menu carries a single "Remove Bookmark" entry
        that dispatches :meth:`BookmarksManager.remove` when activated.

        A dedicated method (rather than threading the bookmark name
        through :meth:`show`) keeps the file / folder / empty menus
        honest — none of those carry a bookmark-name concept, so adding
        it to :meth:`show` would force every existing caller to pass
        ``bookmark_name=None``. Post-destroy short-circuits to ``None``.
        """
        if self._widget is None:
            return None
        menu = create_flat_menu()
        with menu:
            ui.MenuItem(
                "Remove Bookmark",
                triggered_fn=(
                    lambda name=bookmark_name: self._begin_remove_bookmark(
                        name,
                    )
                ),
            )
        menu.show_at(float(x), float(y))
        self._menu = menu
        return menu

    def _begin_add_bookmark(self, item: Optional[FileItem]) -> None:
        """Open the name-override dialog for an Add Bookmark action.

        ``item`` is the right-clicked folder; a ``None`` or non-folder
        target is a defensive refusal (the ``Add Bookmark`` entry only
        surfaces on the folder menu, but a plug-in that re-wired the
        entry onto a different target must not silently pick a random
        URL). The dialog's initial value is the backend's basename of
        the folder URL; users can override it when they want a shorter / more
        readable label.

        Post-destroy (``_widget is None``) silently no-ops. A
        no-manager widget (a test-harness or a future headless mode)
        surfaces a warning via :class:`ErrorReporter` rather than
        silently swallowing the click.
        """
        widget = self._widget
        if widget is None:
            return
        if item is None or not item.is_folder:
            self._stub("Add Bookmark", item)
            return
        manager = self._bookmarks_manager()
        if manager is None:
            ErrorReporter.show_warning(_WARN_BOOKMARK_NO_MANAGER)
            return
        backend = getattr(widget, "_backend", None)
        if backend is None:
            return
        # Default the dialog value to the folder's basename — the
        # architecture's "Name" field default. A URL whose basename is
        # empty (a root URL, e.g. ``mock://``) falls back to the URL
        # itself so the field is not blank on open.
        default_name = backend.basename(item.url) or item.url

        if self._input_dialog is not None:
            try:
                self._input_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._input_dialog = None

        target_url = item.url
        dialog = SimpleInputDialog(
            title=_ADD_BOOKMARK_DIALOG_TITLE,
            prompt=_ADD_BOOKMARK_DIALOG_PROMPT,
            initial_value=default_name,
            on_ok=lambda name, url=target_url: (
                self._add_bookmark_do(name, url)
            ),
        )
        self._input_dialog = dialog
        dialog.show()

    def _add_bookmark_do(self, raw_name: str, url: str) -> None:
        """Validate ``raw_name`` and call :meth:`BookmarksManager.add`.

        Validation rules mirror the Create Folder flow: strip
        whitespace, reject an empty trimmed value. Duplicate-name
        collisions are not rejected — :meth:`BookmarksManager.add`
        treats them as an overwrite by design (the content browser implementation step 44 +
        Step 45), so the user can rebind an existing bookmark to a new
        URL by re-adding with the same name. A no-manager widget
        surfaces a warning rather than crashing (defensive guard; the
        caller already checked, but a mid-flight :meth:`destroy` could
        race the OK click).
        """
        widget = self._widget
        if widget is None:
            return
        manager = self._bookmarks_manager()
        if manager is None:
            ErrorReporter.show_warning(_WARN_BOOKMARK_NO_MANAGER)
            return
        name = (raw_name or "").strip()
        if not name:
            ErrorReporter.show_warning(_WARN_BOOKMARK_EMPTY_NAME)
            return
        manager.add(name, url)
        ErrorReporter.show_success(
            _STATUS_BOOKMARK_ADDED.format(name=name),
        )

    def _begin_remove_bookmark(self, name: str) -> None:
        """Call :meth:`BookmarksManager.remove` for the named bookmark.

        Invoked from :meth:`show_bookmark_menu` after the user clicks
        "Remove Bookmark" on a nav-pane bookmark row. A no-manager
        widget surfaces a warning; an empty / missing name is treated
        as a defensive miss (the menu only builds when the row carries
        a resolved bookmark name, but guard against a stale callback
        that fired after a rename / teardown).
        """
        widget = self._widget
        if widget is None:
            return
        if not name:
            return
        manager = self._bookmarks_manager()
        if manager is None:
            ErrorReporter.show_warning(_WARN_BOOKMARK_NO_MANAGER)
            return
        manager.remove(name)
        ErrorReporter.show_success(
            _STATUS_BOOKMARK_REMOVED.format(name=name),
        )

    def _bookmarks_manager(self) -> Any:
        """Return the widget's :class:`BookmarksManager`, or ``None``.

        The widget exposes the manager via a plain attribute so the
        context menu does not need to know about the manager's
        construction (it is built at window / application startup and
        threaded through :class:`FileBrowserWidget.__init__`). A widget
        constructed in a test without a manager reads ``None`` here;
        callers handle that case with a user-visible warning.
        """
        widget = self._widget
        if widget is None:
            return None
        return getattr(widget, "_bookmarks", None)

    # ── Duplicate / Open-in-Native / Copy URL (Step 37) ─────────────────

    def _duplicate_items(self, items: List[FileItem]) -> None:
        """Duplicate ``items`` into their parent folder via :mod:`file_ops`.

        Each item is copied to ``{parent}/{name_with_Copy_suffix}`` —
        the suffix algorithm lives in
        :func:`file_ops._next_copy_name`. Per-item failure surfaces via
        :class:`ErrorReporter.show_error`; a successful batch reports a
        single status-bar success line naming the count.

        Empty ``items`` / missing widget / missing backend all short-
        circuit silently. Post-destroy safety matches the other menu
        ops: a click that landed after :meth:`destroy` finds
        ``_widget is None`` and returns before touching state.
        """
        widget = self._widget
        if widget is None or not items:
            return
        backend = getattr(widget, "_backend", None)
        if backend is None:
            return
        success_count, errors = file_ops.duplicate_items(
            backend=backend,
            items=items,
            refresh_parent_fn=self._refresh_parent_after_create,
        )
        for url, reason in errors:
            ErrorReporter.show_error(
                _ERROR_DUPLICATE_FAILED.format(url=url, reason=reason),
            )
        if success_count == 1:
            ErrorReporter.show_success(_STATUS_DUPLICATED_SINGLE)
        elif success_count > 1:
            ErrorReporter.show_success(
                _STATUS_DUPLICATED_MULTI.format(count=success_count),
            )

    @staticmethod
    def _can_open_in_native(item: Optional[FileItem]) -> bool:
        """``show_fn`` predicate for the Open in Native Browser entry.

        Hides the entry when the target is ``None`` (defensive — the
        folder menu should always carry an item), when the URL scheme
        is non-local (``mock://`` / ``omniverse://`` cannot be opened
        by ``xdg-open``), or when :mod:`file_ops` itself reports the
        URL as non-local. Kept as a :func:`staticmethod` so the check
        is addressable from tests without instantiating the menu.
        """
        if item is None:
            return False
        return file_ops._is_local_url(item.url)

    def _open_in_native(self, item: Optional[FileItem]) -> None:
        """Dispatch :func:`file_ops.open_in_native_browser` for ``item``.

        Failure (non-local URL that slipped past ``show_fn``, missing
        OS launcher, path does not exist) surfaces as a status-bar
        warning so the user sees a signal instead of a silent no-op.
        """
        if item is None:
            return
        if not file_ops.open_in_native_browser(item.url):
            ErrorReporter.show_warning(_WARN_NATIVE_BROWSER_UNAVAILABLE)

    def _copy_url(self, item: Optional[FileItem]) -> None:
        """Dispatch :func:`file_ops.copy_url_to_clipboard` for ``item``.

        ``item is None`` silently no-ops — the Copy URL entry never
        fires on an EMPTY context, so a ``None`` here indicates a
        plug-in that wired Copy URL onto empty space. The file_ops
        helper itself also no-ops on a falsy URL; this guard is for
        clarity at the call site.
        """
        if item is None:
            return
        file_ops.copy_url_to_clipboard(item.url)
