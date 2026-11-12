# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Render check: draw each material beside a flat reference and compare the two.

The renderer can show a wrong material with no error: a texture that did not become
resident, a module that was shared with the wrong parameters, a fallback. USD cannot
tell, and the renderer has no query for it (its ``query_prims`` and ``read_attribute``
give only authored attributes). So this check asks the renderer to draw it.

For each material that has a derivable expected colour, the material is drawn on a copy of
its own geometry far from the scene, beside a reference cube: the same shader with the same
constant shading controls and the expected colour (MDL: a flat diffuse of that colour). The
expected colour is the mean of the albedo image or the authored constant. The two must show
the same colour within a tolerance, otherwise the material is shown wrong (a fallback, or
another material's texture).

Two ways to run it:

* **Live** (:class:`LivePlan`, used by both renderer adapters): the shapes are added to the
  application's own renderer, so the real materials are compiled by that renderer, with its
  caches, its compile order and its memory. It runs on the ``material_verify`` command, and
  once after the first frame when ``OVUI_VERIFY_MATERIALS`` asks for it (it draws extra
  frames, so it is off by default).
* **Command line** (:func:`main`): a fresh renderer opens a saved scene file, with the
  scene's lights switched off. It shows what this device does with the material, not the
  state of a running application.

Limits: it cannot check a material whose colour is not a single image or a constant, one that
is transparent or emissive, one whose other inputs the reference cannot reproduce, or (without
the optional image library Pillow) one whose colour is an image; those are ``unverifiable``
with the reason.

    python -m ovui_data_adapters.common.render_probe scene.usda [--prefix /World] [--json out.json]

Exit code: 0 all verified materials match, 1 a material differs, 2 the check could not run.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import contextlib
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ovui_data_adapters.common.render_diagnostics import (
    LOGGER,
    RenderDiagnostics,
    get_render_diagnostics,
    set_verification,
)

#: Largest channel difference (0..255) between the real and the reference cube that counts as the same colour.
TOLERANCE = 40
VERIFY_ENV = "OVUI_VERIFY_MATERIALS"
#: Where the live check adds its cubes in the application's renderer.
LIVE_PREFIX = "/OvuiProbe"

ALBEDO_INPUTS = ("base_color", "diffuse_color", "diffuse_color_constant", "diffuseColor", "baseColor")
NOT_PLAIN_INPUTS = ("emission_luminance", "geometry_opacity", "opacity", "transmission_weight", "emission_color")
#: Metalness inputs (OmniPBR, OpenPBR, UsdPreviewSurface, OmniSurface). A metal shows the colour of what it
#: reflects; a flat diffuse reference cannot match it (Factory: Brass_01, metallic 1, was reported as shown wrong).
METAL_INPUTS = ("metallic_constant", "base_metalness", "metallic", "metalness")
#: A material with a metalness above this is not checked.
METAL_LIMIT = 0.5
#: Inputs that change only the direction of the surface or the sharpness of its reflections. When one of them comes
#: from another shader (a normal or roughness map), the reference keeps the default of its shader: the mean colour of
#: the shape changes much less than the tolerance (the regression kitchen has such maps, and its materials are ok).
#: Any other input that comes from another shader makes the material not checkable.
IGNORED_CONNECTED_INPUTS = ("geometry_normal", "geometry_tangent", "normal", "tangent", "specular_roughness",
                            "roughness", "coat_roughness", "base_diffuse_roughness")
#: USD value types that the reference can copy, with the number of values of each.
_COPYABLE_TYPES = {
    "float": 1, "double": 1, "half": 1, "int": 1, "uint": 1, "bool": 1, "token": 1, "string": 1,
    "float2": 2, "double2": 2, "half2": 2, "int2": 2, "texCoord2f": 2,
    "float3": 3, "double3": 3, "half3": 3, "int3": 3, "color3f": 3, "color3d": 3, "color3h": 3,
    "vector3f": 3, "vector3d": 3, "normal3f": 3, "normal3d": 3, "point3f": 3, "point3d": 3,
    "float4": 4, "double4": 4, "color4f": 4, "color4d": 4,
}


@dataclass(frozen=True)
class ShaderInput:
    """One input of the shader that a material output uses, as the scene holds it (OpenUSD or the native stage).

    ``value`` is the authored constant (None when the input has no authored value); ``connected`` is True when the
    input takes its value from another shader.
    """

    name: str
    type_name: str = ""
    value: Any = None
    connected: bool = False


def usda_value(type_name: str, value: Any) -> Optional[str]:
    """The USDA text of a constant of one of the copyable types, or None."""

    count = _COPYABLE_TYPES.get(type_name)
    if count is None or value is None:
        return None
    if type_name in ("token", "string"):
        return json.dumps(str(value))
    if type_name == "bool":
        return "1" if value else "0"
    values = [value] if count == 1 else list(value)
    if len(values) != count:
        return None
    try:
        if type_name.startswith(("int", "uint")):
            text = [str(int(v)) for v in values]
        else:
            numbers = [float(v) for v in values]
            if any(n != n or n in (float("inf"), float("-inf")) for n in numbers):
                return None
            text = [repr(n) for n in numbers]
    except (TypeError, ValueError):
        return None
    return text[0] if count == 1 else "(" + ", ".join(text) + ")"


def _value_text(value: Any) -> str:
    if isinstance(value, (tuple, list)):
        return "(" + ", ".join(f"{float(v):g}" for v in value) + ")"
    return f"{float(value):g}" if isinstance(value, (int, float)) else str(value)


def colour_input(inputs: dict[str, ShaderInput]) -> Optional[str]:
    """The input that holds the colour of the material (the first of :data:`ALBEDO_INPUTS` that is authored)."""

    return next((name for name in ALBEDO_INPUTS if name in inputs and
                 (inputs[name].connected or inputs[name].value is not None)), None)


def reference_inputs(family: str, inputs: dict[str, ShaderInput], colour: str) -> tuple[Optional[list[tuple[str, str, str]]], str]:
    """The inputs that the reference copies from the real shader, or (None, why the material cannot be checked).

    The reference of an OpenPBR, other MaterialX or UsdPreviewSurface material is the same shader with the same
    constants, and the expected colour in place of ``colour``: so a valid control such as ``base_weight 0`` gives the
    same result on both (black). The reference of an MDL material is a flat diffuse MDL that reproduces only the
    colour, so an MDL shader that sets any other input is not checked. (Measured on Factory: OmniPBR materials that
    set only a rough reflection of normal strength still differed from the flat reference by 33 and 34 of 255, close
    to the tolerance of 40; so no other input is taken as harmless.)
    """

    for name in NOT_PLAIN_INPUTS:
        item = inputs.get(name)
        if item is not None and (item.connected or (item.value is not None and item.value not in (0, 0.0, 1, 1.0))):
            return None, f"the material uses {name}; a flat reference cannot match it"
    for name in METAL_INPUTS:
        item = inputs.get(name)
        if item is not None and isinstance(item.value, (int, float)) and float(item.value) > METAL_LIMIT:
            return None, f"the material is a metal ({name} {float(item.value):g}): it shows what it reflects, a flat reference cannot match it"
    copied: list[tuple[str, str, str]] = []
    for name, item in sorted(inputs.items()):
        if name == colour:
            continue
        if item.connected:
            if family != "mdl" and name in IGNORED_CONNECTED_INPUTS:
                continue
            return None, f"{name} comes from another shader; the reference cannot reproduce it"
        if item.value is None:
            continue
        if family == "mdl":
            return None, (f"the MDL shader sets {name} ({_value_text(item.value)}); the flat reference of an MDL material "
                          "reproduces only its colour")
        text = usda_value(item.type_name, item.value)
        if text is None:
            return None, f"the reference cannot copy {name} ({item.type_name or 'its type is not known'})"
        copied.append((item.type_name, name, text))
    return copied, ""

COLS, ROWS, PAIR_W, ROW_H = 6, 4, 3.0, 1.6
CHUNK = COLS * ROWS
#: Distance between two blocks of CHUNK cells. Each block has its own camera; a block that is closer than the view
#: of another camera (about 21 x 12 units) would be drawn on top of the other block's cells.
CHUNK_SPACING = 100.0
STUDIO_Z, CAMERA_DISTANCE = 100000.0, 200.0
FOCAL, APERTURE = 200.0, 20.955
WIDTH, HEIGHT = 1280, 720


class MaterialMismatchError(RuntimeError):
    """A material is shown wrong or a resource failed, and ``OVUI_VERIFY_MATERIALS=strict``."""


def _srgb_to_linear(value: float) -> float:
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def image_mean(path: str) -> tuple[Optional[tuple[int, int, int]], str]:
    """The mean colour (0..255) of an image file, or (None, why it is not known).

    The optional image library Pillow reads it. Without Pillow the colour is not known: that is not a failure of
    the image, and the material is only not checked.
    """

    try:
        from PIL import Image
    except ImportError:
        return None, (
            "the optional image library Pillow is not installed, so the colour of the albedo image is not known "
            "(this is not a failure of the image)"
        )
    try:
        with Image.open(path) as image:
            return image.convert("RGB").resize((1, 1), Image.BOX).getpixel((0, 0)), ""
    except Exception as exc:  # noqa: BLE001 - becomes the reason; the renderer's own log says whether it failed
        return None, (
            f"the albedo image cannot be read here ({type(exc).__name__}: {exc}); "
            "the renderer log says whether the renderer could read it"
        )


def _decoded_as_srgb(image_shader: Any, file_attribute: Any) -> bool:
    """Whether the renderer decodes the 8-bit image of an image shader as sRGB.

    A UsdUVTexture follows its ``sourceColorSpace`` input: ``raw`` is raw, ``sRGB`` and ``auto`` (the default, for an
    8-bit image) are sRGB. A MaterialX image node is sRGB only when the file attribute says so (``sRGB``,
    ``srgb_texture``). Measured with the renderer: a UsdUVTexture with no colour space is drawn as sRGB.
    """

    if _shader_id_of(image_shader) == "UsdUVTexture":
        source = image_shader.GetInput("sourceColorSpace")
        value = source.Get() if source else None
        return str(value or "auto") != "raw"
    return file_attribute.GetColorSpace() in ("sRGB", "srgb_texture")


def _shader_id_of(shader: Any) -> str:
    attribute = shader.GetIdAttr() if shader else None
    return str(attribute.Get() or "") if attribute else ""


def _shader_inputs(shader: Any) -> dict[str, ShaderInput]:
    inputs = {}
    for shader_input in shader.GetInputs():
        attribute = shader_input.GetAttr()
        inputs[shader_input.GetBaseName()] = ShaderInput(
            shader_input.GetBaseName(), str(attribute.GetTypeName()),
            attribute.Get() if attribute.HasAuthoredValue() else None, bool(shader_input.HasConnectedSource()),
        )
    return inputs


def expected_albedo(material_prim: Any) -> tuple[Optional[dict[str, Any]], str]:
    """Return ({"linear", "resources", "source", "family", "identifier", "colour_input", "inputs"}, "") or (None, reason).

    ``inputs`` are the inputs that the reference copies (see :func:`reference_inputs`).
    """

    from pxr import UsdShade

    from ovui_data_adapters.common.render_material_report import (
        _CONTEXT_ORDER,
        _producers,
        _upstream_shaders,
        asset_attributes,
        shader_identifier,
    )

    material = UsdShade.Material(material_prim)
    for context, _name in _CONTEXT_ORDER:
        output = material.GetSurfaceOutput(context)
        if output and output.GetConnectedSource():
            break
    else:
        return None, "no surface output is connected"
    shaders = _upstream_shaders(output)
    if not shaders:
        return None, "the surface output has no shader"
    root = shaders[0]
    identifier = shader_identifier(root)
    mdl_asset = root.GetPrim().GetAttribute("info:mdl:sourceAsset")
    if mdl_asset and mdl_asset.HasAuthoredValue():
        family = "mdl"
    else:
        family = "materialx" if identifier.startswith("ND_") else "preview"
    inputs = _shader_inputs(root)
    colour = colour_input(inputs)
    if colour is None:
        return None, "no albedo input (base_color, diffuse_color, diffuse_color_constant) is authored"
    copied, reason = reference_inputs(family, inputs, colour)
    if copied is None:
        return None, reason
    plan = {"family": family, "identifier": identifier, "colour_input": colour, "inputs": copied}
    shader_input = root.GetInput(colour)
    if not shader_input.HasConnectedSource():
        value = shader_input.Get()
        if value is None or len(value) != 3:
            return None, f"{colour} is not a colour"
        return {"linear": tuple(float(c) for c in value), "resources": [], "source": f"constant {colour}", **plan}, ""
    sources = _producers(shader_input)
    files = [(attr, value) for source in sources for attr, value in asset_attributes(source) if attr.GetName() == "inputs:file"]
    if len(sources) != 1 or len(files) != 1:
        return None, f"{colour} comes from a node graph that is not one image"
    attribute, asset = files[0]
    path = asset.resolvedPath
    if not path or not os.path.isfile(path):
        return None, f"albedo image is missing: {asset.path}"
    mean, why = image_mean(path)
    if mean is None:
        return None, why
    r, g, b = mean
    if _decoded_as_srgb(sources[0], attribute):
        linear = tuple(_srgb_to_linear(c / 255.0) for c in (r, g, b))
    else:
        linear = (r / 255.0, g / 255.0, b / 255.0)
    return {"linear": linear, "resources": [asset.path], "source": "mean of the albedo image", **plan}, ""


def _geometry_by_material(stage: Any) -> dict[str, dict[str, Any]]:
    """The first geometry prim that each material is bound to, with its bound (centre and size) in its own space."""

    from pxr import Usd, UsdGeom, UsdShade

    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_, UsdGeom.Tokens.render])
    gprims = [prim for prim in stage.Traverse() if prim.IsA(UsdGeom.Gprim)]
    materials, _relationships = UsdShade.MaterialBindingAPI.ComputeBoundMaterials(gprims)  # one pass, shared caches
    found: dict[str, dict[str, Any]] = {}
    for prim, material in zip(gprims, materials):
        if not material:
            continue
        path = str(material.GetPath())
        if path in found:
            continue
        box = cache.ComputeUntransformedBound(prim).ComputeAlignedRange()
        if box.IsEmpty():
            continue
        size = max(box.GetSize())
        centre = box.GetMidpoint()
        if not (0 < size < float("inf")) or any(c != c for c in centre):
            continue
        found[path] = {"source": str(prim.GetPath()), "centre": tuple(centre), "size": float(size)}
    return found


def not_reached(limit: int) -> dict[str, Any]:
    """The result of a material that the check did not reach: it stops after ``limit`` materials."""

    return {"state": "not_reached", "reason": f"the check stops after {limit} materials (its limit); not checked"}


def plan(stage: Any, path_prefix: str = "", limit: int = 500) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (materials to draw, result for each material that cannot be checked).

    A material is drawn on a copy of the geometry prim that is bound to it, so that the ORIGINAL
    material instance is observed. A material that no geometry uses cannot be drawn. A material after
    the first ``limit`` is ``not_reached``: it is counted, not dropped.
    """

    from pxr import UsdShade

    geometry = _geometry_by_material(stage)
    todo, skipped = [], {}
    planned = 0
    for prim in stage.Traverse():
        if not prim.IsA(UsdShade.Material):
            continue
        path = str(prim.GetPath())
        if path_prefix and not path.startswith(path_prefix):
            continue
        if planned >= limit:
            skipped[path] = not_reached(limit)
            continue
        planned += 1
        expected, reason = expected_albedo(prim)
        if expected is None:
            skipped[path] = {"state": "unverifiable", "reason": reason}
        elif path not in geometry:
            skipped[path] = {"state": "unverifiable", "reason": "no geometry with a finite size is bound to this material"}
        else:
            todo.append({"path": path, **expected, **geometry[path]})
    return todo, skipped


FLAT_MDL = """mdl 1.6;
import ::df::*;
export material flat(color tint = color(0.5)) = material(
    surface: material_surface(scattering: df::diffuse_reflection_bsdf(tint: tint))
);
"""

#: Render variables of each check product: the picture, and the distance, which is infinite where nothing is drawn.
LDR_VAR, DEPTH_VAR = "LdrColor", "DistanceToImagePlaneSD"


def _cell_in_chunk(offset: int) -> tuple[float, float]:
    row, col = divmod(offset % CHUNK, COLS)
    return col * PAIR_W, -row * ROW_H


def _chunk_origin(chunk_id: int) -> tuple[float, float]:
    return 0.0, -chunk_id * CHUNK_SPACING


def _cell(index: int) -> tuple[float, float]:
    """Studio position of the cell of todo item ``index``: its place in its block, plus the place of the block."""

    x, y = _cell_in_chunk(index)
    ox, oy = _chunk_origin(index // CHUNK)
    return x + ox, y + oy


def _color_text(color: Any) -> str:
    return "(" + ", ".join(repr(float(c)) for c in color) + ")"


def _reference_material_text(root: str, index: int, item: dict[str, Any], work_dir: str) -> str:
    """The reference material: the expected colour, with the shading of the real material.

    OpenPBR, other MaterialX and UsdPreviewSurface: the same shader (``identifier``) with the constants of the real
    shader (``inputs``, see :func:`reference_inputs`) and the expected colour in ``colour_input``. MDL: a flat diffuse
    MDL with the expected colour (the plan checks only MDL shaders that set nothing else). A reference in another
    family would be lit differently, so it could not be compared with the real shape.
    """

    path = f"{root}/RefLook_{index}"
    color = _color_text(item["linear"])
    family = item.get("family", "preview")
    if family == "mdl":
        module = os.path.join(work_dir, "ovui_probe_flat.mdl")
        with open(module, "w", encoding="utf-8") as handle:
            handle.write(FLAT_MDL)
        return (
            f'    def Material "RefLook_{index}"\n    {{\n'
            f"        token outputs:mdl:surface.connect = <{path}/Surface.outputs:out>\n"
            '        def Shader "Surface"\n        {\n'
            '            uniform token info:implementationSource = "sourceAsset"\n'
            f"            uniform asset info:mdl:sourceAsset = @{module}@\n"
            '            uniform token info:mdl:sourceAsset:subIdentifier = "flat"\n'
            f"            color3f inputs:tint = {color}\n"
            "            token outputs:out\n        }\n    }\n"
        )
    if family == "materialx":
        identifier, output, terminal = item.get("identifier") or "ND_open_pbr_surface_surfaceshader", "outputs:mtlx:surface", "out"
    else:
        identifier, output, terminal = item.get("identifier") or "UsdPreviewSurface", "outputs:surface", "surface"
    colour = item.get("colour_input") or ("base_color" if family == "materialx" else "diffuseColor")
    lines = [
        f'    def Material "RefLook_{index}"\n    {{\n',
        f"        token {output}.connect = <{path}/Surface.outputs:{terminal}>\n",
        '        def Shader "Surface"\n        {\n',
        f"            uniform token info:id = {json.dumps(identifier)}\n",
        f"            color3f inputs:{colour} = {color}\n",
    ]
    lines += [f"            {type_name} inputs:{name} = {value}\n" for type_name, name, value in item.get("inputs", ())]
    lines.append(f"            token outputs:{terminal}\n        }}\n    }}\n")
    return "".join(lines)


def studio_layer_text(todo: list[dict[str, Any]], work_dir: str, root: str, real_cubes: bool = False) -> tuple[str, list[str]]:
    """Author the studio as USDA text, without OpenUSD: the dome light, the cameras, the render products and the cubes.

    ``root`` is the prim that holds it all. The reference cubes are always drawn. With ``real_cubes`` a cube
    that uses the scene's own material (the path in ``item["path"]``) is drawn beside each; otherwise the
    caller puts a copy of the original geometry in the cell. Returns (text, names of the render products).
    """

    name = root.rsplit("/", 1)[-1]
    cx = (COLS - 1) * PAIR_W / 2 + 0.75
    cy = -(ROWS - 1) * ROW_H / 2
    out = [f'#usda 1.0\n(\n    defaultPrim = "{name}"\n)\n', f'def Xform "{name}"\n{{\n']
    out.append('    def DomeLight "Dome"\n    {\n        float inputs:intensity = 1000\n    }\n')
    products = []
    for chunk_start in range(0, len(todo), CHUNK):
        chunk = todo[chunk_start:chunk_start + CHUNK]
        chunk_id = chunk_start // CHUNK
        ox, oy = _chunk_origin(chunk_id)
        out.append(
            f'    def Camera "Camera_{chunk_id}"\n    {{\n'
            f"        float focalLength = {FOCAL}\n        float horizontalAperture = {APERTURE}\n"
            f"        float verticalAperture = {APERTURE * HEIGHT / WIDTH}\n"
            f"        float2 clippingRange = ({CAMERA_DISTANCE - 50}, {CAMERA_DISTANCE + 50})\n"
            f"        double3 xformOp:translate = ({cx + ox}, {cy + oy}, {STUDIO_Z + CAMERA_DISTANCE})\n"
            '        uniform token[] xformOpOrder = ["xformOp:translate"]\n    }\n'
            f'    def RenderProduct "Render_{chunk_id}"\n    {{\n'
            f"        rel camera = <{root}/Camera_{chunk_id}>\n"
            f"        uniform int2 resolution = ({WIDTH}, {HEIGHT})\n"
            f"        rel orderedVars = [<{root}/Render_{chunk_id}/{LDR_VAR}>, <{root}/Render_{chunk_id}/{DEPTH_VAR}>]\n"
            f'        def RenderVar "{LDR_VAR}"\n        {{\n            uniform string sourceName = "{LDR_VAR}"\n        }}\n'
            f'        def RenderVar "{DEPTH_VAR}"\n        {{\n            uniform string sourceName = "{DEPTH_VAR}"\n        }}\n'
            "    }\n"
        )
        products.append(f"Render_{chunk_id}")
        for offset, item in enumerate(chunk):
            index = chunk_start + offset
            x, y = _cell(index)
            if real_cubes:
                out.append(
                    f'    def Cube "Real_{index}" (\n        prepend apiSchemas = ["MaterialBindingAPI"]\n    )\n    {{\n'
                    f"        double size = 1\n        double3 xformOp:translate = ({x}, {y}, {STUDIO_Z})\n"
                    '        uniform token[] xformOpOrder = ["xformOp:translate"]\n'
                    f"        rel material:binding = <{item['path']}>\n    }}\n"
                )
            out.append(
                f'    def Cube "Ref_{index}" (\n        prepend apiSchemas = ["MaterialBindingAPI"]\n    )\n    {{\n'
                f"        double size = 1\n        double3 xformOp:translate = ({x + 1.4}, {y}, {STUDIO_Z})\n"
                '        uniform token[] xformOpOrder = ["xformOp:translate"]\n'
                f"        rel material:binding = <{root}/RefLook_{index}>\n    }}\n"
            )
            out.append(_reference_material_text(root, index, item, work_dir))
    out.append("}\n")
    return "".join(out), products


def studio_stage(scene: str, todo: list[dict[str, Any]], work_dir: str) -> Any:
    """Compose a stage for the separate process: the scene, its lights switched off, and the studio."""

    from pxr import Usd, UsdLux

    stage = Usd.Stage.CreateInMemory()
    text, names = studio_layer_text(todo, work_dir, LIVE_PREFIX, real_cubes=True)
    studio_file = os.path.join(work_dir, "studio.usda")
    with open(studio_file, "w", encoding="utf-8") as handle:
        handle.write(text)
    stage.GetRootLayer().subLayerPaths.append(studio_file)
    stage.GetRootLayer().subLayerPaths.append(scene)
    source = Usd.Stage.Open(scene)
    for prim in source.Traverse():
        if prim.HasAPI(UsdLux.LightAPI) or prim.IsA(UsdLux.BoundableLightBase) or prim.IsA(UsdLux.NonboundableLightBase):
            stage.OverridePrim(prim.GetPath()).SetActive(False)
    stage.SetMetadata("customLayerData", {"ovuiProbeProducts": [f"{LIVE_PREFIX}/{n}" for n in names]})
    return stage


def _pixel(index: int) -> tuple[int, int, int, int]:
    """Pixel centres of the real and the reference cube of one cell."""

    x, y = _cell_in_chunk(index)
    cx = (COLS - 1) * PAIR_W / 2 + 0.75
    cy = -(ROWS - 1) * ROW_H / 2
    per_unit = WIDTH / (APERTURE / FOCAL * CAMERA_DISTANCE)
    return (
        int(WIDTH / 2 + (x - cx) * per_unit), int(HEIGHT / 2 - (y - cy) * per_unit),
        int(WIDTH / 2 + (x + 1.4 - cx) * per_unit), int(HEIGHT / 2 - (y - cy) * per_unit),
    )


#: Pixels of the shape that must be left after its edge is cut away, to judge a colour.
MIN_PIXELS = 25
_PER_UNIT = WIDTH / (APERTURE / FOCAL * CAMERA_DISTANCE)


def extract_images(frame: Any, device: Any) -> dict[str, Any]:
    """Copy the picture and the distance of one product frame. ``frame`` is a step result; nothing else is touched."""

    import numpy as np

    images: dict[str, Any] = {}
    for key, var in frame.render_vars.items():
        for wanted in (LDR_VAR, DEPTH_VAR):
            if str(key).endswith(wanted):
                mapped = var.map(device=device)
                try:
                    images[wanted] = np.array(np.from_dlpack(mapped))
                finally:
                    mapped.unmap()
    return images


def _covered_mean(image: Any, depth: Any, centre: tuple[int, int]) -> Optional[tuple[float, float, float]]:
    """The mean colour of the pixels that the shape covers in the window around ``centre``, or None when few are left.

    A pixel is covered when its distance is finite. The edge is cut away (two pixels), because a pixel on the
    edge is blended with the background. This is why a shape with a hole (a frame) is judged on what it covers
    and not on the middle of its cell.
    """

    import numpy as np

    half = int(0.5 * _PER_UNIT) + 3
    x, y = centre
    window = (slice(max(y - half, 0), y + half), slice(max(x - half, 0), x + half))
    covered = np.isfinite(np.squeeze(depth)[window])
    for _ in range(2):
        inner = covered.copy()
        inner[1:, :] &= covered[:-1, :]
        inner[:-1, :] &= covered[1:, :]
        inner[:, 1:] &= covered[:, :-1]
        inner[:, :-1] &= covered[:, 1:]
        covered = inner
    if int(covered.sum()) < MIN_PIXELS:
        return None
    pixels = image[window][..., :3][covered]
    return tuple(float(v) for v in pixels.mean(0))


def judge(todo: list[dict[str, Any]], products: list[str], images: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Compare the real shape with its reference in the images of each product. Returns the result per material.

    ``images[product]`` has the picture (``LdrColor``) and the distance (``DistanceToImagePlaneSD``). A
    renderer that gives no distance cannot say what a shape covers: every material is then unverifiable.
    """

    results = {}
    for chunk_id, product in enumerate(products):
        pair = images[product]
        for offset, item in enumerate(todo[chunk_id * CHUNK:(chunk_id + 1) * CHUNK]):
            if DEPTH_VAR not in pair:
                results[item["path"]] = {
                    "state": "unverifiable",
                    "reason": f"the renderer returned no {DEPTH_VAR}, so what the shape covers is not known",
                }
                continue
            rx, ry, fx, fy = _pixel(offset)
            real = _covered_mean(pair[LDR_VAR], pair[DEPTH_VAR], (rx, ry))
            ref = _covered_mean(pair[LDR_VAR], pair[DEPTH_VAR], (fx, fy))
            if real is None or ref is None:
                results[item["path"]] = {
                    "state": "unverifiable",
                    "reason": "too little of the shape is drawn to judge its colour (it is thinner than a few pixels in the check)",
                }
                continue
            same, delta = compare(tuple(int(v) for v in real), tuple(int(v) for v in ref))
            results[item["path"]] = {
                "state": "ok" if same else "mismatch", "difference": delta, "tolerance": TOLERANCE,
                "rendered": [round(v) for v in real], "reference": [round(v) for v in ref],
                "expected_from": item["source"], "resources": item["resources"],
            }
    return results


def compare(real: tuple[int, int, int], ref: tuple[int, int, int], tolerance: int = TOLERANCE) -> tuple[bool, int]:
    """Return (same colour, largest channel difference)."""

    delta = max(abs(a - b) for a, b in zip(real, ref))
    return delta <= tolerance, delta


def run_child(scene: str, path_prefix: str, limit: int) -> dict[str, Any]:
    """Draw the materials with a renderer of this process. Called by the check process."""

    from pxr import Usd

    from ovui_data_adapters.common.ovrtx_import import import_ovrtx

    imported = import_ovrtx()  # the ovrtx of the active environment, or the one OVRTX_ROOT names
    if imported.module is None:
        raise RuntimeError(f"ovrtx is not available ({imported.error})")
    ovrtx = imported.module

    from ovui_data_adapters.common.render_native_log import NativeLogTail

    source = Usd.Stage.Open(scene)
    todo, results = plan(source, path_prefix, limit)
    if not todo:
        return {"materials": results, "events": []}
    work_dir = tempfile.mkdtemp(prefix="ovui-probe-work-")
    log_path = os.path.join(work_dir, "ovrtx.log")
    diagnostics = RenderDiagnostics()
    tail = NativeLogTail(log_path, diagnostics, interval=0.2).start()
    try:
        studio = studio_stage(scene, todo, work_dir)
        renderer = ovrtx.Renderer(ovrtx.RendererConfig(log_file_path=log_path))
        renderer.open_usd_from_string(studio.GetRootLayer().ExportToString())
        products = studio.GetMetadata("customLayerData")["ovuiProbeProducts"]
        images = {}
        for product in products:
            for _ in range(4):
                output = renderer.step(render_products={product}, delta_time=1 / 60)
            images[product] = extract_images(output[product].frames[0], ovrtx.Device.CPU)
        results.update(judge(todo, products, images))
    finally:
        tail.stop()
        shutil.rmtree(work_dir, ignore_errors=True)
    return {"materials": results, "events": diagnostics.events()}


def clone_matrix(item: dict[str, Any], cell: int) -> list[list[float]]:
    """The world matrix (row-vector convention) that fits a geometry prim into its cell of the studio."""

    import numpy as np

    x, y = _cell(cell)
    move_to_origin = np.eye(4)
    move_to_origin[3, :3] = [-c for c in item["centre"]]
    fit = np.diag([1.0 / item["size"]] * 3 + [1.0])
    move_to_cell = np.eye(4)
    move_to_cell[3, :3] = [x, y, STUDIO_Z]
    return (move_to_origin @ fit @ move_to_cell).tolist()


class LivePlan:
    """What an adapter does in its own renderer for the live check.

    1. Add ``layer_text`` at ``mount`` (a reference layer): the dome light, the cameras, the render
       products and the flat reference cubes.
    2. For each of ``clones`` (``target``, ``source``, ``matrix``): clone the original geometry prim
       ``source`` to ``target`` and write ``matrix`` as its transform. The copy keeps its material
       binding, so the renderer draws the ORIGINAL material instance, with the textures and the
       compiled module that the scene uses.
    3. Step each of ``products``, read each with :func:`extract_images`, and call :meth:`judge`.
    4. Remove the layer (the copies go with it) and call :meth:`cleanup`.

    The plan has no OpenUSD in it: the OpenUSD adapter plans from its pxr stage (:func:`plan`), the OVStage
    adapter plans from the native stage (``ovstage/_material_plan.py``).
    """

    def __init__(self, todo: list[dict[str, Any]], skipped: dict[str, dict[str, Any]], mount: str = LIVE_PREFIX) -> None:
        self.todo, self.skipped, self.mount = todo, skipped, mount
        self.work_dir = tempfile.mkdtemp(prefix="ovui-live-check-")
        try:
            self.layer_text, names = studio_layer_text(todo, self.work_dir, "/P") if todo else ("", [])
        except BaseException:
            self.cleanup()
            raise
        self.products = [f"{mount}/{n}" for n in names]
        self.clones = [
            (f"{mount}/Clone_{index}", item["source"], clone_matrix(item, index)) for index, item in enumerate(todo)
        ]

    def judge(self, images: dict[str, Any]) -> dict[str, Any]:
        materials = dict(self.skipped)
        if self.todo:
            materials.update(judge(self.todo, self.products, images))
        return {"materials": materials, "events": []}

    def cleanup(self) -> None:
        shutil.rmtree(self.work_dir, ignore_errors=True)


def live_plan(stage: Any, path_prefix: str = "", limit: int = 500, mount: str = LIVE_PREFIX) -> LivePlan:
    """Plan the live check of the pxr stage that a renderer shows.

    A plan with nothing to draw still carries the materials that cannot be checked: they are
    reported, never dropped.
    """

    todo, skipped = plan(stage, path_prefix, limit)
    return LivePlan(todo, skipped, mount)


class MaterialCheckRequests:
    """The material checks that ``material_verify`` asked a renderer adapter for, until a frame runs them.

    The adapter calls :meth:`run` at each frame that the viewport asks for, also when native frame pacing draws the
    viewport. A request whose caller stopped waiting (its future is cancelled) leaves the queue at once, so it never
    runs later for nobody. Thread safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: collections.deque = collections.deque()

    def __bool__(self) -> bool:
        with self._lock:
            return bool(self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def request(self, path_prefix: str = "", limit: int = 500) -> concurrent.futures.Future:
        """Queue one check. The future gets the result of the check, or its error."""

        pending: concurrent.futures.Future = concurrent.futures.Future()
        item = (path_prefix, limit, pending)
        with self._lock:
            self._items.append(item)
        pending.add_done_callback(lambda future: future.cancelled() and self._discard(item))
        return pending

    def _discard(self, item: tuple[str, int, concurrent.futures.Future]) -> None:
        with self._lock:
            with contextlib.suppress(ValueError):
                self._items.remove(item)

    def run(self, check: Callable[[str, int], dict[str, Any]]) -> None:
        """Run each queued check with ``check(path_prefix, limit)``, on the calling thread."""

        while True:
            with self._lock:
                if not self._items:
                    return
                path_prefix, limit, pending = self._items.popleft()
            if not pending.set_running_or_notify_cancel():
                continue
            try:
                pending.set_result(check(path_prefix, limit))
            except Exception as exc:  # noqa: BLE001 - the caller of material_verify gets it
                pending.set_exception(exc)


def record_result(result: dict[str, Any], diagnostics: Optional[RenderDiagnostics] = None) -> dict[str, Any]:
    """Keep a check result and record an event for each material that is shown wrong.

    A material that could not be checked is recorded as ``unverified`` (it is not known to be right). A missing
    albedo image is a failure of the result; its event comes from the check of the scene's files, so it is not
    recorded twice here. An image that this process cannot read (for example without Pillow) is not a failure.
    """

    diagnostics = diagnostics or get_render_diagnostics()
    set_verification(result["materials"])
    for event in result.get("events", []):
        diagnostics.record(event["material"], event["resource"], event["kind"], event["message"], event.get("context", ""))
    for path, item in result["materials"].items():
        if item["state"] == "mismatch":
            diagnostics.record(
                path, ", ".join(item["resources"]), "mismatch",
                f"rendered colour {tuple(item['rendered'])} differs from the expected colour "
                f"{tuple(item['reference'])} by {item['difference']} (limit {item['tolerance']}): "
                f"the renderer shows a wrong or fallback material",
            )
        elif item["state"] == "unverifiable":
            # Never silently counted as right: the material was not checked, so it is not known to be right.
            diagnostics.record(path, "", "unverified", f"not checked: {item['reason']} (this does not mean it is wrong)")
    result["unverified"] = sorted(p for p, i in result["materials"].items() if i["state"] == "unverifiable")
    result["not_reached"] = sorted(p for p, i in result["materials"].items() if i["state"] == "not_reached")
    if result["not_reached"]:
        LOGGER.warning(
            "the material check stopped at its limit: %d material(s) were not checked (for example %s); "
            "run the material_verify command with a path_prefix to check them",
            len(result["not_reached"]), result["not_reached"][0],
        )
    result["mismatches"] = sorted(p for p, i in result["materials"].items() if i["state"] == "mismatch")
    # Everything that makes the render wrong: a colour that differs, an image that is missing, and each failure
    # that the renderer's own log reported during the check.
    failures = [f"{path}: shown wrong ({result['materials'][path]['difference']} off)" for path in result["mismatches"]]
    failures += [
        f"{path}: {item['reason']}" for path, item in sorted(result["materials"].items())
        if item["state"] == "unverifiable" and item["reason"].startswith("albedo image is missing")
    ]
    failures += [
        f"{event['resource'] or (event['material'] if event['scope'] == 'material' else 'renderer log')}: "
        f"{event['kind']} failure in the renderer log"
        for event in result.get("events", []) if event["kind"] in ("texture", "mdl", "compile", "memory")
    ]
    result["failures"] = list(dict.fromkeys(failures))
    return result


def verify_mode(default: str = "off") -> str:
    """``off``, ``warn`` or ``strict`` from ``OVUI_VERIFY_MATERIALS`` (``1`` means warn; not set means ``default``).

    The automatic check after the first frame draws extra frames of the scene, so it is off unless asked for.
    """

    value = os.environ.get(VERIFY_ENV, "").strip().lower()
    if not value:
        return default
    if value in ("0", "off"):
        return "off"
    return "strict" if value == "strict" else "warn"


def failure_summary(result: dict[str, Any]) -> str:
    """One line that names every failure of a check result."""

    return "; ".join(result["failures"])


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scene")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)
    scene = os.path.abspath(args.scene)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        result = run_child(scene, args.prefix, args.limit)
    except Exception as exc:  # noqa: BLE001 - the exit code and the message tell the caller
        print(f"render check could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    mismatches = sorted(p for p, i in result["materials"].items() if i["state"] == "mismatch")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(result, handle)
    for path, item in sorted(result["materials"].items()):
        extra = f" rendered {item['rendered']} reference {item['reference']} difference {item['difference']}" if "rendered" in item else f" {item.get('reason', '')}"
        print(f"{item['state']:13s} {path}{extra}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
