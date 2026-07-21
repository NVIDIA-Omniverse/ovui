# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Exact-wheel capability contract for the OVStage adapter."""

from __future__ import annotations

import sys

from ovui_data_adapters.ovstage.layer_stack_adapter import OvstageLayerStackAdapter
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.provider import OvstageProviderSession


_STAGE_UNSUPPORTED_REASONS = {
    "create_stage": (
        "the supplied OVStage 0.1 API can construct an in-memory stage but does "
        "not expose durable new-document creation; select the OpenUSD data adapter "
        "for durable document creation"
    ),
    "export_stage": (
        "the supplied OVStage 0.1 API does not expose stage export or serialization; "
        "select the OpenUSD data adapter for export"
    ),
}

_STAGE_SUPPORTED_REASONS = {
    "create_prims": (
        "the supplied OVStage 0.1 API supports native prim and attribute writes "
        "for representable prim kinds"
    ),
    "delete_prims": (
        "the supplied OVStage 0.1 API supports native prim deletion"
    ),
}

_LAYER_UNSUPPORTED_REASONS = {
    "layer_stack": (
        "the supplied OVStage 0.1 API does not expose layer-stack enumeration; "
        "select the OpenUSD data adapter for layer workflows"
    ),
    "edit_target_read": (
        "the supplied OVStage 0.1 API does not expose edit-target state; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    "edit_target_write": (
        "the supplied OVStage 0.1 API does not expose edit-target mutation; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    "save_layer": (
        "the supplied OVStage 0.1 API does not expose layer save; select the "
        "OpenUSD data adapter for layer persistence"
    ),
    "save_layer_as": (
        "the supplied OVStage 0.1 API does not expose layer save-as or serialization; "
        "select the OpenUSD data adapter for layer persistence"
    ),
    "create_sublayer": (
        "the supplied OVStage 0.1 API does not expose sublayer creation; select the "
        "OpenUSD data adapter for layer workflows"
    ),
    "insert_sublayer": (
        "the supplied OVStage 0.1 API does not expose sublayer insertion; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    "remove_sublayer": (
        "the supplied OVStage 0.1 API does not expose sublayer removal; select the "
        "OpenUSD data adapter for layer workflows"
    ),
    "reload_layer": (
        "the supplied OVStage 0.1 API does not expose layer reload; select the "
        "OpenUSD data adapter for layer workflows"
    ),
    "mute_layer": (
        "the supplied OVStage 0.1 API does not expose layer muting; select the "
        "OpenUSD data adapter for layer workflows"
    ),
    "lock_layer": (
        "the supplied OVStage 0.1 API does not expose layer lock state or mutation; "
        "select the OpenUSD data adapter for layer workflows"
    ),
    "move_sublayer": (
        "the supplied OVStage 0.1 API does not expose sublayer reordering; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    "replace_sublayer": (
        "the supplied OVStage 0.1 API does not expose sublayer replacement; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    "prim_spec_read": (
        "the supplied OVStage 0.1 API does not expose prim-spec or source-layer "
        "inspection; select the OpenUSD data adapter for composition inspection"
    ),
    "prim_spec_edit": (
        "the supplied OVStage 0.1 API does not expose prim-spec mutation; select "
        "the OpenUSD data adapter for composition authoring"
    ),
    "layer_snapshot": (
        "the supplied OVStage 0.1 API does not expose layer snapshots; select the "
        "OpenUSD data adapter for layer workflows"
    ),
    "layer_restore": (
        "the supplied OVStage 0.1 API does not expose layer restoration; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    "transfer_layer_content": (
        "the supplied OVStage 0.1 API does not expose layer-content transfer; select "
        "the OpenUSD data adapter for layer workflows"
    ),
}

_CLEAR_VALUE_REASON = (
    "the supplied OVStage 0.1 API does not expose the authored-opinion and "
    "default-value resolution required to clear a property value; select the "
    "OpenUSD data adapter to clear authored opinions"
)


def _loaded_pxr_modules() -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name in sys.modules
            if name == "pxr" or name.startswith("pxr.")
        )
    )


def test_provider_advertises_exact_wheel_stage_contract() -> None:
    capabilities = OvstageProviderSession(runtime=object()).get_capabilities().stage

    assert capabilities.supported_actions() == ("create_prims", "delete_prims")
    for name, reason in _STAGE_UNSUPPORTED_REASONS.items():
        capability = getattr(capabilities, name)
        assert capability.is_unsupported
        assert capability.reason == reason
    for name, reason in _STAGE_SUPPORTED_REASONS.items():
        capability = getattr(capabilities, name)
        assert capability.is_supported
        assert capability.reason == reason


def test_layer_contract_has_no_delegate_capability_path() -> None:
    assert not hasattr(OvstageLayerStackAdapter, "_make_usd_adapter")
    capabilities = OvstageLayerStackAdapter(scene=object()).get_capabilities()

    assert capabilities.supported_actions() == ()
    for name, reason in _LAYER_UNSUPPORTED_REASONS.items():
        capability = getattr(capabilities, name)
        assert capability.is_unsupported
        assert capability.reason == reason


def test_property_clear_contract_requires_authored_opinion_resolution() -> None:
    capabilities = OvstagePropertyAdapter(scene=None, paths=[]).get_capabilities()
    capability = capabilities.clear_values

    assert capability.is_unsupported
    assert capability.reason == _CLEAR_VALUE_REASON


def test_property_contract_has_no_delegate_capability_path() -> None:
    pxr_modules_before = _loaded_pxr_modules()
    assert not hasattr(OvstagePropertyAdapter, "_make_usd_adapter")
    capabilities = OvstagePropertyAdapter(
        scene=object(),
        paths=[],
    ).get_capabilities()

    capability = capabilities.clear_values
    assert capability.is_unsupported
    assert capability.reason == _CLEAR_VALUE_REASON
    assert _loaded_pxr_modules() == pxr_modules_before
