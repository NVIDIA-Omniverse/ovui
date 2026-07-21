# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION is strictly
# prohibited.

"""OVStage-native held-transform preview contracts.

The full application and real pointer gesture are proven by external evidence.
These focused tests exercise the public renderer preview seam against the exact
OVStage runtime without claiming that unit calls are viewport input.
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys
from typing import Any, Iterator

import numpy as np
import pytest

from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage.provider import (
    create_provider_session,
    create_transform_adapter,
)
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes


_SCENE = '''#usda 1.0
(
    upAxis = "Z"
)

def Xform "World"
{
    double3 xformOp:translate = (10, -4, 2)
    double xformOp:rotateZ = 31
    float3 xformOp:scale = (2, 3, 1)
    uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateZ", "xformOp:scale"]

    def Cube "First"
    {
        double size = 2
        double3 xformOp:translate = (-2, 0, 1)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }

    def Sphere "Second"
    {
        double radius = 1
        double3 xformOp:translate = (3, 1, -1)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }

    def Scope "NotTransformable" {}
}
'''


@pytest.fixture(scope="module")
def ovstage_runtime() -> Any:
    package_parent = Path(__file__).resolve().parents[2]
    previous_paths = list(sys.path)
    loaded = sys.modules.get("ovstage")
    if loaded is not None and not callable(getattr(loaded, "Stage", None)):
        sys.modules.pop("ovstage", None)
    sys.path[:] = [
        entry
        for entry in sys.path
        if not entry or Path(entry).resolve() != package_parent
    ]
    try:
        return load_required_runtimes(
            module_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        )
    finally:
        sys.path[:] = previous_paths


@pytest.fixture()
def opened_scene(
    tmp_path: Path,
    ovstage_runtime: Any,
) -> Iterator[tuple[Any, Any, Any]]:
    scene_path = tmp_path / "live-transform-preview.usda"
    scene_path.write_text(_SCENE, encoding="utf-8")
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(scene_path))
    transform = create_transform_adapter(scene)
    try:
        yield session, scene, transform
    finally:
        session.shutdown_scene()


def _renderer_shell(scene: Any) -> OvstageRendererAdapter:
    adapter = object.__new__(OvstageRendererAdapter)
    adapter._scene = scene
    adapter._attached_stage = scene._stage
    adapter._renderer = object()
    adapter._runtime_root_path = "/_OvuiRuntime"
    adapter._live_preview_write_count = 0
    adapter._live_preview_clear_count = 0
    adapter._live_preview_paths = set()
    adapter._last_live_preview_path = None
    adapter._last_live_preview_matrix = None
    adapter._live_transform_adapter = create_transform_adapter(scene)
    return adapter


def _translated(matrix: list[list[float]], x: float, y: float, z: float) -> list[list[float]]:
    copied = [list(row) for row in matrix]
    copied[3][:3] = [float(x), float(y), float(z)]
    return copied


def _matmul(lhs: list[list[float]], rhs: list[list[float]]) -> list[list[float]]:
    return [
        [
            sum(float(lhs[row][inner]) * float(rhs[inner][column]) for inner in range(4))
            for column in range(4)
        ]
        for row in range(4)
    ]


def test_exact_preview_writes_native_transform_before_clear_without_semantic_event(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    _session, scene, transform = opened_scene
    adapter = _renderer_shell(scene)
    path = "/World/First"
    initial = transform.get_local_transform(path)
    preview = _translated(initial, 4.25, -2.5, 7.0)
    before_ordinal = int(scene.current_ordinal)

    assert adapter.supports_live_local_transform is True
    assert adapter.set_live_local_transform(path, preview) is True

    assert scene.current_ordinal == before_ordinal + 1
    assert np.asarray(transform.get_local_transform(path)) == pytest.approx(
        np.asarray(preview)
    )
    assert adapter._live_preview_write_count == 1
    assert adapter._live_preview_paths == {path}
    assert adapter._last_live_preview_path == path
    assert adapter._last_live_preview_matrix == tuple(np.asarray(preview).reshape(-1))
    # Preview changes native/render state but stays outside external authoring
    # events. Step 13 owns the eventual release/cancel semantic edge.
    assert scene.change_stream.poll() == ()

    adapter.clear_live_local_transforms([path])

    assert np.asarray(transform.get_local_transform(path)) == pytest.approx(
        np.asarray(preview)
    )
    assert adapter._live_preview_clear_count == 1
    assert adapter._live_preview_paths == set()


def test_repeated_and_multi_selection_previews_preserve_local_world_contract(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    _session, scene, transform = opened_scene
    adapter = _renderer_shell(scene)
    parent_world = transform.get_world_transform("/World")
    first_path = "/World/First"
    second_path = "/World/Second"
    first_initial = transform.get_local_transform(first_path)
    second_initial = transform.get_local_transform(second_path)

    first_mid = _translated(first_initial, 1.0, 2.0, 3.0)
    first_final = _translated(first_initial, 5.0, 6.0, 7.0)
    second_final = _translated(second_initial, -8.0, 9.0, 10.0)
    assert adapter.set_live_local_transform(first_path, first_mid) is True
    assert adapter.set_live_local_transform(first_path, first_final) is True
    assert adapter.set_live_local_transform(second_path, second_final) is True

    assert np.asarray(transform.get_local_transform(first_path)) == pytest.approx(
        np.asarray(first_final)
    )
    assert np.asarray(transform.get_local_transform(second_path)) == pytest.approx(
        np.asarray(second_final)
    )
    assert np.asarray(transform.get_world_transform(first_path)) == pytest.approx(
        np.asarray(_matmul(first_final, parent_world))
    )
    assert np.asarray(transform.get_world_transform(second_path)) == pytest.approx(
        np.asarray(_matmul(second_final, parent_world))
    )
    assert adapter._live_preview_write_count == 3
    assert adapter._live_preview_paths == {first_path, second_path}


@pytest.mark.parametrize(
    "path,matrix",
    [
        ("", np.eye(4).tolist()),
        ("World/First", np.eye(4).tolist()),
        ("/World//First", np.eye(4).tolist()),
        ("/World/First/", np.eye(4).tolist()),
        ("/World/Missing", np.eye(4).tolist()),
        ("/_OvuiRuntime/Render/Viewport", np.eye(4).tolist()),
        ("/World/First", [[1.0, 0.0], [0.0, 1.0]]),
        ("/World/First", _translated(np.eye(4).tolist(), float("nan"), 0.0, 0.0)),
        ("/World/First", np.diag([1.0, 0.0, 1.0, 1.0]).tolist()),
    ],
)
def test_invalid_preview_fails_without_native_or_bookkeeping_residue(
    opened_scene: tuple[Any, Any, Any],
    path: str,
    matrix: Any,
) -> None:
    _session, scene, _transform = opened_scene
    adapter = _renderer_shell(scene)
    before_ordinal = int(scene.current_ordinal)

    assert adapter.set_live_local_transform(path, matrix) is False
    assert scene.current_ordinal == before_ordinal
    assert adapter._live_preview_write_count == 0
    assert adapter._live_preview_paths == set()


def test_closed_or_foreign_attachment_never_writes(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    session, scene, transform = opened_scene
    path = "/World/First"
    preview = _translated(transform.get_local_transform(path), 20.0, 0.0, 0.0)
    foreign = _renderer_shell(scene)
    foreign._attached_stage = object()
    before_ordinal = int(scene.current_ordinal)
    assert foreign.supports_live_local_transform is False
    assert foreign.set_live_local_transform(path, preview) is False
    assert scene.current_ordinal == before_ordinal

    closed = _renderer_shell(scene)
    session.shutdown_scene()
    assert closed.supports_live_local_transform is False
    assert closed.set_live_local_transform(path, preview) is False


def test_preview_source_has_no_forbidden_usd_or_widget_boundary() -> None:
    source_path = Path(sys.modules[OvstageRendererAdapter.__module__].__file__).resolve()
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert not {"pxr", "openusd", "ovui_widgets"}.intersection(imported_roots)
    assert "backing_usd" not in source
