# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 39 — context-menu edit-target and
sublayer-creation entries.

Step 39 replaces the Step-38 "Refresh" and placeholder "Create
Sublayer" proof-of-life entries with the real edit-target and
sublayer-creation entries:

1. **Set as Authoring Layer** — on a layer row, hidden if the row is
   already the current edit target; disabled (greyed out) if the
   layer is muted / locked / read-only. Click pushes
   :class:`SetEditTargetCommand`.
2. **Create Sublayer** / **Insert Sublayer...** / **New Anonymous
   Sublayer** (on-layer) — visible on every layer row, disabled on
   non-writable layers. Click opens :func:`save_file_dialog` (for
   Create / Insert) or pushes :class:`CreateSublayerCommand` with
   an empty path (for Anonymous).
3. The same three entries scoped to the root layer on an empty-area
   right-click, gated on :func:`is_empty_area` + :func:`can_edit_root`.

Coverage:

- Default-registration: all seven entries exist after
  :class:`ContextMenuBuilder` construction.
- Predicate gating: on-layer ctx surfaces the on-layer quartet;
  empty-area ctx surfaces the empty-area trio; the two menus stay
  disjoint.
- Click handlers push the expected commands with the expected
  parameters.
- File dialog seam: Create / Insert entries open a
  :func:`save_file_dialog`; on confirm the command pushes; on
  cancel nothing pushes.
- ``enabled_fn=is_writable`` disables the on-layer trio (and the
  Set-Authoring entry) when the layer is muted / locked.
- ``no-app`` / ``no-adapter`` guards: click handlers are no-ops
  when headless (a destroyed window may reach the handler late).
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
from ovui_widgets.layers.commands.layer_commands import SetEditTargetCommand
from ovui_widgets.layers.commands.sublayer_commands import (
    CreateSublayerCommand,
    InsertSublayerCommand,
)
from ovui_widgets.layers.context_menu import (
    can_edit_root,
    is_empty_area,
    is_layer_item,
    is_not_current_edit_target,
    is_writable,
)

# ── Fixtures ────────────────────────────────────────────────────────


class _App:
    """Minimal :class:`Application` stand-in — carries the two
    dependencies Step-39 click handlers consult (``undo_manager`` and
    ``selection_bus``)."""

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


def _entry_by_label_and_group(
    builder: ContextMenuBuilder, label: str, group: int
) -> ContextMenuEntry:
    """Look up the single entry matching ``(label, group)``.

    The Step-39 entries register two "Create Sublayer" entries (one
    on-layer, one empty-area) distinguished by their ``show_fn``; the
    group is identical for both. To pick one unambiguously we also
    filter by a probe predicate: the on-layer variant has
    :func:`is_layer_item` in its ``show_fn``, the empty-area variant
    has :func:`is_empty_area`.
    """
    matches = [
        e for e in builder.entries
        if e.label == label and e.group == group
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"expected 1 entry with label={label!r}, got {len(matches)}"
        )
    return matches[0]


def _on_layer_create(builder: ContextMenuBuilder, label: str) -> ContextMenuEntry:
    matches = [
        e for e in builder.entries
        if e.label == label and is_layer_item in e.show_fn
    ]
    assert len(matches) == 1, f"on-layer {label!r} not found"
    return matches[0]


def _empty_area_create(
    builder: ContextMenuBuilder, label: str
) -> ContextMenuEntry:
    matches = [
        e for e in builder.entries
        if e.label == label and is_empty_area in e.show_fn
    ]
    assert len(matches) == 1, f"empty-area {label!r} not found"
    return matches[0]


# ── Default registration ────────────────────────────────────────────


class TestDefaultEntries:
    def test_seven_entries_registered(self, builder) -> None:
        # Step 39 registered 7; Step 40 appends 4 more file-I/O +
        # removal entries. Count the Step-39 subset by filtering on
        # the four Step-39 labels so this test keeps locking Step 39's
        # own contract (and does not double-count later steps).
        step39_labels = {
            "Set as Authoring Layer",
            "Create Sublayer",
            "Insert Sublayer...",
            "New Anonymous Sublayer",
        }
        step39_entries = [
            e for e in builder.entries if e.label in step39_labels
        ]
        assert len(step39_entries) == 7

    def test_set_authoring_layer_entry_exists(self, builder) -> None:
        entry = next(
            e for e in builder.entries
            if e.label == "Set as Authoring Layer"
        )
        assert is_layer_item in entry.show_fn
        assert is_not_current_edit_target in entry.show_fn
        assert entry.enabled_fn is is_writable

    def test_on_layer_trio_exists(self, builder) -> None:
        for label in (
            "Create Sublayer",
            "Insert Sublayer...",
            "New Anonymous Sublayer",
        ):
            entry = _on_layer_create(builder, label)
            assert is_layer_item in entry.show_fn
            assert entry.enabled_fn is is_writable

    def test_empty_area_trio_exists(self, builder) -> None:
        for label in (
            "Create Sublayer",
            "Insert Sublayer...",
            "New Anonymous Sublayer",
        ):
            entry = _empty_area_create(builder, label)
            assert is_empty_area in entry.show_fn
            assert can_edit_root in entry.show_fn


# ── Predicate filtering ─────────────────────────────────────────────


class TestPredicateFiltering:
    def test_empty_area_surfaces_only_empty_area_trio(
        self, builder, model
    ) -> None:
        ctx = _ctx(model, item=None)
        visible = builder.build_entries_for(ctx)
        labels = [e.label for e in visible]
        # On-layer trio filtered out (is_layer_item fails).
        assert "Set as Authoring Layer" not in labels
        # Empty-area trio passes.
        assert labels.count("Create Sublayer") == 1
        assert labels.count("Insert Sublayer...") == 1
        assert labels.count("New Anonymous Sublayer") == 1

    def test_layer_row_surfaces_on_layer_quartet(
        self, builder, model
    ) -> None:
        item = _find(model, "./child_a.usda")
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        # Empty-area trio filtered out (is_empty_area fails).
        assert labels.count("Create Sublayer") == 1
        assert labels.count("Insert Sublayer...") == 1
        assert labels.count("New Anonymous Sublayer") == 1
        # Set-authoring entry visible (./child_a is not current edit
        # target — root is by default).
        assert "Set as Authoring Layer" in labels

    def test_set_authoring_hidden_when_item_is_current_edit_target(
        self, builder, model
    ) -> None:
        item = _find(model, "./child_a.usda")
        model._edit_target_identifier = item.identifier
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        assert "Set as Authoring Layer" not in labels

    def test_set_authoring_hidden_on_empty_area(
        self, builder, model
    ) -> None:
        visible = builder.build_entries_for(_ctx(model, item=None))
        labels = [e.label for e in visible]
        assert "Set as Authoring Layer" not in labels

    def test_on_layer_entries_still_visible_when_not_writable(
        self, builder, model, adapter
    ) -> None:
        # Writable gating is an enabled_fn, not a show_fn — muted
        # layers still show the entry (greyed out) so the user sees
        # the affordance.
        item = _find(model, "./child_a.usda")
        adapter.set_mute(item.identifier, True)
        item.invalidate_flags()
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        for label in (
            "Create Sublayer",
            "Insert Sublayer...",
            "New Anonymous Sublayer",
        ):
            assert label in labels

    def test_empty_area_hidden_when_root_not_writable(
        self, builder, model, adapter
    ) -> None:
        # can_edit_root is in show_fn for the empty-area entries;
        # a locked root layer hides them entirely.
        root = model.root_item
        assert root is not None
        adapter.set_lock(root.identifier, True)
        root.invalidate_flags()
        visible = builder.build_entries_for(_ctx(model, item=None))
        labels = [e.label for e in visible]
        assert "Create Sublayer" not in labels
        assert "Insert Sublayer..." not in labels
        assert "New Anonymous Sublayer" not in labels


# ── enabled_fn behaviour ────────────────────────────────────────────


class TestEnabledFn:
    def test_set_authoring_enabled_on_writable_layer(
        self, builder, model
    ) -> None:
        item = _find(model, "./child_a.usda")
        entry = next(
            e for e in builder.entries
            if e.label == "Set as Authoring Layer"
        )
        assert entry.enabled_fn is not None
        assert entry.enabled_fn(_ctx(model, item=item)) is True

    def test_set_authoring_disabled_on_muted_layer(
        self, builder, model, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        adapter.set_mute(item.identifier, True)
        item.invalidate_flags()
        entry = next(
            e for e in builder.entries
            if e.label == "Set as Authoring Layer"
        )
        assert entry.enabled_fn(_ctx(model, item=item)) is False

    def test_set_authoring_disabled_on_locked_layer(
        self, builder, model, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        adapter.set_lock(item.identifier, True)
        item.invalidate_flags()
        entry = next(
            e for e in builder.entries
            if e.label == "Set as Authoring Layer"
        )
        assert entry.enabled_fn(_ctx(model, item=item)) is False

    def test_on_layer_create_disabled_on_muted_layer(
        self, builder, model, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        adapter.set_mute(item.identifier, True)
        item.invalidate_flags()
        entry = _on_layer_create(builder, "Create Sublayer")
        assert entry.enabled_fn(_ctx(model, item=item)) is False


# ── Set as Authoring Layer click handler ────────────────────────────


class TestSetAuthoringClick:
    def test_click_pushes_set_edit_target_command(
        self, builder, model, app
    ) -> None:
        item = _find(model, "./child_a.usda")
        entry = next(
            e for e in builder.entries
            if e.label == "Set as Authoring Layer"
        )
        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]
        entry.click_fn(_ctx(model, item=item, services=app))
        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, SetEditTargetCommand)
        assert cmd._new_target == item.identifier

    def test_click_actually_switches_edit_target(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER
        entry = next(
            e for e in builder.entries
            if e.label == "Set as Authoring Layer"
        )
        entry.click_fn(_ctx(model, item=item, services=app))
        assert adapter.get_edit_target_identifier() == item.identifier

    def test_click_noop_when_app_is_none(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        entry = next(
            e for e in builder.entries
            if e.label == "Set as Authoring Layer"
        )
        # Should not raise.
        entry.click_fn(_ctx(model, item=item, services=None))

    def test_click_noop_when_item_is_none(
        self, builder, model, app
    ) -> None:
        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)
        entry = next(
            e for e in builder.entries
            if e.label == "Set as Authoring Layer"
        )
        entry.click_fn(_ctx(model, item=None, services=app))
        assert pushed == []


# ── Create Sublayer (on-layer) click handler ────────────────────────


class TestCreateSublayerClick:
    def test_click_opens_save_file_dialog(
        self, builder, model, app, monkeypatch
    ) -> None:
        calls: List[Tuple[str, str]] = []

        def _fake_dialog(
            title, default_name, on_selected, on_cancelled=None, **kw
        ):
            calls.append((title, default_name))
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _fake_dialog
        )

        item = _find(model, "./child_a.usda")
        entry = _on_layer_create(builder, "Create Sublayer")
        entry.click_fn(_ctx(model, item=item, services=app))

        assert len(calls) == 1
        title, default_name = calls[0]
        assert item.identifier in title or "Create Sublayer" in title
        assert default_name == "untitled.usda"

    def test_dialog_confirm_pushes_create_sublayer_command(
        self, builder, model, app, adapter, monkeypatch
    ) -> None:
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
        entry = _on_layer_create(builder, "Create Sublayer")
        entry.click_fn(_ctx(model, item=item, services=app))

        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]

        # Simulate the user confirming the dialog with a path.
        assert len(captured) == 1
        captured[0]("./new_grandchild.usda")

        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, CreateSublayerCommand)
        assert cmd._parent_id == item.identifier
        assert cmd._position == -1
        assert cmd._new_layer_path == "./new_grandchild.usda"
        assert cmd._transfer_root_content is False

    def test_dialog_cancel_pushes_nothing(
        self, builder, model, app, monkeypatch
    ) -> None:
        # Cancelling dialog: don't invoke on_selected.
        def _cancel_dialog(
            title, default_name, on_selected, on_cancelled=None, **kw
        ):
            if on_cancelled is not None:
                on_cancelled()
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _cancel_dialog
        )

        pushed: List[Any] = []
        app.undo_manager.push = lambda cmd: pushed.append(cmd)

        item = _find(model, "./child_a.usda")
        entry = _on_layer_create(builder, "Create Sublayer")
        entry.click_fn(_ctx(model, item=item, services=app))

        assert pushed == []

    def test_click_noop_when_app_is_none(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        entry = _on_layer_create(builder, "Create Sublayer")
        # Should not raise.
        entry.click_fn(_ctx(model, item=item, services=None))


# ── Insert Sublayer (on-layer) click handler ────────────────────────


class TestInsertSublayerClick:
    def test_click_opens_file_picker_with_blank_default(
        self, builder, model, app, monkeypatch
    ) -> None:
        calls: List = []

        def _fake_dialog(
            title, default_name, on_selected, on_cancelled=None, **kw
        ):
            calls.append((title, default_name))
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _fake_dialog
        )

        item = _find(model, "./child_a.usda")
        entry = _on_layer_create(builder, "Insert Sublayer...")
        entry.click_fn(_ctx(model, item=item, services=app))

        assert len(calls) == 1
        title, default_name = calls[0]
        assert "Insert Sublayer" in title
        assert default_name == ""

    def test_dialog_confirm_pushes_insert_sublayer_command(
        self, builder, model, app, adapter, monkeypatch
    ) -> None:
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
        entry = _on_layer_create(builder, "Insert Sublayer...")
        entry.click_fn(_ctx(model, item=item, services=app))

        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]

        captured[0]("./existing_layer.usda")

        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, InsertSublayerCommand)
        assert cmd._parent_id == item.identifier
        assert cmd._position == -1
        assert cmd._sublayer_path == "./existing_layer.usda"


# ── New Anonymous Sublayer click handler ────────────────────────────


class TestNewAnonymousClick:
    def test_click_pushes_create_sublayer_with_empty_path(
        self, builder, model, app
    ) -> None:
        item = _find(model, "./child_a.usda")
        entry = _on_layer_create(builder, "New Anonymous Sublayer")
        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]
        entry.click_fn(_ctx(model, item=item, services=app))

        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, CreateSublayerCommand)
        assert cmd._parent_id == item.identifier
        assert cmd._new_layer_path == ""
        assert cmd._transfer_root_content is False

    def test_click_does_not_open_dialog(
        self, builder, model, app, monkeypatch
    ) -> None:
        calls: List = []
        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog",
            lambda *a, **k: calls.append(1),
        )
        item = _find(model, "./child_a.usda")
        entry = _on_layer_create(builder, "New Anonymous Sublayer")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert calls == []

    def test_click_mints_anonymous_layer_in_adapter(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        parent_handle = adapter.find_layer(item.identifier)
        assert parent_handle is not None
        children_before = adapter.get_sublayer_identifiers(parent_handle)
        entry = _on_layer_create(builder, "New Anonymous Sublayer")
        entry.click_fn(_ctx(model, item=item, services=app))
        children_after = adapter.get_sublayer_identifiers(parent_handle)
        # One new sublayer appended.
        assert len(children_after) == len(children_before) + 1
        new_id = children_after[-1]
        new_handle = adapter.find_layer(new_id)
        assert new_handle is not None
        # ``new_layer_path=""`` → anonymous.
        assert adapter.is_anonymous(new_handle) is True


# ── Empty-area entries ──────────────────────────────────────────────


class TestEmptyAreaEntries:
    def test_empty_area_create_opens_dialog_and_pushes_command(
        self, builder, model, app, adapter, monkeypatch
    ) -> None:
        captured: List = []

        def _fake_dialog(
            title, default_name, on_selected, on_cancelled=None, **kw
        ):
            captured.append(on_selected)
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _fake_dialog
        )

        entry = _empty_area_create(builder, "Create Sublayer")
        entry.click_fn(_ctx(model, item=None, services=app))
        assert len(captured) == 1

        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]
        captured[0]("./new_root_sub.usda")

        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, CreateSublayerCommand)
        # Parent is the root layer.
        assert cmd._parent_id == model.root_item.identifier
        assert cmd._new_layer_path == "./new_root_sub.usda"

    def test_empty_area_insert_pushes_insert_command(
        self, builder, model, app, monkeypatch
    ) -> None:
        captured: List = []

        def _fake_dialog(
            title, default_name, on_selected, on_cancelled=None, **kw
        ):
            captured.append(on_selected)
            return None

        monkeypatch.setattr(
            "ovui_widgets.common.file_dialogs.save_file_dialog", _fake_dialog
        )

        entry = _empty_area_create(builder, "Insert Sublayer...")
        entry.click_fn(_ctx(model, item=None, services=app))
        assert len(captured) == 1

        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]
        captured[0]("./root_import.usda")

        assert len(pushed) == 1
        cmd = pushed[0]
        assert isinstance(cmd, InsertSublayerCommand)
        assert cmd._parent_id == model.root_item.identifier
        assert cmd._sublayer_path == "./root_import.usda"

    def test_empty_area_anonymous_mints_under_root(
        self, builder, model, app, adapter
    ) -> None:
        root_handle = adapter.get_root_layer()
        children_before = adapter.get_sublayer_identifiers(root_handle)
        entry = _empty_area_create(builder, "New Anonymous Sublayer")
        entry.click_fn(_ctx(model, item=None, services=app))
        children_after = adapter.get_sublayer_identifiers(root_handle)
        assert len(children_after) == len(children_before) + 1
        new_handle = adapter.find_layer(children_after[-1])
        assert new_handle is not None
        assert adapter.is_anonymous(new_handle) is True


# ── is_empty_area predicate ─────────────────────────────────────────


class TestIsEmptyAreaPredicate:
    def test_true_when_item_is_none(self, model) -> None:
        assert is_empty_area(_ctx(model, item=None)) is True

    def test_false_when_item_is_set(self, model) -> None:
        item = _find(model, "./child_a.usda")
        assert is_empty_area(_ctx(model, item=item)) is False

    def test_independent_of_selection(self, model) -> None:
        # Even with a non-empty selection, an empty-area context
        # (item is None) still reports True — the predicate keys off
        # the clicked row, not the global selection.
        sel = [_find(model, "./child_a.usda")]
        assert (
            is_empty_area(_ctx(model, item=None, tree_selection=sel))
            is True
        )


# ── Undo round-trip ─────────────────────────────────────────────────


class TestUndoRoundTrip:
    def test_set_authoring_undoes_to_prior_target(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER
        entry = next(
            e for e in builder.entries
            if e.label == "Set as Authoring Layer"
        )
        entry.click_fn(_ctx(model, item=item, services=app))
        assert adapter.get_edit_target_identifier() == item.identifier
        app.undo_manager.undo()
        assert (
            adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER
        )

    def test_new_anonymous_undoes_to_prior_child_count(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        parent_handle = adapter.find_layer(item.identifier)
        before = list(adapter.get_sublayer_identifiers(parent_handle))
        entry = _on_layer_create(builder, "New Anonymous Sublayer")
        entry.click_fn(_ctx(model, item=item, services=app))
        after = list(adapter.get_sublayer_identifiers(parent_handle))
        assert len(after) == len(before) + 1
        app.undo_manager.undo()
        undone = list(adapter.get_sublayer_identifiers(parent_handle))
        assert undone == before
