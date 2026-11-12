# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Application extension API over the existing Inspector/frame-loop pipeline."""

import asyncio
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import Field

os.environ["OVUIINSPECT_ENABLED"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ovuiinspect as inspector



@pytest.fixture(autouse=True)
def _no_installed_command_entry_points(monkeypatch):
    """The tests expect the catalog of the application under test; an installed module (for
    example ovui-data-adapters-common) must not add commands. The entry-point tests set their own."""

    monkeypatch.setattr("importlib.metadata.entry_points", lambda group=None: [])
    monkeypatch.setattr(inspector, "_STATUS_PROVIDERS", None)


@pytest.fixture
def application(monkeypatch):
    monkeypatch.setattr(inspector, "_STATE", inspector._State())
    app = SimpleNamespace(events=[])
    inspector.attach_application(app)
    yield app
    inspector.detach_application(app)


async def drain_until(task, app):
    for _ in range(3000):
        inspector.drain_pending(SimpleNamespace(), application=app)
        if task.done():
            return await task
        await asyncio.sleep(0.001)
    raise AssertionError("Inspector did not complete queued work")


def test_discovery_validation_and_owner_thread_execution(application):
    class Input(inspector.Arguments):
        amount: int = Field(ge=1, le=3)

    owner_thread = threading.get_ident()

    def handler(amount):
        assert threading.get_ident() == owner_thread
        application.events.append(amount)
        return {"amount": amount}

    inspector.register_command(
        inspector.Command("add", "Add a bounded amount.", Input, handler)
    )
    with TestClient(inspector._create_app()) as client:
        row = next(r for r in client.get("/commands").json()["commands"] if r["name"] == "add")
        assert row["endpoint"] == "/commands/add"
        assert row["input_schema"]["additionalProperties"] is False
        assert client.post("/commands/add", json={"amount": 0}).status_code == 422
        assert (
            client.post(
                "/commands/add", json={"amount": 1, "unexpected": 1}
            ).status_code
            == 422
        )
        assert client.post("/commands/missing", json={}).status_code == 404
        assert application.events == []

        async def run():
            pending = asyncio.create_task(
                asyncio.to_thread(client.post, "/commands/add", json={"amount": 2})
            )
            return await drain_until(pending, application)

        response = asyncio.run(run())
    assert response.json() == {"success": True, "result": {"amount": 2}}
    assert application.events == [2]


def test_failed_contributions_roll_back_catalog_but_keep_core_inspector(application, monkeypatch):
    def broken_provider():
        yield inspector.Command("partial", "Partial", inspector.Arguments, lambda: None)
        raise RuntimeError("extension unavailable")

    app = SimpleNamespace(get_inspector_commands=broken_provider)
    inspector.attach_application(app)
    assert inspector.status()["app_attached"]
    assert inspector.status()["status"] == "degraded"
    assert "extension unavailable" in inspector.status()["contribution_error"]
    assert not inspector._STATE.commands
    monkeypatch.setenv("OVUIINSPECT_ENABLE_EXECUTE", "1")
    command = inspector._Command("execute", {"code": "result = 42"}, 1)
    inspector._advance_execute(command, app)
    assert command.result["result"] == 42


def test_between_render_drains_preserve_one_input_step_per_ui_frame(application):
    from unittest.mock import Mock

    native = SimpleNamespace(_inject_mouse_move=Mock(), _inject_mouse_button=Mock())
    click = inspector._make_click(100, 80, "left", False, 5, None)
    inspector._STATE.enqueue(click)
    for _ in range(4):
        inspector.drain_pending(native, application=application, advance_input=False)
    assert click.step_index == 0
    while not click.done:
        previous = click.step_index
        inspector.drain_pending(native, application=application)
        assert click.step_index == previous + 1
        for _ in range(4):
            inspector.drain_pending(native, application=application, advance_input=False)
        assert click.step_index == previous + 1
    assert [call.args for call in native._inject_mouse_button.call_args_list] == [(0, True), (0, False)]


def test_async_handlers_yield_frames_but_serialize_following_execute(
    application, monkeypatch
):
    monkeypatch.setenv("OVUIINSPECT_ENABLE_EXECUTE", "1")

    async def handler():
        application.events.append("begin")
        await asyncio.sleep(0.025)
        application.events.append("end")
        return {"complete": True}

    inspector.register_command(
        inspector.Command(
            "async_work",
            "Await a frame-friendly operation.",
            inspector.Arguments,
            handler,
        )
    )
    with TestClient(inspector._create_app()) as client:

        async def run():
            pending = asyncio.create_task(
                asyncio.to_thread(client.post, "/commands/async_work", json={})
            )
            while not application.events:
                inspector.drain_pending(SimpleNamespace(), application=application)
                await asyncio.sleep(0.001)
            following = asyncio.create_task(
                asyncio.to_thread(
                    client.post,
                    "/execute",
                    json={"code": "app.events.append('execute')"},
                )
            )
            frames = 0
            while not pending.done():
                inspector.drain_pending(SimpleNamespace(), application=application)
                frames += 1
                await asyncio.sleep(0.001)
            assert frames > 1
            assert (await pending).status_code == 200
            assert (await drain_until(following, application)).status_code == 200

        asyncio.run(run())
    assert application.events == ["begin", "end", "execute"]


def test_removal_prevents_queued_mutation_and_collision_is_rejected(application):
    command = inspector.Command(
        "mutate",
        "Mutate application.",
        inspector.Arguments,
        lambda: application.events.append(1),
    )
    registration = inspector.register_command(command)
    with pytest.raises(ValueError, match="already registered"):
        inspector.register_command(command)
    pending = inspector._Command(
        "extension", {"registration": registration, "arguments": {}}, 1
    )
    inspector._STATE.enqueue(pending)
    registration.remove()
    inspector.drain_pending(SimpleNamespace(), application=application)
    assert pending.result["success"] is False
    assert application.events == []


def test_timeout_cancels_async_work_before_next_mutation(application):
    async def handler():
        try:
            await asyncio.sleep(10)
            application.events.append("late mutation")
        finally:
            application.events.append("cancelling")
            await asyncio.sleep(0.01)
            application.events.append("cancelled")

    registration = inspector.register_command(
        inspector.Command("slow", "Wait.", inspector.Arguments, handler)
    )

    async def run():
        pending = inspector._Command(
            "extension", {"registration": registration, "arguments": {}}, 0.02
        )
        inspector._STATE.enqueue(pending)
        for _ in range(100):
            inspector.drain_pending(SimpleNamespace(), application=application)
            await asyncio.sleep(0.001)
            if not inspector._STATE.queue:
                break
        assert pending.done and pending.result["success"] is False
        assert pending.task.cancelled()
        assert not inspector._STATE.queue

    asyncio.run(run())
    assert application.events == ["cancelling", "cancelled"]


def test_namespace_hook_preserves_context_without_changing_default(
    application, monkeypatch
):
    monkeypatch.setenv("OVUIINSPECT_ENABLE_EXECUTE", "1")

    def execute(code):
        command = inspector._Command("execute", {"code": code}, 1)
        inspector._advance_execute(command, application)
        return command.result

    assert execute("marker = 42")["success"]
    assert execute("result = globals().get('marker')")["result"] is None
    namespace = {}
    application.get_inspector_namespace = lambda: namespace
    assert execute("marker = 42")["success"]
    assert execute("result = marker")["result"] == 42
    failure = execute("print('before'); raise ValueError('failure')")
    assert not failure["success"] and failure["stdout"] == "before\n"
    assert failure["error"] == "ValueError: failure (execute line 1)"
    assert "Traceback" in failure["traceback"]


def test_detach_discards_queued_application_commands(application):
    registration = inspector.register_command(
        inspector.Command(
            "mutate",
            "Mutate.",
            inspector.Arguments,
            lambda: application.events.append(1),
        )
    )
    command = inspector._Command(
        "extension", {"registration": registration, "arguments": {}}, 1
    )
    inspector._STATE.enqueue(command)
    inspector.detach_application(application)
    assert command.done and not registration.active
    assert not inspector._STATE.commands and not inspector._STATE.queue
    assert application.events == []


def test_timeout_message_says_whether_the_command_started(application, monkeypatch):
    queued = inspector._Command("extension", {}, 0.01)
    running = inspector._Command("extension", {}, 0.01)
    running.started = True
    # The frame loop never drains either command: both HTTP waits time out.
    assert "was not run" in inspector._wait(queued)["error"]
    message = inspector._wait(running)["error"]
    assert "after it started" in message and "may still complete" in message


def test_command_errors_are_concise_with_the_traceback_kept_separately(application):
    class Rejected(ValueError):
        def __init__(self):
            super().__init__("Stage edit rejected; nothing was authored")
            self.errors = [{"op": 0, "code": "prim_missing", "path": "/X", "message": "missing"}]

    def handler():
        raise Rejected()

    inspector.register_command(inspector.Command("reject", "Reject.", inspector.Arguments, handler))
    with TestClient(inspector._create_app()) as client:
        async def run():
            pending = asyncio.create_task(asyncio.to_thread(client.post, "/commands/reject", json={}))
            return await drain_until(pending, application)

        response = asyncio.run(run())
    body = response.json()
    assert response.status_code == 400
    assert body["detail"] == "Rejected: Stage edit rejected; nothing was authored"
    # Tracebacks stay in the server log; clients get the message and coded errors.
    assert "Traceback" not in body["detail"] and "traceback" not in body
    assert body["errors"][0]["code"] == "prim_missing"
    health = inspector._STATE.snapshot()
    assert health["last_error"] == body["detail"] and health["last_error_at"] > 0


def test_timed_out_drag_releases_its_button_and_modifiers(application):
    pressed = []
    native = SimpleNamespace(
        _inject_mouse_move=lambda x, y: None,
        _inject_mouse_button=lambda button, down: pressed.append(("button", button, down)),
        _inject_key_event=lambda key, down: pressed.append(("key", key, down)),
    )
    command = inspector._make_drag(10, 10, 100, 10, "middle", 0.05, steps_count=20, modifiers=["alt"])
    inspector._STATE.enqueue(command)
    for _ in range(6):  # modifier down, button down, a few moves: then the deadline passes
        inspector.drain_pending(native, application=application)
    import time
    time.sleep(0.06)
    inspector.drain_pending(native, application=application)
    assert command.result["success"] is False
    downs = [p for p in pressed if p[2]]
    ups = [p for p in pressed if not p[2]]
    assert sorted(p[:2] for p in downs) == sorted(p[:2] for p in ups)


def test_drag_timeout_query_parameter_overrides_the_body(application):
    seen = {}
    original = inspector._make_drag

    def spy(*args, **kwargs):
        command = original(*args, **kwargs)
        seen["timeout"] = command.timeout
        command.fail("stop")
        return command

    inspector._make_drag = spy
    try:
        with TestClient(inspector._create_app()) as client:
            client.post("/mouse/drag?timeout=90", json={"start_x": 1, "start_y": 1, "end_x": 5, "end_y": 5})
    finally:
        inspector._make_drag = original
    assert seen["timeout"] == 90


class _EntryPoint:
    def __init__(self, name, factory):
        self.name, self._factory = name, factory

    def load(self):
        return self._factory


def _entry_points(monkeypatch, *entries):
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: list(entries) if group == inspector.ENTRY_POINT_GROUP else [],
    )


def test_an_installed_module_adds_commands_to_every_application(monkeypatch):
    """An entry point of the group adds commands; ovui does not import the module."""

    seen = []

    def factory(application):
        seen.append(application)
        return [inspector.Command("added", "Added.", inspector.Arguments, lambda: {"ok": True})]

    _entry_points(monkeypatch, _EntryPoint("diag", factory))
    monkeypatch.setattr(inspector, "_STATE", inspector._State())
    app = SimpleNamespace(events=[])
    inspector.attach_application(app)
    assert seen == [app] and set(inspector._STATE.commands) == {"added"}
    inspector.detach_application(app)
    assert not inspector._STATE.commands


def test_an_application_command_of_the_same_name_is_kept(monkeypatch):
    own = inspector.Command("added", "Own.", inspector.Arguments, lambda: {"own": True})
    other = inspector.Command("added", "Other.", inspector.Arguments, lambda: {"own": False})
    _entry_points(monkeypatch, _EntryPoint("diag", lambda application: [other]))
    monkeypatch.setattr(inspector, "_STATE", inspector._State())
    app = SimpleNamespace(get_inspector_commands=lambda: [own])
    inspector.attach_application(app)
    assert inspector._STATE.commands["added"].command is own
    inspector.detach_application(app)


def test_a_failing_entry_point_is_reported_and_does_not_stop_the_others(monkeypatch, capsys):
    def broken(application):
        raise RuntimeError("cannot build")

    good = _EntryPoint("good", lambda application: [inspector.Command("fine", "Fine.", inspector.Arguments, lambda: {})])
    _entry_points(monkeypatch, _EntryPoint("broken", broken), good)
    monkeypatch.setattr(inspector, "_STATE", inspector._State())
    app = SimpleNamespace()
    inspector.attach_application(app)
    assert set(inspector._STATE.commands) == {"fine"}
    assert "broken: RuntimeError: cannot build" in inspector._STATE.contribution_error
    assert "Commands of entry point broken unavailable" in capsys.readouterr().err
    inspector.detach_application(app)


def test_health_shows_extension_status_and_is_degraded_when_it_says_so(monkeypatch):
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: [_EntryPoint("render", lambda: {"degraded": True, "failure_events": 2})]
        if group == inspector.STATUS_ENTRY_POINT_GROUP else [],
    )
    monkeypatch.setattr(inspector, "_STATUS_PROVIDERS", None)
    monkeypatch.setattr(inspector, "_STATE", inspector._State())
    status = inspector.status()
    assert status["status"] == "degraded"
    assert status["extensions"] == {"render": {"degraded": True, "failure_events": 2}}


def test_health_is_ok_without_extensions_and_a_failing_provider_is_reported(monkeypatch):
    monkeypatch.setattr(inspector, "_STATE", inspector._State())
    assert inspector.status()["status"] == "ok" and inspector.status()["extensions"] == {}

    def broken():
        raise RuntimeError("cannot read")

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: [_EntryPoint("bad", broken)] if group == inspector.STATUS_ENTRY_POINT_GROUP else [],
    )
    monkeypatch.setattr(inspector, "_STATUS_PROVIDERS", None)
    status = inspector.status()
    assert status["status"] == "degraded"
    assert status["extensions"]["bad"] == {"degraded": True, "error": "RuntimeError: cannot read"}
