# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Recorder catch-up uses one serialized worker job per selected capture."""

import asyncio
import json
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ovui_widgets.app.media import Media, _encode_recording_batch


@pytest.mark.parametrize("fail_current", [False, True])
def test_catch_up_batches_repeats_and_preserves_observation_counts(
    tmp_path, monkeypatch, fail_current
):
    async def run():
        owner = threading.get_ident()
        app = SimpleNamespace(
            artifacts=tmp_path, config={"width": 2, "height": 2}, active_view="primary"
        )
        media = Media(app)
        media.record_active = True
        media.release_export = Mock()
        now = time.monotonic()
        media.latest_record_frame = (1, "first", now, {"frame_id": 1})
        sends = []
        encoder_events = []
        worker_calls = []
        busy = False

        class Encoder:
            def send(self, frame):
                nonlocal busy
                if frame is None:
                    assert threading.get_ident() != owner
                    return
                assert threading.get_ident() != owner
                assert not busy, "Concurrent access to the encoder"
                busy = True
                try:
                    encoder_events.append(("send", frame))
                    if fail_current and frame == "latest":
                        raise RuntimeError("encoder failed on selected frame")
                    sends.append(frame)
                finally:
                    busy = False

            def close(self):
                assert threading.get_ident() != owner
                assert not busy, "Encoder closed during a write"
                encoder_events.append(("close", None))

        encoder = Encoder()
        monkeypatch.setitem(
            sys.modules, "imageio_ffmpeg", SimpleNamespace(write_frames=lambda *a, **k: encoder)
        )
        original_to_thread = asyncio.to_thread

        async def observe_worker(fn, *args):
            worker_calls.append(fn)
            result = await original_to_thread(fn, *args)
            if fn is _encode_recording_batch:
                if worker_calls.count(_encode_recording_batch) == 1:
                    # Captures may advance while encoding. The latest-slot
                    # contract selects only the last; never count skipped
                    # sequences as observations, nor held images as fresh.
                    for sequence in (2, 3, 4):
                        media.latest_record_frame = (
                            sequence,
                            "latest",
                            now + sequence - 1,
                            {"frame_id": sequence},
                        )
                else:
                    media.record_stop = True
            return result

        monkeypatch.setattr(asyncio, "to_thread", observe_worker)
        await asyncio.wait_for(media.record("primary", fps=10, max_seconds=10), timeout=5)
        assert worker_calls.count(_encode_recording_batch) == 2
        assert len(worker_calls) == 4  # initialize, two batches, serialized close
        assert sends == ["first"] * 30 + ([] if fail_current else ["latest"])
        assert encoder_events[-1] == ("close", None)
        assert sum(kind == "close" for kind, _ in encoder_events) == 1
        media.release_export.assert_called_once()
        assert not media.record_active
        report = json.loads(next(tmp_path.glob("recording-*.json")).read_text())
        assert report["frame_count"] == (30 if fail_current else 31)
        assert report["observed_frame_count"] == (1 if fail_current else 2)
        assert report["duplicated_frame_count"] == 29
        assert [f["state"]["frame_id"] for f in report["frames"]] == (
            [1] if fail_current else [1, 4]
        )
        assert bool(report["error"]) is fail_current
        assert media.record_result["ok"] is not fail_current

    asyncio.run(run())


def test_encoder_initialization_failure_finalizes_recording_state(tmp_path, monkeypatch):
    async def run():
        app = SimpleNamespace(
            artifacts=tmp_path, config={"width": 2, "height": 2}, active_view="primary"
        )
        media = Media(app)
        media.record_active = True
        media.release_export = Mock()
        encoder = SimpleNamespace(
            send=Mock(side_effect=RuntimeError("encoder init failed")), close=Mock()
        )
        monkeypatch.setitem(
            sys.modules, "imageio_ffmpeg", SimpleNamespace(write_frames=lambda *a, **kw: encoder)
        )
        await media.record("primary", fps=5, max_seconds=1)
        assert not media.record_active
        assert media.record_result["ok"] is False
        assert "encoder init failed" in media.record_result["error"]
        assert media.record_result["frame_count"] == 0
        encoder.close.assert_called_once()
        media.release_export.assert_called_once()

    asyncio.run(run())


def test_recording_holds_the_last_image_until_stop(tmp_path, monkeypatch):
    import ovui_widgets.app.media as module

    clock = {"now": 100.0}
    monkeypatch.setattr(
        module, "time", SimpleNamespace(monotonic=lambda: clock["now"], time_ns=time.time_ns)
    )
    sends = []
    # Finalizing the MP4 takes time; it is not recording time.
    encoder = SimpleNamespace(
        send=lambda frame: frame is not None and sends.append(frame),
        close=lambda: clock.update(now=clock["now"] + 0.5),
    )
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", SimpleNamespace(write_frames=lambda *a, **k: encoder))
    app = SimpleNamespace(artifacts=tmp_path, config={"width": 2, "height": 2}, active_view="primary")
    media = Media(app)
    media.record_active = True
    media.release_export = Mock()
    media.latest_record_frame = (1, "a", 100.0, {"frame_id": 1})

    async def run():
        task = asyncio.create_task(media.record("primary", fps=10, max_seconds=60))
        await asyncio.sleep(0.05)
        media.latest_record_frame = (2, "b", 101.0, {"frame_id": 2})
        await asyncio.sleep(0.05)
        clock["now"] = 102.0  # stop requested 1 s after the last capture
        media.record_stop = True
        await asyncio.wait_for(task, timeout=5)

    asyncio.run(run())
    report = json.loads(next(tmp_path.glob("recording-*.json")).read_text())
    # Wall-clock timing holds through the tail as well as through misses.
    assert report["frame_count"] == 20 and sends == ["a"] * 10 + ["b"] * 10
    assert report["encoded_duration_seconds"] == pytest.approx(report["elapsed_seconds"]) == 2.0


def test_failed_recording_start_keeps_the_previous_receipt(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", SimpleNamespace())
    app = SimpleNamespace(
        artifacts=tmp_path, config={"width": 2, "height": 2}, active_view="primary",
        get_media_viewports=lambda: {"primary": object()},
    )
    media = Media(app)
    previous = {"ok": True, "recording": False, "frame_count": 42}
    media.record_result = previous
    media.ensure_export = Mock(side_effect=RuntimeError("export unavailable"))
    media.release_export = Mock()
    with pytest.raises(RuntimeError, match="export unavailable"):
        asyncio.run(media.command("recording_start", {"view_id": None, "fps": 10, "max_seconds": 5}))
    assert media.recording_status() == previous
