# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Area-3 effective resolution application to OpenUSD sessions."""

from __future__ import annotations

import math
from collections.abc import Callable
from types import SimpleNamespace

import pytest

pytest.importorskip("pxr")
from pxr import Sdf, Usd, UsdGeom, UsdRender  # noqa: E402

from ovui_data_adapters.openusd.renderer_adapter import (  # noqa: E402
    _CAMERA_PATH,
    _LDR_VAR_PATH,
    _RENDER_PRODUCT_PATH,
    OvRtxRendererAdapter,
)


def _session_product_resolution(stage: Usd.Stage) -> tuple[int, int]:
    prim = stage.GetPrimAtPath(_RENDER_PRODUCT_PATH)
    assert prim.IsValid()
    product = UsdRender.Product(prim)
    value = product.GetResolutionAttr().Get()
    return (int(value[0]), int(value[1]))


def _make_adapter_for_session_stage(
    stage: Usd.Stage,
) -> tuple[OvRtxRendererAdapter, list[str], list[object], Callable[[], None]]:
    added_usda: list[str] = []
    removed_handles: list[object] = []
    clock = {"now": 0.0}

    adapter = object.__new__(OvRtxRendererAdapter)
    adapter._stage = stage
    adapter._renderer = SimpleNamespace(
        remove_usd=lambda handle: removed_handles.append(handle)
    )
    adapter._session_handle = "old-session"
    adapter._last_resolution = (640, 360)
    adapter._last_big_delta_time = -math.inf
    adapter._last_reinject_time = -math.inf
    adapter._clock = lambda: clock["now"]
    adapter._scene_has_lights = True
    adapter._render_product_path = _RENDER_PRODUCT_PATH
    adapter._default_render_product_path = _RENDER_PRODUCT_PATH
    adapter._camera_path = _CAMERA_PATH
    adapter._default_camera_path = _CAMERA_PATH
    adapter._last_pushed_camera_intrinsics = None
    adapter._session_render_product_setting_lines = lambda: ()

    def _add_session_layer(usda: str) -> str:
        added_usda.append(usda)
        return f"session-{len(added_usda)}"

    adapter._add_ovrtx_session_layer = _add_session_layer

    def _advance_clock() -> None:
        clock["now"] += 1.0

    return adapter, added_usda, removed_handles, _advance_clock


def test_openusd_adapter_authors_effective_size_to_session_render_product_only() -> None:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    root_before = stage.GetRootLayer().ExportToString()
    adapter, added_usda, removed_handles, advance_clock = (
        _make_adapter_for_session_stage(stage)
    )

    for target in (
        (1280, 720),
        (1920, 1080),
        (960, 540),
        (3840, 2160),
        (800, 600),
    ):
        advance_clock()
        adapter._apply_resolution_if_allowed(target)

        assert adapter._last_resolution == target
        assert _session_product_resolution(stage) == target
        assert f"resolution = ({target[0]}, {target[1]})" in added_usda[-1]
        assert stage.GetRootLayer().ExportToString() == root_before
        assert stage.GetRootLayer().GetPrimAtPath(_RENDER_PRODUCT_PATH) is None

    assert removed_handles[0] == "old-session"
    assert adapter._session_handle == f"session-{len(added_usda)}"


def test_direct_session_resolution_authoring_preserves_root_layer() -> None:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    root_before = stage.GetRootLayer().ExportToString()
    adapter, _added_usda, _removed_handles, _advance_clock = (
        _make_adapter_for_session_stage(stage)
    )

    adapter._author_owned_session_render_product_resolution((1920, 1080))

    assert _session_product_resolution(stage) == (1920, 1080)
    assert stage.GetSessionLayer().GetPrimAtPath(_RENDER_PRODUCT_PATH) is not None
    assert stage.GetRootLayer().ExportToString() == root_before
    assert stage.GetRootLayer().GetPrimAtPath(_RENDER_PRODUCT_PATH) is None


def test_session_resolution_authoring_skips_external_render_product() -> None:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    root_before = stage.GetRootLayer().ExportToString()
    adapter, _added_usda, _removed_handles, _advance_clock = (
        _make_adapter_for_session_stage(stage)
    )
    adapter._render_product_path = "/World/UserRenderProduct"

    adapter._author_owned_session_render_product_resolution((1920, 1080))

    assert stage.GetSessionLayer().GetPrimAtPath(_RENDER_PRODUCT_PATH) is None
    assert stage.GetRootLayer().ExportToString() == root_before


def test_openusd_session_uses_adapter_ldr_var_path() -> None:
    stage = Usd.Stage.CreateInMemory()
    adapter, _added_usda, _removed_handles, _advance_clock = (
        _make_adapter_for_session_stage(stage)
    )

    adapter._author_owned_session_render_product_resolution((960, 540))

    prim = stage.GetPrimAtPath(_RENDER_PRODUCT_PATH)
    product = UsdRender.Product(prim)
    assert product.GetOrderedVarsRel().GetTargets() == [Sdf.Path(_LDR_VAR_PATH)]
