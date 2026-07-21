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

os.environ["OVUIINSPECT_ENABLED"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ovuiinspect import (  # noqa: E402
    _advance_checkpoint,
    _advance_command,
    _advance_screenshot,
    _capture_path,
    _Command,
)

_PNG_BYTES = b"\x89PNG\r\n\x1a\ninspector-test"
_LEGACY_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00@\x00\x00\x00 "
    b"legacy-inspector-test"
)
_LEGACY_JPEG_BYTES = (
    b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x20\x00\x40\x03"
    b"\x01\x11\x00\x02\x11\x00\x03\x11\x00\xff\xd9"
)


class _ScreenshotUi:
    def __init__(self, request_id: int = 17) -> None:
        self.request_id = request_id
        self.path = ""
        self.snapshot: dict[str, object] = {}

    def _schedule_screenshot(self, path: str) -> bool:
        self.path = path
        self.snapshot = self.make_snapshot(status="pending", done=False, success=False)
        return True

    def _get_screenshot_result(self) -> dict[str, object]:
        return dict(self.snapshot)

    def make_snapshot(
        self,
        *,
        request_id: int | None = None,
        path: str | None = None,
        status: str = "succeeded",
        done: bool = True,
        success: bool = True,
        width: object = 64,
        height: object = 32,
        message: str = "",
    ) -> dict[str, object]:
        return {
            "request_id": self.request_id if request_id is None else request_id,
            "status": status,
            "done": done,
            "success": success,
            "path": self.path if path is None else path,
            "actual_format": "png" if success else "",
            "width": width,
            "height": height,
            "message": message,
        }

    def complete(self, **overrides: object) -> None:
        self.snapshot = self.make_snapshot(**overrides)


class _LegacyScreenshotUi:
    def __init__(self) -> None:
        self.path = ""
        self.complete = False
        self.polled = False

    def _schedule_screenshot(self, path: str) -> bool:
        self.path = path
        self.complete = False
        self.polled = False
        return True

    def _poll_screenshot_done(self) -> bool:
        if not self.complete or self.polled:
            return False
        self.polled = True
        return True


def _scheduled_command(tmp_path: Path) -> tuple[_Command, _ScreenshotUi, Path]:
    output = tmp_path / "capture.png"
    command = _Command("screenshot", {"path": str(output)}, 1.0)
    ui_native = _ScreenshotUi()

    _advance_screenshot(command, ui_native)

    assert command.scheduled
    assert not command.done
    return command, ui_native, output


def test_screenshot_accepts_only_its_terminal_nonempty_result(tmp_path: Path) -> None:
    command, ui_native, output = _scheduled_command(tmp_path)
    output.write_bytes(_PNG_BYTES)
    ui_native.complete()

    _advance_screenshot(command, ui_native)

    assert command.result == {
        "success": True,
        "path": str(output),
        "screenshot_request": {
            "request_id": 17,
            "status": "pending",
            "done": False,
            "success": False,
            "path": str(output),
            "actual_format": "",
            "width": 64,
            "height": 32,
            "message": "",
        },
        "screenshot_result": {
            "request_id": 17,
            "status": "succeeded",
            "done": True,
            "success": True,
            "path": str(output),
            "actual_format": "png",
            "width": 64,
            "height": 32,
            "message": "",
            "bytes": len(_PNG_BYTES),
        },
    }


def test_screenshot_rejects_stale_request_id(tmp_path: Path) -> None:
    command, ui_native, output = _scheduled_command(tmp_path)
    output.write_bytes(_PNG_BYTES)
    ui_native.complete(request_id=16)

    _advance_screenshot(command, ui_native)

    assert command.result == {
        "success": False,
        "error": "screenshot result changed request ID while waiting: expected 17, got 16",
    }


def test_screenshot_rejects_wrong_result_path(tmp_path: Path) -> None:
    command, ui_native, output = _scheduled_command(tmp_path)
    output.write_bytes(_PNG_BYTES)
    wrong_path = tmp_path / "different.png"
    ui_native.complete(path=str(wrong_path))

    _advance_screenshot(command, ui_native)

    assert command.result == {
        "success": False,
        "error": (
            f"screenshot request 17 reported an unexpected path: "
            f"{str(wrong_path)!r} != {str(output)!r}"
        ),
    }


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_screenshot_rejects_unsuccessful_terminal_status(tmp_path: Path, status: str) -> None:
    command, ui_native, _output = _scheduled_command(tmp_path)
    ui_native.complete(status=status, success=False, message=f"capture {status}")

    _advance_screenshot(command, ui_native)

    assert command.result == {
        "success": False,
        "error": f"screenshot request 17 failed: status={status!r}, message='capture {status}'",
    }


@pytest.mark.parametrize(("width", "height"), [(0, 32), (64, 0), (-1, 32), (64, "bad")])
def test_screenshot_rejects_invalid_extent(
    tmp_path: Path,
    width: object,
    height: object,
) -> None:
    command, ui_native, output = _scheduled_command(tmp_path)
    output.write_bytes(_PNG_BYTES)
    ui_native.complete(width=width, height=height)

    _advance_screenshot(command, ui_native)

    assert command.result is not None
    assert command.result["success"] is False
    assert "completed with an invalid extent" in command.result["error"]


def test_screenshot_rejects_empty_file(tmp_path: Path) -> None:
    command, ui_native, output = _scheduled_command(tmp_path)
    output.touch()
    ui_native.complete()

    _advance_screenshot(command, ui_native)

    assert command.result == {
        "success": False,
        "error": "screenshot request 17 produced an empty image file",
    }


def test_screenshot_rejects_non_png_output(tmp_path: Path) -> None:
    command, ui_native, output = _scheduled_command(tmp_path)
    output.write_bytes(b"not a png")
    ui_native.complete()

    _advance_screenshot(command, ui_native)

    assert command.result == {
        "success": False,
        "error": "screenshot request 17 output is not a valid PNG file",
    }


def test_capture_path_does_not_leave_a_stale_file() -> None:
    path = Path(_capture_path(".png"))

    assert not path.exists()


def test_checkpoint_freezes_state_when_its_screenshot_is_registered(tmp_path: Path) -> None:
    class _Application:
        value = 1
        calls = 0

        def get_inspector_state(self) -> dict[str, int]:
            self.calls += 1
            return {"value": self.value}

    application = _Application()
    ui_native = _ScreenshotUi(request_id=42)
    output = tmp_path / "checkpoint.png"
    command = _Command("checkpoint", {"path": str(output)}, 1.0)

    _advance_checkpoint(command, ui_native, application)
    application.value = 2
    output.write_bytes(_PNG_BYTES)
    ui_native.complete()
    _advance_checkpoint(command, ui_native, application)

    assert command.result is not None
    assert command.result["success"] is True
    assert command.result["state"] == {"value": 1}
    assert command.result["screenshot_request"]["request_id"] == 42
    assert command.result["screenshot_request"]["status"] == "pending"
    assert command.result["screenshot_result"]["request_id"] == 42
    assert command.result["screenshot_result"]["status"] == "succeeded"
    assert application.calls == 1


def test_legacy_schedule_poll_contract_supports_screenshot(tmp_path: Path) -> None:
    output = tmp_path / "legacy.png"
    command = _Command("screenshot", {"path": str(output)}, 1.0)
    ui_native = _LegacyScreenshotUi()

    _advance_screenshot(command, ui_native)

    assert command.scheduled
    assert not command.done
    output.write_bytes(_LEGACY_PNG_BYTES)
    ui_native.complete = True

    _advance_screenshot(command, ui_native)

    assert command.result is not None
    assert command.result["success"] is True
    registration = command.result["screenshot_request"]
    result = command.result["screenshot_result"]
    assert registration["request_id"] > 0
    assert registration["request_id"] == result["request_id"]
    assert registration["status"] == "pending"
    assert result["status"] == "succeeded"
    assert result["actual_format"] == "png"
    assert result["width"] == 64
    assert result["height"] == 32
    assert result["bytes"] == len(_LEGACY_PNG_BYTES)


def test_legacy_schedule_poll_contract_supports_checkpoint(tmp_path: Path) -> None:
    class _Application:
        def get_inspector_state(self) -> dict[str, str]:
            return {"source": "legacy"}

    output = tmp_path / "legacy-checkpoint.png"
    command = _Command("checkpoint", {"path": str(output)}, 1.0)
    ui_native = _LegacyScreenshotUi()

    _advance_checkpoint(command, ui_native, _Application())
    output.write_bytes(_LEGACY_PNG_BYTES)
    ui_native.complete = True
    _advance_checkpoint(command, ui_native, _Application())

    assert command.result is not None
    assert command.result["success"] is True
    assert command.result["state"] == {"source": "legacy"}
    assert (
        command.result["screenshot_request"]["request_id"]
        == command.result["screenshot_result"]["request_id"]
    )


def test_legacy_schedule_poll_contract_probes_jpeg_extent(tmp_path: Path) -> None:
    output = tmp_path / "legacy.jpeg"
    command = _Command("screenshot", {"path": str(output)}, 1.0)
    ui_native = _LegacyScreenshotUi()

    _advance_screenshot(command, ui_native)
    output.write_bytes(_LEGACY_JPEG_BYTES)
    ui_native.complete = True
    _advance_screenshot(command, ui_native)

    assert command.result is not None and command.result["success"] is True
    result = command.result["screenshot_result"]
    assert result["actual_format"] == "jpeg"
    assert result["width"] == 64
    assert result["height"] == 32


def test_timed_out_request_scoped_capture_is_cancelled(tmp_path: Path) -> None:
    class _CancellableUi:
        def __init__(self) -> None:
            self.cancelled: list[int] = []

        def _cancel_screenshot(self, request_id: int) -> bool:
            self.cancelled.append(request_id)
            return True

    command = _Command("screenshot", {"path": str(tmp_path / "timeout.png")}, 0.01)
    command.payload["_screenshot_contract"] = "request_scoped"
    command.payload["_screenshot_request_id"] = 91
    command.created_at -= 1.0
    ui_native = _CancellableUi()

    _advance_command(command, ui_native, None)

    assert ui_native.cancelled == [91]
    assert command.result == {"success": False, "error": "screenshot command timed out"}
