# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Step 51: SnapSystem integration with PrimTransformModel."""
from typing import List

import pytest

from ovui_widgets.common.settings import Settings
from ovui_widgets.common.snap import GridSnapProvider, SnapProvider, SnapSystem
from ovui_widgets.common.testing.mock_stage import MockStageAdapter
from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.viewport.prim_transform_model import PrimTransformModel


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


def _make_model(snap=None):
    ta = MockTransformAdapter()
    sa = MockStageAdapter()
    undo = UndoManager()
    return PrimTransformModel(ta, sa, undo, snap_system=snap), ta


def _assert_live_translation(model, path, tx, ty, tz):
    result = model._live_transforms[path]
    assert result[3][0] == pytest.approx(tx)
    assert result[3][1] == pytest.approx(ty)
    assert result[3][2] == pytest.approx(tz)


class TestSnapDisabled:
    def test_no_snap_system_passes_through(self):
        """When snap_system=None, position is not modified."""
        model, ta = _make_model()
        ta.set_local_transform("/W/A", _identity())
        model.set_selection(["/W/A"])
        model.on_drag_start()
        model.on_drag_moved(_translation_matrix(1.7, 2.3, 4.9))
        _assert_live_translation(model, "/W/A", 1.7, 2.3, 4.9)
        assert ta.get_local_transform("/W/A")[3][0] == pytest.approx(0.0)
        model.on_drag_ended()
        result = ta.get_local_transform("/W/A")
        assert result[3][0] == pytest.approx(1.7)
        assert result[3][1] == pytest.approx(2.3)
        assert result[3][2] == pytest.approx(4.9)

    def test_snap_system_disabled_passes_through(self):
        """SnapSystem with enable(False) behaves as passthrough."""
        snap = SnapSystem()  # enabled=False by default
        snap.add_provider(GridSnapProvider(1.0))
        model, ta = _make_model(snap=snap)
        ta.set_local_transform("/W/A", _identity())
        model.set_selection(["/W/A"])
        model.on_drag_start()
        model.on_drag_moved(_translation_matrix(0.7, 0.3, 0.9))
        _assert_live_translation(model, "/W/A", 0.7, 0.3, 0.9)
        assert ta.get_local_transform("/W/A")[3][0] == pytest.approx(0.0)
        model.on_drag_ended()
        result = ta.get_local_transform("/W/A")
        assert result[3][0] == pytest.approx(0.7)
        assert result[3][1] == pytest.approx(0.3)
        assert result[3][2] == pytest.approx(0.9)


class TestSnapEnabled:
    def test_grid_snap_rounds_to_nearest_unit(self):
        """Enabled GridSnapProvider rounds translation to 1-unit grid."""
        snap = SnapSystem()
        snap.enable(True)
        snap.add_provider(GridSnapProvider(1.0))
        model, ta = _make_model(snap=snap)
        ta.set_local_transform("/W/A", _identity())
        model.set_selection(["/W/A"])
        model.on_drag_start()
        model.on_drag_moved(_translation_matrix(0.7, 0.3, 0.9))
        _assert_live_translation(model, "/W/A", 1.0, 0.0, 1.0)
        assert ta.get_local_transform("/W/A")[3][0] == pytest.approx(0.0)
        model.on_drag_ended()
        result = ta.get_local_transform("/W/A")
        assert result[3][0] == pytest.approx(1.0)  # 0.7 → 1
        assert result[3][1] == pytest.approx(0.0)  # 0.3 → 0
        assert result[3][2] == pytest.approx(1.0)  # 0.9 → 1

    def test_constraint_axis_passed_as_none_to_provider(self):
        """PrimTransformModel passes constraint_axis=None to snap.snap()."""

        class _TrackingProvider(SnapProvider):
            def __init__(self):
                self.last_axis = "not_called"

            def snap(self, position: List[float], constraint_axis) -> List[float]:
                self.last_axis = constraint_axis
                return list(position)

        snap = SnapSystem()
        snap.enable(True)
        tracker = _TrackingProvider()
        snap.add_provider(tracker)
        model, ta = _make_model(snap=snap)
        ta.set_local_transform("/W/A", _identity())
        model.set_selection(["/W/A"])
        model.on_drag_start()
        model.on_drag_moved(_translation_matrix(1.0, 0.0, 0.0))
        assert tracker.last_axis is None
        model.on_drag_ended()

    def test_settings_subscription_toggles_snap_on_off(self):
        """snap.enabled setting subscription enables/disables snap live."""
        snap = SnapSystem()
        snap.add_provider(GridSnapProvider(1.0))
        settings = Settings()
        sub = settings.subscribe("snap.enabled", lambda k, v: snap.enable(bool(v)))  # noqa: F841

        ta = MockTransformAdapter()
        sa = MockStageAdapter()
        undo = UndoManager()
        model = PrimTransformModel(ta, sa, undo, snap_system=snap)

        ta.set_local_transform("/W/A", _identity())
        model.set_selection(["/W/A"])

        # Snap off by default → exact position
        model.on_drag_start()
        model.on_drag_moved(_translation_matrix(0.7, 0.7, 0.7))
        _assert_live_translation(model, "/W/A", 0.7, 0.7, 0.7)
        assert ta.get_local_transform("/W/A")[3][0] == pytest.approx(0.0)
        model.on_drag_ended()
        result = ta.get_local_transform("/W/A")
        assert result[3][0] == pytest.approx(0.7)

        # Enable snap via settings → position snaps to grid
        settings.set("snap.enabled", True)
        ta.set_local_transform("/W/A", _identity())
        model.on_drag_start()
        model.on_drag_moved(_translation_matrix(0.7, 0.7, 0.7))
        _assert_live_translation(model, "/W/A", 1.0, 1.0, 1.0)
        assert ta.get_local_transform("/W/A")[3][0] == pytest.approx(0.0)
        model.on_drag_ended()
        result = ta.get_local_transform("/W/A")
        assert result[3][0] == pytest.approx(1.0)

        # Disable snap via settings → exact position again
        settings.set("snap.enabled", False)
        ta.set_local_transform("/W/A", _identity())
        model.on_drag_start()
        model.on_drag_moved(_translation_matrix(0.7, 0.7, 0.7))
        _assert_live_translation(model, "/W/A", 0.7, 0.7, 0.7)
        assert ta.get_local_transform("/W/A")[3][0] == pytest.approx(0.0)
        model.on_drag_ended()
        result = ta.get_local_transform("/W/A")
        assert result[3][0] == pytest.approx(0.7)
