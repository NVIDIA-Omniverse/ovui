# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The native material plan reads the CURRENT OVStage scene, without OpenUSD."""

from __future__ import annotations

import struct
import sys

import pytest

from ovui_data_adapters.ovstage import _material_plan as mp

FLOAT, COLOR, CONNECTION, ASSET = ((2, 32, 1), 0), ((2, 32, 3), 8), ((1, 64, 2), 12), ((1, 64, 2), 1)


class FakeStage:
    """The read surface that the plan uses: attribute bytes and their layout, and targets, at the current ordinal."""

    current_ordinal = 7

    def __init__(self):
        self.attrs, self.info, self.targets = {}, {}, {}

    def read_attribute(self, ordinal, paths, name):
        assert ordinal == self.current_ordinal
        return self.attrs.get((paths[0], name), b"")

    def read_attribute_info(self, ordinal, path, name):
        layout = self.info.get((path, name))
        if layout is None:
            raise KeyError(name)
        return {"dtype": layout[0], "semantic": layout[1], "is_array": False}

    def read_path_targets(self, ordinal, path, name):
        return self.targets.get((path, name))

    def put(self, path, name, layout, raw):
        self.attrs[(path, name)] = raw
        self.info[(path, name)] = layout

    def color(self, path, name, r, g, b):
        self.put(path, name, COLOR, struct.pack("<3f", r, g, b))

    def number(self, path, name, value):
        self.put(path, name, FLOAT, struct.pack("<f", value))

    def connect(self, path, name, source):
        self.put(path, name, CONNECTION, struct.pack("<QQ", 1, 2))
        self.targets[(path, name)] = (source,)


def extent(low, high):
    return struct.pack("<6f", *low, *high)


SHADER_INPUTS = ("info:id", "info:mdl:sourceAsset", "inputs:base_color", "inputs:base_weight", "inputs:specular_weight",
                 "inputs:specular_roughness", "inputs:diffuse_color_constant", "inputs:albedo_brightness",
                 "inputs:diffuseColor", "inputs:emission_luminance", "inputs:metallic_constant", "inputs:file")


@pytest.fixture
def scene(monkeypatch):
    monkeypatch.setitem(sys.modules, "pxr", None)  # a native-only install: any import of OpenUSD fails
    monkeypatch.setattr(mp, "resolve_token_id", lambda stage, token: {101: "./runner.mdl", 102: "/data/runner.mdl"}.get(token, ""))
    stage = FakeStage()
    records = {
        "/W": "Xform", "/W/Looks/Flat": "Material", "/W/Looks/Flat/Surface": "Shader",
        "/W/Looks/Mdl": "Material", "/W/Looks/Mdl/mdl": "Shader",
        "/W/Looks/Tex": "Material", "/W/Looks/Tex/Surface": "Shader", "/W/Looks/Tex/albedo": "Shader",
        "/W/Looks/Unused": "Material", "/W/Looks/Unused/Surface": "Shader",
        "/W/Flat_geo": "Cube", "/W/Mdl_geo": "Sphere", "/W/Tex_geo": "Cube",
        "/W/Group": "Xform", "/W/Group/Inner_geo": "Mesh",
    }
    names = {path: SHADER_INPUTS for path, kind in records.items() if kind == "Shader"}
    stage.attrs[("/W/Looks/Flat/Surface", "info:id")] = b"ND_open_pbr_surface_surfaceshader"
    stage.color("/W/Looks/Flat/Surface", "inputs:base_color", 0.5, 0.25, 0.125)
    stage.connect("/W/Looks/Flat", "outputs:mtlx:surface", "/W/Looks/Flat/Surface.outputs:out")
    stage.put("/W/Looks/Mdl/mdl", "info:mdl:sourceAsset", ASSET, struct.pack("<QQ", 101, 102))
    stage.color("/W/Looks/Mdl/mdl", "inputs:diffuse_color_constant", 0.55, 0.02, 0.06)
    stage.connect("/W/Looks/Mdl", "outputs:mdl:surface", "/W/Looks/Mdl/mdl.outputs:out")
    stage.attrs[("/W/Looks/Tex/Surface", "info:id")] = b"ND_open_pbr_surface_surfaceshader"
    stage.connect("/W/Looks/Tex/Surface", "inputs:base_color", "/W/Looks/Tex/albedo.outputs:out")
    stage.connect("/W/Looks/Tex", "outputs:mtlx:surface", "/W/Looks/Tex/Surface.outputs:out")
    stage.attrs[("/W/Looks/Tex/albedo", "info:id")] = b"ND_image_color3"
    stage.attrs[("/W/Looks/Unused/Surface", "info:id")] = b"UsdPreviewSurface"
    stage.color("/W/Looks/Unused/Surface", "inputs:diffuseColor", 1, 0, 0)
    stage.targets[("/W/Flat_geo", "material:binding")] = ("/W/Looks/Flat",)
    stage.targets[("/W/Mdl_geo", "material:binding")] = ("/W/Looks/Mdl",)
    stage.targets[("/W/Tex_geo", "material:binding")] = ("/W/Looks/Tex",)
    stage.targets[("/W/Group", "material:binding")] = ("/W/Looks/Mdl",)  # an inherited binding
    for geo, size in (("/W/Flat_geo", 2.0), ("/W/Mdl_geo", 2.6), ("/W/Tex_geo", 2.0), ("/W/Group/Inner_geo", 1.0)):
        stage.attrs[(geo, "extent")] = extent((-size / 2,) * 3, (size / 2,) * 3)
    return stage, records, names


def plan(scene, **kwargs):
    stage, records, names = scene
    return mp.plan_native(stage, records, names, **kwargs)


def test_constants_and_geometry_are_read_from_the_native_stage(scene):
    todo, skipped = plan(scene)
    by_path = {item["path"]: item for item in todo}
    flat = by_path["/W/Looks/Flat"]
    assert flat["family"] == "materialx" and flat["linear"] == pytest.approx((0.5, 0.25, 0.125))
    assert flat["identifier"] == "ND_open_pbr_surface_surfaceshader" and flat["colour_input"] == "base_color"
    assert (flat["source"], flat["size"], flat["centre"]) == ("/W/Flat_geo", 2.0, (0.0, 0.0, 0.0))
    runner = by_path["/W/Looks/Mdl"]
    assert runner["family"] == "mdl" and runner["linear"] == pytest.approx((0.55, 0.02, 0.06))
    assert runner["source"] == "/W/Mdl_geo" and runner["size"] == pytest.approx(2.6)


def test_what_the_native_check_cannot_tell_is_unverifiable_with_the_reason_never_guessed(scene):
    _todo, skipped = plan(scene)
    assert skipped["/W/Looks/Tex"]["reason"] == (
        "base_color comes from another shader (an image); the native check reads constant colours only")
    assert "no geometry" in skipped["/W/Looks/Unused"]["reason"]
    assert all(item["state"] == "unverifiable" for item in skipped.values())


def test_the_reference_keeps_the_shading_controls_of_an_openpbr_material(scene):
    """Review: base_weight 0 and specular_weight 0 make a valid black OpenPBR; the reference must be black too."""

    stage, _records, _names = scene
    stage.number("/W/Looks/Flat/Surface", "inputs:base_weight", 0.0)
    stage.number("/W/Looks/Flat/Surface", "inputs:specular_weight", 0.0)
    stage.connect("/W/Looks/Flat/Surface", "inputs:specular_roughness", "/W/Looks/Flat/Rough.outputs:out")  # a map: ignored
    flat = {item["path"]: item for item in plan(scene)[0]}["/W/Looks/Flat"]
    assert flat["inputs"] == [("float", "base_weight", "0.0"), ("float", "specular_weight", "0.0")]


def test_a_control_that_the_reference_cannot_reproduce_makes_the_material_not_checkable(scene):
    stage, _records, _names = scene
    stage.connect("/W/Looks/Flat/Surface", "inputs:base_weight", "/W/Looks/Flat/Mask.outputs:out")
    stage.number("/W/Looks/Mdl/mdl", "inputs:albedo_brightness", 0.0)
    _todo, skipped = plan(scene)
    assert skipped["/W/Looks/Flat"]["reason"] == "base_weight comes from another shader; the reference cannot reproduce it"
    assert "the MDL shader sets albedo_brightness" in skipped["/W/Looks/Mdl"]["reason"]


def test_the_shader_of_the_material_output_is_checked_not_another_surface_of_the_material(scene):
    stage, records, names = scene
    # Another surface shader under the material, before the connected one in path order.
    records["/W/Looks/Flat/A_Other"] = "Shader"
    names["/W/Looks/Flat/A_Other"] = SHADER_INPUTS
    stage.attrs[("/W/Looks/Flat/A_Other", "info:id")] = b"UsdPreviewSurface"
    stage.color("/W/Looks/Flat/A_Other", "inputs:diffuseColor", 0, 1, 0)
    flat = {item["path"]: item for item in plan(scene)[0]}["/W/Looks/Flat"]
    assert flat["family"] == "materialx" and flat["linear"] == pytest.approx((0.5, 0.25, 0.125))
    # A native stage that holds no connections (older ovstage): the first surface shader of the material.
    del stage.targets[("/W/Looks/Flat", "outputs:mtlx:surface")]
    flat = {item["path"]: item for item in plan(scene)[0]}["/W/Looks/Flat"]
    assert flat["family"] == "preview" and flat["linear"] == pytest.approx((0, 1, 0))


def test_an_edit_is_judged_as_it_is_now_and_not_as_on_disk(scene):
    stage, _records, _names = scene
    before = {i["path"]: i for i in plan(scene)[0]}["/W/Looks/Flat"]["linear"]
    stage.color("/W/Looks/Flat/Surface", "inputs:base_color", 0.05, 0.2, 0.7)  # edited after the scene was opened
    after = {i["path"]: i for i in plan(scene)[0]}["/W/Looks/Flat"]["linear"]
    assert before == pytest.approx((0.5, 0.25, 0.125)) and after == pytest.approx((0.05, 0.2, 0.7))
    # rebinding and resizing too: the geometry that the material is bound to now is the one that is drawn
    stage.targets[("/W/Flat_geo", "material:binding")] = ("/W/Looks/Unused",)
    stage.attrs[("/W/Flat_geo", "extent")] = extent((-3, -3, -3), (3, 3, 3))
    todo, skipped = plan(scene)
    by_path = {i["path"]: i for i in todo}
    assert "/W/Looks/Flat" in skipped and by_path["/W/Looks/Unused"]["size"] == 6.0


def test_a_binding_on_an_ancestor_is_found(scene):
    stage, _records, _names = scene
    del stage.targets[("/W/Mdl_geo", "material:binding")]
    del stage.attrs[("/W/Mdl_geo", "extent")]
    todo, _ = plan(scene)
    assert {i["path"]: i for i in todo}["/W/Looks/Mdl"]["source"] == "/W/Group/Inner_geo"


def test_a_material_that_uses_emission_or_opacity_is_unverifiable(scene):
    stage, _records, _names = scene
    stage.number("/W/Looks/Flat/Surface", "inputs:emission_luminance", 5.0)
    _todo, skipped = plan(scene)
    assert "emission_luminance" in skipped["/W/Looks/Flat"]["reason"]


def test_the_prefix_and_the_limit_select_materials(scene):
    todo, skipped = plan(scene, path_prefix="/W/Looks/M")
    assert [i["path"] for i in todo] == ["/W/Looks/Mdl"] and skipped == {}
    todo, skipped = plan(scene, limit=1)
    planned = [path for path, item in skipped.items() if item["state"] != "not_reached"]
    assert len(todo) + len(planned) == 1
    # The materials after the limit are reported as not reached, not dropped.
    rest = [item for item in skipped.values() if item["state"] == "not_reached"]
    assert rest and all("stops after 1 materials" in item["reason"] for item in rest)


def test_the_files_of_the_native_shaders_are_read_with_their_material(scene, monkeypatch, tmp_path):
    stage, records, _names = scene
    present = tmp_path / "runner.mdl"
    present.write_text("mdl 1.6;")
    tokens = {101: "./runner.mdl", 102: str(present), 201: "./albedo.png", 301: "./gone.png", 302: str(tmp_path / "gone.png"),
              401: "./sky.hdr", 402: str(tmp_path / "sky.hdr")}
    monkeypatch.setattr(mp, "resolve_token_id", lambda stage, token: tokens.get(token, ""))
    values = {
        ("/W/Looks/Mdl/mdl", "info:mdl:sourceAsset"): (struct.pack("<QQ", 101, 102), 1),
        ("/W/Looks/Mdl/mdl", "inputs:diffuse_color_constant"): (struct.pack("<3f", 0.5, 0.5, 0.5), 8),
        ("/W/Looks/Tex/albedo", "inputs:file"): (struct.pack("<QQ", 201, 0), 1),  # not resolved
        ("/W/Looks/Unused/Surface", "inputs:file"): (struct.pack("<QQ", 301, 302), 1),  # resolved, not on disk
        ("/W/Looks/Unused/Surface", "inputs:st"): (struct.pack("<QQ", 301, 302), 0),  # 16 bytes, not an asset
        ("/W/Sky", "inputs:texture:file"): (struct.pack("<QQ", 401, 402), 1),  # a light, not a shader
    }
    records = {**records, "/W/Sky": "DomeLight"}
    monkeypatch.setattr(mp, "_read_shader_values", lambda stage: (
        {key: raw for key, (raw, _semantic) in values.items()},
        {key: semantic for key, (_raw, semantic) in values.items()},
    ))
    names, files = mp.read_shader_catalog(stage, records)
    assert names == {
        "/W/Looks/Mdl/mdl": ("info:mdl:sourceAsset", "inputs:diffuse_color_constant"),
        "/W/Looks/Tex/albedo": ("inputs:file",),
        "/W/Looks/Unused/Surface": ("inputs:file", "inputs:st"),
    }
    assert sorted((f["material"], f["uri"], f["kind"], f["missing"]) for f in files) == [
        ("/W/Looks/Mdl", "./runner.mdl", "mdl", None),  # on disk; a colour is not an asset
        ("/W/Looks/Tex", "./albedo.png", "texture", "unresolved"),
        ("/W/Looks/Unused", "./gone.png", "texture", "missing"),
    ]
    from ovui_data_adapters.common import render_diagnostics as rd
    from ovui_data_adapters.common.render_material_report import record_file_events

    monkeypatch.setattr(rd, "_DIAGNOSTICS", rd.RenderDiagnostics())
    assert record_file_events(files) == {"missing": 2, "linked": 0}
    assert sorted(e["material"] for e in rd.get_render_diagnostics().events()) == ["/W/Looks/Tex", "/W/Looks/Unused"]


class _QueryStage(FakeStage):
    """A stage of an older ovstage: it answers ``query_prims`` itself and has no narrow attribute read."""

    def query_prims(self, ordinal):
        assert ordinal == self.current_ordinal
        return {"groups": [
            {"prim_type": "Shader", "prim_list_handle": 1,
             "attributes": ("info:id", "inputs:diffuseColor", "inputs:file", "outputs:out")},
            {"prim_type": "Material", "prim_list_handle": 2, "attributes": ("outputs:surface",)},
        ]}

    def get_prim_paths(self, handle):
        return {1: ["/W/Looks/Tex/albedo", "/W/Looks/Tex/Surface"], 2: ["/W/Looks/Tex"]}[handle]


def test_a_stage_of_an_older_ovstage_is_read_through_its_own_query(monkeypatch, tmp_path):
    stage = _QueryStage()
    tokens = {201: "./albedo.png", 202: str(tmp_path / "albedo.png")}
    monkeypatch.setattr(mp, "resolve_token_id", lambda stage, token: tokens.get(token, ""))
    # No metadata for the file input: two interned strings that name a file are an asset.
    stage.attrs[("/W/Looks/Tex/albedo", "inputs:file")] = struct.pack("<QQ", 201, 202)
    stage.color("/W/Looks/Tex/Surface", "inputs:diffuseColor", 1, 0, 0)
    records = {"/W/Looks/Tex": "Material", "/W/Looks/Tex/albedo": "Shader", "/W/Looks/Tex/Surface": "Shader"}
    names, files = mp.read_shader_catalog(stage, records)
    assert names == {"/W/Looks/Tex/albedo": ("inputs:file",), "/W/Looks/Tex/Surface": ("inputs:diffuseColor",)}
    assert [(f["material"], f["uri"], f["kind"], f["missing"]) for f in files] == [
        ("/W/Looks/Tex", "./albedo.png", "texture", "missing")]


_NATIVE_SCENE = """#usda 1.0
(
    defaultPrim = "W"
)

def Xform "W"
{
    def Scope "Looks"
    {
        def Material "Tex"
        {
            token outputs:surface.connect = </W/Looks/Tex/Surface.outputs:surface>

            def Shader "Surface"
            {
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor.connect = </W/Looks/Tex/Albedo.outputs:rgb>
                float inputs:roughness = 0.5
                token outputs:surface
            }

            def Shader "Albedo"
            {
                uniform token info:id = "UsdUVTexture"
                asset inputs:file = @./textures/gone.png@
                float3 outputs:rgb
            }
        }

        def Material "Mdl"
        {
            token outputs:mdl:surface.connect = </W/Looks/Mdl/Shader.outputs:out>

            def Shader "Shader"
            {
                uniform token info:implementationSource = "sourceAsset"
                uniform asset info:mdl:sourceAsset = @OmniPBR.mdl@
                uniform token info:mdl:sourceAsset:subIdentifier = "OmniPBR"
                color3f inputs:diffuse_color_constant = (0.8, 0.1, 0.1)
                token outputs:out
            }
        }
    }

    def DomeLight "Sky"
    {
        asset inputs:texture:file = @./textures/sky.hdr@
    }

    def Cube "TexCube" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        rel material:binding = </W/Looks/Tex>
    }

    def Sphere "MdlBall" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        rel material:binding = </W/Looks/Mdl>
    }

    def Scope "Unbound"
    {
        def Material "Spare"
        {
            def Shader "Shader"
            {
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor = (0, 1, 0)
            }
        }
    }
}
"""


@pytest.mark.requires_ovstage
def test_the_real_native_catalog_is_one_narrow_read_of_the_shader_inputs(tmp_path, monkeypatch):
    from ovui_data_adapters.ovstage.provider import PROVIDER_ENTRY_POINT_VALUE, PROVIDER_NAME, create_provider_session
    from ovui_data_adapters.ovstage.renderer_adapter import _query_records
    from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes

    scene_path = tmp_path / "scene.usda"
    scene_path.write_text(_NATIVE_SCENE)
    runtime = load_required_runtimes(module_name=PROVIDER_NAME, entry_point_value=PROVIDER_ENTRY_POINT_VALUE)
    session = create_provider_session(runtime=runtime)
    scene = session.open_stage(str(scene_path))
    try:
        stage = scene.native_stage
        records = _query_records(stage)
        # The query of every attribute of every prim takes seconds on a large scene: the catalog must not use it.
        monkeypatch.setattr(stage, "query_prims", lambda *args, **kwargs: pytest.fail("the full query was used"),
                            raising=False)
        names, files = mp.read_shader_catalog(stage, records)
    finally:
        session.shutdown_scene()
    # The native stage holds the inputs of the materials that geometry binds (so does the full query of the stage):
    # the shader of the unbound material has none.
    assert names == {
        "/W/Looks/Tex/Surface": ("inputs:diffuseColor", "inputs:roughness"),
        "/W/Looks/Tex/Albedo": ("inputs:file",),
        "/W/Looks/Mdl/Shader": ("info:mdl:sourceAsset", "inputs:diffuse_color_constant"),
    }
    # The texture is not found (the resolver gives no path); the bare MDL module is found by the renderer's search
    # path; the light is no shader.
    assert sorted((f["material"], f["uri"], f["kind"], f["missing"]) for f in files) == [
        ("/W/Looks/Mdl", "OmniPBR.mdl", "mdl", None),
        ("/W/Looks/Tex", "./textures/gone.png", "texture", "unresolved"),
    ]


def test_a_native_metal_is_not_checked_against_a_flat_reference(scene):
    stage, _records, _names = scene
    stage.number("/W/Looks/Mdl/mdl", "inputs:metallic_constant", 1.0)
    _todo, skipped = plan(scene)
    assert "is a metal (metallic_constant 1)" in skipped["/W/Looks/Mdl"]["reason"]


@pytest.mark.parametrize("layout,raw,type_name,value", [
    (((2, 32, 1), 0), struct.pack("<f", 0.25), "float", 0.25),
    (((2, 64, 3), 8), struct.pack("<3d", 1, 2, 3), "color3d", (1.0, 2.0, 3.0)),
    (((2, 32, 3), 7), struct.pack("<3f", 0, 0, 1), "normal3f", (0.0, 0.0, 1.0)),
    (((0, 32, 1), 0), struct.pack("<i", -3), "int", -3),
    (((6, 8, 1), 0), b"\x01", "bool", True),
    (((1, 64, 1), 2), struct.pack("<Q", 101), "token", "./runner.mdl"),
    (((1, 64, 2), 1), struct.pack("<QQ", 101, 102), "asset", None),
])
def test_a_native_input_is_read_with_its_usd_type(scene, layout, raw, type_name, value):
    stage, _records, _names = scene
    stage.put("/S", "inputs:x", layout, raw)
    item = mp.native_input(stage, "/S", "inputs:x")
    assert (item.name, item.type_name, item.connected) == ("x", type_name, False)
    if value is not None:
        assert item.value == pytest.approx(value) if isinstance(value, (tuple, float)) else item.value == value
