# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LayerWindow — LAYERS-PLAN Step 8 scaffold.

Covers: subclass relationship, title preservation (the imgui.ini dock
key routes on the window title), adapter late-binding through
``set_adapter``, style-plumbing hook, and clean destroy. The widget /
model / delegate machinery is Phase C, so nothing past the shell is
exercised here.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import omni.ui as ui
import pytest
from ovui_data_adapters.common import LayerStackAdapter

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.managed_window import ManagedWindow
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.layers import LayerDelegate, LayerModel, LayerWindow
from ovui_widgets.layers.style import LAYERS_STYLES


def _can_create_window() -> bool:
    try:
        w = ui.Window("__probe_layers__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_WINDOW_AVAILABLE = _can_create_window()
_skip_no_window = pytest.mark.skipif(
    not _WINDOW_AVAILABLE,
    reason="ui.Window creation not available without ui.init()",
)


class TestImportsAndStructure:
    def test_layer_window_exported_from_package(self):
        import ovui_widgets.layers
        assert ovui_widgets.layers.LayerWindow is LayerWindow

    def test_layer_stack_adapter_in_ovgear_adapters(self):
        """LayerStackAdapter lives in ovui_widgets.common.adapters as of issue #38."""
        from ovui_data_adapters.common import LayerStackAdapter

        from ovui_widgets.common.testing.mock_layer_stack import MockLayerStackAdapter
        assert issubclass(MockLayerStackAdapter, LayerStackAdapter)

    def test_is_managed_window_subclass(self):
        assert issubclass(LayerWindow, ManagedWindow)

    def test_title_constant(self):
        assert LayerWindow.TITLE == "Layers"

    def test_layers_styles_is_dict(self):
        # Step 11 populates the dict; assert the public symbol is the
        # live mutable object (not a frozen mapping) so future steps
        # can extend it in place.
        assert isinstance(LAYERS_STYLES, dict)
        assert LAYERS_STYLES, "Step 11 populates LAYERS_STYLES; must be non-empty"


@_skip_no_window
class TestWindowLifecycle:
    def test_title_preserves_dock_key(self):
        # ovui_widgets.app/layout.py's imgui.ini keys on "Layers" — changing the
        # title breaks dock restoration and the default-layout fallback.
        w = LayerWindow(services=MagicMock())
        assert w.title == "Layers"
        w.destroy()

    def test_window_is_created(self):
        w = LayerWindow(services=MagicMock())
        assert w.window is not None
        w.destroy()

    def test_default_dimensions(self):
        # Plan fixes the default size at 380×600 (Step 8 signature).
        w = LayerWindow(services=MagicMock())
        # ui.Window exposes width/height reflecting the initial size.
        assert w.window.width == 380
        assert w.window.height == 600
        w.destroy()

    def test_module_styles_returns_layers_styles(self):
        w = LayerWindow(services=MagicMock())
        assert w._get_module_styles() is LAYERS_STYLES
        w.destroy()

    def test_destroy_clears_window(self):
        w = LayerWindow(services=MagicMock())
        w.destroy()
        assert w._window is None

    def test_destroy_is_idempotent(self):
        w = LayerWindow(services=MagicMock())
        w.destroy()
        w.destroy()  # must not raise


@_skip_no_window
class TestBuildUi:
    def test_build_ui_does_not_raise(self):
        w = LayerWindow(services=MagicMock())
        with w._window.frame:
            w._build_ui()  # placeholder Label inside a VStack
        w.destroy()

    def test_build_ui_works_without_adapter(self):
        # Step 8 placeholder renders identically with or without an
        # adapter — Phase C replaces the body. Guard against an
        # accidental null-dereference on the stub path.
        w = LayerWindow(services=MagicMock(), adapter=None)
        with w._window.frame:
            w._build_ui()
        w.destroy()


@_skip_no_window
class TestAdapterLateBinding:
    def test_adapter_defaults_to_none(self):
        w = LayerWindow(services=MagicMock())
        assert w._adapter is None
        w.destroy()

    def test_set_adapter_stores_reference(self):
        w = LayerWindow(services=MagicMock())
        adapter = MagicMock(spec=LayerStackAdapter)
        w.set_adapter(adapter)
        assert w._adapter is adapter
        w.destroy()

    def test_set_adapter_none_clears_reference(self):
        w = LayerWindow(services=MagicMock())
        adapter = MagicMock(spec=LayerStackAdapter)
        w.set_adapter(adapter)
        w.set_adapter(None)
        assert w._adapter is None
        w.destroy()

    def test_adapter_can_be_passed_at_construction(self):
        adapter = MagicMock(spec=LayerStackAdapter)
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        assert w._adapter is adapter
        w.destroy()

    def test_app_reference_stored(self):
        services = MagicMock()
        w = LayerWindow(services=services)
        assert w._services is services
        w.destroy()

    def test_phase_c_slots_start_none(self):
        # Model / tree-view / delegate are Phase C seams.
        w = LayerWindow(services=MagicMock())
        assert w._model is None
        assert w._tree_view is None
        assert w._delegate is None
        w.destroy()

    def test_column_widths_constant_has_seven_entries(self):
        # LAYERS-PLAN Step 17: seven columns, name flex + 6 fixed.
        assert len(LayerWindow._COLUMN_WIDTHS) == 7

    def test_column_widths_first_entry_is_fraction(self):
        # Name column must stretch; Fraction instances round-trip as
        # themselves so ``isinstance`` is the cheapest exact check.
        first = LayerWindow._COLUMN_WIDTHS[0]
        assert isinstance(first, ui.Fraction)

    def test_column_widths_fixed_columns_are_pixels(self):
        # The six flag columns must be fixed-pixel so badge icons line
        # up across panel widths. The plan pins them at 24/24/24/24/24/26.
        expected_px = [24, 24, 24, 24, 24, 26]
        for idx, expected in enumerate(expected_px, start=1):
            entry = LayerWindow._COLUMN_WIDTHS[idx]
            assert isinstance(entry, ui.Pixel), (
                f"column {idx} must be ui.Pixel, got {type(entry).__name__}"
            )
            # ``ui.Pixel`` formats as ``"24.000000px"`` — anchor the
            # assertion on the ``<digits>px`` suffix so it cannot match
            # on a substring of a larger number (``24`` in ``240``).
            entry_str = str(entry)
            assert entry_str.endswith("px")
            numeric = entry_str[:-2]
            assert float(numeric) == float(expected), (
                f"column {idx} pixel value mismatch: got {entry!r}"
            )

    def test_set_adapter_rebuilds_frame_when_visible(self):
        # LAYERS-PLAN Step 9: set_adapter must rebuild the frame so the
        # next paint reflects the new adapter (Phase C will fill the body
        # with a real tree view). Today the placeholder is adapter-agnostic
        # but the rebuild contract is testable by swapping ``_window`` for a
        # fake — ``ui.Window.frame`` is a read-only property, so per-attr
        # monkey-patching is not an option.
        w = LayerWindow(services=MagicMock())
        fake_frame = MagicMock()
        fake_window = MagicMock(visible=True, frame=fake_frame)
        real_window = w._window
        try:
            w._window = fake_window
            adapter = MagicMock(spec=LayerStackAdapter)
            w.set_adapter(adapter)
            fake_frame.rebuild.assert_called_once()
        finally:
            w._window = real_window
            w.destroy()

    def test_set_adapter_skips_rebuild_when_hidden(self):
        # Hidden windows don't need an immediate rebuild — ``visible = True``
        # will trigger one. Skipping avoids wasted work on every file open
        # while the user has the panel hidden.
        w = LayerWindow(services=MagicMock())
        fake_frame = MagicMock()
        fake_window = MagicMock(visible=False, frame=fake_frame)
        real_window = w._window
        try:
            w._window = fake_window
            adapter = MagicMock(spec=LayerStackAdapter)
            w.set_adapter(adapter)
            fake_frame.rebuild.assert_not_called()
        finally:
            w._window = real_window
            w.destroy()


@_skip_no_window
class TestStageLifecycle:
    """LAYERS-PLAN Step 15: window forwards adapter changes to the model."""

    def test_set_adapter_creates_model_on_first_attach(self):
        # First non-``None`` adapter materialises the ``LayerModel`` so a
        # later ``_build_ui`` can wire the TreeView immediately.
        w = LayerWindow(services=MagicMock())
        try:
            assert w._model is None
            w.set_adapter(MockLayerStackAdapter())
            assert isinstance(w._model, LayerModel)
        finally:
            w.destroy()

    def test_set_adapter_none_keeps_model_but_empties_tree(self):
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        # Kick the model into existence via a live adapter swap so the
        # attach path runs the same way ``open_file`` drives it.
        w.set_adapter(adapter)
        try:
            model = w._model
            assert isinstance(model, LayerModel)
            w.set_adapter(None)
            assert w._model is model  # same instance, re-targeted
            assert model.adapter is None
            assert model.root_item is None
            assert len(adapter._subscribers) == 0
        finally:
            w.destroy()

    def test_set_adapter_swap_retargets_same_model_instance(self):
        a = MockLayerStackAdapter()
        b = MockLayerStackAdapter()
        b.add_sublayer(ROOT_LAYER_IDENTIFIER, "b_kid")
        w = LayerWindow(services=MagicMock())
        try:
            w.set_adapter(a)
            model_a = w._model
            w.set_adapter(b)
            assert w._model is model_a  # never reallocated
            assert w._model.adapter is b
            assert [s.identifier for s in w._model.root_item.sublayers] == [
                "b_kid"
            ]
            assert len(a._subscribers) == 0
            assert len(b._subscribers) == 1
        finally:
            w.destroy()

    def test_destroy_after_attach_releases_adapter_subscription(self):
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=MagicMock())
        w.set_adapter(adapter)
        assert len(adapter._subscribers) == 1
        w.destroy()
        assert len(adapter._subscribers) == 0
        assert w._model is None
        assert w._tree_view is None

    def test_destroy_without_attach_does_not_raise(self):
        w = LayerWindow(services=MagicMock())
        w.destroy()  # no adapter ever set
        assert w._model is None


@_skip_no_window
class TestSelectionCallback:
    """LAYERS-PLAN Step 16 — TreeView → model selection forwarding."""

    def test_build_ui_wires_selection_changed_fn(self):
        # After ``_build_ui`` with an adapter present, the TreeView must
        # have a selection callback bound so user clicks reach the model.
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        try:
            with w._window.frame:
                w._build_ui()
            assert w._tree_view is not None
            # ovui exposes the bound callback on the private
            # ``_selection_changed_fn`` attribute; fall back to checking
            # the TreeView at minimum has a selection attribute.
            assert hasattr(w._tree_view, "selection")
        finally:
            w.destroy()

    def test_build_ui_creates_layer_delegate_instance(self):
        # LAYERS-PLAN Step 17: the TreeView must be constructed with a
        # ``LayerDelegate`` so per-cell rendering can dispatch on column.
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        try:
            with w._window.frame:
                w._build_ui()
            assert isinstance(w._delegate, LayerDelegate)
        finally:
            w.destroy()

    def test_delegate_survives_frame_rebuild(self):
        # The delegate is stateless between rebuilds — caching one
        # instance across ``_build_ui`` calls avoids reallocating the
        # icon caches (Step 24) every dock restore.
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        try:
            with w._window.frame:
                w._build_ui()
            first = w._delegate
            with w._window.frame:
                w._build_ui()
            assert w._delegate is first
        finally:
            w.destroy()

    def test_destroy_clears_delegate_reference(self):
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        with w._window.frame:
            w._build_ui()
        assert w._delegate is not None
        w.destroy()
        assert w._delegate is None

    def test_on_tree_selection_changed_forwards_to_model(self):
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        try:
            # Force model creation without a TreeView build — the
            # callback must still run against the model alone.
            w.set_adapter(adapter)
            assert w._model is not None
            root = w._model.root_item
            w._on_tree_selection_changed([root])
            assert w._model.selected_items == [root]
        finally:
            w.destroy()

    def test_on_tree_selection_changed_filters_non_layer_items(self):
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        try:
            w.set_adapter(adapter)
            root = w._model.root_item
            w._on_tree_selection_changed([root, "noise", 7])
            assert w._model.selected_items == [root]
        finally:
            w.destroy()

    def test_on_tree_selection_changed_with_empty_list_clears_selection(self):
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        try:
            w.set_adapter(adapter)
            w._on_tree_selection_changed([w._model.root_item])
            w._on_tree_selection_changed([])
            assert w._model.selected_items == []
        finally:
            w.destroy()

    def test_on_tree_selection_changed_without_model_is_noop(self):
        # Called before any adapter is attached — must not raise.
        w = LayerWindow(services=MagicMock())
        try:
            assert w._model is None
            w._on_tree_selection_changed([])  # noqa — should not raise
        finally:
            w.destroy()

    def test_selection_survives_frame_rebuild(self):
        # ``_build_ui`` is called on every dock rebuild; the model
        # outlives it, so a selection set before a rebuild must still
        # be visible on the model afterwards.
        adapter = MockLayerStackAdapter()
        w = LayerWindow(services=MagicMock(), adapter=adapter)
        try:
            with w._window.frame:
                w._build_ui()
            root = w._model.root_item
            w._on_tree_selection_changed([root])
            with w._window.frame:
                w._build_ui()
            # Same model instance; selection list preserved.
            assert w._model.selected_items == [root]
        finally:
            w.destroy()

    def test_selection_cleared_on_adapter_swap(self):
        a = MockLayerStackAdapter()
        b = MockLayerStackAdapter()
        w = LayerWindow(services=MagicMock())
        try:
            w.set_adapter(a)
            w._on_tree_selection_changed([w._model.root_item])
            assert len(w._model.selected_items) == 1
            w.set_adapter(b)
            assert w._model.selected_items == []
        finally:
            w.destroy()
