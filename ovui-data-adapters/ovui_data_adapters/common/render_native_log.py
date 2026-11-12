# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The native renderer log and the modules that the renderer generated.

The native renderer reports a material, texture or MDL failure only in its own
log file, and it raises no Python error. It then draws a fallback material.
The forms of such lines (the paths are examples):

* ``[Error] [omni.rtx.materials] [UsdToMdl] Prim '/World/Looks/red/OpenPBR' parameter
  'ND_image_color3__1_file': References an asset that can not be found: './red.png'``
* ``[Error] [omni.rtx] Failed load texture file:/scene/PotatoRed.png. UJITSO request failed``
* ``[Error] [omni.rtx.materials] [MDLC:COMPILER] error: file:/scene/runner.mdl(7,21): C109 ...``

:class:`NativeLogTail` reads new lines of that file and records each failure as an
event. The renderer also writes each compiled MaterialX material as an MDL module in
a directory that its log names; :func:`read_generated_modules` reads them, so the
report can show which compiled module each material uses.
"""

from __future__ import annotations

import atexit
import glob
import logging
import os
import re
import sys
import tempfile
import threading
from typing import Any, Callable, Optional

from ovui_data_adapters.common.render_diagnostics import (
    LOGGER,
    SCENE,
    STOP_TIMEOUT,
    BackgroundTask,
    RenderDiagnostics,
    RenderEvent,
    WeakOwners,
    get_render_diagnostics,
)

_NATIVE_LINE = re.compile(
    r"^\S+ \[[^\]]*\] \[(?P<level>Info|Warning|Error|Fatal|Verbose)\] \[(?P<source>[^\]]*)\] (?P<text>.*)$"
)
_MODULES_DIR = re.compile(r"Registered MDL search path for MaterialX generated modules: file:(?P<dir>.+?)\s*$")
_MISSING_ASSET = re.compile(
    r"Prim '(?P<prim>[^']+)' parameter '(?P<param>[^']*)': (?P<what>[^:]+): '(?P<uri>[^']*)'"
)
#: Words in a renderer message that mark a resource failure.
_FAILURE_WORDS = re.compile(
    r"(fail|error|unable to|cannot|could not|couldn't|out of memory|oom|not found|can not be found|invalid)",
    re.IGNORECASE,
)
_MEMORY_WORDS = re.compile(
    r"(out[ _]of[ _](device[ _]|host[ _])?memory|\boom\b|bad_alloc|cudaErrorMemoryAllocation|memory alloc|failed to allocate|allocation failed|cannot allocate|vkAllocateMemory failed)",
    re.IGNORECASE,
)
_SUBJECT = re.compile(r"(texture|mdl|material|shader|image)", re.IGNORECASE)
#: A USD prim path in a renderer message: in quotes (``Prim '/World/Looks/red/OpenPBR'``) or after the
#: word prim, material, node or shader. A bare path is not taken: it can be a directory or a file.
_PRIM_PATH = re.compile(
    r"""(?:'|\b(?:prim|material|node|shader)s?:?\s+)(/[A-Za-z_]\w*(?:/[A-Za-z_]\w*)*)(?=['\s:,;)]|\.(?!\w)|$)""", re.IGNORECASE
)
_RESOURCE = re.compile(
    r"""['"]?((?:[A-Za-z][A-Za-z0-9+.-]*:/{1,2})?[^\s'"<>()]+\.(?:mdl|usd[azc]?|png|jpe?g|exr|tiff?|tga|bmp|hdr|dds|webp|mtlx))['"]?""",
    re.IGNORECASE,
)
#: Warnings that every healthy run prints; they are not failures.
_BENIGN = re.compile(
    r"(deprecated|ECC is enabled|C183 unused parameter|invalid semantic \d+ in material omniMaterial"
    # printed when the render settings schemas are registered after the first ovstage call: they
    # concern the render settings API, not a material
    r"|FindAppliedAPIPrimDefinition\('\w+'\) returned nothing|Could not find UsdPrimDefinition for '\w+')",
    re.IGNORECASE,
)


#: rtx.mdltranslator writes this while it makes the cache key of a compiled material: the MDL SDK did not find a
#: texture of the material body next to the module that names it, so the key uses the authored path
#: (``MdlSdk::addMaterialBodyResourceHash``). A MaterialX module is generated in a temporary folder and its texture
#: paths are relative to the scene, so the line comes for every texture of such a module when MaterialX
#: deduplication is off. The renderer still loads the texture from the scene. "encoded relative to its root
#: module" means that the file was found and only its path relative to the module was not written.
_BODY_RESOURCE = re.compile(
    r"MDL material \((?P<module>[^()]*)\) bodyResource \((?P<uri>[^()]*)\) could not be "
    r"(?P<state>resolved|encoded relative to its root module); hashing its authored path"
)


def note_body_resource(uri: str, message: str, unresolved: bool,
                       diagnostics: Optional[RenderDiagnostics] = None) -> Optional[RenderEvent]:
    """Decide a cache-key line of the renderer about a texture of a compiled material (see ``_BODY_RESOURCE``).

    A file that was found is not a failure. A file that the MDL SDK did not find is a failure unless the scene
    explains it: every Shader input of the scene with this authored path names a file that is on disk. Until the
    files of the scene are known (:func:`settle_body_resources`), the line is held, not dropped.
    """

    diagnostics = diagnostics or get_render_diagnostics()
    if not unresolved:
        LOGGER.info("not a failure: %s (the file was found)", message)
        return None
    files = diagnostics.hold_until_files(uri, message)
    if files is None:
        return None
    return _decide_body_resource(uri, message, files, diagnostics)


def _decide_body_resource(uri: str, message: str, files: list[dict[str, Any]],
                          diagnostics: RenderDiagnostics) -> Optional[RenderEvent]:
    named = [item for item in files if item["kind"] == "texture" and item["uri"] == uri]
    if named and all(not item["missing"] and item["resolved"] and os.path.isfile(item["resolved"]) for item in named):
        LOGGER.info("not a failure: %s (the scene's texture %s is on disk: %s)", message, uri, named[0]["resolved"])
        return None
    _note_log_failure()
    return diagnostics.record(SCENE, uri, "texture", message)


def settle_body_resources(files: Optional[list[dict[str, Any]]],
                          diagnostics: Optional[RenderDiagnostics] = None) -> int:
    """The files of the scene are known (``shader_files``; None: they cannot be read): decide the held lines.

    Returns the number of failure events recorded. A line that comes later is decided when it is read.
    """

    diagnostics = diagnostics or get_render_diagnostics()
    count = 0
    for uri, message in diagnostics.set_scene_files(files):
        if _decide_body_resource(uri, message, files or [], diagnostics) is not None:
            count += 1
    return count


def _reports_failure(text: str) -> bool:
    return bool(_FAILURE_WORDS.search(text) and (_SUBJECT.search(text) or _MEMORY_WORDS.search(text)))


def ingest_message(text: str, diagnostics: Optional[RenderDiagnostics] = None, context: str = "",
                   force: bool = False, kind: Optional[str] = None, names: bool = True) -> Optional[RenderEvent]:
    """Turn a renderer message into an event when it reports a resource failure.

    The event names the material when the message has a prim path, and the
    resource when the message has a file. When it has neither, the event is
    scene-wide (it is not tied to a material); ``context`` is kept as a hint.
    ``force`` records a message that has no failure words (an error-level line).
    ``kind`` replaces the kind that the words give, except that a memory failure stays ``memory``.
    ``names=False`` keeps the event scene-wide: the text is the adapter's own and its paths (a render
    product) are not materials.
    """

    if not force and not _reports_failure(text):
        return None
    diagnostics = diagnostics or get_render_diagnostics()
    resource = _RESOURCE.search(text) if names else None
    span = resource.span(1) if resource else (0, 0)
    prim = next((m for m in _PRIM_PATH.finditer(text) if not span[0] <= m.start() < span[1]), None) if names else None
    if _MEMORY_WORDS.search(text):
        kind = "memory"
    elif kind:
        pass
    elif re.search(r"texture|image", text, re.IGNORECASE):
        kind = "texture"
    elif re.search(r"mdl", text, re.IGNORECASE):
        kind = "mdl"
    else:
        kind = "compile"
    named = prim.group(1) if prim else SCENE
    return diagnostics.record(
        named, resource.group(1) if resource else "", kind, text.strip(),
        context="" if prim else context,
    )


def record_scene_failure(text: str, kind: str = "step", diagnostics: Optional[RenderDiagnostics] = None,
                         names: bool = True) -> Optional[RenderEvent]:
    """Record a failure of the render step that the renderer shows as a black or missing frame.

    The event names a resource or a prim only when ``text`` has one. Otherwise it is
    scene-wide, with the last material that the renderer log named as a hint.
    """

    return ingest_message(text, diagnostics, last_log_context(), force=True, kind=kind, names=names)


def record_step_failure(error: BaseException, diagnostics: Optional[RenderDiagnostics] = None) -> Optional[RenderEvent]:
    """Record a failed ``Renderer.step``, so that the black frame that follows is not silent."""

    return record_scene_failure(
        f"Renderer.step failed: {type(error).__name__}: {error}",
        "memory" if isinstance(error, MemoryError) else "step", diagnostics,
    )


def parse_native_log_line(
    line: str, diagnostics: Optional[RenderDiagnostics] = None, context: str = ""
) -> Optional[RenderEvent]:
    """Turn one line of the native renderer log into an event, or return None."""

    match = _NATIVE_LINE.match(line.strip())
    if not match:
        return None
    text = match["text"]
    modules = _MODULES_DIR.search(text)
    if modules:
        register_generated_modules_dir(modules["dir"])
        return None
    if match["level"] not in ("Warning", "Error", "Fatal") or _BENIGN.search(text):
        return None
    diagnostics = diagnostics or get_render_diagnostics()
    body = _BODY_RESOURCE.search(text)
    if body:
        return note_body_resource(body["uri"], f"[{match['source']}] {text}", body["state"] == "resolved", diagnostics)
    asset = _MISSING_ASSET.search(text)
    if asset:
        uri = asset["uri"]
        kind = "mdl" if uri.lower().endswith(".mdl") else "texture"
        _note_log_failure()
        return diagnostics.record(asset["prim"], uri, kind, f"{asset['what']}: {uri} ({asset['param']})")
    # An error line is always a failure, even when it names nothing.
    message, force = f"[{match['source']}] {text}", match["level"] != "Warning"
    if force or _reports_failure(message):
        _note_log_failure()
    return ingest_message(message, diagnostics, context, force=force)


#: The log files that :func:`prepare_native_log` named. The renderer library writes to its log file until the
#: process ends, also for a renderer made after the first one is destroyed, so they are removed only then.
_OWN_LOGS: set[str] = set()
#: Added to a log path that could not be removed at the end of its process (the renderer library still had it open).
_REMOVE_LATER = ".remove"
#: The owners of :func:`start_native_log` that :func:`release_native_log` has not released: a renderer that failed to
#: start, or an adapter that was dropped without shutdown.
_UNRELEASED = 0
#: The lines of the native logs that reported a failure: also a line whose event the diagnostics already held, and a
#: held line that the files of the scene decided later.
_LOG_FAILURES = 0
#: For each native log: the end of the last whole line that a reader read. The cleanup reads the rest.
_READ_TO: dict[str, int] = {}


def _note_log_failure() -> None:
    global _LOG_FAILURES
    _LOG_FAILURES += 1


def _read_unread_lines(path: str) -> str:
    """At the end of the process: read the lines of a native log that no reader read, also a last line with no end.

    Returns why they could not be read, or an empty string.
    """

    try:
        if os.path.getsize(path) <= _READ_TO.get(path, 0):
            return ""  # the readers read it all
        with open(path, "rb") as handle:
            handle.seek(_READ_TO.get(path, 0))
            data = handle.read()
    except OSError as exc:
        return f"its last lines could not be read ({exc})"
    for line in data.decode("utf-8", "replace").split("\n"):
        try:
            parse_native_log_line(line)
        except Exception as exc:  # noqa: BLE001 - one bad line must not stop the cleanup; it is reported
            LOGGER.warning("native log line not parsed (%s: %s): %.200s", type(exc).__name__, exc, line)
    return ""


def prepare_native_log(config: Any) -> Optional[str]:
    """Return the native log path of a renderer config; give it one if it has none.

    A config that already names a log file keeps it. Returns None when the
    config has no such field, so the renderer keeps its default log.
    """

    if config is None:
        return None
    path = getattr(config, "log_file_path", None)
    if path:
        return str(path)
    _remove_marked_logs(tempfile.gettempdir())
    path = os.path.join(tempfile.gettempdir(), f"ovui-ovrtx-{os.getpid()}.log")
    try:
        config.log_file_path = path
    except (AttributeError, TypeError) as exc:
        LOGGER.warning("the renderer config has no log_file_path (%s): native failures are not read", exc)
        return None
    if not _OWN_LOGS:
        atexit.register(remove_native_logs)
    _OWN_LOGS.add(path)
    return path


def _remove_marked_logs(directory: str) -> None:
    """Remove the logs that an ended process marked for removal (see :func:`remove_native_logs`)."""

    for marker in glob.glob(os.path.join(glob.escape(directory), f"ovui-ovrtx-*.log{_REMOVE_LATER}")):
        path = marker[:-len(_REMOVE_LATER)]
        try:
            if os.path.exists(path):
                os.remove(path)
            os.remove(marker)
        except OSError as exc:
            LOGGER.info("the native renderer log %s is not removed yet (%s); a later start tries again", path, exc)


def _keep_reason() -> str:
    """Why the native logs are kept at the end of the process: they are the evidence of a failure. Empty: remove them."""

    if getattr(sys, "last_value", None) is not None:
        return "an unhandled exception ends the process"
    if _UNRELEASED:
        return f"{_UNRELEASED} renderer adapter(s) were not shut down (a renderer that failed to start)"
    if _LOG_FAILURES:
        return f"the renderer log reported {_LOG_FAILURES} failure(s)"
    return ""


def remove_native_logs() -> None:
    """At the end of the process: remove the log files that :func:`prepare_native_log` named, or keep the evidence.

    A log is kept, with a warning that names it, when :func:`_keep_reason` gives a reason. A log that cannot be removed
    (on Windows the renderer library still has it open) is marked, and the next :func:`prepare_native_log` removes it.
    """

    unread = {path: _read_unread_lines(path) for path in _OWN_LOGS if os.path.exists(path)}
    # A cache-key line that still waits for the files of the scene is decided as when they cannot be read.
    settle_body_resources(None)
    reason = _keep_reason()
    while _OWN_LOGS:
        path = _OWN_LOGS.pop()
        if not os.path.exists(path):
            continue  # the renderer did not start far enough to write it
        if reason or unread.get(path):
            LOGGER.warning("the native renderer log %s is kept: %s", path, reason or unread[path])
            continue
        try:
            os.remove(path)
        except OSError as exc:
            try:
                open(path + _REMOVE_LATER, "w").close()
            except OSError as mark_exc:
                LOGGER.warning("the native renderer log %s was not removed (%s) and not marked for a later removal: %s",
                               path, exc, mark_exc)
            else:
                LOGGER.info("the native renderer log %s is removed by the next start: %s", path, exc)


class NativeLogTail:
    """Read new lines of the native renderer log in a thread and record failures."""

    def __init__(self, path: str, diagnostics: Optional[RenderDiagnostics] = None, interval: float = 0.5,
                 owned: Optional[Callable[["NativeLogTail"], bool]] = None) -> None:
        """``owned(tail)``, when given, runs in the thread after each read; the thread ends when it returns False."""

        self.path = path
        self._diagnostics = diagnostics
        self._offset = 0
        self._pending = ""
        self._context = ""
        self._lock = threading.Lock()
        self._owned = owned
        self._task = BackgroundTask(f"ovui-native-log-tail:{os.path.basename(path)}", self._step, interval,
                                    final=self.poll)

    def start(self) -> "NativeLogTail":
        self._task.start()
        return self

    def stop(self, timeout: float = STOP_TIMEOUT) -> bool:
        """Stop the thread, then read what the renderer wrote last. Returns True when it stopped."""

        return self._task.stop(timeout)

    def _step(self) -> None:
        self.poll()
        if self._owned is not None and not self._owned(self):
            self._task.finish()

    def poll(self) -> int:
        """Read the lines written since the last call. Returns the number of lines read."""

        with self._lock:
            try:
                with open(self.path, "rb") as handle:
                    handle.seek(self._offset)
                    data = handle.read()
                    self._offset += len(data)
                    if b"\n" in data:
                        end = self._offset - len(data) + data.rindex(b"\n") + 1
                        _READ_TO[self.path] = max(_READ_TO.get(self.path, 0), end)
            except OSError:
                return 0  # the renderer has not created its log yet
            text = self._pending + data.decode("utf-8", "replace")
            *lines, self._pending = text.split("\n")
            for line in lines:
                try:
                    parse_native_log_line(line, self._diagnostics, self._context)
                except Exception as exc:  # noqa: BLE001 - one bad line must not stop the tail; it is reported
                    LOGGER.warning("native log line not parsed (%s: %s): %.200s", type(exc).__name__, exc, line)
                self._note_context(line)
            return len(lines)

    def _note_context(self, line: str) -> None:
        match = _NATIVE_LINE.match(line.strip())
        if match and match["source"].startswith("omni.rtx.materials"):
            prims = list(_PRIM_PATH.finditer(match["text"]))
            if prims:
                self._context = prims[-1].group(1)

    @property
    def context(self) -> str:
        """The last material path that the renderer log named (a hint, not an attribution)."""

        return self._context


_TAILS: dict[str, list] = {}  # path -> [tail, its owners (WeakOwners)]
_TAILS_LOCK = threading.Lock()
# The owners of the renderer log handler: every owner of start_native_log, also one whose config has no log file.
_HANDLER_OWNERS = WeakOwners()


def start_native_log_tail(path: Optional[str], owner: Any) -> Optional[NativeLogTail]:
    """Start the tail of a log for ``owner``, or add ``owner`` to the running one. Returns None without a path.

    The tail holds its owners by weak reference. An owner that is freed without :func:`stop_native_log_tail` does not
    keep it: when no owner is left alive, the tail ends by itself after its next read (see :func:`_still_owned`).
    """

    if not path:
        return None
    with _TAILS_LOCK:
        entry = _TAILS.get(path)
        if entry is None:
            entry = _TAILS[path] = [NativeLogTail(path, owned=_still_owned).start(), WeakOwners()]
            LOGGER.info("native renderer log: %s", path)
        entry[1].add(owner)
        return entry[0]


def stop_native_log_tail(path: Optional[str], owner: Any) -> bool:
    """Remove ``owner`` from a log tail. The last owner stops it and reads the final lines.

    Returns False when the thread did not stop in its time limit.
    """

    if not path:
        return True
    with _TAILS_LOCK:
        entry = _TAILS.get(path)
        if entry is None:
            return True
        entry[1].discard(owner)
        if len(entry[1]):
            entry[0].poll()
            return True
        del _TAILS[path]
    return entry[0].stop()


def _still_owned(tail: NativeLogTail) -> bool:
    """In the thread of ``tail``, after each read: whether an owner that is still alive uses it.

    When every owner was freed without :func:`stop_native_log_tail`, the tail leaves the list and its thread ends; with
    the last owner of the log handler, the handler is removed too. The renderer that wrote the log is gone, so the
    lines that were just read are its last ones.
    """

    with _TAILS_LOCK:
        entry = _TAILS.get(tail.path)
        if entry is None or entry[0] is not tail:
            return False  # stopped by its last owner, or replaced
        if len(entry[1]):
            return True
        del _TAILS[tail.path]
        if not len(_HANDLER_OWNERS):
            remove_renderer_log_handler()
    LOGGER.info("native renderer log %s: its owners were freed without a shutdown; the reader ends", tail.path)
    return False


def native_log_paths() -> list[str]:
    with _TAILS_LOCK:
        return list(_TAILS)


def begin_scene_events(diagnostics: Optional[RenderDiagnostics] = None) -> int:
    """Before a renderer loads another scene: mark where the failures of the new scene start.

    What the renderer wrote to its log until now is read first: it belongs to the scene that is closed.
    Returns the mark for :func:`retire_closed_scene_events`.
    """

    with _TAILS_LOCK:
        tails = [entry[0] for entry in _TAILS.values()]
    for tail in tails:
        tail.poll()
    diagnostics = diagnostics or get_render_diagnostics()
    # Lines that the files of the closed scene did not decide in time are failures of that scene.
    settle_body_resources(None, diagnostics)
    return diagnostics.begin_scene()


def retire_closed_scene_events(mark: int, diagnostics: Optional[RenderDiagnostics] = None) -> None:
    """The new scene is loaded: drop the failures and the material check result of the scene that was closed."""

    from ovui_data_adapters.common.render_diagnostics import set_verification

    (diagnostics or get_render_diagnostics()).retire_before(mark)
    set_verification({})


def last_log_context() -> str:
    """The last material path that any running tail saw (empty when none)."""

    with _TAILS_LOCK:
        return next((entry[0].context for entry in reversed(list(_TAILS.values())) if entry[0].context), "")


# --------------------------------------------------------------------------
# Modules that the renderer generated
# --------------------------------------------------------------------------

_GENERATED_DIRS: list[str] = []
_ORIGIN = re.compile(r'origin\("(?P<path>/[^"]+)"\)')


#: A renderer that is rebuilt makes a new directory each time; only the newest are read, so the list does not grow.
_GENERATED_DIRS_KEPT = 4


def register_generated_modules_dir(path: str) -> None:
    if path not in _GENERATED_DIRS:
        _GENERATED_DIRS.append(path)
        del _GENERATED_DIRS[:-_GENERATED_DIRS_KEPT]


def generated_modules_dirs() -> list[str]:
    return list(_GENERATED_DIRS)


def read_generated_modules(dirs: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """Read the MaterialX modules that the renderer generated.

    Each module is one compiled material. ``origins`` are the USD property paths
    that the module's annotations name: the materials that the module was built
    from. A module is built once for materials with an equal graph, so it names
    only the first of them.
    """

    modules = []
    for directory in dirs if dirs is not None else generated_modules_dirs():
        for path in sorted(glob.glob(os.path.join(directory, "*", "materialx.mdl"))):
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    text = handle.read()
            except OSError as exc:
                LOGGER.warning("generated module %s cannot be read: %s", path, exc)
                continue
            origins = sorted({m["path"].rsplit(".", 1)[0] for m in _ORIGIN.finditer(text)})
            modules.append({
                "id": os.path.basename(os.path.dirname(path)), "path": path,
                "bytes": os.path.getsize(path), "origins": origins,
            })
    return modules


class RendererLogHandler(logging.Handler):
    """Logging handler that feeds renderer log records to the render diagnostics."""

    def __init__(self, diagnostics: Optional[RenderDiagnostics] = None) -> None:
        super().__init__(level=logging.WARNING)
        self._diagnostics = diagnostics

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == LOGGER.name:
            return  # never feed our own warnings back
        try:
            ingest_message(record.getMessage(), self._diagnostics, last_log_context())
        except Exception:  # noqa: BLE001 - a log handler must not raise
            self.handleError(record)


_LOGGERS = ("ovrtx", "ovstage")


def install_renderer_log_handler() -> None:
    """Feed warnings of the renderer loggers into the render diagnostics, once."""

    for name in _LOGGERS:
        target = logging.getLogger(name)
        if not any(isinstance(h, RendererLogHandler) for h in target.handlers):
            target.addHandler(RendererLogHandler())


def remove_renderer_log_handler() -> None:
    for name in _LOGGERS:
        target = logging.getLogger(name)
        for handler in [h for h in target.handlers if isinstance(h, RendererLogHandler)]:
            target.removeHandler(handler)


def start_native_log(owner: Any, config: Any) -> None:
    """Start reading the log of a renderer config for ``owner`` (an adapter) and install the log handler.

    :func:`release_native_log` gives both back. An owner that is freed without it (an adapter that its caller dropped,
    or whose construction failed after this call) does not keep them: see :func:`start_native_log_tail`.
    """

    global _UNRELEASED
    owner._native_log_path = prepare_native_log(config)
    with _TAILS_LOCK:
        if not getattr(owner, "_native_log_started", False):
            owner._native_log_started = True
            _UNRELEASED += 1
        _HANDLER_OWNERS.add(owner)
        install_renderer_log_handler()
    start_native_log_tail(owner._native_log_path, owner)


def release_native_log(owner: Any) -> None:
    """Stop the log tail that :func:`start_native_log` started for ``owner``.

    The tail reads the last lines of the log first. The log handler is removed when no
    tail is left. Raises :class:`BackgroundTaskStuckError` when the tail does not stop in its
    time limit, so that the application exit fails instead of hanging.
    """

    from ovui_data_adapters.common.render_diagnostics import BackgroundTaskStuckError

    global _UNRELEASED
    path = getattr(owner, "_native_log_path", None)
    owner._native_log_path = None
    stopped = stop_native_log_tail(path, owner)
    with _TAILS_LOCK:
        if getattr(owner, "_native_log_started", False):
            owner._native_log_started = False
            _UNRELEASED -= 1
        _HANDLER_OWNERS.discard(owner)
        if not _TAILS and not len(_HANDLER_OWNERS):
            remove_renderer_log_handler()
    if not stopped:
        raise BackgroundTaskStuckError(f"the reader of the native renderer log {path} did not stop in {STOP_TIMEOUT:.0f} s")
