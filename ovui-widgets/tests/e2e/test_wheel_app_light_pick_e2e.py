# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Viewport clicks near the scene origin with a dome light and a distant light.

OMPE-118428: in 0.3.1rc1, a click on a visible mesh at or near the
world origin selected the DomeLight or the DistantLight of the scene. Neither
light was selected, so the viewport drew no gizmo for it. 0.3.0rc26 selected
the meshes.

The installed windowed USD Viewer (real ovrtx renderer) is driven only with
injected mouse input through the ovui inspector, once per data provider. Each
test starts its own app at 1000x720 and closes the Content browser with the
mouse (it lists the home folder of the machine). After each step it parks the
cursor, waits for a stable frame and compares the whole window with the
reference image of that step, ``golden/light_pick_<step>_<provider>.png``, with
the compare of the other window tests (``driver.py``). Three steps have one
reference image per platform, ``golden/light_pick_<step>_<provider>_<platform>.png``
(see ``PER_PLATFORM_REFERENCES``). A missing
reference image fails. ``OMNI_UI_GENERATE_GOLDEN=1`` writes the reference
images instead.

1. ``test_clicks_near_the_origin_select_the_meshes``: no light is selected.
   Click empty background, the cube at the origin, empty background, and the
   small cube at (0.6, 1.4, 0.6). Each cube click selects that cube and each
   background click leaves nothing selected: the 0.3.0rc26 results.
2. ``test_click_on_the_drawn_light_gizmo_keeps_the_light``: select the sphere
   light in the Stage Browser, so the viewport draws its gizmo. A click on a
   drawn pixel of the gizmo is a viewport pick that keeps the light selected.

Release comparison: install the wheels of a release and run this file. Test 1
passes on 0.3.0rc26 and fails on 0.3.1rc1. Test 2 needs the light gizmo pick
that 0.3.1rc1 added.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest


def _load_by_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_HERE = Path(__file__).resolve().parent
driver = _load_by_path("ovui_e2e_driver_light_pick", _HERE / "driver.py")
field_delete = _load_by_path(
    "ovui_e2e_field_delete_helpers_light_pick", _HERE / "test_wheel_app_field_delete_e2e.py"
)
pytestmark = pytest.mark.requires_ovrtx

ORIGIN_CUBE = "/World/OriginCube"
SMALL_CUBE = "/World/SmallCube"
LAMP = "/World/Lamp"

# The lights of the report, at the origin, and the cubes of the report. The
# sphere light is away from the cubes; the side cube below it keeps it in the
# framed view. Its large radius puts most of its gizmo clear of the move
# gizmo that the viewport draws at the selected light.
SCENE = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 1
    upAxis = "Y"
)

def Xform "World"
{
    def DomeLight "Sky"
    {
        float inputs:intensity = 1000
    }

    def DistantLight "Sun"
    {
        float inputs:intensity = 3000
        float3 xformOp:rotateXYZ = (-45, 30, 0)
        uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
    }

    def Cube "OriginCube"
    {
        color3f[] primvars:displayColor = [(0.8, 0.3, 0.2)]
        double size = 1
    }

    def Cube "SmallCube"
    {
        color3f[] primvars:displayColor = [(0.2, 0.7, 0.3)]
        double size = 0.3
        double3 xformOp:translate = (0.6, 1.4, 0.6)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }

    def Cube "SideCube"
    {
        color3f[] primvars:displayColor = [(0.3, 0.4, 0.8)]
        double size = 0.6
        double3 xformOp:translate = (-2.2, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }

    def SphereLight "Lamp"
    {
        float inputs:intensity = 20000
        float inputs:radius = 1.5
        double3 xformOp:translate = (-2.2, 1.0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
}
"""

# A point of the viewport image, as a fraction of its size, with only the
# empty background under it in both providers' framed views.
BACKGROUND = (0.92, 0.9)
# The cursor waits here, in the empty bottom-right corner of the window, while
# a step is captured, so no hover state is in the reference image.
PARK = (driver.APP_WINDOW_SIZE[0] - 4, driver.APP_WINDOW_SIZE[1] - 4)
# These steps have one reference image per platform. With the Lamp selected,
# Linux draws the light gizmo lines with OpenGL, thicker than the default
# SceneView of Windows (48-59 changed render pixels, the limit is 40), and the
# OpenUSD of conda-forge on Linux ARM64 lists more light properties in the
# Property Inspector. With the small cube selected, the move gizmo touches the
# right edge of the viewport, and Windows draws it 2 px past that edge (16
# changed UI pixels, the limit is 10). The other steps match on every platform.
PER_PLATFORM_REFERENCES = frozenset({"small_cube", "lamp_selected", "lamp_gizmo_click"})
# The light gizmo color (LIGHT_GIZMO_COLOR 0xFF54CEFF is RGB 255, 206, 84) and
# the largest channel difference of a drawn gizmo pixel in a screenshot.
GIZMO_RGB = (255, 206, 84)
GIZMO_RGB_TOLERANCE = 6
# A pixel that differs by at most this from a mix of the gizmo and the
# background color is the anti-aliased edge of a gizmo line.
GIZMO_EDGE_TOLERANCE = 12.0
# The clicked gizmo pixel is at least this far from anything else drawn, so
# the move gizmo cannot take the press.
GIZMO_CLEARANCE_PX = 12.0
PICK_TIMEOUT = 20.0


class _Viewer:
    def __init__(self, session, workdir: Path, provider: str):
        self.session = session
        self.workdir = workdir
        self.provider = provider
        self.step = 0

    def image_rect(self) -> dict:
        return self.session.state()["viewport"]["image_rect"]

    def check(self, name: str, reference: str) -> Path:
        """Capture a stable frame and compare it with its reference image.

        Steps that must look the same share one ``reference``.
        """
        self.step += 1
        self.session.move(*PARK)
        rect = self.image_rect()
        frame = self.workdir / f"{self.step:02d}_{name}.png"
        self.session.wait_stable(frame, rect)
        diffs = self.workdir / f"{self.step:02d}_{name}_compare"
        diffs.mkdir()
        key = f"{reference}_{self.provider}"
        if reference in PER_PLATFORM_REFERENCES:
            key += f"_{driver.platform_key()}"
        driver._compare_or_generate(
            frame, rect, driver.golden_dir() / f"light_pick_{key}.png", diffs, f"light-pick/{key}"
        )
        return frame

    def background_point(self) -> tuple:
        rect = self.image_rect()
        return (
            int(rect["x"] + BACKGROUND[0] * rect["width"]),
            int(rect["y"] + BACKGROUND[1] * rect["height"]),
        )

    def prim_center(self, path: str) -> tuple:
        centers = self.session.state()["viewport"]["prim_screen_centers"]
        assert path in centers, f"{path} is not in the viewport: {sorted(centers)}"
        return tuple(centers[path])

    def click(self, point: tuple, expected: list, where: str) -> dict:
        """Click and wait for the renderer pick of this click; return the selection.

        A click that must change nothing also waits for its own pick, so a late
        wrong selection cannot pass. The OVStage renderer can give the pick
        result to the UI one frame after it counts it, so the result must hold
        in two state reads in a row.
        """
        picks = self.session.state()["renderer"].get("pick_result_count", 0)
        self.session.click(*point)
        deadline = time.monotonic() + PICK_TIMEOUT
        held = 0
        while True:
            state = self.session.state()
            renderer = state.get("renderer", {})
            selection = state.get("selection", {})
            done = (
                renderer.get("pick_result_count", 0) > picks
                and not renderer.get("in_flight_pick_count", 0)
            )
            held = held + 1 if done and selection.get("paths") == expected else 0
            if held >= 2 or time.monotonic() > deadline:
                break
            time.sleep(0.5)
        assert held >= 2, (
            f"[{self.provider}] {where} at {point}: the selection is "
            f"{selection.get('paths')}, expected {expected} (pick finished: {done}, "
            f"sources {selection.get('sources')}, renderer pick "
            f"{selection.get('renderer_last_pick')!r}).\n--- app log ---\n"
            f"{self.session.log_tail()}"
        )
        return selection


@pytest.fixture(scope="module")
def renderer_and_display():
    """Probe the renderer once for this file: the probe starts ovrtx in a new process."""
    field_delete._require_renderer_and_display()


@pytest.fixture(params=driver.WINDOW_PROVIDERS)
def viewer(request, tmp_path, renderer_and_display):
    """A new app per test, so every step starts from the same window."""
    provider = request.param
    driver.assert_installed_provenance(
        driver.OVSTAGE_PRODUCT_MODULES if provider == "ovstage" else driver.PRODUCT_MODULES
    )
    scene = tmp_path / "origin_lights.usda"
    scene.write_text(SCENE)
    session = driver.FullAppSession(
        workdir=tmp_path, log_path=tmp_path / "app.log", provider=provider,
        headless=False, scene=scene,
    )
    session.start()
    try:
        # The first frames still show the Content browser, which lists the home
        # folder of the machine; they have no reference image.
        state = driver._start_and_check(session, tmp_path / "_with_content.png")
        driver.close_content_browser(
            session, state, tmp_path / "_window_menu_open.png", tmp_path / "_content_closed.png"
        )
        viewer = _Viewer(session, tmp_path, provider)
        viewer.check("start", "start")
        yield viewer
    finally:
        session.stop()


def test_clicks_near_the_origin_select_the_meshes(viewer):
    viewer.click(viewer.background_point(), [], "background click, no light selected")
    viewer.check("background_no_light_selected", "start")
    viewer.click(viewer.prim_center(ORIGIN_CUBE), [ORIGIN_CUBE], "origin cube click")
    viewer.check("origin_cube", "origin_cube")
    viewer.click(viewer.background_point(), [], "background click")
    viewer.check("background", "cleared")
    viewer.click(viewer.prim_center(SMALL_CUBE), [SMALL_CUBE], "small cube click")
    viewer.check("small_cube", "small_cube")


def _drawn_gizmo_point(frame: Path, rect: dict) -> tuple:
    """The drawn light gizmo pixel farthest from anything else drawn.

    The move gizmo handles of the selected light take a press as a drag, so
    the click goes to a gizmo pixel with only the background around it.
    """
    import numpy as np
    from PIL import Image

    rgb = np.asarray(Image.open(frame).convert("RGB")).astype(float)
    x0, y0 = int(rect["x"]), int(rect["y"])
    view = rgb[y0:y0 + int(rect["height"]), x0:x0 + int(rect["width"])]
    colors, counts = np.unique(view.reshape(-1, 3), axis=0, return_counts=True)
    background = colors[np.argmax(counts)]
    gizmo_rgb = np.array(GIZMO_RGB, dtype=float)
    gizmo = np.all(np.abs(view - gizmo_rgb) <= GIZMO_RGB_TOLERANCE, axis=-1)
    direction = gizmo_rgb - background
    mix = np.clip(((view - background) @ direction) / (direction @ direction), 0.0, 1.0)
    edge = np.linalg.norm(view - (background + mix[..., None] * direction), axis=-1)
    other = ~gizmo & (edge > GIZMO_EDGE_TOLERANCE)
    gy, gx = np.nonzero(gizmo)
    oy, ox = np.nonzero(other)
    assert gx.size, f"no drawn light gizmo pixel in the viewport of {frame}"
    if not ox.size:
        return x0 + int(gx[0]), y0 + int(gy[0])
    clearance = np.min(np.hypot(gx[:, None] - ox[None, :], gy[:, None] - oy[None, :]), axis=1)
    best = int(np.argmax(clearance))
    assert clearance[best] >= GIZMO_CLEARANCE_PX, (
        f"every drawn light gizmo pixel of {frame} is within {clearance[best]:.1f} px "
        "of something else drawn"
    )
    return x0 + int(gx[best]), y0 + int(gy[best])


def _show_stage_row(viewer, path: str) -> dict:
    """Open the closed Stage Browser rows above ``path`` with their chevrons.

    On a slow runner the state can still show a row closed just after the
    click on its chevron, and a second click would close it again. So after
    each click the rows are read again until that row is open.
    """
    rows = viewer.session.state()["stage_ui"]["rows"]
    for _ in range(path.count("/") + 1):
        row = next((row for row in rows if row["path"] == path), None)
        if row is not None:
            return row
        closed = [
            row for row in rows
            if path.startswith(row["path"].rstrip("/") + "/") and not row["expanded"]
        ]
        assert closed, f"no closed Stage Browser row above {path}: {rows}"
        parent = max(closed, key=lambda row: len(row["path"]))
        viewer.session.click(*parent["chevron_point"])
        deadline = time.monotonic() + PICK_TIMEOUT
        while True:
            rows = viewer.session.state()["stage_ui"]["rows"]
            opened = any(row["path"] == parent["path"] and row["expanded"] for row in rows)
            if opened or time.monotonic() > deadline:
                break
            time.sleep(0.5)
        assert opened, (
            f"the Stage Browser row {parent['path']} is still closed "
            f"{PICK_TIMEOUT:.0f} s after the click on its chevron: {rows}"
        )
    raise AssertionError(f"the Stage Browser shows no {path} row: {rows}")


def test_click_on_the_drawn_light_gizmo_keeps_the_light(viewer):
    lamp_row = _show_stage_row(viewer, LAMP)
    viewer.session.click(*lamp_row["select_point"])
    deadline = time.monotonic() + PICK_TIMEOUT
    while True:
        selection = viewer.session.state().get("selection", {})
        if selection.get("paths") == [LAMP] or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    assert selection.get("paths") == [LAMP], (
        f"[{viewer.provider}] after the Stage Browser click on the Lamp row the "
        f"selection is {selection.get('paths')}"
    )
    assert "viewport" not in selection.get("sources", []), selection
    frame = viewer.check("lamp_selected_in_stage_browser", "lamp_selected")
    point = _drawn_gizmo_point(frame, viewer.image_rect())
    selection = viewer.click(point, [LAMP], "click on the drawn Lamp gizmo")
    # The pick republishes the selection with the viewport as its source.
    assert selection.get("sources") == ["viewport"], (
        f"[{viewer.provider}] a click on the drawn Lamp gizmo at {point} gave the "
        f"selection {selection.get('paths')} from {selection.get('sources')}, expected "
        f"[{LAMP}] from the viewport.\n--- app log ---\n{viewer.session.log_tail()}"
    )
    # The Layers panel shows the selected prim spec after a viewport pick, so
    # this window differs from the one after the Stage Browser click.
    viewer.check("click_on_drawn_lamp_gizmo", "lamp_gizmo_click")
