# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Behavioral coverage for ovstage adapter capability advertisements."""

from __future__ import annotations

import pytest

from ovui_data_adapters.ovstage.layer_stack_adapter import OvstageLayerStackAdapter
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.provider import OvstageProviderSession


def test_ovstage_stage_capabilities_advertise_exact_native_authoring() -> None:
    session = OvstageProviderSession(runtime=object())
    stage_capabilities = session.get_capabilities().stage

    # Only actions the native OVStage runtime can truthfully perform are
    # advertised; durable document creation and export are unsupported with
    # explicit reasons instead of an OpenUSD bridge fallback.
    assert stage_capabilities.supported_actions() == (
        "create_prims",
        "delete_prims",
    )
    assert not stage_capabilities.create_stage.is_supported
    assert not stage_capabilities.export_stage.is_supported
    assert stage_capabilities.create_prims.is_supported
    assert stage_capabilities.delete_prims.is_supported
    assert session.can_export_stage() is False
    assert session.can_create_prims() is True
    assert session.can_delete_prims() is True

    # Supported authoring still requires a live OVStage scene; the no-scene
    # path must fail closed.
    with pytest.raises(NotImplementedError, match="native prim deletion command"):
        session.make_delete_prim_command(object(), "/World")
    with pytest.raises(RuntimeError, match="no active OVStage scene"):
        session.create_xform(object())


def test_ovstage_property_capabilities_match_missing_clear_behavior() -> None:
    adapter = OvstagePropertyAdapter(scene=None, paths=[])
    property_capabilities = adapter.get_capabilities()

    assert property_capabilities.supported_actions() == ()
    with pytest.raises(NotImplementedError):
        adapter.clear_value("test:count")


def test_ovstage_layer_capabilities_match_inert_layer_stack_behavior(tmp_path) -> None:
    adapter = OvstageLayerStackAdapter()
    layer_capabilities = adapter.get_capabilities()

    assert layer_capabilities.supported_actions() == ()
    assert adapter.get_layer_stack_identifiers() == []
    assert adapter.get_edit_target_identifier() == ""
    assert adapter.save_layer("root.usda") is False
    assert adapter.save_layer_as("root.usda", str(tmp_path / "root.usda"), True) is None
    assert adapter.reload_layer("root.usda") is False

    for call in (
        lambda: adapter.get_root_layer(),
        lambda: adapter.set_edit_target("root.usda"),
        lambda: adapter.create_sublayer("root.usda", -1, ""),
        lambda: adapter.insert_sublayer("root.usda", -1, str(tmp_path / "child.usda")),
        lambda: adapter.remove_sublayer("root.usda", 0),
    ):
        with pytest.raises(NotImplementedError):
            call()
