# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Exercise the shared provider without a USD stage or native renderer."""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from ovui_widgets.viewport.inspector import ViewportInspector


@dataclass
class Camera:
    path: str
    label: str
    active: bool


def provider():
    selection = []
    calls = []
    callbacks = []
    surface = SimpleNamespace(
        get_inspector_viewport_rect=lambda: (100, 50, 400, 200),
        map_pick_to_render_ndc=lambda x, y: None if x < -0.8 else (x, y),
        renderer_adapter=SimpleNamespace(
            pick=lambda x, y, cb, request: (calls.append((x, y)), callbacks.append(cb)),
            cancel_pick=lambda request: calls.append("cancel"),
        ),
        apply_pick_selection=lambda path, mode: selection.append((path, mode)),
        get_viewport_state_snapshot=lambda: SimpleNamespace(
            active_camera_path="/Camera",
            cameras=(
                Camera("ovui:perspective", "Perspective", False),
                Camera("/Camera", "Camera", True),
            ),
        ),
        select_camera_path=lambda path: path == "/Camera",
    )
    bus = SimpleNamespace(get_snapshot=lambda: SimpleNamespace(paths=lambda: selection))
    return ViewportInspector(lambda: {"primary": surface}, lambda: bus), calls, callbacks, selection


def test_offset_coordinates_and_selection_share_the_renderer():
    async def run():
        api, calls, callbacks, selection = provider()
        task = asyncio.create_task(api.pick(300, 150, mode="add"))
        await asyncio.sleep(0)
        assert calls == [(0, 0)]
        callbacks[0]("/Cube", [1, 2, 3])
        result = await task
        assert selection == [("/Cube", "add")]
        assert result["hit"]["path"] == "/Cube"
        assert calls[-1] == "cancel"

    asyncio.run(run())


@pytest.mark.parametrize("x,y", [(99, 60), (500, 60), (150, 250), (101, 150)])
def test_outside_and_letterbox_pixels_never_pick(x, y):
    api, calls, _, selection = provider()
    with pytest.raises(ValueError):
        asyncio.run(api.pick(x, y))
    assert not calls and not selection


def test_cancelled_pick_ignores_a_late_renderer_callback():
    async def run():
        api, calls, callbacks, selection = provider()
        task = asyncio.create_task(api.pick(300, 150))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        callbacks[0]("/Late", [0, 0, 0])
        assert not selection
        assert calls[-1] == "cancel"

    asyncio.run(run())


def test_catalog_lists_bindable_authored_cameras_and_rejects_missing_view():
    api, _, _, _ = provider()
    assert [c["path"] for c in api.cameras()["cameras"]] == ["/Camera"]
    assert api.camera("/Camera")["active_camera_path"] == "/Camera"
    with pytest.raises(ValueError):
        api.camera("/Missing")
    with pytest.raises(ValueError):
        api.cameras("missing")


def test_camera_binding_can_update_host_product_as_well_as_surface():
    api, calls, _, _ = provider()
    api.camera_setter = lambda path, view: calls.append((path, view))
    api.camera("/Camera")
    assert calls == [("/Camera", "primary")]
    with pytest.raises(ValueError, match="Unknown viewport"):
        api.camera("/Camera", view_id="hidden")
    assert calls == [("/Camera", "primary")]


def test_rejected_frame_request_leaves_the_camera_alone():
    calls = []
    surface = SimpleNamespace(
        frame_paths=lambda paths, fallback_to_default=True: (
            calls.append((paths, fallback_to_default)), False
        )[1]
    )
    api = ViewportInspector(lambda: {"primary": surface}, lambda: None)
    with pytest.raises(ValueError, match="No bounds"):
        api.frame(paths=["/World/NoSuch"])
    # A rejected command must not move the camera to the default focus.
    assert calls == [(["/World/NoSuch"], False)]


def test_frame_paths_without_bounds_can_skip_the_default_focus():
    from unittest.mock import Mock

    from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
    from ovui_widgets.viewport.viewport_widget import ViewportWidget

    viewport = ViewportWidget(services=None, renderer=MockRendererAdapter())
    viewport._stage_adapter_provider = lambda: SimpleNamespace(
        compute_world_aabb=lambda paths: None, get_up_axis=lambda: "Z"
    )
    viewport._camera.focus = Mock()
    assert viewport.frame_paths(["/World/NoSuch"], fallback_to_default=False) is False
    viewport._camera.focus.assert_not_called()
    # Interactive framing keeps its usable default.
    assert viewport.frame_paths(["/World/NoSuch"]) is False
    viewport._camera.focus.assert_called_once_with([0.0, 0.0, 0.0], 5.0)
    viewport.destroy()
