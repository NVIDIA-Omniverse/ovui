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

from dataclasses import dataclass
from typing import Optional


@dataclass
class FrameClock:
    """Controls how often a render target is re-drawn.

    Construct with the desired ``target_fps`` and call :meth:`should_render`
    once per outer-loop tick. When it returns a non-``None`` ``render_dt``
    the consumer should call its render path with that value and, if the
    render actually happened, call :meth:`commit` to advance the clock.

    The clock is **only** advanced via :meth:`commit`. Skipping a render
    (zero-size widget, hidden window, exception during render) leaves the
    clock untouched, so the next tick will pass the gate immediately and
    re-attempt — preventing a transient skip from delaying the next visible
    frame by a full ``1 / target_fps`` window.
    """

    target_fps: float = 60.0
    _last_committed_time: Optional[float] = None

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
        ``time.monotonic() - 0.0`` interval. Subsequent calls require the
        clock to have advanced by at least :attr:`target_period`.
        """
        last = self._last_committed_time
        if last is None:
            return 0.0
        elapsed = now - last
        if elapsed >= self.target_period:
            return elapsed
        return None

    def commit(self, now: float) -> None:
        """Anchor the next gate decision at ``now``.

        Called by the consumer after a successful render. Pass the same
        ``now`` value that was given to :meth:`should_render` for this
        iteration: the cadence is start-to-start, not completion-to-start,
        which matches a max-FPS interpretation ("never start a new render
        less than ``1/target_fps`` after the previous one began"). If
        completion-to-start is needed instead, sample a fresh
        ``time.monotonic()`` after the render returns and pass that.
        """
        self._last_committed_time = now

    def reset(self) -> None:
        """Drop the last-committed timestamp.

        Used when the render target is replaced (e.g. renderer swap) so the
        next ``should_render`` call returns ``0.0`` again rather than a
        stale-clock interval. The Application's ``set_renderer`` path calls
        this so the freshly-attached renderer gets an immediate first frame.
        """
        self._last_committed_time = None
