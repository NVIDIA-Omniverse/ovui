# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Unit tests for UndoManager — Step 58.

Focus areas not fully covered by test_undo.py:
  - IncrCommand pattern adapted to the real Command ABC
  - push() calls do() automatically — caller must NOT also call do()
  - _NullUndoManager.push() does NOT call do() — the asymmetry is critical
  - begin_group without end_group (leaked group): commands execute but never
    land on the undo stack
  - Clear documentation of the push/undo/redo lifecycle

The real base class is Command (not UndoCommand as in pseudocode).
Command requires both do() and undo() as abstract methods.
redo() defaults to do() if not overridden.
"""


from ovui_data_adapters.services.undo import Subscription
from ovui_widgets.common.undo import Command, UndoManager

# ---------------------------------------------------------------------------
# Test command helper (IncrCommand pattern, real API)
# ---------------------------------------------------------------------------


class IncrCommand(Command):
    """Increment a counter by amount on do/redo; decrement on undo."""

    def __init__(self, counter, amount):
        self._counter = counter
        self._amount = amount

    def do(self):
        self._counter[0] += self._amount

    def undo(self):
        self._counter[0] -= self._amount


# ---------------------------------------------------------------------------
# Basic push / undo / redo cycle
# ---------------------------------------------------------------------------


class TestBasicUndoRedo:
    def test_push_calls_do_automatically(self):
        """UndoManager.push() calls cmd.do() — caller must NOT also call do()."""
        mgr = UndoManager()
        counter = [0]
        mgr.push(IncrCommand(counter, 5))
        assert counter[0] == 5  # do() was called once by push()

    def test_undo_reverses_last_command(self):
        mgr = UndoManager()
        counter = [0]
        mgr.push(IncrCommand(counter, 5))
        mgr.undo()
        assert counter[0] == 0

    def test_redo_reapplies_after_undo(self):
        mgr = UndoManager()
        counter = [0]
        mgr.push(IncrCommand(counter, 5))
        mgr.undo()
        mgr.redo()
        assert counter[0] == 5

    def test_push_clears_redo_stack(self):
        """After a new push, redo is no longer possible."""
        mgr = UndoManager()
        counter = [0]
        mgr.push(IncrCommand(counter, 1))
        mgr.undo()
        assert mgr.can_redo()
        mgr.push(IncrCommand(counter, 2))
        assert not mgr.can_redo()
        assert counter[0] == 2

    def test_multiple_undo_redo_cycles(self):
        mgr = UndoManager()
        counter = [0]
        for i in range(1, 4):
            mgr.push(IncrCommand(counter, i))
        assert counter[0] == 6  # 1 + 2 + 3
        mgr.undo()
        assert counter[0] == 3  # undid +3
        mgr.undo()
        assert counter[0] == 1  # undid +2
        mgr.redo()
        assert counter[0] == 3  # redid +2
        mgr.redo()
        assert counter[0] == 6  # redid +3

    def test_undo_on_empty_stack_returns_false(self):
        mgr = UndoManager()
        assert mgr.undo() is False

    def test_redo_on_empty_stack_returns_false(self):
        mgr = UndoManager()
        assert mgr.redo() is False


# ---------------------------------------------------------------------------
# Group operations
# ---------------------------------------------------------------------------


class TestGroupOperations:
    def test_group_undoes_as_single_unit(self):
        """test_group pattern — all commands in a group undo at once."""
        mgr = UndoManager()
        counter = [0]
        mgr.begin_group("batch")
        for _ in range(3):
            mgr.push(IncrCommand(counter, 1))
        mgr.end_group()
        assert counter[0] == 3
        mgr.undo()
        assert counter[0] == 0  # whole group undone at once

    def test_group_redoes_as_single_unit(self):
        mgr = UndoManager()
        counter = [0]
        mgr.begin_group("batch")
        mgr.push(IncrCommand(counter, 10))
        mgr.push(IncrCommand(counter, 5))
        mgr.end_group()
        mgr.undo()
        assert counter[0] == 0
        mgr.redo()
        assert counter[0] == 15

    def test_nested_groups_undo_as_single_unit(self):
        mgr = UndoManager()
        counter = [0]
        mgr.begin_group("outer")
        mgr.push(IncrCommand(counter, 1))
        mgr.begin_group("inner")
        mgr.push(IncrCommand(counter, 2))
        mgr.push(IncrCommand(counter, 3))
        mgr.end_group()  # closes inner
        mgr.push(IncrCommand(counter, 4))
        mgr.end_group()  # closes outer
        assert counter[0] == 10  # 1 + 2 + 3 + 4
        assert len(mgr._undo_stack) == 1
        mgr.undo()
        assert counter[0] == 0

    def test_empty_group_does_not_add_undo_entry(self):
        mgr = UndoManager()
        mgr.begin_group("empty")
        mgr.end_group()
        assert not mgr.can_undo()
        assert len(mgr._undo_stack) == 0

    def test_commands_inside_group_execute_immediately(self):
        mgr = UndoManager()
        counter = [0]
        mgr.begin_group("g")
        mgr.push(IncrCommand(counter, 7))
        assert counter[0] == 7  # executed immediately — do() called right away
        mgr.end_group()


# ---------------------------------------------------------------------------
# _NullUndoManager (via UndoManager.null())
# ---------------------------------------------------------------------------


class TestNullUndoManager:
    def test_null_returns_undo_manager_instance(self):
        """UndoManager.null() returns a _NullUndoManager which IS an UndoManager."""
        nm = UndoManager.null()
        assert isinstance(nm, UndoManager)

    def test_push_does_not_call_do(self):
        """_NullUndoManager.push() is a no-op — does NOT call cmd.do().

        This is the critical asymmetry: real UndoManager.push() calls do(),
        _NullUndoManager.push() does nothing at all.
        """
        nm = UndoManager.null()
        counter = [0]
        nm.push(IncrCommand(counter, 99))
        assert counter[0] == 0  # do() was NOT called

    def test_undo_returns_false(self):
        assert UndoManager.null().undo() is False

    def test_redo_returns_false(self):
        assert UndoManager.null().redo() is False

    def test_can_undo_false(self):
        assert UndoManager.null().can_undo() is False

    def test_can_redo_false(self):
        assert UndoManager.null().can_redo() is False

    def test_begin_end_group_no_crash(self):
        nm = UndoManager.null()
        nm.begin_group("g")
        nm.end_group()

    def test_push_does_not_fire_change_subscribers(self):
        nm = UndoManager.null()
        calls = []
        sub = nm.subscribe_change(lambda: calls.append(1))  # noqa: F841 — hold ref
        nm.push(IncrCommand([0], 1))
        assert calls == []

    def test_each_null_call_returns_fresh_instance(self):
        assert UndoManager.null() is not UndoManager.null()

    def test_subscribe_change_returns_subscription(self):
        nm = UndoManager.null()
        sub = nm.subscribe_change(lambda: None)
        assert isinstance(sub, Subscription)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_begin_group_without_end_group_does_not_push_to_undo_stack(self):
        """Leaked/open group: commands execute immediately but never reach undo stack.

        If a caller opens a group and never calls end_group(), the commands
        run but cannot be undone. This is a caller error, not a crash.
        """
        mgr = UndoManager()
        counter = [0]
        mgr.begin_group("leaked")
        mgr.push(IncrCommand(counter, 1))
        mgr.push(IncrCommand(counter, 2))
        # group intentionally not ended
        assert counter[0] == 3          # commands ran
        assert not mgr.can_undo()       # nothing on the stack

    def test_cancel_group_restores_state(self):
        mgr = UndoManager()
        counter = [0]
        mgr.begin_group("g")
        mgr.push(IncrCommand(counter, 10))
        mgr.cancel_group()
        assert counter[0] == 0  # undo was applied by cancel
        assert not mgr.can_undo()

    def test_push_after_undo_clears_redo(self):
        mgr = UndoManager()
        counter = [0]
        mgr.push(IncrCommand(counter, 1))
        mgr.push(IncrCommand(counter, 2))
        mgr.undo()
        mgr.push(IncrCommand(counter, 99))
        assert not mgr.can_redo()

    def test_clear_resets_undo_and_redo_stacks(self):
        mgr = UndoManager()
        mgr.push(IncrCommand([0], 1))
        mgr.undo()
        mgr.clear()
        assert not mgr.can_undo()
        assert not mgr.can_redo()

    def test_undo_after_clear_returns_false(self):
        mgr = UndoManager()
        mgr.push(IncrCommand([0], 1))
        mgr.clear()
        assert mgr.undo() is False


# ---------------------------------------------------------------------------
# Non-undoable marker — LAYERS-PLAN Step 33
# ---------------------------------------------------------------------------


class _NonUndoableIncrCommand(IncrCommand):
    """Like IncrCommand but flagged as non-undoable. Used to exercise
    :meth:`UndoManager.push` handling of one-way commands (Save /
    Reload) without depending on the layer-command package."""

    non_undoable = True


class TestNonUndoable:
    def test_default_command_is_undoable(self):
        assert IncrCommand([0], 1).non_undoable is False

    def test_push_executes_non_undoable_command(self):
        mgr = UndoManager()
        counter = [0]
        mgr.push(_NonUndoableIncrCommand(counter, 5))
        assert counter[0] == 5

    def test_push_does_not_append_non_undoable_to_undo_stack(self):
        mgr = UndoManager()
        mgr.push(_NonUndoableIncrCommand([0], 1))
        assert not mgr.can_undo()
        assert len(mgr._undo_stack) == 0

    def test_push_non_undoable_clears_redo_stack(self):
        mgr = UndoManager()
        counter = [0]
        mgr.push(IncrCommand(counter, 3))
        mgr.undo()
        assert mgr.can_redo()
        mgr.push(_NonUndoableIncrCommand(counter, 7))
        assert not mgr.can_redo()

    def test_push_non_undoable_preserves_existing_undo_stack(self):
        mgr = UndoManager()
        counter = [0]
        mgr.push(IncrCommand(counter, 2))
        depth_before = len(mgr._undo_stack)
        mgr.push(_NonUndoableIncrCommand(counter, 5))
        assert len(mgr._undo_stack) == depth_before
        # The original command is still undoable.
        assert mgr.undo() is True
        assert counter[0] == 5  # 2+5=7, undid the +2 → 5

    def test_push_non_undoable_notifies_subscribers(self):
        mgr = UndoManager()
        calls = []
        sub = mgr.subscribe_change(lambda: calls.append(1))  # noqa: F841
        mgr.push(_NonUndoableIncrCommand([0], 1))
        assert calls == [1]

    def test_non_undoable_inside_group_does_not_accumulate(self):
        mgr = UndoManager()
        counter = [0]
        mgr.begin_group("g")
        mgr.push(_NonUndoableIncrCommand(counter, 5))
        mgr.push(_NonUndoableIncrCommand(counter, 6))
        # The group's accumulator stays empty because non_undoable
        # commands never enqueue, so end_group's "empty-group
        # auto-discard" kicks in.
        assert mgr._group_stack[-1][1] == []
        mgr.end_group()
        assert counter[0] == 11
        assert not mgr.can_undo()

    def test_mixed_group_keeps_only_undoable_commands(self):
        mgr = UndoManager()
        counter = [0]
        mgr.begin_group("mixed")
        mgr.push(IncrCommand(counter, 10))
        mgr.push(_NonUndoableIncrCommand(counter, 1))
        mgr.push(IncrCommand(counter, 2))
        assert len(mgr._group_stack[-1][1]) == 2
        mgr.end_group()
        assert counter[0] == 13
        # Undo replays only the two IncrCommands (10 + 2).
        mgr.undo()
        assert counter[0] == 1  # only the non_undoable +1 stays
