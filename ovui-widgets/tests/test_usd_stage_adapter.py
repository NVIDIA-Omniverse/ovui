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

from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from pxr import Gf, Sdf, Usd, UsdGeom
    try:
        from pxr import UsdShade
        HAS_USD_SHADE = True
    except ImportError:
        HAS_USD_SHADE = False
    try:
        from pxr import UsdRender
        HAS_USD_RENDER = True
    except ImportError:
        HAS_USD_RENDER = False
    HAS_USD = True
except ImportError:
    HAS_USD = False
    HAS_USD_RENDER = False
    HAS_USD_SHADE = False

pytestmark = pytest.mark.skipif(not HAS_USD, reason="pxr (OpenUSD) not available")

from ovui_data_adapters.common import (
    BadgeFlags,
    BindMaterialRequest,
    CoreMaterialBindingPolicy,
    CoreMaterialCatalog,
    CoreMaterialDescriptor,
    CoreMaterialErrorCode,
    CoreMaterialFamily,
    CoreMaterialGroupDescriptor,
    CoreMaterialKind,
    CoreMaterialRequirement,
    CoreMaterialWarning,
    CoreMaterialWarningSeverity,
    CreateActionCategory,
    CreateActionErrorCode,
    CreateActionRequirement,
    CreateBindingPolicy,
    CreateMaterialRequest,
    CreateRequest,
    ItemFlags,
    RenderTargetCatalog,
    RenderTargetKind,
    RenderTargetOutputKind,
    StageChoice,
    VisibilityState,
)
from ovui_data_adapters.openusd import stage_adapter as stage_mod
from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_stage():
    return Usd.Stage.CreateInMemory()


@pytest.fixture
def available_mdl_library(tmp_path, monkeypatch):
    """Expose the three Kit-named MDL modules to availability-sensitive tests."""
    for filename in ("OmniSurface.mdl", "OmniGlass.mdl", "OmniPBR.mdl"):
        (tmp_path / filename).write_text("// test MDL module\n", encoding="utf-8")
    monkeypatch.setenv("OVUI_MDL_LIBRARY_PATH", str(tmp_path))


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
    def _render_var(self, stage, path, source_name):
        var = UsdRender.Var.Define(stage, path)
        var.CreateSourceNameAttr().Set(source_name)
        return var

    def _render_product(
        self,
        stage,
        path,
        source_path=None,
        var_paths=None,
        resolution=(1280, 720),
    ):
        product = UsdRender.Product.Define(stage, path)
        if source_path is not None:
            product.CreateCameraRel().SetTargets([Sdf.Path(source_path)])
        if var_paths is not None:
            product.CreateOrderedVarsRel().SetTargets(
                [Sdf.Path(var_path) for var_path in var_paths]
            )
        if resolution is not None:
            product.CreateResolutionAttr().Set(Gf.Vec2i(*resolution))
        return product

    def _warning_codes(self, descriptor):
        return {warning.code for warning in descriptor.warnings}

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
        from ovui_widgets.viewport.camera_controller import CameraController

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
        from ovui_widgets.common.undo import UndoManager
        from ovui_widgets.viewport.camera_controller import CameraController

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
        from ovui_widgets.common.undo import UndoManager
        from ovui_widgets.viewport.camera_controller import CameraController

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

    def test_render_target_catalog_empty_when_no_render_products(self, empty_stage):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")

        catalog = UsdStageAdapter(empty_stage).get_render_target_catalog()

        assert catalog == RenderTargetCatalog()
        assert catalog.is_empty

    def test_render_target_catalog_camera_backed_image_product(self):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Camera.Define(stage, "/World/MainCamera")
        self._render_var(stage, "/Render/Vars/LdrColor", "LdrColor")
        self._render_product(
            stage,
            "/Render/Beauty",
            source_path="/World/MainCamera",
            var_paths=["/Render/Vars/LdrColor"],
            resolution=(1920, 1080),
        )

        catalog = UsdStageAdapter(stage).get_render_target_catalog()

        assert len(catalog.targets) == 1
        descriptor = catalog.targets[0]
        assert descriptor.target_id == "/Render/Beauty"
        assert descriptor.render_product_path == "/Render/Beauty"
        assert descriptor.display_name == "MainCamera"
        assert descriptor.kind is RenderTargetKind.CAMERA
        assert descriptor.source_path == "/World/MainCamera"
        assert descriptor.source_display_name == "MainCamera"
        assert descriptor.source_type == "Camera"
        assert descriptor.output_kind is RenderTargetOutputKind.IMAGE
        assert descriptor.output_names == ("LdrColor",)
        assert descriptor.resolution == (1920, 1080)
        assert descriptor.capabilities == (
            "image_render_target",
            "set_active_render_product",
        )
        assert descriptor.enabled
        assert descriptor.disabled_reason == ""
        assert descriptor.warnings == ()

    def test_render_target_catalog_sensor_backed_point_cloud_product(self):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        stage = Usd.Stage.CreateInMemory()
        stage.DefinePrim("/World/Lidar", "OmniLidar")
        self._render_var(stage, "/Render/Vars/PointCloud", "PointCloud")
        self._render_product(
            stage,
            "/Render/LidarProduct",
            source_path="/World/Lidar",
            var_paths=["/Render/Vars/PointCloud"],
            resolution=(1, 1),
        )

        descriptor = UsdStageAdapter(stage).get_render_target_catalog().targets[0]

        assert descriptor.kind is RenderTargetKind.SENSOR
        assert descriptor.source_path == "/World/Lidar"
        assert descriptor.source_display_name == "Lidar"
        assert descriptor.source_type == "OmniLidar"
        assert descriptor.output_kind is RenderTargetOutputKind.POINT_CLOUD
        assert descriptor.output_names == ("PointCloud",)
        assert descriptor.capabilities == ("point_cloud_output",)
        assert not descriptor.enabled
        assert (
            "PointCloud output requires point-cloud viewport support"
            in descriptor.disabled_reason
        )
        assert self._warning_codes(descriptor) == {"unsupported_output"}

    def test_multiple_render_targets_sample_catalog(self):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        sample_path = Path(__file__).parent / "data" / "multiple_render_targets.usda"
        stage = Usd.Stage.Open(str(sample_path))
        assert stage is not None

        catalog = UsdStageAdapter(stage).get_render_target_catalog()

        by_path = {target.render_product_path: target for target in catalog.targets}
        assert set(by_path) == {
            "/Render/Products/MainCamera",
            "/Render/Products/CloseupCamera",
            "/Render/Products/RoofLidar",
        }
        assert by_path["/Render/Products/MainCamera"].kind is RenderTargetKind.CAMERA
        assert by_path["/Render/Products/MainCamera"].source_path == "/World/Cameras/Main"
        assert by_path["/Render/Products/MainCamera"].resolution == (1280, 720)
        assert by_path["/Render/Products/CloseupCamera"].kind is RenderTargetKind.CAMERA
        assert by_path["/Render/Products/CloseupCamera"].source_path == "/World/Cameras/Closeup"
        assert by_path["/Render/Products/CloseupCamera"].resolution == (960, 540)
        lidar = by_path["/Render/Products/RoofLidar"]
        assert lidar.kind is RenderTargetKind.SENSOR
        assert lidar.source_path == "/World/RoofLidar/Sensor"
        assert lidar.output_kind is RenderTargetOutputKind.POINT_CLOUD
        assert not lidar.enabled
        assert "unsupported_output" in self._warning_codes(lidar)

    def test_render_target_catalog_missing_source_keeps_descriptor_with_warning(self):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        stage = Usd.Stage.CreateInMemory()
        self._render_var(stage, "/Render/Vars/LdrColor", "LdrColor")
        self._render_product(
            stage,
            "/Render/MissingSource",
            var_paths=["/Render/Vars/LdrColor"],
        )

        descriptor = UsdStageAdapter(stage).get_render_target_catalog().targets[0]

        assert descriptor.render_product_path == "/Render/MissingSource"
        assert descriptor.kind is RenderTargetKind.RENDER_PRODUCT
        assert descriptor.source_path is None
        assert descriptor.output_kind is RenderTargetOutputKind.IMAGE
        assert not descriptor.enabled
        assert (
            descriptor.disabled_reason
            == "RenderProduct has no valid source camera or sensor."
        )
        assert "missing_source" in self._warning_codes(descriptor)

    def test_render_target_catalog_invalid_source_path_is_disabled(self):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        stage = Usd.Stage.CreateInMemory()
        self._render_var(stage, "/Render/Vars/LdrColor", "LdrColor")
        self._render_product(
            stage,
            "/Render/InvalidSource",
            source_path="/World/MissingCamera",
            var_paths=["/Render/Vars/LdrColor"],
        )

        descriptor = UsdStageAdapter(stage).get_render_target_catalog().targets[0]

        assert descriptor.source_path == "/World/MissingCamera"
        assert not descriptor.enabled
        assert (
            descriptor.disabled_reason
            == "RenderProduct has no valid source camera or sensor."
        )
        assert "missing_source" in self._warning_codes(descriptor)

    def test_render_target_catalog_missing_resolution_warns_without_crashing(self):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Camera.Define(stage, "/World/MainCamera")
        self._render_var(stage, "/Render/Vars/LdrColor", "LdrColor")
        self._render_product(
            stage,
            "/Render/NoResolution",
            source_path="/World/MainCamera",
            var_paths=["/Render/Vars/LdrColor"],
            resolution=None,
        )

        descriptor = UsdStageAdapter(stage).get_render_target_catalog().targets[0]

        assert descriptor.output_kind is RenderTargetOutputKind.IMAGE
        assert descriptor.resolution is None
        assert descriptor.enabled
        assert "missing_resolution" in self._warning_codes(descriptor)

    def test_render_target_catalog_unknown_output_is_disabled(self):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Camera.Define(stage, "/World/MainCamera")
        self._render_var(stage, "/Render/Vars/WeirdBuffer", "WeirdBuffer")
        self._render_product(
            stage,
            "/Render/UnknownOutput",
            source_path="/World/MainCamera",
            var_paths=["/Render/Vars/WeirdBuffer"],
        )

        descriptor = UsdStageAdapter(stage).get_render_target_catalog().targets[0]

        assert descriptor.output_kind is RenderTargetOutputKind.UNKNOWN
        assert descriptor.output_names == ("WeirdBuffer",)
        assert descriptor.capabilities == ()
        assert not descriptor.enabled
        assert descriptor.disabled_reason == "RenderProduct output kind is unknown."
        assert self._warning_codes(descriptor) == {
            "unknown_output",
            "unsupported_output",
        }


class TestCoreMaterialCatalog:
    @staticmethod
    def _material(catalog, material_id):
        material = catalog.material(material_id)
        assert material is not None, material_id
        return material

    @staticmethod
    def _group(catalog, group_id):
        group = catalog.group(group_id)
        assert group is not None, group_id
        return group

    def test_empty_stage_reports_available_usd_preview_surface_material(self, empty_stage):
        before = empty_stage.GetRootLayer().ExportToString()
        catalog = UsdStageAdapter(empty_stage).list_core_materials()
        material = self._material(catalog, "core_material.usd_preview_surface")
        group = self._group(catalog, "usd_materials")

        assert not catalog.is_empty
        assert catalog.active_stage_id
        assert catalog.edit_target_id
        assert group.label == "USD Materials"
        assert group.is_available
        assert material.is_available
        assert material.family is CoreMaterialFamily.USD
        assert material.kind is CoreMaterialKind.USD_PREVIEW_SURFACE
        assert material.shader_type == "UsdPreviewSurface"
        assert material.default_scope_path == "/World/Looks"
        assert material.default_name == "PreviewSurface"
        assert CoreMaterialRequirement.MATERIAL_SCHEMA in material.requirements
        assert empty_stage.GetRootLayer().ExportToString() == before

    def test_catalog_materials_are_grouped_under_adapter_supplied_group(self, empty_stage):
        catalog = UsdStageAdapter(empty_stage).list_core_materials()

        assert [group.group_id for group in catalog.groups] == [
            "advanced",
            "base",
            "usd_materials",
        ]
        assert [
            material.material_id for material in catalog.materials_for_group("advanced")
        ] == ["core_material.omni_surface"]
        assert [
            material.material_id for material in catalog.materials_for_group("base")
        ] == ["core_material.omni_glass", "core_material.omni_pbr"]
        assert [
            material.material_id
            for material in catalog.materials_for_group("usd_materials")
        ] == ["core_material.usd_preview_surface"]
        assert "core_material.usd_preview_surface" in {
            material.material_id for material in catalog.available_materials
        }

    def test_catalog_exposes_kit_named_mdl_materials_when_modules_are_available(
        self,
        empty_stage,
        available_mdl_library,
    ):
        catalog = UsdStageAdapter(empty_stage).list_core_materials()
        omni_surface = self._material(catalog, "core_material.omni_surface")
        omni_glass = self._material(catalog, "core_material.omni_glass")
        omni_pbr = self._material(catalog, "core_material.omni_pbr")

        assert omni_surface.group_id == "advanced"
        assert omni_surface.family is CoreMaterialFamily.MDL
        assert omni_surface.kind is CoreMaterialKind.OMNI_SURFACE
        assert omni_surface.shader_type == "OmniSurface"
        assert omni_surface.metadata["mdl_source_asset"] == "OmniSurface.mdl"
        assert omni_surface.metadata["mdl_sub_identifier"] == "OmniSurface"
        assert omni_surface.is_available
        assert omni_glass.group_id == "base"
        assert omni_glass.kind is CoreMaterialKind.OMNI_GLASS
        assert omni_glass.metadata["mdl_source_asset"] == "OmniGlass.mdl"
        assert omni_glass.is_available
        assert omni_pbr.group_id == "base"
        assert omni_pbr.kind is CoreMaterialKind.OMNI_PBR
        assert omni_pbr.metadata["mdl_source_asset"] == "OmniPBR.mdl"
        assert omni_pbr.is_available

    def test_catalog_disables_kit_named_mdl_materials_without_modules(
        self,
        empty_stage,
        monkeypatch,
    ):
        monkeypatch.setattr(stage_mod, "_core_material_mdl_search_dirs", lambda: ())

        catalog = UsdStageAdapter(empty_stage).list_core_materials()
        mdl_materials = tuple(
            material
            for material in catalog.materials
            if material.family is CoreMaterialFamily.MDL
        )

        assert mdl_materials
        assert all(not material.is_available for material in mdl_materials)
        assert all(
            "not available in this standalone build" in material.disabled_reason
            for material in mdl_materials
        )

    def test_no_edit_target_disables_material_create_with_reason(self):
        class _NoEditTargetStage:
            def GetRootLayer(self):
                return SimpleNamespace(identifier="fake-root")

            def GetEditTarget(self):
                return SimpleNamespace(GetLayer=lambda: None)

        adapter = UsdStageAdapter.__new__(UsdStageAdapter)
        adapter._stage = _NoEditTargetStage()

        catalog = adapter.list_core_materials()
        material = self._material(catalog, "core_material.usd_preview_surface")

        assert catalog.active_stage_id == "fake-root"
        assert catalog.edit_target_id == ""
        assert not material.is_available
        assert not material.create_supported
        assert material.disabled_reason == "No current edit target is available."

    def test_material_schema_gap_disables_material_with_reason(self, empty_stage, monkeypatch):
        monkeypatch.setattr(stage_mod, "UsdShade", None)

        catalog = UsdStageAdapter(empty_stage).list_core_materials()
        material = self._material(catalog, "core_material.usd_preview_surface")

        assert not material.is_available
        assert not material.create_supported
        assert "UsdShade material schemas" in material.disabled_reason

    def test_no_bindable_selection_keeps_create_available_but_bind_unavailable(self, empty_stage):
        catalog = UsdStageAdapter(empty_stage).list_core_materials(
            selection_paths=["/World/Missing"]
        )
        material = self._material(catalog, "core_material.usd_preview_surface")

        assert material.is_available
        assert not material.bind_supported
        assert not material.can_bind
        assert material.binding_policy is CoreMaterialBindingPolicy.OPTIONAL_BIND_TO_SELECTION
        assert catalog.selection_paths == ("/World/Missing",)
        assert catalog.bindable_selection_paths == ()

    def test_bindable_selection_enables_material_binding(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Cube")

        catalog = UsdStageAdapter(stage).list_core_materials(
            selection_paths=["/World/Cube", "/World/Missing"]
        )
        material = self._material(catalog, "core_material.usd_preview_surface")

        assert material.is_available
        assert material.bind_supported
        assert material.can_bind
        assert catalog.selection_paths == ("/World/Cube", "/World/Missing")
        assert catalog.bindable_selection_paths == ("/World/Cube",)

    def test_unsupported_backend_and_no_active_stage_return_empty_warning_catalogs(
        self,
        empty_stage,
        monkeypatch,
    ):
        monkeypatch.setattr(stage_mod, "HAS_USD", False)
        unsupported = UsdStageAdapter.__new__(UsdStageAdapter)
        unsupported._stage = empty_stage

        unsupported_catalog = unsupported.list_core_materials(selection_paths=["/World/Cube"])
        assert unsupported_catalog.is_empty
        assert unsupported_catalog.selection_paths == ("/World/Cube",)
        assert unsupported_catalog.warnings[0].code == CoreMaterialErrorCode.UNSUPPORTED.value

        monkeypatch.setattr(stage_mod, "HAS_USD", True)
        no_stage = UsdStageAdapter.__new__(UsdStageAdapter)
        no_stage._stage = None

        no_stage_catalog = no_stage.list_core_materials()
        assert no_stage_catalog.is_empty
        assert no_stage_catalog.warnings[0].code == CoreMaterialErrorCode.NO_ACTIVE_STAGE.value

    def test_catalog_group_and_material_ordering_is_deterministic(self, empty_stage, monkeypatch):
        groups = (
            CoreMaterialGroupDescriptor("z_group", label="Z Group", order=20),
            CoreMaterialGroupDescriptor("a_group", label="A Group", order=10),
        )
        specs = (
            stage_mod._CoreMaterialSpec(
                material_id="core_material.b",
                label="B Material",
                group_id="a_group",
                family=CoreMaterialFamily.USD,
                kind=CoreMaterialKind.USD_PREVIEW_SURFACE,
                shader_type="UsdPreviewSurface",
                order=20,
                default_scope_path="/World/Looks",
                default_name="B",
            ),
            stage_mod._CoreMaterialSpec(
                material_id="core_material.a",
                label="A Material",
                group_id="a_group",
                family=CoreMaterialFamily.USD,
                kind=CoreMaterialKind.USD_PREVIEW_SURFACE,
                shader_type="UsdPreviewSurface",
                order=10,
                default_scope_path="/World/Looks",
                default_name="A",
            ),
        )
        monkeypatch.setattr(stage_mod, "_CORE_MATERIAL_GROUPS", groups)
        monkeypatch.setattr(stage_mod, "_CORE_MATERIAL_SPECS", specs)

        catalog = UsdStageAdapter(empty_stage).list_core_materials()

        assert [group.group_id for group in catalog.groups] == ["a_group", "z_group"]
        assert [material.material_id for material in catalog.materials] == [
            "core_material.a",
            "core_material.b",
        ]
        assert [material.material_id for material in catalog.materials_for_group("a_group")] == [
            "core_material.a",
            "core_material.b",
        ]


class TestCoreMaterialCreation:
    @staticmethod
    def _material_prim(stage, path="/World/Looks/PreviewSurface"):
        prim = stage.GetPrimAtPath(path)
        assert prim and prim.IsValid(), path
        return prim

    def test_create_material_success_authors_usd_preview_surface_and_result_policy(
        self,
        empty_stage,
    ):
        adapter = UsdStageAdapter(empty_stage)

        result = adapter.create_material(
            CreateMaterialRequest("core_material.usd_preview_surface")
        )

        assert result.accepted
        assert result.created_material_path == "/World/Looks/PreviewSurface"
        assert result.created_paths == (
            "/World/Looks/PreviewSurface",
            "/World/Looks/PreviewSurface/Shader",
        )
        assert result.selection_paths == ("/World/Looks/PreviewSurface",)
        assert result.focus_path == "/World/Looks/PreviewSurface"
        assert result.error_code == ""
        material = self._material_prim(empty_stage)
        shader = empty_stage.GetPrimAtPath("/World/Looks/PreviewSurface/Shader")
        assert material.GetTypeName() == "Material"
        assert shader.GetTypeName() == "Shader"
        assert shader.GetAttribute("info:id").Get() == "UsdPreviewSurface"
        assert shader.GetAttribute("inputs:roughness").Get() == 0.5
        assert shader.GetAttribute("inputs:metallic").Get() == 0.0

    @pytest.mark.parametrize(
        ("material_id", "material_path", "source_asset", "sub_identifier"),
        (
            ("core_material.omni_surface", "/World/Looks/OmniSurface", "OmniSurface.mdl", "OmniSurface"),
            ("core_material.omni_glass", "/World/Looks/OmniGlass", "OmniGlass.mdl", "OmniGlass"),
            ("core_material.omni_pbr", "/World/Looks/OmniPBR", "OmniPBR.mdl", "OmniPBR"),
        ),
    )
    def test_create_material_authors_kit_mdl_material_source_asset(
        self,
        empty_stage,
        available_mdl_library,
        material_id,
        material_path,
        source_asset,
        sub_identifier,
    ):
        result = UsdStageAdapter(empty_stage).create_material(
            CreateMaterialRequest(material_id)
        )

        assert result.accepted
        assert result.created_material_path == material_path
        material = self._material_prim(empty_stage, material_path)
        shader = empty_stage.GetPrimAtPath(f"{material_path}/Shader")
        assert material.GetTypeName() == "Material"
        assert shader.GetTypeName() == "Shader"
        assert shader.GetAttribute("info:implementationSource").Get() == "sourceAsset"
        assert shader.GetAttribute("info:mdl:sourceAsset").Get().path == source_asset
        assert shader.GetAttribute("info:mdl:sourceAsset:subIdentifier").Get() == (
            sub_identifier
        )
        assert material.GetAttribute("outputs:mdl:surface").GetConnections() == [
            Sdf.Path(f"{material_path}/Shader.outputs:out")
        ]

    def test_create_material_generates_unique_material_name(self, empty_stage):
        adapter = UsdStageAdapter(empty_stage)
        first = adapter.create_material(
            CreateMaterialRequest("core_material.usd_preview_surface")
        )
        second = adapter.create_material(
            CreateMaterialRequest("core_material.usd_preview_surface")
        )

        assert first.created_material_path == "/World/Looks/PreviewSurface"
        assert second.accepted
        assert second.created_material_path == "/World/Looks/PreviewSurface_01"
        assert empty_stage.GetPrimAtPath("/World/Looks/PreviewSurface_01").GetTypeName() == (
            "Material"
        )
        assert empty_stage.GetPrimAtPath(
            "/World/Looks/PreviewSurface_01/Shader"
        ).GetTypeName() == "Shader"

    def test_create_material_honors_explicit_scope_and_requested_name(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Scope.Define(stage, "/World/Materials")
        adapter = UsdStageAdapter(stage)

        result = adapter.create_material(
            CreateMaterialRequest(
                "core_material.usd_preview_surface",
                requested_scope_path="/World/Materials",
                requested_name="Hero Material",
            )
        )

        assert result.accepted
        assert result.created_material_path == "/World/Materials/Hero_Material"
        assert stage.GetPrimAtPath("/World/Materials/Hero_Material").GetTypeName() == (
            "Material"
        )

    def test_create_material_invalid_scope_rejects_without_mutation(self, empty_stage):
        before = empty_stage.GetRootLayer().ExportToString()

        result = UsdStageAdapter(empty_stage).create_material(
            CreateMaterialRequest(
                "core_material.usd_preview_surface",
                requested_scope_path="/World/Missing",
            )
        )

        assert not result.accepted
        assert result.error_code == CoreMaterialErrorCode.VALIDATION_FAILED.value
        assert "does not exist" in result.message
        assert empty_stage.GetRootLayer().ExportToString() == before

    def test_create_material_backend_failure_rolls_back_created_scope(self, empty_stage, monkeypatch):
        adapter = UsdStageAdapter(empty_stage)
        before = empty_stage.GetRootLayer().ExportToString()

        def _raise(*args, **kwargs):
            raise RuntimeError("backend material create failed")

        monkeypatch.setattr(adapter, "_define_core_material", _raise)

        result = adapter.create_material(
            CreateMaterialRequest("core_material.usd_preview_surface")
        )

        assert not result.accepted
        assert result.error_code == CoreMaterialErrorCode.CREATE_FAILED.value
        assert "backend material create failed" in result.message
        assert empty_stage.GetRootLayer().ExportToString() == before
        assert not empty_stage.GetPrimAtPath("/World")

    def test_create_material_surfaces_nonfatal_authoring_warning(self, empty_stage, monkeypatch):
        adapter = UsdStageAdapter(empty_stage)
        real_define = adapter._define_core_material
        warning = CoreMaterialWarning(
            code="default_value_warning",
            message="Using adapter default material values.",
            severity=CoreMaterialWarningSeverity.WARNING,
        )

        def _define_with_warning(material, material_path):
            prim, created_paths, warnings = real_define(material, material_path)
            return prim, created_paths, (*warnings, warning)

        monkeypatch.setattr(adapter, "_define_core_material", _define_with_warning)

        result = adapter.create_material(
            CreateMaterialRequest("core_material.usd_preview_surface")
        )

        assert result.accepted
        assert result.warnings == (warning,)
        assert result.created_material_path == "/World/Looks/PreviewSurface"

    def test_create_material_does_not_bind_when_bind_flag_is_requested(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        cube = UsdGeom.Cube.Define(stage, "/World/Cube").GetPrim()
        adapter = UsdStageAdapter(stage)

        result = adapter.create_material(
            CreateMaterialRequest(
                "core_material.usd_preview_surface",
                selection_paths=("/World/Cube",),
                bind_to_selection=True,
            )
        )

        assert result.accepted
        assert result.created_material_path == "/World/Looks/PreviewSurface"
        assert cube.GetRelationship("material:binding").GetTargets() == []

    def test_create_material_disabled_material_cannot_execute_without_mutation(
        self,
        empty_stage,
        monkeypatch,
    ):
        adapter = UsdStageAdapter(empty_stage)
        before = empty_stage.GetRootLayer().ExportToString()
        disabled = CoreMaterialDescriptor(
            material_id="core_material.usd_preview_surface",
            enabled=False,
            create_supported=False,
            disabled_reason="Adapter disabled this material.",
        )
        monkeypatch.setattr(
            adapter,
            "list_core_materials",
            lambda *, selection_paths=None: CoreMaterialCatalog(materials=(disabled,)),
        )

        result = adapter.create_material(
            CreateMaterialRequest("core_material.usd_preview_surface")
        )

        assert not result.accepted
        assert result.error_code == CoreMaterialErrorCode.DISABLED.value
        assert result.message == "Adapter disabled this material."
        assert empty_stage.GetRootLayer().ExportToString() == before

    def test_create_material_unknown_material_rejects_without_mutation(self, empty_stage):
        before = empty_stage.GetRootLayer().ExportToString()

        result = UsdStageAdapter(empty_stage).create_material(
            CreateMaterialRequest("core_material.not-real")
        )

        assert not result.accepted
        assert result.error_code == CoreMaterialErrorCode.UNSUPPORTED.value
        assert empty_stage.GetRootLayer().ExportToString() == before


class TestCoreMaterialBinding:
    @staticmethod
    def _stage_with_material_and_prims():
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Cube")
        UsdGeom.Sphere.Define(stage, "/World/Sphere")
        adapter = UsdStageAdapter(stage)
        create = adapter.create_material(
            CreateMaterialRequest("core_material.usd_preview_surface")
        )
        assert create.accepted
        return stage, adapter, create.created_material_path

    @staticmethod
    def _binding_targets(stage, prim_path):
        return stage.GetPrimAtPath(prim_path).GetRelationship("material:binding").GetTargets()

    def test_bind_material_success_authors_relationship_with_strength(self):
        if not HAS_USD_SHADE:
            pytest.skip("UsdShade is unavailable in this OpenUSD build")
        stage, adapter, material_path = self._stage_with_material_and_prims()

        result = adapter.bind_material(
            BindMaterialRequest(
                material_path=material_path,
                selection_paths=("/World/Cube",),
                binding_strength="strongerThanDescendants",
            )
        )

        assert result.accepted
        assert result.material_path == material_path
        assert result.bound_prim_paths == ("/World/Cube",)
        assert result.skipped_prim_paths == ()
        assert result.failed_prim_paths == ()
        rel = stage.GetPrimAtPath("/World/Cube").GetRelationship("material:binding")
        assert rel.GetTargets() == [Sdf.Path(material_path)]
        assert UsdShade.MaterialBindingAPI.GetMaterialBindingStrength(rel) == (
            UsdShade.Tokens.strongerThanDescendants
        )

    def test_bind_material_partial_bind_skips_invalid_selection_without_failure(self):
        stage, adapter, material_path = self._stage_with_material_and_prims()

        result = adapter.bind_material(
            BindMaterialRequest(
                material_path=material_path,
                selection_paths=("/World/Cube", "/World/Missing", "/"),
            )
        )

        assert result.accepted
        assert result.bound_prim_paths == ("/World/Cube",)
        assert result.skipped_prim_paths == ("/World/Missing", "/")
        assert result.failed_prim_paths == ()
        assert [warning.code for warning in result.warnings] == [
            "invalid_selection_path",
            "invalid_selection_path",
        ]
        assert self._binding_targets(stage, "/World/Cube") == [Sdf.Path(material_path)]

    def test_bind_material_no_selection_rejects_without_mutation(self):
        stage, adapter, material_path = self._stage_with_material_and_prims()
        before = stage.GetRootLayer().ExportToString()

        result = adapter.bind_material(
            BindMaterialRequest(material_path=material_path)
        )

        assert not result.accepted
        assert result.error_code == CoreMaterialErrorCode.VALIDATION_FAILED.value
        assert "Select at least one prim" in result.message
        assert stage.GetRootLayer().ExportToString() == before

    def test_bind_material_invalid_material_rejects_without_mutation(self):
        stage, adapter, _ = self._stage_with_material_and_prims()
        before = stage.GetRootLayer().ExportToString()

        result = adapter.bind_material(
            BindMaterialRequest(
                material_path="/World/Looks/Missing",
                selection_paths=("/World/Cube",),
            )
        )

        assert not result.accepted
        assert result.error_code == CoreMaterialErrorCode.VALIDATION_FAILED.value
        assert "not a UsdShade material" in result.message
        assert stage.GetRootLayer().ExportToString() == before

    def test_bind_material_backend_failure_rolls_back_partial_binding(self, monkeypatch):
        stage, adapter, material_path = self._stage_with_material_and_prims()
        before = stage.GetRootLayer().ExportToString()
        real_bind = adapter._bind_core_material_to_targets

        def _partial_then_raise(material_prim, targets, binding_strength):
            real_bind(material_prim, targets[:1], binding_strength)
            raise RuntimeError("backend bind failed")

        monkeypatch.setattr(adapter, "_bind_core_material_to_targets", _partial_then_raise)

        result = adapter.bind_material(
            BindMaterialRequest(
                material_path=material_path,
                selection_paths=("/World/Cube", "/World/Sphere"),
            )
        )

        assert not result.accepted
        assert result.error_code == CoreMaterialErrorCode.BIND_FAILED.value
        assert result.failed_prim_paths == ("/World/Cube", "/World/Sphere")
        assert "backend bind failed" in result.message
        assert stage.GetRootLayer().ExportToString() == before
        assert self._binding_targets(stage, "/World/Cube") == []
        assert self._binding_targets(stage, "/World/Sphere") == []

    def test_bind_material_default_strength_is_weaker_than_descendants(self):
        if not HAS_USD_SHADE:
            pytest.skip("UsdShade is unavailable in this OpenUSD build")
        stage, adapter, material_path = self._stage_with_material_and_prims()

        result = adapter.bind_material(
            BindMaterialRequest(
                material_path=material_path,
                selection_paths=("/World/Sphere",),
            )
        )

        assert result.accepted
        rel = stage.GetPrimAtPath("/World/Sphere").GetRelationship("material:binding")
        assert UsdShade.MaterialBindingAPI.GetMaterialBindingStrength(rel) == (
            UsdShade.Tokens.weakerThanDescendants
        )

    def test_create_and_bind_material_success_creates_material_and_binds_selection(self):
        if not HAS_USD_SHADE:
            pytest.skip("UsdShade is unavailable in this OpenUSD build")
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Cube")
        adapter = UsdStageAdapter(stage)

        result = adapter.create_and_bind_material(
            CreateMaterialRequest(
                "core_material.usd_preview_surface",
                selection_paths=("/World/Cube",),
                options={"binding_strength": "stronger"},
            )
        )

        assert result.accepted
        assert result.created_material_path == "/World/Looks/PreviewSurface"
        assert result.created_paths == (
            "/World/Looks/PreviewSurface",
            "/World/Looks/PreviewSurface/Shader",
        )
        assert result.bound_prim_paths == ("/World/Cube",)
        assert result.skipped_prim_paths == ()
        assert result.failed_prim_paths == ()
        assert result.selection_paths == ("/World/Looks/PreviewSurface",)
        assert result.focus_path == "/World/Looks/PreviewSurface"
        assert result.binding_applied
        rel = stage.GetPrimAtPath("/World/Cube").GetRelationship("material:binding")
        assert rel.GetTargets() == [Sdf.Path("/World/Looks/PreviewSurface")]
        assert UsdShade.MaterialBindingAPI.GetMaterialBindingStrength(rel) == (
            UsdShade.Tokens.strongerThanDescendants
        )

    def test_create_and_bind_material_no_selection_rejects_without_mutation(self):
        stage = Usd.Stage.CreateInMemory()
        before = stage.GetRootLayer().ExportToString()

        result = UsdStageAdapter(stage).create_and_bind_material(
            CreateMaterialRequest("core_material.usd_preview_surface")
        )

        assert not result.accepted
        assert result.error_code == CoreMaterialErrorCode.VALIDATION_FAILED.value
        assert "Select at least one prim" in result.message
        assert stage.GetRootLayer().ExportToString() == before

    def test_create_and_bind_material_bind_failure_rolls_back_created_material(
        self,
        monkeypatch,
    ):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Cube.Define(stage, "/World/Cube")
        adapter = UsdStageAdapter(stage)
        before = stage.GetRootLayer().ExportToString()
        real_bind = adapter._bind_core_material_to_targets

        def _partial_then_raise(material_prim, targets, binding_strength):
            real_bind(material_prim, targets, binding_strength)
            raise RuntimeError("combined bind failed")

        monkeypatch.setattr(adapter, "_bind_core_material_to_targets", _partial_then_raise)

        result = adapter.create_and_bind_material(
            CreateMaterialRequest(
                "core_material.usd_preview_surface",
                selection_paths=("/World/Cube",),
            )
        )

        assert not result.accepted
        assert result.error_code == CoreMaterialErrorCode.BIND_FAILED.value
        assert result.failed_prim_paths == ("/World/Cube",)
        assert "combined bind failed" in result.message
        assert stage.GetRootLayer().ExportToString() == before
        assert not stage.GetPrimAtPath("/World/Looks/PreviewSurface")
        assert self._binding_targets(stage, "/World/Cube") == []


class TestCreateActionCatalog:
    @staticmethod
    def _action(catalog, action_id):
        action = catalog.action(action_id)
        assert action is not None, action_id
        return action

    @staticmethod
    def _category(catalog, category):
        descriptor = catalog.category(category)
        assert descriptor is not None, category
        return descriptor

    def test_empty_stage_still_reports_supported_create_actions(self, empty_stage):
        catalog = UsdStageAdapter(empty_stage).list_create_actions()

        assert not catalog.is_empty
        assert catalog.active_stage_id
        assert catalog.edit_target_id
        cube = self._action(catalog, "create.geometry.mesh.cube")
        camera = self._action(catalog, "create.camera")
        render_product = self._action(catalog, "create.render_product")
        assert cube.is_available
        assert cube.label == "Cube"
        assert cube.target_prim_type == "Mesh"
        assert cube.category_id == CreateActionCategory.MESH.value
        assert cube.default_name == "Cube"
        assert camera.is_available
        assert camera.category_id == CreateActionCategory.CAMERAS.value
        assert render_product.is_available
        assert render_product.category_id == CreateActionCategory.RENDER_PRODUCTS.value
        assert render_product.target_prim_type == "RenderProduct"
        assert empty_stage.GetPseudoRoot().GetChildren() == []

    def test_mesh_and_shape_categories_are_split_for_kit_create_layout(self, empty_stage):
        catalog = UsdStageAdapter(empty_stage).list_create_actions()

        mesh = self._category(catalog, CreateActionCategory.MESH)
        shape = self._category(catalog, CreateActionCategory.SHAPE)

        assert mesh.label == "Mesh"
        assert shape.label == "Shape"
        assert [action.action_id for action in catalog.actions_for_category("mesh")] == [
            "create.geometry.mesh.cone",
            "create.geometry.mesh.cube",
            "create.geometry.mesh.cylinder",
            "create.geometry.mesh.disk",
            "create.geometry.mesh.plane",
            "create.geometry.mesh.sphere",
            "create.geometry.mesh.torus",
        ]
        assert [action.label for action in catalog.actions_for_category("mesh")] == [
            "Cone",
            "Cube",
            "Cylinder",
            "Disk",
            "Plane",
            "Sphere",
            "Torus",
        ]
        assert [action.action_id for action in catalog.actions_for_category("shape")] == [
            "create.geometry.shape.capsule",
            "create.geometry.shape.cone",
            "create.geometry.shape.cube",
            "create.geometry.shape.cylinder",
            "create.geometry.shape.sphere",
        ]

    def test_supported_category_contains_ordered_light_actions(self, empty_stage):
        catalog = UsdStageAdapter(empty_stage).list_create_actions()

        category = self._category(catalog, CreateActionCategory.LIGHTS)
        light_ids = [
            action.action_id
            for action in catalog.actions_for_category(CreateActionCategory.LIGHTS)
        ]

        assert category.category_id == "lights"
        assert category.label == "Light"
        assert category.is_available
        assert light_ids == [
            "create.light.cylinder",
            "create.light.disk",
            "create.light.distant",
            "create.light.dome",
            "create.light.rect",
            "create.light.sphere",
        ]
        assert self._action(catalog, "create.light.sphere").target_prim_type == "SphereLight"

    def test_sensor_category_contains_enabled_generic_lidar_action(self, empty_stage):
        catalog = UsdStageAdapter(empty_stage).list_create_actions()

        category = self._category(catalog, CreateActionCategory.SENSORS)
        action = self._action(catalog, "create.sensor.generic-lidar")

        assert category.is_available
        assert category.disabled_reason == ""
        assert action.is_available
        assert action.disabled_reason == ""
        assert action.target_prim_type == "OmniLidar"
        assert CreateActionRequirement.UNSUPPORTED not in action.requirements

    def test_rendering_categories_are_grouped_under_rendering_menu(self, empty_stage):
        catalog = UsdStageAdapter(empty_stage).list_create_actions()

        grouped = (
            CreateActionCategory.RENDER_PRODUCTS,
            CreateActionCategory.SENSORS,
            CreateActionCategory.DECALS,
            CreateActionCategory.PROJECTORS,
        )

        for category_id in grouped:
            category = self._category(catalog, category_id)
            assert category.metadata["parent_path"] == ("Create", "Rendering")

        assert self._action(catalog, "create.render_product").is_available
        assert self._action(catalog, "create.render_product").default_parent_path == "/Render/Products"

    def test_decal_and_projector_actions_stay_disabled_with_schema_reasons(self, empty_stage):
        catalog = UsdStageAdapter(empty_stage).list_create_actions()

        decal = self._action(catalog, "create.decal")
        projector = self._action(catalog, "create.projector")

        assert not decal.is_available
        assert "decal creation schema" in decal.disabled_reason
        assert CreateActionRequirement.UNSUPPORTED in decal.requirements
        assert not projector.is_available
        assert "projector creation schema" in projector.disabled_reason
        assert CreateActionRequirement.UNSUPPORTED in projector.requirements

    def test_no_edit_target_disables_authoring_actions_with_reason(self):
        class _NoEditTargetStage:
            def GetRootLayer(self):
                return SimpleNamespace(identifier="fake-root")

            def GetEditTarget(self):
                return SimpleNamespace(GetLayer=lambda: None)

        adapter = UsdStageAdapter.__new__(UsdStageAdapter)
        adapter._stage = _NoEditTargetStage()

        catalog = adapter.list_create_actions()
        cube = self._action(catalog, "create.geometry.mesh.cube")

        assert catalog.active_stage_id == "fake-root"
        assert catalog.edit_target_id == ""
        assert not cube.is_available
        assert cube.disabled_reason == "No current edit target is available."

    def test_selection_dependent_material_bind_action_tracks_selection(self, empty_stage):
        adapter = UsdStageAdapter(empty_stage)

        no_selection_catalog = adapter.list_create_actions()
        selected_catalog = adapter.list_create_actions(selection_paths=["/World/Cube"])
        no_selection_action = self._action(
            no_selection_catalog,
            "create.material.usd-preview-surface.bind",
        )
        selected_action = self._action(
            selected_catalog,
            "create.material.usd-preview-surface.bind",
        )

        assert not no_selection_action.is_available
        assert no_selection_action.disabled_reason == (
            "Select a prim before using this create action."
        )
        assert CreateActionRequirement.SELECTION in no_selection_action.requirements
        assert selected_action.is_available
        assert selected_action.binding_policy is CreateBindingPolicy.BIND_TO_SELECTION
        assert selected_catalog.selection_paths == ("/World/Cube",)

    def test_unsupported_backend_returns_empty_warning_catalog(self, empty_stage, monkeypatch):
        monkeypatch.setattr(stage_mod, "HAS_USD", False)
        adapter = UsdStageAdapter.__new__(UsdStageAdapter)
        adapter._stage = empty_stage

        catalog = adapter.list_create_actions(selection_paths=["/World/Cube"])

        assert catalog.is_empty
        assert catalog.selection_paths == ("/World/Cube",)
        assert catalog.warnings[0].code == CreateActionErrorCode.UNSUPPORTED.value

    def test_no_active_stage_returns_empty_warning_catalog(self):
        adapter = UsdStageAdapter.__new__(UsdStageAdapter)
        adapter._stage = None

        catalog = adapter.list_create_actions()

        assert catalog.is_empty
        assert catalog.warnings[0].code == CreateActionErrorCode.NO_ACTIVE_STAGE.value

    def test_catalog_category_and_action_ordering_is_deterministic(self, empty_stage):
        catalog = UsdStageAdapter(empty_stage).list_create_actions()

        assert [category.category_id for category in catalog.categories] == [
            "mesh",
            "shape",
            "lights",
            "cameras",
            "scopes",
            "transforms",
            "materials",
            "render_products",
            "sensors",
            "decals",
            "projectors",
        ]
        assert [action.action_id for action in catalog.actions[:8]] == [
            "create.geometry.mesh.cone",
            "create.geometry.mesh.cube",
            "create.geometry.mesh.cylinder",
            "create.geometry.mesh.disk",
            "create.geometry.mesh.plane",
            "create.geometry.mesh.sphere",
            "create.geometry.mesh.torus",
            "create.geometry.shape.capsule",
        ]

    def test_create_prim_success_authors_shape_and_result_policy(self, empty_stage):
        adapter = UsdStageAdapter(empty_stage)

        result = adapter.create_prim(CreateRequest("create.geometry.shape.cube"))

        assert result.accepted
        assert result.primary_path == "/World/Cube"
        assert result.created_paths == ("/World/Cube",)
        assert result.selection_paths == ("/World/Cube",)
        assert result.focus_path == "/World/Cube"
        assert empty_stage.GetPrimAtPath("/World").GetTypeName() == "Xform"
        assert empty_stage.GetPrimAtPath("/World/Cube").GetTypeName() == "Cube"

    def test_create_prim_shape_actions_author_kit_standard_defaults(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.SetStageMetersPerUnit(stage, 0.01)
        UsdGeom.Xform.Define(stage, "/World")
        adapter = UsdStageAdapter(stage)

        mesh_sphere_result = adapter.create_prim(CreateRequest(
            "create.geometry.mesh.sphere",
            requested_name="MeshSphere",
        ))
        shape_sphere_result = adapter.create_prim(CreateRequest(
            "create.geometry.shape.sphere",
            requested_name="ShapeSphere",
        ))
        mesh_cube_result = adapter.create_prim(CreateRequest(
            "create.geometry.mesh.cube",
            requested_name="MeshCube",
        ))
        shape_cube_result = adapter.create_prim(CreateRequest(
            "create.geometry.shape.cube",
            requested_name="ShapeCube",
        ))

        assert mesh_sphere_result.accepted
        assert shape_sphere_result.accepted
        assert mesh_cube_result.accepted
        assert shape_cube_result.accepted

        def extent_values(prim_path):
            extent = stage.GetPrimAtPath(prim_path).GetAttribute("extent").Get()
            return tuple(float(component) for point in extent for component in point)

        shape_sphere = UsdGeom.Sphere(stage.GetPrimAtPath("/World/ShapeSphere"))
        shape_cube = UsdGeom.Cube(stage.GetPrimAtPath("/World/ShapeCube"))

        assert shape_sphere.GetRadiusAttr().Get() == pytest.approx(50.0)
        assert extent_values("/World/ShapeSphere") == pytest.approx(
            (-50.0, -50.0, -50.0, 50.0, 50.0, 50.0)
        )
        assert extent_values("/World/MeshSphere") == pytest.approx(
            extent_values("/World/ShapeSphere")
        )
        assert shape_cube.GetSizeAttr().Get() == pytest.approx(100.0)
        assert extent_values("/World/ShapeCube") == pytest.approx(
            (-50.0, -50.0, -50.0, 50.0, 50.0, 50.0)
        )
        assert extent_values("/World/MeshCube") == pytest.approx(
            extent_values("/World/ShapeCube")
        )

    @pytest.mark.parametrize(
        ("action_id", "path", "expected"),
        (
            ("create.geometry.mesh.cone", "/World/Cone", (258, 320, 1152, {3: 128, 4: 192}, 0.5)),
            ("create.geometry.mesh.cube", "/World/Cube", (8, 6, 24, {4: 6}, 0.5)),
            ("create.geometry.mesh.cylinder", "/World/Cylinder", (66, 96, 320, {3: 64, 4: 32}, 0.5)),
            ("create.geometry.mesh.disk", "/World/Disk", (33, 32, 96, {3: 32}, 0.0)),
            ("create.geometry.mesh.plane", "/World/Plane", (4, 1, 4, {4: 1}, 0.0)),
            ("create.geometry.mesh.sphere", "/World/Sphere", (482, 512, 1984, {3: 64, 4: 448}, 0.5)),
            ("create.geometry.mesh.torus", "/World/Torus", (1024, 1024, 4096, {4: 1024}, 0.25)),
        ),
    )
    def test_create_prim_mesh_actions_author_kit_port_topology(self, action_id, path, expected):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.Xform.Define(stage, "/World")
        adapter = UsdStageAdapter(stage)

        result = adapter.create_prim(CreateRequest(action_id))

        assert result.accepted
        assert result.primary_path == path
        mesh = UsdGeom.Mesh(stage.GetPrimAtPath(path))
        assert mesh

        points = mesh.GetPointsAttr().Get()
        indices = mesh.GetFaceVertexIndicesAttr().Get()
        counts = mesh.GetFaceVertexCountsAttr().Get()
        normals = mesh.GetNormalsAttr().Get()
        extent = mesh.GetExtentAttr().Get()
        st = UsdGeom.PrimvarsAPI(mesh.GetPrim()).GetPrimvar("st")
        st_values = st.Get()
        expected_points, expected_faces, expected_indices, expected_face_counts, expected_translate_y = expected
        counts_list = list(counts)

        assert len(points) == expected_points
        assert len(indices) == expected_indices
        assert len(counts) == expected_faces
        assert {
            face_count: counts_list.count(face_count)
            for face_count in sorted(set(counts_list))
        } == expected_face_counts
        assert all(0 <= index < len(points) for index in indices)
        assert sum(counts) == len(indices)
        assert normals and len(normals) == len(indices)
        assert st
        assert st.GetInterpolation() == "faceVarying"
        assert st_values and len(st_values) == len(indices)
        assert mesh.GetSubdivisionSchemeAttr().Get() == "none"
        assert extent and len(extent) == 2
        assert any(extent[0][axis] < extent[1][axis] for axis in range(3))
        translate = mesh.GetPrim().GetAttribute("xformOp:translate").Get()
        assert tuple(float(value) for value in translate) == pytest.approx((0.0, expected_translate_y, 0.0))

    def test_create_prim_generates_unique_sibling_name(self, empty_stage):
        adapter = UsdStageAdapter(empty_stage)
        first = adapter.create_prim(CreateRequest("create.geometry.shape.cube"))
        second = adapter.create_prim(CreateRequest("create.geometry.shape.cube"))

        assert first.primary_path == "/World/Cube"
        assert second.accepted
        assert second.primary_path == "/World/Cube_01"
        assert empty_stage.GetPrimAtPath("/World/Cube_01").GetTypeName() == "Cube"

    def test_create_prim_honors_explicit_parent_and_requested_name(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        UsdGeom.Xform.Define(stage, "/World/Rig")
        adapter = UsdStageAdapter(stage)

        result = adapter.create_prim(CreateRequest(
            "create.camera",
            requested_parent_path="/World/Rig",
            requested_name="Shot Camera",
        ))

        assert result.accepted
        assert result.primary_path == "/World/Rig/Shot_Camera"
        assert stage.GetPrimAtPath("/World/Rig/Shot_Camera").GetTypeName() == "Camera"

    def test_create_prim_invalid_parent_rejects_without_mutation(self, empty_stage):
        before = empty_stage.GetRootLayer().ExportToString()
        result = UsdStageAdapter(empty_stage).create_prim(CreateRequest(
            "create.camera",
            requested_parent_path="/World/Missing",
        ))

        assert not result.accepted
        assert result.error_code == CreateActionErrorCode.VALIDATION_FAILED.value
        assert "does not exist" in result.message
        assert empty_stage.GetRootLayer().ExportToString() == before

    def test_create_prim_generic_lidar_authors_structural_sensor(self, empty_stage):
        result = UsdStageAdapter(empty_stage).create_prim(
            CreateRequest("create.sensor.generic-lidar")
        )

        assert result.accepted
        assert result.primary_path == "/World/Lidar/Sensor"
        assert result.created_paths == ("/World/Lidar", "/World/Lidar/Sensor")
        assert result.selection_paths == ("/World/Lidar/Sensor",)
        assert empty_stage.GetPrimAtPath("/World/Lidar").GetTypeName() == "Xform"

        sensor = empty_stage.GetPrimAtPath("/World/Lidar/Sensor")
        assert sensor.GetTypeName() == "OmniLidar"
        api_schemas = sensor.GetMetadata("apiSchemas")
        assert "OmniSensorGenericLidarCoreAPI" in api_schemas.GetAppliedItems()
        assert sensor.GetAttribute("omni:sensor:Core:elementsCoordsType").Get() == "CARTESIAN"
        assert sensor.GetAttribute("omni:sensor:Core:outputFrameOfReference").Get() == "WORLD"
        assert tuple(sensor.GetAttribute("omni:sensor:frameRate").Get()) == (10.0, 1.0)
        assert tuple(sensor.GetAttribute("xformOp:rotateXYZ").Get()) == (90.0, 0.0, -90.0)

    def test_create_prim_generic_lidar_places_sensor_outside_selected_geometry(self, empty_stage):
        adapter = UsdStageAdapter(empty_stage)
        torus_result = adapter.create_prim(CreateRequest("create.geometry.mesh.torus"))
        assert torus_result.accepted

        result = adapter.create_prim(
            CreateRequest(
                "create.sensor.generic-lidar",
                selection_paths=torus_result.selection_paths,
            )
        )

        assert result.accepted
        lidar_xform = UsdGeom.Xformable(empty_stage.GetPrimAtPath("/World/Lidar"))
        translate = lidar_xform.GetOrderedXformOps()[0].Get()
        assert tuple(translate) == pytest.approx((0.0, -150.0, 0.0))

    def test_create_prim_render_product_targets_selected_lidar_with_point_cloud_output(self, empty_stage):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        adapter = UsdStageAdapter(empty_stage)
        lidar_result = adapter.create_prim(CreateRequest("create.sensor.generic-lidar"))
        assert lidar_result.accepted

        result = adapter.create_prim(
            CreateRequest(
                "create.render_product",
                selection_paths=("/World/Lidar/Sensor",),
            )
        )

        assert result.accepted
        assert result.primary_path == "/Render/Products/RenderProduct"
        assert result.selection_paths == ("/Render/Products/RenderProduct",)

        assert empty_stage.GetPrimAtPath("/Render").GetTypeName() == "Scope"
        assert empty_stage.GetPrimAtPath("/Render/Products").GetTypeName() == "Scope"
        assert empty_stage.GetPrimAtPath("/Render/Vars").GetTypeName() == "Scope"
        product_prim = empty_stage.GetPrimAtPath("/Render/Products/RenderProduct")
        assert product_prim.IsA(UsdRender.Product)
        product = UsdRender.Product(product_prim)
        assert product.GetCameraRel().GetTargets() == [Sdf.Path("/World/Lidar/Sensor")]
        assert product.GetOrderedVarsRel().GetTargets() == [Sdf.Path("/Render/Vars/PointCloud")]
        assert tuple(product.GetResolutionAttr().Get()) == (1, 1)

        var_prim = empty_stage.GetPrimAtPath("/Render/Vars/PointCloud")
        assert var_prim.IsA(UsdRender.Var)
        assert UsdRender.Var(var_prim).GetSourceNameAttr().Get() == "PointCloud"
        assert tuple(var_prim.GetAttribute("channels").Get()) == (
            "Coordinates",
            "Intensity",
            "Counts",
            "Flags",
            "TimeOffsetNs",
        )

        by_path = {
            target.render_product_path: target
            for target in UsdStageAdapter(empty_stage).get_render_target_catalog().targets
        }
        lidar_target = by_path["/Render/Products/RenderProduct"]
        assert lidar_target.kind is RenderTargetKind.SENSOR
        assert lidar_target.source_path == "/World/Lidar/Sensor"
        assert lidar_target.output_kind is RenderTargetOutputKind.POINT_CLOUD

    def test_create_prim_render_product_targets_selected_lidar_parent(self, empty_stage):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        adapter = UsdStageAdapter(empty_stage)
        assert adapter.create_prim(CreateRequest("create.sensor.generic-lidar")).accepted

        result = adapter.create_prim(
            CreateRequest("create.render_product", selection_paths=("/World/Lidar",))
        )

        assert result.accepted
        product = UsdRender.Product(empty_stage.GetPrimAtPath("/Render/Products/RenderProduct"))
        assert product.GetCameraRel().GetTargets() == [Sdf.Path("/World/Lidar/Sensor")]

    def test_create_prim_render_product_targets_selected_camera_with_ldr_output(self, empty_stage):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        UsdGeom.Camera.Define(empty_stage, "/World/MainCamera")

        result = UsdStageAdapter(empty_stage).create_prim(
            CreateRequest(
                "create.render_product",
                selection_paths=("/World/MainCamera",),
            )
        )

        assert result.accepted
        product = UsdRender.Product(empty_stage.GetPrimAtPath("/Render/Products/RenderProduct"))
        assert product.GetCameraRel().GetTargets() == [Sdf.Path("/World/MainCamera")]
        assert product.GetOrderedVarsRel().GetTargets() == [Sdf.Path("/Render/Vars/LdrColor")]
        assert tuple(product.GetResolutionAttr().Get()) == (1280, 720)
        assert UsdRender.Var(empty_stage.GetPrimAtPath("/Render/Vars/LdrColor")).GetSourceNameAttr().Get() == "LdrColor"

    def test_create_prim_generic_lidar_backend_failure_rolls_back(self, empty_stage, monkeypatch):
        adapter = UsdStageAdapter(empty_stage)
        before = empty_stage.GetRootLayer().ExportToString()

        def _raise(*args, **kwargs):
            raise RuntimeError("lidar authoring failed")

        monkeypatch.setattr(adapter, "_define_generic_lidar_sensor", _raise)
        result = adapter.create_prim(CreateRequest("create.sensor.generic-lidar"))

        assert not result.accepted
        assert result.error_code == CreateActionErrorCode.CREATE_FAILED.value
        assert "lidar authoring failed" in result.message
        assert empty_stage.GetRootLayer().ExportToString() == before

    def test_create_prim_render_product_backend_failure_rolls_back(self, empty_stage, monkeypatch):
        if not HAS_USD_RENDER:
            pytest.skip("UsdRender is unavailable in this OpenUSD build")
        adapter = UsdStageAdapter(empty_stage)
        before = empty_stage.GetRootLayer().ExportToString()

        def _raise(*args, **kwargs):
            raise RuntimeError("render product authoring failed")

        monkeypatch.setattr(adapter, "_define_render_product", _raise)
        result = adapter.create_prim(CreateRequest("create.render_product"))

        assert not result.accepted
        assert result.error_code == CreateActionErrorCode.CREATE_FAILED.value
        assert "render product authoring failed" in result.message
        assert empty_stage.GetRootLayer().ExportToString() == before

    def test_create_prim_disabled_decal_action_rejects_without_mutation(self, empty_stage):
        before = empty_stage.GetRootLayer().ExportToString()
        result = UsdStageAdapter(empty_stage).create_prim(CreateRequest("create.decal"))

        assert not result.accepted
        assert result.error_code == CreateActionErrorCode.DISABLED.value
        assert "decal creation schema" in result.message
        assert empty_stage.GetRootLayer().ExportToString() == before

    def test_create_prim_backend_failure_rolls_back_parent_creation(self, empty_stage, monkeypatch):
        adapter = UsdStageAdapter(empty_stage)
        before = empty_stage.GetRootLayer().ExportToString()

        def _raise(*args, **kwargs):
            raise RuntimeError("backend create failed")

        monkeypatch.setattr(adapter, "_define_create_action_prim", _raise)
        result = adapter.create_prim(CreateRequest("create.xform"))

        assert not result.accepted
        assert result.error_code == CreateActionErrorCode.CREATE_FAILED.value
        assert "backend create failed" in result.message
        assert empty_stage.GetRootLayer().ExportToString() == before

    def test_create_prim_material_bind_applies_binding_and_warning(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        cube = UsdGeom.Cube.Define(stage, "/World/Cube").GetPrim()
        adapter = UsdStageAdapter(stage)

        result = adapter.create_prim(CreateRequest(
            "create.material.usd-preview-surface.bind",
            selection_paths=("/World/Cube", "/World/Missing"),
        ))

        assert result.accepted
        assert result.primary_path == "/World/Looks/PreviewSurface"
        assert result.created_paths == (
            "/World/Looks/PreviewSurface",
            "/World/Looks/PreviewSurface/Shader",
        )
        assert result.binding_applied
        assert result.selection_paths == ("/World/Looks/PreviewSurface",)
        assert result.warnings[0].code == "invalid_selection_path"
        assert Sdf.Path("/World/Looks/PreviewSurface") in cube.GetRelationship(
            "material:binding"
        ).GetTargets()

    def test_create_prim_bind_without_valid_selection_rejects_without_mutation(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/World")
        adapter = UsdStageAdapter(stage)
        before = stage.GetRootLayer().ExportToString()

        result = adapter.create_prim(CreateRequest(
            "create.material.usd-preview-surface.bind",
            selection_paths=("/World/Missing",),
        ))

        assert not result.accepted
        assert result.error_code == CreateActionErrorCode.VALIDATION_FAILED.value
        assert "No valid selected prim" in result.message
        assert stage.GetRootLayer().ExportToString() == before

    def test_create_prim_unknown_action_rejects_without_mutation(self, empty_stage):
        before = empty_stage.GetRootLayer().ExportToString()
        result = UsdStageAdapter(empty_stage).create_prim(
            CreateRequest("create.not-real")
        )

        assert not result.accepted
        assert result.error_code == CreateActionErrorCode.UNSUPPORTED.value
        assert empty_stage.GetRootLayer().ExportToString() == before


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
        # openusd file no longer depends on ovui_widgets.common.settings.Subscription.
        from ovui_data_adapters.common import SubscriptionProtocol
        sub = adapter.subscribe_changes(lambda e: None)
        assert isinstance(sub, SubscriptionProtocol)

    def test_suppress_change_notifications_no_crash(self, adapter):
        with adapter.suppress_change_notifications():
            pass

    def test_begin_end_undo_group_no_crash(self, adapter):
        adapter.begin_undo_group("test")
        adapter.end_undo_group()
