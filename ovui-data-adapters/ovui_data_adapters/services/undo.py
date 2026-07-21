# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Frontend-neutral undo / command / history service.

This module owns the concrete undo stack behavior shared by ovui-widgets and
future non-ovui-widgets frontends: command cancellation, undo grouping, null
manager behavior, and change-notification subscription lifetime.

The ``Command`` ABC and ``UndoManagerProtocol`` remain adapter-common
contracts so OpenUSD adapters can type command inputs without depending on
the higher-level services distribution. They are re-exported here as part of
the complete undo service surface; callers should see one coherent subsystem,
not disconnected primitives.
"""

from __future__ import annotations

import weakref
from typing import Any, Callable

from ovui_data_adapters.common import (
    Command,
    CommandCancelled,
    UndoManagerProtocol,
)
from ovui_data_adapters.common._command import (
    clear_history_consistent as _clear_history_consistent,
    command_edge as _command_edge,
    is_history_consistent as _is_history_consistent,
)



def _retain_failed_revocation(owner: object, handle: object) -> None:
    stale = getattr(owner, "_stale_subscription_handles", None)
    if stale is None:
        try:
            stale = []
            setattr(owner, "_stale_subscription_handles", stale)
        except Exception:
            return
    # Identity-deduplicated: repeated failures of ONE handle retain it
    # exactly once. Retention is NEVER capped: every live registration
    # keeps durable owner-side revocation ownership, and the collection
    # is finite by construction — at most one small handle per admitted
    # registration.
    if not any(existing is handle for existing in stale):
        stale.append(handle)


def _drain_stale_revocations(owner: object) -> None:
    """Retry every retained failed revocation; drop the resolved ones."""
    stale = getattr(owner, "_stale_subscription_handles", None)
    if not stale:
        return
    remaining = []
    for handle in stale:
        try:
            handle.cancel()
        except BaseException:  # noqa: BLE001 — still owned for retry
            if not any(existing is handle for existing in remaining):
                remaining.append(handle)
    stale[:] = remaining

class Subscription:
    """RAII subscription handle for undo-manager change notifications."""

    def __init__(
        self,
        manager_ref: "weakref.ReferenceType[Any]",
        callback: Callable[[], None],
    ) -> None:
        self._manager_ref = manager_ref
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        """Remove this callback from the subscribed undo manager."""
        if self._cancelled:
            return
        manager = self._manager_ref()
        if manager is not None:
            # Mark cancelled only AFTER removal succeeded: a failed
            # revocation stays owned by the MANAGER (GC-safe) and
            # retryable.
            try:
                manager._remove_subscriber(self._callback)
            except BaseException:
                _retain_failed_revocation(manager, self)
                raise
        self._cancelled = True

    def __del__(self) -> None:
        try:
            self.cancel()
        except BaseException:  # noqa: BLE001 — never unraisable: the
            # owner already retains durable revocation ownership.
            pass


def _history_consistent_interrupt(exc: BaseException) -> bool:
    """True for an interrupt raised AFTER its command edge fully applied.

    The provider stream marks an interrupt-class failure
    (``KeyboardInterrupt``, ``SystemExit``) — always on a FRESH per-edge
    exception instance, see ``common._command.history_consistent_interrupt``
    — when it was captured during a post-commit observer publication: the
    command's state effect and its exact inverse are complete, so the
    history entry must still be recorded/moved before the interrupt
    becomes visible to the caller. Ordinary exceptions never qualify.
    """
    return _is_history_consistent(exc)


class UndoGroup(Command):
    """Bundles multiple commands into a single undo entry."""

    def __init__(self, label: str, commands: list[Command]) -> None:
        self._label = label
        self._commands = list(commands)

    def do(self) -> None:
        completed: list[Command] = []
        deferred: BaseException | None = None
        try:
            for command in self._commands:
                try:
                    command.do()
                except BaseException as exc:
                    if _history_consistent_interrupt(exc):
                        # The member's state effect is complete: keep the
                        # group consistent, surface the interrupt after.
                        completed.append(command)
                        if deferred is None:
                            deferred = exc
                        continue
                    raise
                completed.append(command)
        except BaseException as operation_error:
            for command in reversed(completed):
                try:
                    command.undo()
                except BaseException as compensation_error:
                    self._note_compensation_failure(
                        operation_error,
                        "undo",
                        command,
                        compensation_error,
                    )
            raise
        if deferred is not None:
            raise deferred

    def undo(self) -> None:
        completed: list[Command] = []
        deferred: BaseException | None = None
        try:
            for command in reversed(self._commands):
                try:
                    command.undo()
                except BaseException as exc:
                    if _history_consistent_interrupt(exc):
                        completed.append(command)
                        if deferred is None:
                            deferred = exc
                        continue
                    raise
                completed.append(command)
        except BaseException as operation_error:
            # Re-apply successfully undone commands in their original order so
            # the group remains at the pre-undo edge when a later undo fails.
            for command in reversed(completed):
                try:
                    command.redo()
                except BaseException as compensation_error:
                    self._note_compensation_failure(
                        operation_error,
                        "redo",
                        command,
                        compensation_error,
                    )
            raise
        if deferred is not None:
            raise deferred

    @staticmethod
    def _note_compensation_failure(
        operation_error: BaseException,
        action: str,
        command: Command,
        compensation_error: BaseException,
    ) -> None:
        """Keep the operation error primary while preserving rollback details."""
        add_note = getattr(operation_error, "add_note", None)
        if callable(add_note):
            add_note(
                f"UndoGroup compensation could not {action} "
                f"{type(command).__name__}: "
                f"{type(compensation_error).__name__}: {compensation_error}"
            )

    @property
    def label(self) -> str:
        return self._label


class UndoManager:
    """Undo/redo stack with group support and change notifications."""

    def __init__(self) -> None:
        self._undo_stack: list[Command] = []
        self._redo_stack: list[Command] = []
        self._group_stack: list[tuple[str, list[Command]]] = []
        self._subscribers: list[Callable[[], None]] = []
        # Bound methods (weakly held) that settle in-flight edit
        # transactions before a namespace-affecting command mutates; see
        # register_pre_namespace_settler.
        self._pre_namespace_settlers: list = []
        self._settling = False

    def register_pre_namespace_settler(self, settler: Callable[[], None]) -> None:
        """Register a settler run before namespace-affecting commands.

        ``settler`` must be a bound method; it is held WEAKLY so
        registering never extends its owner's lifetime. Commands that
        declare ``affects_namespace = True`` (prim deletion, rename,
        reparent) trigger every live settler before their push edge
        executes, letting an owner finalize or cancel its in-flight
        edit transaction so the namespace mutation can never entangle,
        discard, or absorb an active edit.
        """
        # Selection churn constructs short-lived property adapters. Remove
        # their weak slots at owner finalization instead of waiting for a
        # future namespace command that may never happen.
        owner_ref = weakref.ref(self)

        def _discard_dead(dead_ref: Any) -> None:
            owner = owner_ref()
            if owner is None:
                return
            try:
                owner._pre_namespace_settlers.remove(dead_ref)
            except ValueError:
                pass

        # Also prune before registration so delayed cyclic-GC callbacks and
        # duplicate registration can never make the live list grow without
        # bound.
        live_refs = []
        already_registered = False
        for ref in self._pre_namespace_settlers:
            live = ref()
            if live is None:
                continue
            live_refs.append(ref)
            if live == settler:
                already_registered = True
        self._pre_namespace_settlers = live_refs
        if not already_registered:
            self._pre_namespace_settlers.append(
                weakref.WeakMethod(settler, _discard_dead)
            )

    def _settle_before_namespace(self, command: Command) -> None:
        if self._settling or not getattr(command, "affects_namespace", False):
            return
        if not self._pre_namespace_settlers:
            return
        self._settling = True
        # A namespace command is commonly pushed inside its own Delete or
        # Reparent group. The active property transaction must precede that
        # group as an independent history edge; temporarily suspend every
        # open accumulator while settlers publish their commands, then restore
        # the exact stack before the namespace command itself executes.
        suspended_groups = self._group_stack
        self._group_stack = []
        try:
            for ref in list(self._pre_namespace_settlers):
                settler = ref()
                if settler is None:
                    try:
                        self._pre_namespace_settlers.remove(ref)
                    except ValueError:
                        pass
                    continue
                settler()
        finally:
            self._group_stack = suspended_groups
            self._settling = False

    def push(self, command: Command) -> None:
        """Execute ``command`` and push it. Clears redo stack on success.

        Commands with ``non_undoable = True`` still execute but are not appended
        to the undo stack or current group accumulator. At top level they clear
        the redo stack the same way a fresh push does.

        When :meth:`Command.do` raises :class:`CommandCancelled`, the push is
        discarded silently: no stack entries change, redo remains intact, and
        subscribers are not notified.

        A history-consistent interrupt (see
        :func:`_history_consistent_interrupt`) means the command's state
        effect fully applied: the entry is recorded FIRST, then the
        interrupt re-raises so it stays caller-visible without orphaning
        committed state from its history.
        """
        # PR #109: settle in-flight property edit transactions BEFORE a
        # namespace-affecting command executes (see
        # register_pre_namespace_settler), then run the release/0.2
        # history-consistent interrupt edge around the command itself.
        self._settle_before_namespace(command)
        deferred: BaseException | None = None
        try:
            with _command_edge():
                command.do()
        except CommandCancelled:
            return
        except BaseException as exc:
            if not _history_consistent_interrupt(exc):
                raise
            deferred = exc

        non_undoable = getattr(command, "non_undoable", False)
        if self._group_stack:
            if not non_undoable:
                self._group_stack[-1][1].append(command)
        else:
            if not non_undoable:
                self._undo_stack.append(command)
            self._redo_stack.clear()
            self._notify()
        if deferred is not None:
            # Final command-service frame for this edge: consume the mark
            # so the delivered object can be reused by application code
            # without ever recording an unapplied command. Structured
            # group owners detect the recorded-then-interrupted push via
            # ``open_group_command_count`` growth, not the mark.
            _clear_history_consistent(deferred)
            raise deferred

    def undo(self) -> bool:
        """Undo the last command. Returns ``False`` if nothing can be undone."""
        if not self._undo_stack:
            return False
        # Keep the history edge in place until the command succeeds. This lets
        # callers inspect or retry an entry whose undo raised. A
        # history-consistent interrupt means the edge DID succeed: the entry
        # moves first, then the interrupt re-raises to stay caller-visible.
        command = self._undo_stack[-1]
        deferred: BaseException | None = None
        try:
            with _command_edge():
                command.undo()
        except BaseException as exc:
            if not _history_consistent_interrupt(exc):
                raise
            deferred = exc
        self._undo_stack.pop()
        self._redo_stack.append(command)
        self._notify()
        if deferred is not None:
            # Final command-service frame for this edge: consume the mark
            # so it cannot linger on an object application code may reuse.
            _clear_history_consistent(deferred)
            raise deferred
        return True

    def redo(self) -> bool:
        """Redo the last undone command. Returns ``False`` if nothing can redo."""
        if not self._redo_stack:
            return False
        # As with undo, transfer the entry only after the command edge commits.
        command = self._redo_stack[-1]
        deferred: BaseException | None = None
        try:
            with _command_edge():
                command.redo()
        except BaseException as exc:
            if not _history_consistent_interrupt(exc):
                raise
            deferred = exc
        self._redo_stack.pop()
        self._undo_stack.append(command)
        self._notify()
        if deferred is not None:
            _clear_history_consistent(deferred)
            raise deferred
        return True

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def clear(self) -> None:
        """Clear all undo/redo history, including any open group accumulators.

        An open group must not survive a history wipe: a later push would
        silently join it and never become independently undoable.
        """
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._group_stack.clear()
        self._notify()

    def begin_group(self, label: str) -> None:
        """Start a command group. Groups can nest."""
        self._group_stack.append((label, []))

    @property
    def open_group_depth(self) -> int:
        """Number of currently open (unclosed) group accumulators."""
        return len(self._group_stack)

    @property
    def open_group_command_count(self) -> int:
        """Commands accumulated in the innermost open group (0 if none).

        Supported recovery introspection for structured group owners: a
        force-discard is only safe when the accumulator is observed
        empty — dropping a nonempty one would leave applied effects with
        no history ownership.
        """
        if not self._group_stack:
            return 0
        return len(self._group_stack[-1][1])

    def force_discard_group(self) -> None:
        """Drop the innermost open group WITHOUT undoing or recording it.

        Exceptional-lifecycle escape hatch for structured group owners:
        when ``end_group()`` or ``cancel_group()`` fails, the owner must
        still guarantee that no accumulator outlives its scope (a later
        push would silently join it). The caller owns state truthfulness —
        the discarded commands' effects are neither undone nor undoable, so
        owners pair this with their own baseline verification/compensation
        and a conservative change notification.
        """
        if self._group_stack:
            self._group_stack.pop()

    def end_group(self) -> None:
        """End the current group. When nesting reaches 0, pushes the group.

        A close arriving after the accumulators were wiped (``clear()`` or
        a structured owner's forced discard) is a DEAD TOKEN and no-ops —
        it must not corrupt the in-flight operation with an IndexError,
        and no command may thereby escape its (already discarded) group.
        """
        if not self._group_stack:
            return
        label, commands = self._group_stack.pop()
        group = UndoGroup(label, commands)
        if self._group_stack:
            self._group_stack[-1][1].append(group)
        else:
            if commands:
                self._undo_stack.append(group)
                self._redo_stack.clear()
                self._notify()

    def cancel_group(self) -> None:
        """Cancel the current group. Undo accumulated commands in reverse."""
        # Leave the accumulator reachable until its undo commits. UndoGroup
        # restores already-undone commands if a later command fails, so a
        # failed cancellation can be retried without losing history.
        label, commands = self._group_stack[-1]
        deferred: BaseException | None = None
        try:
            with _command_edge():
                UndoGroup(label, commands).undo()
        except BaseException as exc:
            if not _history_consistent_interrupt(exc):
                raise
            # Every member's compensation COMPLETED (a marked interrupt
            # only surfaces after its edge fully applied): the cancel is
            # terminal. Popping here keeps it atomic — a retry would run
            # the compensation twice, and a later ``end_group`` would
            # record the already-compensated commands for redo to
            # resurrect.
            deferred = exc
        self._group_stack.pop()
        if deferred is not None:
            _clear_history_consistent(deferred)
            raise deferred

    def subscribe_change(self, callback: Callable[[], None]) -> Subscription:
        """Subscribe to undo stack changes.

        The returned :class:`Subscription` cancels itself on garbage collection
        and can also be cancelled explicitly.
        """

        _drain_stale_revocations(self)
        self._subscribers.append(callback)
        return Subscription(weakref.ref(self), callback)

    def _remove_subscriber(self, callback: Callable[[], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def _notify(self) -> None:
        for callback in list(self._subscribers):
            callback()

    @staticmethod
    def null() -> "UndoManager":
        """Return a no-op undo manager.

        All methods are safe to call but do nothing. This is useful for modules
        that accept an optional undo manager and do not need undo support.
        """
        return _NullUndoManager()


class _NullUndoManager(UndoManager):
    """No-op undo manager. All mutations are silently discarded."""

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


__all__ = [
    "Command",
    "CommandCancelled",
    "Subscription",
    "UndoGroup",
    "UndoManager",
    "UndoManagerProtocol",
]
