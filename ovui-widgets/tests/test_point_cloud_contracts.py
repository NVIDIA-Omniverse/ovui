# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for backend-neutral point-cloud contracts."""

from __future__ import annotations

import dataclasses
import subprocess
import sys

import pytest

from ovui_data_adapters.common import (
    PointCloudChannelDescriptor,
    PointCloudChannelSemantic,
    PointCloudColorMode,
    PointCloudCoordinateSpace,
    PointCloudFrame,
    PointCloudOutputCatalog,
    PointCloudOutputDescriptor,
    PointCloudRequest,
    PointCloudRequestResult,
    PointCloudWarning,
    PointCloudWarningSeverity,
    RendererAdapter,
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


def test_point_cloud_contract_module_has_no_backend_or_ui_import_side_effects():
    code = """
import importlib
import sys

for name in ("pxr", "ovrtx", "numpy", "ovui_widgets"):
    if name in sys.modules:
        raise SystemExit(f"{name} was preloaded before the contract import")

importlib.import_module("ovui_data_adapters.common.point_cloud")

loaded = [
    name
    for name in ("pxr", "ovrtx", "numpy", "ovui_widgets")
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
    assert PointCloudChannelSemantic.COORDINATES.value == "coordinates"
    assert PointCloudChannelSemantic.RADIAL_VELOCITY.value == "radial_velocity"
    assert PointCloudChannelSemantic.RCS.value == "rcs"
    assert PointCloudColorMode.FIXED.value == "fixed"
    assert PointCloudColorMode.INTENSITY.value == "intensity"
    assert PointCloudColorMode.RANGE.value == "range"
    assert PointCloudColorMode.VELOCITY.value == "velocity"
    assert PointCloudColorMode.RCS.value == "rcs"
    assert PointCloudColorMode.MATERIAL_ID.value == "material_id"
    assert PointCloudColorMode.OBJECT_ID.value == "object_id"
    assert PointCloudCoordinateSpace.WORLD.value == "world"
    assert PointCloudWarningSeverity.ERROR.value == "error"


def test_channel_descriptor_is_frozen_and_coerces_metadata():
    descriptor = PointCloudChannelDescriptor(
        name="Intensity",
        semantic="intensity",
        dtype="float32",
        component_count="1",
        units="normalized",
        value_range=(0, 1),
        validity_semantics="per_valid_point",
        color_modes=["intensity"],
    )

    assert descriptor.semantic is PointCloudChannelSemantic.INTENSITY
    assert descriptor.component_count == 1
    assert descriptor.value_range == (0.0, 1.0)
    assert descriptor.color_modes == (PointCloudColorMode.INTENSITY,)
    assert descriptor.supports_coloring
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        descriptor.name = "Changed"


def test_channel_descriptor_validates_required_shape():
    with pytest.raises(ValueError, match="channel name"):
        PointCloudChannelDescriptor(name="")
    with pytest.raises(ValueError, match="component_count"):
        PointCloudChannelDescriptor(name="Coordinates", component_count=0)
    with pytest.raises(ValueError, match="value_range"):
        PointCloudChannelDescriptor(name="Range", value_range=(0.0, 1.0, 2.0))


def test_output_descriptor_collects_channels_and_color_modes():
    intensity = PointCloudChannelDescriptor(
        name="Intensity",
        semantic=PointCloudChannelSemantic.INTENSITY,
        color_modes=(PointCloudColorMode.INTENSITY,),
    )
    warning = PointCloudWarning(
        code="sensor_frame",
        message="Output needs a transform before display.",
        severity="warning",
    )
    descriptor = PointCloudOutputDescriptor(
        render_product_path="/Render/Lidar",
        source_sensor_path="/World/Lidar",
        coordinate_space="world",
        transform_to_world=range(16),
        channels=[intensity],
        capabilities=["point_cloud", "world_points"],
        warnings=[warning],
    )

    assert descriptor.channel_names == ("Intensity",)
    assert descriptor.channel("Intensity") == intensity
    assert descriptor.supports_color_mode(PointCloudColorMode.FIXED)
    assert descriptor.supports_color_mode("intensity")
    assert not descriptor.supports_color_mode(PointCloudColorMode.RCS)
    assert descriptor.capabilities == ("point_cloud", "world_points")
    assert descriptor.warnings == (warning,)
    assert descriptor.is_available
    assert descriptor.transform_to_world == tuple(float(i) for i in range(16))


def test_output_descriptor_disabled_and_transform_validation():
    disabled = PointCloudOutputDescriptor(
        render_product_path="/Render/Radar",
        enabled=False,
        disabled_reason="Missing transform.",
    )
    assert not disabled.is_available

    with pytest.raises(ValueError, match="transform_to_world"):
        PointCloudOutputDescriptor(transform_to_world=range(15))


def test_output_catalog_defaults_are_empty_and_immutable():
    catalog = PointCloudOutputCatalog()

    assert catalog.outputs == ()
    assert catalog.is_empty
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        catalog.outputs = ()

    output = PointCloudOutputDescriptor(render_product_path="/Render/Lidar")
    populated = PointCloudOutputCatalog(
        outputs=[output],
        active_render_product_path="/Render/Lidar",
        revision=12,
    )
    assert populated.outputs == (output,)
    assert populated.active_render_product_path == "/Render/Lidar"
    assert populated.revision == "12"
    assert not populated.is_empty


def test_request_coerces_options_and_validates_budget():
    request = PointCloudRequest(
        viewport_id=123,
        render_product_path="/Render/Lidar",
        requested_channels=["Coordinates", "Intensity"],
        max_points="1000",
        decimation_stride="4",
        include_validity=1,
        color_mode="intensity",
        desired_coordinate_space="world",
    )

    assert request.viewport_id == "123"
    assert request.requested_channels == ("Coordinates", "Intensity")
    assert request.max_points == 1000
    assert request.decimation_stride == 4
    assert request.include_validity is True
    assert request.color_mode is PointCloudColorMode.INTENSITY
    assert request.desired_coordinate_space is PointCloudCoordinateSpace.WORLD

    with pytest.raises(ValueError, match="max_points"):
        PointCloudRequest(max_points=0)
    with pytest.raises(ValueError, match="decimation_stride"):
        PointCloudRequest(decimation_stride=0)


def test_frame_snapshot_is_immutable_and_bounds_valid_points():
    frame = PointCloudFrame(
        render_product_path="/Render/Lidar",
        point_count=10,
        valid_point_count=4,
        coordinates="coordinates-buffer",
        channels={"Intensity": "intensity-buffer"},
        validity_mask="mask-buffer",
        coordinate_space="world",
        transform_to_world=range(16),
        frame_index="7",
        timestamp="12.5",
        stale=1,
        source_sensor_path="/World/Lidar",
        source_sensor_type="OmniLidar",
    )

    assert frame.valid_point_count == 4
    assert not frame.is_empty
    assert frame.channel_data("Intensity") == "intensity-buffer"
    assert frame.channel_data("Missing") is None
    assert frame.coordinate_space is PointCloudCoordinateSpace.WORLD
    assert frame.frame_index == 7
    assert frame.timestamp == 12.5
    assert frame.stale is True
    with pytest.raises(TypeError):
        frame.channels["Other"] = "payload"

    with pytest.raises(ValueError, match="valid_point_count"):
        PointCloudFrame(point_count=2, valid_point_count=3)
    with pytest.raises(ValueError, match="point_count"):
        PointCloudFrame(point_count=-1)


def test_request_result_constructors_are_predictable():
    request = PointCloudRequest(viewport_id="viewport", render_product_path="/Render/Lidar")
    accepted = PointCloudRequestResult.accepted_result(
        active_request=request,
        message="Enabled.",
    )
    rejected = PointCloudRequestResult.rejected_result(
        "Unsupported.",
        warning_code="unsupported",
        active_request=request,
    )

    assert accepted.accepted
    assert accepted.active_request == request
    assert accepted.warning_code is None
    assert not rejected.accepted
    assert rejected.warning_code == "unsupported"
    assert rejected.active_request == request


def test_renderer_adapter_point_cloud_defaults_are_no_support():
    renderer = _ConcreteRenderer()
    request = PointCloudRequest(viewport_id="viewport", render_product_path="/Render/Lidar")

    catalog = renderer.list_point_cloud_outputs("/Render/Lidar")
    result = renderer.set_point_cloud_request("viewport", request)

    assert catalog == PointCloudOutputCatalog()
    assert catalog.is_empty
    assert result == PointCloudRequestResult.rejected_result(
        "Point-cloud output is not supported.",
        warning_code="unsupported",
    )
    assert renderer.get_latest_point_cloud_frame("viewport", "/Render/Lidar") is None
    assert renderer.clear_point_cloud_request("viewport") is None


def test_common_package_exports_point_cloud_contracts():
    import ovui_data_adapters.common as pkg

    assert "PointCloudChannelDescriptor" in pkg.__all__
    assert "PointCloudOutputCatalog" in pkg.__all__
    assert "PointCloudRequestResult" in pkg.__all__
