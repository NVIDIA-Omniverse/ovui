# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for TransformAdapter ABC and MockTransformAdapter."""

import pytest
from ovui_data_adapters.common import TransformAdapter

from ovui_widgets.common.testing.mock_transform import MockTransformAdapter


class TestTransformAdapterABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            TransformAdapter()

    def test_abstract_methods_exist(self):
        for name in ("get_local_transform", "get_world_transform",
                     "set_local_transform", "can_transform"):
            assert hasattr(TransformAdapter, name)

    def test_all_methods_are_abstract(self):
        for name in ("get_local_transform", "get_world_transform",
                     "set_local_transform", "can_transform"):
            assert name in TransformAdapter.__abstractmethods__

    def test_no_extra_abstract_methods(self):
        assert TransformAdapter.__abstractmethods__ == frozenset(
            {"get_local_transform", "get_world_transform",
             "set_local_transform", "can_transform"}
        )


class TestMockTransformAdapterGetSet:
    def test_get_unset_path_returns_identity(self):
        adapter = MockTransformAdapter()
        mat = adapter.get_local_transform("/World/Cube")
        assert len(mat) == 4
        assert len(mat[0]) == 4
        assert mat[0][0] == 1.0 and mat[1][1] == 1.0
        assert mat[0][1] == 0.0

    def test_set_get_roundtrip(self):
        adapter = MockTransformAdapter()
        matrix = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [1.0, 2.0, 3.0, 1.0],
        ]
        adapter.set_local_transform("/World/Cube", matrix)
        result = adapter.get_local_transform("/World/Cube")
        assert result[3][0] == pytest.approx(1.0)
        assert result[3][1] == pytest.approx(2.0)
        assert result[3][2] == pytest.approx(3.0)

    def test_get_returns_copy(self):
        adapter = MockTransformAdapter()
        matrix = [[float(i * 4 + j) for j in range(4)] for i in range(4)]
        adapter.set_local_transform("/World/A", matrix)
        result1 = adapter.get_local_transform("/World/A")
        result1[0][0] = 999.0
        result2 = adapter.get_local_transform("/World/A")
        assert result2[0][0] == matrix[0][0]

    def test_set_does_not_alias_input(self):
        adapter = MockTransformAdapter()
        matrix = [[1.0, 0.0, 0.0, 0.0]] * 4
        adapter.set_local_transform("/World/B", matrix)
        matrix[0][0] = 999.0
        result = adapter.get_local_transform("/World/B")
        assert result[0][0] == 1.0

    def test_world_transform_matches_local(self):
        adapter = MockTransformAdapter()
        matrix = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [5.0, 6.0, 7.0, 1.0],
        ]
        adapter.set_local_transform("/World/C", matrix)
        assert adapter.get_world_transform("/World/C") == adapter.get_local_transform("/World/C")

    def test_multiple_paths_independent(self):
        adapter = MockTransformAdapter()
        mat1 = [[1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [1.0, 0.0, 0.0, 1.0]]
        mat2 = [[1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 2.0, 0.0, 1.0]]
        adapter.set_local_transform("/A", mat1)
        adapter.set_local_transform("/B", mat2)
        assert adapter.get_local_transform("/A")[3][0] == pytest.approx(1.0)
        assert adapter.get_local_transform("/B")[3][1] == pytest.approx(2.0)


class TestMockTransformAdapterCanTransform:
    def test_can_transform_default_true(self):
        adapter = MockTransformAdapter()
        assert adapter.can_transform("/World/Cube") is True

    def test_can_transform_any_path_default(self):
        adapter = MockTransformAdapter()
        assert adapter.can_transform("/") is True
        assert adapter.can_transform("/A/B/C") is True

    def test_blocked_path_returns_false(self):
        adapter = MockTransformAdapter(blocked={"/World/Locked"})
        assert adapter.can_transform("/World/Locked") is False

    def test_non_blocked_path_still_true(self):
        adapter = MockTransformAdapter(blocked={"/World/Locked"})
        assert adapter.can_transform("/World/Free") is True

    def test_multiple_blocked_paths(self):
        adapter = MockTransformAdapter(blocked={"/A", "/B"})
        assert adapter.can_transform("/A") is False
        assert adapter.can_transform("/B") is False
        assert adapter.can_transform("/C") is True
