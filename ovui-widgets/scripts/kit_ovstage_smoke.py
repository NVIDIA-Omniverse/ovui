# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Kit-integrated ovstage/ovrtx render + pick + drag smoke for ovui.

Launches the ovui-widgets app against the Kit ovstage data adapter provider,
warms up the first render frame, then drives a *real* mouse
pick and a *real* mouse drag (via ``omni.ui`` input injection — never by mutating
the stage directly) and verifies the picked prim's transform actually changed.
On a host without a display, launch it through ``xvfb-run``: the ovui OpenGL
gizmo layer needs a display even though OVRTX renders the viewport with Vulkan.

It validates that ovui resolves the Kit-integrated ``ovstage`` / ``ovrtx`` runtime
(and that no stale standalone ``ovrtx`` checkout leaks in), captures before/after
screenshots, writes a JSON result, and exits non-zero on any failure.

See ``ovui-data-adapters/docs/kit-runtime.md`` for the Kit build, the required
environment, and troubleshooting.

Example
-------
    cd /path/to/ovui
    OVSTAGE_ROOT=$KIT_ROOT/rendering/ovstage \
    OVRTX_ROOT=$KIT_ROOT/rendering/ovrtx \
    OVSTAGE_BUILD_DIR=$KIT_ROOT/rendering/_build/linux-x86_64/release \
    LD_LIBRARY_PATH=$KIT_ROOT/rendering/_build/linux-x86_64/release \
    PYTHONPATH=$OVSTAGE_ROOT/public/python:$OVRTX_ROOT/public/python \
      xvfb-run -a ovui-widgets/_venv312/bin/python ovui-widgets/scripts/kit_ovstage_smoke.py \
        --out-dir /tmp/ovui-kit-smoke

The first ``Renderer.step(..., ordinal=...)`` after a fresh Kit build can take ~30s
while shaders compile/cache; ``--first-frame-timeout`` defaults to 300s for
that reason.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import sys
import threading
import time
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SCENE = (
    _REPO_ROOT
    / "ovui-data-adapters"
    / "tests"
    / "data"
    / "ovstage_static_scene.usda"
)
# Default prim to pick/move: the cube in the bundled static test scene. Override
# with --prim-path for other scenes (or pass --prim-path "" to pick whatever the
# scene-bounds centre selects).
_DEFAULT_PRIM = "/World/Hierarchy/GroupA/BoxA"


# ── env bootstrap (must happen before importing omni.ui / ovui-widgets) ──────────


def _scrub_standalone_ovrtx() -> list[str]:
    """Drop any already-imported / sys.path standalone ovrtx so Kit ovrtx wins."""
    removed: list[str] = []
    for name in list(sys.modules):
        if name == "ovrtx" or name.startswith("ovrtx."):
            sys.modules.pop(name, None)
            removed.append(name)
    sys.path[:] = [p for p in sys.path if "/dev/ovrtx" not in str(p).replace("\\", "/")]
    return removed


def _resolve_roots(args: argparse.Namespace) -> dict[str, str]:
    """Resolve OVSTAGE_ROOT / OVRTX_ROOT from flags, env, then KIT_ROOT."""
    kit_root = args.kit_root or os.environ.get("KIT_ROOT")
    ovstage = (
        args.ovstage_root
        or os.environ.get("OVSTAGE_ROOT")
        or (str(Path(kit_root) / "rendering" / "ovstage") if kit_root else None)
    )
    ovrtx = (
        args.ovrtx_root
        or os.environ.get("OVRTX_ROOT")
        or (str(Path(kit_root) / "rendering" / "ovrtx") if kit_root else None)
    )
    roots: dict[str, str] = {}
    if ovstage:
        roots["OVSTAGE_ROOT"] = ovstage
    if ovrtx:
        roots["OVRTX_ROOT"] = ovrtx
    return roots


def _configure_environment(args: argparse.Namespace) -> dict[str, Any]:
    """Set the ovui-level env the native ovstage provider needs, in-process.

    Native library discovery — the ovstage/ovrtx runtime directories on
    ``LD_LIBRARY_PATH`` and their public Python packages on ``PYTHONPATH`` —
    must be set by the caller before the process starts; this only configures
    the process-internal switches the resolver reads at import time. No
    OpenUSD (``pxr``) installation is required for the native provider.
    """
    roots = _resolve_roots(args)
    os.environ.update(roots)
    os.environ.setdefault("OVUI_DATA_ADAPTER_PROVIDER", "ovstage")
    # The interactive smoke needs the stock OpenGL transform-gizmo layer. OVRTX
    # remains Vulkan-backed independently. Headless Vulkan ovui intentionally
    # rejects an OpenGL -> Vulkan gizmo fallback, so use Xvfb on display-less
    # hosts instead of silently losing the real pick/drag surface.
    os.environ.setdefault("OMNIUI_HEADLESS", "0")
    os.environ.setdefault("OMNIUI_BACKEND", "opengl")
    os.environ.setdefault("OVRTX_SKIP_USD_CHECK", "1")
    removed = _scrub_standalone_ovrtx()
    return {"roots": roots, "scrubbed_ovrtx_modules": removed}


# ── small helpers ────────────────────────────────────────────────────────────


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return repr(value)


def _module_info(name: str) -> dict[str, Any]:
    import importlib

    try:
        mod = importlib.import_module(name)
        return {
            "ok": True,
            "file": getattr(mod, "__file__", None),
            "version": getattr(mod, "__version__", None),
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}


def _png_size(path: Path) -> tuple[Optional[int], Optional[int]]:
    try:
        data = path.read_bytes()
    except OSError:
        return (None, None)
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return (None, None)
    try:
        width, height = struct.unpack(">II", data[16:24])
    except struct.error:
        return (None, None)
    return (int(width), int(height))


# ── the smoke (imports omni.ui / ovui-widgets lazily, after env is configured) ───


def run_smoke(args: argparse.Namespace, env_info: dict[str, Any]) -> dict[str, Any]:
    import asyncio

    # OVRTX owns the first Carbonite framework in the Kit runtime cohort.  It
    # must be constructed before importing omni.ui, Application, or OVStage;
    # the Application later consumes this exact adapter for the scene attach.
    from ovui_widgets.app.native_runtime_bootstrap import (
        install_preconstructed_renderer,
        preconstruct_selected_native_renderer,
    )

    bootstrap = preconstruct_selected_native_renderer()
    import numpy as np
    import omni.ui as ui
    from omni.ui import testing as uitesting

    from ovui_widgets.app.application import Application
    from ovui_widgets.app.layout import write_split_ini
    from ovui_widgets.app.style import apply_global_styles, set_theme
    from ovui_widgets.common.selection import SelectionBus

    out_dir = Path(args.out_dir)
    shot_dir = out_dir / "screenshots"
    state_dir = out_dir / "state"
    shot_dir.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    label = args.label

    state: dict[str, Any] = {
        "label": label,
        "scene": str(args.scene),
        "prim_path": args.prim_path,
        "env": env_info,
        "provider_env": os.environ.get("OVUI_DATA_ADAPTER_PROVIDER"),
        # runtime_modules is captured after the provider resolves Kit ovstage /
        # ovrtx (the resolver only adds OVSTAGE_ROOT/OVRTX_ROOT to sys.path
        # during provider init), so it reflects the actually-loaded packages.
        "runtime_modules": {},
        "screenshots": {},
        "errors": [],
    }

    # First-frame watchdog: a daemon thread that hard-exits if warmup blocks past
    # the timeout (the synchronous first attached step runs in C and cannot be
    # interrupted cooperatively).
    warmup_done = threading.Event()

    def _watchdog() -> None:
        if warmup_done.wait(timeout=float(args.first_frame_timeout)):
            return
        state["errors"].append(
            {
                "phase": "warmup",
                "error": f"first frame did not render within {args.first_frame_timeout}s",
            }
        )
        try:
            (state_dir / f"{label}.json").write_text(
                json.dumps(_json_safe(state), indent=2, sort_keys=True), encoding="utf-8"
            )
        finally:
            os._exit(2)

    threading.Thread(target=_watchdog, name="kit-smoke-watchdog", daemon=True).start()

    # ── geometry / projection helpers (real screen coordinates) ──────────────

    def _image_rect(viewport: Any) -> Optional[tuple[float, float, int, int]]:
        image = getattr(viewport, "_image", None)
        if image is None:
            return None
        width = int(getattr(image, "computed_width", 0) or 0)
        height = int(getattr(image, "computed_height", 0) or 0)
        if width <= 0 or height <= 0:
            try:
                width, height = viewport._get_viewport_size()
            except Exception:
                return None
        x = float(getattr(image, "screen_position_x", 0.0) or 0.0)
        y = float(getattr(image, "screen_position_y", 0.0) or 0.0)
        return x, y, int(width), int(height)

    def _project(viewport: Any, world_point: tuple[float, float, float]) -> Optional[tuple[int, int]]:
        rect = _image_rect(viewport)
        camera = getattr(viewport, "_camera", None)
        if rect is None or camera is None:
            return None
        ix, iy, w, h = rect
        if w <= 0 or h <= 0:
            return None
        try:
            view, proj = camera.get_matrices(w, h)
            vec = np.array([world_point[0], world_point[1], world_point[2], 1.0])
            clip = np.asarray(proj) @ (np.asarray(view) @ vec)
            if abs(float(clip[3])) < 1.0e-6:
                return None
            ndc = clip[:3] / clip[3]
        except Exception:
            return None
        sx = ix + (float(ndc[0]) + 1.0) * 0.5 * float(w)
        sy = iy + (1.0 - float(ndc[1])) * 0.5 * float(h)
        return int(round(sx)), int(round(sy))

    def _bounds_center(app: Application, path: str) -> Optional[tuple[float, float, float]]:
        adapter = getattr(app, "_stage_adapter", None)
        compute = getattr(adapter, "compute_world_aabb", None)
        if not callable(compute):
            return None
        try:
            bounds = compute([path])
        except Exception:
            bounds = None
        if not bounds:
            return None
        (min_x, min_y, min_z), (max_x, max_y, max_z) = bounds
        return (
            (min_x + max_x) * 0.5,
            (min_y + max_y) * 0.5,
            (min_z + max_z) * 0.5,
        )

    def _pick_candidates(app: Application) -> list[tuple[float, float]]:
        viewport = getattr(app, "_viewport_window", None)
        if viewport is None:
            return []
        target = args.prim_path or "/"
        center = _bounds_center(app, target) or (0.0, 0.0, 0.0)
        cx, cy, cz = center
        offsets = [
            (0.0, 0.0, 0.0),
            (0.0, 0.1, 0.0),
            (0.0, -0.1, 0.0),
            (0.1, 0.0, 0.0),
            (-0.1, 0.0, 0.0),
        ]
        out: list[tuple[float, float]] = []
        for ox, oy, oz in offsets:
            screen = _project(viewport, (cx + ox, cy + oy, cz + oz))
            if screen is not None:
                out.append((float(screen[0]), float(screen[1])))
        # The renderer's private OVStage camera can be one frame ahead of the
        # viewport controller while the first UI layout settles.  The default
        # framing keeps the requested object at image centre, so retain centre
        # samples as deterministic fallbacks for the real mouse click.
        rect = _image_rect(viewport)
        if rect is not None:
            ix, iy, width, height = rect
            mid_x = ix + width * 0.5
            mid_y = iy + height * 0.5
            for dx, dy in ((0.0, 0.0), (8.0, 0.0), (-8.0, 0.0), (0.0, 8.0), (0.0, -8.0)):
                candidate = (float(mid_x + dx), float(mid_y + dy))
                if candidate not in out:
                    out.append(candidate)
        return out

    def _handle_projection(app: Application) -> dict[str, Any]:
        viewport = getattr(app, "_viewport_window", None)
        fn = getattr(viewport, "get_streamed_transform_handle_projections", None)
        if not callable(fn):
            return {"available": False}
        rect = _image_rect(viewport)
        w, h = (rect[2], rect[3]) if rect else (args.width, args.height)
        try:
            # Project at the real image resolution so the returned handle
            # positions line up with the gizmo as drawn.
            return fn(width=int(w), height=int(h))
        except Exception:
            return {"available": False}

    def _drag_candidates(app: Application, projection: dict[str, Any]) -> list[dict[str, Any]]:
        viewport = getattr(app, "_viewport_window", None)
        rect = _image_rect(viewport) if viewport else None
        out: list[dict[str, Any]] = []
        rw = max(1.0, float(projection.get("width") or 1.0))
        rh = max(1.0, float(projection.get("height") or 1.0))
        ix, iy, iw, ih = rect if rect else (0.0, 0.0, rw, rh)
        for axis in projection.get("axes") or []:
            start = axis.get("start")
            end = axis.get("end")
            if not start or not end or len(start) < 2 or len(end) < 2:
                continue
            sx = ix + (float(start[0]) / rw) * iw
            sy = iy + (float(start[1]) / rh) * ih
            ex = ix + (float(end[0]) / rw) * iw
            ey = iy + (float(end[1]) / rh) * ih
            vx, vy = ex - sx, ey - sy
            # Sample several press points along the shaft so at least one lands
            # on the thin arrow geometry; drag past the tip for an unambiguous
            # axis motion.
            for frac in (0.35, 0.5, 0.65):
                press = (round(sx + frac * vx), round(sy + frac * vy))
                release = (round(sx + 1.6 * vx), round(sy + 1.6 * vy))
                moves = [
                    (
                        round(press[0] + t * (release[0] - press[0])),
                        round(press[1] + t * (release[1] - press[1])),
                    )
                    for t in (0.25, 0.5, 0.75, 1.0)
                ]
                out.append(
                    {
                        "axis": str(axis.get("axis") or ""),
                        "press": press,
                        "moves": moves,
                        "release": release,
                    }
                )
        return out

    # ── state inspection ─────────────────────────────────────────────────────

    def _capture(name: str) -> dict[str, Any]:
        path = shot_dir / f"{label}_{name}.png"
        ok = bool(uitesting.capture_screenshot(str(path)))
        w, h = _png_size(path) if path.exists() else (None, None)
        info = {
            "path": str(path),
            "ok": ok,
            "exists": path.exists(),
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "width": w,
            "height": h,
        }
        state["screenshots"][name] = info
        if not ok or not path.exists() or info["size_bytes"] <= 0:
            state["errors"].append({"phase": "screenshot", "error": {name: info}})
        return info

    def _selection_paths(app: Application) -> list[str]:
        bus = getattr(app, "_selection_bus", None)
        snapshot = bus.get_snapshot() if bus and hasattr(bus, "get_snapshot") else None
        return list(snapshot.paths()) if snapshot else []

    def _transform_adapter(app: Application) -> Any:
        viewport = getattr(app, "_viewport_window", None)
        model = getattr(viewport, "_transform_model", None)
        return getattr(model, "_transform", None)

    def _local_translation(app: Application, path: str) -> Optional[list[float]]:
        adapter = _transform_adapter(app)
        if adapter is None:
            return None
        try:
            m = adapter.get_local_transform(path)
            return [float(m[3][0]), float(m[3][1]), float(m[3][2])]
        except Exception:
            return None

    async def _drive(frames: int) -> None:
        for _ in range(frames):
            await ui.next_frame()

    # ── input drivers (real omni.ui mouse events) ────────────────────────────

    async def _click(x: float, y: float) -> None:
        await uitesting.mouse_move(float(x), float(y))
        await _drive(3)
        await uitesting.mouse_click(float(x), float(y))
        await _drive(args.pick_wait_frames)

    async def _drag(candidate: dict[str, Any]) -> None:
        px, py = candidate["press"]
        rx, ry = candidate["release"]
        await uitesting.mouse_move(float(px), float(py))
        await _drive(4)
        await uitesting.mouse_drag(float(px), float(py), float(rx), float(ry), button=0, steps=16)
        await _drive(30)

    # ── orchestration ────────────────────────────────────────────────────────

    async def _main() -> None:
        Application._instance = None
        SelectionBus._instance = None
        app = Application()
        install_preconstructed_renderer(app, bootstrap)
        app._running = True
        app._startup_usd_path = str(args.scene)
        task = asyncio.ensure_future(app.run_async())
        try:
            await _drive(args.warmup_frames)
            warmup_done.set()
            if task.done():
                task.result()  # surface a startup exception
            provider = getattr(app, "_adapter_provider", None)
            state["provider"] = getattr(provider, "name", None)
            renderer = getattr(getattr(app, "_viewport_window", None), "_renderer", None)
            state["renderer_class"] = type(renderer).__name__ if renderer else None
            viewport = getattr(app, "_viewport_window", None)
            performance_start_count = int(
                getattr(renderer, "_successful_frame_count", 0) or 0
            )
            performance_started = time.perf_counter()
            performance_duration = max(float(args.performance_seconds), 0.0)
            while time.perf_counter() - performance_started < performance_duration:
                await ui.next_frame()
            performance_elapsed = time.perf_counter() - performance_started
            performance_end_count = int(
                getattr(renderer, "_successful_frame_count", 0) or 0
            )
            performance_frames = max(
                performance_end_count - performance_start_count,
                0,
            )
            measured_fps = (
                performance_frames / performance_elapsed
                if performance_elapsed > 0.0
                else 0.0
            )
            state["performance"] = {
                "elapsed_seconds": performance_elapsed,
                "rendered_frames": performance_frames,
                "measured_fps": measured_fps,
                "hud_fps": getattr(viewport, "_last_fps", None),
                "target_fps": float(
                    getattr(type(viewport), "MAX_FPS_FOREGROUND", 60.0)
                ),
                "minimum_fps": float(args.min_fps),
            }
            if measured_fps < float(args.min_fps):
                state["errors"].append(
                    {
                        "phase": "performance",
                        "error": (
                            f"measured {measured_fps:.2f} FPS, below "
                            f"the required {float(args.min_fps):.2f} FPS"
                        ),
                    }
                )
            adapter_session = getattr(app, "_adapter_session", None)
            scene = getattr(adapter_session, "current_scene", None)
            native_renderer = getattr(renderer, "_renderer", None)
            attach_mode = getattr(getattr(native_renderer, "config", None), "attach_mode", None)
            borrow_mode = getattr(getattr(renderer, "_ovrtx", None), "AttachMode", None)
            borrow_mode = getattr(borrow_mode, "BORROW", None)
            borrow_contract = {
                "attach_mode": getattr(attach_mode, "value", attach_mode),
                "expected_attach_mode": getattr(borrow_mode, "value", borrow_mode),
                "attached_exact_stage": (
                    getattr(renderer, "_attached_stage", None)
                    is getattr(scene, "_stage", None)
                ),
                "attached_step_count": int(
                    getattr(renderer, "_borrow_step_count", 0) or 0
                ),
                "selection_membership_write_count": int(
                    getattr(renderer, "_selection_outline_attribute_writes", 0) or 0
                ),
            }
            state["borrow_contract"] = borrow_contract
            if state["provider"] != "ovstage":
                state["errors"].append(
                    {"phase": "borrow_contract", "error": "ovstage provider is not active"}
                )
            if state["renderer_class"] != "OvstageRendererAdapter":
                state["errors"].append(
                    {"phase": "borrow_contract", "error": "ovstage renderer adapter is not active"}
                )
            if attach_mode != borrow_mode:
                state["errors"].append(
                    {"phase": "borrow_contract", "error": "OVRTX attach mode is not BORROW"}
                )
            if not borrow_contract["attached_exact_stage"]:
                state["errors"].append(
                    {"phase": "borrow_contract", "error": "OVRTX did not attach the provider OVStage"}
                )
            if borrow_contract["attached_step_count"] <= 0:
                state["errors"].append(
                    {"phase": "borrow_contract", "error": "no attached Renderer.step call was observed"}
                )
            if borrow_contract["selection_membership_write_count"] != 0:
                state["errors"].append(
                    {
                        "phase": "borrow_contract",
                        "error": "unsupported selection membership writes were observed",
                    }
                )
            # Now that the provider has resolved the runtime, record which
            # ovstage / ovrtx packages actually loaded (file + version).
            state["runtime_modules"] = {
                name: _module_info(name) for name in ("ovstage", "ovrtx")
            }
            _capture("initial")

            picked: Optional[str] = None
            for x, y in _pick_candidates(app):
                await _click(x, y)
                paths = _selection_paths(app)
                last = getattr(renderer, "_last_pick_path", None)
                selected = str(paths[0]) if paths else ""
                last_path = str(last or "")
                expected = str(args.prim_path or "")
                if (
                    selected
                    and selected == last_path
                    and (not expected or selected == expected)
                ):
                    picked = selected
                    state["pick"] = {"ok": True, "click": [x, y], "selected_path": picked}
                    break
            if picked is None:
                state["pick"] = {
                    "ok": False,
                    "expected_path": str(args.prim_path or ""),
                    "selected_paths": _selection_paths(app),
                    "renderer_path": getattr(renderer, "_last_pick_path", None),
                }
                state["errors"].append(
                    {
                        "phase": "pick",
                        "error": "no real mouse click selected the requested prim",
                    }
                )
                return
            await _drive(20)
            _capture("after_pick")

            if args.no_drag:
                state["drag"] = {"skipped": True}
                return

            before = _local_translation(app, picked)
            state["transform_before_drag"] = before
            state["ordinal_before_drag"] = getattr(scene, "current_ordinal", None)
            projection = _handle_projection(app)
            moved = False
            for candidate in _drag_candidates(app, projection):
                await _drag(candidate)
                after = _local_translation(app, picked)
                if before is not None and after is not None and any(
                    abs(after[i] - before[i]) > 1e-5 for i in range(3)
                ):
                    state["drag"] = {
                        "ok": True,
                        "candidate": _json_safe(candidate),
                        "before": before,
                        "after": after,
                        "delta": [after[i] - before[i] for i in range(3)],
                    }
                    moved = True
                    state["ordinal_after_drag"] = getattr(scene, "current_ordinal", None)
                    before_ordinal = state.get("ordinal_before_drag")
                    after_ordinal = state.get("ordinal_after_drag")
                    if (
                        before_ordinal is not None
                        and after_ordinal is not None
                        and int(after_ordinal) <= int(before_ordinal)
                    ):
                        state["errors"].append(
                            {
                                "phase": "drag",
                                "error": "OVStage ordinal did not advance after transform",
                            }
                        )
                    break
            _capture("after_drag")
            if not moved:
                state["drag"] = {"ok": False, "before": before, "after": _local_translation(app, picked)}
                state["errors"].append({"phase": "drag", "error": "transform did not change after real mouse drag"})
        finally:
            warmup_done.set()
            app._running = False
            try:
                await asyncio.wait_for(task, timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
            except Exception:
                pass
            try:
                app.shutdown()
            except Exception as exc:
                state["errors"].append(
                    {
                        "phase": "shutdown",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            (state_dir / f"{label}.json").write_text(
                json.dumps(_json_safe(state), indent=2, sort_keys=True), encoding="utf-8"
            )
            try:
                loop = asyncio.get_running_loop()
                loop.call_soon(loop.stop)
            except RuntimeError:
                pass

    layout_root = out_dir / "trial_layouts" / label
    layout_root.mkdir(parents=True, exist_ok=True)
    old_cwd = os.getcwd()
    try:
        os.chdir(layout_root)
        write_split_ini()
        try:
            ui.init(f"ovui kit ovstage smoke {label}", width=args.width, height=args.height, max_fps=None)
        except TypeError:
            ui.init(f"ovui kit ovstage smoke {label}", width=args.width, height=args.height)
        apply_global_styles()
        set_theme("dark")
        ui.run(_main())
    finally:
        os.chdir(old_cwd)
    return state


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Kit ovstage/ovrtx render + real-mouse pick/drag smoke for ovui.",
    )
    parser.add_argument("--out-dir", required=True, help="Directory for screenshots + state JSON.")
    parser.add_argument("--label", default="kit_ovstage_smoke", help="Artifact label / filename stem.")
    parser.add_argument("--scene", default=str(_DEFAULT_SCENE), help="USD/ovstage scene to open.")
    parser.add_argument(
        "--prim-path",
        default=_DEFAULT_PRIM,
        help="Prim to pick/move (empty string = use scene-bounds centre).",
    )
    parser.add_argument("--kit-root", default=None, help="Kit checkout root (else $KIT_ROOT).")
    parser.add_argument("--ovstage-root", default=None, help="Override OVSTAGE_ROOT.")
    parser.add_argument("--ovrtx-root", default=None, help="Override OVRTX_ROOT.")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--warmup-frames", type=int, default=240, help="Frames to drive before measuring.")
    parser.add_argument(
        "--performance-seconds",
        type=float,
        default=3.0,
        help="Steady-state seconds over which to count successful viewport renders.",
    )
    parser.add_argument(
        "--min-fps",
        type=float,
        default=0.0,
        help="Fail when measured viewport FPS is below this value (0 disables the gate).",
    )
    parser.add_argument("--pick-wait-frames", type=int, default=120, help="Frames to settle after a click.")
    parser.add_argument(
        "--first-frame-timeout",
        type=float,
        default=300.0,
        help="Seconds to allow for the first render frame (shader warmup).",
    )
    parser.add_argument("--no-drag", action="store_true", help="Stop after pick (skip the drag stage).")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    env_info = _configure_environment(args)
    try:
        state = run_smoke(args, env_info)
    except Exception:
        import traceback

        out_dir = Path(args.out_dir)
        (out_dir / "state").mkdir(parents=True, exist_ok=True)
        (out_dir / "state" / f"{args.label}.json").write_text(
            json.dumps(
                {"label": args.label, "errors": [{"phase": "fatal", "error": traceback.format_exc()}]},
                indent=2,
            ),
            encoding="utf-8",
        )
        print(traceback.format_exc(), file=sys.stderr)
        return 2
    errors = state.get("errors") or []
    print(f"STATE_JSON={Path(args.out_dir) / 'state' / (args.label + '.json')}", flush=True)
    performance = state.get("performance") or {}
    if "measured_fps" in performance:
        print(f"MEASURED_FPS={float(performance['measured_fps']):.2f}", flush=True)
    if errors:
        print(f"SMOKE FAILED: {len(errors)} error(s)", file=sys.stderr)
        return 2
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
