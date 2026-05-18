# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 43 — Internal drag-drop (reorder sublayers).

Step 43 adds three ``ui.AbstractItemModel`` overrides to
:class:`~ovwidgets.layers.layer_model.LayerModel`:

- :meth:`get_drag_mime_data` — the identifier of the dragged layer, or
  the empty string for reserved top-level rows (root / session) so ovui
  refuses to start a drag on them.
- :meth:`drop_accepted` — validates the drag: rejects non-LayerItem
  sources, reserved rows, circular moves, and drops into non-writable
  parents. Returns ``True`` for every otherwise-legal move.
- :meth:`drop` — executes a validated move by pushing a
  :class:`~ovwidgets.layers.commands.MoveSublayerCommand` through the app's
  undo manager (or a direct adapter call in headless construction).

``drop_location`` semantics mirror the plan's bullet list:

- ``drop_location == -1`` — drop *onto* the target; the target becomes
  the new parent and the source is appended to its sublayer list.
- ``drop_location >= 0`` — drop *between* rows inside the target's
  parent; the source is inserted at that slot.
"""

from __future__ import annotations

from typing import List

import pytest

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import LayerModel
from ovwidgets.layers.commands import MoveSublayerCommand


class _App:
    """Minimal :class:`Application` stand-in for undo-pipeline tests."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    # Two-parent tree — enough nodes to exercise reorder within parent,
    # cross-parent reparent, and circular rejection:
    #   root
    #     ├── ./a.usda
    #     │     └── ./nested.usda
    #     ├── ./b.usda
    #     └── ./c.usda
    ad = MockLayerStackAdapter(include_session=True)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./a.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./b.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./c.usda")
    ad.add_sublayer("./a.usda", "./nested.usda")
    return ad


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def model(adapter: MockLayerStackAdapter, app: _App) -> LayerModel:
    m = LayerModel(adapter, services=app)
    yield m
    m.destroy()


@pytest.fixture
def headless_model(adapter: MockLayerStackAdapter) -> LayerModel:
    """Bare model with no app — exercises the direct-adapter fallback path."""
    m = LayerModel(adapter, services=None)
    yield m
    m.destroy()


def _root_children(adapter: MockLayerStackAdapter) -> List[str]:
    return adapter.get_sublayer_identifiers(adapter.get_root_layer())


# ── get_drag_mime_data ──────────────────────────────────────────────


class TestGetDragMimeData:
    def test_returns_identifier_for_sublayer(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        assert model.get_drag_mime_data(a) == "./a.usda"

    def test_returns_identifier_for_nested_sublayer(
        self, model: LayerModel
    ) -> None:
        nested = model._items_by_id["./nested.usda"]
        assert model.get_drag_mime_data(nested) == "./nested.usda"

    def test_empty_for_root_item(self, model: LayerModel) -> None:
        assert model.get_drag_mime_data(model.root_item) == ""

    def test_empty_for_session_item(self, model: LayerModel) -> None:
        assert model.get_drag_mime_data(model.session_item) == ""

    def test_empty_for_non_layer_item(self, model: LayerModel) -> None:
        assert model.get_drag_mime_data(None) == ""
        assert model.get_drag_mime_data("not-a-layer") == ""


# ── drop_accepted / _can_move_layer validation ──────────────────────


class TestDropAcceptedValidation:
    def test_rejects_non_layer_target(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(None, a, -1) is False
        assert model.drop_accepted("nope", a, -1) is False

    def test_rejects_non_layer_source(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        # Step 45 accepts USD-extension strings as file drops; Step 43
        # still rejects everything else (numbers, strings without a
        # USD-compatible suffix, ...).
        assert model.drop_accepted(a, "not-a-path", -1) is False
        assert model.drop_accepted(a, 42, -1) is False

    def test_rejects_source_equals_target(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(a, a, -1) is False
        assert model.drop_accepted(a, a, 0) is False

    def test_rejects_dragging_root_layer(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        # Root has no parent, so it cannot be moved out of anywhere.
        assert model.drop_accepted(a, model.root_item, -1) is False

    def test_rejects_dragging_session_layer(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(a, model.session_item, -1) is False

    def test_rejects_circular_drop_onto_descendant(
        self, model: LayerModel
    ) -> None:
        # source=./a.usda, target=./nested.usda (descendant of ./a.usda).
        # Dropping A onto its own nested child would cycle.
        a = model._items_by_id["./a.usda"]
        nested = model._items_by_id["./nested.usda"]
        assert model.drop_accepted(nested, a, -1) is False

    def test_rejects_between_drop_with_descendant_parent(
        self, model: LayerModel
    ) -> None:
        # Dropping A between nested's siblings would reparent A to
        # ./nested.usda's parent — which is A itself. Cycle.
        a = model._items_by_id["./a.usda"]
        nested = model._items_by_id["./nested.usda"]
        # drop_location == 0 means "insert at nested's parent [./a.usda]
        # position 0" — that parent is source itself. Reject.
        assert model.drop_accepted(nested, a, 0) is False

    def test_rejects_between_drop_on_top_level(
        self, model: LayerModel
    ) -> None:
        # Dropping between root/session rows has no parent sublayer list
        # to receive the move.
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(model.root_item, a, 0) is False

    def test_rejects_drop_onto_locked_parent(
        self, adapter: MockLayerStackAdapter, model: LayerModel
    ) -> None:
        # Lock ./a.usda — drops ONTO it (becoming its child) must reject.
        adapter.set_lock("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        b = model._items_by_id["./b.usda"]
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(a, b, -1) is False

    def test_rejects_drop_onto_muted_parent(
        self, adapter: MockLayerStackAdapter, model: LayerModel
    ) -> None:
        adapter.set_mute("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        assert model.drop_accepted(a, b, -1) is False

    def test_accepts_valid_reorder_within_parent(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        # Drop C between A and B (drop_location == 1 under root).
        assert model.drop_accepted(a, c, 1) is True

    def test_accepts_valid_reparent(self, model: LayerModel) -> None:
        # Drop C ONTO A (C becomes A's child).
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        assert model.drop_accepted(a, c, -1) is True

    def test_accepts_drop_onto_root(self, model: LayerModel) -> None:
        # Pull ./nested.usda out of ./a.usda and append to root.
        nested = model._items_by_id["./nested.usda"]
        assert model.drop_accepted(model.root_item, nested, -1) is True


# ── drop — reorder within parent ────────────────────────────────────


class TestDropReorderWithinParent:
    def test_pushes_move_command_through_undo_manager(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        # Drop C at slot 1 of root's sublayers → [A, C, B].
        model.drop(a, c, 1)
        assert _root_children(adapter) == [
            "./a.usda", "./c.usda", "./b.usda",
        ]
        assert app.undo_manager.can_undo() is True

    def test_undo_restores_original_order(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        model.drop(a, c, 1)
        assert _root_children(adapter) == [
            "./a.usda", "./c.usda", "./b.usda",
        ]
        app.undo_manager.undo()
        assert _root_children(adapter) == [
            "./a.usda", "./b.usda", "./c.usda",
        ]

    def test_redo_reapplies(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        model.drop(a, c, 1)
        app.undo_manager.undo()
        app.undo_manager.redo()
        assert _root_children(adapter) == [
            "./a.usda", "./c.usda", "./b.usda",
        ]

    def test_pushed_command_is_move_sublayer_command(
        self, model: LayerModel, app: _App
    ) -> None:
        b = model._items_by_id["./b.usda"]
        c = model._items_by_id["./c.usda"]
        # Drop C between A and B (slot 1).
        model.drop(b, c, 1)
        # Latest undo-stack entry is our MoveSublayerCommand.
        history = app.undo_manager._undo_stack
        assert len(history) == 1
        assert isinstance(history[-1], MoveSublayerCommand)


# ── drop — reparent (cross-parent) ──────────────────────────────────


class TestDropReparent:
    def test_drop_onto_appends_to_new_parent(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        # Drop ./c.usda ONTO ./a.usda — C becomes A's second sublayer.
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        model.drop(a, c, -1)
        assert _root_children(adapter) == ["./a.usda", "./b.usda"]
        a_handle = adapter.find_layer("./a.usda")
        assert adapter.get_sublayer_identifiers(a_handle) == [
            "./nested.usda", "./c.usda",
        ]

    def test_undo_restores_cross_parent_move(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        model.drop(a, c, -1)
        app.undo_manager.undo()
        assert _root_children(adapter) == [
            "./a.usda", "./b.usda", "./c.usda",
        ]
        assert adapter.get_sublayer_identifiers(
            adapter.find_layer("./a.usda")
        ) == ["./nested.usda"]

    def test_drop_nested_back_onto_root(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        # Lift ./nested.usda out of ./a.usda and append to root.
        nested = model._items_by_id["./nested.usda"]
        model.drop(model.root_item, nested, -1)
        assert "./nested.usda" in _root_children(adapter)
        a_handle = adapter.find_layer("./a.usda")
        assert adapter.get_sublayer_identifiers(a_handle) == []


# ── drop — invalid moves must not fire commands ─────────────────────


class TestDropRejectsInvalid:
    def test_circular_drop_pushes_no_command(
        self, model: LayerModel, app: _App
    ) -> None:
        a = model._items_by_id["./a.usda"]
        nested = model._items_by_id["./nested.usda"]
        model.drop(nested, a, -1)
        assert app.undo_manager.can_undo() is False

    def test_self_drop_pushes_no_command(
        self, model: LayerModel, app: _App
    ) -> None:
        a = model._items_by_id["./a.usda"]
        model.drop(a, a, -1)
        assert app.undo_manager.can_undo() is False

    def test_root_drag_pushes_no_command(
        self, model: LayerModel, app: _App
    ) -> None:
        a = model._items_by_id["./a.usda"]
        # Cannot drag the root layer.
        model.drop(a, model.root_item, -1)
        assert app.undo_manager.can_undo() is False

    def test_locked_target_pushes_no_command(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        adapter.set_lock("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        model.drop(a, b, -1)
        assert app.undo_manager.can_undo() is False

    def test_non_layer_source_pushes_no_command(
        self, model: LayerModel, app: _App
    ) -> None:
        a = model._items_by_id["./a.usda"]
        # Step 45 accepts USD-extension strings — use a non-USD
        # payload so the Step-43 "unsupported source" branch is the
        # one exercised.
        model.drop(a, "not-a-path", -1)
        assert app.undo_manager.can_undo() is False


# ── Headless fallback ───────────────────────────────────────────────


class TestHeadlessDropFallback:
    def test_drop_without_app_calls_adapter_directly(
        self,
        adapter: MockLayerStackAdapter,
        headless_model: LayerModel,
    ) -> None:
        # With no app attached, the drop path bypasses the undo stack
        # and calls adapter.move_sublayer straight-through — the only
        # way a bare-model unit test can exercise the drop without
        # fabricating an UndoManager.
        a = headless_model._items_by_id["./a.usda"]
        c = headless_model._items_by_id["./c.usda"]
        headless_model.drop(a, c, 1)
        assert _root_children(adapter) == [
            "./a.usda", "./c.usda", "./b.usda",
        ]

    def test_drop_on_destroyed_model_is_noop(
        self,
        adapter: MockLayerStackAdapter,
        app: _App,
    ) -> None:
        model = LayerModel(adapter, services=app)
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        model.destroy()
        # A late release after the window tore down must not reach a
        # nulled adapter.
        model.drop(a, c, 1)
        # Order untouched.
        assert _root_children(adapter) == [
            "./a.usda", "./b.usda", "./c.usda",
        ]


# ── drop_accepted / drop — semantic coupling ────────────────────────


class TestDropAcceptedMatchesDrop:
    """drop_accepted and drop must share the same validation predicate —
    a drop that drop_accepted rejects must not mutate the stack."""

    def test_circular_drop_matches_reject(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        nested = model._items_by_id["./nested.usda"]
        assert model.drop_accepted(nested, a, -1) is False
        model.drop(nested, a, -1)
        # State unchanged — A remains at root, nested under A.
        assert _root_children(adapter) == [
            "./a.usda", "./b.usda", "./c.usda",
        ]
        assert adapter.get_sublayer_identifiers(
            adapter.find_layer("./a.usda")
        ) == ["./nested.usda"]

    def test_locked_parent_drop_matches_reject(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        adapter.set_lock("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        assert model.drop_accepted(a, b, -1) is False
        model.drop(a, b, -1)
        assert adapter.get_sublayer_identifiers(
            adapter.find_layer("./a.usda")
        ) == ["./nested.usda"]
