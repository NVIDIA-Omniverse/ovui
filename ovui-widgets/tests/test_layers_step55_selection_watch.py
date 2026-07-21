# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 55 — ``LayerSelectionWatch``.

Covers the §24.5 listener protocol and the §24.6 "exactly one
LayerItem" focus rule:

- Construction wires :meth:`ui.TreeView.set_selection_changed_fn` so
  the watch is the tree's single selection ingress.
- Single-:class:`LayerItem` selection fires every registered listener
  with that item; a re-selection of the same item does not re-fire.
- Multi-:class:`LayerItem`, empty, prim-spec-only, and mixed
  (layer + prim-spec) selections all resolve to ``None``.
- :meth:`add_listener` / :meth:`remove_listener` round-trip cleanly
  and are idempotent against duplicate registrations.
- :meth:`destroy` clears the tree's callback, drops listeners, and is
  idempotent so Step 55a's hide-then-destroy path stays safe.
- The ``on_change`` any-selection-change hook fires on every click
  (including prim-spec and multi selections) so :class:`LayerWindow`
  can drive the Step-54 footer-button refresh through the watch.
- Integration with :class:`LayerWindow`: ``_build_ui`` constructs a
  watch against the live tree view; a rebuild drops the old watch
  before attaching the new one; ``destroy`` releases it.
"""

from __future__ import annotations

from typing import Any, List, Optional

import pytest
from ovui_data_adapters.common import PrimSpecDescriptor, PrimSpecifier

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import (
    DefaultLayerSettings,
    LayerItem,
    LayerModel,
    LayerSelectionWatch,
    LayerWindow,
    PrimSpecItem,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


class _App:
    """Minimal :class:`Application` stand-in — only the fields the
    watch and its :class:`LayerWindow` host actually read."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


class _FakeTreeView:
    """Captures ``set_selection_changed_fn`` so tests can fire the
    callback without standing up a real :class:`ui.TreeView`.

    The watch's only contact surface with the tree in Step 55 is this
    single setter — mimicking it keeps the unit tests hermetic and
    decoupled from the ovui renderer.
    """

    def __init__(self) -> None:
        self.callback: Any = None
        self.set_calls: int = 0

    def set_selection_changed_fn(self, fn: Any) -> None:
        self.callback = fn
        self.set_calls += 1


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=False)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_a.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_b.usda")
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
    """Walk the tree and return the :class:`LayerItem` for ``identifier``."""
    stack: List[LayerItem] = list(model.get_item_children(None))
    while stack:
        node = stack.pop()
        if isinstance(node, LayerItem) and node.identifier == identifier:
            return node
        stack.extend(model.get_item_children(node))
    raise KeyError(identifier)


def _make_prim_spec_item(layer_item: LayerItem, path: str) -> PrimSpecItem:
    """Build a standalone :class:`PrimSpecItem` attached to ``layer_item``.

    The prim-spec-ignored tests only need the item's identity for
    ``isinstance`` filtering — no child-adapter round-trip is required.
    """
    descriptor = PrimSpecDescriptor(
        path=path,
        type_name="",
        specifier=PrimSpecifier.DEF,
        has_reference=False,
        has_payload=False,
        is_instanceable=False,
    )
    return PrimSpecItem(layer_item, descriptor)


# ─── Construction ────────────────────────────────────────────────────────────


class TestConstruction:
    def test_wires_tree_callback(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """The watch must own the tree view's selection callback."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            assert tree.set_calls == 1
            # Bound-method identity comparisons are brittle (Python
            # re-wraps on every attribute access) — verify by driving
            # the captured callback and observing the watch's focus.
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            tree.callback([root])
            assert watch.focused_layer is root
        finally:
            watch.destroy()

    def test_focused_layer_starts_none(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            assert watch.focused_layer is None
        finally:
            watch.destroy()


# ─── Focus listener protocol (§24.5 / §24.6) ────────────────────────────────


class TestFocusListener:
    def test_single_layer_fires_with_item(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        calls: List[Optional[LayerItem]] = []
        watch.add_listener(calls.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            tree.callback([root])
            assert calls == [root]
            assert watch.focused_layer is root
        finally:
            watch.destroy()

    def test_same_layer_does_not_refire(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """Re-selecting the same :class:`LayerItem` is a no-op — the
        listener fans out only when the focused-layer identity changes.
        """
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        calls: List[Optional[LayerItem]] = []
        watch.add_listener(calls.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            tree.callback([root])
            tree.callback([root])
            tree.callback([root])
            assert calls == [root]
        finally:
            watch.destroy()

    def test_switching_layers_refires(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        calls: List[Optional[LayerItem]] = []
        watch.add_listener(calls.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            child_a = _layer_item(model, "./child_a.usda")
            tree.callback([root])
            tree.callback([child_a])
            assert calls == [root, child_a]
            assert watch.focused_layer is child_a
        finally:
            watch.destroy()

    def test_multi_selection_fires_none(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        calls: List[Optional[LayerItem]] = []
        watch.add_listener(calls.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            child_a = _layer_item(model, "./child_a.usda")
            tree.callback([root])
            tree.callback([root, child_a])
            assert calls == [root, None]
            assert watch.focused_layer is None
        finally:
            watch.destroy()

    def test_empty_selection_fires_none(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        calls: List[Optional[LayerItem]] = []
        watch.add_listener(calls.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            tree.callback([root])
            tree.callback([])
            assert calls == [root, None]
            assert watch.focused_layer is None
        finally:
            watch.destroy()

    def test_prim_spec_only_ignored(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """A lone :class:`PrimSpecItem` selection is not a focused
        layer — the focus stays ``None`` and no listener fires."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        calls: List[Optional[LayerItem]] = []
        watch.add_listener(calls.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            spec = _make_prim_spec_item(root, "/World/Cube")
            tree.callback([spec])
            assert calls == []
            assert watch.focused_layer is None
        finally:
            watch.destroy()

    def test_prim_spec_in_mixed_selection_ignored(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """Mixing a :class:`LayerItem` with a :class:`PrimSpecItem`
        resolves to ``None`` (§24.6). Property panels cannot show both
        a layer and a prim spec at once."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        calls: List[Optional[LayerItem]] = []
        watch.add_listener(calls.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            spec = _make_prim_spec_item(root, "/World/Cube")
            tree.callback([root, spec])
            assert calls == []
            assert watch.focused_layer is None
        finally:
            watch.destroy()

    def test_listener_receives_none_when_leaving_focus(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """Transitioning from a focused layer to a prim-spec row
        still fires the listener — this time with ``None`` — so
        subscribers can clear any layer-scoped UI."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        calls: List[Optional[LayerItem]] = []
        watch.add_listener(calls.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            spec = _make_prim_spec_item(root, "/World/Cube")
            tree.callback([root])
            tree.callback([spec])
            assert calls == [root, None]
        finally:
            watch.destroy()


# ─── Listener subscribe / unsubscribe ───────────────────────────────────────


class TestSubscribeUnsubscribe:
    def test_multiple_listeners_all_fire(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        a: List[Optional[LayerItem]] = []
        b: List[Optional[LayerItem]] = []
        watch.add_listener(a.append)
        watch.add_listener(b.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            tree.callback([root])
            assert a == [root]
            assert b == [root]
        finally:
            watch.destroy()

    def test_remove_listener_silences_it(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        calls: List[Optional[LayerItem]] = []
        watch.add_listener(calls.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            child_a = _layer_item(model, "./child_a.usda")
            tree.callback([root])
            watch.remove_listener(calls.append)
            tree.callback([child_a])
            assert calls == [root]
        finally:
            watch.destroy()

    def test_add_listener_is_idempotent(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """Re-registering the same callable does not double-fire."""
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        calls: List[Optional[LayerItem]] = []
        watch.add_listener(calls.append)
        watch.add_listener(calls.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            tree.callback([root])
            assert calls == [root]
        finally:
            watch.destroy()

    def test_remove_unknown_listener_is_noop(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        try:
            watch.remove_listener(lambda _: None)  # must not raise
        finally:
            watch.destroy()

    def test_listener_unsubscribing_itself_mid_dispatch(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """A listener that unsubscribes itself during dispatch cannot
        perturb the iteration for the peer listeners that come after.
        """
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        peer_calls: List[Optional[LayerItem]] = []

        def suicidal(_: Optional[LayerItem]) -> None:
            watch.remove_listener(suicidal)

        watch.add_listener(suicidal)
        watch.add_listener(peer_calls.append)
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            tree.callback([root])
            assert peer_calls == [root]
        finally:
            watch.destroy()


# ─── ``on_change`` hook ─────────────────────────────────────────────────────


class TestOnChangeHook:
    def test_fires_on_every_selection_change(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """The ``on_change`` hook fires on every callback — focus
        change or not. :class:`LayerWindow` uses this to refresh the
        Step-54 footer flags on every click.
        """
        seen: List[List[Any]] = []
        watch = LayerSelectionWatch(
            tree, model, app.selection_bus, on_change=seen.append
        )
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            tree.callback([root])
            tree.callback([root])  # no focus change
            tree.callback([])
            assert len(seen) == 3
            assert seen[0] == [root]
            assert seen[1] == [root]
            assert seen[2] == []
        finally:
            watch.destroy()

    def test_fires_before_focus_listeners(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """The any-change hook must run before focus listeners so
        :class:`LayerWindow` can sync the model before any consumer
        reads :attr:`LayerModel.selected_items`."""
        order: List[str] = []
        watch = LayerSelectionWatch(
            tree,
            model,
            app.selection_bus,
            on_change=lambda _: order.append("change"),
        )
        watch.add_listener(lambda _: order.append("focus"))
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            tree.callback([root])
            assert order == ["change", "focus"]
        finally:
            watch.destroy()

    def test_hook_receives_copy_not_backing_list(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        """The hook's items argument must be a fresh list — callers
        that stash or mutate it cannot reach back into the tree's
        private state."""
        captured: List[List[Any]] = []
        watch = LayerSelectionWatch(
            tree, model, app.selection_bus, on_change=captured.append
        )
        try:
            root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
            source = [root]
            tree.callback(source)
            assert captured[0] is not source
            assert captured[0] == [root]
        finally:
            watch.destroy()


# ─── Destroy ────────────────────────────────────────────────────────────────


class TestDestroy:
    def test_clears_tree_callback(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        watch.destroy()
        # Construction set the callback once; destroy re-set it to None.
        assert tree.set_calls == 2
        assert tree.callback is None

    def test_idempotent(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        watch.destroy()
        watch.destroy()  # must not raise

    def test_listeners_dropped(
        self,
        tree: _FakeTreeView,
        model: LayerModel,
        app: _App,
    ) -> None:
        watch = LayerSelectionWatch(tree, model, app.selection_bus)
        watch.add_listener(lambda _: None)
        watch.destroy()
        assert watch._listeners == []
        assert watch.focused_layer is None

    def test_tolerates_tree_raising_on_detach(
        self,
        model: LayerModel,
        app: _App,
    ) -> None:
        """A torn-down tree view may reject callback removal — destroy
        must still clear the watch's state rather than propagate."""
        class _ExplodingTree:
            def __init__(self) -> None:
                self.callback = None

            def set_selection_changed_fn(self, fn: Any) -> None:
                if fn is None:
                    raise RuntimeError("tree already dead")
                self.callback = fn

        tv = _ExplodingTree()
        watch = LayerSelectionWatch(tv, model, app.selection_bus)
        watch.destroy()  # does not raise
        assert watch._tree_view is None


# ─── LayerWindow integration ─────────────────────────────────────────────────


class TestWindowIntegration:
    def test_build_ui_constructs_watch(self, window: LayerWindow) -> None:
        assert window._selection_watch is None
        window._build_ui()
        assert isinstance(window._selection_watch, LayerSelectionWatch)

    def test_rebuild_replaces_watch(self, window: LayerWindow) -> None:
        window._build_ui()
        first = window._selection_watch
        assert first is not None
        window._build_ui()
        assert window._selection_watch is not first
        # The old watch must have been destroyed so it no longer
        # holds a live tree-view reference.
        assert first._tree_view is None

    def test_destroy_releases_watch(
        self, adapter: MockLayerStackAdapter, app: _App
    ) -> None:
        w = LayerWindow(services=app, adapter=adapter, settings=DefaultLayerSettings())
        w._build_ui()
        watch = w._selection_watch
        assert watch is not None
        w.destroy()
        assert w._selection_watch is None
        assert watch._tree_view is None

    def test_watch_forwards_to_model_via_on_change(
        self, window: LayerWindow
    ) -> None:
        """The watch's ``on_change`` hook must flow through the window
        so :attr:`LayerModel.selected_items` still tracks the tree
        selection — this preserves Step-16 semantics without a direct
        ``set_selection_changed_fn`` binding on the window itself."""
        window._build_ui()
        model = window._model
        assert model is not None
        root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
        # Fire via the watch's own callback surface so the test
        # exercises the same dispatch path the real tree view uses.
        window._selection_watch._on_tree_selection_changed([root])
        assert model.selected_items == [root]

    def test_watch_focus_listener_sees_window_clicks(
        self, window: LayerWindow
    ) -> None:
        """A downstream consumer registered via ``add_listener`` on
        the window's watch must see focus transitions driven by tree
        clicks — the end-to-end §24.5 path the Property panel uses."""
        window._build_ui()
        model = window._model
        assert model is not None
        root = _layer_item(model, ROOT_LAYER_IDENTIFIER)
        child_a = _layer_item(model, "./child_a.usda")
        calls: List[Optional[LayerItem]] = []
        window._selection_watch.add_listener(calls.append)
        window._selection_watch._on_tree_selection_changed([root])
        window._selection_watch._on_tree_selection_changed([root, child_a])
        assert calls == [root, None]
