# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Per-target render-cadence helper.

The Application owns one :class:`FrameClock` per render target (currently
just the viewport) and consults it on every frame to decide whether the
target is due for a re-render. The clock keeps the timing logic out of
individual widgets — they expose a ``render(render_dt)`` method and the
Application is the only thing that reads or writes the clock.

Why a separate object? The previous fix lived inside
``ViewportWidget._on_frame`` which shadowed the caller-supplied ``dt``
with its own monotonic clock to dodge the "outer loop ticks faster than
the throttle target" bug. That was correct in effect but wrong in shape —
the gate was a render concern, not a widget concern, and the API lied
about what ``dt`` meant. Hoisting the clock here gives:

* one clear owner per render target (``Application._viewport_render_clock``),
* a single ``commit()`` call that only fires after the render has actually
  happened (so a zero-size or hidden-frame skip does not poison the clock),
* a clean unit-test surface — no widget construction needed.
"""

from __future__ import annotations

import math
from typing import Optional


_PERIOD_TOLERANCE_SECS = 0.002


class FrameClock:
    """Controls how often a render target is re-drawn.

    Construct with the desired ``target_fps`` and call :meth:`should_render`
    once per outer-loop tick. When it returns a non-``None`` ``render_dt``
    the consumer should call its render path with that value and, if the
    render actually happened, call :meth:`commit` to advance the clock.

    The actual last-render timestamp and the scheduled next due timestamp
    are tracked separately. That matters when the outer UI pump ticks at a
    coarse cadence such as 100 Hz: anchoring every late render to "now"
    turns a 60 FPS target into a steady 50 FPS cadence. Preserving the
    scheduled phase lets the clock alternate 10/20 ms gaps as needed and
    settle around the requested rate.
    """

    def __init__(self, target_fps: float = 60.0) -> None:
        self._target_fps = float(target_fps)
        self._last_committed_time: Optional[float] = None
        self._next_due_time: Optional[float] = None

    @property
    def target_fps(self) -> float:
        return self._target_fps

    @target_fps.setter
    def target_fps(self, value: float) -> None:
        """Change the cadence target, re-anchoring the pending deadline.

        A live cap change must affect the very next scheduling decision:
        the next due time is recomputed as one *new* period after the last
        committed render, so raising the cap shortens the current wait and
        lowering it lengthens the current wait — the old period's deadline
        is never honored after the change.
        """
        value = float(value)
        if value == self._target_fps:
            return
        self._target_fps = value
        if self._last_committed_time is None:
            self._next_due_time = None
            return
        period = self.target_period
        if period <= 0.0:
            self._next_due_time = None
        else:
            self._next_due_time = self._last_committed_time + period

    @property
    def target_period(self) -> float:
        """Minimum seconds between successive committed renders."""
        # Guard against zero / negative — tests sometimes pass 0 explicitly to
        # disable the gate; we treat that as "always render".
        if self.target_fps <= 0.0:
            return 0.0
        return 1.0 / self.target_fps

    def should_render(self, now: float) -> Optional[float]:
        """Return the elapsed render_dt at ``now`` if the target is due, else ``None``.

        On the very first call (no prior :meth:`commit`) the clock returns
        ``0.0`` so the first frame paints immediately without a fake
        ``now - 0.0`` interval. Subsequent calls require the
        clock to have advanced by at least :attr:`target_period`.
        """
        last = self._last_committed_time
        if last is None:
            return 0.0
        elapsed = now - last
        period = self.target_period
        if period <= 0.0:
            return elapsed
        due = self._next_due_time
        if due is None:
            due = last + period
            self._next_due_time = due
        # Windows timer / swap pacing often reports nominal 60 Hz ticks a bit
        # under the mathematical 16.666 ms period (commonly 15.6-16.0 ms).
        # A strict comparison then skips every other tick and produces a
        # visible 30 FPS cadence. Keep a small tolerance so near-target ticks
        # render, while genuinely faster loops (120+ Hz) remain throttled.
        if now + _PERIOD_TOLERANCE_SECS >= due:
            return elapsed
        return None

    def commit(self, now: float) -> None:
        """Anchor the next gate decision at ``now``.

        Called by the consumer after a successful render. Pass the same
        ``now`` value that was given to :meth:`should_render` for this
        iteration: the cadence is start-to-start, not completion-to-start.
        The next due timestamp advances from the scheduled due time, not
        from ``now``, so a late tick does not permanently lower the cadence.
        """
        period = self.target_period
        if period <= 0.0:
            self._last_committed_time = now
            self._next_due_time = None
            return
        due = self._next_due_time
        if due is None:
            last = self._last_committed_time
            due = now + period if last is None else last + period
        consume_deadline = now + _PERIOD_TOLERANCE_SECS
        if due <= consume_deadline:
            periods_to_advance = math.floor((consume_deadline - due) / period) + 1
            due += periods_to_advance * period
        self._last_committed_time = now
        self._next_due_time = due

    def reset(self) -> None:
        """Drop the last-committed timestamp.

        Used when the render target is replaced (e.g. renderer swap) so the
        next ``should_render`` call returns ``0.0`` again rather than a
        stale-clock interval. The Application's ``set_renderer`` path calls
        this so the freshly-attached renderer gets an immediate first frame.
        """
        self._last_committed_time = None
        self._next_due_time = None
