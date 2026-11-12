# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Inspector commands for render diagnostics.

The Inspector loads :func:`inspector_commands` through the entry-point group
``ovui.inspector_commands`` (declared by ``ovui-data-adapters-common``), so an
application that has this module installed, for example USD Workbench, gets the
commands without its own code, and ovui does not depend on this module.

The commands describe and check what the application shows: its open OpenUSD
stage, or the native OVStage scene of its renderer adapter, with the edits that
are not saved. Nothing is opened again from disk, and no second copy of the
scene is kept.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from ovui_data_adapters.common import render_diagnostics as rd

#: Seconds between two looks at a material check that runs in the renderer.
_CHECK_POLL = 0.05


def _is_pxr_stage(stage: Any) -> bool:
    return stage is not None and hasattr(stage, "Traverse") and hasattr(stage, "GetUsedLayers")


class RenderDiagnosticsService:
    """The render diagnostics commands of one application.

    ``stage_provider`` returns the application's open OpenUSD stage (or None when its scene is not an
    OpenUSD stage), ``renderer_provider`` its active renderer adapter (or None).
    """

    def __init__(self, stage_provider: Callable[[], Any], renderer_provider: Callable[[], Any]) -> None:
        self._stage_provider = stage_provider
        self._renderer_provider = renderer_provider

    # -- commands --------------------------------------------------------
    def describe(self, path_prefix: str = "", limit: int = 500) -> dict[str, Any]:
        """The report of each material of the open scene (see ``render_material_report``)."""

        stage = self._stage_provider()
        if _is_pxr_stage(stage):
            from ovui_data_adapters.common.render_material_report import describe_materials

            report = describe_materials(stage, path_prefix, limit=limit)
        else:
            describe = getattr(self._renderer_provider(), "describe_materials", None)
            if not callable(describe):
                raise RuntimeError(
                    "no scene is open: the application has no OpenUSD stage and its renderer cannot describe a "
                    "native scene"
                )
            report = describe(path_prefix, limit)
        report["resources"] = rd.last_resource_report()
        return report

    def gpu_memory(self) -> dict[str, Any]:
        from ovui_data_adapters.common.render_telemetry import last_renderer_diagnostics

        gpu, host, at_start = rd.read_gpu_memory(), rd.read_host_memory(), rd.gpu_memory_before_renderer()
        return {
            "gpu": vars(gpu) | {"available": gpu.available},
            "gpu_free_when_renderer_started": vars(at_start) if at_start is not None else None,
            "host": vars(host),
            # Totals that the renderer itself reports, when the loaded code that holds its table is identified.
            "renderer": last_renderer_diagnostics(),
        }

    async def verify(self, path_prefix: str = "", limit: int = 500, timeout: float = 300.0) -> dict[str, Any]:
        """Run the material check in the application's own renderer (see ``render_probe``).

        The renderer adapter runs it at its next frame, on the thread that renders, with the scene that it
        shows (unsaved edits included), also when native frame pacing draws the viewport. This handler waits
        for it without stopping the frame loop. When the handler ends without the result (its time limit, or
        the Inspector cancels the command), the request is cancelled: it leaves the adapter's queue and never
        runs later.
        """

        renderer = self._renderer_provider()
        request = getattr(renderer, "request_material_check", None)
        if not callable(request):
            raise RuntimeError(
                "the application's renderer cannot check its materials "
                f"({'no renderer is active' if renderer is None else type(renderer).__name__ + ' has no material check'})"
            )
        pending = request(path_prefix, limit)
        deadline = time.monotonic() + timeout
        try:
            while not pending.done():
                if time.monotonic() > deadline:
                    raise RuntimeError(
                        f"the material check did not end in {timeout:.0f} s; it runs at the next frame of the "
                        "viewport (is the viewport shown?)"
                    )
                await asyncio.sleep(_CHECK_POLL)
        finally:
            if not pending.done():
                pending.cancel()
        result = pending.result()
        counts: dict[str, int] = {}
        for item in result["materials"].values():
            counts[item["state"]] = counts.get(item["state"], 0) + 1
        return {
            "mode": f"in the application's renderer ({type(renderer).__name__})",
            "counts": counts, "mismatches": result["mismatches"], "failures": result["failures"],
            "unverified": result["unverified"], "not_reached": result.get("not_reached", []),
            "stage_dirty": result.get("stage_dirty"),
            "materials": result["materials"],
        }

    def commands(self) -> list[Any]:
        from ovuiinspect import Arguments, Command
        from pydantic import Field

        class Describe(Arguments):
            path_prefix: str = Field(default="", description="Only materials whose path starts with this text.")
            limit: int = Field(default=500, ge=1, le=10000)

        class Verify(Describe):
            timeout: float = Field(default=300.0, gt=0, le=600, description="Seconds to wait for the check.")

        return [
            Command(
                name="render_diagnostics",
                description=(
                    "Per material of the open scene: what the scene authors (preferred context, shader identifier, "
                    "texture URIs) and what the renderer did (generated module, failures from its log, material "
                    "check result), with warnings. Failures that name no material are listed as scene events. Also "
                    "GPU/host memory warnings for the open scene."
                ),
                arguments=Describe,
                handler=lambda path_prefix="", limit=500: self.describe(path_prefix, limit),
                read_only=True,
                category="diagnostics",
            ),
            Command(
                name="material_verify",
                description=(
                    "Draw each material of the open scene beside a flat reference of the expected colour, in the "
                    "application's own renderer, and compare them. Finds materials that the renderer shows wrong or "
                    "as a fallback. Unsaved edits are checked as they are shown."
                ),
                arguments=Verify,
                handler=lambda path_prefix="", limit=500, timeout=300.0: self.verify(path_prefix, limit, timeout),
                read_only=True,
                category="diagnostics",
            ),
            Command(
                name="gpu_memory",
                description=(
                    "GPU memory visible to this process (works on MIG partitions; for an integrated GPU with unified "
                    "memory, such as GB10, the memory that it shares with the host, with a note on its limits), the "
                    "GPU memory that was free when the renderer started, the host memory limit and use, and the "
                    "renderer's own device-memory and "
                    "texture-streaming totals when the loaded renderer code is identified as the build of an "
                    "installed client contract (otherwise the reason)."
                ),
                arguments=Arguments,
                handler=lambda: self.gpu_memory(),
                read_only=True,
                category="diagnostics",
            ),
        ]


def application_stage(application: Any) -> Any:
    """The open OpenUSD stage of an application, or None (a native OVStage scene is not an OpenUSD stage)."""

    getter = getattr(application, "get_stage_adapter", None)
    owners = [application, getter() if callable(getter) else getattr(application, "_stage_adapter", None)]
    for owner in owners:
        value = getattr(owner, "stage", None)
        if _is_pxr_stage(value):
            return value
    return None


def application_renderer(application: Any) -> Any:
    """The active renderer adapter of an application, or None.

    ``get_renderer_adapter()`` (USD Viewer: the renderer of its viewport), else a ``renderer`` attribute.
    """

    getter = getattr(application, "get_renderer_adapter", None)
    if callable(getter):
        return getter()
    return getattr(application, "renderer", None)


def inspector_commands(application: Any) -> list[Any]:
    """Entry point ``ovui.inspector_commands``: the commands for one attached application."""

    return RenderDiagnosticsService(
        lambda: application_stage(application), lambda: application_renderer(application)
    ).commands()


def inspector_status() -> dict[str, Any]:
    """Entry point ``ovui.inspector_status``: shows render failures in ``health``.

    ``degraded`` is True when there is evidence that the render can be wrong: the renderer reported a
    failure, the material check found a material shown wrong or could not run at all, or GPU or host
    memory is below the minimum for the scene. A material that could not be checked is not such evidence:
    it is counted and named (``materials_unverified``), never hidden, but a large scene has many of them,
    and a health that is always degraded would hide the real failures. The application keeps running; each
    failure is named, so that a wrong render is not silent. The failures are those of the open scene.
    """

    events = rd.get_render_diagnostics().events()
    # A material that cannot be checked is not a failure; a check that could not run at all (a scene event) is.
    failures = [e for e in events if e["kind"] != "unverified" or e["scope"] == "scene"]
    check = rd.get_verification()
    wrong = sorted(path for path, item in check.items() if item["state"] == "mismatch")
    unverified = sorted(path for path, item in check.items() if item["state"] == "unverifiable")
    counts: dict[str, int] = {}
    for item in check.values():
        counts[item["state"]] = counts.get(item["state"], 0) + 1
    kinds: dict[str, int] = {}
    for event in failures:
        kinds[event["kind"]] = kinds.get(event["kind"], 0) + 1
    resources = rd.last_resource_report()
    below_minimum = list(resources.get("below_minimum", []))
    return {
        "degraded": bool(failures or below_minimum),
        "failure_events": len(failures),
        "failure_kinds": kinds,
        "materials_shown_wrong": wrong,
        "materials_unverified": unverified[:50],
        "materials_unverified_count": len(unverified),
        "material_check": counts or "not_run",
        "resource_warnings": list(resources.get("warnings", [])),
        "resources_below_minimum": below_minimum,
        "newest": [
            {k: e[k] for k in ("kind", "material", "resource", "message")} for e in failures[-5:]
        ],
        "details": "call the render_diagnostics command",
    }
