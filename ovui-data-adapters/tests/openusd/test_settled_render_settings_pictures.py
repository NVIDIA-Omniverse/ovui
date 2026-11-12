# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Undo and Redo of a Reset show stored settled pictures.

ovrtx keeps memory for each frame that it renders and for each renderer
restart. Undo and Redo of Render Settings > Reset Settings move between the
same settings states, and each move rendered a new picture, so the app grew
with each repeat. Under the ``on_change`` policy the OpenUSD renderer adapter
now keeps a setting change for the next frame. That frame shows the stored
settled picture of the new settings state when nothing else changed, and the
renderer gets nothing; otherwise the renderer gets the settings first and
renders. These tests need no GPU: they drive the real ``render_frame`` with a
fake renderer whose pictures encode the settings it had and the step.
"""

from __future__ import annotations

import time
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from ovui_data_adapters.common.render_settings import RenderSettingRequirement
from ovui_data_adapters.openusd import renderer_adapter as mod
from ovui_data_adapters.openusd._settled_pictures import SettledPictures
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

W, H = 32, 18
SETTLE = 3
_PRODUCT = mod._RENDER_PRODUCT_PATH


class _FakeOvrtx:
    Device = SimpleNamespace(CPU="cpu", CUDA="cuda")
    Semantic = SimpleNamespace(XFORM_MAT4x4="xform")


class _FakeMapping:
    def __init__(self, array):
        self.tensor = SimpleNamespace(numpy=lambda: array)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeRenderer:
    """ovrtx stand-in: red is the step number, green the settings it renders with."""

    def __init__(self):
        self.steps = 0
        self.settings = {}
        self.events = []

    def write_attribute(self, prim_paths, attribute_name, tensor, semantic=None):
        pass

    def step(self, render_products, delta_time):
        self.steps += 1
        self.events.append(("step", dict(self.settings)))
        pixels = np.zeros((H, W, 4), dtype=np.uint8)
        pixels[..., 0] = self.steps % 256
        pixels[..., 1] = sum(int(value) for value in self.settings.values()) % 256
        var = SimpleNamespace(map=lambda device=None, p=pixels: _FakeMapping(p))
        frame = SimpleNamespace(render_vars={"LdrColor": var})
        return {product: SimpleNamespace(frames=[frame]) for product in render_products}


def _descriptor(name, before, requirement=RenderSettingRequirement.WARMUP):
    return SimpleNamespace(
        setting_id=f"{_PRODUCT}:{name}",
        metadata={"attr_name": name, "render_product_path": _PRODUCT},
        value_state=SimpleNamespace(current_value=before),
        requirement=requirement,
    )


def _view(camera_x):
    view = np.eye(4)
    view[0, 3] = -float(camera_x)
    return view


_PROJ = np.array(
    [[1.0, 0, 0, 0], [0, 1.78, 0, 0], [0, 0, -1.0002, -0.020002], [0, 0, -1, 0]]
)


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.setattr(mod, "_ovrtx", _FakeOvrtx)
    monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: None))
    monkeypatch.setattr(
        OvRtxRendererAdapter,
        "_render_setting_target",
        lambda self, descriptor: (_PRODUCT, descriptor.metadata["attr_name"]),
    )

    def write(self, descriptor, value):
        # The renderer gets the value, and a new picture follows, as from the
        # adapter's own write (a live write, or a restart for the render mode).
        self._renderer.settings[descriptor.metadata["attr_name"]] = value
        self._renderer.events.append(("write", descriptor.metadata["attr_name"], value))
        self._release_retained_output()
        return False

    monkeypatch.setattr(OvRtxRendererAdapter, "_write_render_setting_to_ovrtx", write)
    a = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    a._renderer = _FakeRenderer()
    a._stage = object()
    a._usd_handle = object()
    a._default_render_product_path = _PRODUCT
    a._default_camera_path = mod._CAMERA_PATH
    a._render_product_path = _PRODUCT
    a._camera_path = mod._CAMERA_PATH
    a._last_resolution = (W, H)
    a._zero_copy_state = None
    a._ldr_overlap = None
    a._in_flight_pick_queries = deque()
    a._dt_clock = time.monotonic()
    a.set_render_policy("on_change", SETTLE)
    return a


# The settings state of a Reset: two settings, and the render mode, which needs a restart.
_CHANGED = {"gamma": 1, "eco": 1, "mode": 2}
_RESET = {"gamma": 0, "eco": 0, "mode": 0}


def _set(adapter, values):
    """Undo or Redo: the settings of ``values``, as Render Settings applies them."""

    for name, value in values.items():
        before = adapter._renderer_values_shown.get(name, 0)
        requirement = (
            RenderSettingRequirement.RENDERER_RESTART if name == "mode" else RenderSettingRequirement.WARMUP
        )
        assert adapter._deliver_render_setting(_descriptor(name, before, requirement), value) is True
        adapter._renderer_values_shown[name] = value


def _still(adapter, camera_x=1.0):
    """The picture once the adapter stops stepping (the ``on_change`` policy)."""

    frame = None
    for _ in range(40):
        frame = adapter.render_frame(W, H, _view(camera_x), _PROJ)
        if adapter.last_frame_unchanged():
            return frame
    raise AssertionError("the adapter did not stop stepping the renderer")


@pytest.fixture
def settled(adapter):
    """The adapter after the user's settings and Reset, each picture settled."""

    adapter._renderer_values_shown = {}
    _still(adapter)
    _set(adapter, _CHANGED)
    changed = np.array(_still(adapter), copy=True)
    _set(adapter, _RESET)
    reset = np.array(_still(adapter), copy=True)
    assert changed[0, 0, 1] != reset[0, 0, 1]
    return adapter, changed, reset


def test_fast_undo_and_redo_render_each_state_a_bounded_number_of_frames(adapter):
    # The settings change before any picture settles: the user's settings, Reset,
    # then fast Undo and Redo. The renderer finishes the pictures while stored
    # ones are on screen, so the frames of each state are bounded however long
    # this goes on, and each state then shows its settled picture with no step.
    adapter._renderer_values_shown = {}
    renderer = adapter._renderer
    _still(adapter)
    steps_after = []
    for action in range(60):
        _set(adapter, _CHANGED if action % 2 == 0 else _RESET)
        for _ in range(1 + action % 3):
            adapter.render_frame(W, H, _view(1.0), _PROJ)
        steps_after.append(renderer.steps)
    # Each state: its first render, the step that stores it when it is left,
    # and one finished picture of the settle frames (once for its first picture, once again).
    bound = 1 + SETTLE + 2 * (2 * (SETTLE + 2) + 2)
    assert steps_after[-1] == steps_after[29], f"Undo and Redo still step the renderer: {steps_after}"
    assert steps_after[-1] <= bound, steps_after
    for values in (_RESET, _CHANGED):
        _set(adapter, values)
        _still(adapter)
    steps = renderer.steps
    for action in range(10):
        values = _RESET if action % 2 == 0 else _CHANGED
        _set(adapter, values)
        # A picture that the renderer made with these settings (green is their sum).
        assert _still(adapter)[0, 0, 1] == sum(values.values())
    assert renderer.steps == steps, "Undo and Redo of settled states stepped the renderer"


def test_undo_and_redo_show_the_stored_pictures_and_give_the_renderer_nothing(settled):
    adapter, changed, reset = settled
    renderer = adapter._renderer
    renderer.events.clear()
    for _ in range(10):
        _set(adapter, _CHANGED)
        assert np.array_equal(_still(adapter), changed)
        _set(adapter, _RESET)
        assert np.array_equal(_still(adapter), reset)
    assert renderer.events == [], "Undo and Redo of a Reset rendered or wrote to the renderer"


def test_a_stored_picture_is_shown_once_then_kept(settled):
    adapter, changed, _reset = settled
    _set(adapter, _CHANGED)
    shown = adapter.render_frame(W, H, _view(1.0), _PROJ)
    assert np.array_equal(shown, changed)
    assert not adapter.last_frame_unchanged(), "the viewport must upload the stored picture"
    again = adapter.render_frame(W, H, _view(1.0), _PROJ)
    assert again is shown and adapter.last_frame_unchanged()


def test_the_renderer_gets_the_settings_on_screen_before_it_renders_again(settled):
    adapter, changed, _reset = settled
    renderer = adapter._renderer
    _set(adapter, _CHANGED)
    _still(adapter)
    renderer.events.clear()
    # The camera moves: the picture of these settings at another camera.
    _still(adapter, camera_x=2.0)
    first_step = next(index for index, event in enumerate(renderer.events) if event[0] == "step")
    assert renderer.events[first_step][1] == _CHANGED
    assert {event[1] for event in renderer.events[:first_step]} == set(_CHANGED)


def test_settings_that_return_to_the_renderer_values_are_not_written(settled):
    adapter, _changed, reset = settled
    renderer = adapter._renderer
    _set(adapter, _CHANGED)
    _still(adapter)
    _set(adapter, _RESET)
    _still(adapter)
    renderer.events.clear()
    # The renderer still has the reset settings: a camera change writes nothing.
    _still(adapter, camera_x=2.0)
    assert [event for event in renderer.events if event[0] == "write"] == []
    assert renderer.events[0] == ("step", _RESET)


def test_a_change_that_is_not_a_setting_forgets_the_stored_pictures(settled):
    adapter, changed, _reset = settled
    renderer = adapter._renderer
    adapter.request_render()
    _still(adapter)
    steps = renderer.steps
    _set(adapter, _CHANGED)
    picture = _still(adapter)
    assert renderer.steps > steps, "a stored picture was shown after another change"
    assert picture[0, 0, 1] == changed[0, 0, 1]


def test_a_pick_steps_the_renderer_with_the_settings_on_screen(settled):
    adapter, _changed, _reset = settled
    renderer = adapter._renderer
    _set(adapter, _CHANGED)
    _still(adapter)
    renderer.events.clear()
    answers = []
    adapter._in_flight_pick_queries.append(
        [1, "point", "pick", lambda *args: answers.append(args), None, None]
    )
    adapter.render_frame(W, H, _view(1.0), _PROJ)
    assert renderer.events[-1] == ("step", _CHANGED)
    assert answers


def test_a_camera_that_returns_does_not_show_a_picture_of_the_old_camera(settled):
    adapter, _changed, _reset = settled
    renderer = adapter._renderer
    _still(adapter, camera_x=2.0)
    _still(adapter, camera_x=1.0)
    steps = renderer.steps
    _set(adapter, _CHANGED)
    _still(adapter)
    assert renderer.steps > steps


def test_the_continuous_policy_gives_each_setting_to_the_renderer_at_once(adapter):
    adapter._renderer_values_shown = {}
    adapter.set_render_policy("continuous", 0)
    adapter.render_frame(W, H, _view(1.0), _PROJ)
    assert adapter._deliver_render_setting(_descriptor("gamma", 0), 1) is False
    assert adapter._renderer.settings == {"gamma": 1}


def test_stored_pictures_are_copies_bounded_in_count_and_bytes():
    pictures = SettledPictures(limit=2, max_bytes=3 * 100)
    first = np.zeros(100, dtype=np.uint8)
    assert pictures.put("scene", "a", first)
    first[:] = 7
    assert not pictures.get("scene", "a").any(), "the store must keep its own copy"
    assert pictures.put("scene", "b", np.ones(100, dtype=np.uint8))
    pictures.get("scene", "a")  # "a" is now the most recently used
    assert pictures.put("scene", "c", np.ones(100, dtype=np.uint8))
    assert pictures.get("scene", "b") is None and len(pictures) == 2
    assert not pictures.put("scene", "d", np.ones(400, dtype=np.uint8))
    assert pictures.nbytes <= 300
    assert pictures.get("other scene", "a") is None
    pictures.keep_scene("other scene")
    assert len(pictures) == 0
    assert pictures.put("scene", "a", first)
    assert pictures.put("new scene", "b", first)
    assert pictures.get("scene", "a") is None and len(pictures) == 1


def test_a_render_product_that_has_its_targets_makes_no_stage_change():
    # A renderer restart (the render mode of a Reset, its Undo and its Redo)
    # authors the session render product again. A stage change notice of it
    # would make the viewport render again and forget the stored pictures.
    from pxr import Tf, Usd

    from ovui_data_adapters.openusd._session_authoring import ensure_render_product

    stage = Usd.Stage.CreateInMemory()
    ensure_render_product(stage, resolution=(W, H))
    changed = []
    listener = Tf.Notice.Register(
        Usd.Notice.ObjectsChanged,
        lambda notice, sender: changed.extend(
            list(notice.GetChangedInfoOnlyPaths()) + list(notice.GetResyncedPaths())
        ),
        stage,
    )
    try:
        ensure_render_product(stage, resolution=(W, H))
        assert changed == []
        ensure_render_product(stage, camera_path="/OvGearSession/Cameras/Other", resolution=(W, H))
        assert changed, "a new camera target must still be authored"
    finally:
        listener.Revoke()


def test_a_partial_picture_never_replaces_a_settled_one():
    pictures = SettledPictures(limit=2, max_bytes=1000)
    partial = np.full(10, 1, dtype=np.uint8)
    settled = np.full(10, 2, dtype=np.uint8)
    assert pictures.put("scene", "a", partial, settled=False)
    assert not pictures.settled("scene", "a")
    assert pictures.put("scene", "a", settled)
    assert pictures.settled("scene", "a")
    assert not pictures.put("scene", "a", partial, settled=False)
    assert pictures.get("scene", "a")[0] == 2
    assert not pictures.settled("other scene", "a")
    pictures.put("scene", "b", partial)
    pictures.put("scene", "c", partial)  # "a" is the least recently used: it goes
    assert pictures.get("scene", "a") is None and not pictures.settled("scene", "a")


def test_a_camera_change_during_a_background_picture_renders_the_settings_on_screen(adapter):
    adapter._renderer_values_shown = {}
    renderer = adapter._renderer
    _still(adapter)
    _set(adapter, _CHANGED)
    adapter.render_frame(W, H, _view(1.0), _PROJ)  # left before it settles
    _set(adapter, _RESET)
    adapter.render_frame(W, H, _view(1.0), _PROJ)
    _set(adapter, _CHANGED)  # a stored partial picture; the renderer finishes the reset settings
    adapter.render_frame(W, H, _view(1.0), _PROJ)
    adapter.render_frame(W, H, _view(1.0), _PROJ)
    assert renderer.events[-1] == ("step", _RESET), "no background step of the renderer's settings"
    renderer.events.clear()
    _still(adapter, camera_x=2.0)
    first_step = next(index for index, event in enumerate(renderer.events) if event[0] == "step")
    assert renderer.events[first_step][1] == _CHANGED


def _viewport_policy(adapter, values):
    """As the viewport sets it after a frame: the sample target of the path traced state, else the settle frames."""

    adapter.set_render_policy("on_change", 2 * SETTLE if values["mode"] == 2 else SETTLE)


def test_a_settle_change_that_follows_the_settings_keeps_the_stored_pictures(adapter):
    # Path tracing renders to its sample target: the viewport changes the
    # settle frames with the render mode, after the frame of each Undo and Redo.
    adapter._renderer_values_shown = {}
    renderer = adapter._renderer
    _still(adapter)
    for values in (_CHANGED, _RESET, _CHANGED, _RESET):
        _set(adapter, values)
        adapter.render_frame(W, H, _view(1.0), _PROJ)
        _viewport_policy(adapter, values)
        for _ in range(4 * (2 * SETTLE + 2)):
            adapter.render_frame(W, H, _view(1.0), _PROJ)
    pictures = {}
    for values in (_CHANGED, _RESET):
        _set(adapter, values)
        adapter.render_frame(W, H, _view(1.0), _PROJ)
        _viewport_policy(adapter, values)
        pictures[values["mode"]] = np.array(_still(adapter), copy=True)
    renderer.events.clear()
    for _ in range(10):
        for values in (_CHANGED, _RESET):
            _set(adapter, values)
            frame = adapter.render_frame(W, H, _view(1.0), _PROJ)
            _viewport_policy(adapter, values)
            assert np.array_equal(frame, pictures[values["mode"]])
            assert np.array_equal(_still(adapter), pictures[values["mode"]])
    assert renderer.events == [], "a settle change of Undo and Redo rendered or wrote to the renderer"


def test_a_picture_finished_with_fewer_settle_frames_than_its_target_is_finished_again(settled):
    adapter, _changed, _reset = settled
    renderer = adapter._renderer
    _set(adapter, _CHANGED)
    _still(adapter)
    # The target of this settings state rises (its sample target): the stored
    # picture has too few frames, and it is finished again in the background.
    adapter.set_render_policy("on_change", 2 * SETTLE)
    renderer.events.clear()
    for _ in range(4 * (2 * SETTLE + 2)):
        adapter.render_frame(W, H, _view(1.0), _PROJ)
    steps = [event for event in renderer.events if event[0] == "step"]
    assert len(steps) == 2 * SETTLE + 1, renderer.events
    assert all(settings == _CHANGED for _step, settings in steps)
    renderer.events.clear()
    _set(adapter, _RESET)
    _still(adapter)
    _set(adapter, _CHANGED)
    _still(adapter)
    assert [event for event in renderer.events if event[0] == "step"] == []


def test_after_another_change_each_state_renders_once_then_comes_back_stored(settled):
    # A camera change or a selection forgets the stored pictures. The setting
    # values that the renderer has stay known, so the picture on screen is
    # stored under its own settings state, and Undo and Redo after it render
    # each state once at most.
    adapter, _changed, _reset = settled
    renderer = adapter._renderer
    adapter.request_render()
    _still(adapter)
    _set(adapter, _CHANGED)
    _still(adapter)
    steps = renderer.steps
    _set(adapter, _RESET)
    _still(adapter)
    assert renderer.steps == steps, "the state on screen before the change was not stored"
    for values in (_CHANGED, _RESET, _CHANGED):
        _set(adapter, values)
        assert _still(adapter)[0, 0, 1] == sum(values.values())
    assert renderer.steps == steps



def test_a_click_on_a_stored_picture_asks_the_renderer_with_the_settings_on_screen(
    settled, monkeypatch
):
    # Review 5: Undo shows the stored picture of the other render mode. A
    # click queued its pick query while the renderer still had the old mode;
    # the restart for the new mode came after it. The renderer now gets the
    # settings of the picture on screen first, then the query, and the click
    # selects at once.
    adapter, _changed, _reset = settled
    renderer = adapter._renderer
    queued = []

    def enqueue(product, *rect):
        renderer.events.append(("query", dict(renderer.settings)))
        queued.append(rect)

    renderer.enqueue_pick_query = enqueue
    monkeypatch.setattr(
        OvRtxRendererAdapter,
        "_read_pick_hits",
        lambda self, products, product_path=None: [("/World/Cube", None)] if queued and (queued.pop() or True) else [],
    )
    adapter._pick_seq = 0
    adapter._pick_enqueue_count = 0
    _set(adapter, _CHANGED)
    _still(adapter)
    assert adapter._settled_hold is not None, "Undo did not show the stored picture"
    renderer.events.clear()
    answers = []
    adapter.pick(0.1, -0.1, lambda path, _point: answers.append(path), "viewport_click")
    _still(adapter)
    assert answers == ["/World/Cube"], "the click on the stored picture selected nothing"
    query = renderer.events.index(("query", _CHANGED)) if ("query", _CHANGED) in renderer.events else None
    assert query is not None, f"the query was asked with other settings: {renderer.events}"
    assert {event[1] for event in renderer.events[:query] if event[0] == "write"} == set(_CHANGED)


def test_a_surface_query_on_a_stored_picture_answers_the_surface_under_the_cursor(
    settled, monkeypatch
):
    # Review of the zoom: a stored picture stops the render worker, and the
    # surface query of the mouse wheel zoom said "not available", so the zoom
    # used the target depth and moved the camera to the floor. The query is now
    # answered at once by a step that is not shown, at the camera of the
    # picture, and the renderer keeps its settings.
    adapter, changed, _reset = settled
    renderer = adapter._renderer
    queued = []
    cameras = []

    def enqueue(product, *rect, flags=0):
        queued.append((product, rect, flags))

    def write_attribute(prim_paths, attribute_name, tensor, semantic=None):
        if attribute_name == "omni:xform":
            cameras.append(np.asarray(tensor, dtype=np.float64).copy())

    renderer.enqueue_pick_query = enqueue
    renderer.write_attribute = write_attribute
    # ovrtx gives the world position of a hit only with the flag of the native query.
    monkeypatch.setattr(_FakeOvrtx, "OVRTX_PICK_FLAG_INCLUDE_TRACKED_INFO", 4, raising=False)
    monkeypatch.setattr(
        OvRtxRendererAdapter,
        "_read_pick_hits",
        lambda self, products, product_path=None: [
            ("/World/Cabinet", (1.5, 0.25, -2.0) if queued[-1][2] == 4 else None)
        ]
        if queued
        else [],
    )
    monkeypatch.setattr(mod, "_pick_surface_point", lambda *args: None)
    monkeypatch.setattr(mod, "_view_to_ovrtx_transform", lambda view: np.asarray(view))
    monkeypatch.setattr(OvRtxRendererAdapter, "_runtime_camera_xform", lambda self, world, path: world)
    monkeypatch.setattr(OvRtxRendererAdapter, "_push_camera_intrinsics", lambda self, proj, path: None)
    monkeypatch.setattr(mod, "_stage_units_per_meter", lambda stage: 100.0)
    _set(adapter, _CHANGED)
    shown = _still(adapter)
    assert adapter._settled_hold is not None, "Undo did not show the stored picture"
    assert np.array_equal(shown, changed)
    renderer.events.clear()
    # The stored picture stopped the native render worker (no session).
    adapter._frame_pacing_token = 0
    native = SimpleNamespace(
        _native_frame_pacing_query_surface=lambda *rect: 7,
        _native_frame_pacing_surface_hit=lambda: (7, None),
    )
    monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: native))
    number = adapter.query_surface(0.3, 0.2)
    monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: None))
    assert number != 0, "the surface query on a stored picture was not available"
    assert adapter.surface_hit() == (number, (150.0, 25.0, -200.0))
    assert len(queued) == 1 and queued[0][0] == _PRODUCT
    # One step that is not shown, with the camera of the picture and the settings that the renderer had.
    assert [event[0] for event in renderer.events] == ["step"]
    assert np.allclose(cameras[-1], _view(1.0))
    # The stored picture stays on screen until the camera moves.
    assert np.array_equal(adapter.render_frame(W, H, _view(1.0), _PROJ), changed)
    assert [event[0] for event in renderer.events] == ["step"]
