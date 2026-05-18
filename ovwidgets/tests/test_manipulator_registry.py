# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ManipulatorRegistry (Step 49)."""

import pytest

from ovwidgets.viewport.manipulator_registry import ManipulatorRegistry


def _identity():
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _translation_matrix(tx, ty, tz):
    m = _identity()
    m[3][0] = tx
    m[3][1] = ty
    m[3][2] = tz
    return m


class MockTransformAdapter:
    def __init__(self, world_transforms=None):
        self._transforms = world_transforms or {}

    def get_world_transform(self, path):
        return self._transforms.get(path, _identity())

    def get_local_transform(self, path):
        return _identity()

    def set_local_transform(self, path, matrix):
        pass

    def can_transform(self, path):
        return True


class MockTransformModel:
    def __init__(self, transform_adapter):
        self._transform = transform_adapter
        self.set_selection_calls = []

    def set_selection(self, paths):
        self.set_selection_calls.append(list(paths))


class MockManipulator:
    def __init__(self):
        self.shown_at = None
        self.hidden = False

    def show(self, center):
        self.shown_at = list(center)
        self.hidden = False

    def hide(self):
        self.hidden = True
        self.shown_at = None


class TestManipulatorRegistry:
    def _make(self, world_transforms=None):
        adapter = MockTransformAdapter(world_transforms)
        model = MockTransformModel(adapter)
        manip = MockManipulator()
        registry = ManipulatorRegistry(None, model, manip)
        return registry, model, manip

    def test_empty_selection_hides_gizmo(self):
        registry, model, manip = self._make()
        registry.on_selection_changed([])
        assert manip.hidden is True

    def test_empty_selection_gizmo_not_shown(self):
        registry, model, manip = self._make()
        registry.on_selection_changed([])
        assert manip.shown_at is None

    def test_single_prim_shows_gizmo_at_world_origin(self):
        transforms = {"/World/A": _translation_matrix(1.0, 2.0, 3.0)}
        registry, model, manip = self._make(transforms)
        registry.on_selection_changed(["/World/A"])
        assert manip.shown_at == pytest.approx([1.0, 2.0, 3.0])
        assert manip.hidden is False

    def test_multiple_prims_centroid_is_average(self):
        transforms = {
            "/World/A": _translation_matrix(0.0, 0.0, 0.0),
            "/World/B": _translation_matrix(4.0, 2.0, 6.0),
        }
        registry, model, manip = self._make(transforms)
        registry.on_selection_changed(["/World/A", "/World/B"])
        assert manip.shown_at == pytest.approx([2.0, 1.0, 3.0])

    def test_three_prims_centroid(self):
        transforms = {
            "/A": _translation_matrix(0.0, 0.0, 0.0),
            "/B": _translation_matrix(3.0, 6.0, 9.0),
            "/C": _translation_matrix(6.0, 3.0, 0.0),
        }
        registry, model, manip = self._make(transforms)
        registry.on_selection_changed(["/A", "/B", "/C"])
        assert manip.shown_at == pytest.approx([3.0, 3.0, 3.0])

    def test_set_selection_called_on_model(self):
        registry, model, manip = self._make()
        registry.on_selection_changed(["/World/A"])
        assert model.set_selection_calls == [["/World/A"]]

    def test_set_selection_called_with_empty(self):
        registry, model, manip = self._make()
        registry.on_selection_changed([])
        assert model.set_selection_calls == [[]]

    def test_set_selection_called_before_show(self):
        call_order = []
        adapter = MockTransformAdapter()

        class OrderedModel:
            _transform = adapter

            def set_selection(self, paths):
                call_order.append("set_selection")

        class OrderedManip:
            def show(self, center):
                call_order.append("show")

            def hide(self):
                call_order.append("hide")

        registry = ManipulatorRegistry(None, OrderedModel(), OrderedManip())
        registry.on_selection_changed(["/A"])
        assert call_order.index("set_selection") < call_order.index("show")
