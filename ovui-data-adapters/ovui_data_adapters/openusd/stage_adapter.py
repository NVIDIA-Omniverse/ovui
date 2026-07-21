# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""USD-backed StageAdapter wrapping a Usd.Stage.

Hierarchy traversal from Step 22; Step 23 adds visibility edits,
rename/reparent (all undoable via UndoManager), and change notifications.
"""

from __future__ import annotations

import contextlib
import math
import os
import re
import sys
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional

try:
    from pxr import Sdf, Tf, Usd, UsdGeom
    try:
        from pxr import UsdLux
    except ImportError:
        UsdLux = None  # type: ignore[assignment]
    try:
        from pxr import UsdShade
    except ImportError:
        UsdShade = None  # type: ignore[assignment]
    try:
        from pxr import UsdRender
    except ImportError:
        UsdRender = None  # type: ignore[assignment]
    HAS_USD = True
except ImportError:
    HAS_USD = False
    Usd = Sdf = Tf = UsdGeom = UsdLux = UsdShade = UsdRender = None  # type: ignore[assignment]

from ovui_data_adapters.common import (
    AdapterItem,
    BadgeFlags,
    BoundCameraPose,
    ChangeEvent,
    ChangeEventType,
    ContextManager,
    CreateActionCatalog,
    CreateActionCategory,
    CreateActionCategoryDescriptor,
    CreateActionDescriptor,
    CreateActionErrorCode,
    CreateActionRequirement,
    CreateActionWarning,
    CreateActionWarningSeverity,
    CreateActionsAdapter,
    CreateBindingPolicy,
    CreatePlacementPolicy,
    CreateRequest,
    CreateResult,
    CreateSelectionPolicy,
    CoreMaterialBindingPolicy,
    CoreMaterialCatalog,
    CoreMaterialDescriptor,
    CoreMaterialErrorCode,
    CoreMaterialFamily,
    CoreMaterialGroupDescriptor,
    CoreMaterialKind,
    CoreMaterialRequirement,
    CoreMaterialsAdapter,
    CoreMaterialWarning,
    CoreMaterialWarningSeverity,
    BindMaterialRequest,
    BindMaterialResult,
    CreateAndBindMaterialResult,
    CreateMaterialRequest,
    CreateMaterialResult,
    ItemFlags,
    RenderTargetCatalog,
    RenderTargetDescriptor,
    RenderTargetKind,
    RenderTargetOutputKind,
    RenderTargetWarning,
    ReparentPosition,
    StageAdapter,
    StageChoice,
    SubscriptionProtocol,
    VisibilityState,
)


def _is_live_prim(item: Any) -> bool:
    """Return ``True`` iff ``item`` is a live ``Usd.Prim`` reference.

    The Stage tree model captures ``Usd.Prim`` handles when it builds
    rows; deleting a prim (e.g. ``DeletePrimCommand`` or any other
    ``Sdf.BatchNamespaceEdit``-Apply) invalidates those handles a few
    frames before the model rebuilds. Any subsequent attribute access
    on the expired handle raises ``RuntimeError: Accessed invalid
    expired '<name>' prim`` (or ``Accessed invalid null prim`` when
    the handle never resolved). The Stage delegate calls into adapter
    methods like ``get_children`` / ``get_type_category`` /
    ``can_edit_visibility`` from per-frame ``build_branch`` /
    ``build_widget`` / ``can_toggle_now`` — those must short-circuit
    on stale prims and return safe defaults so the delegate frame
    completes without raising. Codex final-UI-QA rerun (2026-05-08)
    captured this regression on `tests/data/simple_scene.usda` →
    `/World/Cube` after the Delete-key path.
    """
    if item is None:
        return False
    is_valid = getattr(item, "IsValid", None)
    if is_valid is None:
        # Not a USD object — caller passed something else (e.g. a
        # path string in a test). Treat as live so we don't suppress
        # useful errors elsewhere.
        return True
    try:
        return bool(is_valid())
    except Exception:
        # An expired ``Usd.Prim`` may itself raise on ``IsValid()``
        # in pathological cases. Treat any exception as "not live".
        return False


def _choice_for_prim(prim: Any) -> StageChoice:
    path = str(prim.GetPath())
    return StageChoice(path=path, display_name=path)


_IMAGE_OUTPUT_TOKENS = {
    "beauty",
    "color",
    "hdrcolor",
    "ldrcolor",
    "rgb",
    "rgba",
}
_POINT_CLOUD_OUTPUT_TOKENS = {
    "pointcloud",
}
_GENERIC_MODEL_OUTPUT_TOKENS = {
    "genericmodeloutput",
}
_SENSOR_SOURCE_MARKERS = (
    "sensor",
    "lidar",
    "radar",
)


def _token_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _warning(code: str, message: str) -> RenderTargetWarning:
    return RenderTargetWarning(code=code, message=message)


def _source_targets(product: Any) -> list[Any]:
    try:
        return list(product.GetCameraRel().GetTargets())
    except Exception:
        return []


def _ordered_var_targets(product: Any) -> list[Any]:
    try:
        return list(product.GetOrderedVarsRel().GetTargets())
    except Exception:
        return []


def _source_descriptor(
    stage: Any,
    product: Any,
) -> tuple[RenderTargetKind, Optional[str], str, str, list[RenderTargetWarning]]:
    warnings: list[RenderTargetWarning] = []
    targets = _source_targets(product)
    if not targets:
        warnings.append(_warning(
            "missing_source",
            "RenderProduct has no camera or sensor target.",
        ))
        return RenderTargetKind.RENDER_PRODUCT, None, "", "", warnings

    source_path = str(targets[0])
    prim = stage.GetPrimAtPath(targets[0])
    if not prim or not prim.IsValid():
        warnings.append(_warning(
            "missing_source",
            f"RenderProduct source {source_path} does not exist.",
        ))
        return RenderTargetKind.RENDER_PRODUCT, source_path, "", "", warnings

    source_type = str(prim.GetTypeName() or "")
    source_name = prim.GetName() or source_path
    if UsdGeom is not None and prim.IsA(UsdGeom.Camera):
        return RenderTargetKind.CAMERA, source_path, source_name, source_type, warnings

    schema_text = " ".join([
        source_type,
        *[str(schema) for schema in prim.GetAppliedSchemas()],
    ])
    if any(marker in schema_text.lower() for marker in _SENSOR_SOURCE_MARKERS):
        return RenderTargetKind.SENSOR, source_path, source_name, source_type, warnings

    warnings.append(_warning(
        "unknown_source",
        f"RenderProduct source {source_path} is not a known camera or sensor.",
    ))
    return RenderTargetKind.RENDER_PRODUCT, source_path, source_name, source_type, warnings


def _render_var_name(stage: Any, var_path: Any) -> tuple[str, Optional[RenderTargetWarning]]:
    prim = stage.GetPrimAtPath(var_path)
    if not prim or not prim.IsValid() or not prim.IsA(UsdRender.Var):
        return str(var_path), _warning(
            "missing_render_var",
            f"RenderVar {var_path} does not exist.",
        )
    var = UsdRender.Var(prim)
    try:
        source_name = var.GetSourceNameAttr().Get()
    except Exception:
        source_name = None
    return str(source_name or prim.GetName() or var_path), None


def _output_metadata(
    stage: Any,
    product: Any,
) -> tuple[RenderTargetOutputKind, tuple[str, ...], list[str], list[RenderTargetWarning]]:
    warnings: list[RenderTargetWarning] = []
    names: list[str] = []
    for var_path in _ordered_var_targets(product):
        output_name, warning = _render_var_name(stage, var_path)
        names.append(output_name)
        if warning is not None:
            warnings.append(warning)

    if not names:
        warnings.append(_warning(
            "unknown_output",
            "RenderProduct has no ordered RenderVars.",
        ))
        return RenderTargetOutputKind.UNKNOWN, (), [], warnings

    tokens = [_token_key(name) for name in names]
    has_image = any(token in _IMAGE_OUTPUT_TOKENS for token in tokens)
    has_point_cloud = any(token in _POINT_CLOUD_OUTPUT_TOKENS for token in tokens)
    has_generic = any(token in _GENERIC_MODEL_OUTPUT_TOKENS for token in tokens)

    if len(names) > 1:
        return RenderTargetOutputKind.MULTI_OUTPUT, tuple(names), tokens, warnings
    if has_image:
        return RenderTargetOutputKind.IMAGE, tuple(names), tokens, warnings
    if has_point_cloud:
        return RenderTargetOutputKind.POINT_CLOUD, tuple(names), tokens, warnings
    if has_generic:
        return RenderTargetOutputKind.GENERIC_MODEL_OUTPUT, tuple(names), tokens, warnings

    warnings.append(_warning(
        "unknown_output",
        f"RenderProduct output {names[0]!r} is unknown.",
    ))
    return RenderTargetOutputKind.UNKNOWN, tuple(names), tokens, warnings


def _resolution(product: Any) -> tuple[tuple[int, int] | None, Optional[RenderTargetWarning]]:
    attr = product.GetResolutionAttr()
    if not attr or not attr.HasAuthoredValue():
        return None, _warning("missing_resolution", "RenderProduct has no authored resolution.")
    value = attr.Get()
    if value is None:
        return None, _warning("missing_resolution", "RenderProduct resolution is unknown.")
    try:
        return (int(value[0]), int(value[1])), None
    except Exception:
        return None, _warning("missing_resolution", "RenderProduct resolution is invalid.")


def _capabilities(
    output_tokens: list[str],
    output_kind: RenderTargetOutputKind,
) -> tuple[str, ...]:
    capabilities: list[str] = []
    if any(token in _IMAGE_OUTPUT_TOKENS for token in output_tokens):
        capabilities.extend(["image_render_target", "set_active_render_product"])
    if any(token in _POINT_CLOUD_OUTPUT_TOKENS for token in output_tokens):
        capabilities.append("point_cloud_output")
    if any(token in _GENERIC_MODEL_OUTPUT_TOKENS for token in output_tokens):
        capabilities.append("generic_model_output")
    if output_kind is RenderTargetOutputKind.MULTI_OUTPUT:
        capabilities.append("multi_output")
    return tuple(capabilities)


def _disabled_reason(
    source_path: Optional[str],
    output_kind: RenderTargetOutputKind,
    capabilities: tuple[str, ...],
    warnings: list[RenderTargetWarning],
) -> str:
    if not source_path or any(warning.code == "missing_source" for warning in warnings):
        return "RenderProduct has no valid source camera or sensor."
    if "image_render_target" in capabilities:
        return ""
    if output_kind is RenderTargetOutputKind.POINT_CLOUD:
        return "PointCloud output requires point-cloud viewport support."
    if output_kind is RenderTargetOutputKind.GENERIC_MODEL_OUTPUT:
        return "Generic model output is not supported by the image viewport."
    if output_kind is RenderTargetOutputKind.MULTI_OUTPUT:
        return "RenderProduct outputs are not supported by the image viewport."
    return "RenderProduct output kind is unknown."


def _render_target_descriptor(stage: Any, prim: Any) -> RenderTargetDescriptor:
    product = UsdRender.Product(prim)
    path = str(prim.GetPath())
    kind, source_path, source_name, source_type, warnings = _source_descriptor(stage, product)
    output_kind, output_names, output_tokens, output_warnings = _output_metadata(stage, product)
    warnings.extend(output_warnings)
    resolution, resolution_warning = _resolution(product)
    if resolution_warning is not None:
        warnings.append(resolution_warning)
    capabilities = _capabilities(output_tokens, output_kind)
    disabled_reason = _disabled_reason(source_path, output_kind, capabilities, warnings)
    if disabled_reason and "image_render_target" not in capabilities:
        warnings.append(_warning("unsupported_output", disabled_reason))

    return RenderTargetDescriptor(
        target_id=path,
        render_product_path=path,
        display_name=source_name or prim.GetName() or path,
        kind=kind,
        source_path=source_path,
        source_display_name=source_name,
        source_type=source_type,
        output_kind=output_kind,
        output_names=output_names,
        resolution=resolution,
        capabilities=capabilities,
        warnings=tuple(warnings),
        enabled=not disabled_reason,
        disabled_reason=disabled_reason,
    )


def _is_property_path_string(path: str) -> bool:
    """True when ``path`` names a property (prim path + '.' + property)."""
    prim, separator, prop = str(path).rpartition(".")
    return bool(separator) and bool(prim) and bool(prop)


def _is_transform_property_name(name: str) -> bool:
    return name == "xformOpOrder" or name.startswith("xformOp:")



def _retain_failed_revocation(owner: object, handle: object) -> None:
    stale = getattr(owner, "_stale_subscription_handles", None)
    if stale is None:
        try:
            stale = []
            setattr(owner, "_stale_subscription_handles", stale)
        except Exception:
            return
    # Identity-deduplicated: repeated failures of ONE handle retain it
    # exactly once. Retention is NEVER capped: every live registration
    # keeps durable owner-side revocation ownership, and the collection
    # is finite by construction — at most one small handle per admitted
    # registration.
    if not any(existing is handle for existing in stale):
        stale.append(handle)


def _drain_stale_revocations(owner: object) -> None:
    """Retry every retained failed revocation; drop the resolved ones."""
    stale = getattr(owner, "_stale_subscription_handles", None)
    if not stale:
        return
    remaining = []
    for handle in stale:
        try:
            handle.cancel()
        except BaseException:  # noqa: BLE001 — still owned for retry
            if not any(existing is handle for existing in remaining):
                remaining.append(handle)
    stale[:] = remaining

class _StageSubscription:
    """Private subscription handle for ``UsdStageAdapter.subscribe_changes``.

    Step 13: replaces the prior dependency on
    ``ovui_widgets.common.settings.Subscription`` so the moved openusd
    stage adapter carries zero ``ovui_widgets.*`` runtime imports.
    Structurally satisfies :class:`SubscriptionProtocol` from
    :mod:`ovui_data_adapters.common` — a no-arg ``cancel()`` method is
    the only required surface.
    """

    def __init__(
        self,
        owner_ref: "weakref.ref[Any]",
        key: str,
        callback: Callable,
    ) -> None:
        self._owner_ref = owner_ref
        self._key = key
        self._callback = callback
        self._cancelled = False

    def cancel(self) -> None:
        """Remove this subscriber from the owning adapter."""
        if self._cancelled:
            return
        owner = self._owner_ref()
        if owner is not None:
            # Mark cancelled only AFTER removal succeeded: a failed
            # revocation stays owned and genuinely retryable — retained
            # by the OWNER, so garbage collection of this handle can
            # never turn a live callback into an unowned registration.
            try:
                owner._remove_subscriber(self._key, self._callback)
            except BaseException:
                _retain_failed_revocation(owner, self)
                raise
        self._cancelled = True

    def __del__(self) -> None:
        try:
            self.cancel()
        except BaseException:  # noqa: BLE001 — never unraisable: the
            # owner already retains durable revocation ownership.
            pass


_NAME_RE = re.compile(r"[^A-Za-z0-9_]")

# Lowercase USD schema type name → icon name registered in StageIcons.
# Concrete light/mesh types resolve to their own icon keys so StageIcons can
# ship per-type artwork; unmapped types fall back to the "Prim" default at
# lookup time (Step 13 wires the real registration).
_ICON_MAP: dict[str, str] = {
    "mesh": "Mesh",
    "sphere": "Mesh", "cube": "Mesh", "cone": "Mesh", "cylinder": "Mesh",
    "capsule": "Mesh", "plane": "Mesh",
    "basiscurves": "Mesh", "points": "Mesh",
    "nurbscurves": "Mesh", "nurbspatch": "Mesh",
    "camera": "Camera",
    "distantlight": "DistantLight",
    "domelight": "DomeLight",
    "spherelight": "SphereLight",
    "rectlight": "RectLight",
    "disklight": "DiskLight",
    "cylinderlight": "CylinderLight",
    "renderproduct": "Prim",
    "scope": "Scope",
    "xform": "Xform",
}

# Lowercase USD schema type name → high-level display category. Categories
# drive icon choice and filter grouping; type labels themselves stay visually
# neutral. Keep these values in sync with
# ``ovui_data_adapters.common.adapters._DEFAULT_TYPE_CATEGORY_MAP``.
_TYPE_CATEGORY_MAP: dict[str, str] = {
    "sphere": "Mesh",
    "cube": "Mesh",
    "cone": "Mesh",
    "cylinder": "Mesh",
    "capsule": "Mesh",
    "plane": "Mesh",
    "basiscurves": "Mesh",
    "points": "Mesh",
    "nurbscurves": "Mesh",
    "nurbspatch": "Mesh",
    "mesh": "Mesh",
    "domelight": "Light",
    "distantlight": "Light",
    "disklight": "Light",
    "rectlight": "Light",
    "spherelight": "Light",
    "cylinderlight": "Light",
    "camera": "Camera",
    "xform": "Xform",
    "scope": "Scope",
}


@dataclass(frozen=True)
class _CreateActionSpec:
    action_id: str
    label: str
    category: CreateActionCategory
    target_prim_type: str
    prim_kind: str
    order: float
    description: str = ""
    capabilities: tuple[str, ...] = ()
    requirements: tuple[CreateActionRequirement, ...] = (
        CreateActionRequirement.ACTIVE_STAGE,
        CreateActionRequirement.WRITABLE_EDIT_TARGET,
    )
    placement_policy: CreatePlacementPolicy = CreatePlacementPolicy.DEFAULT_PARENT
    selection_policy: CreateSelectionPolicy = CreateSelectionPolicy.SELECT_PRIMARY
    binding_policy: CreateBindingPolicy = CreateBindingPolicy.NONE
    default_parent_path: str = "/World"
    default_name: str = ""
    schema_family: str = "usd"
    unsupported_reason: str = ""


@dataclass(frozen=True)
class _CoreMaterialSpec:
    material_id: str
    label: str
    group_id: str
    family: CoreMaterialFamily
    kind: CoreMaterialKind
    shader_type: str
    order: float
    default_scope_path: str
    default_name: str
    capabilities: tuple[str, ...] = ()
    requirements: tuple[CoreMaterialRequirement, ...] = (
        CoreMaterialRequirement.ACTIVE_STAGE,
        CoreMaterialRequirement.WRITABLE_EDIT_TARGET,
        CoreMaterialRequirement.MATERIAL_SCHEMA,
    )
    binding_policy: CoreMaterialBindingPolicy = CoreMaterialBindingPolicy.OPTIONAL_BIND_TO_SELECTION
    schema_family: str = "usd_shade"


def _create_action_default_name(action: CreateActionDescriptor) -> str:
    fallback = action.default_name or action.label
    return fallback[:1].upper() + fallback[1:]


def _create_mesh_name(action: CreateActionDescriptor) -> str:
    return _create_action_default_name(action)


_UNSUPPORTED_SENSOR_SCHEMA_REASON = (
    "No supported OpenUSD sensor creation schema is available in this adapter."
)
_UNSUPPORTED_DECAL_SCHEMA_REASON = (
    "No supported OpenUSD decal creation schema is available in this adapter."
)
_UNSUPPORTED_PROJECTOR_SCHEMA_REASON = (
    "No supported OpenUSD projector creation schema is available in this adapter."
)
_RENDERING_PARENT_PATH = ("Create", "Rendering")
_RENDERING_GROUP_CATEGORY_IDS = {
    CreateActionCategory.RENDER_PRODUCTS.value,
    CreateActionCategory.SENSORS.value,
    CreateActionCategory.DECALS.value,
    CreateActionCategory.PROJECTORS.value,
}
_POINT_CLOUD_RENDER_VAR_CHANNELS = (
    "Coordinates",
    "Intensity",
    "Counts",
    "Flags",
    "TimeOffsetNs",
)
_MDL_SEARCH_ENV_VARS = (
    "OVUI_MDL_LIBRARY_PATH",
    "OVRTX_MDL_LIBRARY_PATH",
    "MDL_SEARCH_PATH",
    "PXR_MDL_SEARCH_PATH",
)

_GEOMETRY_ACTION_SPECS: tuple[_CreateActionSpec, ...] = (
    _CreateActionSpec("create.geometry.mesh.cone", "Cone", CreateActionCategory.MESH, "Mesh", "mesh", 0, default_name="Cone"),
    _CreateActionSpec("create.geometry.mesh.cube", "Cube", CreateActionCategory.MESH, "Mesh", "mesh", 10, default_name="Cube"),
    _CreateActionSpec("create.geometry.mesh.cylinder", "Cylinder", CreateActionCategory.MESH, "Mesh", "mesh", 20, default_name="Cylinder"),
    _CreateActionSpec("create.geometry.mesh.disk", "Disk", CreateActionCategory.MESH, "Mesh", "mesh", 30, default_name="Disk"),
    _CreateActionSpec("create.geometry.mesh.plane", "Plane", CreateActionCategory.MESH, "Mesh", "mesh", 40, default_name="Plane"),
    _CreateActionSpec("create.geometry.mesh.sphere", "Sphere", CreateActionCategory.MESH, "Mesh", "mesh", 50, default_name="Sphere"),
    _CreateActionSpec("create.geometry.mesh.torus", "Torus", CreateActionCategory.MESH, "Mesh", "mesh", 60, default_name="Torus"),
    _CreateActionSpec("create.geometry.shape.capsule", "Capsule", CreateActionCategory.SHAPE, "Capsule", "shape", 0, default_name="Capsule"),
    _CreateActionSpec("create.geometry.shape.cone", "Cone", CreateActionCategory.SHAPE, "Cone", "shape", 10, default_name="Cone"),
    _CreateActionSpec("create.geometry.shape.cube", "Cube", CreateActionCategory.SHAPE, "Cube", "shape", 20, default_name="Cube"),
    _CreateActionSpec("create.geometry.shape.cylinder", "Cylinder", CreateActionCategory.SHAPE, "Cylinder", "shape", 30, default_name="Cylinder"),
    _CreateActionSpec("create.geometry.shape.sphere", "Sphere", CreateActionCategory.SHAPE, "Sphere", "shape", 40, default_name="Sphere"),
)

_LIGHT_ACTION_SPECS: tuple[_CreateActionSpec, ...] = (
    _CreateActionSpec("create.light.cylinder", "Cylinder Light", CreateActionCategory.LIGHTS, "CylinderLight", "light", 0, default_name="CylinderLight", schema_family="usd_lux"),
    _CreateActionSpec("create.light.disk", "Disk Light", CreateActionCategory.LIGHTS, "DiskLight", "light", 10, default_name="DiskLight", schema_family="usd_lux"),
    _CreateActionSpec("create.light.distant", "Distant Light", CreateActionCategory.LIGHTS, "DistantLight", "light", 20, default_name="DistantLight", schema_family="usd_lux"),
    _CreateActionSpec("create.light.dome", "Dome Light", CreateActionCategory.LIGHTS, "DomeLight", "light", 30, default_name="DomeLight", schema_family="usd_lux"),
    _CreateActionSpec("create.light.rect", "Rect Light", CreateActionCategory.LIGHTS, "RectLight", "light", 40, default_name="RectLight", schema_family="usd_lux"),
    _CreateActionSpec("create.light.sphere", "Sphere Light", CreateActionCategory.LIGHTS, "SphereLight", "light", 50, default_name="SphereLight", schema_family="usd_lux"),
)

_OTHER_CREATE_ACTION_SPECS: tuple[_CreateActionSpec, ...] = (
    _CreateActionSpec(
        "create.render_product",
        "Render Product",
        CreateActionCategory.RENDER_PRODUCTS,
        "RenderProduct",
        "render_product",
        0,
        default_parent_path="/Render/Products",
        default_name="RenderProduct",
        schema_family="usd_render",
    ),
    _CreateActionSpec("create.sensor.generic-lidar", "Generic Lidar Sensor", CreateActionCategory.SENSORS, "OmniLidar", "sensor", 0, default_name="Lidar", schema_family="sensor"),
    _CreateActionSpec("create.camera", "Camera", CreateActionCategory.CAMERAS, "Camera", "camera", 0, default_name="Camera"),
    _CreateActionSpec("create.scope", "Scope", CreateActionCategory.SCOPES, "Scope", "scope", 0, default_parent_path="/", default_name="Scope"),
    _CreateActionSpec("create.xform", "Xform", CreateActionCategory.TRANSFORMS, "Xform", "xform", 0, default_name="Xform"),
    _CreateActionSpec("create.decal", "Decal", CreateActionCategory.DECALS, "Decal", "decal", 0, default_name="Decal", schema_family="decal", unsupported_reason=_UNSUPPORTED_DECAL_SCHEMA_REASON),
    _CreateActionSpec("create.projector", "Projector", CreateActionCategory.PROJECTORS, "Projector", "projector", 0, default_name="Projector", schema_family="projector", unsupported_reason=_UNSUPPORTED_PROJECTOR_SCHEMA_REASON),
    _CreateActionSpec("create.material.usd-preview-surface", "USD Preview Surface", CreateActionCategory.MATERIALS, "Material", "material", 0, default_parent_path="/World/Looks", default_name="PreviewSurface", schema_family="usd_shade"),
    _CreateActionSpec(
        "create.material.usd-preview-surface.bind",
        "USD Preview Surface and Bind to Selection",
        CreateActionCategory.MATERIALS,
        "Material",
        "material",
        10,
        default_parent_path="/World/Looks",
        default_name="PreviewSurface",
        schema_family="usd_shade",
        requirements=(
            CreateActionRequirement.ACTIVE_STAGE,
            CreateActionRequirement.WRITABLE_EDIT_TARGET,
            CreateActionRequirement.SELECTION,
        ),
        binding_policy=CreateBindingPolicy.BIND_TO_SELECTION,
    ),
)

_CREATE_ACTION_SPECS: tuple[_CreateActionSpec, ...] = (
    *_GEOMETRY_ACTION_SPECS,
    *_LIGHT_ACTION_SPECS,
    *_OTHER_CREATE_ACTION_SPECS,
)

_CORE_MATERIAL_GROUPS: tuple[CoreMaterialGroupDescriptor, ...] = (
    CoreMaterialGroupDescriptor(
        group_id="advanced",
        label="Advanced",
        order=0,
    ),
    CoreMaterialGroupDescriptor(
        group_id="base",
        label="Base",
        order=100,
    ),
    CoreMaterialGroupDescriptor(
        group_id="usd_materials",
        label="USD Materials",
        order=200,
    ),
)

_CORE_MATERIAL_SPECS: tuple[_CoreMaterialSpec, ...] = (
    _CoreMaterialSpec(
        material_id="core_material.omni_surface",
        label="OmniSurface",
        group_id="advanced",
        family=CoreMaterialFamily.MDL,
        kind=CoreMaterialKind.OMNI_SURFACE,
        shader_type="OmniSurface",
        order=0,
        default_scope_path="/World/Looks",
        default_name="OmniSurface",
        capabilities=("mdl.omni_surface",),
        schema_family="mdl",
    ),
    _CoreMaterialSpec(
        material_id="core_material.omni_glass",
        label="OmniGlass",
        group_id="base",
        family=CoreMaterialFamily.MDL,
        kind=CoreMaterialKind.OMNI_GLASS,
        shader_type="OmniGlass",
        order=0,
        default_scope_path="/World/Looks",
        default_name="OmniGlass",
        capabilities=("mdl.omni_glass",),
        schema_family="mdl",
    ),
    _CoreMaterialSpec(
        material_id="core_material.omni_pbr",
        label="OmniPBR",
        group_id="base",
        family=CoreMaterialFamily.MDL,
        kind=CoreMaterialKind.OMNI_PBR,
        shader_type="OmniPBR",
        order=10,
        default_scope_path="/World/Looks",
        default_name="OmniPBR",
        capabilities=("mdl.omni_pbr",),
        schema_family="mdl",
    ),
    _CoreMaterialSpec(
        material_id="core_material.usd_preview_surface",
        label="USD Preview Surface",
        group_id="usd_materials",
        family=CoreMaterialFamily.USD,
        kind=CoreMaterialKind.USD_PREVIEW_SURFACE,
        shader_type="UsdPreviewSurface",
        order=0,
        default_scope_path="/World/Looks",
        default_name="PreviewSurface",
        capabilities=("usdshade.preview_surface",),
    ),
)


def _create_stage_identifier(stage: Any) -> str:
    try:
        return str(stage.GetRootLayer().identifier or "")
    except Exception:
        return ""


def _create_edit_target_layer(stage: Any) -> tuple[Any | None, str]:
    try:
        edit_target = stage.GetEditTarget()
        layer = edit_target.GetLayer()
    except Exception:
        return None, "No current edit target is available."
    if layer is None:
        return None, "No current edit target is available."
    if not bool(getattr(layer, "permissionToEdit", True)):
        return layer, "Current edit target is not editable."
    return layer, ""


def _create_schema_disabled_reason(spec: _CreateActionSpec) -> str:
    if spec.unsupported_reason:
        return spec.unsupported_reason
    if spec.schema_family == "usd_lux" and UsdLux is None:
        return "UsdLux light schemas are not available in this OpenUSD build."
    if spec.schema_family == "usd_shade" and UsdShade is None:
        return "UsdShade material schemas are not available in this OpenUSD build."
    if spec.schema_family == "usd_render" and UsdRender is None:
        return "UsdRender schemas are not available in this OpenUSD build."
    return ""


def _core_material_mdl_source_asset(spec: _CoreMaterialSpec) -> str:
    return f"{spec.shader_type}.mdl"


def _core_material_mdl_search_dirs() -> tuple[Path, ...]:
    paths: list[Path] = []
    for env_name in _MDL_SEARCH_ENV_VARS:
        for value in os.environ.get(env_name, "").split(os.pathsep):
            if value:
                paths.append(Path(value).expanduser())

    for parent in Path(__file__).resolve().parents:
        paths.extend((
            parent / "ovrtx" / "examples" / "c" / "_deps" / "ovrtx-src" / "bin" / "library" / "mdl" / "Base",
            parent / "ovrtx-src" / "bin" / "library" / "mdl" / "Base",
            parent / "bin" / "library" / "mdl" / "Base",
            parent / "bin" / "mdl",
        ))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        text = str(path)
        if text in seen:
            continue
        seen.add(text)
        unique.append(path)
    return tuple(unique)


def _core_material_mdl_module_available(spec: _CoreMaterialSpec) -> bool:
    source_asset = _core_material_mdl_source_asset(spec)
    return any((directory / source_asset).is_file() for directory in _core_material_mdl_search_dirs())


def _core_material_schema_disabled_reason(spec: _CoreMaterialSpec) -> str:
    if spec.schema_family == "mdl":
        if UsdShade is None:
            return "UsdShade material schemas are not available in this OpenUSD build."
        if not _core_material_mdl_module_available(spec):
            return (
                f"MDL material module {spec.shader_type}.mdl is not available in "
                "this standalone build."
            )
    if spec.schema_family == "usd_shade" and UsdShade is None:
        return "UsdShade material schemas are not available in this OpenUSD build."
    return ""


def _create_disabled_reason(
    spec: _CreateActionSpec,
    *,
    edit_target_reason: str,
    selection_paths: tuple[str, ...],
) -> str:
    schema_reason = _create_schema_disabled_reason(spec)
    if schema_reason:
        return schema_reason
    if (
        CreateActionRequirement.WRITABLE_EDIT_TARGET in spec.requirements
        and edit_target_reason
    ):
        return edit_target_reason
    if (
        CreateActionRequirement.SELECTION in spec.requirements
        and not selection_paths
    ):
        return "Select a prim before using this create action."
    return ""


def _core_material_disabled_reason(
    spec: _CoreMaterialSpec,
    *,
    edit_target_reason: str,
) -> str:
    schema_reason = _core_material_schema_disabled_reason(spec)
    if schema_reason:
        return schema_reason
    if (
        CoreMaterialRequirement.WRITABLE_EDIT_TARGET in spec.requirements
        and edit_target_reason
    ):
        return edit_target_reason
    return ""


def _core_material_warning(
    code: CoreMaterialErrorCode,
    message: str,
    severity: CoreMaterialWarningSeverity = CoreMaterialWarningSeverity.ERROR,
) -> CoreMaterialWarning:
    return CoreMaterialWarning(code=code.value, message=message, severity=severity)


def _core_material_error(
    message: str,
    error_code: CoreMaterialErrorCode,
    *,
    warnings: tuple[CoreMaterialWarning, ...] = (),
) -> CreateMaterialResult:
    if not warnings:
        warnings = (_core_material_warning(error_code, message),)
    return CreateMaterialResult.rejected_result(
        message=message,
        error_code=error_code,
        warnings=warnings,
    )


def _core_material_bindable_selection_paths(
    stage: Any,
    selection_paths: tuple[str, ...],
) -> tuple[str, ...]:
    paths: list[str] = []
    for selection_path in selection_paths:
        sdf_path = _create_action_path(selection_path)
        if sdf_path is None or sdf_path == Sdf.Path.absoluteRootPath:
            continue
        prim = stage.GetPrimAtPath(sdf_path)
        if prim and prim.IsValid():
            paths.append(str(sdf_path))
    return tuple(paths)


def _core_material_binding_targets(
    stage: Any,
    selection_paths: tuple[str, ...],
) -> tuple[tuple[Any, ...], tuple[str, ...], tuple[CoreMaterialWarning, ...]]:
    targets: list[Any] = []
    skipped: list[str] = []
    warnings: list[CoreMaterialWarning] = []
    for selection_path in selection_paths:
        sdf_path = _create_action_path(selection_path)
        if sdf_path is None or sdf_path == Sdf.Path.absoluteRootPath:
            skipped.append(str(selection_path))
            warnings.append(
                CoreMaterialWarning(
                    code="invalid_selection_path",
                    message=f"Selection target is not bindable and was skipped: {selection_path}",
                )
            )
            continue
        prim = stage.GetPrimAtPath(sdf_path)
        if prim and prim.IsValid():
            targets.append(prim)
            continue
        skipped.append(str(selection_path))
        warnings.append(
            CoreMaterialWarning(
                code="invalid_selection_path",
                message=f"Selection target is not bindable and was skipped: {selection_path}",
            )
        )
    return tuple(targets), tuple(skipped), tuple(warnings)


def _core_material_binding_strength_token(strength: str) -> tuple[Any | None, str]:
    text = str(strength or "").strip()
    if not text:
        return UsdShade.Tokens.weakerThanDescendants, ""
    key = re.sub(r"[^a-z0-9]", "", text.lower())
    if key in {"weaker", "weakerthandescendants"}:
        return UsdShade.Tokens.weakerThanDescendants, ""
    if key in {"stronger", "strongerthandescendants"}:
        return UsdShade.Tokens.strongerThanDescendants, ""
    return None, f"Unsupported material binding strength: {strength}"


def _core_material_resolve_scope_path(
    stage: Any,
    material: CoreMaterialDescriptor,
    request: CreateMaterialRequest,
) -> tuple[Any | None, str, bool]:
    requested_scope = str(request.requested_scope_path or "")
    if requested_scope:
        scope_path = _create_action_path(requested_scope)
        if scope_path is None:
            return None, f"Requested material scope path is invalid: {requested_scope}", False
        if scope_path != Sdf.Path.absoluteRootPath:
            scope_prim = stage.GetPrimAtPath(scope_path)
            if not scope_prim or not scope_prim.IsValid():
                return None, f"Requested material scope does not exist: {requested_scope}", False
        return scope_path, "", False

    scope_text = material.default_scope_path or "/World/Looks"
    scope_path = _create_action_path(scope_text)
    if scope_path is None:
        return None, f"Default material scope path is invalid: {scope_text}", False
    return scope_path, "", True


def _create_category_descriptors(
    actions: tuple[CreateActionDescriptor, ...],
) -> tuple[CreateActionCategoryDescriptor, ...]:
    categories: list[CreateActionCategoryDescriptor] = []
    for category in CreateActionCategory.ordered():
        if category is CreateActionCategory.OTHER:
            continue
        category_actions = [
            action for action in actions if action.category_id == category.value
        ]
        if not category_actions:
            continue
        disabled_reasons = {
            action.disabled_reason for action in category_actions if action.disabled_reason
        }
        enabled = any(action.is_available for action in category_actions)
        disabled_reason = ""
        if not enabled and len(disabled_reasons) == 1:
            disabled_reason = next(iter(disabled_reasons))
        elif not enabled:
            disabled_reason = "No create actions in this category are currently available."
        categories.append(
            CreateActionCategoryDescriptor(
                category_id=category,
                order=category.default_order,
                enabled=enabled,
                disabled_reason=disabled_reason,
                metadata=(
                    {"parent_path": _RENDERING_PARENT_PATH}
                    if category.value in _RENDERING_GROUP_CATEGORY_IDS
                    else {}
                ),
            )
        )
    return tuple(categories)


def _create_action_error(
    message: str,
    error_code: CreateActionErrorCode,
) -> CreateResult:
    return CreateResult.rejected_result(
        message=message,
        error_code=error_code,
        warnings=(
            CreateActionWarning(
                code=error_code.value,
                message=message,
                severity=CreateActionWarningSeverity.ERROR,
            ),
        ),
    )


def _create_action_path(path: str) -> Any | None:
    try:
        sdf_path = Sdf.Path(str(path or ""))
    except Exception:
        return None
    if not sdf_path.IsAbsolutePath() or sdf_path.IsPropertyPath():
        return None
    return sdf_path


def _create_child_name(name: str, fallback: str) -> str:
    base = _NAME_RE.sub("_", str(name or fallback or "Prim"))
    base = base.strip("_") or "Prim"
    if not re.match(r"^[A-Za-z_]", base):
        base = f"_{base}"
    return base


def _create_unique_child_path(stage: Any, parent_path: Any, child_name: str) -> Any:
    path = parent_path.AppendChild(child_name)
    if not stage.GetPrimAtPath(path):
        return path

    index = 1
    while True:
        candidate = parent_path.AppendChild(f"{child_name}_{index:02d}")
        if not stage.GetPrimAtPath(candidate):
            return candidate
        index += 1


def _create_resolve_parent_path(
    stage: Any,
    action: CreateActionDescriptor,
    request: Any,
) -> tuple[Any | None, str, bool]:
    requested_parent = str(request.requested_parent_path or "")
    if requested_parent:
        parent_path = _create_action_path(requested_parent)
        if parent_path is None:
            return None, f"Requested parent path is invalid: {requested_parent}", False
        if parent_path != Sdf.Path.absoluteRootPath:
            parent_prim = stage.GetPrimAtPath(parent_path)
            if not parent_prim or not parent_prim.IsValid():
                return None, f"Requested parent does not exist: {requested_parent}", False
        return parent_path, "", False

    selected_parent = ""
    if action.placement_policy is CreatePlacementPolicy.SELECTED_PARENT:
        selected_parent = next(iter(request.selection_paths or ()), "")
    parent_text = selected_parent or action.default_parent_path or "/"
    parent_path = _create_action_path(parent_text)
    if parent_path is None:
        return None, f"Default parent path is invalid: {parent_text}", False
    return parent_path, "", True


def _create_ensure_parent(stage: Any, parent_path: Any, *, create_missing: bool) -> tuple[Any | None, str]:
    if parent_path == Sdf.Path.absoluteRootPath:
        return stage.GetPseudoRoot(), ""
    parent = stage.GetPrimAtPath(parent_path)
    if parent and parent.IsValid():
        return parent, ""
    if not create_missing:
        return None, f"Parent does not exist: {parent_path}"

    current = Sdf.Path.absoluteRootPath
    for element in parent_path.GetPrefixes():
        prim = stage.GetPrimAtPath(element)
        if not prim or not prim.IsValid():
            type_name = (
                "Scope"
                if str(element).startswith("/Render")
                else ("Xform" if element.GetParentPath() == Sdf.Path.absoluteRootPath else "Scope")
            )
            if type_name == "Xform":
                prim = UsdGeom.Xform.Define(stage, element).GetPrim()
            else:
                prim = UsdGeom.Scope.Define(stage, element).GetPrim()
        current = element
    return stage.GetPrimAtPath(current), ""


def _create_is_sensor_source_prim(prim: Any) -> bool:
    source_type = str(prim.GetTypeName() or "")
    schema_text = " ".join([
        source_type,
        *[str(schema) for schema in prim.GetAppliedSchemas()],
    ])
    return any(marker in schema_text.lower() for marker in _SENSOR_SOURCE_MARKERS)


def _create_snapshot_layer(layer: Any) -> Any:
    snapshot = Sdf.Layer.CreateAnonymous("ovui-create-action-snapshot")
    snapshot.TransferContent(layer)
    return snapshot


def _create_restore_layer(layer: Any, snapshot: Any) -> None:
    layer.TransferContent(snapshot)


def _create_warning_result(
    code: str,
    message: str,
    severity: CreateActionWarningSeverity = CreateActionWarningSeverity.WARNING,
) -> CreateActionWarning:
    return CreateActionWarning(code=code, message=message, severity=severity)


class UsdStageAdapter(StageAdapter, CreateActionsAdapter, CoreMaterialsAdapter):
    """USD-backed StageAdapter. Wraps a Usd.Stage.

    Pass an UndoManager to make visibility, rename, and reparent operations
    undoable. If undo_manager is None, operations execute directly.
    """

    def __init__(self, stage: Any, undo_manager: Any = None, call_later: Any = None) -> None:
        self._stage = stage
        self._undo_manager = undo_manager
        self._subscribers: List[Callable] = []
        self._suppressed = False
        self._call_later = call_later

        # Tf.Notice batching state
        self._pending_changed: set = set()
        self._pending_resynced: set = set()
        self._pending_sources: set[Optional[str]] = set()
        self._pending_default_change: Optional[tuple[Optional[str], Optional[str]]] = None
        self._flush_scheduled = False
        self._in_mutation = False  # True while _push() is executing
        self._current_notice_source: Optional[str] = None

        # Visibility attempt/scope state: while an attempt is open, genuine
        # ObjectsChanged payloads are collected verbatim instead of being
        # dropped by the _in_mutation guard; the emitted event derives its
        # paths exclusively from those payloads. A scope (open undo group)
        # owns per-layer first-touch baselines and its members' events/raw
        # segments; the outermost close either flushes one merged event, or
        # — when any member failed — aborts the whole group via
        # UndoManager.cancel_group() and proves every affected layer equal
        # to its scope baseline before suppressing the audit-retained
        # segments (anything unproven flushes conservatively).
        self._visibility_attempts: List[dict] = []
        self._visibility_scope: Optional[dict] = None
        self._undo_group_depth = 0
        self._visibility_scope_audit: List[dict] = []
        # Re-entrant disposal guard: teardown requested while a logical
        # attempt or scope is still open DEFERS until its owner resolves it
        # (one outer disposition; no listener revocation mid-notice).
        self._dispose_deferred = False
        # Genuine operation provenance: >0 exactly while OUR command is
        # authoring (MakeVisible/MakeInvisible) or replaying one of its
        # snapshots. Only bare resyncs captured inside this window are even
        # candidates for the visibility annotation.
        self._operation_window_depth = 0

        # Cached default-prim path so get_item_flags() is O(1) per call;
        # refreshed on every LAYER_INFO event.
        self._default_prim_path: Optional[str] = self._compute_default_prim_path()

        if HAS_USD:
            self._notice_key = Tf.Notice.Register(
                Usd.Notice.ObjectsChanged,
                self._on_notice,
                self._stage,
            )
            self._layer_notice_key = Tf.Notice.Register(
                Sdf.Notice.LayerInfoDidChange,
                self._on_layer_info,
                self._stage.GetRootLayer(),
            )
            # Layer-change VETO for the visibility-only proof: while an
            # attempt is open, record which layers changed. This observation
            # never creates or reclassifies a root — it can only REFUSE the
            # visibility annotation (conservative/structural direction) when
            # a layer outside the operation's baselined target(s) changed
            # during the attempt (e.g. a re-entrant edit to another layer).
            self._sdf_change_key = Tf.Notice.RegisterGlobally(
                Sdf.Notice.LayersDidChange,
                self._on_layers_did_change,
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _remove_subscriber(self, key: str, callback: Callable) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    def _notify(self, event: ChangeEvent) -> None:
        """Deliver ``event`` to every subscriber with failure isolation.

        A throwing subscriber must never starve later consumers (hierarchy
        model, renderer, property inspector, footer). Every callback is
        attempted; collected failures are raised afterwards as one error so
        callers can finalize their own state first and attach context.
        """
        if self._suppressed:
            return
        failures: list = []
        for cb in list(self._subscribers):
            try:
                cb(event)
            except BaseException as exc:  # noqa: BLE001 — isolation by contract
                # BaseException included: a KeyboardInterrupt in one
                # subscriber must not starve the hierarchy/renderer/PI/
                # footer consumers behind it.
                failures.append(exc)
        if failures:
            # Preserve interrupt semantics: if any failure is a
            # non-Exception BaseException (KeyboardInterrupt/SystemExit),
            # re-raise the first such directly; other failures attach.
            primary = next(
                (f for f in failures if not isinstance(f, Exception)),
                None,
            )
            if primary is None:
                primary = RuntimeError(
                    f"{len(failures)} change-event subscriber(s) failed"
                )
                extras = failures
            else:
                extras = [f for f in failures if f is not primary]
            add_note = getattr(primary, "add_note", None)
            if callable(add_note):
                for failure in extras:
                    add_note(f"{type(failure).__name__}: {failure}")
            raise primary

    def _on_notice(self, notice: Any, sender: Any) -> None:
        if self._visibility_attempts:
            attempt = self._visibility_attempts[-1]
            resynced = tuple(str(p) for p in notice.GetResyncedPaths())
            attempt["segments"].append(
                (
                    resynced,
                    tuple(str(p) for p in notice.GetChangedInfoOnlyPaths()),
                )
            )
            if self._operation_window_depth > 0:
                attempt.setdefault("operation_resyncs", set()).update(
                    path for path in resynced if "." not in path.rsplit("/", 1)[-1]
                )
            return
        if self._suppressed or self._in_mutation:
            return
        received_paths = False
        for path in notice.GetResyncedPaths():
            self._pending_resynced.add(str(path))
            received_paths = True
        for path in notice.GetChangedInfoOnlyPaths():
            self._pending_changed.add(str(path))
            received_paths = True
        if received_paths:
            self._pending_sources.add(self._current_notice_source)
        if (self._pending_changed or self._pending_resynced) and not self._flush_scheduled:
            self._flush_scheduled = True
            self._schedule_flush()

    def _on_layers_did_change(self, notice: Any, sender: Any = None) -> None:
        """Record layers changed while a visibility attempt is open.

        Feeds the full-consequence visibility-only proof: an attempt whose
        window captured a bare resync can only be annotated when every layer
        that changed during it is one of the operation's baselined target
        layers (and normalizes equal — see
        ``_prove_attempt_visibility_only``). Unreadable notices poison the
        proof (unprovable is NOT proof), never widen it.
        """
        if not self._visibility_attempts:
            return
        try:
            identifiers = {layer.identifier for layer in notice.GetLayers()}
        except Exception:
            for attempt in self._visibility_attempts:
                attempt["op_baseline_ok"] = False
            return
        for attempt in self._visibility_attempts:
            attempt.setdefault("changed_layers", set()).update(identifiers)

    def _compute_default_prim_path(self) -> Optional[str]:
        if not HAS_USD or self._stage is None:
            return None
        if not self._stage.HasDefaultPrim():
            return None
        prim = self._stage.GetDefaultPrim()
        if not prim or not prim.IsValid():
            return None
        return str(prim.GetPath())

    def _on_layer_info(self, notice: Any, sender: Any) -> None:
        if self._suppressed or self._in_mutation:
            return
        new_default = self._compute_default_prim_path()
        if new_default == self._default_prim_path:
            return
        old_default = self._default_prim_path
        if self._pending_default_change is None:
            self._pending_default_change = (old_default, new_default)
        else:
            # Coalesce: keep the original old value, update to newest target.
            self._pending_default_change = (self._pending_default_change[0], new_default)
        if not self._flush_scheduled:
            self._flush_scheduled = True
            self._schedule_flush()

    def _schedule_flush(self) -> None:
        # Production Application injects a ``call_later`` (drain hook); bare
        # tests with no scheduler get a synchronous flush. Step 13 simplified
        # this from a lazy ``ovui_widgets.common.scheduler`` import to keep the
        # moved openusd file free of ``ovui_widgets.*`` runtime imports.
        if self._call_later is not None:
            self._call_later(0.0, self._flush)
        else:
            self._flush()

    def _flush(self) -> None:
        self._flush_scheduled = False
        pending_default = self._pending_default_change
        self._pending_default_change = None

        if self._pending_changed or self._pending_resynced:
            source = self._pending_event_source()
            # A resynced *property* path (e.g. first-time creation of a
            # `.visibility` spec) does not change topology: classify it as an
            # info change on its property so consumers stay on the precise
            # path. Only resynced *prim* paths mark a hierarchy resync.
            changed = set(self._pending_changed)
            resynced_prims: set = set()
            for path in self._pending_resynced:
                if _is_property_path_string(path):
                    changed.add(path)
                else:
                    resynced_prims.add(path)
            event_type = (
                ChangeEventType.RESYNC
                if resynced_prims
                else ChangeEventType.INFO_CHANGE
            )
            event = ChangeEvent(
                changed_paths=tuple(sorted(changed)),
                resynced_paths=tuple(sorted(resynced_prims)),
                event_type=event_type,
                source=source,
            )
            self._pending_changed.clear()
            self._pending_resynced.clear()
            self._pending_sources.clear()
            self._notify(event)

        if pending_default is not None:
            old_default, new_default = pending_default
            self._default_prim_path = new_default
            changed = tuple(p for p in (old_default, new_default) if p)
            self._notify(ChangeEvent(
                changed_paths=changed,
                resynced_paths=(),
                event_type=ChangeEventType.LAYER_INFO,
            ))

    def _pending_event_source(self) -> Optional[str]:
        if len(self._pending_sources) != 1:
            return None
        source = next(iter(self._pending_sources))
        return source or None

    def _push(self, cmd: Any) -> None:
        """Push cmd to undo_manager (which calls do()), or call do() directly.

        Sets _in_mutation to suppress Tf.Notice collection; adapter methods fire
        their own synchronous notifications instead.
        """
        self._in_mutation = True
        try:
            if self._undo_manager is not None:
                self._undo_manager.push(cmd)
            else:
                cmd.do()
        finally:
            self._in_mutation = False

    @property
    def stage(self) -> Any:
        return self._stage

    # ── Hierarchy ─────────────────────────────────────────────────────────────

    def get_root(self) -> AdapterItem:
        return self._stage.GetPseudoRoot()

    def get_children(self, item: AdapterItem) -> List[AdapterItem]:
        # Deleting a prim invalidates ``Usd.Prim`` references that the
        # Stage tree model captured a frame ago. Returning ``[]`` for
        # an expired/null prim lets the row drain through the next
        # notice flush without raising ``RuntimeError: Accessed invalid
        # ... prim``. Codex final-UI-QA rerun (2026-05-08) hit this on
        # `/World/Cube` after Delete.
        if not _is_live_prim(item):
            return []
        return list(item.GetChildren())

    def can_have_children(self, item: AdapterItem) -> bool:
        return True

    def get_item_path(self, item: AdapterItem) -> str:
        return str(item.GetPath())

    def get_item_at_path(self, path: str) -> Optional[AdapterItem]:
        prim = self._stage.GetPrimAtPath(Sdf.Path(path))
        return prim if prim.IsValid() else None

    # ── Display ───────────────────────────────────────────────────────────────

    def get_display_name(self, item: AdapterItem) -> str:
        name = item.GetName()
        return name if name else "/"

    def get_type_name(self, item: AdapterItem) -> str:
        raw = str(item.GetTypeName())
        if raw:
            return raw
        # Empty typeName: USD class prims carry no schema type, so the Type
        # column shows "Class". Non-class prims with an empty typeName (most
        # commonly the pseudo-root and raw ``over`` specs) render blank.
        get_specifier = getattr(item, "GetSpecifier", None)
        if get_specifier is not None and get_specifier() == Sdf.SpecifierClass:
            return "Class"
        return ""

    def get_type_category(self, item: AdapterItem) -> str:
        if not _is_live_prim(item):
            return "Other"
        raw = str(item.GetTypeName()).lower()
        if not raw:
            return "Other"
        return _TYPE_CATEGORY_MAP.get(raw, "Other")

    def get_icon_name(self, item: AdapterItem) -> str:
        raw = str(item.GetTypeName()).lower()
        if not raw:
            return "Prim"
        return _ICON_MAP.get(raw, "Prim")

    def get_badge_flags(self, item: AdapterItem) -> BadgeFlags:
        flags = BadgeFlags.NONE
        if item.HasAuthoredReferences():
            flags |= BadgeFlags.REFERENCE
        if item.HasAuthoredPayloads():
            flags |= BadgeFlags.PAYLOAD
        if item.IsInstanceable():
            flags |= BadgeFlags.INSTANCE
        if item.HasAuthoredInherits():
            flags |= BadgeFlags.INHERITS
        if item.HasAuthoredSpecializes():
            flags |= BadgeFlags.SPECIALIZES
        if item.GetSpecifier() == Sdf.SpecifierOver:
            flags |= BadgeFlags.OVERRIDE
        return flags

    def get_item_flags(self, item: AdapterItem) -> ItemFlags:
        flags = ItemFlags.NONE
        if item.IsInstanceProxy():
            flags |= ItemFlags.IS_INSTANCE_PROXY
        if item.IsAbstract():
            flags |= ItemFlags.IS_ABSTRACT
        if not item.IsActive():
            flags |= ItemFlags.IS_INACTIVE
        specifier = item.GetSpecifier()
        if specifier == Sdf.SpecifierOver:
            flags |= ItemFlags.IS_OVER
        elif specifier == Sdf.SpecifierClass:
            flags |= ItemFlags.IS_CLASS
        if (
            self._default_prim_path is not None
            and str(item.GetPath()) == self._default_prim_path
        ):
            flags |= ItemFlags.IS_DEFAULT_PRIM
        # TODO(live-session): IS_OUTDATED / IS_IN_LIVE_SESSION / HAS_MISSING_REFS
        # require omni.kit.usd.layers, which is unavailable in the standalone build.
        return flags

    # ── Visibility ────────────────────────────────────────────────────────────

    def compute_visibility(self, item: AdapterItem) -> VisibilityState:
        if item.GetPath() == Sdf.Path.absoluteRootPath:
            return VisibilityState.VISIBLE
        imageable = UsdGeom.Imageable(item)
        if not imageable:
            return VisibilityState.VISIBLE
        vis_attr = imageable.GetVisibilityAttr()
        # Explicitly invisible: authored value is 'invisible'
        if vis_attr.HasAuthoredValue() and vis_attr.Get() == UsdGeom.Tokens.invisible:
            return VisibilityState.INVISIBLE
        # Inherited invisible: effective visibility is invisible but not authored here
        computed = imageable.ComputeVisibility()
        if computed == UsdGeom.Tokens.invisible:
            return VisibilityState.INHERITED_INVISIBLE
        return VisibilityState.VISIBLE

    def set_visibility(self, item: AdapterItem, visible: bool) -> None:
        if not self.can_edit_visibility(item):
            raise ValueError(f"Visibility is not editable for {item.GetPath()}")
        from ovui_data_adapters.openusd import SetVisibilityCommand
        from ovui_data_adapters.common import CommandCancelled
        cmd = SetVisibilityCommand(item, visible, adapter=self)
        self._ensure_scope_baseline()
        attempt = self._begin_visibility_attempt(
            cmd.predicted_write_prims(), command=cmd
        )
        try:
            self._push(cmd)
        except CommandCancelled:
            # Genuine outcome no-op (empty ledger + unchanged layer): the
            # push left undo/redo history untouched; emit nothing.
            self._end_visibility_attempt(attempt)
            return
        except BaseException as exc:
            # BaseException included (KeyboardInterrupt, SystemExit, …): a
            # genuine write may already have landed, so the attempt must
            # still reach a truthful disposition — otherwise the dangling
            # attempt would swallow every later independent edit's notices.
            self._abort_visibility_attempt(attempt, exc)
            raise
        finally:
            self._maybe_complete_deferred_dispose()
        self._commit_visibility_attempt(attempt)
        self._maybe_complete_deferred_dispose()

    def visibility_attempt_ledger_is_empty(self) -> bool:
        """True when the innermost open attempt collected no genuine payload."""
        if not self._visibility_attempts:
            return False
        return not any(
            resynced or changed
            for resynced, changed in self._visibility_attempts[-1]["segments"]
        )

    def _ensure_scope_baseline(self) -> None:
        """First-touch whole-layer baseline for the active scope's target layer.

        Captured before any member authoring so a scope abort can compensate
        the complete group and prove every affected layer field-identical to
        its pre-scope state.
        """
        scope = self._visibility_scope
        if scope is None or scope["closed"]:
            return
        layer = self._stage.GetEditTarget().GetLayer()
        key = layer.identifier
        if key in scope["baselines"]:
            return
        scope["baselines"][key] = (layer, layer.ExportToString())

    def is_imageable(self, item: AdapterItem) -> bool:
        """Live composed-USD read: does inherited visibility apply to item?"""
        if not _is_live_prim(item):
            return False
        return bool(UsdGeom.Imageable(item))

    # ── Visibility attempts (notice-only event roots) ─────────────────────────
    #
    # An attempt collects the genuine Usd.Notice.ObjectsChanged payloads its
    # authoring produces (see _on_notice) and emits one adapter event whose
    # paths derive exclusively from those payloads. Predicted write sets only
    # scope the semantic pre-reads (boundaries); they never create a root: an
    # attempt whose notice ledger names no visibility property emits nothing.

    def _visibility_state_for_path(self, path: str) -> Any:
        prim = self._stage.GetPrimAtPath(path)
        if not prim or not prim.IsValid():
            return None
        return self.compute_visibility(prim)

    @contextlib.contextmanager
    def visibility_operation_window(self) -> Any:
        """Bracket OUR command's authoring/replay (operation provenance).

        SetVisibilityCommand wraps its MakeVisible/MakeInvisible authoring
        and its snapshot replays (undo/redo edges and compensations) in
        this window; notices captured inside it are the only CANDIDATES
        for the visibility annotation — the unchanged-identity fingerprint
        must additionally hold. Notices arriving outside any window (e.g.
        third-party edits between operations) can never be annotated.
        """
        self._operation_window_depth += 1
        try:
            yield
        finally:
            self._operation_window_depth -= 1

    def _begin_visibility_attempt(
        self, predicted_prims: Any, command: Any = None
    ) -> dict:
        boundary_paths: set = set()
        topology_paths: set = set()
        for path in predicted_prims:
            path = str(path)
            boundary_paths.add(path)
            topology_paths.add(path)
            # Ancestors: a Mode B whole-layer replay resyncs the prim its
            # edit target rewrites (e.g. the variant root above the
            # predicted write set), so their pre-attempt topology records
            # are needed to PROVE such a resync left topology unchanged.
            prefix = path.rpartition("/")[0]
            while prefix:
                topology_paths.add(prefix)
                prefix = prefix.rpartition("/")[0]
            prim = self._stage.GetPrimAtPath(path)
            if prim and prim.IsValid():
                for child in prim.GetAllChildren():
                    if UsdGeom.Imageable(child):
                        boundary_paths.add(str(child.GetPath()))
        topology_paths |= boundary_paths
        topology: dict = {}
        for path in topology_paths:
            prim = self._stage.GetPrimAtPath(path)
            if prim and prim.IsValid():
                # Full identity fingerprint: retype, (de)activation, and
                # child-set changes all break it. (Delete/recreate with a
                # byte-identical composed prim inside a replay window is
                # the one theoretically indistinguishable case — composed
                # state is then genuinely identical.)
                topology[path] = (
                    str(prim.GetTypeName()),
                    bool(prim.IsActive()),
                    str(prim.GetSpecifier()),
                    tuple(prim.GetAllChildrenNames()),
                )
            else:
                topology[path] = None  # recorded ABSENT pre-attempt
        # Full-consequence proof baselines: the operation's target layer(s),
        # captured BEFORE any authoring. A bare resync captured inside the
        # operation window is annotated visibility-only ONLY if, at assembly
        # time, every layer that changed during the attempt is one of these
        # and its visibility-normalized content equals the baseline's —
        # i.e. the operation's entire actual consequence beyond visibility
        # opinions (and the inert scaffolding hosting them) is NOTHING.
        # An uncapturable baseline poisons the proof (conservative).
        op_baselines: dict = {}
        op_baseline_ok = True
        op_layers: list = []
        layers_fn = getattr(command, "operation_layers", None)
        if callable(layers_fn):
            try:
                op_layers = [
                    layer for layer in layers_fn() if layer is not None
                ]
            except Exception:
                op_baseline_ok = False
        if not op_layers and self._stage is not None:
            try:
                op_layers = [self._stage.GetEditTarget().GetLayer()]
            except Exception:
                op_baseline_ok = False
        for layer in op_layers:
            try:
                op_baselines[layer.identifier] = (
                    layer, layer.ExportToString()
                )
            except Exception:
                op_baseline_ok = False
        try:
            attempt_edit_target = self._stage.GetEditTarget()
        except Exception:
            attempt_edit_target = None
        attempt = {
            "segments": [],
            "pre": {
                p: self._visibility_state_for_path(p) for p in boundary_paths
            },
            # Genuine pre-attempt structural evidence: composed child-name
            # tuples. Used ONLY to prove a bare resync left topology
            # unchanged; never to add, drop, or fabricate a root.
            "topology": topology,
            "op_baselines": op_baselines,
            "op_baseline_ok": op_baseline_ok and bool(op_baselines),
            "changed_layers": set(),
            # For mapping composed property paths back into baseline layer
            # spec paths (variant edit targets) when proving that a REMOVED
            # ``.visibility`` path was a genuine USD attribute.
            "edit_target": attempt_edit_target,
        }
        self._visibility_attempts.append(attempt)
        return attempt

    def _end_visibility_attempt(self, attempt: dict) -> None:
        if self._visibility_attempts and self._visibility_attempts[-1] is attempt:
            self._visibility_attempts.pop()

    @staticmethod
    def _attempt_roots(attempt: dict) -> "tuple[set, set]":
        """(visibility-property prim roots, bare prim-path roots).

        Both derive exclusively from the attempt's genuine notice payloads:
        `.visibility` property paths name their prims; bare prim paths in
        the RESYNCED payloads (Mode B whole-layer replays resync prims) are
        retained as roots as well. Bare prim paths appearing only as
        changed-info (created `over` ancestors) are not roots.
        """
        vis_paths: set = set()
        resynced_prims: set = set()
        for resynced, changed in attempt["segments"]:
            for path in resynced:
                prim, separator, prop = str(path).rpartition(".")
                if separator and prop == "visibility":
                    vis_paths.add(prim)
                elif not separator:
                    resynced_prims.add(str(path))
            for path in changed:
                prim, separator, prop = str(path).rpartition(".")
                if separator and prop == "visibility":
                    vis_paths.add(prim)
        return vis_paths, resynced_prims

    def _bare_resync_is_replay_consequence(
        self, attempt: dict, prim_path: str
    ) -> bool:
        """Genuine replay/operation provenance for annotating a bare resync.

        ALL legs are required — neither path overlap, predictions, nor
        unchanged state shape alone can reclassify a genuine resync:
        1. OPERATION provenance: the resync was captured inside OUR
           command's authoring/replay window
           (``visibility_operation_window``) — genuine consequences such
           as a direct-variant root resync qualify; notices outside any
           window never do.
        2. STATE provenance: the attempt holds a pre-attempt identity
           fingerprint (type name, active state, specifier, composed
           child names) for the prim, the prim still exists, and the full
           fingerprint is unchanged.
        3. FULL-CONSEQUENCE proof: the operation's entire actual layer
           consequence, beyond visibility opinions and the inert
           scaffolding hosting them, is NOTHING — proven by comparing the
           visibility-normalized target-layer content against the
           pre-attempt baseline, with any change to a non-baselined layer
           vetoing the proof (see ``_prove_attempt_visibility_only``). A
           coarse whole-layer replay that also removed/changed descendant
           non-visibility state, or a re-entrant variant/reference/
           payload/composition or property mutation during the window,
           therefore keeps conservative structural semantics for every
           consumer.
        """
        operation_resyncs = attempt.get("operation_resyncs")
        if not operation_resyncs or prim_path not in operation_resyncs:
            return False
        record = attempt.get("topology", {}).get(prim_path, None)
        if record is None:
            return False  # no record, or recorded absent pre-attempt
        try:
            prim = self._stage.GetPrimAtPath(prim_path)
            if not prim or not prim.IsValid():
                return False
            current = (
                str(prim.GetTypeName()),
                bool(prim.IsActive()),
                str(prim.GetSpecifier()),
                tuple(prim.GetAllChildrenNames()),
            )
            if current != record:
                return False
        except Exception:
            return False
        return self._attempt_consequence_is_visibility_only(attempt)

    def _attempt_net_zero_verified(self, attempt: dict) -> bool:
        """Adapter-side proof of a compensation's net-zero claim.

        True only when every operation-layer baseline captured at attempt
        begin is byte-identical to the live layer again AND no other layer
        this stage composes changed during the attempt. Unprovable is NOT
        proof: uncapturable baselines, unreadable change notifications, or
        verification failures reject the claim (conservative flush).
        """
        if not attempt.get("op_baseline_ok"):
            return False
        baselines = attempt.get("op_baselines") or {}
        if not baselines:
            return False
        changed_layers = attempt.get("changed_layers") or set()
        unbaselined = {
            identifier for identifier in changed_layers
            if identifier not in baselines
        }
        if unbaselined:
            try:
                used = {
                    layer.identifier
                    for layer in self._stage.GetUsedLayers()
                }
            except Exception:
                return False
            if unbaselined & used:
                return False
        try:
            return all(
                layer.ExportToString() == baseline_text
                for layer, baseline_text in baselines.values()
            )
        except Exception:
            return False

    def _vis_path_is_visibility_attribute(
        self, attempt: dict, path: str
    ) -> bool:
        """Prove a ``.visibility``-suffixed path is a genuine USD ATTRIBUTE.

        Name shape alone never reclassifies semantics (round 10): a
        relationship literally named ``visibility`` — existing, created,
        or removed — must keep its genuine structural classification.
        Proof:
        - the path composes live as a ``Usd.Attribute`` → visibility;
        - it composes live as anything else (e.g. a relationship) → NOT;
        - it no longer composes (a removal): the attempt's operation-layer
          BASELINE must hold an ATTRIBUTE spec at the path (direct, or
          mapped through the attempt's frozen edit target for variant
          targets) — the command only ever removes visibility attributes
          it owns, so a baseline relationship spec or an unprovable lookup
          stays conservative/structural.
        """
        try:
            sdf_path = Sdf.Path(str(path))
            obj = self._stage.GetObjectAtPath(sdf_path)
        except Exception:
            return False
        if obj:
            return self._composed_visibility_attribute_authority(obj)
        # REMOVED path: the composed prim must still exist and be genuinely
        # Imageable — the command only removes visibility attributes from
        # Imageable prims it edited (PR review: token/non-custom shape on a
        # non-Imageable prim is NOT schema authority).
        try:
            prim = self._stage.GetPrimAtPath(sdf_path.GetPrimPath())
            if not prim or not prim.IsValid() or not UsdGeom.Imageable(prim):
                return False
        except Exception:
            return False
        baselines = attempt.get("op_baselines") or {}
        if not baselines:
            return False
        cache = attempt.setdefault("_baseline_layer_cache", {})
        candidate_paths = [sdf_path]
        edit_target = attempt.get("edit_target")
        if edit_target is not None:
            try:
                mapped = edit_target.MapToSpecPath(sdf_path)
                if mapped and mapped != sdf_path:
                    candidate_paths.append(mapped)
            except Exception:
                pass
        for identifier, (_layer, baseline_text) in baselines.items():
            layer = cache.get(identifier)
            if layer is None:
                try:
                    layer = Sdf.Layer.CreateAnonymous(".usda")
                    if not layer.ImportFromString(baseline_text):
                        continue
                except Exception:
                    continue
                cache[identifier] = layer
            for candidate in candidate_paths:
                try:
                    spec = layer.GetPropertyAtPath(candidate)
                except Exception:
                    continue
                if spec is not None:
                    # The command only ever removes the schema-shaped
                    # visibility attribute (``token``, non-custom). An
                    # ambiguous removed lookalike — a relationship, or a
                    # custom attribute merely named ``visibility`` — is
                    # not command-owned and stays structural.
                    if not isinstance(spec, Sdf.AttributeSpec):
                        return False
                    try:
                        return (
                            str(spec.typeName) == "token"
                            and not bool(spec.custom)
                        )
                    except Exception:
                        return False
        return False  # unprovable is NOT proof: conservative/structural

    @staticmethod
    def _composed_visibility_attribute_authority(obj: Any) -> bool:
        """ACTUAL UsdGeom.Imageable schema visibility authority.

        Requires a genuine ``Usd.Attribute`` named ``visibility``, ``token``
        typed, non-custom, on a prim that composes as ``UsdGeom.Imageable``.
        Relationships, custom attributes, other value types, and token
        attributes on non-Imageable prims (typeless or non-imageable
        schemas) are lookalikes: genuine notice roots, never visibility
        authority (PR review).
        """
        if not isinstance(obj, Usd.Attribute):
            return False
        try:
            return (
                str(obj.GetTypeName()) == "token"
                and not bool(obj.IsCustom())
                and bool(UsdGeom.Imageable(obj.GetPrim()))
            )
        except Exception:
            return False

    def is_visibility_attribute_path(self, path: str) -> bool:
        """Public LIVE-composition check for consumers (hierarchy model).

        True only when ``path`` currently composes as the genuine Imageable
        schema visibility attribute. Purely observational — no authoring,
        no caching, no root creation.
        """
        try:
            obj = self._stage.GetObjectAtPath(Sdf.Path(str(path)))
        except Exception:
            return False
        if not obj:
            return False
        return self._composed_visibility_attribute_authority(obj)

    def _attempt_consequence_is_visibility_only(self, attempt: dict) -> bool:
        """Cached attempt-wide full-consequence proof (see below)."""
        cached = attempt.get("vis_only_proof")
        if cached is None:
            cached = self._prove_attempt_visibility_only(attempt)
            attempt["vis_only_proof"] = cached
        return cached

    def _prove_attempt_visibility_only(self, attempt: dict) -> bool:
        """Prove the attempt's ENTIRE layer consequence is visibility-only.

        Genuine observation, not prediction: it compares actual authored
        layer content (pre-attempt baseline vs live) and the actual set of
        layers that changed during the attempt. Three conditions:
        - the baselines were capturable and every change notification was
          readable (unprovable is NOT proof);
        - every layer that changed during the attempt is one of the
          operation's baselined target layers (a re-entrant edit to any
          other layer vetoes);
        - each baselined layer, after stripping ``visibility`` attribute
          specs and pruning the inert ``over``/variant scaffolding that
          hosted only them, is byte-identical to its identically-normalized
          baseline — so variant selections, references, payloads, type or
          active changes, transforms, or ANY descendant non-visibility
          opinion difference (e.g. a whole-layer replay removing a later
          surrounding edit) all fail the proof.
        Used exclusively to VETO the visibility annotation — a failed or
        unprovable proof routes the genuine roots structurally; it never
        adds, drops, or fabricates a root.
        """
        if not attempt.get("op_baseline_ok"):
            return False
        baselines = attempt.get("op_baselines") or {}
        if not baselines:
            return False
        changed_layers = attempt.get("changed_layers") or set()
        unbaselined = {
            identifier for identifier in changed_layers
            if identifier not in baselines
        }
        if unbaselined:
            # Only layers this stage actually composes can carry a
            # non-visibility consequence for it; the command's own private
            # anonymous snapshot holders (which TransferContent mutates
            # during capture) never do. Unreadable usage is NOT proof.
            try:
                used = {
                    layer.identifier
                    for layer in self._stage.GetUsedLayers()
                }
            except Exception:
                return False
            if unbaselined & used:
                return False
        try:
            for layer, baseline_text in baselines.values():
                current_text = layer.ExportToString()
                if current_text == baseline_text:
                    continue
                normalized_current = self._visibility_normalized_layer_text(
                    current_text
                )
                normalized_baseline = self._visibility_normalized_layer_text(
                    baseline_text
                )
                if normalized_current != normalized_baseline:
                    return False
            return True
        except Exception:
            return False  # unprovable is NOT proof

    @staticmethod
    def _visibility_normalized_layer_text(text: str) -> str:
        """Layer text with visibility opinions and their scaffolding removed.

        Removes every ``visibility`` ATTRIBUTE spec (root tree and inside
        every variant, recursively), then prunes bottom-up the containers
        left inert by that removal: variants whose prim spec carries
        nothing else, variant sets left with no variants (dropping the
        matching ``variantSetNames`` entry only when no local set spec
        remains), and pure ``over`` prim specs with no other field. Variant
        SELECTIONS, references, payloads, type names, activation, and every
        other property or metadatum survive normalization, so any such
        difference between two normalized texts is a real non-visibility
        consequence. Applied identically to both comparands.
        """
        layer = Sdf.Layer.CreateAnonymous(".usda")
        if not layer.ImportFromString(text):
            raise RuntimeError(
                "layer text import failed during visibility normalization"
            )

        def is_command_owned_visibility_spec(spec: Any) -> bool:
            """EXACTLY the shape SetVisibilityCommand's authoring writes.

            MakeVisible/MakeInvisible author only the default token on a
            plain varying, non-custom ``token`` attribute — nothing else.
            Any additional field (customData, documentation, timeSamples,
            connectionPaths, display metadata, a different type name,
            variability, or a custom flag) is NOT command-owned and must
            survive normalization so it vetoes the visibility-only proof.
            """
            if set(spec.ListInfoKeys()) - {
                "typeName", "variability", "custom", "default"
            }:
                return False
            try:
                return (
                    str(spec.typeName) == "token"
                    and spec.variability == Sdf.VariabilityVarying
                    and not bool(spec.custom)
                )
            except Exception:
                return False

        def strip_visibility(prim_spec: Any) -> None:
            for prop in [
                p for p in list(prim_spec.properties)
                if p.name == "visibility"
                and isinstance(p, Sdf.AttributeSpec)
            ]:
                if is_command_owned_visibility_spec(prop):
                    # The whole spec is command-owned: normalize it away.
                    prim_spec.RemoveProperty(prop)
                elif "default" in prop.ListInfoKeys():
                    # Only the DEFAULT token is command-owned. Every other
                    # visibility-property field stays in the comparand, so
                    # a replay that created/removed/changed custom data,
                    # documentation, time samples, connections, or any
                    # other non-default opinion fails the proof and the
                    # coarse root routes structurally.
                    prop.ClearInfo("default")
            for child in list(prim_spec.nameChildren):
                strip_visibility(child)
            for vset in list(prim_spec.variantSets):
                for variant in list(vset.variants.values()):
                    strip_visibility(variant.primSpec)

        def prune_inert(prim_spec: Any) -> bool:
            """Prune inert scaffolding under prim_spec; True if it is inert."""
            for child in list(prim_spec.nameChildren):
                if prune_inert(child):
                    del prim_spec.nameChildren[child.name]
            pruned_set_names: set = set()
            for vset in list(prim_spec.variantSets):
                for variant in list(vset.variants.values()):
                    if prune_inert(variant.primSpec):
                        vset.RemoveVariant(variant)
                if not len(vset.variants):
                    # An emptied variant set no longer exports; its
                    # matching name-list entries are scaffolding too.
                    pruned_set_names.add(vset.name)
            if pruned_set_names:
                name_list = prim_spec.variantSetNameList
                for field in (
                    "explicitItems", "addedItems", "prependedItems",
                    "appendedItems",
                ):
                    items = list(getattr(name_list, field))
                    kept = [n for n in items if n not in pruned_set_names]
                    if kept != items:
                        setattr(name_list, field, kept)
            if list(prim_spec.properties) or list(prim_spec.nameChildren):
                return False
            if any(len(vs.variants) for vs in prim_spec.variantSets):
                return False
            if dict(prim_spec.variantSelections):
                return False
            info_keys = set(prim_spec.ListInfoKeys())
            info_keys.discard("specifier")
            if info_keys:
                # Any surviving opinion — variant selections, a residual
                # name-list opinion (e.g. an authored-empty explicit list
                # op or a deletion), references, payloads, a type name,
                # activation, kind, … — keeps the spec real.
                return False
            return prim_spec.specifier == Sdf.SpecifierOver

        pseudo_root = layer.pseudoRoot
        for root in list(pseudo_root.nameChildren):
            strip_visibility(root)
        for root in list(pseudo_root.nameChildren):
            if prune_inert(root):
                del pseudo_root.nameChildren[root.name]
        return layer.ExportToString()

    @staticmethod
    def _assemble_visibility_event(
        segments: Any, boundaries: dict, precise: bool,
        consequence_probe: Any = None,
        visibility_attr_probe: Any = None,
    ) -> Optional[ChangeEvent]:
        """Lossless event assembly from the ordered genuine notice segments.

        Every surviving genuine path reaches consumers verbatim with its
        truthful classification: bare prim RESYNCS go to ``resynced_paths``
        (the event is RESYNC-typed), resynced *property* paths are info
        changes on their properties (approved W2 classification), and all
        changed-info entries — including non-visibility survivors such as a
        re-entrant metadata mutation — pass through in ``changed_paths``.
        The visibility delta only ANNOTATES the notice-authorized visibility
        roots (predictions/boundaries never add, drop, or reclassify a
        path); the ordered raw segments ride along for audit. An event with
        visibility content is delta-marked; a purely non-visibility payload
        is emitted as a plain event and takes the ordinary rebuild path.
        """
        segments = [
            (tuple(str(p) for p in resynced), tuple(str(p) for p in changed))
            for resynced, changed in segments
        ]
        changed_paths: set = set()
        resynced_prims: set = set()
        vis_prims: set = set()

        def is_visibility(path: str) -> bool:
            # Name shape is only a FILTER; when an attribute probe is
            # available (attempt context), the path must additionally be
            # PROVEN a genuine USD visibility attribute — a relationship
            # literally named ``visibility`` keeps its structural
            # classification (round 10). Without attempt context (merged
            # scope flushes, disposal), the name-based annotation stays
            # and consumers route such paths structurally themselves.
            prim, _sep, prop = path.rpartition(".")
            if prop != "visibility":
                return False
            if visibility_attr_probe is None:
                return True
            try:
                return bool(visibility_attr_probe(path))
            except Exception:
                return False

        for resynced, changed_info in segments:
            for path in resynced:
                if _is_property_path_string(path):
                    changed_paths.add(path)
                    if is_visibility(path):
                        vis_prims.add(path.rpartition(".")[0])
                else:
                    resynced_prims.add(path)
            for path in changed_info:
                changed_paths.add(path)
                if _is_property_path_string(path):
                    if is_visibility(path):
                        vis_prims.add(path.rpartition(".")[0])
        if not changed_paths and not resynced_prims:
            return None
        if consequence_probe is None:
            # No trustworthy structural evidence (scope assembly over many
            # attempts): bare resyncs stay UNANNOTATED so every consumer
            # treats them structurally — conservative for both topology
            # and visibility (full rebuild / structural renderer sync).
            annotated_resyncs = set()
        else:
            annotated_resyncs = {
                r for r in resynced_prims if consequence_probe(r)
            }
        authored = vis_prims | annotated_resyncs
        delta = None
        if authored:
            delta = {
                "authored": tuple(sorted(authored)),
                "boundaries": boundaries,
                "segments": tuple(segments),
                # The ANNOTATED subset of resynced_paths (proven replay
                # consequences). Consumers key structural-vs-visibility
                # routing on THIS — never on ``authored``, which also
                # contains prims whose own property genuinely changed.
                "operation_resyncs": tuple(sorted(annotated_resyncs)),
            }
            if not precise:
                delta["precise"] = False
            if consequence_probe is not None and (
                visibility_attr_probe is not None
            ):
                # PROVEN annotation (round 11): both attempt-context
                # probes ran, so the annotation carries live authority.
                # Context-free assemblies (scope-conservative flushes,
                # disposal) never set this — their name-shaped annotation
                # is delivery metadata only and can never trigger the
                # renderer's live shortcut.
                delta["proven"] = True
        return ChangeEvent(
            changed_paths=tuple(sorted(changed_paths)),
            resynced_paths=tuple(sorted(resynced_prims)),
            event_type=(
                ChangeEventType.RESYNC
                if resynced_prims
                else ChangeEventType.INFO_CHANGE
            ),
            visibility_delta=delta,
        )

    @staticmethod
    def _raw_segments_event(segments: Any) -> Optional[ChangeEvent]:
        """FINAL nonthrowing fallback: minimal event from frozen raw segments.

        Deliberately independent of the semantic assembler (which may be
        the thing that just failed): plain tuple/str operations only, no
        helpers, no metadata claims. Bare entries go to ``resynced_paths``
        (structural, maximally conservative for every consumer); dotted
        entries to ``changed_paths``; no visibility annotation at all, so
        the model takes the ordinary rebuild path and the renderer takes
        structural synchronization.
        """
        changed: set = set()
        resynced: set = set()
        try:
            for segment in tuple(segments):
                seg_resynced, seg_changed = segment[0], segment[1]
                for path in tuple(seg_resynced) + tuple(seg_changed):
                    text = str(path)
                    if "." in text.rsplit("/", 1)[-1]:
                        changed.add(text)
                    else:
                        resynced.add(text)
        except Exception:
            pass  # keep whatever was gathered; this path must not throw
        if not changed and not resynced:
            return None
        return ChangeEvent(
            changed_paths=tuple(sorted(changed)),
            resynced_paths=tuple(sorted(resynced)),
            event_type=(
                ChangeEventType.RESYNC
                if resynced
                else ChangeEventType.INFO_CHANGE
            ),
            visibility_delta=None,
        )

    def _flush_survivors_after_failure(
        self, attempt: dict, primary: BaseException
    ) -> None:
        """Deliver surviving genuine roots without displacing ``primary``.

        Fallback construction and delivery each catch ``BaseException``;
        every secondary failure attaches to the active primary as a note.
        Construction bottoms out in the nonthrowing raw-segments event, so
        surviving roots cannot be lost to a fallback-of-fallback failure.
        """
        add_note = getattr(primary, "add_note", None)
        event = None
        try:
            event = self._attempt_fallback_event(attempt)
        except BaseException as fallback_error:  # noqa: BLE001 — secondary
            if callable(add_note):
                add_note(
                    "fallback assembly also failed: "
                    f"{type(fallback_error).__name__}: {fallback_error}"
                )
        if event is None:
            event = self._raw_segments_event(attempt["segments"])
        if event is None:
            return  # genuinely nothing survived the ledger
        try:
            self._deliver_visibility_event(event, attempt)
        except BaseException as delivery_error:  # noqa: BLE001 — secondary
            if callable(add_note):
                add_note(
                    "survivor delivery also failed: "
                    f"{type(delivery_error).__name__}: {delivery_error}"
                )

    def _attempt_event(self, attempt: dict) -> Optional[ChangeEvent]:
        vis_prims, resynced_prims = self._attempt_roots(attempt)
        boundaries = {}
        if vis_prims or resynced_prims:
            for path, old_state in attempt["pre"].items():
                if old_state is None:
                    continue
                new_state = self._visibility_state_for_path(path)
                if new_state is None:
                    continue
                boundaries[path] = (old_state, new_state)
        return self._assemble_visibility_event(
            attempt["segments"], boundaries, precise=True,
            consequence_probe=(
                lambda path: self._bare_resync_is_replay_consequence(
                    attempt, path
                )
            ),
            visibility_attr_probe=(
                lambda path: self._vis_path_is_visibility_attribute(
                    attempt, path
                )
            ),
        )

    def _attempt_fallback_event(self, attempt: dict) -> Optional[ChangeEvent]:
        """Conservative paths-only event straight from raw genuine payloads.

        Used when semantic assembly fails: roots are still notice-derived,
        no boundary metadata is claimed, and the model handles every root
        conservatively. The do-time predicted write set is still a
        trustworthy annotation bound (frozen at attempt begin), so Mode B
        replay roots keep their visibility annotation while unrelated
        structural resyncs keep topology semantics.
        """
        return self._assemble_visibility_event(
            attempt["segments"], {}, precise=False,
            consequence_probe=(
                lambda path: self._bare_resync_is_replay_consequence(
                    attempt, path
                )
            ),
            visibility_attr_probe=(
                lambda path: self._vis_path_is_visibility_attribute(
                    attempt, path
                )
            ),
        )

    def _commit_visibility_attempt(self, attempt: dict) -> None:
        if attempt.get("dead"):
            # The attempt was finalized by dispose(): its retained segments
            # were already delivered conservatively. Late completion must
            # not revive, duplicate, or mutate the dead attempt.
            self._maybe_complete_deferred_dispose()
            return
        try:
            self._commit_visibility_attempt_inner(attempt)
        finally:
            # UNCONDITIONAL: every attempt exit — success, assembly
            # failure, or delivery failure — drives deferred finalization.
            self._maybe_complete_deferred_dispose()

    def _commit_visibility_attempt_inner(self, attempt: dict) -> None:
        self._end_visibility_attempt(attempt)
        # Freeze the event before any delivery. If semantic assembly fails,
        # surviving edits must still be reported: fall back to the
        # conservative paths-only event from the raw retained payloads.
        try:
            event = self._attempt_event(attempt)
        except BaseException as primary:  # incl. SystemExit/KeyboardInterrupt
            self._flush_survivors_after_failure(attempt, primary)
            raise
        if event is None:
            self._maybe_complete_deferred_dispose()
            return
        self._deliver_visibility_event(event, attempt)
        self._maybe_complete_deferred_dispose()

    def _deliver_visibility_event(
        self, event: ChangeEvent, attempt: dict
    ) -> None:
        scope = self._visibility_scope
        if scope is not None and not scope["closed"]:
            scope["records"].append(
                {"event": event, "segments": list(attempt["segments"])}
            )
            return
        self._notify(event)

    def _abort_visibility_attempt(
        self, attempt: dict, cause: BaseException
    ) -> None:
        if attempt.get("dead"):
            self._maybe_complete_deferred_dispose()
            return  # finalized by dispose(); already delivered
        try:
            self._abort_visibility_attempt_inner(attempt, cause)
        finally:
            self._maybe_complete_deferred_dispose()

    def _abort_visibility_attempt_inner(
        self, attempt: dict, cause: BaseException
    ) -> None:
        self._end_visibility_attempt(attempt)
        scope = self._visibility_scope
        if scope is not None and not scope["closed"]:
            # A failed member poisons the whole scope: the outermost close
            # aborts and compensates every member (see end_undo_group).
            scope["failed"] = True
            scope["records"].append(
                {"event": None, "segments": list(attempt["segments"])}
            )
            return
        if getattr(cause, "_ovui_visibility_net_zero", False):
            # A net-zero claim is honored only after the ADAPTER verifies
            # it against the attempt's own operation-layer baselines
            # (captured before any authoring): every baselined layer must
            # be byte-identical again and no other stage layer may have
            # changed during the attempt. This is strictly stronger than
            # the command's targeted fingerprints — it also catches a
            # foreign opinion on a PRE-EXISTING spec, a sibling property
            # VALUE change, or an edit outside the recorded prefixes.
            if self._attempt_net_zero_verified(attempt):
                # Proven net-zero: no effect survived; the collected real
                # notices describe a verified round trip and no event is
                # emitted.
                return
            add_note = getattr(cause, "add_note", None)
            if callable(add_note):
                add_note(
                    "net-zero claim REJECTED by the adapter: the target "
                    "layer is not byte-identical to the attempt baseline "
                    "(a foreign consequence survived); retained genuine "
                    "segments flush conservatively"
                )
        # Surviving edits are real: flush them so no genuine notice effect
        # is hidden. Construction bottoms out nonthrowing; construction and
        # delivery failures attach to the original cause, never displacing.
        self._flush_survivors_after_failure(attempt, cause)
        self._maybe_complete_deferred_dispose()

    def run_visibility_command_edge(self, command: Any, edge_fn: Any) -> None:
        """Bracket a command undo/redo edge (invoked outside ``_push``)."""
        hint = getattr(command, "edge_hint_prims", command.predicted_write_prims)
        attempt = self._begin_visibility_attempt(hint(), command=command)
        try:
            edge_fn()
        except BaseException as exc:
            # Edge failures — including BaseException after real replay
            # authoring — finalize the attempt (compensation/net-zero or a
            # conservative flush) before the original exception continues.
            self._abort_visibility_attempt(attempt, exc)
            raise
        finally:
            self._maybe_complete_deferred_dispose()
        self._commit_visibility_attempt(attempt)
        self._maybe_complete_deferred_dispose()

    def _maybe_complete_deferred_dispose(self) -> None:
        """Complete a deferred disposal once the in-flight attempt exits.

        An open scope no longer blocks completion: the immediate dispose
        path folds the attempt segments into the scope records and closes
        it as ONE conservative disposition (bounded never-closing-owner
        recovery).
        """
        if not self._dispose_deferred:
            return
        if self._visibility_attempts:
            return
        self._dispose_deferred = False
        active = sys.exc_info()[1]
        if active is None:
            self.dispose()
            return
        # Deferred completion running while the ACTIVE operation's
        # throwable is unwinding (the hooks in commit/abort run from
        # ``finally``): teardown must complete and every subscriber must
        # be attempted, but the ORIGINAL operation failure keeps its
        # identity — any disposal-time compensation/assembly/delivery/
        # cleanup failure (BaseException included) attaches as an
        # inspectable note instead of displacing the primary.
        try:
            self.dispose()
        except BaseException as teardown_error:  # noqa: BLE001 — secondary
            add_note = getattr(active, "add_note", None)
            if callable(add_note):
                add_note(
                    "deferred disposal during unwind also failed: "
                    f"{type(teardown_error).__name__}: {teardown_error}"
                )
                for extra in getattr(teardown_error, "__notes__", []) or []:
                    add_note(f"  deferred-disposal detail: {extra}")

    def _ensure_manager_groups_closed(self, floor_depth: int) -> None:
        """Force the shared UndoManager back to its pre-scope group depth.

        Runs after every close/cancel attempt (including failed ones): a
        group accumulator that outlives its owning scope would silently
        capture the next adapter's pushes. ``force_discard_group`` never
        raises; discarded commands' state truthfulness is the caller's
        responsibility (baseline verification/replay + conservative event).
        """
        manager = self._undo_manager
        if manager is None:
            return
        depth = getattr(manager, "open_group_depth", None)
        discard = getattr(manager, "force_discard_group", None)
        if depth is None or not callable(discard):
            return
        while manager.open_group_depth > floor_depth:
            discard()

    def _scope_baselines_verified(self, scope: dict, errors: list) -> bool:
        """Prove every first-touch layer field-identical to its baseline.

        A verification exception is NOT proof: it is recorded and the scope
        stays unproved (uncertain), so the retained segments flush
        conservatively instead of being silently suppressed.
        """
        try:
            return all(
                layer.ExportToString() == baseline_text
                for layer, baseline_text in scope["baselines"].values()
            )
        except BaseException as exc:  # unprovable is NOT proof
            errors.append(exc)
            return False

    def _replay_scope_baselines(self, scope: dict, errors: list) -> None:
        """Directly restore every scope layer from its replayable baseline.

        Covers effects ``UndoManager.cancel_group()`` cannot compensate — a
        partially-failed member that authored before its command was
        recorded. The restore is bracketed as an attempt so its genuine
        notices join the scope's retained segments (delivered if the scope
        ends uncertain; suppressed only after equality is re-proven).
        """
        for layer, baseline_text in scope["baselines"].values():
            try:
                if layer.ExportToString() == baseline_text:
                    continue
            except BaseException as exc:
                errors.append(exc)  # unverifiable: attempt the restore anyway
            attempt = self._begin_visibility_attempt(())
            try:
                if not layer.ImportFromString(baseline_text):
                    raise RuntimeError(
                        "baseline replay rejected for layer "
                        f"{layer.identifier}"
                    )
            except BaseException as exc:
                errors.append(exc)
            finally:
                self._end_visibility_attempt(attempt)
                scope["records"].append(
                    {"event": None, "segments": list(attempt["segments"])}
                )

    @staticmethod
    def _merged_scope_event(records: List[dict]) -> Optional[ChangeEvent]:
        events = [r["event"] for r in records if r["event"] is not None]
        if not events:
            return None
        if len(events) == 1:
            return events[0]
        changed: set = set()
        resynced: set = set()
        authored: set = set()
        operation_resyncs_all: set = set()
        segments: list = []
        boundaries: dict = {}
        precise = True
        proven = True
        for event in events:
            changed.update(event.changed_paths)
            resynced.update(event.resynced_paths)
            delta = event.visibility_delta or {}
            authored.update(delta.get("authored") or ())
            operation_resyncs_all.update(delta.get("operation_resyncs") or ())
            segments.extend(delta.get("segments") or ())
            if not delta.get("precise", True):
                precise = False
            if not delta.get("proven", False):
                proven = False
            for path, (old, new) in (delta.get("boundaries") or {}).items():
                if path in boundaries:
                    boundaries[path] = (boundaries[path][0], new)
                else:
                    boundaries[path] = (old, new)
        delta = {
            "authored": tuple(sorted(authored)),
            "boundaries": boundaries,
            "segments": tuple(segments),
            "operation_resyncs": tuple(sorted(operation_resyncs_all)),
        }
        if not precise:
            delta["precise"] = False
        if proven:
            delta["proven"] = True
        return ChangeEvent(
            changed_paths=tuple(sorted(changed)),
            resynced_paths=tuple(sorted(resynced)),
            event_type=(
                ChangeEventType.RESYNC
                if resynced
                else ChangeEventType.INFO_CHANGE
            ),
            visibility_delta=delta if authored else None,
        )

    def _scope_conservative_event(
        self, records: List[dict]
    ) -> Optional[ChangeEvent]:
        """Lossless paths-only event from every raw segment the scope kept."""
        segments = [
            seg for record in records for seg in record["segments"]
        ]
        return self._assemble_visibility_event(segments, {}, precise=False)

    def can_edit_visibility(self, item: AdapterItem) -> bool:
        if not _is_live_prim(item):
            return False
        if item.GetPath() == Sdf.Path.absoluteRootPath:
            return False
        if item.IsInstanceProxy():
            return False
        if not item.IsActive():
            return False
        return bool(UsdGeom.Imageable(item))

    # ── Rename ────────────────────────────────────────────────────────────────

    def can_rename(self, item: AdapterItem) -> bool:
        if item.GetPath() == Sdf.Path.absoluteRootPath:
            return False
        if item.IsInstanceProxy():
            return False
        return True

    def rename(self, item: AdapterItem, new_name: str) -> str:
        from ovui_data_adapters.openusd import NamespaceEditCommand
        old_path = item.GetPath()
        new_path = old_path.GetParentPath().AppendChild(new_name)
        layer = self._stage.GetEditTarget().GetLayer()
        cmd = NamespaceEditCommand(layer, old_path, new_path)
        self._push(cmd)
        self._notify(ChangeEvent(
            changed_paths=(),
            resynced_paths=(str(new_path),),
            event_type=ChangeEventType.RESYNC,
        ))
        return new_name

    def normalize_name(self, name: str) -> str:
        return _NAME_RE.sub("_", name)

    # ── Drag-drop / reparent ──────────────────────────────────────────────────

    def can_reparent(self, items: List[AdapterItem], new_parent: AdapterItem) -> bool:
        new_parent_path = new_parent.GetPath()
        for item in items:
            item_path = item.GetPath()
            # Cannot reparent into self
            if item_path == new_parent_path:
                return False
            # Cannot reparent into a descendant of the item
            if new_parent_path.HasPrefix(item_path):
                return False
        return True

    def reparent(
        self,
        items: List[AdapterItem],
        new_parent: AdapterItem,
        position: ReparentPosition,
    ) -> None:
        from ovui_data_adapters.openusd import NamespaceEditCommand
        layer = self._stage.GetEditTarget().GetLayer()

        if position == ReparentPosition.CHILD:
            target_parent_path = new_parent.GetPath()
        else:
            # BEFORE/AFTER: place alongside new_parent in its parent
            target_parent_path = new_parent.GetPath().GetParentPath()

        moved_paths = []
        for item in items:
            old_path = item.GetPath()
            new_path = target_parent_path.AppendChild(old_path.name)
            moved_paths.append(str(new_path))
            cmd = NamespaceEditCommand(layer, old_path, new_path)
            self._push(cmd)

        self._notify(ChangeEvent(
            changed_paths=(),
            resynced_paths=tuple(moved_paths),
            event_type=ChangeEventType.RESYNC,
        ))

    # ── Filter ────────────────────────────────────────────────────────────────

    def filter_items(
        self,
        items: List[AdapterItem],
        predicate: Callable[[AdapterItem], bool],
    ) -> List[AdapterItem]:
        return [item for item in items if predicate(item)]

    # ── Change notifications ──────────────────────────────────────────────────

    def subscribe_changes(self, callback: Callable[[ChangeEvent], None]) -> SubscriptionProtocol:

        _drain_stale_revocations(self)
        self._subscribers.append(callback)
        return _StageSubscription(weakref.ref(self), "changes", callback)

    @property
    def disposal_pending(self) -> bool:
        """True while a requested disposal awaits open-ownership resolution."""
        return self._dispose_deferred

    @property
    def ownership_busy(self) -> bool:
        """True while an authoring notification is live on the current stack.

        Read-only replacement PREFLIGHT: while this is True, any stage
        replacement/teardown request would have to defer, so callers (the
        Application) must refuse or queue the replacement BEFORE mutating
        any provider, file-path, or history state. Purely observational —
        reading it requests nothing and changes nothing.
        """
        return bool(self._visibility_attempts)

    def cancel_deferred_disposal(self) -> None:
        """Withdraw a deferral this caller itself just requested.

        Used by the Application's refusal path: when even forced disposal
        defers (replacement requested from inside an active authoring
        notification) and the replacement is therefore REFUSED, the old
        adapter must remain fully functional — the caller's own pending
        request must not tear it down when the in-flight operation exits.
        """
        self._dispose_deferred = False

    def dispose(self, force: bool = False) -> bool:
        """Finalize and detach (provider/stage replacement or shutdown).

        Every retained genuine root is truthfully delivered to the OLD
        subscribers before they are dropped: an open visibility scope is
        frozen as uncertain and flushed conservatively from its retained
        segments, then the pending notice queue drains. Only afterwards are
        the Tf.Notice listeners revoked and the subscriber list cleared.
        The scope token is dead after this call; late ``end_undo_group`` /
        ``abort_undo_group`` calls cannot revive it. Idempotent.
        """
        if self._visibility_attempts:
            # Re-entrant disposal during an IN-FLIGHT logical attempt (the
            # only deferral case — it exists solely within one operation's
            # call stack, so no later adapter can interleave): revoking the
            # notice listener now could lose the in-flight genuine notice,
            # and closing the shared manager's group mid-push would let the
            # surviving command land OUTSIDE its owner (a later top-level
            # history entry with no event). That holds for FORCED disposal
            # too — force cannot cut an authoring call on the current
            # stack; there is nothing "wedged" to cut, because the attempt
            # always exits with the stack (BaseException-safe hooks in
            # commit/abort), at which point the full teardown runs with the
            # complete genuine ledger and delivers ONE truthful disposition
            # to the old subscribers BEFORE detaching. An open scope
            # WITHOUT an in-flight attempt (e.g. an owner that never
            # closes) is finalized IMMEDIATELY below.
            # EXPLICIT COMPLETION CONTRACT: returns False (and
            # ``disposal_pending`` is True); callers must not proceed as if
            # ownership were resolved — replacement stays pending or is
            # explicitly refused until the deferred completion runs.
            self._dispose_deferred = True
            return False
        self._dispose_deferred = False
        errors: list = []
        # Orphaned attempts (defensive; the deferral above keeps normal
        # flows out of here): their retained genuine segments must reach
        # the still-subscribed consumers before any detachment.
        open_attempts = list(self._visibility_attempts)
        self._visibility_attempts = []
        attempt_segments = [
            seg for attempt in open_attempts for seg in attempt["segments"]
        ]
        for attempt in open_attempts:
            attempt["dead"] = True
        scope_for_fold = self._visibility_scope
        if attempt_segments and scope_for_fold is not None and not (
            scope_for_fold["closed"]
        ):
            # Forced disposal mid-scope: the attempts' genuine segments
            # join the scope records so the outer operation still yields
            # ONE conservative event/history disposition below.
            scope_for_fold["records"].append(
                {"event": None, "segments": attempt_segments}
            )
            attempt_segments = []
        if attempt_segments:
            pending_attempt_event: Optional[ChangeEvent] = None
            try:
                pending_attempt_event = self._assemble_visibility_event(
                    attempt_segments, {}, precise=False
                )
            except BaseException as exc:
                errors.append(exc)
            if pending_attempt_event is not None:
                try:
                    self._notify(pending_attempt_event)
                except BaseException as exc:
                    errors.append(exc)
        scope = self._visibility_scope
        if scope is not None and not scope["closed"]:
            pending: Optional[ChangeEvent] = None
            try:
                pending = self._scope_conservative_event(scope["records"])
            except BaseException as exc:
                errors.append(exc)
            # The shared manager's group must not outlive this scope: commit
            # the open accumulators (preserving the user's edits as one
            # undoable entry), then force-discard anything a failed commit
            # leaves behind.
            if self._undo_manager is not None:
                for _ in range(self._undo_group_depth):
                    try:
                        self._undo_manager.end_group()
                    except BaseException as exc:
                        errors.append(exc)
                        break
                self._ensure_manager_groups_closed(scope["manager_floor"])
            scope["closed"] = True
            self._visibility_scope_audit.append({
                "label": scope["label"],
                "failed": True,  # disposed-open is an abnormal close
                "segments": [
                    seg for r in scope["records"] for seg in r["segments"]
                ],
            })
            del self._visibility_scope_audit[:-16]
            self._visibility_scope = None
            self._undo_group_depth = 0
            if pending is not None:
                try:
                    self._notify(pending)
                except BaseException as exc:
                    errors.append(exc)
        try:
            if self._pending_changed or self._pending_resynced or (
                self._pending_default_change is not None
            ):
                self._flush()
        except BaseException as exc:
            errors.append(exc)
        for key_attr in ("_notice_key", "_layer_notice_key", "_sdf_change_key"):
            key = getattr(self, key_attr, None)
            if key is not None:
                try:
                    key.Revoke()
                except Exception:
                    pass
                setattr(self, key_attr, None)
        self._subscribers.clear()
        if errors:
            error = errors[0]
            for extra in errors[1:]:
                add_note = getattr(error, "add_note", None)
                if callable(add_note):
                    add_note(f"also: {type(extra).__name__}: {extra}")
            raise error
        return True

    def notify_transform_changed(
        self,
        paths: List[str],
        source: Optional[str] = None,
    ) -> None:
        """Emit an explicit transform event after suppressed viewport edits."""
        changed: list[str] = []
        seen: set[str] = set()
        for path in paths:
            for changed_path in self._transform_change_paths(path):
                if changed_path in seen:
                    continue
                seen.add(changed_path)
                changed.append(changed_path)
        if not changed:
            return
        self._notify(ChangeEvent(
            changed_paths=tuple(changed),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
            source=source,
        ))

    def _transform_change_paths(self, path: str) -> list[str]:
        try:
            sdf_path = Sdf.Path(path)
            prim_path = sdf_path.GetPrimPath() if sdf_path.IsPropertyPath() else sdf_path
            prim = self._stage.GetPrimAtPath(prim_path)
        except Exception:
            return [str(path)]
        if not prim or not prim.IsValid():
            return [str(prim_path)]
        changed = [
            f"{prim_path}.{attr.GetName()}"
            for attr in prim.GetAttributes()
            if _is_transform_property_name(attr.GetName())
        ]
        return changed or [str(prim_path)]

    # ── Undo integration ──────────────────────────────────────────────────────

    def begin_undo_group(self, label: str) -> None:
        """Transactional scope acquisition.

        The underlying UndoManager group is acquired FIRST: if it raises,
        no adapter scope is created and the depth counter is untouched, so
        a failed acquisition cannot leak an open token.
        """
        manager_floor = 0
        if self._undo_manager is not None:
            manager_floor = getattr(self._undo_manager, "open_group_depth", 0)
            self._undo_manager.begin_group(label)
        if self._undo_group_depth == 0:
            self._visibility_scope = {
                "label": label,
                "records": [],       # {'event': ChangeEvent|None, 'segments': [...]}
                "baselines": {},     # layer identifier -> (layer, pre-scope text)
                "failed": False,
                "closed": False,
                # Manager group depth BEFORE this scope opened its group:
                # finalization guarantees the manager returns to this floor,
                # so no accumulator can outlive the owning scope.
                "manager_floor": manager_floor,
            }
        self._undo_group_depth += 1

    def abort_undo_group(self) -> None:
        """Owner-driven abort: poison the scope, then close it.

        Structured scope owners (e.g. the visibility value model's group
        around a multi-selection) call this instead of ``end_undo_group``
        when any member raised, so the outermost close cancels and
        compensates the entire group even for failures the adapter itself
        never observed.

        When invoked while an exception is being handled (the normal abort
        shape: ``except: adapter.abort_undo_group(); raise``), cleanup
        failures NEVER displace that original operation error — they are
        attached to it as notes and swallowed here so the caller's re-raise
        keeps the member error primary.
        """
        scope = self._visibility_scope
        if scope is not None and not scope["closed"]:
            scope["failed"] = True
        active = sys.exc_info()[1]
        if active is None:
            self.end_undo_group()
            return
        try:
            self.end_undo_group()
        except BaseException as cleanup_error:  # secondary: never displaces
            add_note = getattr(active, "add_note", None)
            if callable(add_note):
                add_note(
                    "abort cleanup also failed: "
                    f"{type(cleanup_error).__name__}: {cleanup_error}"
                )

    def end_undo_group(self) -> None:
        """Close the current group; the outermost close disposes the scope.

        A scope with a failed member is aborted as a whole: the UndoManager
        group is cancelled (compensating every completed member through its
        own bracketed undo edge, whose genuine segments join this scope),
        every affected layer is proven field-identical to its first-touch
        baseline before the retained segments are suppressed, and anything
        unproven flushes one conservative event. State finalization happens
        before any error propagates; the scope token is dead afterwards.
        """
        if self._undo_group_depth <= 0:
            # Dead token: the scope was already finalized (close, abort, or
            # dispose). A late call cannot revive it or touch the manager.
            return
        outermost = self._undo_group_depth == 1
        if not outermost:
            self._undo_group_depth -= 1
            if self._undo_manager is not None:
                self._undo_manager.end_group()
            return

        scope = self._visibility_scope
        pending_event: Optional[ChangeEvent] = None
        errors: list = []
        try:
            if scope is not None and scope["failed"]:
                # Scope-wide abort: cancel compensates completed members;
                # their bracketed undo edges append segments to this scope.
                if self._undo_manager is not None:
                    try:
                        self._undo_manager.cancel_group()
                    except BaseException as exc:  # compensation failure
                        errors.append(exc)
                verified = not errors and self._scope_baselines_verified(
                    scope, errors
                )
                if not verified:
                    # Cancellation could not prove equality (an unrecorded
                    # partially-failed member, a cancel failure, or an
                    # unverifiable baseline): replay every first-touch
                    # baseline directly, then re-prove.
                    self._replay_scope_baselines(scope, errors)
                    verified = self._scope_baselines_verified(scope, errors)
                if not verified:
                    # Frozen disposition: UNCERTAIN. Every retained genuine
                    # segment flushes as one conservative paths-only event;
                    # assembly bottoms out in the nonthrowing raw event.
                    try:
                        pending_event = self._scope_conservative_event(
                            scope["records"]
                        )
                    except BaseException as exc:
                        errors.append(exc)
                        pending_event = self._raw_segments_event(
                            [seg for r in scope["records"]
                             for seg in r["segments"]]
                        )
            else:
                if self._undo_manager is not None:
                    try:
                        self._undo_manager.end_group()
                    except BaseException as exc:
                        errors.append(exc)
                if scope is not None:
                    # Event-assembly failure must never hide the members'
                    # surviving edits: fall back to the conservative
                    # paths-only event from the retained raw segments.
                    try:
                        pending_event = self._merged_scope_event(
                            scope["records"]
                        )
                    except BaseException as exc:
                        errors.append(exc)
                        try:
                            pending_event = self._scope_conservative_event(
                                scope["records"]
                            )
                        except BaseException as fallback_exc:
                            errors.append(fallback_exc)
                            pending_event = self._raw_segments_event(
                                [seg for r in scope["records"]
                                 for seg in r["segments"]]
                            )
        finally:
            # Finalize unconditionally: dead token, closed scope, depth 0,
            # audit record retained. The shared UndoManager must return to
            # its pre-scope group depth even when end/cancel raised — a
            # leaked accumulator would silently swallow the next adapter's
            # edits. State truthfulness for any force-discarded commands is
            # already owned above (baseline verification/replay, and the
            # conservative event when unproven).
            if scope is not None:
                self._ensure_manager_groups_closed(scope["manager_floor"])
                scope["closed"] = True
                self._visibility_scope_audit.append({
                    "label": scope["label"],
                    "failed": scope["failed"],
                    "segments": [
                        seg for r in scope["records"] for seg in r["segments"]
                    ],
                })
                del self._visibility_scope_audit[:-16]  # bounded audit log
            self._visibility_scope = None
            self._undo_group_depth = 0

        try:
            if pending_event is not None:
                try:
                    self._notify(pending_event)
                except BaseException as exc:
                    errors.append(exc)
            if errors:
                error = errors[0]
                for extra in errors[1:]:
                    add_note = getattr(error, "add_note", None)
                    if callable(add_note):
                        add_note(f"also: {type(extra).__name__}: {extra}")
                raise error
        finally:
            self._maybe_complete_deferred_dispose()

    # ── Notification suppression ──────────────────────────────────────────────

    @contextlib.contextmanager
    def suppress_change_notifications(self) -> ContextManager:
        old = self._suppressed
        self._suppressed = True
        try:
            yield
        finally:
            self._suppressed = old

    # ── World AABB / framing / bound-camera (Step 7 plan §7) ──────────────────
    #
    # Relocated verbatim from ``ovui_widgets/viewport/viewport_widget.py`` so the
    # widget's inline pxr code can be replaced by abstract calls in Step 17.
    # Until then the widget keeps its own inline copies and these methods
    # mirror the same logic.

    @staticmethod
    def _prims_to_bound(stage: Any, path: str) -> List[Any]:
        """Return the list of prims whose bounds union for ``path``.

        Mirrors :meth:`ViewportWidget._prims_to_bound`: the pseudo-root
        ``"/"`` returns its top-level children (``BBoxCache.ComputeWorldBound``
        on the pseudo-root yields an empty bound because it isn't an
        Imageable prim); every other path returns the single prim at that
        path when valid.
        """
        if path == "/":
            pseudo_root = stage.GetPseudoRoot()
            return [child for child in pseudo_root.GetChildren() if child.IsValid()]
        prim = stage.GetPrimAtPath(path)
        return [prim] if prim.IsValid() else []

    def compute_world_aabb(self, paths: List[str]):
        """Combined world AABB across ``paths``; ``None`` if empty.

        Relocates the BBoxCache iteration from
        ``ViewportWidget.frame_paths`` (lines ~1207-1227) verbatim. Returns
        the same ``((min_xyz), (max_xyz))`` tuple shape the inline code
        produces today; ``None`` when ``paths`` is empty, the stage is
        unavailable, or no prim contributes a non-empty bound.
        """
        if not paths or not HAS_USD or self._stage is None:
            return None
        try:
            from pxr import Gf, UsdGeom
            stage = self._stage
            bbox_cache = UsdGeom.BBoxCache(
                stage.GetTimeCode() if hasattr(stage, "GetTimeCode") else 0,
                [UsdGeom.Tokens.default_],
            )
            total = Gf.BBox3d()
            for path in paths:
                prims = self._prims_to_bound(stage, path)
                for prim in prims:
                    total = Gf.BBox3d.Combine(
                        total, bbox_cache.ComputeWorldBound(prim)
                    )
            rng = total.ComputeAlignedRange()
            if rng.IsEmpty():
                return None
            minp = rng.GetMin()
            maxp = rng.GetMax()
            return (
                (float(minp[0]), float(minp[1]), float(minp[2])),
                (float(maxp[0]), float(maxp[1]), float(maxp[2])),
            )
        except Exception:
            return None

    def compute_prim_world_aabb_with_extent_fallback(self, path: str):
        """Two-tier world AABB for one prim: ``Boundable`` extent → ``BBoxCache``.

        Relocates :meth:`ViewportWidget._compute_world_bbox` verbatim
        (lines ~1100-1159). For :class:`UsdGeom.Boundable` prims, prefers
        ``Boundable.ComputeExtentFromPlugins`` so a Property-panel
        ``radius`` / ``size`` edit invalidates the cached ``extent``
        attribute correctly; falls back to ``UsdGeom.BBoxCache`` for
        non-Boundable selections (Xforms, Scopes). Returns ``None`` for
        invalid paths or any error.
        """
        if not HAS_USD or self._stage is None:
            return None
        try:
            from pxr import Gf, Usd, UsdGeom
            stage = self._stage
            prim = stage.GetPrimAtPath(path)
            if not prim.IsValid():
                return None
            tc = Usd.TimeCode.Default()
            rng = None
            if prim.IsA(UsdGeom.Boundable):
                boundable = UsdGeom.Boundable(prim)
                local_extent = UsdGeom.Boundable.ComputeExtentFromPlugins(
                    boundable, tc
                )
                if local_extent:
                    ltow = UsdGeom.Imageable(prim).ComputeLocalToWorldTransform(tc)
                    local_range = Gf.Range3d(
                        Gf.Vec3d(local_extent[0]),
                        Gf.Vec3d(local_extent[1]),
                    )
                    world_bbox = Gf.BBox3d(local_range, ltow)
                    rng = world_bbox.ComputeAlignedRange()
            if rng is None or rng.IsEmpty():
                bcache = UsdGeom.BBoxCache(tc, [UsdGeom.Tokens.default_])
                bbox = bcache.ComputeWorldBound(prim)
                rng = bbox.ComputeAlignedRange()
            if rng.IsEmpty():
                return None
            minp = rng.GetMin()
            maxp = rng.GetMax()
            return (
                (float(minp[0]), float(minp[1]), float(minp[2])),
                (float(maxp[0]), float(maxp[1]), float(maxp[2])),
            )
        except Exception:
            return None

    def read_bound_camera(self):
        """Return the stage's authored ``boundCamera`` pose, or ``None``.

        Delegates to
        :func:`ovui_data_adapters.openusd.bound_camera.read_bound_camera`
        — the parser was relocated in Step 13 of the plan.
        """
        if self._stage is None:
            return None
        try:
            from ovui_data_adapters.openusd.bound_camera import read_bound_camera
            return read_bound_camera(self._stage)
        except Exception:
            return None

    def read_stage_up_axis(self) -> str:
        """Return the authored USD stage up-axis, independent of camera metadata."""
        if not HAS_USD or self._stage is None:
            return "Y"
        try:
            axis = str(UsdGeom.GetStageUpAxis(self._stage) or "Y").upper()
        except Exception:
            return "Y"
        return "Z" if axis == "Z" else "Y"

    def list_cameras(self) -> List[StageChoice]:
        """Return selectable ``UsdGeom.Camera`` prims in stage traversal order."""
        if not HAS_USD or self._stage is None:
            return []
        return [
            _choice_for_prim(prim)
            for prim in self._stage.Traverse()
            if prim.IsValid() and prim.IsA(UsdGeom.Camera)
        ]

    def read_camera_pose(self, path: str) -> Optional[BoundCameraPose]:
        """Return a viewport pose for the camera prim at ``path``."""
        if self._stage is None:
            return None
        try:
            from ovui_data_adapters.openusd.bound_camera import read_camera_pose
            return read_camera_pose(self._stage, path)
        except Exception:
            return None

    def write_camera_pose_from_matrices(
        self,
        path: str,
        view_matrix: Any,
        proj_matrix: Any,
        width: int,
        height: int,
        target_world: Any,
        source: Optional[str] = None,
        undoable: bool = True,
    ) -> bool:
        """Author the selected USD camera pose from viewport navigation.

        ``proj_matrix``/``width``/``height`` are accepted for parity with the
        renderer camera writer. Navigation edits only change pose here: lens
        and clipping attributes remain as the user's camera authored them.
        ``source`` is carried onto the resulting ``ChangeEvent`` when the USD
        notice batch contains only this write's camera changes. ``undoable``
        controls whether this single final pose write joins the UndoManager.
        """
        if self._stage is None:
            return False
        try:
            from ovui_data_adapters.openusd.commands import CameraPoseCommand

            command = CameraPoseCommand(
                self._stage,
                path,
                view_matrix,
                (
                    float(target_world[0]),
                    float(target_world[1]),
                    float(target_world[2]),
                ),
            )
            previous_source = self._current_notice_source
            self._current_notice_source = source
            try:
                if undoable and self._undo_manager is not None:
                    self._undo_manager.push(command)
                else:
                    command.do()
            finally:
                self._current_notice_source = previous_source
        except Exception:
            return False
        return True

    def list_core_materials(
        self,
        *,
        selection_paths: Iterable[str] | None = None,
    ) -> CoreMaterialCatalog:
        """Return adapter-backed core material catalog entries for the USD context."""
        selection_tuple = tuple(str(path) for path in (selection_paths or ()))
        if not HAS_USD:
            return CoreMaterialCatalog(
                selection_paths=selection_tuple,
                warnings=(
                    _core_material_warning(
                        CoreMaterialErrorCode.UNSUPPORTED,
                        "OpenUSD core material actions are not available.",
                    ),
                ),
            )
        if self._stage is None:
            return CoreMaterialCatalog(
                selection_paths=selection_tuple,
                warnings=(
                    _core_material_warning(
                        CoreMaterialErrorCode.NO_ACTIVE_STAGE,
                        "No active OpenUSD stage is available.",
                    ),
                ),
            )

        stage_id = _create_stage_identifier(self._stage)
        edit_target_layer, edit_target_reason = _create_edit_target_layer(self._stage)
        edit_target_id = ""
        if edit_target_layer is not None:
            edit_target_id = str(getattr(edit_target_layer, "identifier", "") or "")
        bindable_selection_paths = _core_material_bindable_selection_paths(
            self._stage,
            selection_tuple,
        )

        materials: list[CoreMaterialDescriptor] = []
        for spec in _CORE_MATERIAL_SPECS:
            disabled_reason = _core_material_disabled_reason(
                spec,
                edit_target_reason=edit_target_reason,
            )
            bind_supported = bool(
                not disabled_reason
                and bindable_selection_paths
                and spec.binding_policy != CoreMaterialBindingPolicy.NONE
            )
            materials.append(
                CoreMaterialDescriptor(
                    material_id=spec.material_id,
                    label=spec.label,
                    group_id=spec.group_id,
                    family=spec.family,
                    kind=spec.kind,
                    shader_type=spec.shader_type,
                    order=spec.order,
                    capabilities=spec.capabilities,
                    requirements=spec.requirements,
                    default_scope_path=spec.default_scope_path,
                    default_name=spec.default_name,
                    binding_policy=spec.binding_policy,
                    create_supported=not disabled_reason,
                    bind_supported=bind_supported,
                    enabled=not disabled_reason,
                    disabled_reason=disabled_reason,
                    metadata={
                        "schema_family": spec.schema_family,
                        "mdl_source_asset": (
                            _core_material_mdl_source_asset(spec)
                            if spec.schema_family == "mdl"
                            else ""
                        ),
                        "mdl_sub_identifier": (
                            spec.shader_type if spec.schema_family == "mdl" else ""
                        ),
                    },
                )
            )

        group_order = {group.group_id: group.order for group in _CORE_MATERIAL_GROUPS}
        materials_tuple = tuple(
            sorted(
                materials,
                key=lambda material: (
                    group_order.get(material.group_id, 1000.0),
                    material.order,
                    material.material_id,
                ),
            )
        )
        return CoreMaterialCatalog(
            groups=tuple(
                sorted(_CORE_MATERIAL_GROUPS, key=lambda group: (group.order, group.group_id))
            ),
            materials=materials_tuple,
            active_stage_id=stage_id,
            edit_target_id=edit_target_id,
            selection_paths=selection_tuple,
            bindable_selection_paths=bindable_selection_paths,
        )

    def create_material(self, request: CreateMaterialRequest) -> CreateMaterialResult:
        """Execute an adapter-backed core-material create action against USD."""
        catalog = self.list_core_materials(selection_paths=request.selection_paths)
        if catalog.is_empty:
            if catalog.warnings:
                warning = catalog.warnings[0]
                error_code = CoreMaterialErrorCode.CREATE_FAILED
                try:
                    error_code = CoreMaterialErrorCode(warning.code)
                except ValueError:
                    pass
                return _core_material_error(warning.message, error_code)
            return _core_material_error(
                "No core materials are available.",
                CoreMaterialErrorCode.UNSUPPORTED,
            )

        material = catalog.material(request.material_id)
        if material is None:
            return _core_material_error(
                f"Unknown core material: {request.material_id}",
                CoreMaterialErrorCode.UNSUPPORTED,
            )
        if not material.is_available or not material.create_supported:
            return _core_material_error(
                material.disabled_reason or f"Core material is disabled: {request.material_id}",
                CoreMaterialErrorCode.DISABLED,
            )

        edit_target_layer, edit_target_reason = _create_edit_target_layer(self._stage)
        if edit_target_reason or edit_target_layer is None:
            return _core_material_error(
                edit_target_reason or "No current edit target is available.",
                CoreMaterialErrorCode.DISABLED,
            )

        scope_path, scope_error, create_missing_scope = _core_material_resolve_scope_path(
            self._stage,
            material,
            request,
        )
        if scope_error or scope_path is None:
            return _core_material_error(scope_error, CoreMaterialErrorCode.VALIDATION_FAILED)

        child_name = _create_child_name(request.requested_name, material.default_name)
        material_path = _create_unique_child_path(self._stage, scope_path, child_name)

        snapshot = _create_snapshot_layer(edit_target_layer)
        try:
            _, scope_error = _create_ensure_parent(
                self._stage,
                scope_path,
                create_missing=create_missing_scope,
            )
            if scope_error:
                raise ValueError(scope_error)
            prim, created_paths, warnings = self._define_core_material(
                material,
                material_path,
            )
            if prim is None or not prim.IsValid():
                raise RuntimeError(f"Core material create did not author {material_path}")
        except Exception as exc:
            _create_restore_layer(edit_target_layer, snapshot)
            return _core_material_error(
                f"Core material create failed: {exc}",
                CoreMaterialErrorCode.CREATE_FAILED,
            )

        primary_path = str(prim.GetPath())
        self._notify(ChangeEvent(
            changed_paths=(),
            resynced_paths=tuple(created_paths),
            event_type=ChangeEventType.RESYNC,
        ))
        return CreateMaterialResult.accepted_result(
            created_material_path=primary_path,
            created_paths=created_paths,
            selection_paths=(primary_path,),
            focus_path=primary_path,
            message=f"Created material {primary_path}.",
            warnings=warnings,
        )

    def _define_core_material(
        self,
        material: CoreMaterialDescriptor,
        material_path: Any,
    ) -> tuple[Any, tuple[str, ...], tuple[CoreMaterialWarning, ...]]:
        if material.kind is CoreMaterialKind.USD_PREVIEW_SURFACE:
            prim, created_paths, _, _ = self._define_usd_preview_surface_material(
                material_path,
                (),
            )
            return prim, created_paths, ()
        if material.family is CoreMaterialFamily.MDL:
            prim, created_paths = self._define_mdl_material(material, material_path)
            return prim, created_paths, ()
        raise ValueError(f"Unsupported core material kind: {material.kind}")

    def _define_mdl_material(
        self,
        material: CoreMaterialDescriptor,
        material_path: Any,
    ) -> tuple[Any, tuple[str, ...]]:
        if UsdShade is None:
            raise RuntimeError("UsdShade is unavailable.")
        source_asset = str(material.metadata.get("mdl_source_asset") or f"{material.shader_type}.mdl")
        sub_identifier = str(
            material.metadata.get("mdl_sub_identifier") or material.shader_type
        )
        if not source_asset or not sub_identifier:
            raise RuntimeError(f"MDL material metadata is incomplete: {material.material_id}")

        mdl_material = UsdShade.Material.Define(self._stage, material_path)
        shader_path = material_path.AppendChild("Shader")
        shader = UsdShade.Shader.Define(self._stage, shader_path)
        shader_prim = shader.GetPrim()
        shader_prim.CreateAttribute(
            "info:implementationSource",
            Sdf.ValueTypeNames.Token,
            custom=False,
        ).Set("sourceAsset")
        shader_prim.CreateAttribute(
            "info:mdl:sourceAsset",
            Sdf.ValueTypeNames.Asset,
            custom=False,
        ).Set(Sdf.AssetPath(source_asset))
        shader_prim.CreateAttribute(
            "info:mdl:sourceAsset:subIdentifier",
            Sdf.ValueTypeNames.Token,
            custom=False,
        ).Set(sub_identifier)
        shader_output = shader.CreateOutput("out", Sdf.ValueTypeNames.Token)
        for output_name in ("surface", "displacement", "volume"):
            mdl_material.CreateOutput(f"mdl:{output_name}", Sdf.ValueTypeNames.Token).ConnectToSource(
                shader_output
            )
        return mdl_material.GetPrim(), (str(material_path), str(shader_path))

    def bind_material(self, request: BindMaterialRequest) -> BindMaterialResult:
        """Bind an existing material to selected USD prims."""
        if not HAS_USD:
            message = "OpenUSD core material binding is not available."
            return BindMaterialResult.rejected_result(
                material_path=request.material_path,
                failed_prim_paths=request.selection_paths,
                message=message,
                error_code=CoreMaterialErrorCode.UNSUPPORTED,
                warnings=(_core_material_warning(CoreMaterialErrorCode.UNSUPPORTED, message),),
            )
        if self._stage is None:
            message = "No active OpenUSD stage is available."
            return BindMaterialResult.rejected_result(
                material_path=request.material_path,
                failed_prim_paths=request.selection_paths,
                message=message,
                error_code=CoreMaterialErrorCode.NO_ACTIVE_STAGE,
                warnings=(_core_material_warning(CoreMaterialErrorCode.NO_ACTIVE_STAGE, message),),
            )
        if UsdShade is None:
            message = "UsdShade material schemas are not available in this OpenUSD build."
            return BindMaterialResult.rejected_result(
                material_path=request.material_path,
                failed_prim_paths=request.selection_paths,
                message=message,
                error_code=CoreMaterialErrorCode.UNSUPPORTED,
                warnings=(_core_material_warning(CoreMaterialErrorCode.UNSUPPORTED, message),),
            )

        material_path = _create_action_path(request.material_path)
        if material_path is None or material_path == Sdf.Path.absoluteRootPath:
            return BindMaterialResult.rejected_result(
                material_path=request.material_path,
                failed_prim_paths=request.selection_paths,
                message=f"Material path is invalid: {request.material_path}",
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
                warnings=(
                    CoreMaterialWarning(
                        code=CoreMaterialErrorCode.VALIDATION_FAILED.value,
                        message=f"Material path is invalid: {request.material_path}",
                        severity=CoreMaterialWarningSeverity.ERROR,
                    ),
                ),
            )
        material_prim = self._stage.GetPrimAtPath(material_path)
        if not material_prim or not material_prim.IsValid() or not material_prim.IsA(UsdShade.Material):
            message = f"Material does not exist or is not a UsdShade material: {request.material_path}"
            return BindMaterialResult.rejected_result(
                material_path=request.material_path,
                failed_prim_paths=request.selection_paths,
                message=message,
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
                warnings=(
                    CoreMaterialWarning(
                        code=CoreMaterialErrorCode.VALIDATION_FAILED.value,
                        message=message,
                        severity=CoreMaterialWarningSeverity.ERROR,
                    ),
                ),
            )
        if not request.selection_paths:
            message = "Select at least one prim before binding a material."
            return BindMaterialResult.rejected_result(
                material_path=str(material_path),
                message=message,
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
                warnings=(
                    CoreMaterialWarning(
                        code=CoreMaterialErrorCode.VALIDATION_FAILED.value,
                        message=message,
                        severity=CoreMaterialWarningSeverity.ERROR,
                    ),
                ),
            )
        edit_target_layer, edit_target_reason = _create_edit_target_layer(self._stage)
        if edit_target_reason or edit_target_layer is None:
            message = edit_target_reason or "No current edit target is available."
            return BindMaterialResult.rejected_result(
                material_path=str(material_path),
                failed_prim_paths=request.selection_paths,
                message=message,
                error_code=CoreMaterialErrorCode.DISABLED,
                warnings=(_core_material_warning(CoreMaterialErrorCode.DISABLED, message),),
            )

        binding_strength, strength_error = _core_material_binding_strength_token(
            request.binding_strength
        )
        if strength_error or binding_strength is None:
            return BindMaterialResult.rejected_result(
                material_path=str(material_path),
                failed_prim_paths=request.selection_paths,
                message=strength_error,
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
                warnings=(
                    CoreMaterialWarning(
                        code=CoreMaterialErrorCode.VALIDATION_FAILED.value,
                        message=strength_error,
                        severity=CoreMaterialWarningSeverity.ERROR,
                    ),
                ),
            )

        targets, skipped_paths, warnings = _core_material_binding_targets(
            self._stage,
            request.selection_paths,
        )
        if not targets:
            message = "No valid selected prim is available for material binding."
            return BindMaterialResult.rejected_result(
                material_path=str(material_path),
                skipped_prim_paths=skipped_paths,
                message=message,
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
                warnings=(
                    CoreMaterialWarning(
                        code=CoreMaterialErrorCode.VALIDATION_FAILED.value,
                        message=message,
                        severity=CoreMaterialWarningSeverity.ERROR,
                    ),
                    *warnings,
                ),
            )

        snapshot = _create_snapshot_layer(edit_target_layer)
        try:
            bound_paths = self._bind_core_material_to_targets(
                material_prim,
                targets,
                binding_strength,
            )
        except Exception as exc:
            _create_restore_layer(edit_target_layer, snapshot)
            message = f"Core material bind failed: {exc}"
            failed_paths = tuple(str(prim.GetPath()) for prim in targets)
            return BindMaterialResult.rejected_result(
                material_path=str(material_path),
                skipped_prim_paths=skipped_paths,
                failed_prim_paths=failed_paths,
                message=message,
                error_code=CoreMaterialErrorCode.BIND_FAILED,
                warnings=(
                    CoreMaterialWarning(
                        code=CoreMaterialErrorCode.BIND_FAILED.value,
                        message=message,
                        severity=CoreMaterialWarningSeverity.ERROR,
                    ),
                    *warnings,
                ),
            )

        self._notify(ChangeEvent(
            changed_paths=tuple(bound_paths),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        ))
        return BindMaterialResult.accepted_result(
            material_path=str(material_path),
            bound_prim_paths=bound_paths,
            skipped_prim_paths=skipped_paths,
            selection_paths=bound_paths,
            message=f"Bound material {material_path} to {len(bound_paths)} prim(s).",
            warnings=warnings,
        )

    def create_and_bind_material(
        self,
        request: CreateMaterialRequest,
    ) -> CreateAndBindMaterialResult:
        """Atomically create a material and bind it to selected prims."""
        catalog = self.list_core_materials(selection_paths=request.selection_paths)
        if catalog.is_empty:
            if catalog.warnings:
                warning = catalog.warnings[0]
                error_code = CoreMaterialErrorCode.CREATE_FAILED
                try:
                    error_code = CoreMaterialErrorCode(warning.code)
                except ValueError:
                    pass
                return CreateAndBindMaterialResult.rejected_result(
                    message=warning.message,
                    error_code=error_code,
                    warnings=(warning,),
                )
            return CreateAndBindMaterialResult.rejected_result(
                message="No core materials are available.",
                error_code=CoreMaterialErrorCode.UNSUPPORTED,
                warnings=(
                    _core_material_warning(
                        CoreMaterialErrorCode.UNSUPPORTED,
                        "No core materials are available.",
                    ),
                ),
            )

        material = catalog.material(request.material_id)
        if material is None:
            message = f"Unknown core material: {request.material_id}"
            return CreateAndBindMaterialResult.rejected_result(
                message=message,
                error_code=CoreMaterialErrorCode.UNSUPPORTED,
                warnings=(_core_material_warning(CoreMaterialErrorCode.UNSUPPORTED, message),),
            )
        if not material.is_available or not material.create_supported:
            message = material.disabled_reason or f"Core material is disabled: {request.material_id}"
            return CreateAndBindMaterialResult.rejected_result(
                message=message,
                error_code=CoreMaterialErrorCode.DISABLED,
                warnings=(_core_material_warning(CoreMaterialErrorCode.DISABLED, message),),
            )

        edit_target_layer, edit_target_reason = _create_edit_target_layer(self._stage)
        if edit_target_reason or edit_target_layer is None:
            message = edit_target_reason or "No current edit target is available."
            return CreateAndBindMaterialResult.rejected_result(
                failed_prim_paths=request.selection_paths,
                message=message,
                error_code=CoreMaterialErrorCode.DISABLED,
                warnings=(_core_material_warning(CoreMaterialErrorCode.DISABLED, message),),
            )
        if UsdShade is None:
            message = "UsdShade material schemas are not available in this OpenUSD build."
            return CreateAndBindMaterialResult.rejected_result(
                failed_prim_paths=request.selection_paths,
                message=message,
                error_code=CoreMaterialErrorCode.UNSUPPORTED,
                warnings=(_core_material_warning(CoreMaterialErrorCode.UNSUPPORTED, message),),
            )
        if not request.selection_paths:
            message = "Select at least one prim before binding a material."
            return CreateAndBindMaterialResult.rejected_result(
                message=message,
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
                warnings=(
                    CoreMaterialWarning(
                        code=CoreMaterialErrorCode.VALIDATION_FAILED.value,
                        message=message,
                        severity=CoreMaterialWarningSeverity.ERROR,
                    ),
                ),
            )

        scope_path, scope_error, create_missing_scope = _core_material_resolve_scope_path(
            self._stage,
            material,
            request,
        )
        if scope_error or scope_path is None:
            return CreateAndBindMaterialResult.rejected_result(
                failed_prim_paths=request.selection_paths,
                message=scope_error,
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
                warnings=(
                    CoreMaterialWarning(
                        code=CoreMaterialErrorCode.VALIDATION_FAILED.value,
                        message=scope_error,
                        severity=CoreMaterialWarningSeverity.ERROR,
                    ),
                ),
            )

        binding_strength, strength_error = _core_material_binding_strength_token(
            request.options.get("binding_strength", "")
        )
        if strength_error or binding_strength is None:
            return CreateAndBindMaterialResult.rejected_result(
                failed_prim_paths=request.selection_paths,
                message=strength_error,
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
                warnings=(
                    CoreMaterialWarning(
                        code=CoreMaterialErrorCode.VALIDATION_FAILED.value,
                        message=strength_error,
                        severity=CoreMaterialWarningSeverity.ERROR,
                    ),
                ),
            )

        targets, skipped_paths, binding_warnings = _core_material_binding_targets(
            self._stage,
            request.selection_paths,
        )
        if not targets:
            message = "No valid selected prim is available for material binding."
            return CreateAndBindMaterialResult.rejected_result(
                skipped_prim_paths=skipped_paths,
                message=message,
                error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
                warnings=(
                    CoreMaterialWarning(
                        code=CoreMaterialErrorCode.VALIDATION_FAILED.value,
                        message=message,
                        severity=CoreMaterialWarningSeverity.ERROR,
                    ),
                    *binding_warnings,
                ),
            )

        child_name = _create_child_name(request.requested_name, material.default_name)
        material_path = _create_unique_child_path(self._stage, scope_path, child_name)
        snapshot = _create_snapshot_layer(edit_target_layer)
        failure_code = CoreMaterialErrorCode.CREATE_FAILED
        try:
            _, scope_error = _create_ensure_parent(
                self._stage,
                scope_path,
                create_missing=create_missing_scope,
            )
            if scope_error:
                raise ValueError(scope_error)
            prim, created_paths, create_warnings = self._define_core_material(
                material,
                material_path,
            )
            if prim is None or not prim.IsValid():
                raise RuntimeError(f"Core material create did not author {material_path}")
            failure_code = CoreMaterialErrorCode.BIND_FAILED
            bound_paths = self._bind_core_material_to_targets(
                prim,
                targets,
                binding_strength,
            )
        except Exception as exc:
            _create_restore_layer(edit_target_layer, snapshot)
            message = f"Core material create-and-bind failed: {exc}"
            failed_paths = (
                tuple(str(prim.GetPath()) for prim in targets)
                if failure_code is CoreMaterialErrorCode.BIND_FAILED
                else ()
            )
            return CreateAndBindMaterialResult.rejected_result(
                skipped_prim_paths=skipped_paths,
                failed_prim_paths=failed_paths,
                message=message,
                error_code=failure_code,
                warnings=(
                    CoreMaterialWarning(
                        code=failure_code.value,
                        message=message,
                        severity=CoreMaterialWarningSeverity.ERROR,
                    ),
                    *binding_warnings,
                ),
            )

        primary_path = str(prim.GetPath())
        self._notify(ChangeEvent(
            changed_paths=tuple(bound_paths),
            resynced_paths=tuple(created_paths),
            event_type=ChangeEventType.RESYNC,
        ))
        return CreateAndBindMaterialResult.accepted_result(
            created_material_path=primary_path,
            created_paths=created_paths,
            bound_prim_paths=bound_paths,
            skipped_prim_paths=skipped_paths,
            selection_paths=(primary_path,),
            focus_path=primary_path,
            binding_applied=bool(bound_paths),
            message=f"Created material {primary_path} and bound {len(bound_paths)} prim(s).",
            warnings=(*binding_warnings, *create_warnings),
        )

    def _bind_core_material_to_targets(
        self,
        material_prim: Any,
        targets: tuple[Any, ...],
        binding_strength: Any,
    ) -> tuple[str, ...]:
        material = UsdShade.Material(material_prim)
        bound_paths: list[str] = []
        for prim in targets:
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(
                material,
                bindingStrength=binding_strength,
            )
            bound_paths.append(str(prim.GetPath()))
        return tuple(bound_paths)

    def list_create_actions(
        self,
        *,
        selection_paths: Iterable[str] | None = None,
    ) -> CreateActionCatalog:
        """Return adapter-backed prim creation actions for the current USD context."""
        selection_tuple = tuple(str(path) for path in (selection_paths or ()))
        if not HAS_USD:
            return CreateActionCatalog(
                selection_paths=selection_tuple,
                warnings=(
                    CreateActionWarning(
                        code=CreateActionErrorCode.UNSUPPORTED.value,
                        message="OpenUSD create actions are not available.",
                        severity=CreateActionWarningSeverity.ERROR,
                    ),
                ),
            )
        if self._stage is None:
            return CreateActionCatalog(
                selection_paths=selection_tuple,
                warnings=(
                    CreateActionWarning(
                        code=CreateActionErrorCode.NO_ACTIVE_STAGE.value,
                        message="No active OpenUSD stage is available.",
                        severity=CreateActionWarningSeverity.ERROR,
                    ),
                ),
            )

        stage_id = _create_stage_identifier(self._stage)
        edit_target_layer, edit_target_reason = _create_edit_target_layer(self._stage)
        edit_target_id = ""
        if edit_target_layer is not None:
            edit_target_id = str(getattr(edit_target_layer, "identifier", "") or "")

        actions: list[CreateActionDescriptor] = []
        for spec in _CREATE_ACTION_SPECS:
            disabled_reason = _create_disabled_reason(
                spec,
                edit_target_reason=edit_target_reason,
                selection_paths=selection_tuple,
            )
            requirements = spec.requirements
            if spec.unsupported_reason and CreateActionRequirement.UNSUPPORTED not in requirements:
                requirements = (*requirements, CreateActionRequirement.UNSUPPORTED)
            actions.append(
                CreateActionDescriptor(
                    action_id=spec.action_id,
                    label=spec.label,
                    category_id=spec.category,
                    target_prim_type=spec.target_prim_type,
                    prim_kind=spec.prim_kind,
                    description=spec.description,
                    icon_key=_ICON_MAP.get(spec.target_prim_type.lower(), ""),
                    order=spec.order,
                    capabilities=spec.capabilities,
                    requirements=requirements,
                    placement_policy=spec.placement_policy,
                    selection_policy=spec.selection_policy,
                    binding_policy=spec.binding_policy,
                    default_parent_path=spec.default_parent_path,
                    default_name=spec.default_name,
                    enabled=not disabled_reason,
                    disabled_reason=disabled_reason,
                    metadata={
                        "schema_family": spec.schema_family,
                    },
                )
            )

        actions_tuple = tuple(
            sorted(
                actions,
                key=lambda action: (
                    action.category_order,
                    action.order,
                    action.action_id,
                ),
            )
        )
        return CreateActionCatalog(
            categories=_create_category_descriptors(actions_tuple),
            actions=actions_tuple,
            active_stage_id=stage_id,
            edit_target_id=edit_target_id,
            selection_paths=selection_tuple,
        )

    def create_prim(self, request: CreateRequest) -> CreateResult:
        """Execute an adapter-backed create action against the current edit target."""
        catalog = self.list_create_actions(selection_paths=request.selection_paths)
        if catalog.is_empty:
            if catalog.warnings:
                warning = catalog.warnings[0]
                error_code = CreateActionErrorCode.CREATE_FAILED
                try:
                    error_code = CreateActionErrorCode(warning.code)
                except ValueError:
                    pass
                return _create_action_error(warning.message, error_code)
            return _create_action_error(
                "No create actions are available.",
                CreateActionErrorCode.UNSUPPORTED,
            )

        action = catalog.action(request.action_id)
        if action is None:
            return _create_action_error(
                f"Unknown create action: {request.action_id}",
                CreateActionErrorCode.UNSUPPORTED,
            )
        if not action.is_available:
            return _create_action_error(
                action.disabled_reason or f"Create action is disabled: {request.action_id}",
                CreateActionErrorCode.DISABLED,
            )

        edit_target_layer, edit_target_reason = _create_edit_target_layer(self._stage)
        if edit_target_reason or edit_target_layer is None:
            return _create_action_error(
                edit_target_reason or "No current edit target is available.",
                CreateActionErrorCode.DISABLED,
            )

        parent_path, parent_error, create_missing_parent = _create_resolve_parent_path(
            self._stage,
            action,
            request,
        )
        if parent_error or parent_path is None:
            return _create_action_error(parent_error, CreateActionErrorCode.VALIDATION_FAILED)

        child_name = _create_child_name(request.requested_name, action.default_name)
        target_path = _create_unique_child_path(self._stage, parent_path, child_name)
        binding_targets, binding_warnings, binding_error = self._create_binding_targets(
            action,
            request.selection_paths,
        )
        if binding_error:
            return CreateResult.rejected_result(
                message=binding_error,
                error_code=CreateActionErrorCode.VALIDATION_FAILED,
                warnings=(
                    _create_warning_result(
                        CreateActionErrorCode.VALIDATION_FAILED.value,
                        binding_error,
                        CreateActionWarningSeverity.ERROR,
                    ),
                    *binding_warnings,
                ),
            )

        snapshot = _create_snapshot_layer(edit_target_layer)
        try:
            _, parent_error = _create_ensure_parent(
                self._stage,
                parent_path,
                create_missing=create_missing_parent,
            )
            if parent_error:
                raise ValueError(parent_error)
            prim, created_paths, author_warnings, binding_applied = self._define_create_action_prim(
                action,
                target_path,
                binding_targets=binding_targets,
                selection_paths=request.selection_paths,
            )
            if prim is None or not prim.IsValid():
                raise RuntimeError(f"Create action did not author {target_path}")
        except Exception as exc:
            _create_restore_layer(edit_target_layer, snapshot)
            message = f"Create action failed: {exc}"
            return _create_action_error(message, CreateActionErrorCode.CREATE_FAILED)

        warnings = (*binding_warnings, *author_warnings)
        primary_path = str(prim.GetPath())
        selection_paths = self._create_result_selection_paths(action, primary_path, request)
        self._notify(ChangeEvent(
            changed_paths=(),
            resynced_paths=tuple(created_paths),
            event_type=ChangeEventType.RESYNC,
        ))
        return CreateResult.accepted_result(
            created_paths=created_paths,
            primary_path=primary_path,
            selection_paths=selection_paths,
            focus_path=primary_path,
            binding_applied=binding_applied,
            message=f"Created {primary_path}.",
            warnings=warnings,
        )

    def _create_binding_targets(
        self,
        action: CreateActionDescriptor,
        selection_paths: tuple[str, ...],
    ) -> tuple[tuple[Any, ...], tuple[CreateActionWarning, ...], str]:
        if action.binding_policy is not CreateBindingPolicy.BIND_TO_SELECTION:
            return (), (), ""

        warnings: list[CreateActionWarning] = []
        targets: list[Any] = []
        for selection_path in selection_paths:
            sdf_path = _create_action_path(selection_path)
            prim = self._stage.GetPrimAtPath(sdf_path) if sdf_path is not None else None
            if prim and prim.IsValid() and sdf_path != Sdf.Path.absoluteRootPath:
                targets.append(prim)
                continue
            warnings.append(
                _create_warning_result(
                    "invalid_selection_path",
                    f"Selection target is not bindable and was skipped: {selection_path}",
                )
            )
        if not targets:
            return (), tuple(warnings), "No valid selected prim is available for binding."
        return tuple(targets), tuple(warnings), ""

    def _define_create_action_prim(
        self,
        action: CreateActionDescriptor,
        target_path: Any,
        *,
        binding_targets: tuple[Any, ...] = (),
        selection_paths: tuple[str, ...] = (),
    ) -> tuple[Any, tuple[str, ...], tuple[CreateActionWarning, ...], bool]:
        target_type = action.target_prim_type
        if action.prim_kind == "mesh":
            return self._define_create_mesh_prim(action, target_path)

        if action.prim_kind == "shape":
            from ovui_data_adapters.openusd import create_prims

            define = getattr(UsdGeom, target_type).Define
            prim = define(self._stage, target_path).GetPrim()
            create_prims.apply_geometry_standard_prim_attrs(
                self._stage,
                prim,
                _create_action_default_name(action),
            )
            return prim, (str(target_path),), (), False

        if action.prim_kind == "light":
            if UsdLux is None:
                raise RuntimeError("UsdLux is unavailable.")
            from ovui_data_adapters.openusd import create_prims

            define = getattr(UsdLux, target_type).Define
            prim = define(self._stage, target_path).GetPrim()
            create_prims.apply_light_standard_prim_attrs(
                self._stage,
                prim,
                target_type,
            )
            return prim, (str(target_path),), (), False

        if action.prim_kind == "camera":
            from ovui_data_adapters.openusd import create_prims

            prim = UsdGeom.Camera.Define(self._stage, target_path).GetPrim()
            create_prims.apply_camera_standard_prim_attrs(self._stage, prim)
            return prim, (str(target_path),), (), False

        if action.prim_kind == "sensor":
            return self._define_generic_lidar_sensor(target_path, selection_paths)

        if action.prim_kind == "render_product":
            return self._define_render_product(target_path, selection_paths)

        if action.prim_kind == "scope":
            prim = UsdGeom.Scope.Define(self._stage, target_path).GetPrim()
            return prim, (str(target_path),), (), False

        if action.prim_kind == "xform":
            from ovui_data_adapters.openusd import create_prims

            prim = UsdGeom.Xform.Define(self._stage, target_path).GetPrim()
            create_prims.apply_default_xform_ops(prim)
            return prim, (str(target_path),), (), False

        if action.prim_kind == "material":
            return self._define_usd_preview_surface_material(target_path, binding_targets)

        raise ValueError(f"Unsupported create action kind: {action.prim_kind}")

    def _define_create_mesh_prim(
        self,
        action: CreateActionDescriptor,
        target_path: Any,
    ) -> tuple[Any, tuple[str, ...], tuple[CreateActionWarning, ...], bool]:
        from pxr import Vt
        from ovui_data_adapters.openusd import create_prims

        mesh_name = _create_mesh_name(action)
        topology = create_prims.evaluate_mesh_topology(self._stage, mesh_name)
        if not topology.points or not topology.face_vertex_indices or not topology.face_vertex_counts:
            raise RuntimeError(f"Mesh primitive has no authored topology: {mesh_name}")

        mesh = UsdGeom.Mesh.Define(self._stage, target_path)
        prim = mesh.GetPrim()
        create_prims.apply_default_xform_ops(
            prim,
            translate_value=create_prims.mesh_above_ground_translate(self._stage, mesh_name),
        )

        mesh.GetPointsAttr().Set(Vt.Vec3fArray(topology.points))
        mesh.GetNormalsAttr().Set(Vt.Vec3fArray(topology.normals))
        mesh.GetFaceVertexIndicesAttr().Set(list(topology.face_vertex_indices))
        mesh.GetFaceVertexCountsAttr().Set(list(topology.face_vertex_counts))
        mesh.SetNormalsInterpolation(UsdGeom.Tokens.faceVarying)

        st_primvar = UsdGeom.PrimvarsAPI(prim).CreatePrimvar(
            "st",
            Sdf.ValueTypeNames.TexCoord2fArray,
        )
        st_primvar.SetInterpolation(UsdGeom.Tokens.faceVarying)
        st_primvar.Set(Vt.Vec2fArray(topology.st))
        mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
        create_prims.set_extent_from_plugins(prim)
        return prim, (str(target_path),), (), False

    def _define_render_product(
        self,
        target_path: Any,
        selection_paths: tuple[str, ...],
    ) -> tuple[Any, tuple[str, ...], tuple[CreateActionWarning, ...], bool]:
        if UsdRender is None:
            raise RuntimeError("UsdRender is unavailable.")
        from pxr import Gf

        source_path, source_kind = self._create_render_product_source(selection_paths)
        is_point_cloud = source_kind == "sensor"
        var_name = "PointCloud" if is_point_cloud else "LdrColor"
        var_path = Sdf.Path("/Render/Vars").AppendChild(var_name)
        _, parent_error = _create_ensure_parent(
            self._stage,
            var_path.GetParentPath(),
            create_missing=True,
        )
        if parent_error:
            raise ValueError(parent_error)

        var = UsdRender.Var.Define(self._stage, var_path)
        var.CreateSourceNameAttr().Set(var_name)
        if is_point_cloud:
            var.GetPrim().CreateAttribute(
                "channels",
                Sdf.ValueTypeNames.StringArray,
            ).Set(list(_POINT_CLOUD_RENDER_VAR_CHANNELS))

        product = UsdRender.Product.Define(self._stage, target_path)
        if source_path is not None:
            product.CreateCameraRel().SetTargets([source_path])
        product.CreateOrderedVarsRel().SetTargets([var_path])
        product.CreateResolutionAttr().Set(
            Gf.Vec2i(1, 1) if is_point_cloud else Gf.Vec2i(1280, 720)
        )

        created_paths = (
            str(var_path.GetParentPath().GetParentPath()),
            str(var_path.GetParentPath()),
            str(var_path),
            str(target_path.GetParentPath()),
            str(target_path),
        )
        warnings: tuple[CreateActionWarning, ...] = ()
        if source_path is None:
            warnings = (
                _create_warning_result(
                    "missing_source",
                    "RenderProduct was created without a source camera or sensor.",
                ),
            )
        return product.GetPrim(), tuple(dict.fromkeys(created_paths)), warnings, False

    def _create_render_product_source(
        self,
        selection_paths: tuple[str, ...],
    ) -> tuple[Any | None, str]:
        for selection_path in selection_paths:
            sdf_path = _create_action_path(selection_path)
            if sdf_path is None:
                continue
            prim = self._stage.GetPrimAtPath(sdf_path)
            source = self._create_render_product_source_from_prim(prim)
            if source[0] is not None:
                return source

        if UsdGeom is not None:
            for prim in self._stage.Traverse():
                if prim and prim.IsValid() and prim.IsA(UsdGeom.Camera):
                    return prim.GetPath(), "camera"
        return None, ""

    def _create_render_product_source_from_prim(self, prim: Any) -> tuple[Any | None, str]:
        if not prim or not prim.IsValid():
            return None, ""
        if UsdGeom is not None and prim.IsA(UsdGeom.Camera):
            return prim.GetPath(), "camera"
        if _create_is_sensor_source_prim(prim):
            return prim.GetPath(), "sensor"
        child = prim.GetChild("Sensor")
        if child and child.IsValid() and _create_is_sensor_source_prim(child):
            return child.GetPath(), "sensor"
        return None, ""

    def _define_generic_lidar_sensor(
        self,
        target_path: Any,
        selection_paths: tuple[str, ...] = (),
    ) -> tuple[Any, tuple[str, ...], tuple[CreateActionWarning, ...], bool]:
        from pxr import Gf

        parent = UsdGeom.Xform.Define(self._stage, target_path)
        parent_xform = UsdGeom.Xformable(parent.GetPrim())
        translate_value = (
            self._create_lidar_translate_for_selection(selection_paths)
            or Gf.Vec3d(0.0, 0.0, 1.0)
        )
        parent_xform.AddTranslateOp(UsdGeom.XformOp.PrecisionDouble).Set(
            translate_value
        )

        sensor_path = target_path.AppendChild("Sensor")
        sensor_prim = self._stage.DefinePrim(sensor_path, "OmniLidar")
        sensor_prim.SetMetadata(
            "apiSchemas",
            Sdf.TokenListOp.Create(prependedItems=["OmniSensorGenericLidarCoreAPI"]),
        )
        sensor_prim.CreateAttribute(
            "omni:sensor:Core:elementsCoordsType",
            Sdf.ValueTypeNames.Token,
        ).Set("CARTESIAN")
        sensor_prim.CreateAttribute(
            "omni:sensor:Core:outputFrameOfReference",
            Sdf.ValueTypeNames.Token,
        ).Set("WORLD")
        sensor_prim.CreateAttribute(
            "omni:sensor:frameRate",
            Sdf.ValueTypeNames.Double2,
        ).Set((10.0, 1.0))
        sensor_xform = UsdGeom.Xformable(sensor_prim)
        sensor_xform.AddRotateXYZOp(UsdGeom.XformOp.PrecisionFloat).Set(
            Gf.Vec3f(90.0, 0.0, -90.0)
        )
        return sensor_prim, (str(target_path), str(sensor_path)), (), False

    def _create_lidar_translate_for_selection(
        self,
        selection_paths: tuple[str, ...],
    ) -> Any | None:
        from pxr import Gf

        if not selection_paths:
            return None
        bbox_cache = UsdGeom.BBoxCache(
            Usd.TimeCode.Default(),
            ["default", "render", "proxy"],
            useExtentsHint=False,
        )
        selected_range: Any | None = None
        for selection_path in selection_paths:
            sdf_path = _create_action_path(selection_path)
            if sdf_path is None:
                continue
            prim = self._stage.GetPrimAtPath(sdf_path)
            if not prim or not prim.IsValid():
                continue
            try:
                aligned_range = bbox_cache.ComputeWorldBound(prim).ComputeAlignedRange()
            except Exception:
                continue
            if aligned_range.IsEmpty():
                continue
            minimum = aligned_range.GetMin()
            maximum = aligned_range.GetMax()
            values = (
                float(minimum[0]),
                float(minimum[1]),
                float(minimum[2]),
                float(maximum[0]),
                float(maximum[1]),
                float(maximum[2]),
            )
            if not all(math.isfinite(value) for value in values):
                continue
            if selected_range is None:
                selected_range = Gf.Range3d(minimum, maximum)
            else:
                selected_range.UnionWith(aligned_range)

        if selected_range is None or selected_range.IsEmpty():
            return None
        center = selected_range.GetMidpoint()
        minimum = selected_range.GetMin()
        size = selected_range.GetSize()
        max_extent = max(float(size[0]), float(size[1]), float(size[2]))
        try:
            meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(self._stage))
        except Exception:
            meters_per_unit = 1.0
        min_standoff = 1.0
        if math.isfinite(meters_per_unit) and meters_per_unit > 0.0:
            min_standoff = 1.0 / meters_per_unit
        standoff = max(max_extent, min_standoff)
        return Gf.Vec3d(center[0], minimum[1] - standoff, center[2])

    def _define_usd_preview_surface_material(
        self,
        material_path: Any,
        binding_targets: tuple[Any, ...],
    ) -> tuple[Any, tuple[str, ...], tuple[CreateActionWarning, ...], bool]:
        if UsdShade is None:
            raise RuntimeError("UsdShade is unavailable.")
        from pxr import Gf

        material = UsdShade.Material.Define(self._stage, material_path)
        shader_path = material_path.AppendChild("Shader")
        shader = UsdShade.Shader.Define(self._stage, shader_path)
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
            Gf.Vec3f(0.18, 0.18, 0.18)
        )
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.5)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        surface_output = shader.CreateOutput("surface", Sdf.ValueTypeNames.Token)
        material.CreateSurfaceOutput().ConnectToSource(surface_output)
        displacement_output = shader.CreateOutput("displacement", Sdf.ValueTypeNames.Token)
        material.CreateDisplacementOutput().ConnectToSource(displacement_output)
        for prim in binding_targets:
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
        return material.GetPrim(), (str(material_path), str(shader_path)), (), bool(binding_targets)

    @staticmethod
    def _create_result_selection_paths(
        action: CreateActionDescriptor,
        primary_path: str,
        request: CreateRequest,
    ) -> tuple[str, ...]:
        if action.selection_policy in (
            CreateSelectionPolicy.SELECT_CREATED,
            CreateSelectionPolicy.SELECT_PRIMARY,
        ):
            return (primary_path,)
        if action.selection_policy is CreateSelectionPolicy.PRESERVE_SELECTION:
            return tuple(request.selection_paths)
        return ()

    def list_render_products(self) -> List[StageChoice]:
        """Return selectable ``UsdRender.Product`` prims in stage traversal order."""
        if not HAS_USD or self._stage is None or UsdRender is None:
            return []
        return [
            _choice_for_prim(prim)
            for prim in self._stage.Traverse()
            if prim.IsValid() and prim.IsA(UsdRender.Product)
        ]

    def get_render_target_catalog(self) -> RenderTargetCatalog:
        """Return rich ``UsdRender.Product`` metadata in stage traversal order."""
        if not HAS_USD or self._stage is None or UsdRender is None:
            return RenderTargetCatalog()
        return RenderTargetCatalog(
            targets=tuple(
                _render_target_descriptor(self._stage, prim)
                for prim in self._stage.Traverse()
                if prim.IsValid() and prim.IsA(UsdRender.Product)
            )
        )
