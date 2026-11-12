# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""What the renderer reports about materials and texture memory, through the supported ovrtx routes."""

from __future__ import annotations

import ctypes
import importlib.metadata
import os
import pathlib
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ovui_data_adapters.common import render_telemetry as rt

GENERATOR = pathlib.Path(__file__).resolve().parents[1] / "data" / "make_material_regression_scene.py"

# The forms of the messages of the materials channel, with made-up module names and times.
NATIVE = ("Generation of /opt/renderer/mdl/Base/OmniPBR.mdl//World/Looks/Floor/Shader took 0.25 sec "
          "(in task queue for 0.5 sec)")
MTLX_GENERATED = ("Generation of omni_mtlx_greens/materialx.mdl/usd::rtx_scope0::/World/Looks/Greens/OpenPBR::::"
                  "omni_mtlx_greens::materialx::omniMaterial((13)) took 0.5 sec (in task queue for 0.25 sec)")
MTLX_STORED = ("Stored MdlEntitySnapshot to DB: usd::rtx_scope0::/World/Looks/Whitewash/OpenPBR::::"
               "omni_mtlx_greens::materialx::omniMaterial((10))")


def test_the_messages_that_name_a_shader_prim_and_its_module_are_kept():
    store = rt.MaterialMessages()
    assert store.take(NATIVE) and store.take(MTLX_GENERATED) and store.take(MTLX_STORED)
    assert not store.take("Created Material Instance '/World/Looks/Floor/Shader' (parent: 0x1 instance: 0x2)")
    assert not store.take("Generation and compilation of /opt/OmniPBR.mdl took 0.5 sec (queued for 0.25 sec)")
    floor, greens, whitewash = store.for_shaders(
        ["/World/Looks/Floor/Shader", "/World/Looks/Greens/OpenPBR", "/World/Looks/Whitewash/OpenPBR"])
    assert floor["module"] == "/opt/renderer/mdl/Base/OmniPBR.mdl" and floor["kind"] == "mdl_module"
    assert (greens["module"], greens["entity"], greens["kind"]) == ("omni_mtlx_greens::materialx", "omniMaterial", "generated_module")
    assert (whitewash["module"], whitewash["entity"]) == ("omni_mtlx_greens::materialx", "omniMaterial")
    assert store.for_shaders(["/World/Looks/Other/Shader"]) == []


def test_the_message_store_is_bounded_and_says_how_many_fell_out():
    store = rt.MaterialMessages(limit=2)
    for name in ("A", "B", "C"):
        store.take(NATIVE.replace("/World/Looks/Floor/Shader", f"/World/{name}/Shader"))
    assert store.count() == 2 and store.dropped() == 1
    assert store.for_shaders(["/World/A/Shader"]) == [] and store.for_shaders(["/World/C/Shader"])


_LOGGING_TYPES = """
typedef struct ovx_log_message_t
{
    size_t thisSize;
    /** Severity level of the message. */
    ovx_log_severity_t severity;
    ovx_string_t libraryName;
    ovx_string_t channel;
    uint64_t timestampNs; // wall clock
    uint64_t elapsedTimeNs;
    ovx_string_t filePath;
    uint32_t lineNumber;
    ovx_string_t functionName;
    uint32_t processId;
    uint32_t threadId;
    uint64_t sequenceNumber;
    ovx_string_t message;
} ovx_log_message_t;
"""


def _package(tmp_path, logging_h, logging_types):
    root = tmp_path / "ovrtx"
    (root / "include" / "ovrtx").mkdir(parents=True)
    (root / "include" / "ovx").mkdir(parents=True)
    if logging_h is not None:
        (root / "include" / "ovrtx" / "ovrtx_logging.h").write_text(logging_h)
    (root / "include" / "ovx" / "logging_types.h").write_text(logging_types)
    return SimpleNamespace(__file__=str(root / "__init__.py"))


def test_the_callback_is_used_only_with_the_message_layout_that_the_headers_declare(tmp_path):
    declares = "ovrtx_result_t ovrtx_set_log_callback(ovx_log_severity_t severity, ...);"
    assert rt.log_callback_support(_package(tmp_path / "a", declares, _LOGGING_TYPES)) == (True, "")
    # A renderer without the public log callback: no ovrtx_logging.h
    supported, reason = rt.log_callback_support(_package(tmp_path / "b", None, _LOGGING_TYPES))
    assert not supported and "ovrtx_logging.h" in reason
    changed = _LOGGING_TYPES.replace("    uint32_t lineNumber;\n", "")
    supported, reason = rt.log_callback_support(_package(tmp_path / "c", declares, changed))
    assert not supported and "other fields" in reason


def _loaded_extension_module():
    """A native library that this process has really loaded, and an address in its code.

    NumPy's compiled core is a separate library file on every platform; its module init function is in it.
    """

    import numpy._core._multiarray_umath as core

    library = ctypes.CDLL(core.__file__)
    return pathlib.Path(core.__file__), ctypes.cast(library.PyInit__multiarray_umath, ctypes.c_void_p).value


def test_the_file_of_loaded_code_is_found_from_an_address_in_it():
    path, address = _loaded_extension_module()
    found, why = rt.loaded_library_file(address)
    assert found is not None and os.path.samefile(found, path), why
    # Memory that no library file holds (a buffer of this process) has no file.
    buffer = ctypes.create_string_buffer(64)
    found, why = rt.loaded_library_file(ctypes.addressof(buffer))
    assert found is None and why


def _record(path, data):
    return f"{path},sha256={rt._record_digest(data)},{len(data)}\n"


def _install(folder, name, version, files, requires=()):
    """An installed distribution in ``folder``: its files, its METADATA and its RECORD (with SHA-256s)."""

    info = folder / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    lines = "".join(f"Requires-Dist: {item}\n" for item in requires)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n{lines}")
    record = ""
    for relative, data in files.items():
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        record += _record(relative, data)
    (info / "RECORD").write_text(record)


def _header(entries):
    return "".join(f"    ovrtx_result_t (*{name})(ovrtx_renderer_t* renderer);\n" for name in entries).encode()


def _contract(tmp_path, monkeypatch, library_data, client=True, pin="ovrtx==build-a", header_entries=None,
              edit_header=False):
    """Ask the gate about the really loaded ``library`` with the distributions of one made-up install folder.

    The renderer of the folder is build ``build-a``; its record lists ``library_data`` under the name of the loaded
    library. The build names are made up: the gate never depends on which build it is.
    """

    path, address = _loaded_extension_module()
    folder = tmp_path / "site"
    _install(folder, "ovrtx", "build-a", {"ovrtx/__init__.py": b"", f"ovrtx/bin/plugins/{path.name}": library_data})
    if client:
        header = _header(rt.DIAGNOSTICS_ENTRIES if header_entries is None else header_entries)
        _install(folder, "ovrtx-extensions", "build-a", {rt.DIAGNOSTICS_HEADER: header},
                 requires=[pin] if pin else [])
        if edit_header:
            (folder / rt.DIAGNOSTICS_HEADER).write_bytes(header + b"// edited after the install\n")
    monkeypatch.setattr(rt, "_CONTRACTS", {})
    # Only the gate's view of the search path is replaced, so it sees no real install. Python keeps its own path:
    # reading package metadata imports more of the standard library on first use (from Python 3.13 on).
    monkeypatch.setattr(rt, "sys", SimpleNamespace(path=[str(tmp_path / "nothing-else")], platform=sys.platform))
    return rt.diagnostics_contract(SimpleNamespace(__file__=str(folder / "ovrtx" / "__init__.py")), address)


def test_the_table_is_read_only_when_the_loaded_code_is_a_file_of_the_build_of_its_contract(tmp_path, monkeypatch):
    """The layout of the table comes from a client contract only when the native code that holds the table is, by
    its SHA-256, a file of the exact build that the contract belongs to. Package metadata alone is never enough:
    with OVRTX_ROOT the Python package and its client can come from one build and the native files from another."""

    loaded = _loaded_extension_module()[0].read_bytes()
    known, why = _contract(tmp_path / "a", monkeypatch, loaded)
    assert known and "is a file of ovrtx build-a" in why
    # The split layout: the package, its record and its client are of build-a, the loaded native code is not.
    known, why = _contract(tmp_path / "b", monkeypatch, b"the native file of another build")
    assert not known and "is not a file of ovrtx build-a" in why and "SHA-256 differs" in why
    # No client contract: the layout is not known.
    known, why = _contract(tmp_path / "c", monkeypatch, loaded, client=False)
    assert not known and "no client contract" in why
    # A client that does not name its exact build, or names a build that is not installed.
    known, why = _contract(tmp_path / "d", monkeypatch, loaded, pin="ovrtx>=0")
    assert not known and "does not name the exact ovrtx build" in why
    known, why = _contract(tmp_path / "e", monkeypatch, loaded, pin="ovrtx==build-b")
    assert not known and "that build is not installed" in why
    # A header that is not the file of the client's record.
    known, why = _contract(tmp_path / "f", monkeypatch, loaded, edit_header=True)
    assert not known and "is not the file that the record" in why
    # The right build, but its table has other entries (an older renderer has 2 under the same name).
    known, why = _contract(tmp_path / "g", monkeypatch, loaded, header_entries=rt.DIAGNOSTICS_ENTRIES[:2])
    assert not known and "has other entries (2:" in why


def test_a_log_message_is_read_only_when_its_size_covers_the_fields_that_are_read(monkeypatch):
    """A message gives its own size: a smaller message has another layout, and no field past its size is read."""

    monkeypatch.setattr(rt, "_MESSAGES", rt.MaterialMessages())
    monkeypatch.setitem(rt._STATE, "callback_errors", 0)
    text = NATIVE.encode()
    buffer = ctypes.create_string_buffer(text)
    message = rt._OvxLogMessage(thisSize=ctypes.sizeof(rt._OvxLogMessage), severity=rt._OVX_LOG_VERBOSE)
    message.message = rt._OvxString(ctypes.cast(buffer, ctypes.c_void_p), len(text))
    message.thisSize = ctypes.sizeof(rt._OvxLogMessage) - ctypes.sizeof(rt._OvxString)
    rt._on_message(ctypes.pointer(message), None)
    assert rt.get_material_messages().count() == 0 and rt._STATE["callback_errors"] == 1
    message.thisSize = ctypes.sizeof(rt._OvxLogMessage)
    rt._on_message(ctypes.pointer(message), None)
    assert rt.get_material_messages().count() == 1 and rt._STATE["callback_errors"] == 1


def test_the_material_messages_are_off_unless_they_are_asked_for(monkeypatch):
    """They cost time while a scene loads (Factory: first frame 27.9 s without, 31.2 s with), so they are opt-in."""

    monkeypatch.setitem(rt._STATE, "prepared", True)
    monkeypatch.delenv(rt.MESSAGES_ENV, raising=False)
    reason = rt.prepare_material_messages()
    assert f"set {rt.MESSAGES_ENV}=1" in reason and rt._STATE["prepared"] is False
    assert rt.start_material_messages(object()) == reason  # nothing is installed
    assert rt.material_messages_state() == {**rt.material_messages_state(), "active": False, "reason": reason}


class _Renderer:
    """An owner of the material messages, as a renderer adapter is."""


def test_a_freed_renderer_does_not_keep_the_material_callback_installed(monkeypatch):
    """Review: the owners were kept by id, so a renderer that was dropped without a shutdown kept the callback
    installed after the last live renderer stopped (and another object could take its id)."""

    removed = []
    monkeypatch.setitem(rt._STATE, "owners", type(rt._STATE["owners"])())
    monkeypatch.setitem(rt._STATE, "installed", True)
    monkeypatch.setitem(rt._STATE, "library", lambda *args: removed.append(args))
    monkeypatch.setitem(rt._STATE, "reason", rt._STATE["reason"])
    live, dropped = _Renderer(), _Renderer()
    assert rt.start_material_messages(live) == "" and rt.start_material_messages(dropped) == ""
    del dropped
    rt.stop_material_messages(live)
    assert len(removed) == 1 and rt._STATE["installed"] is False


def test_the_capability_list_follows_the_routes_that_are_active(monkeypatch):
    monkeypatch.setitem(rt._STATE, "installed", False)
    monkeypatch.setitem(rt._STATE, "reason", "this ovrtx has no ovrtx_logging.h, so it has no public log callback")
    reports = rt.renderer_reports()
    assert any("ovrtx_logging.h" in item for item in reports["not_reported"])
    assert any("resident" in item for item in reports["not_reported"])
    monkeypatch.setitem(rt._STATE, "installed", True)
    reports = rt.renderer_reports()
    assert any("module that the renderer generated code from" in item for item in reports["reported"])
    assert any("connected to more than one output" in item for item in reports["not_reported"])


@pytest.mark.requires_ovrtx
@pytest.mark.own_process
def test_real_renderer_names_the_module_of_each_material_or_says_why_not(tmp_path, monkeypatch):
    """With an ovrtx whose headers declare the callback, the renderer names the module of the MaterialX and the
    native MDL material of the regression scene; with another ovrtx the route is off and says why."""

    import ovrtx
    from pxr import Gf, Sdf, Usd, UsdRender

    monkeypatch.setattr(rt, "_MESSAGES", rt.MaterialMessages())
    subprocess.run([sys.executable, str(GENERATOR), str(tmp_path)], check=True, capture_output=True)
    stage = Usd.Stage.Open(str(tmp_path / "kitchen.usda"))
    product = UsdRender.Product.Define(stage, "/Render/Camera")
    product.GetCameraRel().SetTargets([Sdf.Path("/World/Cameras/Review_Ref")])
    product.GetResolutionAttr().Set(Gf.Vec2i(320, 180))
    var = UsdRender.Var.Define(stage, "/Render/Camera/LdrColor")
    var.GetSourceNameAttr().Set("LdrColor")
    product.GetOrderedVarsRel().SetTargets([var.GetPath()])
    scene = str(tmp_path / "kitchen_product.usda")
    stage.GetRootLayer().Export(scene)

    monkeypatch.setenv(rt.MESSAGES_ENV, "1")
    supported, why = rt.log_callback_support(ovrtx)
    assert rt.prepare_material_messages() == ("" if supported else why)
    renderer = ovrtx.Renderer(ovrtx.RendererConfig(log_file_path=str(tmp_path / "ovrtx.log")))
    owner = object()
    try:
        rt.start_material_messages(owner)
        renderer.open_usd(scene)
        for _ in range(4):
            renderer.step(render_products={"/Render/Camera"}, delta_time=1 / 60)
        rt.note_renderer_diagnostics(rt.native_renderer_handle(renderer), now=1e12)
        state = rt.material_messages_state()
        if supported:
            assert state["active"] is True and state["callback_errors"] == 0
            whitewash, runner = rt.get_material_messages().for_shaders([
                "/World/Kitchen/W1_Looks/PeruSurfaceV1/Whitewash/OpenPBR",
                "/World/Kitchen/W1_Looks/PeruReviewV2/CrimsonRunner/mdl",
            ])
            assert whitewash["kind"] == "generated_module" and whitewash["module"].startswith("omni_mtlx_")
            assert runner["kind"] == "mdl_module" and os.path.basename(runner["module"]) == "peru_runner_diamond_v1.mdl"
        else:
            assert state["active"] is False and state["reason"] == why
        # The loaded library was built with the API version of the package's headers; headers of another major
        # version do not describe it.
        library = ovrtx._src.bindings._ovrtx_loader._lib
        assert rt.api_version_mismatch(ovrtx, library) == ""
        headers = (pathlib.Path(ovrtx.__file__).parent / "include" / "ovrtx" / "ovrtx_types.h").read_text()
        major = int(re.search(r"#define\s+OVRTX_VERSION_MAJOR\s+(\d+)", headers).group(1))
        other = tmp_path / "other" / "ovrtx"
        (other / "include" / "ovrtx").mkdir(parents=True)
        (other / "include" / "ovrtx" / "ovrtx_types.h").write_text(
            re.sub(r"(#define\s+OVRTX_VERSION_MAJOR\s+)\d+", rf"\g<1>{major + 1}", headers))
        reason = rt.api_version_mismatch(SimpleNamespace(__file__=str(other / "x.py")), library)
        assert f"the headers of the ovrtx package describe {major + 1}." in reason
        # The diagnostics table is in a native file of the loaded renderer, and the totals are read exactly when
        # that file is identified as the build of an installed client contract.
        address, why_not = rt.diagnostics_table_address()
        assert address, why_not
        holder, why_not = rt.loaded_library_file(address)
        assert holder is not None, why_not
        assert pathlib.Path(library._name).resolve().parent in holder.resolve().parents
        known, reason = rt.diagnostics_contract(ovrtx, address)
        diagnostics = rt.last_renderer_diagnostics()
        assert diagnostics["available"] is known
        assert (diagnostics["contract"] if known else diagnostics["reason"]) == reason
        if known:
            assert diagnostics["renderer_device_memory_bytes"] > 0
            assert diagnostics["texture_streaming"]["memory_budget_bytes"] > 0
        else:
            # Where the gate looks for client contracts: next to the loaded package, then the import path.
            loaded = rt._ovrtx_package()[0]
            folders = [str(pathlib.Path(loaded.__file__).resolve().parent.parent), *sys.path]
            clients = [item for item in importlib.metadata.distributions(path=folders)
                       if item.metadata["Name"] == "ovrtx-extensions"]
            assert "no client contract" in reason if not clients else "the table is not read" in reason
    finally:
        rt.stop_material_messages(owner)
        renderer.destroy()
    assert rt.material_messages_state()["active"] is False
