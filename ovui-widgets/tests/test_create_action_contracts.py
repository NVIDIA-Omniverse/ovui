# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for backend-neutral create-action contracts."""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from ovui_data_adapters.common import (
    CREATE_ACTION_CATEGORY_ORDER,
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
)
from ovui_data_adapters.common._subscription import SubscriptionProtocol


def test_create_actions_contract_module_has_no_backend_or_ui_import_side_effects():
    code = """
import importlib
import sys

for name in ("pxr", "ovrtx", "numpy", "ovui_widgets", "omni.ui"):
    if name in sys.modules:
        raise SystemExit(f"{name} was preloaded before the contract import")

importlib.import_module("ovui_data_adapters.common.create_actions")

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


def test_category_order_is_stable_and_matches_srd_groups():
    expected = (
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
        "other",
    )

    assert tuple(category.value for category in CreateActionCategory.ordered()) == expected
    assert tuple(category.value for category in CREATE_ACTION_CATEGORY_ORDER) == expected
    assert CreateActionCategory.MESH.default_order < CreateActionCategory.SHAPE.default_order
    assert CreateActionCategory.TRANSFORMS.default_order < CreateActionCategory.MATERIALS.default_order
    assert CreateActionCategory.MATERIALS.default_order < CreateActionCategory.RENDER_PRODUCTS.default_order
    assert CreateActionCategory.LIGHTS.default_label == "Light"


def test_category_and_action_descriptors_are_frozen_and_coerced():
    warning = CreateActionWarning(
        code=CreateActionErrorCode.DISABLED,
        message="Needs a writable edit target.",
        severity="error",
        metadata={"reason": "muted-layer"},
    )
    category = CreateActionCategoryDescriptor(
        category_id=CreateActionCategory.LIGHTS,
        order=None,
        collapsed_by_default=1,
        warnings=[warning],
        metadata={"source": "adapter"},
    )
    action = CreateActionDescriptor(
        action_id="create.sphere-light",
        label="Sphere Light",
        category_id=CreateActionCategory.LIGHTS,
        target_prim_type="SphereLight",
        prim_kind="light",
        capabilities="usd.create.light",
        requirements=["active_stage", CreateActionRequirement.WRITABLE_EDIT_TARGET],
        placement_policy="selected_parent",
        selection_policy="select_primary",
        binding_policy="optional_bind_to_selection",
        default_parent_path="/World/Lights",
        default_name="SphereLight",
        option_schema={"radius": {"type": "float", "default": 1.0}},
        enabled=False,
        disabled_reason="Muted edit target.",
        warnings=[warning],
        metadata={"namespace": "UsdLux"},
    )

    assert category.category_id == "lights"
    assert category.label == "Light"
    assert category.order == CreateActionCategory.LIGHTS.default_order
    assert category.collapsed_by_default is True
    assert category.warnings == (warning,)
    assert category.metadata["source"] == "adapter"
    assert not action.is_available
    assert action.category_id == "lights"
    assert action.capabilities == ("usd.create.light",)
    assert action.requirements == (
        CreateActionRequirement.ACTIVE_STAGE,
        CreateActionRequirement.WRITABLE_EDIT_TARGET,
    )
    assert action.placement_policy is CreatePlacementPolicy.SELECTED_PARENT
    assert action.selection_policy is CreateSelectionPolicy.SELECT_PRIMARY
    assert action.binding_policy is CreateBindingPolicy.OPTIONAL_BIND_TO_SELECTION
    assert action.can_bind
    assert action.option_schema["radius"]["default"] == 1.0
    with pytest.raises(TypeError):
        action.option_schema["radius"] = {}
    with pytest.raises(TypeError):
        action.metadata["namespace"] = "Changed"
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        action.label = "Changed"


def test_catalog_groups_and_orders_actions_without_mutating_descriptors():
    light_late = CreateActionDescriptor(
        action_id="create.dome-light",
        category_id=CreateActionCategory.LIGHTS,
        order=20,
    )
    light_early = CreateActionDescriptor(
        action_id="create.sphere-light",
        category_id=CreateActionCategory.LIGHTS,
        order=10,
    )
    disabled_camera = CreateActionDescriptor(
        action_id="create.camera",
        category_id=CreateActionCategory.CAMERAS,
        enabled=False,
        disabled_reason="No active stage.",
    )
    catalog = CreateActionCatalog(
        categories=(
            CreateActionCategoryDescriptor(CreateActionCategory.LIGHTS),
            CreateActionCategoryDescriptor(CreateActionCategory.CAMERAS),
        ),
        actions=(light_late, disabled_camera, light_early),
        active_stage_id="stage-a",
        edit_target_id="root.usda",
        selection_paths=["/World/Cube"],
        revision=123,
        metadata={"source": "usd"},
    )

    assert not catalog.is_empty
    assert catalog.category(CreateActionCategory.LIGHTS).label == "Light"
    assert catalog.action("create.camera") is disabled_camera
    assert catalog.actions_for_category("lights") == (light_early, light_late)
    assert catalog.available_actions == (light_late, light_early)
    assert catalog.selection_paths == ("/World/Cube",)
    assert catalog.revision == "123"
    with pytest.raises(TypeError):
        catalog.metadata["source"] = "changed"


def test_request_and_accepted_result_capture_adapter_policy_without_authoring():
    request = CreateRequest(
        action_id="create.material",
        requested_parent_path="/World/Looks",
        requested_name="PreviewSurface",
        selection_paths="/World/Cube",
        placement_hint="material_library",
        options={"bind": True},
        correlation_id=42,
    )
    result = CreateResult.accepted_result(
        created_paths=["/World/Looks/PreviewSurface"],
        binding_applied=True,
        message="Created and bound.",
    )

    assert request.selection_paths == ("/World/Cube",)
    assert request.options["bind"] is True
    assert request.correlation_id == "42"
    assert result.accepted
    assert result.primary_path == "/World/Looks/PreviewSurface"
    assert result.selection_paths == ("/World/Looks/PreviewSurface",)
    assert result.focus_path == ""
    assert result.binding_applied
    assert result.error_code == ""


def test_rejected_result_uses_stable_codes_and_cannot_report_mutation():
    warning = CreateActionWarning(
        code=CreateActionErrorCode.VALIDATION_FAILED,
        message="Name is invalid.",
        severity=CreateActionWarningSeverity.ERROR,
    )
    result = CreateResult.rejected_result(
        message="Name is invalid.",
        error_code=CreateActionErrorCode.VALIDATION_FAILED,
        warnings=[warning],
    )

    assert not result.accepted
    assert result.error_code == "validation_failed"
    assert result.created_paths == ()
    assert result.selection_paths == ()
    assert result.warnings == (warning,)
    with pytest.raises(ValueError, match="must not report mutations"):
        CreateResult(
            accepted=False,
            created_paths=("/World/Cube",),
            error_code=CreateActionErrorCode.CREATE_FAILED,
        )
    with pytest.raises(ValueError, match="cannot carry an error_code"):
        CreateResult(
            accepted=True,
            created_paths=("/World/Cube",),
            error_code=CreateActionErrorCode.CREATE_FAILED,
        )


def test_default_adapter_returns_empty_catalog_and_unsupported_create_result():
    adapter = CreateActionsAdapter()
    catalog = adapter.list_create_actions(selection_paths=["/World/Cube"])
    result = adapter.create_prim(CreateRequest(action_id="create.cube"))
    subscription = adapter.subscribe_create_actions_changes(lambda: None)

    assert catalog.is_empty
    assert catalog.selection_paths == ("/World/Cube",)
    assert not result.accepted
    assert result.error_code == "unsupported"
    assert result.created_paths == ()
    assert result.warnings[0].severity is CreateActionWarningSeverity.ERROR
    assert isinstance(subscription, SubscriptionProtocol)
    subscription.cancel()


def test_contract_validation_rejects_missing_ids_and_invalid_enums():
    with pytest.raises(ValueError, match="category_id"):
        CreateActionCategoryDescriptor(category_id="")
    with pytest.raises(ValueError, match="action_id"):
        CreateActionDescriptor(action_id="")
    with pytest.raises(ValueError, match="action_id"):
        CreateRequest(action_id="")
    with pytest.raises(ValueError):
        CreateActionWarning(code="", message="Missing code.")
    with pytest.raises(ValueError):
        CreateActionDescriptor(action_id="create.cube", requirements=["not-a-requirement"])
