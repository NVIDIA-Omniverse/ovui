# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A still viewer under native frame pacing does not render again.

ovrtx keeps memory on every step. A viewer that rendered its unchanged
picture at full frame rate grew by megabytes a minute while nobody used it.
The viewport now gives a native frame-pacing session the ``on_change`` render
policy by default: the native render worker renders a change (camera, size,
stage edit, render settings, new scene), then the settle frames, and keeps the
picture on screen. Path tracing gathers samples over still frames, so it
settles over its sample target. Without native pacing the renderer adapter
applies the same policy to its synchronous steps; the viewport gives it the
policy, forwards render requests and does not upload the picture that the
adapter says it kept. Any other frame is shown, also one array that an adapter
fills again. The policy follows the mode of the active render product.

A stage change that the renderer says cannot change its picture, and a
selection that cannot change its outline, ask for no render.

A render setting that the picture does not show (Eco Mode) renders no new
frames: the viewport asks no render for its settings event or its USD notice
when the renderer says that the change keeps the picture.
"""

from unittest.mock import MagicMock

import numpy as np
import omni.ui as ui
import pytest
from ovui_data_adapters.common.adapters import ChangeEvent, ChangeEventType, RendererAdapter
from ovui_widgets.common.settings import Settings
from ovui_widgets.viewport.viewport_widget import ViewportWidget

RENDER_POLICY_SETTING_KEY = "app.renderer.renderPolicy"
RENDER_SETTLE_FRAMES_SETTING_KEY = "app.renderer.renderSettleFrames"
# The real-time renderer needs about 500 frames for its sharp picture.
SETTLE_FRAMES = 512
TOKEN = 7


@pytest.fixture
def settings():
    store = Settings()
    Settings.set_instance(store)
    yield store
    Settings.set_instance(None)


@pytest.fixture
def native(monkeypatch):
    """Record what the viewport gives the native frame-pacing session."""
    calls = {"policy": [], "render": []}
    monkeypatch.setattr(
        ui._ui,
        "_native_frame_pacing_set_render_policy",
        lambda token, policy, settle: calls["policy"].append((token, policy, settle)) or True,
        raising=False,
    )
    monkeypatch.setattr(
        ui._ui,
        "_native_frame_pacing_request_render",
        lambda token: calls["render"].append(token) or True,
        raising=False,
    )
    return calls


def _renderer(render_settings=None, token=TOKEN):
    """A renderer that owns a native pacing session and reports render settings."""
    renderer = MagicMock()
    renderer._frame_pacing_token = token
    renderer.render_frame.side_effect = lambda w, h, _view, _proj: np.zeros(
        (int(h), int(w), 4), dtype=np.uint8
    )
    renderer.values = dict(render_settings or {})
    renderer.read_render_setting_value.side_effect = (
        lambda name, **_kw: renderer.values.get(name)
    )
    return renderer


def _viewport(renderer):
    vp = ViewportWidget(services=None, renderer=renderer)
    image = MagicMock()
    image.visible = True
    image.computed_width = 320
    image.computed_height = 200
    vp._image = image
    return vp


def test_a_native_pacing_session_gets_the_on_change_policy_by_default(settings, native):
    vp = _viewport(_renderer())
    try:
        vp._apply_render_policy()
        vp._apply_render_policy()
        assert native["policy"] == [(TOKEN, "on_change", SETTLE_FRAMES)]
    finally:
        vp.destroy()


def test_a_changed_policy_or_settle_count_is_given_again(settings, native):
    vp = _viewport(_renderer())
    try:
        vp._apply_render_policy()
        settings.set(RENDER_SETTLE_FRAMES_SETTING_KEY, 3)
        vp._apply_render_policy()
        settings.set(RENDER_POLICY_SETTING_KEY, "continuous")
        vp._apply_render_policy()
        assert native["policy"] == [
            (TOKEN, "on_change", SETTLE_FRAMES),
            (TOKEN, "on_change", 3),
            (TOKEN, "continuous", 3),
        ]
    finally:
        vp.destroy()


def test_the_native_session_gets_one_settle_frame_at_least(settings, native):
    # The native render worker shows a step only when it submits the next one:
    # with zero settle frames the newest camera would never be shown.
    settings.set(RENDER_SETTLE_FRAMES_SETTING_KEY, 0)
    renderer = _renderer()
    vp = _viewport(renderer)
    try:
        vp._apply_render_policy()
        settings.set(RENDER_POLICY_SETTING_KEY, "continuous")
        vp._apply_render_policy()
        assert native["policy"] == [(TOKEN, "on_change", 1), (TOKEN, "continuous", 0)]
        # The synchronous steps of the adapter keep the setting.
        assert [c.args for c in renderer.set_render_policy.call_args_list] == [
            ("on_change", 0), ("continuous", 0),
        ]
    finally:
        vp.destroy()


def test_path_tracing_settles_over_its_sample_target(settings, native):
    renderer = _renderer(
        {"omni:rtx:rendermode": "PathTracing", "omni:rtx:pt:samplesPerPixel": 32}
    )
    vp = _viewport(renderer)
    try:
        vp._apply_render_policy()
        assert native["policy"] == [(TOKEN, "on_change", 32)]
    finally:
        vp.destroy()


def test_path_tracing_without_a_sample_target_renders_continuously(settings, native):
    renderer = _renderer(
        {"omni:rtx:rendermode": "PathTracing", "omni:rtx:pt:samplesPerPixel": 0}
    )
    vp = _viewport(renderer)
    try:
        vp._apply_render_policy()
        assert native["policy"] == [(TOKEN, "continuous", SETTLE_FRAMES)]
    finally:
        vp.destroy()


def test_a_render_settings_change_renders_again_and_reads_the_render_mode(settings, native):
    renderer = _renderer()
    vp = _viewport(renderer)
    try:
        vp._apply_render_policy()
        renderer.values.update(
            {"omni:rtx:rendermode": "PathTracing", "omni:rtx:pt:samplesPerPixel": 64}
        )
        changed = renderer.subscribe_render_settings_changes.call_args.args[0]
        changed()
        assert native["render"] == [TOKEN]
        vp._apply_render_policy()
        assert native["policy"][-1] == (TOKEN, "on_change", 64)
    finally:
        vp.destroy()


def test_a_render_settings_change_that_keeps_the_picture_renders_nothing(settings, native):
    renderer = _renderer()
    renderer.render_settings_change_keeps_picture.return_value = True
    vp = _viewport(renderer)
    try:
        requests = renderer.request_render.call_count
        changed = renderer.subscribe_render_settings_changes.call_args.args[0]
        changed()
        assert native["render"] == []
        assert renderer.request_render.call_count == requests
    finally:
        vp.destroy()


def test_the_notice_of_a_setting_that_keeps_the_picture_renders_nothing(settings, native):
    eco_mode = "/OvGearSession/Render/Viewport.omni:rtx:rt:ecoMode:enabled"
    renderer = _renderer()
    renderer.stage_change_keeps_picture.side_effect = (
        lambda event: event.changed_paths == (eco_mode,)
    )
    vp = _viewport(renderer)
    try:
        vp.notify_stage_changed(ChangeEvent((eco_mode,), (), ChangeEventType.INFO_CHANGE))
        assert native["render"] == []
        vp.notify_stage_changed(ChangeEvent(("/World/Cube.size",), (), ChangeEventType.INFO_CHANGE))
        assert native["render"] == [TOKEN]
    finally:
        vp.destroy()


def test_a_stage_edit_and_a_new_scene_render_again(settings, native):
    vp = _viewport(_renderer())
    try:
        vp.notify_stage_changed(
            ChangeEvent(("/World/Cube.size",), (), ChangeEventType.INFO_CHANGE)
        )
        vp.attach_stage(
            transform_adapter=MagicMock(),
            stage_adapter=MagicMock(),
            undo_manager=MagicMock(),
        )
        assert native["render"] == [TOKEN, TOKEN]
    finally:
        vp.destroy()


def test_the_renderer_gets_the_policy_and_the_render_requests(settings):
    renderer = _renderer(token=0)
    vp = _viewport(renderer)
    try:
        vp.render(1.0 / 60.0)
        vp.render(1.0 / 60.0)
        renderer.set_render_policy.assert_called_once_with("on_change", SETTLE_FRAMES)
        settings.set(RENDER_POLICY_SETTING_KEY, "continuous")
        vp.render(1.0 / 60.0)
        renderer.set_render_policy.assert_called_with("continuous", SETTLE_FRAMES)

        requests = renderer.request_render.call_count
        vp.notify_stage_changed(
            ChangeEvent(("/World/Cube.size",), (), ChangeEventType.INFO_CHANGE)
        )
        assert renderer.request_render.call_count == requests + 1
    finally:
        vp.destroy()


def test_a_stage_change_that_keeps_the_picture_does_not_render(settings, native):
    # Create > Xform and its Undo: an Xform draws nothing.
    renderer = _renderer()
    renderer.stage_change_keeps_picture.return_value = True
    vp = _viewport(renderer)
    try:
        event = ChangeEvent((), ("/World/Xform",), ChangeEventType.RESYNC)
        vp.notify_stage_changed(event)
        assert native["render"] == []
        renderer.stage_change_keeps_picture.assert_called_once_with(event)
        # The renderer adapter still gets the change.
        renderer.notify_stage_changed.assert_called_once_with(event)

        renderer.stage_change_keeps_picture.return_value = False
        vp.notify_stage_changed(event)
        assert native["render"] == [TOKEN]
    finally:
        vp.destroy()


def test_a_stage_change_renders_when_the_renderer_cannot_tell(settings):
    renderer = _renderer(token=0)
    renderer.stage_change_keeps_picture.side_effect = RuntimeError("no answer")
    vp = _viewport(renderer)
    try:
        requests = renderer.request_render.call_count
        vp.notify_stage_changed(ChangeEvent((), ("/World/Xform",), ChangeEventType.RESYNC))
        assert renderer.request_render.call_count == requests + 1
    finally:
        vp.destroy()


@pytest.mark.parametrize("outline_may_change, renders", [(False, 0), (True, 1), (None, 1)])
def test_a_selection_renders_unless_the_outline_cannot_change(settings, outline_may_change, renders):
    from types import SimpleNamespace

    renderer = _renderer(token=0)
    renderer.set_selection_highlight.return_value = outline_may_change
    vp = _viewport(renderer)
    try:
        requests = renderer.request_render.call_count
        snapshot = SimpleNamespace(paths=lambda: ["/World/Xform"])
        vp._on_bus_selection_changed(SimpleNamespace(snapshot=snapshot))
        renderer.set_selection_highlight.assert_called_once_with(["/World/Xform"])
        assert renderer.request_render.call_count == requests + renders
    finally:
        vp.destroy()


def test_the_same_output_again_is_not_uploaded(settings, monkeypatch):
    still = np.zeros((200, 320, 4), dtype=np.uint8)
    renderer = _renderer(token=0)
    renderer.render_frame.side_effect = lambda *_args: still
    renderer.last_frame_unchanged.return_value = True  # The kept picture of a still camera.
    completions = []
    monkeypatch.setattr(
        ui, "_record_synchronous_renderer_completion", lambda: completions.append(1), raising=False
    )
    vp = _viewport(renderer)
    uploads = []
    monkeypatch.setattr(vp._bridge, "update", lambda frame: uploads.append(frame) or True)
    try:
        for _ in range(5):
            vp.render(1.0 / 60.0)
        assert renderer.render_frame.call_count == 5
        assert len(uploads) == 1
        assert len(completions) == 1
        assert vp.get_presentation_image() is not None
    finally:
        vp.destroy()


class _OneBufferRenderer(RendererAdapter):
    """A renderer adapter that renders each picture into one array that it keeps.

    The public adapter description asks only for an RGBA array, not for a new
    one each time.
    """

    def __init__(self):
        self.buffer = np.zeros((200, 320, 4), dtype=np.uint8)
        self.frames = 0

    def render_frame(self, width, height, view_matrix, proj_matrix):
        self.frames += 1
        self.buffer[...] = self.frames
        return self.buffer

    def load_stage(self, stage):
        return None

    def set_resolution(self, width, height):
        return None

    def pick(self, *_args, **_kwargs):
        return None

    def pick_rect(self, *_args, **_kwargs):
        return None

    def cancel_pick(self, *_args, **_kwargs):
        return None

    def set_selection_highlight(self, *_args, **_kwargs):
        return None

    def shutdown(self):
        return None


@pytest.mark.parametrize("policy", ["on_change", "continuous"])
def test_an_adapter_that_reuses_its_array_shows_every_frame(settings, monkeypatch, policy):
    settings.set(RENDER_POLICY_SETTING_KEY, policy)
    renderer = _OneBufferRenderer()
    vp = _viewport(renderer)
    uploads = []
    monkeypatch.setattr(vp._bridge, "update", lambda frame: uploads.append(int(frame[0, 0, 0])) or True)
    try:
        for _ in range(5):
            vp.render(1.0 / 60.0)
        assert uploads == [1, 2, 3, 4, 5]
    finally:
        vp.destroy()


def test_a_render_product_switch_follows_the_mode_and_samples_of_the_product(settings, native):
    products = {
        "/Render/PathTraced": {
            "omni:rtx:rendermode": "PathTracing",
            "omni:rtx:pt:samplesPerPixel": 256,
        },
        "/Render/RealTime": {"omni:rtx:rendermode": "RealTimePathTracing"},
    }
    renderer = _renderer()
    renderer.active = "/Render/PathTraced"
    renderer.get_active_render_product_path.side_effect = lambda: renderer.active
    renderer.read_render_setting_value.side_effect = (
        lambda name, **_kw: products[renderer.active].get(name)
    )
    vp = _viewport(None)
    try:
        assert vp.set_renderer(renderer)  # As the application attaches its renderer.
        vp._apply_render_policy()
        renderer.active = "/Render/RealTime"
        vp._apply_render_policy()
        renderer.active = "/Render/PathTraced"
        vp._apply_render_policy()
        expected = [("on_change", 256), ("on_change", SETTLE_FRAMES), ("on_change", 256)]
        assert native["policy"] == [(TOKEN, *given) for given in expected]
        assert [c.args for c in renderer.set_render_policy.call_args_list] == expected
    finally:
        vp.destroy()


def test_an_unknown_render_policy_is_refused(settings, native):
    settings.set(RENDER_POLICY_SETTING_KEY, "sometimes")
    settings.set(RENDER_SETTLE_FRAMES_SETTING_KEY, -1)
    assert settings.get(RENDER_POLICY_SETTING_KEY, "unset") == "unset"
    assert settings.get(RENDER_SETTLE_FRAMES_SETTING_KEY, "unset") == "unset"
    vp = _viewport(_renderer())
    try:
        vp._apply_render_policy()
        assert native["policy"] == [(TOKEN, "on_change", SETTLE_FRAMES)]
    finally:
        vp.destroy()


def test_the_default_policy_is_not_written_into_the_settings_file(settings, native, tmp_path):
    vp = _viewport(_renderer())
    try:
        vp._apply_render_policy()
    finally:
        vp.destroy()
    path = tmp_path / "settings.json"
    settings.save_to_file(str(path))
    saved = path.read_text()
    assert RENDER_POLICY_SETTING_KEY not in saved
    assert RENDER_SETTLE_FRAMES_SETTING_KEY not in saved
