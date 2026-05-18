# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""``ScrollPreserver`` — save/restore vertical scroll across panel rebuilds.

property widget stack behavior / the property inspector behavior / the property inspector step 7.3.
Selection changes rebuild :class:`~ovwidgets.property.window.PropertyWindow`'s
content stack from scratch, which resets ``ui.ScrollingFrame.scroll_y`` to
0. When the user re-selects the same kind of prim, losing scroll position
is a regression — their cursor was parked over a specific attribute row
and the whole panel just jumped back to the top.

The preserver has two layers — a policy decision and a timing mechanism.

**Policy** — scroll is preserved only when the new payload's
:meth:`~ovwidgets.property.payload.PropertyPayload.get_scheme` matches the prior
payload's scheme. The architecture doc calls this the "prim type set"
check: if both selections resolve to the same scheme (today a single
string; a richer prim-type set lands in a later step), the widget layout
is structurally identical and a restored ``scroll_y`` still points at
meaningful content. If the scheme changes (Mesh → DomeLight, for
example), the layout is different and a preserved position would land
the viewport on whatever row happens to sit at that pixel — useless.

**Timing** — ``ui.ScrollingFrame.scroll_y`` cannot be restored
synchronously inside the rebuild. Setting it before omni.ui has
completed layout computation clamps the write against a still-zero
``scroll_y_max``, so the value snaps back to 0. The architecture doc
uses a two-frame ``asyncio`` delay (``await next_update_async()`` twice)
around the Kit codebase; ovgear's equivalent is two chained
:meth:`Application.call_later(0.0, ...)` calls because we drive frames
through the ``_on_frame_update`` loop rather than asyncio. Empirically
one frame is not always enough — the architecture doc notes the same
for complex layouts with async-built widgets.

The preserver takes the :class:`ui.ScrollingFrame` via a callable
``frame_getter`` (not a direct reference) so the window can rebind the
frame during its own lifecycle without the preserver going stale. The
``call_later`` function is injected for testability — headless tests pass
a stub that fires the callback synchronously so the two-frame wait is
deterministic.
"""

from __future__ import annotations

from typing import Any, Callable, Optional


class ScrollPreserver:
    """Save and restore ``scroll_y`` on a :class:`ui.ScrollingFrame`.

    The owning :class:`PropertyWindow` calls :meth:`save_position` before
    clearing its content stack, then :meth:`restore_position` after the
    rebuild has emitted its widgets. The restore schedules a two-frame
    deferred write so omni.ui's layout pass has computed a non-zero
    ``scroll_y_max`` by the time the write fires — otherwise the write is
    clamped to 0 and the preservation is silently lost.

    :param frame_getter: Zero-arg callable that returns the current
        :class:`ui.ScrollingFrame` (or ``None`` if the window's UI hasn't
        been built). Passed as a callable rather than a direct reference
        so the window can recreate the frame on rebuild without leaving
        the preserver pointing at a dead widget.
    :param call_later: Callable matching
        :meth:`ovwidgets.app.application.Application.call_later` — takes
        ``(delay_secs: float, callback: Callable[[], None])`` and returns
        a handle with ``.cancel()``. The preserver chains two ``0.0``
        delays to land the restore two frames after the rebuild. Tests
        inject a synchronous stub so the restore fires deterministically.
    """

    def __init__(
        self,
        frame_getter: Callable[[], Optional[Any]],
        call_later: Callable[[float, Callable[[], None]], Any],
    ) -> None:
        self._frame_getter = frame_getter
        self._call_later = call_later
        # Stored scroll position from the most recent :meth:`save_position`
        # call, read back inside the deferred callback chain. ``None``
        # means nothing to restore (either the saver's first call or the
        # prior save was reset because the scheme changed).
        self._saved_scroll_y: Optional[float] = None
        # The scheme string from the prior payload. Compared against the
        # new payload's scheme inside :meth:`restore_position` to decide
        # between preserve (same scheme) and reset (different scheme).
        # ``None`` on the first save so the first rebuild always resets
        # scroll to 0 — there's no prior frame to preserve from.
        self._prev_scheme: Optional[str] = None
        # Outstanding handles from the two chained :func:`call_later`
        # calls. Cancelled by :meth:`destroy` and by a subsequent
        # :meth:`restore_position` so rapid selection changes don't stack
        # up deferred writes that could clobber each other.
        self._pending_first_handle: Optional[Any] = None
        self._pending_second_handle: Optional[Any] = None

    # ------------------------------------------------------------------
    # Save / restore API — called from PropertyWindow._rebuild_content
    # ------------------------------------------------------------------

    def save_position(self) -> None:
        """Snapshot the current ``scroll_y`` for the next restore.

        No-op when the frame getter returns ``None`` (the window's UI
        hasn't been built yet — nothing to save). The saved value is
        read back inside :meth:`restore_position`'s deferred callback;
        if the preserve/reset policy decides to reset, the saved value
        is discarded.
        """
        frame = self._frame_getter()
        if frame is None:
            return
        try:
            self._saved_scroll_y = float(frame.scroll_y)
        except Exception:
            # Headless tests sometimes pass a stub whose ``scroll_y``
            # raises before the ui root is alive. Treat that the same as
            # "nothing to save" rather than crashing the rebuild.
            self._saved_scroll_y = None

    def restore_position(self, new_scheme: str) -> None:
        """Schedule a scroll restore two frames after the rebuild.

        The restore decides between preserve (when ``new_scheme`` matches
        the prior payload's scheme) and reset-to-0 (otherwise). Both
        paths schedule the write through two chained
        :meth:`call_later(0.0, ...)` calls so omni.ui's layout pass has
        a chance to compute ``scroll_y_max`` before the write lands —
        writing scroll_y before layout clamps it to 0.

        The preserver pins the old ``_prev_scheme`` into the deferred
        closure via a local variable so a second :meth:`restore_position`
        fired before the first fires can still be distinguished
        (rapid selection changes cancel the pending handles and reseed
        the comparison; see the cancellation below).

        :param new_scheme: Scheme string from the new payload
            (:meth:`~ovwidgets.property.payload.PropertyPayload.get_scheme`).
        """
        # Cancel any still-pending restores — the user selected again
        # before the prior one fired, so its saved_scroll_y + prev_scheme
        # are stale. The new save_position call already captured the
        # right snapshot and the new restore_position will schedule a
        # fresh callback chain.
        self._cancel_pending()

        should_preserve = (
            self._prev_scheme is not None
            and self._prev_scheme == new_scheme
            and self._saved_scroll_y is not None
        )
        target_scroll_y = self._saved_scroll_y if should_preserve else 0.0
        # Seed the prior-scheme slot with the new scheme so the next
        # restore_position call can decide against it. Doing this before
        # scheduling the deferred write means nested/back-to-back
        # selection changes compare correctly even if earlier handles
        # haven't fired yet.
        self._prev_scheme = new_scheme

        # Close over the target locally so a later save/restore doesn't
        # mutate _saved_scroll_y and affect the already-scheduled write.
        def _apply() -> None:
            self._pending_second_handle = None
            frame = self._frame_getter()
            if frame is None:
                return
            try:
                frame.scroll_y = target_scroll_y  # type: ignore[misc]
            except Exception:
                pass

        def _wait_one_more() -> None:
            self._pending_first_handle = None
            self._pending_second_handle = self._call_later(0.0, _apply)

        self._pending_first_handle = self._call_later(0.0, _wait_one_more)

    def destroy(self) -> None:
        """Cancel pending handles + drop state — idempotent."""
        self._cancel_pending()
        self._saved_scroll_y = None
        self._prev_scheme = None

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _cancel_pending(self) -> None:
        if self._pending_first_handle is not None:
            self._pending_first_handle.cancel()
            self._pending_first_handle = None
        if self._pending_second_handle is not None:
            self._pending_second_handle.cancel()
            self._pending_second_handle = None
