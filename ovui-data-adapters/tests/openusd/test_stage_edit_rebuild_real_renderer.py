# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A stage edit that reloads the scene must not make the UI thread wait.

A rename, its Undo and its Redo reload the live root layer into ovrtx. The first
step after that reload builds the whole scene again; on a large scene it takes
many seconds. Before the fix, ``render_frame`` ran that step on the UI thread and
waited for it, and the window stopped. Now the frame after the reload returns no
new picture while the step runs, and the edits of that time go to ovrtx when the
step is done.

Each test runs in a process of its own with the real renderer and reads the
result back from it, which is what the renderer draws.
"""

from __future__ import annotations

import time

import numpy as np
import pytest
from pxr import Sdf, Usd

from ovui_data_adapters.common import ChangeEvent, ChangeEventType
from ovui_data_adapters.common.render_diagnostics import BackgroundTaskStuckError

pytestmark = [pytest.mark.requires_ovrtx, pytest.mark.own_process]

_SCENE = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "Group"
    {
        def Cube "Box"
        {
            double size = 40
        }
    }
}
"""

_OTHER_SCENE = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Sphere "Ball"
    {
        double radius = 7
    }
}
"""

_MOVED = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [30.0, 0.0, 0.0, 1.0],
]

_VIEW = np.identity(4)
_VIEW[3, 2] = -200.0
_PROJECTION = np.array(
    [[1.0, 0.0, 0.0, 0.0], [0.0, 2.0, 0.0, 0.0], [0.0, 0.0, -1.0, -1.0], [0.0, 0.0, -2.0, 0.0]]
)


def _render(adapter):
    return adapter.render_frame(64, 32, _VIEW, _PROJECTION)


def _render_until_current(adapter, timeout: float = 300.0):
    """Render as a frame loop does until the scene is built again; return the next picture."""

    deadline = time.monotonic() + timeout
    while adapter.scene_update_pending():
        assert time.monotonic() < deadline, "the renderer did not finish building the scene"
        _render(adapter)
        time.sleep(0.01)
    return _render(adapter)


def _rename(stage, old: str, new: str) -> ChangeEvent:
    """Rename as the Stage Browser command does, and return the event that the stage adapter sends."""

    edit = Sdf.BatchNamespaceEdit()
    edit.Add(Sdf.Path(old), Sdf.Path(new))
    assert stage.GetRootLayer().Apply(edit)
    return ChangeEvent(changed_paths=(), resynced_paths=(new,), event_type=ChangeEventType.RESYNC)


def _renderer_value(adapter, attribute: str, prim_path: str) -> float:
    """Return the value that the ovrtx renderer of ``adapter`` has for the attribute."""

    values = np.from_dlpack(adapter._renderer.read_attribute(attribute, [prim_path])).tolist()
    assert len(values) == 1, values
    return float(values[0])


def _renderer_has(adapter, attribute: str, prim_path: str) -> bool:
    try:
        _renderer_value(adapter, attribute, prim_path)
    except RuntimeError:
        return False
    return True


class _NativePacingRecorder:
    """The Python bindings of the native frame pacing coordinator, recording each call.

    A real session needs the Vulkan window of an application, so these
    bindings record what the adapter asks for; the renderer is real.
    """

    def __init__(self):
        self.calls = []

    def _get_present_rate(self):
        return -1.0

    def _get_native_frame_pacing_status(self):
        return {}

    def _native_frame_pacing_start(self, *args):
        raise AssertionError("the paused session must be resumed, not started again")

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


def test_a_rename_reload_does_not_wait_and_an_undo_of_that_time_reaches_the_renderer(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "group.usda"
    scene.write_text(_SCENE)
    stage = Usd.Stage.Open(str(scene))
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        assert _render(adapter) is not None

        adapter.notify_stage_changed(_rename(stage, "/World/Group", "/World/Group2"))
        # The frame after the reload starts the step that builds the scene
        # again and returns at once with no new picture.
        assert _render(adapter) is None
        assert adapter.scene_update_pending()

        # The Undo while that step runs goes to the renderer after the step:
        # the renderer still has the renamed prim.
        adapter.notify_stage_changed(_rename(stage, "/World/Group2", "/World/Group"))
        assert _renderer_value(adapter, "size", "/World/Group2/Box") == 40.0

        assert _render_until_current(adapter) is not None
        assert not adapter.scene_update_pending()
        assert _renderer_value(adapter, "size", "/World/Group/Box") == 40.0
        assert not _renderer_has(adapter, "size", "/World/Group2/Box")
    finally:
        adapter.shutdown()


def test_a_scene_opened_while_the_renderer_builds_the_old_one_again_drops_its_edits(tmp_path):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "group.usda"
    scene.write_text(_SCENE)
    other = tmp_path / "other.usda"
    other.write_text(_OTHER_SCENE)
    stage = Usd.Stage.Open(str(scene))
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        assert _render(adapter) is not None
        adapter.notify_stage_changed(_rename(stage, "/World/Group", "/World/Group2"))
        assert _render(adapter) is None
        adapter.notify_stage_changed(_rename(stage, "/World/Group2", "/World/Group3"))

        # The load waits for the step that still runs, as every renderer
        # mutation does. The kept edit of the old scene is not sent: sent to
        # the new scene, its path would be missing there and reload it again.
        adapter.load_stage(Usd.Stage.Open(str(other)))
        assert not adapter.scene_update_pending()
        assert _render(adapter) is not None
        assert not adapter.scene_update_pending()
        assert _renderer_value(adapter, "radius", "/World/Ball") == 7.0
    finally:
        adapter.shutdown()


def test_a_kept_edit_that_fails_is_reported_and_the_next_kept_edit_still_reaches_the_renderer(
    tmp_path, monkeypatch, capfd
):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "group.usda"
    scene.write_text(_SCENE)
    stage = Usd.Stage.Open(str(scene))
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        assert _render(adapter) is not None
        adapter.notify_stage_changed(_rename(stage, "/World/Group", "/World/Group2"))
        assert _render(adapter) is None

        failing = ChangeEvent(
            changed_paths=("/World/Group2/Box.size",), resynced_paths=(), event_type=ChangeEventType.INFO_CHANGE
        )
        classify = adapter._stage_change_sync_decision

        def fail_for_the_first_edit(event, *args, **kwargs):
            if event is failing:
                raise RuntimeError("the edit cannot be classified")
            return classify(event, *args, **kwargs)

        monkeypatch.setattr(adapter, "_stage_change_sync_decision", fail_for_the_first_edit)
        adapter.notify_stage_changed(failing)
        adapter.notify_stage_changed(_rename(stage, "/World/Group2", "/World/Group"))

        assert _render_until_current(adapter) is not None
        assert "did not reach the renderer: RuntimeError: the edit cannot be classified" in capfd.readouterr().err
        assert _renderer_value(adapter, "size", "/World/Group/Box") == 40.0
        assert not _renderer_has(adapter, "size", "/World/Group2/Box")
    finally:
        adapter.shutdown()


def test_viewport_input_while_the_renderer_builds_the_scene_again_waits_for_nothing_and_takes_effect_after(
    tmp_path, monkeypatch
):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "group.usda"
    scene.write_text(_SCENE)
    stage = Usd.Stage.Open(str(scene))
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        assert _render(adapter) is not None
        adapter.notify_stage_changed(_rename(stage, "/World/Group", "/World/Group2"))
        assert _render(adapter) is None

        # Every renderer call would wait for the rebuild step: record whether
        # one comes while the renderer still builds the scene again.
        calls = []
        renderer = adapter._renderer
        for name in ("enqueue_pick_query", "write_attribute"):
            def spy(*args, _call=getattr(renderer, name), _name=name, **kwargs):
                paths = tuple(kwargs.get("prim_paths") or ())
                calls.append((_name, adapter.scene_update_pending(), paths))
                return _call(*args, **kwargs)

            monkeypatch.setattr(renderer, name, spy)

        first, newest = [], []
        adapter.pick(0.0, 0.0, lambda path, point: first.append(path), "viewport_click")
        adapter.pick(0.0, 0.0, lambda path, point: newest.append(path), "viewport_click")
        assert adapter.set_live_local_transform("/World/Group2/Box", _MOVED) is False
        adapter.clear_live_local_transforms(["/World/Group2/Box"])
        assert calls == []

        assert _render_until_current(adapter) is not None
        for _ in range(3):
            if newest:
                break
            _render(adapter)
        assert newest == ["/World/Group2/Box"]
        assert first == []
        assert ("enqueue_pick_query", False, ()) in calls
        # The restore of the declined preview reaches the renderer after the rebuild.
        assert ("write_attribute", False, ("/World/Group2/Box",)) in calls
        assert all(not pending for _name, pending, _paths in calls), calls
    finally:
        adapter.shutdown()


def test_a_viewport_pick_kept_during_a_rebuild_selects_nothing_in_the_next_document(tmp_path):
    """Review of #854: a click kept during a rebuild selected a prim of the next document.

    Two clicks in the viewport while the renderer built the scene again after
    a rename, then File > Recent Files opened another file before the end:
    the kept clicks were sent against the new document and selected its
    prim. They belong to the document of the click, so they are misses.
    """

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "group.usda"
    scene.write_text(_SCENE)
    other = tmp_path / "other.usda"
    other.write_text(_OTHER_SCENE)
    stage = Usd.Stage.Open(str(scene))
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        assert _render(adapter) is not None
        adapter.notify_stage_changed(_rename(stage, "/World/Group", "/World/Group2"))
        assert _render(adapter) is None

        # The center of the view shows the box in this document and the ball
        # in the other one.
        point, rect = [], []
        adapter.pick(0.0, 0.0, lambda path, world: point.append(path), "viewport_click")
        adapter.pick_rect(-0.5, -0.5, 0.5, 0.5, lambda paths: rect.append(list(paths)))
        assert point == [] and rect == []

        adapter.load_stage(Usd.Stage.Open(str(other)))
        assert point == [None]
        assert rect == [[]]
        assert _render_until_current(adapter) is not None
        for _ in range(3):
            _render(adapter)
        assert point == [None]
        assert rect == [[]]

        # A click in the new document selects its ball: the misses above are
        # not a pick that cannot hit.
        hits = []
        adapter.pick(0.0, 0.0, lambda path, world: hits.append(path), "viewport_click")
        for _ in range(5):
            if hits:
                break
            _render(adapter)
        assert hits == ["/World/Ball"]
    finally:
        adapter.shutdown()


def test_shutdown_answers_a_kept_pick_as_a_miss_and_waits_for_the_rebuild_at_most_its_time_limit(
    tmp_path, monkeypatch, caplog
):
    """Review of #854: the wait for the rebuild step at shutdown had no time limit.

    The step cannot be cancelled, and the renderer must not be released while
    it runs. When the limit runs out, shutdown reports the step, keeps the
    renderer and raises, so that the application exit fails. A later shutdown
    does not wait again and completes when the step has ended. A click kept
    during the step gets a miss at shutdown: its callback was never called.
    """

    from ovui_data_adapters.openusd import OvRtxRendererAdapter
    from ovui_data_adapters.openusd import renderer_adapter

    scene = tmp_path / "group.usda"
    scene.write_text(_SCENE)
    stage = Usd.Stage.Open(str(scene))
    adapter = OvRtxRendererAdapter()
    released = False
    try:
        adapter.load_stage(stage)
        assert _render(adapter) is not None
        adapter.notify_stage_changed(_rename(stage, "/World/Group", "/World/Group2"))
        assert _render(adapter) is None
        point = []
        adapter.pick(0.0, 0.0, lambda path, world: point.append(path), "viewport_click")

        # A limit of 0 s runs out while the step still runs (it takes about 0.1 s).
        monkeypatch.setattr(renderer_adapter, "_REBUILD_STEP_SHUTDOWN_TIMEOUT_S", 0.0, raising=False)
        with pytest.raises(BackgroundTaskStuckError, match="did not end in 0 s at shutdown"):
            adapter.shutdown()
        assert "did not end in 0 s at shutdown" in caplog.text
        assert point == [None]
        assert adapter.scene_update_pending()

        deadline = time.monotonic() + 300.0
        while True:
            started = time.monotonic()
            try:
                adapter.shutdown()
                break
            except BackgroundTaskStuckError:
                assert time.monotonic() - started < 1.0, "a later shutdown waited again"
                assert time.monotonic() < deadline, "the renderer did not finish building the scene"
                time.sleep(0.01)
        released = True
        assert not adapter.scene_update_pending()
        assert point == [None]
    finally:
        if not released:
            monkeypatch.setattr(renderer_adapter, "_REBUILD_STEP_SHUTDOWN_TIMEOUT_S", 300.0, raising=False)
            adapter.shutdown()


def test_with_native_frame_pacing_a_rename_keeps_the_session_paused_until_the_scene_is_built(
    tmp_path, monkeypatch
):
    """Review of #854: with native frame pacing, the viewport was black during the rebuild.

    The rename stopped the native session, which puts a black image in the
    viewport until a new picture comes, and the rebuild takes many seconds.
    Now the session stays paused, so its presenter keeps the last picture.
    After the step, the viewport's lens is written (the reload gave the
    session camera its default lens), and then the same session renders
    the new scene: no stop, no restart, no synchronous step.
    """

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "group.usda"
    scene.write_text(_SCENE)
    stage = Usd.Stage.Open(str(scene))
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        assert _render(adapter) is not None

        # From now on a native session presents the viewport.
        native = _NativePacingRecorder()
        monkeypatch.setattr(OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: native))
        adapter._frame_pacing_provider = object()
        adapter._frame_pacing_token = 1
        adapter._frame_pacing_size = (64, 32)
        adapter._frame_pacing_projection = _PROJECTION.copy()
        adapter._frame_pacing_camera_path = adapter._runtime_camera_path()
        adapter._frame_pacing_needs_sync_step = False
        assert _render(adapter) is None
        assert native.calls == ["publish"]
        native.calls.clear()

        steps, lens = [], []
        renderer = adapter._renderer
        monkeypatch.setattr(
            renderer, "step", lambda *args, _step=renderer.step, **kwargs: steps.append(1) or _step(*args, **kwargs)
        )
        push = adapter._push_camera_intrinsics
        monkeypatch.setattr(
            adapter, "_push_camera_intrinsics", lambda proj, path: lens.append(list(native.calls)) or push(proj, path)
        )

        # The edit and the reload park the render worker (a pause of a paused
        # session does nothing); nothing stops or resumes the session while
        # the renderer builds the scene again.
        adapter.notify_stage_changed(_rename(stage, "/World/Group", "/World/Group2"))
        assert native.calls and set(native.calls) == {"pause"}
        assert adapter.scene_update_pending()
        deadline = time.monotonic() + 300.0
        while True:
            assert time.monotonic() < deadline, "the renderer did not finish building the scene"
            assert _render(adapter) is None
            if not adapter.scene_update_pending():
                break
            assert set(native.calls) == {"pause"}
            time.sleep(0.01)

        # The frame that takes the end of the step writes the lens and then
        # resumes the same session.
        resumed = native.calls.index("resume")
        assert set(native.calls[:resumed]) == {"pause"}
        assert native.calls[resumed:] == ["resume", "publish"]
        assert lens and all(set(calls) == {"pause"} for calls in lens), lens
        assert steps == []
        assert _renderer_value(adapter, "size", "/World/Group2/Box") == 40.0
    finally:
        adapter.shutdown()


def test_a_rebuild_step_that_ovrtx_fails_is_reported_and_the_next_frame_renders_the_scene(
    tmp_path, monkeypatch
):
    """Review of #854: a real failure of the rebuild step was not tried.

    The rebuild step after a rename is started for a render product that does
    not exist, so ovrtx fails the step. The failure is reported as a failed
    step, the viewport no longer waits for the step, and the next frame
    renders the scene with the rename.
    """

    from ovui_data_adapters.common import render_diagnostics
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "group.usda"
    scene.write_text(_SCENE)
    stage = Usd.Stage.Open(str(scene))
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(stage)
        assert _render(adapter) is not None
        adapter.notify_stage_changed(_rename(stage, "/World/Group", "/World/Group2"))
        products = adapter._render_products_for_step
        monkeypatch.setattr(adapter, "_render_products_for_step", lambda: ["/Render/DoesNotExist"])
        assert _render(adapter) is None
        assert adapter.scene_update_pending()
        monkeypatch.setattr(adapter, "_render_products_for_step", products)

        deadline = time.monotonic() + 300.0
        while adapter.scene_update_pending():
            assert time.monotonic() < deadline, "the failed step was never taken"
            _render(adapter)
            time.sleep(0.01)
        messages = [event["message"] for event in render_diagnostics.get_render_diagnostics().events()]
        assert any(message.startswith("Renderer.step failed: RuntimeError:") for message in messages), messages

        assert _render(adapter) is not None
        assert _renderer_value(adapter, "size", "/World/Group2/Box") == 40.0
    finally:
        adapter.shutdown()
