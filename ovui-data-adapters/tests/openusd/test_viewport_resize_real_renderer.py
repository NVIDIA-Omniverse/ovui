# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A viewport size change gives the render product a new resolution, and nothing more.

A window resize (a drag of the window border, a maximize) asks for a new viewport
size on many frames. Before, each new size removed the ovrtx session layer and
added it again, and wrote the render product with its camera and render var to the
session layer of the stage. The first ovrtx step at the new size then ran on the UI
thread on the same frame, also on the first frame after a maximize, so the new
window area stayed black during that step.

Now only the resolution changes, in ovrtx and in the session layer, and only after
the size settled; then the rendering history of the renderer is cleared, so that the
picture at the new size is the picture of a fresh render at that size. Each test runs
in a process of its own with the real renderer.
"""

from __future__ import annotations

import numpy as np
import pytest
from pxr import Gf, Usd, UsdGeom, UsdLux, UsdRender

pytestmark = [pytest.mark.requires_ovrtx, pytest.mark.own_process]

_PRODUCT = "/OvGearSession/Render/Viewport"
# The viewport's matrix layout: the camera 5 units in front of the cube, looking at it.
_VIEW = np.identity(4)
_VIEW[2, 3] = -5.0
_PROJECTION = np.array(
    [[1.45, 0.0, 0.0, 0.0], [0.0, 2.41, 0.0, 0.0], [0.0, 0.0, -1.000002, -0.02], [0.0, 0.0, -1.0, 0.0]]
)


class _RecordingRenderer:
    """The real ovrtx renderer; records session layer removals, additions and resolution writes.

    ``refuse_resolution`` refuses each resolution write, ``refuse_reset`` refuses
    each renderer reset, and ``failed_additions`` session layer additions fail
    first, as a failing renderer does.
    """

    def __init__(
        self,
        renderer,
        refuse_resolution: bool = False,
        failed_additions: int = 0,
        refuse_reset: bool = False,
    ):
        self._renderer = renderer
        self._refuse_resolution = refuse_resolution
        self._refuse_reset = refuse_reset
        self._failed_additions = failed_additions
        self.removals = 0
        self.additions = 0
        self.resolution_writes = []

    def remove_usd(self, *args, **kwargs):
        self.removals += 1
        return self._renderer.remove_usd(*args, **kwargs)

    def add_usd_reference_from_string(self, *args, **kwargs):
        if self._failed_additions:
            self._failed_additions -= 1
            raise RuntimeError("session layer refused")
        self.additions += 1
        return self._renderer.add_usd_reference_from_string(*args, **kwargs)

    def write_attribute(self, *args, **kwargs):
        if kwargs.get("attribute_name") == "resolution":
            self.resolution_writes.append(tuple(np.asarray(kwargs["tensor"]).reshape(-1).tolist()))
            if self._refuse_resolution:
                raise RuntimeError("resolution write refused")
        return self._renderer.write_attribute(*args, **kwargs)

    def reset(self, *args, **kwargs):
        if self._refuse_reset:
            raise RuntimeError("reset refused")
        return self._renderer.reset(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._renderer, name)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _start(
    refuse_resolution: bool = False,
    failed_additions: int = 0,
    refuse_reset: bool = False,
    stage=None,
    first_size=(160, 96),
):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    if stage is None:
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Cube.Define(stage, "/World/Cube")
    adapter = OvRtxRendererAdapter()
    clock = _Clock()
    adapter._clock = clock
    try:
        adapter.load_stage(stage)
        width, height = first_size
        assert adapter.render_frame(width, height, _VIEW, _PROJECTION).shape == (height, width, 4)
        recording = _RecordingRenderer(
            adapter._renderer, refuse_resolution, failed_additions, refuse_reset
        )
        adapter._renderer = recording
    except BaseException:
        adapter.shutdown()
        raise
    return adapter, recording, stage, clock


def _scene_with_edges():
    """Lit boxes at several depths, a sphere and a floor: many edges, where a smeared picture shows."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    places = [(-1.5, -0.8), (0.0, 0.6), (1.5, -0.4), (-0.6, 1.2), (0.9, 1.4)]
    for index, (x, y) in enumerate(places):
        cube = UsdGeom.Cube.Define(stage, f"/World/Cube{index}")
        cube.CreateSizeAttr(0.7)
        UsdGeom.XformCommonAPI(cube).SetTranslate(Gf.Vec3d(x, y, -0.5 * index))
        UsdGeom.XformCommonAPI(cube).SetRotate(Gf.Vec3f(20.0 * index, 35.0, 10.0 * index))
        cube.CreateDisplayColorAttr([Gf.Vec3f(0.2 + 0.15 * index, 0.8 - 0.12 * index, 0.4)])
    sphere = UsdGeom.Sphere.Define(stage, "/World/Sphere")
    sphere.CreateRadiusAttr(0.6)
    UsdGeom.XformCommonAPI(sphere).SetTranslate(Gf.Vec3d(0.4, -1.1, 0.3))
    floor = UsdGeom.Cube.Define(stage, "/World/Floor")
    floor.CreateSizeAttr(1.0)
    UsdGeom.XformCommonAPI(floor).SetTranslate(Gf.Vec3d(0.0, -2.0, -1.0))
    UsdGeom.XformCommonAPI(floor).SetScale(Gf.Vec3f(12.0, 0.2, 12.0))
    UsdLux.DomeLight.Define(stage, "/World/Dome").CreateIntensityAttr(800.0)
    sun = UsdLux.DistantLight.Define(stage, "/World/Sun")
    sun.CreateIntensityAttr(3000.0)
    UsdGeom.XformCommonAPI(sun).SetRotate(Gf.Vec3f(-40.0, 30.0, 0.0))
    return stage


def _stop(adapter, recording) -> None:
    adapter._renderer = recording._renderer
    adapter.shutdown()


def _render(adapter, clock, now: float, size) -> np.ndarray:
    clock.now = now
    frame = adapter.render_frame(size[0], size[1], _VIEW, _PROJECTION)
    assert frame.shape == (size[1], size[0], 4), "the viewport always gets an image of its own size"
    return frame


def _settled_picture(adapter, clock, start: float, size, frames: int) -> np.ndarray:
    """The picture after ``frames`` renders at ``size``, counted from the frame that applies the size.

    The first frames at a new size come before the size settles; the clock then
    jumps past the settle time, as when the user stops and the viewport keeps rendering.
    """
    _render(adapter, clock, start, size)
    _render(adapter, clock, start + 0.01, size)
    frame = None
    for index in range(frames):
        frame = _render(adapter, clock, start + 0.3 + 0.01 * index, size)
    return np.array(frame[..., :3], dtype=np.int16)


def _renderer_resolution(recording) -> tuple:
    return tuple(np.from_dlpack(recording._renderer.read_attribute("resolution", [_PRODUCT])).reshape(-1).tolist())


def _stage_resolution(stage) -> tuple:
    value = UsdRender.Product(stage.GetPrimAtPath(_PRODUCT)).GetResolutionAttr().Get()
    return (int(value[0]), int(value[1]))


def test_a_new_viewport_size_changes_only_the_resolution_after_it_settled():
    adapter, recording, stage, clock = _start()
    changed, resynced = [], []

    def _on_change(notice, _sender):
        changed.extend(str(path) for path in notice.GetChangedInfoOnlyPaths())
        resynced.extend(str(path) for path in notice.GetResyncedPaths())

    from pxr import Tf

    listener = Tf.Notice.Register(Usd.Notice.ObjectsChanged, _on_change, stage)
    try:
        _render(adapter, clock, 1.0, (192, 112))
        assert _renderer_resolution(recording) == (160, 96), (
            "the first frame at a new size does not wait for new render buffers"
        )
        _render(adapter, clock, 1.1, (192, 112))
        assert _renderer_resolution(recording) == (160, 96), "the size has not settled yet"
        _render(adapter, clock, 1.3, (192, 112))
        assert _renderer_resolution(recording) == (192, 112), "the settled size reaches the renderer"
        _render(adapter, clock, 1.4, (192, 112))

        assert recording.resolution_writes == [(192, 112)]
        assert (recording.removals, recording.additions) == (0, 0), "the session layer stays in the renderer"
        assert _stage_resolution(stage) == (192, 112), "picking reads the new size from the stage"
        assert changed == [f"{_PRODUCT}.resolution"], "the stage gets one change of one value"
        assert resynced == []
    finally:
        listener.Revoke()
        _stop(adapter, recording)


def test_a_drag_of_the_window_border_applies_only_the_size_where_it_stopped():
    adapter, recording, stage, clock = _start()
    try:
        now = 1.0
        for size in ((170, 100), (180, 106), (190, 112), (200, 118), (210, 124)):
            _render(adapter, clock, now, size)
            now += 0.05
        assert recording.resolution_writes == [], "no size is applied while the size changes"
        _render(adapter, clock, now + 0.1, (210, 124))
        _render(adapter, clock, now + 0.25, (210, 124))

        assert recording.resolution_writes == [(210, 124)]
        assert _renderer_resolution(recording) == (210, 124)
        assert _stage_resolution(stage) == (210, 124)
        assert (recording.removals, recording.additions) == (0, 0)
    finally:
        _stop(adapter, recording)


def test_a_refused_resolution_write_is_reported_and_retried_until_the_viewport_has_an_image(capfd):
    adapter, recording, stage, clock = _start(refuse_resolution=True, failed_additions=1)
    try:
        _render(adapter, clock, 1.0, (192, 112))
        clock.now = 1.3
        with pytest.raises(RuntimeError, match="session layer refused"):
            adapter.render_frame(192, 112, _VIEW, _PROJECTION)

        frame = _render(adapter, clock, 1.4, (192, 112))
        assert recording.additions == 1, "the next frame composes the session layer again"
        assert _renderer_resolution(recording) == (192, 112)
        assert frame[..., :3].max() > 0, "the viewport gets a rendered image, not a black one"
        report = capfd.readouterr().err
        assert report.count(
            f"the resolution write 192x112 to the render product {_PRODUCT} failed "
            "(RuntimeError: resolution write refused)"
        ) == 2, "each refused write is reported"
    finally:
        _stop(adapter, recording)


def test_the_picture_after_a_size_change_and_back_matches_a_fresh_render_at_that_size():
    """The divider of a panel is dragged and dragged back: the picture must be as a fresh render.

    Before, the new size changed only the resolution of the render product, and the
    rendering history of the renderer kept the frames of the old size. The picture at
    the size where the user stopped stayed smeared and ghosted after the renderer
    settled (also after a Content Browser open or close and a Render Scale change).
    """
    size, other = (730, 376), (620, 376)
    adapter, recording, _stage, clock = _start(stage=_scene_with_edges(), first_size=size)
    try:
        fresh = _settled_picture(adapter, clock, 1.0, size, 64)
        assert fresh.mean() > 50.0, "the scene is lit and seen by the camera"
        _settled_picture(adapter, clock, 10.0, other, 64)
        again = _settled_picture(adapter, clock, 20.0, size, 64)

        assert recording.resolution_writes == [other, size]
        assert (recording.removals, recording.additions) == (0, 0), "the session layer stays in the renderer"
        difference = np.abs(again - fresh)
        assert np.percentile(difference, 99) <= 3, (
            "the picture after the size change and back is not the picture of a fresh render "
            f"at {size[0]}x{size[1]}: 99% of the values are within "
            f"{np.percentile(difference, 99):.0f} of it (mean difference {difference.mean():.2f})"
        )
    finally:
        _stop(adapter, recording)


def test_a_refused_renderer_reset_after_a_size_change_is_reported_and_the_session_layer_is_composed_again(capfd):
    adapter, recording, _stage, clock = _start(refuse_reset=True)
    try:
        _render(adapter, clock, 1.0, (192, 112))
        frame = _render(adapter, clock, 1.3, (192, 112))

        assert recording.resolution_writes == [(192, 112)]
        assert (recording.removals, recording.additions) == (1, 1), (
            "a new session layer starts with no frame of the old size"
        )
        assert _renderer_resolution(recording) == (192, 112)
        frame = _render(adapter, clock, 1.4, (192, 112))
        assert frame[..., :3].max() > 0, "the viewport gets a rendered image, not a black one"
        report = capfd.readouterr().err
        assert report.count(
            "the renderer reset after the resolution change to 192x112 failed "
            "(RuntimeError: reset refused)"
        ) == 1, "the refused reset is reported once"
    finally:
        _stop(adapter, recording)
