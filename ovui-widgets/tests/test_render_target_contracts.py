# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for backend-neutral render target contracts."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from ovui_data_adapters.common import (
    RenderTargetActivationResult,
    RenderTargetCatalog,
    RenderTargetDescriptor,
    RenderTargetKind,
    RenderTargetOutputKind,
    RenderTargetWarning,
    RenderTargetWarningSeverity,
)
import ovui_data_adapters.common.render_targets as render_targets


def test_render_target_contract_module_has_no_backend_or_ui_imports():
    source = Path(render_targets.__file__).read_text(encoding="utf-8")
    assert "pxr" not in source
    assert "ovrtx" not in source
    assert "ovui_widgets" not in source


def test_enum_values_are_stable_strings():
    assert RenderTargetKind.CAMERA.value == "camera"
    assert RenderTargetKind.SENSOR.value == "sensor"
    assert RenderTargetKind.RENDER_PRODUCT.value == "render_product"
    assert RenderTargetKind.UNKNOWN.value == "unknown"
    assert RenderTargetOutputKind.IMAGE.value == "image"
    assert RenderTargetOutputKind.POINT_CLOUD.value == "point_cloud"
    assert RenderTargetOutputKind.GENERIC_MODEL_OUTPUT.value == "generic_model_output"
    assert RenderTargetOutputKind.MULTI_OUTPUT.value == "multi_output"
    assert RenderTargetOutputKind.UNKNOWN.value == "unknown"
    assert RenderTargetWarningSeverity.WARNING.value == "warning"


def test_warning_is_frozen_and_coerces_string_severity():
    warning = RenderTargetWarning(
        code="unsupported_output",
        message="PointCloud display is unavailable.",
        severity="error",
    )

    assert warning.severity is RenderTargetWarningSeverity.ERROR
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        warning.message = "changed"


def test_descriptor_defaults_and_tuple_fields_are_safe():
    warning = RenderTargetWarning("missing_source", "Source prim is missing.")
    descriptor = RenderTargetDescriptor(
        render_product_path="/Render/Beauty",
        output_kind="image",
        output_names=["LdrColor"],
        capabilities=["image_render_target", "set_active_render_product"],
        warnings=[warning],
    )

    assert descriptor.target_id == "/Render/Beauty"
    assert descriptor.display_label == "/Render/Beauty"
    assert descriptor.kind is RenderTargetKind.UNKNOWN
    assert descriptor.output_kind is RenderTargetOutputKind.IMAGE
    assert descriptor.output_names == ("LdrColor",)
    assert descriptor.capabilities == (
        "image_render_target",
        "set_active_render_product",
    )
    assert descriptor.warnings == (warning,)
    assert descriptor.is_selectable


def test_descriptor_disabled_reason_makes_target_not_selectable():
    descriptor = RenderTargetDescriptor(
        target_id="lidar",
        render_product_path="/Render/Lidar",
        display_name="Lidar",
        kind=RenderTargetKind.SENSOR,
        output_kind=RenderTargetOutputKind.POINT_CLOUD,
        enabled=False,
        disabled_reason="PointCloud display is unavailable.",
    )

    assert not descriptor.is_selectable
    assert descriptor.display_label == "Lidar"


def test_descriptor_resolution_requires_width_and_height():
    with pytest.raises(ValueError, match="resolution"):
        RenderTargetDescriptor(
            render_product_path="/Render/Bad",
            resolution=(1280, 720, 1),
        )


def test_catalog_defaults_are_empty_and_immutable():
    catalog = RenderTargetCatalog()

    assert catalog.targets == ()
    assert catalog.is_empty
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        catalog.targets = ()


def test_catalog_coerces_target_sequence_to_tuple():
    descriptor = RenderTargetDescriptor(render_product_path="/Render/Beauty")
    catalog = RenderTargetCatalog(
        targets=[descriptor],
        active_target_id="beauty",
        active_render_product_path="/Render/Beauty",
        revision=42,
    )

    assert catalog.targets == (descriptor,)
    assert catalog.active_target_id == "beauty"
    assert catalog.active_render_product_path == "/Render/Beauty"
    assert catalog.revision == "42"
    assert not catalog.is_empty


def test_activation_result_constructors_are_predictable():
    accepted = RenderTargetActivationResult.accepted_result(
        active_target_id="beauty",
        active_render_product_path="/Render/Beauty",
        message="Activated.",
    )
    rejected = RenderTargetActivationResult.rejected_result(
        "Unsupported target.",
        warning_code="unsupported_output",
        active_target_id="old",
        active_render_product_path="/Render/Old",
    )

    assert accepted.accepted
    assert accepted.warning_code is None
    assert accepted.active_render_product_path == "/Render/Beauty"
    assert not rejected.accepted
    assert rejected.warning_code == "unsupported_output"
    assert rejected.active_target_id == "old"
