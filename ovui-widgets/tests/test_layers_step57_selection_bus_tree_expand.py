# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 57 — ``SelectionBus`` → tree expand.

Step 57 closes the selection loop started in Step 56: when
:class:`~ovui_widgets.common.selection.SelectionBus` publishes a new selection
from an *external* source (a Stage-window prim click, a
Viewport lasso, a Property-panel focus change), the Layers window
answers by expanding the edit-target layer's row + every ancestor
prim-spec row, and selecting the matching :class:`PrimSpecItem`
rows in the tree view.

Coverage:

- External bus event → tree selection lands on the matching specs.
- External bus event → every ancestor row (layer + intermediate
  prim specs) is expanded so the selection is visible.
- Self-originated sources (:data:`LAYERS_SELECT_SOURCE`,
  :data:`LAYERS_UNDO_SOURCE`, :data:`LAYERS_COMMAND_SOURCE`) are
  dropped — no expand, no selection write, no feedback loop.
- A path the edit-target layer does not carry is skipped silently;
  peers on the same event still land in the selection.
- Multi-path events select every resolved spec in the tree.
- Empty edit-target identifier is tolerated (initial state / stage
  between loads) — the event drops through.
- The subscription is cancelled on :meth:`destroy` so a post-destroy
  bus publish cannot touch the watch.
- :data:`LAYERS_OWN_SOURCES` is the re-exported frozenset the
  subscriber boundary pins for its short-circuit check.

Feedback-loop guard:

- While :meth:`_on_bus_event` is applying the inbound selection,
  the tree view's own selection-changed callback (which Step 56
  uses to publish) is a no-op. A partial-match selection (the
  edit-target layer resolves only some of the bus paths) would
  otherwise silently narrow the Stage selection. The flag restores
  after the write so a subsequent user click still forwards.
"""

from __future__ import annotations

from typing import Any, List

import pytest
from ovui_data_adapters.common import PrimSpecDescriptor, PrimSpecifier

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus, SelectionChangedEvent
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import (
    LAYERS_SELECT_SOURCE,
    DefaultLayerSettings,
    LayerItem,
    LayerModel,
    LayerSelectionWatch,
    LayerWindow,
    PrimSpecItem,
)
from ovui_widgets.layers.commands.base import LAYERS_COMMAND_SOURCE, LAYERS_UNDO_SOURCE
from ovui_widgets.layers.selection_watch import LAYERS_OWN_SOURCES

# ─── Fixtures ────────────────────────────────────────────────────────────────


class _FakeTreeView:
    """Minimal tree-view stand-in that records ``set_expanded`` calls
    and stores the last ``selection`` write, so tests can assert on
    both the ancestor expansion and the final selection state.
    """

    def __init__(self) -> None:
        self.callback: Any = None
        self.selection: List[Any] = []
        self.expanded: List[tuple] = []

    def set_selection_changed_fn(self, fn: Any) -> None:
        self.callback = fn

    def set_expanded(self, item: Any, expanded: bool, recursive: bool) -> None:
        self.expanded.append((item, expanded, recursive))


class _App:
    """:class:`Application` stand-in — only the slots the watch reads."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=False)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_a.usda")
    # Seed a three-level prim-spec tree on the root layer:
    #   /World
    #     /World/Set
    #       /World/Set/Hero
    #     /World/Cube
    ad.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/World")
    ad.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/World/Set")
    ad.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/World/Set/Hero")
    ad.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/World/Cube")
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


def _layer_item(model: LayerModel, identifier: str) -> LayerItem:
    stack: List[LayerItem] = list(model.get_item_children(None))
    while stack:
        node = stack.pop()
        if isinstance(node, LayerItem) and node.identifier == identifier:
            return node
        stack.extend(model.get_item_children(node))
    raise KeyError(identifier)


# ─── Module-level constants ──────────────────────────────────────────────────


class TestOwnSources:
    def test_constant_contains_namespaces(self) -> None:
        """Every Layers-owned source must be in the short-circuit
        set. Adding a new namespaced source (e.g. a future
        ``ovui_widgets.layers:paste``) needs an intentional edit here and in
        :mod:`ovui_widgets.layers.selection_watch`."""
        assert LAYERS_SELECT_SOURCE in LAYERS_OWN_SOURCES
        assert LAYERS_UNDO_SOURCE in LAYERS_OWN_SOURCES
        assert LAYERS_COMMAND_SOURCE in LAYERS_OWN_SOURCES

    def test_is_frozenset(self) -> None:
        """Immutable so an accidental ``.add(...)`` at a call site
        cannot silently reshape the short-circuit set."""
        assert isinstance(LAYERS_OWN_SOURCES, frozenset)


# ─── LayerModel.find_prim_spec ───────────────────────────────────────────────


class TestFindPrimSpec:
    def test_top_level_spec(self, model: LayerModel) -> None:
        """A root-level prim spec resolves to the matching
        :class:`PrimSpecItem` on the layer's lazy cache."""
        root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
        spec = model.find_prim_spec(root, "/World")
        assert spec is not None
        assert spec.path == "/World"

    def test_nested_spec_loads_children(self, model: LayerModel) -> None:
        """A deep path walks the cache down one hop at a time —
        ``/World/Set/Hero`` forces ``/World`` and ``/World/Set`` to
        materialise children lazily on the way down."""
        root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
        spec = model.find_prim_spec(root, "/World/Set/Hero")
        assert spec is not None
        assert spec.path == "/World/Set/Hero"

    def test_missing_spec_returns_none(self, model: LayerModel) -> None:
        """A spec not authored on the layer returns ``None`` — USD
        composition lets a prim exist in stage without a spec on
        every layer, so "not here" is the expected case, not an
        error."""
        root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
        assert model.find_prim_spec(root, "/World/Missing") is None

    def test_missing_intermediate_returns_none(self, model: LayerModel) -> None:
        """Walking through a parent that doesn't exist quits early
        without exhausting the adapter."""
        root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
        assert model.find_prim_spec(root, "/Nowhere/Deep/Path") is None

    def test_pseudo_root_returns_none(self, model: LayerModel) -> None:
        """The tree does not render ``/`` as its own prim-spec row —
        callers that receive a pseudo-root path from the bus get
        ``None`` and the caller treats it as "nothing to expand"."""
        root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
        assert model.find_prim_spec(root, "/") is None
        assert model.find_prim_spec(root, "") is None

    def test_find_items_returns_clones(self, model: LayerModel) -> None:
        """A layer reachable through multiple parents appears in the
        sublayer cache multiple times; :meth:`_find_items` returns
        every instance so Step 57's edit-target resolver can pick a
        canonical one."""
        items = model._find_items(ROOT_LAYER_IDENTIFIER)
        assert len(items) >= 1
        assert all(i.identifier == ROOT_LAYER_IDENTIFIER for i in items)

    def test_find_items_unknown_identifier(self, model: LayerModel) -> None:
        assert model._find_items("./does_not_exist.usda") == []


# ─── Inbound bus event → tree selection ──────────────────────────────────────


class TestInboundSelection:
    def test_single_external_path_selects_spec(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """The canonical Step 57 flow: Stage publishes a prim path,
        the watch resolves it to the edit-target layer's spec and
        writes it into the tree-view selection."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            app.selection_bus.publish(["/World/Cube"], source="stage")
            assert len(tree.selection) == 1
            assert isinstance(tree.selection[0], PrimSpecItem)
            assert tree.selection[0].path == "/World/Cube"
        finally:
            watch.destroy()

    def test_multi_path_selects_every_resolved_spec(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """Every path that resolves lands in the tree selection —
        multi-prim selections from Stage round-trip into a multi-row
        Layers selection."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            app.selection_bus.publish(
                ["/World/Cube", "/World/Set"],
                source="stage",
            )
            paths = [s.path for s in tree.selection]
            assert paths == ["/World/Cube", "/World/Set"]
        finally:
            watch.destroy()

    def test_missing_path_is_skipped(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """A path the edit-target layer lacks is silently dropped —
        the peer paths on the same event still land."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            app.selection_bus.publish(
                ["/World/Cube", "/Nowhere", "/World/Set"],
                source="stage",
            )
            paths = [s.path for s in tree.selection]
            assert paths == ["/World/Cube", "/World/Set"]
        finally:
            watch.destroy()

    def test_all_missing_clears_selection(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """Every path missed — the tree selection is still written
        (as an empty list) so stale highlights from a prior external
        publish clear in lockstep."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            # Seed a selection so the write is visible.
            tree.selection = ["stale"]
            app.selection_bus.publish(["/Nowhere"], source="stage")
            assert tree.selection == []
        finally:
            watch.destroy()


# ─── Ancestor expansion ──────────────────────────────────────────────────────


class TestAncestorExpansion:
    def test_deep_spec_expands_every_ancestor(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """``/World/Set/Hero`` → expand ``/World/Set`` (prim-spec
        parent), ``/World`` (prim-spec grandparent), and the owning
        :class:`LayerItem` so every collapsed chevron on the path to
        the target opens before the selection write."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            app.selection_bus.publish(["/World/Set/Hero"], source="stage")
            expanded_items = [call[0] for call in tree.expanded]
            # Every call is ``(item, True, False)`` — the watch never
            # recursively expands, which would over-fan a large
            # layer subtree.
            for _, expanded, recursive in tree.expanded:
                assert expanded is True
                assert recursive is False
            # Ancestors include both prim-spec rows and the layer
            # row; their paths / identifiers should all appear.
            prim_paths = {
                getattr(i, "path", None) for i in expanded_items if hasattr(i, "path")
            }
            assert "/World" in prim_paths
            assert "/World/Set" in prim_paths
            layer_ids = {
                getattr(i, "identifier", None)
                for i in expanded_items
                if hasattr(i, "identifier")
            }
            assert ROOT_LAYER_IDENTIFIER in layer_ids
        finally:
            watch.destroy()

    def test_top_level_spec_expands_only_layer(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """A root-level spec (``/World``) has no prim-spec ancestors,
        just the owning :class:`LayerItem`."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            app.selection_bus.publish(["/World"], source="stage")
            layer_ids = {
                getattr(i, "identifier", None)
                for i, _, _ in tree.expanded
                if hasattr(i, "identifier")
            }
            assert ROOT_LAYER_IDENTIFIER in layer_ids
        finally:
            watch.destroy()

    def test_set_expanded_failure_is_tolerated(
        self,
        model: LayerModel,
        app: _App,
    ) -> None:
        """A torn-down tree view may reject ``set_expanded`` —
        the ancestor walk must continue so other ancestors still
        flip open, and the selection write still fires."""

        class _FlakyTree:
            def __init__(self) -> None:
                self.callback: Any = None
                self.selection: List[Any] = []

            def set_selection_changed_fn(self, fn: Any) -> None:
                self.callback = fn

            def set_expanded(self, *_: Any) -> None:
                raise RuntimeError("tree dead")

        tv = _FlakyTree()
        watch = LayerSelectionWatch(tv, model, app.selection_bus)
        try:
            app.selection_bus.publish(["/World/Cube"], source="stage")
            assert [s.path for s in tv.selection] == ["/World/Cube"]
        finally:
            watch.destroy()


# ─── Source short-circuits ───────────────────────────────────────────────────


class TestOwnSourceShortCircuit:
    @pytest.mark.parametrize(
        "source",
        [LAYERS_SELECT_SOURCE, LAYERS_UNDO_SOURCE, LAYERS_COMMAND_SOURCE],
    )
    def test_own_source_does_not_touch_tree(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
        source: str,
    ) -> None:
        """Self-originated sources (forwarder, undo, command) must
        not drive the inbound sync — the tree keeps whatever it
        had."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            tree.selection = ["preserved"]
            app.selection_bus.publish(["/World/Cube"], source=source)
            assert tree.selection == ["preserved"]
            assert tree.expanded == []
        finally:
            watch.destroy()


# ─── Feedback loop guard ─────────────────────────────────────────────────────


class TestFeedbackLoopGuard:
    def test_inbound_partial_match_does_not_republish(
        self,
        model: LayerModel,
        app: _App,
    ) -> None:
        """Partial match: bus carries two paths, only one resolves on
        the edit-target layer. When the watch writes the narrowed
        list into ``tree.selection``, a real :class:`ui.TreeView`
        fires its ``selection_changed`` callback synchronously —
        that fan-out is Step 56's forwarder, which would otherwise
        publish the partial list back to the bus. The guard blocks
        the re-publish so the bus is not silently narrowed."""

        class _ReentrantTree:
            """Tree stand-in that fires ``callback`` from the
            selection setter — mirrors how a live ``ui.TreeView``
            behaves."""

            def __init__(self) -> None:
                self.callback: Any = None
                self._selection: List[Any] = []

            def set_selection_changed_fn(self, fn: Any) -> None:
                self.callback = fn

            def set_expanded(self, *_: Any) -> None:
                return

            @property
            def selection(self) -> List[Any]:
                return list(self._selection)

            @selection.setter
            def selection(self, value: List[Any]) -> None:
                self._selection = list(value)
                if self.callback is not None:
                    self.callback(list(self._selection))

        tree = _ReentrantTree()
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        events: List[SelectionChangedEvent] = []
        sub = app.selection_bus.subscribe(events.append)
        try:
            app.selection_bus.publish(
                ["/World/Cube", "/Nowhere"],
                source="stage",
            )
            # Only the original "stage" publish — no
            # LAYERS_SELECT_SOURCE re-publish from the forwarder.
            sources = [e.source for e in events]
            assert LAYERS_SELECT_SOURCE not in sources
            # Bus still holds both original paths.
            assert app.selection_bus.get_snapshot().paths() == [
                "/World/Cube",
                "/Nowhere",
            ]
            # The narrowed selection did land in the tree (the
            # resolved spec is selected; ``/Nowhere`` is skipped).
            assert [s.path for s in tree._selection] == ["/World/Cube"]
        finally:
            sub.cancel()
            watch.destroy()

    def test_flag_resets_after_bus_event(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """The guard restores so a later user click still forwards."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            app.selection_bus.publish(["/World/Cube"], source="stage")
            assert watch._applying_bus_event is False
            # A later user click on a prim spec still publishes.
            descriptor = PrimSpecDescriptor(
                path="/World/Set",
                type_name="",
                specifier=PrimSpecifier.DEF,
                has_reference=False,
                has_payload=False,
                is_instanceable=False,
            )
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            spec = PrimSpecItem(root, descriptor)
            tree.callback([spec])
            assert app.selection_bus.get_snapshot().paths() == ["/World/Set"]
            assert (
                app.selection_bus.get_snapshot().items[0].source
                == LAYERS_SELECT_SOURCE
            )
        finally:
            watch.destroy()


# ─── Defensive cases ─────────────────────────────────────────────────────────


class TestDefensive:
    def test_empty_edit_target_drops_event(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """Before an adapter is attached the model holds an empty
        edit-target identifier; the bus event must drop silently
        rather than walk an empty sublayer cache."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            model._edit_target_identifier = ""
            tree.selection = ["preserved"]
            app.selection_bus.publish(["/World/Cube"], source="stage")
            assert tree.selection == ["preserved"]
        finally:
            watch.destroy()

    def test_unknown_edit_target_drops_event(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """An edit-target identifier that no :class:`LayerItem`
        wraps (e.g. a stale id from a retargeting race) is dropped
        — finding "no layer items" is a hard exit, not a fall-back
        to a random layer."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            model._edit_target_identifier = "./ghost.usda"
            app.selection_bus.publish(["/World/Cube"], source="stage")
            assert tree.selection == []
            assert tree.expanded == []
        finally:
            watch.destroy()

    def test_missing_tree_view_drops_event(
        self,
        model: LayerModel,
        app: _App,
    ) -> None:
        """A ``None`` tree view (unit-test harness built without
        standing one up) must not raise from the bus subscriber."""
        watch = LayerSelectionWatch(None, model, app.selection_bus)
        try:
            # Must not raise.
            app.selection_bus.publish(["/World/Cube"], source="stage")
        finally:
            watch.destroy()

    def test_missing_bus_is_tolerated(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
    ) -> None:
        """Headless construction with ``selection_bus=None`` — no
        subscription, no crash."""
        watch = LayerSelectionWatch(tree, model, None)  # type: ignore[arg-type]
        try:
            assert watch._bus_sub is None
        finally:
            watch.destroy()


# ─── Lifecycle ───────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_destroy_cancels_bus_subscription(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """After :meth:`destroy`, a publish cannot touch the torn-down
        watch's tree view. Matches the plan's Step 55a verification
        (``test_destroy_cancels_sub``): the hide→show cycle needs the
        subscription to drop in lockstep with the tree-view callback."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        watch.destroy()
        assert watch._bus_sub is None
        tree.selection = []
        tree.expanded = []
        app.selection_bus.publish(["/World/Cube"], source="stage")
        assert tree.selection == []
        assert tree.expanded == []

    def test_destroy_idempotent_with_subscription(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        watch.destroy()
        watch.destroy()  # must not raise


# ─── LayerWindow integration ─────────────────────────────────────────────────


@pytest.fixture
def window_app() -> _App:
    return _App()


@pytest.fixture
def window_adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=False)
    ad.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/World")
    ad.set_prim_spec_descriptor(ROOT_LAYER_IDENTIFIER, "/World/Cube")
    return ad


@pytest.fixture
def window(
    window_adapter: MockLayerStackAdapter, window_app: _App
) -> LayerWindow:
    w = LayerWindow(
        services=window_app,
        adapter=window_adapter,
        settings=DefaultLayerSettings(),
    )
    yield w
    w.destroy()


class TestWindowIntegration:
    def test_window_watch_subscribes_to_bus(
        self, window: LayerWindow, window_app: _App
    ) -> None:
        """The window's watch subscribes on build so external
        publishes route into the tree without any extra wiring."""
        window._build_ui()
        watch = window._selection_watch
        assert watch is not None
        assert watch._bus_sub is not None

    def test_window_destroy_cancels_bus_subscription(
        self,
        window_adapter: MockLayerStackAdapter,
        window_app: _App,
    ) -> None:
        """Window destroy tears the watch down; the bus subscription
        must drop so a later publish cannot dispatch into a dead
        tree view."""
        w = LayerWindow(
            services=window_app,
            adapter=window_adapter,
            settings=DefaultLayerSettings(),
        )
        w._build_ui()
        watch = w._selection_watch
        assert watch is not None
        bus_sub = watch._bus_sub
        assert bus_sub is not None
        w.destroy()
        assert watch._bus_sub is None
        # A post-destroy publish must not raise.
        window_app.selection_bus.publish(["/World/Cube"], source="stage")
