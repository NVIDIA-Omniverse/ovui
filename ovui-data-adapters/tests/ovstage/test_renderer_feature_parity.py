# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Focused renderer parity tests for the OVStage-owned BORROW data flow."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from ovui_data_adapters.common import (
    PointCloudCoordinateSpace,
    PointCloudRequest,
    RenderVarOutputFrame,
    RenderVarOutputKind,
    RenderVarOutputRequest,
    RenderVarProbeRequest,
    RenderVarWarning,
)
from ovui_data_adapters.ovstage import renderer_adapter as renderer_module
from ovui_data_adapters.ovstage._catalog import (
    NativeCatalogPrim,
    NativeCatalogSnapshot,
)
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter

_PRODUCT = "/Render/Product"
_HDR_NAME = "HdrColor"


class _NoDataApiRenderer:
    """Fails if parity helpers touch any OVRTX renderer method."""

    def __init__(self) -> None:
        self.lookups: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.lookups.append(name)
        raise AssertionError(f"unexpected OVRTX renderer API lookup: {name}")


class _Scene:
    def __init__(self) -> None:
        self._stage = None
        self.is_open = True


class _Mapping:
    def __init__(self, tensor: np.ndarray) -> None:
        self.tensor = tensor

    def __enter__(self) -> "_Mapping":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


class _RenderVar:
    def __init__(self, tensor: Any) -> None:
        self._tensor = np.asarray(tensor)
        self.devices: list[Any] = []

    def map(self, *, device: Any = None) -> _Mapping:
        self.devices.append(device)
        return _Mapping(self._tensor)


_CAMERA = "/World/Camera"
_IDENTITY = tuple(float(index % 5 == 0) for index in range(16))
_ALL_VARS = ("/Render/Vars/Ldr", "/Render/Vars/Hdr", "/Render/Vars/PointCloud")


def _native_snapshot(
    ordered_vars: tuple[str, ...] = _ALL_VARS,
) -> NativeCatalogSnapshot:
    """Owned native catalog data mirroring the package snapshot contract."""

    prims = (
        NativeCatalogPrim(
            path=_CAMERA,
            type_name="Camera",
            applied_schemas=(),
            properties=(("worldMatrix", _IDENTITY),),
        ),
        NativeCatalogPrim(
            path="/Render/Vars/Ldr",
            type_name="RenderVar",
            applied_schemas=(),
            properties=(("sourceName", "LdrColor"),),
        ),
        NativeCatalogPrim(
            path="/Render/Vars/Hdr",
            type_name="RenderVar",
            applied_schemas=(),
            properties=(("sourceName", _HDR_NAME),),
        ),
        NativeCatalogPrim(
            path="/Render/Vars/PointCloud",
            type_name="RenderVar",
            applied_schemas=(),
            properties=(
                ("sourceName", "PointCloud"),
                ("channels", ("Coordinates", "Counts", "Intensity", "Flags")),
            ),
        ),
        NativeCatalogPrim(
            path=_PRODUCT,
            type_name="RenderProduct",
            applied_schemas=(),
            properties=(
                ("camera", (_CAMERA,)),
                ("orderedVars", tuple(ordered_vars)),
                ("resolution", (2, 1)),
            ),
        ),
    )
    return NativeCatalogSnapshot(
        ordinal=1,
        topology_version=1,
        topology_revision=1,
        prims=prims,
    )


def _patch_native_catalog(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: NativeCatalogSnapshot,
) -> dict[str, NativeCatalogSnapshot]:
    holder = {"snapshot": snapshot}
    monkeypatch.setattr(
        renderer_module,
        "native_catalog_snapshot",
        lambda _scene: holder["snapshot"],
    )
    return holder


def _adapter(
    undo_manager: Any | None = None,
) -> tuple[OvstageRendererAdapter, _Scene, _NoDataApiRenderer]:
    scene = _Scene()
    backend = _NoDataApiRenderer()
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._scene = scene
    adapter._undo_manager = undo_manager
    adapter._renderer = backend
    adapter._ovrtx = SimpleNamespace(Device=SimpleNamespace(CPU="cpu"))
    adapter._render_product_path = _PRODUCT
    adapter._default_render_product_path = "/_OvuiRuntime/Render/Viewport"
    adapter._active_render_product_common_path = _PRODUCT
    adapter._point_cloud_requests = {}
    adapter._latest_point_cloud_frames = {}
    adapter._render_var_output_requests = {}
    adapter._latest_render_var_output_frames = {}
    return adapter, scene, backend


def test_native_catalogs_match_render_outputs_without_ovrtx_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _scene, backend = _adapter()
    _patch_native_catalog(monkeypatch, _native_snapshot())

    point_catalog = adapter.list_point_cloud_outputs(_PRODUCT)
    render_var_catalog = adapter.list_render_var_outputs(_PRODUCT)

    assert len(point_catalog.outputs) == 1
    point_output = point_catalog.outputs[0]
    assert point_output.render_var_name == "PointCloud"
    assert point_output.coordinate_space is PointCloudCoordinateSpace.UNKNOWN
    assert point_output.channel_names == (
        "Coordinates",
        "Counts",
        "Intensity",
        "Flags",
    )
    assert point_output.is_available
    assert [output.render_var_name for output in render_var_catalog.outputs] == [
        _HDR_NAME
    ]
    assert backend.lookups == []


def test_source_render_product_never_receives_transient_runtime_writes() -> None:
    adapter, _scene, backend = _adapter()

    assert adapter._runtime_camera_path() is None

    adapter._attached_stage = object()
    adapter._last_resolution = (1280, 720)
    adapter._last_render_product_resolution = (2, 1)
    adapter._apply_resolution(731, 668)
    assert adapter._last_resolution == (731, 668)
    assert adapter._last_render_product_resolution is None

    adapter._render_product_path = adapter._default_render_product_path
    assert adapter._runtime_camera_path() == renderer_module._RENDER_CAMERA_LOCAL_PATH
    assert backend.lookups == []


def test_point_cloud_only_product_keeps_overlay_background_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _scene, backend = _adapter()
    holder = _patch_native_catalog(monkeypatch, _native_snapshot())

    assert adapter._active_product_uses_point_cloud_overlay() is False

    # Even for a PointCloud-only product, the native adapter keeps the
    # presentation overlay inert until native point-cloud presentation
    # support exists; it must never guess from catalog topology.
    holder["snapshot"] = _native_snapshot(
        ordered_vars=("/Render/Vars/PointCloud",)
    )
    assert adapter._active_product_uses_point_cloud_overlay() is False
    assert backend.lookups == []


def test_requests_map_only_ovrtx_product_outputs_and_cache_snapshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _scene, backend = _adapter()
    _patch_native_catalog(monkeypatch, _native_snapshot())
    point_result = adapter.set_point_cloud_request(
        "viewport",
        PointCloudRequest(
            render_product_path=_PRODUCT,
            requested_channels=("Intensity", "Flags"),
        ),
    )
    render_var_result = adapter.set_render_var_output_request(
        "viewport",
        RenderVarOutputRequest(
            render_product_path=_PRODUCT,
            render_var_name=_HDR_NAME,
        ),
    )
    assert point_result.accepted
    assert render_var_result.accepted
    assert adapter._render_products_for_step() == {_PRODUCT}

    render_vars = {
        "Counts": _RenderVar([2]),
        "Coordinates": _RenderVar([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]),
        "Intensity": _RenderVar([0.25, 0.75]),
        "Flags": _RenderVar([0x40, 0]),
        _HDR_NAME: _RenderVar([[[1.0, 0.5, 0.25, 1.0], [0.0, 0.25, 0.5, 1.0]]]),
    }
    products = {
        _PRODUCT: SimpleNamespace(
            frames=[SimpleNamespace(render_vars=render_vars, frame_index=12)]
        )
    }
    adapter._extract_requested_point_cloud_frames(products)
    adapter._extract_requested_render_var_output_frames(products)

    point_frame = adapter.get_latest_point_cloud_frame("viewport")
    assert point_frame is not None and not point_frame.stale
    np.testing.assert_allclose(
        point_frame.coordinates,
        [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
    )
    np.testing.assert_array_equal(point_frame.validity_mask, [True, False])
    np.testing.assert_allclose(point_frame.channels["Intensity"], [0.25, 0.75])
    render_var_frame = adapter.get_latest_render_var_output_frame("viewport")
    assert render_var_frame is not None and not render_var_frame.stale
    assert (render_var_frame.width, render_var_frame.height) == (2, 1)
    assert render_var_frame.frame_index == 12
    assert all(
        device == "cpu"
        for render_var in render_vars.values()
        for device in render_var.devices
    )
    assert backend.lookups == []


def test_render_var_probe_reads_only_the_cached_owned_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _scene, backend = _adapter()
    _patch_native_catalog(monkeypatch, _native_snapshot())
    request_result = adapter.set_render_var_output_request(
        "viewport",
        RenderVarOutputRequest(
            render_product_path=_PRODUCT,
            render_var_name=_HDR_NAME,
            enable_probe=True,
        ),
    )
    assert request_result.accepted
    active_request = request_result.active_request
    assert active_request is not None
    source = _RenderVar(
        [[[1.0, 0.5, 0.25, 1.0], [0.0, 0.25, 0.5, 1.0]]]
    )
    products = {
        _PRODUCT: SimpleNamespace(
            frames=[
                SimpleNamespace(
                    render_vars={_HDR_NAME: source},
                    frame_index=12,
                )
            ]
        )
    }
    adapter._extract_requested_render_var_output_frames(products)
    frame = adapter.get_latest_render_var_output_frame("viewport")
    assert frame is not None
    raw_before = np.array(frame.raw_data, copy=True)

    # Probing must read the host-owned snapshot, not remap the current OVRTX
    # output. Mutating the fake producer after extraction cannot change it.
    source._tensor[0, 1, :] = 99.0
    result = adapter.probe_render_var_output(
        RenderVarProbeRequest(
            viewport_id="viewport",
            render_product_path=_PRODUCT,
            output_id=active_request.output_id,
            normalized_x=1.0,
            normalized_y=0.0,
            frame_index=12,
        )
    )

    assert result.accepted
    assert (result.pixel_x, result.pixel_y) == (1, 0)
    assert result.raw_value == (0.0, 0.25, 0.5, 1.0)
    assert result.display_value == "(0, 0.25, 0.5, 1)"
    assert result.frame_index == 12
    np.testing.assert_array_equal(frame.raw_data, raw_before)
    assert backend.lookups == []


@pytest.mark.parametrize(
    ("frame", "probe", "expected"),
    (
        (
            RenderVarOutputFrame(
                render_product_path=_PRODUCT,
                output_id="depth",
                render_var_name="DepthLinearized",
                width=2,
                height=2,
                dtype="float32",
                component_count=1,
                units="m",
                value_range=(0.0, 4.0),
                display_data=np.array([[0.0, 1.0], [2.0, 3.0]]),
                raw_data=np.array([[0.0, 1.0], [2.0, 3.0]]),
                frame_index=31,
                metadata={"output_kind": RenderVarOutputKind.SCALAR_DEPTH.value},
            ),
            RenderVarProbeRequest(
                viewport_id="viewport",
                pixel_x=1,
                pixel_y=1,
            ),
            {
                "raw_value": 3.0,
                "normalized_value": 0.75,
                "display_value": "3 m",
            },
        ),
        (
            RenderVarOutputFrame(
                render_product_path=_PRODUCT,
                output_id="normal",
                render_var_name="SmoothNormal",
                width=1,
                height=1,
                dtype="float32",
                component_count=3,
                display_data=np.array([[[-1.0, 0.0, 1.0]]]),
                raw_data=np.array([[[-1.0, 0.0, 1.0]]]),
                frame_index=32,
                metadata={"output_kind": RenderVarOutputKind.VECTOR_NORMAL.value},
            ),
            RenderVarProbeRequest(viewport_id="viewport"),
            {
                "raw_value": (-1.0, 0.0, 1.0),
                "normalized_value": None,
                "display_value": "(-1, 0, 1)",
            },
        ),
        (
            RenderVarOutputFrame(
                render_product_path=_PRODUCT,
                output_id="instance-id",
                render_var_name="InstanceId",
                width=2,
                height=1,
                dtype="uint32",
                component_count=1,
                display_data=np.array([[0, 7]], dtype=np.uint32),
                raw_data=np.array([[0, 7]], dtype=np.uint32),
                frame_index=33,
                metadata={
                    "output_kind": RenderVarOutputKind.CATEGORICAL_MASK.value,
                    "category_labels": {7: "Vehicle"},
                },
            ),
            RenderVarProbeRequest(
                viewport_id="viewport",
                pixel_x=1,
                pixel_y=0,
            ),
            {
                "raw_value": 7,
                "normalized_value": 7,
                "display_value": "ID 7: Vehicle",
                "category_id": 7,
                "category_label": "Vehicle",
            },
        ),
    ),
)
def test_render_var_probe_preserves_typed_scalar_vector_and_categorical_values(
    frame: RenderVarOutputFrame,
    probe: RenderVarProbeRequest,
    expected: dict[str, Any],
) -> None:
    adapter, _scene, backend = _adapter()
    active_request = RenderVarOutputRequest(
        viewport_id="viewport",
        render_product_path=frame.render_product_path,
        output_id=frame.output_id,
        render_var_name=frame.render_var_name,
        enable_probe=True,
    )
    adapter._render_var_output_requests["viewport"] = active_request
    adapter._latest_render_var_output_frames[
        ("viewport", frame.render_product_path, frame.output_id)
    ] = frame

    result = adapter.probe_render_var_output(probe)

    assert result.accepted
    for field, value in expected.items():
        assert getattr(result, field) == value
    assert result.frame_index == frame.frame_index
    assert backend.lookups == []


def test_render_var_probe_rejects_bounds_replaced_frames_and_nonfinite_data() -> None:
    adapter, _scene, backend = _adapter()
    warning = RenderVarWarning(code="source_warning", message="cached warning")
    data = np.array([[1.0, np.nan]], dtype=np.float32)
    frame = RenderVarOutputFrame(
        render_product_path=_PRODUCT,
        output_id="depth",
        render_var_name="DepthLinearized",
        width=2,
        height=1,
        dtype="float32",
        component_count=1,
        display_data=data,
        raw_data=data,
        frame_index=42,
        stale=True,
        warnings=(warning,),
        metadata={"output_kind": RenderVarOutputKind.SCALAR_DEPTH.value},
    )
    adapter._render_var_output_requests["viewport"] = RenderVarOutputRequest(
        viewport_id="viewport",
        render_product_path=_PRODUCT,
        output_id="depth",
        render_var_name="DepthLinearized",
        enable_probe=True,
    )
    adapter._latest_render_var_output_frames[
        ("viewport", _PRODUCT, "depth")
    ] = frame

    out_of_bounds = adapter.probe_render_var_output(
        RenderVarProbeRequest(viewport_id="viewport", pixel_x=2, pixel_y=0)
    )
    replaced = adapter.probe_render_var_output(
        RenderVarProbeRequest(
            viewport_id="viewport",
            pixel_x=0,
            pixel_y=0,
            frame_index=41,
        )
    )
    no_data = adapter.probe_render_var_output(
        RenderVarProbeRequest(viewport_id="viewport", pixel_x=1, pixel_y=0)
    )

    assert not out_of_bounds.accepted
    assert out_of_bounds.warning_code == "out_of_bounds"
    assert not replaced.accepted
    assert replaced.warning_code == "frame_replaced"
    assert replaced.frame_index == 42
    assert replaced.stale
    assert replaced.warnings == (warning,)
    assert not no_data.accepted
    assert no_data.warning_code == "no_data"
    assert no_data.frame_index == 42
    assert backend.lookups == []


def test_render_target_activation_uses_native_catalog_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _scene, backend = _adapter()
    _patch_native_catalog(monkeypatch, _native_snapshot())
    adapter._render_product_path = adapter._default_render_product_path
    adapter._active_render_product_common_path = None

    result = adapter.activate_render_target(render_product_path=_PRODUCT)

    assert result.accepted
    assert result.active_render_product_path == _PRODUCT
    assert adapter.get_active_render_product_path() == _PRODUCT
    assert backend.lookups == []


def test_render_settings_fail_closed_without_native_authoring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Render settings stay inert until native OVStage authoring exists.

    The former backing-USD render-setting authoring path was removed with the
    OpenUSD bridge; the native adapter must advertise an empty catalog and
    reject reads, validation, apply, and reset instead of falling back.
    """
    adapter, _scene, backend = _adapter()
    _patch_native_catalog(monkeypatch, _native_snapshot())

    catalog = adapter.list_render_settings(_PRODUCT)
    assert catalog.settings == ()
    assert catalog.active_render_product_path == _PRODUCT

    assert adapter.read_render_setting("rtpt:maxBounces") is None

    validation = adapter.validate_render_setting(
        "rtpt:maxBounces",
        7,
        render_product_path=_PRODUCT,
    )
    assert not validation.accepted
    assert validation.warning_code == "unsupported"

    applied = adapter.apply_render_setting(
        "rtpt:maxBounces",
        7,
        render_product_path=_PRODUCT,
    )
    assert not applied.accepted
    assert applied.warning_code == "unsupported"

    reset = adapter.reset_render_setting(
        "rtpt:maxBounces",
        render_product_path=_PRODUCT,
    )
    assert not reset.accepted
    assert reset.warning_code == "unsupported"
    assert backend.lookups == []


def test_ovstage_renderer_has_no_openusd_provider_dependency() -> None:
    source = Path(renderer_module.__file__).read_text(encoding="utf-8")
    assert "ovui_data_adapters.openusd" not in source
