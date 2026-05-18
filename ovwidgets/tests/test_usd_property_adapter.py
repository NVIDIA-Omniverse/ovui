# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for UsdPropertyAdapter — attribute enumeration, get/set, and undo.

All tests skip gracefully when pxr (OpenUSD) is not available.
"""

import pytest

try:
    from pxr import Gf, Sdf, Usd, UsdGeom
    HAS_USD = True
except ImportError:
    HAS_USD = False

pytestmark = pytest.mark.skipif(not HAS_USD, reason="pxr (OpenUSD) not available")

from ovui_data_adapters.openusd import UsdPropertyAdapter

from ovwidgets.common.undo import UndoManager

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sphere_stage():
    stage = Usd.Stage.CreateInMemory()
    sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
    sphere.GetRadiusAttr().Set(1.0)
    return stage


@pytest.fixture
def xform_stage():
    stage = Usd.Stage.CreateInMemory()
    xform = UsdGeom.Xform.Define(stage, "/Xform")
    xform.AddTranslateOp().Set(Gf.Vec3d(1.0, 2.0, 3.0))
    xform.AddScaleOp().Set(Gf.Vec3f(1.0, 1.0, 1.0))
    return stage


@pytest.fixture
def multi_stage():
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Sphere.Define(stage, "/Sphere").GetRadiusAttr().Set(1.0)
    UsdGeom.Cube.Define(stage, "/Cube").GetSizeAttr().Set(2.0)
    return stage


@pytest.fixture
def two_xform_stage():
    """Two Xforms where only translate Z differs: /A=(1,0,0), /B=(1,0,5)."""
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/A").AddTranslateOp().Set(Gf.Vec3d(1.0, 0.0, 0.0))
    UsdGeom.Xform.Define(stage, "/B").AddTranslateOp().Set(Gf.Vec3d(1.0, 0.0, 5.0))
    return stage


# ── Step 33: Attribute Enumeration ───────────────────────────────────────────

class TestSphereEnumeration:
    def test_radius_found(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        assert "radius" in adapter.get_attribute_names()

    def test_radius_value_type_is_float(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.value_type is float

    def test_array_types_included_step_3_8(self, sphere_stage):
        """Step 3.8 stopped skipping array attributes — ``extent``
        (``float3[]``) and ``primvars:displayColor`` (``color3f[]``)
        both enumerate now. Pre-3.8 they were silently dropped by
        ``_enumerate_attrs`` because ``_map_type`` returned ``None`` for
        ``[]``-suffixed type strings. See the property inspector 3.8."""
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        names = adapter.get_attribute_names()
        assert "extent" in names
        assert "xformOpOrder" in names


class TestXformEnumeration:
    def test_xformop_translate_found(self, xform_stage):
        adapter = UsdPropertyAdapter(xform_stage, ["/Xform"])
        assert "xformOp:translate" in adapter.get_attribute_names()

    def test_xformop_scale_found(self, xform_stage):
        adapter = UsdPropertyAdapter(xform_stage, ["/Xform"])
        assert "xformOp:scale" in adapter.get_attribute_names()

    def test_xformop_order_included_step_3_8(self, xform_stage):
        """Step 3.8: ``xformOpOrder`` (``token[]``) now enumerates as an
        array attribute rather than being silently dropped. See
        the property inspector 3.8."""
        adapter = UsdPropertyAdapter(xform_stage, ["/Xform"])
        assert "xformOpOrder" in adapter.get_attribute_names()


class TestMultiSelection:
    def test_intersection_excludes_sphere_only_attrs(self, multi_stage):
        adapter = UsdPropertyAdapter(multi_stage, ["/Sphere", "/Cube"])
        names = adapter.get_attribute_names()
        assert "radius" not in names   # Sphere only
        assert "size" not in names     # Cube only

    def test_intersection_includes_common_attrs(self, multi_stage):
        adapter = UsdPropertyAdapter(multi_stage, ["/Sphere", "/Cube"])
        names = adapter.get_attribute_names()
        # Both Sphere and Cube inherit from Gprim — share doubleSided, visibility, etc.
        assert "doubleSided" in names or "visibility" in names

    def test_single_path_returns_all_attrs(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        assert "radius" in adapter.get_attribute_names()


class TestEdgeCases:
    def test_empty_paths_returns_empty(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, [])
        assert adapter.get_attribute_names() == []

    def test_invalid_path_returns_empty(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/NonExistent"])
        assert adapter.get_attribute_names() == []

    def test_is_valid_empty_paths(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, [])
        assert not adapter.is_valid()

    def test_is_valid_invalid_path(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/NonExistent"])
        assert not adapter.is_valid()

    def test_is_valid_good_path(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        assert adapter.is_valid()


class TestUnsupportedTypes:
    def test_value_types_are_within_supported_set(self, sphere_stage):
        """Every enumerated attribute's ``value_type`` falls within the
        set of supported adapter value-type tags. Step 3.5 extended the
        set with ``matrix2d/matrix3d/matrix4d``; Step 3.6 added ``asset``
        for ``SdfAssetPath`` attributes; Step 3.7 added ``relationship``
        for ``Usd.Relationship`` objects (every UsdGeom prim inherits
        a ``proxyPrim`` relationship from ``Gprim``); Step 3.8 adds
        ``array`` for every ``[]``-suffixed USD type (``float[]``,
        ``token[]``, ``float3[]``, …), which the sphere fixture
        exercises through the inherited ``extent`` attribute. The
        acceptance list is the adapter's surface contract — a new type
        entering ``_TYPE_MAP`` without a matching row builder would
        surface here."""
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        names = adapter.get_attribute_names()
        for name in names:
            meta = adapter.get_attribute_metadata(name)
            assert meta.value_type in (
                float, int, bool, str,
                "float2", "float3", "float4", "color3f", "color4f",
                "int2", "int3", "int4",
                "matrix2d", "matrix3d", "matrix4d",
                "asset", "relationship", "array",
            )


class TestColor4fTypeMapping:
    """Step 3.4: ``color4f/color4d/color4h`` are now supported. Prior to
    Step 3.4 the adapter silently dropped them because ``_TYPE_MAP`` only
    had the three-channel colour entries."""

    def _stage_with_color4(self):
        """Build an in-memory stage with a Sphere carrying a ``color4f``
        and a ``color4d`` attribute. Kept separate from the module
        ``sphere_stage`` fixture so other tests don't have to update.
        """
        from pxr import Gf, Sdf, Usd, UsdGeom
        stage = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Sphere.Define(stage, "/Sphere").GetPrim()
        a4f = prim.CreateAttribute("color4f_attr", Sdf.ValueTypeNames.Color4f)
        a4f.Set(Gf.Vec4f(0.9, 0.5, 0.1, 0.75))
        a4d = prim.CreateAttribute("color4d_attr", Sdf.ValueTypeNames.Color4d)
        a4d.Set(Gf.Vec4d(0.25, 0.5, 0.75, 1.0))
        return stage

    def test_color4f_attribute_enumerated(self):
        stage = self._stage_with_color4()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert "color4f_attr" in adapter.get_attribute_names()

    def test_color4d_attribute_enumerated(self):
        stage = self._stage_with_color4()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert "color4d_attr" in adapter.get_attribute_names()

    def test_color4f_metadata_type_name(self):
        stage = self._stage_with_color4()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("color4f_attr")
        assert meta.type_name == "color4f"

    def test_color4f_value_roundtrip(self):
        """(0.9, 0.5, 0.1, 0.75) in → 4-tuple out. Float precision loss
        across ``Gf.Vec4f`` rounding is within ``pytest.approx`` tolerance."""
        stage = self._stage_with_color4()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        value = adapter.get_value("color4f_attr")
        assert len(value) == 4
        assert value[0] == pytest.approx(0.9, rel=1e-6)
        assert value[1] == pytest.approx(0.5, rel=1e-6)
        assert value[2] == pytest.approx(0.1, rel=1e-6)
        assert value[3] == pytest.approx(0.75, rel=1e-6)

    def test_color4f_set_value_writes_gf_vec4f(self):
        """Writing back via ``set_value`` must use ``Gf.Vec4f`` (not Vec3f)."""
        stage = self._stage_with_color4()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        adapter.set_value("color4f_attr", (0.1, 0.2, 0.3, 0.4))
        value = adapter.get_value("color4f_attr")
        assert value[0] == pytest.approx(0.1, rel=1e-6)
        assert value[3] == pytest.approx(0.4, rel=1e-6)


class TestGroupMapping:
    def test_xformop_group_is_transform(self, xform_stage):
        adapter = UsdPropertyAdapter(xform_stage, ["/Xform"])
        meta = adapter.get_attribute_metadata("xformOp:translate")
        assert meta.group == "Transform"

    def test_xformop_scale_group_is_transform(self, xform_stage):
        adapter = UsdPropertyAdapter(xform_stage, ["/Xform"])
        meta = adapter.get_attribute_metadata("xformOp:scale")
        assert meta.group == "Transform"

    def test_plain_attr_group_is_attributes(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.group == "Attributes"

    def test_visibility_group_is_attributes(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("visibility")
        assert meta.group == "Attributes"

    # --- Step 5.2: displayGroup metadata drives dot-separated group path ---

    def test_authored_display_group_colons_rewritten_to_dots(self):
        """Step 5.2: when ``attr.GetDisplayGroup()`` authors a
        colon-separated hierarchy (USD's native format), the adapter
        surfaces it as a dot-separated string so the
        :class:`UiDisplayGroup` splitter produces nested frames."""
        from pxr import Sdf, Usd
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/World/Test", "Xform")
        attr = prim.CreateAttribute("foo", Sdf.ValueTypeNames.Float)
        attr.SetDisplayGroup("Transform:Translate")
        adapter = UsdPropertyAdapter(stage, ["/World/Test"])
        meta = adapter.get_attribute_metadata("foo")
        assert meta.group == "Transform.Translate"

    def test_authored_display_group_single_segment_passes_through(self):
        """One-level authored display groups ride the dot-split
        fallback path unchanged — ``"Geometry".split(".")`` produces a
        single segment, still a valid :class:`UiDisplayGroup` path."""
        from pxr import Sdf, Usd
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/World/Test", "Xform")
        attr = prim.CreateAttribute("foo", Sdf.ValueTypeNames.Float)
        attr.SetDisplayGroup("Geometry")
        adapter = UsdPropertyAdapter(stage, ["/World/Test"])
        meta = adapter.get_attribute_metadata("foo")
        assert meta.group == "Geometry"

    def test_authored_display_group_three_levels(self):
        """Authored ``"A:B:C"`` must survive as ``"A.B.C"`` so
        :meth:`UiDisplayGroup.add_prop` produces a three-level deep
        tree."""
        from pxr import Sdf, Usd
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/World/Test", "Xform")
        attr = prim.CreateAttribute("deep", Sdf.ValueTypeNames.Float)
        attr.SetDisplayGroup("A:B:C")
        adapter = UsdPropertyAdapter(stage, ["/World/Test"])
        meta = adapter.get_attribute_metadata("deep")
        assert meta.group == "A.B.C"

    def test_empty_display_group_falls_back_to_namespace_heuristic(self):
        """With no authored ``displayGroup``, the namespace heuristic
        (``xformOp`` → ``"Transform"``, unnamespaced → ``"Attributes"``)
        still drives the group — this is the preserves-existing-tests
        invariant."""
        from pxr import Sdf, Usd
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/World/Test", "Xform")
        prim.CreateAttribute("xformOp:translate", Sdf.ValueTypeNames.Double3)
        adapter = UsdPropertyAdapter(stage, ["/World/Test"])
        meta = adapter.get_attribute_metadata("xformOp:translate")
        assert meta.group == "Transform"

    def test_authored_display_group_on_relationship(self):
        """:class:`Usd.Relationship` inherits ``GetDisplayGroup`` from
        :class:`Usd.Property`. A relationship with an authored
        colon-separated ``displayGroup`` must surface the same
        dot-rewritten form as an attribute."""
        from pxr import Usd
        stage = Usd.Stage.CreateInMemory()
        prim = stage.DefinePrim("/World/Test", "Xform")
        rel = prim.CreateRelationship("material:binding")
        rel.SetDisplayGroup("Material:Bindings")
        adapter = UsdPropertyAdapter(stage, ["/World/Test"])
        meta = adapter.get_attribute_metadata("material:binding")
        assert meta.group == "Material.Bindings"


class TestDisplayName:
    def test_radius_display_name(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.display_name == "Radius"

    def test_translate_display_name_strips_namespace(self, xform_stage):
        adapter = UsdPropertyAdapter(xform_stage, ["/Xform"])
        meta = adapter.get_attribute_metadata("xformOp:translate")
        assert meta.display_name == "Translate"


# ── Step 34: Get/Set Value + Undo ─────────────────────────────────────────────

class TestGetValue:
    def test_get_radius_value(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        val = adapter.get_value("radius")
        assert isinstance(val, float)
        assert val == pytest.approx(1.0)

    def test_get_bool_value(self, sphere_stage):
        sphere_stage.GetPrimAtPath("/Sphere").GetAttribute("doubleSided").Set(True)
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        val = adapter.get_value("doubleSided")
        assert val is True

    def test_get_str_value(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        val = adapter.get_value("visibility")
        assert isinstance(val, str)


class TestSetValue:
    def test_set_radius_writes_to_usd(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        adapter.set_value("radius", 5.0)
        attr = sphere_stage.GetPrimAtPath("/Sphere").GetAttribute("radius")
        assert attr.Get() == pytest.approx(5.0)

    def test_set_bool_writes_to_usd(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        adapter.set_value("doubleSided", True)
        attr = sphere_stage.GetPrimAtPath("/Sphere").GetAttribute("doubleSided")
        assert attr.Get() is True

    def test_set_value_multipath(self, multi_stage):
        # Setting a common attr on both prims
        adapter = UsdPropertyAdapter(multi_stage, ["/Sphere", "/Cube"])
        adapter.set_value("doubleSided", True)
        sphere_val = multi_stage.GetPrimAtPath("/Sphere").GetAttribute("doubleSided").Get()
        cube_val = multi_stage.GetPrimAtPath("/Cube").GetAttribute("doubleSided").Get()
        assert sphere_val is True
        assert cube_val is True


class TestVec3:
    def test_get_translate_returns_tuple(self, xform_stage):
        adapter = UsdPropertyAdapter(xform_stage, ["/Xform"])
        val = adapter.get_value("xformOp:translate")
        assert isinstance(val, tuple)
        assert len(val) == 3
        assert val == pytest.approx((1.0, 2.0, 3.0))

    def test_set_translate_writes_tuple(self, xform_stage):
        adapter = UsdPropertyAdapter(xform_stage, ["/Xform"])
        adapter.set_value("xformOp:translate", (4.0, 5.0, 6.0))
        val = adapter.get_value("xformOp:translate")
        assert val == pytest.approx((4.0, 5.0, 6.0))

    def test_get_scale_returns_float_tuple(self, xform_stage):
        adapter = UsdPropertyAdapter(xform_stage, ["/Xform"])
        val = adapter.get_value("xformOp:scale")
        assert isinstance(val, tuple) and len(val) == 3
        assert all(isinstance(c, float) for c in val)


class TestUndoRedo:
    def test_end_edit_pushes_to_undo_stack(self, sphere_stage):
        undo = UndoManager()
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"], undo_manager=undo)
        adapter.begin_edit("radius")
        adapter.set_value("radius", 5.0)
        adapter.end_edit("radius")
        assert undo.can_undo()

    def test_undo_restores_old_value(self, sphere_stage):
        undo = UndoManager()
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"], undo_manager=undo)
        adapter.begin_edit("radius")
        adapter.set_value("radius", 5.0)
        adapter.end_edit("radius")

        undo.undo()

        attr = sphere_stage.GetPrimAtPath("/Sphere").GetAttribute("radius")
        assert attr.Get() == pytest.approx(1.0)

    def test_redo_restores_new_value(self, sphere_stage):
        undo = UndoManager()
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"], undo_manager=undo)
        adapter.begin_edit("radius")
        adapter.set_value("radius", 5.0)
        adapter.end_edit("radius")

        undo.undo()
        undo.redo()

        attr = sphere_stage.GetPrimAtPath("/Sphere").GetAttribute("radius")
        assert attr.Get() == pytest.approx(5.0)

    def test_no_undo_if_value_unchanged(self, sphere_stage):
        undo = UndoManager()
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"], undo_manager=undo)
        adapter.begin_edit("radius")
        # Don't change the value
        adapter.end_edit("radius")
        assert not undo.can_undo()

    def test_undo_vec3(self, xform_stage):
        undo = UndoManager()
        adapter = UsdPropertyAdapter(xform_stage, ["/Xform"], undo_manager=undo)
        adapter.begin_edit("xformOp:translate")
        adapter.set_value("xformOp:translate", (9.0, 8.0, 7.0))
        adapter.end_edit("xformOp:translate")

        undo.undo()

        val = adapter.get_value("xformOp:translate")
        assert val == pytest.approx((1.0, 2.0, 3.0))

    def test_no_undo_manager_set_value_still_works(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])  # no undo_manager
        adapter.set_value("radius", 7.0)
        assert adapter.get_value("radius") == pytest.approx(7.0)

    def test_begin_end_edit_no_undo_manager_is_noop(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])  # no undo_manager
        adapter.begin_edit("radius")
        adapter.set_value("radius", 3.0)
        adapter.end_edit("radius")  # should not raise


class TestScheme:
    def test_scheme_is_usd(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        assert adapter.get_scheme() == "usd"


class TestSubscription:
    def test_subscribe_fires_on_set_value(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        fired = []
        sub = adapter.subscribe_changes(lambda: fired.append(1))
        adapter.set_value("radius", 2.0)
        assert len(fired) == 1

    def test_cancel_stops_notifications(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        fired = []
        sub = adapter.subscribe_changes(lambda: fired.append(1))
        sub.cancel()
        adapter.set_value("radius", 2.0)
        assert len(fired) == 0


# ── Step 2.2: Per-Component Ambiguity ────────────────────────────────────────

class TestPerComponentAmbiguity:
    def test_vec3_only_z_differs_returns_false_false_true(self, two_xform_stage):
        adapter = UsdPropertyAdapter(two_xform_stage, ["/A", "/B"])
        assert adapter.get_per_component_ambiguity("xformOp:translate") == [
            False,
            False,
            True,
        ]

    def test_vec3_all_equal_returns_all_false(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(stage, "/A").AddTranslateOp().Set(Gf.Vec3d(1.0, 2.0, 3.0))
        UsdGeom.Xform.Define(stage, "/B").AddTranslateOp().Set(Gf.Vec3d(1.0, 2.0, 3.0))
        adapter = UsdPropertyAdapter(stage, ["/A", "/B"])
        assert adapter.get_per_component_ambiguity("xformOp:translate") == [
            False,
            False,
            False,
        ]

    def test_scalar_float_returns_none(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        assert adapter.get_per_component_ambiguity("radius") is None

    def test_unknown_attr_returns_none(self, sphere_stage):
        adapter = UsdPropertyAdapter(sphere_stage, ["/Sphere"])
        assert adapter.get_per_component_ambiguity("nonexistent") is None

    def test_single_path_vec3_returns_all_false(self, xform_stage):
        adapter = UsdPropertyAdapter(xform_stage, ["/Xform"])
        assert adapter.get_per_component_ambiguity("xformOp:translate") == [
            False,
            False,
            False,
        ]


# ── Step 3.5: Matrix Type Mapping (matrix2d / matrix3d / matrix4d) ────────────


class TestMatrixTypeMapping:
    """Step 3.5: ``matrix2d/matrix3d/matrix4d`` are newly supported. Prior
    to Step 3.5 the adapter silently dropped them because ``_TYPE_MAP``
    had no matrix entries. The tests below pin the full USD-to-Python
    roundtrip: enumerate the attribute, pull its metadata, read the value
    as a row-major flat tuple, and write it back through ``set_value``.

    USD matrices ship only in double precision — no ``matrix2f/matrix3f/
    matrix4f`` variants — so these three type names cover the complete
    matrix surface.
    """

    def _stage_with_matrices(self):
        """Build an in-memory stage with a Sphere carrying ``matrix2d``,
        ``matrix3d``, and ``matrix4d`` attributes."""
        stage = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Sphere.Define(stage, "/Sphere").GetPrim()
        m2 = prim.CreateAttribute("m2_attr", Sdf.ValueTypeNames.Matrix2d)
        m2.Set(Gf.Matrix2d(1.0, 2.0, 3.0, 4.0))
        m3 = prim.CreateAttribute("m3_attr", Sdf.ValueTypeNames.Matrix3d)
        m3.Set(Gf.Matrix3d(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0))
        m4 = prim.CreateAttribute("m4_attr", Sdf.ValueTypeNames.Matrix4d)
        m4.Set(Gf.Matrix4d(
            1.0, 2.0, 3.0, 4.0,
            5.0, 6.0, 7.0, 8.0,
            9.0, 10.0, 11.0, 12.0,
            13.0, 14.0, 15.0, 16.0,
        ))
        return stage

    def test_matrix2d_attribute_enumerated(self):
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert "m2_attr" in adapter.get_attribute_names()

    def test_matrix3d_attribute_enumerated(self):
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert "m3_attr" in adapter.get_attribute_names()

    def test_matrix4d_attribute_enumerated(self):
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert "m4_attr" in adapter.get_attribute_names()

    def test_matrix2d_metadata_type_name(self):
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("m2_attr")
        assert meta.type_name == "matrix2d"
        assert meta.value_type == "matrix2d"

    def test_matrix3d_metadata_type_name(self):
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("m3_attr")
        assert meta.type_name == "matrix3d"
        assert meta.value_type == "matrix3d"

    def test_matrix4d_metadata_type_name(self):
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("m4_attr")
        assert meta.type_name == "matrix4d"
        assert meta.value_type == "matrix4d"

    def test_matrix2d_read_returns_flat_tuple_row_major(self):
        """Read the authored ``Gf.Matrix2d(1, 2, 3, 4)`` and verify the
        adapter returns ``(1.0, 2.0, 3.0, 4.0)`` — flat, row-major."""
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        value = adapter.get_value("m2_attr")
        assert isinstance(value, tuple)
        assert len(value) == 4
        assert value == pytest.approx((1.0, 2.0, 3.0, 4.0))

    def test_matrix3d_read_returns_flat_tuple_row_major(self):
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        value = adapter.get_value("m3_attr")
        assert isinstance(value, tuple)
        assert len(value) == 9
        # Gf.Matrix3d(1,2,3,4,5,6,7,8,9) → row 0 = (1,2,3), row 1 = (4,5,6), …
        assert value == pytest.approx(tuple(float(i) for i in range(1, 10)))

    def test_matrix4d_read_returns_flat_tuple_row_major(self):
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        value = adapter.get_value("m4_attr")
        assert isinstance(value, tuple)
        assert len(value) == 16
        assert value == pytest.approx(tuple(float(i) for i in range(1, 17)))

    def test_matrix4d_set_value_writes_gf_matrix4d(self):
        """Writing a flat tuple back via ``set_value`` must roundtrip through
        ``Gf.Matrix4d`` — a 16-float USD double matrix, not 4×4 separate
        doubles or a Vec-shaped write."""
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        new_value = tuple(float(i) * 0.1 for i in range(1, 17))
        adapter.set_value("m4_attr", new_value)
        readback = adapter.get_value("m4_attr")
        assert readback == pytest.approx(new_value)
        # Also verify the underlying USD attribute holds a Gf.Matrix4d.
        usd_val = stage.GetPrimAtPath("/Sphere").GetAttribute("m4_attr").Get()
        assert isinstance(usd_val, Gf.Matrix4d)

    def test_matrix2d_set_value_writes_gf_matrix2d(self):
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        adapter.set_value("m2_attr", (10.0, 20.0, 30.0, 40.0))
        usd_val = stage.GetPrimAtPath("/Sphere").GetAttribute("m2_attr").Get()
        assert isinstance(usd_val, Gf.Matrix2d)
        assert adapter.get_value("m2_attr") == pytest.approx((10.0, 20.0, 30.0, 40.0))

    def test_matrix3d_set_value_writes_gf_matrix3d(self):
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        new_value = tuple(float(i) + 0.5 for i in range(9))
        adapter.set_value("m3_attr", new_value)
        usd_val = stage.GetPrimAtPath("/Sphere").GetAttribute("m3_attr").Get()
        assert isinstance(usd_val, Gf.Matrix3d)
        assert adapter.get_value("m3_attr") == pytest.approx(new_value)

    def test_matrix_per_component_ambiguity_returns_none(self):
        """Matrices are NOT in ``_VECTOR_VALUE_TYPES`` — per-component
        ambiguity returns ``None`` so the row falls back to whole-attribute
        ``is_ambiguous``. Step 3.5 deliberately does NOT add matrices to
        the vec-type set (per-cell ambiguity for matrices is a Phase 8
        polish, not Step 3.5)."""
        stage = self._stage_with_matrices()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert adapter.get_per_component_ambiguity("m4_attr") is None
        assert adapter.get_per_component_ambiguity("m3_attr") is None
        assert adapter.get_per_component_ambiguity("m2_attr") is None

    def test_matrix_default_value_is_identity(self):
        """Unauthored matrix attributes default to the identity matrix —
        the only sane default (a zero matrix is singular)."""
        from ovui_data_adapters.openusd.property_adapter import _default_value
        assert _default_value("matrix2d") == (1.0, 0.0, 0.0, 1.0)
        assert _default_value("matrix3d") == (
            1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
            0.0, 0.0, 1.0,
        )
        assert _default_value("matrix4d") == (
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        )


class TestAssetTypeMapping:
    """Step 3.6: ``asset`` (``SdfAssetPath``) is newly supported. Prior to
    Step 3.6 the adapter silently dropped asset-path attributes because
    ``_TYPE_MAP`` had no entry. The tests below pin the full USD-to-Python
    roundtrip: enumerate the attribute, pull its metadata, read the
    authored string, and write it back through ``set_value`` — which must
    wrap the plain string in an ``Sdf.AssetPath`` (USD rejects a raw str).

    Resolved-path surfacing (``get_resolved_asset_path``) is tested
    separately because it depends on the ArResolver finding the authored
    file; seeding a real temp file lets us prove the resolver actually
    runs without relying on the Default resolver leaving the path raw.
    """

    def _stage_with_asset(self, asset_path="asset://foo.usd"):
        """Build an in-memory stage with a Sphere carrying one ``asset``
        attribute initialised to ``asset_path``.
        """
        stage = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Sphere.Define(stage, "/Sphere").GetPrim()
        attr = prim.CreateAttribute("refAsset", Sdf.ValueTypeNames.Asset)
        attr.Set(Sdf.AssetPath(asset_path))
        return stage

    def test_asset_attribute_enumerated(self):
        stage = self._stage_with_asset()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert "refAsset" in adapter.get_attribute_names()

    def test_asset_metadata_type_name(self):
        stage = self._stage_with_asset()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("refAsset")
        assert meta.type_name == "asset"
        assert meta.value_type == "asset"

    def test_asset_read_returns_authored_string(self):
        stage = self._stage_with_asset("./relative/tex.png")
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        value = adapter.get_value("refAsset")
        assert isinstance(value, str)
        assert value == "./relative/tex.png"

    def test_asset_set_value_wraps_in_sdf_asset_path(self):
        """``set_value`` must wrap the plain string in ``Sdf.AssetPath`` —
        USD's :meth:`Usd.Attribute.Set` raises when handed a raw str for
        an asset-typed attribute. Regression guard for a latent bug that
        would otherwise surface only on first write."""
        stage = self._stage_with_asset("./a.png")
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        adapter.set_value("refAsset", "./new.png")
        usd_val = stage.GetPrimAtPath("/Sphere").GetAttribute("refAsset").Get()
        assert isinstance(usd_val, Sdf.AssetPath)
        assert usd_val.path == "./new.png"
        # Roundtrip: read back through the adapter returns the new string.
        assert adapter.get_value("refAsset") == "./new.png"

    def test_asset_default_value_is_empty_string(self):
        """Unauthored asset attributes default to the empty string so the
        StringField renders cleanly at open (not "None" or a placeholder
        token)."""
        from ovui_data_adapters.openusd.property_adapter import _default_value
        assert _default_value("asset") == ""

    def test_get_resolved_asset_path_returns_none_for_nonexistent(self):
        """USD's default ArResolver returns an empty string when it can't
        locate the asset. The adapter maps that to ``None`` so the row's
        tooltip branch sees a uniform "no resolved path" signal.
        """
        stage = self._stage_with_asset("/this/path/definitely/does/not/exist.usd")
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        resolved = adapter.get_resolved_asset_path("refAsset")
        assert resolved is None

    def test_get_resolved_asset_path_returns_path_for_existing_file(self, tmp_path):
        """When the authored path points at a real file, the ArResolver
        finds it and the adapter surfaces the absolute resolved path.
        Exercises the end-to-end resolver → adapter → row tooltip chain.
        """
        target = tmp_path / "real_asset.usd"
        target.write_text("")  # Any content works; the resolver only needs to find the file.
        stage = self._stage_with_asset(str(target))
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        resolved = adapter.get_resolved_asset_path("refAsset")
        assert resolved is not None
        # Normalise because some resolvers return a slightly different
        # symlink-resolved form than ``str(target)`` (e.g. on macOS the
        # ``/var`` vs ``/private/var`` symlink), but both should match
        # after ``os.path.realpath``.
        import os
        assert os.path.realpath(resolved) == os.path.realpath(str(target))

    def test_get_resolved_asset_path_returns_none_for_non_asset_attr(self):
        """The resolver is only defined for asset-typed attributes;
        calling it on a float attribute returns ``None`` (matches the ABC
        default) so callers don't need to branch on attribute type."""
        stage = self._stage_with_asset()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert adapter.get_resolved_asset_path("radius") is None

    def test_get_resolved_asset_path_returns_none_for_unknown_attr(self):
        """Unknown attribute name returns ``None`` — the adapter must not
        raise, since the row might call this during a rebuild after the
        attribute was removed from the prim."""
        stage = self._stage_with_asset()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert adapter.get_resolved_asset_path("__does_not_exist__") is None


class TestRelationshipTypeMapping:
    """Step 3.7: ``Usd.Relationship`` is newly supported. Prior to Step 3.7
    the adapter silently dropped relationships because ``_enumerate_attrs``
    only walked ``prim.GetAttributes()``. The tests below pin the full
    relationship surface: enumerate the relationship, check metadata,
    read the target list, update the target list externally and read
    again, and confirm ``set_value`` is a defensive no-op until the
    Phase-6 target picker ships.

    Every ``UsdGeom`` prim inherits a ``proxyPrim`` relationship from
    ``Gprim``, so the relationship walk is exercised on the default
    Sphere/Cube fixtures — no custom prim needed.
    """

    def _stage_with_relationship(self, targets=("/World/Target",)):
        """Build an in-memory stage with a Sphere whose ``proxyPrim``
        relationship points at ``targets``.

        Every ``UsdGeom`` prim already carries a ``proxyPrim``
        relationship (from ``UsdGeomImageable``); authoring targets onto
        it is the minimal path to a relationship with live target data.
        """
        stage = Usd.Stage.CreateInMemory()
        # Ensure the target paths exist so the relationship isn't dangling.
        for target in targets:
            UsdGeom.Xform.Define(stage, target)
        prim = UsdGeom.Sphere.Define(stage, "/Sphere").GetPrim()
        rel = prim.GetRelationship("proxyPrim")
        rel.SetTargets([Sdf.Path(t) for t in targets])
        return stage, prim, rel

    def test_relationship_enumerated(self):
        stage, _, _ = self._stage_with_relationship()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert "proxyPrim" in adapter.get_attribute_names()

    def test_relationship_metadata_type_name(self):
        stage, _, _ = self._stage_with_relationship()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("proxyPrim")
        assert meta.type_name == "relationship"
        assert meta.value_type == "relationship"

    def test_get_value_returns_tuple_of_strings(self):
        """``get_value`` must stringify each ``Sdf.Path`` so downstream
        Python code never sees a pxr type through the adapter boundary."""
        stage, _, _ = self._stage_with_relationship(("/World/T1", "/World/T2"))
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        value = adapter.get_value("proxyPrim")
        assert isinstance(value, tuple)
        assert all(isinstance(t, str) for t in value)
        assert value == ("/World/T1", "/World/T2")

    def test_get_value_for_empty_relationship(self):
        """A relationship with zero targets surfaces as an empty tuple —
        matching ``_default_value("relationship")`` and the row's "empty
        StringField" behaviour."""
        stage = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Sphere.Define(stage, "/Sphere").GetPrim()
        # proxyPrim exists on every UsdGeomImageable but has no authored
        # targets by default.
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert adapter.get_value("proxyPrim") == ()

    def test_get_value_for_single_target(self):
        stage, _, _ = self._stage_with_relationship(("/World/OnlyOne",))
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert adapter.get_value("proxyPrim") == ("/World/OnlyOne",)

    def test_get_value_for_multiple_targets(self):
        stage, _, _ = self._stage_with_relationship(
            ("/World/A", "/World/B", "/World/C")
        )
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert adapter.get_value("proxyPrim") == (
            "/World/A",
            "/World/B",
            "/World/C",
        )

    def test_set_value_is_noop(self):
        """Step 3.7: relationships are read-only at the Property Inspector
        level. ``set_value`` on a relationship must NOT clear / overwrite
        the targets. Pins the defensive no-op against a regression that
        would lose data on stray calls (an edit picker ships later in
        Phase 6)."""
        stage, _, rel = self._stage_with_relationship(("/World/Kept",))
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        adapter.set_value("proxyPrim", ("/World/Garbage",))
        # Targets unchanged on the USD side:
        actual = [str(t) for t in rel.GetTargets()]
        assert actual == ["/World/Kept"]
        # Adapter reads unchanged too:
        assert adapter.get_value("proxyPrim") == ("/World/Kept",)

    def test_default_value_is_empty_tuple(self):
        """Unauthored / invalid relationships default to an empty tuple
        so the row's ``_format_relationship_targets`` helper yields the
        empty string for the StringField."""
        from ovui_data_adapters.openusd.property_adapter import _default_value
        assert _default_value("relationship") == ()

    def test_per_component_ambiguity_returns_none(self):
        """Relationships are tuple-like but not vector channels; the
        per-component ambiguity hook must return ``None`` so the row
        doesn't try to apply per-channel ambiguity styling."""
        stage, _, _ = self._stage_with_relationship()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert adapter.get_per_component_ambiguity("proxyPrim") is None

    def test_relationship_enumerates_alongside_attributes(self):
        """Every UsdGeom prim carries both a ``radius`` float attribute
        AND a ``proxyPrim`` relationship — both should appear in the
        enumerated name list so the Property Inspector renders both."""
        stage, _, _ = self._stage_with_relationship()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        names = adapter.get_attribute_names()
        assert "radius" in names
        assert "proxyPrim" in names


# ── Step 3.8: Array attribute handling ────────────────────────────────────────

class TestArrayTypeMapping:
    """Step 3.8: USD array-typed attributes (``float[]``, ``token[]``,
    ``float3[]``, …) no longer silently dropped by ``_enumerate_attrs``.
    All route through the single ``"array"`` sentinel; element type is
    preserved on :class:`UsdAttributeProp.usd_type_str` for potential
    future tooltip/debug use but never reaches ``WidgetBuilderTable``
    dispatch as-is.
    """

    def _stage_with_arrays(self):
        """Author a small and a big ``float[]`` plus a ``token[]`` on a
        Sphere so tests exercise every array branch without relying on
        schema-provided array attributes (which are harder to probe
        deterministically across USD versions)."""
        stage = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Sphere.Define(stage, "/Sphere").GetPrim()
        small = prim.CreateAttribute(
            "mySmallArr", Sdf.ValueTypeNames.FloatArray
        )
        small.Set([1.0, 2.0, 3.0, 4.0])
        big = prim.CreateAttribute("myBigArr", Sdf.ValueTypeNames.FloatArray)
        big.Set([float(i) for i in range(20)])
        tokens = prim.CreateAttribute(
            "myTokenArr", Sdf.ValueTypeNames.TokenArray
        )
        tokens.Set(["a", "b", "c"])
        return stage

    def test_small_array_enumerated(self):
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert "mySmallArr" in adapter.get_attribute_names()

    def test_big_array_enumerated(self):
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert "myBigArr" in adapter.get_attribute_names()

    def test_token_array_enumerated(self):
        """Step 3.8 also covers non-numeric array element types. Prior
        to 3.8, ``token[]`` attributes (e.g. ``xformOpOrder``) were
        silently dropped."""
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert "myTokenArr" in adapter.get_attribute_names()

    def test_array_type_name_is_sentinel(self):
        """``type_name`` dispatch key is always ``"array"`` for array
        attributes — regardless of element type — so the single
        ``build_array`` registration covers every USD array token."""
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert adapter.get_attribute_metadata("mySmallArr").type_name == "array"
        assert adapter.get_attribute_metadata("myBigArr").type_name == "array"
        assert adapter.get_attribute_metadata("myTokenArr").type_name == "array"

    def test_array_value_type_is_array(self):
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("mySmallArr")
        assert meta.value_type == "array"

    def test_is_big_array_false_for_short_array(self):
        """Length-4 array is below the 16-element threshold → small."""
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("mySmallArr")
        assert meta.is_big_array is False

    def test_is_big_array_true_for_long_array(self):
        """Length-20 array is above the 16-element threshold → big."""
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("myBigArr")
        assert meta.is_big_array is True

    def test_is_big_array_false_at_exact_threshold(self):
        """Boundary: an array with exactly 16 elements is NOT big — the
        threshold is strict ``len > 16``, matching property metadata behavior's
        "arrays > 16 elements" wording."""
        stage = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Sphere.Define(stage, "/S").GetPrim()
        attr = prim.CreateAttribute("arr", Sdf.ValueTypeNames.FloatArray)
        attr.Set([float(i) for i in range(16)])
        adapter = UsdPropertyAdapter(stage, ["/S"])
        assert adapter.get_attribute_metadata("arr").is_big_array is False

    def test_is_big_array_true_above_threshold(self):
        """Boundary: 17-element array IS big."""
        stage = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Sphere.Define(stage, "/S").GetPrim()
        attr = prim.CreateAttribute("arr", Sdf.ValueTypeNames.FloatArray)
        attr.Set([float(i) for i in range(17)])
        adapter = UsdPropertyAdapter(stage, ["/S"])
        assert adapter.get_attribute_metadata("arr").is_big_array is True

    def test_get_value_returns_tuple(self):
        """``get_value`` normalises USD's ``Vt.FloatArray`` to a plain
        Python tuple — the row's formatter relies on tuple semantics
        and callers never need to know about pxr types."""
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        val = adapter.get_value("mySmallArr")
        assert isinstance(val, tuple)
        assert val == pytest.approx((1.0, 2.0, 3.0, 4.0))

    def test_get_value_returns_full_big_array(self):
        """Big-array ``get_value`` returns the raw ``Vt.*Array`` directly
        rather than materialising a Python tuple — avoids the O(N)
        allocation that stalled selection on a 100K-point mesh
        (BUG-D003). The value still exposes ``__len__`` (O(1) on
        VtArrays) so the row's ``_format_array_value`` helper produces
        ``"[N items]"`` without iterating. A future "expand inline" UX
        can still call ``tuple(adapter.get_value(…))`` to materialise if
        it genuinely needs the elements."""
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        val = adapter.get_value("myBigArr")
        # ``myBigArr`` is a ``float[]`` of length 20 (> the big-array
        # threshold of 16). The adapter must NOT tuple-convert it.
        assert not isinstance(val, tuple), (
            f"big arrays must stay as VtArray, got tuple (size {len(val)})"
        )
        assert len(val) == 20
        # The caller can still iterate or index if needed; VtArray
        # exposes both.
        assert float(val[0]) == 0.0
        assert float(val[19]) == 19.0

    def test_get_value_token_array_contents(self):
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        val = adapter.get_value("myTokenArr")
        assert tuple(str(t) for t in val) == ("a", "b", "c")

    def test_set_value_is_noop(self):
        """Arrays are read-only at the Property Inspector level.
        ``set_value`` is a defensive no-op so a stray programmatic
        write cannot attempt the ``tuple → Vt.*Array`` conversion
        (which would raise mid-edit) and cannot corrupt the stage."""
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        adapter.set_value("mySmallArr", (9.0, 9.0, 9.0, 9.0))
        # Underlying USD attribute unchanged:
        raw = stage.GetPrimAtPath("/Sphere").GetAttribute("mySmallArr").Get()
        assert tuple(raw) == pytest.approx((1.0, 2.0, 3.0, 4.0))
        # Adapter re-read unchanged:
        assert adapter.get_value("mySmallArr") == pytest.approx(
            (1.0, 2.0, 3.0, 4.0)
        )

    def test_default_value_is_empty_tuple(self):
        """Unauthored / invalid arrays default to an empty tuple so the
        row's ``_format_array_value`` helper yields ``"()"`` for the
        StringField (distinct from the ``""`` fallback used for a
        ``None`` value during a rebuild transient)."""
        from ovui_data_adapters.openusd.property_adapter import _default_value
        assert _default_value("array") == ()

    def test_per_component_ambiguity_returns_none(self):
        """Arrays aren't vector channels; per-component ambiguity must
        return ``None`` so the row doesn't try per-channel styling."""
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        assert adapter.get_per_component_ambiguity("mySmallArr") is None

    def test_extent_enumerated_as_array(self):
        """Step 3.8: the Sphere's inherited ``extent`` attribute
        (``float3[]``) now enumerates. Pin that the inherited schema
        attribute path also lands on the array sentinel."""
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, "/Sphere")
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("extent")
        assert meta.type_name == "array"
        assert meta.value_type == "array"

    def test_array_usd_type_string_preserved_internally(self):
        """The USD type string (``"float[]"``, ``"token[]"``, …) is
        preserved on the underlying ``UsdAttributeProp.usd_type_str``
        for potential tooltip/debug use, even though dispatch uses the
        ``"array"`` sentinel. Pins the design choice."""
        stage = self._stage_with_arrays()
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        # ``_props`` is internal but pinning it here catches a future
        # refactor that forgets to preserve the original USD type.
        prop = adapter._props["mySmallArr"]
        assert prop.usd_type_str == "float[]"
        assert prop.value_type == "array"

    def test_array_enumerates_alongside_scalars(self):
        """A Sphere with a ``double`` radius AND a ``float[]`` array
        enumerates both — the array branch doesn't accidentally mask
        the scalar branch in ``_enumerate_attrs``."""
        stage = self._stage_with_arrays()
        stage.GetPrimAtPath("/Sphere").GetAttribute("radius").Set(2.5)
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        names = adapter.get_attribute_names()
        assert "radius" in names
        assert "mySmallArr" in names


class TestCustomDataRangeMetadata:
    """Step 4.1: ``UsdPropertyAdapter.get_attribute_metadata`` surfaces
    ``customData["range"]`` / ``customData["soft_range"]`` as
    ``AttributeMetadata.hard_range_*`` / ``soft_range_*``.

    Kit's convention (the property inspector behavior) stores drag
    bounds in the attribute's ``customData`` dict. The adapter reads
    those keys at metadata-construction time so the row's FloatDrag/
    IntDrag picks them up via :func:`_drag_kwargs_from_metadata` and
    the model clamp fires on out-of-range writes.
    """

    def _sphere_with_radius_custom_data(self, custom_data):
        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
        attr = sphere.GetRadiusAttr()
        attr.Set(1.0)
        attr.SetCustomData(custom_data)
        return stage

    def test_no_custom_data_ranges_are_none(self):
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, "/Sphere").GetRadiusAttr().Set(1.0)
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.soft_range_min is None
        assert meta.soft_range_max is None
        assert meta.hard_range_min is None
        assert meta.hard_range_max is None

    def test_hard_range_surfaced(self):
        stage = self._sphere_with_radius_custom_data(
            {"range": {"min": 0.0, "max": 10.0}}
        )
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.hard_range_min == 0.0
        assert meta.hard_range_max == 10.0

    def test_hard_range_doubles_as_soft_when_soft_missing(self):
        """the property inspector behavior: when ``soft_range`` is
        absent, the hard range doubles as the soft range so the drag
        handle respects the clamp even mid-drag."""
        stage = self._sphere_with_radius_custom_data(
            {"range": {"min": 0.0, "max": 10.0}}
        )
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.soft_range_min == 0.0
        assert meta.soft_range_max == 10.0

    def test_explicit_soft_range_overrides_hard(self):
        stage = self._sphere_with_radius_custom_data({
            "range": {"min": 0.0, "max": 1e6},
            "soft_range": {"min": 0.0, "max": 100.0},
        })
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.hard_range_min == 0.0
        assert meta.hard_range_max == 1e6
        assert meta.soft_range_min == 0.0
        assert meta.soft_range_max == 100.0

    def test_partial_range_keeps_other_field_none(self):
        stage = self._sphere_with_radius_custom_data(
            {"range": {"min": 0.0}}  # no "max"
        )
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.hard_range_min == 0.0
        assert meta.hard_range_max is None

    def test_malformed_range_falls_back_to_none(self):
        """A malformed author-side ``range = {"min": "not-a-number"}``
        must not raise at widget-construction time; the bound stays
        ``None`` so the row falls back to the unbounded default."""
        stage = self._sphere_with_radius_custom_data(
            {"range": {"min": "not-a-number"}}
        )
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.hard_range_min is None

    def test_range_bound_helper_coerces_ints(self):
        """The helper accepts ints (author-side ``{"min": 0}`` is the
        common case) and produces a ``float``."""
        from ovui_data_adapters.openusd.property_adapter import _range_bound
        assert _range_bound({"min": 0}, "min") == 0.0
        assert isinstance(_range_bound({"min": 0}, "min"), float)

    def test_range_bound_helper_handles_missing_key(self):
        from ovui_data_adapters.openusd.property_adapter import _range_bound
        assert _range_bound({"max": 1.0}, "min") is None

    def test_range_bound_helper_handles_non_dict(self):
        """Defensive: a corrupt customData entry (e.g. a list instead
        of a dict) must not raise."""
        from ovui_data_adapters.openusd.property_adapter import _range_bound
        assert _range_bound(None, "min") is None
        assert _range_bound([0, 1], "min") is None


class TestTimeSampledLockedAuthored:
    """Step 4.2: ``UsdPropertyAdapter.get_attribute_metadata`` populates
    the three read-only state flags (``is_time_sampled``, ``is_locked``,
    ``is_authored``) from the underlying USD attribute so rows can gate
    ``widget.enabled`` and label styling without re-reading USD.

    Conventions (property metadata behavior, the property inspector behavior):

    * ``is_time_sampled = attr.GetNumTimeSamples() > 0`` — any number of
      samples qualifies.
    * ``is_locked = bool(customData["locked"])`` — custom-metadata
      convention since ``omni.kit.usd.layers`` isn't a dependency.
    * ``is_authored = attr.IsAuthored()`` — explicit opinion on at
      least one layer.
    """

    def _sphere(self, setter=None, custom_data=None):
        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
        if setter is not None:
            setter(sphere.GetRadiusAttr())
        if custom_data is not None:
            sphere.GetRadiusAttr().SetCustomData(custom_data)
        return stage

    def test_defaults_for_plain_attribute(self):
        """Unauthored / unlocked / not-time-sampled attribute → all
        defaults (False / False / True-when-authored-or-False-when-not)."""
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, "/Sphere").GetRadiusAttr().Set(1.0)
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.is_time_sampled is False
        assert meta.is_locked is False
        assert meta.is_authored is True

    def test_time_sampled_flag_surfaced(self):
        """A single ``.Set(v, time=t)`` call authors one time sample —
        enough to flip the flag."""
        stage = self._sphere(setter=lambda a: a.Set(1.0, time=0))
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.is_time_sampled is True

    def test_time_sampled_flag_false_with_default_only(self):
        """``.Set(v)`` (no time=) writes a default opinion, not a
        sample — ``is_time_sampled`` must stay False."""
        stage = self._sphere(setter=lambda a: a.Set(1.0))
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.is_time_sampled is False

    def test_locked_flag_from_custom_data(self):
        """``customData["locked"] = True`` → ``is_locked=True``."""
        stage = self._sphere(
            setter=lambda a: a.Set(1.0),
            custom_data={"locked": True},
        )
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.is_locked is True

    def test_locked_flag_false_when_custom_data_explicitly_false(self):
        stage = self._sphere(
            setter=lambda a: a.Set(1.0),
            custom_data={"locked": False},
        )
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.is_locked is False

    def test_locked_flag_false_when_custom_data_missing(self):
        """No ``customData["locked"]`` key → ``is_locked=False`` (default
        per property metadata behavior)."""
        stage = self._sphere(
            setter=lambda a: a.Set(1.0),
            custom_data={"other_key": "value"},
        )
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.is_locked is False

    def test_is_authored_false_for_schema_default(self):
        """Radius left unauthored → ``IsAuthored()`` is False → label
        should render muted. Pins the unauthored → dimmed-label path."""
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, "/Sphere")
        # Do NOT set the radius; it stays at the schema default.
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.is_authored is False

    def test_is_authored_true_after_explicit_set(self):
        stage = self._sphere(setter=lambda a: a.Set(2.5))
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.is_authored is True

    def test_all_three_flags_coexist(self):
        """A single attribute can be time-sampled AND locked AND
        authored simultaneously — the flags are orthogonal."""
        stage = self._sphere(
            setter=lambda a: a.Set(1.0, time=0),
            custom_data={"locked": True},
        )
        adapter = UsdPropertyAdapter(stage, ["/Sphere"])
        meta = adapter.get_attribute_metadata("radius")
        assert meta.is_time_sampled is True
        assert meta.is_locked is True
        assert meta.is_authored is True

    def test_relationship_falls_through_to_defaults(self):
        """Relationships don't have ``GetNumTimeSamples`` / ``IsAuthored``
        attribute semantics; the early ``value_type != "relationship"``
        skip keeps the adapter from calling them and the three flags
        stay at their dataclass defaults (False / False / True).
        """
        stage = Usd.Stage.CreateInMemory()
        prim = UsdGeom.Xform.Define(stage, "/X").GetPrim()
        rel = prim.CreateRelationship("proxyPrim")
        rel.AddTarget("/X")
        adapter = UsdPropertyAdapter(stage, ["/X"])
        meta = adapter.get_attribute_metadata("proxyPrim")
        assert meta.is_time_sampled is False
        assert meta.is_locked is False
        assert meta.is_authored is True


# ── Deep QA regressions (BUG-D001 / D003 / D004 / D005) ───────────────────────

class TestDeepQARegressions:
    """Regressions for bugs surfaced by the Property Window deep-QA pass
    (``tests/qa_property_deep.py``, branch ``qa-property-deep``). Each test
    pins one bug so an unrelated refactor can't silently revive it.
    """

    def test_BUG_D001_stage_backed_subscribe_drops_event_arg(self):
        """Stage-backed adapters deliver change events to ``_on_backing_changed``-
        style callbacks that take *no* args. ``UsdStageAdapter`` fires with
        a ``ChangeEvent`` argument; the property-adapter wrapper must drop
        it. Without the fix the notify loop raised ``TypeError`` mid-frame
        and every property row silently stopped refreshing."""
        from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter

        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
        sphere.GetRadiusAttr().Set(1.0)
        sa = UsdStageAdapter(stage)
        pa = UsdPropertyAdapter(
            stage, ["/Sphere"], UndoManager(), stage_adapter=sa
        )
        fired: list = []

        def noarg_cb() -> None:
            fired.append(1)

        # ``Subscription.__del__`` unsubscribes when the handle drops;
        # keep a reference alive for the duration of the test.
        sub = pa.subscribe_changes(noarg_cb)
        assert sub is not None
        sphere.GetRadiusAttr().Set(5.0)
        sa._flush()  # drive the deferred notify loop synchronously
        assert fired, "stage-backed subscribe delivered zero events"

    def test_BUG_D003_big_array_get_value_skips_tuple_copy(self):
        """For arrays above the big threshold the adapter returns the
        raw ``Vt.*Array`` rather than materialising a Python tuple. This
        is the fix for the 100K-point mesh stall: tupling 100K Gf.Vec3f
        wrappers allocated ~30 MB and blocked the frame loop for several
        seconds."""
        stage = Usd.Stage.CreateInMemory()
        mesh = UsdGeom.Mesh.Define(stage, "/M")
        from pxr import Vt
        mesh.GetPointsAttr().Set(
            Vt.Vec3fArray([Gf.Vec3f(0.0, 0.0, 0.0)] * 10000)
        )
        pa = UsdPropertyAdapter(stage, ["/M"])
        val = pa.get_value("points")
        # The raw VtArray must come back (no Python tuple allocation).
        assert not isinstance(val, tuple), (
            f"big array must not be tuple-wrapped, got {type(val).__name__}"
        )
        assert len(val) == 10000

    def test_BUG_D003_small_array_still_tuple_wrapped(self):
        """Small arrays (≤ threshold) continue to return a Python tuple
        so the small-array display formatter can run ``str(tuple(x))``
        cheaply without iterating twice."""
        stage = Usd.Stage.CreateInMemory()
        cube = UsdGeom.Cube.Define(stage, "/C")
        from pxr import Vt
        attr = cube.GetPrim().CreateAttribute(
            "custom:small", Sdf.ValueTypeNames.FloatArray
        )
        attr.Set(Vt.FloatArray([1.0, 2.0, 3.0]))
        pa = UsdPropertyAdapter(stage, ["/C"])
        val = pa.get_value("custom:small")
        assert isinstance(val, tuple)
        assert val == pytest.approx((1.0, 2.0, 3.0))

    def test_BUG_D004_clear_value_resets_is_authored_flag(self):
        """After ``clear_value`` the NotDefault indicator must go away.
        ``is_authored`` is read via ``HasAuthoredValue()`` — not
        ``IsAuthored()``, which stays ``True`` because the attribute
        spec (typeName / custom / variability) persists on the edit
        target even after ``Clear()`` removes the value opinion."""
        stage = Usd.Stage.CreateInMemory()
        sphere = UsdGeom.Sphere.Define(stage, "/Sphere")
        sphere.GetRadiusAttr().Set(2.5)
        pa = UsdPropertyAdapter(stage, ["/Sphere"], UndoManager())
        assert pa.get_attribute_metadata("radius").is_authored is True
        pa.clear_value("radius")
        assert pa.get_attribute_metadata("radius").is_authored is False
        # Value must be back to the schema default.
        assert sphere.GetRadiusAttr().Get() == 1.0


class TestDeepQAFormatterRegressions:
    """Regressions for the display-string formatter fixes in
    ``ovwidgets.property/attribute_row.py``. Lives here (alongside the adapter
    tests) because the formatter's invariants are tested against USD
    values produced by this adapter."""

    def test_BUG_D005a_formatter_autodetects_big_vs_small(self):
        """``is_big_array=None`` lets the formatter pick the mode from
        the value's current length. Required so a USD edit that crosses
        the threshold flips display modes without the row rebuilding."""
        from ovwidgets.property.attribute_row import _format_array_value
        # Small → tuple repr.
        assert _format_array_value((1.0, 2.0, 3.0)) == "(1.0, 2.0, 3.0)"
        # Big (> 16) → "[N items]".
        big_tuple = tuple(range(100))
        assert _format_array_value(big_tuple) == "[100 items]"

    def test_BUG_D005a_array_row_follows_threshold_crossings(self):
        """Emulates a row's live-refresh path: initial build sees a
        50K array → "[50000 items]"; USD edit shrinks to 3 elements →
        the formatter (called with ``is_big_array=None``) correctly
        switches to the tuple-repr form."""
        from ovwidgets.property.attribute_row import _format_array_value

        stage = Usd.Stage.CreateInMemory()
        cube = UsdGeom.Cube.Define(stage, "/C")
        from pxr import Vt
        attr = cube.GetPrim().CreateAttribute(
            "custom:arr", Sdf.ValueTypeNames.FloatArray
        )
        attr.Set(Vt.FloatArray([float(i) for i in range(50000)]))
        pa = UsdPropertyAdapter(stage, ["/C"])
        # Initial (big) — autodetect yields "[N items]".
        assert _format_array_value(pa.get_value("custom:arr")) == "[50000 items]"
        # Shrink (small) — autodetect yields the tuple repr.
        attr.Set(Vt.FloatArray([1.0, 2.0, 3.0]))
        assert _format_array_value(pa.get_value("custom:arr")) == "(1.0, 2.0, 3.0)"
        # Grow back — autodetect flips back to "[N items]".
        attr.Set(Vt.FloatArray([float(i) for i in range(20000)]))
        assert _format_array_value(pa.get_value("custom:arr")) == "[20000 items]"

    def test_BUG_D005b_small_vec3f_array_hides_gf_repr(self):
        """The Sphere's ``extent`` attribute is a tiny ``Vec3fArray``
        (two Vec3f corners). Pre-fix the row showed
        ``"(Gf.Vec3f(-1.0, -1.0, -1.0), …)"``; the normalizer flattens
        each element to a plain tuple so the repr stays clean."""
        from ovwidgets.property.attribute_row import _format_array_value
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.Sphere.Define(stage, "/S")
        pa = UsdPropertyAdapter(stage, ["/S"])
        val = pa.get_value("extent")
        rendered = _format_array_value(val, is_big_array=False)
        assert "Gf.Vec3f" not in rendered, (
            f"Gf class name leaked into Property Inspector: {rendered!r}"
        )
        # Expect nested tuples — two Vec3 corners.
        assert "(-1.0, -1.0, -1.0)" in rendered
        assert "(1.0, 1.0, 1.0)" in rendered

    def test_BUG_D005_normalize_scalar_elements_unchanged(self):
        """Plain-Python scalars pass through the normalizer unchanged;
        the fix must not accidentally rewrite ``(1, 2, 3)`` → something
        nested."""
        from ovwidgets.property.attribute_row import _format_array_value
        assert _format_array_value((1, 2, 3), is_big_array=False) == "(1, 2, 3)"
        assert _format_array_value(("a", "b"), is_big_array=False) == "('a', 'b')"
        # Boolean passthrough (bool is a subtype of int; still a scalar).
        assert _format_array_value((True, False), is_big_array=False) == "(True, False)"
