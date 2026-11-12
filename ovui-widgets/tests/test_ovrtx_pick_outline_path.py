# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for ovrtx-backed viewport pick and selection outlines."""

from __future__ import annotations

import collections
import glob as _glob
import inspect
import os as _os
import tempfile as _tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from ovui_data_adapters.common import ChangeEvent, ChangeEventType
from ovui_data_adapters.openusd import renderer_adapter as renderer_mod
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter

from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_renderer import MockRendererAdapter
from ovui_widgets.viewport.viewport_widget import ViewportWidget


def _live_snapshot_files() -> set:
    """Both live-root snapshot patterns: the visible tempdir-fallback form and
    the dot-prefixed form written beside a writable root (``glob`` skips the
    leading dot, so it is enumerated explicitly)."""
    tmp = _tempfile.gettempdir()
    return set(
        _glob.glob(_os.path.join(tmp, "*ovui_widgets_live_*"))
    ) | set(
        _glob.glob(_os.path.join(tmp, ".ovui_widgets_live_*"))
    )


@pytest.fixture(autouse=True)
def _no_snapshot_residue():
    """Reclaim any live-root snapshot a bare-adapter ``load_stage`` test writes
    without a full ``shutdown`` teardown, so the suite leaves zero net
    snapshot residue (visible and dot-prefixed)."""
    before = _live_snapshot_files()
    yield
    for path in _live_snapshot_files() - before:
        try:
            _os.unlink(path)
        except OSError:
            pass


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
    adapter._selection_outline_generation = 0
    adapter._selection_outline_last_write = {}
    adapter._in_flight_pick_queries = collections.deque()
    adapter._pick_seq = 0
    adapter._pick_enqueue_count = 0
    adapter._pick_result_count = 0
    adapter._last_pick_pixel_rect = None
    adapter._last_pick_path = None
    adapter._last_pick_world_point = None
    adapter._last_render_product_resolution = None
    adapter._ovrtx_version = (0, 4, 0)
    return adapter


def test_pick_uses_ovrtx_enqueue_pick_query(monkeypatch):
    fake_ovrtx = SimpleNamespace()
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    callbacks = []
    adapter.pick(0.0, 0.0, lambda path, point: callbacks.append((path, point)), "q")

    args, kwargs = renderer.enqueue_calls[0]
    assert args[0] == "/OvGearSession/Render/Viewport"
    assert args[1:] == pytest.approx((50 / 101, 50 / 101, 51 / 101, 51 / 101))
    assert kwargs == {}
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


def test_pick_uses_active_render_product_resolution(monkeypatch):
    class _Stage:
        def GetPrimAtPath(self, path):
            assert path == "/Render/Products/MainCamera"
            return object()

    class _Attr:
        def Get(self):
            return (1280, 720)

    class _Product:
        def GetResolutionAttr(self):
            return _Attr()

    monkeypatch.setattr(renderer_mod, "_usd_render_product", lambda _prim: _Product())
    fake_ovrtx = SimpleNamespace()
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)
    adapter._stage = _Stage()
    adapter._render_product_path = "/Render/Products/MainCamera"
    adapter._last_resolution = (730, 377)
    adapter._pending_resolution = (730, 377)

    adapter.pick(0.0, 0.0, lambda _path, _point: None, "q")

    args, kwargs = renderer.enqueue_calls[0]
    assert args[0] == "/Render/Products/MainCamera"
    assert args[1:] == pytest.approx((0.5, 0.5, 641 / 1280, 361 / 720))
    assert kwargs == {}
    assert adapter._last_pick_pixel_rect == (640, 360, 641, 361)


def test_pick_keeps_pixel_rectangle_for_legacy_ovrtx(monkeypatch):
    fake_ovrtx = SimpleNamespace()
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)
    adapter._ovrtx_version = (0, 3, 0)

    adapter.pick(0.0, 0.0, lambda _path, _point: None, "q")

    assert renderer.enqueue_calls == [
        (("/OvGearSession/Render/Viewport", 50, 50, 51, 51), {})
    ]


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


class _FakeOutlineOperation:
    """Mimics ovrtx ``Operation`` completion semantics for outline writes.

    ``wait()`` returns ``True`` (void-op success), returns ``None`` (timeout),
    or raises ``RuntimeError`` (completion failure) — the three real
    outcomes. A write that is not waited on (or whose completion is not
    validated) would be treated as applied and never retried, so the retry
    sequences below are the consumption proof.
    """

    def __init__(self, outcome=True):
        self.outcome = outcome

    def wait(self, timeout_ns=None):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _FakeAsyncOnlyRenderer(_FakeRenderer):
    """Hypothetical runtime exposing only the async string membership API.

    The INSTALLED ovrtx 0.4.0 wheel exposes neither string variant; its
    surface (style APIs plus ``write_attribute`` of the reserved
    ``omni:selectionOutlineGroup`` attribute) is the base ``_FakeRenderer``
    and is covered by the attribute-transport tests above.  This subclass
    verifies the precedence and completion-validation bookkeeping the
    adapter must keep for runtimes that do ship the dedicated API.
    """

    def __init__(self) -> None:
        super().__init__()
        self.outline_group_calls = []
        self.outline_operations = []
        # Head of this deque is the next operation outcome: ``True`` for
        # success, ``None`` for timeout, an Exception instance for a
        # completion failure. Falls back to success when empty.
        self.outline_group_outcomes: collections.deque = collections.deque()

    def set_selection_outline_group_strings_async(self, prim_paths, group_ids):
        outcome = (
            self.outline_group_outcomes.popleft()
            if self.outline_group_outcomes
            else True
        )
        self.outline_group_calls.append((list(prim_paths), group_ids))
        operation = _FakeOutlineOperation(outcome)
        self.outline_operations.append(operation)
        return operation


class _FakeModernRenderer(_FakeAsyncOnlyRenderer):
    """Hypothetical runtime shipping both string variants of the API.

    NOT the installed ovrtx 0.4.0 wheel (which ships neither variant).
    The blocking string variant wraps
    ``set_selection_outline_group_strings_async(...).wait()``, so completion
    failures surface as exceptions from the blocking call.
    """

    def set_selection_outline_group_strings(self, prim_paths, group_ids):
        # Real ovrtx: ``self.set_selection_outline_group_strings_async(...).wait()``.
        self.set_selection_outline_group_strings_async(prim_paths, group_ids).wait()


def test_selection_highlight_uses_modern_outline_group_api(monkeypatch):
    """A dedicated membership API takes precedence over attribute writes.

    On a runtime that exposes the string membership API, outline groups
    must flow through it rather than the attribute write, so a runtime
    that stops honoring attribute-driven membership still outlines.  (The
    installed ovrtx 0.4.0 wheel exposes no string API; there the reserved
    ``omni:selectionOutlineGroup`` attribute write IS the documented
    transport, covered by the ``_FakeRenderer`` attribute tests.)
    """
    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeModernRenderer()
    adapter = _make_adapter(renderer)

    adapter.set_selection_highlight(["/World/BlueSphere"])
    adapter.set_selection_highlight(["/World/GreenCone"])
    adapter.set_selection_highlight([])

    assert renderer.outline_group_calls == [
        (["/World/BlueSphere"], 1),
        (["/World/BlueSphere"], 0),
        (["/World/GreenCone"], 1),
        (["/World/GreenCone"], 0),
    ]
    # The legacy attribute write must not be the outline transport here.
    assert renderer.write_calls == []


def test_selection_highlight_failed_writes_are_reissued(monkeypatch):
    """Failed outline writes stay retryable instead of caching success.

    A raise at enqueue time and a completion failure both surface from the
    blocking transport as the same exception, so one failure shape covers
    the branch; a cached false success would suppress every future rewrite
    of the same path (set: prim permanently un-outlined; clear: stale
    outline never removed).
    """
    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeModernRenderer()
    adapter = _make_adapter(renderer)

    renderer.outline_group_outcomes.append(
        RuntimeError("simulated completion failure")
    )
    adapter.set_selection_highlight(["/World/Cube"])  # set fails
    adapter.set_selection_highlight(["/World/Cube"])  # retried set applies

    renderer.outline_group_outcomes.append(
        RuntimeError("simulated completion failure")
    )
    adapter.set_selection_highlight([])               # clear fails
    adapter.set_selection_highlight([])               # retried clear applies

    assert renderer.outline_group_calls == [
        (["/World/Cube"], 1),
        (["/World/Cube"], 1),
        (["/World/Cube"], 0),
        (["/World/Cube"], 0),
    ]


def test_selection_highlight_async_only_runtime_waits_explicitly(monkeypatch):
    """On an async-only runtime the adapter must consume completion itself.

    An abandoned ovrtx Operation blocks inside ``__del__`` with a
    ResourceWarning and swallows completion errors there; a timeout-shaped
    ``None`` result is a failure, not a success — both must leave the write
    retryable.
    """
    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeAsyncOnlyRenderer()
    adapter = _make_adapter(renderer)

    adapter.set_selection_highlight(["/World/Cube"])
    assert renderer.outline_group_calls == [(["/World/Cube"], 1)]

    renderer.outline_group_outcomes.append(None)  # timeout-shaped completion
    adapter.set_selection_highlight([])           # clear not applied

    # The retried clear proves the adapter consumed and validated the
    # completion: an unwaited or unvalidated operation would have been
    # cached as applied and never re-issued.
    adapter.set_selection_highlight([])
    assert renderer.outline_group_calls == [
        (["/World/Cube"], 1),
        (["/World/Cube"], 0),
        (["/World/Cube"], 0),
    ]


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


def test_selection_highlight_force_reapply_rewrites_tracked_path(monkeypatch):
    """Forced reapply rewrites selection after renderer overlay replacement."""
    fake_ovrtx = SimpleNamespace(
        OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP="omni:selectionOutlineGroup",
        SelectionGroupStyle=_SelectionGroupStyle,
    )
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    adapter.set_selection_highlight(["/World/Cube"])
    renderer.write_calls.clear()
    adapter._mark_selection_outline_state_stale(
        reason="live_resync_overlay",
        reset_previous=False,
        reset_styles=True,
    )

    adapter.set_selection_highlight(["/World/Cube"], force_reapply=True)

    assert renderer.write_calls == [
        (["/World/Cube"], "omni:selectionOutlineGroup", [1]),
    ]
    assert adapter._selection_outline_previous_paths == {"/World/Cube"}
    assert adapter._selection_outline_last_write == {
        "requested_paths": ["/World/Cube"],
        "applied_paths": ["/World/Cube"],
        "to_clear": [],
        "to_set": ["/World/Cube"],
        "failed_clear": [],
        "failed_set": [],
        "clear_success": True,
        "set_success": True,
        "force_reapply": True,
        "generation": 1,
        "stale_reason": "live_resync_overlay",
    }


def test_refresh_selection_highlight_rewrites_unchanged_selected_paths(monkeypatch):
    """Created prims selected before renderer reload need a forced outline write."""
    fake_ovrtx = SimpleNamespace(
        OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP="omni:selectionOutlineGroup",
        SelectionGroupStyle=_SelectionGroupStyle,
    )
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    adapter.set_selection_highlight(["/World/Torus"])
    adapter.refresh_selection_highlight(["/World/Torus"])

    assert renderer.write_calls == [
        (["/World/Torus"], "omni:selectionOutlineGroup", [1]),
        (["/World/Torus"], "omni:selectionOutlineGroup", [1]),
    ]
    assert adapter._selection_outline_previous_paths == {"/World/Torus"}
    assert adapter._selection_outline_attribute_writes == 2


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


def test_selection_highlight_force_reapply_failed_set_is_retryable(monkeypatch):
    """A failed forced set must not keep claiming the outline is visible."""
    fake_ovrtx = SimpleNamespace(
        OVRTX_ATTR_NAME_SELECTION_OUTLINE_GROUP="omni:selectionOutlineGroup",
        SelectionGroupStyle=_SelectionGroupStyle,
    )
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeRenderer()
    adapter = _make_adapter(renderer)

    adapter.set_selection_highlight(["/World/Cube"])
    renderer.write_calls.clear()
    renderer.write_outcomes.extend([False])
    adapter._mark_selection_outline_state_stale(
        reason="live_resync_overlay",
        reset_previous=False,
        reset_styles=True,
    )

    adapter.set_selection_highlight(["/World/Cube"], force_reapply=True)

    assert renderer.write_calls == []
    assert "/World/Cube" not in adapter._selection_outline_previous_paths
    assert adapter._selection_outline_last_write["failed_set"] == ["/World/Cube"]
    assert adapter._selection_outline_last_write["set_success"] is False
    assert adapter._selection_outline_last_write["force_reapply"] is True

    renderer.write_outcomes.extend([True])
    adapter.set_selection_highlight(["/World/Cube"])

    assert renderer.write_calls == [
        (["/World/Cube"], "omni:selectionOutlineGroup", [1]),
    ]
    assert adapter._selection_outline_previous_paths == {"/World/Cube"}


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

    Regression: a rapid replacement pick under the same
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
    def _remove_layers(**_kwargs) -> None:
        # This pick-only fixture has no native teardown API. Model a proven
        # teardown by clearing the synthetic ownership tokens explicitly.
        adapter._usd_handle = None
        adapter._session_handle = None
        adapter._live_resync_handles = []

    adapter._remove_ovrtx_layers = _remove_layers  # type: ignore[assignment]

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


class _FinishedStep:
    """An ovrtx step operation that is already done, with no render products."""

    def wait(self, timeout_ns=None):
        return self

    def fetch(self, timeout_ns=None):
        return {}


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


def test_prim_resync_reloads_ovrtx_from_live_root_snapshot(tmp_path):
    Usd, UsdGeom = _pxr_usd_modules()
    scene_path = tmp_path / "scene.usda"
    stage = Usd.Stage.CreateNew(str(scene_path))
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdGeom.Cube.Define(stage, "/World/OldCube")
    stage.GetRootLayer().Save()

    renderer = _RootOpenRenderer03()
    adapter = _make_load_stage_adapter(renderer)
    adapter.load_stage(stage)
    renderer.calls.clear()

    # A prim of the opened root is removed: the root is opened again.
    stage.RemovePrim("/World/OldCube")
    assert "OldCube" in scene_path.read_text(encoding="utf-8")

    adapter.notify_stage_changed(ChangeEvent(
        changed_paths=(),
        resynced_paths=("/World/OldCube",),
        event_type=ChangeEventType.RESYNC,
    ))

    assert renderer.calls[0][0] == "file"
    snapshot_path = renderer.calls[0][1]
    assert snapshot_path != str(scene_path)
    assert snapshot_path.startswith(str(tmp_path))
    assert "OldCube" not in open(snapshot_path, encoding="utf-8").read()
    assert renderer.calls[1][0:2] == ("session-string", renderer_mod._SESSION_ROOT_PATH)
    assert "FallbackDome" in renderer.calls[1][2]
    assert adapter._owned_tmp_path == snapshot_path


def _loaded_scene_for_created_prims(tmp_path, renderer=None):
    """A saved scene with /World, /World/OldCube and /World/Looks/Material, loaded."""
    Usd, UsdGeom = _pxr_usd_modules()
    from pxr import UsdShade

    scene_path = tmp_path / "scene.usda"
    stage = Usd.Stage.CreateNew(str(scene_path))
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdGeom.Cube.Define(stage, "/World/OldCube")
    UsdShade.Material.Define(stage, "/World/Looks/Material")
    stage.GetRootLayer().Save()
    renderer = renderer or _RootOpenRenderer03()
    adapter = _make_load_stage_adapter(renderer)
    adapter._latest_point_cloud_frames = {}  # set by the constructor of the real adapter
    adapter.load_stage(stage)
    renderer.calls.clear()
    return scene_path, stage, renderer, adapter


def _resync(adapter, prim_path, *changed):
    adapter.notify_stage_changed(ChangeEvent(
        changed_paths=tuple(changed),
        resynced_paths=(prim_path,),
        event_type=ChangeEventType.RESYNC,
    ))


def _reference_layer(usda):
    from pxr import Sdf

    layer = Sdf.Layer.CreateAnonymous(".usda")
    assert layer.ImportFromString(usda)
    return layer


def test_created_prim_goes_to_ovrtx_as_a_reference_and_undo_removes_it(tmp_path):
    # Each root open makes ovrtx keep more memory, so a created
    # prim and its removal do not open the root again.
    _Usd, UsdGeom = _pxr_usd_modules()
    scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)

    UsdGeom.Cube.Define(stage, "/World/NewCube").GetSizeAttr().Set(5.0)
    _resync(adapter, "/World/NewCube", "/World/NewCube.size")

    assert [call[0:2] for call in renderer.calls] == [("session-string", "/World/NewCube")]
    reference = _reference_layer(renderer.calls[0][2])
    assert reference.defaultPrim == "NewCube"
    assert reference.GetPrimAtPath("/NewCube").typeName == "Cube"
    assert reference.GetAttributeAtPath("/NewCube.size").default == 5.0
    assert adapter._owned_tmp_path is None
    assert "NewCube" not in scene_path.read_text(encoding="utf-8")

    # Undo of the create removes the reference, and the root stays open.
    stage.RemovePrim("/World/NewCube")
    _resync(adapter, "/World/NewCube", "/World/NewCube.size")

    assert renderer.removed == [renderer.calls[0][3]]
    assert len(renderer.calls) == 1
    assert adapter._owned_tmp_path is None


def test_edit_of_a_created_prim_replaces_its_reference(tmp_path):
    from pxr import Sdf

    _Usd, UsdGeom = _pxr_usd_modules()
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)
    UsdGeom.Cube.Define(stage, "/World/NewCube")
    _resync(adapter, "/World/NewCube")
    first_handle = renderer.calls[0][3]

    # A property that ovrtx does not take as a live write.
    stage.GetPrimAtPath("/World/NewCube").CreateAttribute(
        "note", Sdf.ValueTypeNames.String
    ).Set("edited")
    _resync(adapter, "/World/NewCube.note")

    assert renderer.removed == [first_handle]
    assert [call[0:2] for call in renderer.calls] == [
        ("session-string", "/World/NewCube"),
        ("session-string", "/World/NewCube"),
    ]
    assert _reference_layer(renderer.calls[1][2]).GetAttributeAtPath(
        "/NewCube.note"
    ).default == "edited"
    assert adapter._owned_tmp_path is None


def test_resync_of_a_prim_of_the_opened_root_reloads_the_root(tmp_path):
    # ovrtx already has this prim from the root that it opened.
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)
    stage.DefinePrim("/World/OldCube", "Sphere")
    _resync(adapter, "/World/OldCube")

    assert renderer.calls[0][0] == "file"
    assert not [call for call in renderer.calls if call[0:2] == ("session-string", "/World/OldCube")]
    assert adapter._live_prim_reference_paths == []


@pytest.mark.parametrize("case", ["outside_target", "reference_arc", "session_opinion", "variant_set"])
def test_created_prim_that_the_root_layer_alone_cannot_give_reloads_the_root(tmp_path, case):
    # A copy of the root layer specs of the prim would show it wrong; the
    # root opens again with the prim, as before.
    from pxr import Sdf, UsdShade

    Usd, UsdGeom = _pxr_usd_modules()
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)
    prim = UsdGeom.Xform.Define(stage, "/World/NewXform").GetPrim()
    if case == "outside_target":
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(
            UsdShade.Material(stage.GetPrimAtPath("/World/Looks/Material"))
        )
    elif case == "reference_arc":
        other = tmp_path / "other.usda"
        other_stage = Usd.Stage.CreateNew(str(other))
        other_stage.SetDefaultPrim(UsdGeom.Xform.Define(other_stage, "/Other").GetPrim())
        other_stage.GetRootLayer().Save()
        prim.GetReferences().AddReference(str(other))
    elif case == "session_opinion":
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            prim.CreateAttribute("note", Sdf.ValueTypeNames.String).Set("session")
    else:
        prim.GetVariantSets().AddVariantSet("look").AddVariant("red")
    _resync(adapter, "/World/NewXform")

    assert renderer.calls[0][0] == "file"
    assert not [call for call in renderer.calls if call[0:2] == ("session-string", "/World/NewXform")]
    assert adapter._live_prim_reference_paths == []


def test_layer_metadata_change_reloads_the_root(tmp_path):
    # The default prim is metadata of the root layer, which only a reload gives to ovrtx.
    _Usd, UsdGeom = _pxr_usd_modules()
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)
    UsdGeom.Xform.Define(stage, "/World/NewXform")
    _resync(adapter, "/World/NewXform")
    renderer.calls.clear()

    stage.SetDefaultPrim(stage.GetPrimAtPath("/World/NewXform"))
    adapter.notify_stage_changed(ChangeEvent(
        changed_paths=("/World/NewXform",),
        resynced_paths=(),
        event_type=ChangeEventType.LAYER_INFO,
    ))

    assert renderer.calls[0][0] == "file"
    assert adapter._live_prim_reference_paths == []


def test_created_prim_reference_keeps_asset_paths_and_time_codes(tmp_path):
    from pxr import Sdf

    _Usd, UsdGeom = _pxr_usd_modules()
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)
    stage.GetRootLayer().timeCodesPerSecond = 30.0
    renderer.calls.clear()  # the layer metadata change itself is not under test
    prim = UsdGeom.Cube.Define(stage, "/World/NewCube").GetPrim()
    prim.CreateAttribute("texture", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath("./tex.png"))
    prim.CreateAttribute("weight", Sdf.ValueTypeNames.Float).Set(2.0, 10.0)
    _resync(adapter, "/World/NewCube")

    assert [call[0:2] for call in renderer.calls] == [("session-string", "/World/NewCube")]
    reference = _reference_layer(renderer.calls[0][2])
    # The copy is not beside the root layer, so a relative path resolves as from the root layer.
    # USD writes the path with forward slashes also on Windows; Path compares the two forms as one path.
    anchored = reference.GetAttributeAtPath("/NewCube.texture").default.path
    assert _os.path.isabs(anchored)
    assert Path(anchored) == tmp_path / "tex.png"
    # Time samples map to the same stage time as in the root layer.
    assert reference.timeCodesPerSecond == 30.0
    assert reference.QueryTimeSample("/NewCube.weight", 10.0) == 2.0


def test_renderer_with_root_layer_overlays_keeps_the_path_of_main(tmp_path):
    # A renderer that has add_usd_layer gets a created prim as on main (here a
    # reload, for a property that ovrtx cannot take live), not as a reference
    # of the prim alone.
    class _OverlayRenderer(_RootOpenRenderer03):
        def __init__(self):
            super().__init__()
            self.opened_texts = []

        def open_usd_from_file(self, path):
            super().open_usd_from_file(path)
            with open(path, encoding="utf-8") as stream:
                self.opened_texts.append(stream.read())

        def add_usd_layer(self, usda, path_prefix=None):
            handle = f"overlay-{len(self.calls)}"
            self.calls.append(("overlay", path_prefix, usda, handle))
            return handle

    from pxr import Sdf

    _Usd, UsdGeom = _pxr_usd_modules()
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(
        tmp_path, _OverlayRenderer()
    )
    cube = UsdGeom.Cube.Define(stage, "/World/NewCube")
    cube.GetSizeAttr().Set(3.0)
    cube.GetPrim().CreateAttribute("note", Sdf.ValueTypeNames.String).Set("x")
    renderer.opened_texts.clear()
    _resync(adapter, "/World/NewCube", "/World/NewCube.note")

    assert not [call for call in renderer.calls if call[0:2] == ("session-string", "/World/NewCube")]
    assert adapter._live_prim_reference_paths == []
    # The scene reloads, and the root that the renderer opens has the Cube with its size.
    assert [call[0] for call in renderer.calls][:1] == ["file"]
    reopened = _reference_layer(renderer.opened_texts[0])
    assert reopened.GetPrimAtPath("/World/NewCube").typeName == "Cube"
    assert reopened.GetAttributeAtPath("/World/NewCube.size").default == 3.0


def test_failed_reload_restores_the_created_prim_references(tmp_path):
    # When a later reopen fails, the previous native scene comes back, with
    # the created prims that it showed.
    class _FailingSnapshotRenderer(_RootOpenRenderer03):
        allowed_path = None

        def open_usd_from_file(self, path):
            if self.allowed_path is not None and path != self.allowed_path:
                raise RuntimeError(f"native root open failed: {path}")
            super().open_usd_from_file(path)

    _Usd, UsdGeom = _pxr_usd_modules()
    scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(
        tmp_path, _FailingSnapshotRenderer()
    )
    UsdGeom.Cube.Define(stage, "/World/NewCube")
    _resync(adapter, "/World/NewCube")
    UsdGeom.Xform.Define(stage, "/World/NewXform")
    _resync(adapter, "/World/NewXform")
    renderer.calls.clear()

    renderer.allowed_path = str(scene_path)
    stage.RemovePrim("/World/OldCube")
    _resync(adapter, "/World/OldCube")

    assert ("file", str(scene_path)) in [call[0:2] for call in renderer.calls]
    assert [call[0:2] for call in renderer.calls if call[1] == "/World/NewCube"] == [
        ("session-string", "/World/NewCube")
    ]
    assert [str(path) for path in adapter._live_prim_reference_paths] == ["/World/NewCube"]
    assert not [call for call in renderer.calls if call[1] == "/World/NewXform"]
    assert [str(path) for path in adapter._undrawn_created_prim_paths] == ["/World/NewXform"]


def test_created_prim_that_draws_nothing_stays_out_of_ovrtx_and_keeps_the_picture(tmp_path):
    # ovrtx keeps memory on each render step, and the viewport renders after
    # each change it is told about; an Xform draws nothing.
    _Usd, UsdGeom = _pxr_usd_modules()
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)
    created = ChangeEvent(changed_paths=(), resynced_paths=("/World/NewXform",), event_type=ChangeEventType.RESYNC)

    UsdGeom.Xform.Define(stage, "/World/NewXform")
    adapter._still_frame_requested = False
    assert adapter.stage_change_keeps_picture(created) is True
    adapter.notify_stage_changed(created)
    assert renderer.calls == [] and renderer.removed == []
    # The adapter does not ask itself for a step either.
    assert adapter._still_frame_requested is False

    # An edit of the Xform, and its removal (Undo of Create > Xform), keep the picture too.
    UsdGeom.Xform(stage.GetPrimAtPath("/World/NewXform")).AddTranslateOp().Set((1.0, 2.0, 3.0))
    moved = ChangeEvent(
        changed_paths=("/World/NewXform.xformOp:translate", "/World/NewXform.xformOpOrder"),
        resynced_paths=(),
        event_type=ChangeEventType.INFO_CHANGE,
    )
    assert adapter.stage_change_keeps_picture(moved) is True
    adapter.notify_stage_changed(moved)
    stage.RemovePrim("/World/NewXform")
    assert adapter.stage_change_keeps_picture(created) is True
    adapter.notify_stage_changed(created)
    assert renderer.calls == [] and renderer.removed == []
    assert adapter._undrawn_created_prim_paths == []
    assert adapter._owned_tmp_path is None
    assert adapter._still_frame_requested is False


def test_shape_under_a_created_xform_takes_the_xform_to_ovrtx(tmp_path):
    _Usd, UsdGeom = _pxr_usd_modules()
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)
    UsdGeom.Xform.Define(stage, "/World/NewXform")
    _resync(adapter, "/World/NewXform")

    UsdGeom.Sphere.Define(stage, "/World/NewXform/Ball")
    added = ChangeEvent(changed_paths=(), resynced_paths=("/World/NewXform/Ball",), event_type=ChangeEventType.RESYNC)
    assert adapter.stage_change_keeps_picture(added) is False
    adapter.notify_stage_changed(added)

    assert [call[0:2] for call in renderer.calls] == [("session-string", "/World/NewXform")]
    assert _reference_layer(renderer.calls[0][2]).GetPrimAtPath("/NewXform/Ball").typeName == "Sphere"
    assert adapter._undrawn_created_prim_paths == []

    # Without the Sphere the Xform draws nothing again: its reference goes away.
    stage.RemovePrim("/World/NewXform/Ball")
    assert adapter.stage_change_keeps_picture(added) is False
    adapter.notify_stage_changed(added)
    assert renderer.removed == [renderer.calls[0][3]]
    assert len(renderer.calls) == 1
    assert [str(path) for path in adapter._undrawn_created_prim_paths] == ["/World/NewXform"]


def test_undo_of_a_live_edit_of_a_created_shape_is_written_and_rendered(tmp_path, monkeypatch):
    # A committed Translate of a created Cube goes to ovrtx as a live write,
    # not in the text of its reference. Its Undo makes the specs equal to that
    # text again, but ovrtx still has the edited value: the Undo must be
    # written to ovrtx and rendered, as on a prim of the opened file.
    _Usd, UsdGeom = _pxr_usd_modules()
    renderer = _RootOpenRenderer03()
    renderer.write_attribute = lambda *args, **kwargs: renderer.calls.append(
        ("write_attribute", args, kwargs)
    )
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path, renderer)
    monkeypatch.setattr(
        renderer_mod, "_ovrtx",
        SimpleNamespace(Semantic=SimpleNamespace(XFORM_MAT4x4="matrix")),
    )
    translate = UsdGeom.Cube.Define(stage, "/World/NewCube").AddTranslateOp()
    translate.Set((0.0, 0.0, 50.0))
    _resync(adapter, "/World/NewCube", "/World/NewCube.xformOp:translate", "/World/NewCube.xformOpOrder")
    assert [call[0:2] for call in renderer.calls] == [("session-string", "/World/NewCube")]

    def moved():
        # Each change of the stage is a new event, as in the app.
        return ChangeEvent(
            changed_paths=("/World/NewCube.xformOp:translate",),
            resynced_paths=(),
            event_type=ChangeEventType.INFO_CHANGE,
        )

    def last_written_translate():
        writes = [call for call in renderer.calls if call[0] == "write_attribute"]
        assert writes and writes[-1][2]["prim_paths"] == ["/World/NewCube"]
        return tuple(writes[-1][2]["tensor"][0, 3, :3])

    translate.Set((150.0, 0.0, 50.0))
    edit = moved()
    assert adapter.stage_change_keeps_picture(edit) is False
    adapter.notify_stage_changed(edit)
    assert np.allclose(last_written_translate(), (150.0, 0.0, 50.0))
    assert len([call for call in renderer.calls if call[0] == "session-string"]) == 1

    # Undo: the specs are again those of the reference text.
    translate.Set((0.0, 0.0, 50.0))
    adapter._still_frame_requested = False
    undo = moved()
    assert adapter.stage_change_keeps_picture(undo) is False
    adapter.notify_stage_changed(undo)
    assert np.allclose(last_written_translate(), (0.0, 0.0, 50.0))
    assert adapter._still_frame_requested is True


def test_a_failed_created_prim_step_is_reported_once_and_the_scene_reloads(tmp_path, monkeypatch, capsys):
    # The viewport asks stage_change_keeps_picture and then gives the same
    # change to notify_stage_changed. A failure of the created-prim step is
    # reported once, with its cause, and the scene reloads with the prim.
    from pxr import Sdf

    _Usd, UsdGeom = _pxr_usd_modules()
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)
    copy_spec = Sdf.CopySpec

    def copy_spec_that_fails_for_the_cube(source_layer, source_path, target_layer, target_path, *args):
        if str(source_path) == "/World/NewCube" and str(target_path) == "/NewCube":
            raise RuntimeError("the copy failed")
        return copy_spec(source_layer, source_path, target_layer, target_path, *args)

    monkeypatch.setattr(Sdf, "CopySpec", copy_spec_that_fails_for_the_cube)
    UsdGeom.Cube.Define(stage, "/World/NewCube")
    capsys.readouterr()
    created = ChangeEvent(changed_paths=(), resynced_paths=("/World/NewCube",), event_type=ChangeEventType.RESYNC)

    assert adapter.stage_change_keeps_picture(created) is False
    adapter.notify_stage_changed(created)

    reports = [line for line in capsys.readouterr().err.splitlines() if "created prims" in line]
    assert len(reports) == 1, reports
    assert "cannot prepare" in reports[0] and "RuntimeError: the copy failed" in reports[0]
    assert not [call for call in renderer.calls if call[0:2] == ("session-string", "/World/NewCube")]
    assert renderer.calls[0][0] == "file"
    with open(renderer.calls[0][1], encoding="utf-8") as reopened:
        assert 'def Cube "NewCube"' in reopened.read()


def test_a_failed_prim_lookup_for_the_outline_is_reported_and_the_outline_is_written(monkeypatch, capsys):
    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeResettableRenderer()
    adapter = _make_adapter(renderer)

    def failing_lookup(path):
        raise RuntimeError("the stage is closed")

    adapter._stage = SimpleNamespace(GetPrimAtPath=failing_lookup)
    capsys.readouterr()

    assert adapter.set_selection_highlight(["/World/Cube"]) is True
    assert renderer.outline_group_calls
    err = capsys.readouterr().err
    assert "cannot look up '/World/Cube' in the stage for the selection outline" in err
    assert "RuntimeError: the stage is closed" in err


def test_first_create_on_a_new_stage_sends_the_new_parent_with_the_prim(tmp_path):
    # Create > Mesh > Torus on a stage without /World (File > New) makes /World
    # and /World/Torus. The first change names only /World/Torus, the next one
    # /World too. ovrtx adds a missing parent of a reference itself and then
    # refuses a reference at that parent, so /World goes with the Torus.
    Usd, UsdGeom = _pxr_usd_modules()
    stage = Usd.Stage.CreateNew(str(tmp_path / "NewStage.usda"))
    renderer = _RootOpenRenderer03()
    adapter = _make_load_stage_adapter(renderer)
    adapter._latest_point_cloud_frames = {}
    adapter.load_stage(stage)
    renderer.calls.clear()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Mesh.Define(stage, "/World/Torus")

    _resync(adapter, "/World/Torus")
    assert [call[0:2] for call in renderer.calls] == [("session-string", "/World")]
    assert _reference_layer(renderer.calls[0][2]).GetPrimAtPath("/World/Torus").typeName == "Mesh"

    adapter.notify_stage_changed(ChangeEvent(
        changed_paths=("/World/Torus.points",),
        resynced_paths=("/World", "/World/Torus"),
        event_type=ChangeEventType.RESYNC,
    ))
    assert [call[0] for call in renderer.calls if call[0] in ("file", "string")] == []
    assert not [call for call in renderer.calls if call[0:2] == ("session-string", "/World/Torus")]
    assert [str(path) for path in adapter._live_prim_reference_paths] == ["/World"]


def test_created_prim_after_the_root_file_changed_reloads_the_root(tmp_path):
    # ovrtx keeps its first read of the root file. Here another program
    # writes the file without /World after the open, while ovrtx still has
    # /World: the file no longer tells what ovrtx opened, so a created prim
    # reloads the scene once, and ovrtx gets no reference where it has a prim.
    _Usd, UsdGeom = _pxr_usd_modules()
    scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)
    scene_path.write_text("#usda 1.0\n", encoding="utf-8")
    UsdGeom.Cube.Define(stage, "/World/NewCube")

    _resync(adapter, "/World/NewCube")

    assert renderer.calls[0][0] == "file"
    assert renderer.calls[0][1] != str(scene_path)
    assert not [call for call in renderer.calls if call[0] == "session-string" and call[1].startswith("/World")]
    # ovrtx builds the reloaded scene again in its next step, and stage
    # changes wait for that step. Run the step as the frame loop does.
    renderer.step_async = lambda **_kwargs: _FinishedStep()
    while adapter.scene_update_pending():
        adapter._rebuild_step_runs()
    # The reloaded root is a snapshot that ovrtx has as it is: the next created prim needs no reload.
    renderer.calls.clear()
    UsdGeom.Cube.Define(stage, "/World/OtherCube")
    _resync(adapter, "/World/OtherCube")
    assert [call[0:2] for call in renderer.calls] == [("session-string", "/World/OtherCube")]


def test_created_xform_with_an_applied_schema_goes_to_ovrtx(tmp_path):
    # An applied schema (here a light schema) can make the prim draw.
    from pxr import UsdLux

    _Usd, UsdGeom = _pxr_usd_modules()
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)
    UsdLux.LightAPI.Apply(UsdGeom.Xform.Define(stage, "/World/NewXform").GetPrim())
    created = ChangeEvent(changed_paths=(), resynced_paths=("/World/NewXform",), event_type=ChangeEventType.RESYNC)

    assert adapter.stage_change_keeps_picture(created) is False
    adapter.notify_stage_changed(created)
    assert ("session-string", "/World/NewXform") in [call[0:2] for call in renderer.calls]


def test_created_xform_change_that_needs_a_reload_does_not_keep_the_picture(tmp_path):
    _Usd, UsdGeom = _pxr_usd_modules()
    _scene_path, stage, renderer, adapter = _loaded_scene_for_created_prims(tmp_path)
    UsdGeom.Xform.Define(stage, "/World/NewXform")
    _resync(adapter, "/World/NewXform")

    stage.SetDefaultPrim(stage.GetPrimAtPath("/World/NewXform"))
    metadata = ChangeEvent(
        changed_paths=("/World/NewXform",), resynced_paths=(), event_type=ChangeEventType.LAYER_INFO
    )
    assert adapter.stage_change_keeps_picture(metadata) is False
    # A change of the session layer (the render settings follow it) also renders.
    session = ChangeEvent(
        changed_paths=(renderer_mod._LDR_VAR_PATH + ".sourceName",),
        resynced_paths=("/World/NewXform",),
        event_type=ChangeEventType.RESYNC,
    )
    assert adapter.stage_change_keeps_picture(session) is False
    # So does a change of a prim of the opened root.
    stage.RemovePrim("/World/OldCube")
    removed = ChangeEvent(changed_paths=(), resynced_paths=("/World/OldCube",), event_type=ChangeEventType.RESYNC)
    assert adapter.stage_change_keeps_picture(removed) is False


def test_empty_selection_after_an_empty_selection_writes_nothing(monkeypatch):
    # The viewport selects no mesh for an Xform that draws nothing: its outline
    # cannot change, and the viewport needs no render for it.
    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeResettableRenderer()
    adapter = _make_adapter(renderer)
    adapter._still_frame_requested = False

    assert adapter.set_selection_highlight([]) is False
    adapter.refresh_selection_highlight([])
    assert renderer.outline_group_calls == []
    assert adapter._still_frame_requested is False

    assert adapter.set_selection_highlight(["/World/Cube"]) is True
    # The clear of an outline changes the picture.
    assert adapter.set_selection_highlight([]) is True
    assert adapter._still_frame_requested is True


def test_selection_of_a_removed_prim_writes_nothing(monkeypatch):
    # Undo of Create > Xform removes the selected Xform; the viewport then
    # gives its path again, and a prim that is gone outlines nothing.
    Usd, UsdGeom = _pxr_usd_modules()
    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Cube.Define(stage, "/World/Cube")
    renderer = _FakeResettableRenderer()
    adapter = _make_adapter(renderer)
    adapter._stage = stage
    adapter._still_frame_requested = False

    assert adapter.set_selection_highlight(["/World/Xform"]) is False
    adapter.refresh_selection_highlight(["/World/Xform"])
    assert renderer.outline_group_calls == []
    assert adapter._still_frame_requested is False

    assert adapter.set_selection_highlight(["/World/Xform", "/World/Cube"]) is True
    assert renderer.outline_group_calls


def test_load_stage_strips_stale_root_session_scaffolding_from_ovrtx_snapshot(
    tmp_path,
):
    Usd, UsdGeom = _pxr_usd_modules()
    scene_path = tmp_path / "scene.usda"
    stage = Usd.Stage.CreateNew(str(scene_path))
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    stage.DefinePrim("/OvGearSession", "Scope")
    stage.GetRootLayer().Save()

    renderer = _RootOpenRenderer03()
    adapter = _make_load_stage_adapter(renderer)
    adapter.load_stage(str(scene_path))

    assert renderer.calls[0][0] == "file"
    snapshot_path = renderer.calls[0][1]
    assert snapshot_path != str(scene_path)
    assert "OvGearSession" not in open(snapshot_path, encoding="utf-8").read()
    assert "OvGearSession" in scene_path.read_text(encoding="utf-8")
    assert renderer.calls[1][0:2] == ("session-string", renderer_mod._SESSION_ROOT_PATH)
    assert "OvGearSession" in renderer.calls[1][2]
    assert adapter._owned_tmp_path == snapshot_path


def test_transform_info_change_keeps_ovrtx_attribute_update_path(tmp_path, monkeypatch):
    Usd, UsdGeom = _pxr_usd_modules()
    scene_path = tmp_path / "scene.usda"
    stage = Usd.Stage.CreateNew(str(scene_path))
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    cube = UsdGeom.Cube.Define(stage, "/World/Cube")
    cube.AddTranslateOp().Set((1.0, 2.0, 3.0))
    stage.GetRootLayer().Save()

    renderer = _RootOpenRenderer03()
    renderer.write_attribute = lambda *args, **kwargs: renderer.calls.append(
        ("write_attribute", args, kwargs)
    )
    adapter = _make_load_stage_adapter(renderer)
    adapter.load_stage(stage)
    renderer.calls.clear()
    monkeypatch.setattr(
        renderer_mod, "_ovrtx",
        SimpleNamespace(Semantic=SimpleNamespace(XFORM_MAT4x4="matrix")),
    )

    adapter.notify_stage_changed(ChangeEvent(
        changed_paths=("/World/Cube.xformOp:translate",),
        resynced_paths=(),
        event_type=ChangeEventType.INFO_CHANGE,
    ))

    assert not any(call[0] == "file" for call in renderer.calls)
    writes = [call for call in renderer.calls if call[0] == "write_attribute"]
    assert len(writes) == 1
    assert writes[0][2]["attribute_name"] == "omni:xform"
    assert writes[0][2]["prim_paths"] == ["/World/Cube"]
    assert np.allclose(writes[0][2]["tensor"][0, 3, :3], (1.0, 2.0, 3.0))


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
    import ovui_widgets.viewport.viewport_widget as viewport_widget

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


class _FakeResettableRenderer(_FakeModernRenderer):
    def __init__(self) -> None:
        super().__init__()
        self.reset_calls = 0
        self.reset_failures = 0

    def reset(self):
        self.reset_calls += 1
        if self.reset_failures:
            self.reset_failures -= 1
            raise RuntimeError("simulated reset failure")


def test_selection_highlight_activates_outline_pass_once(monkeypatch):
    """The first applied outline membership resets the renderer exactly once.

    With ovrtx 0.5 a membership write alone does not invalidate a converged,
    camera-static render, so without this one-shot reset the outline of a
    headless (CPU-presented) viewport never appears. A failed reset stays
    owed and is retried by the next selection sync.
    """
    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    renderer = _FakeResettableRenderer()
    renderer.reset_failures = 1
    adapter = _make_adapter(renderer)
    adapter._selection_outline_pass_needs_reset = True

    adapter.set_selection_highlight(["/World/Cube"])
    assert renderer.reset_calls == 1
    assert adapter._selection_outline_pass_needs_reset is True

    adapter.set_selection_highlight(["/World/Sphere"])
    assert renderer.reset_calls == 2
    assert adapter._selection_outline_pass_needs_reset is False

    adapter.set_selection_highlight(["/World/Cube"])
    adapter.set_selection_highlight([])
    assert renderer.reset_calls == 2


class _ResettableRootOpenRenderer(_RootOpenRenderer03, _FakeResettableRenderer):
    def __init__(self) -> None:
        _RootOpenRenderer03.__init__(self)
        _FakeResettableRenderer.__init__(self)


def _with_native_pacing(adapter):
    """The process can run a native pacing session (renderer hooks and Vulkan)."""
    adapter._native_frame_pacing_available = lambda: True
    return adapter


def _start_pass_with_first_selection(adapter, path="/World/Cube"):
    """Select a prim and clear the selection again: the first selection starts the pass."""
    adapter.set_selection_highlight([path])
    adapter.set_selection_highlight([])


def test_scene_open_leaves_the_outline_pass_off(monkeypatch):
    """Opening a scene writes no anchor and resets nothing.

    With the anchor in a group at the first render, ovrtx builds the outline
    pass into that render and the scene appears later. Started right after
    the first frames, the pass needs a reset and a restart of the rendering
    session while the user waits for the scene. Only a selection starts it.
    """
    from pxr import Usd, UsdGeom

    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Cube.Define(stage, "/World/Cube")
    renderer = _ResettableRootOpenRenderer()
    adapter = _with_native_pacing(_make_load_stage_adapter(renderer))
    stops = []
    adapter._stop_native_frame_pacing = lambda reason, **kw: stops.append(reason)

    adapter.load_stage(stage)

    hidden_group = renderer_mod._SELECTION_OUTLINE_HIDDEN_GROUP_ID
    assert not [c for c in renderer.outline_group_calls if c[1] == hidden_group]
    assert renderer.reset_calls == 0
    assert adapter._selection_outline_pass_needs_reset is True
    assert not [reason for reason in stops if "outline" in reason]


def test_the_first_selection_resets_once_and_anchors(monkeypatch):
    """The first selection starts the pass with one reset; later ones need none."""
    from pxr import Usd, UsdGeom

    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Cube.Define(stage, "/World/Cube")
    renderer = _ResettableRootOpenRenderer()
    adapter = _with_native_pacing(_make_load_stage_adapter(renderer))
    adapter.load_stage(stage)

    adapter.set_selection_highlight(["/World/Cube"])
    adapter.set_selection_highlight([])
    adapter.set_selection_highlight(["/World/Cube"])

    assert renderer.reset_calls == 1
    hidden_group = renderer_mod._SELECTION_OUTLINE_HIDDEN_GROUP_ID
    assert ([renderer_mod._SELECTION_OUTLINE_ANCHOR_PATH], hidden_group) in renderer.outline_group_calls


def _pacing_bindings(present_rate=-1.0, supported=True, backend="vulkan", status_error=None):
    """``omni.ui``'s native pacing entry points with the given status."""

    def status():
        if status_error is not None:
            raise status_error
        return {"supported": supported, "backend": backend}

    return SimpleNamespace(
        _get_present_rate=lambda: present_rate,
        _get_native_frame_pacing_status=status,
    )


@pytest.mark.parametrize(
    ("bindings", "available"),
    [
        (_pacing_bindings(), True),
        # OpenGL presentation: no standalone Vulkan backend is registered.
        (_pacing_bindings(backend=""), False),
        # No RTX Tools: no renderer hooks are installed.
        (_pacing_bindings(supported=False), False),
        # Presentation on the ordinary UI tick only.
        (_pacing_bindings(present_rate=0.0), False),
        (None, False),
    ],
    ids=["hooks-and-vulkan", "opengl", "no-hooks", "present-rate-zero", "no-bindings"],
)
def test_native_pacing_needs_renderer_hooks_and_vulkan_presentation(bindings, available):
    """Only renderer hooks with Vulkan presentation defer the outline pass."""
    adapter = _make_adapter(_FakeRenderer())
    adapter._frame_pacing_bindings = lambda: bindings

    assert adapter._native_frame_pacing_available() is available


def test_a_failed_pacing_status_read_is_reported_with_its_cause(capsys):
    """A pacing status that cannot be read is reported, not taken silently as absent."""
    adapter = _make_adapter(_FakeRenderer())
    adapter._frame_pacing_bindings = lambda: _pacing_bindings(
        status_error=RuntimeError("status table is gone")
    )

    assert adapter._native_frame_pacing_available() is False

    err = capsys.readouterr().err
    assert "reading the native frame pacing status failed" in err
    assert "RuntimeError: status table is gone" in err


def test_without_native_pacing_the_first_selection_does_not_reset_renderer(monkeypatch):
    """Without native frame pacing the first click shows its outline at once.

    With no renderer hooks (no RTX Tools), or with OpenGL presentation, no
    native pacing session runs, so nothing starts the outline pass after the
    scene's first frames. A reset at the first click then stops the UI and
    the outline shows late. The anchor is written at scene open instead, and
    the first selection needs no reset. The pacing status here is that of an
    app without RTX Tools: Vulkan presentation, no renderer hooks.
    """
    from pxr import Usd, UsdGeom

    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Cube.Define(stage, "/World/Cube")
    renderer = _ResettableRootOpenRenderer()
    adapter = _make_load_stage_adapter(renderer)
    adapter._frame_pacing_bindings = lambda: _pacing_bindings(supported=False)
    adapter.load_stage(stage)
    hidden_group = renderer_mod._SELECTION_OUTLINE_HIDDEN_GROUP_ID
    assert ([renderer_mod._SELECTION_OUTLINE_ANCHOR_PATH], hidden_group) in renderer.outline_group_calls

    adapter.set_selection_highlight(["/World/Cube"])

    assert renderer.reset_calls == 0
    assert (["/World/Cube"], 1) in renderer.outline_group_calls


def test_scene_open_anchors_the_outline_pass_on_the_session_mesh(monkeypatch):
    """No scene prim is the outline anchor; the user can hide any of them.

    An anchor in the user's scene leaves the viewport with no outline after
    the user hides that prim with its eye and then selects something else.
    The anchor is the session layer's own mesh instead, which no user can
    hide or select.
    """
    from pxr import Usd, UsdGeom

    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Cube.Define(stage, "/World/Cube")
    UsdGeom.Sphere.Define(stage, "/World/Sphere")
    renderer = _ResettableRootOpenRenderer()
    adapter = _with_native_pacing(_make_load_stage_adapter(renderer))

    adapter.load_stage(stage)
    _start_pass_with_first_selection(adapter)

    session_usda = renderer.calls[1][2]
    assert 'def Mesh "OutlineAnchor"' in session_usda
    anchor_path = getattr(renderer_mod, "_SELECTION_OUTLINE_ANCHOR_PATH", "")
    hidden_group = renderer_mod._SELECTION_OUTLINE_HIDDEN_GROUP_ID
    hidden_writes = [
        paths for paths, group in renderer.outline_group_calls if group == hidden_group
    ]
    assert hidden_writes and all(paths == [anchor_path] for paths in hidden_writes)
    assert adapter._selection_outline_anchor_applied is True

    # The eye of the first scene prim, then a selection somewhere else.
    UsdGeom.Imageable(stage.GetPrimAtPath("/World/Cube")).MakeInvisible()
    adapter.set_selection_highlight(["/World/Sphere"])

    assert renderer.reset_calls == 1  # the one reset that started the pass
    assert (["/World/Sphere"], 1) in renderer.outline_group_calls
    # The anchor is still the only member of the hidden group.
    hidden_writes = [
        paths for paths, group in renderer.outline_group_calls if group == hidden_group
    ]
    assert all(paths == [anchor_path] for paths in hidden_writes)


def _load_two_rack_stage(monkeypatch):
    from pxr import Usd, UsdGeom

    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Cube.Define(stage, "/World/RackA/Shelf")
    UsdGeom.Cube.Define(stage, "/World/RackB/Shelf")
    renderer = _ResettableRootOpenRenderer()
    adapter = _make_load_stage_adapter(renderer)
    adapter.load_stage(stage)
    return renderer, adapter


def test_session_layer_reinject_puts_the_anchor_back(monkeypatch):
    """A new session layer (for example after a Viewport resize) gets its anchor again."""
    renderer, adapter = _load_two_rack_stage(monkeypatch)
    _start_pass_with_first_selection(adapter, "/World/RackA/Shelf")
    renderer.outline_group_calls.clear()

    adapter._reinject_session_layer()

    assert renderer.outline_group_calls == [(["/OvGearSession/OutlineAnchor"], 2)]
    assert adapter._selection_outline_pass_needs_reset is False


def test_failed_anchor_write_is_reported_and_the_next_session_layer_tries_again(
    monkeypatch, capsys
):
    """A failed anchor write is reported with its cause.

    The first-selection reset stays armed, as on main, and the next session
    layer (for example after a Viewport resize) writes the anchor again.
    """
    from pxr import Usd, UsdGeom

    fake_ovrtx = SimpleNamespace(SelectionGroupStyle=_SelectionGroupStyle)
    monkeypatch.setattr(renderer_mod, "_ovrtx", fake_ovrtx)
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Cube.Define(stage, "/World/Cube")
    renderer = _ResettableRootOpenRenderer()
    # A scene open writes the anchor twice: with its session layer, and again
    # after it clears the outline state.
    for _ in range(2):
        renderer.outline_group_outcomes.append(RuntimeError("injected anchor failure"))
    adapter = _make_load_stage_adapter(renderer)
    adapter._selection_outline_armed = True  # an earlier scene already started the pass

    adapter.load_stage(stage)

    err = capsys.readouterr().err
    assert "selection outline anchor write failed (/OvGearSession/OutlineAnchor)" in err
    assert "RuntimeError: injected anchor failure" in err
    assert adapter._selection_outline_anchor_applied is False
    assert adapter._selection_outline_pass_needs_reset is True

    adapter._reinject_session_layer()

    assert renderer.outline_group_calls[-1] == (["/OvGearSession/OutlineAnchor"], 2)
    assert adapter._selection_outline_anchor_applied is True
    assert capsys.readouterr().err == ""


