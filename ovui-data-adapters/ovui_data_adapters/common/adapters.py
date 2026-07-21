# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Abstract base classes for all OvGear adapters.

ABCs that decouple the UI from any specific
USD or RTX implementation; concrete adapters live in ovui_widgets.stage / ovui_widgets.viewport.

This abstract-contract module remains stdlib-only at runtime even though the
distribution's separate livestream helper requires NumPy.
``ovui_widgets/common/adapters.py`` is a one-step re-export shim that resolves to
this module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, fields
from enum import Enum, Flag, auto
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, Type

# Use the private submodule path to avoid a circular import: this module
# (``ovui_data_adapters.common.adapters``) is itself imported by
# ``ovui_data_adapters.common.__init__``. Reaching back through the package
# while __init__ is still being initialized would re-enter a partially
# constructed namespace. The private path is what ``_undo_manager`` uses too.
from ovui_data_adapters.common._bound_camera_pose import BoundCameraPose
from ovui_data_adapters.common.render_targets import (
    RenderTargetActivationResult,
    RenderTargetCatalog,
)
from ovui_data_adapters.common.render_vars import (
    RenderVarOutputCatalog,
    RenderVarOutputFrame,
    RenderVarOutputRequest,
    RenderVarOutputRequestResult,
    RenderVarProbeRequest,
    RenderVarProbeResult,
)
from ovui_data_adapters.common.point_cloud import (
    PointCloudFrame,
    PointCloudOutputCatalog,
    PointCloudRequest,
    PointCloudRequestResult,
)
from ovui_data_adapters.common._subscription import SubscriptionProtocol

if TYPE_CHECKING:
    import numpy as np

    # Static type-checker view: the real ``numpy.ndarray`` class. Static
    # tools (mypy, pyright, IDE completion) see this branch and resolve
    # ``NDArray`` to the concrete numpy type for full type information on
    # :meth:`RendererAdapter.render_frame`.
    NDArray = np.ndarray
else:
    # Runtime view: keep the abstract-contract import lightweight rather than
    # importing numpy solely for an annotation. ``Any`` makes the public
    # ``RendererAdapter.render_frame`` annotation introspectable via
    # ``typing.get_type_hints()``. Concrete adapters still return a real
    # ``np.ndarray``; this alias only types the public contract. The common
    # distribution's separate livestream helper declares its actual numpy
    # runtime dependency in package metadata.
    NDArray = Any

# ──────────────────────────────────────────────────────────────────────────────
# Opaque type aliases
# ──────────────────────────────────────────────────────────────────────────────

AdapterItem = Any      # Opaque handle; must be hashable. USD adapters use Sdf.Path.
Matrix4d = Any         # 4×4 transform matrix; USD adapters use Gf.Matrix4d.
BoundingBox = Any      # Axis-aligned bounding box.
ImageProvider = Any    # GPU image handle or bytes buffer (RGBA uint8).
Vec3f = Any            # 3-component float vector.
ContextManager = Any   # Return type alias for suppress_change_notifications().

# GpuFrameHandle is the type-only alias for
# :meth:`RendererAdapter.render_frame`'s GPU return type. Inlined here as
# ``Any`` (was previously imported from ``ovui_widgets.common.types``; that
# file also defines it as ``Any``). Keeping it inline removes the last
# TYPE_CHECKING dependency on widget-side modules. The contract is
# semantic: an RGBA uint8 buffer or zero-copy GPU pointer (concrete
# implementation: :class:`ovui_data_adapters.common.GpuFrame`).
GpuFrameHandle = Any

# Axis-aligned bounding box returned by :meth:`StageAdapter.compute_world_aabb`
# and :meth:`StageAdapter.compute_prim_world_aabb_with_extent_fallback`. The
# tuple form ``((min_x, min_y, min_z), (max_x, max_y, max_z))`` is the same
# shape returned by the inline pxr code in ``viewport_widget`` today.
AABB = Optional[Tuple[Tuple[float, float, float], Tuple[float, float, float]]]


# ──────────────────────────────────────────────────────────────────────────────
# Enums and Flags
# ──────────────────────────────────────────────────────────────────────────────

class VisibilityState(Enum):
    VISIBLE = auto()
    INVISIBLE = auto()
    INHERITED_INVISIBLE = auto()


class ItemFlags(Flag):
    """State flags for a stage item exposed through StageAdapter metadata.

    Flags are additive — an item can be both ``IS_ABSTRACT`` and ``IS_CLASS``.
    ``Flag`` (not ``IntFlag``) is used deliberately so the values do not
    silently coerce to ``int`` in arithmetic contexts.
    """

    NONE = 0
    IS_INSTANCE_PROXY = auto()
    IS_ABSTRACT = auto()
    IS_OVER = auto()
    IS_INACTIVE = auto()
    IS_CLASS = auto()
    IS_DEFAULT_PRIM = auto()
    IS_OUTDATED = auto()
    IS_IN_LIVE_SESSION = auto()
    HAS_MISSING_REFS = auto()


class BadgeFlags(Flag):
    """Overlay badge decorations for a stage item exposed through StageAdapter metadata.

    Mirrors USD composition markers exposed by ``Usd.Prim``:
    ``HasAuthoredReferences`` → ``REFERENCE``,
    ``HasAuthoredPayloads``   → ``PAYLOAD``,
    ``IsInstanceable``        → ``INSTANCE``,
    ``HasAuthoredInherits``   → ``INHERITS``,
    ``HasAuthoredSpecializes``→ ``SPECIALIZES``,
    and ``OVERRIDE`` for items whose authored opinions only override
    a stronger layer's spec.
    """

    NONE = 0
    REFERENCE = auto()
    PAYLOAD = auto()
    INSTANCE = auto()
    INHERITS = auto()
    SPECIALIZES = auto()
    OVERRIDE = auto()


# Default fallback mapping for ``StageAdapter.get_type_category``. Adapters
# with schema-level introspection (e.g. UsdStageAdapter) override the method
# and bypass this table. Keys are lowercase type names as returned by
# ``get_type_name``.
_DEFAULT_TYPE_CATEGORY_MAP: dict[str, str] = {
    "mesh": "Mesh",
    "sphere": "Mesh", "cube": "Mesh", "cone": "Mesh", "cylinder": "Mesh",
    "capsule": "Mesh", "plane": "Mesh",
    "basiscurves": "Mesh", "points": "Mesh",
    "nurbscurves": "Mesh", "nurbspatch": "Mesh",
    "light": "Light",
    "domelight": "Light", "distantlight": "Light", "disklight": "Light",
    "rectlight": "Light", "spherelight": "Light", "cylinderlight": "Light",
    "camera": "Camera",
    "xform": "Xform",
    "scope": "Scope",
}


class ReparentPosition(Enum):
    CHILD = auto()   # As last child of new_parent
    BEFORE = auto()  # Before new_parent in sibling order
    AFTER = auto()   # After new_parent in sibling order


class ChangeEventType(Enum):
    INFO_CHANGE = "info"    # Attribute/metadata changes; no structural change
    RESYNC = "resync"       # Prims added/removed/reordered
    LAYER_INFO = "layer"    # Layer metadata changed (e.g., defaultPrim)


class TransformEditMode(Enum):
    """How a transform edit should be applied for a path."""

    DIRECT = "direct"
    REDIRECTED = "redirected"
    BLOCKED = "blocked"


VIEWPORT_CAMERA_POSE_SOURCE = "viewport-camera-pose"
_CAMERA_POSE_PROPERTY_NAMES = frozenset(
    {
        "focusDistance",
        "omni:kit:centerOfInterest",
        "xformOpOrder",
    }
)
_CAMERA_VISUAL_PROPERTY_NAMES = frozenset(
    {
        "clippingRange",
        "focalLength",
        "fStop",
        "horizontalAperture",
        "shutter:close",
        "shutter:open",
        "verticalAperture",
    }
)
_CAMERA_PROPERTY_ONLY_INFO_CHANGE_NAMES = (
    _CAMERA_POSE_PROPERTY_NAMES | _CAMERA_VISUAL_PROPERTY_NAMES
)


def _property_name_from_change_path(path: str) -> str | None:
    _prim_path, separator, property_name = str(path).partition(".")
    if not separator or not property_name:
        return None
    return property_name


def _is_camera_pose_property_path(path: str) -> bool:
    property_name = _property_name_from_change_path(path)
    if property_name is None:
        return False
    return property_name in _CAMERA_POSE_PROPERTY_NAMES or property_name.startswith("xformOp:")


def _is_camera_property_only_info_path(path: str) -> bool:
    property_name = _property_name_from_change_path(path)
    if property_name is None:
        return False
    return (
        property_name in _CAMERA_PROPERTY_ONLY_INFO_CHANGE_NAMES
        or property_name.startswith("xformOp:")
    )


def is_viewport_camera_pose_change_event(event: Any) -> bool:
    """Return true for source-tagged viewport-authored camera-pose edits."""
    if getattr(event, "source", None) != VIEWPORT_CAMERA_POSE_SOURCE:
        return False
    if getattr(event, "event_type", None) not in {
        ChangeEventType.INFO_CHANGE,
        ChangeEventType.RESYNC,
    }:
        return False
    changed = tuple(getattr(event, "changed_paths", ()) or ())
    resynced = tuple(getattr(event, "resynced_paths", ()) or ())
    paths = changed + resynced
    return bool(paths) and all(_is_camera_pose_property_path(path) for path in paths)


def is_camera_property_only_info_change(event: Any) -> bool:
    """Return true for camera pose/lens INFO_CHANGE events that cannot alter hierarchy."""
    if getattr(event, "event_type", None) != ChangeEventType.INFO_CHANGE:
        return False
    if tuple(getattr(event, "resynced_paths", ()) or ()):
        return False
    changed = tuple(getattr(event, "changed_paths", ()) or ())
    return bool(changed) and all(
        _is_camera_property_only_info_path(path)
        for path in changed
    )


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StageChoice:
    """Stage-backed item suitable for a viewport selector menu."""

    path: str
    display_name: str


@dataclass(frozen=True)
class TransformEditPolicy:
    """Widget-facing transform edit decision.

    ``DIRECT`` means viewport tools may write the transform adapter normally.
    ``REDIRECTED`` means controls remain active, but the concrete adapter
    sends the edit to a backend control target instead of writing the scene
    transform directly. ``BLOCKED`` means transform controls should be
    disabled for that path.
    """

    mode: TransformEditMode
    reason: str = ""

    @property
    def is_editable(self) -> bool:
        return self.mode in (TransformEditMode.DIRECT, TransformEditMode.REDIRECTED)

    @property
    def direct_write_allowed(self) -> bool:
        return self.mode is TransformEditMode.DIRECT

    @property
    def redirected(self) -> bool:
        return self.mode is TransformEditMode.REDIRECTED


@dataclass(frozen=True)
class ChangeEvent:
    """Emitted by StageAdapter when the backing scene changes."""

    changed_paths: Tuple[str, ...]
    resynced_paths: Tuple[str, ...]
    event_type: ChangeEventType
    source: Optional[str] = None
    # Optional adapter-owned semantic record for visibility edits. Shape:
    # {"authored": (prim path, ...),                      # from genuine notices
    #  "boundaries": {prim path: (old, new)}}             # VisibilityState pairs
    # ``authored`` names only prims whose visibility opinions the genuine
    # USD notices reported; ``boundaries`` may cover additional evaluated
    # prims but can only prune model work, never add repaint roots.
    visibility_delta: Optional[Any] = None

    def get_common_prefix(self) -> str:
        """Return the common path ancestor of all changed+resynced paths.

        Uses path-component matching to avoid false matches like '/WorldA' and
        '/WorldB' appearing to share '/World'.
        """
        all_paths = list(self.changed_paths) + list(self.resynced_paths)
        if not all_paths:
            return "/"

        components = [p.split("/") for p in all_paths]
        reference = components[0]
        common_len = len(reference)

        for comps in components[1:]:
            for i in range(min(common_len, len(comps))):
                if reference[i] != comps[i]:
                    common_len = i
                    break
            else:
                common_len = min(common_len, len(comps))

        if common_len <= 1:
            return "/"
        return "/".join(reference[:common_len]) or "/"


@dataclass
class AttributeMetadata:
    """Metadata for a single attribute. See property metadata behavior."""

    name: str
    display_name: str
    type_name: str
    value_type: Any
    group: str
    soft_range_min: Optional[float] = None
    soft_range_max: Optional[float] = None
    hard_range_min: Optional[float] = None
    hard_range_max: Optional[float] = None
    allowed_values: Optional[List[Any]] = None
    is_big_array: bool = False
    change_on_edit_end: bool = True
    custom_model_class: Optional[Type] = None
    custom_widget_class: Optional[Type] = None
    is_time_sampled: bool = False
    is_locked: bool = False
    is_authored: bool = True


class AdapterCapabilityStatus(Enum):
    """Static support state for one adapter-provided action.

    A capability reports whether an adapter can perform an action at all.
    It does not answer whether the action is valid for the current UI state
    (for example, saving a clean layer or deleting with no selection).
    """

    SUPPORTED = "supported"
    READ_ONLY = "read_only"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class AdapterCapability:
    """One static action advertised by an adapter capability surface.

    ``read_only`` is reserved for adapters that can expose a surface for
    inspection but cannot perform its authoring mutation. ``supported_actions``
    intentionally returns only fully supported actions.
    """

    status: AdapterCapabilityStatus
    reason: str = ""

    @classmethod
    def supported(cls, reason: str = "") -> "AdapterCapability":
        return cls(AdapterCapabilityStatus.SUPPORTED, reason)

    @classmethod
    def read_only(cls, reason: str = "") -> "AdapterCapability":
        return cls(AdapterCapabilityStatus.READ_ONLY, reason)

    @classmethod
    def unsupported(cls, reason: str = "") -> "AdapterCapability":
        return cls(AdapterCapabilityStatus.UNSUPPORTED, reason)

    @property
    def is_supported(self) -> bool:
        return self.status is AdapterCapabilityStatus.SUPPORTED

    @property
    def is_read_only(self) -> bool:
        return self.status is AdapterCapabilityStatus.READ_ONLY

    @property
    def is_unsupported(self) -> bool:
        return self.status is AdapterCapabilityStatus.UNSUPPORTED


def _supported_actions(capabilities: Any) -> Tuple[str, ...]:
    return tuple(
        capability_field.name
        for capability_field in fields(capabilities)
        if isinstance(
            capability := getattr(capabilities, capability_field.name),
            AdapterCapability,
        )
        and capability.is_supported
    )


@dataclass(frozen=True)
class StageCapabilities:
    """Static stage-level action support exposed by a provider session."""

    create_stage: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    export_stage: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    create_prims: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    delete_prims: AdapterCapability = field(default_factory=AdapterCapability.unsupported)

    def supported_actions(self) -> Tuple[str, ...]:
        return _supported_actions(self)


@dataclass(frozen=True)
class PropertyCapabilities:
    """Static property authoring support exposed by a property adapter.

    ``clear_values`` covers the shared public operation that removes authored
    opinions. Existing reset affordances are backed by that same adapter
    operation until a distinct reset API exists.
    """

    clear_values: AdapterCapability = field(default_factory=AdapterCapability.unsupported)

    def supported_actions(self) -> Tuple[str, ...]:
        return _supported_actions(self)


@dataclass(frozen=True)
class LayerStackCapabilities:
    """Static layer-stack action support exposed by a layer adapter."""

    layer_stack: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    edit_target_read: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    edit_target_write: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    save_layer: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    save_layer_as: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    create_sublayer: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    insert_sublayer: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    remove_sublayer: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    reload_layer: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    mute_layer: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    lock_layer: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    move_sublayer: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    replace_sublayer: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    prim_spec_read: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    prim_spec_edit: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    layer_snapshot: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    layer_restore: AdapterCapability = field(default_factory=AdapterCapability.unsupported)
    transfer_layer_content: AdapterCapability = field(default_factory=AdapterCapability.unsupported)

    def supported_actions(self) -> Tuple[str, ...]:
        return _supported_actions(self)


@dataclass(frozen=True)
class AdapterCapabilities:
    """Provider-session capability snapshot.

    This surface is limited to provider/session actions. Per-selection
    property capabilities and per-stage layer-stack capabilities live on the
    concrete :class:`PropertyAdapter` and :class:`LayerStackAdapter`
    instances, where the backing stage/selection context actually exists.
    """

    stage: StageCapabilities = field(default_factory=StageCapabilities)


class UnresolvedDeliveryDebtError(RuntimeError):
    """Non-destructive, retryable refusal: provider delivery is still owed.

    Raised by adapter disposal — and recognized by application replacement
    and shutdown preflights — when genuine visibility roots could not be
    proven delivered to the provider stream. The raising adapter remains
    fully functional: its listeners, subscribers, and the owed roots stay
    intact, and the refused operation may be retried after the provider
    recovers (the retry delivers the complete owed union first).
    """


# ──────────────────────────────────────────────────────────────────────────────
# Abstract Base Classes — StageAdapter and related adapters
# ──────────────────────────────────────────────────────────────────────────────

class StageAdapter(ABC):
    """Hierarchy / scene-graph adapter used by StageWidget.

    Change-event contract — see ``ChangeEventType``:

    - ``INFO_CHANGE`` — an attribute, metadata, or other per-prim value
      changed; hierarchy is unchanged. The widget refreshes affected rows.
    - ``RESYNC`` — prims were added, removed, reparented, or reordered.
      The widget invalidates the subtree rooted at the common prefix.
    - ``LAYER_INFO`` — root-layer metadata changed (most commonly the
      stage's ``defaultPrim``). Adapters **must** emit this so the widget
      can re-query ``IS_DEFAULT_PRIM`` on the affected prims.
    """

    # ── Hierarchy ──

    @abstractmethod
    def get_root(self) -> AdapterItem: ...

    @abstractmethod
    def get_children(self, item: AdapterItem) -> List[AdapterItem]: ...

    @abstractmethod
    def can_have_children(self, item: AdapterItem) -> bool: ...

    @abstractmethod
    def get_item_path(self, item: AdapterItem) -> str: ...

    @abstractmethod
    def get_item_at_path(self, path: str) -> Optional[AdapterItem]: ...

    # ── Display ──

    @abstractmethod
    def get_display_name(self, item: AdapterItem) -> str: ...

    @abstractmethod
    def get_type_name(self, item: AdapterItem) -> str:
        """Exact scene-graph type (e.g. ``"Sphere"``, ``"DistantLight"``).

        This is the raw value exposed to the Type column model. Display
        delegates may normalize presentation separately. For high-level
        grouping (icons, filters) use :py:meth:`get_type_category` instead.
        """

    def get_type_category(self, item: AdapterItem) -> str:
        """High-level category for the item's type.

        Returns one of ``"Mesh" | "Light" | "Camera" | "Xform" | "Scope" | "Other"``.
        Default looks up :py:meth:`get_type_name` in a built-in map — adapters can
        override for O(1) schema-based dispatch.
        """
        return _DEFAULT_TYPE_CATEGORY_MAP.get(self.get_type_name(item).lower(), "Other")

    @abstractmethod
    def get_icon_name(self, item: AdapterItem) -> str: ...

    @abstractmethod
    def get_badge_flags(self, item: AdapterItem) -> BadgeFlags: ...

    @abstractmethod
    def get_item_flags(self, item: AdapterItem) -> ItemFlags: ...

    # ── Visibility ──

    @abstractmethod
    def compute_visibility(self, item: AdapterItem) -> VisibilityState: ...

    @abstractmethod
    def set_visibility(self, item: AdapterItem, visible: bool) -> None: ...

    @abstractmethod
    def can_edit_visibility(self, item: AdapterItem) -> bool: ...

    # ── Rename ──

    @abstractmethod
    def can_rename(self, item: AdapterItem) -> bool: ...

    @abstractmethod
    def rename(self, item: AdapterItem, new_name: str) -> str:
        """Rename item. Returns the actual name used (may differ on collision)."""

    @abstractmethod
    def normalize_name(self, name: str) -> str:
        """Strip illegal characters; collision handling is adapter-specific."""

    # ── Drag-drop / reparent ──

    @abstractmethod
    def can_reparent(self, items: List[AdapterItem], new_parent: AdapterItem) -> bool: ...

    @abstractmethod
    def reparent(
        self,
        items: List[AdapterItem],
        new_parent: AdapterItem,
        position: ReparentPosition,
    ) -> None: ...

    # ── Filter ──

    @abstractmethod
    def filter_items(
        self,
        items: List[AdapterItem],
        predicate: Callable[[AdapterItem], bool],
    ) -> List[AdapterItem]: ...

    # ── Change notifications ──

    @abstractmethod
    def subscribe_changes(self, callback: Callable[[ChangeEvent], None]) -> SubscriptionProtocol:
        """Subscribe to stage change events. Returns RAII Subscription."""

    def notify_transform_changed(
        self,
        paths: List[str],
        source: Optional[str] = None,
    ) -> None:
        """Emit a transform-info event for adapters that support manual edits.

        Default adapters rely on their native scene notice system. USD-backed
        viewport manipulation suppresses raw USD notices while dragging, then
        calls this for each live manipulator frame and again after mouse-up so
        views that observe stage changes can refresh both live and final
        transform state.
        """

    # ── Undo integration ──

    @abstractmethod
    def begin_undo_group(self, label: str) -> None: ...

    @abstractmethod
    def end_undo_group(self) -> None: ...

    # ── Notification suppression ──

    @abstractmethod
    def suppress_change_notifications(self) -> ContextManager:
        """Context manager that drops ChangeEvents while active."""

    # ── World AABB / framing / bound-camera ───────────────────────────────────
    #
    # These three methods let viewport-side framing and bound-camera restore
    # work through the abstract contract instead of reaching for a raw
    # ``Usd.Stage``. The current ``ViewportWidget`` still uses inline pxr code
    # for these queries; that call-site rewrite happens later in the
    # data-adapters refactor (Step 17 of the plan). Step 7 only introduces
    # the abstract surface and concrete implementations.

    @abstractmethod
    def compute_world_aabb(self, paths: List[str]) -> AABB:
        """Return the combined world-space AABB enclosing ``paths``.

        Returns ``None`` when ``paths`` is empty, when the stage is
        unavailable, or when no prim contributes a non-empty bound.
        Concrete adapters may treat a selected grouping prim as a subtree
        request so frame-selection behavior matches user expectations for
        hierarchy selections. The pseudo-root path ``"/"`` is treated as
        "everything".
        """

    @abstractmethod
    def compute_prim_world_aabb_with_extent_fallback(self, path: str) -> AABB:
        """Return ``((min_xyz, max_xyz))`` for the prim at ``path`` or ``None``.

        Implementations should use backend-native or mirrored geometry data
        and return ``None`` when that data is unavailable. This method is for
        one concrete prim; subtree/group selection behavior belongs in
        :meth:`compute_world_aabb`.
        """

    @abstractmethod
    def read_bound_camera(self) -> Optional[BoundCameraPose]:
        """Return a bound-camera pose when the adapter can provide one.

        A concrete adapter may parse authored camera metadata, read a
        mirrored camera prim, or derive a basic framing pose from computed
        bounds. Returns ``None`` when no adapter-supported bound-camera data
        or computed bounds are available; callers then fall back to bbox
        framing.
        """

    def read_stage_up_axis(self) -> str:
        """Return the stage up-axis metadata as ``"Y"`` or ``"Z"``.

        The default keeps older/minimal adapters compatible and matches USD's
        effective default. USD-backed adapters should override this so
        viewport fallback framing can apply stage orientation even when no
        bound-camera pose exists.
        """
        return "Y"

    # ── Viewport selector defaults ───────────────────────────────────────────
    #
    # Selector menus should be able to query any StageAdapter without forcing
    # every mock/minimal adapter to implement camera or render-product support.

    def list_cameras(self) -> List[StageChoice]:
        """Return stage cameras selectable by a viewport camera menu.

        The default empty list keeps existing adapters valid. USD-backed
        adapters override this to return ``UsdGeom.Camera`` prims.
        """
        return []

    def read_camera_pose(self, path: str) -> Optional[BoundCameraPose]:
        """Return the world-space pose for camera ``path`` if available.

        Viewport camera selectors can call this after a menu selection. The
        default ``None`` means the adapter has no camera-pose support.
        """
        return None

    def write_camera_pose_from_matrices(
        self,
        path: str,
        view_matrix: Matrix4d,
        proj_matrix: Matrix4d,
        width: int,
        height: int,
        target_world: Vec3f,
        source: Optional[str] = None,
        undoable: bool = True,
    ) -> bool:
        """Persist the active viewport pose onto a selected camera prim.

        The default ``False`` keeps non-USD and minimal test adapters source
        compatible. USD-backed adapters override this for selected-camera edit
        mode so viewport navigation moves the actual camera prim, not only a
        detached/free runtime camera. ``source`` optionally tags the resulting
        change event so subscribers can distinguish their own camera writes
        from external edits without suppressing source-less USD notifications.
        ``undoable`` lets teardown persist a final pose without adding a
        user-visible undo entry.
        """
        return False

    def list_render_products(self) -> List[StageChoice]:
        """Return USD render products selectable by a viewport menu.

        The default empty list keeps mock/minimal adapters and non-USD stages
        from needing a render-product concept.
        """
        return []

    def get_render_target_catalog(self) -> RenderTargetCatalog:
        """Return a rich render-target catalog, if supported.

        The default empty catalog keeps existing adapters source-compatible.
        Backends that know sensor/source/output metadata should override this
        instead of exposing backend objects to UI code.
        """
        return RenderTargetCatalog()


class TransformAdapter(ABC):
    """3D transform read/write adapter used by viewport manipulation."""

    @abstractmethod
    def get_local_transform(self, path: str) -> List[List[float]]:
        """Returns 4×4 row-major matrix as list-of-lists."""

    @abstractmethod
    def get_world_transform(self, path: str) -> List[List[float]]:
        """Returns 4×4 world-space matrix."""

    @abstractmethod
    def set_local_transform(self, path: str, matrix: List[List[float]]) -> None:
        """Set local transform. Does NOT push to undo — caller manages group."""

    @abstractmethod
    def can_transform(self, path: str) -> bool:
        """False for instance proxies, abstract prims, etc."""

    def get_transform_edit_policy(self, path: str) -> TransformEditPolicy:
        """Return the edit policy used by viewport transform controls.

        Older adapters only implement :meth:`can_transform`; the default
        policy preserves that behavior. Physics-aware adapters override this
        to distinguish direct writes from solver-owned/redirected edits.
        """
        if self.can_transform(path):
            return TransformEditPolicy(TransformEditMode.DIRECT)
        return TransformEditPolicy(
            TransformEditMode.BLOCKED,
            reason="transform is unavailable for this path",
        )

    def teleport_local_transform(self, path: str, matrix: List[List[float]]) -> None:
        """Apply an explicit teleport/reset-style local transform edit.

        Backends with running simulation can override this to bound the edit
        by a pause or step-synchronization point. The default preserves the
        historical direct write behavior.
        """
        self.set_local_transform(path, matrix)

    def reset_local_transform(self, path: str) -> None:
        """Reset local transform to identity using teleport semantics."""
        self.teleport_local_transform(
            path,
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
        )


class PropertyAdapter(ABC):
    """Attribute/property adapter; also serves as a SelectionBus payload."""

    @abstractmethod
    def get_paths(self) -> List[str]: ...

    @abstractmethod
    def is_valid(self) -> bool: ...

    @abstractmethod
    def get_attribute_names(self) -> List[str]: ...

    @abstractmethod
    def get_attribute_metadata(self, attr_name: str) -> AttributeMetadata: ...

    @abstractmethod
    def get_value(self, attr_name: str) -> Any: ...

    @abstractmethod
    def is_ambiguous(self, attr_name: str) -> bool: ...

    @abstractmethod
    def get_per_component_ambiguity(self, attr_name: str) -> Optional[List[bool]]:
        """Per-channel ambiguity for vector attributes; ``None`` for scalars. See property metadata behavior."""

    @abstractmethod
    def begin_edit(self, attr_name: str) -> None: ...

    @abstractmethod
    def set_value(self, attr_name: str, value: Any) -> None: ...

    @abstractmethod
    def end_edit(self, attr_name: str) -> None: ...

    def cancel_edit(self, attr_name: str) -> None:
        """Cancel an active edit transaction without recording history.

        Backends that keep per-edit state (snapshots, tokens) override
        this to release it and remove any partial authorship; the default
        matches backends whose ``begin_edit`` holds no state.
        """

    @abstractmethod
    def subscribe_changes(self, callback: Callable[[], None]) -> SubscriptionProtocol: ...

    @abstractmethod
    def get_scheme(self) -> str:
        """Return backend identifier, e.g. 'usd' or 'mock'."""

    def get_capabilities(self) -> PropertyCapabilities:
        """Return explicit property actions supported by this adapter."""
        return PropertyCapabilities()

    def get_resolved_asset_path(self, attr_name: str) -> Optional[str]:
        """Resolved absolute path for an asset-path attribute.

        Adapters that back asset-path attributes (USD's ``Sdf.AssetPath``)
        return the ArResolver-resolved absolute path; the
        :class:`AssetPathAttributeRow` shows this as a tooltip alongside
        the authored path. The default implementation returns ``None`` so
        adapters that don't know or don't care about asset resolution need
        not override.

        Introduced by Step 3.6 of the property inspector implementation. Not abstract — a
        concrete ``None`` default keeps existing adapters valid.
        """
        return None

    def clear_value(self, attr_name: str) -> None:
        """Revert ``attr_name`` to its default (unauthored) value.

        Drives the ``NotDefault``
        control-state indicator's click action: when the attribute has an
        authored opinion that differs from the schema default, the user
        clicks the icon and this method removes the authored opinion.

        The ABC default raises :class:`NotImplementedError` so adapters
        that do not yet support reset-to-default opt out explicitly — the
        :class:`ControlStateIndicator` hides its icon when the click
        handler would raise, preserving the row's geometry without
        exposing a dead button. Adapters that support the operation
        override to perform the backing-store-specific clear (USD calls
        :meth:`pxr.Usd.Attribute.Clear`).
        """
        raise NotImplementedError(
            f"{type(self).__name__}.clear_value is not implemented"
        )


class RendererAdapter(ABC):
    """GPU rendering adapter used by ViewportWidget."""

    @abstractmethod
    def load_stage(self, stage: Any) -> None:
        """Load or reload a USD stage into the renderer."""

    @abstractmethod
    def render_frame(
        self,
        width: int,
        height: int,
        view_matrix: Matrix4d,
        proj_matrix: Matrix4d,
    ) -> NDArray | GpuFrameHandle:
        """Render one frame.

        Returns an RGBA uint8 numpy array of shape ``(H, W, 4)``, or a
        :data:`~ovui_data_adapters.common.GpuFrameHandle` (concrete viewport
        implementation: :class:`ovui_data_adapters.common.GpuFrame`)
        carrying a renderer-owned GPU pointer for callers that support
        direct GPU presentation. The runtime annotation uses the
        lightweight ``NDArray`` alias (resolves to ``Any`` at runtime,
        ``numpy.ndarray`` for static type checkers) so
        :func:`typing.get_type_hints` works without importing NumPy merely to
        inspect this abstract contract.
        """

    def get_active_camera_path(self) -> Optional[str]:
        """Return the renderer's active camera path, if selection is supported."""
        return None

    def set_active_camera_path(self, path: Optional[str]) -> bool:
        """Select the renderer camera by prim path.

        Returns ``True`` when the renderer accepted the path. The base
        implementation is an explicit no-op so existing mock/minimal
        renderers do not need to grow selector state until they support it.
        Passing ``None`` asks supporting renderers to restore their fallback
        camera.
        """
        return False

    def get_active_render_product_path(self) -> Optional[str]:
        """Return the renderer's active render product path, if supported."""
        return None

    def set_active_render_product_path(self, path: Optional[str]) -> bool:
        """Select the renderer render product by prim path.

        Returns ``True`` when the renderer accepted the path. The base
        implementation is an explicit no-op so existing renderer adapters
        remain source-compatible. Passing ``None`` asks supporting renderers
        to restore their fallback render product.
        """
        return False

    def supports_in_place_stage_swap(self) -> bool:
        """Whether ``load_stage`` can transition this renderer from its
        currently-loaded stage to a different one *in place*, with an
        authoritative OLD-or-NEW identity even if cleanup reports afterward.

        When ``True``, the application reuses this already-attached renderer
        for a document replacement instead of constructing a second renderer
        that would run alongside it — two live GPU renderers contending for
        native scene/RenderSettings resolution can freeze the frame loop.
        The default declines so renderers that require a fresh instance per
        stage (e.g. a borrow-mode renderer that cannot swap an attached
        scene) keep the construct-fresh path. Implementations that return
        ``True`` should also implement :meth:`is_stage_current`; an unknown
        identity after a throwing load is handled fail-closed.
        """
        return False

    def is_stage_current(self, stage: Any) -> Optional[bool]:
        """Return whether ``stage`` is the renderer's authoritative stage.

        In-place renderers use this after a throwing :meth:`load_stage` to
        distinguish a complete-old failure from a committed-new failure that
        surfaced cleanup debt. ``None`` means the renderer cannot prove either
        identity; callers must fail closed rather than assume rollback.
        """
        return None

    @property
    def supports_live_local_transform(self) -> bool:
        """Whether this renderer can preview local transforms without authoring."""
        return False

    def set_live_local_transform(self, path: str, matrix: Matrix4d) -> bool:
        """Preview a prim-local transform without mutating authoritative data.

        Returns ``True`` when the renderer accepted the preview. The default
        declines so renderers remain source-compatible until they opt in.
        """
        return False

    def clear_live_local_transforms(self, paths: List[str]) -> None:
        """Release live transform previews for ``paths`` when supported."""
        return None

    def activate_render_target(
        self,
        target_id: Optional[str] = None,
        render_product_path: Optional[str] = None,
    ) -> RenderTargetActivationResult:
        """Activate a descriptor-backed render target, if supported.

        The default rejected result keeps existing renderer adapters
        source-compatible until concrete adapters opt in to richer SRD 6.1
        activation reporting.
        """
        return RenderTargetActivationResult.rejected_result(
            "Render target activation is not supported.",
            warning_code="unsupported",
        )

    def list_point_cloud_outputs(
        self,
        render_product_path: Optional[str] = None,
    ) -> PointCloudOutputCatalog:
        """Return point-cloud outputs available to this renderer, if supported."""

        return PointCloudOutputCatalog()

    def set_point_cloud_request(
        self,
        viewport_id: str,
        request: Optional[PointCloudRequest],
    ) -> PointCloudRequestResult:
        """Request point-cloud extraction for one viewport, if supported."""

        return PointCloudRequestResult.rejected_result(
            "Point-cloud output is not supported.",
            warning_code="unsupported",
        )

    def get_latest_point_cloud_frame(
        self,
        viewport_id: str,
        render_product_path: Optional[str] = None,
    ) -> Optional[PointCloudFrame]:
        """Return the latest point-cloud snapshot for one viewport, if available."""

        return None

    def clear_point_cloud_request(self, viewport_id: str) -> None:
        """Clear a viewport point-cloud extraction request, if supported."""

        return None

    def list_render_var_outputs(
        self,
        render_product_path: Optional[str] = None,
    ) -> RenderVarOutputCatalog:
        """Return visualizable RenderVar outputs available to this renderer."""

        return RenderVarOutputCatalog()

    def set_render_var_output_request(
        self,
        viewport_id: str,
        request: Optional[RenderVarOutputRequest],
    ) -> RenderVarOutputRequestResult:
        """Request RenderVar output visualization for one viewport, if supported."""

        return RenderVarOutputRequestResult.rejected_result(
            "RenderVar output visualization is not supported.",
            warning_code="unsupported",
        )

    def get_latest_render_var_output_frame(
        self,
        viewport_id: str,
        render_product_path: Optional[str] = None,
    ) -> Optional[RenderVarOutputFrame]:
        """Return the latest RenderVar visualization snapshot, if available."""

        return None

    def clear_render_var_output_request(self, viewport_id: str) -> None:
        """Clear a viewport RenderVar visualization request, if supported."""

        return None

    def probe_render_var_output(
        self,
        request: RenderVarProbeRequest,
    ) -> RenderVarProbeResult:
        """Return a raw RenderVar value probe result, if supported."""

        return RenderVarProbeResult.unsupported_result()

    @abstractmethod
    def set_resolution(self, width: int, height: int) -> None:
        """Update render target size."""

    @abstractmethod
    def pick(
        self,
        x: float,
        y: float,
        callback: Callable[[Optional[str], Optional[Vec3f]], None],
        query_name: str,
    ) -> None:
        """Async single-pixel pick at viewport pixel (x, y)."""

    @abstractmethod
    def cancel_pick(self, query_name: str) -> None:
        """Cancel pending pick. After return callback MUST NOT be invoked."""

    @abstractmethod
    def pick_rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        callback: Callable[[List[str]], None],
    ) -> None:
        """Rectangle selection pick. callback receives list of prim paths in rect."""

    @abstractmethod
    def set_selection_highlight(self, paths: List[str]) -> None:
        """Update renderer highlight overlay. Empty list clears all highlights."""

    @abstractmethod
    def shutdown(self) -> None:
        """Release GPU resources."""


class SelectionAdapter(ABC):
    """Translates SelectionBus items to adapter-specific items."""

    @abstractmethod
    def to_adapter_items(self, selection: Any) -> List[AdapterItem]: ...

    @abstractmethod
    def to_selection_items(self, adapter_items: List[AdapterItem]) -> List[Any]: ...


# ──────────────────────────────────────────────────────────────────────────────
# LayerStackAdapter family.
#
# Layer-stack types consumed by the Layers window. Moved here from
# ``ovui_widgets.layers.adapter`` per issue #38 so the full adapter family lives in
# one canonical location alongside ``StageAdapter`` / ``TransformAdapter`` /
# ``PropertyAdapter`` / ``RendererAdapter`` / ``SelectionAdapter``.
# ──────────────────────────────────────────────────────────────────────────────


class LayerEventType(Enum):
    """Event taxonomy for :class:`LayerStackAdapter` change notifications.

    ``OUTDATE_STATE_CHANGED`` is reserved for future use (v1 adapters do not
    emit it; the value exists so the UI can stub-handle it and so adapters
    can emit it in a later release without an ABC break).
    """

    EDIT_TARGET_CHANGED = auto()
    SUBLAYERS_CHANGED = auto()
    DIRTY_STATE_CHANGED = auto()
    MUTE_STATE_CHANGED = auto()
    LOCK_STATE_CHANGED = auto()
    INFO_CHANGED = auto()
    FILE_PERMISSION_CHANGED = auto()
    OUTDATE_STATE_CHANGED = auto()


@dataclass(frozen=True)
class LayerEvent:
    """Immutable notification emitted by :class:`LayerStackAdapter`.

    ``identifiers`` is a tuple (not a list) so the field itself is hashable
    and safe to log — callers may aggregate it in sets/dicts without the risk
    of a handler mutating the list between emit and consumption. An empty
    tuple means "re-query everything" — emitted for broad changes such as
    ``EDIT_TARGET_CHANGED`` where the affected layer set is implicit.

    ``info_fields`` maps a layer identifier to the tuple of metadata field
    names that changed on that layer (used by ``INFO_CHANGED``). Empty dict
    otherwise. The dict makes the whole event unhashable by design: callers
    hash or deduplicate on ``identifiers`` instead.
    """

    event_type: LayerEventType
    identifiers: Tuple[str, ...] = ()
    info_fields: Dict[str, Tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class LayerHandle:
    """Opaque handle for a layer in the stack.

    Adapters mint handles; the UI passes them back unchanged. The only
    public attribute is :attr:`identifier` — a stable string key that
    matches ``Sdf.Layer.identifier`` in USD-backed adapters. UI and test
    code must never reach beyond this attribute: doing so would leak
    backend types (``Sdf.Layer``) across the Kit-free boundary.
    """

    identifier: str


class PrimSpecifier(Enum):
    """USD prim-spec specifier kind. Mirrors ``Sdf.SpecifierDef/Over/Class``."""

    DEF = auto()
    OVER = auto()
    CLASS = auto()


@dataclass(frozen=True)
class LayerSnapshot:
    """Opaque-ish round-trip token produced by :meth:`LayerStackAdapter.snapshot_layer`.

    LAYERS-PLAN Step 42 — :class:`~ovui_widgets.layers.commands.MergeDownCommand`
    and :class:`~ovui_widgets.layers.commands.FlattenSublayersCommand` use this
    record to restore a layer after a destructive merge. The snapshot
    captures enough state to rebuild the layer at its original position
    under its original parent and to replay its mute / lock flags +
    edit-target bit.

    - ``identifier`` — the layer's identifier at snapshot time. For
      anonymous layers, a fresh identifier may be minted on restore
      (USD mints a new ``anon:N`` on
      :meth:`Sdf.Layer.CreateAnonymous`); callers that care about the
      post-restore identifier use the return value of
      :meth:`restore_layer_from_snapshot`.
    - ``parent_identifier`` — the identifier of the parent that
      referenced this layer, or ``None`` if the layer was not a
      sublayer of anything (top-level / session / detached).
    - ``position_in_parent`` — index of this layer in the parent's
      sublayer list at snapshot time, or ``-1`` if no parent.
    - ``was_edit_target`` — whether the layer was the stack's edit
      target at snapshot time. :meth:`restore_layer_from_snapshot`
      flips the edit target back when ``True``.
    - ``anonymous`` — whether the layer was anonymous. Drives the
      restore path (``CreateAnonymous`` vs ``FindOrOpen``).
    - ``content`` — opaque serialised layer content. For the USD
      adapter this is the full USDA dump from ``Sdf.Layer.ExportToString``;
      for the mock it is a deterministic encoding of the mock record.
      The only guarantee is that :meth:`restore_layer_from_snapshot`
      accepts whatever :meth:`snapshot_layer` produced.
    - ``custom_layer_data`` — copy of the layer's ``customLayerData``
      dict (USD) or ``info`` dict (mock). Round-tripped so the
      restored layer carries the same key/value pairs.
    - ``mute_state`` — the mute bit at snapshot time.
    - ``lock_state`` — the per-layer lock bit at snapshot time.
    - ``sublayer_identifiers`` — tuple of direct-sublayer identifiers
      at snapshot time. Allows the restore path to rebuild the
      subLayerPaths list without re-parsing ``content``. Stored as a
      tuple so the dataclass remains hashable against the `field` default.
    """

    identifier: str
    parent_identifier: Optional[str]
    position_in_parent: int
    was_edit_target: bool
    anonymous: bool
    content: str
    custom_layer_data: Dict[str, Any] = field(default_factory=dict)
    mute_state: bool = False
    lock_state: bool = False
    sublayer_identifiers: Tuple[str, ...] = ()


@dataclass(frozen=True)
class PrimSpecDescriptor:
    """Plain-data description of a single prim spec on a layer.

    Populated by :meth:`LayerStackAdapter.get_prim_specs` in Step 47. Defined
    here so the adapter package owns the whole layer-stack type family and
    later steps never have to reach across modules.
    """

    path: str
    type_name: str
    specifier: PrimSpecifier
    has_reference: bool
    has_payload: bool
    is_instanceable: bool


class LayerStackAdapter(ABC):
    """Layer-stack adapter consumed by the Layers window.

    One adapter instance wraps exactly one layer stack (one ``Usd.Stage`` in
    the USD implementation); no module-level state. The Layers UI talks to
    this interface only — it never imports ``pxr`` or any Kit module
    (constraint G2 / Kit-free import rule).

    Change-event contract — see :class:`LayerEventType` for the full
    taxonomy. Subscribers receive :class:`LayerEvent` instances over
    :meth:`subscribe_events`; commands in ``ovui_widgets.layers/commands/`` wrap
    mutators with do/undo logic — the adapter never pushes to an undo
    stack on its own.
    """

    # ── Stack discovery ──────────────────────────────────────────────

    def get_capabilities(self) -> LayerStackCapabilities:
        """Return explicit layer actions supported by this adapter."""
        return LayerStackCapabilities()

    @abstractmethod
    def get_root_layer(self) -> LayerHandle:
        """Return a handle to the root layer of the stack."""

    @abstractmethod
    def get_session_layer(self) -> Optional[LayerHandle]:
        """Return a handle to the session layer, or ``None`` if absent."""

    @abstractmethod
    def get_sublayer_identifiers(self, parent: LayerHandle) -> List[str]:
        """Return the ordered list of sublayer identifiers composed under ``parent``."""

    @abstractmethod
    def find_layer(self, identifier: str) -> Optional[LayerHandle]:
        """Look up a layer by its stable identifier. Returns ``None`` if absent."""

    @abstractmethod
    def get_layer_stack_identifiers(
        self,
        include_session: bool = False,
        include_anonymous: bool = True,
    ) -> List[str]:
        """Return the identifiers of every layer in the composed stack.

        ``include_session`` — when ``True``, include the session layer.
        ``include_anonymous`` — when ``False``, skip anonymous layers
        (useful for Save-All, which cannot save anonymous layers without
        first assigning a path).
        """

    # ── Display ──────────────────────────────────────────────────────

    @abstractmethod
    def get_display_name(self, layer: LayerHandle) -> str:
        """Return the human-readable name the Layers window should show."""

    @abstractmethod
    def get_layer_owner(self, layer: LayerHandle) -> str:
        """Return the POSIX owner of the layer file, or ``""`` if unknown."""

    # ── State flags ──────────────────────────────────────────────────

    @abstractmethod
    def is_anonymous(self, layer: LayerHandle) -> bool:
        """``True`` iff the layer is in-memory only and has no file path."""

    @abstractmethod
    def is_dirty(self, layer: LayerHandle) -> bool:
        """``True`` iff the layer has unsaved edits."""

    @abstractmethod
    def is_muted(self, layer: LayerHandle) -> bool:
        """``True`` iff the layer is muted (excluded from composition)."""

    @abstractmethod
    def is_locked(self, layer: LayerHandle) -> bool:
        """``True`` iff the layer is locked against authoring."""

    @abstractmethod
    def is_read_only_on_disk(self, layer: LayerHandle) -> bool:
        """``True`` iff the backing file is not writable by the current user."""

    @abstractmethod
    def is_missing(self, layer: LayerHandle) -> bool:
        """``True`` iff the layer could not be resolved (``Sdf.Find`` returned ``None``)."""

    def is_writable(self, layer: LayerHandle) -> bool:
        """Composite writability flag used by the UI to gate edit gestures.

        Concrete (non-abstract) by design so every adapter gets the same
        definition for free. Subclasses may override only if they have a
        faster path (e.g. caching the combined state).
        """
        return not (
            self.is_locked(layer)
            or self.is_muted(layer)
            or self.is_read_only_on_disk(layer)
        )

    # ── Edit target ──────────────────────────────────────────────────

    @abstractmethod
    def get_edit_target_identifier(self) -> str:
        """Return the identifier of the layer currently targeted for authoring."""

    # ── Change subscription ──────────────────────────────────────────

    @abstractmethod
    def subscribe_events(
        self,
        callback: Callable[[LayerEvent], None],
    ) -> SubscriptionProtocol:
        """Subscribe to layer-stack change events.

        Returns an RAII :class:`~ovui_widgets.common.settings.Subscription`; callers keep
        the handle alive for the subscription to remain active. The adapter
        must invoke ``callback`` on every emitted :class:`LayerEvent`.
        """

    # ── Mutations (Step 6) ───────────────────────────────────────────
    # Commands in Phase F wrap these with do/undo logic. The adapter
    # itself never pushes to ``UndoManager``.

    @abstractmethod
    def set_edit_target(self, identifier: str) -> None:
        """Set the layer targeted for authoring edits.

        Emits ``EDIT_TARGET_CHANGED``. Raises ``KeyError``/``ValueError`` if
        ``identifier`` is unknown to the adapter.
        """

    @abstractmethod
    def set_mute(self, identifier: str, muted: bool) -> None:
        """Mute (``True``) or unmute (``False``) the given layer.

        Emits ``MUTE_STATE_CHANGED`` iff the mute bit actually flipped.
        No-op if the current state already matches ``muted``.
        """

    @abstractmethod
    def set_lock(self, identifier: str, locked: bool) -> None:
        """Set the per-layer lock bit (a Kit-level advisory guardrail).

        Emits ``LOCK_STATE_CHANGED`` iff the lock bit flipped. Persisted
        to the root layer's ``customLayerData`` in USD-backed adapters;
        mock adapters keep the bit in-memory only.
        """

    @abstractmethod
    def create_sublayer(
        self,
        parent_id: str,
        position: int,
        new_layer_path: str,
        transfer_root_content: bool = False,
    ) -> str:
        """Create a new layer and insert it as a sublayer of ``parent_id``.

        ``new_layer_path`` — empty string creates an anonymous layer,
        otherwise creates a fresh file at that path. ``position`` follows
        :py:meth:`list.insert` semantics (``-1`` appends).
        ``transfer_root_content`` — when ``True``, root prims are copied
        from the stage's root layer onto the new sublayer and cleared
        from root (used by the "Split root to sublayer" gesture).

        Returns the identifier of the newly created layer.
        """

    @abstractmethod
    def insert_sublayer(
        self,
        parent_id: str,
        position: int,
        sublayer_path: str,
    ) -> None:
        """Insert an *existing* layer path into ``parent_id`` at ``position``.

        The layer file must already exist; ``sublayer_path`` is stored as
        the sublayer reference. Emits ``SUBLAYERS_CHANGED``.
        """

    @abstractmethod
    def remove_sublayer(self, parent_id: str, position: int) -> str:
        """Remove the sublayer at ``position`` from ``parent_id``.

        Returns the identifier that was removed so an undo handler can
        re-insert it. Emits ``SUBLAYERS_CHANGED``. Raises
        :class:`IndexError` on out-of-range positions.
        """

    @abstractmethod
    def move_sublayer(
        self,
        from_parent_id: str,
        from_position: int,
        to_parent_id: str,
        to_position: int,
        remove_source: bool = True,
    ) -> None:
        """Move (or copy-reference) a sublayer between slots.

        When ``remove_source=True`` the sublayer is unlinked from the
        source parent; when ``False`` both parents reference the same
        child (valid USD composition). Emits ``SUBLAYERS_CHANGED`` for
        every parent touched.
        """

    @abstractmethod
    def replace_sublayer(
        self,
        parent_id: str,
        position: int,
        new_identifier: str,
    ) -> str:
        """Swap the sublayer entry at ``(parent_id, position)`` for ``new_identifier``.

        Returns the identifier that previously occupied the slot so undo
        handlers can restore it. Emits a single ``SUBLAYERS_CHANGED``
        event on the parent (atomic replace — one notification, not two).
        Raises :class:`IndexError` on out-of-range positions.

        Used by :class:`~ovui_widgets.layers.commands.ReplaceSublayerCommand`
        (LAYERS-PLAN Step 31a) and by the Save-As-with-replace flow
        (Step 36).
        """

    # ── Prim-spec mutation (LAYERS-PLAN Step 31a) ───────────────────
    # ``RemovePrimSpecsCommand`` uses the export/remove/import triple
    # to round-trip prim specs across undo. Adapters serialise to an
    # opaque USDA blob so the command stays backend-agnostic.

    @abstractmethod
    def export_prim_spec(self, layer_id: str, path: str) -> str:
        """Serialise the prim spec at ``path`` on ``layer_id`` to USDA text.

        The returned string is an opaque round-trip token — the only
        guarantee is that :meth:`import_prim_spec` will reconstitute the
        same spec bit-identically. Raises :class:`KeyError` when the
        layer is unknown or the path does not resolve to a prim spec.
        """

    @abstractmethod
    def remove_prim_spec(self, layer_id: str, path: str) -> None:
        """Remove the prim spec at ``path`` from ``layer_id``.

        The layer is marked dirty on a successful removal. Raises
        :class:`KeyError` when the layer is unknown or the path does
        not resolve to a prim spec.
        """

    @abstractmethod
    def import_prim_spec(self, layer_id: str, path: str, usda: str) -> None:
        """Restore a prim spec previously produced by :meth:`export_prim_spec`.

        Creates any intermediate parent specs needed to reach ``path``
        and copies the spec at ``path`` from the serialised form. Raises
        :class:`KeyError` when the layer is unknown.
        """

    # ── Prim-spec discovery (LAYERS-PLAN Step 47) ───────────────────
    # Step 48 renders the returned descriptors as ``PrimSpecItem``
    # children inside each ``LayerItem``; Step 50's DEL command
    # resolves paths against ``has_prim_spec`` before dispatch. The
    # hierarchy is walked one level at a time so the Layers tree can
    # lazy-expand without pulling every descendant on first paint.

    @abstractmethod
    def get_prim_specs(
        self, layer_identifier: str, parent_path: str = "/"
    ) -> List[PrimSpecDescriptor]:
        """Return the direct prim-spec children under ``parent_path``.

        ``parent_path == "/"`` returns the layer's root prims; any other
        path returns the ``nameChildren`` of the prim spec at that path.
        Children are returned in the order the backing layer reports them
        (stage-authored order for USD, insertion order for the mock), so
        callers that need deterministic output should sort by
        :attr:`PrimSpecDescriptor.path` themselves.

        Returns an empty list when the path resolves to a prim spec that
        has no children. Raises :class:`KeyError` when the layer is
        unknown to the adapter, or when ``parent_path`` is not ``"/"``
        and does not resolve to a prim spec on the layer.
        """

    @abstractmethod
    def has_prim_spec(self, layer_identifier: str, spec_path: str) -> bool:
        """``True`` iff ``spec_path`` resolves to a prim spec on the layer.

        Raises :class:`KeyError` when the layer is unknown — matches the
        rest of the prim-spec family (``export_prim_spec`` / ``remove_prim_spec``
        / ``import_prim_spec``) so unknown-layer is never ambiguous with a
        missing-path ``False`` return.
        """

    # ── Merge / Flatten support (LAYERS-PLAN Step 42) ───────────────
    # :class:`~ovui_widgets.layers.commands.MergeDownCommand` and
    # :class:`~ovui_widgets.layers.commands.FlattenSublayersCommand` use the
    # snapshot/restore pair to round-trip a destructive merge across
    # undo. ``transfer_layer_content`` is the atomic merge primitive
    # — it copies every root prim spec from ``src`` into ``dst`` in
    # strength order so the destination ends up with the union of
    # both layers' opinions.

    @abstractmethod
    def snapshot_layer(self, identifier: str) -> "LayerSnapshot":
        """Capture a round-trip snapshot of ``identifier``.

        The returned :class:`LayerSnapshot` can be fed to
        :meth:`restore_layer_from_snapshot` to rebuild the layer at its
        original position under its original parent with its content,
        custom data, mute / lock bits, and edit-target flag restored.

        Raises :class:`KeyError` when ``identifier`` is unknown to the
        adapter.
        """

    @abstractmethod
    def restore_layer_from_snapshot(
        self, snapshot: "LayerSnapshot"
    ) -> str:
        """Rebuild a layer from a previously-captured snapshot.

        Re-inserts the layer into its original parent at the original
        position, replays mute + lock bits, and restores the edit
        target when ``snapshot.was_edit_target`` is ``True``.

        Returns the identifier of the restored layer. Anonymous layers
        may receive a fresh identifier (USD's
        :meth:`Sdf.Layer.CreateAnonymous` mints a new one each call);
        callers that held the old identifier must update their
        internal references to the return value.

        Raises :class:`KeyError` when ``snapshot.parent_identifier``
        is provided but no longer resolves.
        """

    @abstractmethod
    def transfer_layer_content(
        self, src_identifier: str, dst_identifier: str
    ) -> None:
        """Copy every root prim spec from ``src`` into ``dst``.

        Used as the merge primitive for
        :class:`~ovui_widgets.layers.commands.MergeDownCommand`: after calling
        this, ``dst`` holds the union of its own opinions and the
        source's opinions (source wins on overlapping specs — matches
        USD's stronger-over-weaker composition rule for a merge from
        a strictly-stronger source). Neither layer is removed.

        Raises :class:`KeyError` when either identifier is unknown.
        """

    # ── File I/O ─────────────────────────────────────────────────────

    @abstractmethod
    def save_layer(self, identifier: str) -> bool:
        """Persist ``identifier`` to disk. Returns ``True`` on success.

        Emits ``DIRTY_STATE_CHANGED`` iff the dirty bit cleared.
        Anonymous or missing layers cannot be saved and return ``False``.
        """

    @abstractmethod
    def save_layer_as(
        self,
        identifier: str,
        new_path: str,
        replace_in_parent: bool,
    ) -> Optional[str]:
        """Export ``identifier`` to ``new_path``; optionally swap the parent
        sublayer entry.

        Returns the new layer's identifier on success, or ``None`` on
        failure. When ``replace_in_parent=True`` every parent that
        references the old identifier is rewritten to point at the new
        one. Emits ``SUBLAYERS_CHANGED`` for each such parent.
        """

    @abstractmethod
    def reload_layer(self, identifier: str) -> bool:
        """Reload ``identifier`` from disk, discarding unsaved edits.

        Returns ``True`` if the layer reloaded (i.e. there was something
        to reload — a no-op reload returns ``False``). Emits
        ``DIRTY_STATE_CHANGED`` iff the dirty bit cleared.
        """
