# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Core primitives for optional Markdown provider plugins.

The native MarkdownWidget currently exposes ``set_image_url_provider_fn`` as a
string-to-string compatibility hook.  These Python classes are intentionally
broader: they model provider work as asynchronous asset requests so HTTP/S,
SVG, Mermaid, and math renderers can share cache and scheduling behavior.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional


_LEGACY_CACHE_DIR = Path.home() / ".cache" / "omni-ui-markdown-assets"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "ovui-markdown-assets"

_log = logging.getLogger(__name__)


def migrate_legacy_cache_dir(
    legacy_path: Path = _LEGACY_CACHE_DIR,
    new_path: Path = DEFAULT_CACHE_DIR,
) -> None:
    """Rename the pre-ovui markdown cache dir to the ovui-branded path.

    Idempotent: skips when ``legacy_path`` is absent or ``new_path`` already
    exists. Concurrent-safe: ``os.replace`` is atomic on POSIX, and racing
    callers that lose the race fall through the ``OSError`` branch without
    crashing. Failures (permissions, cross-device, etc.) are logged and
    swallowed -- the caller proceeds with a fresh cache directory.
    """

    legacy_path = Path(legacy_path)
    new_path = Path(new_path)
    try:
        if legacy_path.exists() and not new_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(legacy_path, new_path)
            _log.info("ovui: migrated markdown cache %s -> %s", legacy_path, new_path)
    except OSError as exc:
        _log.info("ovui: markdown cache migration skipped (%s)", exc)


_migration_lock = threading.Lock()
_migration_done = False


def _run_default_migration_once() -> None:
    global _migration_done
    with _migration_lock:
        if _migration_done:
            return
        _migration_done = True
    migrate_legacy_cache_dir()


_run_default_migration_once()


def stable_digest(*parts: object, length: int = 24) -> str:
    """Return a short stable digest for cache keys."""

    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8", errors="surrogatepass"))
        h.update(b"\0")
    return h.hexdigest()[:length]


@dataclass(frozen=True)
class MarkdownProviderRequest:
    """A provider request independent of a concrete renderer implementation."""

    kind: str
    source: str
    language: str = ""
    alt_text: str = ""
    title: str = ""
    base_dir: Optional[Path] = None
    cache_dir: Path = DEFAULT_CACHE_DIR
    max_display_width: int = 0
    font_size: float = 14.0
    device_scale: float = 1.0
    theme: str = "light"
    options: Mapping[str, object] = field(default_factory=dict)
    generation: int = 0


@dataclass(frozen=True)
class MarkdownProviderResult:
    """Result returned by provider plugins.

    ``path`` is the first compatibility output because MarkdownWidget can
    already consume local raster paths through ``set_image_url_provider_fn``.
    Future C++/Python bindings can also map this shape to raw bytes or
    ImageProvider objects.
    """

    state: str
    path: str = ""
    width: int = 0
    height: int = 0
    baseline: float = 0.0
    error: str = ""
    source: str = ""

    @property
    def ready(self) -> bool:
        return self.state == "ready" and bool(self.path)


class AsyncProviderPlugin:
    """Base class for optional non-blocking provider plugins.

    Results are cached in a bounded LRU keyed by :meth:`cache_key`.  The LRU
    stores the last ``max_cached_results`` *completed* results; in-flight
    futures are tracked separately in ``_futures``.

    Subclasses should override :meth:`can_handle`, :meth:`cache_key`, and
    :meth:`render`.  :meth:`render` runs on the worker pool and must be
    thread-safe against itself.
    """

    #: Default max entries kept in the completed-results LRU.
    DEFAULT_MAX_CACHED_RESULTS = 128

    #: Default worker pool size.
    DEFAULT_CONCURRENCY = 2

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        executor: Optional[ThreadPoolExecutor] = None,
        *,
        max_cached_results: int = DEFAULT_MAX_CACHED_RESULTS,
        concurrency: int = DEFAULT_CONCURRENCY,
    ):
        self.cache_dir = (cache_dir or DEFAULT_CACHE_DIR).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._owned_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(
            max_workers=max(1, int(concurrency)),
            thread_name_prefix=self.__class__.__name__,
        )
        self._futures: "dict[str, Future[MarkdownProviderResult]]" = {}
        # OrderedDict gives us O(1) move-to-end for LRU semantics.
        self._results: "OrderedDict[str, MarkdownProviderResult]" = OrderedDict()
        self._max_cached_results = max(1, int(max_cached_results))
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ API

    def can_handle(self, request: MarkdownProviderRequest) -> bool:
        raise NotImplementedError

    def cache_key(self, request: MarkdownProviderRequest) -> str:
        return stable_digest(request.kind, request.language, request.source, request.theme, request.max_display_width)

    def cached_result(self, request: MarkdownProviderRequest) -> Optional[MarkdownProviderResult]:
        return None

    def render(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
        raise NotImplementedError

    def request(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
        cached = self.cached_result(request)
        if cached is not None:
            return cached

        key = self.cache_key(request)
        with self._lock:
            if key in self._results:
                # LRU hit: refresh recency.
                self._results.move_to_end(key)
                return self._results[key]

            future = self._futures.get(key)
            if future is None:
                future = self._executor.submit(self.render, request)
                self._futures[key] = future

            if not future.done():
                return MarkdownProviderResult(state="pending", source=request.source)

        try:
            result = future.result()
        except Exception as exc:
            result = MarkdownProviderResult(state="failed", error=str(exc), source=request.source)

        with self._lock:
            self._store_result_locked(key, result)
            self._futures.pop(key, None)
        return result

    # ----------------------------------------------------------- cancellation

    def cancel(self, request: MarkdownProviderRequest) -> bool:
        """Best-effort cancellation of a pending request.

        Returns True if a pending future was found and cancelled (or was
        already complete and discarded).  Returns False if nothing was
        registered for this request key.

        Limitation: Python's ThreadPoolExecutor cannot preempt in-flight work.
        If the worker has already started ``render``, this call removes the
        tracking entry but does NOT interrupt the running function.  The
        completed result will be silently dropped when ``render`` returns.
        Subclasses that spawn subprocesses or network I/O should override to
        do better (e.g. terminate the subprocess).
        """

        key = self.cache_key(request)
        with self._lock:
            future = self._futures.pop(key, None)
            # Also drop any cached "failed"/"ready" entry the caller wants gone.
            self._results.pop(key, None)
        if future is None:
            return False
        # future.cancel() returns False if the worker already picked it up.
        future.cancel()
        return True

    def cancel_generation(self, generation: int) -> None:
        """Cancel all in-flight work tied to a document generation.

        Default implementation is a no-op.  Subclasses may override -- the
        plan is to eventually plumb this through to the C++
        ``IMarkdownAssetProvider::cancelGeneration`` hook, so pybind11
        trampolines can propagate the signal into Python land.
        """

        _ = generation

    # --------------------------------------------------------------- helpers

    def _store_result_locked(self, key: str, result: MarkdownProviderResult) -> None:
        """Insert into the LRU and evict oldest if we're over the cap.

        Must be called while holding ``self._lock``.
        """

        self._results[key] = result
        self._results.move_to_end(key)
        while len(self._results) > self._max_cached_results:
            self._results.popitem(last=False)

    def wait_for_idle(self, timeout: Optional[float] = None) -> None:
        """Wait for currently scheduled work and flush completed results.

        This is for tests and screenshot capture. Interactive UI code should
        poll by calling ``request`` during normal frame rendering.

        As a side-effect, completed futures are promoted into ``_results`` so
        the next ``request()`` can return ``ready`` immediately without
        racing the worker threads.
        """

        with self._lock:
            pending = list(self._futures.items())
        for key, future in pending:
            try:
                result = future.result(timeout=timeout)
            except Exception as exc:
                result = MarkdownProviderResult(state="failed", error=str(exc))
            with self._lock:
                self._store_result_locked(key, result)
                self._futures.pop(key, None)

    def shutdown(self) -> None:
        if self._owned_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)


class MarkdownProviderChain:
    """Ordered collection of provider plugins."""

    def __init__(self, plugins: Optional["list[AsyncProviderPlugin]"] = None):
        self.plugins = plugins or []

    def first(self, request: MarkdownProviderRequest) -> MarkdownProviderResult:
        for plugin in self.plugins:
            if plugin.can_handle(request):
                return plugin.request(request)
        return MarkdownProviderResult(state="unsupported", source=request.source)

    def cancel(self, request: MarkdownProviderRequest) -> bool:
        """Propagate ``cancel`` to the first plugin that claims the request.

        Matches the ``first`` dispatch policy: we do not broadcast, because
        only one plugin owns the result for any given request.
        """

        for plugin in self.plugins:
            if plugin.can_handle(request):
                return plugin.cancel(request)
        return False

    def cancel_generation(self, generation: int) -> None:
        for plugin in self.plugins:
            plugin.cancel_generation(generation)

    def wait_for_idle(self, timeout: Optional[float] = None) -> None:
        for plugin in self.plugins:
            plugin.wait_for_idle(timeout=timeout)

    def shutdown(self) -> None:
        for plugin in self.plugins:
            plugin.shutdown()


def run_safely(fn: Callable[[], MarkdownProviderResult], source: str = "") -> MarkdownProviderResult:
    try:
        return fn()
    except Exception as exc:
        return MarkdownProviderResult(state="failed", error=str(exc), source=source)
