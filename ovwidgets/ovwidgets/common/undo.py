# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Undo/redo command stack.

UndoManager is a command-pattern stack with do/undo/redo; supports
compound commands (groups) and change notifications to the UI.
"""

import weakref
from typing import TYPE_CHECKING, Callable, List

from ovui_data_adapters.common import Command

from ovwidgets.common.settings import Subscription

if TYPE_CHECKING:
    from ovui_data_adapters.common import TransformAdapter


class CommandCancelled(Exception):
    """Raised from :meth:`Command.do` to abort a push without mutating stacks.

    Commands use this to short-circuit a push when a pre-do guard
    decides the operation should not proceed — typically a confirm-
    dialog the user cancelled (LAYERS-PLAN Step 37 dirty-remove /
    dirty-reload prompts). :meth:`UndoManager.push` catches the
    exception, returns silently, and does **not** clear the redo
    stack — the user cancelling the prompt leaves history untouched,
    matching the "nothing happened" mental model.
    """


class BatchTransformCommand(Command):
    """Single undo entry for a complete drag operation on one prim.

    Stores only the initial and final transforms — not per-frame deltas.
    """

    def __init__(
        self,
        adapter: "TransformAdapter",
        path: str,
        initial: List[List[float]],
        final: List[List[float]],
    ) -> None:
        self._adapter = adapter
        self._path = path
        self._initial = [row[:] for row in initial]
        self._final = [row[:] for row in final]

    def do(self) -> None:
        self._adapter.set_local_transform(self._path, self._final)

    def undo(self) -> None:
        self._adapter.set_local_transform(self._path, self._initial)


class UndoGroup(Command):
    """Bundles multiple commands into a single undo entry."""

    def __init__(self, label: str, commands: List[Command]) -> None:
        self._label = label
        self._commands = list(commands)

    def do(self) -> None:
        for c in self._commands:
            c.do()

    def undo(self) -> None:
        for c in reversed(self._commands):
            c.undo()

    @property
    def label(self) -> str:
        return self._label


class UndoManager:
    """
    Undo/redo stack with group support and change notifications.

    Every module that modifies state pushes Commands to this manager.
    Groups batch multiple commands into a single undo entry.
    """

    def __init__(self) -> None:
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        # Each entry: (label, accumulated_commands)
        self._group_stack: list[tuple[str, list[Command]]] = []
        self._subscribers: list[Callable] = []

    def push(self, command: Command) -> None:
        """Execute command and push it. Clears redo stack.

        Inside a group, accumulates without touching the main stack.

        Commands with ``non_undoable = True`` still execute but are
        **not** appended to the undo stack (nor to the current group's
        accumulator). At top level they clear the redo stack — a
        one-way operation invalidates redo history the same way a
        fresh push does. See LAYERS-PLAN Step 33 (Save / Reload).

        When :meth:`Command.do` raises :class:`CommandCancelled` the
        push is discarded silently — no stack entries change, the
        redo stack stays intact, and subscribers are not notified.
        Used by confirm-dialog guards (LAYERS-PLAN Step 37) that
        abort on user dismiss.
        """
        try:
            command.do()
        except CommandCancelled:
            return
        non_undoable = getattr(command, "non_undoable", False)
        if self._group_stack:
            if not non_undoable:
                self._group_stack[-1][1].append(command)
        else:
            if not non_undoable:
                self._undo_stack.append(command)
            self._redo_stack.clear()
            self._notify()

    def undo(self) -> bool:
        """Undo the last command. Returns False if nothing to undo."""
        if not self._undo_stack:
            return False
        command = self._undo_stack.pop()
        command.undo()
        self._redo_stack.append(command)
        self._notify()
        return True

    def redo(self) -> bool:
        """Redo the last undone command. Returns False if nothing to redo."""
        if not self._redo_stack:
            return False
        command = self._redo_stack.pop()
        command.redo()
        self._undo_stack.append(command)
        self._notify()
        return True

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def clear(self) -> None:
        """Clear all undo/redo history."""
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._notify()

    def begin_group(self, label: str) -> None:
        """Start a command group. Groups can nest."""
        self._group_stack.append((label, []))

    def end_group(self) -> None:
        """End the current group. When nesting reaches 0, pushes the group."""
        label, commands = self._group_stack.pop()
        group = UndoGroup(label, commands)
        if self._group_stack:
            # Still inside an outer group — add as nested entry.
            self._group_stack[-1][1].append(group)
        else:
            if commands:
                self._undo_stack.append(group)
                self._redo_stack.clear()
                self._notify()

    def cancel_group(self) -> None:
        """Cancel the current group. Undo all accumulated commands in reverse."""
        _label, commands = self._group_stack.pop()
        for command in reversed(commands):
            command.undo()

    def subscribe_change(self, callback: Callable[[], None]) -> Subscription:
        """Subscribe to undo stack changes (push, undo, redo, clear).

        Returns a Subscription that cancels itself on garbage collection.
        """
        self._subscribers.append(callback)
        return Subscription(weakref.ref(self), "change", callback)

    def _remove_subscriber(self, key: str, callback: Callable) -> None:
        # key is unused — UndoManager has a single change event.
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _notify(self) -> None:
        for cb in list(self._subscribers):
            cb()

    @staticmethod
    def null() -> "UndoManager":
        """Return a no-op UndoManager stub.

        All methods are safe to call but do nothing. For modules that receive
        an optional undo_manager parameter and don't need undo support.
        """
        return _NullUndoManager()


class _NullUndoManager(UndoManager):
    """No-op UndoManager. All mutations are silently discarded."""

    def push(self, command: Command) -> None:
        pass

    def undo(self) -> bool:
        return False

    def redo(self) -> bool:
        return False

    def can_undo(self) -> bool:
        return False

    def can_redo(self) -> bool:
        return False

    def clear(self) -> None:
        pass

    def begin_group(self, label: str) -> None:
        pass

    def end_group(self) -> None:
        pass

    def cancel_group(self) -> None:
        pass
