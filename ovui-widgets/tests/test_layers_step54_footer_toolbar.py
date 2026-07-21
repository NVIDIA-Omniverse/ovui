# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 54 — Footer toolbar (Insert / Create / Delete).

Covers:

- :class:`LayerWindow` builds Insert / Create / Delete buttons on the
  footer strip once a model + adapter exist.
- :meth:`LayerWindow._footer_target_and_delete_spec` falls back to
  the root layer when nothing is selected, snaps to the single
  selected :class:`LayerItem` otherwise, and refuses to resolve a
  Delete slot on the root layer.
- :meth:`LayerWindow._refresh_footer_state` flips each button's
  ``enabled`` flag in response to selection changes — Delete stays
  greyed out until a non-root layer is the lone selection.
- :meth:`_on_footer_insert_clicked` opens the Step-36 save-file dialog
  and, on confirm, pushes an :class:`InsertSublayerCommand` with the
  chosen path under the resolved target.
- :meth:`_on_footer_create_clicked` pushes a :class:`CreateSublayerCommand`
  with an empty ``new_layer_path`` — the Step-30 anonymous-mint path
  — without opening a dialog.
- :meth:`_on_footer_delete_clicked` routes through
  :meth:`LayerModel._request_remove_sublayer` so the dirty-layer
  confirm flow (Step 37) is shared with the context-menu Remove
  gesture.
- Frame rebuild nulls the footer handles before repainting so a
  stale button reference can't leak into the next pass.
- :meth:`LayerWindow.destroy` drops the footer handles alongside the
  rest of the window chrome.
"""

from __future__ import annotations

from typing import Any, List, Optional

import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import DefaultLayerSettings, LayerItem, LayerModel, LayerWindow


class _App:
    """Minimal :class:`Application` stand-in for the footer tests."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=False)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_a.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_b.usda")
    return ad


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def window(adapter: MockLayerStackAdapter, app: _App) -> LayerWindow:
    w = LayerWindow(services=app, adapter=adapter, settings=DefaultLayerSettings())
    yield w
    w.destroy()


def _layer_item(model: LayerModel, identifier: str) -> LayerItem:
    """Locate the :class:`LayerItem` for ``identifier`` in the model.

    Walks the tree because the model does not expose an index for us;
    the tree here is shallow enough for an O(N) scan in tests to read
    as noise-free.
    """
    stack: List[LayerItem] = list(model.get_item_children(None))
    while stack:
        node = stack.pop()
        if node.identifier == identifier:
            return node
        stack.extend(model.get_item_children(node))
    raise KeyError(identifier)


# ─── Footer construction ─────────────────────────────────────────────────────


class TestFooterConstruction:
    def test_buttons_built_after_build_ui(self, window: LayerWindow) -> None:
        """All three footer buttons must exist on first paint."""
        window._build_ui()
        assert window._insert_button is not None
        assert window._create_button is not None
        assert window._delete_button is not None

    def test_buttons_are_none_before_build(self, window: LayerWindow) -> None:
        # Construction only caches the options button; footer buttons
        # live on the frame and get built by ``_build_ui``.
        assert window._insert_button is None
        assert window._create_button is None
        assert window._delete_button is None

    def test_rebuild_replaces_handles(self, window: LayerWindow) -> None:
        window._build_ui()
        first_insert = window._insert_button
        first_create = window._create_button
        first_delete = window._delete_button
        assert first_insert is not None
        window._build_ui()
        assert window._insert_button is not first_insert
        assert window._create_button is not first_create
        assert window._delete_button is not first_delete


# ─── Target + delete-spec resolution ─────────────────────────────────────────


class TestFooterTargetResolution:
    def test_no_selection_targets_root(self, window: LayerWindow) -> None:
        window._build_ui()
        target, delete_spec = window._footer_target_and_delete_spec()
        assert target is not None
        assert target.identifier == ROOT_LAYER_IDENTIFIER
        # Root cannot be deleted — delete_spec must be None.
        assert delete_spec is None

    def test_single_layer_selection_targets_that_layer(
        self, window: LayerWindow
    ) -> None:
        window._build_ui()
        model = window._model
        assert model is not None
        child_a = _layer_item(model, "./child_a.usda")
        model.set_selected_items([child_a])
        target, delete_spec = window._footer_target_and_delete_spec()
        assert target is child_a
        assert delete_spec == (ROOT_LAYER_IDENTIFIER, 0)

    def test_multi_layer_selection_falls_back_to_root(
        self, window: LayerWindow
    ) -> None:
        window._build_ui()
        model = window._model
        assert model is not None
        child_a = _layer_item(model, "./child_a.usda")
        child_b = _layer_item(model, "./child_b.usda")
        model.set_selected_items([child_a, child_b])
        target, delete_spec = window._footer_target_and_delete_spec()
        # Multi-select collapses to "no single layer selected" per the
        # plan's "otherwise operate on root" clause.
        assert target is not None
        assert target.identifier == ROOT_LAYER_IDENTIFIER
        assert delete_spec is None

    def test_root_selection_has_no_delete_spec(
        self, window: LayerWindow
    ) -> None:
        window._build_ui()
        model = window._model
        assert model is not None
        root = model.root_item
        assert root is not None
        model.set_selected_items([root])
        target, delete_spec = window._footer_target_and_delete_spec()
        assert target is root
        assert delete_spec is None


# ─── Enabled-state refresh ───────────────────────────────────────────────────


class TestFooterEnabledState:
    def test_default_selection_enables_insert_create_disables_delete(
        self, window: LayerWindow
    ) -> None:
        window._build_ui()
        assert window._insert_button.enabled is True
        assert window._create_button.enabled is True
        assert window._delete_button.enabled is False

    def test_single_non_root_selection_enables_delete(
        self, window: LayerWindow
    ) -> None:
        window._build_ui()
        model = window._model
        assert model is not None
        child_a = _layer_item(model, "./child_a.usda")
        model.set_selected_items([child_a])
        window._refresh_footer_state()
        assert window._delete_button.enabled is True

    def test_root_selection_keeps_delete_disabled(
        self, window: LayerWindow
    ) -> None:
        window._build_ui()
        model = window._model
        assert model is not None
        root = model.root_item
        assert root is not None
        model.set_selected_items([root])
        window._refresh_footer_state()
        assert window._delete_button.enabled is False

    def test_refresh_is_safe_without_buttons(
        self, window: LayerWindow
    ) -> None:
        # Pre-build — no buttons yet. Refresh must be a no-op and
        # must not raise.
        window._refresh_footer_state()

    def test_tree_selection_change_refreshes_footer(
        self, window: LayerWindow
    ) -> None:
        """Routing selection through ``_on_tree_selection_changed`` refreshes."""
        window._build_ui()
        model = window._model
        assert model is not None
        child_a = _layer_item(model, "./child_a.usda")
        assert window._delete_button.enabled is False
        window._on_tree_selection_changed([child_a])
        assert window._delete_button.enabled is True
        window._on_tree_selection_changed([])
        assert window._delete_button.enabled is False


# ─── Click handlers ──────────────────────────────────────────────────────────


class _FakeSaveFileDialog:
    """Captures a :func:`save_file_dialog` call for the footer tests."""

    last: Optional["_FakeSaveFileDialog"] = None

    def __init__(
        self,
        title: str,
        default_name: str,
        on_selected: Any,
        on_cancelled: Any = None,
        filter_ext: str = ".usda",
        default_dir: Any = None,
    ) -> None:
        self.title = title
        self.default_name = default_name
        self.on_selected = on_selected
        self.on_cancelled = on_cancelled
        _FakeSaveFileDialog.last = self

    @classmethod
    def reset(cls) -> None:
        cls.last = None


@pytest.fixture
def fake_save_file_dialog(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Stub out :func:`save_file_dialog` for click-handler tests.

    ``save_file_dialog`` is imported lazily inside
    :meth:`LayerWindow._on_footer_insert_clicked` so we have to patch
    the module-level name in :mod:`ovui_widgets.common.file_dialogs` (the function
    the lazy import resolves) rather than a name in :mod:`ovui_widgets.layers.window`.
    """
    import ovui_widgets.common.file_dialogs as fd

    _FakeSaveFileDialog.reset()
    monkeypatch.setattr(fd, "save_file_dialog", _FakeSaveFileDialog)
    yield _FakeSaveFileDialog


class TestInsertClickHandler:
    def test_insert_opens_dialog_with_target_parent_id(
        self, window: LayerWindow, fake_save_file_dialog: Any
    ) -> None:
        window._build_ui()
        window._on_footer_insert_clicked()
        captured = fake_save_file_dialog.last
        assert captured is not None
        assert ROOT_LAYER_IDENTIFIER in captured.title
        # Default name is blank — the user pastes an existing path.
        assert captured.default_name == ""

    def test_insert_on_confirm_pushes_insert_command(
        self,
        window: LayerWindow,
        app: _App,
        adapter: MockLayerStackAdapter,
        fake_save_file_dialog: Any,
    ) -> None:
        window._build_ui()
        window._on_footer_insert_clicked()
        captured = fake_save_file_dialog.last
        assert captured is not None
        # Simulate the user selecting a file.
        captured.on_selected("./new_inserted.usda")
        # The inserted layer must now sit under the root.
        root_handle = adapter.get_root_layer()
        children = adapter.get_sublayer_identifiers(root_handle)
        assert "./new_inserted.usda" in children
        # Undo must rewind the insertion to exercise the command path.
        app.undo_manager.undo()
        children_after = adapter.get_sublayer_identifiers(root_handle)
        assert "./new_inserted.usda" not in children_after

    def test_insert_targets_selected_layer_when_single_layer_selected(
        self,
        window: LayerWindow,
        app: _App,
        adapter: MockLayerStackAdapter,
        fake_save_file_dialog: Any,
    ) -> None:
        window._build_ui()
        model = window._model
        assert model is not None
        child_a = _layer_item(model, "./child_a.usda")
        model.set_selected_items([child_a])
        window._on_footer_insert_clicked()
        captured = fake_save_file_dialog.last
        assert captured is not None
        assert "./child_a.usda" in captured.title
        # Actually confirm the path so we can verify the parent wiring.
        captured.on_selected("./nested.usda")
        child_handle = adapter.find_layer("./child_a.usda")
        assert child_handle is not None
        nested = adapter.get_sublayer_identifiers(child_handle)
        assert "./nested.usda" in nested

    def test_insert_noop_without_adapter(
        self,
        window: LayerWindow,
        fake_save_file_dialog: Any,
    ) -> None:
        window._build_ui()
        # Detach the adapter after build so the handler sees a missing
        # adapter on click.
        assert window._model is not None
        window._model._adapter = None
        window._on_footer_insert_clicked()
        assert fake_save_file_dialog.last is None


class TestCreateClickHandler:
    def test_create_pushes_anonymous_create_command(
        self,
        window: LayerWindow,
        app: _App,
        adapter: MockLayerStackAdapter,
    ) -> None:
        window._build_ui()
        root_handle = adapter.get_root_layer()
        before = list(adapter.get_sublayer_identifiers(root_handle))
        window._on_footer_create_clicked()
        after = list(adapter.get_sublayer_identifiers(root_handle))
        assert len(after) == len(before) + 1
        # The new identifier must look anonymous — the mock adapter
        # mints ``anon:N`` handles.
        new_ids = [i for i in after if i not in before]
        assert len(new_ids) == 1
        new_handle = adapter.find_layer(new_ids[0])
        assert new_handle is not None
        assert adapter.is_anonymous(new_handle) is True
        # And the command must be on the undo stack.
        app.undo_manager.undo()
        rolled_back = adapter.get_sublayer_identifiers(root_handle)
        assert new_ids[0] not in rolled_back

    def test_create_targets_selected_layer(
        self,
        window: LayerWindow,
        adapter: MockLayerStackAdapter,
    ) -> None:
        window._build_ui()
        model = window._model
        assert model is not None
        child_b = _layer_item(model, "./child_b.usda")
        model.set_selected_items([child_b])
        window._on_footer_create_clicked()
        child_handle = adapter.find_layer("./child_b.usda")
        assert child_handle is not None
        nested = adapter.get_sublayer_identifiers(child_handle)
        assert len(nested) == 1

    def test_create_noop_without_app(self, adapter: MockLayerStackAdapter) -> None:
        # Headless construction: the button is still built but clicking
        # it must not raise — ``_on_footer_create_clicked`` bails on a
        # missing ``app``.
        w = LayerWindow(
            services=None, adapter=adapter, settings=DefaultLayerSettings()
        )
        try:
            w._build_ui()
            w._on_footer_create_clicked()
        finally:
            w.destroy()


class TestDeleteClickHandler:
    def test_delete_removes_selected_sublayer(
        self,
        window: LayerWindow,
        app: _App,
        adapter: MockLayerStackAdapter,
    ) -> None:
        window._build_ui()
        model = window._model
        assert model is not None
        child_a = _layer_item(model, "./child_a.usda")
        model.set_selected_items([child_a])
        window._refresh_footer_state()
        window._on_footer_delete_clicked()
        root_handle = adapter.get_root_layer()
        remaining = adapter.get_sublayer_identifiers(root_handle)
        assert "./child_a.usda" not in remaining
        # Undo must restore it — the click must have travelled through
        # the undoable command pipeline, not a bare adapter call.
        app.undo_manager.undo()
        restored = adapter.get_sublayer_identifiers(root_handle)
        assert "./child_a.usda" in restored

    def test_delete_noop_when_no_selection(
        self,
        window: LayerWindow,
        adapter: MockLayerStackAdapter,
    ) -> None:
        window._build_ui()
        root_handle = adapter.get_root_layer()
        before = list(adapter.get_sublayer_identifiers(root_handle))
        window._on_footer_delete_clicked()
        after = list(adapter.get_sublayer_identifiers(root_handle))
        assert after == before

    def test_delete_noop_when_root_selected(
        self,
        window: LayerWindow,
        adapter: MockLayerStackAdapter,
    ) -> None:
        window._build_ui()
        model = window._model
        assert model is not None
        root = model.root_item
        assert root is not None
        model.set_selected_items([root])
        window._refresh_footer_state()
        assert window._delete_button.enabled is False
        # Click the handler anyway — it must be a no-op.
        before = list(
            adapter.get_sublayer_identifiers(adapter.get_root_layer())
        )
        window._on_footer_delete_clicked()
        after = list(
            adapter.get_sublayer_identifiers(adapter.get_root_layer())
        )
        assert after == before


# ─── Window lifecycle ───────────────────────────────────────────────────────


class TestFooterLifecycle:
    def test_destroy_drops_footer_handles(
        self,
        adapter: MockLayerStackAdapter,
        app: _App,
    ) -> None:
        w = LayerWindow(
            services=app, adapter=adapter, settings=DefaultLayerSettings()
        )
        w._build_ui()
        assert w._insert_button is not None
        w.destroy()
        assert w._insert_button is None
        assert w._create_button is None
        assert w._delete_button is None

    def test_style_entries_present(self) -> None:
        """The five footer style selectors must exist on ``LAYERS_STYLES``."""
        from ovui_widgets.layers.style import LAYERS_STYLES

        for key in (
            "Layers.Footer",
            "Layers.FooterSeparator",
            "Layers.FooterButton",
            "Layers.FooterButton:hovered",
            "Layers.FooterButton:pressed",
            "Layers.FooterButton:disabled",
        ):
            assert key in LAYERS_STYLES, f"Missing footer style: {key}"
