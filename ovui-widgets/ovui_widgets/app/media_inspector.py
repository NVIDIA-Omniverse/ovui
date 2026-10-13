# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Shared, optional Inspector media vocabulary for headless ovui hosts."""

from functools import partial


def media_commands(service):
    """Register without importing CUDA/ovstream or starting an encoder.

    ``service`` returns the application's one persistent Media instance.
    Inspector owns validation, dispatch and frame-loop affinity as usual.
    """
    from ovuiinspect import Arguments, Command
    from pydantic import Field, model_validator
    from typing import Literal

    class Stream(Arguments):
        source: Literal["application", "viewport"] = "viewport"
        view_id: str = "primary"
        protocol: Literal["webrtc", "rtsp", "native"] = "webrtc"
        signal_port: int = Field(default=49100, ge=1024, le=65535)
        media_port: int | None = Field(default=None, ge=1024, le=65535)
        public_ip: str | None = None
        fps: int = Field(default=30, ge=1, le=240)
        allow_input: bool = False

        @model_validator(mode="after")
        def validate_options(self):
            if self.media_port is None:
                self.media_port = {"webrtc": 47998, "native": 47999, "rtsp": 8554}[self.protocol]
            if self.allow_input and (self.source != "application" or self.protocol == "rtsp"):
                raise ValueError("Remote input requires an application source and WebRTC/native")
            return self

    class Record(Arguments):
        view_id: str | None = None
        fps: int = Field(default=15, ge=1, le=60)
        max_seconds: float = Field(default=30, gt=0, le=300)

    async def call(name, **args):
        result = await service().command(name, args)
        if isinstance(result, dict) and (result.get("ok") is False or result.get("error")):
            # A status request must remain readable after failure.
            if name not in {"stream_status", "recording_status"}:
                raise RuntimeError(str(result))
        return result

    definitions = (
        (
            "stream_start",
            Stream,
            "Start OVStream from a viewport's RTX RenderProduct texture or the composed application. One source per application; stop before reconfiguring.",
        ),
        (
            "stream_status",
            Arguments,
            "Read stream state, source, dimensions, clients, submitted frames and errors. Server submission does not prove browser decoding.",
        ),
        (
            "stream_stop",
            Arguments,
            "Idempotently stop streaming and release its resources; an active recording continues.",
        ),
        (
            "recording_start",
            Record,
            "Record the current composed application, preserving its layout, to a bounded MP4. Optionally focus an already visible view; edits and camera navigation continue.",
        ),
        (
            "recording_status",
            Arguments,
            "Read recording progress or the most recently finalized recording receipt.",
        ),
        (
            "recording_stop",
            Arguments,
            "Finalize the MP4 and return observed/held-frame counts and artifacts.",
        ),
    )
    return [
        Command(
            name, description, arguments, partial(call, name), name.endswith("_status"), "media"
        )
        for name, arguments, description in definitions
    ]
