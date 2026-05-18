# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ovwidgets.layers.layer_item.LayerItem` (LAYERS-PLAN Step 12)."""

from __future__ import annotations

import omni.ui as ui
from ovui_data_adapters.common import LayerHandle, LayerStackAdapter

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.testing.mock_layer_stack import (
    ROOT_LAYER_IDENTIFIER,
    SESSION_LAYER_IDENTIFIER,
)
from ovwidgets.layers import LayerItem

# ─── Construction ─────────────────────────────────────────────────────────────


class TestConstruction:
    def test_subclass_of_ui_abstract_item(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert isinstance(item, ui.AbstractItem)

    def test_stores_identifier(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.identifier == ROOT_LAYER_IDENTIFIER

    def test_defaults_parent_to_none(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.parent is None

    def test_stores_parent_reference(self) -> None:
        adapter = MockLayerStackAdapter()
        parent = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
        child = LayerItem(adapter, "child", parent=parent)
        assert child.parent is parent

    def test_defaults_is_session_layer_false(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.is_session_layer is False

    def test_session_layer_flag_is_stored(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(
            adapter, SESSION_LAYER_IDENTIFIER, is_session_layer=True
        )
        assert item.is_session_layer is True

    def test_empty_sublayers_at_init(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.sublayers == []

    def test_empty_prim_specs_at_init(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.prim_specs == []

    def test_edit_target_defaults_false(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.is_edit_target is False
        assert item.has_edit_target_descendant is False

    def test_filter_flags_default_false(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.filtered is False
        assert item.child_filtered is False

    def test_constructor_performs_no_adapter_calls(self) -> None:
        """Construction must be cheap — adapter touches come later."""
        adapter = _RecordingAdapter()
        LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert adapter.calls == []


# ─── Display name ─────────────────────────────────────────────────────────────


class TestDisplayName:
    def test_reads_display_name_from_adapter(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.display_name == "root"

    def test_display_name_follows_adapter_changes(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(
            ROOT_LAYER_IDENTIFIER, "child", display_name="original"
        )
        item = LayerItem(adapter, "child")
        assert item.display_name == "original"
        # Update the underlying mock record — display name is read-through.
        adapter._layers["child"].display_name = "renamed"
        assert item.display_name == "renamed"


# ─── Depth ────────────────────────────────────────────────────────────────────


class TestDepth:
    def test_depth_zero_when_no_parent(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.depth == 0

    def test_depth_one_when_single_parent(self) -> None:
        adapter = MockLayerStackAdapter()
        root = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        child = LayerItem(adapter, "a", parent=root)
        assert child.depth == 1

    def test_depth_increments_down_parent_chain(self) -> None:
        adapter = MockLayerStackAdapter()
        root = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        adapter.add_sublayer("a", "b")
        adapter.add_sublayer("b", "c")
        a = LayerItem(adapter, "a", parent=root)
        b = LayerItem(adapter, "b", parent=a)
        c = LayerItem(adapter, "c", parent=b)
        assert a.depth == 1
        assert b.depth == 2
        assert c.depth == 3


# ─── Flag cache ───────────────────────────────────────────────────────────────


class TestFlagCache:
    def test_first_access_reads_from_adapter(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.is_dirty is True

    def test_stale_cache_until_invalidated(self) -> None:
        """Flag changes on the adapter are NOT seen until the cache dirties."""
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.is_dirty is False  # snapshot cached here
        # Flip the adapter directly without going through a mutator that
        # fires an event — the item has no way to know the flag changed.
        adapter._layers[ROOT_LAYER_IDENTIFIER].dirty = True
        assert item.is_dirty is False  # still returns cached value
        item.invalidate_flags()
        assert item.is_dirty is True  # re-read on next access

    def test_mark_dirty_is_alias_for_invalidate_flags(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        # Prime the cache.
        _ = item.is_dirty
        adapter._layers[ROOT_LAYER_IDENTIFIER].muted = True
        item.mark_dirty()
        assert item.is_muted is True

    def test_refresh_flags_is_idempotent(self) -> None:
        adapter = _RecordingAdapter()
        item = LayerItem(adapter, "L")
        item.refresh_flags()
        adapter.calls.clear()
        # Second refresh while clean must touch nothing on the adapter.
        item.refresh_flags()
        assert adapter.calls == []

    def test_all_six_flags_refresh_together(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_read_only(ROOT_LAYER_IDENTIFIER, True)
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        item.refresh_flags()
        assert item.is_dirty is True
        assert item.is_muted is True
        assert item.is_locked is True
        assert item.is_read_only is True
        # Root is neither missing nor anonymous in the mock.
        assert item.is_missing is False
        assert item.is_anonymous is False

    def test_missing_layer_flag(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.insert_sublayer(ROOT_LAYER_IDENTIFIER, 0, "ghost.usda")
        item = LayerItem(adapter, "ghost.usda")
        assert item.is_missing is True

    def test_anonymous_layer_flag(self) -> None:
        adapter = MockLayerStackAdapter()
        session_item = LayerItem(
            adapter, SESSION_LAYER_IDENTIFIER, is_session_layer=True
        )
        assert session_item.is_anonymous is True

    def test_is_writable_composite(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert item.is_writable is True
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
        item.invalidate_flags()
        assert item.is_writable is False


# ─── Mute / lock cascade (Step 32) ───────────────────────────────────────────


class TestStep32MuteLockCascade:
    """``muted_or_parent_muted`` and ``locked_or_parent_locked`` walk the
    parent chain so an ancestor toggle dims every descendant row without
    the descendant's own flag bit needing to change."""

    def _build_chain(
        self,
        adapter: MockLayerStackAdapter,
    ) -> tuple[LayerItem, LayerItem, LayerItem]:
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "mid")
        adapter.add_sublayer("mid", "deep")
        root = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        mid = LayerItem(adapter, "mid", parent=root)
        deep = LayerItem(adapter, "deep", parent=mid)
        return root, mid, deep

    def test_muted_or_parent_muted_false_when_none_muted(self) -> None:
        adapter = MockLayerStackAdapter()
        _root, _mid, deep = self._build_chain(adapter)
        assert deep.muted_or_parent_muted is False

    def test_muted_or_parent_muted_true_when_self_muted(self) -> None:
        adapter = MockLayerStackAdapter()
        _root, _mid, deep = self._build_chain(adapter)
        adapter.set_mute("deep", True)
        deep.invalidate_flags()
        assert deep.muted_or_parent_muted is True

    def test_muted_or_parent_muted_true_via_parent(self) -> None:
        # Parent is muted, child's own bit remains False — the cascade
        # read walks up and reports True.
        adapter = MockLayerStackAdapter()
        _root, mid, deep = self._build_chain(adapter)
        adapter.set_mute("mid", True)
        mid.invalidate_flags()
        assert deep.is_muted is False
        assert deep.muted_or_parent_muted is True

    def test_muted_or_parent_muted_true_via_grandparent(self) -> None:
        adapter = MockLayerStackAdapter()
        root, _mid, deep = self._build_chain(adapter)
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        root.invalidate_flags()
        assert deep.muted_or_parent_muted is True

    def test_locked_or_parent_locked_cascade(self) -> None:
        adapter = MockLayerStackAdapter()
        _root, mid, deep = self._build_chain(adapter)
        adapter.set_lock("mid", True)
        mid.invalidate_flags()
        assert deep.is_locked is False
        assert deep.locked_or_parent_locked is True

    def test_locked_or_parent_locked_false_by_default(self) -> None:
        adapter = MockLayerStackAdapter()
        _root, _mid, deep = self._build_chain(adapter)
        assert deep.locked_or_parent_locked is False

    def test_cascade_independent_of_parent_mute_state(self) -> None:
        # A locked ancestor does not turn ``muted_or_parent_muted`` on
        # (the two cascades are separate).
        adapter = MockLayerStackAdapter()
        _root, mid, deep = self._build_chain(adapter)
        adapter.set_lock("mid", True)
        mid.invalidate_flags()
        assert deep.locked_or_parent_locked is True
        assert deep.muted_or_parent_muted is False

    def test_root_with_no_parent_returns_self_state(self) -> None:
        # A top-level row with no parent chain: cascade answer equals
        # the item's own bit.
        adapter = MockLayerStackAdapter()
        root = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        assert root.muted_or_parent_muted is False
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        root.invalidate_flags()
        assert root.muted_or_parent_muted is True


# ─── Edit-target state (settable) ─────────────────────────────────────────────


class TestEditTarget:
    def test_set_is_edit_target(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        item.is_edit_target = True
        assert item.is_edit_target is True

    def test_set_has_edit_target_descendant(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        item.has_edit_target_descendant = True
        assert item.has_edit_target_descendant is True

    def test_edit_target_setter_coerces_to_bool(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        item.is_edit_target = 1
        assert item.is_edit_target is True
        item.is_edit_target = 0
        assert item.is_edit_target is False


# ─── Filter state (settable) ──────────────────────────────────────────────────


class TestFilterFlags:
    def test_set_filtered(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        item.filtered = True
        assert item.filtered is True

    def test_set_child_filtered(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        item.child_filtered = True
        assert item.child_filtered is True


# ─── Parent / child plumbing ──────────────────────────────────────────────────


class TestTreeStructure:
    def test_sublayers_list_is_mutable(self) -> None:
        """LayerModel will populate this list — the property must not copy."""
        adapter = MockLayerStackAdapter()
        parent = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        child = LayerItem(adapter, "a", parent=parent)
        parent.sublayers.append(child)
        assert parent.sublayers == [child]
        assert parent.sublayers[0].parent is parent


# ─── Repr ─────────────────────────────────────────────────────────────────────


class TestRepr:
    def test_repr_includes_identifier_and_depth(self) -> None:
        adapter = MockLayerStackAdapter()
        item = LayerItem(adapter, ROOT_LAYER_IDENTIFIER)
        text = repr(item)
        assert ROOT_LAYER_IDENTIFIER in text
        assert "depth=0" in text


# ─── Helpers ─────────────────────────────────────────────────────────────────


class _RecordingAdapter(LayerStackAdapter):
    """Minimal adapter that logs every read the item performs.

    Used to verify construction is side-effect-free and that
    :meth:`LayerItem.refresh_flags` is a no-op when the cache is clean.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    # Read surface — log every call.
    def get_root_layer(self) -> LayerHandle:  # pragma: no cover
        return LayerHandle("L")

    def get_session_layer(self):  # pragma: no cover
        return None

    def get_sublayer_identifiers(self, parent):  # pragma: no cover
        return []

    def find_layer(self, identifier):  # pragma: no cover
        return LayerHandle(identifier)

    def get_layer_stack_identifiers(self, include_session=False, include_anonymous=True):  # pragma: no cover
        return []

    def get_display_name(self, layer):
        self.calls.append(("get_display_name", layer.identifier))
        return layer.identifier

    def get_layer_owner(self, layer):  # pragma: no cover
        return ""

    def is_anonymous(self, layer):
        self.calls.append(("is_anonymous", layer.identifier))
        return False

    def is_dirty(self, layer):
        self.calls.append(("is_dirty", layer.identifier))
        return False

    def is_muted(self, layer):
        self.calls.append(("is_muted", layer.identifier))
        return False

    def is_locked(self, layer):
        self.calls.append(("is_locked", layer.identifier))
        return False

    def is_read_only_on_disk(self, layer):
        self.calls.append(("is_read_only_on_disk", layer.identifier))
        return False

    def is_missing(self, layer):
        self.calls.append(("is_missing", layer.identifier))
        return False

    def get_edit_target_identifier(self):  # pragma: no cover
        return ""

    def subscribe_events(self, callback):  # pragma: no cover
        raise NotImplementedError

    # Mutations — unused here; raise if called so a regression is obvious.
    def set_edit_target(self, identifier):  # pragma: no cover
        raise NotImplementedError

    def set_mute(self, identifier, muted):  # pragma: no cover
        raise NotImplementedError

    def set_lock(self, identifier, locked):  # pragma: no cover
        raise NotImplementedError

    def create_sublayer(self, parent_id, position, new_layer_path, transfer_root_content=False):  # pragma: no cover
        raise NotImplementedError

    def insert_sublayer(self, parent_id, position, sublayer_path):  # pragma: no cover
        raise NotImplementedError

    def remove_sublayer(self, parent_id, position):  # pragma: no cover
        raise NotImplementedError

    def move_sublayer(self, from_parent_id, from_position, to_parent_id, to_position, remove_source=True):  # pragma: no cover
        raise NotImplementedError

    def replace_sublayer(self, parent_id, position, new_identifier):  # pragma: no cover
        raise NotImplementedError

    def export_prim_spec(self, layer_id, path):  # pragma: no cover
        raise NotImplementedError

    def remove_prim_spec(self, layer_id, path):  # pragma: no cover
        raise NotImplementedError

    def import_prim_spec(self, layer_id, path, usda):  # pragma: no cover
        raise NotImplementedError

    def get_prim_specs(self, layer_identifier, parent_path="/"):  # pragma: no cover
        raise NotImplementedError

    def has_prim_spec(self, layer_identifier, spec_path):  # pragma: no cover
        raise NotImplementedError

    def save_layer(self, identifier):  # pragma: no cover
        raise NotImplementedError

    def save_layer_as(self, identifier, new_path, replace_in_parent):  # pragma: no cover
        raise NotImplementedError

    def reload_layer(self, identifier):  # pragma: no cover
        raise NotImplementedError

    def snapshot_layer(self, identifier):  # pragma: no cover
        raise NotImplementedError

    def restore_layer_from_snapshot(self, snapshot):  # pragma: no cover
        raise NotImplementedError

    def transfer_layer_content(self, src_identifier, dst_identifier):  # pragma: no cover
        raise NotImplementedError
