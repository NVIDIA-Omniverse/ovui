# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""What the renderer itself reports about materials and texture memory, through the routes that ovrtx supports.

Two routes, both optional. Each is used only when the LOADED renderer has it (``OVRTX_ROOT`` can select the copy);
otherwise the report says why:

* **Material messages** (:class:`MaterialMessages`). A renderer whose public headers declare
  ``ovrtx_set_log_callback`` in ``<ovrtx/ovrtx_logging.h>`` gives every log message to a public callback, with a
  channel filter. With the materials channel at ``verbose`` (``--/log/channels/omni.rtx.materials=verbose``,
  published through the settings extension that the shader-compile limit also uses), the renderer names, for each
  material shader prim, the MDL module that it generated code from. The two forms (``<...>`` are placeholders)::

      Generation of <resolved module>.mdl/<shader prim path> took <seconds> sec
      Stored MdlEntitySnapshot to DB: usd::<scope>::<shader prim path>::::<generated module>::<entity>((<n>))

  The first form is native MDL (the module path is the file that the renderer resolved), the second is a
  MaterialX material (the module is the one that the renderer generated from the graph). These are what
  the renderer did, not what USD authors. They are not proof that the compile succeeded or that a texture
  is resident: a failure is reported by its own error line (``render_native_log``). The log file keeps its
  level. A renderer without this callback, or with another message layout, does not have this route. The
  layout comes from the headers of the loaded ovrtx package; the callback is installed only when the loaded
  library reports the same API version as those headers (:func:`api_version_mismatch`), and each message is read
  only when its own size field says that it has every field that is read. The route is off unless ``OVUI_RENDERER_MATERIAL_MESSAGES=1`` (:data:`MESSAGES_ENV`): every verbose message of
  the channel then goes through a Python callback while a scene loads.

* **Renderer diagnostics** (:func:`read_renderer_diagnostics`). The internal extension
  ``ovrtx.renderer.diagnostics`` gives the texture-streaming memory use and budget, and the device memory of
  this process (also on a MIG partition). These are totals for the renderer, never per texture. Its table has
  no version or size field, and an older renderer has a shorter table under the same name, so no layout is
  assumed. The layout comes only from a client contract (an ``ovrtx-extensions`` package, for NVIDIA teams)
  that is proved to describe the native code that holds the table: that code's file, found from the address
  of the table, must have the SHA-256 that the installed record of the contract's own ``ovrtx`` build lists
  (:func:`diagnostics_contract`). A Python package, a version number or a list of builds never stands for the
  loaded code. Otherwise the table is not read, and the report says why.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import importlib.metadata
import os
import re
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

from ovui_data_adapters.common.render_diagnostics import LOGGER, WeakOwners

#: The materials channel of the renderer, and the setting that makes it verbose.
MATERIALS_CHANNEL = "omni.rtx.materials"
MATERIALS_VERBOSE_SETTING = f"--/log/channels/{MATERIALS_CHANNEL}=verbose"
#: Set to 1 to read the material messages (off by default: the renderer then sends every verbose message of
#: the materials channel to Python while a scene loads; on the Factory scene, 11,160 materials, about 94,000
#: messages made the first frame 31.2 s instead of 27.9 s).
MESSAGES_ENV = "OVUI_RENDERER_MATERIAL_MESSAGES"

#: Fields of ``ovx_log_message_t`` in ``<ovx/logging_types.h>``, in order. A header with other fields has
#: another layout, and the callback is not installed.
_MESSAGE_FIELDS = (
    "thisSize", "severity", "libraryName", "channel", "timestampNs", "elapsedTimeNs", "filePath",
    "lineNumber", "functionName", "processId", "threadId", "sequenceNumber", "message",
)
_OVX_LOG_VERBOSE = -2
_OVX_LOG_FATAL = 2

#: Shader prims kept (one entry each). A scene with more keeps the newest; the report says how many fell out.
_MAX_SHADERS = 200_000

_GENERATION = re.compile(r"^Generation of (?P<module>.+?\.mdl)/(?P<rest>.+?) took \S+ sec")
_STORED = re.compile(
    r"^Stored MdlEntitySnapshot to DB: usd::[^:]+::(?P<shader>/[^:]+)::::(?P<entity>.+?)(?:\(\(\d+\)\))?\s*$"
)


class MaterialMessages:
    """The material messages that the renderer gave, kept by shader prim path. Thread safe."""

    def __init__(self, limit: int = _MAX_SHADERS) -> None:
        self._limit = limit
        self._by_shader: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self._dropped = 0
        self._lock = threading.Lock()

    def take(self, text: str) -> bool:
        """Keep one renderer message when it names a shader prim and its module. Returns True when kept."""

        entry = None
        match = _GENERATION.match(text)
        if match:
            rest = match["rest"]
            # Native MDL: "<module.mdl>//World/..." (the rest is the prim path). MaterialX:
            # "<hash>/materialx.mdl/usd::<scope>::/World/...::::<module>::<entity>((n))".
            if rest.startswith("/"):
                entry = {"shader": rest, "module": match["module"], "kind": "mdl_module", "message": text.strip()}
            else:
                stored = re.match(r"usd::[^:]+::(?P<shader>/[^:]+)::::(?P<entity>.+?)(?:\(\(\d+\)\))?$", rest)
                if stored:
                    module, _, name = stored["entity"].rpartition("::")
                    entry = {"shader": stored["shader"], "module": module, "entity": name,
                             "kind": "generated_module", "message": text.strip()}
        else:
            match = _STORED.match(text)
            if match:
                module, _, name = match["entity"].rpartition("::")
                entry = {"shader": match["shader"], "module": module, "entity": name,
                         "kind": "generated_module", "message": text.strip()}
        if entry is None:
            return False
        with self._lock:
            self._by_shader.pop(entry["shader"], None)
            self._by_shader[entry["shader"]] = entry
            while len(self._by_shader) > self._limit:
                self._by_shader.popitem(last=False)
                self._dropped += 1
        return True

    def for_shaders(self, paths: list[str]) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(self._by_shader[path]) for path in paths if path in self._by_shader]

    def count(self) -> int:
        with self._lock:
            return len(self._by_shader)

    def dropped(self) -> int:
        with self._lock:
            return self._dropped

    def clear(self) -> None:
        with self._lock:
            self._by_shader.clear()
            self._dropped = 0


_MESSAGES = MaterialMessages()


def get_material_messages() -> MaterialMessages:
    return _MESSAGES


# --------------------------------------------------------------------------
# The public log callback of the renderer
# --------------------------------------------------------------------------


def _ovrtx_package() -> tuple[Any, Any, str]:
    """(ovrtx module, its ctypes bindings module, "") or (None, None, reason)."""

    from ovui_data_adapters.common.ovrtx_import import import_ovrtx

    imported = import_ovrtx()
    if imported.module is None:
        return None, None, f"ovrtx is not available ({imported.error})"
    # The ctypes bindings of the loaded copy (``import ovrtx`` loads them): nothing else is imported.
    bindings = getattr(getattr(imported.module, "_src", None), "bindings", None)
    if bindings is None:
        return None, None, "the loaded ovrtx has no ctypes bindings (ovrtx._src.bindings)"
    return imported.module, bindings, ""


def _header_fields(text: str, struct: str) -> list[str]:
    """The field names of ``typedef struct <struct> { ... } <struct>;`` in a C header, in order."""

    match = re.search(r"typedef\s+struct\s+" + re.escape(struct) + r"\s*\{(?P<body>.*?)\}\s*" + re.escape(struct) + r"\s*;",
                      text, re.DOTALL)
    if not match:
        return []
    body = re.sub(r"/\*.*?\*/", "", match["body"], flags=re.DOTALL)
    body = re.sub(r"//[^\n]*", "", body)
    return [m.group(1) for m in re.finditer(r"(\w+)\s*(?:\[[^\]]*\])?\s*;", body)]


def log_callback_support(module: Any) -> tuple[bool, str]:
    """Whether the installed ovrtx declares the log callback with the message layout that this module reads.

    ``ovrtx/ovrtx_logging.h`` must declare ``ovrtx_set_log_callback`` and ``ovx/logging_types.h`` must give
    ``ovx_log_message_t`` exactly the fields of :data:`_MESSAGE_FIELDS`. A renderer with another callback type is
    not supported. These are the headers of the package; :func:`start_material_messages` also checks that the
    loaded library has their API version.
    """

    include = os.path.join(os.path.dirname(os.path.abspath(module.__file__)), "include")
    logging_h = os.path.join(include, "ovrtx", "ovrtx_logging.h")
    types_h = os.path.join(include, "ovx", "logging_types.h")
    try:
        with open(logging_h, encoding="utf-8") as handle:
            declares = "ovrtx_set_log_callback" in handle.read()
        with open(types_h, encoding="utf-8") as handle:
            fields = _header_fields(handle.read(), "ovx_log_message_t")
    except OSError as exc:
        return False, f"this ovrtx has no {os.path.basename(exc.filename or logging_h)}, so it has no public log callback"
    if not declares:
        return False, "ovrtx_logging.h does not declare ovrtx_set_log_callback"
    if tuple(fields) != _MESSAGE_FIELDS:
        return False, f"ovx_log_message_t has other fields than the ones this module reads: {fields}"
    return True, ""


def api_version_mismatch(module: Any, library: Any) -> str:
    """"" when the loaded renderer library was built with the API version of the headers in the ovrtx package.

    Otherwise the reason. The version comes from the loaded library (``ovrtx_get_version``, which the renderer
    documents for this check) and from ``OVRTX_VERSION_MAJOR``, ``_MINOR`` and ``_PATCH`` of ``ovrtx_types.h``.
    """

    path = os.path.join(os.path.dirname(os.path.abspath(module.__file__)), "include", "ovrtx", "ovrtx_types.h")
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        return f"the ovrtx package has no ovrtx_types.h, so the API version of its headers is not known ({exc})"
    parts = [re.search(rf"#define\s+OVRTX_VERSION_{part}\s+(\d+)", text) for part in ("MAJOR", "MINOR", "PATCH")]
    if not all(parts):
        return "ovrtx_types.h does not define the API version of the headers"
    headers = tuple(int(match.group(1)) for match in parts)
    get_version = _function(library, "ovrtx_get_version", None, *([ctypes.POINTER(ctypes.c_uint32)] * 3))
    values = [ctypes.c_uint32() for _ in range(3)]
    get_version(*(ctypes.byref(value) for value in values))
    loaded = tuple(value.value for value in values)
    if loaded != headers:
        return (f"the loaded renderer library has API version {'.'.join(map(str, loaded))}, but the headers of the "
                f"ovrtx package describe {'.'.join(map(str, headers))}")
    return ""


def _function(lib: Any, name: str, restype: Any, *argtypes: Any) -> Any:
    """A private prototype of one library function: the shared ``lib.<name>`` attributes are not changed."""

    return ctypes.CFUNCTYPE(restype, *argtypes)((name, lib))


class _OvxString(ctypes.Structure):
    _fields_ = [("ptr", ctypes.c_void_p), ("length", ctypes.c_size_t)]


class _OvxLogMessage(ctypes.Structure):
    _fields_ = [
        ("thisSize", ctypes.c_size_t), ("severity", ctypes.c_int), ("libraryName", _OvxString),
        ("channel", _OvxString), ("timestampNs", ctypes.c_uint64), ("elapsedTimeNs", ctypes.c_uint64),
        ("filePath", _OvxString), ("lineNumber", ctypes.c_uint32), ("functionName", _OvxString),
        ("processId", ctypes.c_uint32), ("threadId", ctypes.c_uint32), ("sequenceNumber", ctypes.c_uint64),
        ("message", _OvxString),
    ]


_CALLBACK_TYPE = ctypes.CFUNCTYPE(None, ctypes.POINTER(_OvxLogMessage), ctypes.c_void_p)
_PREFIXES = (b"Generation of ", b"Stored MdlEntitySnapshot")


def _on_message(message: Any, _user: Any) -> None:
    try:
        # Each message gives its own size; a smaller one has another layout and is not read further.
        if message.contents.thisSize < ctypes.sizeof(_OvxLogMessage):
            _STATE["callback_errors"] += 1
            return
        item = message.contents
        if item.severity != _OVX_LOG_VERBOSE or not item.message.ptr or not item.message.length:
            return
        raw = ctypes.string_at(item.message.ptr, item.message.length)
        if raw.startswith(_PREFIXES):
            _MESSAGES.take(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - an exception must not reach the native caller; it is counted
        _STATE["callback_errors"] += 1


#: Kept for the life of the process: the renderer may call it until the system shuts down.
_CALLBACK = _CALLBACK_TYPE(_on_message)
_STATE: dict[str, Any] = {"owners": WeakOwners(), "installed": False, "library": None, "reason": "not started",
                          "callback_errors": 0, "prepared": False}
_STATE_LOCK = threading.Lock()


def _messages_wanted() -> bool:
    return os.environ.get(MESSAGES_ENV, "").strip().lower() in ("1", "on", "true")


def prepare_material_messages() -> str:
    """Before a renderer is created: make the materials channel verbose when the callback route is supported.

    Returns "" when prepared, else the reason why the route is not used.
    """

    if not _messages_wanted():
        _STATE["prepared"] = False
        _STATE["reason"] = (
            f"off; set {MESSAGES_ENV}=1 before the renderer starts to read them (a renderer with the public log "
            "callback; it costs time while a scene loads)"
        )
        return _STATE["reason"]
    module, _bindings, reason = _ovrtx_package()
    if module is not None:
        supported, reason = log_callback_support(module)
        if supported:
            from ovui_data_adapters.common.ovrtx_compile_limits import apply_setting_tokens

            reason = apply_setting_tokens([MATERIALS_VERBOSE_SETTING])
    with _STATE_LOCK:
        _STATE["prepared"] = not reason
        _STATE["reason"] = reason or "prepared; the callback starts with the renderer"
    if reason:
        LOGGER.info("renderer material messages are not used: %s", reason)
    return reason


def start_material_messages(owner: object) -> str:
    """After a renderer is created: install the callback (once per process). Returns "" or the reason."""

    with _STATE_LOCK:
        if _STATE["installed"]:
            _STATE["owners"].add(owner)
            return ""
        if not _STATE["prepared"]:
            return _STATE["reason"]
        module, bindings, reason = _ovrtx_package()
        if bindings is None:
            _STATE["reason"] = reason
            return reason
        try:
            # The callback and its messages have the layout of the headers in the ovrtx package. The loaded library
            # says which API version it was built with: install the callback only when it is the headers' version.
            reason = api_version_mismatch(module, bindings._ovrtx_loader._lib)
            if reason:
                _STATE["reason"] = reason
                LOGGER.warning("renderer material messages are not read: %s", reason)
                return reason
            set_callback = _function(bindings._ovrtx_loader._lib, "ovrtx_set_log_callback", bindings.ovrtx_result_t,
                                     ctypes.c_int, ctypes.POINTER(_OvxString), _CALLBACK_TYPE, ctypes.c_void_p)
            text = f"{MATERIALS_CHANNEL}=verbose".encode()
            buffer = ctypes.create_string_buffer(text)
            channel_filter = _OvxString(ctypes.cast(buffer, ctypes.c_void_p), len(text))
            # Only the materials channel is delivered (every level); other channels only when fatal.
            result = set_callback(_OVX_LOG_FATAL, ctypes.byref(channel_filter), _CALLBACK, None)
            if result.status != bindings.OVRTX_API_SUCCESS:
                _STATE["reason"] = f"ovrtx_set_log_callback returned {result.status!r}"
                LOGGER.warning("renderer material messages are not read: %s", _STATE["reason"])
                return _STATE["reason"]
        except Exception as exc:  # noqa: BLE001 - the route is optional; the reason is reported
            _STATE["reason"] = f"{type(exc).__name__}: {exc}"
            LOGGER.warning("renderer material messages are not read: %s", _STATE["reason"])
            return _STATE["reason"]
        _STATE.update(installed=True, library=set_callback, reason="")
        _STATE["owners"].add(owner)
        LOGGER.info("renderer material messages: the public log callback reads channel %s", MATERIALS_CHANNEL)
        return ""


def stop_material_messages(owner: object) -> None:
    """Remove one owner. The last one removes the callback while the renderer system still runs.

    Owners are held by weak reference: an owner that was freed without this call does not count, so it cannot keep
    the callback installed after the last live owner stops.
    """

    with _STATE_LOCK:
        _STATE["owners"].discard(owner)
        if len(_STATE["owners"]) or not _STATE["installed"]:
            return
        set_callback = _STATE["library"]
        try:
            set_callback(_OVX_LOG_FATAL, None, _CALLBACK_TYPE(), None)
        except Exception as exc:  # noqa: BLE001 - _CALLBACK stays alive, so a late call is still safe
            LOGGER.warning("the renderer log callback was not removed (%s: %s); it stays valid", type(exc).__name__, exc)
        _STATE.update(installed=False, library=None, reason="stopped")


def material_messages_state() -> dict[str, Any]:
    with _STATE_LOCK:
        return {"active": _STATE["installed"], "reason": _STATE["reason"], "shaders": _MESSAGES.count(),
                "shaders_dropped": _MESSAGES.dropped(), "callback_errors": _STATE["callback_errors"]}


# --------------------------------------------------------------------------
# The renderer diagnostics extension (the contract of the loaded renderer)
# --------------------------------------------------------------------------

DIAGNOSTICS_EXTENSION = b"ovrtx.renderer.diagnostics"
#: The header of the client contract that declares the table, in the files of an ``ovrtx-extensions`` package.
DIAGNOSTICS_HEADER = "ovrtx_extensions/include/ovrtx/internal/ovrtx_diagnostics.h"
#: The entries of ``ovrtx_extension_renderer_diagnostics_t``, in order, of the contract that this module reads.
DIAGNOSTICS_ENTRIES = (
    "get_motion_bvh_active", "get_view_tile_cache_stats", "get_texture_streaming_shared_mip_cache_stats",
    "get_texture_streaming_residency_stats", "set_texture_streaming_memory_budget_override",
    "set_texture_streaming_requested_mip_for_testing", "rebuild_texture_streaming_memory_buckets_for_testing",
    "get_device_memory_usage",
)
#: Seconds between two reads after a step.
DIAGNOSTICS_INTERVAL = 1.0


class _Residency(ctypes.Structure):
    _fields_ = [("memory_usage", ctypes.c_uint64), ("memory_budget", ctypes.c_uint64),
                ("test_memory_budget_override", ctypes.c_uint64), ("memory_buckets_kib", ctypes.c_uint32 * 16)]


def loaded_library_file(address: int) -> tuple[Optional[Path], str]:
    """The file of the loaded native library whose memory holds ``address``: (path, "") or (None, reason).

    Linux: the mapping of this process that holds the address (``/proc/self/maps``). The file at its path must
    still be the mapped file (the same device and inode); a file that was replaced after the load does not stand
    for the loaded code. Windows: the module that holds the address. Elsewhere it is not known.
    """

    if not address:
        return None, "no address"
    if sys.platform.startswith("linux"):
        return _mapped_file_linux(address)
    if sys.platform == "win32":
        return _module_file_windows(address)
    return None, f"this system ({sys.platform}) has no supported way to find the file of loaded code"


def _mapped_file_linux(address: int) -> tuple[Optional[Path], str]:
    try:
        with open("/proc/self/maps", encoding="utf-8", errors="replace") as maps:
            lines = maps.readlines()
    except OSError as exc:
        return None, f"/proc/self/maps cannot be read ({exc})"
    for line in lines:
        fields = line.split(maxsplit=5)
        if len(fields) < 6:
            continue
        low, high = (int(value, 16) for value in fields[0].split("-"))
        if not low <= address < high:
            continue
        name = fields[5].rstrip("\n")
        if not name.startswith("/") or name.endswith(" (deleted)"):
            return None, f"the address is not in a library file of this process ({name or 'anonymous memory'})"
        major, minor = (int(value, 16) for value in fields[3].split(":"))
        try:
            info = os.stat(name)
        except OSError as exc:
            return None, f"the mapped file {name} cannot be read ({exc})"
        if (info.st_ino, os.major(info.st_dev), os.minor(info.st_dev)) != (int(fields[4]), major, minor):
            return None, f"{name} is not the file that this process loaded (it was replaced after the load)"
        return Path(name), ""
    return None, "no mapping of this process holds the address"


def _module_file_windows(address: int) -> tuple[Optional[Path], str]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_module = kernel32.GetModuleHandleExW
    get_module.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    get_module.restype = ctypes.c_int
    get_name = kernel32.GetModuleFileNameW
    get_name.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
    get_name.restype = ctypes.c_uint32
    module = ctypes.c_void_p()
    # GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT
    if not get_module(0x4 | 0x2, ctypes.c_void_p(address), ctypes.byref(module)):
        return None, f"no module of this process holds the address (error {ctypes.get_last_error()})"
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_name(module, buffer, len(buffer))
    if not length or length >= len(buffer):
        return None, f"the file name of the module cannot be read (error {ctypes.get_last_error()})"
    return Path(buffer.value), ""


def _record_digest(data: bytes) -> str:
    """A SHA-256 in the form that an installed record (``RECORD``) writes it."""

    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")


def _distributions(name: str, folders: list[str]) -> list[importlib.metadata.Distribution]:
    """The installed distributions called ``name`` in ``folders``, each folder once, in the order of the folders."""

    found: list[importlib.metadata.Distribution] = []
    seen: set[tuple[str, str]] = set()
    for distribution in importlib.metadata.distributions(path=folders):
        if re.sub(r"[-_.]+", "-", (distribution.metadata["Name"] or "")).lower() != name:
            continue
        key = (os.path.abspath(str(distribution.locate_file(""))), distribution.version)
        if key not in seen:
            seen.add(key)
            found.append(distribution)
    return found


def _recorded_with_digest(distribution: importlib.metadata.Distribution, file_name: str, digest: str) -> bool:
    """Whether the installed record of ``distribution`` lists a file called ``file_name`` with this SHA-256."""

    return any(
        item.name == file_name and item.hash is not None and item.hash.mode == "sha256" and item.hash.value == digest
        for item in distribution.files or []
    )


def _pinned_build(client: importlib.metadata.Distribution) -> str:
    """The exact ``ovrtx`` build that a client contract belongs to (its ``ovrtx==<build>`` requirement), or ""."""

    for requirement in client.requires or []:
        match = re.fullmatch(r"\s*ovrtx\s*===?\s*([^\s;,]+)\s*(?:;.*)?", requirement)
        if match:
            return match.group(1)
    return ""


def _contract_for_library(module: Any, library: Path) -> tuple[bool, str]:
    """Steps 2 to 4 of :func:`diagnostics_contract` for the loaded library file."""

    folders = [str(Path(os.path.abspath(module.__file__)).parent.parent)] if getattr(module, "__file__", None) else []
    folders += [folder for folder in sys.path if folder and folder not in folders]
    clients = _distributions("ovrtx-extensions", folders)
    if not clients:
        return False, (f"no client contract (an ovrtx-extensions package) is installed, so the layout of the table "
                       f"in the loaded {library.name} is not known; the table is not read")
    try:
        digest = _record_digest(library.read_bytes())
    except OSError as exc:
        return False, f"the loaded {library} cannot be read to identify it ({exc}); the table is not read"
    reasons = []
    for client in clients:
        build = _pinned_build(client)
        if not build:
            reasons.append(f"ovrtx-extensions {client.version} does not name the exact ovrtx build that it belongs to")
            continue
        header = Path(str(client.locate_file(DIAGNOSTICS_HEADER)))
        try:
            text = header.read_bytes()
        except OSError:
            reasons.append(f"ovrtx-extensions {client.version} has no {DIAGNOSTICS_HEADER}")
            continue
        if not _recorded_with_digest(client, header.name, _record_digest(text)):
            reasons.append(f"{header} is not the file that the record of ovrtx-extensions {client.version} lists")
            continue
        renderers = [item for item in _distributions("ovrtx", folders) if item.version == build]
        if not any(_recorded_with_digest(item, library.name, digest) for item in renderers):
            why = "its SHA-256 differs from the installed record" if renderers else "that build is not installed"
            reasons.append(f"the loaded {library} is not a file of ovrtx {build}, the build of the installed "
                           f"ovrtx-extensions {client.version} ({why})")
            continue
        entries = tuple(re.findall(r"\(\*(\w+)\)\s*\(", text.decode("utf-8", errors="replace")))
        if entries != DIAGNOSTICS_ENTRIES:
            return False, (f"the table of the loaded ovrtx {build} has other entries ({len(entries)}: "
                           f"{', '.join(entries)}; from ovrtx-extensions {client.version}); the table is not read")
        return True, (f"the loaded {library.name} is a file of ovrtx {build} (the same SHA-256 as in its installed "
                      f"record), and ovrtx-extensions {client.version}, the client contract of that build, lists "
                      "the entries that are read")
    return False, "; ".join(reasons) + "; the table is not read"


_CONTRACTS: dict[int, tuple[bool, str]] = {}
_CONTRACTS_LOCK = threading.Lock()


def diagnostics_contract(module: Any, table_address: int) -> tuple[bool, str]:
    """Whether the diagnostics table at ``table_address`` has the layout that this module reads: (bool, why).

    The table has no version or size field, and one extension name has had tables of other lengths. So its layout
    is taken only from a client contract (an ``ovrtx-extensions`` package, for NVIDIA teams) that is proved to
    describe the native code that holds the table, never from a version number or a list of builds:

    1. the file of the loaded native library whose memory holds the table (:func:`loaded_library_file`);
    2. an installed client contract whose header is the file that its own record lists, and which names the exact
       ``ovrtx`` build that it belongs to (its ``ovrtx==<build>`` requirement);
    3. the installed record of that ``ovrtx`` build lists a file of the same name with the same SHA-256 as the
       loaded library: the loaded code is the code of that build;
    4. the header declares exactly the entries of :data:`DIAGNOSTICS_ENTRIES`, in that order.

    When a step fails, the table is not read and the reason says which step failed. The answer is kept for the
    table (one file read and hash for each process).
    """

    with _CONTRACTS_LOCK:
        known = _CONTRACTS.get(table_address)
    if known is not None:
        return known
    library, why = loaded_library_file(table_address)
    if library is None:
        answer = (False, f"the native library that holds the diagnostics table is not known ({why}); it is not read")
    else:
        answer = _contract_for_library(module, library)
    with _CONTRACTS_LOCK:
        _CONTRACTS[table_address] = answer
    return answer


_DIAGNOSTICS: dict[str, Any] = {"available": False, "reason": "no renderer step yet", "time": 0.0}
_DIAGNOSTICS_LOCK = threading.Lock()


def native_renderer_handle(renderer: Any) -> Any:
    """The native handle of an ovrtx renderer, or None. Take it when the renderer gets a scene, not at each frame.

    The ctypes wrapper has no public accessor for it. A frame then reads the totals with the kept handle and looks
    up nothing on the renderer.
    """

    return getattr(renderer, "_handle", None)


def diagnostics_table_address() -> tuple[int, str]:
    """The address of the diagnostics table that the loaded renderer gives: (address, "") or (0, reason).

    ``ovrtx_query_extension`` is a public function of the renderer; nothing in the table is called here.
    """

    _module, bindings, reason = _ovrtx_package()
    if bindings is None:
        return 0, reason
    query = _function(bindings._ovrtx_loader._lib, "ovrtx_query_extension", bindings.ovrtx_result_t,
                      ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))
    table = ctypes.c_void_p()
    result = query(DIAGNOSTICS_EXTENSION, ctypes.byref(table))
    if result.status != bindings.OVRTX_API_SUCCESS or not table.value:
        return 0, f"ovrtx_query_extension({DIAGNOSTICS_EXTENSION.decode()}) failed"
    return table.value, ""


def read_renderer_diagnostics(handle: Any) -> dict[str, Any]:
    """Read the totals of the renderer diagnostics extension with a native renderer handle. Never raises."""

    if handle is None:
        return {"available": False, "reason": "the renderer has no native handle"}
    module, bindings, reason = _ovrtx_package()
    if module is None:
        return {"available": False, "reason": reason}
    try:
        table, why = diagnostics_table_address()
        if not table:
            return {"available": False, "reason": why}
        known, why = diagnostics_contract(module, table)
        if not known:
            return {"available": False, "reason": why}
        slots = ctypes.cast(table, ctypes.POINTER(ctypes.c_void_p * len(DIAGNOSTICS_ENTRIES))).contents
        result_type = bindings.ovrtx_result_t
        residency_fn = ctypes.CFUNCTYPE(result_type, ctypes.c_void_p, ctypes.POINTER(_Residency))(
            slots[DIAGNOSTICS_ENTRIES.index("get_texture_streaming_residency_stats")])
        memory_fn = ctypes.CFUNCTYPE(result_type, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64))(
            slots[DIAGNOSTICS_ENTRIES.index("get_device_memory_usage")])
        address = ctypes.cast(handle, ctypes.c_void_p).value
        residency, memory = _Residency(), ctypes.c_uint64()
        out: dict[str, Any] = {"available": True, "contract": why, "scope": "the whole renderer, not one texture"}
        if residency_fn(address, ctypes.byref(residency)).status == bindings.OVRTX_API_SUCCESS:
            out["texture_streaming"] = {"memory_usage_bytes": int(residency.memory_usage),
                                        "memory_budget_bytes": int(residency.memory_budget)}
        else:
            out["texture_streaming"] = None
        if memory_fn(address, ctypes.byref(memory)).status == bindings.OVRTX_API_SUCCESS:
            out["renderer_device_memory_bytes"] = int(memory.value)
        else:
            out["renderer_device_memory_bytes"] = None
        return out
    except Exception as exc:  # noqa: BLE001 - optional route; the reason is reported
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def note_renderer_diagnostics(handle: Any, now: Optional[float] = None) -> None:
    """After a step: read the totals with the kept native handle, at most once each :data:`DIAGNOSTICS_INTERVAL` seconds.

    Without a handle nothing is read (the totals keep their reason).
    """

    if handle is None:
        return
    now = time.monotonic() if now is None else now
    with _DIAGNOSTICS_LOCK:
        if now - _DIAGNOSTICS["time"] < DIAGNOSTICS_INTERVAL and _DIAGNOSTICS["reason"] != "no renderer step yet":
            return
    values = read_renderer_diagnostics(handle)
    values["time"] = now
    values["read_at"] = time.time()
    with _DIAGNOSTICS_LOCK:
        _DIAGNOSTICS.clear()
        _DIAGNOSTICS.update(values)
        _DIAGNOSTICS.setdefault("reason", "")


def last_renderer_diagnostics() -> dict[str, Any]:
    with _DIAGNOSTICS_LOCK:
        return {k: v for k, v in _DIAGNOSTICS.items() if k != "time"}


def renderer_reports() -> dict[str, Any]:
    """What this renderer reports, through which route, and what it does not report (for the material report)."""

    messages = material_messages_state()
    diagnostics = last_renderer_diagnostics()
    reported = ["failures of a texture, MDL module or material, in the native log (every ovrtx version)"]
    not_reported = [
        "whether a texture is resident: no route reports it for one texture",
        "whether the compile of a material succeeded, other than by an error line in the native log",
    ]
    if messages["active"]:
        reported.append(
            "the MDL module that the renderer generated code from for each material shader prim (native MDL: the "
            "resolved module file; MaterialX: the generated module), through the public log callback "
            f"(channel {MATERIALS_CHANNEL} at verbose)"
        )
        reported.append(
            "which output (MDL, MaterialX, universal) was used, when the generated shader prim is connected to "
            "only one output of the material"
        )
        not_reported.append(
            "which output was used when one shader prim is connected to more than one output (the renderer names "
            "the shader prim, not the output)"
        )
    else:
        reported.append(
            "the MaterialX module that the renderer generates, read from the annotation of the generated file, with "
            "the first material of an equal graph as origin (a renderer that names modules by message writes no "
            "annotation)"
        )
        not_reported.append(
            f"the module and the output that each material uses (material messages: {messages['reason']})"
        )
    if diagnostics.get("available"):
        reported.append(
            "texture-streaming memory use and budget, and the device memory of the renderer process, as totals "
            "(renderer diagnostics extension)"
        )
    else:
        not_reported.append(f"texture-streaming memory totals (renderer diagnostics: {diagnostics.get('reason')})")
    reported.append("the final colour of a material (the live material check draws it); this is not residency")
    return {"reported": reported, "not_reported": not_reported, "material_messages": messages,
            "renderer_diagnostics": diagnostics}
