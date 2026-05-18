# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 34 — per-row save click → command.

Covers the contract:

- Clicking a dirty, saveable row routes the save through
  :class:`SaveLayerCommand` on the owning
  :class:`~ovwidgets.app.application.Application`'s
  :class:`~ovwidgets.common.undo.UndoManager`, not a direct adapter call.
- The ``SaveLayerCommand`` is ``non_undoable``, so the undo stack
  stays unchanged and the redo stack clears (matches the Step-33
  contract, re-verified at the click seam).
- After a successful save the adapter's dirty bit clears and the
  cached :class:`SaveValueModel` re-reads ``False`` so the icon
  disappears on the next paint.
- The anonymous / missing / clean / detached guards still short-
  circuit the click before a command is pushed.
- Headless construction (``app=None``) keeps the pre-Step-34
  semantics: a direct adapter call so the value model stays
  testable without faking an ``UndoManager``.
"""

from __future__ import annotations

from typing import Any, List

import pytest
from ovui_data_adapters.common import LayerEventType

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import LayerModel
from ovwidgets.layers.commands import (
    SaveLayerCommand,
    SetLayerMutenessCommand,
)

# ─── Fixtures ───────────────────────────────────────────────────────────────


class _App:
    """Minimal :class:`Application` stand-in for the click-path tests.

    Exposes the exact surface :meth:`LayerModel._request_save` reads
    (``undo_manager``, ``selection_bus``) — no ``call_later``, so
    events are flushed inline by the model itself (matches how every
    other headless test in the suite exercises the model).
    """

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=True)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child.usda")
    return ad


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def model(adapter, app) -> LayerModel:
    m = LayerModel(adapter, services=app)
    yield m
    m.destroy()


def _child_item(model: LayerModel):
    return model._items_by_id["./child.usda"]


# ─── Click path — concrete layer → SaveLayerCommand on the undo manager ─────


class TestClickPushesCommand:
    def test_click_pushes_save_layer_command(
        self, adapter, app, model
    ) -> None:
        """Clicking the save dot pushes a :class:`SaveLayerCommand`.

        The command path is the Step-34 deliverable — the prior
        Step-19 stub dispatched straight to the adapter. We capture
        the push by wrapping :meth:`UndoManager.push` so the command
        object can be inspected before the manager swallows it.
        """
        adapter.set_dirty("./child.usda", True)
        pushed: List[Any] = []
        original_push = app.undo_manager.push

        def _spy(cmd):
            pushed.append(cmd)
            return original_push(cmd)

        app.undo_manager.push = _spy
        vm = model.get_item_value_model(_child_item(model), 2)
        vm.set_value(True)

        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, SaveLayerCommand)
        assert cmd._identifier == "./child.usda"

    def test_click_clears_dirty_bit(self, adapter, app, model) -> None:
        # End-to-end round-trip — the command's ``do_impl`` forwards
        # to ``adapter.save_layer``, which clears the dirty bit in
        # the mock. The per-row save model re-reads False after the
        # flush, so the icon disappears from the row on the next
        # paint (the delegate watches ``get_value_as_bool``).
        adapter.set_dirty("./child.usda", True)
        child = _child_item(model)
        vm = model.get_item_value_model(child, 2)
        assert vm.get_value_as_bool() is True

        vm.set_value(True)

        assert adapter.is_dirty(adapter.find_layer("./child.usda")) is False
        # The DIRTY_STATE_CHANGED fan-out may run through
        # ``_on_layer_event`` either synchronously or batched — either
        # way the cached value now reflects the adapter's truth.
        assert vm.get_value_as_bool() is False

    def test_click_does_not_land_on_undo_stack(
        self, adapter, app, model
    ) -> None:
        # ``SaveLayerCommand.non_undoable`` is True — ``push`` runs
        # ``do`` but never appends the command. Prime the stack with
        # a real undoable command first so "empty before, empty after"
        # does not mask a mis-routed append.
        app.undo_manager.push(
            SetLayerMutenessCommand(
                adapter, app.selection_bus, "./child.usda", True,
            )
        )
        depth_before = len(app.undo_manager._undo_stack)
        adapter.set_dirty("./child.usda", True)

        vm = model.get_item_value_model(_child_item(model), 2)
        vm.set_value(True)

        assert len(app.undo_manager._undo_stack) == depth_before

    def test_click_clears_redo_stack(self, adapter, app, model) -> None:
        # Any normal push clears redo — re-verify at the save seam so
        # a future refactor that bypasses the manager (e.g. calling
        # ``cmd.do()`` directly) fails this test.
        app.undo_manager.push(
            SetLayerMutenessCommand(
                adapter, app.selection_bus, "./child.usda", True,
            )
        )
        app.undo_manager.undo()
        assert app.undo_manager.can_redo() is True

        adapter.set_dirty("./child.usda", True)
        vm = model.get_item_value_model(_child_item(model), 2)
        vm.set_value(True)

        assert app.undo_manager.can_redo() is False

    def test_click_on_multiple_rows_pushes_independent_commands(
        self, adapter, app, model
    ) -> None:
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./other.usda")
        adapter.set_dirty("./child.usda", True)
        adapter.set_dirty("./other.usda", True)

        pushed: List[Any] = []
        original_push = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original_push(cmd)
        )[1]

        vm_child = model.get_item_value_model(
            model._items_by_id["./child.usda"], 2
        )
        vm_other = model.get_item_value_model(
            model._items_by_id["./other.usda"], 2
        )
        vm_child.set_value(True)
        vm_other.set_value(True)

        assert len(pushed) == 2
        assert {c._identifier for c in pushed} == {
            "./child.usda", "./other.usda",
        }


# ─── Guards — anonymous / missing / clean / detached short-circuit ──────────


class TestClickGuards:
    def test_click_on_clean_row_pushes_nothing(
        self, adapter, app, model
    ) -> None:
        # Clean rows never display the icon; the value-model guard
        # also short-circuits programmatic calls so a test harness
        # or automation script can't drive an unintended save.
        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)

        vm = model.get_item_value_model(_child_item(model), 2)
        vm.set_value(True)

        assert pushed == []

    def test_click_on_anonymous_row_does_not_push_save_command(
        self, adapter, app, model
    ) -> None:
        # Step 36 — anonymous click now opens the save-as file
        # picker instead of short-circuiting. The picker is modal
        # and resolves asynchronously, so no ``SaveLayerCommand``
        # (nor ``SaveLayerAsCommand``) is pushed synchronously in
        # this test; the push happens inside the dialog's Save
        # handler. Here we verify only that the per-row click does
        # not fire a plain ``SaveLayerCommand`` (which would write
        # through ``adapter.save_layer`` and fail on the anonymous
        # layer).
        session_id = model.session_item.identifier
        adapter._layers[session_id].dirty = True
        model.session_item.invalidate_flags()

        pushed: List[Any] = []
        original_push = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original_push(cmd)
        )[1]

        vm = model.get_item_value_model(model.session_item, 2)
        vm.set_value(True)

        # Any pushed command must NOT be a plain SaveLayerCommand —
        # SaveLayerAsCommand is acceptable if the dialog resolved
        # synchronously (which it won't in this environment, so the
        # list is usually empty).
        assert all(not isinstance(c, SaveLayerCommand) for c in pushed)

    def test_request_save_on_anonymous_layer_routes_to_save_as(
        self, adapter, app, model
    ) -> None:
        # Step 36 — the anonymous branch of ``_request_save`` now
        # forwards to ``_request_save_as`` rather than returning
        # silently. We verify the forwarding by monkey-patching the
        # save-as seam and asserting it gets called with the right
        # item — the dialog itself is covered in the Step-36 tests.
        session_id = model.session_item.identifier
        adapter._layers[session_id].dirty = True
        model.session_item.invalidate_flags()

        save_as_calls: List[Any] = []
        model._request_save_as = lambda item: save_as_calls.append(item)

        model._request_save(model.session_item)

        assert save_as_calls == [model.session_item]

    def test_click_on_missing_row_pushes_nothing(
        self, adapter, app, model
    ) -> None:
        adapter._layers["./child.usda"].missing = True
        adapter._layers["./child.usda"].dirty = True
        _child_item(model).invalidate_flags()

        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)

        vm = model.get_item_value_model(_child_item(model), 2)
        vm.set_value(True)

        assert pushed == []

    def test_click_after_detach_pushes_nothing(
        self, adapter, app, model
    ) -> None:
        adapter.set_dirty("./child.usda", True)
        vm = model.get_item_value_model(_child_item(model), 2)
        model._adapter = None

        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)

        vm.set_value(True)  # must not raise

        assert pushed == []

    def test_request_save_after_destroy_is_noop(
        self, adapter, app, model
    ) -> None:
        # A late click through a torn-down window must not reach a
        # nulled adapter. The model-level guard fires before the
        # command path is touched.
        child = _child_item(model)
        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)
        model.destroy()

        model._request_save(child)  # must not raise

        assert pushed == []


# ─── Headless fallback — app=None preserves the direct-adapter path ─────────


class TestHeadlessFallback:
    def test_click_without_app_falls_back_to_adapter(self) -> None:
        # Unit-test construction passes ``app=None``. The model has
        # no undo manager to push through, so the call routes
        # straight to ``adapter.save_layer`` — matches Step 20's
        # mute-model fallback. Keeps the Step-19 test suite green.
        adapter = MockLayerStackAdapter(include_session=True)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child.usda")
        model = LayerModel(adapter)
        try:
            adapter.set_dirty("./child.usda", True)
            vm = model.get_item_value_model(
                model._items_by_id["./child.usda"], 2,
            )
            vm.set_value(True)
            assert (
                adapter.is_dirty(adapter.find_layer("./child.usda"))
                is False
            )
        finally:
            model.destroy()


# ─── Dirty-state refresh after save — icon clears on DIRTY_STATE_CHANGED ────


class TestDirtyRefreshAfterSave:
    def test_save_click_fires_value_changed_on_save_model(
        self, adapter, app, model
    ) -> None:
        # The adapter emits ``DIRTY_STATE_CHANGED`` when the save
        # clears the bit. The batched flush routes it back into the
        # owning LayerModel, which fires ``_value_changed`` on the
        # cached save model — ovui subscribers observe the repaint
        # signal.
        adapter.set_dirty("./child.usda", True)
        vm = model.get_item_value_model(_child_item(model), 2)
        hits: List[Any] = []
        vm.add_value_changed_fn(lambda m: hits.append(m))

        vm.set_value(True)

        assert hits and hits[-1] is vm

    def test_save_click_emits_single_dirty_event(
        self, adapter, app, model
    ) -> None:
        # A save should fire one ``DIRTY_STATE_CHANGED`` per click —
        # not a burst of them from a re-entrant write path. Keeps
        # the Step-32 batch small.
        adapter.set_dirty("./child.usda", True)
        events: List[Any] = []
        # Hold the subscription — the :class:`Subscription`'s
        # ``__del__`` cancels on GC, so a bare ``subscribe_events``
        # call would drop the listener before the save fires.
        sub = adapter.subscribe_events(lambda e: events.append(e))  # noqa: F841
        vm = model.get_item_value_model(_child_item(model), 2)

        vm.set_value(True)

        dirty_events = [
            e for e in events
            if e.event_type == LayerEventType.DIRTY_STATE_CHANGED
        ]
        assert len(dirty_events) == 1
