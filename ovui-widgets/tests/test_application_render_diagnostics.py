# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""USD Viewer gives the render diagnostics commands the renderer of its viewport."""

import asyncio
import concurrent.futures
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def commands(monkeypatch, request):
    # ovuiinspect ships in the inspector skill, not on the default import path. Load it from the checkout without
    # starting its HTTP server, and unload it afterwards so later tests see a normal launch again.
    monkeypatch.setenv("OVUIINSPECT_ENABLED", "0")
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "skills" / "omniverse-ui-inspector"))
    request.addfinalizer(
        lambda: [sys.modules.pop(n) for n in [n for n in sys.modules if n.split(".")[0] == "ovuiinspect"]]
    )
    from ovui_data_adapters.common.render_diagnostics_service import inspector_commands

    return lambda app: {command.name: command for command in inspector_commands(app)}


class _ViewportRenderer:
    """The renderer adapter of the viewport: what the commands may use of it."""

    def __init__(self):
        self.requests = []

    def describe_materials(self, path_prefix, limit):
        return {"success": True, "count": 0, "materials": [], "events": []}

    def request_material_check(self, path_prefix, limit):
        pending = concurrent.futures.Future()
        self.requests.append(pending)
        return pending


def _application(viewport):
    from ovui_widgets.app.application import Application

    app = Application.__new__(Application)  # the real class, without a window
    app._viewport_window = viewport
    app._stage_adapter = SimpleNamespace(stage=object())  # a native OVStage scene: not an OpenUSD stage
    return app


def test_material_verify_runs_in_the_renderer_of_the_viewport(commands):
    """Review: in USD Viewer the command did not find the renderer (it is kept by the viewport, not as
    ``application.renderer``) and drew a saved file in a second renderer."""

    renderer = _ViewportRenderer()
    app = _application(SimpleNamespace(renderer_adapter=renderer))
    assert app.get_renderer_adapter() is renderer
    found = commands(app)

    async def run():
        task = asyncio.ensure_future(found["material_verify"].handler(timeout=5.0))
        while not renderer.requests:
            await asyncio.sleep(0)
        renderer.requests[0].set_running_or_notify_cancel()
        renderer.requests[0].set_result({"materials": {"/World/Looks/Red": {"state": "ok"}}, "mismatches": [],
                                         "failures": [], "unverified": []})
        return await task

    result = asyncio.run(run())
    assert result["mode"] == "in the application's renderer (_ViewportRenderer)" and result["counts"] == {"ok": 1}
    assert found["render_diagnostics"].handler()["count"] == 0  # the native scene is described by the same renderer


def test_without_a_viewport_renderer_the_commands_say_so(commands):
    app = _application(None)
    assert app.get_renderer_adapter() is None
    found = commands(app)
    with pytest.raises(RuntimeError, match="cannot check its materials \\(no renderer is active\\)"):
        asyncio.run(found["material_verify"].handler())
    with pytest.raises(RuntimeError, match="no scene is open"):
        found["render_diagnostics"].handler()


def test_opening_a_file_opens_it_once_and_keeps_no_second_copy_of_the_scene(tmp_path, monkeypatch):
    """Review: Application.open_file started a background check that opened the same file again with OpenUSD and kept
    that second stage for the session (on Factory it also printed composition warnings from another thread)."""

    from pxr import Usd, UsdGeom

    from ovui_widgets.app.application import Application
    from ovui_widgets.common.selection import SelectionBus

    path = str(tmp_path / "scene.usda")
    stage = Usd.Stage.CreateNew(path)
    UsdGeom.Sphere.Define(stage, "/World/Sphere")
    stage.GetRootLayer().Save()
    del stage
    opened = []
    real_open = Usd.Stage.Open

    def counting_open(*args, **kwargs):
        opened.append(str(args[0]) if args else "")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(Usd.Stage, "Open", counting_open)
    Application._instance = None
    SelectionBus._instance = None
    app = Application()
    app._startup_prebuilt_renderer = None  # headless: no viewport, no renderer
    try:
        app.open_file(path)
    finally:
        app.shutdown()  # stops and joins every background task of the application
        Application._instance = None
        SelectionBus._instance = None
    assert opened.count(path) == 1, opened
