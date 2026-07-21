# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""USD-backed PropertyAdapter: attribute enumeration, get/set value, and undo.

Implements the PropertyAdapter ABC using the real USD attribute API.
"""

from __future__ import annotations

import re
import weakref
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

try:
    from pxr import Gf, Sdf, Usd
    HAS_USD = True
except ImportError:
    HAS_USD = False
    Gf = Sdf = Usd = None  # type: ignore[assignment]

from ovui_data_adapters.common import (
    AdapterCapability,
    AttributeMetadata,
    Command,
    PropertyCapabilities,
    PropertyAdapter,
    UndoManagerProtocol,
)

# ──────────────────────────────────────────────────────────────────────────────
# Type and group mapping tables
# ──────────────────────────────────────────────────────────────────────────────

_TYPE_MAP: Dict[str, str] = {
    "float": "float",
    "double": "float",
    "half": "float",
    "int": "int",
    "uint": "int",
    "int64": "int",
    "uint64": "int",
    "string": "str",
    "token": "str",
    "bool": "bool",
    # Vec2 — Step 3.1
    "float2": "float2",
    "double2": "float2",
    "half2": "float2",
    # Vec3
    "float3": "float3",
    "double3": "float3",
    "half3": "float3",
    "vector3f": "float3",
    "vector3d": "float3",
    "vector3h": "float3",
    "normal3f": "float3",
    "normal3d": "float3",
    "point3f": "float3",
    "point3d": "float3",
    "color3f": "color3f",
    "color3d": "color3f",
    "color3h": "color3f",
    # Vec4 — Step 3.1
    "float4": "float4",
    "double4": "float4",
    "half4": "float4",
    # Color4 — Step 3.4
    "color4f": "color4f",
    "color4d": "color4f",
    "color4h": "color4f",
    # Int vec2/3/4 — Step 3.2
    "int2": "int2",
    "int3": "int3",
    "int4": "int4",
    # Matrices — Step 3.5 (USD ships only double-precision matrices; no
    # matrix2f / matrix3f / matrix4f variants exist).
    "matrix2d": "matrix2d",
    "matrix3d": "matrix3d",
    "matrix4d": "matrix4d",
    # Asset path — Step 3.6. USD ships the scalar ``asset`` (SdfAssetPath)
    # and the array ``asset[]`` (SdfAssetPathArray); the array variant is
    # Step 3.8 territory, so only the scalar name is mapped here.
    "asset": "asset",
    # Relationship — Step 3.7. ``Usd.Relationship`` has no
    # ``attr.GetTypeName()`` equivalent; the synthesised ``"relationship"``
    # sentinel is stashed in ``UsdAttributeProp.usd_type_str`` when
    # ``_enumerate_attrs`` walks ``prim.GetRelationships()`` so the builder
    # table key matches.
    "relationship": "relationship",
}

# Step 3.8: length threshold above which an array renders as ``"[N items]"``
# rather than as a full comma-joined tuple. Matches property metadata behavior /
# the property inspector behavior ("big array" = more than 16 elements).
_BIG_ARRAY_THRESHOLD = 16

_VALUE_TYPE_TO_PYTHON: Dict[str, Any] = {
    "float": float,
    "int": int,
    "str": str,
    "bool": bool,
}

_VECTOR_VALUE_TYPES = frozenset({
    "float2", "float3", "float4", "color3f", "color4f",
    "int2", "int3", "int4",
})

_NAMESPACE_GROUP_MAP: Dict[str, str] = {
    "xformOp": "Transform",
    "primvars": "Primvars",
}

_CAMEL_RE = re.compile(r"([a-z])([A-Z])")


# ──────────────────────────────────────────────────────────────────────────────
# Internal data type
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UsdAttributeProp:
    attr_name: str       # Full USD attribute name, e.g. "xformOp:translate"
    display_name: str    # Human-readable, e.g. "Translate"
    group_name: str      # Group label, e.g. "Transform"
    value_type: str      # Our type string, e.g. "float3"
    usd_type_str: str    # Original USD type string, e.g. "double3"


# ──────────────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────────────

def _map_type(usd_type_str: str) -> Optional[str]:
    return _TYPE_MAP.get(usd_type_str.lower())


def _get_group_name(attr_name: str) -> str:
    if ":" in attr_name:
        ns = attr_name.split(":")[0]
        return _NAMESPACE_GROUP_MAP.get(ns, ns.capitalize())
    return "Attributes"


def _get_group_path(prop: Any, attr_name: str) -> str:
    """Return the dot-separated group path for a USD property.

    The Property Inspector now
    splits ``AttributeMetadata.group`` on ``"."`` to build a nested
    :class:`UiDisplayGroup` tree. This helper produces the dotted
    string:

    * If ``prop`` authors a non-empty ``displayGroup`` metadata (USD's
      native colon-separated hierarchy, e.g. ``"Transform:Translate"``),
      the colons are rewritten to dots so the widget's tree builder
      nests the frames correctly. This is the authored-data path — the
      same mechanism upstream Kit uses to drive
      ``UsdPropertyUiEntry.display_group``.
    * Otherwise falls back to :func:`_get_group_name`, the namespace
      heuristic (``xformOp:*`` → ``"Transform"``, unnamespaced →
      ``"Attributes"``). Single-level strings still work as a
      degenerate case of the dot-split — ``"Transform".split(".")``
      yields a single segment.

    ``prop`` may be either a :class:`Usd.Attribute` or a
    :class:`Usd.Relationship`; both subclass :class:`Usd.Property` and
    expose :meth:`GetDisplayGroup`.
    """
    if hasattr(prop, "GetDisplayGroup"):
        dg = prop.GetDisplayGroup()
        if dg:
            return dg.replace(":", ".")
    return _get_group_name(attr_name)


def _get_display_name(attr_name: str) -> str:
    local = attr_name.rsplit(":", 1)[-1]
    local = _CAMEL_RE.sub(r"\1 \2", local)
    return local[0].upper() + local[1:] if local else local


_MATRIX_DIMS: Dict[str, int] = {
    "matrix2d": 2,
    "matrix3d": 3,
    "matrix4d": 4,
}

# Identity matrices (row-major flat tuples), used as ``_default_value`` for
# unauthored matrix attributes. Identity is the sensible default — a zero
# matrix is singular and would make downstream maths explode.
_MATRIX_IDENTITY: Dict[str, tuple] = {
    "matrix2d": (1.0, 0.0, 0.0, 1.0),
    "matrix3d": (
        1.0, 0.0, 0.0,
        0.0, 1.0, 0.0,
        0.0, 0.0, 1.0,
    ),
    "matrix4d": (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ),
}


_OPENUSD_PROPERTY_CAPABILITIES = PropertyCapabilities(
    clear_values=AdapterCapability.supported(),
)


def _range_bound(range_dict: Any, key: str) -> Optional[float]:
    """Coerce ``range_dict[key]`` to ``float`` or ``None``.

    Used by :meth:`UsdPropertyAdapter.get_attribute_metadata` to pull a
    single bound out of the ``customData["range"]`` / ``customData["soft_range"]``
    dict read by :meth:`UsdPropertyAdapter.get_attribute_metadata`. Returns ``None`` when the key is absent
    or the value doesn't coerce cleanly — a malformed author-side
    ``range = {"min": "not-a-number"}`` stays unbounded rather than
    raising a ``TypeError`` during widget construction.
    """
    if not isinstance(range_dict, dict):
        return None
    val = range_dict.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _matrix_to_python(value: Any, n_dim: int) -> tuple:
    """Flatten a ``Gf.MatrixNd`` (row-major) into an ``n_dim * n_dim`` tuple
    of Python floats. ``Gf.Matrix3d[i][j]`` reads row ``i``, column ``j`` —
    matching the ``Gf.Matrix3d(a, b, c, d, e, f, g, h, i)`` constructor
    shape pinned by Step 3.5 (property attribute builder behavior).
    """
    return tuple(
        float(value[row][col])
        for row in range(n_dim)
        for col in range(n_dim)
    )


def _matrix_to_usd(value: Any, n_dim: int) -> Any:
    """Pack a flat ``n_dim * n_dim`` tuple into the matching ``Gf.MatrixNd``.

    The flat-tuple argument shape mirrors USD's constructor — e.g.
    ``Gf.Matrix3d(*flat)`` where ``flat = (a, b, c, d, e, f, g, h, i)``
    yields row 0 = ``(a, b, c)``. The ``(float(v) for v in value)`` pass
    normalises ints / numpy scalars to plain Python floats before USD's
    constructor receives them.
    """
    flat = tuple(float(v) for v in value)
    if n_dim == 2:
        return Gf.Matrix2d(*flat)
    if n_dim == 3:
        return Gf.Matrix3d(*flat)
    return Gf.Matrix4d(*flat)


def _to_python(value: Any, value_type: str) -> Any:
    """Convert USD pxr value to plain Python."""
    if value is None:
        return _default_value(value_type)
    if value_type == "float2":
        return (float(value[0]), float(value[1]))
    if value_type in ("float3", "color3f"):
        return (float(value[0]), float(value[1]), float(value[2]))
    if value_type in ("float4", "color4f"):
        return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    if value_type == "int2":
        return (int(value[0]), int(value[1]))
    if value_type == "int3":
        return (int(value[0]), int(value[1]), int(value[2]))
    if value_type == "int4":
        return (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
    if value_type in _MATRIX_DIMS:
        return _matrix_to_python(value, _MATRIX_DIMS[value_type])
    if value_type == "asset":
        # ``Sdf.AssetPath`` carries both the authored ``path`` and an
        # ArResolver-resolved ``resolvedPath``. The row-level model holds
        # the authored string (so edits roundtrip losslessly); the
        # resolved form is surfaced separately via
        # :meth:`UsdPropertyAdapter.get_resolved_asset_path`.
        return str(value.path) if hasattr(value, "path") else str(value)
    if value_type == "float":
        return float(value)
    if value_type == "int":
        return int(value)
    if value_type == "bool":
        return bool(value)
    if value_type == "str":
        return str(value)
    return value


def _to_usd(value: Any, value_type: str) -> Any:
    """Convert plain Python value to a USD-compatible type."""
    if value_type == "float2":
        return Gf.Vec2f(float(value[0]), float(value[1]))
    if value_type in ("float3", "color3f"):
        return Gf.Vec3f(float(value[0]), float(value[1]), float(value[2]))
    if value_type in ("float4", "color4f"):
        return Gf.Vec4f(float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    if value_type == "int2":
        return Gf.Vec2i(int(value[0]), int(value[1]))
    if value_type == "int3":
        return Gf.Vec3i(int(value[0]), int(value[1]), int(value[2]))
    if value_type == "int4":
        return Gf.Vec4i(int(value[0]), int(value[1]), int(value[2]), int(value[3]))
    if value_type in _MATRIX_DIMS:
        return _matrix_to_usd(value, _MATRIX_DIMS[value_type])
    if value_type == "asset":
        # Wrap the plain string in an ``Sdf.AssetPath`` so USD accepts the
        # write (``attr.Set("foo.usd")`` raises; ``attr.Set(Sdf.AssetPath("foo.usd"))``
        # is the supported call).
        return Sdf.AssetPath(str(value))
    if value_type == "float":
        return float(value)
    if value_type == "int":
        return int(value)
    if value_type == "bool":
        return bool(value)
    return value  # str, token — USD accepts plain str


def _default_value(value_type: str) -> Any:
    if value_type in _MATRIX_IDENTITY:
        return _MATRIX_IDENTITY[value_type]
    return {
        "float": 0.0,
        "int": 0,
        "bool": False,
        "str": "",
        "float2": (0.0, 0.0),
        "float3": (0.0, 0.0, 0.0),
        "float4": (0.0, 0.0, 0.0, 0.0),
        "color3f": (0.0, 0.0, 0.0),
        "color4f": (0.0, 0.0, 0.0, 1.0),
        "int2": (0, 0),
        "int3": (0, 0, 0),
        "int4": (0, 0, 0, 0),
        "asset": "",
        # Step 3.7: unauthored / invalid relationships present as an empty
        # tuple so the row's display formatter yields "" (empty field),
        # matching Kit's ``RelationshipAttributeModel`` behaviour.
        "relationship": (),
        # Step 3.8: unauthored / invalid arrays present as an empty tuple.
        # The row display formatter yields "()" for an empty tuple (never
        # invoked from ``_to_python``, but kept consistent with the
        # relationship entry so downstream code can rely on
        # ``_default_value("array")`` returning a Python container).
        "array": (),
    }.get(value_type)


# ──────────────────────────────────────────────────────────────────────────────
# Undo command
# ──────────────────────────────────────────────────────────────────────────────

class _PropertyEditToken:
    """Per-invocation ownership record for one begin/end edit transaction.

    Freezes everything the transaction may rely on BEFORE any authoring:
    the full ``Usd.EditTarget`` (mapping included), its layer, the MAPPED
    spec paths every member write will land on (computed through the
    frozen target's ``MapToSpecPath`` — identical to the composed paths
    for identity mappings, variant/reference spec paths otherwise), and
    the exact pre-edit snapshot of exactly those specs. ``wrote`` records
    whether THIS invocation actually authored — foreign or invalidation
    changes observed at ``end_edit`` without an owned write never create
    history. ``registry_keys`` are this token's claims in the shared
    cross-adapter spec-ownership registry.
    """

    __slots__ = ("edit_target", "layer", "paths", "spec_paths", "attr_name",
                 "pre", "wrote", "registry_keys", "__weakref__")

    def __init__(self, edit_target, layer, paths, spec_paths, attr_name,
                 pre, registry_keys):
        self.edit_target = edit_target
        self.layer = layer
        self.paths = paths
        self.spec_paths = spec_paths
        self.attr_name = attr_name
        self.pre = pre
        self.wrote = False
        self.registry_keys = registry_keys


# Cross-adapter spec ownership: (layer identifier, spec path) → weak token.
# Two adapters sharing the same stage/layer/property must not overlap one
# logical edit; begin_edit refuses BEFORE any capture or authoring while a
# LIVE token owns any of the mapped specs. Values are weak so an adapter
# discarded mid-edit releases its claims automatically.
_ACTIVE_SPEC_EDITS: Dict[tuple, Any] = {}


def _spec_claim_live(key: tuple) -> bool:
    ref = _ACTIVE_SPEC_EDITS.get(key)
    if ref is None:
        return False
    if ref() is None:
        _ACTIVE_SPEC_EDITS.pop(key, None)
        return False
    return True


def _release_spec_claims(token: "_PropertyEditToken") -> None:
    for key in token.registry_keys:
        ref = _ACTIVE_SPEC_EDITS.get(key)
        if ref is not None and ref() is token:
            _ACTIVE_SPEC_EDITS.pop(key, None)


class SetAttributeCommand(Command):
    """Undo/redo command for a USD attribute value change.

    Anchored on EXACT pre/post property-spec snapshots of the layer the
    edit's FROZEN target mapped to: undo restores the exact prior authored
    opinion — including the ABSENCE of one — and redo replays the exact
    post-edit state, immune to later edit-target changes.

    Every replay invocation is ATOMIC: a fresh compensation baseline of
    the layer's current state is captured first; if the replay fails at
    any point, the baseline is restored and verified before the primary
    failure propagates, so a half-replayed layer can never survive with a
    misleading history cursor.
    """

    def __init__(
        self,
        layer: Any,
        spec_paths: List[Any],
        attr_name: str,
        pre_snapshot: Any,
        post_snapshot: Any,
    ) -> None:
        self._layer = layer
        self._spec_paths = list(spec_paths)
        self._attr_name = attr_name
        self._pre = pre_snapshot
        self._post = post_snapshot
        self.label = f"Set {attr_name}"

    def _fresh_baseline(self) -> Any:
        from ovui_data_adapters.openusd.commands import (
            _TargetedVisibilitySnapshot,
        )

        return _TargetedVisibilitySnapshot(
            self._layer, (), prop_name=self._attr_name,
            prop_spec_paths=self._spec_paths)

    def _replay_atomic(self, snapshot: Any) -> None:
        # Fresh per-invocation compensation baseline: captured BEFORE any
        # mutation, so a failure mid-replay can restore and verify the
        # exact invocation state instead of leaving a half-replayed layer.
        baseline = self._fresh_baseline()
        try:
            snapshot.replay(self._layer)
        except BaseException as primary:  # noqa: BLE001 — compensated
            try:
                baseline.replay(self._layer)
            except BaseException as secondary:  # noqa: BLE001 — noted
                add_note = getattr(primary, "add_note", None)
                if callable(add_note):
                    add_note(
                        "compensation replay also failed; the layer state "
                        "is conservative (genuine notices retained): "
                        f"{type(secondary).__name__}: {secondary}"
                    )
            raise

    def do(self) -> None:
        # push() executes do() while the post state is already current:
        # the verified matches() guard avoids a redundant re-replay (and
        # its notices) without weakening redo, which replays explicitly.
        if not self._post.matches(self._layer):
            self._replay_atomic(self._post)

    def redo(self) -> None:
        self._replay_atomic(self._post)

    def undo(self) -> None:
        self._replay_atomic(self._pre)


# ──────────────────────────────────────────────────────────────────────────────
# Subscription handle
# ──────────────────────────────────────────────────────────────────────────────

class _UsdPropertySubscription:
    def __init__(self, owner: "UsdPropertyAdapter", callback: Callable) -> None:
        self._owner = weakref.ref(owner)
        self._callback = callback

    def cancel(self) -> None:
        owner = self._owner()
        if owner is not None:
            try:
                owner._subscribers.remove(self._callback)
            except ValueError:
                pass

    def __del__(self) -> None:
        self.cancel()


# ──────────────────────────────────────────────────────────────────────────────
# Main adapter
# ──────────────────────────────────────────────────────────────────────────────

class UsdPropertyAdapter(PropertyAdapter):
    """USD-backed PropertyAdapter. Wraps a list of prim paths on a Usd.Stage.

    Enumerates attributes common to ALL selected prims (intersection).
    Pass an UndoManager to make set_value operations undoable via begin/end_edit.
    """

    def __init__(
        self,
        stage: Any,
        paths: List[str],
        undo_manager: Optional[UndoManagerProtocol] = None,
        stage_adapter: Any = None,
    ) -> None:
        self._stage = stage
        self._paths: List[str] = list(paths)
        self._undo_manager = undo_manager
        self._stage_adapter = stage_adapter
        self._props: Dict[str, UsdAttributeProp] = {}
        self._edit_snapshots: Dict[str, Any] = {}
        self._subscribers: List[Callable] = []
        # An undoable namespace mutation (delete/rename/reparent) settles
        # this adapter's in-flight edit transactions before it executes;
        # the registration is weak, so a discarded adapter unregisters
        # itself.
        register = getattr(
            undo_manager, "register_pre_namespace_settler", None)
        if callable(register):
            register(self._settle_active_edits)
        self._refresh()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        """Enumerate attrs common to ALL selected prims (intersection)."""
        self._props = {}
        if not self._paths:
            return

        path_props: List[Dict[str, UsdAttributeProp]] = []
        for path in self._paths:
            prim = self._stage.GetPrimAtPath(path)
            if not prim.IsValid():
                return  # invalid path → empty result
            path_props.append(self._enumerate_attrs(prim))

        if not path_props:
            return

        common_names = set(path_props[0].keys())
        for props in path_props[1:]:
            common_names &= set(props.keys())

        for name in path_props[0]:
            if name in common_names:
                self._props[name] = path_props[0][name]

    def _enumerate_attrs(self, prim: Any) -> Dict[str, UsdAttributeProp]:
        """Enumerate attributes and relationships.

        Step 3.7 extended the walk to include ``prim.GetRelationships()``
        alongside ``prim.GetAttributes()``. Relationships carry no USD type
        token (there is no ``relationship.GetTypeName()`` counterpart to the
        attribute API), so we synthesise ``usd_type_str = "relationship"``
        which the ``WidgetBuilderTable`` registers against.

        Step 3.8 stopped skipping array-typed attributes. USD array type
        strings end in ``"[]"`` (e.g. ``"float[]"``, ``"token[]"``,
        ``"float3[]"``); any ``[]``-suffixed type that ``_map_type`` did not
        resolve to a scalar/vector/matrix tag maps to the ``"array"``
        sentinel. The sentinel is the single key the ``WidgetBuilderTable``
        array builder registers against; the original USD type string is
        preserved on ``UsdAttributeProp.usd_type_str`` for potential
        tooltip/debug use but never reaches dispatch as-is.
        """
        result: Dict[str, UsdAttributeProp] = {}
        for attr in prim.GetAttributes():
            usd_type_str = str(attr.GetTypeName())
            value_type = _map_type(usd_type_str)
            if value_type is None:
                if usd_type_str.endswith("[]"):
                    value_type = "array"
                else:
                    continue  # truly unsupported — skip silently
            name = attr.GetName()
            result[name] = UsdAttributeProp(
                attr_name=name,
                display_name=_get_display_name(name),
                group_name=_get_group_path(attr, name),
                value_type=value_type,
                usd_type_str=usd_type_str,
            )
        for rel in prim.GetRelationships():
            name = rel.GetName()
            result[name] = UsdAttributeProp(
                attr_name=name,
                display_name=_get_display_name(name),
                group_name=_get_group_path(rel, name),
                value_type="relationship",
                usd_type_str="relationship",
            )
        return result

    def _notify(self) -> None:
        for cb in list(self._subscribers):
            cb()

    # ── PropertyAdapter ABC ───────────────────────────────────────────────────

    def get_paths(self) -> List[str]:
        return list(self._paths)

    def is_valid(self) -> bool:
        if not self._paths:
            return False
        for path in self._paths:
            prim = self._stage.GetPrimAtPath(path)
            if not prim.IsValid():
                return False
        return True

    def get_attribute_names(self) -> List[str]:
        return list(self._props.keys())

    def get_attribute_metadata(self, attr_name: str) -> AttributeMetadata:
        prop = self._props[attr_name]
        python_type = _VALUE_TYPE_TO_PYTHON.get(prop.value_type, prop.value_type)
        allowed_values: Optional[List[Any]] = None
        # USD ``token`` attributes may carry ``allowedTokens`` metadata
        # restricting the authored value to a fixed set (e.g.
        # ``visibility ∈ {"inherited", "invisible"}``). Step 3.3 surfaces
        # this via ``AttributeMetadata.allowed_values`` so the token
        # builder can render a ``ui.ComboBox`` instead of a plain
        # ``StringField`` (property attribute builder behavior).
        if prop.usd_type_str.lower() == "token" and self._paths:
            prim = self._stage.GetPrimAtPath(self._paths[0])
            if prim.IsValid():
                attr = prim.GetAttribute(attr_name)
                if attr.IsValid():
                    tokens = attr.GetMetadata("allowedTokens")
                    if tokens:
                        allowed_values = [str(t) for t in tokens]
        # Step 3.8: arrays dispatch through the single ``"array"`` sentinel
        # regardless of element type (``float[]``, ``int[]``, ``float3[]``,
        # …). ``is_big_array`` is computed from the authored length on the
        # first selected prim — the display logic needs the "small tuple"
        # vs "N items" decision before any widget is built, not at paint
        # time. An array that's absent / unauthored counts as small
        # (length 0), matching Kit's ``elide_big_array`` behaviour.
        is_big_array = False
        type_name = prop.usd_type_str
        if prop.value_type == "array":
            type_name = "array"
            if self._paths:
                prim = self._stage.GetPrimAtPath(self._paths[0])
                if prim.IsValid():
                    attr = prim.GetAttribute(attr_name)
                    if attr.IsValid():
                        val = attr.Get()
                        if val is not None and hasattr(val, "__len__"):
                            is_big_array = len(val) > _BIG_ARRAY_THRESHOLD
        # Step 4.1: surface soft/hard range metadata from USD ``customData``.
        # Kit's convention
        # stashes drag bounds in ``customData`` under two keys:
        #
        #   * ``customData["range"]`` → hard clamp (``{"min": x, "max": y}``)
        #   * ``customData["soft_range"]`` → soft drag bounds
        #
        # When ``soft_range`` is absent, the hard range doubles as the soft
        # range so the drag handle still respects the bound (otherwise a
        # zero-to-one roughness slider would scroll unbounded until the
        # model clamp bit on release). Either key may be partial
        # (``{"min": 0}`` with no max) — missing keys stay ``None`` on the
        # metadata so the downstream kwargs helper omits the corresponding
        # widget arg.
        #
        # Step 4.2: the same customData fetch also surfaces the three
        # read-only state flags (property metadata behavior, the property inspector behavior):
        #
        #   * ``is_time_sampled = attr.GetNumTimeSamples() > 0`` — the
        #     attribute is animated (even one sample qualifies); a scalar
        #     write would overwrite the whole curve.
        #   * ``is_locked = bool(customData["locked"])`` — Kit's custom-
        #     metadata convention (there's no first-class USD lock API
        #     outside ``omni.kit.usd.layers`` which this adapter doesn't
        #     depend on; property metadata behavior defaults the flag to False so
        #     the boolean-cast fallback keeps the contract stable).
        #   * ``is_authored = attr.HasAuthoredValue()`` — there is an
        #     explicit authored *value* opinion. Using ``IsAuthored()``
        #     was subtly wrong: ``Usd.Attribute.Clear()`` removes the
        #     value but leaves the attribute spec on the edit-target
        #     layer (typeName / custom / variability fields persist).
        #     ``IsAuthored()`` reports True when any spec exists, so the
        #     NotDefault indicator would never clear after a user reset
        #     (BUG-D004). ``HasAuthoredValue()`` ignores the spec
        #     scaffolding and only reports True when a value opinion is
        #     on the stack — which is exactly what the indicator
        #     predicate needs.
        #
        # Relationships fall through to the defaults (False/False/True)
        # since they aren't selectable for range/lock/time-sample state in
        # the same sense — the existing ``prop.value_type != "relationship"``
        # early skip keeps the read inside the attribute path.
        soft_min = soft_max = hard_min = hard_max = None
        is_time_sampled = False
        is_locked = False
        is_authored = True
        if prop.value_type != "relationship" and self._paths:
            prim = self._stage.GetPrimAtPath(self._paths[0])
            if prim.IsValid():
                attr = prim.GetAttribute(attr_name)
                if attr.IsValid():
                    custom = attr.GetCustomData() or {}
                    hard = custom.get("range") or {}
                    soft = custom.get("soft_range") or hard
                    hard_min = _range_bound(hard, "min")
                    hard_max = _range_bound(hard, "max")
                    soft_min = _range_bound(soft, "min")
                    soft_max = _range_bound(soft, "max")
                    is_time_sampled = attr.GetNumTimeSamples() > 0
                    is_locked = bool(custom.get("locked"))
                    is_authored = attr.HasAuthoredValue()
        return AttributeMetadata(
            name=attr_name,
            display_name=prop.display_name,
            type_name=type_name,
            value_type=python_type,
            group=prop.group_name,
            allowed_values=allowed_values,
            is_big_array=is_big_array,
            soft_range_min=soft_min,
            soft_range_max=soft_max,
            hard_range_min=hard_min,
            hard_range_max=hard_max,
            is_time_sampled=is_time_sampled,
            is_locked=is_locked,
            is_authored=is_authored,
        )

    def get_value(self, attr_name: str) -> Any:
        prop = self._props[attr_name]
        prim = self._stage.GetPrimAtPath(self._paths[0])
        # The owning UsdPropertyAdapter outlives the prim it was built
        # for in two scenarios:
        #   - The user deleted the selected prim (``DeletePrimCommand``);
        #     the adapter's stage-change callback fires before the
        #     PropertyWindow's deferred rebuild swaps in a new adapter
        #     for the cleared selection.
        #   - The user reparented the prim mid-drag.
        # In either case the cached ``self._paths[0]`` no longer
        # resolves, so ``prim.GetAttribute`` raises
        # ``RuntimeError: Accessed invalid null prim`` from the
        # ``call_later`` notice flush. Returning the property's documented
        # "no authored value" sentinel here keeps the per-frame
        # AttributeModel rebuild quiet and matches the
        # PropertyWindow.set_property_adapter_factory empty-panel
        # contract — the Property panel is about to be rebuilt or
        # cleared anyway.
        if not prim.IsValid():
            return _default_value(prop.value_type)
        if prop.value_type == "relationship":
            # Step 3.7: relationships live on a separate USD API.
            # ``GetTargets()`` returns a ``List[Sdf.Path]``; stringify each
            # path so the row's display code (and tests) never see a pxr
            # object leak through the adapter boundary.
            rel = prim.GetRelationship(attr_name)
            if not rel.IsValid():
                return ()
            return tuple(str(t) for t in rel.GetTargets())
        if prop.value_type == "array":
            # Step 3.8: small arrays are surfaced as plain Python tuples so
            # the row's ``_format_array_value`` can ``str(tuple(x))`` the
            # contents cheaply. Big arrays (> ``_BIG_ARRAY_THRESHOLD``) are
            # returned as the raw ``Vt.*Array`` — VtArrays expose an O(1)
            # ``__len__`` which is all the big-array formatter needs
            # (``f"[{len(value)} items]"``). Materialising a 100K-element
            # array into a Python tuple of Gf.Vec3f wrappers for a single
            # selection click allocates ~30 MB and stalls the frame loop
            # for several seconds — BUG-D003. Unauthored / invalid arrays
            # still land as ``()`` (same as ``_default_value("array")``).
            attr = prim.GetAttribute(attr_name)
            if not attr.IsValid():
                return ()
            val = attr.Get()
            if val is None:
                return ()
            # ``hasattr(val, "__len__")`` is defensive — every Vt.*Array
            # exposes it but a third-party adapter subclass could stub
            # ``attr.Get()`` with a value that doesn't. Fall back to the
            # tuple path in that case.
            if hasattr(val, "__len__") and len(val) > _BIG_ARRAY_THRESHOLD:
                return val
            return tuple(val)
        attr = prim.GetAttribute(attr_name)
        return _to_python(attr.Get(), prop.value_type)

    def is_ambiguous(self, attr_name: str) -> bool:
        return False

    def get_per_component_ambiguity(self, attr_name: str) -> Optional[List[bool]]:
        """Per-channel ambiguity for vector attributes; ``None`` for scalars.

        Iterates selected prims, reads each prim's value for ``attr_name``,
        and compares per-index with exact equality. Returns a list of
        booleans where ``True`` marks channels that differ across prims.
        Returns ``None`` for scalar attributes and unknown attributes.
        See property metadata behavior.
        """
        prop = self._props.get(attr_name)
        if prop is None or prop.value_type not in _VECTOR_VALUE_TYPES:
            return None
        values: List[Any] = []
        for path in self._paths:
            prim = self._stage.GetPrimAtPath(path)
            if not prim.IsValid():
                continue
            attr = prim.GetAttribute(attr_name)
            if not attr.IsValid():
                continue
            values.append(_to_python(attr.Get(), prop.value_type))
        if not values:
            return None
        first = values[0]
        return [
            any(v[i] != first[i] for v in values[1:])
            for i in range(len(first))
        ]

    def begin_edit(self, attr_name: str) -> None:
        # STRUCTURED per-invocation ownership: refuse a nested edit of the
        # same attribute BEFORE any capture or authoring — the refusal
        # leaves the first invocation's token, snapshot, and pending
        # authoring completely intact.
        if attr_name in self._edit_snapshots:
            raise RuntimeError(
                f"nested edit of {attr_name!r} refused: an edit "
                "transaction for this attribute is already active"
            )
        from ovui_data_adapters.openusd.commands import (
            _TargetedVisibilitySnapshot,
        )

        # The MAPPED spec paths are frozen BEFORE authoring: every member
        # write lands on edit_target.MapToSpecPath(composed property), so
        # identity mappings capture the composed paths and direct
        # variants/references/offsets capture the exact mapped specs.
        # The snapshot therefore owns exactly this edit's specs — never
        # the whole layer, so foreign concurrent content in the same
        # layer is never owned. An UNCERTAIN mapping (empty mapped path)
        # refuses before any authoring can become untracked.
        edit_target = self._stage.GetEditTarget()
        layer = edit_target.GetLayer()
        spec_paths = []
        for path in self._paths:
            composed = Sdf.Path(str(path)).AppendProperty(attr_name)
            mapped = edit_target.MapToSpecPath(composed)
            if mapped.isEmpty:
                raise RuntimeError(
                    f"edit of {attr_name!r} refused: the current edit "
                    f"target cannot map {composed} to a layer spec path "
                    "(uncertain mapping)"
                )
            spec_paths.append(mapped)
        # SHARED ownership: refuse overlap with any LIVE transaction on
        # the same (layer, spec) — including one owned by a different
        # adapter instance on the same stage and UndoManager — before
        # any mutation, so overlapping edits can never entangle history.
        registry_keys = [
            (str(layer.identifier), str(spec)) for spec in spec_paths
        ]
        for key in registry_keys:
            if _spec_claim_live(key):
                raise RuntimeError(
                    f"overlapping edit refused: {key[1]} in {key[0]} is "
                    "owned by another active edit transaction"
                )
        pre = _TargetedVisibilitySnapshot(
            layer, (), prop_name=attr_name, prop_spec_paths=spec_paths)
        # NOTE: no undo group is opened. The transaction pushes exactly
        # one command at end_edit; an open group would swallow FOREIGN
        # commands (e.g. a deletion arriving mid-edit) into this edit's
        # history entry and made unmatched end_edit close foreign groups.
        token = _PropertyEditToken(
            edit_target, layer, list(self._paths), spec_paths, attr_name,
            pre, registry_keys)
        for key in registry_keys:
            _ACTIVE_SPEC_EDITS[key] = weakref.ref(token)
        self._edit_snapshots[attr_name] = token

    def set_value(self, attr_name: str, value: Any) -> None:
        prop = self._props[attr_name]
        if prop.value_type == "relationship":
            # Step 3.7: relationships are read-only at the Property
            # Inspector level. A target picker (§9.8
            # ``RelationshipTargetPicker``) lands in a later phase; until
            # then, ``set_value`` is a defensive no-op so a stray row
            # edit cannot corrupt the stage.
            return
        if prop.value_type == "array":
            # Step 3.8: arrays are read-only at the Property Inspector
            # level — the row only renders a read-only string. A dedicated
            # array editor (e.g. Kit's ``SdfAssetPathDelegate`` TreeView)
            # lands in a later phase; until then, ``set_value`` is a
            # defensive no-op. Prevents a stray programmatic write from
            # attempting a ``Python tuple → Vt.*Array`` conversion that
            # would raise mid-edit.
            return
        usd_val = _to_usd(value, prop.value_type)
        token = self._edit_snapshots.get(attr_name)

        if isinstance(token, _PropertyEditToken):
            # Author EVERY member against the FROZEN edit target. A
            # genuine synchronous notice callback fired by one member's
            # Set() may change the stage target before the next member,
            # so the frozen target is re-asserted PER MEMBER — one
            # transaction can never split across layers. A foreign
            # mid-write target change is preserved: the previous target
            # is restored only when the current one is still ours.
            # ``wrote`` is marked BEFORE the attempt so even a write that
            # throws mid-way stays owned — end_edit/cancel_edit then
            # restore or record the exact truth instead of ignoring
            # partial authorship.
            token.wrote = True
            for path in self._paths:
                prim = self._stage.GetPrimAtPath(path)
                if not prim.IsValid():
                    continue
                attr = prim.GetAttribute(attr_name)
                if not attr.IsValid():
                    continue
                previous_target = self._stage.GetEditTarget()
                self._stage.SetEditTarget(token.edit_target)
                try:
                    attr.Set(usd_val)
                finally:
                    if self._stage.GetEditTarget() == token.edit_target:
                        self._stage.SetEditTarget(previous_target)
        else:
            for path in self._paths:
                prim = self._stage.GetPrimAtPath(path)
                if prim.IsValid():
                    attr = prim.GetAttribute(attr_name)
                    if attr.IsValid():
                        attr.Set(usd_val)
        self._notify()

    def end_edit(self, attr_name: str) -> None:
        from ovui_data_adapters.openusd.commands import (
            _TargetedVisibilitySnapshot,
        )

        token = self._edit_snapshots.pop(attr_name, None)
        if not isinstance(token, _PropertyEditToken):
            # Unmatched end: inert by contract — it owns nothing and may
            # not close a foreign group or touch any state.
            return
        _release_spec_claims(token)
        if not token.wrote:
            # This invocation authored nothing: whatever changed (foreign
            # concurrent edits, a deletion, nothing at all) is not this
            # transaction's to record.
            return
        if any(
            not self._stage.GetPrimAtPath(path).IsValid()
            for path in token.paths
        ):
            # A prim this edit wrote to was invalidated/deleted by a
            # NON-undoable out-of-band mutation before the transaction
            # closed (undoable namespace commands settle this edit FIRST
            # through the UndoManager's pre-namespace settlers, so they
            # never reach this guard): the foreign resync owns the truth
            # now, and recording or "restoring" over it would fabricate
            # history for a foreign change.
            return
        try:
            # "Changed" is decided from the FROZEN TARGET's truth, not the
            # resolved value: an edit shadowed by a stronger layer still
            # authored real state and must stay undoable, while a
            # same-value commit that left the layer untouched is a genuine
            # no-op and never pollutes history.
            if token.pre.matches(token.layer):
                return
            post = _TargetedVisibilitySnapshot(
                token.layer, (), prop_name=attr_name,
                prop_spec_paths=token.spec_paths)
            if self._undo_manager:
                self._undo_manager.push(SetAttributeCommand(
                    token.layer, token.spec_paths, attr_name,
                    token.pre, post))
        except BaseException as primary:  # noqa: BLE001 — compensated
            # STRUCTURED cancellation: a failure after authoring (post
            # capture, push, replay verification) must not leave authored
            # state with no history entry. Restore and verify the exact
            # invocation baseline; the primary throwable stays primary.
            try:
                token.pre.replay(token.layer)
            except BaseException as secondary:  # noqa: BLE001 — noted
                add_note = getattr(primary, "add_note", None)
                if callable(add_note):
                    add_note(
                        "baseline restoration also failed; layer state is "
                        "conservative (genuine notices retained): "
                        f"{type(secondary).__name__}: {secondary}"
                    )
            raise

    def cancel_edit(self, attr_name: str) -> None:
        """Cancel an active edit transaction, restoring its exact baseline.

        Called by the owning model when the buffered write (or any step
        between ``begin_edit`` and ``end_edit``) raises: any partial
        authorship this invocation performed is removed by replaying the
        pre-edit snapshot (verified), no history entry is created, and the
        token is released. Safe (inert) without an active transaction.
        """
        token = self._edit_snapshots.pop(attr_name, None)
        if not isinstance(token, _PropertyEditToken):
            return
        _release_spec_claims(token)
        if token.wrote and all(
            self._stage.GetPrimAtPath(path).IsValid()
            for path in token.paths
        ):
            # Restore the exact pre-edit specs. Skipped when a target
            # prim was genuinely deleted out-of-band: replaying would
            # RESURRECT spec shells for a prim the foreign mutation
            # removed.
            token.pre.replay(token.layer)

    def _settle_active_edits(self) -> None:
        """Finalize or cancel every active edit transaction NOW.

        Registered with the UndoManager as a pre-namespace settler: an
        undoable namespace mutation (prim deletion, rename, reparent)
        settles in-flight edits first, so every surviving owned write
        gets its truthful history entry BEFORE the namespace changes and
        no foreign namespace command is ever entangled with an active
        edit. Edits that never wrote are cancelled without residue.
        """
        for attr_name in list(self._edit_snapshots):
            token = self._edit_snapshots.get(attr_name)
            if isinstance(token, _PropertyEditToken) and token.wrote:
                self.end_edit(attr_name)
            else:
                self.cancel_edit(attr_name)

    def subscribe_changes(self, callback: Callable) -> Any:
        # PropertyAdapter's subscribe_changes contract takes a no-arg
        # callable; StageAdapter's contract takes a ChangeEvent argument.
        # When we delegate to a stage adapter we must drop the event so
        # AttributeModelBase._on_backing_changed (no-arg) doesn't raise
        # TypeError mid-flush and wedge every property row's refresh.
        if self._stage_adapter is not None:
            return self._stage_adapter.subscribe_changes(
                lambda _event=None: callback()
            )
        self._subscribers.append(callback)
        return _UsdPropertySubscription(self, callback)

    def get_scheme(self) -> str:
        return "usd"

    def get_capabilities(self) -> PropertyCapabilities:
        return _OPENUSD_PROPERTY_CAPABILITIES

    def clear_value(self, attr_name: str) -> None:
        """Remove the authored opinion for ``attr_name`` on every selected prim.

        Step 4.3 of the property inspector implementation. USD's
        :meth:`pxr.Usd.Attribute.Clear` removes the opinion in the
        current edit target layer; the attribute then reports the
        schema default (or the next-strongest-layer opinion if one
        exists). Safe on unauthored or missing attributes — the USD
        API is a no-op in that case.

        Skipped for relationship and array types: relationships use
        :meth:`pxr.Usd.Relationship.ClearTargets` (not wired yet —
        Phase 6/7) and array edits aren't user-driven in this panel,
        so there's no reset-to-default button to fire the click. The
        :class:`ControlStateIndicator` hides the NotDefault icon on
        those rows because ``on_click`` is unset at handler-register
        time.

        Notifies subscribers after the clear so the panel and any
        listening models refresh the display — matches the
        :meth:`set_value` post-write hook (``self._notify()``).
        """
        prop = self._props.get(attr_name)
        if prop is None or prop.value_type in ("relationship", "array"):
            return
        for path in self._paths:
            prim = self._stage.GetPrimAtPath(path)
            if not prim.IsValid():
                continue
            attr = prim.GetAttribute(attr_name)
            if attr.IsValid():
                attr.Clear()
        self._notify()

    def get_resolved_asset_path(self, attr_name: str) -> Optional[str]:
        """Return USD's ArResolver-resolved path for ``attr_name``, or ``None``.

        Reads the raw ``Sdf.AssetPath`` value off the underlying attribute
        and returns its ``resolvedPath``. An empty resolved path (e.g.
        authored as a dangling reference the resolver can't locate) also
        returns ``None`` — matches Kit's
        :class:`SdfAssetPathAttributeModel` behaviour where no tooltip is
        shown when resolution failed.

        Step 3.6 of the property inspector implementation (property metadata behavior). Non-asset attributes
        fall through to the ``None`` branch; we never raise.
        """
        prop = self._props.get(attr_name)
        if prop is None or prop.value_type != "asset":
            return None
        if not self._paths:
            return None
        prim = self._stage.GetPrimAtPath(self._paths[0])
        if not prim.IsValid():
            return None
        attr = prim.GetAttribute(attr_name)
        if not attr.IsValid():
            return None
        raw = attr.Get()
        if raw is None:
            return None
        resolved = getattr(raw, "resolvedPath", None)
        if resolved is None or resolved == "":
            return None
        return str(resolved)
