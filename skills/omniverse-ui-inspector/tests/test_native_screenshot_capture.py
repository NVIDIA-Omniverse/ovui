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

import json
import os
from pathlib import Path
import sys

import pytest


os.environ["OVUIINSPECT_ENABLED"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ovuiinspect import _Command, _advance_checkpoint, _advance_screenshot  # noqa: E402


_RUN_NATIVE = os.environ.get("OVUIINSPECT_RUN_NATIVE_SCREENSHOT_TEST") == "1"


@pytest.mark.skipif(
    not _RUN_NATIVE,
    reason="set OVUIINSPECT_RUN_NATIVE_SCREENSHOT_TEST=1 with a built ovui module",
)
def test_real_native_module_captures_screenshot_and_checkpoint(tmp_path: Path) -> None:
    """Exercise both Inspector capture paths through the built extension module."""

    os.environ.setdefault("OMNIUI_HEADLESS", "1")
    os.environ.setdefault("OMNIUI_BACKEND", "vulkan")

    import omni.ui as ui
    from omni.ui import _ui

    module_path = Path(_ui.__file__).resolve()
    assert module_path.suffix in {".so", ".pyd", ".dylib"}
    assert callable(getattr(_ui, "_get_screenshot_result", None))

    expected_commit = os.environ.get("OVUI_EXPECTED_BUILD_COMMIT")
    if expected_commit:
        assert ui.__commit__ == expected_commit

    output_root = Path(
        os.environ.get("OVUIINSPECT_NATIVE_SCREENSHOT_OUTPUT_DIR", str(tmp_path))
    )
    output_root.mkdir(parents=True, exist_ok=True)
    cancelled_path = output_root / "native-cancelled.png"
    screenshot_path = output_root / "native-screenshot.png"
    checkpoint_path = output_root / "native-checkpoint.png"
    cancelled_path.unlink(missing_ok=True)
    screenshot_path.unlink(missing_ok=True)
    checkpoint_path.unlink(missing_ok=True)

    class _Application:
        def __init__(self) -> None:
            self.calls = 0

        def get_inspector_state(self) -> dict[str, object]:
            self.calls += 1
            return {"proof": "real-native-module", "commit": ui.__commit__}

    assert _ui._standalone_init("native-screenshot-contract", 96, 64)
    window = None
    try:
        window = ui.Window("Native screenshot proof", width=96, height=64)
        with window.frame:
            ui.Label("request-scoped screenshot")
        assert _ui._standalone_tick()

        assert _ui._schedule_screenshot(str(cancelled_path))
        pending = _ui._get_screenshot_result()
        assert pending["status"] == "pending"
        assert _ui._cancel_screenshot(pending["request_id"])
        assert _ui._standalone_tick()
        assert _ui._get_screenshot_result()["status"] == "cancelled"
        assert not cancelled_path.exists()
        assert _ui._poll_screenshot_done() is True
        assert _ui._poll_screenshot_done() is False

        screenshot = _Command("screenshot", {"path": str(screenshot_path)}, 5.0)
        _advance_screenshot(screenshot, _ui)
        assert screenshot.scheduled and not screenshot.done
        assert _ui._standalone_tick()
        _advance_screenshot(screenshot, _ui)
        assert screenshot.result is not None and screenshot.result["success"] is True
        screenshot_request_id = screenshot.result["screenshot_result"]["request_id"]
        assert _ui._poll_screenshot_done() is True
        assert _ui._poll_screenshot_done() is False
        stable_result = _ui._get_screenshot_result()
        assert stable_result["request_id"] == screenshot_request_id
        assert stable_result["status"] == "succeeded"

        application = _Application()
        checkpoint = _Command("checkpoint", {"path": str(checkpoint_path)}, 5.0)
        _advance_checkpoint(checkpoint, _ui, application)
        assert checkpoint.scheduled and not checkpoint.done
        assert _ui._standalone_tick()
        _advance_checkpoint(checkpoint, _ui, application)

        assert checkpoint.result is not None and checkpoint.result["success"] is True
        assert checkpoint.result["state"] == {
            "proof": "real-native-module",
            "commit": ui.__commit__,
        }
        assert application.calls == 1

        for result, path in (
            (screenshot.result, screenshot_path),
            (checkpoint.result, checkpoint_path),
        ):
            registration = result["screenshot_request"]
            terminal = result["screenshot_result"]
            assert registration["request_id"] == terminal["request_id"]
            assert registration["path"] == str(path)
            assert registration["status"] == "pending"
            assert terminal["status"] == "succeeded"
            assert terminal["actual_format"] == "png"
            assert terminal["width"] == 96
            assert terminal["height"] == 64
            assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

        print(
            json.dumps(
                {
                    "module": str(module_path),
                    "commit": ui.__commit__,
                    "screenshot": screenshot.result,
                    "checkpoint": checkpoint.result,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        window = None
        _ui._standalone_shutdown()
