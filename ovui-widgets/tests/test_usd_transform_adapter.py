# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

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


class TestCanTransform:
    def test_valid_prim_returns_true(self, adapter):
        assert adapter.can_transform("/Sphere") is True

    def test_invalid_path_returns_false(self, adapter):
        assert adapter.can_transform("/DoesNotExist") is False
