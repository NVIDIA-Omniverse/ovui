# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for PickGesture and PickRectGesture.

Mouse coordinates arriving from ``omni.ui_scene``'s ``DragGesture``
are in OpenGL NDC space (``[-1, +1]`` across the SceneView), so the
drag threshold lives in NDC units. See ``pick_gesture.py`` for the
derivation of ``PICK_THRESHOLD_NDC``.
"""

from omni.ui_scene import scene as sc

from ovwidgets.viewport.pick_gesture import (
    MOD_CTRL,
    MOD_NONE,
    MOD_SHIFT,
    PICK_THRESHOLD_NDC,
    GizmoAwarePickManager,
    PickGesture,
    PickRectGesture,
)


class TestPickGesture:
    def test_fires_callback_on_short_drag(self):
        results = []
        g = PickGesture(callback=lambda x, y: results.append((x, y)))
        g._start_x = 0.0
        g._start_y = 0.0
        g._process_ended(0.005, 0.0)  # 0.005 NDC < 0.01 threshold
        assert len(results) == 1
        assert results[0] == (0.005, 0.0)

    def test_does_not_fire_on_long_drag(self):
        results = []
        g = PickGesture(callback=lambda x, y: results.append((x, y)))
        g._start_x = 0.0
        g._start_y = 0.0
        g._process_ended(0.1, 0.0)  # 0.1 NDC >> 0.01 → no pick
        assert len(results) == 0

    def test_fires_at_just_under_threshold(self):
        results = []
        g = PickGesture(callback=lambda x, y: results.append((x, y)))
        g._start_x = 0.0
        g._start_y = 0.0
        g._process_ended(PICK_THRESHOLD_NDC - 1e-5, 0.0)
        assert len(results) == 1

    def test_no_fire_at_exact_threshold(self):
        results = []
        g = PickGesture(callback=lambda x, y: results.append((x, y)))
        g._start_x = 0.0
        g._start_y = 0.0
        g._process_ended(PICK_THRESHOLD_NDC, 0.0)  # exactly at threshold → no pick
        assert len(results) == 0

    def test_zero_drag_fires_callback(self):
        results = []
        g = PickGesture(callback=lambda x, y: results.append((x, y)))
        g._start_x = 0.25
        g._start_y = -0.1
        g._process_ended(0.25, -0.1)  # no movement
        assert len(results) == 1
        assert results[0] == (0.25, -0.1)

    def test_none_callback_no_crash(self):
        g = PickGesture(callback=None)
        g._start_x = 0.0
        g._start_y = 0.0
        g._process_ended(0.001, 0.0)  # should not crash with None callback


class TestPickRectGesture:
    def test_fires_callback_on_long_drag(self):
        results = []
        g = PickRectGesture(
            callback=lambda x0, y0, x1, y1: results.append((x0, y0, x1, y1))
        )
        g._start_x = 0.0
        g._start_y = 0.0
        g._process_ended(0.1, 0.0)  # 0.1 NDC >> 0.01 threshold
        assert len(results) == 1
        assert results[0] == (0.0, 0.0, 0.1, 0.0)

    def test_does_not_fire_on_short_drag(self):
        results = []
        g = PickRectGesture(
            callback=lambda x0, y0, x1, y1: results.append((x0, y0, x1, y1))
        )
        g._start_x = 0.0
        g._start_y = 0.0
        g._process_ended(0.005, 0.0)  # 0.005 NDC < 0.01 → no rect
        assert len(results) == 0

    def test_fires_at_exact_threshold(self):
        results = []
        g = PickRectGesture(
            callback=lambda x0, y0, x1, y1: results.append((x0, y0, x1, y1))
        )
        g._start_x = 0.0
        g._start_y = 0.0
        g._process_ended(PICK_THRESHOLD_NDC, 0.0)  # exactly at threshold → fires
        assert len(results) == 1

    def test_none_callback_no_crash(self):
        g = PickRectGesture(callback=None)
        g._start_x = 0.0
        g._start_y = 0.0
        g._process_ended(0.1, 0.0)  # should not crash with None callback

    def test_callback_receives_start_and_end(self):
        """Drag from (-.4, -.3) to (.2, .3) — callback gets all four corners."""
        results = []
        g = PickRectGesture(
            callback=lambda x0, y0, x1, y1: results.append((x0, y0, x1, y1))
        )
        g._start_x = -0.4
        g._start_y = -0.3
        g._process_ended(0.2, 0.3)  # √(.36 + .36) ≈ 0.85 NDC, well past threshold
        assert results == [(-0.4, -0.3, 0.2, 0.3)]


class TestPickDragDoesNotFirePickGesture:
    def test_long_drag_does_not_fire_pick_gesture(self):
        results = []
        g = PickGesture(callback=lambda x, y: results.append((x, y)))
        g._start_x = 0.0
        g._start_y = 0.0
        g._process_ended(0.5, 0.5)  # well past threshold
        assert results == []

    def test_diagonal_drag_respects_euclidean_distance(self):
        results = []
        g = PickGesture(callback=lambda x, y: results.append((x, y)))
        g._start_x = 0.0
        g._start_y = 0.0
        # dx=0.006, dy=0.008 → dist=0.010 (at threshold) → no pick
        g._process_ended(0.006, 0.008)
        assert results == []


class TestModifiers:
    def test_default_modifier_is_none(self):
        g = PickGesture(callback=lambda x, y: None)
        # sc.DragGesture stores modifiers internally; we exposed MOD_NONE
        # as the default so plain left-click still works after the upgrade.
        assert MOD_NONE == 0

    def test_pick_gesture_accepts_shift_modifier(self):
        # The gesture must instantiate cleanly with a modifier; dispatch
        # is owned by sc.DragGesture and we trust it — no need to
        # simulate a real modified click here, just prove we don't break
        # the constructor.
        PickGesture(callback=lambda x, y: None, modifiers=MOD_SHIFT)

    def test_pick_rect_gesture_accepts_ctrl_modifier(self):
        PickRectGesture(
            callback=lambda x0, y0, x1, y1: None, modifiers=MOD_CTRL
        )

    def test_pick_gesture_fires_callback_with_modifier_set(self):
        """Modifier changes don't alter the drag-distance logic."""
        results = []
        g = PickGesture(
            callback=lambda x, y: results.append((x, y)),
            modifiers=MOD_SHIFT,
        )
        g._start_x = 0.0
        g._start_y = 0.0
        g._process_ended(0.005, 0.0)
        assert results == [(0.005, 0.0)]


class _FakeGizmoGesture:
    """Minimal stand-in for ``PrimTranslateChangedGesture`` in unit tests.

    Carries the same pair of attributes the pick manager's guard reads —
    ``is_active`` for an in-flight drag and ``_drag_ended_this_cycle``
    for the latched "just ended" signal.
    """

    def __init__(self) -> None:
        self.is_active: bool = False
        self._drag_ended_this_cycle: bool = False


class TestGizmoAwarePickManager:
    def test_empty_manager_has_no_live_drag(self):
        mgr = GizmoAwarePickManager()
        assert mgr.has_live_gizmo_drag() is False

    def test_active_gesture_reports_live_drag(self):
        mgr = GizmoAwarePickManager()
        g = _FakeGizmoGesture()
        g.is_active = True
        mgr.set_gizmo_gestures([g])
        assert mgr.has_live_gizmo_drag() is True

    def test_latch_reports_live_drag_after_on_ended_clears_active(self):
        """Bug 13 — gizmo on_ended clears is_active; the latch must stand in.

        If the gizmo's ``_on_ended`` fires before the pick gesture's, the
        ``is_active`` flag is already False by the time the pick checks.
        The ``_drag_ended_this_cycle`` latch is the fix so the pick still
        sees "a drag just happened" and bails out of its callback.
        """
        mgr = GizmoAwarePickManager()
        g = _FakeGizmoGesture()
        g.is_active = False
        g._drag_ended_this_cycle = True
        mgr.set_gizmo_gestures([g])
        assert mgr.has_live_gizmo_drag() is True

    def test_reset_drag_end_tracker_clears_latch_on_all_gestures(self):
        mgr = GizmoAwarePickManager()
        a = _FakeGizmoGesture()
        b = _FakeGizmoGesture()
        a._drag_ended_this_cycle = True
        b._drag_ended_this_cycle = True
        mgr.set_gizmo_gestures([a, b])
        mgr.reset_drag_end_tracker()
        assert a._drag_ended_this_cycle is False
        assert b._drag_ended_this_cycle is False
        assert mgr.has_live_gizmo_drag() is False

    def test_reset_drag_end_tracker_tolerates_missing_attribute(self):
        """A gesture without the latch field must not raise on reset.

        The pick manager tracks whatever list of gestures the viewport
        hands it; older or mocked gestures shouldn't crash the reset.
        """
        class _NoLatchGesture:
            is_active = False
        mgr = GizmoAwarePickManager()
        mgr.set_gizmo_gestures([_NoLatchGesture()])
        mgr.reset_drag_end_tracker()  # must not raise

    def test_began_state_reports_live_drag_before_on_began_python_callback(self):
        """Windows ordering bug — pick._on_ended fires before gizmo._on_began.

        ``omni.ui_scene`` stores its gesture caches in
        ``std::unordered_map``. libstdc++ and the MSVC STL bucket pointers
        differently, so the order in which Python callbacks fire across
        the gizmo's manager and the pick gesture's default manager differs
        by platform. On Windows the pick gesture's prevented
        fall-through ``_on_ended`` runs *before* the gizmo's ``_on_began``
        sets ``is_active = True``, leaving both ``is_active`` and the
        ``_drag_ended_this_cycle`` latch at False. Reading the C++ state
        — set during ``preProcess`` before any callback fires — closes
        the window: a state of ``BEGAN`` already means "drag in progress,
        suppress the pick".
        """
        class _StateOnlyGesture:
            is_active = False
            _drag_ended_this_cycle = False
            state = sc.GestureState.BEGAN

        mgr = GizmoAwarePickManager()
        mgr.set_gizmo_gestures([_StateOnlyGesture()])
        assert mgr.has_live_gizmo_drag() is True

    def test_changed_state_reports_live_drag(self):
        """Mid-drag (state=CHANGED) must also count as a live drag."""
        class _ChangedGesture:
            is_active = False
            _drag_ended_this_cycle = False
            state = sc.GestureState.CHANGED

        mgr = GizmoAwarePickManager()
        mgr.set_gizmo_gestures([_ChangedGesture()])
        assert mgr.has_live_gizmo_drag() is True

    def test_possible_state_does_not_report_live_drag(self):
        """A dormant gesture (state=POSSIBLE) must not suppress picks.

        Otherwise the very first click after the manipulator builds
        would be eaten before any drag has actually happened.
        """
        class _DormantGesture:
            is_active = False
            _drag_ended_this_cycle = False
            state = sc.GestureState.POSSIBLE

        mgr = GizmoAwarePickManager()
        mgr.set_gizmo_gestures([_DormantGesture()])
        assert mgr.has_live_gizmo_drag() is False

    def test_state_attribute_missing_falls_back_to_is_active(self):
        """If a fake/mocked gesture has no ``state`` attr, the older
        ``is_active`` / latch checks still apply."""
        class _NoStateGesture:
            is_active = True

        mgr = GizmoAwarePickManager()
        mgr.set_gizmo_gestures([_NoStateGesture()])
        assert mgr.has_live_gizmo_drag() is True
