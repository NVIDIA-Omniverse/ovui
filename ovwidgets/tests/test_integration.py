# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Integration tests — full pipeline across Application, adapters, and USD stage.

These tests exercise the real Application, real USD stage, and real adapters
together without mocks. They verify cross-component flows:
  - Selection driving the property adapter
  - Undo/redo across the adapter stack
  - Visibility, rename, and delete writing to USD
  - Application lifecycle without crashes

All tests are skipped when the pxr (USD) package is unavailable.
"""

import pytest

try:
    from pxr import Sdf, Usd, UsdGeom
    HAS_USD = True
except ImportError:
    HAS_USD = False

pytestmark = pytest.mark.skipif(not HAS_USD, reason="pxr not available")

from ovwidgets.app.application import Application
from ovwidgets.common.selection import SelectionBus

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singletons():
    """Clear singletons before and after each test."""
    Application._instance = None
    SelectionBus._instance = None
    yield
    Application._instance = None
    SelectionBus._instance = None


@pytest.fixture
def stage():
    """In-memory USD stage with a Sphere and an Xform."""
    s = Usd.Stage.CreateInMemory()
    UsdGeom.Sphere.Define(s, "/Sphere")
    UsdGeom.Xform.Define(s, "/World")
    return s


@pytest.fixture
def app(stage):
    """Headless Application with stage loaded. Shuts down after test."""
    application = Application(headless=True)
    application.open_stage(stage)
    yield application
    application.shutdown()


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_prop_adapter(stage, paths, undo=None):
    from ovui_data_adapters.openusd import UsdPropertyAdapter
    from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
    sa = UsdStageAdapter(stage)
    return UsdPropertyAdapter(stage, paths, undo, sa)


def _identity():
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


# ── File Open → Adapter Wiring ────────────────────────────────────────────────

class TestFileOpenWiring:
    def test_open_stage_creates_stage_adapter(self, app, stage):
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        assert app._stage_adapter is not None
        assert isinstance(app._stage_adapter, UsdStageAdapter)

    def test_stage_adapter_references_correct_stage(self, app, stage):
        assert app._stage_adapter.stage is stage

    def test_open_stage_second_call_replaces_adapter(self, stage):
        app = Application()
        app.open_stage(stage)
        first_adapter = app._stage_adapter

        stage2 = Usd.Stage.CreateInMemory()
        UsdGeom.Cube.Define(stage2, "/Cube")
        app.open_stage(stage2)
        assert app._stage_adapter is not first_adapter
        app.shutdown()


# ── Selection → Property Panel ────────────────────────────────────────────────

class TestSelectionDrivesPropertyPanel:
    def test_sphere_has_radius_attribute(self, app, stage):
        adapter = _make_prop_adapter(stage, ["/Sphere"])
        names = adapter.get_attribute_names()
        assert "radius" in names

    def test_radius_display_name(self, app, stage):
        adapter = _make_prop_adapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert "radius" in meta.display_name.lower()

    def test_sphere_radius_default_value(self, app, stage):
        adapter = _make_prop_adapter(stage, ["/Sphere"])
        value = adapter.get_value("radius")
        assert isinstance(value, float)
        assert value >= 0.0

    def test_multiple_selections_intersection(self, app, stage):
        UsdGeom.Sphere.Define(stage, "/Sphere2")
        adapter = _make_prop_adapter(stage, ["/Sphere", "/Sphere2"])
        names = adapter.get_attribute_names()
        # Both spheres share radius — it must be in the intersection
        assert "radius" in names

    def test_empty_selection_has_no_attributes(self, app, stage):
        adapter = _make_prop_adapter(stage, [])
        assert adapter.get_attribute_names() == []

    def test_selection_change_new_adapter_reflects_new_prim(self, app, stage):
        adapter_sphere = _make_prop_adapter(stage, ["/Sphere"])
        adapter_world = _make_prop_adapter(stage, ["/World"])
        # Sphere has radius; Xform does not
        assert "radius" in adapter_sphere.get_attribute_names()
        assert "radius" not in adapter_world.get_attribute_names()


# ── Undo/Redo Transform ───────────────────────────────────────────────────────

class TestUndoRedoTransform:
    def _make_transform_adapter(self, stage):
        from ovui_data_adapters.openusd import UsdTransformAdapter
        return UsdTransformAdapter(stage)

    def test_batch_transform_command_redo(self, app, stage):
        from ovwidgets.common.undo import BatchTransformCommand
        adapter = self._make_transform_adapter(stage)
        initial = adapter.get_local_transform("/Sphere")
        new_mat = [row[:] for row in initial]
        new_mat[3][0] = 7.0
        cmd = BatchTransformCommand(adapter, "/Sphere", initial, new_mat)
        app.undo_manager.push(cmd)
        result = adapter.get_local_transform("/Sphere")
        assert abs(result[3][0] - 7.0) < 1e-5

    def test_batch_transform_command_undo(self, app, stage):
        from ovwidgets.common.undo import BatchTransformCommand
        adapter = self._make_transform_adapter(stage)
        initial = adapter.get_local_transform("/Sphere")
        new_mat = [row[:] for row in initial]
        new_mat[3][0] = 7.0
        cmd = BatchTransformCommand(adapter, "/Sphere", initial, new_mat)
        app.undo_manager.push(cmd)
        app.undo_manager.undo()
        result = adapter.get_local_transform("/Sphere")
        assert abs(result[3][0] - initial[3][0]) < 1e-5

    def test_batch_transform_command_redo_after_undo(self, app, stage):
        from ovwidgets.common.undo import BatchTransformCommand
        adapter = self._make_transform_adapter(stage)
        initial = adapter.get_local_transform("/Sphere")
        new_mat = [row[:] for row in initial]
        new_mat[3][0] = 7.0
        cmd = BatchTransformCommand(adapter, "/Sphere", initial, new_mat)
        app.undo_manager.push(cmd)
        app.undo_manager.undo()
        app.undo_manager.redo()
        result = adapter.get_local_transform("/Sphere")
        assert abs(result[3][0] - 7.0) < 1e-5

    def test_undo_manager_can_undo_after_push(self, app, stage):
        from ovwidgets.common.undo import BatchTransformCommand
        adapter = self._make_transform_adapter(stage)
        initial = adapter.get_local_transform("/Sphere")
        new_mat = [row[:] for row in initial]
        new_mat[3][1] = 5.0
        cmd = BatchTransformCommand(adapter, "/Sphere", initial, new_mat)
        app.undo_manager.push(cmd)
        assert app.undo_manager.can_undo()

    def test_undo_clears_redo_on_new_push(self, app, stage):
        from ovwidgets.common.undo import BatchTransformCommand
        adapter = self._make_transform_adapter(stage)
        initial = adapter.get_local_transform("/Sphere")
        mat_a = [row[:] for row in initial]
        mat_a[3][0] = 3.0
        cmd_a = BatchTransformCommand(adapter, "/Sphere", initial, mat_a)
        app.undo_manager.push(cmd_a)
        app.undo_manager.undo()
        # Now push a new command — redo stack should be cleared
        current = adapter.get_local_transform("/Sphere")
        mat_b = [row[:] for row in current]
        mat_b[3][0] = 9.0
        cmd_b = BatchTransformCommand(adapter, "/Sphere", current, mat_b)
        app.undo_manager.push(cmd_b)
        assert not app.undo_manager.can_redo()


# ── Visibility Toggle → USD ───────────────────────────────────────────────────

class TestVisibilityToggle:
    def test_set_invisible_writes_to_usd(self, app, stage):
        adapter = app._stage_adapter
        prim = stage.GetPrimAtPath("/Sphere")
        item = adapter.get_item_at_path("/Sphere")
        adapter.set_visibility(item, False)
        imageable = UsdGeom.Imageable(prim)
        assert imageable.ComputeVisibility() == UsdGeom.Tokens.invisible

    def test_set_visible_after_invisible(self, app, stage):
        adapter = app._stage_adapter
        item = adapter.get_item_at_path("/Sphere")
        adapter.set_visibility(item, False)
        adapter.set_visibility(item, True)
        prim = stage.GetPrimAtPath("/Sphere")
        imageable = UsdGeom.Imageable(prim)
        assert imageable.ComputeVisibility() == UsdGeom.Tokens.inherited

    def test_compute_visibility_reflects_usd(self, app, stage):
        from ovui_data_adapters.common import VisibilityState
        adapter = app._stage_adapter
        item = adapter.get_item_at_path("/Sphere")
        adapter.set_visibility(item, False)
        state = adapter.compute_visibility(item)
        assert state == VisibilityState.INVISIBLE


# ── Rename → USD ─────────────────────────────────────────────────────────────

class TestRenameToUsd:
    def test_rename_changes_prim_path(self, app, stage):
        adapter = app._stage_adapter
        item = adapter.get_item_at_path("/Sphere")
        adapter.rename(item, "Ball")
        ball = stage.GetPrimAtPath("/Ball")
        old = stage.GetPrimAtPath("/Sphere")
        assert ball.IsValid()
        assert not old.IsValid()

    def test_rename_returns_new_name(self, app, stage):
        adapter = app._stage_adapter
        item = adapter.get_item_at_path("/Sphere")
        result = adapter.rename(item, "RenamedSphere")
        assert result == "RenamedSphere"

    def test_rename_is_undoable(self, app, stage):
        adapter = app._stage_adapter
        item = adapter.get_item_at_path("/Sphere")
        adapter.rename(item, "Ball")
        assert stage.GetPrimAtPath("/Ball").IsValid()
        app.undo_manager.undo()
        assert stage.GetPrimAtPath("/Sphere").IsValid()
        assert not stage.GetPrimAtPath("/Ball").IsValid()


# ── Delete → USD + Undo ───────────────────────────────────────────────────────

class TestDeleteToUsdWithUndo:
    def test_delete_removes_prim(self, app, stage):
        from ovui_data_adapters.openusd import DeletePrimCommand
        cmd = DeletePrimCommand(stage, Sdf.Path("/Sphere"))
        app.undo_manager.push(cmd)
        assert not stage.GetPrimAtPath("/Sphere").IsValid()

    def test_delete_undo_restores_prim(self, app, stage):
        from ovui_data_adapters.openusd import DeletePrimCommand
        cmd = DeletePrimCommand(stage, Sdf.Path("/Sphere"))
        app.undo_manager.push(cmd)
        app.undo_manager.undo()
        assert stage.GetPrimAtPath("/Sphere").IsValid()

    def test_delete_redo_removes_again(self, app, stage):
        from ovui_data_adapters.openusd import DeletePrimCommand
        cmd = DeletePrimCommand(stage, Sdf.Path("/Sphere"))
        app.undo_manager.push(cmd)
        app.undo_manager.undo()
        app.undo_manager.redo()
        assert not stage.GetPrimAtPath("/Sphere").IsValid()


# ── Application Lifecycle ─────────────────────────────────────────────────────

class TestApplicationLifecycle:
    def test_create_open_shutdown_no_crash(self, stage):
        app = Application(headless=True)
        app.open_stage(stage)
        app.shutdown()
        assert Application._instance is None

    def test_shutdown_resets_singleton(self, stage):
        app = Application(headless=True)
        app.open_stage(stage)
        app.shutdown()
        # Should be able to create a new instance after shutdown
        app2 = Application(headless=True)
        assert Application._instance is app2
        app2.shutdown()

    def test_open_stage_without_run_no_crash(self, stage):
        app = Application(headless=True)
        app.open_stage(stage)
        # No run() — purely headless
        assert app._stage_adapter is not None
        app.shutdown()

    def test_multiple_open_stage_calls_no_leak(self, stage):
        app = Application(headless=True)
        app.open_stage(stage)
        stage2 = Usd.Stage.CreateInMemory()
        UsdGeom.Cube.Define(stage2, "/Cube")
        app.open_stage(stage2)
        # Second open_stage replaced the adapter — stage_adapter now wraps stage2
        assert app._stage_adapter.stage is stage2
        app.shutdown()

    def test_selection_bus_available_before_run(self, stage):
        app = Application(headless=True)
        bus = app.selection_bus
        assert bus is not None
        app.shutdown()

    def test_undo_manager_available_before_run(self, stage):
        app = Application(headless=True)
        um = app.undo_manager
        assert um is not None
        app.shutdown()
