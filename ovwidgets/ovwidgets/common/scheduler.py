# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Process-wide scheduler registry — `CallbackHandle` + `call_later` indirection.

Widget code that previously called ``Application.instance().call_later(...)``
now calls :func:`call_later` here. :class:`Application` registers its own
:meth:`call_later` as the backend during ``__init__`` via
:func:`set_call_later`; on shutdown it clears via
:func:`set_call_later(None)`.

When no backend is registered, :func:`call_later` raises ``RuntimeError`` —
the exact same exception type ``Application.instance()`` previously raised
when no application was up. Existing widget try/except RuntimeError guards
that fell back to synchronous execution continue to work unchanged
(synchronous fallback and return-no-op behaviors).

:class:`CallbackHandle` was previously defined inside
``ovwidgets.app.application``; moving it here lets widget code import the
return type without depending on ``ovwidgets.app``.
"""

from __future__ import annotations

from typing import Callable, Optional


class CallbackHandle:
    """Handle for a scheduled callback. Can be cancelled.

    Moved from ``ovwidgets.app.application``. Behavior is identical to the
    previous in-application definition.
    """

    def __init__(self, due_time: float, callback: Callable) -> None:
        self._due_time = due_time
        self._callback: Optional[Callable] = callback
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_fired(self) -> bool:
        return self._callback is None

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled


_call_later_fn: Optional[Callable[[float, Callable], CallbackHandle]] = None


def set_call_later(fn: Optional[Callable[[float, Callable], CallbackHandle]]) -> None:
    """Register / clear the process-wide ``call_later`` backend.

    Called by :class:`ovwidgets.app.application.Application` at
    ``__init__`` (with ``self.call_later`` to register the live frame-loop
    scheduler) and at ``shutdown`` (with ``None`` to clear).

    Tests that need isolation can also call this with a stub callable and
    reset to ``None`` at teardown.
    """
    global _call_later_fn
    _call_later_fn = fn


def call_later(delay_secs: float, callback: Callable) -> CallbackHandle:
    """Schedule ``callback`` to fire after ``delay_secs`` via the registered backend.

    Raises ``RuntimeError`` when no backend is registered (e.g. tests that
    construct widgets in isolation without an :class:`Application`). This
    matches the pre-Rev-8 behavior of
    ``Application.instance().call_later(...)`` raising when no
    :class:`Application` singleton existed, so the existing widget
    ``try/except RuntimeError`` fallback paths from Rev 8 §5.5
    (SYNC-FALLBACK / RETURN-NO-OP) continue to work without code changes.
    """
    if _call_later_fn is None:
        raise RuntimeError("No scheduler registered")
    return _call_later_fn(delay_secs, callback)
