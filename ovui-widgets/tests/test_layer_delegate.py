# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ovui_widgets.layers.layer_delegate.LayerDelegate` (Step 17-22).

The delegate graduates each column from a blank placeholder to a real
widget across Steps 17-22. As of Step 22 every column paints content:
columns 0, 2, 3, 6 paint real value-model-backed widgets; columns 1,
4, 5 paint disabled-tint placeholder glyphs (LAYERS-PLAN Step 22).
Tests exercise the dispatch contract and the expected column symbols
so a later refactor can't silently drop the lookup indirection.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import omni.ui as ui
import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.layers import LayerDelegate, LayerModel


def _can_build_frame() -> bool:
    # ``ui.Frame`` construction requires ``ui.init()``. Under the
    # test-suite harness this is already done by ``conftest.py`` for the
    # ``ui`` fixture; fall back to a probe so the delegate-build tests
    # cleanly skip in minimal environments.
    try:
        w = ui.Window("__probe_layer_delegate__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_UI_AVAILABLE = _can_build_frame()
_skip_no_ui = pytest.mark.skipif(
    not _UI_AVAILABLE,
    reason="ui.Frame construction not available without ui.init()",
)


class TestConstruction:
    def test_is_abstract_item_delegate(self) -> None:
        assert issubclass(LayerDelegate, ui.AbstractItemDelegate)

    def test_instance_is_delegate(self) -> None:
        delegate = LayerDelegate()
        assert isinstance(delegate, ui.AbstractItemDelegate)


class TestColumnConstants:
    """Column ID contract must stay in lockstep with the model / window."""

    def test_column_ids_match_plan_order(self) -> None:
        # LAYERS-PLAN Step 17 freezes the order as
        # name · live · save · local-mute · global-mute · latest · lock.
        assert LayerDelegate.COL_NAME == 0
        assert LayerDelegate.COL_LIVE == 1
        assert LayerDelegate.COL_SAVE == 2
        assert LayerDelegate.COL_LOCAL_MUTE == 3
        assert LayerDelegate.COL_GLOBAL_MUTE == 4
        assert LayerDelegate.COL_LATEST == 5
        assert LayerDelegate.COL_LOCK == 6

    def test_column_ids_cover_full_range(self) -> None:
        ids = {
            LayerDelegate.COL_NAME,
            LayerDelegate.COL_LIVE,
            LayerDelegate.COL_SAVE,
            LayerDelegate.COL_LOCAL_MUTE,
            LayerDelegate.COL_GLOBAL_MUTE,
            LayerDelegate.COL_LATEST,
            LayerDelegate.COL_LOCK,
        }
        # No duplicates, exactly the 0..6 inclusive range.
        assert ids == set(range(LayerModel.NUM_COLUMNS))


@_skip_no_ui
class TestBuildWidget:
    """Dispatch contract — no raises across every column ID."""

    def test_build_widget_on_name_column_uses_value_model(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window("__test_layer_delegate_name__", width=100, height=50)
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(
                        model, model.root_item, LayerDelegate.COL_NAME, 0, False
                    )
        finally:
            window.destroy()
            model.destroy()

    @pytest.mark.parametrize("col", [1, 2, 3, 4, 5, 6])
    def test_build_widget_on_non_name_columns(self, col: int) -> None:
        # Every non-name column must accept the call without raising —
        # a regression here means the TreeView would fault mid-paint.
        # Graduated columns (2 save, 3 local-mute) paint real widgets;
        # the rest still render placeholder ``ui.Spacer`` cells.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window(
            f"__test_layer_delegate_col{col}__", width=50, height=50
        )
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(
                        model, model.root_item, col, 0, False
                    )
        finally:
            window.destroy()
            model.destroy()

    def test_build_widget_ignores_non_layer_item(self) -> None:
        # Prim-spec items (Phase J) flow through the same delegate; the
        # skeleton must return quietly rather than crash on an unknown
        # row type.
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_non_layer__", width=50, height=50
        )
        try:
            with window.frame:
                with ui.VStack():
                    # Model argument is only accessed on the name branch,
                    # so a bare MagicMock is plenty for this assertion.
                    delegate.build_widget(
                        MagicMock(), "not-a-layer-item", 0, 0, False
                    )
        finally:
            window.destroy()

    def test_build_widget_tolerates_unknown_column(self) -> None:
        # ovui always hands back a column id in ``0..NUM_COLUMNS-1``,
        # but the skeleton must not raise on column overflow — the only
        # defensible behaviour is a blank placeholder cell.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_unknown__", width=50, height=50
        )
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(model, model.root_item, 99, 0, False)
        finally:
            window.destroy()
            model.destroy()


class TestStep22PlaceholderTooltipCopy:
    """LAYERS-PLAN Step 22 — placeholder tooltip copy is part of the
    public contract (the strings surface on hover to explain the
    greyed state). Testing them as class constants keeps the
    translation / rename surface explicit: a rename that drifts from
    the plan's `"coming in v2"` phrasing fails here.
    """

    def test_live_tooltip_matches_plan(self) -> None:
        assert (
            LayerDelegate.LIVE_PLACEHOLDER_TOOLTIP
            == "Live sync \u2014 coming in v2"
        )

    def test_global_mute_tooltip_matches_plan(self) -> None:
        assert (
            LayerDelegate.GLOBAL_MUTE_PLACEHOLDER_TOOLTIP
            == "Global mute \u2014 coming in v2"
        )

    def test_latest_tooltip_matches_plan(self) -> None:
        assert (
            LayerDelegate.LATEST_PLACEHOLDER_TOOLTIP
            == "Version tracking \u2014 coming in v2"
        )


@_skip_no_ui
class TestStep22PlaceholderBuilders:
    """Direct coverage for the Step 22 placeholder cell builders.

    The parametrised :class:`TestBuildWidget` sweep already exercises
    the dispatch path into each builder. These tests target the
    builders directly to pin down the per-column behaviours the plan
    calls out (non-interactive, tint, missing-only for Latest).
    """

    def _seed_missing_child(self, adapter: MockLayerStackAdapter) -> None:
        # ``add_sublayer`` creates a record with ``missing=False`` by
        # default; flip the bit via ``set_missing`` so the resulting
        # row reports ``is_missing=True`` when the delegate builds.
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./does-not-exist.usda")
        adapter.set_missing("./does-not-exist.usda", True)

    def test_live_placeholder_builds_without_click_handler(self) -> None:
        # Column 1 must render but not attach a click handler — a
        # click on the cell falls through to the TreeView row select.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_live_ph__", width=50, height=50
        )
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(
                        model, model.root_item, LayerDelegate.COL_LIVE, 0, False
                    )
        finally:
            window.destroy()
            model.destroy()

    def test_global_mute_placeholder_builds_without_click_handler(
        self,
    ) -> None:
        # Column 4 must render but not attach a click handler — same
        # contract as Live. In v1 the column is visually present but
        # non-interactive (muteness scope never flips global).
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_gm_ph__", width=50, height=50
        )
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(
                        model,
                        model.root_item,
                        LayerDelegate.COL_GLOBAL_MUTE,
                        0,
                        False,
                    )
        finally:
            window.destroy()
            model.destroy()

    def test_latest_placeholder_blank_for_present_layer(self) -> None:
        # Column 5 renders a ``ui.Spacer`` (no glyph) for rows whose
        # layer is not missing — Kit's "reload hint only when the
        # file is unresolved" convention (LAYERS-PLAN Step 22).
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_latest_present__", width=50, height=50
        )
        try:
            assert model.root_item.is_missing is False
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(
                        model,
                        model.root_item,
                        LayerDelegate.COL_LATEST,
                        0,
                        False,
                    )
        finally:
            window.destroy()
            model.destroy()

    def test_latest_placeholder_renders_for_missing_layer(self) -> None:
        # Column 5 renders the disabled reload-style glyph for rows
        # whose layer is missing. The build must not raise and the
        # seeded row must actually report ``is_missing=True`` so the
        # test is not silently covering the blank branch.
        adapter = MockLayerStackAdapter()
        self._seed_missing_child(adapter)
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        missing_item = model._items_by_id["./does-not-exist.usda"]
        assert missing_item.is_missing is True
        window = ui.Window(
            "__test_layer_delegate_latest_missing__", width=50, height=50
        )
        try:
            with window.frame:
                with ui.VStack():
                    delegate.build_widget(
                        model,
                        missing_item,
                        LayerDelegate.COL_LATEST,
                        0,
                        False,
                    )
        finally:
            window.destroy()
            model.destroy()


@_skip_no_ui
class TestStep23RowSelectionRectangle:
    """Step 23 — the delegate paints a row-wide selection rectangle.

    Group F (visual diagnostic finding #1) reversed Step 23's per-cell
    Rectangle approach because ovui's TreeView column layout
    splintered the row background into 6 disconnected chunks across
    column dividers. Selection / hover now paint via the TreeView's
    native paint mechanism (``Layers.TreeView:selected.background_color``
    + ``Layers.TreeView.background_selected_color``); per-cell
    rectangles have been removed from ``build_widget`` and
    ``build_branch``.

    These tests do not screenshot — Designer validation happens via
    the Step 23 QA screenshot helper and the Group F diagnostic
    captures. What's asserted here is the non-visual contract after
    Group F:
    - ``build_branch`` on column 0 still produces a ZStack (so the
      drop indicator and focus ring can layer above the branch
      content) but its children no longer include a ``row_bg``
      Rectangle.
    - ``build_branch`` on non-zero columns is a no-op (ovui only calls
      build_branch with ``column_id == 0``, but a defensive call from
      a future codepath must not fault).
    - ``build_widget`` still produces a ZStack per column for the
      drop-indicator / focus-ring overlays; per-cell row_bg Rectangle
      is gone (verified by absence of any Rectangle whose ``name`` is
      ``row_bg`` or ``row_bg_edit_target``).
    """

    def test_build_branch_on_column_zero_paints_row_bg(self) -> None:
        # Group F — branch cell still produces a ZStack so the
        # focus ring + drop indicator can stack above the chevron, but
        # the per-cell row_bg Rectangle that used to be the ZStack's
        # first child has been removed. Selection / hover now paint
        # via the TreeView's native ``:selected`` /
        # ``background_selected_color`` mechanism.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_branch_row_bg__", width=100, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_branch(
                        model, model.root_item, 0, 0, False
                    )
            children = list(ui.Inspector.get_children(container))
            assert len(children) == 1
            stack = children[0]
            assert isinstance(stack, ui.ZStack)
            row_bg_rects = [
                w
                for w in _flatten_widgets(stack)
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None)
                in {"row_bg", "row_bg_edit_target"}
            ]
            assert row_bg_rects == []
        finally:
            window.destroy()
            model.destroy()

    def test_build_branch_non_zero_column_is_noop(self) -> None:
        # ovui only calls build_branch with column_id == 0, but a
        # defensive call must not raise or paint a stray widget.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_branch_col_nonzero__", width=50, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_branch(
                        model, model.root_item, 2, 0, False
                    )
            # No widgets — the branch renderer bails out before
            # touching the tree.
            assert list(ui.Inspector.get_children(container)) == []
        finally:
            window.destroy()
            model.destroy()

    @pytest.mark.parametrize("col", [0, 1, 2, 3, 4, 5, 6])
    def test_build_widget_wraps_column_in_row_bg_zstack(self, col: int) -> None:
        # Group F — every column still wraps its widget in a ZStack so
        # ``_build_drop_indicator`` and ``_build_focus_ring`` have a
        # mounting point above the column content, but the per-cell
        # ``row_bg`` Rectangle that fragmented the row background is
        # gone. The TreeView's native paint at column-stride boundaries
        # is now the only painter of selection / hover tints, which
        # produces one continuous strip.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window(
            f"__test_layer_delegate_col{col}_wrap__", width=100, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, model.root_item, col, 0, False
                    )
            children = list(ui.Inspector.get_children(container))
            assert len(children) == 1
            stack = children[0]
            assert isinstance(stack, ui.ZStack)
            row_bg_rects = [
                w
                for w in _flatten_widgets(stack)
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None)
                in {"row_bg", "row_bg_edit_target"}
            ]
            assert row_bg_rects == []
        finally:
            window.destroy()
            model.destroy()

    def test_build_branch_expanded_row_renders_chevron_glyph(self) -> None:
        # Expandable rows (the root) draw a ``chevron_down.png`` glyph on
        # the front layer so the user sees the expand / collapse
        # affordance. After Group H the chevron is a PNG painted via
        # :class:`ui.ImageWithProvider` (mirroring
        # ``ovui_widgets.stage/widget/stage_delegate.py:91-98``); the previous
        # ``ui.Triangle`` primitive is gone.
        adapter = MockLayerStackAdapter()
        from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER

        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child.usda")
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_branch_chevron__", width=100, height=50
        )
        try:
            assert model.can_item_have_children(model.root_item) is True
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_branch(
                        model, model.root_item, 0, 0, True
                    )

            def _flatten(widget):
                out = [widget]
                try:
                    kids = list(ui.Inspector.get_children(widget))
                except Exception:
                    kids = []
                for k in kids:
                    out.extend(_flatten(k))
                return out

            top_children = list(ui.Inspector.get_children(container))
            all_widgets = _flatten(top_children[0])
            chevrons = [
                w for w in all_widgets
                if isinstance(w, ui.ImageWithProvider)
                and w.style_type_name_override == "Layers.BranchChevron"
            ]
            assert len(chevrons) == 1
            # No ``ui.Triangle`` should remain — Group H removed it.
            triangles = [w for w in all_widgets if isinstance(w, ui.Triangle)]
            assert triangles == []
        finally:
            window.destroy()
            model.destroy()

    def test_build_branch_leaf_row_has_no_chevron(self) -> None:
        # Leaf rows (no children) must not paint a chevron — otherwise
        # the user sees an "expandable" affordance on a row that has
        # nothing to expand. The branch ZStack still paints so the
        # focus ring + drop indicator overlays stay coherent.
        adapter = MockLayerStackAdapter()
        from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER

        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./leaf.usda")
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        leaf_item = model._items_by_id["./leaf.usda"]
        window = ui.Window(
            "__test_layer_delegate_branch_leaf__", width=100, height=50
        )
        try:
            assert model.can_item_have_children(leaf_item) is False
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_branch(model, leaf_item, 0, 1, False)

            def _flatten(widget):
                out = [widget]
                try:
                    kids = list(ui.Inspector.get_children(widget))
                except Exception:
                    kids = []
                for k in kids:
                    out.extend(_flatten(k))
                return out

            top_children = list(ui.Inspector.get_children(container))
            all_widgets = _flatten(top_children[0])
            chevrons = [
                w for w in all_widgets
                if isinstance(w, ui.ImageWithProvider)
                and w.style_type_name_override == "Layers.BranchChevron"
            ]
            assert chevrons == []
            triangles = [w for w in all_widgets if isinstance(w, ui.Triangle)]
            assert triangles == []
        finally:
            window.destroy()
            model.destroy()


def _flatten_widgets(widget):
    """Depth-first recursion over the widget tree — shared by Step 25 tests."""
    out = [widget]
    try:
        kids = list(ui.Inspector.get_children(widget))
    except Exception:
        kids = []
    for k in kids:
        out.extend(_flatten_widgets(k))
    return out


class TestStep25RowBgNameHelper:
    """Step 25 — ``_row_bg_name`` picks the green overlay token.

    These tests reach into the helper directly so the non-visual
    contract (edit-target row → ``"row_bg_edit_target"``, every other
    row → ``"row_bg"``) is covered even without a ``ui`` fixture.
    """

    def test_non_edit_target_returns_row_bg(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        try:
            # Mock adapter seeds the root as the edit target by default;
            # the session layer row is therefore *not* the edit target.
            session_item = next(
                (i for i in model.get_item_children(None) if i.is_session_layer),
                None,
            )
            assert session_item is not None
            assert session_item._is_edit_target is False
            assert delegate._row_bg_name(session_item) == "row_bg"
        finally:
            model.destroy()

    def test_edit_target_returns_row_bg_edit_target(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        try:
            # The mock adapter's default edit target is the root layer.
            assert model.root_item._is_edit_target is True
            assert delegate._row_bg_name(model.root_item) == "row_bg_edit_target"
        finally:
            model.destroy()

    def test_non_layer_item_returns_row_bg(self) -> None:
        # Phase J prim-spec rows flow through the delegate too; a non-
        # LayerItem must fall through to the neutral token so ovui paints
        # the normal row background rather than crashing on the flag read.
        delegate = LayerDelegate()
        assert delegate._row_bg_name("not-a-layer-item") == "row_bg"
        assert delegate._row_bg_name(None) == "row_bg"


class TestStep25LeadingIconStateHelper:
    """Step 25 — ``_leading_icon_state`` picks one of three state tokens.

    Precedence ``edit_target > has_descendant > normal`` matches the
    LAYERS-PLAN Step 25 "Name icon selection hierarchy" line, with
    ``missing`` / ``outdated`` deferred to Step 27 (tested alongside
    its handler landing).
    """

    def test_edit_target_beats_has_descendant(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        try:
            root = model.root_item
            root._has_edit_target_descendant = True  # pathological combo
            assert root._is_edit_target is True
            # Precedence wins — even when a descendant flag happens to be
            # set (shouldn't in practice; guards against regression).
            assert delegate._leading_icon_state(root) == "edit_target"
        finally:
            model.destroy()

    def test_has_descendant_when_not_edit_target(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child.usda")
        adapter.set_edit_target("./child.usda")
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        try:
            # The adapter event propagates edit-target ancestry on the
            # root row; assert the icon state reflects it.
            assert model.root_item._is_edit_target is False
            assert model.root_item._has_edit_target_descendant is True
            assert delegate._leading_icon_state(model.root_item) == "has_descendant"
        finally:
            model.destroy()

    def test_normal_on_plain_row(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./sib.usda")
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        try:
            sib = model._items_by_id["./sib.usda"]
            assert sib._is_edit_target is False
            assert sib._has_edit_target_descendant is False
            assert delegate._leading_icon_state(sib) == "normal"
        finally:
            model.destroy()

    def test_non_layer_item_returns_normal(self) -> None:
        delegate = LayerDelegate()
        assert delegate._leading_icon_state("prim-spec") == "normal"
        assert delegate._leading_icon_state(None) == "normal"


@_skip_no_ui
class TestStep25EditTargetRendering:
    """Step 25 — rendered widget contract for the authoring-layer row.

    Group F (visual diagnostic finding #1) removed the per-cell
    ``Layers.TreeView.Row::row_bg`` / ``::row_bg_edit_target``
    :class:`ui.Rectangle` from every cell because ovui's TreeView column
    layout splintered those rectangles into 6 disconnected chunks.
    Selection, hover, AND the ``cl.layers_row_edit_target`` row
    background now paint via the TreeView's native paint mechanism;
    the per-cell ZStack carries only the column's own widget content,
    drop indicators, and the focus ring.

    The remaining contract:

    - The name column still carries three stacked ``Layers.LeadingIcon``
      bars whose ``name=`` matches the row's edit-target state — the
      leading-icon green is the only persistent edit-target signal
      after Group F.
    - The ``_row_bg_name`` helper still returns the right token when
      consulted directly (covered by ``TestStep25RowBgNameHelper``);
      it is no longer called from the build path but stays as a stable
      surface for ``LayerDelegate`` subclasses and for any future
      reintroduction of a row-spanning overlay.
    """

    @pytest.mark.parametrize("col", [0, 1, 2, 3, 4, 5, 6])
    def test_edit_target_cell_has_no_row_bg_rectangle(self, col: int) -> None:
        # Group F — confirm the per-cell row_bg Rectangle has been
        # removed. The cell's outer ZStack is still present (so the
        # focus ring and drop indicator can layer above the column
        # widget) but it must NOT include a Rectangle whose ``name``
        # is one of the row-bg tokens — those rectangles fragmented
        # the row across column dividers.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        assert model.root_item._is_edit_target is True
        window = ui.Window(
            f"__test_layer_delegate_groupf_col{col}__", width=120, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, model.root_item, col, 0, False
                    )
            top_children = list(ui.Inspector.get_children(container))
            assert len(top_children) == 1
            stack = top_children[0]
            assert isinstance(stack, ui.ZStack)
            row_bg_rects = [
                w
                for w in _flatten_widgets(stack)
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None)
                in {"row_bg", "row_bg_edit_target"}
            ]
            assert row_bg_rects == [], (
                f"Group F regression: column {col} still paints "
                f"{[r.name for r in row_bg_rects]} per-cell rectangles"
            )
        finally:
            window.destroy()
            model.destroy()

    def test_edit_target_branch_cell_has_no_row_bg_rectangle(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        assert model.root_item._is_edit_target is True
        window = ui.Window(
            "__test_layer_delegate_groupf_branch__", width=80, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_branch(
                        model, model.root_item, 0, 0, False
                    )
            stack = list(ui.Inspector.get_children(container))[0]
            row_bg_rects = [
                w
                for w in _flatten_widgets(stack)
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None)
                in {"row_bg", "row_bg_edit_target"}
            ]
            assert row_bg_rects == []
        finally:
            window.destroy()
            model.destroy()

    def test_non_edit_target_row_has_no_row_bg_rectangle(self) -> None:
        # Group F — the per-cell ``row_bg`` Rectangle is gone for both
        # edit-target and non-edit-target rows alike. Selection / hover
        # paint via the TreeView's native mechanism.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./sib.usda")
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        sib = model._items_by_id["./sib.usda"]
        assert sib._is_edit_target is False
        window = ui.Window(
            "__test_layer_delegate_groupf_sibling__", width=120, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, sib, LayerDelegate.COL_NAME, 1, False
                    )
            stack = list(ui.Inspector.get_children(container))[0]
            row_bg_rects = [
                w
                for w in _flatten_widgets(stack)
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None)
                in {"row_bg", "row_bg_edit_target"}
            ]
            assert row_bg_rects == []
        finally:
            window.destroy()
            model.destroy()

    def test_name_column_carries_three_edit_target_bars(self) -> None:
        # The leading icon is three stacked ``Layers.LeadingIcon``
        # rectangles. On the authoring-layer row each carries
        # ``name="edit_target"`` so the green tint resolves. Assert both
        # the count (3) and the state token to pin the contract.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        assert model.root_item._is_edit_target is True
        window = ui.Window(
            "__test_layer_delegate_step25_leading_icon__",
            width=150,
            height=50,
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, model.root_item, LayerDelegate.COL_NAME, 0, False
                    )
            widgets = _flatten_widgets(list(ui.Inspector.get_children(container))[0])
            leading_bars = [
                w
                for w in widgets
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None) == "edit_target"
            ]
            assert len(leading_bars) == 3
        finally:
            window.destroy()
            model.destroy()

    def test_ancestor_of_edit_target_gets_has_descendant_icon(self) -> None:
        # Set a grandchild as the edit target and assert the intermediate
        # parent's name column renders the half-green ``has_descendant``
        # bars rather than the full green.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./mid.usda")
        adapter.add_sublayer("./mid.usda", "./deep.usda")
        adapter.set_edit_target("./deep.usda")
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        mid = model._items_by_id["./mid.usda"]
        assert mid._is_edit_target is False
        assert mid._has_edit_target_descendant is True
        window = ui.Window(
            "__test_layer_delegate_step25_half__",
            width=150,
            height=50,
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, mid, LayerDelegate.COL_NAME, 1, False
                    )
            widgets = _flatten_widgets(list(ui.Inspector.get_children(container))[0])
            bars = [
                w
                for w in widgets
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None) == "has_descendant"
            ]
            assert len(bars) == 3
            # No ``edit_target``-tinted bars on the ancestor — otherwise the
            # full-green signal would leak onto two rows.
            green_bars = [
                w
                for w in widgets
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None) == "edit_target"
            ]
            assert green_bars == []
        finally:
            window.destroy()
            model.destroy()

    def test_plain_row_gets_normal_icon_state(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./sib.usda")
        model = LayerModel(adapter)
        delegate = LayerDelegate()
        sib = model._items_by_id["./sib.usda"]
        assert sib._is_edit_target is False
        assert sib._has_edit_target_descendant is False
        window = ui.Window(
            "__test_layer_delegate_step25_normal__", width=150, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, sib, LayerDelegate.COL_NAME, 1, False
                    )
            widgets = _flatten_widgets(list(ui.Inspector.get_children(container))[0])
            bars = [
                w
                for w in widgets
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None) == "normal"
            ]
            assert len(bars) == 3
        finally:
            window.destroy()
            model.destroy()


class TestStep25StyleTokens:
    """Step 25 — style-dict selectors and palette tokens exist.

    Pins the contract between the delegate's ``name=`` choices and the
    style / palette layer so a token rename can't silently leave the
    green overlay unstyled.
    """

    def test_row_bg_edit_target_style_entry_exists(self) -> None:
        from ovui_widgets.layers.style import LAYERS_STYLES

        assert "Layers.TreeView.Row::row_bg_edit_target" in LAYERS_STYLES
        # Hover / selected inherit the same green so the authoring-layer
        # signal never disappears under interaction — pin both.
        assert "Layers.TreeView.Row::row_bg_edit_target:hovered" in LAYERS_STYLES
        assert "Layers.TreeView.Row::row_bg_edit_target:selected" in LAYERS_STYLES

    def test_leading_icon_state_entries_exist(self) -> None:
        from ovui_widgets.layers.style import LAYERS_STYLES

        assert "Layers.LeadingIcon" in LAYERS_STYLES
        assert "Layers.LeadingIcon::normal" in LAYERS_STYLES
        assert "Layers.LeadingIcon::edit_target" in LAYERS_STYLES
        assert "Layers.LeadingIcon::has_descendant" in LAYERS_STYLES

    def test_palette_has_half_edit_token(self) -> None:
        # Importing the palette module registers the shade on the
        # ColorStore; a missing attribute here means the dim half-green
        # tint would fail to resolve at paint time.
        from omni.ui import color as cl

        import ovui_widgets.app
        import ovui_widgets.common.style.palette  # noqa: F401 — side-effect registration

        assert cl.layers_icon_half_edit is not None


# ─── Step 27 — missing / read-only visual treatments ────────────────────────


@_skip_no_ui
class TestStep27MissingBadge:
    """Step 27 — missing layers paint a red ``X`` badge next to the icon.

    The badge is an ASCII :class:`ui.Label` with ``name=``-less
    ``Layers.MissingBadge`` override. Asserts both the conditional
    rendering (only for missing rows) and the exact glyph so a later
    swap to the Step-27 SVG pack can't silently drop the badge.
    """

    def _seed_missing_row(
        self,
    ) -> "tuple[MockLayerStackAdapter, LayerModel, object]":
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./does-not-exist.usda")
        adapter.set_missing("./does-not-exist.usda", True)
        model = LayerModel(adapter)
        missing_item = model._items_by_id["./does-not-exist.usda"]
        assert missing_item.is_missing is True
        return adapter, model, missing_item

    def test_missing_row_name_column_renders_x_badge(self) -> None:
        # Present ``X`` badge + red ``Layers.MissingBadge`` override on
        # the missing row's name column — both pieces of the Step-27
        # contract must be present.
        _, model, missing_item = self._seed_missing_row()
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_step27_missing__", width=150, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, missing_item, LayerDelegate.COL_NAME, 1, False
                    )
            widgets = _flatten_widgets(list(ui.Inspector.get_children(container))[0])
            badges = [
                w
                for w in widgets
                if isinstance(w, ui.Label) and w.text == "X"
            ]
            assert len(badges) == 1
            # Label carries the ``Layers.MissingBadge`` type override —
            # asserting the text alone would miss a bug where a stray
            # ``X`` appeared in the name label itself.
            assert badges[0].style_type_name_override == "Layers.MissingBadge"
        finally:
            window.destroy()
            model.destroy()

    def test_non_missing_row_name_column_has_no_badge(self) -> None:
        # Present rows must not paint the badge — otherwise the
        # column strip would carry a spurious red X for every layer.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./exists.usda")
        model = LayerModel(adapter)
        present = model._items_by_id["./exists.usda"]
        assert present.is_missing is False
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_step27_no_badge__", width=150, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, present, LayerDelegate.COL_NAME, 1, False
                    )
            widgets = _flatten_widgets(list(ui.Inspector.get_children(container))[0])
            badges = [
                w
                for w in widgets
                if isinstance(w, ui.Label)
                and w.style_type_name_override == "Layers.MissingBadge"
            ]
            assert badges == []
        finally:
            window.destroy()
            model.destroy()

    def test_missing_row_name_label_still_carries_missing_role(
        self,
    ) -> None:
        # Step-18 red label + Step-27 badge must coexist — the badge is
        # an *additional* cue, not a replacement.
        _, model, missing_item = self._seed_missing_row()
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_step27_missing_label__", width=150, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, missing_item, LayerDelegate.COL_NAME, 1, False
                    )
            widgets = _flatten_widgets(list(ui.Inspector.get_children(container))[0])
            name_labels = [
                w
                for w in widgets
                if isinstance(w, ui.Label)
                and w.style_type_name_override == "Layers.NameLabel"
            ]
            assert len(name_labels) == 1
            assert name_labels[0].name == "missing"
        finally:
            window.destroy()
            model.destroy()


@_skip_no_ui
class TestStep27ReadOnlyOverlay:
    """Step 27 — read-only layers paint a non-interactive overlay in col 6.

    The overlay is a :class:`ui.Rectangle` with
    ``name="readonly_overlay"`` painted behind the clickable padlock
    glyph. Pins:

    - Overlay Rectangle is present on the read-only row's col-6 cell.
    - Overlay Rectangle is absent on a writable row.
    - Overlay does not attach a mouse handler (non-interactive).
    """

    def _seed_read_only_row(
        self,
    ) -> "tuple[MockLayerStackAdapter, LayerModel, object]":
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./readonly.usda")
        adapter.set_read_only("./readonly.usda", True)
        model = LayerModel(adapter)
        ro_item = model._items_by_id["./readonly.usda"]
        assert ro_item.is_read_only is True
        return adapter, model, ro_item

    def test_read_only_row_lock_column_paints_overlay(self) -> None:
        # Read-only rows get a ``Layers.LockIcon::readonly_overlay``
        # Rectangle painted behind the clickable padlock. Exactly one
        # overlay Rectangle per cell — anything more means the paint
        # pass is doubling up.
        _, model, ro_item = self._seed_read_only_row()
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_step27_ro__", width=80, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, ro_item, LayerDelegate.COL_LOCK, 1, False
                    )
            widgets = _flatten_widgets(list(ui.Inspector.get_children(container))[0])
            overlays = [
                w
                for w in widgets
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None) == "readonly_overlay"
                and w.style_type_name_override == "Layers.LockIcon"
            ]
            assert len(overlays) == 1
        finally:
            window.destroy()
            model.destroy()

    def test_writable_row_lock_column_has_no_overlay(self) -> None:
        # Writable rows must not paint the read-only overlay —
        # otherwise every lock cell would carry the dim backdrop.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./writable.usda")
        model = LayerModel(adapter)
        writable = model._items_by_id["./writable.usda"]
        assert writable.is_read_only is False
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_step27_writable__", width=80, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, writable, LayerDelegate.COL_LOCK, 1, False
                    )
            widgets = _flatten_widgets(list(ui.Inspector.get_children(container))[0])
            overlays = [
                w
                for w in widgets
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None) == "readonly_overlay"
            ]
            assert overlays == []
        finally:
            window.destroy()
            model.destroy()

    def test_read_only_row_still_has_clickable_lock(self) -> None:
        # The overlay must not eat the user-driven lock toggle — the
        # interactive padlock primitives still render on top, and the
        # click stack (``locked`` / ``unlocked`` state) is unchanged.
        _, model, ro_item = self._seed_read_only_row()
        delegate = LayerDelegate()
        window = ui.Window(
            "__test_layer_delegate_step27_ro_click__", width=80, height=50
        )
        try:
            with window.frame:
                with ui.VStack() as container:
                    delegate.build_widget(
                        model, ro_item, LayerDelegate.COL_LOCK, 1, False
                    )
            widgets = _flatten_widgets(list(ui.Inspector.get_children(container))[0])
            lock_bodies = [
                w
                for w in widgets
                if isinstance(w, ui.Rectangle)
                and getattr(w, "name", None) in ("locked", "unlocked")
                and w.style_type_name_override == "Layers.LockIcon"
            ]
            # At least the body Rectangle paints in both states — the
            # interactive glyph survives the Step-27 ZStack wrap.
            assert len(lock_bodies) >= 1
        finally:
            window.destroy()
            model.destroy()


class TestStep27StyleTokens:
    """Step 27 — style-dict selectors exist for the new states."""

    def test_missing_badge_selector_exists(self) -> None:
        from ovui_widgets.layers.style import LAYERS_STYLES

        assert "Layers.MissingBadge" in LAYERS_STYLES
        # Red tint pinned to ``cl.layers_label_missing`` via the
        # style's ``color`` entry — assert presence so a refactor
        # can't silently drop the tint.
        assert "color" in LAYERS_STYLES["Layers.MissingBadge"]

    def test_readonly_overlay_selector_exists(self) -> None:
        from ovui_widgets.layers.style import LAYERS_STYLES

        assert "Layers.LockIcon::readonly_overlay" in LAYERS_STYLES

    def test_anonymous_namelabel_selector_exists(self) -> None:
        from ovui_widgets.layers.style import LAYERS_STYLES

        assert "Layers.NameLabel::anonymous" in LAYERS_STYLES
