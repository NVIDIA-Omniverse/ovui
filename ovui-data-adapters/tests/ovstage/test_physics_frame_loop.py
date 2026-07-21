# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovphysx -> OVStage -> OVRTX BORROW fixed-step frame-loop behavior."""

from __future__ import annotations

import struct
import time
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from ovui_data_adapters.ovstage.change_stream import OvstageChangeStream
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.provider import (
    PHYSICS_FIXED_TIME_STEP_SECS,
    PHYSICS_STEP_OPERATION,
    OvstagePhysicsControlError,
    OvstagePhysicsControls,
)
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter
from ovui_data_adapters.ovstage.transform_adapter import OvstageTransformAdapter


_BODY_PATH = "/World/PhysicsBody"
_LOCAL_MATRIX = "localMatrix"
_WORLD_MATRIX = "worldMatrix"


class _Runtime:
    def __init__(self, module: "_FakeOvphysxModule") -> None:
        self._module = module

    def module(self, requirement_name: str) -> "_FakeOvphysxModule":
        if requirement_name != "ovphysx":
            raise KeyError(requirement_name)
        return self._module


class _FakeOvphysxModule:
    def __init__(self, events: list[str], stage: "_FakeStage") -> None:
        self._events = events
        self._stage = stage
        self.TensorType = SimpleNamespace(RIGID_BODY_POSE=1)
        self.instances: list[_FakePhysX] = []

    def PhysX(self, *args, **kwargs) -> "_FakePhysX":
        instance = _FakePhysX(self._events, self._stage, args, kwargs)
        self.instances.append(instance)
        return instance


class _FakePhysX:
    def __init__(
        self,
        events: list[str],
        stage: "_FakeStage",
        args: tuple,
        kwargs: dict,
    ) -> None:
        self._events = events
        self.calls: list[tuple[Any, ...]] = [("create", args, kwargs)]
        self._stage = stage
        self.step_error: BaseException | None = None
        self.step_count = 0
        self.pose_binding: _FakeTensorBinding | None = None

    def add_usd(self, source_path: str, path_prefix: str = "") -> tuple[int, int]:
        self.calls.append(("add_usd", source_path, path_prefix))
        return 17, 101

    def wait_op(self, op_index: int) -> None:
        self.calls.append(("wait_op", op_index))

    def wait_all(self) -> None:
        self.calls.append(("wait_all",))

    def create_tensor_binding(
        self,
        *,
        prim_paths: list[str],
        tensor_type: int,
        raise_if_empty: bool,
    ) -> "_FakeTensorBinding":
        self.calls.append((
            "create_tensor_binding",
            tuple(prim_paths),
            tensor_type,
            raise_if_empty,
        ))
        self.pose_binding = _FakeTensorBinding(self, prim_paths)
        return self.pose_binding

    def remove_usd(self, usd_handle: int) -> int:
        self.calls.append(("remove_usd", usd_handle))
        return 202

    def release(self) -> None:
        self.calls.append(("release",))

    def step_sync(self, dt: float, sim_time: float) -> SimpleNamespace:
        self.calls.append(("step_sync", dt, sim_time))
        self._events.append("ovphysx.step")
        if self.step_error is not None:
            raise self.step_error
        self.step_count += 1
        return None


class _FakeTensorBinding:
    def __init__(self, physx: _FakePhysX, prim_paths: list[str]) -> None:
        self._physx = physx
        self.shape = (len(prim_paths), 7)
        self.prim_paths = list(prim_paths)
        self.destroyed = False

    def read(self, output: np.ndarray) -> None:
        self._physx._events.append("ovphysx.read_tensor")
        output[:] = 0.0
        output[:, 0] = float(self._physx.step_count)
        output[:, 6] = 1.0

    def destroy(self) -> None:
        self.destroyed = True
        self._physx.calls.append(("destroy_tensor_binding",))


class _FakeStage:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._handle = self
        self.current_ordinal = 0
        self._attributes = {
            _BODY_PATH: {
                _LOCAL_MATRIX: _pack_matrix(_translation_matrix(0.0)),
                _WORLD_MATRIX: _pack_matrix(_translation_matrix(0.0)),
            },
        }
        self._dirty_by_ordinal: dict[int, dict[str, set[str]]] = {}
        self.query_calls: list[dict[str, Any]] = []

    def handle(self) -> int:
        return 1234

    def begin_frame(self) -> int:
        self.current_ordinal += 1
        return int(self.current_ordinal)

    def end_frame(self, ordinal: int) -> None:
        assert int(ordinal) == int(self.current_ordinal)

    def write_attribute(
        self,
        ordinal: int,
        prim_paths: list[str],
        attr_name: str,
        data: bytes,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        self._events.append("ovstage.write_attribute")
        for index, path in enumerate(prim_paths):
            assert path == _BODY_PATH
            start = index * 16 * 8
            row = bytes(data[start:start + 16 * 8])
            self._attributes[str(path)][str(attr_name)] = row
            self._dirty_by_ordinal.setdefault(int(ordinal), {}).setdefault(
                str(path),
                set(),
            ).add(str(attr_name))

    def query_prims(
        self,
        ordinal: int,
        *,
        since_ordinal: int | None = None,
        attribute_filter: list[str] | tuple[str, ...] | None = None,
        applied_schemas: list[str] | tuple[str, ...] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        if applied_schemas == ["PhysicsRigidBodyAPI"]:
            return {
                "groups": (
                    {
                        "prim_list_handle": 1,
                        "dirty_count": 0,
                        "dirty_indices": [],
                    },
                ),
            }
        since = int(since_ordinal or 0)
        query = {
            "ordinal": int(ordinal),
            "since_ordinal": since,
            "attribute_filter": tuple(attribute_filter or ()),
        }
        self.query_calls.append(query)
        if since_ordinal is not None:
            self._events.append("ovstage.dirty_query")
        requested = set(attribute_filter or ())
        available = {
            _LOCAL_MATRIX,
            _WORLD_MATRIX,
            "xformOp:transform",
            "xformOpOrder",
        }
        changed = False
        for dirty_ordinal, path_attrs in self._dirty_by_ordinal.items():
            if since < dirty_ordinal <= int(ordinal):
                attrs = path_attrs.get(_BODY_PATH, set())
                if not requested or attrs.intersection(requested):
                    changed = True
                    break
        attributes = tuple(attribute_filter or sorted(available))
        return {
            "groups": (
                {
                    "prim_type": "Cube",
                    "prim_list_handle": 1,
                    "attributes": attributes,
                    "dirty_count": 1 if changed else 0,
                    "dirty_indices": [0] if changed else [],
                    "added_indices": [],
                    "removed_indices": [],
                },
            ),
        }

    def get_prim_paths(self, prim_list_handle: int) -> tuple[str, ...]:
        assert int(prim_list_handle) == 1
        return (_BODY_PATH,)

    def get_parent_path(self, path: str) -> str:
        if str(path) == _BODY_PATH:
            return "/World"
        raise KeyError(path)

    def read_attribute(self, _ordinal: int, paths: list[str], attr_name: str) -> bytes:
        return self._attributes[str(paths[0])][str(attr_name)]

    def read_column(
        self,
        _ordinal: int,
        prim_list_handle: int,
        attr_name: str,
    ) -> tuple[list[bytes], tuple[int, int, int]]:
        assert int(prim_list_handle) == 1
        return [self._attributes[_BODY_PATH][str(attr_name)]], (2, 64, 16)


class _FakeScene:
    def __init__(self, stage: _FakeStage) -> None:
        self._stage = stage
        self.source_path = "/tmp/physics_frame_loop.usda"
        self.initial_ordinal = int(stage.current_ordinal)
        self.is_open = True
        self._change_stream: OvstageChangeStream | None = None

    @property
    def current_ordinal(self) -> int:
        return int(self._stage.current_ordinal)

    @property
    def change_stream(self) -> OvstageChangeStream:
        if self._change_stream is None:
            self._change_stream = OvstageChangeStream(self)
        return self._change_stream

    @property
    def hierarchy(self) -> Any:
        raise RuntimeError("fake hierarchy intentionally unavailable")


class _RecordingRenderer:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.step_calls = 0
        self.step_ordinals: list[int] = []
        self.data_api_lookups: list[str] = []

    def step(self, **kwargs: Any) -> object:
        self._events.append("ovrtx.render")
        self.step_calls += 1
        self.step_ordinals.append(int(kwargs["ordinal"]))
        return object()

    def __getattr__(self, name: str) -> Any:
        if name in {
            "query_prims",
            "resolve_prim_path_id",
            "step",
            "update_from_stage",
            "write_attribute",
        }:
            self.data_api_lookups.append(name)
        raise AttributeError(name)


def test_play_tick_writes_pose_to_ovstage_then_renders_borrowed_stage() -> None:
    harness = _Harness()
    transform_adapter = OvstageTransformAdapter(harness.scene)
    property_adapter = OvstagePropertyAdapter(harness.scene, [_BODY_PATH])
    subscription = harness.scene.change_stream.subscribe_stage(
        lambda _event: None,
        call_later=lambda _delay, _callback: None,
    )

    try:
        harness.controls.enable()
        harness.controls.play()
        initial_transform = transform_adapter.get_local_transform(_BODY_PATH)
        initial_property = property_adapter.get_value(_LOCAL_MATRIX)
        harness.stage.query_calls.clear()

        steps = harness.controls.tick(PHYSICS_FIXED_TIME_STEP_SECS * 3.0)
        frame = harness.renderer_adapter.render_frame(64, 32, None, None)
        renderer_query_calls = list(harness.stage.query_calls)

        assert steps == 3
        assert frame.shape == (32, 64, 4)
        assert harness.physx.calls[-3:] == [
            ("step_sync", PHYSICS_FIXED_TIME_STEP_SECS, 0.0),
            ("step_sync", PHYSICS_FIXED_TIME_STEP_SECS, PHYSICS_FIXED_TIME_STEP_SECS),
            ("step_sync", PHYSICS_FIXED_TIME_STEP_SECS, PHYSICS_FIXED_TIME_STEP_SECS * 2.0),
        ]
        assert harness.renderer.step_calls == 1
        assert harness.renderer.step_ordinals == [harness.stage.current_ordinal]
        assert harness.renderer.data_api_lookups == []
        assert transform_adapter.get_local_transform(_BODY_PATH)[3][0] == pytest.approx(3.0)
        refreshed_property_adapter = OvstagePropertyAdapter(harness.scene, [_BODY_PATH])
        property_value = refreshed_property_adapter.get_value(_LOCAL_MATRIX)
        assert initial_transform[3][0] == pytest.approx(0.0)
        assert initial_property[12] == pytest.approx(0.0)
        assert property_value[12] == pytest.approx(3.0)

        assert renderer_query_calls == []
        assert _ordered_subsequence(
            harness.events,
            [
                "ovphysx.step",
                "ovphysx.read_tensor",
                "ovstage.write_attribute",
                "ovrtx.render",
            ],
        )
    finally:
        subscription.cancel()


def test_change_stream_poll_uses_physx_pose_paths_without_dirty_query() -> None:
    harness = _Harness()

    harness.controls.enable()
    harness.controls.play()
    harness.stage.query_calls.clear()
    harness.controls.tick(PHYSICS_FIXED_TIME_STEP_SECS * 2.0)

    events = harness.scene.change_stream.poll()

    assert len(events) == 1
    assert events[0].source == "ovstage:transform"
    assert events[0].changed_paths == (_BODY_PATH,)
    assert harness.stage.query_calls == []


def test_accumulator_only_steps_while_playing_and_stop_pauses() -> None:
    harness = _Harness()
    harness.controls.enable()

    assert harness.controls.tick(PHYSICS_FIXED_TIME_STEP_SECS * 2.0) == 0
    assert harness.physx.calls == [
        ("create", (), {"device": "gpu"}),
        ("add_usd", "/tmp/physics_frame_loop.usda", ""),
        ("wait_op", 101),
        ("create_tensor_binding", (_BODY_PATH,), 1, True),
    ]

    harness.controls.play()
    assert harness.controls.tick(PHYSICS_FIXED_TIME_STEP_SECS * 0.5) == 0
    assert harness.controls.tick(PHYSICS_FIXED_TIME_STEP_SECS * 0.5) == 1
    harness.controls.stop()
    assert harness.controls.tick(PHYSICS_FIXED_TIME_STEP_SECS * 4.0) == 0
    assert sum(1 for call in harness.physx.calls if call[0] == "step_sync") == 1
    assert harness.stage.current_ordinal == 1


def test_pose_tensor_binding_survives_ticks_and_is_destroyed_on_disable() -> None:
    harness = _Harness()
    harness.controls.enable()
    harness.controls.play()
    binding = harness.physx.pose_binding
    assert binding is not None

    harness.controls.tick(PHYSICS_FIXED_TIME_STEP_SECS)
    for _ in range(5):
        harness.controls.tick(PHYSICS_FIXED_TIME_STEP_SECS)

    assert binding.destroyed is False

    harness.controls.disable()

    assert binding.destroyed is True
    assert ("destroy_tensor_binding",) in harness.physx.calls


def test_step_failure_is_structured_and_stops_loop_before_garbage_render() -> None:
    harness = _Harness()
    harness.controls.enable()
    harness.controls.play()
    harness.physx.step_error = RuntimeError("mock solver failed")

    with pytest.raises(OvstagePhysicsControlError) as exc_info:
        harness.controls.tick(PHYSICS_FIXED_TIME_STEP_SECS)

    failure = exc_info.value.failure
    assert failure.operation == PHYSICS_STEP_OPERATION
    assert failure.scene_path == "/tmp/physics_frame_loop.usda"
    assert "mock solver failed" in failure.exception_text
    assert harness.controls.playing is False
    assert harness.stage.current_ordinal == 0
    assert not [event for event in harness.events if event.startswith("ovrtx.")]


class _Harness:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.stage = _FakeStage(self.events)
        self.scene = _FakeScene(self.stage)
        self.module = _FakeOvphysxModule(self.events, self.stage)
        self.session = SimpleNamespace(
            _runtime=_Runtime(self.module),
            current_scene=self.scene,
            prepare_runtime_imports=lambda: None,
        )
        self.controls = OvstagePhysicsControls(self.session)
        self.scene.physics_controls = self.controls
        self.renderer = _RecordingRenderer(self.events)
        self.renderer_adapter = _renderer_adapter(self.scene, self.renderer)

    @property
    def physx(self) -> _FakePhysX:
        return self.module.instances[0]


def _renderer_adapter(
    scene: _FakeScene,
    renderer: _RecordingRenderer,
) -> OvstageRendererAdapter:
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._scene = scene
    adapter._renderer = renderer
    adapter._attached_stage = scene._stage
    adapter._gpu_device_name = "test gpu"
    adapter._logged_first_step = True
    adapter._render_product_path = "/Render/Product"
    adapter._default_render_product_path = adapter._render_product_path
    adapter._active_render_product_common_path = None
    adapter._camera_path = None
    adapter._last_resolution = (64, 32)
    adapter._last_render_product_resolution = adapter._last_resolution
    adapter._dt_clock = time.monotonic()
    adapter._last_load_from_scene_context = False
    adapter._borrow_step_count = 0
    adapter._in_flight_pick_queries = []
    adapter._extract_ldr_color = (  # type: ignore[method-assign]
        lambda _products, width, height: np.zeros((height, width, 4), dtype=np.uint8)
    )
    return adapter


def _translation_matrix(x: float) -> tuple[float, ...]:
    return (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        float(x), 0.0, 0.0, 1.0,
    )


def _pack_matrix(matrix: tuple[float, ...]) -> bytes:
    return struct.pack("<16d", *matrix)


def _ordered_subsequence(values: list[str], expected: list[str]) -> bool:
    start = 0
    for item in expected:
        try:
            index = values.index(item, start)
        except ValueError:
            return False
        start = index + 1
    return True
