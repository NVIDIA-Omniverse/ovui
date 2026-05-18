# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for Phase D selection-mode wiring in :class:`ViewportWidget`.

Covers the ``replace`` / ``add`` / ``remove`` selection modes that
correspond to plain click, shift-click, and ctrl-click (and their
marquee equivalents) in Steps D.2 / D.3.
"""


from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.viewport.viewport_widget import ViewportWidget


class _StubRenderer(MockRendererAdapter):
    """MockRenderer that returns a scripted pick / pick_rect result.

    The mock's base :meth:`pick` returns ``(None, None)`` and
    :meth:`pick_rect` returns ``[]`` — that's fine for the ``replace``
    deselect path but we want to drive the ``add`` / ``remove`` paths
    with actual hits. This subclass takes the canned result at
    construction.
    """

    def __init__(self, pick_path=None, rect_paths=None):
        super().__init__()
        self._pick_path = pick_path
        self._rect_paths = list(rect_paths) if rect_paths else []

    def pick(self, x, y, callback, query_name):
        callback(self._pick_path, (0.0, 0.0, 0.0) if self._pick_path else None)

    def pick_rect(self, x0, y0, x1, y1, callback):
        callback(list(self._rect_paths))


class TestPickReplaceMode:
    def test_replace_on_hit_sets_selection_to_clicked_prim(self):
        bus = SelectionBus()
        bus.publish(["/World/Old"], source="init")
        renderer = _StubRenderer(pick_path="/World/Cube")
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick(0.0, 0.0, "replace")
        assert bus.get_snapshot().paths() == ["/World/Cube"]
        vp.destroy()

    def test_replace_on_miss_clears_selection(self):
        bus = SelectionBus()
        bus.publish(["/World/Old"], source="init")
        renderer = _StubRenderer(pick_path=None)
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick(0.0, 0.0, "replace")
        assert bus.get_snapshot().paths() == []
        vp.destroy()


class TestPickAddMode:
    def test_add_hit_appends_to_selection(self):
        bus = SelectionBus()
        bus.publish(["/World/A"], source="init")
        renderer = _StubRenderer(pick_path="/World/B")
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick(0.0, 0.0, "add")
        assert bus.get_snapshot().paths() == ["/World/A", "/World/B"]
        vp.destroy()

    def test_add_duplicate_hit_is_deduped(self):
        bus = SelectionBus()
        bus.publish(["/World/A"], source="init")
        renderer = _StubRenderer(pick_path="/World/A")
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick(0.0, 0.0, "add")
        # Shift-click a second time on the same prim keeps selection stable.
        assert bus.get_snapshot().paths() == ["/World/A"]
        vp.destroy()

    def test_add_miss_leaves_selection_unchanged(self):
        bus = SelectionBus()
        bus.publish(["/World/A", "/World/B"], source="init")
        renderer = _StubRenderer(pick_path=None)
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick(0.0, 0.0, "add")
        assert bus.get_snapshot().paths() == ["/World/A", "/World/B"]
        vp.destroy()


class TestPickRemoveMode:
    def test_remove_hit_drops_prim_from_selection(self):
        bus = SelectionBus()
        bus.publish(["/World/A", "/World/B", "/World/C"], source="init")
        renderer = _StubRenderer(pick_path="/World/B")
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick(0.0, 0.0, "remove")
        assert bus.get_snapshot().paths() == ["/World/A", "/World/C"]
        vp.destroy()

    def test_remove_missing_path_is_noop(self):
        bus = SelectionBus()
        bus.publish(["/World/A"], source="init")
        renderer = _StubRenderer(pick_path="/World/B")  # not in selection
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick(0.0, 0.0, "remove")
        assert bus.get_snapshot().paths() == ["/World/A"]
        vp.destroy()

    def test_remove_on_miss_leaves_selection_unchanged(self):
        bus = SelectionBus()
        bus.publish(["/World/A", "/World/B"], source="init")
        renderer = _StubRenderer(pick_path=None)
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick(0.0, 0.0, "remove")
        assert bus.get_snapshot().paths() == ["/World/A", "/World/B"]
        vp.destroy()


class TestPickRectModes:
    def test_rect_replace_sets_selection(self):
        bus = SelectionBus()
        bus.publish(["/World/Old"], source="init")
        renderer = _StubRenderer(rect_paths=["/World/A", "/World/B"])
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick_rect(-1.0, -1.0, 1.0, 1.0, "replace")
        assert bus.get_snapshot().paths() == ["/World/A", "/World/B"]
        vp.destroy()

    def test_rect_add_unions_with_current(self):
        bus = SelectionBus()
        bus.publish(["/World/A"], source="init")
        renderer = _StubRenderer(rect_paths=["/World/B", "/World/C"])
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick_rect(-1.0, -1.0, 1.0, 1.0, "add")
        assert bus.get_snapshot().paths() == ["/World/A", "/World/B", "/World/C"]
        vp.destroy()

    def test_rect_remove_subtracts_from_current(self):
        bus = SelectionBus()
        bus.publish(["/World/A", "/World/B", "/World/C"], source="init")
        renderer = _StubRenderer(rect_paths=["/World/B"])
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick_rect(-1.0, -1.0, 1.0, 1.0, "remove")
        assert bus.get_snapshot().paths() == ["/World/A", "/World/C"]
        vp.destroy()

    def test_rect_replace_empty_clears_selection(self):
        bus = SelectionBus()
        bus.publish(["/World/A"], source="init")
        renderer = _StubRenderer(rect_paths=[])
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        vp._on_pick_rect(-1.0, -1.0, 1.0, 1.0, "replace")
        assert bus.get_snapshot().paths() == []
        vp.destroy()


class TestModeCallbackFactories:
    def test_make_pick_callback_binds_mode(self):
        bus = SelectionBus()
        renderer = _StubRenderer(pick_path="/World/X")
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        add_cb = vp._make_pick_callback("add")
        bus.publish(["/World/Y"], source="init")
        add_cb(0.0, 0.0)
        assert bus.get_snapshot().paths() == ["/World/Y", "/World/X"]
        vp.destroy()

    def test_make_pick_rect_callback_binds_mode(self):
        bus = SelectionBus()
        renderer = _StubRenderer(rect_paths=["/World/A", "/World/B"])
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        bus.publish(["/World/Pre"], source="init")
        remove_cb = vp._make_pick_rect_callback("remove")
        # Rect hits A, B — neither is in current selection → no change.
        remove_cb(-1.0, -1.0, 1.0, 1.0)
        assert bus.get_snapshot().paths() == ["/World/Pre"]
        vp.destroy()


class TestMergeSelectionHelper:
    def test_unknown_mode_falls_back_to_replace(self):
        bus = SelectionBus()
        bus.publish(["/World/Old"], source="init")
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        merged = vp._merge_selection(["/World/New"], "garbage-mode")
        assert merged == ["/World/New"]
        vp.destroy()

    def test_merge_without_bus_is_safe(self):
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer)  # no bus
        assert vp._merge_selection(["/A"], "add") == ["/A"]
        assert vp._merge_selection(["/A"], "remove") == []
        vp.destroy()

    def test_add_dedupes_duplicates_in_hits(self):
        bus = SelectionBus()
        renderer = MockRendererAdapter()
        vp = ViewportWidget(services=None, renderer=renderer, bus=bus)
        merged = vp._merge_selection(["/A", "/A", "/B"], "add")
        assert merged == ["/A", "/B"]
        vp.destroy()
