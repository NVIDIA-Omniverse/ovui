# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Plan the live material check from the CURRENT native OVStage scene, without OpenUSD.

The OVStage provider never imports OpenUSD and never opens a backing stage, so the plan reads the native stage: the
material and shader prims, the connection of each material output to its shader, the inputs of that shader (their
constants, and which come from another shader), the material binding of each geometry prim, and the extent of the
geometry. Everything is read at the stage's current ordinal, so an edit that was made after the scene was opened is
judged as it is now, not as it is on disk.

The reference follows the same rules as for an OpenUSD stage (``render_probe.reference_inputs``). The native check
reads constant colours only: a material whose colour comes from another shader (an image) is ``unverifiable`` with
that reason. A native stage that does not hold connections (older ovstage) is read as it was before: the first shader
of the material that is a surface.
"""

from __future__ import annotations

import math
import os
import re
import struct
from importlib import import_module
from typing import Any, Optional

from ovui_data_adapters.common.render_probe import (
    ShaderInput,
    colour_input,
    not_reached,
    reference_inputs,
)
from ovui_data_adapters.ovstage._native import _read_attribute_bytes, read_token_attribute, resolve_token_id
from ovui_data_adapters.ovstage._scene import _discover_kit_attr_names, _has_kit_stage_bridge, _merge_kit_read_groups
from ovui_data_adapters.ovstage.property_adapter import _read_path_targets

_GPRIMS = frozenset({"Cube", "Sphere", "Mesh", "Cylinder", "Cone", "Capsule", "Plane"})
_ANCESTOR_STEPS = 12
#: Material outputs in the order in which the RTX renderer prefers them (MDL, MaterialX, universal).
_SURFACE_OUTPUTS = (("outputs:mdl:surface", "mdl"), ("outputs:mtlx:surface", "materialx"), ("outputs:surface", "preview"))
#: Attribute semantics of the native stage.
_SEMANTIC_NONE, _SEMANTIC_ASSET, _SEMANTIC_TOKEN, _SEMANTIC_CONNECTION = 0, 1, 2, 12
_SEMANTIC_PREFIX = {5: "point", 6: "vector", 7: "normal", 8: "color", 11: "texCoord"}
#: DLPack type codes and the struct format of each (code, bits).
_FORMATS = {(2, 16): "e", (2, 32): "f", (2, 64): "d", (0, 32): "i", (1, 32): "I", (6, 8): "?"}


def _read_asset(stage: Any, path: str, attr: str) -> str:
    """The authored text of an asset attribute (two interned strings: authored, resolved), or ''."""

    raw = _read_attribute_bytes(stage, path, attr)
    if len(raw) != 16:
        return ""
    authored, _resolved = struct.unpack("<QQ", raw)
    return resolve_token_id(stage, authored)


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if path.count("/") > 1 else ""


def _attribute_info(stage: Any, path: str, attr: str) -> Optional[tuple[tuple[int, int, int], int]]:
    """((DLPack code, bits, lanes), semantic) of an attribute, or None when the stage does not say it."""

    reader = getattr(stage, "read_attribute_info", None)
    if not callable(reader):
        return None
    try:
        info = reader(int(stage.current_ordinal), str(path), str(attr))
        code, bits, lanes = (int(v) for v in info["dtype"])
        return (code, bits, lanes), int(info["semantic"])
    except Exception:  # noqa: BLE001 - an attribute without metadata: its type is not known
        return None


def _type_name(code: int, bits: int, lanes: int, semantic: int) -> str:
    """The USD value type of a native attribute layout, or "" when it is not a plain number, colour or token."""

    if semantic == _SEMANTIC_TOKEN:
        return "token" if lanes == 1 else ""
    if code == 6:
        return "bool" if lanes == 1 else ""
    if code in (0, 1):
        if bits != 32:
            return ""
        if lanes == 1:
            return "int" if code == 0 else "uint"
        return f"int{lanes}" if code == 0 and lanes in (2, 3, 4) else ""
    if code != 2 or bits not in (16, 32, 64):
        return ""
    suffix = {16: "h", 32: "f", 64: "d"}[bits]
    prefix = _SEMANTIC_PREFIX.get(semantic)
    if prefix:
        return f"{prefix}{lanes}{suffix}"
    if semantic != _SEMANTIC_NONE:
        return ""
    base = {"h": "half", "f": "float", "d": "double"}[suffix]
    return base if lanes == 1 else f"{base}{lanes}"


def native_input(stage: Any, path: str, attr: str) -> Optional[ShaderInput]:
    """One ``inputs:*`` attribute of a native shader prim, or None when the prim has no value for it."""

    raw = _read_attribute_bytes(stage, path, attr)
    if not raw:
        return None
    name = attr[len("inputs:"):]
    info = _attribute_info(stage, path, attr)
    if info is None:
        # Without metadata only a colour can be told by its size; any other value has an unknown type.
        if len(raw) == 12:
            return ShaderInput(name, "color3f", struct.unpack("<3f", raw))
        return ShaderInput(name, "", raw)
    (code, bits, lanes), semantic = info
    if semantic == _SEMANTIC_CONNECTION:
        return ShaderInput(name, "", None, True)
    type_name = _type_name(code, bits, lanes, semantic)
    if not type_name:
        return ShaderInput(name, "asset" if semantic == _SEMANTIC_ASSET else "", raw)
    if type_name == "token":
        return ShaderInput(name, type_name, resolve_token_id(stage, struct.unpack("<Q", raw[:8])[0]))
    fmt = _FORMATS.get((code, bits))
    if fmt is None or len(raw) != struct.calcsize(f"<{lanes}{fmt}"):
        return ShaderInput(name, "", raw)
    values = struct.unpack(f"<{lanes}{fmt}", raw)
    return ShaderInput(name, type_name, values[0] if lanes == 1 else tuple(values))


def _surface_shader(stage: Any, material: str, shaders: list[str]) -> tuple[Optional[str], str]:
    """(the shader that the preferred surface output of a material connects to, its family), or (None, "")."""

    for output, family in _SURFACE_OUTPUTS:
        targets = _read_path_targets(stage, material, output) or ()
        for target in targets:
            shader = str(target).split(".outputs:", 1)[0]
            if shader in shaders:
                if family == "mdl" or _read_asset(stage, shader, "info:mdl:sourceAsset"):
                    return shader, "mdl"
                identifier = read_token_attribute(stage, shader, "info:id") or ""
                return shader, ("materialx" if identifier.startswith("ND_") else "preview")
    # A native stage without connections: the first shader of the material that is a surface.
    for shader in shaders:
        if _read_asset(stage, shader, "info:mdl:sourceAsset"):
            return shader, "mdl"
        identifier = read_token_attribute(stage, shader, "info:id") or ""
        if identifier == "UsdPreviewSurface":
            return shader, "preview"
        if identifier.startswith("ND_") and "surface" in identifier:
            return shader, "materialx"
    return None, ""


def _expected(stage: Any, material: str, shaders: list[str],
              attribute_names: dict[str, tuple[str, ...]]) -> tuple[Optional[dict[str, Any]], str]:
    """Return ({"linear", "resources", "source", "family", "identifier", "colour_input", "inputs"}, "") or (None, reason)."""

    root, family = _surface_shader(stage, material, shaders)
    if root is None:
        return None, "no surface shader of the material is found in the native stage"
    inputs = {}
    for attr in attribute_names.get(root, ()):
        if attr.startswith("inputs:"):
            item = native_input(stage, root, attr)
            if item is not None:
                inputs[item.name] = item
    colour = colour_input(inputs)
    if colour is None:
        return None, "no albedo input (base_color, diffuse_color, diffuse_color_constant) is authored"
    if inputs[colour].connected:
        return None, f"{colour} comes from another shader (an image); the native check reads constant colours only"
    value = inputs[colour].value
    if not isinstance(value, tuple) or len(value) != 3:
        return None, f"{colour} is not a colour"
    copied, reason = reference_inputs(family, inputs, colour)
    if copied is None:
        return None, reason
    identifier = read_token_attribute(stage, root, "info:id") or ""
    return {"linear": tuple(float(c) for c in value), "resources": [], "source": f"constant {colour}", "family": family,
            "identifier": identifier, "colour_input": colour, "inputs": copied}, ""


def _bound_material(stage: Any, path: str) -> str:
    """The material that a geometry prim is bound to: its own binding, else that of the nearest ancestor."""

    current = path
    for _ in range(_ANCESTOR_STEPS):
        if not current:
            break
        targets = _read_path_targets(stage, current, "material:binding")
        if targets:
            return str(targets[0])
        current = _parent(current)
    return ""


def _bounds(stage: Any, path: str) -> Optional[tuple[tuple[float, float, float], float]]:
    """(centre, size) of the extent of a geometry prim in its own space, or None."""

    raw = _read_attribute_bytes(stage, path, "extent")
    if len(raw) == 24:
        values = struct.unpack("<6f", raw)
    elif len(raw) == 48:
        values = struct.unpack("<6d", raw)
    else:
        return None
    low, high = values[:3], values[3:]
    size = max(high[i] - low[i] for i in range(3))
    centre = tuple((low[i] + high[i]) / 2 for i in range(3))
    if not (0 < size < math.inf) or any(c != c for c in centre):
        return None
    return centre, float(size)


def plan_native(stage: Any, records: dict[str, str], attribute_names: dict[str, tuple[str, ...]],
                path_prefix: str = "", limit: int = 500):
    """Return (materials to draw, result for each material that cannot be checked), as ``render_probe.plan`` does.

    ``attribute_names`` are the attribute names of each shader prim (:func:`read_shader_catalog`).
    """

    materials = sorted(path for path, kind in records.items() if kind == "Material" and path.startswith(path_prefix))
    shaders: dict[str, list[str]] = {}
    for path, kind in records.items():
        if kind == "Shader":
            owner = _owner_material(path, records)
            shaders.setdefault(owner, []).append(path)
    todo, skipped, expected = [], {}, {}
    for material in materials[limit:]:
        skipped[material] = not_reached(limit)
    for material in materials[:limit]:
        item, reason = _expected(stage, material, sorted(shaders.get(material, [])), attribute_names)
        if item is None:
            skipped[material] = {"state": "unverifiable", "reason": reason}
        else:
            expected[material] = item
    wanted = set(expected)
    geometry: dict[str, dict[str, Any]] = {}
    for path, kind in records.items():
        if not wanted:
            break
        if kind not in _GPRIMS:
            continue
        material = _bound_material(stage, path)
        if material not in wanted:
            continue
        bounds = _bounds(stage, path)
        if bounds is None:
            continue
        geometry[material] = {"source": path, "centre": bounds[0], "size": bounds[1]}
        wanted.discard(material)
    for material, item in expected.items():
        if material in geometry:
            todo.append({"path": material, **item, **geometry[material]})
        else:
            skipped[material] = {
                "state": "unverifiable",
                "reason": "no geometry with a finite extent is bound to this material in the native stage",
            }
    return todo, skipped


_FILE = re.compile(r"\.(mdl|png|jpe?g|exr|tiff?|tga|bmp|hdr|dds|webp|ktx2?|tx)$", re.IGNORECASE)


def _read_shader_values(stage: Any) -> tuple[dict[tuple[str, str], bytes], dict[tuple[str, str], int]]:
    """The value and the semantic of every ``inputs:*`` and ``info:mdl:sourceAsset`` attribute of the stage.

    One read of only these attributes at the current ordinal (a tenth of a second on a large scene), not the query of
    every attribute of every prim (seconds). A stage of an older ovstage that answers ``query_prims`` itself has no
    such read: its shader groups are read.
    """

    if not _has_kit_stage_bridge(stage) and callable(getattr(stage, "query_prims", None)):
        return _read_shader_group_values(stage)
    ovstage = import_module("ovstage")
    values: dict[tuple[str, str], bytes] = {}
    semantics: dict[tuple[str, str], int] = {}
    with ovstage.PathDictionary(stage) as paths:
        wanted = [
            name for name in _discover_kit_attr_names(stage)
            if name.startswith("inputs:") or name == "info:mdl:sourceAsset"
        ]
        if wanted:
            _merge_kit_read_groups(
                stage, paths, attr_tokens=[paths.intern_token(name) for name in wanted],
                ordinal_range=ovstage.OrdinalRange.latest(int(stage.current_ordinal)), attrs=values, dtypes={},
                semantics=semantics, arrays={}, path_order=[], seen_paths=set(),
            )
    return values, semantics


def _read_shader_group_values(stage: Any) -> tuple[dict[tuple[str, str], bytes], dict[tuple[str, str], int]]:
    values: dict[tuple[str, str], bytes] = {}
    semantics: dict[tuple[str, str], int] = {}
    result = stage.query_prims(int(stage.current_ordinal))
    for group in result.get("groups", ()):
        if str(group.get("prim_type") or "") != "Shader":
            continue
        names = [
            str(name) for name in group.get("attributes", ()) or ()
            if str(name).startswith("inputs:") or str(name) == "info:mdl:sourceAsset"
        ]
        handle = int(group.get("prim_list_handle") or 0)
        if not handle or not names:
            continue
        for path in map(str, stage.get_prim_paths(handle)):
            for name in names:
                raw = _read_attribute_bytes(stage, path, name)
                if not raw:
                    continue
                values[(path, name)] = raw
                info = _attribute_info(stage, path, name)
                if info is not None:
                    semantics[(path, name)] = info[1]
    return values, semantics


def _owner_material(path: str, records: dict[str, str]) -> str:
    current = _parent(path)
    while current:
        if records.get(current) == "Material":
            return current
        current = _parent(current)
    return path


def read_shader_catalog(stage: Any, records: dict[str, str]) -> tuple[dict[str, tuple[str, ...]], list[dict[str, Any]]]:
    """The ``inputs:*`` and ``info:mdl:sourceAsset`` names of each Shader prim that has a value for them, and every
    texture or MDL file that they name, in the shape of ``render_material_report.shader_files``.

    An asset value is two interned strings (authored, resolved). A bare MDL module name that is not resolved
    is found by the renderer's search path: not missing. A remote URI is not checked.
    """

    values, semantics = _read_shader_values(stage)
    names: dict[str, list[str]] = {}
    files = []
    for (shader, name), raw in values.items():
        if records.get(shader) != "Shader":
            continue
        names.setdefault(shader, []).append(name)
        # A stage that does not give the semantic: a value of two interned strings that names a file is an asset.
        if len(raw) != 16 or semantics.get((shader, name), _SEMANTIC_ASSET) != _SEMANTIC_ASSET:
            continue
        authored_id, resolved_id = struct.unpack("<QQ", raw)
        authored = resolve_token_id(stage, authored_id)
        if not authored or not _FILE.search(authored):
            continue
        resolved = resolve_token_id(stage, resolved_id)
        is_mdl = name == "info:mdl:sourceAsset"
        local = resolved[len("file:"):] if resolved.startswith("file:") else resolved
        if (is_mdl and not resolved) or ("://" in resolved and not resolved.startswith("file:")):
            missing = None
        elif not resolved:
            missing = "unresolved"
        else:
            missing = None if os.path.isfile(local) else "missing"
        files.append({"material": _owner_material(shader, records), "uri": authored, "resolved": local,
                      "kind": "mdl" if is_mdl else "texture", "missing": missing})
    return {shader: tuple(sorted(found)) for shader, found in names.items()}, files
