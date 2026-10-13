# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Owned OVStage-native catalog snapshots for camera and renderer metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ovui_data_adapters.ovstage._native import (
    read_matrix_attribute,
    read_path_attribute_records,
    read_token_attribute,
    resolve_query_names,
)
from ovui_data_adapters.ovstage._scene import _kit_type_records
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter


_CATALOG_PROPERTY_NAMES = (
    "camera",
    "orderedVars",
    "sourceName",
    "channels",
    "worldMatrix",
    "sourceType",
    "dataType",
    "resolution",
    "omni:rtx:rendermode",
)
_CATALOG_PRIMARY_TYPES = frozenset(
    {
        "camera",
        "usdgeomcamera",
        "renderproduct",
        "usdrenderproduct",
        "rendervar",
        "usdrendervar",
    }
)


@dataclass(frozen=True)
class NativeCatalogPrim:
    """Pure-Python copy of native type, schema, and public property data."""

    path: str
    type_name: str
    applied_schemas: tuple[str, ...]
    properties: tuple[tuple[str, Any], ...]

    def value(self, name: str, default: Any = None) -> Any:
        return dict(self.properties).get(name, default)


@dataclass(frozen=True)
class NativeCatalogSnapshot:
    """Immutable current-ordinal catalog state with no borrowed native views."""

    ordinal: int
    topology_version: int
    topology_revision: int
    prims: tuple[NativeCatalogPrim, ...]

    def prim(self, path: str) -> NativeCatalogPrim | None:
        return next((prim for prim in self.prims if prim.path == path), None)

    def paths_of_type(self, *type_names: str) -> tuple[str, ...]:
        accepted = {str(name).lower() for name in type_names}
        return tuple(
            prim.path for prim in self.prims if prim.type_name.lower() in accepted
        )


def native_catalog_snapshot(scene: Any | None) -> NativeCatalogSnapshot:
    """Return one cached, owned native snapshot for the scene's current ordinal."""

    stage = getattr(scene, "_stage", None)
    if scene is None or stage is None or not getattr(scene, "is_open", False):
        return NativeCatalogSnapshot(0, 0, 0, ())
    ordinal = int(getattr(scene, "current_ordinal", None) or stage.current_ordinal)
    topology_version = int(stage.get_topology_version())
    topology_revision = int(getattr(scene, "topology_revision", 0) or 0)
    key = (id(stage), ordinal, topology_version, topology_revision)
    cached = getattr(scene, "_ovui_native_catalog_cache", None)
    if cached is not None and cached[0] == key:
        return cached[1]

    records = _copy_type_records(stage, ordinal)

    property_paths = {
        path
        for path, (type_name, _schemas) in records.items()
        if str(type_name).lower() in _CATALOG_PRIMARY_TYPES
    }
    copied_properties = {
        path: _copy_properties(scene, path)
        for path in sorted(property_paths)
    }
    referenced_paths: set[str] = set()
    for properties in copied_properties.values():
        values = dict(properties)
        referenced_paths.update(_path_values(values.get("camera")))
        referenced_paths.update(_path_values(values.get("orderedVars")))
    for path in sorted(referenced_paths - property_paths):
        if path in records:
            copied_properties[path] = _copy_properties(scene, path)

    catalog_paths = property_paths | {
        path for path in referenced_paths if path in records
    }
    prims: list[NativeCatalogPrim] = []
    for path in sorted(catalog_paths):
        type_name, schemas = records[path]
        prims.append(
            NativeCatalogPrim(
                path=path,
                type_name=str(type_name),
                applied_schemas=tuple(str(value) for value in schemas),
                properties=tuple(copied_properties.get(path, ())),
            )
        )
    snapshot = NativeCatalogSnapshot(
        ordinal=ordinal,
        topology_version=topology_version,
        topology_revision=topology_revision,
        prims=tuple(prims),
    )
    scene._ovui_native_catalog_cache = (key, snapshot)
    return snapshot


def _copy_properties(scene: Any, path: str) -> list[tuple[str, Any]]:
    stage = getattr(scene, "_stage", None)
    if (
        getattr(stage, "_ovui_query_prims_source", None)
        == "native Kit query/read_attributes"
    ):
        records = read_path_attribute_records(
            stage,
            path,
            _CATALOG_PROPERTY_NAMES,
        )
        properties = [
            (name, _owned_value(record.value))
            for name, record in records.items()
        ]
        matrix = read_matrix_attribute(stage, path, "worldMatrix")
        if matrix is not None:
            properties = [
                (name, value)
                for name, value in properties
                if name != "worldMatrix"
            ]
            properties.append(("worldMatrix", _owned_value(matrix)))
        return properties

    # Compatibility fallback for legacy/fake stages without api_v2 queries.
    properties: list[tuple[str, Any]] = []
    try:
        adapter = OvstagePropertyAdapter(scene, [path])
        if not adapter.is_valid():
            return properties
        names = adapter.get_attribute_names()
    except Exception:
        return properties
    for name in names:
        try:
            value = adapter.get_value(name)
        except Exception:
            continue
        properties.append((str(name), _owned_value(value)))
    return properties


def _copy_type_records(
    stage: Any,
    ordinal: int,
) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Copy type/schema metadata without the all-property compatibility cache."""

    if (
        getattr(stage, "_ovui_query_prims_source", None)
        == "native Kit query/read_attributes"
    ):
        return {
            path: (str(type_name), tuple(str(value) for value in schemas))
            for path, (type_name, schemas) in _kit_type_records(
                stage,
                int(ordinal),
            ).items()
            if _is_canonical_path(path)
        }

    records: dict[str, tuple[str, tuple[str, ...]]] = {}
    query_result = stage.query_prims(int(ordinal))
    for group in query_result.get("groups", ()):
        group_type = str(group.get("prim_type", ""))
        schemas = resolve_query_names(stage, group.get("applied_schemas", ()))
        handle = int(group.get("prim_list_handle") or 0)
        if not handle:
            continue
        for raw_path in stage.get_prim_paths(handle):
            path = str(raw_path)
            if _is_canonical_path(path):
                records[path] = (
                    read_token_attribute(stage, path, "usd-prim-type")
                    or group_type,
                    schemas,
                )
    return records


def _path_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if _is_canonical_path(value) else ()
    if isinstance(value, (tuple, list)):
        return tuple(
            str(item)
            for item in value
            if _is_canonical_path(str(item))
        )
    return ()


def _owned_value(value: Any) -> Any:
    if isinstance(value, tuple):
        return tuple(_owned_value(item) for item in value)
    if isinstance(value, list):
        return tuple(_owned_value(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _owned_value(item)) for key, item in value.items()))
    return value


def _is_canonical_path(path: str) -> bool:
    return bool(
        path.startswith("/")
        and path != "/"
        and not path.endswith("/")
        and "//" not in path
        and all(part not in {"", ".", ".."} for part in path[1:].split("/"))
    )


__all__ = ["NativeCatalogPrim", "NativeCatalogSnapshot", "native_catalog_snapshot"]
