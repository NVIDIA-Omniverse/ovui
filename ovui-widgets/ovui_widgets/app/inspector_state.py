# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Read-only USD Viewer state captured by the ovui Inspector.

The Inspector uses this module only after a real mouse or keyboard action.  It
does not offer mutation helpers.  The snapshot deliberately records the
independent views that exist for the selected provider:

* the active provider's scene state — native OVStage topology at its
  committed ordinal for the ``ovstage`` provider, or the provider-owned
  ``pxr.Usd.Stage`` when the OpenUSD provider is selected (the ``usd``
  section carries data only in that case); and
* the provider-neutral Stage adapter hierarchy and UI views shown by the
  widgets.

Keeping the available views in one JSON-safe artifact lets automated QA prove
that a visible UI operation reached the provider's scene state rather than
merely changing a widget model.
"""

from __future__ import annotations

import hashlib
import struct
from itertools import islice
from pathlib import Path
from typing import Any, Iterable

_MAX_SEQUENCE_ITEMS = 128
_MAX_VIEWPORT_PROJECTION_PATHS = 256
_FILE_HASH_CHUNK_SIZE = 1024 * 1024
_CONDITIONAL_RUNTIME_ROOTS = (
    "/TempChangeTracking",
    "/omni_rtx_loadingStatePrim",
    "/Render",
)
_NATIVE_MATRIX_ATTRIBUTES = {
    "localMatrix",
    "worldMatrix",
    "xformOp:transform",
}
_NATIVE_TOKEN_ATTRIBUTES = {
    "visibility",
    "worldVisibility",
    "purpose",
    "orientation",
    "projection",
    "usd-prim-type",
}
_NATIVE_SCALAR_ATTRIBUTES = {
    "size",
    "radius",
    "height",
    "focalLength",
    "horizontalAperture",
    "verticalAperture",
    "intensity",
    "exposure",
}
_OVSTAGE_01_UNREADABLE_MATERIAL_OUTPUT_CONNECTIONS = frozenset(
    {
        "outputs:surface",
        "outputs:displacement",
        "outputs:volume",
    }
)
_OVSTAGE_01_MATERIAL_OUTPUT_CONNECTION_REASON = (
    "OVStage 0.1 public query/read filters Fabric NameSuffix::connection "
    "columns, so neither the material output base name nor its .connect form "
    "produces a native read group"
)


def _safe_call(default: Any, function, *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except Exception:
        return default


def _enum_value(value: Any) -> Any:
    enum_value = getattr(value, "value", None)
    return enum_value if enum_value is not None else value


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        length = len(value)
        if length > _MAX_SEQUENCE_ITEMS:
            sample = list(islice(iter(value), 8))
            encoded = repr(sample).encode("utf-8", errors="replace")
            return {
                "length": length,
                "sample": [_json_value(item) for item in sample],
                "sample_sha256": hashlib.sha256(encoded).hexdigest(),
                "truncated": True,
            }
        return [_json_value(item) for item in value]
    if hasattr(value, "__iter__") and not isinstance(value, (bytes, bytearray)):
        try:
            length = len(value) if hasattr(value, "__len__") else None
            if length is not None and length > _MAX_SEQUENCE_ITEMS:
                sample = list(islice(iter(value), 8))
                return {
                    "length": int(length),
                    "sample": [_json_value(item) for item in sample],
                    "truncated": True,
                }
            sequence = list(islice(iter(value), _MAX_SEQUENCE_ITEMS + 1))
            if len(sequence) > _MAX_SEQUENCE_ITEMS:
                return {
                    "length_at_least": len(sequence),
                    "sample": [
                        _json_value(item)
                        for item in sequence[:8]
                    ],
                    "truncated": True,
                }
            return _json_value(sequence)
        except Exception:
            pass
    converted = _enum_value(value)
    if converted is not value:
        return _json_value(converted)
    return repr(value)


def _numeric_value_fingerprint(value: Any) -> dict[str, Any] | None:
    """Return a complete dtype/shape/hash record for numeric USD values."""

    try:
        import numpy as np

        array = np.asarray(value)
    except Exception:
        return None
    if array.dtype.kind not in {"b", "i", "u", "f"}:
        return None
    try:
        contiguous = np.ascontiguousarray(array)
        payload = contiguous.tobytes(order="C")
    except Exception:
        return None
    return {
        "dtype": str(contiguous.dtype),
        "shape": [int(size) for size in contiguous.shape],
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "complete": True,
    }


def _matrix_values(matrix: Any) -> list[list[float]] | None:
    if matrix is None:
        return None
    if isinstance(matrix, tuple) and len(matrix) == 2:
        candidate = matrix[0]
        try:
            if len(candidate) == 4:
                matrix = candidate
        except Exception:
            pass
    try:
        rows = [[float(value) for value in row] for row in matrix]
    except Exception:
        return None
    if len(rows) != 4 or any(len(row) != 4 for row in rows):
        return None
    return rows


def _flatten_matrix(matrix: list[list[float]] | None) -> tuple[float, ...]:
    if matrix is None:
        return ()
    return tuple(value for row in matrix for value in row)


def _matrix_close(
    left: list[list[float]] | None,
    right: list[list[float]] | None,
    *,
    tolerance: float = 1.0e-5,
) -> bool:
    left_values = _flatten_matrix(left)
    right_values = _flatten_matrix(right)
    return (
        len(left_values) == 16
        and len(right_values) == 16
        and all(abs(a - b) <= tolerance for a, b in zip(left_values, right_values))
    )


def _values_close(left: Any, right: Any, *, tolerance: float = 1.0e-4) -> bool:
    """Compare decoded USD/native values without hiding numeric drift.

    OVStage exposes a deliberately small decoded subset of its native byte
    attributes.  Values in that subset can be compared independently with the
    exact backing USD stage.  Float32 native values need a slightly wider
    tolerance than the matrix path, while tokens and structure remain exact.
    """

    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= tolerance
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            _values_close(a, b, tolerance=tolerance)
            for a, b in zip(left, right)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _values_close(left[key], right[key], tolerance=tolerance)
            for key in left
        )
    return left == right


def _selection_snapshot(app: Any) -> dict[str, Any]:
    bus = getattr(app, "_selection_bus", None)
    snapshot = _safe_call(None, bus.get_snapshot) if bus is not None else None
    items = tuple(getattr(snapshot, "items", ()) or ())
    bus_paths = [str(getattr(item, "path", "")) for item in items]
    stage_window = getattr(app, "_stage_window", None)
    stage_widget = getattr(stage_window, "_widget", None)
    stage_paths = list(_safe_call([], stage_widget.get_selection) or []) if stage_widget else []
    property_window = getattr(app, "_property_window", None)
    property_paths = list(getattr(property_window, "_selection", ()) or ())
    viewport = getattr(app, "_viewport_window", None)
    renderer = getattr(viewport, "_renderer", None)
    transform_model = getattr(viewport, "_transform_model", None)
    renderer_pick = str(getattr(renderer, "_last_pick_path", "") or "")
    return {
        "paths": bus_paths,
        "sources": [str(getattr(item, "source", "")) for item in items],
        "stage_paths": [str(path) for path in stage_paths],
        "property_paths": [str(path) for path in property_paths],
        "renderer_last_pick": renderer_pick,
        "renderer_highlight_paths": [
            str(path) for path in (getattr(renderer, "_selected_paths", ()) or ())
        ],
        "viewport_raw_paths": [
            str(path)
            for path in (getattr(transform_model, "_raw_selected_paths", ()) or ())
        ],
        "viewport_transformable_paths": [
            str(path)
            for path in (getattr(transform_model, "_selected_paths", ()) or ())
        ],
        "stage_matches_bus": [str(path) for path in stage_paths] == bus_paths,
        "property_matches_bus": [str(path) for path in property_paths] == bus_paths,
    }


def _undo_snapshot(app: Any) -> dict[str, Any]:
    manager = getattr(app, "_undo_manager", None)
    if manager is None:
        return {"can_undo": False, "can_redo": False}
    undo_stack = list(getattr(manager, "_undo_stack", ()) or ())
    redo_stack = list(getattr(manager, "_redo_stack", ()) or ())
    group_stack = list(getattr(manager, "_group_stack", ()) or ())
    return {
        "can_undo": bool(_safe_call(False, manager.can_undo)),
        "can_redo": bool(_safe_call(False, manager.can_redo)),
        "undo_depth": len(undo_stack),
        "redo_depth": len(redo_stack),
        "group_depth": len(group_stack),
        "undo_label": str(getattr(undo_stack[-1], "label", "")) if undo_stack else "",
        "redo_label": str(getattr(redo_stack[-1], "label", "")) if redo_stack else "",
        "stage_adapter_uses_app_manager": (
            getattr(getattr(app, "_stage_adapter", None), "_undo_manager", None)
            is manager
        ),
    }


def _status_snapshot(app: Any) -> dict[str, Any]:
    bar = getattr(app, "_status_bar", None)
    label = getattr(bar, "_label", None)
    return {
        "available": label is not None,
        "text": str(getattr(label, "text", "") or ""),
        "level": str(getattr(label, "name", "") or ""),
        "rect": _widget_rect(label),
    }


def _widget_rect(widget: Any) -> dict[str, float] | None:
    if widget is None:
        return None
    try:
        return {
            "x": float(getattr(widget, "screen_position_x", 0.0) or 0.0),
            "y": float(getattr(widget, "screen_position_y", 0.0) or 0.0),
            "width": float(getattr(widget, "computed_width", 0.0) or 0.0),
            "height": float(getattr(widget, "computed_height", 0.0) or 0.0),
        }
    except (TypeError, ValueError):
        return None


def _rect_point(rect: dict[str, float] | None) -> list[int] | None:
    if (
        rect is None
        or float(rect.get("width", 0.0)) <= 0.0
        or float(rect.get("height", 0.0)) <= 0.0
    ):
        return None
    return [
        int(round(float(rect["x"]) + float(rect["width"]) * 0.5)),
        int(round(float(rect["y"]) + float(rect["height"]) * 0.5)),
    ]


def _stage_ui_snapshot(app: Any) -> dict[str, Any]:
    """Return read-only Stage Browser hit geometry for Inspector input.

    The coordinates are an observation oracle, not an action surface. Tests
    still drive ordinary screenshot-space mouse and keyboard input.
    """

    stage_window = getattr(app, "_stage_window", None)
    widget = getattr(stage_window, "_widget", None)
    model = getattr(widget, "_model", None)
    adapter = getattr(widget, "_adapter", None)
    frame = getattr(widget, "_scrolling_frame", None)
    if widget is None or model is None or adapter is None or frame is None:
        return {"available": False, "rows": []}

    try:
        from omni import ui

        dpi_scale = float(ui.Workspace.get_dpi_scale())
    except Exception:
        dpi_scale = 1.0
    if dpi_scale <= 0.0:
        dpi_scale = 1.0

    snapshot_expansion = getattr(model, "_snapshot_expansion_from_tree", None)
    if callable(snapshot_expansion):
        _safe_call(None, snapshot_expansion)
    expanded_paths = set(getattr(model, "_expanded_paths", ()) or ())
    selected_items = list(getattr(model, "_selected_items", ()) or ())
    selected_paths = {
        str(_safe_call("", adapter.get_item_path, item.adapter_item))
        for item in selected_items
    }

    visible: list[tuple[str, int]] = []

    def walk(parent: Any, depth: int) -> None:
        for child in _safe_call([], model.get_item_children, parent) or []:
            path = str(_safe_call("", adapter.get_item_path, child.adapter_item))
            if not path:
                continue
            visible.append((path, depth))
            if path in expanded_paths:
                walk(child, depth + 1)

    walk(None, 0)
    frame_rect = _widget_rect(frame) or {
        "x": 0.0,
        "y": 0.0,
        "width": 0.0,
        "height": 0.0,
    }
    try:
        scroll_y = float(getattr(frame, "scroll_y", 0.0) or 0.0)
    except (TypeError, ValueError):
        scroll_y = 0.0
    row_height = 18.0
    type_width = 50.0
    visibility_width = 32.0
    eye_size = 14.0
    rows: list[dict[str, Any]] = []
    for index, (path, depth) in enumerate(visible):
        adapter_item = _safe_call(None, adapter.get_item_at_path, path)
        badge_flags = int(
            _enum_value(_safe_call(0, adapter.get_badge_flags, adapter_item)) or 0
        )
        item_flags = int(
            _enum_value(_safe_call(0, adapter.get_item_flags, adapter_item)) or 0
        )
        row_y = frame_rect["y"] + index * row_height - scroll_y
        row_rect = {
            "x": frame_rect["x"],
            "y": row_y,
            "width": frame_rect["width"],
            "height": row_height,
        }
        right = frame_rect["x"] + frame_rect["width"]
        rows.append(
            {
                "path": path,
                "index": index,
                "depth": depth,
                "display_name": str(
                    _safe_call("", adapter.get_display_name, adapter_item)
                ),
                "type_name": str(_safe_call("", adapter.get_type_name, adapter_item)),
                "badge_flags": badge_flags,
                "item_flags": item_flags,
                "selected": path in selected_paths,
                "expanded": path in expanded_paths,
                "visible_in_viewport": (
                    row_y + row_height > frame_rect["y"]
                    and row_y < frame_rect["y"] + frame_rect["height"]
                ),
                "rect": row_rect,
                "select_point": [
                    int(round(right - visibility_width - type_width * 0.5)),
                    int(round(row_y + row_height * 0.5)),
                ],
                "name_point": [
                    int(round(frame_rect["x"] + 34.0 + depth * 14.0)),
                    int(round(row_y + row_height * 0.5)),
                ],
                "eye_rect": {
                    "x": right - visibility_width - 4.0,
                    "y": row_y + (row_height - eye_size) * 0.5,
                    "width": eye_size,
                    "height": eye_size,
                },
                "chevron_point": [
                    int(round(frame_rect["x"] + depth * 14.0 + 7.0)),
                    int(round(row_y + row_height * 0.5)),
                ],
            }
        )

    filter_field = getattr(widget, "_filter_field", None)
    filter_model = getattr(filter_field, "model", None)
    filter_text = (
        str(_safe_call("", filter_model.get_value_as_string))
        if filter_model is not None
        else ""
    )
    rename_controller = getattr(widget, "_rename_controller", None)
    active_item = getattr(rename_controller, "_active_item", None)
    pending_item = getattr(rename_controller, "_pending_item", None)
    rename_field = (
        getattr(getattr(widget, "_delegate", None), "_rename_fields", {}).get(
            active_item
        )
        if active_item is not None
        else None
    )

    def item_path(item: Any) -> str:
        if item is None:
            return ""
        return str(_safe_call("", adapter.get_item_path, item.adapter_item))

    filter_rect = _widget_rect(getattr(widget, "_filter_border_rect", None))
    clear_rect = _widget_rect(getattr(widget, "_filter_clear_button", None))
    if (
        filter_rect is not None
        and (clear_rect is None or clear_rect["width"] <= 0 or clear_rect["height"] <= 0)
    ):
        clear_rect = {
            "x": filter_rect["x"] + max(filter_rect["width"] - 26.0, 0.0),
            "y": filter_rect["y"] + max((filter_rect["height"] - 12.0) * 0.5, 0.0),
            "width": 12.0,
            "height": 12.0,
        }

    return {
        "available": True,
        "dpi_scale": dpi_scale,
        "filter_text": filter_text,
        "filter_focused": str(getattr(getattr(widget, "_filter_border_rect", None), "name", ""))
        == "focused",
        "filter_rect": filter_rect,
        "filter_clear_rect": clear_rect,
        "filter_clear_visible": bool(
            getattr(getattr(widget, "_filter_clear_button", None), "visible", False)
        ),
        "tree_rect": frame_rect,
        "scroll_y": scroll_y,
        "row_height": row_height,
        "visible_row_count": len(rows),
        "expanded_paths": sorted(expanded_paths),
        "active_rename_path": item_path(active_item),
        "active_rename_rect": _widget_rect(rename_field),
        "pending_rename_path": item_path(pending_item),
        "rows": rows,
    }


def _property_ui_snapshot(app: Any) -> dict[str, Any]:
    """Return bounded Property Inspector state and real input geometry."""

    window = getattr(app, "_property_window", None)
    adapter = getattr(window, "_adapter", None)
    rows_by_name = getattr(window, "_inspector_attribute_rows", {}) or {}
    if window is None or adapter is None:
        return {"available": False, "selection": [], "rows": {}}

    filter_field = getattr(window, "_filter_field", None)
    filter_model = getattr(filter_field, "model", None)
    scroll_rect = _widget_rect(getattr(window, "_scroll_frame", None))
    rows: dict[str, Any] = {}
    for attr_name in list(rows_by_name)[:_MAX_SEQUENCE_ITEMS]:
        row = rows_by_name[attr_name]
        metadata = _safe_call(None, adapter.get_attribute_metadata, attr_name)
        field_widgets = list(getattr(row, "_widgets", ()) or ())
        if not field_widgets:
            widget = getattr(row, "_widget", None)
            if widget is not None:
                field_widgets = [widget]
        field_rects = [_widget_rect(widget) for widget in field_widgets]
        indicator = getattr(row, "_indicator", None)
        active_state = getattr(indicator, "active_state", None)
        indicator_widget = getattr(indicator, "widget", None)
        per_component = _safe_call(
            None,
            adapter.get_per_component_ambiguity,
            attr_name,
        )
        combo = field_widgets[0] if len(field_widgets) == 1 else None
        combo_model = getattr(combo, "model", None)
        combo_index = None
        if combo_model is not None and hasattr(combo_model, "get_item_value_model"):
            combo_index_model = _safe_call(
                None,
                combo_model.get_item_value_model,
                None,
            )
            if combo_index_model is not None:
                combo_index = _safe_call(
                    None,
                    combo_index_model.get_value_as_int,
                )
        rows[str(attr_name)] = {
            "display_name": str(getattr(metadata, "display_name", "") or ""),
            "type_name": str(getattr(metadata, "type_name", "") or ""),
            "group": str(getattr(metadata, "group", "") or ""),
            "value": _json_value(_safe_call(None, adapter.get_value, attr_name)),
            "ambiguous": bool(_safe_call(False, adapter.is_ambiguous, attr_name)),
            "per_component_ambiguity": _json_value(per_component),
            "allowed_values": _json_value(
                getattr(metadata, "allowed_values", None)
            ),
            "is_authored": bool(getattr(metadata, "is_authored", False)),
            "is_locked": bool(getattr(metadata, "is_locked", False)),
            "field_rects": field_rects,
            "field_points": [
                [
                    int(round(rect["x"] + rect["width"] * 0.5)),
                    int(round(rect["y"] + rect["height"] * 0.5)),
                ]
                for rect in field_rects
                if rect is not None
            ],
            "field_enabled": [
                bool(getattr(widget, "enabled", True))
                for widget in field_widgets
            ],
            "field_widget_types": [
                type(widget).__name__ for widget in field_widgets
            ],
            "combo_index": combo_index,
            "indicator_state": str(getattr(active_state, "name", "") or ""),
            "indicator_rect": _widget_rect(indicator_widget),
            "indicator_visible": bool(
                getattr(indicator_widget, "visible", False)
            ),
        }

    filter_rect = _widget_rect(getattr(window, "_filter_border_rect", None))
    clear_rect = _widget_rect(getattr(window, "_filter_clear_button", None))
    return {
        "available": True,
        "selection": [str(path) for path in getattr(window, "_selection", ())],
        "filter_text": (
            str(_safe_call("", filter_model.get_value_as_string))
            if filter_model is not None
            else ""
        ),
        "filter_focused": str(
            getattr(getattr(window, "_filter_border_rect", None), "name", "")
        ) == "focused",
        "filter_rect": filter_rect,
        "filter_clear_rect": clear_rect,
        "scroll_rect": scroll_rect,
        "row_count": len(rows_by_name),
        "rows_truncated": len(rows_by_name) > _MAX_SEQUENCE_ITEMS,
        "rows": rows,
    }


def _adapter_hierarchy_snapshot(adapter: Any) -> dict[str, Any]:
    if adapter is None:
        return {"available": False, "paths": [], "prims": {}}
    try:
        root = adapter.get_root()
    except Exception as exc:
        return {
            "available": False,
            "paths": [],
            "prims": {},
            "error": f"{type(exc).__name__}: {exc}",
        }

    prims: dict[str, Any] = {}
    stack = [root]
    visited: set[str] = set()
    while stack:
        item = stack.pop()
        path = str(_safe_call("", adapter.get_item_path, item))
        if not path or path in visited:
            continue
        visited.add(path)
        children = list(_safe_call([], adapter.get_children, item) or [])
        child_paths = [
            str(_safe_call("", adapter.get_item_path, child))
            for child in children
        ]
        visibility = _safe_call("", adapter.compute_visibility, item)
        prims[path] = {
            "display_name": str(_safe_call("", adapter.get_display_name, item)),
            "type_name": str(_safe_call("", adapter.get_type_name, item)),
            "type_category": str(_safe_call("", adapter.get_type_category, item)),
            "badge_flags": int(_enum_value(_safe_call(0, adapter.get_badge_flags, item)) or 0),
            "item_flags": int(_enum_value(_safe_call(0, adapter.get_item_flags, item)) or 0),
            "visibility": str(
                getattr(visibility, "name", "") or _enum_value(visibility)
            ),
            "children": child_paths,
        }
        stack.extend(reversed(children))
    return {
        "available": True,
        "paths": sorted(path for path in prims if path != "/"),
        "prims": prims,
    }


def _stage_from_app(app: Any) -> tuple[Any | None, Any | None]:
    session = getattr(app, "_adapter_session", None)
    scene = getattr(session, "current_scene", None)
    if scene is not None:
        try:
            return scene.backing_usd_stage, scene
        except Exception:
            pass
    adapter = getattr(app, "_stage_adapter", None)
    stage = getattr(adapter, "stage", None)
    if stage is not None and callable(getattr(stage, "TraverseAll", None)):
        return stage, None
    return None, scene


def _attribute_snapshot(attribute: Any) -> dict[str, Any]:
    value = _safe_call(None, attribute.Get)
    connections = _safe_call([], attribute.GetConnections)
    return {
        "type": str(_safe_call("", attribute.GetTypeName)),
        "value": _json_value(value),
        "numeric_fingerprint": _numeric_value_fingerprint(value),
        "authored": bool(_safe_call(False, attribute.HasAuthoredValueOpinion)),
        "connections": [str(path) for path in connections],
    }


def _relationship_snapshot(relationship: Any) -> dict[str, Any]:
    return {
        "targets": [str(path) for path in _safe_call([], relationship.GetTargets)],
    }


def _usd_local_matrix(
    prim: Any,
    evidence_provider: Any | None = None,
) -> list[list[float]] | None:
    reader = getattr(evidence_provider, "inspector_usd_local_matrix", None)
    if not callable(reader):
        return None
    return _matrix_values(_safe_call(None, reader, prim))


def _usd_computed_extent_fingerprint(
    prim: Any,
    evidence_provider: Any | None = None,
) -> dict[str, Any] | None:
    """Compute the schema extent OVStage population derives for Boundables."""

    reader = getattr(evidence_provider, "inspector_usd_computed_extent", None)
    if not callable(reader):
        return None
    extent = _safe_call(None, reader, prim)
    return _numeric_value_fingerprint(extent)


def _find_relative_layer(
    layer: Any,
    path: str,
    evidence_provider: Any | None = None,
) -> Any | None:
    finder = getattr(evidence_provider, "inspector_find_relative_layer", None)
    if callable(finder):
        return _safe_call(None, finder, layer, str(path))
    # Sdf.Layer exposes FindRelativeToLayer as a static method on the concrete
    # layer type.  Calling it through the object protocol keeps ovui_widgets free
    # of a concrete OpenUSD import while retaining useful raw-stage tests.
    finder = getattr(type(layer), "FindRelativeToLayer", None)
    if callable(finder):
        return _safe_call(None, finder, layer, str(path))
    return None


def _source_layer_identifiers(
    scene: Any,
    evidence_provider: Any | None = None,
) -> set[str] | None:
    if scene is None:
        return None
    try:
        source = scene.backing_usd_source_layer
    except Exception:
        return set()
    pending = [source]
    identifiers: set[str] = set()
    while pending:
        layer = pending.pop()
        identifier = str(getattr(layer, "identifier", ""))
        if not identifier or identifier in identifiers:
            continue
        identifiers.add(identifier)
        for sublayer_path in getattr(layer, "subLayerPaths", ()):
            child = _find_relative_layer(
                layer,
                str(sublayer_path),
                evidence_provider,
            )
            if child is not None:
                pending.append(child)
    return identifiers


def _usd_stage_snapshot(
    stage: Any,
    scene: Any = None,
    evidence_provider: Any | None = None,
) -> dict[str, Any]:
    if stage is None:
        return {"available": False, "paths": [], "prims": {}}
    source_layer_ids = _source_layer_identifiers(scene, evidence_provider)
    presentation_roots = tuple(
        str(root)
        for root in (getattr(scene, "presentation_root_paths", ()) or ())
    )
    direct_source_paths: set[str] = set()
    prims: dict[str, Any] = {}
    for prim in _safe_call([], stage.TraverseAll):
        path = str(_safe_call("", prim.GetPath))
        if not path:
            continue
        if source_layer_ids is None:
            direct_source_paths.add(path)
        elif any(
            str(getattr(getattr(spec, "layer", None), "identifier", ""))
            in source_layer_ids
            for spec in _safe_call([], prim.GetPrimStack)
        ):
            direct_source_paths.add(path)
        attributes = {
            str(_safe_call("", attribute.GetName)): _attribute_snapshot(attribute)
            for attribute in _safe_call([], prim.GetAttributes)
        }
        relationships = {
            str(_safe_call("", relationship.GetName)): _relationship_snapshot(relationship)
            for relationship in _safe_call([], prim.GetRelationships)
        }
        prim_type_info = _safe_call(None, prim.GetPrimTypeInfo)
        schema_type = (
            _safe_call(None, prim_type_info.GetSchemaType)
            if prim_type_info is not None
            else None
        )
        prims[path] = {
            "type_name": str(_safe_call("", prim.GetTypeName)),
            "schema_registered": bool(schema_type),
            "runtime_owned": any(
                path == root or path.startswith(f"{root}/")
                for root in presentation_roots
            ),
            "specifier": str(_safe_call("", prim.GetSpecifier)),
            "active": bool(_safe_call(False, prim.IsActive)),
            "defined": bool(_safe_call(False, prim.IsDefined)),
            "abstract": bool(_safe_call(False, prim.IsAbstract)),
            "instance": bool(_safe_call(False, prim.IsInstance)),
            "instanceable": bool(_safe_call(False, prim.IsInstanceable)),
            "loaded": bool(_safe_call(False, prim.IsLoaded)),
            "has_references": bool(_safe_call(False, prim.HasAuthoredReferences)),
            "has_payloads": bool(_safe_call(False, prim.HasAuthoredPayloads)),
            "children": [str(child.GetPath()) for child in _safe_call([], prim.GetAllChildren)],
            "local_matrix": _usd_local_matrix(prim, evidence_provider),
            "computed_extent_fingerprint": _usd_computed_extent_fingerprint(
                prim,
                evidence_provider,
            ),
            "attributes": attributes,
            "relationships": relationships,
        }
    for path, record in prims.items():
        current = path
        source_authored = False
        while current and current != "/":
            if current in direct_source_paths:
                source_authored = True
                break
            current = current.rpartition("/")[0] or "/"
        record["source_authored"] = source_authored
    root_layer = _safe_call(None, stage.GetRootLayer)
    edit_target = _safe_call(None, stage.GetEditTarget)
    edit_layer = _safe_call(None, edit_target.GetLayer) if edit_target is not None else None
    default_prim = _safe_call(None, stage.GetDefaultPrim)
    return {
        "available": True,
        "root_layer": str(getattr(root_layer, "identifier", "")),
        "root_real_path": str(getattr(root_layer, "realPath", "")),
        "edit_target": str(getattr(edit_layer, "identifier", "")),
        "default_prim": str(_safe_call("", default_prim.GetPath)) if default_prim else "",
        "paths": sorted(prims),
        "prims": prims,
    }


def _native_raw_bytes(value: Any) -> bytes:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    return b""


def _native_matrix_value(raw: bytes) -> list[list[float]] | None:
    if len(raw) == 16 * 8:
        values = struct.unpack("<16d", raw)
    elif len(raw) == 16 * 4:
        values = struct.unpack("<16f", raw)
    else:
        return None
    return [
        [float(values[row * 4 + column]) for column in range(4)]
        for row in range(4)
    ]


def _native_attribute_snapshot(
    stage: Any,
    ordinal: int,
    path: str,
    name: str,
    evidence_provider: Any | None = None,
) -> dict[str, Any]:
    raw_value = _safe_call(None, stage.read_attribute, ordinal, [path], name)
    raw = _native_raw_bytes(raw_value)
    result: dict[str, Any] = {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest() if raw else "",
    }
    read_path_targets = getattr(stage, "read_path_targets", None)
    if callable(read_path_targets):
        path_targets = _safe_call(
            None,
            read_path_targets,
            int(ordinal),
            str(path),
            str(name),
        )
        if path_targets is not None:
            result["path_targets"] = [str(value) for value in path_targets]
    if raw and len(raw) <= 256:
        result["hex"] = raw.hex()
    if name in _NATIVE_MATRIX_ATTRIBUTES:
        result["value"] = _native_matrix_value(raw)
    elif name in _NATIVE_SCALAR_ATTRIBUTES:
        if len(raw) == 8:
            result["value"] = float(struct.unpack("<d", raw)[0])
        elif len(raw) == 4:
            result["value"] = float(struct.unpack("<f", raw)[0])
    elif name in _NATIVE_TOKEN_ATTRIBUTES:
        reader = getattr(
            evidence_provider,
            "inspector_native_token_attribute",
            None,
        )
        if callable(reader):
            token_value = _safe_call(None, reader, stage, path, name)
            # Kit's native token bridge can return ``b""`` for an absent
            # schema-fallback value.  Absence is an evidence gap, not a real
            # empty token that should be compared against USD's fallback.
            if token_value not in (None, "", b""):
                result["value"] = token_value
    elif (
        raw_value is not None
        and not raw
        and not isinstance(raw_value, (bytes, bytearray, memoryview))
    ):
        result["value"] = _json_value(raw_value)
    return result


def _ovstage_snapshot(
    scene: Any,
    evidence_provider: Any | None = None,
) -> dict[str, Any]:
    if scene is None:
        return {"available": False, "paths": [], "prims": {}}
    stage = getattr(scene, "_stage", None)
    ordinal = getattr(scene, "current_ordinal", None)
    if stage is None or ordinal is None:
        return {"available": False, "paths": [], "prims": {}}
    try:
        groups = stage.query_prims(int(ordinal)).get("groups", ())
        prims: dict[str, Any] = {}
        for group in groups:
            handle = int(group.get("prim_list_handle") or 0)
            if not handle:
                continue
            type_name = str(group.get("prim_type", ""))
            schemas = [str(value) for value in group.get("applied_schemas", ())]
            resolver = getattr(
                evidence_provider,
                "inspector_native_query_names",
                None,
            )
            if callable(resolver):
                attribute_names = _safe_call(
                    (),
                    resolver,
                    stage,
                    group.get("attributes", ()),
                )
            else:
                attribute_names = tuple(
                    str(value) for value in group.get("attributes", ())
                )
            for path_value in stage.get_prim_paths(handle):
                path = str(path_value)
                prims[path] = {
                    "type_name": type_name,
                    "applied_schemas": schemas,
                    "attributes": {
                        str(name): _native_attribute_snapshot(
                            stage,
                            int(ordinal),
                            path,
                            str(name),
                            evidence_provider,
                        )
                        for name in attribute_names
                    },
                }
    except Exception as exc:
        return {
            "available": False,
            "ordinal": int(ordinal),
            "paths": [],
            "prims": {},
            "error": f"{type(exc).__name__}: {exc}",
        }
    # Child-topology authority: record each prim's ordered children — and the
    # pseudo-root's ordered top-level children (native root query convention,
    # ``get_child_paths("")``) — directly from the native stage. Absent,
    # throwing, non-iterable, or otherwise malformed enumeration — including
    # semantically invalid child paths (relative, empty, root, non-canonical,
    # wrong direct parent, duplicates) — is recorded as an explicit authority
    # error instead of being accepted or converted into an empty child list,
    # so topology parity fails closed on any authority failure. User-facing
    # versus provider-owned filtering uses the SAME scene-specific ownership
    # rule as the production OVStage adapter (scene-registered presentation
    # roots plus the authored-/Render exception), obtained through the
    # provider session's ``inspector_user_facing_scene_path`` evidence hook —
    # the policy lives in the provider package, so the two cannot drift and
    # ovui-widgets stays free of provider-package imports.
    child_topology: dict[str, Any] = {"available": False, "errors": []}
    ownership_hook = getattr(
        evidence_provider, "inspector_user_facing_scene_path", None
    )
    if not callable(ownership_hook):
        _ownership_rule = None
        child_topology["errors"].append(
            {
                "path": None,
                "error": "active provider exposes no ownership rule "
                "(inspector_user_facing_scene_path)",
            }
        )
    else:
        _ownership_rule = ownership_hook
        child_topology["presentation_roots"] = [
            str(root)
            for root in (getattr(scene, "presentation_root_paths", ()) or ())
        ]

        def _user_facing(path: str) -> bool:
            return bool(ownership_hook(path))

        try:
            for path, record in prims.items():
                record["user_facing"] = _user_facing(path)
        except Exception as exc:
            _ownership_rule = None
            child_topology["errors"].append(
                {
                    "path": None,
                    "error": "provider ownership rule failed "
                    f"({type(exc).__name__}: {exc})",
                }
            )
    get_child_paths = getattr(stage, "get_child_paths", None)
    if not callable(get_child_paths):
        child_topology["errors"].append(
            {
                "path": None,
                "error": "native stage exposes no callable get_child_paths "
                "child enumeration",
            }
        )
    elif _ownership_rule is not None:

        def _validate_children(
            query_path: str, children: list[str]
        ) -> str | None:
            # Mirrors the production adapter's canonical path contract
            # (``_normalize_path``): absolute, non-root, no empty/"."/".."
            # segments, direct child of the queried node, unique.
            expected_parent = "/" if query_path == "" else query_path
            seen: set[str] = set()
            for child in children:
                if not child or child == "/":
                    return f"empty or root child path {child!r}"
                if not child.startswith("/"):
                    return f"relative child path {child!r}"
                if child.endswith("/") or "//" in child:
                    return f"non-canonical child path {child!r}"
                if any(part in (".", "..") for part in child.split("/")[1:]):
                    return f"dot-segment child path {child!r}"
                parent = child.rsplit("/", 1)[0] or "/"
                if parent != expected_parent:
                    return (
                        f"child {child!r} is not a direct child of "
                        f"{expected_parent!r}"
                    )
                if child in seen:
                    return f"duplicate child path {child!r}"
                seen.add(child)
            return None

        def _enumerate_children(query_path: str) -> tuple[list[str] | None, str | None]:
            try:
                raw = get_child_paths(query_path)
            except Exception as exc:
                return None, f"{type(exc).__name__}: {exc}"
            if isinstance(raw, (str, bytes)) or not hasattr(raw, "__iter__"):
                return None, (
                    "non-iterable child enumeration result: "
                    f"{type(raw).__name__}"
                )
            try:
                items = list(raw)
            except Exception as exc:
                return None, f"{type(exc).__name__}: {exc}"
            children: list[str] = []
            for item in items:
                # The production adapter's path contract rejects non-string
                # values outright; do not stringify them into plausible paths.
                if not isinstance(item, str):
                    return None, (
                        "invalid child enumeration: non-string child item "
                        f"of type {type(item).__name__}"
                    )
                children.append(item)
            violation = _validate_children(query_path, children)
            if violation is not None:
                return None, f"invalid child enumeration: {violation}"
            try:
                return (
                    [child for child in children if _user_facing(child)],
                    None,
                )
            except Exception as exc:
                return None, (
                    f"provider ownership rule failed ({type(exc).__name__}: {exc})"
                )

        root_children, root_error = _enumerate_children("")
        if root_error is not None:
            child_topology["errors"].append({"path": "/", "error": root_error})
        else:
            child_topology["root_children"] = root_children
        for path, record in prims.items():
            children, error = _enumerate_children(path)
            if error is not None:
                child_topology["errors"].append({"path": path, "error": error})
                continue
            record["children"] = children
        child_topology["available"] = not child_topology["errors"]
    return {
        "available": True,
        "ordinal": int(ordinal),
        "topology_version": int(_safe_call(0, stage.get_topology_version)),
        "source_path": str(getattr(scene, "source_path", "")),
        "paths": sorted(prims),
        "prims": prims,
        "child_topology": child_topology,
    }


def _transform_adapter_from_app(app: Any) -> Any | None:
    viewport = getattr(app, "_viewport_window", None)
    model = getattr(viewport, "_transform_model", None)
    return getattr(model, "_transform", None)


def _transform_interaction_snapshot(app: Any) -> dict[str, Any]:
    viewport = getattr(app, "_viewport_window", None)
    model = getattr(viewport, "_transform_model", None)
    snap = getattr(model, "_snap", None) or getattr(app, "_snap_system", None)
    providers = list(getattr(snap, "_providers", ()) or ()) if snap is not None else []
    grid_size = None
    for provider in providers:
        candidate = getattr(provider, "grid_size", None)
        if candidate is None:
            candidate = getattr(provider, "_grid_size", None)
        if candidate is not None:
            try:
                grid_size = float(candidate)
            except (TypeError, ValueError):
                grid_size = None
            break
    get_active_tool = getattr(viewport, "_get_active_tool", None)
    active_tool = _safe_call("", get_active_tool) if callable(get_active_tool) else ""
    tool_buttons: dict[str, Any] = {}
    for tool, button in (getattr(viewport, "_toolbar_buttons", {}) or {}).items():
        if str(tool).startswith("__"):
            continue
        tool_buttons[str(tool)] = {
            "rect": _widget_rect(button),
            "enabled": bool(getattr(button, "enabled", True)),
        }
    settings_dialog = getattr(app, "_settings_dialog", None)
    settings_window = getattr(settings_dialog, "_window", None)
    snap_checkbox = getattr(settings_dialog, "_snap_checkbox", None)
    grid_drag = getattr(settings_dialog, "_grid_size_drag", None)
    close_button = getattr(settings_dialog, "_close_button", None)
    return {
        "active_tool": str(active_tool or ""),
        "drag_active": bool(getattr(model, "_drag_active", False)),
        "raw_selected_paths": [
            str(path) for path in (getattr(model, "_raw_selected_paths", ()) or ())
        ],
        "transformable_paths": [
            str(path) for path in (getattr(model, "_selected_paths", ()) or ())
        ],
        "snap_enabled": bool(getattr(snap, "_enabled", False)),
        "grid_size": grid_size,
        "tool_buttons": tool_buttons,
        "settings_dialog": {
            "visible": bool(getattr(settings_window, "visible", False)),
            "snap_checkbox_rect": _widget_rect(snap_checkbox),
            "grid_size_rect": _widget_rect(grid_drag),
            "close_button_rect": _widget_rect(close_button),
        },
    }


def _transform_snapshot(
    app: Any,
    usd_snapshot: dict[str, Any],
    native_snapshot: dict[str, Any],
) -> dict[str, Any]:
    adapter = _transform_adapter_from_app(app)
    if adapter is None:
        return {
            "available": False,
            "paths": {},
            "mismatches": [],
            "interaction": _transform_interaction_snapshot(app),
        }
    paths: dict[str, Any] = {}
    mismatches: list[str] = []
    controls = getattr(getattr(app, "_adapter_session", None), "physics_controls", None)
    physics_owned_paths = {
        str(path) for path in (getattr(controls, "_pose_paths", ()) or ())
    } if bool(getattr(controls, "enabled", False)) else set()
    user_paths = _usd_user_paths(usd_snapshot)
    for path, prim in usd_snapshot.get("prims", {}).items():
        if path not in user_paths:
            continue
        usd_local = prim.get("local_matrix")
        if usd_local is None:
            continue
        adapter_local = _matrix_values(
            _safe_call(None, adapter.get_local_transform, path)
        )
        native_attributes = (
            native_snapshot.get("prims", {}).get(path, {}).get("attributes", {})
        )
        native_local = native_attributes.get("localMatrix", {}).get("value")
        physics_owned = path in physics_owned_paths
        adapter_matches_usd = _matrix_close(usd_local, adapter_local)
        native_evidence_required = bool(
            native_snapshot.get("available")
            and prim.get("active")
            and prim.get("defined")
            and not prim.get("abstract")
            and path in native_snapshot.get("prims", {})
        )
        native_matches_usd = (
            _matrix_close(usd_local, native_local)
            if native_evidence_required
            else True
        )
        adapter_matches_native = _matrix_close(adapter_local, native_local)
        if physics_owned:
            matches = (
                native_evidence_required
                and native_local is not None
                and adapter_matches_native
            )
        else:
            matches = adapter_matches_usd and native_matches_usd
        paths[path] = {
            "usd_local": usd_local,
            "adapter_local": adapter_local,
            "native_local": native_local,
            "native_evidence_required": native_evidence_required,
            "native_evidence_present": native_local is not None,
            "physics_owned": physics_owned,
            "adapter_matches": adapter_matches_usd,
            "native_matches": native_matches_usd,
            "adapter_matches_native": adapter_matches_native,
            "runtime_differs_from_usd": not native_matches_usd,
            "matches": matches,
        }
        if not matches:
            mismatches.append(path)
    return {
        "available": True,
        "paths": paths,
        "mismatches": mismatches,
        "physics_owned_paths": sorted(physics_owned_paths),
        "interaction": _transform_interaction_snapshot(app),
    }


def _layers_ui_snapshot(app: Any) -> dict[str, Any]:
    """Return stable Layers-window rows and real Inspector hit geometry.

    This is an observation-only bridge. It walks exactly the rows the live
    ``TreeView`` reports expanded, then derives the seven documented column
    hit targets from the tree's measured rectangle and shared 18 px row
    height. Popup and modal controls use their actual widget rectangles.
    """

    layer_window = getattr(app, "_layer_window", None)
    model = getattr(layer_window, "_model", None)
    tree = getattr(layer_window, "_tree_view", None)
    scrolling_frame = getattr(layer_window, "_tree_scrolling_frame", None)
    native_window = getattr(layer_window, "_window", None)
    if layer_window is None or model is None or tree is None or scrolling_frame is None:
        return {"available": False, "rows": [], "context_menu": {"shown": False}}

    def point(rect: dict[str, float] | None) -> list[int] | None:
        if rect is None or rect["width"] <= 0.0 or rect["height"] <= 0.0:
            return None
        return [
            int(round(rect["x"] + rect["width"] * 0.5)),
            int(round(rect["y"] + rect["height"] * 0.5)),
        ]

    def window_rect(window: Any) -> dict[str, float] | None:
        if window is None:
            return None
        try:
            return {
                "x": float(getattr(window, "position_x", 0.0) or 0.0),
                "y": float(getattr(window, "position_y", 0.0) or 0.0),
                "width": float(getattr(window, "width", 0.0) or 0.0),
                "height": float(getattr(window, "height", 0.0) or 0.0),
            }
        except (TypeError, ValueError):
            return None

    def action_id(label: str) -> str:
        return "_".join(
            part for part in "".join(
                char.lower() if char.isalnum() else " " for char in label
            ).split() if part
        )

    tree_rect = _widget_rect(scrolling_frame) or {
        "x": 0.0,
        "y": 0.0,
        "width": 0.0,
        "height": 0.0,
    }
    tree_widget_rect = _widget_rect(tree)
    try:
        scroll_y = float(getattr(scrolling_frame, "scroll_y", 0.0) or 0.0)
    except (TypeError, ValueError):
        scroll_y = 0.0
    selected_items = list(getattr(model, "selected_items", ()) or ())
    # The standalone TreeView lays Layers rows on a 16 px stride even though
    # the shared style token is 18 px. Inspector actions must follow measured
    # paint geometry: an 18 px assumption drifts two pixels per child and can
    # miss the narrow mute/lock hit surfaces after the root row.
    row_height = 16.0
    visible: list[tuple[Any, int]] = []

    def is_expanded(item: Any) -> bool:
        return bool(_safe_call(False, tree.is_expanded, item))

    def walk(parent: Any, depth: int) -> None:
        for child in list(_safe_call([], model.get_item_children, parent) or []):
            visible.append((child, depth))
            if is_expanded(child):
                walk(child, depth + 1)

    walk(None, 0)
    occurrence_by_identifier: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    # The ScrollingFrame rectangle includes its vertical scrollbar. Column
    # layout belongs to the TreeView's content rectangle; using the outer
    # frame shifts every narrow action-column hit target onto the next cell.
    column_rect = (
        tree_widget_rect
        if tree_widget_rect is not None and tree_widget_rect["width"] > 0.0
        else tree_rect
    )
    right = column_rect["x"] + column_rect["width"]
    column_points = {
        "live": right - 134.0,
        "save": right - 110.0,
        "mute": right - 86.0,
        "global_mute": right - 62.0,
        "latest": right - 38.0,
        "lock": right - 13.0,
    }
    for index, (item, depth) in enumerate(visible):
        row_y = tree_rect["y"] + index * row_height - scroll_y
        # Glyphs are optically centred one pixel below the 16 px stride's
        # arithmetic midpoint in this backend (root chevron at y+9).
        center_y = int(round(row_y + 9.0))
        rect = {
            "x": tree_rect["x"],
            "y": row_y,
            "width": tree_rect["width"],
            "height": row_height,
        }
        layer_item = getattr(item, "layer_item", None)
        is_prim_spec = layer_item is not None and hasattr(item, "path")
        if is_prim_spec:
            layer_identifier = str(getattr(layer_item, "identifier", ""))
            spec_path = str(getattr(item, "path", ""))
            identifier = f"{layer_identifier}::{spec_path}"
            row_type = "prim_spec"
            parent_identifier = (
                f"{layer_identifier}::{getattr(getattr(item, 'parent', None), 'path', '')}"
                if getattr(item, "parent", None) is not None
                else layer_identifier
            )
        else:
            layer_identifier = str(getattr(item, "identifier", ""))
            spec_path = ""
            identifier = layer_identifier
            row_type = "layer"
            parent_identifier = str(
                getattr(getattr(item, "parent", None), "identifier", "")
            )
        occurrence = occurrence_by_identifier.get(identifier, 0)
        occurrence_by_identifier[identifier] = occurrence + 1
        row_key = f"{row_type}:{identifier}#{occurrence}"
        name_x = tree_rect["x"] + 32.0 + depth * 14.0
        in_viewport = (
            row_y + row_height > tree_rect["y"]
            and row_y < tree_rect["y"] + tree_rect["height"]
        )
        record: dict[str, Any] = {
            "key": row_key,
            "type": row_type,
            "identifier": identifier,
            "layer_identifier": layer_identifier,
            "spec_path": spec_path,
            "parent_identifier": parent_identifier,
            "index": index,
            "depth": depth,
            "selected": item in selected_items,
            "focused": bool(getattr(item, "is_focused", False)),
            "expanded": is_expanded(item),
            "has_children": bool(_safe_call(False, model.can_item_have_children, item)),
            "visible_in_viewport": in_viewport,
            "rect": rect,
            "select_point": [int(round(name_x)), center_y],
            "name_point": [int(round(name_x)), center_y],
            "context_menu_point": [int(round(name_x)), center_y],
            "drag_point": [int(round(name_x)), center_y],
            "drop_above_point": [int(round(name_x)), int(round(row_y + 2.0))],
            "drop_on_point": [int(round(name_x)), center_y],
            "drop_below_point": [
                int(round(name_x)),
                int(round(row_y + row_height - 2.0)),
            ],
            "chevron_point": [
                # Layer TreeView reserves a 14 px branch column before the
                # delegate's chevron; its visual center is 20 px from the
                # content edge at depth zero, then 14 px per level.
                int(round(tree_rect["x"] + depth * 14.0 + 20.0)),
                center_y,
            ],
        }
        if row_type == "layer":
            record.update(
                {
                    "display_name": str(_safe_call("", lambda: item.display_name)),
                    "is_edit_target": bool(getattr(item, "is_edit_target", False)),
                    "dirty": bool(_safe_call(False, lambda: item.is_dirty)),
                    "muted": bool(_safe_call(False, lambda: item.is_muted)),
                    "locked": bool(_safe_call(False, lambda: item.is_locked)),
                    "anonymous": bool(_safe_call(False, lambda: item.is_anonymous)),
                    "missing": bool(_safe_call(False, lambda: item.is_missing)),
                    "read_only": bool(_safe_call(False, lambda: item.is_read_only)),
                    "delete_eligible": getattr(item, "parent", None) is not None,
                    "save_action_visible": bool(
                        _safe_call(False, lambda: item.is_dirty)
                        and not _safe_call(False, lambda: item.is_missing)
                    ),
                    "action_points": {
                        name: [int(round(x)), center_y]
                        for name, x in column_points.items()
                    },
                }
            )
        else:
            descriptor = getattr(item, "descriptor", None)
            record.update(
                {
                    "type_name": str(getattr(item, "type_name", "") or ""),
                    "specifier": str(_enum_value(getattr(item, "specifier", ""))),
                    "has_reference": bool(getattr(descriptor, "has_reference", False)),
                    "has_payload": bool(getattr(descriptor, "has_payload", False)),
                    "is_instanceable": bool(getattr(descriptor, "is_instanceable", False)),
                }
            )
        rows.append(record)

    filter_field = getattr(layer_window, "_filter_field", None)
    filter_model = getattr(filter_field, "model", None)
    context_builder = getattr(layer_window, "_context_menu_builder", None)
    menu = getattr(context_builder, "_menu", None)
    menu_shown = bool(
        menu is not None
        and (
            getattr(menu, "shown", False)
            or getattr(menu, "visible", False)
        )
    )
    menu_entries: list[dict[str, Any]] = []
    if menu_shown:
        for label, enabled, widget in list(
            getattr(context_builder, "_inspector_menu_items", ()) or ()
        ):
            entry_rect = _widget_rect(widget)
            menu_entries.append(
                {
                    "id": action_id(str(label)),
                    "label": str(label),
                    "enabled": bool(enabled),
                    "rect": entry_rect,
                    "point": point(entry_rect),
                }
            )

    file_dialog: dict[str, Any] = {"shown": False}
    try:
        from ovui_widgets.common import file_dialogs

        open_file_dialogs = list(getattr(file_dialogs, "_OPEN_DIALOGS", ()) or ())
        if open_file_dialogs:
            dialog = open_file_dialogs[-1]
            dialog_window = getattr(dialog, "_window", None)
            field_rect = _widget_rect(getattr(dialog, "_field", None))
            save_rect = _widget_rect(getattr(dialog, "_save_button", None))
            cancel_rect = _widget_rect(getattr(dialog, "_cancel_button", None))
            file_dialog = {
                "shown": bool(getattr(dialog_window, "visible", False)),
                "title": str(getattr(dialog_window, "title", "") or ""),
                "window_rect": window_rect(dialog_window),
                "path": str(getattr(dialog, "path", "") or ""),
                "field_rect": field_rect,
                "field_point": point(field_rect),
                "save_rect": save_rect,
                "save_point": point(save_rect),
                "cancel_rect": cancel_rect,
                "cancel_point": point(cancel_rect),
            }
    except Exception:
        pass

    confirm_dialog: dict[str, Any] = {"shown": False}
    try:
        from ovui_widgets.common import dialogs

        open_confirm_dialogs = list(getattr(dialogs, "_OPEN_DIALOGS", ()) or ())
        try:
            from ovui_widgets.content.widget import confirm_overwrite_dialog

            open_confirm_dialogs.extend(
                list(
                    getattr(confirm_overwrite_dialog, "_OPEN_DIALOGS", ()) or ()
                )
            )
        except Exception:
            pass
        if open_confirm_dialogs:
            dialog = open_confirm_dialogs[-1]
            dialog_window = getattr(dialog, "_window", None)
            confirm_rect = _widget_rect(getattr(dialog, "_confirm_button", None))
            cancel_rect = _widget_rect(getattr(dialog, "_cancel_button", None))
            confirm_dialog = {
                "shown": bool(getattr(dialog_window, "visible", False)),
                "title": str(getattr(dialog_window, "title", "") or ""),
                "url": str(getattr(dialog, "url", "") or ""),
                "window_rect": window_rect(dialog_window),
                "confirm_rect": confirm_rect,
                "confirm_point": point(confirm_rect),
                "cancel_rect": cancel_rect,
                "cancel_point": point(cancel_rect),
            }
    except Exception:
        pass

    open_file_dialog: dict[str, Any] = {"shown": False}
    try:
        from ovui_widgets.content.file_exporter import FileExporterHelper
        from ovui_widgets.content.file_importer import FileImporterHelper

        helpers = (
            ("import", getattr(FileImporterHelper, "_singleton", None)),
            ("export", getattr(FileExporterHelper, "_singleton", None)),
        )
        candidates = [
            (kind, getattr(helper, "_dialog", None))
            for kind, helper in helpers
            if helper is not None and getattr(helper, "_dialog", None) is not None
        ]
        visible = [
            (kind, dialog)
            for kind, dialog in candidates
            if bool(getattr(getattr(dialog, "_window", None), "visible", False))
        ]
        kind, dialog = (visible or candidates or [("", None)])[-1]
        dialog_window = getattr(dialog, "_window", None)
        file_bar = getattr(dialog, "_file_bar", None)
        if dialog is not None and dialog_window is not None:
            field = getattr(file_bar, "_field", None)
            if field is None:
                field = getattr(dialog, "_filename_field", None)
            apply_button = getattr(file_bar, "_apply_button", None)
            cancel_button = getattr(file_bar, "_cancel_button", None)
            field_rect = _widget_rect(field)
            apply_rect = _widget_rect(apply_button)
            cancel_rect = _widget_rect(cancel_button)
            open_file_dialog = {
                "shown": bool(getattr(dialog_window, "visible", False)),
                "kind": kind,
                "title": str(getattr(dialog_window, "title", "") or ""),
                "window_rect": window_rect(dialog_window),
                "filename": str(_safe_call("", dialog.get_filename)),
                "directory": str(_safe_call("", dialog.get_directory)),
                "field_rect": field_rect,
                "field_point": point(field_rect),
                "apply_rect": apply_rect,
                "apply_point": point(apply_rect),
                "apply_enabled": bool(getattr(apply_button, "enabled", False)),
                "cancel_rect": cancel_rect,
                "cancel_point": point(cancel_rect),
            }
    except Exception:
        pass

    def control(widget: Any) -> dict[str, Any]:
        rect = _widget_rect(widget)
        return {
            "rect": rect,
            "point": point(rect),
            "enabled": bool(getattr(widget, "enabled", True)),
            "visible": bool(getattr(widget, "visible", True)),
        }

    options = getattr(layer_window, "_options_button", None)
    return {
        "available": True,
        "window_visible": bool(getattr(native_window, "visible", False)),
        "window_focused": bool(getattr(native_window, "focused", False)),
        "window_rect": window_rect(native_window),
        "frame_rect": _widget_rect(getattr(native_window, "frame", None)),
        "tree_rect": tree_rect,
        "scroll_y": scroll_y,
        "row_height": row_height,
        "filter_text": (
            str(_safe_call("", filter_model.get_value_as_string))
            if filter_model is not None
            else ""
        ),
        "filter_rect": _widget_rect(getattr(layer_window, "_filter_border_rect", None)),
        "filter_clear_rect": _widget_rect(
            getattr(layer_window, "_filter_clear_button", None)
        ),
        "selected_keys": [row["key"] for row in rows if row["selected"]],
        "rows": rows,
        "controls": {
            "options": control(getattr(options, "_hit_rectangle", None)),
            "save_all": control(getattr(layer_window, "_save_all_button", None)),
            "insert": control(getattr(layer_window, "_insert_button", None)),
            "create": control(getattr(layer_window, "_create_button", None)),
            "delete": control(getattr(layer_window, "_delete_button", None)),
        },
        "context_menu": {
            "shown": menu_shown,
            "anchor": _json_value(
                getattr(context_builder, "_inspector_menu_anchor", None)
            ),
            "rect": _widget_rect(menu),
            "entries": menu_entries,
        },
        "open_file_dialog": open_file_dialog,
        "file_dialog": file_dialog,
        "confirm_dialog": confirm_dialog,
    }


def _layer_snapshot(adapter: Any) -> dict[str, Any]:
    if adapter is None:
        return {"available": False, "layers": {}}
    try:
        identifiers = list(adapter.get_layer_stack_identifiers(include_session=True))
    except Exception as exc:
        return {
            "available": False,
            "layers": {},
            "error": f"{type(exc).__name__}: {exc}",
        }
    layers: dict[str, Any] = {}
    for identifier in identifiers:
        layer = _safe_call(None, adapter.find_layer, identifier)
        if layer is None:
            continue
        layers[str(identifier)] = {
            "display_name": str(_safe_call("", adapter.get_display_name, layer)),
            "anonymous": bool(_safe_call(False, adapter.is_anonymous, layer)),
            "dirty": bool(_safe_call(False, adapter.is_dirty, layer)),
            "muted": bool(_safe_call(False, adapter.is_muted, layer)),
            "locked": bool(_safe_call(False, adapter.is_locked, layer)),
            "missing": bool(_safe_call(False, adapter.is_missing, layer)),
            "sublayers": [
                str(item)
                for item in _safe_call([], adapter.get_sublayer_identifiers, layer)
            ],
        }
    root = _safe_call(None, adapter.get_root_layer)
    return {
        "available": True,
        "root": str(getattr(root, "identifier", "")),
        "edit_target": str(_safe_call("", adapter.get_edit_target_identifier)),
        "identifiers": [str(identifier) for identifier in identifiers],
        "layers": layers,
    }


def _file_fingerprint(path: str) -> dict[str, Any]:
    if not path:
        return {"exists": False, "size": 0, "sha256": ""}
    file_path = Path(path)
    try:
        size = file_path.stat().st_size
        digest = hashlib.sha256()
        with file_path.open("rb") as stream:
            while chunk := stream.read(_FILE_HASH_CHUNK_SIZE):
                digest.update(chunk)
    except OSError:
        return {"exists": False, "size": 0, "sha256": ""}
    return {
        "exists": True,
        "size": int(size),
        "sha256": digest.hexdigest(),
    }


def _backing_layer_snapshot(
    stage: Any,
    scene: Any,
    evidence_provider: Any | None = None,
) -> dict[str, Any]:
    if stage is None:
        return {"available": False, "layers": {}}
    try:
        layer_stack = list(stage.GetLayerStack(includeSessionLayers=True))
    except Exception as exc:
        return {
            "available": False,
            "layers": {},
            "error": f"{type(exc).__name__}: {exc}",
        }
    source_layer = None
    if scene is not None:
        source_layer = _safe_call(None, lambda: scene.backing_usd_source_layer)

    logical_layers: list[Any] = []
    unresolved_sublayers: list[dict[str, str]] = []
    if source_layer is not None:
        try:
            pending = [source_layer]
            visited: set[str] = set()
            while pending:
                layer = pending.pop(0)
                identifier = str(getattr(layer, "identifier", ""))
                if not identifier or identifier in visited:
                    continue
                visited.add(identifier)
                logical_layers.append(layer)
                for raw_path in getattr(layer, "subLayerPaths", ()):
                    child = _find_relative_layer(
                        layer,
                        str(raw_path),
                        evidence_provider,
                    )
                    if child is None:
                        unresolved_sublayers.append(
                            {
                                "parent": identifier,
                                "path": str(raw_path),
                                "resolved": str(layer.ComputeAbsolutePath(str(raw_path))),
                            }
                        )
                        continue
                    pending.append(child)
        except Exception as exc:
            return {
                "available": False,
                "layers": {},
                "error": f"{type(exc).__name__}: {exc}",
            }
    else:
        logical_layers = list(layer_stack)

    all_layers: list[Any] = []
    seen_identifiers: set[str] = set()
    logical_identifiers = {
        str(getattr(layer, "identifier", ""))
        for layer in logical_layers
    }
    for layer in [*layer_stack, *logical_layers]:
        identifier = str(getattr(layer, "identifier", ""))
        if not identifier or identifier in seen_identifiers:
            continue
        seen_identifiers.add(identifier)
        all_layers.append(layer)

    layers: dict[str, Any] = {}
    for layer in all_layers:
        identifier = str(getattr(layer, "identifier", ""))
        real_path = str(getattr(layer, "realPath", ""))
        raw_sublayers = [str(path) for path in getattr(layer, "subLayerPaths", ())]
        resolved_sublayers = [
            str(_safe_call(path, layer.ComputeAbsolutePath, path))
            for path in raw_sublayers
        ]
        # OVStage's synthetic session/root layers contain the renderer runtime
        # graph and can be very large. They are intentionally hidden from the
        # logical Layers widget, so hashing them would add no parity evidence
        # and can stall every Inspector checkpoint. Fingerprint only the exact
        # provider-neutral stack exposed to the user.
        content = (
            str(_safe_call("", layer.ExportToString))
            if identifier in logical_identifiers
            else ""
        )
        content_bytes = content.encode("utf-8")
        layers[identifier] = {
            "identifier": identifier,
            "real_path": real_path,
            "anonymous": bool(getattr(layer, "anonymous", False)),
            "dirty": bool(getattr(layer, "dirty", False)),
            "permission_to_edit": bool(getattr(layer, "permissionToEdit", False)),
            "sublayers": raw_sublayers,
            "resolved_sublayers": resolved_sublayers,
            "content_size": len(content_bytes),
            "content_sha256": hashlib.sha256(content_bytes).hexdigest(),
            "file": _file_fingerprint(real_path),
        }
    root = _safe_call(None, stage.GetRootLayer)
    session_layer = _safe_call(None, stage.GetSessionLayer)
    edit_target = _safe_call(None, stage.GetEditTarget)
    edit_layer = _safe_call(None, edit_target.GetLayer) if edit_target is not None else None
    muted_identifiers = sorted(
        str(identifier)
        for identifier in _safe_call([], stage.GetMutedLayers)
    )
    return {
        "available": True,
        "identifiers": [str(getattr(layer, "identifier", "")) for layer in layer_stack],
        "logical_identifiers": [
            str(getattr(layer, "identifier", ""))
            for layer in logical_layers
        ],
        "muted_identifiers": muted_identifiers,
        "unresolved_sublayers": unresolved_sublayers,
        "root": str(getattr(root, "identifier", "")),
        "session": str(getattr(session_layer, "identifier", "")),
        "source": str(getattr(source_layer, "identifier", "")),
        "edit_target": str(getattr(edit_layer, "identifier", "")),
        "layers": layers,
    }


def _capability_value(capability: Any) -> dict[str, Any]:
    status = getattr(capability, "status", None)
    return {
        "status": str(_enum_value(status) or ""),
        "supported": bool(getattr(capability, "is_supported", False)),
        "read_only": bool(getattr(capability, "is_read_only", False)),
        "unsupported": bool(getattr(capability, "is_unsupported", False)),
        "reason": str(getattr(capability, "reason", "") or ""),
    }


def _capability_surface(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    return {
        name: _capability_value(capability)
        for name, capability in vars(value).items()
        if hasattr(capability, "status")
    }


def _capability_snapshot(app: Any) -> dict[str, Any]:
    session = getattr(app, "_adapter_session", None)
    get_provider_capabilities = getattr(session, "get_capabilities", None)
    provider = (
        _safe_call(None, get_provider_capabilities)
        if callable(get_provider_capabilities)
        else None
    )
    stage_capabilities = getattr(provider, "stage", None)
    layer_adapter = getattr(app, "_layer_adapter", None)
    layer_capabilities = (
        _safe_call(None, layer_adapter.get_capabilities)
        if layer_adapter is not None
        else None
    )
    return {
        "stage": _capability_surface(stage_capabilities),
        "layers": _capability_surface(layer_capabilities),
    }


def _create_catalog_snapshot(app: Any) -> dict[str, Any]:
    adapter = getattr(app, "_stage_adapter", None)
    selection = _selection_snapshot(app).get("paths", ())
    create_catalog = _safe_call(
        None,
        adapter.list_create_actions,
        selection_paths=selection,
    ) if callable(getattr(adapter, "list_create_actions", None)) else None
    material_catalog = _safe_call(
        None,
        adapter.list_core_materials,
        selection_paths=selection,
    ) if callable(getattr(adapter, "list_core_materials", None)) else None
    return {
        "selection_paths": [str(path) for path in selection],
        "create_actions": [
            {
                "id": str(getattr(action, "action_id", "")),
                "label": str(getattr(action, "label", "")),
                "category": str(getattr(action, "category_id", "")),
                "available": bool(getattr(action, "is_available", False)),
                "disabled_reason": str(getattr(action, "disabled_reason", "") or ""),
            }
            for action in (getattr(create_catalog, "actions", ()) or ())
        ],
        "bindable_selection_paths": [
            str(path)
            for path in (
                getattr(material_catalog, "bindable_selection_paths", ()) or ()
            )
        ],
        "materials": [
            {
                "id": str(getattr(material, "material_id", "")),
                "label": str(getattr(material, "label", "")),
                "available": bool(getattr(material, "is_available", False)),
                "can_bind": bool(getattr(material, "can_bind", False)),
                "disabled_reason": str(
                    getattr(material, "disabled_reason", "") or ""
                ),
            }
            for material in (getattr(material_catalog, "materials", ()) or ())
        ],
    }


def _menu_snapshot(app: Any) -> dict[str, Any]:
    top_levels: list[dict[str, Any]] = []
    for label, menu in (
        getattr(app, "_inspector_top_level_menus", {}) or {}
    ).items():
        rect = _widget_rect(menu)
        top_levels.append(
            {
                "label": str(label),
                "shown": bool(
                    getattr(menu, "shown", False)
                    or getattr(menu, "visible", False)
                ),
                "rect": rect,
                "point": _rect_point(rect),
            }
        )
    registry = getattr(app, "_menu_registry", None)
    geometry_fn = getattr(registry, "built_item_geometry", None)
    geometry = _safe_call((), geometry_fn) if callable(geometry_fn) else ()
    contributions: list[dict[str, Any]] = []
    available = getattr(registry, "_available_entries", None)
    for item in _safe_call((), available) if callable(available) else ():
        enabled = _safe_call(False, registry._enabled, item)
        contributions.append(
            {
                "id": str(getattr(item, "id", "") or ""),
                "label": str(getattr(item, "label", "") or ""),
                "parent_path": [
                    str(part) for part in (getattr(item, "parent_path", ()) or ())
                ],
                "kind": str(getattr(item, "kind", "") or ""),
                "enabled": bool(enabled),
                "widget_name": str(getattr(item, "widget_name", "") or ""),
            }
        )
    return {
        "top_levels": sorted(top_levels, key=lambda item: item["label"]),
        "contributions": sorted(contributions, key=lambda item: item["id"]),
        "built_items": _json_value(geometry),
        "failures": {
            str(key): f"{type(value).__name__}: {value}"
            for key, value in (getattr(registry, "failures", {}) or {}).items()
        } if registry is not None else {},
    }


def _component_snapshot(app: Any) -> dict[str, Any]:
    manager = getattr(app, "_component_manager", None)
    loaded: list[dict[str, Any]] = []
    for name, record in (getattr(manager, "_loaded", {}) or {}).items():
        handle = getattr(record, "handle", None)
        loaded.append(
            {
                "name": str(name),
                "entry_point": str(getattr(getattr(record, "entry_point", None), "value", "") or ""),
                "handle_type": type(handle).__name__ if handle is not None else "",
                "handle_present": handle is not None,
            }
        )
    failures = getattr(manager, "failures", {}) if manager is not None else {}
    return {
        "loaded_names": sorted(str(name) for name in (getattr(manager, "loaded_names", ()) or ())),
        "loaded": sorted(loaded, key=lambda item: item["name"]),
        "failures": {
            str(name): f"{type(exc).__name__}: {exc}"
            for name, exc in failures.items()
        },
    }


def _result_snapshot(result: Any) -> dict[str, Any] | None:
    if result is None:
        return None
    request = getattr(result, "active_request", None)
    return {
        "accepted": bool(getattr(result, "accepted", False)),
        "message": str(getattr(result, "message", "") or ""),
        "warning_code": str(getattr(result, "warning_code", "") or ""),
        "active_render_product_path": str(
            getattr(result, "active_render_product_path", "") or ""
        ),
        "active_camera_path": str(
            getattr(result, "active_camera_path", "") or ""
        ),
        "active_request": (
            {
                "viewport_id": str(getattr(request, "viewport_id", "") or ""),
                "render_product_path": str(
                    getattr(request, "render_product_path", "") or ""
                ),
                "output_id": str(getattr(request, "output_id", "") or ""),
                "render_var_name": str(
                    getattr(request, "render_var_name", "") or ""
                ),
            }
            if request is not None
            else None
        ),
    }


def _frame_metadata(frame: Any) -> dict[str, Any] | None:
    if frame is None:
        return None
    data = getattr(frame, "display_data", None)
    if data is None:
        data = getattr(frame, "coordinates", None)
    shape = getattr(data, "shape", None)
    warnings = tuple(getattr(frame, "warnings", ()) or ())
    return {
        "render_product_path": str(
            getattr(frame, "render_product_path", "") or ""
        ),
        "output_id": str(getattr(frame, "output_id", "") or ""),
        "render_var_name": str(getattr(frame, "render_var_name", "") or ""),
        "width": int(getattr(frame, "width", 0) or 0),
        "height": int(getattr(frame, "height", 0) or 0),
        "dtype": str(getattr(frame, "dtype", "") or ""),
        "component_count": int(getattr(frame, "component_count", 0) or 0),
        "point_count": int(getattr(frame, "point_count", 0) or 0),
        "valid_point_count": int(getattr(frame, "valid_point_count", 0) or 0),
        "frame_index": int(getattr(frame, "frame_index", 0) or 0),
        "stale": bool(getattr(frame, "stale", False)),
        "shape": [int(value) for value in shape] if shape is not None else [],
        "warning_count": len(warnings),
        "warnings": [
            {
                "code": str(getattr(warning, "code", "") or ""),
                "message": str(getattr(warning, "message", "") or ""),
                "severity": str(
                    _enum_value(getattr(warning, "severity", "")) or ""
                ),
            }
            for warning in warnings
        ],
    }


def _render_settings_window_snapshot(component: Any) -> dict[str, Any]:
    if component is None:
        return {"available": False, "window_visible": False, "rows": {}}
    context = _safe_call(None, component.target_context)
    window = getattr(component, "window", None)
    native_window = getattr(window, "_window", None)
    rows: dict[str, Any] = {}
    for attr_name, record in (
        getattr(window, "_inspector_provider_rows", {}) or {}
    ).items():
        row = record.get("row") if isinstance(record, dict) else None
        adapter = record.get("adapter") if isinstance(record, dict) else None
        widgets = list(getattr(row, "_widgets", ()) or ())
        if not widgets:
            widget = getattr(row, "_widget", None)
            if widget is not None:
                widgets = [widget]
        rects = [_widget_rect(widget) for widget in widgets]
        metadata = _safe_call(None, adapter.get_attribute_metadata, attr_name)
        indicator = getattr(row, "_indicator", None)
        indicator_widget = getattr(indicator, "widget", None)
        row_widget = getattr(row, "_row_hstack", None)
        row_rect = _widget_rect(row_widget)
        context_menu = getattr(row, "_active_context_menu", None)
        try:
            from ovui_widgets.property.parts.attr_context_menu import (
                inspector_menu_items,
            )

            raw_context_items = inspector_menu_items(context_menu)
        except Exception:
            raw_context_items = ()
        context_items: list[dict[str, Any]] = []
        for item_id, label, enabled, widget in raw_context_items:
            item_rect = _widget_rect(widget)
            context_items.append(
                {
                    "id": str(item_id),
                    "label": str(label),
                    "enabled": bool(enabled),
                    "rect": item_rect,
                    "point": _rect_point(item_rect),
                }
            )
        rows[str(attr_name)] = {
            "provider_id": str(record.get("provider_id", "")),
            "display_name": str(getattr(metadata, "display_name", "") or ""),
            "type_name": str(getattr(metadata, "type_name", "") or ""),
            "group": str(getattr(metadata, "group", "") or ""),
            "value": _json_value(_safe_call(None, adapter.get_value, attr_name)),
            "field_rects": rects,
            "field_points": [
                point for point in (_rect_point(rect) for rect in rects) if point is not None
            ],
            "field_enabled": [
                bool(getattr(widget, "enabled", True)) for widget in widgets
            ],
            "indicator_rect": _widget_rect(indicator_widget),
            "indicator_point": _rect_point(_widget_rect(indicator_widget)),
            "row_rect": row_rect,
            "context_menu_point": _rect_point(row_rect),
            "context_menu": {
                "shown": bool(
                    getattr(context_menu, "shown", False)
                    or getattr(context_menu, "visible", False)
                ),
                "rect": _widget_rect(context_menu),
                "items": context_items,
            },
        }
    window_rect = _widget_rect(native_window)
    return {
        "available": context is not None,
        "active_render_product_path": str(
            getattr(context, "render_product_path", "") or ""
        ),
        "window_created": window is not None,
        "window_visible": bool(getattr(native_window, "visible", False)),
        "window_rect": window_rect,
        "window_point": _rect_point(window_rect),
        "rows": rows,
    }


def _physics_snapshot(app: Any) -> dict[str, Any]:
    session = getattr(app, "_adapter_session", None)
    controls = getattr(session, "physics_controls", None)
    if controls is None:
        return {"available": False}
    failure = getattr(controls, "last_failure", None)
    return {
        "available": True,
        "enabled": bool(getattr(controls, "enabled", False)),
        "playing": bool(getattr(controls, "playing", False)),
        "has_physics_scene": bool(
            getattr(controls, "has_physics_scene", False)
        ),
        "can_toggle_enabled": bool(
            _safe_call(False, getattr(controls, "can_toggle_enabled", None))
        ),
        "can_toggle_playing": bool(
            _safe_call(False, getattr(controls, "can_toggle_playing", None))
        ),
        "enable_label": str(
            _safe_call("", getattr(controls, "enable_label", None))
        ),
        "play_label": str(
            _safe_call("", getattr(controls, "play_label", None))
        ),
        "simulation_time": float(
            getattr(controls, "simulation_time", 0.0) or 0.0
        ),
        "pose_paths": [
            str(path) for path in (getattr(controls, "_pose_paths", ()) or ())
        ],
        "pose_write_ordinals": [
            int(value)
            for value in (getattr(controls, "_pose_write_ordinals", ()) or ())
        ],
        "last_failure": (
            {
                "provider_name": str(getattr(failure, "provider_name", "") or ""),
                "operation": str(getattr(failure, "operation", "") or ""),
                "scene_path": str(getattr(failure, "scene_path", "") or ""),
                "exception_type": str(
                    getattr(failure, "exception_type", "") or ""
                ),
                "exception_text": str(
                    getattr(failure, "exception_text", "") or ""
                ),
            }
            if failure is not None
            else None
        ),
    }


def _tap_snapshot(tap: Any) -> dict[str, Any]:
    if tap is None:
        return {"present": False}
    status = _safe_call(("", 0, None), tap.status)
    return {
        "present": True,
        "type": type(tap).__name__,
        "state": str(status[0] or ""),
        "clients": int(status[1] or 0),
        "last_error": str(status[2] or ""),
        "protocol": str(getattr(tap, "protocol", "") or ""),
        "signal_port": int(getattr(tap, "signal_port", 0) or 0),
        "media_port": int(getattr(tap, "media_port", 0) or 0),
        "server_present": getattr(tap, "_server", None) is not None,
        "disabled": bool(getattr(tap, "_disabled", False)),
        "frames_pushed": int(getattr(tap, "_frames_pushed", 0) or 0),
        "frames_skipped": int(getattr(tap, "_frames_skipped", 0) or 0),
        "tee_attempts": int(getattr(tap, "_tee_attempts", 0) or 0),
        "cuda_ring_size": len(getattr(tap, "_scratch_ring", ()) or ()),
        "linear_ring_size": len(getattr(tap, "_linear_ring", ()) or ()),
        "input_bridge_present": getattr(tap, "_input_bridge", None) is not None,
        "closed": bool(getattr(tap, "_closed", False)),
        "close_count": int(getattr(tap, "_close_count", 0) or 0),
    }


def _livestream_snapshot(app: Any, renderer: Any) -> dict[str, Any]:
    viewport = getattr(app, "_viewport_window", None)
    viewport_state_fn = getattr(viewport, "get_viewport_state_snapshot", None)
    viewport_state = (
        _safe_call(None, viewport_state_fn)
        if callable(viewport_state_fn)
        else None
    )
    hud = getattr(viewport_state, "hud", None)
    return {
        "headless_export_active": bool(
            getattr(app, "_headless_export_active", False)
        ),
        "headless_export_disable_logged": bool(
            getattr(app, "_headless_export_disable_logged", False)
        ),
        "headless": _tap_snapshot(getattr(app, "_headless_tap", None)),
        "windowed": _tap_snapshot(getattr(renderer, "_livestream", None)),
        "hud": {
            "state": str(getattr(hud, "stream_state", "") or ""),
            "clients": int(getattr(hud, "stream_clients", 0) or 0),
            "last_error": str(getattr(hud, "stream_last_error", "") or ""),
            "text": str(getattr(hud, "stream_text", "") or ""),
            "tooltip": str(getattr(hud, "stream_tooltip", "") or ""),
        },
    }


def _renderer_snapshot(app: Any, scene: Any) -> dict[str, Any]:
    viewport = getattr(app, "_viewport_window", None)
    renderer = getattr(viewport, "_renderer", None)
    if renderer is None:
        return {"available": False}
    native_renderer = getattr(renderer, "_renderer", None)
    config = getattr(native_renderer, "config", None)
    attach_mode = getattr(config, "attach_mode", None)
    ovrtx_module = getattr(renderer, "_ovrtx", None)
    borrow_mode = getattr(getattr(ovrtx_module, "AttachMode", None), "BORROW", None)
    attached_stage = getattr(renderer, "_attached_stage", None)
    native_stage = getattr(scene, "_stage", None) if scene is not None else None
    # The native renderer retains the borrowed Stage object it was attached
    # to (attach_ovstage borrow contract); identity against the provider's
    # own stage is live native-attachment proof independent of the adapter's
    # bookkeeping.
    native_attached_stage = getattr(native_renderer, "_attached_ovstage", None)
    native_attachment = (
        native_stage is not None and native_attached_stage is native_stage
    )
    if attach_mode is not None:
        # Older/other wheels: a public config field is the direct source.
        attach_mode_report = str(_enum_value(attach_mode))
        attach_mode_source = "config.attach_mode"
        is_borrow_mode = borrow_mode is not None and attach_mode == borrow_mode
    elif native_attachment:
        # Current wheels expose no public attach-mode enum or config field.
        # attach_ovstage is the only public attachment API and its contract
        # is borrowing the externally owned Stage; the live identity above
        # proves this renderer holds exactly the provider-owned instance.
        attach_mode_report = "borrow"
        attach_mode_source = "native_attach_ovstage"
        is_borrow_mode = True
    else:
        attach_mode_report = ""
        attach_mode_source = "unavailable"
        is_borrow_mode = False
    return {
        "available": True,
        "adapter_class": type(renderer).__name__,
        "native_class": type(native_renderer).__name__ if native_renderer is not None else "",
        "attach_mode": attach_mode_report,
        "attach_mode_source": attach_mode_source,
        "is_borrow_mode": is_borrow_mode,
        "attached_exact_ovstage": (
            native_stage is not None and attached_stage is native_stage
        ),
        "native_attached_exact_ovstage": native_attachment,
        "borrow_step_count": int(getattr(renderer, "_borrow_step_count", 0) or 0),
        "borrow_suspend_count": int(
            getattr(renderer, "_borrow_suspend_count", 0) or 0
        ),
        "borrow_resume_count": int(
            getattr(renderer, "_borrow_resume_count", 0) or 0
        ),
        "scene_attached_renderer_count": len(
            getattr(scene, "_attached_renderers", ()) or ()
        ) if scene is not None else 0,
        "successful_frame_count": int(
            getattr(renderer, "_successful_frame_count", 0) or 0
        ),
        "last_frame_shape": _json_value(
            getattr(renderer, "_last_frame_shape", None)
        ),
        "last_frame_nonblack_pixels": getattr(
            renderer, "_last_frame_nonblack_pixels", None
        ),
        "selection_outline_attribute_writes": int(
            getattr(renderer, "_selection_outline_attribute_writes", 0) or 0
        ),
        "live_preview_write_count": int(
            getattr(renderer, "_live_preview_write_count", 0) or 0
        ),
        "live_preview_clear_count": int(
            getattr(renderer, "_live_preview_clear_count", 0) or 0
        ),
        "live_preview_paths": sorted(
            str(path)
            for path in (getattr(renderer, "_live_preview_paths", ()) or ())
        ),
        "last_live_preview_path": str(
            getattr(renderer, "_last_live_preview_path", "") or ""
        ),
        "last_live_preview_matrix": _json_value(
            getattr(renderer, "_last_live_preview_matrix", None)
        ),
        "active_render_product_path": str(
            _safe_call(
                "",
                getattr(renderer, "get_active_render_product_path", None),
            )
        ),
        "active_camera_path": str(
            _safe_call(
                "",
                getattr(renderer, "get_active_camera_path", None),
            )
            or ""
        ),
        "native_render_product_path": str(
            getattr(renderer, "_render_product_path", "") or ""
        ),
        "render_product_resolution": _json_value(
            getattr(renderer, "_last_render_product_resolution", None)
        ),
        "pick_enqueue_count": int(
            getattr(renderer, "_pick_enqueue_count", 0) or 0
        ),
        "pick_result_count": int(
            getattr(renderer, "_pick_result_count", 0) or 0
        ),
        "last_pick_kind": str(
            getattr(renderer, "_last_pick_kind", "") or ""
        ),
        "last_pick_query_name": str(
            getattr(renderer, "_last_pick_query_name", "") or ""
        ),
        "last_pick_pixel_rect": _json_value(
            getattr(renderer, "_last_pick_pixel_rect", None)
        ),
        "last_pick_path": str(getattr(renderer, "_last_pick_path", "") or ""),
        "last_pick_paths": [
            str(path) for path in (getattr(renderer, "_last_pick_paths", ()) or ())
        ],
        "last_pick_world_point": _json_value(
            getattr(renderer, "_last_pick_world_point", None)
        ),
        "in_flight_pick_count": len(
            getattr(renderer, "_in_flight_pick_queries", ()) or ()
        ),
        "selected_paths": [
            str(path) for path in (getattr(renderer, "_selected_paths", ()) or ())
        ],
        # Current outline membership as tracked by the adapter. No generic
        # capability claim is reported here: transport support differs per
        # provider/runtime (dedicated API on ovrtx 0.4, legacy attribute path
        # on older ovrtx) and a single flag misrepresented working legacy
        # outlines as unsupported.
        "selection_outline": {
            "applied_paths": sorted(
                str(path)
                for path in (
                    getattr(renderer, "_selection_outline_previous_paths", ()) or ()
                )
            ),
        },
        "point_cloud_request_count": len(
            getattr(renderer, "_point_cloud_requests", {}) or {}
        ),
        "point_cloud_frame_count": len(
            getattr(renderer, "_latest_point_cloud_frames", {}) or {}
        ),
        "point_cloud_background_fallback_count": int(
            getattr(renderer, "_point_cloud_background_fallback_count", 0) or 0
        ),
        "render_var_request_count": len(
            getattr(renderer, "_render_var_output_requests", {}) or {}
        ),
        "render_var_frame_count": len(
            getattr(renderer, "_latest_render_var_output_frames", {}) or {}
        ),
        "livestream_zero_copy_tee_attempt_count": int(
            getattr(renderer, "_livestream_zero_copy_tee_attempt_count", 0) or 0
        ),
        "livestream_zero_copy_tee_success_count": int(
            getattr(renderer, "_livestream_zero_copy_tee_success_count", 0) or 0
        ),
        "livestream_cuda_tee_and_d2h_count": int(
            getattr(renderer, "_livestream_cuda_tee_and_d2h_count", 0) or 0
        ),
        "livestream_cpu_presentation_count": int(
            getattr(renderer, "_livestream_cpu_presentation_count", 0) or 0
        ),
        "zero_copy": {
            "mode": str(
                _enum_value(
                    getattr(getattr(renderer, "_zero_copy_state", None), "mode", "")
                )
                or ""
            ),
            "enabled": bool(
                getattr(getattr(renderer, "_zero_copy_state", None), "enabled", False)
            ),
            "fallback_reason": str(
                getattr(
                    getattr(renderer, "_zero_copy_state", None),
                    "fallback_reason",
                    "",
                )
                or ""
            ),
        },
    }


def _viewport_snapshot(
    app: Any,
    usd_snapshot: dict[str, Any],
    native_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture stable viewport geometry used to target real Inspector input.

    Projection targets come from the USD view when one exists; a native-only
    OVStage session has no USD view, so the committed native user paths are
    the projection source (bounds still come from the provider's own
    ``compute_world_aabb``).
    """

    viewport = getattr(app, "_viewport_window", None)
    image = getattr(viewport, "_image", None)
    camera = getattr(viewport, "_camera", None)
    if viewport is None or image is None:
        return {"available": False, "prim_screen_centers": {}}
    width = int(getattr(image, "computed_width", 0) or 0)
    height = int(getattr(image, "computed_height", 0) or 0)
    if width <= 0 or height <= 0:
        width, height = _safe_call((0, 0), viewport._get_viewport_size)
        width, height = int(width), int(height)
    image_rect = {
        "x": float(getattr(image, "screen_position_x", 0.0) or 0.0),
        "y": float(getattr(image, "screen_position_y", 0.0) or 0.0),
        "width": width,
        "height": height,
    }
    screen_centers: dict[str, list[int]] = {}
    stage_adapter = getattr(app, "_stage_adapter", None)
    compute_bounds = getattr(stage_adapter, "compute_world_aabb", None)
    projection_source = _usd_user_paths(usd_snapshot)
    if not projection_source and (native_snapshot or {}).get("available"):
        projection_source = _native_user_paths(native_snapshot or {})
    if camera is not None and callable(compute_bounds) and width > 0 and height > 0:
        try:
            import numpy as np

            view, projection = camera.get_matrices(width, height)
            view_array = np.asarray(view)
            projection_array = np.asarray(projection)
            projection_paths = sorted(projection_source)[
                :_MAX_VIEWPORT_PROJECTION_PATHS
            ]
            for path in projection_paths:
                bounds = _safe_call(None, compute_bounds, [path])
                if not bounds:
                    continue
                minimum, maximum = bounds
                world = np.array(
                    [
                        (float(minimum[0]) + float(maximum[0])) * 0.5,
                        (float(minimum[1]) + float(maximum[1])) * 0.5,
                        (float(minimum[2]) + float(maximum[2])) * 0.5,
                        1.0,
                    ]
                )
                clip = projection_array @ (view_array @ world)
                if abs(float(clip[3])) < 1.0e-6:
                    continue
                ndc = clip[:3] / clip[3]
                x = image_rect["x"] + (float(ndc[0]) + 1.0) * 0.5 * width
                y = image_rect["y"] + (1.0 - float(ndc[1])) * 0.5 * height
                if (
                    image_rect["x"] <= x < image_rect["x"] + width
                    and image_rect["y"] <= y < image_rect["y"] + height
                ):
                    screen_centers[str(path)] = [int(round(x)), int(round(y))]
        except Exception:
            screen_centers = {}
    handle_fn = getattr(viewport, "get_streamed_transform_handle_projections", None)
    handle_projection = (
        _safe_call(
            {"available": False},
            lambda: handle_fn(width=width, height=height),
        )
        if callable(handle_fn)
        else {"available": False}
    )
    viewport_state_fn = getattr(viewport, "get_viewport_state_snapshot", None)
    viewport_state = (
        _safe_call(None, viewport_state_fn)
        if callable(viewport_state_fn)
        else None
    )
    camera_button = (getattr(viewport, "_toolbar_buttons", {}) or {}).get("camera")
    camera_button_rect = _widget_rect(camera_button)
    camera_menu = getattr(viewport, "_camera_menu", None)
    camera_menu_items: list[dict[str, Any]] = []
    for path, label, enabled, widget in (
        getattr(viewport, "_camera_menu_items", ()) or ()
    ):
        rect = _widget_rect(widget)
        camera_menu_items.append(
            {
                "path": str(path),
                "label": str(label),
                "enabled": bool(enabled),
                "rect": rect,
                "point": _rect_point(rect),
            }
        )
    hud = getattr(viewport_state, "hud", None)
    return {
        "available": width > 0 and height > 0,
        "image_rect": image_rect,
        "prim_screen_centers": screen_centers,
        "projection_path_limit": _MAX_VIEWPORT_PROJECTION_PATHS,
        "projection_paths_truncated": (
            len(projection_source) > _MAX_VIEWPORT_PROJECTION_PATHS
        ),
        "transform_handles": _json_value(handle_projection),
        "active_tool": str(getattr(viewport_state, "active_tool", "") or ""),
        "tools": [
            {
                "id": str(getattr(tool, "id", "") or ""),
                "label": str(getattr(tool, "label", "") or ""),
                "active": bool(getattr(tool, "active", False)),
                "enabled": bool(getattr(tool, "enabled", False)),
            }
            for tool in (getattr(viewport_state, "tools", ()) or ())
        ],
        "cameras": [
            {
                "path": str(getattr(camera_state, "path", "") or ""),
                "label": str(getattr(camera_state, "label", "") or ""),
                "active": bool(getattr(camera_state, "active", False)),
            }
            for camera_state in (getattr(viewport_state, "cameras", ()) or ())
        ],
        "active_camera_path": str(
            getattr(viewport_state, "active_camera_path", "") or ""
        ),
        "camera_button": {
            "rect": camera_button_rect,
            "point": _rect_point(camera_button_rect),
            "enabled": bool(getattr(camera_button, "enabled", False)),
        },
        "camera_menu": {
            "shown": bool(
                getattr(camera_menu, "shown", False)
                or getattr(camera_menu, "visible", False)
            ),
            "rect": _widget_rect(camera_menu),
            "items": camera_menu_items,
        },
        "toolbar_contributions": [
            {
                "id": str(getattr(item, "id", "") or ""),
                "label": str(getattr(item, "label", "") or ""),
                "kind": str(getattr(item, "kind", "") or ""),
                "enabled": bool(getattr(item, "enabled", False)),
                "widget_name": str(getattr(item, "widget_name", "") or ""),
                "text": str(getattr(item, "text", "") or ""),
            }
            for item in (
                getattr(viewport_state, "toolbar_contributions", ()) or ()
            )
        ],
        "hud": {
            "scene": str(getattr(hud, "scene", "") or ""),
            "fps": _json_value(getattr(hud, "fps", None)),
            "resolution": _json_value(getattr(hud, "resolution", None)),
            "stream_state": str(getattr(hud, "stream_state", "") or ""),
            "stream_clients": int(getattr(hud, "stream_clients", 0) or 0),
            "stream_text": str(getattr(hud, "stream_text", "") or ""),
            "stream_tooltip": str(getattr(hud, "stream_tooltip", "") or ""),
        },
    }


def _is_runtime_implementation_path(path: str) -> bool:
    value = str(path)
    if value == "/":
        return True
    return any(
        value == root or value.startswith(f"{root}/")
        for root in _CONDITIONAL_RUNTIME_ROOTS
    )


def _usd_user_paths(usd_snapshot: dict[str, Any]) -> set[str]:
    return {
        str(path)
        for path, prim in usd_snapshot.get("prims", {}).items()
        if str(path) != "/"
        and not bool(prim.get("runtime_owned"))
        and (
            not _is_runtime_implementation_path(str(path))
            or bool(prim.get("source_authored"))
        )
    }


def _native_user_paths(native_snapshot: dict[str, Any]) -> set[str]:
    """User-scene paths from the native OVStage view (no USD view exists).

    Ownership comes from the snapshot's per-prim ``user_facing`` records,
    which the provider's own ``inspector_user_facing_scene_path`` rule
    produced — no second path-classification policy is applied here.
    Prims without a recorded classification (the ownership rule was
    unavailable or failed) are excluded: fail closed rather than guess.
    """
    return {
        str(path)
        for path, record in native_snapshot.get("prims", {}).items()
        if str(path) != "/" and bool(record.get("user_facing"))
    }


def _bridge_identity_snapshot(
    stage: Any,
    scene: Any,
    evidence_provider: Any | None = None,
) -> dict[str, Any]:
    """Prove shared stage identity when a provider exposes both scene views.

    A backing-USD bridge exists only when the active provider exposes both a
    native OVStage scene and a backing USD stage. The native-only provider has
    no backing stage and the standalone OpenUSD provider has no native scene;
    neither has a bridge to prove, so identity evidence is not required for
    them. When both views exist, the evidence remains fail-closed.
    """

    if stage is None or scene is None:
        return {
            "required": False,
            "available": False,
            "matches": True,
            "note": "no backing-USD bridge exists for the active provider",
        }
    reader = getattr(evidence_provider, "inspector_bridge_identity", None)
    if not callable(reader):
        return {
            "required": True,
            "available": False,
            "matches": False,
            "error": "active provider exposes no backing-stage identity evidence",
        }
    result = _safe_call(None, reader, stage, scene)
    if not isinstance(result, dict):
        return {
            "required": True,
            "available": False,
            "matches": False,
            "error": "provider returned invalid backing-stage identity evidence",
        }
    return result


def _native_topology_parity(
    ovstage_snapshot: dict[str, Any],
    adapter_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Compare adapter types and hierarchy against native OVStage records.

    Used when the native OVStage view is the authoritative baseline (no USD
    view exists). Every path shared by the native and adapter views is
    compared by type name, and each native prim's recorded ordered children
    are compared against the adapter's child list for the same path, so
    equal-path type drift and child-order/hierarchy drift both fail instead
    of passing vacuously.
    """

    native_prims = ovstage_snapshot.get("prims", {})
    adapter_prims = adapter_snapshot.get("prims", {})
    child_topology = ovstage_snapshot.get("child_topology") or {}
    authority_available = bool(child_topology.get("available"))
    authority_errors = list(child_topology.get("errors", ()))
    # Only user-facing native prims (per the production ownership rule
    # recorded at capture time) participate: renderer-owned presentation
    # content that the adapter rightly hides must not read as drift.
    shared_paths = sorted(
        path
        for path in set(native_prims) & set(adapter_prims)
        if path != "/" and native_prims.get(path, {}).get("user_facing", True)
    )
    adapter_type_mismatches: list[dict[str, str]] = []
    child_order_mismatches: list[dict[str, Any]] = []

    def adapter_children_for(path: str) -> list[str]:
        record = adapter_prims.get(path, {})
        return [
            str(child) for child in record.get("children", ()) if str(child) != "/"
        ]

    for path in shared_paths:
        native_record = native_prims.get(path, {})
        adapter_record = adapter_prims.get(path, {})
        native_type = str(native_record.get("type_name", ""))
        adapter_type = str(adapter_record.get("type_name", ""))
        if adapter_type != native_type:
            adapter_type_mismatches.append(
                {"path": path, "ovstage": native_type, "adapter": adapter_type}
            )
        if authority_available:
            # Native children are kept verbatim (runtime-implementation paths
            # excluded at capture time): a child the native scene reports but
            # the adapter does not — or vice versa — is hierarchy drift, not
            # something to filter away.
            native_children = [
                str(child) for child in native_record.get("children", ())
            ]
            if adapter_children_for(path) != native_children:
                child_order_mismatches.append(
                    {
                        "path": path,
                        "ovstage": native_children,
                        "adapter": adapter_children_for(path),
                    }
                )
    if authority_available:
        # The pseudo-root's ordered top-level children come from the native
        # root query convention (get_child_paths("")) and are compared against
        # the adapter's root children.
        native_root_children = [
            str(child) for child in child_topology.get("root_children", ())
        ]
        adapter_root_children = adapter_children_for("/")
        if adapter_root_children != native_root_children:
            child_order_mismatches.append(
                {
                    "path": "/",
                    "ovstage": native_root_children,
                    "adapter": adapter_root_children,
                }
            )
    return {
        "compared_path_count": len(shared_paths),
        "adapter_type_mismatches": adapter_type_mismatches,
        "native_type_mismatches": [],
        "representation_fallbacks": [],
        "child_order_mismatches": child_order_mismatches,
        # Fail closed: without a working native child-enumeration authority
        # there is no basis to affirm hierarchy parity, regardless of the
        # type comparison outcome.
        "child_topology_available": authority_available,
        "authority_errors": authority_errors,
        "matches": (
            authority_available
            and not (adapter_type_mismatches or child_order_mismatches)
        ),
    }


def _topology_value_parity(
    usd_snapshot: dict[str, Any],
    ovstage_snapshot: dict[str, Any],
    adapter_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Compare hierarchy order/types in addition to the existing path sets.

    With a USD view present, USD is the baseline (existing behavior). With a
    native-only session, the comparison is delegated to
    :func:`_native_topology_parity` so native topology evidence is never
    vacuous.
    """

    if not usd_snapshot.get("available") and ovstage_snapshot.get("available"):
        return _native_topology_parity(ovstage_snapshot, adapter_snapshot)

    usd_paths = _usd_user_paths(usd_snapshot)
    usd_prims = usd_snapshot.get("prims", {})
    adapter_prims = adapter_snapshot.get("prims", {})
    native_prims = ovstage_snapshot.get("prims", {})
    adapter_type_mismatches: list[dict[str, str]] = []
    native_type_mismatches: list[dict[str, str]] = []
    representation_fallbacks: list[dict[str, str]] = []
    child_order_mismatches: list[dict[str, Any]] = []

    normalized_to_xform = {"Scope", "PhysicsScene"}

    def user_children(record: dict[str, Any]) -> list[str]:
        return [str(path) for path in record.get("children", ()) if str(path) in usd_paths]

    for path in sorted(usd_paths):
        usd_record = usd_prims.get(path, {})
        adapter_record = adapter_prims.get(path, {})
        native_record = native_prims.get(path, {})
        usd_type = str(usd_record.get("type_name", ""))
        adapter_type = str(adapter_record.get("type_name", ""))
        adapter_type_matches = adapter_type == usd_type
        if adapter_record and not adapter_type_matches:
            adapter_type_mismatches.append(
                {"path": path, "usd": usd_type, "adapter": adapter_type}
            )
        native_type = str(native_record.get("type_name", ""))
        # OVStage normalizes non-rendering container schemas to its
        # renderer-facing Xform representation. Record the fallback explicitly
        # so parity accepts the known representation without hiding it.
        unregistered_typed_schema = bool(usd_type) and not bool(
            usd_record.get("schema_registered", False)
        )
        native_fallback = native_type == "Xform" and (
            usd_type in normalized_to_xform or unregistered_typed_schema
        )
        native_type_matches = native_type == usd_type or native_fallback
        if native_fallback:
            representation_fallbacks.append(
                {
                    "path": path,
                    "usd": usd_type,
                    "ovstage": native_type,
                    "reason": (
                        "unregistered USD typed schema normalized to OVStage Xform"
                        if unregistered_typed_schema
                        else "OVStage renderer-facing Xform normalization"
                    ),
                }
            )
        if native_record and not native_type_matches:
            native_type_mismatches.append(
                {"path": path, "usd": usd_type, "ovstage": native_type}
            )
        usd_children = user_children(usd_record)
        adapter_children = user_children(adapter_record)
        if adapter_record and usd_children != adapter_children:
            child_order_mismatches.append(
                {"path": path, "usd": usd_children, "adapter": adapter_children}
            )
    return {
        "compared_path_count": len(usd_paths),
        "adapter_type_mismatches": adapter_type_mismatches,
        "native_type_mismatches": native_type_mismatches,
        "representation_fallbacks": representation_fallbacks,
        "child_order_mismatches": child_order_mismatches,
        "matches": not (
            adapter_type_mismatches
            or native_type_mismatches
            or child_order_mismatches
        ),
    }


def _attribute_value_parity(
    usd_snapshot: dict[str, Any],
    ovstage_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Compare every native attribute value that has an exact USD peer.

    The native query exposes hashes for opaque payloads and decoded values for
    the renderer-facing scalar/token subset.  Opaque bytes are intentionally
    not guessed at.  This comparison therefore reports both the number of
    independently comparable values and every decoded mismatch.
    """

    compared: list[str] = []
    gaps: list[str] = []
    path_target_compared: list[str] = []
    path_target_gaps: list[str] = []
    unsupported_path_target_gaps: list[dict[str, str]] = []
    mismatches: list[dict[str, Any]] = []
    usd_prims = usd_snapshot.get("prims", {})
    native_prims = ovstage_snapshot.get("prims", {})
    for path in sorted(_usd_user_paths(usd_snapshot) & set(native_prims)):
        usd_attributes = usd_prims.get(path, {}).get("attributes", {})
        usd_relationships = usd_prims.get(path, {}).get("relationships", {})
        native_attributes = native_prims.get(path, {}).get("attributes", {})
        expected_path_targets: dict[str, list[str]] = {
            str(name): [str(value) for value in record.get("targets", ())]
            for name, record in usd_relationships.items()
            if record.get("targets")
        }
        expected_path_targets.update(
            {
                str(name): [str(value) for value in record.get("connections", ())]
                for name, record in usd_attributes.items()
                if record.get("connections")
            }
        )
        for name, native_record in sorted(native_attributes.items()):
            if name in _NATIVE_MATRIX_ATTRIBUTES or name in {
                # OVStage's renderer-facing ``purpose`` classification uses
                # ``geometry`` for ordinary prims where USD composes the
                # schema fallback ``default``. It is derived routing data, not
                # the authored USD purpose opinion.
                "purpose",
                "worldVisibility",
            }:
                continue
            key = f"{path}.{name}"
            if "path_targets" in native_record:
                expected = expected_path_targets.pop(name, None)
                if expected is None:
                    path_target_gaps.append(key)
                    continue
                observed = [str(value) for value in native_record["path_targets"]]
                path_target_compared.append(key)
                compared.append(key)
                if observed != expected:
                    mismatches.append(
                        {
                            "key": key,
                            "usd": expected,
                            "ovstage": observed,
                            "kind": "path_targets",
                        }
                    )
                continue
            if (
                name in expected_path_targets
                and usd_prims.get(path, {}).get("type_name") == "Material"
                and name in _OVSTAGE_01_UNREADABLE_MATERIAL_OUTPUT_CONNECTIONS
            ):
                # Keep the expected target pending so it is recorded below as
                # the narrowly-scoped OVStage 0.1 public-read limitation. If a
                # later runtime exposes path_targets, the branch above compares
                # it exactly and this exception disappears automatically.
                continue
            if name not in usd_attributes:
                continue
            usd_record = usd_attributes[name]
            if name == "extent":
                usd_fingerprint = usd_prims.get(path, {}).get(
                    "computed_extent_fingerprint"
                )
            else:
                usd_fingerprint = usd_record.get("numeric_fingerprint")
            if "value" in native_record:
                usd_value = usd_record.get("value")
                native_value = native_record.get("value")
                compared.append(key)
                if _values_close(usd_value, native_value):
                    continue
                mismatches.append(
                    {
                        "key": key,
                        "usd": usd_value,
                        "ovstage": native_value,
                    }
                )
                continue
            native_bytes = int(native_record.get("bytes", 0) or 0)
            if (
                isinstance(usd_fingerprint, dict)
                and usd_fingerprint.get("complete") is True
                and int(usd_fingerprint.get("bytes", 0) or 0) == native_bytes
                and native_bytes > 0
            ):
                compared.append(key)
                if usd_fingerprint.get("sha256") != native_record.get("sha256"):
                    mismatches.append(
                        {
                            "key": key,
                            "usd": usd_fingerprint,
                            "ovstage": {
                                "bytes": native_bytes,
                                "sha256": native_record.get("sha256", ""),
                            },
                        }
                    )
                continue
            gaps.append(key)
        for name in sorted(expected_path_targets):
            key = f"{path}.{name}"
            if (
                usd_prims.get(path, {}).get("type_name") == "Material"
                and name in _OVSTAGE_01_UNREADABLE_MATERIAL_OUTPUT_CONNECTIONS
            ):
                unsupported_path_target_gaps.append(
                    {
                        "key": key,
                        "reason": _OVSTAGE_01_MATERIAL_OUTPUT_CONNECTION_REASON,
                    }
                )
            else:
                path_target_gaps.append(key)
    return {
        "compared_count": len(compared),
        "compared": compared,
        "gaps": gaps,
        "complete": not gaps,
        "path_target_compared": path_target_compared,
        "path_target_gaps": path_target_gaps,
        "unsupported_path_target_gaps": unsupported_path_target_gaps,
        "path_targets_complete": not path_target_gaps,
        "mismatches": mismatches,
        "matches": not mismatches and not path_target_gaps,
    }


def _layer_state_parity(
    layer_snapshot: dict[str, Any],
    backing_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Compare the provider-neutral Layers view with exact backing USD layers.

    The comparison applies only when a provider exposes both views. The
    native-only provider has neither a logical layer stack nor backing USD
    layers, so there is nothing to compare and the parity is vacuously true;
    exactly one side being available remains a fail-closed mismatch.
    """

    layers_available = bool(layer_snapshot.get("available"))
    backing_available = bool(backing_snapshot.get("available"))
    if not layers_available and not backing_available:
        return {
            "comparable": False,
            "matches": True,
            "missing_in_backing": [],
            "missing_in_adapter": [],
            "sublayer_mismatches": [],
            "flag_mismatches": [],
            "adapter_muted": [],
            "backing_muted": [],
            "muted_matches": True,
            "root_matches": True,
            "edit_target_matches": True,
        }
    if not layers_available or not backing_available:
        return {
            "comparable": False,
            "matches": False,
            "missing_in_backing": [],
            "missing_in_adapter": [],
            "sublayer_mismatches": [],
            "flag_mismatches": [],
            "adapter_muted": [],
            "backing_muted": [],
            "muted_matches": False,
            "root_matches": False,
            "edit_target_matches": False,
        }
    adapter_ids = [str(value) for value in layer_snapshot.get("identifiers", ())]
    backing_layers = backing_snapshot.get("layers", {})
    backing_ids = [
        str(value)
        for value in backing_snapshot.get(
            "logical_identifiers",
            backing_snapshot.get("identifiers", ()),
        )
    ]
    adapter_id_set = set(adapter_ids)
    backing_id_set = set(backing_ids)
    missing = sorted(adapter_id_set - backing_id_set)
    missing_in_adapter = sorted(backing_id_set - adapter_id_set)
    sublayer_mismatches: list[dict[str, Any]] = []
    flag_mismatches: list[dict[str, Any]] = []
    for identifier in adapter_ids:
        adapter_layer = layer_snapshot.get("layers", {}).get(identifier)
        backing_layer = backing_layers.get(identifier)
        if adapter_layer is None or backing_layer is None:
            continue
        adapter_children = [str(value) for value in adapter_layer.get("sublayers", ())]
        backing_children = [
            str(value)
            for value in backing_layer.get(
                "resolved_sublayers",
                backing_layer.get("sublayers", ()),
            )
        ]
        if adapter_children != backing_children:
            sublayer_mismatches.append(
                {
                    "identifier": identifier,
                    "adapter": adapter_children,
                    "backing_usd": backing_children,
                }
            )
        for flag in ("anonymous", "dirty"):
            adapter_value = bool(adapter_layer.get(flag, False))
            backing_value = bool(backing_layer.get(flag, False))
            if adapter_value != backing_value:
                flag_mismatches.append(
                    {
                        "identifier": identifier,
                        "flag": flag,
                        "adapter": adapter_value,
                        "backing_usd": backing_value,
                    }
                )
    adapter_edit_target = str(layer_snapshot.get("edit_target", ""))
    backing_edit_target = str(backing_snapshot.get("edit_target", ""))
    edit_target_matches = bool(adapter_edit_target) and (
        adapter_edit_target == backing_edit_target
    )
    adapter_muted = sorted(
        identifier
        for identifier in adapter_ids
        if bool(layer_snapshot.get("layers", {}).get(identifier, {}).get("muted"))
    )
    backing_muted = sorted(
        identifier
        for identifier in backing_snapshot.get("muted_identifiers", ())
        if identifier in backing_id_set
    )
    muted_matches = adapter_muted == backing_muted
    adapter_root = str(layer_snapshot.get("root", ""))
    backing_root = str(backing_snapshot.get("source", "")) or str(
        backing_snapshot.get("root", "")
    )
    root_matches = bool(adapter_root) and adapter_root == backing_root
    return {
        "comparable": True,
        "matches": not (
            missing
            or missing_in_adapter
            or sublayer_mismatches
            or flag_mismatches
        ) and muted_matches and root_matches and edit_target_matches,
        "missing_in_backing": missing,
        "missing_in_adapter": missing_in_adapter,
        "sublayer_mismatches": sublayer_mismatches,
        "flag_mismatches": flag_mismatches,
        "adapter_muted": adapter_muted,
        "backing_muted": backing_muted,
        "muted_matches": muted_matches,
        "adapter_root": adapter_root,
        "backing_root": backing_root,
        "root_matches": root_matches,
        "adapter_edit_target": adapter_edit_target,
        "backing_edit_target": backing_edit_target,
        "edit_target_matches": edit_target_matches,
    }


def _parity_snapshot(
    usd_snapshot: dict[str, Any],
    ovstage_snapshot: dict[str, Any],
    adapter_snapshot: dict[str, Any],
    transform_snapshot: dict[str, Any],
    layer_snapshot: dict[str, Any],
    backing_layer_snapshot: dict[str, Any],
    bridge_identity: dict[str, Any],
) -> dict[str, Any]:
    usd_available = bool(usd_snapshot.get("available"))
    usd_paths = _usd_user_paths(usd_snapshot)
    runtime_paths = {
        str(path)
        for path, prim in usd_snapshot.get("prims", {}).items()
        if bool(prim.get("runtime_owned"))
    }

    def comparable_paths(paths: Iterable[str]) -> set[str]:
        return {
            str(path)
            for path in paths
            if str(path) != "/" and str(path) not in runtime_paths
            and (
                str(path) in usd_paths
                or not _is_runtime_implementation_path(str(path))
            )
        }

    adapter_paths = comparable_paths(adapter_snapshot.get("paths", ()))
    native_paths = comparable_paths(ovstage_snapshot.get("paths", ()))
    if usd_available:
        # The provider exposes a USD view: USD is the comparison baseline for
        # both the adapter hierarchy and (when present) the native scene.
        baseline = "usd"
        expected_native_paths = {
            path
            for path in usd_paths
            if usd_snapshot["prims"][path].get("active")
            and usd_snapshot["prims"][path].get("defined")
            and not usd_snapshot["prims"][path].get("abstract")
        }
        missing_adapter = sorted(usd_paths - adapter_paths)
        unexpected_adapter = sorted(adapter_paths - usd_paths)
        missing_native = sorted(expected_native_paths - native_paths)
        unexpected_native = sorted(native_paths - expected_native_paths)
    elif ovstage_snapshot.get("available"):
        # Native-only provider: the native OVStage scene is the authoritative
        # baseline, and the adapter/UI hierarchy is compared against it. The
        # absence of a backing USD view is expected, not a parity failure.
        # User-facing versus provider-owned paths come from the ownership
        # flags recorded at capture time with the production adapter's own
        # scene-specific rule: renderer-owned presentation content hidden by
        # the adapter is not drift, while user-facing content (including
        # user-authored /Render) missing from the adapter is.
        baseline = "ovstage"
        native_user_paths = {
            str(path)
            for path, record in ovstage_snapshot.get("prims", {}).items()
            if str(path) != "/" and record.get("user_facing", True)
        }
        adapter_reported_paths = {
            str(path)
            for path in adapter_snapshot.get("paths", ())
            if str(path) != "/"
        }
        missing_adapter = sorted(native_user_paths - adapter_reported_paths)
        unexpected_adapter = sorted(adapter_reported_paths - native_user_paths)
        missing_native = []
        unexpected_native = []
    else:
        # No authoritative scene view is available (e.g. no document open, or
        # a broken provider): parity is INDETERMINATE. Adapter/UI contents
        # cannot prove or disprove anything on their own, and any non-empty
        # adapter hierarchy is surfaced as unverified evidence rather than
        # silently discarded.
        baseline = None
        missing_adapter = []
        unexpected_adapter = []
        missing_native = []
        unexpected_native = []
    transform_mismatches = list(transform_snapshot.get("mismatches", ()))
    topology = _topology_value_parity(
        usd_snapshot,
        ovstage_snapshot,
        adapter_snapshot,
    )
    attribute_values = _attribute_value_parity(usd_snapshot, ovstage_snapshot)
    layer_state = _layer_state_parity(layer_snapshot, backing_layer_snapshot)
    comparable_native = bool(ovstage_snapshot.get("available"))
    comparable = baseline is not None
    adapter_matches_baseline = (
        comparable and not missing_adapter and not unexpected_adapter
    )
    return {
        # Provider-neutral authority/comparison surface. ``baseline`` names
        # the authoritative scene view the adapter/UI hierarchy was compared
        # against ("usd" or "ovstage"); it is None — and ``comparable`` is
        # False — when no authoritative view exists, in which case ``ok`` is
        # always False and ``indeterminate_reason`` explains why.
        "baseline": baseline,
        "comparable": comparable,
        "indeterminate_reason": (
            None
            if comparable
            else "no authoritative scene view (USD or native OVStage) is "
            "available; parity is indeterminate"
        ),
        "unverified_adapter_paths": (
            [] if comparable else sorted(adapter_paths)
        ),
        "adapter_matches_baseline": adapter_matches_baseline,
        "comparable_native": comparable_native,
        "missing_in_adapter": missing_adapter,
        "unexpected_in_adapter": unexpected_adapter,
        "missing_in_ovstage": missing_native,
        "unexpected_in_ovstage": unexpected_native,
        "transform_mismatches": transform_mismatches,
        "bridge_identity": bridge_identity,
        "topology": topology,
        "attribute_values": attribute_values,
        "layer_state": layer_state,
        # Legacy USD-baseline fields (deprecated in favor of ``baseline`` /
        # ``adapter_matches_baseline``): they keep their original meaning —
        # a comparison against the USD view — and are ``None`` (not
        # applicable) whenever no USD view exists, so native-only or
        # absent-authority evidence can never be misread as a USD match.
        "adapter_matches_usd": (
            (not missing_adapter and not unexpected_adapter)
            if usd_available
            else None
        ),
        "ovstage_matches_expected_usd": (
            (comparable_native and not missing_native and not unexpected_native)
            if usd_available
            else None
        ),
        "transforms_match": not transform_mismatches,
        "bridge_identity_matches": bridge_identity.get("matches") is True,
        "topology_matches": topology["matches"],
        "attribute_values_match": attribute_values["matches"],
        "layers_match": layer_state["matches"],
        "ok": (
            comparable
            and adapter_matches_baseline
            and (not comparable_native or (not missing_native and not unexpected_native))
            and not transform_mismatches
            and bridge_identity.get("matches") is True
            and topology["matches"]
            and attribute_values["matches"]
            and layer_state["matches"]
        ),
    }


def capture_application_state(app: Any) -> dict[str, Any]:
    """Return the complete read-only state used by Inspector QA assertions."""

    provider = getattr(getattr(app, "_adapter_provider", None), "name", None)
    evidence_provider = getattr(app, "_adapter_session", None)
    stage_adapter = getattr(app, "_stage_adapter", None)
    usd_stage, scene = _stage_from_app(app)
    adapter_snapshot = _adapter_hierarchy_snapshot(stage_adapter)
    usd_snapshot = _usd_stage_snapshot(usd_stage, scene, evidence_provider)
    native_snapshot = _ovstage_snapshot(scene, evidence_provider)
    transform_snapshot = _transform_snapshot(app, usd_snapshot, native_snapshot)
    layer_snapshot = _layer_snapshot(getattr(app, "_layer_adapter", None))
    backing_layer_snapshot = _backing_layer_snapshot(
        usd_stage,
        scene,
        evidence_provider,
    )
    bridge_identity = _bridge_identity_snapshot(
        usd_stage,
        scene,
        evidence_provider,
    )
    renderer_snapshot = _renderer_snapshot(app, scene)
    renderer_adapter = getattr(getattr(app, "_viewport_window", None), "_renderer", None)
    return {
        "provider": str(provider or ""),
        "current_file_path": str(getattr(app, "_current_file_path", "") or ""),
        "selection": _selection_snapshot(app),
        "stage_ui": _stage_ui_snapshot(app),
        "property_ui": _property_ui_snapshot(app),
        "undo": _undo_snapshot(app),
        "status": _status_snapshot(app),
        "menus": _menu_snapshot(app),
        "components": _component_snapshot(app),
        "adapter": adapter_snapshot,
        "usd": usd_snapshot,
        "ovstage": native_snapshot,
        "transforms": transform_snapshot,
        "layers": layer_snapshot,
        "layers_ui": _layers_ui_snapshot(app),
        "backing_layers": backing_layer_snapshot,
        "bridge_identity": bridge_identity,
        "capabilities": _capability_snapshot(app),
        "create_catalog": _create_catalog_snapshot(app),
        "renderer": renderer_snapshot,
        "physics": _physics_snapshot(app),
        "livestream": _livestream_snapshot(app, renderer_adapter),
        "viewport": _viewport_snapshot(app, usd_snapshot, native_snapshot),
        "parity": _parity_snapshot(
            usd_snapshot,
            native_snapshot,
            adapter_snapshot,
            transform_snapshot,
            layer_snapshot,
            backing_layer_snapshot,
            bridge_identity,
        ),
    }
