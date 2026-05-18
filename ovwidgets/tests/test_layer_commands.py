# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`AbstractLayerCommand` (LAYERS-PLAN Step 28).

Covers every bullet from the plan's **Verify** list plus the edges the
plan calls out explicitly:

- first-``do`` snapshot; subsequent ``do`` / ``redo`` do not
  re-snapshot the (now post-undo) state.
- restore ordering: edit target before :class:`SelectionBus` publish.
- namespaced source string on the undo-phase publish.
- undo-group suppression skips the per-command restore.
- redundant restores elided: no ``set_edit_target`` / ``publish`` when
  the current state already matches the snapshot.
- saved edit target skipped when the layer is gone or no longer
  writable.
- bus mid-publish (``SelectionBusError``) is swallowed so the rest of
  the undo chain keeps running.
"""

from __future__ import annotations

from typing import List, Tuple

import pytest

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.layers import AbstractLayerCommand
from ovwidgets.layers.commands import (
    LAYERS_COMMAND_SOURCE,
    LAYERS_UNDO_SOURCE,
)

# ─── Test-only concrete command ─────────────────────────────────────────────


class _NoOpCommand(AbstractLayerCommand):
    """Concrete :class:`AbstractLayerCommand` that mutates nothing.

    Exists purely so the base class's snapshot / restore lifecycle
    can be exercised without the noise of a real mutation on the
    adapter. Step 28 tests the base, not the subclasses in Step 29+.
    """

    def __init__(self, adapter, bus) -> None:
        super().__init__(adapter, bus)
        self.do_count = 0
        self.undo_count = 0

    def do_impl(self) -> None:
        self.do_count += 1

    def undo_impl(self) -> None:
        self.undo_count += 1


class _TargetSwitchCommand(AbstractLayerCommand):
    """Concrete command that flips the edit target during do_impl.

    Used to pin the ``undo`` → ``_restore_state`` contract: after
    ``undo_impl`` reverts the target flip the base class must still
    restore the pre-command edit-target on top of that (exercises the
    "current != saved" branch in :meth:`_restore_state`).
    """

    def __init__(self, adapter, bus, new_target: str) -> None:
        super().__init__(adapter, bus)
        self._new_target = new_target
        self._prev_target: str = ""

    def do_impl(self) -> None:
        self._prev_target = self._adapter.get_edit_target_identifier()
        self._adapter.set_edit_target(self._new_target)

    def undo_impl(self) -> None:
        self._adapter.set_edit_target(self._prev_target)


# ─── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    """Fresh mock adapter with root + session layers and one sublayer.

    The sublayer gives us a valid target other than root to flip to
    during the restore-ordering tests.
    """
    adapter = MockLayerStackAdapter()
    adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./sub.usda")
    return adapter


@pytest.fixture
def bus() -> SelectionBus:
    """Fresh :class:`SelectionBus` — no singleton pollution across tests."""
    return SelectionBus()


# ─── Base-class shape ────────────────────────────────────────────────────────


class TestBaseClassShape:
    """Static surface checks — the parts other commands depend on."""

    def test_is_command_subclass(self) -> None:
        from ovwidgets.common.undo import Command

        assert issubclass(AbstractLayerCommand, Command)

    def test_cannot_instantiate_abstract_class(
        self, adapter, bus
    ) -> None:
        # do_impl / undo_impl are abstract — a direct construction must
        # fail, otherwise subclasses could forget to override them and
        # silently no-op in production.
        with pytest.raises(TypeError):
            AbstractLayerCommand(adapter, bus)  # type: ignore[abstract]

    def test_source_constants_namespaced(self) -> None:
        # The constants are the whole point of the "source string" work
        # in the plan — pin them so an accidental rename in a later
        # step shows up as a loud test failure rather than a subtle
        # subscriber mis-dispatch.
        assert LAYERS_COMMAND_SOURCE == "ovwidgets.layers:command"
        assert LAYERS_UNDO_SOURCE == "ovwidgets.layers:undo"
        assert LAYERS_COMMAND_SOURCE != LAYERS_UNDO_SOURCE


# ─── Snapshot lifecycle ──────────────────────────────────────────────────────


class TestSnapshotLifecycle:
    def test_do_captures_edit_target_and_selection(
        self, adapter, bus
    ) -> None:
        bus.publish(["/World/A", "/World/B"], source="user")
        adapter.set_edit_target("./sub.usda")

        cmd = _NoOpCommand(adapter, bus)
        cmd.do()

        assert cmd._state_snapshotted is True
        assert cmd._saved_edit_target == "./sub.usda"
        assert cmd._saved_selection == ("/World/A", "/World/B")
        assert cmd.do_count == 1

    def test_do_captures_once_even_if_called_again(
        self, adapter, bus
    ) -> None:
        bus.publish(["/a"], source="user")
        cmd = _NoOpCommand(adapter, bus)
        cmd.do()
        # Caller should never call .do() twice, but if they do the
        # snapshot must still be the original pre-mutation state.
        bus.publish(["/different"], source="user")
        cmd.do()
        assert cmd._saved_selection == ("/a",)
        assert cmd.do_count == 2

    def test_redo_does_not_resnapshot(self, adapter, bus) -> None:
        # The U1 bug in the plan: naive ``redo = do`` would capture
        # the post-undo state as the new "before", breaking the next
        # undo. Our override runs ``do_impl`` only.
        bus.publish(["/before"], source="user")
        cmd = _NoOpCommand(adapter, bus)
        cmd.do()
        cmd.undo()
        bus.publish(["/drifted"], source="user")

        cmd.redo()

        assert cmd._saved_selection == ("/before",)
        assert cmd.do_count == 2  # do + redo both hit do_impl
        assert cmd.undo_count == 1

    def test_redo_runs_do_impl(self, adapter, bus) -> None:
        cmd = _NoOpCommand(adapter, bus)
        cmd.do()
        cmd.undo()
        cmd.redo()
        # After do + undo + redo, the mutation has been applied twice
        # and reversed once — the caller's "current state" should
        # match one completed do.
        assert cmd.do_count == 2
        assert cmd.undo_count == 1


# ─── Undo state restoration ──────────────────────────────────────────────────


class TestUndoRestoresState:
    def test_undo_calls_undo_impl_before_restore(
        self, adapter, bus
    ) -> None:
        # undo_impl must run *first* — the base class's _restore_state
        # looks at adapter state after the mutation has been reversed
        # to decide what it needs to correct (e.g. whether the saved
        # target is still valid).
        bus.publish(["/sel"], source="user")
        order: List[str] = []

        class _RecCommand(AbstractLayerCommand):
            def do_impl(_self) -> None:
                pass

            def undo_impl(_self) -> None:
                order.append("undo_impl")

        cmd = _RecCommand(adapter, bus)
        cmd.do()

        bus_log: List[Tuple[str, str]] = []
        bus.subscribe(
            lambda evt: bus_log.append(("publish", evt.source))
        )

        def _hook(identifier: str) -> None:
            order.append("set_edit_target")

        adapter_orig = adapter.set_edit_target
        adapter.set_edit_target = _hook  # type: ignore[method-assign]
        try:
            bus.publish(["/changed"], source="user")
            cmd.undo()
        finally:
            adapter.set_edit_target = adapter_orig  # type: ignore[method-assign]

        # undo_impl ran before any of the restore-phase adapter /
        # bus calls.
        assert order[0] == "undo_impl"

    def test_undo_restores_edit_target_then_publishes_selection(
        self, adapter, bus
    ) -> None:
        # Pre-mutation state: root is authoring, one prim selected.
        bus.publish(["/World/Ship"], source="user")
        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER

        cmd = _TargetSwitchCommand(adapter, bus, "./sub.usda")
        cmd.do()
        assert adapter.get_edit_target_identifier() == "./sub.usda"

        # Drift both edit target and selection so the restore has
        # something to do on both axes.
        bus.publish(["/World/Other"], source="user")

        order: List[str] = []
        orig_set = adapter.set_edit_target

        def _record_set(identifier: str) -> None:
            order.append(f"set_edit_target({identifier})")
            orig_set(identifier)

        adapter.set_edit_target = _record_set  # type: ignore[method-assign]

        def _record_pub(evt) -> None:
            order.append(
                f"publish({list(evt.snapshot.paths())}, {evt.source})"
            )

        sub = bus.subscribe(_record_pub)  # noqa: F841 — keep alive.

        try:
            cmd.undo()
        finally:
            adapter.set_edit_target = orig_set  # type: ignore[method-assign]

        # undo_impl already restored the target via set_edit_target,
        # then _restore_state sees the current target matches the saved
        # target and therefore skips a redundant second set. The bus
        # publish still happens because the selection drifted.
        pub_idx = next(
            i for i, entry in enumerate(order) if entry.startswith("publish(")
        )
        # All the set_edit_target calls precede the restore publish —
        # the plan's "restore order" contract, tested end-to-end.
        for entry in order[:pub_idx]:
            assert entry.startswith("set_edit_target(")
        assert "publish(['/World/Ship']" in order[pub_idx]
        assert LAYERS_UNDO_SOURCE in order[pub_idx]

    def test_namespaced_source_on_undo_publish(
        self, adapter, bus
    ) -> None:
        # Subscribers use the source to short-circuit their own
        # repaint — if the namespace leaks, every undo causes the
        # Layers window to double-refresh.
        bus.publish(["/p"], source="user")
        cmd = _NoOpCommand(adapter, bus)
        cmd.do()
        bus.publish(["/q"], source="user")

        seen: List[str] = []
        sub = bus.subscribe(lambda evt: seen.append(evt.source))  # noqa: F841

        cmd.undo()

        # Last event fired on the bus during undo must carry the
        # namespaced source, not a generic "undo" / "api".
        assert seen[-1] == LAYERS_UNDO_SOURCE

    def test_no_publish_when_selection_unchanged(
        self, adapter, bus
    ) -> None:
        bus.publish(["/p"], source="user")
        cmd = _NoOpCommand(adapter, bus)
        cmd.do()
        # Selection did NOT drift between do and undo — the restore
        # should short-circuit the publish so subscribers don't get
        # woken up for nothing.
        seen: List[str] = []
        sub = bus.subscribe(lambda evt: seen.append(evt.source))  # noqa: F841

        cmd.undo()

        assert seen == []

    def test_no_set_edit_target_when_unchanged(
        self, adapter, bus
    ) -> None:
        # Pre-mutation state matches; _restore_state must not call
        # adapter.set_edit_target (the adapter would fire a
        # EDIT_TARGET_CHANGED event that LayerModel would treat as a
        # real change).
        cmd = _NoOpCommand(adapter, bus)
        cmd.do()
        calls: List[str] = []
        orig = adapter.set_edit_target
        adapter.set_edit_target = lambda i: calls.append(i) or orig(i)  # type: ignore[method-assign]

        try:
            cmd.undo()
        finally:
            adapter.set_edit_target = orig  # type: ignore[method-assign]

        assert calls == []

    def test_skip_restore_when_saved_target_missing(
        self, bus
    ) -> None:
        # If an in-between command dropped the saved layer, the handle
        # no longer resolves. The restore path must NOT call
        # set_edit_target with a stale identifier — the adapter would
        # raise KeyError.
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "./sub.usda")
        adapter.set_edit_target("./sub.usda")
        cmd = _NoOpCommand(adapter, bus)
        cmd.do()

        # Drop the saved layer by reaching into the mock's backing
        # dict — the real USD adapter models this as a layer that's
        # been unlinked and garbage-collected. The mock's public
        # ``remove_sublayer`` only unlinks parent → child; the layer
        # record itself persists so ``find_layer`` keeps resolving.
        # Clearing ``_layers`` directly is how the USD adapter's
        # ``Sdf.Find(identifier) is None`` case is reproduced here.
        adapter._layers.pop("./sub.usda")
        # And flip the edit target back to a layer that still exists,
        # otherwise get_edit_target_identifier returns a stale id.
        adapter._edit_target_id = ROOT_LAYER_IDENTIFIER
        assert adapter.find_layer("./sub.usda") is None

        calls: List[str] = []
        orig = adapter.set_edit_target
        adapter.set_edit_target = lambda i: calls.append(i) or orig(i)  # type: ignore[method-assign]
        try:
            cmd.undo()  # must not raise
        finally:
            adapter.set_edit_target = orig  # type: ignore[method-assign]

        assert calls == []

    def test_skip_restore_when_saved_target_not_writable(
        self, adapter, bus
    ) -> None:
        # Pre-mutation target: ./sub.usda (writable). The command
        # runs, then something locks it — the restore must skip.
        adapter.set_edit_target("./sub.usda")
        cmd = _NoOpCommand(adapter, bus)
        cmd.do()
        # Flip the target to root, then lock the saved layer.
        adapter.set_edit_target(ROOT_LAYER_IDENTIFIER)
        adapter.set_lock("./sub.usda", True)

        calls: List[str] = []
        orig = adapter.set_edit_target

        def _record(i: str) -> None:
            calls.append(i)
            orig(i)

        adapter.set_edit_target = _record  # type: ignore[method-assign]
        try:
            cmd.undo()
        finally:
            adapter.set_edit_target = orig  # type: ignore[method-assign]

        # set_edit_target may be called zero times (the restore path
        # short-circuits after is_writable returns False). undo_impl
        # in _NoOpCommand doesn't touch the target either.
        assert calls == []
        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER

    def test_selection_bus_error_swallowed(self, adapter) -> None:
        # When the bus is mid-publish we can't re-enter. _restore_state
        # must catch the SelectionBusError and let the rest of the undo
        # chain proceed (F2 in the plan's risk list).
        bus = SelectionBus()

        cmd = _NoOpCommand(adapter, bus)
        cmd.do()

        # Subscribe a handler that triggers the undo mid-publish so
        # the restore's internal .publish() re-enters the bus.
        def _reentry(evt) -> None:
            if evt.source == "user":
                cmd.undo()

        sub = bus.subscribe(_reentry)  # noqa: F841

        # Drift selection so _restore_state actually tries to publish.
        # The call should NOT raise even though we end up re-entering.
        bus.publish(["/x"], source="user")


# ─── Group-aware suppression ─────────────────────────────────────────────────


class TestSuppressStateRestoreInGroup:
    def test_default_is_false(self) -> None:
        # The class-level default is False so a command outside any
        # group restores state on its own. Step 28.5's group wrapper
        # is the sole caller that flips this to True.
        assert AbstractLayerCommand._suppress_state_restore is False

    def test_suppression_skips_restore(self, adapter, bus) -> None:
        bus.publish(["/p"], source="user")
        cmd = _NoOpCommand(adapter, bus)
        cmd.do()
        # Drift state so _restore_state WOULD normally publish +
        # set_edit_target — we expect neither to happen.
        bus.publish(["/q"], source="user")

        cmd._suppress_state_restore = True
        seen: List[str] = []
        sub = bus.subscribe(lambda evt: seen.append(evt.source))  # noqa: F841

        cmd.undo()

        assert seen == []  # no publish → group wrapper owns the restore
        assert cmd.undo_count == 1  # undo_impl still ran

    def test_three_commands_undo_once_with_group_restore(
        self, adapter, bus
    ) -> None:
        # Simulate a three-command group. In real use Step 28.5's
        # UndoGroup.undo would call _restore_state on the outermost
        # command exactly once; here we drive that contract by hand.
        bus.publish(["/initial"], source="user")
        cmds = [_NoOpCommand(adapter, bus) for _ in range(3)]
        for c in cmds:
            c.do()
            c._suppress_state_restore = True

        # Drift state across the group.
        bus.publish(["/middle"], source="user")

        seen: List[str] = []
        sub = bus.subscribe(lambda evt: seen.append(evt.source))  # noqa: F841

        for c in reversed(cmds):
            c.undo()

        # Per-command undo suppressed all publishes.
        assert seen == []

        # The group wrapper would run a single restore now. Fire the
        # outermost command's _restore_state by hand and confirm the
        # saved selection is re-published exactly once.
        cmds[0]._restore_state()

        assert seen == [LAYERS_UNDO_SOURCE]
        assert bus.get_snapshot().paths() == ["/initial"]


# ─── Saved-state persistence through redo cycles ─────────────────────────────


class TestRedoPreservesSnapshot:
    def test_undo_redo_undo_restores_original_each_time(
        self, adapter, bus
    ) -> None:
        # Pin the plan's "test_snapshot_only_on_first_do" verify bullet:
        # undo → redo → undo; the state snapshot is identical across
        # both undos.
        bus.publish(["/original"], source="user")
        adapter.set_edit_target("./sub.usda")

        cmd = _TargetSwitchCommand(adapter, bus, ROOT_LAYER_IDENTIFIER)
        cmd.do()

        bus.publish(["/drift"], source="user")

        cmd.undo()
        # Post-first-undo: back to original snapshot.
        assert bus.get_snapshot().paths() == ["/original"]
        assert adapter.get_edit_target_identifier() == "./sub.usda"

        cmd.redo()
        # Drift again between redo and the second undo to prove the
        # snapshot was NOT overwritten by redo.
        bus.publish(["/drift2"], source="user")

        cmd.undo()
        assert bus.get_snapshot().paths() == ["/original"]
        assert adapter.get_edit_target_identifier() == "./sub.usda"
