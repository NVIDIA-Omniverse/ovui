# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Per-material report: what USD says, and what the renderer did.

Each material has two blocks. ``authored`` is read from USD: the output that the
renderer prefers, the shader identifier, the outputs, the texture URIs. It is not
the renderer's state. ``renderer`` is read from what the renderer reported: the
module that it generated code from for each shader prim (``render_telemetry``, from
the renderer's material messages, or from the annotation of the generated module when
the renderer writes one),
the failures in its log, and the result of the render check (see ``render_probe``).
A value that the renderer does not report is ``None`` or ``not_reported``; it is
never filled from the authored data.
"""

from __future__ import annotations

import glob
import hashlib
import os
import time
from typing import Any, Iterable, Optional

from ovui_data_adapters.common.render_diagnostics import (
    RenderDiagnostics,
    get_render_diagnostics,
    get_verification,
)
from ovui_data_adapters.common.render_native_log import (
    generated_modules_dirs,
    native_log_paths,
    read_generated_modules,
    settle_body_resources,
)
from ovui_data_adapters.common.render_telemetry import (
    get_material_messages,
    last_renderer_diagnostics,
    material_messages_state,
    renderer_reports,
)

#: Order in which the RTX renderer prefers a material output: MDL, then MaterialX,
#: then the universal output (UsdPreviewSurface). This is the authored preference
#: of the renderer; whether it was used is in ``renderer.observed_context``.
_CONTEXT_ORDER = (("mdl", "mdl"), ("mtlx", "materialx"), ("", "preview"))


def _asset_state(authored: str, resolved: str) -> tuple[str, int]:
    """Return (state, bytes) for one texture or module asset."""

    target = resolved or authored
    if not target:
        return "unresolved", 0
    if "://" in target and not target.startswith("file://"):
        return "remote_not_checked", 0
    target = target[len("file://"):] if target.startswith("file://") else target
    if "<UDIM>" in target:
        files = glob.glob(target.replace("<UDIM>", "[0-9][0-9][0-9][0-9]"))
        return ("on_disk", sum(os.path.getsize(f) for f in files)) if files else ("missing", 0)
    if os.path.isfile(target):
        return "on_disk", os.path.getsize(target)
    return ("missing" if resolved else "unresolved"), 0


def _producers(connectable: Any) -> list[Any]:
    """Return the shader prims that produce the value of an input or output.

    Connections through a NodeGraph boundary are followed.
    """

    from pxr import UsdShade

    shaders = []
    for attribute in UsdShade.Utils.GetValueProducingAttributes(connectable):
        prim = attribute.GetPrim()
        if prim.IsA(UsdShade.Shader):
            shaders.append(UsdShade.Shader(prim))
    return shaders


def same_resource(event_resource: str, uri: str, resolved: str) -> bool:
    """Whether a failure event names this texture or module.

    The renderer names the absolute path (often as ``file:/...``), USD has the
    authored (often relative) URI. A resolved path must match exactly; a relative
    URI matches when the event path ends with it.
    """

    if not event_resource:
        return False
    event = event_resource[len("file:"):] if event_resource.startswith("file:") else event_resource
    event = os.path.normpath(event).replace("\\", "/")
    if resolved:
        return event == os.path.normpath(resolved).replace("\\", "/")
    if not uri or "://" in uri:
        return False
    tail = os.path.normpath(uri).replace("\\", "/").lstrip("/")
    return event.endswith("/" + tail) or event == tail


def _upstream_shaders(output: Any) -> list[Any]:
    """Return every shader prim upstream of a material output: the roots first, then the rest by path."""

    found: dict[str, Any] = {}
    roots = _producers(output)
    stack = list(roots)
    while stack:
        shader = stack.pop()
        path = str(shader.GetPath())
        if path in found:
            continue
        found[path] = shader
        for shader_input in shader.GetInputs():
            stack.extend(_producers(shader_input))
    root_paths = list(dict.fromkeys(str(shader.GetPath()) for shader in roots))
    rest = sorted(key for key in found if key not in root_paths)
    return [found[key] for key in root_paths + rest]


def shader_identifier(shader: Any) -> str:
    """The identifier that USD authors for a shader (MDL: module and sub-identifier)."""

    prim = shader.GetPrim()
    asset = prim.GetAttribute("info:mdl:sourceAsset")
    if asset and asset.HasAuthoredValue():
        value = asset.Get()
        sub = prim.GetAttribute("info:mdl:sourceAsset:subIdentifier")
        sub_text = sub.Get() if sub and sub.HasAuthoredValue() else ""
        return f"{value.path}#{sub_text}" if sub_text else str(value.path)
    shader_id = shader.GetIdAttr().Get() if shader.GetIdAttr() else None
    return str(shader_id or "")


def asset_attributes(shader: Any) -> Iterable[tuple[Any, Any]]:
    """Yield (attribute, asset path) for each authored asset attribute of a shader."""

    from pxr import Sdf

    for attribute in shader.GetPrim().GetAttributes():
        if attribute.GetTypeName() == Sdf.ValueTypeNames.Asset and attribute.HasAuthoredValue():
            value = attribute.Get()
            if value is not None and (value.path or value.resolvedPath):
                yield attribute, value


def asset_inputs(shader: Any) -> Iterable[tuple[str, Any]]:
    for attribute, value in asset_attributes(shader):
        yield attribute.GetName(), value


def _topology_key(shaders: list[Any]) -> str:
    """Hash the node types and connections, not the textures or node names."""

    lines = []
    for shader in shaders:
        for shader_input in shader.GetInputs():
            for source in _producers(shader_input):
                lines.append(
                    f"{shader_identifier(shader).split('#')[0]}.{shader_input.GetBaseName()}<-"
                    f"{shader_identifier(source).split('#')[0]}"
                )
    if not lines:
        return ""
    return hashlib.sha1("\n".join(sorted(lines)).encode()).hexdigest()[:12]


def _owner_material(origin: str, material_paths: list[str]) -> Optional[str]:
    """The material whose path is the longest prefix of an origin prim path."""

    best = None
    for path in material_paths:
        if (origin == path or origin.startswith(path + "/")) and (best is None or len(path) > len(best)):
            best = path
    return best


def _from_messages(entry: dict[str, Any], contexts: dict[str, list[str]], messages: Any) -> None:
    """Fill ``entry["renderer"]`` from the renderer's material messages for the shader prims of the material.

    ``contexts`` maps each connected output (``mdl``, ``materialx``, ``preview``) to the shader prims
    upstream of it. The output that the renderer used is known only when the shader prims that it
    generated code for are upstream of one output: one shader prim can serve several outputs.
    """

    shaders = list(dict.fromkeys(path for paths in contexts.values() for path in paths))
    seen = messages.for_shaders(shaders)
    renderer = entry["renderer"]
    renderer["generated"] = [
        {k: item[k] for k in ("shader", "module", "entity", "kind", "message") if k in item} for item in seen
    ]
    if not seen:
        renderer["generation"] = "not_reported"
        return
    renderer["generation"] = "reported"
    modules = sorted({item["module"] + (f"::{item['entity']}" if item.get("entity") else "") for item in seen})
    renderer["compiled_module"] = {
        "id": modules[0] if len(modules) == 1 else modules,
        "shaders": [item["shader"] for item in seen],
        "how": "the renderer's materials channel (public log callback): " + seen[0]["message"][:160],
    }
    used = sorted(name for name, paths in contexts.items() if any(item["shader"] in paths for item in seen))
    if len(used) == 1:
        renderer["observed_context"] = used[0]
    else:
        renderer["candidate_contexts"] = used
        entry["warnings"].append(
            f"the shader prim that the renderer generated code for is connected to the outputs {used}; "
            "the renderer does not say which output it used"
        )


def _compiled_modules(material_paths: list[str]) -> list[dict[str, Any]]:
    modules = read_generated_modules()
    for module in modules:
        owners = {_owner_material(origin, material_paths) for origin in module["origins"]}
        module["materials"] = sorted(owner for owner in owners if owner)
    return modules


def shader_files(stage: Any) -> list[dict[str, Any]]:
    """Every texture or MDL file that a Shader prim of the stage names, with the material that holds the shader.

    One pass over the prims, without a limit (Factory: 11,205 shaders in 0.3 s). Each item has ``material``, ``uri``
    (authored), ``resolved``, ``kind`` (``texture`` or ``mdl``) and ``missing`` (the state when the file is not on
    disk, else None). A bare MDL module name is found by the renderer's search path: it is not missing. Each file
    is looked up on disk once.
    """

    from pxr import Sdf

    asset_type = Sdf.ValueTypeNames.Asset
    states: dict[tuple[str, str], tuple[str, int]] = {}
    files = []
    for prim in stage.Traverse():
        if prim.GetTypeName() != "Shader":
            continue
        owner = prim.GetParent()
        while owner and owner.GetTypeName() != "Material":
            owner = owner.GetParent()
        material = str(owner.GetPath()) if owner else str(prim.GetPath())
        for attribute in prim.GetAuthoredAttributes():
            if attribute.GetTypeName() != asset_type:
                continue
            value = attribute.Get()
            if value is None or not (value.path or value.resolvedPath):
                continue
            key = (value.path, value.resolvedPath)
            state = states.get(key)
            if state is None:
                state = states[key] = _asset_state(value.path, value.resolvedPath)
            name = attribute.GetName()
            is_mdl = name == "info:mdl:sourceAsset"
            missing = state[0] if state[0] in ("missing", "unresolved") and not (is_mdl and state[0] == "unresolved") else None
            files.append({
                "material": material, "uri": value.path, "resolved": value.resolvedPath,
                "kind": "mdl" if is_mdl else "texture", "missing": missing,
            })
    return files


#: Materials named in events for one failing file. A file that many materials use (Factory: one MDL module, 712
#: materials) would otherwise fill the event list; the report still finds every material that uses the file.
FILE_EVENT_MATERIALS = 10


def record_file_events(files: Iterable[dict[str, Any]], diagnostics: Optional[RenderDiagnostics] = None) -> dict[str, int]:
    """Make each file failure name its materials.

    For every file of ``files`` (see :func:`shader_files`): a file that is not on disk is an event of its
    materials (the renderer does not always say it: it can draw a fallback for a missing texture and
    write no line); and a renderer failure that named only that file (``Couldn't process file:...``) is
    recorded again for the materials that use it, with the renderer's message, so that the warning and
    ``health`` name a material and the file. At most :data:`FILE_EVENT_MATERIALS` materials are named for
    one file; each message says how many use it. Returns the number of new events of each sort.
    """

    diagnostics = diagnostics or get_render_diagnostics()
    files = list(files)
    counts = {"missing": 0, "linked": 0}
    # Renderer lines that only the files of the scene can decide (render_native_log.note_body_resource).
    settle_body_resources(files, diagnostics)

    def name(group: list[dict[str, Any]], kind: str, message: str, sort: str) -> None:
        materials = list(dict.fromkeys(item["material"] for item in group))
        suffix = f" ({len(materials)} materials use this file)" if len(materials) > 1 else ""
        for item in [next(i for i in group if i["material"] == m) for m in materials[:FILE_EVENT_MATERIALS]]:
            if diagnostics.record(item["material"], item["uri"], kind, message + suffix):
                counts[sort] += 1

    missing: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in files:
        if item["missing"]:
            missing.setdefault((item["kind"], item["missing"], item["resolved"] or item["uri"]), []).append(item)
    for (kind, state, _file), group in missing.items():
        name(group, kind, f"{kind} {state}: {group[0]['uri']}", "missing")
    for event in [e for e in diagnostics.events() if e["scope"] == "resource"]:
        group = [item for item in files if same_resource(event["resource"], item["uri"], item["resolved"])]
        if group:
            name(group, event["kind"], event["message"], "linked")
    return counts


class FileEventLinker:
    """Names the materials of a renderer failure that names only a file, also when it comes after the first frame.

    The renderer can report a texture that fails to load long after the first frame. :meth:`poll` runs
    :func:`record_file_events` for the files of the scene when there are new events, at most once each
    ``interval`` seconds, so that the warning and ``health`` name the material too.
    """

    def __init__(self, files: list[dict[str, Any]], interval: float = 1.0) -> None:
        self._files = files
        self._interval = interval
        self._version = -1
        self._time = float("-inf")

    def poll(self, now: Optional[float] = None, diagnostics: Optional[RenderDiagnostics] = None) -> bool:
        """Link new events when there are some and the interval has passed. Returns True when it ran."""

        diagnostics = diagnostics or get_render_diagnostics()
        now = time.monotonic() if now is None else now
        version = diagnostics.version()
        if version == self._version or now - self._time < self._interval:
            return False
        record_file_events(self._files, diagnostics)
        self._version, self._time = diagnostics.version(), now
        return True


def new_entry(path: str) -> dict[str, Any]:
    """An empty report entry of one material (the shape of :func:`describe_materials`)."""

    return {
        "path": path,
        "authored": {"context": None, "shader_identifier": None, "outputs": {}},
        "renderer": {"observed_context": None, "compiled_module": None, "inferred_compiled_module": None},
        "topology_key": None,
        "textures": [],
        "render_check": get_verification().get(path, {"state": "not_run"}),
        "events": [],
        "warnings": [],
    }


def texture_entry(shader: str, input_name: str, uri: str, resolved: str) -> dict[str, Any]:
    """One texture or module of a material, with its state on disk (see :func:`describe_materials`)."""

    state, size = _asset_state(uri, resolved)
    if input_name == "info:mdl:sourceAsset" and state == "unresolved":
        # A bare MDL module name is found by the renderer's MDL search path, which the scene cannot see: not a failure.
        state = "search_path"
    return {"shader": shader, "input": input_name, "uri": uri, "resolved": resolved,
            "state": state, "bytes": size, "residency": "not_reported"}


def note_missing_files(entry: dict[str, Any], diagnostics: RenderDiagnostics) -> None:
    """Warn about each texture or module of an entry that is not on disk, and record it as an event."""

    for texture in entry["textures"]:
        if texture["state"] in ("missing", "unresolved"):
            kind = "mdl" if texture["input"] == "info:mdl:sourceAsset" else "texture"
            message = f"{kind} {texture['state']}: {texture['uri']}"
            entry["warnings"].append(message)
            diagnostics.record(entry["path"], texture["uri"], kind, message)


def describe_materials(
    stage: Any,
    path_prefix: str = "",
    diagnostics: Optional[RenderDiagnostics] = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Report each material of an OpenUSD stage (see the module text for the two blocks).

    ``textures[].state`` is the file state seen from USD (``on_disk``, ``missing``,
    ``unresolved``, ``remote_not_checked``, or ``search_path`` for an MDL module name
    that the renderer finds by its own search path). ``textures[].residency`` is
    ``failed`` when the renderer reported a failure for that file; ``unknown`` when a
    scene-wide failure (memory, failed step) happened and nothing else is known;
    otherwise ``not_reported``. The renderer has no residency query, so
    ``not_reported`` does not prove that a texture is resident, and a colour that
    matched in the render check is not residency either: it is in ``render_check``.
    """

    from pxr import UsdShade

    diagnostics = diagnostics or get_render_diagnostics()
    material_prims = [p for p in stage.Traverse() if p.IsA(UsdShade.Material)]
    all_paths = [str(p.GetPath()) for p in material_prims]
    entries: list[dict[str, Any]] = []
    total = 0
    for prim in material_prims:
        path = str(prim.GetPath())
        if path_prefix and not path.startswith(path_prefix):
            continue
        total += 1
        if len(entries) >= limit:
            continue
        material = UsdShade.Material(prim)
        connected = {name: material.GetSurfaceOutput(context) for context, name in _CONTEXT_ORDER}
        connected = {name: out for name, out in connected.items() if out and out.GetConnectedSource()}
        entry = new_entry(path)
        entry["authored"]["outputs"] = {
            name: str(out.GetConnectedSource()[0].GetPrim().GetPath()) for name, out in connected.items()
        }
        entry["_contexts"] = {name: [str(sh.GetPath()) for sh in _upstream_shaders(out)] for name, out in connected.items()}
        if not connected:
            message = "no surface output is connected: the renderer uses a fallback material"
            entry["warnings"].append(message)
            diagnostics.record(path, "", "select", message)
        else:
            name = next(name for _, name in _CONTEXT_ORDER if name in connected)
            entry["authored"]["context"] = name
            if len(connected) > 1:
                targets = {str(o.GetConnectedSource()[0].GetPrim().GetPath()) for o in connected.values()}
                if len(targets) == 1:
                    entry["warnings"].append(
                        f"outputs {sorted(connected)} all connect to one shader; the renderer prefers {name}"
                    )
            shaders = _upstream_shaders(connected[name])
            if shaders:
                entry["authored"]["shader_identifier"] = shader_identifier(shaders[0])
                entry["topology_key"] = _topology_key(shaders) or None
            for shader in shaders:
                for input_name, value in asset_inputs(shader):
                    entry["textures"].append(texture_entry(str(shader.GetPath()), input_name, value.path, value.resolvedPath))
            note_missing_files(entry, diagnostics)
        entries.append(entry)
    return complete_report(entries, total, all_paths, diagnostics)


def complete_report(entries: list[dict[str, Any]], total: int, all_paths: list[str],
                    diagnostics: Optional[RenderDiagnostics] = None) -> dict[str, Any]:
    """Add what the renderer reported to report entries, and wrap them in the report.

    Each entry is from :func:`new_entry`, with ``_contexts`` (each connected output and the shader prims upstream of
    it). Used for an OpenUSD stage (:func:`describe_materials`) and for the native OVStage scene.
    """

    diagnostics = diagnostics or get_render_diagnostics()
    messages = get_material_messages()
    use_messages = material_messages_state()["active"]
    # Some renderers name a generated module by an annotation in it; others write no annotation and name it by
    # message (the material messages).
    modules = [] if use_messages else _compiled_modules(all_paths)
    owner_of_key: dict[str, dict[str, Any]] = {}
    materials = entries
    for entry in materials:
        path = entry["path"]
        contexts = entry.pop("_contexts", {})
        # Renderer state: what the renderer reported for the shader prims of this material.
        key = entry["topology_key"]
        if use_messages:
            _from_messages(entry, contexts, messages)
        owned = next((m for m in modules if path in m["materials"]), None)
        if owned is not None:
            entry["renderer"]["observed_context"] = "materialx"
            entry["renderer"]["compiled_module"] = {
                "id": owned["id"], "path": owned["path"], "origin_materials": owned["materials"],
                "how": "origin annotation of the generated module",
            }
            if key:
                owner_of_key.setdefault(key, owned)
        entry["_module_key"] = key

    events = diagnostics.events()
    for entry in materials:
        path = entry["path"]
        key = entry.pop("_module_key")
        if entry["renderer"]["compiled_module"] is None and key and key in owner_of_key:
            owner = owner_of_key[key]
            # Not an observation: the renderer names no module for this material. The module of the
            # equal graph is shown apart, and the context stays unobserved.
            entry["renderer"]["inferred_compiled_module"] = {
                "id": owner["id"], "path": owner["path"], "origin_materials": owner["materials"],
                "how": "inferred from an equal graph; the renderer does not name this material",
            }
            entry["warnings"].append(
                f"no generated module names this material; a module with an equal graph exists ({owner['id']}, built from "
                f"{', '.join(owner['materials'])}). Whether this material uses it is not reported by the renderer."
            )
        mine = []
        for event in events:
            if event["scope"] == "material" and (event["material"] == path or event["material"].startswith(path + "/")):
                mine.append(event)
            elif event["scope"] == "resource" and any(
                same_resource(event["resource"], t["uri"], t["resolved"]) for t in entry["textures"]
            ):
                mine.append(event)
        entry["events"] = mine
        scene_wide = [e for e in events if e["scope"] == "scene" and e["kind"] in ("memory", "step", "compile")]
        entry["scene_wide_failures"] = len(scene_wide)
        for texture in entry["textures"]:
            failed = [e for e in mine if same_resource(e["resource"], texture["uri"], texture["resolved"])]
            if failed:
                texture["residency"] = "failed"
                if not any(texture["uri"] in w for w in entry["warnings"]):
                    entry["warnings"].append(
                        f"{texture['input']} {texture['uri']}: the renderer reported a failure: {failed[0]['message'][:200]}"
                    )
            elif scene_wide:
                texture["residency"] = "unknown"
        if scene_wide:
            entry["warnings"].append(
                f"{len(scene_wide)} scene-wide failure(s) (memory, step or compile) are not tied to a material: "
                "the state of this material is not known"
            )

    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in materials:
        if entry["topology_key"] and entry["textures"]:
            groups.setdefault(entry["topology_key"], []).append(entry)
    for group in groups.values():
        if len({tuple(sorted(t["uri"] for t in e["textures"])) for e in group}) > 1:
            for entry in group:
                entry["warnings"].append(
                    f"{len(group)} materials share one graph but use different textures; "
                    "run the material_verify command to check that each shows its own"
                )
    return {
        "success": True, "count": len(materials), "total": total, "truncated": total > len(materials),
        "materials": materials, "events": events,
        "scene_events": [e for e in events if e["scope"] == "scene"],
        "native_logs": native_log_paths(), "generated_modules_dirs": generated_modules_dirs(),
        "renderer_reports": renderer_reports(),
        "renderer_totals": last_renderer_diagnostics(),
        "generated_modules": [
            {"id": m["id"], "origins": m["origins"], "materials": m["materials"]} for m in modules
        ],
        "scene_event_note": (
            "A scene event names no material or file. It is not attributed to a material, and every "
            "material is marked unknown (residency `unknown`). `context` is the last material that the "
            "renderer log named before the event; it is a hint only."
        ),
    }
