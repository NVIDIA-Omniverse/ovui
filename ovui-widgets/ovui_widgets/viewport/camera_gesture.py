# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Camera navigation gestures of the viewport.

A :class:`NavigationGesture` turns the drag of one mouse button into the
navigation mode that the bindings give the held modifiers: ``look`` (turn in
place), ``orbit`` (tumble), ``pan`` or ``dolly`` (drag zoom). A press with a
modifier that has no binding of its own uses the button's plain binding, so an
extra Shift or Ctrl never blocks a button. :class:`TumbleGesture`,
:class:`LookGesture`, :class:`PanGesture` and :class:`DollyGesture` are
gestures of one mode. The wheel zooms (:class:`ZoomScrollGesture`); RMB + wheel
sets the fly speed (:class:`FlySpeedScrollGesture`). The gestures write to
``CameraController`` only; they never touch USD.

Input: the gestures read the native cursor motion of the window (pixels,
stamped when each event arrived), so a step is spread over the time the hand
took for it and the rotation acceleration sees the real hand speed. Without a
native window (headless, tests) they read ``raw_input.mouse``, in NDC (x and y
in [-1, +1] across the viewport, +y up), at callback time.

Surface: the orbit turns about the surface under the cursor, the pan grabs
that surface and both zooms approach it. A :class:`SurfaceQuery` asks the
renderer, which answers a frame or two later without stopping; a step that
needs the point waits for it at most :data:`SURFACE_WAIT` seconds, then uses
the point at the target's depth (also used where there is no surface).

Callback signatures: omni.ui_scene calls the callbacks with the owning shape
as a positional argument; each handler takes ``sender=None`` so tests can call
it directly.
"""

import json
import math
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import numpy as np
from omni.ui_scene import scene as sc

from ovui_widgets.viewport.camera_controller import CameraController
from ovui_widgets.viewport.camera_inertia import AngularVelocityTracker, TumbleInertia
from ovui_widgets.viewport.camera_manipulator import CameraManipulatorModel

# Keyboard modifier bit values — match ``carb::input::kKeyboardModifierFlag*``
# mirrored by ovui's ``omni::ui::kKeyMod*`` constants (core/include/omni/ui/Types.h).
MOD_NONE = 0
MOD_SHIFT = 1 << 0
MOD_CTRL = 1 << 1
MOD_ALT = 1 << 2
MOD_SUPER = 1 << 3
# Any modifier state: the gesture itself picks the binding of the modifiers.
MOD_ANY = 0xFFFFFFFF

# Mouse button numbers in ovui: 0 = Left, 1 = Right, 2 = Middle.
MOUSE_LEFT = 0
MOUSE_RIGHT = 1
MOUSE_MIDDLE = 2

# Default perspective FOV (radians), the camera controller's 45 degrees.
DEFAULT_FOV_Y = math.radians(45.0)

# Fallback viewport size used when the gesture is constructed without a
# ``viewport_size_fn``. 1280×720 matches ``ViewportWidget``'s initial
# ``_width``/``_height`` defaults.
_FALLBACK_VIEWPORT_SIZE: Tuple[int, int] = (1280, 720)

# Keep pan math inside the same practical distance envelope as
# CameraController. Invalid state is ignored instead of propagating NaN/inf.
_MAX_PAN_DISTANCE = 1.0e6

# Maximum absolute NDC coordinate accepted from ``raw_input.mouse``. The
# gesture system can dispatch ``on_changed`` against a sibling shape's frame
# (the pick Screen, the selection outline), which reports values like
# ``(-2.13, +2.24)``; rejecting events outside ``±1.5`` keeps the
# drag-past-edge tolerance and drops those.
_NDC_VALID_BOUND = 1.5

# Rotation acceleration: a hand that turns the camera faster than
# ROTATION_GAIN_FROM degrees per second is amplified smoothly, up to
# ROTATION_GAIN_MAX times at ROTATION_GAIN_FULL; a slow hand stays 1:1.
ROTATION_GAIN_FROM = 50.0
ROTATION_GAIN_FULL = 300.0
ROTATION_GAIN_MAX = 6.0
# Time over which the hand speed is averaged (seconds).
_HAND_SPEED_TIME = 0.1
# Longest time one input step is spread over (seconds): the first motion
# after a still hand is not drawn out, and the playback runs at most this
# far behind.
_MAX_STEP_TIME = 0.05
# The playback runs at most this many mean step intervals, and at most
# _MAX_QUEUE seconds, behind the hand.
_QUEUE_STEPS = 3.0
_MAX_QUEUE = 0.012
# Below this release speed (rad/s) a drag does not coast, so a click or a
# slow stop never starts inertia.
INERTIA_LAUNCH_SPEED = 0.5
# The drag zoom: a full-height drag scales the distance by exp(DOLLY_GAIN).
DOLLY_GAIN = 4.0
# The wheel scales the distance to the surface by 1 / ZOOM_STEP_RATIO per
# notch: 1.2 covers 1/6 of the distance, so the camera never passes it.
ZOOM_STEP_RATIO = 1.2
# Longest wait (seconds) for the renderer's surface point.
SURFACE_WAIT = 0.1

MODES = ("look", "orbit", "pan", "dolly")
_GATES = {"look": "disable_look", "orbit": "disable_tumble", "pan": "disable_pan", "dolly": "disable_zoom"}

# Button layouts: (mode, button, modifiers). ``fly`` names the button that,
# held with W/A/S/D/Q/E, flies.
PRESETS: Dict[str, Tuple[Tuple[str, int, int], ...]] = {
    # Omniverse Kit's viewport camera.
    "kit": (
        ("look", MOUSE_RIGHT, 0),
        ("orbit", MOUSE_LEFT, MOD_ALT),
        ("dolly", MOUSE_RIGHT, MOD_ALT),
        ("pan", MOUSE_MIDDLE, 0),
        ("fly", MOUSE_RIGHT, 0),
    ),
    # Content review: the right button tumbles, the left one stays for picking.
    "review": (
        ("orbit", MOUSE_RIGHT, 0),
        ("look", MOUSE_RIGHT, MOD_CTRL),
        ("look", MOUSE_RIGHT, MOD_ALT),
        ("pan", MOUSE_MIDDLE, 0),
        ("dolly", MOUSE_MIDDLE, MOD_CTRL),
        ("dolly", MOUSE_MIDDLE, MOD_ALT),
        ("fly", MOUSE_RIGHT, 0),
    ),
    # Web viewers (three.js OrbitControls); no fly.
    "web": (
        ("orbit", MOUSE_LEFT, 0),
        ("pan", MOUSE_RIGHT, 0),
        ("pan", MOUSE_LEFT, MOD_CTRL),
        ("pan", MOUSE_LEFT, MOD_SHIFT),
        ("pan", MOUSE_LEFT, MOD_ALT),
        ("dolly", MOUSE_MIDDLE, 0),
    ),
}
BUTTON_NAMES = {"left": 0, "lmb": 0, "right": 1, "rmb": 1, "middle": 2, "mmb": 2, "back": 3, "forward": 4}
MODIFIER_NAMES = {
    "shift": MOD_SHIFT, "ctrl": MOD_CTRL, "control": MOD_CTRL, "alt": MOD_ALT, "option": MOD_ALT,
    "super": MOD_SUPER, "cmd": MOD_SUPER, "win": MOD_SUPER,
}

ViewportSizeFn = Callable[[], Tuple[int, int]]


def parse_bindings(preset: str = "kit", changes: Iterable[str] = ()) -> List[Tuple[str, int, int]]:
    """The bindings of ``preset`` with ``changes`` applied.

    Each change is ``MODE=BUTTON[+MODIFIER...]`` (for example ``pan=back`` or
    ``look=right+ctrl``): it replaces the binding of that button and those
    modifiers. ``none`` removes it; ``fly`` moves the fly button. Buttons are
    the names of :data:`BUTTON_NAMES` or numbers 0 to 7. Raises ``ValueError``
    for an unknown preset, mode, button or modifier.
    """
    if preset not in PRESETS:
        raise ValueError(f"unknown navigation preset {preset!r}; use one of {sorted(PRESETS)}")
    table = {(button, mods): mode for mode, button, mods in PRESETS[preset] if mode != "fly"}
    fly = [(button, mods) for mode, button, mods in PRESETS[preset] if mode == "fly"]
    for change in changes:
        mode, _, keys = str(change).partition("=")
        mode = {"tumble": "orbit"}.get(mode.strip().lower(), mode.strip().lower())
        button_name, *mod_names = (part.strip() for part in keys.lower().split("+"))
        button = BUTTON_NAMES.get(button_name)
        if button is None:
            if not button_name.isdigit() or int(button_name) > 7:
                raise ValueError(f"unknown mouse button {button_name!r} in {change!r}")
            button = int(button_name)
        mods = 0
        for name in mod_names:
            if name not in MODIFIER_NAMES:
                raise ValueError(f"unknown modifier {name!r} in {change!r}")
            mods |= MODIFIER_NAMES[name]
        if mode == "fly":
            fly = [(button, mods)]
        elif mode == "none":
            table.pop((button, mods), None)
        elif mode in MODES:
            table[(button, mods)] = mode
        else:
            raise ValueError(f"unknown navigation mode {mode!r} in {change!r}")
    return [(mode, button, mods) for (button, mods), mode in table.items()] + [
        ("fly", button, mods) for button, mods in fly
    ]


def read_bindings_file(path: str) -> List[str]:
    """Binding changes from a JSON file: a list of ``MODE=BUTTON[+MODIFIER...]`` strings."""
    with open(path, encoding="utf-8") as handle:
        changes = json.load(handle)
    if not isinstance(changes, list) or not all(isinstance(change, str) for change in changes):
        raise ValueError(f"{path}: expected a JSON list of 'MODE=BUTTON[+MODIFIER]' strings")
    return changes


@dataclass
class NavigationOptions:
    """The per-user feel of the navigation gestures."""

    invert_look: bool = False  # mouse up turns the look (and fly) view down
    invert_orbit: bool = False  # mouse up turns the orbit the other way
    rotation_gain_max: float = ROTATION_GAIN_MAX
    wheel_step: float = ZOOM_STEP_RATIO
    raw_cursor: bool = False  # hide and lock the cursor during look and orbit drags


def _gate_is_set(model: Optional[CameraManipulatorModel], flag_name: str) -> bool:
    """Return True when the model is present and the named gate flag is 1."""
    if model is None:
        return False
    values = model.get_as_ints(flag_name)
    return bool(values and values[0])


def _mouse_in_ndc_bounds(mouse: Any) -> bool:
    """True when ``mouse.x`` and ``mouse.y`` lie within ``±_NDC_VALID_BOUND``."""
    return abs(mouse.x) <= _NDC_VALID_BOUND and abs(mouse.y) <= _NDC_VALID_BOUND


def _rotation_gain(hand_speed: float, gain_max: Optional[float] = None) -> float:
    """Gain for a hand turning at ``hand_speed`` degrees per second (smoothstep)."""
    gain_max = ROTATION_GAIN_MAX if gain_max is None else gain_max
    s = min(max((hand_speed - ROTATION_GAIN_FROM) / (ROTATION_GAIN_FULL - ROTATION_GAIN_FROM), 0.0), 1.0)
    return 1.0 + (gain_max - 1.0) * s * s * (3.0 - 2.0 * s)


def _viewport_size(viewport_size_fn: Optional[ViewportSizeFn]) -> Tuple[int, int]:
    size = viewport_size_fn() if viewport_size_fn is not None else None
    return size if size else _FALLBACK_VIEWPORT_SIZE


def _aspect(viewport_size_fn: Optional[ViewportSizeFn]) -> float:
    width, height = _viewport_size(viewport_size_fn)
    return width / height if width > 0 and height > 0 else 1.0


def _cursor_point(camera: CameraController, mouse: Any, viewport_size_fn: Optional[ViewportSizeFn]) -> Any:
    """World point under the cursor at the target depth."""
    return camera.cursor_point(mouse.x, mouse.y, _aspect(viewport_size_fn))


def _native_cursor_motion() -> Optional[Tuple[float, float, float]]:
    """``(dx, dy, time)`` of the window's cursor since the previous read, or None without a native window."""
    try:
        from omni.ui import _ui
    except ImportError:
        return None
    read = getattr(_ui, "_read_cursor_motion", None)
    return read() if callable(read) else None


def _capture_cursor(captured: bool) -> None:
    from omni.ui import _ui

    capture = getattr(_ui, "_set_cursor_capture", None)
    if callable(capture):
        capture(captured)


class _SurfacePoint:
    """The answer to one surface query: call it for the point, None while it is not known."""

    def __init__(self, hit_fn: Callable[[], Any], query: int, fallback: Any, deadline: float, clock: Callable[[], float]):
        self._hit_fn = hit_fn
        self._query = query
        self._fallback = np.asarray(fallback, dtype=np.float64)
        self._deadline = deadline
        self._clock = clock
        self.point = None if query else self._fallback

    def __call__(self) -> Any:
        if self.point is None:
            answered, hit = self._hit_fn()
            if answered >= self._query or self._clock() > self._deadline:
                found = answered == self._query and hit is not None
                self.point = np.asarray(hit, dtype=np.float64) if found else self._fallback
        return self.point


class SurfaceQuery:
    """Surface points under the cursor, asked of the renderer without waiting for it.

    ``renderer_fn`` returns the renderer adapter (``query_surface(x, y)`` and
    ``surface_hit()``); ``map_fn`` maps viewport NDC to rendered-image NDC.
    """

    def __init__(
        self,
        renderer_fn: Callable[[], Any],
        map_fn: Optional[Callable[[float, float], Any]] = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._renderer_fn = renderer_fn
        self._map_fn = map_fn
        self._clock = clock
        self._last: Optional[Tuple[Tuple[float, float], _SurfacePoint]] = None

    def point(self, camera: CameraController, mouse: Any, viewport_size_fn: Optional[ViewportSizeFn]) -> _SurfacePoint:
        """The surface point under ``mouse``; the point at the target's depth when there is none.

        Asking again at the same cursor reuses the previous answer while its
        point is still under the cursor (as during a zoom toward it).
        """
        ndc = (float(mouse.x), float(mouse.y))
        aspect = _aspect(viewport_size_fn)
        if self._last is not None and self._last[0] == ndc and self._still_under(camera, self._last[1].point, ndc, aspect):
            return self._last[1]
        renderer = self._renderer_fn()
        render_ndc = self._map_fn(*ndc) if self._map_fn is not None else ndc
        query = 0
        if render_ndc is not None and callable(getattr(renderer, "query_surface", None)):
            query = renderer.query_surface(*render_ndc)
        answer = _SurfacePoint(
            getattr(renderer, "surface_hit", None),
            query,
            camera.cursor_point(ndc[0], ndc[1], aspect),
            self._clock() + SURFACE_WAIT,
            self._clock,
        )
        self._last = (ndc, answer)
        return answer

    @staticmethod
    def _still_under(camera: CameraController, point: Any, ndc: Tuple[float, float], aspect: float) -> bool:
        if point is None:
            return True  # not answered yet
        right, up, back = camera._view_basis()
        offset = point - camera._get_eye()
        depth = -float(np.dot(offset, back))
        if depth <= 0.0:
            return False
        half = math.tan(math.radians(camera.fov_degrees) / 2.0) * depth
        x = float(np.dot(offset, right)) / (half * aspect)
        y = float(np.dot(offset, up)) / half
        return abs(x - ndc[0]) < 1.0e-3 and abs(y - ndc[1]) < 1.0e-3


class NavigationGesture(sc.DragGesture):
    """The drag of one mouse button, in the mode the bindings give the held modifiers.

    ``modes`` maps modifiers to a mode of :data:`MODES`; the plain binding
    (modifiers 0) also takes a press whose modifiers have no binding. Look and
    orbit steps are smoothed by the camera; the pan grabs the surface under
    the press and the drag zoom approaches it. Look and orbit coast after a
    release faster than :data:`INERTIA_LAUNCH_SPEED` (with an ``inertia``).
    A new drag stops all coasting of the camera.
    """

    _default_mode = "look"

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
        viewport_size_fn: Optional[ViewportSizeFn] = None,
        mouse_button: int = MOUSE_RIGHT,
        modifiers: int = MOD_ANY,
        generation: Any = None,
        *,
        modes: Optional[Dict[int, str]] = None,
        inertia: Optional[TumbleInertia] = None,
        surface: Optional[SurfaceQuery] = None,
        flight_keyboard: Any = None,
        options: Optional[NavigationOptions] = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        super().__init__(mouse_button=mouse_button, modifiers=modifiers)
        self._camera = camera
        self._model = model
        self._viewport_size_fn = viewport_size_fn
        self._generation = generation
        self._modes = dict(modes) if modes else {0 if modifiers == MOD_ANY else modifiers: self._default_mode}
        self._inertia = inertia
        self._surface = surface
        self._flight_keyboard = flight_keyboard
        self.options = options or NavigationOptions()
        self._clock = clock
        self._velocity_tracker = AngularVelocityTracker(clock=clock)
        self._mode: Optional[str] = None
        self._fov_y: Optional[float] = None  # the camera's field of view
        self._plain = False
        self._native = False
        self._native_seen = False
        self._captured = False
        self._point: Any = None
        self._time: Optional[float] = None
        self._timed = False
        self._decay = 0.0
        self._span = 0.0
        self._moved = 0.0
        self._steps = 0.0
        self._turned = 0.0
        self._queue_end = 0.0
        self._prev_x = 0.0
        self._prev_y = 0.0
        self._prev_anchored = False
        self.set_on_began_fn(self._on_began)
        self.set_on_changed_fn(self._on_changed)
        self.set_on_ended_fn(self._on_ended)

    @property
    def modes(self) -> Dict[int, str]:
        """Mode of each modifier state this gesture handles."""
        return dict(self._modes)

    @property
    def mode(self) -> Optional[str]:
        """The mode of the live drag, or None."""
        return self._mode

    @property
    def is_active(self) -> bool:
        """True while a drag of this gesture navigates (between ``on_began`` and ``on_ended``)."""
        return self._mode is not None

    @property
    def flies(self) -> bool:
        """True while the button is held through its plain binding: fly keys fly then."""
        return self._mode is not None and self._plain

    def _effective(self) -> bool:
        return self._generation is None or self._generation.effective

    def _on_began(self, sender: Any = None) -> None:
        if not self._effective():
            return
        # The gesture manager matched the modifiers of a one-mode gesture.
        mods = int(self.raw_input.modifiers or 0) & (MOD_SHIFT | MOD_CTRL | MOD_ALT | MOD_SUPER)
        key = mods if mods in self._modes or len(self._modes) > 1 else next(iter(self._modes))
        key = key if key in self._modes else 0
        mode = self._modes.get(key)
        if mode is None or _gate_is_set(self._model, _GATES[mode]):
            self._mode = None
            return
        self._mode = mode
        self._plain = key == 0
        self._camera.stop_coasting()
        if self._inertia is not None:
            self._inertia.stop()
        self._velocity_tracker.reset()
        self._span = self._moved = self._steps = self._turned = self._queue_end = 0.0
        self._native = _native_cursor_motion() is not None  # drops the motion before the press
        self._native_seen = False
        self._time = None  # the first step plays at once and starts the hand's time
        m = self.raw_input.mouse
        # A began from the wrong shape (see ``_mouse_in_ndc_bounds``) anchors
        # at the first in-bounds ``on_changed`` instead.
        self._prev_anchored = _mouse_in_ndc_bounds(m)
        self._prev_x, self._prev_y = (m.x, m.y) if self._prev_anchored else (0.0, 0.0)
        self._point = None
        if mode != "look" and self._prev_anchored:
            if self._surface is not None:
                self._point = self._surface.point(self._camera, m, self._viewport_size_fn)
            else:
                self._point = _cursor_point(self._camera, m, self._viewport_size_fn)
        self._captured = self.options.raw_cursor and self._native and mode in ("look", "orbit")
        if self._captured:
            _capture_cursor(True)

    def _on_changed(self, sender: Any = None) -> None:
        if not self._effective() or self._mode is None:
            return
        # The window's own cursor events when they come; input that does not
        # pass through the window (injected or streamed) moves only the
        # cursor of raw_input.
        motion = _native_cursor_motion() if self._native else None
        if motion is not None and (motion[0] or motion[1]):
            width, height = _viewport_size(self._viewport_size_fn)
            self._native_seen = True
            self._move(2.0 * motion[0] / width, -2.0 * motion[1] / height, motion[2])
        m = self.raw_input.mouse
        if not _mouse_in_ndc_bounds(m):
            return
        if not self._prev_anchored:
            self._prev_x, self._prev_y, self._prev_anchored = m.x, m.y, True
            return
        dx_ndc, dy_ndc = m.x - self._prev_x, m.y - self._prev_y
        self._prev_x, self._prev_y = m.x, m.y
        if not self._native_seen:
            self._move(dx_ndc, dy_ndc, self._clock())

    def _move(self, dx_ndc: float, dy_ndc: float, now: float) -> None:
        if not dx_ndc and not dy_ndc:
            return
        # The steps are played back to back, each at the hand's mean speed
        # over the last _HAND_SPEED_TIME seconds (from the event times), so
        # the camera follows the hand's pace, not the uneven pace at which
        # the events reach the app.
        interval = 0.0 if self._time is None else min(max(now - self._time, 0.0), _MAX_STEP_TIME)
        self._time = now
        self._decay = math.exp(-interval / _HAND_SPEED_TIME)
        self._timed = interval > 0.0  # the first step has no time of its own
        if self._timed:
            self._span = self._span * self._decay + interval
            self._moved = self._moved * self._decay + math.hypot(dx_ndc, dy_ndc)
            self._steps = self._steps * self._decay + 1.0
        clock = self._clock()
        start = min(max(self._queue_end, clock), clock + min(_QUEUE_STEPS * self._span / max(self._steps, 1.0), _MAX_QUEUE))
        duration = min(math.hypot(dx_ndc, dy_ndc) * self._span / self._moved, _MAX_STEP_TIME) if self._moved else 0.0
        self._queue_end = start + duration
        step = dict(duration=duration, delay=start - clock)
        if self._mode == "pan":
            self._pan(dx_ndc, dy_ndc, step)
        elif self._mode == "dolly":
            self._camera.smooth("dolly", -0.5 * DOLLY_GAIN * dy_ndc, anchor=self._point, **step)
        else:
            self._rotate(dx_ndc, dy_ndc, step)

    def _rotate(self, dx_ndc: float, dy_ndc: float, step: Dict[str, float]) -> None:
        # A full-width drag (dx_ndc = 2) turns a full rotation; a right drag
        # turns the scene with the hand.
        method = self._method()
        invert = self.options.invert_look if method == "look" else self.options.invert_orbit
        rotate_y = -dx_ndc * math.pi
        rotate_x = (dy_ndc if invert else -dy_ndc) * math.pi
        if self._timed:
            self._turned = self._turned * self._decay + math.degrees(math.hypot(rotate_y, rotate_x))
        hand_speed = self._turned / self._span if self._span > 0.0 else 0.0
        gain = _rotation_gain(hand_speed, self.options.rotation_gain_max)
        rotate_y *= gain
        rotate_x *= gain
        self._velocity_tracker.record(rotate_y, rotate_x, self._time)
        self._camera.smooth(method, rotate_y, rotate_x, anchor=self._point if method == "orbit" else None, **step)

    def _method(self) -> str:
        """Fly keys turn a plain orbit drag into a look: the mouse steers the fly."""
        flying = self._plain and self._flight_keyboard is not None and self._flight_keyboard.is_flying
        return "look" if flying else self._mode

    def _pan(self, dx_ndc: float, dy_ndc: float, step: Dict[str, float]) -> None:
        # The grabbed point stays under the cursor: one NDC unit is the half
        # extent of the view at the grabbed point's depth.
        point = self._point() if callable(self._point) else self._point
        depth = self._camera.depth_of(point) if point is not None else float(self._camera.state.distance)
        if not math.isfinite(depth) or depth <= 0.0:
            depth = float(self._camera.state.distance)
        if not math.isfinite(depth):
            return
        fov_y = self._fov_y if self._fov_y is not None else math.radians(self._camera.fov_degrees)
        world_per_ndc_y = min(depth, _MAX_PAN_DISTANCE) * math.tan(fov_y / 2.0)
        aspect = _aspect(self._viewport_size_fn)
        if not math.isfinite(aspect) or aspect <= 0.0:
            aspect = 1.0
        self._camera.smooth("pan", -dx_ndc * world_per_ndc_y * aspect, -dy_ndc * world_per_ndc_y, **step)

    def _on_ended(self, sender: Any = None) -> None:
        if not self._effective():
            return
        if self._captured:
            _capture_cursor(False)
            self._captured = False
        mode, self._mode = self._mode, None
        if mode not in ("look", "orbit") or self._inertia is None:
            return
        vy, vx = self._velocity_tracker.pop_handoff()
        if math.hypot(vy, vx) >= INERTIA_LAUNCH_SPEED:
            point = self._point
            if mode == "orbit":
                self._inertia.start(vy, vx, lambda y, x: self._camera.orbit(y, x, point() if callable(point) else point))
            else:
                self._inertia.start(vy, vx, self._camera.look)


class TumbleGesture(NavigationGesture):
    """Drag to orbit about the surface under the cursor (the target without a surface query)."""

    _default_mode = "orbit"

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
        viewport_size_fn: Optional[ViewportSizeFn] = None,
        inertia: Optional[TumbleInertia] = None,
        mouse_button: int = MOUSE_RIGHT,
        modifiers: int = MOD_NONE,
        clock: Callable[[], float] = time.perf_counter,
        generation: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(camera, model, viewport_size_fn, mouse_button, modifiers, generation,
                         inertia=inertia, clock=clock, **kwargs)


class LookGesture(NavigationGesture):
    """Drag to turn the view in place: the eye stays, the target moves."""

    _default_mode = "look"

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
        viewport_size_fn: Optional[ViewportSizeFn] = None,
        mouse_button: int = MOUSE_RIGHT,
        modifiers: int = MOD_SHIFT,
        generation: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(camera, model, viewport_size_fn, mouse_button, modifiers, generation, **kwargs)


class PanGesture(NavigationGesture):
    """Drag to move the camera sideways; the surface under the press stays under the cursor.

    ``fov_y`` (radians) is the vertical field of view the pan scale uses.
    """

    _default_mode = "pan"

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
        viewport_size_fn: Optional[ViewportSizeFn] = None,
        fov_y: float = DEFAULT_FOV_Y,
        mouse_button: int = MOUSE_MIDDLE,
        modifiers: int = MOD_NONE,
        generation: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(camera, model, viewport_size_fn, mouse_button, modifiers, generation, **kwargs)
        self._fov_y = fov_y


class DollyGesture(NavigationGesture):
    """Drag up to zoom toward the surface under the press (Kit's Alt+RMB)."""

    _default_mode = "dolly"

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
        viewport_size_fn: Optional[ViewportSizeFn] = None,
        mouse_button: int = MOUSE_RIGHT,
        modifiers: int = MOD_ALT,
        generation: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(camera, model, viewport_size_fn, mouse_button, modifiers, generation, **kwargs)


class ZoomScrollGesture(sc.ScrollGesture):
    """Mouse wheel → zoom toward the surface under the cursor.

    Each notch scales the distance to that point by ``1 / wheel_step``, so a
    notch covers the same share of the remaining distance (1/6 at 1.2) and
    the camera never passes the surface. Wheel up zooms in. The camera
    glides to each step (its zoom glide half-life).
    """

    def __init__(
        self,
        camera: CameraController,
        model: Optional[CameraManipulatorModel] = None,
        generation: Any = None,
        viewport_size_fn: Optional[ViewportSizeFn] = None,
        *,
        surface: Optional[SurfaceQuery] = None,
        options: Optional[NavigationOptions] = None,
    ) -> None:
        # ``ScrollGesture``'s defaults: any button state, any modifiers.
        super().__init__()
        self._generation = generation
        self._camera = camera
        self._model = model
        self._viewport_size_fn = viewport_size_fn
        self._surface = surface
        self.options = options or NavigationOptions()
        self.set_on_ended_fn(self._on_ended)

    def _on_ended(self, sender: Any = None) -> None:
        if self._generation is not None and not self._generation.effective:
            return
        if _gate_is_set(self._model, "disable_zoom"):
            return
        notches = self.raw_input.mouse_wheel.y
        if notches == 0.0:
            return
        mouse = self.raw_input.mouse
        if self._surface is not None:
            point = self._surface.point(self._camera, mouse, self._viewport_size_fn)
        else:
            point = _cursor_point(self._camera, mouse, self._viewport_size_fn)
        self._camera.stop_coasting()
        self._camera.smooth("dolly", -notches * math.log(self.options.wheel_step), anchor=point)


class FlySpeedScrollGesture(sc.ScrollGesture):
    """RMB + wheel → change the fly speed instead of zooming (Kit)."""

    def __init__(self, flight_keyboard: Any, generation: Any = None, mouse_button: int = MOUSE_RIGHT) -> None:
        # Bound with any modifier, so the drag of the same button does not
        # prevent it (the gesture manager lets a drag and a scroll with the
        # same buttons and modifiers run together).
        super().__init__(mouse_button=mouse_button, modifiers=MOD_ANY)
        self._flight_keyboard = flight_keyboard
        self._generation = generation
        self.set_on_ended_fn(self._on_ended)

    def _on_ended(self, sender: Any = None) -> None:
        if self._generation is not None and not self._generation.effective:
            return
        self._flight_keyboard.step_speed(self.raw_input.mouse_wheel.y)
