# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for backend-neutral RenderVar output visualization contracts."""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from ovui_data_adapters.common import (
    RendererAdapter,
    RenderVarCategoricalSettings,
    RenderVarHdrSettings,
    RenderVarOutputCatalog,
    RenderVarOutputDescriptor,
    RenderVarOutputFrame,
    RenderVarOutputKind,
    RenderVarOutputRequest,
    RenderVarOutputRequestResult,
    RenderVarPresetKind,
    RenderVarProbeRequest,
    RenderVarProbeResult,
    RenderVarScalarRangeSettings,
    RenderVarToneMap,
    RenderVarVectorSettings,
    RenderVarVisualizationPreset,
    RenderVarWarning,
    RenderVarWarningSeverity,
)


class _ConcreteRenderer(RendererAdapter):
    def load_stage(self, stage):
        pass

    def render_frame(self, width, height, view_matrix, proj_matrix):
        return None

    def set_resolution(self, width, height):
        pass

    def pick(self, x, y, callback, query_name):
        callback(None, None)

    def cancel_pick(self, query_name):
        pass

    def pick_rect(self, x0, y0, x1, y1, callback):
        callback([])

    def set_selection_highlight(self, paths):
        pass

    def shutdown(self):
        pass


def test_render_var_contract_module_has_no_backend_or_ui_import_side_effects():
    code = """
import importlib
import sys

for name in ("pxr", "ovrtx", "numpy", "ovui_widgets", "omni.ui"):
    if name in sys.modules:
        raise SystemExit(f"{name} was preloaded before the contract import")

importlib.import_module("ovui_data_adapters.common.render_vars")

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
    assert RenderVarOutputKind.HDR_COLOR.value == "hdr_color"
    assert RenderVarOutputKind.SCALAR_DEPTH.value == "scalar_depth"
    assert RenderVarOutputKind.VECTOR_NORMAL.value == "vector_normal"
    assert RenderVarOutputKind.CATEGORICAL_MASK.value == "categorical_mask"
    assert RenderVarPresetKind.HDR_TONEMAP.value == "hdr_tonemap"
    assert RenderVarPresetKind.SCALAR_GRAYSCALE.value == "scalar_grayscale"
    assert RenderVarPresetKind.VECTOR_SIGNED.value == "vector_signed"
    assert RenderVarPresetKind.CATEGORICAL_PALETTE.value == "categorical_palette"
    assert RenderVarToneMap.ACES.value == "aces"
    assert RenderVarWarningSeverity.ERROR.value == "error"


def test_visualization_preset_settings_are_frozen_and_coerced():
    scalar = RenderVarScalarRangeSettings(
        min_value="0",
        max_value="10",
        auto_range=0,
        invert=1,
        ramp="magma",
    )
    hdr = RenderVarHdrSettings(exposure="1.5", tonemap="aces", gamma="2.4")
    vector = RenderVarVectorSettings(
        channel_indices=["0", "2"],
        signed_remap=0,
        normalize=1,
        component_labels=["X", "Z"],
    )
    categorical = RenderVarCategoricalSettings(
        palette={7: (0, 1, 0, 1)},
        labels={"7": "car"},
        unknown_color=(1, 0, 1, 0.5),
    )
    preset = RenderVarVisualizationPreset(
        kind="categorical_palette",
        categorical=categorical,
        scalar_range=scalar,
        hdr=hdr,
        vector=vector,
        options={"legend": True},
    )

    assert scalar.min_value == 0.0
    assert scalar.max_value == 10.0
    assert scalar.auto_range is False
    assert scalar.invert is True
    assert hdr.tonemap is RenderVarToneMap.ACES
    assert hdr.gamma == 2.4
    assert vector.channel_indices == (0, 2)
    assert vector.normalize is True
    assert categorical.palette[7] == (0.0, 1.0, 0.0, 1.0)
    assert categorical.labels[7] == "car"
    assert preset.kind is RenderVarPresetKind.CATEGORICAL_PALETTE
    assert preset.label == "categorical_palette"
    with pytest.raises(TypeError):
        preset.options["other"] = False
    with pytest.raises(TypeError):
        categorical.palette[9] = (1.0, 1.0, 1.0, 1.0)
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        preset.label = "Changed"


def test_visualization_settings_validate_ranges_and_shapes():
    with pytest.raises(ValueError, match="max_value"):
        RenderVarScalarRangeSettings(min_value=10, max_value=1)
    with pytest.raises(ValueError, match="gamma"):
        RenderVarHdrSettings(gamma=0)
    with pytest.raises(ValueError, match="channel_indices"):
        RenderVarVectorSettings(channel_indices=())
    with pytest.raises(ValueError, match="channel_indices"):
        RenderVarVectorSettings(channel_indices=(-1,))
    with pytest.raises(ValueError, match="RGBA"):
        RenderVarCategoricalSettings(palette={1: (1.0, 0.0, 0.0)})


def test_output_descriptor_coerces_metadata_and_supports_presets():
    warning = RenderVarWarning(
        code="range_estimated",
        message="Using auto range.",
        severity="info",
    )
    preset = RenderVarVisualizationPreset(
        kind=RenderVarPresetKind.SCALAR_GRAYSCALE,
        scalar_range=RenderVarScalarRangeSettings(min_value=0, max_value=100),
    )
    descriptor = RenderVarOutputDescriptor(
        render_product_path="/Render/Camera",
        render_var_name="DistanceToCameraSD",
        output_kind="scalar_depth",
        dtype="float32",
        shape=["720", "1280", "1"],
        component_count="1",
        units="m",
        value_range=(0, 100),
        color_space="linear",
        validity_semantics="finite_values",
        presets=[preset],
        capabilities=["probe", "display"],
        warnings=[warning],
        revision_token=42,
        metadata={"source": "camera"},
    )

    assert descriptor.output_id == "/Render/Camera:DistanceToCameraSD"
    assert descriptor.display_name == "DistanceToCameraSD"
    assert descriptor.output_kind is RenderVarOutputKind.SCALAR_DEPTH
    assert descriptor.shape == (720, 1280, 1)
    assert descriptor.component_count == 1
    assert descriptor.value_range == (0.0, 100.0)
    assert descriptor.presets == (preset,)
    assert descriptor.capabilities == ("probe", "display")
    assert descriptor.warnings == (warning,)
    assert descriptor.revision_token == "42"
    assert descriptor.metadata["source"] == "camera"
    assert descriptor.is_available
    assert descriptor.supports_preset("scalar_grayscale")
    assert not descriptor.supports_preset(RenderVarPresetKind.HDR_TONEMAP)
    with pytest.raises(TypeError):
        descriptor.metadata["other"] = "value"


def test_output_descriptor_disabled_and_validation():
    disabled = RenderVarOutputDescriptor(
        output_id="bad",
        enabled=False,
        disabled_reason="Output failed.",
    )
    assert not disabled.is_available

    with pytest.raises(ValueError, match="component_count"):
        RenderVarOutputDescriptor(component_count=0)
    with pytest.raises(ValueError, match="shape"):
        RenderVarOutputDescriptor(shape=(720, -1, 1))
    with pytest.raises(ValueError, match="value_range"):
        RenderVarOutputDescriptor(value_range=(1.0, 0.0))


def test_catalog_defaults_are_empty_and_lookup_is_stable():
    catalog = RenderVarOutputCatalog()

    assert catalog.outputs == ()
    assert catalog.is_empty
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        catalog.outputs = ()

    descriptor = RenderVarOutputDescriptor(
        output_id="depth",
        render_product_path="/Render/Camera",
        render_var_name="DepthSD",
    )
    warning = RenderVarWarning("stale", "Catalog is stale.")
    populated = RenderVarOutputCatalog(
        outputs=[descriptor],
        active_render_product_path="/Render/Camera",
        active_output_id="depth",
        selected_output_id="depth",
        revision=5,
        warnings=[warning],
    )
    assert populated.outputs == (descriptor,)
    assert populated.output("depth") == descriptor
    assert populated.output("missing") is None
    assert populated.revision == "5"
    assert populated.warnings == (warning,)
    assert not populated.is_empty


def test_request_frame_and_probe_contracts_are_immutable_and_validated():
    preset = RenderVarVisualizationPreset(kind=RenderVarPresetKind.HDR_TONEMAP)
    request = RenderVarOutputRequest(
        viewport_id=99,
        render_product_path="/Render/Camera",
        output_id="hdr",
        render_var_name="HdrColor",
        preset=preset,
        enable_probe=1,
        options={"preview": "rgba"},
    )
    frame = RenderVarOutputFrame(
        render_product_path="/Render/Camera",
        output_id="hdr",
        render_var_name="HdrColor",
        width="1280",
        height="720",
        dtype="uint8",
        component_count="4",
        color_space="srgb",
        value_range=(0, 1),
        display_data="rgba-buffer",
        raw_data="float16-buffer",
        frame_index="8",
        timestamp="12.25",
        stale=1,
        metadata={"preset": "hdr"},
    )
    probe = RenderVarProbeRequest(
        viewport_id="viewport",
        output_id="semantic",
        pixel_x="10",
        pixel_y="20",
        normalized_x="0.25",
        normalized_y="0.5",
        frame_index="8",
    )

    assert request.viewport_id == "99"
    assert request.enable_probe is True
    assert request.options["preview"] == "rgba"
    assert frame.width == 1280
    assert frame.height == 720
    assert frame.frame_index == 8
    assert frame.timestamp == 12.25
    assert frame.stale is True
    assert not frame.is_empty
    assert frame.metadata["preset"] == "hdr"
    assert probe.pixel_x == 10
    assert probe.pixel_y == 20
    assert probe.normalized_x == 0.25
    assert probe.frame_index == 8
    with pytest.raises(TypeError):
        request.options["other"] = "value"
    with pytest.raises(TypeError):
        frame.metadata["other"] = "value"
    with pytest.raises(ValueError, match="dimensions"):
        RenderVarOutputFrame(width=-1)
    with pytest.raises(ValueError, match="normalized_x"):
        RenderVarProbeRequest(normalized_x=1.5)


def test_probe_result_and_request_result_constructors_are_predictable():
    request = RenderVarOutputRequest(
        viewport_id="viewport",
        render_product_path="/Render/Camera",
        output_id="semantic",
    )
    accepted = RenderVarOutputRequestResult.accepted_result(
        active_request=request,
        message="Enabled.",
    )
    rejected = RenderVarOutputRequestResult.rejected_result(
        "Unsupported.",
        warning_code="unsupported",
        active_request=request,
    )
    value = RenderVarProbeResult.value_result(
        raw_value=7,
        normalized_value=0.7,
        display_value="car",
        pixel_x=4,
        pixel_y=6,
        category_id="7",
        category_label="Vehicle",
    )
    unsupported = RenderVarProbeResult.unsupported_result()

    assert accepted.accepted
    assert accepted.active_request == request
    assert accepted.warning_code is None
    assert not rejected.accepted
    assert rejected.warning_code == "unsupported"
    assert value.accepted
    assert value.raw_value == 7
    assert value.category_id == 7
    assert value.category_label == "Vehicle"
    assert not unsupported.accepted
    assert unsupported.warning_code == "unsupported"


def test_renderer_adapter_render_var_defaults_are_no_support():
    renderer = _ConcreteRenderer()
    request = RenderVarOutputRequest(
        viewport_id="viewport",
        render_product_path="/Render/Camera",
        output_id="depth",
    )
    probe = RenderVarProbeRequest(
        viewport_id="viewport",
        render_product_path="/Render/Camera",
        output_id="depth",
        pixel_x=1,
        pixel_y=2,
    )

    catalog = renderer.list_render_var_outputs("/Render/Camera")
    result = renderer.set_render_var_output_request("viewport", request)

    assert catalog == RenderVarOutputCatalog()
    assert catalog.is_empty
    assert result == RenderVarOutputRequestResult.rejected_result(
        "RenderVar output visualization is not supported.",
        warning_code="unsupported",
    )
    assert renderer.get_latest_render_var_output_frame("viewport", "/Render/Camera") is None
    assert renderer.clear_render_var_output_request("viewport") is None
    assert renderer.probe_render_var_output(probe) == RenderVarProbeResult.unsupported_result()


def test_common_package_exports_render_var_contracts():
    import ovui_data_adapters.common as pkg

    assert "RenderVarOutputDescriptor" in pkg.__all__
    assert "RenderVarOutputCatalog" in pkg.__all__
    assert "RenderVarOutputRequestResult" in pkg.__all__
    assert "RenderVarProbeResult" in pkg.__all__
