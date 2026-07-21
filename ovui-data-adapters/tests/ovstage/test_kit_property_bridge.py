# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Runtime-free tests for the Kit stage bridge property-enumeration surface.

These cover the helpers that let the Property Inspector list and decode
attributes of a selected Kit ovstage prim (fixing the prior "No properties"
state): attribute-name exposure, column dtype derivation, and the cache's
per-path attribute listing / column-dtype lookup.
"""
from __future__ import annotations

import struct

import numpy as np

from ovui_data_adapters.ovstage import _scene


def test_kit_material_path_request_contract_for_ovstage_01(monkeypatch) -> None:
    """Require readable binding data without claiming unreadable connections.

    A direct Kit OVStage 0.1 probe of a populated UsdShade material returns a
    semantic-4 group for ``material:binding``. The same public query/read flow
    returns no group for any of the four material terminal spellings below:
    Fabric owns those values under ``NameSuffix::connection`` and OVStage 0.1
    filters that suffix from discovery/type negotiation.
    """

    monkeypatch.setattr(_scene, "_discover_kit_attr_names", lambda _stage: ())

    requested = set(_scene._requested_kit_attr_names(object()))
    unreadable_connection_forms = {
        "outputs:surface",
        "outputs:surface.connect",
        "outputs:displacement",
        "outputs:displacement.connect",
    }

    assert "material:binding" in requested
    assert requested.isdisjoint(unreadable_connection_forms)


def test_exposed_attr_name_maps_and_hides() -> None:
    # Fabric matrix columns surface under their common names.
    assert _scene._kit_exposed_attr_name("omni:fabric:localMatrix") == "localMatrix"
    assert _scene._kit_exposed_attr_name("omni:fabric:worldMatrix") == "worldMatrix"
    # Ordinary attributes pass through.
    assert _scene._kit_exposed_attr_name("size") == "size"
    assert _scene._kit_exposed_attr_name("extent") == "extent"
    # Bridge-internal / underscore-prefixed attributes are hidden.
    assert _scene._kit_exposed_attr_name("_worldVisibility") is None
    assert _scene._kit_exposed_attr_name("_worldExtent") is None


def test_row_dtype_float32_cast_attrs() -> None:
    # extent is down-cast to float32 in _array_row_bytes; dtype must match.
    arr = np.zeros((1, 6), dtype=np.float64)  # 6 values per prim
    assert _scene._kit_row_dtype(arr, 1, "extent") == (2, 32, 6)


def test_row_dtype_native_kinds() -> None:
    # size: one float64 per prim -> (FLOAT=2, 64, lanes=1).
    assert _scene._kit_row_dtype(np.zeros((1, 1), dtype=np.float64), 1, "size") == (2, 64, 1)
    # localMatrix: 16 float64 per prim -> matrix lanes=16.
    assert _scene._kit_row_dtype(
        np.zeros((1, 16), dtype=np.float64), 1, "omni:fabric:localMatrix"
    ) == (2, 64, 16)
    # an integer column maps to DLPack int code 0.
    assert _scene._kit_row_dtype(np.zeros((1, 1), dtype=np.int32), 1, "count") == (0, 32, 1)


def test_row_dtype_rejects_zero_width() -> None:
    assert _scene._kit_row_dtype(np.zeros((0,), dtype=np.float64), 1, "x") is None


def _cache_with(dtypes):
    return _scene._KitStageBridgeCache(
        ordinal=1,
        path_order=tuple({p for (p, _n) in dtypes}),
        attrs={},
        types={},
        dtypes=dtypes,
    )


def test_cache_attribute_names_and_column_dtype() -> None:
    cube = "/World/Hierarchy/GroupA/BoxA"
    dtypes = {
        (cube, "size"): (2, 64, 1),
        (cube, "extent"): (2, 32, 6),
        (cube, "localMatrix"): (2, 64, 16),
        ("/World/Other", "radius"): (2, 64, 1),
    }
    cache = _cache_with(dtypes)
    # Per-path attribute names are sorted and scoped to the path.
    assert cache.attribute_names_for_path(cube) == ("extent", "localMatrix", "size")
    assert cache.attribute_names_for_path("/World/Other") == ("radius",)
    # Column dtype lookup resolves through the registered handle's paths.
    handle = cache.register_paths((cube,))
    assert cache.column_dtype(handle, "size") == (2, 64, 1)
    assert cache.column_dtype(handle, "localMatrix") == (2, 64, 16)
    assert cache.column_dtype(handle, "missing") is None


class _PathDictionary:
    def path_to_string(self, identifier: int) -> str:
        return {
            11: "/World/Looks/Material",
            12: "/World/Looks/Material/Shader",
        }[identifier]

    def token_to_string(self, identifier: int) -> str:
        return {21: "outputs:surface"}[identifier]


def test_cache_decodes_relationship_and_connection_semantics() -> None:
    cube = "/World/Cube"
    material = "/World/Looks/Material"
    cache = _scene._KitStageBridgeCache(
        ordinal=3,
        path_order=(cube, material),
        attrs={
            (cube, "material:binding"): struct.pack("<Q", 11),
            (material, "outputs:surface"): struct.pack("<QQ", 12, 21),
        },
        types={cube: "Cube", material: "Material"},
        semantics={
            (cube, "material:binding"): 4,
            (material, "outputs:surface"): 12,
        },
    )
    paths = _PathDictionary()

    assert cache.read_path_targets(cube, "material:binding", paths) == (
        "/World/Looks/Material",
    )
    assert cache.read_path_targets(material, "outputs:surface", paths) == (
        "/World/Looks/Material/Shader.outputs:surface",
    )
    assert cache.read_path_targets(cube, "size", paths) is None


def test_cache_rejects_misaligned_path_semantic_payload() -> None:
    cache = _scene._KitStageBridgeCache(
        ordinal=1,
        path_order=("/World/Cube",),
        attrs={("/World/Cube", "material:binding"): b"bad"},
        types={},
        semantics={("/World/Cube", "material:binding"): 4},
    )

    try:
        cache.read_path_targets(
            "/World/Cube",
            "material:binding",
            _PathDictionary(),
        )
    except ValueError as exc:
        assert "invalid byte count" in str(exc)
    else:  # pragma: no cover - defensive failure branch
        raise AssertionError("misaligned relationship bytes must be rejected")
