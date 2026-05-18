# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Session-layer USD authoring helpers for the ovrtx viewport integration.

ovrtx reads scene, camera, and render-output definitions from USD prims. To
steer ovrtx from OvGear (camera controller, resolution changes) without
mutating the user's USD file, all OvGear-owned scaffolding prims
(``/OvGearSession/...``, render product, LDR render variable, fallback dome
light) are authored in the stage's **session layer**. Session writes are
discarded on stage close and never dirty the root layer.

Each helper here is a pure function that mutates the stage through an
``Usd.EditContext`` bound to ``stage.GetSessionLayer()``. Functions are
idempotent: calling them twice never duplicates prims and (for the camera)
never overwrites values that Step A.2's matrix writer has authored.

See the viewport behavior
"""

from __future__ import annotations

from typing import Optional, Tuple

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdRender

# Camera intrinsic defaults. Aperture values are lifted from the ovrtx
# reference scene ``planet-system/simple_scene.usda`` so scenes authored
# against that example frame identically in OvGear. Focal length is 18 (the
# plan-spec default); clip range mirrors the plan's 0.01/10000.
_DEFAULT_FOCAL_LENGTH = 18.0
_DEFAULT_H_APERTURE = 20.955
_DEFAULT_V_APERTURE = 15.2908
_DEFAULT_CLIP_NEAR = 0.01
_DEFAULT_CLIP_FAR = 10000.0

# Render product / var defaults.
DEFAULT_RESOLUTION: Tuple[int, int] = (1280, 720)
LDR_SOURCE_NAME = "LdrColor"
PICK_RENDER_PRODUCT_DEVICE_IDS: Tuple[int, ...] = (0,)

# Fallback dome light intensity. 1000 matches the planet-system example.
_DEFAULT_DOME_INTENSITY = 1000.0


def _session_edit(stage: Usd.Stage) -> Usd.EditContext:
    """Return an ``Usd.EditContext`` targeting the session layer."""
    return Usd.EditContext(stage, stage.GetSessionLayer())


def ensure_render_scope(
    stage: Usd.Stage,
    scope_path: str = "/OvGearSession",
) -> Usd.Prim:
    """Ensure a ``UsdGeomScope`` exists at ``scope_path`` in the session layer.

    Idempotent — re-calling returns the existing prim without creating a
    duplicate spec.
    """
    with _session_edit(stage):
        UsdGeom.Scope.Define(stage, scope_path)
    return stage.GetPrimAtPath(scope_path)


def ensure_camera(
    stage: Usd.Stage,
    path: str = "/OvGearSession/Cameras/Main",
) -> UsdGeom.Camera:
    """Ensure a ``UsdGeomCamera`` exists at ``path`` with OvGear defaults.

    On first creation, authors focalLength=18, horizontalAperture=20.955,
    verticalAperture=15.2908, clippingRange=(0.01, 10000), projection=
    perspective. On subsequent calls the existing prim is returned and its
    attributes are left untouched so that Step A.2's per-frame matrix writer
    can author its own values without being clobbered.

    Note: if the path already holds a ``Camera`` prim in any layer (e.g.,
    the user's root layer), defaults are not re-authored — the existing
    camera wins.
    """
    existing = stage.GetPrimAtPath(path)
    already_defined = existing.IsValid() and existing.GetTypeName() == "Camera"
    with _session_edit(stage):
        cam = UsdGeom.Camera.Define(stage, path)
        if not already_defined:
            cam.CreateFocalLengthAttr(_DEFAULT_FOCAL_LENGTH)
            cam.CreateHorizontalApertureAttr(_DEFAULT_H_APERTURE)
            cam.CreateVerticalApertureAttr(_DEFAULT_V_APERTURE)
            cam.CreateClippingRangeAttr(
                Gf.Vec2f(_DEFAULT_CLIP_NEAR, _DEFAULT_CLIP_FAR)
            )
            cam.CreateProjectionAttr(UsdGeom.Tokens.perspective)
    return cam


def ensure_ldr_color_var(
    stage: Usd.Stage,
    var_path: str = "/Render/Vars/LdrColor",
) -> UsdRender.Var:
    """Ensure a ``UsdRender.Var`` exists at ``var_path`` with sourceName=LdrColor.

    ``sourceName`` must match the string ovrtx publishes for the LDR color
    output; changing it on subsequent calls is therefore not useful, so the
    attribute is only authored when the prim is being defined for the first
    time.
    """
    existing = stage.GetPrimAtPath(var_path)
    already_defined = existing.IsValid() and existing.GetTypeName() == "RenderVar"
    with _session_edit(stage):
        var = UsdRender.Var.Define(stage, var_path)
        if not already_defined:
            var.CreateSourceNameAttr(LDR_SOURCE_NAME)
    return var


def ensure_render_product(
    stage: Usd.Stage,
    product_path: str = "/OvGearSession/Render/Viewport",
    camera_path: str = "/OvGearSession/Cameras/Main",
    ldr_var_path: str = "/Render/Vars/LdrColor",
    resolution: Tuple[int, int] = DEFAULT_RESOLUTION,
    ensure_camera_prim: bool = True,
    device_ids: Tuple[int, ...] = PICK_RENDER_PRODUCT_DEVICE_IDS,
) -> UsdRender.Product:
    """Ensure a ``UsdRender.Product`` is wired to the camera and LDR var.

    Creates the referenced camera and render var (via :func:`ensure_camera`
    and :func:`ensure_ldr_color_var`) when they do not exist, then defines
    the render product with ``camera``, ``orderedVars``, and ``resolution``
    (re-)authored on every call — callers can use this helper to respond to
    window resizes or to re-target the camera rel.
    """
    if ensure_camera_prim:
        ensure_camera(stage, camera_path)
    ensure_ldr_color_var(stage, ldr_var_path)
    with _session_edit(stage):
        product = UsdRender.Product.Define(stage, product_path)
        product.CreateCameraRel().SetTargets([Sdf.Path(camera_path)])
        product.CreateOrderedVarsRel().SetTargets([Sdf.Path(ldr_var_path)])
        product.CreateResolutionAttr().Set(
            Gf.Vec2i(int(resolution[0]), int(resolution[1]))
        )
        product.GetPrim().CreateAttribute(
            "deviceIds",
            Sdf.ValueTypeNames.UIntArray,
            custom=False,
            variability=Sdf.VariabilityUniform,
        ).Set([int(device_id) for device_id in device_ids])
    return product


def _stage_has_any_light(stage: Usd.Stage) -> bool:
    """True if any UsdLux light prim exists anywhere on the stage.

    O(N) traversal over all prims (including inactive / abstract) — the
    stage is typically small when this is called (once at viewport init).
    """
    for prim in stage.TraverseAll():
        if prim.HasAPI(UsdLux.LightAPI):
            return True
    return False


def ensure_dome_light(
    stage: Usd.Stage,
    path: str = "/OvGearSession/Lights/FallbackDome",
    intensity: float = _DEFAULT_DOME_INTENSITY,
) -> Optional[UsdLux.DomeLight]:
    """Ensure a fallback dome light exists — but only when the stage has none.

    Returns the dome light when one was created (or was already at ``path``
    from a prior call); returns ``None`` when the stage already has any
    light authored and the user's lighting should be preserved instead.
    """
    existing = stage.GetPrimAtPath(path)
    if existing and existing.IsValid() and existing.IsA(UsdLux.DomeLight):
        # Already created by a previous call — idempotent branch.
        return UsdLux.DomeLight(existing)
    if _stage_has_any_light(stage):
        return None
    with _session_edit(stage):
        dome = UsdLux.DomeLight.Define(stage, path)
        dome.CreateIntensityAttr(float(intensity))
    return dome
