# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Async commands must release their references before Viewer/native teardown."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ovui_widgets.app.application import Application


def test_viewer_finally_awaits_command_cleanup_before_media_and_scene(monkeypatch):
    import omni.ui as ui

    async def run():
        events = []
        entered = asyncio.Event()

        async def command():
            try:
                entered.set()
                await asyncio.Future()
            finally:
                await asyncio.sleep(0)
                events.append("command cleanup")

        task = asyncio.create_task(command())
        await entered.wait()
        app = Application()

        def detach(owner):
            assert owner is app
            events.append("detach")
            task.cancel()
            return (task,)

        app._ovinspect_module = SimpleNamespace(detach_application=detach)
        app._inspector_media = SimpleNamespace(
            close=AsyncMock(side_effect=lambda: events.append("media"))
        )
        # Fail construction so the actual run_async finally executes without a
        # native UI. The shutdown boundary observes the task's completed cleanup.
        monkeypatch.setattr(ui, "MainWindow", Mock(side_effect=RuntimeError("construction")))
        monkeypatch.setattr(app, "_apply_rate_limit_to_ui_pump", Mock())
        real_shutdown = app.shutdown

        def shutdown():
            assert task.done()
            events.append("scene")
            real_shutdown()

        monkeypatch.setattr(app, "shutdown", shutdown)
        await app.run_async()
        assert events == ["detach", "command cleanup", "media", "scene"]
        assert app._shutdown_done

    asyncio.run(run())


def test_synchronous_shutdown_retains_scene_until_cancelled_commands_finish():
    async def run():
        app = Application()
        entered = asyncio.Event()

        async def command():
            try:
                entered.set()
                await asyncio.Future()
            finally:
                await asyncio.sleep(0)

        task = asyncio.create_task(command())
        await entered.wait()

        def detach(owner):
            task.cancel()
            return (task,)

        app._ovinspect_module = SimpleNamespace(detach_application=detach)
        session = SimpleNamespace(shutdown_scene=Mock())
        app._adapter_session = session
        with pytest.raises(RuntimeError, match="Inspector command cleanup"):
            app.shutdown()
        session.shutdown_scene.assert_not_called()
        assert app._adapter_session is session
        await app._finish_inspector_commands()
        app.shutdown()
        session.shutdown_scene.assert_called_once()
        assert app._shutdown_done

    asyncio.run(run())


def _failing_construction_app(monkeypatch, events):
    import omni.ui as ui

    app = Application()
    app._inspector_media = SimpleNamespace(
        close=AsyncMock(side_effect=lambda: events.append("media"))
    )
    monkeypatch.setattr(ui, "MainWindow", Mock(side_effect=RuntimeError("construction")))
    monkeypatch.setattr(app, "_apply_rate_limit_to_ui_pump", Mock())
    real_shutdown = app.shutdown

    def shutdown():
        events.append("scene")
        real_shutdown()

    monkeypatch.setattr(app, "shutdown", shutdown)
    return app


def test_failed_inspector_detach_still_closes_media_and_scene(monkeypatch):
    events = []
    app = _failing_construction_app(monkeypatch, events)

    def detach(owner):
        events.append("detach")
        raise RuntimeError("detach failed")

    app._ovinspect_module = SimpleNamespace(detach_application=detach)
    asyncio.run(app.run_async())
    assert events == ["detach", "media", "scene"]
    assert app._shutdown_done
    # The original failure remains primary; teardown was not skipped.
    assert str(app._run_exception) == "construction"


def test_cancelled_host_finishes_teardown_before_propagating(monkeypatch):
    async def run():
        events = []
        app = _failing_construction_app(monkeypatch, events)
        entered, release = asyncio.Event(), asyncio.Event()

        async def command():
            try:
                await asyncio.Future()
            finally:
                entered.set()
                await release.wait()
                events.append("command cleanup")

        task = asyncio.create_task(command())
        await asyncio.sleep(0)

        def detach(owner):
            task.cancel()
            return (task,)

        app._ovinspect_module = SimpleNamespace(detach_application=detach)
        host = asyncio.create_task(app.run_async())
        await entered.wait()
        host.cancel()  # Ctrl+C or host cancellation while commands clean up.
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await host
        assert events == ["command cleanup", "media", "scene"]
        assert app._shutdown_done

    asyncio.run(run())


def test_second_cancel_during_media_close_still_shuts_down_the_scene(monkeypatch):
    async def run():
        events = []
        app = _failing_construction_app(monkeypatch, events)
        closing, release = asyncio.Event(), asyncio.Event()

        async def close():
            closing.set()
            await release.wait()
            events.append("media")

        app._inspector_media = SimpleNamespace(close=close)
        app._ovinspect_module = SimpleNamespace(detach_application=lambda owner: ())
        host = asyncio.create_task(app.run_async())
        await closing.wait()
        host.cancel()  # A second Ctrl+C while media is closing.
        with pytest.raises(asyncio.CancelledError):
            await host
        assert "scene" in events
        assert app._shutdown_done

    asyncio.run(run())
