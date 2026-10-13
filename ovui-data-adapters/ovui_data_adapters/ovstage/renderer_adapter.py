# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ovrtx renderer adapter for the registered ovstage provider."""

from __future__ import annotations

import inspect
import math
import os
import struct
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Deque, List, Optional

import numpy as np
from ovui_data_adapters.common import (
    AovAuthoringCatalog,
    AovOutputDescriptor,
    Command,
    GpuFrame,
    GpuFrameHandle,
    Matrix4d,
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
    RenderFrameMetadata,
    RenderFrameResult,
    RendererAdapter,
    RenderSettingApplyResult,
    RenderSettingDescriptor,
    RenderSettingRequirement,
    RenderSettingResetResult,
    RenderSettingsCatalog,
    RenderSettingsGroupDescriptor,
    RenderSettingsProviderDescriptor,
    RenderSettingValidationResult,
    RenderSettingValueConstraints,
    RenderSettingValueState,
    RenderSettingValueType,
    RenderSettingVisibility,
    RenderSettingWarning,
    RenderTargetActivationResult,
    RenderVarOutputCatalog,
    RenderVarOutputDescriptor,
    RenderVarOutputFrame,
    RenderVarOutputKind,
    RenderVarOutputRequest,
    RenderVarOutputRequestResult,
    RenderVarPresetKind,
    RenderVarProbeRequest,
    RenderVarProbeResult,
    RenderVarVisualizationPreset,
    RenderVarWarning,
    Vec3f,
    ZeroCopyState,
    omniui_headless_enabled,
    render_setting_values_semantically_equal,
)
from ovui_data_adapters.common._command import (
    history_consistent_interrupt,
    in_command_edge,
    interrupt_copy,
)
from ovui_data_adapters.common._ldr_overlap import (
    CameraSnapshot,
    LdrOverlapState,
    camera_state_differs,
)
from ovui_data_adapters.common.instrumentation import (
    RENDER_THREAD_SCOPE,
    get_instrumentation,
)
from ovui_data_adapters.common.ovrtx_import import import_ovrtx
from ovui_data_adapters.common.render_settings import (
    CAMERA_OWNER_SCOPE as _CAMERA_OWNER_SCOPE,
    RENDER_SETTINGS_OWNER_SCOPE as _RENDER_SETTINGS_OWNER_SCOPE,
    RenderSettingLifecycle,
    build_render_setting_builtin_spec_index,
    render_setting_owner_scope,
    render_setting_spec_owner_scope,
)
from ovui_data_adapters.ovstage._authoring import (
    MISSING as _NATIVE_MISSING,
)
from ovui_data_adapters.ovstage._authoring import (
    NativeValueDescriptor,
    NativeValueEditCommand,
)
from ovui_data_adapters.ovstage._catalog import native_catalog_snapshot
from ovui_data_adapters.ovstage._errors import raise_not_ready
from ovui_data_adapters.ovstage._native import (
    read_matrix_attribute,
    read_path_attribute_records,
    read_paths_attribute_records,
    read_token_attribute,
    resolve_token_id,
)
from ovui_data_adapters.ovstage._scene import (
    _kit_type_records,
    _load_population_module,
    _reconcile_native_write_floor,
)
from ovui_data_adapters.ovstage._stage_write import (
    StageWriteBatch,
    supports_native_stage_writes,
)
from ovui_data_adapters.ovstage.runtime_preflight import (
    OVRTX_RUNTIME_REQUIREMENT,
    validate_ovrtx_borrow_renderer,
    validate_runtime_requirement,
)
from ovui_data_adapters.ovstage.transform_adapter import OvstageTransformAdapter

os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")

_RUNTIME_ROOT_LOCAL_PATH = "/_OvuiRuntime"
_RUNTIME_LAYER_PRIM = "OvuiRuntime"
_RENDER_PRODUCT_LOCAL_PATH = f"{_RUNTIME_ROOT_LOCAL_PATH}/Render/Viewport"
_RENDER_CAMERA_LOCAL_PATH = f"{_RUNTIME_ROOT_LOCAL_PATH}/Render/Cameras/Main"
_LDR_VAR_LOCAL_PATH = f"{_RUNTIME_ROOT_LOCAL_PATH}/Render/Vars/LdrColor"
_LDR_VAR_NAME = "LdrColor"
#: ``_RENDER_SETTINGS_OWNER_SCOPE`` (imported above) is the owner scope of the
#: settings OVRTX reads from the global RenderSettings prim rather than from
#: the RenderProduct or the Camera.
#: OVRTX resolves the global render-settings prim in
#: ``RenderProductPrim::getStageRenderSettings`` as stage metadata
#: ``renderSettingsPrimPath`` first and otherwise ``kRenderRoot`` +
#: ``OmniverseGlobalRenderSettings``.  The metadata leg was measured DEAD in
#: the installed build, and a prim under the adapter's private ``/_OvuiRuntime``
#: prefix is never selected, so this literal path is the only owner identity
#: that reaches the renderer (OWNER-ROUTE, routes a/arel/c/e vs brefrs).
_RENDER_SETTINGS_OWNER_LOCAL_PATH = "/Render/OmniverseGlobalRenderSettings"
_RENDER_SETTINGS_OWNER_PRIM_TYPE = "RenderSettings"
_OVRTX_XFORM_ATTR = "omni:xform"
_DEFAULT_RESOLUTION = (1280, 720)
_MIN_DT = 1.0 / 300.0
_MAX_DT = 0.1
_RENDER_WORKER_WAIT_TIMEOUT_NS = 5_000_000
_RENDER_WORKER_RETRY_SECONDS = 0.001
_RENDER_WORKER_SHUTDOWN_TIMEOUT_SECONDS = 5.0
_RENDER_WORKER_THREAD_NAME = "ovui-ovrtx-render"
_VISIBILITY_INHERITED = "inherited"
_VISIBILITY_INVISIBLE = "invisible"
_VISIBILITY_TOKENS = frozenset({_VISIBILITY_INHERITED, _VISIBILITY_INVISIBLE})
_SELECTION_OUTLINE_GROUP_ID = 1
_SELECTION_OUTLINE_CLEAR_GROUP_ID = 0
_SELECTION_OUTLINE_COLOR = (0.0, 138.0 / 255.0, 249.0 / 255.0, 1.0)
_SELECTION_OUTLINE_FILL = (0.0, 138.0 / 255.0, 249.0 / 255.0, 0.0)
_PICK_HIT_VAR = "ovrtx_pick_hit"
_PICK_HIT_BUFFER_MAGIC = 0x56505448
_PICK_HIT_BUFFER_VERSION = 1
_PICK_HIT_HEADER = struct.Struct("<IIII")
_PICK_HIT_RECORD = struct.Struct("<QIIQdddffff")
_POINT_PICK_TOLERANCE_PX = 4.0
_PICK_CANCEL_EXPLICIT = "explicit"
_PICK_CANCEL_REPLACED = "replaced"

_LIVESTREAM_ENV_VAR = "OVGEAR_LIVESTREAM"
_TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes"})

_POINT_CLOUD_SOURCE_TOKEN = "pointcloud"
_POINT_CLOUD_SOURCE_ATTRS = (
    "omni:sensor:Core:outputFrameOfReference",
    "omni:sensor:WpmDmat:outputFrameOfReference",
    "outputFrameOfReference",
)
_POINT_CLOUD_CHANNEL_SPECS: dict[
    str,
    tuple[
        str,
        PointCloudChannelSemantic,
        str,
        int,
        str,
        Optional[tuple[float, float]],
        str,
        tuple[PointCloudColorMode, ...],
    ],
] = {
    "coordinates": (
        "Coordinates",
        PointCloudChannelSemantic.COORDINATES,
        "float32",
        3,
        "m_or_rad",
        None,
        "",
        (PointCloudColorMode.RANGE,),
    ),
    "counts": (
        "Counts",
        PointCloudChannelSemantic.COUNT,
        "int32",
        1,
        "points",
        None,
        "bounds_per_point_tensors",
        (),
    ),
    "intensity": (
        "Intensity",
        PointCloudChannelSemantic.INTENSITY,
        "float32",
        1,
        "unitless",
        (0.0, 1.0),
        "",
        (PointCloudColorMode.INTENSITY,),
    ),
    "flags": (
        "Flags",
        PointCloudChannelSemantic.FLAGS,
        "uint8",
        1,
        "bitfield",
        None,
        "valid_bit_0x40",
        (),
    ),
    "timeoffsetns": (
        "TimeOffsetNs",
        PointCloudChannelSemantic.TIME_OFFSET,
        "int32",
        1,
        "ns",
        None,
        "",
        (),
    ),
    "radialvelocityms": (
        "RadialVelocityMs",
        PointCloudChannelSemantic.RADIAL_VELOCITY,
        "float32",
        1,
        "m/s",
        None,
        "",
        (PointCloudColorMode.VELOCITY,),
    ),
    "velocity": (
        "Velocity",
        PointCloudChannelSemantic.VELOCITY,
        "float32",
        3,
        "m/s",
        None,
        "",
        (PointCloudColorMode.VELOCITY,),
    ),
    "rcs": (
        "RCS",
        PointCloudChannelSemantic.RCS,
        "float32",
        1,
        "dBsm",
        None,
        "",
        (PointCloudColorMode.RCS,),
    ),
    "materialid": (
        "MaterialId",
        PointCloudChannelSemantic.MATERIAL_ID,
        "uint32",
        1,
        "unitless",
        None,
        "",
        (PointCloudColorMode.MATERIAL_ID,),
    ),
    "objectid": (
        "ObjectId",
        PointCloudChannelSemantic.OBJECT_ID,
        "uint32",
        4,
        "unitless",
        None,
        "",
        (PointCloudColorMode.OBJECT_ID,),
    ),
}

_RENDER_VAR_LDR_TOKEN = "ldrcolor"
_RENDER_VAR_POINT_CLOUD_TOKEN = "pointcloud"
_RENDER_VAR_OUTPUT_SPECS: dict[str, dict[str, Any]] = {
    "hdrcolor": {
        "display_name": "HDR Color",
        "output_kind": RenderVarOutputKind.HDR_COLOR,
        "dtype": "float16",
        "component_count": 4,
        "units": "",
        "value_range": None,
        "color_space": "linear",
        "validity_semantics": "",
        "preset": RenderVarPresetKind.HDR_TONEMAP,
        "capabilities": ("render_var_display", "render_var_probe", "render_var_hdr"),
    },
    "diffusealbedosd": {
        "display_name": "Diffuse Albedo",
        "output_kind": RenderVarOutputKind.HDR_COLOR,
        "dtype": "float16",
        "component_count": 4,
        "units": "",
        "value_range": None,
        "color_space": "linear",
        "validity_semantics": "",
        "preset": RenderVarPresetKind.HDR_TONEMAP,
        "capabilities": ("render_var_display", "render_var_probe", "render_var_hdr"),
    },
    "depthsd": {
        "display_name": "Depth",
        "output_kind": RenderVarOutputKind.SCALAR_DEPTH,
        "dtype": "float32",
        "component_count": 1,
        "units": "unitless",
        "value_range": (0.0, 1.0),
        "color_space": "",
        "validity_semantics": "finite_depth",
        "preset": RenderVarPresetKind.SCALAR_GRAYSCALE,
        "capabilities": ("render_var_display", "render_var_probe", "render_var_scalar"),
    },
    "distancetocamerasd": {
        "display_name": "Distance to Camera",
        "output_kind": RenderVarOutputKind.SCALAR_DEPTH,
        "dtype": "float32",
        "component_count": 1,
        "units": "m",
        "value_range": None,
        "color_space": "",
        "validity_semantics": "finite_distance",
        "preset": RenderVarPresetKind.SCALAR_GRAYSCALE,
        "capabilities": ("render_var_display", "render_var_probe", "render_var_scalar"),
    },
    "distancetoimageplanesd": {
        "display_name": "Distance to Image Plane",
        "output_kind": RenderVarOutputKind.SCALAR_DEPTH,
        "dtype": "float32",
        "component_count": 1,
        "units": "m",
        "value_range": None,
        "color_space": "",
        "validity_semantics": "finite_distance",
        "preset": RenderVarPresetKind.SCALAR_GRAYSCALE,
        "capabilities": ("render_var_display", "render_var_probe", "render_var_scalar"),
    },
    "normalsd": {
        "display_name": "Normal",
        "output_kind": RenderVarOutputKind.VECTOR_NORMAL,
        "dtype": "float32",
        "component_count": 4,
        "units": "unit_vector",
        "value_range": (-1.0, 1.0),
        "color_space": "",
        "validity_semantics": "xyz_normal_w_validity",
        "preset": RenderVarPresetKind.VECTOR_SIGNED,
        "capabilities": ("render_var_display", "render_var_probe", "render_var_vector"),
    },
    "camera3dpositionsd": {
        "display_name": "Camera 3D Position",
        "output_kind": RenderVarOutputKind.VECTOR_NORMAL,
        "dtype": "float32",
        "component_count": 4,
        "units": "scene_units",
        "value_range": None,
        "color_space": "",
        "validity_semantics": "xyz_position_w_validity",
        "preset": RenderVarPresetKind.VECTOR_SIGNED,
        "capabilities": ("render_var_display", "render_var_probe", "render_var_vector"),
    },
    "semanticsegmentation": {
        "display_name": "Semantic Segmentation",
        "output_kind": RenderVarOutputKind.CATEGORICAL_MASK,
        "dtype": "uint32",
        "component_count": 1,
        "units": "id",
        "value_range": None,
        "color_space": "",
        "validity_semantics": "zero_or_id",
        "preset": RenderVarPresetKind.CATEGORICAL_PALETTE,
        "capabilities": (
            "render_var_display",
            "render_var_probe",
            "render_var_categorical",
        ),
    },
    "semanticidmap": {
        "display_name": "Semantic ID Map",
        "output_kind": RenderVarOutputKind.METADATA_MAP,
        "dtype": "uint8",
        "component_count": 1,
        "units": "",
        "value_range": None,
        "color_space": "",
        "validity_semantics": "semantic_id_to_label_map",
        "preset": RenderVarPresetKind.CATEGORICAL_PALETTE,
        "capabilities": (
            "render_var_display",
            "render_var_probe",
            "render_var_categorical",
            "render_var_metadata",
        ),
    },
}

_AOV_AUTHORING_OUTPUTS: tuple[AovOutputDescriptor, ...] = (
    AovOutputDescriptor(
        output_id="normal",
        label="Normal — NormalSD",
        source_name="NormalSD",
        render_var_name="Normal",
        compatible_render_modes=("RealTimePathTracing",),
    ),
    AovOutputDescriptor(
        output_id="diffuse_albedo",
        label="Diffuse Albedo — DiffuseAlbedoSD",
        source_name="DiffuseAlbedoSD",
        render_var_name="DiffuseAlbedo",
        compatible_render_modes=("RealTimePathTracing",),
    ),
    AovOutputDescriptor(
        output_id="distance_to_camera",
        label="Distance to Camera — DistanceToCameraSD",
        source_name="DistanceToCameraSD",
        render_var_name="DistanceToCamera",
        compatible_render_modes=("RealTimePathTracing",),
    ),
    AovOutputDescriptor(
        output_id="distance_to_image_plane",
        label="Distance to Image Plane — DistanceToImagePlaneSD",
        source_name="DistanceToImagePlaneSD",
        render_var_name="DistanceToImagePlane",
        compatible_render_modes=("RealTimePathTracing",),
    ),
    AovOutputDescriptor(
        output_id="camera_3d_position",
        label="Camera 3D Position — Camera3dPositionSD",
        source_name="Camera3dPositionSD",
        render_var_name="Camera3dPosition",
        compatible_render_modes=("RealTimePathTracing",),
    ),
    AovOutputDescriptor(
        output_id="semantic_segmentation",
        label="Semantic Segmentation — SemanticSegmentation",
        source_name="SemanticSegmentation",
        render_var_name="SemanticSegmentation",
        compatible_render_modes=("RealTimePathTracing",),
        note="Requires authored semantics",
    ),
    AovOutputDescriptor(
        output_id="hdr_color",
        label="HDR Color — HdrColor",
        source_name="HdrColor",
        render_var_name="HdrColor",
        compatible_render_modes=(
            "RealTimePathTracing",
            "PathTracing",
            "Minimal",
        ),
    ),
)
_AOV_RENDER_MODES: tuple[tuple[str, str], ...] = (
    ("Real-Time 2.0", "RealTimePathTracing"),
    ("Interactive (Path Tracing)", "PathTracing"),
    ("Minimal", "Minimal"),
)


def _catalog_paths(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, (tuple, list)):
        values = tuple(value)
    else:
        values = ()
    result: list[str] = []
    for item in values:
        path = str(item)
        if (
            path.startswith("/")
            and path != "/"
            and not path.endswith("/")
            and "//" not in path
            and all(part not in {"", ".", ".."} for part in path[1:].split("/"))
            and path not in result
        ):
            result.append(path)
    return tuple(result)


def _first_catalog_path(value: Any) -> str | None:
    paths = _catalog_paths(value)
    return paths[0] if paths else None


def _catalog_string_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(str(item) for item in value)


def _point_cloud_channel_descriptor(name: str) -> PointCloudChannelDescriptor | None:
    spec = _POINT_CLOUD_CHANNEL_SPECS.get(_source_token_key(name))
    if spec is None:
        return None
    (
        display_name,
        semantic,
        dtype,
        component_count,
        units,
        value_range,
        validity_semantics,
        color_modes,
    ) = spec
    return PointCloudChannelDescriptor(
        name=display_name,
        semantic=semantic,
        dtype=dtype,
        component_count=component_count,
        units=units,
        value_range=value_range,
        validity_semantics=validity_semantics,
        color_modes=color_modes,
    )


def _native_catalog_revision(snapshot: Any) -> str:
    return (
        f"{snapshot.ordinal}:{snapshot.topology_version}:"
        f"{snapshot.topology_revision}"
    )


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY_ENV_VALUES


_LDR_OVERLAP_ENV_VAR = "OVGEAR_LDR_OVERLAP"


def _ldr_overlap_env_enabled() -> bool:
    return os.environ.get(_LDR_OVERLAP_ENV_VAR, "1").strip().lower() not in (
        "0", "false", "no",
    )


def _livestream_env_enabled() -> bool:
    """Return whether the legacy windowed viewport stream was requested."""
    return _env_truthy(_LIVESTREAM_ENV_VAR)


# ---------------------------------------------------------------------------
# OVStage-NATIVE public RenderProduct settings.
#
# The accepted render-settings contract (native-exact builtin value types,
# transactional apply/reset with truthful failure, exact undo/redo history,
# and no silent store divergence) is re-seated here on the OVStage-native
# authoring seams: values live in native columns, reads go through the native
# property adapter, and writes go through ``_authoring`` value edits with
# compensating rollback.  There is exactly ONE store now — the legacy
# backing-USD synchronization/recovery ledger class of divergence no longer
# exists.
# ---------------------------------------------------------------------------

_RENDER_SETTINGS_PROVIDER_ID = ""
_RENDER_SETTINGS_PROVIDER_LABEL = ""
_RENDER_SETTINGS_PUBLIC_NAMESPACES: tuple[str, ...] = ()
_RENDER_SETTINGS_GROUP_FALLBACK = ""
_RENDER_SETTINGS_GROUP_LABEL_FALLBACK = ""
_RENDER_SETTINGS_BUILTIN_SPECS: tuple[dict[str, Any], ...] = ()
#: ``attr_name`` -> spec index over the tuple above. The catalog is
#: rebuilt per request and the declared setting surface is large, so a
#: linear scan per attribute is quadratic; the index is rebuilt only
#: when a schema is installed.
_RENDER_SETTINGS_BUILTIN_SPEC_INDEX: dict[str, dict[str, Any]] = {}


def configure_render_settings_schema(
    *,
    provider_id: str,
    provider_label: str,
    public_namespaces: tuple[str, ...],
    group_fallback: str,
    group_label_fallback: str,
    builtin_specs: tuple[dict[str, Any], ...],
    **_unused: Any,
) -> None:
    """Install an opaque optional renderer-property schema."""

    global _RENDER_SETTINGS_PROVIDER_ID
    global _RENDER_SETTINGS_PROVIDER_LABEL
    global _RENDER_SETTINGS_PUBLIC_NAMESPACES
    global _RENDER_SETTINGS_GROUP_FALLBACK
    global _RENDER_SETTINGS_GROUP_LABEL_FALLBACK
    global _RENDER_SETTINGS_BUILTIN_SPECS
    global _RENDER_SETTINGS_BUILTIN_SPEC_INDEX
    _RENDER_SETTINGS_PROVIDER_ID = str(provider_id)
    _RENDER_SETTINGS_PROVIDER_LABEL = str(provider_label)
    _RENDER_SETTINGS_PUBLIC_NAMESPACES = tuple(public_namespaces)
    _RENDER_SETTINGS_GROUP_FALLBACK = str(group_fallback)
    _RENDER_SETTINGS_GROUP_LABEL_FALLBACK = str(group_label_fallback)
    _RENDER_SETTINGS_BUILTIN_SPECS = tuple(dict(spec) for spec in builtin_specs)
    _RENDER_SETTINGS_BUILTIN_SPEC_INDEX = build_render_setting_builtin_spec_index(
        _RENDER_SETTINGS_BUILTIN_SPECS
    )

# DLPack dtype codes (matching ``_authoring``).
_RS_DLPACK_INT = 0
_RS_DLPACK_UINT = 1
_RS_DLPACK_FLOAT = 2
_RS_DLPACK_BOOL = 6
_RS_SEMANTIC_NONE = 0
_RS_SEMANTIC_ASSET_STRING = 1
_RS_SEMANTIC_TOKEN_ID = 2
_RS_SEMANTIC_PATH_EXPRESSION_STRING = 3
_RS_SEMANTIC_COLOR = 8
_RS_SEMANTIC_STRING = 13
_RS_STRING_SEMANTICS = frozenset(
    {
        _RS_SEMANTIC_ASSET_STRING,
        _RS_SEMANTIC_PATH_EXPRESSION_STRING,
        _RS_SEMANTIC_STRING,
    }
)

#: Authoritative native column encoding per builtin source spelling: the
#: dtype/semantic an ABSENT column is created with (runtime-verified 2026-07-16).
_RENDER_SETTING_NATIVE_TEMPLATES: dict[str, tuple[tuple[int, int, int], int]] = {
    "bool": ((_RS_DLPACK_BOOL, 8, 1), _RS_SEMANTIC_NONE),
    "uint": ((_RS_DLPACK_UINT, 32, 1), _RS_SEMANTIC_NONE),
    "int": ((_RS_DLPACK_INT, 32, 1), _RS_SEMANTIC_NONE),
    "float": ((_RS_DLPACK_FLOAT, 32, 1), _RS_SEMANTIC_NONE),
    "token": ((_RS_DLPACK_UINT, 64, 1), _RS_SEMANTIC_TOKEN_ID),
    "string": ((_RS_DLPACK_UINT, 64, 1), _RS_SEMANTIC_TOKEN_ID),
    # The live population encodes color-role columns with the COLOR
    # semantic; plain float3 spellings carry no semantic.
    "color3f": ((_RS_DLPACK_FLOAT, 32, 3), _RS_SEMANTIC_COLOR),
    "float3": ((_RS_DLPACK_FLOAT, 32, 3), _RS_SEMANTIC_NONE),
}


@dataclass(frozen=True)
class _RenderSettingNativeRecord:
    """One exact scalar native column consumed only by renderer settings."""

    name: str
    type_name: str
    dtype: tuple[int, int, int]
    semantic: int
    native_is_array: bool
    is_array: bool
    value: Any


class _RenderSettingsNativeView:
    """One-path native renderer-setting values and descriptors.

    The general Property Inspector deliberately hides ``omni:`` implementation
    columns.  Renderer settings have a separately configured, authoritative
    schema and therefore read those exact names through a narrow native query
    without changing general property visibility.
    """

    def __init__(
        self,
        exact: Mapping[str, _RenderSettingNativeRecord],
    ) -> None:
        self._attribute_records = dict(exact)
        self._exact = dict(exact)

    def is_valid(self) -> bool:
        return True

    def get_attribute_names(self) -> list[str]:
        return list(self._attribute_records)

    def get_value(self, attr_name: str) -> Any:
        record = self._exact.get(str(attr_name))
        if record is None:
            raise KeyError(str(attr_name))
        return record.value


def _render_setting_exact_native_records(
    stage: Any,
    product_path: str,
    attr_names: Sequence[str],
) -> dict[str, _RenderSettingNativeRecord]:
    """Copy configured renderer columns from one prim in a single read.

    ``Stage.read_attributes`` takes a token SEQUENCE, so the whole requested
    set costs one query and one read rather than one of each per name. Every
    returned group names its own attribute token, so the per-column decoding
    and the "exactly one match on this prim, or nothing" rule are unchanged;
    a name with no match is simply absent from the result.
    """

    requested = tuple(
        dict.fromkeys(str(name) for name in attr_names if str(name))
    )
    if not requested:
        return {}
    copied = read_path_attribute_records(
        stage,
        str(product_path),
        requested,
    )
    exact: dict[str, _RenderSettingNativeRecord] = {}
    for attr_name, record in copied.items():
        logical_is_array = (
            record.native_is_array
            and record.semantic not in _RS_STRING_SEMANTICS
        )
        exact[attr_name] = _RenderSettingNativeRecord(
            name=record.name,
            type_name=_render_setting_native_type_name(
                record.dtype,
                record.semantic,
                logical_is_array,
            ),
            dtype=record.dtype,
            semantic=record.semantic,
            native_is_array=record.native_is_array,
            is_array=logical_is_array,
            value=record.value,
        )
    return exact


def _render_setting_builtin_spec(attr_name: str) -> dict[str, Any] | None:
    return _RENDER_SETTINGS_BUILTIN_SPEC_INDEX.get(attr_name)


#: Shared with the OpenUSD adapter: one classification, one fallback.
_render_setting_owner_scope = render_setting_owner_scope


def _render_setting_spec_owner_scope(attr_name: str) -> str:
    """Declared owner scope for one builtin attribute name."""

    return render_setting_spec_owner_scope(
        _RENDER_SETTINGS_BUILTIN_SPEC_INDEX, attr_name
    )


def _render_setting_unsupported_owner(attr_name: str) -> str:
    """Reason this build cannot author a given owner scope natively.

    The native BORROW transport addresses the active RenderProduct, the
    adapter's private runtime Camera and the private global RenderSettings
    prim.  Any other declared owner has no resolved native owner here, so it
    reports that plainly instead of being written onto the product where the
    renderer would never read it.
    """

    owner_scope = _render_setting_spec_owner_scope(attr_name)
    if owner_scope in (
        "RenderProduct",
        _CAMERA_OWNER_SCOPE,
        _RENDER_SETTINGS_OWNER_SCOPE,
    ):
        return ""
    return (
        f"The installed build owns this setting on a {owner_scope} prim, "
        "which this runtime does not provide yet"
    )


def _render_setting_builtin_metadata(spec: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in spec.items():
        if key in {"attr_name", "usd_type"}:
            continue
        if isinstance(value, (RenderSettingValueType, RenderSettingRequirement)):
            metadata[key] = value.value
        else:
            metadata[key] = value
    return metadata


def _render_setting_python_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, np.ndarray):
        return _render_setting_python_value(value.tolist())
    try:
        return tuple(_render_setting_python_value(item) for item in value)
    except TypeError:
        return value


def _render_setting_public_namespace(attr_name: str) -> tuple[str, str] | None:
    """Split a public setting name into its declared namespace and remainder.

    The configured namespaces are a mix of true prefixes (``omni:rtx:``,
    ``exposure:``) and whole attribute names (``renderingColorSpace``,
    ``dataWindowNDC``).  A whole-name namespace matches exactly and leaves an
    empty remainder, which is what the OpenUSD provider already produces for
    the same schema; requiring a strictly longer name silently dropped those
    settings from this provider's catalog entirely.
    """

    for namespace in _RENDER_SETTINGS_PUBLIC_NAMESPACES:
        if attr_name.startswith(namespace):
            return namespace, attr_name[len(namespace):]
    return None


def _render_setting_display_name(value: str) -> str:
    text = str(value or "").split(":")[-1]
    parts: list[str] = []
    token = ""
    for char in text:
        if char.isupper() and token and not token[-1].isupper():
            parts.append(token)
            token = char
        else:
            token += char
    if token:
        parts.append(token)
    return " ".join(part.capitalize() for part in parts) if parts else text


def _render_setting_float_range(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        low = float(value.get("min"))
        high = float(value.get("max"))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(low) and math.isfinite(high)) or low > high:
        return None
    return (low, high)


def _render_setting_allowed_values(metadata: dict[str, Any]) -> tuple[Any, ...]:
    allowed = metadata.get("allowed_values", metadata.get("allowedValues"))
    if isinstance(allowed, (tuple, list)):
        return tuple(_render_setting_python_value(item) for item in allowed)
    if isinstance(allowed, str) and allowed:
        return (allowed,)
    return ()


def _render_setting_component_count(usd_type: str, metadata: dict[str, Any]) -> int:
    explicit = metadata.get("component_count", metadata.get("componentCount"))
    if explicit is not None:
        try:
            count = int(explicit)
            if count > 0:
                return count
        except (TypeError, ValueError):
            pass
    key = _source_token_key(usd_type)
    return next((size for size in (2, 3, 4) if key.endswith(str(size))), 1)


def _render_setting_value_type(
    usd_type: str,
    metadata: dict[str, Any],
) -> RenderSettingValueType:
    explicit = metadata.get("value_type", metadata.get("valueType"))
    if explicit:
        try:
            return RenderSettingValueType(str(explicit))
        except ValueError:
            return RenderSettingValueType.UNKNOWN
    key = str(usd_type or "").lower()
    if key == "bool":
        return RenderSettingValueType.BOOL
    if key in {"int", "uint", "int64", "uint64"}:
        return RenderSettingValueType.INT
    if key in {"float", "double", "half"}:
        return RenderSettingValueType.FLOAT
    if key == "string":
        return RenderSettingValueType.STRING
    if key == "token":
        return (
            RenderSettingValueType.ENUM
            if _render_setting_allowed_values(metadata)
            else RenderSettingValueType.TOKEN
        )
    if key.startswith("color"):
        return RenderSettingValueType.COLOR
    if key in {
        "float2",
        "double2",
        "half2",
        "float3",
        "double3",
        "half3",
        "float4",
        "double4",
        "half4",
        "int2",
        "int3",
        "int4",
        "vector3f",
        "vector3d",
        "vector3h",
        "normal3f",
        "normal3d",
        "normal3h",
        "point3f",
        "point3d",
        "point3h",
    }:
        return RenderSettingValueType.VECTOR
    return RenderSettingValueType.UNKNOWN


def _render_setting_native_type_name(
    dtype: tuple[int, int, int],
    semantic: int,
    is_array: bool,
) -> str:
    """Infer the public scalar type carried by one exact native column."""

    code, bits, lanes = (int(value) for value in dtype)
    if bool(is_array):
        return "array"
    if semantic in _RS_STRING_SEMANTICS:
        return "string"
    if semantic == _RS_SEMANTIC_TOKEN_ID:
        return "token"
    if code == _RS_DLPACK_BOOL and lanes == 1:
        return "bool"
    if code in (_RS_DLPACK_INT, _RS_DLPACK_UINT):
        return "int" if lanes == 1 else f"int{lanes}"
    if code != _RS_DLPACK_FLOAT:
        return "unknown"
    precision = {16: "half", 64: "double"}.get(bits, "float")
    if semantic == _RS_SEMANTIC_COLOR and lanes in (3, 4):
        suffix = {16: "h", 64: "d"}.get(bits, "f")
        return f"color{lanes}{suffix}"
    return precision if lanes == 1 else f"{precision}{lanes}"


def _render_setting_constraints(
    usd_type: str,
    metadata: dict[str, Any],
) -> RenderSettingValueConstraints:
    hard = (
        _render_setting_float_range(metadata.get("range"))
        or _render_setting_float_range(metadata.get("hard_range"))
        or _render_setting_float_range(metadata.get("hardRange"))
    )
    soft = (
        _render_setting_float_range(metadata.get("soft_range"))
        or _render_setting_float_range(metadata.get("softRange"))
        or hard
    )
    return RenderSettingValueConstraints(
        soft_range=soft,
        hard_range=hard,
        allowed_values=_render_setting_allowed_values(metadata),
        component_count=_render_setting_component_count(usd_type, metadata),
        pattern=str(metadata.get("pattern") or ""),
        options=metadata.get("options") if isinstance(metadata.get("options"), dict) else {},
    )


def _render_setting_requirement(metadata: dict[str, Any]) -> RenderSettingRequirement:
    try:
        return RenderSettingRequirement(
            str(metadata.get("requirement", RenderSettingRequirement.NONE.value))
        )
    except ValueError:
        return RenderSettingRequirement.NONE


def _render_setting_visibility(metadata: dict[str, Any]) -> RenderSettingVisibility:
    try:
        return RenderSettingVisibility(
            str(metadata.get("visibility", RenderSettingVisibility.PUBLIC.value))
        )
    except ValueError:
        return RenderSettingVisibility.PUBLIC


def _render_setting_for_id(
    catalog: RenderSettingsCatalog,
    setting_id: str,
) -> RenderSettingDescriptor | None:
    requested = str(setting_id or "")
    if not requested:
        return None
    direct = catalog.setting(requested)
    if direct is not None:
        return direct
    return next(
        (
            setting
            for setting in catalog.settings
            if requested in {setting.property_name, f"{setting.namespace}{setting.property_name}"}
        ),
        None,
    )


def _render_setting_coerce_value(
    descriptor: RenderSettingDescriptor,
    value: Any,
) -> Any:
    value_type = descriptor.value_type
    if value_type is RenderSettingValueType.BOOL:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in {0, 1}:
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        raise ValueError("Expected a boolean value.")
    if value_type is RenderSettingValueType.INT:
        if isinstance(value, bool):
            raise ValueError("Expected an integer value.")
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value) or not value.is_integer():
                raise ValueError("Expected an integer value.")
            return int(value)
        if isinstance(value, str):
            return int(value.strip())
        raise ValueError("Expected an integer value.")
    if value_type is RenderSettingValueType.FLOAT:
        if isinstance(value, bool):
            raise ValueError("Expected a finite numeric value.")
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Expected a finite numeric value.")
        return result
    if value_type in {
        RenderSettingValueType.ENUM,
        RenderSettingValueType.STRING,
        RenderSettingValueType.TOKEN,
        RenderSettingValueType.PATH,
    }:
        return str(value)
    if value_type in {RenderSettingValueType.VECTOR, RenderSettingValueType.COLOR}:
        if isinstance(value, (str, bytes)):
            raise ValueError("Expected a numeric sequence.")
        try:
            items = tuple(value)
        except TypeError as exc:
            raise ValueError("Expected a numeric sequence.") from exc
        expected = descriptor.constraints.component_count
        if len(items) != expected:
            raise ValueError(f"Expected {expected} components; got {len(items)}.")
        result = tuple(float(item) for item in items)
        if not all(math.isfinite(item) for item in result):
            raise ValueError("Expected finite numeric components.")
        return result
    raise ValueError("Unsupported render setting value type.")


def _render_setting_value_within_constraints(
    descriptor: RenderSettingDescriptor,
    value: Any,
) -> tuple[bool, str, str]:
    constraints = descriptor.constraints
    if constraints.soft_range is not None and constraints.hard_range is not None:
        soft_min, soft_max = constraints.soft_range
        hard_min, hard_max = constraints.hard_range
        if not (hard_min <= soft_min <= soft_max <= hard_max):
            return (
                False,
                "Render setting metadata has a soft range outside its hard range.",
                "invalid_constraints",
            )
    if constraints.allowed_values:
        allowed = tuple(_render_setting_python_value(item) for item in constraints.allowed_values)
        if value not in allowed and str(value) not in {str(item) for item in allowed}:
            return (
                False,
                f"Value {value!r} is not one of the allowed values.",
                "value_not_allowed",
            )
    numeric_values: tuple[float, ...]
    if isinstance(value, bool):
        numeric_values = ()
    elif isinstance(value, (int, float)):
        numeric_values = (float(value),)
    elif isinstance(value, tuple) and all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
    ):
        numeric_values = tuple(float(item) for item in value)
    else:
        numeric_values = ()
    if constraints.hard_range is not None:
        lo, hi = constraints.hard_range
        if any(item < lo or item > hi for item in numeric_values):
            return (
                False,
                f"Value {value!r} is outside the allowed range {lo:g}..{hi:g}.",
                "value_out_of_range",
            )
    return True, "", ""


def _render_setting_failure_detail(error: BaseException) -> str:
    detail = str(error)
    notes = tuple(str(note) for note in getattr(error, "__notes__", ()) if note)
    if notes:
        detail = f"{detail}; {'; '.join(notes)}"
    return detail


def _render_setting_native_role_conflict(spec: dict[str, Any], record: Any) -> str:
    """Concrete reason when a live native column sits outside the builtin role.

    Mirrors the accepted classifier on the NATIVE record: the 32-bit integer
    role admits scalar int32/uint32 columns (a pre-existing signed variant
    stays editable with its EFFECTIVE dtype), the float role scalar float32,
    the token role a scalar interned-token column, and the three-lane float
    role a float32 triple. Anything else (e.g. a float32 column under an
    integer builtin) is a role escape that must fail truthfully rather than
    be silently written."""

    expected_key = str(spec.get("usd_type") or "").lower()
    code, bits, lanes = (int(item) for item in record.dtype)
    semantic = int(getattr(record, "semantic", 0) or 0)
    is_array = bool(getattr(record, "native_is_array", False))
    if expected_key in ("int", "uint"):
        compatible = (
            code in (_RS_DLPACK_INT, _RS_DLPACK_UINT)
            and bits == 32
            and lanes == 1
            and semantic == _RS_SEMANTIC_NONE
            and not is_array
        )
    elif expected_key == "float":
        compatible = (
            code == _RS_DLPACK_FLOAT
            and bits == 32
            and lanes == 1
            and semantic == _RS_SEMANTIC_NONE
            and not is_array
        )
    elif expected_key in ("token", "string"):
        compatible = semantic == _RS_SEMANTIC_TOKEN_ID and not is_array
    elif expected_key in ("color3f", "float3", "vector3f", "normal3f", "point3f"):
        # Role-authoritative, not lane-count-shaped: the color role accepts
        # the COLOR semantic the live population authors (plus a bare
        # semantic-free float3 column), while vector/normal/point and plain
        # float3 declarations must NOT consume a color-role column merely
        # because the lane count matches.
        if expected_key == "color3f":
            allowed_semantics = (_RS_SEMANTIC_NONE, _RS_SEMANTIC_COLOR)
        else:
            allowed_semantics = (_RS_SEMANTIC_NONE,)
        compatible = (
            code == _RS_DLPACK_FLOAT
            and bits == 32
            and lanes == 3
            and semantic in allowed_semantics
            and not is_array
        )
    else:
        return ""
    if compatible:
        return ""
    return (
        f"native column for {str(spec.get('attr_name') or '')!r} has dtype "
        f"(code={code}, bits={bits}, lanes={lanes}, semantic={semantic}, "
        f"array={is_array}), outside the builtin's proven native role for "
        f"{expected_key!r}"
    )


def _render_setting_native_descriptor(
    attr_name: str,
    spec: dict[str, Any] | None,
    record: Any | None,
) -> NativeValueDescriptor:
    """Native value descriptor for one setting write.

    A pre-existing column keeps its EFFECTIVE dtype/semantic (no variant
    conversion — a signed int32 builtin stays int32); an absent builtin
    column is created with the authoritative runtime encoding."""

    if record is not None:
        return NativeValueDescriptor(
            name=str(attr_name),
            dtype=tuple(int(item) for item in record.dtype),
            semantic=int(getattr(record, "semantic", 0) or 0),
            native_is_array=bool(getattr(record, "native_is_array", False)),
            logical_is_array=bool(getattr(record, "is_array", False)),
        )
    template = _RENDER_SETTING_NATIVE_TEMPLATES.get(
        str((spec or {}).get("usd_type") or "").lower()
    )
    if template is None:
        raise RuntimeError(
            f"render setting {attr_name!r} has no authoritative native encoding"
        )
    dtype, semantic = template
    return NativeValueDescriptor(
        name=str(attr_name),
        dtype=dtype,
        semantic=semantic,
        native_is_array=False,
        logical_is_array=False,
    )


def _render_setting_native_write_value(
    descriptor: RenderSettingDescriptor,
    normalized_value: Any,
) -> Any:
    if descriptor.value_type in {
        RenderSettingValueType.VECTOR,
        RenderSettingValueType.COLOR,
    }:
        return tuple(float(item) for item in normalized_value)
    if descriptor.value_type in {
        RenderSettingValueType.ENUM,
        RenderSettingValueType.STRING,
        RenderSettingValueType.TOKEN,
        RenderSettingValueType.PATH,
    }:
        return str(normalized_value)
    return normalized_value


def _render_setting_values_equal(old_value: Any, new_value: Any) -> bool:
    """Semantic equality between a live native value and a write value.

    The shared no-op boundary comparison (one definition for the native
    adapter and the bindings layer), with the native MISSING sentinel —
    an authorship transition — never equal to a concrete value."""

    return render_setting_values_semantically_equal(
        old_value, new_value, missing=_NATIVE_MISSING
    )


def _render_setting_builtin_descriptor(
    product_path: str,
    spec: dict[str, Any],
    *,
    current_value: Any,
    authored: bool,
    record: Any | None,
    owner_unavailable_reason: str = "",
) -> RenderSettingDescriptor | None:
    attr_name = str(spec.get("attr_name") or "")
    namespace_parts = _render_setting_public_namespace(attr_name)
    if namespace_parts is None:
        return None
    namespace, property_name = namespace_parts
    unsupported_owner = owner_unavailable_reason or _render_setting_unsupported_owner(
        attr_name
    )
    metadata = _render_setting_builtin_metadata(spec)
    usd_type = str(spec.get("usd_type") or "")
    value_type = _render_setting_value_type(usd_type, metadata)
    default_value = _render_setting_python_value(metadata.get("default"))
    has_default = "default" in metadata
    effective_value = current_value if authored else default_value
    descriptor_metadata: dict[str, Any] = {
        "usd_type": usd_type,
        "attr_name": attr_name,
        "render_product_path": product_path,
        "builtin": True,
        # The owner scope must survive onto the descriptor: apply/reset
        # resolve the owner prim from it, and a missing key silently means
        # "RenderProduct", which is exactly where a globally owned or
        # camera-owned value must never be written.
        "owner_scope": _render_setting_spec_owner_scope(attr_name),
    }
    if record is not None:
        descriptor_metadata["native_dtype"] = tuple(
            int(item) for item in record.dtype
        )
        descriptor_metadata["native_semantic"] = int(
            getattr(record, "semantic", 0) or 0
        )
    state = RenderSettingValueState(
        current_value=effective_value,
        default_value=default_value,
        has_default=has_default,
        authored=authored,
        inherited=bool(not authored and has_default),
        metadata=dict(descriptor_metadata),
    )
    return RenderSettingDescriptor(
        setting_id=f"{product_path}:{attr_name}",
        label=str(metadata.get("label") or _render_setting_display_name(attr_name)),
        provider_id=_RENDER_SETTINGS_PROVIDER_ID,
        group_id=str(
            metadata.get("group_id") or metadata.get("group") or _RENDER_SETTINGS_GROUP_FALLBACK
        ),
        namespace=namespace,
        property_name=property_name,
        description=str(metadata.get("description") or ""),
        value_type=value_type,
        constraints=_render_setting_constraints(usd_type, metadata),
        units=str(metadata.get("units") or ""),
        default_value=default_value,
        has_default=has_default,
        requirement=_render_setting_requirement(metadata),
        visibility=_render_setting_visibility(metadata),
        order=float(metadata.get("order", 1000.0)),
        enabled=not unsupported_owner,
        disabled_reason=unsupported_owner,
        value_state=state,
        revision_token=f"{product_path}:{attr_name}:{effective_value!r}:{authored}",
        metadata=descriptor_metadata,
    )


def _render_setting_record_descriptor(
    product_path: str,
    record: Any,
    current_value: Any,
) -> RenderSettingDescriptor | None:
    """Descriptor for a generic public native column (non-builtin).

    The value type is derived from the LIVE native record; columns whose
    native encoding has no supported control shape stay truthfully disabled
    with a concrete reason."""

    attr_name = str(record.name)
    namespace_parts = _render_setting_public_namespace(attr_name)
    if namespace_parts is None:
        return None
    namespace, property_name = namespace_parts
    usd_type = str(getattr(record, "type_name", "") or "")
    value_type = _render_setting_value_type(usd_type, {})
    warnings: list[RenderSettingWarning] = []
    enabled = True
    disabled_reason = ""
    if value_type is RenderSettingValueType.UNKNOWN or bool(
        getattr(record, "native_is_array", False)
    ):
        value_type = (
            RenderSettingValueType.UNKNOWN
            if value_type is RenderSettingValueType.UNKNOWN
            else value_type
        )
        warning = RenderSettingWarning(
            code="unknown_value_type",
            message=(
                f"RenderProduct setting {attr_name!r} has an unsupported "
                f"native type {usd_type!r}."
            ),
        )
        warnings.append(warning)
        enabled = False
        disabled_reason = warning.message
    descriptor_metadata: dict[str, Any] = {
        "usd_type": usd_type,
        "attr_name": attr_name,
        "render_product_path": product_path,
        "native_dtype": tuple(int(item) for item in record.dtype),
        "native_semantic": int(getattr(record, "semantic", 0) or 0),
    }
    state = RenderSettingValueState(
        current_value=current_value,
        default_value=None,
        has_default=False,
        authored=True,
        inherited=False,
        invalid=value_type is RenderSettingValueType.UNKNOWN,
        disabled=bool(not enabled or disabled_reason),
        disabled_reason=disabled_reason,
        warnings=tuple(warnings),
        metadata=dict(descriptor_metadata),
    )
    return RenderSettingDescriptor(
        setting_id=f"{product_path}:{attr_name}",
        label=_render_setting_display_name(attr_name),
        provider_id=_RENDER_SETTINGS_PROVIDER_ID,
        group_id=_RENDER_SETTINGS_GROUP_FALLBACK,
        namespace=namespace,
        property_name=property_name,
        value_type=value_type,
        constraints=_render_setting_constraints(usd_type, {}),
        default_value=None,
        has_default=False,
        requirement=RenderSettingRequirement.NONE,
        visibility=RenderSettingVisibility.PUBLIC,
        order=1000.0,
        enabled=enabled,
        disabled_reason=disabled_reason,
        value_state=state,
        warnings=tuple(warnings),
        revision_token=f"{product_path}:{attr_name}:{current_value!r}:True",
        metadata=descriptor_metadata,
    )


def _render_settings_group_descriptors(
    settings: list[RenderSettingDescriptor],
    metadata_by_group: dict[str, dict[str, Any]],
) -> tuple[RenderSettingsGroupDescriptor, ...]:
    groups: list[RenderSettingsGroupDescriptor] = []
    for group_id in sorted({setting.group_id for setting in settings}):
        metadata = metadata_by_group.get(group_id, {})
        groups.append(
            RenderSettingsGroupDescriptor(
                group_id=group_id,
                label=str(
                    metadata.get("group_label")
                    or metadata.get("groupLabel")
                    or (
                        _RENDER_SETTINGS_GROUP_LABEL_FALLBACK
                        if group_id == _RENDER_SETTINGS_GROUP_FALLBACK
                        else _render_setting_display_name(group_id)
                    )
                ),
                provider_id=_RENDER_SETTINGS_PROVIDER_ID,
                order=float(
                    metadata.get(
                        "group_order",
                        metadata.get("groupOrder", 1000.0),
                    )
                ),
                collapsed_default=bool(
                    metadata.get("collapsed_default") or metadata.get("collapsedDefault") or False
                ),
                description=str(
                    metadata.get("group_description") or metadata.get("groupDescription") or ""
                ),
                metadata={"namespace": metadata.get("namespace", "")},
            )
        )
    groups.sort(key=lambda item: (item.order, item.label, item.group_id))
    return tuple(groups)


class _RenderSettingNativeCommand(NativeValueEditCommand):
    """One native render-setting edge with the SHARED render lifecycle.

    Undo/redo transfer the exact native value state (including creation and
    deletion of the column via ``MISSING``) through the upstream native
    authoring seam. After EVERY successfully committed edge — apply, reset,
    undo, redo, and grouped execution — the setting's declared renderer
    lifecycle is requested FIRST (a failed commit propagates before either
    step, so rejected edits never trigger updates), then render-settings
    subscribers are notified so open views re-read the store.  The lifecycle
    request precedes notification deliberately: an interrupt-class observer
    failure re-raises under the committed-edge protocol AFTER the committed
    value has its renderer update scheduled."""

    def __init__(
        self,
        *args: Any,
        notify: Callable[[], None],
        lifecycle: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._notify_render_settings = notify
        self._request_render_lifecycle = lifecycle

    def _committed_edge(self) -> None:
        if callable(self._request_render_lifecycle):
            self._request_render_lifecycle()
        self._notify_render_settings()

    def do(self) -> None:
        super().do()
        self._committed_edge()

    def undo(self) -> None:
        super().undo()
        self._committed_edge()


class _RenderSettingsOwnerCommand(Command):
    """One undoable edge of the private global RenderSettings owner prim.

    Undo/redo transfer the EXACT opinion state (including absence, which is
    the effective default) by republishing the adapter's own population
    reference.  Like :class:`_RenderSettingNativeCommand`, the declared
    renderer lifecycle is requested first and render-settings subscribers are
    notified afterwards, and only after the transition has actually
    committed — a failed republish propagates before either.
    """

    def __init__(
        self,
        adapter: Any,
        scene: Any,
        old_opinions: Mapping[str, Any],
        new_opinions: Mapping[str, Any],
        *,
        notify: Callable[[], None],
        lifecycle: Callable[[], None] | None = None,
    ) -> None:
        self._adapter = adapter
        self._scene = scene
        self._old = dict(old_opinions)
        self._new = dict(new_opinions)
        self._notify_render_settings = notify
        self._request_render_lifecycle = lifecycle

    def _transition(self, opinions: Mapping[str, Any]) -> None:
        if (
            self._scene is None
            or getattr(self._adapter, "_scene", None) is not self._scene
            or not getattr(self._scene, "is_open", False)
        ):
            raise RuntimeError(
                "render settings owner history belongs to a closed or "
                "replaced OVStage scene"
            )
        self._adapter._replace_render_settings_owner_layer(opinions)
        if callable(self._request_render_lifecycle):
            self._request_render_lifecycle()
        self._notify_render_settings()

    def do(self) -> None:
        self._transition(self._new)

    def undo(self) -> None:
        self._transition(self._old)


class _RenderProductResolutionMismatch(Exception):
    pass


def _version_tuple(value: Any) -> tuple[int, ...] | str:
    parts: list[int] = []
    for part in str(value).split("."):
        try:
            parts.append(int(part))
        except ValueError:
            return str(value)
    return tuple(parts) if parts else str(value)


def _detect_gpu_device_name() -> str:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name",
                "--format=csv,noheader",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except Exception:
        return "NVIDIA GPU"
    first_line = (result.stdout or "").splitlines()
    if first_line:
        return first_line[0].strip() or "NVIDIA GPU"
    return "NVIDIA GPU"


def _cuda_tensor_extent_and_row_stride_bytes(
    tensor: Any,
) -> tuple[int, int, int] | None:
    shape = getattr(tensor, "shape", None)
    if shape is None:
        return None
    try:
        dims = tuple(int(value) for value in shape)
    except (TypeError, ValueError):
        return None
    if len(dims) < 2:
        return None
    actual_height, actual_width = dims[0], dims[1]
    channels = int(dims[2]) if len(dims) >= 3 else 1
    dtype = getattr(tensor, "dtype", None)
    bits = int(getattr(dtype, "bits", 8) or 8)
    lanes = int(getattr(dtype, "lanes", 1) or 1)
    element_bytes = max(1, (bits * lanes + 7) // 8)
    stride = max(1, actual_width * max(1, channels) * element_bytes)
    return (actual_width, actual_height, stride)


def _rgba_frame_is_black(frame: np.ndarray) -> bool:
    """Exact all-black test for an RGBA uint8 frame, alpha ignored.

    ``frame[:, :, :3].max(initial=0)`` reduced over a non-contiguous slice
    cost ~2.7 ms per frame at 1370x737 and throttled the presentation loop
    under OVUI_WIDGETS_REQUIRE_OVRTX. Masking the alpha byte on a uint32
    view answers the same question in one contiguous C pass (~0.3 ms).
    """
    if (frame.ndim == 3 and frame.shape[-1] == 4
            and frame.dtype == np.uint8 and frame.flags.c_contiguous):
        rgb_mask = np.uint32(
            0x00FFFFFF if sys.byteorder == "little" else 0xFFFFFF00
        )
        return not bool((frame.reshape(-1).view(np.uint32) & rgb_mask).any())
    return int(frame[:, :, :3].max(initial=0)) == 0


def _require_real_ovrtx() -> bool:
    value = os.environ.get("OVUI_WIDGETS_REQUIRE_OVRTX", "")
    return value.strip().lower() not in ("", "0", "false", "no", "off")


def _config_accepts_keyword(config_type: Any, keyword: str) -> bool:
    """Return whether a RendererConfig callable accepts one keyword.

    OVRTX 0.5 is Vulkan-only on Windows and removed ``use_vulkan`` from
    ``RendererConfig``. Older runtimes still require the explicit opt-in.
    Preserve the older behavior when a native/extension callable does not
    publish an inspectable signature.
    """
    try:
        parameters = inspect.signature(config_type).parameters
    except (TypeError, ValueError):
        return True
    return keyword in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )


def _borrow_renderer_config(ovrtx: Any) -> Any:
    attach_mode_type = getattr(ovrtx, "AttachMode", None)
    borrow_mode = getattr(attach_mode_type, "BORROW", None)
    config_type = ovrtx.RendererConfig
    config_kwargs = {
        "keep_system_alive": True,
        "log_level": "info",
        "selection_outline_enabled": True,
        "selection_outline_width": 2,
    }
    if _config_accepts_keyword(config_type, "use_vulkan"):
        config_kwargs["use_vulkan"] = True
    if borrow_mode is not None:
        config_kwargs["attach_mode"] = borrow_mode
    try:
        return config_type(**config_kwargs)
    except TypeError as exc:
        if borrow_mode is None:
            raise
        raise RuntimeError(
            "incompatible public OVRTX attachment contract: public "
            "ovrtx.AttachMode.BORROW is present but ovrtx.RendererConfig "
            "does not accept attach_mode"
        ) from exc


def _source_token_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _render_var_by_source_name(frame: Any, source_name: str) -> Any:
    """Resolve a presentation RenderVar across the 0.4 and 0.5 result APIs."""

    render_vars = getattr(frame, "render_vars", None) or {}
    rv = render_vars.get(source_name)
    if rv is not None:
        return rv
    for render_var_path, candidate in render_vars.items():
        if (
            str(getattr(candidate, "source_name", "") or "") == source_name
            or str(render_var_path).rsplit("/", 1)[-1] == source_name
        ):
            return candidate
    raise KeyError(source_name)


def _normalize_active_prim_path(path: Optional[str], fallback: str) -> Optional[str]:
    if path is None:
        return fallback
    path_str = str(path).strip()
    if not path_str:
        return fallback
    if (
        not path_str.startswith("/")
        or path_str == "/"
        or path_str.endswith("/")
        or "//" in path_str
    ):
        return None
    if "." in path_str or any(part in {"", ".", ".."} for part in path_str[1:].split("/")):
        return None
    return path_str


def _render_var_warning(code: str, message: str) -> RenderVarWarning:
    return RenderVarWarning(code=code, message=message)


def _render_var_output_for_request(
    catalog: RenderVarOutputCatalog,
    request: RenderVarOutputRequest,
) -> RenderVarOutputDescriptor | None:
    requested_product_path = str(request.render_product_path or "")
    requested_output_id = str(request.output_id or "")
    requested_var = _source_token_key(request.render_var_name)
    for output in catalog.outputs:
        if output.render_product_path != requested_product_path:
            continue
        if requested_output_id and output.output_id == requested_output_id:
            return output
        if requested_var and _source_token_key(output.render_var_name) == requested_var:
            return output
    return None


def _point_cloud_warning(code: str, message: str) -> PointCloudWarning:
    return PointCloudWarning(code=code, message=message)


def _point_cloud_output_for_request(
    catalog: PointCloudOutputCatalog,
    request: PointCloudRequest,
) -> PointCloudOutputDescriptor | None:
    requested_product_path = str(request.render_product_path or "")
    requested_var = _source_token_key(request.render_var_name or "PointCloud")
    for output in catalog.outputs:
        if output.render_product_path != requested_product_path:
            continue
        if _source_token_key(output.render_var_name) == requested_var:
            return output
    return None


def _copy_tensor_to_host(data: Any) -> np.ndarray:
    numpy_fn = getattr(data, "numpy", None)
    if callable(numpy_fn):
        return np.array(numpy_fn(), copy=True)
    return np.array(np.from_dlpack(data), copy=True)


def _mapped_channel(mapping: Any, name: str, *, allow_tensor: bool) -> np.ndarray:
    try:
        channel = mapping[name]
    except Exception:
        channel = None
    if channel is not None:
        return _copy_tensor_to_host(channel)
    if not allow_tensor:
        raise KeyError(name)
    try:
        tensor = mapping.tensor
    except Exception as exc:
        raise KeyError(name) from exc
    return _copy_tensor_to_host(tensor)


def _mapped_render_var_tensor(mapping: Any) -> Any:
    # ovrtx 0.5 removed ``MappedRenderVar.tensor``; a single-tensor mapping
    # is itself the DLPack tensor (``shape``, ``dtype``, ``data``). The CPU
    # presentation map (``_map_presentation_frame_cpu``) already handles both
    # shapes; the CUDA maps below need the same, or the zero-copy probe sees
    # an AttributeError and retires tier-2 for the life of the process.
    return getattr(mapping, "tensor", mapping)


def _copy_primary_mapping_tensor(mapping: Any, name: str) -> np.ndarray:
    try:
        tensor = mapping.tensor
    except Exception:
        tensor = mapping[name]
    return _copy_tensor_to_host(tensor)


def _map_render_var_cpu(rv: Any, device: Any, callback: Callable[[Any], Any]) -> Any:
    mapping = rv.map(device=device) if device is not None else rv.map()
    if hasattr(mapping, "__enter__") and hasattr(mapping, "__exit__"):
        with mapping as entered:
            return callback(entered)
    try:
        return callback(mapping)
    finally:
        unmap = getattr(mapping, "unmap", None)
        if callable(unmap):
            unmap()


def _render_var_probe_rejected(
    request: RenderVarProbeRequest,
    message: str,
    warning_code: str,
    *,
    frame: RenderVarOutputFrame | None = None,
    pixel_x: int | None = None,
    pixel_y: int | None = None,
) -> RenderVarProbeResult:
    """Build one deterministic rejection without touching renderer state."""

    return RenderVarProbeResult(
        accepted=False,
        render_product_path=(
            frame.render_product_path if frame is not None else request.render_product_path
        ),
        output_id=frame.output_id if frame is not None else request.output_id,
        render_var_name=(frame.render_var_name if frame is not None else request.render_var_name),
        pixel_x=request.pixel_x if pixel_x is None else pixel_x,
        pixel_y=request.pixel_y if pixel_y is None else pixel_y,
        message=message,
        warning_code=warning_code,
        frame_index=frame.frame_index if frame is not None else None,
        stale=frame.stale if frame is not None else False,
        warnings=frame.warnings if frame is not None else (),
    )


def _render_var_probe_pixel(
    request: RenderVarProbeRequest,
    frame: RenderVarOutputFrame,
) -> tuple[int, int]:
    """Resolve top-left-origin pixel coordinates for a cached output frame."""

    width = int(frame.width)
    height = int(frame.height)
    if width <= 0 or height <= 0:
        raise ValueError("RenderVar frame has no image dimensions.")
    normalized_x = request.normalized_x
    normalized_y = request.normalized_y
    if (normalized_x is None) != (normalized_y is None):
        raise ValueError("Both normalized probe coordinates are required.")
    if normalized_x is not None and normalized_y is not None:
        x = float(normalized_x)
        y = float(normalized_y)
        if not np.isfinite(x) or not np.isfinite(y):
            raise ValueError("Probe coordinates are not finite.")
        if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
            raise ValueError("Probe coordinates are outside the output.")
        return (
            min(width - 1, max(0, int(round(x * float(width - 1))))),
            min(height - 1, max(0, int(round(y * float(height - 1))))),
        )
    pixel_x = int(request.pixel_x)
    pixel_y = int(request.pixel_y)
    if pixel_x >= width or pixel_y >= height:
        raise ValueError("Probe coordinates are outside the output.")
    return (pixel_x, pixel_y)


def _render_var_probe_scalar(value: Any) -> int | float | None:
    """Convert one mapped numeric scalar to a stable Python value."""

    try:
        scalar = np.asarray(value).item()
    except Exception:
        return None
    if isinstance(scalar, (np.integer, int)):
        return int(scalar)
    try:
        numeric = float(scalar)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _render_var_probe_raw_value(sample: Any) -> int | float | tuple[Any, ...] | None:
    values = np.asarray(sample)
    if values.ndim == 0:
        return _render_var_probe_scalar(values)
    converted = tuple(_render_var_probe_scalar(value) for value in values.reshape(-1))
    return converted if any(value is not None for value in converted) else None


def _render_var_probe_sample(
    frame: RenderVarOutputFrame,
    pixel_x: int,
    pixel_y: int,
) -> Any | None:
    """Read one sample from the owned host snapshot without mutating it."""

    source = frame.raw_data if frame.raw_data is not None else frame.display_data
    try:
        data = np.asarray(source)
    except Exception:
        return None
    if data.size == 0 or data.ndim == 0:
        return None
    if data.ndim == 1:
        expected_size = int(frame.width) * int(frame.height)
        if expected_size > 0 and data.size == expected_size:
            data = data.reshape((int(frame.height), int(frame.width)))
        else:
            data = data.reshape((1, data.shape[0]))
    if pixel_y >= data.shape[0] or pixel_x >= data.shape[1]:
        return None
    return data[pixel_y, pixel_x]


def _render_var_probe_normalized_value(
    raw_value: Any,
    value_range: tuple[float, float] | None,
) -> Any:
    if value_range is None:
        return None
    lo = float(value_range[0])
    hi = float(value_range[1])
    if not np.isfinite(lo):
        lo = 0.0
    if not np.isfinite(hi) or hi <= lo:
        hi = lo + 1.0

    def _normalize(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(np.clip((float(value) - lo) / (hi - lo), 0.0, 1.0))
        except (TypeError, ValueError):
            return None

    if isinstance(raw_value, tuple):
        return tuple(_normalize(value) for value in raw_value)
    return _normalize(raw_value)


def _render_var_probe_number(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    try:
        return f"{float(value):.6g}"
    except (TypeError, ValueError):
        return str(value)


def _render_var_probe_display_value(raw_value: Any, units: str) -> str:
    suffix = f" {units}" if units else ""
    if isinstance(raw_value, tuple):
        values = (
            "no data" if value is None else _render_var_probe_number(value) for value in raw_value
        )
        return f"({', '.join(values)}){suffix}"
    return f"{_render_var_probe_number(raw_value)}{suffix}"


def _render_var_probe_output_kind(frame: RenderVarOutputFrame) -> RenderVarOutputKind:
    try:
        return RenderVarOutputKind(str(frame.metadata.get("output_kind") or ""))
    except ValueError:
        return RenderVarOutputKind.UNKNOWN


def _render_var_probe_category_label(
    frame: RenderVarOutputFrame,
    category_id: int,
) -> str:
    labels = frame.metadata.get("category_labels") or frame.metadata.get("labels")
    if isinstance(labels, Mapping):
        label = labels.get(category_id, labels.get(str(category_id)))
        if label is not None:
            return str(label)
    if category_id == 0:
        return "Background"
    return str(category_id)


def _point_cloud_copy_render_var(
    render_vars: dict[Any, Any],
    name: str,
    device: Any,
) -> np.ndarray:
    requested = _source_token_key(name)
    rv = render_vars.get(name)
    if rv is None:
        rv = next(
            (value for key, value in render_vars.items() if _source_token_key(key) == requested),
            None,
        )
    if rv is not None:
        return _map_render_var_cpu(
            rv,
            device,
            lambda mapping: _mapped_channel(mapping, name, allow_tensor=True),
        )
    for candidate in render_vars.values():
        try:
            return _map_render_var_cpu(
                candidate,
                device,
                lambda mapping: _mapped_channel(
                    mapping,
                    name,
                    allow_tensor=False,
                ),
            )
        except KeyError:
            continue
    raise KeyError(name)


def _point_cloud_rows(data: Any, component_count: int = 1) -> np.ndarray:
    arr = np.asarray(data)
    if arr.ndim == 0:
        arr = arr.reshape(1, 1)
    elif arr.ndim == 1 and component_count > 1:
        usable = (arr.size // component_count) * component_count
        arr = arr[:usable].reshape((-1, component_count))
    elif (
        arr.ndim == 2
        and component_count > 1
        and arr.shape[0] == component_count
        and arr.shape[1] != component_count
    ):
        arr = arr.T
    elif arr.ndim > 2:
        arr = arr.reshape((-1, arr.shape[-1]))
    return np.array(arr, copy=False)


def _point_cloud_indices(point_count: int, request: PointCloudRequest) -> np.ndarray:
    indices = np.arange(int(point_count), dtype=np.int64)[:: max(1, int(request.decimation_stride))]
    if request.max_points is not None:
        indices = indices[: int(request.max_points)]
    return indices


def _point_cloud_world_coordinates(
    coordinates: np.ndarray,
    descriptor: PointCloudOutputDescriptor,
    units_per_meter: float,
) -> tuple[np.ndarray | None, PointCloudCoordinateSpace, PointCloudWarning | None]:
    scale = float(units_per_meter)
    if not math.isfinite(scale) or scale <= 0.0:
        scale = 1.0
    if descriptor.coordinate_space is PointCloudCoordinateSpace.WORLD:
        return (
            np.asarray(coordinates[:, :3], dtype=np.float32) * scale,
            PointCloudCoordinateSpace.WORLD,
            None,
        )
    if descriptor.transform_to_world is None:
        return (
            None,
            descriptor.coordinate_space,
            _point_cloud_warning(
                "missing_transform",
                "PointCloud output cannot be transformed to world space.",
            ),
        )
    try:
        matrix = np.asarray(descriptor.transform_to_world, dtype=np.float64).reshape((4, 4))
        points = np.asarray(coordinates[:, :3], dtype=np.float64) * scale
        homogeneous = np.ones((points.shape[0], 4), dtype=np.float64)
        homogeneous[:, :3] = points
        return (
            np.asarray((homogeneous @ matrix)[:, :3], dtype=np.float32),
            PointCloudCoordinateSpace.WORLD,
            None,
        )
    except Exception:
        return (
            None,
            descriptor.coordinate_space,
            _point_cloud_warning(
                "transform_failed",
                "PointCloud output transform failed.",
            ),
        )


def _frame_index(frame: Any) -> Optional[int]:
    for attr_name in ("frame_index", "frameIndex", "index"):
        value = getattr(frame, attr_name, None)
        if value is not None:
            try:
                return int(value)
            except Exception:
                continue
    return None


class _RenderSettingsSubscription:
    def __init__(self, cancel: Callable[[], None]) -> None:
        self._cancel = cancel

    def cancel(self) -> None:
        cancel = self._cancel
        self._cancel = None
        if callable(cancel):
            cancel()


@dataclass(frozen=True)
class _QueuedViewportRender:
    viewport_id: str
    generation: int
    render_product_path: str
    width: int
    height: int
    view_matrix: Any
    projection_matrix: Any
    primary: bool


@dataclass
class _InFlightRenderBatch:
    operation: Any
    metadata: dict[str, RenderFrameMetadata]
    requests: dict[str, _QueuedViewportRender]


class _SecondaryViewportRendererAdapter:
    """TEMP multi-viewport facade owned by one OvstageRendererAdapter."""

    def __init__(self, owner: "OvstageRendererAdapter") -> None:
        self._owner = owner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._owner, name)

    def load_stage(self, stage: Any) -> None:
        return None

    def shutdown(self) -> None:
        self._owner._secondary_viewport_request = None
        self._owner._secondary_viewport_frame = None
        self._owner._secondary_viewport_active = False

    def set_zero_copy_state(self, state: Any) -> None:
        # Both outputs are CPU-mapped from one step for this temporary POC.
        return None

    def set_ldr_overlap_enabled(self, enabled: bool) -> bool:
        return False

    def get_active_camera_path(self) -> Optional[str]:
        return None

    def set_active_camera_path(self, path: Optional[str]) -> bool:
        return False

    def get_active_render_product_path(self) -> Optional[str]:
        return self._owner._secondary_render_product_path

    def set_active_render_product_path(self, path: Optional[str]) -> bool:
        return path in (None, self._owner._secondary_render_product_path)

    def render_frame(
        self,
        width: int,
        height: int,
        view_matrix: Matrix4d,
        proj_matrix: Matrix4d,
    ) -> Any:
        return self._owner._queue_secondary_viewport_frame(
            width,
            height,
            view_matrix,
            proj_matrix,
        )

    def enqueue_render_frame(
        self,
        viewport_id: str,
        generation: int,
        width: int,
        height: int,
        view_matrix: Matrix4d,
        proj_matrix: Matrix4d,
    ) -> None:
        self._owner._enqueue_viewport_render_frame(
            viewport_id,
            generation,
            self._owner._secondary_render_product_path,
            width,
            height,
            view_matrix,
            proj_matrix,
            primary=False,
        )

    def submit_enqueued_render_frames(self) -> bool:
        return bool(self._owner.submit_enqueued_render_frames())

    def poll_render_frame(self, viewport_id: str) -> RenderFrameResult | None:
        return self._owner.poll_render_frame(viewport_id)


class OvstageRendererAdapter(RendererAdapter):
    """OVRTX presentation adapter borrowing an OVStage-owned scene.

    ``viewport_quality`` controls initial quality after renderer resets for
    the generated private viewport product only. The default (0) presents
    progressive frames without a synchronous quality warm-up; later frames
    still accumulate toward the unchanged sampling target. Capture callers
    can request the native full initial-quality budget with 100. Authored
    render products retain their own quality settings.
    """

    def __init__(
        self,
        scene: Any | None = None,
        undo_manager: Any | None = None,
        *,
        viewport_quality: int = 0,
    ) -> None:
        if type(viewport_quality) is not int or not 0 <= viewport_quality <= 100:
            raise ValueError("viewport_quality must be a plain int from 0 to 100")
        self._viewport_quality = viewport_quality
        self._scene = scene
        self._undo_manager = undo_manager
        result = import_ovrtx()
        if result.module is None:
            error = result.error or ImportError("ovrtx not available")
            raise RuntimeError(
                f"ovrtx is not available in this environment ({type(error).__name__}: {error})"
            ) from error

        ovrtx = result.module
        _validate_configured_ovrtx_source(ovrtx)
        validate_runtime_requirement(OVRTX_RUNTIME_REQUIREMENT, ovrtx)
        self._ovrtx = ovrtx
        config = _borrow_renderer_config(ovrtx)
        get_instrumentation().prepare_renderer_config(self, config)
        self._renderer = ovrtx.Renderer(config)
        validate_ovrtx_borrow_renderer(self._renderer)
        self._gpu_device_name = _detect_gpu_device_name()
        self._logged_first_step = False
        self._zero_copy_state: Optional[ZeroCopyState] = None
        # A replacement renderer is constructed before the provider tears
        # down the current scene. LivestreamTap.close() shuts down process-wide
        # ovstream state, so activating the replacement tap here would let the
        # old renderer's later shutdown invalidate it. The optional windowed
        # stream is therefore activated only after load_stage has attached the
        # replacement scene and the provider's old-scene teardown is complete.
        self._livestream = None
        self._livestream_error_logged = False
        self._livestream_host_buf: Optional[np.ndarray] = None
        self._livestream_zero_copy_tee_attempt_count = 0
        self._livestream_zero_copy_tee_success_count = 0
        self._livestream_cuda_tee_and_d2h_count = 0
        self._livestream_cpu_presentation_count = 0
        #: Values this adapter's own load produced on its private owner prims;
        #: authorship is measured against these, never against "a column exists".
        self._render_settings_authorship_baseline: dict[str, dict[str, Any]] = {}
        self._attached_stage: Any = None
        self._runtime_reference_handle: Any = None
        self._runtime_population: Any = None
        self._path_dictionary: Any = None
        self._runtime_root_path = _RUNTIME_ROOT_LOCAL_PATH
        self._runtime_camera_local_path = _RENDER_CAMERA_LOCAL_PATH
        # Global RenderSettings owner: empty until a load resolves it, so the
        # rows it owns fail closed while no document is attached.
        self._runtime_render_settings_local_path = ""
        self._render_settings_owner_handle: Any = None
        self._render_settings_owner_opinions: dict[str, Any] = {}
        self._runtime_render_product_path = _RENDER_PRODUCT_LOCAL_PATH
        self._render_product_path = _RENDER_PRODUCT_LOCAL_PATH
        self._default_render_product_path = self._render_product_path
        self._active_render_product_common_path: str | None = None
        self._camera_path: str | None = _RENDER_CAMERA_LOCAL_PATH
        self._active_camera_common_path: str | None = None
        self._last_resolution = _DEFAULT_RESOLUTION
        self._last_render_product_resolution = _DEFAULT_RESOLUTION
        self._dt_clock = time.perf_counter()
        self._last_load_from_scene_context = False
        self._borrow_step_count = 0
        self._successful_frame_count = 0
        self._last_frame_nonblack_pixels: int | None = None
        self._last_frame_shape: tuple[int, ...] | None = None
        # Depth-one LdrColor presentation overlap (opt-in; the viewport
        # frame loop enables it via set_ldr_overlap_enabled).
        self._ldr_overlap: Optional[LdrOverlapState] = None
        self._live_preview_write_count = 0
        self._live_preview_clear_count = 0
        self._live_preview_paths: set[str] = set()
        self._last_live_preview_path: str | None = None
        self._last_live_preview_matrix: tuple[float, ...] | None = None
        self._last_live_preview_write_duration_ms: float | None = None
        self._live_preview_write_durations_ms: Deque[float] = deque(maxlen=4096)
        # Diagnostic record of the most recent full-policy verdict per
        # previewed path in the current sequence; never read for authorization.
        self._live_preview_policy_cache: dict[str, bool] = {}
        self._live_transform_adapter = (
            OvstageTransformAdapter(scene) if scene is not None else None
        )
        self._selected_paths: list[str] = []
        self._selection_outline_previous_paths: set[str] = set()
        # Membership established in the active attachment generation is kept
        # separate from paths whose detach-time cleanup may have failed.  A
        # replacement OVStage must never inherit the former generation's
        # application claim, even while renderer-owned cleanup is retrying.
        self._selection_outline_stale_paths: set[str] = set()
        self._selection_outline_styles_configured = False
        self._selection_outline_style_calls = 0
        # OVRTX-side data-plane attribute writes (the legacy renderer
        # ``write_attribute`` outline mechanism). The native OVStage adapter
        # NEVER performs them — this counter is the BORROW invariant witness
        # and must stay zero. It is distinct from the reserved-attribute
        # counter below, which counts writes of ovrtx's own reserved
        # presentation column through the OVStage OWNER's copy-in API.
        self._selection_outline_attribute_writes = 0
        # Successful writes of the reserved ``omni:selectionOutlineGroup``
        # presentation attribute through StageWriteBatch — the documented
        # ovrtx 0.4 membership transport on runtimes without the dedicated
        # string membership APIs (the installed wheel exposes neither).
        self._selection_outline_reserved_writes = 0
        self._selection_outline_generation = 0
        self._selection_outline_last_write: dict[str, Any] = {}
        # Older/unknown runtimes may need a reset after dedicated membership
        # writes. Coalesce a clear-A/set-B pair into one compatibility reset;
        # modern runtimes waive this without waiving initial pass activation.
        self._selection_outline_membership_reset_pending = False
        # The outline render pass does not pick up per-prim membership in this
        # app's attached-renderer state until one renderer.reset() runs after
        # membership exists (verified live against ovrtx 0.4 and 0.5; standalone
        # attach sequences do not need it). Armed states mirror where the
        # dead state was observed: fresh attach and resolution resets that
        # happen with no applied outline.
        self._selection_outline_pass_needs_reset = True
        self._in_flight_pick_queries: Deque[list] = deque()
        self._pick_seq = 0
        self._pick_enqueue_count = 0
        self._pick_result_count = 0
        self._last_pick_pixel_rect: tuple[int, int, int, int] | None = None
        self._last_pick_kind: str | None = None
        self._last_pick_query_name: str | None = None
        self._last_pick_path: str | None = None
        self._last_pick_paths: tuple[str, ...] = ()
        self._last_pick_world_point: tuple[float, float, float] | None = None
        self._last_view_matrix: np.ndarray | None = None
        self._last_proj_matrix: np.ndarray | None = None
        self._last_pushed_camera_state: tuple[Any, ...] | None = None
        # TEMP: a second OVUI viewport is represented by another private
        # Camera/RenderProduct, but both products are submitted in one OVRTX
        # step through this adapter.
        self._secondary_viewport_active = False
        self._secondary_viewport_request: tuple[Any, ...] | None = None
        self._secondary_viewport_frame: np.ndarray | None = None
        self._secondary_camera_path = (
            f"{_RUNTIME_ROOT_LOCAL_PATH}/Render/Cameras/Secondary"
        )
        self._secondary_render_product_path = (
            f"{_RUNTIME_ROOT_LOCAL_PATH}/Render/ViewportSecondary"
        )
        self._secondary_last_resolution = _DEFAULT_RESOLUTION
        self._secondary_last_pushed_camera_state: tuple[Any, ...] | None = None
        # Cross-thread presentation state. The UI thread publishes immutable,
        # coalesced viewport requests and consumes completed frames. The
        # dedicated renderer thread is the sole owner of OVRTX step/poll/output
        # extraction for this asynchronous path.
        self._render_state_lock = threading.RLock()
        self._render_worker_wake = threading.Event()
        self._render_worker_stop = threading.Event()
        self._render_worker_error: BaseException | None = None
        self._render_worker_thread: threading.Thread | None = None
        self._queued_viewport_renders: dict[str, _QueuedViewportRender] = {}
        self._completed_viewport_frames: dict[str, RenderFrameResult] = {}
        self._presentation_pending_viewports: set[str] = set()
        self._completed_pick_callbacks: Deque[
            tuple[Callable[..., None], tuple[Any, ...]]
        ] = deque()
        self._in_flight_render_batch: _InFlightRenderBatch | None = None
        self._render_frame_sequence = 0
        self._presented_async_metadata: RenderFrameMetadata | None = None
        self._render_flow_mode = os.environ.get(
            "OMNIUI_RENDER_FLOW_MODE", "nativePacing"
        )
        # Optional native pacing borrows the already-attached renderer/Stage
        # between matching start and stop/drain calls. Python remains their
        # sole owner and every ordinary OVStage publication revokes the borrow
        # before reserving an ordinal.
        self._frame_pacing_provider: Any = None
        self._frame_pacing_token: int = 0
        self._frame_pacing_needs_sync_step: bool = True
        self._frame_pacing_size: tuple[int, int] | None = None
        self._frame_pacing_projection: np.ndarray | None = None
        self._frame_pacing_camera_path: str = ""
        self._frame_pacing_velocity = np.zeros(3, dtype=np.float64)
        self._frame_pacing_restore_overlap: bool = False
        self._frame_pacing_pick_snapshot: CameraSnapshot | None = None
        self._frame_pacing_presented_snapshot: CameraSnapshot | None = None
        self._frame_pacing_pick_generated: bool = False
        self._frame_pacing_pick_association_unavailable: bool = False
        self._frame_pacing_render_paused: bool = False
        self._frame_pacing_camera_query: Any = None
        self._frame_pacing_camera_path_list: Any = 0
        self._frame_pacing_query_path: str = ""
        self._frame_pacing_camera_query_release_op: Any = None
        self._frame_pacing_camera_query_release_succeeded: bool = False
        self._frame_pacing_transition_lock = threading.RLock()
        self._frame_pacing_stage_barrier_callback = (
            self._before_ovstage_frame_publication
        )
        self._point_cloud_requests: dict[str, PointCloudRequest] = {}
        self._latest_point_cloud_frames: dict[tuple[str, str], PointCloudFrame] = {}
        self._point_cloud_background_fallback_count = 0
        self._render_var_output_requests: dict[str, RenderVarOutputRequest] = {}
        self._latest_render_var_output_frames: dict[
            tuple[str, str, str],
            RenderVarOutputFrame,
        ] = {}
        self._render_settings_subscribers: list[Callable[[], None]] = []
        version = _version_tuple(getattr(ovrtx, "__version__", "unknown"))
        self._ovrtx_version = version
        renderer_version = getattr(self._renderer, "version", "unknown")
        use_vulkan = getattr(getattr(self._renderer, "config", None), "use_vulkan", None)
        print(
            "[OvstageRendererAdapter] renderer_constructed "
            f"renderer_class=OvstageRendererAdapter ovrtx_version={version} "
            f"pick_query_uses_ndc={self._pick_query_uses_ndc()} "
            f"renderer_version={renderer_version} config_use_vulkan={use_vulkan} "
            "attach_mode=borrow "
            f'adapter_gpu_device_hint="{self._gpu_device_name}"',
            file=sys.stderr,
        )
        if self._render_flow_mode == "fast":
            self._start_render_worker()

    def _native_render_is_paused(self) -> bool:
        """Report the pick lease state safely on compatibility instances.

        Partially constructed and compatibility adapters predate this state,
        so every read goes through the same defensive accessor already used
        for the pacing token.
        """

        return bool(getattr(self, "_frame_pacing_render_paused", False))

    def set_zero_copy_state(self, state: Optional[ZeroCopyState]) -> None:
        self._zero_copy_state = state

    def set_undo_manager(self, undo_manager: Any | None) -> None:
        """Bind application history after pre-UI OVRTX construction.

        The standalone entry point must create OVRTX before ``Application``
        exists, so the early adapter cannot receive history in its constructor.
        This one-way handoff occurs before a scene is loaded and lets public
        render-setting USD edits join the same application undo stack as every
        other durable authoring operation.
        """

        self._undo_manager = undo_manager

    def attach_render_product_stream(self, tap, render_product_path):
        """Bind the existing CUDA texture tee to one explicit RenderProduct."""
        from ovui_data_adapters.common._render_product_stream import attach
        attach(self, tap, render_product_path)

    def detach_render_product_stream(self, tap):
        """Release this owner without affecting another stream or closing it."""
        from ovui_data_adapters.common._render_product_stream import detach
        detach(self, tap)

    def render_product_stream_attached(self, tap):
        """Whether this renderer still feeds the given external stream."""
        from ovui_data_adapters.common._render_product_stream import is_attached
        return is_attached(self, tap)

    @property
    def livestream(self) -> Any:
        """The optional legacy windowed viewport livestream tap."""
        return self._livestream

    @property
    def runtime_root_path(self) -> str:
        """Private presentation prefix selected for the attached scene."""

        return str(self._runtime_root_path)

    def _activate_windowed_livestream(self) -> None:
        """Start the optional viewport stream after scene replacement.

        This method deliberately runs only at the successful end of
        :meth:`load_stage`.  Renderer preconstruction must remain transport
        free because a failed provider open cleans up that unused renderer
        while the previous renderer and its active process-global tap are
        still live.
        """

        if self._livestream is not None:
            return
        if not _livestream_env_enabled() or omniui_headless_enabled():
            return
        from ovui_data_adapters.common._livestream_tap import LivestreamTap

        self._livestream = LivestreamTap.maybe_create()

    def load_stage(self, stage: Any) -> None:
        scene = stage
        if not hasattr(scene, "_stage"):
            raise TypeError(f"load_stage expected OvstageScene, got {type(stage).__name__}")
        ovstage = getattr(scene, "_stage", None)
        if ovstage is None or not getattr(scene, "is_open", False):
            raise_not_ready("renderer scene load")

        if self._attached_stage is not None:
            raise RuntimeError("OVRTX does not support swapping an attached OVStage")
        # Ownership: nothing retained may outlive the native attach below.
        self._discard_async_render_state()
        self._release_retained_output()
        records = _query_records(ovstage)
        runtime_root_path = _select_runtime_root_path(scene)
        runtime_layer = _build_runtime_layer(
            ovstage,
            resolution=_DEFAULT_RESOLUTION,
            records=records,
            runtime_root_path=runtime_root_path,
            viewport_quality=self._viewport_quality,
        )
        self._remove_scene()
        population = _load_population_module(import_module("ovstage"))
        _register_presentation_root(scene, runtime_layer.root_path)
        try:
            reference_handle = _add_runtime_layer(
                population,
                ovstage,
                runtime_layer.usda,
                prefix_path=runtime_layer.root_path,
            )
        except BaseException:
            _unregister_presentation_root_if_absent(
                scene,
                runtime_layer.root_path,
            )
            raise
        # The global RenderSettings owner is added AFTER the essential runtime
        # layer and removed BEFORE it, so every teardown is order-reversed.
        # Each reference gets its own begin_frame/end_frame transaction inside
        # _add_runtime_layer, so the ordinals stay one-per-transaction.
        owner_handle, owner_path = _attach_render_settings_owner(
            scene, population, ovstage, {}
        )
        try:
            path_dictionary = import_module("ovstage").PathDictionary(ovstage)
        except Exception as exc:
            _compensate_render_settings_owner_failure(
                exc,
                scene=scene,
                population=population,
                stage=ovstage,
                reference_handle=owner_handle,
                owner_path=owner_path,
            )
            _compensate_runtime_layer_failure(
                exc,
                scene=scene,
                population=population,
                stage=ovstage,
                reference_handle=reference_handle,
                runtime_root_path=runtime_layer.root_path,
            )
            raise
        try:
            self._renderer.attach_ovstage(ovstage)
        except Exception as exc:
            path_dictionary.destroy()
            _compensate_render_settings_owner_failure(
                exc,
                scene=scene,
                population=population,
                stage=ovstage,
                reference_handle=owner_handle,
                owner_path=owner_path,
            )
            _compensate_runtime_layer_failure(
                exc,
                scene=scene,
                population=population,
                stage=ovstage,
                reference_handle=reference_handle,
                runtime_root_path=runtime_layer.root_path,
            )
            raise
        self._scene = scene
        self._attached_stage = ovstage
        existing_barrier = getattr(
            ovstage,
            "_ovui_before_frame_publication",
            None,
        )
        if (
            existing_barrier is None
            and bool(
                getattr(
                    ovstage,
                    "_ovui_before_frame_publication_supported",
                    False,
                )
            )
        ):
            ovstage._ovui_before_frame_publication = (
                self._frame_pacing_stage_barrier_callback
            )
        # Renderer/stage attachment is a defined recovery trigger for the
        # render-settings update ledger (replacement + reload semantics).
        self._clear_render_settings_update_block()
        self._live_transform_adapter = OvstageTransformAdapter(scene)
        self._live_preview_paths.clear()
        self._runtime_population = population
        self._runtime_reference_handle = reference_handle
        self._path_dictionary = path_dictionary
        self._runtime_root_path = runtime_layer.root_path
        self._runtime_camera_local_path = runtime_layer.camera_path
        self._secondary_camera_path = (
            f"{runtime_layer.root_path}/Render/Cameras/Secondary"
        )
        self._secondary_render_product_path = (
            f"{runtime_layer.root_path}/Render/ViewportSecondary"
        )
        self._render_settings_owner_handle = owner_handle
        self._runtime_render_settings_local_path = owner_path
        self._render_settings_owner_opinions = {}
        self._runtime_render_product_path = runtime_layer.render_product_path
        self._camera_path = runtime_layer.camera_path
        self._active_camera_common_path = None
        self._render_product_path = runtime_layer.render_product_path
        self._default_render_product_path = self._render_product_path
        self._active_render_product_common_path = None
        self._last_resolution = _DEFAULT_RESOLUTION
        self._last_render_product_resolution = _DEFAULT_RESOLUTION
        self._secondary_last_resolution = _DEFAULT_RESOLUTION
        self._secondary_last_pushed_camera_state = None
        self._secondary_viewport_frame = None
        self._dt_clock = time.perf_counter()
        self._last_load_from_scene_context = True
        # Retry any possibly renderer-retained membership from an older
        # attachment, but never publish it as applied in this generation.
        self._selection_outline_generation = int(
            getattr(self, "_selection_outline_generation", 0) or 0
        ) + 1
        self._selection_outline_previous_paths.clear()
        self._selection_outline_membership_reset_pending = False
        stale_paths = getattr(self, "_selection_outline_stale_paths", None)
        if not isinstance(stale_paths, set):
            stale_paths = set()
            self._selection_outline_stale_paths = stale_paths
        stale_outline = sorted(stale_paths)
        if stale_outline:
            cleared = self._write_selection_outline_group(
                stale_outline, _SELECTION_OUTLINE_CLEAR_GROUP_ID
            )
            stale_paths.difference_update(cleared)
        self._selection_outline_last_write = {
            "requested_paths": list(self._selected_paths),
            "applied_paths": [],
            "pending_paths": sorted(set(self._selected_paths)),
            "stale_cleanup_paths": sorted(stale_paths),
            "generation": self._selection_outline_generation,
            "stale_reason": (
                "stale_cleanup_pending" if stale_paths else "stage_attached"
            ),
        }
        # The newly attached scene needs one activation reset after
        # membership next exists (see __init__).
        self._selection_outline_pass_needs_reset = True
        self._borrow_step_count = 0
        self._successful_frame_count = 0
        self._last_frame_nonblack_pixels = None
        self._last_frame_shape = None
        attach_renderer = getattr(scene, "attach_renderer", None)
        if callable(attach_renderer):
            attach_renderer(self)
        # AUTHORSHIP BASELINE. The native store has no "authored vs default"
        # distinction: a column either exists or it does not, and OVStage/OVRTX
        # populate schema-default columns (dataWindowNDC, the exposure family)
        # the moment the private runtime RenderProduct and Camera are created.
        # Treating "a column exists" as authorship made a brand-new session
        # report user overrides for settings nobody touched. Snapshot what THIS
        # adapter's own initialisation produced, so authorship can mean what the
        # OpenUSD provider means: a value that differs from what the document
        # came up with.
        self._capture_render_settings_authorship_baseline()
        self._activate_windowed_livestream()
        print(
            "[OvstageRendererAdapter] load_stage source=ovstage_scene_context "
            "renderer=ovrtx attach_mode=borrow "
            f"render_product={self._render_product_path}",
            file=sys.stderr,
        )

    def set_frame_pacing_provider(self, provider: Any) -> None:
        """Bind the viewport provider used by optional native frame pacing."""

        if provider is getattr(self, "_frame_pacing_provider", None):
            return
        self._stop_native_frame_pacing("viewport provider replacement")
        self._frame_pacing_provider = provider

    def set_frame_pacing_suspended(self, suspended: bool) -> None:
        """Pause native renderer demand while its viewport is hidden.

        Visibility restoration deliberately does not resume here. The next
        visible viewport publication goes through ``_publish_native_frame``,
        whose existing resume handshake reconciles the live Stage write floor
        and revalidates all other ownership preconditions first.
        """

        token = int(getattr(self, "_frame_pacing_token", 0) or 0)
        if suspended:
            if token and not self._native_render_is_paused():
                self._stop_native_frame_pacing(
                    "hidden viewport", pause_render=True
                )

    @staticmethod
    def _frame_pacing_bindings() -> Any:
        try:
            from omni.ui import _ui as native_ui
        except (ImportError, AttributeError):
            return None
        names = (
            "_native_frame_pacing_start_ovstage",
            "_native_frame_pacing_publish",
            "_native_frame_pacing_stop",
            "_native_frame_pacing_pause_render",
            "_native_frame_pacing_resume_render",
            "_get_present_rate",
            "_get_native_frame_pacing_status",
        )
        # Every name has to be callable. Returning None keeps the viewport on
        # the synchronous render path.
        if not all(callable(getattr(native_ui, name, None)) for name in names):
            return None
        return native_ui

    def _before_ovstage_frame_publication(self) -> None:
        """Hand Stage publication ownership back to Python before begin_frame."""

        token = int(getattr(self, "_frame_pacing_token", 0) or 0)
        if not token:
            return
        if self._native_render_is_paused():
            return
        self._stop_native_frame_pacing("OVStage publication")

    def _frame_pacing_eligible(self) -> bool:
        native_ui = self._frame_pacing_bindings()
        stage = self._attached_stage
        scene = self._scene
        render_worker = getattr(self, "_render_worker_thread", None)
        if render_worker is not None and render_worker.is_alive():
            return False
        if native_ui is None or float(native_ui._get_present_rate()) == 0.0:
            return False
        if (
            self._renderer is None
            or stage is None
            or scene is None
            or not getattr(scene, "is_open", False)
            or getattr(scene, "_stage", None) is not stage
            or self._frame_pacing_provider is None
            or self._livestream is not None
            or self._point_cloud_requests
            or self._render_var_output_requests
            or self._runtime_camera_path() is None
            or str(self._render_product_path or "")
            != str(self._default_render_product_path or "")
            or getattr(stage, "_ovui_before_frame_publication", None)
            is not self._frame_pacing_stage_barrier_callback
            or not bool(
                getattr(
                    stage,
                    "_ovui_before_frame_publication_supported",
                    False,
                )
            )
        ):
            return False
        # The coordinator borrows the renderer's already-attached Stage. Do
        # not trust adapter bookkeeping alone: fail closed if the exact
        # wrapper instance that OVRTX attached is no longer this Stage.
        renderer_state = self.__dict__["_renderer"].__dict__
        if renderer_state.get("_attached_ovstage") is not stage:
            return False
        # Native pacing publishes GPU-resident images itself, so a pending
        # Python zero-copy request no longer competes with it: while a session
        # owns the renderer borrow, render_frame never runs and the legacy
        # GpuFrame path stays dormant. Refusing pacing here is what left the
        # ordinary launcher, which requests zero-copy, permanently unpaced.
        # `_ldr_overlap_allowed` keeps its own gate: that path really does
        # share the Python GpuFrame mechanism.
        return True

    def _ensure_frame_pacing_camera_query(self, camera_path: str) -> int:
        query = self._frame_pacing_camera_query
        if (
            query is not None
            and self._frame_pacing_camera_path_list
            and self._frame_pacing_query_path == camera_path
        ):
            return int(query.handle)
        self._release_frame_pacing_camera_query()
        stage = self._attached_stage
        dictionary = self._path_dictionary
        if stage is None or dictionary is None:
            return 0
        try:
            # OVStage 0.2 returns an owning PathList int subclass. Retain that
            # object until the query is released; reducing it to a bare int
            # lets its finalizer revoke the caller-owned list immediately.
            # OVStage 0.1 returns a plain int and follows the same path.
            path_list = dictionary.create_path_list_from_strings([camera_path])
            self._frame_pacing_camera_path_list = path_list
            self._frame_pacing_query_path = camera_path
            query = stage.query_from_path_list(path_list)
            self._frame_pacing_camera_query = query
            handle = int(getattr(query, "handle", 0) or 0)
            if not handle:
                raise RuntimeError("OVStage camera query returned an invalid handle")
        except Exception:
            # Publish ownership to the adapter before cleanup. If releasing
            # either resource fails, keep the fields intact so detach/shutdown
            # can retry instead of losing a live Stage query or path list.
            try:
                self._release_frame_pacing_camera_query()
            except Exception as cleanup_error:
                raise RuntimeError(
                    "failed to clean up an incomplete OVStage camera query"
                ) from cleanup_error
            return 0
        return handle

    def _release_frame_pacing_camera_query(self) -> None:
        query = getattr(self, "_frame_pacing_camera_query", None)
        path_list = getattr(self, "_frame_pacing_camera_path_list", 0) or 0
        if query is not None:
            stage = self._attached_stage
            if stage is None:
                raise RuntimeError("OVStage camera query outlived its Stage")
            operation = getattr(
                self, "_frame_pacing_camera_query_release_op", None
            )
            if operation is None:
                operation = query.release()
                if not bool(getattr(operation, "ok", False)):
                    raise RuntimeError("OVStage camera query release was rejected")
                self._frame_pacing_camera_query_release_op = operation
                self._frame_pacing_camera_query_release_succeeded = False
            operation_succeeded = bool(
                getattr(
                    self,
                    "_frame_pacing_camera_query_release_succeeded",
                    False,
                )
            )
            if not operation_succeeded:
                status, error_op_ids, _ = stage.wait_op(int(operation.op_id))
                operation_succeeded = (
                    int(status) == int(operation.status)
                    and not error_op_ids
                )
                self._frame_pacing_camera_query_release_succeeded = (
                    operation_succeeded
                )
            release_status = int(stage.release_op(int(operation.op_id)))
            if release_status != int(operation.status):
                # Keep both the claimed Query wrapper and its terminal
                # operation id so the next lifecycle drain can retry release
                # of tracking state without enqueueing a duplicate release.
                raise RuntimeError(
                    "OVStage camera query operation release must be retried"
                )
            self._frame_pacing_camera_query_release_op = None
            self._frame_pacing_camera_query_release_succeeded = False
            if not operation_succeeded:
                # The release operation completed with an execution error.
                # Tracking is now safely gone; return wrapper ownership so a
                # later drain can enqueue the query release again.
                query._rollback_release()
                raise RuntimeError("OVStage camera query release failed")
            self._frame_pacing_camera_query = None
        if path_list:
            dictionary = self._path_dictionary
            if dictionary is None:
                raise RuntimeError(
                    "OVStage camera path list outlived its dictionary"
                )
            dictionary.destroy_path_list(path_list)
            self._frame_pacing_camera_path_list = 0
        self._frame_pacing_query_path = ""

    def _borrow_native_frame_pacing_state(
        self,
        camera_path: str,
    ) -> tuple[int, str, int, int, int, int, int, int] | None:
        """Return a capability-checked renderer/Stage/query borrow."""

        if not self._frame_pacing_eligible():
            return None
        import ctypes

        renderer = self._renderer
        stage = self._attached_stage
        if renderer is None or stage is None:
            return None
        renderer_state = self.__dict__["_renderer"].__dict__
        stage_state = stage.__dict__
        handle = renderer_state.get("_handle")
        bindings = renderer_state.get("_bindings")
        stage_instance = stage_state.get("_inst")
        if handle is None or bindings is None or stage_instance is None:
            return None
        try:
            renderer_address = int(
                ctypes.cast(handle, ctypes.c_void_p).value or 0
            )
            stage_address = int(
                ctypes.cast(stage_instance, ctypes.c_void_p).value or 0
            )
            library_path = os.path.abspath(os.fspath(bindings.library_path))
            bindings_module = sys.modules.get(type(bindings).__module__)
            output_type = getattr(
                bindings_module,
                "ovrtx_render_product_render_var_output_t",
                None,
            )
            name_field = getattr(output_type, "source_name", None)
            if name_field is None:
                name_field = getattr(output_type, "render_var_name", None)
            handle_field = getattr(output_type, "output_handle", None)
            if name_field is None or handle_field is None:
                return None
            render_var_stride = ctypes.sizeof(output_type)
            render_var_name_offset = name_field.offset
            render_var_handle_offset = handle_field.offset
        except (AttributeError, OSError, TypeError, ValueError):
            return None
        if (
            not renderer_address
            or not stage_address
            or not os.path.isfile(library_path)
            or name_field.size != 16
            or handle_field.size != 8
            or not 0 < render_var_stride <= 4096
            or render_var_name_offset + name_field.size > render_var_stride
            or render_var_handle_offset + handle_field.size > render_var_stride
        ):
            return None
        try:
            committed_ordinal = int(_reconcile_native_write_floor(stage))
            camera_query = self._ensure_frame_pacing_camera_query(camera_path)
        except (AttributeError, OSError, TypeError, ValueError):
            return None
        if not camera_query:
            return None
        return (
            renderer_address,
            library_path,
            stage_address,
            camera_query,
            committed_ordinal,
            render_var_stride,
            render_var_name_offset,
            render_var_handle_offset,
        )

    def _stop_native_frame_pacing(
        self,
        reason: str,
        *,
        capture_selected_camera: bool = False,
        pause_render: bool = False,
    ) -> None:
        """Drain native renderer/Stage work before any Python operation."""

        transition_lock = getattr(self, "_frame_pacing_transition_lock", None)
        if transition_lock is None:
            # A few compatibility consumers construct a deliberately partial
            # adapter without running __init__. Such objects cannot activate
            # native pacing and retain their historical synchronous behavior.
            return
        stage = getattr(self, "_attached_stage", None)
        ownership_gate = getattr(stage, "_ovui_frame_lock", None)
        if ownership_gate is None:
            with transition_lock:
                self._stop_native_frame_pacing_locked(
                    reason,
                    capture_selected_camera=capture_selected_camera,
                    pause_render=pause_render,
                )
            return
        # Lock order is always Stage ownership gate, then adapter transition.
        # begin_frame already holds the RLock when its revocation callback
        # reaches here; re-entry is intentional and covers the full frame.
        wait_scope = self.start_ovui_performance_scope(
            "OvstageRendererAdapter.native_pacing.lock_wait"
        )
        try:
            with ownership_gate, transition_lock:
                self.end_ovui_performance_scope(wait_scope)
                wait_scope = None
                self._stop_native_frame_pacing_locked(
                    reason,
                    capture_selected_camera=capture_selected_camera,
                    pause_render=pause_render,
                )
        finally:
            self.end_ovui_performance_scope(wait_scope)

    def _stop_native_frame_pacing_locked(
        self,
        reason: str,
        *,
        capture_selected_camera: bool,
        pause_render: bool = False,
    ) -> None:
        token = int(getattr(self, "_frame_pacing_token", 0) or 0)
        self._frame_pacing_pick_snapshot = None
        self._frame_pacing_pick_generated = False
        self._frame_pacing_pick_association_unavailable = False
        # Every Python Stage publication requires one synchronous renderer
        # update/step before native pacing may resume, even when no native
        # borrow had started yet.
        self._frame_pacing_needs_sync_step = True
        if not token:
            return
        self._frame_pacing_presented_snapshot = None
        native_ui = self._frame_pacing_bindings()
        if native_ui is None:
            raise RuntimeError(
                "native frame pacing bindings disappeared while OVStage "
                f"ownership was pinned before {reason}"
            )
        if capture_selected_camera:
            self._frame_pacing_pick_association_unavailable = True
            try:
                status = dict(native_ui._get_native_frame_pacing_status())
                self._frame_pacing_pick_generated = bool(
                    status.get("selected_image_is_generated", False)
                )
                selected_world = status.get("selected_camera_world")
                projection = self._frame_pacing_projection
                size = self._frame_pacing_size
                if (
                    not self._frame_pacing_pick_generated
                    and selected_world is not None
                    and projection is not None
                    and size is not None
                ):
                    world = np.asarray(selected_world, dtype=np.float64).reshape(4, 4)
                    selected_view = np.linalg.inv(world.T)
                    projection_array = np.asarray(
                        projection, dtype=np.float64
                    ).reshape(4, 4)
                    selected_size = (int(size[0]), int(size[1]))
                    if (
                        np.all(np.isfinite(selected_view))
                        and np.all(np.isfinite(projection_array))
                        and selected_size[0] > 0
                        and selected_size[1] > 0
                    ):
                        self._frame_pacing_pick_snapshot = CameraSnapshot.capture(
                            selected_view,
                            projection_array,
                            selected_size,
                        )
                        self._frame_pacing_pick_association_unavailable = False
            except (
                IndexError,
                KeyError,
                OverflowError,
                TypeError,
                ValueError,
                np.linalg.LinAlgError,
            ):
                self._frame_pacing_pick_snapshot = None
        if pause_render and bool(self._profile_ovui_call(
            "OvstageRendererAdapter.native_pacing.pause_render",
            native_ui._native_frame_pacing_pause_render, token,
        )):
            self._frame_pacing_render_paused = True
            return
        drain_scope = self.start_ovui_performance_scope(
            "OvstageRendererAdapter.native_pacing.drain"
        )
        try:
            while not bool(native_ui._native_frame_pacing_stop(token)):
                time.sleep(0.001)
        finally:
            self.end_ovui_performance_scope(drain_scope)
        self._frame_pacing_token = 0
        self._frame_pacing_render_paused = False
        self._last_pushed_camera_state = None
        stage = self._attached_stage
        if stage is not None:
            _reconcile_native_write_floor(stage)

    def _publish_native_frame(
        self,
        width: int,
        height: int,
        view_matrix: Any,
        proj_matrix: Any,
    ) -> bool:
        """Publish raw camera intent; native owns Stage writes and steps."""

        transition_lock = getattr(self, "_frame_pacing_transition_lock", None)
        if transition_lock is None:
            return False
        stage = getattr(self, "_attached_stage", None)
        ownership_gate = getattr(stage, "_ovui_frame_lock", None)
        if ownership_gate is None:
            return False
        # Atomically establish the native borrow only after every complete
        # Python Stage frame has released the same gate. A later begin_frame
        # acquires this gate first and revokes/joins the borrower before it
        # reserves or publishes its next ordinal.
        with ownership_gate, transition_lock:
            if not self._frame_pacing_eligible():
                if self._frame_pacing_token:
                    self._stop_native_frame_pacing_locked(
                        "capability fallback",
                        capture_selected_camera=False,
                    )
                if self._frame_pacing_restore_overlap:
                    self.set_ldr_overlap_enabled(True)
                    self._frame_pacing_restore_overlap = False
                return False
            size = (int(width), int(height))
            projection = np.ascontiguousarray(
                proj_matrix, dtype=np.float64
            ).reshape(4, 4)
            camera_path = self._runtime_camera_path()
            if camera_path is None:
                return False
            projection_intrinsics_changed = False
            current_projection = self._frame_pacing_projection
            if current_projection is None:
                projection_intrinsics_changed = True
            else:
                projection_intrinsics_changed = (
                    abs(float(projection[0, 0]) - float(current_projection[0, 0]))
                    > 1e-12
                    or abs(float(projection[1, 1]) - float(current_projection[1, 1]))
                    > 1e-12
                )
            if self._frame_pacing_token and (
                size != self._frame_pacing_size
                or camera_path != self._frame_pacing_camera_path
                # Dolly changes near/far only; ovrtx camera authoring consumes fx/fy.
                or projection_intrinsics_changed
            ):
                self._stop_native_frame_pacing_locked(
                    "resolution or camera intrinsics change",
                    capture_selected_camera=False,
                    pause_render=True,
                )
                return False
            native_ui = self._frame_pacing_bindings()
            if native_ui is None:
                return False
            if self._frame_pacing_token and self._native_render_is_paused():
                if self._in_flight_pick_queries:
                    return False
                if not bool(
                    native_ui._native_frame_pacing_resume_render(
                        self._frame_pacing_token,
                    )
                ):
                    self._stop_native_frame_pacing_locked(
                        "failed render-worker resume",
                        capture_selected_camera=False,
                        pause_render=False,
                    )
                    return False
                self._frame_pacing_render_paused = False
                self._frame_pacing_needs_sync_step = False
            if self._frame_pacing_needs_sync_step:
                return False
            if not self._frame_pacing_token:
                borrow = self._borrow_native_frame_pacing_state(camera_path)
                if borrow is None:
                    return False
                restore_overlap = self._ldr_overlap is not None
                self.set_ldr_overlap_enabled(False)
                (
                    renderer_address,
                    library_path,
                    stage_address,
                    camera_query,
                    committed_ordinal,
                    render_var_stride,
                    render_var_name_offset,
                    render_var_handle_offset,
                ) = borrow
                token = int(
                    native_ui._native_frame_pacing_start_ovstage(
                        renderer_address,
                        library_path,
                        render_var_stride,
                        render_var_name_offset,
                        render_var_handle_offset,
                        stage_address,
                        camera_query,
                        committed_ordinal,
                        self._frame_pacing_provider,
                        str(self._render_product_path),
                        camera_path,
                        size[0],
                        size[1],
                    )
                    or 0
                )
                if not token:
                    if restore_overlap:
                        self.set_ldr_overlap_enabled(True)
                    return False
                self._frame_pacing_restore_overlap = (
                    self._frame_pacing_restore_overlap or restore_overlap
                )
                self._frame_pacing_token = token
                self._frame_pacing_size = size
                self._frame_pacing_projection = projection.copy()
                self._frame_pacing_camera_path = camera_path

            raw_world = _view_to_ovrtx_transform(view_matrix).reshape(4, 4)
            publication_time = time.perf_counter()
            velocity = self._frame_pacing_velocity
            published = bool(
                native_ui._native_frame_pacing_publish(
                    self._frame_pacing_token,
                    size[0],
                    size[1],
                    raw_world.reshape(-1),
                    velocity,
                    publication_time,
                )
            )
            if not published:
                self._stop_native_frame_pacing_locked(
                    "failed camera publication",
                    capture_selected_camera=False,
                )
            return published

    def _release_retained_output(self) -> None:
        """Release the retained step result and presentation cache.

        MUST run immediately before every ownership-invalidating native
        mutation (OVStage attach/detach, renderer reset, teardown), after
        any cheap early-return guard of the enclosing boundary function.
        An ovrtx step-result container holds native output handles; letting
        one live across a native mutation is undefined. Idempotent and cheap
        when nothing is retained.
        """
        if int(getattr(self, "_frame_pacing_token", 0) or 0) and (
            not self._native_render_is_paused()
        ):
            self._stop_native_frame_pacing("renderer or Stage mutation")
        overlap = getattr(self, "_ldr_overlap", None)
        if overlap is not None:
            overlap.release(clear_presentation=True)

    @property
    def presented_camera_snapshot(self) -> Optional[CameraSnapshot]:
        """Complete camera state of the image returned by ``render_frame``.

        The viewport uses this to drive scene-overlay (gizmo/outline)
        matrices so overlays always match the visible image, which under
        overlap is one frame older than the just-submitted camera. ``None``
        when the overlap is disabled or nothing has been presented; callers
        then fall back to the matrices they submitted.
        """
        metadata = getattr(self, "_presented_async_metadata", None)
        if metadata is not None:
            return CameraSnapshot.capture(
                metadata.view_matrix,
                metadata.projection_matrix,
                metadata.extent,
            )
        one_shot = getattr(self, "_frame_pacing_presented_snapshot", None)
        if one_shot is not None:
            return one_shot
        overlap = getattr(self, "_ldr_overlap", None)
        return overlap.presented_snapshot if overlap is not None else None

    def set_ldr_overlap_enabled(self, enabled: bool) -> bool:
        """Opt the continuous frame loop in or out of the depth-one overlap.

        ``render_frame`` stays fully synchronous (historical contract) until
        a frame-loop consumer opts in. Disabling releases any retained
        output. ``OVGEAR_LDR_OVERLAP=0`` vetoes enablement (kill switch).
        Returns whether the overlap is enabled after the call.
        """
        if enabled and _ldr_overlap_env_enabled():
            if getattr(self, "_ldr_overlap", None) is None:
                self._ldr_overlap = LdrOverlapState()
            return True
        self._release_retained_output()
        self._ldr_overlap = None
        return False

    def _ldr_overlap_allowed(self) -> bool:
        """Whether the overlap may present a retained frame this call.

        Gated OFF (synchronous behavior, retained released) when the single
        per-frame LdrColor mapping is shared with another consumer:
        livestream tee, tier-2 zero-copy GPU ingest, or a render-var output
        request targeting the active product's LdrColor. An ovrtx render var
        must not be mapped twice, and those paths have their own
        synchronization/lifetime designs.
        """
        if getattr(self, "_ldr_overlap", None) is None:
            return False
        if getattr(self, "_livestream", None) is not None:
            return False
        zero_copy = self._zero_copy_state
        if zero_copy is not None and zero_copy.gpu_pending:
            return False
        product = str(self._render_product_path or "")
        for request in getattr(self, "_render_var_output_requests", {}).values():
            if str(getattr(request, "render_product_path", "")) != product:
                continue
            var_name = (getattr(request, "render_var_name", "") or "").lower()
            output_id = (getattr(request, "output_id", "") or "").lower()
            if "ldr" in var_name or "ldr" in output_id:
                return False
        return True

    def instrumentation_target(self) -> Any | None:
        """Return the native renderer for optional instrumentation."""

        return self._renderer

    def create_secondary_viewport_renderer(self) -> Any:
        """TEMP: expose a second product without creating a second OVRTX renderer."""

        self._secondary_viewport_active = True
        self.set_ldr_overlap_enabled(False)
        return _SecondaryViewportRendererAdapter(self)

    def start_ovui_performance_scope(self, function_name: str) -> Any:
        """Start an optional, thread-aware timing scope; return its token."""

        return get_instrumentation().begin_scope(self, function_name)

    def end_ovui_performance_scope(self, token: Any) -> None:
        """End a scope returned by :meth:`start_ovui_performance_scope`."""

        if token is not None:
            get_instrumentation().end_scope(self, token)

    def _profile_ovui_call(
        self,
        function_name: str,
        function: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        token = self.start_ovui_performance_scope(function_name)
        try:
            return function(*args, **kwargs)
        finally:
            self.end_ovui_performance_scope(token)

    def _start_render_worker(self) -> None:
        """Start the thread that exclusively advances asynchronous OVRTX frames."""

        worker = self._render_worker_thread
        if worker is not None and worker.is_alive():
            return
        self._render_worker_stop.clear()
        self._render_worker_wake.clear()
        worker = threading.Thread(
            target=self._render_worker_main,
            name=_RENDER_WORKER_THREAD_NAME,
            daemon=True,
        )
        self._render_worker_thread = worker
        worker.start()

    def _stop_render_worker(self) -> None:
        """Stop asynchronous rendering before invalidating native ownership."""

        worker = self._render_worker_thread
        if worker is None:
            return
        self._render_worker_stop.set()
        self._render_worker_wake.set()
        if worker is not threading.current_thread():
            worker.join(timeout=_RENDER_WORKER_SHUTDOWN_TIMEOUT_SECONDS)
        if worker.is_alive():
            raise RuntimeError("OVRTX render worker did not stop before renderer shutdown")
        self._render_worker_thread = None

    def _render_worker_main(self) -> None:
        """Own OVRTX submit, completion polling, and output extraction."""

        while not self._render_worker_stop.is_set():
            self._render_worker_wake.wait()
            self._render_worker_wake.clear()
            while not self._render_worker_stop.is_set():
                with self._render_state_lock:
                    presentation_pending = bool(self._presentation_pending_viewports)
                    requests_pending = bool(self._queued_viewport_renders)
                if presentation_pending:
                    break
                if self._in_flight_render_batch is None and not requests_pending:
                    break

                render_thread_scope = self.start_ovui_performance_scope(RENDER_THREAD_SCOPE)
                try:
                    self._submit_enqueued_render_frames_impl()
                except BaseException as exc:
                    self._in_flight_render_batch = None
                    self._dispatch_pending_pick_misses()
                    with self._render_state_lock:
                        if self._render_worker_error is None:
                            self._render_worker_error = exc
                    break
                finally:
                    self.end_ovui_performance_scope(render_thread_scope)
                if self._in_flight_render_batch is not None:
                    self._render_worker_wake.wait(_RENDER_WORKER_RETRY_SECONDS)
                    self._render_worker_wake.clear()

    def enqueue_render_frame(
        self,
        viewport_id: str,
        generation: int,
        width: int,
        height: int,
        view_matrix: Matrix4d,
        proj_matrix: Matrix4d,
    ) -> None:
        """Queue the primary viewport for the next batched OVRTX step."""

        self._enqueue_viewport_render_frame(
            viewport_id,
            generation,
            str(self._render_product_path),
            width,
            height,
            view_matrix,
            proj_matrix,
            primary=True,
        )

    def _enqueue_viewport_render_frame(
        self,
        viewport_id: str,
        generation: int,
        render_product_path: str,
        width: int,
        height: int,
        view_matrix: Matrix4d,
        proj_matrix: Matrix4d,
        *,
        primary: bool,
    ) -> None:
        return self._enqueue_viewport_render_frame_impl(
            viewport_id,
            generation,
            render_product_path,
            width,
            height,
            view_matrix,
            proj_matrix,
            primary=primary,
        )

    def _enqueue_viewport_render_frame_impl(
        self,
        viewport_id: str,
        generation: int,
        render_product_path: str,
        width: int,
        height: int,
        view_matrix: Matrix4d,
        proj_matrix: Matrix4d,
        *,
        primary: bool,
    ) -> None:
        request = _QueuedViewportRender(
            viewport_id=str(viewport_id),
            generation=int(generation),
            render_product_path=str(render_product_path),
            width=max(int(width), 1),
            height=max(int(height), 1),
            view_matrix=_coerce_matrix4(view_matrix).copy(),
            projection_matrix=_coerce_matrix4(proj_matrix).copy(),
            primary=bool(primary),
        )
        # Keep only the newest not-yet-submitted request per viewport.
        with self._render_state_lock:
            self._queued_viewport_renders[request.viewport_id] = request

    def poll_render_frame(self, viewport_id: str) -> RenderFrameResult | None:
        """Return one completed viewport frame without touching OVRTX."""

        self._drain_completed_pick_callbacks()
        with self._render_state_lock:
            error = self._render_worker_error
            self._render_worker_error = None
            frame = (
                None
                if error is not None
                else self._completed_viewport_frames.pop(str(viewport_id), None)
            )
        if error is not None:
            raise RuntimeError("OVRTX render worker failed") from error
        return frame

    def release_render_frame(self, metadata: RenderFrameMetadata) -> None:
        """Release renderer backpressure after a frame was discarded by the UI."""

        with self._render_state_lock:
            self._presentation_pending_viewports.discard(str(metadata.viewport_id))
        self._render_worker_wake.set()

    def mark_render_frame_presented(self, metadata: RenderFrameMetadata) -> None:
        """Publish the camera identity that now backs the visible image."""

        return self._mark_render_frame_presented_impl(metadata)

    def _mark_render_frame_presented_impl(self, metadata: RenderFrameMetadata) -> None:
        if metadata.render_product_path == str(self._render_product_path):
            self._presented_async_metadata = metadata
            self._last_view_matrix = _coerce_matrix4(metadata.view_matrix)
            self._last_proj_matrix = _coerce_matrix4(metadata.projection_matrix)
        self.release_render_frame(metadata)

    def submit_enqueued_render_frames(self) -> bool:
        """Wake the renderer thread after all active viewports are queued."""

        with self._render_state_lock:
            has_requests = bool(self._queued_viewport_renders)
        self._render_worker_wake.set()
        return has_requests

    def _submit_enqueued_render_frames_impl(self) -> bool:
        self._poll_in_flight_render_batch(_RENDER_WORKER_WAIT_TIMEOUT_NS)
        if self._in_flight_render_batch is not None:
            return False
        with self._render_state_lock:
            if self._presentation_pending_viewports:
                return False
            if not self._queued_viewport_renders:
                return False
            requests = self._queued_viewport_renders
            self._queued_viewport_renders = {}
        if self._attached_stage is None:
            for request in requests.values():
                image = np.zeros((request.height, request.width, 4), dtype=np.uint8)
                image[..., 3] = 255
                self._render_frame_sequence += 1
                metadata = RenderFrameMetadata(
                    sequence=self._render_frame_sequence,
                    generation=request.generation,
                    viewport_id=request.viewport_id,
                    render_product_path=request.render_product_path,
                    extent=(request.width, request.height),
                    view_matrix=request.view_matrix,
                    projection_matrix=request.projection_matrix,
                    ordinal=0,
                )
                self._store_completed_viewport_frame(
                    RenderFrameResult(image=image, metadata=metadata)
                )
            return True

        self._consume_render_settings_renderer_update()
        for request in requests.values():
            if request.primary:
                self._apply_resolution(request.width, request.height)
                self._last_view_matrix = request.view_matrix
                self._last_proj_matrix = request.projection_matrix
                self._push_view_camera_state(
                    request.view_matrix,
                    request.projection_matrix,
                )
            else:
                self._apply_secondary_resolution(request.width, request.height)
                self._push_secondary_view_camera_state(
                    request.view_matrix,
                    request.projection_matrix,
                )

        now = time.perf_counter()
        dt = max(_MIN_DT, min(_MAX_DT, now - self._dt_clock))
        self._dt_clock = now
        ordinal = int(getattr(self._scene, "current_ordinal", 0) or 0)
        self._render_frame_sequence += 1
        sequence = self._render_frame_sequence
        metadata = {
            request.viewport_id: RenderFrameMetadata(
                sequence=sequence,
                generation=request.generation,
                viewport_id=request.viewport_id,
                render_product_path=request.render_product_path,
                extent=(request.width, request.height),
                view_matrix=request.view_matrix,
                projection_matrix=request.projection_matrix,
                ordinal=ordinal,
            )
            for request in requests.values()
        }
        product_paths = {
            request.render_product_path for request in requests.values()
        }
        product_paths.update(
            request.render_product_path
            for request in self._point_cloud_requests.values()
            if request.render_product_path
        )
        product_paths.update(
            request.render_product_path
            for request in self._render_var_output_requests.values()
            if request.render_product_path
        )
        operation = self._renderer.step_async(
            render_products=product_paths,
            delta_time=dt,
            ordinal=ordinal,
        )
        self._borrow_step_count += 1
        self._in_flight_render_batch = _InFlightRenderBatch(
            operation=operation,
            metadata=metadata,
            requests=requests,
        )
        return True

    def _store_completed_viewport_frame(self, frame: RenderFrameResult) -> None:
        return self._store_completed_viewport_frame_impl(frame)

    def _store_completed_viewport_frame_impl(self, frame: RenderFrameResult) -> None:
        with self._render_state_lock:
            previous = self._completed_viewport_frames.get(frame.metadata.viewport_id)
            if previous is not None:
                close = getattr(previous.image, "close", None)
                if callable(close):
                    close()
            self._completed_viewport_frames[frame.metadata.viewport_id] = frame
            self._presentation_pending_viewports.add(frame.metadata.viewport_id)

    def _discard_async_render_state(self) -> None:
        """Release queued/completed presentation state at ownership edges."""

        return self._discard_async_render_state_impl()

    def _discard_async_render_state_impl(self) -> None:
        with self._render_state_lock:
            self._queued_viewport_renders.clear()
            for frame in self._completed_viewport_frames.values():
                close = getattr(frame.image, "close", None)
                if callable(close):
                    close()
            self._completed_viewport_frames.clear()
            self._presentation_pending_viewports.clear()
            self._completed_pick_callbacks.clear()
            self._render_worker_error = None
        self._in_flight_render_batch = None
        self._presented_async_metadata = None

    def _poll_in_flight_render_batch(self, timeout_ns: int) -> None:
        return self._poll_in_flight_render_batch_impl(timeout_ns)

    def _poll_in_flight_render_batch_impl(self, timeout_ns: int) -> None:
        batch = self._in_flight_render_batch
        if batch is None:
            return
        pending = batch.operation.wait(timeout_ns=int(timeout_ns))
        if pending is None:
            return
        products = pending.fetch(timeout_ns=0)
        if products is None:
            return
        self._in_flight_render_batch = None
        self._dispatch_pending_pick_results(products)
        self._extract_requested_point_cloud_frames(products)
        self._extract_requested_render_var_output_frames(products)
        for viewport_id, request in batch.requests.items():
            uses_point_cloud_overlay = False
            if request.primary:
                uses_point_cloud_overlay = self._active_product_uses_point_cloud_overlay()
            if request.primary and uses_point_cloud_overlay:
                image = np.zeros((request.height, request.width, 4), dtype=np.uint8)
                image[..., 3] = 255
            elif request.primary:
                image = self._extract_ldr_color(
                    products,
                    request.width,
                    request.height,
                )
            else:
                image = self._extract_product_ldr_color_cpu(
                    products,
                    request.render_product_path,
                    request.width,
                    request.height,
                )
            self._store_completed_viewport_frame(
                RenderFrameResult(image=image, metadata=batch.metadata[viewport_id]),
            )
            self._successful_frame_count += 1

    def _queue_secondary_viewport_frame(
        self,
        width: int,
        height: int,
        view_matrix: Matrix4d,
        proj_matrix: Matrix4d,
    ) -> np.ndarray:
        width = max(int(width), 1)
        height = max(int(height), 1)
        self._secondary_viewport_request = (
            width,
            height,
            view_matrix,
            proj_matrix,
        )
        frame = self._secondary_viewport_frame
        if frame is None:
            frame = np.zeros((height, width, 4), dtype=np.uint8)
            frame[..., 3] = 255
        return frame

    def _extract_product_ldr_color_cpu(
        self,
        products: Any,
        product_path: str,
        width: int,
        height: int,
    ) -> np.ndarray:
        try:
            render_var = self._presentation_render_var(products, product_path)
            frame = self._map_presentation_frame_cpu(render_var)
        except Exception as exc:
            if _require_real_ovrtx():
                raise RuntimeError(
                    "ovrtx multi-viewport output map failed "
                    f"for {product_path} ({type(exc).__name__}: {exc})"
                ) from exc
            frame = np.zeros((height, width, 4), dtype=np.uint8)
        return _normalize_rgba(frame, width, height)

    def _render_multi_viewport_frame(
        self,
        width: int,
        height: int,
        view_matrix: Matrix4d,
        proj_matrix: Matrix4d,
    ) -> np.ndarray:
        self._apply_resolution(width, height)
        request = self._secondary_viewport_request
        if request is None:
            secondary_width = width
            secondary_height = height
            secondary_view = view_matrix
            secondary_projection = proj_matrix
        else:
            (
                secondary_width,
                secondary_height,
                secondary_view,
                secondary_projection,
            ) = request
        self._apply_secondary_resolution(
            secondary_width,
            secondary_height,
        )
        self._push_view_camera_state(view_matrix, proj_matrix)
        self._push_secondary_view_camera_state(
            secondary_view,
            secondary_projection,
        )
        now = time.perf_counter()
        dt = max(_MIN_DT, min(_MAX_DT, now - self._dt_clock))
        self._dt_clock = now
        ordinal = int(getattr(self._scene, "current_ordinal", 0) or 0)
        products = self._renderer.step(
            render_products=self._render_products_for_step(),
            delta_time=dt,
            ordinal=ordinal,
        )
        self._borrow_step_count += 1
        self._dispatch_pending_pick_results(products)
        self._extract_requested_point_cloud_frames(products)
        self._extract_requested_render_var_output_frames(products)
        primary_frame = self._extract_product_ldr_color_cpu(
            products,
            str(self._render_product_path),
            width,
            height,
        )
        self._secondary_viewport_frame = self._extract_product_ldr_color_cpu(
            products,
            self._secondary_render_product_path,
            secondary_width,
            secondary_height,
        )
        self._successful_frame_count += 1
        self._last_frame_shape = tuple(
            int(value) for value in primary_frame.shape
        )
        return primary_frame

    def render_frame(
        self,
        width: int,
        height: int,
        view_matrix: Matrix4d,
        proj_matrix: Matrix4d,
    ) -> Any | GpuFrameHandle:
        # A pacing pick may expose one synchronous selected-camera frame to
        # the viewport overlay. It is valid for exactly the UI composition
        # following that render and never survives into the next raw intent.
        self._frame_pacing_presented_snapshot = None
        width = max(int(width), 1)
        height = max(int(height), 1)
        if self._attached_stage is None:
            return np.zeros((height, width, 4), dtype=np.uint8)
        if self._secondary_viewport_active:
            return self._render_multi_viewport_frame(
                width,
                height,
                view_matrix,
                proj_matrix,
            )
        try:
            complete_camera = (
                np.asarray(view_matrix).shape == (4, 4)
                and np.asarray(proj_matrix).shape == (4, 4)
            )
        except Exception:
            complete_camera = False
        pacing_available = bool(
            complete_camera
            and getattr(self, "_frame_pacing_transition_lock", None) is not None
        )
        # Steady-state pacing performs no Python-side Stage or renderer
        # operation. Any ordinary OVStage publication first stops and drains
        # the native borrower through the Stage's publication barrier, then
        # comes through the synchronous path below once before pacing resumes.
        if pacing_available and self._profile_ovui_call(
            "OvstageRendererAdapter._publish_native_frame",
            self._publish_native_frame, width, height, view_matrix, proj_matrix,
        ):
            return None

        pacing_pick_snapshot = getattr(
            self, "_frame_pacing_pick_snapshot", None
        )
        if pacing_pick_snapshot is not None:
            view_matrix = pacing_pick_snapshot.view
            proj_matrix = pacing_pick_snapshot.projection
            width, height = pacing_pick_snapshot.size
        self._apply_resolution(width, height)
        # Shared render-setting lifecycle actuation (declared WARMUP
        # requirement): drain the per-edge pending ledger — one renderer
        # reset per owed committed edge — on the presentation thread, with
        # the retained-output ownership boundary released first; a faulted
        # drain stays blocked-with-reason until a defined recovery trigger.
        # The continuous frame loop supplies the warmup convergence steps.
        self._profile_ovui_call(
            "OvstageRendererAdapter._consume_render_settings_renderer_update",
            self._consume_render_settings_renderer_update,
        )
        # Pick/camera association under overlap: a pick enqueued this frame
        # resolves against THIS step, but the user aimed at the image on
        # screen — the frame presented LAST call. Submit that presented
        # camera instead so the pick ray matches the visible pixels. When
        # the substituted camera differs from the live one in ANY component
        # (view, projection, extract size), this step's color is rendered
        # with an already-shown camera: mark it presentation-skipped so the
        # visual stream stays monotonic (one explicit duplicate of the
        # current visible frame follows; static clicks change nothing).
        overlap = getattr(self, "_ldr_overlap", None)
        pick_skip = False
        if overlap is not None and self._in_flight_pick_queries:
            presented = overlap.presented_snapshot
            if presented is not None:
                if camera_state_differs(
                        presented, view_matrix, proj_matrix,
                        (width, height)):
                    pick_skip = True
                view_matrix = presented.view
                proj_matrix = presented.projection
        self._last_view_matrix = _coerce_matrix4(view_matrix)
        self._last_proj_matrix = _coerce_matrix4(proj_matrix)
        self._profile_ovui_call(
            "OvstageRendererAdapter._push_view_camera_state",
            self._push_view_camera_state, view_matrix, proj_matrix,
        )
        now = time.perf_counter()
        dt = max(_MIN_DT, min(_MAX_DT, now - self._dt_clock))
        self._dt_clock = now
        try:
            if not self._logged_first_step:
                self._logged_first_step = True
                print(
                    "[OvstageRendererAdapter] Renderer.step real_ovrtx_gpu_path "
                    f'device_hint="{self._gpu_device_name}" '
                    f"render_product={self._render_product_path}",
                    file=sys.stderr,
                )
            ordinal = int(getattr(self._scene, "current_ordinal", 0) or 0)
            products = self._renderer.step(
                render_products=self._render_products_for_step(),
                delta_time=dt,
                ordinal=ordinal,
            )
            self._borrow_step_count += 1
        except Exception as exc:
            # exceptional transition: never trust the retained container
            # across a failed step (renderer state is suspect).
            self._release_retained_output()
            self._dispatch_pending_pick_misses()
            self._mark_point_cloud_requests_stale(
                "step_failed",
                "Renderer step failed before PointCloud extraction.",
            )
            self._mark_render_var_output_requests_stale(
                "step_failed",
                "Renderer step failed before RenderVar output extraction.",
            )
            if _require_real_ovrtx():
                raise RuntimeError("ovrtx Renderer.step failed") from exc
            self._frame_pacing_pick_snapshot = None
            self._frame_pacing_pick_generated = False
            self._frame_pacing_pick_association_unavailable = False
            return np.zeros((height, width, 4), dtype=np.uint8)

        if pacing_available:
            self._frame_pacing_needs_sync_step = False
            self._frame_pacing_size = (int(width), int(height))
            self._frame_pacing_projection = np.ascontiguousarray(
                proj_matrix, dtype=np.float64
            ).reshape(4, 4).copy()
            self._frame_pacing_camera_path = self._runtime_camera_path() or ""
        if pacing_pick_snapshot is not None:
            self._frame_pacing_presented_snapshot = pacing_pick_snapshot
            self._frame_pacing_pick_snapshot = None

        self._profile_ovui_call(
            "OvstageRendererAdapter._dispatch_pending_pick_results",
            self._dispatch_pending_pick_results, products,
        )
        if not self._in_flight_pick_queries or pacing_pick_snapshot is not None:
            self._frame_pacing_pick_generated = False
            self._frame_pacing_pick_association_unavailable = False
        # Keep the stable native-pacing descriptor installed while the
        # synchronous Stage/resolution step completes. Sending its LdrColor to
        # ImageBridge here would replace the provider descriptor during the UI
        # frame and make the already-recorded ImGui texture ID unsafe.
        if self._native_render_is_paused():
            return None
        self._profile_ovui_call(
            "OvstageRendererAdapter._extract_requested_point_cloud_frames",
            self._extract_requested_point_cloud_frames, products,
        )
        self._profile_ovui_call(
            "OvstageRendererAdapter._extract_requested_render_var_output_frames",
            self._extract_requested_render_var_output_frames, products,
        )
        if self._active_product_uses_point_cloud_overlay():
            # A PointCloud-only product intentionally has no LdrColor render
            # var. Keep the normal ovui presentation loop alive with a neutral
            # RGBA canvas so the point-cloud viewport contribution can consume
            # the structured frame extracted above. This is presentation-only;
            # scene discovery comes from OVStage and point payloads come from
            # the OVRTX output mapping, never an OVRTX scene/data API.
            output = np.zeros((height, width, 4), dtype=np.uint8)
            output[..., 3] = 255
            self._point_cloud_background_fallback_count = int(
                getattr(self, "_point_cloud_background_fallback_count", 0) or 0
            ) + 1
            # The synthetic canvas never maps LdrColor; a container retained
            # for the previous product must not outlive the product switch.
            self._release_retained_output()
        elif overlap is None or not self._ldr_overlap_allowed():
            if overlap is not None:
                # Gated frame (livestream / zero-copy / LdrColor output
                # request): those paths share the single per-frame LdrColor
                # mapping and keep their existing synchronous behavior.
                overlap.release(clear_presentation=True)
            output = self._profile_ovui_call(
                "OvstageRendererAdapter._extract_ldr_color",
                self._extract_ldr_color, products, width, height,
            )
        else:
            # Depth-one overlap: present the PREVIOUS step's image (its GPU
            # work has had a full frame to finish, so the map cost is small
            # instead of ~one GPU frame) and retain ``products`` for the
            # next call. The retention key ties the retained container to
            # the stage, product, committed resolution, and renderer
            # identity — any change releases it and the next frame re-fills
            # synchronously (correct image, one slower frame, no flash).
            committed = getattr(self, "_last_resolution", None)
            retention_key = (
                id(self._attached_stage),
                str(self._render_product_path or ""),
                tuple(committed) if committed else None,
                id(self._renderer),
            )
            snapshot = CameraSnapshot.capture(
                view_matrix, proj_matrix, (width, height)
            )
            output = overlap.consume(
                products,
                retention_key,
                snapshot,
                lambda retained: self._profile_ovui_call(
                    "OvstageRendererAdapter._extract_ldr_color",
                    self._extract_ldr_color, retained, width, height,
                ),
                (height, width),
                pick_skip,
            )
        self._successful_frame_count = int(getattr(self, "_successful_frame_count", 0) or 0) + 1
        if isinstance(output, np.ndarray):
            self._last_frame_shape = tuple(int(value) for value in output.shape)
            if output.ndim >= 3 and output.shape[-1] >= 3:
                # EXACT nonblack-pixel count for the inspector/QA
                # nonempty-frame contract (a sparse single-pixel frame must
                # never read as empty). The naive per-pixel reduction cost
                # ~13 ms/frame at 1370x737 and gated the presentation loop;
                # viewing each RGBA pixel as one machine word and masking
                # off the alpha byte counts the same thing in one C pass
                # (~0.3 ms). Non-RGBA/uncontiguous frames take the exact
                # slow path (they are never the per-frame hot path).
                if (output.shape[-1] == 4 and output.dtype == np.uint8
                        and output.flags.c_contiguous):
                    rgb_mask = np.uint32(
                        0x00FFFFFF if sys.byteorder == "little"
                        else 0xFFFFFF00
                    )
                    self._last_frame_nonblack_pixels = int(np.count_nonzero(
                        output.reshape(-1).view(np.uint32) & rgb_mask
                    ))
                else:
                    self._last_frame_nonblack_pixels = int(np.count_nonzero(
                        np.any(output[..., :3] != 0, axis=-1)
                    ))
        else:
            self._last_frame_shape = (
                int(getattr(output, "height", height)),
                int(getattr(output, "width", width)),
                4,
            )
            self._last_frame_nonblack_pixels = None
        return output

    def set_resolution(self, width: int, height: int) -> None:
        """Resize only the provider-owned transient RenderProduct.

        Source products retain their populated resolution. Their mapped output
        is normalized to the viewport extent during presentation; changing a
        public product requires native authoring, never this transient path.
        """
        self._apply_resolution(max(int(width), 1), max(int(height), 1))

    @property
    def supports_live_local_transform(self) -> bool:
        """Whether the attached scene can accept native held-drag matrices."""

        scene = getattr(self, "_scene", None)
        stage = getattr(self, "_attached_stage", None)
        return bool(
            scene is not None
            and stage is not None
            and getattr(scene, "is_open", False)
            and getattr(scene, "_stage", None) is stage
            and callable(getattr(stage, "write_attribute", None))
            and callable(getattr(stage, "query_from_path_list", None))
            and callable(getattr(stage, "begin_frame", None))
            and callable(getattr(stage, "end_frame", None))
        )

    def set_live_local_transform(self, path: str, matrix: Matrix4d) -> bool:
        """Publish one native local-matrix preview through public OVStage.

        OVStage's borrowed OVRTX renderer has no separate transform overlay.
        The transient preview therefore advances the native ``omni:xform``
        column that OVRTX already consumes, while the scene change stream is
        suppressed so held moves remain outside semantic authoring events and
        undo history. Release/cancel lifecycle policy remains owned by the
        existing manipulator contract and its later Step 13 completion.
        """

        if not self.supports_live_local_transform:
            return False
        scene = self._scene
        stage = self._attached_stage
        normalized_path = _canonical_live_preview_path(path)
        if normalized_path is None or _is_presentation_path(
            scene,
            normalized_path,
            getattr(self, "_runtime_root_path", _RUNTIME_ROOT_LOCAL_PATH),
        ):
            return False
        values = _coerce_live_preview_matrix(matrix)
        if values is None:
            return False

        transform = getattr(self, "_live_transform_adapter", None)
        policy_cache = getattr(self, "_live_preview_policy_cache", None)
        if not isinstance(policy_cache, dict):
            policy_cache = {}
            self._live_preview_policy_cache = policy_cache
        if transform is None or getattr(transform, "_scene", None) is not scene:
            transform = OvstageTransformAdapter(scene)
            self._live_transform_adapter = transform
            policy_cache.clear()

        # The full transform edit policy is re-derived on EVERY preview write.
        # No verdict is ever reused: any policy input (physics playback, body
        # mode, control-target availability, controls identity, prim or
        # transform-column existence) may change mid-sequence, and a preview
        # write authorized by yesterday's policy is a stale authorization.
        # This stays off the held-drag critical path because the policy's
        # matrix-column probe is a narrow single-path native read, never the
        # ordinal-keyed full-stage bridge cache.  ``_live_preview_policy_cache``
        # records the most recent verdict per previewed path for diagnostics
        # only; it is never consulted for authorization.
        try:
            allowed = bool(
                transform.get_transform_edit_policy(
                    normalized_path
                ).direct_write_allowed
            )
        except Exception:
            return False
        policy_cache[normalized_path] = allowed
        if not allowed:
            return False

        started_ns = time.perf_counter_ns()
        try:
            self._stop_native_frame_pacing("live transform preview", pause_render=True)
            with scene.change_stream.suppress_notifications():
                ovstage = import_module("ovstage")
                with StageWriteBatch(stage, [normalized_path]) as batch:
                    batch.write_fixed(
                        _OVRTX_XFORM_ATTR,
                        values,
                        lanes=16,
                        semantic=ovstage.AttributeSemantic.MATRIX,
                    )
            native_ui = self._frame_pacing_bindings()
            token = int(getattr(self, "_frame_pacing_token", 0) or 0)
            ownership_gate = getattr(stage, "_ovui_frame_lock", None)
            transition_lock = getattr(self, "_frame_pacing_transition_lock", None)
            if (
                token
                and native_ui is not None
                and ownership_gate is not None
                and transition_lock is not None
            ):
                with ownership_gate, transition_lock:
                    if self._native_render_is_paused() and bool(
                        native_ui._native_frame_pacing_resume_render(token)
                    ):
                        self._frame_pacing_render_paused = False
                        self._frame_pacing_needs_sync_step = False
        except Exception:
            return False

        duration_ms = (time.perf_counter_ns() - started_ns) / 1_000_000.0
        self._live_preview_write_count = int(
            getattr(self, "_live_preview_write_count", 0) or 0
        ) + 1
        preview_paths = getattr(self, "_live_preview_paths", None)
        if not isinstance(preview_paths, set):
            preview_paths = set()
            self._live_preview_paths = preview_paths
        preview_paths.add(normalized_path)
        self._last_live_preview_path = normalized_path
        self._last_live_preview_matrix = tuple(
            float(value) for value in values.reshape(-1)
        )
        self._last_live_preview_write_duration_ms = duration_ms
        durations = getattr(self, "_live_preview_write_durations_ms", None)
        if not isinstance(durations, deque):
            durations = deque(maxlen=4096)
            self._live_preview_write_durations_ms = durations
        durations.append(duration_ms)
        return True

    def clear_live_local_transforms(self, paths: List[str]) -> None:
        """Discard preview bookkeeping without an additional native write."""

        preview_paths = getattr(self, "_live_preview_paths", None)
        if isinstance(preview_paths, set):
            preview_paths.difference_update(str(value) for value in paths or ())
        policy_cache = getattr(self, "_live_preview_policy_cache", None)
        if paths and isinstance(policy_cache, dict):
            # Diagnostic verdict record; scoped to one preview sequence.
            policy_cache.clear()
        if paths:
            self._live_preview_clear_count = int(
                getattr(self, "_live_preview_clear_count", 0) or 0
            ) + 1
        return None

    def get_active_camera_path(self) -> Optional[str]:
        return self._active_camera_common_path

    def set_active_camera_path(self, path: Optional[str]) -> bool:
        if path is None or str(path).strip() == "":
            common_path = None
        else:
            common_path = str(path)
        if common_path is not None and not common_path.startswith("/"):
            return False
        if common_path is not None and not self._path_has_type(
            common_path, ("Camera", "UsdGeomCamera")
        ):
            return False
        self._stop_native_frame_pacing("active camera change")
        # The viewport always renders through its private OVStage camera.  The
        # selected scene path identifies the camera whose pose the viewport
        # state adapter reads/authors; view/projection matrices are copied into
        # the private camera below.  Keeping the RenderProduct relationship
        # fixed also lets OVStage population own its Fabric connectivity.
        self._active_camera_common_path = common_path
        self._camera_path = self._runtime_camera_local_path
        return True

    def get_active_render_product_path(self) -> Optional[str]:
        return getattr(self, "_active_render_product_common_path", None) or getattr(
            self,
            "_render_product_path",
            None,
        )

    def set_active_render_product_path(self, path: Optional[str]) -> bool:
        if path is None or str(path).strip() == "":
            common_path = None
            render_product_path = self._default_render_product_path
        else:
            common_path = str(path)
            render_product_path = common_path
        if common_path is not None and not common_path.startswith("/"):
            return False
        if common_path is not None and not self._path_has_type(
            common_path, ("RenderProduct", "UsdRenderProduct")
        ):
            return False
        self._stop_native_frame_pacing("active render product change")
        self._render_product_path = render_product_path
        self._active_render_product_common_path = common_path
        # Target switching is a defined recovery trigger for the
        # render-settings update ledger.
        self._clear_render_settings_update_block()
        return True

    def activate_render_target(
        self,
        target_id: Optional[str] = None,
        render_product_path: Optional[str] = None,
    ) -> RenderTargetActivationResult:
        """Activate an OVStage-native RenderProduct for BORROW presentation."""

        current_path = self.get_active_render_product_path()
        if getattr(self, "_renderer", None) is None:
            return RenderTargetActivationResult.rejected_result(
                "Render target activation requires a renderer backend.",
                warning_code="unsupported",
                active_target_id=current_path or "",
                active_render_product_path=current_path or "",
            )
        requested_path = str(render_product_path or target_id or "").strip()
        if not requested_path:
            return RenderTargetActivationResult.rejected_result(
                "No render target was provided.",
                warning_code="missing_target",
                active_target_id=current_path or "",
                active_render_product_path=current_path or "",
            )
        fallback = getattr(
            self,
            "_default_render_product_path",
            _RENDER_PRODUCT_LOCAL_PATH,
        )
        normalized_path = _normalize_active_prim_path(requested_path, fallback)
        if normalized_path is None:
            return RenderTargetActivationResult.rejected_result(
                f"Render target path is not a valid prim path: {requested_path}",
                warning_code="unknown_target",
                active_target_id=current_path or "",
                active_render_product_path=current_path or "",
            )
        probe_error = self._probe_render_product_health(normalized_path)
        if probe_error:
            return RenderTargetActivationResult.rejected_result(
                (
                    f"Render target {normalized_path} cannot produce frames "
                    f"({probe_error}); the current render target stays active."
                ),
                warning_code="unrenderable_target",
                active_target_id=current_path or "",
                active_render_product_path=current_path or "",
            )
        # Selecting the provider-owned default product is the documented
        # "return to default presentation" flow: it maps onto the default
        # setter form (no public common path). Passing the private runtime
        # path through the public-path branch instead was rejected by the
        # public RenderProduct type check, leaving the picker's default
        # entry permanently unusable.
        accepted = self.set_active_render_product_path(
            None if normalized_path == fallback else normalized_path
        )
        active_path = self.get_active_render_product_path()
        if accepted or active_path == normalized_path:
            return RenderTargetActivationResult.accepted_result(
                active_target_id=normalized_path,
                active_render_product_path=active_path or normalized_path,
                message="Activated render target.",
            )
        return RenderTargetActivationResult.rejected_result(
            f"Renderer rejected render target: {normalized_path}",
            warning_code="backend_rejected",
            active_target_id=active_path or "",
            active_render_product_path=active_path or "",
        )

    def _presentation_render_var(self, products: Any, product_path: str) -> Any:
        """The exact presentation lookup used by the viewport step loop.

        Frame zero of the requested product must expose the LdrColor render
        var; anything else is not presentable by this viewport."""

        product = products[str(product_path)]
        frame = product.frames[0]
        return _render_var_by_source_name(frame, _LDR_VAR_NAME)

    def _map_presentation_frame_cpu(self, rv: Any) -> np.ndarray:
        """The exact CPU presentation mapping used by the viewport step loop."""

        mapping = rv.map(device=self._ovrtx.Device.CPU)
        mapping.__enter__()
        try:
            tensor = getattr(mapping, "tensor", mapping)
            try:
                return np.array(np.from_dlpack(tensor), copy=True)
            except (AttributeError, TypeError):
                if tensor is mapping:
                    raise
                return np.array(np.from_dlpack(mapping), copy=True)
        finally:
            mapping.__exit__(None, None, None)

    def _probe_render_product_health(self, product_path: str) -> str:
        """One BORROW-safe native probe step of a candidate RenderProduct.

        Catalog-level validation cannot see runtime-side rejection of a
        product (e.g. a RenderProduct the runtime constructs as incomplete,
        or one whose outputs omit the viewport's presentation render var).
        Committing such a product previously broke the presentation loop:
        successful frames froze while step/map failures flooded the log and
        the viewport presented stale pixels.  The probe steps ONLY the
        candidate product once, at the current committed ordinal, on the
        same presentation thread (no ownership or frame-overlap change), and
        then proves THE SAME presentation contract the viewport uses — the
        probe frame must yield a mappable LdrColor presentation image via
        the presentation path's own extraction and CPU mapping (a valid
        all-black image passes).  On failure the concrete reason is
        returned and the previously active product keeps rendering.
        Returns an empty string when healthy or when there is no live
        native pipeline to protect."""

        renderer = getattr(self, "_renderer", None)
        if renderer is None or getattr(self, "_attached_stage", None) is None:
            return ""
        path = str(product_path or "")
        if not path:
            return ""
        self._release_retained_output()
        try:
            ordinal = int(getattr(self._scene, "current_ordinal", 0) or 0)
            products = renderer.step(
                render_products={path},
                delta_time=_MIN_DT,
                ordinal=ordinal,
            )
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        try:
            rv = self._presentation_render_var(products, path)
        except Exception as exc:
            return (
                f"the runtime produced no mappable {_LDR_VAR_NAME} "
                f"presentation frame for this RenderProduct "
                f"({type(exc).__name__}: {exc})"
            )
        try:
            frame = self._map_presentation_frame_cpu(rv)
        except Exception as exc:
            return (
                f"the {_LDR_VAR_NAME} presentation output of this "
                f"RenderProduct cannot be mapped ({type(exc).__name__}: {exc})"
            )
        if not isinstance(frame, np.ndarray) or frame.size == 0:
            return (
                f"the mapped {_LDR_VAR_NAME} presentation output of this "
                "RenderProduct is empty"
            )
        return ""

    def list_point_cloud_outputs(
        self,
        render_product_path: Optional[str] = None,
    ) -> PointCloudOutputCatalog:
        active_path = str(
            render_product_path or self.get_active_render_product_path() or ""
        )
        snapshot = native_catalog_snapshot(self._scene)
        product = snapshot.prim(active_path)
        outputs: list[PointCloudOutputDescriptor] = []
        if product is not None and product.type_name.lower() in {
            "renderproduct",
            "usdrenderproduct",
        }:
            source_path = _first_catalog_path(product.value("camera"))
            source = snapshot.prim(source_path) if source_path else None
            for var_path in _catalog_paths(product.value("orderedVars")):
                render_var = snapshot.prim(var_path)
                if render_var is None or render_var.type_name.lower() not in {
                    "rendervar",
                    "usdrendervar",
                }:
                    continue
                source_name = str(render_var.value("sourceName") or "")
                if _source_token_key(source_name) != _RENDER_VAR_POINT_CLOUD_TOKEN:
                    continue
                channel_names = _catalog_string_values(render_var.value("channels"))
                channels = tuple(
                    descriptor
                    for name in channel_names
                    if (descriptor := _point_cloud_channel_descriptor(name)) is not None
                )
                missing_required = not {
                    "coordinates",
                    "counts",
                }.issubset({_source_token_key(channel.name) for channel in channels})
                reason = (
                    "Exact OVStage exposes no complete PointCloud channel catalog."
                    if missing_required
                    else ""
                )
                outputs.append(
                    PointCloudOutputDescriptor(
                        render_product_path=active_path,
                        render_var_name=source_name or "PointCloud",
                        source_sensor_path=source_path if source is not None else None,
                        source_sensor_name=(
                            source_path.rsplit("/", 1)[-1] if source else ""
                        ),
                        source_sensor_type=source.type_name if source is not None else "",
                        coordinate_space=PointCloudCoordinateSpace.UNKNOWN,
                        transform_to_world=(
                            source.value("worldMatrix") if source is not None else None
                        ),
                        channels=channels,
                        capabilities=(
                            ("point_cloud_catalog",) if not missing_required else ()
                        ),
                        warnings=(
                            (_point_cloud_warning("missing_channels", reason),)
                            if reason
                            else ()
                        ),
                        enabled=not missing_required and source is not None,
                        disabled_reason=reason or (
                            "PointCloud source target is unavailable."
                            if source is None
                            else ""
                        ),
                    )
                )
        return PointCloudOutputCatalog(
            outputs=tuple(outputs),
            active_render_product_path=active_path or None,
            revision=_native_catalog_revision(snapshot),
        )

    def set_point_cloud_request(
        self,
        viewport_id: str,
        request: Optional[PointCloudRequest],
    ) -> PointCloudRequestResult:
        self._ensure_point_cloud_state()
        viewport_key = str(viewport_id or "")
        if not viewport_key:
            return PointCloudRequestResult.rejected_result(
                "A viewport id is required.",
                warning_code="missing_viewport",
            )
        if request is None:
            self.clear_point_cloud_request(viewport_key)
            return PointCloudRequestResult.accepted_result(message="Point-cloud request cleared.")
        product_path = str(
            request.render_product_path or self.get_active_render_product_path() or ""
        )
        if not product_path:
            return PointCloudRequestResult.rejected_result(
                "A render product path is required.",
                warning_code="missing_render_product",
            )
        active_request = PointCloudRequest(
            viewport_id=viewport_key,
            render_product_path=product_path,
            render_var_name=request.render_var_name or "PointCloud",
            requested_channels=request.requested_channels,
            max_points=request.max_points,
            decimation_stride=request.decimation_stride,
            include_validity=request.include_validity,
            color_mode=request.color_mode,
            desired_coordinate_space=request.desired_coordinate_space,
        )
        descriptor = _point_cloud_output_for_request(
            self.list_point_cloud_outputs(product_path),
            active_request,
        )
        if descriptor is None:
            return PointCloudRequestResult.rejected_result(
                "Point-cloud output was not found.",
                warning_code="missing_output",
                active_request=active_request,
            )
        if not descriptor.is_available:
            return PointCloudRequestResult.rejected_result(
                descriptor.disabled_reason or "Point-cloud output is disabled.",
                warning_code="disabled_output",
                active_request=active_request,
            )
        previous = self._point_cloud_requests.get(viewport_key)
        if previous is not None and previous.render_product_path != product_path:
            self._latest_point_cloud_frames.pop(
                (viewport_key, previous.render_product_path),
                None,
            )
        self._point_cloud_requests[viewport_key] = active_request
        return PointCloudRequestResult.accepted_result(
            active_request=active_request,
            message="Point-cloud request accepted.",
        )

    def get_latest_point_cloud_frame(
        self,
        viewport_id: str,
        render_product_path: Optional[str] = None,
    ) -> Optional[PointCloudFrame]:
        self._ensure_point_cloud_state()
        viewport_key = str(viewport_id or "")
        if not viewport_key:
            return None
        if render_product_path:
            return self._latest_point_cloud_frames.get((viewport_key, str(render_product_path)))
        request = self._point_cloud_requests.get(viewport_key)
        if request is not None:
            return self._latest_point_cloud_frames.get((viewport_key, request.render_product_path))
        return next(
            (
                frame
                for (key, _path), frame in self._latest_point_cloud_frames.items()
                if key == viewport_key
            ),
            None,
        )

    def clear_point_cloud_request(self, viewport_id: str) -> None:
        self._ensure_point_cloud_state()
        viewport_key = str(viewport_id or "")
        self._point_cloud_requests.pop(viewport_key, None)
        for key in tuple(self._latest_point_cloud_frames):
            if key[0] == viewport_key:
                self._latest_point_cloud_frames.pop(key, None)

    def list_render_var_outputs(
        self,
        render_product_path: Optional[str] = None,
    ) -> RenderVarOutputCatalog:
        active_path = str(
            render_product_path or self.get_active_render_product_path() or ""
        )
        snapshot = native_catalog_snapshot(self._scene)
        product = snapshot.prim(active_path)
        render_mode = str(
            (product.value("omni:rtx:rendermode") if product is not None else "")
            or ""
        ) or "RealTimePathTracing"
        outputs: list[RenderVarOutputDescriptor] = []
        if product is not None and product.type_name.lower() in {
            "renderproduct",
            "usdrenderproduct",
        }:
            for var_path in _catalog_paths(product.value("orderedVars")):
                render_var = snapshot.prim(var_path)
                if render_var is None or render_var.type_name.lower() not in {
                    "rendervar",
                    "usdrendervar",
                }:
                    continue
                source_name = str(render_var.value("sourceName") or "")
                source_key = _source_token_key(source_name)
                if source_key in {_RENDER_VAR_LDR_TOKEN, _RENDER_VAR_POINT_CLOUD_TOKEN}:
                    continue
                spec = _RENDER_VAR_OUTPUT_SPECS.get(source_key)
                if spec is None:
                    outputs.append(
                        RenderVarOutputDescriptor(
                            render_product_path=active_path,
                            render_var_name=source_name or var_path.rsplit("/", 1)[-1],
                            output_kind=RenderVarOutputKind.UNKNOWN,
                            warnings=(
                                _render_var_warning(
                                    "unsupported_source",
                                    "The native RenderVar source is not supported for display.",
                                ),
                            ),
                            enabled=False,
                            disabled_reason="Unsupported native RenderVar source.",
                            revision_token=_native_catalog_revision(snapshot),
                            metadata={"source_path": var_path},
                        )
                    )
                    continue
                outputs.append(
                    RenderVarOutputDescriptor(
                        render_product_path=active_path,
                        render_var_name=source_name,
                        display_name=spec["display_name"],
                        output_kind=spec["output_kind"],
                        dtype=spec["dtype"],
                        component_count=spec["component_count"],
                        units=spec["units"],
                        value_range=spec["value_range"],
                        color_space=spec["color_space"],
                        validity_semantics=spec["validity_semantics"],
                        presets=(
                            RenderVarVisualizationPreset(
                                kind=spec["preset"],
                                label=spec["display_name"],
                            ),
                        ),
                        capabilities=spec["capabilities"],
                        enabled=(
                            source_key == "hdrcolor"
                            or render_mode == "RealTimePathTracing"
                        ),
                        disabled_reason=(
                            "Requires Real-Time 2.0."
                            if source_key != "hdrcolor"
                            and render_mode != "RealTimePathTracing"
                            else ""
                        ),
                        revision_token=_native_catalog_revision(snapshot),
                        metadata={
                            "source_path": var_path,
                            "source_name": source_name,
                            "render_mode": render_mode,
                            "source_type": str(render_var.value("sourceType") or ""),
                            "data_type": str(render_var.value("dataType") or ""),
                        },
                    )
                )
        return RenderVarOutputCatalog(
            outputs=tuple(outputs),
            active_render_product_path=active_path,
            revision=_native_catalog_revision(snapshot),
        )

    def get_aov_authoring_catalog(self) -> AovAuthoringCatalog:
        """Return the reviewed catalog for the installed native runtime."""

        version = getattr(self, "_ovrtx_version", "unknown")
        runtime_root = str(getattr(self, "_runtime_root_path", "") or "")
        version_text = ".".join(str(item) for item in version) if isinstance(
            version, tuple
        ) else str(version)
        recognized = isinstance(version, tuple) and tuple(version[:2]) == (0, 4)
        return AovAuthoringCatalog(
            runtime_version=version_text,
            outputs=_AOV_AUTHORING_OUTPUTS if recognized else (),
            render_modes=_AOV_RENDER_MODES if recognized else (),
            enabled=recognized,
            disabled_reason=(
                ""
                if recognized
                else f"ovrtx {version_text or 'unknown'} has no verified AOV catalog."
            ),
            template_render_product_path=str(
                getattr(self, "_runtime_render_product_path", "") or ""
            ),
            template_camera_path=str(
                getattr(self, "_runtime_camera_local_path", "") or ""
            ),
            template_ldr_render_var_path=(
                f"{runtime_root}/Render/Vars/LdrColor" if runtime_root else ""
            ),
        )

    def set_render_var_output_request(
        self,
        viewport_id: str,
        request: Optional[RenderVarOutputRequest],
    ) -> RenderVarOutputRequestResult:
        self._ensure_render_var_output_state()
        viewport_key = str(viewport_id or "")
        if not viewport_key:
            return RenderVarOutputRequestResult.rejected_result(
                "A viewport id is required.",
                warning_code="missing_viewport",
            )
        if request is None:
            self.clear_render_var_output_request(viewport_key)
            return RenderVarOutputRequestResult.accepted_result(
                message="RenderVar output request cleared."
            )
        product_path = str(
            request.render_product_path or self.get_active_render_product_path() or ""
        )
        if not product_path:
            return RenderVarOutputRequestResult.rejected_result(
                "A render product path is required.",
                warning_code="missing_render_product",
            )
        active_request = RenderVarOutputRequest(
            viewport_id=viewport_key,
            render_product_path=product_path,
            output_id=request.output_id,
            render_var_name=request.render_var_name,
            preset=request.preset,
            enable_probe=request.enable_probe,
            options=request.options,
        )
        descriptor = _render_var_output_for_request(
            self.list_render_var_outputs(product_path),
            active_request,
        )
        if descriptor is None:
            return RenderVarOutputRequestResult.rejected_result(
                "RenderVar output was not found.",
                warning_code="missing_output",
                active_request=active_request,
            )
        if not descriptor.is_available:
            return RenderVarOutputRequestResult.rejected_result(
                descriptor.disabled_reason or "RenderVar output is disabled.",
                warning_code="disabled_output",
                active_request=active_request,
            )
        active_request = RenderVarOutputRequest(
            viewport_id=viewport_key,
            render_product_path=descriptor.render_product_path,
            output_id=descriptor.output_id,
            render_var_name=descriptor.render_var_name,
            preset=request.preset,
            enable_probe=request.enable_probe,
            options=request.options,
        )
        previous = self._render_var_output_requests.get(viewport_key)
        if previous is not None:
            previous_key = (
                viewport_key,
                previous.render_product_path,
                previous.output_id,
            )
            next_key = (
                viewport_key,
                active_request.render_product_path,
                active_request.output_id,
            )
            if previous_key != next_key:
                self._latest_render_var_output_frames.pop(previous_key, None)
        self._render_var_output_requests[viewport_key] = active_request
        return RenderVarOutputRequestResult.accepted_result(
            active_request=active_request,
            message="RenderVar output request accepted.",
        )

    def get_latest_render_var_output_frame(
        self,
        viewport_id: str,
        render_product_path: Optional[str] = None,
    ) -> Optional[RenderVarOutputFrame]:
        self._ensure_render_var_output_state()
        viewport_key = str(viewport_id or "")
        if not viewport_key:
            return None
        request = self._render_var_output_requests.get(viewport_key)
        if request is not None:
            if render_product_path and request.render_product_path != str(render_product_path):
                return None
            return self._latest_render_var_output_frames.get(
                (viewport_key, request.render_product_path, request.output_id)
            )
        return next(
            (
                frame
                for (key, product_path, _output_id), frame in (
                    self._latest_render_var_output_frames.items()
                )
                if key == viewport_key
                and (not render_product_path or product_path == str(render_product_path))
            ),
            None,
        )

    def clear_render_var_output_request(self, viewport_id: str) -> None:
        self._ensure_render_var_output_state()
        viewport_key = str(viewport_id or "")
        self._render_var_output_requests.pop(viewport_key, None)
        for key in tuple(self._latest_render_var_output_frames):
            if key[0] == viewport_key:
                self._latest_render_var_output_frames.pop(key, None)

    def probe_render_var_output(
        self,
        request: RenderVarProbeRequest,
    ) -> RenderVarProbeResult:
        """Probe the owned host snapshot for one active RenderVar output.

        Pixel coordinates use a top-left origin. When both normalized
        coordinates are supplied they take precedence and map inclusively to
        ``[0, width - 1]`` and ``[0, height - 1]``. This method deliberately
        reads only the frame cache populated during ``render_frame``; it never
        maps an OVRTX output or accesses the OVRTX scene/data API.
        """

        self._ensure_render_var_output_state()
        viewport_key = str(request.viewport_id or "")
        if not viewport_key:
            return _render_var_probe_rejected(
                request,
                "A viewport id is required.",
                "missing_viewport",
            )
        active_request = self._render_var_output_requests.get(viewport_key)
        if active_request is None:
            return _render_var_probe_rejected(
                request,
                "No RenderVar output request is active for this viewport.",
                "no_request",
            )
        if not active_request.enable_probe:
            return _render_var_probe_rejected(
                request,
                "RenderVar probing is not enabled for this output request.",
                "probe_disabled",
            )
        if (
            request.render_product_path
            and request.render_product_path != active_request.render_product_path
        ):
            return _render_var_probe_rejected(
                request,
                "The requested RenderProduct is not active for this viewport.",
                "output_mismatch",
            )
        if request.output_id and request.output_id != active_request.output_id:
            return _render_var_probe_rejected(
                request,
                "The requested RenderVar output is not active for this viewport.",
                "output_mismatch",
            )
        if request.render_var_name and _source_token_key(
            request.render_var_name
        ) != _source_token_key(active_request.render_var_name):
            return _render_var_probe_rejected(
                request,
                "The requested RenderVar is not active for this viewport.",
                "output_mismatch",
            )
        frame = self._latest_render_var_output_frames.get(
            (
                viewport_key,
                active_request.render_product_path,
                active_request.output_id,
            )
        )
        if frame is None:
            return _render_var_probe_rejected(
                request,
                "No RenderVar frame is available.",
                "no_frame",
            )
        if request.frame_index is not None and request.frame_index != frame.frame_index:
            return _render_var_probe_rejected(
                request,
                "The requested RenderVar frame has been replaced.",
                "frame_replaced",
                frame=frame,
            )
        try:
            pixel_x, pixel_y = _render_var_probe_pixel(request, frame)
        except ValueError as exc:
            return _render_var_probe_rejected(
                request,
                str(exc),
                "out_of_bounds",
                frame=frame,
            )
        sample = _render_var_probe_sample(frame, pixel_x, pixel_y)
        raw_value = None if sample is None else _render_var_probe_raw_value(sample)
        if raw_value is None:
            return _render_var_probe_rejected(
                request,
                "No finite RenderVar sample is available at this pixel.",
                "no_data",
                frame=frame,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
            )
        if isinstance(raw_value, tuple) and len(raw_value) == 1 and int(frame.component_count) == 1:
            raw_value = raw_value[0]
        output_kind = _render_var_probe_output_kind(frame)
        if output_kind in (
            RenderVarOutputKind.CATEGORICAL_MASK,
            RenderVarOutputKind.METADATA_MAP,
        ):
            scalar = raw_value[0] if isinstance(raw_value, tuple) else raw_value
            if scalar is None:
                return _render_var_probe_rejected(
                    request,
                    "No category ID is available at this pixel.",
                    "no_data",
                    frame=frame,
                    pixel_x=pixel_x,
                    pixel_y=pixel_y,
                )
            category_id = int(round(float(scalar)))
            category_label = _render_var_probe_category_label(frame, category_id)
            return RenderVarProbeResult(
                accepted=True,
                render_product_path=frame.render_product_path,
                output_id=frame.output_id,
                render_var_name=frame.render_var_name,
                pixel_x=pixel_x,
                pixel_y=pixel_y,
                raw_value=category_id,
                normalized_value=category_id,
                display_value=f"ID {category_id}: {category_label}",
                category_id=category_id,
                category_label=category_label,
                units=frame.units,
                frame_index=frame.frame_index,
                stale=frame.stale,
                warnings=frame.warnings,
            )
        return RenderVarProbeResult(
            accepted=True,
            render_product_path=frame.render_product_path,
            output_id=frame.output_id,
            render_var_name=frame.render_var_name,
            pixel_x=pixel_x,
            pixel_y=pixel_y,
            raw_value=raw_value,
            normalized_value=_render_var_probe_normalized_value(
                raw_value,
                frame.value_range,
            ),
            display_value=_render_var_probe_display_value(raw_value, frame.units),
            units=frame.units,
            frame_index=frame.frame_index,
            stale=frame.stale,
            warnings=frame.warnings,
        )

    def _capture_render_settings_authorship_baseline(self) -> None:
        """Record the values this adapter's own load produced on its owner prims."""

        baseline: dict[str, dict[str, Any]] = {}
        for owner_path in (
            str(getattr(self, "_render_product_path", "") or ""),
            str(getattr(self, "_runtime_camera_local_path", "") or ""),
        ):
            if not owner_path:
                continue
            native = self._render_settings_native_adapter(owner_path)
            if native is None:
                continue
            values: dict[str, Any] = {}
            for attr_name in self._render_settings_records(native):
                try:
                    values[attr_name] = _render_setting_python_value(
                        native.get_value(attr_name)
                    )
                except Exception:
                    continue
            baseline[owner_path] = values
        self._render_settings_authorship_baseline = baseline

    def _render_setting_native_authored(
        self,
        owner_path: str,
        attr_name: str,
        current_value: Any,
    ) -> bool:
        """True only when ``current_value`` is a real opinion, not our own init.

        An attribute this adapter never initialised is somebody's opinion by
        definition. One it did initialise counts as authored only once its value
        has moved away from that initial value — which is exactly what a user
        edit does, and exactly what a reset undoes.
        """

        baseline = getattr(self, "_render_settings_authorship_baseline", None)
        if not isinstance(baseline, dict):
            return True
        owner_values = baseline.get(str(owner_path))
        if owner_values is None or attr_name not in owner_values:
            return True
        return not _render_setting_values_equal(owner_values[attr_name], current_value)

    def _render_settings_native_adapter(
        self,
        product_path: str,
        attr_names: Sequence[str] | None = None,
    ) -> Any | None:
        """Native property view of one RenderProduct prim, or None.

        Attribute discovery and values are copied from one exact-path native
        query.  This must not route through the general Property Inspector's
        full-stage compatibility cache: a render-mode edit is independent of
        scene size.  The returned view exposes typed records (dtype/semantic)
        plus decoded values.
        ``attr_names`` narrows the exact columns fetched to the ones a caller
        actually needs; the default discovers the public columns on this one
        owner path.
        """

        scene = getattr(self, "_scene", None)
        if scene is None or not getattr(scene, "is_open", False):
            return None
        try:
            stage = getattr(scene, "_stage", None)
            requested = (
                None
                if attr_names is None
                else tuple(
                    dict.fromkeys(
                        str(name) for name in attr_names if str(name)
                    )
                )
            )
            copied = read_path_attribute_records(
                stage,
                str(product_path),
                requested,
            )
            if not copied:
                return None
            exact: dict[str, _RenderSettingNativeRecord] = {}
            for attr_name, record in copied.items():
                if (
                    _render_setting_public_namespace(attr_name) is None
                    and _render_setting_builtin_spec(attr_name) is None
                ):
                    continue
                logical_is_array = (
                    record.native_is_array
                    and record.semantic not in _RS_STRING_SEMANTICS
                )
                exact[attr_name] = _RenderSettingNativeRecord(
                    name=record.name,
                    type_name=_render_setting_native_type_name(
                        record.dtype,
                        record.semantic,
                        logical_is_array,
                    ),
                    dtype=record.dtype,
                    semantic=record.semantic,
                    native_is_array=record.native_is_array,
                    is_array=logical_is_array,
                    value=record.value,
                )
            return _RenderSettingsNativeView(exact)
        except Exception:
            return None

    @staticmethod
    def _render_settings_records(native: Any | None) -> dict[str, Any]:
        if native is None:
            return {}
        records = getattr(native, "_attribute_records", None)
        return dict(records) if isinstance(records, dict) else {}

    def _private_viewport_quality_default(
        self,
        product_path: str,
        attr_name: str,
    ) -> int | None:
        """Instance default for the generated product only, never the schema."""

        private_path = str(getattr(self, "_default_render_product_path", "") or "")
        if (
            attr_name == "omni:rtx:quality"
            and private_path
            and product_path == private_path
        ):
            return getattr(self, "_viewport_quality", None)
        return None

    def list_render_settings(
        self,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingsCatalog:
        """Read public RenderProduct settings from the native OVStage store."""

        active_path = str(render_product_path or self.get_active_render_product_path() or "")
        if not active_path:
            return RenderSettingsCatalog(active_render_product_path=active_path)
        snapshot = native_catalog_snapshot(getattr(self, "_scene", None))
        prim = snapshot.prim(active_path)
        if prim is None or prim.type_name.lower() not in {
            "renderproduct",
            "usdrenderproduct",
        }:
            return RenderSettingsCatalog(active_render_product_path=active_path)
        native = self._render_settings_native_adapter(active_path)
        records = self._render_settings_records(native)

        owner_opinions = self._render_settings_owner_opinions_map()
        owner_unavailable = (
            ""
            if str(getattr(self, "_runtime_render_settings_local_path", "") or "")
            else (
                "The global RenderSettings prim is not available for the "
                "attached scene"
            )
        )

        settings: list[RenderSettingDescriptor] = []
        warnings: list[RenderSettingWarning] = []
        groups: dict[str, dict[str, Any]] = {}
        public_attr_names: set[str] = set()
        # Camera-owned settings (the exposure/autoExposure family) are authored
        # onto the runtime camera the active product renders through, so their
        # values have to be read from THERE. Reading them from the product is
        # what made every one of those rows report the default with
        # authored=False after a successful edit.
        camera_path = str(getattr(self, "_runtime_camera_local_path", "") or "")
        camera_native = (
            self._render_settings_native_adapter(camera_path) if camera_path else None
        )
        camera_records = self._render_settings_records(camera_native)
        for attr_name in sorted(records):
            if _render_setting_public_namespace(attr_name) is None:
                continue
            if _render_setting_spec_owner_scope(attr_name) in (
                _RENDER_SETTINGS_OWNER_SCOPE,
                _CAMERA_OWNER_SCOPE,
            ):
                # Neither is ever read from the product; a column that happens
                # to sit there is not what OVRTX reads.
                continue
            public_attr_names.add(attr_name)
            record = records[attr_name]
            try:
                current_value = _render_setting_python_value(
                    native.get_value(attr_name)
                )
                spec = _render_setting_builtin_spec(attr_name)
                if spec is not None:
                    descriptor = _render_setting_builtin_descriptor(
                        active_path,
                        spec,
                        current_value=current_value,
                        authored=self._render_setting_native_authored(
                            active_path, attr_name, current_value
                        ),
                        record=record,
                    )
                else:
                    descriptor = _render_setting_record_descriptor(
                        active_path,
                        record,
                        current_value,
                    )
            except Exception:
                warnings.append(
                    RenderSettingWarning(
                        code="setting_failed",
                        message="A RenderProduct setting could not be described.",
                    )
                )
                continue
            if descriptor is None:
                continue
            quality_default = self._private_viewport_quality_default(
                active_path, attr_name
            )
            if quality_default is not None:
                # Keep the native type/capabilities, but describe this adapter's
                # configured default instead of a process-wide schema default.
                authored = not _render_setting_values_equal(
                    current_value, quality_default
                )
                descriptor = replace(
                    descriptor,
                    default_value=quality_default,
                    has_default=True,
                    value_state=replace(
                        descriptor.value_state,
                        current_value=current_value,
                        default_value=quality_default,
                        has_default=True,
                        authored=authored,
                        inherited=not authored,
                    ),
                    revision_token=(
                        f"{active_path}:{attr_name}:{current_value!r}:"
                        f"{authored}:{quality_default!r}"
                    ),
                )
            settings.append(descriptor)
            group_metadata = groups.setdefault(
                descriptor.group_id,
                {"namespace": descriptor.namespace},
            )
            if spec is not None:
                group_metadata.update(_render_setting_builtin_metadata(spec))

        for spec in _RENDER_SETTINGS_BUILTIN_SPECS:
            attr_name = str(spec.get("attr_name") or "")
            if not attr_name or attr_name in public_attr_names:
                continue
            owner_scope = _render_setting_spec_owner_scope(attr_name)
            globally_owned = owner_scope == _RENDER_SETTINGS_OWNER_SCOPE
            camera_owned = owner_scope == _CAMERA_OWNER_SCOPE
            authored = globally_owned and attr_name in owner_opinions
            current_value = owner_opinions.get(attr_name) if authored else None
            camera_record = camera_records.get(attr_name) if camera_owned else None
            if camera_record is not None and camera_native is not None:
                try:
                    current_value = _render_setting_python_value(
                        camera_native.get_value(attr_name)
                    )
                except Exception:
                    current_value = None
                authored = current_value is not None and (
                    self._render_setting_native_authored(
                        camera_path, attr_name, current_value
                    )
                )
            descriptor = _render_setting_builtin_descriptor(
                active_path,
                spec,
                current_value=current_value,
                authored=authored,
                record=camera_record,
                owner_unavailable_reason=owner_unavailable if globally_owned else "",
            )
            if descriptor is None:
                continue
            settings.append(descriptor)
            groups.setdefault(
                descriptor.group_id,
                {"namespace": descriptor.namespace},
            ).update(_render_setting_builtin_metadata(spec))
        settings.sort(key=lambda item: (item.group_id, item.order, item.label, item.setting_id))
        providers = (
            (
                RenderSettingsProviderDescriptor(
                    provider_id=_RENDER_SETTINGS_PROVIDER_ID,
                    display_name=_RENDER_SETTINGS_PROVIDER_LABEL,
                    api_version="1",
                    capabilities=(
                        "render_settings_catalog",
                        "render_settings_value_state",
                    ),
                    isolation_key=active_path,
                ),
            )
            if settings
            else ()
        )
        return RenderSettingsCatalog(
            active_render_product_path=active_path,
            active_render_product_label=str(
                active_path.rsplit("/", 1)[-1] or active_path
            ),
            providers=providers,
            groups=_render_settings_group_descriptors(settings, groups),
            settings=tuple(settings),
            revision=f"{active_path}:{len(settings)}",
            warnings=tuple(warnings),
        )

    def read_render_setting(
        self,
        setting_id: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingValueState | None:
        descriptor = _render_setting_for_id(
            self.list_render_settings(render_product_path),
            setting_id,
        )
        return None if descriptor is None else descriptor.value_state

    def read_render_setting_value(
        self,
        attr_name: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> Any:
        """The effective value of ONE named setting, without the rest.

        Resolves the owner prim and applies the authored-else-default rule
        exactly as :meth:`list_render_settings` does for the same name, but
        fetches only that one native column — so a caller after a single
        token does not pay for the whole declared surface.
        """

        attr_name = str(attr_name or "")
        active_path = str(
            render_product_path or self.get_active_render_product_path() or ""
        )
        if not attr_name or not active_path:
            return None
        if _render_setting_public_namespace(attr_name) is None:
            # Not a described setting at all: the catalog has no row for it.
            return None
        spec = _render_setting_builtin_spec(attr_name)
        default_value = (
            _render_setting_python_value(
                _render_setting_builtin_metadata(spec).get("default")
            )
            if spec is not None
            else None
        )
        owner_scope = _render_setting_spec_owner_scope(attr_name)
        if owner_scope == _RENDER_SETTINGS_OWNER_SCOPE:
            # Globally owned values live in the adapter's own owner-layer
            # opinions, never on the product.
            opinions = self._render_settings_owner_opinions_map()
            if attr_name in opinions:
                return _render_setting_python_value(opinions[attr_name])
            return default_value
        owner_path = (
            str(getattr(self, "_runtime_camera_local_path", "") or "")
            if owner_scope == _CAMERA_OWNER_SCOPE
            else active_path
        )
        native = (
            self._render_settings_native_adapter(owner_path, (attr_name,))
            if owner_path
            else None
        )
        if native is None or attr_name not in self._render_settings_records(native):
            return default_value
        try:
            current_value = _render_setting_python_value(
                native.get_value(attr_name)
            )
        except Exception:
            return default_value
        if (
            spec is None
            or self._private_viewport_quality_default(owner_path, attr_name) is not None
        ):
            # Generic columns and the private viewport's quality use the live
            # value even when it equals the captured authorship baseline.
            return current_value
        if owner_scope == _CAMERA_OWNER_SCOPE and current_value is None:
            return default_value
        if self._render_setting_native_authored(
            owner_path, attr_name, current_value
        ):
            return current_value
        return default_value

    def subscribe_render_settings_changes(
        self,
        callback: Callable[[], None],
    ) -> _RenderSettingsSubscription:
        """Refresh settings views after apply, reset, undo, or redo.

        Every returned handle owns a UNIQUE tokenized record: subscribing the
        same callback twice yields two independently live subscriptions, and
        cancelling one can never remove another owner's record. Cancellation
        is idempotent.
        """

        subscribers = getattr(self, "_render_settings_subscribers", None)
        if not isinstance(subscribers, list):
            subscribers = []
            self._render_settings_subscribers = subscribers
        token = object()
        if callable(callback):
            subscribers.append((token, callback))

        def cancel() -> None:
            active = getattr(self, "_render_settings_subscribers", None)
            if isinstance(active, list):
                self._render_settings_subscribers = [
                    record for record in active if record[0] is not token
                ]

        return _RenderSettingsSubscription(cancel)

    def _notify_render_settings_changed(self) -> None:
        """Refresh render-settings views; interrupt-safe at command edges.

        Every subscriber is attempted exactly once. Ordinary ``Exception``
        failures stay isolated — subscriptions are disposable UI observers
        and a stale view must not invalidate an already accepted native
        state transition. Interrupt-class ``BaseException`` failures are
        NOT hidden, but they must never orphan a committed native value
        from its history entry: this notification runs after
        ``apply_native_value_edit`` committed the native state and BEFORE
        the command service records or moves the history edge, so the
        first captured interrupt re-raises only after all subscribers were
        attempted — as a fresh HISTORY-CONSISTENT-marked copy while a
        command-service edge is executing (upstream's committed-edge
        protocol: ``UndoManager`` push/undo/redo/grouped finalization then
        record or move the pending entry FIRST and re-raise the interrupt
        to the caller), and as a clean unmarked copy outside any edge
        (a caller-managed direct ``do()`` has no pending entry to protect).
        """

        interrupt: BaseException | None = None
        for _token, callback in tuple(
            getattr(self, "_render_settings_subscribers", ()) or ()
        ):
            try:
                callback()
            except Exception:
                # Ordinary observer failure: isolated, remaining
                # subscribers still get their delivery.
                continue
            except BaseException as exc:
                if interrupt is None:
                    interrupt = exc
        if interrupt is None:
            return
        if in_command_edge():
            raise history_consistent_interrupt(interrupt)
        raise interrupt_copy(interrupt)

    @property
    def render_settings_recovery_pending(self) -> bool:
        """Always False: native render-setting edits commit to ONE store.

        The legacy backing-USD/native divergence class that required a
        retained recovery ledger no longer exists — each edit is a single
        native value transaction with compensating rollback, so a failed
        edit leaves the store unchanged and there is nothing to recover."""

        return False

    def retry_render_settings_recovery(self) -> bool:
        """Kept for API compatibility; there is no divergence to recover."""

        return True

    def validate_render_setting(
        self,
        setting_id: str,
        value: Any,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingValidationResult:
        active_path = str(render_product_path or self.get_active_render_product_path() or "")
        if not active_path:
            return RenderSettingValidationResult.rejected_result(
                "No active RenderProduct is available.",
                setting_id=setting_id,
                warning_code="missing_render_product",
            )
        result, _descriptor = self._render_setting_validation_for(
            self.list_render_settings(active_path),
            setting_id,
            value,
        )
        return result

    def _render_setting_validation_for(
        self,
        catalog: Any,
        setting_id: str,
        value: Any,
    ) -> tuple[RenderSettingValidationResult, Any]:
        """Validate one value against a catalog the caller already holds.

        The resolved descriptor comes back with the result, so a caller that
        goes on to author the value does not have to describe the whole
        declared setting surface a second time to find the row it has just
        validated against.
        """

        descriptor = _render_setting_for_id(catalog, setting_id)
        if descriptor is None:
            return RenderSettingValidationResult.rejected_result(
                "Render setting is not available for this RenderProduct.",
                setting_id=setting_id,
                warning_code="unknown_setting",
            ), None
        if not descriptor.enabled or descriptor.disabled_reason:
            return RenderSettingValidationResult.rejected_result(
                descriptor.disabled_reason or "Render setting is disabled.",
                setting_id=descriptor.setting_id,
                warning_code="setting_disabled",
            ), descriptor
        if descriptor.value_type is RenderSettingValueType.UNKNOWN:
            return RenderSettingValidationResult.rejected_result(
                "Render setting value type is not supported.",
                setting_id=descriptor.setting_id,
                warning_code="unsupported_type",
            ), descriptor
        try:
            normalized = _render_setting_coerce_value(descriptor, value)
        except (TypeError, ValueError) as exc:
            return RenderSettingValidationResult.rejected_result(
                str(exc),
                setting_id=descriptor.setting_id,
                warning_code="invalid_value",
            ), descriptor
        valid, message, code = _render_setting_value_within_constraints(
            descriptor,
            normalized,
        )
        if not valid:
            return RenderSettingValidationResult.rejected_result(
                message,
                setting_id=descriptor.setting_id,
                warning_code=code,
            ), descriptor
        return RenderSettingValidationResult.accepted_result(
            setting_id=descriptor.setting_id,
            normalized_value=normalized,
            requirement=descriptor.requirement,
            message="Render setting value is valid.",
        ), descriptor

    def _request_render_settings_renderer_update(self) -> None:
        """Record one committed edge owed a successful renderer update.

        Edge identity: the shared lifecycle hook fires exactly once per
        committed command edge (apply, reset, undo, redo — grouped members
        included), so each unit of ``_render_settings_update_pending_edges``
        IS one distinct committed edge. The ledger drains on the
        presentation thread at the top of ``render_frame`` (#110's
        retained-output ownership boundary released first, one renderer
        reset per owed edge, and the continuously stepping frame loop then
        re-converges the image — a blocking warmup on the UI thread would
        stall presentation for no benefit). Component batching WITHIN one
        edge stays one unit; distinct edges are never merged into one
        actuation, so request/completion accounting always represents
        committed-edge completion truthfully."""

        self._render_settings_update_pending_edges = int(
            getattr(self, "_render_settings_update_pending_edges", 0) or 0
        ) + 1
        self._render_settings_update_request_count = int(
            getattr(self, "_render_settings_update_request_count", 0) or 0
        ) + 1
        # A new committed edge is a defined recovery trigger: a previously
        # blocked drain gets exactly one fresh attempt covering EVERY
        # outstanding edge at the next presented frame.
        self._render_settings_update_blocked_reason = ""

    @property
    def _render_settings_update_pending(self) -> bool:
        """True while any committed edge still awaits its renderer update."""

        return (
            int(getattr(self, "_render_settings_update_pending_edges", 0) or 0)
            > 0
        )

    def _clear_render_settings_update_block(self) -> None:
        """Recovery trigger: allow one fresh drain attempt for owed edges.

        Called from every defined healthy-recovery boundary — a new
        committed edge, renderer replacement (stage load / reload), and
        render-target switching — plus the explicit
        :meth:`retry_render_settings_renderer_update`."""

        self._render_settings_update_blocked_reason = ""

    def retry_render_settings_renderer_update(self) -> bool:
        """Explicitly re-arm the renderer-update drain after a fault.

        Returns True when committed edges remain owed (the next presented
        frame re-attempts each outstanding edge exactly once), False when
        nothing is pending."""

        self._clear_render_settings_update_block()
        pending = bool(self._render_settings_update_pending)
        if pending:
            # The native steady-state path deliberately bypasses Python's
            # reset ledger. Hand ownership back so the next synchronous frame
            # performs this explicitly requested recovery before pacing can
            # start again.
            self._stop_native_frame_pacing("render-settings update retry")
        return pending

    def _block_render_settings_update(self, reason: str) -> None:
        """One truthful fault transition: mark blocked and log ONCE.

        The owed edges stay in the ledger (exact ownership, recoverable);
        the per-frame consumer skips actuation while blocked, so a
        persistent fault never hammers the renderer or floods the log at
        presentation rate. Each new blockage logs exactly one line."""

        self._render_settings_update_blocked_reason = str(reason)
        self._render_settings_update_fault_count = int(
            getattr(self, "_render_settings_update_fault_count", 0) or 0
        ) + 1
        print(
            "[OvstageRendererAdapter] render-settings renderer update "
            f"blocked ({reason}); "
            f"{int(self._render_settings_update_pending_edges)} committed "
            "edge(s) retained for recovery — a new edit, target switch, "
            "stage reload, or retry_render_settings_renderer_update() "
            "re-attempts them once",
            file=sys.stderr,
        )

    def _consume_render_settings_renderer_update(self) -> None:
        """Drain owed renderer updates: one success per committed edge.

        Presentation-thread actuation with failure-safe, NON-DESTRUCTIVE
        ownership: an edge is released ONLY after its reset SUCCEEDS. A
        renderer without reset capability, or a failing reset, retains
        every owed edge and marks the ledger BLOCKED with the concrete
        reason — one log line per fault transition and NO further
        per-frame reset attempts — so a committed value is never silently
        stranded while diagnostics claim completion, and a persistent
        fault never turns one user command into frame-rate renderer
        hammering. A defined recovery trigger (new committed edge,
        renderer replacement, render-target switch, stage reload, or the
        explicit retry) re-arms exactly one drain attempt that completes
        each outstanding edge exactly once. In strict real-ovrtx mode the
        fault transition additionally raises (once — the blocked ledger
        gates later frames)."""

        if int(
            getattr(self, "_render_settings_update_pending_edges", 0) or 0
        ) <= 0:
            return
        if getattr(self, "_render_settings_update_blocked_reason", ""):
            # Owed edges await a recovery trigger; no per-frame retry.
            return
        reset = getattr(self._renderer, "reset", None)
        if not callable(reset):
            # Missing capability: fail truthfully, never consume the edge.
            self._block_render_settings_update(
                "renderer exposes no reset capability"
            )
            if _require_real_ovrtx():
                raise RuntimeError(
                    "ovrtx renderer exposes no reset while committed render "
                    "setting edges await their renderer update"
                )
            return
        # Ownership boundary FIRST: a retained step-result container
        # must never live across a renderer reset. One release covers the
        # whole drain — no step happens between the per-edge resets.
        self._release_retained_output()
        while self._render_settings_update_pending_edges > 0:
            try:
                reset()
            except Exception as exc:
                # Owed edges retained; the drain stays blocked until a
                # recovery trigger re-arms it.
                self._block_render_settings_update(
                    f"renderer reset failed: {exc}"
                )
                if _require_real_ovrtx():
                    raise RuntimeError(
                        "ovrtx renderer reset failed while applying a render "
                        "setting lifecycle"
                    ) from exc
                return
            self._render_settings_update_pending_edges -= 1
            self._render_settings_update_apply_count = int(
                getattr(self, "_render_settings_update_apply_count", 0) or 0
            ) + 1

    def _render_setting_lifecycle_for(
        self,
        descriptor: RenderSettingDescriptor,
    ) -> Callable[[], None] | None:
        """The SHARED declared-lifecycle hook for one setting descriptor.

        Driven purely by the descriptor's declared requirement (the
        capability boundary — no per-setting wiring): WARMUP settings and
        RENDERER_RESTART settings both request the accepted safe renderer
        actuation on every committed edge — one bounded renderer reset per
        distinct committed transition, drained on the presentation thread with
        blocked-ledger recovery, after which the continuously stepping
        frame loop re-converges the image in the newly consumed mode (the
        declared safe restart: the ovrtx renderer and RenderProduct stay
        live, accumulated history is discarded). NONE-requirement settings
        need no renderer action."""

        if descriptor.requirement in (
            RenderSettingRequirement.WARMUP,
            RenderSettingRequirement.RENDERER_RESTART,
        ):
            return self._request_render_settings_renderer_update
        return None


    def _render_setting_owner_path(self, descriptor: Any, product_path: str) -> str:
        """Runtime prim that authoritatively owns this setting.

        Camera-owned settings belong to the runtime camera the active native
        RenderProduct renders through, not to the product itself. Globally
        owned settings belong to the private RenderSettings prim OVRTX itself
        resolves. Both are part of the adapter's own private population
        references, so BORROW ownership of the attached scene is untouched. An
        owner that cannot be resolved returns empty so the caller fails closed
        — never the RenderProduct, where the renderer would never read it.
        """

        scope = _render_setting_owner_scope(descriptor)
        if scope == "RenderProduct":
            return product_path
        if scope == _CAMERA_OWNER_SCOPE:
            return str(getattr(self, "_runtime_camera_local_path", "") or "")
        if scope == _RENDER_SETTINGS_OWNER_SCOPE:
            return str(getattr(self, "_runtime_render_settings_local_path", "") or "")
        return ""

    def _render_settings_owner_opinions_map(self) -> dict[str, Any]:
        """The opinions currently authored on the private owner prim."""

        opinions = getattr(self, "_render_settings_owner_opinions", None)
        return dict(opinions) if isinstance(opinions, dict) else {}

    def _replace_render_settings_owner_layer(
        self,
        opinions: Mapping[str, Any],
    ) -> None:
        """Republish the private owner reference with exactly ``opinions``.

        The value cannot be written into the borrowed OVStage directly: the
        prim is deliberately hidden from the Kit stage bridge's child listing
        (``_scene._is_user_scene_path``), which the shared native authoring
        seam validates paths against, and ``ovrtx_write_attribute`` is
        rejected outright in borrow mode. Regenerating the adapter's OWN
        population reference is the delivery route measured to work, and it
        keeps BORROW exact: no user prim is ever authored.

        The replacement is remove-then-add because two references at the same
        prefix do not compose (measured: removing the older one tears the
        column back out). A failed add restores the previous opinions so no
        edit is half-applied; if that restore also fails the owner is dropped
        and every globally owned row fails closed rather than lying.
        """

        population = getattr(self, "_runtime_population", None)
        stage = self._attached_stage
        handle = getattr(self, "_render_settings_owner_handle", None)
        owner_path = str(
            getattr(self, "_runtime_render_settings_local_path", "") or ""
        )
        if population is None or stage is None or handle is None or not owner_path:
            raise RuntimeError(
                "the global RenderSettings owner prim is not available"
            )
        target = dict(opinions)
        previous = self._render_settings_owner_opinions_map()
        # Build both layers BEFORE touching the population, so an unspellable
        # value fails without disturbing the live reference.
        target_usda = _build_render_settings_owner_layer(target)
        previous_usda = _build_render_settings_owner_layer(previous)
        # Ownership: a retained step-result container must not live across a
        # native population mutation.
        self._release_retained_output()
        _remove_runtime_layer(population, stage, handle)
        self._render_settings_owner_handle = None
        try:
            self._render_settings_owner_handle = _add_runtime_layer(
                population, stage, target_usda, prefix_path=owner_path
            )
        except BaseException as exc:
            try:
                self._render_settings_owner_handle = _add_runtime_layer(
                    population, stage, previous_usda, prefix_path=owner_path
                )
            except BaseException as restore_error:
                self._runtime_render_settings_local_path = ""
                self._render_settings_owner_opinions = {}
                _unregister_presentation_root_if_absent(self._scene, owner_path)
                add_note = getattr(exc, "add_note", None)
                if callable(add_note):
                    add_note(
                        "global render settings owner could not be restored and "
                        "is now unavailable: "
                        f"{type(restore_error).__name__}: {restore_error}"
                    )
            raise
        self._render_settings_owner_opinions = target

    def _commit_render_settings_owner_opinion(
        self,
        attr_name: str,
        new_value: Any,
        *,
        lifecycle: Callable[[], None] | None = None,
    ) -> None:
        """One undoable transition of the private owner prim's opinions.

        History ownership follows :meth:`_commit_native_render_setting`
        exactly: the enclosing provider command records the single edge when
        this apply already runs inside one.
        """

        target = self._render_settings_owner_opinions_map()
        if new_value is _NATIVE_MISSING:
            target.pop(str(attr_name), None)
        else:
            target[str(attr_name)] = new_value
        command = _RenderSettingsOwnerCommand(
            self,
            self._scene,
            self._render_settings_owner_opinions_map(),
            target,
            notify=self._notify_render_settings_changed,
            lifecycle=lifecycle,
        )
        manager = getattr(self, "_undo_manager", None)
        push = getattr(manager, "push", None) if manager is not None else None
        if callable(push) and not in_command_edge():
            push(command)
        else:
            command.do()

    def _commit_native_render_setting(
        self,
        product_path: str,
        native_descriptor: NativeValueDescriptor,
        old_value: Any,
        new_value: Any,
        *,
        lifecycle: Callable[[], None] | None = None,
    ) -> None:
        """One undoable native value transition for a public render setting.

        The command commits through the upstream native authoring seam
        (validated, compensating rollback, one attribute-change event),
        requests the setting's declared renderer lifecycle, and refreshes
        render-settings views on every do/undo/redo edge.  A failing commit
        propagates BEFORE any history edge is recorded, so a rejected edit
        never leaves a false undo entry, a mutated store, or a spurious
        renderer update.

        History ownership: exactly ONE owner records each edge.
        When this apply already executes INSIDE another command's edge —
        the provider binding layer routes projection-row writes through
        its own undoable command whose do/undo/redo re-enter this public
        apply with forward values — pushing here would nest a second
        history entry inside the outer edge: duplicated undo steps, a
        redo-stack clear DURING the outer manager's redo (orphaning the
        entry being redone mid-``redo()``), and phantom entries pushed
        from inside ``undo()``. Detected through upstream's #113
        command-edge scope, the same transition executes as a
        caller-managed direct command instead; the enclosing command
        records exactly one edge, while notification and the declared
        renderer lifecycle still run on every committed transition."""

        command = _RenderSettingNativeCommand(
            self._scene,
            (str(product_path),),
            native_descriptor,
            (old_value,),
            (new_value,),
            category="attribute",
            source="render_settings:set",
            notify=self._notify_render_settings_changed,
            lifecycle=lifecycle,
        )
        manager = getattr(self, "_undo_manager", None)
        push = getattr(manager, "push", None) if manager is not None else None
        if callable(push) and not in_command_edge():
            push(command)
        else:
            command.do()

    def apply_render_setting(
        self,
        setting_id: str,
        value: Any,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingApplyResult:
        """Author one public render setting in the native OVStage store."""

        active_path = str(
            render_product_path or self.get_active_render_product_path() or ""
        )
        if not active_path:
            return RenderSettingApplyResult.rejected_result(
                "No active RenderProduct is available.",
                setting_id=setting_id,
                warning_code="missing_render_product",
            )
        # Validation and authoring describe the SAME pre-write state, so they
        # read one catalog between them rather than one each.
        validation, descriptor = self._render_setting_validation_for(
            self.list_render_settings(active_path),
            setting_id,
            value,
        )
        if not validation.accepted:
            return RenderSettingApplyResult.rejected_result(
                validation.message or "Render setting validation failed.",
                setting_id=validation.setting_id or setting_id,
                warning_code=validation.warning_code or "validation_failed",
            )
        if descriptor is None:
            return RenderSettingApplyResult.rejected_result(
                "Render setting is not available for apply.",
                setting_id=validation.setting_id,
                warning_code="unknown_setting",
            )
        product_path = str(descriptor.metadata.get("render_product_path") or "")
        attr_name = str(descriptor.metadata.get("attr_name") or "")
        owner_path = self._render_setting_owner_path(descriptor, product_path)
        if not product_path or not attr_name:
            return RenderSettingApplyResult.rejected_result(
                "Render setting is not available for apply.",
                setting_id=descriptor.setting_id,
                warning_code="unsupported",
            )
        if not owner_path:
            return RenderSettingApplyResult.rejected_result(
                "Render setting owner prim could not be resolved.",
                setting_id=descriptor.setting_id,
                warning_code="unsupported",
            )
        if _render_setting_owner_scope(descriptor) == _RENDER_SETTINGS_OWNER_SCOPE:
            # The private owner prim is not a native property view; its opinions
            # live in the adapter's own reference.
            return self._apply_globally_owned_render_setting(
                descriptor,
                attr_name,
                product_path,
                validation.normalized_value,
            )
        # The record and the previous value must come from the prim the value is
        # WRITTEN to; reading them from the product made the no-op comparison
        # and the authored test answer about the wrong prim.
        native = self._render_settings_native_adapter(owner_path)
        if native is None:
            return RenderSettingApplyResult.rejected_result(
                "Render setting is not available for apply.",
                setting_id=descriptor.setting_id,
                warning_code="unsupported",
            )
        record = self._render_settings_records(native).get(attr_name)
        spec = _render_setting_builtin_spec(attr_name)
        if spec is None and record is None:
            return RenderSettingApplyResult.rejected_result(
                "Render setting attribute is not available for apply.",
                setting_id=descriptor.setting_id,
                warning_code="unsupported",
            )
        if spec is not None and record is not None:
            conflict = _render_setting_native_role_conflict(spec, record)
            if conflict:
                return RenderSettingApplyResult.rejected_result(
                    f"Render setting apply failed: {conflict}",
                    setting_id=descriptor.setting_id,
                    warning_code="apply_failed",
                )
        try:
            native_descriptor = _render_setting_native_descriptor(
                attr_name, spec, record
            )
            old_value = (
                _NATIVE_MISSING
                if record is None
                else _render_setting_python_value(native.get_value(attr_name))
            )
            new_value = _render_setting_native_write_value(
                descriptor,
                validation.normalized_value,
            )
            # Semantic no-op boundary (shared for every supported row): an
            # ALREADY-AUTHORED column receiving the identical native value
            # is no transition at all — no command, no history entry, no
            # notification, no renderer-update ownership. An unauthored
            # setting receiving its default value is NOT a no-op: authorship
            # itself changes (old is MISSING), so it stays a real edge.
            if record is not None and _render_setting_values_equal(
                old_value, new_value
            ):
                value_state = self.read_render_setting(
                    descriptor.setting_id,
                    render_product_path=product_path,
                )
                return RenderSettingApplyResult.accepted_result(
                    setting_id=descriptor.setting_id,
                    current_value=(
                        value_state.current_value
                        if value_state is not None
                        else validation.normalized_value
                    ),
                    value_state=value_state,
                    requirement=descriptor.requirement,
                    message=(
                        "Render setting already holds this value; "
                        "no change was made."
                    ),
                )
            self._commit_native_render_setting(
                owner_path,
                native_descriptor,
                old_value,
                new_value,
                lifecycle=self._render_setting_lifecycle_for(descriptor),
            )
        except Exception as exc:
            return RenderSettingApplyResult.rejected_result(
                f"Render setting apply failed: {_render_setting_failure_detail(exc)}",
                setting_id=descriptor.setting_id,
                warning_code="apply_failed",
            )
        value_state = self.read_render_setting(
            descriptor.setting_id,
            render_product_path=product_path,
        )
        return RenderSettingApplyResult.accepted_result(
            setting_id=descriptor.setting_id,
            current_value=(
                value_state.current_value
                if value_state is not None
                else validation.normalized_value
            ),
            value_state=value_state,
            requirement=descriptor.requirement,
            message="Render setting applied to the native OVStage store.",
        )

    def reset_render_setting(
        self,
        setting_id: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingResetResult:
        """Restore the effective default of a native setting.

        Deleting the column restores the runtime's pre-authoring state (the
        schema default becomes effective again), which is the native
        equivalent of clearing the authored opinion — including for a
        role-escaped pre-existing column, where deletion IS the remediation
        that removes the escape. The generated viewport's quality is the
        exception: reset restores its configured instance default through an
        undoable write, since deleting it would enable the native default 100.
        """

        active_path = str(render_product_path or self.get_active_render_product_path() or "")
        if not active_path:
            return RenderSettingResetResult.rejected_result(
                "No active RenderProduct is available.",
                setting_id=setting_id,
                warning_code="missing_render_product",
            )
        descriptor = _render_setting_for_id(
            self.list_render_settings(active_path),
            setting_id,
        )
        if descriptor is None:
            return RenderSettingResetResult.rejected_result(
                "Render setting is not available for this RenderProduct.",
                setting_id=setting_id,
                warning_code="unknown_setting",
            )
        product_path = str(descriptor.metadata.get("render_product_path") or "")
        attr_name = str(descriptor.metadata.get("attr_name") or "")
        owner_path = self._render_setting_owner_path(descriptor, product_path)
        if _render_setting_owner_scope(descriptor) == _RENDER_SETTINGS_OWNER_SCOPE:
            return self._reset_globally_owned_render_setting(
                descriptor,
                attr_name,
                product_path,
                owner_path,
            )
        native = (
            self._render_settings_native_adapter(owner_path) if owner_path else None
        )
        record = self._render_settings_records(native).get(attr_name)
        if native is None or record is None or not owner_path:
            return RenderSettingResetResult.rejected_result(
                "Render setting has no authored native value to reset.",
                setting_id=descriptor.setting_id,
                warning_code="not_authored",
            )
        committed = False
        try:
            native_descriptor = _render_setting_native_descriptor(
                attr_name,
                _render_setting_builtin_spec(attr_name),
                record,
            )
            old_value = _render_setting_python_value(native.get_value(attr_name))
            quality_default = self._private_viewport_quality_default(owner_path, attr_name)
            if quality_default is None or not _render_setting_values_equal(
                old_value, quality_default
            ):
                self._commit_native_render_setting(
                    owner_path,
                    native_descriptor,
                    old_value,
                    quality_default if quality_default is not None else _NATIVE_MISSING,
                    lifecycle=self._render_setting_lifecycle_for(descriptor),
                )
                committed = True
        except Exception as exc:
            return RenderSettingResetResult.rejected_result(
                f"Render setting reset failed: {_render_setting_failure_detail(exc)}",
                setting_id=descriptor.setting_id,
                warning_code="reset_failed",
            )
        value_state = self.read_render_setting(
            descriptor.setting_id,
            render_product_path=product_path,
        )
        return RenderSettingResetResult.accepted_result(
            setting_id=descriptor.setting_id,
            reset_value=None if value_state is None else value_state.current_value,
            value_state=value_state,
            requirement=descriptor.requirement,
            message=(
                "Render setting reset in the native OVStage store."
                if committed
                else "Render setting already holds its configured default; no change was made."
            ),
        )

    def _apply_globally_owned_render_setting(
        self,
        descriptor: RenderSettingDescriptor,
        attr_name: str,
        product_path: str,
        normalized_value: Any,
    ) -> RenderSettingApplyResult:
        """Author one globally owned setting onto the private owner prim."""

        old_value = self._render_settings_owner_opinions_map().get(
            attr_name, _NATIVE_MISSING
        )
        new_value = _render_setting_native_write_value(descriptor, normalized_value)
        # Same semantic no-op boundary as the native path: an already-authored
        # opinion receiving its identical value is no transition; an
        # unauthored one receiving the default still changes authorship.
        if old_value is not _NATIVE_MISSING and _render_setting_values_equal(
            old_value, new_value
        ):
            value_state = self.read_render_setting(
                descriptor.setting_id,
                render_product_path=product_path,
            )
            return RenderSettingApplyResult.accepted_result(
                setting_id=descriptor.setting_id,
                current_value=(
                    value_state.current_value
                    if value_state is not None
                    else normalized_value
                ),
                value_state=value_state,
                requirement=descriptor.requirement,
                message=(
                    "Render setting already holds this value; no change was made."
                ),
            )
        try:
            self._commit_render_settings_owner_opinion(
                attr_name,
                new_value,
                lifecycle=self._render_setting_lifecycle_for(descriptor),
            )
        except Exception as exc:
            return RenderSettingApplyResult.rejected_result(
                f"Render setting apply failed: {_render_setting_failure_detail(exc)}",
                setting_id=descriptor.setting_id,
                warning_code="apply_failed",
            )
        value_state = self.read_render_setting(
            descriptor.setting_id,
            render_product_path=product_path,
        )
        return RenderSettingApplyResult.accepted_result(
            setting_id=descriptor.setting_id,
            current_value=(
                value_state.current_value
                if value_state is not None
                else normalized_value
            ),
            value_state=value_state,
            requirement=descriptor.requirement,
            message=(
                "Render setting applied to the private global RenderSettings prim."
            ),
        )

    def _reset_globally_owned_render_setting(
        self,
        descriptor: RenderSettingDescriptor,
        attr_name: str,
        product_path: str,
        owner_path: str,
    ) -> RenderSettingResetResult:
        """Drop one globally owned opinion; the effective default returns."""

        authored = attr_name in self._render_settings_owner_opinions_map()
        if not owner_path or not authored:
            return RenderSettingResetResult.rejected_result(
                "Render setting has no authored native value to reset.",
                setting_id=descriptor.setting_id,
                warning_code="not_authored",
            )
        try:
            self._commit_render_settings_owner_opinion(
                attr_name,
                _NATIVE_MISSING,
                lifecycle=self._render_setting_lifecycle_for(descriptor),
            )
        except Exception as exc:
            return RenderSettingResetResult.rejected_result(
                f"Render setting reset failed: {_render_setting_failure_detail(exc)}",
                setting_id=descriptor.setting_id,
                warning_code="reset_failed",
            )
        value_state = self.read_render_setting(
            descriptor.setting_id,
            render_product_path=product_path,
        )
        return RenderSettingResetResult.accepted_result(
            setting_id=descriptor.setting_id,
            reset_value=None if value_state is None else value_state.current_value,
            value_state=value_state,
            requirement=descriptor.requirement,
            message=(
                "Render setting reset on the private global RenderSettings prim."
            ),
        )

    # ------------------------------------------------------------------
    # Process-global render setting lifecycle: this adapter's PUBLIC
    # capability, and the whole of its contribution to process-global
    # renderer configuration.
    #
    # The capability is the same one the OpenUSD adapter answers, so a caller
    # that owns such a configuration channel is provider-independent. What
    # differs is that OVStage/BORROW cannot perform an in-place rebuild at
    # all; see the lifecycle hooks below.
    # ------------------------------------------------------------------

    def global_render_setting_lifecycle_requirement(
        self,
        lifecycle: RenderSettingLifecycle,
    ) -> str:
        """"" when ``lifecycle`` can be performed safely right now."""

        if lifecycle is RenderSettingLifecycle.NONE:
            return "names no consumer on this build"
        return ""

    def perform_global_render_setting_lifecycle(
        self,
        lifecycle: RenderSettingLifecycle,
        value: Any,
    ) -> str:
        """Make a just-written value effective. "" on success, else the fault."""

        # A borrowed scene cannot be rebuilt under, so publishing the value
        # is all this adapter does.
        return ""

    def _ensure_point_cloud_state(self) -> None:
        if not hasattr(self, "_point_cloud_requests"):
            self._point_cloud_requests = {}
        if not hasattr(self, "_latest_point_cloud_frames"):
            self._latest_point_cloud_frames = {}

    def _ensure_render_var_output_state(self) -> None:
        if not hasattr(self, "_render_var_output_requests"):
            self._render_var_output_requests = {}
        if not hasattr(self, "_latest_render_var_output_frames"):
            self._latest_render_var_output_frames = {}

    def _render_products_for_step(self) -> set[str]:
        self._ensure_point_cloud_state()
        self._ensure_render_var_output_state()
        paths = {str(self._render_product_path)}
        if self._secondary_viewport_active:
            paths.add(str(self._secondary_render_product_path))
        paths.update(
            request.render_product_path
            for request in self._point_cloud_requests.values()
            if request.render_product_path
        )
        paths.update(
            request.render_product_path
            for request in self._render_var_output_requests.values()
            if request.render_product_path
        )
        return paths

    def _active_product_uses_point_cloud_overlay(self) -> bool:
        """Whether the active native product is point-cloud-only presentation."""

        return False

    def _extract_requested_point_cloud_frames(self, products: Any) -> None:
        self._ensure_point_cloud_state()
        for viewport_id, request in tuple(self._point_cloud_requests.items()):
            try:
                frame = self._extract_point_cloud_frame(products, request)
            except Exception as exc:
                frame = self._stale_point_cloud_frame(
                    viewport_id,
                    request,
                    "extraction_failed",
                    f"PointCloud extraction failed: {type(exc).__name__}: {exc}",
                )
            self._latest_point_cloud_frames[(viewport_id, request.render_product_path)] = frame

    def _extract_requested_render_var_output_frames(self, products: Any) -> None:
        self._ensure_render_var_output_state()
        for viewport_id, request in tuple(self._render_var_output_requests.items()):
            try:
                frame = self._extract_render_var_output_frame(products, request)
            except Exception as exc:
                frame = self._stale_render_var_output_frame(
                    viewport_id,
                    request,
                    "extraction_failed",
                    f"RenderVar extraction failed: {type(exc).__name__}: {exc}",
                )
            self._latest_render_var_output_frames[
                (viewport_id, request.render_product_path, request.output_id)
            ] = frame

    def _mark_point_cloud_requests_stale(self, code: str, message: str) -> None:
        self._ensure_point_cloud_state()
        for viewport_id, request in tuple(self._point_cloud_requests.items()):
            self._latest_point_cloud_frames[(viewport_id, request.render_product_path)] = (
                self._stale_point_cloud_frame(
                    viewport_id,
                    request,
                    code,
                    message,
                )
            )

    def _mark_render_var_output_requests_stale(
        self,
        code: str,
        message: str,
    ) -> None:
        self._ensure_render_var_output_state()
        for viewport_id, request in tuple(self._render_var_output_requests.items()):
            self._latest_render_var_output_frames[
                (viewport_id, request.render_product_path, request.output_id)
            ] = self._stale_render_var_output_frame(
                viewport_id,
                request,
                code,
                message,
            )

    def _stale_point_cloud_frame(
        self,
        viewport_id: str,
        request: PointCloudRequest,
        code: str,
        message: str,
        descriptor: PointCloudOutputDescriptor | None = None,
    ) -> PointCloudFrame:
        key = (str(viewport_id or ""), str(request.render_product_path or ""))
        warning = _point_cloud_warning(code, message)
        previous = self._latest_point_cloud_frames.get(key)
        if previous is not None:
            return PointCloudFrame(
                render_product_path=previous.render_product_path,
                render_var_name=previous.render_var_name,
                point_count=previous.point_count,
                valid_point_count=previous.valid_point_count,
                coordinates=previous.coordinates,
                channels=dict(previous.channels),
                validity_mask=previous.validity_mask,
                coordinate_space=previous.coordinate_space,
                transform_to_world=previous.transform_to_world,
                frame_index=previous.frame_index,
                timestamp=previous.timestamp,
                stale=True,
                source_sensor_path=previous.source_sensor_path,
                source_sensor_type=previous.source_sensor_type,
                channel_descriptors=previous.channel_descriptors,
                warnings=(*previous.warnings, warning),
            )
        return PointCloudFrame(
            render_product_path=request.render_product_path,
            render_var_name=request.render_var_name,
            stale=True,
            source_sensor_path=(descriptor.source_sensor_path if descriptor is not None else None),
            source_sensor_type=(descriptor.source_sensor_type if descriptor is not None else ""),
            channel_descriptors=descriptor.channels if descriptor is not None else (),
            warnings=(warning,),
        )

    def _stale_render_var_output_frame(
        self,
        viewport_id: str,
        request: RenderVarOutputRequest,
        code: str,
        message: str,
        descriptor: RenderVarOutputDescriptor | None = None,
    ) -> RenderVarOutputFrame:
        key = (
            str(viewport_id or ""),
            str(request.render_product_path or ""),
            str(request.output_id or ""),
        )
        warning = _render_var_warning(code, message)
        previous = self._latest_render_var_output_frames.get(key)
        if previous is not None:
            return RenderVarOutputFrame(
                render_product_path=previous.render_product_path,
                output_id=previous.output_id,
                render_var_name=previous.render_var_name,
                width=previous.width,
                height=previous.height,
                dtype=previous.dtype,
                component_count=previous.component_count,
                color_space=previous.color_space,
                units=previous.units,
                value_range=previous.value_range,
                display_data=previous.display_data,
                raw_data=previous.raw_data,
                frame_index=previous.frame_index,
                timestamp=previous.timestamp,
                stale=True,
                warnings=(*previous.warnings, warning),
                metadata=dict(previous.metadata),
            )
        return RenderVarOutputFrame(
            render_product_path=request.render_product_path,
            output_id=request.output_id,
            render_var_name=request.render_var_name,
            dtype=descriptor.dtype if descriptor is not None else "",
            component_count=descriptor.component_count if descriptor is not None else 1,
            color_space=descriptor.color_space if descriptor is not None else "",
            units=descriptor.units if descriptor is not None else "",
            value_range=descriptor.value_range if descriptor is not None else None,
            stale=True,
            warnings=(warning,),
        )

    def _extract_point_cloud_frame(
        self,
        products: Any,
        request: PointCloudRequest,
    ) -> PointCloudFrame:
        descriptor = _point_cloud_output_for_request(
            self.list_point_cloud_outputs(request.render_product_path),
            request,
        )
        if descriptor is None:
            return self._stale_point_cloud_frame(
                request.viewport_id,
                request,
                "missing_output",
                "PointCloud output was not found.",
            )
        if not descriptor.is_available:
            return self._stale_point_cloud_frame(
                request.viewport_id,
                request,
                "disabled_output",
                descriptor.disabled_reason or "PointCloud output is disabled.",
                descriptor,
            )
        try:
            frame_out = products[request.render_product_path].frames[0]
            render_vars = getattr(frame_out, "render_vars", None) or {}
        except Exception:
            return self._stale_point_cloud_frame(
                request.viewport_id,
                request,
                "missing_product",
                "PointCloud render product was not returned by the renderer.",
                descriptor,
            )
        device = getattr(getattr(self, "_ovrtx", None), "Device", None)
        cpu_device = getattr(device, "CPU", None)
        try:
            counts = _point_cloud_copy_render_var(render_vars, "Counts", cpu_device)
            coordinate_data = _point_cloud_copy_render_var(
                render_vars,
                "Coordinates",
                cpu_device,
            )
        except Exception as exc:
            return self._stale_point_cloud_frame(
                request.viewport_id,
                request,
                "mapping_failed",
                f"PointCloud required channel mapping failed: {exc}",
                descriptor,
            )
        coordinate_rows = _point_cloud_rows(coordinate_data, 3)
        try:
            point_count = int(np.asarray(counts).reshape(-1)[0])
        except Exception:
            point_count = int(coordinate_rows.shape[0])
        point_count = max(0, min(point_count, int(coordinate_rows.shape[0])))
        indices = _point_cloud_indices(point_count, request)
        selected = np.array(coordinate_rows[:point_count, :3][indices], copy=True)
        world, coordinate_space, transform_warning = _point_cloud_world_coordinates(
            selected,
            descriptor,
            1.0,
        )
        if transform_warning is not None:
            return self._stale_point_cloud_frame(
                request.viewport_id,
                request,
                transform_warning.code,
                transform_warning.message,
                descriptor,
            )
        channel_by_name = {channel.name: channel for channel in descriptor.channels}
        requested_channels = request.requested_channels or tuple(
            channel.name
            for channel in descriptor.channels
            if channel.semantic
            not in {
                PointCloudChannelSemantic.COORDINATES,
                PointCloudChannelSemantic.COUNT,
            }
        )
        channels: dict[str, Any] = {}
        warnings = list(descriptor.warnings)
        flags_data = None
        for channel_name in requested_channels:
            channel = channel_by_name.get(str(channel_name))
            if channel is None:
                warnings.append(
                    _point_cloud_warning(
                        "missing_channel",
                        f"Requested PointCloud channel {channel_name!r} is not described.",
                    )
                )
                continue
            try:
                data = _point_cloud_copy_render_var(
                    render_vars,
                    channel.name,
                    cpu_device,
                )
                rows = _point_cloud_rows(data, channel.component_count)
                payload = np.array(rows[indices], copy=True)
            except Exception:
                warnings.append(
                    _point_cloud_warning(
                        "missing_channel",
                        f"PointCloud channel {channel.name!r} was not returned.",
                    )
                )
                continue
            if channel.semantic is PointCloudChannelSemantic.FLAGS:
                flags_data = data
            if channel.semantic not in {
                PointCloudChannelSemantic.COORDINATES,
                PointCloudChannelSemantic.COUNT,
            }:
                channels[channel.name] = payload
        validity_mask = None
        valid_point_count = len(indices)
        if request.include_validity and "Flags" in channel_by_name:
            try:
                if flags_data is None:
                    flags_data = _point_cloud_copy_render_var(
                        render_vars,
                        "Flags",
                        cpu_device,
                    )
                flags = (
                    np.asarray(flags_data)
                    .reshape(-1)[indices]
                    .astype(
                        np.uint64,
                        copy=False,
                    )
                )
                validity_mask = np.array((flags & 0x40) != 0, copy=True)
                valid_point_count = int(np.count_nonzero(validity_mask))
            except Exception:
                warnings.append(
                    _point_cloud_warning(
                        "missing_validity",
                        "PointCloud Flags channel was not returned.",
                    )
                )
        return PointCloudFrame(
            render_product_path=request.render_product_path,
            render_var_name=request.render_var_name,
            point_count=len(indices),
            valid_point_count=valid_point_count,
            coordinates=world,
            channels=channels,
            validity_mask=validity_mask,
            coordinate_space=coordinate_space,
            transform_to_world=descriptor.transform_to_world,
            frame_index=_frame_index(frame_out),
            timestamp=time.perf_counter(),
            stale=False,
            source_sensor_path=descriptor.source_sensor_path,
            source_sensor_type=descriptor.source_sensor_type,
            channel_descriptors=descriptor.channels,
            warnings=tuple(warnings),
        )

    def _extract_render_var_output_frame(
        self,
        products: Any,
        request: RenderVarOutputRequest,
    ) -> RenderVarOutputFrame:
        descriptor = _render_var_output_for_request(
            self.list_render_var_outputs(request.render_product_path),
            request,
        )
        if descriptor is None:
            return self._stale_render_var_output_frame(
                request.viewport_id,
                request,
                "missing_output",
                "RenderVar output was not found.",
            )
        if not descriptor.is_available:
            return self._stale_render_var_output_frame(
                request.viewport_id,
                request,
                "disabled_output",
                descriptor.disabled_reason or "RenderVar output is disabled.",
                descriptor,
            )
        try:
            frame_out = products[request.render_product_path].frames[0]
            render_vars = getattr(frame_out, "render_vars", None) or {}
        except Exception:
            return self._stale_render_var_output_frame(
                request.viewport_id,
                request,
                "missing_product",
                "RenderVar render product was not returned by the renderer.",
                descriptor,
            )
        names = (
            descriptor.render_var_name,
            str(descriptor.metadata.get("source_name") or ""),
            descriptor.display_name,
        )
        runtime_var = next(
            (render_vars[name] for name in names if name and name in render_vars),
            None,
        )
        if runtime_var is None:
            requested_names = {_source_token_key(name) for name in names if name}
            runtime_var = next(
                (
                    value
                    for key, value in render_vars.items()
                    if _source_token_key(key) in requested_names
                ),
                None,
            )
        if runtime_var is None:
            return self._stale_render_var_output_frame(
                request.viewport_id,
                request,
                "mapping_failed",
                f"RenderVar {descriptor.render_var_name!r} was not returned.",
                descriptor,
            )
        device = getattr(getattr(self, "_ovrtx", None), "Device", None)
        cpu_device = getattr(device, "CPU", None)
        try:
            data = _map_render_var_cpu(
                runtime_var,
                cpu_device,
                lambda mapping: _copy_primary_mapping_tensor(
                    mapping,
                    descriptor.render_var_name,
                ),
            )
            if descriptor.output_kind is RenderVarOutputKind.METADATA_MAP:
                width = height = 0
            elif data.ndim >= 2:
                height, width = int(data.shape[0]), int(data.shape[1])
            else:
                raise ValueError(f"RenderVar data must be at least 2D, got {data.shape}")
            actual_components = 1 if data.ndim == 2 else int(data.shape[-1])
            if (
                descriptor.output_kind is not RenderVarOutputKind.METADATA_MAP
                and actual_components < descriptor.component_count
            ):
                raise ValueError(
                    f"RenderVar has {actual_components} components, expected "
                    f"{descriptor.component_count}."
                )
        except Exception as exc:
            return self._stale_render_var_output_frame(
                request.viewport_id,
                request,
                "mapping_failed",
                f"RenderVar output mapping failed: {exc}",
                descriptor,
            )
        return RenderVarOutputFrame(
            render_product_path=descriptor.render_product_path,
            output_id=descriptor.output_id,
            render_var_name=descriptor.render_var_name,
            width=width,
            height=height,
            dtype=descriptor.dtype or str(data.dtype),
            component_count=descriptor.component_count,
            color_space=descriptor.color_space,
            units=descriptor.units,
            value_range=descriptor.value_range,
            display_data=data,
            raw_data=data,
            frame_index=_frame_index(frame_out),
            timestamp=time.perf_counter(),
            stale=False,
            warnings=descriptor.warnings,
            metadata={
                "shape": tuple(int(item) for item in np.asarray(data).shape),
                "output_kind": descriptor.output_kind.value,
            },
        )

    def _path_has_type(self, path: str, type_names: tuple[str, ...]) -> bool:
        scene = self._scene
        stage = getattr(scene, "_stage", None)
        if stage is None or not getattr(scene, "is_open", False):
            return True
        if _uses_native_kit_query(stage):
            try:
                record = _kit_type_records(
                    stage,
                    int(stage.current_ordinal),
                ).get(str(path))
            except Exception:
                return False
            if record is None:
                return False
            prim_type, _schemas = record
            accepted = {str(type_name).lower() for type_name in type_names}
            return str(prim_type).lower() in accepted
        for type_name in type_names:
            try:
                result = stage.query_prims(
                    int(stage.current_ordinal),
                    require_all=[type_name],
                )
            except Exception:
                continue
            for group in result.get("groups", ()):
                handle = int(group.get("prim_list_handle") or 0)
                if not handle:
                    continue
                try:
                    paths = {str(value) for value in stage.get_prim_paths(handle)}
                except Exception:
                    continue
                if path in paths:
                    return True
        return False

    def _push_runtime_camera_state_fast(
        self,
        camera_path: str | None,
        view_matrix: Any,
        proj_matrix: Any,
        state_attribute: str,
    ) -> None:
        """Apply camera state through the pre-merge OVStage write flow."""

        stage = self._attached_stage
        if stage is None or camera_path is None or view_matrix is None:
            return
        try:
            ovstage = import_module("ovstage")
            matrix_semantic = ovstage.AttributeSemantic.MATRIX
            world_tensor = _view_to_ovrtx_transform(view_matrix).reshape(-1)
            intrinsics = _compute_camera_intrinsics(proj_matrix)
            camera_state = (camera_path, world_tensor.tobytes(), intrinsics)
            if getattr(self, state_attribute, None) == camera_state:
                return
            with StageWriteBatch(stage, [camera_path]) as batch:
                batch.write_fixed(
                    _OVRTX_XFORM_ATTR,
                    world_tensor,
                    lanes=16,
                    semantic=matrix_semantic,
                )
                if intrinsics is not None:
                    focal, horizontal_aperture, vertical_aperture = intrinsics
                    for attribute_name, value in (
                        ("focalLength", focal),
                        ("horizontalAperture", horizontal_aperture),
                        ("verticalAperture", vertical_aperture),
                    ):
                        batch.write_fixed(
                            attribute_name,
                            np.asarray([value], dtype=np.float32),
                        )
            setattr(self, state_attribute, camera_state)
        except Exception as exc:
            if _require_real_ovrtx():
                raise RuntimeError("OVStage camera write failed") from exc

    def _push_runtime_camera_state_native_pacing(
        self,
        camera_path: str | None,
        view_matrix: Any,
        proj_matrix: Any,
        state_attribute: str,
    ) -> None:
        """Apply camera state through the clean ``origin/main`` write flow."""

        stage = self._attached_stage
        if stage is None or camera_path is None or view_matrix is None:
            return
        try:
            ovstage = import_module("ovstage")
            matrix_semantic = ovstage.AttributeSemantic.MATRIX
            world_tensor = _view_to_ovrtx_transform(view_matrix).reshape(-1)
            intrinsics = _compute_camera_intrinsics(proj_matrix)
            projection_mode = _camera_projection_mode(proj_matrix)
            camera_state = (
                camera_path,
                world_tensor.tobytes(),
                intrinsics,
                projection_mode,
            )
            if getattr(self, state_attribute, None) == camera_state:
                return
            with StageWriteBatch(stage, [camera_path]) as batch:
                batch.write_fixed(
                    _OVRTX_XFORM_ATTR,
                    world_tensor,
                    lanes=16,
                    semantic=matrix_semantic,
                )
                if intrinsics is not None:
                    focal, horizontal_aperture, vertical_aperture = intrinsics
                    for attribute_name, value in (
                        ("focalLength", focal),
                        ("horizontalAperture", horizontal_aperture),
                        ("verticalAperture", vertical_aperture),
                    ):
                        batch.write_fixed(
                            attribute_name,
                            np.asarray([value], dtype=np.float32),
                        )
                if projection_mode is not None:
                    batch.write_tokens("projection", (projection_mode,))
            setattr(self, state_attribute, camera_state)
        except Exception as exc:
            if _require_real_ovrtx():
                raise RuntimeError("OVStage camera write failed") from exc

    def _push_runtime_camera_state(
        self,
        camera_path: str | None,
        view_matrix: Any,
        proj_matrix: Any,
        state_attribute: str,
    ) -> None:
        if self._render_flow_mode == "fast":
            self._push_runtime_camera_state_fast(
                camera_path,
                view_matrix,
                proj_matrix,
                state_attribute,
            )
        else:
            self._push_runtime_camera_state_native_pacing(
                camera_path,
                view_matrix,
                proj_matrix,
                state_attribute,
            )

    def _push_view_camera_state(self, view_matrix: Any, proj_matrix: Any) -> None:
        self._push_runtime_camera_state(
            self._runtime_camera_path(),
            view_matrix,
            proj_matrix,
            "_last_pushed_camera_state",
        )

    def _push_secondary_view_camera_state(
        self,
        view_matrix: Any,
        proj_matrix: Any,
    ) -> None:
        self._push_runtime_camera_state(
            self._secondary_camera_path,
            view_matrix,
            proj_matrix,
            "_secondary_last_pushed_camera_state",
        )

    def _runtime_camera_path(self) -> str | None:
        """Return the provider-owned camera that may receive transient state.

        Only the private runtime RenderProduct consumes this private OVStage
        camera. A source RenderProduct already consumes its populated camera
        relationship. Writing view/projection values directly to that public
        camera is deferred until the native authoring contract is implemented.
        """

        default_product = getattr(
            self,
            "_default_render_product_path",
            _RENDER_PRODUCT_LOCAL_PATH,
        )
        product_path = str(
            getattr(self, "_render_product_path", default_product) or default_product
        )
        if product_path != default_product:
            return None
        return getattr(
            self,
            "_runtime_camera_local_path",
            _RENDER_CAMERA_LOCAL_PATH,
        )

    def pick(
        self,
        x: float,
        y: float,
        callback: Callable[[Optional[str], Optional[Vec3f]], None],
        query_name: str,
    ) -> None:
        renderer = self._renderer
        if (
            self._attached_stage is None
            or renderer is None
            or not hasattr(renderer, "enqueue_pick_query")
        ):
            callback(None, None)
            return
        self._stop_native_frame_pacing(
            "pick query", capture_selected_camera=True, pause_render=True
        )
        if (
            bool(getattr(self, "_frame_pacing_pick_generated", False))
            or bool(
                getattr(
                    self,
                    "_frame_pacing_pick_association_unavailable",
                    False,
                )
            )
        ):
            # Generated-image camera timing is not available in ovrtx 0.4,
            # and a real image is usable only with its complete camera state.
            # Keep callbacks on this UI thread and fail closed rather than
            # cast a ray from a camera that did not produce the visible image.
            self._frame_pacing_pick_generated = False
            self._frame_pacing_pick_snapshot = None
            self._frame_pacing_pick_association_unavailable = False
            callback(None, None)
            return
        try:
            left, top, right, bottom = self._ndc_rect_to_pick_pixels(x, y, x, y)
            renderer.enqueue_pick_query(
                self._render_product_path,
                *self._pick_pixels_to_query_rect(left, top, right, bottom),
            )
        except Exception:
            self._frame_pacing_pick_snapshot = None
            self._frame_pacing_pick_generated = False
            self._frame_pacing_pick_association_unavailable = False
            callback(None, None)
            return
        name = str(query_name or "viewport_click")
        self._cancel_in_flight_point(name, _PICK_CANCEL_REPLACED)
        self._pick_seq += 1
        self._in_flight_pick_queries.append(
            [
                self._pick_seq,
                "point",
                name,
                callback,
                None,
                None,
                (float(x), float(y)),
            ]
        )
        self._pick_enqueue_count += 1
        self._last_pick_pixel_rect = (left, top, right, bottom)
        self._last_pick_kind = "point"
        self._last_pick_query_name = name
        self._last_pick_paths = ()

    def cancel_pick(self, query_name: str) -> None:
        self._cancel_in_flight_point(
            str(query_name or "viewport_click"),
            _PICK_CANCEL_EXPLICIT,
        )

    def _cancel_in_flight_point(self, name: str, reason: str) -> None:
        for entry in self._in_flight_pick_queries:
            if entry[1] == "point" and entry[2] == name and entry[3] is not None:
                entry[3] = None
                entry[4] = reason

    def pick_rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        callback: Callable[[List[str]], None],
    ) -> None:
        renderer = self._renderer
        if (
            self._attached_stage is None
            or renderer is None
            or not hasattr(renderer, "enqueue_pick_query")
        ):
            callback([])
            return
        self._stop_native_frame_pacing(
            "rectangle pick query", capture_selected_camera=True, pause_render=True
        )
        if (
            bool(getattr(self, "_frame_pacing_pick_generated", False))
            or bool(
                getattr(
                    self,
                    "_frame_pacing_pick_association_unavailable",
                    False,
                )
            )
        ):
            self._frame_pacing_pick_generated = False
            self._frame_pacing_pick_snapshot = None
            self._frame_pacing_pick_association_unavailable = False
            callback([])
            return
        try:
            left, top, right, bottom = self._ndc_rect_to_pick_pixels(x0, y0, x1, y1)
            renderer.enqueue_pick_query(
                self._render_product_path,
                *self._pick_pixels_to_query_rect(left, top, right, bottom),
            )
        except Exception:
            self._frame_pacing_pick_snapshot = None
            self._frame_pacing_pick_generated = False
            self._frame_pacing_pick_association_unavailable = False
            callback([])
            return
        self._pick_seq += 1
        self._in_flight_pick_queries.append(
            [
                self._pick_seq,
                "rect",
                f"viewport_rect:{time.monotonic_ns()}",
                callback,
                None,
                None,
                None,
            ]
        )
        self._pick_enqueue_count += 1
        self._last_pick_pixel_rect = (left, top, right, bottom)
        self._last_pick_kind = "rect"
        self._last_pick_query_name = self._in_flight_pick_queries[-1][2]
        self._last_pick_paths = ()

    def set_selection_highlight(self, paths: List[str]) -> None:
        """Drive ovrtx's per-prim selection-outline membership for ``paths``.

        Membership goes through the dedicated ``set_selection_outline_group``
        renderer API when the runtime exposes one (renderer-owned
        presentation state that never writes the borrowed OVStage), else
        through ovrtx's reserved ``omni:selectionOutlineGroup`` presentation
        attribute written via the OVStage owner's copy-in API — the
        documented transport on the installed 0.4.0 wheel.  The historical
        BORROW prohibition covered OVRTX stage-data attribute writes into
        the owner's data plane; neither channel performs one.  Bookkeeping
        advances only after a write succeeds, so a transient failure leaves
        the affected paths retryable on the next selection sync.  Runtimes
        with neither transport degrade honestly: selection still
        synchronizes, no outline appears.
        """
        selected = list(dict.fromkeys(str(path) for path in (paths or []) if path))
        self._selected_paths = selected
        self._configure_selection_outline_styles()

        previous = set(self._selection_outline_previous_paths)
        stale_paths = getattr(self, "_selection_outline_stale_paths", None)
        if not isinstance(stale_paths, set):
            stale_paths = set()
            self._selection_outline_stale_paths = stale_paths
        current = set(selected)
        to_clear = sorted((previous - current) | (stale_paths - current))
        to_set = [path for path in selected if path not in previous]
        cleared = (
            self._profile_ovui_call(
                "OvstageRendererAdapter.selection_outline.clear",
                self._write_selection_outline_group,
                to_clear, _SELECTION_OUTLINE_CLEAR_GROUP_ID
            )
            if to_clear
            else set()
        )
        applied = (
            self._profile_ovui_call(
                "OvstageRendererAdapter.selection_outline.set",
                self._write_selection_outline_group, to_set, _SELECTION_OUTLINE_GROUP_ID,
            )
            if to_set
            else set()
        )
        self._selection_outline_previous_paths.difference_update(cleared)
        stale_paths.difference_update(cleared)
        self._selection_outline_previous_paths.update(applied)
        # A successful current-generation set supersedes any uncertain
        # renderer membership for the same path from an older attachment.
        stale_paths.difference_update(applied)
        pending = current - self._selection_outline_previous_paths
        self._selection_outline_last_write = {
            "requested_paths": list(selected),
            "applied_paths": sorted(self._selection_outline_previous_paths),
            "pending_paths": sorted(pending),
            "to_clear": list(to_clear),
            "cleared_paths": sorted(cleared),
            "to_set": list(to_set),
            "set_paths": sorted(applied),
            "stale_cleanup_paths": sorted(stale_paths),
            "generation": int(self._selection_outline_generation),
            "stale_reason": (
                "stale_cleanup_pending"
                if stale_paths
                else "missing_native_paths"
                if pending
                else ""
            ),
        }
        membership_reset_pending = bool(
            getattr(self, "_selection_outline_membership_reset_pending", False)
        )
        if current & self._selection_outline_previous_paths or membership_reset_pending:
            # Applied membership that is currently DESIRED exists (fresh
            # writes or membership carried over a scene transition) — the
            # pass activation must cover both.  Stale paths awaiting a
            # failed clear's retry never trigger activation.
            self._ensure_selection_outline_pass_active()

    def refresh_selection_highlight(self, paths: List[str]) -> None:
        """Retry unapplied native membership after a rendered/topology edge.

        Existing applied paths remain untouched.  Missing paths deliberately
        stay outside ``_selection_outline_previous_paths``, so the ordinary
        delta calculation retries them as soon as the active native stage
        contains the prim.  This avoids clear/set churn on stable membership
        while giving the viewport's post-frame and stage-change refresh paths
        a truthful convergence seam.
        """

        self.set_selection_highlight(paths)

    def shutdown(self) -> None:
        # The worker must be fully stopped before any frame/output/stage or
        # renderer ownership is invalidated below.
        self._stop_render_worker()
        # Ownership: a retained step-result container must never outlive the
        # native renderer handle, which is explicitly destroyed below.
        self._discard_async_render_state()
        self._release_retained_output()
        self._dispatch_pending_pick_misses()
        # Detach first. A provider replacement can fail here and retain the
        # current scene for a safe retry; its active process-global stream must
        # remain usable in that case. Once detach succeeds, closing this old
        # tap is safe and must precede activation of the replacement tap.
        self._remove_scene()
        from ovui_data_adapters.common._render_product_stream import release_for_shutdown

        # A borrowed RenderProduct stream is released, never closed, here.
        livestream = release_for_shutdown(self)
        if livestream is not None:
            try:
                livestream.close()
            except Exception as exc:
                # The native Stage is already detached, so optional transport
                # cleanup cannot strand an OVStage borrower.
                print(
                    "[OvstageRendererAdapter] livestream shutdown failed: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
            finally:
                self._livestream = None
        renderer = self._renderer
        if renderer is not None:
            # Instrumentation wrappers can retain the Python renderer after
            # this adapter retires. Destroy its native sync scope
            # deterministically so it cannot block descriptor reclamation for
            # the next renderer.
            renderer.destroy()
        get_instrumentation().release_renderer(self)
        self._renderer = None

    def _remove_scene(self) -> None:
        stage = self._attached_stage
        if stage is None:
            self._live_transform_adapter = None
            preview_paths = getattr(self, "_live_preview_paths", None)
            if isinstance(preview_paths, set):
                preview_paths.clear()
            policy_cache = getattr(self, "_live_preview_policy_cache", None)
            if isinstance(policy_cache, dict):
                policy_cache.clear()
            return
        renderer = self._renderer
        if renderer is None:
            raise RuntimeError(
                "cannot release borrowed OVStage after the OVRTX renderer was destroyed"
            )
        # Ownership: release before ``detach_ovstage`` invalidates the
        # step-result container's native handles.
        self._release_retained_output()
        # Outline membership can survive the detach on both transports —
        # renderer state keyed by prim path (dedicated APIs) or reserved
        # attribute values in this stage's data (a re-attach would still
        # carry them); clear it so a later attachment with same-named
        # prims does not inherit a stale outline.  Transactional: the
        # tracked set advances ONLY when the clear write succeeds, and a
        # failed detach below restores the cleared membership in-place (the
        # scene is still attached and its outline must not need an external
        # selection resync).  A clear failure followed by a successful
        # detach keeps the stale paths tracked for retry at the next
        # load_stage / selection sync instead of silently leaking them. Such
        # paths are cleanup work, not applied membership in a later generation.
        outlined_paths = getattr(self, "_selection_outline_previous_paths", None)
        cleared_for_detach: list[str] = []
        if outlined_paths:
            candidate_paths = sorted(outlined_paths)
            cleared = self._write_selection_outline_group(
                candidate_paths, _SELECTION_OUTLINE_CLEAR_GROUP_ID
            )
            outlined_paths.difference_update(cleared)
            cleared_for_detach = sorted(cleared)
        scene = self._scene
        population = self._runtime_population
        reference_handle = self._runtime_reference_handle
        path_dictionary = self._path_dictionary
        runtime_root_path = str(
            getattr(self, "_runtime_root_path", _RUNTIME_ROOT_LOCAL_PATH)
        )
        owner_handle = getattr(self, "_render_settings_owner_handle", None)
        owner_path = str(
            getattr(self, "_runtime_render_settings_local_path", "") or ""
        )

        # The camera query and its path list are Python-owned resources that
        # native code only borrows while pacing is active. The borrower is
        # drained above, so release them before detach can invalidate the
        # Stage instance they reference.
        self._release_frame_pacing_camera_query()

        # A failed detach must leave the Stage alive and registered with its
        # owner.  Clearing state first would let OvstageScene.shutdown destroy
        # an instance that OVRTX may still be borrowing.
        try:
            renderer.detach_ovstage()
        except BaseException:
            # The scene remains attached: restore its visible outline and
            # local tracking in-place before the failure returns, so no
            # external selection resync is required.  If the restoration
            # write itself fails, the state stays truthful (membership
            # cleared and untracked) and the PRIMARY detach failure still
            # propagates.
            if cleared_for_detach:
                restored = self._write_selection_outline_group(
                    cleared_for_detach, _SELECTION_OUTLINE_GROUP_ID
                )
                outlined_paths.update(restored)
            raise
        barrier_callback = getattr(
            self, "_frame_pacing_stage_barrier_callback", None
        )
        if (
            barrier_callback is not None
            and getattr(stage, "_ovui_before_frame_publication", None)
            is barrier_callback
        ):
            stage._ovui_before_frame_publication = None
        self._attached_stage = None
        stale_paths = getattr(self, "_selection_outline_stale_paths", None)
        if not isinstance(stale_paths, set):
            stale_paths = set()
            self._selection_outline_stale_paths = stale_paths
        stale_paths.update(outlined_paths or ())
        if isinstance(outlined_paths, set):
            outlined_paths.clear()
        self._selection_outline_generation = int(
            getattr(self, "_selection_outline_generation", 0) or 0
        ) + 1
        requested_paths = list(getattr(self, "_selected_paths", ()) or ())
        self._selection_outline_last_write = {
            "requested_paths": requested_paths,
            "applied_paths": [],
            "pending_paths": sorted(set(requested_paths)),
            "stale_cleanup_paths": sorted(stale_paths),
            "generation": self._selection_outline_generation,
            "stale_reason": "stage_detached",
        }
        self._runtime_population = None
        self._runtime_reference_handle = None
        self._render_settings_owner_handle = None
        self._runtime_render_settings_local_path = ""
        self._render_settings_owner_opinions = {}
        self._path_dictionary = None
        self._live_transform_adapter = None
        preview_paths = getattr(self, "_live_preview_paths", None)
        if isinstance(preview_paths, set):
            preview_paths.clear()
        policy_cache = getattr(self, "_live_preview_policy_cache", None)
        if isinstance(policy_cache, dict):
            policy_cache.clear()
        detach_renderer = getattr(scene, "detach_renderer", None)
        if callable(detach_renderer):
            detach_renderer(self)
        destroy = getattr(path_dictionary, "destroy", None)
        if callable(destroy):
            try:
                destroy()
            except Exception:
                pass
        if population is not None and owner_handle is not None:
            try:
                # Order-reversed: the owner reference was added after the
                # runtime layer, so it is removed before it.
                _remove_render_settings_owner(
                    scene=scene,
                    population=population,
                    stage=stage,
                    reference_handle=owner_handle,
                    owner_path=owner_path,
                )
            except Exception as exc:
                # Same policy as the runtime layer below: the renderer is
                # detached, and scene-owned root tracking survives so export
                # still filters the stranded private prim.  It is still a
                # stranded private prim in a scene the user keeps working in,
                # so it is reported rather than silently absorbed.
                print(
                    "[OvstageRendererAdapter] private RenderSettings owner "
                    f"{owner_path} could not be removed on detach "
                    f"({type(exc).__name__}: {exc}); it stays tracked as a "
                    "scene-owned presentation root and is filtered from export",
                    file=sys.stderr,
                )
        if population is not None and reference_handle is not None:
            try:
                _remove_runtime_layer_from_scene(
                    scene=scene,
                    population=population,
                    stage=stage,
                    reference_handle=reference_handle,
                    runtime_root_path=runtime_root_path,
                )
            except Exception:
                # The renderer is detached, but the population reference may
                # remain. Scene-owned root tracking deliberately survives so
                # persistent export filters the stranded private subtree.
                pass

    def _apply_resolution(self, width: int, height: int) -> None:
        metric_id = self.start_ovui_performance_scope("OvstageRendererAdapter._apply_resolution")
        try:
            target = (int(width), int(height))
            if target == self._last_resolution:
                return
            stage = self._attached_stage
            if stage is None:
                self._last_resolution = target
                self._last_render_product_resolution = target
                return
            render_product_path = str(getattr(self, "_render_product_path", "") or "")
            runtime_root_path = str(
                getattr(self, "_runtime_root_path", _RUNTIME_ROOT_LOCAL_PATH)
            )
            if not (
                render_product_path == runtime_root_path
                or render_product_path.startswith(f"{runtime_root_path}/")
            ):
                # The viewport size is presentation state. A public RenderProduct
                # may only be changed by a native authoring command. Keep the UI extent for output
                # normalization while allowing the next map to report the source
                # product's unchanged native extent.
                self._last_resolution = target
                self._last_render_product_resolution = None
                return
            # Ownership: the reset below invalidates retained output handles.
            # Placed after the no-op guards so unchanged-resolution frames stay
            # free, immediately before the native mutation.
            self._release_retained_output()
            try:
                with StageWriteBatch(stage, [render_product_path]) as batch:
                    batch.write_fixed(
                        "resolution",
                        np.asarray(target, dtype=np.int32),
                        lanes=2,
                    )
                self._last_resolution = target
                self._last_render_product_resolution = None
                reset = getattr(self._renderer, "reset", None)
                if callable(reset):
                    reset()
                    if not self._selection_outline_previous_paths:
                        # A reset while no outline membership is applied leaves
                        # the outline pass inactive for later writes; re-arm the
                        # one-shot activation reset for the next selection.
                        self._selection_outline_pass_needs_reset = True
            except Exception as exc:
                if _require_real_ovrtx():
                    raise RuntimeError("OVStage render-product resolution write failed") from exc
                return
        finally:
            self.end_ovui_performance_scope(metric_id)

    def _apply_secondary_resolution(self, width: int, height: int) -> None:
        target = (int(width), int(height))
        if target == self._secondary_last_resolution:
            return
        stage = self._attached_stage
        if stage is None:
            self._secondary_last_resolution = target
            return
        self._release_retained_output()
        try:
            with StageWriteBatch(
                stage,
                [self._secondary_render_product_path],
            ) as batch:
                batch.write_fixed(
                    "resolution",
                    np.asarray(target, dtype=np.int32),
                    lanes=2,
                )
            self._secondary_last_resolution = target
            reset = getattr(self._renderer, "reset", None)
            if callable(reset):
                reset()
        except Exception as exc:
            if _require_real_ovrtx():
                raise RuntimeError(
                    "OVStage secondary render-product resolution write failed"
                ) from exc

    def _configure_selection_outline_styles(self) -> None:
        if getattr(self, "_selection_outline_styles_configured", False):
            return
        renderer = getattr(self, "_renderer", None)
        setter = getattr(renderer, "set_selection_group_styles", None)
        if setter is None:
            return
        # Ownership: style configuration mutates native renderer state; the
        # latch above keeps this off the per-frame no-op path.
        self._release_retained_output()
        try:
            style_cls = getattr(self._ovrtx, "SelectionGroupStyle", None)
            style = (
                style_cls(
                    outline_color=_SELECTION_OUTLINE_COLOR,
                    fill_color=_SELECTION_OUTLINE_FILL,
                )
                if style_cls is not None
                else {
                    "outline_color": _SELECTION_OUTLINE_COLOR,
                    "fill_color": _SELECTION_OUTLINE_FILL,
                }
            )
            setter({_SELECTION_OUTLINE_GROUP_ID: style})
        except Exception:
            return
        self._selection_outline_styles_configured = True
        self._selection_outline_style_calls += 1

    def _write_selection_outline_group(
        self, paths: List[str], group_id: int
    ) -> set[str]:
        """Write membership and return only paths established/satisfied.

        Dedicated renderer membership APIs take precedence when available.
        Their completion must be consumed and validated before reporting success:
        an abandoned ovrtx ``Operation`` blocks inside ``__del__`` with a
        ResourceWarning and swallows completion errors there, and an
        unvalidated completion value would advance the outline bookkeeping
        for a write that never applied.  The blocking string variant is
        ovrtx's own ``_async(...).wait()`` wrapper, so completion failures
        surface as exceptions and keep paths retryable.

        When neither string membership method is available, the documented
        membership transport is the reserved
        ``omni:selectionOutlineGroup`` uint8 attribute written through the
        attached OVStage owner (write a non-zero group to outline a prim,
        group 0 to clear).  That fallback is
        ``_write_selection_outline_group_reserved`` below.
        """
        renderer = getattr(self, "_renderer", None)
        if renderer is None or not paths:
            return set()
        requested = list(dict.fromkeys(str(path) for path in paths if path))
        group_setter = getattr(
            renderer, "set_selection_outline_group_strings", None
        )
        async_group_setter = getattr(
            renderer, "set_selection_outline_group_strings_async", None
        )
        stage = getattr(self, "_attached_stage", None)
        if stage is None and int(group_id) == _SELECTION_OUTLINE_CLEAR_GROUP_ID and (
            callable(group_setter) or callable(async_group_setter)
        ):
            # Dedicated APIs retain renderer-owned path membership across the
            # detach boundary, so a tracked stale clear must still reach them.
            existing = list(requested)
        else:
            existing = [
                path for path in requested if _native_path_exists(stage, path)
            ]
        missing = set(requested) - set(existing)
        if not existing:
            return (
                set(requested)
                if int(group_id) == _SELECTION_OUTLINE_CLEAR_GROUP_ID
                else set()
            )
        if (
            callable(group_setter) or callable(async_group_setter)
        ) and not self._native_render_is_paused():
            self._profile_ovui_call(
                "OvstageRendererAdapter._stop_native_frame_pacing",
                self._stop_native_frame_pacing, "selection outline membership",
            )
        if callable(group_setter):
            try:
                group_setter(existing, int(group_id))
            except Exception:
                return missing if int(group_id) == _SELECTION_OUTLINE_CLEAR_GROUP_ID else set()
            self._selection_outline_membership_reset_pending = True
            return set(existing) | (
                missing if int(group_id) == _SELECTION_OUTLINE_CLEAR_GROUP_ID else set()
            )
        if callable(async_group_setter):
            try:
                operation = async_group_setter(existing, int(group_id))
                wait = getattr(operation, "wait", None)
                if not callable(wait):
                    # A completion that cannot be awaited is unverifiable;
                    # counting it as success would cache an unconfirmed
                    # write as applied and never retry it.
                    return missing if int(group_id) == _SELECTION_OUTLINE_CLEAR_GROUP_ID else set()
                # ``wait()`` blocks until the renderer resolves the
                # operation and raises on completion failure; a ``None``
                # (timeout-shaped) result is never treated as applied.
                completed = self._profile_ovui_call(
                    "OvstageRendererAdapter.selection_outline.wait", wait
                )
            except Exception:
                return missing if int(group_id) == _SELECTION_OUTLINE_CLEAR_GROUP_ID else set()
            if completed is None:
                return missing if int(group_id) == _SELECTION_OUTLINE_CLEAR_GROUP_ID else set()
            self._selection_outline_membership_reset_pending = True
            return set(existing) | (
                missing if int(group_id) == _SELECTION_OUTLINE_CLEAR_GROUP_ID else set()
            )
        written = self._write_selection_outline_group_reserved(existing, group_id)
        if int(group_id) == _SELECTION_OUTLINE_CLEAR_GROUP_ID:
            written.update(missing)
        return written

    def _write_selection_outline_group_reserved(
        self, paths: List[str], group_id: int
    ) -> set[str]:
        """Write membership via the reserved presentation attribute.

        This is the ovrtx-documented membership transport on the installed
        0.4.0 wheel: per-prim uint8 ``omni:selectionOutlineGroup`` values
        (exported by ovrtx as ``OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP``)
        written through the OVStage OWNER's copy-in API — StageWriteBatch's
        begin_frame/write_attribute/end_frame discipline, identical to the
        adapter's render-product resolution write — never through an OVRTX
        stage-data API.  The attribute is renderer-defined presentation
        metadata, not user scene content.

        Writes are UPSERTs, so every target must already exist in the
        attached stage: a path that does not carries no membership in this
        stage.  Missing paths are therefore vacuously satisfied for a clear
        (nothing to clear — the load_stage stale-retry case, where writing
        would ghost-create prims in the new scene) and unoutlineable for a
        set (there is no prim to render).  The batch is awaited by
        ``write_fixed``; any failure leaves the paths retryable.
        """
        stage = getattr(self, "_attached_stage", None)
        if stage is None or not supports_native_stage_writes(stage):
            return set()
        target_paths = [
            path for path in paths if _native_path_exists(stage, path)
        ]
        if not target_paths:
            # No existing prim carries or can carry membership; the request
            # is already satisfied without touching the stage.
            return set()
        attribute_name = str(
            getattr(
                self._ovrtx,
                "OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP",
                "omni:selectionOutlineGroup",
            )
        )
        try:
            with StageWriteBatch(stage, target_paths) as batch:
                batch.write_fixed(
                    attribute_name,
                    np.full(len(target_paths), int(group_id), dtype=np.uint8),
                )
        except Exception:
            return set()
        self._selection_outline_reserved_writes += 1
        return set(target_paths)

    def _ensure_selection_outline_pass_active(self) -> None:
        """Activate outlines once, avoiding repeated modern membership resets.

        A missing or failing ``reset`` leaves the relevant flag armed, so the
        next selection sync retries instead of claiming presentation state
        that OVRTX has not consumed.
        """
        # OVRTX 0.5 applies completed dedicated membership changes on the next
        # step/step_with_stage once the outline pass is active. Fresh viewer
        # attachments still need their one-shot activation; waiving it leaves
        # outlines invisible until a camera change invalidates the render.
        # Repeated resets rebuild render history and can stall every click.
        # Use the loaded native library version, not Python wheel metadata:
        # a newer wrapper alone cannot retire the older-runtime workaround.
        native_version = getattr(self._renderer, "version", None)
        if (
            isinstance(native_version, tuple)
            and len(native_version) >= 3
            and all(isinstance(part, int) for part in native_version)
            and native_version >= (0, 5, 0)
        ):
            # Named bindings keep non-invoking probes visible to the ownership audit.
            group_setter = getattr(
                self._renderer, "set_selection_outline_group_strings", None
            )
            async_group_setter = getattr(
                self._renderer, "set_selection_outline_group_strings_async", None
            )
            if callable(group_setter) or callable(async_group_setter):
                self._selection_outline_membership_reset_pending = False
                # Clear-only work must not spend an owed activation on empty
                # membership (for example after a failed activation reset).
                if not (
                    set(self._selected_paths) & self._selection_outline_previous_paths
                ):
                    return
        activation_reset_pending = bool(
            getattr(self, "_selection_outline_pass_needs_reset", False)
        )
        membership_reset_pending = bool(
            getattr(self, "_selection_outline_membership_reset_pending", False)
        )
        if not activation_reset_pending and not membership_reset_pending:
            return
        reset = getattr(self._renderer, "reset", None)
        if not callable(reset):
            return
        # Ownership: reset invalidates retained output handles (same
        # ordering as the resolution-change reset above).
        self._release_retained_output()
        try:
            reset()
        except Exception:
            return
        self._selection_outline_pass_needs_reset = False
        self._selection_outline_membership_reset_pending = False

    def _ndc_rect_to_pick_pixels(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> tuple[int, int, int, int]:
        width, height = self._pick_resolution()
        width = max(1, int(width))
        height = max(1, int(height))

        def _clamp(value: float) -> float:
            return max(-1.0, min(1.0, float(value)))

        def _to_px(x_ndc: float, y_ndc: float) -> tuple[int, int]:
            px = int(round((_clamp(x_ndc) + 1.0) * 0.5 * (width - 1)))
            py = int(round((1.0 - _clamp(y_ndc)) * 0.5 * (height - 1)))
            return (
                max(0, min(width - 1, px)),
                max(0, min(height - 1, py)),
            )

        ax, ay = _to_px(x0, y0)
        bx, by = _to_px(x1, y1)
        left = min(ax, bx)
        top = min(ay, by)
        right = min(width, max(ax, bx) + 1)
        bottom = min(height, max(ay, by) + 1)
        return (left, top, right, bottom)

    def _pick_query_uses_ndc(self) -> bool:
        """Whether ``enqueue_pick_query`` takes a normalized [0, 1] NDC rect.

        The ovrtx pick-query coordinate convention changed at 0.4.0: Kit ovrtx
        >= 0.4.0 takes a normalized [0, 1] top-left NDC rectangle and rejects
        out-of-bounds (pixel) values, while the old standalone ovrtx 0.3.x took
        RenderProduct pixel-int rectangles. Dispatch on the resolved ovrtx
        package version so both runtimes pick correctly. An unknown/non-numeric
        version defaults to NDC (the current Kit target).
        """
        version = getattr(self, "_ovrtx_version", None)
        if not isinstance(version, tuple):
            version = _version_tuple(getattr(self._ovrtx, "__version__", "unknown"))
        if isinstance(version, tuple) and len(version) >= 2:
            return version >= (0, 4, 0)
        return True

    def _pick_pixels_to_query_rect(
        self, left: int, top: int, right: int, bottom: int
    ) -> tuple[float, float, float, float] | tuple[int, int, int, int]:
        """Return the pick-query rectangle in the convention the active ovrtx
        expects: normalized [0, 1] NDC for >= 0.4.0, pixel ints for 0.3.x."""
        if self._pick_query_uses_ndc():
            return self._pick_pixels_to_query_ndc(left, top, right, bottom)
        return (int(left), int(top), int(right), int(bottom))

    def _pick_pixels_to_query_ndc(
        self, left: int, top: int, right: int, bottom: int
    ) -> tuple[float, float, float, float]:
        """Convert a top-left-origin pixel rect to the normalized [0, 1] NDC
        rectangle Kit ovrtx ``enqueue_pick_query`` expects.

        Kit ovrtx 0.4.0 takes ``[x/width, y/height, (x+1)/width, (y+1)/height]``
        top-left-origin NDC and rejects out-of-bounds (pixel) values, so the
        old pixel-rect call silently raised inside ``pick`` and never enqueued.
        """
        width, height = self._pick_resolution()
        width = max(1, int(width))
        height = max(1, int(height))

        def _norm(value: float, size: int) -> float:
            return max(0.0, min(1.0, float(value) / float(size)))

        return (
            _norm(left, width),
            _norm(top, height),
            _norm(right, width),
            _norm(bottom, height),
        )

    def _pick_resolution(self) -> tuple[int, int]:
        resolution = getattr(self, "_last_render_product_resolution", None)
        if resolution is None:
            resolution = getattr(self, "_last_resolution", _DEFAULT_RESOLUTION)
        try:
            width, height = resolution
        except Exception:
            width, height = _DEFAULT_RESOLUTION
        return (max(1, int(width)), max(1, int(height)))

    def _cache_hits_for_replacement_pick(
        self,
        name: str,
        hits: list[tuple[str, tuple[float, float, float]]],
    ) -> None:
        if not hits:
            return
        for entry in reversed(self._in_flight_pick_queries):
            if entry[1] == "point" and entry[2] == name and entry[3] is not None:
                entry[5] = list(hits)
                return

    def _select_point_hit(
        self,
        hits: list[tuple[str, tuple[float, float, float]]],
        target: tuple[float, float] | None,
    ) -> tuple[str, tuple[float, float, float]] | None:
        if not hits:
            return None
        if len(hits) == 1:
            return hits[0]
        if target is None:
            return None
        view = getattr(self, "_last_view_matrix", None)
        proj = getattr(self, "_last_proj_matrix", None)
        if view is None or proj is None:
            return None

        width, height = self._pick_resolution()
        width = max(1, int(width))
        height = max(1, int(height))
        target_x = max(-1.0, min(1.0, float(target[0])))
        target_y = max(-1.0, min(1.0, float(target[1])))

        candidates: list[
            tuple[float, float, float, int, tuple[str, tuple[float, float, float]]]
        ] = []
        for index, hit in enumerate(hits):
            closest_point_distance = math.inf
            closest_point_depth = math.inf
            for ndc in _project_world_to_ndc_candidates(hit[1], view, proj):
                dx = (float(ndc[0]) - target_x) * 0.5 * width
                dy = (float(ndc[1]) - target_y) * 0.5 * height
                distance_px = math.hypot(dx, dy)
                if distance_px < closest_point_distance:
                    closest_point_distance = distance_px
                    closest_point_depth = float(ndc[2])
                if distance_px <= _POINT_PICK_TOLERANCE_PX:
                    candidates.append((distance_px, distance_px, float(ndc[2]), index, hit))
                    break
            bounds_hit = self._projected_prim_bounds_pick_distance(
                hit[0],
                target_x,
                target_y,
                view,
                proj,
                width,
                height,
            )
            if bounds_hit is not None and bounds_hit[0] <= _POINT_PICK_TOLERANCE_PX:
                bounds_distance, bounds_depth = bounds_hit
                candidates.append(
                    (
                        bounds_distance,
                        closest_point_distance,
                        min(closest_point_depth, bounds_depth),
                        index,
                        hit,
                    )
                )
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        return candidates[0][4]

    def _projected_prim_bounds_pick_distance(
        self,
        path: str,
        target_x: float,
        target_y: float,
        view: np.ndarray,
        proj: np.ndarray,
        width: int,
        height: int,
    ) -> tuple[float, float] | None:
        scene = getattr(self, "_scene", None)
        stage = getattr(scene, "_stage", None)
        if stage is None or not getattr(scene, "is_open", False):
            return None
        try:
            type_name = _query_records(stage).get(str(path), "")
            bounds = _local_geometry_bounds(stage, str(path), type_name)
        except Exception:
            return None
        if bounds is None:
            return None
        matrix = _read_matrix(stage, str(path), "worldMatrix")
        if matrix is None:
            matrix = _read_matrix(stage, str(path), "localMatrix")

        projected: list[tuple[float, float, float]] = []
        for corner in _bounds_corners(*bounds):
            point = _transform_point(corner, matrix)
            ndc = _project_world_to_ndc(point, view, proj)
            if ndc is not None:
                projected.append(ndc)
        if not projected:
            return None

        xs = [(float(ndc[0]) + 1.0) * 0.5 * width for ndc in projected]
        ys = [(float(ndc[1]) + 1.0) * 0.5 * height for ndc in projected]
        target_px = (float(target_x) + 1.0) * 0.5 * width
        target_py = (float(target_y) + 1.0) * 0.5 * height
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        dx = max(min_x - target_px, 0.0, target_px - max_x)
        dy = max(min_y - target_py, 0.0, target_py - max_y)
        depth = min(float(ndc[2]) for ndc in projected)
        return (math.hypot(dx, dy), depth)

    def _dispatch_pending_pick_results(self, products: Any) -> None:
        queue = getattr(self, "_in_flight_pick_queries", None)
        if not queue:
            return
        hits = self._read_pick_hits(products)
        entry = queue.popleft()
        _seq, kind, name, callback, cancel_reason, cached_hits, point_target = entry
        self._pick_result_count = getattr(self, "_pick_result_count", 0) + 1
        effective_hits = hits or (cached_hits or [])
        if kind == "point":
            point_hit = self._select_point_hit(effective_hits, point_target)
            point_path = point_hit[0] if point_hit is not None else None
            point_world = point_hit[1] if point_hit is not None else None
            self._last_pick_path = point_path
            self._last_pick_paths = (point_path,) if point_path else ()
            self._last_pick_world_point = point_world
            if callback is None:
                if cancel_reason == _PICK_CANCEL_REPLACED:
                    self._cache_hits_for_replacement_pick(name, hits)
                return
            self._deliver_pick_callback(callback, point_path, point_world)
            return
        rect_paths = list(dict.fromkeys(path for path, _point in effective_hits if path))
        self._last_pick_path = rect_paths[0] if len(rect_paths) == 1 else None
        self._last_pick_paths = tuple(rect_paths)
        self._last_pick_world_point = None
        if callback is None:
            return
        self._deliver_pick_callback(callback, rect_paths)

    def _deliver_pick_callback(
        self, callback: Callable[..., None], *args: Any
    ) -> None:
        """Keep callbacks produced by the renderer worker on the UI thread."""

        if threading.current_thread() is self._render_worker_thread:
            with self._render_state_lock:
                self._completed_pick_callbacks.append((callback, args))
            return
        try:
            callback(*args)
        except Exception:
            pass

    def _drain_completed_pick_callbacks(self) -> None:
        """Run renderer results while the UI thread consumes ready frames."""

        with self._render_state_lock:
            callbacks = tuple(self._completed_pick_callbacks)
            self._completed_pick_callbacks.clear()
        for callback, args in callbacks:
            try:
                callback(*args)
            except Exception:
                pass

    def _dispatch_pending_pick_misses(self) -> None:
        entries = list(getattr(self, "_in_flight_pick_queries", ()))
        self._in_flight_pick_queries.clear()
        self._last_pick_path = None
        self._last_pick_paths = ()
        self._last_pick_world_point = None
        for (
            _seq,
            kind,
            _name,
            callback,
            _cancel_reason,
            _cached_hits,
            _target,
        ) in entries:
            if callback is None:
                continue
            if kind == "point":
                self._deliver_pick_callback(callback, None, None)
            else:
                self._deliver_pick_callback(callback, [])

    def _read_pick_hits(
        self,
        products: Any,
    ) -> list[tuple[str, tuple[float, float, float]]]:
        try:
            product = products[self._render_product_path]
            frame = product.frames[0]
            render_vars = getattr(frame, "render_vars", None) or {}
            rv = render_vars.get(getattr(self._ovrtx, "OVRTX_RENDER_VAR_PICK_HIT", _PICK_HIT_VAR))
            if rv is None:
                return []
            device = getattr(getattr(self._ovrtx, "Device", None), "CPU", None)
        except Exception:
            return []
        mapping = None
        should_unmap = False
        try:
            mapping = rv.map(device=device) if device is not None else rv.map()
            unmap = getattr(mapping, "unmap", None)
            if (
                not callable(unmap)
                and hasattr(mapping, "__enter__")
                and hasattr(
                    mapping,
                    "__exit__",
                )
            ):
                with mapping as mapped:
                    mapped_hits = self._parse_pick_hit_mapping(mapped)
                    if mapped_hits is not None:
                        return mapped_hits
                    try:
                        data = mapped.tensor.to_bytes()
                    except Exception:
                        data = b""
                return self._parse_pick_hit_buffer(data)
            should_unmap = callable(unmap)
            mapped_hits = self._parse_pick_hit_mapping(mapping)
            if mapped_hits is not None:
                return mapped_hits
            try:
                data = mapping.tensor.to_bytes()
            except Exception:
                data = b""
        except Exception:
            return []
        finally:
            if should_unmap:
                unmap = getattr(mapping, "unmap", None)
                try:
                    unmap()
                except Exception:
                    pass
        return self._parse_pick_hit_buffer(data)

    def _parse_pick_hit_mapping(
        self,
        mapping: Any,
    ) -> list[tuple[str, tuple[float, float, float]]] | None:
        try:
            tensor_names = set(mapping.keys())
        except Exception:
            tensor_names = None
        if tensor_names is not None and (
            "primPath" not in tensor_names or "worldPositionM" not in tensor_names
        ):
            return None
        magic = self._read_pick_hit_param(mapping, "magic")
        version = self._read_pick_hit_param(mapping, "version")
        hit_count = self._read_pick_hit_param(mapping, "hitCount")
        expected_magic = int(
            getattr(
                self._ovrtx,
                "OVRTX_PICK_HIT_MAGIC",
                getattr(
                    self._ovrtx,
                    "OVRTX_PICK_HIT_BUFFER_MAGIC",
                    _PICK_HIT_BUFFER_MAGIC,
                ),
            )
        )
        expected_version = int(
            getattr(
                self._ovrtx,
                "OVRTX_PICK_HIT_VERSION",
                getattr(
                    self._ovrtx,
                    "OVRTX_PICK_HIT_BUFFER_VERSION",
                    _PICK_HIT_BUFFER_VERSION,
                ),
            )
        )
        if (
            magic != expected_magic
            or version != expected_version
            or hit_count is None
            or hit_count <= 0
        ):
            return []
        try:
            prim_paths = np.from_dlpack(mapping["primPath"]).copy().reshape(-1)
            world_positions = np.from_dlpack(mapping["worldPositionM"]).copy().reshape((-1, 3))
        except Exception:
            return []
        hits: list[tuple[str, tuple[float, float, float]]] = []
        count = min(int(hit_count), len(prim_paths), len(world_positions))
        for index in range(count):
            path = self._resolve_ovrtx_prim_path(int(prim_paths[index]))
            if not path:
                continue
            wx, wy, wz = world_positions[index]
            hits.append((path, (float(wx), float(wy), float(wz))))
        return hits

    def _read_pick_hit_param(self, mapping: Any, name: str) -> int | None:
        try:
            param = mapping.params.get(name)
            if param is None:
                return None
            arr = np.from_dlpack(param)
            if arr.size <= 0:
                return None
            return int(arr.reshape(-1)[0])
        except Exception:
            return None

    def _parse_pick_hit_buffer(
        self,
        data: bytes,
    ) -> list[tuple[str, tuple[float, float, float]]]:
        if len(data) < _PICK_HIT_HEADER.size:
            return []
        magic, version, hit_count, stride = _PICK_HIT_HEADER.unpack_from(data, 0)
        expected_magic = int(
            getattr(self._ovrtx, "OVRTX_PICK_HIT_BUFFER_MAGIC", _PICK_HIT_BUFFER_MAGIC)
        )
        expected_version = int(
            getattr(
                self._ovrtx,
                "OVRTX_PICK_HIT_BUFFER_VERSION",
                _PICK_HIT_BUFFER_VERSION,
            )
        )
        if magic != expected_magic or version != expected_version or hit_count <= 0:
            return []
        if stride < _PICK_HIT_RECORD.size:
            return []
        hits: list[tuple[str, tuple[float, float, float]]] = []
        offset = _PICK_HIT_HEADER.size
        for _ in range(int(hit_count)):
            if offset + _PICK_HIT_RECORD.size > len(data):
                break
            (
                prim_path_id,
                _object_type,
                _pad0,
                _instance_id,
                wx,
                wy,
                wz,
                _nx,
                _ny,
                _nz,
                _pad1,
            ) = _PICK_HIT_RECORD.unpack_from(data, offset)
            offset += int(stride)
            path = self._resolve_ovrtx_prim_path(int(prim_path_id))
            if path:
                hits.append((path, (float(wx), float(wy), float(wz))))
        return hits

    def _resolve_ovrtx_prim_path(self, prim_path_id: int) -> Optional[str]:
        paths = self._path_dictionary
        if paths is None:
            return None
        try:
            path = paths.path_to_string(int(prim_path_id))
        except Exception:
            return None
        return _borrowed_path_to_scene_path(
            str(path or ""),
            runtime_root_path=getattr(
                self,
                "_runtime_root_path",
                _RUNTIME_ROOT_LOCAL_PATH,
            ),
        )

    def _extract_ldr_color(
        self,
        products: Any,
        width: int,
        height: int,
    ) -> np.ndarray | GpuFrame:
        try:
            rv = self._presentation_render_var(products, self._render_product_path)
        except Exception as exc:
            if _require_real_ovrtx():
                raise RuntimeError(
                    "ovrtx render output map failed "
                    f"({type(exc).__name__}: {exc})"
                ) from exc
            return np.zeros((height, width, 4), dtype=np.uint8)

        state = getattr(self, "_zero_copy_state", None)
        from ovui_data_adapters.common._render_product_stream import for_current_product
        livestream = for_current_product(self)
        committed_resolution = getattr(self, "_last_resolution", (width, height))
        gpu_size_matches = (int(width), int(height)) == committed_resolution

        # A single CUDA mapping feeds both presentation consumers when the
        # ovui ImageBridge supports GPU ingest.  Livestream copies from this
        # same tensor before GpuFrame transfers mapping ownership to the UI.
        if state is not None and state.gpu_pending and gpu_size_matches:
            mapping = None
            try:
                mapping = rv.map(device=self._ovrtx.Device.CUDA)
                mapping.__enter__()
                tensor = _mapped_render_var_tensor(mapping)
                tensor_layout = _cuda_tensor_extent_and_row_stride_bytes(tensor)
                if tensor_layout is None:
                    actual_width = int(width)
                    actual_height = int(height)
                    stride = None
                else:
                    actual_width, actual_height, stride = tensor_layout
                self._last_render_product_resolution = (
                    int(actual_width),
                    int(actual_height),
                )
                if int(actual_width) != int(width) or int(actual_height) != int(height):
                    try:
                        mapping.__exit__(None, None, None)
                    except Exception:
                        pass
                    mapping = None
                    raise _RenderProductResolutionMismatch(
                        "CUDA render var extent "
                        f"{int(actual_width)}x{int(actual_height)} "
                        f"does not match requested {int(width)}x{int(height)}"
                    )
                if livestream is not None:
                    try:
                        self._livestream_zero_copy_tee_attempt_count = int(
                            getattr(
                                self,
                                "_livestream_zero_copy_tee_attempt_count",
                                0,
                            )
                            or 0
                        ) + 1
                        pushed = livestream.tee_to_ovstream(tensor, width, height)
                        if pushed:
                            self._livestream_zero_copy_tee_success_count = int(
                                getattr(
                                    self,
                                    "_livestream_zero_copy_tee_success_count",
                                    0,
                                )
                                or 0
                            ) + 1
                    except Exception:
                        # The transport is best effort.  Never forfeit the
                        # zero-copy UI frame because the stream leg failed.
                        pass
                return GpuFrame(
                    ptr=int(tensor.data),
                    width=int(width),
                    height=int(height),
                    mapping=mapping,
                    stride=stride,
                )
            except _RenderProductResolutionMismatch:
                pass
            except Exception as exc:
                if mapping is not None:
                    try:
                        mapping.__exit__(None, None, None)
                    except Exception:
                        pass
                state.mark_fallback(f"CUDA map raised: {type(exc).__name__}: {exc}")

        arr: np.ndarray | None = None
        if livestream is not None:
            try:
                with rv.map(device=self._ovrtx.Device.CUDA) as mapping:
                    tensor = _mapped_render_var_tensor(mapping)
                    tensor_layout = _cuda_tensor_extent_and_row_stride_bytes(tensor)
                    if tensor_layout is None:
                        actual_width = int(width)
                        actual_height = int(height)
                    else:
                        actual_width, actual_height, _stride = tensor_layout
                    self._last_render_product_resolution = (
                        int(actual_width),
                        int(actual_height),
                    )
                    if (int(actual_width), int(actual_height)) != (
                        int(width),
                        int(height),
                    ):
                        raise _RenderProductResolutionMismatch(
                            "CUDA render var extent "
                            f"{int(actual_width)}x{int(actual_height)} "
                            f"does not match requested {int(width)}x{int(height)}"
                        )
                    arr = livestream.tee_and_d2h(
                        tensor,
                        width,
                        height,
                        host_buf=getattr(self, "_livestream_host_buf", None),
                    )
                    self._livestream_host_buf = arr
                    self._livestream_cuda_tee_and_d2h_count = int(
                        getattr(self, "_livestream_cuda_tee_and_d2h_count", 0) or 0
                    ) + 1
            except _RenderProductResolutionMismatch:
                # Resize races are expected.  A CPU map below is allowed to
                # normalize the producer's actual extent for this frame.
                pass
            except Exception:
                # Livestream is optional.  Fall through to the established
                # CPU output path and report only the first escaped failure.
                if not getattr(self, "_livestream_error_logged", False):
                    import traceback as _traceback

                    _traceback.print_exc()
                    self._livestream_error_logged = True

        if arr is None:
            try:
                arr = self._map_presentation_frame_cpu(rv)
                if livestream is not None:
                    self._livestream_cpu_presentation_count = int(
                        getattr(self, "_livestream_cpu_presentation_count", 0) or 0
                    ) + 1
                if arr.ndim == 3 and arr.shape[0] > 0 and arr.shape[1] > 0:
                    self._last_render_product_resolution = (
                        int(arr.shape[1]),
                        int(arr.shape[0]),
                    )
            except Exception as exc:
                if _require_real_ovrtx():
                    raise RuntimeError(
                        "ovrtx render output map failed "
                        f"({type(exc).__name__}: {exc})"
                    ) from exc
                return np.zeros((height, width, 4), dtype=np.uint8)

        # An all-black frame is VALID fresh output from the active product
        # (e.g. zero-bounce path tracing, a black constant color, or a camera
        # facing empty space). Raising here conflated legitimate black frames
        # with pipeline failure, flooding "ovrtx render output is empty"
        # while presentation stalled on a stale frame (borrow steps advanced,
        # successful frames froze). Real failures still raise above: a failed
        # step, a missing product/var, or a failed output map.
        # (#110's fast `_rgba_frame_is_black` helper is retained for
        # diagnostics; it is no longer a failure condition.)
        return _normalize_rgba(arr, width, height)


class _RuntimeLayer:
    def __init__(
        self,
        *,
        usda: str,
        root_path: str,
        camera_path: str,
        render_product_path: str,
        camera_matrix: tuple[float, ...],
    ) -> None:
        self.usda = usda
        self.root_path = root_path
        self.camera_path = camera_path
        self.render_product_path = render_product_path
        self.camera_matrix = camera_matrix


def _build_runtime_layer(
    stage: Any,
    *,
    resolution: tuple[int, int] = _DEFAULT_RESOLUTION,
    records: dict[str, str] | None = None,
    runtime_root_path: str = _RUNTIME_ROOT_LOCAL_PATH,
    viewport_quality: int = 0,
) -> _RuntimeLayer:
    records = _query_records(stage) if records is None else records
    # A newly-created durable USD has no user prims yet. The private runtime
    # layer below supplies the camera, RenderProduct, RenderVar and fallback
    # light that OVRTX needs, so an empty query is a valid document rather than
    # a renderer error. Framing already falls back to the origin/unit radius.
    camera_matrix = _framing_camera_matrix(stage, records)
    width, height = (max(int(resolution[0]), 1), max(int(resolution[1]), 1))

    lines = [
        "#usda 1.0",
        "(",
        f'    defaultPrim = "{_RUNTIME_LAYER_PRIM}"',
        ")",
        "",
        f'def Scope "{_RUNTIME_LAYER_PRIM}"',
        "{",
        '    def Scope "Render"',
        "    {",
        '        def Scope "Cameras"',
        "        {",
        '            def Camera "Main"',
        "            {",
        "                float focalLength = 24",
        "                float horizontalAperture = 20.955",
        "                float verticalAperture = 15.2908",
        "                float2 clippingRange = (0.01, 10000)",
        '                token projection = "perspective"',
        f"                matrix4d xformOp:transform = {_format_matrix(camera_matrix)}",
        '                uniform token[] xformOpOrder = ["xformOp:transform"]',
        "            }",
        '            def Camera "Secondary"',
        "            {",
        "                float focalLength = 24",
        "                float horizontalAperture = 20.955",
        "                float verticalAperture = 15.2908",
        "                float2 clippingRange = (0.01, 10000)",
        '                token projection = "perspective"',
        f"                matrix4d xformOp:transform = {_format_matrix(camera_matrix)}",
        '                uniform token[] xformOpOrder = ["xformOp:transform"]',
        "            }",
        "        }",
        '        def RenderProduct "Viewport"',
        "        {",
        "            rel camera = <../Cameras/Main>",
        "            uniform uint[] deviceIds = [0]",
        f"            custom int omni:rtx:quality = {viewport_quality}",
        "            rel orderedVars = <../Vars/LdrColor>",
        f"            uniform int2 resolution = ({width}, {height})",
        "        }",
        '        def RenderProduct "ViewportSecondary"',
        "        {",
        "            rel camera = <../Cameras/Secondary>",
        "            uniform uint[] deviceIds = [0]",
        "            rel orderedVars = <../Vars/LdrColor>",
        f"            uniform int2 resolution = ({width}, {height})",
        "        }",
        '        def Scope "Vars"',
        "        {",
        '            def RenderVar "LdrColor"',
        "            {",
        f'                uniform string sourceName = "{_LDR_VAR_NAME}"',
        "            }",
        "        }",
    ]
    if not _has_light(records):
        lines.extend(
            [
                '        def DomeLight "FallbackDome"',
                "        {",
                "            color3f inputs:color = (0.01, 0.011, 0.014)",
                "            float inputs:intensity = 2500",
                "        }",
                '        def DistantLight "FallbackKey"',
                "        {",
                "            float inputs:intensity = 3000",
                "            float inputs:angle = 0.0",
                "            matrix4d xformOp:transform = "
                "( (0.866,0,-0.5,0), (-0.354,0.707,-0.612,0), "
                "(0.354,0.707,0.612,0), (0,0,0,1) )",
                '            uniform token[] xformOpOrder = ["xformOp:transform"]',
                "        }",
            ]
        )
    lines.extend(["    }", "}"])
    return _RuntimeLayer(
        usda="\n".join(lines) + "\n",
        root_path=str(runtime_root_path),
        camera_path=f"{runtime_root_path}/Render/Cameras/Main",
        render_product_path=f"{runtime_root_path}/Render/Viewport",
        camera_matrix=camera_matrix,
    )


def _render_settings_owner_literal(usd_type: str, value: Any) -> str:
    """USDA literal for one authored global render-setting opinion."""

    kind = str(usd_type or "").lower()
    if kind == "bool":
        return "true" if bool(value) else "false"
    if kind in ("token", "string"):
        text = str(value).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{text}"'
    if kind in ("int", "uint"):
        return str(int(value))
    if kind == "float":
        return repr(float(value))
    if isinstance(value, (tuple, list)):
        return "(" + ", ".join(repr(float(item)) for item in value) + ")"
    raise RuntimeError(
        f"global render setting has no USDA spelling for type {usd_type!r}"
    )


def _build_render_settings_owner_layer(opinions: Mapping[str, Any]) -> str:
    """The private layer that carries the global RenderSettings prim.

    Declarations follow the installed schema: implementation settings are
    namespaced (``omni:rtx:...``) and are ``custom``; the un-namespaced names
    in this scope are ``UsdRenderSettingsBase`` properties, every one of which
    that build declares ``uniform``.  Re-declaring them differently would be a
    variability/customness conflict on the composed prim.
    """

    lines = [
        "#usda 1.0",
        "(",
        f'    defaultPrim = "{_RENDER_SETTINGS_OWNER_LOCAL_PATH.rsplit("/", 1)[-1]}"',
        ")",
        "",
        f'def {_RENDER_SETTINGS_OWNER_PRIM_TYPE} '
        f'"{_RENDER_SETTINGS_OWNER_LOCAL_PATH.rsplit("/", 1)[-1]}"',
        "{",
    ]
    for attr_name in sorted(opinions):
        spec = _render_setting_builtin_spec(attr_name)
        if spec is None:
            raise RuntimeError(
                f"global render setting {attr_name!r} has no installed schema spec"
            )
        usd_type = str(spec.get("usd_type") or "")
        literal = _render_settings_owner_literal(usd_type, opinions[attr_name])
        declaration = (
            f"custom {usd_type}" if ":" in attr_name else f"uniform {usd_type}"
        )
        lines.append(f"    {declaration} {attr_name} = {literal}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _attach_render_settings_owner(
    scene: Any,
    population: Any,
    stage: Any,
    opinions: Mapping[str, Any],
) -> tuple[Any, str]:
    """Add the private reference that carries the global RenderSettings prim.

    Returns ``(handle, owner_path)``, or ``(None, "")`` when the owner cannot
    be provided — which is not a load failure: the renderer works without it
    and the globally owned rows then fail closed.  The prim is adapter-private
    presentation, so it is registered as a presentation root; a scene that
    already carries its own prim at that exact path is left untouched rather
    than shadowed or mutated, because BORROW forbids authoring user content.
    """

    owner_path = _RENDER_SETTINGS_OWNER_LOCAL_PATH
    if _native_path_exists(stage, owner_path):
        print(
            "[OvstageRendererAdapter] global render settings owner unavailable: "
            f"{owner_path} already exists in the attached scene",
            file=sys.stderr,
        )
        return (None, "")
    _register_presentation_root(scene, owner_path)
    try:
        handle = _add_runtime_layer(
            population,
            stage,
            _build_render_settings_owner_layer(opinions),
            prefix_path=owner_path,
        )
    except Exception as exc:
        # Degrading this optional capability must not fail an otherwise good
        # scene load; the rows it owns reject honestly instead.
        _unregister_presentation_root_if_absent(scene, owner_path)
        print(
            "[OvstageRendererAdapter] global render settings owner unavailable: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return (None, "")
    return (handle, owner_path)


def _select_runtime_root_path(scene: Any) -> str:
    """Choose a private prefix without shadowing native scene topology."""

    stage = getattr(scene, "_stage", None)
    if stage is None:
        return _RUNTIME_ROOT_LOCAL_PATH
    for index in range(1, 10_000):
        candidate = (
            _RUNTIME_ROOT_LOCAL_PATH
            if index == 1
            else f"{_RUNTIME_ROOT_LOCAL_PATH}_{index}"
        )
        if not _native_path_exists(stage, candidate):
            return candidate
    raise RuntimeError("could not allocate a private OVStage presentation prefix")


def _validate_configured_ovrtx_source(module: Any) -> None:
    """Fail closed when ``OVRTX_ROOT`` is shadowed by another installation."""

    configured_root = os.environ.get("OVRTX_ROOT", "").strip()
    module_file = str(getattr(module, "__file__", "") or "").strip()
    if not configured_root or not module_file:
        # Native modules always expose ``__file__``. File-less ModuleType test
        # doubles remain supported without weakening production validation.
        return
    try:
        Path(module_file).resolve().relative_to(Path(configured_root).expanduser().resolve())
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            "OVRTX_ROOT is configured, but Python imported ovrtx from a "
            f"different installation: {module_file}"
        ) from exc


def _apply_population_changes(population: Any, stage: Any) -> int:
    apply_changes = getattr(population, "apply_usd_changes", None)
    if not callable(apply_changes):
        raise RuntimeError("Kit OVStage population.apply_usd_changes is required")
    ordinal = int(stage.begin_frame())
    try:
        apply_changes(stage, ordinal)
    finally:
        stage.end_frame(ordinal)
    return ordinal


def _add_runtime_layer(
    population: Any,
    stage: Any,
    usda: str,
    *,
    prefix_path: str = _RUNTIME_ROOT_LOCAL_PATH,
) -> Any:
    add_reference = getattr(population, "add_usd_reference_from_string", None)
    if not callable(add_reference):
        raise RuntimeError("Kit OVStage population.add_usd_reference_from_string is required")
    handle = add_reference(stage, usda, str(prefix_path))
    try:
        _apply_population_changes(population, stage)
    except Exception:
        # Keep the OVStage population transaction clean when the private
        # presentation layer fails to apply.  Preserve the original failure;
        # cleanup is best-effort because the failed apply may also have left
        # the population backend unable to process another change.
        remove_reference = getattr(population, "remove_usd", None)
        if callable(remove_reference):
            try:
                remove_reference(stage, handle)
                _apply_population_changes(population, stage)
            except Exception:
                pass
        raise
    return handle


def _register_presentation_root(scene: Any, runtime_root_path: str) -> None:
    register = getattr(scene, "register_presentation_root", None)
    if not callable(register):
        raise RuntimeError("OVStage scene does not track presentation roots")
    register(str(runtime_root_path))


def _unregister_presentation_root_if_absent(
    scene: Any,
    runtime_root_path: str,
) -> None:
    """Release tracking only when native population left no composed prim."""

    stage = getattr(scene, "_stage", None)
    if stage is None or _native_path_exists(stage, str(runtime_root_path)):
        return
    unregister = getattr(scene, "unregister_presentation_root", None)
    if callable(unregister):
        unregister(str(runtime_root_path))


def _native_path_exists(stage: Any, path: str) -> bool:
    value = str(path or "").rstrip("/")
    if not value.startswith("/") or value == "/":
        return value == "/"
    parent = value.rsplit("/", 1)[0]
    try:
        return value in {
            str(child) for child in stage.get_child_paths(parent or "")
        }
    except (AttributeError, KeyError, RuntimeError):
        return False


def _canonical_live_preview_path(path: Any) -> str | None:
    """Return a strict absolute prim path suitable for a native preview."""

    if not isinstance(path, str):
        return None
    value = path
    if (
        value == "/"
        or not value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or any(part in ("", ".", "..") for part in value.split("/")[1:])
    ):
        return None
    return value


def _is_presentation_path(scene: Any, path: str, runtime_root_path: str) -> bool:
    """Reject renderer-owned and other presentation-only population roots."""

    roots = {
        str(root)
        for root in getattr(scene, "presentation_root_paths", ()) or ()
        if str(root)
    }
    roots.add(str(runtime_root_path or _RUNTIME_ROOT_LOCAL_PATH))
    return any(path == root or path.startswith(f"{root}/") for root in roots)


def _coerce_live_preview_matrix(matrix: Any) -> np.ndarray | None:
    """Copy one finite, non-singular row-major 4x4 preview matrix."""

    try:
        values = np.ascontiguousarray(np.asarray(matrix, dtype=np.float64))
    except (TypeError, ValueError):
        return None
    if values.shape != (4, 4) or not bool(np.all(np.isfinite(values))):
        return None

    # Match the durable transform adapter's policy without decomposing the
    # matrix: pivot, shear, negative/nonuniform scale, and op order stay exact.
    rows = values[:3, :3].copy()
    scale = max(1.0, float(np.max(np.abs(rows))))
    tolerance = 1.0e-12 * scale
    for column in range(3):
        pivot = column + int(np.argmax(np.abs(rows[column:, column])))
        if abs(float(rows[pivot, column])) <= tolerance:
            return None
        if pivot != column:
            rows[[column, pivot]] = rows[[pivot, column]]
        pivot_value = float(rows[column, column])
        for row in range(column + 1, 3):
            factor = float(rows[row, column]) / pivot_value
            rows[row, column:] -= factor * rows[column, column:]
    return values


def _remove_runtime_layer_from_scene(
    *,
    scene: Any,
    population: Any,
    stage: Any,
    reference_handle: Any,
    runtime_root_path: str,
) -> None:
    _remove_runtime_layer(population, stage, reference_handle)
    unregister = getattr(scene, "unregister_presentation_root", None)
    if callable(unregister):
        unregister(str(runtime_root_path))


def _remove_render_settings_owner(
    *,
    scene: Any,
    population: Any,
    stage: Any,
    reference_handle: Any,
    owner_path: str,
) -> None:
    """Drop the private global-RenderSettings reference and its root."""

    if reference_handle is None or not owner_path:
        return
    _remove_runtime_layer(population, stage, reference_handle)
    unregister = getattr(scene, "unregister_presentation_root", None)
    if callable(unregister):
        unregister(str(owner_path))


def _compensate_render_settings_owner_failure(
    operation_error: BaseException,
    *,
    scene: Any,
    population: Any,
    stage: Any,
    reference_handle: Any,
    owner_path: str,
) -> None:
    try:
        _remove_render_settings_owner(
            scene=scene,
            population=population,
            stage=stage,
            reference_handle=reference_handle,
            owner_path=owner_path,
        )
    except BaseException as cleanup_error:
        add_note = getattr(operation_error, "add_note", None)
        if callable(add_note):
            add_note(
                "global render settings owner cleanup also failed: "
                f"{type(cleanup_error).__name__}: {cleanup_error}"
            )


def _compensate_runtime_layer_failure(
    operation_error: BaseException,
    *,
    scene: Any,
    population: Any,
    stage: Any,
    reference_handle: Any,
    runtime_root_path: str,
) -> None:
    try:
        _remove_runtime_layer_from_scene(
            scene=scene,
            population=population,
            stage=stage,
            reference_handle=reference_handle,
            runtime_root_path=runtime_root_path,
        )
    except BaseException as cleanup_error:
        add_note = getattr(operation_error, "add_note", None)
        if callable(add_note):
            add_note(
                "private presentation population cleanup also failed: "
                f"{type(cleanup_error).__name__}: {cleanup_error}"
            )


def _remove_runtime_layer(population: Any, stage: Any, handle: Any) -> None:
    remove_reference = getattr(population, "remove_usd", None)
    if not callable(remove_reference):
        return
    remove_reference(stage, handle)
    _apply_population_changes(population, stage)


def _query_records(stage: Any) -> dict[str, str]:
    if _uses_native_kit_query(stage):
        return {
            str(path): str(type_name or "Xform")
            for path, (type_name, _schemas) in _kit_type_records(
                stage,
                int(stage.current_ordinal),
            ).items()
        }
    result = stage.query_prims(int(stage.current_ordinal))
    records: dict[str, str] = {}
    for group in result.get("groups", ()):
        group_type_name = str(group.get("prim_type") or "Xform")
        handle = int(group.get("prim_list_handle") or 0)
        if not handle:
            continue
        for path in stage.get_prim_paths(handle):
            path_text = str(path)
            records[path_text] = (
                read_token_attribute(stage, path_text, "usd-prim-type") or group_type_name
            )
    return records


def _uses_native_kit_query(stage: Any) -> bool:
    return (
        getattr(stage, "_ovui_query_prims_source", None)
        == "native Kit query/read_attributes"
    )


def _has_light(records: dict[str, str]) -> bool:
    return any("Light" in type_name for type_name in records.values())


def _framing_camera_matrix(stage: Any, records: dict[str, str]) -> tuple[float, ...]:
    bounds = _scene_geometry_bounds(stage, records)
    if bounds is None:
        center = (0.0, 0.0, 0.0)
        radius = 1.0
    else:
        mins, maxs = bounds
        center = tuple((mins[i] + maxs[i]) * 0.5 for i in range(3))
        size = tuple(maxs[i] - mins[i] for i in range(3))
        radius = max(math.sqrt(sum(component * component for component in size)) * 0.5, 1.0)
    distance = max(radius * 4.0, 4.0)
    position = (
        center[0] + distance * 0.75,
        center[1] + distance * 0.45,
        center[2] + distance,
    )
    return _look_at_camera_matrix(position, center)


def _look_at_camera_matrix(
    position: tuple[float, float, float],
    target: tuple[float, float, float],
) -> tuple[float, ...]:
    forward = _normalize_vec3(tuple(target[i] - position[i] for i in range(3)))
    z_axis = tuple(-component for component in forward)
    world_up = (0.0, 1.0, 0.0)
    x_axis = _normalize_vec3(_cross(world_up, z_axis))
    if _length_vec3(x_axis) <= 1.0e-6:
        x_axis = (1.0, 0.0, 0.0)
    y_axis = _cross(z_axis, x_axis)
    tx, ty, tz = position
    return (
        x_axis[0],
        x_axis[1],
        x_axis[2],
        0.0,
        y_axis[0],
        y_axis[1],
        y_axis[2],
        0.0,
        z_axis[0],
        z_axis[1],
        z_axis[2],
        0.0,
        tx,
        ty,
        tz,
        1.0,
    )


def _cross(
    lhs: tuple[float, float, float],
    rhs: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        lhs[1] * rhs[2] - lhs[2] * rhs[1],
        lhs[2] * rhs[0] - lhs[0] * rhs[2],
        lhs[0] * rhs[1] - lhs[1] * rhs[0],
    )


def _length_vec3(value: tuple[float, float, float]) -> float:
    return math.sqrt(sum(component * component for component in value))


def _normalize_vec3(value: tuple[float, float, float]) -> tuple[float, float, float]:
    length = _length_vec3(value)
    if length <= 1.0e-9:
        return (0.0, 0.0, 0.0)
    return tuple(component / length for component in value)


def _scene_geometry_bounds(
    stage: Any,
    records: dict[str, str],
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    if _uses_native_kit_query(stage):
        return _scene_geometry_bounds_kit(stage, records)

    mins = [math.inf, math.inf, math.inf]
    maxs = [-math.inf, -math.inf, -math.inf]
    found = False
    for path, type_name in records.items():
        local_bounds = _local_geometry_bounds(stage, path, type_name)
        if local_bounds is None:
            continue
        matrix = _read_matrix(stage, path, "worldMatrix")
        if matrix is None:
            matrix = _read_matrix(stage, path, "localMatrix")
        for point in _bounds_corners(*local_bounds):
            world = _transform_point(point, matrix)
            for axis in range(3):
                mins[axis] = min(mins[axis], world[axis])
                maxs[axis] = max(maxs[axis], world[axis])
        found = True
    if not found:
        return None
    return (tuple(mins), tuple(maxs))


_KIT_FRAMING_ATTRIBUTE_NAMES = (
    "size",
    "radius",
    "extent",
    "omni:fabric:worldMatrix",
    "omni:fabric:localMatrix",
)


def _scene_geometry_bounds_kit(
    stage: Any,
    records: dict[str, str],
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """Frame Kit geometry from one bounded metadata read, never mesh points."""

    geometry = {
        str(path): str(type_name)
        for path, type_name in records.items()
        if str(type_name) in {"Cube", "Sphere", "Mesh"}
    }
    if not geometry:
        return None
    try:
        copied = read_paths_attribute_records(
            stage,
            tuple(geometry),
            _KIT_FRAMING_ATTRIBUTE_NAMES,
        )
    except Exception:
        return None
    mins = [math.inf, math.inf, math.inf]
    maxs = [-math.inf, -math.inf, -math.inf]
    found = False
    for path, type_name in geometry.items():
        properties = copied.get(path, {})
        local_bounds = _local_geometry_bounds_from_values(type_name, properties)
        if local_bounds is None:
            continue
        matrix = _native_record_matrix(
            properties.get("omni:fabric:worldMatrix")
        )
        if matrix is None:
            matrix = _native_record_matrix(
                properties.get("omni:fabric:localMatrix")
            )
        for point in _bounds_corners(*local_bounds):
            world = _transform_point(point, matrix)
            for axis in range(3):
                mins[axis] = min(mins[axis], world[axis])
                maxs[axis] = max(maxs[axis], world[axis])
        found = True
    if not found:
        return None
    return (tuple(mins), tuple(maxs))


def _local_geometry_bounds_from_values(
    type_name: str,
    properties: Mapping[str, Any],
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    if type_name == "Cube":
        size = _native_record_float(properties.get("size"), 1.0)
        half = size * 0.5
        bounds = ((-half, -half, -half), (half, half, half))
        return bounds if _valid_bounds(bounds) else None
    if type_name == "Sphere":
        radius = _native_record_float(properties.get("radius"), 1.0)
        bounds = ((-radius, -radius, -radius), (radius, radius, radius))
        return bounds if _valid_bounds(bounds) else None
    if type_name == "Mesh":
        extent = _native_record_float3_rows(properties.get("extent"))
        if len(extent) >= 2:
            bounds = (extent[0], extent[1])
            return bounds if _valid_bounds(bounds) else None
    return None


def _native_record_float(record: Any, fallback: float) -> float:
    dtype = tuple(getattr(record, "dtype", ()))
    if (
        len(dtype) != 3
        or int(dtype[0]) != _RS_DLPACK_FLOAT
        or int(dtype[1]) not in (32, 64)
        or int(dtype[2]) != 1
        or bool(getattr(record, "native_is_array", False))
    ):
        return float(fallback)
    try:
        value = float(getattr(record, "value"))
    except (AttributeError, TypeError, ValueError):
        return float(fallback)
    return value if math.isfinite(value) else float(fallback)


def _native_record_matrix(record: Any) -> tuple[float, ...] | None:
    dtype = tuple(getattr(record, "dtype", ()))
    if (
        len(dtype) != 3
        or int(dtype[0]) != _RS_DLPACK_FLOAT
        or int(dtype[1]) not in (32, 64)
        or int(dtype[2]) != 16
        or int(getattr(record, "semantic", 0) or 0) != 10
        or bool(getattr(record, "native_is_array", False))
    ):
        return None
    values = getattr(record, "value", None)
    matrix = _matrix_tuple_from_flat(values) if values is not None else None
    if matrix is None or not all(math.isfinite(value) for value in matrix):
        return None
    return matrix


def _native_record_float3_rows(
    record: Any,
) -> tuple[tuple[float, float, float], ...]:
    dtype = tuple(getattr(record, "dtype", ()))
    native_is_array = bool(getattr(record, "native_is_array", False))
    if (
        len(dtype) != 3
        or int(dtype[0]) != _RS_DLPACK_FLOAT
        or int(dtype[1]) not in (32, 64)
        or int(dtype[2]) not in ((3,) if native_is_array else (6,))
        or int(getattr(record, "semantic", 0) or 0) != 0
    ):
        return ()
    return _float3_rows(getattr(record, "value", None))


def _float3_rows(values: Any) -> tuple[tuple[float, float, float], ...]:
    if values is None:
        return ()
    try:
        if values and isinstance(values[0], (tuple, list)):
            rows = tuple(
                tuple(float(component) for component in row)
                for row in values
            )
        else:
            flat = tuple(float(component) for component in values)
            rows = tuple(
                flat[index:index + 3]
                for index in range(0, len(flat), 3)
            )
    except (TypeError, ValueError):
        return ()
    return tuple(row for row in rows if len(row) == 3)


def _local_geometry_bounds(
    stage: Any,
    path: str,
    type_name: str,
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    if type_name == "Cube":
        size = _read_double(stage, path, "size") or 1.0
        half = float(size) * 0.5
        bounds = ((-half, -half, -half), (half, half, half))
        return bounds if _valid_bounds(bounds) else None
    if type_name == "Sphere":
        radius = _read_double(stage, path, "radius") or 1.0
        radius = float(radius)
        bounds = ((-radius, -radius, -radius), (radius, radius, radius))
        return bounds if _valid_bounds(bounds) else None
    if type_name == "Mesh":
        extent = _read_float3_array(stage, path, "extent")
        if len(extent) >= 2:
            bounds = (extent[0], extent[1])
            if _valid_bounds(bounds):
                return bounds
        points = _read_float3_array(stage, path, "points")
        if points:
            bounds = (
                tuple(min(point[axis] for point in points) for axis in range(3)),
                tuple(max(point[axis] for point in points) for axis in range(3)),
            )
            return bounds if _valid_bounds(bounds) else None
    return None


def _valid_bounds(
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]],
) -> bool:
    values = tuple(float(component) for point in bounds for component in point)
    if not all(math.isfinite(component) for component in values):
        return False
    if any(abs(component) > 1.0e20 for component in values):
        return False
    mins, maxs = bounds
    return all(float(mins[axis]) <= float(maxs[axis]) for axis in range(3))


def _bounds_corners(
    mins: tuple[float, float, float],
    maxs: tuple[float, float, float],
) -> tuple[tuple[float, float, float], ...]:
    return tuple(
        (x, y, z)
        for x in (mins[0], maxs[0])
        for y in (mins[1], maxs[1])
        for z in (mins[2], maxs[2])
    )


def _transform_point(
    point: tuple[float, float, float],
    matrix: tuple[float, ...] | None,
) -> tuple[float, float, float]:
    if matrix is None:
        return point
    x, y, z = point
    return (
        x * matrix[0] + y * matrix[4] + z * matrix[8] + matrix[12],
        x * matrix[1] + y * matrix[5] + z * matrix[9] + matrix[13],
        x * matrix[2] + y * matrix[6] + z * matrix[10] + matrix[14],
    )


def _read_attr(stage: Any, path: str, attr_name: str) -> bytes:
    try:
        data = stage.read_attribute(int(stage.current_ordinal), [path], attr_name)
    except Exception:
        return b""
    if not isinstance(data, (bytes, bytearray)):
        return b""
    return bytes(data)


def _read_matrix(stage: Any, path: str, attr_name: str) -> tuple[float, ...] | None:
    if _uses_native_kit_query(stage):
        return read_matrix_attribute(stage, path, attr_name)
    data = _read_attr(stage, path, attr_name)
    if len(data) != 128:
        return None
    return struct.unpack("<16d", data)


def _read_float3_array(
    stage: Any,
    path: str,
    attr_name: str,
) -> tuple[tuple[float, float, float], ...]:
    if _uses_native_kit_query(stage):
        values = _read_exact_value(stage, path, attr_name)
        if values is None:
            return ()
        try:
            if values and isinstance(values[0], (tuple, list)):
                rows = tuple(
                    tuple(float(component) for component in row)
                    for row in values
                )
            else:
                flat = tuple(float(component) for component in values)
                rows = tuple(
                    flat[index:index + 3]
                    for index in range(0, len(flat), 3)
                )
        except (TypeError, ValueError):
            return ()
        return tuple(row for row in rows if len(row) == 3)
    data = _read_attr(stage, path, attr_name)
    if not data or len(data) % 12:
        return ()
    values = struct.unpack(f"<{len(data) // 4}f", data)
    return tuple((values[i], values[i + 1], values[i + 2]) for i in range(0, len(values), 3))


def _read_int_array(stage: Any, path: str, attr_name: str) -> tuple[int, ...]:
    if _uses_native_kit_query(stage):
        values = _read_exact_value(stage, path, attr_name)
        if values is None:
            return ()
        try:
            return tuple(int(value) for value in values)
        except (TypeError, ValueError):
            return ()
    data = _read_attr(stage, path, attr_name)
    if not data or len(data) % 4:
        return ()
    return tuple(int(value) for value in struct.unpack(f"<{len(data) // 4}i", data))


def _read_double_tuple(
    stage: Any,
    path: str,
    attr_name: str,
    count: int,
) -> tuple[float, ...] | None:
    if _uses_native_kit_query(stage):
        values = _read_exact_value(stage, path, attr_name)
        if values is None:
            return None
        if not isinstance(values, (tuple, list)):
            values = (values,)
        try:
            converted = tuple(float(value) for value in values)
        except (TypeError, ValueError):
            return None
        return converted if len(converted) == int(count) else None
    data = _read_attr(stage, path, attr_name)
    if len(data) != count * 8:
        return None
    return tuple(float(value) for value in struct.unpack(f"<{count}d", data))


def _read_double(stage: Any, path: str, attr_name: str) -> float | None:
    values = _read_double_tuple(stage, path, attr_name, 1)
    if values is None:
        return None
    return values[0]


def _read_float(stage: Any, path: str, attr_name: str) -> float | None:
    if _uses_native_kit_query(stage):
        value = _read_exact_value(stage, path, attr_name)
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None
    data = _read_attr(stage, path, attr_name)
    if len(data) != 4:
        return None
    return float(struct.unpack("<f", data)[0])


def _read_token(stage: Any, path: str, attr_name: str) -> str | None:
    if _uses_native_kit_query(stage):
        value = _read_exact_value(stage, path, attr_name)
        return value if isinstance(value, str) and value else None
    return read_token_attribute(stage, path, attr_name)


def _read_visibility_token(stage: Any, path: str) -> str:
    if _uses_native_kit_query(stage):
        value = _read_token(stage, path, "visibility")
        return value if value in _VISIBILITY_TOKENS else _VISIBILITY_INHERITED
    data = _read_attr(stage, path, "visibility")
    if not data:
        return _VISIBILITY_INHERITED
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    if text in _VISIBILITY_TOKENS:
        return text
    if len(data) == 8:
        try:
            resolved = resolve_token_id(stage, struct.unpack("<Q", data)[0])
        except Exception:
            resolved = ""
        if resolved in _VISIBILITY_TOKENS:
            return resolved
    return _VISIBILITY_INHERITED


def _read_exact_value(stage: Any, path: str, attr_name: str) -> Any | None:
    """Copy one exact Kit value without touching the full-stage value cache."""

    try:
        records = read_path_attribute_records(
            stage,
            str(path),
            (str(attr_name),),
        )
    except Exception:
        return None
    record = records.get(str(attr_name))
    return None if record is None else record.value


def _matrix_tuple_from_flat(values: Any) -> tuple[float, ...] | None:
    try:
        flat = tuple(float(value) for value in values)
    except (TypeError, ValueError):
        return None
    if len(flat) != 16:
        return None
    return flat


def _borrowed_path_to_scene_path(
    path: str,
    *,
    runtime_root_path: str = _RUNTIME_ROOT_LOCAL_PATH,
) -> str | None:
    value = str(path).strip()
    if not value.startswith("/"):
        return None
    root = str(runtime_root_path)
    if value == root or value.startswith(f"{root}/"):
        return None
    return value


def _view_to_ovrtx_transform(view_matrix: Any) -> np.ndarray:
    view_np = np.asarray(view_matrix, dtype=np.float64)
    if view_np.shape != (4, 4):
        raise ValueError(f"view_matrix must be 4x4, got {view_np.shape}")
    world_gl = np.linalg.inv(view_np)
    world_usd = np.ascontiguousarray(world_gl.T, dtype=np.float64)
    return world_usd.reshape(1, 4, 4)


def _coerce_matrix4(value: Any) -> np.ndarray | None:
    if value is None:
        return None
    try:
        matrix = np.asarray(value, dtype=np.float64)
    except Exception:
        return None
    if matrix.shape != (4, 4):
        return None
    return matrix


def _project_world_to_ndc(
    point: tuple[float, float, float],
    view_matrix: np.ndarray,
    proj_matrix: np.ndarray,
) -> tuple[float, float, float] | None:
    candidates = _project_world_to_ndc_candidates(point, view_matrix, proj_matrix)
    return candidates[0] if candidates else None


def _project_world_to_ndc_candidates(
    point: tuple[float, float, float],
    view_matrix: np.ndarray,
    proj_matrix: np.ndarray,
) -> list[tuple[float, float, float]]:
    try:
        world = np.asarray(
            [float(point[0]), float(point[1]), float(point[2]), 1.0],
            dtype=np.float64,
        )
    except Exception:
        return []

    clips: list[np.ndarray] = []
    for view, proj in (
        (view_matrix, proj_matrix),
        (view_matrix.T, proj_matrix.T),
    ):
        for clip in (proj @ view @ world, world @ view @ proj):
            clips.append(np.asarray(clip, dtype=np.float64))

    candidates: list[tuple[float, float, float]] = []
    seen: set[tuple[int, int, int]] = set()
    for clip in clips:
        try:
            w = float(clip[3])
        except Exception:
            continue
        if abs(w) <= 1.0e-12:
            continue
        ndc = clip[:3] / w
        if not np.all(np.isfinite(ndc)):
            continue
        key = tuple(int(round(float(value) * 1.0e6)) for value in ndc[:3])
        if key in seen:
            continue
        seen.add(key)
        candidates.append((float(ndc[0]), float(ndc[1]), float(ndc[2])))
    return candidates


def _compute_camera_intrinsics(
    proj_matrix: Any,
) -> tuple[float, float, float] | None:
    if proj_matrix is None:
        return None
    try:
        proj = np.asarray(proj_matrix, dtype=np.float64)
    except Exception:
        return None
    if proj.shape != (4, 4):
        return None
    try:
        fy = abs(float(proj[1, 1]))
        fx = abs(float(proj[0, 0]))
    except Exception:
        return None
    if fy <= 1.0e-9 or fx <= 1.0e-9:
        return None
    if _camera_projection_mode(proj) == "orthographic":
        horizontal_aperture = 20.0 / fx
        vertical_aperture = 20.0 / fy
        focal = 50.0
        return (float(focal), float(horizontal_aperture), float(vertical_aperture))
    vertical_aperture = 15.2908
    horizontal_aperture = vertical_aperture * fy / fx
    focal = 0.5 * vertical_aperture * fy
    return (float(focal), float(horizontal_aperture), float(vertical_aperture))


def _camera_projection_mode(proj_matrix: Any) -> str | None:
    if proj_matrix is None:
        return None
    try:
        proj = np.asarray(proj_matrix, dtype=np.float64)
    except Exception:
        return None
    if proj.shape != (4, 4):
        return None
    if np.isclose(proj[3, 3], 1.0) and np.isclose(proj[3, 2], 0.0):
        return "orthographic"
    if np.isclose(proj[3, 3], 0.0) and np.isclose(proj[3, 2], -1.0):
        return "perspective"
    return None


def _normalize_rgba(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    rgba = np.asarray(arr)
    if rgba.dtype != np.uint8:
        rgba = rgba.astype(np.uint8, copy=False)
    if rgba.ndim != 3:
        return np.zeros((height, width, 4), dtype=np.uint8)
    if rgba.shape[2] == 3:
        alpha = np.full((rgba.shape[0], rgba.shape[1], 1), 255, dtype=np.uint8)
        rgba = np.concatenate([rgba, alpha], axis=2)
    elif rgba.shape[2] != 4:
        return np.zeros((height, width, 4), dtype=np.uint8)
    if rgba.shape[0] == height and rgba.shape[1] == width:
        return np.ascontiguousarray(rgba)
    y_idx = np.linspace(0, rgba.shape[0] - 1, height).astype(np.int64)
    x_idx = np.linspace(0, rgba.shape[1] - 1, width).astype(np.int64)
    return np.ascontiguousarray(rgba[y_idx][:, x_idx])


def _format_matrix(values: tuple[float, ...]) -> str:
    rows = []
    for i in range(0, 16, 4):
        rows.append("(" + ", ".join(_format_float(v) for v in values[i : i + 4]) + ")")
    return "( " + ", ".join(rows) + " )"


def _format_float(value: float) -> str:
    return format(float(value), ".9g")
