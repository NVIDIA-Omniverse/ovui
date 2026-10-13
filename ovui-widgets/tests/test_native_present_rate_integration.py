# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Default-on native pacing across a real product session.

A normal launch — the same bootstrap/``run(usd_path=...)`` sequence as
``ovui_widgets.app.__main__`` — must leave the viewport's own renderer owning
an active native pacing session that is really completing OVRTX frames, and
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

Skipping is limited to a missing *capability* — no display, no windowed Vulkan
standalone backend, or no provider runtime. A capable host that then fails to
establish or activate the session fails the test; it is never skipped.
"""

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

# Confirms the host can reach a windowed Vulkan standalone backend and load
# the provider's own adapter stack. It deliberately proves capability only —
# session activation is what the tests themselves assert.
_CAPABILITY = """
import importlib, os, sys
os.environ["OMNIUI_BACKEND"] = "vulkan"
os.environ.pop("OMNIUI_HEADLESS", None)
for module in sys.argv[1:]:
    importlib.import_module(module)
import omni.ui as ui
ui.init("capability", width=64, height=64, max_fps=60.0, present_fps=60.0)
print("CAPABLE", ui.get_present_rate())
# Whether this host can import exported memory into CUDA at all. Asked in a
# process with no pacing session and no native render thread, so it is the
# host's property and cannot be perturbed by — or confused with — the
# in-session publication behaviour a test then asserts.
print("GPU_UPLOAD", bool(ui.has_gpu_byte_image()))
"""

_SESSION = r"""
import json, os, sys, threading, time
from pathlib import Path

provider, scene, mode = sys.argv[1], sys.argv[2], sys.argv[3]
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
            else:
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


def _run(
    script: str, argv: list, timeout: float, workdir: Path
) -> subprocess.CompletedProcess:
    """Run a product subprocess in its own throwaway directory.

    ``Application.run`` writes UI layout state (``imgui.ini``) relative to the
    working directory and persists settings to a user profile, so both are
    redirected into ``workdir``; nothing lands in the source tree or the real
    profile. ``sys.path`` is absolutised first so the current working tree
    still wins over any installed copy from the new directory.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        str(Path(entry).resolve()) for entry in sys.path if entry
    )
    env["OVUI_WIDGETS_SETTINGS_PATH"] = str(workdir / "settings.json")
    env.pop("OMNIUI_BACKEND", None)
    env.pop("OMNIUI_HEADLESS", None)
    return subprocess.run(
        [sys.executable, "-c", script, *argv],
        capture_output=True, text=True, timeout=timeout, env=env,
        cwd=str(workdir),
    )


def _capable(workdir: Path, *runtimes: str) -> bool:
    if os.name != "nt" and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return False
    if not SCENE.exists():
        return False
    try:
        done = _run(_CAPABILITY, list(runtimes), 180, workdir)
    except (OSError, subprocess.SubprocessError):
        return False
    return any(
        line.startswith("CAPABLE") and float(line.split()[1]) == 60.0
        for line in done.stdout.splitlines()
    )


def _gpu_upload_capable(workdir: Path, *runtimes: str) -> bool:
    """Host capability, established outside any session under test.

    Deliberately not the in-session capability call: that is the very API whose
    provisional answer is the regression these tests guard, so using it for
    eligibility would let a regressed build skip instead of fail.
    """
    try:
        done = _run(_CAPABILITY, list(runtimes), 180, workdir)
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line.strip() == "GPU_UPLOAD True"
               for line in done.stdout.splitlines())


def _session(tmp_path: Path, provider: str, runtimes: tuple, mode: str) -> dict:
    probe_dir = tmp_path / f"{provider}-probe"
    session_dir = tmp_path / f"{provider}-session"
    probe_dir.mkdir()
    session_dir.mkdir()
    if not _capable(probe_dir, *runtimes):
        pytest.skip(f"no windowed Vulkan standalone backend + {provider} runtime")
    done = _run(_SESSION, [provider, str(SCENE), mode], 420, session_dir)
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
    # The session must have executed this working tree, from the throwaway
    # directory rather than the repository.
    assert Path(observed["application_module"]) == (
        Path(__file__).resolve().parents[1]
        / "ovui_widgets" / "app" / "application.py"
    ), observed["application_module"]
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
    # Past this point the host is known capable, so there is no exit that
    # skips: the session either publishes through the GPU or the test fails.
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
