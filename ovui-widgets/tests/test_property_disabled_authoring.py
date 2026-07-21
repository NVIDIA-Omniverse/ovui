# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Property Inspector disabled authoring gates for the ovstage provider."""

from __future__ import annotations

import pathlib
from typing import Any, Iterator

import pytest

from ovui_data_adapters.ovstage._scene import OvstageScene
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.runtime_preflight import (
    OvstageRuntimePreflightError,
    load_required_runtimes,
)
from ovui_widgets.property.models import AttributeModelBase
from ovui_widgets.property.parts.control_state import ControlStateManager
from ovui_widgets.property.parts.attr_context_menu import (
    can_reset as can_reset_attr,
    clear_clipboard as clear_attr_clipboard,
    reset_value,
)
from ovui_widgets.property.parts.display_group import UiDisplayGroup
from ovui_widgets.property.parts.group_context_menu import can_reset as can_reset_group


pytestmark = [
    pytest.mark.requires_ovstage,
    pytest.mark.requires_ovphysx,
    pytest.mark.requires_ovrtx,
]

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_STATIC_SCENE_PATH = _REPO_ROOT / "ovui-data-adapters" / "tests" / "data" / "ovstage_static_scene.usda"
_MIRRORED_PATH = "/World/AttributeCases/MirroredValues"


@pytest.fixture(autouse=True)
def _fresh_control_states() -> Iterator[None]:
    ControlStateManager._reset_for_tests()
    clear_attr_clipboard()
    try:
        yield
    finally:
        ControlStateManager._reset_for_tests()
        clear_attr_clipboard()


@pytest.fixture()
def ovstage_runtime():
    try:
        return load_required_runtimes(
            module_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        )
    except OvstageRuntimePreflightError as exc:
        pytest.skip(str(exc))


@pytest.fixture()
def ovstage_scene(ovstage_runtime: Any) -> Iterator[OvstageScene]:
    assert _STATIC_SCENE_PATH.is_file(), f"missing static fixture: {_STATIC_SCENE_PATH}"
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(_STATIC_SCENE_PATH))
    try:
        yield scene
    finally:
        session.shutdown_scene()


def _group_for(prop) -> UiDisplayGroup:
    group = UiDisplayGroup(name=prop.group)
    group.add_prop(prop, ())
    return group


def test_clear_to_default_controls_stay_disabled_for_ovstage_runtime_rows(
    ovstage_scene: OvstageScene,
) -> None:
    # OVStage exposes no authored-opinion/default query, so even a writable
    # native row must keep clear-to-default disabled instead of guessing.
    adapter = OvstagePropertyAdapter(ovstage_scene, [_MIRRORED_PATH])
    metadata = adapter.get_attribute_metadata("visibility")
    model = AttributeModelBase(adapter, "visibility", metadata)
    manager = ControlStateManager.get_instance()
    before = adapter.get_value("visibility")

    assert model.is_readonly is False
    assert manager.get_active_state(model) is None
    assert can_reset_attr(adapter, "visibility") is False
    assert can_reset_group(adapter, _group_for(metadata)) is False
    assert reset_value(adapter, "visibility") is False
    assert adapter.get_value("visibility") == before


def test_attributes_absent_from_native_surface_fail_closed(
    ovstage_scene: OvstageScene,
) -> None:
    # Custom USD-authored attributes are not part of the exact OVStage 0.1
    # native column surface. The native-only adapter refuses them instead of
    # mirroring USD opinions into fabricated Property Inspector rows.
    adapter = OvstagePropertyAdapter(ovstage_scene, [_MIRRORED_PATH])

    names = adapter.get_attribute_names()
    assert "test:count" not in names
    assert "test:indices" not in names
    with pytest.raises(NotImplementedError):
        adapter.get_attribute_metadata("test:indices")
    with pytest.raises(NotImplementedError):
        adapter.get_value("test:count")


def test_computed_transform_properties_remain_disabled_for_property_authoring(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstagePropertyAdapter(ovstage_scene, [_MIRRORED_PATH])
    metadata = adapter.get_attribute_metadata("localMatrix")
    model = AttributeModelBase(adapter, "localMatrix", metadata)

    assert model.is_readonly is True
    with pytest.raises(NotImplementedError):
        adapter.set_value("localMatrix", (1.0,) * 16)
