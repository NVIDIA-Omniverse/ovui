# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for ovui_data_adapters.openusd._session_authoring.

Verifies that every helper:
- Creates the expected prim with the expected type and attributes.
- Authors exclusively in the stage's session layer, leaving the root
  layer byte-identical to its pre-call state.
- Is idempotent: second call does not create a duplicate spec.

Also verifies the dome-light fallback is skipped when any user-authored
light exists on the stage.
"""

from __future__ import annotations

import pytest

pxr = pytest.importorskip("pxr")
from ovui_data_adapters.openusd._session_authoring import (  # noqa: E402
    DEFAULT_RESOLUTION,
    LDR_SOURCE_NAME,
    PICK_RENDER_PRODUCT_DEVICE_IDS,
    ensure_camera,
    ensure_dome_light,
    ensure_ldr_color_var,
    ensure_render_product,
    ensure_render_scope,
)
from pxr import Gf, Sdf, Usd, UsdLux  # noqa: E402

# ── Helpers ────────────────────────────────────────────────────────────────


@pytest.fixture
def stage():
    return Usd.Stage.CreateInMemory()


def _root_has_any_prim(stage: Usd.Stage) -> bool:
    return len(stage.GetRootLayer().rootPrims) > 0


def _session_has_spec(stage: Usd.Stage, path: str) -> bool:
    return stage.GetSessionLayer().GetPrimAtPath(path) is not None


def _root_has_spec(stage: Usd.Stage, path: str) -> bool:
    return stage.GetRootLayer().GetPrimAtPath(path) is not None


# ── ensure_render_scope ─────────────────────────────────────────────────────


class TestEnsureRenderScope:
    def test_creates_scope_prim(self, stage):
        prim = ensure_render_scope(stage)
        assert prim.IsValid()
        assert prim.GetTypeName() == "Scope"
        assert str(prim.GetPath()) == "/OvGearSession"

    def test_authored_in_session_layer_only(self, stage):
        ensure_render_scope(stage)
        assert _session_has_spec(stage, "/OvGearSession")
        assert not _root_has_spec(stage, "/OvGearSession")

    def test_root_layer_untouched(self, stage):
        ensure_render_scope(stage)
        assert not _root_has_any_prim(stage)

    def test_idempotent(self, stage):
        p1 = ensure_render_scope(stage)
        p2 = ensure_render_scope(stage)
        assert p1.GetPath() == p2.GetPath()
        # Still exactly one child under the session layer's pseudo-root.
        session_prims = stage.GetSessionLayer().rootPrims
        assert len(session_prims) == 1

    def test_custom_path(self, stage):
        prim = ensure_render_scope(stage, scope_path="/Custom/Scope")
        assert str(prim.GetPath()) == "/Custom/Scope"
        assert prim.GetTypeName() == "Scope"


# ── ensure_camera ───────────────────────────────────────────────────────────


class TestEnsureCamera:
    def test_creates_camera(self, stage):
        cam = ensure_camera(stage)
        prim = cam.GetPrim()
        assert prim.IsValid()
        assert prim.GetTypeName() == "Camera"
        assert str(prim.GetPath()) == "/OvGearSession/Cameras/Main"

    def test_defaults(self, stage):
        cam = ensure_camera(stage)
        assert cam.GetFocalLengthAttr().Get() == pytest.approx(18.0)
        assert cam.GetHorizontalApertureAttr().Get() == pytest.approx(20.955)
        assert cam.GetVerticalApertureAttr().Get() == pytest.approx(15.2908)
        clip = cam.GetClippingRangeAttr().Get()
        assert clip[0] == pytest.approx(0.01)
        assert clip[1] == pytest.approx(10000.0)
        assert cam.GetProjectionAttr().Get() == "perspective"

    def test_authored_in_session_layer_only(self, stage):
        ensure_camera(stage)
        assert _session_has_spec(stage, "/OvGearSession/Cameras/Main")
        assert not _root_has_spec(stage, "/OvGearSession/Cameras/Main")
        assert not _root_has_any_prim(stage)

    def test_idempotent(self, stage):
        c1 = ensure_camera(stage)
        c2 = ensure_camera(stage)
        assert c1.GetPath() == c2.GetPath()

    def test_idempotent_preserves_caller_edits(self, stage):
        """Step A.2's matrix writer must not be clobbered by re-calling this helper."""
        cam = ensure_camera(stage)
        # Simulate Step A.2: overwrite several camera attrs in the session layer.
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            cam.GetFocalLengthAttr().Set(35.0)
            cam.GetHorizontalApertureAttr().Set(36.0)
            cam.GetClippingRangeAttr().Set(Gf.Vec2f(0.5, 5000.0))
        ensure_camera(stage)
        assert cam.GetFocalLengthAttr().Get() == pytest.approx(35.0)
        assert cam.GetHorizontalApertureAttr().Get() == pytest.approx(36.0)
        clip = cam.GetClippingRangeAttr().Get()
        assert clip[0] == pytest.approx(0.5)
        assert clip[1] == pytest.approx(5000.0)

    def test_custom_path(self, stage):
        cam = ensure_camera(stage, path="/MyScope/Cam")
        assert str(cam.GetPath()) == "/MyScope/Cam"
        assert cam.GetPrim().GetTypeName() == "Camera"


# ── ensure_ldr_color_var ────────────────────────────────────────────────────


class TestEnsureLdrColorVar:
    def test_creates_var(self, stage):
        var = ensure_ldr_color_var(stage)
        prim = var.GetPrim()
        assert prim.IsValid()
        assert prim.GetTypeName() == "RenderVar"
        assert str(prim.GetPath()) == "/Render/Vars/LdrColor"

    def test_source_name(self, stage):
        var = ensure_ldr_color_var(stage)
        # Value must equal the ovrtx protocol string exactly.
        assert var.GetSourceNameAttr().Get() == "LdrColor"

    def test_source_name_constant_matches_protocol(self):
        assert LDR_SOURCE_NAME == "LdrColor"

    def test_authored_in_session_layer_only(self, stage):
        ensure_ldr_color_var(stage)
        assert _session_has_spec(stage, "/Render/Vars/LdrColor")
        assert not _root_has_spec(stage, "/Render/Vars/LdrColor")
        assert not _root_has_any_prim(stage)

    def test_idempotent(self, stage):
        v1 = ensure_ldr_color_var(stage)
        v2 = ensure_ldr_color_var(stage)
        assert v1.GetPath() == v2.GetPath()

    def test_custom_path(self, stage):
        var = ensure_ldr_color_var(stage, var_path="/My/Vars/Ldr")
        assert str(var.GetPath()) == "/My/Vars/Ldr"


# ── ensure_render_product ───────────────────────────────────────────────────


class TestEnsureRenderProduct:
    def test_creates_product(self, stage):
        product = ensure_render_product(stage)
        prim = product.GetPrim()
        assert prim.IsValid()
        assert prim.GetTypeName() == "RenderProduct"
        assert str(prim.GetPath()) == "/OvGearSession/Render/Viewport"

    def test_camera_rel_targets(self, stage):
        product = ensure_render_product(stage)
        targets = product.GetCameraRel().GetTargets()
        assert targets == [Sdf.Path("/OvGearSession/Cameras/Main")]

    def test_ordered_vars_rel_targets(self, stage):
        product = ensure_render_product(stage)
        targets = product.GetOrderedVarsRel().GetTargets()
        assert targets == [Sdf.Path("/Render/Vars/LdrColor")]

    def test_default_resolution(self, stage):
        product = ensure_render_product(stage)
        res = product.GetResolutionAttr().Get()
        assert (int(res[0]), int(res[1])) == DEFAULT_RESOLUTION

    def test_default_resolution_constant(self):
        assert DEFAULT_RESOLUTION == (1280, 720)

    def test_device_ids_pins_to_cuda_visible_gpu_zero(self, stage):
        product = ensure_render_product(stage)
        attr = product.GetPrim().GetAttribute("deviceIds")
        assert attr.IsValid()
        assert attr.GetTypeName() == Sdf.ValueTypeNames.UIntArray
        assert attr.GetVariability() == Sdf.VariabilityUniform
        assert list(attr.Get()) == [0]

    def test_device_ids_constant_matches_picking_requirement(self):
        assert PICK_RENDER_PRODUCT_DEVICE_IDS == (0,)

    def test_custom_resolution(self, stage):
        product = ensure_render_product(stage, resolution=(1024, 768))
        res = product.GetResolutionAttr().Get()
        assert (int(res[0]), int(res[1])) == (1024, 768)

    def test_resolution_updates_on_recall(self, stage):
        """Calling the helper again with a new resolution re-authors the attr."""
        ensure_render_product(stage, resolution=(1280, 720))
        product = ensure_render_product(stage, resolution=(1920, 1080))
        res = product.GetResolutionAttr().Get()
        assert (int(res[0]), int(res[1])) == (1920, 1080)

    def test_auto_creates_camera_and_var(self, stage):
        ensure_render_product(stage)
        cam = stage.GetPrimAtPath("/OvGearSession/Cameras/Main")
        assert cam.IsValid() and cam.GetTypeName() == "Camera"
        var = stage.GetPrimAtPath("/Render/Vars/LdrColor")
        assert var.IsValid() and var.GetTypeName() == "RenderVar"

    def test_wired_via_relationships(self, stage):
        """RenderProduct.camera must resolve back to the Camera prim."""
        product = ensure_render_product(stage)
        cam_targets = product.GetCameraRel().GetTargets()
        assert len(cam_targets) == 1
        cam_prim = stage.GetPrimAtPath(cam_targets[0])
        assert cam_prim.IsValid()
        assert cam_prim.GetTypeName() == "Camera"

        var_targets = product.GetOrderedVarsRel().GetTargets()
        assert len(var_targets) == 1
        var_prim = stage.GetPrimAtPath(var_targets[0])
        assert var_prim.IsValid()
        assert var_prim.GetTypeName() == "RenderVar"

    def test_authored_in_session_layer_only(self, stage):
        ensure_render_product(stage)
        assert _session_has_spec(stage, "/OvGearSession/Render/Viewport")
        assert _session_has_spec(stage, "/OvGearSession/Cameras/Main")
        assert _session_has_spec(stage, "/Render/Vars/LdrColor")
        assert not _root_has_any_prim(stage)

    def test_idempotent(self, stage):
        p1 = ensure_render_product(stage)
        p2 = ensure_render_product(stage)
        assert p1.GetPath() == p2.GetPath()

    def test_custom_paths(self, stage):
        product = ensure_render_product(
            stage,
            product_path="/Custom/Product",
            camera_path="/Custom/Cam",
            ldr_var_path="/Custom/Var",
            resolution=(640, 480),
        )
        assert str(product.GetPath()) == "/Custom/Product"
        assert product.GetCameraRel().GetTargets() == [Sdf.Path("/Custom/Cam")]
        assert product.GetOrderedVarsRel().GetTargets() == [Sdf.Path("/Custom/Var")]

    def test_can_skip_camera_authoring_for_external_camera(self, stage):
        product = ensure_render_product(
            stage,
            camera_path="/World/ShotCamera",
            ensure_camera_prim=False,
        )

        assert product.GetCameraRel().GetTargets() == [
            Sdf.Path("/World/ShotCamera")
        ]
        assert _session_has_spec(stage, "/OvGearSession/Render/Viewport")
        assert not _session_has_spec(stage, "/World/ShotCamera")

    def test_positional_ensure_camera_flag_still_supported(self, stage):
        product = ensure_render_product(
            stage,
            "/OvGearSession/Render/Viewport",
            "/World/ShotCamera",
            "/Render/Vars/LdrColor",
            DEFAULT_RESOLUTION,
            False,
        )

        assert product.GetCameraRel().GetTargets() == [
            Sdf.Path("/World/ShotCamera")
        ]
        assert not _session_has_spec(stage, "/World/ShotCamera")


# ── ensure_dome_light ───────────────────────────────────────────────────────


class TestEnsureDomeLight:
    def test_creates_when_stage_has_no_lights(self, stage):
        dome = ensure_dome_light(stage)
        assert dome is not None
        assert dome.GetPrim().IsValid()
        assert dome.GetPrim().GetTypeName() == "DomeLight"
        assert str(dome.GetPath()) == "/OvGearSession/Lights/FallbackDome"

    def test_default_intensity(self, stage):
        dome = ensure_dome_light(stage)
        assert dome.GetIntensityAttr().Get() == pytest.approx(1000.0)

    def test_custom_intensity(self, stage):
        dome = ensure_dome_light(stage, intensity=500.0)
        assert dome.GetIntensityAttr().Get() == pytest.approx(500.0)

    def test_authored_in_session_layer_only(self, stage):
        ensure_dome_light(stage)
        assert _session_has_spec(stage, "/OvGearSession/Lights/FallbackDome")
        assert not _root_has_any_prim(stage)

    def test_skipped_when_dome_light_already_in_root(self, stage):
        UsdLux.DomeLight.Define(stage, "/World/UserDome")
        result = ensure_dome_light(stage)
        assert result is None
        assert not _session_has_spec(stage, "/OvGearSession/Lights/FallbackDome")

    def test_skipped_when_distant_light_in_root(self, stage):
        UsdLux.DistantLight.Define(stage, "/World/Sun")
        assert ensure_dome_light(stage) is None

    def test_skipped_when_sphere_light_in_root(self, stage):
        UsdLux.SphereLight.Define(stage, "/World/Bulb")
        assert ensure_dome_light(stage) is None

    def test_skipped_when_rect_light_in_root(self, stage):
        UsdLux.RectLight.Define(stage, "/World/Panel")
        assert ensure_dome_light(stage) is None

    def test_idempotent_when_we_own_the_dome(self, stage):
        d1 = ensure_dome_light(stage)
        d2 = ensure_dome_light(stage)
        assert d1 is not None and d2 is not None
        assert d1.GetPath() == d2.GetPath()

    def test_custom_path(self, stage):
        dome = ensure_dome_light(stage, path="/Custom/Dome")
        assert dome is not None
        assert str(dome.GetPath()) == "/Custom/Dome"


# ── Integrated session setup ───────────────────────────────────────────────


class TestFullSessionSetup:
    def test_all_helpers_on_empty_stage(self, stage):
        ensure_render_scope(stage)
        ensure_camera(stage)
        ensure_ldr_color_var(stage)
        ensure_render_product(stage)
        ensure_dome_light(stage)
        # Root layer remains byte-identical to an empty stage.
        assert not _root_has_any_prim(stage)
        # Every expected prim is present in the session layer.
        for path in (
            "/OvGearSession",
            "/OvGearSession/Cameras/Main",
            "/OvGearSession/Render/Viewport",
            "/Render/Vars/LdrColor",
            "/OvGearSession/Lights/FallbackDome",
        ):
            assert _session_has_spec(stage, path), f"missing session spec: {path}"

    def test_session_export_contains_prims(self, stage):
        ensure_camera(stage)
        ensure_ldr_color_var(stage)
        ensure_render_product(stage)
        ensure_dome_light(stage)
        session_str = stage.GetSessionLayer().ExportToString()
        for needle in (
            "def Camera ",
            "def RenderProduct ",
            "def RenderVar ",
            "def DomeLight ",
            "uniform uint[] deviceIds = [0]",
            'sourceName = "LdrColor"',
            "resolution = (1280, 720)",
        ):
            assert needle in session_str, f"missing in session export: {needle!r}"

    def test_root_layer_byte_identical_after_setup(self, stage):
        before = stage.GetRootLayer().ExportToString()
        ensure_render_scope(stage)
        ensure_camera(stage)
        ensure_ldr_color_var(stage)
        ensure_render_product(stage)
        ensure_dome_light(stage)
        after = stage.GetRootLayer().ExportToString()
        assert before == after

    def test_user_lighting_preserved_through_full_setup(self, stage):
        UsdLux.SphereLight.Define(stage, "/World/Key")
        ensure_render_scope(stage)
        ensure_camera(stage)
        ensure_ldr_color_var(stage)
        ensure_render_product(stage)
        assert ensure_dome_light(stage) is None
        # User's light remains, no fallback dome authored.
        user_light = stage.GetPrimAtPath("/World/Key")
        assert user_light.IsValid()
        assert _root_has_spec(stage, "/World/Key")
        assert not _session_has_spec(stage, "/OvGearSession/Lights/FallbackDome")

    def test_all_helpers_idempotent_when_called_twice(self, stage):
        for _ in range(2):
            ensure_render_scope(stage)
            ensure_camera(stage)
            ensure_ldr_color_var(stage)
            ensure_render_product(stage)
            ensure_dome_light(stage)
        # Re-verify the camera prim is singular.
        cam_prim = stage.GetPrimAtPath("/OvGearSession/Cameras/Main")
        assert cam_prim.IsValid()
        # And the dome is singular.
        dome_prim = stage.GetPrimAtPath("/OvGearSession/Lights/FallbackDome")
        assert dome_prim.IsValid()
        # Root still pristine.
        assert not _root_has_any_prim(stage)
