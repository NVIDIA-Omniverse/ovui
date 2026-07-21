# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Runtime-free contract tests for native OVStage BORROW rendering."""

from __future__ import annotations

import ast
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from ovui_data_adapters.ovstage import renderer_adapter as renderer_module
from ovui_data_adapters.ovstage._scene import OvstageScene
from ovui_data_adapters.ovstage.provider import OvstageProviderSession
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter

_ALLOWED_RENDERER_CALLS = frozenset(
    {
        # Native OVStage attachment and presentation.
        "attach_ovstage",
        "detach_ovstage",
        "step",
        # Presentation-only interaction and renderer controls.
        "enqueue_pick_query",
        "reset",
        "set_selection_group_styles",
        # Selection-outline membership is renderer-owned, stream-ordered
        # presentation state (dedicated API in ovrtx 0.4); it never
        # writes the borrowed OVStage data plane.
        "set_selection_outline_group_strings",
        "set_selection_outline_group_strings_async",
        # Read-only renderer metadata used for diagnostics and assertions.
        "config",
        "version",
    }
)


def _is_self_renderer(node: ast.AST, aliases: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr == "_renderer"
    ) or (isinstance(node, ast.Name) and node.id in aliases) or (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "self"
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "_renderer"
    )


def _assigned_names(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, (ast.Tuple, ast.List)):
        return tuple(name for element in node.elts for name in _assigned_names(element))
    return ()


def _renderer_calls(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    aliases: set[str] = set()
    method_aliases: dict[str, str] = {}

    # Resolve local aliases independently of statement order so the check also
    # catches a helper variable introduced during a future refactor.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(function):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if value is not None and _is_self_renderer(value, aliases):
                for target in targets:
                    for name in _assigned_names(target):
                        if name not in aliases:
                            aliases.add(name)
                            changed = True

    for node in ast.walk(function):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "getattr"
            and len(value.args) >= 2
            and _is_self_renderer(value.args[0], aliases)
            and isinstance(value.args[1], ast.Constant)
            and isinstance(value.args[1].value, str)
        ):
            for target in targets:
                for name in _assigned_names(target):
                    method_aliases[name] = value.args[1].value

    calls: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and _is_self_renderer(
            node.func.value, aliases
        ):
            calls.add(node.func.attr)
        elif isinstance(node.func, ast.Name) and node.func.id in method_aliases:
            calls.add(method_aliases[node.func.id])
        elif (
            isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and _is_self_renderer(node.args[0], aliases)
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            calls.add(node.args[1].value)
    return calls


def test_ovrtx_renderer_calls_remain_presentation_only() -> None:
    """BORROW mode must never grow a second, OVRTX-owned scene data plane.

    Scan the complete provider package rather than only ``renderer_adapter`` so
    a future helper cannot move an OVRTX data call outside the original guard.
    """
    source_path = Path(renderer_module.__file__).resolve()
    calls_by_function: dict[str, set[str]] = {}
    for candidate in source_path.parent.rglob("*.py"):
        tree = ast.parse(
            candidate.read_text(encoding="utf-8"),
            filename=str(candidate),
        )
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls_by_function[
                    f"{candidate.relative_to(source_path.parent)}:{node.name}:{node.lineno}"
                ] = _renderer_calls(node)
    disallowed = {
        function_name: sorted(calls - _ALLOWED_RENDERER_CALLS)
        for function_name, calls in calls_by_function.items()
        if calls - _ALLOWED_RENDERER_CALLS
    }

    assert disallowed == {}, (
        "OVRTX BORROW mode may attach, present, pick, and configure rendering, "
        f"but must not use the OVRTX data API: {disallowed}"
    )


def test_borrow_ast_guard_tracks_getattr_renderer_aliases() -> None:
    """A future data write cannot evade the guard through ``getattr``."""

    tree = ast.parse(
        """
def mutate(self):
    renderer = getattr(self, "_renderer", None)
    writer = getattr(renderer, "write_attribute", None)
    writer("/World/Cube", "visibility", "invisible")
    getattr(self, "_renderer").reset_stage()
"""
    )
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)

    assert _renderer_calls(function) == {"reset_stage", "write_attribute"}


class _BorrowRenderer:
    def __init__(self) -> None:
        self.step_calls: list[dict[str, Any]] = []
        self.forbidden_attribute_lookups: list[str] = []

    def step(self, **kwargs: Any) -> dict[str, object]:
        self.step_calls.append(dict(kwargs))
        return {}

    def __getattr__(self, name: str) -> Any:
        self.forbidden_attribute_lookups.append(name)
        raise AssertionError(f"unexpected OVRTX renderer API lookup: {name}")


def _borrow_adapter(renderer: _BorrowRenderer) -> OvstageRendererAdapter:
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._scene = SimpleNamespace(current_ordinal=37)
    adapter._renderer = renderer
    adapter._attached_stage = object()
    adapter._render_product_path = "/_OvuiRuntime/Render/Viewport"
    adapter._camera_path = None
    adapter._last_resolution = (64, 32)
    adapter._last_render_product_resolution = (64, 32)
    adapter._last_view_matrix = None
    adapter._last_proj_matrix = None
    adapter._dt_clock = time.monotonic()
    adapter._logged_first_step = True
    adapter._borrow_step_count = 0
    adapter._successful_frame_count = 0
    adapter._last_frame_nonblack_pixels = None
    adapter._last_frame_shape = None
    adapter._in_flight_pick_queries = []
    adapter._extract_ldr_color = (  # type: ignore[method-assign]
        lambda _products, width, height: np.zeros((height, width, 4), dtype=np.uint8)
    )
    return adapter


def test_render_frame_steps_the_attached_ovstage_ordinal() -> None:
    renderer = _BorrowRenderer()
    adapter = _borrow_adapter(renderer)

    frame = adapter.render_frame(64, 32, None, None)

    assert frame.shape == (32, 64, 4)
    assert len(renderer.step_calls) == 1
    call = renderer.step_calls[0]
    assert call["render_products"] == {"/_OvuiRuntime/Render/Viewport"}
    assert call["ordinal"] == 37
    assert call["delta_time"] > 0.0
    assert adapter._borrow_step_count == 1
    assert renderer.forbidden_attribute_lookups == []


def test_borrow_mode_declines_preview_without_an_attached_ovstage_owner() -> None:
    renderer = _BorrowRenderer()
    adapter = _borrow_adapter(renderer)

    assert adapter.supports_live_local_transform is False
    assert adapter.set_live_local_transform("/World/Cube", np.eye(4).tolist()) is False
    assert adapter.clear_live_local_transforms(["/World/Cube"]) is None
    assert renderer.forbidden_attribute_lookups == []


def test_pick_path_ids_are_resolved_by_the_ovstage_dictionary() -> None:
    renderer = _BorrowRenderer()
    adapter = _borrow_adapter(renderer)
    resolved_ids: list[int] = []

    class _PathDictionary:
        def path_to_string(self, path_id: int) -> str:
            resolved_ids.append(path_id)
            return "/World/Cube"

    adapter._path_dictionary = _PathDictionary()

    assert adapter._resolve_ovrtx_prim_path(73) == "/World/Cube"
    assert resolved_ids == [73]
    assert renderer.forbidden_attribute_lookups == []


class _LifecycleStage:
    current_ordinal = 1

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def destroy(self) -> None:
        self._events.append("stage.destroy")


class _LifecycleRenderer:
    def __init__(self, events: list[str], *, fail_detach: bool = False) -> None:
        self._events = events
        self._fail_detach = fail_detach

    def detach_ovstage(self) -> None:
        self._events.append("renderer.detach_ovstage")
        if self._fail_detach:
            raise RuntimeError("mock detach failure")


class _LifecyclePathDictionary:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def destroy(self) -> None:
        self._events.append("path_dictionary.destroy")


def _attached_lifecycle_pair(
    *,
    fail_detach: bool = False,
) -> tuple[OvstageScene, OvstageRendererAdapter, _LifecycleStage, list[str]]:
    events: list[str] = []
    stage = _LifecycleStage(events)
    scene = OvstageScene(
        stage=stage,
        source_path="/tmp/borrow.usda",
        initial_ordinal=stage.current_ordinal,
        root_paths=("/World",),
    )
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._scene = scene
    adapter._renderer = _LifecycleRenderer(events, fail_detach=fail_detach)
    adapter._attached_stage = stage
    adapter._runtime_population = None
    adapter._runtime_reference_handle = None
    adapter._path_dictionary = _LifecyclePathDictionary(events)
    adapter._in_flight_pick_queries = []
    scene.attach_renderer(adapter)
    return scene, adapter, stage, events


def test_scene_shutdown_detaches_borrow_renderer_before_destroying_stage() -> None:
    scene, adapter, _stage, events = _attached_lifecycle_pair()

    scene.shutdown()

    assert events == [
        "renderer.detach_ovstage",
        "path_dictionary.destroy",
        "stage.destroy",
    ]
    assert scene.is_open is False
    assert adapter._attached_stage is None
    assert adapter._renderer is None


def test_detach_failure_blocks_stage_destruction_and_preserves_provider_owner() -> None:
    scene, adapter, stage, events = _attached_lifecycle_pair(fail_detach=True)
    session = OvstageProviderSession.__new__(OvstageProviderSession)
    session._current_scene = scene
    session.physics_controls = SimpleNamespace(
        disable=lambda: events.append("physics.disable")
    )

    with pytest.raises(RuntimeError, match="mock detach failure"):
        session.shutdown_scene()

    assert events == ["physics.disable", "renderer.detach_ovstage"]
    assert session.current_scene is scene
    assert scene.is_open is True
    assert scene._stage is stage
    assert adapter._attached_stage is stage
    assert adapter._renderer is not None
