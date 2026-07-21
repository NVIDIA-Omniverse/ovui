# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest
from PIL import Image

from .inspector_qa import harness as harness_module
from .inspector_qa.harness import (
    EvidenceRecorder,
    InspectorAppProcess,
    InspectorClient,
    InspectorRuntimeConfig,
    _request_error_detail,
)


class _ProcessConfig:
    python = Path("/nonexistent/test-python")

    def process_environment(self, *, port: int, workspace: Path) -> dict[str, str]:
        assert port > 0
        assert workspace.is_absolute()
        return {}


def test_runtime_config_opts_child_process_into_state_guided_qa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OVUIINSPECT_ENABLE_STATE", "0")
    config = InspectorRuntimeConfig(
        repo_root=tmp_path,
        python=tmp_path / "python",
        kit_root=tmp_path / "kit",
        ovstage_root=tmp_path / "ovstage",
        ovrtx_root=tmp_path / "ovrtx",
        rendering_build=tmp_path / "build",
        ovui_python_root=tmp_path / "ovui-python",
    )

    environment = config.process_environment(port=12345, workspace=tmp_path / "workspace")

    assert environment["OVUIINSPECT_ENABLE_STATE"] == "1"
    assert environment["OVUIINSPECT_ENABLE_EXECUTE"] == "0"


def test_evidence_manifest_labels_state_guided_interactions(tmp_path: Path) -> None:
    EvidenceRecorder(object(), tmp_path)  # type: ignore[arg-type]

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["interaction_mode"] == "state_guided"


def test_http_error_detail_preserves_fastapi_response_body() -> None:
    error = HTTPError(
        "http://127.0.0.1:9910/keyboard/press",
        400,
        "Bad Request",
        {},
        BytesIO(b'{"detail":"steps command timed out"}'),
    )

    detail = _request_error_detail(error)

    assert "HTTP Error 400" in detail
    assert 'response={"detail":"steps command timed out"}' in detail


def test_app_process_popen_failure_closes_log_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = InspectorAppProcess(_ProcessConfig(), tmp_path, scene=None)  # type: ignore[arg-type]
    monkeypatch.setattr(
        harness_module.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected")),
    )

    with pytest.raises(OSError, match="injected"):
        application.start()

    assert application._closed is True
    assert application._log_handle is None
    assert application.process is None


def test_app_process_startup_timeout_cleans_group_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Process:
        pid = 4242
        returncode = None

        def __init__(self) -> None:
            self.wait_calls = 0

        def poll(self) -> None:
            return None

        def wait(self, *, timeout: float) -> int:
            assert timeout == 30.0
            self.wait_calls += 1
            self.returncode = 0
            return 0

    process = Process()
    popen_kwargs: dict[str, object] = {}

    def popen(*_args, **kwargs):
        popen_kwargs.update(kwargs)
        return process

    clock = iter((0.0, 301.0))
    monkeypatch.setattr(harness_module.subprocess, "Popen", popen)
    monkeypatch.setattr(harness_module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(harness_module, "_process_group_exists", lambda _pgid: False)
    application = InspectorAppProcess(_ProcessConfig(), tmp_path, scene=None)  # type: ignore[arg-type]
    shutdown_calls: list[None] = []
    monkeypatch.setattr(
        application.client,
        "shutdown",
        lambda: shutdown_calls.append(None),
    )

    with pytest.raises(RuntimeError, match="Inspector did not answer"):
        application.start()

    assert popen_kwargs["start_new_session"] is True
    assert process.wait_calls == 1
    assert shutdown_calls == [None]
    assert application._closed is True
    assert application._process_group_id is None
    assert application._log_handle is None

    application.close()
    assert process.wait_calls == 1
    assert shutdown_calls == [None]


def test_app_process_rejects_second_start_without_replacing_owned_process(
    tmp_path: Path,
) -> None:
    application = InspectorAppProcess(_ProcessConfig(), tmp_path, scene=None)  # type: ignore[arg-type]
    owned_process = object()
    application.process = owned_process  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="already started"):
        application.start()

    assert application.process is owned_process


def test_screenshot_stats_count_nonblack_pixels_by_pixel(tmp_path) -> None:
    path = tmp_path / "known.png"
    image = Image.new("RGB", (2, 2), (0, 0, 0))
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((1, 0), (0, 255, 0))
    image.putpixel((0, 1), (0, 0, 255))
    image.save(path)

    stats = EvidenceRecorder._screenshot_stats(path)

    assert stats["width"] == 2
    assert stats["height"] == 2
    assert stats["nonblack_pixels"] == 3
    assert stats["max_channel_range"] == 255
    assert stats["luma_mean"] > 0.0
    assert stats["luma_std"] > 0.0
    assert len(stats["pixel_sha256"]) == 64


def _checkpoint_payload(*, terminal_request_id: int = 7) -> dict:
    stream = BytesIO()
    Image.new("RGB", (2, 2), (1, 2, 3)).save(stream, format="PNG")
    payload = stream.getvalue()
    return {
        "success": True,
        "state": {"provider": "ovstage"},
        "screenshot": {
            "request": {"request_id": 7, "path": "/tmp/request.png"},
            "result": {
                "request_id": terminal_request_id,
                "path": "/tmp/request.png",
                "status": "succeeded",
            },
            "image_base64": base64.b64encode(payload).decode("ascii"),
            "mime_type": "image/png",
            "bytes": len(payload),
        },
    }


def test_inspector_client_checkpoint_writes_exact_correlated_png(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = InspectorClient(9910)
    calls = []

    def post(path, payload, *, timeout):
        calls.append((path, payload, timeout))
        return _checkpoint_payload()

    monkeypatch.setattr(client, "_post", post)
    path = tmp_path / "checkpoint.png"

    result = client.checkpoint(path, timeout=12.0)

    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert result["state"] == {"provider": "ovstage"}
    assert result["screenshot_request"]["request_id"] == 7
    assert result["screenshot_result"]["request_id"] == 7
    assert calls == [("/checkpoint?timeout=12.0&fmt=png", {}, 17.0)]


def test_inspector_client_checkpoint_rejects_request_identity_change(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = InspectorClient(9910)
    monkeypatch.setattr(
        client,
        "_post",
        lambda *_args, **_kwargs: _checkpoint_payload(terminal_request_id=8),
    )

    with pytest.raises(RuntimeError, match="request identity changed"):
        client.checkpoint(tmp_path / "checkpoint.png")


def test_inspector_client_click_forwards_real_double_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = InspectorClient(9910)
    calls = []

    def post(path, payload, *, timeout):
        calls.append((path, payload, timeout))
        return {"success": True}

    monkeypatch.setattr(client, "_post", post)

    client.click(17, 23, modifiers=["ctrl"], double=True, timeout=4.0)

    assert calls == [
        (
            "/mouse/click",
            {
                "x": 17,
                "y": 23,
                "button": "left",
                "modifiers": ["ctrl"],
                "double": True,
                "timeout": 4.0,
            },
            9.0,
        )
    ]


def test_inspector_client_defaults_real_input_to_long_frame_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = InspectorClient(9910)
    calls = []

    def post(path, payload, *, timeout):
        calls.append((path, payload, timeout))
        return {"success": True}

    monkeypatch.setattr(client, "_post", post)

    client.press("z", modifiers=["ctrl", "shift"])

    assert calls == [
        (
            "/keyboard/press",
            {"key": "z", "modifiers": ["ctrl", "shift"], "timeout": 60.0},
            65.0,
        )
    ]


def test_evidence_settles_filtered_property_rows_after_layout(tmp_path) -> None:
    laid_out = {
        "property_ui": {
            "available": True,
            "filter_text": "Radius",
            "rows": {
                "radius": {
                    "field_rects": [
                        {"x": 1100.0, "y": 190.0, "width": 120.0, "height": 20.0}
                    ]
                }
            },
        }
    }

    class _Client:
        def __init__(self) -> None:
            self.state_calls = 0

        def state(self, *, timeout: float):
            assert timeout == 60.0
            self.state_calls += 1
            return laid_out

    client = _Client()
    recorder = EvidenceRecorder(client, tmp_path)  # type: ignore[arg-type]
    before_layout = {
        "property_ui": {
            "available": True,
            "filter_text": "Radius",
            "rows": {
                "radius": {
                    "field_rects": [
                        {"x": 984.0, "y": 48.0, "width": 0.0, "height": 0.0}
                    ]
                }
            },
        }
    }

    settled, frames = recorder._settled_state(before_layout)

    assert settled is laid_out
    assert frames == 1
    assert client.state_calls == 1


def test_evidence_settles_open_camera_menu_geometry(tmp_path) -> None:
    laid_out = {
        "viewport": {
            "camera_menu": {
                "shown": True,
                "items": [{"path": "/World/Camera", "point": [420, 110]}],
            }
        }
    }

    class _Client:
        def state(self, *, timeout: float):
            assert timeout == 60.0
            return laid_out

    recorder = EvidenceRecorder(_Client(), tmp_path)  # type: ignore[arg-type]
    before_layout = {
        "viewport": {
            "camera_menu": {
                "shown": True,
                "items": [{"path": "/World/Camera", "point": None}],
            }
        }
    }

    settled, frames = recorder._settled_state(before_layout)

    assert settled is laid_out
    assert frames == 1


def _readiness_state(centers: dict) -> dict:
    return {
        "ovstage": {"available": True, "paths": ["/World"]},
        "adapter": {"available": True},
        "renderer": {"available": True, "successful_frame_count": 3},
        "components": {
            "loaded_names": [
                "ovui_widgets_ovrtx_tools",
                "ovstage_physics_controls",
            ],
            "failures": {},
        },
        "viewport": {
            "available": True,
            "prim_screen_centers": centers,
            "projection_paths_truncated": False,
        },
    }


class _StubStateClient:
    def __init__(self, state: dict) -> None:
        self._state = state

    def state(self, *, timeout: float = 60.0) -> dict:
        return self._state


def _readiness_app(tmp_path: Path, state: dict) -> InspectorAppProcess:
    application = InspectorAppProcess(_ProcessConfig(), tmp_path, scene=None)  # type: ignore[arg-type]

    class _Process:
        returncode = None

        @staticmethod
        def poll() -> None:
            return None

    application.process = _Process()  # type: ignore[assignment]
    application.client = _StubStateClient(state)  # type: ignore[assignment]
    return application


def test_wait_for_scene_centers_requirement_is_opt_in(tmp_path: Path) -> None:
    """Empty/nonprojectable scenes stay ready by default; workflows that aim
    input at prim screen centers opt in and are deferred until the native
    bounds queries have projected them."""
    application = _readiness_app(tmp_path, _readiness_state({}))
    state = application.wait_for_scene(timeout=2.0)
    assert state["viewport"]["prim_screen_centers"] == {}

    class _CentersAppearLater:
        def __init__(self) -> None:
            self._polls = 0

        def state(self, *, timeout: float = 60.0) -> dict:
            self._polls += 1
            centers = {"/World/Cube": [5, 5]} if self._polls >= 3 else {}
            return _readiness_state(centers)

    application.client = _CentersAppearLater()  # type: ignore[assignment]
    state = application.wait_for_scene(
        timeout=10.0, require_prim_screen_centers=True
    )
    # Returning the LATER state (centers present) is the behavioral proof
    # that readiness was deferred until projection targets existed.
    assert state["viewport"]["prim_screen_centers"] == {"/World/Cube": [5, 5]}
