# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""In-memory :class:`BackendAdapter` for tests (``mock://`` scheme).

See the content browser behavior and the content browser implementation step 3.

``MockBackend`` is the content-browser counterpart of
:class:`MockStageAdapter`: a fully self-contained
implementation of :class:`BackendAdapter` backed by a dict tree so
tests can exercise stat / list / copy / move / delete without touching
the real filesystem. The default tree is deliberately small and
deterministic (fixed timestamps, known sizes) so test assertions can
name exact counts and flags without fragile FS dependencies.

Error injection is provided via :attr:`MockBackend._errors`. Any
operation whose target URL matches a key in that dict returns the
mapped :class:`BackendResult` instead of touching the tree — the
clean way to verify ``ERROR_ACCESS_DENIED`` / ``ERROR_CONNECTION``
handling without twisting real permissions.

Change events: the content browser implementation step 16 wires a real subscriber list so
tests can drive the :class:`FileBrowserModel` auto-refresh path. A
callback registered through :meth:`subscribe_changes` is fired when a
test calls :meth:`emit_change` with the matching URL. The default tree
is *not* mutated by :meth:`emit_change` — callers explicitly drive
both the tree state and the event emission when the two need to stay
consistent, so tests can verify divergence scenarios too.
"""

import weakref
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from ovui_data_adapters.services.settings import Subscription
from ovui_data_adapters.services.content.backends.backend_adapter import (
    BackendAdapter,
    BackendChangeEvent,
    BackendFileFlags,
    BackendListEntry,
    BackendResult,
)

# ``mock://`` scheme prefix. URLs are parsed strictly — anything not
# starting with this prefix is not supported.
_SCHEME = "mock://"

# Deterministic base timestamps for the default tree (2026-01-01 UTC).
# A single value keeps assertions simple; tests that care about
# ordering can override per-entry by passing a custom ``root``.
_BASE_TIME = 1767225600.0


# ──────────────────────────────────────────────────────────────────────────────
# In-memory tree node
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _MockEntry:
    """One node in the :class:`MockBackend` tree.

    ``children`` is an ordered ``dict`` (Python 3.7+ preserves
    insertion order), which gives :meth:`MockBackend.list_dir` a stable
    output order. ``parent`` is a back-reference used to detach nodes
    during move / delete.
    """

    name: str
    is_folder: bool
    size: int = 0
    modified: float = _BASE_TIME
    created: float = _BASE_TIME
    children: Dict[str, "_MockEntry"] = field(default_factory=dict)
    parent: Optional["_MockEntry"] = field(default=None, repr=False)


# ──────────────────────────────────────────────────────────────────────────────
# Default tree — matches the content browser implementation step 3
# ──────────────────────────────────────────────────────────────────────────────

def _build_default_tree() -> _MockEntry:
    """Construct the tree used by ``MockBackend()`` with no argument.

    Layout::

        mock://
          Home/
            Documents/
              Projects/
                demo.usda     (128 bytes)
                demo.usdc     (2048 bytes)
                readme.md     (512 bytes)
            Textures/
              concrete.png    (1.2 MB)
              metal.hdr       (4.5 MB)
            Scripts/
              test.py         (1 KB)
            .hidden_folder/
              secret.txt
          Shared/             (empty)
    """
    root = _MockEntry(name="", is_folder=True)

    def _add(parent: _MockEntry, name: str, is_folder: bool,
             size: int = 0) -> _MockEntry:
        entry = _MockEntry(
            name=name, is_folder=is_folder, size=size, parent=parent,
        )
        parent.children[name] = entry
        return entry

    home = _add(root, "Home", is_folder=True)
    _add(root, "Shared", is_folder=True)  # stays empty

    documents = _add(home, "Documents", is_folder=True)
    textures = _add(home, "Textures", is_folder=True)
    scripts = _add(home, "Scripts", is_folder=True)
    hidden = _add(home, ".hidden_folder", is_folder=True)

    projects = _add(documents, "Projects", is_folder=True)
    _add(projects, "demo.usda", is_folder=False, size=128)
    _add(projects, "demo.usdc", is_folder=False, size=2048)
    _add(projects, "readme.md", is_folder=False, size=512)

    _add(textures, "concrete.png", is_folder=False, size=1_258_291)  # 1.2 MB
    _add(textures, "metal.hdr", is_folder=False, size=4_718_592)     # 4.5 MB

    _add(scripts, "test.py", is_folder=False, size=1024)

    _add(hidden, "secret.txt", is_folder=False, size=16)

    return root


# ──────────────────────────────────────────────────────────────────────────────
# URL parsing (pure — no backend state)
# ──────────────────────────────────────────────────────────────────────────────

def _url_to_parts(url: str) -> Optional[List[str]]:
    """Split a ``mock://`` URL into its path components.

    Returns ``None`` if ``url`` lacks the ``mock://`` scheme. A root
    URL (``mock://`` or ``mock:///``) yields an empty list. Empty
    components (from double or trailing slashes) are filtered out.
    """
    if not url.startswith(_SCHEME):
        return None
    tail = url[len(_SCHEME):]
    return [part for part in tail.split("/") if part]


def _parts_to_url(parts: List[str]) -> str:
    """Re-assemble ``parts`` into a canonical ``mock://`` URL."""
    return _SCHEME + "/".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# Tree helpers (pure — used by copy / merge)
# ──────────────────────────────────────────────────────────────────────────────

def _clone_tree(
    node: _MockEntry, new_name: str, parent: _MockEntry,
) -> _MockEntry:
    """Deep-copy ``node`` under ``parent`` with ``new_name``.

    Sizes and timestamps are preserved; parent back-refs are rebuilt as
    children are cloned so the result is a self-consistent subtree.
    """
    clone = _MockEntry(
        name=new_name,
        is_folder=node.is_folder,
        size=node.size,
        modified=node.modified,
        created=node.created,
        parent=parent,
    )
    for child in node.children.values():
        clone.children[child.name] = _clone_tree(child, child.name, clone)
    return clone


def _merge_tree(src: _MockEntry, dst: _MockEntry) -> None:
    """Merge ``src``'s children into ``dst`` in place.

    Counterpart to ``shutil.copytree(dirs_exist_ok=True)`` used by
    :meth:`LocalFSBackend.copy` on folder-overwrite: folder children
    that collide are merged recursively; file children and
    folder-vs-file collisions are replaced by a fresh clone.
    """
    for name, child in list(src.children.items()):
        existing = dst.children.get(name)
        if child.is_folder and existing is not None and existing.is_folder:
            _merge_tree(child, existing)
        else:
            if existing is not None:
                existing.parent = None
            dst.children[name] = _clone_tree(child, name, dst)


# ──────────────────────────────────────────────────────────────────────────────
# MockBackend
# ──────────────────────────────────────────────────────────────────────────────

class MockBackend(BackendAdapter):
    """In-memory :class:`BackendAdapter` keyed on ``mock://``.

    Pass a custom ``root`` to drive tests against a bespoke tree shape;
    otherwise the default tree (see :func:`_build_default_tree`) is
    used.

    Error injection: set ``backend._errors[url] = BackendResult.X`` to
    make the next operation against ``url`` short-circuit and return
    ``X`` instead of touching the tree. Match is by exact URL string —
    tests should use the same form (trailing slash / scheme) they pass
    to the operation under test.
    """

    SCHEME = _SCHEME

    def __init__(self, root: Optional[_MockEntry] = None) -> None:
        self._root: _MockEntry = (
            root if root is not None else _build_default_tree()
        )
        self._errors: Dict[str, BackendResult] = {}
        # URL → list of active callbacks. Populated by :meth:`subscribe_changes`,
        # drained by :meth:`emit_change`, pruned by
        # :meth:`_remove_subscriber` when a :class:`Subscription` is
        # cancelled. Empty lists are dropped so the dict stays small
        # across test-driven subscribe/cancel churn.
        self._subscribers: Dict[
            str, List[Callable[[BackendChangeEvent], None]]
        ] = {}

    # ── Internal helpers ──

    def _find(
        self, url: str,
    ) -> Tuple[Optional[_MockEntry], Optional[BackendResult]]:
        """Resolve ``url`` to a tree node.

        Returns ``(entry, None)`` on success, ``(None,
        ERROR_NOT_SUPPORTED)`` if ``url`` is not a mock URL, or
        ``(None, ERROR_NOT_FOUND)`` if the path does not exist.
        """
        parts = _url_to_parts(url)
        if parts is None:
            return (None, BackendResult.ERROR_NOT_SUPPORTED)
        node = self._root
        for part in parts:
            if not node.is_folder:
                return (None, BackendResult.ERROR_NOT_FOUND)
            child = node.children.get(part)
            if child is None:
                return (None, BackendResult.ERROR_NOT_FOUND)
            node = child
        return (node, None)

    def _to_entry(self, node: _MockEntry) -> BackendListEntry:
        """Snapshot a ``_MockEntry`` as the public
        :class:`BackendListEntry`. Mock entries are always readable and
        writable; no symlinks exist in this world.
        """
        flags = BackendFileFlags.IS_READABLE | BackendFileFlags.IS_WRITABLE
        if node.is_folder:
            flags |= BackendFileFlags.IS_FOLDER
        if node.name.startswith("."):
            flags |= BackendFileFlags.IS_HIDDEN
        return BackendListEntry(
            name=node.name,
            flags=flags,
            size=node.size,
            modified_time=node.modified,
            created_time=node.created,
        )

    def _check_injected(self, url: str) -> Optional[BackendResult]:
        """Return the injected error for ``url`` (if any). Exact-string
        match — callers and tests must agree on the URL form."""
        return self._errors.get(url)

    # ── Scheme support ──

    def supports_url(self, url: str) -> bool:
        return bool(url) and url.startswith(_SCHEME)

    # ── Reads ──

    def stat(
        self, url: str,
    ) -> Tuple[BackendResult, Optional[BackendListEntry]]:
        err = self._check_injected(url)
        if err is not None:
            return (err, None)
        node, nerr = self._find(url)
        if nerr is not None:
            return (nerr, None)
        assert node is not None
        return (BackendResult.OK, self._to_entry(node))

    def list_dir(
        self, url: str,
    ) -> Tuple[BackendResult, List[BackendListEntry]]:
        err = self._check_injected(url)
        if err is not None:
            return (err, [])
        node, nerr = self._find(url)
        if nerr is not None:
            return (nerr, [])
        assert node is not None
        if not node.is_folder:
            return (BackendResult.ERROR, [])
        return (
            BackendResult.OK,
            [self._to_entry(child) for child in node.children.values()],
        )

    # ── Writes ──

    def create_folder(self, url: str) -> BackendResult:
        err = self._check_injected(url)
        if err is not None:
            return err
        parts = _url_to_parts(url)
        if parts is None:
            return BackendResult.ERROR_NOT_SUPPORTED
        if not parts:
            # Attempt to create the root itself.
            return BackendResult.ERROR_ALREADY_EXISTS
        parent_parts, name = parts[:-1], parts[-1]
        parent, perr = self._find(_parts_to_url(parent_parts))
        if perr is not None:
            return perr
        assert parent is not None
        if not parent.is_folder:
            return BackendResult.ERROR
        if name in parent.children:
            return BackendResult.ERROR_ALREADY_EXISTS
        parent.children[name] = _MockEntry(
            name=name, is_folder=True, parent=parent,
        )
        return BackendResult.OK

    def copy(
        self, src_url: str, dst_url: str, overwrite: bool = False,
    ) -> BackendResult:
        err = self._check_injected(src_url)
        if err is not None:
            return err
        err = self._check_injected(dst_url)
        if err is not None:
            return err
        src, serr = self._find(src_url)
        if serr is not None:
            return serr
        assert src is not None
        dst_parts = _url_to_parts(dst_url)
        if dst_parts is None:
            return BackendResult.ERROR_NOT_SUPPORTED
        if not dst_parts:
            return BackendResult.ERROR_ALREADY_EXISTS  # root always exists
        dst_parent_parts, dst_name = dst_parts[:-1], dst_parts[-1]
        dst_parent, dperr = self._find(_parts_to_url(dst_parent_parts))
        if dperr is not None:
            return dperr
        assert dst_parent is not None
        if not dst_parent.is_folder:
            return BackendResult.ERROR
        existing = dst_parent.children.get(dst_name)
        if existing is not None and not overwrite:
            return BackendResult.ERROR_ALREADY_EXISTS
        if (existing is not None and src.is_folder and existing.is_folder):
            # Folder-over-folder with overwrite → merge
            # (matches shutil.copytree(dirs_exist_ok=True) used by
            # LocalFSBackend.copy).
            _merge_tree(src, existing)
        else:
            if existing is not None:
                existing.parent = None
            dst_parent.children[dst_name] = _clone_tree(
                src, dst_name, dst_parent,
            )
        return BackendResult.OK

    def move(
        self, src_url: str, dst_url: str, overwrite: bool = False,
    ) -> BackendResult:
        err = self._check_injected(src_url)
        if err is not None:
            return err
        err = self._check_injected(dst_url)
        if err is not None:
            return err
        src, serr = self._find(src_url)
        if serr is not None:
            return serr
        assert src is not None
        if src.parent is None:
            return BackendResult.ERROR  # cannot move the root
        dst_parts = _url_to_parts(dst_url)
        if dst_parts is None:
            return BackendResult.ERROR_NOT_SUPPORTED
        if not dst_parts:
            return BackendResult.ERROR_ALREADY_EXISTS  # root always exists
        dst_parent_parts, dst_name = dst_parts[:-1], dst_parts[-1]
        dst_parent, dperr = self._find(_parts_to_url(dst_parent_parts))
        if dperr is not None:
            return dperr
        assert dst_parent is not None
        if not dst_parent.is_folder:
            return BackendResult.ERROR
        # Refuse to move a node into itself or one of its descendants.
        ancestor: Optional[_MockEntry] = dst_parent
        while ancestor is not None:
            if ancestor is src:
                return BackendResult.ERROR
            ancestor = ancestor.parent
        existing = dst_parent.children.get(dst_name)
        if existing is src:
            # Moving src onto itself — nothing to do.
            return BackendResult.OK
        if existing is not None:
            if not overwrite:
                return BackendResult.ERROR_ALREADY_EXISTS
            # Replace (not merge) — matches LocalFSBackend.move with
            # overwrite=True, which strips the destination before
            # shutil.move to prevent the "move inside" default.
            existing.parent = None
            del dst_parent.children[dst_name]
        # Unlink src from its old parent, re-link under dst_parent.
        old_parent = src.parent
        del old_parent.children[src.name]
        src.parent = dst_parent
        src.name = dst_name
        dst_parent.children[dst_name] = src
        return BackendResult.OK

    def delete(self, url: str) -> BackendResult:
        err = self._check_injected(url)
        if err is not None:
            return err
        node, nerr = self._find(url)
        if nerr is not None:
            return nerr
        assert node is not None
        if node.parent is None:
            return BackendResult.ERROR  # cannot delete the root
        parent = node.parent
        del parent.children[node.name]
        node.parent = None
        return BackendResult.OK

    # ── URL utilities ──

    def normalize_url(self, url: str) -> str:
        parts = _url_to_parts(url)
        if parts is None:
            return url  # not a mock URL — pass through unchanged
        resolved: List[str] = []
        for part in parts:
            if part == ".":
                continue
            if part == "..":
                if resolved:
                    resolved.pop()
                continue
            resolved.append(part)
        return _parts_to_url(resolved)

    def join_url(self, base: str, child: str) -> str:
        base_parts = _url_to_parts(base)
        if base_parts is None:
            # Base is not a mock URL — treat as opaque string join.
            sep = "" if base.endswith("/") else "/"
            return f"{base}{sep}{child}"
        child_parts = [p for p in child.split("/") if p]
        return self.normalize_url(_parts_to_url(base_parts + child_parts))

    def parent_url(self, url: str) -> Optional[str]:
        parts = _url_to_parts(url)
        if parts is None or not parts:
            return None
        return _parts_to_url(parts[:-1])

    def basename(self, url: str) -> str:
        parts = _url_to_parts(url)
        if parts is None or not parts:
            return ""
        return parts[-1]

    # ── Live updates ──

    def subscribe_changes(
        self,
        url: str,
        callback: Callable[[BackendChangeEvent], None],
    ) -> Subscription:
        """Register ``callback`` for :meth:`emit_change` events on ``url``.

        Overrides the ABC's no-op default with a real subscriber list
        so the content browser implementation step 16 can drive :class:`FileBrowserModel`'s
        auto-refresh path from tests. Match is by exact URL string —
        the subscriber for ``mock://Home`` does not receive events
        emitted against ``mock://Home/Documents``. A later step can
        add URL-prefix dispatch if a real filesystem watcher lands.

        The returned object duck-types
        :class:`ovui_data_adapters.services.settings.Subscription` — tests can hold it,
        drop it, or call :meth:`~Subscription.cancel` explicitly.
        ``__del__`` also cancels so a subscription that only exists
        in a local variable cleans up when the variable goes out of
        scope.
        """
        self._subscribers.setdefault(url, []).append(callback)
        return _MockBackendSubscription(  # type: ignore[return-value]
            weakref.ref(self), url, callback,
        )

    def emit_change(
        self,
        url: str,
        event_type: str,
        entry: Optional[BackendListEntry],
    ) -> None:
        """Dispatch a synthesized :class:`BackendChangeEvent` to subscribers.

        Test hook. Callers construct the event payload explicitly (the
        tree is *not* mutated by this call) and this method fans out
        to every callback registered under ``url``. No-op if no one
        is subscribed to ``url`` — safe to emit speculatively from a
        test without arranging a matching subscriber.

        The subscriber list is snapshotted before iteration so a
        callback that cancels its own subscription during dispatch
        does not raise ``list changed size during iteration``.
        """
        event = BackendChangeEvent(
            url=url, event_type=event_type, entry=entry,
        )
        for callback in list(self._subscribers.get(url, ())):
            callback(event)

    def _remove_subscriber(
        self,
        url: str,
        callback: Callable[[BackendChangeEvent], None],
    ) -> None:
        """Drop one ``callback`` registration for ``url``.

        Invoked by :class:`_MockBackendSubscription.cancel`. Leaves
        other subscribers for the same URL untouched and prunes the
        URL key entirely once its list is empty (keeps ``_subscribers``
        compact across subscribe/cancel churn in long test sessions).
        """
        subs = self._subscribers.get(url)
        if subs is None:
            return
        if callback in subs:
            subs.remove(callback)
        if not subs:
            self._subscribers.pop(url, None)

    # ── Test helpers ──

    def reset(self) -> None:
        """Rebuild the default tree and clear the error-injection map.

        Fixtures that mutate the tree (e.g. ``create_folder`` /
        ``delete`` tests) call this from their teardown so subsequent
        tests start from a known state. Change subscribers are also
        cleared — a subscriber that outlived its test would receive
        events fired from the next test's setup.
        """
        self._root = _build_default_tree()
        self._errors.clear()
        self._subscribers.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Subscription handle returned by :meth:`MockBackend.subscribe_changes`
# ──────────────────────────────────────────────────────────────────────────────

class _MockBackendSubscription:
    """RAII handle that removes a callback from a :class:`MockBackend`.

    Duck-types :class:`ovui_data_adapters.services.settings.Subscription`: public ``cancel``
    idempotently unsubscribes the callback; ``__del__`` cancels via the
    same path so a handle whose last strong reference is dropped also
    releases. The backend is referenced weakly so a subscription that
    outlives its backend does not pin the backend alive — matches the
    pattern :class:`ovui_data_adapters.services.settings.Subscription` uses for the settings
    store.
    """

    def __init__(
        self,
        backend_ref: "weakref.ref[MockBackend]",
        url: str,
        callback: Callable[[BackendChangeEvent], None],
    ) -> None:
        self._backend_ref = backend_ref
        self._url = url
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        backend = self._backend_ref()
        if backend is not None:
            backend._remove_subscriber(self._url, self._callback)

    def __del__(self) -> None:
        self.cancel()
