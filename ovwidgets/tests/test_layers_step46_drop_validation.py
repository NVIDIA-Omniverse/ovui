# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 46 — Drop validation edge cases.

Step 46 rounds out :meth:`LayerModel._can_move_layer` with the corner
cases surfaced during Step 43-45 exercise:

- Source or target layer was removed from the adapter mid-drag.
- Source (or source's parent) was locked between drag-start and
  drop-release.
- A between-drop that resolves to the source's current slot (no-op).
- Self-drop (already rejected in Step 43; pinned here against
  regression).
- Drop on direct parent at the same slot (no-op guard).
- Anonymous layers — the session layer is pinned by ``parent is None``
  while anonymous sublayers follow the normal lock / mute rules.

Every rejection returns a human-readable ``reason`` so the Step 44
drop-visual controller (and the Step 44 error-reporter toast) surface
why the gesture failed. Coverage pairs a ``drop_accepted`` assertion
with a ``drop`` assertion that no command lands on the undo stack —
rejections must never produce silent mutations.
"""

from __future__ import annotations

import pytest

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_layer_stack import (
    ROOT_LAYER_IDENTIFIER,
    SESSION_LAYER_IDENTIFIER,
)
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import LayerModel


class _App:
    """Minimal :class:`Application` stand-in — shared with Step 43/44/45."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    # Same tree shape as Step 43 for reuse of the canonical sample:
    #   root
    #     ├── ./a.usda
    #     │     └── ./nested.usda
    #     ├── ./b.usda
    #     └── ./c.usda
    #   session
    #     └── ./s.usda
    ad = MockLayerStackAdapter(include_session=True)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./a.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./b.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./c.usda")
    ad.add_sublayer("./a.usda", "./nested.usda")
    ad.add_sublayer(SESSION_LAYER_IDENTIFIER, "./s.usda")
    return ad


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def model(adapter: MockLayerStackAdapter, app: _App) -> LayerModel:
    m = LayerModel(adapter, services=app)
    yield m
    m.destroy()


# ── Stale source / target ───────────────────────────────────────────


class TestStaleLayersEdgeCase:
    """A peer command tore the tree down while the drag was in flight."""

    def test_stale_target_rejects_cleanly(
        self, adapter: MockLayerStackAdapter, model: LayerModel
    ) -> None:
        # Capture the target LayerItem, then simulate the target layer
        # being removed from the adapter mid-drag by deleting it from
        # the mock's internal layer dict. The tree-side LayerItem is
        # still a live Python ref — without the Step 46 guard its
        # ``is_writable`` read would raise ``KeyError`` through
        # ``_require`` and propagate up through ovui.
        b = model._items_by_id["./b.usda"]
        c = model._items_by_id["./c.usda"]
        # Remove ./b.usda from the adapter's layer map.
        del adapter._layers["./b.usda"]
        ok, reason = model._can_move_layer(b, c, -1)
        assert ok is False
        assert reason is not None
        assert "no longer exists" in reason

    def test_stale_source_rejects_cleanly(
        self, adapter: MockLayerStackAdapter, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        c = model._items_by_id["./c.usda"]
        del adapter._layers["./c.usda"]
        ok, reason = model._can_move_layer(a, c, -1)
        assert ok is False
        assert reason is not None
        assert "no longer exists" in reason

    def test_stale_target_drop_pushes_no_command(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        b = model._items_by_id["./b.usda"]
        c = model._items_by_id["./c.usda"]
        del adapter._layers["./b.usda"]
        # Should not raise and should not push any command.
        model.drop(b, c, -1)
        assert app.undo_manager.can_undo() is False


# ── Source lock / source-parent lock ────────────────────────────────


class TestSourceLockEdgeCase:
    """Source locked between drag-start and drop-release rejects the drop."""

    def test_locked_source_rejects(
        self, adapter: MockLayerStackAdapter, model: LayerModel
    ) -> None:
        # Lock ./c.usda after the model built — mirrors the user
        # toggling the lock column while holding a drag.
        adapter.set_lock("./c.usda", True)
        model._items_by_id["./c.usda"].invalidate_flags()
        b = model._items_by_id["./b.usda"]
        c = model._items_by_id["./c.usda"]
        ok, reason = model._can_move_layer(b, c, -1)
        assert ok is False
        assert reason == "Cannot move locked layer"

    def test_locked_source_parent_rejects(
        self, adapter: MockLayerStackAdapter, model: LayerModel
    ) -> None:
        # Lock ./a.usda — ./nested.usda sits underneath and inherits
        # the "cannot be removed from a locked parent" restriction.
        adapter.set_lock("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        model._items_by_id["./nested.usda"].invalidate_flags()
        b = model._items_by_id["./b.usda"]
        nested = model._items_by_id["./nested.usda"]
        ok, reason = model._can_move_layer(b, nested, -1)
        assert ok is False
        assert reason == "Cannot move locked layer"

    def test_locked_source_drop_pushes_no_command(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        adapter.set_lock("./c.usda", True)
        model._items_by_id["./c.usda"].invalidate_flags()
        b = model._items_by_id["./b.usda"]
        c = model._items_by_id["./c.usda"]
        model.drop(b, c, -1)
        assert app.undo_manager.can_undo() is False

    def test_locked_source_parent_drop_pushes_no_command(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
        app: _App,
    ) -> None:
        adapter.set_lock("./a.usda", True)
        model._items_by_id["./a.usda"].invalidate_flags()
        model._items_by_id["./nested.usda"].invalidate_flags()
        b = model._items_by_id["./b.usda"]
        nested = model._items_by_id["./nested.usda"]
        model.drop(b, nested, -1)
        assert app.undo_manager.can_undo() is False


# ── Self-drop / same-position no-op ─────────────────────────────────


class TestNoOpDropEdgeCase:
    """Self-drop and same-slot reorders are no-ops, not errors."""

    def test_self_drop_onto_rejects(self, model: LayerModel) -> None:
        # Step 43 already covered this; pin it again so a future
        # refactor of _can_move_layer cannot silently lose the check.
        a = model._items_by_id["./a.usda"]
        ok, reason = model._can_move_layer(a, a, -1)
        assert ok is False
        assert reason is not None
        assert "same row" in reason

    def test_self_drop_between_rejects(self, model: LayerModel) -> None:
        a = model._items_by_id["./a.usda"]
        ok, reason = model._can_move_layer(a, a, 0)
        assert ok is False
        assert reason is not None

    def test_between_drop_at_current_slot_rejects(
        self, model: LayerModel
    ) -> None:
        # ./b.usda sits at slot 1 under root. Dropping it back at
        # slot 1 in root's sublayer list (target=./a.usda, the row
        # whose parent is root) is a no-op the user almost certainly
        # didn't mean — pop-then-insert would leave B at slot 1.
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        ok, reason = model._can_move_layer(a, b, 1)
        assert ok is False
        assert reason is not None
        assert "already at this position" in reason

    def test_between_drop_at_current_slot_plus_one_rejects(
        self, model: LayerModel
    ) -> None:
        # Pop-then-insert: ``to_pos == from_pos + 1`` lands at the same
        # slot under the same parent. ./b.usda is at slot 1; slot 2
        # resolves to the same landing spot.
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        ok, reason = model._can_move_layer(a, b, 2)
        assert ok is False
        assert reason is not None
        assert "already at this position" in reason

    def test_between_drop_at_different_slot_accepts(
        self, model: LayerModel
    ) -> None:
        # Slot 0 is a genuine move (B leapfrogs A); must not reject.
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        ok, reason = model._can_move_layer(a, b, 0)
        assert ok is True
        assert reason is None

    def test_same_slot_drop_pushes_no_command(
        self, model: LayerModel, app: _App
    ) -> None:
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        model.drop(a, b, 1)
        assert app.undo_manager.can_undo() is False


# ── Anonymous layer edge cases ──────────────────────────────────────


class TestAnonymousLayerEdgeCase:
    """Anonymous layers — session is pinned, anonymous sublayers move normally."""

    def test_session_layer_drag_rejected(self, model: LayerModel) -> None:
        # The session layer is anonymous (``is_anonymous`` True) and
        # its parent is None, so the Step 43 parent-pin reject fires
        # first. Pin the coverage here so the Step 46 stale / lock
        # guards don't accidentally open a path around the parent
        # check for anonymous rows.
        a = model._items_by_id["./a.usda"]
        session = model.session_item
        assert session is not None
        assert session.is_anonymous is True
        ok, reason = model._can_move_layer(a, session, -1)
        assert ok is False
        assert reason is not None

    def test_anonymous_sublayer_moves_normally(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        # Mint an anonymous sublayer under ./a.usda (empty
        # ``new_layer_path`` mirrors USD's ``Sdf.Layer.CreateAnonymous``).
        # It should move like any other sublayer, subject only to the
        # normal lock / mute rules.
        anon_id = adapter.create_sublayer("./a.usda", -1, "")
        # Let the model pick up the structural change synchronously
        # (headless / no app.call_later scheduler — events flush inline).
        anon = model._items_by_id[anon_id]
        assert anon.is_anonymous is True
        # Drop the anonymous sublayer onto ./b.usda — valid move.
        b = model._items_by_id["./b.usda"]
        ok, reason = model._can_move_layer(b, anon, -1)
        assert ok is True
        assert reason is None

    def test_anonymous_sublayer_respects_source_lock(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        # Locking an anonymous sublayer still blocks the move — the
        # Step 46 lock rule is identifier-agnostic.
        anon_id = adapter.create_sublayer("./a.usda", -1, "")
        adapter.set_lock(anon_id, True)
        anon = model._items_by_id[anon_id]
        anon.invalidate_flags()
        b = model._items_by_id["./b.usda"]
        ok, reason = model._can_move_layer(b, anon, -1)
        assert ok is False
        assert reason == "Cannot move locked layer"


# ── Drop onto direct parent ─────────────────────────────────────────


class TestDropOntoParentEdgeCase:
    """Drop-onto own parent at end is a move-to-end (allowed); same-slot drops reject."""

    def test_drop_onto_own_parent_moves_to_end(
        self,
        adapter: MockLayerStackAdapter,
        model: LayerModel,
    ) -> None:
        # ./a.usda sits at slot 0 under root. Dropping A onto root
        # (drop_location = -1) appends A to root's sublayer list,
        # reordering [A, B, C] → [B, C, A]. Not a no-op — this is a
        # legit move-to-end gesture.
        a = model._items_by_id["./a.usda"]
        ok, reason = model._can_move_layer(model.root_item, a, -1)
        assert ok is True
        assert reason is None

    def test_between_drop_at_current_position_rejects(
        self, model: LayerModel
    ) -> None:
        # Reordering ./b.usda (slot 1 of root) between A and B at
        # slot 1 under root is a no-op. ``_can_move_layer`` rejects
        # with the "already at this position" toast.
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        ok, reason = model._can_move_layer(a, b, 1)
        assert ok is False
        assert reason is not None
        assert "already at this position" in reason


# ── drop_accepted parity ────────────────────────────────────────────


class TestDropAcceptedParity:
    """``drop_accepted`` must agree with ``_can_move_layer`` for every case."""

    def test_drop_accepted_matches_locked_source(
        self, adapter: MockLayerStackAdapter, model: LayerModel
    ) -> None:
        adapter.set_lock("./c.usda", True)
        model._items_by_id["./c.usda"].invalidate_flags()
        b = model._items_by_id["./b.usda"]
        c = model._items_by_id["./c.usda"]
        assert model.drop_accepted(b, c, -1) is False

    def test_drop_accepted_matches_same_position(
        self, model: LayerModel
    ) -> None:
        a = model._items_by_id["./a.usda"]
        b = model._items_by_id["./b.usda"]
        assert model.drop_accepted(a, b, 1) is False

    def test_drop_accepted_matches_stale_target(
        self, adapter: MockLayerStackAdapter, model: LayerModel
    ) -> None:
        b = model._items_by_id["./b.usda"]
        c = model._items_by_id["./c.usda"]
        del adapter._layers["./b.usda"]
        assert model.drop_accepted(b, c, -1) is False
        # Controller holds the rejection reason for the tooltip.
        assert model.drop_visual.rejection_reason is not None
