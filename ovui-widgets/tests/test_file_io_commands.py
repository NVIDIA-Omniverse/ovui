# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`SaveLayerCommand` and :class:`ReloadLayerCommand`
(LAYERS-PLAN Step 33).

Covers the Step-33 contract:

- Both commands are :class:`AbstractLayerCommand` subclasses with
  ``non_undoable = True`` at the class level.
- :meth:`SaveLayerCommand.do_impl` calls
  :meth:`~ovui_widgets.common.adapters.LayerStackAdapter.save_layer` and
  clears the layer's dirty bit on success.
- :meth:`ReloadLayerCommand.do_impl` calls
  :meth:`~ovui_widgets.common.adapters.LayerStackAdapter.reload_layer`.
- :class:`IOError` / :class:`PermissionError` raised by the adapter
  are caught and surfaced through an injected ``error_reporter`` —
  the exception does not propagate out of the command.
- An adapter returning ``False`` from ``save_layer`` (anonymous or
  missing layer) reports an error but does not raise.
- :meth:`UndoManager.push` honours ``non_undoable``: the command
  executes, the redo stack is cleared, and the undo stack stays
  unchanged. ``can_undo()`` returns whatever it returned before.
- Non-undoable commands pushed *inside* a group do not accumulate
  on the group, so the group ends empty and auto-discards.
- The no-op ``undo_impl`` is safe to call directly (defensive
  guard against misuse).
"""

from __future__ import annotations

from typing import List

import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers.commands import (
    AbstractLayerCommand,
    ReloadLayerCommand,
    SaveLayerCommand,
    SetLayerMutenessCommand,
)

# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    """Adapter seeded with one concrete (non-anonymous) sublayer."""
    ad = MockLayerStackAdapter(include_session=True)
    ad.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./child.usda")
    return ad


@pytest.fixture
def bus() -> SelectionBus:
    return SelectionBus()


@pytest.fixture
def manager() -> UndoManager:
    return UndoManager()


class _CollectingReporter:
    """Stand-in for :class:`~ovui_widgets.common.error_reporter.ErrorReporter` that
    captures each ``show_error`` call for assertion."""

    def __init__(self) -> None:
        self.errors: List[str] = []

    def show_error(self, message: str) -> None:
        self.errors.append(message)


# ─── Class-level marker ─────────────────────────────────────────────────────


class TestNonUndoableMarker:
    def test_save_command_is_non_undoable(self) -> None:
        assert SaveLayerCommand.non_undoable is True

    def test_reload_command_is_non_undoable(self) -> None:
        assert ReloadLayerCommand.non_undoable is True

    def test_save_command_is_subclass_of_base(self) -> None:
        assert issubclass(SaveLayerCommand, AbstractLayerCommand)

    def test_reload_command_is_subclass_of_base(self) -> None:
        assert issubclass(ReloadLayerCommand, AbstractLayerCommand)

    def test_default_command_is_undoable(self) -> None:
        # Regular commands inherit ``non_undoable = False`` from the
        # Command base — the marker defaults to False.
        cmd = SetLayerMutenessCommand(
            MockLayerStackAdapter(), SelectionBus(),
            ROOT_LAYER_IDENTIFIER, True,
        )
        assert cmd.non_undoable is False


# ─── SaveLayerCommand ───────────────────────────────────────────────────────


class TestSaveLayerCommand:
    def test_do_clears_dirty_bit(self, adapter, bus) -> None:
        adapter.set_dirty("./child.usda", True)
        cmd = SaveLayerCommand(adapter, bus, "./child.usda")
        cmd.do()
        assert adapter.is_dirty(adapter.find_layer("./child.usda")) is False

    def test_do_on_clean_layer_is_noop(self, adapter, bus) -> None:
        # Mock ``save_layer`` returns True for a clean layer without
        # touching the dirty bit. No error surfaces.
        reporter = _CollectingReporter()
        cmd = SaveLayerCommand(adapter, bus, "./child.usda", reporter)
        cmd.do()
        assert reporter.errors == []

    def test_anonymous_layer_reports_error(self, adapter, bus) -> None:
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "")
        anon_id = adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )[-1]
        reporter = _CollectingReporter()
        cmd = SaveLayerCommand(adapter, bus, anon_id, reporter)
        cmd.do()
        assert len(reporter.errors) == 1
        assert anon_id in reporter.errors[0]

    def test_ioerror_is_caught_and_reported(self, adapter, bus) -> None:
        reporter = _CollectingReporter()

        def _raise(_identifier):
            raise IOError("disk full")

        adapter.save_layer = _raise  # monkeypatch
        cmd = SaveLayerCommand(
            adapter, bus, "./child.usda", reporter
        )
        cmd.do()  # must not propagate
        assert len(reporter.errors) == 1
        assert "disk full" in reporter.errors[0]

    def test_permissionerror_is_caught_and_reported(
        self, adapter, bus
    ) -> None:
        reporter = _CollectingReporter()

        def _raise(_identifier):
            raise PermissionError("read-only fs")

        adapter.save_layer = _raise
        cmd = SaveLayerCommand(
            adapter, bus, "./child.usda", reporter
        )
        cmd.do()
        assert len(reporter.errors) == 1
        assert "read-only fs" in reporter.errors[0]

    def test_non_file_exception_is_not_caught(self, adapter, bus) -> None:
        # Only IOError / PermissionError are in the contract. A
        # surprise ValueError bubbles up so the bug gets seen.
        def _raise(_identifier):
            raise ValueError("unexpected")

        adapter.save_layer = _raise
        cmd = SaveLayerCommand(adapter, bus, "./child.usda")
        with pytest.raises(ValueError):
            cmd.do()

    def test_undo_is_noop(self, adapter, bus) -> None:
        # ``undo`` chain: undo_impl is a no-op, _restore_state runs on
        # top but does not error — the base class tolerates the
        # default snapshot (root edit target, empty selection).
        adapter.set_dirty("./child.usda", True)
        cmd = SaveLayerCommand(adapter, bus, "./child.usda")
        cmd.do()
        # No exception; dirty stays False (undo doesn't restore it).
        cmd.undo()
        assert adapter.is_dirty(adapter.find_layer("./child.usda")) is False


# ─── ReloadLayerCommand ─────────────────────────────────────────────────────


class TestReloadLayerCommand:
    def test_do_clears_dirty_bit(self, adapter, bus) -> None:
        adapter.set_dirty("./child.usda", True)
        cmd = ReloadLayerCommand(adapter, bus, "./child.usda")
        cmd.do()
        assert adapter.is_dirty(adapter.find_layer("./child.usda")) is False

    def test_ioerror_is_caught_and_reported(self, adapter, bus) -> None:
        reporter = _CollectingReporter()

        def _raise(_identifier):
            raise IOError("stream gone")

        adapter.reload_layer = _raise
        cmd = ReloadLayerCommand(
            adapter, bus, "./child.usda", reporter
        )
        cmd.do()
        assert len(reporter.errors) == 1
        assert "stream gone" in reporter.errors[0]

    def test_permissionerror_is_caught_and_reported(
        self, adapter, bus
    ) -> None:
        reporter = _CollectingReporter()

        def _raise(_identifier):
            raise PermissionError("nope")

        adapter.reload_layer = _raise
        cmd = ReloadLayerCommand(
            adapter, bus, "./child.usda", reporter
        )
        cmd.do()
        assert len(reporter.errors) == 1

    def test_undo_is_noop(self, adapter, bus) -> None:
        adapter.set_dirty("./child.usda", True)
        cmd = ReloadLayerCommand(adapter, bus, "./child.usda")
        cmd.do()
        cmd.undo()  # no exception


# ─── UndoManager integration — non_undoable semantics ───────────────────────


class TestUndoManagerNonUndoable:
    def test_push_executes_save(self, adapter, bus, manager) -> None:
        adapter.set_dirty("./child.usda", True)
        cmd = SaveLayerCommand(adapter, bus, "./child.usda")
        manager.push(cmd)
        assert adapter.is_dirty(adapter.find_layer("./child.usda")) is False

    def test_push_does_not_land_on_undo_stack(
        self, adapter, bus, manager
    ) -> None:
        # Prime with one real command so the undo stack is non-empty
        # — the push of a non_undoable command must leave it alone.
        manager.push(
            SetLayerMutenessCommand(
                adapter, bus, "./child.usda", True
            )
        )
        depth_before = len(manager._undo_stack)
        manager.push(SaveLayerCommand(adapter, bus, "./child.usda"))
        assert len(manager._undo_stack) == depth_before

    def test_push_preserves_can_undo_from_before(
        self, adapter, bus, manager
    ) -> None:
        assert manager.can_undo() is False
        manager.push(SaveLayerCommand(adapter, bus, "./child.usda"))
        assert manager.can_undo() is False

        manager.push(
            SetLayerMutenessCommand(
                adapter, bus, "./child.usda", True
            )
        )
        assert manager.can_undo() is True
        manager.push(SaveLayerCommand(adapter, bus, "./child.usda"))
        assert manager.can_undo() is True

    def test_push_clears_redo_stack(self, adapter, bus, manager) -> None:
        # Establish a redo entry.
        manager.push(
            SetLayerMutenessCommand(
                adapter, bus, "./child.usda", True
            )
        )
        manager.undo()
        assert manager.can_redo() is True

        manager.push(SaveLayerCommand(adapter, bus, "./child.usda"))
        assert manager.can_redo() is False

    def test_push_fires_change_subscribers(
        self, adapter, bus, manager
    ) -> None:
        calls: List[int] = []
        sub = manager.subscribe_change(lambda: calls.append(1))  # noqa: F841
        manager.push(SaveLayerCommand(adapter, bus, "./child.usda"))
        assert calls == [1]

    def test_reload_via_manager_same_semantics(
        self, adapter, bus, manager
    ) -> None:
        manager.push(
            SetLayerMutenessCommand(
                adapter, bus, "./child.usda", True
            )
        )
        depth = len(manager._undo_stack)
        adapter.set_dirty("./child.usda", True)
        manager.push(ReloadLayerCommand(adapter, bus, "./child.usda"))
        assert adapter.is_dirty(adapter.find_layer("./child.usda")) is False
        assert len(manager._undo_stack) == depth


# ─── UndoManager integration — non_undoable inside groups ───────────────────


class TestUndoManagerNonUndoableInsideGroup:
    def test_group_with_only_non_undoable_auto_discards(
        self, adapter, bus, manager
    ) -> None:
        # A group containing only non-undoable commands ends empty and
        # must not land on the undo stack (Step 33 "Save All" pattern).
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./other.usda")
        adapter.set_dirty("./child.usda", True)
        adapter.set_dirty("./other.usda", True)

        manager.begin_group("Save All")
        manager.push(SaveLayerCommand(adapter, bus, "./child.usda"))
        manager.push(SaveLayerCommand(adapter, bus, "./other.usda"))
        manager.end_group()

        assert manager.can_undo() is False
        assert adapter.is_dirty(adapter.find_layer("./child.usda")) is False
        assert adapter.is_dirty(adapter.find_layer("./other.usda")) is False

    def test_group_with_mixed_keeps_only_undoable(
        self, adapter, bus, manager
    ) -> None:
        # A group that contains both a regular undoable mutation and
        # a non-undoable command should keep only the undoable one in
        # the group's command list.
        manager.begin_group("mixed")
        manager.push(
            SetLayerMutenessCommand(
                adapter, bus, "./child.usda", True
            )
        )
        manager.push(SaveLayerCommand(adapter, bus, "./child.usda"))
        # Inspect the in-flight group before end_group.
        assert len(manager._group_stack[-1][1]) == 1
        manager.end_group()

        # End-group should land a one-command group on the stack.
        assert manager.can_undo() is True
        assert len(manager._undo_stack) == 1
