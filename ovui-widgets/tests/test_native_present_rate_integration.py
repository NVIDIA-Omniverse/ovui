# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Native pacing and its public fallback across a real product session.

A normal launch — the same bootstrap/``run(usd_path=...)`` sequence as
``ovui_widgets.app.__main__`` — must leave the viewport's own renderer owning
an active native pacing session when a provider is installed, and
the HUD showing actual rendered-content updates rather than its placeholder.
These fail if the product stops requesting native max-throughput at startup,
if adapter session registration or activation breaks, if a low UI rate
implicitly caps renderer presentation, or if an explicit presentation disable
gets overridden.

Each session runs in its own process and its own temporary directory:
``omni.ui`` initialises once per process, so an in-process version would
inherit whatever backend an earlier test installed, and a real launch writes
UI layout/settings state that must not reach the source tree or a user
profile.

Tests requiring a native pacing provider skip when none is installed; the
public release renders through the UI tick and exercises that fallback below.
OpenUSD integration also skips when its optional ``pxr`` package is absent.
Missing hardware or platform also skips: no display, no windowed Vulkan
standalone backend, or no CUDA-capable GPU behind it. On a capable host, a
renderer runtime that fails to import, an installed provider that is refused
or crashes, or a session that fails to establish or activate fails the test.
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCENE = Path(__file__).parent / "data" / "simple_scene.usda"
_CONTINUITY_WORKLOAD = {
    "omni:rtx:rt:directLighting:samples": 32,
    "omni:rtx:rt:indirectdiffuse:samples": 16,
    "omni:rtx:rt:reflections:samples": 16,
    "omni:rtx:shadows:sampleCount": 32,
}

# The hardware and platform question only: a display, a windowed Vulkan
# standalone backend and CUDA import of Vulkan memory, i.e. a real GPU. It loads
# no renderer and no optional package, so a software fault cannot make it say
# "no". Only a "no" from here may skip a test.
_HARDWARE = """
import ctypes
import ctypes.util
import os
import sys
os.environ["OMNIUI_BACKEND"] = "vulkan"
os.environ.pop("OMNIUI_HEADLESS", None)
# A host without a Vulkan loader lacks the platform: ovui's standalone module
# links it and cannot even be imported. Ask the operating system directly, so
# that only that case - not any other import failure - reads as "no".
try:
    if os.name == "nt":
        ctypes.WinDLL("vulkan-1.dll")
    else:
        ctypes.CDLL(ctypes.util.find_library("vulkan") or "libvulkan.so.1")
except OSError as exc:
    print("NO_VULKAN_LOADER", exc)
    sys.exit(0)
import omni.ui as ui
try:
    ui.init("hardware", width=64, height=64, max_fps=60.0, present_fps=60.0)
except RuntimeError as exc:
    print("NO_WINDOWED_VULKAN", exc)
else:
    print("CAPABLE", ui.get_present_rate())
    # Whether this host can import exported memory into CUDA at all. Asked in
    # a process with no pacing session and no native render thread, so it is
    # the host's property and cannot be perturbed by - or confused with - the
    # in-session publication behaviour a test then asserts.
    print("GPU_UPLOAD", bool(ui.has_gpu_byte_image()))
    # Whether the driver has a CUDA device, which the renderer needs. A GPU
    # partition can have one without the memory import above; a software
    # rasteriser has none.
    try:
        cuda = ctypes.WinDLL("nvcuda.dll") if os.name == "nt" else ctypes.CDLL("libcuda.so.1")
        count = ctypes.c_int(0)
        devices = count.value if cuda.cuInit(0) == 0 and cuda.cuDeviceGetCount(ctypes.byref(count)) == 0 else 0
    except OSError:
        devices = 0
    print("CUDA_DEVICES", devices)
"""

# The software the tests need, on a host the hardware probe accepted: the
# provider's renderer runtime and adapter stack, and an installed package that
# fills ovui's renderer slot, installed the way the application does it. Any
# failure here - an import error, a refused table, a crash - fails the test.
_CAPABILITY = """
import importlib, os, sys
os.environ["OMNIUI_BACKEND"] = "vulkan"
os.environ.pop("OMNIUI_HEADLESS", None)
for module in sys.argv[1:]:
    importlib.import_module(module)
import omni.ui as ui
# ovui itself holds no renderer call. An optional package fills its renderer
# slot before ui.init, exactly as the application does; without that package
# there is no native pacing to assert and this host is not capable.
from ovui_widgets.app.native_runtime_bootstrap import install_native_frame_pacing_hooks
install_native_frame_pacing_hooks()
ui.init("capability", width=64, height=64, max_fps=60.0, present_fps=60.0)
print("CAPABLE", ui.get_present_rate())
print("PACING_HOOKS", bool(ui.get_frame_pacing_status()["supported"]))
from importlib.metadata import entry_points
print("PACING_PROVIDERS", len(tuple(entry_points(group="ovui_widgets.native_pacing"))))
print("CAPABILITY_DONE")
"""

_SESSION = r"""
import json, os, sys, threading, time
from pathlib import Path

provider, scene, mode, render_policy = sys.argv[1:5]
if mode in {"fallback", "on_change_sync"}:
    # A public install: no package publishes a renderer table. Hide any that
    # this environment has, at the one place the application looks for them.
    import ovui_widgets.app.native_runtime_bootstrap as _bootstrap
    _real_entry_points_for = _bootstrap._entry_points_for
    _bootstrap._entry_points_for = lambda group: (
        () if group == _bootstrap._NATIVE_PACING_ENTRY_POINT_GROUP
        else _real_entry_points_for(group)
    )
os.environ["OVUI_DATA_ADAPTER_PROVIDER"] = provider
os.environ["OVUI_WIDGETS_REQUIRE_OVRTX"] = "1"
os.environ["OVRTX_SKIP_USD_CHECK"] = "1"
os.environ.pop("OMNIUI_BACKEND", None)   # ordinary launch selects its own
os.environ["OVGEAR_LIVESTREAM"] = "0"
os.environ.pop("OMNIUI_HEADLESS", None)
os.environ.pop("OMNIUI_RENDER_FLOW_MODE", None)

# Same launch sequence as ovui_widgets.app.__main__.
from ovui_widgets.app.native_runtime_bootstrap import (
    install_preconstructed_renderer,
    preconstruct_selected_native_renderer,
)

bootstrap = preconstruct_selected_native_renderer()

import omni.ui as ui
import ovui_widgets.app.application as application_module
from ovui_widgets.app.application import Application

KEY = Application.RATE_LIMIT_FPS_SETTING_KEY
app = Application()
install_preconstructed_renderer(app, bootstrap)
if render_policy:
    app.settings.set("app.renderer.renderPolicy", render_policy)

out = {"application_module": application_module.__file__, "cwd": os.getcwd()}
state = {"phase": "await_session"}
deadline = time.monotonic() + 120.0
original = app._on_native_pacing_frame_update


def _renderer():
    window = getattr(app, "_viewport_window", None)
    return getattr(window, "_renderer", None)


def _hud():
    window = getattr(app, "_viewport_window", None)
    surface = getattr(window, "_viewport", None) or window
    snapshot = surface._build_hud_state_snapshot()
    return {"fps": snapshot.fps, "render_fps": snapshot.render_fps,
            "fps_text": snapshot.fps_text}


CONTINUITY_WORKLOAD = {
    "omni:rtx:rt:directLighting:samples": 32,
    "omni:rtx:rt:indirectdiffuse:samples": 16,
    "omni:rtx:rt:reflections:samples": 16,
    "omni:rtx:shadows:sampleCount": 32,
}


def _apply_continuity_workload(renderer):
    active_path = renderer.get_active_render_product_path()
    catalog = renderer.list_render_settings(active_path)
    descriptors = {
        str(item.metadata.get("attr_name") or ""): item
        for item in catalog.settings
    }
    applications = []
    for attr_name, value in CONTINUITY_WORKLOAD.items():
        descriptor = descriptors[attr_name]
        applied = renderer.apply_render_setting(
            descriptor.setting_id,
            value,
            render_product_path=active_path,
        )
        applications.append({
            "attr_name": attr_name,
            "value": value,
            "accepted": bool(getattr(applied, "accepted", False)),
        })
    return active_path, applications


def _presentation_counter_gap(status):
    # Sampling is concurrent with native submission.  The platform counter is
    # process-wide while pacing totals restart with a new owned session, so
    # compare the gap at both ends of each interval rather than the totals.
    total = int(status.get("total_presents") or 0)
    return (
        int(status.get("present_submit_successes") or 0) - total,
        int(status.get("window_presents") or 0) - total,
    )


def _observe_explicit_off():
    off_deadline = time.monotonic() + 10.0
    while time.monotonic() < off_deadline:
        settled = ui.get_frame_pacing_status()
        if (settled.get("active") is False and
                int(settled.get("session_token") or 0) == 0):
            out["after_off"] = {
                "active": False,
                "session_token": 0,
                "hud": _hud(),
            }
            app.request_exit()
            return
        time.sleep(0.01)
    out["off_timed_out_status"] = {
        "active": bool(settled.get("active")),
        "session_token": int(settled.get("session_token") or 0),
    }
    app.request_exit()


def observe(dt):
    original(dt)
    state["ui_updates"] = state.get("ui_updates", 0) + 1
    now = time.monotonic()
    status = ui.get_frame_pacing_status()
    phase = state["phase"]

    if now > deadline:
        out["timed_out_in"] = phase
        out["last_status"] = {k: status.get(k) for k in (
            "active", "session_token", "status_reason", "supported",
            "real_render_completions", "selected_viewport_content_changes",
            "last_error")}
        state["phase"] = "done"
    elif mode == "fallback" and phase == "await_session":
        # Without a renderer table there is no session to wait for. Let the
        # scene load, then measure the ordinary UI-tick presentation.
        start = state.setdefault("fallback_start", now)
        if now - start >= 8.0:
            state["fallback_t0"] = now
            state["fallback_c0"] = int(status.get("renderer_completions") or 0)
            state["fallback_u0"] = state["ui_updates"]
            state["phase"] = "fallback_measure"
    elif mode == "on_change_sync" and phase == "await_session":
        # No renderer table: the viewport renders through render_frame. Wait
        # for the scene and its first frames, as the fallback mode does.
        start = state.setdefault("sync_start", now)
        if now - start >= 8.0 and int(status.get("renderer_completions") or 0) > 0:
            state["phase"] = "still_wait"
    elif phase == "fallback_measure":
        if now - state["fallback_t0"] >= 2.0:
            out["fallback"] = {
                "supported": bool(status.get("supported")),
                "active": bool(status.get("active")),
                "status_reason": status.get("status_reason"),
                "last_error": status.get("last_error"),
                "completions_delta": int(status.get("renderer_completions") or 0)
                - state["fallback_c0"],
                "ui_updates": state["ui_updates"] - state["fallback_u0"],
                "elapsed": now - state["fallback_t0"],
                "hud": _hud(),
            }
            state["phase"] = "done"
    elif phase == "await_session":
        if status.get("active") and int(status.get("session_token") or 0):
            renderer = _renderer()
            out["session"] = {
                "session_token": int(status.get("session_token") or 0),
                "renderer_token": int(
                    getattr(renderer, "_frame_pacing_token", 0) or 0),
                "renderer_class": type(renderer).__name__,
                "present_rate": float(status.get("present_rate") or 0.0),
                "backend": status.get("backend"),
                "present_policy": status.get("present_policy"),
                "active_present_mode": status.get("active_present_mode"),
            }
            state["t0"] = now
            state["c0"] = int(status.get("renderer_completions") or 0)
            state["u0"] = int(status.get("selected_content_changes") or 0)
            state["v0"] = int(
                status.get("selected_viewport_image_changes") or 0
            )
            state["p0"] = int(status.get("present_submit_successes") or 0)
            state["t_present0"] = int(status.get("total_presents") or 0)
            state["repeat0"] = int(status.get("repeated_presents") or 0)
            # Totals, not deltas: a capable path must never take the host
            # route, so any host publication at all — including one raced in
            # during startup before the capability answer was ready — is a
            # failure rather than something a later window can hide.
            out["gpu_publications_total"] = int(
                status.get("gpu_resident_publications") or 0)
            out["host_publications_total"] = int(
                status.get("host_fallback_publications") or 0)
            state["phase"] = "accumulate"
    elif phase == "accumulate":
        if now - state["t0"] >= 2.0:
            out["baseline_elapsed"] = now - state["t0"]
            out["completions_delta"] = (
                int(status.get("renderer_completions") or 0) - state["c0"])
            out["render_updates_delta"] = int(
                status.get("selected_content_changes") or 0
            ) - state["u0"]
            out["viewport_changes_delta"] = int(
                status.get("selected_viewport_image_changes") or 0
            ) - state["v0"]
            out["present_successes_delta"] = int(
                status.get("present_submit_successes") or 0
            ) - state["p0"]
            out["total_presents_delta"] = int(
                status.get("total_presents") or 0
            ) - state["t_present0"]
            out["repeated_presents_delta"] = int(
                status.get("repeated_presents") or 0
            ) - state["repeat0"]
            out["baseline_present_rate"] = float(
                status.get("present_rate") or 0.0
            )
            out["gpu_publications_total"] = int(
                status.get("gpu_resident_publications") or 0)
            out["host_publications_total"] = int(
                status.get("host_fallback_publications") or 0)
            out["hud"] = _hud()
            if mode == "edit":
                state["phase"] = "create_cube"
            elif mode == "full":
                state["phase"] = "low_ui"
            elif mode == "positive":
                state["positive_t0"] = now
                state["positive0"] = {
                    key: int(status.get(key) or 0)
                    for key in (
                        "real_render_completions",
                        "selected_viewport_image_changes",
                        "present_submit_successes",
                        "total_presents",
                        "renderer_timestamp_intervals",
                        "renderer_timestamp_interval_total_nanoseconds",
                        "dropped_images",
                        "repeated_presents",
                        "renderer_frame_order_violations",
                        "renderer_timestamp_order_violations",
                    )
                }
                out["positive_request_accepted"] = bool(
                    ui.set_present_rate(15.0)
                )
                state["phase"] = "positive_accumulate"
            elif mode == "hidden_tab":
                state["phase"] = "hide"
            elif mode == "restarts":
                state["restart_token"] = out["session"]["session_token"]
                state["phase"] = "restart"
            elif mode == "material_verify":
                state["phase"] = "verify_steady"
            elif mode == "on_change":
                # The still checks start after the outline pass restarted
                # the session (see verify_steady).
                state["after_steady"] = "still_wait"
                state["phase"] = "verify_steady"
            else:
                state["phase"] = "done"
    elif phase == "still_wait":
        # The on_change policy renders a change and its settle frames, then
        # stops. Wait until no frame came for 1.5 s.
        render_key = (int(status.get("session_token") or 0),
                      int(status.get("renderer_completions") or 0))
        if render_key != state.get("still_key"):
            state["still_key"], state["still_since"] = render_key, now
        elif now - state["still_since"] >= 1.5:
            state["still_t0"] = now
            state["phase"] = "still_measure"
    elif phase == "still_measure":
        if now - state["still_t0"] >= 2.0:
            token, completions = state["still_key"]
            out.setdefault("still", []).append({
                "same_session": int(status.get("session_token") or 0) == token,
                "completions_delta": int(status.get("renderer_completions") or 0) - completions,
                "hud": _hud(),
            })
            if len(out["still"]) == 1:
                # A stage edit must render again.
                from ovui_widgets.app.create_menu import create_shape_prim
                assert create_shape_prim(app, "Cube") is not None, "Create Shape Cube failed"
                state["change_t0"] = now
                state["phase"] = "change_wait"
            elif mode == "on_change":
                state["phase"] = "verify_steady"
            else:
                state["phase"] = "verify_start"
    elif phase == "change_wait":
        render_key = (int(status.get("session_token") or 0),
                      int(status.get("renderer_completions") or 0))
        if render_key[0] != state["still_key"][0] or render_key[1] > state["still_key"][1]:
            out["change_rendered_after"] = now - state["change_t0"]
            state["phase"] = "still_wait"
    elif phase == "verify_steady":
        # The OpenUSD adapter starts its selection outline pass once, when the
        # viewport is idle after start-up; that pass resets the renderer and
        # restarts the session with one Python frame. The command is called
        # after it, in steady native pacing, where no frame comes through the
        # Python step.
        renderer = _renderer()
        if (getattr(renderer, "_selection_outline_armed", True)
                and not getattr(renderer, "_selection_outline_pass_needs_reset", False)
                and getattr(renderer, "_outline_pass_settle_after", None) is None
                and status.get("active") and int(status.get("session_token") or 0)
                and int(getattr(renderer, "_frame_pacing_token", 0) or 0)):
            out["verify_steady_after"] = now - state["t0"]
            state["phase"] = state.pop("after_steady", "verify_start")
    elif phase == "verify_start":
        # The render diagnostics command material_verify, as the Inspector
        # runs it: a coroutine on the application's loop that asks the
        # viewport's renderer for a check at its next frame and waits.
        import asyncio
        from ovui_data_adapters.common.render_diagnostics_service import (
            RenderDiagnosticsService,
            application_renderer,
            application_stage,
        )
        service = RenderDiagnosticsService(
            lambda: application_stage(app), lambda: application_renderer(app))
        out["verify_token_before"] = int(status.get("session_token") or 0)
        out["verify_active_before"] = bool(status.get("active"))
        state["verify_t0"] = now
        state["verify_task"] = asyncio.get_running_loop().create_task(
            service.verify(timeout=60.0))
        state["phase"] = "verify_wait"
    elif phase == "verify_wait":
        task = state["verify_task"]
        if task.done():
            out["verify_seconds"] = now - state["verify_t0"]
            if task.exception() is not None:
                error = task.exception()
                out["verify_error"] = f"{type(error).__name__}: {error}"
            else:
                result = task.result()
                out["verify"] = {key: result[key] for key in (
                    "mode", "counts", "mismatches", "failures")}
            state["verify_after_t0"] = now
            # Without native pacing there is no session to draw again.
            state["phase"] = "done" if mode == "on_change_sync" else "verify_after"
    elif phase == "verify_after":
        # Native frame pacing draws the viewport again after the check.
        token = int(status.get("session_token") or 0)
        if status.get("active") and token:
            out["verify_after"] = {
                "session_token": token,
                "renderer_token": int(
                    getattr(_renderer(), "_frame_pacing_token", 0) or 0),
            }
            state["phase"] = "done"
        elif now - state["verify_after_t0"] > 20.0:
            out["verify_after"] = {"session_token": 0, "renderer_token": 0}
            state["phase"] = "done"
    elif phase == "positive_accumulate":
        if now - state["positive_t0"] >= 4.0:
            out["positive_elapsed"] = now - state["positive_t0"]
            out["positive_effective_present_rate"] = float(
                status.get("present_rate") or 0.0
            )
            out["positive_deltas"] = {
                key: int(status.get(key) or 0) - state["positive0"][key]
                for key in state["positive0"]
            }
            state["phase"] = "continuity_apply"
    elif phase == "continuity_apply":
        renderer = _renderer()
        active_path, applications = _apply_continuity_workload(renderer)
        out["continuity_workload"] = {
            "active_path": active_path,
            "applications": applications,
        }
        state["continuity_path"] = active_path
        state["phase"] = "continuity_await"
    elif phase == "continuity_await":
        renderer = _renderer()
        readbacks = {
            attr_name: renderer.read_render_setting_value(
                attr_name,
                render_product_path=state["continuity_path"],
            )
            for attr_name in CONTINUITY_WORKLOAD
        }
        if status.get("active") and readbacks == CONTINUITY_WORKLOAD:
            out["continuity_workload"]["readbacks"] = readbacks
            app.settings.set(KEY, 120)
            state["continuity_warmup_t0"] = now
            state["phase"] = "continuity_warmup"
    elif phase == "continuity_warmup":
        if now - state["continuity_warmup_t0"] >= 2.0:
            gap = _presentation_counter_gap(status)
            if state.get("continuity_candidate_gap") != gap:
                state["continuity_candidate_gap"] = gap
                return
            state["continuity_counter_gap0"] = gap
            state["continuity_t0"] = now
            state["continuity0"] = {
                key: int(status.get(key) or 0)
                for key in (
                    "ui_geometry_generations",
                    "real_render_completions",
                    "generated_images",
                    "selected_viewport_image_changes",
                    "present_submit_successes",
                    "total_presents",
                    "repeated_presents",
                    "window_presents",
                    "completed_frame_groups",
                    "dropped_images",
                    "replaced_frame_groups",
                    "renderer_frame_order_violations",
                    "renderer_timestamp_order_violations",
                    "errors",
                )
            }
            state["phase"] = "continuity_measure"
    elif phase == "continuity_measure":
        if (now - state["continuity_t0"] >= 4.0
                and _presentation_counter_gap(status)
                == state["continuity_counter_gap0"]):
            out["continuity_elapsed"] = now - state["continuity_t0"]
            out["continuity_deltas"] = {
                key: int(status.get(key) or 0) - state["continuity0"][key]
                for key in state["continuity0"]
            }
            state["pause_entry0"] = {
                key: int(status.get(key) or 0)
                for key in (
                    "ui_geometry_generations",
                    "real_render_completions",
                    "generated_images",
                    "selected_viewport_image_changes",
                    "present_submit_successes",
                    "total_presents",
                    "repeated_presents",
                    "window_presents",
                    "completed_frame_groups",
                    "dropped_images",
                    "replaced_frame_groups",
                    "ownership_generation",
                    "renderer_frame_order_violations",
                    "renderer_timestamp_order_violations",
                    "errors",
                )
            }
            # Hiding the real viewport is a supported user-facing pause. Its
            # production visibility callback suspends native viewport work and
            # returns whole-window presentation to the ordinary UI pump.
            app._viewport_window.visible = False
            state["phase"] = "pause_await"
    elif phase == "pause_await":
        if status.get("render_paused"):
            selected = int(status.get("selected_viewport_image_changes") or 0)
            if state.get("pause_candidate_selected") != selected:
                state["pause_candidate_selected"] = selected
                return
            state["pause_t0"] = now
            state["pause_ui_updates0"] = state["ui_updates"]
            state["pause0"] = {
                key: int(status.get(key) or 0)
                for key in state["pause_entry0"]
            }
            state["pause_ownership_generation_delta"] = (
                state["pause0"]["ownership_generation"]
                - state["pause_entry0"]["ownership_generation"]
            )
            state["phase"] = "pause_measure"
    elif phase == "pause_measure":
        if (now - state["pause_t0"] >= 1.5
                and status.get("render_paused")):
            out["pause_elapsed"] = now - state["pause_t0"]
            out["pause_app_ui_updates"] = (
                state["ui_updates"] - state["pause_ui_updates0"]
            )
            out["pause_ownership_generation_delta"] = state[
                "pause_ownership_generation_delta"
            ]
            out["pause_deltas"] = {
                key: int(status.get(key) or 0) - state["pause0"][key]
                for key in state["pause0"]
            }
            out["pause_final"] = {
                "active": bool(status.get("active")),
                "render_paused": bool(status.get("render_paused")),
                "render_loop_fatal": bool(status.get("render_loop_fatal")),
                "last_error": str(status.get("last_error") or ""),
            }
            state["phase"] = "done"
    elif phase == "hide":
        # Hide the viewport the way a user does: dock another window into
        # its node as a tab and select that tab. The viewport window stays
        # open, so pacing stays active while its image is absent.
        viewport = ui.Workspace.get_window("Viewport")
        other = ui.Workspace.get_window("Property Inspector")
        other.dock_in(viewport, ui.DockPosition.SAME)
        other.focus()
        state["phase"] = "await_hidden"
    elif phase == "await_hidden":
        viewport = ui.Workspace.get_window("Viewport")
        other = ui.Workspace.get_window("Property Inspector")
        if (viewport.dock_id and other.dock_id == viewport.dock_id and
                other.is_selected_in_dock() and
                not viewport.is_selected_in_dock()):
            state.setdefault("hidden_seen", now)
        # Let a present that was in flight at the tab change land first.
        if "hidden_seen" in state and now - state["hidden_seen"] >= 0.5:
            state["hidden_t0"] = now
            state["hidden_w0"] = int(status.get("window_presents") or 0)
            state["phase"] = "hidden_accumulate"
    elif phase == "hidden_accumulate":
        if now - state["hidden_t0"] >= 2.0:
            out["hidden"] = {
                "active": bool(status.get("active")),
                "session_token": int(status.get("session_token") or 0),
                "window_presents_delta": int(
                    status.get("window_presents") or 0) - state["hidden_w0"],
            }
            ui.Workspace.get_window("Viewport").focus()
            state["phase"] = "await_shown"
    elif phase == "await_shown":
        if ui.Workspace.get_window("Viewport").is_selected_in_dock():
            state["shown_t0"] = now
            state["shown_p0"] = int(
                status.get("presented_renderer_frames") or 0)
            state["phase"] = "shown_accumulate"
    elif phase == "shown_accumulate":
        if now - state["shown_t0"] >= 2.0:
            out["shown"] = {
                "active": bool(status.get("active")),
                "session_token": int(status.get("session_token") or 0),
                "presented_renderer_frames_delta": int(
                    status.get("presented_renderer_frames") or 0
                ) - state["shown_p0"],
            }
            state["phase"] = "done"
    elif phase == "restart":
        # A selection change stops the session; the next frame starts a new one.
        paths = ["/World/Cube", "/World/Sphere"]
        _renderer().set_selection_highlight([paths[len(out.get("restarts", [])) % 2]])
        state["phase"] = "await_restart"
    elif phase == "await_restart":
        token = int(status.get("session_token") or 0)
        if (status.get("active") and token > state["restart_token"] and
                int(status.get("presented_renderer_frames") or 0) > 0):
            state["restart_token"] = token
            out.setdefault("restarts", []).append({
                "token": token,
                "render": int(status.get("render_worker_thread") or 0),
                "present": int(status.get("present_worker_thread") or 0),
            })
            state["phase"] = "restart" if len(out["restarts"]) < 9 else "done"
    elif phase == "create_cube":
        from ovui_widgets.app.create_menu import create_shape_prim
        assert create_shape_prim(app, "Cube") is not None, "Create Shape Cube failed"
        assert app.undo_manager.can_undo(), "Create Shape Cube did not create an undo entry"
        state["edit_presents"] = int(status.get("presented_renderer_frames") or 0)
        state["edit_token"] = int(status.get("session_token") or 0)
        state["edit_t0"] = now
        state["phase"] = "after_create"
    elif phase in {"after_create", "after_undo"}:
        if now - state["edit_t0"] >= 2.0:
            capture_path = state.get("edit_capture")
            if capture_path is None:
                capture_path = Path.cwd() / f"edit-{len(out.get('edits', []))}-{phase}.png"
                assert ui._ui._schedule_screenshot(str(capture_path)), "framebuffer capture rejected"
                state["edit_capture"] = str(capture_path)
                return
            capture = ui._ui._get_screenshot_result()
            if not capture["done"]:
                return
            assert capture["success"] and capture["path"] == capture_path, capture
            # A Python Stage write restarts the native session, and the
            # presented-frame counter starts again with the new session.
            token = int(status.get("session_token") or 0)
            presented = int(status.get("presented_renderer_frames") or 0)
            if token == state["edit_token"]:
                presented -= state["edit_presents"]
            out.setdefault("edits", []).append({
                "phase": phase,
                "active": bool(status.get("active")),
                "last_error": status.get("last_error"),
                "session_token": token,
                "presented_frames": presented,
                "capture": capture,
            })
            state["edit_capture"] = None
            if phase == "after_create":
                app.undo_manager.undo()
                assert app.undo_manager.can_redo(), "Undo did not undo cube creation"
                state["edit_presents"] = int(status.get("presented_renderer_frames") or 0)
                state["edit_token"] = int(status.get("session_token") or 0)
                state["edit_t0"] = now
                state["phase"] = "after_undo"
            else:
                cycles = len(out["edits"]) // 2
                state["phase"] = "create_cube" if cycles < 3 else "done"
    elif phase == "low_ui":
        app.settings.set(KEY, 20)
        low = ui.get_frame_pacing_status()
        out["present_rate_after_ui20"] = ui.get_present_rate()
        out["ui_rate_after_ui20"] = ui.get_max_frame_rate()
        out["token_after_ui20"] = int(
            ui.get_frame_pacing_status().get("session_token") or 0)
        state["low_t0"] = now
        state["low_ui0"] = state["ui_updates"]
        state["low0"] = {key: int(low.get(key) or 0) for key in (
            "renderer_completions", "selected_renderer_frames",
            "presented_renderer_frames", "present_submit_successes",
            "dropped_images", "repeated_presents",
            "renderer_frame_order_violations",
            "last_selected_renderer_frame_serial",
            "last_presented_renderer_frame_serial")}
        state["phase"] = "low_ui_accumulate"
    elif phase == "low_ui_accumulate":
        if now - state["low_t0"] >= 4.0:
            low = ui.get_frame_pacing_status()
            out["ui20_elapsed"] = now - state["low_t0"]
            out["ui20_updates"] = state["ui_updates"] - state["low_ui0"]
            out["ui20_deltas"] = {
                key: int(low.get(key) or 0) - state["low0"][key]
                for key in state["low0"]
            }
            state["phase"] = "explicit_off"
    elif phase == "explicit_off":
        ui.set_present_rate(0.0)
        app.settings.set(KEY, 90)
        out["rate_after_disable_then_change"] = ui.get_present_rate()
        state["phase"] = "observe_off"
        threading.Thread(target=_observe_explicit_off, daemon=True).start()

    if state["phase"] == "done":
        app.request_exit()


app._on_native_pacing_frame_update = observe
try:
    app.run(usd_path=scene)
finally:
    app.shutdown()
print("RESULT " + json.dumps(out))
"""


# Every child gets the platform setup the test process itself has. On Windows
# Python does not search PATH for the DLLs of an extension module; CI and the
# other ovui tests name the Vulkan loader folder in Vulkan_DLL_DIR and add it
# with os.add_dll_directory, which a child process does not inherit.
_CHILD_PRELUDE = """
import os as _ovui_test_os
if _ovui_test_os.name == "nt" and _ovui_test_os.environ.get("Vulkan_DLL_DIR"):
    _OVUI_TEST_VULKAN_DLL_DIRECTORY = _ovui_test_os.add_dll_directory(
        _ovui_test_os.environ["Vulkan_DLL_DIR"]
    )
"""


def _run(
    script: str, argv: list, timeout: float, workdir: Path
) -> subprocess.CompletedProcess:
    """Run a product subprocess in its own throwaway directory.

    ``Application.run`` writes UI layout state (``imgui.ini``) relative to the
    working directory and persists settings to a user profile, so both are
    redirected into ``workdir``; nothing lands in the source tree or the real
    profile. ``sys.path`` is absolutised first so the package roots selected
    by conftest still apply from the new directory.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        str(Path(entry).resolve()) for entry in sys.path if entry
    )
    env["OVUI_WIDGETS_SETTINGS_PATH"] = str(workdir / "settings.json")
    env.pop("OMNIUI_BACKEND", None)
    env.pop("OMNIUI_HEADLESS", None)
    return subprocess.run(
        [sys.executable, "-c", _CHILD_PRELUDE + script, *argv],
        capture_output=True, text=True, timeout=timeout, env=env,
        cwd=str(workdir),
    )


def _hardware(workdir: Path) -> dict:
    """Whether this host has the hardware and platform these tests need.

    Returns ``{"capable": bool, "gpu_upload": bool, "cuda": bool, "reason": str}``.
    ``capable`` needs the memory import (``gpu_upload``); ``cuda`` says only
    that a windowed backend and a CUDA device are there. A probe that crashes
    is not an answer about hardware, so it fails the test.
    """
    if os.name != "nt" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return {"capable": False, "gpu_upload": False, "reason": "no display"}
    done = _run(_HARDWARE, [], 180, workdir)
    assert done.returncode == 0, (
        f"the hardware probe itself failed ({done.returncode})\n"
        f"stdout:\n{done.stdout[-3000:]}\nstderr:\n{done.stderr[-3000:]}"
    )
    lines = done.stdout.splitlines()
    if any(line.startswith("NO_VULKAN_LOADER") for line in lines):
        return {"capable": False, "gpu_upload": False, "reason": "no Vulkan loader on this host"}
    windowed = any(
        line.startswith("CAPABLE") and float(line.split()[1]) == 60.0
        for line in lines
    )
    gpu_upload = any(line.strip() == "GPU_UPLOAD True" for line in lines)
    cuda = windowed and any(
        line.startswith("CUDA_DEVICES") and int(line.split()[1]) > 0
        for line in lines
    )
    if not windowed:
        return {"capable": False, "gpu_upload": False, "cuda": False,
                "reason": "no windowed Vulkan standalone backend"}
    if not gpu_upload:
        # ovrtx and native pacing need a CUDA device that can import Vulkan
        # memory; a software rasteriser such as lavapipe has none.
        return {"capable": False, "gpu_upload": False, "cuda": cuda,
                "reason": "no CUDA-capable GPU behind Vulkan"}
    return {"capable": True, "gpu_upload": True, "cuda": cuda, "reason": ""}


def _probe(workdir: Path, *runtimes: str) -> dict:
    """What this installation offers on a capable host.

    Fails on any software fault: a probe that exits non-zero (an import error,
    a crash inside a provider), or a provider that ovui refuses. An empty
    provider list is valid for the public release.
    """
    done = _run(_CAPABILITY, list(runtimes), 180, workdir)
    output = (
        f"exit status {done.returncode}\nstdout:\n{done.stdout[-3000:]}\n"
        f"stderr:\n{done.stderr[-3000:]}"
    )
    assert done.returncode == 0 and "CAPABILITY_DONE" in done.stdout, (
        "the renderer runtime, the adapter stack or the package that fills "
        "ovui's renderer slot failed to load on a capable GPU host:\n" + output
    )
    lines = done.stdout.splitlines()
    return {
        "windowed": any(
            line.startswith("CAPABLE") and float(line.split()[1]) == 60.0
            for line in lines
        ),
        "hooks": any(line.strip() == "PACING_HOOKS True" for line in lines),
        "providers": next(
            (int(line.split()[1]) for line in lines if line.startswith("PACING_PROVIDERS")), 0
        ),
        "stdout": output,
    }


def _gpu_upload_capable(workdir: Path, *runtimes: str) -> bool:
    """Host capability, established outside any session under test.

    Deliberately not the in-session capability call: that is the very API whose
    provisional answer is the regression these tests guard, so using it for
    eligibility would let a regressed build skip instead of fail.
    """
    return _hardware(workdir)["gpu_upload"]


def _session(
    tmp_path: Path, provider: str, runtimes: tuple, mode: str, scene: Path = SCENE,
    gpu_upload: bool = True, render_policy: str = "continuous",
) -> dict:
    """One real session. ``gpu_upload=False``: the test needs only a windowed
    backend and a CUDA device; native pacing then publishes through the host.

    ``render_policy`` is the ``app.renderer.renderPolicy`` of the session; an
    empty string keeps the default (``on_change``). The pacing measurements
    need a viewport that renders every frame, so they use ``continuous``: the
    default stops rendering a still picture."""
    if provider == "openusd" and importlib.util.find_spec("pxr") is None:
        pytest.skip("OpenUSD integration requires the optional pxr runtime")
    probe_dir = tmp_path / f"{provider}-probe"
    session_dir = tmp_path / f"{provider}-session"
    probe_dir.mkdir()
    session_dir.mkdir()
    if not scene.exists():
        pytest.fail(f"the test scene is missing: {scene}")
    hardware = _hardware(probe_dir)
    if not (hardware["capable"] if gpu_upload else hardware["cuda"]):
        pytest.skip(hardware["reason"] or "no CUDA device")
    probe = _probe(probe_dir, *runtimes)
    assert probe["windowed"], "the windowed backend the hardware probe found is gone:\n" + probe["stdout"]
    if mode not in {"fallback", "on_change_sync"}:
        if not probe["providers"]:
            pytest.skip("native pacing requires an optional renderer provider")
        assert probe["hooks"], (
            "a package publishes a renderer table for native frame pacing, "
            "but ovui did not accept it:\n" + probe["stdout"]
        )
    done = _run(_SESSION, [provider, str(scene), mode, render_policy], 420, session_dir)
    assert done.returncode == 0, (
        f"{provider} session failed ({done.returncode})\n"
        f"stdout:\n{done.stdout[-3000:]}\nstderr:\n{done.stderr[-3000:]}"
    )
    result = next(
        (l for l in done.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert result is not None, (
        f"{provider} session produced no result\nrc={done.returncode}\n"
        f"stdout:\n{done.stdout[-3000:]}\nstderr:\n{done.stderr[-3000:]}")
    observed = json.loads(result[len("RESULT "):])
    # Match the package selected by conftest: installed wheels or this checkout.
    from ovui_widgets.app import application as application_module

    assert Path(observed["application_module"]).resolve() == Path(
        application_module.__file__
    ).resolve(), observed["application_module"]
    assert Path(observed["cwd"]) == session_dir
    assert "timed_out_in" not in observed, (
        f"{provider} never reached an active owned session: {observed}")
    return observed


def _assert_owned_active_session(observed: dict, provider: str) -> None:
    """The shared default-on outcome: this viewport's renderer owns a live
    session that is really rendering, and the HUD shows presented rendered
    content rather than renderer completion activity."""
    session = observed["session"]
    assert session["session_token"] != 0
    assert session["renderer_token"] == session["session_token"]
    assert session["present_rate"] < 0.0
    assert session["backend"] == "vulkan"
    assert session["present_policy"] == "immediate_preferred"
    assert session["active_present_mode"] in {"IMMEDIATE", "MAILBOX", "FIFO"}
    assert observed["completions_delta"] > 0, "no real OVRTX completions"
    assert observed["render_updates_delta"] > 0, "no rendered-content updates"
    assert observed["baseline_present_rate"] < 0.0
    assert observed["present_successes_delta"] == (
        observed["viewport_changes_delta"]
        + observed["repeated_presents_delta"]
    )
    assert observed["total_presents_delta"] == observed[
        "present_successes_delta"
    ]
    hud = observed["hud"]
    assert hud["render_fps"] is not None and hud["render_fps"] > 0.0
    assert hud["fps_text"].endswith(f"/{hud['render_fps']:.0f}")
    assert not hud["fps_text"].endswith("/-")


def test_openusd_default_launch_owns_an_active_pacing_session(tmp_path):
    """Default-on, plus the live-cap and explicit-off precedence that share
    this one expensive session."""
    observed = _session(
        tmp_path,
        "openusd",
        ("ovrtx", "ovui_data_adapters.openusd.renderer_adapter"),
        "full",
    )
    _assert_owned_active_session(observed, "openusd")
    assert observed["session"]["renderer_class"] == "OvRtxRendererAdapter"

    # The real Kit-compatible UI policy may run at 20 FPS, but it must not
    # mutate native presentation or couple distinct renderer delivery to UI.
    assert observed["present_rate_after_ui20"] < 0.0
    assert observed["ui_rate_after_ui20"] == pytest.approx(20.0)
    assert observed["token_after_ui20"] == observed["session"]["session_token"]
    low = observed["ui20_deltas"]
    assert 15.0 <= observed["ui20_updates"] / observed["ui20_elapsed"] <= 25.0
    assert low["renderer_completions"] > 2 * observed["ui20_updates"]
    assert low["selected_renderer_frames"] >= 0.95 * low["renderer_completions"]
    assert low["presented_renderer_frames"] == low["selected_renderer_frames"]
    assert low["present_submit_successes"] == low["presented_renderer_frames"]
    assert low["last_selected_renderer_frame_serial"] == low["selected_renderer_frames"]
    assert low["last_presented_renderer_frame_serial"] == low["presented_renderer_frames"]
    assert low["dropped_images"] == 0
    assert low["repeated_presents"] == 0
    assert low["renderer_frame_order_violations"] == 0

    # An explicit disable is not resurrected by a later, unrelated cap change,
    # and the HUD goes back to its placeholder rather than a stale number.
    assert observed["rate_after_disable_then_change"] == 0.0
    assert "off_timed_out_status" not in observed, observed.get(
        "off_timed_out_status"
    )
    after_off = observed["after_off"]
    assert after_off["active"] is False
    assert after_off["session_token"] == 0
    assert after_off["hud"]["render_fps"] is None
    assert after_off["hud"]["fps_text"].endswith("/-")


def test_openusd_ui_presents_while_a_dock_tab_hides_the_viewport(tmp_path):
    """While another tab of its dock node hides the viewport, pacing stays
    active but has no viewport image to replay. The platform must then
    present the UI itself, or the OS window keeps an old image while the UI
    still takes input. Selecting the viewport tab again resumes native
    presentation of renderer frames."""
    observed = _session(
        tmp_path,
        "openusd",
        ("ovrtx", "ovui_data_adapters.openusd.renderer_adapter"),
        "hidden_tab",
    )
    _assert_owned_active_session(observed, "openusd")
    # Docking resizes the viewport, which may renew the session token.
    hidden = observed["hidden"]
    assert hidden["active"] is True
    assert hidden["session_token"] != 0
    # About 100 at the default UI rate; zero when the window is not presented.
    assert hidden["window_presents_delta"] >= 10, (
        "no window presentation while a dock tab hid the viewport")
    shown = observed["shown"]
    assert shown["active"] is True
    assert shown["session_token"] != 0
    assert shown["presented_renderer_frames_delta"] > 0


@pytest.mark.requires_ovrtx
@pytest.mark.parametrize("provider", ["openusd"])
def test_create_cube_undo_keeps_native_vulkan_rendering(tmp_path, provider):
    """Three Create/Undo cycles must keep presenting and capturing real frames."""
    runtimes = ("ovrtx", f"ovui_data_adapters.{provider}.renderer_adapter")
    observed = _session(tmp_path, provider, runtimes, "edit")
    _assert_owned_active_session(observed, provider)
    assert len(observed["edits"]) == 6
    for edit in observed["edits"]:
        assert edit["active"] and not edit["last_error"], edit
        assert edit["session_token"] != 0, edit
        assert edit["presented_frames"] > 0, edit
        capture = edit["capture"]
        assert capture["success"] and capture["width"] > 0 and capture["height"] > 0, capture
        with Path(capture["path"]).open("rb") as screenshot:
            assert screenshot.read(8) == b"\x89PNG\r\n\x1a\n", capture


@pytest.mark.requires_ovrtx
def test_session_restarts_reuse_the_pacing_worker_threads(tmp_path):
    """A selection change restarts the pacing session. ovrtx keeps about
    1 MiB of per-thread state for every thread that maps its results, so a
    new render thread per session grew the process on every click (#371).
    The restarted sessions must run on the same worker threads."""
    observed = _session(
        tmp_path,
        "openusd",
        ("ovrtx", "ovui_data_adapters.openusd.renderer_adapter"),
        "restarts",
    )
    _assert_owned_active_session(observed, "openusd")
    restarts = observed["restarts"]
    assert len(restarts) == 9
    # ovui names the thread that renders and the thread that presents each
    # session. All 9 sessions must run on the same two threads.
    assert len({r["token"] for r in restarts}) == 9
    assert {r["render"] for r in restarts} == {restarts[0]["render"]} != {0}, restarts
    assert {r["present"] for r in restarts} == {restarts[0]["present"]} != {0}, restarts
    assert restarts[0]["render"] != restarts[0]["present"]


# Two cubes with flat UsdPreviewSurface colours: the material check can judge both.
_FLAT_MATERIALS_SCENE = """#usda 1.0
(
    defaultPrim = "World"
    upAxis = "Y"
)

def Xform "World"
{
    def DomeLight "Dome"
    {
        float inputs:intensity = 1000
    }

    def Scope "Looks"
    {
        def Material "Red"
        {
            token outputs:surface.connect = </World/Looks/Red/Surface.outputs:surface>

            def Shader "Surface"
            {
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor = (0.8, 0.1, 0.1)
                float inputs:roughness = 0.6
                token outputs:surface
            }
        }

        def Material "Green"
        {
            token outputs:surface.connect = </World/Looks/Green/Surface.outputs:surface>

            def Shader "Surface"
            {
                uniform token info:id = "UsdPreviewSurface"
                color3f inputs:diffuseColor = (0.1, 0.7, 0.2)
                float inputs:roughness = 0.6
                token outputs:surface
            }
        }
    }

    def Cube "RedBox" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        rel material:binding = </World/Looks/Red>
        double size = 2.5
        double3 xformOp:translate = (-2, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }

    def Cube "GreenBox" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        rel material:binding = </World/Looks/Green>
        double size = 2.5
        double3 xformOp:translate = (2, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
}
"""


@pytest.mark.requires_ovrtx
@pytest.mark.parametrize("provider", [
    "openusd",
    pytest.param("ovstage", marks=pytest.mark.requires_ovstage),
])
def test_material_verify_ends_while_native_pacing_draws_the_viewport(tmp_path, provider):
    """Defect: with the renderer package installed, native frame pacing draws
    the viewport and render_frame returns after it publishes the camera, so
    the check that material_verify queued never ran and the command timed out
    after 300 s. The check must run at the next frame, and native pacing must
    draw the viewport again after it."""
    scene = tmp_path / "flat-materials.usda"
    scene.write_text(_FLAT_MATERIALS_SCENE, encoding="utf-8")
    runtimes = ("ovrtx", f"ovui_data_adapters.{provider}.renderer_adapter")
    observed = _session(tmp_path, provider, runtimes, "material_verify", scene, gpu_upload=False)
    _assert_owned_active_session(observed, provider)
    assert observed["verify_active_before"] and observed["verify_token_before"]
    assert "verify_error" not in observed, observed["verify_error"]
    verify = observed["verify"]
    assert verify["mode"].startswith("in the application's renderer")
    assert verify["counts"] == {"ok": 2}, verify
    assert verify["mismatches"] == [] and verify["failures"] == []
    assert observed["verify_seconds"] < 30.0
    after = observed["verify_after"]
    assert after["session_token"] != 0, "native pacing did not draw the viewport again"
    assert after["renderer_token"] == after["session_token"]


@pytest.mark.requires_ovrtx
@pytest.mark.parametrize("mode", ["on_change", "on_change_sync"])
def test_the_default_render_policy_stops_rendering_a_still_viewport(tmp_path, mode):
    """Regression: ovrtx keeps memory on every render step, so a still USD
    Viewer that rendered every frame grew without end. With the default
    render policy the viewport renders a change and its settle frames, then
    stops; a stage edit renders again, and a material check still gets its
    frame. ``on_change``: native frame pacing; ``on_change_sync``: no renderer
    table, so the viewport renders through ``render_frame`` (the adapter)."""
    scene = tmp_path / "flat-materials.usda"
    scene.write_text(_FLAT_MATERIALS_SCENE, encoding="utf-8")
    runtimes = ("ovrtx", "ovui_data_adapters.openusd.renderer_adapter")
    observed = _session(
        tmp_path, "openusd", runtimes, mode, scene, gpu_upload=False, render_policy="")
    if mode == "on_change":
        session = observed["session"]
        assert session["session_token"] != 0
        assert session["renderer_token"] == session["session_token"]
        assert observed["completions_delta"] > 0, "the first frames were not rendered"
    first, second = observed["still"]
    for still in (first, second):
        assert still["same_session"], still
        assert still["completions_delta"] == 0, f"a still viewport rendered: {still}"
        assert still["hud"]["fps_text"].endswith("/0"), still
    assert observed["change_rendered_after"] < 10.0, "the stage edit was not rendered"
    assert "verify_error" not in observed, observed["verify_error"]
    verify = observed["verify"]
    assert verify["counts"] == {"ok": 2}, verify
    assert verify["mismatches"] == [] and verify["failures"] == []
    assert observed["verify_seconds"] < 30.0


def test_default_launch_publishes_gpu_resident_frames_without_host_readback(tmp_path):
    """A capable ordinary session must publish through the GPU, not the host.

    This is the boundary the separate uploader tests cannot cover: OVRTX map →
    native session → slot-ring publication. If the coordinator regresses to
    mapping LdrColor on the CPU, the session still runs and still completes
    frames, so every other assertion here keeps passing — only the publication
    split changes. The skip is a property of the host (can it import exported
    memory at all), decided by the same real probe the product uses, and is
    independent of which route the coordinator then chooses.
    """
    runtimes = ("ovrtx", "ovui_data_adapters.openusd.renderer_adapter")
    capability_dir = tmp_path / "gpu-upload-probe"
    capability_dir.mkdir()
    if not _gpu_upload_capable(capability_dir, *runtimes):
        pytest.skip("this host cannot import exported memory into CUDA, so "
                    "GPU-resident publication is legitimately unavailable")
    # Hardware eligibility is established. _session also checks the optional
    # OpenUSD runtime and pacing provider; once present, the session must
    # publish through the GPU or fail.
    observed = _session(tmp_path, "openusd", runtimes, "session")
    _assert_owned_active_session(observed, "openusd")
    assert observed["gpu_publications_total"] > 0, (
        "a capable session published no GPU-resident frames; the coordinator "
        "fell back to host mapping and the viewport is paying a CPU readback"
    )
    assert observed["host_publications_total"] == 0, (
        "a capable session published through the host route: "
        f"{observed['host_publications_total']} host publications. Even one "
        "means a caller acted on a capability answer that was not the single "
        "completed probe result."
    )


def test_default_launch_without_a_renderer_package(tmp_path):
    """A public install has no package that fills ovui's renderer slot.

    The product still launches the same way, reports exactly why native pacing
    is off, and keeps rendering and presenting the viewport on the UI tick.
    """
    observed = _session(
        tmp_path,
        "openusd",
        ("ovrtx", "ovui_data_adapters.openusd.renderer_adapter"),
        "fallback",
    )
    fallback = observed["fallback"]
    assert fallback["supported"] is False
    assert fallback["active"] is False
    assert fallback["status_reason"] == "hooks_unavailable"
    # Core names no optional package; the reason is generic.
    assert "renderer hooks" in fallback["last_error"]
    assert fallback["completions_delta"] > 0, "the viewport stopped rendering"
    assert fallback["ui_updates"] > 0
    hud = fallback["hud"]
    assert hud["render_fps"] is not None and hud["render_fps"] > 0.0
