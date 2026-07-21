# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the sublayer commands (LAYERS-PLAN Step 30 / Step 31 / Step 31a):

- :class:`CreateSublayerCommand`
- :class:`InsertSublayerCommand`
- :class:`RemoveSublayerCommand`
- :class:`MoveSublayerCommand`
- :class:`ReplaceSublayerCommand`
- :class:`RemovePrimSpecsCommand`

Each command is exercised in isolation (do / undo / redo round-trip)
and via :class:`~ovui_widgets.common.undo.UndoManager` so the ``Ctrl+Z`` pipeline
verify-bullet from the plan is pinned end-to-end.
:class:`RemoveSublayerCommand` additionally checks the mute + lock +
edit-target snapshot-and-restore contract that the plan calls out.
:class:`MoveSublayerCommand` covers same-parent reorder (including
the destination-index adjustment across a pop-then-insert) and
cross-parent relocation.
:class:`ReplaceSublayerCommand` verifies the atomic single-event
replace and the do/undo/redo round-trip against the plan's bullet
``[A, B, C] → replace B with D → [A, D, C]``.
:class:`RemovePrimSpecsCommand` confirms the export-snapshot-restore
round-trip described in LAYERS-PLAN Step 31a.
"""

from __future__ import annotations

import pytest
from ovui_data_adapters.common import LayerEventType

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers.commands import (
    AbstractLayerCommand,
    CreateSublayerCommand,
    InsertSublayerCommand,
    MoveSublayerCommand,
    RemovePrimSpecsCommand,
    RemoveSublayerCommand,
    ReplaceSublayerCommand,
)

# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    """Fresh mock adapter with root + session (no sublayers by default)."""
    return MockLayerStackAdapter(include_session=True)


@pytest.fixture
def adapter_with_sub() -> MockLayerStackAdapter:
    """Mock adapter with root + session + one existing sublayer."""
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./existing.usda")
    return adapter


@pytest.fixture
def bus() -> SelectionBus:
    """Independent SelectionBus — no singleton pollution across tests."""
    return SelectionBus()


@pytest.fixture
def manager() -> UndoManager:
    """Fresh undo stack per test."""
    return UndoManager()


# ─── CreateSublayerCommand ──────────────────────────────────────────────────


class TestCreateSublayerCommand:

    def test_is_subclass_of_base(self) -> None:
        assert issubclass(CreateSublayerCommand, AbstractLayerCommand)

    def test_do_creates_sublayer(self, adapter, bus) -> None:
        cmd = CreateSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./new.usda"
        )
        cmd.do()
        children = adapter.get_sublayer_identifiers(adapter.get_root_layer())
        assert "./new.usda" in children

    def test_do_stores_created_identifier(self, adapter, bus) -> None:
        cmd = CreateSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./new.usda"
        )
        cmd.do()
        assert cmd._created_identifier == "./new.usda"

    def test_do_anonymous_mints_identifier(self, adapter, bus) -> None:
        cmd = CreateSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, ""
        )
        cmd.do()
        assert cmd._created_identifier is not None
        assert cmd._created_identifier.startswith("anon:")
        layer = adapter.find_layer(cmd._created_identifier)
        assert layer is not None
        assert adapter.is_anonymous(layer)

    def test_undo_removes_sublayer(self, adapter, bus) -> None:
        cmd = CreateSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./new.usda"
        )
        cmd.do()
        assert "./new.usda" in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )
        cmd.undo()
        assert "./new.usda" not in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )

    def test_redo_reinserts_same_identifier(self, adapter, bus) -> None:
        # Redo must not mint a second layer record — the identifier
        # captured during the first do is reused.
        cmd = CreateSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./new.usda"
        )
        cmd.do()
        original_id = cmd._created_identifier
        cmd.undo()
        cmd.redo()
        assert cmd._created_identifier == original_id
        assert "./new.usda" in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )

    def test_redo_anonymous_does_not_drift(self, adapter, bus) -> None:
        # Anonymous re-create would mint a fresh ``anon:N``; the redo
        # path insert-by-identifier must reuse the original.
        cmd = CreateSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, ""
        )
        cmd.do()
        minted = cmd._created_identifier
        assert minted is not None
        cmd.undo()
        cmd.redo()
        assert cmd._created_identifier == minted
        assert minted in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )

    def test_create_at_specific_position(self, adapter_with_sub, bus) -> None:
        cmd = CreateSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0, "./front.usda"
        )
        cmd.do()
        children = adapter_with_sub.get_sublayer_identifiers(
            adapter_with_sub.get_root_layer()
        )
        assert children[0] == "./front.usda"
        assert children[1] == "./existing.usda"

    def test_undo_when_peer_shifted_sublayers(self, adapter, bus) -> None:
        # If a peer command re-orders siblings between do and undo, the
        # command must find the created identifier by name rather than
        # by the index it was inserted at.
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./a.usda")
        cmd = CreateSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./b.usda"
        )
        cmd.do()
        # Peer inserts a new sublayer at the front, shifting b's index.
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, 0, "./peer.usda")
        cmd.undo()
        children = adapter.get_sublayer_identifiers(adapter.get_root_layer())
        assert "./b.usda" not in children
        assert "./a.usda" in children
        assert "./peer.usda" in children

    def test_do_fires_sublayers_changed_event(self, adapter, bus) -> None:
        events: list = []
        sub = adapter.subscribe_events(lambda e: events.append(e))  # noqa: F841
        cmd = CreateSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./new.usda"
        )
        cmd.do()
        sublayer_events = [
            e
            for e in events
            if e.event_type == LayerEventType.SUBLAYERS_CHANGED
        ]
        assert len(sublayer_events) == 1
        assert sublayer_events[0].identifiers == (ROOT_LAYER_IDENTIFIER,)


# ─── InsertSublayerCommand ──────────────────────────────────────────────────


class TestInsertSublayerCommand:

    def test_is_subclass_of_base(self) -> None:
        assert issubclass(InsertSublayerCommand, AbstractLayerCommand)

    def test_do_inserts_existing_path(self, adapter, bus) -> None:
        cmd = InsertSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./existing.usda"
        )
        cmd.do()
        assert "./existing.usda" in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )

    def test_undo_removes_inserted_sublayer(self, adapter, bus) -> None:
        cmd = InsertSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./existing.usda"
        )
        cmd.do()
        cmd.undo()
        assert "./existing.usda" not in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )

    def test_redo_reinserts(self, adapter, bus) -> None:
        cmd = InsertSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./existing.usda"
        )
        cmd.do()
        cmd.undo()
        cmd.redo()
        assert "./existing.usda" in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )

    def test_insert_at_specific_position(self, adapter_with_sub, bus) -> None:
        cmd = InsertSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0, "./front.usda"
        )
        cmd.do()
        children = adapter_with_sub.get_sublayer_identifiers(
            adapter_with_sub.get_root_layer()
        )
        assert children[0] == "./front.usda"

    def test_undo_when_peer_shifted_sublayers(self, adapter, bus) -> None:
        cmd = InsertSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./target.usda"
        )
        cmd.do()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, 0, "./peer.usda")
        cmd.undo()
        children = adapter.get_sublayer_identifiers(adapter.get_root_layer())
        assert "./target.usda" not in children
        assert "./peer.usda" in children


# ─── RemoveSublayerCommand ──────────────────────────────────────────────────


class TestRemoveSublayerCommand:

    def test_is_subclass_of_base(self) -> None:
        assert issubclass(RemoveSublayerCommand, AbstractLayerCommand)

    def test_do_removes_sublayer(self, adapter_with_sub, bus) -> None:
        cmd = RemoveSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0
        )
        cmd.do()
        children = adapter_with_sub.get_sublayer_identifiers(
            adapter_with_sub.get_root_layer()
        )
        assert "./existing.usda" not in children

    def test_do_stores_removed_identifier(self, adapter_with_sub, bus) -> None:
        cmd = RemoveSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0
        )
        cmd.do()
        assert cmd._removed_identifier == "./existing.usda"

    def test_undo_restores_at_same_index(self, adapter, bus) -> None:
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./a.usda")
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./b.usda")
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./c.usda")

        # Remove the middle one.
        cmd = RemoveSublayerCommand(adapter, bus, ROOT_LAYER_IDENTIFIER, 1)
        cmd.do()
        children = adapter.get_sublayer_identifiers(adapter.get_root_layer())
        assert children == ["./a.usda", "./c.usda"]

        cmd.undo()
        children = adapter.get_sublayer_identifiers(adapter.get_root_layer())
        assert children == ["./a.usda", "./b.usda", "./c.usda"]

    def test_redo_reapplies(self, adapter_with_sub, bus) -> None:
        cmd = RemoveSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0
        )
        cmd.do()
        cmd.undo()
        cmd.redo()
        children = adapter_with_sub.get_sublayer_identifiers(
            adapter_with_sub.get_root_layer()
        )
        assert "./existing.usda" not in children

    def test_undo_restores_mute_state(self, adapter_with_sub, bus) -> None:
        adapter_with_sub.set_mute("./existing.usda", True)
        cmd = RemoveSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0
        )
        cmd.do()
        cmd.undo()
        layer = adapter_with_sub.find_layer("./existing.usda")
        assert layer is not None
        assert adapter_with_sub.is_muted(layer) is True

    def test_undo_restores_lock_state(self, adapter_with_sub, bus) -> None:
        adapter_with_sub.set_lock("./existing.usda", True)
        cmd = RemoveSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0
        )
        cmd.do()
        cmd.undo()
        layer = adapter_with_sub.find_layer("./existing.usda")
        assert layer is not None
        assert adapter_with_sub.is_locked(layer) is True

    def test_do_switches_edit_target_to_root_when_removing_edit_target(
        self, adapter_with_sub, bus
    ) -> None:
        adapter_with_sub.set_edit_target("./existing.usda")
        assert (
            adapter_with_sub.get_edit_target_identifier() == "./existing.usda"
        )
        cmd = RemoveSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0
        )
        cmd.do()
        assert (
            adapter_with_sub.get_edit_target_identifier()
            == ROOT_LAYER_IDENTIFIER
        )

    def test_undo_restores_edit_target_when_it_was_removed(
        self, adapter_with_sub, bus
    ) -> None:
        adapter_with_sub.set_edit_target("./existing.usda")
        cmd = RemoveSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0
        )
        cmd.do()
        cmd.undo()
        # Base class's _restore_state flips the edit target back once
        # the layer is reinserted and writable again.
        assert (
            adapter_with_sub.get_edit_target_identifier()
            == "./existing.usda"
        )

    def test_do_does_not_touch_edit_target_when_unrelated(
        self, adapter_with_sub, bus
    ) -> None:
        # Edit target is root, we remove the child — no re-target
        # should fire during do.
        events: list = []
        sub = adapter_with_sub.subscribe_events(  # noqa: F841
            lambda e: events.append(e)
        )
        cmd = RemoveSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0
        )
        cmd.do()
        target_events = [
            e
            for e in events
            if e.event_type == LayerEventType.EDIT_TARGET_CHANGED
        ]
        assert target_events == []

    def test_out_of_range_position_raises(self, adapter, bus) -> None:
        cmd = RemoveSublayerCommand(adapter, bus, ROOT_LAYER_IDENTIFIER, 5)
        with pytest.raises(IndexError):
            cmd.do()

    def test_unknown_parent_raises(self, adapter, bus) -> None:
        cmd = RemoveSublayerCommand(adapter, bus, "@nope@", 0)
        with pytest.raises(KeyError):
            cmd.do()


# ─── UndoManager integration ────────────────────────────────────────────────


class TestUndoManagerIntegration:
    """End-to-end: push through the real :class:`UndoManager` so the
    ``Ctrl+Z`` verify-bullet from the plan is covered."""

    def test_create_then_undo(self, adapter, bus, manager) -> None:
        cmd = CreateSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./new.usda"
        )
        manager.push(cmd)
        assert "./new.usda" in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )
        assert manager.undo() is True
        assert "./new.usda" not in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )

    def test_create_undo_redo_roundtrip(self, adapter, bus, manager) -> None:
        cmd = CreateSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./new.usda"
        )
        manager.push(cmd)
        manager.undo()
        assert manager.redo() is True
        assert "./new.usda" in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )

    def test_insert_then_undo(self, adapter, bus, manager) -> None:
        cmd = InsertSublayerCommand(
            adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./existing.usda"
        )
        manager.push(cmd)
        assert "./existing.usda" in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )
        assert manager.undo() is True
        assert "./existing.usda" not in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )

    def test_remove_then_undo(self, adapter_with_sub, bus, manager) -> None:
        cmd = RemoveSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0
        )
        manager.push(cmd)
        assert "./existing.usda" not in adapter_with_sub.get_sublayer_identifiers(
            adapter_with_sub.get_root_layer()
        )
        assert manager.undo() is True
        assert "./existing.usda" in adapter_with_sub.get_sublayer_identifiers(
            adapter_with_sub.get_root_layer()
        )

    def test_remove_undo_redo_roundtrip(
        self, adapter_with_sub, bus, manager
    ) -> None:
        cmd = RemoveSublayerCommand(
            adapter_with_sub, bus, ROOT_LAYER_IDENTIFIER, 0
        )
        manager.push(cmd)
        manager.undo()
        assert manager.redo() is True
        assert "./existing.usda" not in adapter_with_sub.get_sublayer_identifiers(
            adapter_with_sub.get_root_layer()
        )

    def test_stacked_create_and_remove_unwind_in_reverse(
        self, adapter, bus, manager
    ) -> None:
        manager.push(
            CreateSublayerCommand(
                adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./a.usda"
            )
        )
        manager.push(
            CreateSublayerCommand(
                adapter, bus, ROOT_LAYER_IDENTIFIER, -1, "./b.usda"
            )
        )
        manager.push(
            RemoveSublayerCommand(adapter, bus, ROOT_LAYER_IDENTIFIER, 0)
        )
        # Undo remove → back to [a, b]
        manager.undo()
        children = adapter.get_sublayer_identifiers(adapter.get_root_layer())
        assert children == ["./a.usda", "./b.usda"]
        # Undo create b → [a]
        manager.undo()
        children = adapter.get_sublayer_identifiers(adapter.get_root_layer())
        assert children == ["./a.usda"]
        # Undo create a → []
        manager.undo()
        children = adapter.get_sublayer_identifiers(adapter.get_root_layer())
        assert children == []


# ─── MoveSublayerCommand ────────────────────────────────────────────────────


@pytest.fixture
def adapter_abc() -> MockLayerStackAdapter:
    """Mock adapter with root + ``[./a.usda, ./b.usda, ./c.usda]``."""
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./a.usda")
    adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./b.usda")
    adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./c.usda")
    return adapter


@pytest.fixture
def adapter_two_parents() -> MockLayerStackAdapter:
    """Mock adapter with two parents, each holding one sublayer.

    Layout::

        root
        ├─ ./parent_a.usda
        │   └─ ./child_a.usda
        └─ ./parent_b.usda
            └─ ./child_b.usda
    """
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./parent_a.usda")
    adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./parent_b.usda")
    adapter.create_sublayer("./parent_a.usda", -1, "./child_a.usda")
    adapter.create_sublayer("./parent_b.usda", -1, "./child_b.usda")
    return adapter


class TestMoveSublayerCommand:

    def test_is_subclass_of_base(self) -> None:
        assert issubclass(MoveSublayerCommand, AbstractLayerCommand)

    def test_same_parent_forward_reorder(self, adapter_abc, bus) -> None:
        # Move A (pos 0) forward to pos 2 in [A, B, C]. The adapter's
        # pop-then-insert settles A between B and C.
        cmd = MoveSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 0,
            ROOT_LAYER_IDENTIFIER, 2,
        )
        cmd.do()
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./b.usda", "./a.usda", "./c.usda"]

    def test_same_parent_backward_reorder(self, adapter_abc, bus) -> None:
        # Move C (pos 2) backwards to pos 0 in [A, B, C].
        cmd = MoveSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 2,
            ROOT_LAYER_IDENTIFIER, 0,
        )
        cmd.do()
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./c.usda", "./a.usda", "./b.usda"]

    def test_do_stores_moved_identifier(self, adapter_abc, bus) -> None:
        cmd = MoveSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 1,
            ROOT_LAYER_IDENTIFIER, 0,
        )
        cmd.do()
        assert cmd._moved_identifier == "./b.usda"

    def test_undo_restores_order(self, adapter_abc, bus) -> None:
        cmd = MoveSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 0,
            ROOT_LAYER_IDENTIFIER, 2,
        )
        cmd.do()
        cmd.undo()
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./a.usda", "./b.usda", "./c.usda"]

    def test_redo_reapplies(self, adapter_abc, bus) -> None:
        cmd = MoveSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 0,
            ROOT_LAYER_IDENTIFIER, 2,
        )
        cmd.do()
        cmd.undo()
        cmd.redo()
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./b.usda", "./a.usda", "./c.usda"]

    def test_undo_after_backward_reorder(self, adapter_abc, bus) -> None:
        # Backward same-parent moves hit the adapter's
        # ``to_position -= 1`` index-shift during undo — the command
        # pre-inflates the target position to compensate.
        cmd = MoveSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 2,
            ROOT_LAYER_IDENTIFIER, 0,
        )
        cmd.do()
        assert adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        ) == ["./c.usda", "./a.usda", "./b.usda"]
        cmd.undo()
        assert adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        ) == ["./a.usda", "./b.usda", "./c.usda"]

    def test_redo_after_backward_reorder(self, adapter_abc, bus) -> None:
        cmd = MoveSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 2,
            ROOT_LAYER_IDENTIFIER, 0,
        )
        cmd.do()
        cmd.undo()
        cmd.redo()
        assert adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        ) == ["./c.usda", "./a.usda", "./b.usda"]

    def test_cross_parent_move(self, adapter_two_parents, bus) -> None:
        # Move ./child_a.usda from parent_a → parent_b (append).
        cmd = MoveSublayerCommand(
            adapter_two_parents, bus,
            "./parent_a.usda", 0,
            "./parent_b.usda", -1,
        )
        cmd.do()
        parent_a_handle = adapter_two_parents.find_layer("./parent_a.usda")
        parent_b_handle = adapter_two_parents.find_layer("./parent_b.usda")
        assert adapter_two_parents.get_sublayer_identifiers(
            parent_a_handle
        ) == []
        assert adapter_two_parents.get_sublayer_identifiers(
            parent_b_handle
        ) == ["./child_b.usda", "./child_a.usda"]

    def test_cross_parent_undo_restores(
        self, adapter_two_parents, bus
    ) -> None:
        cmd = MoveSublayerCommand(
            adapter_two_parents, bus,
            "./parent_a.usda", 0,
            "./parent_b.usda", -1,
        )
        cmd.do()
        cmd.undo()
        parent_a_handle = adapter_two_parents.find_layer("./parent_a.usda")
        parent_b_handle = adapter_two_parents.find_layer("./parent_b.usda")
        assert adapter_two_parents.get_sublayer_identifiers(
            parent_a_handle
        ) == ["./child_a.usda"]
        assert adapter_two_parents.get_sublayer_identifiers(
            parent_b_handle
        ) == ["./child_b.usda"]

    def test_cross_parent_redo(self, adapter_two_parents, bus) -> None:
        cmd = MoveSublayerCommand(
            adapter_two_parents, bus,
            "./parent_a.usda", 0,
            "./parent_b.usda", 0,
        )
        cmd.do()
        cmd.undo()
        cmd.redo()
        parent_a_handle = adapter_two_parents.find_layer("./parent_a.usda")
        parent_b_handle = adapter_two_parents.find_layer("./parent_b.usda")
        assert adapter_two_parents.get_sublayer_identifiers(
            parent_a_handle
        ) == []
        assert adapter_two_parents.get_sublayer_identifiers(
            parent_b_handle
        ) == ["./child_a.usda", "./child_b.usda"]

    def test_noop_move_is_undoable(self, adapter_abc, bus) -> None:
        # Moving pos 1 → pos 1 (same parent) is a no-op, but the
        # command should still round-trip cleanly.
        cmd = MoveSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 1,
            ROOT_LAYER_IDENTIFIER, 1,
        )
        cmd.do()
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./a.usda", "./b.usda", "./c.usda"]
        cmd.undo()
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./a.usda", "./b.usda", "./c.usda"]

    def test_unknown_parent_raises(self, adapter, bus) -> None:
        cmd = MoveSublayerCommand(
            adapter, bus, "@nope@", 0, ROOT_LAYER_IDENTIFIER, 0
        )
        with pytest.raises(KeyError):
            cmd.do()

    def test_out_of_range_from_position_raises(
        self, adapter_abc, bus
    ) -> None:
        cmd = MoveSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 7,
            ROOT_LAYER_IDENTIFIER, 0,
        )
        with pytest.raises(IndexError):
            cmd.do()

    def test_do_fires_sublayers_changed_event_once_per_parent(
        self, adapter_two_parents, bus
    ) -> None:
        events: list = []
        sub = adapter_two_parents.subscribe_events(  # noqa: F841
            lambda e: events.append(e)
        )
        cmd = MoveSublayerCommand(
            adapter_two_parents, bus,
            "./parent_a.usda", 0,
            "./parent_b.usda", -1,
        )
        cmd.do()
        sublayer_events = [
            e
            for e in events
            if e.event_type == LayerEventType.SUBLAYERS_CHANGED
        ]
        touched = sorted(
            e.identifiers[0] for e in sublayer_events if e.identifiers
        )
        assert touched == ["./parent_a.usda", "./parent_b.usda"]

    def test_undo_handles_post_do_peer_reorder(self, adapter_abc, bus) -> None:
        # Move A from pos 0 to pos 2 → [B, A, C]. A peer then swaps
        # A and C (insert D between). Undo must still locate A by
        # identifier, not by stored ``to_position``.
        cmd = MoveSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 0,
            ROOT_LAYER_IDENTIFIER, 2,
        )
        cmd.do()
        adapter_abc.create_sublayer(
            ROOT_LAYER_IDENTIFIER, 0, "./peer.usda"
        )
        # Now children == [peer, B, A, C]; A has shifted from pos 1
        # to pos 2. Undo should still move A back to pos 0.
        cmd.undo()
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children[0] == "./a.usda"
        assert "./peer.usda" in children

    def test_undo_manager_integration(
        self, adapter_abc, bus, manager
    ) -> None:
        cmd = MoveSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 0,
            ROOT_LAYER_IDENTIFIER, 2,
        )
        manager.push(cmd)
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./b.usda", "./a.usda", "./c.usda"]
        assert manager.undo() is True
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./a.usda", "./b.usda", "./c.usda"]
        assert manager.redo() is True
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./b.usda", "./a.usda", "./c.usda"]


# ─── ReplaceSublayerCommand ─────────────────────────────────────────────────


class TestReplaceSublayerCommand:

    def test_is_subclass_of_base(self) -> None:
        assert issubclass(ReplaceSublayerCommand, AbstractLayerCommand)

    def test_do_swaps_entry(self, adapter_abc, bus) -> None:
        cmd = ReplaceSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 1, "./d.usda"
        )
        cmd.do()
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./a.usda", "./d.usda", "./c.usda"]

    def test_do_stores_old_identifier(self, adapter_abc, bus) -> None:
        cmd = ReplaceSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 1, "./d.usda"
        )
        cmd.do()
        assert cmd._old_identifier == "./b.usda"

    def test_undo_restores_original(self, adapter_abc, bus) -> None:
        cmd = ReplaceSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 1, "./d.usda"
        )
        cmd.do()
        cmd.undo()
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./a.usda", "./b.usda", "./c.usda"]

    def test_redo_reapplies(self, adapter_abc, bus) -> None:
        cmd = ReplaceSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 1, "./d.usda"
        )
        cmd.do()
        cmd.undo()
        cmd.redo()
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./a.usda", "./d.usda", "./c.usda"]

    def test_redo_does_not_overwrite_old_identifier(
        self, adapter_abc, bus
    ) -> None:
        # Redo re-reads the current slot (now containing ``./d.usda``)
        # but must leave ``_old_identifier`` anchored at ``./b.usda``
        # so the next undo still restores the original.
        cmd = ReplaceSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 1, "./d.usda"
        )
        cmd.do()
        cmd.undo()
        cmd.redo()
        assert cmd._old_identifier == "./b.usda"
        cmd.undo()
        children = adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        )
        assert children == ["./a.usda", "./b.usda", "./c.usda"]

    def test_do_fires_single_sublayers_changed_event(
        self, adapter_abc, bus
    ) -> None:
        events: list = []
        sub = adapter_abc.subscribe_events(  # noqa: F841
            lambda e: events.append(e)
        )
        cmd = ReplaceSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 1, "./d.usda"
        )
        cmd.do()
        sublayer_events = [
            e
            for e in events
            if e.event_type == LayerEventType.SUBLAYERS_CHANGED
        ]
        # One event, not two — the adapter's replace_sublayer is atomic
        # (not remove + insert).
        assert len(sublayer_events) == 1
        assert sublayer_events[0].identifiers == (ROOT_LAYER_IDENTIFIER,)

    def test_out_of_range_position_raises(self, adapter_abc, bus) -> None:
        cmd = ReplaceSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 99, "./d.usda"
        )
        with pytest.raises(IndexError):
            cmd.do()

    def test_unknown_parent_raises(self, adapter_abc, bus) -> None:
        cmd = ReplaceSublayerCommand(
            adapter_abc, bus, "./nonexistent.usda", 0, "./d.usda"
        )
        with pytest.raises(KeyError):
            cmd.do()

    def test_undo_manager_integration(
        self, adapter_abc, bus, manager
    ) -> None:
        cmd = ReplaceSublayerCommand(
            adapter_abc, bus, ROOT_LAYER_IDENTIFIER, 1, "./d.usda"
        )
        manager.push(cmd)
        assert adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        ) == ["./a.usda", "./d.usda", "./c.usda"]
        assert manager.undo() is True
        assert adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        ) == ["./a.usda", "./b.usda", "./c.usda"]
        assert manager.redo() is True
        assert adapter_abc.get_sublayer_identifiers(
            adapter_abc.get_root_layer()
        ) == ["./a.usda", "./d.usda", "./c.usda"]


# ─── RemovePrimSpecsCommand ─────────────────────────────────────────────────


@pytest.fixture
def adapter_with_prim_specs() -> MockLayerStackAdapter:
    """Mock adapter with one sublayer carrying two prim specs."""
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./layer1.usda")
    adapter.set_prim_spec("./layer1.usda", "/World/Cube", "<cube-usda>")
    adapter.set_prim_spec("./layer1.usda", "/World/Sphere", "<sphere-usda>")
    return adapter


class TestRemovePrimSpecsCommand:

    def test_is_subclass_of_base(self) -> None:
        assert issubclass(RemovePrimSpecsCommand, AbstractLayerCommand)

    def test_do_removes_single_spec(
        self, adapter_with_prim_specs, bus
    ) -> None:
        cmd = RemovePrimSpecsCommand(
            adapter_with_prim_specs, bus,
            [("./layer1.usda", "/World/Cube")],
        )
        cmd.do()
        with pytest.raises(KeyError):
            adapter_with_prim_specs.export_prim_spec(
                "./layer1.usda", "/World/Cube"
            )
        # The other spec is untouched.
        assert (
            adapter_with_prim_specs.export_prim_spec(
                "./layer1.usda", "/World/Sphere"
            )
            == "<sphere-usda>"
        )

    def test_undo_restores_bit_identical_snapshot(
        self, adapter_with_prim_specs, bus
    ) -> None:
        cmd = RemovePrimSpecsCommand(
            adapter_with_prim_specs, bus,
            [("./layer1.usda", "/World/Cube")],
        )
        cmd.do()
        cmd.undo()
        assert (
            adapter_with_prim_specs.export_prim_spec(
                "./layer1.usda", "/World/Cube"
            )
            == "<cube-usda>"
        )

    def test_redo_reapplies_removal(
        self, adapter_with_prim_specs, bus
    ) -> None:
        cmd = RemovePrimSpecsCommand(
            adapter_with_prim_specs, bus,
            [("./layer1.usda", "/World/Cube")],
        )
        cmd.do()
        cmd.undo()
        cmd.redo()
        with pytest.raises(KeyError):
            adapter_with_prim_specs.export_prim_spec(
                "./layer1.usda", "/World/Cube"
            )

    def test_do_stores_snapshots(
        self, adapter_with_prim_specs, bus
    ) -> None:
        cmd = RemovePrimSpecsCommand(
            adapter_with_prim_specs, bus,
            [
                ("./layer1.usda", "/World/Cube"),
                ("./layer1.usda", "/World/Sphere"),
            ],
        )
        cmd.do()
        assert cmd._snapshots == [
            ("./layer1.usda", "/World/Cube", "<cube-usda>"),
            ("./layer1.usda", "/World/Sphere", "<sphere-usda>"),
        ]

    def test_batch_across_layers(self, adapter, bus) -> None:
        # Two layers, one spec each → remove both in one command,
        # undo restores both.
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./l1.usda")
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./l2.usda")
        adapter.set_prim_spec("./l1.usda", "/A", "a-blob")
        adapter.set_prim_spec("./l2.usda", "/B", "b-blob")
        cmd = RemovePrimSpecsCommand(
            adapter, bus,
            [("./l1.usda", "/A"), ("./l2.usda", "/B")],
        )
        cmd.do()
        with pytest.raises(KeyError):
            adapter.export_prim_spec("./l1.usda", "/A")
        with pytest.raises(KeyError):
            adapter.export_prim_spec("./l2.usda", "/B")
        cmd.undo()
        assert adapter.export_prim_spec("./l1.usda", "/A") == "a-blob"
        assert adapter.export_prim_spec("./l2.usda", "/B") == "b-blob"

    def test_undo_walks_reverse_order(
        self, adapter_with_prim_specs, bus
    ) -> None:
        # Restore order must be the reverse of remove order so a
        # deeply nested spec lands after its parent has been rebuilt.
        adapter_with_prim_specs.set_prim_spec(
            "./layer1.usda", "/World/Cube/Shader", "<shader-usda>"
        )
        cmd = RemovePrimSpecsCommand(
            adapter_with_prim_specs, bus,
            [
                ("./layer1.usda", "/World/Cube"),
                ("./layer1.usda", "/World/Cube/Shader"),
            ],
        )
        cmd.do()
        # Track import order by subscribing to DIRTY_STATE_CHANGED +
        # observing the prim_specs dict at each undo step. Instead of
        # instrumenting the adapter, verify the snapshots list is
        # walked reverse by spying on import_prim_spec.
        call_order: list = []
        original = adapter_with_prim_specs.import_prim_spec

        def spy(layer_id, path, usda):
            call_order.append((layer_id, path))
            original(layer_id, path, usda)

        adapter_with_prim_specs.import_prim_spec = spy  # type: ignore[method-assign]
        cmd.undo()
        assert call_order == [
            ("./layer1.usda", "/World/Cube/Shader"),
            ("./layer1.usda", "/World/Cube"),
        ]

    def test_remove_unknown_path_raises(
        self, adapter_with_prim_specs, bus
    ) -> None:
        cmd = RemovePrimSpecsCommand(
            adapter_with_prim_specs, bus,
            [("./layer1.usda", "/Nonexistent")],
        )
        with pytest.raises(KeyError):
            cmd.do()

    def test_do_fires_dirty_state_events(
        self, adapter_with_prim_specs, bus
    ) -> None:
        events: list = []
        sub = adapter_with_prim_specs.subscribe_events(  # noqa: F841
            lambda e: events.append(e)
        )
        cmd = RemovePrimSpecsCommand(
            adapter_with_prim_specs, bus,
            [("./layer1.usda", "/World/Cube")],
        )
        cmd.do()
        dirty_events = [
            e
            for e in events
            if e.event_type == LayerEventType.DIRTY_STATE_CHANGED
            and e.identifiers == ("./layer1.usda",)
        ]
        assert len(dirty_events) == 1

    def test_entries_copied_from_caller_list(
        self, adapter_with_prim_specs, bus
    ) -> None:
        # Mutating the caller's list after constructing the command
        # must not affect what the command removes.
        entries = [("./layer1.usda", "/World/Cube")]
        cmd = RemovePrimSpecsCommand(adapter_with_prim_specs, bus, entries)
        entries.append(("./layer1.usda", "/World/Sphere"))
        cmd.do()
        with pytest.raises(KeyError):
            adapter_with_prim_specs.export_prim_spec(
                "./layer1.usda", "/World/Cube"
            )
        # The sphere spec survives because it wasn't in the command's
        # own copy of the entries list.
        assert (
            adapter_with_prim_specs.export_prim_spec(
                "./layer1.usda", "/World/Sphere"
            )
            == "<sphere-usda>"
        )

    def test_undo_manager_integration(
        self, adapter_with_prim_specs, bus, manager
    ) -> None:
        cmd = RemovePrimSpecsCommand(
            adapter_with_prim_specs, bus,
            [("./layer1.usda", "/World/Cube")],
        )
        manager.push(cmd)
        with pytest.raises(KeyError):
            adapter_with_prim_specs.export_prim_spec(
                "./layer1.usda", "/World/Cube"
            )
        assert manager.undo() is True
        assert (
            adapter_with_prim_specs.export_prim_spec(
                "./layer1.usda", "/World/Cube"
            )
            == "<cube-usda>"
        )
        assert manager.redo() is True
        with pytest.raises(KeyError):
            adapter_with_prim_specs.export_prim_spec(
                "./layer1.usda", "/World/Cube"
            )
