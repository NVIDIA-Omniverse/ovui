# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for UsdStageAdapter — hierarchy traversal (Step 22).

All tests skip gracefully when pxr (OpenUSD) is not available.
"""

import pytest

try:
    from pxr import Gf, Sdf, Usd, UsdGeom
    try:
        from pxr import UsdRender
        HAS_USD_RENDER = True
    except ImportError:
        HAS_USD_RENDER = False
    HAS_USD = True
except ImportError:
    HAS_USD = False
    HAS_USD_RENDER = False

pytestmark = pytest.mark.skipif(not HAS_USD, reason="pxr (OpenUSD) not available")

from ovui_data_adapters.common import (
    BadgeFlags,
    ItemFlags,
    StageChoice,
    VisibilityState,
)
from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_stage():
    return Usd.Stage.CreateInMemory()


@pytest.fixture
def simple_stage():
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Mesh.Define(stage, "/World/Cube")
    UsdGeom.Camera.Define(stage, "/World/Camera")
    return stage


@pytest.fixture
def nested_stage():
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/Root")
    UsdGeom.Xform.Define(stage, "/Root/Child")
    UsdGeom.Xform.Define(stage, "/Root/Child/Grandchild")
    UsdGeom.Mesh.Define(stage, "/Root/Child/GrandchildMesh")
    return stage


@pytest.fixture
def adapter(simple_stage):
    return UsdStageAdapter(simple_stage)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_wraps_stage(self, simple_stage):
        a = UsdStageAdapter(simple_stage)
        assert a._stage is simple_stage

    def test_undo_manager_optional(self, simple_stage):
        a = UsdStageAdapter(simple_stage)
        assert a._undo_manager is None

    def test_undo_manager_stored(self, simple_stage):
        sentinel = object()
        a = UsdStageAdapter(simple_stage, undo_manager=sentinel)
        assert a._undo_manager is sentinel


# ---------------------------------------------------------------------------
# get_root
# ---------------------------------------------------------------------------

class TestGetRoot:
    def test_returns_pseudo_root(self, adapter, simple_stage):
        root = adapter.get_root()
        assert root == simple_stage.GetPseudoRoot()

    def test_pseudo_root_path_is_slash(self, adapter):
        root = adapter.get_root()
        assert str(root.GetPath()) == "/"

    def test_empty_stage_root(self, empty_stage):
        a = UsdStageAdapter(empty_stage)
        root = a.get_root()
        assert root is not None


# ---------------------------------------------------------------------------
# get_children
# ---------------------------------------------------------------------------

class TestGetChildren:
    def test_root_children(self, adapter):
        root = adapter.get_root()
        children = adapter.get_children(root)
        names = [c.GetName() for c in children]
        assert "World" in names

    def test_world_children(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        children = adapter.get_children(world)
        names = [c.GetName() for c in children]
        assert "Cube" in names
        assert "Camera" in names

    def test_returns_list(self, adapter):
        root = adapter.get_root()
        result = adapter.get_children(root)
        assert isinstance(result, list)

    def test_leaf_has_no_children(self, adapter, simple_stage):
        cube = simple_stage.GetPrimAtPath("/World/Cube")
        assert adapter.get_children(cube) == []

    def test_empty_stage_root_has_no_children(self, empty_stage):
        a = UsdStageAdapter(empty_stage)
        root = a.get_root()
        assert adapter.get_children(root) == [] if False else a.get_children(root) == []


# ---------------------------------------------------------------------------
# get_display_name
# ---------------------------------------------------------------------------

class TestGetDisplayName:
    def test_prim_name(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        assert adapter.get_display_name(world) == "World"

    def test_child_name(self, adapter, simple_stage):
        cube = simple_stage.GetPrimAtPath("/World/Cube")
        assert adapter.get_display_name(cube) == "Cube"

    def test_pseudo_root_returns_slash(self, adapter):
        root = adapter.get_root()
        assert adapter.get_display_name(root) == "/"


# ---------------------------------------------------------------------------
# get_type_name
# ---------------------------------------------------------------------------

class TestGetTypeName:
    def test_xform_type(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        assert adapter.get_type_name(world) == "Xform"

    def test_mesh_type(self, adapter, simple_stage):
        cube = simple_stage.GetPrimAtPath("/World/Cube")
        assert adapter.get_type_name(cube) == "Mesh"

    def test_camera_type(self, adapter, simple_stage):
        cam = simple_stage.GetPrimAtPath("/World/Camera")
        assert adapter.get_type_name(cam) == "Camera"

    def test_untyped_def_prim_returns_empty(self, simple_stage):
        # A ``def`` prim with no typeName has no USD schema type — render
        # blank in the Type column, not the speculative "Class" label which
        # is reserved for actual class specifiers.
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/Untyped")
        a = UsdStageAdapter(stage)
        prim = stage.GetPrimAtPath("/Untyped")
        assert a.get_type_name(prim) == ""

    def test_class_prim_returns_class(self):
        stage = Usd.Stage.CreateInMemory()
        proto = stage.CreateClassPrim("/Proto")
        a = UsdStageAdapter(stage)
        assert a.get_type_name(proto) == "Class"

    def test_over_prim_returns_empty(self):
        stage = Usd.Stage.CreateInMemory()
        stage.OverridePrim("/Foo")
        a = UsdStageAdapter(stage)
        prim = stage.GetPrimAtPath("/Foo")
        assert a.get_type_name(prim) == ""

    def test_pseudo_root_returns_empty(self, simple_stage):
        a = UsdStageAdapter(simple_stage)
        assert a.get_type_name(a.get_root()) == ""


class TestGetTypeCategory:
    def test_mesh_category(self, adapter, simple_stage):
        cube = simple_stage.GetPrimAtPath("/World/Cube")
        assert adapter.get_type_category(cube) == "Mesh"

    def test_camera_category(self, adapter, simple_stage):
        cam = simple_stage.GetPrimAtPath("/World/Camera")
        assert adapter.get_type_category(cam) == "Camera"

    def test_xform_category(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        assert adapter.get_type_category(world) == "Xform"

    def test_untyped_prim_returns_other(self):
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/Untyped")
        a = UsdStageAdapter(stage)
        prim = stage.GetPrimAtPath("/Untyped")
        assert a.get_type_category(prim) == "Other"


# ---------------------------------------------------------------------------
# get_item_path
# ---------------------------------------------------------------------------

class TestGetItemPath:
    def test_root_path(self, adapter):
        root = adapter.get_root()
        assert adapter.get_item_path(root) == "/"

    def test_prim_path(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        assert adapter.get_item_path(world) == "/World"

    def test_nested_path(self, adapter, simple_stage):
        cube = simple_stage.GetPrimAtPath("/World/Cube")
        assert adapter.get_item_path(cube) == "/World/Cube"

    def test_returns_string(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        assert isinstance(adapter.get_item_path(world), str)


# ---------------------------------------------------------------------------
# get_item_at_path
# ---------------------------------------------------------------------------

class TestGetItemAtPath:
    def test_valid_path(self, adapter):
        prim = adapter.get_item_at_path("/World")
        assert prim is not None
        assert prim.GetName() == "World"

    def test_invalid_path_returns_none(self, adapter):
        assert adapter.get_item_at_path("/DoesNotExist") is None

    def test_nested_path(self, adapter):
        prim = adapter.get_item_at_path("/World/Cube")
        assert prim is not None
        assert prim.GetName() == "Cube"


# ---------------------------------------------------------------------------
# Nested hierarchy traversal
# ---------------------------------------------------------------------------

class TestNestedHierarchy:
    def test_traverse_three_levels(self, nested_stage):
        a = UsdStageAdapter(nested_stage)
        root = a.get_root()
        top_children = a.get_children(root)
        assert any(c.GetName() == "Root" for c in top_children)

        root_prim = nested_stage.GetPrimAtPath("/Root")
        level1 = a.get_children(root_prim)
        assert any(c.GetName() == "Child" for c in level1)

        child_prim = nested_stage.GetPrimAtPath("/Root/Child")
        level2 = a.get_children(child_prim)
        names = [c.GetName() for c in level2]
        assert "Grandchild" in names
        assert "GrandchildMesh" in names

    def test_path_consistency(self, nested_stage):
        a = UsdStageAdapter(nested_stage)
        prim = nested_stage.GetPrimAtPath("/Root/Child/Grandchild")
        assert a.get_item_path(prim) == "/Root/Child/Grandchild"

    def test_display_name_at_each_level(self, nested_stage):
        a = UsdStageAdapter(nested_stage)
        for path, expected in [
            ("/Root", "Root"),
            ("/Root/Child", "Child"),
            ("/Root/Child/Grandchild", "Grandchild"),
        ]:
            prim = nested_stage.GetPrimAtPath(path)
            assert a.get_display_name(prim) == expected


# ---------------------------------------------------------------------------
# Empty stage
# ---------------------------------------------------------------------------

class TestEmptyStage:
    def test_root_has_no_children(self, empty_stage):
        a = UsdStageAdapter(empty_stage)
        root = a.get_root()
        assert a.get_children(root) == []

    def test_root_display_name_is_slash(self, empty_stage):
        a = UsdStageAdapter(empty_stage)
        assert a.get_display_name(a.get_root()) == "/"

    def test_selector_lists_are_empty(self, empty_stage):
        a = UsdStageAdapter(empty_stage)
        assert a.list_cameras() == []
        assert a.list_render_products() == []


class TestViewportSelectors:
    def test_list_cameras_returns_nested_camera_choices(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Camera.Define(stage, "/World/MainCamera")
        UsdGeom.Xform.Define(stage, "/World/Rig")
        UsdGeom.Camera.Define(stage, "/World/Rig/ShotCamera")
        UsdGeom.Mesh.Define(stage, "/World/Mesh")

        choices = UsdStageAdapter(stage).list_cameras()

        assert choices == [
            StageChoice("/World/MainCamera", "/World/MainCamera"),
            StageChoice("/World/Rig/ShotCamera", "/World/Rig/ShotCamera"),
        ]

    def test_read_camera_pose_returns_pose_for_camera_path(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera = UsdGeom.Camera.Define(stage, "/World/MainCamera")
        xformable = UsdGeom.Xformable(camera.GetPrim())
        xformable.AddTranslateOp().Set(Gf.Vec3d(2.0, 3.0, 10.0))
        coi_attr = camera.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest", Sdf.ValueTypeNames.Vector3d
        )
        coi_attr.Set(Gf.Vec3d(0.0, 0.0, -5.0))

        pose = UsdStageAdapter(stage).read_camera_pose("/World/MainCamera")

        assert pose is not None
        assert pose.eye == pytest.approx((2.0, 3.0, 10.0))
        assert pose.target == pytest.approx((2.0, 3.0, 5.0))
        assert pose.prim_path == "/World/MainCamera"

    def test_read_camera_pose_returns_none_for_invalid_or_non_camera_path(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Xform.Define(stage, "/World/NotACamera")
        adapter = UsdStageAdapter(stage)

        assert adapter.read_camera_pose("/World/Missing") is None
        assert adapter.read_camera_pose("/World/NotACamera") is None

    def test_write_camera_pose_authors_parent_relative_pose(self):
        from ovwidgets.viewport.camera_controller import CameraController

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        world = UsdGeom.Xform.Define(stage, "/World")
        world.AddTranslateOp().Set(Gf.Vec3d(100.0, 0.0, 0.0))
        camera = UsdGeom.Camera.Define(stage, "/World/Camera")
        camera.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, 0.0, -10.0))

        controller = CameraController()
        controller.focus(target=[3.0, 2.0, -1.0], distance=20.0)
        controller.orbit(0.4, 0.2)
        view, proj = controller.get_matrices(640, 360)

        adapter = UsdStageAdapter(stage)
        assert adapter.write_camera_pose_from_matrices(
            "/World/Camera",
            view,
            proj,
            640,
            360,
            tuple(controller.state.target),
        )

        pose = adapter.read_camera_pose("/World/Camera")
        assert pose is not None
        assert pose.eye == pytest.approx(
            tuple(float(v) for v in controller._get_eye()),
            rel=1e-5,
            abs=1e-5,
        )
        assert pose.target == pytest.approx((3.0, 2.0, -1.0))
        local_translation = UsdGeom.Xformable(
            camera.GetPrim()
        ).GetLocalTransformation().ExtractTranslation()
        assert float(local_translation[0]) != pytest.approx(float(pose.eye[0]))
        assert float(local_translation[0]) == pytest.approx(
            float(pose.eye[0]) - 100.0,
            rel=1e-5,
            abs=1e-5,
        )

    def test_write_camera_pose_creates_single_undo_entry(self):
        from ovwidgets.common.undo import UndoManager
        from ovwidgets.viewport.camera_controller import CameraController

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera = UsdGeom.Camera.Define(stage, "/World/Camera")
        xformable = UsdGeom.Xformable(camera.GetPrim())
        xformable.AddTranslateOp().Set(Gf.Vec3d(0.0, 3.0, 12.0))
        camera.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, -3.0, -12.0))

        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        controller = CameraController()
        controller.focus(target=[1.0, 2.0, 3.0], distance=20.0)
        controller.orbit(0.4, 0.2)
        view, proj = controller.get_matrices(640, 360)

        assert adapter.write_camera_pose_from_matrices(
            "/World/Camera",
            view,
            proj,
            640,
            360,
            tuple(controller.state.target),
        )

        assert len(undo._undo_stack) == 1
        assert undo.can_undo() is True
        assert undo.can_redo() is False

    def test_write_camera_pose_undo_redo_restores_pose_and_authored_stack(self):
        from ovwidgets.common.undo import UndoManager
        from ovwidgets.viewport.camera_controller import CameraController

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.Xform.Define(stage, "/World")
        camera = UsdGeom.Camera.Define(stage, "/World/Camera")
        xformable = UsdGeom.Xformable(camera.GetPrim())
        xformable.AddTranslateOp().Set(Gf.Vec3d(0.0, 3.0, 12.0))
        camera.GetPrim().CreateAttribute(
            "omni:kit:centerOfInterest",
            Sdf.ValueTypeNames.Double3,
        ).Set(Gf.Vec3d(0.0, -3.0, -12.0))
        initial_pose = UsdStageAdapter(stage).read_camera_pose("/World/Camera")
        initial_properties = set(
            stage.GetEditTarget().GetLayer()
            .GetPrimAtPath("/World/Camera")
            .properties.keys()
        )

        undo = UndoManager()
        adapter = UsdStageAdapter(stage, undo_manager=undo)
        controller = CameraController()
        controller.focus(target=[1.0, 2.0, 3.0], distance=20.0)
        controller.orbit(0.4, 0.2)
        view, proj = controller.get_matrices(640, 360)
        assert adapter.write_camera_pose_from_matrices(
            "/World/Camera",
            view,
            proj,
            640,
            360,
            tuple(controller.state.target),
        )
        written_pose = adapter.read_camera_pose("/World/Camera")
        written_properties = set(
            stage.GetEditTarget().GetLayer()
            .GetPrimAtPath("/World/Camera")
            .properties.keys()
        )

        assert written_pose.eye != pytest.approx(initial_pose.eye)
        assert "xformOp:transform" in written_properties

        assert undo.undo() is True
        restored_pose = adapter.read_camera_pose("/World/Camera")
        restored_properties = set(
            stage.GetEditTarget().GetLayer()
            .GetPrimAtPath("/World/Camera")
            .properties.keys()
        )
        assert restored_pose.eye == pytest.approx(initial_pose.eye, rel=1e-5, abs=1e-5)
        assert restored_pose.target == pytest.approx(
            initial_pose.target,
            rel=1e-5,
            abs=1e-5,
        )
        assert restored_properties == initial_properties

        assert undo.redo() is True
        redone_pose = adapter.read_camera_pose("/World/Camera")
        assert redone_pose.eye == pytest.approx(written_pose.eye, rel=1e-5, abs=1e-5)
        assert redone_pose.target == pytest.approx(
            written_pose.target,
            rel=1e-5,
            abs=1e-5,
        )

    def test_list_render_products_returns_product_choices(self):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Scope.Define(stage, "/Render")
        UsdRender.Product.Define(stage, "/Render/Beauty")
        UsdGeom.Scope.Define(stage, "/Render/Nested")
        UsdRender.Product.Define(stage, "/Render/Nested/Viewport")
        UsdRender.Var.Define(stage, "/Render/LdrColor")

        choices = UsdStageAdapter(stage).list_render_products()

        assert choices == [
            StageChoice("/Render/Beauty", "/Render/Beauty"),
            StageChoice("/Render/Nested/Viewport", "/Render/Nested/Viewport"),
        ]


# ---------------------------------------------------------------------------
# Other ABC methods (stubs / no-crash)
# ---------------------------------------------------------------------------

class TestStubMethods:
    def test_can_have_children(self, adapter, simple_stage):
        cube = simple_stage.GetPrimAtPath("/World/Cube")
        assert adapter.can_have_children(cube) is True

    def test_get_icon_name_mesh(self, adapter, simple_stage):
        cube = simple_stage.GetPrimAtPath("/World/Cube")
        assert adapter.get_icon_name(cube) == "Mesh"

    def test_get_icon_name_camera(self, adapter, simple_stage):
        cam = simple_stage.GetPrimAtPath("/World/Camera")
        assert adapter.get_icon_name(cam) == "Camera"

    def test_get_icon_name_xform(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        assert adapter.get_icon_name(world) == "Xform"

    def test_get_icon_name_unknown_returns_prim(self, simple_stage):
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/Untyped")
        a = UsdStageAdapter(stage)
        prim = stage.GetPrimAtPath("/Untyped")
        assert a.get_icon_name(prim) == "Prim"

    def test_get_badge_flags(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        flags = adapter.get_badge_flags(world)
        assert isinstance(flags, BadgeFlags)
        assert flags == BadgeFlags.NONE

    def test_get_item_flags(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        assert adapter.get_item_flags(world) == ItemFlags.NONE

    def test_compute_visibility_returns_visible(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        assert adapter.compute_visibility(world) == VisibilityState.VISIBLE

    def test_can_rename_returns_true_for_normal_prim(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        assert adapter.can_rename(world) is True

    def test_can_rename_returns_false_for_pseudo_root(self, adapter, simple_stage):
        pseudo_root = simple_stage.GetPseudoRoot()
        assert adapter.can_rename(pseudo_root) is False

    def test_can_reparent_returns_false(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        assert adapter.can_reparent([world], world) is False

    def test_normalize_name(self, adapter):
        assert adapter.normalize_name("hello world!") == "hello_world_"

    def test_filter_items(self, adapter, simple_stage):
        world = simple_stage.GetPrimAtPath("/World")
        children = adapter.get_children(world)
        meshes = adapter.filter_items(children, lambda p: adapter.get_type_name(p) == "Mesh")
        assert all(adapter.get_type_name(p) == "Mesh" for p in meshes)

    def test_subscribe_changes_returns_subscription(self, adapter):
        # Step 13: UsdStageAdapter.subscribe_changes now returns a private
        # _StageSubscription that satisfies SubscriptionProtocol — the moved
        # openusd file no longer depends on ovwidgets.common.settings.Subscription.
        from ovui_data_adapters.common import SubscriptionProtocol
        sub = adapter.subscribe_changes(lambda e: None)
        assert isinstance(sub, SubscriptionProtocol)

    def test_suppress_change_notifications_no_crash(self, adapter):
        with adapter.suppress_change_notifications():
            pass

    def test_begin_end_undo_group_no_crash(self, adapter):
        adapter.begin_undo_group("test")
        adapter.end_undo_group()
