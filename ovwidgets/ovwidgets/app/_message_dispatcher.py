# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tier 3 custom-message envelope dispatcher (issue #34, Step 3.7).

The ovstream :class:`Server` exposes a generic message channel through
``send_message(text)`` and the ``on_message`` callback. Kit-style web
clients (`web-viewer-sample <https://github.com/NVIDIA-Omniverse/web-viewer-sample>`_)
use that channel for application-level RPCs encoded as a flat JSON
envelope::

    { "event_type": "openStageRequest", "payload": { "url": "..." } }

This module owns the ovgear side of that protocol. The
``MessageDispatcher`` is split across **two threads**:

1. ``on_message(text)`` runs on the ovstream worker thread. It only
   parses the envelope, validates field shapes, and enqueues a work
   item — it never touches application or UI state. This avoids the
   sticky-state failure mode Codex flagged in Step 3.7 review:
   driving ``Application.open_file`` or ``omni.ui.standalone.set_window_size``
   off the main loop is a thread-safety hazard.
2. ``drain_pending(*, open_stage_fn, resize_fn)`` runs on the main
   loop (alongside :meth:`Application._drain_remote_input`) and pops
   the queue. Application actions and reply emits both happen here.

The actions are injected so the dispatcher has no direct dependency
on :mod:`ovwidgets.app.application` or :mod:`omni.ui` — both can be replaced
with mocks in tests.

The reply format mirrors the request:

* ``openStageRequest``       → ``openedStageResult`` with
  ``payload.result = "success" | "error"`` and ``payload.url``.
* ``changeResolutionRequest`` → ``changeResolutionConfirmation`` with
  ``payload.result = "success" | "error"`` plus ``payload.width`` /
  ``payload.height``.

Any other ``event_type`` is dropped silently with a stderr log so a
forward-compat client extension cannot disable the streaming pipeline.
Malformed JSON, missing fields, ill-typed fields, exceptions raised
by the action callables, and ``send_message_fn`` raising all turn
into structured ``"error"`` replies (when the request type is
recognised) or stderr logs.
"""

from __future__ import annotations

import json
import sys
import threading
from collections import deque
from typing import Any, Callable, Deque, Optional

# Action callable shapes — kept loose so the application can pass
# ``Application.open_file`` (returns ``None``) and a custom
# ``_do_resize`` (returns ``bool``) without extra adapters.
OpenStageFn = Callable[[str], Any]
ResizeFn = Callable[[int, int], Any]
SendMessageFn = Callable[[str], None]


class MessageDispatcher:
    """Two-thread dispatcher: parse on worker, run on main loop."""

    def __init__(self, *, send_message_fn: SendMessageFn) -> None:
        self._send = send_message_fn
        self._lock = threading.Lock()
        self._pending: Deque[dict] = deque()

    # ------------------------------------------------------------------
    # Worker-thread side — wire to ``Server.on_message``
    # ------------------------------------------------------------------

    def on_message(self, text: str) -> None:
        """Parse one envelope and enqueue a work item.

        Runs on the ovstream worker thread; never raises so a
        malformed message can't tear the SDK callback path down.
        Never invokes the application action callables — those run on
        the main loop in :meth:`drain_pending`. Validation errors
        produce a "reply" work item that the main-loop drain will
        emit; this keeps the ``send_message`` channel exercised from a
        single thread.
        """
        action = self._parse(text)
        if action is None:
            return
        with self._lock:
            self._pending.append(action)

    # ------------------------------------------------------------------
    # Main-loop side — call once per frame from
    # ``Application._drain_message_queue``
    # ------------------------------------------------------------------

    def drain_pending(
        self,
        *,
        open_stage_fn: OpenStageFn,
        resize_fn: ResizeFn,
    ) -> int:
        """Drain queued work items, run the matching action and emit
        the reply envelope.

        Returns the number of items processed (useful for tests and
        debugging). Each work item is independently exception-safe —
        an action that raises is reported back as an ``"error"`` reply
        and the loop continues with the next item.
        """
        with self._lock:
            items = list(self._pending)
            self._pending.clear()
        for action in items:
            self._run_action(
                action,
                open_stage_fn=open_stage_fn,
                resize_fn=resize_fn,
            )
        return len(items)

    # ------------------------------------------------------------------
    # Parsing (worker thread)
    # ------------------------------------------------------------------

    def _parse(self, text: str) -> Optional[dict]:
        envelope = self._parse_envelope(text)
        if envelope is None:
            return None
        event_type = envelope.get("event_type")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        if event_type == "openStageRequest":
            url = payload.get("url")
            if not isinstance(url, str) or not url:
                # Validation error: enqueue a reply-only item so the
                # main-loop drain emits it through the same path.
                return {
                    "kind": "reply",
                    "event_type": "openedStageResult",
                    "payload": {
                        "result": "error",
                        "url": "",
                        "error": "missing 'url'",
                    },
                }
            return {"kind": "open_stage", "url": url}

        if event_type == "changeResolutionRequest":
            width = payload.get("width")
            height = payload.get("height")
            if not _valid_dim(width) or not _valid_dim(height):
                return {
                    "kind": "reply",
                    "event_type": "changeResolutionConfirmation",
                    "payload": {
                        "result": "error",
                        "width": _coerce_int(width),
                        "height": _coerce_int(height),
                        "error": "invalid 'width'/'height'",
                    },
                }
            return {"kind": "change_resolution",
                    "width": int(width), "height": int(height)}

        # Forward-compatible: drop unknown event types with a log so a
        # future client extension cannot break the pipeline. No reply.
        print(
            f"[ovgear/livestream] unknown custom message "
            f"event_type={event_type!r}; ignored",
            file=sys.stderr,
        )
        return None

    def _parse_envelope(self, text: str) -> Optional[dict]:
        if not isinstance(text, str) or not text:
            print(
                "[ovgear/livestream] custom message dropped: empty/non-str",
                file=sys.stderr,
            )
            return None
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError as exc:
            print(
                f"[ovgear/livestream] custom message JSON decode "
                f"failed: {exc}",
                file=sys.stderr,
            )
            return None
        if not isinstance(envelope, dict):
            print(
                "[ovgear/livestream] custom message envelope is not "
                "a JSON object; ignored",
                file=sys.stderr,
            )
            return None
        return envelope

    # ------------------------------------------------------------------
    # Execution (main loop)
    # ------------------------------------------------------------------

    def _run_action(
        self,
        action: dict,
        *,
        open_stage_fn: OpenStageFn,
        resize_fn: ResizeFn,
    ) -> None:
        kind = action["kind"]
        if kind == "reply":
            self._send_envelope(action["event_type"], action["payload"])
            return
        if kind == "open_stage":
            url = action["url"]
            try:
                open_stage_fn(url)
            except Exception as exc:
                self._send_envelope("openedStageResult", {
                    "result": "error",
                    "url": url,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                return
            self._send_envelope("openedStageResult", {
                "result": "success", "url": url,
            })
            return
        if kind == "change_resolution":
            width = action["width"]
            height = action["height"]
            try:
                ok = resize_fn(width, height)
            except Exception as exc:
                self._send_envelope("changeResolutionConfirmation", {
                    "result": "error",
                    "width": width,
                    "height": height,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                return
            # ``None`` is treated as success because some application-
            # level resize hooks return ``None`` on success. Only an
            # explicit ``False`` is a refusal.
            if ok is None or ok:
                self._send_envelope("changeResolutionConfirmation", {
                    "result": "success",
                    "width": width,
                    "height": height,
                })
            else:
                self._send_envelope("changeResolutionConfirmation", {
                    "result": "error",
                    "width": width,
                    "height": height,
                    "error": "resize backend refused",
                })
            return
        # Unknown kind shouldn't happen — _parse only emits the kinds
        # handled above. Log defensively rather than raise.
        print(
            f"[ovgear/livestream] internal: unknown action kind "
            f"{kind!r}; dropped",
            file=sys.stderr,
        )

    def _send_envelope(self, event_type: str, payload: dict) -> None:
        envelope = {"event_type": event_type, "payload": payload}
        try:
            self._send(json.dumps(envelope))
        except Exception as exc:
            print(
                f"[ovgear/livestream] custom message send failed: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------

def _valid_dim(value: Any) -> bool:
    """Reject non-int, bool (subclass of int), zero, and negatives."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
    )


def _coerce_int(value: Any) -> int:
    """Best-effort int conversion for echoing back invalid dimensions
    in error replies. Anything non-int becomes 0."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0
