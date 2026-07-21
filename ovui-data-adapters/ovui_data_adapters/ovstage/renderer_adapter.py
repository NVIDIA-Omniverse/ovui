# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovrtx renderer adapter for the registered ovstage provider."""

from __future__ import annotations

import math
import os
import struct
import subprocess
import sys
import time
from collections import deque
from collections.abc import Mapping
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Deque, List, Optional

import numpy as np
from ovui_data_adapters.common import (
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
    RendererAdapter,
    RenderSettingApplyResult,
    RenderSettingResetResult,
    RenderSettingsCatalog,
    RenderSettingValidationResult,
    RenderSettingValueState,
    RenderTargetActivationResult,
    RenderVarOutputCatalog,
    RenderVarOutputDescriptor,
    RenderVarOutputFrame,
    RenderVarOutputKind,
    RenderVarOutputRequest,
    RenderVarOutputRequestResult,
    RenderVarPresetKind,
    RenderVarVisualizationPreset,
    RenderVarProbeRequest,
    RenderVarProbeResult,
    RenderVarWarning,
    Vec3f,
    ZeroCopyState,
    omniui_headless_enabled,
)
from ovui_data_adapters.common._ldr_overlap import (
    CameraSnapshot,
    LdrOverlapState,
    camera_state_differs,
)
from ovui_data_adapters.common.ovrtx_import import import_ovrtx
from ovui_data_adapters.ovstage._catalog import native_catalog_snapshot
from ovui_data_adapters.ovstage._errors import raise_not_ready
from ovui_data_adapters.ovstage._native import read_token_attribute, resolve_token_id
from ovui_data_adapters.ovstage._scene import (
    _load_population_module,
)
from ovui_data_adapters.ovstage._stage_write import StageWriteBatch
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
_OVRTX_XFORM_ATTR = "omni:xform"
_DEFAULT_RESOLUTION = (1280, 720)
_MIN_DT = 1.0 / 300.0
_MAX_DT = 0.1
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


def _borrow_renderer_config(ovrtx: Any) -> Any:
    attach_mode_type = getattr(ovrtx, "AttachMode", None)
    borrow_mode = getattr(attach_mode_type, "BORROW", None)
    config_kwargs = {
        "keep_system_alive": True,
        "log_level": "info",
        "use_vulkan": True,
        "selection_outline_enabled": True,
        "selection_outline_width": 2,
    }
    if borrow_mode is not None:
        config_kwargs["attach_mode"] = borrow_mode
    try:
        return ovrtx.RendererConfig(**config_kwargs)
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


class OvstageRendererAdapter(RendererAdapter):
    """OVRTX presentation adapter borrowing an OVStage-owned scene."""

    def __init__(
        self,
        scene: Any | None = None,
        undo_manager: Any | None = None,
    ) -> None:
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
        self._attached_stage: Any = None
        self._runtime_reference_handle: Any = None
        self._runtime_population: Any = None
        self._path_dictionary: Any = None
        self._runtime_root_path = _RUNTIME_ROOT_LOCAL_PATH
        self._runtime_camera_local_path = _RENDER_CAMERA_LOCAL_PATH
        self._runtime_render_product_path = _RENDER_PRODUCT_LOCAL_PATH
        self._render_product_path = _RENDER_PRODUCT_LOCAL_PATH
        self._default_render_product_path = self._render_product_path
        self._active_render_product_common_path: str | None = None
        self._camera_path: str | None = _RENDER_CAMERA_LOCAL_PATH
        self._active_camera_common_path: str | None = None
        self._last_resolution = _DEFAULT_RESOLUTION
        self._last_render_product_resolution = _DEFAULT_RESOLUTION
        self._dt_clock = time.monotonic()
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
        self._selection_outline_styles_configured = False
        self._selection_outline_style_calls = 0
        # Data-plane attribute writes (the legacy outline mechanism removed in
        # ovrtx 0.4). The native OVStage adapter NEVER performs them — this
        # counter is the BORROW invariant witness and must stay zero.
        self._selection_outline_attribute_writes = 0
        # The outline render pass does not pick up per-prim membership in this
        # app's attached-renderer state until one renderer.reset() runs after
        # membership exists (verified live against ovrtx 0.4; standalone
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
        self._release_retained_output()
        records = _query_records(ovstage)
        runtime_root_path = _select_runtime_root_path(scene)
        runtime_layer = _build_runtime_layer(
            ovstage,
            resolution=_DEFAULT_RESOLUTION,
            records=records,
            runtime_root_path=runtime_root_path,
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
        try:
            path_dictionary = import_module("ovstage").PathDictionary(ovstage)
        except Exception as exc:
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
        self._live_transform_adapter = OvstageTransformAdapter(scene)
        self._live_preview_paths.clear()
        self._runtime_population = population
        self._runtime_reference_handle = reference_handle
        self._path_dictionary = path_dictionary
        self._runtime_root_path = runtime_layer.root_path
        self._runtime_camera_local_path = runtime_layer.camera_path
        self._runtime_render_product_path = runtime_layer.render_product_path
        self._camera_path = runtime_layer.camera_path
        self._active_camera_common_path = None
        self._render_product_path = runtime_layer.render_product_path
        self._default_render_product_path = self._render_product_path
        self._active_render_product_common_path = None
        self._last_resolution = _DEFAULT_RESOLUTION
        self._last_render_product_resolution = _DEFAULT_RESOLUTION
        self._dt_clock = time.monotonic()
        self._last_load_from_scene_context = True
        # Membership tracked from a scene whose detach-time clear failed is
        # still present in the renderer and must not leak onto same-named
        # prims here: retry the clear now that a scene is attached again.
        # On another failure the paths STAY tracked — the next selection
        # sync's clear delta keeps retrying — rather than being dropped
        # while the renderer still outlines them.
        stale_outline = sorted(self._selection_outline_previous_paths)
        if stale_outline and self._write_selection_outline_group(
            stale_outline, _SELECTION_OUTLINE_CLEAR_GROUP_ID
        ):
            self._selection_outline_previous_paths.clear()
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
        self._activate_windowed_livestream()
        print(
            "[OvstageRendererAdapter] load_stage source=ovstage_scene_context "
            "renderer=ovrtx attach_mode=borrow "
            f"render_product={self._render_product_path}",
            file=sys.stderr,
        )

    def _release_retained_output(self) -> None:
        """Release the retained step result and presentation cache.

        MUST run immediately before every ownership-invalidating native
        mutation (OVStage attach/detach, renderer reset, teardown), after
        any cheap early-return guard of the enclosing boundary function.
        An ovrtx step-result container holds native output handles; letting
        one live across a native mutation is undefined. Idempotent and cheap
        when nothing is retained.
        """
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

    def render_frame(
        self,
        width: int,
        height: int,
        view_matrix: Matrix4d,
        proj_matrix: Matrix4d,
    ) -> Any | GpuFrameHandle:
        width = max(int(width), 1)
        height = max(int(height), 1)
        if self._attached_stage is None:
            return np.zeros((height, width, 4), dtype=np.uint8)
        self._apply_resolution(width, height)
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
        self._push_view_camera_state(view_matrix, proj_matrix)
        now = time.monotonic()
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
            return np.zeros((height, width, 4), dtype=np.uint8)
        self._dispatch_pending_pick_results(products)
        self._extract_requested_point_cloud_frames(products)
        self._extract_requested_render_var_output_frames(products)
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
            output = self._extract_ldr_color(products, width, height)
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
                lambda retained: self._extract_ldr_color(
                    retained, width, height
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
            with scene.change_stream.suppress_notifications():
                ovstage = import_module("ovstage")
                with StageWriteBatch(stage, [normalized_path]) as batch:
                    batch.write_fixed(
                        _OVRTX_XFORM_ATTR,
                        values,
                        lanes=16,
                        semantic=ovstage.AttributeSemantic.MATRIX,
                    )
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
        self._render_product_path = render_product_path
        self._active_render_product_common_path = common_path
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
        accepted = self.set_active_render_product_path(normalized_path)
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
                        revision_token=_native_catalog_revision(snapshot),
                        metadata={
                            "source_path": var_path,
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

    def list_render_settings(
        self,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingsCatalog:
        """Return an empty catalog until native setting discovery is implemented."""

        active_path = str(render_product_path or self.get_active_render_product_path() or "")
        return RenderSettingsCatalog(active_render_product_path=active_path)

    def read_render_setting(
        self,
        setting_id: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingValueState | None:
        del setting_id, render_product_path
        return None

    def subscribe_render_settings_changes(
        self,
        callback: Callable[[], None],
    ) -> _RenderSettingsSubscription:
        """Refresh settings views after apply, reset, undo, or redo."""

        subscribers = getattr(self, "_render_settings_subscribers", None)
        if not isinstance(subscribers, list):
            subscribers = []
            self._render_settings_subscribers = subscribers
        if callable(callback) and callback not in subscribers:
            subscribers.append(callback)

        def cancel() -> None:
            active = getattr(self, "_render_settings_subscribers", None)
            if isinstance(active, list) and callback in active:
                active.remove(callback)

        return _RenderSettingsSubscription(cancel)

    def _notify_render_settings_changed(self) -> None:
        for callback in tuple(
            getattr(self, "_render_settings_subscribers", ()) or ()
        ):
            try:
                callback()
            except Exception:
                # Subscriptions are disposable UI observers; a stale view must
                # not invalidate an already accepted native state transition.
                continue

    def validate_render_setting(
        self,
        setting_id: str,
        value: Any,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingValidationResult:
        del value, render_product_path
        return RenderSettingValidationResult.rejected_result(
            "Native OVStage render-setting authoring is not available yet.",
            setting_id=setting_id,
            warning_code="unsupported",
        )

    def apply_render_setting(
        self,
        setting_id: str,
        value: Any,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingApplyResult:
        """Reject until OVStage-native render-setting authoring is available."""

        validation = self.validate_render_setting(
            setting_id,
            value,
            render_product_path=render_product_path,
        )
        if not validation.accepted:
            return RenderSettingApplyResult.rejected_result(
                validation.message or "Render setting validation failed.",
                setting_id=validation.setting_id or setting_id,
                warning_code=validation.warning_code or "validation_failed",
            )
        return RenderSettingApplyResult.rejected_result(
            validation.message or "Native OVStage render-setting authoring is unavailable.",
            setting_id=validation.setting_id or setting_id,
            warning_code=validation.warning_code or "unsupported",
        )

    def reset_render_setting(
        self,
        setting_id: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingResetResult:
        del render_product_path
        return RenderSettingResetResult.rejected_result(
            "Native OVStage render-setting reset is not available yet.",
            setting_id=setting_id,
            warning_code="unsupported",
        )

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
            timestamp=time.monotonic(),
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
            timestamp=time.monotonic(),
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

    def _push_view_camera_state(self, view_matrix: Any, proj_matrix: Any) -> None:
        stage = self._attached_stage
        camera_path = self._runtime_camera_path()
        if stage is None or camera_path is None or view_matrix is None:
            return
        try:
            ovstage = import_module("ovstage")
            matrix_semantic = ovstage.AttributeSemantic.MATRIX
            world_tensor = _view_to_ovrtx_transform(view_matrix).reshape(-1)
            intrinsics = _compute_camera_intrinsics(proj_matrix)
            camera_state = (camera_path, world_tensor.tobytes(), intrinsics)
            if camera_state == self._last_pushed_camera_state:
                return
            with StageWriteBatch(stage, [camera_path]) as batch:
                batch.write_fixed(
                    _OVRTX_XFORM_ATTR,
                    world_tensor,
                    lanes=16,
                    semantic=matrix_semantic,
                )
                if intrinsics is not None:
                    focal, h_aperture, v_aperture = intrinsics
                    for attr_name, value in (
                        ("focalLength", focal),
                        ("horizontalAperture", h_aperture),
                        ("verticalAperture", v_aperture),
                    ):
                        batch.write_fixed(
                            attr_name,
                            np.asarray([value], dtype=np.float32),
                        )
            self._last_pushed_camera_state = camera_state
        except Exception as exc:
            if _require_real_ovrtx():
                raise RuntimeError("OVStage camera write failed") from exc

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
        try:
            left, top, right, bottom = self._ndc_rect_to_pick_pixels(x, y, x, y)
            renderer.enqueue_pick_query(
                self._render_product_path,
                *self._pick_pixels_to_query_rect(left, top, right, bottom),
            )
        except Exception:
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
        try:
            left, top, right, bottom = self._ndc_rect_to_pick_pixels(x0, y0, x1, y1)
            renderer.enqueue_pick_query(
                self._render_product_path,
                *self._pick_pixels_to_query_rect(left, top, right, bottom),
            )
        except Exception:
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
        renderer API, which is renderer-owned presentation state (it never
        writes the borrowed OVStage), so it is allowed in BORROW mode — the
        historical prohibition here covered only attribute writes into the
        owner's data plane.  Bookkeeping advances only after a write
        succeeds, so a transient failure leaves the affected paths
        retryable on the next selection sync.  Runtimes without the API
        degrade honestly: selection still synchronizes, no outline appears.
        """
        selected = list(dict.fromkeys(str(path) for path in (paths or []) if path))
        self._selected_paths = selected
        self._configure_selection_outline_styles()

        previous = set(self._selection_outline_previous_paths)
        current = set(selected)
        to_clear = sorted(previous - current)
        to_set = [path for path in selected if path not in previous]
        if to_clear and self._write_selection_outline_group(
            to_clear, _SELECTION_OUTLINE_CLEAR_GROUP_ID
        ):
            self._selection_outline_previous_paths.difference_update(to_clear)
        if to_set and self._write_selection_outline_group(
            to_set, _SELECTION_OUTLINE_GROUP_ID
        ):
            self._selection_outline_previous_paths.update(to_set)
        if current & self._selection_outline_previous_paths:
            # Applied membership that is currently DESIRED exists (fresh
            # writes or membership carried over a scene transition) — the
            # pass activation must cover both.  Stale paths awaiting a
            # failed clear's retry never trigger activation.
            self._ensure_selection_outline_pass_active()

    def shutdown(self) -> None:
        # Ownership: a retained step-result container must never outlive the
        # native renderer handle (dropping ``_renderer`` below is the LAST
        # reference and triggers native teardown).
        self._release_retained_output()
        self._dispatch_pending_pick_misses()
        # Detach first. A provider replacement can fail here and retain the
        # current scene for a safe retry; its active process-global stream must
        # remain usable in that case. Once detach succeeds, closing this old
        # tap is safe and must precede activation of the replacement tap.
        self._remove_scene()
        livestream = getattr(self, "_livestream", None)
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
        # Outline membership is renderer state keyed by prim path and would
        # survive the detach; clear it so a later scene with same-named
        # prims does not inherit a stale outline.  Transactional: the
        # tracked set advances ONLY when the clear write succeeds, and a
        # failed detach below restores the cleared membership in-place (the
        # scene is still attached and its outline must not need an external
        # selection resync).  A clear failure followed by a successful
        # detach keeps the stale paths tracked for retry at the next
        # load_stage / selection sync instead of silently leaking them.
        outlined_paths = getattr(self, "_selection_outline_previous_paths", None)
        cleared_for_detach: list[str] = []
        if outlined_paths:
            candidate_paths = sorted(outlined_paths)
            if self._write_selection_outline_group(
                candidate_paths, _SELECTION_OUTLINE_CLEAR_GROUP_ID
            ):
                outlined_paths.clear()
                cleared_for_detach = candidate_paths
        scene = self._scene
        population = self._runtime_population
        reference_handle = self._runtime_reference_handle
        path_dictionary = self._path_dictionary
        runtime_root_path = str(
            getattr(self, "_runtime_root_path", _RUNTIME_ROOT_LOCAL_PATH)
        )

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
            if cleared_for_detach and self._write_selection_outline_group(
                cleared_for_detach, _SELECTION_OUTLINE_GROUP_ID
            ):
                outlined_paths.update(cleared_for_detach)
            raise
        self._attached_stage = None
        self._runtime_population = None
        self._runtime_reference_handle = None
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
    ) -> bool:
        """Write outline-group membership for ``paths``; return success.

        Completion must be consumed and validated before reporting success:
        an abandoned ovrtx ``Operation`` blocks inside ``__del__`` with a
        ResourceWarning and swallows completion errors there, and an
        unvalidated completion value would advance the outline bookkeeping
        for a write that never applied.  The blocking string variant is
        ovrtx's own ``_async(...).wait()`` wrapper, so completion failures
        surface as exceptions and keep paths retryable.
        """
        renderer = getattr(self, "_renderer", None)
        if renderer is None or not paths:
            return False
        group_setter = getattr(
            renderer, "set_selection_outline_group_strings", None
        )
        if callable(group_setter):
            try:
                group_setter(list(paths), int(group_id))
            except Exception:
                return False
            return True
        async_group_setter = getattr(
            renderer, "set_selection_outline_group_strings_async", None
        )
        if callable(async_group_setter):
            try:
                operation = async_group_setter(list(paths), int(group_id))
                wait = getattr(operation, "wait", None)
                if not callable(wait):
                    # A completion that cannot be awaited is unverifiable;
                    # counting it as success would cache an unconfirmed
                    # write as applied and never retry it.
                    return False
                # ``wait()`` blocks until the renderer resolves the
                # operation and raises on completion failure; a ``None``
                # (timeout-shaped) result is never treated as applied.
                completed = wait()
            except Exception:
                return False
            return completed is not None
        return False

    def _ensure_selection_outline_pass_active(self) -> None:
        """One guarded renderer.reset() after outline membership first exists.

        Called only while successful membership is applied.  A missing or
        failing ``reset`` leaves the flag ARMED — disarming without a reset
        would claim an activation that never happened — so the next
        successful membership write retries it.
        """
        if not getattr(self, "_selection_outline_pass_needs_reset", False):
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
            try:
                callback(point_path, point_world)
            except Exception:
                pass
            return
        rect_paths = list(dict.fromkeys(path for path, _point in effective_hits if path))
        self._last_pick_path = rect_paths[0] if len(rect_paths) == 1 else None
        self._last_pick_paths = tuple(rect_paths)
        self._last_pick_world_point = None
        if callback is None:
            return
        try:
            callback(rect_paths)
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
            try:
                if kind == "point":
                    callback(None, None)
                else:
                    callback([])
            except Exception:
                pass

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
            product = products[self._render_product_path]
            frame = product.frames[0]
            rv = frame.render_vars[_LDR_VAR_NAME]
        except Exception as exc:
            if _require_real_ovrtx():
                raise RuntimeError("ovrtx render output map failed") from exc
            return np.zeros((height, width, 4), dtype=np.uint8)

        state = getattr(self, "_zero_copy_state", None)
        livestream = getattr(self, "_livestream", None)
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
                tensor = mapping.tensor
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
                    tensor = mapping.tensor
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
                with rv.map(device=self._ovrtx.Device.CPU) as mapping:
                    arr = np.array(np.from_dlpack(mapping), copy=True)
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
                    raise RuntimeError("ovrtx render output map failed") from exc
                return np.zeros((height, width, 4), dtype=np.uint8)

        frame = _normalize_rgba(arr, width, height)
        if _require_real_ovrtx() and _rgba_frame_is_black(frame):
            raise RuntimeError("ovrtx render output is empty")
        return frame


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
        '            def Camera "Main" (',
        "                prepend apiSchemas = [",
        '                    "OmniRtxCameraAutoExposureAPI_1",',
        '                    "OmniRtxCameraExposureAPI_1"',
        "                ]",
        "            )",
        "            {",
        "                float exposure:responsivity = 1.1026709",
        "                float exposure:time = 0.02",
        "                bool omni:rtx:autoExposure:enabled = 1",
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
    data = _read_attr(stage, path, attr_name)
    if len(data) != 128:
        return None
    return struct.unpack("<16d", data)


def _read_float3_array(
    stage: Any,
    path: str,
    attr_name: str,
) -> tuple[tuple[float, float, float], ...]:
    data = _read_attr(stage, path, attr_name)
    if not data or len(data) % 12:
        return ()
    values = struct.unpack(f"<{len(data) // 4}f", data)
    return tuple((values[i], values[i + 1], values[i + 2]) for i in range(0, len(values), 3))


def _read_int_array(stage: Any, path: str, attr_name: str) -> tuple[int, ...]:
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
    data = _read_attr(stage, path, attr_name)
    if len(data) != 4:
        return None
    return float(struct.unpack("<f", data)[0])


def _read_token(stage: Any, path: str, attr_name: str) -> str | None:
    return read_token_attribute(stage, path, attr_name)


def _read_visibility_token(stage: Any, path: str) -> str:
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
    vertical_aperture = 15.2908
    horizontal_aperture = vertical_aperture * fy / fx
    focal = 0.5 * vertical_aperture * fy
    return (float(focal), float(horizontal_aperture), float(vertical_aperture))


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
