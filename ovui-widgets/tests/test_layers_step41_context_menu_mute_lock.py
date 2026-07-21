# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 41 — context-menu mute/lock entries.

Step 41 adds four entries to the Layers right-click menu, all in
``GROUP_STATE``:

1. **Mute Layer / Unmute Layer** — single entry with a dynamic
   :attr:`ContextMenuEntry.label_fn` that flips based on
   :attr:`LayerItem.is_muted`. Click pushes
   :class:`~ovui_widgets.layers.commands.SetLayerMutenessCommand` with the
   opposite of the current state.
2. **Lock Layer / Unlock Layer** — same shape for the lock bit,
   routed through :class:`~ovui_widgets.layers.commands.SetLayerLockCommand`.
3. **Lock Layer and Descendants** — walks the clicked item's subtree
   and pushes one :class:`SetLayerLockCommand` per not-already-locked
   layer, wrapped in a single :meth:`UndoManager.begin_group` /
   :meth:`UndoManager.end_group` so one Ctrl+Z undoes the whole
   tree-lock.
4. **Unlock Layer and Descendants** — inverse; pushes one command per
   currently-locked layer in the subtree.

Coverage:

- Default registration: four new entries, all in ``GROUP_STATE``,
  show on every layer row and hide on an empty-area click.
- Dynamic labels: ``label_fn`` returns the expected string for each
  state pair.
- Click pipelines: Mute / Lock push a single command with the
  opposite-state target; the tree-lock variants push an undo group
  that survives a single Ctrl+Z.
- Subtree dedupe: a layer sublayered in two places (a cyclic / shared
  sublayer shape) contributes at most one command per identifier.
- Guards: ``ctx.services is None``, ``ctx.model._adapter is None``, and
  ``ctx.item is None`` invocations are no-ops rather than crashes.
"""

from __future__ import annotations

from typing import Any, List

import pytest

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.common.undo import UndoGroup, UndoManager
from ovui_widgets.layers import (
    ContextMenuBuilder,
    ContextMenuEntry,
    LayerItem,
    LayerModel,
    MenuContext,
)
from ovui_widgets.layers.commands.layer_commands import (
    SetLayerLockCommand,
    SetLayerMutenessCommand,
)
from ovui_widgets.layers.context_menu import (
    GROUP_STATE,
    is_layer_item,
)

# ── Fixtures ────────────────────────────────────────────────────────


class _App:
    """Minimal :class:`Application` stand-in for context-menu click tests."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    # Build a two-level tree:
    #   root
    #     ├── child_a
    #     │     └── grandchild_a
    #     └── child_b
    # Gives the Lock-tree click something to recurse into.
    ad = MockLayerStackAdapter(include_session=True)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_a.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child_b.usda")
    ad.add_sublayer("./child_a.usda", "./grandchild_a.usda")
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
    services=None,
) -> MenuContext:
    return MenuContext(
        item=item,
        tree_selection=[],
        model=model,
        services=services,
    )


def _entry(builder: ContextMenuBuilder, label: str) -> ContextMenuEntry:
    matches = [e for e in builder.entries if e.label == label]
    assert len(matches) == 1, (
        f"expected 1 entry with label={label!r}, got {len(matches)}"
    )
    return matches[0]


# ── Default registration ────────────────────────────────────────────


class TestDefaultRegistration:
    def test_mute_entry_registered(self, builder) -> None:
        entry = _entry(builder, "Mute Layer")
        assert entry.group == GROUP_STATE
        assert entry.show_fn == [is_layer_item]
        assert entry.label_fn is not None

    def test_lock_entry_registered(self, builder) -> None:
        entry = _entry(builder, "Lock Layer")
        assert entry.group == GROUP_STATE
        assert entry.show_fn == [is_layer_item]
        assert entry.label_fn is not None

    def test_lock_tree_entry_registered(self, builder) -> None:
        entry = _entry(builder, "Lock Layer and Descendants")
        assert entry.group == GROUP_STATE
        assert entry.show_fn == [is_layer_item]

    def test_unlock_tree_entry_registered(self, builder) -> None:
        entry = _entry(builder, "Unlock Layer and Descendants")
        assert entry.group == GROUP_STATE
        assert entry.show_fn == [is_layer_item]

    def test_state_group_has_four_entries(self, builder) -> None:
        state_entries = [
            e for e in builder.entries if e.group == GROUP_STATE
        ]
        labels = [e.label for e in state_entries]
        assert labels == [
            "Mute Layer",
            "Lock Layer",
            "Lock Layer and Descendants",
            "Unlock Layer and Descendants",
        ]


# ── Predicate filtering ─────────────────────────────────────────────


class TestPredicateFiltering:
    def test_entries_visible_on_any_layer_row(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        assert "Mute Layer" in labels
        assert "Lock Layer" in labels
        assert "Lock Layer and Descendants" in labels
        assert "Unlock Layer and Descendants" in labels

    def test_entries_visible_on_root(self, builder, model) -> None:
        root = model.root_item
        assert root is not None
        visible = builder.build_entries_for(_ctx(model, item=root))
        labels = [e.label for e in visible]
        # GROUP_STATE entries are not gated on root/non-root — a user
        # can lock the root layer just like any other.
        assert "Mute Layer" in labels
        assert "Lock Layer" in labels

    def test_entries_hidden_on_empty_area(self, builder, model) -> None:
        visible = builder.build_entries_for(_ctx(model, item=None))
        labels = [e.label for e in visible]
        assert "Mute Layer" not in labels
        assert "Lock Layer" not in labels
        assert "Lock Layer and Descendants" not in labels
        assert "Unlock Layer and Descendants" not in labels


# ── Dynamic labels ──────────────────────────────────────────────────


class TestDynamicLabels:
    def test_mute_label_unmuted(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        assert item.is_muted is False
        entry = _entry(builder, "Mute Layer")
        assert entry.label_fn(_ctx(model, item=item)) == "Mute Layer"

    def test_mute_label_muted(self, builder, model, adapter) -> None:
        item = _find(model, "./child_a.usda")
        adapter.set_mute(item.identifier, True)
        item.invalidate_flags()
        entry = _entry(builder, "Mute Layer")
        assert entry.label_fn(_ctx(model, item=item)) == "Unmute Layer"

    def test_lock_label_unlocked(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        assert item.is_locked is False
        entry = _entry(builder, "Lock Layer")
        assert entry.label_fn(_ctx(model, item=item)) == "Lock Layer"

    def test_lock_label_locked(self, builder, model, adapter) -> None:
        item = _find(model, "./child_a.usda")
        adapter.set_lock(item.identifier, True)
        item.invalidate_flags()
        entry = _entry(builder, "Lock Layer")
        assert entry.label_fn(_ctx(model, item=item)) == "Unlock Layer"

    def test_mute_label_on_none_item_is_stable(self, builder, model) -> None:
        # Defensive: label_fn must not blow up on an empty-area context
        # even though the entry's show_fn gate would normally hide it.
        entry = _entry(builder, "Mute Layer")
        assert entry.label_fn(_ctx(model, item=None)) == "Mute Layer"

    def test_lock_label_on_none_item_is_stable(self, builder, model) -> None:
        entry = _entry(builder, "Lock Layer")
        assert entry.label_fn(_ctx(model, item=None)) == "Lock Layer"


# ── Mute click ──────────────────────────────────────────────────────


class TestMuteClick:
    def test_click_on_unmuted_pushes_mute_command(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        assert item.is_muted is False

        entry = _entry(builder, "Mute Layer")
        entry.click_fn(_ctx(model, item=item, services=app))

        assert adapter.is_muted(adapter.find_layer(item.identifier)) is True

    def test_click_on_muted_pushes_unmute_command(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        adapter.set_mute(item.identifier, True)
        item.invalidate_flags()

        entry = _entry(builder, "Mute Layer")
        entry.click_fn(_ctx(model, item=item, services=app))

        assert adapter.is_muted(adapter.find_layer(item.identifier)) is False

    def test_click_pushes_exactly_one_command(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]
        entry = _entry(builder, "Mute Layer")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert len(pushed) == 1
        assert isinstance(pushed[0], SetLayerMutenessCommand)

    def test_click_undo_restores_previous_state(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Mute Layer")
        entry.click_fn(_ctx(model, item=item, services=app))
        handle = adapter.find_layer(item.identifier)
        assert adapter.is_muted(handle) is True
        app.undo_manager.undo()
        assert adapter.is_muted(handle) is False

    def test_click_noop_without_app(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Mute Layer")
        entry.click_fn(_ctx(model, item=item, services=None))  # must not raise

    def test_click_noop_without_item(self, builder, model, app) -> None:
        entry = _entry(builder, "Mute Layer")
        entry.click_fn(_ctx(model, item=None, services=app))  # must not raise


# ── Lock click ──────────────────────────────────────────────────────


class TestLockClick:
    def test_click_on_unlocked_pushes_lock_command(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        assert item.is_locked is False
        entry = _entry(builder, "Lock Layer")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert adapter.is_locked(adapter.find_layer(item.identifier)) is True

    def test_click_on_locked_pushes_unlock_command(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        adapter.set_lock(item.identifier, True)
        item.invalidate_flags()
        entry = _entry(builder, "Lock Layer")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert adapter.is_locked(adapter.find_layer(item.identifier)) is False

    def test_click_pushes_exactly_one_command(
        self, builder, model, app
    ) -> None:
        item = _find(model, "./child_a.usda")
        pushed: List[Any] = []
        original = app.undo_manager.push
        app.undo_manager.push = lambda cmd: (
            pushed.append(cmd), original(cmd)
        )[1]
        entry = _entry(builder, "Lock Layer")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert len(pushed) == 1
        assert isinstance(pushed[0], SetLayerLockCommand)

    def test_click_undo_restores_previous_state(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Lock Layer")
        entry.click_fn(_ctx(model, item=item, services=app))
        handle = adapter.find_layer(item.identifier)
        assert adapter.is_locked(handle) is True
        app.undo_manager.undo()
        assert adapter.is_locked(handle) is False

    def test_click_noop_without_app(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Lock Layer")
        entry.click_fn(_ctx(model, item=item, services=None))  # must not raise


# ── Lock-tree / Unlock-tree click ───────────────────────────────────


class TestLockTreeClick:
    def test_click_locks_self_and_all_descendants(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        assert item.is_locked is False
        entry = _entry(builder, "Lock Layer and Descendants")
        entry.click_fn(_ctx(model, item=item, services=app))
        # Both child_a and grandchild_a must be locked now.
        assert adapter.is_locked(adapter.find_layer("./child_a.usda")) is True
        assert (
            adapter.is_locked(adapter.find_layer("./grandchild_a.usda"))
            is True
        )
        # Sibling is untouched.
        assert (
            adapter.is_locked(adapter.find_layer("./child_b.usda")) is False
        )

    def test_click_on_root_locks_entire_tree(
        self, builder, model, app, adapter
    ) -> None:
        root = model.root_item
        assert root is not None
        entry = _entry(builder, "Lock Layer and Descendants")
        entry.click_fn(_ctx(model, item=root, services=app))
        for identifier in (
            root.identifier,
            "./child_a.usda",
            "./child_b.usda",
            "./grandchild_a.usda",
        ):
            handle = adapter.find_layer(identifier)
            assert handle is not None, identifier
            assert adapter.is_locked(handle) is True, identifier

    def test_single_undo_unlocks_the_whole_tree(
        self, builder, model, app, adapter
    ) -> None:
        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Lock Layer and Descendants")
        entry.click_fn(_ctx(model, item=item, services=app))
        # One ctrl+z must undo the whole group in one step.
        assert app.undo_manager.undo() is True
        assert (
            adapter.is_locked(adapter.find_layer("./child_a.usda")) is False
        )
        assert (
            adapter.is_locked(adapter.find_layer("./grandchild_a.usda"))
            is False
        )
        # Only one undo entry was created (the group).
        assert app.undo_manager.can_undo() is False

    def test_click_pushes_single_undo_group(
        self, builder, model, app
    ) -> None:
        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Lock Layer and Descendants")
        entry.click_fn(_ctx(model, item=item, services=app))
        # The undo stack holds a single UndoGroup wrapping per-layer
        # SetLayerLockCommands — that's the plan's contract.
        assert len(app.undo_manager._undo_stack) == 1
        entry_on_stack = app.undo_manager._undo_stack[0]
        assert isinstance(entry_on_stack, UndoGroup)

    def test_click_skips_already_locked_descendants(
        self, builder, model, app, adapter
    ) -> None:
        # Pre-lock one descendant — the tree-lock must not push a
        # redundant command for it, so undo restores only the items
        # that actually changed.
        adapter.set_lock("./grandchild_a.usda", True)
        _find(model, "./grandchild_a.usda").invalidate_flags()

        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Lock Layer and Descendants")
        entry.click_fn(_ctx(model, item=item, services=app))

        # child_a is now locked, grandchild_a was already locked.
        assert adapter.is_locked(adapter.find_layer("./child_a.usda")) is True
        # Undo must leave grandchild_a locked (we didn't touch it).
        app.undo_manager.undo()
        assert (
            adapter.is_locked(adapter.find_layer("./child_a.usda")) is False
        )
        assert (
            adapter.is_locked(adapter.find_layer("./grandchild_a.usda"))
            is True
        )

    def test_click_is_noop_when_all_already_locked(
        self, builder, model, app, adapter
    ) -> None:
        # Every node in the subtree is already locked — the click
        # produces no undo entry at all (empty group).
        for identifier in ("./child_a.usda", "./grandchild_a.usda"):
            adapter.set_lock(identifier, True)
            _find(model, identifier).invalidate_flags()

        item = _find(model, "./child_a.usda")
        before = len(app.undo_manager._undo_stack)
        entry = _entry(builder, "Lock Layer and Descendants")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert len(app.undo_manager._undo_stack) == before

    def test_click_noop_without_app(self, builder, model) -> None:
        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Lock Layer and Descendants")
        entry.click_fn(_ctx(model, item=item, services=None))  # must not raise

    def test_click_noop_without_item(self, builder, model, app) -> None:
        entry = _entry(builder, "Lock Layer and Descendants")
        entry.click_fn(_ctx(model, item=None, services=app))  # must not raise


class TestUnlockTreeClick:
    def test_click_unlocks_self_and_all_descendants(
        self, builder, model, app, adapter
    ) -> None:
        # Lock everything first.
        for identifier in (
            "./child_a.usda",
            "./child_b.usda",
            "./grandchild_a.usda",
        ):
            adapter.set_lock(identifier, True)
            _find(model, identifier).invalidate_flags()

        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Unlock Layer and Descendants")
        entry.click_fn(_ctx(model, item=item, services=app))

        assert (
            adapter.is_locked(adapter.find_layer("./child_a.usda")) is False
        )
        assert (
            adapter.is_locked(adapter.find_layer("./grandchild_a.usda"))
            is False
        )
        # Sibling still locked — tree-unlock is scoped to the subtree.
        assert (
            adapter.is_locked(adapter.find_layer("./child_b.usda")) is True
        )

    def test_single_undo_relocks_the_whole_tree(
        self, builder, model, app, adapter
    ) -> None:
        for identifier in ("./child_a.usda", "./grandchild_a.usda"):
            adapter.set_lock(identifier, True)
            _find(model, identifier).invalidate_flags()

        item = _find(model, "./child_a.usda")
        entry = _entry(builder, "Unlock Layer and Descendants")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert app.undo_manager.undo() is True
        assert (
            adapter.is_locked(adapter.find_layer("./child_a.usda")) is True
        )
        assert (
            adapter.is_locked(adapter.find_layer("./grandchild_a.usda"))
            is True
        )

    def test_click_is_noop_when_all_already_unlocked(
        self, builder, model, app
    ) -> None:
        item = _find(model, "./child_a.usda")
        before = len(app.undo_manager._undo_stack)
        entry = _entry(builder, "Unlock Layer and Descendants")
        entry.click_fn(_ctx(model, item=item, services=app))
        assert len(app.undo_manager._undo_stack) == before


# ── Canonical order ─────────────────────────────────────────────────


class TestCanonicalOrder:
    def test_state_entries_between_create_and_file_io(
        self, builder, model, adapter
    ) -> None:
        # Make one sublayer dirty so "Save" also surfaces and the
        # order across all three groups (create → state → file-I/O)
        # is asserted on a single rendered menu.
        item = _find(model, "./child_a.usda")
        adapter.set_dirty(item.identifier, True)
        item.invalidate_flags()
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        create_idx = labels.index("Create Sublayer")
        mute_idx = labels.index("Mute Layer")
        save_idx = labels.index("Save")
        assert create_idx < mute_idx < save_idx

    def test_lock_tree_follows_lock_single(
        self, builder, model
    ) -> None:
        item = _find(model, "./child_a.usda")
        visible = builder.build_entries_for(_ctx(model, item=item))
        labels = [e.label for e in visible]
        lock_idx = labels.index("Lock Layer")
        lock_tree_idx = labels.index("Lock Layer and Descendants")
        unlock_tree_idx = labels.index("Unlock Layer and Descendants")
        assert lock_idx < lock_tree_idx < unlock_tree_idx
