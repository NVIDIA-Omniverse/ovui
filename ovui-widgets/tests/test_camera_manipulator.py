# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for CameraManipulatorModel (Viewport Plan §B.1) + CameraManipulator
(Viewport Plan §B.5).

The model is the sc.AbstractManipulatorModel implementation that sits between
camera gestures and the CameraController. These tests exercise the item
registry, typed accessors, listener notification, and the cross-kind coercion
/ size-validation invariants the gestures (added in §B.2 onward) rely on.

The manipulator is the sc.Manipulator subclass that owns the four camera
gestures plus optional flight-keyboard + tumble-inertia helpers. Tests cover
construction, gesture wiring, on_build screen installation, and the
``integrate`` per-frame passthrough.
"""

import pytest
from omni.ui_scene import scene as sc

from ovui_widgets.viewport.camera_controller import CameraController
from ovui_widgets.viewport.camera_flight_keyboard import FlightModeKeyboard
from ovui_widgets.viewport.camera_gesture import (
    MOD_ALT,
    MOD_CTRL,
    MOD_SHIFT,
    MOUSE_LEFT,
    parse_bindings,
)
from ovui_widgets.viewport.camera_inertia import TumbleInertia
from ovui_widgets.viewport.camera_manipulator import (
    DEFAULT_INERTIA_SECONDS,
    CameraManipulator,
    CameraManipulatorModel,
)


def _size_fn():
    return (1280, 720)


_EXPECTED_ITEMS = (
    # (name, kind, size)
    ("move",               "float", 3),
    ("rotate",             "float", 3),
    ("speed",              "float", 3),
    ("transform",          "float", 16),
    ("projection",         "float", 16),
    ("ndc_aspect",         "float", 1),
    ("center_of_interest", "float", 3),
    ("up_axis",            "float", 3),
    ("fly_inertia",        "float", 1),
    ("tumble_inertia",     "float", 1),
    ("coi_picked",         "int",   1),
    ("orthographic",       "int",   1),
    ("disable_pan",        "int",   1),
    ("disable_tumble",     "int",   1),
    ("disable_look",       "int",   1),
    ("disable_zoom",       "int",   1),
    ("disable_fly",        "int",   1),
)


class TestModelConstruction:
    def test_model_exists(self):
        m = CameraManipulatorModel()
        assert m is not None

    def test_model_subclasses_abstract_manipulator_model(self):
        m = CameraManipulatorModel()
        assert isinstance(m, sc.AbstractManipulatorModel)

    def test_all_expected_items_registered(self):
        m = CameraManipulatorModel()
        for name, _kind, _size in _EXPECTED_ITEMS:
            item = m.get_item(name)
            assert item is not None, f"item {name!r} missing"

    def test_item_count_matches_plan(self):
        """Step B.1 lists exactly 17 items. A silent add/remove here would
        mean the model has drifted from the plan without a doc update."""
        m = CameraManipulatorModel()
        assert len(m._items) == len(_EXPECTED_ITEMS) == 17

    def test_get_item_unknown_returns_none(self):
        m = CameraManipulatorModel()
        assert m.get_item("nonexistent") is None

    def test_get_item_is_stable_across_calls(self):
        m = CameraManipulatorModel()
        assert m.get_item("rotate") is m.get_item("rotate")

    def test_items_are_abstract_manipulator_item_subclass(self):
        """Required so omni.ui_scene can accept them through the shared_ptr
        API. If this ever breaks, gestures won't be able to pass items to
        C++-side manipulator machinery."""
        m = CameraManipulatorModel()
        assert isinstance(m.get_item("rotate"), sc.AbstractManipulatorItem)


class TestDefaultValues:
    def test_move_default_is_zero(self):
        m = CameraManipulatorModel()
        assert m.get_as_floats("move") == [0.0, 0.0, 0.0]

    def test_rotate_default_is_zero(self):
        m = CameraManipulatorModel()
        assert m.get_as_floats("rotate") == [0.0, 0.0, 0.0]

    def test_speed_default_is_one(self):
        m = CameraManipulatorModel()
        assert m.get_as_floats("speed") == [1.0, 1.0, 1.0]

    def test_transform_default_is_identity(self):
        m = CameraManipulatorModel()
        mtx = m.get_as_floats("transform")
        assert len(mtx) == 16
        # Identity: diag=1, off-diag=0
        assert mtx == [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]

    def test_projection_default_is_identity(self):
        m = CameraManipulatorModel()
        mtx = m.get_as_floats("projection")
        assert len(mtx) == 16
        assert mtx[0] == 1.0 and mtx[5] == 1.0 and mtx[10] == 1.0 and mtx[15] == 1.0

    def test_ndc_aspect_default_is_one(self):
        m = CameraManipulatorModel()
        assert m.get_as_floats("ndc_aspect") == [1.0]

    def test_center_of_interest_default_is_zero(self):
        m = CameraManipulatorModel()
        assert m.get_as_floats("center_of_interest") == [0.0, 0.0, 0.0]

    def test_up_axis_default_is_y_up(self):
        m = CameraManipulatorModel()
        assert m.get_as_floats("up_axis") == [0.0, 1.0, 0.0]

    def test_inertia_defaults_match_architecture_doc(self):
        m = CameraManipulatorModel()
        assert m.get_as_floats("fly_inertia") == [DEFAULT_INERTIA_SECONDS]
        assert m.get_as_floats("tumble_inertia") == [DEFAULT_INERTIA_SECONDS]
        assert DEFAULT_INERTIA_SECONDS == 0.15

    def test_bool_items_default_false(self):
        m = CameraManipulatorModel()
        for name in (
            "coi_picked", "orthographic",
            "disable_pan", "disable_tumble", "disable_look",
            "disable_zoom", "disable_fly",
        ):
            assert m.get_as_ints(name) == [0], f"{name} default should be 0"


class TestSetFloatsHappyPath:
    def test_set_and_get_rotate(self):
        m = CameraManipulatorModel()
        m.set_floats("rotate", [0.1, 0.2, 0.3])
        assert m.get_as_floats("rotate") == [0.1, 0.2, 0.3]

    def test_set_transform_round_trip(self):
        m = CameraManipulatorModel()
        mtx = [
            2.0, 0.0, 0.0, 0.0,
            0.0, 3.0, 0.0, 0.0,
            0.0, 0.0, 4.0, 0.0,
            5.0, 6.0, 7.0, 1.0,
        ]
        m.set_floats("transform", mtx)
        assert m.get_as_floats("transform") == mtx

    def test_set_via_item_object(self):
        m = CameraManipulatorModel()
        item = m.get_item("move")
        m.set_floats(item, [9.0, 8.0, 7.0])
        assert m.get_as_floats("move") == [9.0, 8.0, 7.0]

    def test_set_floats_coerces_ints_to_floats(self):
        m = CameraManipulatorModel()
        m.set_floats("center_of_interest", [1, 2, 3])
        vals = m.get_as_floats("center_of_interest")
        assert vals == [1.0, 2.0, 3.0]
        assert all(isinstance(v, float) for v in vals)


class TestSetIntsHappyPath:
    def test_set_and_get_orthographic(self):
        m = CameraManipulatorModel()
        m.set_ints("orthographic", [1])
        assert m.get_as_ints("orthographic") == [1]

    def test_disable_flags_are_independent(self):
        m = CameraManipulatorModel()
        m.set_ints("disable_pan", [1])
        assert m.get_as_ints("disable_pan") == [1]
        assert m.get_as_ints("disable_tumble") == [0]
        assert m.get_as_ints("disable_zoom") == [0]

    def test_coi_picked_toggle(self):
        m = CameraManipulatorModel()
        m.set_ints("coi_picked", [1])
        assert m.get_as_ints("coi_picked") == [1]
        m.set_ints("coi_picked", [0])
        assert m.get_as_ints("coi_picked") == [0]


class TestCrossKindCoercion:
    def test_set_ints_on_float_item_stores_floats(self):
        """Up-axis is a float item. set_ints [0,0,1] must store floats so
        later ``get_as_floats`` doesn't surface int leaks."""
        m = CameraManipulatorModel()
        m.set_ints("up_axis", [0, 0, 1])
        vals = m.get_as_floats("up_axis")
        assert vals == [0.0, 0.0, 1.0]
        assert all(isinstance(v, float) for v in vals)

    def test_set_floats_on_int_item_stores_ints(self):
        """Orthographic is an int gate. If a gesture mistakenly calls
        set_floats([1.0]), coerce rather than silently storing 1.0."""
        m = CameraManipulatorModel()
        m.set_floats("orthographic", [1.0])
        vals = m.get_as_ints("orthographic")
        assert vals == [1]
        assert all(isinstance(v, int) and not isinstance(v, bool) for v in vals)

    def test_get_as_floats_on_int_item_returns_floats(self):
        m = CameraManipulatorModel()
        m.set_ints("disable_tumble", [1])
        vals = m.get_as_floats("disable_tumble")
        assert vals == [1.0]
        assert isinstance(vals[0], float)

    def test_get_as_ints_on_float_item_returns_ints(self):
        m = CameraManipulatorModel()
        m.set_floats("speed", [2.7, 3.4, 4.9])
        vals = m.get_as_ints("speed")
        # Casting is truncation (float → int); matches built-in int() semantics.
        assert vals == [2, 3, 4]
        assert all(isinstance(v, int) for v in vals)


class TestListenerNotification:
    def test_listener_fires_on_set_floats(self):
        """Per Step B.1 acceptance: set_ints('rotate', [0.1, 0, 0]) fires listener."""
        m = CameraManipulatorModel()
        hits = []
        m.add_item_changed_fn(lambda mdl, it: hits.append(it.name))
        m.set_floats("rotate", [0.1, 0.0, 0.0])
        assert hits == ["rotate"]

    def test_listener_fires_on_set_ints(self):
        m = CameraManipulatorModel()
        hits = []
        m.add_item_changed_fn(lambda mdl, it: hits.append(it.name))
        m.set_ints("orthographic", [1])
        assert hits == ["orthographic"]

    def test_listener_receives_model_and_item(self):
        m = CameraManipulatorModel()
        captured = []
        m.add_item_changed_fn(lambda mdl, it: captured.append((mdl, it)))
        m.set_floats("move", [1.0, 0.0, 0.0])
        assert len(captured) == 1
        mdl, it = captured[0]
        assert mdl is m
        assert it is m.get_item("move")

    def test_listener_fires_for_every_change(self):
        m = CameraManipulatorModel()
        hits = []
        m.add_item_changed_fn(lambda mdl, it: hits.append(it.name))
        m.set_floats("rotate", [0.1, 0.0, 0.0])
        m.set_floats("move", [0.0, 0.1, 0.0])
        m.set_ints("disable_pan", [1])
        assert hits == ["rotate", "move", "disable_pan"]

    def test_multiple_listeners_all_notified(self):
        m = CameraManipulatorModel()
        a, b = [], []
        m.add_item_changed_fn(lambda mdl, it: a.append(it.name))
        m.add_item_changed_fn(lambda mdl, it: b.append(it.name))
        m.set_floats("rotate", [0.5, 0.0, 0.0])
        assert a == ["rotate"]
        assert b == ["rotate"]

    def test_subscribe_returns_cancellable_subscription(self):
        m = CameraManipulatorModel()
        hits = []
        sub = m.subscribe_item_changed_fn(
            lambda mdl, it: hits.append(it.name)
        )
        m.set_floats("rotate", [0.1, 0.0, 0.0])
        assert hits == ["rotate"]

        # Dropping the subscription (via Python refcount or explicit del) must
        # detach the callback. omni.ui subscriptions keep the callback alive
        # until the subscription object itself is GC'd.
        del sub
        m.set_floats("rotate", [0.2, 0.0, 0.0])
        assert hits == ["rotate"]  # no additional entry

    def test_remove_item_changed_fn_detaches_callback(self):
        m = CameraManipulatorModel()
        hits = []
        cb_id = m.add_item_changed_fn(lambda mdl, it: hits.append(it.name))
        m.set_floats("rotate", [0.1, 0.0, 0.0])
        m.remove_item_changed_fn(cb_id)
        m.set_floats("rotate", [0.2, 0.0, 0.0])
        assert hits == ["rotate"]


class TestUnknownItemInputs:
    def test_get_as_floats_unknown_string_returns_empty(self):
        m = CameraManipulatorModel()
        assert m.get_as_floats("nonsense") == []

    def test_get_as_ints_unknown_string_returns_empty(self):
        m = CameraManipulatorModel()
        assert m.get_as_ints("nonsense") == []

    def test_set_floats_unknown_string_is_silent_noop(self):
        """Unknown writes don't raise — keeps gestures that feature-gate on
        item presence (e.g. disable flags a future plug-in adds) simple."""
        m = CameraManipulatorModel()
        hits = []
        m.add_item_changed_fn(lambda mdl, it: hits.append(it.name))
        m.set_floats("nonsense", [1.0])
        assert hits == []

    def test_set_ints_unknown_string_is_silent_noop(self):
        m = CameraManipulatorModel()
        hits = []
        m.add_item_changed_fn(lambda mdl, it: hits.append(it.name))
        m.set_ints("nonsense", [1])
        assert hits == []

    def test_get_as_floats_none_returns_empty(self):
        m = CameraManipulatorModel()
        assert m.get_as_floats(None) == []

    def test_get_as_ints_none_returns_empty(self):
        m = CameraManipulatorModel()
        assert m.get_as_ints(None) == []


class TestSizeValidation:
    def test_set_floats_wrong_size_raises(self):
        m = CameraManipulatorModel()
        with pytest.raises(ValueError, match="expects 3 values, got 2"):
            m.set_floats("rotate", [1.0, 2.0])

    def test_set_floats_too_many_raises(self):
        m = CameraManipulatorModel()
        with pytest.raises(ValueError, match="expects 3 values, got 4"):
            m.set_floats("move", [1.0, 2.0, 3.0, 4.0])

    def test_set_ints_wrong_size_on_scalar_raises(self):
        m = CameraManipulatorModel()
        with pytest.raises(ValueError, match="expects 1 values, got 3"):
            m.set_ints("orthographic", [0, 1, 0])

    def test_set_floats_wrong_size_on_matrix_raises(self):
        m = CameraManipulatorModel()
        with pytest.raises(ValueError, match="expects 16 values"):
            m.set_floats("transform", [1.0] * 9)


class TestItemKindMetadata:
    @pytest.mark.parametrize("name,kind,size", _EXPECTED_ITEMS)
    def test_item_kind_and_size(self, name, kind, size):
        m = CameraManipulatorModel()
        item = m.get_item(name)
        assert item.name == name
        assert item.kind == kind
        assert item.size == size
        assert len(item.value) == size


# ---------------------------------------------------------------------------
# CameraManipulator (Step B.5)
# ---------------------------------------------------------------------------


class TestCameraManipulatorConstruction:
    def test_is_sc_manipulator(self):
        man = CameraManipulator(camera_controller=CameraController())
        assert isinstance(man, sc.Manipulator)

    def test_stores_camera_controller(self):
        cam = CameraController()
        man = CameraManipulator(camera_controller=cam)
        assert man.camera_controller is cam

    def test_default_model_is_camera_manipulator_model(self):
        """Not passing a model must allocate a fresh CameraManipulatorModel —
        gestures rely on the model's ``disable_*`` gates existing."""
        man = CameraManipulator(camera_controller=CameraController())
        assert isinstance(man.model, CameraManipulatorModel)

    def test_passes_model_through_to_gestures(self):
        model = CameraManipulatorModel()
        man = CameraManipulator(
            camera_controller=CameraController(), model=model
        )
        assert man.model is model
        for g in man.camera_gestures:
            assert g._model is model

    def test_viewport_size_fn_plumbed_to_angular_and_pan_gestures(self):
        man = CameraManipulator(
            camera_controller=CameraController(),
            viewport_size_fn=_size_fn,
        )
        assert man.tumble_gesture._viewport_size_fn is _size_fn
        assert man.pan_gesture._viewport_size_fn is _size_fn
        assert man.look_gesture._viewport_size_fn is _size_fn

    def test_camera_gestures_returns_a_copy(self):
        """Mutating the returned list must not affect the manipulator's
        internal registry — otherwise tests/clients can accidentally erase
        a gesture and break input dispatch."""
        man = CameraManipulator(camera_controller=CameraController())
        copy = man.camera_gestures
        copy.pop()
        assert len(man.camera_gestures) == len(copy) + 1

    def test_ctor_accepts_camera_controller_as_keyword(self):
        """Plan §B.5 example uses the ``camera_controller=`` kwarg."""
        cam = CameraController()
        man = CameraManipulator(camera_controller=cam)
        assert man.camera_controller is cam


class TestCameraManipulatorTumbleInertiaWiring:
    def test_tumble_gesture_receives_inertia(self):
        cam = CameraController()
        model = CameraManipulatorModel()
        inertia = TumbleInertia(cam, model=model)
        man = CameraManipulator(
            camera_controller=cam, model=model, tumble_inertia=inertia
        )
        assert man.tumble_gesture._inertia is inertia

    def test_tumble_inertia_property_exposed(self):
        cam = CameraController()
        model = CameraManipulatorModel()
        inertia = TumbleInertia(cam, model=model)
        man = CameraManipulator(
            camera_controller=cam, model=model, tumble_inertia=inertia
        )
        assert man.tumble_inertia is inertia

    def test_no_inertia_leaves_tumble_gesture_plain(self):
        man = CameraManipulator(camera_controller=CameraController())
        assert man.tumble_gesture._inertia is None


class TestCameraManipulatorFlightKeyboardWiring:
    def test_flight_keyboard_property_exposed(self):
        cam = CameraController()
        kb = FlightModeKeyboard(cam)
        man = CameraManipulator(
            camera_controller=cam, flight_keyboard=kb
        )
        assert man.flight_keyboard is kb

    def test_no_flight_keyboard_leaves_property_none(self):
        man = CameraManipulator(camera_controller=CameraController())
        assert man.flight_keyboard is None


class TestCameraManipulatorOnBuild:
    def test_on_build_does_not_raise_inside_scene(self):
        """Manipulator's on_build must emit a ``sc.Screen`` without error
        when the manipulator is sitting in a ``SceneView`` scene context."""
        sv = sc.SceneView()
        with sv.scene:
            man = CameraManipulator(camera_controller=CameraController())
        man.on_build()  # must not raise

    def test_invalidate_is_supported(self):
        sv = sc.SceneView()
        with sv.scene:
            man = CameraManipulator(camera_controller=CameraController())
        man.invalidate()  # must not raise


class TestCameraManipulatorOnModelUpdated:
    def test_no_op_does_not_raise(self):
        """B.5 scope leaves the write-through hook empty; future steps may
        fill it in. Pin the no-op now so tests catch accidental coupling
        before the architecture work actually lands."""
        man = CameraManipulator(camera_controller=CameraController())
        man.on_model_updated(man.model.get_item("rotate"))
        man.on_model_updated(None)


class TestCameraManipulatorIntegrate:
    def test_integrate_is_safe_without_flight_or_inertia(self):
        man = CameraManipulator(camera_controller=CameraController())
        man.integrate(0.016)  # must not raise

    def test_integrate_calls_flight_integrate_when_flying(self):
        cam = CameraController()
        kb = FlightModeKeyboard(cam)
        # Force flying-state so the branch fires.
        kb.notify_rmb_press()
        kb.handle_key_event(ord("W"), 0, pressed=True)
        man = CameraManipulator(
            camera_controller=cam, flight_keyboard=kb
        )
        before = list(cam.state.target)
        man.integrate(0.1)
        after = list(cam.state.target)
        assert after != before, "flight integration should have moved the target"

    def test_integrate_skips_flight_when_not_flying(self):
        cam = CameraController()
        kb = FlightModeKeyboard(cam)
        man = CameraManipulator(
            camera_controller=cam, flight_keyboard=kb
        )
        before = list(cam.state.target)
        man.integrate(0.1)
        assert list(cam.state.target) == before

    def test_integrate_ticks_tumble_inertia_when_active(self):
        cam = CameraController()
        model = CameraManipulatorModel()
        inertia = TumbleInertia(cam, model=model)
        # Arm the coast with a tail velocity well above min_speed.
        inertia.start(1.0, 0.0)
        assert inertia.is_active
        man = CameraManipulator(
            camera_controller=cam, model=model, tumble_inertia=inertia
        )
        before_az = cam.state.azimuth
        man.integrate(0.016)
        assert cam.state.azimuth != before_az, "inertia tick should rotate the camera"

    def test_integrate_skips_inertia_when_inactive(self):
        cam = CameraController()
        model = CameraManipulatorModel()
        inertia = TumbleInertia(cam, model=model)
        assert not inertia.is_active
        man = CameraManipulator(
            camera_controller=cam, model=model, tumble_inertia=inertia
        )
        before_az = cam.state.azimuth
        man.integrate(0.016)
        assert cam.state.azimuth == before_az


class TestCameraManipulatorGesturesWriteThrough:
    """End-to-end smoke checks: each gesture mutates CameraController through
    the manipulator's owned instances."""

    def test_tumble_mutates_camera_via_manipulator(self):
        cam = CameraController()
        man = CameraManipulator(camera_controller=cam)
        g = man.tumble_gesture
        g.raw_input.mouse.x = 0.0
        g.raw_input.mouse.y = 0.0
        g._on_began()
        g.raw_input.mouse.x = 0.5
        g.raw_input.mouse.y = 0.0
        g._on_changed()
        assert cam.state.azimuth != 0.0

    def test_pan_mutates_camera_via_manipulator(self):
        cam = CameraController()
        man = CameraManipulator(
            camera_controller=cam, viewport_size_fn=_size_fn
        )
        g = man.pan_gesture
        g.raw_input.mouse.x = 0.0
        g.raw_input.mouse.y = 0.0
        g._on_began()
        g.raw_input.mouse.x = 0.2
        g.raw_input.mouse.y = 0.0
        g._on_changed()
        assert list(cam.state.target) != [0.0, 0.0, 0.0]

    def test_zoom_mutates_camera_via_manipulator(self):
        cam = CameraController()
        man = CameraManipulator(camera_controller=cam)
        g = man.zoom_gesture
        before = cam.state.distance
        g.raw_input.mouse_wheel.y = 3.0
        g._on_ended()
        assert cam.state.distance != before


def _press(gesture, modifiers=0):
    gesture.raw_input.modifiers = modifiers
    gesture.raw_input.mouse.x = 0.0
    gesture.raw_input.mouse.y = 0.0
    gesture._on_began()
    return gesture.mode


class TestCameraManipulatorBindings:
    """Which mode each button and modifier state navigates in."""

    def test_kit_layout(self):
        man = CameraManipulator(camera_controller=CameraController())
        assert _press(man.look_gesture) == "look"
        assert _press(man.look_gesture, MOD_ALT) == "dolly"
        assert _press(man.tumble_gesture, MOD_ALT) == "orbit"
        assert _press(man.pan_gesture) == "pan"

    def test_an_unbound_modifier_does_not_block_a_button(self):
        man = CameraManipulator(camera_controller=CameraController())
        assert _press(man.look_gesture, MOD_SHIFT) == "look"
        assert _press(man.look_gesture, MOD_CTRL) == "look"
        assert _press(man.pan_gesture, MOD_CTRL | MOD_SHIFT) == "pan"

    def test_review_layout_tumbles_with_the_right_button(self):
        man = CameraManipulator(camera_controller=CameraController(), bindings=parse_bindings("review"))
        assert _press(man.tumble_gesture) == "orbit"
        assert _press(man.tumble_gesture, MOD_CTRL) == "look"
        assert _press(man.pan_gesture, MOD_ALT) == "dolly"

    def test_a_binding_change_moves_a_mode_to_another_button(self):
        man = CameraManipulator(
            camera_controller=CameraController(), bindings=parse_bindings("kit", ["pan=back", "none=middle"])
        )
        assert man.pan_gesture.mouse_button == 3
        assert _press(man.pan_gesture) == "pan"
        assert all(getattr(g, "mouse_button", None) != 2 for g in man.camera_gestures)

    def test_unknown_names_are_reported(self):
        for change in ("spin=left", "pan=wheel9", "look=right+hyper"):
            with pytest.raises(ValueError):
                parse_bindings("kit", [change])
        with pytest.raises(ValueError):
            parse_bindings("maya")

    def test_only_a_plain_right_drag_flies(self):
        cam = CameraController()
        kb = FlightModeKeyboard(cam)
        man = CameraManipulator(camera_controller=cam, flight_keyboard=kb)
        kb.handle_key_event(ord("W"), 0, True)
        _press(man.look_gesture, MOD_ALT)
        assert not kb.is_flying
        man.look_gesture._on_ended()
        _press(man.look_gesture, MOD_SHIFT)
        assert kb.is_flying
        _press(man.tumble_gesture, MOD_ALT)
        man.look_gesture._on_ended()
        assert not kb.is_flying

    def test_the_drag_zoom_works_when_look_is_disabled(self):
        cam = CameraController()
        model = CameraManipulatorModel()
        model.set_ints("disable_look", [1])
        man = CameraManipulator(camera_controller=cam, model=model, viewport_size_fn=_size_fn)
        assert _press(man.look_gesture) is None
        assert _press(man.look_gesture, MOD_ALT) == "dolly"
        man.look_gesture.raw_input.mouse.y = 0.25
        man.look_gesture._on_changed()
        assert cam.state.distance < 5.0

    def test_tumble_alt_gesture_is_the_alt_left_tumble(self):
        man = CameraManipulator(camera_controller=CameraController())
        assert man.tumble_alt_gesture is man.tumble_gesture
        assert man.tumble_gesture.mouse_button == MOUSE_LEFT
        assert man.tumble_gesture.modifiers == MOD_ALT
