# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage PropertyAdapter ambiguity from real multi-select reads."""

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

_BOX_A = "/World/Hierarchy/GroupA/BoxA"
_HIDDEN_CHILD_CUBE = "/World/VisibilityCases/HiddenParent/InheritedHiddenChild"
_NESTED_PARENT = "/World/TransformCases/NestedParent"
_NESTED_CHILD = "/World/TransformCases/NestedParent/NestedChild"
_EXPLICIT_HIDDEN_SPHERE = "/World/VisibilityCases/VisibleParent/ExplicitHiddenChild"
_INHERITED_VISIBLE_SPHERE = "/World/VisibilityCases/VisibleParent/InheritedVisibleChild"


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


def _double(stage: Any, path: str, attr_name: str) -> float:
    return struct.unpack("<d", _raw(stage, path, attr_name))[0]


def _matrix(stage: Any, path: str, attr_name: str) -> tuple[float, ...]:
    return struct.unpack("<16d", _raw(stage, path, attr_name))


def test_scalar_ambiguity_uses_real_differing_ovstage_values(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstagePropertyAdapter(ovstage_scene, [_BOX_A, _HIDDEN_CHILD_CUBE])
    stage = ovstage_scene._stage
    box_size = _double(stage, _BOX_A, "size")
    child_size = _double(stage, _HIDDEN_CHILD_CUBE, "size")

    assert box_size != child_size
    assert "size" in adapter.get_attribute_names()
    assert adapter.is_ambiguous("size") is True
    assert adapter.get_value("size") is None
    assert adapter.get_per_component_ambiguity("size") is None


def test_per_component_ambiguity_uses_real_differing_ovstage_values(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstagePropertyAdapter(ovstage_scene, [_NESTED_PARENT, _NESTED_CHILD])
    stage = ovstage_scene._stage
    parent_matrix = _matrix(stage, _NESTED_PARENT, "localMatrix")
    child_matrix = _matrix(stage, _NESTED_CHILD, "localMatrix")

    assert parent_matrix[12:15] == pytest.approx((0.0, 10.0, 0.0))
    assert child_matrix[12:15] == pytest.approx((0.0, 0.0, 2.0))
    assert adapter.is_ambiguous("localMatrix") is True
    assert adapter.get_value("localMatrix") is None
    component_ambiguity = adapter.get_per_component_ambiguity("localMatrix")
    assert component_ambiguity is not None
    assert len(component_ambiguity) == 16
    assert [index for index, differs in enumerate(component_ambiguity) if differs] == [
        13,
        14,
    ]


def test_matching_values_are_not_ambiguous_in_multiselect(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstagePropertyAdapter(
        ovstage_scene,
        [_EXPLICIT_HIDDEN_SPHERE, _INHERITED_VISIBLE_SPHERE],
    )
    stage = ovstage_scene._stage
    explicit_radius = _double(stage, _EXPLICIT_HIDDEN_SPHERE, "radius")
    inherited_radius = _double(stage, _INHERITED_VISIBLE_SPHERE, "radius")

    assert explicit_radius == inherited_radius
    assert adapter.is_ambiguous("radius") is False
    assert adapter.get_value("radius") == pytest.approx(explicit_radius)
    assert adapter.get_per_component_ambiguity("radius") is None
