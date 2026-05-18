# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovuiinspect -- FastAPI inspector for standalone ovui apps.

Importing this module starts a localhost HTTP server when FastAPI and uvicorn
are available. UI-mutating requests are queued and must be drained by the app's
frame loop through :func:`drain_pending`.
"""

import base64
import contextlib
import io
import os
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "attach_application",
    "detach_application",
    "drain_pending",
    "status",
]

__version__ = "0.1.0"

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 9910
_EXEC_GLOBALS: dict[str, Any] = {"__name__": "__ovuiinspect_execute__"}

_IMGUI_KEY_TAB = 512
_IMGUI_KEY_LEFT_ARROW = 513
_IMGUI_KEY_RIGHT_ARROW = 514
_IMGUI_KEY_UP_ARROW = 515
_IMGUI_KEY_DOWN_ARROW = 516
_IMGUI_KEY_PAGE_UP = 517
_IMGUI_KEY_PAGE_DOWN = 518
_IMGUI_KEY_HOME = 519
_IMGUI_KEY_END = 520
_IMGUI_KEY_INSERT = 521
_IMGUI_KEY_DELETE = 522
_IMGUI_KEY_BACKSPACE = 523
_IMGUI_KEY_SPACE = 524
_IMGUI_KEY_ENTER = 525
_IMGUI_KEY_ESCAPE = 526
_IMGUI_KEY_LEFT_CTRL = 527
_IMGUI_KEY_LEFT_SHIFT = 528
_IMGUI_KEY_LEFT_ALT = 529
_IMGUI_KEY_LEFT_SUPER = 530
_IMGUI_KEY_0 = 536
_IMGUI_KEY_A = 546
_IMGUI_KEY_F1 = 572

_KEYS: dict[str, int] = {
    "tab": _IMGUI_KEY_TAB,
    "left": _IMGUI_KEY_LEFT_ARROW,
    "right": _IMGUI_KEY_RIGHT_ARROW,
    "up": _IMGUI_KEY_UP_ARROW,
    "down": _IMGUI_KEY_DOWN_ARROW,
    "page_up": _IMGUI_KEY_PAGE_UP,
    "pageup": _IMGUI_KEY_PAGE_UP,
    "page_down": _IMGUI_KEY_PAGE_DOWN,
    "pagedown": _IMGUI_KEY_PAGE_DOWN,
    "home": _IMGUI_KEY_HOME,
    "end": _IMGUI_KEY_END,
    "insert": _IMGUI_KEY_INSERT,
    "delete": _IMGUI_KEY_DELETE,
    "del": _IMGUI_KEY_DELETE,
    "backspace": _IMGUI_KEY_BACKSPACE,
    "space": _IMGUI_KEY_SPACE,
    "enter": _IMGUI_KEY_ENTER,
    "return": _IMGUI_KEY_ENTER,
    "escape": _IMGUI_KEY_ESCAPE,
    "esc": _IMGUI_KEY_ESCAPE,
    "ctrl": _IMGUI_KEY_LEFT_CTRL,
    "control": _IMGUI_KEY_LEFT_CTRL,
    "shift": _IMGUI_KEY_LEFT_SHIFT,
    "alt": _IMGUI_KEY_LEFT_ALT,
    "super": _IMGUI_KEY_LEFT_SUPER,
    "meta": _IMGUI_KEY_LEFT_SUPER,
    "cmd": _IMGUI_KEY_LEFT_SUPER,
}
for _i in range(10):
    _KEYS[str(_i)] = _IMGUI_KEY_0 + _i
for _i, _ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _KEYS[_ch] = _IMGUI_KEY_A + _i
for _i in range(1, 25):
    _KEYS[f"f{_i}"] = _IMGUI_KEY_F1 + (_i - 1)

_BUTTONS = {"left": 0, "right": 1, "middle": 2}
_MODIFIER_ORDER = ("ctrl", "shift", "alt", "super")
_DRAG_DEFAULT_STEPS = 10
_DRAG_STEPS_PER_SECOND = 60.0


@dataclass
class _Command:
    kind: str
    payload: dict[str, Any]
    timeout: float
    created_at: float = field(default_factory=time.monotonic)
    event: threading.Event = field(default_factory=threading.Event)
    steps: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    step_index: int = 0
    scheduled: bool = False
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    @property
    def deadline(self) -> float:
        return self.created_at + self.timeout

    @property
    def done(self) -> bool:
        return self.event.is_set()

    def succeed(self, **result: Any) -> None:
        self.result = {"success": True, **result}
        self.event.set()

    def fail(self, message: str) -> None:
        self.error = message
        self.result = {"success": False, "error": message}
        self.event.set()


class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.application: Optional[Any] = None
        self.attached_at: Optional[float] = None
        self.server_started_at: Optional[float] = None
        self.startup_error: Optional[str] = None
        self.last_error: Optional[str] = None
        self.last_frame_at: Optional[float] = None
        self.queue: list[_Command] = []

    def enqueue(self, command: _Command) -> None:
        with self.lock:
            self.queue.append(command)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "status": "ok" if self.startup_error is None else "degraded",
                "version": __version__,
                "host": _host(),
                "port": _port(),
                "app_attached": self.application is not None,
                "server_started_at": self.server_started_at,
                "attached_at": self.attached_at,
                "last_frame_at": self.last_frame_at,
                "queue_depth": len(self.queue),
                "execute_enabled": _execute_enabled(),
                "startup_error": self.startup_error,
                "last_error": self.last_error,
            }


_STATE = _State()
_SERVER_THREAD: Optional[threading.Thread] = None


def _host() -> str:
    return os.environ.get("OVUIINSPECT_HOST", _DEFAULT_HOST)


def _port() -> int:
    raw = os.environ.get("OVUIINSPECT_PORT", str(_DEFAULT_PORT))
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_PORT


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _enabled() -> bool:
    return _truthy_env("OVUIINSPECT_ENABLED", True)


def _execute_enabled() -> bool:
    return _truthy_env("OVUIINSPECT_ENABLE_EXECUTE", False)


def _log(message: str) -> None:
    print(f"[ovuiinspect] {message}", file=sys.stderr)


def attach_application(application: Any) -> None:
    """Attach the current Application instance for status and execute helpers."""
    with _STATE.lock:
        _STATE.application = application
        _STATE.attached_at = time.time()


def detach_application(application: Optional[Any] = None) -> None:
    """Detach the current Application instance."""
    with _STATE.lock:
        if application is None or _STATE.application is application:
            _STATE.application = None
            _STATE.attached_at = None


def status() -> dict[str, Any]:
    """Return current inspector status without going through HTTP."""
    return _STATE.snapshot()


def _require_attached() -> None:
    if _STATE.application is None:
        raise RuntimeError("ovuiinspect is imported, but no ovui application is attached yet")


def _wait(command: _Command) -> dict[str, Any]:
    if not command.event.wait(command.timeout + 0.25):
        command.fail("command timed out before the ovui frame loop drained it")
    return command.result or {"success": False, "error": "command finished without a result"}


def _submit(command: _Command) -> dict[str, Any]:
    try:
        _require_attached()
    except RuntimeError as exc:
        return {"success": False, "error": str(exc)}
    _STATE.enqueue(command)
    return _wait(command)


def _key_code(name: str) -> int:
    key = name.strip().lower().replace("-", "_")
    if key not in _KEYS:
        raise ValueError(f"unsupported key: {name!r}")
    return _KEYS[key]


def _modifier_codes(modifiers: Optional[list[str]]) -> list[int]:
    if not modifiers:
        return []
    lookup = {name.strip().lower(): True for name in modifiers if name.strip()}
    codes: list[int] = []
    for name in _MODIFIER_ORDER:
        if name in lookup or (name == "ctrl" and "control" in lookup):
            codes.append(_key_code(name))
    unknown = sorted(set(lookup) - {"ctrl", "control", "shift", "alt", "super", "meta", "cmd"})
    if unknown:
        raise ValueError(f"unsupported modifier(s): {', '.join(unknown)}")
    return codes


def _validate_xy(x: float, y: float) -> tuple[float, float]:
    x = float(x)
    y = float(y)
    if x < 0 or y < 0:
        raise ValueError("coordinates must be non-negative")
    return x, y


def _make_move(x: float, y: float, timeout: float) -> _Command:
    x, y = _validate_xy(x, y)
    command = _Command("steps", {}, timeout)
    command.steps = [("move", (x, y)), ("wait", ())]
    return command


def _make_click(
    x: float,
    y: float,
    button: str,
    double: bool,
    timeout: float,
) -> _Command:
    button_index = _BUTTONS.get(button)
    if button_index is None:
        raise ValueError("button must be one of: left, right, middle")
    x, y = _validate_xy(x, y)
    steps: list[tuple[str, tuple[Any, ...]]] = [("move", (x, y)), ("wait", ())]
    clicks = 2 if double else 1
    for _ in range(clicks):
        steps.extend([
            ("button", (button_index, True)),
            ("wait", ()),
            ("button", (button_index, False)),
            ("wait", ()),
        ])
    command = _Command("steps", {}, timeout)
    command.steps = steps
    return command


def _resolve_drag_steps(steps_count: Optional[int], duration: Optional[float]) -> int:
    if steps_count is not None:
        return max(1, int(steps_count))
    if duration is None:
        return _DRAG_DEFAULT_STEPS
    duration = float(duration)
    if duration < 0:
        raise ValueError("duration must be non-negative")
    return max(1, int(round(duration * _DRAG_STEPS_PER_SECOND)))


def _make_drag(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    button: str,
    timeout: float,
    steps_count: Optional[int] = None,
    duration: Optional[float] = None,
) -> _Command:
    button_index = _BUTTONS.get(button)
    if button_index is None:
        raise ValueError("button must be one of: left, right, middle")
    x1, y1 = _validate_xy(x1, y1)
    x2, y2 = _validate_xy(x2, y2)
    steps_count = _resolve_drag_steps(steps_count, duration)
    steps: list[tuple[str, tuple[Any, ...]]] = [
        ("move", (x1, y1)),
        ("wait", ()),
        ("button", (button_index, True)),
        ("wait", ()),
    ]
    for i in range(1, steps_count + 1):
        t = i / steps_count
        steps.append(("move", (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)))
        steps.append(("wait", ()))
    steps.extend([("button", (button_index, False)), ("wait", ())])
    command = _Command("steps", {}, timeout)
    command.steps = steps
    return command


def _make_scroll(
    direction: str,
    amount: float,
    x: Optional[float],
    y: Optional[float],
    timeout: float,
) -> _Command:
    direction = direction.lower()
    dx = dy = 0.0
    if direction == "up":
        dy = abs(float(amount))
    elif direction == "down":
        dy = -abs(float(amount))
    elif direction == "left":
        dx = -abs(float(amount))
    elif direction == "right":
        dx = abs(float(amount))
    else:
        raise ValueError("direction must be one of: up, down, left, right")
    steps: list[tuple[str, tuple[Any, ...]]] = []
    if x is not None and y is not None:
        x, y = _validate_xy(x, y)
        steps.extend([("move", (x, y)), ("wait", ())])
    steps.extend([("scroll", (dx, dy)), ("wait", ())])
    command = _Command("steps", {}, timeout)
    command.steps = steps
    return command


def _make_type(text: str, timeout: float) -> _Command:
    command = _Command("steps", {}, timeout)
    command.steps = [("text", (text,)), ("wait", ()), ("wait", ())]
    return command


def _make_press(key: str, modifiers: Optional[list[str]], timeout: float) -> _Command:
    key_code = _key_code(key)
    modifier_codes = _modifier_codes(modifiers)
    steps: list[tuple[str, tuple[Any, ...]]] = []
    for code in modifier_codes:
        steps.append(("key", (code, True)))
    steps.extend([("key", (key_code, True)), ("wait", ()), ("key", (key_code, False))])
    for code in reversed(modifier_codes):
        steps.append(("key", (code, False)))
    steps.append(("wait", ()))
    command = _Command("steps", {}, timeout)
    command.steps = steps
    return command


def _make_combo(combo: str, timeout: float) -> _Command:
    parts = [part.strip() for part in combo.replace("+", " ").split() if part.strip()]
    if not parts:
        raise ValueError("combo must include at least one key")
    key = parts[-1]
    modifiers = parts[:-1]
    return _make_press(key, modifiers, timeout)


def _advance_steps(
    command: _Command,
    ui_native: Any,
    application: Optional[Any],
) -> None:
    if command.step_index >= len(command.steps):
        command.succeed()
        return
    action, args = command.steps[command.step_index]
    command.step_index += 1
    if action == "wait":
        pass
    elif action == "move":
        ui_native._inject_mouse_move(float(args[0]), float(args[1]))
        command.payload["last_xy"] = (float(args[0]), float(args[1]))
    elif action == "button":
        ui_native._inject_mouse_button(int(args[0]), bool(args[1]))
        if int(args[0]) == 0 and bool(args[1]) and application is not None:
            hook = getattr(application, "_on_remote_left_click", None)
            xy = command.payload.get("last_xy")
            if callable(hook) and xy is not None:
                hook(int(xy[0]), int(xy[1]))
    elif action == "scroll":
        ui_native._inject_mouse_scroll(float(args[0]), float(args[1]))
    elif action == "text":
        ui_native._inject_text_input(str(args[0]))
        if application is not None:
            hook = getattr(application, "_on_remote_char", None)
            if callable(hook):
                for ch in str(args[0]):
                    hook(ch)
    elif action == "key":
        ui_native._inject_key_event(int(args[0]), bool(args[1]))
    else:
        command.fail(f"internal error: unsupported step {action!r}")
        return
    if command.step_index >= len(command.steps):
        command.succeed()


def _advance_screenshot(command: _Command, ui_native: Any) -> None:
    path = str(command.payload["path"])
    if not command.scheduled:
        command.scheduled = True
        schedule = getattr(ui_native, "_schedule_screenshot", None)
        if callable(schedule):
            if not schedule(path):
                command.fail("_schedule_screenshot returned False")
            return
        capture = getattr(ui_native, "_capture_screenshot", None)
        if callable(capture):
            if capture(path) and Path(path).exists():
                command.succeed(path=path)
            else:
                command.fail("_capture_screenshot failed")
            return
        command.fail("ovui screenshot API is unavailable")
        return

    poll = getattr(ui_native, "_poll_screenshot_done", None)
    done = True
    if callable(poll):
        done = bool(poll())
    if done and Path(path).exists():
        command.succeed(path=path)
    elif time.monotonic() >= command.deadline:
        command.fail("screenshot timed out before ovui wrote the image")


def _advance_execute(command: _Command, application: Optional[Any]) -> None:
    if not _execute_enabled():
        command.fail("execute is disabled; set OVUIINSPECT_ENABLE_EXECUTE=1 before launch")
        return
    code = str(command.payload.get("code", ""))
    stdout = io.StringIO()
    stderr = io.StringIO()
    namespace = dict(_EXEC_GLOBALS)
    namespace["application"] = application
    namespace["app"] = application
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            compiled = compile(code, "<ovuiinspect>", "exec")
            exec(compiled, namespace, namespace)
    except Exception:
        command.fail(traceback.format_exc())
        return
    command.succeed(stdout=stdout.getvalue(), stderr=stderr.getvalue())


def _advance_shutdown(command: _Command, application: Optional[Any]) -> None:
    if application is None:
        command.fail("no application is attached")
        return
    request_exit = getattr(application, "request_exit", None)
    if not callable(request_exit):
        command.fail("attached application has no request_exit()")
        return
    request_exit()
    command.succeed(message="shutdown requested")


def _advance_command(command: _Command, ui_native: Any, application: Optional[Any]) -> None:
    if time.monotonic() >= command.deadline:
        command.fail(f"{command.kind} command timed out")
        return
    try:
        if command.kind == "steps":
            _advance_steps(command, ui_native, application)
        elif command.kind == "screenshot":
            _advance_screenshot(command, ui_native)
        elif command.kind == "execute":
            _advance_execute(command, application)
        elif command.kind == "shutdown":
            _advance_shutdown(command, application)
        else:
            command.fail(f"internal error: unsupported command {command.kind!r}")
    except Exception:
        command.fail(traceback.format_exc())


def drain_pending(ui_native: Any, *, application: Optional[Any] = None) -> int:
    """Drain one queued inspector step onto the ovui frame loop.

    The host ovui application calls this immediately before
    ``await ui.next_frame()``. Only one step is advanced per frame so hover,
    press, release, and drag sequences preserve ImGui's expected frame
    ordering.
    """
    with _STATE.lock:
        _STATE.last_frame_at = time.time()
        if application is not None:
            _STATE.application = application
        command = _STATE.queue[0] if _STATE.queue else None
    if command is None:
        return 0

    _advance_command(command, ui_native, application or _STATE.application)

    if command.done:
        with _STATE.lock:
            if _STATE.queue and _STATE.queue[0] is command:
                _STATE.queue.pop(0)
            else:
                try:
                    _STATE.queue.remove(command)
                except ValueError:
                    pass
            if command.error:
                _STATE.last_error = command.error
    return 1


def _image_bytes(fmt: str, timeout: float) -> tuple[bytes, str, dict[str, Any]]:
    suffix = ".jpg" if fmt in {"jpg", "jpeg"} else ".png"
    media_type = "image/jpeg" if suffix == ".jpg" else "image/png"
    tmp = tempfile.NamedTemporaryFile(prefix="ovuiinspect_", suffix=suffix, delete=False)
    path = tmp.name
    tmp.close()
    command = _Command("screenshot", {"path": path}, timeout)
    result = _submit(command)
    if not result.get("success"):
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)
        return b"", media_type, result
    data = Path(path).read_bytes()
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    return data, media_type, result


def _create_app() -> Any:
    from fastapi import Body, FastAPI, HTTPException, Response
    from pydantic import BaseModel

    app = FastAPI(title="ovuiinspect", version=__version__)

    class MoveRequest(BaseModel):
        x: float
        y: float
        duration: float = 0.0
        timeout: float = 5.0

    class ClickRequest(BaseModel):
        x: float
        y: float
        button: str = "left"
        double: bool = False
        timeout: float = 5.0

    class DragRequest(BaseModel):
        start_x: float
        start_y: float
        end_x: float
        end_y: float
        button: str = "left"
        steps: Optional[int] = None
        duration: Optional[float] = None
        timeout: float = 10.0

    class ScrollRequest(BaseModel):
        direction: str
        amount: float = 5.0
        x: Optional[float] = None
        y: Optional[float] = None
        timeout: float = 5.0

    class TypeRequest(BaseModel):
        text: str
        delay: float = 0.0
        timeout: float = 5.0

    class PressRequest(BaseModel):
        key: str
        modifiers: Optional[list[str]] = None
        timeout: float = 5.0

    class ComboRequest(BaseModel):
        combo: str
        timeout: float = 5.0

    class ExecuteRequest(BaseModel):
        code: str
        timeout: float = 10.0

    def checked(result: dict[str, Any]) -> dict[str, Any]:
        if result.get("success") is False:
            raise HTTPException(status_code=400, detail=result.get("error", "request failed"))
        return result

    @app.get("/health")
    def health() -> dict[str, Any]:
        return _STATE.snapshot()

    @app.get("/status")
    def get_status() -> dict[str, Any]:
        return _STATE.snapshot()

    def capture_application_image(fmt: str, timeout: float) -> Response:
        fmt = fmt.lower()
        if fmt not in {"png", "jpg", "jpeg"}:
            raise HTTPException(status_code=400, detail="fmt must be png, jpg, or jpeg")
        data, media_type, result = _image_bytes(fmt, timeout)
        if not result.get("success"):
            raise HTTPException(status_code=503, detail=result.get("error", "screenshot failed"))
        return Response(content=data, media_type=media_type)

    def capture_application_json(fmt: str, timeout: float) -> dict[str, Any]:
        fmt = fmt.lower()
        if fmt not in {"png", "jpg", "jpeg"}:
            raise HTTPException(status_code=400, detail="fmt must be png, jpg, or jpeg")
        data, media_type, result = _image_bytes(fmt, timeout)
        if not result.get("success"):
            raise HTTPException(status_code=503, detail=result.get("error", "screenshot failed"))
        return {
            "success": True,
            "image_base64": base64.b64encode(data).decode("ascii"),
            "mime_type": media_type,
            "bytes": len(data),
        }

    @app.get("/screenshot")
    def screenshot(timeout: float = 5.0, fmt: str = "png") -> Response:
        return capture_application_image(fmt, timeout)

    @app.post("/screenshot")
    def screenshot_json(timeout: float = 5.0, fmt: str = "png") -> dict[str, Any]:
        return capture_application_json(fmt, timeout)

    @app.get("/capture/application.png")
    def capture_application_png(timeout: float = 5.0) -> Response:
        return capture_application_image("png", timeout)

    @app.get("/capture/application.jpg")
    def capture_application_jpg(timeout: float = 5.0) -> Response:
        return capture_application_image("jpg", timeout)

    @app.post("/capture/application")
    def capture_application(timeout: float = 5.0, fmt: str = "png") -> dict[str, Any]:
        return capture_application_json(fmt, timeout)

    @app.post("/mouse/move")
    def mouse_move(request: MoveRequest = Body(...)) -> dict[str, Any]:
        try:
            command = _make_move(request.x, request.y, request.timeout)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return checked(_submit(command))

    @app.post("/mouse/click")
    def mouse_click(request: ClickRequest = Body(...)) -> dict[str, Any]:
        try:
            command = _make_click(
                request.x,
                request.y,
                request.button,
                request.double,
                request.timeout,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return checked(_submit(command))

    @app.post("/mouse/drag")
    def mouse_drag(request: DragRequest = Body(...)) -> dict[str, Any]:
        try:
            command = _make_drag(
                request.start_x,
                request.start_y,
                request.end_x,
                request.end_y,
                request.button,
                request.timeout,
                request.steps,
                request.duration,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return checked(_submit(command))

    @app.post("/mouse/scroll")
    def mouse_scroll(request: ScrollRequest = Body(...)) -> dict[str, Any]:
        try:
            command = _make_scroll(
                request.direction,
                request.amount,
                request.x,
                request.y,
                request.timeout,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return checked(_submit(command))

    @app.post("/keyboard/type")
    def keyboard_type(request: TypeRequest = Body(...)) -> dict[str, Any]:
        return checked(_submit(_make_type(request.text, request.timeout)))

    @app.post("/keyboard/press")
    def keyboard_press(request: PressRequest = Body(...)) -> dict[str, Any]:
        try:
            command = _make_press(request.key, request.modifiers, request.timeout)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return checked(_submit(command))

    @app.post("/keyboard/combo")
    def keyboard_combo(request: ComboRequest = Body(...)) -> dict[str, Any]:
        try:
            command = _make_combo(request.combo, request.timeout)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return checked(_submit(command))

    @app.post("/execute")
    def execute(request: ExecuteRequest = Body(...)) -> dict[str, Any]:
        result = _submit(_Command("execute", {"code": request.code}, request.timeout))
        if result.get("success") is False and not _execute_enabled():
            raise HTTPException(status_code=403, detail=result.get("error"))
        return checked(result)

    @app.post("/shutdown")
    def shutdown() -> dict[str, Any]:
        return checked(_submit(_Command("shutdown", {}, 5.0)))

    return app


def _start_server() -> None:
    global _SERVER_THREAD
    if not _enabled():
        _log("disabled by OVUIINSPECT_ENABLED")
        return
    if _SERVER_THREAD is not None:
        return
    try:
        import uvicorn
    except Exception as exc:
        _STATE.startup_error = f"missing dependency: {type(exc).__name__}: {exc}"
        _log(f"FastAPI server not started: {_STATE.startup_error}")
        return
    try:
        app = _create_app()
    except Exception as exc:
        _STATE.startup_error = f"app creation failed: {type(exc).__name__}: {exc}"
        _log(_STATE.startup_error)
        return

    def _run() -> None:
        config = uvicorn.Config(
            app,
            host=_host(),
            port=_port(),
            log_level=os.environ.get("OVUIINSPECT_LOG_LEVEL", "warning"),
            access_log=_truthy_env("OVUIINSPECT_ACCESS_LOG", False),
        )
        server = uvicorn.Server(config)
        with _STATE.lock:
            _STATE.server_started_at = time.time()
        try:
            server.run()
        except Exception as exc:
            _STATE.startup_error = f"server failed: {type(exc).__name__}: {exc}"
            _log(_STATE.startup_error)

    _SERVER_THREAD = threading.Thread(target=_run, name="ovuiinspect-fastapi", daemon=True)
    _SERVER_THREAD.start()
    _log(f"server starting on http://{_host()}:{_port()}")


_start_server()
