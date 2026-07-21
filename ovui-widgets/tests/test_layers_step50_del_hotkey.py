# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 50 — ``Del`` hotkey deletes selected prim specs.

Covers:

- :attr:`ManagedWindow.is_focused` proxies the underlying ``ui.Window``
  focus bit and tolerates a destroyed window.
- :meth:`LayerWindow.get_selected_items` exposes the model's
  selection list (union of :class:`LayerItem` and
  :class:`PrimSpecItem`) to the application-level keyboard dispatcher.
- :meth:`LayerModel.set_selected_items` now stores
  :class:`PrimSpecItem` entries alongside :class:`LayerItem` entries so
  Phase J rows round-trip through the selection snapshot (Step 50
  widened the Step 16 filter).
- :meth:`Application._on_key_pressed` with ``_KEY_DELETE`` routes to the
  Layers prim-spec deletion path when the Layers window owns focus and a
  :class:`PrimSpecItem` sits in the selection; otherwise it falls through
  to :meth:`Application._delete_selected` (the Stage prim-delete path).
- The dispatched :class:`RemovePrimSpecsCommand` removes the selected
  prim specs via the :class:`LayerStackAdapter` and
  :class:`~ovui_widgets.common.undo.UndoManager` undo restores them bit-identical.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from ovui_data_adapters.common import PrimSpecDescriptor, PrimSpecifier

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import LayerItem, LayerModel, PrimSpecItem
from ovui_widgets.layers.commands import RemovePrimSpecsCommand

_MOD_CTRL = 2
_KEY_DELETE = 261
_KEY_BACKSPACE = 259


# ─── ManagedWindow.is_focused ────────────────────────────────────────────────


class TestManagedWindowIsFocused:

    def test_is_focused_reflects_underlying_window(self) -> None:
        from ovui_widgets.common.managed_window import ManagedWindow
        w = ManagedWindow("__probe_is_focused__", width=10, height=10)
        # Fresh ui.Window defaults to not-focused (no ImGui focus frame).
        assert w.is_focused is False
        w.destroy()

    def test_is_focused_false_after_destroy(self) -> None:
        from ovui_widgets.common.managed_window import ManagedWindow
        w = ManagedWindow("__probe_is_focused_destroy__", width=10, height=10)
        w.destroy()
        assert w.is_focused is False


# ─── LayerModel selection — accepts PrimSpecItem (Step 50 widens Step 16) ───


class TestLayerModelSelectionWithPrimSpecs:

    def _seed_adapter(self) -> MockLayerStackAdapter:
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
        )
        return adapter

    def test_accepts_layer_and_prim_spec_items(self) -> None:
        adapter = self._seed_adapter()
        model = LayerModel(adapter=adapter)
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        spec = PrimSpecItem(
            layer,
            PrimSpecDescriptor(
                path="/World",
                type_name="Xform",
                specifier=PrimSpecifier.DEF,
                has_reference=False,
                has_payload=False,
                is_instanceable=False,
            ),
        )
        model.set_selected_items([layer, spec])
        stored = model.selected_items
        assert layer in stored
        assert spec in stored
        model.destroy()

    def test_rejects_other_types(self) -> None:
        adapter = self._seed_adapter()
        model = LayerModel(adapter=adapter)
        model.set_selected_items([object(), "not-an-item", 42])
        assert model.selected_items == []
        model.destroy()


# ─── LayerWindow.get_selected_items ─────────────────────────────────────────


def _can_create_window() -> bool:
    try:
        import omni.ui as ui
        w = ui.Window("__probe_step50__", width=10, height=10)
        w.destroy()
        return True
    except Exception:
        return False


_WINDOW_AVAILABLE = _can_create_window()
_skip_no_window = pytest.mark.skipif(
    not _WINDOW_AVAILABLE,
    reason="ui.Window creation not available without ui.init()",
)


@_skip_no_window
class TestLayerWindowGetSelectedItems:

    def test_returns_empty_when_no_model(self) -> None:
        from ovui_widgets.layers import LayerWindow
        w = LayerWindow(services=MagicMock())
        # No adapter → no model built yet.
        assert w.get_selected_items() == []
        w.destroy()

    def test_returns_model_selection(self) -> None:
        from ovui_widgets.layers import LayerWindow
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
        )
        w = LayerWindow(services=MagicMock())
        try:
            # set_adapter materialises the model (mirrors test_layer_window).
            w.set_adapter(adapter)
            model = w._model
            assert model is not None
            layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
            spec = PrimSpecItem(
                layer,
                PrimSpecDescriptor(
                    path="/World",
                    type_name="Xform",
                    specifier=PrimSpecifier.DEF,
                    has_reference=False,
                    has_payload=False,
                    is_instanceable=False,
                ),
            )
            model.set_selected_items([layer, spec])
            out = w.get_selected_items()
            assert layer in out
            assert spec in out
        finally:
            w.destroy()


# ─── Application._on_key_pressed — Del scoped to the Layers window ──────────


def _make_app():
    """Create a minimal Application-like object for dispatch tests."""
    from ovui_widgets.app.application import Application
    Application._instance = None
    with patch("ovui_widgets.app.application.SnapSystem"), \
         patch("ovui_widgets.app.application.GridSnapProvider"), \
         patch("ovui_widgets.app.application.SurfaceSnapProvider"):
        app = Application.__new__(Application)
        app._settings = MagicMock()
        app._settings.get.return_value = "dark"
        app._settings.subscribe.return_value = MagicMock()
        app._undo_manager = UndoManager()
        app._selection_bus = SelectionBus()
        app._stage_adapter = None
        app._layer_adapter = None
        app._main_win = None
        app._stage_window = None
        app._viewport_window = None
        app._property_window = None
        app._layer_window = None
        app._content_window = None
        app._pending_callbacks = []
        app._running = False
        app._dockspace = None
        app._status_bar = None
        app._current_stage_sub = None
        app._stage_change_listeners = []
        app._snap_system = MagicMock()
        app._snap_sub = MagicMock()
        app._theme_sub = MagicMock()
        Application._instance = app
    return app


def teardown_function():
    from ovui_widgets.app.application import Application
    Application._instance = None
    SelectionBus._instance = None


def _make_layer_window_with_spec(
    adapter: MockLayerStackAdapter,
    *,
    layer_id: str,
    spec_path: str,
):
    """Build a LayerItem + PrimSpecItem pair whose identity matches the adapter.

    Returns ``(layer_item, prim_spec_item)``.
    """
    layer = LayerItem(adapter, layer_id)
    desc = PrimSpecDescriptor(
        path=spec_path,
        type_name="Xform",
        specifier=PrimSpecifier.DEF,
        has_reference=False,
        has_payload=False,
        is_instanceable=False,
    )
    spec = PrimSpecItem(layer, desc)
    return layer, spec


class TestDelHotkeyScoping:

    def test_fallthrough_when_no_layer_window(self) -> None:
        app = _make_app()
        app._delete_selected = MagicMock()
        app._on_key_pressed(_KEY_DELETE, 0, True)
        app._delete_selected.assert_called_once()

    def test_fallthrough_when_layer_window_not_focused(self) -> None:
        app = _make_app()
        lw = MagicMock()
        lw.is_focused = False
        app._layer_window = lw
        app._delete_selected = MagicMock()
        app._on_key_pressed(_KEY_DELETE, 0, True)
        app._delete_selected.assert_called_once()
        lw.get_selected_items.assert_not_called()

    def test_layers_focused_but_no_adapter_consumes_key(self) -> None:
        app = _make_app()
        lw = MagicMock()
        lw.is_focused = True
        app._layer_window = lw
        app._layer_adapter = None
        app._delete_selected = MagicMock()
        app._on_key_pressed(_KEY_DELETE, 0, True)
        # Layers owns focus → never fall through to Stage delete.
        app._delete_selected.assert_not_called()

    def test_layers_focused_no_prim_spec_selection_consumes_key(self) -> None:
        app = _make_app()
        adapter = MockLayerStackAdapter()
        app._layer_adapter = adapter
        lw = MagicMock()
        lw.is_focused = True
        # Only a LayerItem is selected — Step 50 ignores layer deletion
        # (the context menu owns layer-removal flow).
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        lw.get_selected_items.return_value = [layer]
        app._layer_window = lw
        app._delete_selected = MagicMock()
        app._on_key_pressed(_KEY_DELETE, 0, True)
        app._delete_selected.assert_not_called()

    def test_layers_focused_with_prim_spec_pushes_command(self) -> None:
        app = _make_app()
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec(ROOT_LAYER_IDENTIFIER, "/World", "<usda-world>")
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
        )
        app._layer_adapter = adapter
        lw = MagicMock()
        lw.is_focused = True
        _, spec = _make_layer_window_with_spec(
            adapter, layer_id=ROOT_LAYER_IDENTIFIER, spec_path="/World"
        )
        lw.get_selected_items.return_value = [spec]
        app._layer_window = lw
        app._delete_selected = MagicMock()

        app._on_key_pressed(_KEY_DELETE, 0, True)

        app._delete_selected.assert_not_called()
        # Spec was removed via the adapter.
        with pytest.raises(KeyError):
            adapter.export_prim_spec(ROOT_LAYER_IDENTIFIER, "/World")
        # Undo restores it bit-identical.
        assert app._undo_manager.undo() is True
        assert (
            adapter.export_prim_spec(ROOT_LAYER_IDENTIFIER, "/World")
            == "<usda-world>"
        )

    def test_layers_focused_multi_selection_deletes_all(self) -> None:
        app = _make_app()
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec(ROOT_LAYER_IDENTIFIER, "/World", "<a>")
        adapter.set_prim_spec(ROOT_LAYER_IDENTIFIER, "/Sphere", "<b>")
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
        )
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/Sphere", type_name="Sphere"
        )
        app._layer_adapter = adapter
        lw = MagicMock()
        lw.is_focused = True
        _, spec_a = _make_layer_window_with_spec(
            adapter, layer_id=ROOT_LAYER_IDENTIFIER, spec_path="/World"
        )
        _, spec_b = _make_layer_window_with_spec(
            adapter, layer_id=ROOT_LAYER_IDENTIFIER, spec_path="/Sphere"
        )
        # Mix in a stray LayerItem — the handler must filter to
        # PrimSpecItem entries only.
        layer = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        lw.get_selected_items.return_value = [spec_a, layer, spec_b]
        app._layer_window = lw

        app._on_key_pressed(_KEY_DELETE, 0, True)

        with pytest.raises(KeyError):
            adapter.export_prim_spec(ROOT_LAYER_IDENTIFIER, "/World")
        with pytest.raises(KeyError):
            adapter.export_prim_spec(ROOT_LAYER_IDENTIFIER, "/Sphere")
        # Single undo frame restores both specs.
        assert app._undo_manager.undo() is True
        assert (
            adapter.export_prim_spec(ROOT_LAYER_IDENTIFIER, "/World")
            == "<a>"
        )
        assert (
            adapter.export_prim_spec(ROOT_LAYER_IDENTIFIER, "/Sphere")
            == "<b>"
        )

    def test_backspace_also_scoped_to_layers(self) -> None:
        app = _make_app()
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec(ROOT_LAYER_IDENTIFIER, "/World", "<u>")
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
        )
        app._layer_adapter = adapter
        lw = MagicMock()
        lw.is_focused = True
        _, spec = _make_layer_window_with_spec(
            adapter, layer_id=ROOT_LAYER_IDENTIFIER, spec_path="/World"
        )
        lw.get_selected_items.return_value = [spec]
        app._layer_window = lw
        app._delete_selected = MagicMock()

        app._on_key_pressed(_KEY_BACKSPACE, 0, True)

        app._delete_selected.assert_not_called()
        with pytest.raises(KeyError):
            adapter.export_prim_spec(ROOT_LAYER_IDENTIFIER, "/World")

    def test_not_pressed_does_not_dispatch(self) -> None:
        """Key-release events are ignored by the shortcut dispatcher — the
        Step 50 path must honour that contract so focus-while-holding-Del
        doesn't double-fire on release.
        """
        app = _make_app()
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec(ROOT_LAYER_IDENTIFIER, "/World", "<u>")
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
        )
        app._layer_adapter = adapter
        lw = MagicMock()
        lw.is_focused = True
        _, spec = _make_layer_window_with_spec(
            adapter, layer_id=ROOT_LAYER_IDENTIFIER, spec_path="/World"
        )
        lw.get_selected_items.return_value = [spec]
        app._layer_window = lw

        app._on_key_pressed(_KEY_DELETE, 0, False)

        # Spec survives — release events short-circuit before the
        # scoping check runs.
        assert (
            adapter.export_prim_spec(ROOT_LAYER_IDENTIFIER, "/World") == "<u>"
        )

    def test_helper_reports_fallthrough_without_layer_window(self) -> None:
        app = _make_app()
        assert app._delete_selected_prim_specs_in_layers() is False

    def test_helper_reports_consumed_when_layers_focused(self) -> None:
        app = _make_app()
        lw = MagicMock()
        lw.is_focused = True
        lw.get_selected_items.return_value = []
        app._layer_window = lw
        adapter = MockLayerStackAdapter()
        app._layer_adapter = adapter
        assert app._delete_selected_prim_specs_in_layers() is True

    def test_command_pushed_is_remove_prim_specs(self) -> None:
        """Verify the pushed command type — guards against silent regressions
        where the handler might route to a different (or non-undoable)
        delete path.
        """
        app = _make_app()
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec(ROOT_LAYER_IDENTIFIER, "/World", "<u>")
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
        )
        app._layer_adapter = adapter
        app._undo_manager = MagicMock()
        lw = MagicMock()
        lw.is_focused = True
        _, spec = _make_layer_window_with_spec(
            adapter, layer_id=ROOT_LAYER_IDENTIFIER, spec_path="/World"
        )
        lw.get_selected_items.return_value = [spec]
        app._layer_window = lw

        app._on_key_pressed(_KEY_DELETE, 0, True)

        app._undo_manager.push.assert_called_once()
        pushed = app._undo_manager.push.call_args.args[0]
        assert isinstance(pushed, RemovePrimSpecsCommand)

    def test_does_not_interfere_with_stage_delete(self) -> None:
        """When Layers is *not* focused but a stage window is, Del must
        reach :meth:`_delete_selected` and the Layers adapter must never
        be touched — even if a spec selection exists in the Layers model
        (stale selection after panel focus change).
        """
        app = _make_app()
        adapter = MockLayerStackAdapter()
        adapter.set_prim_spec(ROOT_LAYER_IDENTIFIER, "/World", "<u>")
        adapter.set_prim_spec_descriptor(
            ROOT_LAYER_IDENTIFIER, "/World", type_name="Xform"
        )
        app._layer_adapter = adapter
        lw = MagicMock()
        lw.is_focused = False
        _, spec = _make_layer_window_with_spec(
            adapter, layer_id=ROOT_LAYER_IDENTIFIER, spec_path="/World"
        )
        lw.get_selected_items.return_value = [spec]
        app._layer_window = lw
        app._delete_selected = MagicMock()

        app._on_key_pressed(_KEY_DELETE, 0, True)

        app._delete_selected.assert_called_once()
        # Spec untouched — Layers path never ran.
        assert (
            adapter.export_prim_spec(ROOT_LAYER_IDENTIFIER, "/World") == "<u>"
        )
