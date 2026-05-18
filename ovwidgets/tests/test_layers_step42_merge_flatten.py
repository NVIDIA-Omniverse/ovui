# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for LAYERS-PLAN Step 42 — Merge Down and Flatten Sublayers.

Step 42 lands:

- **Adapter snapshot/restore API** —
  :meth:`~ovwidgets.common.adapters.LayerStackAdapter.snapshot_layer`,
  :meth:`~ovwidgets.common.adapters.LayerStackAdapter.restore_layer_from_snapshot`,
  and :meth:`~ovwidgets.common.adapters.LayerStackAdapter.transfer_layer_content`
  on the ABC + mock + USD adapters.
- **Two undoable commands** —
  :class:`~ovwidgets.layers.commands.MergeDownCommand` and
  :class:`~ovwidgets.layers.commands.FlattenSublayersCommand`. Both snapshot
  every layer they touch before mutating, so ``undo`` rebuilds the
  pre-merge state byte-for-byte.
- **Two confirmation dialogs** — :func:`ovwidgets.common.dialogs.confirm_merge_down_dialog`
  and :func:`ovwidgets.common.dialogs.confirm_flatten_dialog`. Both are thin
  wrappers around :func:`ovwidgets.common.dialogs.confirm_dialog` so the
  accompanying tests focus on "does the confirm button fire the
  continuation?" rather than re-testing the base dialog machinery.
- **Two context-menu entries** — "Merge Down" gated on
  :func:`~ovwidgets.layers.context_menu.has_sibling_below`, "Flatten
  Sublayers" gated on :func:`~ovwidgets.layers.context_menu.has_sublayers`.
  Both land in :data:`~ovwidgets.layers.context_menu.GROUP_DESTRUCTIVE` and
  their click handlers open the corresponding confirmation dialog.

Coverage map:

- :class:`TestMockAdapterSnapshot` — round-trip the snapshot/restore
  pair on the mock adapter, including prim-spec content, mute / lock
  bits, and anonymous-identifier minting.
- :class:`TestTransferLayerContent` — the merge primitive itself:
  specs are copied, destination is marked dirty, source is untouched.
- :class:`TestMergeDownCommand` / :class:`TestFlattenSublayersCommand`
  — do / undo round-trips on a 3-sublayer stack; subsequent
  redo/undo cycles hold the pre-merge state anchored.
- :class:`TestMergeDownEntry` / :class:`TestFlattenEntry` — context-
  menu predicate filtering, click-handler opens the dialog, confirm
  pushes the right command.
- :class:`TestPredicates` — :func:`has_sibling_below` and
  :func:`has_sublayers` edge cases (top-level rows, empty-area clicks,
  last-sibling rows).
- :class:`TestCanonicalOrder` — destructive group lands at the tail
  (Remove → Merge Down → Flatten Sublayers).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from ovui_data_adapters.common import LayerSnapshot

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.common.undo import UndoManager
from ovwidgets.layers import (
    ContextMenuBuilder,
    ContextMenuEntry,
    LayerItem,
    LayerModel,
    MenuContext,
)
from ovwidgets.layers.commands import (
    FlattenSublayersCommand,
    MergeDownCommand,
)
from ovwidgets.layers.context_menu import (
    GROUP_DESTRUCTIVE,
    has_sibling_below,
    has_sublayers,
    is_layer_item,
    is_writable,
)

# ── Fixtures ────────────────────────────────────────────────────────


class _App:
    """Minimal :class:`Application` stand-in for context-menu click tests."""

    def __init__(self) -> None:
        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()


@pytest.fixture
def adapter() -> MockLayerStackAdapter:
    # Build a 3-sublayer stack:
    #   root
    #     ├── ./top.usda         (source for merge-down)
    #     ├── ./middle.usda      (destination for merge-down)
    #     └── ./bottom.usda
    # plus a nested sublayer on top for the flatten test:
    #   ./top.usda
    #     └── ./nested.usda
    ad = MockLayerStackAdapter(include_session=True)
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./top.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./middle.usda")
    ad.add_sublayer(ROOT_LAYER_IDENTIFIER, "./bottom.usda")
    ad.add_sublayer("./top.usda", "./nested.usda")
    ad.set_prim_spec("./top.usda", "/PrimFromTop", "top-usda-blob")
    ad.set_prim_spec("./middle.usda", "/PrimFromMiddle", "middle-usda-blob")
    ad.set_prim_spec("./bottom.usda", "/PrimFromBottom", "bottom-usda-blob")
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


# ── Adapter snapshot/restore ────────────────────────────────────────


class TestMockAdapterSnapshot:
    def test_snapshot_captures_basic_identity(self, adapter) -> None:
        snap = adapter.snapshot_layer("./top.usda")
        assert isinstance(snap, LayerSnapshot)
        assert snap.identifier == "./top.usda"
        assert snap.parent_identifier == ROOT_LAYER_IDENTIFIER
        assert snap.position_in_parent == 0
        assert snap.anonymous is False
        # The nested sublayer identifier is captured.
        assert "./nested.usda" in snap.sublayer_identifiers

    def test_snapshot_captures_state_flags(self, adapter) -> None:
        adapter.set_mute("./middle.usda", True)
        adapter.set_lock("./middle.usda", True)
        snap = adapter.snapshot_layer("./middle.usda")
        assert snap.mute_state is True
        assert snap.lock_state is True

    def test_snapshot_captures_edit_target(self, adapter) -> None:
        adapter.set_edit_target("./top.usda")
        snap = adapter.snapshot_layer("./top.usda")
        assert snap.was_edit_target is True
        other = adapter.snapshot_layer("./middle.usda")
        assert other.was_edit_target is False

    def test_snapshot_content_includes_prim_specs(self, adapter) -> None:
        snap = adapter.snapshot_layer("./top.usda")
        assert "/PrimFromTop" in snap.content
        assert "top-usda-blob" in snap.content

    def test_snapshot_of_missing_layer_raises(self, adapter) -> None:
        with pytest.raises(KeyError):
            adapter.snapshot_layer("./does-not-exist.usda")

    def test_restore_round_trip_preserves_prim_specs(self, adapter) -> None:
        snap = adapter.snapshot_layer("./top.usda")
        # Clear the layer's specs and remove it from the tree.
        adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
        adapter._layers["./top.usda"].prim_specs.clear()
        assert adapter._layers["./top.usda"].prim_specs == {}

        adapter.restore_layer_from_snapshot(snap)

        # Specs are back.
        assert (
            adapter._layers["./top.usda"].prim_specs["/PrimFromTop"]
            == "top-usda-blob"
        )
        # Parent re-references the layer at its original slot.
        assert adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )[0] == "./top.usda"

    def test_restore_preserves_mute_and_lock_bits(self, adapter) -> None:
        adapter.set_mute("./middle.usda", True)
        adapter.set_lock("./middle.usda", True)
        snap = adapter.snapshot_layer("./middle.usda")
        adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 1)
        # Clear bits so we can verify they actually get replayed.
        adapter._layers["./middle.usda"].muted = False
        adapter._layers["./middle.usda"].locked = False
        adapter.restore_layer_from_snapshot(snap)
        assert adapter.is_muted(adapter.find_layer("./middle.usda")) is True
        assert adapter.is_locked(adapter.find_layer("./middle.usda")) is True

    def test_restore_anonymous_mints_fresh_identifier(
        self, adapter
    ) -> None:
        # Create an anonymous sublayer, snapshot, remove, restore —
        # the restored layer gets a NEW identifier (matches USD).
        anon_id = adapter.create_sublayer(
            ROOT_LAYER_IDENTIFIER, -1, ""
        )
        snap = adapter.snapshot_layer(anon_id)
        # Remove it from tree.
        siblings = adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )
        pos = siblings.index(anon_id)
        adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, pos)

        new_id = adapter.restore_layer_from_snapshot(snap)
        assert new_id != anon_id  # Fresh anon identifier.
        assert new_id.startswith("anon:")
        # Layer is back in the parent's sublayer list.
        assert new_id in adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )

    def test_restore_replays_edit_target(self, adapter) -> None:
        adapter.set_edit_target("./top.usda")
        snap = adapter.snapshot_layer("./top.usda")
        adapter.set_edit_target(ROOT_LAYER_IDENTIFIER)
        adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
        adapter.restore_layer_from_snapshot(snap)
        assert adapter.get_edit_target_identifier() == "./top.usda"


# ── Transfer layer content ──────────────────────────────────────────


class TestTransferLayerContent:
    def test_copies_specs_into_destination(self, adapter) -> None:
        adapter.transfer_layer_content("./top.usda", "./middle.usda")
        middle_specs = adapter._layers["./middle.usda"].prim_specs
        assert middle_specs["/PrimFromTop"] == "top-usda-blob"
        # Destination's own spec is preserved.
        assert middle_specs["/PrimFromMiddle"] == "middle-usda-blob"

    def test_source_is_not_modified(self, adapter) -> None:
        adapter.transfer_layer_content("./top.usda", "./middle.usda")
        assert adapter._layers["./top.usda"].prim_specs == {
            "/PrimFromTop": "top-usda-blob"
        }

    def test_destination_marked_dirty(self, adapter) -> None:
        assert adapter.is_dirty(adapter.find_layer("./middle.usda")) is False
        adapter.transfer_layer_content("./top.usda", "./middle.usda")
        assert adapter.is_dirty(adapter.find_layer("./middle.usda")) is True

    def test_source_specs_override_destination_specs(
        self, adapter
    ) -> None:
        # Both layers have a spec at /Shared — source wins (stronger).
        adapter.set_prim_spec("./top.usda", "/Shared", "from-top")
        adapter.set_prim_spec("./middle.usda", "/Shared", "from-middle")
        adapter.transfer_layer_content("./top.usda", "./middle.usda")
        assert (
            adapter._layers["./middle.usda"].prim_specs["/Shared"]
            == "from-top"
        )

    def test_empty_source_is_noop(self, adapter) -> None:
        # An empty source should not mark the destination dirty.
        adapter._layers["./top.usda"].prim_specs.clear()
        adapter.transfer_layer_content("./top.usda", "./middle.usda")
        # Dirty bit stays False since nothing moved.
        assert adapter.is_dirty(adapter.find_layer("./middle.usda")) is False


# ── MergeDownCommand ────────────────────────────────────────────────


class TestMergeDownCommand:
    def test_do_transfers_content_and_removes_source(
        self, adapter, app
    ) -> None:
        cmd = MergeDownCommand(
            adapter, app.selection_bus, ROOT_LAYER_IDENTIFIER, 0
        )
        app.undo_manager.push(cmd)
        siblings = adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )
        assert siblings == ["./middle.usda", "./bottom.usda"]
        # Destination now carries both specs.
        middle_specs = adapter._layers["./middle.usda"].prim_specs
        assert middle_specs["/PrimFromTop"] == "top-usda-blob"
        assert middle_specs["/PrimFromMiddle"] == "middle-usda-blob"

    def test_undo_restores_source_and_destination(
        self, adapter, app
    ) -> None:
        pre_middle_specs = dict(
            adapter._layers["./middle.usda"].prim_specs
        )
        pre_top_specs = dict(adapter._layers["./top.usda"].prim_specs)
        cmd = MergeDownCommand(
            adapter, app.selection_bus, ROOT_LAYER_IDENTIFIER, 0
        )
        app.undo_manager.push(cmd)
        app.undo_manager.undo()

        siblings = adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )
        assert siblings == [
            "./top.usda",
            "./middle.usda",
            "./bottom.usda",
        ]
        assert (
            adapter._layers["./middle.usda"].prim_specs == pre_middle_specs
        )
        assert adapter._layers["./top.usda"].prim_specs == pre_top_specs

    def test_redo_reapplies_merge(self, adapter, app) -> None:
        cmd = MergeDownCommand(
            adapter, app.selection_bus, ROOT_LAYER_IDENTIFIER, 0
        )
        app.undo_manager.push(cmd)
        app.undo_manager.undo()
        app.undo_manager.redo()
        siblings = adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )
        assert siblings == ["./middle.usda", "./bottom.usda"]
        middle_specs = adapter._layers["./middle.usda"].prim_specs
        assert "/PrimFromTop" in middle_specs

    def test_do_raises_without_sibling_below(self, adapter, app) -> None:
        # Position 2 is the last sibling; no sibling below.
        cmd = MergeDownCommand(
            adapter, app.selection_bus, ROOT_LAYER_IDENTIFIER, 2
        )
        with pytest.raises(IndexError):
            cmd.do()

    def test_do_raises_on_unknown_parent(self, adapter, app) -> None:
        cmd = MergeDownCommand(
            adapter, app.selection_bus, "./missing-parent.usda", 0
        )
        with pytest.raises(KeyError):
            cmd.do()


# ── FlattenSublayersCommand ─────────────────────────────────────────


class TestFlattenSublayersCommand:
    def test_do_merges_all_direct_sublayers_into_parent(
        self, adapter, app
    ) -> None:
        root_handle = adapter.get_root_layer()
        cmd = FlattenSublayersCommand(
            adapter, app.selection_bus, ROOT_LAYER_IDENTIFIER
        )
        app.undo_manager.push(cmd)
        # Root has no sublayers.
        assert adapter.get_sublayer_identifiers(root_handle) == []
        # All three prim specs landed on root.
        root_specs = adapter._layers[ROOT_LAYER_IDENTIFIER].prim_specs
        assert "/PrimFromTop" in root_specs
        assert "/PrimFromMiddle" in root_specs
        assert "/PrimFromBottom" in root_specs

    def test_undo_restores_parent_and_all_sublayers(
        self, adapter, app
    ) -> None:
        pre_root_specs = dict(
            adapter._layers[ROOT_LAYER_IDENTIFIER].prim_specs
        )
        pre_siblings = adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )
        cmd = FlattenSublayersCommand(
            adapter, app.selection_bus, ROOT_LAYER_IDENTIFIER
        )
        app.undo_manager.push(cmd)
        app.undo_manager.undo()

        assert (
            adapter.get_sublayer_identifiers(adapter.get_root_layer())
            == pre_siblings
        )
        assert (
            adapter._layers[ROOT_LAYER_IDENTIFIER].prim_specs
            == pre_root_specs
        )
        # Every sublayer still carries its original prim spec.
        assert (
            adapter._layers["./top.usda"].prim_specs["/PrimFromTop"]
            == "top-usda-blob"
        )
        assert (
            adapter._layers["./middle.usda"].prim_specs["/PrimFromMiddle"]
            == "middle-usda-blob"
        )

    def test_redo_reapplies_flatten(self, adapter, app) -> None:
        cmd = FlattenSublayersCommand(
            adapter, app.selection_bus, ROOT_LAYER_IDENTIFIER
        )
        app.undo_manager.push(cmd)
        app.undo_manager.undo()
        app.undo_manager.redo()
        assert (
            adapter.get_sublayer_identifiers(adapter.get_root_layer())
            == []
        )

    def test_do_is_noop_on_empty_parent(self, adapter, app) -> None:
        # Create an empty sublayer and flatten it — nothing to merge.
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./empty.usda")
        cmd = FlattenSublayersCommand(
            adapter, app.selection_bus, "./empty.usda"
        )
        pre_stack_len = len(app.undo_manager._undo_stack)
        app.undo_manager.push(cmd)
        # Empty parent → nothing snapshotted → no meaningful mutation.
        assert cmd._parent_snapshot is None

    def test_undo_without_do_is_noop(self, adapter, app) -> None:
        # Command never ran — undo_impl must short-circuit.
        cmd = FlattenSublayersCommand(
            adapter, app.selection_bus, ROOT_LAYER_IDENTIFIER
        )
        cmd.undo_impl()  # Must not raise.


# ── Predicates ──────────────────────────────────────────────────────


class TestPredicates:
    def test_has_sibling_below_true_for_middle_row(self, model) -> None:
        top = _find(model, "./top.usda")
        assert has_sibling_below(_ctx(model, item=top)) is True

    def test_has_sibling_below_false_for_last_row(self, model) -> None:
        bottom = _find(model, "./bottom.usda")
        assert has_sibling_below(_ctx(model, item=bottom)) is False

    def test_has_sibling_below_false_for_root(self, model) -> None:
        root = model.root_item
        assert root is not None
        # Root has no parent, so no siblings.
        assert has_sibling_below(_ctx(model, item=root)) is False

    def test_has_sibling_below_false_on_empty_area(self, model) -> None:
        assert has_sibling_below(_ctx(model, item=None)) is False

    def test_has_sublayers_true_when_layer_has_children(
        self, model
    ) -> None:
        root = model.root_item
        assert root is not None
        assert has_sublayers(_ctx(model, item=root)) is True

    def test_has_sublayers_true_for_top_with_nested(self, model) -> None:
        top = _find(model, "./top.usda")
        assert has_sublayers(_ctx(model, item=top)) is True

    def test_has_sublayers_false_for_leaf_layer(self, model) -> None:
        middle = _find(model, "./middle.usda")
        assert has_sublayers(_ctx(model, item=middle)) is False

    def test_has_sublayers_false_on_empty_area(self, model) -> None:
        assert has_sublayers(_ctx(model, item=None)) is False


# ── Merge Down context-menu entry ───────────────────────────────────


class TestMergeDownEntry:
    def test_entry_registered(self, builder) -> None:
        entry = _entry(builder, "Merge Down")
        assert entry.group == GROUP_DESTRUCTIVE
        assert is_layer_item in entry.show_fn
        assert is_writable in entry.show_fn
        assert has_sibling_below in entry.show_fn

    def test_visible_on_row_with_sibling_below(
        self, builder, model
    ) -> None:
        top = _find(model, "./top.usda")
        visible = builder.build_entries_for(_ctx(model, item=top))
        assert "Merge Down" in [e.label for e in visible]

    def test_hidden_on_last_sibling(self, builder, model) -> None:
        bottom = _find(model, "./bottom.usda")
        visible = builder.build_entries_for(_ctx(model, item=bottom))
        assert "Merge Down" not in [e.label for e in visible]

    def test_hidden_on_empty_area(self, builder, model) -> None:
        visible = builder.build_entries_for(_ctx(model, item=None))
        assert "Merge Down" not in [e.label for e in visible]

    def test_click_opens_confirm_dialog(
        self, builder, model, app
    ) -> None:
        top = _find(model, "./top.usda")
        entry = _entry(builder, "Merge Down")
        # Swap out the dialog so the test never touches ui.
        captured: dict = {}

        def _fake_dialog(
            source_name, destination_name, on_merge, on_cancel=None
        ):
            captured["source_name"] = source_name
            captured["destination_name"] = destination_name
            captured["on_merge"] = on_merge
            return object()

        with patch(
            "ovwidgets.common.dialogs.confirm_merge_down_dialog",
            _fake_dialog,
        ):
            entry.click_fn(_ctx(model, item=top, services=app))

        assert "source_name" in captured
        # Command NOT pushed yet — the user hasn't confirmed.
        assert not app.undo_manager.can_undo()

    def test_confirm_pushes_merge_command(
        self, builder, model, app, adapter
    ) -> None:
        top = _find(model, "./top.usda")
        entry = _entry(builder, "Merge Down")
        captured: dict = {}

        def _fake_dialog(
            source_name, destination_name, on_merge, on_cancel=None
        ):
            captured["on_merge"] = on_merge
            return object()

        with patch(
            "ovwidgets.common.dialogs.confirm_merge_down_dialog",
            _fake_dialog,
        ):
            entry.click_fn(_ctx(model, item=top, services=app))

        # Invoke the confirm continuation — that's what the user's
        # "Merge Down" button click would do.
        captured["on_merge"]()
        siblings = adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )
        assert siblings == ["./middle.usda", "./bottom.usda"]
        assert app.undo_manager.can_undo() is True

    def test_click_noop_without_app(self, builder, model) -> None:
        top = _find(model, "./top.usda")
        entry = _entry(builder, "Merge Down")
        entry.click_fn(_ctx(model, item=top, services=None))  # must not raise

    def test_click_noop_on_last_sibling(
        self, builder, model, app
    ) -> None:
        # Even though the predicate would hide the entry, the click
        # handler is defensive against a stale cache firing it.
        bottom = _find(model, "./bottom.usda")
        entry = _entry(builder, "Merge Down")
        captured: dict = {}

        def _fake_dialog(*args, **kwargs):
            captured["called"] = True
            return object()

        with patch(
            "ovwidgets.common.dialogs.confirm_merge_down_dialog",
            _fake_dialog,
        ):
            entry.click_fn(_ctx(model, item=bottom, services=app))

        # Dialog should NOT open on a last-sibling click.
        assert "called" not in captured


# ── Flatten context-menu entry ──────────────────────────────────────


class TestFlattenEntry:
    def test_entry_registered(self, builder) -> None:
        entry = _entry(builder, "Flatten Sublayers")
        assert entry.group == GROUP_DESTRUCTIVE
        assert is_layer_item in entry.show_fn
        assert is_writable in entry.show_fn
        assert has_sublayers in entry.show_fn

    def test_visible_on_layer_with_sublayers(
        self, builder, model
    ) -> None:
        root = model.root_item
        assert root is not None
        visible = builder.build_entries_for(_ctx(model, item=root))
        assert "Flatten Sublayers" in [e.label for e in visible]

    def test_hidden_on_leaf_layer(self, builder, model) -> None:
        middle = _find(model, "./middle.usda")
        visible = builder.build_entries_for(_ctx(model, item=middle))
        assert "Flatten Sublayers" not in [e.label for e in visible]

    def test_hidden_on_empty_area(self, builder, model) -> None:
        visible = builder.build_entries_for(_ctx(model, item=None))
        assert "Flatten Sublayers" not in [e.label for e in visible]

    def test_click_opens_confirm_dialog_with_count(
        self, builder, model, app
    ) -> None:
        root = model.root_item
        assert root is not None
        entry = _entry(builder, "Flatten Sublayers")
        captured: dict = {}

        def _fake_dialog(
            parent_name, sublayer_count, on_flatten, on_cancel=None
        ):
            captured["parent_name"] = parent_name
            captured["sublayer_count"] = sublayer_count
            captured["on_flatten"] = on_flatten
            return object()

        with patch(
            "ovwidgets.common.dialogs.confirm_flatten_dialog",
            _fake_dialog,
        ):
            entry.click_fn(_ctx(model, item=root, services=app))

        assert captured["sublayer_count"] == 3
        assert app.undo_manager.can_undo() is False

    def test_confirm_pushes_flatten_command(
        self, builder, model, app, adapter
    ) -> None:
        root = model.root_item
        assert root is not None
        entry = _entry(builder, "Flatten Sublayers")
        captured: dict = {}

        def _fake_dialog(
            parent_name, sublayer_count, on_flatten, on_cancel=None
        ):
            captured["on_flatten"] = on_flatten
            return object()

        with patch(
            "ovwidgets.common.dialogs.confirm_flatten_dialog",
            _fake_dialog,
        ):
            entry.click_fn(_ctx(model, item=root, services=app))

        captured["on_flatten"]()
        assert (
            adapter.get_sublayer_identifiers(adapter.get_root_layer())
            == []
        )
        assert app.undo_manager.can_undo() is True

    def test_click_noop_without_app(self, builder, model) -> None:
        root = model.root_item
        assert root is not None
        entry = _entry(builder, "Flatten Sublayers")
        entry.click_fn(_ctx(model, item=root, services=None))  # must not raise


# ── Canonical order ─────────────────────────────────────────────────


class TestCanonicalOrder:
    def test_destructive_group_ordering(self, builder, model) -> None:
        top = _find(model, "./top.usda")
        visible = builder.build_entries_for(_ctx(model, item=top))
        labels = [e.label for e in visible]
        # All three destructive entries are visible on ./top.usda
        # (writable, has sibling below, has nested sublayer).
        remove_idx = labels.index("Remove")
        merge_idx = labels.index("Merge Down")
        flatten_idx = labels.index("Flatten Sublayers")
        assert remove_idx < merge_idx < flatten_idx

    def test_destructive_after_state_and_file_io(
        self, builder, model, adapter
    ) -> None:
        top = _find(model, "./top.usda")
        adapter.set_dirty(top.identifier, True)
        top.invalidate_flags()
        visible = builder.build_entries_for(_ctx(model, item=top))
        labels = [e.label for e in visible]
        mute_idx = labels.index("Mute Layer")
        save_idx = labels.index("Save")
        merge_idx = labels.index("Merge Down")
        assert mute_idx < save_idx < merge_idx


# ── Dialog helper tests ─────────────────────────────────────────────


class TestDialogHelpers:
    def test_merge_down_dialog_builds_confirm_button(
        self, monkeypatch
    ) -> None:
        from ovwidgets.common import dialogs

        captured: dict = {}

        def _fake_confirm(**kwargs):
            captured.update(kwargs)
            return object()

        monkeypatch.setattr(dialogs, "confirm_dialog", _fake_confirm)
        dialogs.confirm_merge_down_dialog(
            source_name="A.usda",
            destination_name="B.usda",
            on_merge=lambda: None,
        )
        assert captured["confirm_label"] == "Merge Down"
        assert captured["cancel_label"] == "Cancel"
        assert "A.usda" in captured["message"]
        assert "B.usda" in captured["message"]

    def test_flatten_dialog_singular_count(self, monkeypatch) -> None:
        from ovwidgets.common import dialogs

        captured: dict = {}

        def _fake_confirm(**kwargs):
            captured.update(kwargs)
            return object()

        monkeypatch.setattr(dialogs, "confirm_dialog", _fake_confirm)
        dialogs.confirm_flatten_dialog(
            parent_name="root",
            sublayer_count=1,
            on_flatten=lambda: None,
        )
        assert captured["confirm_label"] == "Flatten"
        assert "1 sublayer" in captured["message"]
        # Guard against plural form sneaking in for the 1-count case.
        assert "1 sublayers" not in captured["message"]

    def test_flatten_dialog_plural_count(self, monkeypatch) -> None:
        from ovwidgets.common import dialogs

        captured: dict = {}

        def _fake_confirm(**kwargs):
            captured.update(kwargs)
            return object()

        monkeypatch.setattr(dialogs, "confirm_dialog", _fake_confirm)
        dialogs.confirm_flatten_dialog(
            parent_name="root",
            sublayer_count=5,
            on_flatten=lambda: None,
        )
        assert "5 sublayers" in captured["message"]


# ── USD-backed adapter integration ──────────────────────────────────
#
# The mock tests above cover the happy path; the tests below exercise
# the USD adapter's snapshot / restore / transfer implementations
# against a live in-memory ``Usd.Stage`` so a bug in the ``Sdf.CopySpec``
# wiring or the ``ExportToString`` / ``ImportFromString`` round-trip
# gets caught before it breaks a real merge.

try:
    from pxr import Sdf, Usd
    _HAS_USD = True
except ImportError:
    _HAS_USD = False


@pytest.mark.skipif(not _HAS_USD, reason="pxr (OpenUSD) not available")
class TestUsdAdapterMergeFlatten:
    def _build(self, tmp_path):
        from ovui_data_adapters.openusd.layer_stack_adapter import UsdLayerStackAdapter

        top = Sdf.Layer.CreateNew(str(tmp_path / "top.usda"))
        Sdf.CreatePrimInLayer(top, "/PrimFromTop")
        top.Save()

        middle = Sdf.Layer.CreateNew(str(tmp_path / "middle.usda"))
        Sdf.CreatePrimInLayer(middle, "/PrimFromMiddle")
        middle.Save()

        root = Sdf.Layer.CreateNew(str(tmp_path / "root.usda"))
        root.subLayerPaths.append("top.usda")
        root.subLayerPaths.append("middle.usda")
        root.Save()

        stage = Usd.Stage.Open(str(tmp_path / "root.usda"))
        adapter = UsdLayerStackAdapter(stage, UndoManager())
        # Prime the cache for every sublayer so find_layer resolves.
        adapter.get_sublayer_identifiers(adapter.get_root_layer())
        return adapter, str(tmp_path / "top.usda"), str(
            tmp_path / "middle.usda"
        )

    def test_snapshot_round_trip_content(self, tmp_path) -> None:
        adapter, top_id, middle_id = self._build(tmp_path)
        snap = adapter.snapshot_layer(top_id)
        # USDA text spells the prim by bare name (no leading slash).
        assert "PrimFromTop" in snap.content
        assert snap.parent_identifier == adapter.get_root_layer().identifier
        assert snap.position_in_parent == 0

    def test_transfer_layer_content_copies_prims(self, tmp_path) -> None:
        adapter, top_id, middle_id = self._build(tmp_path)
        adapter.transfer_layer_content(top_id, middle_id)
        middle_sdf = Sdf.Layer.Find(middle_id)
        assert middle_sdf.GetPrimAtPath("/PrimFromTop") is not None
        assert middle_sdf.GetPrimAtPath("/PrimFromMiddle") is not None

    def test_merge_down_round_trip(self, tmp_path) -> None:
        adapter, top_id, middle_id = self._build(tmp_path)
        app = _App()
        cmd = MergeDownCommand(
            adapter,
            app.selection_bus,
            adapter.get_root_layer().identifier,
            0,
        )
        app.undo_manager.push(cmd)

        siblings = adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )
        assert len(siblings) == 1
        assert siblings[0] == middle_id

        middle_sdf = Sdf.Layer.Find(middle_id)
        assert middle_sdf.GetPrimAtPath("/PrimFromTop") is not None

        # Undo puts top.usda back at position 0.
        app.undo_manager.undo()
        siblings = adapter.get_sublayer_identifiers(
            adapter.get_root_layer()
        )
        assert len(siblings) == 2
        assert siblings[0] == top_id
        assert siblings[1] == middle_id
