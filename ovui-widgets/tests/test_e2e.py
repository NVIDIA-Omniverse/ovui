# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""End-to-end smoke tests for the OvGear pipeline — Step 67.

Exercises the full open→select→move→undo→redo sequence using both mock
adapters (no USD required) and a real Usd.Stage (pxr required, skipped if
absent). These tests are the primary regression guard for future refactors.
"""

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def undo():
    from ovui_widgets.common.undo import UndoManager
    return UndoManager()


@pytest.fixture
def bus():
    from ovui_widgets.common.selection import SelectionBus
    return SelectionBus()


@pytest.fixture
def transform():
    from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
    return MockTransformAdapter()


# ---------------------------------------------------------------------------
# SelectionBus E2E
# ---------------------------------------------------------------------------

class TestSelectionBusE2E:
    def test_publish_and_read_back(self, bus):
        bus.publish(['/World/Sphere'], source='test')
        assert bus.get_snapshot().paths() == ['/World/Sphere']

    def test_initial_snapshot_empty(self, bus):
        snap = bus.get_snapshot()
        assert snap.paths() == []
        assert not snap

    def test_publish_replaces_previous_selection(self, bus):
        bus.publish(['/A'], source='test')
        bus.publish(['/B', '/C'], source='test')
        assert bus.get_snapshot().paths() == ['/B', '/C']

    def test_clear_empties_selection(self, bus):
        bus.publish(['/A'], source='test')
        bus.clear()
        assert bus.get_snapshot().paths() == []

    def test_subscriber_receives_event(self, bus):
        received = []
        sub = bus.subscribe(lambda e: received.append(e.snapshot.paths()))  # noqa: F841
        bus.publish(['/Sphere'], source='test')
        assert received == [['/Sphere']]

    def test_subscriber_sees_source(self, bus):
        events = []
        sub = bus.subscribe(lambda e: events.append(e.source))  # noqa: F841
        bus.publish(['/A'], source='tool')
        assert events == ['tool']

    def test_multi_item_selection_length(self, bus):
        bus.publish(['/A', '/B', '/C'], source='test')
        assert len(bus.get_snapshot()) == 3

    def test_reentrant_publish_raises(self, bus):
        from ovui_widgets.common.selection import SelectionBusError

        def bad_cb(event):
            bus.publish(['/X'], source='inner')

        sub = bus.subscribe(bad_cb)  # noqa: F841
        with pytest.raises(SelectionBusError):
            bus.publish(['/A'], source='test')


# ---------------------------------------------------------------------------
# BatchTransformCommand E2E
# ---------------------------------------------------------------------------

class TestBatchTransformCommandE2E:
    def test_do_sets_transform(self, transform):
        from ovui_widgets.common.undo import BatchTransformCommand

        initial = transform.get_local_transform('/Sphere')
        final = [row[:] for row in initial]
        final[3][0] = 5.0
        cmd = BatchTransformCommand(transform, '/Sphere', initial, final)
        cmd.do()
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 5.0) < 1e-9

    def test_undo_reverts_transform(self, transform):
        from ovui_widgets.common.undo import BatchTransformCommand

        initial = transform.get_local_transform('/Sphere')
        final = [row[:] for row in initial]
        final[3][0] = 5.0
        cmd = BatchTransformCommand(transform, '/Sphere', initial, final)
        cmd.do()
        cmd.undo()
        assert abs(transform.get_local_transform('/Sphere')[3][0]) < 1e-9

    def test_redo_reapplies_transform(self, transform):
        from ovui_widgets.common.undo import BatchTransformCommand

        initial = transform.get_local_transform('/Sphere')
        final = [row[:] for row in initial]
        final[3][0] = 5.0
        cmd = BatchTransformCommand(transform, '/Sphere', initial, final)
        cmd.do()
        cmd.undo()
        cmd.redo()
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 5.0) < 1e-9

    def test_initial_stored_as_copy(self, transform):
        """Mutating caller's initial matrix after construction does not corrupt undo."""
        from ovui_widgets.common.undo import BatchTransformCommand

        initial = transform.get_local_transform('/Sphere')
        final = [row[:] for row in initial]
        final[3][0] = 5.0
        cmd = BatchTransformCommand(transform, '/Sphere', initial, final)
        initial[3][0] = 999.0  # mutate caller reference
        cmd.do()
        cmd.undo()
        assert abs(transform.get_local_transform('/Sphere')[3][0]) < 1e-9

    def test_final_stored_as_copy(self, transform):
        """Mutating caller's final matrix after construction does not corrupt redo."""
        from ovui_widgets.common.undo import BatchTransformCommand

        initial = transform.get_local_transform('/Sphere')
        final = [row[:] for row in initial]
        final[3][0] = 5.0
        cmd = BatchTransformCommand(transform, '/Sphere', initial, final)
        final[3][0] = 999.0  # mutate caller reference
        cmd.do()
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 5.0) < 1e-9


# ---------------------------------------------------------------------------
# UndoManager E2E
# ---------------------------------------------------------------------------

class TestUndoManagerE2E:
    def test_push_executes_command(self, transform, undo):
        from ovui_widgets.common.undo import BatchTransformCommand

        initial = transform.get_local_transform('/Sphere')
        final = [row[:] for row in initial]
        final[3][0] = 3.0
        undo.push(BatchTransformCommand(transform, '/Sphere', initial, final))
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 3.0) < 1e-9

    def test_push_then_undo(self, transform, undo):
        from ovui_widgets.common.undo import BatchTransformCommand

        initial = transform.get_local_transform('/Sphere')
        final = [row[:] for row in initial]
        final[3][0] = 3.0
        undo.push(BatchTransformCommand(transform, '/Sphere', initial, final))
        undo.undo()
        assert abs(transform.get_local_transform('/Sphere')[3][0]) < 1e-9

    def test_undo_redo_cycle(self, transform, undo):
        from ovui_widgets.common.undo import BatchTransformCommand

        initial = transform.get_local_transform('/Sphere')
        final = [row[:] for row in initial]
        final[3][0] = 3.0
        undo.push(BatchTransformCommand(transform, '/Sphere', initial, final))
        undo.undo()
        undo.redo()
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 3.0) < 1e-9

    def test_undo_empty_returns_false(self, undo):
        assert undo.undo() is False

    def test_redo_empty_returns_false(self, undo):
        assert undo.redo() is False

    def test_push_clears_redo_stack(self, transform, undo):
        from ovui_widgets.common.undo import BatchTransformCommand

        initial = transform.get_local_transform('/Sphere')
        m1 = [row[:] for row in initial]
        m1[3][0] = 3.0
        undo.push(BatchTransformCommand(transform, '/Sphere', initial, m1))
        undo.undo()
        assert undo.can_redo()
        m2 = [row[:] for row in initial]
        m2[3][0] = 7.0
        undo.push(BatchTransformCommand(transform, '/Sphere', initial, m2))
        assert not undo.can_redo()

    def test_multiple_commands_undo_in_order(self, transform, undo):
        from ovui_widgets.common.undo import BatchTransformCommand

        base = transform.get_local_transform('/Sphere')
        m1 = [row[:] for row in base]; m1[3][0] = 1.0
        m2 = [row[:] for row in base]; m2[3][0] = 2.0
        m3 = [row[:] for row in base]; m3[3][0] = 3.0
        undo.push(BatchTransformCommand(transform, '/Sphere', base, m1))
        undo.push(BatchTransformCommand(transform, '/Sphere', m1, m2))
        undo.push(BatchTransformCommand(transform, '/Sphere', m2, m3))
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 3.0) < 1e-9
        undo.undo()
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 2.0) < 1e-9
        undo.undo()
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 1.0) < 1e-9
        undo.undo()
        assert abs(transform.get_local_transform('/Sphere')[3][0]) < 1e-9

    def test_group_counts_as_single_undo(self, transform, undo):
        from ovui_widgets.common.undo import BatchTransformCommand

        base_a = transform.get_local_transform('/A')
        m_a = [row[:] for row in base_a]; m_a[3][0] = 1.0
        base_b = transform.get_local_transform('/B')
        m_b = [row[:] for row in base_b]; m_b[3][0] = 2.0

        undo.begin_group("Move")
        undo.push(BatchTransformCommand(transform, '/A', base_a, m_a))
        undo.push(BatchTransformCommand(transform, '/B', base_b, m_b))
        undo.end_group()

        undo.undo()
        assert abs(transform.get_local_transform('/A')[3][0]) < 1e-9
        assert abs(transform.get_local_transform('/B')[3][0]) < 1e-9
        assert not undo.can_undo()

    def test_can_undo_can_redo_transitions(self, transform, undo):
        from ovui_widgets.common.undo import BatchTransformCommand

        assert not undo.can_undo()
        assert not undo.can_redo()
        base = transform.get_local_transform('/Sphere')
        m = [row[:] for row in base]; m[3][0] = 1.0
        undo.push(BatchTransformCommand(transform, '/Sphere', base, m))
        assert undo.can_undo()
        assert not undo.can_redo()
        undo.undo()
        assert not undo.can_undo()
        assert undo.can_redo()

    def test_clear_resets_both_stacks(self, transform, undo):
        from ovui_widgets.common.undo import BatchTransformCommand

        base = transform.get_local_transform('/Sphere')
        m = [row[:] for row in base]; m[3][0] = 1.0
        undo.push(BatchTransformCommand(transform, '/Sphere', base, m))
        undo.clear()
        assert not undo.can_undo()
        assert not undo.can_redo()


# ---------------------------------------------------------------------------
# Full mock pipeline E2E
# ---------------------------------------------------------------------------

class TestFullPipelineE2E:
    def test_open_select_move_undo_redo(self):
        """Full pipeline with mock adapters — the primary regression test."""
        from ovui_widgets.common.selection import SelectionBus
        from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
        from ovui_widgets.common.undo import BatchTransformCommand, UndoManager

        bus = SelectionBus()
        transform = MockTransformAdapter()
        um = UndoManager()

        # 1. Select
        bus.publish(['/World/Sphere'], source='viewport')
        assert bus.get_snapshot().paths() == ['/World/Sphere']

        # 2. Move
        initial = transform.get_local_transform('/World/Sphere')
        final = [row[:] for row in initial]
        final[3][0] = 3.0
        um.push(BatchTransformCommand(transform, '/World/Sphere', initial, final))
        assert abs(transform.get_local_transform('/World/Sphere')[3][0] - 3.0) < 1e-5

        # 3. Undo
        um.undo()
        assert abs(transform.get_local_transform('/World/Sphere')[3][0]) < 1e-5

        # 4. Redo
        um.redo()
        assert abs(transform.get_local_transform('/World/Sphere')[3][0] - 3.0) < 1e-5

    def test_clear_selection_does_not_affect_undo_history(self):
        from ovui_widgets.common.selection import SelectionBus
        from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
        from ovui_widgets.common.undo import BatchTransformCommand, UndoManager

        bus = SelectionBus()
        transform = MockTransformAdapter()
        um = UndoManager()

        bus.publish(['/Sphere'], source='test')
        initial = transform.get_local_transform('/Sphere')
        final = [row[:] for row in initial]; final[3][0] = 5.0
        um.push(BatchTransformCommand(transform, '/Sphere', initial, final))

        bus.clear()
        assert bus.get_snapshot().paths() == []
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 5.0) < 1e-5
        um.undo()
        assert abs(transform.get_local_transform('/Sphere')[3][0]) < 1e-5

    def test_empty_selection_undo_noop(self):
        from ovui_widgets.common.selection import SelectionBus
        from ovui_widgets.common.undo import UndoManager

        bus = SelectionBus()
        um = UndoManager()
        bus.publish([], source='test')
        assert um.undo() is False
        assert um.redo() is False

    def test_sequential_moves_undo_chain(self):
        from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
        from ovui_widgets.common.undo import BatchTransformCommand, UndoManager

        transform = MockTransformAdapter()
        um = UndoManager()
        base = transform.get_local_transform('/Prim')

        positions = [1.0, 2.0, 5.0]
        prev = base
        for x in positions:
            nxt = [row[:] for row in prev]; nxt[3][0] = x
            um.push(BatchTransformCommand(transform, '/Prim', prev, nxt))
            prev = nxt

        assert abs(transform.get_local_transform('/Prim')[3][0] - 5.0) < 1e-5
        for expected in [2.0, 1.0, 0.0]:
            um.undo()
            assert abs(transform.get_local_transform('/Prim')[3][0] - expected) < 1e-5

    def test_redo_after_full_undo_chain(self):
        from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
        from ovui_widgets.common.undo import BatchTransformCommand, UndoManager

        transform = MockTransformAdapter()
        um = UndoManager()
        base = transform.get_local_transform('/Prim')

        positions = [1.0, 2.0, 3.0]
        prev = base
        for x in positions:
            nxt = [row[:] for row in prev]; nxt[3][0] = x
            um.push(BatchTransformCommand(transform, '/Prim', prev, nxt))
            prev = nxt

        for _ in positions:
            um.undo()
        for x in positions:
            um.redo()
            assert abs(transform.get_local_transform('/Prim')[3][0] - x) < 1e-5


# ---------------------------------------------------------------------------
# Application-level E2E
# ---------------------------------------------------------------------------

class TestApplicationE2E:
    def test_application_has_undo_manager(self, headless_app):
        from ovui_widgets.common.undo import UndoManager
        assert isinstance(headless_app.undo_manager, UndoManager)

    def test_application_has_selection_bus(self, headless_app):
        from ovui_widgets.common.selection import SelectionBus
        assert isinstance(headless_app.selection_bus, SelectionBus)

    def test_application_selection_publish(self, headless_app):
        headless_app.selection_bus.publish(['/World/Sphere'], source='test')
        assert headless_app.selection_bus.get_snapshot().paths() == ['/World/Sphere']

    def test_application_undo_manager_push_undo(self, headless_app):
        from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
        from ovui_widgets.common.undo import BatchTransformCommand

        transform = MockTransformAdapter()
        initial = transform.get_local_transform('/Sphere')
        final = [row[:] for row in initial]; final[3][0] = 7.0
        headless_app.undo_manager.push(
            BatchTransformCommand(transform, '/Sphere', initial, final)
        )
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 7.0) < 1e-9
        headless_app.undo_manager.undo()
        assert abs(transform.get_local_transform('/Sphere')[3][0]) < 1e-9

    def test_application_double_create_raises(self, headless_app):
        from ovui_widgets.app.application import Application
        with pytest.raises(AssertionError):
            Application()

    def test_application_shutdown_allows_recreate(self):
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus

        Application._instance = None
        SelectionBus._instance = None
        app = Application()
        app.shutdown()
        app2 = Application()
        assert Application._instance is app2
        app2.shutdown()


# ---------------------------------------------------------------------------
# USD-backed E2E (skipped if pxr unavailable)
# ---------------------------------------------------------------------------

class TestUsdPipelineE2E:
    """Full open→select→move→undo→redo with a real Usd.Stage."""

    @pytest.fixture(autouse=True)
    def _require_pxr(self):
        pytest.importorskip("pxr")

    def test_open_stage_sets_adapter(self, headless_app):
        from pxr import Usd, UsdGeom
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, '/Sphere')
        headless_app.open_stage(stage)
        assert headless_app._stage_adapter is not None

    def test_open_stage_replaces_adapter(self, headless_app):
        from pxr import Usd
        stage1 = Usd.Stage.CreateInMemory()
        stage2 = Usd.Stage.CreateInMemory()
        headless_app.open_stage(stage1)
        adapter1 = headless_app._stage_adapter
        headless_app.open_stage(stage2)
        assert headless_app._stage_adapter is not adapter1

    def test_select_via_bus(self, headless_app):
        from pxr import Usd, UsdGeom
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, '/Sphere')
        headless_app.open_stage(stage)
        headless_app.selection_bus.publish(['/Sphere'], source='test')
        assert headless_app.selection_bus.get_snapshot().paths() == ['/Sphere']

    def test_full_open_select_move_undo_redo(self, headless_app):
        """The canonical E2E smoke test — full pipeline with USD."""
        from ovui_data_adapters.openusd import UsdTransformAdapter
        from pxr import Usd, UsdGeom

        from ovui_widgets.common.undo import BatchTransformCommand

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, '/Sphere')
        headless_app.open_stage(stage)

        # Select
        headless_app.selection_bus.publish(['/Sphere'], source='test')
        assert headless_app.selection_bus.get_snapshot().paths() == ['/Sphere']

        # Move
        transform = UsdTransformAdapter(stage)
        initial = transform.get_local_transform('/Sphere')
        final = [row[:] for row in initial]
        final[3][0] = 3.0
        cmd = BatchTransformCommand(transform, '/Sphere', initial, final)
        headless_app.undo_manager.push(cmd)
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 3.0) < 1e-5

        # Undo
        headless_app.undo_manager.undo()
        assert abs(transform.get_local_transform('/Sphere')[3][0]) < 1e-5

        # Redo
        headless_app.undo_manager.redo()
        assert abs(transform.get_local_transform('/Sphere')[3][0] - 3.0) < 1e-5

    def test_usd_multiple_prims_undo_group(self, headless_app):
        from ovui_data_adapters.openusd import UsdTransformAdapter
        from pxr import Usd, UsdGeom

        from ovui_widgets.common.undo import BatchTransformCommand

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, '/Sphere')
        UsdGeom.Cube.Define(stage, '/Cube')
        headless_app.open_stage(stage)

        transform = UsdTransformAdapter(stage)
        init_s = transform.get_local_transform('/Sphere')
        fin_s = [row[:] for row in init_s]; fin_s[3][0] = 1.0
        init_c = transform.get_local_transform('/Cube')
        fin_c = [row[:] for row in init_c]; fin_c[3][0] = 2.0

        headless_app.undo_manager.begin_group("MoveAll")
        headless_app.undo_manager.push(
            BatchTransformCommand(transform, '/Sphere', init_s, fin_s)
        )
        headless_app.undo_manager.push(
            BatchTransformCommand(transform, '/Cube', init_c, fin_c)
        )
        headless_app.undo_manager.end_group()

        headless_app.undo_manager.undo()
        assert abs(transform.get_local_transform('/Sphere')[3][0]) < 1e-5
        assert abs(transform.get_local_transform('/Cube')[3][0]) < 1e-5
        assert not headless_app.undo_manager.can_undo()
