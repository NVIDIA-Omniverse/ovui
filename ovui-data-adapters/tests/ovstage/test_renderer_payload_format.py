# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovstage renderer payload formatting helpers."""

from __future__ import annotations

import struct

import numpy as np
import pytest
from ovui_data_adapters.common import GpuFrame, ZeroCopyState, _Mode
from ovui_data_adapters.ovstage import renderer_adapter


class _FakeStage:
    current_ordinal = 7

    def __init__(self, attrs: dict[tuple[str, str], bytes]) -> None:
        self._attrs = attrs

    def read_attribute(self, ordinal: int, paths: list[str], attr_name: str) -> bytes:
        assert ordinal == self.current_ordinal
        assert len(paths) == 1
        return self._attrs.get((paths[0], attr_name), b"")


def test_extract_ldr_color_uses_gpu_frame_when_zero_copy_enabled() -> None:
    class Device:
        CPU = "cpu"
        CUDA = "cuda"

    class Tensor:
        data = 0xCAFE
        shape = (480, 640, 4)

        class DType:
            bits = 8
            lanes = 1

        dtype = DType()

    class Mapping:
        def __init__(self) -> None:
            self.tensor = Tensor()
            self.entered = False
            self.exited = False

        def __enter__(self):
            self.entered = True
            return self

        def __exit__(self, exc_type, exc, tb):
            self.exited = True
            return False

    class RenderVar:
        def __init__(self, mapping: Mapping) -> None:
            self.mapping = mapping
            self.devices = []

        def map(self, device):
            self.devices.append(device)
            return self.mapping

    adapter = renderer_adapter.OvstageRendererAdapter.__new__(
        renderer_adapter.OvstageRendererAdapter
    )
    adapter._ovrtx = type("FakeOvRtx", (), {"Device": Device})
    adapter._render_product_path = "/Render/Viewport"
    adapter._last_resolution = (640, 480)
    adapter._zero_copy_state = ZeroCopyState(_Mode.ENABLED)

    mapping = Mapping()
    rv = RenderVar(mapping)
    frame_out = type("FrameOut", (), {"render_vars": {"LdrColor": rv}})()
    product = type("Product", (), {"frames": [frame_out]})()
    products = {"/Render/Viewport": product}

    frame = adapter._extract_ldr_color(products, 640, 480)

    assert isinstance(frame, GpuFrame)
    try:
        assert frame.ptr == 0xCAFE
        assert (frame.width, frame.height) == (640, 480)
        assert frame.stride == 640 * 4
        assert rv.devices == [Device.CUDA]
        assert mapping.entered is True
        assert mapping.exited is False
    finally:
        frame.close()
    assert mapping.exited is True


def test_extract_ldr_color_falls_back_to_cpu_on_resolution_mismatch() -> None:
    class Device:
        CPU = "cpu"
        CUDA = "cuda"

    class Mapping:
        def __init__(self, arr: np.ndarray) -> None:
            self._arr = arr

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __dlpack__(self, *args, **kwargs):
            return self._arr.__dlpack__(*args, **kwargs)

        def __dlpack_device__(self):
            return self._arr.__dlpack_device__()

    class RenderVar:
        def __init__(self, arr: np.ndarray) -> None:
            self._arr = arr
            self.devices = []

        def map(self, device):
            self.devices.append(device)
            return Mapping(self._arr)

    adapter = renderer_adapter.OvstageRendererAdapter.__new__(
        renderer_adapter.OvstageRendererAdapter
    )
    adapter._ovrtx = type("FakeOvRtx", (), {"Device": Device})
    adapter._render_product_path = "/Render/Viewport"
    adapter._last_resolution = (640, 480)
    adapter._zero_copy_state = ZeroCopyState(_Mode.ENABLED)

    src = np.ones((480, 640, 4), dtype=np.uint8) * 17
    rv = RenderVar(src)
    frame_out = type("FrameOut", (), {"render_vars": {"LdrColor": rv}})()
    product = type("Product", (), {"frames": [frame_out]})()
    products = {"/Render/Viewport": product}

    frame = adapter._extract_ldr_color(products, 800, 600)

    assert rv.devices == [Device.CPU]
    assert frame.shape == (600, 800, 4)
    assert np.all(frame[:480, :640] == 17)


def test_extract_ldr_color_resamples_cpu_when_cuda_extent_is_stale() -> None:
    class Device:
        CPU = "cpu"
        CUDA = "cuda"

    class Tensor:
        data = 0xCAFE
        shape = (720, 1280, 4)

        class DType:
            bits = 8
            lanes = 1

        dtype = DType()

    class CudaMapping:
        def __init__(self) -> None:
            self.tensor = Tensor()
            self.exited = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.exited = True
            return False

    class CpuMapping:
        def __init__(self, arr: np.ndarray) -> None:
            self._arr = arr

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __dlpack__(self, *args, **kwargs):
            return self._arr.__dlpack__(*args, **kwargs)

        def __dlpack_device__(self):
            return self._arr.__dlpack_device__()

    class RenderVar:
        def __init__(self, arr: np.ndarray, cuda_mapping: CudaMapping) -> None:
            self._arr = arr
            self.cuda_mapping = cuda_mapping
            self.devices = []

        def map(self, device):
            self.devices.append(device)
            if device == Device.CUDA:
                return self.cuda_mapping
            return CpuMapping(self._arr)

    adapter = renderer_adapter.OvstageRendererAdapter.__new__(
        renderer_adapter.OvstageRendererAdapter
    )
    adapter._ovrtx = type("FakeOvRtx", (), {"Device": Device})
    adapter._render_product_path = "/Render/Viewport"
    adapter._last_resolution = (731, 668)
    adapter._last_render_product_resolution = None
    adapter._zero_copy_state = ZeroCopyState(_Mode.ENABLED)

    src = np.ones((720, 1280, 4), dtype=np.uint8) * 23
    cuda_mapping = CudaMapping()
    rv = RenderVar(src, cuda_mapping)
    frame_out = type("FrameOut", (), {"render_vars": {"LdrColor": rv}})()
    product = type("Product", (), {"frames": [frame_out]})()
    products = {"/Render/Viewport": product}

    frame = adapter._extract_ldr_color(products, 731, 668)

    assert rv.devices == [Device.CUDA, Device.CPU]
    assert cuda_mapping.exited is True
    assert frame.shape == (668, 731, 4)
    assert np.all(frame == 23)
    assert adapter._last_render_product_resolution == (1280, 720)


def _pack_float3_array(*values: tuple[float, float, float]) -> bytes:
    flattened = tuple(component for value in values for component in value)
    return struct.pack(f"<{len(flattened)}f", *flattened)


def _pack_matrix(*, tx: float = 0.0, ty: float = 0.0, tz: float = 0.0) -> bytes:
    return struct.pack(
        "<16d",
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        tx, ty, tz, 1.0,
    )


class _FakeHierarchyStage(_FakeStage):
    current_ordinal = 11

    def __init__(self) -> None:
        super().__init__({})
        self._records = {
            "/Render": "Xform",
            "/Render/Viewport": "RenderProduct",
            "/World": "Xform",
            "/World/Cube": "Cube",
        }
        self._children = {
            "": ("/Render", "/World"),
            "/Render": ("/Render/Viewport",),
            "/World": ("/World/Cube",),
        }

    def query_prims(self, ordinal: int, **kwargs):
        assert ordinal == self.current_ordinal
        return {
            "groups": tuple(
                {"prim_type": prim_type, "prim_list_handle": index + 1}
                for index, prim_type in enumerate(self._records.values())
            )
        }

    def get_prim_paths(self, prim_list_handle: int):
        return [tuple(self._records.keys())[int(prim_list_handle) - 1]]

    def query_children(self, ordinal: int, path: str):
        assert ordinal == self.current_ordinal
        return {"paths": self._children.get(path, ())}

    def get_child_paths(self, path: str):
        return self._children.get(path, ())


def test_runtime_layer_only_authors_private_render_prims() -> None:
    payload = renderer_adapter._build_runtime_layer(_FakeHierarchyStage())

    assert 'def Scope "OvuiRuntime"' in payload.usda
    assert 'def Camera "Main"' in payload.usda
    assert '"OmniRtxCameraAutoExposureAPI_1"' in payload.usda
    assert '"OmniRtxCameraExposureAPI_1"' in payload.usda
    assert "float exposure:responsivity = 1.1026709" in payload.usda
    assert "float exposure:time = 0.02" in payload.usda
    assert "bool omni:rtx:autoExposure:enabled = 1" in payload.usda
    assert 'def RenderProduct "Viewport"' in payload.usda
    assert "uniform uint[] deviceIds = [0]" in payload.usda
    assert "rel camera = <../Cameras/Main>" in payload.usda
    assert "rel orderedVars = <../Vars/LdrColor>" in payload.usda
    assert payload.camera_path == renderer_adapter._RENDER_CAMERA_LOCAL_PATH
    assert payload.usda.count('def Scope "Render"') == 1
    assert 'def RenderSettings' not in payload.usda
    assert 'def Cube "Cube"' not in payload.usda
    assert 'def Xform "World"' not in payload.usda


def test_runtime_layer_bootstraps_an_empty_new_stage() -> None:
    class EmptyStage:
        current_ordinal = 1

        def query_prims(self, ordinal: int):
            assert ordinal == self.current_ordinal
            return {"groups": ()}

    payload = renderer_adapter._build_runtime_layer(EmptyStage())

    assert 'def Camera "Main"' in payload.usda
    assert 'def RenderProduct "Viewport"' in payload.usda
    assert 'def RenderVar "LdrColor"' in payload.usda
    assert 'def DistantLight "FallbackKey"' in payload.usda


def test_runtime_layer_uses_collision_free_private_prefix() -> None:
    class NativeStage:
        def get_child_paths(self, parent_path: str) -> tuple[str, ...]:
            # The committed native topology already owns /_OvuiRuntime, so
            # the presentation layer must pick the next free private prefix.
            if parent_path == "":
                return ("/_OvuiRuntime", "/World")
            return ()

    class Scene:
        _stage = NativeStage()

    root_path = renderer_adapter._select_runtime_root_path(Scene())
    payload = renderer_adapter._build_runtime_layer(
        _FakeHierarchyStage(),
        runtime_root_path=root_path,
    )

    assert root_path == "/_OvuiRuntime_2"
    assert payload.root_path == root_path
    assert payload.camera_path == "/_OvuiRuntime_2/Render/Cameras/Main"
    assert payload.render_product_path == "/_OvuiRuntime_2/Render/Viewport"


def test_failed_runtime_layer_population_is_rolled_back() -> None:
    events: list[object] = []

    class Stage:
        def begin_frame(self) -> int:
            ordinal = 10 + sum(event == "begin" for event in events)
            events.append("begin")
            return ordinal

        def end_frame(self, ordinal: int) -> None:
            events.append(("end", ordinal))

    class Population:
        apply_count = 0

        def add_usd_reference_from_string(
            self, stage: Stage, usda: str, prefix: str
        ) -> int:
            events.append(("add", stage, usda, prefix))
            return 73

        def apply_usd_changes(self, stage: Stage, ordinal: int) -> None:
            self.apply_count += 1
            events.append(("apply", stage, ordinal))
            if self.apply_count == 1:
                raise RuntimeError("population failed")

        def remove_usd(self, stage: Stage, handle: int) -> None:
            events.append(("remove", stage, handle))

    stage = Stage()
    population = Population()

    with pytest.raises(RuntimeError, match="population failed"):
        renderer_adapter._add_runtime_layer(
            population,
            stage,
            "#usda 1.0\n",
        )

    assert population.apply_count == 2
    assert any(event == ("remove", stage, 73) for event in events)


def test_failed_population_cleanup_keeps_still_composed_root_scene_owned() -> None:
    root_path = "/_OvuiRuntime_2"

    class NativeStage:
        def get_child_paths(self, parent_path: str) -> tuple[str, ...]:
            # The committed native topology still composes the runtime root.
            assert parent_path == ""
            return (root_path,)

    class Scene:
        _stage = NativeStage()

        def __init__(self) -> None:
            self.presentation_root_paths = {root_path}

        def unregister_presentation_root(self, path: str) -> None:
            self.presentation_root_paths.discard(path)

    scene = Scene()

    renderer_adapter._unregister_presentation_root_if_absent(scene, root_path)

    assert scene.presentation_root_paths == {root_path}


def test_absent_runtime_root_releases_scene_ownership() -> None:
    root_path = "/_OvuiRuntime_2"

    class NativeStage:
        def get_child_paths(self, parent_path: str) -> tuple[str, ...]:
            assert parent_path == ""
            return ()

    class Scene:
        _stage = NativeStage()

        def __init__(self) -> None:
            self.presentation_root_paths = {root_path}

        def unregister_presentation_root(self, path: str) -> None:
            self.presentation_root_paths.discard(path)

    scene = Scene()

    renderer_adapter._unregister_presentation_root_if_absent(scene, root_path)

    assert scene.presentation_root_paths == set()


def test_runtime_removal_failure_does_not_release_scene_ownership() -> None:
    root_path = "/_OvuiRuntime_2"

    class Scene:
        def __init__(self) -> None:
            self.presentation_root_paths = {root_path}

        def unregister_presentation_root(self, path: str) -> None:
            self.presentation_root_paths.discard(path)

    class Population:
        def remove_usd(self, _stage: object, _handle: object) -> None:
            raise RuntimeError("injected native removal failure")

    scene = Scene()

    with pytest.raises(RuntimeError, match="injected native removal failure"):
        renderer_adapter._remove_runtime_layer_from_scene(
            scene=scene,
            population=Population(),
            stage=object(),
            reference_handle=object(),
            runtime_root_path=root_path,
        )

    assert scene.presentation_root_paths == {root_path}


def test_framing_camera_ignores_container_xform_sentinel_extents() -> None:
    huge = 3.0e38
    stage = _FakeStage(
        {
            ("/World", "extent"): _pack_float3_array(
                (-huge, -huge, -huge),
                (huge, huge, huge),
            ),
            ("/World", "worldMatrix"): _pack_matrix(),
            ("/World/Cube", "size"): struct.pack("<d", 2.0),
            ("/World/Cube", "worldMatrix"): _pack_matrix(),
        }
    )
    records = {
        "/World": "Xform",
        "/World/Cube": "Cube",
    }

    matrix = renderer_adapter._framing_camera_matrix(stage, records)

    assert abs(matrix[12]) < 20.0
    assert abs(matrix[13]) < 20.0
    assert abs(matrix[14]) < 20.0
