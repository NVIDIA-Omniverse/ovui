# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Provider-owned ovstage scene open and population."""

from __future__ import annotations

import pathlib

import pytest

from ovui_data_adapters.common import CreateRequest
from ovui_data_adapters.ovstage._scene import (
    POPULATION_OPERATION,
    OvstageScene,
    OvstageSceneOpenError,
)
from ovui_data_adapters.ovstage.layer_stack_adapter import OvstageLayerStackAdapter
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    build_factories,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes


pytestmark = [
    pytest.mark.requires_ovstage,
]


@pytest.fixture()
def ovstage_runtime():
    return load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )


def test_open_stage_populates_fixture_roots_from_native_ovstage(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime,
) -> None:
    session = create_provider_session(runtime=ovstage_runtime)

    scene = session.open_stage(str(ovstage_static_scene_path))

    assert isinstance(scene, OvstageScene)
    assert session.current_scene is scene
    assert scene.is_open is True
    assert scene.source_path == str(ovstage_static_scene_path.resolve())
    assert scene.root_paths == ("/World",)
    assert scene.initial_ordinal > 0
    assert scene.current_ordinal == scene.initial_ordinal

    session.shutdown_scene()


def test_opened_scene_is_shared_by_scaffold_adapters(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime,
) -> None:
    factories = build_factories(runtime=ovstage_runtime)
    session = factories.session()
    scene = session.open_stage(str(ovstage_static_scene_path))

    stage = factories.stage(scene, None, None)
    properties = factories.properties(scene, ["/World"], None, stage)
    transforms = factories.transforms(scene)
    renderer = factories.renderer(scene)
    selection = factories.selection(scene, stage)
    layers = factories.layers(scene, None)

    assert stage._scene is scene
    assert properties._native._scene is scene
    assert transforms._scene is scene
    assert renderer._scene is scene
    assert selection._scene is scene
    assert layers._scene is scene
    assert properties.get_paths() == ["/World"]
    assert properties.is_valid() is True
    assert transforms.can_transform("/World") is True
    assert transforms.can_transform("/") is False
    # The native-only adapter exposes no logical USD layer stack; the layer
    # adapter is truthfully inert instead of delegating to an OpenUSD bridge.
    assert layers.get_layer_stack_identifiers() == []

    session.shutdown_scene()


def test_population_failure_is_structured_and_preserves_current_scene(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_test_data_dir: pathlib.Path,
    ovstage_runtime,
) -> None:
    session = create_provider_session(runtime=ovstage_runtime)
    good_scene = session.open_stage(str(ovstage_static_scene_path))
    missing_path = ovstage_test_data_dir / "does-not-exist.usda"

    with pytest.raises(OvstageSceneOpenError) as exc_info:
        session.open_stage(str(missing_path))

    failure = exc_info.value.failure
    assert failure.provider_name == PROVIDER_NAME
    assert failure.entry_point_value == PROVIDER_ENTRY_POINT_VALUE
    assert failure.operation == POPULATION_OPERATION
    assert failure.path == str(missing_path.resolve())
    assert failure.ordinal is not None
    assert failure.ordinal > 0
    assert failure.exception_type == "OvstageError"
    assert "failed to open" in failure.exception_text
    assert session.population_failures == (failure,)
    assert session.current_scene is good_scene
    assert good_scene.is_open is True

    session.shutdown_scene()


def test_scene_shutdown_releases_native_handle_and_reopen_is_safe(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime,
) -> None:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    native_stage = scene._stage

    assert bool(getattr(native_stage, "_inst", None)) is True

    session.shutdown_scene()
    scene.shutdown()

    assert session.current_scene is None
    assert scene.is_open is False
    assert bool(getattr(native_stage, "_inst", None)) is False

    next_scene = session.open_stage(str(ovstage_static_scene_path))
    assert next_scene is not scene
    assert next_scene.is_open is True
    assert next_scene.root_paths == ("/World",)
    assert next_scene.initial_ordinal > 0

    session.shutdown_scene()
