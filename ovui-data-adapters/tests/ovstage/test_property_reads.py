# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Exact native OVStage property reads plus computed matrix attributes."""

from __future__ import annotations

import pathlib
import struct
from typing import Any, Iterator

import pytest

from ovui_data_adapters.ovstage._scene import OvstageScene
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes


pytestmark = [
    pytest.mark.requires_ovstage,
]

_CAMERA_PATH = "/World/Cameras/MainCamera"


@pytest.fixture()
def ovstage_runtime():
    return load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )


@pytest.fixture()
def ovstage_scene(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
) -> Iterator[OvstageScene]:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    try:
        yield scene
    finally:
        session.shutdown_scene()


def _raw(stage: Any, path: str, attr_name: str) -> bytes:
    return bytes(stage.read_attribute(int(stage.current_ordinal), [path], attr_name))


def _unpack(stage: Any, path: str, attr_name: str, fmt: str) -> tuple[Any, ...]:
    return struct.unpack(fmt, _raw(stage, path, attr_name))


def test_property_adapter_validates_real_ovstage_paths(
    ovstage_scene: OvstageScene,
) -> None:
    valid = OvstagePropertyAdapter(ovstage_scene, [_CAMERA_PATH])
    missing = OvstagePropertyAdapter(ovstage_scene, ["/World/DoesNotExist"])
    empty = OvstagePropertyAdapter(ovstage_scene, [])

    assert valid.get_paths() == [_CAMERA_PATH]
    assert valid.is_valid() is True
    assert missing.is_valid() is False
    assert empty.is_valid() is False


def test_attribute_names_are_common_readable_ovstage_attributes(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstagePropertyAdapter(ovstage_scene, [_CAMERA_PATH])

    names = adapter.get_attribute_names()

    assert {
        "clippingRange",
        "focalLength",
        "horizontalAperture",
        "localMatrix",
        "worldMatrix",
    }.issubset(set(names))
    assert "usd-schemas" not in names


def test_values_use_exact_native_columns_and_computed_matrices(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstagePropertyAdapter(ovstage_scene, [_CAMERA_PATH])
    stage = ovstage_scene._stage

    assert adapter.get_scheme() == "ovstage"
    assert adapter.get_value("focalLength") == pytest.approx(
        _unpack(stage, _CAMERA_PATH, "focalLength", "<f")[0]
    )
    assert adapter.get_value("horizontalAperture") == pytest.approx(
        _unpack(stage, _CAMERA_PATH, "horizontalAperture", "<f")[0]
    )
    # The native-only adapter reports the exact native column value — even
    # where OVStage 0.1 mirrors its own fallback for this double2 column —
    # instead of re-deriving an authoritative value from a USD bridge.
    clipping_raw = _raw(stage, _CAMERA_PATH, "clippingRange")
    clipping_fmt = "<2d" if len(clipping_raw) == 16 else "<2f"
    assert adapter.get_value("clippingRange") == pytest.approx(
        struct.unpack(clipping_fmt, clipping_raw)
    )
    assert len(adapter.get_value("worldMatrix")) == 16
    assert len(adapter.get_value("localMatrix")) == 16


def test_metadata_combines_usd_properties_and_computed_ovstage_fields(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstagePropertyAdapter(ovstage_scene, [_CAMERA_PATH])

    expected = {
        "focalLength": ("float", float, "Focal Length", "Attributes"),
        "clippingRange": ("float2", "float2", "Clipping Range", "Attributes"),
        "localMatrix": ("matrix4d", tuple, "Local Matrix", "Attributes"),
    }

    for attr_name, (type_name, value_type, display_name, group) in expected.items():
        metadata = adapter.get_attribute_metadata(attr_name)
        assert metadata.name == attr_name
        assert metadata.type_name == type_name
        assert metadata.value_type == value_type
        assert metadata.display_name == display_name
        assert metadata.group == group

    assert adapter.get_attribute_metadata("localMatrix").is_locked is True
    assert adapter.get_resolved_asset_path("focalLength") is None


def test_values_are_plain_python_objects(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstagePropertyAdapter(ovstage_scene, [_CAMERA_PATH])

    for attr_name in adapter.get_attribute_names():
        value = adapter.get_value(attr_name)
        assert isinstance(value, (bool, int, float, str, tuple))
