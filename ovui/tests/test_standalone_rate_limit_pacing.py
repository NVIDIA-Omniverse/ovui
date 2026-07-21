# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Interruptible max-FPS pacing in the standalone run loops.

Exercises the pure-Python pacing primitives without launching a window,
following the ``test_standalone_frame_info.py`` pattern: the C++
``_standalone_tick`` / ``_standalone_should_close`` calls are patched so
the tests drive :func:`run_async`'s real pacing wait.

Contracts under test:

* a live :func:`set_max_frame_rate` change wakes an in-flight pacing wait
  and the wait recomputes its budget against the NEW rate — both faster
  and slower;
* :func:`request_wakeup` ends the wait early (exit responsiveness);
* the budget is per-iteration relative (Kit ``minLoopTime`` semantics):
  an overrun iteration is never followed by a shorter-than-period
  iteration to catch up.
"""

import asyncio
import threading
import time
import unittest
from unittest.mock import patch

from omni.ui import standalone


class _PumpHarness:
    """Patch the native calls so run_async() ticks until told to close."""

    def __init__(self):
        self.tick_times = []
        self._close = False

    def close(self):
        self._close = True

    def __enter__(self):
        self._patches = [
            patch.object(
                standalone._ui, "_standalone_tick",
                lambda: self.tick_times.append(time.monotonic()),
            ),
            patch.object(
                standalone._ui, "_standalone_should_close",
                lambda: self._close,
            ),
        ]
        for p in self._patches:
            p.__enter__()
        standalone._initialized = True  # skip real init
        standalone._frame_index = 0
        standalone._last_tick_time = None
        standalone._next_frame_futures = []
        standalone._wakeup_event.clear()
        standalone._wakeup_break = False
        standalone._async_wakeup_event = None
        standalone._async_wakeup_loop = None
        return self

    def __exit__(self, *exc):
        standalone._initialized = False
        standalone.set_max_frame_rate(60.0)
        for p in reversed(self._patches):
            p.__exit__(*exc)
        return False


class TestRunAsyncInFlightRateChange(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_faster_change_shortens_pending_wait(self):
        """10 -> 100 FPS during the in-flight wait: the iteration completes
        near the NEW 10 ms period, not the old 100 ms one."""
        with _PumpHarness() as pump:
            standalone.set_max_frame_rate(10.0)

            async def scenario():
                async def change():
                    await asyncio.sleep(0.005)
                    standalone.set_max_frame_rate(100.0)
                changer = asyncio.create_task(change())
                runner = asyncio.create_task(standalone.run_async())
                while len(pump.tick_times) < 2:
                    await asyncio.sleep(0.001)
                pump.close()
                standalone.request_wakeup()
                await changer
                await runner

            start = time.monotonic()
            self._run(scenario())
            first_interval = pump.tick_times[1] - pump.tick_times[0]
            self.assertLess(
                first_interval, 0.050,
                f"stale 100ms wait retained: {first_interval*1000:.1f}ms",
            )
            self.assertGreaterEqual(first_interval, 0.009)

    def test_slower_change_extends_pending_wait(self):
        """100 -> 10 FPS during the in-flight wait: the iteration completes
        near the NEW 100 ms period."""
        with _PumpHarness() as pump:
            standalone.set_max_frame_rate(100.0)

            async def scenario():
                async def change():
                    await asyncio.sleep(0.002)
                    standalone.set_max_frame_rate(10.0)
                changer = asyncio.create_task(change())
                runner = asyncio.create_task(standalone.run_async())
                while len(pump.tick_times) < 2:
                    await asyncio.sleep(0.001)
                pump.close()
                standalone.request_wakeup()
                await changer
                await runner

            self._run(scenario())
            first_interval = pump.tick_times[1] - pump.tick_times[0]
            self.assertGreaterEqual(
                first_interval, 0.090,
                f"old 10ms wait honored: {first_interval*1000:.1f}ms",
            )

    def test_request_wakeup_releases_long_wait(self):
        """An exit request 5 ms into a 500 ms pacing wait releases promptly."""
        with _PumpHarness() as pump:
            standalone.set_max_frame_rate(2.0)  # 500 ms period

            async def scenario():
                runner = asyncio.create_task(standalone.run_async())
                while len(pump.tick_times) < 1:
                    await asyncio.sleep(0.001)
                await asyncio.sleep(0.005)
                pump.close()
                standalone.request_wakeup()
                start = time.monotonic()
                await runner
                return time.monotonic() - start

            release = self._run(scenario())
            self.assertLess(
                release, 0.050,
                f"exit stranded behind pacing wait: {release*1000:.1f}ms",
            )

    def test_no_catchup_after_overrun(self):
        """A 30 ms overrun at a 20 ms cap must not shorten the following
        iteration below the period — the budget is per-iteration relative,
        not an absolute schedule."""
        with _PumpHarness() as pump:
            standalone.set_max_frame_rate(50.0)  # 20 ms period
            overran = {"done": False}
            original = standalone._ui._standalone_tick

            def slow_second_tick():
                pump.tick_times.append(time.monotonic())
                if len(pump.tick_times) == 2 and not overran["done"]:
                    overran["done"] = True
                    time.sleep(0.030)  # iteration overruns its budget

            async def scenario():
                with patch.object(
                    standalone._ui, "_standalone_tick", slow_second_tick
                ):
                    runner = asyncio.create_task(standalone.run_async())
                    while len(pump.tick_times) < 5:
                        await asyncio.sleep(0.001)
                    pump.close()
                    standalone.request_wakeup()
                    await runner

            self._run(scenario())
            intervals = [
                pump.tick_times[i] - pump.tick_times[i - 1]
                for i in range(1, 5)
            ]
            for i, interval in enumerate(intervals, start=1):
                self.assertGreaterEqual(
                    interval, 0.0195,
                    f"iteration {i} ran below the 20ms cap period: "
                    f"{interval*1000:.1f}ms (intervals: "
                    f"{[f'{v*1000:.1f}' for v in intervals]})",
                )


class TestBlockingRunWaitPrimitives(unittest.TestCase):
    """run()'s pacing uses the threading.Event wait; verify wakeup works
    cross-thread (the only way a change can land mid-wait there)."""

    def test_set_max_frame_rate_wakes_threading_wait(self):
        standalone._wakeup_event.clear()
        standalone._wakeup_break = False
        woke = {}

        def waiter():
            start = time.monotonic()
            standalone._wakeup_event.wait(0.5)
            woke["after"] = time.monotonic() - start

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.02)
        standalone.set_max_frame_rate(30.0)
        t.join(timeout=2.0)
        self.assertIn("after", woke)
        self.assertLess(woke["after"], 0.2)
        self.assertFalse(standalone._consume_wakeup_break())
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()

    def test_request_wakeup_with_active_run_sets_break_flag(self):
        standalone._reset_pacing_wake_state()
        standalone._run_active = True
        try:
            standalone.request_wakeup()
            self.assertTrue(standalone._wakeup_event.is_set())
            self.assertTrue(standalone._consume_wakeup_break())
            self.assertFalse(standalone._consume_wakeup_break())  # one-shot
        finally:
            standalone._run_active = False
            standalone._reset_pacing_wake_state()

    def test_request_wakeup_without_active_run_is_noop(self):
        standalone._reset_pacing_wake_state()
        self.assertFalse(standalone._run_active)
        standalone.request_wakeup()
        self.assertFalse(standalone._wakeup_event.is_set())
        self.assertFalse(standalone._wakeup_break)


class TestWakeStateLifecycle(unittest.TestCase):
    """Wake state is scoped to the active run: no leaks across iterations,
    runs, or init/run/shutdown cycles."""

    def _run_capped(self, prewake=False, wake_at_exit=False, n_ticks=3):
        """Drive a real run() at 20 FPS; return the tick intervals (ms)."""
        ticks = []
        state = {"close": False}
        with patch.object(
            standalone._ui, "_standalone_tick",
            lambda: ticks.append(time.monotonic()),
        ), patch.object(
            standalone._ui, "_standalone_should_close",
            lambda: state["close"],
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(20.0)  # 50 ms period
            if prewake:
                standalone.request_wakeup()  # no active run: must be a no-op

            async def app_task():
                while len(ticks) < n_ticks:
                    await asyncio.sleep(0.001)
                if wake_at_exit:
                    standalone.request_wakeup()
                state["close"] = True

            standalone.run(app_task())
            standalone._initialized = False
        return [
            (ticks[i] - ticks[i - 1]) * 1000.0 for i in range(1, len(ticks))
        ]

    def test_wake_at_exit_does_not_leak_into_next_run(self):
        first = self._run_capped(wake_at_exit=True)
        self.assertFalse(standalone._wakeup_break)
        self.assertFalse(standalone._wakeup_event.is_set())
        self.assertIsNone(standalone._async_wakeup_event)
        second = self._run_capped()
        for interval in second:
            self.assertGreaterEqual(
                interval, 45.0,
                f"stale wakeup leaked into a later run: {second}",
            )

    def test_noop_wake_cannot_uncap_a_later_run(self):
        intervals = self._run_capped(prewake=True)
        for interval in intervals:
            self.assertGreaterEqual(
                interval, 45.0,
                f"no-op wakeup produced an uncapped interval: {intervals}",
            )

    def test_run_async_completion_leaves_clean_state(self):
        with _PumpHarness() as pump:
            standalone.set_max_frame_rate(100.0)

            async def scenario():
                runner = asyncio.create_task(standalone.run_async())
                while len(pump.tick_times) < 2:
                    await asyncio.sleep(0.001)
                pump.close()
                standalone.request_wakeup()
                await runner

            asyncio.run(scenario())
            self.assertFalse(standalone._run_active)
            self.assertFalse(standalone._wakeup_break)
            self.assertFalse(standalone._wakeup_event.is_set())
            self.assertIsNone(standalone._async_wakeup_event)

    def test_shutdown_resets_wake_state(self):
        standalone._wakeup_break = True
        standalone._wakeup_event.set()
        with patch.object(standalone._ui, "_standalone_shutdown", lambda: None):
            standalone._initialized = True
            standalone.shutdown()
        self.assertFalse(standalone._wakeup_break)
        self.assertFalse(standalone._wakeup_event.is_set())


class TestActiveShutdown(unittest.TestCase):
    """shutdown() during an active low-FPS wait must release the waiter
    promptly (not strand it for the old period) and leave clean state."""

    def test_async_shutdown_releases_active_wait_promptly(self):
        ticks = []
        with patch.object(
            standalone._ui, "_standalone_tick",
            lambda: ticks.append(time.monotonic()),
        ), patch.object(
            standalone._ui, "_standalone_should_close", lambda: False
        ), patch.object(
            standalone._ui, "_standalone_shutdown", lambda: None
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(2.0)  # 500 ms period

            async def scenario():
                runner = asyncio.create_task(standalone.run_async())
                while len(ticks) < 1:
                    await asyncio.sleep(0.001)
                await asyncio.sleep(0.005)  # 5 ms into the 500 ms wait
                t0 = time.monotonic()
                standalone.shutdown()
                await runner
                return (time.monotonic() - t0) * 1000

            latency = asyncio.run(scenario())
        self.assertLess(
            latency, 100.0,
            f"active shutdown stranded the waiter: {latency:.1f} ms",
        )
        self.assertFalse(standalone._run_active)
        self.assertFalse(standalone._initialized)
        self.assertFalse(standalone._wakeup_break)
        self.assertFalse(standalone._wakeup_event.is_set())
        self.assertIsNone(standalone._async_wakeup_event)
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()

    def test_sync_shutdown_from_thread_releases_active_wait_promptly(self):
        ticks = []
        result = {}
        with patch.object(
            standalone._ui, "_standalone_tick",
            lambda: ticks.append(time.monotonic()),
        ), patch.object(
            standalone._ui, "_standalone_should_close", lambda: False
        ), patch.object(
            standalone._ui, "_standalone_shutdown", lambda: None
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(2.0)

            def killer():
                while len(ticks) < 1:
                    time.sleep(0.001)
                time.sleep(0.005)
                result["t0"] = time.monotonic()
                standalone.shutdown()

            t = threading.Thread(target=killer)
            t.start()
            standalone.run()
            done = time.monotonic()
            t.join(timeout=5.0)
        latency = (done - result["t0"]) * 1000
        self.assertLess(
            latency, 100.0,
            f"active shutdown stranded run(): {latency:.1f} ms",
        )
        self.assertFalse(standalone._run_active)
        self.assertFalse(standalone._wakeup_break)
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()

    def test_init_and_run_work_after_active_shutdown(self):
        """Shutdown/init overlap: a fresh cycle after an active shutdown
        starts from clean pacing state and honors its cap."""
        self.test_async_shutdown_releases_active_wait_promptly()
        ticks = []
        state = {"close": False}
        with patch.object(
            standalone._ui, "_standalone_tick",
            lambda: ticks.append(time.monotonic()),
        ), patch.object(
            standalone._ui, "_standalone_should_close",
            lambda: state["close"],
        ), patch.object(
            standalone._ui, "_standalone_shutdown", lambda: None
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(50.0)  # 20 ms period

            async def app_task():
                while len(ticks) < 3:
                    await asyncio.sleep(0.001)
                state["close"] = True

            standalone.run(app_task())
        intervals = [
            (ticks[i] - ticks[i - 1]) * 1000 for i in range(1, len(ticks))
        ]
        for interval in intervals:
            self.assertGreaterEqual(interval, 18.0, intervals)
        standalone.set_max_frame_rate(60.0)


class TestConcurrentRuns(unittest.TestCase):
    """Overlapping run()/run_async() invocations are rejected without
    corrupting the active runner's wake state."""

    def test_second_run_async_raises_and_leaves_runner_wakeable(self):
        ticks = []
        close = {"v": False}
        with patch.object(
            standalone._ui, "_standalone_tick",
            lambda: ticks.append(time.monotonic()),
        ), patch.object(
            standalone._ui, "_standalone_should_close", lambda: close["v"]
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(2.0)  # 500 ms period

            async def scenario():
                runner_a = asyncio.create_task(standalone.run_async())
                while len(ticks) < 1:
                    await asyncio.sleep(0.001)
                with self.assertRaises(RuntimeError):
                    await standalone.run_async()
                # Runner A's lifecycle state is untouched by the rejection.
                self.assertTrue(standalone._run_active)
                await asyncio.sleep(0.005)
                t0 = time.monotonic()
                close["v"] = True
                standalone.request_wakeup()  # must still reach runner A
                await runner_a
                return (time.monotonic() - t0) * 1000

            latency = asyncio.run(scenario())
            standalone._initialized = False
        self.assertLess(
            latency, 100.0,
            f"surviving runner lost wake delivery: {latency:.1f} ms",
        )
        self.assertFalse(standalone._run_active)
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()

    def test_sync_run_rejected_while_async_runner_active(self):
        ticks = []
        close = {"v": False}
        with patch.object(
            standalone._ui, "_standalone_tick",
            lambda: ticks.append(time.monotonic()),
        ), patch.object(
            standalone._ui, "_standalone_should_close", lambda: close["v"]
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(100.0)

            async def scenario():
                runner = asyncio.create_task(standalone.run_async())
                while len(ticks) < 1:
                    await asyncio.sleep(0.001)
                with self.assertRaises(RuntimeError):
                    standalone.run()
                self.assertTrue(standalone._run_active)
                close["v"] = True
                standalone.request_wakeup()
                await runner

            asyncio.run(scenario())
            standalone._initialized = False
        self.assertFalse(standalone._run_active)
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()


class TestSimultaneousAdmissionStress(unittest.TestCase):
    """Genuinely simultaneous cross-thread starts (barrier + tiny switch
    interval) must admit exactly one runner, every trial."""

    TRIALS = 20

    def _stress(self, kinds):
        import sys as _sys

        prev_interval = _sys.getswitchinterval()
        _sys.setswitchinterval(1e-6)
        try:
            for _ in range(self.TRIALS):
                close = {"v": False}
                barrier = threading.Barrier(len(kinds))
                admitted, rejected = [], []

                def sync_runner():
                    barrier.wait()
                    try:
                        standalone.run()
                        admitted.append("sync")
                    except RuntimeError:
                        rejected.append("sync")

                def async_runner():
                    barrier.wait()
                    try:
                        asyncio.run(standalone.run_async())
                        admitted.append("async")
                    except RuntimeError:
                        rejected.append("async")

                runners = {"sync": sync_runner, "async": async_runner}
                with patch.object(
                    standalone._ui, "_standalone_tick",
                    lambda: time.sleep(0.0005),
                ), patch.object(
                    standalone._ui, "_standalone_should_close",
                    lambda: close["v"],
                ), patch.object(
                    standalone._ui, "_standalone_shutdown", lambda: None
                ), patch.object(standalone, "init", lambda *a, **k: None):
                    standalone._initialized = True
                    standalone.set_max_frame_rate(400.0)
                    threads = [
                        threading.Thread(target=runners[k]) for k in kinds
                    ]
                    for t in threads:
                        t.start()
                    time.sleep(0.02)
                    close["v"] = True
                    for t in threads:
                        t.join(timeout=5.0)
                    standalone._initialized = False
                # Exactly one admitted; simultaneous losers rejected. (A
                # loser that arrived after the winner already exited may
                # legitimately be admitted sequentially — the invariant is
                # "never two at once", i.e. never zero rejections AND two
                # overlapping admissions; overlap is what the 20ms hold
                # above guarantees.)
                self.assertEqual(
                    len(admitted) + len(rejected), len(kinds),
                    (admitted, rejected),
                )
                self.assertLessEqual(len(admitted), 2)
                if len(admitted) == 2:
                    self.fail(
                        f"two runners admitted concurrently: {admitted}"
                    )
        finally:
            _sys.setswitchinterval(prev_interval)
            standalone._run_active = False
            standalone._reset_pacing_wake_state()
            standalone.set_max_frame_rate(60.0)

    def test_sync_sync(self):
        self._stress(["sync", "sync"])

    def test_async_async_separate_threads(self):
        self._stress(["async", "async"])

    def test_mixed_sync_async(self):
        self._stress(["sync", "async"])

    def test_survivor_still_wakeable_after_overlap_attempt(self):
        ticks = []
        close = {"v": False}
        with patch.object(
            standalone._ui, "_standalone_tick",
            lambda: ticks.append(time.monotonic()),
        ), patch.object(
            standalone._ui, "_standalone_should_close", lambda: close["v"]
        ), patch.object(
            standalone._ui, "_standalone_shutdown", lambda: None
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(2.0)  # 500 ms period

            result = {}

            def loser():
                try:
                    standalone.run()
                    result["loser"] = "admitted"
                except RuntimeError:
                    result["loser"] = "rejected"

            async def scenario():
                runner = asyncio.create_task(standalone.run_async())
                while len(ticks) < 1:
                    await asyncio.sleep(0.001)
                t = threading.Thread(target=loser)
                t.start()
                t.join(timeout=5.0)
                await asyncio.sleep(0.005)
                t0 = time.monotonic()
                close["v"] = True
                standalone.request_wakeup()
                await runner
                return (time.monotonic() - t0) * 1000

            latency = asyncio.run(scenario())
            standalone._initialized = False
        self.assertEqual(result["loser"], "rejected")
        self.assertLess(
            latency, 100.0,
            f"survivor lost wake delivery after overlap: {latency:.1f} ms",
        )
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()


class TestTeardownTickExclusion(unittest.TestCase):
    """The precise stale-guard interleaving: runner passes the loop guard,
    shutdown completes teardown, runner proceeds — the native tick must be
    skipped, not executed after teardown."""

    def _forced_interleaving(self, start_runner):
        log = []
        gate = threading.Event()
        in_guard = threading.Event()
        calls = {"n": 0}

        def hooked_should_close():
            # Per-iteration call sequence: outer guard, [tick], pacing
            # guard. Call 3 is iteration 2's OUTER guard: `_initialized`
            # was read True before this blocks; shutdown completes; on
            # release the runner proceeds toward the native tick.
            calls["n"] += 1
            if calls["n"] == 3:
                in_guard.set()
                gate.wait(5.0)
            return False if calls["n"] <= 3 else True

        with patch.object(
            standalone._ui, "_standalone_tick",
            lambda: log.append("tick"),
        ), patch.object(
            standalone._ui, "_standalone_should_close", hooked_should_close
        ), patch.object(
            standalone._ui, "_standalone_shutdown",
            lambda: log.append("teardown"),
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(1000.0)
            thread = start_runner()
            self.assertTrue(in_guard.wait(5.0))
            standalone.shutdown()
            gate.set()
            thread.join(timeout=5.0)
            self.assertFalse(thread.is_alive())
            standalone._initialized = False
        self.assertIn("teardown", log)
        after = log[log.index("teardown") + 1:]
        self.assertNotIn(
            "tick", after,
            f"native tick after teardown: {log}",
        )
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()

    def test_sync_runner_guard_to_tick_race(self):
        def start():
            t = threading.Thread(target=standalone.run)
            t.start()
            return t

        self._forced_interleaving(start)

    def test_async_runner_guard_to_tick_race(self):
        def start():
            t = threading.Thread(
                target=lambda: asyncio.run(standalone.run_async())
            )
            t.start()
            return t

        self._forced_interleaving(start)


class TestReentrantShutdown(unittest.TestCase):
    """Public shutdown() called from a native callback dispatched inside the
    tick (same thread) must not deadlock; teardown is deferred until the
    in-flight native work completes, and no later tick runs."""

    def test_shutdown_from_tick_callback_defers_teardown(self):
        log = []

        def tick_with_callback():
            log.append("tick-begin")
            standalone.shutdown()  # e.g. a native window-close listener
            log.append("tick-end")

        with patch.object(
            standalone._ui, "_standalone_tick", tick_with_callback
        ), patch.object(
            standalone._ui, "_standalone_should_close", lambda: False
        ), patch.object(
            standalone._ui, "_standalone_shutdown",
            lambda: log.append("teardown"),
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(100.0)
            runner = threading.Thread(target=standalone.run)
            t0 = time.monotonic()
            runner.start()
            runner.join(3.0)
            self.assertFalse(
                runner.is_alive(),
                "shutdown() from a native tick callback deadlocked",
            )
        self.assertLess(time.monotonic() - t0, 3.0)
        # Native work finished BEFORE teardown; exactly one tick ran.
        self.assertEqual(log, ["tick-begin", "tick-end", "teardown"])
        self.assertFalse(standalone._initialized)
        self.assertFalse(standalone._run_active)
        self.assertFalse(standalone._shutdown_requested_in_tick)
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()


class TestShutdownDuringAdmittedStartup(unittest.TestCase):
    """shutdown() landing after admission but before initialization stops
    that run: no re-initialization, no tick — no teardown->init->tick."""

    def test_stopped_startup_does_not_reinitialize(self):
        log = []
        hold = threading.Event()
        in_window = threading.Event()
        real_ensure = standalone._ensure_initialized_for_run

        def gated_ensure():
            in_window.set()
            hold.wait(5.0)
            return real_ensure()

        with patch.object(
            standalone._ui, "_standalone_tick", lambda: log.append("tick")
        ), patch.object(
            standalone._ui, "_standalone_should_close", lambda: False
        ), patch.object(
            standalone._ui, "_standalone_shutdown",
            lambda: log.append("teardown"),
        ), patch.object(
            standalone._ui, "_standalone_init",
            lambda *a: log.append("init"),
        ), patch.object(
            standalone, "_ensure_initialized_for_run", gated_ensure
        ):
            standalone._initialized = True  # backend up from a prior cycle
            standalone.set_max_frame_rate(100.0)
            runner = threading.Thread(target=standalone.run)
            runner.start()
            self.assertTrue(in_window.wait(5.0))
            standalone.shutdown()  # targets the admitted run
            marker = len(log)
            hold.set()
            runner.join(timeout=5.0)
            self.assertFalse(runner.is_alive())
        self.assertEqual(log[:marker], ["teardown"])
        self.assertNotIn("init", log[marker:])
        self.assertNotIn("tick", log[marker:])
        self.assertFalse(standalone._run_active)
        self.assertFalse(standalone._initialized)
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()


class TestOwnershipThroughCleanup(unittest.TestCase):
    """A runner retains the slot through loop-close and shutdown; a
    successor cannot be admitted while predecessor cleanup can still touch
    shared native state, and is admitted cleanly afterwards."""

    def test_successor_rejected_until_predecessor_cleanup_completes(self):
        log = []
        hold = threading.Event()
        in_cleanup = threading.Event()
        pred_ident = {}
        real_set_event_loop = asyncio.set_event_loop

        def gated_set_event_loop(loop):
            if loop is None and threading.get_ident() == pred_ident.get("id"):
                in_cleanup.set()
                hold.wait(5.0)
            return real_set_event_loop(loop)

        close = {"v": False}
        with patch.object(
            standalone._ui, "_standalone_tick",
            lambda: log.append("tick"),
        ), patch.object(
            standalone._ui, "_standalone_should_close", lambda: close["v"]
        ), patch.object(
            standalone._ui, "_standalone_shutdown",
            lambda: log.append("teardown"),
        ), patch.object(
            standalone.asyncio, "set_event_loop", gated_set_event_loop
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(200.0)

            def predecessor():
                pred_ident["id"] = threading.get_ident()
                standalone.run()

            pred = threading.Thread(target=predecessor)
            pred.start()
            time.sleep(0.02)
            close["v"] = True
            self.assertTrue(in_cleanup.wait(5.0))
            # Cleanup (shutdown) still pending: admission must fail and the
            # predecessor must remain the owner.
            with self.assertRaises(RuntimeError):
                standalone.run()
            self.assertTrue(standalone._run_active)
            self.assertNotIn("teardown", log)  # nothing torn down yet
            hold.set()
            pred.join(timeout=5.0)
            self.assertFalse(pred.is_alive())
            self.assertIn("teardown", log)     # predecessor's own teardown
            self.assertFalse(standalone._run_active)

            # After release, a successor is admitted cleanly.
            log.clear()
            close["v"] = False
            standalone._initialized = True

            async def close_soon():
                while not log:
                    await asyncio.sleep(0.001)
                close["v"] = True

            standalone.run(close_soon())
            self.assertIn("tick", log)
        standalone._initialized = False
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()


class TestShutdownUnderNativeExceptions(unittest.TestCase):
    """Shutdown stays authoritative and finalizes exactly once when the
    native tick or native teardown raises."""

    def test_tick_exception_still_processes_callback_shutdown(self):
        log = []
        close = {"v": False}

        def tick_then_raise():
            log.append("tick[A]")
            standalone.shutdown()
            raise RuntimeError("native tick failed")

        with patch.object(
            standalone._ui, "_standalone_should_close", lambda: close["v"]
        ), patch.object(
            standalone._ui, "_standalone_shutdown",
            lambda: log.append("teardown"),
        ), patch.object(
            standalone._ui, "_standalone_init", lambda *a: log.append("init")
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(100.0)

            async def failing_run():
                with patch.object(
                    standalone._ui, "_standalone_tick", tick_then_raise
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "native tick failed"
                    ):
                        await standalone.run_async()

            asyncio.run(failing_run())
            # Teardown/finalization completed BEFORE ownership was released
            # and before the tick exception reached the caller.
            self.assertEqual(log, ["tick[A]", "teardown"])
            self.assertFalse(standalone._initialized)
            self.assertFalse(standalone._shutdown_requested_in_tick)
            self.assertFalse(standalone._run_active)
            self.assertFalse(standalone._stop_requested)

            # A successor starts cleanly and is not torn down mid-run.
            async def successor():
                with patch.object(
                    standalone._ui, "_standalone_tick",
                    lambda: log.append("tick[B]"),
                ):
                    runner = asyncio.create_task(standalone.run_async())
                    while log.count("tick[B]") < 3:
                        await asyncio.sleep(0.001)
                    close["v"] = True
                    standalone.request_wakeup()
                    await runner

            asyncio.run(successor())
            self.assertGreaterEqual(log.count("tick[B]"), 3)
            self.assertEqual(log.count("teardown"), 1)  # A's only
            self.assertEqual(log.count("init"), 1)      # B's fresh init
        standalone._initialized = False
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()

    def test_tick_and_deferred_teardown_both_fail_keeps_tick_exception(self):
        """Precedence: the tick's operational exception propagates; the
        deferred-teardown failure is reported via the module logger."""
        close = {"v": False}

        def tick_then_raise():
            standalone.shutdown()
            raise RuntimeError("native tick failed")

        def raising_teardown():
            raise RuntimeError("native teardown failed")

        with patch.object(
            standalone._ui, "_standalone_should_close", lambda: close["v"]
        ), patch.object(
            standalone._ui, "_standalone_shutdown", raising_teardown
        ), patch.object(
            standalone._ui, "_standalone_tick", tick_then_raise
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(100.0)

            async def failing_run():
                with self.assertLogs(
                    "omni.ui.standalone", level="ERROR"
                ) as captured:
                    with self.assertRaisesRegex(
                        RuntimeError, "native tick failed"
                    ):
                        await standalone.run_async()
                self.assertTrue(
                    any("teardown failed" in line for line in captured.output)
                )

            asyncio.run(failing_run())
            self.assertFalse(standalone._initialized)
            self.assertFalse(standalone._shutdown_requested_in_tick)
            self.assertFalse(standalone._run_active)
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()

    def test_teardown_exception_still_releases_async_waiter(self):
        ticks = []
        close = {"v": False}

        def raising_teardown():
            raise RuntimeError("native teardown failed")

        with patch.object(
            standalone._ui, "_standalone_tick",
            lambda: ticks.append(time.monotonic()),
        ), patch.object(
            standalone._ui, "_standalone_should_close", lambda: close["v"]
        ), patch.object(
            standalone._ui, "_standalone_shutdown", raising_teardown
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(2.0)  # 500 ms period

            async def scenario():
                runner = asyncio.create_task(standalone.run_async())
                while len(ticks) < 1:
                    await asyncio.sleep(0.001)
                await asyncio.sleep(0.005)
                t0 = time.monotonic()
                with self.assertRaisesRegex(
                    RuntimeError, "native teardown failed"
                ):
                    standalone.shutdown()
                close["v"] = True
                await runner
                return (time.monotonic() - t0) * 1000

            latency = asyncio.run(scenario())
        self.assertLess(
            latency, 100.0,
            f"waiter stranded after teardown exception: {latency:.1f} ms",
        )
        self.assertFalse(standalone._initialized)
        self.assertFalse(standalone._run_active)
        # Repeated shutdown after a failed teardown: teardown is not
        # retried (initialized already False) and nothing raises.
        standalone.shutdown()
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()

    def test_teardown_exception_still_releases_sync_waiter(self):
        ticks = []
        result = {}

        def raising_teardown():
            raise RuntimeError("native teardown failed")

        with patch.object(
            standalone._ui, "_standalone_tick",
            lambda: ticks.append(time.monotonic()),
        ), patch.object(
            standalone._ui, "_standalone_should_close", lambda: False
        ), patch.object(
            standalone._ui, "_standalone_shutdown", raising_teardown
        ):
            standalone._initialized = True
            standalone.set_max_frame_rate(2.0)

            def killer():
                while len(ticks) < 1:
                    time.sleep(0.001)
                time.sleep(0.005)
                result["t0"] = time.monotonic()
                try:
                    standalone.shutdown()
                except RuntimeError as exc:
                    result["exc"] = str(exc)

            t = threading.Thread(target=killer)
            t.start()
            standalone.run()  # its own finally-shutdown skips (already down)
            done = time.monotonic()
            t.join(timeout=5.0)
        self.assertEqual(result.get("exc"), "native teardown failed")
        latency = (done - result["t0"]) * 1000
        self.assertLess(
            latency, 100.0,
            f"run() stranded after teardown exception: {latency:.1f} ms",
        )
        self.assertFalse(standalone._run_active)
        standalone.set_max_frame_rate(60.0)
        standalone._reset_pacing_wake_state()


if __name__ == "__main__":
    unittest.main()
