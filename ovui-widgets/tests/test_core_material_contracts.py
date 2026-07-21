# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for backend-neutral core-material contracts."""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from ovui_data_adapters.common import (
    BindMaterialRequest,
    BindMaterialResult,
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
    CoreMaterialsAdapter,
    CreateAndBindMaterialResult,
    CreateMaterialRequest,
    CreateMaterialResult,
)
from ovui_data_adapters.common._subscription import SubscriptionProtocol


def test_core_material_contract_module_has_no_backend_or_ui_import_side_effects():
    code = """
import importlib
import sys

for name in ("pxr", "ovrtx", "numpy", "ovui_widgets", "omni.ui"):
    if name in sys.modules:
        raise SystemExit(f"{name} was preloaded before the contract import")

importlib.import_module("ovui_data_adapters.common.core_materials")

loaded = [
    name
    for name in ("pxr", "ovrtx", "numpy", "ovui_widgets", "omni.ui")
    if name in sys.modules
]
if loaded:
    raise SystemExit("forbidden modules loaded: " + ", ".join(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_group_and_material_descriptors_are_frozen_and_coerced():
    warning = CoreMaterialWarning(
        code=CoreMaterialErrorCode.DISABLED,
        message="Material schema is unavailable.",
        severity="error",
        metadata={"schema": "UsdShade"},
    )
    group = CoreMaterialGroupDescriptor(
        group_id="usd_preview",
        order=20,
        collapsed_by_default=1,
        warnings=[warning],
        metadata={"source": "adapter"},
    )
    material = CoreMaterialDescriptor(
        material_id="usd_preview_surface",
        group_id=group.group_id,
        submenu_path="USD Preview",
        family="usd",
        kind="usd_preview_surface",
        shader_type="UsdPreviewSurface",
        swatch=[0.2, 0.4, 0.8, 1.0],
        capabilities="usdshade.preview_surface",
        requirements=["active_stage", CoreMaterialRequirement.WRITABLE_EDIT_TARGET],
        default_scope_path="/World/Looks",
        default_name="PreviewSurface",
        binding_policy="optional_bind_to_selection",
        bind_supported=True,
        warnings=[warning],
        metadata={"schema": "UsdShade"},
    )

    assert group.label == "Usd Preview"
    assert group.is_available
    assert group.warnings == (warning,)
    assert material.label == "Usd Preview Surface"
    assert material.submenu_path == ("USD Preview",)
    assert material.family is CoreMaterialFamily.USD
    assert material.kind is CoreMaterialKind.USD_PREVIEW_SURFACE
    assert material.swatch == (0.2, 0.4, 0.8, 1.0)
    assert material.capabilities == ("usdshade.preview_surface",)
    assert material.requirements == (
        CoreMaterialRequirement.ACTIVE_STAGE,
        CoreMaterialRequirement.WRITABLE_EDIT_TARGET,
    )
    assert material.binding_policy is CoreMaterialBindingPolicy.OPTIONAL_BIND_TO_SELECTION
    assert material.can_bind
    assert material.metadata["schema"] == "UsdShade"
    with pytest.raises(TypeError):
        material.metadata["schema"] = "Changed"
    with pytest.raises(TypeError):
        warning.metadata["schema"] = "Changed"
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        material.label = "Changed"


def test_catalog_groups_and_orders_materials_without_mutating_descriptors():
    late = CoreMaterialDescriptor(
        material_id="standard_surface",
        group_id="materialx",
        family=CoreMaterialFamily.MATERIALX,
        kind=CoreMaterialKind.STANDARD_SURFACE,
        order=20,
    )
    early = CoreMaterialDescriptor(
        material_id="openpbr",
        group_id="materialx",
        family=CoreMaterialFamily.MATERIALX,
        kind=CoreMaterialKind.OPENPBR,
        order=10,
    )
    disabled = CoreMaterialDescriptor(
        material_id="library_ref",
        group_id="library",
        family=CoreMaterialFamily.LIBRARY,
        kind=CoreMaterialKind.LIBRARY_REFERENCE,
        enabled=False,
        disabled_reason="Library path is not configured.",
    )
    catalog = CoreMaterialCatalog(
        groups=(
            CoreMaterialGroupDescriptor("materialx", order=10),
            CoreMaterialGroupDescriptor("library", order=20),
        ),
        materials=(late, disabled, early),
        active_stage_id="stage-a",
        edit_target_id="root.usda",
        selection_paths=["/World/Cube"],
        bindable_selection_paths=("/World/Cube",),
        revision=7,
        metadata={"source": "usd"},
    )

    assert not catalog.is_empty
    assert catalog.group("materialx").label == "Materialx"
    assert catalog.material("library_ref") is disabled
    assert catalog.materials_for_group("materialx") == (early, late)
    assert catalog.available_materials == (late, early)
    assert catalog.selection_paths == ("/World/Cube",)
    assert catalog.bindable_selection_paths == ("/World/Cube",)
    assert catalog.revision == "7"
    with pytest.raises(TypeError):
        catalog.metadata["source"] = "changed"


def test_omni_mdl_material_kind_ids_are_stable():
    assert CoreMaterialFamily.MDL.value == "mdl"
    assert CoreMaterialKind.OMNI_SURFACE.value == "omni_surface"
    assert CoreMaterialKind.OMNI_GLASS.value == "omni_glass"
    assert CoreMaterialKind.OMNI_PBR.value == "omni_pbr"


def test_create_and_bind_requests_and_accepted_results_capture_adapter_policy():
    create_request = CreateMaterialRequest(
        material_id="openpbr",
        requested_scope_path="/World/Looks",
        requested_name="OpenPBR",
        selection_paths="/World/Cube",
        bind_to_selection=True,
        options={"roughness": 0.4},
        correlation_id=42,
    )
    bind_request = BindMaterialRequest(
        material_path="/World/Looks/OpenPBR",
        selection_paths=["/World/Cube", "/World/Sphere"],
        binding_strength="strongerThanDescendants",
        options={"preview": True},
        correlation_id=43,
    )
    create_result = CreateMaterialResult.accepted_result(
        created_material_path="/World/Looks/OpenPBR",
        message="Created.",
    )
    bind_result = BindMaterialResult.accepted_result(
        material_path="/World/Looks/OpenPBR",
        bound_prim_paths=["/World/Cube"],
        skipped_prim_paths=["/World/Sphere"],
        selection_paths=["/World/Cube"],
    )
    combined_result = CreateAndBindMaterialResult.accepted_result(
        created_material_path="/World/Looks/OpenPBR",
        bound_prim_paths=["/World/Cube"],
        skipped_prim_paths=["/World/Sphere"],
        binding_applied=True,
    )

    assert create_request.selection_paths == ("/World/Cube",)
    assert create_request.options["roughness"] == 0.4
    assert create_request.correlation_id == "42"
    assert bind_request.selection_paths == ("/World/Cube", "/World/Sphere")
    assert bind_request.options["preview"] is True
    assert bind_request.correlation_id == "43"
    assert create_result.created_paths == ("/World/Looks/OpenPBR",)
    assert create_result.selection_paths == ("/World/Looks/OpenPBR",)
    assert bind_result.bound_prim_paths == ("/World/Cube",)
    assert bind_result.skipped_prim_paths == ("/World/Sphere",)
    assert bind_result.selection_paths == ("/World/Cube",)
    assert combined_result.created_paths == ("/World/Looks/OpenPBR",)
    assert combined_result.bound_prim_paths == ("/World/Cube",)
    assert combined_result.selection_paths == ("/World/Looks/OpenPBR",)
    assert combined_result.binding_applied


def test_rejected_results_use_stable_codes_and_cannot_report_mutation():
    warning = CoreMaterialWarning(
        code=CoreMaterialErrorCode.VALIDATION_FAILED,
        message="No writable edit target.",
        severity=CoreMaterialWarningSeverity.ERROR,
    )
    create_result = CreateMaterialResult.rejected_result(
        message="No writable edit target.",
        error_code=CoreMaterialErrorCode.VALIDATION_FAILED,
        warnings=[warning],
    )
    bind_result = BindMaterialResult.rejected_result(
        material_path="/World/Looks/OpenPBR",
        skipped_prim_paths=["/World/Scope"],
        failed_prim_paths=["/World/Cube"],
        message="Selection is not bindable.",
    )
    combined_result = CreateAndBindMaterialResult.rejected_result(
        failed_prim_paths=["/World/Cube"],
        message="Create-and-bind failed.",
        error_code=CoreMaterialErrorCode.BIND_FAILED,
    )

    assert not create_result.accepted
    assert create_result.error_code == "validation_failed"
    assert create_result.created_paths == ()
    assert create_result.selection_paths == ()
    assert bind_result.error_code == "bind_failed"
    assert bind_result.material_path == "/World/Looks/OpenPBR"
    assert bind_result.bound_prim_paths == ()
    assert bind_result.failed_prim_paths == ("/World/Cube",)
    assert combined_result.error_code == "bind_failed"
    assert combined_result.created_paths == ()
    assert combined_result.bound_prim_paths == ()
    assert combined_result.failed_prim_paths == ("/World/Cube",)
    with pytest.raises(ValueError, match="must not report mutations"):
        CreateMaterialResult(
            accepted=False,
            created_material_path="/World/Looks/OpenPBR",
            error_code=CoreMaterialErrorCode.CREATE_FAILED,
        )
    with pytest.raises(ValueError, match="must not report mutations"):
        BindMaterialResult(
            accepted=False,
            bound_prim_paths=("/World/Cube",),
            error_code=CoreMaterialErrorCode.BIND_FAILED,
        )
    with pytest.raises(ValueError, match="must not report mutations"):
        CreateAndBindMaterialResult(
            accepted=False,
            created_paths=("/World/Looks/OpenPBR",),
            error_code=CoreMaterialErrorCode.CREATE_FAILED,
        )
    with pytest.raises(ValueError, match="cannot carry an error_code"):
        CreateMaterialResult(
            accepted=True,
            created_material_path="/World/Looks/OpenPBR",
            error_code=CoreMaterialErrorCode.CREATE_FAILED,
        )


def test_default_adapter_returns_empty_catalog_unsupported_results_and_cancel_subscription():
    adapter = CoreMaterialsAdapter()
    catalog = adapter.list_core_materials(selection_paths=["/World/Cube"])
    create_result = adapter.create_material(CreateMaterialRequest(material_id="openpbr"))
    bind_result = adapter.bind_material(
        BindMaterialRequest(
            material_path="/World/Looks/OpenPBR",
            selection_paths=["/World/Cube"],
        )
    )
    combined_result = adapter.create_and_bind_material(
        CreateMaterialRequest(
            material_id="openpbr",
            selection_paths=["/World/Cube"],
            bind_to_selection=True,
        )
    )
    subscription = adapter.subscribe_core_materials_changes(lambda: None)

    assert catalog.is_empty
    assert catalog.selection_paths == ("/World/Cube",)
    assert not create_result.accepted
    assert create_result.error_code == "unsupported"
    assert create_result.created_paths == ()
    assert create_result.warnings[0].severity is CoreMaterialWarningSeverity.ERROR
    assert not bind_result.accepted
    assert bind_result.error_code == "unsupported"
    assert bind_result.material_path == "/World/Looks/OpenPBR"
    assert bind_result.bound_prim_paths == ()
    assert bind_result.failed_prim_paths == ("/World/Cube",)
    assert not combined_result.accepted
    assert combined_result.error_code == "unsupported"
    assert combined_result.created_paths == ()
    assert combined_result.bound_prim_paths == ()
    assert isinstance(subscription, SubscriptionProtocol)
    subscription.cancel()


def test_contract_validation_rejects_missing_ids_invalid_enums_and_bad_swatch():
    with pytest.raises(ValueError, match="group_id"):
        CoreMaterialGroupDescriptor(group_id="")
    with pytest.raises(ValueError, match="material_id"):
        CoreMaterialDescriptor(material_id="")
    with pytest.raises(ValueError, match="material_id"):
        CreateMaterialRequest(material_id="")
    with pytest.raises(ValueError, match="material_path"):
        BindMaterialRequest(material_path="")
    with pytest.raises(ValueError, match="code"):
        CoreMaterialWarning(code="", message="Missing code.")
    with pytest.raises(ValueError):
        CoreMaterialDescriptor(material_id="openpbr", family="not-a-family")
    with pytest.raises(ValueError):
        CoreMaterialDescriptor(material_id="openpbr", requirements=["not-a-requirement"])
    with pytest.raises(ValueError, match="swatch"):
        CoreMaterialDescriptor(material_id="openpbr", swatch=(1.0, 0.0, 0.0))


def test_stable_error_and_warning_codes_are_used_by_material_results():
    unavailable = CoreMaterialWarning(
        code=CoreMaterialErrorCode.NO_ACTIVE_STAGE,
        message="No active stage.",
        severity=CoreMaterialWarningSeverity.ERROR,
    )
    create_result = CreateMaterialResult.rejected_result(
        message="No active stage.",
        error_code=CoreMaterialErrorCode.NO_ACTIVE_STAGE,
        warnings=[unavailable],
    )
    bind_result = BindMaterialResult.rejected_result(message="Cannot bind.")
    combined_result = CreateAndBindMaterialResult.rejected_result(
        message="Cannot create.",
    )

    assert create_result.error_code == "no_active_stage"
    assert create_result.warnings[0].code == "no_active_stage"
    assert create_result.warnings[0].severity is CoreMaterialWarningSeverity.ERROR
    assert bind_result.error_code == "bind_failed"
    assert combined_result.error_code == "create_failed"
