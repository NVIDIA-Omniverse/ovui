# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the three layer setter commands (LAYERS-PLAN Step 29):

- :class:`SetEditTargetCommand`
- :class:`SetLayerMutenessCommand`
- :class:`SetLayerLockCommand`

Each command is exercised in isolation (do / undo / redo round-trip)
and via :class:`~ovui_widgets.common.undo.UndoManager` so the ``Ctrl+Z`` pipeline
verify-bullet from the plan is pinned end-to-end. The value-model
integration block confirms :class:`~ovui_widgets.layers.models.mute_model.LocalMuteValueModel`
and :class:`~ovui_widgets.layers.models.lock_model.LockValueModel` actually
route through the command layer when an :class:`Application`-like
object is attached to the owning :class:`LayerModel`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from ovui_data_adapters.common import LayerEventType

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import LayerModel
from ovui_widgets.layers.commands import (
    LAYERS_UNDO_SOURCE,
    AbstractLayerCommand,
    SetEditTargetCommand,
    SetLayerLockCommand,
    SetLayerMutenessCommand,
)

# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    """Fresh mock adapter with root + session + one sublayer."""
    adapter = MockLayerStackAdapter(include_session=True)
    adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./sub.usda")
    return adapter


@pytest.fixture
def bus() -> SelectionBus:
    """Independent SelectionBus — no singleton pollution across tests."""
    return SelectionBus()


@pytest.fixture
def manager() -> UndoManager:
    """Fresh undo stack per test."""
    return UndoManager()


# ─── SetEditTargetCommand ───────────────────────────────────────────────────


class TestSetEditTargetCommand:
    """Verify the edit-target switch command; rest of the state-restore
    contract is already covered by ``test_layer_commands.py`` via the
    abstract base class."""

    def test_is_subclass_of_base(self) -> None:
        assert issubclass(SetEditTargetCommand, AbstractLayerCommand)

    def test_do_switches_edit_target(self, adapter, bus) -> None:
        cmd = SetEditTargetCommand(adapter, bus, "./sub.usda")
        cmd.do()
        assert adapter.get_edit_target_identifier() == "./sub.usda"

    def test_undo_restores_previous_edit_target(self, adapter, bus) -> None:
        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER
        cmd = SetEditTargetCommand(adapter, bus, "./sub.usda")
        cmd.do()
        cmd.undo()
        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER

    def test_redo_reapplies(self, adapter, bus) -> None:
        cmd = SetEditTargetCommand(adapter, bus, "./sub.usda")
        cmd.do()
        cmd.undo()
        cmd.redo()
        assert adapter.get_edit_target_identifier() == "./sub.usda"

    def test_undo_uses_base_snapshot_not_construction_time(
        self, adapter, bus
    ) -> None:
        # The base class snapshots the pre-mutation edit target inside
        # ``do()``. Changing the adapter's target between construction
        # and do must NOT bleed into the saved value — otherwise a
        # command built while planning would capture an unrelated state.
        cmd = SetEditTargetCommand(adapter, bus, "./sub.usda")
        adapter.set_edit_target("./sub.usda")
        # Now the "current" target matches the new target; construct a
        # fresh command that flips to root and confirm the snapshot
        # reflects the moment-of-do state.
        cmd2 = SetEditTargetCommand(adapter, bus, ROOT_LAYER_IDENTIFIER)
        cmd2.do()
        assert cmd2._saved_edit_target == "./sub.usda"
        cmd2.undo()
        assert adapter.get_edit_target_identifier() == "./sub.usda"

    def test_undo_publishes_with_layers_undo_source(
        self, adapter, bus
    ) -> None:
        # Subscribers rely on the namespaced source to suppress their
        # own repaint when the bus event originated from a layer undo.
        bus.publish(["/World/Ship"], source="user")
        cmd = SetEditTargetCommand(adapter, bus, "./sub.usda")
        cmd.do()
        bus.publish(["/World/Other"], source="user")
        seen: list = []
        sub = bus.subscribe(lambda evt: seen.append(evt.source))  # noqa: F841
        cmd.undo()
        assert seen[-1] == LAYERS_UNDO_SOURCE


# ─── SetLayerMutenessCommand ────────────────────────────────────────────────


class TestSetLayerMutenessCommand:

    def test_is_subclass_of_base(self) -> None:
        assert issubclass(SetLayerMutenessCommand, AbstractLayerCommand)

    def test_do_mutes(self, adapter, bus) -> None:
        cmd = SetLayerMutenessCommand(adapter, bus, "./sub.usda", True)
        cmd.do()
        assert adapter.is_muted(adapter.find_layer("./sub.usda")) is True

    def test_undo_unmutes(self, adapter, bus) -> None:
        cmd = SetLayerMutenessCommand(adapter, bus, "./sub.usda", True)
        cmd.do()
        cmd.undo()
        assert adapter.is_muted(adapter.find_layer("./sub.usda")) is False

    def test_do_unmutes_then_undo_mutes(self, adapter, bus) -> None:
        # Symmetric direction: starting from muted, the command should
        # unmute on do and re-mute on undo.
        adapter.set_mute("./sub.usda", True)
        cmd = SetLayerMutenessCommand(adapter, bus, "./sub.usda", False)
        cmd.do()
        assert adapter.is_muted(adapter.find_layer("./sub.usda")) is False
        cmd.undo()
        assert adapter.is_muted(adapter.find_layer("./sub.usda")) is True

    def test_redo_reapplies(self, adapter, bus) -> None:
        cmd = SetLayerMutenessCommand(adapter, bus, "./sub.usda", True)
        cmd.do()
        cmd.undo()
        cmd.redo()
        assert adapter.is_muted(adapter.find_layer("./sub.usda")) is True

    def test_stores_target_state_as_bool(self, adapter, bus) -> None:
        # Truthy non-bool inputs (legacy callers) should still land as
        # a genuine bool so the adapter's ``==`` no-op check lines up.
        cmd = SetLayerMutenessCommand(adapter, bus, "./sub.usda", 1)
        assert cmd._muted is True
        cmd = SetLayerMutenessCommand(adapter, bus, "./sub.usda", 0)
        assert cmd._muted is False

    def test_do_fires_mute_event(self, adapter, bus) -> None:
        events: list = []
        # Keep the Subscription alive — its ``__del__`` unsubscribes,
        # so dropping the return value would silently discard events.
        sub = adapter.subscribe_events(lambda e: events.append(e))  # noqa: F841
        cmd = SetLayerMutenessCommand(adapter, bus, "./sub.usda", True)
        cmd.do()
        mute_events = [
            e for e in events if e.event_type == LayerEventType.MUTE_STATE_CHANGED
        ]
        assert len(mute_events) == 1
        assert mute_events[0].identifiers == ("./sub.usda",)


# ─── SetLayerLockCommand ────────────────────────────────────────────────────


class TestSetLayerLockCommand:

    def test_is_subclass_of_base(self) -> None:
        assert issubclass(SetLayerLockCommand, AbstractLayerCommand)

    def test_do_locks(self, adapter, bus) -> None:
        cmd = SetLayerLockCommand(adapter, bus, "./sub.usda", True)
        cmd.do()
        assert adapter.is_locked(adapter.find_layer("./sub.usda")) is True

    def test_undo_unlocks(self, adapter, bus) -> None:
        cmd = SetLayerLockCommand(adapter, bus, "./sub.usda", True)
        cmd.do()
        cmd.undo()
        assert adapter.is_locked(adapter.find_layer("./sub.usda")) is False

    def test_do_unlocks_then_undo_locks(self, adapter, bus) -> None:
        adapter.set_lock("./sub.usda", True)
        cmd = SetLayerLockCommand(adapter, bus, "./sub.usda", False)
        cmd.do()
        assert adapter.is_locked(adapter.find_layer("./sub.usda")) is False
        cmd.undo()
        assert adapter.is_locked(adapter.find_layer("./sub.usda")) is True

    def test_redo_reapplies(self, adapter, bus) -> None:
        cmd = SetLayerLockCommand(adapter, bus, "./sub.usda", True)
        cmd.do()
        cmd.undo()
        cmd.redo()
        assert adapter.is_locked(adapter.find_layer("./sub.usda")) is True

    def test_stores_target_state_as_bool(self, adapter, bus) -> None:
        cmd = SetLayerLockCommand(adapter, bus, "./sub.usda", 1)
        assert cmd._locked is True
        cmd = SetLayerLockCommand(adapter, bus, "./sub.usda", 0)
        assert cmd._locked is False

    def test_do_fires_lock_event(self, adapter, bus) -> None:
        events: list = []
        sub = adapter.subscribe_events(lambda e: events.append(e))  # noqa: F841
        cmd = SetLayerLockCommand(adapter, bus, "./sub.usda", True)
        cmd.do()
        lock_events = [
            e for e in events if e.event_type == LayerEventType.LOCK_STATE_CHANGED
        ]
        assert len(lock_events) == 1
        assert lock_events[0].identifiers == ("./sub.usda",)


# ─── UndoManager integration ────────────────────────────────────────────────


class TestUndoManagerIntegration:
    """End-to-end: push through the real :class:`UndoManager` so the
    ``Ctrl+Z`` verify-bullet from the plan is covered."""

    def test_push_then_undo_restores_mute(
        self, adapter, bus, manager
    ) -> None:
        cmd = SetLayerMutenessCommand(adapter, bus, "./sub.usda", True)
        manager.push(cmd)
        assert adapter.is_muted(adapter.find_layer("./sub.usda")) is True
        assert manager.undo() is True
        assert adapter.is_muted(adapter.find_layer("./sub.usda")) is False

    def test_push_then_undo_redo_mute(
        self, adapter, bus, manager
    ) -> None:
        cmd = SetLayerMutenessCommand(adapter, bus, "./sub.usda", True)
        manager.push(cmd)
        manager.undo()
        assert manager.redo() is True
        assert adapter.is_muted(adapter.find_layer("./sub.usda")) is True

    def test_push_then_undo_restores_lock(
        self, adapter, bus, manager
    ) -> None:
        cmd = SetLayerLockCommand(adapter, bus, "./sub.usda", True)
        manager.push(cmd)
        assert adapter.is_locked(adapter.find_layer("./sub.usda")) is True
        assert manager.undo() is True
        assert adapter.is_locked(adapter.find_layer("./sub.usda")) is False

    def test_push_then_undo_restores_edit_target(
        self, adapter, bus, manager
    ) -> None:
        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER
        cmd = SetEditTargetCommand(adapter, bus, "./sub.usda")
        manager.push(cmd)
        assert adapter.get_edit_target_identifier() == "./sub.usda"
        assert manager.undo() is True
        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER

    def test_mixed_stack_undoes_in_reverse_order(
        self, adapter, bus, manager
    ) -> None:
        # Push edit-target + mute + lock, then undo three times — each
        # undo reverses its own mutation without stepping on the others.
        manager.push(SetEditTargetCommand(adapter, bus, "./sub.usda"))
        manager.push(SetLayerMutenessCommand(adapter, bus, "./sub.usda", True))
        # After muting, the adapter rejects set_edit_target on a muted
        # layer if we retry — so we picked mute last-but-one and lock on
        # root (which isn't the current edit target) to avoid adapter
        # guardrails. Lock the root to test the three-deep unwind.
        manager.push(SetLayerLockCommand(adapter, bus, ROOT_LAYER_IDENTIFIER, True))

        # Undo lock → root unlocked.
        assert manager.undo() is True
        assert adapter.is_locked(adapter.get_root_layer()) is False
        # Undo mute → sub unmuted.
        assert manager.undo() is True
        assert adapter.is_muted(adapter.find_layer("./sub.usda")) is False
        # Undo edit target → back to root.
        assert manager.undo() is True
        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER


# ─── Value-model routing ────────────────────────────────────────────────────


def _make_app(manager: UndoManager, bus: SelectionBus) -> SimpleNamespace:
    """Tiny duck-typed stand-in for :class:`Application`.

    The value models only read ``_app.undo_manager`` and
    ``_app.selection_bus`` — a :class:`SimpleNamespace` is the lightest
    way to supply them without the singleton pollution that comes with
    constructing a real :class:`Application` in tests.
    """
    return SimpleNamespace(undo_manager=manager, selection_bus=bus)


class TestValueModelRoutesThroughCommand:
    """LocalMuteValueModel / LockValueModel must push a command when an
    app is attached, and fall back to the direct adapter call when it
    isn't."""

    def test_mute_model_with_app_pushes_command(
        self, adapter, bus, manager
    ) -> None:
        app = _make_app(manager, bus)
        model = LayerModel(adapter, services=app)
        try:
            vm = model.get_item_value_model(model.root_item, 3)
            assert adapter.is_muted(adapter.get_root_layer()) is False
            vm.set_value(True)
            # Mutation applied.
            assert adapter.is_muted(adapter.get_root_layer()) is True
            # And it's on the undo stack — one click, one undo step.
            assert manager.can_undo() is True
            manager.undo()
            assert adapter.is_muted(adapter.get_root_layer()) is False
        finally:
            model.destroy()

    def test_lock_model_with_app_pushes_command(
        self, adapter, bus, manager
    ) -> None:
        app = _make_app(manager, bus)
        model = LayerModel(adapter, services=app)
        try:
            vm = model.get_item_value_model(model.root_item, 6)
            assert adapter.is_locked(adapter.get_root_layer()) is False
            vm.set_value(True)
            assert adapter.is_locked(adapter.get_root_layer()) is True
            assert manager.can_undo() is True
            manager.undo()
            assert adapter.is_locked(adapter.get_root_layer()) is False
        finally:
            model.destroy()

    def test_mute_model_without_app_calls_adapter_directly(
        self, adapter
    ) -> None:
        # Regression guard for the LayerModel(adapter) construction path
        # used by every Step 20 unit test — no app, no undo stack, but
        # the direct write still has to land.
        model = LayerModel(adapter)
        try:
            vm = model.get_item_value_model(model.root_item, 3)
            vm.set_value(True)
            assert adapter.is_muted(adapter.get_root_layer()) is True
        finally:
            model.destroy()

    def test_lock_model_without_app_calls_adapter_directly(
        self, adapter
    ) -> None:
        model = LayerModel(adapter)
        try:
            vm = model.get_item_value_model(model.root_item, 6)
            vm.set_value(True)
            assert adapter.is_locked(adapter.get_root_layer()) is True
        finally:
            model.destroy()

    def test_mute_click_toggle_undoable_round_trip(
        self, adapter, bus, manager
    ) -> None:
        # Mirrors the delegate's click-handler: vm.set_value(not
        # vm.get_value_as_bool()). Click → mute, Ctrl+Z → unmute, redo
        # → mute again. Every arrow exercises one UndoManager method.
        app = _make_app(manager, bus)
        model = LayerModel(adapter, services=app)
        try:
            vm = model.get_item_value_model(model.root_item, 3)
            vm.set_value(not vm.get_value_as_bool())
            assert adapter.is_muted(adapter.get_root_layer()) is True
            manager.undo()
            assert adapter.is_muted(adapter.get_root_layer()) is False
            manager.redo()
            assert adapter.is_muted(adapter.get_root_layer()) is True
        finally:
            model.destroy()

    def test_lock_click_toggle_undoable_round_trip(
        self, adapter, bus, manager
    ) -> None:
        app = _make_app(manager, bus)
        model = LayerModel(adapter, services=app)
        try:
            vm = model.get_item_value_model(model.root_item, 6)
            vm.set_value(not vm.get_value_as_bool())
            assert adapter.is_locked(adapter.get_root_layer()) is True
            manager.undo()
            assert adapter.is_locked(adapter.get_root_layer()) is False
            manager.redo()
            assert adapter.is_locked(adapter.get_root_layer()) is True
        finally:
            model.destroy()

    def test_no_op_mute_click_does_not_push_command(
        self, adapter, bus, manager
    ) -> None:
        # Clicking "mute" on an already-muted layer must not enter the
        # undo stack — otherwise the adapter's own no-op guard silently
        # swallows ``do`` while ``undo`` actually flips the bit, so
        # Ctrl+Z would "undo" a change that never happened.
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        app = _make_app(manager, bus)
        model = LayerModel(adapter, services=app)
        try:
            vm = model.get_item_value_model(model.root_item, 3)
            assert vm.get_value_as_bool() is True
            vm.set_value(True)  # no-op click
            assert manager.can_undo() is False
            assert adapter.is_muted(adapter.get_root_layer()) is True
        finally:
            model.destroy()

    def test_no_op_lock_click_does_not_push_command(
        self, adapter, bus, manager
    ) -> None:
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
        app = _make_app(manager, bus)
        model = LayerModel(adapter, services=app)
        try:
            vm = model.get_item_value_model(model.root_item, 6)
            assert vm.get_value_as_bool() is True
            vm.set_value(True)
            assert manager.can_undo() is False
            assert adapter.is_locked(adapter.get_root_layer()) is True
        finally:
            model.destroy()

    def test_detached_adapter_is_noop_even_with_app(
        self, adapter, bus, manager
    ) -> None:
        # Late click after :meth:`LayerModel.set_adapter` cleared the
        # adapter reference — even with an app attached, the guard in
        # ``set_value`` must short-circuit before building the command.
        app = _make_app(manager, bus)
        model = LayerModel(adapter, services=app)
        try:
            vm = model.get_item_value_model(model.root_item, 3)
            model._adapter = None
            vm.set_value(True)  # must not raise
            assert manager.can_undo() is False
        finally:
            # Restore so destroy() can do its detach cleanup.
            model._adapter = adapter
            model.destroy()
