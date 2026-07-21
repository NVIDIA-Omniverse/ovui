# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for UsdStageAdapter type metadata.

the stage implementation step 3 split the single ``get_type_name`` into:

- ``get_type_name`` — real USD type (e.g. ``"Sphere"``, ``"DistantLight"``).
- ``get_type_category`` — high-level bucket used for icons and filtering
  (``"Mesh" | "Light" | "Camera" | "Xform" | "Scope" | "Other"``).

These tests assert both methods on the ``_TYPE_CATEGORY_MAP`` table.
"""

from unittest.mock import MagicMock

import pytest
from ovui_data_adapters.openusd.stage_adapter import _TYPE_CATEGORY_MAP, UsdStageAdapter


def _make_prim(type_name: str):
    prim = MagicMock()
    prim.GetTypeName.return_value = type_name
    return prim


class TestTypeCategoryMap:
    """Unit tests for the _TYPE_CATEGORY_MAP constants."""

    def test_map_contains_sphere(self):
        assert _TYPE_CATEGORY_MAP["sphere"] == "Mesh"

    def test_map_contains_cube(self):
        assert _TYPE_CATEGORY_MAP["cube"] == "Mesh"

    def test_map_contains_cone(self):
        assert _TYPE_CATEGORY_MAP["cone"] == "Mesh"

    def test_map_contains_cylinder(self):
        assert _TYPE_CATEGORY_MAP["cylinder"] == "Mesh"

    def test_map_contains_capsule(self):
        assert _TYPE_CATEGORY_MAP["capsule"] == "Mesh"

    def test_map_contains_plane(self):
        assert _TYPE_CATEGORY_MAP["plane"] == "Mesh"

    def test_map_contains_basiscurves(self):
        assert _TYPE_CATEGORY_MAP["basiscurves"] == "Mesh"

    def test_map_contains_points(self):
        assert _TYPE_CATEGORY_MAP["points"] == "Mesh"

    def test_map_contains_nurbscurves(self):
        assert _TYPE_CATEGORY_MAP["nurbscurves"] == "Mesh"

    def test_map_contains_nurbspatch(self):
        assert _TYPE_CATEGORY_MAP["nurbspatch"] == "Mesh"

    def test_map_contains_mesh(self):
        assert _TYPE_CATEGORY_MAP["mesh"] == "Mesh"

    def test_map_contains_domelight(self):
        assert _TYPE_CATEGORY_MAP["domelight"] == "Light"

    def test_map_contains_distantlight(self):
        assert _TYPE_CATEGORY_MAP["distantlight"] == "Light"

    def test_map_contains_disklight(self):
        assert _TYPE_CATEGORY_MAP["disklight"] == "Light"

    def test_map_contains_rectlight(self):
        assert _TYPE_CATEGORY_MAP["rectlight"] == "Light"

    def test_map_contains_spherelight(self):
        assert _TYPE_CATEGORY_MAP["spherelight"] == "Light"

    def test_map_contains_cylinderlight(self):
        assert _TYPE_CATEGORY_MAP["cylinderlight"] == "Light"

    def test_map_contains_camera(self):
        assert _TYPE_CATEGORY_MAP["camera"] == "Camera"

    def test_map_contains_xform(self):
        assert _TYPE_CATEGORY_MAP["xform"] == "Xform"

    def test_map_contains_scope(self):
        assert _TYPE_CATEGORY_MAP["scope"] == "Scope"

    def test_all_values_are_valid_categories(self):
        valid = {"Mesh", "Light", "Camera", "Xform", "Scope", "Other"}
        for key, val in _TYPE_CATEGORY_MAP.items():
            assert val in valid, f"{key!r} maps to invalid category {val!r}"


def _make_adapter():
    stage = MagicMock()
    stage.GetPseudoRoot.return_value = MagicMock()
    stage.GetPseudoRoot.return_value.GetChildren.return_value = []
    adapter = UsdStageAdapter.__new__(UsdStageAdapter)
    adapter._stage = stage
    adapter._undo_manager = None
    adapter._subscribers = []
    adapter._suppressed = False
    adapter._call_later = None
    adapter._pending_changed = set()
    adapter._pending_resynced = set()
    adapter._flush_scheduled = False
    adapter._in_mutation = False
    return adapter


class TestGetTypeCategory:
    """UsdStageAdapter.get_type_category() — badge-coloring bucket."""

    def test_sphere_returns_mesh(self):
        adapter = _make_adapter()
        prim = _make_prim("Sphere")
        assert adapter.get_type_category(prim) == "Mesh"

    def test_cube_returns_mesh(self):
        adapter = _make_adapter()
        prim = _make_prim("Cube")
        assert adapter.get_type_category(prim) == "Mesh"

    def test_mesh_returns_mesh(self):
        adapter = _make_adapter()
        prim = _make_prim("Mesh")
        assert adapter.get_type_category(prim) == "Mesh"

    def test_domelight_returns_light(self):
        adapter = _make_adapter()
        prim = _make_prim("DomeLight")
        assert adapter.get_type_category(prim) == "Light"

    def test_distantlight_returns_light(self):
        adapter = _make_adapter()
        prim = _make_prim("DistantLight")
        assert adapter.get_type_category(prim) == "Light"

    def test_disklight_returns_light(self):
        adapter = _make_adapter()
        prim = _make_prim("DiskLight")
        assert adapter.get_type_category(prim) == "Light"

    def test_rectlight_returns_light(self):
        adapter = _make_adapter()
        prim = _make_prim("RectLight")
        assert adapter.get_type_category(prim) == "Light"

    def test_spherelight_returns_light(self):
        adapter = _make_adapter()
        prim = _make_prim("SphereLight")
        assert adapter.get_type_category(prim) == "Light"

    def test_camera_returns_camera(self):
        adapter = _make_adapter()
        prim = _make_prim("Camera")
        assert adapter.get_type_category(prim) == "Camera"

    def test_xform_returns_xform(self):
        adapter = _make_adapter()
        prim = _make_prim("Xform")
        assert adapter.get_type_category(prim) == "Xform"

    def test_scope_returns_scope(self):
        adapter = _make_adapter()
        prim = _make_prim("Scope")
        assert adapter.get_type_category(prim) == "Scope"

    def test_empty_type_name_returns_other(self):
        adapter = _make_adapter()
        prim = _make_prim("")
        assert adapter.get_type_category(prim) == "Other"

    def test_unknown_type_returns_other(self):
        adapter = _make_adapter()
        prim = _make_prim("FancyCustomPrim")
        assert adapter.get_type_category(prim) == "Other"

    def test_case_insensitive_lookup(self):
        adapter = _make_adapter()
        prim = _make_prim("SPHERE")
        assert adapter.get_type_category(prim) == "Mesh"


class TestGetTypeName:
    """UsdStageAdapter.get_type_name() returns the real USD type verbatim."""

    @pytest.mark.parametrize(
        "raw",
        ["Sphere", "Cube", "Mesh", "Camera", "Xform", "Scope",
         "DistantLight", "DomeLight", "RectLight", "FancyCustomPrim"],
    )
    def test_returns_raw_type(self, raw):
        adapter = _make_adapter()
        prim = _make_prim(raw)
        assert adapter.get_type_name(prim) == raw

    def test_empty_type_name_class_spec_returns_class(self):
        Sdf = pytest.importorskip("pxr", reason="pxr not available").Sdf
        adapter = _make_adapter()
        prim = _make_prim("")
        prim.GetSpecifier.return_value = Sdf.SpecifierClass
        assert adapter.get_type_name(prim) == "Class"

    def test_empty_type_name_over_spec_returns_empty(self):
        Sdf = pytest.importorskip("pxr", reason="pxr not available").Sdf
        adapter = _make_adapter()
        prim = _make_prim("")
        prim.GetSpecifier.return_value = Sdf.SpecifierOver
        assert adapter.get_type_name(prim) == ""

    def test_empty_type_name_def_spec_returns_empty(self):
        Sdf = pytest.importorskip("pxr", reason="pxr not available").Sdf
        adapter = _make_adapter()
        prim = _make_prim("")
        prim.GetSpecifier.return_value = Sdf.SpecifierDef
        assert adapter.get_type_name(prim) == ""

    def test_preserves_case(self):
        adapter = _make_adapter()
        prim = _make_prim("SPHERE")
        # Must NOT normalize here; presentation-only casing belongs in the UI delegate.
        assert adapter.get_type_name(prim) == "SPHERE"


class TestGetIconName:
    """UsdStageAdapter.get_icon_name() returns StageIcons-ready names."""

    def test_mesh_returns_mesh(self):
        adapter = _make_adapter()
        prim = _make_prim("Mesh")
        assert adapter.get_icon_name(prim) == "Mesh"

    def test_cube_returns_mesh(self):
        adapter = _make_adapter()
        prim = _make_prim("Cube")
        assert adapter.get_icon_name(prim) == "Mesh"

    def test_camera_returns_camera(self):
        adapter = _make_adapter()
        prim = _make_prim("Camera")
        assert adapter.get_icon_name(prim) == "Camera"

    def test_distantlight_returns_distantlight(self):
        adapter = _make_adapter()
        prim = _make_prim("DistantLight")
        assert adapter.get_icon_name(prim) == "DistantLight"

    def test_scope_returns_scope(self):
        adapter = _make_adapter()
        prim = _make_prim("Scope")
        assert adapter.get_icon_name(prim) == "Scope"

    def test_xform_returns_xform(self):
        adapter = _make_adapter()
        prim = _make_prim("Xform")
        assert adapter.get_icon_name(prim) == "Xform"

    def test_empty_returns_prim_fallback(self):
        adapter = _make_adapter()
        prim = _make_prim("")
        assert adapter.get_icon_name(prim) == "Prim"

    def test_unknown_returns_prim_fallback(self):
        adapter = _make_adapter()
        prim = _make_prim("FancyCustomPrim")
        assert adapter.get_icon_name(prim) == "Prim"
