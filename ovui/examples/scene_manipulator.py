# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
omni.ui.scene — XYZ Translate Manipulator
==========================================

A 3D scene with an interactive translate manipulator:

  • Red arrow  (X) — left-drag to translate along X
  • Green arrow (Y) — left-drag to translate along Y
  • Blue arrow  (Z) — left-drag to translate along Z
  • Right-drag anywhere to orbit the camera
  • Arrows highlight on hover; status bar shows current position

Usage::

    python examples/scene_manipulator.py              # interactive window
    python examples/scene_manipulator.py --screenshot  # headless PNG capture
"""

import math
import os
import sys
from pathlib import Path

# Ensure omni.ui_scene is importable from the local repo tree even when only
# omni.ui has been pip-installed.  This is a no-op if the package is already
# on sys.path (e.g. after a full 'pip install -e .').
_REPO_PYTHON = Path(__file__).resolve().parent.parent / "python"
if _REPO_PYTHON.is_dir() and str(_REPO_PYTHON) not in sys.path:
    sys.path.insert(0, str(_REPO_PYTHON))
_SCRIPT_DIR = Path(__file__).resolve().parent

import omni.ui as ui
from omni.ui_scene import scene as sc
from omni.ui import color as cl


# ── Headless gesture manager fix ───────────────────────────────────────────────
#
# SceneView._captureInput() only sets MouseInput.clicked when
# isHovered() && isWindowHovered — both may be False in headless Vulkan mode
# because ImGui's window-hover tracking relies on the GLFW event loop.
#
# GestureManager.amend_input() is called *before* gesture dispatch, so we
# can synthesise clicked = newly-pressed buttons (down & ~prev_down) here.
# AbstractShape.setGestures() only overwrites a gesture's manager when the
# gesture has none yet, so setting drag.manager before sc.Line(...) preserves
# our custom manager throughout the manipulator's lifetime.

class _HeadlessGestureManager(sc.GestureManager):
    """Synthesise 'clicked' from button-down transitions in headless mode."""

    def __init__(self):
        super().__init__()
        self._prev_down = 0

    def amend_input(self, inp):
        if inp.clicked == 0 and inp.down != 0:
            inp.clicked = inp.down & ((~self._prev_down) & 0xFFFFFFFF)
        self._prev_down = inp.down
        return inp


_headless_mgr = _HeadlessGestureManager()

# ── Configuration ──────────────────────────────────────────────────────────────

_SCREENSHOT = "--screenshot" in sys.argv
_SCREENSHOT_FAILED = False

WIN_W, WIN_H = 900, 680
SCENE_H      = 580          # pixels of vertical space for the 3D viewport

# Axis colors — cl(r, g, b, a) with floats in [0, 1].
# cl() returns an ImGui-compatible packed uint32 in ABGR order.
C_X      = cl(0.92, 0.22, 0.22)          # red   — X axis
C_X_HI   = cl(1.00, 0.45, 0.45)          # bright red on hover
C_Y      = cl(0.22, 0.88, 0.32)          # green — Y axis
C_Y_HI   = cl(0.40, 1.00, 0.55)
C_Z      = cl(0.25, 0.50, 1.00)          # blue  — Z axis
C_Z_HI   = cl(0.45, 0.68, 1.00)
C_CUBE   = cl(0.88, 0.88, 0.88)          # light grey wireframe cube
C_GM     = cl(0.45, 0.45, 0.45, 0.60)    # semi-transparent grid major
C_Gm     = cl(0.28, 0.28, 0.28, 0.40)    # semi-transparent grid minor
C_AX_X   = cl(0.92, 0.22, 0.22, 0.35)    # faint world-space origin axis
C_AX_Y   = cl(0.22, 0.88, 0.32, 0.35)
C_AX_Z   = cl(0.25, 0.50, 1.00, 0.35)

# Window chrome (same cl() encoding for ImGui styles)
BG_DARK  = cl(0.10, 0.10, 0.10)
BG_MID   = cl(0.13, 0.13, 0.14)
C_TEXT   = cl(0.83, 0.83, 0.83)
C_DIM    = cl(0.48, 0.48, 0.48)

# Axis table: (direction-vector, normal-color, hover-color, label-char)
_AXES = [
    ([1.0, 0.0, 0.0], C_X, C_X_HI, "X"),
    ([0.0, 1.0, 0.0], C_Y, C_Y_HI, "Y"),
    ([0.0, 0.0, 1.0], C_Z, C_Z_HI, "Z"),
]

ARROW_LEN   = 1.9   # world units
ARROW_THICK = 5.0   # base shaft thickness (px)
TIP_R       = 0.13  # arrowhead cone radius


# ── Math helpers ───────────────────────────────────────────────────────────────

def _cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _normalize(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 1e-9 else list(v)


def _perspective(fov_deg=55.0, aspect=1.5, near=0.1, far=200.0):
    """Column-major perspective projection matrix (flat list, 16 floats)."""
    f  = 1.0 / math.tan(math.radians(fov_deg * 0.5))
    nf = 1.0 / (near - far)
    return [
        f / aspect,  0.0,  0.0,                  0.0,
        0.0,         f,    0.0,                  0.0,
        0.0,         0.0,  (far + near) * nf,   -1.0,
        0.0,         0.0,  2.0 * far * near * nf, 0.0,
    ]


def _orbit_view(yaw_deg, pitch_deg, dist=9.0):
    """View matrix for a camera orbiting the origin (pitch×X, yaw×Y)."""
    rot   = sc.Matrix44.get_rotation_matrix(pitch_deg, yaw_deg, 0.0, True)
    trans = sc.Matrix44.get_translation_matrix(0.0, 0.0, -dist)
    m     = trans * rot
    return [m[i] for i in range(16)]


# ── Camera model ───────────────────────────────────────────────────────────────

class OrbitCamera(sc.AbstractManipulatorModel):
    """Perspective orbit camera — right-drag the viewport to rotate."""

    def __init__(self, aspect: float = 1.5):
        super().__init__()
        self._aspect =  aspect
        self._yaw    =  35.0    # horizontal (degrees)
        self._pitch  =  22.0    # vertical   (degrees)

    def rotate(self, d_yaw: float, d_pitch: float) -> None:
        self._yaw   += d_yaw
        self._pitch  = max(-88.0, min(88.0, self._pitch + d_pitch))
        self._item_changed("view")

    def get_as_floats(self, item) -> list:
        if item == self.get_item("projection"):
            return _perspective(fov_deg=55.0, aspect=self._aspect)
        if item == self.get_item("view"):
            return _orbit_view(self._yaw, self._pitch, dist=9.0)
        return []


# ── Translate manipulator ──────────────────────────────────────────────────────

class TranslateManipulator(sc.Manipulator):
    """
    XYZ gizmo that lets the user drag each axis arrow to translate a cube.

    on_build() draws the full scene contents — grid, reference axes, cube, and
    the three interactive arrow gizmos — inside a Transform positioned at the
    current object location.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pos            = [0.0, 0.0, 0.0]   # current world position
        self._hovered        = -1                  # axis index under cursor (-1 = none)
        self._drag_start_pos = None                # _pos snapshot at drag start
        self._drag_start_pt  = None                # 3D world point at drag start
        # Gesture objects are created ONCE and reused across on_build() calls.
        # This keeps gestures alive in eBegan/eChanged state across rebuilds so
        # that invalidate() called from _drag_changed doesn't reset the gesture
        # to ePossible and break multi-frame drags.
        self._drags = [
            sc.DragGesture(
                on_began_fn   = lambda s, i=i: self._drag_began(s, i),
                on_changed_fn = lambda s, i=i: self._drag_changed(s, i),
                on_ended_fn   = lambda s:       self._drag_ended(s),
            )
            for i in range(3)
        ]
        for drag in self._drags:
            drag.manager = _headless_mgr
        self._hovers = [
            sc.HoverGesture(
                on_began_fn = lambda s, i=i: self._hover_in(i),
                on_ended_fn = lambda s, i=i: self._hover_out(i),
            )
            for i in range(3)
        ]

    @property
    def position(self) -> list:
        return list(self._pos)

    # ── Manipulator.on_build ───────────────────────────────────────────────────

    def on_build(self):
        # Grid and world-origin axes are scene-anchored — draw them at the
        # world origin so they stay put while the cube translates.
        _draw_grid()
        _draw_origin_axes()

        # Only the cube and its gizmo arrows follow _pos.
        tf = sc.Matrix44.get_translation_matrix(*self._pos)
        with sc.Transform(transform=tf):
            _draw_cube()
            for idx, (axis, col, col_hi, label) in enumerate(_AXES):
                is_hot  = (self._hovered == idx)
                color   = col_hi if is_hot else col
                thick   = ARROW_THICK * (1.9 if is_hot else 1.0)
                self._build_arrow(idx, axis, color, thick, label)

    # ── arrow builder ──────────────────────────────────────────────────────────

    def _build_arrow(self, idx, axis, color, thick, label):
        tip = [ARROW_LEN * v for v in axis]

        # Two vectors perpendicular to the axis (for the cone rim).
        # Pick a reference that is NOT parallel to the axis — using Y as
        # the default gave a zero cross-product for the Y arrow itself,
        # collapsing the arrowhead cone.
        ref   = [1.0, 0.0, 0.0] if abs(axis[1]) > 0.9 else [0.0, 1.0, 0.0]
        perp0 = _normalize(_cross(axis, ref))
        perp1 = _cross(axis, perp0)

        cone_base = [(ARROW_LEN - TIP_R * 2.0) * v for v in axis]

        # Reuse pre-created gesture objects (created once in __init__).
        # Stable gesture identity keeps the DragGesture in eBegan/eChanged
        # across on_build() rebuilds triggered by invalidate(), so multi-
        # frame drags work correctly.
        drag  = self._drags[idx]
        hover = self._hovers[idx]

        # Shaft — carries drag gesture.
        # intersection_thickness=12 gives the hit-area radius in screen pixels.
        # 12px is wide enough for comfortable interactive use and tight enough
        # that adjacent arrows don't accidentally trigger each other.
        sc.Line([0.0, 0.0, 0.0], cone_base,
                color=color, thickness=thick,
                intersection_thickness=12.0,
                gesture=drag)

        # Arrowhead cone — 4 lines from rim to tip
        for s0, s1 in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            rim = [cone_base[j] + (s0 * perp0[j] + s1 * perp1[j]) * TIP_R
                   for j in range(3)]
            sc.Line(rim, tip, color=color, thickness=thick * 0.8)

        # Axis label
        lp = [(ARROW_LEN + 0.32) * v for v in axis]
        with sc.Transform(transform=sc.Matrix44.get_translation_matrix(*lp)):
            sc.Label(label, color=color, size=16, alignment=ui.Alignment.CENTER)

    # ── gesture handlers ───────────────────────────────────────────────────────

    def _drag_began(self, shape, idx):
        self._drag_start_pos = list(self._pos)
        self._drag_start_pt  = _payload_point(shape.gesture_payload)

    def _drag_changed(self, shape, idx):
        if self._drag_start_pos is None or self._drag_start_pt is None:
            return
        curr = _payload_point(shape.gesture_payload)
        if curr is None:
            return
        axis  = _AXES[idx][0]
        delta = [curr[j] - self._drag_start_pt[j] for j in range(3)]
        proj  = sum(delta[j] * axis[j] for j in range(3))
        self._pos = [self._drag_start_pos[j] + axis[j] * proj for j in range(3)]
        self.invalidate()

    def _drag_ended(self, shape):
        self._drag_start_pos = None
        self._drag_start_pt  = None

    def _hover_in(self, idx):
        if self._hovered != idx:
            self._hovered = idx
            self.invalidate()

    def _hover_out(self, idx):
        if self._hovered == idx:
            self._hovered = -1
            self.invalidate()


# ── Scene decoration helpers ───────────────────────────────────────────────────

def _draw_grid():
    """Reference grid in the XZ plane (Y = 0)."""
    for i in range(-5, 6):
        c = C_GM if (i == 0) else C_Gm
        t = 1.5  if (i == 0) else 1.0
        sc.Line([float(i), 0.0, -5.0], [float(i),  0.0,  5.0], color=c, thickness=t)
        sc.Line([-5.0, 0.0, float(i)], [ 5.0,  0.0, float(i)], color=c, thickness=t)


def _draw_origin_axes():
    """Faint world-origin axis lines so the user always knows where (0,0,0) is."""
    sc.Line([-5.0, 0.0, 0.0], [5.0, 0.0, 0.0], color=C_AX_X, thickness=1.0)
    sc.Line([0.0, -5.0, 0.0], [0.0, 5.0, 0.0], color=C_AX_Y, thickness=1.0)
    sc.Line([0.0, 0.0, -5.0], [0.0, 0.0, 5.0], color=C_AX_Z, thickness=1.0)


def _draw_cube():
    """Wireframe cube centered at the origin — the 'object' being translated."""
    s = 0.42
    v = [
        (-s, -s, -s), ( s, -s, -s), ( s,  s, -s), (-s,  s, -s),
        (-s, -s,  s), ( s, -s,  s), ( s,  s,  s), (-s,  s,  s),
    ]
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),   # back face
        (4, 5), (5, 6), (6, 7), (7, 4),   # front face
        (0, 4), (1, 5), (2, 6), (3, 7),   # connecting edges
    ]
    for a, b in edges:
        sc.Line(list(v[a]), list(v[b]), color=C_CUBE, thickness=2.0)


# ── Payload helper ─────────────────────────────────────────────────────────────

def _payload_point(payload):
    """Return the best 3D world-space point from a shape gesture payload."""
    for attr in ("line_closest_point", "ray_closest_point"):
        pt = getattr(payload, attr, None)
        if pt is not None:
            return list(pt)
    return None


# ── Projection helper ──────────────────────────────────────────────────────────

def _project_world_to_screen(world_pt, view_mat, proj_mat, scene_x, scene_y, scene_w, scene_h):
    """Project a 3D world point to window pixel coordinates.

    Parameters
    ----------
    world_pt  : [x, y, z]
    view_mat  : flat 16-element column-major view matrix
    proj_mat  : flat 16-element column-major projection matrix
    scene_x/y : top-left pixel offset of the SceneView within the window
    scene_w/h : pixel size of the SceneView widget
    """
    def _mat_vec(m, v):
        # column-major 4×4 * vec4
        return [
            m[0]*v[0] + m[4]*v[1] + m[ 8]*v[2] + m[12]*v[3],
            m[1]*v[0] + m[5]*v[1] + m[ 9]*v[2] + m[13]*v[3],
            m[2]*v[0] + m[6]*v[1] + m[10]*v[2] + m[14]*v[3],
            m[3]*v[0] + m[7]*v[1] + m[11]*v[2] + m[15]*v[3],
        ]
    vp = view_mat
    pp = proj_mat
    p4 = [world_pt[0], world_pt[1], world_pt[2], 1.0]
    eye  = _mat_vec(vp, p4)
    clip = _mat_vec(pp, eye)
    if abs(clip[3]) < 1e-9:
        return None
    ndc_x = clip[0] / clip[3]
    ndc_y = clip[1] / clip[3]
    # NDC → pixel; SceneView uses: mouse.x = -1 + 2*(px - cursor.x)/width
    px = scene_x + (ndc_x + 1.0) * 0.5 * scene_w
    py = scene_y + (1.0 - ndc_y) * 0.5 * scene_h
    return (px, py)


# ── App setup ──────────────────────────────────────────────────────────────────

ui.init("omni.ui.scene — Translate Manipulator", width=WIN_W, height=WIN_H)

camera = OrbitCamera(aspect=WIN_W / SCENE_H)

win = ui.Window(
    "omni.ui.scene — Translate Manipulator", width=WIN_W, height=WIN_H,
    flags=(
        ui.WINDOW_FLAGS_NO_SCROLLBAR |
        ui.WINDOW_FLAGS_NO_TITLE_BAR |
        ui.WINDOW_FLAGS_NO_RESIZE    |
        ui.WINDOW_FLAGS_NO_MOVE
    ),
    position_x=0, position_y=0,
    fill_app_window=not _SCREENSHOT,
)
win.frame.set_style({"Window": {
    "background_color": BG_DARK, "border_color": 0x0, "border_radius": 0,
}})

with win.frame:
    with ui.VStack(spacing=0):

        # ── header bar ────────────────────────────────────────────────────────
        with ui.ZStack(height=36):
            ui.Rectangle(style={"background_color": BG_MID, "border_width": 0})
            with ui.HStack(height=36):
                ui.Spacer(width=14)
                ui.Label(
                    "omni.ui.scene  ·  XYZ Translate Manipulator",
                    alignment=ui.Alignment.LEFT_CENTER,
                    style={"font_size": 15, "color": C_TEXT},
                )
                ui.Spacer()
                ui.Label(
                    "Left-drag arrows  ·  Right-drag to orbit",
                    alignment=ui.Alignment.RIGHT_CENTER,
                    style={"font_size": 12, "color": C_DIM},
                )
                ui.Spacer(width=14)

        # ── 3D viewport ───────────────────────────────────────────────────────
        scene_view = sc.SceneView(
            camera,
            aspect_ratio_policy=sc.AspectRatioPolicy.PRESERVE_ASPECT_FIT,
            height=SCENE_H,
        )

        with scene_view.scene:
            manipulator = TranslateManipulator()
            manipulator.invalidate()

            # Right-drag anywhere on the viewport to orbit the camera.
            # sc.Screen is a full-viewport hit surface; the DragGesture's
            # mouse_button=1 filter means the arrow DragGestures (button 0)
            # are not affected.
            def _orbit_drag(sender):
                dx, dy = sender.gesture_payload.mouse_moved
                camera.rotate(dx * 20.0, -dy * 20.0)

            _orbit_gesture = sc.DragGesture(on_changed_fn=_orbit_drag)
            _orbit_gesture.mouse_button = 1
            _orbit_gesture.manager = _headless_mgr
            sc.Screen(gesture=_orbit_gesture)

        # ── status bar ────────────────────────────────────────────────────────
        with ui.ZStack(height=28):
            ui.Rectangle(style={"background_color": BG_MID, "border_width": 0})
            with ui.HStack(height=28):
                ui.Spacer(width=14)
                _status = ui.Label(
                    "Position: (+0.00, +0.00, +0.00)"
                    "  ·  Drag an axis arrow to translate  ·  Right-drag to orbit",
                    alignment=ui.Alignment.LEFT_CENTER,
                    style={"font_size": 12, "color": C_DIM},
                )


# ── Main loop / screenshot ─────────────────────────────────────────────────────

async def _main():
    from omni.ui import testing
    global _SCREENSHOT_FAILED

    await testing.wait_frames(12)          # let the scene settle

    if _SCREENSHOT:
        screenshot_ok = True
        _status.text = (
            "Position: (+0.00, +0.00, +0.00)"
            "  |  omni.ui.scene translate manipulator  |  drag arrows to translate"
        )
        await testing.wait_frames(6)

        # ── Initial state screenshot ──────────────────────────────────────────
        out0 = str(_SCRIPT_DIR / "scene_manipulator_screenshot.png")
        os.makedirs(os.path.dirname(out0) or ".", exist_ok=True)
        ok = testing.capture_screenshot(out0)
        if ok:
            print(f"screenshot saved: {out0}")
        else:
            print(f"ERROR: screenshot capture failed: {out0}", file=sys.stderr)
            screenshot_ok = False

        # ── Test X-axis drag: drag from the X-arrow shaft midpoint rightward ─
        # Project the X arrow shaft midpoint (0.95, 0, 0) to screen coords
        # using the exact camera matrices, so we hit within intersection range.
        view_mat = camera.get_as_floats(camera.get_item("view"))
        proj_mat = camera.get_as_floats(camera.get_item("projection"))
        scene_left = 0
        scene_top  = 36  # header height

        # Shaft midpoint of the X arrow
        shaft_mid  = [0.95, 0.0, 0.0]
        # Drag-end target: further along +X
        shaft_end  = [2.80, 0.0, 0.0]

        p0 = _project_world_to_screen(shaft_mid, view_mat, proj_mat,
                                       scene_left, scene_top, WIN_W, SCENE_H)
        p1 = _project_world_to_screen(shaft_end, view_mat, proj_mat,
                                       scene_left, scene_top, WIN_W, SCENE_H)
        if p0 and p1:
            arrow_x0, arrow_y0 = p0
            arrow_x1, arrow_y1 = p1
        else:
            # Fallback
            arrow_x0, arrow_y0 = 500, 315
            arrow_x1, arrow_y1 = 650, 315

        await testing.mouse_drag(arrow_x0, arrow_y0, arrow_x1, arrow_y1,
                                  button=0, steps=15)
        await testing.wait_frames(8)

        p = manipulator._pos
        _status.text = (
            f"Position: ({p[0]:+.2f}, {p[1]:+.2f}, {p[2]:+.2f})"
            f"  |  after X-drag  |  cube moved along +X"
        )
        await testing.wait_frames(4)

        # ── Post-drag screenshot ──────────────────────────────────────────────
        out1 = str(_SCRIPT_DIR / "scene_manipulator_after_drag.png")
        os.makedirs(os.path.dirname(out1) or ".", exist_ok=True)
        ok = testing.capture_screenshot(out1)
        if ok:
            print(f"screenshot saved: {out1}")
        else:
            print(f"ERROR: screenshot capture failed: {out1}", file=sys.stderr)
            screenshot_ok = False
        if not screenshot_ok:
            _SCREENSHOT_FAILED = True
        print(f"cube position after X drag: {manipulator._pos}")
        return

    # Interactive mode — keep the status bar live
    while True:
        await ui.next_frame()
        p = manipulator._pos
        _status.text = (
            f"Position: ({p[0]:+.2f}, {p[1]:+.2f}, {p[2]:+.2f})"
            f"  |  Left-drag an arrow  |  Right-drag to orbit"
        )


ui.run(_main())
if _SCREENSHOT and _SCREENSHOT_FAILED:
    sys.exit(1)
