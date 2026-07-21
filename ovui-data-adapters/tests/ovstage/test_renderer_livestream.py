# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Runtime-free OVStage renderer coverage for the legacy viewport stream."""

from __future__ import annotations

from collections import deque
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pytest
from ovui_data_adapters.common import GpuFrame, ZeroCopyState, _Mode
from ovui_data_adapters.common import _livestream_tap as tap_module
from ovui_data_adapters.ovstage import renderer_adapter as renderer_module
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter


class _FakeRenderer:
    version = "test-renderer"

    def __init__(self, config: Any) -> None:
        self.config = config

    def attach_ovstage(self, _stage: Any) -> None:
        return None

    def detach_ovstage(self) -> None:
        return None

    def step(self, **_kwargs: Any) -> dict[str, object]:
        return {}


class _FakePathDictionary:
    def __init__(self, _stage: Any) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class _FakeScene:
    def __init__(self) -> None:
        self._stage = object()
        self.is_open = True
        self.attached_renderers: list[Any] = []
        self.presentation_root_paths: set[str] = set()

    def attach_renderer(self, renderer: Any) -> None:
        self.attached_renderers.append(renderer)

    def detach_renderer(self, renderer: Any) -> None:
        self.attached_renderers.remove(renderer)

    def register_presentation_root(self, path: str) -> None:
        self.presentation_root_paths.add(path)

    def unregister_presentation_root(self, path: str) -> None:
        self.presentation_root_paths.discard(path)


def _patch_scene_load(monkeypatch: pytest.MonkeyPatch) -> None:
    ovstage = SimpleNamespace(PathDictionary=_FakePathDictionary)
    monkeypatch.setattr(renderer_module, "import_module", lambda _name: ovstage)
    monkeypatch.setattr(renderer_module, "_query_records", lambda _stage: [])
    monkeypatch.setattr(
        renderer_module,
        "_build_runtime_layer",
        lambda _stage, *, resolution, records, runtime_root_path: SimpleNamespace(
            usda="#usda 1.0",
            root_path=runtime_root_path,
            camera_path=f"{runtime_root_path}/Render/Cameras/Main",
            render_product_path=f"{runtime_root_path}/Render/Viewport",
        ),
    )
    monkeypatch.setattr(renderer_module, "_load_population_module", lambda _module: object())
    monkeypatch.setattr(
        renderer_module,
        "_add_runtime_layer",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(renderer_module, "_remove_runtime_layer", lambda *_args: None)


def _fake_ovrtx() -> ModuleType:
    module = ModuleType("ovrtx")
    module.__version__ = "test"
    module.AttachMode = SimpleNamespace(BORROW=object())

    class RendererConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    module.RendererConfig = RendererConfig
    module.Renderer = _FakeRenderer
    return module


@pytest.mark.parametrize(
    ("stream_value", "headless_value", "expected_enabled"),
    (
        (None, None, False),
        ("0", None, False),
        ("true", None, True),
        ("YES", None, True),
        ("1", "1", False),
        ("1", "true", True),
        ("1", "YES", True),
    ),
)
def test_init_gates_provider_neutral_livestream_and_exposes_property(
    monkeypatch: pytest.MonkeyPatch,
    stream_value: str | None,
    headless_value: str | None,
    expected_enabled: bool,
) -> None:
    ovrtx = _fake_ovrtx()
    tap = SimpleNamespace(close=lambda: None)
    create_calls: list[None] = []

    monkeypatch.setattr(
        renderer_module,
        "import_ovrtx",
        lambda: SimpleNamespace(module=ovrtx, error=None),
    )
    monkeypatch.setattr(renderer_module, "_validate_configured_ovrtx_source", lambda _m: None)
    monkeypatch.setattr(renderer_module, "_detect_gpu_device_name", lambda: "Test GPU")
    _patch_scene_load(monkeypatch)

    def maybe_create(_cls: type[Any]) -> Any:
        create_calls.append(None)
        return tap

    monkeypatch.setattr(
        tap_module.LivestreamTap,
        "maybe_create",
        classmethod(maybe_create),
    )
    if stream_value is None:
        monkeypatch.delenv("OVGEAR_LIVESTREAM", raising=False)
    else:
        monkeypatch.setenv("OVGEAR_LIVESTREAM", stream_value)
    if headless_value is None:
        monkeypatch.delenv("OMNIUI_HEADLESS", raising=False)
    else:
        monkeypatch.setenv("OMNIUI_HEADLESS", headless_value)

    adapter = OvstageRendererAdapter()
    try:
        # Renderer preconstruction happens before provider replacement and
        # must not acquire process-global ovstream ownership.
        assert adapter.livestream is None
        assert create_calls == []

        adapter.load_stage(_FakeScene())

        assert adapter.livestream is (tap if expected_enabled else None)
        assert len(create_calls) == int(expected_enabled)
    finally:
        adapter.shutdown()


class _LifecycleTap:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1
        self.events.append(f"{self.name}.close")


def _patch_adapter_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    ovrtx = _fake_ovrtx()
    monkeypatch.setattr(
        renderer_module,
        "import_ovrtx",
        lambda: SimpleNamespace(module=ovrtx, error=None),
    )
    monkeypatch.setattr(renderer_module, "_validate_configured_ovrtx_source", lambda _m: None)
    monkeypatch.setattr(renderer_module, "_detect_gpu_device_name", lambda: "Test GPU")
    _patch_scene_load(monkeypatch)


def test_failed_replacement_cleanup_does_not_close_active_livestream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed provider open cleans only its transport-free prebuilt renderer."""

    events: list[str] = []
    taps = [_LifecycleTap("active", events), _LifecycleTap("replacement", events)]
    create_index = 0

    def maybe_create(_cls: type[Any]) -> Any:
        nonlocal create_index
        tap = taps[create_index]
        create_index += 1
        events.append(f"{tap.name}.create")
        return tap

    _patch_adapter_construction(monkeypatch)
    monkeypatch.setenv("OVGEAR_LIVESTREAM", "1")
    monkeypatch.delenv("OMNIUI_HEADLESS", raising=False)
    monkeypatch.setattr(
        tap_module.LivestreamTap,
        "maybe_create",
        classmethod(maybe_create),
    )

    active = OvstageRendererAdapter()
    active.load_stage(_FakeScene())
    replacement = OvstageRendererAdapter()
    try:
        assert active.livestream is taps[0]
        assert replacement.livestream is None
        assert events == ["active.create"]

        # Mirrors Application.open_file cleaning a prebuilt renderer after
        # session.open_stage fails while the provider keeps its old scene.
        replacement.shutdown()

        assert active.livestream is taps[0]
        assert taps[0].close_count == 0
        assert events == ["active.create"]
    finally:
        active.shutdown()


def test_successful_replacement_activates_new_tap_after_old_tap_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider teardown completes before the replacement takes ovstream ownership."""

    events: list[str] = []
    taps = [_LifecycleTap("old", events), _LifecycleTap("new", events)]
    create_index = 0

    def maybe_create(_cls: type[Any]) -> Any:
        nonlocal create_index
        tap = taps[create_index]
        create_index += 1
        events.append(f"{tap.name}.create")
        return tap

    _patch_adapter_construction(monkeypatch)
    monkeypatch.setenv("OVGEAR_LIVESTREAM", "1")
    monkeypatch.delenv("OMNIUI_HEADLESS", raising=False)
    monkeypatch.setattr(
        tap_module.LivestreamTap,
        "maybe_create",
        classmethod(maybe_create),
    )

    old = OvstageRendererAdapter()
    old.load_stage(_FakeScene())
    replacement = OvstageRendererAdapter()
    try:
        assert events == ["old.create"]
        assert replacement.livestream is None

        # This is the provider's old-scene teardown inside open_stage().
        old.shutdown()
        replacement.load_stage(_FakeScene())

        assert events == ["old.create", "old.close", "new.create"]
        assert taps[0].close_count == 1
        assert taps[1].close_count == 0
        assert replacement.livestream is taps[1]
    finally:
        replacement.shutdown()


def test_failed_old_scene_detach_preserves_active_livestream() -> None:
    """A failed provider replacement retains both the old scene and stream."""

    class _FailingDetachRenderer:
        def detach_ovstage(self) -> None:
            raise RuntimeError("injected detach failure")

    tap = _LifecycleTap("active", [])
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._livestream = tap
    adapter._in_flight_pick_queries = deque()
    adapter._attached_stage = object()
    adapter._renderer = _FailingDetachRenderer()
    adapter._scene = None
    adapter._runtime_population = None
    adapter._runtime_reference_handle = None
    adapter._path_dictionary = None

    with pytest.raises(RuntimeError, match="injected detach failure"):
        adapter.shutdown()

    assert adapter.livestream is tap
    assert tap.close_count == 0
    assert adapter._attached_stage is not None
    assert adapter._renderer is not None


class _Device:
    CPU = "cpu"
    CUDA = "cuda"


class _Tensor:
    def __init__(self, width: int, height: int, ptr: int = 0xCAFE) -> None:
        self.data = ptr
        self.shape = (height, width, 4)
        self.dtype = SimpleNamespace(bits=8, lanes=1)


class _CudaMapping:
    def __init__(self, tensor: _Tensor) -> None:
        self.tensor = tensor
        self.entered = False
        self.exited = False

    def __enter__(self) -> "_CudaMapping":
        self.entered = True
        return self

    def __exit__(self, *_args: Any) -> bool:
        self.exited = True
        return False


class _CpuMapping:
    def __init__(self, array: np.ndarray) -> None:
        self._array = array

    def __enter__(self) -> "_CpuMapping":
        return self

    def __exit__(self, *_args: Any) -> bool:
        return False

    def __dlpack__(self, *args: Any, **kwargs: Any) -> Any:
        return self._array.__dlpack__(*args, **kwargs)

    def __dlpack_device__(self) -> Any:
        return self._array.__dlpack_device__()


class _RenderVar:
    def __init__(
        self,
        tensor: _Tensor,
        cpu_array: np.ndarray,
    ) -> None:
        self.cuda_mapping = _CudaMapping(tensor)
        self.cpu_array = cpu_array
        self.devices: list[str] = []

    def map(self, device: str) -> _CudaMapping | _CpuMapping:
        self.devices.append(device)
        if device == _Device.CUDA:
            return self.cuda_mapping
        return _CpuMapping(self.cpu_array)


class _Tap:
    def __init__(self, d2h_array: np.ndarray | None = None) -> None:
        self.d2h_array = d2h_array
        self.tee_calls: list[tuple[_Tensor, int, int]] = []
        self.d2h_calls: list[tuple[_Tensor, int, int, np.ndarray | None]] = []
        self.close_count = 0
        self.fail_d2h = False

    def tee_to_ovstream(self, tensor: _Tensor, width: int, height: int) -> None:
        self.tee_calls.append((tensor, width, height))

    def tee_and_d2h(
        self,
        tensor: _Tensor,
        width: int,
        height: int,
        *,
        host_buf: np.ndarray | None,
    ) -> np.ndarray:
        self.d2h_calls.append((tensor, width, height, host_buf))
        if self.fail_d2h:
            raise RuntimeError("injected livestream copy failure")
        assert self.d2h_array is not None
        return self.d2h_array

    def close(self) -> None:
        self.close_count += 1


def _adapter_and_products(
    *,
    width: int = 3,
    height: int = 2,
    tap: _Tap,
    zero_copy: bool,
) -> tuple[OvstageRendererAdapter, _RenderVar, dict[str, Any]]:
    tensor = _Tensor(width, height)
    cpu_array = np.full((height, width, 4), 23, dtype=np.uint8)
    render_var = _RenderVar(tensor, cpu_array)
    products = {
        "/Render/Viewport": SimpleNamespace(
            frames=[SimpleNamespace(render_vars={"LdrColor": render_var})]
        )
    }
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._ovrtx = SimpleNamespace(Device=_Device)
    adapter._render_product_path = "/Render/Viewport"
    adapter._last_resolution = (width, height)
    adapter._last_render_product_resolution = (width, height)
    adapter._zero_copy_state = ZeroCopyState(_Mode.ENABLED) if zero_copy else None
    adapter._livestream = tap
    adapter._livestream_error_logged = False
    adapter._livestream_host_buf = None
    return adapter, render_var, products


def test_zero_copy_ui_and_livestream_share_one_cuda_mapping() -> None:
    tap = _Tap()
    adapter, render_var, products = _adapter_and_products(
        tap=tap,
        zero_copy=True,
    )

    output = adapter._extract_ldr_color(products, 3, 2)

    assert isinstance(output, GpuFrame)
    assert render_var.devices == [_Device.CUDA]
    assert tap.tee_calls == [(render_var.cuda_mapping.tensor, 3, 2)]
    assert tap.d2h_calls == []
    assert render_var.cuda_mapping.entered
    assert not render_var.cuda_mapping.exited
    output.close()
    assert render_var.cuda_mapping.exited


def test_livestream_only_tees_cuda_output_and_returns_host_frame() -> None:
    streamed = np.arange(24, dtype=np.uint8).reshape(2, 3, 4)
    tap = _Tap(streamed)
    adapter, render_var, products = _adapter_and_products(
        tap=tap,
        zero_copy=False,
    )

    output = adapter._extract_ldr_color(products, 3, 2)

    np.testing.assert_array_equal(output, streamed)
    assert render_var.devices == [_Device.CUDA]
    assert tap.tee_calls == []
    assert tap.d2h_calls == [(render_var.cuda_mapping.tensor, 3, 2, None)]
    assert render_var.cuda_mapping.exited
    assert adapter._livestream_host_buf is streamed


def test_livestream_cuda_failure_falls_back_to_cpu_output() -> None:
    tap = _Tap()
    tap.fail_d2h = True
    adapter, render_var, products = _adapter_and_products(
        tap=tap,
        zero_copy=False,
    )

    output = adapter._extract_ldr_color(products, 3, 2)

    assert render_var.devices == [_Device.CUDA, _Device.CPU]
    assert render_var.cuda_mapping.exited
    assert adapter._livestream_error_logged is True
    assert output.shape == (2, 3, 4)
    assert np.all(output == 23)


def test_shutdown_closes_livestream_once_and_releases_renderer() -> None:
    tap = _Tap()
    adapter = OvstageRendererAdapter.__new__(OvstageRendererAdapter)
    adapter._livestream = tap
    adapter._in_flight_pick_queries = deque()
    adapter._attached_stage = None
    adapter._renderer = object()

    adapter.shutdown()
    adapter.shutdown()

    assert tap.close_count == 1
    assert adapter.livestream is None
    assert adapter._renderer is None
