# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""OVStage BORROW camera, pick, render-product, and highlight behavior."""

from __future__ import annotations

import pathlib
import time
from collections import deque
from types import SimpleNamespace
from typing import Any, Iterator

import numpy as np
import pytest

from ovui_data_adapters.ovstage import renderer_adapter as renderer_module
from ovui_data_adapters.ovstage._scene import OvstageScene
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.renderer_adapter import (
    _RENDER_CAMERA_LOCAL_PATH,
    _RENDER_PRODUCT_LOCAL_PATH,
    OvstageRendererAdapter,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.ovstage.stage_adapter import OvstageStageAdapter

pytestmark = [pytest.mark.requires_ovstage]

_CAMERA_PATH = "/World/Cameras/MainCamera"
_PICKED_PATH = "/World/Hierarchy/GroupA/BoxA"
_NEIGHBOR_PATH = "/World/Hierarchy/GroupA/BallA"
_IDENTITY4 = np.eye(4, dtype=np.float64)


@pytest.fixture()
def ovstage_runtime():
    return load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )


@pytest.fixture()
def ovstage_scene(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
) -> Iterator[OvstageScene]:
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    try:
        yield scene
    finally:
        session.shutdown_scene()


def test_stage_lists_camera_prims_and_reads_mirrored_camera_pose(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = OvstageStageAdapter(ovstage_scene)

    cameras = adapter.list_cameras()
    pose = adapter.read_camera_pose(_CAMERA_PATH)

    assert [choice.path for choice in cameras] == [_CAMERA_PATH]
    assert [choice.display_name for choice in cameras] == ["MainCamera"]
    assert pose is not None
    assert pose.prim_path == _CAMERA_PATH
    assert pose.eye == pytest.approx((6.0, 4.0, 8.0))
    assert pose.target != pytest.approx(pose.eye)
    assert 10.0 < pose.fov_degrees < 60.0


@pytest.mark.parametrize("runtime_root", ["/_OvuiRuntime", "/_OvuiRuntime_1"])
def test_primary_selectors_exclude_secondary_viewport_prims(
    tmp_path: pathlib.Path,
    ovstage_runtime: Any,
    runtime_root: str,
) -> None:
    scene_path = tmp_path / "camera_choices.usda"
    scene_path.write_text(
        '#usda 1.0\n'
        'def Xform "World"\n'
        '{\n'
        '    def Camera "Secondary" {}\n'
        '    def RenderProduct "ViewportSecondary"\n'
        '    {\n'
        '        rel camera = </World/Secondary>\n'
        '    }\n'
        '}\n'
        f'def Scope "{runtime_root[1:]}" {{\n'
        '    def Scope "Render"\n'
        '    {\n'
        '        def Scope "Cameras"\n'
        '        {\n'
        '            def Camera "Main" {}\n'
        '            def Camera "Secondary" {}\n'
        '        }\n'
        '        def RenderProduct "Viewport"\n'
        '        {\n'
        '            rel camera = <../Cameras/Main>\n'
        '        }\n'
        '        def RenderProduct "ViewportSecondary"\n'
        '        {\n'
        '            rel camera = <../Cameras/Secondary>\n'
        '        }\n'
        '    }\n'
        '}\n',
        encoding="utf-8",
    )
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(scene_path))
    try:
        scene.register_presentation_root(runtime_root)
        adapter = OvstageStageAdapter(scene)

        assert {choice.path for choice in adapter.list_cameras()} == {
            "/World/Secondary",
            f"{runtime_root}/Render/Cameras/Main",
        }
        expected_products = {
            "/World/ViewportSecondary",
            f"{runtime_root}/Render/Viewport",
        }
        assert {choice.path for choice in adapter.list_render_products()} == expected_products
        assert {
            target.render_product_path for target in adapter.get_render_target_catalog().targets
        } == expected_products
    finally:
        session.shutdown_scene()


def test_renderer_switches_to_listed_camera_path(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = _interaction_adapter(ovstage_scene, _RecordingRenderer())

    assert adapter.set_active_camera_path(_CAMERA_PATH) is True
    assert adapter.get_active_camera_path() == _CAMERA_PATH
    assert adapter.set_active_camera_path("/World/Hierarchy/GroupA/BoxA") is False
    assert adapter.get_active_camera_path() == _CAMERA_PATH
    assert adapter.set_active_camera_path(None) is True
    assert adapter.get_active_camera_path() is None


def test_renderer_type_checks_never_build_the_full_stage_value_cache(
    ovstage_scene: OvstageScene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ovui_data_adapters.ovstage._scene as scene_module

    def reject_full_value_cache(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("type check attempted the full-stage value cache")

    monkeypatch.setattr(scene_module, "_kit_stage_cache", reject_full_value_cache)
    adapter = _interaction_adapter(ovstage_scene, _RecordingRenderer())

    assert adapter.set_active_camera_path(_CAMERA_PATH) is True
    assert adapter.set_active_camera_path(_PICKED_PATH) is False


def test_runtime_layer_metadata_never_builds_the_full_stage_value_cache(
    ovstage_scene: OvstageScene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ovui_data_adapters.ovstage._scene as scene_module

    def reject_full_value_cache(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("runtime layer attempted the full-stage value cache")

    monkeypatch.setattr(scene_module, "_kit_stage_cache", reject_full_value_cache)
    stage = ovstage_scene._stage

    records = renderer_module._query_records(stage)
    matrix = renderer_module._framing_camera_matrix(
        stage,
        {_NEIGHBOR_PATH: records[_NEIGHBOR_PATH]},
    )
    mesh_bounds = renderer_module._scene_geometry_bounds(
        stage,
        {"/World/Hierarchy/GroupB/TriangleMesh": "Mesh"},
    )
    camera_matrix = renderer_module._read_matrix(
        stage,
        _CAMERA_PATH,
        "worldMatrix",
    )

    assert records[_PICKED_PATH] == "Cube"
    assert records[_NEIGHBOR_PATH] == "Sphere"
    assert matrix[12:15] == pytest.approx((3.0, 1.8, 4.0))
    assert mesh_bounds is not None
    assert mesh_bounds[0] == pytest.approx((-0.5, 0.0, 0.0))
    assert mesh_bounds[1] == pytest.approx((0.5, 1.0, 0.0))
    assert camera_matrix is not None
    assert camera_matrix[12:15] == pytest.approx((6.0, 4.0, 8.0))


def test_framing_batches_fixed_geometry_metadata_and_never_reads_mesh_points(
    ovstage_scene: OvstageScene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage = ovstage_scene._stage
    batch_reader = getattr(renderer_module, "read_paths_attribute_records", None)
    assert callable(batch_reader), "renderer framing has no batched native reader"
    calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def tracked_batch_reader(
        native_stage: Any,
        paths: Any,
        names: Any,
    ) -> Any:
        normalized_paths = tuple(str(path) for path in paths)
        normalized_names = tuple(str(name) for name in names)
        calls.append((normalized_paths, normalized_names))
        return batch_reader(native_stage, normalized_paths, normalized_names)

    def reject_per_property_reads(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("framing issued one native query per geometry property")

    monkeypatch.setattr(
        renderer_module,
        "read_paths_attribute_records",
        tracked_batch_reader,
    )
    monkeypatch.setattr(
        renderer_module,
        "_read_exact_value",
        reject_per_property_reads,
    )

    bounds = renderer_module._scene_geometry_bounds(
        stage,
        {
            _PICKED_PATH: "Cube",
            _NEIGHBOR_PATH: "Sphere",
            "/World/Hierarchy/GroupB/TriangleMesh": "Mesh",
        },
    )

    assert bounds is not None
    assert bounds[0] == pytest.approx((-0.5, -0.5, -0.5))
    assert bounds[1] == pytest.approx((0.5, 1.0, 0.5))
    assert len(calls) == 1
    assert set(calls[0][0]) == {
        _PICKED_PATH,
        _NEIGHBOR_PATH,
        "/World/Hierarchy/GroupB/TriangleMesh",
    }
    assert set(calls[0][1]) == {
        "size",
        "radius",
        "extent",
        "omni:fabric:worldMatrix",
        "omni:fabric:localMatrix",
    }


def test_batch_path_attribute_read_uses_one_native_query_for_all_paths(
    ovstage_scene: OvstageScene,
) -> None:
    from ovui_data_adapters.ovstage._native import read_paths_attribute_records

    stage = ovstage_scene._stage
    smaller_cube = "/World/VisibilityCases/HiddenParent/InheritedHiddenChild"
    original_query = stage.query_from_path_list
    original_read = stage.read_attributes
    original_release = stage.release_group
    query_calls = 0
    read_calls = 0
    release_calls = 0

    def tracked_query(path_list: Any) -> Any:
        nonlocal query_calls
        query_calls += 1
        return original_query(path_list)

    def tracked_read(query: Any, attributes: Any, ordinal_range: Any) -> Any:
        nonlocal read_calls
        read_calls += 1
        return original_read(query, attributes, ordinal_range)

    def tracked_release(group: Any) -> None:
        nonlocal release_calls
        release_calls += 1
        original_release(group)

    stage.query_from_path_list = tracked_query
    stage.read_attributes = tracked_read
    stage.release_group = tracked_release
    try:
        copied = read_paths_attribute_records(
            stage,
            (smaller_cube, _PICKED_PATH, _NEIGHBOR_PATH),
            ("size", "radius", "extent"),
        )
    finally:
        stage.query_from_path_list = original_query
        stage.read_attributes = original_read
        stage.release_group = original_release

    assert query_calls == 1
    assert read_calls == 1
    assert release_calls > 0
    assert copied[_PICKED_PATH]["size"].value == pytest.approx(1.0)
    assert copied[smaller_cube]["size"].value == pytest.approx(0.75)
    assert copied[_NEIGHBOR_PATH]["radius"].value == pytest.approx(0.5)
    assert copied[_PICKED_PATH]["extent"].value == pytest.approx(
        (-0.5, -0.5, -0.5, 0.5, 0.5, 0.5)
    )
    assert copied[_NEIGHBOR_PATH]["extent"].value == pytest.approx(
        (-0.5, -0.5, -0.5, 0.5, 0.5, 0.5)
    )


def test_exact_native_string_decoding_preserves_empty_values() -> None:
    from ovui_data_adapters.ovstage._native import _decode_path_attribute_values

    decoded_scalar = _decode_path_attribute_values(
        SimpleNamespace(),
        [0],
        (1, 8, 1),
        13,
        False,
    )
    decoded_array = _decode_path_attribute_values(
        SimpleNamespace(),
        [ord("a"), 0, 0, ord("b"), 0],
        (1, 8, 1),
        1,
        True,
    )

    assert decoded_scalar == ""
    assert decoded_array == ("a", "", "b")


def test_default_render_product_is_the_ovstage_runtime_product(
    ovstage_scene: OvstageScene,
) -> None:
    adapter = _interaction_adapter(ovstage_scene, _RecordingRenderer())

    assert adapter.get_active_render_product_path() == _RENDER_PRODUCT_LOCAL_PATH
    assert adapter.set_active_render_product_path("relative/path") is False
    assert adapter.get_active_render_product_path() == _RENDER_PRODUCT_LOCAL_PATH


def test_set_resolution_writes_only_private_ovstage_render_product(
    ovstage_scene: OvstageScene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batches: list[_RecordedBatch] = []

    class _Batch(_RecordedBatch):
        def __init__(self, stage: Any, paths: list[str]) -> None:
            super().__init__(stage, paths)
            batches.append(self)

    monkeypatch.setattr(renderer_module, "StageWriteBatch", _Batch)
    renderer = _RecordingRenderer()
    adapter = _interaction_adapter(ovstage_scene, renderer)

    adapter.set_resolution(321, 123)

    assert len(batches) == 1
    assert batches[0].stage is ovstage_scene._stage
    assert batches[0].paths == [_RENDER_PRODUCT_LOCAL_PATH]
    assert len(batches[0].writes) == 1
    attr_name, values, lanes, _semantic = batches[0].writes[0]
    assert attr_name == "resolution"
    assert tuple(values) == (321, 123)
    assert lanes == 2
    assert renderer.reset_count == 1
    assert renderer.data_api_lookups == []
    assert adapter._last_render_product_resolution is None


def test_render_frame_writes_private_camera_through_ovstage(
    ovstage_scene: OvstageScene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batches: list[_RecordedBatch] = []

    class _Batch(_RecordedBatch):
        def __init__(self, stage: Any, paths: list[str]) -> None:
            super().__init__(stage, paths)
            batches.append(self)

    monkeypatch.setattr(renderer_module, "StageWriteBatch", _Batch)
    renderer = _RecordingRenderer()
    adapter = _interaction_adapter(ovstage_scene, renderer)

    adapter.render_frame(64, 32, _IDENTITY4, _IDENTITY4)

    assert batches
    ortho_batch = batches[0]
    assert ortho_batch.stage is ovstage_scene._stage
    assert ortho_batch.paths == [_RENDER_CAMERA_LOCAL_PATH]
    assert ortho_batch.writes[0][0] == "omni:xform"
    assert ortho_batch.writes[0][2] == 16
    assert ortho_batch.token_writes == [("projection", ("orthographic",))]

    perspective_projection = np.asarray(
        (
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, -1.0, -1.0),
            (0.0, 0.0, -1.0, 0.0),
        ),
        dtype=np.float64,
    )
    adapter.render_frame(64, 32, _IDENTITY4, perspective_projection)

    assert len(batches) >= 2
    assert batches[1].token_writes == [("projection", ("perspective",))]
    assert renderer.step_ordinals == [
        int(ovstage_scene.current_ordinal),
        int(ovstage_scene.current_ordinal),
    ]
    assert renderer.data_api_lookups == []


def test_pick_uses_native_paths_and_ovstage_path_dictionary(
    ovstage_scene: OvstageScene,
) -> None:
    renderer = _RecordingRenderer()
    renderer.next_pick_hits = [(_PICKED_PATH, (0.0, 0.0, 0.0))]
    adapter = _interaction_adapter(ovstage_scene, renderer)
    received: list[tuple[str | None, Any]] = []

    adapter.pick(0.0, 0.0, lambda path, point: received.append((path, point)), "click")
    adapter.render_frame(64, 32, None, None)

    assert len(renderer.pick_queries) == 1
    render_product_path, left, top, right, bottom = renderer.pick_queries[0]
    assert render_product_path == _RENDER_PRODUCT_LOCAL_PATH
    assert left <= 0.5 < right
    assert top <= 0.5 < bottom
    assert received == [(_PICKED_PATH, (0.0, 0.0, 0.0))]
    assert adapter._path_dictionary.resolved_ids == [1]
    assert renderer.data_api_lookups == []


def test_point_pick_selects_hit_under_cursor_not_first_neighbor(
    ovstage_scene: OvstageScene,
) -> None:
    renderer = _RecordingRenderer()
    renderer.next_pick_hits = [
        (_NEIGHBOR_PATH, (0.4, 0.0, 0.0)),
        (_PICKED_PATH, (0.0, 0.0, 0.0)),
    ]
    adapter = _interaction_adapter(ovstage_scene, renderer)
    received: list[tuple[str | None, Any]] = []

    adapter.pick(0.0, 0.0, lambda path, point: received.append((path, point)), "click")
    adapter.render_frame(100, 100, _IDENTITY4, _IDENTITY4)

    assert received == [(_PICKED_PATH, (0.0, 0.0, 0.0))]


def test_point_pick_empty_space_near_geometry_reports_miss(
    ovstage_scene: OvstageScene,
) -> None:
    renderer = _RectSensitiveRenderer(
        hit_path=_PICKED_PATH,
        hit_position=(0.5, 0.0, 0.0),
        hit_pixel=(10, 50),
        resolution=(100, 100),
    )
    adapter = _interaction_adapter(ovstage_scene, renderer)
    adapter._last_render_product_resolution = (100, 100)
    received: list[tuple[str | None, Any]] = []

    adapter.pick(0.7, 0.0, lambda path, point: received.append((path, point)), "click")
    adapter.render_frame(100, 100, _IDENTITY4, _IDENTITY4)

    assert received == [(None, None)]


def test_pick_hit_mapping_accepts_explicit_unmap_contract(
    ovstage_scene: OvstageScene,
) -> None:
    renderer = _RecordingRenderer()
    renderer.next_pick_path = _PICKED_PATH
    adapter = _interaction_adapter(ovstage_scene, renderer)
    render_var = _FakeExplicitPickRenderVar([renderer.next_pick_path])
    products = {
        _RENDER_PRODUCT_LOCAL_PATH: _FakeProductWithRenderVar(render_var),
    }

    hits = adapter._read_pick_hits(products)

    assert hits == [(_PICKED_PATH, (1.0, 2.0, 3.0))]
    assert render_var.mapping is not None
    assert render_var.mapping.unmapped is True


def test_marquee_pick_dedupes_scene_paths_and_drops_runtime_paths(
    ovstage_scene: OvstageScene,
) -> None:
    renderer = _RecordingRenderer()
    renderer.next_pick_paths = [
        _PICKED_PATH,
        _PICKED_PATH,
        _RENDER_CAMERA_LOCAL_PATH,
    ]
    adapter = _interaction_adapter(ovstage_scene, renderer)
    received: list[list[str]] = []

    adapter.pick_rect(-0.5, 0.5, 0.5, -0.5, received.append)
    adapter.render_frame(64, 32, None, None)

    assert received == [[_PICKED_PATH]]


@pytest.mark.parametrize("native_version", [(0, 4, 0), (0, 5, 0), "unknown"])
def test_selection_highlight_reserved_attribute_transport_on_installed_runtime(
    ovstage_scene: OvstageScene,
    native_version: Any,
) -> None:
    """The installed ovrtx 0.4.0 surface establishes REAL applied membership.

    ``_RecordingRenderer`` models the installed wheel exactly: style APIs
    but neither ``set_selection_outline_group_strings`` variant.  Membership
    must land through the reserved ``omni:selectionOutlineGroup`` attribute
    written to the real native stage via the OVStage owner's copy-in API,
    witnessed here by the stage's committed write journal (the
    ovrtx-consumed reserved column is not surfaced back through
    ``read_attributes``; the pixel-level witness is the GPU inspector_qa
    flow, exactly as ovrtx's own pinned outline doc test asserts pixels,
    not reads).  If the requested selection never becomes applied
    membership, this test fails.  The renderer's own data plane is never
    touched and the one-shot activation reset runs exactly once while
    membership is applied.
    """
    from ovui_data_adapters.ovstage._stage_write import recorded_stage_writes

    renderer = _RecordingRenderer()
    renderer.version = native_version
    adapter = _interaction_adapter(ovstage_scene, renderer)
    stage = ovstage_scene._stage
    attr = "omni:selectionOutlineGroup"

    mark = int(stage.current_ordinal)
    adapter.set_selection_highlight([_PICKED_PATH])
    assert adapter._selection_outline_previous_paths == {_PICKED_PATH}
    assert adapter._selection_outline_reserved_writes == 1
    assert adapter._selection_outline_attribute_writes == 0
    assert "write_attribute" not in renderer.data_api_lookups
    assert 1 in renderer.styles
    assert renderer.reset_count == 1  # one-shot outline-pass activation
    writes = recorded_stage_writes(
        stage, since_ordinal=mark, current_ordinal=int(stage.current_ordinal)
    )
    assert writes.get(attr) == {_PICKED_PATH}

    mark = int(stage.current_ordinal)
    adapter.set_selection_highlight([])
    assert adapter._selection_outline_previous_paths == set()
    assert adapter._selection_outline_reserved_writes == 2
    assert renderer.reset_count == 1  # activation never re-fires on churn
    writes = recorded_stage_writes(
        stage, since_ordinal=mark, current_ordinal=int(stage.current_ordinal)
    )
    assert writes.get(attr) == {_PICKED_PATH}  # the committed clear write

    mark = int(stage.current_ordinal)
    adapter.set_selection_highlight([_NEIGHBOR_PATH, _PICKED_PATH])
    assert adapter._selection_outline_previous_paths == {
        _NEIGHBOR_PATH,
        _PICKED_PATH,
    }
    assert adapter._selection_outline_reserved_writes == 3
    assert adapter._selection_outline_attribute_writes == 0
    writes = recorded_stage_writes(
        stage, since_ordinal=mark, current_ordinal=int(stage.current_ordinal)
    )
    assert writes.get(attr) == {_NEIGHBOR_PATH, _PICKED_PATH}


def test_reserved_clear_never_creates_missing_prims(
    ovstage_scene: OvstageScene,
) -> None:
    """Stale clears for paths absent from the attached stage are vacuous.

    Reserved-attribute writes are UPSERTs; a clear retried after a scene
    transition (load_stage stale-retry semantics) must not ghost-create
    prims in the newly attached stage.  A missing path carries no
    membership here, so the clear succeeds without touching the stage.
    """
    missing = "/World/Hierarchy/GroupA/NeverExisted"
    renderer = _RecordingRenderer()
    adapter = _interaction_adapter(ovstage_scene, renderer)
    stage = ovstage_scene._stage
    adapter._selection_outline_previous_paths = {missing}

    adapter.set_selection_highlight([])

    assert adapter._selection_outline_previous_paths == set()
    assert adapter._selection_outline_reserved_writes == 0
    assert missing not in set(
        stage.get_child_paths("/World/Hierarchy/GroupA")
    )


def test_mixed_native_membership_reports_only_existing_and_converges_on_create(
    ovstage_scene: OvstageScene,
) -> None:
    """Partial native writes never promote a missing requested path.

    The missing member stays pending, becomes applied after the real native
    prim appears and the production refresh seam runs, and then clears without
    ghost creation.  This exercises the mixed-path failure shape
    against the real OVStage rather than a synthetic outline API.
    """
    from ovui_data_adapters.ovstage._stage_write import recorded_stage_writes

    existing = _PICKED_PATH
    missing = "/World/Hierarchy/GroupA/LaterCube"
    renderer = _RecordingRenderer()
    adapter = _interaction_adapter(ovstage_scene, renderer)
    stage = ovstage_scene._stage
    attr = "omni:selectionOutlineGroup"

    mark = int(stage.current_ordinal)
    adapter.set_selection_highlight([existing, missing])

    assert adapter._selected_paths == [existing, missing]
    assert adapter._selection_outline_previous_paths == {existing}
    assert adapter._selection_outline_last_write["pending_paths"] == [missing]
    writes = recorded_stage_writes(
        stage, since_ordinal=mark, current_ordinal=int(stage.current_ordinal)
    )
    assert writes.get(attr) == {existing}

    ordinal = int(stage.begin_frame())
    stage.create_prims(ordinal, [missing], "Cube")
    stage.end_frame(ordinal)
    before_generation = adapter._selection_outline_generation
    adapter.refresh_selection_highlight([existing, missing])

    assert adapter._selection_outline_previous_paths == {existing, missing}
    assert adapter._selection_outline_last_write["pending_paths"] == []
    assert adapter._selection_outline_generation == before_generation

    adapter.set_selection_highlight([])
    assert adapter._selected_paths == []
    assert adapter._selection_outline_previous_paths == set()
    assert adapter._selection_outline_last_write["pending_paths"] == []


def test_selection_highlight_degrades_honestly_without_any_transport(
    ovstage_scene: OvstageScene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Runtimes with NEITHER transport keep selection sync intact.

    No dedicated membership API, no owner copy-in write surface: no
    fallback into the renderer's data plane, no renderer reset, no crash,
    no membership claimed as applied; the global outline style stays
    configured.
    """
    renderer = _RecordingRenderer()
    adapter = _interaction_adapter(ovstage_scene, renderer)
    monkeypatch.setattr(
        renderer_module, "supports_native_stage_writes", lambda _stage: False
    )

    adapter.set_selection_highlight([_PICKED_PATH])
    adapter.set_selection_highlight([])

    assert 1 in renderer.styles
    assert "write_attribute" not in renderer.data_api_lookups
    assert renderer.reset_count == 0
    assert adapter._selection_outline_previous_paths == set()
    assert adapter._selection_outline_reserved_writes == 0


@pytest.mark.parametrize("native_version", [(0, 4, 0), "unknown", None])
def test_dedicated_outline_membership_resets_after_each_change(
    ovstage_scene: OvstageScene,
    native_version: Any,
) -> None:
    """A dedicated clear-A/set-B pair gets one reset after both writes.

    Older or unrecognized native OVRTX retains the reset workaround. The
    replacement must not reset between its clear and set operations, which
    would briefly publish an empty selection and leave the new set stale.
    """
    renderer = _OutlineRecordingRenderer()
    renderer.version = native_version
    adapter = _interaction_adapter(ovstage_scene, renderer)
    # A newer Python wrapper cannot promise behavior from an older binary.
    adapter._ovrtx_version = (0, 5, 373095)

    adapter.set_selection_highlight([_PICKED_PATH])
    adapter.set_selection_highlight([_NEIGHBOR_PATH])

    assert renderer.outline_writes == [
        ([_PICKED_PATH], 1),
        ([_PICKED_PATH], 0),
        ([_NEIGHBOR_PATH], 1),
    ]
    assert renderer.reset_count == 2


@pytest.mark.parametrize("transport", ["blocking", "async"])
@pytest.mark.parametrize("package_version", [(0, 5, 373095), (0, 4, 0), "unknown"])
def test_native_05_dedicated_selection_resets_only_for_activation(
    ovstage_scene: OvstageScene,
    transport: str,
    package_version: Any,
) -> None:
    """Modern native membership keeps its one-shot outline activation.

    Replacement, clear, and reselect deliver their exact membership writes
    without another reset. Repeating the current selection is a no-op.
    Native renderer version governs this even with older wrapper metadata.
    """
    renderer = (
        _OutlineRecordingRenderer()
        if transport == "blocking"
        else _AsyncOutlineRecordingRenderer()
    )
    renderer.version = (0, 5, 0)
    adapter = _interaction_adapter(ovstage_scene, renderer)
    adapter._ovrtx_version = package_version

    adapter.set_selection_highlight([_PICKED_PATH])
    assert renderer.reset_count == 1
    adapter.set_selection_highlight([_PICKED_PATH])
    adapter.set_selection_highlight([_NEIGHBOR_PATH])
    adapter.set_selection_highlight([])
    adapter.set_selection_highlight([])
    adapter.set_selection_highlight([_PICKED_PATH])

    assert adapter._selected_paths == [_PICKED_PATH]
    assert adapter._selection_outline_previous_paths == {_PICKED_PATH}
    assert renderer.outline_writes == [
        ([_PICKED_PATH], 1),
        ([_PICKED_PATH], 0),
        ([_NEIGHBOR_PATH], 1),
        ([_NEIGHBOR_PATH], 0),
        ([_PICKED_PATH], 1),
    ]
    assert 1 in renderer.styles
    assert renderer.reset_count == 1


def test_native_05_resolution_change_keeps_its_own_reset(
    ovstage_scene: OvstageScene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resize rearms activation only when no outline membership is applied."""
    monkeypatch.setattr(renderer_module, "StageWriteBatch", _RecordedBatch)
    renderer = _OutlineRecordingRenderer()
    renderer.version = (0, 5, 0)
    adapter = _interaction_adapter(ovstage_scene, renderer)
    adapter._ovrtx_version = (0, 5, 373095)

    adapter.set_selection_highlight([_PICKED_PATH])
    adapter.set_resolution(321, 123)
    adapter.set_selection_highlight([_PICKED_PATH])
    assert renderer.reset_count == 2  # activation plus selected resize

    adapter.set_selection_highlight([])
    adapter.set_resolution(322, 124)
    adapter.set_selection_highlight([])
    assert renderer.reset_count == 3  # empty resize, activation still owed
    assert adapter._selection_outline_pass_needs_reset is True
    adapter.set_selection_highlight([_NEIGHBOR_PATH])
    adapter.set_selection_highlight([_PICKED_PATH])
    assert renderer.reset_count == 4  # one activation after the empty resize
    assert adapter._selection_outline_previous_paths == {_PICKED_PATH}


@pytest.mark.parametrize(
    ("initial_paths", "fail_groups"),
    [
        ([], {}),
        (["/World/Hierarchy/GroupA/NeverExisted"], {}),
        ([_PICKED_PATH], {1: 1}),
    ],
)
def test_native_05_unapplied_selection_preserves_activation(
    ovstage_scene: OvstageScene,
    initial_paths: list[str],
    fail_groups: dict[int, int],
) -> None:
    """Empty, absent, or failed membership cannot satisfy pass activation."""
    renderer = _OutlineRecordingRenderer(fail_groups=fail_groups)
    renderer.version = (0, 5, 0)
    adapter = _interaction_adapter(ovstage_scene, renderer)

    adapter.set_selection_highlight(initial_paths)
    adapter.set_selection_highlight([])

    assert renderer.outline_writes == []
    assert renderer.reset_count == 0
    assert adapter._selection_outline_previous_paths == set()
    assert adapter._selection_outline_pass_needs_reset is True

    adapter.set_selection_highlight([_PICKED_PATH])

    assert renderer.outline_writes == [([_PICKED_PATH], 1)]
    assert renderer.reset_count == 1
    assert adapter._selection_outline_pass_needs_reset is False


def test_native_05_failed_activation_retries_without_rewriting_membership(
    ovstage_scene: OvstageScene,
) -> None:
    """An identical selection retries a failed reset, keeping applied membership."""
    renderer = _OutlineRecordingRenderer(reset_failures=1)
    renderer.version = (0, 5, 0)
    adapter = _interaction_adapter(ovstage_scene, renderer)

    adapter.set_selection_highlight([_PICKED_PATH])
    assert renderer.reset_count == 0
    assert adapter._selection_outline_previous_paths == {_PICKED_PATH}
    assert adapter._selection_outline_pass_needs_reset is True

    adapter.set_selection_highlight([_PICKED_PATH])

    assert renderer.outline_writes == [([_PICKED_PATH], 1)]
    assert renderer.reset_count == 1
    assert adapter._selection_outline_pass_needs_reset is False


def test_native_05_clear_after_failed_activation_keeps_reset_owed(
    ovstage_scene: OvstageScene,
) -> None:
    """Clearing failed activation cannot spend the reset on an empty outline."""
    renderer = _OutlineRecordingRenderer(reset_failures=1)
    renderer.version = (0, 5, 0)
    adapter = _interaction_adapter(ovstage_scene, renderer)

    adapter.set_selection_highlight([_PICKED_PATH])
    adapter.set_selection_highlight([])

    assert renderer.reset_count == 0
    assert adapter._selection_outline_previous_paths == set()
    assert adapter._selection_outline_pass_needs_reset is True

    adapter.set_selection_highlight([_NEIGHBOR_PATH])

    assert renderer.outline_writes == [
        ([_PICKED_PATH], 1),
        ([_PICKED_PATH], 0),
        ([_NEIGHBOR_PATH], 1),
    ]
    assert renderer.reset_count == 1
    assert adapter._selection_outline_pass_needs_reset is False


def test_resolution_resets_reactivate_only_without_applied_outline(
    ovstage_scene: OvstageScene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolution resets do not stack activation resets onto live outlines.

    With membership applied, a resolution change performs only its own
    reset; after a resolution reset with NO membership, the next selection
    performs exactly one activation reset.
    """
    monkeypatch.setattr(renderer_module, "StageWriteBatch", _RecordedBatch)
    renderer = _OutlineRecordingRenderer()
    adapter = _interaction_adapter(ovstage_scene, renderer)

    adapter.set_selection_highlight([_PICKED_PATH])    # activation reset (1)
    adapter.set_resolution(321, 123)                   # resolution reset (2)
    adapter.set_selection_highlight([_PICKED_PATH])    # no further reset
    assert renderer.reset_count == 2

    adapter.set_selection_highlight([])                # membership reset (3)
    adapter.set_resolution(322, 124)                   # resolution reset (4)
    adapter.set_selection_highlight([_NEIGHBOR_PATH])  # activation reset (5)
    adapter.set_selection_highlight([_PICKED_PATH])    # membership reset (6)
    assert renderer.reset_count == 6


def test_failed_activation_reset_is_retried_on_next_selection(
    ovstage_scene: OvstageScene,
) -> None:
    renderer = _OutlineRecordingRenderer(reset_failures=1)
    adapter = _interaction_adapter(ovstage_scene, renderer)

    adapter.set_selection_highlight([_PICKED_PATH])
    assert renderer.reset_count == 0  # the injected failure consumed the try

    adapter.set_selection_highlight([_PICKED_PATH, _NEIGHBOR_PATH])
    assert renderer.reset_count == 1  # retried and succeeded

    adapter.set_selection_highlight([_NEIGHBOR_PATH])
    assert renderer.reset_count == 2  # successful clear is rendered


@pytest.mark.parametrize(
    ("native_version", "expected_resets"), [((0, 4, 0), 2), ((0, 5, 0), 1)]
)
def test_failed_writes_are_reissued_by_the_next_selection_sync(
    ovstage_scene: OvstageScene,
    native_version: tuple[int, ...],
    expected_resets: int,
) -> None:
    """A failed set and a failed clear are each retried, never dropped."""
    renderer = _OutlineRecordingRenderer(fail_groups={1: 1})
    renderer.version = native_version
    adapter = _interaction_adapter(ovstage_scene, renderer)

    adapter.set_selection_highlight([_PICKED_PATH])    # set raises, no write
    assert renderer.outline_writes == []
    adapter.set_selection_highlight([_PICKED_PATH])    # retried set applies
    assert renderer.outline_writes == [([_PICKED_PATH], 1)]

    renderer._fail_groups[0] = 1
    adapter.set_selection_highlight([])                # clear raises
    assert renderer.outline_writes == [([_PICKED_PATH], 1)]
    adapter.set_selection_highlight([])                # retried clear applies
    assert renderer.outline_writes == [
        ([_PICKED_PATH], 1),
        ([_PICKED_PATH], 0),
    ]
    assert adapter._selection_outline_previous_paths == set()
    assert renderer.reset_count == expected_resets


@pytest.mark.parametrize(
    ("native_version", "expected_resets"), [((0, 4, 0), 2), ((0, 5, 0), 1)]
)
def test_async_only_transport_waits_each_operation_exactly_once(
    ovstage_scene: OvstageScene,
    native_version: tuple[int, ...],
    expected_resets: int,
) -> None:
    """The async fallback consumes completions in-call; a timeout-shaped
    ``None`` completion is not applied and the write is retried."""
    renderer = _AsyncOutlineRecordingRenderer()
    renderer.version = native_version
    adapter = _interaction_adapter(ovstage_scene, renderer)

    adapter.set_selection_highlight([_PICKED_PATH])
    assert renderer.outline_writes == [([_PICKED_PATH], 1)]

    renderer.wait_results.append(None)  # timeout-shaped completion
    adapter.set_selection_highlight([])
    assert renderer.outline_writes == [([_PICKED_PATH], 1)]

    adapter.set_selection_highlight([])  # retried clear applies
    assert renderer.outline_writes == [
        ([_PICKED_PATH], 1),
        ([_PICKED_PATH], 0),
    ]
    assert adapter._selection_outline_previous_paths == set()
    assert renderer.reset_count == expected_resets


def _transition_adapter(
    scene: OvstageScene, renderer: _RecordingRenderer
) -> OvstageRendererAdapter:
    """Interaction adapter with the extra state _remove_scene touches."""
    adapter = _interaction_adapter(scene, renderer)
    adapter._runtime_population = None
    adapter._runtime_reference_handle = None
    adapter._live_preview_policy_cache = {}
    return adapter


def test_failed_detach_restores_visible_outline_without_resync(
    ovstage_scene: OvstageScene,
) -> None:
    """The retained scene keeps its outline the moment the failure returns."""
    renderer = _OutlineRecordingRenderer(detach_failures=1)
    adapter = _transition_adapter(ovstage_scene, renderer)

    adapter.set_selection_highlight([_PICKED_PATH])
    with pytest.raises(RuntimeError, match="transient detach failure"):
        adapter._remove_scene()

    # Immediately after the exception — no selection resync in between —
    # the native membership was restored in-place.
    assert renderer.outline_writes == [
        ([_PICKED_PATH], 1),  # original selection
        ([_PICKED_PATH], 0),  # pre-detach clear
        ([_PICKED_PATH], 1),  # automatic restoration on detach failure
    ]

    # The retried transition then clears and detaches without leaking.
    adapter._remove_scene()
    assert renderer.detach_count == 1
    assert renderer.outline_writes[-1] == ([_PICKED_PATH], 0)


def test_clear_failure_never_leaks_into_a_later_scene(
    ovstage_scene: OvstageScene,
) -> None:
    """Stale renderer membership is retried until cleared, even across a
    failed detach, so same-named prims never inherit an outline."""
    renderer = _OutlineRecordingRenderer(fail_groups={0: 2}, detach_failures=1)
    adapter = _transition_adapter(ovstage_scene, renderer)

    adapter.set_selection_highlight([_PICKED_PATH])
    # First transition: the clear write fails AND the detach fails — the
    # outline stays visible in the renderer (no restoration write needed).
    with pytest.raises(RuntimeError, match="transient detach failure"):
        adapter._remove_scene()
    assert renderer.outline_writes == [([_PICKED_PATH], 1)]

    # Second transition: the clear write fails again but detach succeeds —
    # cleanup stays retryable without becoming current-generation membership.
    adapter._remove_scene()
    assert renderer.detach_count == 1
    assert renderer.outline_writes == [([_PICKED_PATH], 1)]
    assert adapter._selection_outline_previous_paths == set()
    assert adapter._selection_outline_stale_paths == {_PICKED_PATH}
    assert adapter._selection_outline_last_write["applied_paths"] == []
    assert adapter._selection_outline_last_write["pending_paths"] == [_PICKED_PATH]

    # The next selection sync re-issues the clear so the stale outline
    # cannot appear on a later same-named scene.
    adapter.set_selection_highlight([])
    assert renderer.outline_writes[-1] == ([_PICKED_PATH], 0)
    assert adapter._selection_outline_stale_paths == set()


def test_replacement_generation_recovers_failed_clear_exactly_once(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
) -> None:
    """Old-generation cleanup cannot claim or starve replacement membership.

    This follows the production adapter through two real
    native OVStage sessions.  Clear transport fails across detach and attach;
    after recovery the renderer receives the selected membership exactly once
    and a stable refresh performs no additional native write.
    """
    session1 = create_provider_session(runtime=ovstage_runtime)
    scene1 = session1.open_stage(str(ovstage_static_scene_path))
    adapter = OvstageRendererAdapter(scene1)
    adapter.load_stage(scene1)
    renderer = adapter._renderer
    native_group_setter = renderer.set_selection_outline_group_strings
    native_outline_writes: list[tuple[list[str], int]] = []

    def record_outline_write(paths: list[str], group_id: int) -> None:
        native_group_setter(paths, group_id)
        native_outline_writes.append((list(paths), int(group_id)))

    renderer.set_selection_outline_group_strings = record_outline_write
    adapter.set_selection_highlight([_PICKED_PATH])
    assert native_outline_writes == [([_PICKED_PATH], 1)]
    original_write = adapter._write_selection_outline_group

    def fail_clear(paths: list[str], group_id: int) -> set[str]:
        if int(group_id) == 0:
            return set()
        return original_write(paths, group_id)

    adapter._write_selection_outline_group = fail_clear  # type: ignore[method-assign]
    adapter._remove_scene()
    assert adapter._selection_outline_previous_paths == set()
    assert adapter._selection_outline_stale_paths == {_PICKED_PATH}
    assert adapter._selection_outline_last_write["applied_paths"] == []
    assert adapter._selection_outline_last_write["pending_paths"] == [_PICKED_PATH]
    session1.shutdown_scene()

    session2 = create_provider_session(runtime=ovstage_runtime)
    scene2 = session2.open_stage(str(ovstage_static_scene_path))
    try:
        adapter.load_stage(scene2)
        assert adapter._selection_outline_previous_paths == set()
        assert adapter._selection_outline_stale_paths == {_PICKED_PATH}
        assert adapter._selection_outline_last_write["applied_paths"] == []
        assert adapter._selection_outline_last_write["pending_paths"] == [
            _PICKED_PATH
        ]
        assert native_outline_writes == [([_PICKED_PATH], 1)]

        adapter._write_selection_outline_group = original_write  # type: ignore[method-assign]
        adapter.refresh_selection_highlight([_PICKED_PATH])
        assert native_outline_writes == [
            ([_PICKED_PATH], 1),
            ([_PICKED_PATH], 1),
        ]
        assert adapter._selection_outline_previous_paths == {_PICKED_PATH}
        assert adapter._selection_outline_stale_paths == set()
        assert adapter._selection_outline_last_write["applied_paths"] == [
            _PICKED_PATH
        ]
        assert adapter._selection_outline_last_write["pending_paths"] == []

        adapter.refresh_selection_highlight([_PICKED_PATH])
        assert native_outline_writes == [
            ([_PICKED_PATH], 1),
            ([_PICKED_PATH], 1),
        ]
    finally:
        adapter.shutdown()
        session2.shutdown_scene()


def test_first_step_puts_the_runtime_outline_anchor_in_the_hidden_group(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
) -> None:
    """The runtime layer's mesh with no area goes into the hidden group after the first step.

    ovrtx draws new outlines on an image that it no longer refines only
    while a prim that is not hidden is in an outline group. The renderer gets
    the attached prims at its first step and drops membership written before
    it. With the anchor in place, the first selection needs no reset.
    """
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    adapter = OvstageRendererAdapter(scene)
    renderer = adapter._renderer
    native_group_setter = renderer.set_selection_outline_group_strings
    native_reset = renderer.reset
    writes: list[tuple[list[str], int]] = []
    resets: list[int] = []

    def record_outline_write(paths: list[str], group_id: int) -> None:
        native_group_setter(paths, group_id)
        writes.append((list(paths), int(group_id)))

    def record_reset() -> None:
        resets.append(1)
        native_reset()

    renderer.set_selection_outline_group_strings = record_outline_write
    renderer.reset = record_reset
    try:
        adapter.load_stage(scene)
        assert writes == []

        adapter.render_frame(64, 32, None, None)
        anchor = f"{adapter.runtime_root_path}/Render/OutlineAnchor"
        assert writes == [([anchor], 2)]
        adapter.render_frame(64, 32, None, None)
        assert writes == [([anchor], 2)]
        resets.clear()  # The first frame's resolution change resets, as on main.

        adapter.set_selection_highlight([_PICKED_PATH])

        assert writes == [([anchor], 2), ([_PICKED_PATH], 1)]
        assert resets == []
    finally:
        adapter.shutdown()
        session.shutdown_scene()


@pytest.mark.parametrize("failures", [1, 3])
def test_failed_runtime_outline_anchor_write_is_reported_and_tried_again(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
    capsys: pytest.CaptureFixture[str],
    failures: int,
) -> None:
    """A failed anchor write is reported with its cause and tried at the next step.

    After three failed steps the adapter stops trying for this scene and says
    so; the first selection then resets the renderer, as on main.
    """
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    adapter = OvstageRendererAdapter(scene)
    renderer = adapter._renderer
    native_group_setter = renderer.set_selection_outline_group_strings
    writes: list[tuple[list[str], int]] = []
    remaining = [failures]

    def flaky_outline_write(paths: list[str], group_id: int) -> None:
        if remaining[0]:
            remaining[0] -= 1
            raise RuntimeError("injected anchor failure")
        native_group_setter(paths, group_id)
        writes.append((list(paths), int(group_id)))

    renderer.set_selection_outline_group_strings = flaky_outline_write
    try:
        adapter.load_stage(scene)
        capsys.readouterr()
        anchor = f"{adapter.runtime_root_path}/Render/OutlineAnchor"

        adapter.render_frame(64, 32, None, None)

        err = capsys.readouterr().err
        assert f"selection outline anchor write failed (attempt 1 of 3, {anchor})" in err
        assert "RuntimeError: injected anchor failure" in err
        assert adapter._selection_outline_anchor_applied is False

        adapter.render_frame(64, 32, None, None)
        adapter.render_frame(64, 32, None, None)
        adapter.render_frame(64, 32, None, None)

        err = capsys.readouterr().err
        if failures == 1:
            assert err.count("selection outline anchor write failed") == 0
            assert writes == [([anchor], 2)]
            assert adapter._selection_outline_anchor_applied is True
            assert adapter._selection_outline_pass_needs_reset is False
        else:
            assert "attempt 3 of 3" in err
            assert "no more attempts for this scene" in err
            assert writes == []
            assert adapter._selection_outline_anchor_applied is False
            assert adapter._selection_outline_pass_needs_reset is True
    finally:
        adapter.shutdown()
        session.shutdown_scene()


def test_failed_outline_style_setup_keeps_no_step_outputs_alive(
    ovstage_static_scene_path: pathlib.Path,
    ovstage_runtime: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The saved cause of a failed style setup does not keep step outputs alive.

    An exception keeps its traceback, and with it the frames of
    ``render_frame`` and their step outputs. After the retry succeeds and the
    retained output is released, no step output may stay alive.
    """
    import gc

    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    adapter = OvstageRendererAdapter(scene)
    renderer = adapter._renderer
    native_styles = renderer.set_selection_group_styles
    failed = [False]

    def flaky_styles(styles: Any) -> None:
        if not failed[0]:
            failed[0] = True
            raise RuntimeError("injected style failure")
        native_styles(styles)

    renderer.set_selection_group_styles = flaky_styles
    try:
        adapter.load_stage(scene)
        adapter._selection_outline_styles_configured = False
        adapter.render_frame(64, 32, None, None)
        assert "injected style failure" in capsys.readouterr().err
        adapter.render_frame(64, 32, None, None)
        assert adapter._selection_outline_anchor_applied is True

        adapter._release_retained_output()
        gc.collect()

        alive = [o for o in gc.get_objects() if type(o).__name__ == "RenderProductSetOutputs"]
        assert alive == []
    finally:
        adapter.shutdown()
        session.shutdown_scene()


class _RecordedBatch:
    def __init__(self, stage: Any, paths: list[str]) -> None:
        self.stage = stage
        self.paths = list(paths)
        self.writes: list[tuple[str, np.ndarray, int, Any]] = []
        self.token_writes: list[tuple[str, tuple[str, ...]]] = []

    def __enter__(self) -> "_RecordedBatch":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def write_fixed(
        self,
        attribute_name: str,
        values: Any,
        *,
        lanes: int = 1,
        semantic: Any = 0,
    ) -> None:
        self.writes.append(
            (
                str(attribute_name),
                np.asarray(values).copy().reshape(-1),
                int(lanes),
                semantic,
            )
        )

    def write_tokens(self, attribute_name: str, values: Any) -> None:
        self.token_writes.append(
            (str(attribute_name), tuple(str(value) for value in values))
        )


class _FakeDevice:
    CPU = "cpu"


class _FakeSelectionGroupStyle:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = dict(kwargs)


class _FakeOvrtx:
    Device = _FakeDevice
    SelectionGroupStyle = _FakeSelectionGroupStyle
    OVRTX_RENDER_VAR_PICK_HIT = "ovrtx_pick_hit"
    OVRTX_PICK_HIT_MAGIC = 0x56505448
    OVRTX_PICK_HIT_VERSION = 1


class _FakeMapping:
    def __init__(
        self,
        paths: list[str],
        positions: list[tuple[float, float, float]] | None = None,
    ) -> None:
        self._path_ids = np.arange(1, len(paths) + 1, dtype=np.uint64)
        self._positions = np.array(
            positions or [(1.0, 2.0, 3.0)] * len(paths),
            dtype=np.float64,
        )
        self.params = {
            "magic": np.array([_FakeOvrtx.OVRTX_PICK_HIT_MAGIC], dtype=np.uint32),
            "version": np.array([_FakeOvrtx.OVRTX_PICK_HIT_VERSION], dtype=np.uint32),
            "hitCount": np.array([len(paths)], dtype=np.uint32),
        }

    def __enter__(self) -> "_FakeMapping":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def keys(self) -> tuple[str, str]:
        return ("primPath", "worldPositionM")

    def __getitem__(self, key: str) -> np.ndarray:
        if key == "primPath":
            return self._path_ids
        if key == "worldPositionM":
            return self._positions
        raise KeyError(key)


class _FakeExplicitMapping(_FakeMapping):
    def __init__(
        self,
        paths: list[str],
        positions: list[tuple[float, float, float]] | None = None,
    ) -> None:
        super().__init__(paths, positions)
        self.unmapped = False

    def keys(self) -> tuple[str, str]:
        raise AttributeError("real OVRTX explicit mappings are index-addressed")

    def unmap(self) -> None:
        self.unmapped = True


class _FakePickRenderVar:
    def __init__(
        self,
        paths: list[str],
        positions: list[tuple[float, float, float]] | None = None,
    ) -> None:
        self._paths = list(paths)
        self._positions = list(positions or [(1.0, 2.0, 3.0)] * len(paths))

    def map(self, **_kwargs: Any) -> _FakeMapping:
        return _FakeMapping(self._paths, self._positions)


class _FakeExplicitPickRenderVar:
    def __init__(
        self,
        paths: list[str],
        positions: list[tuple[float, float, float]] | None = None,
    ) -> None:
        self._paths = list(paths)
        self._positions = list(positions or [(1.0, 2.0, 3.0)] * len(paths))
        self.mapping: _FakeExplicitMapping | None = None

    def map(self, **_kwargs: Any) -> _FakeExplicitMapping:
        self.mapping = _FakeExplicitMapping(self._paths, self._positions)
        return self.mapping


class _FakeFrame:
    def __init__(
        self,
        paths: list[str],
        positions: list[tuple[float, float, float]] | None = None,
    ) -> None:
        self.render_vars = {"ovrtx_pick_hit": _FakePickRenderVar(paths, positions)}


class _FakeFrameWithRenderVar:
    def __init__(self, render_var: Any) -> None:
        self.render_vars = {"ovrtx_pick_hit": render_var}


class _FakeProduct:
    def __init__(
        self,
        paths: list[str],
        positions: list[tuple[float, float, float]] | None = None,
    ) -> None:
        self.frames = [_FakeFrame(paths, positions)]


class _FakeProductWithRenderVar:
    def __init__(self, render_var: Any) -> None:
        self.frames = [_FakeFrameWithRenderVar(render_var)]


class _RecordingRenderer:
    _DATA_APIS = frozenset(
        {
            "add_usd",
            "add_usd_reference_from_string",
            "query_prims",
            "read_attribute",
            "remove_usd",
            "reset_stage",
            "resolve_prim_path_id",
            "step",
            "update_from_stage",
            "write_attribute",
        }
    )

    def __init__(self) -> None:
        self.version = (0, 4, 0)
        self.pick_queries: list[tuple[str, float, float, float, float]] = []
        self.next_pick_path: str | None = None
        self.next_pick_paths: list[str] = []
        self.next_pick_hits: list[tuple[str, tuple[float, float, float]]] = []
        self.styles: dict[int, Any] = {}
        self.reset_count = 0
        self.step_ordinals: list[int] = []
        self.data_api_lookups: list[str] = []

    def reset(self) -> None:
        self.reset_count += 1

    def enqueue_pick_query(
        self,
        render_product_path: str,
        left_ndc: float,
        top_ndc: float,
        right_ndc: float,
        bottom_ndc: float,
    ) -> None:
        self.pick_queries.append(
            (render_product_path, left_ndc, top_ndc, right_ndc, bottom_ndc)
        )

    def step(self, **kwargs: Any) -> dict[str, _FakeProduct]:
        self.step_ordinals.append(int(kwargs["ordinal"]))
        return {
            _RENDER_PRODUCT_LOCAL_PATH: _FakeProduct(
                self._current_pick_paths(),
                self._current_pick_positions(),
            )
        }

    def set_selection_group_styles(self, styles: dict[int, Any]) -> None:
        self.styles.update(styles)

    def _current_pick_paths(self) -> list[str]:
        if self.next_pick_hits:
            return [path for path, _position in self.next_pick_hits]
        if self.next_pick_paths:
            return list(self.next_pick_paths)
        return [self.next_pick_path] if self.next_pick_path else []

    def _current_pick_positions(self) -> list[tuple[float, float, float]]:
        if self.next_pick_hits:
            return [position for _path, position in self.next_pick_hits]
        return [(1.0, 2.0, 3.0)] * len(self._current_pick_paths())

    def __getattr__(self, name: str) -> Any:
        if name in self._DATA_APIS:
            self.data_api_lookups.append(name)
        raise AttributeError(name)


class _OutlineRecordingRenderer(_RecordingRenderer):
    """Recording renderer with the dedicated blocking membership setter.

    Models a runtime that EXPOSES ``set_selection_outline_group_strings``.
    The installed ovrtx 0.4.0 wheel exposes neither string variant — its
    real transport (the reserved ``omni:selectionOutlineGroup`` attribute
    through the OVStage owner API) is covered by
    ``test_selection_highlight_reserved_attribute_transport_on_installed_runtime``;
    these fakes verify the precedence and retry bookkeeping the adapter
    must keep for runtimes that do ship the dedicated APIs.

    ``fail_groups`` maps a group id to the number of times a write for that
    group raises before succeeding. ``reset_failures`` makes that many
    ``reset()`` calls raise (after counting the attempt like the base).
    ``detach_failures`` makes that many ``detach_ovstage()`` calls raise.
    """

    def __init__(
        self,
        *,
        fail_groups: dict[int, int] | None = None,
        reset_failures: int = 0,
        detach_failures: int = 0,
    ) -> None:
        super().__init__()
        self.outline_writes: list[tuple[list[str], int]] = []
        self.detach_count = 0
        self._fail_groups = dict(fail_groups or {})
        self._reset_failures = int(reset_failures)
        self._detach_failures = int(detach_failures)

    def set_selection_outline_group_strings(
        self, prim_paths: list[str], group_ids: int
    ) -> None:
        group = int(group_ids)
        remaining = self._fail_groups.get(group, 0)
        if remaining > 0:
            self._fail_groups[group] = remaining - 1
            raise RuntimeError(f"transient outline write failure (group {group})")
        self.outline_writes.append((list(prim_paths), group))

    def reset(self) -> None:
        if self._reset_failures > 0:
            self._reset_failures -= 1
            raise RuntimeError("transient reset failure")
        super().reset()

    def detach_ovstage(self) -> None:
        if self._detach_failures > 0:
            self._detach_failures -= 1
            raise RuntimeError("transient detach failure")
        self.detach_count += 1


class _FakeOutlineOperation:
    def __init__(self, result: Any) -> None:
        self._result = result

    def wait(self, timeout: Any = None) -> Any:
        return self._result


class _AsyncOutlineRecordingRenderer(_RecordingRenderer):
    """Recording renderer exposing ONLY the async membership setter.

    A write only lands in ``outline_writes`` when its operation completes
    successfully, so a retry after a timeout-shaped completion is visible
    purely in the final call sequence.
    """

    def __init__(self) -> None:
        super().__init__()
        self.outline_writes: list[tuple[list[str], int]] = []
        self.wait_results: list[Any] = []

    def set_selection_outline_group_strings_async(
        self, prim_paths: list[str], group_ids: int
    ) -> _FakeOutlineOperation:
        result = self.wait_results.pop(0) if self.wait_results else True
        if result is not None:
            self.outline_writes.append((list(prim_paths), int(group_ids)))
        return _FakeOutlineOperation(result)


class _RectSensitiveRenderer(_RecordingRenderer):
    def __init__(
        self,
        *,
        hit_path: str,
        hit_position: tuple[float, float, float],
        hit_pixel: tuple[int, int],
        resolution: tuple[int, int],
    ) -> None:
        super().__init__()
        self.hit_path = hit_path
        self.hit_position = hit_position
        self.hit_pixel = hit_pixel
        self.resolution = resolution

    def _current_pick_paths(self) -> list[str]:
        return [self.hit_path] if self._last_query_contains_hit_pixel() else []

    def _current_pick_positions(self) -> list[tuple[float, float, float]]:
        return [self.hit_position] if self._last_query_contains_hit_pixel() else []

    def _last_query_contains_hit_pixel(self) -> bool:
        if not self.pick_queries:
            return False
        _path, left, top, right, bottom = self.pick_queries[-1]
        width, height = self.resolution
        x = self.hit_pixel[0] / float(max(1, width))
        y = self.hit_pixel[1] / float(max(1, height))
        return left <= x < right and top <= y < bottom


class _FakePathDictionary:
    def __init__(self, renderer: _RecordingRenderer) -> None:
        self._renderer = renderer
        self.resolved_ids: list[int] = []

    def path_to_string(self, path_id: int) -> str:
        self.resolved_ids.append(int(path_id))
        paths = self._renderer._current_pick_paths()
        index = int(path_id) - 1
        return str(paths[index]) if 0 <= index < len(paths) else ""


def _interaction_adapter(
    scene: OvstageScene,
    renderer: _RecordingRenderer,
) -> OvstageRendererAdapter:
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._scene = scene
    adapter._ovrtx = _FakeOvrtx
    adapter._ovrtx_version = (0, 4, 0)
    adapter._renderer = renderer
    adapter._attached_stage = scene._stage
    adapter._path_dictionary = _FakePathDictionary(renderer)
    adapter._gpu_device_name = "test gpu"
    adapter._logged_first_step = True
    adapter._render_product_path = _RENDER_PRODUCT_LOCAL_PATH
    adapter._runtime_root_path = "/_OvuiRuntime"
    adapter._runtime_camera_local_path = _RENDER_CAMERA_LOCAL_PATH
    adapter._runtime_render_product_path = _RENDER_PRODUCT_LOCAL_PATH
    adapter._default_render_product_path = adapter._render_product_path
    adapter._active_render_product_common_path = None
    adapter._camera_path = _RENDER_CAMERA_LOCAL_PATH
    adapter._active_camera_common_path = None
    adapter._render_worker_thread = None
    adapter._render_flow_mode = "nativePacing"
    adapter._secondary_viewport_active = False
    adapter._last_resolution = (64, 32)
    adapter._last_render_product_resolution = (64, 32)
    adapter._dt_clock = time.perf_counter()
    adapter._last_load_from_scene_context = False
    adapter._borrow_step_count = 0
    adapter._selected_paths = []
    adapter._selection_outline_previous_paths = set()
    adapter._selection_outline_stale_paths = set()
    adapter._selection_outline_styles_configured = False
    adapter._selection_outline_style_calls = 0
    adapter._selection_outline_attribute_writes = 0
    adapter._selection_outline_reserved_writes = 0
    adapter._selection_outline_generation = 1
    adapter._selection_outline_last_write = {}
    adapter._selection_outline_membership_reset_pending = False
    adapter._selection_outline_pass_needs_reset = True
    adapter._in_flight_pick_queries = deque()
    adapter._pick_seq = 0
    adapter._pick_enqueue_count = 0
    adapter._pick_result_count = 0
    adapter._last_pick_pixel_rect = None
    adapter._last_pick_path = None
    adapter._last_pick_world_point = None
    adapter._last_view_matrix = None
    adapter._last_proj_matrix = None
    adapter._last_pushed_camera_state = None
    adapter._extract_ldr_color = (  # type: ignore[method-assign]
        lambda _products, width, height: np.zeros((height, width, 4), dtype=np.uint8)
    )
    return adapter


def test_globally_owned_render_setting_reaches_only_the_owner_prim(
    ovstage_scene: OvstageScene,
) -> None:
    """A RenderSettings-owned value lands on the owner prim, nowhere else.

    Setup installs a two-entry renderer schema (the schema is injectable by
    design), then the REAL public apply/reset run against a real BORROW
    attachment.  The assertions are about WHERE the value went and whether
    the reset restored the effective default, read back from the native
    OVStage store — not about catalog contents.
    """

    from ovui_data_adapters.ovstage.renderer_adapter import (
        _render_setting_exact_native_records,
        configure_render_settings_schema,
    )
    from ovui_data_adapters.ovstage.stage_adapter import is_user_facing_scene_path

    attr_name = "omni:rtx:pt:multigpu:enabled"
    previous = (
        renderer_module._RENDER_SETTINGS_PROVIDER_ID,
        renderer_module._RENDER_SETTINGS_PROVIDER_LABEL,
        renderer_module._RENDER_SETTINGS_PUBLIC_NAMESPACES,
        renderer_module._RENDER_SETTINGS_GROUP_FALLBACK,
        renderer_module._RENDER_SETTINGS_GROUP_LABEL_FALLBACK,
        renderer_module._RENDER_SETTINGS_BUILTIN_SPECS,
    )
    configure_render_settings_schema(
        provider_id="test",
        provider_label="Test",
        public_namespaces=("omni:rtx:",),
        group_fallback="test",
        group_label_fallback="Test",
        builtin_specs=(
            {
                "attr_name": attr_name,
                "usd_type": "bool",
                "default": True,
                "label": "Enabled",
                "owner_scope": "RenderSettings",
            },
        ),
    )
    adapter = OvstageRendererAdapter(ovstage_scene)
    try:
        adapter.load_stage(ovstage_scene)
        stage = ovstage_scene._stage
        owner_path = adapter._runtime_render_settings_local_path
        product_path = adapter.get_active_render_product_path()
        camera_path = adapter._runtime_camera_local_path
        assert owner_path, "the global RenderSettings owner prim was not provided"

        def value_at(path: str) -> Any:
            records = _render_setting_exact_native_records(
                stage, path, (attr_name,)
            )
            record = records.get(attr_name)
            return None if record is None else record.value

        applied = adapter.apply_render_setting(
            f"{product_path}:{attr_name}", False
        )
        assert applied.accepted, applied.message
        assert value_at(owner_path) is False, (
            "the globally owned setting never reached OVRTX's owner prim"
        )
        assert value_at(product_path) is None
        assert value_at(camera_path) is None
        assert is_user_facing_scene_path(owner_path, ovstage_scene, stage) is False

        was_reset = adapter.reset_render_setting(f"{product_path}:{attr_name}")
        assert was_reset.accepted, was_reset.message
        assert value_at(owner_path) is None, (
            "reset left the authored value in the native store"
        )
        assert value_at(product_path) is None
    finally:
        adapter.shutdown()
        configure_render_settings_schema(
            provider_id=previous[0],
            provider_label=previous[1],
            public_namespaces=previous[2],
            group_fallback=previous[3],
            group_label_fallback=previous[4],
            builtin_specs=previous[5],
        )


def test_single_setting_read_reports_what_the_catalog_reports(
    ovstage_scene: OvstageScene,
) -> None:
    """One value read must agree with the catalog it stands in for."""

    from ovui_data_adapters.ovstage.renderer_adapter import (
        configure_render_settings_schema,
    )

    camera_attr = "omni:rtx:post:histogram:whiteScale"
    product_attr = "omni:rtx:probe:productOwned"
    global_attr = "omni:rtx:pt:multigpu:enabled"
    previous = (
        renderer_module._RENDER_SETTINGS_PROVIDER_ID,
        renderer_module._RENDER_SETTINGS_PROVIDER_LABEL,
        renderer_module._RENDER_SETTINGS_PUBLIC_NAMESPACES,
        renderer_module._RENDER_SETTINGS_GROUP_FALLBACK,
        renderer_module._RENDER_SETTINGS_GROUP_LABEL_FALLBACK,
        renderer_module._RENDER_SETTINGS_BUILTIN_SPECS,
    )
    configure_render_settings_schema(
        provider_id="test",
        provider_label="Test",
        public_namespaces=("omni:rtx:",),
        group_fallback="test",
        group_label_fallback="Test",
        builtin_specs=(
            {
                "attr_name": camera_attr,
                "usd_type": "float",
                "owner_scope": "Camera",
                "default": 1.5,
                "label": "Camera Owned",
            },
            {
                "attr_name": product_attr,
                "usd_type": "uint",
                "owner_scope": "RenderProduct",
                "default": 2,
                "label": "Product Owned",
            },
            {
                "attr_name": global_attr,
                "usd_type": "bool",
                "owner_scope": "RenderSettings",
                "default": True,
                "label": "Globally Owned",
            },
        ),
    )
    adapter = OvstageRendererAdapter(ovstage_scene)
    try:
        adapter.load_stage(ovstage_scene)
        product_path = adapter.get_active_render_product_path()

        def catalog_agrees(phase: str) -> None:
            for row in adapter.list_render_settings(product_path).settings:
                attr_name = str(row.metadata.get("attr_name") or "")
                assert adapter.read_render_setting_value(
                    attr_name,
                    render_product_path=product_path,
                ) == row.value_state.current_value, (
                    f"{phase}: single read disagrees with the catalog "
                    f"for {attr_name}"
                )

        catalog_agrees("unauthored")
        for attr_name, value in (
            (camera_attr, 9.25),
            (product_attr, 6),
            (global_attr, False),
        ):
            applied = adapter.apply_render_setting(
                f"{product_path}:{attr_name}",
                value,
            )
            assert applied.accepted, applied.message
            assert adapter.read_render_setting_value(
                attr_name,
                render_product_path=product_path,
            ) == value
        catalog_agrees("authored")

        for attr_name in (camera_attr, product_attr, global_attr):
            was_reset = adapter.reset_render_setting(
                f"{product_path}:{attr_name}"
            )
            assert was_reset.accepted, was_reset.message
        catalog_agrees("reset")

        assert adapter.read_render_setting_value(
            "omni:rtx:probe:absent",
            render_product_path=product_path,
        ) is None
    finally:
        adapter.shutdown()
        configure_render_settings_schema(
            provider_id=previous[0],
            provider_label=previous[1],
            public_namespaces=previous[2],
            group_fallback=previous[3],
            group_label_fallback=previous[4],
            builtin_specs=previous[5],
        )


def test_non_builtin_public_setting_keeps_its_native_scalar_type(
    ovstage_scene: OvstageScene,
) -> None:
    from ovui_data_adapters.common import RenderSettingValueType
    from ovui_data_adapters.ovstage.renderer_adapter import (
        _render_setting_record_descriptor,
        configure_render_settings_schema,
    )

    previous = (
        renderer_module._RENDER_SETTINGS_PROVIDER_ID,
        renderer_module._RENDER_SETTINGS_PROVIDER_LABEL,
        renderer_module._RENDER_SETTINGS_PUBLIC_NAMESPACES,
        renderer_module._RENDER_SETTINGS_GROUP_FALLBACK,
        renderer_module._RENDER_SETTINGS_GROUP_LABEL_FALLBACK,
        renderer_module._RENDER_SETTINGS_BUILTIN_SPECS,
    )
    configure_render_settings_schema(
        provider_id="test",
        provider_label="Test",
        public_namespaces=("exposure",),
        group_fallback="test",
        group_label_fallback="Test",
        builtin_specs=(),
    )
    adapter = _interaction_adapter(ovstage_scene, _RecordingRenderer())
    try:
        native = adapter._render_settings_native_adapter(_CAMERA_PATH)
        assert native is not None
        record = native._attribute_records["exposure"]

        descriptor = _render_setting_record_descriptor(
            _CAMERA_PATH,
            record,
            native.get_value("exposure"),
        )

        assert descriptor is not None
        assert descriptor.value_type is RenderSettingValueType.FLOAT
        assert descriptor.enabled is True
        assert descriptor.value_state.current_value == pytest.approx(0.0)
    finally:
        configure_render_settings_schema(
            provider_id=previous[0],
            provider_label=previous[1],
            public_namespaces=previous[2],
            group_fallback=previous[3],
            group_label_fallback=previous[4],
            builtin_specs=previous[5],
        )


def test_render_setting_owner_view_never_builds_the_full_stage_property_catalog(
    ovstage_scene: OvstageScene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reading one runtime setting stays scoped to its owner prim."""

    from ovui_data_adapters.ovstage.property_adapter import (
        _NativeOvstagePropertyAdapter,
    )
    from ovui_data_adapters.ovstage.renderer_adapter import (
        configure_render_settings_schema,
    )

    attr_name = "focalLength"
    previous = (
        renderer_module._RENDER_SETTINGS_PROVIDER_ID,
        renderer_module._RENDER_SETTINGS_PROVIDER_LABEL,
        renderer_module._RENDER_SETTINGS_PUBLIC_NAMESPACES,
        renderer_module._RENDER_SETTINGS_GROUP_FALLBACK,
        renderer_module._RENDER_SETTINGS_GROUP_LABEL_FALLBACK,
        renderer_module._RENDER_SETTINGS_BUILTIN_SPECS,
    )
    configure_render_settings_schema(
        provider_id="test",
        provider_label="Test",
        public_namespaces=("focal",),
        group_fallback="test",
        group_label_fallback="Test",
        builtin_specs=(
            {
                "attr_name": attr_name,
                "usd_type": "float",
                "default": 50.0,
                "label": "Focal Length",
            },
        ),
    )
    adapter = _interaction_adapter(ovstage_scene, _RecordingRenderer())
    try:
        def reject_full_catalog(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError(
                "one render-setting read attempted a full-stage property catalog"
            )

        monkeypatch.setattr(
            _NativeOvstagePropertyAdapter,
            "_copy_path_descriptors",
            staticmethod(reject_full_catalog),
        )

        native = adapter._render_settings_native_adapter(_CAMERA_PATH)

        assert native is not None
        assert attr_name in adapter._render_settings_records(native)
        assert native.get_value(attr_name) == pytest.approx(35.0)
    finally:
        configure_render_settings_schema(
            provider_id=previous[0],
            provider_label=previous[1],
            public_namespaces=previous[2],
            group_fallback=previous[3],
            group_label_fallback=previous[4],
            builtin_specs=previous[5],
        )
