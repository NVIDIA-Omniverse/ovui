# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""Inspector vocabulary for any host of stock ViewportSurface widgets.

The provider receives viewport and selection accessors. It has no USD, renderer
SDK, application singleton or USD Workbench dependency; adapters remain authoritative.
"""

import asyncio
from dataclasses import asdict
import uuid


class ViewportInspector:
    def __init__(self, viewports, selection_bus, camera_setter=None):
        self.viewports = viewports
        self.selection_bus = selection_bus
        self.camera_setter = camera_setter

    def surface(self, view_id):
        views = self.viewports()
        if view_id not in views:
            raise ValueError(f"Unknown viewport {view_id!r}; available: {list(views)}")
        return views[view_id]

    def list(self):
        views = []
        for key, surface in self.viewports().items():
            snapshot = asdict(surface.get_viewport_state_snapshot())
            # The viewport_tool vocabulary: selection mode hides the gizmo but
            # keeps the widget's active transform tool.
            tool = snapshot.get("active_tool")
            if not snapshot.get("transform_manipulator_visible", True):
                tool = "select"
            elif tool == "translate":
                tool = "move"
            views.append({"view_id": key, "tool": tool, **snapshot})
        return {"views": views}

    def selection(self):
        return {"selection": list(self.selection_bus().get_snapshot().paths())}

    def cameras(self, view_id="primary"):
        snapshot = self.surface(view_id).get_viewport_state_snapshot()
        return {
            "active_camera_path": snapshot.active_camera_path,
            "cameras": [
                asdict(camera) for camera in snapshot.cameras if camera.path.startswith("/")
            ],
        }

    def camera(self, path, view_id="primary"):
        surface = self.surface(view_id)
        if self.camera_setter is not None:
            self.camera_setter(path, view_id)
        elif not surface.select_camera_path(path):
            raise ValueError(f"Cannot bind camera: {path}")
        return self.cameras(view_id)

    def frame(self, paths=None, view_id="primary"):
        selected = paths if paths is not None else self.selection()["selection"]
        # A rejected request must not move the camera to the default focus.
        if not self.surface(view_id).frame_paths(selected or ["/"], fallback_to_default=False):
            raise ValueError(f"No bounds available to frame: {selected or ['/']}")
        return {"framed": selected or ["/"]}

    def tool(self, tool="select", view_id="primary"):
        surface = self.surface(view_id)
        if tool != "select" and not surface.set_active_tool(
            "translate" if tool == "move" else tool
        ):
            raise ValueError(f"Cannot activate viewport tool: {tool}")
        # Selection mode hides the gizmo; a later explicit tool choice (this
        # command, the toolbar or W/E/R) shows it again.
        surface.set_transform_manipulator_visible(tool != "select")
        return {"tool": tool, "view_id": view_id}

    async def pick(self, x, y, view_id="primary", mode="replace"):
        surface = self.surface(view_id)
        rect = surface.get_inspector_viewport_rect()
        left, top, width, height = rect
        if width <= 0 or height <= 0 or not (left <= x < left + width and top <= y < top + height):
            raise ValueError(
                "Pixel is outside the visible viewport; use a current application screenshot"
            )
        ndc = surface.map_pick_to_render_ndc(2 * (x - left) / width - 1, 1 - 2 * (y - top) / height)
        if ndc is None:
            raise ValueError("Pixel is in viewport letterboxing")
        renderer = surface.renderer_adapter
        if renderer is None:
            raise ValueError("Viewport has no renderer")
        future = asyncio.get_running_loop().create_future()

        def complete(path, position):
            if not future.done():
                path = surface.resolve_pick_path(*ndc, path)
                surface.apply_pick_selection(path, mode)
                future.set_result(
                    {
                        "path": str(path) if path else None,
                        "world_position": list(position) if position is not None else None,
                    }
                )

        request_id = "inspector-" + uuid.uuid4().hex
        try:
            renderer.pick(*ndc, complete, request_id)
            hit = await asyncio.wait_for(future, 30)
        finally:
            renderer.cancel_pick(request_id)
        return {"hit": hit, **self.selection()}

    def commands(self):
        # Optional Inspector dependency is imported only for an inspected host.
        from ovuiinspect import Arguments, Command
        from pydantic import Field
        from typing import Literal

        class View(Arguments):
            view_id: str = "primary"

        class Camera(View):
            path: str

        class Frame(View):
            paths: list[str] | None = None

        class Tool(View):
            tool: Literal["select", "move", "rotate", "scale"] = "select"

        class Pick(View):
            x: float = Field(ge=0)
            y: float = Field(ge=0)
            mode: Literal["replace", "add", "toggle", "remove"] = "replace"

        return [
            Command(name, description, arguments, handler, read_only, "viewport")
            for name, description, arguments, handler, read_only in (
                (
                    "viewport_list",
                    "List application viewports and their current tools/cameras; tool is select, move, rotate or scale (active_tool is the gizmo remembered in selection mode).",
                    Arguments,
                    self.list,
                    True,
                ),
                (
                    "selection_get",
                    "Read the application's authoritative selection paths.",
                    Arguments,
                    self.selection,
                    True,
                ),
                (
                    "camera_list",
                    "List authored cameras available through the viewport's adapter.",
                    View,
                    self.cameras,
                    True,
                ),
                (
                    "camera_set",
                    "Bind this viewport to an existing camera path.",
                    Camera,
                    self.camera,
                    False,
                ),
                (
                    "viewport_frame",
                    "Frame specified paths or the current selection.",
                    Frame,
                    self.frame,
                    False,
                ),
                (
                    "viewport_tool",
                    "Choose the stock selection or transform manipulator.",
                    Tool,
                    self.tool,
                    False,
                ),
                (
                    "viewport_pick",
                    "Pick current full-application screenshot pixels through the renderer and selection bus. Recapture after camera/scene/size changes.",
                    Pick,
                    self.pick,
                    False,
                ),
            )
        ]
