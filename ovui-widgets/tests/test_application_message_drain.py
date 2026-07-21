# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Application-level tests for the Step 3.7 message drain + resize path.

Covers the two Codex Step 3.7 NOT-GOOD blockers end-to-end through
the production :class:`Application` integration:

1. Worker-thread ``Server.on_message`` parses + enqueues; the
   main-loop ``Application._drain_message_queue`` runs the action and
   emits the reply. Application/UI state (``Application.open_file``,
   :meth:`Application._do_resize`) is **never** invoked from the
   worker thread.

2. ``_do_resize`` falls back to bridge extents when
   ``omni.ui.standalone.set_window_size`` returns ``False`` (the
   headless mode case — ``StandaloneInit.cpp:209–213`` returns
   ``False`` when ``s_glfwPlatform`` is null). The dispatcher reports
   ``success`` because the bridge extent — the meaningful side-effect
   for input mapping — actually updated.
"""

from __future__ import annotations

import json
import sys
from unittest.mock import MagicMock

from ovstream import KeyState, MouseEvent, MouseEventType

from ovui_widgets.app._input_bridge import RemoteInputBridge
from ovui_widgets.app._message_dispatcher import MessageDispatcher

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _attach_message_dispatcher(headless_app, send_mock):
    """Attach a fresh :class:`MessageDispatcher` to the given
    :class:`Application` and return it."""
    dispatcher = MessageDispatcher(send_message_fn=send_mock)
    headless_app._message_dispatcher = dispatcher
    return dispatcher


def _decode_reply(send_mock: MagicMock, index: int = 0) -> dict:
    raw = send_mock.call_args_list[index].args[0]
    return json.loads(raw)


def _stub_ovui_standalone(
    monkeypatch,
    *,
    set_window_size_return,
    headless_resize_return=None,
    headless_extent=None,
):
    """Stub ``omni.ui.standalone`` and its ``headless_frame`` submodule
    so ``Application._do_resize`` exercises the intended branch
    deterministically.

    Returns ``(set_window_size_mock, headless_resize_mock,
    headless_extent_mock)`` so tests can introspect call args.

    ``set_window_size_return`` controls the windowed path. When it is
    ``False`` (the production state in headless mode per
    ``StandaloneInit.cpp:209-213``), ``_do_resize`` falls through to
    the real headless path. ``headless_resize_return`` controls
    whether that path reports success; ``headless_extent`` controls
    the post-resize extent that the tap and bridge read back.
    """
    set_window_size_mock = MagicMock(return_value=set_window_size_return)
    headless_resize_mock = MagicMock(
        return_value=True if headless_resize_return is None
        else headless_resize_return,
    )
    headless_extent_mock = MagicMock(
        return_value=headless_extent if headless_extent is not None else (0, 0),
    )

    standalone_module = MagicMock()
    standalone_module.set_window_size = set_window_size_mock
    headless_frame_module = MagicMock()
    headless_frame_module.resize = headless_resize_mock
    headless_frame_module.extent = headless_extent_mock
    standalone_module.headless_frame = headless_frame_module

    monkeypatch.setitem(sys.modules, "omni.ui.standalone", standalone_module)
    monkeypatch.setitem(
        sys.modules, "omni.ui.standalone.headless_frame", headless_frame_module,
    )
    return set_window_size_mock, headless_resize_mock, headless_extent_mock


def _force_set_window_size(monkeypatch, return_value):
    """Compatibility shim used by a few tests that only need to
    control the windowed path. Returns the ``set_window_size`` mock."""
    set_window_size_mock, _resize_mock, _extent_mock = _stub_ovui_standalone(
        monkeypatch,
        set_window_size_return=return_value,
        headless_resize_return=False,  # headless path also unavailable
    )
    return set_window_size_mock


# --------------------------------------------------------------------------
# Codex blocker #1 — no app/UI mutation on the SDK callback thread
# --------------------------------------------------------------------------


def test_drain_message_queue_is_noop_without_dispatcher(headless_app) -> None:
    """No-op when no dispatcher has been attached (windowed mode or
    before ``_setup_headless_export`` ran)."""
    headless_app._message_dispatcher = None
    headless_app._drain_message_queue()  # must not raise


def test_on_message_does_not_call_open_file_inline(headless_app) -> None:
    """The dispatcher's ``on_message`` callback runs on the ovstream
    worker thread. Even with a real :class:`Application` attached, it
    must not invoke ``open_file`` until the main-loop drain runs."""
    send = MagicMock()
    dispatcher = _attach_message_dispatcher(headless_app, send)
    headless_app.open_file = MagicMock()  # type: ignore[assignment]

    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {"url": "/tmp/scene.usda"},
    }))

    headless_app.open_file.assert_not_called()
    send.assert_not_called()

    # Main-loop drain executes the action and emits the reply.
    headless_app._drain_message_queue()
    headless_app.open_file.assert_called_once_with("/tmp/scene.usda")
    reply = _decode_reply(send)
    assert reply["event_type"] == "openedStageResult"
    assert reply["payload"]["result"] == "success"


def test_on_message_does_not_call_do_resize_inline(
    headless_app, monkeypatch,
) -> None:
    """Symmetric to the open-file test: ``_do_resize`` only runs
    during the main-loop drain."""
    send = MagicMock()
    dispatcher = _attach_message_dispatcher(headless_app, send)
    bridge = RemoteInputBridge(width=1, height=1)
    headless_app.set_remote_input_bridge(bridge)
    _force_set_window_size(monkeypatch, return_value=True)

    spy_do_resize = MagicMock(side_effect=headless_app._do_resize)
    monkeypatch.setattr(headless_app, "_do_resize", spy_do_resize)

    dispatcher.on_message(json.dumps({
        "event_type": "changeResolutionRequest",
        "payload": {"width": 1280, "height": 720},
    }))

    spy_do_resize.assert_not_called()
    send.assert_not_called()

    headless_app._drain_message_queue()
    spy_do_resize.assert_called_once_with(1280, 720)
    assert send.call_count == 1


def test_drain_message_queue_swallows_dispatcher_exceptions(
    headless_app, capsys,
) -> None:
    """Internal dispatcher errors must not unwind the main loop —
    they are logged to stderr and the loop continues."""
    bad = MagicMock()
    bad.drain_pending.side_effect = RuntimeError("boom-internal")
    headless_app._message_dispatcher = bad

    headless_app._drain_message_queue()  # must not raise
    err = capsys.readouterr().err
    assert "message drain raised" in err
    assert "boom-internal" in err


# --------------------------------------------------------------------------
# Codex blocker #2 — headless-compatible resize path
# --------------------------------------------------------------------------


def test_do_resize_windowed_path_calls_set_window_size_and_succeeds(
    headless_app, monkeypatch,
) -> None:
    """In windowed mode, ``set_window_size`` returns ``True`` (the
    GLFW platform actually resized the OS framebuffer). ``_do_resize``
    also forwards the new extents to the bridge so input clamping
    follows."""
    set_window_size = _force_set_window_size(monkeypatch, return_value=True)
    bridge = RemoteInputBridge(width=1, height=1)
    headless_app.set_remote_input_bridge(bridge)

    assert headless_app._do_resize(1920, 1080) is True
    set_window_size.assert_called_once_with(1920, 1080)

    # Bridge clamp window updated to the new extent.
    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.MOVE, modifiers=0,
        x=2000, y=2000, data=0, data2=0, button_state=KeyState.UP,
    ))
    xy, _events = bridge.drain()
    assert xy == (1919, 1079)


def test_do_resize_headless_path_calls_real_headless_resize_and_updates_bridge_to_actual_extent(
    headless_app, monkeypatch,
) -> None:
    """Codex Step 3.7 re-review fix.

    ``set_window_size`` returns ``False`` in headless mode
    (``StandaloneInit.cpp:209-213``). ``_do_resize`` MUST fall
    through to ``omni.ui.standalone.headless_frame.resize(w, h)`` —
    the real ovui binding added for this fix that tears down the
    CUDA-Vulkan interop, recreates the Vulkan framebuffer at the new
    extent, and re-imports it into CUDA. Bridge clamping then tracks
    the **actual** post-resize extent (read back from
    ``headless_frame.extent()``), not the requested size — so a
    Vulkan clamp to device limits is reflected truthfully.
    """
    set_window_size, headless_resize, headless_extent = _stub_ovui_standalone(
        monkeypatch,
        set_window_size_return=False,       # headless: GLFW path refuses
        headless_resize_return=True,         # real headless resize succeeds
        headless_extent=(1280, 720),         # actual framebuffer extent after resize
    )
    bridge = RemoteInputBridge(width=1, height=1)
    headless_app.set_remote_input_bridge(bridge)

    assert headless_app._do_resize(1280, 720) is True
    set_window_size.assert_called_once_with(1280, 720)
    headless_resize.assert_called_once_with(1280, 720)
    # ``extent()`` is consulted to read back the actual framebuffer
    # size and propagate it to the bridge.
    headless_extent.assert_called()

    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.MOVE, modifiers=0,
        x=2000, y=2000, data=0, data2=0, button_state=KeyState.UP,
    ))
    xy, _events = bridge.drain()
    assert xy == (1279, 719)


def test_do_resize_clamps_bridge_to_actual_extent_when_backend_clamps(
    headless_app, monkeypatch,
) -> None:
    """If the Vulkan/headless backend clamps the requested extent (for
    example, because of a device limit), the bridge follows the
    **actual** post-resize extent, not the inflated request — Codex
    review #2 demands the bridge match the real streamed frame."""
    _stub_ovui_standalone(
        monkeypatch,
        set_window_size_return=False,
        headless_resize_return=True,
        # Backend clamped the request to a smaller power-of-two-ish size.
        headless_extent=(1024, 768),
    )
    bridge = RemoteInputBridge(width=1, height=1)
    headless_app.set_remote_input_bridge(bridge)

    assert headless_app._do_resize(8192, 8192) is True

    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.MOVE, modifiers=0,
        x=4000, y=4000, data=0, data2=0, button_state=KeyState.UP,
    ))
    xy, _events = bridge.drain()
    assert xy == (1023, 767)


def test_do_resize_returns_false_when_real_headless_resize_fails(
    headless_app, monkeypatch,
) -> None:
    """If both ``set_window_size`` AND
    ``headless_frame.resize`` refuse, ``_do_resize`` returns ``False``
    and the dispatcher will emit an error reply. The bridge is **not**
    updated to a resolution the streamed frame doesn't actually use —
    pre-fix code would have updated the bridge anyway and reported
    fake success."""
    set_window_size, headless_resize, _extent = _stub_ovui_standalone(
        monkeypatch,
        set_window_size_return=False,
        headless_resize_return=False,        # real headless path fails too
    )
    bridge = RemoteInputBridge(width=1, height=1)
    headless_app.set_remote_input_bridge(bridge)

    assert headless_app._do_resize(1280, 720) is False
    set_window_size.assert_called_once_with(1280, 720)
    headless_resize.assert_called_once_with(1280, 720)

    # Bridge extents must NOT have been updated — the streamed frame
    # is unchanged, so the input clamp window stays at construction
    # values.
    bridge.on_mouse_event(MouseEvent(
        type=MouseEventType.MOVE, modifiers=0,
        x=2000, y=2000, data=0, data2=0, button_state=KeyState.UP,
    ))
    xy, _events = bridge.drain()
    assert xy == (0, 0)


def test_do_resize_returns_false_when_headless_resize_module_missing(
    headless_app, monkeypatch,
) -> None:
    """If ``omni.ui.standalone.headless_frame.resize`` is unavailable
    (older ovui build, no ovui rebuild applied), ``_do_resize``
    returns ``False`` rather than fake-success the bridge update."""
    set_window_size_mock = MagicMock(return_value=False)
    standalone_module = MagicMock()
    standalone_module.set_window_size = set_window_size_mock
    # headless_frame submodule exists but has no ``resize`` attribute.
    headless_frame_module = MagicMock(spec=[])
    standalone_module.headless_frame = headless_frame_module
    monkeypatch.setitem(sys.modules, "omni.ui.standalone", standalone_module)
    monkeypatch.setitem(
        sys.modules, "omni.ui.standalone.headless_frame", headless_frame_module,
    )
    bridge = RemoteInputBridge(width=1, height=1)
    headless_app.set_remote_input_bridge(bridge)

    assert headless_app._do_resize(1280, 720) is False


def test_do_resize_returns_false_when_no_bridge_and_set_window_size_false(
    headless_app, monkeypatch,
) -> None:
    """Both paths refuse and no bridge is attached — error reply
    (no fake success)."""
    _stub_ovui_standalone(
        monkeypatch,
        set_window_size_return=False,
        headless_resize_return=False,
    )
    headless_app.set_remote_input_bridge(None)

    assert headless_app._do_resize(800, 600) is False


def test_do_resize_swallows_set_window_size_exceptions(
    headless_app, monkeypatch, capsys,
) -> None:
    """An exception raised by ``set_window_size`` (e.g. ovui not
    initialised) must not propagate. Falls through to the headless
    path; if that also succeeds, returns True."""
    standalone_module = MagicMock()
    standalone_module.set_window_size = MagicMock(side_effect=RuntimeError("not init"))
    headless_frame_module = MagicMock()
    headless_frame_module.resize = MagicMock(return_value=True)
    headless_frame_module.extent = MagicMock(return_value=(1024, 768))
    standalone_module.headless_frame = headless_frame_module
    monkeypatch.setitem(sys.modules, "omni.ui.standalone", standalone_module)
    monkeypatch.setitem(
        sys.modules, "omni.ui.standalone.headless_frame", headless_frame_module,
    )
    bridge = RemoteInputBridge(width=1, height=1)
    headless_app.set_remote_input_bridge(bridge)

    assert headless_app._do_resize(1024, 768) is True
    err = capsys.readouterr().err
    assert "set_window_size raised" in err


def test_message_dispatch_change_resolution_reports_success_in_headless(
    headless_app, monkeypatch,
) -> None:
    """End-to-end: a worker-thread ``changeResolutionRequest`` on a
    headless application drains on the main loop, falls through to
    the real ``headless_frame.resize`` path, verifies the new extent,
    and replies ``success``."""
    _stub_ovui_standalone(
        monkeypatch,
        set_window_size_return=False,        # GLFW path refuses (headless)
        headless_resize_return=True,          # real headless resize succeeds
        headless_extent=(1920, 1080),         # actual framebuffer matches request
    )
    send = MagicMock()
    dispatcher = _attach_message_dispatcher(headless_app, send)
    bridge = RemoteInputBridge(width=1, height=1)
    headless_app.set_remote_input_bridge(bridge)

    dispatcher.on_message(json.dumps({
        "event_type": "changeResolutionRequest",
        "payload": {"width": 1920, "height": 1080},
    }))
    send.assert_not_called()
    headless_app._drain_message_queue()

    reply = _decode_reply(send)
    assert reply == {
        "event_type": "changeResolutionConfirmation",
        "payload": {"result": "success", "width": 1920, "height": 1080},
    }


def test_message_dispatch_change_resolution_reports_error_when_no_resize_path(
    headless_app, monkeypatch,
) -> None:
    """End-to-end: when both ``set_window_size`` and the real headless
    resize refuse, the dispatcher reports a structured ``error`` reply
    rather than faking success."""
    _stub_ovui_standalone(
        monkeypatch,
        set_window_size_return=False,
        headless_resize_return=False,         # real headless path fails too
    )
    send = MagicMock()
    dispatcher = _attach_message_dispatcher(headless_app, send)
    headless_app.set_remote_input_bridge(None)

    dispatcher.on_message(json.dumps({
        "event_type": "changeResolutionRequest",
        "payload": {"width": 800, "height": 600},
    }))
    headless_app._drain_message_queue()

    reply = _decode_reply(send)
    assert reply["event_type"] == "changeResolutionConfirmation"
    assert reply["payload"]["result"] == "error"
    assert "refused" in reply["payload"]["error"]


# --------------------------------------------------------------------------
# Run-loop wiring
# --------------------------------------------------------------------------


def test_run_async_drains_message_queue_before_next_frame() -> None:
    """Static-source check: the main loop body must call
    ``self._drain_message_queue()`` before ``await ui.next_frame()``.
    Mirror of the Step 3.3 check for ``_drain_remote_input``."""
    import inspect
    import re

    from ovui_widgets.app.application import Application

    src = inspect.getsource(Application.run_async)
    m = re.search(r"while self\._running", src)
    assert m, "Application.run_async has no while self._running loop"
    body = src[m.start():]
    drain_at = body.find("self._drain_message_queue()")
    next_frame_at = body.find("await ui.next_frame()")
    assert drain_at != -1, (
        "Application.run_async loop body never calls _drain_message_queue"
    )
    assert next_frame_at != -1
    assert drain_at < next_frame_at, (
        "_drain_message_queue must precede ui.next_frame so application "
        "actions run on the same tick the message arrived"
    )
