# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the standalone FrameInfo / max-FPS pacing API.

Exercises the pure-Python pacing primitives directly without launching a
window. The C++ ``_standalone_tick()`` call is patched to a no-op so the
tests can drive ``_tick_one_frame()`` and ``_max_fps_remaining()`` through
their full code paths.
"""

import asyncio
import time
import unittest
from unittest.mock import patch

from omni.ui import standalone
from omni.ui.standalone import FrameInfo


class _NoopTickPatch:
    """Context manager that stubs ``_ui._standalone_tick`` to a no-op."""

    def __enter__(self):
        self._patch = patch.object(standalone._ui, "_standalone_tick", lambda: None)
        self._patch.__enter__()
        # Reset module state so each test starts from a clean slate.
        # ``_initialized`` must read True: _tick_one_frame re-checks it under
        # the native lock and skips the (stubbed) tick when torn down.
        self._was_initialized = standalone._initialized
        standalone._initialized = True
        standalone._frame_index = 0
        standalone._last_tick_time = None
        standalone._next_frame_futures = []
        return self

    def __exit__(self, *exc):
        standalone._initialized = self._was_initialized
        return self._patch.__exit__(*exc)


class TestFrameInfo(unittest.TestCase):
    def test_frame_info_fields(self):
        info = FrameInfo(dt=0.016, time=12345.0, index=7)
        self.assertEqual(info.dt, 0.016)
        self.assertEqual(info.time, 12345.0)
        self.assertEqual(info.index, 7)

    def test_frame_info_is_frozen(self):
        info = FrameInfo(dt=0.0, time=0.0, index=0)
        with self.assertRaises(Exception):
            info.dt = 1.0  # type: ignore[misc]


class TestTickOneFrame(unittest.TestCase):
    def test_first_tick_dt_is_zero(self):
        with _NoopTickPatch():
            info = standalone._tick_one_frame()
            self.assertEqual(info.dt, 0.0)
            self.assertEqual(info.index, 0)
            self.assertGreater(info.time, 0.0)

    def test_index_increments(self):
        with _NoopTickPatch():
            i0 = standalone._tick_one_frame()
            i1 = standalone._tick_one_frame()
            i2 = standalone._tick_one_frame()
            self.assertEqual(i0.index, 0)
            self.assertEqual(i1.index, 1)
            self.assertEqual(i2.index, 2)

    def test_dt_measures_wallclock_gap(self):
        with _NoopTickPatch():
            standalone._tick_one_frame()
            time.sleep(0.02)
            info = standalone._tick_one_frame()
            self.assertGreaterEqual(info.dt, 0.015)
            self.assertLess(info.dt, 0.5)  # sanity ceiling

    def test_resolves_pending_futures_with_frame_info(self):
        with _NoopTickPatch():
            loop = asyncio.new_event_loop()
            try:
                fut = loop.create_future()
                standalone._next_frame_futures.append(fut)
                info = standalone._tick_one_frame()
                # Future was resolved with the same FrameInfo
                self.assertTrue(fut.done())
                self.assertIs(fut.result(), info)
            finally:
                loop.close()


class TestMaxFrameRate(unittest.TestCase):
    def setUp(self):
        # Save + restore module state so other tests aren't affected.
        self._saved = standalone._max_frame_rate

    def tearDown(self):
        standalone._max_frame_rate = self._saved

    def test_default_cap_is_60(self):
        # Reset and re-init to default.
        standalone.set_max_frame_rate(60.0)
        self.assertEqual(standalone.get_max_frame_rate(), 60.0)

    def test_set_disables_cap_with_none(self):
        standalone.set_max_frame_rate(None)
        self.assertIsNone(standalone.get_max_frame_rate())

    def test_set_disables_cap_with_zero(self):
        standalone.set_max_frame_rate(0.0)
        self.assertIsNone(standalone.get_max_frame_rate())

    def test_set_disables_cap_with_negative(self):
        standalone.set_max_frame_rate(-1.0)
        self.assertIsNone(standalone.get_max_frame_rate())

    def test_target_period_at_60_fps(self):
        standalone.set_max_frame_rate(60.0)
        period = standalone._max_fps_target_period()
        self.assertAlmostEqual(period, 1.0 / 60.0, places=6)

    def test_target_period_zero_when_uncapped(self):
        standalone.set_max_frame_rate(None)
        self.assertEqual(standalone._max_fps_target_period(), 0.0)

    def test_remaining_zero_when_uncapped(self):
        standalone.set_max_frame_rate(None)
        self.assertEqual(
            standalone._max_fps_remaining_since(time.monotonic()), 0.0,
        )

    def test_remaining_full_budget_when_frame_start_is_now(self):
        """Iteration just started — almost the full 1/60s budget remains."""
        standalone.set_max_frame_rate(60.0)
        frame_start = time.monotonic()
        remaining = standalone._max_fps_remaining_since(frame_start)
        self.assertGreater(remaining, 0.010)
        self.assertLess(remaining, 0.020)

    def test_remaining_zero_when_iteration_consumed_the_budget(self):
        """Mirror of the vsync host: the whole 16.7ms already elapsed —
        no extra sleep should be requested."""
        standalone.set_max_frame_rate(60.0)
        # Pretend frame_start was 100ms ago.
        frame_start = time.monotonic() - 0.1
        self.assertEqual(
            standalone._max_fps_remaining_since(frame_start), 0.0,
        )


class TestVsyncHostDoesNotDoubleSleep(unittest.TestCase):
    """Regression test for Codex review v2 item 1.

    On a hardware-vsync host ``_standalone_tick()`` already blocks for
    ~16.7 ms inside ``glfwSwapBuffers``. Before the fix, ``_max_fps_remaining``
    measured elapsed against a timestamp captured *after* the tick — so it
    saw ~0 ms elapsed and asked the run loop to sleep another full frame.
    Effective frame rate halved.

    The fix captures ``frame_start`` *before* the tick so the budget covers
    the whole iteration. After the tick has consumed ``≥ 1/max_fps``
    seconds, the remaining sleep should be ``0.0``.
    """

    def setUp(self):
        self._saved = standalone._max_frame_rate
        standalone.set_max_frame_rate(60.0)

    def tearDown(self):
        standalone._max_frame_rate = self._saved

    def test_tick_consumed_full_budget_means_zero_remaining(self):
        # Simulate _standalone_tick spending the entire 1/60s budget — the
        # exact behaviour of glfwSwapBuffers under hardware vsync at 60 Hz.
        target = 1.0 / 60.0
        with _NoopTickPatch():
            def slow_tick():
                # Spend the full budget plus a smidge to be sure the host
                # is on the boundary, never below.
                time.sleep(target * 1.05)

            with patch.object(standalone._ui, "_standalone_tick", side_effect=slow_tick):
                frame_start = time.monotonic()
                standalone._tick_one_frame()
                remaining = standalone._max_fps_remaining_since(frame_start)
                # The tick already consumed ≥ target — no extra sleep.
                self.assertEqual(remaining, 0.0)

    def test_fast_tick_leaves_most_of_the_budget(self):
        target = 1.0 / 60.0
        with _NoopTickPatch():
            frame_start = time.monotonic()
            standalone._tick_one_frame()  # noop tick, microseconds
            remaining = standalone._max_fps_remaining_since(frame_start)
            # Most of the budget should remain — 80%+ as a generous floor.
            self.assertGreater(remaining, 0.80 * target)


class TestNextFrameReturnsFrameInfo(unittest.TestCase):
    def test_next_frame_resolves_with_frame_info(self):
        async def runner():
            with _NoopTickPatch():
                # Schedule a single tick so the future resolves.
                fut_future = asyncio.ensure_future(standalone.next_frame())
                # Drive one tick on the next loop iteration so the awaiter is
                # registered before the tick fires.
                await asyncio.sleep(0)
                standalone._tick_one_frame()
                info = await fut_future
                return info

        loop = asyncio.new_event_loop()
        try:
            info = loop.run_until_complete(runner())
        finally:
            loop.close()

        self.assertIsInstance(info, FrameInfo)
        self.assertEqual(info.index, 0)


if __name__ == "__main__":
    unittest.main()
