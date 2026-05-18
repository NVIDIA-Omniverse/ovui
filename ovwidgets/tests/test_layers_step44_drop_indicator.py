# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 44 — Drop indicator visual.

Step 44 adds a :class:`~ovwidgets.layers.drop_visual_controller.DropVisualController`
owned by :class:`~ovwidgets.layers.layer_model.LayerModel` that tracks the
active drag-over target (if any), the ovui-provided ``drop_location``,
whether the hover validates, and the human-readable rejection reason
for invalid drops. The :class:`~ovwidgets.layers.layer_delegate.LayerDelegate`
reads the controller on every ``build_widget`` / ``build_branch`` pass
and paints one of four named indicator overlays.

Coverage split:

- :class:`TestDropVisualController` — pure-state tests on the
  controller. No :class:`LayerModel` wiring; exercises mutators,
  accessors, and :meth:`indicator_for` fall-outs.
- :class:`TestModelDropIndicatorIntegration` — drag-hover plumbing on
  the real model: :meth:`drop_accepted` updates the controller with
  the correct ``is_valid`` / ``rejection_reason``, :meth:`drop`
  clears state on accept and reject, late callbacks after
  :meth:`destroy` don't fault.
- :class:`TestCanMoveLayerRejectionReasons` — the return-tuple from
  :meth:`LayerModel._can_move_layer` carries the right reason token
  for each reject branch (matches the LAYERS-PLAN Step 44 copy so
  the tooltip / toast text is stable).
"""

from __future__ import annotations

from typing import List

import pytest

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import LayerModel
from ovwidgets.layers.drop_visual_controller import (
    INDICATOR_DROP_ABOVE,
    INDICATOR_DROP_BELOW,
    INDICATOR_DROP_REJECTED,
    INDICATOR_DROP_TARGET,
    INDICATOR_NONE,
    DropVisualController,
)


class _App:
    """Minimal :class:`Application` stand-in for undo-pipeline tests."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    # Same tree used by Step 43 tests so rejection-reason assertions
    # against locked / muted parents stay stable when the two files
    # read side by side.
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


# ── DropVisualController state ──────────────────────────────────────


class TestDropVisualController:
    def test_initial_state_is_empty(self) -> None:
        dvc = DropVisualController()
        assert dvc.current_target is None
        assert dvc.current_drop_location == -1
        assert dvc.is_valid is False
        assert dvc.rejection_reason is None

    def test_show_valid_sets_target_and_location(self) -> None:
        dvc = DropVisualController()
        item = object()  # stand-in; indicator_for gates on LayerItem
        previous = dvc.show_valid(item, -1)
        assert previous is None
        assert dvc.current_target is item
        assert dvc.current_drop_location == -1
        assert dvc.is_valid is True
        assert dvc.rejection_reason is None

    def test_show_rejected_stores_reason(self) -> None:
        dvc = DropVisualController()
        item = object()
        previous = dvc.show_rejected(item, -1, "would cycle")
        assert previous is None
        assert dvc.current_target is item
        assert dvc.is_valid is False
        assert dvc.rejection_reason == "would cycle"

    def test_show_returns_previous_target(self) -> None:
        dvc = DropVisualController()
        a, b = object(), object()
        dvc.show_valid(a, -1)
        previous = dvc.show_valid(b, -1)
        assert previous is a

    def test_show_valid_clears_prior_rejection_reason(self) -> None:
        dvc = DropVisualController()
        a = object()
        dvc.show_rejected(a, -1, "nope")
        dvc.show_valid(a, -1)
        assert dvc.is_valid is True
        assert dvc.rejection_reason is None

    def test_clear_resets_all_state(self) -> None:
        dvc = DropVisualController()
        dvc.show_rejected(object(), 3, "no good")
        previous = dvc.clear()
        assert previous is not None
        assert dvc.current_target is None
        assert dvc.current_drop_location == -1
        assert dvc.is_valid is False
        assert dvc.rejection_reason is None

    def test_clear_is_idempotent(self) -> None:
        dvc = DropVisualController()
        assert dvc.clear() is None
        assert dvc.clear() is None
        assert dvc.current_target is None


class TestIndicatorFor:
    """:meth:`DropVisualController.indicator_for` — the delegate lookup."""

    def test_no_target_returns_none(
        self, model: LayerModel
    ) -> None:
        dvc = DropVisualController()
        a = model._items_by_id["./a.usda"]
        assert dvc.indicator_for(a) == INDICATOR_NONE

    def test_non_target_item_returns_none(
        self, model: LayerModel
    ) -> None:
        dvc = DropVisualController()
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        dvc.show_valid(a, -1)
        assert dvc.indicator_for(b) == INDICATOR_NONE

    def test_valid_onto_target_returns_drop_target(
        self, model: LayerModel
    ) -> None:
        dvc = DropVisualController()
        a = model._items_by_id["./a.usda"]
        dvc.show_valid(a, -1)
        assert dvc.indicator_for(a) == INDICATOR_DROP_TARGET

    def test_rejected_onto_returns_drop_rejected(
        self, model: LayerModel
    ) -> None:
        dvc = DropVisualController()
        a = model._items_by_id["./a.usda"]
        dvc.show_rejected(a, -1, "reason")
        assert dvc.indicator_for(a) == INDICATOR_DROP_REJECTED

    def test_rejected_between_returns_drop_rejected(
        self, model: LayerModel
    ) -> None:
        # A rejected between-drop reads as a full-row red because the
        # user hasn't committed to an above/below side.
        dvc = DropVisualController()
        a = model._items_by_id["./a.usda"]
        dvc.show_rejected(a, 1, "locked")
        assert dvc.indicator_for(a) == INDICATOR_DROP_REJECTED

    def test_valid_between_above_when_drop_at_target_position(
        self, model: LayerModel
    ) -> None:
        # Root's sublayers: [./a.usda, ./b.usda, ./c.usda]. ./b is at
        # position 1. drop_location == 1 inserts at that slot — above B.
        dvc = DropVisualController()
        b = model._items_by_id["./b.usda"]
        dvc.show_valid(b, 1)
        assert dvc.indicator_for(b) == INDICATOR_DROP_ABOVE

    def test_valid_between_above_when_drop_at_zero(
        self, model: LayerModel
    ) -> None:
        dvc = DropVisualController()
        a = model._items_by_id["./a.usda"]
        # a is at position 0 under root. drop_location == 0 → above.
        dvc.show_valid(a, 0)
        assert dvc.indicator_for(a) == INDICATOR_DROP_ABOVE

    def test_valid_between_below_when_drop_past_target_position(
        self, model: LayerModel
    ) -> None:
        # ./b is at position 1. drop_location == 2 → land after B → below.
        dvc = DropVisualController()
        b = model._items_by_id["./b.usda"]
        dvc.show_valid(b, 2)
        assert dvc.indicator_for(b) == INDICATOR_DROP_BELOW

    def test_non_layer_item_target_defaults_to_above(self) -> None:
        # Defensive — a target with no parent (e.g. root) should fall
        # out to above rather than raise when drop_location >= 0.
        dvc = DropVisualController()
        sentinel = object()
        dvc.show_valid(sentinel, 0)
        assert dvc.indicator_for(sentinel) == INDICATOR_DROP_ABOVE


# ── LayerModel ↔ controller plumbing ────────────────────────────────


class TestModelDropIndicatorIntegration:
    def test_model_owns_controller(self, model: LayerModel) -> None:
        assert isinstance(model.drop_visual, DropVisualController)

    def test_valid_drop_accepted_marks_target_valid(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        assert model.drop_accepted(a, c, -1) is True
        dv = model.drop_visual
        assert dv.current_target is a
        assert dv.current_drop_location == -1
        assert dv.is_valid is True
        assert dv.rejection_reason is None

    def test_rejected_drop_accepted_marks_target_rejected(
        self, model: LayerModel
    ) -> None:
        # Source == target — straightforward rejection path.
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(a, a, -1) is False
        dv = model.drop_visual
        assert dv.current_target is a
        assert dv.is_valid is False
        assert dv.rejection_reason == (
            "Cannot drop: source and target are the same row"
        )

    def test_circular_drop_accepted_marks_rejected_with_cycle_reason(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        nested = model._items_by_id["./nested.usda"]
        assert model.drop_accepted(nested, a, -1) is False
        assert (
            model.drop_visual.rejection_reason
            == "Cannot drop: would create circular reference"
        )

    def test_locked_target_marks_rejected_with_locked_reason(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        adapter.set_lock("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        assert model.drop_accepted(a, b, -1) is False
        assert (
            model.drop_visual.rejection_reason
            == "Cannot drop: target layer is locked"
        )

    def test_muted_target_marks_rejected_with_muted_reason(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        adapter.set_mute("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        assert model.drop_accepted(a, b, -1) is False
        assert (
            model.drop_visual.rejection_reason
            == "Cannot drop: target layer is muted"
        )

    def test_root_drag_marks_rejected_with_root_reason(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(a, model.root_item, -1) is False
        assert (
            model.drop_visual.rejection_reason
            == "Cannot drop: root and session layers cannot be moved"
        )

    def test_between_drop_top_level_rejected_with_between_reason(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        assert model.drop_accepted(model.root_item, a, 0) is False
        assert (
            model.drop_visual.rejection_reason
            == "Cannot drop: top-level rows cannot accept a between-drop"
        )

    def test_non_layer_target_clears_indicator(
        self, model: LayerModel
    ) -> None:
        # Prime the controller with a valid hover, then feed a
        # non-LayerItem target (string payload, future Step 45-ish).
        # The indicator must clear so the stale highlight doesn't linger.
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        model.drop_accepted(a, c, -1)
        assert model.drop_visual.current_target is a
        assert model.drop_accepted(None, c, -1) is False
        assert model.drop_visual.current_target is None

    def test_non_layer_source_marks_rejected_unsupported(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        # Step 45 accepts USD-extension strings — use a non-USD, non-
        # string payload so the "unsupported drag source" branch is
        # the one exercised.
        assert model.drop_accepted(a, 42, -1) is False
        dv = model.drop_visual
        assert dv.current_target is a
        assert dv.is_valid is False
        assert dv.rejection_reason == (
            "Cannot drop: unsupported drag source"
        )

    def test_successful_drop_clears_indicator(
        self,
        model: LayerModel,
    ) -> None:
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        model.drop_accepted(a, c, -1)
        assert model.drop_visual.current_target is a
        model.drop(a, c, -1)
        assert model.drop_visual.current_target is None
        assert model.drop_visual.current_drop_location == -1

    def test_rejected_drop_release_clears_indicator(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        adapter.set_lock("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        model.drop_accepted(a, b, -1)
        assert model.drop_visual.is_valid is False
        model.drop(a, b, -1)
        # Rejected release must clear state so the red outline doesn't
        # linger forever after the user releases.
        assert model.drop_visual.current_target is None

    def test_hover_refresh_repaints_stale_row(
        self, model: LayerModel
    ) -> None:
        # :meth:`LayerModel._fire_drop_indicator_refresh` calls
        # ``_item_changed`` on the stale row so ovui repaints it.
        # Monkey-patch ``_item_changed`` to record invocations.
        invocations: List[object] = []
        original = model._item_changed

        def recorder(item):
            invocations.append(item)
            return original(item)

        model._item_changed = recorder  # type: ignore[assignment]
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        c = model._items_by_id["./c.usda"]
        invocations.clear()
        # First hover — no previous target, so only ``a`` repaints.
        model.drop_accepted(a, c, -1)
        assert a in invocations
        invocations.clear()
        # Hover moves to ``b`` — both the old target ``a`` and the
        # new target ``b`` repaint so the indicator rides along.
        model.drop_accepted(b, c, -1)
        assert a in invocations
        assert b in invocations

    def test_destroyed_model_clear_is_safe(
        self,
        adapter: MockLayerStackAdapter,
        app: _App,
    ) -> None:
        # A drag-in-progress followed by destroy (user closes the
        # window before releasing) must not crash on the
        # ``_item_changed`` path.
        model = LayerModel(adapter, services=app)
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        model.drop_accepted(a, c, -1)
        model.destroy()
        # Controller was cleared as part of destroy, so current_target
        # is None and subsequent calls are no-ops.
        assert model.drop_visual.current_target is None

    def test_destroyed_model_drop_is_noop_without_state(
        self,
        adapter: MockLayerStackAdapter,
        app: _App,
    ) -> None:
        model = LayerModel(adapter, services=app)
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        model.destroy()
        # Drop on a destroyed model short-circuits and does not leave
        # indicator state behind.
        model.drop(a, c, -1)
        assert model.drop_visual.current_target is None


# ── _can_move_layer return-tuple copy ───────────────────────────────


class TestCanMoveLayerRejectionReasons:
    """Step 44 changes ``_can_move_layer`` to return ``(ok, reason)``.

    These tests lock the user-facing copy strings so refactors can't
    silently change the tooltip / toast wording.
    """

    def test_accepted_move_returns_none_reason(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        ok, reason = model._can_move_layer(a, c, -1)
        assert ok is True
        assert reason is None

    def test_self_drop_reason(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        ok, reason = model._can_move_layer(a, a, -1)
        assert ok is False
        assert reason == "Cannot drop: source and target are the same row"

    def test_root_drag_reason(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        ok, reason = model._can_move_layer(a, model.root_item, -1)
        assert ok is False
        assert reason == (
            "Cannot drop: root and session layers cannot be moved"
        )

    def test_between_drop_on_top_level_reason(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        ok, reason = model._can_move_layer(model.root_item, a, 0)
        assert ok is False
        assert reason == (
            "Cannot drop: top-level rows cannot accept a between-drop"
        )

    def test_circular_reason(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        nested = model._items_by_id["./nested.usda"]
        ok, reason = model._can_move_layer(nested, a, -1)
        assert ok is False
        assert reason == "Cannot drop: would create circular reference"

    def test_locked_target_reason(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        adapter.set_lock("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        ok, reason = model._can_move_layer(a, b, -1)
        assert ok is False
        assert reason == "Cannot drop: target layer is locked"

    def test_muted_target_reason(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        adapter.set_mute("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        ok, reason = model._can_move_layer(a, b, -1)
        assert ok is False
        assert reason == "Cannot drop: target layer is muted"
