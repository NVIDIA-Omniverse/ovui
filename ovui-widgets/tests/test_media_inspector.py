# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Shared media source selection, lifecycle, isolation and discovery."""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from ovui_widgets.app.media import Media, ReferenceMediaHost
from ovui_widgets.app.media_inspector import media_commands
from ovui_widgets.common.inspector_runtime import inspector_runtime


@pytest.fixture(autouse=True)
def installed_inspector_runtime(monkeypatch):
    # Preserve installed-release validation; never add a checkout package path.
    monkeypatch.setenv("OVUIINSPECT_ENABLED", "0")
    with inspector_runtime():
        yield


def commands(media):
    return {command.name: command for command in media_commands(lambda: media)}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    surface = SimpleNamespace(get_inspector_viewport_rect=lambda: (11.1, 20, 801, 401))
    views = {"primary": surface}
    app = SimpleNamespace(
        activate=Mock(),
        settle=AsyncMock(),
        active_view="primary",
        get_media_viewports=lambda: views,
        artifacts=tmp_path,
        config={"width": 1280, "height": 720},
    )
    renderer = SimpleNamespace(
        attach_render_product_stream=Mock(), detach_render_product_stream=Mock()
    )
    app.get_media_render_product = lambda view_id: {
        "renderer": renderer,
        "product_path": "/Render/Primary",
        "extent": (960, 540),
    }
    media = Media(app)
    export = SimpleNamespace(
        extent=lambda: (1280, 720),
        wait_ready=lambda timeout: True,
        copy_to_linear=lambda *args: True,
        signal_consumed=Mock(),
        shutdown=Mock(),
    )
    cuda = SimpleNamespace(
        current_context=lambda: 123,
        malloc_pitch=lambda *args: (1000, 5120),
        d2d_region=Mock(),
        free=Mock(),
    )

    def ensure():
        media.headless = export
        media.cuda = cuda
        media.owns_export = True

    media.ensure_export = ensure
    taps = []

    class Tap:
        def __init__(self, **kwargs):
            self.submitted_frames = 0
            self.configuration = kwargs
            self.start = Mock()
            self.close = Mock()
            self.tee_linear_to_ovstream = Mock(return_value=True)
            self.status = lambda: ("STREAMING", 1, None)
            self.set_input_bridge = Mock()
            taps.append(self)

    monkeypatch.setattr("ovui_data_adapters.common._livestream_tap._Cudart", lambda: cuda)
    monkeypatch.setitem(
        sys.modules,
        "ovstream",
        SimpleNamespace(
            initialize=Mock(), shutdown=Mock(), LogLevel=SimpleNamespace(INFO=1, WARNING=2)
        ),
    )
    monkeypatch.setattr("ovui_data_adapters.common._livestream_tap.LivestreamTap", Tap)
    return media, views, taps, export, cuda


def test_shared_registry_defaults_and_input_validation(rig):
    media, *_ = rig
    registry = commands(media)
    assert set(registry) == {
        "stream_start",
        "stream_stop",
        "stream_status",
        "recording_start",
        "recording_stop",
        "recording_status",
    }
    model = registry["stream_start"].arguments
    assert model().media_port == 47998
    assert model(protocol="native").media_port == 47999
    assert model(protocol="rtsp").media_port == 8554
    with pytest.raises(ValueError):
        model(allow_input=True)
    with pytest.raises(ValueError):
        model(source="application", protocol="rtsp", allow_input=True)
    with pytest.raises(ValueError):
        model(fps=0)
    with pytest.raises(ValueError):
        model(unknown=1)


def test_viewport_stream_binds_render_product_without_compositor(rig):
    media, views, taps, export, cuda = rig

    async def run():
        model = commands(media)["stream_start"].arguments
        before = dict(os.environ)
        result = await media.command("stream_start", model().model_dump())
        assert dict(os.environ) == before
        assert result["extent"] == (960, 540)
        assert result["pixel_source"] == "render_product_cuda"
        assert result["render_product_path"] == "/Render/Primary"
        assert media.headless is None
        media.stream_renderer.attach_render_product_stream.assert_called_once_with(
            taps[0], "/Render/Primary"
        )
        media.export_frame()
        taps[0].tee_linear_to_ovstream.assert_not_called()
        assert media.submitted_frames == 0
        renderer = media.stream_renderer
        result = await media.command("stream_stop", {})
        renderer.detach_render_product_stream.assert_called_once_with(taps[0])
        assert result["state"] == "OFF" and result["connection"] is None
        await media.close()

    asyncio.run(run())


def test_whole_application_stop_does_not_stop_recording(rig):
    media, views, taps, export, _ = rig

    async def run():
        model = commands(media)["stream_start"].arguments
        result = await media.command("stream_start", model(source="application").model_dump())
        assert result["extent"] == (1280, 720)
        media.app.activate.assert_not_called()
        media.export_frame()
        taps[0].tee_linear_to_ovstream.assert_called_once_with(1000, 1280, 720, 5120)
        media.record_active = True
        await media.command("stream_stop", {})
        assert media.record_active and media.headless is export
        assert media.stream_config is None
        await media.command("stream_stop", {})
        assert taps[0].close.call_count == 1
        media.record_active = False
        await media.close()
        export.shutdown.assert_called_once()

    asyncio.run(run())


def test_restart_failure_cleans_up_and_status_remains_readable(rig):
    media, _, taps, export, _ = rig

    async def run():
        registry = commands(media)
        args = registry["stream_start"].arguments().model_dump()
        await media.command("stream_start", args)
        with pytest.raises(ValueError, match="already active"):
            await media.command("stream_start", args)
        await media.command("stream_stop", {})
        media.app.settle.side_effect = RuntimeError("render unavailable")
        with pytest.raises(RuntimeError, match="render unavailable"):
            await media.command("stream_start", args)
        assert media.headless is None and media.tap is None
        status = await registry["stream_status"].handler()
        assert status["state"] == "ERROR" and "render unavailable" in status["error"]
        await media.command("stream_stop", {})
        await media.close()

    asyncio.run(run())


def test_reference_status_does_not_take_over_legacy_export(tmp_path, monkeypatch):
    monkeypatch.setenv("OVUI_MEDIA_DIRECTORY", str(tmp_path / "not-created"))
    legacy = SimpleNamespace(
        status=lambda: ("STREAMING", 1, None),
        protocol="webrtc",
        signal_port=50001,
        media_port=50002,
        public_ip=None,
    )
    app = SimpleNamespace(
        _headless_tap=legacy, _teardown_headless_export=Mock(), set_remote_input_bridge=Mock()
    )
    media = Media(ReferenceMediaHost(app))

    async def run():
        result = await media.command("stream_status", {})
        assert result["state"] == "STREAMING"
        app._teardown_headless_export.assert_not_called()
        assert not (tmp_path / "not-created").exists()
        await media.command("stream_stop", {})
        app._teardown_headless_export.assert_called_once()
        assert media.owns_export

    asyncio.run(run())


def test_cancelled_stream_start_releases_export_and_can_retry(rig):
    media, _, taps, export, _ = rig

    async def run():
        model = commands(media)["stream_start"].arguments
        media.app.settle.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await media.command("stream_start", model(source="application").model_dump())
        assert media.headless is None and media.tap is None
        export.shutdown.assert_called_once()
        media.app.settle.side_effect = None
        await media.command("stream_start", model().model_dump())
        await media.close()

    asyncio.run(run())


@pytest.mark.parametrize("application_stream", [False, True])
def test_cancelled_recording_start_releases_only_unshared_export(rig, application_stream):
    media, _, _, export, _ = rig

    async def run():
        registry = commands(media)
        if application_stream:
            await media.command(
                "stream_start",
                registry["stream_start"].arguments(source="application").model_dump(),
            )
        media.app.settle.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await media.command(
                "recording_start", registry["recording_start"].arguments().model_dump()
            )
        assert not media.record_active and media.record_task is None
        assert (media.headless is export) is application_stream
        assert export.shutdown.call_count == (0 if application_stream else 1)
        media.app.settle.side_effect = None
        media.record = AsyncMock()
        await media.command("recording_start", registry["recording_start"].arguments().model_dump())
        await media.record_task
        media.record_active = False
        await media.close()

    asyncio.run(run())


def test_default_recording_preserves_visible_quad_and_rejects_hidden_view(rig):
    media, views, _, _, _ = rig
    views.clear()
    views.update({key: object() for key in ("front", "left", "top", "perspective")})
    media.app.active_view = "perspective"
    media.record = AsyncMock()

    async def run():
        model = commands(media)["recording_start"].arguments
        with pytest.raises(ValueError, match="preserves the current layout"):
            await media.command("recording_start", model(view_id="primary").model_dump())
        result = await media.command("recording_start", model().model_dump())
        assert result["view_id"] == "perspective"
        media.app.activate.assert_not_called()
        await media.record_task
        media.record_active = False
        await media.close()

    asyncio.run(run())


def test_native_tap_error_is_readable_and_stoppable_with_retained_connection(rig):
    media, _, taps, _, _ = rig

    async def run():
        args = commands(media)["stream_start"].arguments().model_dump()
        await media.command("stream_start", args)
        taps[0].status = lambda: ("ERROR", 0, "native encoder failed")
        status = await media.command("stream_status", {})
        assert status["state"] == "ERROR" and status["connection"] == args
        assert media.tap is taps[0]
        stopped = await media.command("stream_stop", {})
        assert stopped["state"] == "OFF" and stopped["connection"] is None
        await media.close()

    asyncio.run(run())


def test_media_owns_one_sdk_lifetime_across_stream_restarts(rig):
    media, _views, taps, _export, _cuda = rig
    ovstream = sys.modules["ovstream"]
    args = {
        "source": "viewport",
        "view_id": "primary",
        "protocol": "webrtc",
        "signal_port": 49100,
        "media_port": 47998,
        "fps": 30,
        "public_ip": None,
        "allow_input": False,
    }

    async def run():
        for _ in range(2):
            await media.command("stream_start", args)
            await media.command("stream_stop", {})
        await media.close()

    asyncio.run(run())
    # The taps borrow Media's SDK: their close cannot shut it down underneath
    # a later stream or replace Media's logging configuration.
    assert [tap.configuration["manage_sdk"] for tap in taps] == [False, False]
    ovstream.initialize.assert_called_once()
    ovstream.shutdown.assert_called_once()


def test_recorded_frames_use_the_cheap_frame_receipt(rig):
    media, _views, _taps, export, _cuda = rig
    media.app.get_inspector_state = Mock(side_effect=AssertionError("full snapshot per frame"))
    media.app.get_media_frame_state = Mock(return_value={"frame_id": 7})
    media.ensure_export()
    media.cuda.d2h = Mock()
    media.record_active = True
    media.record_extent = export.extent()
    media.export_frame()
    assert media.error is None
    assert media.latest_record_frame[0] == 1
    assert media.latest_record_frame[3] == {"frame_id": 7}


def test_recording_rejects_odd_export_dimensions_before_starting(rig, monkeypatch):
    media, _views, _taps, export, _cuda = rig
    export.extent = lambda: (961, 540)
    monkeypatch.setitem(sys.modules, "imageio_ffmpeg", SimpleNamespace())
    media.release_export = Mock()
    with pytest.raises(ValueError, match="even"):
        asyncio.run(media.command("recording_start", {"view_id": None, "fps": 15, "max_seconds": 5}))
    assert not media.record_active and media.record_task is None
    media.release_export.assert_called_once()


def test_resize_during_recording_stops_it_with_a_clear_error(rig):
    media, _views, _taps, export, _cuda = rig
    media.app.get_media_frame_state = Mock(return_value={})
    media.ensure_export()
    media.cuda.d2h = Mock()
    media.record_active = True
    media.record_extent = (1280, 720)
    export.extent = lambda: (1024, 720)
    media.export_frame()
    assert media.latest_record_frame is None
    assert media.record_stop
    assert "resized" in media.record_error
    # Streaming state is independent of the recording failure.
    assert media.error is None


def test_stream_released_by_its_renderer_is_reported_and_restartable(rig):
    media, _views, taps, _export, _cuda = rig
    args = {
        "source": "viewport",
        "view_id": "primary",
        "protocol": "webrtc",
        "signal_port": 49100,
        "media_port": 47998,
        "fps": 30,
        "public_ip": None,
        "allow_input": False,
    }
    asyncio.run(media.command("stream_start", args))
    renderer = media.stream_renderer
    renderer.render_product_stream_attached = Mock(return_value=True)
    assert media.status()["state"] == "STREAMING"
    # For example the Viewer replaced its renderer during a provider switch.
    renderer.render_product_stream_attached.return_value = False
    status = media.status()
    assert status["state"] == "ERROR" and "released" in status["error"]
    assert asyncio.run(media.command("stream_stop", {}))["state"] == "OFF"
    renderer.render_product_stream_attached.return_value = True  # The new tap is bound.
    assert asyncio.run(media.command("stream_start", args))["state"] == "STREAMING"
