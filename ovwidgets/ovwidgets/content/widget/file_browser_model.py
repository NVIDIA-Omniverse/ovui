# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FileBrowserModel — ``omni.ui.AbstractItemModel`` for the content browser.

See the content browser behavior (Model Layer) and the content browser implementation step 7.
``FileBrowserModel`` is the counterpart of Kit's ``FileBrowserModel``: the
single source of truth for the tree/list views over a
:class:`BackendAdapter`. It keeps a lazy :class:`FileItem` cache keyed by
URL, drives synchronous populate on first access, applies folders-first
+ natural-number sort, and batches ``item_changed`` notifications so a
burst of refresh events collapses into one UI redraw per frame.

Everything downstream (delegate Step 8, widget Step 9, window Step 10,
auto-refresh Step 11) reads this model. Adding features to the model
(new columns, live change events, drag/drop) belongs to later plan
steps; this module is deliberately narrow — cache + sort + filter +
throttled dispatch — to keep the contract small.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any, Callable, Dict, List, Optional, Set

import omni.ui as ui

from ovwidgets.common.asset_types import AssetCategory
from ovwidgets.content.backends.backend_adapter import (
    BackendAdapter,
    BackendChangeEvent,
    BackendFileFlags,
    BackendResult,
)
from ovwidgets.content.widget.confirm_overwrite_dialog import (
    ConfirmOverwriteDialog,
    OverwriteChoice,
)
from ovwidgets.content.widget.file_item import FileItem

# Suffix under the parent folder where thumbnails live (manual or auto).
# Mirrors the content browser behavior ``_thumbnails_dir``. Joined
# via :meth:`BackendAdapter.join_url` so every backend's URL separator
# rules (local FS vs a future Nucleus / HTTP adapter) handle the nested
# path the same way.
_THUMBNAIL_DIR_SUFFIX = ".thumbs/256x256"


# ──────────────────────────────────────────────────────────────────────────────
# Sort policy constants
# ──────────────────────────────────────────────────────────────────────────────

class FileBrowserSortPolicy:
    """String constants for :meth:`FileBrowserModel.set_sort_policy`.

    Plain strings (not an ``Enum``) so settings-persistence can round-trip
    them as-is and the model can compare with ``==`` without unwrapping.
    Only six combinations are defined; any other value is treated as
    :attr:`NAME_ASC` to avoid an exception in the sort path.
    """

    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"
    DATE_ASC = "date_asc"
    DATE_DESC = "date_desc"
    SIZE_ASC = "size_asc"
    SIZE_DESC = "size_desc"


# ──────────────────────────────────────────────────────────────────────────────
# Natural sort helper
# ──────────────────────────────────────────────────────────────────────────────

# Matches Kit OM-12985: "10.usd" must sort after "2.usd". ``re.split`` on
# a digit-run group produces an alternating list of non-digit / digit
# segments; tagging each with a leading ``(0, int)`` vs ``(1, str)``
# prevents cross-type comparisons (``int`` vs ``str``) from raising at
# sort time and keeps digit runs sorted numerically regardless of length.
_DIGIT_SPLIT = re.compile(r"(\d+)")


def _natural_sort_key(name: str) -> tuple:
    """Return a tuple key for case-insensitive natural-number ordering.

    Splits ``name`` on digit runs. Each segment becomes ``(0, int)`` for
    digits or ``(1, casefolded_str)`` for text. Tuple comparison then
    orders numeric segments numerically and text segments
    lexicographically; the leading ``0``/``1`` tag guarantees that a
    digit segment and a text segment at the same position never
    compare as mismatched types.

    Examples::

        _natural_sort_key("2.usd")  # → ((0, 2),  (1, ".usd"))
        _natural_sort_key("10.usd") # → ((0, 10), (1, ".usd"))
    """
    parts = _DIGIT_SPLIT.split(name.casefold())
    key: List[tuple] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)


# ──────────────────────────────────────────────────────────────────────────────
# Drop state (Step 38 — internal drag-drop)
# ──────────────────────────────────────────────────────────────────────────────

class _DropState:
    """Mutable per-batch state for :meth:`FileBrowserModel.drop`.

    Drop is **async** — each collision spawns a
    :class:`ConfirmOverwriteDialog` whose ``on_response`` callback drives
    the next iteration. Mirrors
    :class:`ovwidgets.content.widget.context_menu._PasteState` so
    the two flows speak the same dialect (same overwrite semantics, same
    per-batch ``Yes to All`` / ``No to All`` decision).

    Fields:

    * ``remaining`` — source URLs still to process (popped from the
      left as each iteration completes).
    * ``dst_parent_url`` — folder every surviving URL lands in. Fixed
      for the batch — resolved once from the drop target at
      :meth:`FileBrowserModel.drop` entry.
    * ``is_copy`` — ``True`` for Ctrl-drag (``backend.copy``), ``False``
      for plain drag (``backend.move``). Snapshot at batch start so a
      mid-batch Ctrl release does not flip semantics.
    * ``overwrite_all`` — tri-state per-batch decision:
      ``None`` = keep asking, ``True`` = Yes-to-All, ``False`` =
      No-to-All.
    * ``success_count`` / ``errors`` — tallies for end-of-batch
      reporting. Errors collect as ``(url, result_name)``.
    * ``affected_parents`` — URL set of every parent folder touched by
      the batch (source parents + ``dst_parent_url``) so refresh runs
      once per parent at end-of-batch instead of per-URL.
    * ``on_complete`` — optional callback invoked after end-of-batch
      refresh finishes. Widget-level hook that lets the host refresh
      the sibling pane (tree vs detail) without coupling the model to
      the widget.
    """

    __slots__ = (
        "remaining",
        "dst_parent_url",
        "is_copy",
        "overwrite_all",
        "success_count",
        "errors",
        "affected_parents",
        "on_complete",
    )

    def __init__(
        self,
        remaining: List[str],
        dst_parent_url: str,
        is_copy: bool,
        on_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        self.remaining: List[str] = list(remaining)
        self.dst_parent_url: str = dst_parent_url
        self.is_copy: bool = bool(is_copy)
        self.overwrite_all: Optional[bool] = None
        self.success_count: int = 0
        self.errors: List[tuple] = []
        self.affected_parents: Set[str] = set()
        self.on_complete: Optional[Callable[[], None]] = on_complete


# ──────────────────────────────────────────────────────────────────────────────
# FileBrowserModel
# ──────────────────────────────────────────────────────────────────────────────

class FileBrowserModel(ui.AbstractItemModel):
    """Lazy :class:`FileItem` cache fronted as an ``AbstractItemModel``.

    Per the content browser behavior: every query goes through
    :meth:`get_item_children`, which synchronously populates the
    underlying :class:`FileItem` on first touch, then applies
    folders-first + natural-sort + filters. Change events are deferred
    one frame via :meth:`ovwidgets.app.application.Application.call_later` so a
    burst of ``refresh_item`` calls collapses into one dispatch.

    Single-threaded by design. The :class:`FileItem` mutex is defensive
    insurance against a future threaded populate extension; the model
    itself does not take any lock.
    """

    # Three built-in columns (name / size / date). Plug-in columns land
    # in a later step and extend this value on the header query only
    # (§5.4 column-count asymmetry), not on individual items — so the
    # constant stays fixed.
    BUILTIN_COLUMN_COUNT = 3

    # Text-filter substrings are compared case-insensitively via
    # ``lower()`` — plan §Step 7 bullet 7.

    def __init__(
        self,
        backend: BackendAdapter,
        root_url: str,
        folder_only: bool = False,
        sort_policy: str = FileBrowserSortPolicy.NAME_ASC,
        single_column: bool = False,
    ) -> None:
        super().__init__()
        self._backend = backend
        self._root_url = backend.normalize_url(root_url)
        self._folder_only = folder_only
        self._sort_policy = sort_policy
        # Step 13 two-pane tree pane: the left pane renders a single
        # Name column only, so it instantiates its model with
        # ``single_column=True``. omni.ui reserves per-column horizontal
        # space based on the model's ``get_item_value_model_count`` —
        # reporting 3 columns on a view with ``column_widths=[Fraction(1)]``
        # squeezes the Name column to a third of the pane width. The
        # tree pane opts into a 1-column count so its single column
        # genuinely fills the pane.
        self._single_column = single_column

        # URL → FileItem cache. Every FileItem the model ever observes
        # (root, populated children, etc.) is registered here. Lookups
        # by URL are O(1); bookmark-expansion and hash-based selection
        # routing rely on it in later steps.
        self._cache: Dict[str, FileItem] = {}
        self._root: FileItem = self._get_or_create(self._root_url, is_folder=True)

        # Filters. ``None`` asset-type whitelist means "allow all"; any
        # set means "only allow folders + leaves whose ``category`` is
        # in the set". Folders are always allowed regardless of
        # whitelist so the user can drill into subfolders; matches the
        # Kit filter-by-type behaviour.
        self._asset_type_whitelist: Optional[Set[AssetCategory]] = None
        self._text_filter: str = ""
        # Step 49 — per-entry ``fnmatch`` globs for the file-picker
        # extension combo. Empty list means "no filter" (equivalent to
        # the ``*.*`` / "All files" selection). Patterns are matched
        # case-insensitively against the child's basename; folders
        # always pass regardless of pattern so the user can drill into
        # a subtree whose only leaves would otherwise be filtered out.
        self._glob_patterns: List[str] = []
        self._show_hidden: bool = False

        # Throttled item_changed dispatch (§5.7). A single pending set
        # collects items whose children changed during this frame; the
        # handle guards against re-scheduling — only the first call
        # this frame enqueues a ``call_later``. ``None`` is a legal
        # element here and encodes "top-level re-query" (used by
        # :meth:`set_root_url`) — omni.ui's ``_item_changed(None)`` is
        # the sentinel for "the root's children changed", which is
        # what a re-root fundamentally is.
        self._pending_item_changed: Set[Optional[FileItem]] = set()
        self._item_changed_handle: Any = None

        # Step 15: most recent ``BackendResult`` observed while populating
        # through :meth:`get_item_children`. The widget's empty-state
        # overlay reads this to distinguish "folder is empty" (OK + 0
        # children) from "access denied" / "not found" / other errors.
        # Reset to ``OK`` on :meth:`set_root_url` so a stale error from
        # the previous root does not bleed into the fresh one before
        # the first populate runs.
        self._last_error: BackendResult = BackendResult.OK

        # Step 16: backend change-event subscription. The ABC's default
        # returns a no-op :class:`ovwidgets.common.settings.Subscription`, so a
        # production backend without watching capability (LocalFSBackend
        # in v1) incurs zero cost here. :class:`MockBackend` overrides
        # with a real subscriber list — tests drive events via its
        # ``emit_change`` hook. Stored so :meth:`destroy` can cancel;
        # without that, the backend's subscriber list would keep a
        # strong reference to :meth:`_on_backend_change` and, through
        # it, the whole model.
        self._change_sub: Any = backend.subscribe_changes(
            self._root_url, self._on_backend_change,
        )

        # Step 38 — internal drag-drop state. ``_drop_state`` is
        # populated by :meth:`drop` and consumed by :meth:`_drop_next` /
        # :meth:`_drop_finalize`. ``None`` when no drop is in flight;
        # guards against re-entrant :meth:`drop` calls while a collision
        # dialog is still open. ``_drop_confirm_dialog`` keeps a strong
        # Python reference to the live :class:`ConfirmOverwriteDialog`
        # so ovui does not GC the popup out from under the user between
        # spawn and response.
        self._drop_state: Optional[_DropState] = None
        self._drop_confirm_dialog: Optional[ConfirmOverwriteDialog] = None

    # ── AbstractItemModel API ─────────────────────────────────────────────────

    def get_item_children(
        self, item: Optional[ui.AbstractItem],
    ) -> List[ui.AbstractItem]:
        """Return the sorted+filtered children of ``item`` (or root).

        Pipeline order (mirrors the content browser implementation step 7 bullets):

        1. ``item is None`` → shorthand for the root. Equivalent to
           ``get_item_children(self._root)`` — follows the Kit
           ``FileBrowserModel`` convention where ``None`` names the
           implicit parent of the top-level items. Step 9's widget
           uses ``root_visible=True`` so the TreeView draws the root
           row from the ``self._root`` :class:`FileItem` directly.
        2. Non-:class:`FileItem` or leaf → empty list.
        3. Populate from backend if not yet populated. On success, sync
           the URL cache with the freshly added children. On error
           (``ERROR_ACCESS_DENIED`` in particular) return the existing
           snapshot — which may be empty — so the UI shows an empty
           folder rather than a stack trace.
        4. Apply filters in order: folder-only → hidden → asset-type
           whitelist → text filter.
        5. Sort: folders first, then files; each group sorted per
           ``sort_policy`` (name uses natural-number sort).
        """
        if item is None:
            item = self._root
        if not isinstance(item, FileItem):
            return []
        if not item.is_folder:
            return []

        if not item.populated:
            result = item.populate(self._backend)
            # Record the populate result so the Step 15 empty-state
            # overlay can distinguish "folder is empty" (OK + 0
            # children) from "access denied" / "not found" / other
            # errors. Every populate updates this — the widget reads
            # it right after calling ``get_item_children`` on the root
            # so the value is always synchronised with the root's
            # most recent populate attempt.
            self._last_error = result
            if result is BackendResult.OK:
                # Sync cache so URL-keyed lookups find the newly
                # materialised children. Overwrite is safe — if a cache
                # entry already existed for this URL, the child produced
                # by populate is the authoritative object (see §5.6).
                for child in item.children:
                    self._cache[child.url] = child
                # Step 25: schedule a thumbnail-discovery pass for the
                # freshly populated folder. Deferred via
                # :meth:`call_later` so the expensive ``list_dir`` on
                # ``.thumbs/256x256`` does not block the initial
                # children dispatch — the UI renders the folder's
                # default icons immediately and cards swap in custom
                # thumbnails on the next frame.
                self._schedule_thumbnail_populate(item)
            # Any other result leaves ``_populated`` False so a retry
            # on the next ``get_item_children`` call goes through.

        snapshot = item.children

        if self._folder_only:
            snapshot = [c for c in snapshot if c.is_folder]

        if not self._show_hidden:
            snapshot = [c for c in snapshot if not self._is_hidden(c)]

        whitelist = self._asset_type_whitelist
        if whitelist is not None:
            # Folders always pass so the user can descend into a
            # subtree whose only leaves would be filtered out. Matches
            # Kit's behaviour for the "Show only X files" dropdown.
            snapshot = [
                c for c in snapshot
                if c.is_folder or c.category in whitelist
            ]

        if self._text_filter:
            needle = self._text_filter.lower()
            snapshot = [c for c in snapshot if needle in c.name.lower()]

        if self._glob_patterns:
            # Folders always pass the glob filter — same carve-out the
            # asset-type whitelist uses — so the user can still drill
            # into a subtree even when the active globs would filter
            # out every leaf at this level.
            patterns = self._glob_patterns
            filtered: List[FileItem] = []
            for child in snapshot:
                if child.is_folder:
                    filtered.append(child)
                    continue
                name_lower = child.name.lower()
                for pattern in patterns:
                    if fnmatch.fnmatchcase(name_lower, pattern):
                        filtered.append(child)
                        break
            snapshot = filtered

        return self._sort_children(snapshot)

    def can_item_have_children(self, item: ui.AbstractItem) -> bool:
        """Folders have children; leaves do not.

        The TreeView uses this for the expand-arrow branch without
        actually calling ``get_item_children``, so it stays O(1) even
        for huge folders.
        """
        if not isinstance(item, FileItem):
            return False
        return item.is_folder

    def get_item_value_model_count(self, item: ui.AbstractItem) -> int:
        """Column count for this model — 3 by default, 1 when single-column.

        The three built-in columns are Name, Size, Date. The Step 13
        tree pane opts into a 1-column view via ``single_column=True``;
        reporting 1 here makes omni.ui allocate the full pane width to
        the Name column rather than reserving a third of it for each
        of three columns. Plug-in columns (Step 29) extend this on the
        header query only; individual items return the active count.
        """
        if self._single_column:
            return 1
        return self.BUILTIN_COLUMN_COUNT

    def get_item_value_model(
        self, item: ui.AbstractItem, column_id: int,
    ) -> Optional[ui.AbstractValueModel]:
        """Dispatch to the item's lazy ``SimpleStringModel`` accessors.

        ``column_id`` 0/1/2 → name/size/date. Any other ID returns
        ``None`` — the delegate will render an empty cell, matching
        Kit's behaviour for unrecognised column IDs.
        """
        if not isinstance(item, FileItem):
            return None
        if column_id == 0:
            return item.get_name_model()
        if column_id == 1:
            return item.get_size_model()
        if column_id == 2:
            return item.get_date_model()
        return None

    # ── Filter API ────────────────────────────────────────────────────────────

    def set_asset_type_whitelist(
        self, categories: Optional[Set[AssetCategory]],
    ) -> None:
        """Restrict leaf visibility to these asset categories.

        ``None`` or an empty set resets to "allow all"; any non-empty
        set restricts leaves to members of that set. Folders are
        unaffected so the user can still descend into a subtree.
        Triggers a deferred ``item_changed`` on the current root so any
        visible tree refreshes.

        Step 28 (the content browser implementation step F) folds the empty-set case into the
        None case so :class:`FilterButton`'s
        ``on_filter_changed(set())`` — emitted when the user unchecks
        every dropdown item — reads as "no filter" rather than "hide
        everything". Passing a concrete empty container from the UI
        layer was otherwise indistinguishable from "the user wants
        nothing to match".
        """
        if not categories:
            self._asset_type_whitelist = None
        else:
            self._asset_type_whitelist = set(categories)
        self._schedule_item_changed(self._root)

    def set_glob_filter(self, patterns: Optional[List[str]]) -> None:
        """Restrict leaf visibility to basenames matching any ``fnmatch`` glob.

        the content browser implementation step 49 — the file picker's extension combo drives
        this setter. ``patterns`` is a list of ``fnmatch`` glob strings
        (``"*.usd"``, ``"*.usda"``, ...); a leaf passes when its
        basename matches at least one entry (logical OR across patterns,
        AND with every other active filter via composition in
        :meth:`get_item_children`).

        Normalisation:

        * ``None`` / empty list → no filter (view behaves as before).
        * Entries are stripped; blank entries are dropped.
        * Patterns are lowered once here and matched against a lowered
          basename in :meth:`get_item_children` so the filter is
          case-insensitive on every platform (``fnmatch.fnmatch`` is
          case-sensitive on POSIX + case-insensitive on Windows —
          lowering both sides removes that divergence).
        * A list containing ``"*.*"`` is treated as the "All files"
          sentinel and reduces to no filter — matches the
          the content browser implementation step 49 bullet *"``*.*`` (All files) → no
          filter"*. Without this carve-out ``"*.*"`` would filter out
          extension-less leaves (``Makefile``, ``LICENSE``), which is
          the opposite of what the combo's "All files" entry promises.

        Folders are always allowed regardless of the glob so the user
        can still descend into a subtree.

        Triggers a deferred ``item_changed`` on the current root so any
        visible tree refreshes on the next frame.
        """
        cleaned: List[str] = []
        for pattern in patterns or []:
            stripped = (pattern or "").strip()
            if not stripped:
                continue
            if stripped == "*.*":
                # "All files" sentinel — reduce to no filter regardless
                # of any other pattern in the list. The combo's
                # "All files" entry is conventionally a lone ``*.*``,
                # but a caller that mixes it with a concrete glob still
                # gets the intuitive "show everything" behaviour.
                cleaned = []
                break
            cleaned.append(stripped.lower())
        self._glob_patterns = cleaned
        self._schedule_item_changed(self._root)

    @property
    def glob_filter(self) -> List[str]:
        """Current glob-filter patterns (empty list = no filter).

        Returns a fresh copy so callers can mutate without affecting
        the model's internal state. Exposed mainly for tests — the UI
        layer drives the filter through :meth:`set_glob_filter` and
        reads through the file-picker combo, not this property.
        """
        return list(self._glob_patterns)

    def set_text_filter(self, text: str) -> None:
        """Set the case-insensitive substring filter for leaf names.

        Empty string ``""`` disables the filter. The filter is applied
        to every visible item; matching is ``text.lower() in
        item.name.lower()``.
        """
        self._text_filter = text
        self._schedule_item_changed(self._root)

    def set_show_hidden(self, value: bool) -> None:
        """Toggle visibility of hidden entries (basenames starting ``.``)."""
        self._show_hidden = bool(value)
        self._schedule_item_changed(self._root)

    def set_sort_policy(self, policy: str) -> None:
        """Change the sort order used for :meth:`get_item_children`.

        Accepts any string; only the six :class:`FileBrowserSortPolicy`
        constants affect behaviour, and an unknown value falls through
        to name-ascending order in :meth:`_sort_children`.
        """
        self._sort_policy = policy
        self._schedule_item_changed(self._root)

    @property
    def sort_policy(self) -> str:
        """The active sort policy — one of :class:`FileBrowserSortPolicy`.

        Exposed so the delegate's header renderer can choose the right
        arrow without reaching into ``_sort_policy``.
        """
        return self._sort_policy

    @property
    def text_filter(self) -> str:
        """Current case-insensitive substring filter (empty = no filter).

        Exposed for Step 29 :class:`HighlightLabel` wiring — the Name-
        column delegate and :class:`FileCard` read this to decide
        whether to paint a plain :class:`ui.Label` or an alternating-
        label highlighter for the item's name.
        """
        return self._text_filter

    @property
    def last_error(self) -> BackendResult:
        """Result code from the most recent populate through :meth:`get_item_children`.

        Reset to :attr:`BackendResult.OK` on construction and on every
        :meth:`set_root_url`. Updated on each populate — so the value is
        the last populate's outcome on whatever item was queried.
        Callers that specifically want the root's result should call
        ``get_item_children(self.root)`` and read this property
        immediately afterwards, which is the pattern
        :meth:`FileBrowserWidget._update_empty_state` uses for the
        empty-state / error overlay (Step 15). A dedicated per-item
        error map is deliberately not exposed — the overlay is a whole-
        pane affordance, not a per-row one.
        """
        return self._last_error

    # ── Root navigation ───────────────────────────────────────────────────────

    @property
    def root(self) -> FileItem:
        """The current root :class:`FileItem`. Always live in the cache."""
        return self._root

    @property
    def root_url(self) -> str:
        """Canonical URL of the current root (post-``normalize_url``)."""
        return self._root_url

    def set_root_url(self, url: str) -> None:
        """Swap the root and evict cache entries outside the new tree.

        Eviction is a pure-string prefix test against the normalised new
        root URL. Entries that are exact matches for the new root or
        live under it are retained; everything else is dropped. The
        lazy cache makes this cheap even for a deep previous tree.

        Dispatches ``_item_changed(None)`` rather than
        ``_item_changed(self._root)`` because the bound
        :class:`ui.TreeView` keyed its top-level cache off the *old*
        root; telling it "the new root's children changed" is a no-op
        from its perspective (it was never asking about that item).
        ``None`` is omni.ui's sentinel for "top-level children have
        changed, re-query from scratch", which is what a re-root
        actually is. Without this, the view keeps rendering the old
        root's children even after the model has moved on (the Step
        14 tree-click / detail-double-click sync would otherwise look
        visually inert even though the model state was correct).
        """
        new_url = self._backend.normalize_url(url)
        if new_url == self._root_url:
            return
        self._root_url = new_url
        # Eviction prefix: ``new_url`` itself keeps its entry; children
        # live under ``new_url + "/"``. The explicit separator check
        # prevents ``mock://Home`` from matching ``mock://Homework``.
        prefix = new_url if new_url.endswith("/") else new_url + "/"
        stale = [
            cached_url for cached_url in self._cache
            if cached_url != new_url and not cached_url.startswith(prefix)
        ]
        for cached_url in stale:
            self._cache.pop(cached_url, None)
        self._root = self._get_or_create(new_url, is_folder=True)
        # Step 15: fresh root means the previous root's populate result
        # is now irrelevant. Reset to ``OK`` so the overlay does not
        # flash an error message before the new root has had a chance
        # to populate (the next :meth:`get_item_children` call will
        # overwrite with the real result).
        self._last_error = BackendResult.OK
        self._schedule_item_changed(None)

    def resolve(self, url: str) -> Optional[FileItem]:
        """Walk from root to the :class:`FileItem` at ``url``, populating ancestors.

        Mirrors
        :meth:`ovwidgets.stage.widget.hierarchy_model.HierarchyModel.resolve_path`:
        calls :meth:`get_item_children` on each ancestor as it descends,
        which triggers a backend populate on first touch and threads the
        just-materialised child through the URL cache. The walk itself
        is filter-aware — the same folder-only / whitelist / hidden /
        text filter pipeline that drives the visible TreeView rows —
        because the Step 14 caller (``FileBrowserWidget._on_detail_double_click``)
        wants to mirror selection between the two panes and a node that
        is filtered out of the tree pane cannot be meaningfully
        "selected" there. Callers that need unfiltered resolution should
        clear the relevant filter first.

        Returns ``None`` when ``url`` is outside the current root, names
        a node that is filtered out of a visible ancestor, or points at
        a path the backend does not list. The walk stops at the first
        dead end — a missing ancestor is reported as ``None`` rather
        than raised so the caller can fall back silently (e.g. skip
        mirroring a selection that no longer exists).
        """
        target = self._backend.normalize_url(url)
        if target == self._root_url:
            return self._root

        # Target must live under the current root. Explicit separator
        # guard so ``mock://Home`` does not match ``mock://Homework``
        # (same invariant ``set_root_url`` enforces for eviction).
        root_prefix = (
            self._root_url if self._root_url.endswith("/")
            else self._root_url + "/"
        )
        if not target.startswith(root_prefix):
            return None

        current: FileItem = self._root
        # Bound the walk by the number of ``/``-separated segments in
        # the target URL: each iteration strictly descends one level,
        # so an infinite loop would require the child set to keep
        # naming prefixes of the target without ever reaching it. The
        # explicit cap defends against a pathological backend where
        # ``list_dir`` returns the folder itself as a child.
        for _ in range(target.count("/") + 1):
            if current.url == target:
                return current
            children = self.get_item_children(current)
            next_item: Optional[FileItem] = None
            for child in children:
                if not isinstance(child, FileItem):
                    continue
                if child.url == target:
                    return child
                child_prefix = (
                    child.url if child.url.endswith("/") else child.url + "/"
                )
                if target.startswith(child_prefix):
                    next_item = child
                    break
            if next_item is None:
                return None
            current = next_item
        return None

    # ── Refresh ──────────────────────────────────────────────────────────────

    def refresh_item(self, item: FileItem) -> None:
        """Mark ``item`` stale; next :meth:`get_item_children` repopulates.

        The populate happens lazily — on the next UI query — not
        immediately. That way multiple ``refresh_item`` calls in the
        same frame collapse to one backend round-trip. The
        ``item_changed`` dispatch is the signal that tells the view to
        re-query.
        """
        if not isinstance(item, FileItem):
            return
        item.mark_dirty()
        self._schedule_item_changed(item)

    def refresh_all(self) -> None:
        """Convenience — :meth:`refresh_item` on the current root."""
        self.refresh_item(self._root)

    # ── Drag-drop (Step 38) ───────────────────────────────────────────────────

    def drop(
        self,
        target_item: Optional[FileItem],
        urls_str: str,
        is_copy: bool = False,
        on_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        """Move or copy ``urls_str`` URLs into the folder named by ``target_item``.

        See the content browser behavior (internal drag-drop) and
        §27.5 (Move-vs-Copy split). ``urls_str`` is the newline-joined
        payload that :meth:`omni.ui.Widget.set_drag_fn` returns from the
        drag source — this method splits on ``"\\n"`` and processes each
        URL against the same backend the model holds.

        Semantics:

        * ``target_item is None`` or ``target_item`` is a folder — the
          drop lands in that folder. ``None`` targets the model's
          current root (the "empty space in the detail pane" case per
          the content browser implementation step 38).
        * ``target_item`` is a file — refused silently; a file cannot
          contain children, and surfacing a warning would spam the
          status bar on an accidental near-miss drag.
        * Each source is validated against the destination:
          equal URL (drop onto self) or an ancestor of the destination
          (drop parent into its own child) is skipped per
          :meth:`_is_ancestor_or_self`. Matches Kit's
          ``copy_items`` guard (architecture §27.3).
        * ``is_copy=True`` — :meth:`BackendAdapter.copy` each surviving
          URL. ``False`` — :meth:`BackendAdapter.move`. The caller
          reads Ctrl state at drop time and passes the boolean.
        * Collision (:attr:`BackendResult.ERROR_ALREADY_EXISTS`) on
          either op spawns a :class:`ConfirmOverwriteDialog`; the
          dialog's ``on_response`` callback re-enters :meth:`_drop_next`
          to keep the batch moving. Yes-to-All / No-to-All latches the
          decision for the remaining URLs (same batched-decision pattern
          the Paste flow uses).
        * ``on_complete`` fires once after :meth:`_drop_finalize`, after
          model-internal parents have been refreshed. The widget-level
          hook lets the host refresh the sibling pane (tree vs detail)
          without coupling the model to the widget.

        Re-entrancy guard: if a drop is already in flight
        (``_drop_state is not None``) the second call silently no-ops.
        The dialog response chain drives the active batch to completion.
        Post-:meth:`destroy` (no backend) is also a silent no-op.
        """
        if self._drop_state is not None:
            return
        if self._backend is None:
            return
        raw = urls_str or ""
        urls = [u for u in raw.split("\n") if u]
        if not urls:
            return

        dst_parent_url = self._resolve_drop_target(target_item)
        if dst_parent_url is None:
            return

        # Filter sources: skip self-drops and parent→child drops. A
        # surviving source is one whose basename will land under
        # ``dst_parent_url`` without overwriting its own ancestor.
        filtered: List[str] = []
        for src in urls:
            if self._is_ancestor_or_self(src, dst_parent_url):
                continue
            filtered.append(src)
        if not filtered:
            return

        self._drop_state = _DropState(
            remaining=filtered,
            dst_parent_url=dst_parent_url,
            is_copy=is_copy,
            on_complete=on_complete,
        )
        self._drop_next()

    def _resolve_drop_target(
        self, target_item: Optional[FileItem],
    ) -> Optional[str]:
        """Return the folder URL that a drop on ``target_item`` lands in.

        * ``None`` → the model's current root (empty-space drop).
        * :class:`FileItem` folder → its URL.
        * :class:`FileItem` file → ``None`` (drop refused; files do not
          contain children).
        """
        if target_item is None:
            return self._root_url
        if not isinstance(target_item, FileItem):
            return None
        if not target_item.is_folder:
            return None
        return target_item.url

    def _is_ancestor_or_self(self, src_url: str, dst_url: str) -> bool:
        """Return True when ``src_url`` is the same as, or contains, ``dst_url``.

        Drop invariant from the content browser behavior: a source
        whose path is an ancestor of the destination must be refused —
        copying or moving a folder into one of its own descendants is
        nonsensical at the filesystem level (``shutil.move`` would
        happily recurse forever on LocalFS; Nucleus returns
        :attr:`BackendResult.ERROR`). The predicate also covers the
        degenerate self-drop case (``src_url == dst_url``) without a
        separate branch.

        Normalises both URLs via :meth:`BackendAdapter.normalize_url`
        so a trailing-slash variant does not slip past the check.
        """
        backend = self._backend
        if backend is None:
            return False
        src_norm = backend.normalize_url(src_url)
        dst_norm = backend.normalize_url(dst_url)
        if src_norm == dst_norm:
            return True
        src_prefix = src_norm if src_norm.endswith("/") else src_norm + "/"
        return dst_norm.startswith(src_prefix)

    def _drop_next(self) -> None:
        """Process the next URL in :attr:`_drop_state` or finalize.

        Synchronous fast path for collision-free / pre-decided batches
        (``overwrite_all`` latched); pauses on the first collision that
        still needs a user decision and re-enters from
        :meth:`_on_drop_overwrite_choice`. Mirrors
        :meth:`context_menu.FileContextMenu._paste_next` so the Paste
        and Drop flows share the same collision-dialog cadence.
        """
        state = self._drop_state
        if state is None:
            return
        backend = self._backend
        if backend is None:
            self._drop_finalize()
            return

        while state.remaining:
            src_url = state.remaining[0]
            name = backend.basename(src_url)
            if not name:
                state.errors.append((src_url, "ERROR_NOT_SUPPORTED"))
                state.remaining.pop(0)
                continue
            dst_url = backend.join_url(state.dst_parent_url, name)
            overwrite = state.overwrite_all is True
            if state.is_copy:
                result = backend.copy(src_url, dst_url, overwrite=overwrite)
            else:
                result = backend.move(src_url, dst_url, overwrite=overwrite)
            if result == BackendResult.OK:
                state.success_count += 1
                self._record_drop_parents(src_url, state)
                state.remaining.pop(0)
                continue
            if result == BackendResult.ERROR_ALREADY_EXISTS:
                if state.overwrite_all is True:
                    state.errors.append((src_url, result.name))
                    state.remaining.pop(0)
                    continue
                if state.overwrite_all is False:
                    state.remaining.pop(0)
                    continue
                self._open_drop_overwrite_dialog(dst_url)
                return
            state.errors.append((src_url, result.name))
            state.remaining.pop(0)

        self._drop_finalize()

    def _record_drop_parents(
        self, src_url: str, state: _DropState,
    ) -> None:
        """Queue source + destination parents for end-of-batch refresh.

        A successful drop on a move (``is_copy=False``) visibly changes
        both the source parent (source row disappears) and the
        destination parent (destination row appears). A copy only
        changes the destination, but refreshing the source parent is
        cheap enough that unconditionally recording both keeps the two
        branches symmetric — matches
        :meth:`context_menu.FileContextMenu._record_refresh_from_url`
        on the Paste side.
        """
        backend = self._backend
        if backend is None:
            return
        src_parent = backend.parent_url(src_url)
        if src_parent is not None:
            state.affected_parents.add(src_parent)
        state.affected_parents.add(state.dst_parent_url)

    def _open_drop_overwrite_dialog(self, dst_url: str) -> None:
        """Spawn a :class:`ConfirmOverwriteDialog` for a colliding ``dst_url``.

        Dismisses any in-flight dialog first so a rapid drop cannot
        stack two popups. ``multi`` is derived from whether the batch
        has items beyond the current one — a single-item drop hides
        the Yes-to-All / No-to-All buttons for a tighter dialog.
        """
        state = self._drop_state
        if state is None:
            return
        if self._drop_confirm_dialog is not None:
            try:
                self._drop_confirm_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._drop_confirm_dialog = None
        multi = len(state.remaining) > 1
        dialog = ConfirmOverwriteDialog(
            url=dst_url,
            on_response=self._on_drop_overwrite_choice,
            multi=multi,
        )
        self._drop_confirm_dialog = dialog
        dialog.show()

    def _on_drop_overwrite_choice(self, choice: "OverwriteChoice") -> None:
        """Handle the user's response to a drop-collision prompt.

        ``YES`` / ``YES_TO_ALL`` retry the current URL with
        ``overwrite=True``; ``NO`` / ``NO_TO_ALL`` skip it. ``*_TO_ALL``
        additionally latches :attr:`_DropState.overwrite_all` so the
        remaining collisions in the batch do not spawn a dialog.
        """
        self._drop_confirm_dialog = None
        state = self._drop_state
        if state is None:
            return

        if choice == OverwriteChoice.YES_TO_ALL:
            state.overwrite_all = True
        elif choice == OverwriteChoice.NO_TO_ALL:
            state.overwrite_all = False

        if choice in (OverwriteChoice.YES, OverwriteChoice.YES_TO_ALL):
            self._retry_drop_current_with_overwrite()
        else:
            if state.remaining:
                state.remaining.pop(0)

        self._drop_next()

    def _retry_drop_current_with_overwrite(self) -> None:
        """Re-issue the current URL's copy / move with ``overwrite=True``.

        Only invoked from :meth:`_on_drop_overwrite_choice` after the
        first attempt raised :attr:`BackendResult.ERROR_ALREADY_EXISTS`.
        A non-OK retry surfaces as an error and pops the URL — we do
        not re-open the dialog for the same URL because the user
        already answered.
        """
        state = self._drop_state
        if state is None:
            return
        backend = self._backend
        if backend is None or not state.remaining:
            if state.remaining:
                state.remaining.pop(0)
            return
        src_url = state.remaining[0]
        name = backend.basename(src_url)
        dst_url = backend.join_url(state.dst_parent_url, name)
        if state.is_copy:
            result = backend.copy(src_url, dst_url, overwrite=True)
        else:
            result = backend.move(src_url, dst_url, overwrite=True)
        if result == BackendResult.OK:
            state.success_count += 1
            self._record_drop_parents(src_url, state)
        else:
            state.errors.append((src_url, result.name))
        state.remaining.pop(0)

    def _drop_finalize(self) -> None:
        """End-of-batch: refresh every affected parent and fire ``on_complete``.

        Refresh is keyed by URL via :meth:`resolve`; a parent that is
        not in the model's cache (drop happened outside the current
        subtree) falls back to :meth:`refresh_all` so the UI still
        repaints. ``on_complete`` fires last so the widget can cascade
        a refresh to the sibling pane after this model's own refresh
        has been scheduled.
        """
        state = self._drop_state
        self._drop_state = None
        if state is None:
            return
        for parent_url in state.affected_parents:
            self._refresh_drop_parent(parent_url)
        if state.on_complete is not None:
            try:
                state.on_complete()
            except Exception:  # noqa: BLE001
                # A crashing post-drop hook must not leave the model in
                # a half-finalized state. The hook is widget-side glue
                # (refresh the other pane) — a failure there is best
                # surfaced as a log than as a crash into the drop
                # driver.
                pass

    def _refresh_drop_parent(self, parent_url: str) -> None:
        """Mark ``parent_url`` dirty in this model so dropped rows repaint.

        Falls back to :meth:`refresh_all` when ``parent_url`` is not in
        the cache — the drop may have affected a folder outside the
        currently-rooted subtree (e.g. a tree-pane drop into a sibling
        folder of the detail root). Matching
        :meth:`context_menu.FileContextMenu._refresh_parent_after_create`.
        """
        parent_item = self.resolve(parent_url)
        if parent_item is not None:
            self.refresh_item(parent_item)
        else:
            self.refresh_all()

    # ── Backend change events (Step 16) ───────────────────────────────────────

    def _on_backend_change(self, event: BackendChangeEvent) -> None:
        """Apply a :class:`BackendChangeEvent` to the cached tree.

        Matches the content browser behavior ``event.url`` names
        the *parent* folder where a child was created / deleted /
        updated; the entry's ``name`` identifies the child. Lookups go
        through the URL → :class:`FileItem` cache so only folders the
        user has actually observed receive updates — an event for a
        folder that was never visited is dropped silently. When the
        user eventually navigates there, :meth:`FileItem.populate`
        fetches the current state directly from the backend and the
        missed event is irrelevant.

        Event-type contract:

        * ``"created"`` → build a fresh :class:`FileItem` from the
          payload and add it under the target. URL-keyed cache
          updated so :meth:`resolve` can find it.
        * ``"deleted"`` → detach the named child (``remove_child``
          uses ``dict.pop`` so a concurrent iterator does not raise)
          and drop its URL from the cache.
        * ``"updated"`` → find the existing child by name and call
          :meth:`FileItem.update_metadata` — pushes fresh size/date
          strings into any already-bound ``SimpleStringModel`` so the
          view repaints.

        Unknown event types (e.g. ``"obliterated"``) or events without
        an ``entry`` are dropped without scheduling a dispatch —
        following the the content browser behavior rule that
        consumers ignore event types they do not understand.

        Finally, :meth:`_schedule_item_changed` is invoked on the
        target so the existing §5.7 batching path folds a burst of
        events into one view refresh per frame.
        """
        target_item = self._cache.get(event.url)
        if target_item is None or not target_item.is_folder:
            return
        entry = event.entry
        if entry is None:
            return

        if event.event_type == "created":
            child_url = self._backend.join_url(target_item.url, entry.name)
            is_folder = bool(entry.flags & BackendFileFlags.IS_FOLDER)
            new_child = FileItem(
                url=child_url,
                name=entry.name,
                is_folder=is_folder,
                size=entry.size,
                modified=entry.modified_time,
                parent=target_item,
            )
            target_item.add_child(new_child)
            self._cache[child_url] = new_child
        elif event.event_type == "deleted":
            removed = target_item.remove_child(entry.name)
            if removed is not None:
                # Drop the URL from the cache so a subsequent
                # :meth:`resolve` does not fish out the detached item.
                # Descendants in the cache become unreachable via the
                # tree but are left alone — if the user re-creates a
                # folder of the same name they'll be overwritten by a
                # fresh populate at that level.
                self._cache.pop(removed.url, None)
        elif event.event_type == "updated":
            for child in target_item.children:
                if child.name == entry.name:
                    child.update_metadata(entry)
                    break
            else:
                # No matching child — nothing to update, and nothing
                # visually changed, so skip the dispatch too.
                return
        else:
            return

        self._schedule_item_changed(target_item)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Release the backend subscription and any pending dispatch.

        Idempotent — the attribute guards below short-circuit a second
        call. :meth:`FileBrowserWidget.destroy` and
        :meth:`FileBrowserWidget.set_backend` invoke this so the
        backend's subscriber list stops pinning the model alive via
        :meth:`_on_backend_change` once the widget has moved on.

        Pending ``call_later`` handles are cancelled to prevent a
        stale flush from firing after the widget is torn down; the
        pending-item set is cleared for the same reason.
        """
        if self._change_sub is not None:
            self._change_sub.cancel()
            self._change_sub = None
        if self._item_changed_handle is not None:
            self._item_changed_handle.cancel()
            self._item_changed_handle = None
        self._pending_item_changed.clear()
        # Step 38 — dismiss any live drop-overwrite dialog so a late
        # response cannot re-enter :meth:`_on_drop_overwrite_choice`
        # after the model has been torn down. Clearing ``_drop_state``
        # is a belt-and-braces guard: the state-keyed guards inside
        # :meth:`_drop_next` already refuse to dispatch when the state
        # is ``None``.
        if self._drop_confirm_dialog is not None:
            try:
                self._drop_confirm_dialog.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._drop_confirm_dialog = None
        self._drop_state = None

    # ── Cache access (internal) ───────────────────────────────────────────────

    def _get_or_create(self, url: str, is_folder: bool) -> FileItem:
        """Return the cached :class:`FileItem` for ``url``, creating if absent.

        The ``is_folder`` argument is only honoured when creating —
        existing cache entries are returned as-is regardless of the
        requested flag, because the backend's ``IS_FOLDER`` bit is
        authoritative and ``_get_or_create`` is not meant to rewrite an
        item's type. Callers that need to change the type should evict
        first.

        Root-level URLs without a basename (e.g. ``mock://`` or
        ``file:///``) fall back to the full URL as display name so the
        view is never asked to render a blank label.
        """
        existing = self._cache.get(url)
        if existing is not None:
            return existing
        name = self._backend.basename(url)
        if not name:
            name = url
        item = FileItem(url=url, name=name, is_folder=is_folder)
        self._cache[url] = item
        return item

    def _schedule_item_changed(self, item: Optional[FileItem]) -> None:
        """Queue ``item`` for a deferred ``_item_changed`` dispatch.

        Idempotent per frame: a second call while a flush is pending
        simply adds to the set; the next frame flushes all accumulated
        items in one pass. Matches the content browser behavior
        throttling semantics.

        ``item`` may be ``None`` — that routes the dispatch to
        ``_item_changed(None)``, omni.ui's sentinel for "the top-
        level children changed, re-query from scratch". Used by
        :meth:`set_root_url` so a re-root actually reaches the
        bound :class:`ui.TreeView` (the view does not know about the
        new root item until the None-dispatch lands).

        If the :class:`ovwidgets.app.application.Application` singleton is not
        available (e.g. in a pure-Python unit test that hasn't built
        one), we fall back to immediate dispatch. Tests that need the
        deferred path explicitly construct an ``Application`` fixture.
        """
        self._pending_item_changed.add(item)
        if self._item_changed_handle is not None:
            return

        # Late-bind the import so this module does not pull the common
        # scheduler into every test that just imports the class for a
        # static helper call (e.g. ``_natural_sort_key``).
        from ovwidgets.common import scheduler as _scheduler

        try:
            self._item_changed_handle = _scheduler.call_later(
                0.0, self._flush_item_changed
            )
        except RuntimeError:
            self._flush_item_changed()
            return

    def _schedule_thumbnail_populate(self, parent: FileItem) -> None:
        """Defer a :meth:`_populate_thumbnails` pass to the next frame.

        Step 25 (the content browser behavior). A folder's thumb
        directory ``<parent>/.thumbs/256x256`` is a separate
        ``list_dir`` call — running it inline inside
        :meth:`get_item_children` would double the backend round-trips
        the first time the user enters a folder. Deferring via
        :meth:`ovwidgets.app.application.Application.call_later` splits the two
        calls across frames: the default-icon grid paints first, then
        the thumbnail swap lands on the next tick.

        Falls back to immediate execution when no scheduler is registered
        (same pattern :meth:`_schedule_item_changed` uses), so unit tests
        that do not spin up an :class:`ovwidgets.app.application.Application`
        still exercise the discovery path.
        """
        from ovwidgets.common import scheduler as _scheduler

        try:
            _scheduler.call_later(0.0, lambda: self._populate_thumbnails(parent))
        except RuntimeError:
            self._populate_thumbnails(parent)
            return

    def _populate_thumbnails(self, parent: FileItem) -> None:
        """Look up ``<parent>/.thumbs/256x256`` and attach thumbnails.

        Step 25 (the content browser behavior — manual wins over
        auto). For every leaf child that does not already carry a
        ``custom_thumbnail``, match against entries in the thumb dir:
        first ``<name>.png`` (manual), then ``<name>.auto.png``
        (generator fallback). On match, call
        :meth:`FileItem.set_custom_thumbnail` with the full URL of the
        thumbnail asset — the card (:class:`FileCard`) consumes this on
        its next build.

        Contract:

        * Missing thumb directory (any non-``OK`` result from
          ``list_dir``) is a silent no-op — folders without authored
          thumbnails simply display default icons. No log or error; the
          empty case is the common case.
        * Already-thumbnailed children are skipped so a repeat populate
          does not re-fire ``_on_thumbnail_changed`` uselessly.
        * Folders are skipped — a stray ``Subdir.png`` in ``.thumbs/``
          must not hijack the folder icon.
        * Every other leaf is eligible regardless of asset category.
          Real-world ``.thumbs/256x256`` directories (Kit / Nucleus
          convention — architecture §10.2) carry previews for USD, FBX,
          MDL, and image assets alike; restricting discovery to
          :attr:`AssetCategory.IMAGE` hid every authored preview for
          the 3D asset types users most want to preview (Bug 10).
        * :meth:`_schedule_item_changed` fires once after the loop so a
          folder-full of thumbnail assignments collapses into a single
          view refresh.

        ``list_dir`` on a non-existent thumb folder returns
        :attr:`BackendResult.ERROR_NOT_FOUND` (both
        :class:`ovwidgets.app.testing.MockBackend` and
        :class:`ovwidgets.content.backends.local_fs.LocalFSBackend` agree); the
        early-return below absorbs every non-OK result so a future
        backend that returns a different code (``ERROR_ACCESS_DENIED``
        for a permission-denied thumb dir) is also quietly absorbed.
        """
        thumbs_url = self._backend.join_url(parent.url, _THUMBNAIL_DIR_SUFFIX)
        result, entries = self._backend.list_dir(thumbs_url)
        if result is not BackendResult.OK:
            return

        thumbs_by_name = {entry.name: entry for entry in entries}

        changed = False
        for child in parent.children:
            if child.is_folder:
                continue
            if child.custom_thumbnail is not None:
                continue

            manual_name = child.name + ".png"
            auto_name = child.name + ".auto.png"

            match_name: Optional[str] = None
            if manual_name in thumbs_by_name:
                match_name = manual_name
            elif auto_name in thumbs_by_name:
                match_name = auto_name

            if match_name is None:
                continue

            child.set_custom_thumbnail(
                self._backend.join_url(thumbs_url, match_name),
            )
            changed = True

        if changed:
            self._schedule_item_changed(parent)

    def _flush_item_changed(self) -> None:
        """Drain the pending set and dispatch one ``_item_changed`` per item.

        The set is snapshot-and-cleared before dispatch so a re-entrant
        handler that triggers another ``_schedule_item_changed`` does
        not double-dispatch this frame — the new item lands in a fresh
        pending set and schedules its own flush.
        """
        self._item_changed_handle = None
        items = list(self._pending_item_changed)
        self._pending_item_changed.clear()
        for item in items:
            self._item_changed(item)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _is_hidden(self, item: FileItem) -> bool:
        """Return True if ``item``'s basename starts with ``.``.

        Uses the backend's ``basename`` rather than the ``FileItem``'s
        ``name`` property so URL-encoded oddities (percent-escaped
        dots, etc.) round-trip through the same logic the backend uses
        for stat / list_dir. In practice for the local-FS and mock
        backends the two are equivalent; routing through ``backend``
        makes the model behaviour backend-defined rather than
        string-manipulation defined.
        """
        basename = self._backend.basename(item.url)
        if basename:
            return basename.startswith(".")
        return item.name.startswith(".")

    def _sort_children(self, children: List[FileItem]) -> List[FileItem]:
        """Return ``children`` sorted folders-first, then per sort policy.

        Folders and files are sorted separately so folders always come
        first regardless of the active sort field. For ``DATE_*`` and
        ``SIZE_*`` policies the folder group is tie-broken by name
        (folders have size 0 and share a timestamp on many backends, so
        the raw field would not produce a stable order).
        """
        folders = [c for c in children if c.is_folder]
        files = [c for c in children if not c.is_folder]

        # Table-driven dispatch: ``(file_key, reverse)`` per policy.
        # Folders always sort by name (ascending for ASC / name-based
        # policies, descending only for NAME_DESC) so their within-group
        # order is stable even when the active field would tie.
        name_key = lambda c: _natural_sort_key(c.name)  # noqa: E731
        file_key_table = {
            FileBrowserSortPolicy.NAME_ASC:  (name_key, False),
            FileBrowserSortPolicy.NAME_DESC: (name_key, True),
            FileBrowserSortPolicy.DATE_ASC:  (lambda c: c.modified, False),
            FileBrowserSortPolicy.DATE_DESC: (lambda c: c.modified, True),
            FileBrowserSortPolicy.SIZE_ASC:  (lambda c: c.size, False),
            FileBrowserSortPolicy.SIZE_DESC: (lambda c: c.size, True),
        }
        file_key, reverse = file_key_table.get(
            self._sort_policy, (name_key, False),
        )

        folder_reverse = self._sort_policy == FileBrowserSortPolicy.NAME_DESC
        folders.sort(key=name_key, reverse=folder_reverse)
        files.sort(key=file_key, reverse=reverse)

        return folders + files
