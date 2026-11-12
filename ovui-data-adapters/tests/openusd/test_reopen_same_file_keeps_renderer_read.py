# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The same unchanged file opened again is not read again by the renderer.

ovrtx keeps memory of each root that it opens. Before the fix, each
File > Open or File > Recent Files of the file that was open made ovrtx open
the root again, and the memory of the app grew at each reopen (about 15 MB for
each reopen of a scene with 50,000 meshes). Now the renderer keeps its read of
the root when the file did not change and nothing outside the session layer
was written to the renderer's scene. Only the session layer is replaced.

The tests use the real renderer. They count the root opens that the adapter
asks of the renderer (each one still goes to the renderer) and read back the
values that the renderer draws. Each test runs in a process of its own,
because the ovrtx file cache and the adapter's record of the files that ovrtx
read are process-wide.
"""

from __future__ import annotations

import pytest
import numpy as np
from pxr import Gf, Usd

pytestmark = [pytest.mark.requires_ovrtx, pytest.mark.own_process]

_SCENE = """#usda 1.0
(
    defaultPrim = "World"
    metersPerUnit = 0.01
    upAxis = "Y"
)

def Xform "World"
{
    def Cube "Box" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        rel material:binding = </World/Looks/Red>
        double size = 40
        double3 xformOp:translate = (150, 20, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }

    def Scope "Looks"
    {
        def Material "Red"
        {
            token outputs:surface.connect = </World/Looks/Red/Surface.outputs:surface>

            def Shader "Surface"
            {
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor = (0.8, 0.1, 0.1)
                token outputs:surface
            }
        }
    }

    def Camera "Cam"
    {
        double3 xformOp:translate = (0, 50, 500)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
}

def Scope "Render"
{
    def RenderProduct "Product"
    {
        rel camera = </World/Cam>
        rel orderedVars = </Render/Vars/LdrColor>
        uniform int2 resolution = (64, 36)
        float ovuitest:gain = 1
    }

    def Scope "Vars"
    {
        def RenderVar "LdrColor"
        {
            uniform string sourceName = "LdrColor"
        }
    }
}
"""

# The red material of the scene as a material of an MDL module of its own.
_MDL_MODULE = """mdl 1.6;
import ::df::*;
export material red_paint(
    color tint = color(0.8, 0.1, 0.1)
) = material(
    surface: material_surface(
        scattering: df::diffuse_reflection_bsdf(tint: tint)
    )
);
"""
_MDL_SCENE = _SCENE.replace(
    """            token outputs:surface.connect = </World/Looks/Red/Surface.outputs:surface>

            def Shader "Surface"
            {
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor = (0.8, 0.1, 0.1)
                token outputs:surface
            }""",
    """            token outputs:mdl:surface.connect = </World/Looks/Red/Surface.outputs:out>

            def Shader "Surface"
            {
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @./red_paint.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "red_paint"
                token outputs:out
            }""",
)
assert _MDL_SCENE != _SCENE

_FILE_XFORM = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [150.0, 20.0, 0.0, 1.0]]
_FILE_CAMERA_XFORM = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 50.0, 500.0, 1.0]]

_ROOT_OPENS = ("open_usd", "open_usd_from_file", "open_usd_from_string")


def _count_root_opens(adapter, monkeypatch) -> list[str]:
    """Return a list that gets the name of each root open that the adapter asks of its renderer."""

    opened: list[str] = []
    for name in _ROOT_OPENS:
        method = getattr(adapter._renderer, name, None)
        if method is None:
            continue

        def counted(*args, _method=method, _name=name, **kwargs):
            opened.append(_name)
            return _method(*args, **kwargs)

        monkeypatch.setattr(adapter._renderer, name, counted)
    return opened


def _renderer_value(adapter, attribute: str, prim_path: str) -> list:
    """Return the value that the ovrtx renderer of ``adapter`` has for the attribute."""

    values = np.from_dlpack(adapter._renderer.read_attribute(attribute, [prim_path])).tolist()
    assert len(values) == 1, values
    return values[0]


def _draw(adapter):
    """Return the last of three frames that the renderer of ``adapter`` draws for the viewport camera."""

    view = np.eye(4)
    view[1, 3] = -40.0
    view[2, 3] = -600.0  # A GL view of a camera at (0, 40, 600).
    projection = np.array([[1.0, 0, 0, 0], [0, 1.78, 0, 0], [0, 0, -1.0002, -0.020002], [0, 0, -1, 0]])
    image = None
    for _ in range(3):
        frame = adapter.render_frame(160, 90, view, projection)
        if frame is not None:
            image = np.array(frame, copy=True)
    return image


def _red_pixels(image) -> int:
    """Return the number of pixels of ``image`` where the red box is drawn."""

    return int(((image[..., 0].astype(np.int16) - image[..., 1].astype(np.int16)) > 60).sum())


def test_the_same_unchanged_file_opened_again_is_not_read_again(tmp_path, monkeypatch):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "box.usda"
    scene.write_text(_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        opened = _count_root_opens(adapter, monkeypatch)
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        assert len(opened) == 1
        first_session = adapter._session_handle

        # File > Recent Files with the file that is open: a new stage of the same file each time.
        for _ in range(3):
            adapter.load_stage(Usd.Stage.Open(str(scene)))
            assert _renderer_value(adapter, "size", "/World/Box") == 40.0
            assert _renderer_value(adapter, "omni:xform", "/World/Box") == _FILE_XFORM

        assert len(opened) == 1
        assert adapter._session_handle is not None and adapter._session_handle != first_session
    finally:
        adapter.shutdown()


def test_the_same_file_opened_again_draws_the_frames_of_its_first_open(tmp_path, monkeypatch):
    """A new open of the root clears the rendering history of the renderer; a kept root must do the same."""

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "box.usda"
    scene.write_text(_SCENE)
    view = np.eye(4)
    view[1, 3] = -40.0
    view[2, 3] = -600.0  # A GL view of a camera at (0, 40, 600).
    projection = np.array([[1.0, 0, 0, 0], [0, 1.78, 0, 0], [0, 0, -1.0002, -0.020002], [0, 0, -1, 0]])

    def open_and_draw():
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        image = None
        for _ in range(3):
            frame = adapter.render_frame(160, 90, view, projection)
            if frame is not None:
                image = np.array(frame, copy=True)
        return image

    adapter = OvRtxRendererAdapter()
    try:
        opened = _count_root_opens(adapter, monkeypatch)
        first = open_and_draw()
        assert first is not None and first.mean() > 0
        for _ in range(2):
            assert np.array_equal(open_and_draw(), first)
        # The frames came from the kept root, not from a new read of the file.
        assert len(opened) == 1
    finally:
        adapter.shutdown()


def test_a_live_transform_then_the_same_file_opened_again_shows_the_transform_of_the_file(tmp_path, monkeypatch):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "box.usda"
    scene.write_text(_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        opened = _count_root_opens(adapter, monkeypatch)
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        # A gizmo drag shows its transform in the renderer before anything is written to USD.
        moved = Gf.Matrix4d().SetTranslate(Gf.Vec3d(1.0, 2.0, 3.0))
        assert adapter.set_live_local_transform("/World/Box", moved)
        assert _renderer_value(adapter, "omni:xform", "/World/Box")[3] == [1.0, 2.0, 3.0, 1.0]

        adapter.load_stage(Usd.Stage.Open(str(scene)))

        assert _renderer_value(adapter, "omni:xform", "/World/Box") == _FILE_XFORM
        assert len(opened) == 2
    finally:
        adapter.shutdown()


def test_an_edit_in_the_session_layer_then_the_same_file_opened_again_shows_the_file(tmp_path, monkeypatch):
    from ovui_data_adapters.openusd import OvRtxRendererAdapter
    from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

    scene = tmp_path / "box.usda"
    scene.write_text(_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        opened = _count_root_opens(adapter, monkeypatch)
        stage = Usd.Stage.Open(str(scene))
        adapter.load_stage(stage)
        # The Layers panel can make the session layer the authoring layer. The
        # edit goes to the renderer as the app sends it; the file stays as it is.
        queued = []
        stage_adapter = UsdStageAdapter(stage, call_later=lambda delay, callback: queued.append(callback))
        subscription = stage_adapter.subscribe_changes(adapter.notify_stage_changed)
        try:
            stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
            stage.GetPrimAtPath("/World/Box").GetAttribute("size").Set(80.0)
            while queued:
                queued.pop(0)()
        finally:
            subscription.cancel()
            stage_adapter.dispose()
        assert _renderer_value(adapter, "size", "/World/Box") == 80.0
        assert not stage.GetRootLayer().dirty

        # The new stage of the same file has its own, empty session layer.
        adapter.load_stage(Usd.Stage.Open(str(scene)))

        assert _renderer_value(adapter, "size", "/World/Box") == 40.0
        assert len(opened) == 2
    finally:
        adapter.shutdown()


@pytest.mark.parametrize("finish", ["Escape", "the start value"])
def test_a_cancelled_number_edit_then_the_same_file_opened_again_reads_the_root_at_most_once(
    tmp_path, monkeypatch, finish
):
    """After a number edit that ends with the value of the file, the same file opens again with one root read at most.

    Escape in a decimal number field cancels the edit. An edit can also end at its start value: Escape in an
    integer field writes it back, and a user can type it again and press Enter. The application then shows the
    root layer as not modified, but OpenUSD keeps the layer dirty. The edit was written to the renderer, so the
    next open of the same file can read the root again, but each later open must keep that root. A later edit
    that is not cancelled is a change that is not saved: the next open must show it.
    """

    from ovui_data_adapters.openusd import OvRtxRendererAdapter
    from ovui_data_adapters.openusd._layer_modified_state import is_layer_modified
    from ovui_data_adapters.openusd.property_adapter import UsdPropertyAdapter
    from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
    from ovui_data_adapters.services.undo import UndoManager

    scene = tmp_path / "box.usda"
    scene.write_text(_SCENE)
    translate = "xformOp:translate"

    adapter = OvRtxRendererAdapter()
    try:
        opened = _count_root_opens(adapter, monkeypatch)
        stage = Usd.Stage.Open(str(scene))
        adapter.load_stage(stage)
        root = stage.GetRootLayer()
        properties = UsdPropertyAdapter(stage, ["/World/Box"], undo_manager=UndoManager())
        # The Property Inspector writes each typed value to the stage, and the app sends the change to the renderer.
        queued = []
        stage_adapter = UsdStageAdapter(stage, call_later=lambda delay, callback: queued.append(callback))
        subscription = stage_adapter.subscribe_changes(adapter.notify_stage_changed)

        def type_value(value):
            properties.set_value(translate, value)
            while queued:
                queued.pop(0)()

        try:
            properties.begin_edit(translate)
            type_value((150.0, 90.0, 0.0))
            assert _renderer_value(adapter, "omni:xform", "/World/Box")[3] == [150.0, 90.0, 0.0, 1.0]
            if finish == "Escape":
                properties.cancel_edit(translate)
            else:
                type_value((150.0, 20.0, 0.0))
                properties.end_edit(translate)
            while queued:
                queued.pop(0)()
        finally:
            subscription.cancel()
            stage_adapter.dispose()
        assert _renderer_value(adapter, "omni:xform", "/World/Box") == _FILE_XFORM
        # The layer is shown as not modified (no modified dot, Save All off), but OpenUSD keeps it dirty.
        assert root.dirty and not is_layer_modified(root)

        # File > Recent Files with the same file, several times.
        root_reads = []
        for _ in range(3):
            adapter.load_stage(Usd.Stage.Open(str(scene)))
            root_reads.append(len(opened))
            assert _renderer_value(adapter, "omni:xform", "/World/Box") == _FILE_XFORM
        assert root_reads[0] <= 2 and root_reads == [root_reads[0]] * 3, root_reads

        # An edit that is not cancelled is a change that is not saved, so the next open shows it.
        properties.begin_edit(translate)
        properties.set_value(translate, (150.0, 90.0, 0.0))
        properties.end_edit(translate)
        assert is_layer_modified(root)
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        assert _renderer_value(adapter, "omni:xform", "/World/Box")[3] == [150.0, 90.0, 0.0, 1.0]
    finally:
        adapter.shutdown()


def test_a_selection_outline_then_the_same_file_opened_again_is_read_again(tmp_path, monkeypatch):
    """The outline group of a selected prim is renderer state on a prim of the scene.

    A new open of the file has no selection, so the renderer must not keep it.
    """

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "box.usda"
    scene.write_text(_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        opened = _count_root_opens(adapter, monkeypatch)
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        adapter.set_selection_highlight(["/World/Box"])
        assert adapter._selection_outline_previous_paths == {"/World/Box"}

        adapter.load_stage(Usd.Stage.Open(str(scene)))

        assert len(opened) == 2
        assert _renderer_value(adapter, "size", "/World/Box") == 40.0
    finally:
        adapter.shutdown()


@pytest.mark.parametrize("selected", ["after the open", "before the open"])
def test_a_frame_of_a_render_product_of_the_scene_then_the_same_file_opened_again_shows_the_camera_of_the_file(
    tmp_path, monkeypatch, selected
):
    """Each frame of a render product of the scene writes the viewport camera to the camera prim of that product."""

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "box.usda"
    scene.write_text(_SCENE)

    def select_the_product_of_the_scene():
        # The Render Target picker selects the product of the scene and its camera.
        assert adapter.set_active_camera_path("/World/Cam")
        assert adapter.set_active_render_product_path("/Render/Product")

    adapter = OvRtxRendererAdapter()
    try:
        opened = _count_root_opens(adapter, monkeypatch)
        if selected == "before the open":
            select_the_product_of_the_scene()
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        if selected == "after the open":
            select_the_product_of_the_scene()
        view = np.eye(4)
        view[0, 3] = -7.0  # A GL view of a camera at (7, 0, 0).
        projection = np.array([[1.0, 0, 0, 0], [0, 1.78, 0, 0], [0, 0, -1.0002, -0.020002], [0, 0, -1, 0]])
        adapter.render_frame(64, 36, view, projection)
        assert _renderer_value(adapter, "omni:xform", "/World/Cam")[3][:3] == [7.0, 0.0, 0.0]
        # Back to the viewport's own camera, then File > Recent Files with the same file.
        assert adapter.set_active_render_product_path(None)
        assert adapter.set_active_camera_path(None)

        adapter.load_stage(Usd.Stage.Open(str(scene)))

        assert _renderer_value(adapter, "omni:xform", "/World/Cam") == _FILE_CAMERA_XFORM
        assert len(opened) == 2
    finally:
        adapter.shutdown()


def test_a_live_material_check_then_the_same_file_opened_again_is_read_again(tmp_path, monkeypatch):
    """The check adds copies of scene prims and a layer of its own to the renderer's scene."""

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "box.usda"
    scene.write_text(_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        opened = _count_root_opens(adapter, monkeypatch)
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        result = adapter.verify_materials_live()
        assert "/World/Looks/Red" in str(result["materials"])

        adapter.load_stage(Usd.Stage.Open(str(scene)))

        assert len(opened) == 2
        assert _renderer_value(adapter, "size", "/World/Box") == 40.0
    finally:
        adapter.shutdown()


def test_a_live_render_setting_of_a_render_product_of_the_scene_then_the_same_file_opened_again_shows_the_file(
    tmp_path, monkeypatch
):
    """A render setting can belong to a render product of the scene while the session's own product is active.

    The value goes to the renderer at once, and the notice of the stage edit comes later.
    """

    from ovui_data_adapters.openusd import OvRtxRendererAdapter
    from ovui_data_adapters.openusd import renderer_adapter

    # The optional renderer tools install a schema of settings; this one names the attribute of the scene product.
    renderer_adapter.configure_render_settings_schema(
        provider_id="test",
        provider_label="Test",
        public_namespaces=("ovuitest:",),
        metadata_key="ovuitest",
        group_fallback="test",
        group_label_fallback="Test",
        builtin_specs=(),
    )
    scene = tmp_path / "box.usda"
    scene.write_text(_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        opened = _count_root_opens(adapter, monkeypatch)
        stage = Usd.Stage.Open(str(scene))
        adapter.load_stage(stage)
        # The Layers panel can make the session layer the authoring layer; the file stays as it is.
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        result = adapter.apply_render_setting(
            "/Render/Product:ovuitest:gain", 2.0, render_product_path="/Render/Product"
        )
        assert result.accepted, result
        assert _renderer_value(adapter, "ovuitest:gain", "/Render/Product") == 2.0
        assert not stage.GetRootLayer().dirty

        adapter.load_stage(Usd.Stage.Open(str(scene)))

        assert _renderer_value(adapter, "ovuitest:gain", "/Render/Product") == 1.0
        assert len(opened) == 2
    finally:
        adapter.shutdown()


def test_a_failed_open_of_the_same_file_keeps_the_scene_that_was_open(tmp_path, monkeypatch):
    """After a reopen of the same file fails, the viewport still draws the scene that was open.

    Here the renderer refuses the session layer of the new open. The kept root was not touched, but the session
    layer of the scene that was open was already removed; it has the camera and the render product of the
    viewport, so it must be put back, or the viewport draws nothing after the failed open.
    """

    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    scene = tmp_path / "box.usda"
    scene.write_text(_SCENE)

    adapter = OvRtxRendererAdapter()
    try:
        opened = _count_root_opens(adapter, monkeypatch)
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        before = _draw(adapter)
        assert before is not None and _red_pixels(before) > 0

        add_layer = adapter._renderer.add_usd_reference_from_string
        refused = []

        def refuse_the_next_layer(*args, **kwargs):
            if not refused:
                refused.append(args)
                raise RuntimeError("the renderer refused the layer")
            return add_layer(*args, **kwargs)

        monkeypatch.setattr(adapter._renderer, "add_usd_reference_from_string", refuse_the_next_layer)
        with pytest.raises(RuntimeError, match="the renderer refused the layer"):
            adapter.load_stage(Usd.Stage.Open(str(scene)))
        # The open failed on the kept root, which was not opened again.
        assert refused and len(opened) == 1

        # The viewport still draws the red box of the scene that was open.
        after = _draw(adapter)
        assert after is not None and _red_pixels(after) > 0
        assert _renderer_value(adapter, "size", "/World/Box") == 40.0

        # The next open of the same file works and keeps the root.
        adapter.load_stage(Usd.Stage.Open(str(scene)))
        again = _draw(adapter)
        assert again is not None and _red_pixels(again) > 0
        assert len(opened) == 1
    finally:
        adapter.shutdown()


def test_the_material_report_keeps_what_the_renderer_said_when_the_same_file_opens_again(tmp_path, monkeypatch):
    """The material report names, for each shader, the module that the renderer generated code from.

    The renderer says this while it compiles the materials of a scene that it opened. A kept root is the scene
    that it compiled, and it compiles nothing again, so after the reopen the report must still name the module
    that the renderer said at the first open. The check needs a renderer with the public log callback: without
    it the report names no module at either open, so there is nothing to keep, and the test fails with the reason.
    """

    import ovrtx
    from ovui_data_adapters.common import render_telemetry
    from ovui_data_adapters.common.render_material_report import describe_materials
    from ovui_data_adapters.openusd import OvRtxRendererAdapter

    monkeypatch.setenv(render_telemetry.MESSAGES_ENV, "1")
    supported, why = render_telemetry.log_callback_support(ovrtx)
    assert supported, f"the material report needs the renderer's public log callback: {why}"
    scene = tmp_path / "box.usda"
    scene.write_text(_MDL_SCENE)
    (tmp_path / "red_paint.mdl").write_text(_MDL_MODULE)

    def module_of_red(stage):
        (entry,) = [item for item in describe_materials(stage)["materials"] if item["path"] == "/World/Looks/Red"]
        return entry["renderer"]["compiled_module"]

    adapter = OvRtxRendererAdapter()
    try:
        opened = _count_root_opens(adapter, monkeypatch)
        stage = Usd.Stage.Open(str(scene))
        adapter.load_stage(stage)
        assert _draw(adapter) is not None
        first = module_of_red(stage)
        assert first is not None and first["id"].endswith("red_paint.mdl"), first

        # File > Recent Files with the file that is open.
        stage = Usd.Stage.Open(str(scene))
        adapter.load_stage(stage)
        assert _draw(adapter) is not None

        assert len(opened) == 1
        assert module_of_red(stage) == first
    finally:
        adapter.shutdown()
