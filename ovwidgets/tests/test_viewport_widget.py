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

import numpy as np
import omni.ui as ui
import pytest
from ovui_data_adapters.common import (
    VIEWPORT_CAMERA_POSE_SOURCE,
    BoundCameraPose,
    StageChoice,
)

from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.viewport.camera_navigation_state import CameraNavigationState
from ovwidgets.viewport.image_bridge import ImageBridge
from ovwidgets.viewport.viewport_widget import ViewportWidget


class _FakeCameraStageAdapter:
    def __init__(self, choices=(), poses=None, render_products=()):
        self.choices = tuple(choices)
        self.poses = dict(poses or {})
        self.render_products = tuple(render_products)
        self.read_paths = []

    def list_cameras(self):
        return list(self.choices)

    def read_camera_pose(self, path):
        self.read_paths.append(path)
        return self.poses.get(path)

    def list_render_products(self):
        return list(self.render_products)


class _FakeRenderProductRenderer(MockRendererAdapter):
    def __init__(self, active_path=None, *, accept=True):
        super().__init__()
        self.active_path = active_path
        self.accept = accept
        self.set_paths = []

    def get_active_render_product_path(self):
        return self.active_path

    def set_active_render_product_path(self, path):
        self.set_paths.append(path)
        if not self.accept:
            return False
        self.active_path = path
        return True


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
        self.shown_at = None
        self.destroyed = False
        self.hidden = False
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
            _FakeCameraMenu.stack[-1].items.append(self)

    def trigger(self):
        fn = self.kwargs.get("triggered_fn")
        if fn is not None:
            return fn()
        return None


class _VisibleViewportImage:
    visible = True
    computed_width = 640
    computed_height = 360


def _make_renderable_viewport() -> ViewportWidget:
    vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
    vp._image = _VisibleViewportImage()
    return vp


@pytest.fixture
def fake_camera_menu(monkeypatch):
    import ovwidgets.viewport.viewport_widget as viewport_mod

    _FakeCameraMenu.stack = []
    _FakeCameraMenu.instances = []
    monkeypatch.setattr(viewport_mod.ui, "Menu", _FakeCameraMenu)
    monkeypatch.setattr(viewport_mod.ui, "MenuItem", _FakeCameraMenuItem)
    return _FakeCameraMenu


class TestViewportWidgetCreation:
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


class TestViewportSelectionHighlightExpansion:
    def _make_viewport(self):
        from ovwidgets.common.selection import SelectionBus

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


class TestViewportWidgetLayout:
    def test_image_widget_created_after_build(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)
        vp._build_ui()
        assert vp._image is not None
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
        import ovwidgets.viewport.viewport_widget as viewport_mod
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

class TestViewportToolbar:
    def test_toolbar_contains_transform_tools_and_selector_buttons(self):
        from ovwidgets.viewport.transform_manipulator import (
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
            "render_product",
        )
        assert "select" not in vp._toolbar_buttons
        assert "shade" not in vp._toolbar_buttons
        vp.destroy()

    def test_toolbar_buttons_are_icon_buttons(self, monkeypatch):
        import ovwidgets.viewport.viewport_widget as viewport_mod

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
        assert all(kwargs.get("width") == vp.TOOLBAR_BUTTON_SIZE for kwargs in seen_buttons)
        assert all(kwargs.get("height") == vp.TOOLBAR_BUTTON_SIZE for kwargs in seen_buttons)
        assert all(kwargs.get("tooltip") for kwargs in seen_buttons)
        assert all(kwargs.get("enabled") is False for _, kwargs in seen_icons)
        assert all(kwargs.get("opaque_for_mouse_events") is False for _, kwargs in seen_icons)
        vp.destroy()

    def test_toolbar_button_stacks_clip_scene_view_clicks(self, monkeypatch):
        import ovwidgets.viewport.viewport_widget as viewport_mod

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
        from ovwidgets.viewport.transform_manipulator import TOOL_ROTATE, TOOL_TRANSLATE

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
        from ovwidgets.viewport.transform_manipulator import TOOL_TRANSLATE

        vp = ViewportWidget(services=None, renderer=MockRendererAdapter())
        vp._build_ui()
        vp._toolbar_button_backgrounds[TOOL_TRANSLATE].name = ""
        vp._on_toolbar_tool_clicked(TOOL_TRANSLATE)
        assert vp._toolbar_button_backgrounds[TOOL_TRANSLATE].name == "active"
        assert vp._tool_registry.active_tool == TOOL_TRANSLATE
        vp.destroy()

    def test_toolbar_state_tracks_settings_changes_from_menu_or_hotkey(self):
        from types import SimpleNamespace

        from ovwidgets.common.selection import SelectionBus
        from ovwidgets.common.settings import Settings
        from ovwidgets.viewport.manipulator_registry import ACTIVE_TOOL_SETTING
        from ovwidgets.viewport.transform_manipulator import TOOL_ROTATE, TOOL_SCALE

        app = SimpleNamespace(settings=Settings(), selection_bus=SelectionBus())
        vp = ViewportWidget(services=app, renderer=MockRendererAdapter())
        vp._build_ui()
        app.settings.set(ACTIVE_TOOL_SETTING, TOOL_SCALE)
        assert vp._tool_registry.active_tool == TOOL_SCALE
        assert vp._transform_manipulator.tool == TOOL_SCALE
        assert vp._toolbar_button_backgrounds[TOOL_SCALE].name == "active"
        assert vp._toolbar_button_backgrounds[TOOL_ROTATE].name == ""
        assert vp._toolbar_button_backgrounds["camera"].name == ""
        assert vp._toolbar_button_backgrounds["render_product"].name == ""
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
        assert vp._camera.fov_degrees == pytest.approx(60.0)

        menu = vp._show_camera_menu_at(0, 0)
        assert menu.items[0].label == "Main Camera"
        assert menu.items[0].kwargs.get("checked") is True
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

    def test_render_product_menu_uses_shared_flat_menu_and_lists_stage_products(
        self, fake_camera_menu
    ):
        choices = (
            StageChoice("/Render/Beauty", "Beauty"),
            StageChoice("/Render/Preview", "Preview"),
        )
        adapter = _FakeCameraStageAdapter(render_products=choices)
        renderer = _FakeRenderProductRenderer(active_path="/Render/Beauty")
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            stage_adapter_provider=lambda: adapter,
        )
        menu = vp._show_render_product_menu_at(23, 31)
        assert isinstance(menu, fake_camera_menu)
        assert menu.title == "Render Product"
        assert "delegate" in menu.kwargs
        assert menu.shown_at == (23.0, 31.0)
        assert [item.label for item in menu.items] == [
            "Active: /Render/Beauty",
            "Beauty",
            "Preview",
        ]
        assert menu.items[0].kwargs.get("enabled") is False
        product_items = menu.items[1:]
        assert all(item.kwargs.get("checkable") is True for item in product_items)
        assert [item.kwargs.get("checked") for item in product_items] == [True, False]
        assert all(callable(item.kwargs.get("triggered_fn")) for item in product_items)
        vp.destroy()

    def test_render_product_menu_empty_state_is_disabled_item(self, fake_camera_menu):
        adapter = _FakeCameraStageAdapter()
        vp = ViewportWidget(
            services=None,
            renderer=_FakeRenderProductRenderer(),
            stage_adapter_provider=lambda: adapter,
        )
        menu = vp._show_render_product_menu_at(0, 0)
        assert [item.label for item in menu.items] == ["(no render products)"]
        assert menu.items[0].kwargs.get("enabled") is False
        assert "triggered_fn" not in menu.items[0].kwargs
        vp.destroy()

    def test_render_product_menu_selection_sets_renderer_active_product(
        self, fake_camera_menu
    ):
        adapter = _FakeCameraStageAdapter(
            render_products=(StageChoice("/Render/Beauty", "Beauty"),),
        )
        renderer = _FakeRenderProductRenderer()
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            stage_adapter_provider=lambda: adapter,
        )
        menu = vp._show_render_product_menu_at(0, 0)
        assert menu.items[0].trigger() is True
        assert renderer.set_paths == ["/Render/Beauty"]
        assert renderer.active_path == "/Render/Beauty"
        assert vp._active_render_product_path == "/Render/Beauty"

        menu = vp._show_render_product_menu_at(0, 0)
        assert [item.label for item in menu.items] == [
            "Active: /Render/Beauty",
            "Beauty",
        ]
        assert menu.items[1].kwargs.get("checked") is True
        vp.destroy()

    def test_render_product_selection_rejects_empty_or_unsupported_paths(self):
        renderer = _FakeRenderProductRenderer(accept=False)
        vp = ViewportWidget(services=None, renderer=renderer)
        assert vp._select_render_product_path("") is False
        assert renderer.set_paths == []
        assert vp._select_render_product_path("/Render/Beauty") is False
        assert renderer.set_paths == ["/Render/Beauty"]
        assert vp._active_render_product_path is None
        vp.destroy()

    def test_render_product_menu_handles_stale_active_product_without_checking_choice(
        self, fake_camera_menu
    ):
        adapter = _FakeCameraStageAdapter(
            render_products=(StageChoice("/Render/Beauty", "Beauty"),),
        )
        renderer = _FakeRenderProductRenderer(active_path="/Render/Missing")
        vp = ViewportWidget(
            services=None,
            renderer=renderer,
            stage_adapter_provider=lambda: adapter,
        )
        menu = vp._show_render_product_menu_at(0, 0)
        assert [item.label for item in menu.items] == [
            "Active: /Render/Missing",
            "Beauty",
        ]
        assert menu.items[1].kwargs.get("checked") is False
        vp.destroy()

    def test_destroy_closes_render_product_menu(self, fake_camera_menu):
        adapter = _FakeCameraStageAdapter(
            render_products=(StageChoice("/Render/Beauty", "Beauty"),),
        )
        vp = ViewportWidget(
            services=None,
            renderer=_FakeRenderProductRenderer(),
            stage_adapter_provider=lambda: adapter,
        )
        menu = vp._show_render_product_menu_at(0, 0)
        vp.destroy()
        assert menu.destroyed is True

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

        from ovwidgets.common.undo import UndoManager

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

    def test_set_renderer_clears_cached_render_product_path(self):
        vp = ViewportWidget(
            services=None,
            renderer=_FakeRenderProductRenderer(active_path="/Render/Old"),
        )
        assert vp._select_render_product_path("/Render/Old") is True
        vp.set_renderer(MockRendererAdapter())
        assert vp._active_render_product_path is None
        vp.destroy()


class TestApplicationPrimCountWiring:
    def setup_method(self):
        from ovwidgets.app.application import Application
        from ovwidgets.common.selection import SelectionBus
        Application._instance = None
        SelectionBus._instance = None
        self.app = Application()

    def teardown_method(self):
        self.app.shutdown()
        from ovwidgets.app.application import Application
        from ovwidgets.common.selection import SelectionBus
        Application._instance = None
        SelectionBus._instance = None

    def test_get_prim_count_returns_zero_when_no_adapter(self):
        self.app._stage_adapter = None
        assert self.app._get_prim_count() == 0

    def test_get_prim_count_counts_mock_prims(self):
        from ovwidgets.common.testing.mock_stage import MockStageAdapter
        self.app._stage_adapter = MockStageAdapter()
        count = self.app._get_prim_count()
        # Default tree: World + Geometry + Ground + Sphere + Cube + Lights + DomeLight + Camera = 8
        assert count == 8

    def test_on_stage_changed_resync_calls_update_prim_count(self):
        from unittest.mock import MagicMock

        from ovui_data_adapters.common import ChangeEvent, ChangeEventType

        from ovwidgets.common.testing.mock_stage import MockStageAdapter
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

        from ovwidgets.common.testing.mock_stage import MockStageAdapter
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

        from ovwidgets.common.testing.mock_stage import MockStageAdapter
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

        from ovwidgets.common.testing.mock_stage import MockStageAdapter
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

        from ovwidgets.common.testing.mock_stage import MockStageAdapter
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
        pxr = pytest.importorskip("pxr", reason="pxr not available")
        Usd, UsdGeom = pxr.Usd, pxr.UsdGeom
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        viewport = MagicMock()
        self.app._viewport_window = viewport
        self.app._stage_window = None
        self.app._property_window = None
        monkeypatch.setattr(self.app, "_build_renderer_for_stage", lambda *a, **k: None)
        self.app.selection_bus.publish(["/OldStage/Cube"], source="test")
        self.app._load_stage(stage, title="unit_scene.usda")
        viewport.set_scene_name.assert_called_once_with("unit_scene.usda")
        viewport.attach_stage.assert_called_once()
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
        from ovwidgets.app.application import Application
        from ovwidgets.common.selection import SelectionBus
        Application._instance = None
        SelectionBus._instance = None
        self.app = Application()

    def teardown_method(self):
        self.app.shutdown()
        from ovwidgets.app.application import Application
        from ovwidgets.common.selection import SelectionBus
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

        from ovwidgets.common.testing.mock_stage import MockStageAdapter
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
