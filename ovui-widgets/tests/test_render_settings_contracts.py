# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for backend-neutral public Render Settings contracts."""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from ovui_data_adapters.common import (
    RenderSettingApplyResult,
    RenderSettingDescriptor,
    RenderSettingRequirement,
    RenderSettingResetResult,
    RenderSettingValidationResult,
    RenderSettingValueConstraints,
    RenderSettingValueState,
    RenderSettingValueType,
    RenderSettingVisibility,
    RenderSettingWarning,
    RenderSettingWarningSeverity,
    RenderSettingsAdapter,
    RenderSettingsCatalog,
    RenderSettingsGroupDescriptor,
    RenderSettingsProviderDescriptor,
)


def test_render_settings_contract_module_has_no_backend_or_ui_import_side_effects():
    code = """
import importlib
import sys

for name in ("pxr", "ovrtx", "numpy", "ovui_widgets", "omni.ui"):
    if name in sys.modules:
        raise SystemExit(f"{name} was preloaded before the contract import")

importlib.import_module("ovui_data_adapters.common.render_settings")

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


def test_enum_values_are_stable_public_strings():
    assert RenderSettingValueType.BOOL.value == "bool"
    assert RenderSettingValueType.FLOAT.value == "float"
    assert RenderSettingValueType.COLOR.value == "color"
    assert RenderSettingRequirement.NONE.value == "none"
    assert RenderSettingRequirement.WARMUP.value == "warmup"
    assert RenderSettingRequirement.RENDERER_RESTART.value == "renderer_restart"
    assert RenderSettingRequirement.APPLICATION_RESTART.value == "application_restart"
    assert RenderSettingRequirement.UNSUPPORTED.value == "unsupported"
    assert RenderSettingVisibility.PUBLIC.value == "public"
    assert RenderSettingVisibility.DEV_ONLY.value == "dev_only"
    assert RenderSettingWarningSeverity.ERROR.value == "error"


def test_provider_group_setting_descriptors_are_frozen_and_coerced():
    warning = RenderSettingWarning(
        code="requires_restart",
        message="Renderer restart required.",
        severity="info",
    )
    provider = RenderSettingsProviderDescriptor(
        provider_id="public-render-product",
        display_name="Public RenderProduct Settings",
        api_version=2,
        capabilities="author",
        visibility="dev_only",
        isolation_key="render-product",
        warnings=[warning],
        metadata={"owner": "ovui-render-settings"},
    )
    group = RenderSettingsGroupDescriptor(
        group_id="sampling",
        label="Sampling",
        provider_id=provider.provider_id,
        order="10",
        collapsed_default=1,
        metadata={"namespace": "omni:rtx:"},
    )
    constraints = RenderSettingValueConstraints(
        soft_range=(1, 64),
        hard_range=["1", "4096"],
        allowed_values=[1, 2, 4, 8],
        component_count="1",
        options={"step": 1},
    )
    state = RenderSettingValueState(
        current_value=16,
        default_value=4,
        has_default=1,
        authored=1,
        dirty=0,
        metadata={"source": "authored"},
    )
    setting = RenderSettingDescriptor(
        setting_id="omni:rtx:samples",
        label="Samples",
        provider_id=provider.provider_id,
        group_id=group.group_id,
        namespace="omni:rtx:",
        property_name="samples",
        value_type="int",
        constraints=constraints,
        units="samples",
        default_value=4,
        has_default=True,
        requirement="warmup",
        visibility="public",
        value_state=state,
        warnings=[warning],
        revision_token=42,
        metadata={"schema": "RenderProduct"},
    )

    assert provider.capabilities == ("author",)
    assert provider.visibility is RenderSettingVisibility.DEV_ONLY
    assert provider.dev_only
    assert provider.is_available
    assert provider.metadata["owner"] == "ovui-render-settings"
    assert group.order == 10.0
    assert group.collapsed_default is True
    assert constraints.hard_range == (1.0, 4096.0)
    assert constraints.allowed_values == (1, 2, 4, 8)
    assert constraints.component_count == 1
    assert state.has_default is True
    assert state.authored is True
    assert state.resettable
    assert setting.value_type is RenderSettingValueType.INT
    assert setting.requirement is RenderSettingRequirement.WARMUP
    assert setting.resettable
    assert setting.revision_token == "42"
    assert setting.is_available
    with pytest.raises(TypeError):
        provider.metadata["other"] = "value"
    with pytest.raises(TypeError):
        constraints.options["step"] = 2
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        setting.label = "Changed"


def test_descriptor_validation_rejects_missing_ids_and_bad_constraints():
    with pytest.raises(ValueError, match="provider_id"):
        RenderSettingsProviderDescriptor(provider_id="")
    with pytest.raises(ValueError, match="group_id"):
        RenderSettingsGroupDescriptor(group_id="")
    with pytest.raises(ValueError, match="setting_id"):
        RenderSettingDescriptor(setting_id="")
    with pytest.raises(ValueError, match="component_count"):
        RenderSettingValueConstraints(component_count=0)
    with pytest.raises(ValueError, match="range values"):
        RenderSettingValueConstraints(soft_range=(1,))
    with pytest.raises(ValueError, match="range max"):
        RenderSettingValueConstraints(hard_range=(10, 1))


def test_value_state_matches_property_window_reset_semantics():
    inherited = RenderSettingValueState(
        current_value=4,
        default_value=4,
        has_default=True,
        inherited=True,
    )
    authored = RenderSettingValueState(
        current_value=16,
        default_value=4,
        has_default=True,
        authored=True,
        dirty=True,
    )
    disabled = RenderSettingValueState(
        current_value=16,
        default_value=4,
        has_default=True,
        authored=True,
        disabled=True,
        disabled_reason="Locked by provider.",
    )

    assert not inherited.resettable
    assert authored.resettable
    assert authored.dirty
    assert not disabled.resettable
    assert disabled.disabled_reason == "Locked by provider."

    authored_setting = RenderSettingDescriptor(
        setting_id="samples",
        has_default=True,
        value_state=authored,
    )
    inherited_setting = RenderSettingDescriptor(
        setting_id="samples-default",
        has_default=True,
        value_state=inherited,
    )
    assert authored_setting.resettable
    assert not inherited_setting.resettable


def test_catalog_defaults_and_lookup_are_stable():
    empty = RenderSettingsCatalog(active_render_product_path="/Render/Product")

    assert empty.is_empty
    assert empty.providers == ()
    assert empty.groups == ()
    assert empty.settings == ()
    assert empty.active_render_product_path == "/Render/Product"
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        empty.settings = ()

    provider = RenderSettingsProviderDescriptor(provider_id="public")
    group = RenderSettingsGroupDescriptor(group_id="quality")
    setting = RenderSettingDescriptor(setting_id="samples", group_id="quality")
    warning = RenderSettingWarning("stale", "Catalog is stale.")
    catalog = RenderSettingsCatalog(
        active_render_product_path="/Render/Product",
        active_render_product_label="Render Product",
        providers=provider,
        groups=[group],
        settings=(setting,),
        revision=5,
        warnings=[warning],
    )

    assert not catalog.is_empty
    assert catalog.provider("public") == provider
    assert catalog.provider("missing") is None
    assert catalog.group("quality") == group
    assert catalog.group("missing") is None
    assert catalog.setting("samples") == setting
    assert catalog.setting("missing") is None
    assert catalog.revision == "5"
    assert catalog.warnings == (warning,)


def test_validation_apply_and_reset_result_semantics_are_stable():
    validation_default = RenderSettingValidationResult()
    apply_default = RenderSettingApplyResult()
    reset_default = RenderSettingResetResult()

    assert not validation_default.accepted
    assert not apply_default.accepted
    assert not reset_default.accepted

    accepted_validation = RenderSettingValidationResult.accepted_result(
        setting_id="samples",
        normalized_value=32,
        requirement="warmup",
        message="Accepted.",
    )
    accepted_apply = RenderSettingApplyResult.accepted_result(
        setting_id="samples",
        current_value=32,
        requirement=RenderSettingRequirement.RENDERER_RESTART,
    )
    accepted_reset = RenderSettingResetResult.accepted_result(
        setting_id="samples",
        reset_value=4,
    )
    rejected_validation = RenderSettingValidationResult.rejected_result(
        "Unsupported.",
        setting_id="samples",
        warning_code="unsupported",
    )
    rejected_apply = RenderSettingApplyResult.rejected_result(
        "Failed.",
        setting_id="samples",
    )
    rejected_reset = RenderSettingResetResult.rejected_result(
        "Cannot reset.",
        setting_id="samples",
    )

    assert accepted_validation.accepted
    assert accepted_validation.normalized_value == 32
    assert accepted_validation.requirement is RenderSettingRequirement.WARMUP
    assert accepted_apply.accepted
    assert accepted_apply.requirement is RenderSettingRequirement.RENDERER_RESTART
    assert accepted_reset.accepted
    assert accepted_reset.reset_value == 4
    assert rejected_validation.warning_code == "unsupported"
    assert rejected_apply.warning_code == "apply_failed"
    assert rejected_reset.warning_code == "reset_failed"


def test_render_settings_adapter_defaults_are_unsupported_and_noop():
    adapter = RenderSettingsAdapter()
    callback_called = False

    def _callback() -> None:
        nonlocal callback_called
        callback_called = True

    catalog = adapter.list_render_settings("/Render/Product")
    validation = adapter.validate_render_setting(
        "samples",
        32,
        render_product_path="/Render/Product",
    )
    apply = adapter.apply_render_setting(
        "samples",
        32,
        render_product_path="/Render/Product",
    )
    reset = adapter.reset_render_setting(
        "samples",
        render_product_path="/Render/Product",
    )
    subscription = adapter.subscribe_render_settings_changes(_callback)

    assert catalog.is_empty
    assert catalog.active_render_product_path == "/Render/Product"
    assert adapter.read_render_setting("samples") is None
    assert not validation.accepted
    assert validation.warning_code == "unsupported"
    assert not apply.accepted
    assert apply.warning_code == "unsupported"
    assert not reset.accepted
    assert reset.warning_code == "unsupported"
    subscription.cancel()
    assert not callback_called


def test_common_package_exports_render_settings_contracts():
    import ovui_data_adapters.common as common

    assert common.RenderSettingsAdapter is RenderSettingsAdapter
    assert "RenderSettingsAdapter" in common.__all__
    assert "RenderSettingsCatalog" in common.__all__
    assert "RenderSettingDescriptor" in common.__all__
    assert "RenderSettingApplyResult" in common.__all__
