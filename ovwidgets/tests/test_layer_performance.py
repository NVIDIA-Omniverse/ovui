# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Layers-window performance benchmarks (LAYERS-PLAN Step 61).

Guards four budgets from LAYERS-WINDOW-ARCHITECTURE §35:

* 500-sublayer tree build under 1 second (§35.1).
* 1000 adapter events in a single frame flushed in ≤ 2 batches under 100ms
  (§35.3 — the batch mechanism is the critical perf win).
* Name-search filter on a layer holding 10k prim specs under 100ms (§35.4).
* Flatten-command snapshot buffer ≤ 16MB for 15 × 1MB layers (§35 / Step 42).

The first three tests run headless against ``MockLayerStackAdapter``; the
memory budget needs ``pxr`` to exercise the real snapshot round-trip. All
tests are tagged ``@pytest.mark.performance`` so CI can opt-in; they stay
part of the default run because each one completes in well under a second
on the reference hardware.
"""

from __future__ import annotations

import sys
import time

import pytest
from ovui_data_adapters.common import LayerEvent, LayerEventType

from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER, MockLayerStackAdapter
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers.layer_model import LayerModel

try:  # pragma: no cover — import guard, not exercised in no-pxr CI
    from pxr import Sdf, Usd

    _HAS_USD = True
except ImportError:  # pragma: no cover
    _HAS_USD = False


class _DeferringApp:
    """Minimal ``Application`` stand-in that queues ``call_later`` callbacks.

    Mirrors the helper in :mod:`tests.test_layer_model` — the real
    :meth:`Application.call_later` hops onto the frame loop so many
    synchronous adapter events in one tick coalesce into a single
    :meth:`LayerModel._flush_events` call. Tests need manual control
    over that drain so the batch-count assertion is deterministic.
    """

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()
        self._queue: list = []
        self.flush_calls: int = 0

    def call_later(self, _delay: float, cb) -> None:
        self._queue.append(cb)

    def tick(self) -> int:
        fired = 0
        while self._queue:
            cb = self._queue.pop(0)
            cb()
            fired += 1
        return fired

    @property
    def pending(self) -> int:
        return len(self._queue)


# ── 1 · Tree build for 500 sublayers ──────────────────────────────────────────


@pytest.mark.performance
class TestTreeBuild500Sublayers:
    """LAYERS-WINDOW-ARCHITECTURE §35.1 — 500 sublayers build under 1s."""

    BUDGET_S = 1.0

    def test_build_500_flat_sublayers_under_1s(self) -> None:
        """500 direct sublayers under the root build in < 1s (cold)."""
        adapter = MockLayerStackAdapter()
        for i in range(500):
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, f"sub_{i:04d}")

        start = time.perf_counter()
        model = LayerModel(adapter)
        elapsed = time.perf_counter() - start

        try:
            assert model._root_item is not None
            assert len(model._root_item.sublayers) == 500
            assert elapsed < self.BUDGET_S, (
                f"LayerModel build with 500 sublayers took "
                f"{elapsed * 1000:.1f}ms (budget {self.BUDGET_S * 1000:.0f}ms)"
            )
        finally:
            model.destroy()

    def test_build_nested_depth_50_under_1s(self) -> None:
        """A 50-deep chain of sublayers (~500 cycle-check steps) stays fast.

        Depth stresses the cycle-detection walk in
        :meth:`LayerModel._load_sublayers` which scans each new item's
        parent chain. This test guards against accidentally making that
        walk quadratic in total tree size.
        """
        adapter = MockLayerStackAdapter()
        parent = ROOT_LAYER_IDENTIFIER
        # Chain width 10 at each of 50 levels → 500 sublayer constructions
        # with the deepest layer paying a 50-step cycle check.
        for depth in range(50):
            child = f"level_{depth:02d}"
            adapter.add_sublayer(parent, child)
            for i in range(9):
                adapter.add_sublayer(parent, f"peer_{depth:02d}_{i}")
            parent = child

        start = time.perf_counter()
        model = LayerModel(adapter)
        elapsed = time.perf_counter() - start

        try:
            assert elapsed < self.BUDGET_S, (
                f"Nested 500-sublayer build took {elapsed * 1000:.1f}ms "
                f"(budget {self.BUDGET_S * 1000:.0f}ms)"
            )
        finally:
            model.destroy()


# ── 2 · Event batching under load ─────────────────────────────────────────────


@pytest.mark.performance
class TestEventBatching:
    """LAYERS-WINDOW-ARCHITECTURE §35.3 — 1000 events coalesce into one flush."""

    BUDGET_S = 0.1

    def test_1000_dirty_events_flush_in_one_batch(self) -> None:
        """1000 dirty flips in one frame → exactly 1 ``_flush_events`` call."""
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        for i in range(10):
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, f"sub_{i}")
        model = LayerModel(adapter, services=app)
        try:
            # Burst 1000 events across the 10 sublayers, alternating the
            # flag so each call actually fires (``set_dirty`` short-
            # circuits when the bit already matches).
            start = time.perf_counter()
            for n in range(1000):
                target = f"sub_{n % 10}"
                # ``set_dirty`` short-circuits when the state matches,
                # so alternate the whole round to keep every call an
                # actual transition and every event on the queue.
                adapter.set_dirty(target, (n // 10) % 2 == 0)
            # Before the frame drain, exactly one flush is scheduled
            # regardless of how many events are queued.
            assert app.pending == 1
            assert len(model._pending_events) == 1000
            # Drain the "frame" — this is the single ``_flush_events``
            # call that processes the whole batch.
            fired = app.tick()
            elapsed = time.perf_counter() - start

            assert fired == 1, (
                f"Expected 1 batched flush; got {fired}. The per-event "
                "path collapsed the batching — check _on_layer_event's "
                "call_later gate."
            )
            assert model._pending_events == []
            assert elapsed < self.BUDGET_S, (
                f"1000 batched events processed in {elapsed * 1000:.1f}ms "
                f"(budget {self.BUDGET_S * 1000:.0f}ms)"
            )
        finally:
            model.destroy()

    def test_1000_sublayer_events_flush_in_one_batch(self) -> None:
        """1000 synthetic SUBLAYERS_CHANGED events in one frame flush once.

        Structural events hit the widest rebuild path in
        :meth:`LayerModel._flush_events` — validating it stays O(1)
        flushes per frame catches regressions where a later phase
        accidentally forces per-event rebuilds.
        """
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_0")
        model = LayerModel(adapter, services=app)
        try:
            start = time.perf_counter()
            for _ in range(1000):
                # Fire synthetic events straight into the model so we
                # exercise the batch path without paying the mock's
                # per-event bookkeeping cost.
                model._on_layer_event(
                    LayerEvent(
                        event_type=LayerEventType.SUBLAYERS_CHANGED,
                        identifiers=(ROOT_LAYER_IDENTIFIER,),
                    )
                )
            assert app.pending == 1
            fired = app.tick()
            elapsed = time.perf_counter() - start

            assert fired == 1
            assert elapsed < self.BUDGET_S, (
                f"1000 structural events processed in {elapsed * 1000:.1f}ms "
                f"(budget {self.BUDGET_S * 1000:.0f}ms)"
            )
        finally:
            model.destroy()


# ── 3 · Filter over a 10k-prim-spec layer ─────────────────────────────────────


@pytest.mark.performance
class TestFilter10kPrimSpecs:
    """LAYERS-WINDOW-ARCHITECTURE §35.4 — filter stays cheap under load."""

    BUDGET_S = 0.1

    def _build_model_with_prim_specs(
        self, count: int
    ) -> tuple[LayerModel, MockLayerStackAdapter]:
        adapter = MockLayerStackAdapter()
        # Seed prim-spec descriptors directly on the mock so the cost of
        # populating the stage is bounded: this test measures filter
        # time, not mock-adapter construction.
        for i in range(count):
            adapter.set_prim_spec_descriptor(
                ROOT_LAYER_IDENTIFIER, f"/spec_{i:05d}"
            )
        model = LayerModel(adapter)
        return model, adapter

    def test_filter_with_10k_prim_specs_under_100ms(self) -> None:
        """``filter_by_text`` on a 10k-prim-spec layer finishes in < 100ms."""
        model, _adapter = self._build_model_with_prim_specs(10_000)
        try:
            # Force the prim-spec cache to populate ahead of the
            # measurement so the filter walk runs over a fully
            # materialised tree — that's the worst case for Step 51's
            # layer-name walk, even though the current implementation
            # only scans ``display_name``.
            root = model._root_item
            assert root is not None
            model._ensure_prim_specs_loaded(root)
            assert len(root._prim_specs) == 10_000

            start = time.perf_counter()
            model.filter_by_text("spec_5000")
            elapsed = time.perf_counter() - start

            assert elapsed < self.BUDGET_S, (
                f"filter_by_text with 10k prim specs took "
                f"{elapsed * 1000:.1f}ms (budget {self.BUDGET_S * 1000:.0f}ms)"
            )
        finally:
            model.destroy()

    def test_repeated_filter_toggles_stay_fast(self) -> None:
        """10 set-then-clear filter toggles over a 10k-spec tree < 500ms total.

        Guards against the scenario where the clear path walks prim
        specs even though the filter itself does not — a regression that
        would quietly quadratic the user's typing latency in the Step 51
        search field.
        """
        model, _adapter = self._build_model_with_prim_specs(10_000)
        try:
            root = model._root_item
            assert root is not None
            model._ensure_prim_specs_loaded(root)

            start = time.perf_counter()
            for i in range(10):
                model.filter_by_text(f"match_{i}")
                model.filter_by_text("")
            elapsed = time.perf_counter() - start

            assert elapsed < 0.5, (
                f"10 filter set/clear cycles over 10k specs took "
                f"{elapsed * 1000:.1f}ms (budget 500ms)"
            )
        finally:
            model.destroy()


# ── 4 · Flatten snapshot memory budget (pxr-gated) ────────────────────────────


@pytest.mark.performance
@pytest.mark.skipif(not _HAS_USD, reason="pxr (OpenUSD) not available")
class TestFlattenSnapshotMemory:
    """LAYERS-PLAN Step 61 — retained snapshot buffer stays bounded on flatten."""

    # Plan target: ≤ 16MB for 15 × 1MB layers.
    MEMORY_BUDGET_BYTES = 16 * 1024 * 1024
    TARGET_LAYER_BYTES = 1 * 1024 * 1024
    LAYER_COUNT = 15

    def test_flatten_15_layers_snapshot_under_16mb(self, tmp_path) -> None:
        """FlattenSublayersCommand's retained buffer ≤ 16MB across 15×1MB."""
        from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter

        from ovwidgets.layers.commands.merge_flatten_commands import (
            FlattenSublayersCommand,
        )

        # Build the root + 15 on-disk sublayers, each padded to ~1MB via
        # a single large ``customLayerData`` string. Using custom data
        # keeps the fill cost O(1) per layer instead of creating
        # thousands of prim specs; the serialised USDA is still ~1MB.
        payload = "x" * self.TARGET_LAYER_BYTES
        root = Sdf.Layer.CreateNew(str(tmp_path / "root.usda"))
        sublayer_paths = []
        for i in range(self.LAYER_COUNT):
            path = str(tmp_path / f"sub_{i:02d}.usda")
            sub = Sdf.Layer.CreateNew(path)
            sub.customLayerData = {"ovgear_perf_payload": payload}
            sub.Save()
            root.subLayerPaths.append(f"sub_{i:02d}.usda")
            sublayer_paths.append(path)
        root.Save()

        stage = Usd.Stage.Open(str(tmp_path / "root.usda"))
        adapter = UsdLayerStackAdapter(stage, UndoManager())
        adapter.get_sublayer_identifiers(adapter.get_root_layer())

        bus = SelectionBus()
        try:
            cmd = FlattenSublayersCommand(
                adapter,
                bus,
                adapter.get_root_layer().identifier,
            )
            cmd.do_impl()

            # Direct retention check — every snapshot holds its USDA
            # content as a ``str`` on the command instance. Summing
            # their byte lengths gives a lower bound on the retained
            # buffer that's tight enough to catch accidental doubling
            # (e.g. if snapshot logic ever kept both content + sublayer
            # blobs twice).
            retained = sys.getsizeof(cmd._parent_snapshot.content)
            for snap in cmd._sublayer_snapshots:
                retained += sys.getsizeof(snap.content)

            assert len(cmd._sublayer_snapshots) == self.LAYER_COUNT
            assert retained <= self.MEMORY_BUDGET_BYTES, (
                f"Retained snapshot buffer = {retained / 1024 / 1024:.2f}MB "
                f"(budget {self.MEMORY_BUDGET_BYTES / 1024 / 1024:.0f}MB)"
            )
        finally:
            # The command + adapter hold stage references; drop ours so
            # pytest tmp_path cleanup succeeds on Windows runners.
            SelectionBus._instance = None
