# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The per-material report of the native OVStage scene, without OpenUSD.

The same report as ``render_material_report.describe_materials`` gives for an OpenUSD stage, read from the native
stage at its current ordinal, so an edit that is not saved is reported as it is shown. A native stage that does not
hold shader connections (older ovstage) gives the shaders of each material without the output that uses them.
"""

from __future__ import annotations

import struct
from typing import Any, Optional

from ovui_data_adapters.common.render_diagnostics import RenderDiagnostics, get_render_diagnostics
from ovui_data_adapters.common.render_material_report import complete_report, new_entry, note_missing_files, texture_entry
from ovui_data_adapters.ovstage._material_plan import _SURFACE_OUTPUTS, _owner_material
from ovui_data_adapters.ovstage._native import _read_attribute_bytes, read_token_attribute, resolve_token_id
from ovui_data_adapters.ovstage.property_adapter import _read_path_targets


def _target_prim(target: Any) -> str:
    return str(target).split(".outputs:", 1)[0]


def _upstream(stage: Any, root: str, attribute_names: dict[str, tuple[str, ...]]) -> list[str]:
    """The shader prims upstream of ``root`` through the connections of their inputs: the root first, then by path."""

    found, stack = [root], [root]
    while stack:
        shader = stack.pop()
        for attr in attribute_names.get(shader, ()):
            if not attr.startswith("inputs:"):
                continue
            for target in _read_path_targets(stage, shader, attr) or ():
                source = _target_prim(target)
                if source in attribute_names and source not in found:
                    found.append(source)
                    stack.append(source)
    return [root] + sorted(found[1:])


def _identifier(stage: Any, shader: str) -> str:
    asset = _asset(stage, shader, "info:mdl:sourceAsset")
    if asset is not None and asset[0]:
        sub = read_token_attribute(stage, shader, "info:mdl:sourceAsset:subIdentifier") or ""
        return f"{asset[0]}#{sub}" if sub else asset[0]
    return read_token_attribute(stage, shader, "info:id") or ""


def _asset(stage: Any, shader: str, attr: str) -> Optional[tuple[str, str]]:
    """(authored, resolved) of an asset attribute, or None when the value is not an asset."""

    raw = _read_attribute_bytes(stage, shader, attr)
    if len(raw) != 16:
        return None
    authored_id, resolved_id = struct.unpack("<QQ", raw)
    authored = resolve_token_id(stage, authored_id)
    if not authored:
        return None
    resolved = resolve_token_id(stage, resolved_id)
    return authored, (resolved[len("file:"):] if resolved.startswith("file:") else resolved)


def _is_asset(stage: Any, shader: str, attr: str) -> bool:
    reader = getattr(stage, "read_attribute_info", None)
    if not callable(reader):
        return False
    try:
        return int(reader(int(stage.current_ordinal), shader, attr)["semantic"]) == 1
    except Exception:  # noqa: BLE001 - an attribute without metadata is not read as a file
        return False


def describe_native_materials(stage: Any, records: dict[str, str], attribute_names: dict[str, tuple[str, ...]],
                              path_prefix: str = "", limit: int = 500,
                              diagnostics: Optional[RenderDiagnostics] = None) -> dict[str, Any]:
    """Report each material of the native stage (see ``render_material_report.describe_materials``).

    ``records`` are the prim types of the stage and ``attribute_names`` the attribute names of each shader prim.
    """

    diagnostics = diagnostics or get_render_diagnostics()
    all_paths = sorted(path for path, kind in records.items() if kind == "Material")
    materials = [path for path in all_paths if path.startswith(path_prefix)]
    shaders: dict[str, list[str]] = {}
    for path, kind in records.items():
        if kind == "Shader":
            shaders.setdefault(_owner_material(path, records), []).append(path)
    entries = []
    for path in materials[:limit]:
        entry = new_entry(path)
        own = sorted(shaders.get(path, []))
        outputs = {}
        for output, name in _SURFACE_OUTPUTS:
            targets = [_target_prim(t) for t in (_read_path_targets(stage, path, output) or ())]
            if targets and targets[0] in attribute_names:
                outputs[name] = targets[0]
        entry["authored"]["outputs"] = outputs
        entry["_contexts"] = {name: _upstream(stage, shader, attribute_names) for name, shader in outputs.items()}
        if outputs:
            name = next(name for _output, name in _SURFACE_OUTPUTS if name in outputs)
            entry["authored"]["context"] = name
            if len(outputs) > 1 and len(set(outputs.values())) == 1:
                entry["warnings"].append(f"outputs {sorted(outputs)} all connect to one shader; the renderer prefers {name}")
            used = entry["_contexts"][name]
            entry["authored"]["shader_identifier"] = _identifier(stage, used[0])
        else:
            used = own
            entry["warnings"].append(
                "the native stage holds no surface output connection of this material; its shaders are listed"
            )
        for shader in used:
            for attr in attribute_names.get(shader, ()):
                if not (attr.startswith("inputs:") or attr == "info:mdl:sourceAsset"):
                    continue
                if attr != "info:mdl:sourceAsset" and not _is_asset(stage, shader, attr):
                    continue
                asset = _asset(stage, shader, attr)
                if asset is not None:
                    entry["textures"].append(texture_entry(shader, attr, asset[0], asset[1]))
        note_missing_files(entry, diagnostics)
        entries.append(entry)
    return complete_report(entries, len(materials), all_paths, diagnostics)
