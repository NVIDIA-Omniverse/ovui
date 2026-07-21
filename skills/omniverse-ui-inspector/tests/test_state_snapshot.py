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

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ["OVUIINSPECT_ENABLED"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ovuiinspect as inspector  # noqa: E402
from ovuiinspect import _advance_state, _Command  # noqa: E402


class _StateApplication:
    def get_inspector_state(self):
        return {
            "provider": "ovstage",
            "path": Path("scene.usda"),
            "paths": ("/World", "/World/Cube"),
        }


def test_state_snapshot_runs_application_provider_and_normalizes_json_values() -> None:
    command = _Command("state", {}, 1.0)

    _advance_state(command, _StateApplication())

    assert command.result == {
        "success": True,
        "state": {
            "provider": "ovstage",
            "path": "scene.usda",
            "paths": ["/World", "/World/Cube"],
        },
    }


def test_state_snapshot_rejects_missing_application() -> None:
    command = _Command("state", {}, 1.0)

    _advance_state(command, None)

    assert command.result == {
        "success": False,
        "error": "no application is attached",
    }


def test_state_snapshot_rejects_non_mapping_provider_result() -> None:
    class InvalidApplication:
        def get_inspector_state(self):
            return ["not", "a", "mapping"]

    command = _Command("state", {}, 1.0)

    _advance_state(command, InvalidApplication())

    assert command.result == {
        "success": False,
        "error": "get_inspector_state() must return a dict",
    }


def test_state_endpoints_are_disabled_by_default_without_affecting_screenshots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OVUIINSPECT_ENABLE_STATE", raising=False)

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("disabled state endpoint reached its implementation")

    screenshot = b"\x89PNG\r\n\x1a\nfixture"
    monkeypatch.setattr(inspector, "_submit", unexpected_call)
    monkeypatch.setattr(inspector, "_checkpoint_bytes", unexpected_call)
    monkeypatch.setattr(
        inspector,
        "_image_bytes",
        lambda _fmt, _timeout: (screenshot, "image/png", {"success": True}),
    )

    with TestClient(inspector._create_app()) as client:
        assert client.get("/status").json()["state_enabled"] is False
        for method, path in ((client.get, "/state"), (client.post, "/checkpoint")):
            response = method(path)
            assert response.status_code == 403
            assert response.json() == {
                "detail": (
                    "application state endpoints are disabled; set "
                    "OVUIINSPECT_ENABLE_STATE=1 before launch"
                )
            }
        response = client.get("/screenshot")

    assert response.status_code == 200
    assert response.content == screenshot
    assert response.headers["content-type"] == "image/png"


def test_state_opt_in_enables_state_and_checkpoint_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OVUIINSPECT_ENABLE_STATE", "1")
    screenshot = b"\x89PNG\r\n\x1a\nfixture"
    request = {"request_id": 17, "path": "/tmp/checkpoint.png"}
    result = {**request, "status": "succeeded"}

    def submit(command: _Command) -> dict:
        assert command.kind == "state"
        return {"success": True, "state": {"provider": "ovstage"}}

    monkeypatch.setattr(inspector, "_submit", submit)
    monkeypatch.setattr(
        inspector,
        "_checkpoint_bytes",
        lambda _fmt, _timeout: (
            screenshot,
            "image/png",
            {
                "success": True,
                "state": {"provider": "ovstage"},
                "screenshot_request": request,
                "screenshot_result": result,
            },
        ),
    )

    with TestClient(inspector._create_app()) as client:
        assert client.get("/status").json()["state_enabled"] is True
        assert client.get("/state").json() == {
            "success": True,
            "state": {"provider": "ovstage"},
        }
        checkpoint = client.post("/checkpoint").json()

    assert checkpoint["success"] is True
    assert checkpoint["state"] == {"provider": "ovstage"}
    assert checkpoint["screenshot"]["request"] == request
    assert checkpoint["screenshot"]["result"] == result
