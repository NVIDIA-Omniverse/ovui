# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 2.6 — headless full-UI export hook in `Application`.

The hook fires once per frame between `await ui.next_frame()` and
`_on_frame_update`. Each tick must:

1. wait_ready (10ms timeout in ns)
2. extent → (w, h)
3. tap.acquire_linear_scratch(w, h) → (ptr, pitch)
4. headless_frame.copy_to_linear(ptr, pitch, 0)
5. tap.tee_linear_to_ovstream(ptr, w, h, pitch)  (swap + sync + stream
   are internal — Step 2.5 fix)
6. signal_consumed

These tests cover the hook in isolation by constructing an `Application`,
priming the export state by hand (the real run-loop setup needs ovui),
and driving `_run_headless_export_hook` directly. That mirrors how the
real loop sees the hook fire each tick.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock


def _make_active_export_app(headless_app, *, copy_returns=None,
                            wait_returns=None, extent=(1920, 1080),
                            pitch=7936):
    """Wire `headless_app` with mock tap + mock headless_frame so the
    export hook sees a fully active pipeline."""
    tap = MagicMock()
    tap.acquire_linear_scratch.side_effect = (
        lambda w, h: (0xCAFE0000, pitch)
    )
    tap.tee_linear_to_ovstream.return_value = True

    if copy_returns is None:
        copy_returns = iter([True] * 64)
    if wait_returns is None:
        wait_returns = iter([True] * 64)

    headless_frame = MagicMock()
    headless_frame.wait_ready.side_effect = lambda timeout_ns: next(wait_returns)
    headless_frame.extent.side_effect = lambda: extent
    headless_frame.copy_to_linear.side_effect = (
        lambda ptr, pitch_bytes, stream: next(copy_returns)
    )
    headless_frame.signal_consumed.return_value = None

    headless_app._headless_tap = tap
    headless_app._headless_frame_module = headless_frame
    headless_app._headless_export_active = True
    return tap, headless_frame


def test_hook_inactive_when_export_disabled(headless_app):
    """In windowed mode (or after a permanent disable) the hook is a
    pure no-op — it does not touch the tap or the headless_frame
    module even when those references are still set."""
    tap, headless_frame = _make_active_export_app(headless_app)
    headless_app._headless_export_active = False

    headless_app._run_headless_export_hook()

    tap.assert_not_called()
    tap.tee_linear_to_ovstream.assert_not_called()
    tap.acquire_linear_scratch.assert_not_called()
    headless_frame.wait_ready.assert_not_called()
    headless_frame.copy_to_linear.assert_not_called()
    headless_frame.signal_consumed.assert_not_called()


def test_hook_runs_full_pipeline_in_order_for_5_ticks(headless_app):
    """5 ticks of the hook → 5 strict orderings of
    wait_ready → extent → acquire → copy_to_linear →
    tee_linear_to_ovstream → signal_consumed.
    """
    parent = MagicMock()  # observes call ordering across tap + frame
    tap, headless_frame = _make_active_export_app(headless_app)
    parent.attach_mock(tap, "tap")
    parent.attach_mock(headless_frame, "frame")

    for _ in range(5):
        headless_app._run_headless_export_hook()

    # 5 tee calls with the (ptr, w, h, pitch) the hook pulled from
    # extent + acquire_linear_scratch.
    assert tap.tee_linear_to_ovstream.call_count == 5
    for c in tap.tee_linear_to_ovstream.call_args_list:
        args, _kw = c
        assert args == (0xCAFE0000, 1920, 1080, 7936)

    # Each tick walks the surface in the documented order.
    method_names = [c[0] for c in parent.mock_calls]
    expected_per_tick = [
        "frame.wait_ready",
        "frame.extent",
        "tap.acquire_linear_scratch",
        "frame.copy_to_linear",
        "tap.tee_linear_to_ovstream",
        "frame.signal_consumed",
    ]
    assert method_names == expected_per_tick * 5

    # wait_ready was called with the documented 10ms (ns) timeout.
    for c in headless_frame.wait_ready.call_args_list:
        args, _ = c
        assert args == (10_000_000,)
    # copy_to_linear is invoked on the default stream (handle 0).
    for c in headless_frame.copy_to_linear.call_args_list:
        args, _ = c
        assert args == (0xCAFE0000, 7936, 0)
    # signal_consumed was called once per tick.
    assert headless_frame.signal_consumed.call_count == 5


def test_wait_ready_false_disables_hook_permanently(headless_app):
    """Codex Issue 2: ``wait_ready`` returning ``False`` is a real
    pipeline malfunction (its contract is "True on success"); the
    hook must permanently disable, **not** treat it as a transient
    skip. ``signal_consumed`` is *not* issued because the V→C wait
    was never queued — there's nothing to balance.
    """
    tap, headless_frame = _make_active_export_app(
        headless_app,
        wait_returns=iter([False, True, True]),
    )

    headless_app._run_headless_export_hook()

    headless_frame.extent.assert_not_called()
    tap.acquire_linear_scratch.assert_not_called()
    headless_frame.copy_to_linear.assert_not_called()
    tap.tee_linear_to_ovstream.assert_not_called()
    # No signal_consumed — wait_ready never queued the V→C wait, so
    # there's no semaphore work to balance.
    headless_frame.signal_consumed.assert_not_called()
    assert headless_app._headless_export_active is False

    # Subsequent ticks short-circuit without calling any surface.
    headless_app._run_headless_export_hook()
    headless_frame.wait_ready.assert_called_once()


def test_copy_to_linear_false_disables_hook_after_signal_consumed(headless_app):
    """Codex Issue 2: ``copy_to_linear`` returning ``False`` after a
    successful ``wait_ready`` is also a permanent failure (pipeline
    not initialised or invalid params per the wrapper docstring).

    Critical ordering: ``signal_consumed`` MUST fire first so the V/C
    semaphore pair stays balanced (``wait_ready`` already queued the
    V→C wait). Only after that does the hook flip the disable flag.
    Without this ordering ovui's next render would block forever
    waiting on the missing C→V signal.
    """
    parent = MagicMock()  # observes call ordering
    tap, headless_frame = _make_active_export_app(
        headless_app,
        copy_returns=iter([False, True]),
    )
    parent.attach_mock(tap, "tap")
    parent.attach_mock(headless_frame, "frame")

    headless_app._run_headless_export_hook()

    # The pipeline ran up to copy_to_linear, then signaled, then disabled.
    method_names = [c[0] for c in parent.mock_calls]
    assert method_names == [
        "frame.wait_ready",
        "frame.extent",
        "tap.acquire_linear_scratch",
        "frame.copy_to_linear",
        "frame.signal_consumed",
    ], method_names

    headless_frame.copy_to_linear.assert_called_once()
    tap.tee_linear_to_ovstream.assert_not_called()
    headless_frame.signal_consumed.assert_called_once_with()
    assert headless_app._headless_export_active is False

    # Subsequent ticks short-circuit.
    headless_app._run_headless_export_hook()
    assert headless_frame.copy_to_linear.call_count == 1


def test_zero_extent_skips_pipeline_but_signals(headless_app):
    """If the headless pipeline reports a (0, 0) extent (ovui hasn't
    rendered yet) the hook does not allocate a scratch slot or call
    the tap — but it still signals consumption so semaphore pairing
    stays balanced."""
    tap, headless_frame = _make_active_export_app(
        headless_app, extent=(0, 0),
    )

    headless_app._run_headless_export_hook()

    tap.acquire_linear_scratch.assert_not_called()
    tap.tee_linear_to_ovstream.assert_not_called()
    headless_frame.copy_to_linear.assert_not_called()
    headless_frame.signal_consumed.assert_called_once_with()
    assert headless_app._headless_export_active is True


def test_wait_ready_exception_disables_hook(headless_app):
    """A raised `wait_ready` is a permanent failure: the hook flips
    `_headless_export_active` to False and the next tick is a no-op.
    The renderer keeps ticking unaffected."""
    tap, headless_frame = _make_active_export_app(headless_app)
    headless_frame.wait_ready.side_effect = RuntimeError("V→C semaphore broken")

    headless_app._run_headless_export_hook()

    assert headless_app._headless_export_active is False
    tap.tee_linear_to_ovstream.assert_not_called()
    # Subsequent ticks must short-circuit without calling any surface.
    headless_app._run_headless_export_hook()
    headless_frame.wait_ready.assert_called_once()  # exactly the failed call


def test_copy_to_linear_exception_disables_hook(headless_app):
    """An exception from `copy_to_linear` is a permanent failure
    (CUDA-level error). Disable + skip subsequent ticks."""
    tap, headless_frame = _make_active_export_app(headless_app)
    headless_frame.copy_to_linear.side_effect = RuntimeError("cudaMemcpy2DFromArrayAsync rc=700")

    headless_app._run_headless_export_hook()

    assert headless_app._headless_export_active is False
    tap.tee_linear_to_ovstream.assert_not_called()


def test_acquire_linear_scratch_exception_disables_hook(headless_app):
    """If the tap fails to allocate a scratch slot, the hook disables
    the export — there's nowhere to copy the frame into."""
    tap, headless_frame = _make_active_export_app(headless_app)
    tap.acquire_linear_scratch.side_effect = RuntimeError("cudaMallocPitch rc=2")

    headless_app._run_headless_export_hook()

    assert headless_app._headless_export_active is False
    headless_frame.copy_to_linear.assert_not_called()
    tap.tee_linear_to_ovstream.assert_not_called()


def test_signal_consumed_exception_disables_hook(headless_app):
    """A failure in `signal_consumed` after a successful frame is also
    a permanent disable — without it the V/C pair is unbalanced and
    ovui will block on its next render."""
    tap, headless_frame = _make_active_export_app(headless_app)
    headless_frame.signal_consumed.side_effect = RuntimeError("C→V semaphore signal failed")

    headless_app._run_headless_export_hook()

    # The frame did get streamed (failure happens after).
    tap.tee_linear_to_ovstream.assert_called_once()
    assert headless_app._headless_export_active is False


def test_hook_writes_acquired_pointer_into_copy_to_linear(headless_app):
    """The dst_dev_ptr handed to `copy_to_linear` is exactly the
    pointer returned by `tap.acquire_linear_scratch` — same buffer
    flows through to `tee_linear_to_ovstream`. Catches a regression
    where the hook might re-allocate or shuffle pointers between
    steps.
    """
    tap, headless_frame = _make_active_export_app(headless_app)
    # Make acquire return a per-tick distinct pointer so we can match
    # call → use within the same tick.
    counter = iter([0xAA00, 0xBB00, 0xCC00])
    tap.acquire_linear_scratch.side_effect = (
        lambda w, h: (next(counter), 7936)
    )

    for _ in range(3):
        headless_app._run_headless_export_hook()

    copy_calls = [c.args for c in headless_frame.copy_to_linear.call_args_list]
    tee_calls = [c.args for c in tap.tee_linear_to_ovstream.call_args_list]

    assert [c[0] for c in copy_calls] == [0xAA00, 0xBB00, 0xCC00]
    assert [t[0] for t in tee_calls] == [0xAA00, 0xBB00, 0xCC00]


def test_setup_skipped_when_env_unset(monkeypatch, headless_app):
    """`_setup_headless_export` is a no-op when `OMNIUI_HEADLESS` is
    unset (windowed mode). Nothing is allocated, no module is
    imported, and the hook stays inactive.
    """
    monkeypatch.delenv("OMNIUI_HEADLESS", raising=False)
    monkeypatch.delenv("OVGEAR_LIVESTREAM", raising=False)

    headless_app._setup_headless_export()

    assert headless_app._headless_tap is None
    assert headless_app._headless_frame_module is None
    assert headless_app._headless_export_active is False


def test_setup_skipped_when_only_omniui_headless_set(monkeypatch, headless_app):
    """Headless ovwidgets.app without livestream still must not start the
    export pipeline — both flags are required."""
    monkeypatch.setenv("OMNIUI_HEADLESS", "1")
    monkeypatch.delenv("OVGEAR_LIVESTREAM", raising=False)

    headless_app._setup_headless_export()

    assert headless_app._headless_export_active is False


def test_setup_treats_init_returning_false_as_failure(monkeypatch, headless_app):
    """Codex Issue 1: ``headless_frame.init()`` returning ``False``
    means the C++ pipeline refused (or was already initialised). In
    either case subsequent ``copy_to_linear`` / ``wait_ready`` calls
    can't be trusted, so the hook must NOT activate. The tap created
    earlier in setup is closed; ``_headless_export_active`` stays
    ``False``.
    """
    monkeypatch.setenv("OMNIUI_HEADLESS", "1")
    monkeypatch.setenv("OVGEAR_LIVESTREAM", "1")

    # Stub the import targets so setup runs end-to-end without
    # touching real ovstream / ovui state.
    fake_tap = MagicMock()
    fake_tap.close = MagicMock()
    fake_tap_class = MagicMock()
    fake_tap_class.maybe_create.return_value = fake_tap

    fake_module = types.ModuleType("ovui_data_adapters.openusd._livestream_tap")
    fake_module.LivestreamTap = fake_tap_class
    monkeypatch.setitem(
        __import__("sys").modules, "ovui_data_adapters.openusd._livestream_tap", fake_module,
    )

    fake_headless_frame = MagicMock()
    fake_headless_frame.init.return_value = False  # the trigger condition
    fake_standalone = types.ModuleType("omni.ui.standalone")
    fake_standalone.headless_frame = fake_headless_frame
    monkeypatch.setitem(
        __import__("sys").modules, "omni.ui.standalone", fake_standalone,
    )

    headless_app._setup_headless_export()

    fake_tap_class.maybe_create.assert_called_once_with()
    fake_headless_frame.init.assert_called_once_with()
    # Tap must be closed so we don't leak the ovstream Server that
    # ``maybe_create`` already brought up.
    fake_tap.close.assert_called_once_with()
    # Hook must remain inactive — no state written.
    assert headless_app._headless_tap is None
    assert headless_app._headless_frame_module is None
    assert headless_app._headless_export_active is False


def test_teardown_clears_state(headless_app):
    """Shutdown path: `_teardown_headless_export` closes the tap,
    shuts down the frame pipeline, and clears all state regardless of
    whether the hook was active."""
    tap, headless_frame = _make_active_export_app(headless_app)

    headless_app._teardown_headless_export()

    tap.close.assert_called_once_with()
    headless_frame.shutdown.assert_called_once_with()
    assert headless_app._headless_tap is None
    assert headless_app._headless_frame_module is None
    assert headless_app._headless_export_active is False


def test_teardown_swallows_close_exceptions(headless_app):
    """A failing tap.close() must not propagate from teardown — the
    rest of the application shutdown still has work to do.
    """
    tap, headless_frame = _make_active_export_app(headless_app)
    tap.close.side_effect = RuntimeError("close raised")
    headless_frame.shutdown.side_effect = RuntimeError("shutdown raised")

    # Must not raise.
    headless_app._teardown_headless_export()

    assert headless_app._headless_tap is None
    assert headless_app._headless_frame_module is None
    assert headless_app._headless_export_active is False


def test_setup_idempotent_when_already_active(headless_app):
    """Calling `_setup_headless_export` while the pipeline is already
    active is a no-op — does not double-initialise or overwrite
    state."""
    tap, headless_frame = _make_active_export_app(headless_app)
    pre_tap = headless_app._headless_tap
    pre_module = headless_app._headless_frame_module

    headless_app._setup_headless_export()

    assert headless_app._headless_tap is pre_tap
    assert headless_app._headless_frame_module is pre_module
    assert headless_app._headless_export_active is True


# ── Step 2.7: failure-isolation parity — exception resilience over many frames ──

def _drain_renderer_ticks(headless_app, n_ticks: int) -> None:
    """Drive `_on_frame_update` ``n_ticks`` times.

    `_on_frame_update` early-returns when `_viewport_window is None`
    (the windowed renderer is the only thing it would advance after
    the call_later sweep). The fixture leaves it None, so each tick
    exercises the call_later sweep and the early-return path — i.e.
    the same outer-loop work the headless main loop does every tick
    even when no viewport is rendering. Importantly, none of that
    work should be affected by a disabled headless export hook.
    """
    for _ in range(n_ticks):
        headless_app._on_frame_update(0.016)  # ~60 fps tick_dt


def test_wait_ready_raise_disables_then_60_frames_complete(headless_app):
    """Plan §2.7 acceptance test: an exception raised by
    ``wait_ready`` permanently disables the export hook AND the
    renderer (modeled by ``_on_frame_update`` plus 60 more hook
    calls) keeps ticking unaffected.

    After the disable:

    - the hook becomes a no-op (no surface methods touched);
    - 60 more hook invocations complete without raising;
    - 60 more ``_on_frame_update`` calls complete without raising.

    Mirrors the pattern from windowed tap's
    ``test_non_ovstream_error_does_not_propagate`` /
    ``test_disabled_tap_short_circuits``.
    """
    tap, headless_frame = _make_active_export_app(headless_app)
    headless_frame.wait_ready.side_effect = RuntimeError(
        "cudaWaitExternalSemaphoresAsync rc=700"
    )

    # Tick that raises → permanent disable.
    headless_app._run_headless_export_hook()
    assert headless_app._headless_export_active is False
    assert headless_frame.wait_ready.call_count == 1
    tap.tee_linear_to_ovstream.assert_not_called()
    headless_frame.copy_to_linear.assert_not_called()
    headless_frame.signal_consumed.assert_not_called()

    # 60 more hook ticks must short-circuit without raising and without
    # ever re-touching the failed surface.
    for _ in range(60):
        headless_app._run_headless_export_hook()
    assert headless_frame.wait_ready.call_count == 1  # never called again
    tap.tee_linear_to_ovstream.assert_not_called()

    # Renderer outer-loop work continues normally — 60 ticks, no raise.
    _drain_renderer_ticks(headless_app, 60)


def test_copy_to_linear_raise_disables_then_60_frames_complete(headless_app):
    """Same as above for ``copy_to_linear`` raising — the most likely
    real-world failure (a CUDA-level error from
    ``cudaMemcpy2DFromArrayAsync``). The renderer must be unaffected
    over 60 subsequent ticks; the hook must not retry."""
    tap, headless_frame = _make_active_export_app(headless_app)
    headless_frame.copy_to_linear.side_effect = RuntimeError(
        "cudaMemcpy2DFromArrayAsync rc=700 (illegal address)"
    )

    headless_app._run_headless_export_hook()
    assert headless_app._headless_export_active is False
    # The pipeline ran up to copy_to_linear and stopped there — no
    # signal_consumed (there's no contract requiring it after an
    # exception; the unwind happens through teardown on shutdown).
    headless_frame.copy_to_linear.assert_called_once()
    tap.tee_linear_to_ovstream.assert_not_called()
    headless_frame.signal_consumed.assert_not_called()

    # 60 more hook ticks must short-circuit cleanly.
    for _ in range(60):
        headless_app._run_headless_export_hook()
    headless_frame.copy_to_linear.assert_called_once()  # never retried
    tap.tee_linear_to_ovstream.assert_not_called()

    _drain_renderer_ticks(headless_app, 60)


def test_disable_logged_only_once_across_60_failed_ticks(headless_app):
    """Belt-and-suspenders: after 60 hook ticks against a raising
    ``wait_ready``, the disable warning is logged exactly once
    (``_headless_export_disable_logged`` flag prevents stderr spam).
    """
    tap, headless_frame = _make_active_export_app(headless_app)
    # Bypass the disable-on-first-failure short-circuit by leaving
    # the active flag True between calls — simulates the (impossible
    # in production, but structurally valid) case where a hypothetical
    # transient retry hits the same path repeatedly.
    headless_frame.wait_ready.side_effect = RuntimeError("intermittent")

    log_count_before = headless_app._headless_export_disable_logged

    for _ in range(60):
        headless_app._headless_export_active = True  # force re-entry
        headless_app._run_headless_export_hook()

    # Despite 60 forced re-entries, the one-shot log flag is set after
    # the first failure and stays set.
    assert headless_app._headless_export_disable_logged is True
    assert log_count_before is False  # was unset to begin with
