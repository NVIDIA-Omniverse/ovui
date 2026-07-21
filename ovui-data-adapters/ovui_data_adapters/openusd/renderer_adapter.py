# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OvRtxRendererAdapter — RendererAdapter backed by the ovrtx GPU renderer.

ovrtx loads USD scenes into its own internal representation (Fabric)
via :meth:`ovrtx.Renderer.open_usd` /
:meth:`add_usd_reference_from_string`. Subsequent pxr edits to the
source stage are NOT visible to ovrtx unless we push them explicitly
through :meth:`write_attribute`. This adapter maintains
two views of the camera and render product:

* **pxr session layer** — authored by Step A.1 helpers so the Stage
  Browser / Property Inspector / other OvGear-internal consumers see a
  consistent scene graph.
* **ovrtx internal stage** — a separate inline USDA layer
  (``_build_session_usda``) composed into ovrtx alongside the user's
  root layer. The canonical transform attribute there is ``omni:xform``
  (Fabric convention, USD row-vector form).

Per frame, :meth:`render_frame` mirrors the live camera transform and
intrinsics into ovrtx via :meth:`renderer.write_attribute`; it does not
mutate the pxr session layer for free-camera motion. See the viewport behavior
"""

from __future__ import annotations

import os

# ``OVRTX_SKIP_USD_CHECK`` must be set BEFORE the first ``import ovrtx``
# (which is deferred to :func:`_probe_ovrtx` below). Setting it at
# module load is safe regardless of whether ovrtx ever gets imported.
os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")

import collections
import math
import re
import struct
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, List, Optional, Tuple

# RFC 3986 URI scheme prefix (used by ``_anchor_asset_path`` to keep
# URI/resolver identifiers byte-for-byte when relocating a live-root
# snapshot). Matches Ar's own scheme classification.
_ASSET_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

import numpy as np
from ovui_data_adapters.common import (
    ChangeEventType,
    GpuFrame,
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
    RenderVarCategoricalSettings,
    RenderVarHdrSettings,
    RenderVarOutputCatalog,
    RenderVarOutputDescriptor,
    RenderVarOutputFrame,
    RenderVarOutputKind,
    RenderVarOutputRequest,
    RenderVarOutputRequestResult,
    RenderVarPresetKind,
    RenderVarScalarRangeSettings,
    RenderVarVectorSettings,
    RenderVarVisualizationPreset,
    RenderVarWarning,
    RenderSettingApplyResult,
    RenderSettingDescriptor,
    RenderSettingRequirement,
    RenderSettingResetResult,
    RenderSettingValidationResult,
    RenderSettingValueConstraints,
    RenderSettingValueState,
    RenderSettingValueType,
    RenderSettingVisibility,
    RenderSettingWarning,
    RenderSettingsCatalog,
    RenderSettingsGroupDescriptor,
    RenderSettingsProviderDescriptor,
    RendererAdapter,
    RenderTargetActivationResult,
    ZeroCopyState,
)
from ovui_data_adapters.common.ovrtx_import import (
    OVRTX_BIN_DIR_ENV as _OVRTX_BIN_DIR_ENV,
    OVRTX_ROOT_ENV as _OVRTX_ROOT_ENV,
    import_ovrtx,
)
from ovui_data_adapters.common._ldr_overlap import (
    CameraSnapshot,
    LdrOverlapState,
    camera_state_differs,
)

# ── Note on carb's ``omni.hydra`` re-registration warning ──
# ovrtx's bundled carb prints the line
#
#   [Warning] [omni.log] Source: omni.hydra was already registered.
#
# to fd 1 (stdout) once per process shortly after
# :class:`ovrtx.Renderer` construction. It fires because ovui's
# libraries, loaded earlier in the same process, have already
# registered the ``omni.hydra`` log source — carb keeps the first
# handler and emits a WARN for the second. The registration is a
# no-op and the warning is safe to ignore. The write is asynchronous
# from a carb worker thread, and carb appears to cache its own dup of
# fd 1 at ``import ovrtx`` time, so a Python-side stdout redirect set
# up in :class:`OvRtxRendererAdapter.__init__` does not catch it.
# Suppressing it from Python would require an ``LD_PRELOAD`` shim or
# carb-side configuration we do not control. Documented here so the
# noise does not get mistaken for a real failure and so future
# maintainers do not chase another filter implementation.

# ``ovrtx`` ships its own USD libraries bundled into the shared object.
# Importing ``ovrtx`` BEFORE ``pxr`` in the same process triggers a
# ``multiple debug symbol definitions for 'SDF_ASSET'`` abort when pxr
# later initializes. The fix is to defer ``import ovrtx`` until first
# adapter construction — by then, anything that needed pxr has already
# loaded it, so the bundled libusd composes cleanly on top.
#
# Symmetric trap on the other side: once ``pxr.Usd.Stage.Open`` has run,
# ovrtx's bundled USD plugin can no longer read ``bin/mdl/Default.mdl``
# via its file datasource (``FileDatasourceInputStream failed to open`` →
# ``C100 "mdl" expected`` → ``Failed to create HydraEngine``). The
# ``mdl::Default`` module ends up missing, materials fail to resolve, and
# ``step()`` returns a black frame. Constructing the ``ovrtx.Renderer``
# BEFORE the first ``Usd.Stage.Open`` primes ovrtx's MDL cache and
# sidesteps the conflict, so callers must pre-build the adapter before
# opening any stage in the same process. :meth:`Application.open_file`
# enforces this ordering for the user-facing USD-open path.
_ovrtx: Any = None
_OVRTX_IMPORT_ERROR: Optional[BaseException] = None
_OVRTX_PROBED: bool = False


def _probe_ovrtx() -> bool:
    """Import ovrtx lazily; cache the outcome; return availability.

    Safe to call repeatedly — the underlying ``import ovrtx`` runs at
    most once per process.
    """
    global _ovrtx, _OVRTX_IMPORT_ERROR, _OVRTX_PROBED
    if _OVRTX_PROBED:
        return _ovrtx is not None
    _OVRTX_PROBED = True
    result = import_ovrtx()
    _ovrtx = result.module
    _OVRTX_IMPORT_ERROR = result.error
    return _ovrtx is not None


def _version_tuple(value: Any) -> tuple[int, ...] | str:
    parts: list[int] = []
    for part in str(value).split("."):
        try:
            parts.append(int(part))
        except ValueError:
            return str(value)
    return tuple(parts) if parts else str(value)


class _LazyAvailable:
    """Proxy whose ``bool()`` triggers the one-shot ovrtx import probe.

    Not a Python descriptor — just an object with ``__bool__`` so code
    that reads ``AVAILABLE`` as a flag defers the heavy ovrtx import
    until it's actually needed. Tests and :class:`Application` can
    inspect the flag before any adapter construction without triggering
    the pxr load-order trap.
    """

    def __repr__(self) -> str:  # pragma: no cover — cosmetic
        return f"<AVAILABLE lazy={_probe_ovrtx()}>"

    def __bool__(self) -> bool:
        return _probe_ovrtx()


#: Evaluates to ``True`` iff ``ovrtx`` can be imported cleanly.
#: The probe runs on first truthiness check; repeated reads are cached.
AVAILABLE = _LazyAvailable()


# ── Session prim paths ──
# All OvGear-owned prims live under ``/OvGearSession`` so they do not
# collide with paths the user's scene may already use (``/Render``,
# ``/World``, cameras at root, etc.). The pxr session-layer helpers
# (Step A.1) default to the same paths.
_CAMERA_PATH = "/OvGearSession/Cameras/Main"
_RENDER_PRODUCT_PATH = "/OvGearSession/Render/Viewport"
_LDR_VAR_PATH = "/OvGearSession/Render/Vars/LdrColor"
_DOME_LIGHT_PATH = "/OvGearSession/Lights/FallbackDome"
_SESSION_ROOT_PATH = "/OvGearSession"

_DEFAULT_RESOLUTION: Tuple[int, int] = (1280, 720)
_LDR_VAR_NAME = "LdrColor"
_PICK_RENDER_PRODUCT_DEVICE_IDS: Tuple[int, ...] = (0,)

# delta_time clamp for ovrtx.step — protects sensors from huge gaps
# when the frame loop stalls (e.g., first-frame shader compile).
_MIN_DT = 1.0 / 300.0
_MAX_DT = 0.1

# Resize debounce tuning (the viewport behavior). The plan defines a big
# delta as the strict inequality ``|new - last| > _RESIZE_BIG_DELTA_PX``,
# so ``_RESIZE_BIG_DELTA_PX`` is the *exclusive* threshold (an 8 px change
# is NOT big; 9 px IS). When two such deltas land within
# ``_RESIZE_ACTIVE_WINDOW_S`` of each other we consider the viewport to be
# in an active drag-resize and throttle RenderProduct reinjects to one per
# ``_RESIZE_DEBOUNCE_S``. Between drags (or for a single isolated jump)
# the new resolution is applied immediately.
_RESIZE_BIG_DELTA_PX = 8
_RESIZE_ACTIVE_WINDOW_S = 0.200
_RESIZE_DEBOUNCE_S = 0.250

_SELECTION_OUTLINE_GROUP_ID = 1
_SELECTION_OUTLINE_CLEAR_GROUP_ID = 0
_SELECTION_OUTLINE_ATTR = "omni:selectionOutlineGroup"
_SELECTION_OUTLINE_COLOR = (0.0, 138.0 / 255.0, 249.0 / 255.0, 1.0)
_SELECTION_OUTLINE_FILL = (0.0, 138.0 / 255.0, 249.0 / 255.0, 0.0)
_PICK_CANCEL_EXPLICIT = "explicit"
_PICK_CANCEL_REPLACED = "replaced"

_PICK_HIT_VAR = "ovrtx_pick_hit"
_PICK_HIT_BUFFER_MAGIC = 0x56505448
_PICK_HIT_BUFFER_VERSION = 1
_PICK_HIT_HEADER = struct.Struct("<IIII")
_PICK_HIT_RECORD = struct.Struct("<QIIQdddffff")
_ROOT_STAGE_SENTINEL = object()
_SESSION_INSTALL_SENTINEL = object()
_ROLLBACK_NATIVE_SENTINEL = object()


@dataclass
class NativeCleanupDiagnostic:
    """Bounded, identity-preserving account of one unresolved native owner.

    The adapter owns these records while cleanup is retryable.  Throwable
    objects live here rather than on one another, so callers can inspect the
    exact operation/cleanup objects without constructing exception cycles.
    """

    owner: str
    handle: Any
    snapshot: Optional[str]
    origin: str
    primary: BaseException
    errors: list[BaseException] = field(default_factory=list)
    failure_count: int = 0
    dropped_error_count: int = 0

    @property
    def first_error(self) -> BaseException:
        return self.errors[0]

    @property
    def latest_error(self) -> BaseException:
        return self.errors[-1]

    def retain(self, error: BaseException) -> None:
        self.failure_count += 1
        if len(self.errors) >= 16:
            # Preserve the first fault and the most recent bounded history.
            del self.errors[1]
            self.dropped_error_count += 1
        self.errors.append(error)


@dataclass
class ThrowableRelationship:
    """Bounded secondary throwables retained for an exact primary object."""

    primary: BaseException
    secondaries: list[BaseException] = field(default_factory=list)
    secondary_count: int = 0
    dropped_secondary_count: int = 0

    def retain(self, secondary: BaseException) -> None:
        self.secondary_count += 1
        if len(self.secondaries) >= 16:
            del self.secondaries[0]
            self.dropped_secondary_count += 1
        self.secondaries.append(secondary)


@dataclass
class _NativeCleanupObligation:
    owner: str
    handle: Any
    snapshot: Optional[str]
    origin: str
    diagnostic: NativeCleanupDiagnostic


@dataclass
class _NativeRestoreObligation:
    primary: BaseException
    need_root: bool
    need_session: bool
    need_overlays: bool
    prospective_snapshot: Optional[str]
    diagnostic: NativeCleanupDiagnostic

_POINT_CLOUD_SOURCE_TOKEN = "pointcloud"
_POINT_CLOUD_SOURCE_ATTRS: Tuple[str, ...] = (
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
        Optional[Tuple[float, float]],
        str,
        Tuple[PointCloudColorMode, ...],
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


# strata#17 livestream env-flag check. Inlined here (rather than imported
# from ``_livestream_tap``) so the default-off path does NOT pull
# ``_livestream_tap`` into ``sys.modules`` (Codex blocker 5). Must stay
# in sync with the source-of-truth in ``_livestream_tap._enabled``.
_LIVESTREAM_ENV_VAR = "OVGEAR_LIVESTREAM"


def _livestream_env_enabled() -> bool:
    return os.environ.get(_LIVESTREAM_ENV_VAR, "").strip().lower() in (
        "1", "true", "yes",
    )


# Depth-one LdrColor overlap (see ``_ldr_overlap``). On by default; set
# OVGEAR_LDR_OVERLAP=0 to restore the fully synchronous consume path.
_LDR_OVERLAP_ENV_VAR = "OVGEAR_LDR_OVERLAP"


def _ldr_overlap_env_enabled() -> bool:
    return os.environ.get(_LDR_OVERLAP_ENV_VAR, "1").strip().lower() not in (
        "0", "false", "no",
    )


def _normalize_active_prim_path(path: Optional[str], fallback: str) -> Optional[str]:
    """Normalize a selector path or return ``None`` for obvious non-prim paths."""
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
    try:
        from pxr import Sdf
        sdf_path = Sdf.Path(path_str)
        if not sdf_path.IsAbsolutePath() or not sdf_path.IsPrimPath():
            return None
        return str(sdf_path)
    except Exception:
        # Keep this helper usable in import-isolation tests where pxr is not
        # installed; the string checks above still reject common non-prim paths.
        if "." in path_str:
            return None
    return path_str


def _source_token_key(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _render_var_warning(code: str, message: str) -> RenderVarWarning:
    return RenderVarWarning(code=code, message=message)


def _render_var_ordered_var_targets(product: Any) -> list[Any]:
    try:
        return list(product.GetOrderedVarsRel().GetTargets())
    except Exception:
        return []


def _render_var_resolution(product: Any) -> tuple[int, int] | None:
    try:
        value = product.GetResolutionAttr().Get()
    except Exception:
        value = None
    if value is None:
        return None
    try:
        return (max(0, int(value[0])), max(0, int(value[1])))
    except Exception:
        return None


def _render_var_shape(
    resolution: tuple[int, int] | None,
    component_count: int,
    output_kind: RenderVarOutputKind,
) -> tuple[int, ...]:
    if output_kind is RenderVarOutputKind.METADATA_MAP:
        return ()
    if resolution is None:
        return ()
    width, height = resolution
    return (height, width, int(component_count))


def _render_var_preset(spec: dict[str, Any]) -> RenderVarVisualizationPreset:
    preset_kind = spec["preset"]
    output_kind = spec["output_kind"]
    label = str(spec["display_name"])
    if preset_kind is RenderVarPresetKind.HDR_TONEMAP:
        return RenderVarVisualizationPreset(
            kind=preset_kind,
            label=label,
            hdr=RenderVarHdrSettings(),
        )
    if preset_kind is RenderVarPresetKind.SCALAR_GRAYSCALE:
        value_range = spec.get("value_range")
        return RenderVarVisualizationPreset(
            kind=preset_kind,
            label=label,
            scalar_range=RenderVarScalarRangeSettings(
                min_value=None if value_range is None else value_range[0],
                max_value=None if value_range is None else value_range[1],
                auto_range=value_range is None,
            ),
        )
    if preset_kind is RenderVarPresetKind.VECTOR_SIGNED:
        return RenderVarVisualizationPreset(
            kind=preset_kind,
            label=label,
            vector=RenderVarVectorSettings(
                channel_indices=(0, 1, 2),
                signed_remap=output_kind is RenderVarOutputKind.VECTOR_NORMAL,
                component_labels=("X", "Y", "Z"),
            ),
        )
    if preset_kind is RenderVarPresetKind.CATEGORICAL_PALETTE:
        return RenderVarVisualizationPreset(
            kind=preset_kind,
            label=label,
            categorical=RenderVarCategoricalSettings(),
        )
    return RenderVarVisualizationPreset(kind=preset_kind, label=label)


def _render_var_source_name(var: Any, prim: Any) -> str:
    try:
        source_name = var.GetSourceNameAttr().Get()
    except Exception:
        source_name = None
    return str(source_name or prim.GetName() or "")


def _render_var_missing_descriptor(
    product_path: str,
    var_path: Any,
) -> RenderVarOutputDescriptor:
    warning = _render_var_warning(
        "missing_render_var",
        f"RenderProduct target {var_path} does not resolve to a RenderVar.",
    )
    render_var_name = str(var_path)
    return RenderVarOutputDescriptor(
        render_product_path=product_path,
        render_var_name=render_var_name,
        display_name=render_var_name.rsplit("/", 1)[-1] or render_var_name,
        output_kind=RenderVarOutputKind.UNKNOWN,
        component_count=1,
        capabilities=("render_var_missing",),
        warnings=(warning,),
        enabled=False,
        disabled_reason=warning.message,
        metadata={"render_var_path": render_var_name},
    )


def _render_var_unknown_descriptor(
    product_path: str,
    render_var_name: str,
    var_path: Any,
    resolution: tuple[int, int] | None,
) -> RenderVarOutputDescriptor:
    warning = _render_var_warning(
        "unknown_output",
        f"RenderVar output {render_var_name!r} is not recognized.",
    )
    return RenderVarOutputDescriptor(
        render_product_path=product_path,
        render_var_name=render_var_name,
        display_name=render_var_name or str(var_path),
        output_kind=RenderVarOutputKind.UNKNOWN,
        dtype="",
        shape=_render_var_shape(resolution, 1, RenderVarOutputKind.UNKNOWN),
        component_count=1,
        capabilities=("render_var_unknown",),
        warnings=(warning,),
        enabled=False,
        disabled_reason=warning.message,
        metadata={"render_var_path": str(var_path), "source_name": render_var_name},
    )


def _render_var_output_descriptor(
    stage: Any,
    product: Any,
    product_path: str,
    var_path: Any,
) -> RenderVarOutputDescriptor | None:
    from pxr import UsdRender

    prim = stage.GetPrimAtPath(var_path)
    if not prim or not prim.IsValid() or not prim.IsA(UsdRender.Var):
        return _render_var_missing_descriptor(product_path, var_path)

    var = UsdRender.Var(prim)
    render_var_name = _render_var_source_name(var, prim)
    token = _source_token_key(render_var_name)
    if token in {_RENDER_VAR_LDR_TOKEN, _RENDER_VAR_POINT_CLOUD_TOKEN}:
        return None

    resolution = _render_var_resolution(product)
    spec = _RENDER_VAR_OUTPUT_SPECS.get(token)
    if spec is None:
        return _render_var_unknown_descriptor(
            product_path,
            render_var_name,
            var_path,
            resolution,
        )

    output_kind = spec["output_kind"]
    component_count = int(spec["component_count"])
    shape = _render_var_shape(resolution, component_count, output_kind)
    warnings: list[RenderVarWarning] = []
    if resolution is None and output_kind is not RenderVarOutputKind.METADATA_MAP:
        warnings.append(_render_var_warning(
            "missing_resolution",
            "RenderProduct has no authored resolution for this output.",
        ))
    return RenderVarOutputDescriptor(
        render_product_path=product_path,
        render_var_name=render_var_name,
        display_name=str(spec["display_name"]),
        output_kind=output_kind,
        dtype=str(spec["dtype"]),
        shape=shape,
        component_count=component_count,
        units=str(spec["units"]),
        value_range=spec["value_range"],
        color_space=str(spec["color_space"]),
        validity_semantics=str(spec["validity_semantics"]),
        presets=(_render_var_preset(spec),),
        capabilities=tuple(spec["capabilities"]),
        warnings=tuple(warnings),
        revision_token=f"{product_path}:{render_var_name}",
        metadata={
            "render_var_path": str(var_path),
            "source_name": render_var_name,
            "resolution": resolution or (),
        },
    )


def _render_var_product_prims(
    stage: Any,
    render_product_path: Optional[str],
) -> list[Any]:
    from pxr import Sdf, UsdRender

    if render_product_path:
        try:
            path = Sdf.Path(str(render_product_path))
        except Exception:
            return []
        prim = stage.GetPrimAtPath(path)
        if prim and prim.IsValid() and prim.IsA(UsdRender.Product):
            return [prim]
        return []
    return [
        prim
        for prim in stage.Traverse()
        if prim and prim.IsValid() and prim.IsA(UsdRender.Product)
    ]


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


_RENDER_SETTINGS_PROVIDER_ID = "openusd.render_product.public"
_RENDER_SETTINGS_PROVIDER_LABEL = "Public RenderProduct Settings"
_RENDER_SETTINGS_PUBLIC_NAMESPACES: Tuple[str, ...] = ("omni:rtx:",)
_RENDER_SETTINGS_METADATA_KEY = "renderSettings"
_RENDER_SETTINGS_GROUP_FALLBACK = "omni_rtx"
_RENDER_SETTINGS_GROUP_LABEL_FALLBACK = "Omni RTX"
_RENDER_SETTINGS_BUILTIN_SPECS: Tuple[dict[str, Any], ...] = (
    {
        "attr_name": "omni:rtx:rtpt:maxBounces",
        "usd_type": "int",
        "value_type": RenderSettingValueType.INT,
        "default": 3,
        "label": "Max Bounces",
        "description": "Maximum real-time path-tracing bounce count.",
        "group_id": "quality",
        "group_label": "Quality",
        "group_order": 10.0,
        "order": 10.0,
        "requirement": RenderSettingRequirement.WARMUP.value,
        "range": {"min": 0.0, "max": 32.0},
        "soft_range": {"min": 0.0, "max": 16.0},
        "units": "bounces",
    },
    {
        "attr_name": "omni:rtx:rendermode",
        "usd_type": "string",
        "value_type": RenderSettingValueType.ENUM,
        "default": "Real-Time Path-Tracing",
        "label": "Render Mode",
        "group_id": "quality",
        "group_label": "Quality",
        "group_order": 10.0,
        "order": 20.0,
        "requirement": RenderSettingRequirement.RENDERER_RESTART.value,
        "allowed_values": ("Real-Time Path-Tracing", "PathTracing", "Minimal"),
    },
    {
        "attr_name": "omni:rtx:rt:ambientLight:intensity",
        "usd_type": "float",
        "value_type": RenderSettingValueType.FLOAT,
        "default": 0.0,
        "label": "Ambient Light Intensity",
        "group_id": "tone",
        "group_label": "Tone",
        "group_order": 20.0,
        "order": 10.0,
        "requirement": RenderSettingRequirement.WARMUP.value,
        "range": {"min": 0.0, "max": 50000.0},
        "soft_range": {"min": 0.0, "max": 5000.0},
    },
    {
        "attr_name": "omni:rtx:minimal:constantColor",
        "usd_type": "color3f",
        "value_type": RenderSettingValueType.COLOR,
        "default": (0.0, 0.0, 0.0),
        "label": "Minimal Constant Color",
        "description": "Constant RGB output used by ovrtx Minimal render mode.",
        "group_id": "tone",
        "group_label": "Tone",
        "group_order": 20.0,
        "order": 20.0,
        "requirement": RenderSettingRequirement.WARMUP.value,
        "component_count": 3,
        "range": {"min": 0.0, "max": 1.0},
        "soft_range": {"min": 0.0, "max": 1.0},
    },
)


def _render_setting_builtin_spec(attr_name: str) -> dict[str, Any] | None:
    for spec in _RENDER_SETTINGS_BUILTIN_SPECS:
        if str(spec.get("attr_name") or "") == attr_name:
            return spec
    return None


def _render_setting_builtin_metadata(spec: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in spec.items():
        if key in {"attr_name", "usd_type"}:
            continue
        if isinstance(value, RenderSettingValueType):
            metadata[key] = value.value
        elif isinstance(value, RenderSettingRequirement):
            metadata[key] = value.value
        else:
            metadata[key] = value
    return metadata


def _render_setting_custom_data_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _render_setting_custom_data_value(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_render_setting_custom_data_value(item) for item in value]
    if isinstance(value, list):
        return [_render_setting_custom_data_value(item) for item in value]
    return value


def _render_setting_warning(code: str, message: str) -> RenderSettingWarning:
    return RenderSettingWarning(code=code, message=message)


def _render_setting_python_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "path"):
        try:
            return str(value.path)
        except Exception:
            pass
    if isinstance(value, dict):
        return {
            str(key): _render_setting_python_value(item)
            for key, item in value.items()
        }
    try:
        return tuple(_render_setting_python_value(item) for item in value)
    except TypeError:
        return str(value)


def _render_setting_metadata(attr: Any) -> dict[str, Any]:
    try:
        custom = attr.GetCustomData() or {}
    except Exception:
        return {}
    data = custom.get(_RENDER_SETTINGS_METADATA_KEY) or custom.get("render_settings")
    if isinstance(data, dict):
        return dict(data)
    return {}


def _render_setting_public_namespace(attr_name: str) -> tuple[str, str] | None:
    for namespace in _RENDER_SETTINGS_PUBLIC_NAMESPACES:
        if attr_name.startswith(namespace):
            return namespace, attr_name[len(namespace):]
    return None


def _render_setting_display_name(attr_name: str) -> str:
    local = attr_name.rsplit(":", 1)[-1]
    if not local:
        return attr_name
    chars: list[str] = []
    previous_lower = False
    for char in local:
        if previous_lower and char.isupper():
            chars.append(" ")
        chars.append(char)
        previous_lower = char.islower() or char.isdigit()
    label = "".join(chars).replace("_", " ").strip()
    return label[:1].upper() + label[1:] if label else attr_name


def _render_setting_float_range(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, dict):
        return None
    lo = value.get("min")
    hi = value.get("max")
    if lo is None or hi is None:
        return None
    try:
        lo_f = float(lo)
        hi_f = float(hi)
    except (TypeError, ValueError):
        return None
    if hi_f < lo_f:
        return None
    return (lo_f, hi_f)


def _render_setting_allowed_values(
    attr: Any,
    metadata: dict[str, Any],
) -> tuple[Any, ...]:
    authored = metadata.get("allowed_values")
    if authored is None:
        authored = metadata.get("allowedValues")
    if authored is not None:
        try:
            return tuple(_render_setting_python_value(item) for item in authored)
        except TypeError:
            return (_render_setting_python_value(authored),)
    try:
        tokens = attr.GetMetadata("allowedTokens")
    except Exception:
        tokens = None
    if tokens:
        return tuple(str(token) for token in tokens)
    return ()


def _render_setting_component_count(usd_type: str, metadata: dict[str, Any]) -> int:
    explicit = metadata.get("component_count") or metadata.get("componentCount")
    if explicit is not None:
        try:
            count = int(explicit)
            if count > 0:
                return count
        except (TypeError, ValueError):
            pass
    key = _source_token_key(usd_type)
    if key.endswith("2"):
        return 2
    if key.endswith("3"):
        return 3
    if key.endswith("4"):
        return 4
    return 1


def _render_setting_value_type(
    usd_type: str,
    attr: Any,
    metadata: dict[str, Any],
) -> RenderSettingValueType:
    explicit = metadata.get("value_type") or metadata.get("valueType")
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
            if _render_setting_allowed_values(attr, metadata)
            else RenderSettingValueType.TOKEN
        )
    if key == "asset":
        return RenderSettingValueType.PATH
    if key in {"color3f", "color3d", "color3h", "color4f", "color4d", "color4h"}:
        return RenderSettingValueType.COLOR
    if key in {
        "float2", "double2", "half2",
        "float3", "double3", "half3",
        "float4", "double4", "half4",
        "int2", "int3", "int4",
        "vector3f", "vector3d", "vector3h",
        "normal3f", "normal3d", "normal3h",
        "point3f", "point3d", "point3h",
    }:
        return RenderSettingValueType.VECTOR
    return RenderSettingValueType.UNKNOWN


def _render_setting_requirement(metadata: dict[str, Any]) -> RenderSettingRequirement:
    raw = metadata.get("requirement", RenderSettingRequirement.NONE.value)
    try:
        return RenderSettingRequirement(str(raw))
    except ValueError:
        return RenderSettingRequirement.NONE


def _render_setting_visibility(metadata: dict[str, Any]) -> RenderSettingVisibility:
    raw = metadata.get("visibility", RenderSettingVisibility.PUBLIC.value)
    try:
        return RenderSettingVisibility(str(raw))
    except ValueError:
        return RenderSettingVisibility.PUBLIC


def _render_setting_constraints(
    attr: Any,
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
        allowed_values=_render_setting_allowed_values(attr, metadata),
        component_count=_render_setting_component_count(usd_type, metadata),
        pattern=str(metadata.get("pattern") or ""),
        options=(
            metadata.get("options")
            if isinstance(metadata.get("options"), dict)
            else {}
        ),
    )


def _render_setting_default_value(
    attr: Any,
    value: Any,
    authored: bool,
    metadata: dict[str, Any],
) -> tuple[Any, bool]:
    if "default" in metadata:
        return _render_setting_python_value(metadata.get("default")), True
    if not authored and value is not None:
        return _render_setting_python_value(value), True
    return None, False


def _render_setting_descriptor(
    product_path: str,
    attr: Any,
) -> RenderSettingDescriptor | None:
    attr_name = str(attr.GetName())
    namespace_parts = _render_setting_public_namespace(attr_name)
    if namespace_parts is None:
        return None
    namespace, property_name = namespace_parts
    metadata = _render_setting_metadata(attr)
    builtin_spec = _render_setting_builtin_spec(attr_name)
    if builtin_spec is not None:
        metadata = {
            **_render_setting_builtin_metadata(builtin_spec),
            **metadata,
        }
    usd_type = str(attr.GetTypeName() or "")
    value_type = _render_setting_value_type(usd_type, attr, metadata)
    warnings: list[RenderSettingWarning] = []
    disabled_reason = str(
        metadata.get("disabled_reason")
        or metadata.get("disabledReason")
        or ""
    )
    enabled = bool(metadata.get("enabled", True))
    if value_type is RenderSettingValueType.UNKNOWN:
        warning = _render_setting_warning(
            "unknown_value_type",
            f"RenderProduct setting {attr_name!r} has unsupported USD type {usd_type!r}.",
        )
        warnings.append(warning)
        enabled = False
        if not disabled_reason:
            disabled_reason = warning.message

    try:
        current_value = _render_setting_python_value(attr.Get())
    except Exception:
        warning = _render_setting_warning(
            "read_failed",
            f"RenderProduct setting {attr_name!r} could not be read.",
        )
        warnings.append(warning)
        current_value = None
        enabled = False
        if not disabled_reason:
            disabled_reason = warning.message
    try:
        authored = bool(attr.HasAuthoredValue())
    except Exception:
        authored = False
    default_value, has_default = _render_setting_default_value(
        attr,
        current_value,
        authored,
        metadata,
    )
    if current_value is None and has_default:
        current_value = default_value

    state = RenderSettingValueState(
        current_value=current_value,
        default_value=default_value,
        has_default=has_default,
        authored=authored,
        inherited=bool((not authored) and has_default),
        dirty=False,
        invalid=value_type is RenderSettingValueType.UNKNOWN,
        disabled=bool((not enabled) or disabled_reason),
        disabled_reason=disabled_reason,
        message=str(metadata.get("message") or ""),
        warnings=tuple(warnings),
        metadata={
            "usd_type": usd_type,
            "render_product_path": product_path,
            "attr_name": attr_name,
        },
    )
    group_id = str(
        metadata.get("group_id")
        or metadata.get("group")
        or _RENDER_SETTINGS_GROUP_FALLBACK
    )
    label = str(metadata.get("label") or _render_setting_display_name(attr_name))
    return RenderSettingDescriptor(
        setting_id=f"{product_path}:{attr_name}",
        label=label,
        provider_id=_RENDER_SETTINGS_PROVIDER_ID,
        group_id=group_id,
        namespace=namespace,
        property_name=property_name,
        description=str(metadata.get("description") or ""),
        value_type=value_type,
        constraints=_render_setting_constraints(attr, usd_type, metadata),
        units=str(metadata.get("units") or ""),
        default_value=default_value,
        has_default=has_default,
        requirement=_render_setting_requirement(metadata),
        visibility=_render_setting_visibility(metadata),
        visibility_gate=str(
            metadata.get("visibility_gate")
            or metadata.get("visibilityGate")
            or ""
        ),
        order=float(metadata.get("order", 1000.0)),
        enabled=enabled,
        disabled_reason=disabled_reason,
        value_state=state,
        warnings=tuple(warnings),
        revision_token=f"{product_path}:{attr_name}:{current_value!r}:{authored}",
        metadata={
            "usd_type": usd_type,
            "attr_name": attr_name,
            "render_product_path": product_path,
        },
    )


def _render_setting_builtin_descriptor(
    product_path: str,
    spec: dict[str, Any],
) -> RenderSettingDescriptor | None:
    attr_name = str(spec.get("attr_name") or "")
    namespace_parts = _render_setting_public_namespace(attr_name)
    if namespace_parts is None:
        return None
    namespace, property_name = namespace_parts
    metadata = _render_setting_builtin_metadata(spec)
    usd_type = str(spec.get("usd_type") or "")
    value_type = _render_setting_value_type(usd_type, None, metadata)
    default_value = _render_setting_python_value(metadata.get("default"))
    has_default = "default" in metadata
    state = RenderSettingValueState(
        current_value=default_value,
        default_value=default_value,
        has_default=has_default,
        authored=False,
        inherited=has_default,
        dirty=False,
        invalid=False,
        disabled=not bool(metadata.get("enabled", True)),
        disabled_reason=str(
            metadata.get("disabled_reason")
            or metadata.get("disabledReason")
            or ""
        ),
        metadata={
            "usd_type": usd_type,
            "render_product_path": product_path,
            "attr_name": attr_name,
            "builtin": True,
        },
    )
    return RenderSettingDescriptor(
        setting_id=f"{product_path}:{attr_name}",
        label=str(metadata.get("label") or _render_setting_display_name(attr_name)),
        provider_id=_RENDER_SETTINGS_PROVIDER_ID,
        group_id=str(
            metadata.get("group_id")
            or metadata.get("group")
            or _RENDER_SETTINGS_GROUP_FALLBACK
        ),
        namespace=namespace,
        property_name=property_name,
        description=str(metadata.get("description") or ""),
        value_type=value_type,
        constraints=_render_setting_constraints(None, usd_type, metadata),
        units=str(metadata.get("units") or ""),
        default_value=default_value,
        has_default=has_default,
        requirement=_render_setting_requirement(metadata),
        visibility=_render_setting_visibility(metadata),
        visibility_gate=str(
            metadata.get("visibility_gate")
            or metadata.get("visibilityGate")
            or ""
        ),
        order=float(metadata.get("order", 1000.0)),
        enabled=bool(metadata.get("enabled", True)),
        disabled_reason=str(
            metadata.get("disabled_reason")
            or metadata.get("disabledReason")
            or ""
        ),
        value_state=state,
        revision_token=f"{product_path}:{attr_name}:{default_value!r}:False",
        metadata={
            "usd_type": usd_type,
            "attr_name": attr_name,
            "render_product_path": product_path,
            "builtin": True,
            "render_settings_metadata": metadata,
        },
    )


def _render_settings_group_descriptors(
    settings: list[RenderSettingDescriptor],
    metadata_by_group: dict[str, dict[str, Any]],
) -> tuple[RenderSettingsGroupDescriptor, ...]:
    groups: list[RenderSettingsGroupDescriptor] = []
    for group_id in sorted({setting.group_id for setting in settings}):
        group_metadata = metadata_by_group.get(group_id, {})
        groups.append(RenderSettingsGroupDescriptor(
            group_id=group_id,
            label=str(
                group_metadata.get("group_label")
                or group_metadata.get("groupLabel")
                or (
                    _RENDER_SETTINGS_GROUP_LABEL_FALLBACK
                    if group_id == _RENDER_SETTINGS_GROUP_FALLBACK
                    else _render_setting_display_name(group_id)
                )
            ),
            provider_id=_RENDER_SETTINGS_PROVIDER_ID,
            order=float(group_metadata.get(
                "group_order",
                group_metadata.get("groupOrder", 1000.0),
            )),
            collapsed_default=bool(
                group_metadata.get("collapsed_default")
                or group_metadata.get("collapsedDefault")
                or False
            ),
            description=str(
                group_metadata.get("group_description")
                or group_metadata.get("groupDescription")
                or ""
            ),
            metadata={"namespace": group_metadata.get("namespace", "")},
        ))
    groups.sort(key=lambda item: (item.order, item.label, item.group_id))
    return tuple(groups)


def _render_settings_product_prim(
    stage: Any,
    render_product_path: Optional[str],
) -> Any:
    from pxr import Sdf, UsdRender

    if not render_product_path:
        return None
    try:
        path = Sdf.Path(str(render_product_path))
        prim = stage.GetPrimAtPath(path)
        if prim and prim.IsValid() and prim.IsA(UsdRender.Product):
            return prim
    except Exception:
        return None
    return None


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
    for setting in catalog.settings:
        if requested in {
            setting.property_name,
            f"{setting.namespace}{setting.property_name}",
        }:
            return setting
    return None


def _render_setting_reject_validation(
    setting_id: str,
    message: str,
    code: str,
) -> RenderSettingValidationResult:
    return RenderSettingValidationResult.rejected_result(
        message,
        setting_id=setting_id,
        warning_code=code,
    )


def _render_setting_reject_apply(
    setting_id: str,
    message: str,
    code: str,
) -> RenderSettingApplyResult:
    return RenderSettingApplyResult.rejected_result(
        message,
        setting_id=setting_id,
        warning_code=code,
    )


def _render_setting_reject_reset(
    setting_id: str,
    message: str,
    code: str,
) -> RenderSettingResetResult:
    return RenderSettingResetResult.rejected_result(
        message,
        setting_id=setting_id,
        warning_code=code,
    )


def _render_setting_constraints_are_consistent(
    constraints: RenderSettingValueConstraints,
) -> bool:
    if constraints.soft_range is None or constraints.hard_range is None:
        return True
    soft_min, soft_max = constraints.soft_range
    hard_min, hard_max = constraints.hard_range
    return hard_min <= soft_min <= soft_max <= hard_max


def _render_setting_coerce_bool(value: Any) -> bool:
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


def _render_setting_coerce_int(value: Any) -> int:
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


def _render_setting_coerce_float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Expected a finite numeric value.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Expected a finite numeric value.")
    return result


def _render_setting_coerce_sequence(
    value: Any,
    *,
    component_count: int,
    label: str,
) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"Expected a {label} sequence.")
    try:
        items = tuple(value)
    except TypeError as exc:
        raise ValueError(f"Expected a {label} sequence.") from exc
    if len(items) != component_count:
        raise ValueError(
            f"Expected {component_count} {label} components; got {len(items)}."
        )
    return tuple(_render_setting_coerce_float(item) for item in items)


def _render_setting_coerce_value(
    descriptor: RenderSettingDescriptor,
    value: Any,
) -> Any:
    constraints = descriptor.constraints
    value_type = descriptor.value_type
    if value_type is RenderSettingValueType.BOOL:
        return _render_setting_coerce_bool(value)
    if value_type is RenderSettingValueType.INT:
        return _render_setting_coerce_int(value)
    if value_type is RenderSettingValueType.FLOAT:
        return _render_setting_coerce_float(value)
    if value_type in {
        RenderSettingValueType.ENUM,
        RenderSettingValueType.STRING,
        RenderSettingValueType.TOKEN,
        RenderSettingValueType.PATH,
    }:
        return str(value)
    if value_type is RenderSettingValueType.VECTOR:
        return _render_setting_coerce_sequence(
            value,
            component_count=constraints.component_count,
            label="vector",
        )
    if value_type is RenderSettingValueType.COLOR:
        return _render_setting_coerce_sequence(
            value,
            component_count=constraints.component_count,
            label="color",
        )
    raise ValueError("Unsupported render setting value type.")


def _render_setting_numeric_values(value: Any) -> tuple[float, ...]:
    if isinstance(value, bool):
        return ()
    if isinstance(value, (int, float)):
        return (float(value),)
    if isinstance(value, tuple):
        values: list[float] = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                return ()
            values.append(float(item))
        return tuple(values)
    return ()


def _render_setting_value_within_constraints(
    descriptor: RenderSettingDescriptor,
    value: Any,
) -> tuple[bool, str, str]:
    constraints = descriptor.constraints
    if not _render_setting_constraints_are_consistent(constraints):
        return (
            False,
            "Render setting metadata has a soft range outside its hard range.",
            "invalid_constraints",
        )
    if constraints.allowed_values:
        allowed = tuple(
            _render_setting_python_value(item)
            for item in constraints.allowed_values
        )
        allowed_strings = {str(item) for item in allowed}
        if value not in allowed and str(value) not in allowed_strings:
            return (
                False,
                f"Value {value!r} is not one of the allowed values.",
                "value_not_allowed",
            )
    if constraints.hard_range is not None:
        lo, hi = constraints.hard_range
        for numeric in _render_setting_numeric_values(value):
            if numeric < lo or numeric > hi:
                return (
                    False,
                    f"Value {value!r} is outside the allowed range {lo:g}..{hi:g}.",
                    "value_out_of_range",
                )
    return True, "", ""


def _render_setting_usd_type_name(usd_type: str) -> Any:
    from pxr import Sdf

    key = str(usd_type or "").lower()
    return {
        "bool": Sdf.ValueTypeNames.Bool,
        "int": Sdf.ValueTypeNames.Int,
        "uint": Sdf.ValueTypeNames.UInt,
        "int64": Sdf.ValueTypeNames.Int64,
        "uint64": Sdf.ValueTypeNames.UInt64,
        "float": Sdf.ValueTypeNames.Float,
        "double": Sdf.ValueTypeNames.Double,
        "half": Sdf.ValueTypeNames.Half,
        "string": Sdf.ValueTypeNames.String,
        "token": Sdf.ValueTypeNames.Token,
        "asset": Sdf.ValueTypeNames.Asset,
        "float2": Sdf.ValueTypeNames.Float2,
        "float3": Sdf.ValueTypeNames.Float3,
        "float4": Sdf.ValueTypeNames.Float4,
        "double2": Sdf.ValueTypeNames.Double2,
        "double3": Sdf.ValueTypeNames.Double3,
        "double4": Sdf.ValueTypeNames.Double4,
        "color3f": Sdf.ValueTypeNames.Color3f,
        "color4f": Sdf.ValueTypeNames.Color4f,
    }.get(key)


def _render_setting_attr_for_descriptor(
    stage: Any,
    descriptor: RenderSettingDescriptor,
    *,
    create: bool = False,
) -> Any:
    product_path = str(descriptor.metadata.get("render_product_path") or "")
    attr_name = str(descriptor.metadata.get("attr_name") or "")
    if not product_path or not attr_name:
        return None
    try:
        prim = stage.GetPrimAtPath(product_path)
        if not prim or not prim.IsValid():
            return None
        attr = prim.GetAttribute(attr_name)
        if not attr or not attr.IsValid():
            if not create or not descriptor.metadata.get("builtin"):
                return None
            usd_type_name = _render_setting_usd_type_name(
                str(descriptor.metadata.get("usd_type") or "")
            )
            if usd_type_name is None:
                return None
            attr = prim.CreateAttribute(attr_name, usd_type_name, custom=True)
            if not attr or not attr.IsValid():
                return None
            metadata = descriptor.metadata.get("render_settings_metadata")
            if isinstance(metadata, dict):
                try:
                    payload = _render_setting_custom_data_value(metadata)
                    attr.SetCustomData({
                        _RENDER_SETTINGS_METADATA_KEY: payload,
                    })
                except Exception:
                    pass
    except Exception:
        return None
    return attr


def _render_setting_edit_target_layer(
    stage: Any,
    descriptor: RenderSettingDescriptor,
) -> Any:
    product_path = str(descriptor.metadata.get("render_product_path") or "")
    if not product_path.startswith(f"{_SESSION_ROOT_PATH}/"):
        return None
    try:
        return stage.GetSessionLayer()
    except Exception:
        return None


def _render_setting_usd_value(
    descriptor: RenderSettingDescriptor,
    normalized_value: Any,
) -> Any:
    if descriptor.value_type in {
        RenderSettingValueType.VECTOR,
        RenderSettingValueType.COLOR,
    }:
        return tuple(normalized_value)
    return normalized_value


def _render_setting_set_attr(
    attr: Any,
    descriptor: RenderSettingDescriptor,
    normalized_value: Any,
) -> None:
    if not attr.Set(_render_setting_usd_value(descriptor, normalized_value)):
        raise RuntimeError("USD attribute Set returned false")


def _render_setting_clear_attr(attr: Any) -> None:
    if not attr.Clear():
        raise RuntimeError("USD attribute Clear returned false")


def _point_cloud_warning(code: str, message: str) -> PointCloudWarning:
    return PointCloudWarning(code=code, message=message)


def _point_cloud_source_targets(product: Any) -> list[Any]:
    try:
        return list(product.GetCameraRel().GetTargets())
    except Exception:
        return []


def _point_cloud_ordered_var_targets(product: Any) -> list[Any]:
    try:
        return list(product.GetOrderedVarsRel().GetTargets())
    except Exception:
        return []


def _usd_render_product(prim: Any) -> Any:
    from pxr import UsdRender

    return UsdRender.Product(prim)


def _point_cloud_render_var_source_name(var: Any, prim: Any) -> str:
    try:
        source_name = var.GetSourceNameAttr().Get()
    except Exception:
        source_name = None
    return str(source_name or prim.GetName() or "PointCloud")


def _point_cloud_render_var_channels(
    prim: Any,
    warnings: list[PointCloudWarning],
) -> tuple[str, ...]:
    attr = prim.GetAttribute("channels")
    if not attr or not attr.HasAuthoredValue():
        warnings.append(_point_cloud_warning(
            "missing_channels",
            "PointCloud RenderVar has no authored channels.",
        ))
        authored: tuple[str, ...] = ()
    else:
        try:
            value = attr.Get() or ()
            authored = tuple(str(channel) for channel in value if str(channel))
        except Exception:
            warnings.append(_point_cloud_warning(
                "missing_channels",
                "PointCloud RenderVar channels could not be read.",
            ))
            authored = ()

    channels: list[str] = []
    seen: set[str] = set()
    for channel in authored:
        key = _source_token_key(channel)
        if not key or key in seen:
            continue
        spec = _POINT_CLOUD_CHANNEL_SPECS.get(key)
        channels.append(spec[0] if spec is not None else str(channel))
        seen.add(key)
    return tuple(channels)


def _point_cloud_channel_descriptor(
    channel: str,
    warnings: list[PointCloudWarning],
) -> PointCloudChannelDescriptor:
    key = _source_token_key(channel)
    spec = _POINT_CLOUD_CHANNEL_SPECS.get(key)
    if spec is None:
        warnings.append(_point_cloud_warning(
            "unknown_channel",
            f"PointCloud channel {channel!r} is unknown.",
        ))
        return PointCloudChannelDescriptor(
            name=str(channel),
            semantic=PointCloudChannelSemantic.UNKNOWN,
        )

    (
        name,
        semantic,
        dtype,
        component_count,
        units,
        value_range,
        validity_semantics,
        color_modes,
    ) = spec
    return PointCloudChannelDescriptor(
        name=name,
        semantic=semantic,
        dtype=dtype,
        component_count=component_count,
        units=units,
        value_range=value_range,
        validity_semantics=validity_semantics,
        color_modes=color_modes,
    )


def _point_cloud_coordinate_space(prim: Any) -> PointCloudCoordinateSpace:
    for attr_name in _POINT_CLOUD_SOURCE_ATTRS:
        attr = prim.GetAttribute(attr_name)
        if not attr or not attr.HasAuthoredValue():
            continue
        try:
            value = attr.Get()
        except Exception:
            continue
        key = _source_token_key(value)
        if key == "world":
            return PointCloudCoordinateSpace.WORLD
        if key == "sensor":
            return PointCloudCoordinateSpace.SENSOR
        if key in {"local", "custom"}:
            return PointCloudCoordinateSpace.LOCAL
    return PointCloudCoordinateSpace.UNKNOWN


def _point_cloud_transform_to_world(prim: Any) -> tuple[float, ...] | None:
    try:
        from pxr import Usd, UsdGeom
    except Exception:
        return None
    try:
        xformable = UsdGeom.Xformable(prim)
        if not xformable:
            return None
        matrix = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        return tuple(float(matrix[row][col]) for row in range(4) for col in range(4))
    except Exception:
        return None


def _point_cloud_source_metadata(
    stage: Any,
    product: Any,
) -> tuple[
    Optional[str],
    str,
    str,
    PointCloudCoordinateSpace,
    tuple[float, ...] | None,
    list[PointCloudWarning],
]:
    warnings: list[PointCloudWarning] = []
    targets = _point_cloud_source_targets(product)
    if not targets:
        warnings.append(_point_cloud_warning(
            "missing_source",
            "RenderProduct has no sensor target.",
        ))
        return None, "", "", PointCloudCoordinateSpace.UNKNOWN, None, warnings

    source_path = str(targets[0])
    prim = stage.GetPrimAtPath(targets[0])
    if not prim or not prim.IsValid():
        warnings.append(_point_cloud_warning(
            "missing_source",
            f"RenderProduct source {source_path} does not exist.",
        ))
        return source_path, "", "", PointCloudCoordinateSpace.UNKNOWN, None, warnings

    return (
        source_path,
        str(prim.GetName() or source_path),
        str(prim.GetTypeName() or ""),
        _point_cloud_coordinate_space(prim),
        _point_cloud_transform_to_world(prim),
        warnings,
    )


def _point_cloud_capabilities(
    channels: tuple[PointCloudChannelDescriptor, ...],
    coordinate_space: PointCloudCoordinateSpace,
) -> tuple[str, ...]:
    capabilities: list[str] = ["point_cloud"]
    semantics = {channel.semantic for channel in channels}
    color_modes = {
        color_mode
        for channel in channels
        for color_mode in channel.color_modes
    }
    if PointCloudChannelSemantic.COORDINATES in semantics:
        capabilities.append("point_cloud_coordinates")
    if PointCloudChannelSemantic.COUNT in semantics:
        capabilities.append("point_cloud_counts")
    if PointCloudChannelSemantic.FLAGS in semantics:
        capabilities.append("point_cloud_validity")
    if coordinate_space is PointCloudCoordinateSpace.WORLD:
        capabilities.append("point_cloud_world_points")
    elif coordinate_space is PointCloudCoordinateSpace.SENSOR:
        capabilities.append("point_cloud_sensor_frame")
    for color_mode in (
        PointCloudColorMode.RANGE,
        PointCloudColorMode.INTENSITY,
        PointCloudColorMode.VELOCITY,
        PointCloudColorMode.RCS,
        PointCloudColorMode.MATERIAL_ID,
        PointCloudColorMode.OBJECT_ID,
    ):
        if color_mode in color_modes:
            capabilities.append(f"point_cloud_color_{color_mode.value}")
    return tuple(capabilities)


def _point_cloud_source_disabled_reason(source_type: str) -> str:
    """Return runtime safety disables for source types ovui must not activate."""

    if "radar" in str(source_type or "").lower():
        # Runtime-safety denylist: current ovrtx radar sensor activation aborts
        # the process, and ovrtx must stay untouched. Revisit for safe radar variants.
        return (
            "Radar PointCloud output is disabled because the current ovrtx radar "
            "sensor runtime aborts during initialization."
        )
    return ""


def _point_cloud_output_descriptor(
    stage: Any,
    product: Any,
    product_path: str,
    var_path: Any,
) -> PointCloudOutputDescriptor | None:
    from pxr import UsdRender

    warnings: list[PointCloudWarning] = []
    prim = stage.GetPrimAtPath(var_path)
    if not prim or not prim.IsValid() or not prim.IsA(UsdRender.Var):
        return None

    var = UsdRender.Var(prim)
    render_var_name = _point_cloud_render_var_source_name(var, prim)
    if _source_token_key(render_var_name) != _POINT_CLOUD_SOURCE_TOKEN:
        return None

    (
        source_path,
        source_name,
        source_type,
        coordinate_space,
        transform_to_world,
        source_warnings,
    ) = _point_cloud_source_metadata(stage, product)
    warnings.extend(source_warnings)
    channel_names = _point_cloud_render_var_channels(prim, warnings)
    channels = tuple(
        _point_cloud_channel_descriptor(channel, warnings)
        for channel in channel_names
    )
    semantics = {channel.semantic for channel in channels}
    disabled_reason = ""
    if any(warning.code == "missing_source" for warning in warnings):
        disabled_reason = "PointCloud output has no valid source sensor."
    source_disabled_reason = _point_cloud_source_disabled_reason(source_type)
    if not disabled_reason and source_disabled_reason:
        disabled_reason = source_disabled_reason
        warnings.append(_point_cloud_warning(
            "unsafe_sensor_runtime",
            disabled_reason,
        ))
    elif not disabled_reason and PointCloudChannelSemantic.COORDINATES not in semantics:
        disabled_reason = "PointCloud output has no Coordinates channel."
        warnings.append(_point_cloud_warning(
            "missing_coordinates",
            disabled_reason,
        ))
    elif not disabled_reason and PointCloudChannelSemantic.COUNT not in semantics:
        disabled_reason = "PointCloud output has no Counts channel."
        warnings.append(_point_cloud_warning(
            "missing_counts",
            disabled_reason,
        ))

    return PointCloudOutputDescriptor(
        render_product_path=product_path,
        render_var_name=render_var_name,
        source_sensor_path=source_path,
        source_sensor_name=source_name,
        source_sensor_type=source_type,
        coordinate_space=coordinate_space,
        transform_to_world=transform_to_world,
        channels=channels,
        capabilities=_point_cloud_capabilities(channels, coordinate_space),
        warnings=tuple(warnings),
        enabled=not disabled_reason,
        disabled_reason=disabled_reason,
    )


def _point_cloud_product_prims(
    stage: Any,
    render_product_path: Optional[str],
) -> list[Any]:
    from pxr import Sdf, UsdRender

    if render_product_path:
        try:
            path = Sdf.Path(str(render_product_path))
        except Exception:
            return []
        prim = stage.GetPrimAtPath(path)
        if prim and prim.IsValid() and prim.IsA(UsdRender.Product):
            return [prim]
        return []
    return [
        prim
        for prim in stage.Traverse()
        if prim and prim.IsValid() and prim.IsA(UsdRender.Product)
    ]


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


def _point_cloud_render_vars_for_product(
    products: Any,
    render_product_path: str,
) -> dict[Any, Any] | None:
    try:
        product = products[render_product_path]
    except Exception:
        return None
    frames = getattr(product, "frames", None)
    if not frames:
        return None
    return getattr(frames[0], "render_vars", None) or {}


def _point_cloud_render_var(render_vars: dict[Any, Any], name: str) -> Any:
    if name in render_vars:
        return render_vars[name]
    requested = _source_token_key(name)
    for key, value in render_vars.items():
        if _source_token_key(key) == requested:
            return value
    return None


def _copy_tensor_to_host(data: Any) -> np.ndarray:
    numpy_fn = getattr(data, "numpy", None)
    if callable(numpy_fn):
        return np.array(numpy_fn(), copy=True)
    return np.array(np.from_dlpack(data), copy=True)


def _point_cloud_copy_tensor(data: Any) -> np.ndarray:
    return _copy_tensor_to_host(data)


def _point_cloud_copy_mapped_channel(
    mapping: Any,
    name: str,
    *,
    allow_tensor: bool = True,
) -> np.ndarray:
    try:
        channel = mapping[name]
    except Exception:
        channel = None
    if channel is not None:
        return _point_cloud_copy_tensor(channel)
    if not allow_tensor:
        raise KeyError(name)
    try:
        tensor = mapping.tensor
    except Exception as exc:
        raise KeyError(name) from exc
    return _point_cloud_copy_tensor(tensor)


def _point_cloud_copy_render_var(render_vars: dict[Any, Any], name: str) -> np.ndarray:
    rv = _point_cloud_render_var(render_vars, name)
    device = None
    try:
        device = _ovrtx.Device.CPU
    except Exception:
        pass
    if rv is not None:
        with rv.map(device=device) as mapping:
            return _point_cloud_copy_mapped_channel(mapping, name)
    for candidate in render_vars.values():
        mapper = getattr(candidate, "map", None)
        if not callable(mapper):
            continue
        with mapper(device=device) as mapping:
            try:
                return _point_cloud_copy_mapped_channel(
                    mapping,
                    name,
                    allow_tensor=False,
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


def _point_cloud_count(counts: Any, coordinate_count: int) -> int:
    try:
        count_value = int(np.asarray(counts).reshape(-1)[0])
    except Exception:
        count_value = int(coordinate_count)
    return max(0, min(count_value, int(coordinate_count)))


def _point_cloud_indices(
    point_count: int,
    request: PointCloudRequest,
) -> np.ndarray:
    stride = max(1, int(request.decimation_stride))
    indices = np.arange(int(point_count), dtype=np.int64)[::stride]
    if request.max_points is not None:
        indices = indices[: int(request.max_points)]
    return indices


def _point_cloud_channel_payload(
    data: Any,
    indices: np.ndarray,
    descriptor: PointCloudChannelDescriptor,
) -> np.ndarray:
    rows = _point_cloud_rows(data, descriptor.component_count)
    return np.array(rows[indices], copy=True)


def _point_cloud_validity_mask(flags: Any, indices: np.ndarray) -> np.ndarray:
    values = np.asarray(flags).reshape(-1)
    selected = values[indices].astype(np.uint64, copy=False)
    return np.array((selected & 0x40) != 0, copy=True)


def _stage_units_per_meter(stage: Any) -> float:
    try:
        from pxr import UsdGeom

        meters_per_unit = float(UsdGeom.GetStageMetersPerUnit(stage))
    except Exception:
        return 1.0
    if not math.isfinite(meters_per_unit) or meters_per_unit <= 0.0:
        return 1.0
    return 1.0 / meters_per_unit


def _point_cloud_world_coordinates(
    coordinates: np.ndarray,
    descriptor: PointCloudOutputDescriptor,
    units_per_meter: float = 1.0,
) -> tuple[np.ndarray | None, PointCloudCoordinateSpace, PointCloudWarning | None]:
    scale = float(units_per_meter) if math.isfinite(float(units_per_meter)) else 1.0
    if scale <= 0.0:
        scale = 1.0
    if descriptor.coordinate_space is PointCloudCoordinateSpace.WORLD:
        return (
            np.asarray(coordinates[:, :3], dtype=np.float32) * scale,
            PointCloudCoordinateSpace.WORLD,
            None,
        )
    transform = descriptor.transform_to_world
    if transform is None:
        return (
            None,
            descriptor.coordinate_space,
            _point_cloud_warning(
                "missing_transform",
                "PointCloud output cannot be transformed to world space.",
            ),
        )
    try:
        matrix = np.asarray(transform, dtype=np.float64).reshape((4, 4))
        points = np.asarray(coordinates[:, :3], dtype=np.float64) * scale
        homogeneous = np.ones((points.shape[0], 4), dtype=np.float64)
        homogeneous[:, :3] = points
        transformed = homogeneous @ matrix
        return (
            np.asarray(transformed[:, :3], dtype=np.float32),
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


def _point_cloud_frame_index(frame_out: Any) -> Optional[int]:
    for attr_name in ("frame_index", "frameIndex", "index"):
        value = getattr(frame_out, attr_name, None)
        if value is None:
            continue
        try:
            return int(value)
        except Exception:
            continue
    return None


def _render_var_render_vars_for_product(
    products: Any,
    render_product_path: str,
) -> tuple[dict[Any, Any] | None, Any]:
    try:
        product = products[render_product_path]
    except Exception:
        return None, None
    frames = getattr(product, "frames", None)
    if not frames:
        return None, None
    frame_out = frames[0]
    return getattr(frame_out, "render_vars", None) or {}, frame_out


def _render_var_runtime_render_var(
    render_vars: dict[Any, Any],
    descriptor: RenderVarOutputDescriptor,
) -> Any:
    names = (
        descriptor.render_var_name,
        descriptor.metadata.get("source_name", ""),
        descriptor.display_name,
    )
    for name in names:
        if name and name in render_vars:
            return render_vars[name]
    requested = {_source_token_key(name) for name in names if name}
    for key, value in render_vars.items():
        if _source_token_key(key) in requested:
            return value
    return None


def _render_var_copy_runtime_data(
    render_vars: dict[Any, Any],
    descriptor: RenderVarOutputDescriptor,
) -> np.ndarray:
    rv = _render_var_runtime_render_var(render_vars, descriptor)
    if rv is None:
        raise KeyError(descriptor.render_var_name)
    device = None
    try:
        device = _ovrtx.Device.CPU
    except Exception:
        pass
    with rv.map(device=device) as mapping:
        try:
            return _copy_tensor_to_host(mapping.tensor)
        except Exception:
            try:
                return _copy_tensor_to_host(mapping[descriptor.render_var_name])
            except Exception:
                raise


def _render_var_frame_shape(
    data: np.ndarray,
    descriptor: RenderVarOutputDescriptor,
) -> tuple[int, int, int]:
    arr = np.asarray(data)
    if descriptor.output_kind is RenderVarOutputKind.METADATA_MAP:
        return 0, 0, int(descriptor.component_count)
    if arr.ndim < 2:
        raise ValueError(f"RenderVar data must be at least 2D, got {arr.shape}")
    component_count = int(descriptor.component_count)
    actual_components = 1 if arr.ndim == 2 else int(arr.shape[-1])
    if actual_components < component_count:
        raise ValueError(
            f"RenderVar data has {actual_components} components; "
            f"expected at least {component_count}"
        )
    return int(arr.shape[1]), int(arr.shape[0]), component_count


def _point_cloud_requested_channel_names(
    request: PointCloudRequest,
    descriptor: PointCloudOutputDescriptor,
) -> tuple[str, ...]:
    if request.requested_channels:
        return tuple(str(channel) for channel in request.requested_channels if channel)
    ignored = {
        PointCloudChannelSemantic.COORDINATES,
        PointCloudChannelSemantic.COUNT,
    }
    return tuple(
        channel.name
        for channel in descriptor.channels
        if channel.semantic not in ignored
    )


def _config_with_selection_outline_enabled(config: Any) -> Any:
    """Return an ovrtx renderer config with outline and sensor motion enabled."""
    if not _probe_ovrtx():
        return config
    if config is None:
        config_cls = getattr(_ovrtx, "RendererConfig", None)
        if config_cls is None:
            return None
        try:
            return config_cls(
                selection_outline_enabled=True,
                selection_outline_width=2,
                enable_motion_bvh=True,
            )
        except TypeError:
            cfg = config_cls()
            try:
                cfg.selection_outline_enabled = True
                cfg.selection_outline_width = 2
                cfg.enable_motion_bvh = True
            except Exception:
                pass
            return cfg
    try:
        if getattr(config, "selection_outline_enabled", None) is None:
            setattr(config, "selection_outline_enabled", True)
        if getattr(config, "selection_outline_width", None) is None:
            setattr(config, "selection_outline_width", 2)
        if getattr(config, "enable_motion_bvh", None) is None:
            setattr(config, "enable_motion_bvh", True)
    except Exception:
        pass
    return config


def _stage_change_path_affects_transform(path: Any) -> bool:
    if not getattr(path, "IsPropertyPath", lambda: False)():
        return True
    _prim_path, separator, property_name = str(path).partition(".")
    if not separator:
        return False
    return property_name == "xformOpOrder" or property_name.startswith("xformOp:")


_STAGE_CHANGE_SYNC_LIVE = "live"
_STAGE_CHANGE_SYNC_OVERLAY = "overlay"
_STAGE_CHANGE_SYNC_RELOAD = "reload"


def _stage_change_path_is_session(path: Any) -> bool:
    path_str = str(path)
    return path_str == _SESSION_ROOT_PATH or path_str.startswith(
        f"{_SESSION_ROOT_PATH}/"
    )


def _build_session_usda(
    resolution: Tuple[int, int],
    include_fallback_dome: bool,
    camera_path: str = _CAMERA_PATH,
    render_product_setting_lines: Tuple[str, ...] = (),
) -> str:
    """Return an inline USDA layer defining OvGear's camera and render product.

    The layer's ``defaultPrim`` is ``OvGearSession`` and every prim is
    nested under ``/OvGearSession/...`` so it can be composed into ovrtx
    via ``add_usd_reference_from_string(..., "/OvGearSession")`` without
    colliding with paths from the user's root layer.

    The camera is authored with an identity transform; per-frame
    intrinsics and world xform are pushed via ``write_attribute`` in
    :meth:`OvRtxRendererAdapter.render_frame`.
    """
    w = int(resolution[0])
    h = int(resolution[1])
    camera_target = camera_path or _CAMERA_PATH
    render_product_device_ids = ", ".join(
        str(device_id) for device_id in _PICK_RENDER_PRODUCT_DEVICE_IDS
    )
    render_product_setting_block = ""
    if render_product_setting_lines:
        render_product_setting_block = "\n" + "\n".join(render_product_setting_lines)
    dome_block = ""
    if include_fallback_dome:
        # DomeLight doubles as the visible environment; ``inputs:color`` set
        # to a dark near-black keeps the viewport's background in the same
        # dark family as the side panels instead of rendering a bright white
        # sky. A DistantLight carries the scene-illumination budget so prims
        # stay lit when the dome's emission is this low.
        dome_block = (
            '\n'
            '    def Scope "Lights"\n'
            '    {\n'
            '        def DomeLight "FallbackDome"\n'
            '        {\n'
            '            color3f inputs:color = (0.010, 0.011, 0.014)\n'
            '            float inputs:intensity = 2500\n'
            '        }\n'
            # Key light rotated ~30° yaw, ~-45° pitch (upper-right of the
            # default +Z camera) so prims get a three-quarter key without
            # the light disc intersecting the camera's frustum. angle=0
            # keeps the light rendered as a pure directional so no sun
            # disc appears in the dark sky.
            '        def DistantLight "FallbackKey"\n'
            '        {\n'
            '            float inputs:intensity = 3000\n'
            '            float inputs:angle = 0.0\n'
            '            matrix4d xformOp:transform = ( (0.866, 0, -0.5, 0), (-0.354, 0.707, -0.612, 0), (0.354, 0.707, 0.612, 0), (0, 0, 0, 1) )\n'
            '            uniform token[] xformOpOrder = ["xformOp:transform"]\n'
            '        }\n'
            '    }\n'
        )
    return f"""#usda 1.0
(
    defaultPrim = "OvGearSession"
)

def Scope "OvGearSession"
{{
    def Scope "Cameras"
    {{
        def Camera "Main" (
            prepend apiSchemas = ["OmniRtxCameraAutoExposureAPI_1", "OmniRtxCameraExposureAPI_1"]
        )
        {{
            float focalLength = 18
            float horizontalAperture = 20.955
            float verticalAperture = 15.2908
            float2 clippingRange = (0.01, 10000)
            float exposure:responsivity = 1.1026709
            float exposure:time = 0.02
            float fStop = 0
            bool omni:rtx:autoExposure:enabled = 1
            token projection = "perspective"
            matrix4d xformOp:transform = ( (1,0,0,0), (0,1,0,0), (0,0,1,0), (0,0,0,1) )
            uniform token[] xformOpOrder = ["xformOp:transform"]
        }}
    }}

    def Scope "Render"
    {{
        def RenderProduct "Viewport"
        {{
            rel camera = <{camera_target}>
            rel orderedVars = </OvGearSession/Render/Vars/LdrColor>
            uniform uint[] deviceIds = [{render_product_device_ids}]
            uniform int2 resolution = ({w}, {h})
{render_product_setting_block}
        }}

        def Scope "Vars"
        {{
            def RenderVar "LdrColor"
            {{
                uniform string sourceName = "{_LDR_VAR_NAME}"
            }}
        }}
    }}{dome_block}
}}
"""


def _usda_string_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _usda_value_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, str):
        return _usda_string_literal(value)
    try:
        if isinstance(value, np.generic):
            value = value.item()
    except Exception:
        pass
    if isinstance(value, (int, float)):
        return repr(value)
    try:
        values = tuple(value)
    except TypeError:
        return _usda_string_literal(str(value))
    return "(" + ", ".join(_usda_value_literal(item) for item in values) + ")"


def _render_setting_usda_line(attr: Any) -> str | None:
    try:
        name = attr.GetName()
        type_name = str(attr.GetTypeName())
        value = attr.Get()
    except Exception:
        return None
    if value is None:
        return None
    return f"            {type_name} {name} = {_usda_value_literal(value)}"


def _stage_has_any_light(stage: Any) -> bool:
    """True if any user-scene ``UsdLux.LightAPI`` prim exists on the stage."""
    # Local import so this module imports cleanly when pxr is not
    # available (e.g., during `import ovrtx_renderer_adapter` probing).
    from pxr import UsdLux
    try:
        session_layer = stage.GetSessionLayer()
    except Exception:
        session_layer = None
    for prim in stage.TraverseAll():
        prim_path = str(prim.GetPath())
        if prim_path == _SESSION_ROOT_PATH or prim_path.startswith(
            f"{_SESSION_ROOT_PATH}/"
        ):
            continue
        if prim.HasAPI(UsdLux.LightAPI):
            try:
                prim_stack = tuple(prim.GetPrimStack())
            except Exception:
                prim_stack = ()
            if not prim_stack:
                return True
            for spec in prim_stack:
                if session_layer is not None and spec.layer == session_layer:
                    continue
                return True
    return False


def _view_to_ovrtx_transform(view_matrix: np.ndarray) -> np.ndarray:
    """Convert a GL-convention view matrix to a USD row-vector world matrix.

    :class:`ovui_widgets.viewport.camera_controller.CameraController` produces
    a GL view matrix (column-vector math, translation in column 3).
    The camera world transform is ``inverse(view)``, still in GL form;
    ovrtx's ``omni:xform`` expects USD row-vector form (translation in
    row 3), so we transpose on the way out. Returns an ``(1, 4, 4)``
    C-contiguous float64 array ready for ``write_attribute`` —
    ``ovrtx_write_attribute`` rejects non-compact strides from numpy's
    transpose view, so we materialize the transpose into a fresh buffer.
    """
    view_np = np.asarray(view_matrix, dtype=np.float64)
    if view_np.shape != (4, 4):
        raise ValueError(f"view_matrix must be 4x4, got {view_np.shape}")
    world_gl = np.linalg.inv(view_np)
    # ``ascontiguousarray`` materializes the transpose; without it the
    # stride check in ovrtx_write_attribute rejects the tensor.
    world_usd = np.ascontiguousarray(world_gl.T, dtype=np.float64)
    return world_usd.reshape(1, 4, 4)


class OvRtxRendererAdapter(RendererAdapter):
    """Concrete :class:`RendererAdapter` that delegates to ``ovrtx.Renderer``.

    Requires ``ovrtx`` and a compatible NVIDIA GPU. Module-level
    :data:`AVAILABLE` reports whether the library imported cleanly;
    constructing the adapter on an unavailable system raises
    :class:`RuntimeError`.
    """

    def __init__(
        self,
        render_product_path: str = _RENDER_PRODUCT_PATH,
        camera_path: str = _CAMERA_PATH,
        config: Any = None,
        zero_copy_state: Optional[ZeroCopyState] = None,
    ) -> None:
        if not _probe_ovrtx():
            raise RuntimeError(
                "ovrtx is not available in this environment "
                f"({type(_OVRTX_IMPORT_ERROR).__name__ if _OVRTX_IMPORT_ERROR else 'unknown'}: "
                f"{_OVRTX_IMPORT_ERROR})"
            )
        # Belt-and-braces: if Application forgot to set the env var
        # before this import, the module-level setdefault already did
        # it; re-assert for safety in case a caller cleared it.
        os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")

        config = _config_with_selection_outline_enabled(config)
        self._renderer = (
            _ovrtx.Renderer(config) if config is not None else _ovrtx.Renderer()
        )
        # ovrtx pick-query coordinate convention changed at 0.4.0 (pixel ints
        # -> normalized [0, 1] NDC); record the version to dispatch correctly.
        self._ovrtx_version = _version_tuple(getattr(_ovrtx, "__version__", "unknown"))
        self._default_render_product_path = render_product_path
        self._default_camera_path = camera_path
        self._render_product_path = render_product_path
        self._camera_path = camera_path

        self._stage: Any = None
        self._usd_handle: Any = None
        self._session_handle: Any = None
        self._live_resync_handles: list[Any] = []
        # Retryable native cleanup/restoration ownership.  The two legacy
        # lists remain derived audit views; the typed obligations below are
        # authoritative because a snapshot belongs to one exact root.
        self._native_scene_unresolved: bool = False
        self._native_scene_unresolved_error: Optional[BaseException] = None
        self._unremoved_native_handles: list[Any] = []
        self._retained_debt_snapshots: list[str] = []
        self._native_cleanup_obligations: list[_NativeCleanupObligation] = []
        self._current_native_cleanup_diagnostics: dict[
            tuple[str, int], NativeCleanupDiagnostic
        ] = {}
        self._native_restore_obligation: Optional[
            _NativeRestoreObligation
        ] = None
        self._throwable_relationships: list[ThrowableRelationship] = []
        self._dropped_throwable_relationships: int = 0
        # ``_last_resolution`` is the resolution currently committed to
        # ovrtx Fabric via ``_build_session_usda`` — not necessarily the
        # latest resolution requested by the viewport widget. The debounce
        # logic in ``render_frame`` gates updates.
        self._last_resolution: Tuple[int, int] = _DEFAULT_RESOLUTION
        self._pending_resolution: Tuple[int, int] = _DEFAULT_RESOLUTION
        self._last_render_product_resolution: Optional[Tuple[int, int]] = None
        self._last_pushed_camera_intrinsics: Optional[tuple[str, float, float, float]] = None
        self._dt_clock: float = time.monotonic()
        # Clock injection point — tests override to drive the debounce
        # timers deterministically without real wall-clock waits.
        self._clock: Callable[[], float] = time.monotonic
        # ``-inf`` so the very first size mismatch after construction
        # applies immediately (no spurious "actively resizing" state).
        self._last_big_delta_time: float = -math.inf
        self._last_reinject_time: float = -math.inf
        self._selected_paths: List[str] = []
        self._selection_outline_previous_paths: set[str] = set()
        self._selection_outline_styles_configured: bool = False
        self._selection_outline_style_calls: int = 0
        self._selection_outline_attribute_writes: int = 0
        self._selection_outline_generation: int = 0
        self._selection_outline_last_write: dict[str, Any] = {}
        # FIFO of in-flight ovrtx pick queries that we have already
        # enqueued and are waiting to drain on a subsequent frame. Each
        # entry is ``[seq, kind, name, cb_or_None, cancel_reason,
        # cached_hits]``. ``cancel_pick`` nulls the callback in-place
        # rather than removing the entry — ovrtx still surfaces a result
        # for the canceled query on the next frame, so the slot must be
        # drained before a replacement query's callback can fire. Rapid
        # same-name replacement is special-cased because ovrtx 0.3 may
        # collapse same-RenderProduct picks and surface the latest hit
        # while the superseded FIFO slot is at the head.
        self._in_flight_pick_queries: Deque[list] = collections.deque()
        self._pick_seq: int = 0
        self._pick_enqueue_count: int = 0
        self._pick_result_count: int = 0
        self._last_pick_pixel_rect: Optional[Tuple[int, int, int, int]] = None
        self._last_pick_path: Optional[str] = None
        self._last_pick_world_point: Optional[Tuple[float, float, float]] = None
        # Populated when we must export an anonymous root layer to disk
        # so ``open_usd`` can resolve it.
        self._owned_tmp_path: Optional[str] = None

        # Whether the scene's root layer already carries its own lights
        # — drives whether we inject a fallback dome into ovrtx.
        self._scene_has_lights: bool = False
        # strata#16 tier-2: shared state coordinating CUDA-mapped LdrColor
        # extraction with the ImageBridge's GPU ingest probe. None = tier-1
        # only; otherwise renderer follows state.gpu_pending and returns a
        # GpuFrame for direct set_bytes_data_from_gpu push.
        self._zero_copy_state: Optional[ZeroCopyState] = zero_copy_state
        # Depth-one LdrColor overlap: present frame N-1 while the GPU renders
        # frame N (see ``_ldr_overlap`` module docs). OFF by default so
        # ``render_frame`` keeps its historical synchronous contract for
        # every caller; the continuous viewport frame loop opts in via
        # :meth:`set_ldr_overlap_enabled` (and OVGEAR_LDR_OVERLAP=0 vetoes).
        self._ldr_overlap: Optional[LdrOverlapState] = None
        # Optional ovstream livestream tap (strata#17). ``None`` unless
        # the ``OVGEAR_LIVESTREAM=1`` environment variable is set AND
        # ``ovstream`` is importable. When active, ``_extract_ldr_color``
        # tees the CUDA-mapped LdrColor buffer to NVENC zero-copy before
        # handing off to the UI consumer.
        #
        # Note (Codex blocker 5): the env check must run BEFORE importing
        # ``_livestream_tap`` so that the default-off path is byte-identical
        # to pre-PR import-graph terms. Importing ``_livestream_tap`` only
        # when the env flag is set keeps that promise.
        #
        # When OMNIUI_HEADLESS=1 the full-UI stream is owned by the headless
        # frame export pipeline (Application._setup_headless_export).
        # Suppress this renderer-level tap so it does not race for port 49100.
        _headless_ui = os.environ.get("OMNIUI_HEADLESS", "").strip() == "1"
        if _livestream_env_enabled() and not _headless_ui:
            from ovui_data_adapters.openusd._livestream_tap import LivestreamTap
            self._livestream = LivestreamTap.maybe_create()
        else:
            self._livestream = None
        self._livestream_error_logged = False
        # Reusable host buffer for the livestream D2H copy — sized lazily
        # to match the current render product resolution.
        self._livestream_host_buf: Optional[np.ndarray] = None
        self._point_cloud_requests: dict[str, PointCloudRequest] = {}
        self._latest_point_cloud_frames: dict[tuple[str, str], PointCloudFrame] = {}
        self._render_var_output_requests: dict[str, RenderVarOutputRequest] = {}
        self._latest_render_var_output_frames: dict[
            tuple[str, str, str],
            RenderVarOutputFrame,
        ] = {}

    def set_zero_copy_state(self, state: Optional[ZeroCopyState]) -> None:
        """Share zero-copy coordination state with the viewport bridge."""
        self._zero_copy_state = state

    # ── Depth-one LdrColor overlap: ownership and presentation state ──

    def _release_retained_output(self) -> None:
        """Release the retained step result and presentation cache.

        MUST run immediately before every ownership-invalidating native
        mutation (layer add/remove, root open/reload, renderer reset,
        product switch, teardown), after any cheap early-return guard of the
        enclosing boundary function. An ovrtx step-result container holds
        native output handles; letting one live across a native mutation is
        undefined (measured consequences range from stale mappings to
        renderer deadlock). Idempotent and cheap when nothing is retained.

        The static ownership audit verifies both the call-site coverage and
        the ordering of this call inside every boundary function.
        """
        overlap = getattr(self, "_ldr_overlap", None)
        if overlap is not None:
            overlap.release(clear_presentation=True)

    @property
    def presented_camera_snapshot(self) -> Optional[CameraSnapshot]:
        """Complete camera state of the image returned by ``render_frame``.

        The viewport uses this to drive scene-overlay (gizmo/outline
        context) matrices so overlays always match the visible image, which
        under overlap is one frame older than the just-submitted camera.
        ``None`` when the overlap is disabled or nothing has been presented;
        callers must then fall back to the matrices they submitted (which
        are identical to the presented ones on the synchronous path).
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

    @property
    def livestream(self) -> Any:
        """The optional livestream tap, or ``None`` when disabled.

        Step 1.7's status overlay polls this from the viewport widget
        (read-only). Tier-2 / Tier-3 work will reuse the same accessor
        — keep it stable.
        """
        return self._livestream

    @property
    def supports_live_local_transform(self) -> bool:
        """Whether ovrtx can accept renderer-only local transform previews."""
        renderer = getattr(self, "_renderer", None)
        writer = getattr(renderer, "write_attribute", None)
        semantic = getattr(getattr(_ovrtx, "Semantic", None), "XFORM_MAT4x4", None)
        return callable(writer) and semantic is not None

    def get_active_camera_path(self) -> Optional[str]:
        """Return the camera prim path selected by the viewport."""
        return self._camera_path

    def set_active_camera_path(self, path: Optional[str]) -> bool:
        """Select the viewport camera prim used to derive per-frame matrices.

        ``None`` or an empty path restores the constructor fallback. The
        method rejects obvious non-prim paths and leaves the previous camera
        active in that case.
        """
        fallback = getattr(self, "_default_camera_path", _CAMERA_PATH)
        next_path = _normalize_active_prim_path(path, fallback)
        if next_path is None:
            return False
        if next_path == self._camera_path:
            return True
        self._camera_path = next_path
        if getattr(self, "_stage", None) is not None:
            self._reset_render_timing_state()
        return True

    def get_active_render_product_path(self) -> Optional[str]:
        """Return the render product path requested from ovrtx frames."""
        return self._render_product_path

    def list_point_cloud_outputs(
        self,
        render_product_path: Optional[str] = None,
    ) -> PointCloudOutputCatalog:
        """Return PointCloud-capable RenderProduct descriptors from the loaded USD stage."""

        stage = getattr(self, "_stage", None)
        if stage is None:
            return PointCloudOutputCatalog()
        try:
            product_prims = _point_cloud_product_prims(stage, render_product_path)
        except (ImportError, RuntimeError):
            return PointCloudOutputCatalog(
                active_render_product_path=self.get_active_render_product_path()
            )
        descriptors: list[PointCloudOutputDescriptor] = []
        for prim in product_prims:
            try:
                product_path = str(prim.GetPath())
                product = _usd_render_product(prim)
                for var_path in _point_cloud_ordered_var_targets(product):
                    descriptor = _point_cloud_output_descriptor(
                        stage,
                        product,
                        product_path,
                        var_path,
                    )
                    if descriptor is not None:
                        descriptors.append(descriptor)
            except Exception:
                continue
        return PointCloudOutputCatalog(
            outputs=tuple(descriptors),
            active_render_product_path=self.get_active_render_product_path(),
        )

    def list_render_var_outputs(
        self,
        render_product_path: Optional[str] = None,
    ) -> RenderVarOutputCatalog:
        """Return non-LDR RenderVar output descriptors from the loaded USD stage."""

        stage = getattr(self, "_stage", None)
        if stage is None:
            return RenderVarOutputCatalog()
        try:
            product_prims = _render_var_product_prims(stage, render_product_path)
        except (ImportError, RuntimeError):
            return RenderVarOutputCatalog(
                active_render_product_path=self.get_active_render_product_path()
            )
        descriptors: list[RenderVarOutputDescriptor] = []
        catalog_warnings: list[RenderVarWarning] = []
        for prim in product_prims:
            try:
                product_path = str(prim.GetPath())
                product = _usd_render_product(prim)
                var_targets = _render_var_ordered_var_targets(product)
                if not var_targets:
                    catalog_warnings.append(_render_var_warning(
                        "missing_output",
                        f"RenderProduct {product_path} has no ordered RenderVars.",
                    ))
                    continue
                for var_path in var_targets:
                    try:
                        descriptor = _render_var_output_descriptor(
                            stage,
                            product,
                            product_path,
                            var_path,
                        )
                    except Exception:
                        continue
                    if descriptor is not None:
                        descriptors.append(descriptor)
            except Exception:
                continue
        return RenderVarOutputCatalog(
            outputs=tuple(descriptors),
            active_render_product_path=self.get_active_render_product_path(),
            warnings=tuple(catalog_warnings),
        )

    def list_render_settings(
        self,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingsCatalog:
        """Return public RenderProduct schema settings from the loaded USD stage."""

        stage = getattr(self, "_stage", None)
        active_path = str(render_product_path or self.get_active_render_product_path() or "")
        if stage is None or not active_path:
            return RenderSettingsCatalog(active_render_product_path=active_path)
        try:
            prim = _render_settings_product_prim(stage, active_path)
        except (ImportError, RuntimeError):
            return RenderSettingsCatalog(active_render_product_path=active_path)
        if prim is None:
            return RenderSettingsCatalog(active_render_product_path=active_path)

        product_path = str(prim.GetPath())
        settings: list[RenderSettingDescriptor] = []
        catalog_warnings: list[RenderSettingWarning] = []
        group_metadata: dict[str, dict[str, Any]] = {}
        public_attr_names: set[str] = set()
        for attr in prim.GetAttributes():
            try:
                attr_name = str(attr.GetName())
                if _render_setting_public_namespace(attr_name) is not None:
                    public_attr_names.add(attr_name)
            except Exception:
                attr_name = "<unknown>"
            try:
                descriptor = _render_setting_descriptor(product_path, attr)
            except Exception:
                catalog_warnings.append(_render_setting_warning(
                    "setting_failed",
                    f"RenderProduct setting {attr_name!r} could not be described.",
                ))
                continue
            if descriptor is None:
                continue
            settings.append(descriptor)
            metadata = _render_setting_metadata(attr)
            existing_group = group_metadata.setdefault(
                descriptor.group_id,
                {"namespace": descriptor.namespace},
            )
            for key, value in metadata.items():
                if key not in existing_group or key in {
                    "group_order",
                    "groupOrder",
                    "group_label",
                    "groupLabel",
                    "group_description",
                    "groupDescription",
                }:
                    existing_group[key] = value

        for spec in _RENDER_SETTINGS_BUILTIN_SPECS:
            attr_name = str(spec.get("attr_name") or "")
            if not attr_name or attr_name in public_attr_names:
                continue
            descriptor = _render_setting_builtin_descriptor(product_path, spec)
            if descriptor is None:
                continue
            settings.append(descriptor)
            public_attr_names.add(attr_name)
            metadata = _render_setting_builtin_metadata(spec)
            existing_group = group_metadata.setdefault(
                descriptor.group_id,
                {"namespace": descriptor.namespace},
            )
            for key, value in metadata.items():
                if key not in existing_group or key in {
                    "group_order",
                    "groupOrder",
                    "group_label",
                    "groupLabel",
                    "group_description",
                    "groupDescription",
                }:
                    existing_group[key] = value

        settings.sort(key=lambda item: (item.group_id, item.order, item.label, item.setting_id))
        groups = _render_settings_group_descriptors(settings, group_metadata)
        providers: tuple[RenderSettingsProviderDescriptor, ...] = ()
        if settings:
            providers = (
                RenderSettingsProviderDescriptor(
                    provider_id=_RENDER_SETTINGS_PROVIDER_ID,
                    display_name=_RENDER_SETTINGS_PROVIDER_LABEL,
                    api_version="1",
                    capabilities=("render_settings_catalog", "render_settings_value_state"),
                    isolation_key=product_path,
                ),
            )
        return RenderSettingsCatalog(
            active_render_product_path=product_path,
            active_render_product_label=str(prim.GetName() or product_path),
            providers=providers,
            groups=groups,
            settings=tuple(settings),
            revision=f"{product_path}:{len(settings)}",
            warnings=tuple(catalog_warnings),
        )

    def read_render_setting(
        self,
        setting_id: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingValueState | None:
        """Return the current value state for a public RenderProduct setting."""

        descriptor = _render_setting_for_id(
            self.list_render_settings(render_product_path),
            setting_id,
        )
        return None if descriptor is None else descriptor.value_state

    def validate_render_setting(
        self,
        setting_id: str,
        value: Any,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingValidationResult:
        """Validate and normalize a public RenderProduct setting value."""

        stage = getattr(self, "_stage", None)
        active_path = str(render_product_path or self.get_active_render_product_path() or "")
        if stage is None or not active_path:
            return _render_setting_reject_validation(
                setting_id,
                "No active RenderProduct is available.",
                "missing_render_product",
            )
        catalog = self.list_render_settings(active_path)
        descriptor = _render_setting_for_id(catalog, setting_id)
        if descriptor is None:
            return _render_setting_reject_validation(
                setting_id,
                "Render setting is not available for this RenderProduct.",
                "unknown_setting",
            )
        if not descriptor.enabled or descriptor.disabled_reason:
            return _render_setting_reject_validation(
                descriptor.setting_id,
                descriptor.disabled_reason or "Render setting is disabled.",
                "setting_disabled",
            )
        if descriptor.value_type is RenderSettingValueType.UNKNOWN:
            return _render_setting_reject_validation(
                descriptor.setting_id,
                "Render setting value type is not supported.",
                "unsupported_type",
            )
        try:
            normalized = _render_setting_coerce_value(descriptor, value)
        except (TypeError, ValueError) as exc:
            return _render_setting_reject_validation(
                descriptor.setting_id,
                str(exc),
                "invalid_value",
            )
        ok, message, code = _render_setting_value_within_constraints(
            descriptor,
            normalized,
        )
        if not ok:
            return _render_setting_reject_validation(
                descriptor.setting_id,
                message,
                code,
            )
        return RenderSettingValidationResult.accepted_result(
            setting_id=descriptor.setting_id,
            normalized_value=normalized,
            requirement=descriptor.requirement,
            message="Render setting value is valid.",
        )

    def apply_render_setting(
        self,
        setting_id: str,
        value: Any,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingApplyResult:
        """Validate then author a public RenderProduct setting value."""

        validation = self.validate_render_setting(
            setting_id,
            value,
            render_product_path=render_product_path,
        )
        if not validation.accepted:
            return _render_setting_reject_apply(
                validation.setting_id or setting_id,
                validation.message or "Render setting validation failed.",
                validation.warning_code or "validation_failed",
            )
        stage = getattr(self, "_stage", None)
        descriptor = _render_setting_for_id(
            self.list_render_settings(render_product_path),
            validation.setting_id,
        )
        if stage is None or descriptor is None:
            return _render_setting_reject_apply(
                validation.setting_id,
                "Render setting is not available for apply.",
                "unknown_setting",
            )
        previous_edit_target = None
        target_layer = _render_setting_edit_target_layer(stage, descriptor)
        try:
            if target_layer is not None:
                previous_edit_target = stage.GetEditTarget()
                stage.SetEditTarget(target_layer)
            attr = _render_setting_attr_for_descriptor(stage, descriptor, create=True)
            if attr is None:
                return _render_setting_reject_apply(
                    descriptor.setting_id,
                    "Render setting attribute is not available for apply.",
                    "unsupported",
                )
            try:
                previous_authored = bool(attr.HasAuthoredValue())
            except Exception:
                previous_authored = False
            try:
                previous_value = attr.Get()
            except Exception:
                previous_value = None
            try:
                _render_setting_set_attr(attr, descriptor, validation.normalized_value)
                self._write_render_setting_to_ovrtx(
                    descriptor,
                    validation.normalized_value,
                )
            except Exception as exc:
                try:
                    if previous_authored:
                        attr.Set(previous_value)
                    else:
                        attr.Clear()
                except Exception:
                    pass
                return _render_setting_reject_apply(
                    descriptor.setting_id,
                    f"Render setting apply failed: {exc}",
                    "apply_failed",
                )
        finally:
            if previous_edit_target is not None:
                try:
                    stage.SetEditTarget(previous_edit_target)
                except Exception:
                    pass
        value_state = self.read_render_setting(
            descriptor.setting_id,
            render_product_path=descriptor.metadata.get("render_product_path"),
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
            message="Render setting applied.",
        )

    def reset_render_setting(
        self,
        setting_id: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingResetResult:
        """Clear the authored opinion for a public RenderProduct setting."""

        stage = getattr(self, "_stage", None)
        active_path = str(render_product_path or self.get_active_render_product_path() or "")
        if stage is None or not active_path:
            return _render_setting_reject_reset(
                setting_id,
                "No active RenderProduct is available.",
                "missing_render_product",
            )
        descriptor = _render_setting_for_id(
            self.list_render_settings(active_path),
            setting_id,
        )
        if descriptor is None:
            return _render_setting_reject_reset(
                setting_id,
                "Render setting is not available for this RenderProduct.",
                "unknown_setting",
            )
        if not descriptor.enabled or descriptor.disabled_reason:
            return _render_setting_reject_reset(
                descriptor.setting_id,
                descriptor.disabled_reason or "Render setting is disabled.",
                "setting_disabled",
            )
        previous_edit_target = None
        target_layer = _render_setting_edit_target_layer(stage, descriptor)
        try:
            if target_layer is not None:
                previous_edit_target = stage.GetEditTarget()
                stage.SetEditTarget(target_layer)
            attr = _render_setting_attr_for_descriptor(stage, descriptor)
            if attr is None:
                return _render_setting_reject_reset(
                    descriptor.setting_id,
                    "Render setting attribute is not available for reset.",
                    "unsupported",
                )
            try:
                previous_authored = bool(attr.HasAuthoredValue())
            except Exception:
                previous_authored = False
            try:
                previous_value = attr.Get()
            except Exception:
                previous_value = None
            try:
                _render_setting_clear_attr(attr)
            except Exception as exc:
                return _render_setting_reject_reset(
                    descriptor.setting_id,
                    f"Render setting reset failed: {exc}",
                    "reset_failed",
                )
            value_state = self.read_render_setting(
                descriptor.setting_id,
                render_product_path=descriptor.metadata.get("render_product_path"),
            )
            try:
                if value_state is not None:
                    self._write_render_setting_to_ovrtx(
                        descriptor,
                        value_state.current_value,
                    )
            except Exception as exc:
                try:
                    if previous_authored:
                        attr.Set(previous_value)
                    else:
                        attr.Clear()
                except Exception:
                    pass
                return _render_setting_reject_reset(
                    descriptor.setting_id,
                    f"Render setting reset failed: {exc}",
                    "reset_failed",
                )
        finally:
            if previous_edit_target is not None:
                try:
                    stage.SetEditTarget(previous_edit_target)
                except Exception:
                    pass
        return RenderSettingResetResult.accepted_result(
            setting_id=descriptor.setting_id,
            reset_value=None if value_state is None else value_state.current_value,
            value_state=value_state,
            requirement=descriptor.requirement,
            message="Render setting reset.",
        )

    def set_point_cloud_request(
        self,
        viewport_id: str,
        request: Optional[PointCloudRequest],
    ) -> PointCloudRequestResult:
        """Request PointCloud extraction for one viewport."""

        self._ensure_point_cloud_state()
        viewport_key = str(viewport_id or "")
        if not viewport_key:
            return PointCloudRequestResult.rejected_result(
                "A viewport id is required.",
                warning_code="missing_viewport",
            )
        if request is None:
            self.clear_point_cloud_request(viewport_key)
            return PointCloudRequestResult.accepted_result(
                message="Point-cloud request cleared.",
            )

        render_product_path = str(
            request.render_product_path or self.get_active_render_product_path() or ""
        )
        if not render_product_path:
            return PointCloudRequestResult.rejected_result(
                "A render product path is required.",
                warning_code="missing_render_product",
            )
        active_request = PointCloudRequest(
            viewport_id=viewport_key,
            render_product_path=render_product_path,
            render_var_name=request.render_var_name or "PointCloud",
            requested_channels=request.requested_channels,
            max_points=request.max_points,
            decimation_stride=request.decimation_stride,
            include_validity=request.include_validity,
            color_mode=request.color_mode,
            desired_coordinate_space=request.desired_coordinate_space,
        )
        try:
            catalog = self.list_point_cloud_outputs(render_product_path)
        except Exception:
            return PointCloudRequestResult.rejected_result(
                "Point-cloud outputs could not be queried.",
                warning_code="catalog_failed",
                active_request=active_request,
            )
        descriptor = _point_cloud_output_for_request(catalog, active_request)
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
        previous_request = self._point_cloud_requests.get(viewport_key)
        if (
            previous_request is not None
            and previous_request.render_product_path != active_request.render_product_path
        ):
            self._latest_point_cloud_frames.pop(
                (viewport_key, previous_request.render_product_path),
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
        """Return the latest cached PointCloud frame for one viewport."""

        self._ensure_point_cloud_state()
        viewport_key = str(viewport_id or "")
        if not viewport_key:
            return None
        if render_product_path:
            return self._latest_point_cloud_frames.get(
                (viewport_key, str(render_product_path))
            )
        request = self._point_cloud_requests.get(viewport_key)
        if request is not None:
            return self._latest_point_cloud_frames.get(
                (viewport_key, request.render_product_path)
            )
        for (key, _product_path), frame in self._latest_point_cloud_frames.items():
            if key == viewport_key:
                return frame
        return None

    def clear_point_cloud_request(self, viewport_id: str) -> None:
        """Clear one viewport PointCloud request and cached snapshots."""

        self._ensure_point_cloud_state()
        viewport_key = str(viewport_id or "")
        if not viewport_key:
            return None
        self._point_cloud_requests.pop(viewport_key, None)
        for key in list(self._latest_point_cloud_frames):
            if key[0] == viewport_key:
                self._latest_point_cloud_frames.pop(key, None)
        return None

    def set_render_var_output_request(
        self,
        viewport_id: str,
        request: Optional[RenderVarOutputRequest],
    ) -> RenderVarOutputRequestResult:
        """Request non-LDR RenderVar output extraction for one viewport."""

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
                message="RenderVar output request cleared.",
            )

        render_product_path = str(
            request.render_product_path or self.get_active_render_product_path() or ""
        )
        if not render_product_path:
            return RenderVarOutputRequestResult.rejected_result(
                "A render product path is required.",
                warning_code="missing_render_product",
            )
        active_request = RenderVarOutputRequest(
            viewport_id=viewport_key,
            render_product_path=render_product_path,
            output_id=request.output_id,
            render_var_name=request.render_var_name,
            preset=request.preset,
            enable_probe=request.enable_probe,
            options=request.options,
        )
        try:
            catalog = self.list_render_var_outputs(render_product_path)
        except Exception:
            return RenderVarOutputRequestResult.rejected_result(
                "RenderVar output catalog could not be queried.",
                warning_code="catalog_failed",
                active_request=active_request,
            )
        descriptor = _render_var_output_for_request(catalog, active_request)
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
        previous_request = self._render_var_output_requests.get(viewport_key)
        if previous_request is not None:
            previous_key = (
                viewport_key,
                previous_request.render_product_path,
                previous_request.output_id,
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
        """Return the latest cached RenderVar output frame for one viewport."""

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
        for (key, product_path, _output_id), frame in (
            self._latest_render_var_output_frames.items()
        ):
            if key == viewport_key and (
                not render_product_path or product_path == str(render_product_path)
            ):
                return frame
        return None

    def clear_render_var_output_request(self, viewport_id: str) -> None:
        """Clear one viewport RenderVar output request and cached snapshots."""

        self._ensure_render_var_output_state()
        viewport_key = str(viewport_id or "")
        if not viewport_key:
            return None
        self._render_var_output_requests.pop(viewport_key, None)
        for key in list(self._latest_render_var_output_frames):
            if key[0] == viewport_key:
                self._latest_render_var_output_frames.pop(key, None)
        return None

    def set_active_render_product_path(self, path: Optional[str]) -> bool:
        """Select the render product path passed to ``renderer.step``.

        ``None`` or an empty path restores the constructor fallback. The
        selected product is expected to exist in the loaded scene or in the
        adapter's session layer; missing products fail closed to a black frame
        through the existing render path.
        """
        fallback = getattr(self, "_default_render_product_path", _RENDER_PRODUCT_PATH)
        next_path = _normalize_active_prim_path(path, fallback)
        if next_path is None:
            return False
        if next_path == self._render_product_path:
            return True
        # Ownership: the retained step result references the OUTGOING
        # product; release it before the switch re-authors native state.
        self._release_retained_output()
        self._render_product_path = next_path
        self._sync_active_selector_state()
        return True

    def activate_render_target(
        self,
        target_id: Optional[str] = None,
        render_product_path: Optional[str] = None,
    ) -> RenderTargetActivationResult:
        """Activate a render target and report the normalized outcome."""

        current_path = self.get_active_render_product_path()
        if getattr(self, "_renderer", None) is None:
            return RenderTargetActivationResult.rejected_result(
                "Render target activation requires a renderer backend.",
                warning_code="unsupported",
                active_target_id=current_path or "",
                active_render_product_path=current_path or "",
            )

        descriptor = self._resolve_render_target_descriptor(
            target_id=target_id,
            render_product_path=render_product_path,
        )
        requested_path = (
            str(render_product_path).strip()
            if render_product_path is not None
            else ""
        )
        if not requested_path and descriptor is not None:
            requested_path = descriptor.render_product_path
        if not requested_path and target_id is not None:
            requested_path = str(target_id).strip()
        if not requested_path:
            return RenderTargetActivationResult.rejected_result(
                "No render target was provided.",
                warning_code="missing_target",
                active_target_id=current_path or "",
                active_render_product_path=current_path or "",
            )

        fallback = getattr(self, "_default_render_product_path", _RENDER_PRODUCT_PATH)
        normalized_path = _normalize_active_prim_path(requested_path, fallback)
        if normalized_path is None:
            return RenderTargetActivationResult.rejected_result(
                f"Render target path is not a valid prim path: {requested_path}",
                warning_code="unknown_target",
                active_target_id=current_path or "",
                active_render_product_path=current_path or "",
            )

        if descriptor is None and self._catalog_lookup_available():
            if normalized_path != fallback:
                return RenderTargetActivationResult.rejected_result(
                    f"Render target is not known: {normalized_path}",
                    warning_code="unknown_target",
                    active_target_id=current_path or "",
                    active_render_product_path=current_path or "",
                )
        elif descriptor is not None and not descriptor.is_selectable:
            warning_code = (
                descriptor.warnings[0].code
                if descriptor.warnings
                else "disabled_target"
            )
            return RenderTargetActivationResult.rejected_result(
                descriptor.disabled_reason or "Render target is disabled.",
                warning_code=warning_code,
                active_target_id=current_path or "",
                active_render_product_path=current_path or "",
            )

        accepted = self.set_active_render_product_path(normalized_path)
        active_path = self.get_active_render_product_path()
        active_target_id = (
            descriptor.target_id if descriptor is not None else normalized_path
        )
        if accepted or active_path == normalized_path:
            return RenderTargetActivationResult.accepted_result(
                active_target_id=active_target_id,
                active_render_product_path=active_path or normalized_path,
                message="Activated render target.",
            )
        return RenderTargetActivationResult.rejected_result(
            f"Renderer rejected render target: {normalized_path}",
            warning_code="backend_rejected",
            active_target_id=active_path or "",
            active_render_product_path=active_path or "",
        )

    def _catalog_lookup_available(self) -> bool:
        """Return whether the loaded stage can answer render-target catalog queries."""

        return getattr(self, "_stage", None) is not None

    def _resolve_render_target_descriptor(
        self,
        *,
        target_id: Optional[str],
        render_product_path: Optional[str],
    ) -> Any:
        stage = getattr(self, "_stage", None)
        if stage is None:
            return None
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

        catalog = UsdStageAdapter(stage).get_render_target_catalog()
        target_token = str(target_id).strip() if target_id is not None else ""
        product_path = (
            str(render_product_path).strip()
            if render_product_path is not None
            else ""
        )
        for descriptor in catalog.targets:
            if target_token and descriptor.target_id == target_token:
                return descriptor
            if product_path and descriptor.render_product_path == product_path:
                return descriptor
        return None

    def _sync_active_selector_state(self) -> None:
        """Reflect active camera/product changes into loaded renderer state."""
        if (
            getattr(self, "_stage", None) is None
            or getattr(self, "_renderer", None) is None
            or getattr(self, "_usd_handle", None) is None
        ):
            return
        self._reinject_session_layer()
        self._reset_render_timing_state()

    def _uses_owned_camera(self) -> bool:
        return self._camera_path == getattr(self, "_default_camera_path", _CAMERA_PATH)

    def _uses_owned_render_product(self) -> bool:
        return self._render_product_path == getattr(
            self, "_default_render_product_path", _RENDER_PRODUCT_PATH
        )

    def _runtime_camera_path(self) -> str:
        """Return the camera prim the active render product can actually use."""
        default_camera = getattr(self, "_default_camera_path", _CAMERA_PATH)
        if self._uses_owned_render_product():
            return default_camera
        return self._camera_path

    def _reset_render_timing_state(self) -> None:
        self._dt_clock = time.monotonic()
        self._last_big_delta_time = -math.inf
        self._last_reinject_time = -math.inf
        self._last_pushed_camera_intrinsics = None

    # ── Stage loading ──

    def supports_in_place_stage_swap(self) -> bool:
        """``load_stage`` transitions this renderer between stages in place.

        The full PREPARE → NATIVE TRIAL → COMMIT IDENTITY → RECONCILE OLD
        transaction is designed to be called repeatedly on the SAME renderer
        to swap the loaded stage atomically (complete-old-or-complete-new,
        with single-root rollback on a failed trial). So the application can
        reuse this attached renderer for a document replacement rather than
        constructing a second ovrtx renderer alongside it.
        """
        return True

    def is_stage_current(self, stage: Any) -> Optional[bool]:
        """Truthful logical-stage identity, including throwing commits."""
        return getattr(self, "_stage", None) is stage

    def _ensure_native_cleanup_tracking(self) -> None:
        """Initialize cleanup state for constructor-bypassing test adapters."""
        if not hasattr(self, "_native_cleanup_obligations"):
            self._native_cleanup_obligations = []
        if not hasattr(self, "_current_native_cleanup_diagnostics"):
            self._current_native_cleanup_diagnostics = {}
        if not hasattr(self, "_native_restore_obligation"):
            self._native_restore_obligation = None
        if not hasattr(self, "_throwable_relationships"):
            self._throwable_relationships = []
        if not hasattr(self, "_dropped_throwable_relationships"):
            self._dropped_throwable_relationships = 0
        if not hasattr(self, "_unremoved_native_handles"):
            self._unremoved_native_handles = []
        if not hasattr(self, "_retained_debt_snapshots"):
            self._retained_debt_snapshots = []
        if not hasattr(self, "_native_scene_unresolved"):
            self._native_scene_unresolved = False
        if not hasattr(self, "_native_scene_unresolved_error"):
            self._native_scene_unresolved_error = None

    @property
    def native_cleanup_diagnostics(self) -> tuple[NativeCleanupDiagnostic, ...]:
        """Active bounded cleanup diagnostics, retaining throwable identity."""
        self._ensure_native_cleanup_tracking()
        debt = [item.diagnostic for item in self._native_cleanup_obligations]
        current = list(self._current_native_cleanup_diagnostics.values())
        restore = self._native_restore_obligation
        if restore is not None:
            current.append(restore.diagnostic)
        return tuple(debt + current)

    @property
    def throwable_diagnostics(self) -> tuple[ThrowableRelationship, ...]:
        """Bounded exact-primary to exact-secondary relationships."""
        self._ensure_native_cleanup_tracking()
        return tuple(self._throwable_relationships)

    def _retain_secondary_throwable(
        self,
        primary: BaseException,
        secondary: BaseException,
        *,
        label: str,
    ) -> None:
        """Retain identity without adding an object edge to ``primary``."""
        if primary is secondary:
            return
        self._ensure_native_cleanup_tracking()
        relationship = next(
            (
                item
                for item in self._throwable_relationships
                if item.primary is primary
            ),
            None,
        )
        if relationship is None:
            if len(self._throwable_relationships) >= 16:
                del self._throwable_relationships[0]
                self._dropped_throwable_relationships += 1
            relationship = ThrowableRelationship(primary=primary)
            self._throwable_relationships.append(relationship)
        relationship.retain(secondary)
        add_note = getattr(primary, "add_note", None)
        if callable(add_note):
            add_note(
                f"{label}: {secondary!r}; exact secondary retained in "
                "adapter.throwable_diagnostics"
            )

    def _new_native_cleanup_diagnostic(
        self,
        *,
        owner: str,
        handle: Any,
        snapshot: Optional[str],
        origin: str,
        primary: Optional[BaseException],
        error: BaseException,
    ) -> NativeCleanupDiagnostic:
        operation_primary = primary if primary is not None else error
        diagnostic = NativeCleanupDiagnostic(
            owner=owner,
            handle=handle,
            snapshot=snapshot,
            origin=origin,
            primary=operation_primary,
        )
        diagnostic.retain(error)
        if operation_primary is not error:
            self._retain_secondary_throwable(
                operation_primary,
                error,
                label=f"native {owner} cleanup also failed",
            )
        return diagnostic

    def _record_current_native_cleanup_failure(
        self,
        *,
        owner: str,
        handle: Any,
        snapshot: Optional[str],
        origin: str,
        primary: Optional[BaseException],
        error: BaseException,
    ) -> NativeCleanupDiagnostic:
        self._ensure_native_cleanup_tracking()
        key = (owner, id(handle))
        diagnostic = self._current_native_cleanup_diagnostics.get(key)
        if diagnostic is None:
            diagnostic = self._new_native_cleanup_diagnostic(
                owner=owner,
                handle=handle,
                snapshot=snapshot,
                origin=origin,
                primary=primary,
                error=error,
            )
            self._current_native_cleanup_diagnostics[key] = diagnostic
        else:
            diagnostic.retain(error)
            relationship_primary = primary or diagnostic.primary
            if relationship_primary is not error:
                self._retain_secondary_throwable(
                    relationship_primary,
                    error,
                    label=f"native {owner} cleanup retry also failed",
                )
        self._refresh_native_cleanup_state()
        return diagnostic

    def _clear_current_native_cleanup_diagnostic(
        self, owner: str, handle: Any
    ) -> None:
        self._ensure_native_cleanup_tracking()
        diagnostic = self._current_native_cleanup_diagnostics.pop(
            (owner, id(handle)), None
        )
        self._refresh_native_cleanup_state()
        if diagnostic is not None:
            self._clear_throwable_relationship_if_resolved(
                diagnostic.primary
            )

    def _add_native_cleanup_obligation(
        self,
        *,
        owner: str,
        handle: Any,
        snapshot: Optional[str],
        origin: str,
        primary: Optional[BaseException],
        error: BaseException,
    ) -> _NativeCleanupObligation:
        self._ensure_native_cleanup_tracking()
        existing = next(
            (
                item
                for item in self._native_cleanup_obligations
                if item.owner == owner and item.handle is handle
            ),
            None,
        )
        if existing is not None:
            existing.diagnostic.retain(error)
            relationship_primary = primary or existing.diagnostic.primary
            if relationship_primary is not error:
                self._retain_secondary_throwable(
                    relationship_primary,
                    error,
                    label=f"native {owner} cleanup retry also failed",
                )
            self._refresh_native_cleanup_state()
            return existing
        diagnostic = self._new_native_cleanup_diagnostic(
            owner=owner,
            handle=handle,
            snapshot=snapshot,
            origin=origin,
            primary=primary,
            error=error,
        )
        obligation = _NativeCleanupObligation(
            owner=owner,
            handle=handle,
            snapshot=snapshot,
            origin=origin,
            diagnostic=diagnostic,
        )
        self._native_cleanup_obligations.append(obligation)
        self._refresh_native_cleanup_state()
        return obligation

    def _refresh_native_cleanup_state(self) -> None:
        self._ensure_native_cleanup_tracking()
        obligations = list(self._native_cleanup_obligations)
        self._unremoved_native_handles = [
            item.handle for item in obligations if item.handle is not None
        ]
        self._retained_debt_snapshots = list(
            dict.fromkeys(
                item.snapshot for item in obligations if item.snapshot is not None
            )
        )
        diagnostics = [item.diagnostic for item in obligations]
        diagnostics.extend(self._current_native_cleanup_diagnostics.values())
        if self._native_restore_obligation is not None:
            diagnostics.append(self._native_restore_obligation.diagnostic)
        self._native_scene_unresolved = bool(diagnostics)
        self._native_scene_unresolved_error = (
            diagnostics[0].latest_error if diagnostics else None
        )

    def _resolve_native_cleanup_before_load(self) -> None:
        """Admit a new load only after every prior native owner resolves."""
        self._ensure_native_cleanup_tracking()
        if self._native_restore_obligation is not None:
            self._retry_native_scene_restoration()
        self._drain_native_debt()
        self._refresh_native_cleanup_state()
        if self._native_scene_unresolved:
            error = self._native_scene_unresolved_error
            if error is not None:
                raise error
            raise RuntimeError("native scene cleanup remains unresolved")

    def load_stage(self, stage: Any, *, use_live_root_snapshot: bool = False) -> None:
        """Load a USD stage (or file path) into the ovrtx renderer.

        Accepts either a :class:`pxr.Usd.Stage` or a path string. When
        given a Stage with an anonymous root layer, the layer is
        exported to a temp file so ``open_usd`` can resolve it. When
        ``use_live_root_snapshot`` is true, file-backed stages also load
        through a temporary copy of the live root layer. That preserves
        unsaved Create-menu edits without writing the user's USD file.

        After this call, the ovrtx renderer holds the user's scene
        composed with an inline OvGear session layer (camera, render
        product, LDR var, optional fallback dome). The pxr stage's
        session layer carries an equivalent structure so the rest of
        OvGear (Stage Browser, Property Inspector) sees OvGear's
        scaffolding prims too.
        """
        from pxr import Usd  # lazy — module must import without pxr

        # A second document must never be published beside unresolved native
        # composition from an earlier operation.  This retry happens before
        # prospective USD scaffolding or snapshot creation.
        self._resolve_native_cleanup_before_load()

        # ── Phase 1: PREPARE ── resolve the prospective pxr stage plus the
        # best root-open payload for ovrtx WITHOUT touching any current
        # renderer/document ownership. File-backed stages should use file
        # loading so relative asset paths keep their resolver context;
        # anonymous stages can go straight to ovrtx 0.3's inline root loader
        # when available; older renderers still get an exported tempfile.
        # A failure anywhere in this phase — any ``BaseException``,
        # including ``KeyboardInterrupt`` — must leave the previous stage,
        # renderer content, retained output, pending picks, and owned
        # snapshot exactly as they were, and remove every partially created
        # prospective resource.
        root_usda: Optional[str] = None
        prospective_tmp_path: Optional[str] = None
        try:
            if isinstance(stage, str):
                path = stage
                prospective_stage = Usd.Stage.Open(path)
                root_layer = prospective_stage.GetRootLayer()
                # ``Usd.Stage.Open`` can return a still-dirty cached layer
                # (the same document was edited and reopened without
                # saving). ovrtx must render what the stage composes, not
                # the stale file on disk, so a dirty root layer always
                # loads through a live snapshot of the in-memory layer.
                strip_scaffolding = self._root_layer_has_session_scaffolding(
                    root_layer
                )
                if strip_scaffolding or root_layer.dirty:
                    path = self._export_live_root_layer_snapshot(
                        root_layer,
                        strip_session_root=strip_scaffolding,
                    )
                    prospective_tmp_path = path
            elif hasattr(stage, "GetRootLayer"):
                prospective_stage = stage
                root_layer = stage.GetRootLayer()
                strip_session_root = self._root_layer_has_session_scaffolding(
                    root_layer
                )
                if root_layer.anonymous:
                    if getattr(self._renderer, "open_usd_from_string", None) is not None:
                        root_usda = self._export_root_layer_to_string(
                            root_layer,
                            strip_session_root=strip_session_root,
                        )
                        path = None
                    else:
                        # Legacy file-only loaders require a resolvable path.
                        fd, tmp_path = tempfile.mkstemp(
                            suffix=".usda", prefix="ovgear_"
                        )
                        os.close(fd)
                        prospective_tmp_path = tmp_path
                        root_layer.Export(tmp_path)
                        if strip_session_root:
                            self._strip_session_root_from_layer_file(tmp_path)
                        path = tmp_path
                else:
                    # A dirty file-backed root layer means the stage composes
                    # unsaved opinions (e.g. a visibility edit surviving a
                    # reopen through the Sdf layer cache). Loading ovrtx from
                    # ``realPath`` would silently drop those opinions and
                    # desynchronize the viewport from USD/Stage Browser
                    # state, so dirty layers always take the live-snapshot
                    # path.
                    live_root_needed = use_live_root_snapshot or root_layer.dirty
                    if (
                        live_root_needed
                        and getattr(self._renderer, "open_usd_from_string", None) is not None
                        and getattr(self._renderer, "open_usd_from_file", None) is None
                        and getattr(self._renderer, "open_usd", None) is None
                    ):
                        root_usda = self._export_root_layer_to_string(
                            root_layer,
                            strip_session_root=strip_session_root,
                        )
                        path = None
                    elif live_root_needed or strip_session_root:
                        path = self._export_live_root_layer_snapshot(
                            root_layer,
                            strip_session_root=strip_session_root,
                        )
                        prospective_tmp_path = path
                    else:
                        path = root_layer.realPath or root_layer.identifier
            else:
                raise TypeError(
                    f"load_stage expected pxr.Usd.Stage or path str, got {type(stage).__name__}"
                )
        except BaseException:
            if prospective_tmp_path is not None:
                try:
                    os.unlink(prospective_tmp_path)
                except OSError:
                    pass
            raise

        # ── Phase 2: SCAFFOLD ── mirror OvGear's scaffolding into the
        # PROSPECTIVE stage's session layer so other OvGear panels see a
        # consistent camera / render product. These writes touch only the
        # prospective stage (the application discards it wholesale if this
        # load fails); they never touch the current document or root layer.
        #
        # Any failure here — including KeyboardInterrupt/SystemExit — must
        # reclaim the prepared snapshot before it leaks: scaffolding runs
        # AFTER the dirty-root snapshot is written but BEFORE any native
        # handle references it, so the snapshot is this adapter's to reclaim
        # (Codex finding 2).
        try:
            from ovui_data_adapters.openusd._session_authoring import (
                ensure_camera,
                ensure_dome_light,
                ensure_ldr_color_var,
                ensure_render_scope,
            )
            ensure_render_scope(prospective_stage)
            session_camera_path = getattr(
                self, "_default_camera_path", _CAMERA_PATH
            )
            if self._uses_owned_render_product():
                ensure_camera(prospective_stage, session_camera_path)
            ensure_ldr_color_var(prospective_stage, _LDR_VAR_PATH)
            # ensure_dome_light returns None if the stage already has any
            # light — we mirror that into ovrtx so we don't double-light.
            prospective_has_lights = _stage_has_any_light(prospective_stage)
            if not prospective_has_lights:
                ensure_dome_light(prospective_stage, _DOME_LIGHT_PATH)
            prospective_session_usda = _build_session_usda(
                self._last_resolution,
                include_fallback_dome=not prospective_has_lights,
                camera_path=session_camera_path,
                render_product_setting_lines=(
                    self._session_render_product_setting_lines()
                ),
            )
        except BaseException:
            if prospective_tmp_path is not None:
                try:
                    os.unlink(prospective_tmp_path)
                except OSError:
                    pass
            raise

        # ── Phase 2: NATIVE TRIAL ── install the prospective scene in the
        # renderer while the current document state (stage identity, owned
        # snapshot, pending picks) stays untouched. The retained one-frame
        # step output must be released before ANY native mutation — its
        # native handles would dangle — and is regenerated identically by
        # the next render_frame, so releasing it loses no observable state.
        #
        # Two native API shapes exist:
        # * handle-based (``add_usd``): the new root/session compose
        #   ALONGSIDE the old handles; nothing old is destroyed until
        #   commit, and a failed trial simply removes the new handles.
        # * single-root (``open_usd*``): opening a root TEARS DOWN the
        #   renderer's current root and session, so a failed trial rolls
        #   back by re-opening the exact payload the renderer held before
        #   (recorded at the previous successful commit).
        single_root_api = (
            getattr(self._renderer, "open_usd_from_string", None) is not None
            or getattr(self._renderer, "open_usd_from_file", None) is not None
            or getattr(self._renderer, "open_usd", None) is not None
        )
        old_root_handle = self._usd_handle
        old_session_handle = self._session_handle
        old_overlay_handles = list(
            getattr(self, "_live_resync_handles", None) or []
        )
        old_snapshot = self._owned_tmp_path
        # Selection paths, outline bookkeeping, pending picks, the owned
        # snapshot, the stage identity, and the rollback payload are all
        # deliberately NOT touched before the irrevocable commit point —
        # any failure up to that point must leave the complete old state.
        # The retained one-frame step output is the sole exception: it must
        # be released before ANY native mutation (its native handles would
        # dangle), and it is neither durable nor observable — the next
        # render_frame regenerates it identically for whichever scene is
        # current.
        self._release_retained_output()
        new_root_handle = None
        new_session_handle = None
        try:
            new_root_handle = self._open_ovrtx_root(
                path, root_layer_content=root_usda
            )
            new_session_handle = self._add_ovrtx_session_layer(
                prospective_session_usda
            )
        except BaseException as primary:
            # Reclaim every partially installed prospective resource —
            # including on KeyboardInterrupt/SystemExit. A prospective
            # handle that cannot be removed becomes tracked cleanup debt
            # (never silently swallowed), and its snapshot file is retained
            # rather than deleted while a handle still references it (Codex
            # finding 1). For destructive single-root APIs the incoming
            # open already tore the old scene down, so restore it.
            if single_root_api:
                # The destructive prospective root invalidated every old
                # token.  Keep the prospective snapshot until reopening the
                # old root authoritatively neutralizes that native root.
                self._usd_handle = None
                self._session_handle = None
                self._live_resync_handles = []
                self._reclaim_prospective_native(
                    None,
                    new_session_handle,
                    None,
                    primary=primary,
                )
                self._restore_native_scene(
                    primary,
                    need_root=True,
                    need_session=True,
                    need_overlays=bool(old_overlay_handles),
                    prospective_snapshot=prospective_tmp_path,
                )
            else:
                self._reclaim_prospective_native(
                    new_root_handle,
                    new_session_handle,
                    prospective_tmp_path,
                    primary=primary,
                )
            raise

        # ── Phase 4: COMMIT IDENTITY ── the new scene is installed and is
        # the authoritative rendered scene. Adopt it as the current
        # document BEFORE reconciling old native resources, so a
        # reconciliation fault can never produce a mixed IDENTITY: the
        # document is the new stage, and any un-removed old handle is
        # tracked debt (drained by the next teardown/shutdown), never a
        # silently mixed success.
        #
        # Every throwable from here on is chained: the FIRST becomes the
        # propagated primary and each later one is attached, so no
        # BaseException — pending-pick SystemExit included — is ever lost
        # or displaced (Codex finding 3).
        first_fault: Optional[BaseException] = None

        # Drain pending picks from the OUTGOING stage as misses before the
        # swap is visible to render_frame (Codex review of #67). A callback
        # may raise anything, including SystemExit; defer it and keep going.
        try:
            self._dispatch_pending_pick_misses()
        except BaseException as fault:
            first_fault = fault

        self._stage = prospective_stage
        self._usd_handle = new_root_handle
        self._session_handle = new_session_handle
        self._live_resync_handles = []
        # The new snapshot is now the owned snapshot; the OLD snapshot is
        # released by reconciliation once its root handle is gone.
        self._owned_tmp_path = prospective_tmp_path
        # Rollback record: the exact payload the renderer now holds.
        self._root_open_payload = (path, root_usda)
        self._session_layer_usda = prospective_session_usda
        self._scene_has_lights = prospective_has_lights
        # The pre-load gate proved that no earlier obligation remains.  New
        # reconciliation diagnostics below are added only for this commit.
        self._refresh_native_cleanup_state()
        self._mark_selection_outline_state_stale(
            reason="root_reload",
            reset_previous=True,
            reset_styles=True,
        )

        # ── Phase 5: RECONCILE OLD ── remove every old native handle for
        # BOTH API shapes. The old snapshot file is deleted only once its
        # root handle is gone (never delete a file a live handle still
        # references). An un-removable handle is recorded as cleanup debt +
        # unresolved state and chained — never a swallowed failure or a
        # success reported with residual old composition (Codex findings
        # 1 & 4).
        first_fault = self._chain_faults(
            first_fault,
            self._reconcile_old_native(
                old_overlay_handles,
                old_session_handle,
                old_root_handle,
                old_snapshot,
                single_root_api=single_root_api,
                primary=first_fault,
            ),
        )

        # ── Phase 6: COMMIT BOOKKEEPING ── may raise; chain so a late fault
        # never displaces the deferred pick / reconcile throwables.
        try:
            self._author_owned_session_render_product_resolution(
                self._last_resolution
            )
            self._pending_resolution = self._last_resolution
            self._reset_render_timing_state()
        except BaseException as fault:
            first_fault = self._chain_faults(first_fault, fault)

        if first_fault is not None:
            raise first_fault

    def _chain_faults(
        self,
        primary: Optional[BaseException],
        secondary: Optional[BaseException],
    ) -> Optional[BaseException]:
        """Keep the FIRST throwable primary and attach later ones as notes.

        Guarantees no ``BaseException`` (``SystemExit``/``KeyboardInterrupt``
        included) is silently displaced or lost when several faults occur
        across deferred callbacks, reconciliation, and commit bookkeeping.
        """
        if secondary is None:
            return primary
        if primary is None:
            return secondary
        self._retain_secondary_throwable(
            primary,
            secondary,
            label="a later stage-transition step also failed",
        )
        return primary

    def _reconcile_old_native(
        self,
        old_overlays: list,
        old_session: Any,
        old_root: Any,
        old_snapshot: Optional[str],
        *,
        single_root_api: bool = False,
        primary: Optional[BaseException] = None,
    ) -> Optional[BaseException]:
        """Release the OLD native scene after the new scene is committed.

        For the HANDLE-BASED API (``add_usd``) the old overlays, session, and
        root composed ALONGSIDE the new scene and must be explicitly removed;
        any handle that cannot be removed is retained as cleanup debt
        (drained by the next ``_remove_ovrtx_layers``/``shutdown``) and
        surfaced truthfully via ``_native_scene_unresolved``.

        For the SINGLE-ROOT API (``open_usd*``) a destructive incoming open
        may already have TORN DOWN some of the previous composition together
        with the old root. Removal is still ATTEMPTED for every old handle
        (so a still-live layer is genuinely released), but a removal failure
        is treated as BENIGN — the destructive open already released that
        handle — rather than as cleanup debt: re-removing an already-gone
        native layer fails, and that failure must not abort the transition or
        report residual composition. Returns the first REAL removal fault (if
        any) for the caller to chain, so a genuine handle-based reconcile
        failure never reports success with residual old composition.
        """
        self._release_retained_output()
        fault: Optional[BaseException] = None
        # Removal is ATTEMPTED for every old handle so a still-live layer is
        # genuinely released. For the SINGLE-ROOT API a removal failure is
        # BENIGN — the destructive open already released the handle — so it
        # is neither debt nor a propagated fault. For the HANDLE-BASED API a
        # failure is genuine cleanup debt. All native calls stay directly in
        # this boundary body (after the release proof above).
        for handle in list(old_overlays):
            if handle is None or handle is _ROOT_STAGE_SENTINEL:
                continue
            try:
                self._renderer.remove_usd(handle)
            except BaseException as exc:  # noqa: BLE001
                if not single_root_api:
                    self._add_native_cleanup_obligation(
                        owner="old-overlay",
                        handle=handle,
                        snapshot=None,
                        origin="replacement-reconcile",
                        primary=primary,
                        error=exc,
                    )
                    fault = self._chain_faults(fault, exc)
        if old_session is not None and old_session is not _ROOT_STAGE_SENTINEL:
            try:
                self._renderer.remove_usd(old_session)
            except BaseException as exc:  # noqa: BLE001
                if not single_root_api:
                    self._add_native_cleanup_obligation(
                        owner="old-session",
                        handle=old_session,
                        snapshot=None,
                        origin="replacement-reconcile",
                        primary=primary,
                        error=exc,
                    )
                    fault = self._chain_faults(fault, exc)
        root_removed = True
        if old_root is not None and old_root is not _ROOT_STAGE_SENTINEL:
            try:
                self._renderer.remove_usd(old_root)
            except BaseException as exc:  # noqa: BLE001
                if not single_root_api:
                    # Single-root: benign (already released), root_removed
                    # stays True so the old snapshot is freed.
                    root_removed = False
                    self._add_native_cleanup_obligation(
                        owner="old-root",
                        handle=old_root,
                        snapshot=old_snapshot,
                        origin="replacement-reconcile",
                        primary=primary,
                        error=exc,
                    )
                    fault = self._chain_faults(fault, exc)
        # Release the old snapshot ONLY once its root handle is gone and it
        # is not the newly-owned snapshot; otherwise retain it as debt.
        if old_snapshot is not None and old_snapshot != self._owned_tmp_path:
            if root_removed:
                try:
                    os.unlink(old_snapshot)
                except OSError:
                    pass
        self._refresh_native_cleanup_state()
        return fault

    def _reclaim_prospective_native(
        self,
        new_root_handle: Any,
        new_session_handle: Any,
        prospective_tmp_path: Optional[str],
        *,
        primary: BaseException,
    ) -> None:
        """Remove partially installed prospective layers and their snapshot.

        A prospective handle that cannot be removed is recorded as tracked
        cleanup debt + unresolved state (never silently swallowed), and the
        prospective snapshot file is deleted ONLY when the root handle that
        would reference it is gone — a still-referenced file is retained as
        debt for the next teardown/shutdown rather than orphaned under a
        live handle (Codex findings 1 & 7).
        """
        self._release_retained_output()
        # ``None``/sentinel roots reference no discrete file handle, so the
        # snapshot is safe to delete unless a live handle survives removal.
        root_reclaimed = (
            new_root_handle is None or new_root_handle is _ROOT_STAGE_SENTINEL
        )
        for owner, handle in (
            ("prospective-session", new_session_handle),
            ("prospective-root", new_root_handle),
        ):
            if handle is None or handle is _ROOT_STAGE_SENTINEL:
                continue
            try:
                self._renderer.remove_usd(handle)
                if handle is new_root_handle:
                    root_reclaimed = True
            except BaseException as cleanup_error:  # noqa: BLE001
                self._add_native_cleanup_obligation(
                    owner=owner,
                    handle=handle,
                    snapshot=(
                        prospective_tmp_path
                        if handle is new_root_handle
                        else None
                    ),
                    origin="prospective-reclaim",
                    primary=primary,
                    error=cleanup_error,
                )
        if prospective_tmp_path is not None:
            if root_reclaimed:
                try:
                    os.unlink(prospective_tmp_path)
                except OSError:
                    pass
        self._refresh_native_cleanup_state()

    def _drain_native_debt(self) -> None:
        """Retry removing tracked native cleanup debt; free freed snapshots.

        Called by ``_remove_ovrtx_layers`` (next-load teardown) and
        ``shutdown`` so retained debt is reconciled at the next safe point,
        or truthfully carried forward if it still cannot be removed. A
        retained snapshot file is deleted only once every debt handle is
        cleared.
        """
        self._ensure_native_cleanup_tracking()
        if not self._native_cleanup_obligations:
            self._refresh_native_cleanup_state()
            return
        self._release_retained_output()
        renderer = getattr(self, "_renderer", None)
        first_fault: Optional[BaseException] = None
        remaining: list[_NativeCleanupObligation] = []
        resolved_primaries: list[BaseException] = []
        for obligation in list(self._native_cleanup_obligations):
            if obligation.handle is not None:
                if renderer is None:
                    first_fault = self._chain_faults(
                        first_fault, obligation.diagnostic.latest_error
                    )
                    remaining.append(obligation)
                    continue
                try:
                    renderer.remove_usd(obligation.handle)
                except BaseException as error:  # noqa: BLE001
                    obligation.diagnostic.retain(error)
                    self._retain_secondary_throwable(
                        obligation.diagnostic.primary,
                        error,
                        label=(
                            f"native {obligation.owner} cleanup retry also "
                            "failed"
                        ),
                    )
                    first_fault = self._chain_faults(first_fault, error)
                    remaining.append(obligation)
                    continue
                # The native owner is gone.  Set the token to None before a
                # fallible file deletion so a later retry never double-removes.
                obligation.handle = None

            if obligation.snapshot is not None:
                try:
                    os.unlink(obligation.snapshot)
                except FileNotFoundError:
                    pass
                except BaseException as error:  # noqa: BLE001
                    obligation.diagnostic.retain(error)
                    self._retain_secondary_throwable(
                        obligation.diagnostic.primary,
                        error,
                        label=(
                            f"native {obligation.owner} snapshot reclaim also "
                            "failed"
                        ),
                    )
                    first_fault = self._chain_faults(first_fault, error)
                    remaining.append(obligation)
                    continue
                obligation.snapshot = None

            resolved_primaries.append(obligation.diagnostic.primary)

        self._native_cleanup_obligations = remaining
        self._refresh_native_cleanup_state()
        for primary in resolved_primaries:
            self._clear_throwable_relationship_if_resolved(primary)
        if first_fault is not None:
            raise first_fault

    def _restore_native_scene(
        self,
        primary: BaseException,
        *,
        need_root: bool,
        need_session: bool,
        need_overlays: bool,
        keep_existing_root: bool = False,
        keep_existing_session: bool = False,
        prospective_snapshot: Optional[str] = None,
    ) -> bool:
        """Re-install the previous native scene after a failed transition.

        Restores exactly the pieces that were lost: the root (from the
        EXACT payload recorded at the previous successful commit — no new
        files, so the old owned snapshot file and ownership stay
        untouched), the session layer, live-resync overlays (rebuilt from
        the still-current old stage), and the visible selection highlight.
        Selection paths and outline bookkeeping were never cleared.

        If restoration itself fails, the double fault is NOT swallowed:
        the secondary failure is attached to ``primary`` as an exception
        note (preserving the primary's identity and causality), the
        adapter declares an explicit unresolved-native-scene condition
        (``_native_scene_unresolved``), and the handles are cleared so the
        next load or shutdown remains safe.
        """
        self._release_retained_output()
        payload = getattr(self, "_root_open_payload", None)
        session_usda = getattr(self, "_session_layer_usda", None)
        try:
            if need_root and not keep_existing_root:
                if not payload:
                    raise RuntimeError(
                        "no rollback payload recorded for the previous scene"
                    )
                rollback_path, rollback_usda = payload
                self._usd_handle = self._open_ovrtx_root(
                    rollback_path, root_layer_content=rollback_usda
                )
            if need_session and not keep_existing_session:
                if not session_usda:
                    raise RuntimeError(
                        "no session payload recorded for the previous scene"
                    )
                self._session_handle = self._add_ovrtx_session_layer(
                    session_usda
                )
            if need_overlays:
                self._live_resync_handles = []
                if not self._sync_ovrtx_root_snapshot_overlay_from_stage():
                    add_layer = getattr(self._renderer, "add_usd_layer", None)
                    if callable(add_layer):
                        raise RuntimeError(
                            "live-resync overlay restoration failed"
                        )
        except BaseException as secondary:
            self._declare_unresolved_native_scene(
                primary,
                secondary,
                need_root=need_root and self._usd_handle is None,
                need_session=need_session and self._session_handle is None,
                need_overlays=(
                    need_overlays
                    and not bool(getattr(self, "_live_resync_handles", None))
                ),
                prospective_snapshot=prospective_snapshot,
            )
            return False

        if prospective_snapshot is not None:
            try:
                os.unlink(prospective_snapshot)
            except FileNotFoundError:
                pass
            except BaseException as cleanup_error:  # noqa: BLE001
                self._add_native_cleanup_obligation(
                    owner="rollback-snapshot",
                    handle=None,
                    snapshot=prospective_snapshot,
                    origin="rollback-neutralization",
                    primary=primary,
                    error=cleanup_error,
                )
                return False
        prior_restore = self._native_restore_obligation
        self._native_restore_obligation = None
        self._refresh_native_cleanup_state()
        if prior_restore is not None:
            self._clear_throwable_relationship_if_resolved(
                prior_restore.diagnostic.primary
            )
        # Visible selection highlight is cosmetic (the authoritative
        # selection bookkeeping was never touched); reapply best-effort.
        selected = list(getattr(self, "_selected_paths", []) or [])
        if selected:
            try:
                self.set_selection_highlight(selected, force_reapply=True)
            except Exception:
                pass
        return True

    def _retry_native_scene_restoration(self) -> None:
        obligation = self._native_restore_obligation
        if obligation is None:
            return
        self._restore_native_scene(
            obligation.primary,
            need_root=obligation.need_root,
            need_session=obligation.need_session,
            need_overlays=obligation.need_overlays,
            keep_existing_root=not obligation.need_root,
            keep_existing_session=not obligation.need_session,
            prospective_snapshot=obligation.prospective_snapshot,
        )
        if self._native_restore_obligation is not None:
            raise self._native_restore_obligation.diagnostic.latest_error

    def _declare_unresolved_native_scene(
        self,
        primary: BaseException,
        secondary: BaseException,
        *,
        need_root: bool,
        need_session: bool,
        need_overlays: bool,
        prospective_snapshot: Optional[str],
    ) -> None:
        """Truthful double-fault protocol for a failed scene restoration.

        Never swallows the secondary silently: it is attached to the
        primary throwable as an exception note and retained on the adapter
        (``_native_scene_unresolved_error``) beside an explicit
        ``_native_scene_unresolved`` flag. The adapter's document identity
        remains the old stage — which is truthful for every pxr-level
        consumer — while the flag records that the native renderer holds
        no usable root/session until the next successful load. Handles are
        cleared so the next load or shutdown is safe (teardown tolerates
        absent handles; the next load takes the no-old-native path).
        """
        self._ensure_native_cleanup_tracking()
        existing = self._native_restore_obligation
        if existing is None:
            diagnostic = self._new_native_cleanup_diagnostic(
                owner="rollback-native-scene",
                handle=_ROLLBACK_NATIVE_SENTINEL,
                snapshot=prospective_snapshot,
                origin="failed-transition-rollback",
                primary=primary,
                error=secondary,
            )
            self._native_restore_obligation = _NativeRestoreObligation(
                primary=primary,
                need_root=need_root,
                need_session=need_session,
                need_overlays=need_overlays,
                prospective_snapshot=prospective_snapshot,
                diagnostic=diagnostic,
            )
        else:
            existing.need_root = need_root
            existing.need_session = need_session
            existing.need_overlays = need_overlays
            existing.diagnostic.retain(secondary)
            self._retain_secondary_throwable(
                existing.primary,
                secondary,
                label="native scene restoration retry also failed",
            )
        add_note = getattr(primary, "add_note", None)
        if callable(add_note):
            add_note(
                "native scene restoration also failed; exact secondary "
                "retained in adapter.native_cleanup_diagnostics"
            )
        self._refresh_native_cleanup_state()

    def _clear_throwable_relationship_if_resolved(
        self, primary: BaseException
    ) -> None:
        active_primaries = {
            id(diagnostic.primary) for diagnostic in self.native_cleanup_diagnostics
        }
        if id(primary) in active_primaries:
            return
        self._throwable_relationships = [
            item
            for item in self._throwable_relationships
            if item.primary is not primary
        ]

    def _remove_ovrtx_layers(
        self, *, allow_renderer_drop: bool = False
    ) -> None:
        """Remove every native owner or raise while preserving failed ones."""
        self._ensure_native_cleanup_tracking()
        self._release_retained_output()
        first_fault: Optional[BaseException] = None
        try:
            self._drain_native_debt()
        except BaseException as error:  # noqa: BLE001
            first_fault = self._chain_faults(first_fault, error)
        if first_fault is not None:
            # A prior mixed-composition obligation gates teardown of the
            # complete current scene.  Preserve its exact owners for the
            # later retry that first resolves the debt.
            self._refresh_native_cleanup_state()
            raise first_fault
        try:
            self._remove_live_resync_layers()
        except BaseException as error:  # noqa: BLE001
            first_fault = self._chain_faults(first_fault, error)

        session_handle = getattr(self, "_session_handle", None)
        if session_handle is None:
            self._clear_current_native_cleanup_diagnostic(
                "current-session-install", _SESSION_INSTALL_SENTINEL
            )
        if session_handle is not None:
            try:
                self._renderer.remove_usd(session_handle)
            except BaseException as error:  # noqa: BLE001
                self._record_current_native_cleanup_failure(
                    owner="current-session",
                    handle=session_handle,
                    snapshot=None,
                    origin="shutdown-or-teardown",
                    primary=first_fault,
                    error=error,
                )
                first_fault = self._chain_faults(first_fault, error)
            else:
                self._session_handle = None
                self._clear_current_native_cleanup_diagnostic(
                    "current-session", session_handle
                )

        root_handle = getattr(self, "_usd_handle", None)
        renderer_drop_neutralizes_root = False
        if root_handle is not None:
            try:
                if root_handle is _ROOT_STAGE_SENTINEL:
                    reset_stage = getattr(self._renderer, "reset_stage", None)
                    if callable(reset_stage):
                        reset_stage()
                    elif allow_renderer_drop:
                        renderer_drop_neutralizes_root = True
                    else:
                        raise RuntimeError(
                            "single-root native scene requires renderer "
                            "destruction for removal"
                        )
                else:
                    self._renderer.remove_usd(root_handle)
            except BaseException as error:  # noqa: BLE001
                self._record_current_native_cleanup_failure(
                    owner="current-root",
                    handle=root_handle,
                    snapshot=getattr(self, "_owned_tmp_path", None),
                    origin="shutdown-or-teardown",
                    primary=first_fault,
                    error=error,
                )
                first_fault = self._chain_faults(first_fault, error)
            else:
                if not renderer_drop_neutralizes_root:
                    self._usd_handle = None
                    self._clear_current_native_cleanup_diagnostic(
                        "current-root", root_handle
                    )

        if self._native_restore_obligation is not None and not allow_renderer_drop:
            first_fault = self._chain_faults(
                first_fault,
                self._native_restore_obligation.diagnostic.latest_error,
            )

        if first_fault is not None:
            self._refresh_native_cleanup_state()
            raise first_fault

        # These unknown/sentinel roots are neutralized only by the caller's
        # immediate renderer drop.  Do not reach this point if any other
        # native owner refused removal.
        if renderer_drop_neutralizes_root:
            self._usd_handle = None
            self._clear_current_native_cleanup_diagnostic(
                "current-root", root_handle
            )
        self._refresh_native_cleanup_state()

    def _remove_live_resync_layers(self) -> None:
        """Remove overlays independently; retain every failed exact handle."""
        handles = tuple(getattr(self, "_live_resync_handles", ()) or ())
        if not handles:
            self._live_resync_handles = []
            return
        self._release_retained_output()
        remaining: list[Any] = []
        first_fault: Optional[BaseException] = None
        for handle in handles:
            try:
                self._renderer.remove_usd(handle)
            except BaseException as error:  # noqa: BLE001
                remaining.append(handle)
                self._record_current_native_cleanup_failure(
                    owner="current-overlay",
                    handle=handle,
                    snapshot=None,
                    origin="overlay-teardown",
                    primary=first_fault,
                    error=error,
                )
                first_fault = self._chain_faults(first_fault, error)
            else:
                self._clear_current_native_cleanup_diagnostic(
                    "current-overlay", handle
                )
        self._live_resync_handles = remaining
        self._refresh_native_cleanup_state()
        if first_fault is not None:
            raise first_fault

    def _open_ovrtx_root(
        self,
        path: Optional[str],
        root_layer_content: Optional[str] = None,
    ) -> Any:
        """Load the root USD scene and return a loaded-state token."""
        self._release_retained_output()
        open_usd_from_string = getattr(self._renderer, "open_usd_from_string", None)
        if root_layer_content is not None and open_usd_from_string is not None:
            open_usd_from_string(root_layer_content)
            return _ROOT_STAGE_SENTINEL

        if path is None:
            raise RuntimeError("ovrtx root loading needs a file path or inline USDA")

        open_usd_from_file = getattr(self._renderer, "open_usd_from_file", None)
        if open_usd_from_file is not None:
            open_usd_from_file(path)
            return _ROOT_STAGE_SENTINEL

        open_usd = getattr(self._renderer, "open_usd", None)
        if open_usd is not None:
            open_usd(path)
            return _ROOT_STAGE_SENTINEL
        return self._renderer.add_usd(path)

    def _root_layer_has_session_scaffolding(self, root_layer: Any) -> bool:
        try:
            return root_layer.GetPrimAtPath(_SESSION_ROOT_PATH) is not None
        except Exception:
            return False

    def _export_root_layer_to_string(
        self,
        root_layer: Any,
        *,
        strip_session_root: bool = False,
    ) -> str:
        if not strip_session_root:
            return root_layer.ExportToString()
        from pxr import Sdf
        layer = Sdf.Layer.CreateAnonymous(".usda")
        if not layer.ImportFromString(root_layer.ExportToString()):
            raise RuntimeError("failed to import root layer snapshot")
        self._strip_session_root_from_layer(layer)
        return layer.ExportToString()

    def _export_live_root_layer_snapshot(
        self,
        root_layer: Any,
        *,
        strip_session_root: bool = False,
    ) -> str:
        """Export the live root layer to a temporary file for ovrtx reloads."""
        root_path = str(getattr(root_layer, "realPath", None) or getattr(
            root_layer, "identifier", ""
        ) or "")
        root_dir = ""
        if root_path and not strip_session_root:
            root_dir = os.path.dirname(os.path.abspath(root_path))
        if not root_dir or not os.path.isdir(root_dir):
            root_dir = tempfile.gettempdir()
        fd = -1
        tmp_path = ""
        try:
            fd, tmp_path = tempfile.mkstemp(
                suffix=".usda",
                prefix=".ovui_widgets_live_",
                dir=root_dir,
            )
        except OSError:
            fd, tmp_path = tempfile.mkstemp(
                suffix=".usda",
                prefix="ovui_widgets_live_",
            )
        finally:
            if fd >= 0:
                os.close(fd)
        try:
            # A snapshot that does not live beside the original root would
            # silently break the layer's relative composition arcs
            # (references, payloads, sublayers, asset-valued fields): the
            # live stage composes them against the original directory, the
            # relocated copy would not. Rewrite every asset path to the
            # form it resolves to FROM THE ORIGINAL LAYER before export,
            # so ovrtx composes exactly what the live stage composes. If
            # any path cannot be anchored, fail here — before any ovrtx
            # state is touched — rather than hand over an incomplete scene.
            original_dir = (
                os.path.dirname(os.path.abspath(root_path)) if root_path else ""
            )
            snapshot_dir = os.path.dirname(os.path.abspath(tmp_path))
            if not original_dir or snapshot_dir != original_dir:
                from pxr import Sdf, UsdUtils

                snapshot_layer = Sdf.Layer.CreateAnonymous(
                    "ovui_widgets_live_snapshot.usda"
                )
                snapshot_layer.TransferContent(root_layer)
                UsdUtils.ModifyAssetPaths(
                    snapshot_layer,
                    lambda asset_path: self._anchor_asset_path(
                        root_layer, asset_path
                    ),
                )
                if not snapshot_layer.Export(tmp_path):
                    raise RuntimeError(
                        f"failed to export root layer snapshot: {tmp_path}"
                    )
            elif not root_layer.Export(tmp_path):
                raise RuntimeError(f"failed to export root layer snapshot: {tmp_path}")
            if strip_session_root:
                self._strip_session_root_from_layer_file(tmp_path)
        except BaseException:
            # BaseException, not Exception: a KeyboardInterrupt mid-export
            # must not leak the partial snapshot either.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        # Ownership of the snapshot is NOT taken here: the caller commits
        # it (replacing any previous owned snapshot) only after every
        # prospective load input has been prepared successfully.
        return tmp_path

    def _anchor_asset_path(self, root_layer: Any, asset_path: str) -> str:
        """Anchor a composition asset path to the original root layer.

        Used when a live-root snapshot must be written somewhere other
        than the root layer's own directory. Only identifiers that are
        genuinely relative under Ar semantics are anchored (resolved
        exactly as the original layer resolves them); everything already
        addressable independent of the layer's location — absolute
        filesystem paths, URI/resolver-scheme identifiers such as
        ``https://…`` or ``omniverse://…``, and anonymous-layer
        identifiers — is preserved byte-for-byte. ``ComputeAbsolutePath``
        must never see a URI: the default resolver would "normalize" it
        into a semantically different identifier (``https://x`` →
        ``https:/x``). An unanchorable relative path raises so the load
        fails truthfully before any current renderer state changes,
        instead of producing a silently incomplete scene for ovrtx.
        """
        from pxr import Sdf

        if not asset_path:
            return asset_path
        if Sdf.Layer.IsAnonymousLayerIdentifier(asset_path):
            return asset_path
        # RFC 3986 scheme detection, mirroring Ar's own URI classification:
        # scheme = ALPHA *(ALPHA / DIGIT / "+" / "-" / ".") followed by ":".
        # A Windows drive prefix ("C:/…") is an absolute path, not a URI,
        # and is equally preserved byte-for-byte by the isabs branch below;
        # both classifications leave the identifier untouched.
        if _ASSET_URI_SCHEME_RE.match(asset_path):
            return asset_path
        if os.path.isabs(asset_path):
            return asset_path
        anchored = root_layer.ComputeAbsolutePath(asset_path)
        if not anchored:
            raise RuntimeError(
                "cannot anchor composition asset path for the live root "
                f"snapshot: {asset_path!r} (root layer: "
                f"{root_layer.identifier!r})"
            )
        return anchored

    def _strip_session_root_from_layer_file(self, path: str) -> None:
        from pxr import Sdf
        layer = Sdf.Layer.FindOrOpen(path)
        if layer is None:
            raise RuntimeError(f"failed to open root layer snapshot: {path}")
        if self._strip_session_root_from_layer(layer):
            if not layer.Save():
                raise RuntimeError(
                    f"failed to save sanitized root layer snapshot: {path}"
                )

    def _strip_session_root_from_layer(self, layer: Any) -> bool:
        spec = layer.GetPrimAtPath(_SESSION_ROOT_PATH)
        if spec is None:
            return False
        if str(getattr(layer, "defaultPrim", "")) == spec.name:
            try:
                layer.ClearDefaultPrim()
            except Exception:
                layer.defaultPrim = ""
        del layer.rootPrims[spec.name]
        return True

    def _add_ovrtx_session_layer(self, usda: str) -> Any:
        """Compose OvGear's session layer into the ovrtx runtime stage."""
        self._release_retained_output()
        add_reference = getattr(self._renderer, "add_usd_reference_from_string", None)
        if add_reference is not None:
            try:
                return add_reference(usda, _SESSION_ROOT_PATH)
            except Exception:
                add_layer = getattr(self._renderer, "add_usd_layer", None)
                if add_layer is None:
                    raise
                return add_layer(usda, path_prefix=_SESSION_ROOT_PATH)
        return self._renderer.add_usd_layer(usda, path_prefix=_SESSION_ROOT_PATH)

    def _sync_ovrtx_root_snapshot_overlay_from_stage(self) -> bool:
        """Mirror a simple live prim resync without reopening the root.

        ovrtx root reopen tears down the renderer's current USD root and
        session layer. For ordinary prim creates, composing the current root
        snapshot as a transient overlay keeps the renderer in sync without the
        visible multi-frame surface churn caused by a full root reload. Deletions
        and schema/property edits still use the stronger reload path.
        """
        if self._stage is None or self._renderer is None:
            return False
        add_layer = getattr(self._renderer, "add_usd_layer", None)
        if not callable(add_layer):
            return False
        self._release_retained_output()
        try:
            root_usda = self._stage.GetRootLayer().ExportToString()
            self._remove_live_resync_layers()
            handle = add_layer(root_usda, path_prefix=None)
            self._live_resync_handles = [handle]
            had_lights = bool(getattr(self, "_scene_has_lights", False))
            self._scene_has_lights = _stage_has_any_light(self._stage)
            if self._scene_has_lights != had_lights:
                self._reinject_session_layer()
            self._latest_point_cloud_frames.clear()
            self._reset_render_timing_state()
            self._reapply_selection_outline_after_live_resync()
            return True
        except Exception:
            # `_remove_live_resync_layers` retains every removal failure in
            # this list; never erase those exact retry owners here.
            return False

    @staticmethod
    def _usd_value_to_write_payload(value: Any) -> Any:
        if isinstance(value, str):
            return [value]
        if isinstance(value, bool):
            return np.ascontiguousarray(np.asarray([value], dtype=np.bool_))
        if isinstance(value, int) and not isinstance(value, bool):
            return np.ascontiguousarray(np.asarray([value], dtype=np.int64))
        if isinstance(value, float):
            return np.ascontiguousarray(np.asarray([value], dtype=np.float64))
        try:
            array = np.asarray(value)
        except Exception:
            return value
        if array.dtype == object:
            return value
        return np.ascontiguousarray(array)

    @staticmethod
    def _render_setting_value_to_write_payload(
        descriptor: RenderSettingDescriptor,
        value: Any,
    ) -> Any:
        usd_type = str(descriptor.metadata.get("usd_type") or "").lower()
        if usd_type in {"string", "token", "asset"}:
            return [str(value)]
        if usd_type == "bool":
            return np.ascontiguousarray(np.asarray([bool(value)], dtype=np.bool_))
        if usd_type in {"int", "int64"}:
            dtype = np.int64 if usd_type == "int64" else np.int32
            return np.ascontiguousarray(np.asarray([int(value)], dtype=dtype))
        if usd_type in {"uint", "uint64"}:
            dtype = np.uint64 if usd_type == "uint64" else np.uint32
            return np.ascontiguousarray(np.asarray([int(value)], dtype=dtype))
        if usd_type in {"half", "float", "double"}:
            dtype = np.float64 if usd_type == "double" else np.float32
            return np.ascontiguousarray(np.asarray([float(value)], dtype=dtype))
        if usd_type in {
            "float2",
            "float3",
            "float4",
            "color3f",
            "color4f",
            "vector3f",
            "normal3f",
            "point3f",
        }:
            return np.ascontiguousarray(np.asarray([tuple(value)], dtype=np.float32))
        return OvRtxRendererAdapter._usd_value_to_write_payload(value)

    def _write_render_setting_to_ovrtx(
        self,
        descriptor: RenderSettingDescriptor,
        value: Any,
    ) -> None:
        renderer = getattr(self, "_renderer", None)
        writer = getattr(renderer, "write_attribute", None)
        if not callable(writer):
            raise RuntimeError("Renderer does not support live setting writes.")
        product_path = str(descriptor.metadata.get("render_product_path") or "")
        attr_name = str(descriptor.metadata.get("attr_name") or "")
        if not product_path or not attr_name:
            raise RuntimeError("Render setting target is missing.")
        self._release_retained_output()
        if descriptor.requirement is RenderSettingRequirement.RENDERER_RESTART:
            reset = getattr(renderer, "reset", None)
            if product_path.startswith(f"{_SESSION_ROOT_PATH}/"):
                if callable(reset):
                    reset()
                self._reinject_session_layer()
            elif not self._reload_live_root_snapshot():
                raise RuntimeError("Renderer restart failed.")
            self._reset_render_timing_state()
            return
        writer(
            prim_paths=[product_path],
            attribute_name=attr_name,
            tensor=self._render_setting_value_to_write_payload(descriptor, value),
        )
        reset = getattr(renderer, "reset", None)
        if callable(reset):
            reset()
            self._reinject_session_layer()
            self._reset_render_timing_state()

    def _session_render_product_setting_lines(self) -> Tuple[str, ...]:
        """Return authored public render settings for the owned RenderProduct."""
        if (
            getattr(self, "_stage", None) is None
            or not self._uses_owned_render_product()
        ):
            return ()
        try:
            prim = self._stage.GetPrimAtPath(self._render_product_path)
        except Exception:
            return ()
        if not prim or not prim.IsValid():
            return ()
        lines: list[str] = []
        try:
            attrs = tuple(prim.GetAttributes())
        except Exception:
            attrs = ()
        for attr in attrs:
            try:
                name = attr.GetName()
                authored = bool(attr.HasAuthoredValue())
            except Exception:
                continue
            if (
                not authored
                or not any(
                    name.startswith(namespace)
                    for namespace in _RENDER_SETTINGS_PUBLIC_NAMESPACES
                )
            ):
                continue
            line = _render_setting_usda_line(attr)
            if line:
                lines.append(line)
        return tuple(lines)

    def _write_property_to_ovrtx(self, prim: Any, sdf_path: Any) -> bool:
        if not sdf_path.IsPropertyPath():
            return False
        property_name = sdf_path.name
        if (
            property_name == "visibility"
            or property_name == "xformOpOrder"
            or property_name.startswith("xformOp:")
        ):
            return False
        attribute = prim.GetAttribute(property_name)
        if not attribute:
            return False
        try:
            value = attribute.Get()
        except Exception:
            return False
        if value is None:
            return False
        try:
            self._renderer.write_attribute(
                prim_paths=[str(sdf_path.GetPrimPath())],
                attribute_name=property_name,
                tensor=self._usd_value_to_write_payload(value),
            )
            return True
        except Exception:
            return False

    def notify_stage_changed(self, event: Any) -> None:
        """Mirror live USD edits into ovrtx."""
        if self._stage is None or self._renderer is None:
            return
        changed_paths = tuple(getattr(event, "changed_paths", ()) or ())
        resynced_paths = tuple(getattr(event, "resynced_paths", ()) or ())
        paths = changed_paths + resynced_paths
        if paths and all(_stage_change_path_is_session(path) for path in paths):
            return
        if not paths:
            paths = tuple(str(prim.GetPath()) for prim in self._stage.TraverseAll())
        try:
            from pxr import Sdf, Usd, UsdGeom
        except Exception:
            return
        # A bare prim entry in a visibility-marked event is a coarse genuine
        # root (e.g. a Mode B whole-layer replay resync): the replay may have
        # touched any descendant's local opinion, so every imageable
        # descendant's token is re-pushed. Property entries stay per-prim.
        visibility_marked = (
            getattr(event, "visibility_delta", None) is not None
            or getattr(event, "source", None) == "ovstage:visibility"
        )
        # Descendant fan-out applies only to notice-authorized visibility
        # roots. Other bare survivors in a marked event (e.g. a re-entrant
        # metadata mutation the ledger retained) sync per-prim.
        fan_out_roots: Any = None
        if getattr(event, "visibility_delta", None) is not None:
            fan_out_roots = set(
                (event.visibility_delta or {}).get("authored") or ()
            )
        sync_decision = self._stage_change_sync_decision(
            event,
            changed_paths,
            resynced_paths,
            Sdf,
        )
        if sync_decision == _STAGE_CHANGE_SYNC_OVERLAY:
            if self._sync_ovrtx_root_snapshot_overlay_from_stage():
                return
            if self._reload_live_root_snapshot():
                return
        elif sync_decision == _STAGE_CHANGE_SYNC_RELOAD:
            if self._reload_live_root_snapshot():
                return
        seen_visibility: set[str] = set()
        seen_transform: set[str] = set()
        for path in paths:
            try:
                sdf_path = Sdf.Path(path)
                prim_path = sdf_path.GetPrimPath() if sdf_path.IsPropertyPath() else sdf_path
                path_str = str(prim_path)
                if path_str.startswith(_SESSION_ROOT_PATH):
                    continue
                prim = self._stage.GetPrimAtPath(prim_path)
                if not prim or not prim.IsValid():
                    continue
                sync_prims = [(path_str, prim)]
                if (
                    visibility_marked
                    and not sdf_path.IsPropertyPath()
                    and (fan_out_roots is None or path_str in fan_out_roots)
                ):
                    sync_prims.extend(
                        (str(descendant.GetPath()), descendant)
                        for descendant in Usd.PrimRange(prim)
                        if descendant != prim
                    )
                for sync_path, sync_prim in sync_prims:
                    imageable = UsdGeom.Imageable(sync_prim)
                    if imageable and sync_path not in seen_visibility:
                        seen_visibility.add(sync_path)
                        # Push the prim's LOCAL visibility opinion, not the
                        # composed result: ovrtx resolves inherited visibility
                        # down its own hierarchy, so baking an ancestor's state
                        # into a descendant's token ('invisible' resolved from
                        # a hidden parent) leaves the descendant stale when a
                        # later edit flips only the ancestor.
                        token = imageable.GetVisibilityAttr().Get()
                        self._renderer.write_attribute(
                            [sync_path],
                            "visibility",
                            [str(token)],
                        )
                if (
                    path_str not in seen_transform
                    and _stage_change_path_affects_transform(sdf_path)
                ):
                    seen_transform.add(path_str)
                    self._write_prim_transform_to_ovrtx(prim, path_str)
                if sdf_path.IsPropertyPath():
                    self._write_property_to_ovrtx(prim, sdf_path)
            except Exception:
                continue

    def _stage_change_live_safe_visibility_path(
        self, sdf_module: Any, path: Any, authored: Any = ()
    ) -> bool:
        """True iff ``path`` is provably handled by the LIVE writer.

        Live-safe forms:
        - a ``visibility`` property path that composes as a genuine USD
          ATTRIBUTE;
        - a REMOVED ``visibility`` path whose prim the ADAPTER proved as a
          visibility-authored root (``delta['authored']``) — the command's
          own attribute removal; the per-prim schema-token push covers it.
          A removed path WITHOUT adapter proof (e.g. a relationship
          literally named ``visibility`` deleted re-entrantly) is NOT
          live-safe: name shape never reclassifies semantics (round 10);
        - a bare prim path appearing as changed-INFO (USD reports
          structural consequences as resyncs, so a changed-info prim
          entry is metadata/created-``over`` scaffolding; the live loop
          re-pushes its token harmlessly).
        Live relationships (even one named ``visibility``),
        non-visibility properties, and unparseable paths are NOT
        live-safe — the attribute-only live writer cannot express their
        consequences.
        """
        path_str = str(path or "")
        if not path_str:
            return False
        if _stage_change_path_is_session(path_str):
            return True  # stripped before reaching OVRTX either way
        try:
            sdf_path = sdf_module.Path(path_str)
        except Exception:
            return False
        if not sdf_path.IsPropertyPath():
            return True  # bare changed-info prim entry (non-structural)
        if sdf_path.name != "visibility":
            return False
        try:
            obj = self._stage.GetObjectAtPath(sdf_path)
        except Exception:
            return False
        if obj:
            try:
                from pxr import Usd, UsdGeom
                # ACTUAL Imageable schema authority required (PR review):
                # a live custom Float, plain String, custom token, other
                # lookalike, or a token/non-custom attribute on a
                # NON-Imageable prim is not the schema attribute the live
                # writer expresses — structural handling.
                return (
                    isinstance(obj, Usd.Attribute)
                    and str(obj.GetTypeName()) == "token"
                    and not bool(obj.IsCustom())
                    and bool(UsdGeom.Imageable(obj.GetPrim()))
                )
            except Exception:
                return False
        # The property no longer composes: only the adapter's proven
        # visibility-authored annotation makes the removal live-safe.
        return str(sdf_path.GetPrimPath()) in (authored or ())

    def _stage_change_sync_decision(
        self,
        event: Any,
        changed_paths: tuple[Any, ...],
        resynced_paths: tuple[Any, ...],
        sdf_module: Any,
    ) -> str:
        """Classify a stage notice into live write, overlay, or full reload.

        A simple existing-prim resync (ordinary Create action) can be
        re-presented to ovrtx with a transient root snapshot overlay, avoiding
        the visible full-root reload churn. Destructive or structural changes
        still reload the live root snapshot through ``load_stage`` so deletes,
        schema/API changes, property edits, layer updates, and stale session
        roots are reflected with main's session-root stripping path.
        """
        event_type = getattr(event, "event_type", None)
        if event_type is ChangeEventType.LAYER_INFO:
            return _STAGE_CHANGE_SYNC_RELOAD
        if getattr(event, "visibility_delta", None) is not None:
            # Adapter-marked visibility attempt/scope event: its truthfully
            # RESYNC-classified bare roots (Mode B replays) are visibility
            # outcomes on existing prims, not structural changes — the live
            # per-prim write path (with conservative descendant fan-out for
            # bare roots) is the correct, flicker-free synchronization.
            # The shortcut is allowed ONLY when EVERY path is proven safe
            # for live handling (round 9): every resync must carry the
            # visibility annotation AND every changed path must be either
            # a genuine visibility ATTRIBUTE consequence or a bare
            # changed-info prim entry (non-structural by USD semantics —
            # created ``over`` ancestors, metadata). Anything else the
            # ledger retained — a re-entrant RELATIONSHIP creation/removal/
            # retarget (``material:binding``), an unsupported property
            # form, a foreign attribute edit, or an unannotated resync —
            # falls through to the ordinary structural classifier so the
            # genuine consequence reaches overlay/reload instead of being
            # silently skipped by the attribute-only live writer.
            delta = event.visibility_delta or {}
            annotated = set(delta.get("operation_resyncs") or ())
            delta_authored = set(delta.get("authored") or ())
            # PROVEN + PRECISE annotation required: a context-free,
            # merged-imprecise, disposal, or otherwise unproven delta can
            # NEVER take the live shortcut, regardless of its annotation.
            if delta.get("proven") is True and delta.get(
                "precise", True
            ) and all(
                str(path) in annotated for path in resynced_paths
            ) and all(
                self._stage_change_live_safe_visibility_path(
                    sdf_module, path, authored=delta_authored
                )
                for path in changed_paths
            ):
                return _STAGE_CHANGE_SYNC_LIVE

        resynced_path_strings = {str(path or "") for path in resynced_paths}
        general_delta = getattr(event, "visibility_delta", None) or {}
        # ``authored`` may vouch for a REMOVED visibility path only when
        # the annotation is attempt-proven (round 11); an unproven
        # context-free annotation vouches for nothing.
        general_authored = (
            set(general_delta.get("authored") or ())
            if general_delta.get("proven") is True
            else set()
        )
        # CATEGORICAL structural boundary (PR review): a delta-marked event
        # that is unproven or imprecise (scope-conservative flushes,
        # precise+imprecise merges, unresolved-scope disposal) may never
        # resolve to LIVE — even when every individual path would pass the
        # stage checks — because its annotation cannot vouch for the
        # event's completeness. The floor below coerces a would-be LIVE
        # outcome to the structural overlay path.
        structural_floor = bool(
            getattr(event, "visibility_delta", None) is not None
            and not (
                general_delta.get("proven") is True
                and general_delta.get("precise", True)
            )
        )
        needs_overlay = False
        for path in (*changed_paths, *resynced_paths):
            path_str = str(path or "")
            if not path_str or _stage_change_path_is_session(path_str):
                continue
            sdf_path = None
            try:
                sdf_path = sdf_module.Path(path_str)
            except Exception:
                sdf_path = None

            if sdf_path is not None and sdf_path.IsPropertyPath():
                property_name = sdf_path.name
                if (
                    property_name == "xformOpOrder"
                    or property_name.startswith("xformOp:")
                ):
                    continue
                if property_name == "visibility":
                    # Name shape alone is not visibility semantics: only a
                    # genuine live ATTRIBUTE (or an adapter-proven removed
                    # one) may take the live path; a relationship named
                    # ``visibility`` — created, retargeted, or removed —
                    # reloads structurally (round 10).
                    if self._stage_change_live_safe_visibility_path(
                        sdf_module, path_str, authored=general_authored
                    ):
                        continue
                    return _STAGE_CHANGE_SYNC_RELOAD
                return _STAGE_CHANGE_SYNC_RELOAD

            if sdf_path is None and "." in path_str:
                _prim_path, _separator, property_name = path_str.partition(".")
                if (
                    property_name == "visibility"
                    or property_name == "xformOpOrder"
                    or property_name.startswith("xformOp:")
                ):
                    continue
                return _STAGE_CHANGE_SYNC_RELOAD

            is_resync_path = (
                path_str in resynced_path_strings
                or event_type is ChangeEventType.RESYNC
            )
            if not is_resync_path:
                continue

            try:
                prim = self._stage.GetPrimAtPath(sdf_path or path_str)
                prim_exists = bool(prim and prim.IsValid())
            except Exception:
                prim_exists = False
            if prim_exists:
                needs_overlay = True
                continue
            return _STAGE_CHANGE_SYNC_RELOAD

        if needs_overlay:
            return _STAGE_CHANGE_SYNC_OVERLAY
        if structural_floor:
            return _STAGE_CHANGE_SYNC_OVERLAY
        return _STAGE_CHANGE_SYNC_LIVE

    def _reload_live_root_snapshot(self) -> bool:
        if self._stage is None or self._renderer is None:
            return False
        self._release_retained_output()
        selected_paths = list(getattr(self, "_selected_paths", []) or [])
        try:
            self.load_stage(self._stage, use_live_root_snapshot=True)
            self._latest_point_cloud_frames.clear()
            if selected_paths:
                self.set_selection_highlight(selected_paths, force_reapply=True)
            return True
        except Exception:
            return False

    def _write_local_transform_matrix_to_ovrtx(
        self,
        path_str: str,
        matrix: Matrix4d,
    ) -> bool:
        renderer = getattr(self, "_renderer", None)
        writer = getattr(renderer, "write_attribute", None)
        semantic = getattr(getattr(_ovrtx, "Semantic", None), "XFORM_MAT4x4", None)
        if not path_str or not callable(writer) or semantic is None:
            return False
        try:
            tensor = np.ascontiguousarray(
                np.asarray([matrix], dtype=np.float64),
                dtype=np.float64,
            )
            if tensor.shape != (1, 4, 4):
                return False
            writer(
                prim_paths=[str(path_str)],
                attribute_name="omni:xform",
                tensor=tensor,
                semantic=semantic,
            )
            return True
        except Exception:
            return False

    def set_live_local_transform(self, path: str, matrix: Matrix4d) -> bool:
        """Push a prim-local transform preview into ovrtx without authoring USD."""
        return self._write_local_transform_matrix_to_ovrtx(str(path), matrix)

    def clear_live_local_transforms(self, paths: List[str]) -> None:
        """Restore ovrtx transforms for ``paths`` from the authoritative USD stage."""
        stage = getattr(self, "_stage", None)
        if stage is None:
            return None
        for path in paths or []:
            path_str = str(path)
            if not path_str:
                continue
            try:
                prim = stage.GetPrimAtPath(path_str)
            except Exception:
                continue
            if prim and prim.IsValid():
                self._write_prim_transform_to_ovrtx(prim, path_str)
        return None

    def _write_prim_transform_to_ovrtx(self, prim: Any, path_str: str) -> None:
        try:
            from pxr import UsdGeom
        except Exception:
            return
        xformable = UsdGeom.Xformable(prim)
        if not xformable:
            return
        try:
            matrix = xformable.GetLocalTransformation()
            self._write_local_transform_matrix_to_ovrtx(path_str, matrix)
        except Exception:
            return

    # ── Per-frame rendering ──

    def render_frame(
        self,
        width: int,
        height: int,
        view_matrix: Any,
        proj_matrix: Any,
    ) -> np.ndarray | GpuFrame:
        """Render one frame via ovrtx.

        Drives the session camera from ``(view_matrix, proj_matrix)``
        each frame, then calls ``renderer.step``. The normal tier-1 path
        returns a ``(H, W, 4)`` uint8 RGBA ndarray copied from the CPU-mapped
        ``LdrColor`` render var. When tier-2 zero-copy is active and the
        requested size matches ovrtx's committed render product, this may
        instead return a :class:`GpuFrame` carrying a live CUDA mapping for
        :class:`ImageBridge` to consume synchronously.

        On any failure (missing stage, missing LdrColor var, ovrtx step
        error) a black ``(height, width, 4)`` uint8 frame is returned
        instead of raising — a transient renderer fault must not take
        down the viewport frame loop.
        """
        if self._stage is None or self._usd_handle is None:
            return np.zeros((int(height), int(width), 4), dtype=np.uint8)
        if width <= 0 or height <= 0:
            return np.zeros((max(int(height), 1), max(int(width), 1), 4), dtype=np.uint8)

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
        if (overlap is not None
                and getattr(self, "_in_flight_pick_queries", None)):
            presented = overlap.presented_snapshot
            if presented is not None:
                if camera_state_differs(
                        presented, view_matrix, proj_matrix,
                        (int(width), int(height))):
                    pick_skip = True
                view_matrix = presented.view
                proj_matrix = presented.projection

        runtime_camera_path = self._runtime_camera_path()
        # 1) Resolution change: debounced reinject of the session layer.
        # Rapid drag-resize events within a 200 ms window collapse into a
        # single reinject every 250 ms to avoid ovrtx churn; isolated
        # resizes apply on the same frame. We run the reinject FIRST so
        # the per-frame ``write_attribute`` pushes below land on the
        # current session-layer handle and survive the same step. If
        # the order were inverted, the reinject would replace the
        # session and the writes would land on a now-detached handle —
        # ovrtx would render the reinjected USDA defaults instead of
        # the live values.
        self._apply_resolution_if_allowed((int(width), int(height)))

        # 2) Mirror camera values into ovrtx Fabric for the camera that the
        # active render product can actually consume. The owned session
        # render product lives in a separate ovrtx layer, so it must stay
        # bound to the owned session camera; selected scene cameras still
        # feed the viewport pose, but the owned camera receives the live
        # matrices for that default product. User-selected render products
        # are not re-authored, so when one is active the selected scene
        # camera receives the world-space runtime write instead. In both
        # cases, user camera prims stay read-only on the pxr/USD side.
        # Issue #22 — keep the intrinsics push paired with the xform push so
        # the rendered image and the omni.ui.scene overlay use the same
        # camera.
        world_tensor = _view_to_ovrtx_transform(view_matrix)
        try:
            self._renderer.write_attribute(
                prim_paths=[runtime_camera_path],
                attribute_name="omni:xform",
                tensor=world_tensor,
                semantic=_ovrtx.Semantic.XFORM_MAT4x4,
            )
        except Exception:
            # Don't bring the frame loop down on a single write error —
            # step() below will either still succeed with the previous
            # transform, or fail and we'll return a black frame.
            pass
        self._push_camera_intrinsics(proj_matrix, runtime_camera_path)

        # 3) Step ovrtx with a clamped delta.
        now = time.monotonic()
        dt = max(_MIN_DT, min(_MAX_DT, now - self._dt_clock))
        self._dt_clock = now
        render_product_paths = self._render_products_for_step()
        try:
            products = self._renderer.step(
                render_products=render_product_paths,
                delta_time=dt,
            )
        except Exception:
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
            return np.zeros((int(height), int(width), 4), dtype=np.uint8)

        self._dispatch_pending_pick_results(products)
        self._extract_requested_point_cloud_frames(products)
        self._extract_requested_render_var_output_frames(products)

        # When the debounce defers a resolution change, ovrtx still
        # renders at ``self._last_resolution`` — potentially smaller or
        # larger than ``(width, height)``. ``_extract_ldr_color`` uses the
        # CPU path for those mismatch frames so ``_normalize_rgba`` can
        # pad/crop safely before ImageBridge sees the requested size.
        if overlap is None or not self._ldr_overlap_allowed():
            if overlap is not None:
                # Gated frame (livestream / zero-copy / LdrColor output
                # request): those paths share the single per-frame LdrColor
                # mapping and keep their existing synchronous behavior.
                overlap.release(clear_presentation=True)
            return self._extract_ldr_color(products, int(width), int(height))

        # Depth-one overlap: present the PREVIOUS step's image (its GPU work
        # has had a full frame to finish, so the map cost is ~0.3 ms instead
        # of ~one GPU frame) and retain ``products`` for the next call. The
        # retention key ties the retained container to the stage, product,
        # committed resolution, and renderer identity — any change releases
        # it and the next frame re-fills synchronously (correct image, one
        # slower frame, no black flash).
        committed = getattr(self, "_last_resolution", None)
        retention_key = (
            id(self._stage),
            str(self._render_product_path or ""),
            tuple(committed) if committed else None,
            id(self._renderer),
        )
        snapshot = CameraSnapshot.capture(
            view_matrix, proj_matrix, (int(width), int(height))
        )
        return overlap.consume(
            products,
            retention_key,
            snapshot,
            lambda retained: self._extract_ldr_color(
                retained, int(width), int(height)
            ),
            (int(height), int(width)),
            pick_skip,
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
        for request in self._point_cloud_requests.values():
            if request.render_product_path:
                paths.add(str(request.render_product_path))
        for request in self._render_var_output_requests.values():
            if request.render_product_path:
                paths.add(str(request.render_product_path))
        return paths

    def _extract_requested_point_cloud_frames(self, products: Any) -> None:
        self._ensure_point_cloud_state()
        for viewport_id, request in list(self._point_cloud_requests.items()):
            try:
                frame = self._extract_point_cloud_frame(products, request)
            except Exception as exc:
                frame = self._stale_point_cloud_frame(
                    viewport_id,
                    request,
                    "extraction_failed",
                    f"PointCloud extraction failed: {type(exc).__name__}: {exc}",
                )
            self._latest_point_cloud_frames[
                (viewport_id, request.render_product_path)
            ] = frame

    def _mark_point_cloud_requests_stale(self, code: str, message: str) -> None:
        self._ensure_point_cloud_state()
        for viewport_id, request in list(self._point_cloud_requests.items()):
            self._latest_point_cloud_frames[
                (viewport_id, request.render_product_path)
            ] = self._stale_point_cloud_frame(viewport_id, request, code, message)

    def _extract_requested_render_var_output_frames(self, products: Any) -> None:
        self._ensure_render_var_output_state()
        for viewport_id, request in list(self._render_var_output_requests.items()):
            try:
                frame = self._extract_render_var_output_frame(products, request)
            except Exception as exc:
                frame = self._stale_render_var_output_frame(
                    viewport_id,
                    request,
                    "extraction_failed",
                    f"RenderVar output extraction failed: {type(exc).__name__}: {exc}",
                )
            self._latest_render_var_output_frames[
                (viewport_id, request.render_product_path, request.output_id)
            ] = frame

    def _mark_render_var_output_requests_stale(self, code: str, message: str) -> None:
        self._ensure_render_var_output_state()
        for viewport_id, request in list(self._render_var_output_requests.items()):
            self._latest_render_var_output_frames[
                (viewport_id, request.render_product_path, request.output_id)
            ] = self._stale_render_var_output_frame(viewport_id, request, code, message)

    def _point_cloud_descriptor_for_frame(
        self,
        request: PointCloudRequest,
    ) -> PointCloudOutputDescriptor | None:
        catalog = self.list_point_cloud_outputs(request.render_product_path)
        return _point_cloud_output_for_request(catalog, request)

    def _render_var_descriptor_for_frame(
        self,
        request: RenderVarOutputRequest,
    ) -> RenderVarOutputDescriptor | None:
        catalog = self.list_render_var_outputs(request.render_product_path)
        return _render_var_output_for_request(catalog, request)

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
            component_count=(
                descriptor.component_count if descriptor is not None else 1
            ),
            color_space=descriptor.color_space if descriptor is not None else "",
            units=descriptor.units if descriptor is not None else "",
            value_range=descriptor.value_range if descriptor is not None else None,
            stale=True,
            warnings=(warning,),
            metadata={
                "descriptor": descriptor.output_id if descriptor is not None else "",
            },
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
            source_sensor_path=(
                descriptor.source_sensor_path if descriptor is not None else None
            ),
            source_sensor_type=(
                descriptor.source_sensor_type if descriptor is not None else ""
            ),
            channel_descriptors=(
                descriptor.channels if descriptor is not None else ()
            ),
            warnings=(warning,),
        )

    def _extract_point_cloud_frame(
        self,
        products: Any,
        request: PointCloudRequest,
    ) -> PointCloudFrame:
        descriptor = self._point_cloud_descriptor_for_frame(request)
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
        render_vars = _point_cloud_render_vars_for_product(
            products,
            request.render_product_path,
        )
        if render_vars is None:
            return self._stale_point_cloud_frame(
                request.viewport_id,
                request,
                "missing_product",
                "PointCloud render product was not returned by the renderer.",
                descriptor,
            )

        try:
            counts = _point_cloud_copy_render_var(render_vars, "Counts")
            coordinates_data = _point_cloud_copy_render_var(render_vars, "Coordinates")
        except Exception as exc:
            return self._stale_point_cloud_frame(
                request.viewport_id,
                request,
                "mapping_failed",
                f"PointCloud required channel mapping failed: {type(exc).__name__}: {exc}",
                descriptor,
            )

        coordinate_rows = _point_cloud_rows(coordinates_data, 3)
        available_count = coordinate_rows.shape[0]
        bounded_count = _point_cloud_count(counts, available_count)
        indices = _point_cloud_indices(bounded_count, request)
        coordinate_rows = np.asarray(coordinate_rows[:bounded_count, :3])
        selected_coordinates = np.array(coordinate_rows[indices], copy=True)
        world_coordinates, coordinate_space, transform_warning = (
            _point_cloud_world_coordinates(
                selected_coordinates,
                descriptor,
                _stage_units_per_meter(self._stage),
            )
        )
        warnings = list(descriptor.warnings)
        if transform_warning is not None:
            warnings.append(transform_warning)
            return self._stale_point_cloud_frame(
                request.viewport_id,
                request,
                transform_warning.code,
                transform_warning.message,
                descriptor,
            )

        channel_by_name = {channel.name: channel for channel in descriptor.channels}
        channels: dict[str, Any] = {}
        flags_data = None
        for channel_name in _point_cloud_requested_channel_names(request, descriptor):
            channel = channel_by_name.get(channel_name)
            if channel is None:
                warnings.append(_point_cloud_warning(
                    "missing_channel",
                    f"Requested PointCloud channel {channel_name!r} is not described.",
                ))
                continue
            if channel.semantic is PointCloudChannelSemantic.COUNT:
                continue
            try:
                data = _point_cloud_copy_render_var(render_vars, channel.name)
                payload = _point_cloud_channel_payload(
                    data,
                    indices,
                    channel,
                )
            except Exception:
                warnings.append(_point_cloud_warning(
                    "missing_channel",
                    f"PointCloud channel {channel.name!r} was not returned.",
                ))
                continue
            if channel.semantic is PointCloudChannelSemantic.FLAGS:
                flags_data = data
            if channel.semantic is PointCloudChannelSemantic.COORDINATES:
                continue
            channels[channel.name] = payload

        validity_mask = None
        valid_point_count = len(indices)
        if request.include_validity:
            if flags_data is None and "Flags" in channel_by_name:
                try:
                    flags_data = _point_cloud_copy_render_var(render_vars, "Flags")
                except Exception:
                    warnings.append(_point_cloud_warning(
                        "missing_validity",
                        "PointCloud Flags channel was not returned.",
                    ))
            if flags_data is not None:
                try:
                    validity_mask = _point_cloud_validity_mask(flags_data, indices)
                    valid_point_count = int(np.count_nonzero(validity_mask))
                except Exception:
                    warnings.append(_point_cloud_warning(
                        "invalid_validity",
                        "PointCloud Flags channel could not be interpreted.",
                    ))

        frame_out = None
        try:
            frame_out = products[request.render_product_path].frames[0]
        except Exception:
            pass
        return PointCloudFrame(
            render_product_path=request.render_product_path,
            render_var_name=request.render_var_name,
            point_count=len(indices),
            valid_point_count=valid_point_count,
            coordinates=world_coordinates,
            channels=channels,
            validity_mask=validity_mask,
            coordinate_space=coordinate_space,
            transform_to_world=descriptor.transform_to_world,
            frame_index=_point_cloud_frame_index(frame_out),
            timestamp=self._clock(),
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
        descriptor = self._render_var_descriptor_for_frame(request)
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
        render_vars, frame_out = _render_var_render_vars_for_product(
            products,
            request.render_product_path,
        )
        if render_vars is None:
            return self._stale_render_var_output_frame(
                request.viewport_id,
                request,
                "missing_product",
                "RenderVar render product was not returned by the renderer.",
                descriptor,
            )
        try:
            data = _render_var_copy_runtime_data(render_vars, descriptor)
            width, height, component_count = _render_var_frame_shape(
                data,
                descriptor,
            )
        except Exception as exc:
            return self._stale_render_var_output_frame(
                request.viewport_id,
                request,
                "mapping_failed",
                f"RenderVar output mapping failed: {type(exc).__name__}: {exc}",
                descriptor,
            )
        return RenderVarOutputFrame(
            render_product_path=descriptor.render_product_path,
            output_id=descriptor.output_id,
            render_var_name=descriptor.render_var_name,
            width=width,
            height=height,
            dtype=descriptor.dtype or str(data.dtype),
            component_count=component_count,
            color_space=descriptor.color_space,
            units=descriptor.units,
            value_range=descriptor.value_range,
            display_data=data,
            raw_data=data,
            frame_index=_point_cloud_frame_index(frame_out),
            timestamp=self._clock(),
            stale=False,
            warnings=descriptor.warnings,
            metadata={
                "shape": tuple(int(item) for item in np.asarray(data).shape),
                "output_kind": descriptor.output_kind.value,
            },
        )

    def _push_camera_intrinsics(self, proj_matrix: Any, camera_path: str) -> None:
        """Push focalLength / h_aperture / v_aperture to ovrtx Fabric.

        ``UsdGeomCamera`` declares these as ``float`` (32-bit), so we
        send a length-1 ``float32`` tensor per attribute. On any failure
        the call is swallowed — the renderer keeps rendering with the
        previous frame's values and the next frame retries. Issue #22.
        """
        try:
            from ovui_data_adapters.openusd._camera_writer import compute_camera_intrinsics
            focal, h_ap, v_ap, _, _ = compute_camera_intrinsics(proj_matrix)
        except Exception:
            return
        signature = (str(camera_path), float(focal), float(h_ap), float(v_ap))
        if signature == getattr(self, "_last_pushed_camera_intrinsics", None):
            return
        try:
            for name, value in (
                ("focalLength", focal),
                ("horizontalAperture", h_ap),
                ("verticalAperture", v_ap),
            ):
                tensor = np.array([value], dtype=np.float32)
                self._renderer.write_attribute(
                    prim_paths=[camera_path],
                    attribute_name=name,
                    tensor=tensor,
                )
            self._last_pushed_camera_intrinsics = signature
        except Exception:
            pass

    def _apply_resolution_if_allowed(self, target: Tuple[int, int]) -> None:
        """Commit ``target`` to ovrtx Fabric iff the debounce policy allows.

        Policy (the viewport behavior):

        * If the request equals the last committed resolution, do nothing.
        * Otherwise measure the delta. A "big" delta is >8 px on either
          axis; we compute ``actively_resizing`` from the *prior*
          ``_last_big_delta_time`` before updating it with the current
          frame, so a single isolated jump is never "actively resizing"
          against itself — it must have at least one big-delta predecessor
          within ``_RESIZE_ACTIVE_WINDOW_S`` to qualify.
        * "Actively resizing" means a prior big delta was seen within
          ``_RESIZE_ACTIVE_WINDOW_S``. During active resize, throttle
          reinjects to one per ``_RESIZE_DEBOUNCE_S``. When not active,
          apply immediately — including sub-threshold deltas after the
          active window expires.

        When the write is deferred, the render step below still runs —
        ovrtx renders at ``_last_resolution`` and ``_normalize_rgba`` in
        the caller pads/crops the returned frame to the requested
        ``(width, height)`` so the on-screen image stays coherent.
        """
        if target == self._last_resolution:
            return
        now = self._clock()
        dw = abs(target[0] - self._last_resolution[0])
        dh = abs(target[1] - self._last_resolution[1])
        big_delta = dw > _RESIZE_BIG_DELTA_PX or dh > _RESIZE_BIG_DELTA_PX
        actively_resizing = (now - self._last_big_delta_time) < _RESIZE_ACTIVE_WINDOW_S
        if big_delta:
            self._last_big_delta_time = now
        throttle_ok = (now - self._last_reinject_time) >= _RESIZE_DEBOUNCE_S
        if (not actively_resizing) or throttle_ok:
            self._last_resolution = target
            self._last_reinject_time = now
            self._reinject_session_layer()

    def _reinject_session_layer(self) -> None:
        """Re-compose the OvGear session layer after a resolution change."""
        self._ensure_native_cleanup_tracking()
        self._release_retained_output()
        if self._session_handle is not None:
            old_session_handle = self._session_handle
            try:
                self._renderer.remove_usd(old_session_handle)
            except BaseException as error:  # noqa: BLE001
                self._record_current_native_cleanup_failure(
                    owner="current-session",
                    handle=old_session_handle,
                    snapshot=None,
                    origin="session-reinject",
                    primary=None,
                    error=error,
                )
                raise
            else:
                self._session_handle = None
                self._clear_current_native_cleanup_diagnostic(
                    "current-session", old_session_handle
                )
        try:
            session_camera_path = getattr(self, "_default_camera_path", _CAMERA_PATH)
            self._session_handle = self._add_ovrtx_session_layer(
                _build_session_usda(
                    self._last_resolution,
                    include_fallback_dome=not self._scene_has_lights,
                    camera_path=session_camera_path,
                    render_product_setting_lines=(
                        self._session_render_product_setting_lines()
                    ),
                )
            )
            self._last_pushed_camera_intrinsics = None
        except BaseException as error:
            # Leave session uninstalled — step() will fail loudly next
            # frame (black frame via the try/except in render_frame).
            self._session_handle = None
            self._record_current_native_cleanup_failure(
                owner="current-session-install",
                handle=_SESSION_INSTALL_SENTINEL,
                snapshot=None,
                origin="session-reinject",
                primary=None,
                error=error,
            )
            raise
        else:
            self._clear_current_native_cleanup_diagnostic(
                "current-session-install", _SESSION_INSTALL_SENTINEL
            )

        # Also reflect the new resolution into the pxr stage's session
        # render product so Property Inspector is consistent.
        try:
            self._author_owned_session_render_product_resolution(self._last_resolution)
        except Exception:
            pass

    def _author_owned_session_render_product_resolution(
        self,
        resolution: Tuple[int, int],
    ) -> None:
        """Mirror the committed effective resolution into the pxr session layer.

        OpenUSD-backed viewports own a session RenderProduct under
        ``/OvGearSession``. Resolution changes must update that session
        product only; the user's root layer remains untouched.
        """
        if self._stage is None or not self._uses_owned_render_product():
            return
        from ovui_data_adapters.openusd._session_authoring import ensure_render_product

        session_camera_path = getattr(self, "_default_camera_path", _CAMERA_PATH)
        ensure_render_product(
            self._stage,
            product_path=self._render_product_path,
            camera_path=session_camera_path,
            ldr_var_path=_LDR_VAR_PATH,
            resolution=(int(resolution[0]), int(resolution[1])),
            ensure_camera_prim=True,
        )

    def _extract_ldr_color(
        self,
        products: Any,
        width: int,
        height: int,
    ) -> np.ndarray | GpuFrame:
        """Extract the LdrColor render var.

        Three live paths share one ``rv.map(device=CUDA)`` per frame
        (ovrtx forbids a second map on the same RV):

        * GPU-UI zero-copy + livestream (both env flags set): tee the
          CUDA pointer to ovstream NVENC via
          ``LivestreamTap.tee_to_ovstream``, then return a
          :class:`GpuFrame` keeping the mapping alive for ``ImageBridge``
          to consume. No D2H. (Codex blocker 4 — composition.)
        * GPU-UI zero-copy only: return a :class:`GpuFrame`.
        * Livestream only: tee + D2H, return ``(H, W, 4)`` uint8 host
          ndarray.

        The default fallback maps to CPU and returns an ``(H, W, 4)``
        uint8 ndarray — the legacy tier-1 path. The mapped DLPack
        buffer is invalidated when ``map()``'s context manager exits,
        so we ``.copy()`` the numpy view before returning.
        """
        try:
            product = products[self._render_product_path]
        except Exception:
            return np.zeros((height, width, 4), dtype=np.uint8)
        if not getattr(product, "frames", None):
            return np.zeros((height, width, 4), dtype=np.uint8)
        frame_out = product.frames[0]
        render_vars = getattr(frame_out, "render_vars", None) or {}
        rv = render_vars.get(_LDR_VAR_NAME)
        if rv is None:
            return np.zeros((height, width, 4), dtype=np.uint8)

        state = self._zero_copy_state
        livestream = getattr(self, "_livestream", None)
        committed_resolution = getattr(self, "_last_resolution", (width, height))
        gpu_size_matches = (int(width), int(height)) == committed_resolution

        # ── GPU UI zero-copy path (with optional livestream tee) ──
        if state is not None and state.gpu_pending and gpu_size_matches:
            mapping = None
            try:
                mapping = rv.map(device=_ovrtx.Device.CUDA)
                mapping.__enter__()
                ptr = int(mapping.tensor.data)
                # Codex blocker 4: when both flags are on, tee to
                # ovstream from the SAME mapping (one CUDA map serves
                # both consumers — the GPU-UI ingest reads ptr directly,
                # NVENC reads its D2D copy). Failures inside
                # ``tee_to_ovstream`` are isolated by the tap; they
                # cannot bubble out and break the GPU UI ingest.
                if livestream is not None:
                    try:
                        livestream.tee_to_ovstream(mapping.tensor, width, height)
                    except Exception:
                        # tee_to_ovstream is contracted to be
                        # exception-safe; but if anything escapes,
                        # swallow it here so the GPU UI path keeps working.
                        pass
                return GpuFrame(
                    ptr=ptr,
                    width=int(width),
                    height=int(height),
                    mapping=mapping,
                )
            except Exception as exc:
                if mapping is not None:
                    try:
                        mapping.__exit__(None, None, None)
                    except Exception:
                        pass
                state.mark_fallback(f"CUDA map raised: {type(exc).__name__}: {exc}")

        # ── Livestream-only path (CUDA map shared with D2H for UI) ──
        if livestream is not None:
            try:
                with rv.map(device=_ovrtx.Device.CUDA) as mapping:
                    arr = livestream.tee_and_d2h(
                        mapping.tensor, width, height,
                        host_buf=getattr(self, "_livestream_host_buf", None),
                    )
                    self._livestream_host_buf = arr
                if arr.ndim >= 2 and arr.shape[0] > 0 and arr.shape[1] > 0:
                    self._last_render_product_resolution = (
                        int(arr.shape[1]),
                        int(arr.shape[0]),
                    )
                return _normalize_rgba(arr, width, height)
            except Exception:
                # tee_and_d2h is contracted to never raise out (Codex
                # blocker 3). If something does escape, fall through to
                # the CPU map path so the viewport stays live — only
                # log the first occurrence.
                if not getattr(self, "_livestream_error_logged", False):
                    import traceback as _tb
                    _tb.print_exc()
                    self._livestream_error_logged = True

        # ── CPU map path (default + post-livestream-failure fallback) ──
        try:
            with rv.map(device=_ovrtx.Device.CPU) as mapping:
                arr = mapping.tensor.numpy()
                # Must copy: the DLPack buffer is unmapped on __exit__.
                arr = np.array(arr, copy=True)
        except Exception:
            return np.zeros((height, width, 4), dtype=np.uint8)

        if arr.ndim >= 2 and arr.shape[0] > 0 and arr.shape[1] > 0:
            self._last_render_product_resolution = (
                int(arr.shape[1]),
                int(arr.shape[0]),
            )
        return _normalize_rgba(arr, width, height)

    # ── Resolution / selection / picking ──

    def set_resolution(self, width: int, height: int) -> None:
        """Cache a new resolution; :meth:`render_frame` applies it lazily."""
        self._pending_resolution = (int(width), int(height))

    def set_selection_highlight(
        self,
        paths: List[str],
        *,
        force_reapply: bool = False,
    ) -> None:
        """Drive ovrtx's native selection-outline state for selected prims.

        Tracks ``_selection_outline_previous_paths`` defensively: clears
        and sets advance the tracked set only after their ovrtx write
        succeeds. A transient ovrtx write failure leaves bookkeeping in
        the retryable state — otherwise a deselected prim could stay
        outlined forever, or a selected prim could be skipped forever.
        ``force_reapply`` rewrites selected paths even when bookkeeping
        says they were already outlined; use it after renderer layer
        replacement because ovrtx outline attributes may have been
        dropped while this adapter's cache still contains the selection.
        """
        selected = list(dict.fromkeys(str(p) for p in (paths or []) if p))
        self._selected_paths = selected
        self._configure_selection_outline_styles()

        previous = set(getattr(self, "_selection_outline_previous_paths", set()))
        current = set(selected)
        to_clear = sorted(previous - current)
        to_set = [
            path
            for path in selected
            if force_reapply or path not in previous
        ]

        new_previous: set[str] = set(previous)
        clear_success = True
        set_success = True
        failed_clear: list[str] = []
        failed_set: list[str] = []
        if to_clear:
            if self._write_selection_outline_group(
                to_clear,
                _SELECTION_OUTLINE_CLEAR_GROUP_ID,
            ):
                new_previous.difference_update(to_clear)
            else:
                clear_success = False
                failed_clear = list(to_clear)
            # On failure leave to_clear paths in ``new_previous`` so the
            # next call retries the clear.
        if to_set:
            if self._write_selection_outline_group(
                to_set, _SELECTION_OUTLINE_GROUP_ID
            ):
                new_previous.update(to_set)
            else:
                set_success = False
                failed_set = list(to_set)
                if force_reapply:
                    # A forced reapply means the underlying renderer layer
                    # may have been replaced. If the set fails, do not keep
                    # pretending those selected paths are visibly outlined;
                    # leave them retryable on the next selection sync.
                    new_previous.difference_update(to_set)
        last_write = dict(getattr(self, "_selection_outline_last_write", {}) or {})
        stale_reason = last_write.get("stale_reason")
        self._selection_outline_previous_paths = new_previous
        self._selection_outline_last_write = {
            "requested_paths": list(selected),
            "applied_paths": sorted(new_previous),
            "to_clear": list(to_clear),
            "to_set": list(to_set),
            "failed_clear": failed_clear,
            "failed_set": failed_set,
            "clear_success": clear_success,
            "set_success": set_success,
            "force_reapply": bool(force_reapply),
            "generation": int(getattr(self, "_selection_outline_generation", 0)),
            "stale_reason": stale_reason,
        }

    def _mark_selection_outline_state_stale(
        self,
        *,
        reason: str,
        reset_previous: bool,
        reset_styles: bool,
    ) -> None:
        self._selection_outline_generation = (
            int(getattr(self, "_selection_outline_generation", 0)) + 1
        )
        if reset_previous:
            self._selection_outline_previous_paths = set()
        if reset_styles:
            self._selection_outline_styles_configured = False
        last = dict(getattr(self, "_selection_outline_last_write", {}) or {})
        last.update(
            {
                "stale_reason": str(reason),
                "generation": self._selection_outline_generation,
                "reset_previous": bool(reset_previous),
                "reset_styles": bool(reset_styles),
            }
        )
        self._selection_outline_last_write = last

    def _reapply_selection_outline_after_live_resync(self) -> None:
        selected_paths = list(getattr(self, "_selected_paths", []) or [])
        previous_paths = set(getattr(self, "_selection_outline_previous_paths", set()))
        if not selected_paths and not previous_paths:
            return
        self._mark_selection_outline_state_stale(
            reason="live_resync_overlay",
            reset_previous=False,
            reset_styles=True,
        )
        self.set_selection_highlight(selected_paths, force_reapply=True)

    def refresh_selection_highlight(self, paths: List[str]) -> None:
        """Force-write the current selection outline for already-selected paths.

        A newly authored prim can be selected before the live renderer snapshot
        has reloaded the mesh. The first selection write may therefore be
        accepted by the renderer bookkeeping before it is visible. This refresh
        path preserves normal clear handling but writes every current selected
        path again after the next rendered frame.
        """

        selected = list(dict.fromkeys(str(p) for p in (paths or []) if p))
        self._selected_paths = selected
        self._configure_selection_outline_styles()

        previous = set(getattr(self, "_selection_outline_previous_paths", set()))
        current = set(selected)
        to_clear = sorted(previous - current)

        new_previous: set[str] = set(previous)
        if to_clear:
            if self._write_selection_outline_group(
                to_clear,
                _SELECTION_OUTLINE_CLEAR_GROUP_ID,
            ):
                new_previous.difference_update(to_clear)
        if selected:
            if self._write_selection_outline_group(
                selected,
                _SELECTION_OUTLINE_GROUP_ID,
            ):
                new_previous.update(current)
        self._selection_outline_previous_paths = new_previous

    def pick(
        self,
        x: float,
        y: float,
        callback: Callable[[Optional[str], Optional[Tuple[float, float, float]]], None],
        query_name: str,
    ) -> None:
        """Enqueue an ovrtx GPU pick; callback resolves after the next frame.

        Picks under the same ``query_name`` follow a "latest wins" rule:
        re-issuing a pick under a still-in-flight name auto-cancels the
        prior callback. The prior query's result is still drained from
        ovrtx by :meth:`_dispatch_pending_pick_results` so a rapid
        second click cannot inherit the canceled query's hit.
        """
        if (
            self._stage is None
            or self._usd_handle is None
            or self._renderer is None
            or not hasattr(self._renderer, "enqueue_pick_query")
        ):
            callback(None, None)
            return
        try:
            left, top, right, bottom = self._ndc_rect_to_pick_pixels(x, y, x, y)
            self._renderer.enqueue_pick_query(
                self._render_product_path,
                *self._pick_pixels_to_query_rect(left, top, right, bottom),
            )
        except Exception:
            callback(None, None)
            return
        name = str(query_name or "viewport_click")
        # Latest pick under this name supersedes any in-flight one.
        self._cancel_in_flight_point(name, _PICK_CANCEL_REPLACED)
        self._pick_seq += 1
        self._in_flight_pick_queries.append(
            [self._pick_seq, "point", name, callback, None, None]
        )
        self._pick_enqueue_count += 1
        self._last_pick_pixel_rect = (left, top, right, bottom)

    def cancel_pick(self, query_name: str) -> None:
        """Cancel any in-flight point-pick callback registered under ``query_name``.

        The underlying ovrtx query has already been enqueued and will
        still surface a result on the next frame; only the Python
        callback is suppressed. The result slot is preserved in the
        FIFO so it gets drained before any replacement query's callback
        is dispatched.
        """
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
        """Enqueue an ovrtx rectangle pick; callback resolves after next frame."""
        if (
            self._stage is None
            or self._usd_handle is None
            or self._renderer is None
            or not hasattr(self._renderer, "enqueue_pick_query")
        ):
            callback([])
            return
        try:
            left, top, right, bottom = self._ndc_rect_to_pick_pixels(x0, y0, x1, y1)
            self._renderer.enqueue_pick_query(
                self._render_product_path,
                *self._pick_pixels_to_query_rect(left, top, right, bottom),
            )
        except Exception:
            callback([])
            return
        self._pick_seq += 1
        name = f"viewport_rect:{time.monotonic_ns()}"
        self._in_flight_pick_queries.append(
            [self._pick_seq, "rect", name, callback, None, None]
        )
        self._pick_enqueue_count += 1
        self._last_pick_pixel_rect = (left, top, right, bottom)

    def _configure_selection_outline_styles(self) -> None:
        if getattr(self, "_selection_outline_styles_configured", False):
            return
        renderer = getattr(self, "_renderer", None)
        setter = getattr(renderer, "set_selection_group_styles", None)
        if setter is None:
            return
        self._release_retained_output()
        try:
            style_cls = getattr(_ovrtx, "SelectionGroupStyle", None)
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
        self._selection_outline_style_calls = (
            getattr(self, "_selection_outline_style_calls", 0) + 1
        )

    def _write_selection_outline_group(
        self, paths: List[str], group_id: int
    ) -> bool:
        """Write the outline-group membership for ``paths``; return success.

        Returns ``False`` for any failure (no renderer, no writer, empty
        paths, or the underlying call raising) so callers can decide
        whether to advance their bookkeeping.
        """
        renderer = getattr(self, "_renderer", None)
        if renderer is None or not paths:
            return False
        # ovrtx 0.4 removed the ``omni:selectionOutlineGroup``
        # attribute mechanism (and its module-level attribute-name constant);
        # per-prim outline membership goes through a dedicated renderer API.
        # On such runtimes the legacy ``write_attribute`` call below is
        # accepted as a generic Fabric write but no longer drives the outline
        # pass, so the dedicated API must take precedence when present.
        #
        # Completion must be consumed before this method reports success:
        # an abandoned ovrtx ``Operation`` blocks inside ``__del__`` with a
        # ResourceWarning and SWALLOWS any completion error there, which
        # would let a failed set/clear advance the outline bookkeeping and
        # never be retried. The blocking string variant is ovrtx's own
        # ``_async(...).wait()`` wrapper — completion failures surface as
        # exceptions here and keep the paths retryable.
        group_setter = getattr(
            renderer, "set_selection_outline_group_strings", None
        )
        if group_setter is not None:
            try:
                group_setter(list(paths), int(group_id))
            except Exception:
                return False
            self._selection_outline_attribute_writes = (
                getattr(self, "_selection_outline_attribute_writes", 0) + 1
            )
            return True
        async_group_setter = getattr(
            renderer, "set_selection_outline_group_strings_async", None
        )
        if async_group_setter is not None:
            try:
                operation = async_group_setter(list(paths), int(group_id))
                wait = getattr(operation, "wait", None)
                # A waitless return value means the runtime applied the
                # write synchronously; ``wait(None)`` blocks until the
                # renderer resolves the operation (void ops return True)
                # and raises on completion failure.
                completed = wait() if callable(wait) else True
            except Exception:
                return False
            if completed is None:
                return False
            self._selection_outline_attribute_writes = (
                getattr(self, "_selection_outline_attribute_writes", 0) + 1
            )
            return True
        writer = getattr(renderer, "write_attribute", None)
        if writer is None:
            return False
        attr_name = getattr(
            _ovrtx,
            "OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP",
            _SELECTION_OUTLINE_ATTR,
        )
        tensor = np.full((len(paths),), int(group_id), dtype=np.uint8)
        try:
            writer(
                prim_paths=list(paths),
                attribute_name=attr_name,
                tensor=tensor,
            )
        except TypeError:
            try:
                writer(list(paths), attr_name, tensor)
            except Exception:
                return False
        except Exception:
            return False
        self._selection_outline_attribute_writes = (
            getattr(self, "_selection_outline_attribute_writes", 0) + 1
        )
        return True

    def _pick_query_uses_ndc(self) -> bool:
        """Whether ``enqueue_pick_query`` takes a normalized [0, 1] NDC rect.

        ovrtx >= 0.4.0 takes a normalized [0, 1] top-left NDC rectangle (and
        rejects out-of-bounds pixel values); ovrtx 0.3.x takes RenderProduct
        pixel-int rectangles. Dispatch on the resolved ovrtx package version so
        both runtimes pick correctly; unknown/non-numeric defaults to NDC.
        """
        version = getattr(self, "_ovrtx_version", None)
        if not isinstance(version, tuple):
            version = _version_tuple(getattr(_ovrtx, "__version__", "unknown"))
        if isinstance(version, tuple) and len(version) >= 2:
            return version >= (0, 4, 0)
        return True

    def _pick_pixels_to_query_rect(
        self, left: int, top: int, right: int, bottom: int
    ) -> Tuple[float, float, float, float] | Tuple[int, int, int, int]:
        """Return the pick-query rectangle in the convention the active ovrtx
        expects: normalized [0, 1] NDC for >= 0.4.0, pixel ints for 0.3.x."""
        if self._pick_query_uses_ndc():
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
        return (int(left), int(top), int(right), int(bottom))

    def _ndc_rect_to_pick_pixels(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> Tuple[int, int, int, int]:
        width, height = self._pick_resolution()
        width = max(1, int(width))
        height = max(1, int(height))

        def _clamp(v: float) -> float:
            return max(-1.0, min(1.0, float(v)))

        def _to_px(x_ndc: float, y_ndc: float) -> Tuple[int, int]:
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

    def _active_render_product_resolution(self) -> Optional[Tuple[int, int]]:
        stage = getattr(self, "_stage", None)
        product_path = str(getattr(self, "_render_product_path", "") or "")
        if stage is None or not product_path:
            return None
        try:
            prim = stage.GetPrimAtPath(product_path)
            product = _usd_render_product(prim)
            attr = product.GetResolutionAttr()
            value = attr.Get() if attr is not None else None
            if value is None:
                return None
            return (max(1, int(value[0])), max(1, int(value[1])))
        except Exception:
            return None

    def _pick_resolution(self) -> Tuple[int, int]:
        resolution = self._active_render_product_resolution()
        if resolution is None:
            resolution = getattr(self, "_last_render_product_resolution", None)
        if resolution is None:
            resolution = getattr(self, "_last_resolution", None)
        if resolution is None:
            resolution = getattr(self, "_pending_resolution", _DEFAULT_RESOLUTION)
        try:
            width, height = resolution
        except Exception:
            width, height = _DEFAULT_RESOLUTION
        return (max(1, int(width)), max(1, int(height)))

    def _cache_hits_for_replacement_pick(
        self,
        name: str,
        hits: List[Tuple[str, Tuple[float, float, float]]],
    ) -> None:
        """Attach collapsed ovrtx 0.3 hits to the live replacement pick.

        ovrtx 0.3 can collapse rapid picks on the same RenderProduct and
        expose the latest hit while the superseded FIFO slot is still at
        the adapter head. Keep that hit with the live replacement entry
        so it can be delivered when the replacement slot is drained. If
        a later frame provides a fresh hit for that live slot, the fresh
        frame wins and this cached value is ignored.
        """
        if not hits:
            return
        queue = getattr(self, "_in_flight_pick_queries", None)
        if not queue:
            return
        for entry in reversed(queue):
            if entry[1] == "point" and entry[2] == name and entry[3] is not None:
                entry[5] = list(hits)
                return

    def _dispatch_pending_pick_results(self, products: Any) -> None:
        """Drain the oldest in-flight pick query and dispatch its result.

        ovrtx surfaces queued pick queries one frame at a time and we
        cannot tell results apart by inspecting the buffer, so each
        frame consumes exactly the head of the FIFO. Entries whose
        callback was cleared by :meth:`cancel_pick` (or by a same-name
        replacement pick) still pop their result slot here without
        dispatching — that is what keeps a stale canceled hit from
        leaking into a replacement query's callback. When ovrtx 0.3
        collapses rapid same-RenderProduct picks, a non-empty result
        observed while draining a replaced slot is cached onto the live
        replacement slot instead of being discarded.
        """
        queue = getattr(self, "_in_flight_pick_queries", None)
        if not queue:
            return
        hits = self._read_pick_hits(products)
        entry = queue.popleft()
        _seq, kind, _name, cb, cancel_reason, cached_hits = entry
        self._pick_result_count = getattr(self, "_pick_result_count", 0) + 1
        effective_hits = hits or (cached_hits or [])
        if kind == "point":
            point_path = effective_hits[0][0] if effective_hits else None
            point_world = effective_hits[0][1] if effective_hits else None
            self._last_pick_path = point_path
            self._last_pick_world_point = point_world
            if cb is None:
                if cancel_reason == _PICK_CANCEL_REPLACED:
                    self._cache_hits_for_replacement_pick(_name, hits)
                return
            try:
                cb(point_path, point_world)
            except Exception:
                pass
            return
        # rect
        rect_paths = list(dict.fromkeys(path for path, _point in effective_hits if path))
        if cb is None:
            return
        try:
            cb(rect_paths)
        except Exception:
            pass

    def _dispatch_pending_pick_misses(self) -> None:
        """Fire miss callbacks for every in-flight pick and clear the queue."""
        queue = getattr(self, "_in_flight_pick_queries", None)
        if queue is None:
            return
        self._last_pick_path = None
        self._last_pick_world_point = None
        entries = list(queue)
        queue.clear()
        for _seq, kind, _name, cb, _cancel_reason, _cached_hits in entries:
            if cb is None:
                continue
            try:
                if kind == "point":
                    cb(None, None)
                else:
                    cb([])
            except Exception:
                pass

    def _read_pick_hits(
        self,
        products: Any,
    ) -> List[Tuple[str, Tuple[float, float, float]]]:
        """Read the pick-hit buffer using ovrtx's context-manager map protocol.

        ovrtx's render-var ``map(...)`` returns a context manager; the
        tensor buffer is only valid inside ``__enter__``/``__exit__``
        (see the CPU/CUDA LDR paths in :meth:`_extract_ldr_color`).
        Calling ``.unmap()`` on the returned object without entering it
        was unreliable: some mappings do not expose ``tensor`` until
        ``__enter__`` runs, which caused every pick to silently drain
        as a miss (Codex review of #67). Always use ``with`` here.
        """
        try:
            product = products[self._render_product_path]
            frame = product.frames[0]
            render_vars = getattr(frame, "render_vars", None) or {}
            rv = render_vars.get(
                getattr(_ovrtx, "OVRTX_RENDER_VAR_PICK_HIT", _PICK_HIT_VAR)
            )
            if rv is None:
                return []
            device = getattr(getattr(_ovrtx, "Device", None), "CPU", None)
        except Exception:
            return []
        try:
            cm = rv.map(device=device) if device is not None else rv.map()
            with cm as mapping:
                mapped_hits = self._parse_pick_hit_mapping(mapping)
                if mapped_hits is not None:
                    return mapped_hits
                try:
                    data = mapping.tensor.to_bytes()
                except Exception:
                    data = b""
        except Exception:
            return []
        return self._parse_pick_hit_buffer(data)

    def _parse_pick_hit_mapping(
        self,
        mapping: Any,
    ) -> Optional[List[Tuple[str, Tuple[float, float, float]]]]:
        """Parse ovrtx 0.3's named multi-tensor pick-hit schema.

        Returns ``None`` when ``mapping`` is not the 0.3 schema so callers
        can fall back to the legacy packed-buffer path used by older fakes.
        """
        try:
            tensor_names = set(mapping.keys())
        except Exception:
            return None
        if "primPath" not in tensor_names or "worldPositionM" not in tensor_names:
            return None

        magic = self._read_pick_hit_param(mapping, "magic")
        version = self._read_pick_hit_param(mapping, "version")
        hit_count = self._read_pick_hit_param(mapping, "hitCount")
        expected_magic = int(
            getattr(
                _ovrtx,
                "OVRTX_PICK_HIT_MAGIC",
                getattr(_ovrtx, "OVRTX_PICK_HIT_BUFFER_MAGIC", _PICK_HIT_BUFFER_MAGIC),
            )
        )
        expected_version = int(
            getattr(
                _ovrtx,
                "OVRTX_PICK_HIT_VERSION",
                getattr(
                    _ovrtx,
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
            world_positions = np.from_dlpack(mapping["worldPositionM"]).copy()
            world_positions = world_positions.reshape((-1, 3))
        except Exception:
            return []

        hits: List[Tuple[str, Tuple[float, float, float]]] = []
        count = min(int(hit_count), len(prim_paths), len(world_positions))
        for i in range(count):
            path = self._resolve_ovrtx_prim_path(int(prim_paths[i]))
            if not path:
                continue
            wx, wy, wz = world_positions[i]
            hits.append((path, (float(wx), float(wy), float(wz))))
        return hits

    def _read_pick_hit_param(self, mapping: Any, name: str) -> Optional[int]:
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
    ) -> List[Tuple[str, Tuple[float, float, float]]]:
        if len(data) < _PICK_HIT_HEADER.size:
            return []
        magic, version, hit_count, stride = _PICK_HIT_HEADER.unpack_from(data, 0)
        expected_magic = int(
            getattr(_ovrtx, "OVRTX_PICK_HIT_BUFFER_MAGIC", _PICK_HIT_BUFFER_MAGIC)
        )
        expected_version = int(
            getattr(
                _ovrtx,
                "OVRTX_PICK_HIT_BUFFER_VERSION",
                _PICK_HIT_BUFFER_VERSION,
            )
        )
        if magic != expected_magic or version != expected_version or hit_count <= 0:
            return []
        if stride < _PICK_HIT_RECORD.size:
            return []
        hits: List[Tuple[str, Tuple[float, float, float]]] = []
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
        renderer = getattr(self, "_renderer", None)
        public_resolver = getattr(renderer, "resolve_prim_path_id", None)
        if public_resolver is not None:
            try:
                path = public_resolver(int(prim_path_id))
            except Exception:
                path = None
            path = str(path or "")
            if path.startswith(_SESSION_ROOT_PATH):
                return None
            return path if path.startswith("/") else None
        resolver = getattr(renderer, "_get_path_dict", None)
        if resolver is None:
            return None
        try:
            path = resolver().prim_path_to_string(prim_path_id)
        except Exception:
            return None
        path = str(path or "")
        if path.startswith(_SESSION_ROOT_PATH):
            return None
        return path if path.startswith("/") else None

    # ── Shutdown ──

    def shutdown(self) -> None:
        """Release GPU resources and any temp files we created.

        Pending pick/rect callbacks are fired with miss results so
        their closures are released deterministically — otherwise a
        viewport-tear-down with picks in flight would retain those
        callbacks (and whatever they captured) until GC eventually
        cleared the renderer adapter.
        """
        # Ownership: a retained step-result container must never outlive the
        # native renderer handle (dropping ``_renderer`` below is the LAST
        # reference and triggers native teardown).
        self._ensure_native_cleanup_tracking()
        # Native ownership mutation is forbidden until the retained step
        # output is unconditionally released (enforced by the ownership
        # audit).  A release failure aborts before any teardown mutation.
        self._release_retained_output()
        first_fault: Optional[BaseException] = None
        try:
            self._dispatch_pending_pick_misses()
        except BaseException as error:  # noqa: BLE001
            first_fault = self._chain_faults(first_fault, error)
        livestream = getattr(self, "_livestream", None)
        if livestream is not None:
            try:
                livestream.close()
            except BaseException as error:  # noqa: BLE001
                first_fault = self._chain_faults(first_fault, error)
            else:
                self._livestream = None
        try:
            self._remove_ovrtx_layers(allow_renderer_drop=True)
        except BaseException as error:  # noqa: BLE001
            first_fault = self._chain_faults(first_fault, error)

        # Any native/livestream refusal keeps the renderer and all logical
        # ownership retryable.  A drained pick callback fault has no remaining
        # owner, so native shutdown may complete before that primary escapes.
        self._refresh_native_cleanup_state()
        native_refusal = bool(
            self._native_scene_unresolved
            or getattr(self, "_usd_handle", None) is not None
            or getattr(self, "_session_handle", None) is not None
            or bool(getattr(self, "_live_resync_handles", None))
            or (
                livestream is not None
                and getattr(self, "_livestream", None) is livestream
            )
        )
        # An unresolved rollback root is authoritatively neutralized by the
        # renderer destruction below, but only after every independently
        # removable owner has succeeded.
        restore = self._native_restore_obligation
        if restore is not None:
            only_restore_unresolved = (
                not self._native_cleanup_obligations
                and not self._current_native_cleanup_diagnostics
                and getattr(self, "_usd_handle", None) is None
                and getattr(self, "_session_handle", None) is None
                and not bool(getattr(self, "_live_resync_handles", None))
            )
            if only_restore_unresolved:
                native_refusal = False

        if native_refusal:
            if first_fault is not None:
                raise first_fault
            error = self._native_scene_unresolved_error
            if error is not None:
                raise error
            raise RuntimeError("native renderer shutdown remains unresolved")

        # ``ovrtx.Renderer.__del__`` destroys the GPU handle — dropping
        # our reference by setting the attribute is enough; the refcount
        # falling to zero triggers the destructor.
        self._renderer = None
        if restore is not None:
            snapshot = restore.prospective_snapshot
            if snapshot is not None:
                try:
                    os.unlink(snapshot)
                except FileNotFoundError:
                    pass
                except BaseException as error:  # noqa: BLE001
                    # Native composition is already neutralized, but the
                    # owned file remains a retryable cleanup obligation.
                    self._add_native_cleanup_obligation(
                        owner="neutralized-rollback-snapshot",
                        handle=None,
                        snapshot=snapshot,
                        origin="renderer-drop",
                        primary=restore.primary,
                        error=error,
                    )
                    raise error
            self._native_restore_obligation = None
        self._drop_owned_tmp_path()
        self._stage = None
        self._refresh_native_cleanup_state()
        if first_fault is not None:
            raise first_fault

    def _drop_owned_tmp_path(self) -> None:
        """Remove the anonymous-stage tempfile if we own one."""
        if self._owned_tmp_path is None:
            return
        try:
            os.unlink(self._owned_tmp_path)
        except OSError:
            # Best effort — file may already be gone if someone swept /tmp.
            pass
        self._owned_tmp_path = None


def _normalize_rgba(arr: np.ndarray, width: int, height: int) -> np.ndarray:
    """Coerce ``arr`` to an ``(H, W, 4)`` uint8 contiguous array.

    ovrtx's ``LdrColor`` is documented as RGBA uint8, but we defend
    against a shape/dtype drift by handling RGB → RGBA padding and
    float → uint8 conversion. The returned array is always a fresh
    contiguous buffer — safe to hand to ``ByteImageProvider`` which
    will read from it repeatedly.
    """
    if arr.dtype != np.uint8:
        # ovrtx normally returns normalized float LdrColor, but resize
        # transitions can surface byte-range float buffers. Preserve
        # byte-range data instead of multiplying it into an all-white image.
        finite_max = float(np.nanmax(arr)) if arr.size else 0.0
        scale = 255.0 if finite_max <= 1.0 else 1.0
        arr = np.clip(arr * scale, 0, 255).astype(np.uint8)
    if arr.ndim == 3 and arr.shape[2] == 3:
        alpha = np.full((arr.shape[0], arr.shape[1], 1), 255, dtype=np.uint8)
        arr = np.concatenate([arr, alpha], axis=2)
    if arr.ndim != 3 or arr.shape[2] != 4:
        return np.zeros((height, width, 4), dtype=np.uint8)
    # Resize to the requested size (ovrtx may return the native
    # render-product resolution which can drift from the requested one
    # during viewport resize). Resampling the whole image preserves the
    # view; top-left crop/pad makes the frame appear blown out or zoomed.
    h, w = arr.shape[0], arr.shape[1]
    if h != height or w != width:
        if h <= 0 or w <= 0:
            return np.zeros((height, width, 4), dtype=np.uint8)
        y_idx = np.linspace(0, h - 1, int(height)).round().astype(np.intp)
        x_idx = np.linspace(0, w - 1, int(width)).round().astype(np.intp)
        return np.ascontiguousarray(arr[y_idx[:, None], x_idx[None, :], :])
    return np.ascontiguousarray(arr)
