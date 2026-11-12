# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A paused native pacing session keeps the viewport's presentation key.

Choosing Ortho and framing a selection changes the camera intrinsics. The
adapter pauses the native render worker for the synchronous step that applies
them. If that step's LdrColor reached the ImageBridge, it would replace the
key the native presenter installed in the viewport provider. Resuming at the
same size never installs the key again, so the viewport kept showing the last
synchronous image, old selection outlines included, until a transform
restarted the session. These runtime-free tests drive the real
``render_frame`` path with a fake renderer and fake native bindings.
"""

from __future__ import annotations

import time
from collections import deque
from types import SimpleNamespace

import numpy as np
import pytest

from ovui_data_adapters.openusd import renderer_adapter as mod
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

W, H = 64, 36
_VIEW = np.eye(4)
_PERSPECTIVE = np.array(
    [[1.0, 0, 0, 0], [0, 1.78, 0, 0], [0, 0, -1.0002, -0.020002], [0, 0, -1, 0]]
)
# Ortho framing: a different fx/fy, so ovrtx needs new camera intrinsics.
_ORTHO = np.array(
    [[0.2, 0, 0, 0], [0, 0.356, 0, 0], [0, 0, -0.002, -1.0], [0, 0, 0, 1.0]]
)


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
    def __init__(self):
        self.steps = 0

    def write_attribute(self, prim_paths, attribute_name, tensor, semantic=None):
        pass

    def reset(self, time=0.0):
        pass

    def step(self, render_products, delta_time):
        self.steps += 1
        pixels = np.full((H, W, 4), 255, dtype=np.uint8)
        var = SimpleNamespace(map=lambda device=None: _FakeMapping(pixels))
        frame = SimpleNamespace(render_vars={"LdrColor": var})
        return {product: SimpleNamespace(frames=[frame]) for product in render_products}


class _FakeNativePacing:
    """The native coordinator's Python bindings, recording each call."""

    def __init__(self):
        self.calls = []

    def _get_present_rate(self):
        return -1.0

    def _get_native_frame_pacing_status(self):
        return {}

    def _native_frame_pacing_start(self, *args):
        raise AssertionError("the running session must be resumed, not restarted")

    def _native_frame_pacing_publish(self, token, width, height, world, velocity, timestamp):
        self.calls.append("publish")
        return True

    def _native_frame_pacing_pause_render(self, token):
        self.calls.append("pause")
        return True

    def _native_frame_pacing_resume_render(self, token):
        self.calls.append("resume")
        return True

    def _native_frame_pacing_stop(self, token):
        self.calls.append("stop")
        return True


@pytest.fixture
def native(monkeypatch):
    bindings = _FakeNativePacing()
    monkeypatch.setattr(mod, "_ovrtx", _FakeOvrtx)
    monkeypatch.setattr(
        OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: bindings)
    )
    return bindings


@pytest.fixture
def adapter(native):
    a = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    a._renderer = _FakeRenderer()
    a._stage = object()
    a._usd_handle = object()
    a._default_render_product_path = mod._RENDER_PRODUCT_PATH
    a._default_camera_path = mod._CAMERA_PATH
    a._render_product_path = mod._RENDER_PRODUCT_PATH
    a._camera_path = mod._CAMERA_PATH
    a._last_resolution = (W, H)
    a._zero_copy_state = None
    a._livestream = None
    a._point_cloud_requests = {}
    a._render_var_output_requests = {}
    a._in_flight_pick_queries = deque()
    a._dt_clock = time.monotonic()
    # A running native session presents this viewport. Starting a session
    # disables the LdrOverlap, as _publish_native_frame does.
    a._ldr_overlap = None
    a._frame_pacing_provider = object()
    a._frame_pacing_token = 1
    a._frame_pacing_needs_sync_step = False
    a._frame_pacing_render_paused = False
    a._frame_pacing_size = (W, H)
    a._frame_pacing_projection = _PERSPECTIVE.copy()
    a._frame_pacing_camera_path = a._runtime_camera_path()
    a._frame_pacing_last_raw_world = None
    a._frame_pacing_last_intent_time = 0.0
    a._frame_pacing_restore_overlap = False
    a._frame_pacing_pick_snapshot = None
    a._frame_pacing_presented_snapshot = None
    a._frame_pacing_pick_generated = False
    a._frame_pacing_pick_association_unavailable = False
    return a


def test_intrinsics_change_keeps_the_native_presentation_key(adapter, native):
    assert adapter.render_frame(W, H, _VIEW, _PERSPECTIVE) is None
    assert native.calls == ["publish"]

    # Ortho framing: the worker pauses and Python applies the intrinsics.
    image = adapter.render_frame(W, H, _VIEW, _ORTHO)
    assert native.calls == ["publish", "pause"]
    assert adapter._renderer.steps == 1
    # The native session still owns the provider's key: no synchronous
    # image may reach the ImageBridge and replace it.
    assert image is None

    # The next frame resumes the same session, which presents again.
    assert adapter.render_frame(W, H, _VIEW, _ORTHO) is None
    assert native.calls == ["publish", "pause", "resume", "publish"]
    assert adapter._renderer.steps == 1


def test_the_outline_pass_starts_when_the_viewport_is_idle(adapter, native, monkeypatch):
    """Defects: the outline pass held either the start-up or the first selection.

    Started right after the scene's first frames, its reset and session
    restart made UI frames of 24-55 ms during start-up. Started at the
    first selection, it reset the renderer while the user waited for the
    outline. It now starts when the viewport is idle after start-up: not
    before the scene has been shown for a while, and not while the camera
    moves. The steps are main's: pause, anchor, reset, and one session
    restart when the frames after the reset are shown.
    """

    clock = [100.0]
    monkeypatch.setattr(mod.time, "perf_counter", lambda: clock[0])
    resets = []
    adapter._renderer.reset = lambda *a, **k: resets.append(1)
    adapter._selection_outline_pass_needs_reset = True
    presented = [10]
    native._get_native_frame_pacing_status = lambda: {"presented_renderer_frames": presented[0]}
    moving = _VIEW.copy()

    ui_thread_frames = []

    def frame(view=_VIEW, advance=0.5):
        clock[0] += advance
        if adapter.render_frame(W, H, view, _PERSPECTIVE) is not None:
            ui_thread_frames.append(clock[0])

    # Start-up: the scene is shown, but not long enough.
    for _ in range(int(mod._OUTLINE_PASS_AFTER_S / 0.5) - 2):
        frame()
    assert resets == []
    # The camera moves: still no start while it moves, nor right after.
    for step in range(8):
        moving[3, 0] = float(step)
        frame(moving)
    frame(moving)
    assert resets == []
    # Idle: the pass starts with a pause and a resume.
    for _ in range(int(mod._OUTLINE_PASS_STILL_S / 0.5) + 2):
        frame(moving)
    assert resets == [1]
    assert adapter._selection_outline_pass_needs_reset is False
    assert ui_thread_frames == []
    presented[0] += 3
    for _ in range(3):
        frame(moving)

    assert native.calls.count("pause") == 1
    assert native.calls.count("resume") == 1
    assert native.calls.count("stop") == 1
    # The restart renders on the UI thread until the new session runs; this
    # fake renderer cannot be borrowed again, so it stays there.
    assert ui_thread_frames
    assert resets == [1]


def test_a_selection_that_starts_the_outline_pass_does_not_wait_for_the_renderer(adapter, native, monkeypatch):
    """Defect: a selection soon after the scene appeared held the UI twice as long as on main.

    Before the idle start, the first selection starts the outline pass and
    resets the renderer. The selection stopped the session, so the next
    frame rendered on the UI thread and waited for the long first render
    after the reset. The selection now pauses the session; the next frame
    resumes it, and once three frames after the reset are shown the
    session restarts once. The viewport's refresh of the outline after the
    next frame waits for that restart instead of for the renderer. A later
    selection pauses the session too (review of #854): a stop puts a black
    image in the viewport until a new picture comes, for all of a rebuild
    when the selection changes just before a structural edit.
    """

    resets = []
    adapter._renderer.reset = lambda *a, **k: resets.append(1)
    adapter._selection_outline_pass_needs_reset = True
    adapter._selection_outline_armed = False
    writes = []
    monkeypatch.setattr(
        adapter,
        "_write_selection_outline_group",
        lambda paths, group: writes.append((list(paths), group)) or True,
    )
    monkeypatch.setattr(adapter, "_configure_selection_outline_styles", lambda: None)
    monkeypatch.setattr(
        adapter,
        "_apply_selection_outline_anchor",
        lambda: setattr(adapter, "_selection_outline_anchor_applied", True),
    )
    presented = [50]
    native._get_native_frame_pacing_status = lambda: {"presented_renderer_frames": presented[0]}

    adapter.set_selection_highlight(["/World/Cube"])
    assert resets == [1]
    assert native.calls == ["pause"]
    # The next frame resumes the session: nothing renders on the UI thread.
    assert adapter.render_frame(W, H, _VIEW, _PERSPECTIVE) is None
    assert native.calls == ["pause", "resume", "publish"]
    assert adapter.render_frame(W, H, _VIEW, _PERSPECTIVE) is None
    writes.clear()
    adapter.refresh_selection_highlight(["/World/Cube"])
    assert "stop" not in native.calls and native.calls.count("pause") == 1
    assert writes == []

    presented[0] += 3
    adapter.render_frame(W, H, _VIEW, _PERSPECTIVE)
    assert native.calls.count("stop") == 1
    assert writes == [(["/World/Cube"], mod._SELECTION_OUTLINE_GROUP_ID)]
    assert resets == [1]

    native.calls.clear()
    adapter._frame_pacing_token = 7
    adapter._frame_pacing_needs_sync_step = False
    adapter.set_selection_highlight(["/World/Other"])
    assert native.calls == ["pause"]
    assert adapter._frame_pacing_token == 7
    assert resets == [1]


@pytest.mark.parametrize("newer", [["/World/Other"], []], ids=["newer selection", "clear"])
def test_a_held_outline_refresh_never_writes_back_an_older_selection(adapter, native, monkeypatch, newer):
    """Defect: a held refresh of selection A overwrote a newer selection or undid a clear."""

    adapter._renderer.reset = lambda *a, **k: None
    adapter._selection_outline_pass_needs_reset = True
    adapter._selection_outline_armed = False
    writes = []
    monkeypatch.setattr(
        adapter,
        "_write_selection_outline_group",
        lambda paths, group: writes.append((list(paths), group)) or True,
    )
    monkeypatch.setattr(adapter, "_configure_selection_outline_styles", lambda: None)
    monkeypatch.setattr(
        adapter,
        "_apply_selection_outline_anchor",
        lambda: setattr(adapter, "_selection_outline_anchor_applied", True),
    )
    presented = [50]
    native._get_native_frame_pacing_status = lambda: {"presented_renderer_frames": presented[0]}

    adapter.set_selection_highlight(["/World/A"])
    adapter.render_frame(W, H, _VIEW, _PERSPECTIVE)
    adapter.refresh_selection_highlight(["/World/A"])  # held
    adapter.set_selection_highlight(newer)
    writes.clear()
    # Deliver whatever is still held: by the session restart or by its end.
    presented[0] += 3
    for _ in range(3):
        adapter.render_frame(W, H, _VIEW, _PERSPECTIVE)

    group = mod._SELECTION_OUTLINE_GROUP_ID
    assert not [w for w in writes if "/World/A" in w[0] and w[1] == group]
    assert adapter._selected_paths == newer


def _light_stage():
    from pxr import Usd, UsdGeom, UsdLux

    stage = Usd.Stage.CreateInMemory()
    UsdLux.DomeLight.Define(stage, "/World/Dome").CreateIntensityAttr(1.0)
    UsdGeom.Mesh.Define(stage, "/World/Mesh")
    return stage


def _info_change(*paths):
    from ovui_data_adapters.common.adapters import ChangeEvent, ChangeEventType

    return ChangeEvent(
        changed_paths=tuple(paths),
        resynced_paths=(),
        event_type=ChangeEventType.INFO_CHANGE,
    )


def test_a_slider_drag_on_a_light_pauses_the_session_and_never_restarts_it(adapter, native):
    """Defect: every edit of a slider drag stopped the native session.

    The next frame then started a new session on the UI thread, which made
    a stall of 40-130 ms for each edit of a light intensity drag. A value
    edit that ovrtx takes in place now parks the render worker and the next
    frame resumes the same session. ``_native_frame_pacing_start`` of the
    fake raises, so a restart fails the test.
    """

    stage = _light_stage()
    adapter._stage = stage
    adapter._reload_live_root_snapshot = lambda: pytest.fail("a value edit must not reload")
    writes = []
    adapter._renderer.write_attribute = lambda **kw: writes.append(kw["tensor"].tolist())
    assert adapter.render_frame(W, H, _VIEW, _PERSPECTIVE) is None
    native.calls.clear()

    attr = stage.GetAttributeAtPath("/World/Dome.inputs:intensity")
    for step in range(1, 21):
        attr.Set(float(step))
        adapter.notify_stage_changed(_info_change("/World/Dome.inputs:intensity"))
        assert adapter.render_frame(W, H, _VIEW, _PERSPECTIVE) is None
        assert adapter.render_frame(W, H, _VIEW, _PERSPECTIVE) is None

    assert "stop" not in native.calls
    assert native.calls.count("pause") == 20
    assert native.calls.count("resume") == 20
    assert adapter._frame_pacing_token == 1
    # Each edit reached ovrtx, and the last value is the final one.
    assert writes == [[float(step)] for step in range(1, 21)]


@pytest.mark.parametrize("event", ["mesh points", "root resync"])
def test_a_structural_stage_change_pauses_the_session_and_does_not_stop_it(adapter, native, event):
    """Review of #854: with native frame pacing, a rename made the viewport black.

    A structural edit (here a mesh topology change) or a layer mute (a resync
    of the root) reloads the scene, and ovrtx then builds it again for many
    seconds. The stop of the session put a black image key in the viewport
    for all that time. A pause keeps the presenter, which shows the last
    picture. ``_native_frame_pacing_start`` of the fake raises, so a restart
    fails the test.
    """

    from ovui_data_adapters.common.adapters import ChangeEvent, ChangeEventType

    stage = _light_stage()
    adapter._stage = stage
    adapter._reload_live_root_snapshot = lambda: True
    assert adapter.render_frame(W, H, _VIEW, _PERSPECTIVE) is None
    native.calls.clear()

    if event == "mesh points":
        adapter.notify_stage_changed(_info_change("/World/Mesh.points"))
    else:
        adapter.notify_stage_changed(
            ChangeEvent(changed_paths=(), resynced_paths=("/",), event_type=ChangeEventType.RESYNC)
        )

    assert native.calls == ["pause"]
    assert adapter._frame_pacing_token == 1
    assert adapter.scene_update_pending()


def _restart_adapter(adapter, native, monkeypatch):
    """A running session whose renderer can be borrowed again, with a reset to count."""

    resets = []
    adapter._renderer.reset = lambda *a, **k: resets.append(1)
    adapter._selection_outline_armed = True
    adapter._rendered_since_load = True
    monkeypatch.setattr(adapter, "_reinject_session_layer", lambda: None)
    monkeypatch.setattr(adapter, "_release_retained_output", lambda **k: None)
    monkeypatch.setattr(adapter, "_reset_render_timing_state", lambda: None)
    monkeypatch.setattr(adapter, "_borrow_native_renderer", lambda: (1, "lib", 1, 0, 0))
    starts = []
    native._native_frame_pacing_start = lambda *a: starts.append(a) or 5
    return resets, starts


def test_the_first_frame_after_a_render_setting_restart_is_rendered_by_the_native_worker(
    adapter, native, monkeypatch
):
    """Defect: a render setting such as Denoising stalled the UI for seconds.

    The setting resets the renderer, and the first frame after a reset takes
    seconds on a heavy scene. The stop of the session made that frame render
    on the UI thread. The native worker now renders it: the next frame starts
    the session again and runs no synchronous step. The stage change that the
    setting authors stops the session once more, and keeps that.
    """

    resets, starts = _restart_adapter(adapter, native, monkeypatch)
    adapter._stop_native_frame_pacing("render setting mutation")
    adapter._restart_for_render_settings()
    adapter._stop_native_frame_pacing("stage change publication")
    assert resets == [1]

    # The session starts a frame or two after the frame that applied the
    # setting, and no frame renders a step on the UI thread.
    for _ in range(mod._NATIVE_FIRST_FRAME_DELAY_FRAMES):
        assert adapter.render_frame(W, H, _VIEW, _PERSPECTIVE) is None
        assert starts == []
    assert adapter.render_frame(W, H, _VIEW, _PERSPECTIVE) is None
    assert len(starts) == 1
    assert adapter._renderer.steps == 0
    assert adapter._frame_pacing_token == 5
    assert adapter._frame_pacing_first_frame_native is False


def test_a_render_setting_restart_writes_the_viewport_lens_before_the_native_session_starts(
    adapter, native, monkeypatch
):
    """Defect: after a reset the scene was about 38% larger, with an unchanged camera.

    The reset replaces the session camera, which then holds the session
    default lens. The synchronous step wrote the viewport's lens. The native
    first frame must write it too, before the worker takes the renderer.
    """

    resets, starts = _restart_adapter(adapter, native, monkeypatch)
    order = []
    monkeypatch.setattr(
        adapter, "_push_camera_intrinsics", lambda proj, path: order.append(("lens", proj))
    )
    native._native_frame_pacing_start = lambda *a: order.append(("start",)) or 5
    adapter._stop_native_frame_pacing("render setting mutation")
    adapter._restart_for_render_settings()
    for _ in range(mod._NATIVE_FIRST_FRAME_DELAY_FRAMES + 1):
        adapter.render_frame(W, H, _VIEW, _ORTHO)

    assert [item[0] for item in order] == ["lens", "start"]
    assert order[0][1] is _ORTHO


def test_other_mutations_still_render_one_synchronous_step_before_the_session_restarts(
    adapter, native, monkeypatch
):
    resets, starts = _restart_adapter(adapter, native, monkeypatch)
    adapter._stop_native_frame_pacing("stage change publication")

    image = adapter.render_frame(W, H, _VIEW, _PERSPECTIVE)
    assert image is not None and adapter._renderer.steps == 1
    assert starts == []


def test_a_new_viewport_size_keeps_the_session_paused_until_the_size_is_applied(adapter, native):
    """A window resize must not let the native worker run with the old render size.

    A new viewport size waits until it settles. Before, the session resumed on
    the next frame and the synchronous path that applies the size did not run
    again, so the render product kept its old size.
    """
    clock = [10.0]
    adapter._clock = lambda: clock[0]
    adapter._resize_request = (W, H)
    resolution_writes = []

    def write_attribute(prim_paths, attribute_name, tensor, semantic=None):
        if attribute_name == "resolution":
            resolution_writes.append(np.asarray(tensor).tolist())

    adapter._renderer.write_attribute = write_attribute
    adapter._author_owned_session_render_product_resolution_value = lambda resolution: None
    size = (W + 32, H + 18)

    assert adapter.render_frame(W, H, _VIEW, _PERSPECTIVE) is None
    # The first frame at the new size: the worker pauses; ovrtx keeps the old size.
    assert adapter.render_frame(*size, _VIEW, _PERSPECTIVE) is None
    assert native.calls == ["publish", "pause"]
    clock[0] += 0.1
    assert adapter.render_frame(*size, _VIEW, _PERSPECTIVE) is None
    assert native.calls == ["publish", "pause"], "the worker stays paused while the size waits"
    assert resolution_writes == []

    clock[0] += mod._RESIZE_SETTLE_S
    assert adapter.render_frame(*size, _VIEW, _PERSPECTIVE) is None
    assert resolution_writes == [[list(size)]], "the settled size reaches the render product"
    assert adapter.render_frame(*size, _VIEW, _PERSPECTIVE) is None
    assert native.calls == ["publish", "pause", "resume", "publish"]


def test_a_new_session_starts_after_a_waiting_pick_is_answered(adapter, native, monkeypatch):
    # Review 5 of #774: right after a renderer restart no session runs, and a
    # new session would render the first frame. A pick queued then waits for
    # the answer of a synchronous step; a session started before it took
    # every step, and the click selected nothing.
    adapter._frame_pacing_token = 0
    adapter._frame_pacing_first_frame_native = True
    adapter._frame_pacing_start_delay = 0
    started = []

    def start(*args):
        started.append(args)
        return 7

    native._native_frame_pacing_start = start
    monkeypatch.setattr(
        OvRtxRendererAdapter, "_borrow_native_renderer", lambda self: (1, "ovrtx", 0, 0, 0)
    )
    queued = []
    adapter._renderer.enqueue_pick_query = lambda product, *rect: queued.append(rect)
    monkeypatch.setattr(
        OvRtxRendererAdapter,
        "_read_pick_hits",
        lambda self, products, product_path=None: [("/World/Cube", None)] if queued else [],
    )
    adapter._pick_seq = 0
    adapter._pick_enqueue_count = 0
    answers = []
    adapter.pick(0.0, 0.0, lambda path, _point: answers.append(path), "viewport_click")
    adapter.render_frame(W, H, _VIEW, _PERSPECTIVE)
    assert answers == ["/World/Cube"], "the waiting pick got no answer"
    assert started == [] and adapter._renderer.steps == 1
    # With no pick waiting, the next frame starts the session.
    assert adapter.render_frame(W, H, _VIEW, _PERSPECTIVE) is None
    assert len(started) == 1
