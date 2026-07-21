# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Headless live-resize safety tests for the ovui binding added in
commit ``342259d`` and hardened against the Codex Step 3.7
re-review NOT-GOOD findings (`fix(headless): make runtime resize
safe and transactional`).

These tests boot the real headless Vulkan stack, exercise the
``omni.ui.standalone.headless_frame`` pipeline, and prove:

1. **Drain-then-resize after signal_consumed.**
   ``wait_ready → copy_to_linear → signal_consumed → resize → wait_ready
   → copy_to_linear`` runs through without semaphore/interop teardown
   hazards. The pre-fix ``resizeHeadlessFrame`` tore down
   ``s_headlessFrameInterop`` before the queued CUDA C→V signal had
   completed; the new ``CudaVulkanInterop::drainPendingHandoff``
   (cudaStreamSynchronize + vkDeviceWaitIdle) makes that safe.

2. **Transactional framebuffer recreation.** A request that exceeds
   the Vulkan device's ``maxImageDimension2D`` limit must fail
   ``createFramebuffer`` cleanly: ``resize`` returns ``False``, the
   prior ``extent()`` is preserved, and the next valid resize still
   works. The pre-fix code committed ``m_fbWidth/m_fbHeight`` before
   trying to create new resources, so a failed recreate left the
   backend reporting a fake new extent.

The tests SKIP when the host doesn't have Vulkan/CUDA hardware so
they don't break the rest of the suite on machines that lack the
runtime — but they fully exercise the production path on the GPU
DGXC VM where issue #34 is being developed.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def headless_ovui():
    """Initialise ovui in headless Vulkan mode for the lifetime of
    the test module. The init sequence mirrors what
    ``ovui_widgets.app.headless`` does at production startup, but bare
    (no Application, no panels) so the test isolates the
    framebuffer-resize path."""
    # Required envs for headless Vulkan + CUDA interop. Set BEFORE
    # importing omni.ui to make sure the C++ side reads the correct
    # values during ``standalone::init``.
    os.environ.setdefault("OMNIUI_HEADLESS", "1")
    os.environ.setdefault("OMNIUI_BACKEND", "vulkan")

    try:
        from omni.ui import standalone
        from omni.ui.standalone import headless_frame
    except Exception as exc:
        pytest.skip(f"omni.ui not importable: {exc}")

    # standalone.init returns None on success in this build of ovui
    # (the Python wrapper doesn't surface the C++ bool). Catch
    # exceptions instead.
    try:
        standalone.init(width=320, height=240)
    except Exception as exc:
        pytest.skip(f"ovui standalone init failed: {exc}")
    # Drive a couple of frames so the offscreen render target is
    # populated before headless_frame.init imports it into CUDA.
    for _ in range(3):
        standalone._tick_one_frame()
    if not headless_frame.init():
        pytest.skip("headless_frame.init returned False (CUDA-Vulkan interop unavailable)")

    yield standalone, headless_frame

    headless_frame.shutdown()
    standalone.shutdown()


def _alloc_pitched_dst(cudart, width: int, height: int) -> tuple[int, int]:
    """Allocate a pitched RGBA8 device buffer big enough for one
    frame and return ``(dev_ptr, pitch)``."""
    ptr, pitch = cudart.malloc_pitch(width * 4, height)
    return int(ptr), int(pitch)


def test_drain_handoff_then_resize_then_copy(headless_ovui):
    """Plan acceptance for Codex Step 3.7 re-review #1.

    Sequence:
    1. wait_ready → copy_to_linear → signal_consumed.
       This arms an async CUDA signal on the C→V semaphore.
    2. resize.
       The pre-fix code tore down the interop handles while the
       semaphore was still in flight. The new ``drainPendingHandoff``
       (``cudaStreamSynchronize`` + ``vkDeviceWaitIdle``) blocks
       until the handoff has retired, then it's safe to destroy.
    3. wait_ready → copy_to_linear.
       The new (post-resize) imports work for export.

    Test passes if every step returns success and the second copy
    target receives non-zero pitch at the new extent.
    """
    standalone, headless_frame = headless_ovui
    try:
        from ovui_data_adapters.openusd._livestream_tap import _Cudart
    except Exception as exc:
        pytest.skip(f"_Cudart helper not importable: {exc}")

    cudart = _Cudart()

    # Drive one tick so a fresh frame is queued for export.
    standalone._tick_one_frame()

    # 1. wait_ready / copy / signal_consumed at the original extent.
    w0, h0 = headless_frame.extent()
    assert w0 > 0 and h0 > 0
    dst_ptr_0, pitch_0 = _alloc_pitched_dst(cudart, w0, h0)
    try:
        assert headless_frame.wait_ready(10_000_000) is True
        assert headless_frame.copy_to_linear(dst_ptr_0, pitch_0) is True
        headless_frame.signal_consumed()  # arms async CUDA signal

        # 2. Resize immediately — proves the drain is safe.
        new_w, new_h = 416, 304
        assert headless_frame.resize(new_w, new_h) is True

        # 3. Drive another tick so the new framebuffer has content,
        #    then run the full export pipeline at the new extent.
        standalone._tick_one_frame()
        w1, h1 = headless_frame.extent()
        assert (w1, h1) == (new_w, new_h)
    finally:
        cudart.free(dst_ptr_0)

    dst_ptr_1, pitch_1 = _alloc_pitched_dst(cudart, w1, h1)
    try:
        assert headless_frame.wait_ready(10_000_000) is True
        assert headless_frame.copy_to_linear(dst_ptr_1, pitch_1) is True
        headless_frame.signal_consumed()
    finally:
        cudart.free(dst_ptr_1)


def test_resize_to_unsupported_extent_returns_false_and_preserves_prior_extent(
    headless_ovui,
):
    """Plan acceptance for Codex Step 3.7 re-review #2.

    A resize request that exceeds the Vulkan device's
    ``maxImageDimension2D`` limit (or otherwise causes
    ``createFramebuffer`` to fail) must:

    - return ``False`` from ``headless_frame.resize``;
    - NOT corrupt ``headless_frame.extent()`` — it must still
      report the prior valid size, not the requested one;
    - leave the framebuffer in a state that subsequent valid
      resizes still work.

    The pre-fix code committed ``m_fbWidth``/``m_fbHeight`` to the
    requested values *before* trying to create the new resources,
    so a failed create returned False but ``extent()`` reported the
    fake new extent.
    """
    standalone, headless_frame = headless_ovui

    # First, get a known-good baseline.
    assert headless_frame.resize(384, 288) is True
    standalone._tick_one_frame()
    w_before, h_before = headless_frame.extent()
    assert (w_before, h_before) == (384, 288)

    # Vulkan ``maxImageDimension2D`` is at least 4096 on every
    # compliant device and typically 16384–32768 on modern GPUs.
    # 200000×200000 is far above any current device limit and will
    # fail ``vkCreateImage`` with VK_ERROR_OUT_OF_DEVICE_MEMORY or
    # VK_ERROR_FORMAT_NOT_SUPPORTED on every implementation.
    too_big_w, too_big_h = 200_000, 200_000
    assert headless_frame.resize(too_big_w, too_big_h) is False

    # Critical invariant: the prior extent is preserved on failure.
    w_after, h_after = headless_frame.extent()
    assert (w_after, h_after) == (w_before, h_before), (
        f"resize({too_big_w}, {too_big_h}) failed but extent corrupted: "
        f"was {(w_before, h_before)}, now {(w_after, h_after)}"
    )

    # Recovery: a subsequent valid resize still works.
    assert headless_frame.resize(256, 192) is True
    standalone._tick_one_frame()
    w_recover, h_recover = headless_frame.extent()
    assert (w_recover, h_recover) == (256, 192)


def test_resize_aborts_when_drain_handoff_fails_and_does_not_destroy_interop(
    headless_ovui,
):
    """Codex Step 3.7 re-review #3 fix.

    ``CudaVulkanInterop::drainPendingHandoff`` now returns ``bool``;
    ``standalone::resizeHeadlessFrame`` aborts BEFORE
    ``s_headlessFrameInterop->shutdown()`` / reset when the drain
    fails. Pre-fix behavior: drain logged and returned ``void``, so
    the resize tore the interop down anyway, leaving destroyed
    semaphores while CUDA / Vulkan work might still be in flight.

    The proof:
    1. Establish a baseline extent — drives the export pipeline so
       the interop is fully initialised.
    2. Arm the test seam so the next ``drainPendingHandoff`` returns
       ``false``.
    3. Call ``resize(new_w, new_h)`` and assert it returns ``False``.
    4. Assert ``extent()`` still reports the prior valid extent —
       i.e. the framebuffer is intact and was not recreated, and the
       interop's import wasn't replaced.
    5. Assert the export pipeline still works at the prior extent
       (``wait_ready`` + ``copy_to_linear``) — direct evidence that
       the interop was NOT destroyed.
    6. Clear the test seam and assert a follow-up valid resize still
       succeeds and ``extent()`` reflects the new size.
    """
    standalone, headless_frame = headless_ovui
    from omni.ui import _ui as _ui_native

    if not hasattr(_ui_native, "_headless_frame_test_inject_drain_failure"):
        pytest.skip("ovui build lacks the drain-failure test seam")

    try:
        from ovui_data_adapters.openusd._livestream_tap import _Cudart
    except Exception as exc:
        pytest.skip(f"_Cudart helper not importable: {exc}")
    cudart = _Cudart()

    # 1. Baseline.
    assert headless_frame.resize(384, 288) is True
    standalone._tick_one_frame()
    w0, h0 = headless_frame.extent()
    assert (w0, h0) == (384, 288)

    # 2. Arm the fault injection.
    _ui_native._headless_frame_test_inject_drain_failure(True)

    # 3. Resize attempt — drain fails, resize aborts before
    #    teardown, returns False.
    assert headless_frame.resize(512, 384) is False

    # 4. Extent is preserved — neither the framebuffer was
    #    recreated nor the interop's imports were replaced.
    w_after, h_after = headless_frame.extent()
    assert (w_after, h_after) == (w0, h0), (
        f"resize aborted but extent corrupted: was {(w0, h0)}, "
        f"now {(w_after, h_after)}"
    )

    # 5. Export pipeline still works at the prior extent — direct
    #    evidence that the interop is intact (its CUDA imports
    #    weren't destroyed). If the resize had torn the interop
    #    down anyway (the pre-fix bug), wait_ready / copy_to_linear
    #    would crash on the freed handles.
    standalone._tick_one_frame()
    dst_ptr, pitch = cudart.malloc_pitch(w_after * 4, h_after)
    try:
        assert headless_frame.wait_ready(10_000_000) is True
        assert headless_frame.copy_to_linear(dst_ptr, pitch) is True
        headless_frame.signal_consumed()
    finally:
        cudart.free(dst_ptr)

    # 6. Recovery: with the fault injection cleared (the seam is
    #    one-shot so this is automatic), a follow-up valid resize
    #    works.
    assert headless_frame.resize(320, 240) is True
    standalone._tick_one_frame()
    w_recover, h_recover = headless_frame.extent()
    assert (w_recover, h_recover) == (320, 240)


def test_drain_failure_seam_is_one_shot(headless_ovui):
    """The fault-injection flag must clear itself after one trip so
    a single ``True`` arm doesn't permanently disable resize."""
    standalone, headless_frame = headless_ovui
    from omni.ui import _ui as _ui_native

    if not hasattr(_ui_native, "_headless_frame_test_inject_drain_failure"):
        pytest.skip("ovui build lacks the drain-failure test seam")

    # Establish baseline.
    assert headless_frame.resize(384, 288) is True
    standalone._tick_one_frame()

    # Arm + first call: fails.
    _ui_native._headless_frame_test_inject_drain_failure(True)
    assert headless_frame.resize(512, 384) is False
    standalone._tick_one_frame()

    # Second call without re-arming: succeeds.
    assert headless_frame.resize(256, 192) is True
    standalone._tick_one_frame()
    assert headless_frame.extent() == (256, 192)


def test_resize_invalid_dimensions_returns_false(headless_ovui):
    """Negative / zero / oversized-int dimensions are rejected at
    the C++ entry point without touching the framebuffer.
    Defensive lower-bound coverage."""
    standalone, headless_frame = headless_ovui

    standalone._tick_one_frame()
    w_before, h_before = headless_frame.extent()

    # Each invalid input should bounce off the validation in
    # ``standalone::resizeHeadlessFrame`` (width <= 0 || height <= 0).
    for w, h in [(0, 100), (100, 0), (-1, 100), (100, -1), (0, 0)]:
        assert headless_frame.resize(w, h) is False, (
            f"resize({w}, {h}) should return False"
        )

    w_after, h_after = headless_frame.extent()
    assert (w_after, h_after) == (w_before, h_before)
