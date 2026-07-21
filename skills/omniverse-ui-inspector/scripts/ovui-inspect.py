#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovui-inspect -- zero-dependency CLI client for the ovui inspector."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HOST = os.environ.get("OVUIINSPECT_HOST", "127.0.0.1")
PORT = os.environ.get("OVUIINSPECT_PORT", "9910")
BASE_URL = f"http://{HOST}:{PORT}"


def configure(host: str | None = None, port: int | str | None = None) -> None:
    global HOST, PORT, BASE_URL
    if host:
        HOST = str(host)
    if port:
        PORT = str(port)
    BASE_URL = f"http://{HOST}:{PORT}"


def _decode_error(error: HTTPError) -> dict:
    body = error.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(body)
    except Exception:
        payload = body[:500]
    return {"success": False, "error": f"HTTP {error.code}", "detail": payload}


def _connection_error(exc: object) -> dict:
    return {
        "success": False,
        "error": f"Connection failed: {exc}",
        "hint": (
            "Inspector is not reachable. Verify the ovui app process is still "
            "running and listening on OVUIINSPECT_HOST/OVUIINSPECT_PORT."
        ),
    }


def _post(path: str, data: dict | None = None, timeout: float = 60.0):
    req = Request(
        f"{BASE_URL}{path}",
        data=json.dumps(data or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except HTTPError as exc:
        return _decode_error(exc)
    except URLError as exc:
        return _connection_error(exc.reason)
    except (TimeoutError, OSError) as exc:
        return _connection_error(exc)


def _get(path: str, params: dict | None = None, timeout: float = 60.0):
    url = f"{BASE_URL}{path}"
    if params:
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        if qs:
            url = f"{url}?{qs}"
    req = Request(url, method="GET")
    try:
        with urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if content_type.startswith("image/"):
                return raw, content_type
            return json.loads(raw)
    except HTTPError as exc:
        return _decode_error(exc)
    except URLError as exc:
        return _connection_error(exc.reason)
    except (TimeoutError, OSError) as exc:
        return _connection_error(exc)


def health():
    return _get("/health", timeout=5.0)


def status():
    return _get("/status", timeout=5.0)


def application_state(timeout: float = 5.0):
    return _get("/state", {"timeout": timeout}, timeout=timeout + 5)


def wait_for_health(timeout: float = 60.0, interval: float = 0.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = health()
        if isinstance(result, dict) and result.get("status") in {"ok", "degraded"}:
            return True
        time.sleep(interval)
    return False


def screenshot(out_path: str, fmt: str = "png", timeout: float = 10.0):
    ext = "jpg" if fmt.lower() in {"jpg", "jpeg"} else "png"
    result = _get(f"/capture/application.{ext}", {"timeout": timeout}, timeout=timeout + 5)
    if isinstance(result, tuple):
        data, _content_type = result
        with open(out_path, "wb") as handle:
            handle.write(data)
        return {"success": True, "out": out_path, "bytes": len(data)}
    if isinstance(result, dict) and result.get("image_base64"):
        data = base64.b64decode(result["image_base64"])
        with open(out_path, "wb") as handle:
            handle.write(data)
        return {"success": True, "out": out_path, "bytes": len(data)}
    return result


def move(x: int, y: int, timeout: float = 5.0):
    return _post("/mouse/move", {"x": x, "y": y, "timeout": timeout}, timeout=timeout + 5)


def click(
    x: int | None = None,
    y: int | None = None,
    *,
    button: str = "left",
    double: bool = False,
    modifiers: list[str] | None = None,
    timeout: float = 5.0,
):
    data = {"button": button, "double": double, "timeout": timeout}
    if x is not None:
        data["x"] = x
    if y is not None:
        data["y"] = y
    if modifiers is not None:
        data["modifiers"] = modifiers
    return _post("/mouse/click", data, timeout=timeout + 5)


def drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    *,
    button: str = "left",
    steps: int | None = None,
    duration: float | None = None,
    modifiers: list[str] | None = None,
    timeout: float = 10.0,
):
    data = {
        "start_x": start_x,
        "start_y": start_y,
        "end_x": end_x,
        "end_y": end_y,
        "button": button,
        "timeout": timeout,
    }
    if steps is not None:
        data["steps"] = steps
    if duration is not None:
        data["duration"] = duration
    if modifiers is not None:
        data["modifiers"] = modifiers
    return _post(
        "/mouse/drag",
        data,
        timeout=timeout + 5,
    )


def scroll(
    direction: str,
    *,
    amount: float = 5.0,
    x: int | None = None,
    y: int | None = None,
    timeout: float = 5.0,
):
    return _post(
        "/mouse/scroll",
        {"direction": direction, "amount": amount, "x": x, "y": y, "timeout": timeout},
        timeout=timeout + 5,
    )


def type_text(text: str, timeout: float = 5.0):
    return _post("/keyboard/type", {"text": text, "timeout": timeout}, timeout=timeout + 5)


def press(key: str, modifiers: list[str] | None = None, timeout: float = 5.0):
    return _post(
        "/keyboard/press",
        {"key": key, "modifiers": modifiers, "timeout": timeout},
        timeout=timeout + 5,
    )


def combo(combo_str: str, timeout: float = 5.0):
    return _post(
        "/keyboard/combo",
        {"combo": combo_str, "timeout": timeout},
        timeout=timeout + 5,
    )


def execute(code: str, timeout: float = 10.0):
    return _post("/execute", {"code": code, "timeout": timeout}, timeout=timeout + 5)


def shutdown():
    return _post("/shutdown", {}, timeout=10.0)


def _print(data) -> None:
    if isinstance(data, (dict, list)):
        print(json.dumps(data, indent=2))
    elif isinstance(data, (bytes, bytearray)):
        print(f"<{len(data)} bytes>")
    else:
        print(data)


def _exit_code(data) -> int:
    if isinstance(data, dict) and data.get("success") is False:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ovui-inspect", description="ovui Inspector CLI")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("health")
    sub.add_parser("status")
    state_cmd = sub.add_parser(
        "state",
        help="Read QA application state (requires OVUIINSPECT_ENABLE_STATE=1)",
    )
    state_cmd.add_argument("--out", help="Optional JSON output path")
    state_cmd.add_argument("--timeout", type=float, default=5.0)
    wait_cmd = sub.add_parser("wait")
    wait_cmd.add_argument("--timeout", type=float, default=60.0)
    shot = sub.add_parser("screenshot")
    shot.add_argument("--out", "-o", default="screenshot.png")
    shot.add_argument("--format", choices=["png", "jpg", "jpeg"], default="png")
    shot.add_argument("--timeout", type=float, default=10.0)
    mv = sub.add_parser("move")
    mv.add_argument("x", type=int)
    mv.add_argument("y", type=int)
    ck = sub.add_parser("click")
    ck.add_argument("x", type=int)
    ck.add_argument("y", type=int)
    ck.add_argument("--button", choices=["left", "right", "middle"], default="left")
    ck.add_argument("--double", action="store_true")
    ck.add_argument("--modifiers")
    dg = sub.add_parser("drag")
    dg.add_argument("start_x", type=int)
    dg.add_argument("start_y", type=int)
    dg.add_argument("end_x", type=int)
    dg.add_argument("end_y", type=int)
    dg.add_argument("--button", choices=["left", "right", "middle"], default="left")
    dg.add_argument(
        "--duration",
        type=float,
        help="drag duration in seconds; converted to frame-stepped positions by the server",
    )
    dg.add_argument(
        "--steps",
        type=int,
        help="exact drag move-step count; overrides duration when both are provided",
    )
    dg.add_argument("--modifiers", help="Comma-separated ctrl,shift,alt,super")
    sc = sub.add_parser("scroll")
    sc.add_argument("direction", choices=["up", "down", "left", "right"])
    sc.add_argument("--amount", type=float, default=5.0)
    sc.add_argument("--x", type=int)
    sc.add_argument("--y", type=int)
    ty = sub.add_parser("type")
    ty.add_argument("text")
    pr = sub.add_parser("press")
    pr.add_argument("key")
    pr.add_argument("--modifiers")
    co = sub.add_parser("combo")
    co.add_argument("combo")
    ex = sub.add_parser("execute")
    ex.add_argument("code")
    ex.add_argument("--timeout", type=float, default=10.0)
    sub.add_parser("shutdown")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    result = None
    if args.command == "health":
        result = health()
    elif args.command == "status":
        result = status()
    elif args.command == "state":
        result = application_state(args.timeout)
        if args.out and isinstance(result, dict) and result.get("success"):
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2, sort_keys=True)
                handle.write("\n")
            result = {"success": True, "out": args.out, "state": result.get("state")}
    elif args.command == "wait":
        ok = wait_for_health(args.timeout)
        print("OK" if ok else "TIMEOUT")
        return 0 if ok else 1
    elif args.command == "screenshot":
        result = screenshot(args.out, args.format, args.timeout)
    elif args.command == "move":
        result = move(args.x, args.y)
    elif args.command == "click":
        modifiers = [m.strip() for m in args.modifiers.split(",")] if args.modifiers else None
        result = click(args.x, args.y, button=args.button, double=args.double, modifiers=modifiers)
    elif args.command == "drag":
        modifiers = [m.strip() for m in args.modifiers.split(",")] if args.modifiers else None
        result = drag(
            args.start_x,
            args.start_y,
            args.end_x,
            args.end_y,
            button=args.button,
            steps=args.steps,
            duration=args.duration,
            modifiers=modifiers,
        )
    elif args.command == "scroll":
        result = scroll(args.direction, amount=args.amount, x=args.x, y=args.y)
    elif args.command == "type":
        result = type_text(args.text)
    elif args.command == "press":
        modifiers = [m.strip() for m in args.modifiers.split(",")] if args.modifiers else None
        result = press(args.key, modifiers)
    elif args.command == "combo":
        result = combo(args.combo)
    elif args.command == "execute":
        result = execute(args.code, args.timeout)
    elif args.command == "shutdown":
        result = shutdown()
    _print(result)
    return _exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
