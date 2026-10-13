# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Server side of stream performance logging: a per-frame timeline and per-second summaries.

The livestream tap reports each frame as it moves through the stream pipeline:

* ``produced`` — the renderer's frame was queued for the stream (copy launched), render thread;
* ``ready`` — its copy completed (observed by the publish thread);
* ``sent`` — ``stream_video`` returned, as a new frame or a repeat of the last one;
* ``dropped`` — a newer frame superseded it before it was sent.

Once per second the trace rolls a summary: frame counts, the intervals between produced frames and
between sent frames (percentiles, maximum, gaps longer than 1.5 periods), the queue latency from
produced to sent, ovstream QoS (round-trip delay, bitrate) and the client count. Summaries are kept in
memory (``stream_status`` → ``perf``) and, when a directory is configured, appended as JSON lines.
Every record carries ``wall`` (Unix seconds) so server and client logs can be merged by time.

``OVUI_STREAM_TRACE``: ``0`` (default) no file, ``1`` per-second summaries, ``frames`` summaries and
one line per sent frame.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional


def trace_mode() -> str:
    return os.environ.get("OVUI_STREAM_TRACE", "0").strip().lower()


def _percentiles(values: list) -> dict:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]  # noqa: E731
    return {"n": len(ordered), "p50": round(pick(0.5) * 1000, 2), "p95": round(pick(0.95) * 1000, 2),
            "p99": round(pick(0.99) * 1000, 2), "max": round(ordered[-1] * 1000, 2),
            "min": round(ordered[0] * 1000, 2)}


class StreamTrace:
    """Thread-safe frame timeline for one stream; cheap enough to run on every frame."""

    def __init__(self, fps: int, directory: Optional[Path] = None, label: str = "stream") -> None:
        self.period = 1.0 / max(1, int(fps))
        self.fps = int(fps)
        self.mode = trace_mode()
        self._lock = threading.Lock()
        self._offset = time.time() - time.perf_counter()
        self._file = None
        self.path: Optional[Path] = None
        if directory is not None and self.mode != "0":
            try:
                directory = Path(directory)
                directory.mkdir(parents=True, exist_ok=True)
                self.path = directory / f"{label}-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}.jsonl"
                self._file = open(self.path, "a", buffering=1)
            except OSError:
                self._file = None
        self._second_start = time.perf_counter()
        self._reset_window()
        self.last_summary: Optional[dict] = None
        self.history: deque = deque(maxlen=120)
        self.totals = {"produced": 0, "sent_new": 0, "repeats": 0, "dropped": 0, "late_sends": 0,
                       "producer_gaps": 0}
        self.qos: Optional[dict] = None
        self.clients = 0
        self._last_sent_t: Optional[float] = None
        self._last_produced_t: Optional[float] = None
        self.write({"event": "start", "fps": self.fps, "mode": self.mode})

    def wall(self, t_perf: float) -> float:
        return round(t_perf + self._offset, 6)

    def _reset_window(self) -> None:
        self._w = {"produced": 0, "sent_new": 0, "repeats": 0, "dropped": 0, "send_intervals": [],
                   "produce_intervals": [], "queue": [], "copy": [], "send_call": [], "in_flight": []}

    def write(self, record: dict) -> None:
        if self._file is None:
            return
        record.setdefault("wall", round(time.time(), 6))
        try:
            self._file.write(json.dumps(record, separators=(",", ":")) + "\n")
        except (OSError, ValueError):
            self._file = None

    # ── events ──

    def produced(self, seq: int, t: float, index: int = 0, frames: int = 1) -> None:
        with self._lock:
            self._w["produced"] += 1
            self.totals["produced"] += 1
            if self._last_produced_t is not None and index == 0:
                interval = t - self._last_produced_t
                self._w["produce_intervals"].append(interval)
                if interval > 1.5 * self.period * max(1, frames):
                    self.totals["producer_gaps"] += 1
            if index == 0:
                self._last_produced_t = t

    def dropped(self, count: int) -> None:
        if count:
            with self._lock:
                self._w["dropped"] += count
                self.totals["dropped"] += count

    def sent(self, seq: int, fresh: bool, t_produced: float, t_ready: Optional[float], t_sent: float,
             call_s: float, in_flight: int) -> None:
        with self._lock:
            w = self._w
            if fresh:
                w["sent_new"] += 1
                self.totals["sent_new"] += 1
                w["queue"].append(t_sent - t_produced)
                if t_ready is not None:
                    w["copy"].append(t_ready - t_produced)
            else:
                w["repeats"] += 1
                self.totals["repeats"] += 1
            if self._last_sent_t is not None:
                interval = t_sent - self._last_sent_t
                w["send_intervals"].append(interval)
                if interval > 1.5 * self.period:
                    self.totals["late_sends"] += 1
            self._last_sent_t = t_sent
            w["send_call"].append(call_s)
            w["in_flight"].append(in_flight)
        if self.mode == "frames":
            self.write({"event": "sent", "seq": seq, "fresh": fresh, "produced": self.wall(t_produced),
                        "ready": self.wall(t_ready) if t_ready is not None else None,
                        "sent": self.wall(t_sent), "call_ms": round(call_s * 1000, 3),
                        "in_flight": in_flight})

    def on_qos(self, status: Any) -> None:
        fields = ("recommended_width", "recommended_height", "recommended_fps", "average_rtd_ms",
                  "average_bitrate", "maximum_bitrate", "fec_percent")
        self.qos = {name: getattr(status, name, None) for name in fields}
        self.write({"event": "qos", **self.qos})

    def connection(self, connected: bool, clients: int) -> None:
        self.clients = clients
        self.write({"event": "connection", "connected": connected, "clients": clients})

    # ── summaries ──

    def tick(self, now: Optional[float] = None) -> Optional[dict]:
        """Roll the per-second summary when a second has elapsed (publish thread)."""
        now = time.perf_counter() if now is None else now
        if now - self._second_start < 1.0:
            return None
        with self._lock:
            w, elapsed = self._w, now - self._second_start
            self._reset_window()
            self._second_start = now
        period_ms = self.period * 1000
        sends = w["send_intervals"]
        summary = {
            "event": "second", "wall": self.wall(now), "seconds": round(elapsed, 3), "target_fps": self.fps,
            "clients": self.clients,
            "produced_fps": round(w["produced"] / elapsed, 1),
            "sent_fps": round((w["sent_new"] + w["repeats"]) / elapsed, 1),
            "new_fps": round(w["sent_new"] / elapsed, 1),
            "repeats": w["repeats"], "dropped": w["dropped"],
            "send_interval_ms": _percentiles(sends),
            "late_sends": sum(1 for i in sends if i * 1000 > 1.5 * period_ms),
            "produce_interval_ms": _percentiles(w["produce_intervals"]),
            "queue_ms": _percentiles(w["queue"]),
            "copy_ms": _percentiles(w["copy"]),
            "send_call_ms": _percentiles(w["send_call"]),
            "in_flight_max": max(w["in_flight"]) if w["in_flight"] else 0,
            "qos": self.qos,
        }
        self.last_summary = summary
        self.history.append(summary)
        self.write(summary)
        return summary

    def snapshot(self) -> dict:
        """For ``stream_status``: the last per-second summary, totals and the log path."""
        return {"last_second": self.last_summary, "totals": dict(self.totals), "qos": self.qos,
                "log": str(self.path) if self.path else None, "mode": self.mode}

    def close(self) -> None:
        self.write({"event": "stop", "totals": self.totals})
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
