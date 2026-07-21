# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OVStage BORROW camera, pick, render-product, and highlight behavior."""

from __future__ import annotations

import pathlib
import time
from collections import deque
from typing import Any, Iterator

import numpy as np
import pytest

from ovui_data_adapters.ovstage._scene import OvstageScene
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage import renderer_adapter as renderer_module
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
    camera_batch = batches[0]
    assert camera_batch.stage is ovstage_scene._stage
    assert camera_batch.paths == [_RENDER_CAMERA_LOCAL_PATH]
    assert camera_batch.writes[0][0] == "omni:xform"
    assert camera_batch.writes[0][2] == 16
    assert renderer.step_ordinals == [int(ovstage_scene.current_ordinal)]
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


def test_selection_highlight_degrades_honestly_without_outline_api(
    ovstage_scene: OvstageScene,
) -> None:
    """Runtimes without the membership API keep selection sync intact.

    No fallback into the owner's data plane, no renderer reset, no crash;
    the global outline style stays configured.
    """
    renderer = _RecordingRenderer()
    adapter = _interaction_adapter(ovstage_scene, renderer)

    adapter.set_selection_highlight([_PICKED_PATH])
    adapter.set_selection_highlight([])

    assert 1 in renderer.styles
    assert "write_attribute" not in renderer.data_api_lookups
    assert renderer.reset_count == 0


def test_outline_lifecycle_set_move_clear_with_single_activation(
    ovstage_scene: OvstageScene,
) -> None:
    """Set/move/clear membership writes with exactly one activation reset.

    The outline pass is activated by one renderer reset on the first
    applied membership and never again during selection churn.
    """
    renderer = _OutlineRecordingRenderer()
    adapter = _interaction_adapter(ovstage_scene, renderer)

    adapter.set_selection_highlight([_PICKED_PATH])
    adapter.set_selection_highlight([_NEIGHBOR_PATH])
    adapter.set_selection_highlight([])
    adapter.set_selection_highlight([_PICKED_PATH])

    assert renderer.outline_writes == [
        ([_PICKED_PATH], 1),
        ([_PICKED_PATH], 0),
        ([_NEIGHBOR_PATH], 1),
        ([_NEIGHBOR_PATH], 0),
        ([_PICKED_PATH], 1),
    ]
    assert renderer.reset_count == 1


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

    adapter.set_selection_highlight([])                # outline cleared
    adapter.set_resolution(322, 124)                   # resolution reset (3)
    adapter.set_selection_highlight([_NEIGHBOR_PATH])  # activation reset (4)
    adapter.set_selection_highlight([_PICKED_PATH])    # no further reset
    assert renderer.reset_count == 4


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
    assert renderer.reset_count == 1  # activated; never reset again


def test_failed_writes_are_reissued_by_the_next_selection_sync(
    ovstage_scene: OvstageScene,
) -> None:
    """A failed set and a failed clear are each retried, never dropped."""
    renderer = _OutlineRecordingRenderer(fail_groups={1: 1})
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


def test_async_only_transport_waits_each_operation_exactly_once(
    ovstage_scene: OvstageScene,
) -> None:
    """The async fallback consumes completions in-call; a timeout-shaped
    ``None`` completion is not applied and the write is retried."""
    renderer = _AsyncOutlineRecordingRenderer()
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
    # the stale membership is carried instead of being forgotten.
    adapter._remove_scene()
    assert renderer.detach_count == 1
    assert renderer.outline_writes == [([_PICKED_PATH], 1)]

    # The next selection sync re-issues the clear so the stale outline
    # cannot appear on a later same-named scene.
    adapter.set_selection_highlight([])
    assert renderer.outline_writes[-1] == ([_PICKED_PATH], 0)


class _RecordedBatch:
    def __init__(self, stage: Any, paths: list[str]) -> None:
        self.stage = stage
        self.paths = list(paths)
        self.writes: list[tuple[str, np.ndarray, int, Any]] = []

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
    adapter._ovrtx_version = "kit"
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
    adapter._last_resolution = (64, 32)
    adapter._last_render_product_resolution = (64, 32)
    adapter._dt_clock = time.monotonic()
    adapter._last_load_from_scene_context = False
    adapter._borrow_step_count = 0
    adapter._selected_paths = []
    adapter._selection_outline_previous_paths = set()
    adapter._selection_outline_styles_configured = False
    adapter._selection_outline_style_calls = 0
    adapter._selection_outline_attribute_writes = 0
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
