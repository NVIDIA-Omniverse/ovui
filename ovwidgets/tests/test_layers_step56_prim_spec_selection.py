# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 56 — prim-spec selection → ``SelectionBus``.

Step 55 fans out focused-:class:`LayerItem` changes to listeners.
Step 56 adds the sibling path: every :class:`PrimSpecItem` in the
tree-view selection is mirrored to :class:`~ovwidgets.common.selection.SelectionBus`
under :data:`~ovwidgets.layers.selection_watch.LAYERS_SELECT_SOURCE` so Stage
/ Property windows react to a Layers-panel click exactly like a click
in the Stage tree.

Coverage:

- A single :class:`PrimSpecItem` click publishes one path.
- Multi-select publishes every path in the selection order.
- Mixed ``[LayerItem, PrimSpecItem]`` publishes only the prim-spec
  paths (the layer row is already §24.6 focus-``None`` and has no
  downstream meaning to the bus).
- Layer-only / empty selections do **not** clear the bus — an
  external prim-selection held by Stage / Property survives a Layers
  panel click on a layer row.
- Self-echo elision: if the bus already holds the same ordered tuple
  of paths, no re-publish fires. This is the Step 57 inbound-sync
  feedback-loop guard.
- Reentrancy: a subscriber that is already publishing through the bus
  causes the publish to raise :class:`SelectionBusError`; the watch
  defers the publish through ``call_later(0, ...)`` and lands it on
  the deferred frame. A rapid-click test drives the retry path 10
  times without losing a publish.
- Lifecycle: after :meth:`destroy`, pending retries silently no-op
  because the bus reference is nulled.
- :data:`LAYERS_SELECT_SOURCE` is the namespaced string the plan
  pins (``"ovwidgets.layers:select"``).
- Re-export from :mod:`ovwidgets.layers` — call sites import it by name.
"""

from __future__ import annotations

from typing import Any, Callable, List, Tuple

import pytest
from ovui_data_adapters.common import PrimSpecDescriptor, PrimSpecifier

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.selection import (
    SelectionBus,
    SelectionChangedEvent,
)
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import (
    LAYERS_SELECT_SOURCE,
    DefaultLayerSettings,
    LayerItem,
    LayerModel,
    LayerSelectionWatch,
    LayerWindow,
    PrimSpecItem,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


class _FakeTreeView:
    """Minimal tree-view stand-in — captures
    ``set_selection_changed_fn`` so tests can drive the watch directly."""

    def __init__(self) -> None:
        self.callback: Any = None

    def set_selection_changed_fn(self, fn: Any) -> None:
        self.callback = fn


class _Scheduler:
    """Collects deferred callbacks so tests can run them on demand.

    Mirrors :meth:`Application.call_later`'s shape (delay, callback)
    and is driven manually — the reentrancy-retry path is synchronous
    otherwise, and a real timer would make these tests racy.
    """

    def __init__(self) -> None:
        self.pending: List[Tuple[float, Callable[[], None]]] = []

    def __call__(self, delay: float, callback: Callable[[], None]) -> None:
        self.pending.append((delay, callback))

    def run_all(self) -> None:
        """Fire every queued callback in arrival order; drains the
        queue even if a callback schedules a new one."""
        while self.pending:
            _, cb = self.pending.pop(0)
            cb()


class _App:
    """:class:`Application` stand-in — only the slots the watch and
    :class:`LayerWindow` actually read."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()
        self.scheduler = _Scheduler()

    def call_later(self, delay: float, callback: Callable[[], None]) -> None:
        self.scheduler(delay, callback)


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=False)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_a.usda")
    return ad


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def tree() -> _FakeTreeView:
    return _FakeTreeView()


@pytest.fixture
def model(adapter: MockLayerStackAdapter, app: _App) -> LayerModel:
    m = LayerModel(adapter, services=app, settings=DefaultLayerSettings())
    yield m
    m.destroy()


@pytest.fixture
def window(adapter: MockLayerStackAdapter, app: _App) -> LayerWindow:
    w = LayerWindow(services=app, adapter=adapter, settings=DefaultLayerSettings())
    yield w
    w.destroy()


def _layer_item(model: LayerModel, identifier: str) -> LayerItem:
    stack: List[LayerItem] = list(model.get_item_children(None))
    while stack:
        node = stack.pop()
        if isinstance(node, LayerItem) and node.identifier == identifier:
            return node
        stack.extend(model.get_item_children(node))
    raise KeyError(identifier)


def _make_prim_spec(layer_item: LayerItem, path: str, type_name: str = "") -> PrimSpecItem:
    """Build a standalone :class:`PrimSpecItem` — Step 56 only reads
    :attr:`PrimSpecItem.path`, so a fresh descriptor without hitting
    the adapter is enough."""
    descriptor = PrimSpecDescriptor(
        path=path,
        type_name=type_name,
        specifier=PrimSpecifier.DEF,
        has_reference=False,
        has_payload=False,
        is_instanceable=False,
    )
    return PrimSpecItem(layer_item, descriptor)


class _EventList(list):
    """A :class:`list` subclass that pins a :class:`Subscription`
    reference so :meth:`Subscription.__del__` doesn't cancel mid-test.

    The bus subscription is owned by the :class:`Subscription` handle
    returned by :meth:`SelectionBus.subscribe`; letting it fall out of
    scope triggers :meth:`Subscription.__del__` which removes the
    callback. Holding the handle on the collected-events list keeps
    the lifetime tied to the list — exactly the scope callers want.
    """


def _captured_events(bus: SelectionBus) -> _EventList:
    """Attach a subscriber that records every bus event — the
    Stage/Property stand-in in these tests."""
    events = _EventList()
    events._sub = bus.subscribe(events.append)  # type: ignore[attr-defined]
    return events


# ─── Module-level constant ──────────────────────────────────────────────────


class TestSourceConstant:
    def test_value_is_namespaced(self) -> None:
        """Plan pins the source string to ``"ovwidgets.layers:select"`` —
        pinned so Stage / Viewport can't short-circuit the wrong
        publisher by accident. A rename must be an intentional edit
        to this test and every subscriber."""
        assert LAYERS_SELECT_SOURCE == "ovwidgets.layers:select"

    def test_reexported_from_package(self) -> None:
        """Call sites import the constant from :mod:`ovwidgets.layers` —
        the sub-module path stays stable but the package surface is
        the canonical import site."""
        import ovwidgets.layers
        from ovwidgets.layers.selection_watch import LAYERS_SELECT_SOURCE as module_level

        assert ovwidgets.layers.LAYERS_SELECT_SOURCE is module_level


# ─── Direct publish path ────────────────────────────────────────────────────


class TestPrimSpecPublish:
    def test_single_spec_publishes_one_path(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """One prim-spec click → one publish with one path under the
        Layers namespace."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        events = _captured_events(app.selection_bus)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            spec = _make_prim_spec(root, "/World/Cube")
            tree.callback([spec])
            assert len(events) == 1
            assert events[0].source == LAYERS_SELECT_SOURCE
            assert events[0].snapshot.paths() == ["/World/Cube"]
        finally:
            watch.destroy()

    def test_multi_spec_publishes_all_paths(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """Every prim-spec in the selection publishes — ordered as
        the tree delivered them so subscribers see stable order."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        events = _captured_events(app.selection_bus)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            a = _make_prim_spec(root, "/World/Cube")
            b = _make_prim_spec(root, "/World/Sphere")
            c = _make_prim_spec(root, "/World/Plane")
            tree.callback([a, b, c])
            assert len(events) == 1
            assert events[0].snapshot.paths() == [
                "/World/Cube",
                "/World/Sphere",
                "/World/Plane",
            ]
        finally:
            watch.destroy()

    def test_mixed_selection_publishes_only_prim_specs(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """Plan §24.6 makes the layer row focus-``None`` in mixed
        selections; Step 56 drops the layer and publishes only the
        prim-spec paths so the bus never holds a layer identifier."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        events = _captured_events(app.selection_bus)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            spec = _make_prim_spec(root, "/World/Cube")
            tree.callback([root, spec])
            assert len(events) == 1
            assert events[0].snapshot.paths() == ["/World/Cube"]
        finally:
            watch.destroy()


# ─── Non-publishing cases ───────────────────────────────────────────────────


class TestNonPublishing:
    def test_layer_only_selection_does_not_publish(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """Clicking a layer row must not touch the bus — that would
        wipe any Stage/Property prim selection the user already
        has."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        events = _captured_events(app.selection_bus)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            tree.callback([root])
            assert events == []
        finally:
            watch.destroy()

    def test_empty_selection_does_not_publish(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """Empty selection is not a clear — same reason as
        layer-only. An explicit API caller clears the bus; the
        Layers panel does not."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        events = _captured_events(app.selection_bus)
        try:
            tree.callback([])
            assert events == []
        finally:
            watch.destroy()

    def test_specs_then_layer_keeps_bus_intact(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """Prim-spec click → layer-row click: the prim selection
        published on the first click survives the second. Stage /
        Property continue showing the prim."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            spec = _make_prim_spec(root, "/World/Cube")
            tree.callback([spec])
            tree.callback([root])
            snapshot = app.selection_bus.get_snapshot()
            assert snapshot.paths() == ["/World/Cube"]
            assert snapshot.items[0].source == LAYERS_SELECT_SOURCE
        finally:
            watch.destroy()

    def test_missing_bus_is_tolerated(
        self, tree: _FakeTreeView, model: LayerModel
    ) -> None:
        """Headless fixtures may pass ``selection_bus=None`` — the
        watch must degrade silently. Needed for test harnesses and
        the initial :class:`LayerWindow` build before the full
        :class:`Application` is constructed."""
        watch = LayerSelectionWatch(tree, model, None)  # type: ignore[arg-type]
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            spec = _make_prim_spec(root, "/World/Cube")
            tree.callback([spec])  # must not raise
        finally:
            watch.destroy()


# ─── Elision (Step 57 inbound-sync guard) ───────────────────────────────────


class TestElision:
    def test_same_paths_does_not_republish(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """If the bus already holds the same ordered tuple of paths
        (e.g. Stage just published them and Step 57 synced the tree),
        the watch does not re-publish. Breaks the feedback loop."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        events = _captured_events(app.selection_bus)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            spec = _make_prim_spec(root, "/World/Cube")
            tree.callback([spec])
            tree.callback([spec])
            tree.callback([spec])
            assert len(events) == 1
        finally:
            watch.destroy()

    def test_different_order_republishes(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """Same set, different order → a new publish. Order matters
        to subscribers that render a 'focus' prim as the first path."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        events = _captured_events(app.selection_bus)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            a = _make_prim_spec(root, "/World/Cube")
            b = _make_prim_spec(root, "/World/Sphere")
            tree.callback([a, b])
            tree.callback([b, a])
            assert len(events) == 2
            assert events[0].snapshot.paths() == ["/World/Cube", "/World/Sphere"]
            assert events[1].snapshot.paths() == ["/World/Sphere", "/World/Cube"]
        finally:
            watch.destroy()

    def test_switch_paths_publishes(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        events = _captured_events(app.selection_bus)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            a = _make_prim_spec(root, "/A")
            b = _make_prim_spec(root, "/B")
            tree.callback([a])
            tree.callback([b])
            assert [e.snapshot.paths() for e in events] == [["/A"], ["/B"]]
        finally:
            watch.destroy()

    def test_externally_seeded_bus_elides_first_publish(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """The bus is seeded by an external source (mimicking Step
        57 syncing the tree from Stage). The watch's first forward
        must elide — no double publish, no feedback loop."""
        app.selection_bus.publish(["/World/Cube"], source="stage")
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        events = _captured_events(app.selection_bus)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            spec = _make_prim_spec(root, "/World/Cube")
            tree.callback([spec])
            assert list(events) == []
        finally:
            watch.destroy()


# ─── Reentrancy retry ───────────────────────────────────────────────────────


class TestReentrancy:
    def test_bus_error_schedules_retry(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """A subscriber that re-publishes inside its handler forces
        our own publish to raise :class:`SelectionBusError`. The
        watch must defer the retry through ``call_later`` and land
        the publish on the deferred frame."""
        watch = LayerSelectionWatch(
            tree, model, app.selection_bus, call_later=app.call_later
        )
        # Subscriber that re-enters bus.publish — forces the watch's
        # own publish into the reentrant-error path.
        seen: List[str] = []

        def reentrant_subscriber(event: SelectionChangedEvent) -> None:
            if event.source == "stage":
                # While handling a stage publish, synthesise a
                # Layers-originated forward. Bus is in the
                # _publishing=True state, so our publish will raise.
                root_item = _layer_item(model, ROOT_LAYER_IDENTIFIER)
                spec_item = _make_prim_spec(root_item, "/World/Cube")
                tree.callback([spec_item])
                seen.append("inner")

        sub = app.selection_bus.subscribe(reentrant_subscriber)
        try:
            # Drive an external (stage) publish that triggers the
            # reentrant inner publish through our tree.callback.
            app.selection_bus.publish(["/World/Sphere"], source="stage")
            # Inner subscriber fired but its publish raised — queued
            # a retry via call_later.
            assert seen == ["inner"]
            assert len(app.scheduler.pending) == 1
            # Run the deferred retry: now the bus is idle, publish
            # succeeds.
            app.scheduler.run_all()
            snapshot = app.selection_bus.get_snapshot()
            assert snapshot.paths() == ["/World/Cube"]
            assert snapshot.items[0].source == LAYERS_SELECT_SOURCE
        finally:
            sub.cancel()
            watch.destroy()

    def test_retry_elides_if_bus_already_holds_paths(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """Between scheduling the retry and running it, another
        publisher may have landed the same paths. The retry must
        elide — publishing twice would fire subscribers twice."""
        watch = LayerSelectionWatch(
            tree, model, app.selection_bus, call_later=app.call_later
        )
        try:
            # Manually schedule a deferred publish by feeding paths
            # into the internal helper; simulates the post-error
            # retry state without needing the reentrancy scaffolding.
            watch._publish_prim_paths(["/X"])
            # Now land /X externally; the bus holds it.
            events = _captured_events(app.selection_bus)
            # Re-running the same publish must elide.
            watch._publish_prim_paths(["/X"])
            assert list(events) == []
        finally:
            watch.destroy()

    def test_rapid_clicks_eventually_land(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """Plan's explicit verification — 10 quick clicks through
        the reentrant path all eventually publish (the final state
        is the last click's paths)."""
        watch = LayerSelectionWatch(
            tree, model, app.selection_bus, call_later=app.call_later
        )

        # Build 10 distinct specs so each click changes the desired
        # path and exercises the publish path every time.
        root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
        specs = [_make_prim_spec(root, f"/World/Obj{i}") for i in range(10)]

        # A subscriber that reentrantly forwards the *next* spec as
        # each event lands — this forces every publish through the
        # reentrant-retry path without terminating.
        iter_idx = {"i": 0}

        def reentrant(event: SelectionChangedEvent) -> None:
            if event.source != LAYERS_SELECT_SOURCE:
                return
            idx = iter_idx["i"]
            iter_idx["i"] += 1
            if idx >= 9:
                return
            tree.callback([specs[idx + 1]])

        reentrant_sub = app.selection_bus.subscribe(reentrant)
        try:
            tree.callback([specs[0]])
            # Drain the scheduler queue until quiescent.
            for _ in range(50):
                if not app.scheduler.pending:
                    break
                app.scheduler.run_all()
            else:
                pytest.fail("retry queue did not drain")
            # All 10 specs eventually landed. The final bus state is
            # the last click.
            snapshot = app.selection_bus.get_snapshot()
            assert snapshot.paths() == ["/World/Obj9"]
            assert snapshot.items[0].source == LAYERS_SELECT_SOURCE
        finally:
            reentrant_sub.cancel()
            watch.destroy()

    def test_bus_error_without_scheduler_drops_retry_silently(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """A watch built without ``call_later`` (unit tests, headless
        harnesses) cannot retry — the reentrancy case must not raise
        out of the callback into the tree view."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)

        def reentrant_subscriber(event: SelectionChangedEvent) -> None:
            if event.source == "stage":
                root_item = _layer_item(model, ROOT_LAYER_IDENTIFIER)
                spec_item = _make_prim_spec(root_item, "/World/Cube")
                tree.callback([spec_item])

        sub = app.selection_bus.subscribe(reentrant_subscriber)
        try:
            app.selection_bus.publish(["/World/Sphere"], source="stage")
            # No retry queue, no raise — bus still holds the outer
            # publish's paths; the inner reentrant publish was
            # dropped.
            assert app.selection_bus.get_snapshot().paths() == ["/World/Sphere"]
        finally:
            sub.cancel()
            watch.destroy()


# ─── Lifecycle ──────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_destroy_nulls_bus_so_pending_retry_noops(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """A retry scheduled before destroy must fire safely after —
        the watch's bus reference is null, so ``_publish_prim_paths``
        short-circuits without touching a potentially-torn-down bus."""
        watch = LayerSelectionWatch(
            tree, model, app.selection_bus, call_later=app.call_later
        )
        # Queue a retry manually by poking the helper.
        watch._call_later(0, lambda: watch._publish_prim_paths(["/X"]))  # type: ignore[misc]
        watch.destroy()
        # Drain — no raise, no publish.
        events = _captured_events(app.selection_bus)
        app.scheduler.run_all()
        assert list(events) == []

    def test_destroy_clears_call_later_reference(
        self, tree: _FakeTreeView, model: LayerModel, app: _App
    ) -> None:
        """Releases the scheduler ref so the watch doesn't pin the
        :class:`Application` across destroy."""
        watch = LayerSelectionWatch(
            tree, model, app.selection_bus, call_later=app.call_later
        )
        watch.destroy()
        assert watch._call_later is None


# ─── LayerWindow integration ────────────────────────────────────────────────


class TestWindowIntegration:
    def test_watch_is_constructed_with_call_later(
        self, window: LayerWindow, app: _App
    ) -> None:
        """The window threads :meth:`Application.call_later` into the
        watch so the reentrancy-retry path works in production."""
        window._build_ui()
        watch = window._selection_watch
        assert watch is not None
        assert watch._call_later is not None

    def test_prim_spec_click_publishes_through_window_watch(
        self, window: LayerWindow, app: _App
    ) -> None:
        """End-to-end: a prim-spec item fed through the window's
        tree-view callback publishes under
        :data:`LAYERS_SELECT_SOURCE`. This is the Stage/Property
        reaction path."""
        window._build_ui()
        watch = window._selection_watch
        assert watch is not None
        model = window._model
        assert model is not None
        root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
        spec = _make_prim_spec(root, "/World/Cube")
        events = _captured_events(app.selection_bus)
        watch._on_tree_selection_changed([spec])
        assert len(events) == 1
        assert events[0].source == LAYERS_SELECT_SOURCE
        assert events[0].snapshot.paths() == ["/World/Cube"]

    def test_window_layer_click_does_not_publish(
        self, window: LayerWindow, app: _App
    ) -> None:
        """The Step-55 focus path still works via the window, and
        Step 56 does not leak a bus publish when the selection is a
        pure :class:`LayerItem`."""
        window._build_ui()
        watch = window._selection_watch
        assert watch is not None
        model = window._model
        assert model is not None
        root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
        events = _captured_events(app.selection_bus)
        watch._on_tree_selection_changed([root])
        assert events == []
