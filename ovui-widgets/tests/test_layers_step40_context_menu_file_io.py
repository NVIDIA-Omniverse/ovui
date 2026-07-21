# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 40 — context-menu file-I/O and removal entries.

Step 40 adds four entries to the Layers right-click menu:

1. **Save** — on-layer, gated on ``is_layer_item`` + ``is_layer_dirty``.
   Click routes through :meth:`LayerModel._request_save`, which pushes
   :class:`~ovui_widgets.layers.commands.SaveLayerCommand` for concrete layers
   and forwards to Save-As for anonymous layers.
2. **Save As...** — on-layer, gated on ``is_layer_item`` +
   ``is_not_root_layer``. Click opens the Step-36 file picker through
   :meth:`LayerModel._request_save_as`.
3. **Reload** — on-layer, gated on ``is_layer_item`` +
   ``is_not_anonymous``. Click routes through
   :meth:`LayerModel._request_reload`, which opens the Step-37
   confirm-reload dialog for dirty layers.
4. **Remove** — on-layer, gated on ``is_layer_item`` +
   ``is_not_root_layer``. Click resolves the (parent, position) pair
   from the clicked item and routes through
   :meth:`LayerModel._request_remove_sublayer`, which opens the
   Step-37 confirm-dirty-remove dialog for dirty layers.

Coverage:

- Default registration: the four entries exist after
  :class:`ContextMenuBuilder` construction, with the right ``group``
  and ``show_fn``.
- Predicate gating: clean vs dirty, root vs sublayer, anonymous vs
  concrete all filter as prescribed.
- Click handlers delegate to ``LayerModel._request_*`` entry points
  (rather than pushing commands directly), so the Step-37 confirm
  dialogs and the Step-36 file picker activate through the same
  seam the toolbar / column-2 click uses.
- No-app / no-adapter / no-parent guards are no-ops rather than
  raising.
"""

from __future__ import annotations

from typing import Any, List, Tuple

import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoManager
from ovui_widgets.layers import (
    ContextMenuBuilder,
    ContextMenuEntry,
    LayerItem,
    LayerModel,
    MenuContext,
)
from ovui_widgets.layers.commands.file_io_commands import (
    ReloadLayerCommand,
    SaveLayerCommand,
)
from ovui_widgets.layers.commands.sublayer_commands import RemoveSublayerCommand
from ovui_widgets.layers.context_menu import (
    GROUP_DESTRUCTIVE,
    GROUP_FILE_IO,
    is_layer_dirty,
    is_layer_item,
    is_not_anonymous,
    is_not_root_layer,
)

# ── Fixtures ────────────────────────────────────────────────────────


class _App:
    """Minimal :class:`Application` stand-in for context-menu click tests."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    ad = MockLayerStackAdapter(include_session=True)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_a.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_b.usda")
    return ad


@pytest.fixture
def app() -> _App:
    return _App()


@pytest.fixture
def model(adapter, app) -> LayerModel:
    m = LayerModel(adapter, services=app)
    yield m
    m.destroy()


@pytest.fixture
def builder(model, app) -> ContextMenuBuilder:
    return ContextMenuBuilder(model=model, services=app)


def _find(model: LayerModel, identifier: str) -> LayerItem:
    item = model._items_by_id[identifier]
    assert isinstance(item, LayerItem)
    return item


def _ctx(
    model: LayerModel,
    item=None,
    tree_selection: List[LayerItem] = None,
    services=None,
) -> MenuContext:
    return MenuContext(
        item=item,
        tree_selection=list(tree_selection or []),
        model=model,
        services=services,
    )


def _entry(builder: ContextMenuBuilder, label: str) -> ContextMenuEntry:
    """Pick the single Step-40 entry by label.

    Each Step-40 label is unique across the registered entry list
    (Create / Insert / New Anonymous also share labels across on-layer
    and empty-area variants — but none of those collide with Save /
    Save As... / Reload / Remove). A direct label match is safe here.
    """
    matches = [e for e in builder.entries if e.label == label]
    assert len(matches) == 1, (
        f"expected 1 entry with label={label!r}, got {len(matches)}"
    )
    return matches[0]


# ── Default registration ────────────────────────────────────────────


class TestDefaultRegistration:
    def test_total_entry_count_grows_by_four(self, builder) -> None:
        # Step 39 registered 7 entries; Step 40 adds 4 more; Step 41
        # adds 4 more (mute, lock, lock tree, unlock tree); Step 42
        # adds 2 more (merge down, flatten sublayers).
        assert len(builder.entries) == 17

    def test_save_entry_registered(self, builder) -> None:
        entry = _entry(builder, "Save")
        assert entry.group == GROUP_FILE_IO
        assert is_layer_item in entry.show_fn
        assert is_layer_dirty in entry.show_fn

    def test_save_as_entry_registered(self, builder) -> None:
        entry = _entry(builder, "Save As...")
        assert entry.group == GROUP_FILE_IO
        assert is_layer_item in entry.show_fn
        assert is_not_root_layer in entry.show_fn

    def test_reload_entry_registered(self, builder) -> None:
        entry = _entry(builder, "Reload")
        assert entry.group == GROUP_FILE_IO
        assert is_layer_item in entry.show_fn
        assert is_not_anonymous in entry.show_fn

    def test_remove_entry_registered(self, builder) -> None:
        entry = _entry(builder, "Remove")
        assert entry.group == GROUP_DESTRUCTIVE
        assert is_layer_item in entry.show_fn
        assert is_not_root_layer in entry.show_fn


# ── Predicate filtering ─────────────────────────────────────────────


class TestPredicateFiltering:
    def test_save_hidden_on_clean_layer(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        assert "Save" not in labels

    def test_save_visible_on_dirty_layer(
        self, builder, model, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        adapter.set_dirty(item.identifier, True)
        item.invalidate_flags()
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        assert "Save" in labels

    def test_save_hidden_on_empty_area(self, builder, model) -> None:
        visible = builder.build_entries_for(_ctx(model, item=None))
        labels = [e.label for e in visible]
        assert "Save" not in labels

    def test_save_as_visible_on_non_root(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        assert "Save As..." in labels

    def test_save_as_hidden_on_root(self, builder, model) -> None:
        root = model.root_item
        assert root is not None
        visible = builder.build_entries_for(_ctx(model, item=root))
        labels = [e.label for e in visible]
        assert "Save As..." not in labels

    def test_reload_visible_on_concrete_layer(
        self, builder, model
    ) -> None:
        item = _find(model, "./child_a.usda")
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        assert "Reload" in labels

    def test_reload_hidden_on_anonymous_layer(
        self, builder, model, adapter
    ) -> None:
        # Mint an anonymous sublayer and gate on it.
        anon_id = adapter.create_sublayer(
            ROOT_LAYER_IDENTIFIER, -1, "", False
        )
        # Build an item for it (tree rebuild happens on child refresh,
        # but a direct ``LayerItem`` works for predicate tests).
        anon_item = LayerItem(adapter, anon_id)
        visible = builder.build_entries_for(_ctx(model, item=anon_item))
        labels = [e.label for e in visible]
        assert "Reload" not in labels

    def test_remove_visible_on_non_root(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        assert "Remove" in labels

    def test_remove_hidden_on_root(self, builder, model) -> None:
        root = model.root_item
        assert root is not None
        visible = builder.build_entries_for(_ctx(model, item=root))
        labels = [e.label for e in visible]
        assert "Remove" not in labels


# ── Save click ──────────────────────────────────────────────────────


class TestSaveClick:
    def test_click_on_dirty_concrete_layer_pushes_save_command(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        adapter.set_dirty(item.identifier, True)
        item.invalidate_flags()
        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]

        entry = _entry(builder, "Save")
        entry.click_fn(_ctx(model, item=item, services=app))

        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, SaveLayerCommand)
        assert cmd._identifier == item.identifier

    def test_click_on_clean_concrete_layer_still_routes_through_model(
        self, builder, model, app
    ) -> None:
        # ``_request_save`` tolerates a clean layer (the menu's
        # ``is_layer_dirty`` gate normally filters this out, but a
        # direct click-handler invocation from a test must still be
        # safe — the model pushes the command regardless of the dirty
        # flag, matching the column-2 click).
        item = _find(model, "./child_a.usda")
        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]

        entry = _entry(builder, "Save")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert len(pushed) == 1
        assert isinstance(pushed[0], SaveLayerCommand)

    def test_click_on_anonymous_layer_forwards_to_save_as(
        self, builder, model, app, adapter, monkeypatch
    ) -> None:
        # Mint an anonymous sublayer under root.
        anon_id = adapter.create_sublayer(
            ROOT_LAYER_IDENTIFIER, -1, "", False
        )
        # The anonymous layer is now in the adapter; build a standalone
        # LayerItem for it (the tree's ``_items_by_id`` cache tracks
        # events asynchronously, but a bare LayerItem reads flags
        # directly from the adapter).
        anon_item = LayerItem(adapter, anon_id)
        assert anon_item.is_anonymous is True

        # Intercept the save-as dialog so we never touch ovui.
        dialog_calls: List[str] = []

        def _fake_dialog(
            title, default_name, on_selected, on_cancelled=None, **kw
        ):
            dialog_calls.append(title)
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _fake_dialog
        )

        entry = _entry(builder, "Save")
        entry.click_fn(_ctx(model, item=anon_item, services=app))
        # ``_request_save`` saw ``is_anonymous`` and forwarded to
        # ``_request_save_as``, which opened the picker.
        assert len(dialog_calls) == 1

    def test_click_noop_on_non_layer_item(
        self, builder, model, app
    ) -> None:
        entry = _entry(builder, "Save")
        entry.click_fn(_ctx(model, item=None, services=app))  # must not raise


# ── Save As click ───────────────────────────────────────────────────


class TestSaveAsClick:
    def test_click_opens_save_file_dialog(
        self, builder, model, app, monkeypatch
    ) -> None:
        dialog_calls: List[Tuple[str, str]] = []

        def _fake_dialog(
            title, default_name, on_selected, on_cancelled=None, **kw
        ):
            dialog_calls.append((title, default_name))
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _fake_dialog
        )
        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Save As...")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert len(dialog_calls) == 1

    def test_dialog_confirm_pushes_save_as_command(
        self, builder, model, app, adapter, monkeypatch
    ) -> None:
        from ovui_widgets.layers.commands.file_io_commands import SaveLayerAsCommand

        captured: List = []

        def _fake_dialog(
            title, default_name, on_selected, on_cancelled=None, **kw
        ):
            captured.append(on_selected)
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _fake_dialog
        )

        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Save As...")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert len(captured) == 1

        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]
        captured[0]("./child_a_copy.usda")

        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, SaveLayerAsCommand)
        assert cmd._source_identifier == item.identifier
        assert cmd._new_path == "./child_a_copy.usda"

    def test_click_noop_when_app_is_none(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Save As...")
        # Must not raise even without an app.
        entry.click_fn(_ctx(model, item=item, services=None))


# ── Reload click ────────────────────────────────────────────────────


class TestReloadClick:
    def test_click_on_clean_layer_pushes_reload_command(
        self, builder, model, app
    ) -> None:
        item = _find(model, "./child_a.usda")
        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]
        entry = _entry(builder, "Reload")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, ReloadLayerCommand)
        assert cmd._identifier == item.identifier

    def test_click_on_dirty_layer_opens_confirm_dialog(
        self, builder, model, app, adapter, monkeypatch
    ) -> None:
        # Step-37 ``confirm_reload_dialog`` guards the dirty path.
        dialog_calls: List[str] = []

        def _fake_confirm(
            layer_name, on_reload, on_cancel=None, **kw
        ):
            dialog_calls.append(layer_name)
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_reload_dialog", _fake_confirm
        )

        item = _find(model, "./child_a.usda")
        adapter.set_dirty(item.identifier, True)
        item.invalidate_flags()

        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]

        entry = _entry(builder, "Reload")
        entry.click_fn(_ctx(model, item=item, services=app))

        # Dialog opened; no command pushed yet.
        assert len(dialog_calls) == 1
        assert pushed == []

    def test_click_noop_when_app_is_none(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Reload")
        entry.click_fn(_ctx(model, item=item, services=None))  # must not raise


# ── Remove click ────────────────────────────────────────────────────


class TestRemoveClick:
    def test_click_on_clean_sublayer_pushes_remove_command(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]
        entry = _entry(builder, "Remove")
        entry.click_fn(_ctx(model, item=item, services=app))

        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, RemoveSublayerCommand)
        assert cmd._parent_id == ROOT_LAYER_IDENTIFIER
        assert cmd._position == 0

    def test_click_actually_removes_from_adapter(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        root_handle = adapter.get_root_layer()
        before = list(adapter.get_sublayer_identifiers(root_handle))
        assert item.identifier in before

        entry = _entry(builder, "Remove")
        entry.click_fn(_ctx(model, item=item, services=app))

        after = list(adapter.get_sublayer_identifiers(root_handle))
        assert item.identifier not in after

    def test_click_on_dirty_sublayer_opens_confirm_dialog(
        self, builder, model, app, adapter, monkeypatch
    ) -> None:
        dialog_calls: List[str] = []

        def _fake_dialog(
            layer_name,
            on_save_and_remove,
            on_remove_without_saving,
            on_cancel=None,
            **kw,
        ):
            dialog_calls.append(layer_name)
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.dialogs.confirm_dirty_remove_dialog", _fake_dialog
        )

        item = _find(model, "./child_a.usda")
        adapter.set_dirty(item.identifier, True)
        item.invalidate_flags()

        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]

        entry = _entry(builder, "Remove")
        entry.click_fn(_ctx(model, item=item, services=app))

        # Dialog opened; no command pushed yet.
        assert len(dialog_calls) == 1
        assert pushed == []

    def test_undo_restores_removed_sublayer(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        root_handle = adapter.get_root_layer()
        before = list(adapter.get_sublayer_identifiers(root_handle))

        entry = _entry(builder, "Remove")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert list(adapter.get_sublayer_identifiers(root_handle)) != before

        app.undo_manager.undo()
        after_undo = list(adapter.get_sublayer_identifiers(root_handle))
        assert after_undo == before

    def test_click_noop_when_item_has_no_parent(
        self, builder, model, app
    ) -> None:
        # Root has ``_parent is None``; even though ``is_not_root_layer``
        # would filter the entry out, a direct click-fn invocation on
        # root must not blow up.
        root = model.root_item
        assert root is not None
        assert root._parent is None
        entry = _entry(builder, "Remove")
        entry.click_fn(_ctx(model, item=root, services=app))  # must not raise

    def test_click_noop_when_adapter_is_none(
        self, builder, model, app
    ) -> None:
        item = _find(model, "./child_a.usda")
        model._adapter = None
        entry = _entry(builder, "Remove")
        entry.click_fn(_ctx(model, item=item, services=app))  # must not raise


# ── Group ordering / separators ─────────────────────────────────────


class TestCanonicalOrder:
    def test_file_io_entries_follow_create_entries(
        self, builder, model, adapter
    ) -> None:
        # Make the layer dirty so Save surfaces.
        item = _find(model, "./child_a.usda")
        adapter.set_dirty(item.identifier, True)
        item.invalidate_flags()
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        # Create-group entries (GROUP_CREATE=20) precede file-I/O
        # entries (GROUP_FILE_IO=40).
        create_idx = labels.index("Create Sublayer")
        save_idx = labels.index("Save")
        assert create_idx < save_idx

    def test_remove_entry_follows_file_io_group(
        self, builder, model, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        adapter.set_dirty(item.identifier, True)
        item.invalidate_flags()
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        # Remove (GROUP_DESTRUCTIVE=50) follows file-I/O trio.
        save_idx = labels.index("Save")
        remove_idx = labels.index("Remove")
        assert save_idx < remove_idx
