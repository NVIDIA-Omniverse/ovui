# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The render diagnostics Inspector commands and the health status, without OpenUSD."""

import asyncio
import concurrent.futures
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ovui_data_adapters.common import render_diagnostics as rd
from ovui_data_adapters.common import render_diagnostics_service as service_module


@pytest.fixture(autouse=True)
def _inspector(monkeypatch, request):
    monkeypatch.setenv("OVUIINSPECT_ENABLED", "0")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "skills" / "omniverse-ui-inspector"))
    request.addfinalizer(lambda: [sys.modules.pop(n) for n in [n for n in sys.modules if n.split(".")[0] == "ovuiinspect"]])
    monkeypatch.setattr(rd, "_DIAGNOSTICS", rd.RenderDiagnostics())
    monkeypatch.setattr(rd, "_VERIFICATION", {})
    monkeypatch.setattr(rd, "_RESOURCE_REPORT", {"checked": False, "warnings": []})
    # These commands must work in an install without OpenUSD: any import of pxr fails here.
    monkeypatch.setitem(sys.modules, "pxr", None)


def _commands(application):
    return {c.name: c for c in service_module.inspector_commands(application)}


class _NativeRenderer:
    """The surface of a renderer adapter that the commands use: the native OVStage adapter has it."""

    def __init__(self):
        self.described = []
        self.requests = []

    def describe_materials(self, path_prefix, limit):
        self.described.append((path_prefix, limit))
        return {"success": True, "count": 1, "materials": [{"path": "/World/Looks/Red"}], "events": []}

    def request_material_check(self, path_prefix, limit):
        pending = concurrent.futures.Future()
        self.requests.append((path_prefix, limit, pending))
        return pending


def test_the_report_of_a_native_scene_comes_from_the_active_renderer_without_openusd():
    renderer = _NativeRenderer()
    application = SimpleNamespace(get_renderer_adapter=lambda: renderer, _current_file_path="/scene/on/disk.usda")
    report = _commands(application)["render_diagnostics"].handler(path_prefix="/World", limit=7)
    assert renderer.described == [("/World", 7)]
    assert report["materials"] == [{"path": "/World/Looks/Red"}] and report["resources"] == {"checked": False, "warnings": []}


def test_without_a_stage_or_a_renderer_the_report_says_that_no_scene_is_open():
    # A known file path is not opened again: the commands describe only what the application shows.
    application = SimpleNamespace(_current_file_path="/scene/on/disk.usda")
    with pytest.raises(RuntimeError, match="no scene is open"):
        _commands(application)["render_diagnostics"].handler()


def test_material_verify_runs_at_a_frame_of_the_active_renderer_and_waits_without_blocking_the_loop():
    renderer = _NativeRenderer()
    handler = _commands(SimpleNamespace(get_renderer_adapter=lambda: renderer))["material_verify"].handler

    async def run():
        call = handler(path_prefix="/World", limit=3, timeout=5.0)
        assert inspect.isawaitable(call)  # the Inspector awaits it on the application's loop
        task = asyncio.ensure_future(call)
        frames = 0
        while not renderer.requests:  # the loop keeps running while the handler waits
            frames += 1
            await asyncio.sleep(0)
        assert renderer.requests[0][:2] == ("/World", 3)
        # The next frame of the renderer runs the check and gives its result.
        renderer.requests[0][2].set_running_or_notify_cancel()
        renderer.requests[0][2].set_result({
            "materials": {"/World/Looks/Red": {"state": "ok"}, "/World/Looks/Green": {"state": "unverifiable"}},
            "mismatches": [], "failures": [], "unverified": ["/World/Looks/Green"], "stage_dirty": True,
        })
        return await task

    result = asyncio.run(run())
    assert result["mode"] == "in the application's renderer (_NativeRenderer)"
    assert result["counts"] == {"ok": 1, "unverifiable": 1} and result["stage_dirty"] is True


def test_material_verify_that_does_not_run_in_time_is_cancelled_and_reported():
    renderer = _NativeRenderer()
    handler = _commands(SimpleNamespace(get_renderer_adapter=lambda: renderer))["material_verify"].handler
    with pytest.raises(RuntimeError, match="did not end in 0 s; it runs at the next frame of the viewport"):
        asyncio.run(handler(timeout=0.05))
    assert renderer.requests[0][2].cancelled()


def test_material_verify_that_the_inspector_cancels_takes_its_request_back():
    """Defect: the Inspector cancels a command at its time limit; the request stayed queued and ran later for nobody."""

    renderer = _NativeRenderer()
    handler = _commands(SimpleNamespace(get_renderer_adapter=lambda: renderer))["material_verify"].handler

    async def run():
        task = asyncio.ensure_future(handler(timeout=60.0))
        while not renderer.requests:
            await asyncio.sleep(0)
        task.cancel()  # what the Inspector does when the command passes its time limit
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert renderer.requests[0][2].cancelled()


def test_a_cancelled_check_request_leaves_the_queue_at_once_and_never_runs():
    from ovui_data_adapters.common.render_probe import MaterialCheckRequests

    queue, ran = MaterialCheckRequests(), []
    first, second = queue.request("/World/A", 1), queue.request("/World/B", 2)
    assert len(queue) == 2
    first.cancel()
    assert len(queue) == 1  # no frame is needed for it to leave
    queue.run(lambda path_prefix, limit: ran.append((path_prefix, limit)) or {"path": path_prefix})
    assert ran == [("/World/B", 2)] and second.result(timeout=0) == {"path": "/World/B"} and not queue
    failing = queue.request()
    queue.run(lambda path_prefix, limit: 1 / 0)
    assert isinstance(failing.exception(timeout=0), ZeroDivisionError)  # the caller gets the error of the check


def test_material_verify_needs_a_renderer_that_can_check_and_never_falls_back_to_the_saved_file():
    for application, why in (
        (SimpleNamespace(source_path="/scene.usda"), "no renderer is active"),
        (SimpleNamespace(renderer=object()), "object has no material check"),
    ):
        with pytest.raises(RuntimeError, match=f"cannot check its materials \\({why}\\)"):
            asyncio.run(_commands(application)["material_verify"].handler())


def test_the_renderer_of_the_application_is_found_by_its_accessor_before_an_attribute():
    accessor, attribute = _NativeRenderer(), _NativeRenderer()
    assert service_module.application_renderer(SimpleNamespace(get_renderer_adapter=lambda: accessor,
                                                               renderer=attribute)) is accessor
    assert service_module.application_renderer(SimpleNamespace(renderer=attribute)) is attribute
    assert service_module.application_renderer(SimpleNamespace()) is None


def test_gpu_memory_reports_the_device_the_host_and_the_renderer_totals(monkeypatch):
    monkeypatch.setattr(rd, "read_gpu_memory", lambda index=0: rd.GpuMemory(47 * rd.GIB, 1, 2, "MIG 2g.48gb", True, "nvml"))
    monkeypatch.setattr(rd, "read_host_memory", lambda: rd.HostMemory(128 * rd.GIB, 9 * rd.GIB, "cgroup2", 103 * rd.GIB))
    memory = _commands(SimpleNamespace())["gpu_memory"].handler()
    assert memory["gpu"]["available"] is True and memory["gpu"]["mig"] is True
    assert memory["host"]["used_bytes"] == 9 * rd.GIB and memory["host"]["reclaimable_bytes"] == 103 * rd.GIB
    assert "available" in memory["renderer"]


def test_inspector_status_is_degraded_with_the_named_failures_and_ok_without():
    assert service_module.inspector_status()["degraded"] is False
    rd.get_render_diagnostics().record("/World/Looks/red", "./red.png", "texture", "not found")
    rd.set_verification({"/World/Looks/red": {"state": "mismatch"}, "/World/Looks/blue": {"state": "ok"}})
    status = service_module.inspector_status()
    assert status["degraded"] is True and status["failure_kinds"] == {"texture": 1}
    assert status["materials_shown_wrong"] == ["/World/Looks/red"]
    assert status["material_check"] == {"mismatch": 1, "ok": 1}
    assert status["newest"][0]["resource"] == "./red.png"


def test_a_check_that_could_not_run_degrades_health_and_a_material_that_was_not_checked_does_not():
    diagnostics = rd.get_render_diagnostics()
    diagnostics.record("/World/Looks/Glass", "", "unverified", "not checked: the material uses opacity")
    status = service_module.inspector_status()
    assert status["degraded"] is False and status["failure_events"] == 0
    diagnostics.record(rd.SCENE, "", "unverified", "the material check could not run: RuntimeError: no clone_usd")
    status = service_module.inspector_status()
    assert status["degraded"] is True and status["failure_kinds"] == {"unverified": 1}
    assert status["newest"][0]["message"].startswith("the material check could not run")


def test_inspector_status_shows_the_startup_warnings_and_a_resource_below_the_minimum(monkeypatch):
    unknown = "The host memory limit is unknown; cannot check the minimum of 48 GiB for scene size 404 MiB."
    below = "When the renderer started, 3.4 GiB of the 47.4 GiB of 'GPU' were free (other processes used the rest)"
    monkeypatch.setattr(rd, "_RESOURCE_REPORT", {"checked": True, "warnings": [below, unknown], "below_minimum": [below]})
    status = service_module.inspector_status()
    assert status["degraded"] is True and status["failure_events"] == 0
    assert status["resources_below_minimum"] == [below] and status["resource_warnings"] == [below, unknown]
    # a resource that cannot be read is a warning, not evidence of a wrong render
    monkeypatch.setattr(rd, "_RESOURCE_REPORT", {"checked": True, "warnings": [unknown], "below_minimum": []})
    status = service_module.inspector_status()
    assert status["degraded"] is False and status["resource_warnings"] == [unknown]
