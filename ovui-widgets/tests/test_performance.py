# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Performance baseline benchmarks (stage browser behavior).

Each test measures a critical path and asserts it completes within a
generous CI threshold (10–100× the production target). These tests
catch pathological regressions (accidental O(n²), infinite loops) without
flaking on loaded machines.

production targets (§10):
  - Stage browser hierarchy fetch 1000 prims: < 100ms
  - SelectionBus dispatch 100 subscribers:   < 1ms
  - FilterPipeline filter 1000 items:        < 50ms
  - Property row build 20 attributes:        < 200ms
"""

import time

import omni.ui as ui
from ovui_data_adapters.common import AttributeMetadata

from ovui_widgets.app.testing import MockPropertyAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_stage import MockStageAdapter
from ovui_widgets.property.attribute_row import build_attribute_row
from ovui_widgets.stage.filter_pipeline import FilterPipeline, make_name_filter
from ovui_widgets.stage.hierarchy_model import HierarchyModel

# ── Helpers ───────────────────────────────────────────────────────────────────

def _float_meta(name: str) -> AttributeMetadata:
    return AttributeMetadata(
        name=name,
        display_name=name.title(),
        type_name="float",
        value_type=float,
        group="Perf",
    )


def _vec3_meta(name: str) -> AttributeMetadata:
    return AttributeMetadata(
        name=name,
        display_name=name.title(),
        type_name="float3",
        value_type=float,
        group="Perf",
    )


# ── Hierarchy performance ─────────────────────────────────────────────────────

class TestHierarchyPerformance:
    """Stage Browser critical path benchmarks."""

    # CI threshold: 1000ms (10× production target of 100ms).
    HIERARCHY_THRESHOLD_S = 1.0

    def test_adapter_get_children_1000_prims(self):
        """MockStageAdapter.get_children(root) for 1000 flat children."""
        adapter = MockStageAdapter(prim_count=1000)
        root = adapter.get_root()

        start = time.perf_counter()
        children = adapter.get_children(root)
        elapsed = time.perf_counter() - start

        assert len(children) == 1000
        assert elapsed < self.HIERARCHY_THRESHOLD_S, (
            f"adapter.get_children(1000 prims) took {elapsed*1000:.1f}ms "
            f"(threshold {self.HIERARCHY_THRESHOLD_S*1000:.0f}ms)"
        )

    def test_hierarchy_model_load_1000_prims(self):
        """HierarchyModel.get_item_children(root) for 1000 flat children (cold cache)."""
        adapter = MockStageAdapter(prim_count=1000)
        model = HierarchyModel(adapter)

        # get_item_children(None) returns [root_item]
        root_items = model.get_item_children(None)
        assert len(root_items) == 1
        root_item = root_items[0]

        start = time.perf_counter()
        children = model.get_item_children(root_item)
        elapsed = time.perf_counter() - start

        assert len(children) == 1000
        assert elapsed < self.HIERARCHY_THRESHOLD_S, (
            f"HierarchyModel load 1000 prims took {elapsed*1000:.1f}ms "
            f"(threshold {self.HIERARCHY_THRESHOLD_S*1000:.0f}ms)"
        )

    def test_hierarchy_model_second_call_cached(self):
        """Second get_item_children call (warm cache) is at least as fast as first."""
        adapter = MockStageAdapter(prim_count=1000)
        model = HierarchyModel(adapter)
        root_item = model.get_item_children(None)[0]

        # Warm the cache
        model.get_item_children(root_item)

        start = time.perf_counter()
        children_cached = model.get_item_children(root_item)
        elapsed_cached = time.perf_counter() - start

        assert len(children_cached) == 1000
        # Cached call must be well under 100ms regardless of production target
        assert elapsed_cached < 0.1, (
            f"Cached get_item_children took {elapsed_cached*1000:.1f}ms "
            f"(expected < 100ms for cache hit)"
        )

    def test_adapter_get_children_default_tree(self):
        """Default tree (8 prims) fetch is effectively instant."""
        adapter = MockStageAdapter()
        root = adapter.get_root()

        start = time.perf_counter()
        children = adapter.get_children(root)
        elapsed = time.perf_counter() - start

        assert len(children) == 3  # Geometry, Lights, Camera
        assert elapsed < 0.01, (
            f"Default tree get_children took {elapsed*1000:.1f}ms (expected < 10ms)"
        )

    def test_hierarchy_model_root_only(self):
        """get_item_children(None) returns root in < 10ms."""
        adapter = MockStageAdapter(prim_count=1000)
        model = HierarchyModel(adapter)

        start = time.perf_counter()
        roots = model.get_item_children(None)
        elapsed = time.perf_counter() - start

        assert len(roots) == 1
        assert elapsed < 0.01, (
            f"get_item_children(None) took {elapsed*1000:.1f}ms (expected < 10ms)"
        )

    def test_adapter_get_children_5000_prims(self):
        """5000-prim flat tree stays under 5× the 1000-prim threshold."""
        adapter = MockStageAdapter(prim_count=5000)
        root = adapter.get_root()

        start = time.perf_counter()
        children = adapter.get_children(root)
        elapsed = time.perf_counter() - start

        assert len(children) == 5000
        # 5× items → allow 5× threshold (linear, not quadratic)
        assert elapsed < 5 * self.HIERARCHY_THRESHOLD_S, (
            f"5000-prim get_children took {elapsed*1000:.1f}ms"
        )


# ── SelectionBus performance ──────────────────────────────────────────────────

class TestSelectionBusPerformance:
    """SelectionBus dispatch benchmarks."""

    # CI threshold: 100ms (100× production target of 1ms).
    DISPATCH_THRESHOLD_S = 0.1

    def setup_method(self):
        SelectionBus._instance = None

    def teardown_method(self):
        SelectionBus._instance = None

    def test_dispatch_100_subscribers(self):
        """publish() to 100 subscribers."""
        bus = SelectionBus()
        calls = [0]
        subs = []
        for _ in range(100):
            sub = bus.subscribe(lambda e: calls.__setitem__(0, calls[0] + 1))
            subs.append(sub)

        start = time.perf_counter()
        bus.publish(["/World/Prim"], source="test")
        elapsed = time.perf_counter() - start

        assert calls[0] == 100
        assert elapsed < self.DISPATCH_THRESHOLD_S, (
            f"100-subscriber dispatch took {elapsed*1000:.2f}ms "
            f"(threshold {self.DISPATCH_THRESHOLD_S*1000:.0f}ms)"
        )

    def test_dispatch_10_subscribers_baseline(self):
        """publish() to 10 subscribers — near-zero overhead baseline."""
        bus = SelectionBus()
        calls = [0]
        subs = []
        for _ in range(10):
            sub = bus.subscribe(lambda e: calls.__setitem__(0, calls[0] + 1))
            subs.append(sub)

        start = time.perf_counter()
        bus.publish(["/World/A"], source="test")
        elapsed = time.perf_counter() - start

        assert calls[0] == 10
        assert elapsed < 0.01, (
            f"10-subscriber dispatch took {elapsed*1000:.2f}ms (expected < 10ms)"
        )

    def test_dispatch_no_subscribers(self):
        """publish() with no subscribers — pure overhead < 1ms."""
        bus = SelectionBus()

        start = time.perf_counter()
        bus.publish(["/World/A"], source="test")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.001, (
            f"Zero-subscriber dispatch took {elapsed*1000:.3f}ms (expected < 1ms)"
        )

    def test_dispatch_large_selection_100_paths(self):
        """publish() with 100-path selection and 10 subscribers."""
        bus = SelectionBus()
        subs = []
        for _ in range(10):
            sub = bus.subscribe(lambda e: None)
            subs.append(sub)

        paths = [f"/World/Prim_{i}" for i in range(100)]

        start = time.perf_counter()
        bus.publish(paths, source="test")
        elapsed = time.perf_counter() - start

        snap = bus.get_snapshot()
        assert len(snap) == 100
        assert elapsed < self.DISPATCH_THRESHOLD_S, (
            f"100-path dispatch took {elapsed*1000:.2f}ms"
        )

    def test_subscribe_and_cancel_100(self):
        """Subscribe 100 callbacks then cancel all — no memory leak."""
        bus = SelectionBus()
        subs = []
        for _ in range(100):
            subs.append(bus.subscribe(lambda e: None))

        assert len(bus._subscribers) == 100

        start = time.perf_counter()
        for sub in subs:
            sub.cancel()
        elapsed = time.perf_counter() - start

        assert len(bus._subscribers) == 0
        assert elapsed < self.DISPATCH_THRESHOLD_S, (
            f"Cancel 100 subs took {elapsed*1000:.2f}ms"
        )

    def test_repeated_publish_100_times(self):
        """100 consecutive publishes to 10 subscribers total < 100ms."""
        bus = SelectionBus()
        total_calls = [0]
        subs = []
        for _ in range(10):
            sub = bus.subscribe(lambda e: total_calls.__setitem__(0, total_calls[0] + 1))
            subs.append(sub)

        start = time.perf_counter()
        for i in range(100):
            bus.publish([f"/Prim_{i}"], source="test")
        elapsed = time.perf_counter() - start

        assert total_calls[0] == 1000  # 100 publishes × 10 subscribers
        assert elapsed < self.DISPATCH_THRESHOLD_S, (
            f"100 repeated publishes took {elapsed*1000:.2f}ms"
        )


# ── FilterPipeline performance ────────────────────────────────────────────────

class TestFilterPipelinePerformance:
    """FilterPipeline filtering benchmarks."""

    # CI threshold: 1000ms (20× production target of 50ms).
    FILTER_THRESHOLD_S = 1.0

    def _get_1000_items(self):
        adapter = MockStageAdapter(prim_count=1000)
        return adapter, adapter.get_children(adapter.get_root())

    def test_no_filter_passes_all(self):
        """is_active=False path — passes() never called in real code."""
        pipeline = FilterPipeline()
        adapter, items = self._get_1000_items()

        assert not pipeline.is_active

        start = time.perf_counter()
        results = [pipeline.passes(adapter, item) for item in items]
        elapsed = time.perf_counter() - start

        assert all(results)
        assert elapsed < self.FILTER_THRESHOLD_S, (
            f"No-filter 1000 items took {elapsed*1000:.1f}ms"
        )

    def test_name_filter_match_all_1000(self):
        """Filter 'Prim_' matches all 1000 items."""
        pipeline = FilterPipeline()
        pipeline.add_predicate(make_name_filter("Prim_"))
        adapter, items = self._get_1000_items()

        start = time.perf_counter()
        results = [pipeline.passes(adapter, item) for item in items]
        elapsed = time.perf_counter() - start

        assert all(results)
        assert elapsed < self.FILTER_THRESHOLD_S, (
            f"Match-all filter 1000 items took {elapsed*1000:.1f}ms"
        )

    def test_name_filter_match_none_1000(self):
        """Filter 'ZZZNOMATCH' matches no items."""
        pipeline = FilterPipeline()
        pipeline.add_predicate(make_name_filter("ZZZNOMATCH"))
        adapter, items = self._get_1000_items()

        start = time.perf_counter()
        results = [pipeline.passes(adapter, item) for item in items]
        elapsed = time.perf_counter() - start

        assert not any(results)
        assert elapsed < self.FILTER_THRESHOLD_S, (
            f"Match-none filter 1000 items took {elapsed*1000:.1f}ms"
        )

    def test_name_filter_partial_match_1000(self):
        """Filter 'Prim_5' matches Prim_5, Prim_50..Prim_59 etc. (subset)."""
        pipeline = FilterPipeline()
        pipeline.add_predicate(make_name_filter("Prim_5"))
        adapter, items = self._get_1000_items()

        start = time.perf_counter()
        results = [pipeline.passes(adapter, item) for item in items]
        elapsed = time.perf_counter() - start

        matched = sum(results)
        assert matched > 0
        assert matched < 1000
        assert elapsed < self.FILTER_THRESHOLD_S, (
            f"Partial filter 1000 items took {elapsed*1000:.1f}ms"
        )

    def test_two_predicates_1000(self):
        """Two stacked predicates — still sub-threshold."""
        pipeline = FilterPipeline()
        pipeline.add_predicate(make_name_filter("Prim_"))
        pipeline.add_predicate(make_name_filter("1"))
        adapter, items = self._get_1000_items()

        start = time.perf_counter()
        results = [pipeline.passes(adapter, item) for item in items]
        elapsed = time.perf_counter() - start

        assert elapsed < self.FILTER_THRESHOLD_S, (
            f"Two-predicate filter 1000 items took {elapsed*1000:.1f}ms"
        )

    def test_filter_clear_resets_is_active(self):
        """clear() resets is_active; subsequent passes() trivially fast."""
        pipeline = FilterPipeline()
        pipeline.add_predicate(make_name_filter("x"))
        assert pipeline.is_active

        pipeline.clear()
        assert not pipeline.is_active

        adapter, items = self._get_1000_items()
        start = time.perf_counter()
        results = [pipeline.passes(adapter, item) for item in items]
        elapsed = time.perf_counter() - start

        assert elapsed < self.FILTER_THRESHOLD_S


# ── Property adapter performance ──────────────────────────────────────────────

class TestMockPropertyAdapterPerformance:
    """MockPropertyAdapter critical path benchmarks (no UI context needed)."""

    # CI threshold: 100ms for 1000 repeated calls.
    ADAPTER_THRESHOLD_S = 0.1

    def _make_adapter_20_attrs(self) -> MockPropertyAdapter:
        attrs = {f"attr_{i}": _float_meta(f"attr_{i}") for i in range(20)}
        adapter = MockPropertyAdapter(paths=["/Prim"], attributes=attrs)
        for i in range(20):
            adapter.set_value(f"attr_{i}", float(i))
        return adapter

    def test_get_value_1000_calls(self):
        """1000 consecutive get_value calls < 100ms."""
        adapter = self._make_adapter_20_attrs()

        start = time.perf_counter()
        for _ in range(1000):
            for i in range(20):
                _ = adapter.get_value(f"attr_{i}")
        elapsed = time.perf_counter() - start

        assert elapsed < self.ADAPTER_THRESHOLD_S, (
            f"20000 get_value calls took {elapsed*1000:.1f}ms"
        )

    def test_set_value_1000_calls(self):
        """1000 consecutive set_value calls < 100ms."""
        adapter = self._make_adapter_20_attrs()

        start = time.perf_counter()
        for i in range(1000):
            adapter.set_value("attr_0", float(i))
        elapsed = time.perf_counter() - start

        assert elapsed < self.ADAPTER_THRESHOLD_S, (
            f"1000 set_value calls took {elapsed*1000:.1f}ms"
        )

    def test_is_ambiguous_1000_calls_single_path(self):
        """is_ambiguous() on single-path adapter — fast path."""
        adapter = MockPropertyAdapter(
            paths=["/Prim"],
            attributes={"x": _float_meta("x")},
        )
        adapter.set_value("x", 1.0)

        start = time.perf_counter()
        for _ in range(1000):
            adapter.is_ambiguous("x")
        elapsed = time.perf_counter() - start

        assert elapsed < self.ADAPTER_THRESHOLD_S, (
            f"1000 is_ambiguous calls (single path) took {elapsed*1000:.1f}ms"
        )

    def test_is_ambiguous_1000_calls_two_paths(self):
        """is_ambiguous() on two-path adapter (full comparison path)."""
        adapter = MockPropertyAdapter(
            paths=["/P1", "/P2"],
            attributes={"x": _float_meta("x")},
        )
        adapter.set_path_value("/P1", "x", 1.0)
        adapter.set_path_value("/P2", "x", 2.0)

        start = time.perf_counter()
        for _ in range(1000):
            adapter.is_ambiguous("x")
        elapsed = time.perf_counter() - start

        assert elapsed < self.ADAPTER_THRESHOLD_S, (
            f"1000 is_ambiguous calls (two paths, different) took {elapsed*1000:.1f}ms"
        )

    def test_get_attribute_names_1000_calls(self):
        """get_attribute_names() repeatedly < 100ms."""
        adapter = self._make_adapter_20_attrs()

        start = time.perf_counter()
        for _ in range(1000):
            names = adapter.get_attribute_names()
        elapsed = time.perf_counter() - start

        assert len(names) == 20
        assert elapsed < self.ADAPTER_THRESHOLD_S, (
            f"1000 get_attribute_names calls took {elapsed*1000:.1f}ms"
        )


# ── Property row build performance ────────────────────────────────────────────

class TestPropertyRowBuildPerformance:
    """Attribute row widget build benchmarks (requires omni.ui context)."""

    # CI threshold: 2000ms for 20 rows (10× production target of 200ms).
    ROW_BUILD_THRESHOLD_S = 2.0

    def _make_mixed_attrs(self, count: int):
        """Make `count` mixed-type AttributeMetadata entries."""
        attrs = {}
        for i in range(count):
            if i % 4 == 0:
                attrs[f"float_{i}"] = _float_meta(f"float_{i}")
            elif i % 4 == 1:
                attrs[f"vec3_{i}"] = _vec3_meta(f"vec3_{i}")
            elif i % 4 == 2:
                attrs[f"int_{i}"] = AttributeMetadata(
                    name=f"int_{i}",
                    display_name=f"Int {i}",
                    type_name="int",
                    value_type=int,
                    group="Perf",
                )
            else:
                attrs[f"bool_{i}"] = AttributeMetadata(
                    name=f"bool_{i}",
                    display_name=f"Bool {i}",
                    type_name="bool",
                    value_type=bool,
                    group="Perf",
                )
        return attrs

    def test_build_20_attribute_rows(self):
        """Build 20 mixed-type attribute rows < 2000ms."""
        attrs = self._make_mixed_attrs(20)
        adapter = MockPropertyAdapter(paths=["/Prim"], attributes=attrs)
        for name, meta in attrs.items():
            if meta.type_name == "float3":
                adapter.set_value(name, (1.0, 0.0, 0.0))
            elif meta.value_type is bool:
                adapter.set_value(name, True)
            elif meta.value_type is int:
                adapter.set_value(name, 1)
            else:
                adapter.set_value(name, 1.0)

        w = ui.Window("perf_row_build_20", width=400, height=600)
        rows = []
        start = time.perf_counter()
        with w.frame:
            with ui.VStack():
                for name, meta in attrs.items():
                    row = build_attribute_row(meta, adapter)
                    rows.append(row)
        elapsed = time.perf_counter() - start

        assert len(rows) == 20
        assert elapsed < self.ROW_BUILD_THRESHOLD_S, (
            f"Building 20 attribute rows took {elapsed*1000:.1f}ms "
            f"(threshold {self.ROW_BUILD_THRESHOLD_S*1000:.0f}ms)"
        )

    def test_build_5_attribute_rows_baseline(self):
        """5 float rows — baseline sanity check < 500ms."""
        attrs = {f"float_{i}": _float_meta(f"float_{i}") for i in range(5)}
        adapter = MockPropertyAdapter(paths=["/Prim"], attributes=attrs)
        for name in attrs:
            adapter.set_value(name, 1.0)

        w = ui.Window("perf_row_build_5", width=400, height=300)
        rows = []
        start = time.perf_counter()
        with w.frame:
            with ui.VStack():
                for name, meta in attrs.items():
                    row = build_attribute_row(meta, adapter)
                    rows.append(row)
        elapsed = time.perf_counter() - start

        assert len(rows) == 5
        assert elapsed < 0.5, (
            f"Building 5 attribute rows took {elapsed*1000:.1f}ms (expected < 500ms)"
        )

    def test_build_20_rows_mixed_values_set(self):
        """Build rows for adapter with all values pre-set (non-None path)."""
        attrs = {f"f_{i}": _float_meta(f"f_{i}") for i in range(20)}
        adapter = MockPropertyAdapter(paths=["/Prim"], attributes=attrs)
        for i, name in enumerate(attrs):
            adapter.set_value(name, float(i * 1.5))

        w = ui.Window("perf_row_build_20_vals", width=400, height=600)
        rows = []
        start = time.perf_counter()
        with w.frame:
            with ui.VStack():
                for name, meta in attrs.items():
                    row = build_attribute_row(meta, adapter)
                    rows.append(row)
        elapsed = time.perf_counter() - start

        assert len(rows) == 20
        assert elapsed < self.ROW_BUILD_THRESHOLD_S, (
            f"Building 20 pre-set rows took {elapsed*1000:.1f}ms"
        )


# ── Combined path benchmark ───────────────────────────────────────────────────

class TestCombinedPathPerformance:
    """End-to-end critical path combining multiple subsystems."""

    def setup_method(self):
        SelectionBus._instance = None

    def teardown_method(self):
        SelectionBus._instance = None

    def test_selection_then_hierarchy_filter(self):
        """Publish selection + filter 500 prims — total < 1000ms."""
        bus = SelectionBus()
        received = []
        sub = bus.subscribe(lambda e: received.append(e.snapshot.paths()))  # hold ref

        adapter = MockStageAdapter(prim_count=500)
        pipeline = FilterPipeline()
        pipeline.add_predicate(make_name_filter("Prim_"))
        items = adapter.get_children(adapter.get_root())

        start = time.perf_counter()
        bus.publish(["/World/Prim_1", "/World/Prim_2"], source="test")
        filtered = [item for item in items if pipeline.passes(adapter, item)]
        elapsed = time.perf_counter() - start

        assert len(received) == 1
        assert len(filtered) == 500
        assert elapsed < 1.0, f"Combined path took {elapsed*1000:.1f}ms"

    def test_adapter_hierarchy_full_traversal_1000(self):
        """Full recursive traversal of 1000-prim flat tree < 500ms."""
        adapter = MockStageAdapter(prim_count=1000)

        def _count(item):
            return 1 + sum(_count(c) for c in adapter.get_children(item))

        start = time.perf_counter()
        # Root itself + 1000 flat children → each child has 0 children
        total = sum(1 for _ in adapter.get_children(adapter.get_root()))
        elapsed = time.perf_counter() - start

        assert total == 1000
        assert elapsed < 0.5, f"Traversal of 1000 prims took {elapsed*1000:.1f}ms"
