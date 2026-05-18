# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Focused tests for ovrtx-backed viewport pick and selection outlines."""

from __future__ import annotations

import collections
import inspect
from types import SimpleNamespace

import numpy as np
import pytest
from ovui_data_adapters.openusd import renderer_adapter as renderer_mod
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.viewport.viewport_widget import ViewportWidget


class _FakeRenderer:
    def __init__(self) -> None:
        self.enqueue_calls = []
        self.style_calls = []
        self.write_calls = []
        # When non-empty, the head of this deque is the next write outcome:
        # ``True`` lets the call succeed, ``False`` raises so the adapter
        # observes a failed write. Falls back to success when empty.
        self.write_outcomes: collections.deque = collections.deque()

    def enqueue_pick_query(self, *args, **kwargs):
        self.enqueue_calls.append((args, kwargs))

    def set_selection_group_styles(self, styles):
        self.style_calls.append(styles)

    def write_attribute(self, prim_paths, attribute_name, tensor, **_kwargs):
        if self.write_outcomes and self.write_outcomes[0] is False:
            self.write_outcomes.popleft()
            raise RuntimeError("simulated ovrtx write failure")
        if self.write_outcomes:
            self.write_outcomes.popleft()
        self.write_calls.append(
            (list(prim_paths), attribute_name, np.asarray(tensor).astype(np.uint8).tolist())
        )


class _SelectionGroupStyle:
    def __init__(self, outline_color, fill_color):
        self.outline_color = tuple(outline_color)
        self.fill_color = tuple(fill_color)


def _make_adapter(renderer: _FakeRenderer) -> OvRtxRendererAdapter:
    adapter = OvRtxRendererAdapter.__new__(OvRtxRendererAdapter)
    adapter._renderer = renderer
    adapter._stage = object()
    adapter._usd_handle = object()
    adapter._render_product_path = "/OvGearSession/Render/Viewport"
    adapter._pending_resolution = (101, 101)
    adapter._last_resolution = (101, 101)
    adapter._selected_paths = []
    adapter._selection_outline_previous_paths = set()
    adapter._selection_outline_styles_configured = False
    adapter._selection_outline_style_calls = 0
    adapter._selection_outline_attribute_writes = 0
    adapter._in_flight_pick_queries = collections.deque()
    adapter._pick_seq = 0
    adapter._pick_enqueue_count = 0
    adapter._pick_result_count = 0
    adapter._last_pick_pixel_rect = None
    adapter._last_pick_path = None
    adapter._last_pick_world_point = None
    return adapter


def test_pick_uses_ovrtx_enqueue_pick_query(monkeypatch):
    fake_ovrtx = SimpleNamespace()
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    callbacks = []
    adapter.pick(0.0, 0.0, lambda path, point: callbacks.append((path, point)), "q")

    assert renderer.enqueue_calls == [
        (("/OvGearSession/Render/Viewport", 50, 50, 51, 51), {})
    ]
    assert callbacks == []
    # Exactly one in-flight point query, registered under name "q",
    # callback still live.
    assert len(adapter._in_flight_pick_queries) == 1
    seq, kind, name, cb, cancel_reason, cached_hits = adapter._in_flight_pick_queries[0]
    assert kind == "point"
    assert name == "q"
    assert cb is not None
    assert cancel_reason is None
    assert cached_hits is None
    assert adapter._pick_enqueue_count == 1


def test_selection_highlight_writes_and_clears_ovrtx_outline_groups(monkeypatch):
    fake_ovrtx = SimpleNamespace(
        OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP="omni:selectionOutlineGroup",
        SelectionGroupStyle=_SelectionGroupStyle,
    )
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    adapter.set_selection_highlight(["/World/Cube"])
    adapter.set_selection_highlight(["/World/Sphere"])
    adapter.set_selection_highlight([])

    assert len(renderer.style_calls) == 1
    style = renderer.style_calls[0][1]
    assert isinstance(style, _SelectionGroupStyle)
    assert style.outline_color[-1] == 1.0
    assert renderer.write_calls == [
        (["/World/Cube"], "omni:selectionOutlineGroup", [1]),
        (["/World/Cube"], "omni:selectionOutlineGroup", [0]),
        (["/World/Sphere"], "omni:selectionOutlineGroup", [1]),
        (["/World/Sphere"], "omni:selectionOutlineGroup", [0]),
    ]
    assert adapter._selection_outline_attribute_writes == 4


def test_selection_highlight_coalesces_unchanged_selected_paths(monkeypatch):
    """Unchanged selections must not rewrite ovrtx outline attributes."""
    fake_ovrtx = SimpleNamespace(
        OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP="omni:selectionOutlineGroup",
        SelectionGroupStyle=_SelectionGroupStyle,
    )
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    adapter.set_selection_highlight(["/World/Cube"])
    adapter.set_selection_highlight(["/World/Cube"])

    assert renderer.write_calls == [
        (["/World/Cube"], "omni:selectionOutlineGroup", [1]),
    ]
    assert adapter._selection_outline_previous_paths == {"/World/Cube"}
    assert adapter._selection_outline_attribute_writes == 1


def test_selection_highlight_only_updates_multi_selection_delta(monkeypatch):
    """Removing one prim clears only that prim and leaves retained paths alone."""
    fake_ovrtx = SimpleNamespace(
        OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP="omni:selectionOutlineGroup",
        SelectionGroupStyle=_SelectionGroupStyle,
    )
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    adapter.set_selection_highlight(["/World/Cube", "/World/Sphere"])
    adapter.set_selection_highlight(["/World/Sphere"])

    assert renderer.write_calls == [
        (["/World/Cube", "/World/Sphere"], "omni:selectionOutlineGroup", [1, 1]),
        (["/World/Cube"], "omni:selectionOutlineGroup", [0]),
    ]
    assert adapter._selection_outline_previous_paths == {"/World/Sphere"}
    assert adapter._selection_outline_attribute_writes == 2


def test_selection_highlight_retries_set_after_failed_write(monkeypatch):
    """A failed outline set must stay retryable on the next selection call."""
    fake_ovrtx = SimpleNamespace(
        OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP="omni:selectionOutlineGroup",
        SelectionGroupStyle=_SelectionGroupStyle,
    )
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    renderer.write_outcomes.extend([False])
    adapter.set_selection_highlight(["/World/Cube"])
    assert "/World/Cube" not in adapter._selection_outline_previous_paths
    assert renderer.write_calls == []
    assert adapter._selection_outline_attribute_writes == 0

    renderer.write_outcomes.extend([True])
    adapter.set_selection_highlight(["/World/Cube"])

    assert renderer.write_calls == [
        (["/World/Cube"], "omni:selectionOutlineGroup", [1]),
    ]
    assert adapter._selection_outline_previous_paths == {"/World/Cube"}
    assert adapter._selection_outline_attribute_writes == 1


def test_selection_highlight_retries_clear_after_failed_write(monkeypatch):
    """A failed outline clear leaves the path tracked so the next call retries.

    Regression for Codex review of #67: previously the adapter
    optimistically dropped paths from ``_selection_outline_previous_paths``
    even when ``_write_selection_outline_group`` failed, so a transient
    ovrtx failure could leave a deselected prim outlined forever.
    """
    fake_ovrtx = SimpleNamespace(
        OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP="omni:selectionOutlineGroup",
        SelectionGroupStyle=_SelectionGroupStyle,
    )
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    # Step 1: Select Cube — the SET write succeeds.
    renderer.write_outcomes.extend([True])  # set ["Cube"] -> 1
    adapter.set_selection_highlight(["/World/Cube"])

    # Step 2: Deselect — clear write FAILS. Cube must remain tracked.
    renderer.write_outcomes.extend([False])  # clear ["Cube"] -> 0 (fails)
    adapter.set_selection_highlight([])
    assert "/World/Cube" in adapter._selection_outline_previous_paths, (
        "failed clear must leave the path tracked so it can be retried"
    )

    # Step 3: Deselect again — clear write succeeds and Cube is finally
    # removed from the tracked set.
    renderer.write_outcomes.extend([True])  # retry clear succeeds
    adapter.set_selection_highlight([])
    assert "/World/Cube" not in adapter._selection_outline_previous_paths

    # The write sequence should show: initial set, failed clear attempt
    # (which raised — not recorded), then the successful retry clear.
    assert renderer.write_calls == [
        (["/World/Cube"], "omni:selectionOutlineGroup", [1]),
        (["/World/Cube"], "omni:selectionOutlineGroup", [0]),
    ]
    # Two writes counted: the initial set and the successful retry.
    assert adapter._selection_outline_attribute_writes == 2


def test_two_rapid_picks_do_not_inherit_canceled_hit(monkeypatch):
    """A second click before the next frame must not receive the first click's hit.

    Regression for Codex review of #67 (blocking finding 1): the old
    name-keyed dict made it impossible to distinguish a stale ovrtx
    pick result from the replacement query's result.
    """
    fake_ovrtx = SimpleNamespace()
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    # Click A: callback would, if hit, capture the canceled-query result.
    canceled_results: list = []
    adapter.pick(
        0.0, 0.0,
        lambda path, point: canceled_results.append((path, point)),
        "viewport_click",
    )
    # Click B (rapid, before the next frame): re-issue under same name.
    live_results: list = []
    adapter.pick(
        0.5, 0.5,
        lambda path, point: live_results.append((path, point)),
        "viewport_click",
    )

    # Two enqueues; FIFO has two slots; first slot's callback was nulled
    # in place when the second pick replaced it.
    assert adapter._pick_enqueue_count == 2
    assert len(adapter._in_flight_pick_queries) == 2
    assert adapter._in_flight_pick_queries[0][3] is None
    assert adapter._in_flight_pick_queries[1][3] is not None

    # Stub the hit reader so the first frame returns Cube (what the
    # canceled query would have hit) and the second frame returns
    # Sphere (the live query's actual hit).
    fake_hits = collections.deque([
        [("/World/Cube", (1.0, 2.0, 3.0))],
        [("/World/Sphere", (4.0, 5.0, 6.0))],
    ])

    def _fake_read(_products):
        return fake_hits.popleft() if fake_hits else []

    adapter._read_pick_hits = _fake_read  # type: ignore[assignment]

    # Frame 1: drains the canceled slot — no callback fires.
    adapter._dispatch_pending_pick_results(products=None)
    assert canceled_results == []
    assert live_results == []
    assert len(adapter._in_flight_pick_queries) == 1
    assert adapter._in_flight_pick_queries[0][5] == [
        ("/World/Cube", (1.0, 2.0, 3.0))
    ]

    # Frame 2: drains the live slot with the live query's hit.
    adapter._dispatch_pending_pick_results(products=None)
    assert canceled_results == []
    assert live_results == [("/World/Sphere", (4.0, 5.0, 6.0))]
    assert len(adapter._in_flight_pick_queries) == 0


def test_collapsed_same_render_product_pick_delivers_latest_replacement_hit(monkeypatch):
    """ovrtx 0.3 can collapse rapid same-RenderProduct picks to latest hit.

    Regression for PR #67 Step 6: a rapid replacement pick under the same
    RenderProduct returned the latest hit while the superseded FIFO slot
    was still at the adapter head, then a miss on the live slot. The live
    callback must receive that cached latest hit instead of ``None``.
    """
    fake_ovrtx = SimpleNamespace()
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    canceled_results: list = []
    adapter.pick(
        0.0, 0.0,
        lambda path, point: canceled_results.append((path, point)),
        "viewport_click",
    )
    live_results: list = []
    adapter.pick(
        0.0, 0.0,
        lambda path, point: live_results.append((path, point)),
        "viewport_click",
    )

    assert len(adapter._in_flight_pick_queries) == 2
    assert adapter._in_flight_pick_queries[0][3] is None
    assert adapter._in_flight_pick_queries[0][4] == renderer_mod._PICK_CANCEL_REPLACED
    assert adapter._in_flight_pick_queries[1][3] is not None

    fake_hits = collections.deque([
        [("/World/Sphere", (4.0, 5.0, 6.0))],
        [],
    ])

    def _fake_read(_products):
        return fake_hits.popleft() if fake_hits else []

    adapter._read_pick_hits = _fake_read  # type: ignore[assignment]

    adapter._dispatch_pending_pick_results(products=None)
    assert canceled_results == []
    assert live_results == []
    assert len(adapter._in_flight_pick_queries) == 1
    assert adapter._in_flight_pick_queries[0][5] == [
        ("/World/Sphere", (4.0, 5.0, 6.0))
    ]

    adapter._dispatch_pending_pick_results(products=None)
    assert canceled_results == []
    assert live_results == [("/World/Sphere", (4.0, 5.0, 6.0))]
    assert adapter._last_pick_path == "/World/Sphere"
    assert len(adapter._in_flight_pick_queries) == 0


def test_explicit_cancel_pick_drains_without_dispatch(monkeypatch):
    """``cancel_pick`` nulls the slot but still drains it on the next frame."""
    fake_ovrtx = SimpleNamespace()
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    calls: list = []
    adapter.pick(0.0, 0.0, lambda p, w: calls.append((p, w)), "q")
    adapter.cancel_pick("q")

    assert len(adapter._in_flight_pick_queries) == 1
    assert adapter._in_flight_pick_queries[0][3] is None

    adapter._read_pick_hits = lambda _p: [("/World/Cube", (0.0, 0.0, 0.0))]  # type: ignore[assignment]
    adapter._dispatch_pending_pick_results(products=None)
    assert calls == []
    assert len(adapter._in_flight_pick_queries) == 0


def test_shutdown_dispatches_pending_pick_misses(monkeypatch):
    """Shutdown drains pending pick/rect callbacks so closures are released.

    Regression for Codex review of #67 (non-blocking finding 1).
    """
    fake_ovrtx = SimpleNamespace()
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)
    adapter._livestream = None
    adapter._owned_tmp_path = None

    point_calls: list = []
    rect_calls: list = []
    adapter.pick(0.0, 0.0, lambda p, w: point_calls.append((p, w)), "q")
    adapter.pick_rect(-0.5, -0.5, 0.5, 0.5, lambda paths: rect_calls.append(list(paths)))

    assert len(adapter._in_flight_pick_queries) == 2

    # Stub out the bits of shutdown we don't want to exercise here.
    adapter._remove_ovrtx_layers = lambda: None  # type: ignore[assignment]

    adapter.shutdown()

    assert point_calls == [(None, None)]
    assert rect_calls == [[]]
    assert len(adapter._in_flight_pick_queries) == 0
    assert adapter._renderer is None
    assert adapter._stage is None


class _GatedTensor:
    """Tensor stand-in that only exposes data while its mapping is entered."""

    def __init__(self, data: bytes, gate: dict) -> None:
        self._data = data
        self._gate = gate

    def to_bytes(self) -> bytes:
        if not self._gate.get("entered"):
            raise RuntimeError(
                "tensor.to_bytes() called outside the mapping context"
            )
        return self._data


class _ContextMapping:
    """Render-var mapping that records enter/exit and gates the tensor."""

    def __init__(self, data: bytes) -> None:
        self._gate: dict = {"entered": False}
        self._data = data
        self.events: list[str] = []
        # ``tensor`` only becomes usable inside ``__enter__``; outside the
        # context, ``.to_bytes()`` raises just like a real ovrtx mapping.
        self.tensor = _GatedTensor(self._data, self._gate)

    def __enter__(self) -> "_ContextMapping":
        self._gate["entered"] = True
        self.events.append("enter")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._gate["entered"] = False
        self.events.append("exit")
        return False


class _ContextRV:
    def __init__(self, mapping: _ContextMapping) -> None:
        self._mapping = mapping
        self.map_calls: list[dict] = []

    def map(self, device=None):
        self.map_calls.append({"device": device})
        return self._mapping


class _NamedPickMapping:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.params = {
            "magic": np.array([renderer_mod._PICK_HIT_BUFFER_MAGIC], dtype=np.uint32),
            "version": np.array([renderer_mod._PICK_HIT_BUFFER_VERSION], dtype=np.uint32),
            "hitCount": np.array([1], dtype=np.uint32),
        }
        self._tensors = {
            "primPath": np.array([7], dtype=np.uint64),
            "worldPositionM": np.array([[1.0, 2.0, 3.0]], dtype=np.float64),
        }

    def __enter__(self) -> "_NamedPickMapping":
        self.events.append("enter")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.events.append("exit")
        return False

    def keys(self):
        return self._tensors.keys()

    def __getitem__(self, key: str):
        return self._tensors[key]


def _hit_buffer(prim_path_id: int) -> bytes:
    """Construct a minimal pick-hit buffer matching the adapter's struct."""
    header = renderer_mod._PICK_HIT_HEADER.pack(
        renderer_mod._PICK_HIT_BUFFER_MAGIC,
        renderer_mod._PICK_HIT_BUFFER_VERSION,
        1,
        renderer_mod._PICK_HIT_RECORD.size,
    )
    record = renderer_mod._PICK_HIT_RECORD.pack(
        int(prim_path_id),   # prim_path_id
        0,                   # object_type
        0,                   # pad0
        0,                   # instance_id
        1.0,                 # wx
        2.0,                 # wy
        3.0,                 # wz
        0.0, 0.0, 1.0,       # normal
        0.0,                 # pad1
    )
    return header + record


class _FrameStub:
    def __init__(self, render_vars: dict) -> None:
        self.render_vars = render_vars


class _ProductStub:
    def __init__(self, render_vars: dict) -> None:
        self.frames = [_FrameStub(render_vars)]


class _RootOpenRenderer03:
    """ovrtx 0.3-style renderer exposing only explicit root-open APIs."""

    def __init__(self) -> None:
        self.calls = []
        self.removed = []

    def open_usd_from_file(self, path):
        self.calls.append(("file", path))

    def open_usd_from_string(self, usda):
        self.calls.append(("string", usda))

    def add_usd_reference_from_string(self, usda, prefix_path):
        handle = f"session-{len(self.calls)}"
        self.calls.append(("session-string", prefix_path, usda, handle))
        return handle

    def remove_usd(self, handle):
        self.removed.append(handle)


def _make_load_stage_adapter(renderer) -> OvRtxRendererAdapter:
    adapter = _make_adapter(renderer)
    adapter._usd_handle = None
    adapter._session_handle = None
    adapter._owned_tmp_path = None
    adapter._default_camera_path = renderer_mod._CAMERA_PATH
    adapter._default_render_product_path = renderer_mod._RENDER_PRODUCT_PATH
    adapter._camera_path = renderer_mod._CAMERA_PATH
    adapter._render_product_path = renderer_mod._RENDER_PRODUCT_PATH
    adapter._last_resolution = (320, 180)
    adapter._pending_resolution = (320, 180)
    adapter._scene_has_lights = True
    return adapter


def _pxr_usd_modules():
    pytest.importorskip("pxr")
    from pxr import Usd, UsdGeom

    return Usd, UsdGeom


def test_read_pick_hits_uses_mapping_context_manager(monkeypatch):
    """``_read_pick_hits`` must enter and exit the render-var mapping.

    Regression for Codex re-review of #67: previously the code called
    ``rv.map(...)`` without entering the returned context manager and
    then ``mapping.unmap()`` on exit. Real ovrtx mappings only expose
    ``tensor`` between ``__enter__`` and ``__exit__``, which silently
    drained every pick as a miss.
    """
    # Stand-in for ovrtx that supplies a CPU device and resolves the
    # synthetic prim-path id back to a real path.
    class _PathDict:
        def prim_path_to_string(self, _pid):
            return "/World/Cube"

    fake_renderer = SimpleNamespace(_get_path_dict=lambda: _PathDict())
    fake_ovrtx = SimpleNamespace(
        Device=SimpleNamespace(CPU="cpu"),
        OVRTX_RENDER_VAR_PICK_HIT="pick_hit",
        OVRTX_PICK_HIT_BUFFER_MAGIC=renderer_mod._PICK_HIT_BUFFER_MAGIC,
        OVRTX_PICK_HIT_BUFFER_VERSION=renderer_mod._PICK_HIT_BUFFER_VERSION,
    )
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)

    adapter = _make_adapter(fake_renderer)
    mapping = _ContextMapping(_hit_buffer(prim_path_id=7))
    rv = _ContextRV(mapping)
    products = {adapter._render_product_path: _ProductStub({"pick_hit": rv})}

    hits = adapter._read_pick_hits(products)

    # Map was entered with the CPU device, the tensor was read inside
    # the context, and __exit__ ran after.
    assert rv.map_calls == [{"device": "cpu"}]
    assert mapping.events == ["enter", "exit"]
    assert hits == [("/World/Cube", (1.0, 2.0, 3.0))]


def test_read_pick_hits_does_not_call_unmap_outside_context(monkeypatch):
    """The mapping must release via __exit__ — no bare ``.unmap()`` calls."""

    class _NoUnmapMapping(_ContextMapping):
        def unmap(self):  # pragma: no cover — should never be called
            raise AssertionError(
                "_read_pick_hits must release the mapping via __exit__, "
                "not by calling .unmap() directly"
            )

    class _PathDict:
        def prim_path_to_string(self, _pid):
            return "/World/Cube"

    fake_renderer = SimpleNamespace(_get_path_dict=lambda: _PathDict())
    fake_ovrtx = SimpleNamespace(
        Device=SimpleNamespace(CPU="cpu"),
        OVRTX_RENDER_VAR_PICK_HIT="pick_hit",
        OVRTX_PICK_HIT_BUFFER_MAGIC=renderer_mod._PICK_HIT_BUFFER_MAGIC,
        OVRTX_PICK_HIT_BUFFER_VERSION=renderer_mod._PICK_HIT_BUFFER_VERSION,
    )
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)

    adapter = _make_adapter(fake_renderer)
    mapping = _NoUnmapMapping(_hit_buffer(prim_path_id=1))
    rv = _ContextRV(mapping)
    products = {adapter._render_product_path: _ProductStub({"pick_hit": rv})}

    hits = adapter._read_pick_hits(products)
    assert mapping.events == ["enter", "exit"]
    assert hits == [("/World/Cube", (1.0, 2.0, 3.0))]


def test_read_pick_hits_reads_ovrtx_03_named_tensors(monkeypatch):
    class _Renderer:
        def resolve_prim_path_id(self, _pid):
            return "/World/Cube"

    fake_ovrtx = SimpleNamespace(
        Device=SimpleNamespace(CPU="cpu"),
        OVRTX_RENDER_VAR_PICK_HIT="pick_hit",
        OVRTX_PICK_HIT_MAGIC=renderer_mod._PICK_HIT_BUFFER_MAGIC,
        OVRTX_PICK_HIT_VERSION=renderer_mod._PICK_HIT_BUFFER_VERSION,
    )
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)

    adapter = _make_adapter(_Renderer())
    mapping = _NamedPickMapping()
    rv = _ContextRV(mapping)
    products = {adapter._render_product_path: _ProductStub({"pick_hit": rv})}

    hits = adapter._read_pick_hits(products)

    assert rv.map_calls == [{"device": "cpu"}]
    assert mapping.events == ["enter", "exit"]
    assert hits == [("/World/Cube", (1.0, 2.0, 3.0))]


def test_load_stage_uses_ovrtx_03_file_root_open(tmp_path):
    _pxr_usd_modules()
    scene_path = tmp_path / "scene.usda"
    scene_path.write_text(
        """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
}
""",
        encoding="utf-8",
    )
    renderer = _RootOpenRenderer03()
    adapter = _make_load_stage_adapter(renderer)

    adapter.load_stage(str(scene_path))

    assert renderer.calls[0] == ("file", str(scene_path))
    assert renderer.calls[1][0:2] == ("session-string", renderer_mod._SESSION_ROOT_PATH)
    assert adapter._usd_handle is renderer_mod._ROOT_STAGE_SENTINEL


def test_load_stage_uses_ovrtx_03_string_root_open_for_anonymous_stage():
    Usd, UsdGeom = _pxr_usd_modules()
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    renderer = _RootOpenRenderer03()
    adapter = _make_load_stage_adapter(renderer)

    adapter.load_stage(stage)

    kind, root_usda = renderer.calls[0]
    assert kind == "string"
    assert 'def Xform "World"' in root_usda
    assert renderer.calls[1][0:2] == ("session-string", renderer_mod._SESSION_ROOT_PATH)
    assert adapter._usd_handle is renderer_mod._ROOT_STAGE_SENTINEL
    assert adapter._owned_tmp_path is None


def test_load_stage_drains_pending_picks_from_previous_stage(monkeypatch):
    """Reloading the stage must miss-out pending picks from the prior stage.

    Regression for Codex re-review of #67: ``load_stage`` previously
    swapped renderer state without touching ``_in_flight_pick_queries``,
    so a click queued just before a reload could be dispatched against
    the new stage's products, silently selecting an unrelated prim.
    """
    fake_ovrtx = SimpleNamespace()
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    point_calls: list = []
    rect_calls: list = []
    adapter.pick(0.0, 0.0, lambda p, w: point_calls.append((p, w)), "viewport_click")
    adapter.pick_rect(-0.5, -0.5, 0.5, 0.5, lambda paths: rect_calls.append(list(paths)))
    assert len(adapter._in_flight_pick_queries) == 2

    # Drive only the early part of ``load_stage`` that touches pending
    # picks — the rest needs pxr/ovrtx machinery we don't want to spin
    # up here. The implementation is required to drain pending picks
    # before swapping any state, so calling the documented entry point
    # for that step is enough for the regression.
    adapter._dispatch_pending_pick_misses()

    # Pending callbacks fired exactly once with a miss; the FIFO is
    # empty and a follow-up dispatch (simulating a render on the newly
    # loaded stage) does nothing.
    assert point_calls == [(None, None)]
    assert rect_calls == [[]]
    assert len(adapter._in_flight_pick_queries) == 0

    adapter._read_pick_hits = lambda _p: [("/World/Sphere", (9.0, 9.0, 9.0))]  # type: ignore[assignment]
    adapter._dispatch_pending_pick_results(products=None)
    assert point_calls == [(None, None)]  # no second dispatch
    assert rect_calls == [[]]


def test_load_stage_calls_dispatch_pending_pick_misses_first(monkeypatch):
    """``load_stage`` must call ``_dispatch_pending_pick_misses`` up front.

    Source-level check so the contract is locked in even if a future
    refactor reshapes the body — the drain has to happen before any
    state swap to be effective.
    """
    source = inspect.getsource(OvRtxRendererAdapter.load_stage)
    # Drain call must appear before any renderer/stage mutation. Match
    # the literal call, then assert it occurs ahead of the first
    # renderer-state mutation we want to guard against.
    drain_idx = source.find("self._dispatch_pending_pick_misses()")
    teardown_idx = source.find("self._remove_ovrtx_layers()")
    add_usd_idx = source.find("self._renderer.add_usd(")
    assert drain_idx != -1, "load_stage must drain pending picks"
    assert teardown_idx == -1 or drain_idx < teardown_idx
    assert add_usd_idx == -1 or drain_idx < add_usd_idx


def test_viewport_widget_no_longer_constructs_selection_outline_manipulator():
    import ovwidgets.viewport.viewport_widget as viewport_widget

    assert not hasattr(viewport_widget, "SelectionOutlineManipulator")
    source = inspect.getsource(viewport_widget.ViewportWidget._build_ui)
    assert "SelectionOutlineManipulator" not in source


class _SyncPickRenderer(MockRendererAdapter):
    def pick(self, x, y, callback, query_name):
        callback("/World/Cube", (0.0, 0.0, 0.0))


def test_viewport_pick_still_publishes_through_selection_bus():
    bus = SelectionBus()
    viewport = ViewportWidget(services=None, renderer=_SyncPickRenderer(), bus=bus)
    try:
        viewport._on_pick(0.0, 0.0, "replace")
        assert bus.get_snapshot().paths() == ["/World/Cube"]
    finally:
        viewport.destroy()
