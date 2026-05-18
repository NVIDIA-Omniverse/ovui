# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ovwidgets.common.undo — Command, UndoGroup, UndoManager."""

import gc

import pytest

from ovwidgets.common.settings import Subscription
from ovwidgets.common.undo import Command, UndoGroup, UndoManager

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class SetValueCommand(Command):
    """Simple command: sets target[key] = new_value; undo restores old_value."""

    def __init__(self, target: dict, key: str, new_value, old_value):
        self._target = target
        self._key = key
        self._new = new_value
        self._old = old_value

    def do(self):
        self._target[self._key] = self._new

    def undo(self):
        self._target[self._key] = self._old


class CountingCommand(Command):
    """Records how many times do/undo/redo were called."""

    def __init__(self):
        self.do_count = 0
        self.undo_count = 0
        self.redo_count = 0

    def do(self):
        self.do_count += 1

    def undo(self):
        self.undo_count += 1

    def redo(self):
        self.redo_count += 1


# ---------------------------------------------------------------------------
# Command ABC
# ---------------------------------------------------------------------------

class TestCommand:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            Command()

    def test_redo_defaults_to_do(self):
        class NoRedoOverride(Command):
            do_count = 0
            def do(self): self.do_count += 1
            def undo(self): pass

        cmd = NoRedoOverride()
        cmd.do()
        cmd.redo()
        assert cmd.do_count == 2  # redo() falls back to do()

    def test_redo_custom_override(self):
        """redo() on CountingCommand increments redo_count, not do_count."""
        cmd = CountingCommand()
        cmd.redo()
        assert cmd.do_count == 0
        assert cmd.redo_count == 1


# ---------------------------------------------------------------------------
# UndoGroup
# ---------------------------------------------------------------------------

class TestUndoGroup:
    def test_do_calls_all_in_order(self):
        log = []
        state = {}

        class LogCmd(Command):
            def __init__(self, n):
                self.n = n
            def do(self):
                log.append(("do", self.n))
                state[self.n] = True
            def undo(self):
                log.append(("undo", self.n))
                state.pop(self.n, None)

        cmds = [LogCmd(1), LogCmd(2), LogCmd(3)]
        group = UndoGroup("test", cmds)
        group.do()
        assert log == [("do", 1), ("do", 2), ("do", 3)]
        assert state == {1: True, 2: True, 3: True}

    def test_undo_calls_all_in_reverse_order(self):
        log = []

        class LogCmd(Command):
            def __init__(self, n):
                self.n = n
            def do(self): pass
            def undo(self):
                log.append(self.n)

        cmds = [LogCmd(1), LogCmd(2), LogCmd(3)]
        group = UndoGroup("test", cmds)
        group.undo()
        assert log == [3, 2, 1]

    def test_label_property(self):
        group = UndoGroup("my label", [])
        assert group.label == "my label"

    def test_commands_list_is_copied(self):
        original = [CountingCommand()]
        group = UndoGroup("g", original)
        original.clear()
        group.do()
        assert group._commands[0].do_count == 1

    def test_empty_group_do_undo_no_error(self):
        group = UndoGroup("empty", [])
        group.do()
        group.undo()


# ---------------------------------------------------------------------------
# Basic push / undo / redo
# ---------------------------------------------------------------------------

class TestBasicPushUndoRedo:
    def test_push_calls_do(self):
        mgr = UndoManager()
        cmd = CountingCommand()
        mgr.push(cmd)
        assert cmd.do_count == 1

    def test_undo_calls_undo(self):
        mgr = UndoManager()
        cmd = CountingCommand()
        mgr.push(cmd)
        result = mgr.undo()
        assert result is True
        assert cmd.undo_count == 1

    def test_redo_calls_redo(self):
        mgr = UndoManager()
        cmd = CountingCommand()
        mgr.push(cmd)
        mgr.undo()
        result = mgr.redo()
        assert result is True
        assert cmd.redo_count == 1

    def test_state_correct_after_push_undo_redo(self):
        mgr = UndoManager()
        state = {"x": 0}
        mgr.push(SetValueCommand(state, "x", 1, 0))
        assert state["x"] == 1
        mgr.undo()
        assert state["x"] == 0
        mgr.redo()
        assert state["x"] == 1

    def test_undo_returns_false_when_empty(self):
        mgr = UndoManager()
        assert mgr.undo() is False

    def test_redo_returns_false_when_empty(self):
        mgr = UndoManager()
        assert mgr.redo() is False

    def test_redo_returns_false_after_push(self):
        mgr = UndoManager()
        mgr.push(CountingCommand())
        assert mgr.redo() is False


# ---------------------------------------------------------------------------
# Stack state (can_undo / can_redo)
# ---------------------------------------------------------------------------

class TestStackState:
    def test_initially_cannot_undo_or_redo(self):
        mgr = UndoManager()
        assert mgr.can_undo() is False
        assert mgr.can_redo() is False

    def test_can_undo_after_push(self):
        mgr = UndoManager()
        mgr.push(CountingCommand())
        assert mgr.can_undo() is True

    def test_cannot_redo_after_push(self):
        mgr = UndoManager()
        mgr.push(CountingCommand())
        assert mgr.can_redo() is False

    def test_can_redo_after_undo(self):
        mgr = UndoManager()
        mgr.push(CountingCommand())
        mgr.undo()
        assert mgr.can_redo() is True
        assert mgr.can_undo() is False

    def test_push_after_undo_clears_redo_stack(self):
        mgr = UndoManager()
        mgr.push(CountingCommand())
        mgr.push(CountingCommand())
        mgr.undo()
        assert mgr.can_redo() is True
        mgr.push(CountingCommand())
        assert mgr.can_redo() is False

    def test_multiple_pushes_all_undoable(self):
        mgr = UndoManager()
        state = {"v": 0}
        for i in range(1, 4):
            mgr.push(SetValueCommand(state, "v", i, i - 1))
        assert state["v"] == 3
        mgr.undo()
        assert state["v"] == 2
        mgr.undo()
        assert state["v"] == 1
        mgr.undo()
        assert state["v"] == 0
        assert mgr.can_undo() is False

    def test_redo_all_after_undo_all(self):
        mgr = UndoManager()
        state = {"v": 0}
        for i in range(1, 4):
            mgr.push(SetValueCommand(state, "v", i, i - 1))
        for _ in range(3):
            mgr.undo()
        for _ in range(3):
            assert mgr.redo() is True
        assert state["v"] == 3
        assert mgr.can_redo() is False


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

class TestGroups:
    def test_group_creates_single_undo_entry(self):
        mgr = UndoManager()
        state = {"a": 0, "b": 0}
        mgr.begin_group("grp")
        mgr.push(SetValueCommand(state, "a", 1, 0))
        mgr.push(SetValueCommand(state, "b", 2, 0))
        mgr.end_group()
        assert state == {"a": 1, "b": 2}
        # One undo entry, not two
        assert len(mgr._undo_stack) == 1

    def test_group_undo_reverses_all_commands(self):
        mgr = UndoManager()
        state = {"a": 0, "b": 0}
        mgr.begin_group("grp")
        mgr.push(SetValueCommand(state, "a", 1, 0))
        mgr.push(SetValueCommand(state, "b", 2, 0))
        mgr.end_group()
        mgr.undo()
        assert state == {"a": 0, "b": 0}

    def test_commands_inside_group_execute_immediately(self):
        mgr = UndoManager()
        state = {"v": 0}
        mgr.begin_group("g")
        mgr.push(SetValueCommand(state, "v", 42, 0))
        assert state["v"] == 42  # executed immediately
        mgr.end_group()

    def test_nested_groups_work(self):
        mgr = UndoManager()
        log = []

        class LogCmd(Command):
            def __init__(self, tag):
                self.tag = tag
            def do(self): pass
            def undo(self):
                log.append(self.tag)

        mgr.begin_group("outer")
        mgr.push(LogCmd("A"))
        mgr.begin_group("inner")
        mgr.push(LogCmd("B"))
        mgr.push(LogCmd("C"))
        mgr.end_group()  # inner closes
        mgr.push(LogCmd("D"))
        mgr.end_group()  # outer closes

        assert len(mgr._undo_stack) == 1
        mgr.undo()
        # Undo order: D first, then inner group (C, B), then A
        assert log == ["D", "C", "B", "A"]

    def test_nested_groups_single_undo_entry(self):
        mgr = UndoManager()
        mgr.begin_group("outer")
        mgr.begin_group("inner")
        mgr.push(CountingCommand())
        mgr.end_group()
        mgr.end_group()
        assert len(mgr._undo_stack) == 1

    def test_cancel_group_undoes_accumulated_commands(self):
        mgr = UndoManager()
        state = {"a": 1, "b": 2}
        mgr.begin_group("g")
        mgr.push(SetValueCommand(state, "a", 10, 1))
        mgr.push(SetValueCommand(state, "b", 20, 2))
        mgr.cancel_group()
        assert state == {"a": 1, "b": 2}
        assert mgr.can_undo() is False

    def test_cancel_group_undo_order_is_reversed(self):
        mgr = UndoManager()
        log = []

        class LogUndo(Command):
            def __init__(self, tag):
                self.tag = tag
            def do(self): pass
            def undo(self):
                log.append(self.tag)

        mgr.begin_group("g")
        mgr.push(LogUndo("first"))
        mgr.push(LogUndo("second"))
        mgr.cancel_group()
        assert log == ["second", "first"]

    def test_empty_group_does_not_create_undo_entry(self):
        mgr = UndoManager()
        mgr.begin_group("empty")
        mgr.end_group()
        assert mgr.can_undo() is False
        assert len(mgr._undo_stack) == 0


# ---------------------------------------------------------------------------
# Change notifications
# ---------------------------------------------------------------------------

class TestChangeNotifications:
    def test_subscriber_called_on_push(self):
        mgr = UndoManager()
        calls = []
        sub = mgr.subscribe_change(lambda: calls.append("push"))
        mgr.push(CountingCommand())
        assert calls == ["push"]

    def test_subscriber_called_on_undo(self):
        mgr = UndoManager()
        calls = []
        mgr.push(CountingCommand())
        sub = mgr.subscribe_change(lambda: calls.append("undo"))
        mgr.undo()
        assert calls == ["undo"]

    def test_subscriber_called_on_redo(self):
        mgr = UndoManager()
        calls = []
        mgr.push(CountingCommand())
        mgr.undo()
        sub = mgr.subscribe_change(lambda: calls.append("redo"))
        mgr.redo()
        assert calls == ["redo"]

    def test_subscriber_called_on_clear(self):
        mgr = UndoManager()
        calls = []
        sub = mgr.subscribe_change(lambda: calls.append("clear"))
        mgr.clear()
        assert calls == ["clear"]

    def test_subscriber_called_on_group_end(self):
        mgr = UndoManager()
        calls = []
        sub = mgr.subscribe_change(lambda: calls.append("change"))
        mgr.begin_group("g")
        mgr.push(CountingCommand())
        assert calls == []  # not called mid-group
        mgr.end_group()
        assert calls == ["change"]

    def test_subscriber_not_called_on_cancel_group(self):
        mgr = UndoManager()
        calls = []
        sub = mgr.subscribe_change(lambda: calls.append("change"))
        mgr.begin_group("g")
        mgr.push(CountingCommand())
        mgr.cancel_group()
        assert calls == []

    def test_multiple_subscribers(self):
        mgr = UndoManager()
        calls_a = []
        calls_b = []
        sub_a = mgr.subscribe_change(lambda: calls_a.append(1))
        sub_b = mgr.subscribe_change(lambda: calls_b.append(1))
        mgr.push(CountingCommand())
        assert calls_a == [1]
        assert calls_b == [1]

    def test_cancelled_subscription_not_called(self):
        mgr = UndoManager()
        calls = []
        sub = mgr.subscribe_change(lambda: calls.append(1))
        sub.cancel()
        mgr.push(CountingCommand())
        assert calls == []

    def test_subscription_returns_subscription_instance(self):
        mgr = UndoManager()
        sub = mgr.subscribe_change(lambda: None)
        assert isinstance(sub, Subscription)

    def test_subscription_gc_auto_cancels(self):
        mgr = UndoManager()
        calls = []
        sub = mgr.subscribe_change(lambda: calls.append(1))
        del sub
        gc.collect()
        mgr.push(CountingCommand())
        assert calls == []


# ---------------------------------------------------------------------------
# Null manager
# ---------------------------------------------------------------------------

class TestNullManager:
    def test_null_returns_undo_manager_instance(self):
        nm = UndoManager.null()
        assert isinstance(nm, UndoManager)

    def test_push_does_not_call_do(self):
        nm = UndoManager.null()
        cmd = CountingCommand()
        nm.push(cmd)
        assert cmd.do_count == 0

    def test_undo_returns_false(self):
        nm = UndoManager.null()
        assert nm.undo() is False

    def test_redo_returns_false(self):
        nm = UndoManager.null()
        assert nm.redo() is False

    def test_can_undo_false(self):
        nm = UndoManager.null()
        assert nm.can_undo() is False

    def test_can_redo_false(self):
        nm = UndoManager.null()
        assert nm.can_redo() is False

    def test_clear_no_crash(self):
        nm = UndoManager.null()
        nm.clear()

    def test_begin_end_group_no_crash(self):
        nm = UndoManager.null()
        nm.begin_group("g")
        nm.end_group()

    def test_cancel_group_no_crash(self):
        nm = UndoManager.null()
        nm.begin_group("g")
        nm.cancel_group()

    def test_subscribe_change_no_crash(self):
        nm = UndoManager.null()
        sub = nm.subscribe_change(lambda: None)
        assert isinstance(sub, Subscription)

    def test_push_does_not_fire_subscribers(self):
        nm = UndoManager.null()
        calls = []
        nm.subscribe_change(lambda: calls.append(1))
        nm.push(CountingCommand())
        assert calls == []

    def test_each_null_call_returns_fresh_instance(self):
        nm1 = UndoManager.null()
        nm2 = UndoManager.null()
        assert nm1 is not nm2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_clear_resets_everything(self):
        mgr = UndoManager()
        mgr.push(CountingCommand())
        mgr.push(CountingCommand())
        mgr.undo()
        mgr.clear()
        assert mgr.can_undo() is False
        assert mgr.can_redo() is False

    def test_push_after_clear_works(self):
        mgr = UndoManager()
        mgr.push(CountingCommand())
        mgr.clear()
        cmd = CountingCommand()
        mgr.push(cmd)
        assert cmd.do_count == 1
        assert mgr.can_undo() is True

    def test_undo_after_clear_returns_false(self):
        mgr = UndoManager()
        mgr.push(CountingCommand())
        mgr.clear()
        assert mgr.undo() is False

    def test_redo_after_clear_returns_false(self):
        mgr = UndoManager()
        mgr.push(CountingCommand())
        mgr.undo()
        mgr.clear()
        assert mgr.redo() is False

    def test_push_after_undo_clears_redo(self):
        mgr = UndoManager()
        state = {"v": 0}
        mgr.push(SetValueCommand(state, "v", 1, 0))
        mgr.push(SetValueCommand(state, "v", 2, 1))
        mgr.undo()
        assert state["v"] == 1
        mgr.push(SetValueCommand(state, "v", 99, 1))
        assert mgr.can_redo() is False
        assert state["v"] == 99

    def test_group_redo_works(self):
        mgr = UndoManager()
        state = {"a": 0, "b": 0}
        mgr.begin_group("g")
        mgr.push(SetValueCommand(state, "a", 1, 0))
        mgr.push(SetValueCommand(state, "b", 2, 0))
        mgr.end_group()
        mgr.undo()
        assert state == {"a": 0, "b": 0}
        mgr.redo()
        assert state == {"a": 1, "b": 2}

    def test_deeply_nested_groups(self):
        mgr = UndoManager()
        state = {"v": 0}
        mgr.begin_group("L1")
        mgr.begin_group("L2")
        mgr.begin_group("L3")
        mgr.push(SetValueCommand(state, "v", 42, 0))
        mgr.end_group()
        mgr.end_group()
        mgr.end_group()
        assert len(mgr._undo_stack) == 1
        assert state["v"] == 42
        mgr.undo()
        assert state["v"] == 0

    def test_cancel_inner_group_outer_continues(self):
        mgr = UndoManager()
        state = {"a": 0, "b": 0}
        mgr.begin_group("outer")
        mgr.push(SetValueCommand(state, "a", 1, 0))
        mgr.begin_group("inner")
        mgr.push(SetValueCommand(state, "b", 99, 0))
        mgr.cancel_group()  # cancel inner — b is restored
        assert state["b"] == 0
        assert state["a"] == 1
        mgr.end_group()  # outer still has cmd_a
        assert len(mgr._undo_stack) == 1
        mgr.undo()
        assert state["a"] == 0

    def test_command_redo_uses_custom_override(self):
        """Verify that UndoGroup.redo() calls do() on all sub-commands
        (since UndoGroup doesn't override redo(), it falls back to do())."""
        mgr = UndoManager()
        cmds = [CountingCommand(), CountingCommand()]
        mgr.begin_group("g")
        for c in cmds:
            mgr.push(c)
        mgr.end_group()
        mgr.undo()
        mgr.redo()
        # redo() on UndoGroup falls through to do(), so do_count goes from 1 to 2
        for c in cmds:
            assert c.do_count == 2
