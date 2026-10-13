# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Shared headless ovui media lifecycle over headless_frame and LivestreamTap.

The owner calls drain_input before rendering, export_frame after rendering and
awaits close before UI teardown. No USD or USD Workbench dependency is required.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Protocol, TypedDict

import numpy as np

from ovui_widgets.common.artifacts import artifact, atomic_json


class MediaRenderProduct(TypedDict):
    renderer: Any
    product_path: str
    extent: tuple[int, int]


class MediaHost(Protocol):
    """Owner-thread interface shared by application hosts and the regular USD Viewer.

    The host continues pumping frames during settle(), calls drain_input before
    a frame and export_frame afterwards, detaches/awaits Inspector commands, then
    awaits Media.close() before releasing renderer, CUDA or UI resources.
    Streaming is OFF -> starting -> active/ERROR -> OFF; recording independently
    owns its encoder task. Optional prepare_export/legacy_stream_status hooks
    adapt the Viewer's older environment-controlled export on the first mutation.
    """

    active_view: str
    artifacts: Path
    config: dict

    def activate(self, view_id: str) -> Any: ...
    def get_media_viewports(self) -> dict[str, Any]: ...
    def get_media_render_product(self, view_id: str) -> MediaRenderProduct: ...
    # Called for every recorded frame: return a small JSON-safe receipt
    # (frame, camera), not the host's full Inspector state snapshot.
    def get_media_frame_state(self) -> dict: ...
    async def settle(self, frames: int = 3) -> None: ...


class ReferenceMediaHost:
    """Small host adapter for the regular USD Viewer; no scene ownership."""

    def __init__(self, app):
        self.app = app
        self.active_view = "primary"
        self.artifacts = Path(os.environ.get("OVUI_MEDIA_DIRECTORY", "ovui-media")).resolve()

    def prepare_export(self):
        # Adopt the existing environment-controlled export only on a mutation.
        self.app._teardown_headless_export()
        self.app.set_remote_input_bridge(None)
        self.app._message_dispatcher = None

    def legacy_stream_status(self):
        tap = getattr(self.app, "_headless_tap", None)
        if tap is None:
            return None
        state, clients, error = tap.status()
        return {
            "state": state,
            "clients": clients,
            "error": error,
            "connection": {
                "source": "application",
                "protocol": tap.protocol,
                "signal_port": tap.signal_port,
                "media_port": tap.media_port,
                "public_ip": tap.public_ip,
            },
            "control": "startup environment; next start/stop adopts Inspector lifecycle",
            "client_decode_verified": False,
        }

    @property
    def config(self):
        from omni.ui.standalone import headless_frame

        width, height = headless_frame.extent()
        return {"width": width, "height": height}

    def activate(self, view_id):
        if view_id not in self.get_media_viewports():
            raise ValueError(f"No visible viewport {view_id!r}")

    def get_media_viewports(self):
        view = self.app._viewport_window
        return {"primary": view} if view is not None and view.visible else {}

    def get_media_render_product(self, view_id):
        surface = self.get_media_viewports().get(view_id)
        if surface is None:
            raise ValueError(f"No visible viewport {view_id!r}")
        renderer = surface.renderer_adapter
        size = surface.get_resolution_state().effective_size
        if renderer is None or not size:
            raise ValueError("Viewport has no rendered product yet")
        return {
            "renderer": renderer,
            "product_path": renderer.get_active_render_product_path(),
            "extent": size,
        }

    def get_media_frame_state(self):
        view = self.app._viewport_window
        camera = view.capture_aov_camera_state() if view is not None else None
        return {
            "current_file_path": str(getattr(self.app, "_current_file_path", "") or ""),
            "view_matrix": [list(row) for row in camera.view_matrix] if camera else None,
        }

    async def settle(self, frames=3):
        # The application's normal owner loop continues rendering throughout.
        import omni.ui as ui

        for _ in range(frames):
            await ui.next_frame()


def _encode_recording_batch(encoder, previous, current, repeats):
    """One serialized encoder job per selected observation, including holds."""
    written = 0
    try:
        for _ in range(repeats):
            encoder.send(previous)
            written += 1
        encoder.send(current)
        written += 1
    except Exception as exc:
        # Preserve truthful partial-frame accounting if the encoder fails.
        return written, exc
    return written, None


class Media:
    def __init__(self, app: MediaHost):
        self.app = app
        self.tap = None
        self.headless = None
        self.bridge = None
        self.submitted_frames = 0
        self.error = None
        self.stream_error = None
        self.record_task = None
        self.record_stop = False
        self.record_result = None
        self.stream_config = None
        self.cuda = None
        self.buffer = 0
        self.pitch = 0
        self.extent = None
        self.record_active = False
        self.record_extent = None
        self.record_error = None
        self.record_fps = 15
        self.last_record_capture = 0
        self.latest_record_frame = None
        self.record_sequence = 0
        self.stream_runtime = None
        self.stream_extent = None
        self.stream_renderer = None
        self.stream_product = None
        self.last_stream_submit = 0.0
        self.lock = asyncio.Lock()
        self.owns_export = False

    def adopt_export(self):
        if not self.owns_export:
            prepare = getattr(self.app, "prepare_export", None)
            if prepare:
                prepare()
            self.owns_export = True

    def ensure_export(self):
        if self.headless:
            return
        self.adopt_export()
        from omni.ui.standalone import headless_frame
        from ovui_data_adapters.common._livestream_tap import _Cudart

        if not headless_frame.init():
            raise RuntimeError(
                "ovui headless CUDA export could not initialize: CUDA/Vulkan interop is "
                "unavailable or the display surface is in a failed state (see the application "
                "log for VulkanByteImageGpu/CudaVulkanInterop errors; a build without "
                "OMNIUI_REQUIRE_CUDA=ON cannot export)"
            )
        self.headless = headless_frame
        self.cuda = _Cudart()
        self.error = None

    def release_export(self):
        if self.headless:
            self.headless.shutdown()
            self.headless = None
        if self.buffer:
            self.cuda.free(self.buffer)
            self.buffer = 0
        self.extent = None

    async def command(self, name, args):
        async with self.lock:
            return await self._command(name, args)

    async def _command(self, name, args):
        if name == "stream_start":
            if self.tap:
                raise ValueError("Stream is already active; stop it before changing ports")
            if (
                self.record_active
                and args["source"] == "viewport"
                and args["view_id"] not in self.app.get_media_viewports()
            ):
                raise ValueError("Stop recording before changing the active viewport")
            self.stream_error = None
            from ovui_data_adapters.common._livestream_tap import LivestreamTap

            if args["source"] == "viewport":
                self.app.activate(args["view_id"])
            try:
                self.adopt_export()
                if args["source"] == "application":
                    self.ensure_export()
                    await self.app.settle(3)
                    width, height = self.headless.extent()
                else:
                    # Use the renderer's established CUDA RenderProduct tap.
                    # No composed framebuffer, crop, or CPU upload is involved.
                    from ovui_data_adapters.common._livestream_tap import _Cudart

                    self.cuda = self.cuda or _Cudart()
                    await self.app.settle(2)
                    target = self.app.get_media_render_product(args["view_id"])
                    self.stream_renderer = target["renderer"]
                    self.stream_product = target["product_path"]
                    width, height = target["extent"]
                self.stream_extent = (width, height)
                if min(width, height) < 2 or width % 2 or height % 2:
                    raise ValueError(
                        "Streaming requires positive even RenderProduct/application dimensions"
                    )
                if self.stream_runtime is None:
                    import ovstream

                    # Keep the process-level SDK alive across individual streams.
                    ovstream.initialize(
                        log_fn=lambda level, channel, message, timestamp: print(
                            f"[ovui/media][{level.name}][{channel}] {message}", flush=True
                        ),
                        log_min_severity=(
                            ovstream.LogLevel.INFO
                            if os.environ.get("OVUI_MEDIA_VERBOSE") == "1"
                            else ovstream.LogLevel.WARNING
                        ),
                    )
                    self.stream_runtime = ovstream
                # Media owns the SDK lifetime; the tap must not shut it down.
                self.tap = LivestreamTap(
                    cuda_context=self.cuda.current_context(), config=args, manage_sdk=False,
                    trace_directory=Path(self.app.artifacts) / "stream-trace",
                )
                if args["allow_input"]:
                    from ovui_widgets.app._input_bridge import RemoteInputBridge

                    self.bridge = RemoteInputBridge(width=width, height=height)
                    self.tap.set_input_bridge(self.bridge)
                self.tap.start(width, height)
                if self.stream_renderer is not None:
                    self.stream_renderer.attach_render_product_stream(self.tap, self.stream_product)
            except BaseException as exc:
                self.stop_stream()
                self.stream_error = f"{type(exc).__name__}: {exc}"
                raise
            self.error = None
            self.submitted_frames = 0
            self.last_stream_submit = 0.0
            self.stream_config = dict(args)
            return self.status()
        if name == "stream_status":
            return self.status()
        if name == "stream_stop":
            self.adopt_export()
            self.stop_stream()
            self.stream_error = None
            if not self.record_active:
                self.error = None
            return self.status()
        if name == "recording_status":
            return self.recording_status()
        if name == "recording_start":
            if self.record_task and not self.record_task.done():
                raise ValueError("A recording is already active")
            view_id = args["view_id"] or self.app.active_view
            if view_id not in self.app.get_media_viewports():
                raise ValueError(
                    "Activate the requested view before recording; recording preserves the current layout"
                )
            # Fail before claiming a recording is active when the optional
            # encoder dependency is unavailable.
            import imageio_ffmpeg  # noqa: F401

            if view_id != self.app.active_view:
                self.app.activate(view_id)
            self.record_stop = False
            try:
                self.ensure_export()
                await self.app.settle(3)
                width, height = self.headless.extent()
                if min(width, height) < 2 or width % 2 or height % 2:
                    raise ValueError(
                        "Recording requires positive even application dimensions; "
                        f"the export is {width}x{height}"
                    )
                self.app.artifacts.mkdir(parents=True, exist_ok=True)
            except BaseException:
                # An Inspector timeout cancels this handler before a recording
                # task exists. Preserve an application stream's shared export.
                if not (
                    self.tap
                    and self.stream_config
                    and self.stream_config["source"] == "application"
                ):
                    self.release_export()
                raise
            # A start that fails keeps the previous recording's receipt.
            self.record_result = None
            self.record_active = True
            self.record_extent = (width, height)
            self.record_error = None
            self.record_fps = args["fps"]
            self.record_sequence = 0
            self.last_record_capture = 0
            self.latest_record_frame = None
            self.record_task = asyncio.create_task(self.record(**{**args, "view_id": view_id}))
            return {
                "recording": True,
                "view_id": view_id,
                "fps": args["fps"],
                "max_seconds": args["max_seconds"],
            }
        if name == "recording_stop":
            if not self.record_task:
                raise ValueError("No recording has been started")
            self.record_stop = True
            await asyncio.shield(self.record_task)
            return self.record_result
        raise ValueError("Unknown media command")

    def status(self):
        if not self.owns_export and not self.tap:
            legacy = getattr(self.app, "legacy_stream_status", lambda: None)()
            if legacy is not None:
                return legacy
        state, clients, error = self.tap.status() if self.tap else ("OFF", 0, None)
        attached = getattr(self.stream_renderer, "render_product_stream_attached", None)
        if self.tap and attached is not None and not attached(self.tap):
            # The renderer was shut down or replaced underneath this stream.
            state = "ERROR"
            error = "The renderer released this RenderProduct stream; stop and restart streaming"
        return {
            "state": "ERROR" if self.error or self.stream_error else state,
            "clients": clients,
            "submitted_frames": self.tap.submitted_frames if self.tap else self.submitted_frames,
            "error": self.error or self.stream_error or error,
            "connection": self.stream_config,
            "render_product_path": self.stream_product,
            "pixel_source": (
                "render_product_cuda" if self.stream_renderer else "composed_application_cuda"
            )
            if self.tap
            else None,
            "extent": getattr(self.tap, "extent", self.stream_extent) if self.tap else None,
            # Stream performance: last per-second summary, totals, QoS, trace log (``_stream_trace``).
            "perf": getattr(self.tap, "perf", None) if self.tap else None,
            "recording": self.record_active,
            "client_decode_verified": False,
            "note": "Server state does not prove client decoding; validate receiver frame counters.",
        }

    def recording_status(self):
        if self.record_active:
            return {
                "recording": True,
                "requested_fps": self.record_fps,
                "captured_frames": self.record_sequence,
                "error": self.record_error or self.error,
            }
        return self.record_result or {"recording": False}

    def drain_input(self):
        if self.bridge:
            import omni.ui as ui

            from ovui_widgets.app._input_drain import drain_bridge_into_ui

            drain_bridge_into_ui(self.bridge, ui._ui)

    def export_frame(self):
        if not self.headless or self.error:
            return
        ready = False
        try:
            ready = self.headless.wait_ready(10_000_000)
            if not ready:
                raise RuntimeError("Headless export did not queue its Vulkan/CUDA wait")
            width, height = self.headless.extent()
            if width and height:
                if self.extent != (width, height):
                    if self.buffer:
                        self.cuda.free(self.buffer)
                    self.buffer, self.pitch = self.cuda.malloc_pitch(width * 4, height)
                    self.extent = (width, height)
                if not self.headless.copy_to_linear(self.buffer, self.pitch, 0):
                    raise RuntimeError("Headless export copy failed")
                now = time.monotonic()
                if self.record_active and (width, height) != self.record_extent:
                    # The encoder was opened for the starting extent.
                    if not self.record_stop:
                        self.record_error = (
                            f"Application resized from {self.record_extent} to "
                            f"{(width, height)} during recording; restart the recording"
                        )
                        self.record_stop = True
                elif self.record_active and now - self.last_record_capture >= 1 / self.record_fps:
                    raw = np.empty((height, self.pitch), dtype=np.uint8)
                    self.cuda.d2h(raw, self.buffer, raw.nbytes)
                    rgb = raw[:, : width * 4].reshape(height, width, 4)[:, :, :3].copy()
                    self.record_sequence += 1
                    self.latest_record_frame = (
                        self.record_sequence,
                        rgb,
                        now,
                        self.app.get_media_frame_state(),
                    )
                    self.last_record_capture = now
                if (
                    self.tap
                    and self.stream_renderer is None
                    and now - self.last_stream_submit >= 1 / self.stream_config["fps"]
                ):
                    if (width, height) != self.stream_extent:
                        self.stream_error = (
                            "Application resized; restart streaming for the new extent"
                        )
                        self.stop_stream(release_export=False)
                    else:
                        if self.tap.tee_linear_to_ovstream(self.buffer, width, height, self.pitch):
                            self.submitted_frames += 1
                        self.last_stream_submit = now

        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            if ready:
                self.headless.signal_consumed()
        if self.error:
            # Disable the producer handshake too; otherwise its next frame can
            # block forever waiting for an abandoned CUDA consumer.
            self.stop_stream()
            self.record_stop = True
            self.release_export()
        elif self.stream_error and not self.record_active and not self.tap:
            self.release_export()

    def stop_stream(self, *, release_export=True):
        if self.tap:
            self.submitted_frames = self.tap.submitted_frames
            if self.stream_renderer is not None:
                self.stream_renderer.detach_render_product_stream(self.tap)
            self.tap.close()
            self.tap = None
        self.bridge = None
        self.stream_config = None
        self.stream_extent = None
        self.stream_renderer = self.stream_product = None
        if release_export and not self.record_active:
            self.release_export()

    async def record(self, view_id, fps, max_seconds):
        import imageio_ffmpeg

        path = self.app.artifacts / f"recording-{time.time_ns()}.mp4"
        width, height = self.record_extent or (self.app.config["width"], self.app.config["height"])
        encoder = imageio_ffmpeg.write_frames(
            str(path),
            (width, height),
            fps=fps,
            codec="libx264",
            pix_fmt_in="rgb24",
            pix_fmt_out="yuv420p",
            macro_block_size=1,
            output_params=["-movflags", "+faststart"],
        )
        started = time.monotonic()
        stopped = None
        frames = []
        error = None
        encoded_frames = 0
        last_sequence = 0
        last_rgb = None
        first_capture = None
        try:
            await asyncio.to_thread(encoder.send, None)
            while not self.record_stop and time.monotonic() - started < max_seconds:
                frame = self.latest_record_frame
                if frame is None or frame[0] == last_sequence:
                    await asyncio.sleep(0.005)
                    continue
                last_sequence, rgb, captured_at, state = frame
                first_capture = first_capture or captured_at
                target_index = round((captured_at - first_capture) * fps)
                # Hold the last observed image through missed sampling periods.
                # Do not speed up time when rendering cannot sustain requested FPS.
                repeats = max(0, target_index - encoded_frames) if last_rgb is not None else 0
                # A separate owner-loop round trip for every held image lets
                # catch-up fall further behind while latest_record_frame is
                # overwritten. Only encoder I/O runs in this single worker job;
                # CUDA capture and USD/UI state remain on the owning thread.
                written, encode_error = await asyncio.to_thread(
                    _encode_recording_batch, encoder, last_rgb, rgb, repeats
                )
                encoded_frames += written
                if encode_error is not None:
                    raise encode_error
                last_rgb = rgb
                frames.append(
                    {
                        "captured_monotonic": captured_at,
                        "encoded_frame": encoded_frames,
                        "state": state,
                    }
                )
            stopped = time.monotonic()
            if last_rgb is not None:
                # Hold the last image until the stop, as through missed periods:
                # otherwise the video ends at the last capture, short of wall time.
                tail = round((stopped - first_capture) * fps) - encoded_frames
                if tail > 0:
                    written, encode_error = await asyncio.to_thread(
                        _encode_recording_batch, encoder, last_rgb, last_rgb, tail - 1
                    )
                    encoded_frames += written
                    if encode_error is not None:
                        raise encode_error
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                await asyncio.to_thread(encoder.close)
            except Exception as exc:
                error = error or f"{type(exc).__name__}: {exc}"
            finally:
                self.record_active = False
                if not self.tap:
                    self.release_export()
        metadata = {
            "frames": frames,
            "frame_count": encoded_frames,
            "observed_frame_count": len(frames),
            "duplicated_frame_count": encoded_frames - len(frames),
            "requested_fps": fps,
            # Up to the stop request; encoder finalization is not recording time.
            "elapsed_seconds": (stopped or time.monotonic()) - started,
            "encoded_duration_seconds": encoded_frames / fps,
            # Encoder start-up before the first captured image is not encoded.
            "first_capture_offset_seconds": (first_capture - started) if first_capture else None,
            "error": error or self.record_error or self.error,
            "timing": "Composed Vulkan frames sampled through CUDA; repeated frames preserve wall-clock timing when sampling misses a requested interval and from the last capture until stop.",
        }
        atomic_json(path.with_suffix(".json"), metadata)
        self.record_result = {
            "ok": bool(frames) and metadata["error"] is None,
            "recording": False,
            **{k: v for k, v in metadata.items() if k != "frames"},
            "artifacts": ([artifact(path, kind="video")] if path.exists() else [])
            + [artifact(path.with_suffix(".json"), kind="receipt")],
        }

    async def close(self):
        self.record_stop = True
        if self.record_task:
            await asyncio.shield(self.record_task)
        self.stop_stream()
        if self.stream_runtime:
            self.stream_runtime.shutdown()
            self.stream_runtime = None
