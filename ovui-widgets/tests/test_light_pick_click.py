# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A real click and the ``viewport_pick`` command with lights in the scene.

The renderer reports geometry only. These tests give it a mesh (or nothing) at
the click. A light that is not selected draws no gizmo, so the mesh stays the
answer. A click on the drawn gizmo of the selected light selects
that light, except that a dome or distant light gizmo leaves the mesh.
"""

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
from ovui_widgets.viewport.inspector import ViewportInspector
from ovui_widgets.viewport.viewport_widget import ViewportWidget
from tests.light_pick_fakes import FakeStage


class _FakeRenderer(MockRendererAdapter):
    """Renderer that answers every pick with one scripted prim path."""

    def __init__(self, pick_path):
        super().__init__()
        self._pick_path = pick_path

    def pick(self, x, y, callback, query_name):
        callback(self._pick_path, (0.0, 0.0, 0.0) if self._pick_path else None)


def translation(x, y, z):
    matrix = np.eye(4)
    matrix[3, :3] = (x, y, z)
    return matrix.tolist()


# The camera looks at the origin, so the click (0, 0) is on the origin. A
# sphere light at (-0.5, 0, 0) and a dome light at (-1, 0, 0) draw a circle
# through the origin; the middle ray of a distant light starts there.
WORLD = {
    "/World/Sky": translation(0, 0, 0),
    "/World/Sun": translation(0, 0, 0),
    "/World/Lamp": translation(-0.5, 0, 0),
    "/World/Dome": translation(-1, 0, 0),
}
TRANSFORM = SimpleNamespace(
    get_world_transform=lambda path: WORLD.get(path, translation(0, 0, 0)),
    can_transform=lambda path: True,
)
LIGHTS = {
    "/World/Sky": "DomeLight",
    "/World/Sun": "DistantLight",
    "/World/Lamp": "SphereLight",
    "/World/Dome": "DomeLight",
}


def make_viewport(pick_path, lights=("/World/Sky", "/World/Sun"), selected=None):
    stage = FakeStage()
    for path in lights:
        stage.add(path, LIGHTS[path])
    for name in ("Pillar", "OriginCube"):
        stage.add(f"/World/{name}", "Mesh")
    bus = SelectionBus()
    bus.publish(["/World/Old"], source="init")
    viewport = ViewportWidget(
        services=None,
        renderer=_FakeRenderer(pick_path),
        bus=bus,
        stage_adapter_provider=lambda: stage,
    )
    viewport._transform_model._transform = TRANSFORM
    viewport._camera.state.target = [0.0, 0.0, 0.0]
    viewport._camera.state.distance = 10.0
    if selected is not None:
        # The Stage Browser selects; the viewport then draws the light gizmo.
        bus.publish([selected], source="stage")
    return viewport, stage, bus


def selected(bus):
    return bus.get_snapshot().paths()


@pytest.mark.parametrize(
    "mode,expected",
    [("replace", ["/World/OriginCube"]), ("add", ["/World/Old", "/World/OriginCube"])],
)
def test_click_on_a_mesh_at_the_origin_selects_it_while_the_lights_are_unselected(mode, expected):
    viewport, _, bus = make_viewport("/World/OriginCube")
    viewport._on_pick(0.0, 0.0, mode)
    assert selected(bus) == expected
    viewport.destroy()


def test_click_on_empty_background_at_unselected_lights_clears_the_selection():
    viewport, _, bus = make_viewport(None)
    viewport._on_pick(0.0, 0.0, "replace")
    assert selected(bus) == []
    viewport.destroy()


def test_click_on_the_drawn_gizmo_of_the_selected_light_keeps_the_light():
    for pick_path in ("/World/Pillar", None):
        viewport, _, bus = make_viewport(pick_path, lights=("/World/Lamp",), selected="/World/Lamp")
        viewport._on_pick(0.0, 0.0, "replace")
        assert selected(bus) == ["/World/Lamp"]
        viewport.destroy()


@pytest.mark.parametrize("light", ["/World/Dome", "/World/Sun"])
def test_click_on_a_drawn_dome_or_distant_gizmo_over_a_mesh_selects_the_mesh(light):
    viewport, _, bus = make_viewport("/World/OriginCube", lights=(light,), selected=light)
    viewport._on_pick(0.0, 0.0, "replace")
    assert selected(bus) == ["/World/OriginCube"]
    viewport.destroy()
    viewport, _, bus = make_viewport(None, lights=(light,), selected=light)
    viewport._on_pick(0.0, 0.0, "replace")
    assert selected(bus) == [light]
    viewport.destroy()


def test_click_away_from_the_selected_light_keeps_the_mesh_and_the_deselect():
    viewport, _, bus = make_viewport("/World/Pillar", lights=("/World/Lamp",), selected="/World/Lamp")
    viewport._on_pick(0.9, 0.9, "replace")
    assert selected(bus) == ["/World/Pillar"]
    viewport.destroy()
    viewport, _, bus = make_viewport(None, lights=("/World/Lamp",), selected="/World/Lamp")
    viewport._on_pick(0.9, 0.9, "replace")
    assert selected(bus) == []
    viewport.destroy()


def test_click_on_a_hidden_selected_light_selects_the_mesh_in_front():
    viewport, stage, bus = make_viewport("/World/Pillar", lights=("/World/Lamp",), selected="/World/Lamp")
    stage.hidden.add("/World/Lamp")
    viewport._on_pick(0.0, 0.0, "replace")
    assert selected(bus) == ["/World/Pillar"]
    viewport.destroy()


def _fail(message):
    def read(*args, **kwargs):
        raise RuntimeError(message)

    return read


@pytest.mark.parametrize(
    "owner,reader",
    [
        ("stage", "get_light_shape_attributes"),
        ("stage", "read_stage_meters_per_unit"),
        ("stage", "get_icon_name"),
        ("stage", "compute_visibility"),
        ("transforms", "get_world_transform"),
    ],
)
def test_failed_read_of_the_selected_light_is_reported_and_keeps_the_mesh(owner, reader, capsys):
    # The drawing gives the default gizmo when a size or units read fails, and
    # the click is on that gizmo. The pick must not use it: it reports the
    # cause and keeps the renderer hit.
    viewport, stage, bus = make_viewport("/World/Pillar", lights=("/World/Lamp",), selected="/World/Lamp")
    target = stage
    if owner == "transforms":
        target = SimpleNamespace(**vars(TRANSFORM))
        viewport._transform_model._transform = target
    setattr(target, reader, _fail(f"{reader} is unreadable"))
    viewport._on_pick(0.0, 0.0, "replace")
    assert selected(bus) == ["/World/Pillar"]
    err = capsys.readouterr().err
    assert "Light pick: reading the selected light /World/Lamp failed" in err
    assert f"RuntimeError: {reader} is unreadable" in err
    viewport.destroy()


def test_click_on_the_app_fallback_dome_gizmo_is_not_a_light_pick():
    viewport, stage, bus = make_viewport(None, lights=())
    stage.add("/OvGearSession", "Scope")
    stage.add("/OvGearSession/Lights", "Scope", parent="/OvGearSession")
    stage.add("/OvGearSession/Lights/FallbackDome", "DomeLight", parent="/OvGearSession/Lights")
    WORLD["/OvGearSession/Lights/FallbackDome"] = translation(-1, 0, 0)
    try:
        bus.publish(["/OvGearSession/Lights/FallbackDome"], source="stage")
        viewport._on_pick(0.0, 0.0, "replace")
        assert selected(bus) == []
    finally:
        del WORLD["/OvGearSession/Lights/FallbackDome"]
        viewport.destroy()


def inspector_pick(pick_path, **viewport_options):
    viewport, stage, bus = make_viewport(pick_path, **viewport_options)
    viewport._image = SimpleNamespace(
        screen_position_x=100, screen_position_y=50, computed_width=400, computed_height=200
    )
    api = ViewportInspector(lambda: {"primary": viewport}, lambda: bus)
    result = asyncio.run(api.pick(300, 150))
    viewport.destroy()
    return result, selected(bus)


def test_viewport_pick_command_keeps_the_mesh_under_unselected_lights():
    result, paths = inspector_pick("/World/OriginCube")
    assert paths == ["/World/OriginCube"]
    assert result["hit"]["path"] == "/World/OriginCube"


def test_viewport_pick_command_selects_the_drawn_light_gizmo():
    result, paths = inspector_pick("/World/Pillar", lights=("/World/Lamp",), selected="/World/Lamp")
    assert paths == ["/World/Lamp"]
    assert result["hit"]["path"] == "/World/Lamp"
