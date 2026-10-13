# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace as _dataclass_replace
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
    ZeroCopyState,
)
from ovui_data_adapters.common._ldr_overlap import (
    CameraSnapshot,
    LdrOverlapState,
    camera_state_differs,
)
from ovui_data_adapters.common.instrumentation import get_instrumentation
from ovui_data_adapters.common.ovrtx_import import import_ovrtx
from ovui_data_adapters.common.render_settings import (
    CAMERA_OWNER_SCOPE as _CAMERA_OWNER_SCOPE,
    RENDER_SETTINGS_OWNER_SCOPE as _RENDER_SETTINGS_OWNER_SCOPE,
    RenderSettingLifecycle,
    build_render_setting_builtin_spec_index,
    render_setting_owner_scope,
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

# The prim OVRTX itself resolves for globally owned render settings.
# ``RenderProductPrim::getStageRenderSettings`` (omni.usd-abi) tries the stage
# metadatum ``renderSettingsPrimPath`` first and falls back to
# ``kRenderRoot``/``OmniverseGlobalRenderSettings``; when neither exists it
# DEFINES this prim on its own runtime stage. The metadata leg was measured
# to be ignored by the installed build, so this literal path is the only
# owner OVRTX honours (see OWNER-ROUTE, routes ``b`` vs ``c``/``e``); the
# scope itself is ``_RENDER_SETTINGS_OWNER_SCOPE``, imported above.
_RENDER_SETTINGS_OWNER_ROOT_PATH = "/Render"
_RENDER_SETTINGS_OWNER_PATH = "/Render/OmniverseGlobalRenderSettings"
_RENDER_SETTINGS_OWNER_TYPE = "RenderSettings"

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


# Canonical RenderVar source names this adapter renders and decodes: the
# display color first, then every output in ``_RENDER_VAR_OUTPUT_SPECS``.
_RENDER_VAR_SOURCE_NAMES = (
    "LdrColor",
    "HdrColor",
    "DiffuseAlbedoSD",
    "DepthSD",
    "DistanceToCameraSD",
    "DistanceToImagePlaneSD",
    "NormalSD",
    "Camera3dPositionSD",
    "SemanticSegmentation",
    "SemanticIdMap",
)


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


_RENDER_SETTINGS_PROVIDER_ID = ""
_RENDER_SETTINGS_PROVIDER_LABEL = ""
_RENDER_SETTINGS_PUBLIC_NAMESPACES: Tuple[str, ...] = ()
_RENDER_SETTINGS_METADATA_KEY = ""
_RENDER_SETTINGS_GROUP_FALLBACK = ""
_RENDER_SETTINGS_GROUP_LABEL_FALLBACK = ""
_RENDER_SETTINGS_BUILTIN_SPECS: Tuple[dict[str, Any], ...] = ()
#: ``attr_name`` -> spec index over the tuple above. The catalog is
#: rebuilt per request and the declared setting surface is large, so a
#: linear scan per attribute is quadratic; the index is rebuilt only
#: when a schema is installed.
_RENDER_SETTINGS_BUILTIN_SPEC_INDEX: dict[str, dict[str, Any]] = {}
_SESSION_CAMERA_PRIM_METADATA_LINES: Tuple[str, ...] = ()
_SESSION_CAMERA_ATTRIBUTE_LINES: Tuple[str, ...] = ()
_RENDER_SETTINGS_CATALOG_REVISION_FN: Callable[[Any], Any] = repr


def configure_render_settings_schema(
    *,
    provider_id: str,
    provider_label: str,
    public_namespaces: Tuple[str, ...],
    metadata_key: str,
    group_fallback: str,
    group_label_fallback: str,
    builtin_specs: Tuple[dict[str, Any], ...],
    session_camera_prim_metadata_lines: Tuple[str, ...] = (),
    session_camera_attribute_lines: Tuple[str, ...] = (),
    catalog_revision_fn: Callable[[Any], Any] = repr,
) -> None:
    """Install an opaque optional renderer-property schema."""

    global _RENDER_SETTINGS_PROVIDER_ID
    global _RENDER_SETTINGS_PROVIDER_LABEL
    global _RENDER_SETTINGS_PUBLIC_NAMESPACES
    global _RENDER_SETTINGS_METADATA_KEY
    global _RENDER_SETTINGS_GROUP_FALLBACK
    global _RENDER_SETTINGS_GROUP_LABEL_FALLBACK
    global _RENDER_SETTINGS_BUILTIN_SPECS
    global _RENDER_SETTINGS_BUILTIN_SPEC_INDEX
    global _SESSION_CAMERA_PRIM_METADATA_LINES
    global _SESSION_CAMERA_ATTRIBUTE_LINES
    global _RENDER_SETTINGS_CATALOG_REVISION_FN
    _RENDER_SETTINGS_PROVIDER_ID = str(provider_id)
    _RENDER_SETTINGS_PROVIDER_LABEL = str(provider_label)
    _RENDER_SETTINGS_PUBLIC_NAMESPACES = tuple(public_namespaces)
    _RENDER_SETTINGS_METADATA_KEY = str(metadata_key)
    _RENDER_SETTINGS_GROUP_FALLBACK = str(group_fallback)
    _RENDER_SETTINGS_GROUP_LABEL_FALLBACK = str(group_label_fallback)
    _RENDER_SETTINGS_BUILTIN_SPECS = tuple(dict(spec) for spec in builtin_specs)
    _RENDER_SETTINGS_BUILTIN_SPEC_INDEX = build_render_setting_builtin_spec_index(
        _RENDER_SETTINGS_BUILTIN_SPECS
    )
    _SESSION_CAMERA_PRIM_METADATA_LINES = tuple(session_camera_prim_metadata_lines)
    _SESSION_CAMERA_ATTRIBUTE_LINES = tuple(session_camera_attribute_lines)
    _RENDER_SETTINGS_CATALOG_REVISION_FN = catalog_revision_fn


def _render_setting_builtin_spec(attr_name: str) -> dict[str, Any] | None:
    return _RENDER_SETTINGS_BUILTIN_SPEC_INDEX.get(attr_name)


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


class _RenderSettingsSubscription:
    """RAII handle for one render-settings change subscription."""

    def __init__(self, cancel: Callable[[], None]) -> None:
        self._cancel = cancel

    def cancel(self) -> None:
        cancel = self._cancel
        self._cancel = None
        if callable(cancel):
            cancel()


def _stage_change_touches_public_render_settings(
    paths: Any,
    active_product_path: str = "",
) -> bool:
    """Whether a changed path authors a public setting on the ACTIVE product.

    Public settings edits on OTHER RenderProducts are not part of this
    adapter's catalog and must not produce (first-)events for subscribers.
    An empty ``active_product_path`` matches nothing.
    """

    product = str(active_product_path or "")
    if not product:
        return False
    for raw_path in tuple(paths or ()):
        text = str(raw_path)
        prim_text, separator, property_text = text.partition(".")
        if not separator or prim_text != product:
            continue
        if any(
            property_text.startswith(namespace)
            for namespace in _RENDER_SETTINGS_PUBLIC_NAMESPACES
        ):
            return True
    return False


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


#: Runtime-verified role-compatible USD declarations per authoritative
#: builtin spelling.  The effective native column follows the authored
#: declaration for every listed variant (``int`` populates a valid int32
#: column, ``uint`` a uint32 column) and the unchanged provider transaction
#: updates either coherently through the real application path
#: (full-application GPU probes 2026-07-16; pinned
#: ``tests/docs/python/test_attribute_read.py`` documents that the native
#: 32-bit integer storage may be signed or unsigned depending on the schema,
#: and ``skills/render-settings/SKILL.md`` documents the int32 write path).
_RENDER_SETTING_ROLE_COMPATIBLE_USD_TYPES: dict[str, tuple[str, ...]] = {
    "uint": ("int",),
    "int": ("uint",),
}


def _render_setting_native_type_conflict(attr: Any) -> str:
    """Concrete reason when an authored builtin cannot carry the native type.

    The mapped RenderProduct builtins have runtime-authoritative native
    column roles. Compatibility is
    classified from the live authored attribute against the builtin's role:

    - the authoritative generated-schema spelling is always compatible (it
      is also what absent-attribute creation authors);
    - runtime-verified role variants stay editable with their EFFECTIVE
      USD/native type preserved (signed/unsigned 32-bit integers — the
      write payload derives from the descriptor's effective ``usd_type``,
      so the established native int32/uint32 column keeps its dtype and
      exact value);
    - role-only spellings that share the exact underlying value type
      (``float3`` vs ``color3f``, both ``GfVec3f``) are compatible;
    - everything else (e.g. ``string``/``float`` on the integer builtin,
      ``string`` on the ``token`` render mode) would silently desynchronize
      or mis-type the native store, so the edit fails truthfully instead.
    """

    attr_name = str(attr.GetName())
    spec = _render_setting_builtin_spec(attr_name)
    if spec is None:
        return ""
    expected_key = str(spec.get("usd_type") or "").lower()
    expected = _render_setting_usd_type_name(expected_key)
    if expected is None:
        return ""
    try:
        actual = attr.GetTypeName()
    except Exception:
        return ""
    if not actual:
        return ""
    if actual == expected or actual.type == expected.type:
        return ""
    if str(actual).lower() in _RENDER_SETTING_ROLE_COMPATIBLE_USD_TYPES.get(
        expected_key, ()
    ):
        return ""
    return (
        f"RenderProduct builtin {attr_name!r} is authored with USD type "
        f"{str(actual)!r}, but the native runtime column requires the exact "
        f"type {str(expected)!r}; retype or remove the authored attribute "
        "before editing this setting."
    )


#: Shared with the OVStage adapter: one classification, one fallback.
_render_setting_owner_scope = render_setting_owner_scope


def _render_setting_owner_path(
    stage: Any,
    descriptor: RenderSettingDescriptor,
) -> str:
    """Prim that authoritatively owns this setting.

    Most settings are owned by the active RenderProduct. Exposure and
    auto-exposure are owned by the Camera the product references, so they are
    resolved through that relationship instead of being authored onto the
    product where the renderer would never read them. Globally owned settings
    resolve to the prim OVRTX itself resolves — never to the product, which
    the renderer would never read them from. An owner that cannot be resolved
    yields an empty path so the caller fails closed.
    """

    product_path = str(descriptor.metadata.get("render_product_path") or "")
    owner_scope = _render_setting_owner_scope(descriptor)
    if owner_scope == "RenderProduct":
        return product_path
    if owner_scope == _RENDER_SETTINGS_OWNER_SCOPE:
        # The owner is a fixed, adapter-owned prim; it is only addressable
        # while a document is loaded, because the value reaches the renderer
        # through that document's root snapshot.
        return _RENDER_SETTINGS_OWNER_PATH if stage is not None else ""
    if owner_scope != _CAMERA_OWNER_SCOPE or not product_path:
        return ""
    try:
        product = stage.GetPrimAtPath(product_path)
        if not product or not product.IsValid():
            return ""
        relationship = product.GetRelationship("camera")
        targets = relationship.GetTargets() if relationship else ()
    except Exception:
        return ""
    # Exactly one referenced camera is authoritative; anything else is
    # ambiguous and must not be authored.
    return str(targets[0]) if len(targets) == 1 else ""


def _render_setting_attr_for_descriptor(
    stage: Any,
    descriptor: RenderSettingDescriptor,
    *,
    create: bool = False,
) -> Any:
    product_path = _render_setting_owner_path(stage, descriptor)
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
    if _render_setting_owner_scope(descriptor) == _RENDER_SETTINGS_OWNER_SCOPE:
        # The globally owned prim lives on the adapter's own hidden stage,
        # whose root layer is already the edit target; retargeting the user
        # document's session layer would author nowhere useful.
        return None
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


def _mapped_render_var_tensor(mapping: Any) -> Any:
    # ovrtx 0.5 removed ``MappedRenderVar.tensor``; a single-tensor mapping
    # is itself the DLPack tensor (``shape``, ``dtype``, ``data``).
    return getattr(mapping, "tensor", mapping)


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
        # ovrtx 0.5 keys render vars by full RenderVar path.
        descriptor.metadata.get("render_var_path", ""),
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


def _renderer_config_with_overrides(config: Any, overrides: Mapping[str, Any]) -> Any:
    """Copy ``config`` with ``overrides`` applied, leaving the original untouched.

    A ``RENDERER_CONFIG_RECREATE`` setting's real owner is a public
    ``RendererConfig`` field, so the rebuilt renderer must carry the new field
    value while every other field this adapter negotiated (attach mode, Vulkan,
    selection outline, GPU selection, log path) survives verbatim.
    """

    if not overrides or config is None:
        return config
    import dataclasses  # noqa: PLC0415 — only needed on the rebuild path

    if dataclasses.is_dataclass(config):
        known = {field_.name for field_ in dataclasses.fields(config)}
        return dataclasses.replace(
            config,
            **{name: value for name, value in overrides.items() if name in known},
        )
    for name, value in overrides.items():
        setattr(config, name, value)
    return config


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

# Numeric UsdGeomCamera properties consumed by OVRTX's live attribute writer.
# Projection/schema changes and relationships retain structural handling.
# Kit viewport metadata on cameras: the orbit target. The viewport's camera writer authors it at the
# end of every navigation gesture; as an unknown property it reloaded the whole scene (~0.55 s on a
# five-prim stage), so every orbit, pan, zoom or fly ended with a visible freeze.
_KIT_VIEWPORT_METADATA = ("omni:kit:centerOfInterest",)

_LIVE_CAMERA_ATTRIBUTE_TYPES = {
    "focalLength": "float",
    "focusDistance": "float",
    "fStop": "float",
    "horizontalAperture": "float",
    "verticalAperture": "float",
    "horizontalApertureOffset": "float",
    "verticalApertureOffset": "float",
    "clippingRange": "float2",
}

# Value inputs of existing lights and shaders that OVRTX updates in place with
# write_attribute. OVRTX requires the attribute's exact dtype (it rejects a
# float64 payload for a float input). Asset-valued and connected inputs, shader
# identity (info:*), material bindings and schema changes stay structural.
_LIVE_INPUT_DTYPES = {
    "float": (np.float32, None),
    "bool": (np.bool_, None),
    "int": (np.int32, None),
    "float3": (np.float32, 3),
    "color3f": (np.float32, 3),
}
_LIVE_LIGHT_INPUTS = frozenset(
    {
        "inputs:intensity",
        "inputs:exposure",
        "inputs:color",
        "inputs:colorTemperature",
        "inputs:enableColorTemperature",
        "inputs:radius",
        "inputs:width",
        "inputs:height",
        "inputs:length",
        "inputs:angle",
        "inputs:diffuse",
        "inputs:specular",
    }
)


def _stage_change_path_is_session(path: Any) -> bool:
    path_str = str(path)
    return path_str == _SESSION_ROOT_PATH or path_str.startswith(
        f"{_SESSION_ROOT_PATH}/"
    )


def _build_session_usda(
    resolution: Tuple[int, int],
    include_fallback_dome: bool,
    camera_path: str = _CAMERA_PATH,
    camera_projection: str = "perspective",
    camera_setting_lines: Tuple[str, ...] = (),
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
    projection_token = (
        "orthographic" if camera_projection == "orthographic" else "perspective"
    )
    render_product_device_ids = ", ".join(
        str(device_id) for device_id in _PICK_RENDER_PRODUCT_DEVICE_IDS
    )
    render_product_setting_block = ""
    if render_product_setting_lines:
        render_product_setting_block = "\n" + "\n".join(render_product_setting_lines)
    camera_metadata_block = ""
    if _SESSION_CAMERA_PRIM_METADATA_LINES:
        camera_metadata_block = " (\n" + "\n".join(
            f"            {line}" for line in _SESSION_CAMERA_PRIM_METADATA_LINES
        ) + "\n        )"
    camera_attribute_block = ""
    camera_lines = tuple(_SESSION_CAMERA_ATTRIBUTE_LINES) + tuple(
        camera_setting_lines
    )
    if camera_lines:
        camera_attribute_block = "".join(
            f"            {line.strip()}\n" for line in camera_lines
        )
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
        def Camera "Main"{camera_metadata_block}
        {{
{camera_attribute_block}\
            float focalLength = 18
            float horizontalAperture = 20.955
            float verticalAperture = 15.2908
            float2 clippingRange = (0.01, 10000)
            float fStop = 0
            token projection = "{projection_token}"
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


def _render_setting_default_usda_line(attr_name: str) -> str | None:
    """USDA line stating a builtin's declared default explicitly."""

    spec = _render_setting_builtin_spec(attr_name)
    if not spec:
        return None
    usd_type = str(spec.get("usd_type") or "")
    if not usd_type or "default" not in spec:
        return None
    value = _render_setting_python_value(spec.get("default"))
    if value is None:
        return None
    return f"            {usd_type} {attr_name} = {_usda_value_literal(value)}"


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


_PICK_RAY_MAX_TRIANGLES = 2_000_000


def _ray_prim_parameter(prim: Any, origin: np.ndarray, direction: np.ndarray) -> Optional[float]:
    """First ``t >= 0`` where ``origin + t * direction`` meets ``prim`` (local space)."""
    from pxr import UsdGeom

    if prim.IsA(UsdGeom.Cube):
        half = 0.5 * float(UsdGeom.Cube(prim).GetSizeAttr().Get() or 2.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            t0 = (-half - origin) / direction
            t1 = (half - origin) / direction
        near = np.nanmax(np.minimum(t0, t1))
        far = np.nanmin(np.maximum(t0, t1))
        if not np.isfinite(near) or near > far or far < 0:
            return None
        return float(near if near >= 0 else far)
    if prim.IsA(UsdGeom.Sphere):
        radius = float(UsdGeom.Sphere(prim).GetRadiusAttr().Get() or 1.0)
        a = float(direction @ direction)
        b = 2.0 * float(origin @ direction)
        c = float(origin @ origin) - radius * radius
        disc = b * b - 4 * a * c
        if a <= 0 or disc < 0:
            return None
        roots = sorted(((-b - math.sqrt(disc)) / (2 * a), (-b + math.sqrt(disc)) / (2 * a)))
        return next((float(t) for t in roots if t >= 0), None)
    if prim.IsA(UsdGeom.Mesh):
        mesh = UsdGeom.Mesh(prim)
        points = np.asarray(mesh.GetPointsAttr().Get() or [], dtype=np.float64).reshape(-1, 3)
        counts = np.asarray(mesh.GetFaceVertexCountsAttr().Get() or [], dtype=np.int64)
        indices = np.asarray(mesh.GetFaceVertexIndicesAttr().Get() or [], dtype=np.int64)
        if not len(points) or not len(counts) or counts.sum() != len(indices):
            return None
        if int(np.maximum(counts - 2, 0).sum()) > _PICK_RAY_MAX_TRIANGLES:
            return None
        # Fan-triangulate every face: (v0, v[k+1], v[k+2]) for k in 0..count-3.
        starts = np.cumsum(counts) - counts
        triangles = np.maximum(counts - 2, 0)
        face = np.repeat(np.arange(len(counts)), triangles)
        k = np.arange(len(face)) - (np.cumsum(triangles) - triangles)[face]
        base = starts[face]
        try:
            v0 = points[indices[base]]
            v1 = points[indices[base + k + 1]]
            v2 = points[indices[base + k + 2]]
        except IndexError:
            return None
        # Moller-Trumbore, vectorized over triangles.
        e1, e2 = v1 - v0, v2 - v0
        p = np.cross(direction, e2)
        det = np.einsum("ij,ij->i", e1, p)
        valid = np.abs(det) > 1e-12
        inv = np.where(valid, 1.0 / np.where(valid, det, 1.0), 0.0)
        tvec = origin - v0
        u = np.einsum("ij,ij->i", tvec, p) * inv
        q = np.cross(tvec, e1)
        v = (q @ direction) * inv
        t = np.einsum("ij,ij->i", e2, q) * inv
        hit = valid & (u >= 0) & (v >= 0) & (u + v <= 1) & (t >= 0)
        return float(t[hit].min()) if hit.any() else None
    return None


def _pick_surface_point(
    stage: Any,
    path: str,
    view: Any,
    projection: Any,
    ndc_x: float,
    ndc_y: float,
) -> Optional[Tuple[float, float, float]]:
    """World point where the pick ray through NDC ``(x, y)`` first meets ``path``.

    ``view``/``projection`` are the GL column-vector matrices of the rendered
    frame (y up, depth -1..1). Supports Cube, Sphere and Mesh prims; returns
    None for other geometry, missing prims or a ray that misses the prim.
    """
    try:
        from pxr import Usd, UsdGeom

        prim = stage.GetPrimAtPath(str(path)) if stage is not None and path else None
        if not prim or not prim.IsA(UsdGeom.Gprim):
            return None
        inverse = np.linalg.inv(
            np.asarray(projection, dtype=np.float64).reshape(4, 4)
            @ np.asarray(view, dtype=np.float64).reshape(4, 4)
        )
        near = inverse @ np.array([ndc_x, ndc_y, -1.0, 1.0])
        far = inverse @ np.array([ndc_x, ndc_y, 1.0, 1.0])
        near, far = near[:3] / near[3], far[:3] / far[3]
        # USD row-vector matrices; the ray parameter survives the affine map.
        world = np.asarray(
            UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default()),
            dtype=np.float64,
        )
        to_local = np.linalg.inv(world)
        origin = (np.append(near, 1.0) @ to_local)[:3]
        direction = (np.append(far, 1.0) @ to_local)[:3] - origin
        t = _ray_prim_parameter(prim, origin, direction)
        if t is None or t > 1.0:
            return None
        point = np.append(origin + t * direction, 1.0) @ world
        return (float(point[0]), float(point[1]), float(point[2]))
    except Exception:
        return None


class OvRtxRendererAdapter(RendererAdapter):
    """Concrete :class:`RendererAdapter` that delegates to ``ovrtx.Renderer``.

    Requires ``ovrtx`` and a compatible NVIDIA GPU. Module-level
    :data:`AVAILABLE` reports whether the library imported cleanly;
    constructing the adapter on an unavailable system raises
    :class:`RuntimeError`.
    """

    _camera_projection_mode: str = "perspective"
    # Property-name prefixes of metadata a host authors but nothing renders
    # (for example collaboration presence). Edits to them never reach ovrtx
    # and never reload the scene.
    non_rendering_property_prefixes: tuple[str, ...] = ()

    def _non_rendering_prefixes(self) -> tuple[str, ...]:
        """Host-declared non-rendering prefixes plus Kit viewport metadata RTX never renders."""
        return (*self.non_rendering_property_prefixes, *_KIT_VIEWPORT_METADATA)

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
        # Set once a rebuild for a process-global setting destroyed the old
        # renderer without standing up a replacement: this adapter can never
        # rebuild again, and every global row must say so.
        self._global_setting_rebuild_fault: str = ""
        # Retained so a process-global setting whose owner is a public
        # RendererConfig field can rebuild the renderer from the exact
        # negotiated configuration instead of reading it back off the
        # native handle.
        self._renderer_config = config
        get_instrumentation().prepare_renderer_config(self, config)
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
        # Usd.Stage layer muting is stage-local and does not emit a useful
        # ObjectsChanged notice.  Remember the composition state represented
        # by the native renderer so render_frame can detect that boundary.
        self._loaded_muted_layer_identifiers: tuple[str, ...] = ()
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
        self._camera_projection_mode: str = "perspective"
        self._dt_clock: float = time.perf_counter()
        # Clock injection point — tests override to drive the debounce
        # timers deterministically without real wall-clock waits.
        self._clock: Callable[[], float] = time.perf_counter
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
        # The ovrtx outline pass does not show newly written membership in a
        # converged, camera-static render until one renderer.reset() runs
        # after membership exists (same contract as the OVStage adapter's
        # activation reset). Armed on construction, root reload, and session
        # reinjects that happen while no outline membership is applied.
        self._selection_outline_pass_needs_reset: bool = True
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
        self._pick_query_products: dict[int, str] = {}
        self._pick_query_waits: dict[int, int] = {}
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
        # Presented-frame bookkeeping read by the inspector state endpoint.
        self._successful_frame_count = 0
        self._last_frame_nonblack_pixels: int | None = None
        self._last_frame_shape: tuple[int, ...] | None = None
        # RenderProducts a host presents together (see
        # :meth:`set_render_product_group`); the camera state each last wrote
        # into the renderer; and CPU images the latest group step rendered
        # for the others, keyed like the camera state.
        self._render_product_group: frozenset[str] = frozenset()
        self._grouped_cameras: dict[str, tuple] = {}
        self._grouped_frames: dict[str, tuple] = {}
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
        # Render Settings change observers: tokenized
        # (token, callback) records notified through the snapshot-deduped
        # publisher after successful apply/reset and when live stage edits
        # (external editors, undo/redo, product resyncs) change the public
        # RenderProduct settings state.
        self._render_settings_subscribers: list[tuple[object, Callable[[], None]]] = []
        self._render_settings_last_snapshot: tuple | None = None
        self._latest_render_var_output_frames: dict[
            tuple[str, str, str],
            RenderVarOutputFrame,
        ] = {}

        # Optional native pacing borrows (but never owns) the Python-created
        # renderer between the matching start and stop/drain calls.
        self._frame_pacing_provider: Any = None
        self._frame_pacing_token: int = 0
        self._frame_pacing_needs_sync_step: bool = True
        self._frame_pacing_size: tuple[int, int] | None = None
        self._frame_pacing_projection: np.ndarray | None = None
        self._frame_pacing_camera_path: str = ""
        self._frame_pacing_last_raw_world: np.ndarray | None = None
        self._frame_pacing_last_intent_time: float = 0.0
        self._frame_pacing_restore_overlap: bool = False
        self._frame_pacing_pick_snapshot: CameraSnapshot | None = None
        self._frame_pacing_presented_snapshot: CameraSnapshot | None = None
        self._frame_pacing_pick_generated: bool = False
        self._frame_pacing_pick_association_unavailable: bool = False
        self._frame_pacing_render_paused: bool = False

    def _native_render_is_paused(self) -> bool:
        """Report the pick lease state safely on compatibility instances.

        Partially constructed and compatibility adapters predate this state,
        so every read goes through the same defensive accessor already used
        for the pacing token.
        """

        return bool(getattr(self, "_frame_pacing_render_paused", False))

    def set_zero_copy_state(self, state: Optional[ZeroCopyState]) -> None:
        """Share zero-copy coordination state with the viewport bridge."""
        self._zero_copy_state = state

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
        whose existing resume handshake revalidates the renderer, camera,
        resolution, and pick-query state before returning ownership to the
        native worker.
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
            "_native_frame_pacing_start",
            "_native_frame_pacing_publish",
            "_native_frame_pacing_stop",
            "_native_frame_pacing_pause_render",
            "_native_frame_pacing_resume_render",
            "_get_present_rate",
            "_get_native_frame_pacing_status",
        )
        if not all(callable(getattr(native_ui, name, None)) for name in names):
            return None
        return native_ui

    def _frame_pacing_eligible(self) -> bool:
        # The native worker steps one product; a group must keep stepping all.
        if len(getattr(self, "_render_product_group", ())) > 1:
            return False
        native_ui = self._frame_pacing_bindings()
        if native_ui is None or float(native_ui._get_present_rate()) == 0.0:
            return False
        if (
            self._renderer is None
            or self._stage is None
            or self._usd_handle is None
            or self._frame_pacing_provider is None
            or self._livestream is not None
            or self._point_cloud_requests
            or self._render_var_output_requests
        ):
            return False
        # Native pacing publishes GPU-resident images itself, so a pending
        # Python zero-copy request no longer competes with it: while a session
        # owns the renderer borrow, render_frame never runs and the legacy
        # GpuFrame path stays dormant. Refusing pacing here is what left the
        # ordinary launcher, which requests zero-copy, permanently unpaced.
        # `_ldr_overlap_allowed` keeps its own gate: that path really does
        # share the Python GpuFrame mechanism.
        if getattr(self._renderer, "_attached_ovstage", None) is not None:
            return False
        return True

    def _borrow_native_renderer(self) -> tuple[int, str, int, int, int] | None:
        """Validate and describe the usable OVRTX native borrow."""

        if not self._frame_pacing_eligible():
            return None
        import ctypes

        # The installed ctypes wrapper does not expose a public borrow
        # accessor. Keep this bridge isolated as plain wrapper state so
        # renderer capabilities never escape through normal adapter paths.
        wrapper_state = self.__dict__["_renderer"].__dict__
        handle = wrapper_state.get("_handle")
        bindings = wrapper_state.get("_bindings")
        if handle is None or bindings is None:
            return None
        try:
            address = int(ctypes.cast(handle, ctypes.c_void_p).value or 0)
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
            not address
            or not os.path.isfile(library_path)
            or name_field.size != 16
            or handle_field.size != 8
            or not 0 < render_var_stride <= 4096
            or render_var_name_offset + name_field.size > render_var_stride
            or render_var_handle_offset + handle_field.size > render_var_stride
        ):
            return None
        return (
            address,
            library_path,
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
        """Drain and join the borrower before any Python renderer operation."""

        token = int(getattr(self, "_frame_pacing_token", 0) or 0)
        self._frame_pacing_pick_snapshot = None
        self._frame_pacing_pick_generated = False
        self._frame_pacing_pick_association_unavailable = False
        if not token:
            # A pick callback can synchronously author selection while the
            # selected-camera image is being installed. Preserve that frame's
            # already-produced one-shot until the viewport consumes it; the
            # beginning of the next render clears it unconditionally.
            self._frame_pacing_needs_sync_step = True
            return
        self._frame_pacing_presented_snapshot = None
        native_ui = self._frame_pacing_bindings()
        if native_ui is None:
            raise RuntimeError(
                "native frame pacing bindings disappeared while renderer "
                f"ownership was pinned before {reason}"
            )
        if capture_selected_camera:
            # An active pacing pick is valid only when it can be tied to one
            # complete selected real-frame camera. Missing/malformed state and
            # generated selections stay fail-closed after the mandatory drain.
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
                    world_usd = np.asarray(
                        selected_world, dtype=np.float64
                    ).reshape(4, 4)
                    selected_view = np.linalg.inv(world_usd.T)
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
                            selected_view, projection_array, selected_size
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
                # A malformed diagnostic must not prevent the mandatory
                # drain; the pick remains explicitly unavailable below.
                self._frame_pacing_pick_snapshot = None
        if pause_render and bool(native_ui._native_frame_pacing_pause_render(token)):
            self._frame_pacing_render_paused = True
            self._frame_pacing_needs_sync_step = True
            return
        # There is no ovrtx cancellation primitive. A failed native cleanup
        # attempt deliberately retains its maps/results and the borrowed token
        # so that a later attempt can release them safely. Keep retrying with a
        # bounded pause instead of abandoning that ownership and allowing the
        # Python renderer mutation below to race retained native resources.
        while not bool(native_ui._native_frame_pacing_stop(token)):
            time.sleep(0.001)
        self._frame_pacing_token = 0
        self._frame_pacing_render_paused = False
        self._frame_pacing_needs_sync_step = True

    def _publish_native_frame(
        self,
        width: int,
        height: int,
        view_matrix: Any,
        proj_matrix: Any,
    ) -> bool:
        """Publish one complete camera intent without calling ovrtx in Python."""

        if not self._frame_pacing_eligible():
            if getattr(self, "_frame_pacing_token", 0):
                self._stop_native_frame_pacing("capability fallback")
            if getattr(self, "_frame_pacing_restore_overlap", False):
                self.set_ldr_overlap_enabled(True)
                self._frame_pacing_restore_overlap = False
            return False
        size = (int(width), int(height))
        projection = np.ascontiguousarray(proj_matrix, dtype=np.float64).reshape(4, 4)
        camera_path = self._runtime_camera_path()
        if self._frame_pacing_token and (
            size != self._frame_pacing_size
            or camera_path != self._frame_pacing_camera_path
            or self._frame_pacing_projection is None
            # Dolly changes near/far only; ovrtx camera authoring consumes fx/fy.
            or not np.allclose(
                projection.diagonal()[:2],
                self._frame_pacing_projection.diagonal()[:2],
                rtol=0.0,
                atol=1e-12,
            )
        ):
            self._stop_native_frame_pacing(
                "resolution or camera intrinsics change", pause_render=True
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
                    self._frame_pacing_token
                )
            ):
                self._stop_native_frame_pacing("failed render-worker resume")
                return False
            self._frame_pacing_render_paused = False
            self._frame_pacing_needs_sync_step = False
        if self._frame_pacing_needs_sync_step:
            return False
        if not self._frame_pacing_token:
            borrow = self._borrow_native_renderer()
            if borrow is None:
                return False
            # The overlap may retain a live result container from the
            # synchronous bootstrap frame. Release it before handing sole
            # renderer ownership to native code. Default-off pacing therefore
            # leaves the existing overlap behavior untouched.
            restore_overlap = getattr(self, "_ldr_overlap", None) is not None
            self.set_ldr_overlap_enabled(False)
            (
                address,
                library_path,
                render_var_stride,
                render_var_name_offset,
                render_var_handle_offset,
            ) = borrow
            token = int(native_ui._native_frame_pacing_start(
                address,
                library_path,
                render_var_stride,
                render_var_name_offset,
                render_var_handle_offset,
                self._frame_pacing_provider,
                str(self._render_product_path),
                camera_path,
                size[0],
                size[1],
            ) or 0)
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

        # A Python camera record is the complete authoritative intent. Native
        # prediction may advance from it between UI ticks, but must never feed
        # back into a later publication: doing so compounds motion already
        # represented by the new raw camera pose.
        # Native code writes this record as the camera's ``omni:xform``, which
        # ovrtx composes under the camera's parents.
        raw_world = self._runtime_camera_xform(
            _view_to_ovrtx_transform(view_matrix), camera_path
        ).reshape(4, 4)
        # Must stay perf_counter: the native coordinator differences this
        # against std::chrono::steady_clock (NativeFramePacing.cpp writeCamera).
        publication_time = time.perf_counter()
        velocity = np.zeros(3, dtype=np.float64)
        previous_world = self._frame_pacing_last_raw_world
        previous_time = self._frame_pacing_last_intent_time
        if previous_world is not None and publication_time > previous_time:
            velocity = (
                raw_world[3, :3] - previous_world[3, :3]
            ) / (publication_time - previous_time)
        published = bool(native_ui._native_frame_pacing_publish(
            self._frame_pacing_token,
            size[0],
            size[1],
            raw_world.reshape(-1).tolist(),
            velocity.tolist(),
            publication_time,
        ))
        if not published:
            self._stop_native_frame_pacing("failed camera publication")
        else:
            self._frame_pacing_last_raw_world = raw_world.copy()
            self._frame_pacing_last_intent_time = publication_time
            self._frame_pacing_projection = projection.copy()
        return published

    # ── Depth-one LdrColor overlap: ownership and presentation state ──

    def _release_retained_output(self, *, keep_grouped_frames: bool = False) -> None:
        """Release the retained step result and presentation cache.

        MUST run immediately before every ownership-invalidating native
        mutation (layer add/remove, root open/reload, renderer reset,
        product switch, teardown), after any cheap early-return guard of the
        enclosing boundary function. An ovrtx step-result container holds
        native output handles; letting one live across a native mutation is
        undefined (measured consequences range from stale mappings to
        renderer deadlock). Idempotent and cheap when nothing is retained.

        Grouped images and camera records describe the renderer before the
        mutation and are forgotten too, unless ``keep_grouped_frames`` (a
        switch between products of one group, which mutates nothing).

        The static ownership audit verifies both the call-site coverage and
        the ordering of this call inside every boundary function.
        """
        overlap = getattr(self, "_ldr_overlap", None)
        if overlap is not None:
            overlap.release(clear_presentation=True)
        if not keep_grouped_frames:
            self._discard_grouped_frames()

    def set_render_product_group(self, paths: Any) -> None:
        """Step ``paths`` together; call once per host frame that shows them.

        ovrtx rebuilds per-product render state whenever the set of stepped
        RenderProducts changes (measured ~0.27 s of GPU work per product on an
        L40), so a host that presents several products in turn, such as a quad
        layout, must keep all of them in every step. One step then renders
        every grouped product, and ``render_frame`` presents another grouped
        authored product from that step while its camera is exactly the one
        the product last rendered with. Images are shared within one host
        frame only. An empty group restores single-product steps.
        """
        group = frozenset(str(path) for path in paths or () if path)
        if group != getattr(self, "_render_product_group", frozenset()):
            self._render_product_group = group
            self._grouped_cameras = {}
        self._grouped_frames = {}

    def _discard_grouped_frames(self, changed_paths: Any = None) -> None:
        """Forget grouped images and the camera records a change may outdate.

        Without ``changed_paths`` any renderer state may have changed. With
        them, only records of cameras at, below or with a property in one of
        those paths are forgotten; images are always dropped.
        """
        self._grouped_frames = {}
        cameras = getattr(self, "_grouped_cameras", {})
        if not changed_paths:
            self._grouped_cameras = {}
            return
        owners = {str(path).split(".", 1)[0] for path in changed_paths}
        self._grouped_cameras = {
            product: key
            for product, key in cameras.items()
            if not any(
                owner == "/" or key[1] == owner or key[1].startswith(owner + "/")
                for owner in owners
            )
        }

    def _is_grouped_product(self, path: Any) -> bool:
        """Whether ``path`` is an authored product of a multi-product group."""
        group = getattr(self, "_render_product_group", ())
        default = getattr(self, "_default_render_product_path", _RENDER_PRODUCT_PATH)
        return len(group) > 1 and str(path) in group and path != default

    def _grouped_frame_key(
        self, camera_path: str, view_matrix: Any, proj_matrix: Any, width: int, height: int
    ) -> Optional[tuple]:
        """Camera state of this grouped frame, or None when it renders alone.

        Consumers sharing the single per-frame LdrColor mapping (livestream,
        zero-copy, RenderVar/PointCloud requests) and pending picks keep the
        per-frame synchronous path.
        """
        zero_copy = getattr(self, "_zero_copy_state", None)
        if (
            not self._is_grouped_product(self._render_product_path)
            or getattr(self, "_in_flight_pick_queries", None)
            or getattr(self, "_frame_pacing_pick_snapshot", None) is not None
            or getattr(self, "_livestream", None) is not None
            or (zero_copy is not None and zero_copy.gpu_pending)
            or getattr(self, "_point_cloud_requests", None)
            or getattr(self, "_render_var_output_requests", None)
        ):
            return None
        return (
            str(self._render_product_path),
            str(camera_path),
            np.ascontiguousarray(view_matrix, dtype=np.float64).tobytes(),
            np.ascontiguousarray(proj_matrix, dtype=np.float64).tobytes(),
            (int(width), int(height)),
        )

    def _cache_grouped_frames(self, products: Any, key: tuple) -> None:
        """Keep this step's images of the other grouped products.

        Each rendered with the camera its product last wrote, unless a later
        write to the same camera (a shared camera) replaced it.
        """
        cameras = {
            product: other
            for product, other in getattr(self, "_grouped_cameras", {}).items()
            if product != key[0] and other[1] != key[1] and self._is_grouped_product(product)
        }
        self._grouped_frames = {
            product: (other, self._extract_ldr_color(products, *other[4], product_path=product))
            for product, other in cameras.items()
        }
        cameras[key[0]] = key
        self._grouped_cameras = cameras

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
        self._stop_native_frame_pacing("active camera change")
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

    @staticmethod
    def supported_render_var_outputs() -> list[dict[str, Any]]:
        """Describe every RenderVar source this renderer can produce, before configuration.

        ``sensor`` is false for the display color (``LdrColor``), which views
        render but ``sensor_capture`` does not decode.
        """
        outputs = []
        for name in _RENDER_VAR_SOURCE_NAMES:
            spec = _RENDER_VAR_OUTPUT_SPECS.get(_source_token_key(name))
            outputs.append({
                "source_name": name,
                "display_name": str(spec["display_name"]) if spec else "LDR Color",
                "output_kind": spec["output_kind"].value if spec else "ldr_color",
                "units": str(spec["units"]) if spec else "",
                "sensor": spec is not None,
            })
        return outputs

    @staticmethod
    def supported_render_var_name(name: str) -> Optional[str]:
        """Return the canonical source name for ``name`` (case-insensitive), or None."""
        key = _source_token_key(name)
        return next((n for n in _RENDER_VAR_SOURCE_NAMES if _source_token_key(n) == key), None)

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
            builtin_scope = _render_setting_owner_scope(descriptor)
            if builtin_scope == _RENDER_SETTINGS_OWNER_SCOPE:
                descriptor = self._render_settings_owner_value_state(descriptor)
            elif builtin_scope == _CAMERA_OWNER_SCOPE:
                descriptor = self._render_settings_camera_value_state(descriptor)
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

    def subscribe_render_settings_changes(
        self,
        callback: Callable[[], None],
    ) -> _RenderSettingsSubscription:
        """Notify on real render-settings changes (apply/reset/external/undo).

        Every returned handle owns a UNIQUE tokenized record: subscribing the
        same callback twice yields two independently live subscriptions, and
        cancelling one can never remove another owner's record. Cancellation
        is idempotent.
        """

        subscribers = getattr(self, "_render_settings_subscribers", None)
        if not isinstance(subscribers, list):
            subscribers = []
            self._render_settings_subscribers = subscribers
        if not subscribers:
            # Rebaseline on EVERY zero-to-one subscriber transition: the
            # snapshot gate compares against the state this subscription
            # epoch signed up under, so a change that happened while nobody
            # listened can never surface as a false first event, and an
            # unrelated signal cannot manufacture one either.
            try:
                self._render_settings_last_snapshot = (
                    self._render_settings_state_snapshot()
                )
            except Exception:
                self._render_settings_last_snapshot = None
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
        for _token, callback in tuple(
            getattr(self, "_render_settings_subscribers", ()) or ()
        ):
            try:
                callback()
            except Exception:
                # Observers are disposable; one raising observer cannot block
                # later observers or invalidate the authored edit.
                continue

    def _stage_change_affects_active_product(self, resynced_paths):
        """Whether a prim-level resync removes/replaces the active product.

        A RenderProduct removal or replacement arrives as a prim resync (no
        attribute path), which is a CATALOG change for the settings surface.
        """

        product_path = str(self.get_active_render_product_path() or "")
        if not product_path:
            return False
        for raw_path in tuple(resynced_paths or ()):
            prim_text = str(raw_path).split(".")[0]
            if not prim_text:
                continue
            if product_path == prim_text or product_path.startswith(
                prim_text.rstrip("/") + "/"
            ):
                return True
        return False

    def _render_settings_state_snapshot(self, catalog: Any = None) -> tuple | None:
        """CANONICAL provider revision of the public settings state.

        Deterministic recursive canonicalization of the COMPLETE catalog —
        active product identity/label, every provider descriptor, every
        group descriptor, every binding descriptor with all nested state,
        the revision string, and catalog warnings — so any live semantic
        change with an unchanged value is still a change.

        ``catalog`` lets a caller that has just described this exact state,
        with nothing mutating in between, hand that description over instead
        of paying for an identical second one. The canonicalization itself is
        unchanged and still covers the complete catalog.
        """

        if catalog is None:
            try:
                catalog = self.list_render_settings(None)
            except Exception:
                return None
        catalog_revision = _RENDER_SETTINGS_CATALOG_REVISION_FN(catalog)
        return (
            str(self.get_active_render_product_path() or ""),
            catalog_revision,
        )

    def _publish_render_settings_change(self, catalog: Any = None) -> None:
        """One authoritative event per LOGICAL settings change.

        Every producer (explicit apply/reset success and the USD stage-notice
        path) funnels through this snapshot gate: the current public settings
        state (values, availability, catalog membership) is compared against
        the last published snapshot, so one logical edit delivered through
        BOTH producers notifies exactly once, unchanged repeated notices are
        suppressed, and a RenderProduct resync/removal (catalog change)
        notifies even though no attribute path was named.
        """

        snapshot = self._render_settings_state_snapshot(catalog)
        if snapshot == getattr(self, "_render_settings_last_snapshot", None):
            return
        self._render_settings_last_snapshot = snapshot
        self._notify_render_settings_changed()

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

    def read_render_setting_value(
        self,
        attr_name: str,
        *,
        render_product_path: Optional[str] = None,
    ) -> Any:
        """The effective value of ONE named setting, without the rest.

        Describes exactly the one attribute through the same helpers
        :meth:`list_render_settings` uses — the authored USD attribute when
        the product carries it, otherwise the declared builtin corrected from
        its real owner prim — so a caller after a single token does not pay
        for the whole declared surface.
        """

        attr_name = str(attr_name or "")
        stage = getattr(self, "_stage", None)
        active_path = str(
            render_product_path or self.get_active_render_product_path() or ""
        )
        if stage is None or not attr_name or not active_path:
            return None
        if _render_setting_public_namespace(attr_name) is None:
            # Not a described setting at all: the catalog has no row for it.
            return None
        try:
            prim = _render_settings_product_prim(stage, active_path)
        except (ImportError, RuntimeError):
            return None
        if prim is None:
            return None
        product_path = str(prim.GetPath())
        descriptor = None
        try:
            attr = prim.GetAttribute(attr_name)
            if attr:
                descriptor = _render_setting_descriptor(product_path, attr)
        except Exception:
            descriptor = None
        if descriptor is None:
            spec = _render_setting_builtin_spec(attr_name)
            if spec is None:
                return None
            descriptor = _render_setting_builtin_descriptor(product_path, spec)
            if descriptor is None:
                return None
            builtin_scope = _render_setting_owner_scope(descriptor)
            if builtin_scope == _RENDER_SETTINGS_OWNER_SCOPE:
                descriptor = self._render_settings_owner_value_state(descriptor)
            elif builtin_scope == _CAMERA_OWNER_SCOPE:
                descriptor = self._render_settings_camera_value_state(descriptor)
        state = getattr(descriptor, "value_state", None)
        return getattr(state, "current_value", None)

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
            return _render_setting_reject_validation(
                setting_id,
                "Render setting is not available for this RenderProduct.",
                "unknown_setting",
            ), None
        if not descriptor.enabled or descriptor.disabled_reason:
            return _render_setting_reject_validation(
                descriptor.setting_id,
                descriptor.disabled_reason or "Render setting is disabled.",
                "setting_disabled",
            ), descriptor
        if descriptor.value_type is RenderSettingValueType.UNKNOWN:
            return _render_setting_reject_validation(
                descriptor.setting_id,
                "Render setting value type is not supported.",
                "unsupported_type",
            ), descriptor
        try:
            normalized = _render_setting_coerce_value(descriptor, value)
        except (TypeError, ValueError) as exc:
            return _render_setting_reject_validation(
                descriptor.setting_id,
                str(exc),
                "invalid_value",
            ), descriptor
        ok, message, code = _render_setting_value_within_constraints(
            descriptor,
            normalized,
        )
        if not ok:
            return _render_setting_reject_validation(
                descriptor.setting_id,
                message,
                code,
            ), descriptor
        return RenderSettingValidationResult.accepted_result(
            setting_id=descriptor.setting_id,
            normalized_value=normalized,
            requirement=descriptor.requirement,
            message="Render setting value is valid.",
        ), descriptor

    def apply_render_setting(
        self,
        setting_id: str,
        value: Any,
        *,
        render_product_path: Optional[str] = None,
    ) -> RenderSettingApplyResult:
        """Validate then author a public RenderProduct setting value."""

        stage = getattr(self, "_stage", None)
        active_path = str(render_product_path or self.get_active_render_product_path() or "")
        if stage is None or not active_path:
            return _render_setting_reject_apply(
                setting_id,
                "No active RenderProduct is available.",
                "missing_render_product",
            )
        # Validation and authoring describe the SAME pre-write state, so they
        # read one catalog between them rather than one each.
        validation, descriptor = self._render_setting_validation_for(
            self.list_render_settings(active_path),
            setting_id,
            value,
        )
        if not validation.accepted:
            return _render_setting_reject_apply(
                validation.setting_id or setting_id,
                validation.message or "Render setting validation failed.",
                validation.warning_code or "validation_failed",
            )
        if descriptor is None:
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
            attr = _render_setting_attr_for_descriptor(
                self._render_setting_owner_stage_for(descriptor, create=True),
                descriptor,
                create=True,
            )
            if attr is None:
                return _render_setting_reject_apply(
                    descriptor.setting_id,
                    "Render setting attribute is not available for apply.",
                    "unsupported",
                )
            conflict = _render_setting_native_type_conflict(attr)
            if conflict:
                return _render_setting_reject_apply(
                    descriptor.setting_id,
                    f"Render setting apply failed: {conflict}",
                    "apply_failed",
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
        # The read-back and the publish gate describe the SAME post-write
        # state with nothing mutating between them, so they share one
        # description instead of building two identical ones.
        written_product = str(descriptor.metadata.get("render_product_path") or "")
        written = self.list_render_settings(written_product)
        written_descriptor = _render_setting_for_id(written, descriptor.setting_id)
        value_state = (
            None if written_descriptor is None else written_descriptor.value_state
        )
        # The gate's snapshot is always of the ACTIVE product; a write aimed
        # at any other product does not describe it, so that case still reads
        # its own.
        self._publish_render_settings_change(
            written
            if written_product == str(self.get_active_render_product_path() or "")
            else None
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
            attr = _render_setting_attr_for_descriptor(
                self._render_setting_owner_stage_for(descriptor),
                descriptor,
            )
            if attr is None:
                return _render_setting_reject_reset(
                    descriptor.setting_id,
                    "Render setting attribute is not available for reset.",
                    "unsupported",
                )
            # A genuinely incompatible declaration rejects for reset exactly
            # as it does for apply: clearing it would leave the builtin's
            # native storage in a type outside its proven role and the
            # post-clear live write would push the default in that
            # unsupported dtype — a silent role escape. Same deterministic
            # contract as the OVStage twin.
            conflict = _render_setting_native_type_conflict(attr)
            if conflict:
                return _render_setting_reject_reset(
                    descriptor.setting_id,
                    f"Render setting reset failed: {conflict}",
                    "reset_failed",
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
        self._publish_render_settings_change()
        return RenderSettingResetResult.accepted_result(
            setting_id=descriptor.setting_id,
            reset_value=None if value_state is None else value_state.current_value,
            value_state=value_state,
            requirement=descriptor.requirement,
            message="Render setting reset.",
        )

    # ------------------------------------------------------------------
    # Process-global render setting lifecycle: this adapter's PUBLIC
    # capability, and the whole of its contribution to process-global
    # renderer configuration.
    #
    # A caller that owns such a configuration channel asks whether the
    # lifecycle a value needs can run right now, asks for it to be run once
    # the value is written, and asks how to describe what did or did not
    # happen. Nothing about any particular settings channel, key or ABI is
    # known here — only what THIS provider can do to a live renderer.
    # ------------------------------------------------------------------

    def global_render_setting_lifecycle_requirement(
        self,
        lifecycle: RenderSettingLifecycle,
    ) -> str:
        """"" when ``lifecycle`` can be performed safely right now.

        Otherwise a precise ``"requires <X>"`` phrase. Callers check this
        BEFORE writing, so a value that cannot be made effective is never
        written in the first place.
        """

        if lifecycle is RenderSettingLifecycle.NONE:
            return "names no consumer on this build"
        if self._renderer is None:
            # Nothing to rebuild yet. Every one of these settings is read when a
            # renderer is constructed, so publishing now is the CHEAPEST correct
            # actuation: the next renderer picks it up with no rebuild at all.
            return ""
        # EVERY row is actuated by a renderer rebuild over the same stage (see
        # GLOBAL_SETTING_ACTUATION_IS_RENDERER_REBUILD: on this build the
        # settings write kills the consumer's own live subscription after the
        # first publication). Without a loaded stage there is nothing to
        # rebuild onto, and doing it anyway would drop the scene.
        if getattr(self, "_stage", None) is None:
            return "requires a loaded stage so the renderer can be rebuilt safely"
        if self._native_scene_unresolved:
            return (
                "requires the unresolved native scene cleanup to be retried before "
                "the renderer can be rebuilt"
            )
        fault = self._global_setting_rebuild_fault
        if fault:
            return (
                "requires provider recovery: an earlier rebuild for a "
                f"process-global setting failed and could not be undone ({fault})"
            )
        return ""

    def perform_global_render_setting_lifecycle(
        self,
        lifecycle: RenderSettingLifecycle,
        value: Any,
    ) -> str:
        """Make a just-written value effective. "" on success, else the fault."""

        overrides: dict[str, Any] = {}
        if lifecycle is RenderSettingLifecycle.RENDERER_CONFIG_RECREATE:
            # This row's real owner is a public RendererConfig field; the key
            # alone is not enough (CRenderApiImpl.cpp:404-427).
            overrides = {
                "enable_geometry_streaming": bool(value),
                "enable_geometry_streaming_lod": bool(value),
            }
        if self._renderer is None:
            # Pre-creation path: no rebuild is needed or possible. Carry the
            # config override into the configuration the next renderer is built
            # from, so the RendererConfig-owned row is not silently dropped.
            self._renderer_config = _renderer_config_with_overrides(
                getattr(self, "_renderer_config", None), overrides
            )
            return ""
        return self._rebuild_renderer_for_global_setting(overrides)

    def _drain_one_frame_for_global_setting(self) -> str:
        """Step and drain one frame so a live consumer observes the new value."""

        self._stop_native_frame_pacing("global render-setting drain")
        renderer = self._renderer
        if renderer is None:
            return "no live OVRTX renderer"
        try:
            # Ownership: the retained step-result container must not survive a
            # new step's native output handles.
            self._release_retained_output()
            renderer.step(
                render_products={self._render_product_path},
                delta_time=_MIN_DT,
            )
        except Exception as exc:  # noqa: BLE001
            return f"{type(exc).__name__}: {exc}"
        return ""

    def _rebuild_renderer_for_global_setting(
        self,
        config_overrides: dict[str, Any],
    ) -> str:
        """Rebuild the renderer over the SAME stage, preserving presentation.

        A process-global setting whose consumer samples during scene/resource/
        material construction only becomes effective on a freshly built
        renderer.  Rebuilding must not cost the user their scene, so the active
        camera, RenderProduct and resolution are captured and restored around
        it, and the stage is re-loaded through the adapter's own load path
        rather than a bespoke one.
        """

        stage = getattr(self, "_stage", None)
        if stage is None:
            return "no loaded stage"
        # Deliberately NOT aliased to a local: ``self._renderer`` must hold the
        # LAST reference so clearing the field below actually destroys the
        # native renderer. A surviving local keeps two renderers alive and the
        # second one dies on "Out of resource descriptors".
        if self._renderer is None:
            return "no live OVRTX renderer"
        self._stop_native_frame_pacing("global render-setting rebuild")
        capture = {
            "stage": stage,
            "config": self._renderer_config,
            "camera_path": self._camera_path,
            "render_product_path": self._render_product_path,
            "active_camera": getattr(self, "_active_camera_common_path", None),
            "active_product": getattr(self, "_active_render_product_common_path", None),
            "resolution": tuple(self._pending_resolution),
            "ldr_overlap_enabled": self._ldr_overlap is not None,
        }
        camera_path = capture["camera_path"]
        render_product_path = capture["render_product_path"]
        active_camera = capture["active_camera"]
        active_product = capture["active_product"]
        resolution = capture["resolution"]
        ldr_overlap_enabled = capture["ldr_overlap_enabled"]
        try:
            self._release_retained_output()
            self._remove_ovrtx_layers(allow_renderer_drop=True)
        except BaseException as exc:  # noqa: BLE001
            # Native ownership refused to release: the current renderer and
            # scene are intact and retryable — never leave them half-torn.
            return f"native scene release failed: {type(exc).__name__}: {exc}"
        get_instrumentation().release_renderer(self)
        self._renderer = None
        try:
            new_config = _config_with_selection_outline_enabled(
                _renderer_config_with_overrides(
                    self._renderer_config, config_overrides
                )
            )
            self._renderer_config = new_config
            self._renderer = (
                _ovrtx.Renderer(new_config) if new_config is not None else _ovrtx.Renderer()
            )
            self._camera_path = camera_path
            self._render_product_path = render_product_path
            self.load_stage(stage)
        except BaseException as exc:  # noqa: BLE001
            # The replacement did not come up. Losing the setting is acceptable;
            # losing the user's session is not, so put the previous renderer
            # back before reporting anything. A single ordinary edit must never
            # be a one-way door.
            fault = f"renderer rebuild failed: {type(exc).__name__}: {exc}"
            restore_fault = self._restore_renderer_after_failed_rebuild(capture)
            if not restore_fault:
                return (
                    f"{fault}. The previous renderer, scene, camera, "
                    "RenderProduct and presentation state were restored."
                )
            # Restoration failed too: record the fault so every global row
            # reports it instead of offering an edit that cannot land.
            self._global_setting_rebuild_fault = (
                f"{fault}; restoring the previous renderer also failed: "
                f"{restore_fault}"
            )
            print(
                "[OvRtxRendererAdapter] render-settings renderer rebuild failed "
                "and the previous renderer could not be restored: "
                f"{self._global_setting_rebuild_fault}",
                file=sys.stderr,
            )
            return self._global_setting_rebuild_fault
        # Restore presentation state so the rebuild is invisible to the user.
        # Each item is restored independently and every failure is NAMED: a
        # half-restored viewport that reports one generic error hides which part
        # of the user's presentation state was actually lost.
        self._render_product_path = render_product_path
        self._camera_path = camera_path
        if active_camera is not None:
            self._active_camera_common_path = active_camera
        if active_product is not None:
            self._active_render_product_common_path = active_product
        unrestored: list[str] = []
        for label, restore in (
            ("resolution", lambda: self.set_resolution(int(resolution[0]), int(resolution[1]))),
            (
                "presentation overlap",
                (lambda: self.set_ldr_overlap_enabled(True))
                if ldr_overlap_enabled
                else None,
            ),
        ):
            if restore is None:
                continue
            try:
                restore()
            except Exception as exc:  # noqa: BLE001
                unrestored.append(f"{label} ({type(exc).__name__}: {exc})")
        drain_fault = self._drain_one_frame_for_global_setting()
        if unrestored:
            return (
                "the renderer was rebuilt and the setting is effective, but this "
                "presentation state was not restored: " + "; ".join(unrestored)
            )
        return drain_fault

    def _restore_renderer_after_failed_rebuild(
        self,
        capture: dict[str, Any],
    ) -> str:
        """Put the adapter back on a working renderer. "" on success.

        Rebuilt from the configuration captured BEFORE the setting's override
        was folded in, over the same stage, restoring the same camera,
        RenderProduct, resolution and presentation overlap. The setting is
        simply not applied; the session survives.
        """

        stage = capture.get("stage")
        if stage is None:
            return "no captured stage"
        # Drop whatever half-built renderer the failed attempt left behind so
        # only one native renderer is ever alive.
        try:
            self._release_retained_output()
        except BaseException:  # noqa: BLE001 — the handle is being discarded
            pass
        get_instrumentation().release_renderer(self)
        self._renderer = None
        try:
            previous_config = capture.get("config")
            self._renderer_config = previous_config
            self._renderer = (
                _ovrtx.Renderer(previous_config)
                if previous_config is not None
                else _ovrtx.Renderer()
            )
            self._camera_path = capture["camera_path"]
            self._render_product_path = capture["render_product_path"]
            self._stage = stage
            self.load_stage(stage)
        except BaseException as exc:  # noqa: BLE001
            return f"{type(exc).__name__}: {exc}"
        self._render_product_path = capture["render_product_path"]
        self._camera_path = capture["camera_path"]
        if capture.get("active_camera") is not None:
            self._active_camera_common_path = capture["active_camera"]
        if capture.get("active_product") is not None:
            self._active_render_product_common_path = capture["active_product"]
        resolution = capture["resolution"]
        try:
            self.set_resolution(int(resolution[0]), int(resolution[1]))
            if capture["ldr_overlap_enabled"]:
                self.set_ldr_overlap_enabled(True)
        except Exception as exc:  # noqa: BLE001
            # The renderer and the scene ARE back; only presentation trim is
            # missing, and that must not be reported as a lost session.
            print(
                "[OvRtxRendererAdapter] renderer restored after a failed "
                f"render-settings rebuild, but presentation state was not fully "
                f"reapplied: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        self._global_setting_rebuild_fault = ""
        return ""

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
        self._stop_native_frame_pacing("active render product change")
        # Ownership: the retained step result references the OUTGOING
        # product; release it before the switch re-authors native state.
        # Switching between authored products of one group re-authors
        # nothing, so the group's shared images stay valid.
        self._release_retained_output(
            keep_grouped_frames=self._is_grouped_product(self._render_product_path)
            and self._is_grouped_product(next_path)
        )
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

        adapter = UsdStageAdapter(stage)
        try:
            catalog = adapter.get_render_target_catalog()
        finally:
            adapter.dispose()
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
        # Authored products already carry their camera, resolution and settings.
        # Switching between them must not rebuild an unrelated owned session.
        if self._uses_owned_render_product():
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
        self._dt_clock = time.perf_counter()
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
        self._stop_native_frame_pacing("stage load")
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
        # Globally owned (RenderSettings) opinions belong to the document that
        # is currently loaded. A load of a DIFFERENT document must not carry
        # them over, so they are neither exported here nor kept at commit.
        carries_owner = stage is getattr(self, "_stage", None) and stage is not None
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
                prospective_muted_layers = self._muted_layer_identifiers(
                    prospective_stage
                )
                session_layer = prospective_stage.GetSessionLayer()
                has_session_sublayers = bool(
                    session_layer and session_layer.subLayerPaths
                )
                if prospective_muted_layers or has_session_sublayers:
                    # Muting is not authored into the root layer.  Loading the
                    # root file or a root-layer snapshot would therefore keep
                    # rendering the muted contribution.  Flatten the live
                    # composed stage for this renderer load. Live collaboration
                    # overlays in session sublayers likewise do not exist in
                    # the root file and must survive structural reloads. The authoritative
                    # editable stage remains ``prospective_stage``.
                    path = self._export_composed_stage_snapshot(
                        prospective_stage,
                        include_render_settings_owner=carries_owner,
                    )
                    prospective_tmp_path = path
                elif root_layer.anonymous:
                    if getattr(self._renderer, "open_usd_from_string", None) is not None:
                        root_usda = self._export_root_layer_to_string(
                            root_layer,
                            strip_session_root=strip_session_root,
                            include_render_settings_owner=carries_owner,
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
                        if carries_owner:
                            self._author_render_settings_owner_into_layer_file(
                                tmp_path
                            )
                        path = tmp_path
                else:
                    # A dirty file-backed root layer means the stage composes
                    # unsaved opinions (e.g. a visibility edit surviving a
                    # reopen through the Sdf layer cache). Loading ovrtx from
                    # ``realPath`` would silently drop those opinions and
                    # desynchronize the viewport from USD/Stage Browser
                    # state, so dirty layers always take the live-snapshot
                    # path.
                    #
                    # A globally owned render setting has nowhere else to
                    # live: the renderer reads it from a prim on the root it
                    # opened, so an otherwise clean file-backed stage must
                    # also go through the snapshot — but ONLY while such an
                    # opinion is actually authored.
                    owner_root_needed = (
                        carries_owner and self._has_render_settings_owner_opinions()
                    )
                    live_root_needed = (
                        use_live_root_snapshot
                        or root_layer.dirty
                        or owner_root_needed
                    )
                    if (
                        live_root_needed
                        and getattr(self._renderer, "open_usd_from_string", None) is not None
                        and getattr(self._renderer, "open_usd_from_file", None) is None
                        and getattr(self._renderer, "open_usd", None) is None
                    ):
                        root_usda = self._export_root_layer_to_string(
                            root_layer,
                            strip_session_root=strip_session_root,
                            include_render_settings_owner=carries_owner,
                        )
                        path = None
                    elif live_root_needed or strip_session_root:
                        path = self._export_live_root_layer_snapshot(
                            root_layer,
                            strip_session_root=strip_session_root,
                            include_render_settings_owner=carries_owner,
                        )
                        prospective_tmp_path = path
                    else:
                        path = root_layer.realPath or root_layer.identifier
            else:
                raise TypeError(
                    f"load_stage expected pxr.Usd.Stage or path str, got {type(stage).__name__}"
                )
            prospective_muted_layers = self._muted_layer_identifiers(
                prospective_stage
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
        # handle references it, so the snapshot is this adapter's to reclaim.
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
            if carries_owner:
                product_setting_lines = (
                    self._session_render_product_setting_lines()
                )
                camera_setting_lines = self._session_camera_setting_lines()
            else:
                # A different document: the current stage is still the
                # previous document here, and the new one must not inherit
                # its render settings. Only the new document's own opinions
                # are stated.
                product_setting_lines = self._session_owner_setting_lines(
                    getattr(self, "_render_product_path", ""),
                    prospective_stage,
                    restate_published=False,
                )
                camera_setting_lines = self._session_owner_setting_lines(
                    session_camera_path,
                    prospective_stage,
                    restate_published=False,
                )
            prospective_session_usda = _build_session_usda(
                self._last_resolution,
                include_fallback_dome=not prospective_has_lights,
                camera_path=session_camera_path,
                camera_projection=self._camera_projection_mode,
                render_product_setting_lines=product_setting_lines,
                camera_setting_lines=camera_setting_lines,
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
            # rather than deleted while a handle still references it. For
            # destructive single-root APIs the incoming
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
        # or displaced.
        first_fault: Optional[BaseException] = None

        # Drain pending picks from the outgoing stage as misses before the
        # swap is visible to render_frame. A callback may raise anything,
        # including SystemExit; defer it and keep going.
        try:
            self._dispatch_pending_pick_misses()
        except BaseException as fault:
            first_fault = fault

        if not carries_owner:
            # A different document is now authoritative; its globally owned
            # settings start from the renderer's own defaults, and nothing
            # published for the previous document is restated for it.
            self._discard_render_settings_owner()
            self._published_render_settings = set()
        self._stage = prospective_stage
        self._loaded_muted_layer_identifiers = prospective_muted_layers
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
        # success reported with residual old composition.
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
        live handle.
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
        self._stop_native_frame_pacing("native scene teardown")
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
        include_render_settings_owner: bool = False,
    ) -> str:
        author_owner = (
            include_render_settings_owner
            and self._has_render_settings_owner_opinions()
        )
        if not strip_session_root and not author_owner:
            return root_layer.ExportToString()
        from pxr import Sdf
        layer = Sdf.Layer.CreateAnonymous(".usda")
        if not layer.ImportFromString(root_layer.ExportToString()):
            raise RuntimeError("failed to import root layer snapshot")
        if strip_session_root:
            self._strip_session_root_from_layer(layer)
        if author_owner:
            self._author_render_settings_owner_into_layer(layer)
        return layer.ExportToString()

    def _export_live_root_layer_snapshot(
        self,
        root_layer: Any,
        *,
        strip_session_root: bool = False,
        include_render_settings_owner: bool = False,
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
            if (
                include_render_settings_owner
                and self._has_render_settings_owner_opinions()
            ):
                self._author_render_settings_owner_into_layer_file(tmp_path)
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

    @staticmethod
    def _muted_layer_identifiers(stage: Any) -> tuple[str, ...]:
        """Return the deterministic stage-local mute set."""

        getter = getattr(stage, "GetMutedLayers", None)
        if not callable(getter):
            return ()
        return tuple(sorted(str(identifier) for identifier in getter()))

    def _export_composed_stage_snapshot(
        self,
        stage: Any,
        *,
        include_render_settings_owner: bool = False,
    ) -> str:
        """Export the stage's current composition, including layer muting."""

        flattened = stage.Flatten()
        if flattened is None:
            raise RuntimeError("failed to flatten the composed USD stage")
        self._strip_session_root_from_layer(flattened)
        if (
            include_render_settings_owner
            and self._has_render_settings_owner_opinions()
        ):
            self._author_render_settings_owner_into_layer(flattened)
        root_layer = stage.GetRootLayer()
        if not root_layer.anonymous:
            # Flatten anchors asset paths from file-backed layers, but keeps
            # relative paths authored in anonymous, session and Live layers.
            # The stage resolves those against its root layer; the snapshot
            # lives in the temp directory, so anchor them the same way.
            from pxr import UsdUtils

            UsdUtils.ModifyAssetPaths(
                flattened,
                lambda asset_path: self._anchor_asset_path(root_layer, asset_path),
            )

        # Binary Crate: the flattened production stage is written and reparsed
        # on every structural reload, where text serialization dominates.
        fd, tmp_path = tempfile.mkstemp(
            suffix=".usdc",
            prefix="ovui_widgets_composed_",
        )
        os.close(fd)
        try:
            if not flattened.Export(tmp_path):
                raise RuntimeError(
                    f"failed to export composed stage snapshot: {tmp_path}"
                )
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
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
        from ovui_data_adapters.openusd._session_authoring import strip_session_root

        return strip_session_root(layer)

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

    def _note_published_render_setting(
        self,
        descriptor: RenderSettingDescriptor,
    ) -> None:
        """Record that this build has stated a value for the setting.

        The ledger lets a later reset restate the declared default rather
        than merely dropping the authored opinion from the recomposed
        session, which the renderer would otherwise never observe.
        """

        attr_name = str(descriptor.metadata.get("attr_name") or "")
        if not attr_name:
            return
        published = getattr(self, "_published_render_settings", None)
        if not isinstance(published, set):
            published = set()
            self._published_render_settings = published
        published.add(attr_name)

    # ── Globally owned (RenderSettings) settings ──────────────────────────
    #
    # OVRTX reads these from ``/Render/OmniverseGlobalRenderSettings`` on its
    # own runtime stage, which it creates itself at ``open_usd`` time — so no
    # prefixed session reference can reach it, and an opinion on the
    # RenderProduct or the Camera is never consulted. The only measured
    # delivery route is the adapter-owned exported ROOT SNAPSHOT.
    #
    # The opinion itself is kept on a hidden in-memory stage rather than on
    # the user's document: the OpenUSD Stage Browser walks the composed pxr
    # stage without a runtime-prim filter, so a prim authored there — even in
    # the session layer — would appear as user scene content.

    def _render_settings_owner_stage(self, *, create: bool = False) -> Any:
        """The hidden stage carrying globally owned render-setting opinions."""

        stage = getattr(self, "_render_settings_owner_document", None)
        if stage is not None or not create:
            return stage
        if getattr(self, "_stage", None) is None:
            return None
        from pxr import Usd, UsdGeom

        stage = Usd.Stage.CreateInMemory("ovgear_render_settings_owner.usda")
        UsdGeom.Scope.Define(stage, _RENDER_SETTINGS_OWNER_ROOT_PATH)
        stage.DefinePrim(_RENDER_SETTINGS_OWNER_PATH, _RENDER_SETTINGS_OWNER_TYPE)
        self._render_settings_owner_document = stage
        return stage

    def _render_setting_owner_stage_for(
        self,
        descriptor: RenderSettingDescriptor,
        *,
        create: bool = False,
    ) -> Any:
        """Stage that holds ``descriptor``'s owner prim."""

        if _render_setting_owner_scope(descriptor) == _RENDER_SETTINGS_OWNER_SCOPE:
            return self._render_settings_owner_stage(create=create)
        return getattr(self, "_stage", None)

    def _render_settings_owner_authored_names(self) -> Tuple[str, ...]:
        """Names of globally owned settings that currently carry an opinion.

        A reset clears the value but can leave the property spec behind, so
        membership is decided by ``HasAuthoredValue`` — never by spec
        existence — otherwise a reset setting would keep being delivered and
        would keep forcing the snapshot path.
        """

        stage = self._render_settings_owner_stage()
        if stage is None:
            return ()
        try:
            prim = stage.GetPrimAtPath(_RENDER_SETTINGS_OWNER_PATH)
            if not prim or not prim.IsValid():
                return ()
            return tuple(
                str(attr.GetName())
                for attr in prim.GetAttributes()
                if attr.HasAuthoredValue()
            )
        except Exception:
            return ()

    def _has_render_settings_owner_opinions(self) -> bool:
        """Whether any globally owned setting currently carries an opinion.

        Every extra cost of this owner model — forcing a clean file-backed
        stage onto the snapshot path, and reloading the root on write — is
        gated on this, so a document that never touches one of these settings
        behaves exactly as before.
        """

        return bool(self._render_settings_owner_authored_names())

    def _author_render_settings_owner_into_layer(self, layer: Any) -> bool:
        """Merge the hidden owner prim into an exported ROOT snapshot layer.

        Only the properties this adapter authored are copied, so a user scene
        that already defines ``/Render`` (or the settings prim itself) keeps
        every opinion the adapter did not set.
        """

        authored_names = self._render_settings_owner_authored_names()
        if not authored_names:
            return False
        from pxr import Sdf

        source_layer = self._render_settings_owner_stage().GetRootLayer()
        scope_spec = Sdf.CreatePrimInLayer(
            layer, Sdf.Path(_RENDER_SETTINGS_OWNER_ROOT_PATH)
        )
        if scope_spec.specifier == Sdf.SpecifierOver and not scope_spec.typeName:
            scope_spec.specifier = Sdf.SpecifierDef
            scope_spec.typeName = "Scope"
        owner_path = Sdf.Path(_RENDER_SETTINGS_OWNER_PATH)
        target_spec = Sdf.CreatePrimInLayer(layer, owner_path)
        if target_spec.specifier == Sdf.SpecifierOver and not target_spec.typeName:
            target_spec.specifier = Sdf.SpecifierDef
            target_spec.typeName = _RENDER_SETTINGS_OWNER_TYPE
        for name in authored_names:
            if not Sdf.CopySpec(
                source_layer,
                owner_path.AppendProperty(name),
                layer,
                owner_path.AppendProperty(name),
            ):
                raise RuntimeError(
                    "failed to author the global render settings owner "
                    f"property {name!r} into the root snapshot"
                )
        return True

    def _author_render_settings_owner_into_layer_file(self, path: str) -> None:
        from pxr import Sdf

        layer = Sdf.Layer.FindOrOpen(path)
        if layer is None:
            raise RuntimeError(f"failed to open root layer snapshot: {path}")
        if self._author_render_settings_owner_into_layer(layer):
            if not layer.Save():
                raise RuntimeError(
                    f"failed to save root layer snapshot: {path}"
                )

    def _discard_render_settings_owner(self) -> None:
        """Drop globally owned opinions belonging to a superseded document."""

        self._render_settings_owner_document = None

    def _render_settings_owner_prim_value_state(
        self,
        descriptor: RenderSettingDescriptor,
        stage: Any,
        owner_path: str,
    ) -> RenderSettingDescriptor:
        """Reflect the authored opinion that lives on ``owner_path``.

        The builtin catalog rows are described from the RenderProduct, so an
        opinion the renderer reads from a DIFFERENT prim would otherwise always
        read back as the declared default with ``authored=False`` — an edit that
        succeeds, then visibly snaps back, and a reset affordance that never
        lights up.
        """

        if stage is None or not owner_path:
            return descriptor
        attr_name = str(descriptor.metadata.get("attr_name") or "")
        if not attr_name:
            return descriptor
        try:
            prim = stage.GetPrimAtPath(owner_path)
            attr = prim.GetAttribute(attr_name) if prim and prim.IsValid() else None
            if attr is None or not attr.IsValid() or not attr.HasAuthoredValue():
                return descriptor
            value = _render_setting_python_value(attr.Get())
        except Exception:
            return descriptor
        if value is None:
            return descriptor
        state = _dataclass_replace(
            descriptor.value_state,
            current_value=value,
            authored=True,
            inherited=False,
        )
        return _dataclass_replace(
            descriptor,
            value_state=state,
            revision_token=(
                f"{descriptor.metadata.get('render_product_path')}"
                f":{attr_name}:{value!r}:True"
            ),
        )

    def _render_settings_owner_value_state(
        self,
        descriptor: RenderSettingDescriptor,
    ) -> RenderSettingDescriptor:
        """Readback for the hidden global RenderSettings owner prim."""

        return self._render_settings_owner_prim_value_state(
            descriptor,
            self._render_settings_owner_stage(),
            _RENDER_SETTINGS_OWNER_PATH,
        )

    def _render_settings_camera_value_state(
        self,
        descriptor: RenderSettingDescriptor,
    ) -> RenderSettingDescriptor:
        """Readback for a Camera-owned setting (the exposure/autoExposure family).

        These are authored onto the Camera the active RenderProduct references,
        never onto the product itself, so the product-shaped builtin descriptor
        has to be corrected from the camera prim.
        """

        stage = getattr(self, "_stage", None)
        return self._render_settings_owner_prim_value_state(
            descriptor,
            stage,
            _render_setting_owner_path(stage, descriptor),
        )

    def _write_render_setting_to_ovrtx(
        self,
        descriptor: RenderSettingDescriptor,
        value: Any,
    ) -> None:
        self._stop_native_frame_pacing("render setting mutation")
        renderer = getattr(self, "_renderer", None)
        owner_scope = _render_setting_owner_scope(descriptor)
        writer = getattr(renderer, "write_attribute", None)
        if owner_scope != _RENDER_SETTINGS_OWNER_SCOPE and not callable(writer):
            raise RuntimeError("Renderer does not support live setting writes.")
        owner_stage = self._render_setting_owner_stage_for(descriptor)
        product_path = _render_setting_owner_path(owner_stage, descriptor)
        attr_name = str(descriptor.metadata.get("attr_name") or "")
        if not product_path or not attr_name:
            raise RuntimeError("Render setting target is missing.")
        self._release_retained_output()
        if owner_scope == _RENDER_SETTINGS_OWNER_SCOPE:
            # The renderer reads globally owned settings from a UsdPrim on the
            # stage it opened, so the opinion only becomes effective once that
            # root is reopened with the snapshot carrying it. A live column
            # write is not a delivery route for these (measured: the readback
            # is value-blind and IRenderSettingsContext reads USD, not Fabric).
            if not self._reload_live_root_snapshot():
                raise RuntimeError("Render setting delivery failed.")
            self._reset_render_timing_state()
            return
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
        # The owned session RenderProduct is what the renderer actually
        # consumes these settings from, so the value only becomes effective
        # once the session is recomposed; the live column write above alone
        # is not observed for RenderProduct settings.
        self._note_published_render_setting(descriptor)
        reset = getattr(renderer, "reset", None)
        if callable(reset):
            reset()
            self._reinject_session_layer()
            self._reset_render_timing_state()

    def _session_camera_setting_lines(self) -> Tuple[str, ...]:
        """Authored public render settings owned by the session Camera."""

        camera_path = str(
            getattr(self, "_default_camera_path", "") or _CAMERA_PATH
        )
        return self._session_owner_setting_lines(camera_path)

    def _session_render_product_setting_lines(self) -> Tuple[str, ...]:
        """Return authored public render settings for the owned RenderProduct."""
        return self._session_owner_setting_lines(self._render_product_path)

    def _session_owner_setting_lines(
        self,
        owner_path: str,
        stage: Any = None,
        *,
        restate_published: bool = True,
    ) -> Tuple[str, ...]:
        """Authored public render settings carried by one owner prim.

        ``stage`` defaults to the current document. Settings reset back to
        their default are still stated explicitly, so the recomposed session
        tells the renderer to return to the default rather than merely
        dropping the opinion, which it would never observe. A different
        document passes ``restate_published=False``: its session is built
        from its own authored opinions only.
        """
        stage = stage if stage is not None else getattr(self, "_stage", None)
        if (
            stage is None
            or not self._uses_owned_render_product()
            or not owner_path
        ):
            return ()
        try:
            prim = stage.GetPrimAtPath(owner_path)
        except Exception:
            return ()
        if not prim or not prim.IsValid():
            return ()
        lines: list[str] = []
        # Only restate defaults for settings this owner actually carries; a
        # RenderProduct default must never be emitted onto the Camera.
        is_product = owner_path == self._render_product_path
        ledger = (
            getattr(self, "_published_render_settings", ()) if restate_published else ()
        )
        published = {
            name
            for name in (ledger or ())
            if (
                str(
                    (_render_setting_builtin_spec(name) or {}).get("owner_scope")
                    or "RenderProduct"
                )
                == "RenderProduct"
            )
            is is_product
        }
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
                published.discard(name)
        # Settings published earlier in this session but no longer authored
        # (reset to default) must still be stated explicitly. Dropping the
        # line only removes the opinion from the recomposed session; it never
        # tells the renderer to go back to the default, so the superseded
        # value would keep rendering while the UI reported the default.
        for name in sorted(published):
            line = _render_setting_default_usda_line(name)
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
        if property_name.startswith(self._non_rendering_prefixes()):
            return True  # Nothing to render.
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
            if self._stage_change_live_safe_camera_path(sdf_path):
                # Camera schema scalars/vectors are float32, not the generic
                # Python float64 payload. One row corresponds to one prim.
                payload = np.asarray([value], dtype=np.float32)
            elif self._stage_change_live_safe_input_path(sdf_path):
                dtype, width = _LIVE_INPUT_DTYPES[str(attribute.GetTypeName())]
                payload = np.ascontiguousarray(
                    np.asarray([value], dtype=dtype).reshape((1, width) if width else (1,))
                )
            else:
                payload = self._usd_value_to_write_payload(value)
            self._renderer.write_attribute(
                prim_paths=[str(sdf_path.GetPrimPath())],
                attribute_name=property_name,
                tensor=payload,
            )
            return True
        except Exception:
            return False

    def notify_stage_changed(self, event: Any) -> None:
        """Mirror live USD edits into ovrtx."""
        if self._stage is None or self._renderer is None:
            return
        self._stop_native_frame_pacing("stage change publication")
        changed_paths = tuple(getattr(event, "changed_paths", ()) or ())
        resynced_paths = tuple(getattr(event, "resynced_paths", ()) or ())
        paths = changed_paths + resynced_paths
        self._discard_grouped_frames(paths)
        # External stage edits (other editors, USD undo/redo) that touch a
        # public RenderProduct setting — or resync/remove/replace the active
        # RenderProduct prim itself (a catalog change) — publish through the
        # snapshot-deduped gate, before any early return so session-authored
        # settings count too.
        if _stage_change_touches_public_render_settings(
            paths, self.get_active_render_product_path() or ""
        ) or self._stage_change_affects_active_product(resynced_paths):
            self._publish_render_settings_change()
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
        live_write_failed = False
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
                    if (
                        imageable
                        and sync_path not in seen_visibility
                        and (not sdf_path.IsPropertyPath() or sdf_path.name == "visibility")
                    ):
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
                    written = self._write_property_to_ovrtx(prim, sdf_path)
                    if written and sdf_path.name in _LIVE_CAMERA_ATTRIBUTE_TYPES:
                        # The authored lens (with its authored aperture aspect)
                        # replaced the viewport-fitted intrinsics in ovrtx; push
                        # those again on the next frame instead of trusting the
                        # cache (reopened views otherwise rendered ~1.3x zoomed).
                        self._last_pushed_camera_intrinsics = None
                    if not written and self._stage_change_live_safe_input_path(sdf_path):
                        # The value was classified live but OVRTX refused it:
                        # reload rather than keep rendering a stale value.
                        live_write_failed = True
            except Exception:
                continue
        if live_write_failed:
            self._reload_live_root_snapshot()

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

    def stage_change_sync_decision(self, event: Any) -> str:
        """Classify a change event as "live", "overlay" or "reload" without applying it.

        Hosts use this to coalesce bursts of structural changes into one
        reload while forwarding live value updates immediately.
        """
        from pxr import Sdf

        changed_paths = tuple(getattr(event, "changed_paths", ()) or ())
        resynced_paths = tuple(getattr(event, "resynced_paths", ()) or ())
        paths = changed_paths + resynced_paths
        if not paths:
            return _STAGE_CHANGE_SYNC_RELOAD  # notify_stage_changed treats it as everything
        if all(_stage_change_path_is_session(path) for path in paths):
            return _STAGE_CHANGE_SYNC_LIVE
        return self._stage_change_sync_decision(event, changed_paths, resynced_paths, Sdf)

    def _stage_change_live_safe_input_path(self, path: Any) -> bool:
        """Accept existing, unconnected value inputs of lights and shaders."""
        if not path.IsPropertyPath() or not path.name.startswith("inputs:"):
            return False
        try:
            from pxr import Sdf, Usd, UsdLux, UsdShade

            attribute = self._stage.GetObjectAtPath(path)
            if not isinstance(attribute, Usd.Attribute) or attribute.Get() is None:
                return False
            if str(attribute.GetTypeName()) not in _LIVE_INPUT_DTYPES:
                return False
            # A connection (or a removed one) changes the network, not a value.
            if not all(
                isinstance(spec, Sdf.AttributeSpec) and not spec.HasInfo("connectionPaths")
                for spec in attribute.GetPropertyStack()
            ):
                return False
            prim = attribute.GetPrim()
            if prim.HasAPI(UsdLux.LightAPI):
                return path.name in _LIVE_LIGHT_INPUTS
            return bool(UsdShade.Shader(prim))
        except Exception:
            return False

    def property_updates_live(self, property_path: str) -> bool:
        """Whether a value edit of ``property_path`` reaches ovrtx without a reload.

        Mirrors the per-property rules of ``_stage_change_sync_decision`` for
        the stage as it is now: transforms, visibility, existing numeric camera
        attributes, non-rendering metadata and unconnected light/shader value
        inputs are written live; any other property reloads the scene.
        """
        try:
            from pxr import Sdf

            path = Sdf.Path(str(property_path))
        except Exception:
            return False
        if not path.IsPropertyPath():
            return False
        name = path.name
        return bool(
            name in {"xformOpOrder", "visibility"}
            or name.startswith("xformOp:")
            or name.startswith(self._non_rendering_prefixes())
            or self._stage_change_live_safe_camera_path(path)
            or self._stage_change_live_safe_input_path(path)
        )

    def _stage_change_live_safe_camera_path(self, path: Any) -> bool:
        """Accept only existing numeric Camera schema attributes for live writes."""
        if not path.IsPropertyPath():
            return False
        expected_type = _LIVE_CAMERA_ATTRIBUTE_TYPES.get(path.name)
        if expected_type is None:
            return False
        try:
            from pxr import Sdf, Usd, UsdGeom

            attribute = self._stage.GetObjectAtPath(path)
            return (
                isinstance(attribute, Usd.Attribute)
                and bool(UsdGeom.Camera(attribute.GetPrim()))
                and not attribute.IsCustom()
                and str(attribute.GetTypeName()) == expected_type
                # USD schema fallback can mask a malformed relationship spec.
                and all(isinstance(spec, Sdf.AttributeSpec)
                        for spec in attribute.GetPropertyStack())
                and attribute.Get() is not None
            )
        except Exception:
            return False

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
                if self._stage_change_live_safe_camera_path(sdf_path):
                    continue
                if property_name.startswith(self._non_rendering_prefixes()):
                    continue
                if self._stage_change_live_safe_input_path(sdf_path):
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
        # A reload restores authored camera values in ovrtx.
        self._last_pushed_camera_intrinsics = None
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

    def _runtime_camera_xform(self, world_tensor: np.ndarray, camera_path: str) -> np.ndarray:
        """Return the ``omni:xform`` tensor that places ``camera_path`` at ``world_tensor``.

        ovrtx composes ``omni:xform`` under the prim's ancestors, like any other
        prim transform, so a scene camera under a transformed parent must
        receive its parent-local matrix; writing the world matrix applies the
        parent transform twice. Unparented cameras (and the owned session
        camera) are returned unchanged.
        """
        stage = getattr(self, "_stage", None)
        if stage is None or not camera_path:
            return world_tensor
        try:
            from pxr import Usd, UsdGeom

            xformable = UsdGeom.Xformable(stage.GetPrimAtPath(camera_path))
            if not xformable or xformable.GetResetXformStack():
                return world_tensor
            parent = np.asarray(
                xformable.ComputeParentToWorldTransform(Usd.TimeCode.Default()),
                dtype=np.float64,
            )
        except Exception:
            return world_tensor
        if np.allclose(parent, np.eye(4), rtol=0.0, atol=1e-12):
            return world_tensor
        # USD row-vector convention: world = local * parentToWorld.
        local = world_tensor.reshape(4, 4) @ np.linalg.inv(parent)
        return np.ascontiguousarray(local, dtype=np.float64).reshape(1, 4, 4)

    def set_live_local_transform(self, path: str, matrix: Matrix4d) -> bool:
        """Push a prim-local transform preview into ovrtx without authoring USD."""
        self._stop_native_frame_pacing("live transform preview")
        self._discard_grouped_frames([str(path)])
        return self._write_local_transform_matrix_to_ovrtx(str(path), matrix)

    def clear_live_local_transforms(self, paths: List[str]) -> None:
        """Restore ovrtx transforms for ``paths`` from the authoritative USD stage."""
        self._stop_native_frame_pacing("live transform restore")
        self._discard_grouped_frames([str(path) for path in paths or []])
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

    def instrumentation_target(self) -> Any | None:
        """Return the native renderer for optional instrumentation."""

        return self._renderer

    def render_frame(
        self,
        width: int,
        height: int,
        view_matrix: Any,
        proj_matrix: Any,
    ) -> np.ndarray | GpuFrame | None:
        """Render one frame via ovrtx.

        Drives the session camera from ``(view_matrix, proj_matrix)``
        each frame, then calls ``renderer.step``. The normal tier-1 path
        returns a ``(H, W, 4)`` uint8 RGBA ndarray copied from the CPU-mapped
        ``LdrColor`` render var. When tier-2 zero-copy is active and the
        requested size matches ovrtx's committed render product, this may
        instead return a :class:`GpuFrame` carrying a live CUDA mapping for
        :class:`ImageBridge` to consume synchronously.

        When native Vulkan pacing is active, a complete camera record is
        published and ``None`` is returned; the native presenter owns the
        provider image. On any failure (missing stage, missing LdrColor var, ovrtx step
        error) a black ``(height, width, 4)`` uint8 frame is returned
        instead of raising — a transient renderer fault must not take
        down the viewport frame loop.
        """
        # A pacing pick may expose one synchronous selected-camera frame to
        # the viewport overlay. It is valid for exactly the UI composition
        # following that render and never survives into the next raw intent.
        self._frame_pacing_presented_snapshot = None
        if self._stage is None or self._usd_handle is None:
            return np.zeros((int(height), int(width), 4), dtype=np.uint8)
        if width <= 0 or height <= 0:
            return np.zeros((max(int(height), 1), max(int(width), 1), 4), dtype=np.uint8)
        # MuteLayer/UnmuteLayer changes composition without a useful USD
        # ObjectsChanged notice, so the application's ordinary stage-change
        # forwarding cannot wake this renderer.  Compare the cheap stage-local
        # mute set before the native-pacing early return and rebuild from a
        # flattened composed snapshot when it changes. ``load_stage`` owns an
        # atomic transition contract, and its failures must propagate rather
        # than becoming an indefinite series of unexplained black frames.
        current_muted_layers = self._muted_layer_identifiers(self._stage)
        if current_muted_layers != getattr(
            self, "_loaded_muted_layer_identifiers", ()
        ):
            self.load_stage(self._stage, use_live_root_snapshot=True)
        raw_world_tensor = _view_to_ovrtx_transform(view_matrix)

        # Steady-state pacing performs no Python-side renderer operation.
        # Lifecycle/mutation paths stop and drain the borrower first, set the
        # synchronous-step latch, and come through the historical path below
        # once before pacing can restart.
        if self._publish_native_frame(width, height, view_matrix, proj_matrix):
            return None

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
        pacing_pick_snapshot = getattr(
            self, "_frame_pacing_pick_snapshot", None
        )
        if pacing_pick_snapshot is not None:
            view_matrix = pacing_pick_snapshot.view
            proj_matrix = pacing_pick_snapshot.projection
            width, height = pacing_pick_snapshot.size
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
        # A grouped product whose camera is unchanged since the group's latest
        # step presents that step's image (see set_render_product_group).
        grouped_key = self._grouped_frame_key(
            runtime_camera_path, view_matrix, proj_matrix, width, height
        )
        if grouped_key is None:
            # This frame writes a camera the group's records do not describe.
            self._discard_grouped_frames()
        else:
            grouped = self._grouped_frames.pop(grouped_key[0], None)
            if grouped is not None and grouped[0] == grouped_key:
                if overlap is not None:
                    overlap.release(clear_presentation=True)
                return self._record_successful_frame(
                    grouped[1], int(width), int(height)
                )
        self._apply_camera_projection(proj_matrix)
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
        world_tensor = self._runtime_camera_xform(
            _view_to_ovrtx_transform(view_matrix), runtime_camera_path
        )
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

        # Picks resolve against this step: keep its camera for world positions.
        self._pick_step_camera = (
            np.array(view_matrix, dtype=np.float64),
            np.array(proj_matrix, dtype=np.float64),
        )

        # 3) Step ovrtx with a clamped delta.
        now = time.perf_counter()
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
            self._frame_pacing_pick_snapshot = None
            self._frame_pacing_pick_generated = False
            self._frame_pacing_pick_association_unavailable = False
            return np.zeros((int(height), int(width), 4), dtype=np.uint8)

        self._frame_pacing_needs_sync_step = False
        self._frame_pacing_size = (int(width), int(height))
        self._frame_pacing_projection = np.ascontiguousarray(
            proj_matrix, dtype=np.float64
        ).reshape(4, 4).copy()
        self._frame_pacing_camera_path = runtime_camera_path
        self._frame_pacing_last_raw_world = raw_world_tensor.reshape(4, 4).copy()
        self._frame_pacing_last_intent_time = now

        if pacing_pick_snapshot is not None:
            # This synchronous image was rendered from the exact selected
            # view/projection/size used for its pick query. Keep that complete
            # state for the one UI composition that installs the image.
            self._frame_pacing_presented_snapshot = pacing_pick_snapshot
            self._frame_pacing_pick_snapshot = None

        self._dispatch_pending_pick_results(products)
        if not self._in_flight_pick_queries or pacing_pick_snapshot is not None:
            self._frame_pacing_pick_generated = False
            self._frame_pacing_pick_association_unavailable = False
        if self._native_render_is_paused() and pacing_pick_snapshot is not None:
            return None
        self._extract_requested_point_cloud_frames(products)
        self._extract_requested_render_var_output_frames(products)

        # When the debounce defers a resolution change, ovrtx still
        # renders at ``self._last_resolution`` — potentially smaller or
        # larger than ``(width, height)``. ``_extract_ldr_color`` uses the
        # CPU path for those mismatch frames so ``_normalize_rgba`` can
        # pad/crop safely before ImageBridge sees the requested size.
        if overlap is None or grouped_key is not None or not self._ldr_overlap_allowed():
            if overlap is not None:
                # Gated frame (livestream / zero-copy / LdrColor output
                # request): those paths share the single per-frame LdrColor
                # mapping and keep their existing synchronous behavior.
                # Grouped frames are synchronous too: the other products
                # present this step's images after their product switches.
                overlap.release(clear_presentation=True)
            if grouped_key is not None:
                self._cache_grouped_frames(products, grouped_key)
            return self._record_successful_frame(
                self._extract_ldr_color(products, int(width), int(height)),
                int(width),
                int(height),
            )

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
        output = overlap.consume(
            products,
            retention_key,
            snapshot,
            lambda retained: self._extract_ldr_color(
                retained, int(width), int(height)
            ),
            (int(height), int(width)),
            pick_skip,
        )
        return self._record_successful_frame(output, int(width), int(height))

    def _record_successful_frame(
        self, output: Any, width: int, height: int
    ) -> Any:
        """Record a frame produced by a renderer step for inspector state."""

        self._successful_frame_count = int(getattr(self, "_successful_frame_count", 0) or 0) + 1
        if isinstance(output, np.ndarray):
            self._last_frame_shape = tuple(int(value) for value in output.shape)
            if output.ndim >= 3 and output.shape[-1] >= 3:
                # Exact nonblack-pixel count; the RGBA uint8 hot path views
                # each pixel as one machine word and masks off alpha.
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
        # A changed product set rebuilds render state: keep the group in it.
        paths.update(getattr(self, "_render_product_group", ()))
        # ovrtx consumes queued picks on the next step, even when another
        # viewport is currently bound. Render their originating products too.
        paths.update(getattr(self, "_pick_query_products", {}).values())
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
            from ovui_data_adapters.openusd._camera_writer import (
                compute_camera_intrinsics,
            )
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

    def _apply_camera_projection(self, proj_matrix: Any) -> None:
        """Recompose the owned runtime camera when its projection changes."""
        if not self._uses_owned_render_product():
            return
        try:
            from ovui_data_adapters.openusd._camera_writer import (
                camera_projection_from_matrix,
            )

            mode = camera_projection_from_matrix(proj_matrix)
        except Exception:
            return
        if mode == self._camera_projection_mode:
            return
        previous = self._camera_projection_mode
        self._camera_projection_mode = mode
        try:
            self._reinject_session_layer()
        except Exception:
            self._camera_projection_mode = previous

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
        if not self._uses_owned_render_product():
            return
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
                    camera_projection=self._camera_projection_mode,
                    render_product_setting_lines=(
                        self._session_render_product_setting_lines()
                    ),
                    camera_setting_lines=self._session_camera_setting_lines(),
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
        if not getattr(self, "_selection_outline_previous_paths", set()):
            # Recomposing with no applied membership leaves the outline pass
            # inactive for later writes; re-arm the activation reset.
            self._selection_outline_pass_needs_reset = True

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
        product_path: Optional[str] = None,
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

        ``product_path`` selects another product of the same step result;
        those images always take the CPU path, because the zero-copy and
        livestream consumers follow the active product only.
        """
        try:
            product = products[product_path or self._render_product_path]
        except Exception:
            return np.zeros((height, width, 4), dtype=np.uint8)
        if not getattr(product, "frames", None):
            return np.zeros((height, width, 4), dtype=np.uint8)
        frame_out = product.frames[0]
        render_vars = getattr(frame_out, "render_vars", None) or {}
        rv = render_vars.get(_LDR_VAR_NAME)
        if rv is None:
            rv = next(
                (
                    candidate
                    for candidate in render_vars.values()
                    if str(getattr(candidate, "source_name", "") or "")
                    == _LDR_VAR_NAME
                ),
                None,
            )
        if rv is None:
            return np.zeros((height, width, 4), dtype=np.uint8)

        state = self._zero_copy_state if product_path is None else None
        from ovui_data_adapters.common._render_product_stream import for_current_product
        livestream = for_current_product(self) if product_path is None else None
        committed_resolution = getattr(self, "_last_resolution", (width, height))
        gpu_size_matches = (int(width), int(height)) == committed_resolution

        # ── GPU UI zero-copy path (with optional livestream tee) ──
        if state is not None and state.gpu_pending and gpu_size_matches:
            mapping = None
            try:
                mapping = rv.map(device=_ovrtx.Device.CUDA)
                mapping.__enter__()
                tensor = _mapped_render_var_tensor(mapping)
                ptr = int(tensor.data)
                # Codex blocker 4: when both flags are on, tee to
                # ovstream from the SAME mapping (one CUDA map serves
                # both consumers — the GPU-UI ingest reads ptr directly,
                # NVENC reads its D2D copy). Failures inside
                # ``tee_to_ovstream`` are isolated by the tap; they
                # cannot bubble out and break the GPU UI ingest.
                if livestream is not None:
                    try:
                        livestream.tee_to_ovstream(tensor, width, height)
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

        # ── Asynchronous livestream path (the ovstream reference pipeline) ──
        # The tap validates the mapped extent itself; a frame of another size (a deferred resize)
        # raises ValueError and takes the synchronous path below.
        if livestream is not None and getattr(livestream, "async_enabled", False):
            try:
                # Frame generation (DLSS-G) returns several frames per step, generated before real,
                # in presentation order: stream them all; the last (real) one is the CPU image.
                rvs = [self._ldr_render_var(f) for f in product.frames]
                rvs = [v for v in rvs if v is not None] or [rv]
                self._frames_per_step = len(rvs)
                image = self._tee_livestream_async(rvs, livestream, int(width), int(height))
                # Without a CPU image the viewport keeps showing an older frame.
                self._cpu_image_stale = image is None
                return image
            except ValueError:
                pass
            except Exception:
                if not getattr(self, "_livestream_async_error_logged", False):
                    import traceback as _tb
                    _tb.print_exc()
                    self._livestream_async_error_logged = True

        # ── Livestream-only path (CUDA map shared with D2H for UI) ──
        if livestream is not None:
            try:
                with rv.map(device=_ovrtx.Device.CUDA) as mapping:
                    arr = livestream.tee_and_d2h(
                        _mapped_render_var_tensor(mapping), width, height,
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
                # Must copy: the DLPack buffer is unmapped on __exit__.
                arr = _copy_tensor_to_host(_mapped_render_var_tensor(mapping))
        except Exception:
            return np.zeros((height, width, 4), dtype=np.uint8)

        if arr.ndim >= 2 and arr.shape[0] > 0 and arr.shape[1] > 0:
            self._last_render_product_resolution = (
                int(arr.shape[1]),
                int(arr.shape[0]),
            )
        return _normalize_rgba(arr, width, height)

    @staticmethod
    def _ldr_render_var(frame_out: Any) -> Any:
        render_vars = getattr(frame_out, "render_vars", None) or {}
        rv = render_vars.get(_LDR_VAR_NAME)
        if rv is None:
            rv = next((candidate for candidate in render_vars.values()
                       if str(getattr(candidate, "source_name", "") or "") == _LDR_VAR_NAME), None)
        return rv

    @property
    def frames_per_step(self) -> int:
        """Frames the last streamed step presented: 1, or 2-4 with frame generation (DLSS-G)."""
        return int(getattr(self, "_frames_per_step", 1) or 1)

    # Hosts that consume the streamed frames only (a headless streaming application) set this so a
    # streamed frame carries no CPU image unless one was requested: the render thread then never
    # waits for the GPU frame. Captures call :meth:`request_cpu_image` first.
    cpu_image_on_demand: bool = False

    def request_cpu_image(self, frames: int = 1) -> bool:
        """Ask for a CPU image of the next ``frames`` streamed frames.

        Returns True while the last streamed frame has no CPU image (the renderer streams
        asynchronously with CPU images on demand), so the caller should wait for a new frame and
        ask again; False once the CPU image shows the last rendered frame.
        """
        self._cpu_image_requests = max(int(getattr(self, "_cpu_image_requests", 0) or 0), int(frames))
        from ovui_data_adapters.common._render_product_stream import for_current_product
        livestream = for_current_product(self)
        return bool(self.cpu_image_on_demand and livestream is not None
                    and getattr(livestream, "async_enabled", False)
                    and getattr(self, "_cpu_image_stale", False))

    def _tee_livestream_async(self, rvs: list, livestream: Any, width: int, height: int) -> Any:
        """Stream a step's frames without waiting for them; return a CPU image only when wanted.

        Each LdrColor output is mapped on the tap's CUDA stream, which waits for the render on the
        GPU; the tap queues a copy into its ring and records an event; the mapping is released
        against that event, so ovrtx keeps the buffer until the copy has read it. A CPU image
        (``cpu_image_on_demand`` off, or requested) of the last frame waits for it on the host.
        """
        requests = int(getattr(self, "_cpu_image_requests", 0) or 0)
        want_cpu = not self.cpu_image_on_demand or requests > 0
        result = None
        for index, rv in enumerate(rvs):
            last = index == len(rvs) - 1
            mapping = rv.map(device=_ovrtx.Device.CUDA, sync_stream=livestream.cuda_stream)
            event = None
            try:
                tensor = _mapped_render_var_tensor(mapping)
                event = livestream.tee_async(tensor, width, height, index, len(rvs))
                if last and want_cpu:
                    from ovui_data_adapters.common._livestream_tap import _tensor_cuda_device

                    mapping.wait()
                    host = getattr(self, "_livestream_host_buf", None)
                    if host is None or host.shape != (height, width, 4):
                        host = np.empty((height, width, 4), dtype=np.uint8)
                    livestream._cudart.d2h(host, int(tensor.data), width * height * 4,
                                           device=_tensor_cuda_device(tensor))
                    self._livestream_host_buf = host
                    self._cpu_image_requests = max(0, requests - 1)
                    # The image bridge may keep the array; hand it a copy.
                    result = _normalize_rgba(host.copy(), width, height)
            finally:
                if event is not None:
                    mapping.unmap(event=event)
                else:
                    mapping.unmap()
        self._last_render_product_resolution = (width, height)
        return result

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
        if not self._native_render_is_paused():
            self._stop_native_frame_pacing("selection highlight mutation")
        self._grouped_frames = {}  # Shared images predate the new outline.
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
        if current & new_previous:
            self._ensure_selection_outline_pass_active()

    def _ensure_selection_outline_pass_active(self) -> None:
        """Run the one-shot outline-pass activation reset once membership exists.

        Without it a camera-static CPU-presented viewport keeps showing the
        converged pre-selection image: the membership write alone does not
        invalidate ovrtx's render history. A missing/failing ``reset`` keeps
        the flag armed so the next selection sync retries.
        """
        if not getattr(self, "_selection_outline_pass_needs_reset", False):
            return
        # Ownership: reset invalidates retained output handles.
        self._release_retained_output()
        reset = getattr(self._renderer, "reset", None)
        if not callable(reset):
            return
        try:
            reset()
        except Exception:
            return
        self._selection_outline_pass_needs_reset = False

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
            self._selection_outline_pass_needs_reset = True
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

        if not self._native_render_is_paused():
            self._stop_native_frame_pacing("selection highlight refresh")
        self._grouped_frames = {}  # Shared images predate the new outline.
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
        self._stop_native_frame_pacing(
            "pick query", capture_selected_camera=True, pause_render=True
        )
        if (
            self._frame_pacing_pick_generated
            or self._frame_pacing_pick_association_unavailable
        ):
            # ovrtx 0.4 does not expose generated-image camera/timing, and a
            # real selection is usable only with its complete camera state.
            # Keep the callback on this UI thread and fail closed rather than
            # associate a raw-camera ray with different visible pixels.
            self._frame_pacing_pick_generated = False
            self._frame_pacing_pick_snapshot = None
            self._frame_pacing_pick_association_unavailable = False
            callback(None, None)
            return
        try:
            left, top, right, bottom = self._ndc_rect_to_pick_pixels(x, y, x, y)
            self._renderer.enqueue_pick_query(
                self._render_product_path,
                *self._pick_pixels_to_query_rect(left, top, right, bottom),
            )
        except Exception:
            self._frame_pacing_pick_snapshot = None
            self._frame_pacing_pick_association_unavailable = False
            callback(None, None)
            return
        name = str(query_name or "viewport_click")
        # Latest pick under this name supersedes any in-flight one.
        self._cancel_in_flight_point(name, _PICK_CANCEL_REPLACED)
        self._pick_seq += 1
        self._in_flight_pick_queries.append(
            [self._pick_seq, "point", name, callback, None, None]
        )
        if not hasattr(self, "_pick_query_ndc"):
            self._pick_query_ndc = {}
        self._pick_query_ndc[self._pick_seq] = (float(x), float(y))
        self._remember_pick_product()
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
        self._stop_native_frame_pacing(
            "rectangle pick query", capture_selected_camera=True, pause_render=True
        )
        if (
            self._frame_pacing_pick_generated
            or self._frame_pacing_pick_association_unavailable
        ):
            self._frame_pacing_pick_generated = False
            self._frame_pacing_pick_snapshot = None
            self._frame_pacing_pick_association_unavailable = False
            callback([])
            return
        try:
            left, top, right, bottom = self._ndc_rect_to_pick_pixels(x0, y0, x1, y1)
            self._renderer.enqueue_pick_query(
                self._render_product_path,
                *self._pick_pixels_to_query_rect(left, top, right, bottom),
            )
        except Exception:
            self._frame_pacing_pick_snapshot = None
            self._frame_pacing_pick_association_unavailable = False
            callback([])
            return
        self._pick_seq += 1
        name = f"viewport_rect:{time.monotonic_ns()}"
        self._in_flight_pick_queries.append(
            [self._pick_seq, "rect", name, callback, None, None]
        )
        self._remember_pick_product()
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

    def _remember_pick_product(self) -> None:
        if not hasattr(self, "_pick_query_products"):
            self._pick_query_products = {}
        self._pick_query_products[self._pick_seq] = str(self._render_product_path)

    def _cache_hits_for_replacement_pick(
        self,
        name: str,
        hits: List[Tuple[str, Tuple[float, float, float]]],
        product_path: Optional[str] = None,
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
            entry_product = getattr(self, "_pick_query_products", {}).get(
                entry[0], self._render_product_path
            )
            if (
                entry[1] == "point" and entry[2] == name and entry[3] is not None
                and entry_product == (product_path or self._render_product_path)
            ):
                entry[5] = list(hits)
                return

    def _dispatch_pending_pick_results(self, products: Any) -> None:
        """Drain one in-flight pick per rendered product and dispatch results.

        ovrtx surfaces queued pick queries one frame at a time and we
        cannot tell results apart by inspecting the buffer, so each
        frame consumes exactly the head of each product's FIFO. Entries whose
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
        # Keep FIFO ordering within each product. Different products can return
        # in the same GPU step and must each have their own result consumed.
        product_paths = getattr(self, "_pick_query_products", {})
        waits = getattr(self, "_pick_query_waits", {})
        self._pick_query_waits = waits
        drained = set()
        for entry in list(queue):
            if entry not in queue:
                continue  # A preceding callback can tear down/reset the queue.
            product_path = product_paths.get(entry[0], self._render_product_path)
            if product_path in drained:
                continue
            drained.add(product_path)
            available = True
            if products is not None:
                try:
                    available = products[product_path] is not None
                except Exception:
                    available = False
            if not available:
                waits[entry[0]] = waits.get(entry[0], 0) + 1
                if waits[entry[0]] < 3:
                    continue
                # A vanished product must not leave a mouse callback pending
                # indefinitely. Use the adapter's existing unavailable/miss
                # result after three steps, rather than clearing on first gap.
            hits = [] if not available else (
                self._read_pick_hits(products) if product_path == self._render_product_path
                else self._read_pick_hits(products, product_path=product_path)
            )
            queue.remove(entry)
            product_paths.pop(entry[0], None)
            waits.pop(entry[0], None)
            self._dispatch_pick_entry(entry, hits, product_path)

    def _dispatch_pick_entry(self, entry, hits, product_path) -> None:
        _seq, kind, _name, cb, cancel_reason, cached_hits = entry
        self._pick_result_count = getattr(self, "_pick_result_count", 0) + 1
        effective_hits = hits or (cached_hits or [])
        if kind == "point":
            point_path = effective_hits[0][0] if effective_hits else None
            point_world = effective_hits[0][1] if effective_hits else None
            ndc = getattr(self, "_pick_query_ndc", {}).pop(_seq, None)
            camera = getattr(self, "_pick_step_camera", None)
            if point_path and point_world is None and ndc and camera is not None:
                # The renderer gave no position: ray-cast the picked prim in USD
                # with the camera of the frame the pick resolved against.
                point_world = _pick_surface_point(
                    getattr(self, "_stage", None), point_path, camera[0], camera[1], *ndc
                )
            self._last_pick_path = point_path
            self._last_pick_world_point = point_world
            if cb is None:
                if cancel_reason == _PICK_CANCEL_REPLACED:
                    self._cache_hits_for_replacement_pick(_name, hits, product_path)
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
        getattr(self, "_pick_query_ndc", {}).clear()
        getattr(self, "_pick_query_products", {}).clear()
        getattr(self, "_pick_query_waits", {}).clear()
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
        *,
        product_path: Optional[str] = None,
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
            product = products[product_path or self._render_product_path]
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
            world_normals = (
                np.from_dlpack(mapping["worldNormal"]).copy().reshape((-1, 3))
                if "worldNormal" in tensor_names
                else None
            )
        except Exception:
            return []

        hits: List[Tuple[str, Optional[Tuple[float, float, float]]]] = []
        count = min(int(hit_count), len(prim_paths), len(world_positions))
        for i in range(count):
            path = self._resolve_ovrtx_prim_path(int(prim_paths[i]))
            if not path:
                continue
            # A real hit has a unit surface normal. ovrtx 0.4 leaves both
            # position and normal zero: report the position as unavailable
            # rather than a fabricated origin.
            if world_normals is not None and (
                i >= len(world_normals) or not np.linalg.norm(world_normals[i]) > 1e-6
            ):
                hits.append((path, None))
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
        self._stop_native_frame_pacing("renderer shutdown")
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
        from ovui_data_adapters.common._render_product_stream import release_for_shutdown

        # A borrowed RenderProduct stream is released, never closed, here.
        livestream = release_for_shutdown(self)
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
        # instrumentation's cached references as well lets the refcount fall
        # to zero and trigger the destructor.
        get_instrumentation().release_renderer(self)
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
        self._loaded_muted_layer_identifiers = ()
        self._discard_render_settings_owner()
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
