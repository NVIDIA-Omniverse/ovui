# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Focused nonvisual guards for the exact-runtime render/pick contract.

Real OVRTX rendering and pointer input are proven by the external packaged-app
evidence.  These tests deliberately cover only deterministic adapter behavior
that can be exercised without claiming a GPU or full-application result.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

from ovui_data_adapters.ovstage import renderer_adapter as renderer_module
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter


class _NativeHierarchyStage:
    def __init__(self, paths: set[str]) -> None:
        self.paths = set(paths)
        self.child_queries: list[str] = []

    def get_child_paths(self, parent: str) -> tuple[str, ...]:
        self.child_queries.append(str(parent))
        prefix = f"{parent}/" if parent else "/"
        return tuple(
            sorted(
                path
                for path in self.paths
                if path.startswith(prefix)
                and "/" not in path[len(prefix) :]
            )
        )


def test_private_runtime_prefix_uses_native_occupancy_without_touching_user_roots() -> None:
    stage = _NativeHierarchyStage({"/_OvuiRuntime", "/_OvuiRuntime_1", "/World"})
    scene = SimpleNamespace(_stage=stage)

    selected = renderer_module._select_runtime_root_path(scene)

    assert selected == "/_OvuiRuntime_2"
    assert stage.paths == {"/_OvuiRuntime", "/_OvuiRuntime_1", "/World"}
    # The established renderer sequence is the unsuffixed root followed by
    # numeric candidates beginning at ``_2``.  Both candidates are checked
    # through the public hierarchy before the private reference is authored.
    assert stage.child_queries == ["", ""]
    payload = renderer_module._build_runtime_layer(
        stage,
        records={},
        runtime_root_path=selected,
    )
    assert payload.root_path == selected
    assert payload.camera_path == "/_OvuiRuntime_2/Render/Cameras/Main"
    assert payload.render_product_path == "/_OvuiRuntime_2/Render/Viewport"


class _PathDictionary:
    def __init__(self, paths: dict[int, str]) -> None:
        self.paths = dict(paths)
        self.resolved_ids: list[int] = []
        self.destroyed = False

    def path_to_string(self, path_id: int) -> str:
        assert not self.destroyed
        self.resolved_ids.append(int(path_id))
        return self.paths.get(int(path_id), "")

    def destroy(self) -> None:
        self.destroyed = True


class _MappedPickResult(dict[str, np.ndarray]):
    def __init__(self, path_id: int) -> None:
        super().__init__(
            primPath=np.asarray([path_id], dtype=np.uint64),
            worldPositionM=np.asarray([[1.25, -2.5, 3.75]], dtype=np.float64),
        )
        self.params = {
            "magic": np.asarray([0x56505448], dtype=np.uint32),
            "version": np.asarray([1], dtype=np.uint32),
            "hitCount": np.asarray([1], dtype=np.uint32),
        }


def _pick_adapter(dictionary: _PathDictionary) -> OvstageRendererAdapter:
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._ovrtx = SimpleNamespace(
        OVRTX_PICK_HIT_MAGIC=0x56505448,
        OVRTX_PICK_HIT_VERSION=1,
    )
    adapter._path_dictionary = dictionary
    adapter._runtime_root_path = "/_OvuiRuntime_2"
    return adapter


def test_native_pick_id_is_copied_then_resolved_by_the_live_path_dictionary() -> None:
    dictionary = _PathDictionary({0xC0FFEE: "/World/Geometry/PickCube"})
    adapter = _pick_adapter(dictionary)

    hits = adapter._parse_pick_hit_mapping(_MappedPickResult(0xC0FFEE))

    assert hits == [("/World/Geometry/PickCube", (1.25, -2.5, 3.75))]
    assert dictionary.resolved_ids == [0xC0FFEE]


def test_private_pick_paths_are_filtered_from_application_selection() -> None:
    dictionary = _PathDictionary(
        {
            7: "/_OvuiRuntime_2/Render/Viewport",
            8: "/World/Geometry/PickCube",
        }
    )
    adapter = _pick_adapter(dictionary)

    assert adapter._resolve_ovrtx_prim_path(7) is None
    assert adapter._resolve_ovrtx_prim_path(8) == "/World/Geometry/PickCube"
    assert dictionary.resolved_ids == [7, 8]


def test_dictionary_generation_is_neutralized_before_a_replacement_resolves() -> None:
    old_dictionary = _PathDictionary({41: "/Old/Target"})
    old_adapter = _pick_adapter(old_dictionary)
    assert old_adapter._resolve_ovrtx_prim_path(41) == "/Old/Target"

    old_dictionary.destroy()
    old_adapter._path_dictionary = None
    new_dictionary = _PathDictionary({41: "/New/Target"})
    new_adapter = _pick_adapter(new_dictionary)

    assert old_adapter._resolve_ovrtx_prim_path(41) is None
    assert new_adapter._resolve_ovrtx_prim_path(41) == "/New/Target"
    assert old_dictionary.resolved_ids == [41]
    assert new_dictionary.resolved_ids == [41]


def test_remove_scene_detaches_then_destroys_dictionary_and_owned_root(monkeypatch) -> None:
    events: list[Any] = []
    user_paths = {"/_OvuiRuntime", "/_OvuiRuntime_1", "/World"}
    stage = SimpleNamespace(name="generation-a")
    dictionary = _PathDictionary({73: "/World/Target"})

    class Renderer:
        def detach_ovstage(self) -> None:
            events.append("renderer.detach")

    class Scene:
        def detach_renderer(self, adapter: Any) -> None:
            events.append(("scene.detach", adapter))

    def remove_runtime_layer_from_scene(**kwargs: Any) -> None:
        events.append(
            (
                "population.remove",
                kwargs["stage"],
                kwargs["reference_handle"],
                kwargs["runtime_root_path"],
            )
        )

    monkeypatch.setattr(
        renderer_module,
        "_remove_runtime_layer_from_scene",
        remove_runtime_layer_from_scene,
    )
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._attached_stage = stage
    adapter._renderer = Renderer()
    adapter._scene = Scene()
    adapter._runtime_population = object()
    adapter._runtime_reference_handle = "reference-a"
    adapter._path_dictionary = dictionary
    adapter._runtime_root_path = "/_OvuiRuntime_2"

    adapter._remove_scene()

    assert events[0] == "renderer.detach"
    assert events[1][0] == "scene.detach"
    assert events[2] == (
        "population.remove",
        stage,
        "reference-a",
        "/_OvuiRuntime_2",
    )
    assert dictionary.destroyed is True
    assert adapter._attached_stage is None
    assert adapter._path_dictionary is None
    assert adapter._resolve_ovrtx_prim_path(73) is None
    assert user_paths == {"/_OvuiRuntime", "/_OvuiRuntime_1", "/World"}


def test_renderer_module_has_no_forbidden_provider_or_usd_import_boundary() -> None:
    source_path = Path(renderer_module.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert "pxr" not in imported_roots
    assert "openusd" not in imported_roots
    assert "backing_usd" not in source_path.read_text(encoding="utf-8")
