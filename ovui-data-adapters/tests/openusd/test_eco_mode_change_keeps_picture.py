# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""An Eco Mode change gives the renderer the value and keeps the picture.

ovrtx keeps memory for each frame that it renders. Undo and Redo of Render
Settings > Reset Settings clear and check Eco Mode, and each change rendered
the settle frames again. Eco Mode only says when the renderer stops refining a
still picture, and under the ``on_change`` policy the viewport stops a still
picture after its settle frames anyway. These runtime-free tests check:

- a change that keeps the effective value (the reset of a render mode that the
  toolbar set to its default) keeps the picture and is not written again;
- the choice: an Eco Mode change keeps the picture, unless Eco Mode stopped the
  picture on screen early and the change lets the renderer refine it further;
  early means before the settle frames and before the declared default frame
  limit, after which the renderer itself treats a still picture as final;
  other settings, restarts and unknown values never keep it;
- the settings event says that it keeps the picture only when every change in
  it does, and only while its callbacks run;
- the USD notice of the written setting is known by its path, for the adapter
  and the viewport in either order;
- the render worker paused for such a write resumes without rendering, unless
  another pause before the resume needs a new picture.

The real renderer test is in test_render_setting_change_keeps_renderer_real_renderer.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ovui_data_adapters.common.render_settings import RenderSettingRequirement
from ovui_data_adapters.openusd import renderer_adapter as mod
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

ECO_MODE = "omni:rtx:rt:ecoMode:enabled"
FRAME_LIMIT = "omni:rtx:rt:ecoMode:maxFramesWithoutChange"
PRODUCT = "/OvGearSession/Render/Viewport"
SETTLE = 512


def _descriptor(attr_name, current, requirement=RenderSettingRequirement.WARMUP):
    return SimpleNamespace(
        setting_id=f"{PRODUCT}:{attr_name}",
        metadata={"attr_name": attr_name, "render_product_path": PRODUCT},
        requirement=requirement,
        value_state=SimpleNamespace(current_value=current),
    )


class _Choice:
    """An adapter with the Eco Mode values in USD and a frame counter that the test moves."""

    def __init__(self, enabled=True, limit=500, policy=("on_change", SETTLE), final=None):
        self.usd = {ECO_MODE: enabled, FRAME_LIMIT: limit}
        self.frames = 0
        adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
        adapter._still_frame_policy = policy
        adapter._rendered_since_load = True
        adapter.read_render_setting_value = lambda name, **_kw: self.usd.get(name)
        adapter._rendered_frames_marker = lambda: self.frames
        # The declared default frame limit; None: the schema does not declare it.
        adapter._eco_mode_final_frames = lambda: final
        self.adapter = adapter

    def change(self, attr_name, value, **kwargs):
        """The choice for one change, then the new value in USD (as apply and reset author it)."""
        keeps = self.adapter._render_setting_change_keeps_picture(
            _descriptor(attr_name, self.usd[attr_name], **kwargs), value
        )
        self.usd[attr_name] = value
        return keeps


def test_eco_mode_changes_keep_a_picture_that_the_settle_frames_refined():
    choice = _Choice()
    # The picture on screen was refined with Eco Mode on and its default limit
    # of 500 frames, below the 512 settle frames: Eco Mode off refines it.
    assert choice.change(ECO_MODE, False) is False
    choice.frames += SETTLE + 1
    # Refined with Eco Mode off: nothing is left to refine, in either direction.
    for value in (True, False) * 30:
        assert choice.change(ECO_MODE, value) is True


def test_with_the_declared_default_limit_eco_mode_changes_keep_the_picture_at_any_pace():
    # The renderer treats a picture of 500 still frames as final. Settle frames
    # of an earlier change may still run at the next Undo or Redo.
    choice = _Choice(final=500)
    for value in (False, True) * 30:
        choice.frames += 100
        assert choice.change(ECO_MODE, value) is True


def test_a_picture_that_eco_mode_stopped_early_is_refined_when_eco_mode_goes_off():
    choice = _Choice(limit=10, final=500)
    assert choice.change(ECO_MODE, False) is False
    choice.frames += SETTLE
    assert choice.change(ECO_MODE, True) is True
    assert choice.change(ECO_MODE, False) is True


def test_the_declared_default_limit_comes_from_the_schema(monkeypatch):
    spec = {"attr_name": FRAME_LIMIT, "usd_type": "uint", "default": 500}
    monkeypatch.setattr(mod, "_RENDER_SETTINGS_BUILTIN_SPEC_INDEX", {FRAME_LIMIT: spec})
    assert OvRtxRendererAdapter._eco_mode_final_frames() == 500
    monkeypatch.setattr(mod, "_RENDER_SETTINGS_BUILTIN_SPEC_INDEX", {})
    assert OvRtxRendererAdapter._eco_mode_final_frames() is None


def test_a_picture_rendered_with_eco_mode_on_is_refined_when_eco_mode_goes_off():
    choice = _Choice(enabled=False)
    assert choice.change(ECO_MODE, True) is True
    # A camera move renders a new picture with Eco Mode on.
    choice.frames += 20
    assert choice.change(ECO_MODE, False) is False


def test_a_frame_limit_change_refines_only_a_picture_that_eco_mode_stopped():
    choice = _Choice(limit=600)
    assert choice.change(FRAME_LIMIT, 2) is True
    choice.frames += 3
    assert choice.change(FRAME_LIMIT, 100) is False
    choice.frames += 101
    assert choice.change(FRAME_LIMIT, 50) is True
    # The picture of 100 frames is still on screen: a limit up to 100 refines nothing.
    assert choice.change(FRAME_LIMIT, 100) is True
    assert choice.change(FRAME_LIMIT, 101) is False


def test_with_eco_mode_off_the_frame_limit_keeps_the_picture():
    choice = _Choice(enabled=False)
    assert choice.change(FRAME_LIMIT, 2) is True
    assert choice.change(FRAME_LIMIT, 1000) is True


def test_continuous_rendering_keeps_the_picture():
    choice = _Choice(policy=("continuous", 0))
    assert choice.change(ECO_MODE, False) is True


@pytest.mark.parametrize(
    "case",
    ["other setting", "renderer restart", "nothing rendered", "unknown value", "unknown frames"],
)
def test_other_changes_render_again(case):
    choice = _Choice()
    attr_name, requirement = ECO_MODE, RenderSettingRequirement.WARMUP
    if case == "other setting":
        attr_name = "omni:rtx:post:tonemap:enableSrgbToGamma"
        choice.usd[attr_name] = True
    elif case == "renderer restart":
        requirement = RenderSettingRequirement.RENDERER_RESTART
    elif case == "nothing rendered":
        choice.adapter._rendered_since_load = False
    elif case == "unknown value":
        choice.usd[FRAME_LIMIT] = None
    elif case == "unknown frames":
        # Without a frame count, the picture counts as refined with the Eco Mode before the change.
        choice.adapter._rendered_frames_marker = lambda: None
        assert choice.change(ECO_MODE, False) is False
        choice.frames += SETTLE
        assert choice.change(ECO_MODE, True) is True
        assert choice.change(ECO_MODE, False) is False
        return
    assert choice.change(attr_name, False, requirement=requirement) is False


def _publisher():
    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    adapter._frame_service_active = False
    snapshots = iter(range(1_000_000))
    adapter._render_settings_state_snapshot = lambda catalog: next(snapshots)
    seen = []
    adapter.subscribe_render_settings_changes(
        lambda: seen.append(adapter.render_settings_change_keeps_picture())
    )
    return adapter, seen


def test_the_settings_event_keeps_the_picture_only_when_every_change_does():
    adapter, seen = _publisher()
    adapter._publish_render_settings_change(keeps_picture=True)
    adapter._publish_render_settings_change()
    with adapter.render_setting_batch():
        adapter._publish_render_settings_change(keeps_picture=True)
        adapter._publish_render_settings_change(keeps_picture=True)
    with adapter.render_setting_batch():
        adapter._publish_render_settings_change(keeps_picture=True)
        adapter._publish_render_settings_change()
    assert seen == [True, False, True, False]
    # Outside a callback the answer is no.
    assert adapter.render_settings_change_keeps_picture() is False


def test_the_notice_of_the_written_setting_is_known_in_either_order():
    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    adapter._stage = object()
    adapter._renderer = object()
    calls = []
    adapter._drop_kept_render_settings_catalogs = lambda: None
    adapter._stop_native_frame_pacing = lambda reason, **kw: calls.append(("pause", kw))
    adapter._publish_render_settings_change = lambda catalog=None, **kw: calls.append(("publish", kw))
    written = f"{PRODUCT}.{ECO_MODE}"
    notice = SimpleNamespace(changed_paths=(written,), resynced_paths=())
    other = SimpleNamespace(changed_paths=(written, "/World/Cube.size"), resynced_paths=())

    adapter._kept_picture_setting_paths = {written}
    assert adapter.stage_change_keeps_picture(other) is False
    assert adapter.stage_change_keeps_picture(notice) is True  # the viewport first
    adapter.notify_stage_changed(notice)
    assert adapter.stage_change_keeps_picture(notice) is True  # the viewport after the adapter
    assert calls == [
        ("pause", {"pause_render": True, "keep_picture": True}),
        ("publish", {"keeps_picture": True}),
    ]
    # A later notice of the same attribute is another change.
    assert adapter.stage_change_keeps_picture(
        SimpleNamespace(changed_paths=(written,), resynced_paths=())
    ) is False


class _Native:
    """The native coordinator's pause and resume bindings, recording each call."""

    def __init__(self, render_option=True):
        self.calls = []
        self.render_option = render_option

    def _native_frame_pacing_pause_render(self, token):
        self.calls.append("pause")
        return True

    def _native_frame_pacing_resume_render(self, token, **kwargs):
        if kwargs and not self.render_option:
            raise TypeError("incompatible function arguments")
        self.calls.append(("resume", kwargs.get("render", True)))
        return True


def _paused_adapter(monkeypatch, native):
    monkeypatch.setattr(
        OvRtxRendererAdapter, "_frame_pacing_bindings", staticmethod(lambda: native)
    )
    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    adapter._frame_pacing_token = 1
    adapter._frame_pacing_render_paused = False
    adapter._frame_pacing_first_frame_native = False
    adapter._still_frame_requested = False
    return adapter


def test_a_pause_that_keeps_the_picture_resumes_without_rendering(monkeypatch):
    native = _Native()
    adapter = _paused_adapter(monkeypatch, native)
    adapter._stop_native_frame_pacing("setting", pause_render=True, keep_picture=True)
    adapter._stop_native_frame_pacing("notice", pause_render=True, keep_picture=True)
    assert adapter._still_frame_requested is False
    assert adapter._resume_native_render(native) is True
    # Any pause that needs a new picture makes the resume render.
    adapter._stop_native_frame_pacing("setting", pause_render=True, keep_picture=True)
    adapter._stop_native_frame_pacing("camera", pause_render=True)
    assert adapter._still_frame_requested is True
    assert adapter._resume_native_render(native) is True
    assert native.calls == ["pause", "pause", ("resume", False), "pause", "pause", ("resume", True)]


def test_an_ovui_without_the_resume_option_renders_at_the_resume(monkeypatch):
    native = _Native(render_option=False)
    adapter = _paused_adapter(monkeypatch, native)
    adapter._stop_native_frame_pacing("setting", pause_render=True, keep_picture=True)
    assert adapter._resume_native_render(native) is True
    assert native.calls == ["pause", ("resume", True)]


def test_without_a_session_a_change_that_keeps_the_picture_asks_for_no_step(monkeypatch):
    adapter = _paused_adapter(monkeypatch, _Native())
    adapter._frame_pacing_token = 0
    adapter._frame_pacing_needs_sync_step = False
    adapter._stop_native_frame_pacing("setting", pause_render=True, keep_picture=True)
    assert adapter._still_frame_requested is False
    assert adapter._frame_pacing_needs_sync_step is False
    adapter._stop_native_frame_pacing("edit")
    assert adapter._still_frame_requested is True


RENDER_MODE = "omni:rtx:rendermode"


def test_a_change_that_keeps_the_effective_value_keeps_the_picture():
    # The toolbar authors the render mode; when it ends on the default, the
    # reset of Reset Settings and its Undo keep the effective value.
    adapter = _Choice().adapter
    restart = RenderSettingRequirement.RENDERER_RESTART
    same = _descriptor(RENDER_MODE, "RealTimePathTracing", requirement=restart)
    assert adapter._render_setting_change_keeps_picture(same, "RealTimePathTracing") is True
    assert adapter._render_setting_change_keeps_picture(same, "PathTracing") is False
    flag = _descriptor("omni:rtx:post:tonemap:enableSrgbToGamma", True)
    assert adapter._render_setting_change_keeps_picture(flag, True) is True
    assert adapter._render_setting_change_keeps_picture(flag, 1) is False
    assert adapter._render_setting_change_keeps_picture(_descriptor(RENDER_MODE, None), None) is False


def test_an_unchanged_value_is_not_written_again(monkeypatch):
    adapter = _Choice(final=500).adapter
    calls = []

    class _Renderer:
        def write_attribute(self, **kwargs):
            calls.append(("write", kwargs["attribute_name"]))

    adapter._renderer = _Renderer()
    adapter._render_setting_owner_stage_for = lambda descriptor: object()
    adapter._stop_native_frame_pacing = lambda reason, **kw: calls.append(("pause", kw))
    adapter._renderer_reads_render_settings_from_fabric = lambda: True
    adapter._render_setting_value_to_write_payload = lambda descriptor, value: value
    adapter._note_published_render_setting = lambda descriptor: None
    monkeypatch.setattr(mod, "_render_setting_owner_path", lambda stage, descriptor: PRODUCT)
    restart = RenderSettingRequirement.RENDERER_RESTART
    same = _descriptor(RENDER_MODE, "RealTimePathTracing", requirement=restart)
    assert adapter._write_render_setting_keeping_picture(same, "RealTimePathTracing") is True
    assert calls == []
    assert adapter._write_render_setting_keeping_picture(_descriptor(ECO_MODE, True), False) is True
    assert calls == [("pause", {"pause_render": True, "keep_picture": True}), ("write", ECO_MODE)]
    # The USD notice of one Undo names both attributes: both are known.
    assert adapter._kept_picture_setting_paths == {f"{PRODUCT}.{RENDER_MODE}", f"{PRODUCT}.{ECO_MODE}"}
