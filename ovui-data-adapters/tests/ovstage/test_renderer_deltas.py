# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OVStage edits consumed directly by an OVRTX BORROW renderer."""

from __future__ import annotations

import pathlib
import time
from typing import Any, Iterator

import numpy as np
import pytest

from ovui_data_adapters.ovstage._scene import OvstageScene
from ovui_data_adapters.ovstage.provider import (
    create_provider_session,
)
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter
from ovui_data_adapters.ovstage.transform_adapter import OvstageTransformAdapter


_NESTED_PARENT = "/World/TransformCases/NestedParent"
_VISIBLE_PARENT = "/World/VisibilityCases/VisibleParent"


@pytest.fixture(scope="module")
def ovrtx_first_bootstrap() -> Iterator[OvstageRendererAdapter]:
    """Match the application entrypoint's native runtime ordering.

    Constructing OVRTX establishes the Kit Carbonite/USD cohort before any
    OVStage Stage exists. The focused tests never attach or render through
    this bootstrap renderer; it exists only to initialize the shared native
    runtime in the same order as ``native_runtime_bootstrap``.
    """

    renderer = OvstageRendererAdapter()
    try:
        yield renderer
    finally:
        renderer.shutdown()


@pytest.fixture()
def ovstage_scene(
    ovstage_static_scene_path: pathlib.Path,
    ovrtx_first_bootstrap: OvstageRendererAdapter,
) -> Iterator[OvstageScene]:
    del ovrtx_first_bootstrap  # fixture dependency is the ordering contract
    session = create_provider_session()
    scene = session.open_stage(str(ovstage_static_scene_path))
    try:
        yield scene
    finally:
        session.shutdown_scene()


@pytest.mark.requires_ovstage
@pytest.mark.requires_ovrtx
def test_transform_edit_advances_the_ordinal_passed_to_step(
    ovstage_scene: OvstageScene,
) -> None:
    transform_adapter = OvstageTransformAdapter(ovstage_scene)
    renderer = _BorrowRenderer()
    adapter = _borrow_adapter(ovstage_scene, renderer)
    transform_adapter.set_local_transform(
        _NESTED_PARENT,
        _translation_matrix(7.0, 8.0, 9.0),
    )
    edited_ordinal = int(ovstage_scene.current_ordinal)
    frame = adapter.render_frame(64, 32, None, None)

    assert frame.shape == (32, 64, 4)
    assert renderer.step_ordinals == [edited_ordinal]
    assert renderer.forbidden_data_api_lookups == []


@pytest.mark.requires_ovstage
@pytest.mark.requires_ovrtx
def test_visibility_edit_is_presented_without_an_ovrtx_delta_write(
    ovstage_scene: OvstageScene,
) -> None:
    stage_adapter = OvstageStageAdapter(ovstage_scene)
    renderer = _BorrowRenderer()
    adapter = _borrow_adapter(ovstage_scene, renderer)
    item = stage_adapter.get_item_at_path(_VISIBLE_PARENT)
    assert item is not None

    stage_adapter.set_visibility(item, False)
    edited_ordinal = int(ovstage_scene.current_ordinal)
    adapter.render_frame(64, 32, None, None)

    assert renderer.step_ordinals == [edited_ordinal]
    assert renderer.forbidden_data_api_lookups == []


def test_live_transform_preview_without_an_owner_never_uses_ovrtx_data() -> None:
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    renderer = _BorrowRenderer()
    adapter._scene = None
    adapter._attached_stage = None
    adapter._renderer = renderer

    assert adapter.supports_live_local_transform is False
    assert (
        adapter.set_live_local_transform(
            _NESTED_PARENT,
            _translation_matrix(1.0, 2.0, 3.0),
        )
        is False
    )
    assert adapter.clear_live_local_transforms([_NESTED_PARENT]) is None
    assert renderer.forbidden_data_api_lookups == []


class _BorrowRenderer:
    _FORBIDDEN_DATA_APIS = frozenset(
        {
            "add_usd",
            "add_usd_reference_from_string",
            "query_prims",
            "read_attribute",
            "remove_usd",
            "reset_stage",
            "resolve_prim_path_id",
            "step",
            "update_from_stage",
            "write_attribute",
        }
    )

    def __init__(self) -> None:
        self.step_ordinals: list[int] = []
        self.forbidden_data_api_lookups: list[str] = []

    def step(self, **kwargs: Any) -> dict[str, object]:
        self.step_ordinals.append(int(kwargs["ordinal"]))
        return {}

    def __getattr__(self, name: str) -> Any:
        if name in self._FORBIDDEN_DATA_APIS:
            self.forbidden_data_api_lookups.append(name)
        raise AttributeError(name)


def _borrow_adapter(
    scene: OvstageScene,
    renderer: _BorrowRenderer,
) -> OvstageRendererAdapter:
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._scene = scene
    adapter._renderer = renderer
    adapter._attached_stage = scene._stage
    adapter._gpu_device_name = "test gpu"
    adapter._logged_first_step = True
    adapter._render_product_path = "/_OvuiRuntime/Render/Viewport"
    adapter._camera_path = None
    adapter._last_resolution = (64, 32)
    adapter._last_render_product_resolution = (64, 32)
    adapter._dt_clock = time.monotonic()
    adapter._borrow_step_count = 0
    adapter._in_flight_pick_queries = None
    adapter._extract_ldr_color = (  # type: ignore[method-assign]
        lambda _products, width, height: np.zeros((height, width, 4), dtype=np.uint8)
    )
    return adapter


def _translation_matrix(x: float, y: float, z: float) -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [float(x), float(y), float(z), 1.0],
    ]
