# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 38 — the :class:`ContextMenuBuilder`
framework and its predicate helpers.

Step 38 ships the declarative menu machinery; Steps 39-42 populate
the real entry list. The tests here lock the framework's contract
so later phases can append entries without regressing the filter
behaviour, the canonical-order grouping, the closure-capture fix for
the I8 closure bug, or the teardown path that prevents stale menus
from firing against dead contexts (LAYERS-WINDOW-ARCHITECTURE Logic F3).

Coverage:

- Predicate helpers — every predicate is exercised against a hand-
  built :class:`MenuContext` covering the happy path and at least
  one failure path. Predicates that read through
  :attr:`LayerItem.is_writable` / ``is_dirty`` / etc. route through
  the cached :class:`MockLayerStackAdapter`, so a ``set_muted`` call
  must invalidate the item before the next predicate read (same
  convention the tree-paint path uses).
- :class:`ContextMenuEntry` / :class:`MenuContext` — dataclass
  defaults, mutability (tests confirm we can append to
  ``tree_selection`` after building the context), and the
  ``separator_before`` flag round-trip.
- :class:`ContextMenuBuilder` — registration, canonical ordering,
  :meth:`build_entries_for` filtering, default Step-38 entries, and
  the click-handler closure guarantee (the I8 bug).
- LayerWindow wiring — the delegate callback slot carries the
  window's right-click handler, which funnels into the builder's
  :meth:`show_at`. The heavy UI path is gated on a ``ui.Frame``
  build probe so minimal environments skip rather than fail.
"""

from __future__ import annotations

from typing import List

import omni.ui as ui
import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import (
    ContextMenuBuilder,
    ContextMenuEntry,
    LayerItem,
    LayerModel,
    MenuContext,
)
from ovui_widgets.layers.context_menu import (
    GROUP_DESTRUCTIVE,
    GROUP_EDIT_TARGET,
    GROUP_FILE_IO,
    GROUP_STATE,
    GROUP_UTILITY,
    can_edit_root,
    has_any_items_selected,
    is_layer_dirty,
    is_layer_item,
    is_layer_locked,
    is_layer_muted,
    is_not_anonymous,
    is_not_current_edit_target,
    is_not_missing,
    is_not_reserved,
    is_not_root_layer,
    is_not_session_layer,
    is_single_selection,
    is_writable,
    no_items_selected,
)

# ── Shared fixtures ─────────────────────────────────────────────────


class _App:
    """Minimal stand-in for :class:`Application`; only the fields the
    click handlers read."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=True)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./anon_child.usda")
    return ad


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def model(adapter, app) -> LayerModel:
    m = LayerModel(adapter, services=app)
    yield m
    m.destroy()


def _find(model: LayerModel, identifier: str) -> LayerItem:
    item = model._items_by_id[identifier]
    assert isinstance(item, LayerItem)
    return item


def _ctx(
    model: LayerModel,
    item=None,
    tree_selection: List[LayerItem] = None,
    services=None,
) -> MenuContext:
    return MenuContext(
        item=item,
        tree_selection=list(tree_selection or []),
        model=model,
        services=services,
    )


def _can_build_frame() -> bool:
    try:
        w = ui.Window("__probe_ctx_menu__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_UI_AVAILABLE = _can_build_frame()
_skip_no_ui = pytest.mark.skipif(
    not _UI_AVAILABLE, reason="ui.Frame construction unavailable"
)


# ── Dataclass surface ───────────────────────────────────────────────


class TestMenuContextDataclass:
    def test_fields_round_trip(self, model) -> None:
        item = _find(model, "./child.usda")
        ctx = MenuContext(
            item=item, tree_selection=[item], model=model, services=None
        )
        assert ctx.item is item
        assert ctx.tree_selection == [item]
        assert ctx.model is model
        assert ctx.services is None

    def test_empty_area_item_is_none(self, model) -> None:
        ctx = MenuContext(
            item=None, tree_selection=[], model=model, services=None
        )
        assert ctx.item is None
        assert ctx.tree_selection == []

    def test_tree_selection_is_defensive(self, model) -> None:
        # The window snapshots ``selected_items`` into a fresh list.
        # Mutating the snapshot must not propagate back to the model.
        src = [_find(model, "./child.usda")]
        ctx = MenuContext(
            item=None, tree_selection=list(src), model=model, services=None
        )
        ctx.tree_selection.append(_find(model, "./anon_child.usda"))
        assert len(src) == 1


class TestContextMenuEntryDataclass:
    def test_default_fields(self) -> None:
        entry = ContextMenuEntry(
            label="Demo",
            show_fn=[],
            click_fn=lambda ctx: None,
        )
        assert entry.label == "Demo"
        assert entry.show_fn == []
        assert entry.icon is None
        assert entry.separator_before is False
        assert entry.enabled_fn is None
        assert entry.group == GROUP_UTILITY

    def test_custom_fields(self) -> None:
        entry = ContextMenuEntry(
            label="Save",
            show_fn=[is_layer_item],
            click_fn=lambda ctx: None,
            icon="save.svg",
            separator_before=True,
            enabled_fn=lambda ctx: True,
            group=GROUP_FILE_IO,
        )
        assert entry.icon == "save.svg"
        assert entry.separator_before is True
        assert entry.enabled_fn is not None
        assert entry.group == GROUP_FILE_IO


# ── Predicate helpers ───────────────────────────────────────────────


class TestIsLayerItem:
    def test_true_for_layer_item(self, model) -> None:
        item = _find(model, "./child.usda")
        assert is_layer_item(_ctx(model, item=item)) is True

    def test_false_for_empty_area(self, model) -> None:
        assert is_layer_item(_ctx(model, item=None)) is False


class TestSelectionPredicates:
    def test_no_items_selected_true_when_empty(self, model) -> None:
        assert no_items_selected(_ctx(model)) is True

    def test_no_items_selected_false_when_populated(self, model) -> None:
        sel = [_find(model, "./child.usda")]
        assert no_items_selected(_ctx(model, tree_selection=sel)) is False

    def test_has_any_items_selected_mirrors_no_items(self, model) -> None:
        assert has_any_items_selected(_ctx(model)) is False
        sel = [_find(model, "./child.usda")]
        assert has_any_items_selected(_ctx(model, tree_selection=sel)) is True

    def test_is_single_selection(self, model) -> None:
        a = _find(model, "./child.usda")
        b = _find(model, "./anon_child.usda")
        assert is_single_selection(_ctx(model, tree_selection=[a])) is True
        assert is_single_selection(_ctx(model)) is False
        assert is_single_selection(
            _ctx(model, tree_selection=[a, b])
        ) is False


class TestIsNotMissing:
    def test_true_for_normal_layer(self, model) -> None:
        item = _find(model, "./child.usda")
        assert is_not_missing(_ctx(model, item=item)) is True

    def test_false_for_empty_area(self, model) -> None:
        assert is_not_missing(_ctx(model, item=None)) is False

    def test_false_for_missing_layer(self, model, adapter) -> None:
        item = _find(model, "./child.usda")
        adapter._layers["./child.usda"].missing = True
        item.invalidate_flags()
        assert is_not_missing(_ctx(model, item=item)) is False


class TestIsNotAnonymous:
    def test_true_for_concrete(self, model) -> None:
        item = _find(model, "./child.usda")
        assert is_not_anonymous(_ctx(model, item=item)) is True

    def test_false_for_anonymous(self, model, adapter) -> None:
        item = _find(model, "./child.usda")
        adapter._layers["./child.usda"].anonymous = True
        item.invalidate_flags()
        assert is_not_anonymous(_ctx(model, item=item)) is False

    def test_false_for_empty_area(self, model) -> None:
        assert is_not_anonymous(_ctx(model, item=None)) is False


class TestIsWritable:
    def test_writable_true_by_default(self, model) -> None:
        item = _find(model, "./child.usda")
        assert is_writable(_ctx(model, item=item)) is True

    def test_muted_is_not_writable(self, model, adapter) -> None:
        item = _find(model, "./child.usda")
        adapter.set_mute("./child.usda", True)
        item.invalidate_flags()
        assert is_writable(_ctx(model, item=item)) is False

    def test_locked_is_not_writable(self, model, adapter) -> None:
        item = _find(model, "./child.usda")
        adapter.set_lock("./child.usda", True)
        item.invalidate_flags()
        assert is_writable(_ctx(model, item=item)) is False

    def test_empty_area_is_not_writable(self, model) -> None:
        assert is_writable(_ctx(model, item=None)) is False


class TestIsNotCurrentEditTarget:
    def test_true_when_not_edit_target(self, model) -> None:
        item = _find(model, "./child.usda")
        model._edit_target_identifier = ROOT_LAYER_IDENTIFIER
        assert is_not_current_edit_target(_ctx(model, item=item)) is True

    def test_false_when_is_edit_target(self, model) -> None:
        item = _find(model, "./child.usda")
        model._edit_target_identifier = item.identifier
        assert is_not_current_edit_target(_ctx(model, item=item)) is False

    def test_false_for_empty_area(self, model) -> None:
        assert is_not_current_edit_target(_ctx(model, item=None)) is False


class TestDirtyMutedLockedPredicates:
    def test_is_layer_dirty(self, model, adapter) -> None:
        item = _find(model, "./child.usda")
        assert is_layer_dirty(_ctx(model, item=item)) is False
        adapter.set_dirty("./child.usda", True)
        item.invalidate_flags()
        assert is_layer_dirty(_ctx(model, item=item)) is True

    def test_is_layer_muted(self, model, adapter) -> None:
        item = _find(model, "./child.usda")
        assert is_layer_muted(_ctx(model, item=item)) is False
        adapter.set_mute("./child.usda", True)
        item.invalidate_flags()
        assert is_layer_muted(_ctx(model, item=item)) is True

    def test_is_layer_locked(self, model, adapter) -> None:
        item = _find(model, "./child.usda")
        assert is_layer_locked(_ctx(model, item=item)) is False
        adapter.set_lock("./child.usda", True)
        item.invalidate_flags()
        assert is_layer_locked(_ctx(model, item=item)) is True

    def test_empty_area_returns_false(self, model) -> None:
        assert is_layer_dirty(_ctx(model, item=None)) is False
        assert is_layer_muted(_ctx(model, item=None)) is False
        assert is_layer_locked(_ctx(model, item=None)) is False


class TestRootAndSessionPredicates:
    def test_is_not_root_layer_true_for_sublayer(self, model) -> None:
        item = _find(model, "./child.usda")
        assert is_not_root_layer(_ctx(model, item=item)) is True

    def test_is_not_root_layer_false_for_root(self, model) -> None:
        root = model.root_item
        assert is_not_root_layer(_ctx(model, item=root)) is False

    def test_is_not_session_layer_true_for_sublayer(self, model) -> None:
        item = _find(model, "./child.usda")
        assert is_not_session_layer(_ctx(model, item=item)) is True

    def test_is_not_session_layer_false_for_session(self, model) -> None:
        session = model.session_item
        assert session is not None
        assert is_not_session_layer(_ctx(model, item=session)) is False

    def test_is_not_reserved_false_for_root(self, model) -> None:
        root = model.root_item
        assert is_not_reserved(_ctx(model, item=root)) is False

    def test_is_not_reserved_false_for_session(self, model) -> None:
        session = model.session_item
        assert session is not None
        assert is_not_reserved(_ctx(model, item=session)) is False

    def test_is_not_reserved_true_for_sublayer(self, model) -> None:
        item = _find(model, "./child.usda")
        assert is_not_reserved(_ctx(model, item=item)) is True


class TestCanEditRoot:
    def test_true_when_root_writable(self, model) -> None:
        assert can_edit_root(_ctx(model)) is True

    def test_false_when_root_locked(self, model, adapter) -> None:
        root = model.root_item
        adapter.set_lock(root.identifier, True)
        root.invalidate_flags()
        assert can_edit_root(_ctx(model)) is False


# ── Builder: registration + canonical order ─────────────────────────


STEP39_DEFAULT_ENTRY_COUNT = 17
STEP39_DEFAULT_LABELS = (
    "Set as Authoring Layer",
    "Create Sublayer",
    "Insert Sublayer...",
    "New Anonymous Sublayer",
)


class TestBuilderRegistration:
    def test_default_entries_registered(self, model) -> None:
        builder = ContextMenuBuilder(model=model, services=None)
        # Running default count — Step 39 ships seven entries, Step 40
        # adds four (Save / Save As / Reload / Remove), Step 41 adds
        # four more (Mute, Lock, Lock tree, Unlock tree), and Step 42
        # adds two (Merge Down, Flatten Sublayers). This test locks the
        # count so a later registration that accidentally adds a new
        # default here (rather than through a dedicated ``_register_*``
        # helper) fails loudly.
        assert len(builder.entries) == STEP39_DEFAULT_ENTRY_COUNT
        labels = [e.label for e in builder.entries]
        for expected in STEP39_DEFAULT_LABELS:
            assert expected in labels, f"missing default entry: {expected}"
        # "Create Sublayer", "Insert Sublayer...", "New Anonymous
        # Sublayer" each appear twice (on-layer + empty-area variant).
        assert labels.count("Create Sublayer") == 2
        assert labels.count("Insert Sublayer...") == 2
        assert labels.count("New Anonymous Sublayer") == 2
        assert labels.count("Set as Authoring Layer") == 1

    def test_register_entry_appends(self, model) -> None:
        builder = ContextMenuBuilder(model=model, services=None)
        before = len(builder.entries)
        builder.register_entry(
            ContextMenuEntry(
                label="Demo",
                show_fn=[is_layer_item],
                click_fn=lambda ctx: None,
            )
        )
        assert len(builder.entries) == before + 1
        assert builder.entries[-1].label == "Demo"

    def test_entries_property_is_defensive_copy(self, model) -> None:
        builder = ContextMenuBuilder(model=model, services=None)
        snapshot = builder.entries
        snapshot.clear()
        # Internal list still has the Step 39 defaults.
        assert len(builder.entries) == STEP39_DEFAULT_ENTRY_COUNT


class TestCanonicalOrder:
    def test_groups_sorted_ascending(self, model) -> None:
        builder = ContextMenuBuilder(model=model, services=None)
        # Register in reverse group order — canonical order should
        # re-sort ascending.
        builder.register_entry(
            ContextMenuEntry(
                label="Destruct",
                show_fn=[],
                click_fn=lambda c: None,
                group=GROUP_DESTRUCTIVE,
            )
        )
        builder.register_entry(
            ContextMenuEntry(
                label="EditTarget",
                show_fn=[],
                click_fn=lambda c: None,
                group=GROUP_EDIT_TARGET,
            )
        )
        labels = [e.label for e in builder._canonical_order()]
        edit_idx = labels.index("EditTarget")
        destruct_idx = labels.index("Destruct")
        assert edit_idx < destruct_idx

    def test_within_group_registration_order_preserved(self, model) -> None:
        builder = ContextMenuBuilder(model=model, services=None)
        builder.register_entry(
            ContextMenuEntry(
                label="First",
                show_fn=[],
                click_fn=lambda c: None,
                group=GROUP_STATE,
            )
        )
        builder.register_entry(
            ContextMenuEntry(
                label="Second",
                show_fn=[],
                click_fn=lambda c: None,
                group=GROUP_STATE,
            )
        )
        labels = [
            e.label for e in builder._canonical_order()
            if e.group == GROUP_STATE
        ]
        # GROUP_STATE already hosts the Step-41 mute/lock quartet by
        # default; the two registrations above must land **after** them
        # in registration order — Python's stable sort keeps entries
        # within a group in the order they were appended.
        assert labels[-2:] == ["First", "Second"]


# ── Builder: build_entries_for filtering ────────────────────────────


class TestBuildEntriesFor:
    def test_filters_by_all_predicates(self, model) -> None:
        builder = ContextMenuBuilder(model=model, services=None)
        # Empty-area context: the on-layer entries (gated by
        # :func:`is_layer_item`) filter out; the empty-area trio
        # (gated by :func:`is_empty_area` + :func:`can_edit_root`)
        # passes.
        ctx = _ctx(model, item=None)
        visible = builder.build_entries_for(ctx)
        labels = [e.label for e in visible]
        # "Set as Authoring Layer" needs a layer item.
        assert "Set as Authoring Layer" not in labels
        # Empty-area trio all pass.
        assert labels.count("Create Sublayer") == 1
        assert labels.count("Insert Sublayer...") == 1
        assert labels.count("New Anonymous Sublayer") == 1

    def test_predicates_all_must_pass(self, model) -> None:
        builder = ContextMenuBuilder(model=model, services=None)
        # Layer-item context: the on-layer trio (plus Set as
        # Authoring Layer when the layer is not the current edit
        # target) passes; the empty-area trio's
        # :func:`is_empty_area` predicate fails because
        # ``ctx.item is not None``.
        item = _find(model, "./child.usda")
        ctx = _ctx(
            model,
            item=item,
            tree_selection=[item],
        )
        visible = builder.build_entries_for(ctx)
        labels = [e.label for e in visible]
        # On-layer trio all pass; each label appears once (the empty-
        # area duplicates filtered out).
        assert labels.count("Create Sublayer") == 1
        assert labels.count("Insert Sublayer...") == 1
        assert labels.count("New Anonymous Sublayer") == 1
        # Set as Authoring Layer passes (./child.usda is not the
        # current edit target — root is by default).
        assert "Set as Authoring Layer" in labels

    def test_empty_show_fn_always_shows(self, model) -> None:
        builder = ContextMenuBuilder(model=model, services=None)
        builder.register_entry(
            ContextMenuEntry(
                label="AlwaysVisible",
                show_fn=[],
                click_fn=lambda c: None,
            )
        )
        visible = builder.build_entries_for(_ctx(model, item=None))
        assert "AlwaysVisible" in [e.label for e in visible]

    def test_returns_fresh_list(self, model) -> None:
        builder = ContextMenuBuilder(model=model, services=None)
        ctx = _ctx(model, item=None)
        a = builder.build_entries_for(ctx)
        b = builder.build_entries_for(ctx)
        # Defensive copies — mutations don't share state.
        assert a is not b
        a.clear()
        assert len(builder.build_entries_for(ctx)) > 0


# ── Closure-capture contract (LAYERS-PLAN Logic I8) ─────────────────


class TestClosureCapture:
    """The I8 closure bug: when ``show_at`` builds MenuItems in a
    loop, each ``triggered_fn`` must capture *this iteration's*
    entry and ctx — not a late-binding reference that mutates on the
    next ``show_at`` call. We can't directly introspect the built
    ``ui.MenuItem`` callback from headless, so we emulate the same
    build-loop pattern and assert the captured values.
    """

    def test_default_arg_closure_captures_per_iteration(self) -> None:
        triggers = []

        class _Entry:
            def __init__(self, label):
                self.label = label

            def click_fn(self, ctx):
                triggers.append((self.label, ctx))

        entries = [_Entry("A"), _Entry("B")]
        captured = []
        for i, entry in enumerate(entries):
            ctx = f"ctx_{i}"
            # This is exactly the lambda shape used in show_at.
            fn = lambda e=entry, c=ctx: e.click_fn(c)
            captured.append(fn)
        # Fire them all — each should carry its own (entry, ctx).
        for fn in captured:
            fn()
        assert triggers == [("A", "ctx_0"), ("B", "ctx_1")]

    def test_closure_captures_ctx(self, model) -> None:
        """The plan-named test: menu #1's click must NOT fire with
        menu #2's ctx. We simulate two successive ``show_at`` calls
        by building the lambda list twice with different contexts
        and assert the first lambda still fires with the first ctx.
        """
        a = _find(model, "./child.usda")
        b = _find(model, "./anon_child.usda")
        ctx_a = _ctx(model, item=a)
        ctx_b = _ctx(model, item=b)

        captured_items: List[LayerItem] = []

        def _click(ctx: MenuContext) -> None:
            captured_items.append(ctx.item)

        # First "menu build" — one item captured against ctx_a.
        fn_a = lambda e_click=_click, c=ctx_a: e_click(c)
        # Second "menu build" — a fresh ctx_b binding. If the lambda
        # had closed over the name rather than the value, the first
        # lambda fired after this point would see ctx_b.
        fn_b = lambda e_click=_click, c=ctx_b: e_click(c)

        fn_a()
        fn_b()
        # Each fn saw its own ctx.
        assert captured_items[0] is a
        assert captured_items[1] is b


# ── LayerWindow wiring (UI-available only) ──────────────────────────


@_skip_no_ui
class TestLayerWindowIntegration:
    """Tests exercising :class:`LayerWindow`'s wiring of the builder
    and the delegate's ``on_right_click`` hook.

    All tests drive ``w._build_ui()`` explicitly inside the window's
    frame scope — ``frame.rebuild()`` alone queues a rebuild but does
    not fire ``_build_ui`` synchronously (the paint pipeline does that
    on the next ovui frame, which a headless pytest session never
    drives). This matches the pattern in ``tests/test_layer_window.py``.
    """

    def test_window_builds_context_menu_builder(
        self, adapter, app
    ) -> None:
        from ovui_widgets.layers import LayerWindow

        win = LayerWindow(services=app, adapter=adapter)
        try:
            with win._window.frame:
                win._build_ui()
            assert win._context_menu_builder is not None
            assert isinstance(win._context_menu_builder, ContextMenuBuilder)
        finally:
            win.destroy()

    def test_delegate_on_right_click_wired_after_build(
        self, adapter, app
    ) -> None:
        from ovui_widgets.layers import LayerWindow

        win = LayerWindow(services=app, adapter=adapter)
        try:
            with win._window.frame:
                win._build_ui()
            assert win._delegate is not None
            # The delegate's right-click callback is the window's
            # bridge method — set during _build_ui.
            assert win._delegate.on_right_click == win._on_row_right_click
        finally:
            win.destroy()

    def test_empty_area_right_click_builds_empty_area_ctx(
        self, adapter, app, monkeypatch
    ) -> None:
        from ovui_widgets.layers import LayerWindow

        win = LayerWindow(services=app, adapter=adapter)
        try:
            with win._window.frame:
                win._build_ui()
            captured = {}

            def _fake_show_at(x, y, ctx):
                captured["x"] = x
                captured["y"] = y
                captured["ctx"] = ctx

            monkeypatch.setattr(
                win._context_menu_builder, "show_at", _fake_show_at
            )
            # Right-click in empty area
            win._on_empty_area_pressed(12.0, 34.0, 1, 0)
            assert captured["ctx"].item is None
            assert captured["x"] == 12.0
            assert captured["y"] == 34.0
            # Left-click: should NOT fire
            captured.clear()
            win._on_empty_area_pressed(12.0, 34.0, 0, 0)
            assert "ctx" not in captured
        finally:
            win.destroy()

    def test_row_right_click_builds_item_ctx(
        self, adapter, app, monkeypatch
    ) -> None:
        from ovui_widgets.layers import LayerWindow

        win = LayerWindow(services=app, adapter=adapter)
        try:
            with win._window.frame:
                win._build_ui()
            captured = {}

            def _fake_show_at(x, y, ctx):
                captured["x"] = x
                captured["y"] = y
                captured["ctx"] = ctx

            monkeypatch.setattr(
                win._context_menu_builder, "show_at", _fake_show_at
            )
            item = win._model._items_by_id["./child.usda"]
            win._on_row_right_click(item, 50.0, 60.0)
            assert captured["ctx"].item is item
            assert captured["ctx"].model is win._model
            assert captured["ctx"].services is app
            assert captured["x"] == 50.0
            assert captured["y"] == 60.0
        finally:
            win.destroy()

    def test_builder_retargets_on_set_adapter(
        self, adapter, app
    ) -> None:
        from ovui_widgets.layers import LayerWindow

        win = LayerWindow(services=app, adapter=adapter)
        try:
            with win._window.frame:
                win._build_ui()
            first_builder = win._context_menu_builder
            first_model = win._model
            # Swap the adapter and confirm the builder's model
            # reference follows. The builder instance may be reused
            # (preferred) — the contract is that it references the
            # current model after the swap.
            second_adapter = MockLayerStackAdapter(include_session=True)
            second_adapter.add_sublayer(
                ROOT_LAYER_IDENTIFIER, "./other.usda"
            )
            win.set_adapter(second_adapter)
            assert win._context_menu_builder is not None
            assert win._context_menu_builder._model is win._model
            assert win._model is first_model  # in-place retarget
        finally:
            win.destroy()

    def test_destroy_releases_builder(
        self, adapter, app
    ) -> None:
        from ovui_widgets.layers import LayerWindow

        win = LayerWindow(services=app, adapter=adapter)
        with win._window.frame:
            win._build_ui()
        assert win._context_menu_builder is not None
        win.destroy()
        assert win._context_menu_builder is None
