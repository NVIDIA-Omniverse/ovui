# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A render setting change reaches the renderer with no renderer reset.

Each Undo or Redo of Render Settings > Reset Settings changes a render setting
of the session RenderProduct. Before the fix, each change also reset the
renderer and replaced the session layer. The renderer then built its views and
their DLSS state again, and NVIDIA NGX kept memory for each build, so the app
kept more memory with each repeat.

The loaded renderer reads render settings from Fabric and finds their changes
there, so the live attribute write gives it the value. The test runs the OpenUSD
renderer adapter with the real renderer: a setting change, its reset to the
default and the change again (as Undo, Redo and Undo do) must each change the
rendered picture, with no renderer reset and the same session layer.

The renderer keeps memory for each frame that it renders. In the report, Undo
and Redo toggle Eco Mode, which only says when the renderer stops refining a
still picture: no frame is rendered for it, and the renderer has each value
before it renders again. A picture that Eco Mode stopped before the settle frames is rendered again
when Eco Mode is turned off. The toolbar authors the render mode, which needs a
renderer restart; when it ends on the default, the reset of Reset Settings and
its Undo keep the effective value: no restart and no frame.

A Reset can also change settings that the picture shows, and the render mode.
Undo and Redo then return to settings states whose settled pictures the adapter
has stored: the stored picture is shown with no frame and no restart, and the
renderer gets the settings before it renders again.
"""

from __future__ import annotations

import collections
import gc
import warnings

import numpy as np
import pytest
from ovui_data_adapters.openusd import renderer_adapter
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter
from pxr import Usd

# The render settings schema is process-wide, so the test runs in a process of its own.
pytestmark = [pytest.mark.requires_ovrtx, pytest.mark.own_process]

_SCENE = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 0.01
    upAxis = "Y"
)

def Xform "World"
{
    def Cube "Cube"
    {
        double size = 100
        double3 xformOp:translate = (-120, 50, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }

    def Mesh "Floor"
    {
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
        point3f[] points = [(-500, 0, -500), (-500, 0, 500), (500, 0, 500), (500, 0, -500)]
        normal3f[] normals = [(0, 1, 0), (0, 1, 0), (0, 1, 0), (0, 1, 0)] (
            interpolation = "vertex"
        )
        float3[] extent = [(-500, 0, -500), (500, 0, 500)]
        uniform token subdivisionScheme = "none"
    }
}
"""

#: Tone mapping "SRGB To Gamma Conversion": on by default; off gives a much darker picture.
_SRGB_TO_GAMMA = "omni:rtx:post:tonemap:enableSrgbToGamma"
_RENDER_MODE = "omni:rtx:rendermode"
_ECO_MODE = "omni:rtx:rt:ecoMode:enabled"
_ECO_MODE_FRAME_LIMIT = "omni:rtx:rt:ecoMode:maxFramesWithoutChange"
#: Path tracing renders to this sample target; the viewport makes it the settle frames.
_PATH_TRACING_SAMPLES = "omni:rtx:pt:samplesPerPixel"
_SETTLE_FRAMES = 8
_WIDTH, _HEIGHT = 320, 180
_VIEW = np.array(
    [[1, 0, 0, 0], [0, 0.94, -0.34, 0], [0, 0.34, 0.94, 0], [0, -150, -900, 1.0]]
).T
_PROJECTION = np.array(
    [[1.0, 0, 0, 0], [0, 1.78, 0, 0], [0, 0, -1.0002, -0.20002], [0, 0, -1, 0]]
)


def _brightness(adapter: OvRtxRendererAdapter) -> float:
    """Mean RGB of the picture after the renderer settles on the current settings."""

    frame = None
    for _ in range(60):
        adapter.request_render()
        frame = adapter.render_frame(_WIDTH, _HEIGHT, _VIEW, _PROJECTION)
    assert isinstance(frame, np.ndarray), f"no picture from the renderer: {frame!r}"
    return float(np.asarray(frame)[..., :3].mean())


def _still_picture(adapter: OvRtxRendererAdapter, view: np.ndarray = _VIEW) -> np.ndarray:
    """The picture once the adapter stops stepping the renderer (the ``on_change`` policy)."""

    frame = None
    for _ in range(200):
        frame = adapter.render_frame(_WIDTH, _HEIGHT, view, _PROJECTION)
        if adapter.last_frame_unchanged():
            break
    assert adapter.last_frame_unchanged(), "the adapter did not stop stepping the renderer"
    assert isinstance(frame, np.ndarray), f"no picture from the renderer: {frame!r}"
    return np.array(frame, copy=True)


def _renderer_value(adapter: OvRtxRendererAdapter, attr_name: str, product: str):
    """The value that the renderer has for a setting of ``product``."""

    return np.from_dlpack(adapter._renderer.read_attribute(attr_name, [product])).tolist()[0]


def _object_counts() -> collections.Counter:
    gc.collect()
    return collections.Counter(type(item).__qualname__ for item in gc.get_objects())


def test_a_render_setting_change_and_its_reset_change_the_picture_with_no_renderer_reset(
    tmp_path,
) -> None:
    # The one setting of the test, as the Render Settings schema declares it.
    renderer_adapter.configure_render_settings_schema(
        provider_id="test",
        provider_label="Test",
        public_namespaces=("omni:rtx:",),
        metadata_key="renderSettings",
        group_fallback="rtx",
        group_label_fallback="RTX",
        builtin_specs=(
            {
                "attr_name": _SRGB_TO_GAMMA,
                "usd_type": "bool",
                "value_type": "bool",
                "requirement": "warmup",
                "default": True,
            },
        ),
    )
    scene = tmp_path / "scene.usda"
    scene.write_text(_SCENE)
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        default = _brightness(adapter)
        srgb_to_gamma = next(
            descriptor
            for descriptor in adapter.list_render_settings().settings
            if (descriptor.metadata or {}).get("attr_name") == _SRGB_TO_GAMMA
        )
        renderer = adapter._renderer
        resets = []
        reset = renderer.reset
        renderer.reset = lambda *args, **kwargs: resets.append(1) or reset(*args, **kwargs)
        session = adapter._session_handle

        assert adapter.apply_render_setting(srgb_to_gamma.setting_id, False).accepted
        darker = _brightness(adapter)
        assert adapter.reset_render_setting(srgb_to_gamma.setting_id).accepted
        restored = _brightness(adapter)
        assert adapter.apply_render_setting(srgb_to_gamma.setting_id, False).accepted
        darker_again = _brightness(adapter)

        assert darker < 0.5 * default, (default, darker)
        assert abs(restored - default) < 0.05 * default, (default, restored)
        assert abs(darker_again - darker) < 0.05 * default, (darker, darker_again)
        assert resets == [], "a render setting change reset the renderer"
        assert adapter._session_handle == session, "a render setting change replaced the session layer"

        # More changes and resets keep no Python objects, as many Undo and Redo steps must not.
        # pytest keeps each warning that it records, and the renderer's write call warns that it
        # is deprecated; that record is not memory of the app.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            before = _object_counts()
            for _ in range(20):
                assert adapter.reset_render_setting(srgb_to_gamma.setting_id).accepted
                assert adapter.apply_render_setting(srgb_to_gamma.setting_id, False).accepted
            after = _object_counts()
        grown = {name: count for name, count in (after - before).items() if count >= 20}
        assert not grown, f"each render setting change keeps objects: {grown}"
    finally:
        adapter.shutdown()


def test_an_eco_mode_change_reaches_the_renderer_with_no_new_frame(tmp_path) -> None:
    renderer_adapter.configure_render_settings_schema(
        provider_id="test",
        provider_label="Test",
        public_namespaces=("omni:rtx:",),
        metadata_key="renderSettings",
        group_fallback="rtx",
        group_label_fallback="RTX",
        builtin_specs=(
            {
                "attr_name": _ECO_MODE,
                "usd_type": "bool",
                "value_type": "bool",
                "requirement": "warmup",
                "default": True,
            },
            {
                "attr_name": _ECO_MODE_FRAME_LIMIT,
                "usd_type": "int",
                "value_type": "int",
                "requirement": "warmup",
                "default": 500,
            },
            {
                "attr_name": _RENDER_MODE,
                "usd_type": "token",
                "value_type": "enum",
                "requirement": "renderer_restart",
                "default": "RealTimePathTracing",
                "allowed_values": ("RealTimePathTracing", "PathTracing"),
            },
        ),
    )
    scene = tmp_path / "scene.usda"
    scene.write_text(_SCENE)
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        adapter.set_render_policy("on_change", _SETTLE_FRAMES)
        picture = _still_picture(adapter)
        settings = {
            (descriptor.metadata or {}).get("attr_name"): descriptor
            for descriptor in adapter.list_render_settings().settings
        }
        eco_mode, frame_limit = settings[_ECO_MODE], settings[_ECO_MODE_FRAME_LIMIT]
        render_mode = settings[_RENDER_MODE]
        product = eco_mode.metadata["render_product_path"]
        renderer = adapter._renderer
        steps = []
        step = renderer.step
        renderer.step = lambda *args, **kwargs: steps.append(1) or step(*args, **kwargs)
        resets = []
        reset = renderer.reset
        renderer.reset = lambda *args, **kwargs: resets.append(1) or reset(*args, **kwargs)

        # The render mode set to its default, and its reset: the effective
        # value stays, so no restart and no frame.
        for _ in range(2):
            assert adapter.apply_render_setting(render_mode.setting_id, "RealTimePathTracing").accepted
            assert np.array_equal(_still_picture(adapter), picture)
            assert adapter.reset_render_setting(render_mode.setting_id).accepted
            assert np.array_equal(_still_picture(adapter), picture)
        assert resets == [], "a render mode change that keeps its value restarted the renderer"
        assert steps == [], f"render mode changes that keep the value rendered {len(steps)} frames"

        # Undo and Redo of Reset Settings clear and check Eco Mode. The picture
        # on screen stays, and no frame is rendered.
        for _ in range(3):
            assert adapter.apply_render_setting(eco_mode.setting_id, False).accepted
            assert np.array_equal(_still_picture(adapter), picture)
            assert adapter.reset_render_setting(eco_mode.setting_id).accepted
            assert np.array_equal(_still_picture(adapter), picture)
        assert steps == [], f"Eco Mode changes rendered {len(steps)} frames"
        # The renderer has the last value before it renders again.
        assert adapter.apply_render_setting(eco_mode.setting_id, False).accepted
        assert np.array_equal(_still_picture(adapter), picture)
        adapter.request_render()
        _still_picture(adapter)
        assert _renderer_value(adapter, _ECO_MODE, product) is False
        assert adapter.reset_render_setting(eco_mode.setting_id).accepted
        _still_picture(adapter)
        assert _renderer_value(adapter, _ECO_MODE, product) is True
        steps.clear()

        # With a frame limit below the settle frames, Eco Mode stops the
        # renderer early. Eco Mode off then lets it refine the picture: the
        # picture is rendered again.
        assert adapter.apply_render_setting(frame_limit.setting_id, 2).accepted
        _still_picture(adapter)
        assert _renderer_value(adapter, _ECO_MODE_FRAME_LIMIT, product) == 2
        assert steps == [], "a lower Eco Mode frame limit rendered frames"
        adapter.request_render()
        _still_picture(adapter)
        rendered = len(steps)
        assert rendered > 0
        assert adapter.apply_render_setting(eco_mode.setting_id, False).accepted
        _still_picture(adapter)
        assert len(steps) > rendered, (
            "Eco Mode off did not render a picture that Eco Mode had stopped early"
        )
    finally:
        adapter.shutdown()


def test_undo_and_redo_of_a_reset_show_the_stored_pictures_with_no_frame(tmp_path) -> None:
    renderer_adapter.configure_render_settings_schema(
        provider_id="test",
        provider_label="Test",
        public_namespaces=("omni:rtx:",),
        metadata_key="renderSettings",
        group_fallback="rtx",
        group_label_fallback="RTX",
        builtin_specs=(
            {
                "attr_name": _SRGB_TO_GAMMA,
                "usd_type": "bool",
                "value_type": "bool",
                "requirement": "warmup",
                "default": True,
            },
            {
                "attr_name": _ECO_MODE,
                "usd_type": "bool",
                "value_type": "bool",
                "requirement": "warmup",
                "default": True,
            },
            {
                "attr_name": _RENDER_MODE,
                "usd_type": "token",
                "value_type": "enum",
                "requirement": "renderer_restart",
                "default": "RealTimePathTracing",
                "allowed_values": ("RealTimePathTracing", "PathTracing"),
            },
        ),
    )
    scene = tmp_path / "scene.usda"
    scene.write_text(_SCENE)
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        adapter.set_render_policy("on_change", _SETTLE_FRAMES)
        _still_picture(adapter)
        settings = {
            (descriptor.metadata or {}).get("attr_name"): descriptor
            for descriptor in adapter.list_render_settings().settings
        }
        product = settings[_ECO_MODE].metadata["render_product_path"]
        changed = {_SRGB_TO_GAMMA: False, _ECO_MODE: False, _RENDER_MODE: "PathTracing"}

        def undo() -> None:
            for name, value in changed.items():
                assert adapter.apply_render_setting(settings[name].setting_id, value).accepted

        def redo() -> None:
            for name in changed:
                assert adapter.reset_render_setting(settings[name].setting_id).accepted

        undo()
        changed_picture = _still_picture(adapter)
        redo()
        reset_picture = _still_picture(adapter)
        assert not np.array_equal(changed_picture, reset_picture)

        renderer = adapter._renderer
        steps = []
        step = renderer.step
        renderer.step = lambda *args, **kwargs: steps.append(1) or step(*args, **kwargs)
        resets = []
        reset = renderer.reset
        renderer.reset = lambda *args, **kwargs: resets.append(1) or reset(*args, **kwargs)
        for _ in range(5):
            undo()
            assert np.array_equal(_still_picture(adapter), changed_picture)
            redo()
            assert np.array_equal(_still_picture(adapter), reset_picture)
        undo()
        assert np.array_equal(_still_picture(adapter), changed_picture)
        assert steps == [], f"Undo and Redo of a Reset rendered {len(steps)} frames"
        assert resets == [], "Undo and Redo of a Reset restarted the renderer"

        # Another camera renders, and the renderer has the settings of the
        # picture on screen first (the render mode with its restart).
        view = _VIEW.copy()
        view[0, 3] = 60.0
        _still_picture(adapter, view)
        assert steps, "a camera change showed a stored picture"
        assert resets == [1]
        assert _renderer_value(adapter, _SRGB_TO_GAMMA, product) is False
        assert _renderer_value(adapter, _ECO_MODE, product) is False

        # A stored picture belongs to its camera: back at the first camera,
        # Redo renders the picture of the reset settings again.
        _still_picture(adapter)
        steps.clear()
        redo()
        again = _still_picture(adapter)
        assert steps, "a stored picture of another camera was shown"
        difference = np.abs(again[..., :3].astype(float) - reset_picture[..., :3]).mean()
        changed_difference = np.abs(
            changed_picture[..., :3].astype(float) - reset_picture[..., :3]
        ).mean()
        assert difference < 0.2 * changed_difference, (difference, changed_difference)
        assert _renderer_value(adapter, _SRGB_TO_GAMMA, product) is True
        assert _renderer_value(adapter, _ECO_MODE, product) is True
    finally:
        adapter.shutdown()


def test_fast_undo_and_redo_of_a_reset_render_a_bounded_number_of_frames(tmp_path) -> None:
    # As the test above, with each Undo or Redo one or two frames after the last
    # one: no picture settles before the next action.
    renderer_adapter.configure_render_settings_schema(
        provider_id="test",
        provider_label="Test",
        public_namespaces=("omni:rtx:",),
        metadata_key="renderSettings",
        group_fallback="rtx",
        group_label_fallback="RTX",
        builtin_specs=(
            {
                "attr_name": _SRGB_TO_GAMMA,
                "usd_type": "bool",
                "value_type": "bool",
                "requirement": "warmup",
                "default": True,
            },
            {
                "attr_name": _RENDER_MODE,
                "usd_type": "token",
                "value_type": "enum",
                "requirement": "renderer_restart",
                "default": "RealTimePathTracing",
                "allowed_values": ("RealTimePathTracing", "PathTracing"),
            },
        ),
    )
    scene = tmp_path / "scene.usda"
    scene.write_text(_SCENE)
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        adapter.set_render_policy("on_change", _SETTLE_FRAMES)
        _still_picture(adapter)
        settings = {
            (descriptor.metadata or {}).get("attr_name"): descriptor
            for descriptor in adapter.list_render_settings().settings
        }
        changed = {_SRGB_TO_GAMMA: False, _RENDER_MODE: "PathTracing"}

        def undo() -> None:
            for name, value in changed.items():
                assert adapter.apply_render_setting(settings[name].setting_id, value).accepted

        def redo() -> None:
            for name in changed:
                assert adapter.reset_render_setting(settings[name].setting_id).accepted

        renderer = adapter._renderer
        steps = []
        step = renderer.step
        renderer.step = lambda *args, **kwargs: steps.append(1) or step(*args, **kwargs)
        resets = []
        reset = renderer.reset
        renderer.reset = lambda *args, **kwargs: resets.append(1) or reset(*args, **kwargs)
        steps_after = []
        for action in range(60):
            undo() if action % 2 == 0 else redo()
            for _ in range(1 + action % 2):
                adapter.render_frame(_WIDTH, _HEIGHT, _VIEW, _PROJECTION)
            steps_after.append(len(steps))
        assert steps_after[-1] == steps_after[29], f"Undo and Redo still render: {steps_after}"
        # Each state: its first frames, a step that stores the picture when it
        # is left, and the settle frames of a finished picture, twice at most.
        assert steps_after[-1] <= 2 * (4 + 2 * (_SETTLE_FRAMES + 2)), steps_after
        assert len(resets) <= 4, f"{len(resets)} renderer restarts"

        # After a pause on each state (the renderer finishes the pictures that
        # were left early), Undo and Redo show settled pictures, with no frame.
        def pause() -> np.ndarray:
            for _ in range(3 * (_SETTLE_FRAMES + 2)):
                adapter.render_frame(_WIDTH, _HEIGHT, _VIEW, _PROJECTION)
            return _still_picture(adapter)

        reset_picture = pause()
        undo()
        changed_picture = pause()
        rendered, restarts = len(steps), len(resets)
        for _ in range(5):
            redo()
            assert np.array_equal(_still_picture(adapter), reset_picture)
            undo()
            assert np.array_equal(_still_picture(adapter), changed_picture)
        assert (len(steps), len(resets)) == (rendered, restarts)

        # They are the pictures that a straight render of each state gives.
        adapter.request_render()
        straight_changed = _still_picture(adapter)
        redo()
        adapter.request_render()
        straight_reset = _still_picture(adapter)
        apart = np.abs(changed_picture[..., :3].astype(float) - reset_picture[..., :3]).mean()
        for shown, straight in ((changed_picture, straight_changed), (reset_picture, straight_reset)):
            difference = np.abs(shown[..., :3].astype(float) - straight[..., :3]).mean()
            assert difference < 0.05 * apart, (difference, apart)
    finally:
        adapter.shutdown()


def test_undo_and_redo_of_a_reset_with_a_sample_target_show_the_stored_pictures(tmp_path) -> None:
    # The Reset of review 4: the render mode and a path tracing sample target.
    # After each frame the viewport gives the adapter its render policy: the
    # sample target of path tracing, else the settle frames. So each Undo and
    # Redo also changes the settle frames.
    renderer_adapter.configure_render_settings_schema(
        provider_id="test",
        provider_label="Test",
        public_namespaces=("omni:rtx:",),
        metadata_key="renderSettings",
        group_fallback="rtx",
        group_label_fallback="RTX",
        builtin_specs=(
            {
                "attr_name": _SRGB_TO_GAMMA,
                "usd_type": "bool",
                "value_type": "bool",
                "requirement": "warmup",
                "default": True,
            },
            {
                "attr_name": _RENDER_MODE,
                "usd_type": "token",
                "value_type": "enum",
                "requirement": "renderer_restart",
                "default": "RealTimePathTracing",
                "allowed_values": ("RealTimePathTracing", "PathTracing"),
            },
            {
                "attr_name": _PATH_TRACING_SAMPLES,
                "usd_type": "int",
                "value_type": "int",
                "requirement": "warmup",
                "default": _SETTLE_FRAMES,
            },
        ),
    )
    scene = tmp_path / "scene.usda"
    scene.write_text(_SCENE)
    adapter = OvRtxRendererAdapter()
    try:
        adapter.load_stage(Usd.Stage.Open(str(scene)))

        def frame() -> np.ndarray:
            picture = adapter.render_frame(_WIDTH, _HEIGHT, _VIEW, _PROJECTION)
            # The policy rule of the viewport, from the values that it reads.
            settle = _SETTLE_FRAMES
            if adapter.read_render_setting_value(_RENDER_MODE) == "PathTracing":
                settle = int(adapter.read_render_setting_value(_PATH_TRACING_SAMPLES))
            adapter.set_render_policy("on_change", settle)
            return picture

        def still() -> np.ndarray:
            picture = None
            for _ in range(400):
                picture = frame()
                if adapter.last_frame_unchanged():
                    break
            assert adapter.last_frame_unchanged(), "the adapter did not stop stepping the renderer"
            return np.array(picture, copy=True)

        still()
        settings = {
            (descriptor.metadata or {}).get("attr_name"): descriptor
            for descriptor in adapter.list_render_settings().settings
        }
        changed = {_SRGB_TO_GAMMA: False, _RENDER_MODE: "PathTracing", _PATH_TRACING_SAMPLES: 2 * _SETTLE_FRAMES}

        def undo() -> None:
            for name, value in changed.items():
                assert adapter.apply_render_setting(settings[name].setting_id, value).accepted

        def redo() -> None:
            for name in changed:
                assert adapter.reset_render_setting(settings[name].setting_id).accepted

        undo()
        changed_picture = still()
        redo()
        reset_picture = still()
        assert not np.array_equal(changed_picture, reset_picture)

        renderer = adapter._renderer
        steps = []
        step = renderer.step
        renderer.step = lambda *args, **kwargs: steps.append(1) or step(*args, **kwargs)
        resets = []
        reset = renderer.reset
        renderer.reset = lambda *args, **kwargs: resets.append(1) or reset(*args, **kwargs)
        for _ in range(5):
            undo()
            assert np.array_equal(still(), changed_picture)
            redo()
            assert np.array_equal(still(), reset_picture)
        assert steps == [], f"Undo and Redo of a Reset with a sample target rendered {len(steps)} frames"
        assert resets == [], "Undo and Redo of a Reset with a sample target restarted the renderer"
        # The path traced state keeps its own sample target.
        undo()
        still()
        assert adapter._still_frame_policy == ("on_change", 2 * _SETTLE_FRAMES)
    finally:
        adapter.shutdown()
