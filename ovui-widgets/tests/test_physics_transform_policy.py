# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Viewport transform controls follow adapter-owned physics edit policy."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ovui_data_adapters.common import TransformEditMode, TransformEditPolicy
from ovui_widgets.common.snap import GridSnapProvider, SnapSystem
from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.viewport.prim_transform_model import PrimTransformModel
from ovui_widgets.viewport.transform_manipulator import TOOL_TRANSLATE
from ovui_widgets.viewport.viewport_widget import ViewportWidget


_DYNAMIC = "/World/DynamicBody"
_KINEMATIC = "/World/KinematicBody"
_BLOCKED = "/World/BlockedBody"
_IDENTITY = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]
_DELTA = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [4.0, 0.0, 0.0, 1.0],
]


def _delta(x: float, y: float = 0.0, z: float = 0.0) -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [float(x), float(y), float(z), 1.0],
    ]


def _enabled_grid_snap() -> SnapSystem:
    snap = SnapSystem()
    snap.enable(True)
    snap.add_provider(GridSnapProvider(1.0))
    return snap


class _PolicyTransformAdapter(MockTransformAdapter):
    def __init__(self, policies: dict[str, TransformEditPolicy]) -> None:
        super().__init__()
        self._policies = dict(policies)
        self.direct_writes: list[tuple[str, list[list[float]]]] = []
        self.control_targets: list[tuple[str, list[list[float]]]] = []

    def get_transform_edit_policy(self, path: str) -> TransformEditPolicy:
        return self._policies.get(path, TransformEditPolicy(TransformEditMode.DIRECT))

    def can_transform(self, path: str) -> bool:
        return self.get_transform_edit_policy(path).is_editable

    def set_local_transform(self, path: str, matrix: list[list[float]]) -> None:
        policy = self.get_transform_edit_policy(path)
        if policy.mode is TransformEditMode.BLOCKED:
            raise AssertionError("blocked transform should not be written")
        copied = [row[:] for row in matrix]
        if policy.mode is TransformEditMode.REDIRECTED:
            self.control_targets.append((path, copied))
            return
        self.direct_writes.append((path, copied))
        super().set_local_transform(path, matrix)


def _make_stage() -> MagicMock:
    stage = MagicMock()
    stage.suppress_change_notifications.side_effect = lambda: _cm()
    return stage


@contextmanager
def _cm():
    yield


def _model(transform: _PolicyTransformAdapter) -> PrimTransformModel:
    return PrimTransformModel(transform, _make_stage(), UndoManager())


def _translation(matrix: list[list[float]]) -> tuple[float, float, float]:
    return (float(matrix[3][0]), float(matrix[3][1]), float(matrix[3][2]))


def test_paused_body_keeps_transform_controls_enabled_and_writes_runtime_transform() -> None:
    transform = _PolicyTransformAdapter(
        {_DYNAMIC: TransformEditPolicy(TransformEditMode.DIRECT)}
    )
    transform.set_local_transform(_DYNAMIC, [row[:] for row in _IDENTITY])
    model = _model(transform)

    model.set_selection([_DYNAMIC])
    model.on_drag_start()
    model.on_drag_moved(_DELTA)

    assert model.transform_controls_enabled() is True
    assert transform.direct_writes == [(_DYNAMIC, _IDENTITY)]
    assert model._live_transforms[_DYNAMIC][3][0] == pytest.approx(4.0)
    assert transform.get_local_transform(_DYNAMIC)[3][0] == pytest.approx(0.0)

    model.on_drag_ended()

    assert transform.direct_writes[-1][0] == _DYNAMIC
    assert transform.get_local_transform(_DYNAMIC)[3][0] == pytest.approx(4.0)
    assert transform.control_targets == []


def test_running_dynamic_body_disables_viewport_transform_controls() -> None:
    reason = "running dynamic body is owned by the physics solver"
    transform = _PolicyTransformAdapter(
        {_DYNAMIC: TransformEditPolicy(TransformEditMode.BLOCKED, reason=reason)}
    )
    model = _model(transform)

    model.set_selection([_DYNAMIC])

    assert model.has_transformable_selection() is False
    assert model.transform_controls_enabled() is False
    assert model.transform_controls_tooltip() == reason
    assert model._initial_transforms == {}


def test_running_dynamic_selection_disables_toolbar_buttons_with_reason() -> None:
    reason = "running dynamic body is owned by the physics solver"
    transform = _PolicyTransformAdapter(
        {_DYNAMIC: TransformEditPolicy(TransformEditMode.BLOCKED, reason=reason)}
    )
    model = _model(transform)
    model.set_selection([_DYNAMIC])
    viewport = ViewportWidget.__new__(ViewportWidget)
    viewport._transform_model = model
    viewport._toolbar_button_backgrounds = {TOOL_TRANSLATE: SimpleNamespace(name="")}
    viewport._toolbar_buttons = {
        TOOL_TRANSLATE: SimpleNamespace(enabled=True, tooltip="")
    }
    viewport._iter_toolbar_tool_specs = lambda: (
        (TOOL_TRANSLATE, "Move", "W", "viewport_tool_move"),
    )
    viewport._get_active_tool = lambda: TOOL_TRANSLATE

    ViewportWidget._refresh_toolbar_state(viewport)

    assert viewport._toolbar_buttons[TOOL_TRANSLATE].enabled is False
    assert viewport._toolbar_buttons[TOOL_TRANSLATE].tooltip == reason
    assert viewport._toolbar_button_backgrounds[TOOL_TRANSLATE].name == "disabled"


def test_running_kinematic_body_routes_drag_to_control_target_not_raw_write() -> None:
    transform = _PolicyTransformAdapter(
        {
            _KINEMATIC: TransformEditPolicy(
                TransformEditMode.REDIRECTED,
                reason="running kinematic body uses ovphysx control targets",
            )
        }
    )
    transform.set_local_transform(_KINEMATIC, [row[:] for row in _IDENTITY])
    transform.direct_writes.clear()
    transform.control_targets.clear()
    model = _model(transform)

    model.set_selection([_KINEMATIC])
    model.on_drag_start()
    model.on_drag_moved(_DELTA)

    assert model.transform_controls_enabled() is True
    assert transform.direct_writes == []
    assert transform.control_targets == []
    assert model._live_transforms[_KINEMATIC][3][0] == pytest.approx(4.0)

    model.on_drag_ended()

    assert transform.control_targets[-1][0] == _KINEMATIC
    assert transform.control_targets[-1][1][3][0] == pytest.approx(4.0)
    assert transform.get_local_transform(_KINEMATIC)[3][0] == pytest.approx(0.0)


def test_mixed_policy_drag_routes_each_prim_to_its_destination() -> None:
    reason = "running dynamic body is owned by the physics solver"
    transform = _PolicyTransformAdapter(
        {
            _DYNAMIC: TransformEditPolicy(TransformEditMode.DIRECT),
            _KINEMATIC: TransformEditPolicy(
                TransformEditMode.REDIRECTED,
                reason="running kinematic body uses ovphysx control targets",
            ),
            _BLOCKED: TransformEditPolicy(TransformEditMode.BLOCKED, reason=reason),
        }
    )
    for path in (_DYNAMIC, _KINEMATIC, _BLOCKED):
        MockTransformAdapter.set_local_transform(transform, path, [row[:] for row in _IDENTITY])
    model = _model(transform)

    model.set_selection([_DYNAMIC, _KINEMATIC, _BLOCKED])

    assert model.has_transformable_selection() is True
    assert set(model._selected_paths) == {_DYNAMIC, _KINEMATIC}
    assert _BLOCKED not in model._selected_paths
    model.on_drag_start()
    model.on_drag_moved(_DELTA)
    assert set(model._initial_transforms) == {_DYNAMIC, _KINEMATIC}
    assert set(model._live_transforms) == {_DYNAMIC, _KINEMATIC}
    assert transform.direct_writes == []
    assert transform.control_targets == []
    assert transform.get_local_transform(_DYNAMIC)[3][0] == pytest.approx(0.0)
    assert transform.get_local_transform(_KINEMATIC)[3][0] == pytest.approx(0.0)
    assert transform.get_local_transform(_BLOCKED)[3][0] == pytest.approx(0.0)

    model.on_drag_ended()

    assert len(transform.direct_writes) == 1
    assert transform.direct_writes[0][0] == _DYNAMIC
    assert transform.direct_writes[0][1][3][0] == pytest.approx(4.0)
    assert len(transform.control_targets) == 1
    assert transform.control_targets[0][0] == _KINEMATIC
    assert transform.control_targets[0][1][3][0] == pytest.approx(4.0)
    assert transform.get_local_transform(_DYNAMIC)[3][0] == pytest.approx(4.0)
    assert transform.get_local_transform(_KINEMATIC)[3][0] == pytest.approx(0.0)
    assert transform.get_local_transform(_BLOCKED)[3][0] == pytest.approx(0.0)


def test_snap_values_route_to_direct_and_redirected_destinations() -> None:
    transform = _PolicyTransformAdapter(
        {
            _DYNAMIC: TransformEditPolicy(TransformEditMode.DIRECT),
            _KINEMATIC: TransformEditPolicy(
                TransformEditMode.REDIRECTED,
                reason="running kinematic body uses ovphysx control targets",
            ),
        }
    )
    for path in (_DYNAMIC, _KINEMATIC):
        MockTransformAdapter.set_local_transform(transform, path, [row[:] for row in _IDENTITY])
    model = PrimTransformModel(
        transform,
        _make_stage(),
        UndoManager(),
        snap_system=_enabled_grid_snap(),
    )

    model.set_selection([_DYNAMIC, _KINEMATIC])
    model.on_drag_start()
    model.on_drag_moved(_delta(4.7, 0.2, 0.9))

    assert _translation(model._live_transforms[_DYNAMIC]) == pytest.approx((5.0, 0.0, 1.0))
    assert _translation(model._live_transforms[_KINEMATIC]) == pytest.approx((5.0, 0.0, 1.0))
    assert transform.direct_writes == []
    assert transform.control_targets == []

    model.on_drag_ended()

    assert transform.direct_writes[-1][0] == _DYNAMIC
    assert _translation(transform.direct_writes[-1][1]) == pytest.approx((5.0, 0.0, 1.0))
    assert transform.direct_writes[-1][1][3][0] != pytest.approx(4.7)
    assert transform.control_targets[-1][0] == _KINEMATIC
    assert _translation(transform.control_targets[-1][1]) == pytest.approx((5.0, 0.0, 1.0))
    assert transform.control_targets[-1][1][3][0] != pytest.approx(4.7)
    assert _translation(transform.get_local_transform(_DYNAMIC)) == pytest.approx((5.0, 0.0, 1.0))
    assert _translation(transform.get_local_transform(_KINEMATIC)) == pytest.approx((0.0, 0.0, 0.0))
