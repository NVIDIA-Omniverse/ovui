# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Process-wide registry of ovui-resource clears.

OvGear has 21 module-scope holders of C++ ovui resources: 15 dict
caches of :class:`omni.ui.RasterImageProvider`, 3 singletons
(:data:`menu_bar._LOGO_PROVIDER` plus
:attr:`FileImporterHelper._singleton` and
:attr:`FileExporterHelper._singleton`), and 3 dialog-tracking lists
(``_OPEN_DIALOGS`` in :mod:`ovui_widgets.common.file_dialogs`,
:mod:`ovui_widgets.common.dialogs`, and
:mod:`ovui_widgets.content.widget.confirm_overwrite_dialog`).
Their C++ destructors must run *before* :func:`omni.ui.shutdown`
runs, otherwise they UAF the standalone backend's
``s_rasterImageLoader`` / ``Workspace``.

Each holder registers a zero-arg clear callback here at import time;
:meth:`Application.shutdown` calls :func:`clear_all` to invoke every
registered callback.

Issue #35, Step 2.

``provider()`` and ``_PROVIDER_CACHE`` were elevated from
:mod:`ovui_widgets.stage.widget.stage_icons` to this shared module in Issue #31
Step 5 so that any widget package (e.g. ``ovui_widgets.property``) can call
``provider()`` without creating a cross-widget import dependency.
"""
from __future__ import annotations

from collections.abc import Hashable
from typing import Any, Callable, Dict, List, Tuple

# Each entry is ``(dedup_key, callback)``. The dedup_key is one of:
#
# * an ``int`` from ``id(...)`` of the cleared resource (used by
#   :func:`register_dict`) or of the callback object itself (used by
#   :func:`register`); or
# * a ``str`` like ``"singleton:menu_bar._LOGO_PROVIDER"`` or
#   ``"clsmethod:ovui_widgets.content.file_importer.FileImporterHelper.reset_singleton"``
#   (used by :func:`register_singleton` and
#   :func:`register_classmethod`). The string form is stable across
#   module reload.
#
# The annotation accepts both shapes via :class:`~collections.abc.Hashable`
# (Round 7 F3).
_callbacks: List[Tuple[Hashable, Callable[[], None]]] = []


def _has_key(key: Hashable) -> bool:
    """True iff ``key`` already exists in the registry."""
    return any(k == key for k, _ in _callbacks)


def register(clear_callback: Callable[[], None]) -> None:
    """Register an arbitrary clear function.

    Idempotent **by identity of the callback object** — i.e.
    registering the *same* function/lambda/bound-method object twice
    is a no-op.

    Caveat: re-creating a bound method like ``cache.clear`` each call
    produces a NEW bound-method object, so passing ``cache.clear``
    twice through this entry point WILL register twice. Prefer
    :func:`register_dict` (deduplicates by ``id(cache)``),
    :func:`register_singleton` or :func:`register_classmethod`
    (string-keyed dedup) for owner-keyed clears.
    """
    key = id(clear_callback)
    if _has_key(key):
        return
    _callbacks.append((key, clear_callback))


def register_dict(cache: Dict) -> None:
    """Convenience wrapper for the common case of a module-scope dict.

    Idempotent **by identity of the dict** — registering the same dict
    twice is a no-op even if the bound-method object differs between
    calls. Stores a closure that calls ``cache.clear()`` at clear time;
    the closure is recreated on every call but the dedup key is the
    dict's ``id`` so the second registration is rejected.
    """
    key = id(cache)
    if _has_key(key):
        return
    _callbacks.append((key, lambda: cache.clear()))


def register_singleton(owner: object, attr: str) -> None:
    """Convenience wrapper for an attribute that must be set to None
    at teardown (module global, class attribute, etc).

    Idempotent **by string key** — re-registering the same
    ``(owner, attr)`` pair is a no-op even across module reload
    (Round 3 F3). The ``owner.__name__`` (or ``repr(owner)``) +
    attribute name pair is stable; ``id(owner)`` would not be (a
    reload swaps the module/class object).
    """
    name = getattr(owner, "__name__", None) or repr(owner)
    key = f"singleton:{name}.{attr}"
    if _has_key(key):
        return
    _callbacks.append((key, lambda: setattr(owner, attr, None)))


def register_classmethod(cls: type, method_name: str) -> None:
    """Register a classmethod by stable string key (Round 3 F3).

    Useful for :meth:`FileImporterHelper.reset_singleton` and similar:
    bound methods are NOT identity-stable (every attribute access
    creates a fresh bound-method object), so ``register(cls.method)``
    can register multiple times. ``register_classmethod`` keys by
    ``"clsmethod:{module}.{qualname}.{method}"`` which is stable.
    """
    key = f"clsmethod:{cls.__module__}.{cls.__qualname__}.{method_name}"
    if _has_key(key):
        return
    # Look the method up at call time (cls.__dict__ may have changed
    # between registration and clear_all()).
    _callbacks.append((key, lambda: getattr(cls, method_name)()))


def clear_all() -> None:
    """Invoke every registered clear callback.

    Errors are swallowed — we are tearing down, partial failures must
    not block other clears. The registry list itself is NOT emptied:
    re-running :func:`clear_all` is a safe no-op for callbacks that
    are already idempotent (dict ``clear()``, ``setattr(..., None)``,
    ``reset_singleton()``), and avoiding the empty ensures a second
    :meth:`Application.shutdown` call (e.g. from a test) still drives
    the same teardown path.
    """
    for _key, cb in _callbacks:
        try:
            cb()
        except Exception:
            # Don't print: shutdown is in progress, stderr may already
            # be on the way out. The teardown must continue.
            pass


# ---------------------------------------------------------------------------
# Process-wide RasterImageProvider cache (Issue #31 Step 5)
# ---------------------------------------------------------------------------
# Elevated from ovui_widgets.stage.widget.stage_icons so that any widget package
# (e.g. ovui_widgets.property) can call provider() without a cross-widget import.
# The return-type annotation is a forward-reference string so omni.ui is
# NOT imported at module level — ovui_widgets.common.icon_caches must remain importable
# in headless test environments where omni.ui is unavailable.

_PROVIDER_CACHE: Dict[str, Any] = {}
register_dict(_PROVIDER_CACHE)


def provider(path: str) -> Any:
    """Return a cached ``omni.ui.RasterImageProvider`` for *path*.

    ``omni.ui.Image(url)`` silently fails on the standalone build; only
    the provider-backed ``omni.ui.ImageWithProvider`` renders reliably.
    Providers are cached by path so the PNG is decoded only once per
    process.

    The return type is ``omni.ui.RasterImageProvider`` at runtime; the
    annotation is kept as ``Any`` so this module remains importable in
    headless test environments where ``omni.ui`` is not available.
    """
    prov = _PROVIDER_CACHE.get(path)
    if prov is None:
        import omni.ui as ui  # deferred — not available in headless tests
        prov = ui.RasterImageProvider(path)
        _PROVIDER_CACHE[path] = prov
    return prov
