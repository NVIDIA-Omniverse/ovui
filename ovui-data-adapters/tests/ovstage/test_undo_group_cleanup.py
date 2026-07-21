# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OVStage undo-group manager-depth cleanup contracts (runtime-free).

The adapter's visibility scope owns one manager group level per nesting
level. Whatever happens on close — a committed end, an aborted cancel, or
the manager's own ``end_group()``/``cancel_group()`` raising — the shared
``UndoManager`` must return to its pre-scope group depth so no accumulator
outlives the scope and silently captures a later, unrelated push.
"""

from __future__ import annotations

import pytest

from ovui_data_adapters.common import Command
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter
from ovui_data_adapters.services.undo import UndoManager


class _Recorded(Command):
    def __init__(self) -> None:
        self.done = 0
        self.undone = 0

    def do(self) -> None:
        self.done += 1

    def undo(self) -> None:
        self.undone += 1


class _EndFailsOnce(UndoManager):
    def __init__(self) -> None:
        super().__init__()
        self.end_failures_left = 1

    def end_group(self) -> None:
        if self.end_failures_left:
            self.end_failures_left -= 1
            raise RuntimeError("end_group boom")
        super().end_group()


class _CancelFailsAlways(UndoManager):
    def cancel_group(self) -> None:
        raise RuntimeError("cancel_group boom")


def _assert_isolated_after_recovery(manager: UndoManager) -> None:
    """A later command records independently at top level."""
    assert manager.open_group_depth == 0
    command = _Recorded()
    manager.push(command)
    assert command.done == 1
    assert manager.can_undo() is True
    assert manager.undo() is True
    assert command.undone == 1


def test_end_group_failure_restores_depth_and_isolates_later_pushes() -> None:
    manager = _EndFailsOnce()
    adapter = OvstageStageAdapter(scene=None, undo_manager=manager)
    adapter.begin_undo_group("Toggle Visibility")
    assert manager.open_group_depth == 1
    with pytest.raises(RuntimeError, match="end_group boom"):
        adapter.end_undo_group()
    _assert_isolated_after_recovery(manager)


def test_end_failure_after_level_recorded_keeps_history() -> None:
    """Production path: a change subscriber raises during the record.

    ``end_group()`` at top level pops, records, and THEN notifies — a
    raising subscriber fails the close AFTER the level closed and the
    group was recorded. Recovery must observe that (depth already at the
    floor) and never run a compensating call against what is now an
    outer/committed context: the recorded entry survives, the applied
    command is never undone behind the caller's back, and the failure is
    still reported.
    """
    manager = UndoManager()

    def raising_subscriber() -> None:
        raise RuntimeError("subscriber boom")

    subscription = manager.subscribe_change(raising_subscriber)
    adapter = OvstageStageAdapter(scene=None, undo_manager=manager)
    adapter.begin_undo_group("Toggle Visibility")
    foreign = _Recorded()
    manager.push(foreign)
    with pytest.raises(RuntimeError, match="subscriber boom"):
        adapter.end_undo_group()
    subscription.cancel()
    assert manager.open_group_depth == 0
    assert foreign.done == 1
    assert foreign.undone == 0  # nothing compensated a recorded close
    assert manager.can_undo() is True  # the applied command kept history
    assert manager.undo() is True
    assert foreign.undone == 1


def test_aborted_nonempty_group_cancel_failure_records_applied_commands() -> None:
    """Cancellation failure must not orphan applied commands from history.

    An aborted group prefers compensation, but when ``cancel_group()``
    keeps failing the nonempty accumulator is RECORDED rather than
    force-discarded: an applied command must never be left in effect
    with no history entry.
    """
    manager = _CancelFailsAlways()
    adapter = OvstageStageAdapter(scene=None, undo_manager=manager)
    adapter.begin_undo_group("Toggle Visibility")
    foreign = _Recorded()
    manager.push(foreign)

    class _MemberError(Exception):
        pass

    member_error = _MemberError("member failed")
    try:
        raise member_error
    except _MemberError:
        adapter.abort_undo_group()
    notes = getattr(member_error, "__notes__", [])
    assert any("cancel_group boom" in note for note in notes)
    assert manager.open_group_depth == 0
    assert foreign.done == 1 and foreign.undone == 0
    assert manager.can_undo() is True  # recorded, not silently dropped
    assert manager.undo() is True
    assert foreign.undone == 1


def test_aborted_group_cancel_failure_recovers_depth() -> None:
    manager = _CancelFailsAlways()
    adapter = OvstageStageAdapter(scene=None, undo_manager=manager)
    adapter.begin_undo_group("Toggle Visibility")

    class _MemberError(Exception):
        pass

    member_error = _MemberError("member failed")
    try:
        raise member_error
    except _MemberError:
        # The widget abort path: the member error stays primary, cleanup
        # context attaches as a note, and no exception displaces it.
        adapter.abort_undo_group()
    notes = getattr(member_error, "__notes__", [])
    assert any("cancel_group boom" in note for note in notes)
    _assert_isolated_after_recovery(manager)


def test_aborted_group_cancel_failure_without_active_exception_raises() -> None:
    manager = _CancelFailsAlways()
    adapter = OvstageStageAdapter(scene=None, undo_manager=manager)
    adapter.begin_undo_group("Toggle Visibility")
    with pytest.raises(RuntimeError, match="cancel_group boom"):
        adapter.abort_undo_group()
    _assert_isolated_after_recovery(manager)


class _BothFail(UndoManager):
    """end_group() and cancel_group() both fail until released."""

    def __init__(self) -> None:
        super().__init__()
        self.fail = True

    def end_group(self) -> None:
        if self.fail:
            raise RuntimeError("end boom")
        super().end_group()

    def cancel_group(self) -> None:
        if self.fail:
            raise RuntimeError("cancel boom")
        super().cancel_group()


def test_double_close_failure_nonempty_group_retains_ownership() -> None:
    """No force-discard of applied effects when nothing else progresses.

    When completion AND cancellation both fail before any progress on a
    NONEMPTY group, the accumulator must not be force-discarded — that
    would leave applied effects with no history ownership. The level is
    retained (reported as cleanup context) and stays recoverable: a later
    successful close records the accumulated commands.
    """
    manager = _BothFail()
    adapter = OvstageStageAdapter(scene=None, undo_manager=manager)
    adapter.begin_undo_group("Toggle Visibility")
    foreign = _Recorded()
    manager.push(foreign)

    class _MemberError(Exception):
        pass

    member_error = _MemberError("member failed")
    try:
        raise member_error
    except _MemberError:
        adapter.abort_undo_group()
    # Ownership retained, never orphaned; failure context observable.
    assert manager.open_group_depth == 1
    assert foreign.done == 1 and foreign.undone == 0
    notes = getattr(member_error, "__notes__", [])
    assert any("cancel boom" in note for note in notes)
    # The retained level recovers once the manager cooperates again.
    manager.fail = False
    manager.end_group()
    assert manager.open_group_depth == 0
    assert manager.can_undo() is True
    assert manager.undo() is True
    assert foreign.undone == 1


def test_double_close_failure_empty_group_is_discarded_to_floor() -> None:
    """An EMPTY accumulator may be force-discarded: nothing can be orphaned."""
    manager = _BothFail()
    adapter = OvstageStageAdapter(scene=None, undo_manager=manager)
    adapter.begin_undo_group("Toggle Visibility")
    with pytest.raises(RuntimeError, match="cancel boom"):
        adapter.abort_undo_group()
    assert manager.open_group_depth == 0
    manager.fail = False
    _assert_isolated_after_recovery(manager)


def test_nested_inner_end_failure_outermost_close_restores_floor() -> None:
    manager = _EndFailsOnce()
    adapter = OvstageStageAdapter(scene=None, undo_manager=manager)
    adapter.begin_undo_group("outer")
    adapter.begin_undo_group("inner")
    assert manager.open_group_depth == 2
    # The inner close reports its failure and leaves its manager level
    # leaked; the outermost close must still return the manager to the
    # recorded pre-scope floor.
    with pytest.raises(RuntimeError, match="end_group boom"):
        adapter.end_undo_group()
    assert manager.open_group_depth == 2
    adapter.end_undo_group()
    _assert_isolated_after_recovery(manager)


def test_pre_existing_outer_group_is_preserved() -> None:
    manager = _EndFailsOnce()
    manager.begin_group("caller-owned")
    adapter = OvstageStageAdapter(scene=None, undo_manager=manager)
    adapter.begin_undo_group("Toggle Visibility")
    assert manager.open_group_depth == 2
    with pytest.raises(RuntimeError, match="end_group boom"):
        adapter.end_undo_group()
    # Recovery stops at the recorded floor: the caller's own group level
    # survives untouched.
    assert manager.open_group_depth == 1
    manager.end_group()
    assert manager.open_group_depth == 0
