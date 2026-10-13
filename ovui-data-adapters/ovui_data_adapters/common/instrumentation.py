# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Optional timing and metric instrumentation for renderers and the app.

The released packages install no instrumentation: every hook is a no-op. An
optional package can publish one ``Instrumentation`` factory in the
``ovui_data_adapters.instrumentation`` entry-point group. The first call to
:func:`get_instrumentation` loads it. This module is safe to import before
``omni.ui`` and before any renderer exists.

Every hook takes the renderer adapter that owns the work (``owner``). An
implementation can call ``owner.instrumentation_target()`` to get the
renderer's native object.
"""

from __future__ import annotations

import sys
import threading
from importlib.metadata import entry_points
from typing import Any

ENTRY_POINT_GROUP = "ovui_data_adapters.instrumentation"

#: Scope name for one iteration of the application's main loop.
MAIN_THREAD_SCOPE = "thread.main"
#: Scope name for one iteration of a renderer's worker thread.
RENDER_THREAD_SCOPE = "thread.render"
#: Value name for the viewport's measured frames per second.
VIEWPORT_FPS_VALUE = "viewport.fps"


class Instrumentation:
    """No-op instrumentation. Subclasses override the hooks they support."""

    def prepare_renderer_config(self, owner: Any, config: Any) -> None:
        """Called once with the native renderer config before creation."""

    def release_renderer(self, owner: Any) -> None:
        """Drop every reference to ``owner``'s native renderer."""

    def begin_scope(self, owner: Any, name: str) -> Any:
        """Start a timed scope on this thread; return a token or ``None``."""
        return None

    def end_scope(self, owner: Any, token: Any) -> None:
        """End a scope that :meth:`begin_scope` started."""

    def begin_phase(self, owner: Any, name: str, information: str) -> bool:
        """Start a named phase; return ``True`` when it was started."""
        return False

    def end_phase(self, owner: Any, name: str, information: str) -> None:
        """End a phase that :meth:`begin_phase` started."""

    def record_value(self, owner: Any, name: str, value: float) -> None:
        """Record one sample of a named value."""


_NO_INSTRUMENTATION = Instrumentation()
_lock = threading.Lock()
_instrumentation: Instrumentation | None = None


def _load_instrumentation() -> Instrumentation:
    for point in entry_points(group=ENTRY_POINT_GROUP):
        try:
            candidate = point.load()()
        except Exception as exc:
            print(
                f"[ovui_data_adapters.instrumentation] {point.name!r} failed to load: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue
        if isinstance(candidate, Instrumentation):
            return candidate
    return _NO_INSTRUMENTATION


def get_instrumentation() -> Instrumentation:
    """Return the installed instrumentation, or the no-op one."""

    global _instrumentation
    current = _instrumentation
    if current is not None:
        return current
    with _lock:
        if _instrumentation is None:
            _instrumentation = _load_instrumentation()
        return _instrumentation


def set_instrumentation(instrumentation: Instrumentation | None) -> None:
    """Install ``instrumentation``; ``None`` reloads from entry points later."""

    global _instrumentation
    with _lock:
        _instrumentation = instrumentation


def profile_call(owner: Any, name: str, function: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Call ``function`` inside a scope named ``name``."""

    instrumentation = get_instrumentation()
    token = instrumentation.begin_scope(owner, name)
    try:
        return function(*args, **kwargs)
    finally:
        if token is not None:
            instrumentation.end_scope(owner, token)


__all__ = [
    "ENTRY_POINT_GROUP",
    "Instrumentation",
    "MAIN_THREAD_SCOPE",
    "RENDER_THREAD_SCOPE",
    "VIEWPORT_FPS_VALUE",
    "get_instrumentation",
    "profile_call",
    "set_instrumentation",
]
