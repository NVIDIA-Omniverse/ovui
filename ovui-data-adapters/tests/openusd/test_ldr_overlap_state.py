# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Deterministic tests for the depth-one LdrColor overlap state machine."""

from __future__ import annotations

import numpy as np
import pytest

from ovui_data_adapters.common._ldr_overlap import (
    CameraSnapshot,
    LdrOverlapState,
    camera_state_differs,
)

H, W = 4, 6
KEY = ("stage", "/Render/P", (W, H), "renderer")


def snap(seq: int, *, fov: float = 1.0, size=(W, H)) -> CameraSnapshot:
    view = np.eye(4)
    view[0, 3] = float(seq)  # camera translates one unit per frame
    proj = np.eye(4)
    proj[0, 0] = fov
    return CameraSnapshot.capture(view, proj, size)


def image(seq: int) -> np.ndarray:
    return np.full((H, W, 4), seq % 251, dtype=np.uint8)


class Products:
    """Stand-in step-result container tagged with its frame sequence."""

    def __init__(self, seq: int) -> None:
        self.seq = seq


def extractor(calls: list[int]):
    def extract(products: Products) -> np.ndarray:
        calls.append(products.seq)
        return image(products.seq)
    return extract


def drive(state: LdrOverlapState, seq: int, *, key=KEY, pick_skip=False,
          calls=None, fov: float = 1.0):
    calls = calls if calls is not None else []
    return state.consume(Products(seq), key, snap(seq, fov=fov),
                         extractor(calls), (H, W), pick_skip)


# ── fill sequence: sync -> duplicate -> steady overlap ───────────────────


def test_fill_sequence_and_steady_overlap():
    state = LdrOverlapState()
    calls: list[int] = []

    first = state.consume(Products(1), KEY, snap(1), extractor(calls), (H, W), False)
    assert calls == [1] and first[0, 0, 0] == 1          # sync fill: own image
    assert state.presented_snapshot.view[0, 3] == 1.0

    second = state.consume(Products(2), KEY, snap(2), extractor(calls), (H, W), False)
    assert calls == [1]                                   # duplicate: no extract
    assert second[0, 0, 0] == 1                           # re-presents frame 1
    assert state.presented_snapshot.view[0, 3] == 1.0     # snapshot matches image

    third = state.consume(Products(3), KEY, snap(3), extractor(calls), (H, W), False)
    assert calls == [1, 2] and third[0, 0, 0] == 2        # steady: presents N-1
    assert state.presented_snapshot.view[0, 3] == 2.0

    fourth = state.consume(Products(4), KEY, snap(4), extractor(calls), (H, W), False)
    assert calls == [1, 2, 3] and fourth[0, 0, 0] == 3


def test_presented_sequence_is_monotonic_with_duplicates_only():
    state = LdrOverlapState()
    presented: list[float] = []
    for seq in range(1, 30):
        pick_skip = seq in (7, 15)  # simulated moving-camera picks
        drive(state, seq, pick_skip=pick_skip)
        presented.append(float(state.presented_snapshot.view[0, 3]))
    for prev, cur in zip(presented, presented[1:]):
        assert cur >= prev, f"visual rewind: {prev} -> {cur}"
    assert any(a == b for a, b in zip(presented, presented[1:]))  # explicit dups


# ── complete-camera association ───────────────────────────────────────────


def test_presented_snapshot_travels_with_presented_image():
    state = LdrOverlapState()
    for seq in range(1, 6):
        img = drive(state, seq)
        shown = state.presented_snapshot
        assert shown.view[0, 3] == float(img[0, 0, 0])  # snapshot == image frame


def test_camera_state_differs_covers_view_projection_and_size():
    base = snap(1)
    assert not camera_state_differs(base, base.view, base.projection, base.size)
    moved = snap(2)
    assert camera_state_differs(base, moved.view, base.projection, base.size)
    fov = snap(1, fov=1.2)  # projection-only change (FOV animation)
    assert camera_state_differs(base, base.view, fov.projection, base.size)
    assert camera_state_differs(base, base.view, base.projection, (W + 2, H))


# ── moving-camera picks: skip + one duplicate, never a rewind ─────────────


def test_pick_skip_presents_one_duplicate_and_never_the_pick_frame():
    state = LdrOverlapState()
    calls: list[int] = []
    for seq in (1, 2, 3):
        state.consume(Products(seq), KEY, snap(seq), extractor(calls), (H, W), False)
    # frame 4 carries a moving-camera pick: its color must never be shown
    out4 = state.consume(Products(4), KEY, snap(4), extractor(calls), (H, W), True)
    assert out4[0, 0, 0] == 3                       # presents N-1 normally
    out5 = state.consume(Products(5), KEY, snap(5), extractor(calls), (H, W), False)
    assert out5[0, 0, 0] == 3                       # explicit duplicate
    out6 = state.consume(Products(6), KEY, snap(6), extractor(calls), (H, W), False)
    assert out6[0, 0, 0] == 5                       # resumes with NEWER frame
    assert 4 not in calls                           # pick frame never extracted


def test_static_pick_adds_no_duplicate():
    state = LdrOverlapState()
    presented = []
    for seq in (1, 2, 3, 4, 5):
        drive(state, seq, pick_skip=False)  # static clicks: caller passes False
        presented.append(float(state.presented_snapshot.view[0, 3]))
    assert presented == [1.0, 1.0, 2.0, 3.0, 4.0]  # only the fill duplicate


# ── key changes and failures ─────────────────────────────────────────────


def test_key_change_refills_synchronously_with_current_frame():
    state = LdrOverlapState()
    calls: list[int] = []
    for seq in (1, 2, 3):
        state.consume(Products(seq), KEY, snap(seq), extractor(calls), (H, W), False)
    new_key = ("stage2",) + KEY[1:]
    out = state.consume(Products(4), new_key, snap(4), extractor(calls), (H, W), False)
    assert out[0, 0, 0] == 4                        # current frame, no stale
    assert calls == [1, 2, 4]                       # retained 3 dropped unmapped


def test_consumption_failure_invalidates_exactly_once_and_recovers():
    state = LdrOverlapState()
    calls: list[int] = []
    for seq in (1, 2):
        state.consume(Products(seq), KEY, snap(seq), extractor(calls), (H, W), False)

    def failing(products: Products) -> np.ndarray:
        raise RuntimeError("injected consumption failure")

    with pytest.raises(RuntimeError):
        state.consume(Products(3), KEY, snap(3), failing, (H, W), False)
    assert state.retained_products is None          # exactly-once invalidation
    assert state.last_image is None
    assert state.presented_snapshot is None

    out = state.consume(Products(4), KEY, snap(4), extractor(calls), (H, W), False)
    assert out[0, 0, 0] == 4                        # sync refill, no stale frame


def test_duplicate_size_mismatch_falls_back_to_sync():
    state = LdrOverlapState()
    calls: list[int] = []
    state.consume(Products(1), KEY, snap(1), extractor(calls), (H, W), False)
    # cache is (H, W); ask for a different extract size on the dup path
    out = state.consume(Products(2), KEY, snap(2, size=(W + 2, H)),
                        extractor(calls), (H, W + 2), False)
    assert calls == [1, 2] and out[0, 0, 0] == 2    # fresh, correctly sized


# ── ownership release ─────────────────────────────────────────────────────


def test_release_is_idempotent_and_reports_holding():
    state = LdrOverlapState()
    calls: list[int] = []
    state.consume(Products(1), KEY, snap(1), extractor(calls), (H, W), False)
    assert state.release() is True
    assert state.release() is False
    assert state.retained_products is None
    assert state.last_image is None and state.presented_snapshot is None


def test_release_then_consume_refills_with_current_frame():
    state = LdrOverlapState()
    calls: list[int] = []
    for seq in (1, 2, 3):
        state.consume(Products(seq), KEY, snap(seq), extractor(calls), (H, W), False)
    state.release()                                  # native mutation boundary
    out = state.consume(Products(4), KEY, snap(4), extractor(calls), (H, W), False)
    assert out[0, 0, 0] == 4                        # nothing pre-mutation shown
    assert 3 not in calls[2:]
