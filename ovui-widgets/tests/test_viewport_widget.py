# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ViewportWidget ZStack layout (Step 40)."""

import asyncio
from types import SimpleNamespace

import numpy as np
import omni.ui as ui
import pytest
from ovui_data_adapters.common import (
    VIEWPORT_CAMERA_POSE_SOURCE,
    BoundCameraPose,
    StageChoice,
)

from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
from ovui_widgets.common.testing.mock_stage import MockStageAdapter
from ovui_widgets.common.testing.mock_transform import MockTransformAdapter
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.viewport.camera_navigation_state import CameraNavigationState
from ovui_widgets.viewport.image_bridge import ImageBridge
from ovui_widgets.viewport.pick_gesture import PickGesture, PickRectGesture
from ovui_widgets.viewport.toolbar_hooks import ViewportStatusBadge, ViewportToolbarAction
from ovui_widgets.viewport.transform_manipulator import TOOL_ROTATE, TOOL_TRANSLATE
from ovui_widgets.viewport import viewport_widget as viewport_mod
from ovui_widgets.viewport.viewport_hooks import (
    ViewportAnchoredPanel,
    ViewportOutputPreset,
    ViewportPointCloudRenderer,
)
from ovui_widgets.viewport.viewport_widget import (
    ViewportChromeOptions,
    ViewportSurface,
    ViewportWidget,
)


class _FakeCameraStageAdapter:
    def __init__(self, choices=(), poses=None):
        self.choices = tuple(choices)
        self.poses = dict(poses or {})
        self.read_paths = []

    def list_cameras(self):
        return list(self.choices)

    def read_camera_pose(self, path):
        self.read_paths.append(path)
        return self.poses.get(path)


class _FakeHierarchyItem:
    def __init__(self, path, category, children=()):
        self.path = path
        self.category = category
        self.children = list(children)


class _FakeHierarchyStageAdapter:
    def __init__(self):
        self.mesh_a = _FakeHierarchyItem("/World/GroupA/MeshA", "Mesh")
        self.mesh_b = _FakeHierarchyItem("/World/GroupA/ChildGroup/MeshB", "Mesh")
        self.mesh_c = _FakeHierarchyItem(
            "/World/GroupA/ChildGroup/GrandChildGroup/MeshC",
            "Mesh",
        )
        self.grand_child_group = _FakeHierarchyItem(
            "/World/GroupA/ChildGroup/GrandChildGroup",
            "Xform",
            [self.mesh_c],
        )
        self.child_group = _FakeHierarchyItem(
            "/World/GroupA/ChildGroup",
            "Xform",
            [self.mesh_b, self.grand_child_group],
        )
        self.group_a = _FakeHierarchyItem(
            "/World/GroupA",
            "Xform",
            [self.mesh_a, self.child_group],
        )
        self.empty_group = _FakeHierarchyItem("/World/EmptyGroup", "Xform")
        self.mesh_outside = _FakeHierarchyItem("/World/MeshOutside", "Mesh")
        self.world = _FakeHierarchyItem(
            "/World",
            "Xform",
            [self.group_a, self.empty_group, self.mesh_outside],
        )
        self._by_path = {}
        for item in (
            self.world,
            self.group_a,
            self.mesh_a,
            self.child_group,
            self.mesh_b,
            self.grand_child_group,
            self.mesh_c,
            self.empty_group,
            self.mesh_outside,
        ):
            self._by_path[item.path] = item

    def get_item_at_path(self, path):
        return self._by_path.get(path)

    def get_children(self, item):
        return list(item.children)

    def get_type_category(self, item):
        return item.category

    def get_item_path(self, item):
        return item.path


class _FakeCameraMenu:
    stack = []
    instances = []

    def __init__(self, title="", **kwargs):
        self.title = title
        self.kwargs = kwargs
        self.items = []
        self.submenus = []
        self.children = []
        self.shown_at = None
        self.destroyed = False
        self.hidden = False
        if type(self).stack:
            parent = type(self).stack[-1]
            parent.submenus.append(self)
            parent.children.append(("menu", self))
        type(self).instances.append(self)

    def __enter__(self):
        type(self).stack.append(self)
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        type(self).stack.pop()

    def show_at(self, x, y):
        self.shown_at = (float(x), float(y))

    def destroy(self):
        self.destroyed = True

    def hide(self):
        self.hidden = True


class _FakeCameraMenuItem:
    def __init__(self, label, **kwargs):
        self.label = label
        self.kwargs = kwargs
        if _FakeCameraMenu.stack:
            parent = _FakeCameraMenu.stack[-1]
            parent.items.append(self)
            parent.children.append(("item", self))

    def trigger(self):
        fn = self.kwargs.get("triggered_fn")
        if fn is None:
            fn = self.kwargs.get("row_handoff_fn")
        if fn is not None:
            return fn()
        return None


class _VisibleViewportImage:
    visible = True
    computed_width = 640
    computed_height = 360


class _FakeLivestreamTap:
    signal_port = 49100
    media_port = 47999
    protocol = "webrtc"
    public_ip = None

    def __init__(self, state="LISTENING", clients=0, last_error=None):
        self.state = state
        self.clients = clients
        self.last_error = last_error

    def status(self):
        return self.state, self.clients, self.last_error


class _FakeFrame:
    def __init__(self):
        self.build_fn = None

    def set_build_fn(self, fn):
        self.build_fn = fn


class _IdentityStreamCamera:
    def get_matrices(self, width, height):
        identity = [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
        return identity, identity


class _LiveTransformRenderer(MockRendererAdapter):
    def __init__(self):
        super().__init__()
        self.live_transforms = {}
        self.cleared_live_paths = []

    def set_live_local_transform(self, path, matrix):
        self.live_transforms[path] = [row[:] for row in matrix]
        return True

    def clear_live_local_transforms(self, paths):
        self.cleared_live_paths.append(list(paths))
        for path in paths:
            self.live_transforms.pop(path, None)


class _UnsupportedFixedResolutionRenderer(MockRendererAdapter):
    supports_fixed_resolution = False


class _MenuFailureRenderer(MockRendererAdapter):
    resolution_menu_failure_reason = "Resolution menu unavailable: data refresh failed"


class _CountingSelectionHighlightRenderer(MockRendererAdapter):
    def __init__(self):
        super().__init__()
        self.highlight_calls = []

    def set_selection_highlight(self, paths):
        self.highlight_calls.append(list(paths))
        super().set_selection_highlight(paths)

    def refresh_selection_highlight(self, paths):
        self.highlight_calls.append(list(paths))
        super().set_selection_highlight(paths)


class _A6CountingSettings:
    def __init__(self) -> None:
        from ovui_widgets.common.settings import Settings

        self._settings = Settings()
        self.set_calls = []

    def get(self, key, default=None):
        return self._settings.get(key, default)

    def set(self, key, value):
        before = self._settings.get(key, object())
        self._settings.set(key, value)
        after = self._settings.get(key, object())
        if before != after:
            self.set_calls.append((key, value))

    def subscribe(self, key, callback):
        return self._settings.subscribe(key, callback)


class _FakeNumericFieldModel:
    def __init__(self, value):
        self._value = value
        self.begin_edit_callbacks = []
        self.end_edit_callbacks = []
        self.value_changed_callbacks = []

    def get_value_as_int(self) -> int:
        return int(self._value)

    def get_value_as_string(self) -> str:
        return str(self._value)

    def set_value(self, value) -> None:
        self._value = value
        for callback in tuple(self.value_changed_callbacks):
            callback(self)

    def add_begin_edit_fn(self, callback):
        self.begin_edit_callbacks.append(callback)

    def add_end_edit_fn(self, callback):
        self.end_edit_callbacks.append(callback)

    def add_value_changed_fn(self, callback):
        self.value_changed_callbacks.append(callback)


class _FakeNumericField:
    def __init__(self, value):
        self.model = _FakeNumericFieldModel(value)
        self.key_pressed_fn = None

    def set_key_pressed_fn(self, callback):
        self.key_pressed_fn = callback


class _FakeLabel:
    def __init__(self):
        self.text = ""


class _FakeButton:
    def __init__(self, enabled: bool = True):
        self.enabled = bool(enabled)


class _FakeStringValueModel:
    def __init__(self, value: str):
        self._value = str(value)

    def get_value_as_string(self) -> str:
        return self._value


class _FakeComboRootModel:
    def __init__(self, value: int = 0):
        self._value = int(value)

    def get_value_as_int(self) -> int:
        return self._value

    def set_value(self, value: int) -> None:
        self._value = int(value)


class _FakeRatioComboModel:
    def __init__(self, values: tuple[str, ...], selected_index: int = 0):
        self._children = [_FakeStringValueModel(value) for value in values]
        self._root = _FakeComboRootModel(selected_index)

    def get_item_children(self, _item):
        return list(self._children)

    def get_item_value_model(self, item, _column_id=0):
        if item is None:
            return self._root
        return item

    def append_child_item(self, _parent, value_model):
        if isinstance(value_model, str):
            value_model = _FakeStringValueModel(value_model)
        self._children.append(value_model)
        return value_model

    def remove_item(self, item):
        self._children.remove(item)

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(child.get_value_as_string() for child in self._children)

    @property
    def selected_index(self) -> int:
        return self._root.get_value_as_int()


def _make_renderable_viewport() -> ViewportWidget:
    vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
    vp._image = _VisibleViewportImage()
    return vp


def _hidden_chrome_options() -> ViewportChromeOptions:
    return ViewportChromeOptions(
        show_toolbar=False,
        show_settings_button=False,
        show_text_hud=False,
        show_livestream_overlay=False,
        show_anchored_panels=False,
    )


def _build_viewport(viewport, build_fn=None) -> None:
    build = build_fn or viewport._build_ui
    build()


def _build_or_xfail_unsupported(viewport, build_fn=None) -> None:
    # Backward-compatible name: with the default scene backend every
    # environment builds, so this is now a plain build.
    _build_viewport(viewport, build_fn)


def _make_streamed_transform_surface(*, bus=None):
    from omni.ui_scene import scene as sc

    from ovui_widgets.viewport.transform_manipulator import TransformManipulator

    renderer = _LiveTransformRenderer()
    transform = MockTransformAdapter()
    stage = MockStageAdapter()
    undo = UndoManager()
    surface = ViewportSurface(renderer=renderer, bus=bus)
    surface.attach_stage(
        transform_adapter=transform,
        stage_adapter=stage,
        undo_manager=undo,
        snap_system=None,
    )
    surface._camera = _IdentityStreamCamera()
    surface._get_gizmo_world_scale = lambda: 1.0
    surface._transform_model.set_selection(["/World/Geometry/Cube"])

    generation = viewport_mod._Generation(renderer)
    generation.alive = True
    scene_view = sc.SceneView()
    with scene_view.scene:
        manipulator = TransformManipulator(
            model=surface._transform_model,
            tool=TOOL_TRANSLATE,
            pivot_fn=surface._transform_model.get_pivot_world,
            size_fn=lambda: 1.0,
            generation=generation,
        )
        manipulator.on_build()
    surface._scene_view = scene_view
    surface._transform_manipulator = manipulator
    surface._live_generation = generation
    return surface, renderer, transform, undo


@pytest.fixture
def fake_camera_menu(monkeypatch):
    import ovui_widgets.viewport.viewport_widget as viewport_mod

    _FakeCameraMenu.stack = []
    _FakeCameraMenu.instances = []
    monkeypatch.setattr(viewport_mod.ui, "Menu", _FakeCameraMenu)
    monkeypatch.setattr(viewport_mod.ui, "MenuItem", _FakeCameraMenuItem)
    return _FakeCameraMenu


class TestViewportWidgetCreation:
    def test_viewport_surface_is_public_package_export(self):
        import ovui_widgets.viewport as viewport_pkg

        assert viewport_pkg.ViewportSurface is ViewportSurface

    def test_create_with_mock_renderer_no_crash(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        assert vp is not None
        vp.destroy()

    def test_bridge_is_initialized(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        assert isinstance(vp._bridge, ImageBridge)
        vp.destroy()

    def test_renderer_stored(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        assert vp._renderer is renderer
        vp.destroy()

    def test_transform_model_receives_initial_renderer(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        assert vp._transform_model.renderer_adapter is renderer
        vp.destroy()


class TestViewportSelectionHighlightExpansion:
    def _make_viewport(self):
        from ovui_widgets.common.selection import SelectionBus

        adapter = _FakeHierarchyStageAdapter()
        renderer = MockRendererAdapter()
        bus = SelectionBus()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            bus=bus,
            stage_adapter_provider=lambda: adapter,
        )
        return vp, renderer, bus

    def test_direct_mesh_selection_highlights_that_mesh(self):
        vp, renderer, bus = self._make_viewport()
        bus.publish(["/World/GroupA/MeshA"], source="stage")
        assert renderer._selected_paths == ["/World/GroupA/MeshA"]
        assert vp._transform_model._selected_paths == ["/World/GroupA/MeshA"]
        vp.destroy()

    def test_parent_selection_highlights_immediate_and_deep_mesh_descendants(self):
        vp, renderer, bus = self._make_viewport()
        bus.publish(["/World/GroupA"], source="stage")
        assert renderer._selected_paths == [
            "/World/GroupA/MeshA",
            "/World/GroupA/ChildGroup/MeshB",
            "/World/GroupA/ChildGroup/GrandChildGroup/MeshC",
        ]
        assert vp._transform_model._selected_paths == ["/World/GroupA"]
        vp.destroy()

    def test_child_parent_selection_highlights_deeper_descendant_mesh(self):
        vp, renderer, bus = self._make_viewport()
        bus.publish(["/World/GroupA/ChildGroup"], source="stage")
        assert renderer._selected_paths == [
            "/World/GroupA/ChildGroup/MeshB",
            "/World/GroupA/ChildGroup/GrandChildGroup/MeshC",
        ]
        vp.destroy()

    def test_multi_selection_unions_descendant_meshes_without_duplicates(self):
        vp, renderer, bus = self._make_viewport()
        bus.publish(
            [
                "/World/GroupA",
                "/World/GroupA/MeshA",
                "/World/MeshOutside",
            ],
            source="stage",
        )
        assert renderer._selected_paths == [
            "/World/GroupA/MeshA",
            "/World/GroupA/ChildGroup/MeshB",
            "/World/GroupA/ChildGroup/GrandChildGroup/MeshC",
            "/World/MeshOutside",
        ]
        vp.destroy()

    def test_empty_parent_selection_clears_renderer_highlights(self):
        vp, renderer, bus = self._make_viewport()
        bus.publish(["/World/GroupA/MeshA"], source="stage")
        assert renderer._selected_paths == ["/World/GroupA/MeshA"]
        bus.publish(["/World/EmptyGroup"], source="stage")
        assert renderer._selected_paths == []
        assert vp._transform_model._selected_paths == ["/World/EmptyGroup"]
        vp.destroy()

    def test_selection_highlight_retries_once_after_render_for_created_prims(self):
        from ovui_widgets.common.selection import SelectionBus

        adapter = _FakeHierarchyStageAdapter()
        renderer = _CountingSelectionHighlightRenderer()
        bus = SelectionBus()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            bus=bus,
            stage_adapter_provider=lambda: adapter,
        )
        vp._image = _VisibleViewportImage()
        try:
            initial_call_count = len(renderer.highlight_calls)
            bus.publish(["/World/GroupA/MeshA"], source="qa_tools.create_prims")

            assert renderer.highlight_calls[-1] == ["/World/GroupA/MeshA"]
            assert len(renderer.highlight_calls) == initial_call_count + 1
            assert vp._selection_highlight_retry_paths == ["/World/GroupA/MeshA"]

            assert vp.render(0.1) is True

            assert renderer.highlight_calls[-1] == ["/World/GroupA/MeshA"]
            assert len(renderer.highlight_calls) == initial_call_count + 2
            assert vp._selection_highlight_retry_paths is None

            assert vp.render(0.1) is True
            assert len(renderer.highlight_calls) == initial_call_count + 2
        finally:
            vp.destroy()


class TestViewportWidgetLayout:
    def test_viewport_surface_builds_into_caller_owned_frame(self):
        renderer = MockRendererAdapter()
        surface = ViewportSurface(
            services=None,
            renderer=renderer,
            chrome_options=_hidden_chrome_options(),
        )
        frame = _FakeFrame()

        surface.build_into(frame)

        assert frame.build_fn is not None
        assert getattr(frame.build_fn, "__self__", None) is surface
        assert getattr(frame.build_fn, "__func__", None) is ViewportSurface._build_ui
        assert not hasattr(surface, "_window")

        _build_viewport(surface, frame.build_fn)

        assert surface._image is not None
        assert isinstance(surface._bridge, ImageBridge)
        assert surface._scene_view is not None
        assert surface._camera_manipulator is not None
        assert surface._transform_manipulator is not None
        assert surface._tool_registry is not None
        assert surface._toolbar_frame is None
        assert surface._scene_value_label is None
        assert surface._fps_value_label is None
        assert surface._resolution_value_label is None
        assert surface._livestream_row is None
        surface._image = _VisibleViewportImage()
        assert surface.render(0.1) is True
        assert renderer.render_call_count == 1
        assert surface._last_resolution == (640, 360)
        surface.destroy()

    def test_viewport_surface_rejects_non_frame_embedding_target(self):
        surface = ViewportSurface(services=None, renderer=MockRendererAdapter())
        try:
            with pytest.raises(TypeError, match="requires a frame with set_build_fn"):
                surface.build_into(object())
        finally:
            surface.destroy()

    def test_viewport_widget_wraps_same_surface_lifecycle(self):
        renderer = MockRendererAdapter()
        widget = ViewportWidget(
            services=None,
            renderer=renderer,
            chrome_options=_hidden_chrome_options(),
        )

        assert isinstance(widget, ViewportSurface)
        assert widget.window is not None

        _build_viewport(widget)

        assert widget._image is not None
        assert widget._scene_view is not None
        assert widget._camera_manipulator is not None
        assert widget._transform_manipulator is not None
        assert widget._tool_registry is not None
        assert widget._toolbar_frame is None
        assert widget._scene_value_label is None
        widget.destroy()

    def test_image_widget_created_after_build(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert vp._image is not None
        vp.destroy()

    def test_default_chrome_options_preserve_desktop_viewport_chrome(self):
        panel_builds = []
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp.viewport_hooks.add(
            ViewportAnchoredPanel(
                id="test.panel",
                label="Test Panel",
                build_fn=lambda context: panel_builds.append(context.anchor),
            )
        )
        vp._build_ui()

        assert vp.chrome_options == ViewportChromeOptions()
        assert vp._toolbar_frame is not None
        assert [
            entry.widget_name
            for entry in vp._pre_tools_toolbar_hooks.iter_contributions()
        ] == ["viewport_toolbar_settings"]
        assert vp._scene_value_label is not None
        assert vp._fps_value_label is not None
        assert vp._resolution_value_label is not None
        assert vp._livestream_row is not None
        assert panel_builds == ["top_left"]
        vp.destroy()

    def test_hidden_chrome_options_skip_server_chrome_not_viewport_internals(self):
        panel_builds = []
        frame_updates = []
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            chrome_options=ViewportChromeOptions(
                show_toolbar=False,
                show_text_hud=False,
                show_livestream_overlay=False,
                show_anchored_panels=False,
            ),
        )
        vp.viewport_hooks.add(
            ViewportAnchoredPanel(
                id="test.panel",
                label="Test Panel",
                build_fn=lambda context: panel_builds.append(context.anchor),
            )
        )
        vp.viewport_hooks.add(
            ViewportPointCloudRenderer(
                id="test.frame",
                label="Test Frame",
                update_fn=lambda context: frame_updates.append(
                    (context.width, context.height, context.scene_view is vp._scene_view)
                ),
            )
        )
        vp._build_ui()
        vp._image = _VisibleViewportImage()

        assert vp._toolbar_frame is None
        assert vp._toolbar_buttons == {}
        assert vp._scene_value_label is None
        assert vp._fps_value_label is None
        assert vp._resolution_value_label is None
        assert vp._livestream_row is None
        assert panel_builds == []

        assert isinstance(vp._bridge, ImageBridge)
        assert vp._bridge.provider is not None
        assert vp._image is not None
        assert vp._scene_view is not None
        assert vp._camera_manipulator is not None
        assert vp._transform_manipulator is not None
        assert vp._tool_registry is not None
        assert vp.viewport_hooks is not None
        assert vp.render(0.1) is True
        assert frame_updates == [(640, 360, True)]
        vp.destroy()

    def test_hidden_chrome_state_snapshot_exposes_toolbar_and_hud_state(self):
        renderer = MockRendererAdapter()
        renderer.livestream = _FakeLivestreamTap()
        stage_adapter = _FakeCameraStageAdapter(
            choices=(StageChoice("/World/CameraA", "Camera A"),),
            poses={
                "/World/CameraA": BoundCameraPose(
                    eye=(0.0, 0.0, 8.0),
                    target=(0.0, 0.0, 0.0),
                    up_axis="Y",
                    fov_degrees=60.0,
                    prim_path="/World/CameraA",
                )
            },
        )
        surface = ViewportSurface(
            services=None,
            renderer=renderer,
            stage_adapter_provider=lambda: stage_adapter,
            chrome_options=_hidden_chrome_options(),
        )
        surface.toolbar_hooks.add(
            ViewportToolbarAction(
                id="render_target.main",
                label="Main Render Target",
                tooltip="Switch render target",
            )
        )
        surface.toolbar_hooks.add(
            ViewportStatusBadge(
                id="rendervar.albedo",
                label="Albedo",
                text_fn=lambda _owner: "Albedo",
                tooltip_fn=lambda _owner: "RenderVar output",
            )
        )
        surface.viewport_hooks.add(
            ViewportOutputPreset(
                id="rendervar.depth",
                label="Depth",
            )
        )

        _build_viewport(surface)
        assert surface._toolbar_frame is None
        assert surface._scene_value_label is None
        assert surface._fps_value_label is None
        assert surface._resolution_value_label is None
        assert surface._livestream_row is None

        assert surface.select_camera_path("/World/CameraA") is True
        assert surface.set_active_tool(TOOL_ROTATE) is True
        surface.set_scene_name("sample.usda")
        surface._image = _VisibleViewportImage()
        assert surface.render(0.1) is True

        snapshot = surface.get_viewport_state_snapshot()

        assert snapshot.active_tool == TOOL_ROTATE
        rotate = next(tool for tool in snapshot.tools if tool.id == TOOL_ROTATE)
        assert rotate.active is True
        assert rotate.enabled is True
        assert snapshot.active_camera_path == "/World/CameraA"
        assert [(camera.path, camera.label, camera.active) for camera in snapshot.cameras] == [
            ("/World/CameraA", "Camera A", True)
        ]
        toolbar_by_id = {item.id: item for item in snapshot.toolbar_contributions}
        assert toolbar_by_id["render_target.main"].label == "Main Render Target"
        assert toolbar_by_id["render_target.main"].tooltip == "Switch render target"
        assert toolbar_by_id["rendervar.albedo"].text == "Albedo"
        assert toolbar_by_id["rendervar.albedo"].tooltip == "RenderVar output"
        output_by_id = {item.id: item for item in snapshot.output_contributions}
        assert output_by_id["rendervar.depth"].label == "Depth"
        assert snapshot.hud.scene == "sample.usda"
        assert snapshot.hud.fps_text == "10"
        assert snapshot.hud.resolution == (640, 360)
        assert snapshot.hud.resolution_text == "640×360"
        assert snapshot.hud.stream_state == "LISTENING"
        assert snapshot.hud.stream_text == "Listening :49100/47999"
        assert "PathTracing" not in snapshot.hud.stream_text
        assert not hasattr(snapshot.hud, "render_progress")
        assert not hasattr(snapshot.hud, "path_tracing_status")
        surface.destroy()

    def test_hidden_chrome_uses_default_scene_and_manipulators(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            chrome_options=ViewportChromeOptions(
                show_toolbar=False,
                show_text_hud=False,
                show_livestream_overlay=False,
                show_anchored_panels=False,
            ),
        )
        try:
            vp._build_ui()
            state = vp.get_manipulator_scene_backend_state()
            assert state["backend"] == "default"
            assert state["fallback_to_default_scene"] is False
            assert state["transform_manipulator_present"] is True
            assert vp._camera_manipulator is not None
            assert vp._transform_manipulator is not None
        finally:
            vp.destroy()

    def test_hidden_chrome_preserves_pick_and_marquee_gestures(self, monkeypatch):
        import ovui_widgets.viewport.viewport_widget as viewport_mod

        created_screens = []
        original_screen = viewport_mod.sc.Screen

        def spy_screen(*args, **kwargs):
            created_screens.append(tuple(kwargs.get("gestures") or ()))
            return original_screen(*args, **kwargs)

        monkeypatch.setattr(viewport_mod.sc, "Screen", spy_screen)
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            chrome_options=ViewportChromeOptions(
                show_toolbar=False,
                show_text_hud=False,
                show_livestream_overlay=False,
                show_anchored_panels=False,
            ),
        )
        vp._build_ui()

        assert len(created_screens) == 1
        gestures = created_screens[0]
        point_picks = [g for g in gestures if isinstance(g, PickGesture)]
        marquee_picks = [g for g in gestures if isinstance(g, PickRectGesture)]
        assert len(point_picks) == 3
        assert len(marquee_picks) == 3
        assert all(getattr(g, "_callback", None) is not None for g in gestures)
        assert all(
            getattr(g, "_viewport_pick_manager", None) is vp._pick_manager
            for g in gestures
        )
        assert vp._pick_manager is not None
        assert vp._tool_registry is not None
        vp.destroy()

    def test_hidden_chrome_preserves_selection_highlight_renderer_path(self):
        bus = SelectionBus()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            bus=bus,
            chrome_options=ViewportChromeOptions(
                show_toolbar=False,
                show_text_hud=False,
                show_livestream_overlay=False,
                show_anchored_panels=False,
            ),
        )

        bus.publish(["/World/Cube"], source="test")

        assert renderer._selected_paths == ["/World/Cube"]
        assert vp._transform_model._selected_paths == ["/World/Cube"]
        vp.destroy()

    def test_toolbar_hidden_attach_stage_wires_transform_model_adapters(self):
        from unittest.mock import MagicMock

        class _CameraBindingRenderer(MockRendererAdapter):
            def __init__(self):
                super().__init__()
                self.active_camera_paths = []

            def set_active_camera_path(self, path):
                self.active_camera_paths.append(path)
                return True

        renderer = _CameraBindingRenderer()
        transform_adapter = MagicMock(name="transform_adapter")
        stage_adapter = MagicMock(name="stage_adapter")
        undo_manager = MagicMock(name="undo_manager")
        snap_system = MagicMock(name="snap_system")
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            chrome_options=ViewportChromeOptions(show_toolbar=False),
        )
        vp._build_ui()

        vp.attach_stage(
            transform_adapter=transform_adapter,
            stage_adapter=stage_adapter,
            undo_manager=undo_manager,
            snap_system=snap_system,
        )

        model = vp._transform_model
        assert model._transform is transform_adapter
        assert model._stage is stage_adapter
        assert model._undo is undo_manager
        assert model._snap is snap_system
        assert model.renderer_adapter is renderer
        assert model.has_adapters() is True
        assert renderer.active_camera_paths == [None]
        vp.destroy()

    def test_hidden_chrome_attached_stage_renders_real_viewport_surfaces(
        self,
        monkeypatch,
    ):
        import ovui_widgets.viewport.viewport_widget as viewport_mod

        screen_gesture_sets = []
        frame_updates = []
        original_screen = viewport_mod.sc.Screen

        def spy_screen(*args, **kwargs):
            screen_gesture_sets.append(tuple(kwargs.get("gestures") or ()))
            return original_screen(*args, **kwargs)

        monkeypatch.setattr(viewport_mod.sc, "Screen", spy_screen)

        renderer = MockRendererAdapter()
        stage_adapter = MockStageAdapter()
        transform_adapter = MockTransformAdapter()
        undo_manager = UndoManager()
        bus = SelectionBus()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            bus=bus,
            stage_adapter_provider=lambda: stage_adapter,
            chrome_options=ViewportChromeOptions(
                show_toolbar=False,
                show_text_hud=False,
                show_livestream_overlay=False,
                show_anchored_panels=False,
            ),
        )
        vp.viewport_hooks.add(
            ViewportPointCloudRenderer(
                id="test.render.probe",
                label="Test Render Probe",
                update_fn=lambda context: frame_updates.append(
                    (
                        context.width,
                        context.height,
                        context.scene_view is vp._scene_view,
                    )
                ),
            )
        )

        vp._build_ui()

        vp.attach_stage(
            transform_adapter=transform_adapter,
            stage_adapter=stage_adapter,
            undo_manager=undo_manager,
            snap_system=None,
        )
        renderer.load_stage(stage_adapter)
        vp._image = _VisibleViewportImage()
        bus.publish(["/World/Geometry/Cube"], source="test")

        assert vp._toolbar_frame is None
        assert vp._scene_value_label is None
        assert vp._fps_value_label is None
        assert vp._resolution_value_label is None
        assert vp._livestream_row is None

        state = vp.get_manipulator_scene_backend_state()
        assert state["backend"] == "default"
        assert state["fallback_to_default_scene"] is False
        assert state["transform_manipulator_present"] is True
        assert vp._camera_manipulator is not None
        assert vp._transform_manipulator is not None
        assert vp._tool_registry is not None
        assert vp._pick_manager is not None
        assert vp._transform_model.has_adapters() is True
        assert vp._transform_model.renderer_adapter is renderer
        assert renderer._selected_paths == ["/World/Geometry/Cube"]

        assert len(screen_gesture_sets) == 1
        gestures = screen_gesture_sets[0]
        assert len([g for g in gestures if isinstance(g, PickGesture)]) == 3
        assert len([g for g in gestures if isinstance(g, PickRectGesture)]) == 3

        assert vp.render(0.1) is True
        assert renderer.render_call_count == 1
        assert vp._last_image_frame is not None
        assert frame_updates == [(640, 360, True)]
        vp.destroy()

    def test_streamed_transform_drag_routes_to_real_translate_gesture(self):
        surface, renderer, transform, undo = _make_streamed_transform_surface()
        path = "/World/Geometry/Cube"
        initial = transform.get_local_transform(path)

        began = surface.handle_streamed_transform_pointer_event(
            event_type="button",
            x=130,
            y=100,
            button=1,
            pressed=True,
            width=200,
            height=200,
        )
        preview = surface.handle_streamed_transform_pointer_event(
            event_type="move",
            x=150,
            y=100,
            width=200,
            height=200,
        )
        committed = surface.handle_streamed_transform_pointer_event(
            event_type="button",
            x=150,
            y=100,
            button=1,
            pressed=False,
            width=200,
            height=200,
        )

        final = transform.get_local_transform(path)
        assert began["handled"] is True
        assert began["phase"] == "begin"
        assert began["reason"] == "real_translate_handle_hit"
        assert preview["handled"] is True
        assert preview["phase"] == "preview"
        assert preview["preview_applied"] is True
        assert path in renderer.cleared_live_paths[-1]
        assert final != initial
        assert final[3][0] > initial[3][0]
        assert committed["handled"] is True
        assert committed["phase"] == "commit"
        assert committed["committed"] is True
        assert committed["changed_paths"] == [path]
        assert committed["property_changed"] is True
        assert committed["usd_changed"] is True
        assert committed["command_history_added"] is True
        assert committed["undo_changed"] is True
        assert undo.can_undo() is True
        assert renderer.live_transforms == {}
        surface.destroy()

    def test_streamed_transform_drag_syncs_stale_model_from_selection_bus(self):
        bus = SelectionBus()
        surface, renderer, transform, undo = _make_streamed_transform_surface(bus=bus)
        path = "/World/Geometry/Cube"
        bus.publish([path], source="viewport-pick")
        surface._transform_model.set_selection([])

        began = surface.handle_streamed_transform_pointer_event(
            event_type="button",
            x=130,
            y=100,
            button=1,
            pressed=True,
            width=200,
            height=200,
        )

        assert began["handled"] is True
        assert began["phase"] == "begin"
        assert began["reason"] == "real_translate_handle_hit"
        assert began["selected_paths"] == [path]
        assert surface._transform_model.has_transformable_selection() is True
        surface.handle_streamed_transform_pointer_event(
            event_type="cancel",
            width=200,
            height=200,
        )
        assert undo.can_undo() is False
        assert renderer.live_transforms == {}
        surface.destroy()

    def test_sync_selection_from_bus_updates_viewport_visual_state(self):
        bus = SelectionBus()
        surface, renderer, transform, undo = _make_streamed_transform_surface(bus=bus)
        path = "/World/Geometry/Cube"
        surface._transform_model.set_selection([])
        renderer.set_selection_highlight([])

        bus.publish([path], source="backend-viewport-pick")
        synced = surface.sync_selection_from_bus()

        assert synced == [path]
        assert renderer._selected_paths == [path]
        assert surface._transform_model._raw_selected_paths == [path]
        assert surface._transform_model._selected_paths == [path]
        assert surface._transform_model.has_transformable_selection() is True
        surface.destroy()

    def test_streamed_transform_handle_projections_use_real_selection(self):
        surface, renderer, transform, undo = _make_streamed_transform_surface()
        path = "/World/Geometry/Cube"

        projections = surface.get_streamed_transform_handle_projections(200, 200)

        assert projections["available"] is True
        assert projections["selected_paths"] == [path]
        assert projections["raw_selected_paths"] == [path]
        assert projections["reason"] == "projected"
        assert projections["width"] == 200
        assert projections["height"] == 200
        assert {axis["axis"] for axis in projections["axes"]} == {"x", "y", "z"}
        assert any(axis["start"] is not None and axis["end"] is not None for axis in projections["axes"])
        surface.destroy()

    def test_z_up_camera_projects_and_hits_world_z_transform_handle(self):
        from ovui_widgets.viewport.camera_controller import CameraController

        surface, renderer, transform, undo = _make_streamed_transform_surface()
        surface._camera = CameraController()
        surface._camera.set_pose(
            eye=(3.0, -5.0, 4.0),
            target=(0.0, 0.0, 0.0),
            up_axis="Z",
        )

        projections = surface.get_streamed_transform_handle_projections(800, 600)
        z_axis = next(axis for axis in projections["axes"] if axis["axis"] == "z")
        start = z_axis["start"]
        end = z_axis["end"]
        hit = surface._hit_streamed_translate_handle(
            round(start[0] * 0.2 + end[0] * 0.8),
            round(start[1] * 0.2 + end[1] * 0.8),
            800,
            600,
        )

        assert projections["available"] is True
        assert surface._camera.up_axis == pytest.approx([0.0, 0.0, 1.0])
        assert start != pytest.approx(end)
        assert hit is not None
        assert hit["axis"] == "z"
        surface.destroy()

    def test_streamed_transform_escape_cancels_preview_without_commit(self):
        surface, renderer, transform, undo = _make_streamed_transform_surface()
        path = "/World/Geometry/Cube"
        initial = transform.get_local_transform(path)

        surface.handle_streamed_transform_pointer_event(
            event_type="button",
            x=130,
            y=100,
            button=1,
            pressed=True,
            width=200,
            height=200,
        )
        preview = surface.handle_streamed_transform_pointer_event(
            event_type="move",
            x=150,
            y=100,
            width=200,
            height=200,
        )
        canceled = surface.handle_streamed_transform_pointer_event(
            event_type="key_down",
            key_code=27,
            width=200,
            height=200,
        )

        assert preview["preview_applied"] is True
        assert canceled["handled"] is True
        assert canceled["phase"] == "cancel"
        assert canceled["cancel_restored"] is True
        assert transform.get_local_transform(path) == initial
        assert undo.can_undo() is False
        assert renderer.live_transforms == {}
        assert renderer.cleared_live_paths[-1] == [path]
        surface.destroy()

    def test_streamed_transform_cancel_event_restores_preview_without_commit(self):
        surface, renderer, transform, undo = _make_streamed_transform_surface()
        path = "/World/Geometry/Cube"
        initial = transform.get_local_transform(path)

        surface.handle_streamed_transform_pointer_event(
            event_type="button",
            x=130,
            y=100,
            button=1,
            pressed=True,
            width=200,
            height=200,
        )
        preview = surface.handle_streamed_transform_pointer_event(
            event_type="move",
            x=150,
            y=100,
            width=200,
            height=200,
        )
        canceled = surface.handle_streamed_transform_pointer_event(
            event_type="cancel",
            width=200,
            height=200,
        )

        assert preview["preview_applied"] is True
        assert canceled["handled"] is True
        assert canceled["phase"] == "cancel"
        assert canceled["reason"] == "stream_disconnect"
        assert canceled["cancel_restored"] is True
        assert transform.get_local_transform(path) == initial
        assert undo.can_undo() is False
        assert renderer.live_transforms == {}
        assert renderer.cleared_live_paths[-1] == [path]
        surface.destroy()

    def test_chrome_options_can_hide_toolbar_independently(self, monkeypatch):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.common.style.urls import get_icon_path
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        order = []
        original_invisible_button = viewport_mod.ui.InvisibleButton

        def spy_invisible_button(*args, **kwargs):
            identifier = str(kwargs.get("identifier") or "")
            if identifier.startswith("viewport_toolbar_") or identifier.startswith(
                "qa_tools_"
            ):
                order.append(identifier)
            return original_invisible_button(*args, **kwargs)

        monkeypatch.setattr(viewport_mod.ui, "InvisibleButton", spy_invisible_button)
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            chrome_options={"show_toolbar": False},
        )
        vp.toolbar_hooks.add(
            ViewportToolbarMenu(
                id="qa_tools.render_target_picker",
                label="Render Target",
                tooltip="Render Target",
                icon_path=get_icon_path("content_gear"),
                widget_name="qa_tools_render_target_menu",
            )
        )
        vp._build_ui()

        assert vp._toolbar_frame is None
        assert vp._pre_tools_toolbar_hooks.iter_contributions() == ()
        assert [entry.widget_name for entry in vp.toolbar_hooks.iter_contributions()] == [
            "qa_tools_render_target_menu"
        ]
        assert order == []
        assert vp._scene_value_label is not None
        assert vp._livestream_row is not None
        assert vp._transform_manipulator is not None
        assert vp._tool_registry is not None
        vp.destroy()

    def test_chrome_options_can_hide_settings_button_independently(self, monkeypatch):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.common.style.urls import get_icon_path
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        order = []
        original_invisible_button = viewport_mod.ui.InvisibleButton

        def spy_invisible_button(*args, **kwargs):
            identifier = str(kwargs.get("identifier") or "")
            if identifier.startswith("viewport_toolbar_") or identifier.startswith(
                "qa_tools_"
            ):
                order.append(identifier)
            return original_invisible_button(*args, **kwargs)

        monkeypatch.setattr(viewport_mod.ui, "InvisibleButton", spy_invisible_button)
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            chrome_options={"show_settings_button": False},
        )
        vp.toolbar_hooks.add(
            ViewportToolbarMenu(
                id="qa_tools.render_target_picker",
                label="Render Target",
                tooltip="Render Target",
                icon_path=get_icon_path("content_gear"),
                widget_name="qa_tools_render_target_menu",
            )
        )
        vp._build_ui()

        assert vp._toolbar_frame is not None
        assert vp._pre_tools_toolbar_hooks.iter_contributions() == ()
        assert order == [
            "viewport_toolbar_translate",
            "viewport_toolbar_rotate",
            "viewport_toolbar_scale",
            "viewport_toolbar_camera",
            "qa_tools_render_target_menu",
        ]
        assert vp._scene_value_label is not None
        assert vp._livestream_row is not None
        assert vp._transform_manipulator is not None
        assert vp._tool_registry is not None
        vp.destroy()

    def test_chrome_options_can_hide_text_hud_independently(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            chrome_options=ViewportChromeOptions(show_text_hud=False),
        )
        vp._build_ui()

        assert vp._toolbar_frame is not None
        assert vp._scene_value_label is None
        assert vp._fps_value_label is None
        assert vp._resolution_value_label is None
        assert vp._livestream_row is not None
        assert vp._scene_view is not None
        vp.destroy()

    def test_chrome_options_can_hide_livestream_overlay_independently(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            chrome_options=ViewportChromeOptions(show_livestream_overlay=False),
        )
        vp._build_ui()

        assert vp._toolbar_frame is not None
        assert vp._scene_value_label is not None
        assert vp._livestream_row is None
        assert vp._scene_view is not None
        vp.destroy()

    def test_chrome_options_can_hide_anchored_panels_independently(self):
        panel_builds = []
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            chrome_options=ViewportChromeOptions(show_anchored_panels=False),
        )
        vp.viewport_hooks.add(
            ViewportAnchoredPanel(
                id="test.panel",
                label="Test Panel",
                build_fn=lambda context: panel_builds.append(context.anchor),
            )
        )
        vp._build_ui()

        assert panel_builds == []
        assert vp._toolbar_frame is not None
        assert vp._scene_value_label is not None
        assert vp._livestream_row is not None
        assert vp._scene_view is not None
        vp.destroy()

    def test_fps_label_created_after_build(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert vp._fps_label is not None
        vp.destroy()

    def test_fps_label_is_ui_label(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert isinstance(vp._fps_label, ui.Label)
        vp.destroy()


class TestViewportWidgetOnFrame:
    def test_on_frame_before_build_no_crash(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        # _image is None before build — _on_frame should guard against this
        vp._on_frame(0.016)
        vp.destroy()

    def test_on_frame_after_build_updates_fps(self):
        from unittest.mock import MagicMock
        renderer = MagicMock()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        # _build_ui's real ImageWithProvider has computed_width=0 in the
        # test harness, so swap in a fake image with non-zero size — the
        # FPS HUD only updates inside the render() body, which exits early
        # for zero-size widgets in the new architecture.
        img = MagicMock()
        img.visible = True
        img.computed_width = 800
        img.computed_height = 600
        vp._image = img
        renderer.render_frame.side_effect = lambda rw, rh, _v, _p: np.zeros(
            (int(rh), int(rw), 4), dtype=np.uint8
        )
        vp._on_frame(0.1)  # 10 FPS — passes the legacy shim's gate
        if vp._fps_label is not None:
            assert "10" in vp._fps_label.text
        vp.destroy()


class TestCameraNavigationState:
    def test_helper_starts_settled_and_clears_dirty_after_settle(self):
        state = CameraNavigationState(stable_frame_threshold=2)

        assert not state.is_active
        assert not state.is_dirty
        assert state.observe(("baseline",)) is False
        assert state.settled_signature == ("baseline",)

        assert state.observe(("moved",)) is True
        assert state.is_active
        assert state.is_dirty
        assert state.dirty_signature == ("moved",)
        assert state.observe(("moved",)) is False
        assert state.is_active
        assert state.observe(("moved",)) is False

        assert not state.is_active
        assert state.is_dirty
        assert state.settled_signature == ("moved",)

        state.clear_dirty()
        assert not state.is_dirty
        assert state.dirty_signature is None

    def test_helper_missing_signature_resets_to_settled(self):
        state = CameraNavigationState(stable_frame_threshold=2)
        state.observe(("baseline",))
        state.observe(("moved",))

        assert state.is_active
        assert state.is_dirty

        state.observe(None)

        assert not state.is_active
        assert not state.is_dirty
        assert state.last_signature is None


class TestViewportCameraNavigationTracking:
    def test_fresh_widget_starts_not_navigating(self):
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            assert not vp.is_camera_navigation_active()
            assert not vp.has_dirty_camera_navigation()
            assert vp._camera_navigation_state.last_signature is None
        finally:
            vp.destroy()

    def test_signature_change_marks_active_then_settles_without_end_event(self):
        vp = _make_renderable_viewport()
        try:
            assert vp.render(0.1) is True
            baseline = vp._camera_navigation_state.last_signature
            assert baseline is not None
            assert not vp.is_camera_navigation_active()
            assert not vp.has_dirty_camera_navigation()

            vp._camera.orbit(0.1, 0.02)
            assert vp.render(0.1) is True

            assert vp.is_camera_navigation_active()
            assert vp.has_dirty_camera_navigation()
            assert vp._camera_navigation_state.dirty_signature != baseline

            assert vp.render(0.1) is True
            assert vp.is_camera_navigation_active()
            assert vp.render(0.1) is True

            assert not vp.is_camera_navigation_active()
            assert vp.has_dirty_camera_navigation()
            assert (
                vp._camera_navigation_state.settled_signature
                == vp._camera_navigation_state.last_signature
            )
        finally:
            vp.destroy()

    def test_selected_camera_navigation_marks_active_without_authoring_change(self):
        pose = BoundCameraPose(
            eye=(0.0, 3.0, 12.0),
            target=(0.0, 0.0, 0.0),
            up_axis="Y",
            fov_degrees=45.0,
            prim_path="/World/Camera1",
        )
        adapter = _FakeCameraStageAdapter(poses={"/World/Camera1": pose})
        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._select_camera_path("/World/Camera1") is True
            assert not vp.is_camera_navigation_active()
            assert not vp.has_dirty_camera_navigation()

            vp._camera.orbit(0.1, 0.02)
            assert vp.render(0.1) is True

            assert vp.is_camera_navigation_active()
            assert vp.has_dirty_camera_navigation()
        finally:
            vp.destroy()

    def test_matching_selected_camera_author_signature_clears_dirty(self):
        pose = BoundCameraPose(
            eye=(0.0, 3.0, 12.0),
            target=(0.0, 0.0, 0.0),
            up_axis="Y",
            fov_degrees=45.0,
            prim_path="/World/Camera1",
        )
        adapter = _FakeCameraStageAdapter(poses={"/World/Camera1": pose})
        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._select_camera_path("/World/Camera1") is True
            signature = vp._camera_navigation_signature()
            vp._camera_navigation_state.reset(("stale",))
            vp._camera_navigation_state.observe(signature)
            assert vp.has_dirty_camera_navigation()

            view, projection = vp._camera.get_matrices(640, 360)
            assert vp._author_active_camera_pose(view, projection, 640, 360) is False

            assert not vp.has_dirty_camera_navigation()
        finally:
            vp.destroy()

    @pytest.mark.parametrize(
        ("label", "mutate"),
        (
            ("orbit", lambda vp: vp._camera.orbit(0.1, 0.02)),
            ("pan", lambda vp: vp._camera.pan(0.5, 0.25)),
            ("zoom", lambda vp: vp._camera.zoom(1.0)),
        ),
        ids=("orbit", "pan", "zoom"),
    )
    def test_orbit_pan_and_zoom_mark_navigation_active(self, label, mutate):
        vp = _make_renderable_viewport()
        try:
            assert vp.render(0.1) is True
            mutate(vp)
            assert vp.render(0.1) is True

            assert vp.is_camera_navigation_active(), label
            assert vp.has_dirty_camera_navigation(), label
        finally:
            vp.destroy()


class TestViewportWidgetDestroy:
    def test_destroy_is_safe(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp.destroy()  # must not raise

    def test_destroy_calls_renderer_shutdown(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp.destroy()
        assert renderer._shutdown_called

    def test_double_destroy_is_safe(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp.destroy()
        # Second destroy should not crash (renderer already shut down)
        # ManagedWindow.destroy guards with _window is None
        vp.destroy()


# ---------------------------------------------------------------------------
# Step 18 — corner HUD label/value overlays
# ---------------------------------------------------------------------------

class TestViewportHUDOverlay:
    def test_scene_label_created_after_build(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert vp._scene_value_label is not None
        assert isinstance(vp._scene_value_label, ui.Label)
        vp.destroy()

    def test_fps_and_resolution_labels_created_after_build(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert isinstance(vp._fps_value_label, ui.Label)
        assert isinstance(vp._resolution_value_label, ui.Label)
        vp.destroy()

    def test_set_scene_name_updates_scene_value(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        vp.set_scene_name("simple_scene.usda")
        assert vp._scene_value_label.text == "simple_scene.usda"
        vp.destroy()

    def test_set_scene_name_none_clears_and_hides_scene_row(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        vp.set_scene_name("simple_scene.usda")
        vp.set_scene_name(None)
        assert vp._scene_value_label.text == ""
        assert vp._scene_row.visible is False
        vp.destroy()

    def test_update_prim_count_stores_value_without_viewport_hud_text(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        vp.update_prim_count(1234)
        assert vp._prim_count == 1234
        assert vp._prim_count_label is None
        vp.destroy()

    def test_update_prim_count_before_build_no_crash(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp.update_prim_count(100)  # _prim_count_label is None — must not raise
        assert vp._prim_count == 100
        vp.destroy()

    def test_fps_label_alias_points_to_value_label(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert vp._fps_label is vp._fps_value_label
        vp.destroy()

    def test_refresh_hud_formats_resolution_with_multiplication_sign(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        vp._last_fps = 24.0
        vp._last_resolution = (1920, 1080)
        vp._refresh_hud()
        assert vp._fps_value_label.text == "24"
        assert vp._resolution_value_label.text == "1920×1080"
        vp.destroy()

    def test_refresh_hud_prefers_committed_effective_size(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        vp._last_resolution = (1920, 1080)
        vp.set_resolution_state(effective_size=(960, 540))
        vp._refresh_hud()
        assert vp._resolution_value_label.text == "960×540"
        vp.destroy()

    def test_refresh_hud_falls_back_to_last_render_size_for_event_gap(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        vp.set_resolution_state(effective_size=None)
        vp._last_resolution = (1280, 720)
        vp._refresh_hud()
        assert vp._resolution_value_label.text == "1280×720"
        vp.destroy()

    @pytest.mark.parametrize(
        "label,requested_size,scale,fill_viewport,frame_size,expected",
        (
            ("HD1080P", (1920, 1080), 1.0, False, (1600, 900), (1920, 1080)),
            ("HD1080P", (1920, 1080), 0.5, False, (1600, 900), (960, 540)),
            ("Icon", (512, 512), 0.25, False, (1600, 900), (128, 128)),
            ("UHD", (3840, 2160), 2.0, False, (1600, 900), (3840, 2160)),
            ("Square", (1024, 1024), 1.0, True, (1600, 900), (1820, 1024)),
            ("Custom", (1500, 1000), 1.0, False, (1600, 900), (1500, 1000)),
        ),
    )
    def test_render_updates_existing_hud_from_effective_size_workflows(
        self,
        label,
        requested_size,
        scale,
        fill_viewport,
        frame_size,
        expected,
    ):
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=frame_size[0],
            computed_height=frame_size[1],
        )
        vp._resolution_value_label = _FakeLabel()
        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=requested_size,
                scale=scale,
                fill_viewport=fill_viewport,
                selected_label=label,
                effective_size=None,
            )

            assert vp.render(1.0 / 60.0) is True

            state = vp.get_resolution_state()
            assert state.effective_size == expected
            assert vp._last_resolution == expected
            assert vp._resolution_value_label.text == f"{expected[0]}×{expected[1]}"
        finally:
            vp.destroy()

    def test_refresh_hud_hides_separator_until_fps_and_res_exist(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        vp._last_fps = 60.0
        vp._last_resolution = None
        vp._refresh_hud()
        assert vp._fps_res_separator_label.visible is False
        vp._last_resolution = (1280, 720)
        vp._refresh_hud()
        assert vp._fps_res_separator_label.visible is True
        vp.destroy()

    def test_hud_builder_uses_viewport_hud_style_selectors(self, monkeypatch):
        seen = []
        original = ViewportWidget._build_hud_label

        def spy(self, text, style, width=None, alignment=ui.Alignment.LEFT_CENTER):
            seen.append(style)
            return original(self, text, style, width=width, alignment=alignment)

        monkeypatch.setattr(ViewportWidget, "_build_hud_label", spy)
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert "Viewport.HUD.Label" in seen
        assert "Viewport.HUD.Value" in seen
        assert "Viewport.HUD.Separator" in seen
        vp.destroy()

    def test_hud_root_uses_viewport_hud_style_selector(self, monkeypatch):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        seen = []
        original = viewport_mod.ui.ZStack

        def spy_zstack(*args, **kwargs):
            seen.append(kwargs.get("style_type_name_override"))
            return original(*args, **kwargs)

        monkeypatch.setattr(viewport_mod.ui, "ZStack", spy_zstack)
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert "Viewport.HUD" in seen
        vp.destroy()

    def test_shipped_hud_flow_has_no_resolution_diagnostic_overlay(self, monkeypatch):
        monkeypatch.delenv(viewport_mod.AREA1_SETTINGS_SCHEMA_QA_ENV, raising=False)
        monkeypatch.delenv(viewport_mod.AREA2_CATALOG_QA_ENV, raising=False)
        monkeypatch.delenv(viewport_mod.AREA3_RENDER_QA_ENV, raising=False)
        monkeypatch.delenv(viewport_mod.AREA3_INTERACTION_QA_ENV, raising=False)
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert vp._resolution_render_qa_window is None
        assert vp._resolution_catalog_qa_window is None
        assert vp._resolution_settings_schema_qa_window is None
        assert vp._resolution_value_label is not None
        vp.destroy()

class TestViewportToolbar:
    def _record_toolbar_button_order(self, monkeypatch):
        import ovui_widgets.viewport.viewport_widget as viewport_mod

        order = []
        original_invisible_button = viewport_mod.ui.InvisibleButton
        original_button = viewport_mod.ui.Button

        def _record(identifier):
            identifier = str(identifier or "")
            if identifier.startswith("viewport_toolbar_"):
                order.append(identifier)

        def spy_invisible_button(*args, **kwargs):
            _record(kwargs.get("identifier"))
            return original_invisible_button(*args, **kwargs)

        def spy_button(*args, **kwargs):
            _record(kwargs.get("identifier"))
            return original_button(*args, **kwargs)

        monkeypatch.setattr(viewport_mod.ui, "InvisibleButton", spy_invisible_button)
        monkeypatch.setattr(viewport_mod.ui, "Button", spy_button)
        return order

    def _open_settings_menu(self, vp):
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        class _Anchor:
            screen_position_x = 31
            screen_position_y = 47
            computed_height = 20

        contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
        assert isinstance(contribution, ViewportToolbarMenu)
        vp._pre_tools_toolbar_hooks._show_menu(contribution, _Anchor())
        return [
            menu
            for menu in _FakeCameraMenu.instances
            if menu.title == "Settings"
        ][-1]

    def _open_render_resolution_menu(self, vp):
        settings_menu = self._open_settings_menu(vp)
        viewport_menu = settings_menu.submenus[0]
        return viewport_menu.submenus[0]

    def _latest_settings_menu(self):
        return [
            menu
            for menu in _FakeCameraMenu.instances
            if menu.title == "Settings"
        ][-1]

    def _latest_viewport_menu(self):
        return self._latest_settings_menu().submenus[0]

    def _latest_render_resolution_menu(self):
        return self._latest_viewport_menu().submenus[0]

    def _assert_settings_menu_closed(self, vp, settings_menu):
        assert settings_menu.destroyed is True
        assert (
            viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
            not in vp._pre_tools_toolbar_hooks._menus
        )

    def _viewport_submenu(self, viewport_menu, title):
        matches = [menu for menu in viewport_menu.submenus if menu.title == title]
        assert matches, title
        return matches[0]

    def _viewport_item(self, viewport_menu, label):
        matches = [item for item in viewport_menu.items if item.label == label]
        assert matches, label
        return matches[0]

    def test_toolbar_contains_transform_tools_and_camera_selector(self):
        from ovui_widgets.viewport.transform_manipulator import (
            TOOL_ROTATE,
            TOOL_SCALE,
            TOOL_TRANSLATE,
        )

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._build_ui()
        assert vp._toolbar_frame is not None
        assert tuple(vp._toolbar_buttons) == (
            TOOL_TRANSLATE,
            TOOL_ROTATE,
            TOOL_SCALE,
            "camera",
        )
        assert "select" not in vp._toolbar_buttons
        assert "shade" not in vp._toolbar_buttons
        assert "render_product" not in vp._toolbar_buttons
        vp.destroy()

    def test_settings_toolbar_button_occupies_pre_tools_host_before_move(self, monkeypatch):
        import ovui_widgets.viewport.viewport_widget as viewport_mod

        order = self._record_toolbar_button_order(monkeypatch)
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._build_ui()

        assert order == [
            "viewport_toolbar_settings",
            "viewport_toolbar_translate",
            "viewport_toolbar_rotate",
            "viewport_toolbar_scale",
            "viewport_toolbar_camera",
        ]
        assert "viewport_toolbar_pre_tools_host_placeholder" not in order
        assert all("resolution" not in identifier.lower() for identifier in order)
        assert vp.toolbar_hooks.iter_contributions() == ()
        vp.destroy()

    def test_settings_gear_uses_standard_leading_toolbar_registry(self):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.common.style.urls import get_icon_path
        from ovui_widgets.viewport.toolbar_hooks import (
            ViewportToolbarMenu,
            ViewportToolbarRegistry,
        )

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            vp.toolbar_hooks.add(
                ViewportToolbarMenu(
                    id="qa_tools.render_target_picker",
                    label="Render Target",
                    tooltip="Render Target",
                    icon_path=get_icon_path("content_gear"),
                    widget_name="qa_tools_render_target_menu",
                )
            )

            assert isinstance(vp._pre_tools_toolbar_hooks, ViewportToolbarRegistry)
            assert isinstance(vp.toolbar_hooks, ViewportToolbarRegistry)

            leading_contributions = vp._pre_tools_toolbar_hooks.iter_contributions()
            external_contributions = vp.toolbar_hooks.iter_contributions()

            assert [entry.id for entry in leading_contributions] == [
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
            ]
            assert isinstance(leading_contributions[0], ViewportToolbarMenu)
            assert leading_contributions[0].widget_name == "viewport_toolbar_settings"
            assert leading_contributions[0].label == "Settings"
            assert leading_contributions[0].tooltip == "Settings"
            assert leading_contributions[0].icon_path.endswith("content_gear.png")
            assert callable(leading_contributions[0].build_fn)
            assert [entry.widget_name for entry in external_contributions] == [
                "qa_tools_render_target_menu"
            ]
        finally:
            vp.destroy()

    def test_qa_placeholder_env_does_not_replace_product_settings_gear(self, monkeypatch):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.viewport.transform_manipulator import (
            TOOL_ROTATE,
            TOOL_SCALE,
            TOOL_TRANSLATE,
        )

        monkeypatch.setenv(
            viewport_mod.FOUNDATION_QA_PRE_TOOLS_PLACEHOLDER_ENV,
            "1",
        )
        order = self._record_toolbar_button_order(monkeypatch)
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._build_ui()

        assert order == [
            "viewport_toolbar_settings",
            "viewport_toolbar_translate",
            "viewport_toolbar_rotate",
            "viewport_toolbar_scale",
            "viewport_toolbar_camera",
        ]
        assert tuple(vp._toolbar_buttons) == (
            TOOL_TRANSLATE,
            TOOL_ROTATE,
            TOOL_SCALE,
            "camera",
        )
        assert "viewport_toolbar_pre_tools_host_placeholder" not in order
        assert all("resolution" not in identifier.lower() for identifier in order)
        assert order[-1] == "viewport_toolbar_camera"
        vp.destroy()

    def test_settings_toolbar_registration_is_idempotent(self, monkeypatch):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        monkeypatch.setenv(
            viewport_mod.FOUNDATION_QA_PRE_TOOLS_PLACEHOLDER_ENV,
            "true",
        )
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            vp._register_foundation_qa_pre_tools_placeholder()
            contributions = vp._pre_tools_toolbar_hooks.iter_contributions()

            assert [contribution.id for contribution in contributions] == [
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
            ]
            assert [contribution.widget_name for contribution in contributions] == [
                "viewport_toolbar_settings"
            ]
            assert [contribution.label for contribution in contributions] == [
                "Settings"
            ]
            assert [contribution.tooltip for contribution in contributions] == [
                "Settings"
            ]
            assert contributions[0].icon_path.endswith("content_gear.png")
            assert isinstance(contributions[0], ViewportToolbarMenu)
            assert callable(contributions[0].build_fn)
        finally:
            vp.destroy()

    def test_settings_toolbar_menu_opens_single_viewport_submenu_item(
        self, fake_camera_menu
    ):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        class _Anchor:
            screen_position_x = 31
            screen_position_y = 47
            computed_height = 20

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
            assert isinstance(contribution, ViewportToolbarMenu)

            vp._pre_tools_toolbar_hooks._show_menu(contribution, _Anchor())

            menu = fake_camera_menu.instances[0]
            assert menu.title == "Settings"
            assert "delegate" in menu.kwargs
            assert menu.shown_at == (31.0, 67.0)
            assert [submenu.title for submenu in menu.submenus] == ["Viewport"]
            assert menu.items == []
            assert [
                submenu.title
                for submenu in menu.submenus
                if submenu.title != "Viewport"
            ] == []
            assert viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID in (
                vp._pre_tools_toolbar_hooks._menus
            )
        finally:
            vp.destroy()

    def test_settings_toolbar_menu_has_no_direct_resolution_rows(
        self, fake_camera_menu
    ):
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        class _Anchor:
            screen_position_x = 0
            screen_position_y = 0
            computed_height = 0

        forbidden = {
            "Render Resolution",
            "Custom Resolution",
            "Render Scale",
            "Fill Viewport",
            "Viewport Resolution",
            "Resolution",
            "UHD",
            "HD1080P",
            "HD720P",
            "Custom",
        }
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
            assert isinstance(contribution, ViewportToolbarMenu)

            vp._pre_tools_toolbar_hooks._show_menu(contribution, _Anchor())

            settings_menu = fake_camera_menu.instances[0]
            top_level_labels = [
                *[item.label for item in settings_menu.items],
                *[submenu.title for submenu in settings_menu.submenus],
            ]
            assert top_level_labels == ["Viewport"]
            assert forbidden.isdisjoint(top_level_labels)
        finally:
            vp.destroy()

    def test_settings_toolbar_menu_destroys_on_dismiss_or_reopen(
        self, fake_camera_menu
    ):
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        class _Anchor:
            screen_position_x = 4
            screen_position_y = 8
            computed_height = 12

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
            assert isinstance(contribution, ViewportToolbarMenu)

            vp._pre_tools_toolbar_hooks._show_menu(contribution, _Anchor())
            first = fake_camera_menu.instances[0]
            vp._pre_tools_toolbar_hooks._show_menu(contribution, _Anchor())
            second = [
                menu
                for menu in fake_camera_menu.instances
                if menu.title == "Settings"
            ][-1]

            assert first.destroyed is True
            assert second.destroyed is False
            vp._pre_tools_toolbar_hooks._destroy_menu(contribution.id)
            assert second.destroyed is True
            assert vp._pre_tools_toolbar_hooks._menus == {}
        finally:
            vp.destroy()

    def test_settings_toolbar_menu_dismisses_and_consumes_viewport_pick(
        self, fake_camera_menu
    ):
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        class _Anchor:
            screen_position_x = 4
            screen_position_y = 8
            computed_height = 12

        pick_calls = []
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._renderer.pick = lambda *args, **kwargs: pick_calls.append((args, kwargs))
        try:
            contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
            assert isinstance(contribution, ViewportToolbarMenu)
            vp._pre_tools_toolbar_hooks._show_menu(contribution, _Anchor())
            menu = fake_camera_menu.instances[0]

            vp._on_pick(0.0, 0.0, "replace")

            assert menu.destroyed is True
            assert vp._pre_tools_toolbar_hooks._menus == {}
            assert pick_calls == []
        finally:
            vp.destroy()

    def test_viewport_settings_submenu_shell_has_srd_order_and_non_hiding_rows(
        self, fake_camera_menu
    ):
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        class _Anchor:
            screen_position_x = 31
            screen_position_y = 47
            computed_height = 20

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
            assert isinstance(contribution, ViewportToolbarMenu)

            vp._pre_tools_toolbar_hooks._show_menu(contribution, _Anchor())

            settings_menu = fake_camera_menu.instances[0]
            assert [submenu.title for submenu in settings_menu.submenus] == ["Viewport"]
            viewport_menu = settings_menu.submenus[0]
            assert [
                (kind, child.title if kind == "menu" else child.label)
                for kind, child in viewport_menu.children
            ] == [
                ("menu", "Render Resolution"),
                ("item", "Custom Resolution"),
                ("item", "Render Scale"),
                ("item", "Fill Viewport"),
            ]
            render_resolution_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            assert render_resolution_menu.kwargs.get("hotkey_text") == "Viewport"
            assert [
                item.label
                for item in render_resolution_menu.items
            ] == [
                "Viewport",
                "UHD",
                "1440P",
                "2K",
                "HD1080P",
                "HD720P",
                "Square",
                "Icon",
                "Custom",
            ]
            assert render_resolution_menu.submenus == []
            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            assert custom_editor.label == "Custom Resolution"
            assert custom_editor.kwargs.get("hide_on_click") is False
            assert custom_editor.kwargs.get("custom_resolution_editor") is True
            assert custom_editor.kwargs.get("custom_resolution_controls") == (
                "width_field",
                "height_field",
                "link_toggle",
                "ratio_combo",
                "save_icon",
                "width_label",
                "height_label",
            )
            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            assert render_scale.label == "Render Scale"
            assert render_scale.kwargs.get("hide_on_click") is False
            assert render_scale.kwargs.get("render_scale_combo") is True
            assert render_scale.kwargs.get("render_scale_options") == (
                "200%",
                "100%",
                "66.67%",
                "50%",
                "33.33%",
                "25%",
            )
            assert render_scale.kwargs.get("render_scale_current_label") == "100%"
            assert render_scale.kwargs.get("render_scale_current_index") == 1
            assert render_scale.kwargs.get("render_scale_applies_on_change") is True
            assert callable(render_scale.kwargs.get("render_scale_changed_fn"))
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")
            assert fill_viewport.label == "Fill Viewport"
            assert fill_viewport.kwargs.get("fill_viewport_checkbox") is True
            assert fill_viewport.kwargs.get("hide_on_click") is False
            assert fill_viewport.kwargs.get("enabled") is False
            assert fill_viewport.kwargs.get("fill_viewport_enabled") is False
            assert fill_viewport.kwargs.get("fill_viewport_checked") is False
            assert fill_viewport.kwargs.get("fill_viewport_applies_on_change") is False
            assert callable(fill_viewport.kwargs.get("fill_viewport_changed_fn"))
            assert fill_viewport.kwargs.get("triggered_fn") is None
        finally:
            vp.destroy()

    def test_no_renderer_keeps_settings_path_visible(self, fake_camera_menu):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=None,
        )
        try:
            availability = vp.get_resolution_availability()
            assert availability.renderer_available is False
            assert availability.settings_available is True
            assert vp._resolution_unavailable_reason() == (
                "Resolution unavailable: no renderer"
            )

            contributions = vp._pre_tools_toolbar_hooks.iter_contributions()
            assert [contribution.label for contribution in contributions] == [
                "Settings"
            ]
            assert isinstance(contributions[0], ViewportToolbarMenu)

            settings_menu = self._open_settings_menu(vp)
            assert settings_menu.title == "Settings"
            assert [submenu.title for submenu in settings_menu.submenus] == [
                "Viewport"
            ]
            viewport_menu = settings_menu.submenus[0]
            assert [submenu.title for submenu in viewport_menu.submenus] == [
                "Render Resolution"
            ]
        finally:
            vp.destroy()

    def test_no_renderer_disables_resolution_rows_and_inline_controls(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        reason = "Resolution unavailable: no renderer"
        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=None,
        )
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )

            assert render_menu.kwargs["hotkey_text"] == "Viewport"
            assert [
                item.label
                for item in render_menu.items
                if item.kwargs.get("checked")
            ] == ["Viewport"]
            assert {item.kwargs.get("enabled") for item in render_menu.items} == {
                False
            }
            assert all(
                item.kwargs.get("disabled_reason") == reason
                for item in render_menu.items
            )
            assert all(
                reason in str(item.kwargs.get("hotkey_text", ""))
                for item in render_menu.items
            )
            assert all(item.kwargs.get("triggered_fn") is None for item in render_menu.items)

            review = [item for item in render_menu.items if item.label == "Review"][0]
            assert review.kwargs.get("delete_affordance") is True
            assert review.kwargs.get("delete_tooltip") == reason
            assert review.kwargs.get("delete_handoff_fn") is None

            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            assert custom_editor.kwargs.get("enabled") is False
            assert custom_editor.kwargs.get("disabled_reason") == reason
            assert custom_editor.kwargs.get("custom_resolution_disabled_reason") == reason
            assert (
                custom_editor.kwargs["custom_resolution_save_enabled_fn"](
                    1501,
                    1000,
                )
                is False
            )
            assert custom_editor.kwargs["custom_resolution_apply_fn"](1501, 1000) is False
            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is False

            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            assert render_scale.kwargs.get("enabled") is False
            assert render_scale.kwargs.get("disabled_reason") == reason
            assert render_scale.kwargs.get("render_scale_applies_on_change") is False
            assert render_scale.kwargs["render_scale_changed_fn"](0) is False

            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")
            assert fill_viewport.kwargs.get("enabled") is False
            assert fill_viewport.kwargs.get("fill_viewport_enabled") is False
            assert fill_viewport.kwargs.get("fill_viewport_disabled_reason") == reason
            assert fill_viewport.kwargs.get("triggered_fn") is None
            assert fill_viewport.kwargs["fill_viewport_changed_fn"](True) is False
        finally:
            vp.destroy()

    def test_no_renderer_disabled_actions_do_not_write_render_or_update_hud(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.viewport.resolution_settings import (
            viewport_fill_viewport_key,
            viewport_resolution_key,
            viewport_resolution_scale_key,
            write_shared_custom_resolution_list,
        )

        settings = _A6CountingSettings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        settings.set_calls.clear()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=None,
            viewport_id="a7-t01-no-renderer",
        )
        vp._image = _VisibleViewportImage()
        vp._resolution_value_label = _FakeLabel()
        vp._resolution_value_label.text = "640×360"
        try:
            render_menu = self._open_render_resolution_menu(vp)
            hd1080p = [item for item in render_menu.items if item.label == "HD1080P"][0]
            review = [item for item in render_menu.items if item.label == "Review"][0]
            viewport_menu = self._latest_viewport_menu()
            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")

            assert hd1080p.trigger() is None
            hd1080p_row = next(
                row
                for row in viewport_mod.BUILTIN_RESOLUTION_PRESETS
                if row.label == "HD1080P"
            )
            assert vp._apply_render_resolution_row_selection(
                hd1080p_row
            ) is False
            assert render_scale.kwargs["render_scale_changed_fn"](3) is False
            assert fill_viewport.kwargs["fill_viewport_changed_fn"](True) is False
            assert custom_editor.kwargs["custom_resolution_apply_fn"](1501, 1000) is False
            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is False
            assert review.kwargs["delete_handoff_fn"] is None
            assert vp._handoff_saved_custom_delete(
                viewport_mod.iter_saved_custom_resolution_catalog_rows(
                    vp.get_resolution_settings().custom_list
                )[0]
            ) is False

            assert settings.set_calls == []
            assert settings.get(viewport_resolution_key(vp.viewport_id)) is None
            assert settings.get(viewport_resolution_scale_key(vp.viewport_id)) is None
            assert settings.get(viewport_fill_viewport_key(vp.viewport_id)) is None
            assert vp.get_resolution_state().selected_label == "Viewport"
            assert vp.get_resolution_state().requested_size == (0, 0)
            assert vp._last_resolution is None
            assert vp._resolution_value_label.text == "640×360"
            assert vp._custom_resolution_save_dialog_window is None
            assert [entry["name"] for entry in vp.get_resolution_settings().custom_list] == [
                "Review"
            ]
        finally:
            vp.destroy()

    def test_missing_settings_service_disables_resolution_changes_with_reason(
        self,
        fake_camera_menu,
        monkeypatch,
    ):
        from ovui_widgets.common.settings import Settings

        monkeypatch.setattr(Settings, "_instance", None)
        reason = "Resolution unavailable: settings service"
        vp = ViewportWidget(
            services=SimpleNamespace(settings=None, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a7-t02-missing-settings",
        )
        vp._image = _VisibleViewportImage()
        vp._resolution_value_label = _FakeLabel()
        vp._resolution_value_label.text = "640×360"
        try:
            availability = vp.get_resolution_availability()
            assert availability.renderer_available is True
            assert availability.settings_available is False
            assert vp._resolution_unavailable_reason() == reason

            settings_menu = self._open_settings_menu(vp)
            assert settings_menu.title == "Settings"
            assert [submenu.title for submenu in settings_menu.submenus] == [
                "Viewport"
            ]
            viewport_menu = settings_menu.submenus[0]
            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            assert render_menu.kwargs["hotkey_text"] == "Viewport"
            assert [
                item.label
                for item in render_menu.items
                if item.kwargs.get("checked")
            ] == ["Viewport"]
            assert {item.kwargs.get("enabled") for item in render_menu.items} == {
                False
            }
            assert all(
                item.kwargs.get("disabled_reason") == reason
                for item in render_menu.items
            )
            assert all(
                reason in str(item.kwargs.get("hotkey_text", ""))
                for item in render_menu.items
            )

            hd1080p = [item for item in render_menu.items if item.label == "HD1080P"][0]
            assert hd1080p.trigger() is None
            hd1080p_row = next(
                row
                for row in viewport_mod.BUILTIN_RESOLUTION_PRESETS
                if row.label == "HD1080P"
            )
            assert vp._apply_render_resolution_row_selection(hd1080p_row) is False

            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            assert custom_editor.kwargs.get("enabled") is False
            assert custom_editor.kwargs.get("custom_resolution_disabled_reason") == reason
            assert custom_editor.kwargs["custom_resolution_apply_fn"](1501, 1000) is False
            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is False

            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            assert render_scale.kwargs.get("enabled") is False
            assert render_scale.kwargs.get("disabled_reason") == reason
            assert render_scale.kwargs["render_scale_changed_fn"](3) is False

            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")
            assert fill_viewport.kwargs.get("enabled") is False
            assert fill_viewport.kwargs.get("fill_viewport_disabled_reason") == reason
            assert fill_viewport.kwargs.get("triggered_fn") is None
            assert fill_viewport.kwargs["fill_viewport_changed_fn"](True) is False

            assert vp.get_resolution_state().selected_label == "Viewport"
            assert vp.get_resolution_state().requested_size == (0, 0)
            assert vp._last_resolution is None
            assert vp._resolution_value_label.text == "640×360"
            assert vp._custom_resolution_save_dialog_window is None
            assert vp._resolve_settings() is None
        finally:
            vp.destroy()

    def test_no_stage_disables_resolution_changes_with_reason_and_noops(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.viewport.resolution_settings import (
            viewport_fill_viewport_key,
            viewport_resolution_key,
            viewport_resolution_scale_key,
            write_shared_custom_resolution_list,
        )

        reason = "Resolution unavailable: no stage loaded"
        settings = _A6CountingSettings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        settings.set_calls.clear()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a7-t02-no-stage",
            stage_adapter_provider=lambda: None,
        )
        vp._image = _VisibleViewportImage()
        vp._resolution_value_label = _FakeLabel()
        vp._resolution_value_label.text = "640×360"
        try:
            availability = vp.get_resolution_availability()
            assert availability.renderer_available is True
            assert availability.settings_available is True
            assert vp._resolution_stage_available_for_policy() is False
            assert vp._resolution_unavailable_reason() == reason

            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            assert [
                item.label
                for item in render_menu.items
                if item.kwargs.get("checked")
            ] == ["Viewport"]
            assert {item.kwargs.get("enabled") for item in render_menu.items} == {
                False
            }
            assert all(
                item.kwargs.get("disabled_reason") == reason
                for item in render_menu.items
            )
            assert all(
                reason in str(item.kwargs.get("hotkey_text", ""))
                for item in render_menu.items
            )

            hd1080p = [item for item in render_menu.items if item.label == "HD1080P"][0]
            review = [item for item in render_menu.items if item.label == "Review"][0]
            assert hd1080p.trigger() is None
            assert review.trigger() is None
            assert review.kwargs.get("delete_handoff_fn") is None
            assert review.kwargs.get("delete_tooltip") == reason
            hd1080p_row = next(
                row
                for row in viewport_mod.BUILTIN_RESOLUTION_PRESETS
                if row.label == "HD1080P"
            )
            assert vp._apply_render_resolution_row_selection(hd1080p_row) is False
            assert vp._handoff_saved_custom_delete(
                viewport_mod.iter_saved_custom_resolution_catalog_rows(
                    vp.get_resolution_settings().custom_list
                )[0]
            ) is False

            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            assert custom_editor.kwargs.get("enabled") is False
            assert custom_editor.kwargs.get("custom_resolution_disabled_reason") == reason
            assert custom_editor.kwargs["custom_resolution_apply_fn"](1501, 1000) is False
            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is False

            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            assert render_scale.kwargs.get("enabled") is False
            assert render_scale.kwargs.get("disabled_reason") == reason
            assert render_scale.kwargs["render_scale_changed_fn"](3) is False

            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")
            assert fill_viewport.kwargs.get("enabled") is False
            assert fill_viewport.kwargs.get("fill_viewport_disabled_reason") == reason
            assert fill_viewport.kwargs.get("triggered_fn") is None
            assert fill_viewport.kwargs["fill_viewport_changed_fn"](True) is False

            assert settings.set_calls == []
            assert settings.get(viewport_resolution_key(vp.viewport_id)) is None
            assert settings.get(viewport_resolution_scale_key(vp.viewport_id)) is None
            assert settings.get(viewport_fill_viewport_key(vp.viewport_id)) is None
            assert vp.get_resolution_state().selected_label == "Viewport"
            assert vp.get_resolution_state().requested_size == (0, 0)
            assert vp._last_resolution is None
            assert vp._resolution_value_label.text == "640×360"
            assert vp._custom_resolution_save_dialog_window is None
            assert [entry["name"] for entry in vp.get_resolution_settings().custom_list] == [
                "Review"
            ]
        finally:
            vp.destroy()

    def test_over_max_preset_row_is_visible_disabled_with_max_reason(
        self, fake_camera_menu
    ):
        from ovui_widgets.viewport.resolution_settings import (
            SETTING_RESOLUTION_PRESETS,
            viewport_resolution_key,
        )

        reason = "Resolution unavailable: max 3840x2160"
        full_setting = [
            value
            for row in viewport_mod.BUILTIN_RESOLUTION_PRESETS
            for value in row.dimensions
        ]
        settings = _A6CountingSettings()
        settings.set(SETTING_RESOLUTION_PRESETS, full_setting)
        settings.set_calls.clear()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a7-t04-over-max",
        )
        vp._image = _VisibleViewportImage()
        vp._resolution_value_label = _FakeLabel()
        vp._resolution_value_label.text = "640×360"
        try:
            render_menu = self._open_render_resolution_menu(vp)
            rows = {item.label: item for item in render_menu.items}

            assert "5K Wide" in rows
            assert rows["5K Wide"].kwargs.get("enabled") is False
            assert rows["5K Wide"].kwargs.get("disabled_reason") == reason
            assert rows["5K Wide"].kwargs.get("tooltip") == reason
            assert reason in rows["5K Wide"].kwargs.get("hotkey_text")
            assert rows["5K Wide"].trigger() is None
            five_k_row = next(
                row
                for row in viewport_mod.BUILTIN_RESOLUTION_PRESETS
                if row.label == "5K Wide"
            )
            assert vp._apply_render_resolution_row_selection(
                five_k_row
            ) is False

            assert rows["UHD"].kwargs.get("enabled") is True
            assert rows["Super Ultra Wide"].kwargs.get("enabled") is True
            assert rows["Custom"].kwargs.get("enabled") is True
            assert [
                item.label for item in render_menu.items if item.kwargs.get("checked")
            ] == ["Viewport"]
            assert settings.set_calls == []
            assert settings.get(viewport_resolution_key(vp.viewport_id)) is None
            assert vp.get_resolution_state().selected_label == "Viewport"
            assert vp.get_resolution_state().requested_size == (0, 0)
            assert vp._last_resolution is None
            assert vp._resolution_value_label.text == "640×360"

            reopened_menu = self._open_render_resolution_menu(vp)
            reopened_5k = [
                item for item in reopened_menu.items if item.label == "5K Wide"
            ][0]
            assert reopened_5k.kwargs.get("enabled") is False
            assert reopened_5k.kwargs.get("disabled_reason") == reason
            assert [
                item.label for item in reopened_menu.items if item.kwargs.get("checked")
            ] == ["Viewport"]
        finally:
            vp.destroy()

    def test_uhd_200_percent_clamps_and_exposes_max_bound_warning(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings

        warning = "Clamped to maximum 3840x2160."
        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
            viewport_id="a7-t04-uhd-200",
        )
        vp._image = _VisibleViewportImage()
        vp._resolution_value_label = _FakeLabel()
        try:
            render_menu = self._open_render_resolution_menu(vp)
            uhd = [item for item in render_menu.items if item.label == "UHD"][0]
            assert uhd.kwargs.get("enabled") is True
            assert uhd.trigger() is True

            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            scale_index = render_scale.kwargs["render_scale_options"].index("200%")
            assert render_scale.kwargs["render_scale_changed_fn"](scale_index) is True

            state = vp.get_resolution_state()
            assert state.selected_label == "UHD"
            assert state.requested_size == (3840, 2160)
            assert state.scale == 2.0
            assert state.effective_size == (3840, 2160)
            assert vp._resolution_value_label.text == "3840×2160"
            assert renderer.render_call_count == 2

            latest_render_menu = self._open_render_resolution_menu(vp)
            latest_scale = self._viewport_item(
                self._latest_viewport_menu(),
                "Render Scale",
            )
            assert latest_render_menu.kwargs["hotkey_text"] == "UHD"
            assert latest_render_menu.kwargs.get("tooltip") == warning
            assert latest_scale.kwargs.get("tooltip") == warning
            assert latest_scale.kwargs["render_scale_current_label"] == "200%"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["UHD"]
        finally:
            vp.destroy()

    def test_unsupported_fixed_adapter_disables_fixed_rows_and_controls(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        reason = "Resolution unavailable: fixed resolution unsupported"
        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=_UnsupportedFixedResolutionRenderer(),
            viewport_id="a7-t05-unsupported-fixed",
        )
        try:
            assert vp.get_resolution_availability().renderer_available is True
            assert vp._resolution_unavailable_reason() == ""
            assert vp._resolution_fixed_unsupported_reason() == reason

            settings_menu = self._open_settings_menu(vp)
            assert settings_menu.title == "Settings"
            viewport_menu = settings_menu.submenus[0]
            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            rows = {item.label: item for item in render_menu.items}

            assert rows["Viewport"].kwargs.get("enabled") is True
            assert rows["Viewport"].kwargs.get("disabled_reason") == ""
            assert rows["Viewport"].kwargs.get("checked") is True
            for label in ("HD1080P", "Square", "Icon", "Custom", "Review"):
                assert rows[label].kwargs.get("enabled") is False
                assert rows[label].kwargs.get("disabled_reason") == reason
                assert rows[label].kwargs.get("tooltip") == reason
                assert reason in str(rows[label].kwargs.get("hotkey_text", ""))
                assert rows[label].trigger() is None

            assert rows["Review"].kwargs.get("delete_affordance") is True
            assert rows["Review"].kwargs.get("delete_tooltip") == reason
            assert rows["Review"].kwargs.get("delete_handoff_fn") is None
            assert rows["Review"].label == "Review"
            review_visible_text = " ".join(
                str(part or "")
                for part in (
                    rows["Review"].label,
                    rows["Review"].kwargs.get("hotkey_text"),
                    rows["Review"].kwargs.get("tooltip"),
                    rows["Review"].kwargs.get("disabled_reason"),
                    rows["Review"].kwargs.get("delete_tooltip"),
                )
            )
            assert "__ovui_saved_custom_delete__" not in review_visible_text
            assert "||" not in review_visible_text
            assert "1500x1000" in str(rows["Review"].kwargs.get("hotkey_text"))
            assert "1.50:1" in str(rows["Review"].kwargs.get("hotkey_text"))

            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            assert custom_editor.kwargs.get("enabled") is False
            assert custom_editor.kwargs.get("disabled_reason") == reason
            assert custom_editor.kwargs.get("custom_resolution_disabled_reason") == reason
            assert (
                custom_editor.kwargs["custom_resolution_save_enabled_fn"](
                    1501,
                    1000,
                )
                is False
            )
            assert custom_editor.kwargs["custom_resolution_apply_fn"](1501, 1000) is False
            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is False

            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            assert render_scale.kwargs.get("enabled") is False
            assert render_scale.kwargs.get("disabled_reason") == reason
            assert render_scale.kwargs.get("tooltip") == reason
            assert render_scale.kwargs.get("render_scale_applies_on_change") is False
            assert render_scale.kwargs["render_scale_changed_fn"](3) is False

            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")
            assert fill_viewport.kwargs.get("enabled") is False
            assert fill_viewport.kwargs.get("fill_viewport_enabled") is False
            assert fill_viewport.kwargs.get("fill_viewport_disabled_reason") == reason
            assert fill_viewport.kwargs.get("tooltip") == reason
            assert fill_viewport.kwargs.get("triggered_fn") is None
            assert fill_viewport.kwargs["fill_viewport_changed_fn"](True) is False
        finally:
            vp.destroy()

    def test_unsupported_fixed_adapter_fixed_actions_noop_without_fake_state(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.viewport.resolution_settings import (
            viewport_fill_viewport_key,
            viewport_resolution_key,
            viewport_resolution_scale_key,
            write_shared_custom_resolution_list,
            write_viewport_instance_resolution,
        )

        settings = _A6CountingSettings()
        write_viewport_instance_resolution(
            settings,
            "a7-t05-unsupported-noop",
            [1920, 1080],
        )
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        settings.set_calls.clear()
        renderer = _UnsupportedFixedResolutionRenderer()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
            viewport_id="a7-t05-unsupported-noop",
        )
        vp._image = _VisibleViewportImage()
        vp._resolution_value_label = _FakeLabel()
        vp._resolution_value_label.text = "640×360"
        try:
            render_menu = self._open_render_resolution_menu(vp)
            rows = {item.label: item for item in render_menu.items}
            hd1080p = rows["HD1080P"]
            review = rows["Review"]
            viewport_menu = self._latest_viewport_menu()
            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")

            assert render_menu.kwargs["hotkey_text"] == "Viewport"
            assert [
                item.label for item in render_menu.items if item.kwargs.get("checked")
            ] == ["Viewport"]
            assert hd1080p.trigger() is None
            hd1080p_row = next(
                row
                for row in viewport_mod.BUILTIN_RESOLUTION_PRESETS
                if row.label == "HD1080P"
            )
            assert vp._apply_render_resolution_row_selection(hd1080p_row) is False
            assert custom_editor.kwargs["custom_resolution_apply_fn"](1501, 1000) is False
            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is False
            assert render_scale.kwargs["render_scale_changed_fn"](3) is False
            assert fill_viewport.kwargs["fill_viewport_changed_fn"](True) is False
            assert review.kwargs.get("delete_handoff_fn") is None
            assert vp._handoff_saved_custom_delete(
                viewport_mod.iter_saved_custom_resolution_catalog_rows(
                    vp.get_resolution_settings().custom_list
                )[0]
            ) is False

            assert settings.set_calls == []
            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [
                1920,
                1080,
            ]
            assert settings.get(viewport_resolution_scale_key(vp.viewport_id)) is None
            assert settings.get(viewport_fill_viewport_key(vp.viewport_id)) is None
            assert vp.get_resolution_state().selected_label == "Viewport"
            assert vp.get_resolution_state().requested_size == (0, 0)
            assert renderer.render_call_count == 0
            assert vp._last_resolution is None
            assert vp._resolution_value_label.text == "640×360"
            assert vp._custom_resolution_save_dialog_window is None
        finally:
            vp.destroy()

    def test_unsupported_fixed_adapter_viewport_fallback_remains_usable(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.viewport.resolution_settings import (
            viewport_resolution_key,
            write_viewport_instance_resolution,
        )

        settings = _A6CountingSettings()
        write_viewport_instance_resolution(
            settings,
            "a7-t05-unsupported-viewport",
            [1920, 1080],
        )
        settings.set_calls.clear()
        renderer = _UnsupportedFixedResolutionRenderer()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
            viewport_id="a7-t05-unsupported-viewport",
        )
        vp._image = _VisibleViewportImage()
        try:
            render_menu = self._open_render_resolution_menu(vp)
            viewport = [
                item for item in render_menu.items if item.label == "Viewport"
            ][0]

            assert viewport.kwargs.get("enabled") is True
            assert viewport.trigger() is True
            assert settings.set_calls == [
                (viewport_resolution_key(vp.viewport_id), [0, 0])
            ]
            assert vp.get_resolution_state().selected_label == "Viewport"
            assert vp.get_resolution_state().requested_size == (0, 0)
            assert renderer.render_call_count == 0
            latest_render_menu = self._latest_render_resolution_menu()
            assert latest_render_menu.kwargs["hotkey_text"] == "Viewport"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Viewport"]
        finally:
            vp.destroy()

    def test_menu_failure_launch_profile_preserves_settings_path(
        self,
        fake_camera_menu,
        monkeypatch,
    ):
        reason = "Resolution menu unavailable: data refresh failed"
        monkeypatch.setenv("OVUI_VIEWPORT_A7_MENU_FAILURE_QA", "1")
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            assert vp._resolution_menu_failure_qa_window is not None
            visible_profile_text = " ".join(
                str(getattr(label, "text", "") or "")
                for label in vp._resolution_menu_failure_qa_labels
            )
            assert "A7 menu-failure profile active" in visible_profile_text
            assert reason in visible_profile_text

            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            assert render_menu.kwargs.get("hotkey_text") == "Unavailable"
            assert render_menu.kwargs.get("tooltip") == reason
            assert [item.label for item in render_menu.items] == [
                "Resolution unavailable"
            ]
            assert render_menu.items[0].kwargs.get("enabled") is False
            assert render_menu.items[0].kwargs.get("disabled_reason") == reason
        finally:
            vp.destroy()

    def test_menu_data_failure_preserves_settings_path_with_disabled_fallback(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key

        reason = "Resolution menu unavailable: data refresh failed"
        settings = _A6CountingSettings()
        renderer = _MenuFailureRenderer()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
            viewport_id="a7-t07-menu-failure",
        )
        vp._image = _VisibleViewportImage()
        vp._resolution_value_label = _FakeLabel()
        vp._resolution_value_label.text = "640×360"
        try:
            settings_menu = self._open_settings_menu(vp)
            assert settings_menu.title == "Settings"
            viewport_menu = settings_menu.submenus[0]
            assert viewport_menu.title == "Viewport"
            assert [menu.title for menu in viewport_menu.submenus] == [
                "Render Resolution"
            ]

            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            assert render_menu.kwargs.get("hotkey_text") == "Unavailable"
            assert render_menu.kwargs.get("tooltip") == reason
            assert [item.label for item in render_menu.items] == [
                "Resolution unavailable"
            ]
            fallback_row = render_menu.items[0]
            assert fallback_row.kwargs.get("enabled") is False
            assert fallback_row.kwargs.get("disabled_reason") == reason
            assert fallback_row.kwargs.get("tooltip") == reason
            assert fallback_row.kwargs.get("hotkey_text") == reason
            assert fallback_row.trigger() is None

            for label in ("Custom Resolution", "Render Scale", "Fill Viewport"):
                item = self._viewport_item(viewport_menu, label)
                assert item.kwargs.get("enabled") is False
                assert item.kwargs.get("disabled_reason") == reason
                assert item.kwargs.get("tooltip") == reason
                assert item.kwargs.get("hotkey_text") == reason
                assert item.trigger() is None

            assert self._viewport_item(
                viewport_menu,
                "Custom Resolution",
            ).kwargs.get("custom_resolution_save_handoff") is False
            assert self._viewport_item(
                viewport_menu,
                "Render Scale",
            ).kwargs.get("render_scale_applies_on_change") is False
            assert self._viewport_item(
                viewport_menu,
                "Fill Viewport",
            ).kwargs.get("fill_viewport_applies_on_change") is False
            assert vp._settings_menu_control_callback_tokens == set()
            assert settings.set_calls == []
            assert settings.get(viewport_resolution_key(vp.viewport_id)) is None
            assert vp.get_resolution_state().selected_label == "Viewport"
            assert vp._last_resolution is None
            assert vp._resolution_value_label.text == "640×360"
            assert vp._custom_resolution_save_dialog_window is None
            assert renderer.render_call_count == 0
        finally:
            vp.destroy()

    def test_menu_data_failure_reopen_stable_and_no_fake_apply(
        self,
        fake_camera_menu,
    ):
        reason = "Resolution menu unavailable: data refresh failed"
        settings = _A6CountingSettings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=_MenuFailureRenderer(),
            viewport_id="a7-t07-menu-failure-reopen",
        )
        try:
            first_menu = self._open_settings_menu(vp)
            first_viewport_menu = first_menu.submenus[0]
            first_render_menu = self._viewport_submenu(
                first_viewport_menu,
                "Render Resolution",
            )
            first_fallback = first_render_menu.items[0]
            assert first_fallback.kwargs.get("disabled_reason") == reason
            assert first_fallback.trigger() is None

            reopened_menu = self._open_settings_menu(vp)
            reopened_viewport_menu = reopened_menu.submenus[0]
            reopened_render_menu = self._viewport_submenu(
                reopened_viewport_menu,
                "Render Resolution",
            )
            assert reopened_render_menu.kwargs.get("hotkey_text") == "Unavailable"
            assert reopened_render_menu.kwargs.get("tooltip") == reason
            assert [item.label for item in reopened_render_menu.items] == [
                "Resolution unavailable"
            ]
            assert reopened_render_menu.items[0].kwargs.get("enabled") is False
            assert reopened_render_menu.items[0].trigger() is None
            assert [
                item.label
                for item in reopened_render_menu.items
                if item.kwargs.get("checked")
            ] == []

            assert settings.set_calls == []
            assert vp.get_resolution_state().selected_label == "Viewport"
            assert vp._custom_resolution_save_dialog_window is None
        finally:
            vp.destroy()

    def test_menu_data_failure_catches_refresh_exception_and_isolates_toolbar(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.viewport.transform_manipulator import (
            TOOL_ROTATE,
            TOOL_SCALE,
            TOOL_TRANSLATE,
        )

        reason = "Resolution menu unavailable: data refresh failed"
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())

        def _raise_current_label():
            raise RuntimeError("catalog refresh exploded")

        vp._current_render_resolution_menu_label = _raise_current_label
        try:
            settings_menu = self._open_settings_menu(vp)
            viewport_menu = settings_menu.submenus[0]
            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            assert render_menu.kwargs.get("hotkey_text") == "Unavailable"
            assert render_menu.kwargs.get("tooltip") == reason
            assert [item.label for item in render_menu.items] == [
                "Resolution unavailable"
            ]
            assert render_menu.items[0].kwargs.get("disabled_reason") == reason
            assert render_menu.items[0].trigger() is None

            vp._build_ui()
            assert tuple(vp._toolbar_buttons) == (
                TOOL_TRANSLATE,
                TOOL_ROTATE,
                TOOL_SCALE,
                "camera",
            )
            vp._on_toolbar_tool_clicked(TOOL_ROTATE)
            assert vp._tool_registry.active_tool == TOOL_ROTATE
        finally:
            vp.destroy()

    def test_missing_icon_profile_uses_labeled_fallback_affordances(
        self,
        fake_camera_menu,
        monkeypatch,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        monkeypatch.setenv(viewport_mod.AREA7_MISSING_ICON_QA_ENV, "1")
        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a7-t08-missing-icons",
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._resolution_missing_icon_qa_window is not None
            visible_profile_text = " ".join(
                str(getattr(label, "text", "") or "")
                for label in vp._resolution_missing_icon_qa_labels
            )
            assert "A7 missing-icon profile active" in visible_profile_text
            assert "Settings filter icon/label" in visible_profile_text
            assert "save S" in visible_profile_text
            assert "delete x" in visible_profile_text

            contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
            assert isinstance(contribution, ViewportToolbarMenu)
            assert contribution.label == "Settings"
            assert contribution.tooltip == "Settings"
            assert contribution.icon_path.endswith("content_filter.png")

            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            rows = {item.label: item for item in render_menu.items}

            review = rows["Review"]
            assert review.kwargs.get("delete_affordance") is True
            assert review.kwargs.get("delete_fallback_label") == "x"
            assert review.kwargs.get("delete_fallback_tooltip") == "Delete Review"
            assert review.kwargs.get("badge_fallback_label") == "1500x1000  1.50:1"
            assert "delete label x" in review.kwargs.get(
                "icon_fallback_affordances",
            )
            assert "badge text" in review.kwargs.get("icon_fallback_affordances")
            assert review.kwargs.get("icon_fallback_profile") == (
                "A7 missing-icon profile active"
            )
            assert callable(review.kwargs.get("row_handoff_fn"))
            assert callable(review.kwargs.get("delete_handoff_fn"))

            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            assert custom_editor.kwargs.get("custom_resolution_icon_fallbacks") == (
                "link toggle label L",
                "ratio combo text labels",
                "save label S",
            )
            assert custom_editor.kwargs.get("link_toggle_fallback_label") == "L"
            assert custom_editor.kwargs.get("save_icon_fallback_label") == "S"
            assert (
                custom_editor.kwargs.get("link_toggle_fallback_tooltip")
                == "Link width and height"
            )
            assert (
                custom_editor.kwargs.get("save_icon_fallback_tooltip")
                == "Save custom resolution"
            )

            assert custom_editor.kwargs["custom_resolution_apply_fn"](1501, 1000) is True
            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is True
            assert vp._custom_resolution_save_dialog_window is not None
            assert vp._custom_resolution_save_dialog_window.visible is True
        finally:
            vp.destroy()

    def test_missing_icon_profile_falls_back_when_settings_asset_lookup_fails(
        self,
        fake_camera_menu,
        monkeypatch,
    ):
        import ovui_widgets.common.style.urls as style_urls

        def _raise_missing_icon(_name):
            raise KeyError("missing settings icon")

        monkeypatch.setattr(style_urls, "get_icon_path", _raise_missing_icon)
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
            assert contribution.label == "Settings"
            assert contribution.tooltip == "Settings"
            assert contribution.icon_path is None

            settings_menu = self._open_settings_menu(vp)
            assert settings_menu.title == "Settings"
            assert [submenu.title for submenu in settings_menu.submenus] == [
                "Viewport"
            ]
        finally:
            vp.destroy()

    def test_ovui_only_runtime_profile_keeps_basic_selection_operable(
        self,
        fake_camera_menu,
        monkeypatch,
    ):
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key

        monkeypatch.setenv(viewport_mod.AREA7_OVUI_ONLY_RUNTIME_QA_ENV, "1")
        settings = _A6CountingSettings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
            viewport_id="a7-t08-ovui-only",
        )
        vp._image = _VisibleViewportImage()
        vp._resolution_value_label = _FakeLabel()
        try:
            assert vp._resolution_ovui_only_qa_window is not None
            visible_profile_text = " ".join(
                str(getattr(label, "text", "") or "")
                for label in vp._resolution_ovui_only_qa_labels
            )
            assert "A7 ovui-only runtime profile active" in visible_profile_text
            assert "ovui widgets only" in visible_profile_text

            render_menu = self._open_render_resolution_menu(vp)
            hd720p = [item for item in render_menu.items if item.label == "HD720P"][0]
            assert hd720p.kwargs.get("enabled") is True
            assert hd720p.trigger() is True

            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [
                1280,
                720,
            ]
            assert vp.get_resolution_state().selected_label == "HD720P"
            assert vp.get_resolution_state().requested_size == (1280, 720)
            assert vp._resolution_value_label.text == "1280×720"
            assert renderer.render_call_count == 1
            latest_render_menu = self._open_render_resolution_menu(vp)
            assert latest_render_menu.kwargs["hotkey_text"] == "HD720P"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["HD720P"]

            source = viewport_mod.__loader__.get_source(viewport_mod.__name__)
            assert "import omni.kit" not in source
            assert "from omni.kit" not in source
        finally:
            vp.destroy()

    def test_resolution_menu_exposes_keyboard_targets_and_visible_labels(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a7-t09-keyboard-targets",
        )
        vp._image = _VisibleViewportImage()
        try:
            settings_menu = self._open_settings_menu(vp)
            viewport_menu = settings_menu.submenus[0]

            assert viewport_menu.kwargs.get("identifier") == (
                "viewport_settings_viewport_menu"
            )
            assert viewport_menu.kwargs.get("inspector_target") == (
                "viewport_settings_viewport_menu"
            )
            assert viewport_menu.kwargs.get("accessibility_label") == "Viewport"
            assert viewport_menu.kwargs.get("keyboard_focus_order") == 1
            assert viewport_menu.kwargs.get("keyboard_activation_keys") == (
                "Enter",
                "Space",
            )

            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            assert render_menu.kwargs.get("identifier") == (
                "viewport_render_resolution_menu"
            )
            assert render_menu.kwargs.get("inspector_target") == (
                "viewport_render_resolution_menu"
            )
            assert render_menu.kwargs.get("accessibility_label") == (
                "Render Resolution"
            )
            assert render_menu.kwargs.get("keyboard_focus_order") == 2
            assert render_menu.kwargs.get("stable_geometry") is True

            rows = {item.label: item for item in render_menu.items}
            hd1080p = rows["HD1080P"]
            assert hd1080p.kwargs.get("inspector_target") == (
                "viewport_render_resolution_row_hd1080p"
            )
            assert hd1080p.kwargs.get("accessibility_label") == "HD1080P"
            assert hd1080p.kwargs.get("visible_label") == "HD1080P"
            assert hd1080p.kwargs.get("keyboard_activation_keys") == (
                "Enter",
                "Space",
            )
            assert hd1080p.kwargs.get("focus_visible") is True
            assert hd1080p.kwargs.get("stable_geometry") is True
            assert "HD1080P" in hd1080p.kwargs.get("tooltip")
            assert "1920x1080" in hd1080p.kwargs.get("tooltip")

            review = rows["Review"]
            assert review.kwargs.get("inspector_target") == (
                "viewport_render_resolution_row_review"
            )
            assert review.kwargs.get("delete_inspector_target") == (
                "viewport_render_resolution_row_review_delete"
            )
            assert review.kwargs.get("keyboard_delete_activation_keys") == (
                "Tab",
                "Enter",
                "Space",
            )
            assert review.kwargs.get("delete_tooltip") == "Delete Review"
            assert callable(review.kwargs.get("row_handoff_fn"))
            assert callable(review.kwargs.get("delete_handoff_fn"))

            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            assert custom_editor.kwargs.get("inspector_target") == (
                "viewport_custom_resolution_editor"
            )
            assert custom_editor.kwargs.get("keyboard_focus_order") == 30
            assert custom_editor.kwargs.get("visible_label") == "Custom Resolution"
            assert custom_editor.kwargs.get("custom_resolution_width_identifier") == (
                "viewport_custom_resolution_width_field"
            )
            assert custom_editor.kwargs.get("custom_resolution_height_identifier") == (
                "viewport_custom_resolution_height_field"
            )
            assert custom_editor.kwargs.get("custom_resolution_ratio_identifier") == (
                "viewport_custom_resolution_ratio_combo"
            )
            assert custom_editor.kwargs.get("custom_resolution_save_identifier") == (
                "viewport_custom_resolution_save_button"
            )
            assert custom_editor.kwargs.get("keyboard_control_order") == (
                "viewport_custom_resolution_width_field",
                "viewport_custom_resolution_height_field",
                "viewport_custom_resolution_link_toggle",
                "viewport_custom_resolution_ratio_combo",
                "viewport_custom_resolution_save_button",
            )

            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            assert render_scale.kwargs.get("inspector_target") == (
                "viewport_render_scale_control"
            )
            assert render_scale.kwargs.get("render_scale_identifier") == (
                "viewport_render_scale_combo"
            )
            assert render_scale.kwargs.get("keyboard_focus_order") == 40
            assert render_scale.kwargs.get("tooltip") == "Render Scale"

            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")
            assert fill_viewport.kwargs.get("inspector_target") == (
                "viewport_fill_viewport_control"
            )
            assert fill_viewport.kwargs.get("fill_viewport_identifier") == (
                "viewport_fill_viewport_checkbox"
            )
            assert fill_viewport.kwargs.get("keyboard_focus_order") == 50
            assert fill_viewport.kwargs.get("disabled_focusable") is True
            assert fill_viewport.kwargs.get("disabled_reason_visible") == (
                "Disabled while Render Resolution is Viewport"
            )

            focus_order = [
                viewport_menu.kwargs["keyboard_focus_order"],
                render_menu.kwargs["keyboard_focus_order"],
                hd1080p.kwargs["keyboard_focus_order"],
                custom_editor.kwargs["keyboard_focus_order"],
                render_scale.kwargs["keyboard_focus_order"],
                fill_viewport.kwargs["keyboard_focus_order"],
            ]
            assert focus_order == sorted(focus_order)
        finally:
            vp.destroy()

    def test_disabled_resolution_controls_keep_focusable_reasons_without_fake_state(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_resolution_key,
            write_shared_custom_resolution_list,
        )

        reason = "Resolution unavailable: no renderer"
        settings = _A6CountingSettings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        settings.set_calls.clear()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=None,
            viewport_id="a7-t09-disabled-focus",
        )
        vp._image = _VisibleViewportImage()
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            hd1080p = [item for item in render_menu.items if item.label == "HD1080P"][0]
            review = [item for item in render_menu.items if item.label == "Review"][0]

            for item in (hd1080p, review):
                assert item.kwargs.get("enabled") is False
                assert item.kwargs.get("disabled_focusable") is True
                assert item.kwargs.get("disabled_reason_visible") == reason
                assert item.kwargs.get("disabled_reason_tooltip") == reason
                assert item.kwargs.get("focus_visible") is True
                assert item.trigger() is None

            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")
            for item in (custom_editor, render_scale, fill_viewport):
                assert item.kwargs.get("disabled_focusable") is True
                assert item.kwargs.get("disabled_reason_visible") == reason
                assert item.kwargs.get("disabled_reason_tooltip") == reason
                assert item.trigger() is None

            assert custom_editor.kwargs["custom_resolution_apply_fn"](1501, 1000) is False
            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is False
            assert render_scale.kwargs["render_scale_changed_fn"](3) is False
            assert fill_viewport.kwargs["fill_viewport_changed_fn"](True) is False
            assert review.kwargs.get("delete_handoff_fn") is None
            assert settings.set_calls == []
            assert settings.get(viewport_resolution_key(vp.viewport_id)) is None
        finally:
            vp.destroy()

    def test_save_dialog_keyboard_enter_and_escape_use_existing_actions(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._apply_custom_resolution_field_values(1501, 1000) is True
            assert vp._open_custom_resolution_save_dialog() is True
            vp._custom_resolution_save_dialog_key_pressed(
                viewport_mod._KEY_ESCAPE,
                0,
                True,
            )
            assert vp._custom_resolution_save_dialog_window.visible is False
            assert vp.get_resolution_settings().custom_list == []

            assert vp._open_custom_resolution_save_dialog() is True
            vp._custom_resolution_save_dialog_key_pressed(
                viewport_mod._IMGUI_KEY_ESCAPE,
                0,
                True,
            )
            assert vp._custom_resolution_save_dialog_window.visible is False
            assert vp.get_resolution_settings().custom_list == []

            assert vp._open_custom_resolution_save_dialog() is True
            vp._custom_resolution_save_dialog_name_field.model.set_value("Review")
            vp._custom_resolution_save_dialog_key_pressed(
                viewport_mod._IMGUI_KEY_ENTER,
                0,
                True,
            )
            assert vp._custom_resolution_save_dialog_window.visible is False
            assert vp.get_resolution_settings().custom_list == [
                {"name": "Review", "width": 1501, "height": 1000}
            ]

            assert vp._apply_custom_resolution_field_values(1502, 1000) is True
            assert vp._open_custom_resolution_save_dialog() is True
            vp._custom_resolution_save_dialog_name_field.model.set_value("Second")
            vp._custom_resolution_save_dialog_key_pressed(
                viewport_mod._KEY_KEYPAD_ENTER,
                0,
                False,
            )
            assert vp._custom_resolution_save_dialog_window.visible is True
            assert vp.get_resolution_settings().custom_list == [
                {"name": "Review", "width": 1501, "height": 1000}
            ]
            vp._custom_resolution_save_dialog_key_pressed(
                viewport_mod._IMGUI_KEY_KEYPAD_ENTER,
                0,
                True,
            )
            assert vp._custom_resolution_save_dialog_window.visible is False
            assert vp.get_resolution_settings().custom_list == [
                {"name": "Review", "width": 1501, "height": 1000},
                {"name": "Second", "width": 1502, "height": 1000},
            ]
        finally:
            vp.destroy()

    def test_scale_and_fill_menu_payloads_register_control_callbacks(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.menu import (
            _lookup_menu_control_callback,
            _parse_fill_viewport_payload,
            _parse_render_scale_payload,
        )

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            scale_index, scale_labels, scale_token = _parse_render_scale_payload(
                render_scale.kwargs["hotkey_text"]
            )
            assert scale_index == render_scale.kwargs["render_scale_current_index"]
            assert scale_labels == render_scale.kwargs["render_scale_options"]
            assert _lookup_menu_control_callback(scale_token) is (
                render_scale.kwargs["render_scale_changed_fn"]
            )

            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")
            fill_enabled, fill_checked, fill_token = _parse_fill_viewport_payload(
                fill_viewport.kwargs["hotkey_text"]
            )
            assert fill_enabled is fill_viewport.kwargs["fill_viewport_enabled"]
            assert fill_checked is fill_viewport.kwargs["fill_viewport_checked"]
            assert _lookup_menu_control_callback(fill_token) is (
                fill_viewport.kwargs["fill_viewport_changed_fn"]
            )
        finally:
            vp.destroy()

    def test_custom_resolution_inline_row_declares_required_controls(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.menu import (
            CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER,
            _lookup_menu_control_callback,
            _parse_custom_resolution_editor_apply_payload,
            _parse_custom_resolution_editor_bounds_payload,
            _parse_custom_resolution_editor_default_size_payload,
            _parse_custom_resolution_editor_payload,
            _parse_custom_resolution_editor_save_enabled_payload,
        )
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        class _Anchor:
            screen_position_x = 31
            screen_position_y = 47
            computed_height = 20

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
            assert isinstance(contribution, ViewportToolbarMenu)
            vp._pre_tools_toolbar_hooks._show_menu(contribution, _Anchor())
            viewport_menu = fake_camera_menu.instances[0].submenus[0]
            custom_editor = viewport_menu.items[0]

            assert custom_editor.label == "Custom Resolution"
            assert custom_editor.kwargs.get("hide_on_click") is False
            assert custom_editor.kwargs.get("hotkey_text", "").startswith(
                CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER
            )
            assert custom_editor.kwargs.get("custom_resolution_editor") is True
            assert custom_editor.kwargs.get("custom_resolution_default_width") == 1920
            assert custom_editor.kwargs.get("custom_resolution_default_height") == 1080
            assert custom_editor.kwargs.get("custom_resolution_ratio_options") == (
                "16:9",
                "4:3",
                "1:1",
                "21:9",
                "32:9",
            )
            assert custom_editor.kwargs.get("custom_resolution_controls") == (
                "width_field",
                "height_field",
                "link_toggle",
                "ratio_combo",
                "save_icon",
                "width_label",
                "height_label",
            )
            assert custom_editor.kwargs.get("custom_resolution_save_handoff") is True
            assert callable(
                custom_editor.kwargs.get("custom_resolution_save_handoff_fn")
            )
            assert custom_editor.kwargs.get(
                "custom_resolution_applies_on_end_edit"
            ) is True
            assert callable(custom_editor.kwargs.get("custom_resolution_apply_fn"))
            token = custom_editor.kwargs.get("custom_resolution_save_callback_token")
            assert _parse_custom_resolution_editor_payload(
                custom_editor.kwargs.get("hotkey_text")
            ) == token
            assert _lookup_menu_control_callback(token) is (
                custom_editor.kwargs.get("custom_resolution_save_handoff_fn")
            )
            save_enabled_token = custom_editor.kwargs.get(
                "custom_resolution_save_enabled_callback_token"
            )
            assert _parse_custom_resolution_editor_save_enabled_payload(
                custom_editor.kwargs.get("hotkey_text")
            ) == save_enabled_token
            assert _lookup_menu_control_callback(save_enabled_token) is (
                custom_editor.kwargs.get("custom_resolution_save_enabled_fn")
            )
            apply_token = custom_editor.kwargs.get(
                "custom_resolution_apply_callback_token"
            )
            assert _parse_custom_resolution_editor_apply_payload(
                custom_editor.kwargs.get("hotkey_text")
            ) == apply_token
            assert _lookup_menu_control_callback(apply_token) is (
                custom_editor.kwargs.get("custom_resolution_apply_fn")
            )
            assert _parse_custom_resolution_editor_default_size_payload(
                custom_editor.kwargs.get("hotkey_text")
            ) == (1920, 1080)
            assert _parse_custom_resolution_editor_bounds_payload(
                custom_editor.kwargs.get("hotkey_text")
            ) == (64, 64, 3840, 2160)
            assert custom_editor.kwargs.get("custom_resolution_min_width") == 64
            assert custom_editor.kwargs.get("custom_resolution_min_height") == 64
            assert custom_editor.kwargs.get("custom_resolution_max_width") == 3840
            assert custom_editor.kwargs.get("custom_resolution_max_height") == 2160
        finally:
            vp.destroy()

    def test_custom_resolution_inline_row_uses_a1_min_and_a3_max_bounds(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.menu import (
            _parse_custom_resolution_editor_bounds_payload,
        )
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import SETTING_MIN_RESOLUTION

        settings = Settings()
        settings.set(SETTING_MIN_RESOLUTION, [80, 90])
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        vp._image = _VisibleViewportImage()
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")

            assert custom_editor.kwargs.get("custom_resolution_min_width") == 80
            assert custom_editor.kwargs.get("custom_resolution_min_height") == 90
            assert custom_editor.kwargs.get("custom_resolution_max_width") == 3840
            assert custom_editor.kwargs.get("custom_resolution_max_height") == 2160
            assert _parse_custom_resolution_editor_bounds_payload(
                custom_editor.kwargs["hotkey_text"]
            ) == (80, 90, 3840, 2160)
        finally:
            vp.destroy()

    def test_custom_resolution_inline_row_is_distinct_from_custom_sentinel(
        self, fake_camera_menu
    ):
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            custom_editor = viewport_menu.items[0]
            render_resolution_menu = viewport_menu.submenus[0]
            custom_sentinel = [
                item for item in render_resolution_menu.items if item.label == "Custom"
            ][0]

            assert custom_editor.label == "Custom Resolution"
            assert custom_editor.kwargs.get("custom_resolution_editor") is True
            assert custom_sentinel.label == "Custom"
            assert custom_sentinel.kwargs.get("custom_resolution_editor") is not True
            assert custom_sentinel.kwargs.get("checkable") is True
            assert custom_sentinel.kwargs.get("hotkey_text") == "[-1,-1]"
        finally:
            vp.destroy()

    def test_custom_resolution_inline_row_is_non_hiding_and_noop(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            custom_editor = viewport_menu.items[0]

            assert custom_editor.kwargs.get("hide_on_click") is False
            assert custom_editor.kwargs.get("save_icon_opens_modal") is True
            assert "triggered_fn" not in custom_editor.kwargs
            assert custom_editor.trigger() is None
            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is False
            assert viewport_menu.destroyed is False
            assert vp.get_resolution_settings().custom_list == []
            assert vp._custom_resolution_save_dialog_window is None
        finally:
            vp.destroy()

    def test_custom_resolution_save_handoff_invokes_owner_without_fake_save(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings

        calls = []
        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        vp.set_custom_resolution_save_handoff(lambda: calls.append("save") or False)
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            custom_editor = viewport_menu.items[0]

            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is False

            assert calls == ["save"]
            assert viewport_menu.destroyed is False
            assert vp.get_resolution_settings().custom_list == []
            assert vp._resolution_settings_schema_qa_window is None
        finally:
            vp.destroy()

    def test_custom_resolution_enabled_save_opens_dialog_with_active_dimensions(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._apply_custom_resolution_field_values(1501, 1000) is True
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            custom_editor = viewport_menu.items[0]

            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is True

            window = vp._custom_resolution_save_dialog_window
            assert window is not None
            assert window.title == "Save Custom Viewport Resolution"
            assert vp._custom_resolution_save_dialog_size == (1501, 1000)
            assert (
                vp._custom_resolution_save_dialog_resolution_label.text
                == "1501 x 1000"
            )
            assert (
                vp._custom_resolution_save_dialog_name_field.model.get_value_as_string()
                == ""
            )
            assert vp._custom_resolution_save_dialog_save_button is not None
            assert vp._custom_resolution_save_dialog_save_button.enabled is True
            assert vp._custom_resolution_save_dialog_error_label.text == ""
            assert vp.get_resolution_settings().custom_list == []
            assert vp.get_resolution_state().selected_label == "Custom"
        finally:
            vp.destroy()

    def test_custom_resolution_save_dialog_rejects_empty_and_space_names(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._apply_custom_resolution_field_values(1501, 1000) is True
            assert vp._open_custom_resolution_save_dialog() is True

            assert vp._save_custom_resolution_from_dialog() is False
            assert vp._custom_resolution_save_dialog_window.visible is True
            assert (
                vp._custom_resolution_save_dialog_error_label.text
                == "Name is required."
            )
            assert vp.get_resolution_settings().custom_list == []

            vp._custom_resolution_save_dialog_name_field.model.set_value("   ")
            assert vp._save_custom_resolution_from_dialog() is False
            assert vp._custom_resolution_save_dialog_window.visible is True
            assert (
                vp._custom_resolution_save_dialog_error_label.text
                == "Name is required."
            )
            assert vp.get_resolution_settings().custom_list == []
            assert vp.get_resolution_state().selected_label == "Custom"
        finally:
            vp.destroy()

    def test_custom_resolution_save_dialog_valid_name_appends_and_selects_row(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._apply_custom_resolution_field_values(1501, 1000) is True
            assert vp._open_custom_resolution_save_dialog() is True
            vp._custom_resolution_save_dialog_name_field.model.set_value(" Review ")

            assert vp._save_custom_resolution_from_dialog() is True

            assert vp._custom_resolution_save_dialog_window.visible is False
            assert vp.get_resolution_settings().custom_list == [
                {"name": "Review", "width": 1501, "height": 1000}
            ]
            state = vp.get_resolution_state()
            assert state.requested_size == (1501, 1000)
            assert state.selected_label == "Review"

            render_resolution_menu = self._open_render_resolution_menu(vp)
            review_rows = [
                item for item in render_resolution_menu.items if item.label == "Review"
            ]
            assert len(review_rows) == 1
            assert review_rows[0].kwargs.get("checked") is True
            assert "1501" in str(review_rows[0].kwargs.get("hotkey_text", ""))
            assert "1000" in str(review_rows[0].kwargs.get("hotkey_text", ""))
        finally:
            vp.destroy()

    def test_custom_resolution_save_dialog_rejects_duplicate_name(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._apply_custom_resolution_field_values(1501, 1000) is True
            assert vp._open_custom_resolution_save_dialog() is True
            vp._custom_resolution_save_dialog_name_field.model.set_value("Review")

            assert vp._save_custom_resolution_from_dialog() is False

            assert vp._custom_resolution_save_dialog_window.visible is True
            assert (
                vp._custom_resolution_save_dialog_error_label.text
                == "Name already exists."
            )
            assert vp.get_resolution_settings().custom_list == [
                {"name": "Review", "width": 1500, "height": 1000}
            ]
            assert vp.get_resolution_state().selected_label == "Custom"
        finally:
            vp.destroy()

    def test_custom_resolution_save_dialog_rechecks_duplicate_dimensions(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._apply_custom_resolution_field_values(1501, 1000) is True
            assert vp._open_custom_resolution_save_dialog() is True
            write_shared_custom_resolution_list(
                settings,
                [{"name": "Existing", "width": 1501, "height": 1000}],
            )
            vp._custom_resolution_save_dialog_name_field.model.set_value("Review")

            assert vp._save_custom_resolution_from_dialog() is False

            assert vp._custom_resolution_save_dialog_window.visible is True
            assert (
                vp._custom_resolution_save_dialog_error_label.text
                == "Resolution already exists."
            )
            assert vp.get_resolution_settings().custom_list == [
                {"name": "Existing", "width": 1501, "height": 1000}
            ]
            assert vp.get_resolution_state().selected_label == "Existing"
        finally:
            vp.destroy()

    def test_custom_resolution_save_dialog_cancel_after_error_does_not_mutate(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._apply_custom_resolution_field_values(1501, 1000) is True
            state_before = vp.get_resolution_state()
            assert vp._open_custom_resolution_save_dialog() is True
            assert vp._save_custom_resolution_from_dialog() is False

            assert vp._close_custom_resolution_save_dialog() is False

            assert vp._custom_resolution_save_dialog_window.visible is False
            assert vp.get_resolution_settings().custom_list == []
            assert (
                vp.get_resolution_state().requested_size
                == state_before.requested_size
            )
            assert (
                vp.get_resolution_state().selected_label
                == state_before.selected_label
            )
        finally:
            vp.destroy()

    def test_custom_resolution_save_dialog_cancel_close_does_not_mutate_state(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._apply_custom_resolution_field_values(1501, 1000) is True
            state_before = vp.get_resolution_state()

            assert vp._open_custom_resolution_save_dialog() is True
            vp._custom_resolution_save_dialog_name_field.model.set_value("Review")
            assert vp._close_custom_resolution_save_dialog() is False

            assert vp._custom_resolution_save_dialog_window.visible is False
            assert vp.get_resolution_settings().custom_list == []
            assert (
                vp.get_resolution_state().requested_size
                == state_before.requested_size
            )
            assert (
                vp.get_resolution_state().selected_label
                == state_before.selected_label
            )

            assert vp._open_custom_resolution_save_dialog() is True
            assert vp._custom_resolution_save_dialog_window.visible is True
            assert vp._custom_resolution_save_dialog_size == (1501, 1000)
            assert (
                vp._custom_resolution_save_dialog_name_field.model.get_value_as_string()
                == ""
            )
        finally:
            vp.destroy()

    def test_custom_resolution_disabled_save_does_not_open_dialog(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            custom_editor = viewport_menu.items[0]

            assert custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is False
            assert vp._custom_resolution_save_dialog_window is None
            assert vp.get_resolution_settings().custom_list == []
            assert vp.get_resolution_state().selected_label == "Viewport"
        finally:
            vp.destroy()

    def test_custom_resolution_save_enabled_predicate_uses_area2_matching(self):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            assert (
                vp._custom_resolution_save_enabled_for_dimensions(1920, 1080)
                is False
            )
            assert (
                vp._custom_resolution_save_enabled_for_dimensions(1500, 1000)
                is False
            )
            assert (
                vp._custom_resolution_save_enabled_for_dimensions(0, 1000)
                is False
            )
            assert (
                vp._custom_resolution_save_enabled_for_dimensions(1501, 1000)
                is True
            )
        finally:
            vp.destroy()

    def test_custom_resolution_save_enabled_state_transitions_after_field_edits(
        self,
    ):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1920)
        height = _FakeNumericField(1080)
        save_button = _FakeButton(enabled=True)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1920,
            default_height=1080,
            save_enabled_callback=lambda w, h: (w, h) == (1501, 1000),
        )
        recovery.attach_feedback(save_button=save_button)

        assert recovery.save_enabled is False
        assert save_button.enabled is False

        recovery.begin_edit(active_field="width")
        width.model.set_value("1501")
        height.model.set_value("1000")
        assert recovery.update_linked_pair("width") == (1501, 1000)

        assert recovery.save_enabled is True
        assert save_button.enabled is True

        width.model.set_value("0")
        assert recovery.update_linked_pair("width") is None
        assert recovery.save_enabled is False
        assert save_button.enabled is False

    def test_custom_resolution_disabled_save_click_noops_without_fake_row(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1920)
        height = _FakeNumericField(1080)
        save_button = _FakeButton(enabled=True)
        calls = []
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1920,
            default_height=1080,
            save_enabled_callback=lambda _w, _h: False,
        )
        recovery.attach_feedback(save_button=save_button)

        assert recovery.save_enabled is False
        assert save_button.enabled is False
        assert (
            recovery.invoke_save_handoff(lambda: calls.append("save") or True)
            is False
        )
        assert calls == []

    def test_typed_custom_resolution_end_edit_defers_unsaved_apply(
        self, fake_camera_menu, monkeypatch
    ):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key

        frame_waits = []

        async def _fake_next_frame():
            frame_waits.append("frame")
            await asyncio.sleep(0)

        monkeypatch.setattr(viewport_mod.ui, "next_frame", _fake_next_frame)

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            apply_fn = custom_editor.kwargs["custom_resolution_apply_fn"]
            resolution_key = viewport_resolution_key(vp.viewport_id)

            async def _exercise():
                assert apply_fn(1500, 1000) is True
                assert settings.get(resolution_key) is None
                assert vp.get_resolution_state().selected_label == "Viewport"

                for _ in range(10):
                    await asyncio.sleep(0)

            asyncio.run(_exercise())

            assert frame_waits
            assert settings.get(resolution_key) == [1500, 1000]
            assert vp.get_resolution_settings().custom_list == []

            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1500, 1000)
            assert state.selected_label == "Custom"
            assert state.effective_size == (1500, 1000)
            assert vp._last_resolution == (1500, 1000)

            latest_menu = self._open_settings_menu(vp)
            latest_viewport_menu = latest_menu.submenus[0]
            latest_render_menu = self._viewport_submenu(
                latest_viewport_menu,
                "Render Resolution",
            )
            latest_custom_editor = self._viewport_item(
                latest_viewport_menu,
                "Custom Resolution",
            )
            assert latest_render_menu.kwargs["hotkey_text"] == "Custom"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Custom"]
            assert latest_custom_editor.kwargs["custom_resolution_default_width"] == 1500
            assert latest_custom_editor.kwargs["custom_resolution_default_height"] == 1000
            assert [
                item.label
                for item in latest_render_menu.items
                if "1500" in str(item.kwargs.get("hotkey_text", ""))
            ] == []
        finally:
            vp.destroy()

    def test_custom_resolution_begin_edit_snapshot_and_cancel_restore(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1500)
        height = _FakeNumericField(1000)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1920,
            default_height=1080,
        )

        recovery.begin_edit()
        assert recovery.snapshot == (1500, 1000)

        width.model.set_value(1600)
        recovery.cancel_edit()

        assert width.model.get_value_as_int() == 1500
        assert height.model.get_value_as_int() == 1000
        assert recovery.snapshot == (1500, 1000)

    def test_custom_resolution_rejected_commit_restores_snapshot(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1500)
        height = _FakeNumericField(1000)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1500,
            default_height=1000,
        )
        apply_calls = []

        recovery.begin_edit()
        width.model.set_value(1600)
        height.model.set_value(0)
        recovery.end_edit(lambda w, h: apply_calls.append((w, h)) or True)

        assert apply_calls == []
        assert width.model.get_value_as_int() == 1500
        assert height.model.get_value_as_int() == 1000
        assert recovery.snapshot == (1500, 1000)

        recovery.begin_edit()
        width.model.set_value(1600)
        height.model.set_value(1000)
        recovery.end_edit(lambda w, h: apply_calls.append((w, h)) or False)

        assert apply_calls == [(1600, 1000)]
        assert width.model.get_value_as_int() == 1500
        assert height.model.get_value_as_int() == 1000
        assert recovery.snapshot == (1500, 1000)

    def test_custom_resolution_invalid_half_edit_does_not_write_or_render(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._apply_custom_resolution_field_values(1500, 1000) is True
            resolution_key = viewport_resolution_key(vp.viewport_id)
            assert settings.get(resolution_key) == [1500, 1000]
            assert vp._last_resolution == (1500, 1000)
            state = vp.get_resolution_state()
            assert state.selected_label == "Custom"

            assert vp._apply_custom_resolution_field_values(1600, 0) is False
            assert settings.get(resolution_key) == [1500, 1000]
            assert vp.get_resolution_state().requested_size == (1500, 1000)
            assert vp.get_resolution_state().selected_label == "Custom"
            assert vp._last_resolution == (1500, 1000)
            assert vp.get_resolution_settings().custom_list == []
        finally:
            vp.destroy()

    def test_custom_resolution_zero_input_rejects_with_visible_error(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1500)
        height = _FakeNumericField(1000)
        error_label = _FakeLabel()
        save_button = _FakeButton(enabled=True)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1500,
            default_height=1000,
        )
        recovery.attach_feedback(
            error_label=error_label,
            save_button=save_button,
        )
        apply_calls = []

        recovery.begin_edit(active_field="width")
        width.model.set_value("0")
        assert recovery.update_linked_pair("width") is None
        assert error_label.text == "Width must be a positive integer."
        assert recovery.validation_error == error_label.text
        assert save_button.enabled is False

        recovery.end_edit(
            lambda w, h: apply_calls.append((w, h)) or True,
            active_field="width",
        )

        assert apply_calls == []
        assert width.model.get_value_as_int() == 1500
        assert height.model.get_value_as_int() == 1000
        assert error_label.text == "Width must be a positive integer."
        assert save_button.enabled is False

    def test_custom_resolution_negative_input_rejects_and_restores_height(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1500)
        height = _FakeNumericField(1000)
        error_label = _FakeLabel()
        save_button = _FakeButton(enabled=True)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1500,
            default_height=1000,
        )
        recovery.attach_feedback(
            error_label=error_label,
            save_button=save_button,
        )
        apply_calls = []

        recovery.begin_edit(active_field="height")
        height.model.set_value("-1")
        recovery.end_edit(
            lambda w, h: apply_calls.append((w, h)) or True,
            active_field="height",
        )

        assert apply_calls == []
        assert width.model.get_value_as_int() == 1500
        assert height.model.get_value_as_int() == 1000
        assert error_label.text == "Height must be a positive integer."
        assert save_button.enabled is False

    def test_custom_resolution_empty_input_rejects_and_recovers_previous_value(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1500)
        height = _FakeNumericField(1000)
        error_label = _FakeLabel()
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1500,
            default_height=1000,
        )
        recovery.attach_feedback(error_label=error_label)
        apply_calls = []

        recovery.begin_edit(active_field="width")
        width.model.set_value("")
        recovery.end_edit(
            lambda w, h: apply_calls.append((w, h)) or True,
            active_field="width",
        )

        assert apply_calls == []
        assert width.model.get_value_as_int() == 1500
        assert height.model.get_value_as_int() == 1000
        assert error_label.text == "Width must be a positive integer."

    def test_custom_resolution_non_integer_input_rejects_without_apply(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1500)
        height = _FakeNumericField(1000)
        error_label = _FakeLabel()
        save_button = _FakeButton(enabled=True)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1500,
            default_height=1000,
        )
        recovery.attach_feedback(
            error_label=error_label,
            save_button=save_button,
        )
        apply_calls = []

        recovery.begin_edit(active_field="width")
        width.model.set_value("abc")
        recovery.end_edit(
            lambda w, h: apply_calls.append((w, h)) or True,
            active_field="width",
        )

        assert apply_calls == []
        assert width.model.get_value_as_int() == 1500
        assert height.model.get_value_as_int() == 1000
        assert error_label.text == "Width must be a positive integer."
        assert save_button.enabled is False

    def test_custom_resolution_below_min_clamps_with_visible_feedback(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1500)
        height = _FakeNumericField(1000)
        error_label = _FakeLabel()
        save_button = _FakeButton(enabled=True)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1500,
            default_height=1000,
            bounds=(64, 64, 3840, 2160),
        )
        recovery.attach_feedback(
            error_label=error_label,
            save_button=save_button,
        )
        apply_calls = []

        recovery.begin_edit(active_field="width")
        width.model.set_value("12")
        height.model.set_value("20")
        recovery.end_edit(
            lambda w, h: apply_calls.append((w, h)) or True,
            active_field="width",
        )

        assert apply_calls == [(64, 64)]
        assert width.model.get_value_as_int() == 64
        assert height.model.get_value_as_int() == 64
        assert error_label.text == "Clamped to minimum 64x64."
        assert save_button.enabled is False

    def test_custom_resolution_above_max_clamps_with_visible_feedback(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1500)
        height = _FakeNumericField(1000)
        error_label = _FakeLabel()
        save_button = _FakeButton(enabled=True)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1500,
            default_height=1000,
            bounds=(64, 64, 3840, 2160),
        )
        recovery.attach_feedback(
            error_label=error_label,
            save_button=save_button,
        )
        apply_calls = []

        recovery.begin_edit(active_field="width")
        width.model.set_value("8000")
        height.model.set_value("5000")
        recovery.end_edit(
            lambda w, h: apply_calls.append((w, h)) or True,
            active_field="width",
        )

        assert apply_calls == [(3840, 2160)]
        assert width.model.get_value_as_int() == 3840
        assert height.model.get_value_as_int() == 2160
        assert error_label.text == "Clamped to maximum 3840x2160."
        assert save_button.enabled is False

    def test_custom_resolution_out_of_bounds_in_progress_disables_save_until_valid(
        self,
    ):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1500)
        height = _FakeNumericField(1000)
        error_label = _FakeLabel()
        save_button = _FakeButton(enabled=True)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1500,
            default_height=1000,
            bounds=(64, 64, 3840, 2160),
        )
        recovery.attach_feedback(
            error_label=error_label,
            save_button=save_button,
        )
        apply_calls = []

        recovery.begin_edit(active_field="width")
        width.model.set_value("12")
        assert recovery.update_linked_pair("width") == (12, 1000)
        assert error_label.text == "Clamped to minimum 64x64."
        assert save_button.enabled is False
        assert apply_calls == []

        width.model.set_value("1500")
        height.model.set_value("1000")
        assert recovery.update_linked_pair("width") == (1500, 1000)
        assert error_label.text == ""
        assert save_button.enabled is True

    def test_custom_resolution_linked_width_edit_updates_height(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1920)
        height = _FakeNumericField(1080)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1920,
            default_height=1080,
            ratio_options=("16:9", "4:3"),
            linked=True,
        )
        apply_calls = []

        recovery.begin_edit(active_field="width")
        width.model.set_value(1600)
        assert recovery.update_linked_pair("width") == (1600, 900)
        assert height.model.get_value_as_int() == 900
        assert apply_calls == []
        recovery.end_edit(
            lambda w, h: apply_calls.append((w, h)) or True,
            active_field="width",
        )

        assert height.model.get_value_as_int() == 900
        assert apply_calls == [(1600, 900)]
        assert recovery.snapshot == (1600, 900)

    def test_custom_resolution_linked_height_edit_updates_width(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1600)
        height = _FakeNumericField(900)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1600,
            default_height=900,
            ratio_options=("16:9", "4:3"),
            linked=True,
        )
        recovery.set_ratio_by_index(1)
        apply_calls = []

        recovery.begin_edit(active_field="height")
        height.model.set_value(900)
        recovery.end_edit(
            lambda w, h: apply_calls.append((w, h)) or True,
            active_field="height",
        )

        assert width.model.get_value_as_int() == 1200
        assert apply_calls == [(1200, 900)]
        assert recovery.snapshot == (1200, 900)

    def test_custom_resolution_linked_edit_truncates_non_integer_pair(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1365)
        height = _FakeNumericField(768)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1365,
            default_height=768,
            ratio_options=("16:9",),
            linked=True,
        )
        apply_calls = []

        recovery.begin_edit(active_field="width")
        width.model.set_value(1366)
        recovery.end_edit(
            lambda w, h: apply_calls.append((w, h)) or True,
            active_field="width",
        )

        assert height.model.get_value_as_int() == 768
        assert apply_calls == [(1366, 768)]

    def test_custom_resolution_link_off_keeps_fields_independent(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1600)
        height = _FakeNumericField(900)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1600,
            default_height=900,
            ratio_options=("16:9", "4:3"),
            linked=True,
        )
        recovery.set_linked(False)
        apply_calls = []

        recovery.begin_edit(active_field="width")
        width.model.set_value(1500)
        recovery.end_edit(
            lambda w, h: apply_calls.append((w, h)) or True,
            active_field="width",
        )

        assert width.model.get_value_as_int() == 1500
        assert height.model.get_value_as_int() == 900
        assert apply_calls == [(1500, 900)]
        assert recovery.snapshot == (1500, 900)

    def test_custom_resolution_linked_pair_hands_off_to_unsaved_apply(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        width = _FakeNumericField(1920)
        height = _FakeNumericField(1080)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1920,
            default_height=1080,
            ratio_options=("16:9",),
            linked=True,
        )
        try:
            recovery.begin_edit(active_field="width")
            width.model.set_value(1600)
            recovery.end_edit(
                vp._apply_custom_resolution_field_values,
                active_field="width",
            )

            resolution_key = viewport_resolution_key(vp.viewport_id)
            assert settings.get(resolution_key) == [1600, 900]
            assert vp.get_resolution_state().requested_size == (1600, 900)
            assert vp.get_resolution_state().selected_label == "Custom"
            assert vp._last_resolution == (1600, 900)
            assert vp.get_resolution_settings().custom_list == []
        finally:
            vp.destroy()

    def test_custom_resolution_ratio_choices_include_srd_options(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        recovery = _CustomResolutionEditRecovery(
            _FakeNumericField(1920),
            _FakeNumericField(1080),
            default_width=1920,
            default_height=1080,
            ratio_options=("16:9", "4:3", "1:1", "21:9", "32:9"),
        )

        assert recovery.ratio_choice_labels() == (
            "16:9",
            "4:3",
            "1:1",
            "21:9",
            "32:9",
        )

    def test_custom_resolution_ratio_selection_drives_1_to_1_linked_square(
        self,
    ):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1600)
        height = _FakeNumericField(900)
        combo = _FakeRatioComboModel(("16:9", "4:3", "1:1", "21:9", "32:9"))
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1600,
            default_height=900,
            ratio_options=combo.labels,
            linked=True,
        )
        recovery.attach_ratio_combo_model(combo)
        recovery.set_ratio_by_index(2)

        recovery.begin_edit(active_field="width")
        width.model.set_value(900)
        assert recovery.update_linked_pair("width") == (900, 900)

        assert height.model.get_value_as_int() == 900
        assert combo.labels == ("16:9", "4:3", "1:1", "21:9", "32:9")
        assert combo.selected_index == 2
        assert recovery.ratio == 1.0

    def test_custom_resolution_unlinked_custom_ratio_formats_decimal_label(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(900)
        height = _FakeNumericField(900)
        combo = _FakeRatioComboModel(("16:9", "4:3", "1:1", "21:9", "32:9"), 2)
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=900,
            default_height=900,
            ratio_options=combo.labels,
            linked=False,
        )
        recovery.attach_ratio_combo_model(combo)

        recovery.begin_edit(active_field="width")
        width.model.set_value(1500)
        recovery.update_linked_pair("width")
        recovery.begin_edit(active_field="height")
        height.model.set_value(1000)
        assert recovery.update_linked_pair("height") == (1500, 1000)

        assert combo.labels == (
            "16:9",
            "4:3",
            "1:1",
            "21:9",
            "32:9",
            "1.50:1",
        )
        assert combo.selected_index == 5
        assert width.model.get_value_as_int() == 1500
        assert height.model.get_value_as_int() == 1000

    def test_custom_resolution_matching_dimensions_restore_listed_ratio_display(self):
        from ovui_widgets.common.menu import _CustomResolutionEditRecovery

        width = _FakeNumericField(1500)
        height = _FakeNumericField(1000)
        combo = _FakeRatioComboModel(("16:9", "4:3", "1:1", "21:9", "32:9"))
        recovery = _CustomResolutionEditRecovery(
            width,
            height,
            default_width=1500,
            default_height=1000,
            ratio_options=combo.labels,
            linked=False,
        )
        recovery.attach_ratio_combo_model(combo)
        assert combo.labels[-1] == "1.50:1"
        assert combo.selected_index == 5

        width.model.set_value(900)
        height.model.set_value(900)
        assert recovery.update_linked_pair("height") == (900, 900)

        assert combo.labels == ("16:9", "4:3", "1:1", "21:9", "32:9")
        assert combo.selected_index == 2

    def test_render_scale_combo_renders_area1_options_and_current_value(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            SETTING_RENDER_SCALE_LIST,
            write_viewport_instance_resolution_scale,
        )

        settings = Settings()
        settings.set(SETTING_RENDER_SCALE_LIST, [1.0, 0.5, 0.25])
        write_viewport_instance_resolution_scale(settings, "a4-t07-scale", 0.5)
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a4-t07-scale",
        )
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_scale = self._viewport_item(viewport_menu, "Render Scale")

            assert render_scale.label == "Render Scale"
            assert render_scale.kwargs.get("render_scale_combo") is True
            assert render_scale.kwargs.get("render_scale_options") == (
                "100%",
                "50%",
                "25%",
            )
            assert render_scale.kwargs.get("render_scale_current_index") == 1
            assert render_scale.kwargs.get("render_scale_current_label") == "50%"
            assert render_scale.kwargs.get("hide_on_click") is False
            assert render_scale.kwargs.get("render_scale_applies_on_change") is True
            assert callable(render_scale.kwargs.get("render_scale_changed_fn"))
            assert "triggered_fn" not in render_scale.kwargs
        finally:
            vp.destroy()

    def test_fill_viewport_checkbox_renders_disabled_in_viewport_mode(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_viewport_instance_fill_viewport,
        )

        settings = Settings()
        write_viewport_instance_fill_viewport(settings, "a4-t07-fill-view", True)
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a4-t07-fill-view",
        )
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")

            assert fill_viewport.label == "Fill Viewport"
            assert fill_viewport.kwargs.get("fill_viewport_checkbox") is True
            assert fill_viewport.kwargs.get("enabled") is False
            assert fill_viewport.kwargs.get("fill_viewport_enabled") is False
            assert fill_viewport.kwargs.get("fill_viewport_checked") is False
            assert fill_viewport.kwargs.get("hide_on_click") is False
            assert fill_viewport.kwargs.get("triggered_fn") is None
        finally:
            vp.destroy()

    def test_fill_viewport_checkbox_renders_enabled_for_fixed_selection(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_viewport_instance_fill_viewport,
        )
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        settings = Settings()
        write_viewport_instance_fill_viewport(settings, "a4-t07-fill-fixed", True)
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a4-t07-fill-fixed",
        )
        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1920, 1080),
                selected_label="HD1080P",
            )
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")

            assert fill_viewport.label == "Fill Viewport"
            assert fill_viewport.kwargs.get("fill_viewport_checkbox") is True
            assert fill_viewport.kwargs.get("enabled") is True
            assert fill_viewport.kwargs.get("fill_viewport_enabled") is True
            assert fill_viewport.kwargs.get("fill_viewport_checked") is True
            assert fill_viewport.kwargs.get("hide_on_click") is False
            assert fill_viewport.kwargs.get("fill_viewport_applies_on_change") is True
            assert callable(fill_viewport.kwargs.get("fill_viewport_changed_fn"))
            assert callable(fill_viewport.kwargs.get("triggered_fn"))
        finally:
            vp.destroy()

    def test_render_scale_combo_action_updates_settings_state_and_render(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_resolution_scale_key,
            write_viewport_instance_resolution,
        )
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        try:
            write_viewport_instance_resolution(settings, vp.viewport_id, [1920, 1080])
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1920, 1080),
                selected_label="HD1080P",
            )
            settings_menu = self._open_settings_menu(vp)
            viewport_menu = settings_menu.submenus[0]
            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            selected_index = render_scale.kwargs["render_scale_options"].index("50%")

            assert render_scale.kwargs["render_scale_changed_fn"](selected_index) is True

            assert settings.get(viewport_resolution_scale_key(vp.viewport_id)) == 0.5
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1920, 1080)
            assert state.selected_label == "HD1080P"
            assert state.scale == 0.5
            assert state.effective_size == (960, 540)
            assert vp._last_resolution == (960, 540)
            self._assert_settings_menu_closed(vp, settings_menu)

            latest_menu = self._open_settings_menu(vp)
            latest_viewport_menu = latest_menu.submenus[0]
            latest_render_menu = self._viewport_submenu(
                latest_viewport_menu,
                "Render Resolution",
            )
            latest_scale = self._viewport_item(latest_viewport_menu, "Render Scale")
            assert latest_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["HD1080P"]
            assert latest_scale.kwargs["render_scale_current_label"] == "50%"
        finally:
            vp.destroy()

    def test_fill_viewport_checkbox_action_updates_settings_state_and_render(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_fill_viewport_key,
            write_viewport_instance_resolution,
        )
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1600,
            computed_height=900,
        )
        try:
            write_viewport_instance_resolution(settings, vp.viewport_id, [1024, 1024])
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1024, 1024),
                selected_label="Square",
            )
            settings_menu = self._open_settings_menu(vp)
            viewport_menu = settings_menu.submenus[0]
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")

            assert fill_viewport.trigger() is True

            assert settings.get(viewport_fill_viewport_key(vp.viewport_id)) is True
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1024, 1024)
            assert state.selected_label == "Square"
            assert state.fill_viewport is True
            assert state.effective_size == (1820, 1024)
            assert vp._last_resolution == (1820, 1024)
            self._assert_settings_menu_closed(vp, settings_menu)

            latest_menu = self._open_settings_menu(vp)
            latest_viewport_menu = latest_menu.submenus[0]
            latest_render_menu = self._viewport_submenu(
                latest_viewport_menu,
                "Render Resolution",
            )
            latest_fill = self._viewport_item(latest_viewport_menu, "Fill Viewport")
            assert latest_render_menu.kwargs["hotkey_text"] == "Square"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Square"]
            assert latest_fill.kwargs["fill_viewport_checked"] is True
            assert latest_fill.kwargs["fill_viewport_enabled"] is True
        finally:
            vp.destroy()

    def test_hd720p_fill_viewport_extends_from_requested_size_after_viewport_mode(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_fill_viewport_key,
            viewport_resolution_key,
        )

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=806,
            computed_height=659,
        )
        try:
            assert vp.render(1.0 / 60.0) is True
            assert vp.get_resolution_state().selected_label == "Viewport"
            assert vp.get_resolution_state().effective_size == (806, 659)

            settings_menu = self._open_settings_menu(vp)
            viewport_menu = settings_menu.submenus[0]
            render_menu = self._viewport_submenu(viewport_menu, "Render Resolution")
            hd720 = [item for item in render_menu.items if item.label == "HD720P"][0]
            assert hd720.trigger() is True

            state = vp.get_resolution_state()
            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [
                1280,
                720,
            ]
            assert state.selected_label == "HD720P"
            assert state.requested_size == (1280, 720)
            assert state.fill_viewport is False
            assert state.effective_size == (1280, 720)
            assert vp._last_resolution == (1280, 720)
            self._assert_settings_menu_closed(vp, settings_menu)

            fill_settings_menu = self._open_settings_menu(vp)
            latest_viewport_menu = fill_settings_menu.submenus[0]
            fill_viewport = self._viewport_item(latest_viewport_menu, "Fill Viewport")
            assert fill_viewport.trigger() is True

            state = vp.get_resolution_state()
            assert settings.get(viewport_fill_viewport_key(vp.viewport_id)) is True
            assert state.selected_label == "HD720P"
            assert state.requested_size == (1280, 720)
            assert state.fill_viewport is True
            assert state.effective_size == (1280, 1046)
            assert vp._last_resolution == (1280, 1046)
            assert getattr(vp._last_image_frame, "shape", None) == (1046, 1280, 4)
            self._assert_settings_menu_closed(vp, fill_settings_menu)
        finally:
            vp.destroy()

    def test_fill_viewport_checkbox_is_noop_in_viewport_mode(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_fill_viewport_key,
            write_viewport_instance_fill_viewport,
        )

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            write_viewport_instance_fill_viewport(settings, vp.viewport_id, True)
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")

            assert fill_viewport.kwargs["fill_viewport_enabled"] is False
            assert fill_viewport.trigger() is None
            assert fill_viewport.kwargs["fill_viewport_changed_fn"](True) is False

            assert settings.get(viewport_fill_viewport_key(vp.viewport_id)) is True
            state = vp.get_resolution_state()
            assert state.is_viewport_mode is True
            assert state.fill_viewport is False
            assert state.selected_label == "Viewport"
        finally:
            vp.destroy()

    def test_scale_and_fill_failed_writes_do_not_move_state_optimistically(
        self, fake_camera_menu
    ):
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        class _FailingSettings:
            def get(self, _key, default=None):
                return default

            def set(self, _key, _value):
                raise RuntimeError("write failed")

        vp = ViewportWidget(
            services=SimpleNamespace(settings=_FailingSettings(), selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1920, 1080),
                selected_label="HD1080P",
            )
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")
            selected_index = render_scale.kwargs["render_scale_options"].index("50%")

            assert render_scale.kwargs["render_scale_changed_fn"](selected_index) is False
            assert fill_viewport.trigger() is False

            assert isinstance(vp._last_render_resolution_apply_error, RuntimeError)
            state = vp.get_resolution_state()
            assert state.requested_size == (1920, 1080)
            assert state.selected_label == "HD1080P"
            assert state.scale == 1.0
            assert state.fill_viewport is False
            assert render_scale.kwargs["render_scale_current_label"] == "100%"
            assert fill_viewport.kwargs["fill_viewport_checked"] is False
        finally:
            vp.destroy()

    def test_per_viewport_resolution_notification_updates_state_menu_and_render(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_viewport_instance_resolution,
        )

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._resolution_settings_subscription is not None
            self._open_settings_menu(vp)

            write_viewport_instance_resolution(settings, vp.viewport_id, [1920, 1080])

            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1920, 1080)
            assert state.selected_label == "HD1080P"
            assert state.effective_size == (1920, 1080)
            assert vp._last_resolution == (1920, 1080)
            assert renderer.render_call_count == 1
            latest_render_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0].submenus[0]
            assert latest_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["HD1080P"]
        finally:
            vp.destroy()

    def test_per_viewport_scale_notification_updates_controls_and_effective_size(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_viewport_instance_resolution,
            write_viewport_instance_resolution_scale,
        )

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        try:
            self._open_settings_menu(vp)
            write_viewport_instance_resolution(settings, vp.viewport_id, [1920, 1080])
            write_viewport_instance_resolution_scale(settings, vp.viewport_id, 0.5)

            state = vp.get_resolution_state()
            assert state.selected_label == "HD1080P"
            assert state.scale == 0.5
            assert state.effective_size == (960, 540)
            assert vp._last_resolution == (960, 540)
            assert renderer.render_call_count == 2
            latest_viewport_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0]
            latest_render_menu = latest_viewport_menu.submenus[0]
            latest_scale = self._viewport_item(latest_viewport_menu, "Render Scale")
            assert latest_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert latest_scale.kwargs["render_scale_current_label"] == "50%"
        finally:
            vp.destroy()

    def test_per_viewport_fill_notification_updates_checkbox_and_fill_effective_size(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_viewport_instance_fill_viewport,
            write_viewport_instance_resolution,
        )

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1600,
            computed_height=900,
        )
        try:
            self._open_settings_menu(vp)
            write_viewport_instance_resolution(settings, vp.viewport_id, [1024, 1024])
            write_viewport_instance_fill_viewport(settings, vp.viewport_id, True)

            state = vp.get_resolution_state()
            assert state.selected_label == "Square"
            assert state.fill_viewport is True
            assert state.effective_size == (1820, 1024)
            assert vp._last_resolution == (1820, 1024)
            latest_viewport_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0]
            latest_fill = self._viewport_item(latest_viewport_menu, "Fill Viewport")
            assert latest_fill.kwargs["fill_viewport_enabled"] is True
            assert latest_fill.kwargs["fill_viewport_checked"] is True
        finally:
            vp.destroy()

    def test_menu_resolution_write_is_self_origin_guarded_and_renders_once(
        self, fake_camera_menu
    ):
        from ovui_widgets.viewport.resolution_settings import (
            ResolutionSettingsChange,
            viewport_resolution_key,
        )

        settings = _A6CountingSettings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            hd1080p = [
                item for item in render_resolution_menu.items if item.label == "HD1080P"
            ][0]

            assert hd1080p.trigger() is True

            assert settings.set_calls == [
                (viewport_resolution_key(vp.viewport_id), [1920, 1080])
            ]
            assert renderer.render_call_count == 1
            assert vp._last_resolution == (1920, 1080)
            assert vp._resolution_settings_self_origin_values == {}

            vp._on_resolution_settings_change(
                ResolutionSettingsChange(
                    viewport_resolution_key(vp.viewport_id),
                    [1920, 1080],
                    vp.viewport_id,
                )
            )

            assert renderer.render_call_count == 1
            assert vp._last_resolution == (1920, 1080)
        finally:
            vp.destroy()

    def test_same_value_resolution_notification_does_not_refresh_or_render(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            ResolutionSettingsChange,
            viewport_resolution_key,
            write_viewport_instance_resolution,
        )

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        try:
            self._open_settings_menu(vp)
            write_viewport_instance_resolution(settings, vp.viewport_id, [1920, 1080])
            menu_count = len(fake_camera_menu.instances)

            vp._on_resolution_settings_change(
                ResolutionSettingsChange(
                    viewport_resolution_key(vp.viewport_id),
                    [1920, 1080],
                    vp.viewport_id,
                )
            )

            assert renderer.render_call_count == 1
            assert len(fake_camera_menu.instances) == menu_count
            state = vp.get_resolution_state()
            assert state.requested_size == (1920, 1080)
            assert state.selected_label == "HD1080P"
        finally:
            vp.destroy()

    def test_viewport_mode_resize_requests_recompute_without_settings_write(
        self, fake_camera_menu
    ):
        settings = _A6CountingSettings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1280,
            computed_height=720,
        )
        vp._resolution_value_label = _FakeLabel()
        try:
            assert vp.render(1.0 / 60.0) is True
            assert renderer.render_call_count == 1
            assert vp.get_resolution_state().effective_size == (1280, 720)
            assert vp._last_resolution == (1280, 720)
            assert vp._resolution_value_label.text == "1280×720"
            assert settings.set_calls == []

            vp._image.computed_width = 800
            vp._image.computed_height = 450

            vp.update(1.0 / 60.0)

            assert vp._viewport_resize_render_refresh_pending is True
            assert renderer.render_call_count == 1
            assert settings.set_calls == []
            state_before_render = vp.get_resolution_state()
            assert state_before_render.selected_label == "Viewport"
            assert state_before_render.requested_size == (0, 0)

            assert vp.render(1.0 / 60.0) is True

            state = vp.get_resolution_state()
            assert state.is_viewport_mode is True
            assert state.requested_size == (0, 0)
            assert state.selected_label == "Viewport"
            assert state.effective_size == (800, 450)
            assert vp._last_resolution == (800, 450)
            assert vp._last_viewport_mode_effective_resolution is not None
            assert (
                vp._last_viewport_mode_effective_resolution.visible_frame_size
                == (800, 450)
            )
            assert vp._last_viewport_mode_visible_frame_size == (800, 450)
            assert vp._resolution_value_label.text == "800×450"
            assert vp._viewport_resize_render_refresh_pending is False
            assert renderer.render_call_count == 2
            assert settings.set_calls == []

            render_resolution_menu = self._open_render_resolution_menu(vp)
            assert render_resolution_menu.kwargs["hotkey_text"] == "Viewport"
            assert [
                item.label
                for item in render_resolution_menu.items
                if item.kwargs.get("checked")
            ] == ["Viewport"]
        finally:
            vp.destroy()

    def test_viewport_mode_resize_requests_are_coalesced(self):
        settings = _A6CountingSettings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1280,
            computed_height=720,
        )
        try:
            assert vp.render(1.0 / 60.0) is True
            assert renderer.render_call_count == 1

            for width, height in ((1200, 675), (1024, 576), (800, 450)):
                vp._image.computed_width = width
                vp._image.computed_height = height
                vp.update(1.0 / 60.0)

            assert vp._viewport_resize_render_refresh_pending is True
            assert renderer.render_call_count == 1
            assert settings.set_calls == []

            assert vp.render(1.0 / 60.0) is True

            assert renderer.render_call_count == 2
            assert vp.get_resolution_state().effective_size == (800, 450)
            assert vp._last_resolution == (800, 450)
            assert vp._viewport_resize_render_refresh_pending is False
            assert settings.set_calls == []

            vp.update(1.0 / 60.0)

            assert vp._viewport_resize_render_refresh_pending is False
            assert renderer.render_call_count == 2
            assert settings.set_calls == []
        finally:
            vp.destroy()

    def test_resize_storm_refreshes_open_menu_once_after_final_render(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.viewport.transform_manipulator import (
            TOOL_ROTATE,
            TOOL_SCALE,
            TOOL_TRANSLATE,
        )

        settings = _A6CountingSettings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1280,
            computed_height=720,
        )
        vp._resolution_value_label = _FakeLabel()
        try:
            assert vp.render(1.0 / 60.0) is True
            assert renderer.render_call_count == 1
            assert vp._resolution_value_label.text == "1280×720"

            self._open_render_resolution_menu(vp)
            settings_menu_count = len(
                [
                    menu
                    for menu in fake_camera_menu.instances
                    if menu.title == "Settings"
                ]
            )

            for width, height in (
                (1270, 714),
                (1180, 664),
                (1040, 585),
                (920, 518),
                (800, 450),
            ):
                vp._image.computed_width = width
                vp._image.computed_height = height
                vp.update(1.0 / 120.0)

            assert vp._viewport_resize_render_refresh_pending is True
            assert renderer.render_call_count == 1
            assert settings.set_calls == []
            assert len(
                [
                    menu
                    for menu in fake_camera_menu.instances
                    if menu.title == "Settings"
                ]
            ) == settings_menu_count
            assert [
                entry.label
                for entry in vp._pre_tools_toolbar_hooks.iter_contributions()
            ] == ["Settings"]
            assert tuple(spec[0] for spec in vp._iter_toolbar_tool_specs()) == (
                TOOL_TRANSLATE,
                TOOL_ROTATE,
                TOOL_SCALE,
            )

            assert vp.render(1.0 / 60.0) is True

            settings_menus = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ]
            assert len(settings_menus) == settings_menu_count + 1
            assert settings_menus[-2].destroyed is True
            latest_render_menu = self._latest_render_resolution_menu()
            assert latest_render_menu.kwargs["hotkey_text"] == "Viewport"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Viewport"]
            state = vp.get_resolution_state()
            assert state.selected_label == "Viewport"
            assert state.requested_size == (0, 0)
            assert state.effective_size == (800, 450)
            assert vp._last_resolution == (800, 450)
            assert vp._resolution_value_label.text == "800×450"
            assert vp._viewport_resize_render_refresh_pending is False
            assert renderer.render_call_count == 2
            assert settings.set_calls == []
        finally:
            vp.destroy()

    def test_resize_storm_safely_invalidates_open_menu_when_reshow_fails(
        self,
        fake_camera_menu,
    ):
        settings = _A6CountingSettings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1280,
            computed_height=720,
        )
        vp._resolution_value_label = _FakeLabel()
        try:
            assert vp.render(1.0 / 60.0) is True
            settings_menu = self._open_settings_menu(vp)
            vp._pre_tools_toolbar_hooks._menu_anchors.pop(
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID,
                None,
            )

            for width, height in ((1200, 675), (980, 552), (800, 450)):
                vp._image.computed_width = width
                vp._image.computed_height = height
                vp.update(1.0 / 120.0)

            assert vp._viewport_resize_render_refresh_pending is True
            assert vp.render(1.0 / 60.0) is True

            assert settings_menu.destroyed is True
            assert (
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
                not in vp._pre_tools_toolbar_hooks._menus
            )
            assert vp._resolution_value_label.text == "800×450"
            assert vp.get_resolution_state().selected_label == "Viewport"
            assert settings.set_calls == []

            reopened_render_menu = self._open_render_resolution_menu(vp)
            assert reopened_render_menu.kwargs["hotkey_text"] == "Viewport"
            assert [
                item.label
                for item in reopened_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Viewport"]
        finally:
            vp.destroy()

    def test_fill_viewport_resize_requests_recompute_without_settings_write(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        settings = _A6CountingSettings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1600,
            computed_height=900,
        )
        vp._resolution_value_label = _FakeLabel()
        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1024, 1024),
                scale=1.0,
                fill_viewport=True,
                selected_label="Square",
                effective_size=None,
            )

            assert vp.render(1.0 / 60.0) is True
            assert renderer.render_call_count == 1
            assert vp.get_resolution_state().effective_size == (1820, 1024)
            assert vp._last_resolution == (1820, 1024)
            assert vp._last_fill_viewport_visible_frame_size == (1600, 900)
            assert vp._resolution_value_label.text == "1820×1024"
            assert settings.set_calls == []

            vp._image.computed_width = 1200
            vp._image.computed_height = 800

            vp.update(1.0 / 60.0)

            assert vp._viewport_resize_render_refresh_pending is True
            assert renderer.render_call_count == 1
            assert settings.set_calls == []
            state_before_render = vp.get_resolution_state()
            assert state_before_render.requested_size == (1024, 1024)
            assert state_before_render.selected_label == "Square"
            assert state_before_render.fill_viewport is True

            assert vp.render(1.0 / 60.0) is True

            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1024, 1024)
            assert state.selected_label == "Square"
            assert state.fill_viewport is True
            assert state.effective_size == (1536, 1024)
            assert vp._last_resolution == (1536, 1024)
            assert vp._last_fixed_mode_effective_resolution is not None
            assert vp._last_fixed_mode_effective_resolution.fill_viewport is True
            assert (
                vp._last_fixed_mode_effective_resolution.visible_frame_size
                == (1200, 800)
            )
            assert vp._last_fill_viewport_visible_frame_size == (1200, 800)
            assert vp._resolution_value_label.text == "1536×1024"
            assert vp._viewport_resize_render_refresh_pending is False
            assert renderer.render_call_count == 2
            assert settings.set_calls == []

            render_resolution_menu = self._open_render_resolution_menu(vp)
            assert render_resolution_menu.kwargs["hotkey_text"] == "Square"
            assert [
                item.label
                for item in render_resolution_menu.items
                if item.kwargs.get("checked")
            ] == ["Square"]
        finally:
            vp.destroy()

    def test_fill_viewport_resize_off_on_transition_uses_correct_mode(self):
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        settings = _A6CountingSettings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1600,
            computed_height=900,
        )
        vp._resolution_value_label = _FakeLabel()
        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1024, 1024),
                scale=1.0,
                fill_viewport=False,
                selected_label="Square",
                effective_size=None,
            )

            assert vp.render(1.0 / 60.0) is True
            assert vp.get_resolution_state().effective_size == (1024, 1024)
            assert vp._last_fixed_mode_effective_resolution is not None
            assert vp._last_fixed_mode_effective_resolution.fill_viewport is False
            assert vp._last_fill_viewport_visible_frame_size is None
            assert vp._resolution_value_label.text == "1024×1024"

            vp._image.computed_width = 1200
            vp._image.computed_height = 800
            vp.update(1.0 / 60.0)

            assert vp._viewport_resize_render_refresh_pending is False
            assert renderer.render_call_count == 1
            assert settings.set_calls == []

            assert vp.render(1.0 / 60.0) is True
            assert vp.get_resolution_state().effective_size == (1024, 1024)
            assert vp._last_fixed_mode_effective_resolution is not None
            assert vp._last_fixed_mode_effective_resolution.fill_viewport is False
            assert vp._last_fixed_mode_effective_resolution.visible_frame_size is None
            assert vp._last_fill_viewport_visible_frame_size is None
            assert vp._resolution_value_label.text == "1024×1024"

            vp.set_resolution_state(fill_viewport=True, effective_size=None)

            assert vp.render(1.0 / 60.0) is True
            assert vp.get_resolution_state().effective_size == (1536, 1024)
            assert vp._last_fill_viewport_visible_frame_size == (1200, 800)
            assert vp._resolution_value_label.text == "1536×1024"

            vp._image.computed_width = 1600
            vp._image.computed_height = 900
            vp.update(1.0 / 60.0)

            assert vp._viewport_resize_render_refresh_pending is True
            assert settings.set_calls == []

            assert vp.render(1.0 / 60.0) is True
            state = vp.get_resolution_state()
            assert state.selected_label == "Square"
            assert state.fill_viewport is True
            assert state.effective_size == (1820, 1024)
            assert vp._last_resolution == (1820, 1024)
            assert vp._resolution_value_label.text == "1820×1024"
            assert vp._viewport_resize_render_refresh_pending is False
            assert settings.set_calls == []
        finally:
            vp.destroy()

    def test_shared_custom_list_notification_adds_and_removes_saved_rows(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            self._open_render_resolution_menu(vp)

            write_shared_custom_resolution_list(
                settings,
                [{"name": "Review", "width": 1500, "height": 1000}],
            )

            latest_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0].submenus[0]
            labels = [item.label for item in latest_menu.items]
            review = [item for item in latest_menu.items if item.label == "Review"][0]
            assert "Review" in labels
            assert "1500" in review.kwargs["hotkey_text"]
            assert "1.50:1" in review.kwargs["hotkey_text"]
            assert review.kwargs.get("delete_affordance") is True

            write_shared_custom_resolution_list(settings, [])

            latest_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0].submenus[0]
            labels = [item.label for item in latest_menu.items]
            assert "Review" not in labels
            assert "Viewport" in labels
            assert "HD1080P" in labels
            assert "Custom" in labels
        finally:
            vp.destroy()

    def test_shared_custom_list_notification_fans_out_to_viewport_menus(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        first = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a6-t02-first",
        )
        second = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a6-t02-second",
        )
        try:
            self._open_render_resolution_menu(first)
            self._open_render_resolution_menu(second)
            settings_menu_count = len(
                [menu for menu in fake_camera_menu.instances if menu.title == "Settings"]
            )

            write_shared_custom_resolution_list(
                settings,
                [{"name": "Review", "width": 1500, "height": 1000}],
            )

            settings_menus = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ]
            refreshed_menus = settings_menus[settings_menu_count:]
            assert len(refreshed_menus) == 2
            for menu in refreshed_menus:
                render_menu = menu.submenus[0].submenus[0]
                assert "Review" in [item.label for item in render_menu.items]
        finally:
            second.destroy()
            first.destroy()

    def test_per_viewport_resolution_notification_is_scoped_to_one_viewport(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_resolution_key,
            write_viewport_instance_resolution,
        )

        settings = Settings()
        first_renderer = MockRendererAdapter()
        second_renderer = MockRendererAdapter()
        first = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=first_renderer,
            viewport_id="a6-t08-notify-a",
        )
        second = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=second_renderer,
            viewport_id="a6-t08-notify-b",
        )
        first._image = SimpleNamespace(
            visible=True,
            computed_width=1280,
            computed_height=720,
        )
        second._image = SimpleNamespace(
            visible=True,
            computed_width=1024,
            computed_height=768,
        )
        first._resolution_value_label = _FakeLabel()
        second._resolution_value_label = _FakeLabel()
        try:
            assert first.render(1.0 / 60.0) is True
            assert second.render(1.0 / 60.0) is True
            assert first._resolution_value_label.text == "1280×720"
            assert second._resolution_value_label.text == "1024×768"

            write_viewport_instance_resolution(
                settings,
                first.viewport_id,
                [1280, 720],
            )

            first_state = first.get_resolution_state()
            second_state = second.get_resolution_state()
            assert first_state.selected_label == "HD720P"
            assert first_state.requested_size == (1280, 720)
            assert first._last_resolution == (1280, 720)
            assert first_renderer.render_call_count == 2
            assert first._resolution_value_label.text == "1280×720"

            assert second_state.selected_label == "Viewport"
            assert second_state.requested_size == (0, 0)
            assert second._last_resolution == (1024, 768)
            assert second_renderer.render_call_count == 1
            assert second._resolution_value_label.text == "1024×768"
            assert settings.get(viewport_resolution_key(second.viewport_id)) is None

            first_menu = self._open_render_resolution_menu(first)
            second_menu = self._open_render_resolution_menu(second)
            assert first_menu.kwargs["hotkey_text"] == "HD720P"
            assert [
                item.label for item in first_menu.items if item.kwargs.get("checked")
            ] == ["HD720P"]
            assert second_menu.kwargs["hotkey_text"] == "Viewport"
            assert [
                item.label for item in second_menu.items if item.kwargs.get("checked")
            ] == ["Viewport"]
        finally:
            second.destroy()
            first.destroy()

    def test_menu_resolution_write_does_not_touch_other_viewport(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key

        settings = Settings()
        first = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a6-t08-write-a",
        )
        second = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a6-t08-write-b",
        )
        first._image = _VisibleViewportImage()
        second._image = _VisibleViewportImage()
        try:
            render_menu = self._open_render_resolution_menu(first)
            hd720p = [item for item in render_menu.items if item.label == "HD720P"][0]

            assert hd720p.trigger() is True

            assert settings.get(viewport_resolution_key(first.viewport_id)) == [
                1280,
                720,
            ]
            assert settings.get(viewport_resolution_key(second.viewport_id)) is None
            assert first.get_resolution_state().selected_label == "HD720P"
            assert second.get_resolution_state().selected_label == "Viewport"

            second_menu = self._open_render_resolution_menu(second)
            assert second_menu.kwargs["hotkey_text"] == "Viewport"
            assert [
                item.label for item in second_menu.items if item.kwargs.get("checked")
            ] == ["Viewport"]
        finally:
            second.destroy()
            first.destroy()

    def test_shared_custom_list_fans_out_without_foreign_selection_change(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
            write_viewport_instance_resolution,
        )

        settings = Settings()
        first_renderer = MockRendererAdapter()
        second_renderer = MockRendererAdapter()
        first = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=first_renderer,
            viewport_id="a6-t08-shared-a",
        )
        second = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=second_renderer,
            viewport_id="a6-t08-shared-b",
        )
        first._image = _VisibleViewportImage()
        second._image = _VisibleViewportImage()
        try:
            write_viewport_instance_resolution(
                settings, first.viewport_id, [1280, 720]
            )
            write_viewport_instance_resolution(
                settings, second.viewport_id, [1024, 1024]
            )
            first_render_count = first_renderer.render_call_count
            second_render_count = second_renderer.render_call_count

            self._open_render_resolution_menu(first)
            self._open_render_resolution_menu(second)
            settings_menu_count = len(
                [menu for menu in fake_camera_menu.instances if menu.title == "Settings"]
            )

            write_shared_custom_resolution_list(
                settings,
                [{"name": "Review", "width": 1500, "height": 1000}],
            )

            settings_menus = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ]
            refreshed_menus = settings_menus[settings_menu_count:]
            assert len(refreshed_menus) == 2
            hotkey_texts = sorted(
                menu.submenus[0].submenus[0].kwargs["hotkey_text"]
                for menu in refreshed_menus
            )
            assert hotkey_texts == ["HD720P", "Square"]
            for menu in refreshed_menus:
                render_menu = menu.submenus[0].submenus[0]
                assert "Review" in [item.label for item in render_menu.items]

            assert first.get_resolution_state().selected_label == "HD720P"
            assert second.get_resolution_state().selected_label == "Square"
            assert first_renderer.render_call_count == first_render_count
            assert second_renderer.render_call_count == second_render_count

            write_shared_custom_resolution_list(settings, [])

            settings_menus = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ]
            refreshed_menus = settings_menus[settings_menu_count + 2 :]
            assert len(refreshed_menus) == 2
            for menu in refreshed_menus:
                render_menu = menu.submenus[0].submenus[0]
                assert "Review" not in [item.label for item in render_menu.items]
            assert first.get_resolution_state().selected_label == "HD720P"
            assert second.get_resolution_state().selected_label == "Square"
            assert first_renderer.render_call_count == first_render_count
            assert second_renderer.render_call_count == second_render_count
        finally:
            second.destroy()
            first.destroy()

    def test_shared_custom_removal_recovers_each_viewport_independently(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
            write_viewport_instance_resolution,
        )

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        first = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a6-t08-recover-a",
        )
        second = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a6-t08-recover-b",
        )
        first._image = _VisibleViewportImage()
        second._image = _VisibleViewportImage()
        try:
            write_viewport_instance_resolution(
                settings, first.viewport_id, [1500, 1000]
            )
            write_viewport_instance_resolution(
                settings, second.viewport_id, [1280, 720]
            )
            self._open_render_resolution_menu(first)
            self._open_render_resolution_menu(second)
            settings_menu_count = len(
                [menu for menu in fake_camera_menu.instances if menu.title == "Settings"]
            )

            write_shared_custom_resolution_list(settings, [])

            settings_menus = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ]
            refreshed_menus = settings_menus[settings_menu_count:]
            assert len(refreshed_menus) == 2
            by_hotkey = {
                menu.submenus[0].submenus[0].kwargs["hotkey_text"]: (
                    menu.submenus[0].submenus[0]
                )
                for menu in refreshed_menus
            }
            assert set(by_hotkey) == {"Custom", "HD720P"}
            assert [
                item.label
                for item in by_hotkey["Custom"].items
                if item.kwargs.get("checked")
            ] == ["Custom"]
            assert "Review" not in [item.label for item in by_hotkey["Custom"].items]
            assert [
                item.label
                for item in by_hotkey["HD720P"].items
                if item.kwargs.get("checked")
            ] == ["HD720P"]
            assert "Review" not in [item.label for item in by_hotkey["HD720P"].items]
            assert first.get_resolution_state().selected_label == "Custom"
            assert second.get_resolution_state().selected_label == "HD720P"
        finally:
            second.destroy()
            first.destroy()

    def test_stale_viewport_settings_callback_after_destroy_is_noop(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            ResolutionSettingsChange,
            viewport_resolution_key,
            write_viewport_instance_resolution,
        )

        settings = Settings()
        stale_renderer = MockRendererAdapter()
        live_renderer = MockRendererAdapter()
        stale = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=stale_renderer,
            viewport_id="a6-t08-stale",
        )
        live = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=live_renderer,
            viewport_id="a6-t08-live",
        )
        stale._image = _VisibleViewportImage()
        live._image = _VisibleViewportImage()
        try:
            self._open_render_resolution_menu(stale)
            self._open_render_resolution_menu(live)
            stale.destroy()

            stale._on_resolution_settings_change(
                ResolutionSettingsChange(
                    viewport_resolution_key(stale.viewport_id),
                    [1280, 720],
                    stale.viewport_id,
                )
            )

            assert stale.get_resolution_state().selected_label == "Viewport"
            assert stale_renderer.render_call_count == 0
            assert live.get_resolution_state().selected_label == "Viewport"
            assert live_renderer.render_call_count == 0

            write_viewport_instance_resolution(
                settings, live.viewport_id, [1280, 720]
            )

            assert live.get_resolution_state().selected_label == "HD720P"
            assert live_renderer.render_call_count == 1
            assert stale.get_resolution_state().selected_label == "Viewport"
            assert stale_renderer.render_call_count == 0
        finally:
            live.destroy()
            if not getattr(stale, "_viewport_id_released", True):
                stale.destroy()

    def test_destroy_cancels_settings_subscription_and_shared_writes_skip_dead_viewport(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
            write_viewport_instance_resolution,
        )

        settings = Settings()
        stale_renderer = MockRendererAdapter()
        live_renderer = MockRendererAdapter()
        stale = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=stale_renderer,
            viewport_id="a6-t09-stale-sub",
        )
        live = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=live_renderer,
            viewport_id="a6-t09-live-sub",
        )
        stale._image = _VisibleViewportImage()
        live._image = _VisibleViewportImage()
        stale_id = stale.viewport_id
        try:
            self._open_render_resolution_menu(stale)
            self._open_render_resolution_menu(live)
            settings_menu_count = len(
                [menu for menu in fake_camera_menu.instances if menu.title == "Settings"]
            )

            stale.destroy()
            write_viewport_instance_resolution(settings, stale_id, [1920, 1080])
            write_shared_custom_resolution_list(
                settings,
                [{"name": "Review", "width": 1500, "height": 1000}],
            )

            settings_menus = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ]
            assert len(settings_menus) == settings_menu_count + 1
            live_render_menu = settings_menus[-1].submenus[0].submenus[0]
            assert "Review" in [item.label for item in live_render_menu.items]
            assert stale.get_resolution_state().selected_label == "Viewport"
            assert stale_renderer.render_call_count == 0

            write_viewport_instance_resolution(settings, live.viewport_id, [1280, 720])

            assert live.get_resolution_state().selected_label == "HD720P"
            assert live_renderer.render_call_count == 1
            assert stale.get_resolution_state().selected_label == "Viewport"
            assert stale_renderer.render_call_count == 0
        finally:
            live.destroy()
            if not getattr(stale, "_viewport_id_released", True):
                stale.destroy()

    def test_late_lifecycle_callbacks_after_destroy_are_noops(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            ResolutionSettingsChange,
            SETTING_CUSTOM_RESOLUTION_LIST,
            viewport_resolution_key,
        )

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
            viewport_id="a6-t09-late",
        )
        vp._image = _VisibleViewportImage()
        vp._resolution_value_label = _FakeLabel()
        viewport_id = vp.viewport_id
        try:
            self._open_render_resolution_menu(vp)
            vp._resolution_value_label.text = "640×360"

            vp.destroy()
            vp._last_resolution = (1920, 1080)

            vp._on_resolution_settings_change(
                ResolutionSettingsChange(
                    viewport_resolution_key(viewport_id),
                    [1280, 720],
                    viewport_id,
                )
            )
            vp._on_resolution_settings_change(
                ResolutionSettingsChange(
                    SETTING_CUSTOM_RESOLUTION_LIST,
                    [{"name": "Review", "width": 1500, "height": 1000}],
                    viewport_id,
                )
            )
            vp._request_settings_menu_reshow()
            vp._request_render_resolution_apply_refresh()
            vp._request_viewport_resize_render_refresh()
            vp.update(1.0 / 60.0)
            assert vp.render(1.0 / 60.0) is False
            vp._refresh_hud()

            assert vp.get_resolution_state().selected_label == "Viewport"
            assert renderer.render_call_count == 0
            assert vp._resolution_render_refresh_pending is False
            assert vp._viewport_resize_render_refresh_pending is False
            assert vp._settings_menu_reshow_pending is False
            assert vp._resolution_value_label.text == "640×360"
            assert (
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
                not in vp._pre_tools_toolbar_hooks._menus
            )
        finally:
            if not getattr(vp, "_viewport_id_released", True):
                vp.destroy()

    def test_destroy_cleans_open_settings_menu_and_save_dialog_owner_surfaces(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a6-t09-surfaces",
        )
        vp._image = _VisibleViewportImage()
        try:
            assert vp._apply_custom_resolution_field_values(1501, 1000) is True
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            settings_menu = self._latest_settings_menu()
            custom_editor = viewport_menu.items[0]
            save_handoff = custom_editor.kwargs["custom_resolution_save_handoff_fn"]

            assert save_handoff() is True
            window = vp._custom_resolution_save_dialog_window
            assert window is not None

            vp.destroy()

            assert settings_menu.destroyed is True
            assert vp._pre_tools_toolbar_hooks._menus == {}
            assert vp._custom_resolution_save_dialog_window is None
            assert vp._custom_resolution_save_dialog_name_field is None
            assert vp._settings_menu_control_callback_tokens == set()
            assert save_handoff() is False
            assert vp._save_custom_resolution_from_dialog() is False
            assert vp.get_resolution_settings().custom_list == []
        finally:
            if not getattr(vp, "_viewport_id_released", True):
                vp.destroy()

    def test_destroy_clears_resize_render_and_hud_pending_work(self):
        settings = _A6CountingSettings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
            viewport_id="a6-t09-resize",
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1280,
            computed_height=720,
        )
        vp._resolution_value_label = _FakeLabel()
        try:
            assert vp.render(1.0 / 60.0) is True
            assert vp._resolution_value_label.text == "1280×720"
            vp._image.computed_width = 800
            vp._image.computed_height = 450
            vp.update(1.0 / 60.0)
            assert vp._viewport_resize_render_refresh_pending is True

            vp.destroy()
            vp._image.computed_width = 640
            vp._image.computed_height = 360

            assert vp._viewport_resize_render_refresh_pending is False
            assert vp._resolution_render_refresh_pending is False
            assert vp._custom_resolution_field_apply_pending is False
            assert vp._custom_resolution_field_pending_size is None
            assert vp.render(1.0 / 60.0) is False
            assert renderer.render_call_count == 1
            assert vp._resolution_value_label.text == "1280×720"
            assert settings.set_calls == []
        finally:
            if not getattr(vp, "_viewport_id_released", True):
                vp.destroy()

    def test_destroyed_menu_callbacks_do_not_write_settings_or_delete_rows(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_resolution_key,
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
            viewport_id="a6-t09-menu-callbacks",
        )
        vp._image = _VisibleViewportImage()
        try:
            render_menu = self._open_render_resolution_menu(vp)
            hd720p = [item for item in render_menu.items if item.label == "HD720P"][0]
            review = [item for item in render_menu.items if item.label == "Review"][0]

            vp.destroy()

            assert hd720p.trigger() is False
            assert review.kwargs["delete_handoff_fn"]() is False
            assert settings.get(viewport_resolution_key(vp.viewport_id)) is None
            assert [entry["name"] for entry in vp.get_resolution_settings().custom_list] == [
                "Review"
            ]
        finally:
            if not getattr(vp, "_viewport_id_released", True):
                vp.destroy()

    def test_destroy_and_recreate_registers_one_fresh_update_path(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_viewport_instance_resolution,
            write_viewport_instance_resolution_scale,
        )

        settings = Settings()
        old_renderer = MockRendererAdapter()
        old = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=old_renderer,
            viewport_id="a6-t09-recreate",
        )
        old._image = _VisibleViewportImage()
        old._resolution_value_label = _FakeLabel()
        self._open_render_resolution_menu(old)
        old.destroy()

        new_renderer = MockRendererAdapter()
        new = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=new_renderer,
            viewport_id="a6-t09-recreate",
        )
        new._image = _VisibleViewportImage()
        new._resolution_value_label = _FakeLabel()
        try:
            self._open_render_resolution_menu(new)

            write_viewport_instance_resolution(settings, new.viewport_id, [1920, 1080])
            write_viewport_instance_resolution_scale(settings, new.viewport_id, 0.5)

            assert old_renderer.render_call_count == 0
            assert old._resolution_value_label.text == ""
            assert new_renderer.render_call_count == 2
            assert new.get_resolution_state().selected_label == "HD1080P"
            assert new.get_resolution_state().scale == 0.5
            assert new.get_resolution_state().effective_size == (960, 540)
            assert new._resolution_value_label.text == "960×540"

            render_menu = self._open_render_resolution_menu(new)
            assert render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert [
                item.label
                for item in render_menu.items
                if item.kwargs.get("checked")
            ] == ["HD1080P"]
        finally:
            new.destroy()

    def test_shared_custom_list_removal_recovers_selection_via_area2(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
            write_viewport_instance_resolution,
        )

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            self._open_render_resolution_menu(vp)
            write_viewport_instance_resolution(settings, vp.viewport_id, [1500, 1000])
            selected_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0].submenus[0]
            assert selected_menu.kwargs["hotkey_text"] == "Review"
            assert [
                item.label
                for item in selected_menu.items
                if item.kwargs.get("checked")
            ] == ["Review"]

            write_shared_custom_resolution_list(settings, [])

            latest_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0].submenus[0]
            labels = [item.label for item in latest_menu.items]
            checked_labels = [
                item.label for item in latest_menu.items if item.kwargs.get("checked")
            ]
            assert "Review" not in labels
            assert latest_menu.kwargs["hotkey_text"] == "Custom"
            assert checked_labels == ["Custom"]
            assert vp.get_resolution_state().selected_label == "Custom"
        finally:
            vp.destroy()

    def test_preset_list_notification_adds_and_removes_visible_rows(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_catalog import BUILTIN_RESOLUTION_PRESETS
        from ovui_widgets.viewport.resolution_settings import SETTING_RESOLUTION_PRESETS

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            self._open_render_resolution_menu(vp)
            settings.set(SETTING_RESOLUTION_PRESETS, [1920, 1080, 1280, 720])

            latest_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0].submenus[0]
            labels = [item.label for item in latest_menu.items]
            assert labels == ["Viewport", "HD1080P", "HD720P", "Custom"]

            full_setting = [
                value
                for row in BUILTIN_RESOLUTION_PRESETS
                for value in row.dimensions
            ]
            settings.set(SETTING_RESOLUTION_PRESETS, full_setting)

            latest_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0].submenus[0]
            labels = [item.label for item in latest_menu.items]
            assert "SD" in labels
            assert "Ultra Wide" in labels
            assert "Super Ultra Wide" in labels
            assert "5K Wide" in labels
        finally:
            vp.destroy()

    def test_render_scale_option_notification_rebuilds_combo_options(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import SETTING_RENDER_SCALE_LIST

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            assert "66.67%" in render_scale.kwargs["render_scale_options"]

            settings.set(SETTING_RENDER_SCALE_LIST, [1.0, 0.75, 0.5])

            latest_viewport_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0]
            latest_scale = self._viewport_item(latest_viewport_menu, "Render Scale")
            assert latest_scale.kwargs["render_scale_options"] == (
                "100%",
                "75%",
                "50%",
            )
            assert latest_scale.kwargs["render_scale_current_label"] == "100%"

            settings.set(SETTING_RENDER_SCALE_LIST, [1.0, 0.25])

            latest_viewport_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0]
            latest_scale = self._viewport_item(latest_viewport_menu, "Render Scale")
            assert latest_scale.kwargs["render_scale_options"] == ("100%", "25%")
        finally:
            vp.destroy()

    def test_unchanged_shared_option_notification_does_not_duplicate_refresh(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            ResolutionSettingsChange,
            SETTING_RENDER_SCALE_LIST,
        )

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        try:
            self._open_settings_menu(vp)
            menu_count = len(fake_camera_menu.instances)
            current_options = list(vp.get_resolution_settings().render_scale_list)

            vp._on_resolution_settings_change(
                ResolutionSettingsChange(
                    SETTING_RENDER_SCALE_LIST,
                    current_options,
                    vp.viewport_id,
                )
            )

            assert len(fake_camera_menu.instances) == menu_count
            assert renderer.render_call_count == 0
        finally:
            vp.destroy()

    def test_reopened_menu_reads_current_resolution_and_scale_settings(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_viewport_instance_resolution,
            write_viewport_instance_resolution_scale,
        )

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            write_viewport_instance_resolution(settings, vp.viewport_id, [1920, 1080])
            write_viewport_instance_resolution_scale(settings, vp.viewport_id, 0.5)

            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            render_scale = self._viewport_item(viewport_menu, "Render Scale")

            assert vp.get_resolution_state().selected_label == "HD1080P"
            assert render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert [
                item.label for item in render_menu.items if item.kwargs.get("checked")
            ] == ["HD1080P"]
            assert render_scale.kwargs["render_scale_current_label"] == "50%"
            assert render_scale.kwargs["render_scale_current_index"] == (
                render_scale.kwargs["render_scale_options"].index("50%")
            )
        finally:
            vp.destroy()

    def test_reopened_menu_refreshes_unsaved_custom_fields_and_ratio(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_viewport_instance_resolution,
        )

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            write_viewport_instance_resolution(settings, vp.viewport_id, [1500, 1000])

            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")

            assert render_menu.kwargs["hotkey_text"] == "Custom"
            assert [
                item.label for item in render_menu.items if item.kwargs.get("checked")
            ] == ["Custom"]
            assert custom_editor.kwargs["custom_resolution_default_width"] == 1500
            assert custom_editor.kwargs["custom_resolution_default_height"] == 1000
            assert custom_editor.kwargs["custom_resolution_ratio_options"] == (
                "16:9",
                "4:3",
                "1:1",
                "21:9",
                "32:9",
            )
            assert "1500" not in [
                item.label for item in render_menu.items
            ]
        finally:
            vp.destroy()

    def test_reopened_menu_refreshes_fill_checkbox_from_current_state(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_viewport_instance_fill_viewport,
            write_viewport_instance_resolution,
            write_viewport_instance_resolution_scale,
        )

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            write_viewport_instance_resolution(settings, vp.viewport_id, [1024, 1024])
            write_viewport_instance_resolution_scale(settings, vp.viewport_id, 0.5)
            write_viewport_instance_fill_viewport(settings, vp.viewport_id, True)

            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_menu = self._viewport_submenu(
                viewport_menu,
                "Render Resolution",
            )
            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")

            assert render_menu.kwargs["hotkey_text"] == "Square"
            assert [
                item.label for item in render_menu.items if item.kwargs.get("checked")
            ] == ["Square"]
            assert render_scale.kwargs["render_scale_current_label"] == "50%"
            assert fill_viewport.kwargs["fill_viewport_enabled"] is True
            assert fill_viewport.kwargs["fill_viewport_checked"] is True
        finally:
            vp.destroy()

    def test_reopened_menu_reflects_saved_row_add_remove_without_duplicates(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
            write_viewport_instance_resolution,
        )

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            write_shared_custom_resolution_list(
                settings,
                [{"name": "Review", "width": 1500, "height": 1000}],
            )
            write_viewport_instance_resolution(settings, vp.viewport_id, [1500, 1000])

            first_render_menu = self._open_render_resolution_menu(vp)
            second_render_menu = self._open_render_resolution_menu(vp)
            first_labels = [item.label for item in first_render_menu.items]
            second_labels = [item.label for item in second_render_menu.items]
            assert first_labels.count("Review") == 1
            assert second_labels.count("Review") == 1
            assert second_render_menu.kwargs["hotkey_text"] == "Review"
            assert [
                item.label
                for item in second_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Review"]

            write_shared_custom_resolution_list(settings, [])
            latest_render_menu = self._open_render_resolution_menu(vp)
            latest_labels = [item.label for item in latest_render_menu.items]
            assert "Review" not in latest_labels
            assert latest_render_menu.kwargs["hotkey_text"] == "Custom"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Custom"]
        finally:
            vp.destroy()

    def test_open_menu_row_and_scale_changes_refresh_visible_state(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            hd1080p = [
                item for item in render_resolution_menu.items if item.label == "HD1080P"
            ][0]

            assert hd1080p.trigger() is True

            latest_render_menu = self._open_render_resolution_menu(vp)
            latest_viewport_menu = self._latest_viewport_menu()
            latest_scale = self._viewport_item(latest_viewport_menu, "Render Scale")
            assert latest_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["HD1080P"]

            selected_index = latest_scale.kwargs["render_scale_options"].index("50%")
            assert latest_scale.kwargs["render_scale_changed_fn"](selected_index) is True

            latest_render_menu = self._open_render_resolution_menu(vp)
            latest_scale = self._viewport_item(
                self._latest_viewport_menu(),
                "Render Scale",
            )
            assert latest_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["HD1080P"]
            assert latest_scale.kwargs["render_scale_current_label"] == "50%"
            assert vp.get_resolution_state().effective_size == (960, 540)
        finally:
            vp.destroy()

    def test_accept_hd1080p_and_render_scale_50_end_to_end(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_resolution_key,
            viewport_resolution_scale_key,
        )

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
            viewport_id="a8-t01-happy-path",
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1280,
            computed_height=720,
        )
        vp._resolution_value_label = _FakeLabel()

        def checked_labels(render_menu):
            return [
                item.label
                for item in render_menu.items
                if item.kwargs.get("checked")
            ]

        def item_by_label(menu, label):
            return [item for item in menu.items if item.label == label][0]

        try:
            assert vp._resolution_render_qa_window is None
            assert vp._resolution_catalog_qa_window is None
            assert vp._resolution_settings_schema_qa_window is None
            assert [
                contribution.label
                for contribution in vp._pre_tools_toolbar_hooks.iter_contributions()
            ] == ["Settings"]
            assert vp.toolbar_hooks.iter_contributions() == ()

            settings_menu = self._open_settings_menu(vp)
            assert settings_menu.title == "Settings"
            assert [submenu.title for submenu in settings_menu.submenus] == [
                "Viewport"
            ]
            viewport_menu = settings_menu.submenus[0]
            render_menu = self._viewport_submenu(viewport_menu, "Render Resolution")
            assert render_menu.kwargs["hotkey_text"] == "Viewport"
            assert checked_labels(render_menu) == ["Viewport"]
            assert self._viewport_item(
                viewport_menu,
                "Render Scale",
            ).kwargs["render_scale_current_label"] == "100%"

            hd1080p = item_by_label(render_menu, "HD1080P")
            assert hd1080p.trigger() is True

            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [
                1920,
                1080,
            ]
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1920, 1080)
            assert state.selected_label == "HD1080P"
            assert state.scale == 1.0
            assert state.effective_size == (1920, 1080)
            assert vp._last_resolution == (1920, 1080)
            assert getattr(vp._last_image_frame, "shape", None) == (1080, 1920, 4)
            assert vp._resolution_value_label.text == "1920×1080"
            self._assert_settings_menu_closed(vp, settings_menu)

            latest_render_menu = self._open_render_resolution_menu(vp)
            latest_viewport_menu = self._latest_viewport_menu()
            assert latest_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert checked_labels(latest_render_menu) == ["HD1080P"]
            latest_scale = self._viewport_item(latest_viewport_menu, "Render Scale")
            assert latest_scale.kwargs["render_scale_current_label"] == "100%"

            selected_index = latest_scale.kwargs["render_scale_options"].index("50%")
            assert latest_scale.kwargs["render_scale_changed_fn"](selected_index) is True

            assert settings.get(viewport_resolution_scale_key(vp.viewport_id)) == 0.5
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1920, 1080)
            assert state.selected_label == "HD1080P"
            assert state.scale == 0.5
            assert state.effective_size == (960, 540)
            assert vp._last_resolution == (960, 540)
            assert getattr(vp._last_image_frame, "shape", None) == (540, 960, 4)
            assert vp._resolution_value_label.text == "960×540"
            self._assert_settings_menu_closed(vp, self._latest_settings_menu())

            reopened_render_menu = self._open_render_resolution_menu(vp)
            reopened_viewport_menu = self._latest_viewport_menu()
            reopened_scale = self._viewport_item(reopened_viewport_menu, "Render Scale")
            assert reopened_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert checked_labels(reopened_render_menu) == ["HD1080P"]
            assert reopened_scale.kwargs["render_scale_current_label"] == "50%"

            hd1080p_again = item_by_label(reopened_render_menu, "HD1080P")
            assert hd1080p_again.trigger() is True
            self._assert_settings_menu_closed(vp, self._latest_settings_menu())

            final_render_menu = self._open_render_resolution_menu(vp)
            final_scale = self._viewport_item(
                self._latest_viewport_menu(),
                "Render Scale",
            )
            assert final_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert checked_labels(final_render_menu) == ["HD1080P"]
            assert final_scale.kwargs["render_scale_current_label"] == "50%"
            assert vp.get_resolution_state().effective_size == (960, 540)
            assert vp._last_resolution == (960, 540)
            assert vp._resolution_value_label.text == "960×540"
            assert vp._resolution_render_qa_window is None
            assert vp._resolution_catalog_qa_window is None
            assert vp._resolution_settings_schema_qa_window is None
        finally:
            vp.destroy()

    def test_accept_square_fill_viewport_end_to_end(
        self,
        fake_camera_menu,
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_fill_viewport_key,
            viewport_resolution_key,
        )

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
            viewport_id="a8-t02-square-fill",
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1600,
            computed_height=900,
        )
        vp._resolution_value_label = _FakeLabel()

        def checked_labels(render_menu):
            return [
                item.label
                for item in render_menu.items
                if item.kwargs.get("checked")
            ]

        def item_by_label(menu, label):
            return [item for item in menu.items if item.label == label][0]

        try:
            assert vp._resolution_render_qa_window is None
            assert vp._resolution_catalog_qa_window is None
            assert vp._resolution_settings_schema_qa_window is None
            assert [
                contribution.label
                for contribution in vp._pre_tools_toolbar_hooks.iter_contributions()
            ] == ["Settings"]
            assert vp.toolbar_hooks.iter_contributions() == ()

            settings_menu = self._open_settings_menu(vp)
            viewport_menu = settings_menu.submenus[0]
            render_menu = self._viewport_submenu(viewport_menu, "Render Resolution")
            assert render_menu.kwargs["hotkey_text"] == "Viewport"
            assert checked_labels(render_menu) == ["Viewport"]
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")
            assert fill_viewport.kwargs["fill_viewport_enabled"] is False
            assert fill_viewport.kwargs["fill_viewport_checked"] is False

            square = item_by_label(render_menu, "Square")
            assert square.trigger() is True

            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [
                1024,
                1024,
            ]
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1024, 1024)
            assert state.selected_label == "Square"
            assert state.scale == 1.0
            assert state.fill_viewport is False
            assert state.effective_size == (1024, 1024)
            assert vp._last_resolution == (1024, 1024)
            assert getattr(vp._last_image_frame, "shape", None) == (1024, 1024, 4)
            assert vp._resolution_value_label.text == "1024×1024"
            self._assert_settings_menu_closed(vp, settings_menu)

            latest_render_menu = self._open_render_resolution_menu(vp)
            latest_viewport_menu = self._latest_viewport_menu()
            latest_fill = self._viewport_item(latest_viewport_menu, "Fill Viewport")
            assert latest_render_menu.kwargs["hotkey_text"] == "Square"
            assert checked_labels(latest_render_menu) == ["Square"]
            assert latest_fill.kwargs["fill_viewport_enabled"] is True
            assert latest_fill.kwargs["fill_viewport_checked"] is False

            assert latest_fill.trigger() is True

            assert settings.get(viewport_fill_viewport_key(vp.viewport_id)) is True
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1024, 1024)
            assert state.selected_label == "Square"
            assert state.scale == 1.0
            assert state.fill_viewport is True
            assert state.effective_size == (1820, 1024)
            assert vp._last_resolution == (1820, 1024)
            assert getattr(vp._last_image_frame, "shape", None) == (1024, 1820, 4)
            assert vp._resolution_value_label.text == "1820×1024"
            self._assert_settings_menu_closed(vp, self._latest_settings_menu())

            reopened_render_menu = self._open_render_resolution_menu(vp)
            reopened_viewport_menu = self._latest_viewport_menu()
            reopened_fill = self._viewport_item(reopened_viewport_menu, "Fill Viewport")
            assert reopened_render_menu.kwargs["hotkey_text"] == "Square"
            assert checked_labels(reopened_render_menu) == ["Square"]
            assert reopened_fill.kwargs["fill_viewport_enabled"] is True
            assert reopened_fill.kwargs["fill_viewport_checked"] is True

            viewport_row = item_by_label(reopened_render_menu, "Viewport")
            assert viewport_row.trigger() is True
            self._assert_settings_menu_closed(vp, self._latest_settings_menu())

            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [0, 0]
            state = vp.get_resolution_state()
            assert state.is_viewport_mode is True
            assert state.selected_label == "Viewport"
            assert state.fill_viewport is False
            assert state.effective_size == (1600, 900)
            assert vp._last_resolution == (1600, 900)
            assert getattr(vp._last_image_frame, "shape", None) == (900, 1600, 4)
            assert vp._resolution_value_label.text == "1600×900"

            final_render_menu = self._open_render_resolution_menu(vp)
            final_fill = self._viewport_item(
                self._latest_viewport_menu(),
                "Fill Viewport",
            )
            assert final_render_menu.kwargs["hotkey_text"] == "Viewport"
            assert checked_labels(final_render_menu) == ["Viewport"]
            assert final_fill.kwargs["fill_viewport_enabled"] is False
            assert final_fill.kwargs["fill_viewport_checked"] is False
            assert settings.get(viewport_fill_viewport_key(vp.viewport_id)) is True
            assert vp._resolution_render_qa_window is None
            assert vp._resolution_catalog_qa_window is None
            assert vp._resolution_settings_schema_qa_window is None
        finally:
            vp.destroy()

    def test_accept_saved_custom_create_and_select_end_to_end(
        self,
        fake_camera_menu,
        monkeypatch,
    ):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key

        frame_waits = []

        async def _fake_next_frame():
            frame_waits.append("frame")
            await asyncio.sleep(0)

        monkeypatch.setattr(viewport_mod.ui, "next_frame", _fake_next_frame)

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
            viewport_id="a8-t03-saved-custom",
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1280,
            computed_height=720,
        )
        vp._resolution_value_label = _FakeLabel()

        def checked_labels(render_menu):
            return [
                item.label
                for item in render_menu.items
                if item.kwargs.get("checked")
            ]

        def rows_by_label(render_menu):
            return {item.label: item for item in render_menu.items}

        try:
            assert vp._resolution_render_qa_window is None
            assert vp._resolution_catalog_qa_window is None
            assert vp._resolution_settings_schema_qa_window is None
            assert [
                contribution.label
                for contribution in vp._pre_tools_toolbar_hooks.iter_contributions()
            ] == ["Settings"]
            assert vp.toolbar_hooks.iter_contributions() == ()

            settings_menu = self._open_settings_menu(vp)
            viewport_menu = settings_menu.submenus[0]
            render_menu = self._viewport_submenu(viewport_menu, "Render Resolution")
            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            assert render_menu.kwargs["hotkey_text"] == "Viewport"
            assert checked_labels(render_menu) == ["Viewport"]
            assert custom_editor.kwargs["custom_resolution_editor"] is True
            assert custom_editor.kwargs["custom_resolution_save_handoff"] is True

            apply_fn = custom_editor.kwargs["custom_resolution_apply_fn"]

            async def _apply_custom_size():
                assert apply_fn(1500, 1000) is True
                assert settings.get(viewport_resolution_key(vp.viewport_id)) is None
                assert vp.get_resolution_state().selected_label == "Viewport"

                for _ in range(10):
                    await asyncio.sleep(0)

            asyncio.run(_apply_custom_size())

            assert frame_waits
            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [
                1500,
                1000,
            ]
            assert vp.get_resolution_settings().custom_list == []
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1500, 1000)
            assert state.selected_label == "Custom"
            assert state.scale == 1.0
            assert state.effective_size == (1500, 1000)
            assert vp._last_resolution == (1500, 1000)
            assert getattr(vp._last_image_frame, "shape", None) == (1000, 1500, 4)
            assert vp._resolution_value_label.text == "1500×1000"

            latest_viewport_menu = self._open_settings_menu(vp).submenus[0]
            latest_render_menu = self._viewport_submenu(
                latest_viewport_menu,
                "Render Resolution",
            )
            latest_custom_editor = self._viewport_item(
                latest_viewport_menu,
                "Custom Resolution",
            )
            assert latest_render_menu.kwargs["hotkey_text"] == "Custom"
            assert checked_labels(latest_render_menu) == ["Custom"]
            assert latest_custom_editor.kwargs["custom_resolution_default_width"] == 1500
            assert latest_custom_editor.kwargs["custom_resolution_default_height"] == 1000
            assert latest_custom_editor.kwargs[
                "custom_resolution_save_enabled_fn"
            ](1500, 1000) is True

            assert latest_custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is True
            window = vp._custom_resolution_save_dialog_window
            assert window is not None
            assert window.title == "Save Custom Viewport Resolution"
            assert window.visible is True
            assert vp._custom_resolution_save_dialog_size == (1500, 1000)
            assert vp._custom_resolution_save_dialog_resolution_label.text == (
                "1500 x 1000"
            )
            assert vp._custom_resolution_save_dialog_save_button.enabled is True
            assert vp._custom_resolution_save_dialog_error_label.text == ""

            vp._custom_resolution_save_dialog_name_field.model.set_value("Review")
            vp._custom_resolution_save_dialog_key_pressed(
                viewport_mod._IMGUI_KEY_ENTER,
                0,
                True,
            )

            assert vp._custom_resolution_save_dialog_window.visible is False
            assert vp.get_resolution_settings().custom_list == [
                {"name": "Review", "width": 1500, "height": 1000}
            ]
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1500, 1000)
            assert state.selected_label == "Review"
            assert state.effective_size is None

            assert vp.render(1.0 / 60.0) is True
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1500, 1000)
            assert state.selected_label == "Review"
            assert state.effective_size == (1500, 1000)
            assert vp._last_resolution == (1500, 1000)
            assert getattr(vp._last_image_frame, "shape", None) == (1000, 1500, 4)
            assert vp._resolution_value_label.text == "1500×1000"

            saved_render_menu = self._open_render_resolution_menu(vp)
            saved_viewport_menu = self._latest_viewport_menu()
            saved_custom_editor = self._viewport_item(
                saved_viewport_menu,
                "Custom Resolution",
            )
            rows = rows_by_label(saved_render_menu)
            review_rows = [
                item for item in saved_render_menu.items if item.label == "Review"
            ]
            assert saved_render_menu.kwargs["hotkey_text"] == "Review"
            assert checked_labels(saved_render_menu) == ["Review"]
            assert len(review_rows) == 1
            assert review_rows[0].kwargs["checked"] is True
            assert "1500x1000" in str(rows["Review"].kwargs.get("hotkey_text"))
            assert "1.50:1" in str(rows["Review"].kwargs.get("hotkey_text"))

            assert saved_custom_editor.kwargs["custom_resolution_default_width"] == 1500
            assert saved_custom_editor.kwargs["custom_resolution_default_height"] == 1000
            assert saved_custom_editor.kwargs[
                "custom_resolution_save_enabled_fn"
            ](1500, 1000) is False
            assert saved_custom_editor.kwargs["custom_resolution_save_handoff_fn"]() is False
            assert vp._custom_resolution_save_dialog_window.visible is False

            duplicate_render_menu = self._open_render_resolution_menu(vp)
            duplicate_review_rows = [
                item for item in duplicate_render_menu.items if item.label == "Review"
            ]
            assert duplicate_render_menu.kwargs["hotkey_text"] == "Review"
            assert checked_labels(duplicate_render_menu) == ["Review"]
            assert len(duplicate_review_rows) == 1
            assert vp.get_resolution_settings().custom_list == [
                {"name": "Review", "width": 1500, "height": 1000}
            ]
            assert vp._resolution_render_qa_window is None
            assert vp._resolution_catalog_qa_window is None
            assert vp._resolution_settings_schema_qa_window is None
        finally:
            vp.destroy()

    def test_accept_resolution_persistence_across_real_restart_end_to_end(
        self,
        fake_camera_menu,
        monkeypatch,
        tmp_path,
    ):
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key

        frame_waits = []

        async def _fake_next_frame():
            frame_waits.append("frame")
            await asyncio.sleep(0)

        monkeypatch.setattr(viewport_mod.ui, "next_frame", _fake_next_frame)

        settings_path = tmp_path / "a8_t04_settings.json"
        monkeypatch.setenv("OVUI_WIDGETS_SETTINGS_PATH", str(settings_path))

        def _reset_application_singletons():
            Application._instance = None
            SelectionBus._instance = None
            Settings.set_instance(None)

        def _new_app():
            _reset_application_singletons()
            return Application()

        def _make_viewport(app):
            vp = ViewportWidget(
                services=app,
                renderer=MockRendererAdapter(),
                viewport_id="main",
            )
            vp._image = SimpleNamespace(
                visible=True,
                computed_width=1280,
                computed_height=720,
            )
            vp._resolution_value_label = _FakeLabel()
            return vp

        def checked_labels(render_menu):
            return [
                item.label
                for item in render_menu.items
                if item.kwargs.get("checked")
            ]

        def review_rows(render_menu):
            return [item for item in render_menu.items if item.label == "Review"]

        first = None
        first_vp = None
        second = None
        second_vp = None
        try:
            first = _new_app()
            first_vp = _make_viewport(first)

            settings_menu = self._open_settings_menu(first_vp)
            viewport_menu = settings_menu.submenus[0]
            render_menu = self._viewport_submenu(viewport_menu, "Render Resolution")
            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            assert render_menu.kwargs["hotkey_text"] == "Viewport"
            assert checked_labels(render_menu) == ["Viewport"]

            apply_fn = custom_editor.kwargs["custom_resolution_apply_fn"]

            async def _apply_custom_size():
                assert apply_fn(1500, 1000) is True
                assert first.settings.get(viewport_resolution_key("main")) is None

                for _ in range(10):
                    await asyncio.sleep(0)

            asyncio.run(_apply_custom_size())

            assert frame_waits
            assert first_vp.get_resolution_state().selected_label == "Custom"
            assert first_vp._resolution_value_label.text == "1500×1000"

            latest_viewport_menu = self._open_settings_menu(first_vp).submenus[0]
            latest_custom_editor = self._viewport_item(
                latest_viewport_menu,
                "Custom Resolution",
            )
            assert latest_custom_editor.kwargs[
                "custom_resolution_save_enabled_fn"
            ](1500, 1000) is True
            assert latest_custom_editor.kwargs[
                "custom_resolution_save_handoff_fn"
            ]() is True
            assert first_vp._custom_resolution_save_dialog_window.visible is True

            first_vp._custom_resolution_save_dialog_name_field.model.set_value("Review")
            first_vp._custom_resolution_save_dialog_key_pressed(
                viewport_mod._IMGUI_KEY_ENTER,
                0,
                True,
            )

            assert first_vp._custom_resolution_save_dialog_window.visible is False
            assert first_vp.render(1.0 / 60.0) is True

            pre_scale_viewport_menu = self._open_settings_menu(first_vp).submenus[0]
            pre_scale_render_menu = self._viewport_submenu(
                pre_scale_viewport_menu,
                "Render Resolution",
            )
            scale_item = self._viewport_item(pre_scale_viewport_menu, "Render Scale")
            fill_item = self._viewport_item(pre_scale_viewport_menu, "Fill Viewport")
            assert pre_scale_render_menu.kwargs["hotkey_text"] == "Review"
            assert checked_labels(pre_scale_render_menu) == ["Review"]
            assert len(review_rows(pre_scale_render_menu)) == 1
            assert fill_item.kwargs["fill_viewport_enabled"] is True
            assert fill_item.kwargs["fill_viewport_checked"] is False

            selected_index = scale_item.kwargs["render_scale_options"].index("50%")
            assert scale_item.kwargs["render_scale_changed_fn"](selected_index) is True

            pre_quit_state = first_vp.get_resolution_state()
            assert pre_quit_state.selected_label == "Review"
            assert pre_quit_state.requested_size == (1500, 1000)
            assert pre_quit_state.scale == 0.5
            assert pre_quit_state.fill_viewport is False
            assert pre_quit_state.effective_size == (750, 500)
            assert first_vp._last_resolution == (750, 500)
            assert getattr(first_vp._last_image_frame, "shape", None) == (500, 750, 4)
            assert first_vp._resolution_value_label.text == "750×500"

            pre_quit_render_menu = self._open_render_resolution_menu(first_vp)
            pre_quit_viewport_menu = self._latest_viewport_menu()
            pre_quit_scale = self._viewport_item(pre_quit_viewport_menu, "Render Scale")
            pre_quit_fill = self._viewport_item(
                pre_quit_viewport_menu,
                "Fill Viewport",
            )
            assert pre_quit_render_menu.kwargs["hotkey_text"] == "Review"
            assert checked_labels(pre_quit_render_menu) == ["Review"]
            assert pre_quit_scale.kwargs["render_scale_current_label"] == "50%"
            assert pre_quit_fill.kwargs["fill_viewport_checked"] is False

            first_vp.destroy()
            first_vp = None
            first.shutdown()
            first = None

            second = _new_app()
            second_vp = _make_viewport(second)

            restored_initial_state = second_vp.get_resolution_state()
            assert restored_initial_state.selected_label == "Review"
            assert restored_initial_state.requested_size == (1500, 1000)
            assert restored_initial_state.scale == 0.5
            assert restored_initial_state.fill_viewport is False
            assert restored_initial_state.effective_size is None

            assert second_vp.render(1.0 / 60.0) is True

            restored_state = second_vp.get_resolution_state()
            assert restored_state.selected_label == "Review"
            assert restored_state.requested_size == (1500, 1000)
            assert restored_state.scale == 0.5
            assert restored_state.fill_viewport is False
            assert restored_state.effective_size == (750, 500)
            assert second_vp._last_resolution == (750, 500)
            assert getattr(second_vp._last_image_frame, "shape", None) == (500, 750, 4)
            assert second_vp._resolution_value_label.text == "750×500"

            restored_render_menu = self._open_render_resolution_menu(second_vp)
            restored_viewport_menu = self._latest_viewport_menu()
            restored_scale = self._viewport_item(restored_viewport_menu, "Render Scale")
            restored_fill = self._viewport_item(
                restored_viewport_menu,
                "Fill Viewport",
            )
            restored_review_rows = review_rows(restored_render_menu)
            assert restored_render_menu.kwargs["hotkey_text"] == "Review"
            assert checked_labels(restored_render_menu) == ["Review"]
            assert len(restored_review_rows) == 1
            assert restored_review_rows[0].kwargs["checked"] is True
            assert "1500x1000" in str(
                restored_review_rows[0].kwargs.get("hotkey_text")
            )
            assert restored_scale.kwargs["render_scale_current_label"] == "50%"
            assert restored_fill.kwargs["fill_viewport_enabled"] is True
            assert restored_fill.kwargs["fill_viewport_checked"] is False

            reopened_render_menu = self._open_render_resolution_menu(second_vp)
            reopened_viewport_menu = self._latest_viewport_menu()
            reopened_scale = self._viewport_item(reopened_viewport_menu, "Render Scale")
            reopened_fill = self._viewport_item(reopened_viewport_menu, "Fill Viewport")
            assert reopened_render_menu.kwargs["hotkey_text"] == "Review"
            assert checked_labels(reopened_render_menu) == ["Review"]
            assert len(review_rows(reopened_render_menu)) == 1
            assert reopened_scale.kwargs["render_scale_current_label"] == "50%"
            assert reopened_fill.kwargs["fill_viewport_checked"] is False
            assert second_vp._resolution_value_label.text == "750×500"
            assert second_vp._resolution_render_qa_window is None
            assert second_vp._resolution_catalog_qa_window is None
            assert second_vp._resolution_settings_schema_qa_window is None
        finally:
            if first_vp is not None:
                first_vp.destroy()
            if second_vp is not None:
                second_vp.destroy()
            if first is not None:
                first.shutdown()
            if second is not None:
                second.shutdown()
            _reset_application_singletons()

    def test_accept_multi_viewport_independence_with_shared_custom_rows_end_to_end(
        self,
        fake_camera_menu,
        monkeypatch,
    ):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_fill_viewport_key,
            viewport_resolution_key,
            viewport_resolution_scale_key,
        )

        frame_waits = []

        async def _fake_next_frame():
            frame_waits.append("frame")
            await asyncio.sleep(0)

        monkeypatch.setattr(viewport_mod.ui, "next_frame", _fake_next_frame)

        settings = Settings()
        renderer_a = MockRendererAdapter()
        renderer_b = MockRendererAdapter()
        viewport_a = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer_a,
            viewport_id="a8-t05-viewport-a",
        )
        viewport_b = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer_b,
            viewport_id="a8-t05-viewport-b",
        )
        viewport_a._image = SimpleNamespace(
            visible=True,
            computed_width=1280,
            computed_height=720,
        )
        viewport_b._image = SimpleNamespace(
            visible=True,
            computed_width=1400,
            computed_height=900,
        )
        viewport_a._resolution_value_label = _FakeLabel()
        viewport_b._resolution_value_label = _FakeLabel()

        def checked_labels(render_menu):
            return [
                item.label
                for item in render_menu.items
                if item.kwargs.get("checked")
            ]

        def item_by_label(menu, label):
            return [item for item in menu.items if item.label == label][0]

        def review_rows(render_menu):
            return [item for item in render_menu.items if item.label == "Review"]

        def viewport_controls(vp):
            viewport_menu = self._open_settings_menu(vp).submenus[0]
            render_menu = self._viewport_submenu(viewport_menu, "Render Resolution")
            custom_editor = self._viewport_item(viewport_menu, "Custom Resolution")
            render_scale = self._viewport_item(viewport_menu, "Render Scale")
            fill_viewport = self._viewport_item(viewport_menu, "Fill Viewport")
            return viewport_menu, render_menu, custom_editor, render_scale, fill_viewport

        try:
            assert viewport_a.render(1.0 / 60.0) is True
            assert viewport_b.render(1.0 / 60.0) is True
            assert viewport_a._resolution_value_label.text == "1280×720"
            assert viewport_b._resolution_value_label.text == "1400×900"

            _, a_menu, _, a_scale, _ = viewport_controls(viewport_a)
            assert item_by_label(a_menu, "HD1080P").trigger() is True
            latest_a_scale = self._viewport_item(
                self._latest_viewport_menu(),
                "Render Scale",
            )
            scale_50_index = latest_a_scale.kwargs["render_scale_options"].index("50%")
            assert latest_a_scale.kwargs["render_scale_changed_fn"](scale_50_index) is True

            a_state = viewport_a.get_resolution_state()
            b_state = viewport_b.get_resolution_state()
            assert a_state.selected_label == "HD1080P"
            assert a_state.requested_size == (1920, 1080)
            assert a_state.scale == 0.5
            assert a_state.effective_size == (960, 540)
            assert viewport_a._last_resolution == (960, 540)
            assert getattr(viewport_a._last_image_frame, "shape", None) == (
                540,
                960,
                4,
            )
            assert viewport_a._resolution_value_label.text == "960×540"
            assert b_state.selected_label == "Viewport"
            assert b_state.requested_size == (0, 0)
            assert b_state.scale == 1.0
            assert b_state.effective_size == (1400, 900)
            assert viewport_b._last_resolution == (1400, 900)
            assert viewport_b._resolution_value_label.text == "1400×900"
            assert settings.get(viewport_resolution_key(viewport_b.viewport_id)) is None
            assert settings.get(viewport_resolution_scale_key(viewport_b.viewport_id)) is None

            _, b_menu, _, b_scale, b_fill = viewport_controls(viewport_b)
            assert item_by_label(b_menu, "Square").trigger() is True
            assert viewport_b.render(1.0 / 60.0) is True

            a_state = viewport_a.get_resolution_state()
            b_state = viewport_b.get_resolution_state()
            assert a_state.selected_label == "HD1080P"
            assert a_state.effective_size == (960, 540)
            assert viewport_a._resolution_value_label.text == "960×540"
            assert b_state.selected_label == "Square"
            assert b_state.requested_size == (1024, 1024)
            assert b_state.scale == 1.0
            assert b_state.fill_viewport is False
            assert b_state.effective_size == (1024, 1024)
            assert viewport_b._last_resolution == (1024, 1024)
            assert getattr(viewport_b._last_image_frame, "shape", None) == (
                1024,
                1024,
                4,
            )
            assert viewport_b._resolution_value_label.text == "1024×1024"
            assert settings.get(viewport_resolution_key(viewport_a.viewport_id)) == [
                1920,
                1080,
            ]
            assert settings.get(viewport_resolution_key(viewport_b.viewport_id)) == [
                1024,
                1024,
            ]
            assert b_scale.kwargs["render_scale_current_label"] == "100%"
            assert b_fill.kwargs["fill_viewport_enabled"] is False
            b_render_count_after_square = renderer_b.render_call_count

            (
                _,
                _,
                a_custom_editor,
                _,
                _,
            ) = viewport_controls(viewport_a)
            apply_fn = a_custom_editor.kwargs["custom_resolution_apply_fn"]

            async def _apply_review_dimensions():
                assert apply_fn(1500, 1000) is True
                for _ in range(10):
                    await asyncio.sleep(0)

            asyncio.run(_apply_review_dimensions())
            assert frame_waits
            assert viewport_a.get_resolution_state().selected_label == "Custom"
            assert viewport_b.get_resolution_state().selected_label == "Square"
            assert viewport_b._resolution_value_label.text == "1024×1024"

            latest_a_viewport_menu = self._open_settings_menu(viewport_a).submenus[0]
            latest_a_custom_editor = self._viewport_item(
                latest_a_viewport_menu,
                "Custom Resolution",
            )
            assert latest_a_custom_editor.kwargs[
                "custom_resolution_save_enabled_fn"
            ](1500, 1000) is True
            assert latest_a_custom_editor.kwargs[
                "custom_resolution_save_handoff_fn"
            ]() is True
            assert viewport_a._custom_resolution_save_dialog_window.visible is True
            viewport_a._custom_resolution_save_dialog_name_field.model.set_value("Review")
            viewport_a._custom_resolution_save_dialog_key_pressed(
                viewport_mod._IMGUI_KEY_ENTER,
                0,
                True,
            )

            assert viewport_a._custom_resolution_save_dialog_window.visible is False
            assert viewport_a.render(1.0 / 60.0) is True
            assert viewport_a.get_resolution_settings().custom_list == [
                {"name": "Review", "width": 1500, "height": 1000}
            ]

            a_state = viewport_a.get_resolution_state()
            b_state = viewport_b.get_resolution_state()
            assert a_state.selected_label == "Review"
            assert a_state.requested_size == (1500, 1000)
            assert a_state.scale == 0.5
            assert a_state.effective_size == (750, 500)
            assert viewport_a._last_resolution == (750, 500)
            assert viewport_a._resolution_value_label.text == "750×500"
            assert b_state.selected_label == "Square"
            assert b_state.requested_size == (1024, 1024)
            assert viewport_b._last_resolution == (1024, 1024)
            assert getattr(viewport_b._last_image_frame, "shape", None) == (
                1024,
                1024,
                4,
            )
            assert viewport_b._resolution_value_label.text == "1024×1024"

            saved_a_menu = self._open_render_resolution_menu(viewport_a)
            saved_b_menu = self._open_render_resolution_menu(viewport_b)
            assert saved_a_menu.kwargs["hotkey_text"] == "Review"
            assert checked_labels(saved_a_menu) == ["Review"]
            assert len(review_rows(saved_a_menu)) == 1
            assert saved_b_menu.kwargs["hotkey_text"] == "Square"
            assert checked_labels(saved_b_menu) == ["Square"]
            assert len(review_rows(saved_b_menu)) == 1
            assert settings.get(viewport_resolution_key(viewport_b.viewport_id)) == [
                1024,
                1024,
            ]
            assert settings.get(viewport_resolution_scale_key(viewport_b.viewport_id)) is None
            assert settings.get(viewport_fill_viewport_key(viewport_b.viewport_id)) is None
            assert renderer_b.render_call_count == b_render_count_after_square

            assert item_by_label(saved_b_menu, "Review").trigger() is True

            b_state = viewport_b.get_resolution_state()
            a_state = viewport_a.get_resolution_state()
            assert b_state.selected_label == "Review"
            assert b_state.requested_size == (1500, 1000)
            assert b_state.scale == 1.0
            assert b_state.effective_size == (1500, 1000)
            assert viewport_b._last_resolution == (1500, 1000)
            assert getattr(viewport_b._last_image_frame, "shape", None) == (
                1000,
                1500,
                4,
            )
            assert viewport_b._resolution_value_label.text == "1500×1000"
            assert a_state.selected_label == "Review"
            assert a_state.scale == 0.5
            assert a_state.effective_size == (750, 500)
            assert viewport_a._resolution_value_label.text == "750×500"

            a_after_b_menu = self._open_render_resolution_menu(viewport_a)
            b_after_b_menu = self._open_render_resolution_menu(viewport_b)
            assert a_after_b_menu.kwargs["hotkey_text"] == "Review"
            assert checked_labels(a_after_b_menu) == ["Review"]
            assert len(review_rows(a_after_b_menu)) == 1
            assert b_after_b_menu.kwargs["hotkey_text"] == "Review"
            assert checked_labels(b_after_b_menu) == ["Review"]
            assert len(review_rows(b_after_b_menu)) == 1

            a_viewport_menu = self._open_settings_menu(viewport_a).submenus[0]
            a_scale = self._viewport_item(a_viewport_menu, "Render Scale")
            scale_25_index = a_scale.kwargs["render_scale_options"].index("25%")
            assert a_scale.kwargs["render_scale_changed_fn"](scale_25_index) is True

            a_state = viewport_a.get_resolution_state()
            b_state = viewport_b.get_resolution_state()
            assert a_state.selected_label == "Review"
            assert a_state.scale == 0.25
            assert a_state.effective_size == (375, 250)
            assert viewport_a._last_resolution == (375, 250)
            assert getattr(viewport_a._last_image_frame, "shape", None) == (
                250,
                375,
                4,
            )
            assert viewport_a._resolution_value_label.text == "375×250"
            assert b_state.selected_label == "Review"
            assert b_state.scale == 1.0
            assert b_state.effective_size == (1500, 1000)
            assert viewport_b._last_resolution == (1500, 1000)
            assert viewport_b._resolution_value_label.text == "1500×1000"
            assert settings.get(viewport_resolution_scale_key(viewport_a.viewport_id)) == 0.25
            assert settings.get(viewport_resolution_scale_key(viewport_b.viewport_id)) is None

            final_a_menu = self._open_render_resolution_menu(viewport_a)
            final_a_viewport_menu = self._latest_viewport_menu()
            final_a_scale = self._viewport_item(
                final_a_viewport_menu,
                "Render Scale",
            )
            final_b_menu = self._open_render_resolution_menu(viewport_b)
            final_b_viewport_menu = self._latest_viewport_menu()
            final_b_scale = self._viewport_item(
                final_b_viewport_menu,
                "Render Scale",
            )
            assert final_a_menu.kwargs["hotkey_text"] == "Review"
            assert checked_labels(final_a_menu) == ["Review"]
            assert len(review_rows(final_a_menu)) == 1
            assert final_b_menu.kwargs["hotkey_text"] == "Review"
            assert checked_labels(final_b_menu) == ["Review"]
            assert len(review_rows(final_b_menu)) == 1
            assert final_a_scale.kwargs["render_scale_current_label"] == "25%"
            assert final_b_scale.kwargs["render_scale_current_label"] == "100%"
            assert viewport_a._resolution_render_qa_window is None
            assert viewport_b._resolution_render_qa_window is None
            assert viewport_a._resolution_catalog_qa_window is None
            assert viewport_b._resolution_catalog_qa_window is None
            assert viewport_a._resolution_settings_schema_qa_window is None
            assert viewport_b._resolution_settings_schema_qa_window is None
        finally:
            viewport_b.destroy()
            viewport_a.destroy()

    def test_accept_openusd_session_layer_resolution_with_clean_root_end_to_end(
        self,
        fake_camera_menu,
    ):
        pytest.importorskip("pxr")
        from pxr import Usd, UsdGeom, UsdRender

        from ovui_data_adapters.openusd.renderer_adapter import (
            _CAMERA_PATH,
            _LDR_VAR_PATH,
            _RENDER_PRODUCT_PATH,
            OvRtxRendererAdapter,
        )
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_scale_key

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        root_before = stage.GetRootLayer().ExportToString()

        class _OpenUsdSessionAcceptanceRenderer(MockRendererAdapter):
            def __init__(self, stage):
                super().__init__()
                self.added_session_usda = []
                self.removed_session_handles = []
                self._clock_value = 0.0
                self.session_adapter = object.__new__(OvRtxRendererAdapter)
                self.session_adapter._stage = stage
                self.session_adapter._renderer = SimpleNamespace(
                    remove_usd=lambda handle: self.removed_session_handles.append(
                        handle,
                    ),
                )
                self.session_adapter._session_handle = "initial-session"
                self.session_adapter._last_resolution = (640, 360)
                self.session_adapter._last_big_delta_time = float("-inf")
                self.session_adapter._last_reinject_time = float("-inf")
                self.session_adapter._clock = lambda: self._clock_value
                self.session_adapter._scene_has_lights = True
                self.session_adapter._render_product_path = _RENDER_PRODUCT_PATH
                self.session_adapter._default_render_product_path = _RENDER_PRODUCT_PATH
                self.session_adapter._camera_path = _CAMERA_PATH
                self.session_adapter._default_camera_path = _CAMERA_PATH
                self.session_adapter._last_pushed_camera_intrinsics = None
                self.session_adapter._session_render_product_setting_lines = lambda: ()

                def _add_session_layer(usda: str) -> str:
                    self.added_session_usda.append(usda)
                    return f"a8-t06-session-{len(self.added_session_usda)}"

                self.session_adapter._add_ovrtx_session_layer = _add_session_layer

            def render_frame(self, width, height, view_matrix, proj_matrix):
                self._clock_value += 1.0
                self.session_adapter._apply_resolution_if_allowed(
                    (int(width), int(height)),
                )
                return super().render_frame(width, height, view_matrix, proj_matrix)

        def checked_labels(render_menu):
            return [
                item.label
                for item in render_menu.items
                if item.kwargs.get("checked")
            ]

        def item_by_label(menu, label):
            return [item for item in menu.items if item.label == label][0]

        def session_render_product_resolution():
            prim = stage.GetPrimAtPath(_RENDER_PRODUCT_PATH)
            assert prim.IsValid()
            product = UsdRender.Product(prim)
            value = product.GetResolutionAttr().Get()
            return (int(value[0]), int(value[1]))

        def assert_layer_report(target):
            assert session_render_product_resolution() == target
            assert stage.GetSessionLayer().GetPrimAtPath(_RENDER_PRODUCT_PATH) is not None
            assert stage.GetRootLayer().GetPrimAtPath(_RENDER_PRODUCT_PATH) is None
            assert stage.GetRootLayer().ExportToString() == root_before
            assert f"resolution = ({target[0]}, {target[1]})" in (
                renderer.added_session_usda[-1]
            )

        settings = Settings()
        renderer = _OpenUsdSessionAcceptanceRenderer(stage)
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
            viewport_id="a8-t06-openusd-session",
        )
        vp._image = SimpleNamespace(
            visible=True,
            computed_width=1280,
            computed_height=720,
        )
        vp._resolution_value_label = _FakeLabel()

        try:
            assert vp._resolution_render_qa_window is None
            assert vp._resolution_catalog_qa_window is None
            assert vp._resolution_settings_schema_qa_window is None
            assert [
                contribution.label
                for contribution in vp._pre_tools_toolbar_hooks.iter_contributions()
            ] == ["Settings"]
            assert vp.toolbar_hooks.iter_contributions() == ()

            assert vp.render(1.0 / 60.0) is True
            assert vp._resolution_value_label.text == "1280×720"
            assert_layer_report((1280, 720))

            settings_menu = self._open_settings_menu(vp)
            assert settings_menu.title == "Settings"
            viewport_menu = settings_menu.submenus[0]
            render_menu = self._viewport_submenu(viewport_menu, "Render Resolution")
            assert render_menu.kwargs["hotkey_text"] == "Viewport"
            assert checked_labels(render_menu) == ["Viewport"]

            hd1080p = item_by_label(render_menu, "HD1080P")
            assert hd1080p.trigger() is True

            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1920, 1080)
            assert state.selected_label == "HD1080P"
            assert state.scale == 1.0
            assert state.effective_size == (1920, 1080)
            assert vp._last_resolution == (1920, 1080)
            assert getattr(vp._last_image_frame, "shape", None) == (1080, 1920, 4)
            assert vp._resolution_value_label.text == "1920×1080"
            assert_layer_report((1920, 1080))
            assert renderer.removed_session_handles == ["initial-session", "a8-t06-session-1"]

            latest_render_menu = self._open_render_resolution_menu(vp)
            latest_viewport_menu = self._latest_viewport_menu()
            latest_scale = self._viewport_item(latest_viewport_menu, "Render Scale")
            assert latest_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert checked_labels(latest_render_menu) == ["HD1080P"]
            assert latest_scale.kwargs["render_scale_current_label"] == "100%"

            scale_50_index = latest_scale.kwargs["render_scale_options"].index("50%")
            assert latest_scale.kwargs["render_scale_changed_fn"](scale_50_index) is True

            assert settings.get(viewport_resolution_scale_key(vp.viewport_id)) == 0.5
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1920, 1080)
            assert state.selected_label == "HD1080P"
            assert state.scale == 0.5
            assert state.effective_size == (960, 540)
            assert vp._last_resolution == (960, 540)
            assert getattr(vp._last_image_frame, "shape", None) == (540, 960, 4)
            assert vp._resolution_value_label.text == "960×540"
            assert_layer_report((960, 540))

            refreshed_render_menu = self._open_render_resolution_menu(vp)
            refreshed_viewport_menu = self._latest_viewport_menu()
            refreshed_scale = self._viewport_item(
                refreshed_viewport_menu,
                "Render Scale",
            )
            assert refreshed_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert checked_labels(refreshed_render_menu) == ["HD1080P"]
            assert refreshed_scale.kwargs["render_scale_current_label"] == "50%"

            assert stage.GetRootLayer().ExportToString() == root_before
            assert stage.GetRootLayer().GetPrimAtPath(_RENDER_PRODUCT_PATH) is None
            assert stage.GetSessionLayer().GetPrimAtPath(_RENDER_PRODUCT_PATH) is not None
            assert session_render_product_resolution() == (960, 540)
            assert len(renderer.added_session_usda) == 3
            assert "resolution = (960, 540)" in renderer.added_session_usda[-1]
            assert _LDR_VAR_PATH in renderer.added_session_usda[-1]
            assert vp._resolution_render_qa_window is None
            assert vp._resolution_catalog_qa_window is None
            assert vp._resolution_settings_schema_qa_window is None
        finally:
            vp.destroy()

    def test_open_menu_custom_row_add_remove_refreshes_without_duplicates(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
            write_viewport_instance_resolution,
        )

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            self._open_render_resolution_menu(vp)

            write_shared_custom_resolution_list(
                settings,
                [{"name": "Review", "width": 1500, "height": 1000}],
            )
            write_viewport_instance_resolution(settings, vp.viewport_id, [1500, 1000])

            latest_render_menu = self._latest_render_resolution_menu()
            labels = [item.label for item in latest_render_menu.items]
            assert labels.count("Review") == 1
            assert latest_render_menu.kwargs["hotkey_text"] == "Review"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Review"]

            write_shared_custom_resolution_list(settings, [])

            latest_render_menu = self._latest_render_resolution_menu()
            labels = [item.label for item in latest_render_menu.items]
            assert "Review" not in labels
            assert latest_render_menu.kwargs["hotkey_text"] == "Custom"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Custom"]
        finally:
            vp.destroy()

    def test_open_menu_companion_setting_change_refreshes_to_viewport(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_viewport_instance_resolution,
        )

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        try:
            write_viewport_instance_resolution(settings, vp.viewport_id, [1920, 1080])
            self._open_render_resolution_menu(vp)

            write_viewport_instance_resolution(settings, vp.viewport_id, [0, 0])

            latest_render_menu = self._latest_render_resolution_menu()
            assert latest_render_menu.kwargs["hotkey_text"] == "Viewport"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Viewport"]
            assert vp.get_resolution_state().selected_label == "Viewport"
            assert vp._last_resolution == (640, 360)
        finally:
            vp.destroy()

    def test_open_menu_refresh_fallback_invalidates_without_stale_surface(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_viewport_instance_resolution,
        )

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            settings_menu = self._open_settings_menu(vp)
            vp._pre_tools_toolbar_hooks._menu_anchors.pop(
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID,
                None,
            )

            write_viewport_instance_resolution(settings, vp.viewport_id, [1920, 1080])

            assert settings_menu.destroyed is True
            assert (
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
                not in vp._pre_tools_toolbar_hooks._menus
            )

            reopened_render_menu = self._open_render_resolution_menu(vp)
            assert reopened_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert [
                item.label
                for item in reopened_render_menu.items
                if item.kwargs.get("checked")
            ] == ["HD1080P"]
        finally:
            vp.destroy()

    def test_render_resolution_submenu_renders_default_rows_from_area2_order(
        self, fake_camera_menu
    ):
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)

            assert [
                item.label
                for item in render_resolution_menu.items
            ] == [
                "Viewport",
                "UHD",
                "1440P",
                "2K",
                "HD1080P",
                "HD720P",
                "Square",
                "Icon",
                "Custom",
            ]
            assert [
                item.kwargs.get("hotkey_text")
                for item in render_resolution_menu.items
            ] == [
                "[0,0]",
                "3840x2160  16:9",
                "2560x1440  16:9",
                "2048x1080  1.90:1",
                "1920x1080  16:9",
                "1280x720  16:9",
                "1024x1024  1:1",
                "512x512  1:1",
                "[-1,-1]",
            ]
            assert all(
                item.kwargs.get("checkable") is True
                for item in render_resolution_menu.items
            )
            assert [
                item.kwargs.get("checked")
                for item in render_resolution_menu.items
            ] == [True, False, False, False, False, False, False, False, False]
            assert not any(
                item.kwargs.get("delete_affordance")
                for item in render_resolution_menu.items
            )
        finally:
            vp.destroy()

    def test_render_resolution_submenu_custom_sentinel_is_selectable_radio_row(
        self, fake_camera_menu
    ):
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1921, 1080),
                selected_label="Custom",
            )
            render_resolution_menu = self._open_render_resolution_menu(vp)
            custom_items = [
                item for item in render_resolution_menu.items if item.label == "Custom"
            ]

            assert len(custom_items) == 1
            custom = custom_items[0]
            assert custom.kwargs.get("checkable") is True
            assert custom.kwargs.get("checked") is True
            assert custom.kwargs.get("hotkey_text") == "[-1,-1]"
            assert custom.kwargs.get("delete_affordance") is False
            assert [
                item.label
                for item in render_resolution_menu.items
                if item.kwargs.get("checked")
            ] == ["Custom"]
        finally:
            vp.destroy()

    def test_render_resolution_submenu_checks_area2_selected_row_once(
        self, fake_camera_menu
    ):
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1920, 1080),
                selected_label="HD1080P",
            )
            render_resolution_menu = self._open_render_resolution_menu(vp)
            checked_labels = [
                item.label
                for item in render_resolution_menu.items
                if item.kwargs.get("checked")
            ]

            assert checked_labels == ["HD1080P"]
            assert sum(
                1
                for item in render_resolution_menu.items
                if item.kwargs.get("checked")
            ) == 1
        finally:
            vp.destroy()

    def test_render_resolution_submenu_full_catalog_uses_area2_badges(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_catalog import BUILTIN_RESOLUTION_PRESETS
        from ovui_widgets.viewport.resolution_settings import SETTING_RESOLUTION_PRESETS

        full_setting = [
            value
            for row in BUILTIN_RESOLUTION_PRESETS
            for value in row.dimensions
        ]
        settings = Settings()
        settings.set(SETTING_RESOLUTION_PRESETS, full_setting)
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        vp._image = _VisibleViewportImage()
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            labels = [item.label for item in render_resolution_menu.items]
            details_by_label = {
                item.label: item.kwargs.get("hotkey_text")
                for item in render_resolution_menu.items
            }

            assert labels == [
                "Viewport",
                "UHD",
                "1440P",
                "2K",
                "HD1080P",
                "HD720P",
                "Square",
                "Icon",
                "SD",
                "Ultra Wide",
                "Super Ultra Wide",
                "5K Wide",
                "Custom",
            ]
            assert details_by_label["SD"] == "1280x960  4:3"
            assert details_by_label["Ultra Wide"] == "3440x1440  2.39:1"
            assert details_by_label["Super Ultra Wide"] == "3840x1440  2.67:1"
            assert details_by_label["5K Wide"] == (
                "5120x2880  16:9  Resolution unavailable: max 3840x2160"
            )
            assert details_by_label["Custom"] == "[-1,-1]"
            assert "21:9" not in details_by_label["Ultra Wide"]
            assert "32:9" not in details_by_label["Super Ultra Wide"]
        finally:
            vp.destroy()

    def test_render_resolution_submenu_saved_custom_rows_have_delete_affordance(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.menu import (
            SAVED_CUSTOM_DELETE_HOTKEY_MARKER,
            _lookup_menu_control_callback,
            _parse_saved_custom_delete_payload,
        )
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            labels = [item.label for item in render_resolution_menu.items]
            by_label = {item.label: item for item in render_resolution_menu.items}

            assert labels[-2:] == ["Custom", "Review"]
            assert by_label["Review"].kwargs.get("hotkey_text", "").startswith(
                SAVED_CUSTOM_DELETE_HOTKEY_MARKER
            )
            detail_text, payload_token = _parse_saved_custom_delete_payload(
                by_label["Review"].kwargs.get("hotkey_text")
            )
            assert detail_text == "1500x1000  1.50:1"
            assert by_label["Review"].kwargs.get("delete_affordance") is True
            assert by_label["Review"].kwargs.get("delete_tooltip") == "Delete Review"
            assert callable(by_label["Review"].kwargs.get("delete_handoff_fn"))
            row_token = by_label["Review"].kwargs.get("row_callback_token")
            assert row_token
            assert _lookup_menu_control_callback(row_token) is (
                by_label["Review"].kwargs.get("row_handoff_fn")
            )
            assert callable(by_label["Review"].kwargs.get("row_handoff_fn"))
            token = by_label["Review"].kwargs.get("delete_callback_token")
            assert payload_token == token
            assert _lookup_menu_control_callback(token) is (
                by_label["Review"].kwargs.get("delete_handoff_fn")
            )
            for label in [
                "Viewport",
                "UHD",
                "1440P",
                "2K",
                "HD1080P",
                "HD720P",
                "Square",
                "Icon",
                "Custom",
            ]:
                assert by_label[label].kwargs.get("delete_affordance") is False
                assert by_label[label].kwargs.get("delete_handoff_fn") is None
        finally:
            vp.destroy()

    def test_saved_custom_delete_handoff_invokes_owner_without_fake_delete(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_resolution_key,
            write_shared_custom_resolution_list,
        )

        calls = []
        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        vp.set_saved_custom_delete_handoff(
            lambda row: calls.append((row.label, row.dimensions)) or False
        )
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            by_label = {item.label: item for item in render_resolution_menu.items}

            assert by_label["Review"].kwargs["delete_handoff_fn"]() is False

            assert calls == [("Review", (1500, 1000))]
            assert [
                entry["name"] for entry in vp.get_resolution_settings().custom_list
            ] == ["Review"]
            assert by_label["Review"].kwargs.get("delete_affordance") is True
            assert render_resolution_menu.destroyed is False

            assert by_label["HD1080P"].trigger() is True
            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [
                1920,
                1080,
            ]
            assert vp.get_resolution_state().selected_label == "HD1080P"
            assert [
                entry["name"] for entry in vp.get_resolution_settings().custom_list
            ] == ["Review"]
        finally:
            vp.destroy()

    def test_saved_custom_delete_removes_exact_row_and_refreshes_menu(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [
                {"name": "Review", "width": 1500, "height": 1000},
                {"name": "Portrait", "width": 1080, "height": 1920},
            ],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            by_label = {item.label: item for item in render_resolution_menu.items}

            assert by_label["Review"].kwargs["delete_handoff_fn"]() is True

            assert vp.get_resolution_settings().custom_list == [
                {"name": "Portrait", "width": 1080, "height": 1920}
            ]
            latest_render_menu = self._open_render_resolution_menu(vp)
            latest_labels = [item.label for item in latest_render_menu.items]
            latest_delete_labels = [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("delete_affordance")
            ]
            assert "Review" not in latest_labels
            assert "Portrait" in latest_labels
            assert "Viewport" in latest_labels
            assert "HD1080P" in latest_labels
            assert "Custom" in latest_labels
            assert latest_delete_labels == ["Portrait"]
        finally:
            vp.destroy()

    def test_saved_custom_delete_ignores_builtins_sentinels_and_stale_targets(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_catalog import (
            BUILTIN_RESOLUTION_PRESETS,
            CUSTOM_RESOLUTION_SENTINEL,
            RESOLUTION_CATALOG_KIND_SAVED_CUSTOM,
            VIEWPORT_RESOLUTION_SENTINEL,
        )
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            assert vp._delete_saved_custom_resolution_row(
                VIEWPORT_RESOLUTION_SENTINEL
            ) is False
            assert vp._delete_saved_custom_resolution_row(
                BUILTIN_RESOLUTION_PRESETS[0]
            ) is False
            assert vp._delete_saved_custom_resolution_row(
                CUSTOM_RESOLUTION_SENTINEL
            ) is False
            assert vp._delete_saved_custom_resolution_row(
                SimpleNamespace(
                    kind=RESOLUTION_CATALOG_KIND_SAVED_CUSTOM,
                    label="Review",
                    dimensions=(1600, 900),
                )
            ) is False
            assert vp.get_resolution_settings().custom_list == [
                {"name": "Review", "width": 1500, "height": 1000}
            ]

            render_resolution_menu = self._open_render_resolution_menu(vp)
            review = [
                item for item in render_resolution_menu.items if item.label == "Review"
            ][0]
            delete_fn = review.kwargs["delete_handoff_fn"]
            assert delete_fn() is True
            assert vp.get_resolution_settings().custom_list == []

            assert delete_fn() is False
            assert vp.get_resolution_settings().custom_list == []
        finally:
            vp.destroy()

    def test_saved_custom_delete_selected_non_preset_recovers_to_custom(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            review = [
                item for item in render_resolution_menu.items if item.label == "Review"
            ][0]

            assert review.trigger() is True

            selected_menu = self._open_render_resolution_menu(vp)
            assert selected_menu.kwargs["hotkey_text"] == "Review"
            assert [
                item.label
                for item in selected_menu.items
                if item.kwargs.get("checked")
            ] == ["Review"]
            selected_review = [
                item for item in selected_menu.items if item.label == "Review"
            ][0]

            assert selected_review.kwargs["delete_handoff_fn"]() is True

            state = vp.get_resolution_state()
            assert state.requested_size == (1500, 1000)
            assert state.selected_label == "Custom"
            latest_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0].submenus[0]
            latest_labels = [item.label for item in latest_menu.items]
            checked_labels = [
                item.label for item in latest_menu.items if item.kwargs.get("checked")
            ]
            assert latest_menu.kwargs["hotkey_text"] == "Custom"
            assert checked_labels == ["Custom"]
            assert "Review" not in latest_labels
        finally:
            vp.destroy()

    def test_saved_custom_delete_selected_preset_duplicate_recovers_to_builtin(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_resolution_key,
            write_shared_custom_resolution_list,
            write_viewport_instance_resolution,
        )
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "HD Copy", "width": 1920, "height": 1080}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            write_viewport_instance_resolution(
                settings,
                vp.viewport_id,
                [1920, 1080],
            )
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1920, 1080),
                selected_label="HD Copy",
            )
            render_resolution_menu = self._open_render_resolution_menu(vp)
            hd_copy = [
                item for item in render_resolution_menu.items if item.label == "HD Copy"
            ][0]

            assert hd_copy.kwargs["delete_handoff_fn"]() is True

            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [
                1920,
                1080,
            ]
            state = vp.get_resolution_state()
            assert state.requested_size == (1920, 1080)
            assert state.selected_label == "HD1080P"
            latest_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0].submenus[0]
            latest_labels = [item.label for item in latest_menu.items]
            checked_labels = [
                item.label for item in latest_menu.items if item.kwargs.get("checked")
            ]
            assert latest_menu.kwargs["hotkey_text"] == "HD1080P"
            assert checked_labels == ["HD1080P"]
            assert "HD Copy" not in latest_labels
        finally:
            vp.destroy()

    def test_saved_custom_delete_selected_without_fixed_state_recovers_to_viewport(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
            write_viewport_instance_resolution,
        )
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_VIEWPORT

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            write_viewport_instance_resolution(settings, vp.viewport_id, [0, 0])
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_VIEWPORT,
                requested_size=(0, 0),
                selected_label="Review",
            )
            render_resolution_menu = self._open_render_resolution_menu(vp)
            review = [
                item for item in render_resolution_menu.items if item.label == "Review"
            ][0]

            assert review.kwargs["delete_handoff_fn"]() is True

            state = vp.get_resolution_state()
            assert state.requested_size == (0, 0)
            assert state.selected_label == "Viewport"
            latest_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1].submenus[0].submenus[0]
            latest_labels = [item.label for item in latest_menu.items]
            checked_labels = [
                item.label for item in latest_menu.items if item.kwargs.get("checked")
            ]
            assert latest_menu.kwargs["hotkey_text"] == "Viewport"
            assert checked_labels == ["Viewport"]
            assert "Review" not in latest_labels
        finally:
            vp.destroy()

    def test_render_resolution_submenu_saved_custom_selection_checks_saved_row(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            write_shared_custom_resolution_list,
        )
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1500, 1000),
                selected_label="Review",
            )
            render_resolution_menu = self._open_render_resolution_menu(vp)

            assert [
                item.label
                for item in render_resolution_menu.items
                if item.kwargs.get("checked")
            ] == ["Review"]
        finally:
            vp.destroy()

    def test_render_resolution_row_click_writes_settings_and_accepts_builtin_state(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            hd1080p = [
                item for item in render_resolution_menu.items if item.label == "HD1080P"
            ][0]

            assert hd1080p.trigger() is True

            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [
                1920,
                1080,
            ]
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1920, 1080)
            assert state.selected_label == "HD1080P"
            assert state.effective_size == (1920, 1080)
            assert vp._last_resolution == (1920, 1080)

            latest_render_menu = self._open_render_resolution_menu(vp)
            assert latest_render_menu.kwargs["hotkey_text"] == "HD1080P"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["HD1080P"]
        finally:
            vp.destroy()

    def test_render_resolution_row_click_returns_to_viewport_state(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        settings = Settings()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=renderer,
        )
        vp._image = _VisibleViewportImage()
        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1920, 1080),
                selected_label="HD1080P",
            )
            render_resolution_menu = self._open_render_resolution_menu(vp)
            viewport = [
                item for item in render_resolution_menu.items if item.label == "Viewport"
            ][0]

            assert viewport.trigger() is True

            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [0, 0]
            state = vp.get_resolution_state()
            assert state.is_viewport_mode is True
            assert state.requested_size == (0, 0)
            assert state.selected_label == "Viewport"
            assert state.effective_size == (640, 360)
            assert vp._last_resolution == (640, 360)
            latest_render_menu = self._open_render_resolution_menu(vp)
            assert latest_render_menu.kwargs["hotkey_text"] == "Viewport"
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Viewport"]
        finally:
            vp.destroy()

    def test_render_resolution_row_click_accepts_saved_custom_from_area2(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            viewport_resolution_key,
            write_shared_custom_resolution_list,
        )

        settings = Settings()
        write_shared_custom_resolution_list(
            settings,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            review = [
                item for item in render_resolution_menu.items if item.label == "Review"
            ][0]

            assert review.trigger() is True

            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [
                1500,
                1000,
            ]
            state = vp.get_resolution_state()
            assert state.is_fixed_mode is True
            assert state.requested_size == (1500, 1000)
            assert state.selected_label == "Review"
            latest_render_menu = self._open_render_resolution_menu(vp)
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Review"]
        finally:
            vp.destroy()

    def test_render_resolution_custom_sentinel_reuses_existing_unsaved_size(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1921, 1080),
                selected_label="Custom",
            )
            render_resolution_menu = self._open_render_resolution_menu(vp)
            custom = [
                item for item in render_resolution_menu.items if item.label == "Custom"
            ][0]

            assert custom.trigger() is True

            assert settings.get(viewport_resolution_key(vp.viewport_id)) == [
                1921,
                1080,
            ]
            assert vp.get_resolution_state().requested_size == (1921, 1080)
            assert vp.get_resolution_state().selected_label == "Custom"
        finally:
            vp.destroy()

    def test_render_resolution_custom_sentinel_without_unsaved_size_is_noop(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import viewport_resolution_key

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            custom = [
                item for item in render_resolution_menu.items if item.label == "Custom"
            ][0]

            assert custom.trigger() is False

            assert settings.get(viewport_resolution_key(vp.viewport_id)) is None
            assert vp.get_resolution_state().is_viewport_mode is True
            assert vp.get_resolution_state().requested_size == (0, 0)
            assert vp.get_resolution_state().selected_label == "Viewport"
        finally:
            vp.destroy()

    def test_render_resolution_duplicate_click_is_idempotent(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings

        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        changes = []
        handle = vp.subscribe_resolution_state(
            lambda old, new: changes.append((old, new))
        )
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            viewport = [
                item for item in render_resolution_menu.items if item.label == "Viewport"
            ][0]

            assert viewport.trigger() is True

            assert changes == []
            latest_menu = [
                menu for menu in fake_camera_menu.instances if menu.title == "Settings"
            ][-1]
            latest_render_menu = latest_menu.submenus[0].submenus[0]
            assert [
                item.label
                for item in latest_render_menu.items
                if item.kwargs.get("checked")
            ] == ["Viewport"]
        finally:
            handle.unsubscribe()
            vp.destroy()

    def test_render_resolution_failed_write_does_not_move_checkmark_optimistically(
        self, fake_camera_menu
    ):
        class _FailingSettings:
            def get(self, _key, default=None):
                return default

            def set(self, _key, _value):
                raise RuntimeError("write failed")

        vp = ViewportWidget(
            services=SimpleNamespace(settings=_FailingSettings(), selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            hd1080p = [
                item for item in render_resolution_menu.items if item.label == "HD1080P"
            ][0]

            assert hd1080p.trigger() is False

            assert isinstance(vp._last_render_resolution_apply_error, RuntimeError)
            assert vp.get_resolution_state().is_viewport_mode is True
            assert vp.get_resolution_state().selected_label == "Viewport"
            assert [
                item.label
                for item in render_resolution_menu.items
                if item.kwargs.get("checked")
            ] == ["Viewport"]
        finally:
            vp.destroy()

    def test_render_resolution_submenu_malformed_saved_custom_entries_are_absent(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import SETTING_CUSTOM_RESOLUTION_LIST

        warning = "Some saved custom resolutions were ignored."
        settings = Settings()
        settings.set(
            SETTING_CUSTOM_RESOLUTION_LIST,
            [
                {"name": "Review", "width": 1500, "height": 1000},
                {"name": "", "width": 1200, "height": 800},
                {"name": "Bad", "width": 0, "height": 100},
                {"name": "Missing Height", "width": 1200},
                {"name": "Text Dims", "width": "1200", "height": 800},
                {"name": "Bool Dims", "width": True, "height": 800},
                ["Unsupported", 1200, 800],
                {"name": "Review Duplicate", "width": 1500, "height": 1000},
                {"name": "Review", "width": 1600, "height": 900},
            ],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            render_resolution_menu = self._open_render_resolution_menu(vp)
            labels = [item.label for item in render_resolution_menu.items]
            delete_labels = [
                item.label
                for item in render_resolution_menu.items
                if item.kwargs.get("delete_affordance")
            ]

            assert render_resolution_menu.kwargs.get("tooltip") == warning
            assert "Viewport" in labels
            assert "HD1080P" in labels
            assert "Custom" in labels
            assert labels.count("Review") == 1
            assert "Bad" not in labels
            assert "Missing Height" not in labels
            assert "Text Dims" not in labels
            assert "Bool Dims" not in labels
            assert "Unsupported" not in labels
            assert "Review Duplicate" not in labels
            assert "" not in labels
            assert warning not in labels
            assert delete_labels == ["Review"]

            review = [item for item in render_resolution_menu.items if item.label == "Review"][
                0
            ]
            assert "1500" in review.kwargs["hotkey_text"]
            assert "1000" in review.kwargs["hotkey_text"]
            assert "1.50:1" in review.kwargs["hotkey_text"]
            assert review.trigger() is True
            assert vp.get_resolution_state().selected_label == "Review"
            assert vp.get_resolution_state().requested_size == (1500, 1000)
            assert "Review Duplicate" != vp.get_resolution_state().selected_label

            reopened_menu = self._open_render_resolution_menu(vp)
            reopened_labels = [item.label for item in reopened_menu.items]
            assert reopened_labels.count("Review") == 1
            assert "Bad" not in reopened_labels
            assert "Review Duplicate" not in reopened_labels
            assert reopened_menu.kwargs.get("tooltip") == warning
        finally:
            vp.destroy()

    def test_corrupt_shared_custom_list_refresh_suppresses_invalid_rows(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import SETTING_CUSTOM_RESOLUTION_LIST

        warning = "Some saved custom resolutions were ignored."
        settings = Settings()
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )
        try:
            self._open_render_resolution_menu(vp)

            settings.set(
                SETTING_CUSTOM_RESOLUTION_LIST,
                [
                    {"name": "Visible", "width": 1400, "height": 900},
                    {"name": "Invalid Zero", "width": 0, "height": 900},
                    {"name": "Visible Duplicate", "width": 1400, "height": 900},
                    {"name": "Visible", "width": 1500, "height": 1000},
                    {"name": "", "width": 1600, "height": 900},
                ],
            )
            latest_menu = self._latest_render_resolution_menu()
            labels = [item.label for item in latest_menu.items]
            assert latest_menu.kwargs.get("tooltip") == warning
            assert labels.count("Visible") == 1
            assert "Invalid Zero" not in labels
            assert "Visible Duplicate" not in labels
            assert "" not in labels
            assert "Viewport" in labels
            assert "Custom" in labels

            settings.set(
                SETTING_CUSTOM_RESOLUTION_LIST,
                [{"name": "Clean", "width": 1600, "height": 900}],
            )
            latest_menu = self._latest_render_resolution_menu()
            labels = [item.label for item in latest_menu.items]
            assert latest_menu.kwargs.get("tooltip") is None
            assert "Clean" in labels
            assert "Visible" not in labels
            assert "Invalid Zero" not in labels

            settings.set(
                SETTING_CUSTOM_RESOLUTION_LIST,
                [
                    {"name": "", "width": 1200, "height": 800},
                    {"name": "Missing Width", "height": 800},
                    ["Unsupported", 1200, 800],
                ],
            )
            latest_menu = self._latest_render_resolution_menu()
            labels = [item.label for item in latest_menu.items]
            assert latest_menu.kwargs.get("tooltip") == warning
            assert "Missing Width" not in labels
            assert "Unsupported" not in labels
            assert "Clean" not in labels
            assert "Viewport" in labels
            assert "HD1080P" in labels
            assert "Custom" in labels
        finally:
            vp.destroy()

    def test_viewport_settings_submenu_current_label_uses_area2_selection_values(
        self, fake_camera_menu
    ):
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.resolution_settings import (
            SETTING_CUSTOM_RESOLUTION_LIST,
        )
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        class _Anchor:
            screen_position_x = 31
            screen_position_y = 47
            computed_height = 20

        settings = Settings()
        settings.set(
            SETTING_CUSTOM_RESOLUTION_LIST,
            [{"name": "Review", "width": 1500, "height": 1000}],
        )
        vp = ViewportWidget(
            services=SimpleNamespace(settings=settings, selection_bus=None),
            renderer=MockRendererAdapter(),
        )

        def current_label() -> str:
            contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
            assert isinstance(contribution, ViewportToolbarMenu)
            vp._pre_tools_toolbar_hooks._show_menu(contribution, _Anchor())
            settings_menu = [
                menu
                for menu in fake_camera_menu.instances
                if menu.title == "Settings"
            ][-1]
            return settings_menu.submenus[0].submenus[0].kwargs["hotkey_text"]

        try:
            assert current_label() == "Viewport"

            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1920, 1080),
                selected_label="HD1080P",
            )
            assert current_label() == "HD1080P"

            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1921, 1080),
                selected_label="Custom",
            )
            assert current_label() == "Custom"

            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1500, 1000),
                selected_label="Custom",
            )
            assert current_label() == "Review"
        finally:
            vp.destroy()

    def test_viewport_settings_submenu_reopen_refreshes_current_label(
        self, fake_camera_menu
    ):
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        class _Anchor:
            screen_position_x = 4
            screen_position_y = 8
            computed_height = 12

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())

        def open_label() -> str:
            contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
            assert isinstance(contribution, ViewportToolbarMenu)
            vp._pre_tools_toolbar_hooks._show_menu(contribution, _Anchor())
            settings_menu = [
                menu
                for menu in fake_camera_menu.instances
                if menu.title == "Settings"
            ][-1]
            return settings_menu.submenus[0].submenus[0].kwargs["hotkey_text"]

        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1920, 1080),
                selected_label="HD1080P",
            )
            assert open_label() == "HD1080P"
            hd_menu = [
                menu
                for menu in fake_camera_menu.instances
                if menu.title == "Settings"
            ][-1]

            vp.set_resolution_state(
                mode="viewport",
                requested_size=(0, 0),
                selected_label="Viewport",
            )
            assert open_label() == "Viewport"
            assert hd_menu.destroyed is True
        finally:
            vp.destroy()

    def test_viewport_settings_submenu_current_label_is_menu_only(
        self, fake_camera_menu
    ):
        from ovui_widgets.viewport.resolution_state import RESOLUTION_MODE_FIXED
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        class _Anchor:
            screen_position_x = 31
            screen_position_y = 47
            computed_height = 20

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            vp.set_resolution_state(
                mode=RESOLUTION_MODE_FIXED,
                requested_size=(1920, 1080),
                selected_label="HD1080P",
            )
            contribution = vp._pre_tools_toolbar_hooks.iter_contributions()[0]
            assert isinstance(contribution, ViewportToolbarMenu)

            assert contribution.label == "Settings"
            assert contribution.tooltip == "Settings"
            assert contribution.widget_name == "viewport_toolbar_settings"
            assert "HD1080P" not in contribution.label
            assert "HD1080P" not in contribution.tooltip

            vp._pre_tools_toolbar_hooks._show_menu(contribution, _Anchor())
            settings_menu = fake_camera_menu.instances[0]
            render_resolution_menu = settings_menu.submenus[0].submenus[0]
            assert render_resolution_menu.kwargs["hotkey_text"] == "HD1080P"
        finally:
            vp.destroy()

    def test_resolution_host_attachment_uses_stable_identity_and_owner_context(self):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarAction

        contexts = []
        on_add_owners = []
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            handle = vp.attach_resolution_toolbar_host(
                lambda context: (
                    contexts.append(context)
                    or ViewportToolbarAction(
                        id=context.attachment_id,
                        label="QA",
                        widget_name="viewport_toolbar_test_resolution_host",
                        on_add=lambda owner: on_add_owners.append(owner),
                    )
                ),
                replace=True,
            )

            assert handle.id == viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
            assert handle.attachment_id == viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
            assert handle.viewport_id == vp.viewport_id
            assert handle.active is True
            assert contexts[0].attachment_id == viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
            assert contexts[0].owner is vp
            assert contexts[0].viewport is vp
            assert contexts[0].viewport_id == vp.viewport_id
            assert on_add_owners == [vp]
            assert [entry.id for entry in vp._pre_tools_toolbar_hooks.iter_contributions()] == [
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
            ]
        finally:
            vp.destroy()

    def test_resolution_host_rejects_duplicate_attachment_without_duplicate_control(self):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarAction

        build_calls = []
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            first = vp.attach_resolution_toolbar_host(
                lambda context: (
                    build_calls.append("first")
                    or ViewportToolbarAction(
                        id=context.attachment_id,
                        label="First",
                        widget_name="viewport_toolbar_resolution_first",
                    )
                ),
                replace=True,
            )
            second = vp.attach_resolution_toolbar_host(
                lambda context: (
                    build_calls.append("second")
                    or ViewportToolbarAction(
                        id=context.attachment_id,
                        label="Second",
                        widget_name="viewport_toolbar_resolution_second",
                    )
                )
            )
            contributions = vp._pre_tools_toolbar_hooks.iter_contributions()

            assert second is first
            assert build_calls == ["first"]
            assert [entry.id for entry in contributions] == [
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
            ]
            assert [entry.label for entry in contributions] == ["First"]
        finally:
            vp.destroy()

    def test_resolution_host_replacement_keeps_one_visible_attachment(self):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarAction

        removed = []
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            first = vp.attach_resolution_toolbar_host(
                lambda context: ViewportToolbarAction(
                    id=context.attachment_id,
                    label="First",
                    widget_name="viewport_toolbar_resolution_first",
                    on_remove=lambda owner: removed.append(("first", owner)),
                ),
                replace=True,
            )
            replacement = vp.attach_resolution_toolbar_host(
                lambda context: ViewportToolbarAction(
                    id=context.attachment_id,
                    label="Second",
                    widget_name="viewport_toolbar_resolution_second",
                ),
                replace=True,
            )
            contributions = vp._pre_tools_toolbar_hooks.iter_contributions()

            assert first.active is False
            assert replacement.active is True
            assert replacement is not first
            assert removed == [("first", vp)]
            assert [entry.id for entry in contributions] == [
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
            ]
            assert [entry.label for entry in contributions] == ["Second"]
        finally:
            vp.destroy()

    def test_resolution_host_rejects_wrong_attachment_identity(self):
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarAction

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        try:
            with pytest.raises(ValueError):
                vp.attach_resolution_toolbar_host(
                    lambda _context: ViewportToolbarAction(
                        id="wrong.identity",
                        label="Wrong",
                    ),
                    replace=True,
                )
            assert [
                entry.widget_name
                for entry in vp._pre_tools_toolbar_hooks.iter_contributions()
            ] == ["viewport_toolbar_settings"]
        finally:
            vp.destroy()

    def test_resolution_host_isolated_per_viewport_identity(self):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarAction

        contexts = []
        first = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            viewport_id="review",
        )
        second = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            viewport_id="review",
        )
        try:
            first_handle = first.attach_resolution_toolbar_host(
                lambda context: (
                    contexts.append(context)
                    or ViewportToolbarAction(
                        id=context.attachment_id,
                        label="First",
                        widget_name="viewport_toolbar_resolution_first",
                    )
                ),
                replace=True,
            )
            second_handle = second.attach_resolution_toolbar_host(
                lambda context: (
                    contexts.append(context)
                    or ViewportToolbarAction(
                        id=context.attachment_id,
                        label="Second",
                        widget_name="viewport_toolbar_resolution_second",
                    )
                ),
                replace=True,
            )

            assert first.viewport_id == "review"
            assert second.viewport_id == "review_2"
            assert first_handle.viewport_id == first.viewport_id
            assert second_handle.viewport_id == second.viewport_id
            assert [context.owner for context in contexts] == [first, second]
            assert [context.viewport_id for context in contexts] == [
                first.viewport_id,
                second.viewport_id,
            ]
            assert [entry.id for entry in first._pre_tools_toolbar_hooks.iter_contributions()] == [
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
            ]
            assert [entry.id for entry in second._pre_tools_toolbar_hooks.iter_contributions()] == [
                viewport_mod.VIEWPORT_RESOLUTION_ATTACHMENT_ID
            ]

            assert first_handle.remove() is True
            assert first._pre_tools_toolbar_hooks.iter_contributions() == ()
            assert [entry.label for entry in second._pre_tools_toolbar_hooks.iter_contributions()] == [
                "Second"
            ]
            assert second_handle.active is True
        finally:
            second.destroy()
            first.destroy()

    def test_resolution_host_attachment_is_cleaned_up_on_destroy(self):
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarAction

        removed = []
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        handle = vp.attach_resolution_toolbar_host(
            lambda context: ViewportToolbarAction(
                id=context.attachment_id,
                label="QA",
                widget_name="viewport_toolbar_resolution_destroy_cleanup",
                on_remove=lambda owner: removed.append(owner),
            ),
            replace=True,
        )

        vp.destroy()

        assert handle.active is False
        assert handle.remove() is False
        assert removed == [vp]
        assert vp._pre_tools_toolbar_hooks.iter_contributions() == ()

    def test_toolbar_buttons_are_icon_buttons(self, monkeypatch):
        import ovui_widgets.viewport.viewport_widget as viewport_mod

        seen_buttons = []
        seen_icons = []
        original_invisible_button = viewport_mod.ui.InvisibleButton
        original_image = viewport_mod.ui.ImageWithProvider

        def spy_invisible_button(*args, **kwargs):
            if str(kwargs.get("identifier", "")).startswith("viewport_toolbar_"):
                seen_buttons.append(kwargs)
            return original_invisible_button(*args, **kwargs)

        def spy_image(*args, **kwargs):
            if kwargs.get("style_type_name_override") == "Viewport.Toolbar.Icon":
                seen_icons.append((args, kwargs))
            return original_image(*args, **kwargs)

        monkeypatch.setattr(viewport_mod.ui, "InvisibleButton", spy_invisible_button)
        monkeypatch.setattr(viewport_mod.ui, "ImageWithProvider", spy_image)
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._build_ui()
        assert len(seen_buttons) == 5
        assert len(seen_icons) == 5
        assert seen_buttons[0].get("identifier") == "viewport_toolbar_settings"
        assert seen_buttons[0].get("tooltip") == "Settings"
        assert "viewport_toolbar_render_product" not in {
            kwargs.get("identifier") for kwargs in seen_buttons
        }
        assert all(kwargs.get("width") == vp.TOOLBAR_BUTTON_SIZE for kwargs in seen_buttons)
        assert all(kwargs.get("height") == vp.TOOLBAR_BUTTON_SIZE for kwargs in seen_buttons)
        assert all(kwargs.get("tooltip") for kwargs in seen_buttons)
        assert all(kwargs.get("enabled") is False for _, kwargs in seen_icons)
        assert all(kwargs.get("opaque_for_mouse_events") is False for _, kwargs in seen_icons)
        vp.destroy()

    def test_toolbar_hook_menu_can_replace_target_picker_later(self, monkeypatch):
        import ovui_widgets.viewport.viewport_widget as viewport_mod
        from ovui_widgets.viewport.toolbar_hooks import ViewportToolbarMenu

        seen_buttons = []
        seen_hook_buttons = []
        original_invisible_button = viewport_mod.ui.InvisibleButton
        original_button = viewport_mod.ui.Button

        def spy_invisible_button(*args, **kwargs):
            if str(kwargs.get("identifier", "")).startswith("viewport_toolbar_"):
                seen_buttons.append(kwargs)
            return original_invisible_button(*args, **kwargs)

        def spy_button(*args, **kwargs):
            if str(kwargs.get("identifier", "")).startswith("viewport_toolbar_"):
                seen_hook_buttons.append(kwargs)
            return original_button(*args, **kwargs)

        monkeypatch.setattr(viewport_mod.ui, "InvisibleButton", spy_invisible_button)
        monkeypatch.setattr(viewport_mod.ui, "Button", spy_button)
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp.toolbar_hooks.add(
            ViewportToolbarMenu(
                id="render_target.picker",
                label="T",
                tooltip="Render Target",
            )
        )
        vp._build_ui()

        assert "viewport_toolbar_render_product" not in {
            kwargs.get("identifier") for kwargs in seen_buttons
        }
        assert [kwargs.get("identifier") for kwargs in seen_hook_buttons] == [
            "viewport_toolbar_menu_render_target_picker",
        ]
        vp.destroy()

    def test_toolbar_button_stacks_clip_scene_view_clicks(self, monkeypatch):
        import ovui_widgets.viewport.viewport_widget as viewport_mod

        seen_button_stacks = []
        original_zstack = viewport_mod.ui.ZStack

        def spy_zstack(*args, **kwargs):
            if (
                kwargs.get("width") == ViewportWidget.TOOLBAR_BUTTON_SIZE
                and kwargs.get("height") == ViewportWidget.TOOLBAR_BUTTON_SIZE
            ):
                seen_button_stacks.append(kwargs)
            return original_zstack(*args, **kwargs)

        monkeypatch.setattr(viewport_mod.ui, "ZStack", spy_zstack)
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._build_ui()
        assert len(seen_button_stacks) == 5
        assert all(
            kwargs.get("content_clipping") is True for kwargs in seen_button_stacks
        )
        assert vp._scene_view.child_windows_input is False
        vp.destroy()

    def test_toolbar_click_switches_registry_and_manipulator(self):
        from ovui_widgets.viewport.transform_manipulator import TOOL_ROTATE, TOOL_TRANSLATE

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._build_ui()
        assert vp._tool_registry.active_tool == TOOL_TRANSLATE
        vp._on_toolbar_tool_clicked(TOOL_ROTATE)
        assert vp._tool_registry.active_tool == TOOL_ROTATE
        assert vp._transform_manipulator.tool == TOOL_ROTATE
        assert vp._toolbar_button_backgrounds[TOOL_ROTATE].name == "active"
        assert vp._toolbar_button_backgrounds[TOOL_TRANSLATE].name == ""
        vp.destroy()

    def test_toolbar_clicking_active_tool_restores_checked_state(self):
        from ovui_widgets.viewport.transform_manipulator import TOOL_TRANSLATE

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._build_ui()
        vp._toolbar_button_backgrounds[TOOL_TRANSLATE].name = ""
        vp._on_toolbar_tool_clicked(TOOL_TRANSLATE)
        assert vp._toolbar_button_backgrounds[TOOL_TRANSLATE].name == "active"
        assert vp._tool_registry.active_tool == TOOL_TRANSLATE
        vp.destroy()

    def test_toolbar_state_tracks_settings_changes_from_menu_or_hotkey(self):
        from types import SimpleNamespace

        from ovui_widgets.common.selection import SelectionBus
        from ovui_widgets.common.settings import Settings
        from ovui_widgets.viewport.manipulator_registry import ACTIVE_TOOL_SETTING
        from ovui_widgets.viewport.transform_manipulator import TOOL_ROTATE, TOOL_SCALE

        app = SimpleNamespace(settings=Settings(), selection_bus=SelectionBus())
        vp = ViewportWidget(services=app, renderer=MockRendererAdapter())
        vp._build_ui()
        app.settings.set(ACTIVE_TOOL_SETTING, TOOL_SCALE)
        assert vp._tool_registry.active_tool == TOOL_SCALE
        assert vp._transform_manipulator.tool == TOOL_SCALE
        assert vp._toolbar_button_backgrounds[TOOL_SCALE].name == "active"
        assert vp._toolbar_button_backgrounds[TOOL_ROTATE].name == ""
        assert vp._toolbar_button_backgrounds["camera"].name == ""
        vp.destroy()

    def test_camera_menu_uses_shared_flat_menu_and_lists_stage_cameras(
        self, fake_camera_menu
    ):
        choices = (
            StageChoice("/World/MainCamera", "Main Camera"),
            StageChoice("/World/Shot/CameraB", "Shot Camera"),
        )
        adapter = _FakeCameraStageAdapter(choices=choices)
        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )
        menu = vp._show_camera_menu_at(17, 29)
        assert isinstance(menu, fake_camera_menu)
        assert menu.title == "Camera"
        assert "delegate" in menu.kwargs
        assert menu.shown_at == (17.0, 29.0)
        assert [item.label for item in menu.items] == [
            "Main Camera",
            "Shot Camera",
        ]
        assert all(item.kwargs.get("checkable") is True for item in menu.items)
        assert all(item.kwargs.get("checked") is False for item in menu.items)
        assert all(callable(item.kwargs.get("triggered_fn")) for item in menu.items)
        vp.destroy()

    def test_camera_menu_empty_state_is_disabled_item(self, fake_camera_menu):
        adapter = _FakeCameraStageAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )
        menu = vp._show_camera_menu_at(0, 0)
        assert [item.label for item in menu.items] == ["(no cameras)"]
        assert menu.items[0].kwargs.get("enabled") is False
        assert "triggered_fn" not in menu.items[0].kwargs
        vp.destroy()

    def test_camera_menu_selection_applies_pose_and_tracks_active_path(
        self, fake_camera_menu
    ):
        pose = BoundCameraPose(
            eye=(1.0, 2.0, 3.0),
            target=(4.0, 5.0, 6.0),
            up_axis="Z",
            fov_degrees=60.0,
            prim_path="/World/MainCamera",
        )
        adapter = _FakeCameraStageAdapter(
            choices=(StageChoice("/World/MainCamera", "Main Camera"),),
            poses={"/World/MainCamera": pose},
        )

        class _CameraBindingRenderer(MockRendererAdapter):
            def __init__(self):
                super().__init__()
                self.active_camera_path = None

            def get_active_camera_path(self):
                return self.active_camera_path

            def set_active_camera_path(self, path):
                self.active_camera_path = path
                return True

        renderer = _CameraBindingRenderer()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            stage_adapter_provider=lambda: adapter,
        )
        menu = vp._show_camera_menu_at(0, 0)
        assert menu.items[0].trigger() is True
        assert adapter.read_paths == ["/World/MainCamera"]
        assert vp._active_camera_path == "/World/MainCamera"
        assert renderer.get_active_camera_path() == "/World/MainCamera"
        assert vp._camera.state.target == pytest.approx([4.0, 5.0, 6.0])
        assert vp._camera.up_axis == pytest.approx([0.0, 0.0, 1.0])
        assert vp._camera_model.get_as_floats("up_axis") == pytest.approx(
            [0.0, 0.0, 1.0]
        )
        assert vp._camera.fov_degrees == pytest.approx(60.0)

        menu = vp._show_camera_menu_at(0, 0)
        assert menu.items[0].label == "Main Camera"
        assert menu.items[0].kwargs.get("checked") is True
        vp.destroy()

    def test_stage_up_axis_and_restored_camera_sync_manipulator_model(self):
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())

        assert vp.apply_stage_up_axis("Z") is True
        assert vp._camera.up_axis == pytest.approx([0.0, 0.0, 1.0])
        assert vp._camera_model.get_as_floats("up_axis") == pytest.approx(
            [0.0, 0.0, 1.0]
        )

        snapshot = vp._camera_state_snapshot()
        assert vp.apply_stage_up_axis("Y") is True
        vp._restore_camera_state_snapshot(snapshot)

        assert vp._camera.up_axis == pytest.approx([0.0, 0.0, 1.0])
        assert vp._camera_model.get_as_floats("up_axis") == pytest.approx(
            [0.0, 0.0, 1.0]
        )
        vp.destroy()

    def test_public_camera_selection_seam_applies_pose_and_tracks_active_path(self):
        pose = BoundCameraPose(
            eye=(1.0, 2.0, 3.0),
            target=(4.0, 5.0, 6.0),
            up_axis="Z",
            fov_degrees=60.0,
            prim_path="/World/MainCamera",
        )
        adapter = _FakeCameraStageAdapter(
            poses={"/World/MainCamera": pose},
        )
        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )

        assert vp.select_camera_path("/World/MainCamera") is True

        assert adapter.read_paths == ["/World/MainCamera"]
        assert vp._active_camera_path == "/World/MainCamera"
        assert vp._camera.state.target == pytest.approx([4.0, 5.0, 6.0])
        vp.destroy()

    def test_camera_selection_with_missing_pose_is_noop(self, fake_camera_menu):
        adapter = _FakeCameraStageAdapter(
            choices=(StageChoice("/World/MainCamera", "Main Camera"),),
        )
        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )
        before_target = list(vp._camera.state.target)
        assert vp._select_camera_path("/World/MainCamera") is False
        assert adapter.read_paths == ["/World/MainCamera"]
        assert vp._active_camera_path is None
        assert vp._camera.state.target == before_target
        vp.destroy()

    def test_attach_stage_clears_active_camera_menu_selection(self):
        from unittest.mock import MagicMock

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._active_camera_path = "/World/MainCamera"
        vp.attach_stage(
            transform_adapter=MagicMock(),
            stage_adapter=MagicMock(),
            undo_manager=MagicMock(),
        )
        assert vp._active_camera_path is None
        vp.destroy()

    def test_attach_stage_resets_renderer_active_camera_path(self):
        """Loading a fresh stage clears any previous user camera binding.

        Without this reset, opening stage B would keep the renderer
        pinned to whatever camera prim was selected on stage A — a
        path that no longer exists in stage B — leaving the renderer
        in a wedged state with no live camera matrices.
        """
        from unittest.mock import MagicMock

        class _CameraBindingRenderer(MockRendererAdapter):
            def __init__(self):
                super().__init__()
                self.set_paths = []

            def set_active_camera_path(self, path):
                self.set_paths.append(path)
                return True

        renderer = _CameraBindingRenderer()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp.attach_stage(
            transform_adapter=MagicMock(),
            stage_adapter=MagicMock(),
            undo_manager=MagicMock(),
        )
        assert renderer.set_paths == [None]
        vp.destroy()

    def test_attach_stage_provides_current_renderer_to_transform_model(self):
        from unittest.mock import MagicMock

        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._transform_model.set_renderer(None)

        vp.attach_stage(
            transform_adapter=MagicMock(),
            stage_adapter=MagicMock(),
            undo_manager=MagicMock(),
        )

        assert vp._transform_model.renderer_adapter is renderer
        vp.destroy()

    def test_select_camera_path_rejects_renderer_binding_failure(
        self, fake_camera_menu
    ):
        pose = BoundCameraPose(
            eye=(7.0, 3.0, -2.0),
            target=(1.0, 2.0, 3.0),
            up_axis="Y",
            fov_degrees=50.0,
            prim_path="/World/ShotCam",
        )
        adapter = _FakeCameraStageAdapter(
            choices=(StageChoice("/World/ShotCam", "Shot Cam"),),
            poses={"/World/ShotCam": pose},
        )

        class _RejectingCameraRenderer(MockRendererAdapter):
            def __init__(self):
                super().__init__()
                self.set_paths = []

            def set_active_camera_path(self, path):
                self.set_paths.append(path)
                return False

        renderer = _RejectingCameraRenderer()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            stage_adapter_provider=lambda: adapter,
        )
        before_target = list(vp._camera.state.target)

        assert vp._select_camera_path("/World/ShotCam") is False

        assert renderer.set_paths == ["/World/ShotCam"]
        assert vp._active_camera_path is None
        assert vp._camera.state.target == before_target
        vp.destroy()

    def test_selected_usd_camera_inactive_navigation_authors_pose_and_persists(self):
        pytest.importorskip("pxr")
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Gf, Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera1 = UsdGeom.Camera.Define(stage, "/World/Camera1")
        UsdGeom.Xformable(camera1.GetPrim()).AddTranslateOp().Set(
            Gf.Vec3d(0.0, 3.0, 12.0)
        )
        camera1.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, -3.0, -12.0))
        camera2 = UsdGeom.Camera.Define(stage, "/World/Camera2")
        UsdGeom.Xformable(camera2.GetPrim()).AddTranslateOp().Set(
            Gf.Vec3d(8.0, 2.0, 10.0)
        )
        camera2.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(-8.0, -2.0, -10.0))
        adapter = UsdStageAdapter(stage)

        class _Image:
            visible = True
            computed_width = 640
            computed_height = 360

        renderer = MockRendererAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            stage_adapter_provider=lambda: adapter,
        )
        vp._image = _Image()

        assert vp._select_camera_path("/World/Camera1") is True
        initial_distance = vp._camera.state.distance
        initial_eye = adapter.read_camera_pose("/World/Camera1").eye

        vp._camera.zoom(2.0)
        zoomed_distance = vp._camera.state.distance
        assert zoomed_distance > initial_distance
        assert vp.render(0.1) is True
        assert vp.is_camera_navigation_active()

        active_pose = adapter.read_camera_pose("/World/Camera1")
        assert active_pose.eye == pytest.approx(initial_eye)

        vp._reset_camera_navigation_state()
        assert not vp.is_camera_navigation_active()
        assert vp.render(0.1) is True

        zoomed_pose = adapter.read_camera_pose("/World/Camera1")
        assert zoomed_pose.eye != pytest.approx(initial_eye)
        assert zoomed_pose.eye == pytest.approx(
            tuple(float(v) for v in vp._camera._get_eye()),
            rel=1e-5,
            abs=1e-5,
        )
        assert zoomed_pose.target == pytest.approx((0.0, 0.0, 0.0))

        assert vp._select_camera_path("/World/Camera2") is True
        assert vp._select_camera_path("/World/Camera1") is True

        assert vp._camera.state.distance == pytest.approx(zoomed_distance)
        assert tuple(float(v) for v in vp._camera._get_eye()) == pytest.approx(
            zoomed_pose.eye
        )
        vp.destroy()

    def test_selected_usd_camera_natural_settle_clears_dirty(self):
        pytest.importorskip("pxr")
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Gf, Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera = UsdGeom.Camera.Define(stage, "/World/Camera1")
        UsdGeom.Xformable(camera.GetPrim()).AddTranslateOp().Set(
            Gf.Vec3d(0.0, 3.0, 12.0)
        )
        camera.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, -3.0, -12.0))

        class _CountingStageAdapter(UsdStageAdapter):
            def __init__(self, stage):
                super().__init__(stage)
                self.write_count = 0

            def write_camera_pose_from_matrices(
                self,
                path,
                view_matrix,
                proj_matrix,
                width,
                height,
                target_world,
                source=None,
            ):
                self.write_count += 1
                return super().write_camera_pose_from_matrices(
                    path,
                    view_matrix,
                    proj_matrix,
                    width,
                    height,
                    target_world,
                    source=source,
                )

        adapter = _CountingStageAdapter(stage)
        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )
        vp._image = _VisibleViewportImage()

        assert vp._select_camera_path("/World/Camera1") is True
        vp._camera.orbit(0.1, 0.02)
        assert vp.render(0.1) is True
        assert adapter.write_count == 0
        assert vp.is_camera_navigation_active()
        assert vp.has_dirty_camera_navigation()

        for _ in range(vp.CAMERA_NAVIGATION_SETTLE_FRAMES):
            assert vp.render(0.1) is True

        assert adapter.write_count == 1
        assert not vp.is_camera_navigation_active()
        assert not vp.has_dirty_camera_navigation()
        vp.destroy()

    def test_selected_usd_camera_self_authored_notice_does_not_resync(self):
        pytest.importorskip("pxr")
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Gf, Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera = UsdGeom.Camera.Define(stage, "/World/Camera1")
        UsdGeom.Xformable(camera.GetPrim()).AddTranslateOp().Set(
            Gf.Vec3d(0.0, 3.0, 12.0)
        )
        camera.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, -3.0, -12.0))

        class _CountingStageAdapter(UsdStageAdapter):
            def __init__(self, stage):
                self.deferred = []
                super().__init__(stage, call_later=lambda _delay, fn: self.deferred.append(fn))
                self.write_count = 0
                self.events = []

            def drain(self):
                while self.deferred:
                    callbacks = tuple(self.deferred)
                    self.deferred.clear()
                    for callback in callbacks:
                        callback()

            def write_camera_pose_from_matrices(
                self,
                path,
                view_matrix,
                proj_matrix,
                width,
                height,
                target_world,
                source=None,
            ):
                self.write_count += 1
                result = super().write_camera_pose_from_matrices(
                    path,
                    view_matrix,
                    proj_matrix,
                    width,
                    height,
                    target_world,
                    source=source,
                )
                self.drain()
                return result

            def _notify(self, event):
                self.events.append(event)
                return super()._notify(event)

        class _CountingViewportWidget(ViewportWidget):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.sync_count = 0

            def _sync_active_camera_from_stage_change(self, event):
                self.sync_count += 1
                return super()._sync_active_camera_from_stage_change(event)

        adapter = _CountingStageAdapter(stage)
        vp = _CountingViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )
        vp._image = _VisibleViewportImage()
        subscription = adapter.subscribe_changes(vp.notify_stage_changed)
        try:
            assert vp._select_camera_path("/World/Camera1") is True
            vp._camera.orbit(0.1, 0.02)
            assert vp.render(0.1) is True
            assert adapter.write_count == 0

            for _ in range(vp.CAMERA_NAVIGATION_SETTLE_FRAMES):
                assert vp.render(0.1) is True

            assert adapter.write_count == 1
            assert len(adapter.events) == 1
            assert adapter.events[0].source == VIEWPORT_CAMERA_POSE_SOURCE
            assert vp.sync_count == 0
        finally:
            subscription.cancel()
            vp.destroy()

    def test_destroy_commits_dirty_camera_pose(self):
        pytest.importorskip("pxr")
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Gf, Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera = UsdGeom.Camera.Define(stage, "/World/Camera1")
        UsdGeom.Xformable(camera.GetPrim()).AddTranslateOp().Set(
            Gf.Vec3d(0.0, 3.0, 12.0)
        )
        camera.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, -3.0, -12.0))

        class _CountingStageAdapter(UsdStageAdapter):
            def __init__(self, stage):
                super().__init__(stage)
                self.write_count = 0

            def write_camera_pose_from_matrices(
                self,
                path,
                view_matrix,
                proj_matrix,
                width,
                height,
                target_world,
                source=None,
            ):
                self.write_count += 1
                return super().write_camera_pose_from_matrices(
                    path,
                    view_matrix,
                    proj_matrix,
                    width,
                    height,
                    target_world,
                    source=source,
                )

        adapter = _CountingStageAdapter(stage)
        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )
        vp._image = _VisibleViewportImage()

        assert vp._select_camera_path("/World/Camera1") is True
        vp._camera.orbit(0.1, 0.02)
        assert vp.render(0.1) is True
        dragged_eye = tuple(float(v) for v in vp._camera._get_eye())
        dragged_target = tuple(float(v) for v in vp._camera.state.target)
        assert adapter.write_count == 0
        assert vp.has_dirty_camera_navigation()

        vp.destroy()

        assert adapter.write_count == 1
        pose = adapter.read_camera_pose("/World/Camera1")
        assert pose.eye == pytest.approx(dragged_eye, rel=1e-5, abs=1e-5)
        assert pose.target == pytest.approx(dragged_target, rel=1e-5, abs=1e-5)

    def test_destroy_dirty_camera_commit_does_not_create_undo_entry(self):
        pytest.importorskip("pxr")
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Gf, Sdf, Usd, UsdGeom

        from ovui_widgets.common.undo import UndoManager

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera = UsdGeom.Camera.Define(stage, "/World/Camera1")
        UsdGeom.Xformable(camera.GetPrim()).AddTranslateOp().Set(
            Gf.Vec3d(0.0, 3.0, 12.0)
        )
        camera.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, -3.0, -12.0))

        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )
        vp._image = _VisibleViewportImage()

        assert vp._select_camera_path("/World/Camera1") is True
        vp._camera.orbit(0.1, 0.02)
        assert vp.render(0.1) is True
        dragged_eye = tuple(float(v) for v in vp._camera._get_eye())
        assert vp.has_dirty_camera_navigation()

        vp.destroy()

        pose = adapter.read_camera_pose("/World/Camera1")
        assert pose.eye == pytest.approx(dragged_eye, rel=1e-5, abs=1e-5)
        assert undo.can_undo() is False

    def test_selected_usd_camera_external_transform_change_updates_viewport_pose(self):
        pytest.importorskip("pxr")
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Gf, Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera = UsdGeom.Camera.Define(stage, "/World/Camera1")
        translate_op = UsdGeom.Xformable(camera.GetPrim()).AddTranslateOp()
        translate_op.Set(Gf.Vec3d(0.0, 3.0, 12.0))
        camera.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, -3.0, -12.0))
        adapter = UsdStageAdapter(stage)

        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )

        assert vp._select_camera_path("/World/Camera1") is True
        assert tuple(float(v) for v in vp._camera._get_eye()) == pytest.approx(
            (0.0, 3.0, 12.0)
        )
        assert vp._camera.state.target == pytest.approx([0.0, 0.0, 0.0])

        translate_op.Set(Gf.Vec3d(6.0, 3.0, 12.0))
        event = ChangeEvent(
            changed_paths=("/World/Camera1.xformOp:translate",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        vp.notify_stage_changed(event)

        assert tuple(float(v) for v in vp._camera._get_eye()) == pytest.approx(
            (6.0, 3.0, 12.0),
            rel=1e-5,
            abs=1e-5,
        )
        assert vp._camera.state.target == pytest.approx(
            [6.0, 0.0, 0.0],
            rel=1e-5,
            abs=1e-5,
        )
        assert vp._last_authored_camera_signature == vp._camera_author_signature(
            "/World/Camera1"
        )
        vp.destroy()

    def test_selected_usd_camera_external_transform_change_still_invokes_sync(self):
        pytest.importorskip("pxr")
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Gf, Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera = UsdGeom.Camera.Define(stage, "/World/Camera1")
        translate_op = UsdGeom.Xformable(camera.GetPrim()).AddTranslateOp()
        translate_op.Set(Gf.Vec3d(0.0, 3.0, 12.0))
        camera.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, -3.0, -12.0))
        adapter = UsdStageAdapter(stage)

        class _CountingViewportWidget(ViewportWidget):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.sync_count = 0

            def _sync_active_camera_from_stage_change(self, event):
                self.sync_count += 1
                return super()._sync_active_camera_from_stage_change(event)

        vp = _CountingViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )

        assert vp._select_camera_path("/World/Camera1") is True
        translate_op.Set(Gf.Vec3d(6.0, 3.0, 12.0))
        vp.notify_stage_changed(
            ChangeEvent(
                changed_paths=("/World/Camera1.xformOp:translate",),
                resynced_paths=(),
                event_type=ChangeEventType.INFO_CHANGE,
            )
        )

        assert vp.sync_count == 1
        assert tuple(float(v) for v in vp._camera._get_eye()) == pytest.approx(
            (6.0, 3.0, 12.0),
            rel=1e-5,
            abs=1e-5,
        )
        vp.destroy()

    def test_selected_usd_camera_external_transform_update_does_not_reauthor_until_navigation(
        self,
    ):
        pytest.importorskip("pxr")
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Gf, Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera = UsdGeom.Camera.Define(stage, "/World/Camera1")
        translate_op = UsdGeom.Xformable(camera.GetPrim()).AddTranslateOp()
        translate_op.Set(Gf.Vec3d(0.0, 3.0, 12.0))
        camera.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, -3.0, -12.0))

        class _CountingStageAdapter(UsdStageAdapter):
            def __init__(self, stage):
                super().__init__(stage)
                self.write_count = 0

            def write_camera_pose_from_matrices(
                self,
                path,
                view_matrix,
                proj_matrix,
                width,
                height,
                target_world,
                source=None,
            ):
                self.write_count += 1
                return super().write_camera_pose_from_matrices(
                    path,
                    view_matrix,
                    proj_matrix,
                    width,
                    height,
                    target_world,
                    source=source,
                )

        class _Image:
            visible = True
            computed_width = 640
            computed_height = 360

        adapter = _CountingStageAdapter(stage)
        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )
        vp._image = _Image()

        assert vp._select_camera_path("/World/Camera1") is True
        translate_op.Set(Gf.Vec3d(6.0, 3.0, 12.0))
        vp.notify_stage_changed(
            ChangeEvent(
                changed_paths=("/World/Camera1.xformOp:translate",),
                resynced_paths=(),
                event_type=ChangeEventType.INFO_CHANGE,
            )
        )

        assert vp.render(0.1) is True
        assert adapter.write_count == 0

        vp._camera.zoom(1.0)
        assert vp.render(0.1) is True
        assert adapter.write_count == 0

        vp._reset_camera_navigation_state()
        assert vp.render(0.1) is True
        assert adapter.write_count == 1
        vp.destroy()

    def test_selected_usd_camera_external_transform_is_latest_after_switching_back(
        self,
    ):
        pytest.importorskip("pxr")
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter
        from pxr import Gf, Sdf, Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera1 = UsdGeom.Camera.Define(stage, "/World/Camera1")
        translate1 = UsdGeom.Xformable(camera1.GetPrim()).AddTranslateOp()
        translate1.Set(Gf.Vec3d(0.0, 3.0, 12.0))
        camera1.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, -3.0, -12.0))
        camera2 = UsdGeom.Camera.Define(stage, "/World/Camera2")
        UsdGeom.Xformable(camera2.GetPrim()).AddTranslateOp().Set(
            Gf.Vec3d(8.0, 2.0, 10.0)
        )
        camera2.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(-8.0, -2.0, -10.0))
        adapter = UsdStageAdapter(stage)

        vp = ViewportWidget(
            services=None,
            renderer=MockRendererAdapter(),
            stage_adapter_provider=lambda: adapter,
        )

        assert vp._select_camera_path("/World/Camera1") is True
        translate1.Set(Gf.Vec3d(6.0, 3.0, 12.0))
        vp.notify_stage_changed(
            ChangeEvent(
                changed_paths=("/World/Camera1.xformOp:translate",),
                resynced_paths=(),
                event_type=ChangeEventType.INFO_CHANGE,
            )
        )

        assert vp._select_camera_path("/World/Camera2") is True
        assert vp._select_camera_path("/World/Camera1") is True

        assert tuple(float(v) for v in vp._camera._get_eye()) == pytest.approx(
            (6.0, 3.0, 12.0),
            rel=1e-5,
            abs=1e-5,
        )
        assert vp._camera.state.target == pytest.approx(
            [6.0, 0.0, 0.0],
            rel=1e-5,
            abs=1e-5,
        )
        vp.destroy()

class TestApplicationPrimCountWiring:
    def setup_method(self):
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus
        Application._instance = None
        SelectionBus._instance = None
        self.app = Application()

    def teardown_method(self):
        self.app.shutdown()
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus
        Application._instance = None
        SelectionBus._instance = None

    def test_get_prim_count_returns_zero_when_no_adapter(self):
        self.app._stage_adapter = None
        assert self.app._get_prim_count() == 0

    def test_get_prim_count_counts_mock_prims(self):
        from ovui_widgets.common.testing.mock_stage import MockStageAdapter
        self.app._stage_adapter = MockStageAdapter()
        count = self.app._get_prim_count()
        # Default tree: World + Geometry + Ground + Sphere + Cube + Lights + DomeLight + Camera = 8
        assert count == 8

    def test_on_stage_changed_resync_calls_update_prim_count(self):
        from unittest.mock import MagicMock

        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        from ovui_widgets.common.testing.mock_stage import MockStageAdapter
        self.app._stage_adapter = MockStageAdapter()
        mock_vp = MagicMock()
        self.app._viewport_window = mock_vp
        event = ChangeEvent(
            changed_paths=(),
            resynced_paths=("/World",),
            event_type=ChangeEventType.RESYNC,
        )
        self.app._on_stage_changed(event)
        mock_vp.update_prim_count.assert_called_once_with(8)

    def test_on_stage_changed_resync_refreshes_layer_contents(self):
        from unittest.mock import MagicMock

        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        from ovui_widgets.common.testing.mock_stage import MockStageAdapter
        self.app._stage_adapter = MockStageAdapter()
        mock_layer_window = MagicMock()
        self.app._layer_window = mock_layer_window
        event = ChangeEvent(
            changed_paths=(),
            resynced_paths=("/World/Cube",),
            event_type=ChangeEventType.RESYNC,
        )
        self.app._on_stage_changed(event)
        mock_layer_window.refresh_layer_contents.assert_called_once_with()

    def test_on_stage_changed_info_change_does_not_call_update_prim_count(self):
        from unittest.mock import MagicMock

        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        from ovui_widgets.common.testing.mock_stage import MockStageAdapter
        self.app._stage_adapter = MockStageAdapter()
        mock_vp = MagicMock()
        self.app._viewport_window = mock_vp
        event = ChangeEvent(
            changed_paths=("/World",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        self.app._on_stage_changed(event)
        mock_vp.update_prim_count.assert_not_called()

    def test_on_stage_changed_info_change_does_not_refresh_layer_contents(self):
        from unittest.mock import MagicMock

        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        from ovui_widgets.common.testing.mock_stage import MockStageAdapter
        self.app._stage_adapter = MockStageAdapter()
        mock_layer_window = MagicMock()
        self.app._layer_window = mock_layer_window
        event = ChangeEvent(
            changed_paths=("/World/Cube.size",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        self.app._on_stage_changed(event)
        mock_layer_window.refresh_layer_contents.assert_not_called()

    def test_on_stage_changed_resync_no_crash_when_viewport_none(self):
        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        from ovui_widgets.common.testing.mock_stage import MockStageAdapter
        self.app._stage_adapter = MockStageAdapter()
        self.app._viewport_window = None
        event = ChangeEvent(
            changed_paths=(),
            resynced_paths=("/World",),
            event_type=ChangeEventType.RESYNC,
        )
        self.app._on_stage_changed(event)  # must not raise

    def test_load_stage_forwards_scene_title_to_viewport(self, monkeypatch):
        from unittest.mock import MagicMock
        Usd = pytest.importorskip("pxr.Usd", reason="pxr.Usd not available")
        UsdGeom = pytest.importorskip(
            "pxr.UsdGeom",
            reason="pxr.UsdGeom not available",
        )
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        viewport = MagicMock()
        renderer = MagicMock()
        self.app._viewport_window = viewport
        self.app._stage_window = None
        self.app._property_window = None
        monkeypatch.setattr(
            self.app,
            "_build_renderer_for_stage",
            lambda *a, **k: renderer,
        )
        self.app.selection_bus.publish(["/OldStage/Cube"], source="test")
        self.app._load_stage(stage, title="unit_scene.usda")
        viewport.set_scene_name.assert_called_once_with("unit_scene.usda")
        viewport.attach_stage.assert_called_once()
        viewport.set_renderer.assert_called_once_with(renderer)
        assert self.app.selection_bus.get_snapshot().paths() == []


class TestViewportNotifyStageChanged:
    """ViewportWidget.notify_stage_changed forwards to the renderer."""

    def test_forwards_to_renderer_if_handler_exists(self):
        from unittest.mock import MagicMock
        renderer = MagicMock(spec=["render_frame", "shutdown", "notify_stage_changed",
                                   "set_selection_highlight", "set_resolution",
                                   "load_stage", "pick", "pick_rect", "cancel_pick"])
        vp = ViewportWidget(services=None, renderer=renderer)
        event = object()
        vp.notify_stage_changed(event)
        renderer.notify_stage_changed.assert_called_once_with(event)
        vp.destroy()

    def test_noop_when_renderer_lacks_handler(self):
        """MockRendererAdapter has no notify_stage_changed — must not raise."""
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp.notify_stage_changed(object())  # must not raise
        vp.destroy()

    def test_swallows_handler_exception(self):
        from unittest.mock import MagicMock
        renderer = MagicMock()
        renderer.notify_stage_changed.side_effect = RuntimeError("boom")
        vp = ViewportWidget(services=None, renderer=renderer)
        vp.notify_stage_changed(object())  # must not propagate
        vp.destroy()


class TestViewportWidgetResizeClamping:
    """Step A.5 — widget clamps computed size before calling render_frame.

    The viewport measures ``_image.computed_width/height`` each frame; these
    values can be anything from 0 (layout pending) to ~7680 (4K × HiDPI).
    ``_on_frame`` must clamp to [64, 3840] × [64, 2160] before invoking the
    renderer so the renderer never has to deal with absurd buffer sizes.
    """

    @staticmethod
    def _vp_with_fake_image(renderer, w: float, h: float):
        """Return a ViewportWidget whose ``_image`` reports ``w × h``.

        Bypasses ``_build_ui`` (which would try to talk to real omni.ui
        layout) and installs a minimal stub — enough for ``_on_frame``
        to pull measurements off it. Also wires ``render_frame`` to
        return a correctly-shaped zero array so the bridge update path
        after the renderer call doesn't blow up on a MagicMock result.
        """
        from unittest.mock import MagicMock
        vp = ViewportWidget(services=None, renderer=renderer)
        img = MagicMock()
        img.visible = True
        img.computed_width = w
        img.computed_height = h
        vp._image = img

        def _fake_render(rw, rh, _view, _proj):
            return np.zeros((int(rh), int(rw), 4), dtype=np.uint8)
        renderer.render_frame.side_effect = _fake_render
        return vp

    def test_below_min_clamps_up_to_64x64(self):
        from unittest.mock import MagicMock
        renderer = MagicMock()
        vp = self._vp_with_fake_image(renderer, 10, 20)
        vp._on_frame(0.1)
        args, _ = renderer.render_frame.call_args
        w, h, _view, _proj = args
        assert w == 64
        assert h == 64
        vp.destroy()

    def test_above_max_clamps_down_to_4k_uhd(self):
        from unittest.mock import MagicMock
        renderer = MagicMock()
        vp = self._vp_with_fake_image(renderer, 7680, 4320)
        vp._on_frame(0.1)
        args, _ = renderer.render_frame.call_args
        w, h, _view, _proj = args
        assert w == 3840
        assert h == 2160
        vp.destroy()

    def test_within_bounds_passes_through(self):
        from unittest.mock import MagicMock
        renderer = MagicMock()
        vp = self._vp_with_fake_image(renderer, 1600, 900)
        vp._on_frame(0.1)
        args, _ = renderer.render_frame.call_args
        w, h, _view, _proj = args
        assert w == 1600
        assert h == 900
        vp.destroy()

    def test_asymmetric_clamp_on_one_axis_only(self):
        # 4000 wide is out of range but 1200 tall is fine — the axes
        # clamp independently.
        from unittest.mock import MagicMock
        renderer = MagicMock()
        vp = self._vp_with_fake_image(renderer, 4000, 1200)
        vp._on_frame(0.1)
        args, _ = renderer.render_frame.call_args
        w, h, _view, _proj = args
        assert w == 3840
        assert h == 1200
        vp.destroy()

    def test_zero_dimension_still_returns_early(self):
        # A 0-size widget (layout pending) must NOT get a 64×64 render —
        # the early-return for w<=0/h<=0 fires before clamping.
        from unittest.mock import MagicMock
        renderer = MagicMock()
        vp = self._vp_with_fake_image(renderer, 0, 0)
        vp._on_frame(0.1)
        renderer.render_frame.assert_not_called()
        vp.destroy()

    def test_clamp_constants_match_viewport_plan(self):
        # Pin the constants so a refactor doesn't silently drift from
        # the viewport behavior ("minimum 64×64, maximum 3840×2160").
        assert ViewportWidget.MIN_RENDER_WIDTH == 64
        assert ViewportWidget.MIN_RENDER_HEIGHT == 64
        assert ViewportWidget.MAX_RENDER_WIDTH == 3840
        assert ViewportWidget.MAX_RENDER_HEIGHT == 2160


class TestApplicationNotifiesViewportOnStageChange:
    def setup_method(self):
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus
        Application._instance = None
        SelectionBus._instance = None
        self.app = Application()

    def teardown_method(self):
        self.app.shutdown()
        from ovui_widgets.app.application import Application
        from ovui_widgets.common.selection import SelectionBus
        Application._instance = None
        SelectionBus._instance = None

    def test_info_change_forwards_to_viewport(self):
        from unittest.mock import MagicMock

        from ovui_data_adapters.common import ChangeEvent, ChangeEventType
        mock_vp = MagicMock()
        self.app._viewport_window = mock_vp
        event = ChangeEvent(
            changed_paths=("/World/Cube.xformOp:translate",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )
        self.app._on_stage_changed(event)
        mock_vp.notify_stage_changed.assert_called_once_with(event)

    def test_resync_also_forwards_to_viewport(self):
        from unittest.mock import MagicMock

        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        from ovui_widgets.common.testing.mock_stage import MockStageAdapter
        self.app._stage_adapter = MockStageAdapter()
        mock_vp = MagicMock()
        self.app._viewport_window = mock_vp
        event = ChangeEvent(
            changed_paths=(),
            resynced_paths=("/World",),
            event_type=ChangeEventType.RESYNC,
        )
        self.app._on_stage_changed(event)
        mock_vp.notify_stage_changed.assert_called_once_with(event)


class TestRendererGenerationLifecycle:
    """Renderer-generation transitions rebuild or preserve the UI coherently.

    The OpenGL manipulator overlay's publish path is tied to the renderer
    generation the scene view was built against, so EVERY generation change
    after the UI is built — real→real, real→none, none→real — must rebuild
    the widget UI; the rebuild destroys the previous scene view so repeated
    transitions do not leak GL resources or strand input routing on dead
    scene views. Same-object re-assignment and a first install before the
    UI exists must not trigger redundant rebuilds, and final teardown must
    release the scene view.
    """

    def _viewport_with_fake_window(self, *, ui_built: bool):
        from types import SimpleNamespace

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        rebuilds = []
        vp._window = SimpleNamespace(
            frame=SimpleNamespace(rebuild=lambda: rebuilds.append(1)),
        )
        if ui_built:
            # ``_image`` is the built-UI marker: it exists for every build
            # (including the rendererless one, which has no scene view).
            vp._image = SimpleNamespace(visible=True)
            vp._scene_view = SimpleNamespace(destroy=lambda: None)
        return vp, rebuilds

    def test_real_to_real_swap_rebuilds(self):
        vp, rebuilds = self._viewport_with_fake_window(ui_built=True)
        vp.set_renderer(MockRendererAdapter())
        assert rebuilds == [1]

    def test_real_to_none_rebuilds_when_ui_built(self):
        vp, rebuilds = self._viewport_with_fake_window(ui_built=True)
        vp.set_renderer(None)
        assert rebuilds == [1]

    def test_none_to_real_rebuilds_when_ui_built(self):
        vp, rebuilds = self._viewport_with_fake_window(ui_built=True)
        vp._renderer = None
        vp.set_renderer(MockRendererAdapter())
        assert rebuilds == [1]

    def test_none_to_real_rebuilds_from_rendererless_build(self):
        # The rendererless build has NO scene view — the built-UI marker is
        # the Layer-1 image, so restoring a renderer must still rebuild.
        from types import SimpleNamespace

        vp, rebuilds = self._viewport_with_fake_window(ui_built=True)
        vp._renderer = None
        vp._scene_view = None
        vp.set_renderer(MockRendererAdapter())
        assert rebuilds == [1]

    def test_reinstalling_same_renderer_does_not_rebuild(self):
        vp, rebuilds = self._viewport_with_fake_window(ui_built=True)
        vp.set_renderer(vp._renderer)
        assert rebuilds == []

    def test_first_install_before_ui_build_does_not_rebuild(self):
        vp, rebuilds = self._viewport_with_fake_window(ui_built=False)
        vp._renderer = None
        vp.set_renderer(MockRendererAdapter())
        assert rebuilds == []

    def test_swap_before_ui_build_does_not_rebuild(self):
        vp, rebuilds = self._viewport_with_fake_window(ui_built=False)
        vp.set_renderer(MockRendererAdapter())
        assert rebuilds == []

    def test_repeated_transitions_rebuild_each_generation_change(self):
        vp, rebuilds = self._viewport_with_fake_window(ui_built=True)
        real_a = MockRendererAdapter()
        vp.set_renderer(real_a)   # real -> real
        vp.set_renderer(real_a)   # same object: no-op
        vp.set_renderer(None)     # real -> none
        vp.set_renderer(MockRendererAdapter())  # none -> real
        assert rebuilds == [1, 1, 1]

    def test_rebuild_destroys_previous_scene_view(self):
        from types import SimpleNamespace

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        destroyed = []
        vp._scene_view = SimpleNamespace(destroy=lambda: destroyed.append(1))
        _build_or_xfail_unsupported(vp)
        assert destroyed == [1]
        vp.destroy()

    def test_destroy_surface_resources_destroys_scene_view(self):
        from types import SimpleNamespace

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        destroyed = []
        vp._scene_view = SimpleNamespace(destroy=lambda: destroyed.append(1))
        vp._destroy_surface_resources()
        assert destroyed == [1]
        assert vp._scene_view is None


class TestRendererTransitionDragBoundary:
    """Renderer transitions atomically resolve active drags and overlays."""

    def _viewport_with_fake_window(self):
        from types import SimpleNamespace

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._window = SimpleNamespace(
            frame=SimpleNamespace(rebuild=lambda: None),
        )
        return vp

    @staticmethod
    def _wire_model_for_drag(vp):
        from contextlib import contextmanager
        from unittest.mock import MagicMock

        from ovui_widgets.common.testing.mock_transform import (
            MockTransformAdapter,
        )
        from ovui_widgets.common.undo import UndoManager

        @contextmanager
        def _cm():
            yield

        stage = MagicMock()
        stage.suppress_change_notifications.side_effect = lambda: _cm()
        model = vp._transform_model
        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=stage,
            undo=UndoManager(),
            renderer=vp._renderer,
        )
        return model

    def test_set_renderer_cancels_active_drag_against_old_generation(self):
        vp = self._viewport_with_fake_window()
        model = self._wire_model_for_drag(vp)
        model.set_selection(["/World/A"])
        model.on_drag_start()
        assert model._drag_active is True

        vp.set_renderer(MockRendererAdapter())

        assert model._drag_active is False
        assert model._live_transforms == {}
        assert model.failed_preview_restores == {}

    def test_set_renderer_to_none_cancels_active_drag(self):
        vp = self._viewport_with_fake_window()
        model = self._wire_model_for_drag(vp)
        model.set_selection(["/World/A"])
        model.on_drag_start()

        vp.set_renderer(None)

        assert model._drag_active is False
        assert model.failed_preview_restores == {}

    def test_rendererless_build_creates_no_manipulator_layer(self):
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._renderer = None
        vp._build_ui()
        assert vp._scene_view is None
        assert vp._transform_manipulator is None
        assert vp._camera_manipulator is None
        assert vp._pick_manager is None
        assert vp._tool_registry is None
        vp.destroy()

    def test_rendererless_build_still_destroys_previous_scene_view(self):
        from types import SimpleNamespace

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        destroyed = []
        vp._scene_view = SimpleNamespace(destroy=lambda: destroyed.append(1))
        vp._renderer = None
        vp._build_ui()
        assert destroyed == [1]
        assert vp._scene_view is None
        vp.destroy()


class TestTeardownResolvesDrags:
    """Final teardown resolves drag state before destroying resources."""

    def _wired_viewport(self):
        from contextlib import contextmanager
        from unittest.mock import MagicMock

        from ovui_widgets.common.testing.mock_transform import (
            MockTransformAdapter,
        )
        from ovui_widgets.common.undo import UndoManager

        @contextmanager
        def _cm():
            yield

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        stage = MagicMock()
        stage.suppress_change_notifications.side_effect = lambda: _cm()
        model = vp._transform_model
        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=stage,
            undo=UndoManager(),
            renderer=vp._renderer,
        )
        return vp, model

    def test_teardown_resolves_active_model_drag(self):
        vp, model = self._wired_viewport()
        model.set_selection(["/World/A"])
        model.on_drag_start()
        assert model._drag_active is True
        dead = vp._renderer

        vp._destroy_surface_resources()

        assert model._drag_active is False
        assert model._live_transforms == {}
        assert model.failed_preview_restores == {}
        assert model._renderer is not dead
        assert model._renderer is None

    def test_teardown_is_idempotent(self):
        vp, model = self._wired_viewport()
        model.set_selection(["/World/A"])
        model.on_drag_start()
        vp._destroy_surface_resources()
        vp._destroy_surface_resources()
        assert model._drag_active is False
        assert model._renderer is None

    def test_teardown_safe_when_cancel_raises(self):
        vp, model = self._wired_viewport()

        class _RaisingStage:
            def begin_undo_group(self, label):
                pass

            def end_undo_group(self):
                raise RuntimeError("undo close failed")

        model._stage = _RaisingStage()
        model.set_selection(["/World/A"])
        model.on_drag_start()

        vp._destroy_surface_resources()

        assert model._drag_active is False
        assert model._renderer is None

    def test_teardown_resolves_streamed_drag(self):
        vp, model = self._wired_viewport()
        vp._streamed_transform_drag = {
            "gesture": type(
                "G", (), {"cancel_streamed_drag": lambda self: True}
            )(),
            "axis": "x",
            "pointer_start": (0, 0),
        }

        vp._destroy_surface_resources()

        assert vp._streamed_transform_drag is None


class TestReplacementOwnershipCoherence:
    """Renderer replacement never splits surface/model ownership."""

    def test_replacement_with_raising_undo_close_keeps_owners_together(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from ovui_widgets.common.testing.mock_transform import (
            MockTransformAdapter,
        )
        from ovui_widgets.common.undo import UndoManager

        @contextmanager
        def _cm():
            yield

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._window = SimpleNamespace(frame=SimpleNamespace(rebuild=lambda: None))
        model = vp._transform_model

        class _RaisingStage:
            def begin_undo_group(self, label):
                pass

            def end_undo_group(self):
                raise RuntimeError("undo close failed")

        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=_RaisingStage(),
            undo=UndoManager(),
            renderer=vp._renderer,
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()

        new = MockRendererAdapter()
        vp.set_renderer(new)

        assert vp._renderer is new
        assert model._renderer is new
        assert model._drag_active is False

    def test_replacement_with_raising_shutdown_blocks_publication(self):
        from types import SimpleNamespace

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._window = SimpleNamespace(frame=SimpleNamespace(rebuild=lambda: None))
        old = vp._renderer
        old.shutdown = lambda: (_ for _ in ()).throw(RuntimeError("shutdown failed"))
        vp._transform_model.set_renderer(old)

        new = MockRendererAdapter()
        vp.set_renderer(new)

        # a possibly-live predecessor blocks successor publication:
        # owners stay together on the detached state, the predecessor is
        # the single owned obligation, and the refused incoming renderer
        # was resolved by courtesy shutdown (never adopted).
        assert vp._renderer is None
        assert vp._transform_model._renderer is None
        assert vp.unresolved_predecessor is old
        assert new._shutdown_called is True
        assert vp.lifecycle_state == "unavailable"

    def test_replacement_with_raising_rebuild_faults_coherently(self):
        from types import SimpleNamespace

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._image = SimpleNamespace(visible=True)
        def _boom():
            raise RuntimeError("rebuild failed")
        vp._window = SimpleNamespace(frame=SimpleNamespace(rebuild=_boom))
        vp._transform_model.set_renderer(vp._renderer)

        new = MockRendererAdapter()
        vp.set_renderer(new)

        # no half-generation is published: the viewport faults with both
        # owners detached together and the successor resolved.
        assert vp._renderer is None
        assert vp._transform_model._renderer is None
        assert new._shutdown_called is True
        assert vp.lifecycle_state == "unavailable"


class TestReplacementTransaction:
    """Renderer replacement has one commit point and a safe fallback."""

    def _viewport(self, rebuild=None):
        from types import SimpleNamespace

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._image = SimpleNamespace(visible=True)
        vp._window = SimpleNamespace(
            frame=SimpleNamespace(rebuild=rebuild or (lambda: None)),
        )
        vp._transform_model.set_renderer(vp._renderer)
        return vp

    def test_model_assignment_failure_falls_back_to_detached_state(self):
        vp = self._viewport()
        model = vp._transform_model
        old = vp._renderer

        def raising_set(renderer):
            raise RuntimeError("model assignment failed")

        model.set_renderer = raising_set
        vp.set_renderer(MockRendererAdapter())

        # wholly detached — never split between predecessor and successor
        assert vp._renderer is None
        assert model._renderer is None
        assert model._renderer is not old

    def test_rebuild_request_failure_faults_and_destroys_stale_ui(self):
        from types import SimpleNamespace

        destroyed = []
        tools = []

        def boom():
            raise RuntimeError("rebuild request failed")

        vp = self._viewport(rebuild=boom)
        vp._scene_view = SimpleNamespace(destroy=lambda: destroyed.append(1))
        vp._tool_registry = SimpleNamespace(destroy=lambda: tools.append(1))
        new = MockRendererAdapter()

        vp.set_renderer(new)

        # a successor without a verified UI generation is never
        # published: the viewport faults, the stale scene view AND the
        # tool registry are destroyed (not just nulled), and the
        # successor is shut down rather than leaked.
        assert vp._renderer is None
        assert vp._transform_model._renderer is None
        assert vp.lifecycle_state == "unavailable"
        assert destroyed == [1]
        assert tools == [1]
        assert new._shutdown_called is True
        assert vp._scene_view is None
        assert vp._transform_manipulator is None
        assert vp._pick_manager is None
        assert vp._tool_registry is None

    def test_shutdown_failure_is_observable_and_blocks_publication(self):
        from unittest.mock import patch

        vp = self._viewport()
        old = vp._renderer

        def sboom():
            raise RuntimeError("shutdown failed")

        old.shutdown = sboom
        new = MockRendererAdapter()
        with patch(
            "ovui_widgets.viewport.viewport_widget.ErrorReporter.log_error"
        ) as log:
            vp.set_renderer(new)

        # observable AND truthful: no successor coexists with the
        # possibly-live predecessor
        assert vp._renderer is None
        assert vp._transform_model._renderer is None
        assert vp.unresolved_predecessor is old
        assert any(
            "shutdown" in str(call.args[1]) for call in log.call_args_list
        )
        # once the predecessor recovers, the next install is admitted
        old.shutdown = lambda: None
        final = MockRendererAdapter()
        vp.set_renderer(final)
        assert vp.unresolved_predecessor is None
        assert vp._renderer is final
        assert vp._transform_model._renderer is final

    def test_replacement_failures_during_active_drag_finalize_drag(self):
        from contextlib import contextmanager
        from unittest.mock import MagicMock

        from ovui_widgets.common.testing.mock_transform import (
            MockTransformAdapter,
        )
        from ovui_widgets.common.undo import UndoManager

        @contextmanager
        def _cm():
            yield

        vp = self._viewport()
        model = vp._transform_model
        stage = MagicMock()
        stage.suppress_change_notifications.side_effect = lambda: _cm()
        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=stage,
            undo=UndoManager(),
            renderer=vp._renderer,
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()
        old = vp._renderer

        def sboom():
            raise RuntimeError("shutdown failed")

        old.shutdown = sboom
        new = MockRendererAdapter()
        vp.set_renderer(new)

        assert model._drag_active is False
        assert model._live_transforms == {}
        # publication blocked by the unresolved predecessor; ownership
        # stays coherent on the detached state
        assert vp._renderer is None and model._renderer is None
        assert vp.unresolved_predecessor is old

    def test_repeated_replacement_after_failed_attempt_recovers(self):
        vp = self._viewport()
        model = vp._transform_model

        real_set = type(model).set_renderer

        def raising_set(renderer):
            raise RuntimeError("model assignment failed")

        model.set_renderer = raising_set
        vp.set_renderer(MockRendererAdapter())
        assert vp._renderer is None  # detached fallback

        # injection cleared: the next replacement succeeds wholesale
        del model.set_renderer
        final = MockRendererAdapter()
        vp.set_renderer(final)
        assert vp._renderer is final
        assert model._renderer is final

    def test_teardown_detach_failure_drops_dead_reference(self):
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        model = vp._transform_model
        dead = vp._renderer
        model.set_renderer(dead)

        def raising_detach(renderer):
            raise RuntimeError("detach failed")

        model.set_renderer = raising_detach
        vp._destroy_surface_resources()

        assert model._renderer is None
        assert model._renderer is not dead


class TestFailClosedLifecycle:
    """Adversarial combinations: safety state holds even when cleanup and
    diagnostics themselves raise; unresolved work survives only as bounded
    inert obligations."""

    def _viewport(self, rebuild=None):
        from types import SimpleNamespace

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._image = SimpleNamespace(visible=True)
        vp._window = SimpleNamespace(
            frame=SimpleNamespace(rebuild=rebuild or (lambda: None)),
        )
        vp._transform_model.set_renderer(vp._renderer)
        return vp

    def test_partial_mutation_plus_raising_reporter_stays_coherent(self):
        from unittest.mock import patch

        vp = self._viewport()
        model = vp._transform_model
        old = vp._renderer
        succ = MockRendererAdapter()

        def partial_then_raise(renderer):
            model._renderer = renderer  # mutates, then fails
            raise RuntimeError("publication failed after mutation")

        model.set_renderer = partial_then_raise
        with patch(
            "ovui_widgets.viewport.viewport_widget.ErrorReporter.log_error",
            side_effect=RuntimeError("reporter failed"),
        ):
            vp.set_renderer(succ)  # must not raise

        assert vp._renderer is None
        assert model._renderer is None
        assert old._shutdown_called is True
        assert succ._shutdown_called is True
        assert vp.lifecycle_state == "unavailable"

    def test_predecessor_shutdown_failure_is_the_single_owned_obligation(self):
        vp = self._viewport()
        old = vp._renderer
        calls = []

        def failing_shutdown():
            calls.append(1)
            raise RuntimeError("shutdown failed")

        old.shutdown = failing_shutdown
        new = MockRendererAdapter()
        vp.set_renderer(new)

        # publication blocked; the predecessor is the one owned debt and
        # the refused incoming renderer was never adopted
        assert vp._renderer is None
        assert vp.unresolved_predecessor is old
        assert new._shutdown_called is True

        # the slot is retried at the next lifecycle point and clears
        # once the owner recovers, re-admitting installs
        old.shutdown = lambda: calls.append("ok")
        final = MockRendererAdapter()
        vp.set_renderer(final)
        assert vp.unresolved_predecessor is None
        assert vp._renderer is final
        assert "ok" in calls

    def test_repeated_rejected_installs_never_grow_owned_debt(self):
        vp = self._viewport()
        old = vp._renderer
        old.shutdown = lambda: (_ for _ in ()).throw(RuntimeError("x"))
        vp.set_renderer(MockRendererAdapter())  # creates the single debt
        assert vp.unresolved_predecessor is old

        # repeated rejected installs whose own shutdown also fails are
        # refused WITHOUT adoption: owned debt cannot grow and no retry
        # work accumulates
        for _ in range(6):
            rejected = MockRendererAdapter()
            rejected.shutdown = lambda: (_ for _ in ()).throw(
                RuntimeError("reject shutdown failed")
            )
            vp.set_renderer(rejected)
            assert vp.unresolved_predecessor is old
            assert vp._renderer is None

        # recovery clears the single slot and re-admits installs
        old.shutdown = lambda: None
        final = MockRendererAdapter()
        vp.set_renderer(final)
        assert vp.unresolved_predecessor is None
        assert vp._renderer is final

    def test_combined_teardown_failures_reach_terminal_state(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        from ovui_widgets.common.testing.mock_transform import (
            MockTransformAdapter,
        )
        from ovui_widgets.common.undo import UndoManager

        @contextmanager
        def _cm():
            yield

        vp = self._viewport()
        model = vp._transform_model

        class _RaisingStage:
            def begin_undo_group(self, label):
                pass

            def end_undo_group(self):
                raise RuntimeError("undo close failed")

            def suppress_change_notifications(self):
                return _cm()

        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=_RaisingStage(),
            undo=UndoManager(),
            renderer=vp._renderer,
        )
        model.set_selection(["/World/A"])
        model.on_drag_start()  # active drag with an owner whose close fails
        dead = vp._renderer
        shutdown_refusal = RuntimeError("shutdown")
        dead.shutdown = lambda: (_ for _ in ()).throw(shutdown_refusal)
        vp._scene_view = SimpleNamespace(
            destroy=lambda: (_ for _ in ()).throw(RuntimeError("sv destroy"))
        )
        vp._tool_registry = SimpleNamespace(
            destroy=lambda: (_ for _ in ()).throw(RuntimeError("tool destroy"))
        )
        real_detach = model.set_renderer
        model.set_renderer = lambda r: (_ for _ in ()).throw(
            RuntimeError("detach failed")
        )

        with patch(
            "ovui_widgets.viewport.viewport_widget.ErrorReporter.log_error",
            side_effect=RuntimeError("reporter failed"),
        ):
            with pytest.raises(RuntimeError) as caught:
                vp._destroy_surface_resources()
        assert caught.value is shutdown_refusal

        # terminal invariants despite every injected failure
        assert model._drag_active is False
        assert model._live_transforms == {}
        assert model._renderer is None
        assert vp._renderer is None
        assert vp.lifecycle_state == "destroyed"
        # undo contamination retained truthfully (owner still failing)
        assert len(model.contaminated_undo_owners) > 0
        # unresolved renderer shutdown retained as the single owned debt
        assert vp.unresolved_predecessor is dead

        # a later recovery retry is safe and idempotent
        dead.shutdown = lambda: None
        vp._destroy_surface_resources()
        assert vp.lifecycle_state == "destroyed"
        assert model._renderer is None

    def test_queued_input_is_harmless_in_faulted_state(self):
        def boom():
            raise RuntimeError("rebuild request failed")

        vp = self._viewport(rebuild=boom)
        vp.set_renderer(MockRendererAdapter())  # faults (rebuild fails)
        assert vp.lifecycle_state == "unavailable"

        # queued mouse-up / escape find nothing to act on
        assert vp.cancel_active_transform_drag(reason="escape") is False
        # no pick/gesture surfaces remain
        assert vp._scene_view is None
        assert vp._pick_manager is None
        # a new drag cannot start through the model without a renderer:
        # preview writes are refused, no USD is touched
        model = vp._transform_model
        assert model._renderer is None


class TestLifecycleStateTruth:
    """lifecycle_state describes established reality, never requested work."""

    def _viewport(self, rebuild=None):
        from types import SimpleNamespace

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._image = SimpleNamespace(visible=True)
        vp._window = SimpleNamespace(
            frame=SimpleNamespace(rebuild=rebuild or (lambda: None)),
        )
        vp._transform_model.set_renderer(vp._renderer)
        return vp

    def test_construction_before_first_build_is_not_usable(self):
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        assert vp.lifecycle_state == "unavailable"

    def test_successful_build_is_usable(self):
        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        _build_or_xfail_unsupported(vp)
        assert vp.lifecycle_state == "usable"
        vp.destroy()

    def test_rebuild_request_is_not_completion(self):
        from types import SimpleNamespace

        vp = self._viewport()  # fake rebuild: requested but never executed
        vp._scene_view = SimpleNamespace(destroy=lambda: None)
        vp.set_renderer(MockRendererAdapter())
        # request returned, no build ran: not usable, and no
        # old-generation interaction resource remains attached
        assert vp.lifecycle_state == "unavailable"
        assert vp._scene_view is None
        assert vp._transform_manipulator is None
        assert vp._pick_manager is None

    def test_delayed_build_completion_becomes_usable(self):
        vp = self._viewport()
        vp.set_renderer(MockRendererAdapter())
        assert vp.lifecycle_state == "unavailable"
        # the framework's deferred build eventually runs for the CURRENT
        # generation
        _build_or_xfail_unsupported(vp)
        assert vp.lifecycle_state == "usable"
        vp._destroy_surface_resources()

    def test_partial_build_failure_is_not_usable(self):
        from types import SimpleNamespace

        vp = self._viewport()
        # simulate a partial UI creation result: scene view exists but
        # the manipulator/pick surface never completed
        vp._scene_view = SimpleNamespace(destroy=lambda: None)
        vp._transform_manipulator = None
        vp._pick_manager = None
        assert vp.lifecycle_state == "unavailable"

    def test_clearing_renderer_is_inert_at_return(self):
        from types import SimpleNamespace

        vp = self._viewport()
        sv = SimpleNamespace(destroy=lambda: None)
        vp._scene_view = sv
        vp.set_renderer(None)
        assert vp.lifecycle_state == "unavailable"
        assert vp._scene_view is None  # not deferred to a later rebuild

    def test_stale_completion_from_older_generation_builds_current(self):
        vp = self._viewport()
        vp.set_renderer(None)  # generation change while a build is pending
        # the deferred build from the older generation now runs — it must
        # build for the CURRENT (rendererless) generation, not resurrect
        # the old one
        vp._build_ui()
        assert vp._scene_view is None
        assert vp.lifecycle_state == "unavailable"

    def test_destroyed_rejects_new_renderer_and_resolves_it(self):
        vp = self._viewport()
        vp._destroy_surface_resources()
        assert vp.lifecycle_state == "destroyed"
        live = MockRendererAdapter()
        vp.set_renderer(live)
        assert vp._renderer is None
        assert vp.lifecycle_state == "destroyed"
        assert live._shutdown_called is True

    def test_destroyed_never_adopts_renderer_even_if_shutdown_fails(self):
        vp = self._viewport()
        vp._destroy_surface_resources()
        stubborn = MockRendererAdapter()
        stubborn.shutdown = lambda: (_ for _ in ()).throw(RuntimeError("x"))
        vp.set_renderer(stubborn)
        # ownership refused: the caller keeps the resource; the terminal
        # object retains nothing
        assert vp._renderer is None
        assert vp.unresolved_predecessor is not stubborn
        assert vp.lifecycle_state == "destroyed"

    def test_stale_manipulator_callbacks_are_inert_after_detach(self):
        from contextlib import contextmanager
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from ovui_widgets.common.testing.mock_transform import (
            MockTransformAdapter,
        )
        from ovui_widgets.common.undo import UndoManager
        from ovui_widgets.viewport.translate_gizmo import (
            PrimTranslateChangedGesture,
        )

        @contextmanager
        def _cm():
            yield

        vp = self._viewport()
        model = vp._transform_model
        stage = MagicMock()
        stage.suppress_change_notifications.side_effect = lambda: _cm()
        model.attach_adapters(
            transform_adapter=MockTransformAdapter(),
            stage_adapter=stage,
            undo=UndoManager(),
            renderer=vp._renderer,
        )
        model.set_selection(["/World/A"])
        gesture = PrimTranslateChangedGesture.__new__(
            PrimTranslateChangedGesture
        )
        gesture._model = model
        gesture._active = False
        gesture._accumulated = [0.0, 0.0, 0.0]
        gesture._drag_start_point = None
        gesture._drag_ended_this_cycle = False
        vp._transform_manipulator = SimpleNamespace(
            _translate_drags=[gesture],
            _rotate_drags=[],
            _scale_drags=[],
            _uniform_scale_drag=None,
        )
        # the gesture belongs to the live generation; the resource
        # destructor FAILS, and the callback stays retained externally
        import ovui_widgets.viewport.viewport_widget as viewport_mod

        token = viewport_mod._Generation(vp._renderer, vp)
        token.alive = True
        gesture._generation = token
        vp._live_generation = token
        vp._scene_view = SimpleNamespace(
            destroy=lambda: (_ for _ in ()).throw(RuntimeError("sv"))
        )
        vp.set_renderer(None)

        assert token.alive is False  # single invalidation boundary flipped
        gesture._on_began()  # stale externally retained callback fires
        assert model._drag_active is False
        assert gesture._active is False
        # and it stays inert after a later successful generation
        vp.set_renderer(MockRendererAdapter())
        gesture._on_began()
        assert model._drag_active is False

    def test_teardown_interrupt_preserved_after_terminal_safety(self):
        from types import SimpleNamespace

        vp = self._viewport()
        sv = SimpleNamespace(destroy=lambda: None)
        tools = SimpleNamespace(destroy=lambda: None)
        vp._scene_view = sv
        vp._tool_registry = tools

        class _Interrupting:
            def __init__(self):
                self.fired = False

            def cancel(self):
                if not self.fired:
                    self.fired = True
                    raise KeyboardInterrupt()

        vp._bus_sub = _Interrupting()
        with pytest.raises(KeyboardInterrupt):
            vp._destroy_surface_resources()
        # the interrupt escaped only AFTER terminal safety: everything
        # was still detached and the state is genuinely terminal
        assert vp.lifecycle_state == "destroyed"
        assert vp._scene_view is None
        assert vp._tool_registry is None
        assert vp._renderer is None
        # repeated teardown after the interrupt is safe
        vp._destroy_surface_resources()
        assert vp.lifecycle_state == "destroyed"


class TestGenerationTransaction:
    """Round 12: generations are transactional — born unpublished,
    atomically published, revoked before any native shutdown — and
    renderer installation reports an explicit ownership result."""

    def _framed(self, vp):
        vp._window = SimpleNamespace(frame=SimpleNamespace(rebuild=lambda: None))
        vp._image = SimpleNamespace(visible=True)

    def _built(self, renderer=None):
        vp = ViewportWidget(
            services=None, renderer=renderer or MockRendererAdapter()
        )
        self._framed(vp)
        _build_or_xfail_unsupported(vp)
        return vp

    def test_usable_requires_current_pick_manager(self):
        vp = self._built()
        assert vp.lifecycle_state == "usable"
        vp._pick_manager = None
        assert vp.lifecycle_state == "unavailable"

    def test_usable_requires_current_manipulator(self):
        vp = self._built()
        vp._transform_manipulator = None
        assert vp.lifecycle_state == "unavailable"

    def test_failed_build_disposes_partials_and_keeps_callbacks_inert(self):
        import ovui_widgets.viewport.viewport_widget as viewport_mod

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        self._framed(vp)
        created = []
        real_pick = viewport_mod.PickGesture

        class RecordingPick(real_pick):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self)

        def exploding_registry(*args, **kwargs):
            raise RuntimeError("late build failure")

        real_registry = viewport_mod.ToolRegistry
        viewport_mod.PickGesture = RecordingPick
        viewport_mod.ToolRegistry = exploding_registry
        try:
            with pytest.raises(RuntimeError) as excinfo:
                vp._build_ui()
        finally:
            viewport_mod.PickGesture = real_pick
            viewport_mod.ToolRegistry = real_registry
        assert "late build failure" in str(excinfo.value)
        # the failed transaction disposed every partial resource ...
        assert vp.lifecycle_state == "unavailable"
        assert vp._scene_view is None
        assert vp._pick_manager is None
        assert vp._tool_registry is None
        # ... and the callbacks it created never became live
        assert created
        fired = []
        for g in created:
            g._callback = lambda *a: fired.append(a)
            g._start_x = 0.0
            g._start_y = 0.0
            g._process_ended(0.0005, 0.0005)
        assert fired == []

    def test_outgoing_generation_revoked_before_native_shutdown(self):
        vp = self._built()
        token = vp._live_generation
        seen = []
        old = vp._renderer
        old.shutdown = lambda: seen.append(token.alive)
        vp._transform_model.set_renderer(old)
        assert vp.set_renderer(MockRendererAdapter()) is True
        assert seen == [False]

    def test_ownership_result_false_when_both_shutdowns_fail(self):
        vp = self._built()
        old = vp._renderer

        def _raise():
            raise RuntimeError("shutdown failed")

        old.shutdown = _raise
        vp._transform_model.set_renderer(old)
        incoming = MockRendererAdapter()
        incoming.shutdown = _raise
        assert vp.set_renderer(incoming) is False
        # the possibly-live predecessor holds the single debt slot; the
        # refused incoming stays caller-owned via the False result
        assert vp.unresolved_predecessor is old
        assert vp._renderer is None

    def test_shut_down_predecessor_is_never_republished(self):
        vp = self._built()
        old = vp._renderer
        calls = {"n": 0}

        def _fail_once():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("shutdown failed once")

        old.shutdown = _fail_once
        vp._transform_model.set_renderer(old)
        vp.set_renderer(MockRendererAdapter())
        assert vp.unresolved_predecessor is old
        # offering the same object again first resolves it as the
        # predecessor (retry succeeds) — a renderer known to be shut
        # down must not be published
        assert vp.set_renderer(old) is False
        assert calls["n"] == 2
        assert vp._renderer is not old
        assert vp.unresolved_predecessor is None


    def test_usable_requires_current_camera_manipulator(self):
        vp = self._built()
        vp._camera_manipulator = None
        assert vp.lifecycle_state == "unavailable"

    def test_usable_requires_current_tool_registry(self):
        vp = self._built()
        vp._tool_registry = None
        assert vp.lifecycle_state == "unavailable"

    def test_destroyed_scene_view_reference_is_unavailable(self):
        vp = self._built()
        vp._scene_view.destroy()
        assert vp.lifecycle_state == "unavailable"

    def test_destroyed_tool_registry_reference_is_unavailable(self):
        vp = self._built()
        vp._tool_registry.destroy()
        assert vp.lifecycle_state == "unavailable"

    def test_gesture_ownership_is_explicit_at_construction(self):
        # A gesture constructed WITHOUT a generation owns itself and is
        # live (standalone/public contract); one built with a not-yet-
        # published generation is inert until publication.
        fired = []
        standalone = PickGesture(callback=lambda x, y: fired.append("solo"))
        standalone._start_x = standalone._start_y = 0.0
        standalone._process_ended(0.0005, 0.0005)
        assert fired == ["solo"]
        import ovui_widgets.viewport.viewport_widget as viewport_mod

        token = viewport_mod._Generation(None)  # born unpublished
        owned = PickGesture(
            callback=lambda x, y: fired.append("owned"), generation=token
        )
        owned._start_x = owned._start_y = 0.0
        owned._process_ended(0.0005, 0.0005)
        assert fired == ["solo"]
        token.alive = True
        owned._process_ended(0.0005, 0.0005)
        assert fired == ["solo", "owned"]


    def test_built_callbacks_inert_once_unavailable(self):
        import ovui_widgets.viewport.viewport_widget as viewport_mod

        created = []
        real_pick = viewport_mod.PickGesture

        class RecordingPick(real_pick):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created.append(self)

        viewport_mod.PickGesture = RecordingPick
        try:
            vp = self._built()
        finally:
            viewport_mod.PickGesture = real_pick
        vp._scene_view.destroy()
        assert vp.lifecycle_state == "unavailable"
        fired = []
        g = created[0]
        g._callback = lambda *a: fired.append(a)
        g._start_x = g._start_y = 0.0
        g._process_ended(0.0001, 0.0001)
        assert fired == []

    def test_hover_gestures_carry_the_generation(self):
        vp = self._built()
        m = vp._transform_manipulator
        hovers = [*m._translate_hovers, *m._rotate_hovers,
                  *m._scale_hovers, m._uniform_scale_hover]
        token = vp._live_generation
        assert hovers and all(h._generation is token for h in hovers)

    def test_supported_scene_view_destruction_boundary(self):
        # The supported destruction routes are owner-mediated: the
        # owner revokes the generation BEFORE any native destroy runs,
        # and the handed-out object's Python destroy() is observable
        # (marker set before super(), so raising/repeated destroy stay
        # safe). Direct base-class destroy bypass is out of contract.
        vp = self._built()
        token = vp._live_generation
        order = []
        sv = vp._scene_view
        real_destroy = type(sv).destroy

        def observing(self_sv):
            order.append(("token_alive_at_destroy", token.alive))
            real_destroy(self_sv)

        type(sv).destroy = observing
        try:
            vp.set_renderer(MockRendererAdapter())
        finally:
            type(sv).destroy = real_destroy
        assert order == [("token_alive_at_destroy", False)]
        # observable Python destroy on a retained reference
        vp2 = self._built()
        sv2 = vp2._scene_view
        sv2.destroy()
        sv2.destroy()  # repeated destroy stays safe
        assert sv2.destroyed is True
        assert vp2.lifecycle_state == "unavailable"
