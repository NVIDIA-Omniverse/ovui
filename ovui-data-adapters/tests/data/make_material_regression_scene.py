# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression scene for regression: the material classes of the reported kitchen.

usage: make_material_regression_scene.py <out-dir> [--break KIND ...]

The scene has the same material kinds and paths as the reported kitchen:

* ``/World/Kitchen/W1_Looks/PeruSurfaceV1/Whitewash``: MaterialX OpenPBR, plaster texture.
* ``/World/Kitchen/W1_Looks/PeruReviewV2/CrimsonRunner``: native MDL; the universal, MDL
  and MaterialX outputs all connect to the one MDL shader.
* ``/World/Kitchen/W4_FoodProduce_v1/Looks/PotatoRed``: MaterialX OpenPBR, potato texture.
* ``/World/Kitchen/Looks/Greens`` and ``.../Blues``: more OpenPBR materials with the same graph
  (albedo, normal map, roughness images) and other albedo files.

Camera: ``/World/Cameras/Review_Ref``. Render it at 1280x720.

``--break`` makes one failure that the renderer shows only as a fallback material:

* ``missing-texture``: the potato albedo file does not exist.
* ``corrupt-texture``: the potato albedo file exists but is not an image.
* ``broken-mdl``: the runner MDL module has a compile error.

``--break flat-colors`` is not a fault either: the four OpenPBR materials use a constant ``base_color`` and no
image. The native check of the OVStage adapter reads constant colours only, so only such materials (and an MDL with
a constant) can be checked natively.

``--break frame`` is not a fault either: it adds two materials with the same shader and the same constant
colour, one on a rectangular FRAME mesh (outer +-1, opening +-0.6) and one on a solid cube. Both must be ok: a
check that samples the middle of the cell would find the background through the opening of the frame.

``--break module-defaults`` is not a fault: the runner takes the defaults of its MDL module (no colour is
authored on the shader), so a colour check cannot know what it must look like (it is ``unverifiable``).
"""

import os
import sys

from PIL import Image
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade

RUNNER_MDL = """mdl 1.6;
import ::df::*;
export material peru_runner(
    color diffuse_color_constant = color(0.55, 0.02, 0.06)
) = material(
    surface: material_surface(
        scattering: df::diffuse_reflection_bsdf(tint: diffuse_color_constant)
    )
);
"""
BROKEN_MDL = RUNNER_MDL.replace("df::diffuse_reflection_bsdf(", "df::no_such_bsdf(")

#: name -> (path, albedo RGB, position, size)
OPENPBR = {
    "Whitewash": ("/World/Kitchen/W1_Looks/PeruSurfaceV1/Whitewash", (225, 220, 205), (-4.5, 0.0, 0.0)),
    "PotatoRed": ("/World/Kitchen/W4_FoodProduce_v1/Looks/PotatoRed", (170, 40, 45), (1.5, 0.0, 0.0)),
    "Greens": ("/World/Kitchen/Looks/Greens", (40, 190, 60), (4.5, 0.0, 0.0)),
    "Blues": ("/World/Kitchen/Looks/Blues", (40, 70, 200), (-1.5, 2.8, 0.0)),
}
RUNNER_PATH = "/World/Kitchen/W1_Looks/PeruReviewV2/CrimsonRunner"
V = Sdf.ValueTypeNames


def _openpbr(stage, name, path, texture, flat=None):
    material = UsdShade.Material.Define(stage, path)
    pbr = UsdShade.Shader.Define(stage, path + "/OpenPBR")
    pbr.CreateIdAttr("ND_open_pbr_surface_surfaceshader")
    if flat is not None:
        pbr.CreateInput("base_color", V.Color3f).Set(Gf.Vec3f(*(c / 255.0 for c in flat)))
        material.CreateSurfaceOutput("mtlx").ConnectToSource(pbr.CreateOutput("out", V.Token))
        return material

    def image(node, node_id, file, out_type):
        shader = UsdShade.Shader.Define(stage, f"{path}/{node}")
        shader.CreateIdAttr(node_id)
        file_input = shader.CreateInput("file", V.Asset)
        file_input.Set(Sdf.AssetPath(f"./{file}"))
        if node == "albedo":
            file_input.GetAttr().SetColorSpace("sRGB")
        return shader.CreateOutput("out", out_type)

    albedo = image("albedo", "ND_image_color3", texture, V.Color3f)
    normal = image("normal_tex", "ND_image_vector3", "normal.png", V.Float3)
    rough = image("rough_tex", "ND_image_float", "rough.png", V.Float)
    nmap = UsdShade.Shader.Define(stage, path + "/normalmap")
    nmap.CreateIdAttr("ND_normalmap")
    nmap.CreateInput("in", V.Float3).ConnectToSource(normal)
    pbr.CreateInput("base_color", V.Color3f).ConnectToSource(albedo)
    pbr.CreateInput("geometry_normal", V.Float3).ConnectToSource(nmap.CreateOutput("out", V.Float3))
    pbr.CreateInput("specular_roughness", V.Float).ConnectToSource(rough)
    material.CreateSurfaceOutput("mtlx").ConnectToSource(pbr.CreateOutput("out", V.Token))
    return material


def _runner(stage, module_defaults=False):
    material = UsdShade.Material.Define(stage, RUNNER_PATH)
    shader = UsdShade.Shader.Define(stage, RUNNER_PATH + "/mdl")
    shader.SetSourceAsset(Sdf.AssetPath("./peru_runner_diamond_v1.mdl"), "mdl")
    shader.SetSourceAssetSubIdentifier("peru_runner", "mdl")
    if not module_defaults:
        shader.CreateInput("diffuse_color_constant", V.Color3f).Set(Gf.Vec3f(0.55, 0.02, 0.06))
    out = shader.CreateOutput("out", V.Token)
    for context in ("mdl", "mtlx", ""):
        material.CreateSurfaceOutput(context).ConnectToSource(out)
    return material


def _flat_red(stage, path):
    material = UsdShade.Material.Define(stage, path)
    pbr = UsdShade.Shader.Define(stage, path + "/OpenPBR")
    pbr.CreateIdAttr("ND_open_pbr_surface_surfaceshader")
    pbr.CreateInput("base_color", V.Color3f).Set(Gf.Vec3f(0.85, 0.05, 0.07))
    material.CreateSurfaceOutput("mtlx").ConnectToSource(pbr.CreateOutput("out", V.Token))
    return material


def _frame_and_cube(stage):
    """A red rectangular frame mesh and a red solid cube, with two materials of the same shader and colour."""

    frame = UsdGeom.Mesh.Define(stage, "/World/Kitchen/Frame_geo")
    outer, inner = 1.0, 0.6
    points = [(-outer, -outer, 0), (outer, -outer, 0), (outer, outer, 0), (-outer, outer, 0),
              (-inner, -inner, 0), (inner, -inner, 0), (inner, inner, 0), (-inner, inner, 0)]
    frame.GetPointsAttr().Set([Gf.Vec3f(*p) for p in points])
    frame.GetFaceVertexCountsAttr().Set([4, 4, 4, 4])
    frame.GetFaceVertexIndicesAttr().Set([0, 1, 5, 4, 1, 2, 6, 5, 2, 3, 7, 6, 3, 0, 4, 7])
    frame.GetExtentAttr().Set([Gf.Vec3f(-outer, -outer, 0), Gf.Vec3f(outer, outer, 0)])
    frame.GetDoubleSidedAttr().Set(True)
    UsdGeom.XformCommonAPI(frame).SetTranslate((7.0, 0.0, 0.0))
    UsdShade.MaterialBindingAPI.Apply(frame.GetPrim()).Bind(_flat_red(stage, "/World/Kitchen/Looks/RedFrame"))
    cube = UsdGeom.Cube.Define(stage, "/World/Kitchen/RedSolid_geo")
    cube.GetSizeAttr().Set(2.0)
    UsdGeom.XformCommonAPI(cube).SetTranslate((7.0, 3.0, 0.0))
    UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(_flat_red(stage, "/World/Kitchen/Looks/RedSolid"))


def build(out, breaks=()):
    os.makedirs(out, exist_ok=True)
    Image.new("RGB", (64, 64), (128, 128, 255)).save(f"{out}/normal.png")
    Image.new("L", (64, 64), 120).save(f"{out}/rough.png")
    open(f"{out}/peru_runner_diamond_v1.mdl", "w").write(BROKEN_MDL if "broken-mdl" in breaks else RUNNER_MDL)
    stage = Usd.Stage.CreateNew(f"{out}/kitchen.usda")
    UsdGeom.SetStageUpAxis(stage, "Y")
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    camera = UsdGeom.Camera.Define(stage, "/World/Cameras/Review_Ref")
    UsdGeom.XformCommonAPI(camera).SetTranslate((0, 0, 34))
    UsdLux.DomeLight.Define(stage, "/World/Dome").CreateIntensityAttr(1500)
    for name, (path, rgb, position) in OPENPBR.items():
        texture = f"{name}.png"
        if not ("missing-texture" in breaks and name == "PotatoRed"):
            if "corrupt-texture" in breaks and name == "PotatoRed":
                open(f"{out}/{texture}", "wb").write(b"this is not an image")
            else:
                Image.new("RGB", (64, 64), rgb).save(f"{out}/{texture}")
        material = _openpbr(stage, name, path, texture, rgb if "flat-colors" in breaks else None)
        shape = (UsdGeom.Sphere if name == "PotatoRed" else UsdGeom.Cube).Define(stage, f"/World/Kitchen/{name}_geo")
        shape.GetPrim().GetAttribute("radius" if name == "PotatoRed" else "size").Set(1.3 if name == "PotatoRed" else 2.0)
        UsdGeom.XformCommonAPI(shape).SetTranslate(position)
        UsdShade.MaterialBindingAPI.Apply(shape.GetPrim()).Bind(material)
    runner = UsdGeom.Cube.Define(stage, "/World/Kitchen/Runner_geo")
    runner.GetSizeAttr().Set(2.0)
    UsdGeom.XformCommonAPI(runner).SetTranslate((-1.5, -2.8, 0.0))
    UsdShade.MaterialBindingAPI.Apply(runner.GetPrim()).Bind(_runner(stage, "module-defaults" in breaks))
    if "frame" in breaks:
        _frame_and_cube(stage)
    stage.GetRootLayer().Save()
    return f"{out}/kitchen.usda"


def main(argv):
    breaks = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--break"]
    print("wrote", build(argv[1], breaks))


if __name__ == "__main__":
    main(sys.argv)
