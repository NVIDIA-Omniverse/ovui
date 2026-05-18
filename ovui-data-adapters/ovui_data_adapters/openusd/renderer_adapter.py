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

Per frame, :meth:`render_frame` writes the camera intrinsics to the
pxr stage via :mod:`ovrtx_camera_writer` (A.2) and mirrors the world
transform into ovrtx via :meth:`renderer.write_attribute`. See
the viewport behavior
"""

from __future__ import annotations

import os

# ``OVRTX_SKIP_USD_CHECK`` must be set BEFORE the first ``import ovrtx``
# (which is deferred to :func:`_probe_ovrtx` below). Setting it at
# module load is safe regardless of whether ovrtx ever gets imported.
os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")

import collections
import math
import struct
import tempfile
import time
from typing import Any, Callable, Deque, List, Optional, Tuple

import numpy as np
from ovui_data_adapters.common import GpuFrame, RendererAdapter, ZeroCopyState

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
    try:
        import ovrtx as _mod
        _ovrtx = _mod
    except (ImportError, RuntimeError, OSError) as exc:
        _ovrtx = None
        _OVRTX_IMPORT_ERROR = exc
    return _ovrtx is not None


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


# strata#17 livestream env-flag check. Inlined here (rather than imported
# from ``_livestream_tap``) so the default-off path does NOT pull
# ``_livestream_tap`` into ``sys.modules`` (Codex blocker 5). Must stay
# in sync with the source-of-truth in ``_livestream_tap._enabled``.
_LIVESTREAM_ENV_VAR = "OVGEAR_LIVESTREAM"


def _livestream_env_enabled() -> bool:
    return os.environ.get(_LIVESTREAM_ENV_VAR, "").strip().lower() in (
        "1", "true", "yes",
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


def _config_with_selection_outline_enabled(config: Any) -> Any:
    """Return an ovrtx renderer config with the native outline pass enabled."""
    if not _probe_ovrtx():
        return config
    if config is None:
        config_cls = getattr(_ovrtx, "RendererConfig", None)
        if config_cls is None:
            return None
        try:
            return config_cls(selection_outline_enabled=True, selection_outline_width=2)
        except TypeError:
            cfg = config_cls()
            try:
                cfg.selection_outline_enabled = True
                cfg.selection_outline_width = 2
            except Exception:
                pass
            return cfg
    try:
        if getattr(config, "selection_outline_enabled", None) is None:
            setattr(config, "selection_outline_enabled", True)
        if getattr(config, "selection_outline_width", None) is None:
            setattr(config, "selection_outline_width", 2)
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


def _build_session_usda(
    resolution: Tuple[int, int],
    include_fallback_dome: bool,
    camera_path: str = _CAMERA_PATH,
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
        def Camera "Main"
        {{
            float focalLength = 18
            float horizontalAperture = 20.955
            float verticalAperture = 15.2908
            float2 clippingRange = (0.01, 10000)
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


def _stage_has_any_light(stage: Any) -> bool:
    """True if any ``UsdLux.LightAPI``-applied prim exists on the stage."""
    # Local import so this module imports cleanly when pxr is not
    # available (e.g., during `import ovrtx_renderer_adapter` probing).
    from pxr import UsdLux
    for prim in stage.TraverseAll():
        if prim.HasAPI(UsdLux.LightAPI):
            return True
    return False


def _view_to_ovrtx_transform(view_matrix: np.ndarray) -> np.ndarray:
    """Convert a GL-convention view matrix to a USD row-vector world matrix.

    :class:`ovwidgets.viewport.camera_controller.CameraController` produces
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
        self._default_render_product_path = render_product_path
        self._default_camera_path = camera_path
        self._render_product_path = render_product_path
        self._camera_path = camera_path

        self._stage: Any = None
        self._usd_handle: Any = None
        self._session_handle: Any = None
        # ``_last_resolution`` is the resolution currently committed to
        # ovrtx Fabric via ``_build_session_usda`` — not necessarily the
        # latest resolution requested by the viewport widget. The debounce
        # logic in ``render_frame`` gates updates.
        self._last_resolution: Tuple[int, int] = _DEFAULT_RESOLUTION
        self._pending_resolution: Tuple[int, int] = _DEFAULT_RESOLUTION
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

    def set_zero_copy_state(self, state: Optional[ZeroCopyState]) -> None:
        """Share zero-copy coordination state with the viewport bridge."""
        self._zero_copy_state = state

    @property
    def livestream(self) -> Any:
        """The optional livestream tap, or ``None`` when disabled.

        Step 1.7's status overlay polls this from the viewport widget
        (read-only). Tier-2 / Tier-3 work will reuse the same accessor
        — keep it stable.
        """
        return self._livestream

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
        self._render_product_path = next_path
        self._sync_active_selector_state()
        return True

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

    # ── Stage loading ──

    def load_stage(self, stage: Any) -> None:
        """Load a USD stage (or file path) into the ovrtx renderer.

        Accepts either a :class:`pxr.Usd.Stage` or a path string. When
        given a Stage with an anonymous root layer, the layer is
        exported to a temp file so ``open_usd`` can resolve it.

        After this call, the ovrtx renderer holds the user's scene
        composed with an inline OvGear session layer (camera, render
        product, LDR var, optional fallback dome). The pxr stage's
        session layer carries an equivalent structure so the rest of
        OvGear (Stage Browser, Property Inspector) sees OvGear's
        scaffolding prims too.
        """
        from pxr import Usd  # lazy — module must import without pxr

        # Drain any pending pick callbacks from the OUTGOING stage as
        # miss results before swapping renderer state. Otherwise a pick
        # queued on the previous stage would be dispatched against the
        # new stage's products on the next ``render_frame`` and could
        # select/clear an unrelated prim (Codex review of #67).
        self._dispatch_pending_pick_misses()

        # A prior anonymous-stage tempfile would leak if we just
        # overwrote the path; remove it before deriving a new one.
        self._drop_owned_tmp_path()

        # Resolve the pxr stage plus the best root-open payload for ovrtx.
        # File-backed stages should use file loading so relative asset paths
        # keep their resolver context. Anonymous stages can go straight to
        # ovrtx 0.3's inline root loader when available; older renderers still
        # get the exported tempfile path they understand.
        root_usda: Optional[str] = None
        if isinstance(stage, str):
            path = stage
            self._stage = Usd.Stage.Open(path)
        elif hasattr(stage, "GetRootLayer"):
            self._stage = stage
            root_layer = stage.GetRootLayer()
            if root_layer.anonymous:
                if getattr(self._renderer, "open_usd_from_string", None) is not None:
                    root_usda = root_layer.ExportToString()
                    path = None
                else:
                    # Legacy file-only loaders require a resolvable path; export once.
                    fd, tmp_path = tempfile.mkstemp(suffix=".usda", prefix="ovgear_")
                    os.close(fd)
                    root_layer.Export(tmp_path)
                    self._owned_tmp_path = tmp_path
                    path = tmp_path
            else:
                path = root_layer.realPath or root_layer.identifier
        else:
            raise TypeError(
                f"load_stage expected pxr.Usd.Stage or path str, got {type(stage).__name__}"
            )

        # Mirror OvGear's scaffolding into the pxr stage's session layer
        # so other OvGear panels see a consistent camera / render
        # product. These writes do not touch the user's root layer.
        from ovui_data_adapters.openusd._session_authoring import (
            ensure_camera,
            ensure_dome_light,
            ensure_ldr_color_var,
            ensure_render_product,
            ensure_render_scope,
        )
        ensure_render_scope(self._stage)
        session_camera_path = getattr(self, "_default_camera_path", _CAMERA_PATH)
        if self._uses_owned_render_product():
            ensure_camera(self._stage, session_camera_path)
        ensure_ldr_color_var(self._stage, _LDR_VAR_PATH)
        if self._uses_owned_render_product():
            ensure_render_product(
                self._stage,
                product_path=self._render_product_path,
                camera_path=session_camera_path,
                ldr_var_path=_LDR_VAR_PATH,
                resolution=self._last_resolution,
                ensure_camera_prim=True,
            )
        # ensure_dome_light returns None if the stage already has any
        # light — we mirror that into ovrtx so we don't double-light.
        self._scene_has_lights = _stage_has_any_light(self._stage)
        if not self._scene_has_lights:
            ensure_dome_light(self._stage, _DOME_LIGHT_PATH)

        # Tear down any previous load (reload case).
        self._remove_ovrtx_layers()

        # 1) Load the user's scene. This is the snapshot ovrtx renders.
        self._usd_handle = self._open_ovrtx_root(path, root_layer_content=root_usda)
        # 2) Compose OvGear's camera / render product on top.
        self._session_handle = self._add_ovrtx_session_layer(
            _build_session_usda(
                self._last_resolution,
                include_fallback_dome=not self._scene_has_lights,
                camera_path=session_camera_path,
            )
        )
        self._pending_resolution = self._last_resolution
        # Fresh stage → fresh debounce history. Without this reset, state
        # from a previous stage (mid-drag, recent reinjects) could force
        # the first few frames of the new stage to throttle unnecessarily.
        self._reset_render_timing_state()

    def _remove_ovrtx_layers(self) -> None:
        """Drop previously-loaded USD / session handles from ovrtx."""
        session_handle = getattr(self, "_session_handle", None)
        if session_handle is not None:
            try:
                self._renderer.remove_usd(session_handle)
            except Exception:
                # Renderer may have been torn down already; carry on so
                # a broken previous load doesn't block a fresh one.
                pass
            self._session_handle = None

        root_handle = getattr(self, "_usd_handle", None)
        if root_handle is None:
            return
        try:
            if root_handle is _ROOT_STAGE_SENTINEL:
                reset_stage = getattr(self._renderer, "reset_stage", None)
                if reset_stage is not None:
                    reset_stage()
            else:
                self._renderer.remove_usd(root_handle)
        except Exception:
            pass
        self._usd_handle = None

    def _open_ovrtx_root(
        self,
        path: Optional[str],
        root_layer_content: Optional[str] = None,
    ) -> Any:
        """Load the root USD scene and return a loaded-state token."""
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

    def _add_ovrtx_session_layer(self, usda: str) -> Any:
        """Compose OvGear's session layer into the ovrtx runtime stage."""
        add_reference = getattr(self._renderer, "add_usd_reference_from_string", None)
        if add_reference is not None:
            return add_reference(usda, _SESSION_ROOT_PATH)
        return self._renderer.add_usd_layer(usda, path_prefix=_SESSION_ROOT_PATH)

    def notify_stage_changed(self, event: Any) -> None:
        """Mirror live USD visibility and transform edits into ovrtx."""
        if self._stage is None or self._renderer is None:
            return
        changed_paths = tuple(getattr(event, "changed_paths", ()) or ())
        resynced_paths = tuple(getattr(event, "resynced_paths", ()) or ())
        paths = changed_paths + resynced_paths
        if paths and all(path.startswith(_SESSION_ROOT_PATH) for path in paths):
            return
        if not paths:
            paths = tuple(str(prim.GetPath()) for prim in self._stage.TraverseAll())
        try:
            from pxr import Sdf, UsdGeom
        except Exception:
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
                imageable = UsdGeom.Imageable(prim)
                if imageable and path_str not in seen_visibility:
                    seen_visibility.add(path_str)
                    token = imageable.ComputeVisibility()
                    self._renderer.write_attribute(
                        [path_str],
                        "visibility",
                        [str(token)],
                    )
                if (
                    path_str not in seen_transform
                    and _stage_change_path_affects_transform(sdf_path)
                ):
                    seen_transform.add(path_str)
                    self._write_prim_transform_to_ovrtx(prim, path_str)
            except Exception:
                continue

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
            tensor = np.ascontiguousarray(
                np.asarray([matrix], dtype=np.float64),
                dtype=np.float64,
            )
            self._renderer.write_attribute(
                prim_paths=[path_str],
                attribute_name="omni:xform",
                tensor=tensor,
                semantic=_ovrtx.Semantic.XFORM_MAT4x4,
            )
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

        runtime_camera_path = self._runtime_camera_path()
        drives_owned_camera = (
            runtime_camera_path
            == getattr(self, "_default_camera_path", _CAMERA_PATH)
        )
        if drives_owned_camera:
            # 1) Update the owned session camera on the pxr side (A.2).
            from ovui_data_adapters.openusd._camera_writer import write_camera_from_matrices
            write_camera_from_matrices(
                self._stage,
                runtime_camera_path,
                view_matrix,
                proj_matrix,
                width,
                height,
            )
        # 2) Resolution change: debounced reinject of the session layer.
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

        # 3) Mirror camera values into ovrtx Fabric for the camera that the
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

        # 4) Step ovrtx with a clamped delta.
        now = time.monotonic()
        dt = max(_MIN_DT, min(_MAX_DT, now - self._dt_clock))
        self._dt_clock = now
        try:
            products = self._renderer.step(
                render_products={self._render_product_path},
                delta_time=dt,
            )
        except Exception:
            self._dispatch_pending_pick_misses()
            return np.zeros((int(height), int(width), 4), dtype=np.uint8)

        self._dispatch_pending_pick_results(products)

        # When the debounce defers a resolution change, ovrtx still
        # renders at ``self._last_resolution`` — potentially smaller or
        # larger than ``(width, height)``. ``_extract_ldr_color`` uses the
        # CPU path for those mismatch frames so ``_normalize_rgba`` can
        # pad/crop safely before ImageBridge sees the requested size.
        return self._extract_ldr_color(products, int(width), int(height))

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
        if self._session_handle is not None:
            try:
                self._renderer.remove_usd(self._session_handle)
            except Exception:
                pass
            self._session_handle = None
        try:
            session_camera_path = getattr(self, "_default_camera_path", _CAMERA_PATH)
            self._session_handle = self._add_ovrtx_session_layer(
                _build_session_usda(
                    self._last_resolution,
                    include_fallback_dome=not self._scene_has_lights,
                    camera_path=session_camera_path,
                )
            )
        except Exception:
            # Leave session uninstalled — step() will fail loudly next
            # frame (black frame via the try/except in render_frame).
            self._session_handle = None

        # Also reflect the new resolution into the pxr stage's session
        # render product so Property Inspector is consistent.
        if self._stage is not None:
            try:
                from ovui_data_adapters.openusd._session_authoring import ensure_render_product
                if self._uses_owned_render_product():
                    session_camera_path = getattr(
                        self, "_default_camera_path", _CAMERA_PATH
                    )
                    ensure_render_product(
                        self._stage,
                        product_path=self._render_product_path,
                        camera_path=session_camera_path,
                        ldr_var_path=_LDR_VAR_PATH,
                        resolution=self._last_resolution,
                        ensure_camera_prim=True,
                    )
            except Exception:
                pass

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

        return _normalize_rgba(arr, width, height)

    # ── Resolution / selection / picking ──

    def set_resolution(self, width: int, height: int) -> None:
        """Cache a new resolution; :meth:`render_frame` applies it lazily."""
        self._pending_resolution = (int(width), int(height))

    def set_selection_highlight(self, paths: List[str]) -> None:
        """Drive ovrtx's native selection-outline state for selected prims.

        Tracks ``_selection_outline_previous_paths`` defensively: clears
        and sets advance the tracked set only after their ovrtx write
        succeeds. A transient ovrtx write failure leaves bookkeeping in
        the retryable state — otherwise a deselected prim could stay
        outlined forever, or a selected prim could be skipped forever.
        """
        selected = list(dict.fromkeys(str(p) for p in (paths or []) if p))
        self._selected_paths = selected
        self._configure_selection_outline_styles()

        previous = set(getattr(self, "_selection_outline_previous_paths", set()))
        current = set(selected)
        to_clear = sorted(previous - current)
        to_set = [path for path in selected if path not in previous]

        new_previous: set[str] = set(previous)
        if to_clear:
            if self._write_selection_outline_group(
                to_clear,
                _SELECTION_OUTLINE_CLEAR_GROUP_ID,
            ):
                new_previous.difference_update(to_clear)
            # On failure leave to_clear paths in ``new_previous`` so the
            # next call retries the clear.
        if to_set:
            if self._write_selection_outline_group(
                to_set, _SELECTION_OUTLINE_GROUP_ID
            ):
                new_previous.update(to_set)
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
                left,
                top,
                right,
                bottom,
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
                left,
                top,
                right,
                bottom,
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
        """Write the outline-group attribute for ``paths``; return success.

        Returns ``False`` for any failure (no renderer, no writer, empty
        paths, or the underlying call raising) so callers can decide
        whether to advance their bookkeeping.
        """
        renderer = getattr(self, "_renderer", None)
        writer = getattr(renderer, "write_attribute", None)
        if writer is None or not paths:
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

    def _ndc_rect_to_pick_pixels(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> Tuple[int, int, int, int]:
        width, height = getattr(self, "_last_resolution", None) or getattr(
            self, "_pending_resolution", _DEFAULT_RESOLUTION
        )
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
        self._dispatch_pending_pick_misses()
        livestream = getattr(self, "_livestream", None)
        if livestream is not None:
            livestream.close()
            self._livestream = None
        self._remove_ovrtx_layers()
        # ``ovrtx.Renderer.__del__`` destroys the GPU handle — dropping
        # our reference by setting the attribute is enough; the refcount
        # falling to zero triggers the destructor.
        self._renderer = None
        self._drop_owned_tmp_path()
        self._stage = None

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
        arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
    if arr.ndim == 3 and arr.shape[2] == 3:
        alpha = np.full((arr.shape[0], arr.shape[1], 1), 255, dtype=np.uint8)
        arr = np.concatenate([arr, alpha], axis=2)
    if arr.ndim != 3 or arr.shape[2] != 4:
        return np.zeros((height, width, 4), dtype=np.uint8)
    # Crop / pad to the requested size (ovrtx may return the native
    # render-product resolution which can drift from the requested one
    # on the very first step after a resize reinjection).
    h, w = arr.shape[0], arr.shape[1]
    if h != height or w != width:
        out = np.zeros((height, width, 4), dtype=np.uint8)
        copy_h = min(h, height)
        copy_w = min(w, width)
        out[:copy_h, :copy_w] = arr[:copy_h, :copy_w]
        return out
    return np.ascontiguousarray(arr)
