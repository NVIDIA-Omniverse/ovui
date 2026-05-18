# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for the Step 3.7 Kit-style custom-message dispatcher.

Two-thread design (Codex Step 3.7 review fix #1): ``on_message``
parses the envelope and enqueues a work item on the ovstream worker
thread; the main loop calls ``drain_pending(open_stage_fn=...,
resize_fn=...)`` to run the application action and emit the reply.

The wire format mirrors what `web-viewer-sample`'s
``_handleCustomEvent`` (``Window.tsx:317–376``) produces and consumes:
flat JSON ``{ "event_type": "...", "payload": {...} }``.
"""

from __future__ import annotations

import json
import threading
from unittest.mock import MagicMock

import pytest

from ovwidgets.app._message_dispatcher import MessageDispatcher

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _make_dispatcher(send=None) -> tuple[MessageDispatcher, MagicMock]:
    send = send if send is not None else MagicMock()
    dispatcher = MessageDispatcher(send_message_fn=send)
    return dispatcher, send


def _drain(dispatcher: MessageDispatcher, *, open_stage=None, resize=None) -> int:
    open_stage = open_stage if open_stage is not None else MagicMock()
    resize = resize if resize is not None else MagicMock(return_value=True)
    return dispatcher.drain_pending(
        open_stage_fn=open_stage,
        resize_fn=resize,
    )


def _decode_reply(send_mock: MagicMock, index: int = 0) -> dict:
    raw = send_mock.call_args_list[index].args[0]
    return json.loads(raw)


# --------------------------------------------------------------------------
# Codex Step 3.7 fix #1 — actions and replies must NOT run inline on the
# worker thread.
# --------------------------------------------------------------------------


def test_on_message_does_not_call_open_stage_inline() -> None:
    """``on_message`` runs on the ovstream worker thread. The
    application's ``open_file`` callable must not be invoked inline —
    it touches stage/UI state and must run on the main loop instead.
    """
    dispatcher, send = _make_dispatcher()
    open_stage = MagicMock()
    resize = MagicMock(return_value=True)

    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {"url": "/tmp/scene.usda"},
    }))

    open_stage.assert_not_called()
    send.assert_not_called()
    # Main-loop drain runs the action and emits the reply.
    dispatcher.drain_pending(open_stage_fn=open_stage, resize_fn=resize)
    open_stage.assert_called_once_with("/tmp/scene.usda")
    assert send.call_count == 1


def test_on_message_does_not_call_resize_inline() -> None:
    """Symmetric guard for ``changeResolutionRequest`` — the resize
    callable (``omni.ui.standalone.set_window_size`` /
    ``Application._do_resize`` in production) is also UI-state work."""
    dispatcher, send = _make_dispatcher()
    open_stage = MagicMock()
    resize = MagicMock(return_value=True)

    dispatcher.on_message(json.dumps({
        "event_type": "changeResolutionRequest",
        "payload": {"width": 1920, "height": 1080},
    }))

    resize.assert_not_called()
    send.assert_not_called()
    dispatcher.drain_pending(open_stage_fn=open_stage, resize_fn=resize)
    resize.assert_called_once_with(1920, 1080)
    assert send.call_count == 1


def test_on_message_validation_error_reply_is_deferred_until_drain() -> None:
    """Even validation errors (missing url, bad dims) defer their
    reply emit to the main-loop drain, so the ``send_message`` channel
    is exercised from a single thread."""
    dispatcher, send = _make_dispatcher()
    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {},  # missing 'url'
    }))
    send.assert_not_called()
    _drain(dispatcher)
    assert send.call_count == 1
    reply = _decode_reply(send)
    assert reply["payload"]["result"] == "error"


def test_drain_runs_multiple_queued_items_in_order() -> None:
    dispatcher, send = _make_dispatcher()
    open_stage = MagicMock()
    resize = MagicMock(return_value=True)

    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {"url": "/a.usda"},
    }))
    dispatcher.on_message(json.dumps({
        "event_type": "changeResolutionRequest",
        "payload": {"width": 800, "height": 600},
    }))
    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {"url": "/b.usda"},
    }))

    assert dispatcher.drain_pending(
        open_stage_fn=open_stage, resize_fn=resize,
    ) == 3
    assert open_stage.call_args_list == [
        ((("/a.usda",)), {}),
        ((("/b.usda",)), {}),
    ]
    resize.assert_called_once_with(800, 600)
    assert send.call_count == 3


def test_drain_clears_queue_after_running() -> None:
    dispatcher, _send = _make_dispatcher()
    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {"url": "/a.usda"},
    }))
    _drain(dispatcher)
    # Second drain has nothing to do.
    assert _drain(dispatcher) == 0


def test_drain_continues_past_action_exception() -> None:
    """An action that raises must turn into an "error" reply for that
    item but not abort the rest of the queue."""
    dispatcher, send = _make_dispatcher()
    open_stage = MagicMock(side_effect=[FileNotFoundError("no a"), None])

    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {"url": "/a.usda"},
    }))
    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {"url": "/b.usda"},
    }))
    _drain(dispatcher, open_stage=open_stage)

    assert open_stage.call_count == 2
    assert send.call_count == 2
    reply_a = _decode_reply(send, 0)
    reply_b = _decode_reply(send, 1)
    assert reply_a["payload"]["result"] == "error"
    assert reply_a["payload"]["url"] == "/a.usda"
    assert reply_b["payload"]["result"] == "success"
    assert reply_b["payload"]["url"] == "/b.usda"


# --------------------------------------------------------------------------
# openStageRequest
# --------------------------------------------------------------------------


def test_open_stage_request_invokes_open_stage_and_replies_success() -> None:
    dispatcher, send = _make_dispatcher()
    open_stage = MagicMock()

    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {"url": "/tmp/scene.usda"},
    }))
    _drain(dispatcher, open_stage=open_stage)

    open_stage.assert_called_once_with("/tmp/scene.usda")
    reply = _decode_reply(send)
    assert reply == {
        "event_type": "openedStageResult",
        "payload": {"result": "success", "url": "/tmp/scene.usda"},
    }


def test_open_stage_request_with_missing_url_replies_error() -> None:
    dispatcher, send = _make_dispatcher()
    open_stage = MagicMock()

    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {},
    }))
    _drain(dispatcher, open_stage=open_stage)

    open_stage.assert_not_called()
    reply = _decode_reply(send)
    assert reply["event_type"] == "openedStageResult"
    assert reply["payload"]["result"] == "error"
    assert reply["payload"]["url"] == ""
    assert "missing" in reply["payload"]["error"]


def test_open_stage_request_when_action_raises_replies_error() -> None:
    dispatcher, send = _make_dispatcher()
    open_stage = MagicMock(side_effect=FileNotFoundError("no such file"))

    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {"url": "/tmp/missing.usda"},
    }))
    _drain(dispatcher, open_stage=open_stage)

    reply = _decode_reply(send)
    assert reply["payload"]["result"] == "error"
    assert reply["payload"]["url"] == "/tmp/missing.usda"
    assert "FileNotFoundError" in reply["payload"]["error"]


def test_open_stage_request_with_non_string_url_replies_error() -> None:
    dispatcher, send = _make_dispatcher()
    open_stage = MagicMock()
    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {"url": 12345},
    }))
    _drain(dispatcher, open_stage=open_stage)

    open_stage.assert_not_called()
    reply = _decode_reply(send)
    assert reply["payload"]["result"] == "error"


# --------------------------------------------------------------------------
# changeResolutionRequest
# --------------------------------------------------------------------------


def test_change_resolution_request_invokes_resize_and_replies_success() -> None:
    dispatcher, send = _make_dispatcher()
    resize = MagicMock(return_value=True)

    dispatcher.on_message(json.dumps({
        "event_type": "changeResolutionRequest",
        "payload": {"width": 1920, "height": 1080},
    }))
    _drain(dispatcher, resize=resize)

    resize.assert_called_once_with(1920, 1080)
    reply = _decode_reply(send)
    assert reply == {
        "event_type": "changeResolutionConfirmation",
        "payload": {"result": "success", "width": 1920, "height": 1080},
    }


def test_change_resolution_request_when_resize_returns_false_replies_error() -> None:
    """When the resize callable explicitly refuses (returns ``False``),
    the dispatcher reports a structured error rather than swallowing it."""
    dispatcher, send = _make_dispatcher()
    resize = MagicMock(return_value=False)

    dispatcher.on_message(json.dumps({
        "event_type": "changeResolutionRequest",
        "payload": {"width": 800, "height": 600},
    }))
    _drain(dispatcher, resize=resize)

    reply = _decode_reply(send)
    assert reply["payload"]["result"] == "error"
    assert "refused" in reply["payload"]["error"]


def test_change_resolution_request_when_resize_returns_none_replies_success() -> None:
    """An application-level resize hook that returns ``None`` on
    success is treated as success."""
    dispatcher, send = _make_dispatcher()
    resize = MagicMock(return_value=None)

    dispatcher.on_message(json.dumps({
        "event_type": "changeResolutionRequest",
        "payload": {"width": 1280, "height": 720},
    }))
    _drain(dispatcher, resize=resize)

    reply = _decode_reply(send)
    assert reply["payload"]["result"] == "success"


def test_change_resolution_request_when_resize_raises_replies_error() -> None:
    dispatcher, send = _make_dispatcher()
    resize = MagicMock(side_effect=RuntimeError("backend asleep"))

    dispatcher.on_message(json.dumps({
        "event_type": "changeResolutionRequest",
        "payload": {"width": 1920, "height": 1080},
    }))
    _drain(dispatcher, resize=resize)

    reply = _decode_reply(send)
    assert reply["payload"]["result"] == "error"
    assert "RuntimeError" in reply["payload"]["error"]


@pytest.mark.parametrize(
    "payload",
    [
        {"width": 0, "height": 1080},
        {"width": -1, "height": 1080},
        {"width": 1920, "height": 0},
        {"width": "1920", "height": "1080"},
        {"width": 1920.0, "height": 1080.0},
        {"width": True, "height": 1080},
        {"height": 1080},
        {},
    ],
)
def test_change_resolution_request_invalid_payload_does_not_call_resize(
    payload: dict,
) -> None:
    dispatcher, send = _make_dispatcher()
    resize = MagicMock(return_value=True)

    dispatcher.on_message(json.dumps({
        "event_type": "changeResolutionRequest",
        "payload": payload,
    }))
    _drain(dispatcher, resize=resize)

    resize.assert_not_called()
    reply = _decode_reply(send)
    assert reply["payload"]["result"] == "error"


# --------------------------------------------------------------------------
# Unknown / malformed
# --------------------------------------------------------------------------


def test_unknown_event_type_is_silently_dropped() -> None:
    dispatcher, send = _make_dispatcher()
    open_stage = MagicMock()
    resize = MagicMock()
    dispatcher.on_message(json.dumps({
        "event_type": "futureFeatureRequest",
        "payload": {"x": 1},
    }))
    _drain(dispatcher, open_stage=open_stage, resize=resize)

    open_stage.assert_not_called()
    resize.assert_not_called()
    send.assert_not_called()


def test_malformed_json_is_silently_dropped() -> None:
    dispatcher, send = _make_dispatcher()
    dispatcher.on_message("{not valid json")
    _drain(dispatcher)
    send.assert_not_called()


def test_non_object_envelope_is_silently_dropped() -> None:
    dispatcher, send = _make_dispatcher()
    dispatcher.on_message(json.dumps([1, 2, 3]))
    dispatcher.on_message(json.dumps("hello"))
    _drain(dispatcher)
    send.assert_not_called()


def test_empty_message_is_silently_dropped() -> None:
    dispatcher, send = _make_dispatcher()
    dispatcher.on_message("")
    _drain(dispatcher)
    send.assert_not_called()


def test_payload_not_an_object_is_treated_as_empty() -> None:
    dispatcher, send = _make_dispatcher()
    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": "not-a-dict",
    }))
    _drain(dispatcher)
    reply = _decode_reply(send)
    assert reply["payload"]["result"] == "error"


def test_send_message_failure_does_not_propagate(capsys: pytest.CaptureFixture) -> None:
    send = MagicMock(side_effect=RuntimeError("conn closed"))
    dispatcher, _send = _make_dispatcher(send=send)
    dispatcher.on_message(json.dumps({
        "event_type": "openStageRequest",
        "payload": {"url": "/x.usda"},
    }))
    _drain(dispatcher)  # must not raise
    assert "send failed" in capsys.readouterr().err


def test_on_message_is_thread_safe() -> None:
    """The worker thread can fire ``on_message`` concurrently with
    a main-loop ``drain_pending`` call. The lock-protected deque
    ensures every queued action is dispatched exactly once."""
    dispatcher, send = _make_dispatcher()
    open_stage = MagicMock()
    n_threads = 4
    n_per_thread = 50

    def producer(start: int) -> None:
        for i in range(n_per_thread):
            dispatcher.on_message(json.dumps({
                "event_type": "openStageRequest",
                "payload": {"url": f"/p{start + i}.usda"},
            }))

    threads = [
        threading.Thread(target=producer, args=(t * 1000,))
        for t in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    drained = dispatcher.drain_pending(
        open_stage_fn=open_stage,
        resize_fn=MagicMock(),
    )
    assert drained == n_threads * n_per_thread
    assert open_stage.call_count == n_threads * n_per_thread
    assert send.call_count == n_threads * n_per_thread
