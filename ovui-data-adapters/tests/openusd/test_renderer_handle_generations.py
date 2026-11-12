# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A destructive single-root open retires the old native handles.

The fake renderer models handle generations. An ``open_usd*`` call resets the
native stage, so every handle from before it is retired. A native
``remove_usd`` with a retired handle is the call that must never happen:
ovrtx does not document it as safe. The adapter still removes its current
session natively, at session reinjection and at shutdown. These tests need
no GPU.
"""

from __future__ import annotations

from typing import Any

from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

from pxr import Usd, UsdGeom

_PRODUCT = "/OvGearSession/Render/Viewport"


class _GenerationRenderer:
    """Fake single-root renderer. It records every native call."""

    def __init__(self) -> None:
        self.generation = 0
        self._next_handle = 0
        self.live: dict[int, int] = {}
        self.calls: list[tuple[str, Any]] = []
        self.retired_removals: list[int] = []

    def _open(self, kind: str) -> None:
        self.generation += 1
        self.live.clear()
        self.calls.append((kind, self.generation))

    def open_usd_from_file(self, path: str) -> None:
        self._open("open_usd_from_file")

    def open_usd_from_string(self, usda: str) -> None:
        self._open("open_usd_from_string")

    def add_usd_reference_from_string(self, usda: str, prefix: str) -> int:
        self._next_handle += 1
        self.live[self._next_handle] = self.generation
        self.calls.append(("add_usd_reference_from_string", self._next_handle))
        return self._next_handle

    def remove_usd(self, handle: int) -> None:
        self.calls.append(("remove_usd", handle))
        if handle not in self.live:
            self.retired_removals.append(handle)
            raise RuntimeError("USD handle is invalid or already removed")
        del self.live[handle]

    def reset_stage(self) -> None:
        self._open("reset_stage")

    def removals(self) -> list[Any]:
        return [handle for name, handle in self.calls if name == "remove_usd"]

    def write_attribute(self, *args: Any, **kwargs: Any) -> None:
        return None

    def reset(self) -> None:
        return None


def _adapter(renderer: _GenerationRenderer) -> OvRtxRendererAdapter:
    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    adapter._renderer = renderer
    adapter._renderer_config = None
    adapter._stage = None
    adapter._usd_handle = None
    adapter._session_handle = None
    adapter._live_resync_handles = []
    adapter._owned_tmp_path = None
    adapter._last_resolution = (64, 64)
    adapter._pending_resolution = (64, 64)
    adapter._latest_point_cloud_frames = {}
    adapter._render_product_path = _PRODUCT
    adapter._default_render_product_path = _PRODUCT
    return adapter


def _stage() -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    return stage


def test_second_load_does_not_remove_previous_generation_handles() -> None:
    renderer = _GenerationRenderer()
    adapter = _adapter(renderer)

    adapter.load_stage(_stage())
    old_session = adapter._session_handle
    assert old_session in renderer.live

    adapter.load_stage(_stage())

    assert renderer.retired_removals == []
    assert ("remove_usd", old_session) not in renderer.calls
    assert adapter._session_handle != old_session
    assert adapter._session_handle in renderer.live


def test_many_loads_never_remove_retired_handles() -> None:
    renderer = _GenerationRenderer()
    adapter = _adapter(renderer)

    for _ in range(5):
        adapter.load_stage(_stage())

    assert renderer.retired_removals == []
    assert not [call for call in renderer.calls if call[0] == "remove_usd"]
    assert list(renderer.live) == [adapter._session_handle]


def test_old_overlay_tokens_are_retired_without_native_removal() -> None:
    renderer = _GenerationRenderer()
    adapter = _adapter(renderer)
    adapter.load_stage(_stage())
    overlay = renderer.add_usd_reference_from_string("", "/Overlay")
    adapter._live_resync_handles = [overlay]

    adapter.load_stage(_stage())

    assert renderer.retired_removals == []
    assert adapter._live_resync_handles == []


def test_session_reinjection_after_reload_removes_current_session() -> None:
    renderer = _GenerationRenderer()
    adapter = _adapter(renderer)
    adapter.load_stage(_stage())
    adapter.load_stage(_stage())
    current = adapter._session_handle

    adapter._reinject_session_layer()

    assert renderer.removals() == [current]
    assert renderer.retired_removals == []
    assert current not in renderer.live
    assert list(renderer.live) == [adapter._session_handle]


def test_shutdown_after_reload_removes_only_current_session() -> None:
    renderer = _GenerationRenderer()
    adapter = _adapter(renderer)
    adapter.load_stage(_stage())
    adapter.load_stage(_stage())
    current = adapter._session_handle

    adapter.shutdown()

    assert renderer.removals() == [current]
    assert renderer.retired_removals == []
    assert renderer.live == {}
    assert adapter._session_handle is None
