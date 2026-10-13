# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for UsdTransformAdapter (skipped when USD is unavailable)."""

import pytest

try:
    from pxr import Usd, UsdGeom
    HAS_USD = True
except ImportError:
    HAS_USD = False

pytestmark = pytest.mark.skipif(not HAS_USD, reason="pxr not available")


@pytest.fixture
def stage_with_sphere():
    stage = Usd.Stage.CreateInMemory()
    sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
    UsdGeom.XformCommonAPI(sphere).SetTranslate((1.0, 2.0, 3.0))
    return stage


@pytest.fixture
def adapter(stage_with_sphere):
    from ovui_data_adapters.openusd import UsdTransformAdapter
    return UsdTransformAdapter(stage_with_sphere)


class TestGetLocalTransform:
    def test_returns_4x4(self, adapter):
        mat = adapter.get_local_transform("/Sphere")
        assert len(mat) == 4
        assert all(len(row) == 4 for row in mat)

    def test_translation_in_row3(self, adapter):
        mat = adapter.get_local_transform("/Sphere")
        assert abs(mat[3][0] - 1.0) < 1e-5
        assert abs(mat[3][1] - 2.0) < 1e-5
        assert abs(mat[3][2] - 3.0) < 1e-5

    def test_invalid_path_returns_identity(self, adapter):
        mat = adapter.get_local_transform("/DoesNotExist")
        assert len(mat) == 4
        assert mat[0][0] == pytest.approx(1.0)
        assert mat[0][1] == pytest.approx(0.0)

    def test_returns_plain_lists(self, adapter):
        mat = adapter.get_local_transform("/Sphere")
        assert isinstance(mat, list)
        assert isinstance(mat[0], list)
        assert isinstance(mat[0][0], float)


class TestGetWorldTransform:
    def test_returns_4x4(self, adapter):
        mat = adapter.get_world_transform("/Sphere")
        assert len(mat) == 4
        assert all(len(row) == 4 for row in mat)

    def test_returns_plain_lists(self, adapter):
        mat = adapter.get_world_transform("/Sphere")
        assert isinstance(mat, list)
        assert isinstance(mat[0], list)

    def test_root_prim_world_matches_local(self, stage_with_sphere):
        from ovui_data_adapters.openusd import UsdTransformAdapter
        adapter = UsdTransformAdapter(stage_with_sphere)
        local = adapter.get_local_transform("/Sphere")
        world = adapter.get_world_transform("/Sphere")
        assert abs(world[3][0] - local[3][0]) < 1e-5


class TestSetLocalTransform:
    def test_set_changes_prim(self, adapter, stage_with_sphere):
        new_matrix = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [10.0, 20.0, 30.0, 1.0],
        ]
        adapter.set_local_transform("/Sphere", new_matrix)
        mat = adapter.get_local_transform("/Sphere")
        assert abs(mat[3][0] - 10.0) < 1e-5
        assert abs(mat[3][1] - 20.0) < 1e-5
        assert abs(mat[3][2] - 30.0) < 1e-5

    def test_set_invalid_path_no_crash(self, adapter):
        adapter.set_local_transform("/DoesNotExist", [[1, 0, 0, 0]] * 4)


class TestAuthoredTransformHistory:
    def test_undo_redo_round_trips_authored_xform_structure(self):
        from ovui_data_adapters.openusd import UsdTransformAdapter

        from ovui_widgets.common.undo import BatchTransformCommand, UndoManager

        stage = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Xform.Define(stage, "/Object")
        common = UsdGeom.XformCommonAPI(prim)
        common.SetTranslate((1.0, 2.0, 3.0))
        common.SetRotate((10.0, 20.0, 30.0))
        common.SetScale((1.0, 2.0, 3.0))
        adapter = UsdTransformAdapter(stage)
        initial = adapter.get_local_transform("/Object")
        final = [row[:] for row in initial]
        final[3][0] += 4.0
        layer = stage.GetRootLayer()
        authored_before = layer.ExportToString()

        undo = UndoManager()
        undo.push(BatchTransformCommand(adapter, "/Object", initial, final))
        authored_after = layer.ExportToString()
        assert authored_after != authored_before

        assert undo.undo() is True
        assert layer.ExportToString() == authored_before
        assert undo.redo() is True
        assert layer.ExportToString() == authored_after


class TestCanTransform:
    def test_valid_prim_returns_true(self, adapter):
        assert adapter.can_transform("/Sphere") is True

    def test_invalid_path_returns_false(self, adapter):
        assert adapter.can_transform("/DoesNotExist") is False
