# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""CameraManipulatorModel + CameraManipulator — the camera-navigation manipulator.

Step B.1 defined :class:`CameraManipulatorModel`, an
``sc.AbstractManipulatorModel`` subclass that holds the working state a group
of camera gestures share: pending translation/rotation deltas, per-mode speed
scalars, gate flags, stage metadata (``up_axis``, ``projection``,
``ndc_aspect``, ``center_of_interest``), and inertia coefficients. Gestures
mutate the model via ``set_floats`` / ``set_ints``; :class:`CameraManipulator`
(Step B.5) listens via ``on_model_updated`` and writes through to
``CameraController`` each frame.

Step B.5 adds :class:`CameraManipulator` — an ``sc.Manipulator`` subclass that
owns the four camera gestures (tumble, pan, look, zoom) plus the optional
flight-mode keyboard and tumble-inertia helpers. Its ``on_build`` attaches
the gestures to an ``sc.Screen`` inside the scene graph; its
``on_model_updated`` is a no-op today — the B.2 gestures mutate
``CameraController`` directly — and is reserved for the future model-first
write path described in the camera navigation behavior

The model is the data bus. ``CameraController`` remains the single source of
truth for camera state — everything on the model is transient input that the
gestures accumulate between frames.

Mirrors the item registration pattern of
``omni.kit.manipulator.camera.CameraManipulatorModel`` (see
the camera navigation behavior) so a future port of that
module's gestures can drop onto this model without reshaping the data bus.
"""

from typing import Any, Iterable, List, Optional

from omni.ui_scene import scene as sc

_FLOAT = "float"
_INT = "int"

# Default tumble/flight inertia time constant, in seconds, matching
# the camera navigation behavior ~85% decay over 300ms.
DEFAULT_INERTIA_SECONDS = 0.15

# Flat 16-float row-major identity matrix used as the default for ``transform``
# and ``projection``. Gestures that need the real camera matrix overwrite the
# item on ``on_began``; the identity default keeps the model self-consistent
# before any matrices have been pushed in.
_IDENTITY_4X4: List[float] = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]

# Item declarations: (name, kind, default values).
# ``kind`` determines which typed accessor — ``get_as_floats`` vs
# ``get_as_ints`` — returns the item's native values. The cross-kind accessors
# still work (they coerce), but storage is normalised to the declared kind so
# a 0/1 gate never silently becomes 0.9999.
_ITEM_DECLS = (
    ("move",               _FLOAT, [0.0, 0.0, 0.0]),
    ("rotate",             _FLOAT, [0.0, 0.0, 0.0]),
    ("speed",              _FLOAT, [1.0, 1.0, 1.0]),
    ("transform",          _FLOAT, list(_IDENTITY_4X4)),
    ("projection",         _FLOAT, list(_IDENTITY_4X4)),
    ("ndc_aspect",         _FLOAT, [1.0]),
    ("center_of_interest", _FLOAT, [0.0, 0.0, 0.0]),
    ("up_axis",            _FLOAT, [0.0, 1.0, 0.0]),
    ("fly_inertia",        _FLOAT, [DEFAULT_INERTIA_SECONDS]),
    ("tumble_inertia",     _FLOAT, [DEFAULT_INERTIA_SECONDS]),
    ("coi_picked",         _INT,   [0]),
    ("orthographic",       _INT,   [0]),
    ("disable_pan",        _INT,   [0]),
    ("disable_tumble",     _INT,   [0]),
    ("disable_look",       _INT,   [0]),
    ("disable_zoom",       _INT,   [0]),
    ("disable_fly",        _INT,   [0]),
)


class _CamItem(sc.AbstractManipulatorItem):
    """Per-item storage slot for ``CameraManipulatorModel``.

    Each item carries its declared kind (``"float"`` or ``"int"``) and its
    fixed size plus the current value list. ``CameraManipulatorModel`` creates
    one of these per registered name at construction; the instance is returned
    from ``get_item(name)`` and is the object ``set_floats`` / ``set_ints``
    mutate.
    """

    def __init__(self, name: str, kind: str, default: List[Any]) -> None:
        super().__init__()
        self.name = name
        self.kind = kind
        self.size = len(default)
        self.value: List[Any] = list(default)


class CameraManipulatorModel(sc.AbstractManipulatorModel):
    """sc.AbstractManipulatorModel implementation for camera gestures.

    See the viewport behavior for the item list and
    the camera navigation behavior for the role of this
    model in the gesture → manipulator → ``CameraController`` pipeline.

    All items are pre-registered at construction, so a gesture that writes to
    an unknown name is a no-op rather than silently allocating a new slot.
    """

    def __init__(self) -> None:
        super().__init__()
        self._items: dict = {
            name: _CamItem(name, kind, default)
            for name, kind, default in _ITEM_DECLS
        }

    # -- sc.AbstractManipulatorModel overrides ---------------------------------
    #
    # The installed ``omni.ui_scene`` bindings pass the item argument through
    # as a raw ``object`` without translating a string identifier into the
    # registered item on the C++ side. These overrides accept either form —
    # a bare string, an item instance, or ``None`` — so callers (and gestures)
    # can work with whichever is convenient.

    def get_item(self, identifier: str) -> Optional[_CamItem]:
        return self._items.get(identifier)

    def get_as_floats(self, item: Any) -> List[float]:
        resolved = self._resolve(item)
        if resolved is None:
            return []
        return [float(v) for v in resolved.value]

    def get_as_ints(self, item: Any) -> List[int]:
        resolved = self._resolve(item)
        if resolved is None:
            return []
        return [int(v) for v in resolved.value]

    def set_floats(self, item: Any, values: Iterable[float]) -> None:
        resolved = self._resolve(item)
        if resolved is None:
            return
        vals = [float(v) for v in values]
        self._assert_size(resolved, vals)
        resolved.value = [int(v) for v in vals] if resolved.kind == _INT else vals
        self._item_changed(resolved)

    def set_ints(self, item: Any, values: Iterable[int]) -> None:
        resolved = self._resolve(item)
        if resolved is None:
            return
        vals = [int(v) for v in values]
        self._assert_size(resolved, vals)
        resolved.value = (
            [float(v) for v in vals] if resolved.kind == _FLOAT else vals
        )
        self._item_changed(resolved)

    # -- helpers ---------------------------------------------------------------

    def _resolve(self, item: Any) -> Optional[_CamItem]:
        if isinstance(item, str):
            return self._items.get(item)
        if isinstance(item, _CamItem):
            return item
        return None

    @staticmethod
    def _assert_size(item: _CamItem, values: List[Any]) -> None:
        if len(values) != item.size:
            raise ValueError(
                f"item {item.name!r} expects {item.size} values, got {len(values)}"
            )


class CameraManipulator(sc.Manipulator):
    """sc.Manipulator that owns the camera gestures + optional flight/inertia.

    Step B.5 of the Viewport Plan. Replaces the free-function
    ``register_camera_gestures`` helper with a proper ``sc.Manipulator``
    subclass. Instantiated inside ``with sc.SceneView().scene:``; the draw
    loop calls :meth:`on_build`, which emits an ``sc.Screen(gestures=...)``
    covering the viewport. The gesture instances (one drag per bound
    button, the wheel zoom) are constructed eagerly in ``__init__`` so callers and tests can wire
    references (e.g., flight-keyboard RMB polling) before the first draw
    fires, and are reused across successive ``on_build`` invalidations.

    Flight-mode keyboard and tumble inertia are injected rather than
    constructed internally — :class:`~ovui_widgets.viewport.viewport_widget.ViewportWidget`
    already builds them before ``_build_ui`` so the app's key dispatcher can
    bind to ``flight_keyboard.handle_key_event`` in time for the first event.
    Passing them in keeps that wiring order intact.

    The ``model`` is both the ``sc.Manipulator``'s model (exposed via the
    inherited ``self.model`` property after ``super().__init__``) and the
    shared data bus for the gestures.
    """

    def __init__(
        self,
        camera_controller: Any,
        model: Optional["CameraManipulatorModel"] = None,
        viewport_size_fn: Optional[Any] = None,
        flight_keyboard: Optional[Any] = None,
        tumble_inertia: Optional[Any] = None,
        generation: Any = None,
        *,
        bindings: Optional[Iterable[Any]] = None,
        surface: Optional[Any] = None,
        options: Optional[Any] = None,
        **kwargs: Any,
    ) -> None:
        # Lazy imports keep this module's import graph flat: camera_gesture,
        # camera_flight_keyboard, and camera_inertia all import from
        # camera_manipulator, so importing them at module scope here would
        # cycle.
        from ovui_widgets.viewport.camera_gesture import (
            MOD_ANY,
            FlySpeedScrollGesture,
            NavigationGesture,
            ZoomScrollGesture,
            parse_bindings,
        )

        self._camera = camera_controller
        self._model: CameraManipulatorModel = (
            model if model is not None else CameraManipulatorModel()
        )
        self._viewport_size_fn = viewport_size_fn
        self._flight_keyboard = flight_keyboard
        self._tumble_inertia = tumble_inertia

        # One drag gesture per mouse button (Omniverse Kit's layout unless
        # ``bindings`` says otherwise, see ``camera_gesture.parse_bindings``).
        # A button with a plain binding takes every modifier state and picks
        # the binding of the held modifiers, or the plain one.
        bindings = list(bindings) if bindings is not None else parse_bindings()
        modes_by_button: dict = {}
        for mode, button, mods in bindings:
            if mode != "fly":
                modes_by_button.setdefault(button, {})[mods] = mode
        shared = dict(
            model=self._model,
            viewport_size_fn=viewport_size_fn,
            generation=generation,
            inertia=tumble_inertia,
            surface=surface,
            flight_keyboard=flight_keyboard,
            options=options,
        )
        drags_by_button: dict = {}
        for button, modes in modes_by_button.items():
            groups = [(MOD_ANY, modes)] if 0 in modes else [(mods, {mods: mode}) for mods, mode in modes.items()]
            drags_by_button[button] = [
                NavigationGesture(camera_controller, mouse_button=button, modifiers=mods, modes=group, **shared)
                for mods, group in groups
            ]
        self._drags: List[Any] = [drag for drags in drags_by_button.values() for drag in drags]
        self._tumble, self._pan, self._look, self._dolly = (
            next((drag for drag in self._drags if mode in drag.modes.values()), None)
            for mode in ("orbit", "pan", "look", "dolly")
        )
        self._zoom = ZoomScrollGesture(
            self._camera, model=self._model, generation=generation,
            viewport_size_fn=self._viewport_size_fn, surface=surface, options=options,
        )
        self._camera_gestures: List[Any] = [*self._drags, self._zoom]

        if self._flight_keyboard is not None:
            # The fly button: held with a fly key it flies, and its wheel
            # sets the fly speed. Wiring happens here (rather than in
            # on_build) so the keyboard sees the gestures before the first
            # key event.
            fly_buttons = {button for mode, button, _ in bindings if mode == "fly"}
            self._flight_keyboard.set_rmb_gestures(
                [drag for button in fly_buttons for drag in drags_by_button.get(button, ())]
            )
            for button in fly_buttons:
                self._camera_gestures.append(FlySpeedScrollGesture(self._flight_keyboard, generation, button))

        super().__init__(model=self._model, **kwargs)

    # -- introspection ----------------------------------------------------

    @property
    def camera_controller(self) -> Any:
        return self._camera

    @property
    def camera_gestures(self) -> List[Any]:
        """The drag gestures (one per button), the wheel zoom, then the fly-speed wheel of the fly button."""
        return list(self._camera_gestures)

    @property
    def tumble_gesture(self) -> Any:
        """The gesture that orbits (None when no binding orbits)."""
        return self._tumble

    @property
    def tumble_alt_gesture(self) -> Any:
        """The Alt+LMB tumble of Kit's layout: :attr:`tumble_gesture`."""
        return self._tumble

    @property
    def dolly_gesture(self) -> Any:
        return self._dolly

    @property
    def pan_gesture(self) -> Any:
        return self._pan

    @property
    def look_gesture(self) -> Any:
        return self._look

    @property
    def zoom_gesture(self) -> Any:
        return self._zoom

    @property
    def flight_keyboard(self) -> Any:
        return self._flight_keyboard

    @property
    def tumble_inertia(self) -> Any:
        return self._tumble_inertia

    # -- sc.Manipulator hooks --------------------------------------------

    def on_build(self) -> None:
        """Attach the gesture instances to an ``sc.Screen``.

        Called by ``sc.SceneView``'s draw pipeline whenever the manipulator
        is invalidated (or on first display). The same gesture instances
        are reused across rebuilds — sc preserves its retained-mode tree,
        and :class:`~omni.ui_scene.scene.AbstractShape.gestures` accepts
        re-registering an existing gesture on a fresh shape.
        """
        sc.Screen(gestures=self._camera_gestures)

    def on_model_updated(self, item: Any) -> None:
        """Placeholder for the future model-first write-through path.

        The Step B.2 gestures mutate :class:`CameraController` directly, so
        this hook has nothing to do today. the camera navigation behavior describes a richer design where gestures push only into the
        model and the manipulator translates item changes into controller
        mutations — wiring that up is not in B.5's scope.
        """

    # -- per-frame helpers -----------------------------------------------

    def integrate(self, dt: float) -> None:
        """Advance flight-mode velocity and tumble inertia one frame.

        Safe to call unconditionally; short-circuits when the corresponding
        subsystem is absent or inactive. Kept as a single entry point so
        :class:`~ovui_widgets.viewport.viewport_widget.ViewportWidget._on_frame` can
        drive both subsystems with one line.
        """
        if self._flight_keyboard is not None and self._flight_keyboard.is_flying:
            self._flight_keyboard.integrate(dt)
        if self._tumble_inertia is not None and self._tumble_inertia.is_active:
            self._tumble_inertia.tick(dt)
