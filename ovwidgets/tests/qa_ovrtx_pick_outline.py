# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Screenshot-first QA for ovrtx viewport picking and selection outlines.

This is a standalone harness, not a pytest test. It launches the real
application against ``tests/data/simple_scene.usda``, clicks the cube through
``omni.ui.testing`` input, waits for the selection to propagate through the
normal bus path, and captures a screenshot with
``omni.ui.testing.capture_screenshot``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

REPO_OVWIDGETS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_OVWIDGETS))

import omni.ui as ui  # noqa: E402
from omni.ui import testing as uitesting  # noqa: E402

from ovwidgets.app.application import Application  # noqa: E402
from ovwidgets.app.layout import write_split_ini  # noqa: E402
from ovwidgets.app.style import apply_global_styles, set_theme  # noqa: E402
from ovwidgets.common.selection import SelectionBus  # noqa: E402
from ovwidgets.viewport.viewport_widget import ViewportWidget  # noqa: E402

USD_PATH = Path(__file__).resolve().parent / "data" / "simple_scene.usda"
ARTIFACT_DIR = Path(
    os.environ.get(
        "OVWIDGETS_OVRTX_QA_DIR",
        "<path-to-artifacts>/ovui_ovrtx_pick_outline",
    )
).resolve()
SCREENSHOT_PATH = (ARTIFACT_DIR / "ovrtx_pick_outline_cube.png").resolve()
RESULT_PATH = (ARTIFACT_DIR / "qa_ovrtx_pick_outline_result.json").resolve()


async def _drive(frames: int) -> None:
    for _ in range(frames):
        await ui.next_frame()


def _snapshot_paths(app: Application) -> list[str]:
    snap = app.selection_bus.get_snapshot()
    if snap is None:
        return []
    return list(snap.paths())


def _stage_selection(app: Application) -> list[str]:
    stage_window = getattr(app, "_stage_window", None)
    widget = getattr(stage_window, "_widget", None)
    if widget is None:
        return []
    return list(widget.get_selection())


def _property_selection(app: Application) -> list[str]:
    property_window = getattr(app, "_property_window", None)
    if property_window is None:
        return []
    return list(getattr(property_window, "_selection", []))


def _viewport_image_rect(viewport: Any) -> tuple[float, float, int, int]:
    image = getattr(viewport, "_image", None)
    if image is None:
        raise RuntimeError("Viewport image widget was not built")
    width = int(getattr(image, "computed_width", 0) or 0)
    height = int(getattr(image, "computed_height", 0) or 0)
    if width <= 0 or height <= 0:
        width, height = viewport._get_viewport_size()
    x = float(getattr(image, "screen_position_x", 0.0) or 0.0)
    y = float(getattr(image, "screen_position_y", 0.0) or 0.0)
    return x, y, int(width), int(height)


def _project_world_to_screen(
    viewport: Any,
    world_point: tuple[float, float, float],
) -> tuple[int, int, tuple[float, float, float]]:
    image_x, image_y, width, height = _viewport_image_rect(viewport)
    view, proj = viewport._camera.get_matrices(width, height)
    vec = np.array([world_point[0], world_point[1], world_point[2], 1.0])
    clip = np.asarray(proj) @ (np.asarray(view) @ vec)
    if abs(float(clip[3])) < 1.0e-6:
        raise RuntimeError(f"Cannot project point {world_point}: w is zero")
    ndc = clip[:3] / clip[3]
    screen_x = image_x + (float(ndc[0]) + 1.0) * 0.5 * float(width)
    screen_y = image_y + (1.0 - float(ndc[1])) * 0.5 * float(height)
    return int(round(screen_x)), int(round(screen_y)), (
        float(ndc[0]),
        float(ndc[1]),
        float(ndc[2]),
    )


def _renderer(app: Application) -> Any:
    viewport = getattr(app, "_viewport_window", None)
    if viewport is None:
        raise RuntimeError("Application viewport window was not built")
    renderer = getattr(viewport, "_renderer", None)
    if renderer is None:
        raise RuntimeError("Viewport renderer was not built")
    return renderer


async def _wait_for_real_viewport(app: Application) -> Any:
    for _ in range(240):
        await ui.next_frame()
        viewport = getattr(app, "_viewport_window", None)
        if viewport is None:
            continue
        renderer = getattr(viewport, "_renderer", None)
        if renderer is None:
            continue
        try:
            _viewport_image_rect(viewport)
        except Exception:
            continue
        if (
            renderer.__class__.__name__ == "OvRtxRendererAdapter"
            and getattr(renderer, "_stage", None) is not None
        ):
            return viewport
    renderer = getattr(getattr(app, "_viewport_window", None), "_renderer", None)
    raise RuntimeError(
        "Timed out waiting for an OvRtxRendererAdapter viewport; "
        f"renderer={type(renderer).__name__ if renderer is not None else None}"
    )


async def _click_cube(app: Application, viewport: Any) -> dict[str, Any]:
    renderer = _renderer(app)
    initial_enqueue_count = int(getattr(renderer, "_pick_enqueue_count", 0))
    click_candidates = [
        (-1.5, 0.0, 0.0),
        (-1.5, 0.25, 0.0),
        (-1.5, -0.25, 0.0),
        (-1.5, 0.0, 0.35),
        (-1.5, 0.0, -0.35),
    ]
    click_trace: list[dict[str, Any]] = []
    for point in click_candidates:
        sx, sy, ndc = _project_world_to_screen(viewport, point)
        click_trace.append({"world": point, "screen": (sx, sy), "ndc": ndc})
        await uitesting.mouse_move(sx, sy)
        await _drive(3)
        await uitesting.mouse_click(sx, sy)
        await _drive(90)
        if _snapshot_paths(app) == ["/World/Cube"]:
            break
    else:
        raise RuntimeError(
            "Mouse click did not select /World/Cube; "
            f"selection={_snapshot_paths(app)} "
            f"last_pick={getattr(renderer, '_last_pick_path', None)!r} "
            f"click_trace={click_trace}"
        )

    for _ in range(90):
        if (
            _snapshot_paths(app) == ["/World/Cube"]
            and _stage_selection(app) == ["/World/Cube"]
            and _property_selection(app) == ["/World/Cube"]
            and int(getattr(renderer, "_pick_enqueue_count", 0)) > initial_enqueue_count
            and int(getattr(renderer, "_selection_outline_attribute_writes", 0)) > 0
        ):
            break
        await ui.next_frame()

    return {
        "click_trace": click_trace,
        "initial_pick_enqueue_count": initial_enqueue_count,
        "final_pick_enqueue_count": int(getattr(renderer, "_pick_enqueue_count", 0)),
        "last_pick_path": getattr(renderer, "_last_pick_path", None),
        "last_pick_pixel_rect": getattr(renderer, "_last_pick_pixel_rect", None),
    }


async def _main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    Application._instance = None
    SelectionBus._instance = None

    app = Application()
    app._running = True
    app._startup_usd_path = str(USD_PATH)
    task = asyncio.ensure_future(app.run_async())

    result: dict[str, Any] | None = None
    try:
        viewport = await _wait_for_real_viewport(app)
        await _drive(80)
        click_result = await _click_cube(app, viewport)
        renderer = _renderer(app)

        local_overlay_present = bool(
            hasattr(viewport, "_selection_outline_manipulator")
            and getattr(viewport, "_selection_outline_manipulator", None) is not None
        )
        build_ui_source = inspect.getsource(ViewportWidget._build_ui)
        ovrtx_api_available = bool(
            hasattr(getattr(renderer, "_renderer", None), "enqueue_pick_query")
            and hasattr(getattr(renderer, "_renderer", None), "set_selection_group_styles")
        )

        if local_overlay_present or "SelectionOutlineManipulator" in build_ui_source:
            raise RuntimeError("Local SelectionOutlineManipulator production path is present")
        if _snapshot_paths(app) != ["/World/Cube"]:
            raise RuntimeError(f"Final selection mismatch: {_snapshot_paths(app)}")
        if _stage_selection(app) != ["/World/Cube"]:
            raise RuntimeError(f"Stage Browser did not sync: {_stage_selection(app)}")
        if _property_selection(app) != ["/World/Cube"]:
            raise RuntimeError(
                f"Property Inspector did not sync: {_property_selection(app)}"
            )
        if int(getattr(renderer, "_pick_enqueue_count", 0)) <= click_result[
            "initial_pick_enqueue_count"
        ]:
            raise RuntimeError("ovrtx pick path was not observed")
        if int(getattr(renderer, "_selection_outline_style_calls", 0)) <= 0:
            raise RuntimeError("ovrtx selection outline style API was not used")
        if int(getattr(renderer, "_selection_outline_attribute_writes", 0)) <= 0:
            raise RuntimeError("ovrtx selection outline attributes were not written")

        await _drive(30)
        screenshot_ok = bool(uitesting.capture_screenshot(str(SCREENSHOT_PATH)))
        if not screenshot_ok or not SCREENSHOT_PATH.exists():
            raise RuntimeError(f"Failed to capture screenshot at {SCREENSHOT_PATH}")

        result = {
            "renderer": renderer.__class__.__name__,
            "ovrtx_pick_path_used": True,
            "pick_enqueue_count": int(getattr(renderer, "_pick_enqueue_count", 0)),
            "pick_result_count": int(getattr(renderer, "_pick_result_count", 0)),
            "local_selection_outline_manipulator_present": local_overlay_present,
            "local_selection_outline_manipulator_in_build_ui": (
                "SelectionOutlineManipulator" in build_ui_source
            ),
            "ovrtx_selection_outline_apis_available": ovrtx_api_available,
            "selection_outline_style_calls": int(
                getattr(renderer, "_selection_outline_style_calls", 0)
            ),
            "selection_outline_attribute_writes": int(
                getattr(renderer, "_selection_outline_attribute_writes", 0)
            ),
            "final_selection": _snapshot_paths(app),
            "stage_browser_selection": _stage_selection(app),
            "property_inspector_selection": _property_selection(app),
            "final_screenshot": str(SCREENSHOT_PATH),
            **click_result,
        }
        RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print("QA_RESULT " + json.dumps(result, sort_keys=True))
    finally:
        app._running = False
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()
        except Exception:
            pass
        app.shutdown()
        if result is None:
            print("QA_RESULT null")


if __name__ == "__main__":
    for path in [
        Path("imgui.ini"),
        Path(os.path.expanduser("~/.ovgear/layout.json")),
    ]:
        if path.exists():
            path.unlink()
    write_split_ini()
    ui.init("OvGear ovrtx Pick Outline QA", width=1280, height=800)
    apply_global_styles()
    set_theme("dark")
    ui.run(_main())
