# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A click on the drawn gizmo of the selected UsdLux light selects that light.

A light that is not selected draws no gizmo, so it never takes a click from the
mesh or the empty background under it.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from tests.light_pick_fakes import FakeStage
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.viewport.camera_controller import CameraController
from ovui_widgets.viewport.light_manipulator import SUPPORTED_LIGHT_TYPES
from ovui_widgets.viewport.light_pick import pick_light_path
from ovui_widgets.viewport.viewport_widget import ViewportSurface

SIZE = (730, 376)


def translation(x, y, z):
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, z, 1]


def report(path, exc):
    raise AssertionError(f"unexpected failure for {path}: {exc}")


def camera_matrices(projection_mode="perspective"):
    camera = CameraController()
    camera.projection_mode = projection_mode
    camera.state.target = [0.0, 0.0, 0.0]
    camera.state.distance = 10.0
    camera.state.azimuth = 0.0
    camera.state.elevation = 0.0
    return camera.get_matrices(*SIZE)


def to_ndc(point, view, projection):
    clip = projection @ view @ np.array([*point, 1.0])
    return (clip[0] / clip[3], clip[1] / clip[3])


def camera_from_above(azimuth=0.7, elevation=0.6):
    """A view from which no circle of a gizmo at the origin is seen edge-on."""
    camera = CameraController()
    camera.state.target = [0.0, 0.0, 0.0]
    camera.state.distance = 10.0
    camera.state.azimuth = azimuth
    camera.state.elevation = elevation
    return camera.get_matrices(*SIZE)


# One point on a drawn line of each gizmo, with the default dimensions.
DRAWN_POINT = {
    "CylinderLight": (0.5, 0.0, 0.0),  # a side line of the cylinder
    "DiskLight": (0.5, 0.0, 0.0),  # the disk circle
    "DistantLight": (0.0, 0.0, 0.0),  # the start of the middle ray
    "DomeLight": (1.0, 0.0, 0.0),  # a dome circle
    "RectLight": (0.5, 0.0, 0.0),  # the right edge of the rectangle
    "SphereLight": (0.5, 0.0, 0.0),  # a sphere circle
}


@pytest.mark.parametrize("light_type", sorted(SUPPORTED_LIGHT_TYPES))
def test_click_on_a_drawn_line_picks_the_light(light_type):
    view, projection = camera_from_above()
    light = ("/World/Light", light_type, {}, translation(0, 0, 0))
    ndc = to_ndc(DRAWN_POINT[light_type], view, projection)
    assert pick_light_path([light], view, projection, ndc, SIZE, report) == "/World/Light"


@pytest.mark.parametrize(
    "light_type,attributes", [("DomeLight", {}), ("SphereLight", {"radius": 1.0})]
)
def test_click_inside_a_gizmo_where_no_line_is_drawn_is_not_a_pick(light_type, attributes):
    # The light origin is about 22 px from the nearest drawn line here.
    view, projection = camera_from_above()
    light = ("/World/Light", light_type, attributes, translation(0, 0, 0))
    origin = to_ndc((0.0, 0.0, 0.0), view, projection)
    assert pick_light_path([light], view, projection, origin, SIZE, report) is None


def test_dome_outline_is_picked_and_background_is_not():
    view, projection = camera_matrices()
    light = ("/World/DomeLight", "DomeLight", {}, translation(0, 0, 0))
    on_outline = to_ndc((1.0, 0, 0), view, projection)
    assert pick_light_path([light], view, projection, on_outline, SIZE, report) == "/World/DomeLight"
    for background in ((0.9, 0.9), (-0.9, -0.5), (0.0, 0.8)):
        assert pick_light_path([light], view, projection, background, SIZE, report) is None


def test_light_behind_camera_is_not_picked():
    view, projection = camera_matrices()
    light = ("/World/Light", "SphereLight", {}, translation(0, 0, 40))
    assert pick_light_path([light], view, projection, (0.0, 0.0), SIZE, report) is None


def test_orthographic_light_behind_camera_is_not_picked():
    # The camera sits at z=10 and looks down -Z. Orthographic w stays 1, so
    # only the depth range can tell that z=20 is behind the camera.
    view, projection = camera_matrices("orthographic")
    behind = ("/World/Behind", "SphereLight", {}, translation(0, 0, 20))
    assert pick_light_path([behind], view, projection, (0.0, 0.0), SIZE, report) is None
    in_front = ("/World/Front", "SphereLight", {}, translation(0, 0, 0))
    assert pick_light_path([in_front], view, projection, (0.0, 0.0), SIZE, report) == "/World/Front"


def test_nearest_of_two_overlapping_lights_wins():
    # The click is on a circle of B. The same circle of A passes about 4 px
    # away, also within reach of the click.
    view, projection = camera_from_above()
    lights = [
        ("/World/A", "SphereLight", {}, translation(0, 0, 0)),
        ("/World/B", "SphereLight", {}, translation(0.1, 0, 0)),
    ]
    ndc = to_ndc((0.6, 0, 0), view, projection)
    assert pick_light_path(lights[:1], view, projection, ndc, SIZE, report) == "/World/A"
    assert pick_light_path(lights, view, projection, ndc, SIZE, report) == "/World/B"


def dome_and_sphere_in_front(offset_px):
    """A click on the edge-on circle of a dome at the origin, and a sphere
    light in front of the dome whose own edge-on circle is ``offset_px`` away."""
    view, projection = camera_matrices()
    # The camera is at z=10, so the sphere at z=2.5 is 7.5 in front of it.
    shift = offset_px / (SIZE[0] / 2) * 7.5 / projection[0][0]
    lights = [
        ("/World/DomeLight", "DomeLight", {}, translation(0, 0, 0)),
        ("/World/SphereLight", "SphereLight", {}, translation(shift, 0, 2.5)),
    ]
    click = (0.0, to_ndc((shift, 0.25, 2.5), view, projection)[1])
    return lights, view, projection, click


def test_equally_near_outlines_pick_the_light_in_front():
    lights, view, projection, click = dome_and_sphere_in_front(0.4)
    assert pick_light_path(lights, view, projection, click, SIZE, report) == "/World/SphereLight"
    lights, view, projection, click = dome_and_sphere_in_front(3.0)
    assert pick_light_path(lights, view, projection, click, SIZE, report) == "/World/DomeLight"


IDENTITY = translation(0, 0, 0)


def make_surface(light_types, selected=(), world_matrix=IDENTITY):
    """A viewport surface whose camera looks at the origin from 10 units."""
    adapter = FakeStage(light_types)
    surface = ViewportSurface.__new__(ViewportSurface)
    surface._stage_adapter_provider = lambda: adapter
    surface._bus = SelectionBus()
    # Like ``PrimTransformModel``: the world matrix of the first selected prim.
    surface._transform_model = SimpleNamespace(
        get_first_world_transform=lambda raise_errors=False: world_matrix,
    )
    surface._renderer = None
    surface._camera = CameraController()
    surface._camera.state.target = [0.0, 0.0, 0.0]
    surface._camera.state.distance = 10.0
    surface._interaction_frame_and_render_size = lambda: (SIZE, SIZE)
    select(surface, *selected)
    return surface


def select(surface, *paths):
    """Select as the Stage Browser does; the viewport then draws the gizmo."""
    surface._bus.publish(list(paths), source="stage")
    surface._selected_light_type_cache = None


def on_drawn_line(surface, point):
    view, projection = surface._camera.get_matrices(*SIZE)
    return to_ndc(point, view, projection)


def test_unselected_lights_at_the_origin_do_not_take_the_click():
    # The scene of the report: a dome and a distant light at the origin, no
    # light selected, so no gizmo is drawn.
    # The origin is at the centre of the view; (1, 0, 0) is on a dome circle.
    surface = make_surface(["DomeLight", "DistantLight"])
    for click in ((0.0, 0.0), on_drawn_line(surface, (1.0, 0.0, 0.0))):
        assert surface.resolve_pick_path(*click, "/World/OriginCube") == "/World/OriginCube"
        assert surface.resolve_pick_path(*click, None) is None


def test_drawn_gizmo_of_the_selected_light_is_picked_over_a_mesh_and_the_background():
    surface = make_surface(["SphereLight"], selected=["/World/L0"])
    click = on_drawn_line(surface, (0.5, 0.0, 0.0))
    assert surface.resolve_pick_path(*click, "/World/Pillar") == "/World/L0"
    assert surface.resolve_pick_path(*click, None) == "/World/L0"


@pytest.mark.parametrize("light_type,point", [("DomeLight", (1.0, 0.0, 0.0)), ("DistantLight", (0.0, 0.0, 0.0))])
def test_drawn_dome_or_distant_gizmo_keeps_the_mesh_under_the_click(light_type, point):
    surface = make_surface([light_type], selected=["/World/L0"])
    click = on_drawn_line(surface, point)
    assert surface.resolve_pick_path(*click, "/World/OriginCube") == "/World/OriginCube"
    assert surface.resolve_pick_path(*click, None) == "/World/L0"


def test_click_away_from_the_selected_light_keeps_the_renderer_hit():
    surface = make_surface(["SphereLight"], selected=["/World/L0"])
    assert surface.resolve_pick_path(0.9, 0.9, None) is None
    assert surface.resolve_pick_path(0.9, 0.9, "/World/Cube") == "/World/Cube"


def test_no_gizmo_is_picked_unless_one_light_alone_is_selected():
    surface = make_surface(["SphereLight", "SphereLight"])
    click = on_drawn_line(surface, (0.5, 0.0, 0.0))
    surface._get_stage_adapter().add("/World/Cube", "Mesh")
    for selection in ([], ["/World/L0", "/World/L1"], ["/World/L0", "/World/Cube"], ["/World/Cube"]):
        select(surface, *selection)
        assert surface.resolve_pick_path(*click, "/World/Pillar") == "/World/Pillar"
    select(surface, "/World/L1")
    assert surface.resolve_pick_path(*click, "/World/Pillar") == "/World/L1"


def test_selected_light_without_a_world_matrix_draws_no_gizmo_and_is_not_picked():
    surface = make_surface(["SphereLight"], selected=["/World/L0"], world_matrix=None)
    click = on_drawn_line(surface, (0.5, 0.0, 0.0))
    assert surface.resolve_pick_path(*click, "/World/Pillar") == "/World/Pillar"


def test_hidden_selected_light_is_not_picked_and_a_shown_light_is_again():
    surface = make_surface(["SphereLight"], selected=["/World/L0"])
    adapter = surface._get_stage_adapter()
    click = on_drawn_line(surface, (0.5, 0.0, 0.0))
    adapter.hidden.add("/World/L0")
    assert surface.resolve_pick_path(*click, "/World/Sphere") == "/World/Sphere"
    assert surface.resolve_pick_path(*click, None) is None
    adapter.hidden.discard("/World/L0")
    assert surface.resolve_pick_path(*click, "/World/Sphere") == "/World/L0"


def test_selected_light_under_a_hidden_parent_is_not_picked():
    surface = make_surface([])
    adapter = surface._get_stage_adapter()
    adapter.add("/World/Group", "Xform")
    adapter.add("/World/Group/Lamp", "SphereLight", parent="/World/Group")
    select(surface, "/World/Group/Lamp")
    click = on_drawn_line(surface, (0.5, 0.0, 0.0))
    adapter.hidden.add("/World/Group")
    assert surface.resolve_pick_path(*click, "/World/Cube") == "/World/Cube"
    adapter.hidden.clear()
    assert surface.resolve_pick_path(*click, "/World/Cube") == "/World/Group/Lamp"


def test_selected_app_session_light_is_not_picked():
    surface = make_surface([])
    adapter = surface._get_stage_adapter()
    adapter.add("/OvGearSession", "Scope")
    adapter.add("/OvGearSession/Lights", "Scope", parent="/OvGearSession")
    adapter.add("/OvGearSession/Lights/FallbackDome", "DomeLight", parent="/OvGearSession/Lights")
    select(surface, "/OvGearSession/Lights/FallbackDome")
    assert surface.resolve_pick_path(*on_drawn_line(surface, (1.0, 0.0, 0.0)), None) is None
