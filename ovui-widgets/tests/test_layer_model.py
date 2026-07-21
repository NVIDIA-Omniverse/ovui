# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ovui_widgets.layers.layer_model.LayerModel` (LAYERS-PLAN Step 13).

Covers the plan's Verify bullets plus the LayerModel contract —
top-level children (with / without the session layer), value-model
plumbing, structural vs. flag event dispatch, lifecycle cleanup, and
the ``DefaultLayerSettings`` stand-in introduced for A-3.
"""

from __future__ import annotations

import omni.ui as ui
import pytest
from ovui_data_adapters.common import LayerEvent, LayerEventType

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.testing.mock_layer_stack import (
    ROOT_LAYER_IDENTIFIER,
    SESSION_LAYER_IDENTIFIER,
)
from ovui_widgets.layers import (
    DefaultLayerSettings,
    LayerItem,
    LayerModel,
    LayerNameValueModel,
    LocalMuteValueModel,
    LockValueModel,
    SaveValueModel,
)

# ─── Default settings stub ────────────────────────────────────────────────────


class TestDefaultLayerSettings:
    def test_defaults_match_arch_section_15(self) -> None:
        settings = DefaultLayerSettings()
        # Kit defaults (LAYERS-WINDOW-ARCHITECTURE §15):
        assert settings.show_session_layer is True
        assert settings.show_layer_contents is True
        assert settings.show_missing_reference is True
        assert settings.show_info_notification is True
        assert settings.show_merge_or_flatten_warning is True
        assert settings.show_layer_file_extension is True

    def test_can_override_show_session_layer(self) -> None:
        settings = DefaultLayerSettings(show_session_layer=False)
        assert settings.show_session_layer is False


# ─── Construction ─────────────────────────────────────────────────────────────


class TestConstruction:
    def test_subclass_of_abstract_item_model(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert isinstance(model, ui.AbstractItemModel)
        finally:
            model.destroy()

    def test_stores_adapter(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.adapter is adapter
        finally:
            model.destroy()

    def test_builds_root_item_on_init(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.root_item is not None
            assert isinstance(model.root_item, LayerItem)
            assert model.root_item.identifier == ROOT_LAYER_IDENTIFIER
            assert model.root_item.is_session_layer is False
        finally:
            model.destroy()

    def test_builds_session_item_when_adapter_has_one(self) -> None:
        adapter = MockLayerStackAdapter(include_session=True)
        model = LayerModel(adapter)
        try:
            assert model.session_item is not None
            assert model.session_item.identifier == SESSION_LAYER_IDENTIFIER
            assert model.session_item.is_session_layer is True
        finally:
            model.destroy()

    def test_no_session_item_when_adapter_has_none(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        model = LayerModel(adapter)
        try:
            assert model.session_item is None
        finally:
            model.destroy()

    def test_default_settings_when_none_passed(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert isinstance(model.settings, DefaultLayerSettings)
            assert model.settings.show_session_layer is True
        finally:
            model.destroy()

    def test_custom_settings_stored(self) -> None:
        adapter = MockLayerStackAdapter()
        settings = DefaultLayerSettings(show_session_layer=False)
        model = LayerModel(adapter, settings=settings)
        try:
            assert model.settings is settings
        finally:
            model.destroy()

    def test_root_layer_registered_in_sublayers_cache(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert ROOT_LAYER_IDENTIFIER in model._sublayers_cache
            assert model._sublayers_cache[ROOT_LAYER_IDENTIFIER] == [
                model.root_item
            ]
        finally:
            model.destroy()

    def test_root_layer_registered_in_items_by_id(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model._items_by_id[ROOT_LAYER_IDENTIFIER] is model.root_item
            assert (
                model._items_by_id[SESSION_LAYER_IDENTIFIER]
                is model.session_item
            )
        finally:
            model.destroy()


# ─── Top-level children (plan Verify bullet) ──────────────────────────────────


class TestTopLevelChildren:
    def test_children_with_session_hidden_returns_root_only(self) -> None:
        adapter = MockLayerStackAdapter(include_session=True)
        model = LayerModel(
            adapter, settings=DefaultLayerSettings(show_session_layer=False)
        )
        try:
            children = model.get_item_children(None)
            assert children == [model.root_item]
        finally:
            model.destroy()

    def test_children_with_session_shown_returns_session_then_root(self) -> None:
        adapter = MockLayerStackAdapter(include_session=True)
        model = LayerModel(
            adapter, settings=DefaultLayerSettings(show_session_layer=True)
        )
        try:
            children = model.get_item_children(None)
            assert children == [model.session_item, model.root_item]
        finally:
            model.destroy()

    def test_children_when_adapter_has_no_session(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        model = LayerModel(adapter)
        try:
            children = model.get_item_children(None)
            assert children == [model.root_item]
        finally:
            model.destroy()

    def test_layer_item_returns_its_sublayers(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            # Step 14 populates sublayers — Step 13 returns whatever the
            # item currently holds (empty list by default).
            children = model.get_item_children(model.root_item)
            assert children == []
        finally:
            model.destroy()

    def test_unknown_item_returns_empty_list(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.get_item_children("not a LayerItem") == []
        finally:
            model.destroy()


# ─── can_item_have_children ───────────────────────────────────────────────────


class TestCanItemHaveChildren:
    def test_none_can_have_children(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.can_item_have_children(None) is True
        finally:
            model.destroy()

    def test_layer_item_without_sublayers_returns_false(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.can_item_have_children(model.root_item) is False
        finally:
            model.destroy()

    def test_non_layer_item_returns_false(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.can_item_have_children("string") is False
        finally:
            model.destroy()


# ─── Value model plumbing ────────────────────────────────────────────────────


class TestValueModel:
    def test_column_count_is_seven(self) -> None:
        # LAYERS-PLAN Step 17 — the TreeView allocates a cell per column,
        # so the model must advertise all seven (name + six flag columns).
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.get_item_value_model_count(model.root_item) == 7
            assert LayerModel.NUM_COLUMNS == 7
        finally:
            model.destroy()

    def test_column_zero_returns_layer_name_value_model(self) -> None:
        # LAYERS-PLAN Step 18 — column 0 graduated from a plain
        # ``ui.SimpleStringModel`` to a :class:`LayerNameValueModel`
        # so the delegate can pick up state suffixes and the color
        # role without reaching back through the adapter itself.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            vm = model.get_item_value_model(model.root_item, 0)
            assert isinstance(vm, LayerNameValueModel)
            assert isinstance(vm, ui.AbstractValueModel)
        finally:
            model.destroy()

    def test_value_model_carries_display_name(self) -> None:
        # Mock adapter defaults the edit target to the root layer, and
        # Step 24 now applies that snapshot on construction, so the
        # Step-18 suffix renders on the root row. Flipping the target
        # to a non-existent id clears root's flag without surfacing
        # any other row's label — giving us a clean "bare display
        # name" assertion surface.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            model._update_edit_target("")
            vm = model.get_item_value_model(model.root_item, 0)
            assert vm.get_value_as_string() == "root"
        finally:
            model.destroy()

    def test_session_layer_display_name_has_anonymous_suffix(self) -> None:
        # Session layer in the mock is anonymous by construction
        # (:class:`MockLayerStackAdapter`). Step 27 swapped the
        # Step-18 ``(Anonymous)`` parenthetical for the terser
        # ``[anon]`` bracket tag so the session row reads as a metadata
        # annotation rather than a prose hint.
        adapter = MockLayerStackAdapter(include_session=True)
        model = LayerModel(adapter)
        try:
            vm = model.get_item_value_model(model.session_item, 0)
            assert vm.get_value_as_string() == "session [anon]"
        finally:
            model.destroy()

    def test_value_model_is_cached_on_item(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            vm_first = model.get_item_value_model(model.root_item, 0)
            vm_second = model.get_item_value_model(model.root_item, 0)
            assert vm_first is vm_second
        finally:
            model.destroy()

    def test_column_two_returns_save_value_model(self) -> None:
        # LAYERS-PLAN Step 19 — column 2 graduated from the shared
        # placeholder to a :class:`SaveValueModel`. Lazy-cached on the
        # item so every re-render of the row reuses the same instance
        # (Logic F4).
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            vm = model.get_item_value_model(model.root_item, 2)
            assert isinstance(vm, SaveValueModel)
            assert isinstance(vm, ui.AbstractValueModel)
            assert model.root_item._save_model is vm
            # Second access returns the cached instance, not a new one.
            assert model.get_item_value_model(model.root_item, 2) is vm
        finally:
            model.destroy()

    def test_column_three_returns_local_mute_value_model(self) -> None:
        # LAYERS-PLAN Step 20 — column 3 graduated from the shared
        # placeholder to a :class:`LocalMuteValueModel`. Same lazy-per-
        # item cache contract as Step 19's save model.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            vm = model.get_item_value_model(model.root_item, 3)
            assert isinstance(vm, LocalMuteValueModel)
            assert isinstance(vm, ui.AbstractValueModel)
            assert model.root_item._local_mute_model is vm
            assert model.get_item_value_model(model.root_item, 3) is vm
        finally:
            model.destroy()

    def test_column_six_returns_lock_value_model(self) -> None:
        # LAYERS-PLAN Step 21 — column 6 graduated from the shared
        # placeholder to a :class:`LockValueModel`. Same lazy-per-
        # item cache contract as Steps 19 and 20.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            vm = model.get_item_value_model(model.root_item, 6)
            assert isinstance(vm, LockValueModel)
            assert isinstance(vm, ui.AbstractValueModel)
            assert model.root_item._lock_model is vm
            assert model.get_item_value_model(model.root_item, 6) is vm
        finally:
            model.destroy()

    @pytest.mark.parametrize("col", [1, 4, 5])
    def test_icon_columns_return_empty_placeholder_model(self, col: int) -> None:
        # Columns 1, 4, 5 remain blank placeholders until Step 22 wires
        # their per-item models. The placeholder must be non-``None``
        # (``ui.TreeView`` faults on a null value model) and must read
        # back as an empty string. Columns 2, 3, and 6 graduated in
        # Steps 19, 20, and 21 — covered by the dedicated tests above.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            vm = model.get_item_value_model(model.root_item, col)
            assert isinstance(vm, ui.SimpleStringModel)
            assert vm.get_value_as_string() == ""
        finally:
            model.destroy()

    def test_placeholder_value_model_shared_across_items_and_columns(
        self,
    ) -> None:
        # The placeholder is stateless so a single shared instance is
        # correct; allocating per-(item, col) would churn extra
        # ``SimpleStringModel`` objects per row for every not-yet-
        # graduated column (Step 22 replaces the rest).
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "kid")
        model = LayerModel(adapter)
        try:
            root_col1 = model.get_item_value_model(model.root_item, 1)
            root_col4 = model.get_item_value_model(model.root_item, 4)
            kid = model._items_by_id["kid"]
            kid_col5 = model.get_item_value_model(kid, 5)
            assert root_col1 is root_col4
            assert root_col1 is kid_col5
        finally:
            model.destroy()

    def test_column_outside_range_returns_none(self) -> None:
        # Defensive — ovui should only ever hand back ``0 <= col < 7``,
        # but the model must not fault if something queries column 7.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.get_item_value_model(model.root_item, 7) is None
            assert model.get_item_value_model(model.root_item, -1) is None
        finally:
            model.destroy()

    def test_non_layer_item_value_model_is_none(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.get_item_value_model("string", 0) is None
            # Non-layer items don't get placeholders either — Phase J
            # prim-spec rows will have their own dispatch in the model.
            assert model.get_item_value_model("string", 3) is None
        finally:
            model.destroy()


# ─── Adapter events ───────────────────────────────────────────────────────────


class TestEventDispatch:
    def test_sublayers_changed_triggers_item_changed_none(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            notifications: list = []
            sub = model.subscribe_item_changed_fn(
                lambda m, item: notifications.append(item)
            )
            # Drop the reference once the assertion is done — ui subscriptions
            # use opaque handles whose identity doesn't matter.
            _ = sub
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_A")
            # The event must fire at least once with ``None`` → full-tree rebuild.
            assert None in notifications
        finally:
            model.destroy()

    def test_sublayers_changed_preserves_top_level_item(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            original_root = model.root_item
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_A")
            # Step 32: the structural pass reloads the sublayer
            # subtree under the existing root item; the top-level
            # ``LayerItem`` instance is preserved so long-lived
            # references (selection, value-model caches, etc.) stay
            # valid across structural events.
            assert model.root_item is original_root
            assert [s.identifier for s in model.root_item.sublayers] == [
                "sub_A"
            ]
            assert model.root_item.identifier == ROOT_LAYER_IDENTIFIER
        finally:
            model.destroy()

    def test_edit_target_changed_refreshes_edit_target_cache(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_A")
        model = LayerModel(adapter)
        try:
            assert model._edit_target_identifier == ROOT_LAYER_IDENTIFIER
            adapter.set_edit_target("sub_A")
            assert model._edit_target_identifier == "sub_A"
        finally:
            model.destroy()

    def test_dirty_state_change_invalidates_item_flags(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            # Warm the cache so _flags_dirty flips to False.
            assert model.root_item.is_dirty is False
            assert model.root_item._flags_dirty is False
            adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
            # Flag event must mark the affected item dirty again.
            assert model.root_item._flags_dirty is True
            # Re-read → picks up the new value.
            assert model.root_item.is_dirty is True
        finally:
            model.destroy()

    def test_mute_state_change_routes_to_items_by_id(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.root_item.is_muted is False
            assert model.root_item._flags_dirty is False
            adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
            assert model.root_item._flags_dirty is True
            assert model.root_item.is_muted is True
        finally:
            model.destroy()


# ─── Lifecycle ────────────────────────────────────────────────────────────────


class TestLifecycle:
    def test_destroy_cancels_event_subscription(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        assert len(adapter._subscribers) == 1
        model.destroy()
        assert len(adapter._subscribers) == 0

    def test_destroy_is_idempotent(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        model.destroy()
        model.destroy()  # must not raise
        assert model.root_item is None
        assert model.session_item is None

    def test_destroyed_model_ignores_events(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        model.destroy()
        # Firing an event on a destroyed model must not throw —
        # the subscription was cancelled so nothing reaches us.
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_A")  # no raise
        assert model.root_item is None


# ─── Sublayer recursion (Step 14) ─────────────────────────────────────────────


class TestSublayerRecursion:
    """LAYERS-PLAN Step 14: lazy ``_load_sublayers`` with cache + cycle guard."""

    def test_nested_three_levels(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub1")
        adapter.add_sublayer("sub1", "sub2")
        model = LayerModel(adapter)
        try:
            root = model.root_item
            assert len(root.sublayers) == 1
            sub1 = root.sublayers[0]
            assert sub1.identifier == "sub1"
            assert sub1.parent is root
            assert len(sub1.sublayers) == 1
            sub2 = sub1.sublayers[0]
            assert sub2.identifier == "sub2"
            assert sub2.parent is sub1
            assert sub2.sublayers == []
        finally:
            model.destroy()

    def test_can_item_have_children_follows_sublayer_population(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "kid")
        model = LayerModel(adapter)
        try:
            assert model.can_item_have_children(model.root_item) is True
            assert model.can_item_have_children(model.root_item.sublayers[0]) is False
        finally:
            model.destroy()

    def test_get_item_children_returns_populated_sublayers(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "kid_a")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "kid_b")
        model = LayerModel(adapter)
        try:
            kids = model.get_item_children(model.root_item)
            assert [k.identifier for k in kids] == ["kid_a", "kid_b"]
        finally:
            model.destroy()

    def test_direct_cycle_does_not_recurse(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "self_ref")
        # self_ref references itself — a direct cycle.
        adapter.add_sublayer("self_ref", "self_ref")
        model = LayerModel(adapter)
        try:
            root = model.root_item
            assert len(root.sublayers) == 1
            self_ref = root.sublayers[0]
            assert self_ref.identifier == "self_ref"
            # The self-reference at depth 2 is filtered by the cycle guard.
            assert self_ref.sublayers == []
        finally:
            model.destroy()

    def test_indirect_cycle_breaks_recursion(self) -> None:
        """root → A → B → A — the inner A is dropped by the parent-chain guard."""
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "A")
        adapter.add_sublayer("A", "B")
        adapter.add_sublayer("B", "A")
        model = LayerModel(adapter)
        try:
            root = model.root_item
            assert len(root.sublayers) == 1
            a_item = root.sublayers[0]
            assert a_item.identifier == "A"
            assert len(a_item.sublayers) == 1
            b_item = a_item.sublayers[0]
            assert b_item.identifier == "B"
            # B's child "A" is an ancestor → skipped.
            assert b_item.sublayers == []
        finally:
            model.destroy()

    def test_same_sublayer_under_two_parents_stored_twice_in_cache(self) -> None:
        """Plan verify bullet: two occurrences → ``_sublayers_cache`` length 2."""
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "A")
        adapter.add_sublayer("A", "B")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "B")
        model = LayerModel(adapter)
        try:
            cache = model._sublayers_cache["B"]
            assert len(cache) == 2
            parents = {item.parent.identifier for item in cache}
            assert parents == {"A", ROOT_LAYER_IDENTIFIER}
            assert all(item.identifier == "B" for item in cache)
        finally:
            model.destroy()

    def test_new_sublayer_registered_in_items_by_id(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_x")
        model = LayerModel(adapter)
        try:
            assert "sub_x" in model._items_by_id
            assert model._items_by_id["sub_x"].identifier == "sub_x"
            assert model._items_by_id["sub_x"].parent is model.root_item
        finally:
            model.destroy()

    def test_items_by_id_prefers_first_cached_instance(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "A")
        adapter.add_sublayer("A", "B")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "B")
        model = LayerModel(adapter)
        try:
            # First occurrence (under A) wins the fast-path slot.
            cache = model._sublayers_cache["B"]
            assert model._items_by_id["B"] is cache[0]
        finally:
            model.destroy()

    def test_sublayer_flags_are_refreshed_after_load(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_d")
        adapter.set_dirty("sub_d", True)
        model = LayerModel(adapter)
        try:
            sub = model.root_item.sublayers[0]
            # ``_load_sublayers`` must have called refresh_flags so the
            # cached dirty bit already reflects the adapter state.
            assert sub._flags_dirty is False
            assert sub.is_dirty is True
        finally:
            model.destroy()

    def test_sublayers_changed_event_adds_new_sublayer(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        model = LayerModel(adapter)
        try:
            assert model.root_item.sublayers == []
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "hot_add")
            # Full reset is Step 13's handler — after it we still see
            # the new sublayer (Step 14 populates descendants).
            assert len(model.root_item.sublayers) == 1
            assert model.root_item.sublayers[0].identifier == "hot_add"
            assert "hot_add" in model._items_by_id
            assert model._sublayers_cache["hot_add"][0].parent is model.root_item
        finally:
            model.destroy()

    def test_remove_sublayer_updates_tree_and_cache(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "transient")
        model = LayerModel(adapter)
        try:
            assert "transient" in model._items_by_id
            adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
            assert model.root_item.sublayers == []
            assert "transient" not in model._items_by_id
            assert "transient" not in model._sublayers_cache
        finally:
            model.destroy()

    def test_remove_nested_sublayer_cleans_descendants(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "parent")
        adapter.add_sublayer("parent", "child")
        adapter.add_sublayer("child", "grandchild")
        model = LayerModel(adapter)
        try:
            assert "grandchild" in model._items_by_id
            # Remove the middle node — the adapter fires SUBLAYERS_CHANGED
            # for "parent"; the full re-load drops child + grandchild.
            adapter.remove_sublayer("parent", 0)
            assert model.root_item.sublayers[0].sublayers == []
            assert "child" not in model._items_by_id
            assert "grandchild" not in model._items_by_id
            assert "child" not in model._sublayers_cache
            assert "grandchild" not in model._sublayers_cache
        finally:
            model.destroy()

    def test_session_sublayers_are_loaded_too(self) -> None:
        adapter = MockLayerStackAdapter(include_session=True)
        adapter.add_sublayer(SESSION_LAYER_IDENTIFIER, "session_child")
        model = LayerModel(adapter)
        try:
            session = model.session_item
            assert session is not None
            assert len(session.sublayers) == 1
            assert session.sublayers[0].identifier == "session_child"
        finally:
            model.destroy()

    def test_destroy_clears_sublayer_caches(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        adapter.add_sublayer("a", "b")
        model = LayerModel(adapter)
        assert "b" in model._items_by_id
        model.destroy()
        assert model._items_by_id == {}
        assert dict(model._sublayers_cache) == {}

    def test_destroy_subtree_promotes_sibling_into_items_by_id(self) -> None:
        """Destroying one instance of a cloned layer keeps the other reachable."""
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "A")
        adapter.add_sublayer("A", "B")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "B")
        model = LayerModel(adapter)
        try:
            primary = model._items_by_id["B"]
            # Remove the B under A (position 0 in A's sublayers) — the
            # clone directly under root must take over the fast-path slot.
            adapter.remove_sublayer("A", 0)
            remaining = model._items_by_id["B"]
            assert remaining is not primary
            assert remaining.parent is model.root_item
            assert len(model._sublayers_cache["B"]) == 1
        finally:
            model.destroy()


# ─── Regressions ──────────────────────────────────────────────────────────────


class TestEventEnumCoverage:
    """Guard against new :class:`LayerEventType` values being silently ignored."""

    def test_all_event_types_handled_without_raising(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            for event_type in LayerEventType:
                # Every defined event must be dispatchable without error.
                model._on_layer_event(
                    LayerEvent(
                        event_type=event_type,
                        identifiers=(ROOT_LAYER_IDENTIFIER,),
                    )
                )
        finally:
            model.destroy()


# ─── Stage attach / detach lifecycle (Step 15) ────────────────────────────────


class TestStageLifecycle:
    """LAYERS-PLAN Step 15: ``set_adapter`` re-targets the model in place."""

    def test_constructed_with_none_adapter_is_empty(self) -> None:
        # A model with no adapter must start empty and hold no subs.
        model = LayerModel(None)
        try:
            assert model.adapter is None
            assert model.root_item is None
            assert model.session_item is None
            assert model._event_sub is None
            assert model.get_item_children(None) == []
        finally:
            model.destroy()

    def test_set_adapter_populates_tree_from_empty(self) -> None:
        adapter = MockLayerStackAdapter(include_session=True)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_x")
        model = LayerModel(None)
        try:
            model.set_adapter(adapter)
            assert model.adapter is adapter
            assert model.root_item is not None
            assert model.root_item.identifier == ROOT_LAYER_IDENTIFIER
            assert model.session_item is not None
            assert [s.identifier for s in model.root_item.sublayers] == ["sub_x"]
            assert len(adapter._subscribers) == 1
        finally:
            model.destroy()

    def test_set_adapter_none_empties_tree_and_cancels_subscription(
        self,
    ) -> None:
        adapter = MockLayerStackAdapter(include_session=True)
        model = LayerModel(adapter)
        try:
            assert len(adapter._subscribers) == 1
            model.set_adapter(None)
            assert model.adapter is None
            assert model.root_item is None
            assert model.session_item is None
            assert model._items_by_id == {}
            assert dict(model._sublayers_cache) == {}
            assert model._event_sub is None
            assert len(adapter._subscribers) == 0
            # Empty tree answers the top-level query with no rows.
            assert model.get_item_children(None) == []
        finally:
            model.destroy()

    def test_set_adapter_switch_rewires_to_new_adapter(self) -> None:
        # adapter A has a distinct sublayer shape from adapter B — after
        # the swap, the tree must reflect B and A must be fully detached.
        adapter_a = MockLayerStackAdapter()
        adapter_a.add_sublayer(ROOT_LAYER_IDENTIFIER, "from_a")
        adapter_b = MockLayerStackAdapter()
        adapter_b.add_sublayer(ROOT_LAYER_IDENTIFIER, "from_b1")
        adapter_b.add_sublayer(ROOT_LAYER_IDENTIFIER, "from_b2")

        model = LayerModel(adapter_a)
        try:
            assert [s.identifier for s in model.root_item.sublayers] == [
                "from_a"
            ]
            model.set_adapter(adapter_b)
            assert model.adapter is adapter_b
            assert [s.identifier for s in model.root_item.sublayers] == [
                "from_b1",
                "from_b2",
            ]
            # A's caches are wiped and its subscription is cancelled.
            assert "from_a" not in model._items_by_id
            assert "from_a" not in model._sublayers_cache
            assert len(adapter_a._subscribers) == 0
            assert len(adapter_b._subscribers) == 1
        finally:
            model.destroy()

    def test_set_adapter_fires_item_changed_none(self) -> None:
        # The bound TreeView must re-query after a retarget — we notify
        # with ``None`` to signal a full-tree invalidation.
        adapter_a = MockLayerStackAdapter()
        adapter_b = MockLayerStackAdapter()
        model = LayerModel(adapter_a)
        try:
            notifications: list = []
            sub = model.subscribe_item_changed_fn(
                lambda m, item: notifications.append(item)
            )
            _ = sub  # retain through the test
            notifications.clear()
            model.set_adapter(adapter_b)
            assert None in notifications
        finally:
            model.destroy()

    def test_set_adapter_swaps_do_not_accumulate_subscribers(self) -> None:
        # Repeated retarget must keep at most one subscriber alive on
        # the currently-attached adapter — guards against the classic
        # "forgot to unsubscribe" leak.
        adapter_a = MockLayerStackAdapter()
        adapter_b = MockLayerStackAdapter()
        model = LayerModel(adapter_a)
        try:
            for _ in range(5):
                model.set_adapter(adapter_b)
                model.set_adapter(adapter_a)
            assert len(adapter_a._subscribers) == 1
            assert len(adapter_b._subscribers) == 0
        finally:
            model.destroy()

    def test_events_from_old_adapter_ignored_after_swap(self) -> None:
        # After set_adapter(B), firing events on A must not reach the
        # model — the subscription was cancelled, so the handler is
        # never invoked. Rebuilds only run for B's events.
        adapter_a = MockLayerStackAdapter()
        adapter_b = MockLayerStackAdapter()
        model = LayerModel(adapter_a)
        try:
            model.set_adapter(adapter_b)
            # Mutating A must not retarget or re-populate the model.
            adapter_a.add_sublayer(ROOT_LAYER_IDENTIFIER, "ghost")
            assert "ghost" not in model._items_by_id
            # Mutations on B still drive updates.
            adapter_b.add_sublayer(ROOT_LAYER_IDENTIFIER, "real")
            assert "real" in model._items_by_id
        finally:
            model.destroy()

    def test_destroy_is_safe_after_set_adapter_none(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        model.set_adapter(None)
        model.destroy()  # must not raise
        assert model.adapter is None
        assert model.root_item is None

    def test_set_adapter_after_destroy_is_noop(self) -> None:
        # A destroyed model rejects reattachment — callers should drop
        # the reference, not revive the corpse.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        model.destroy()
        model.set_adapter(MockLayerStackAdapter())
        assert model.root_item is None
        assert model.adapter is None

    def test_layer_items_released_after_set_adapter_none(self) -> None:
        # After detach every materialised ``LayerItem`` must become
        # unreferenced from the model so the cycle breaks and the
        # weakref callback eventually fires.
        import gc
        import weakref

        adapter = MockLayerStackAdapter(include_session=True)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "kid")
        model = LayerModel(adapter)
        kid = model._items_by_id["kid"]
        kid_ref = weakref.ref(kid)
        root_ref = weakref.ref(model.root_item)
        session_ref = weakref.ref(model.session_item)
        del kid
        model.set_adapter(None)
        gc.collect()
        assert kid_ref() is None
        assert root_ref() is None
        assert session_ref() is None
        model.destroy()


# ─── Selection (Step 16) ──────────────────────────────────────────────────────


class TestSelection:
    """LAYERS-PLAN Step 16 — single-column selection tracking on the model."""

    def test_selected_items_empty_by_default(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model.selected_items == []
        finally:
            model.destroy()

    def test_set_selected_items_records_list(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "kid")
        model = LayerModel(adapter)
        try:
            kid = model._items_by_id["kid"]
            model.set_selected_items([kid])
            assert model.selected_items == [kid]
        finally:
            model.destroy()

    def test_selected_items_returns_defensive_copy(self) -> None:
        # Mutating the accessor result must not corrupt the internal
        # list — guards against callers appending / clearing in place.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            root = model.root_item
            model.set_selected_items([root])
            snapshot = model.selected_items
            snapshot.clear()
            assert model.selected_items == [root]
        finally:
            model.destroy()

    def test_set_selected_items_filters_non_layer_items(self) -> None:
        # TreeView should only ever hand back ``LayerItem`` instances in
        # Step 16 (no prim-spec rows yet), but the mutator must stay
        # type-stable — Phase J will mix prim-spec rows into the tree.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            root = model.root_item
            model.set_selected_items([root, "not-a-layer-item", 42, None])
            assert model.selected_items == [root]
        finally:
            model.destroy()

    def test_set_selected_items_replaces_previous(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "kid_a")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "kid_b")
        model = LayerModel(adapter)
        try:
            a = model._items_by_id["kid_a"]
            b = model._items_by_id["kid_b"]
            model.set_selected_items([a])
            model.set_selected_items([b])
            assert model.selected_items == [b]
        finally:
            model.destroy()

    def test_set_selected_items_accepts_empty_list(self) -> None:
        # Clicking into empty tree space should clear the selection.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            model.set_selected_items([model.root_item])
            model.set_selected_items([])
            assert model.selected_items == []
        finally:
            model.destroy()

    def test_set_adapter_clears_selection(self) -> None:
        # Selection references items from the previous adapter; the
        # retarget path must drop them so the new tree starts fresh.
        adapter_a = MockLayerStackAdapter()
        model = LayerModel(adapter_a)
        try:
            model.set_selected_items([model.root_item])
            model.set_adapter(MockLayerStackAdapter())
            assert model.selected_items == []
        finally:
            model.destroy()

    def test_set_adapter_none_clears_selection(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            model.set_selected_items([model.root_item])
            model.set_adapter(None)
            assert model.selected_items == []
        finally:
            model.destroy()

    def test_destroy_clears_selection(self) -> None:
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        model.set_selected_items([model.root_item])
        model.destroy()
        assert model.selected_items == []

    def test_set_selected_items_after_destroy_is_noop(self) -> None:
        # Late callbacks from a torn-down TreeView must not resurrect
        # any state on the destroyed model.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        root = model.root_item
        model.destroy()
        model.set_selected_items([root])
        assert model.selected_items == []

    def test_selected_items_released_after_adapter_swap(self) -> None:
        import gc
        import weakref

        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "kid")
        model = LayerModel(adapter)
        try:
            kid = model._items_by_id["kid"]
            kid_ref = weakref.ref(kid)
            model.set_selected_items([kid])
            del kid
            model.set_adapter(MockLayerStackAdapter())
            gc.collect()
            assert kid_ref() is None
        finally:
            model.destroy()


# ─── Edit-target tracking (Step 24) ──────────────────────────────────────────


class TestStep24EditTargetTracking:
    """LAYERS-PLAN Step 24 — ``_edit_target_identifier`` in sync with the
    adapter, ``LayerItem._is_edit_target`` flags fan across clones, and
    ``_has_edit_target_descendant`` propagates up the parent chain."""

    def test_initial_edit_target_flag_set_on_root(self) -> None:
        # Mock adapter defaults the edit target to ROOT_LAYER_IDENTIFIER;
        # Step 24 must apply that initial state so the Step-18 name
        # model starts rendering the "(Authoring Layer)" suffix on the
        # very first paint — previously the flag waited for a live
        # ``set_edit_target`` call before it flipped.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            assert model._edit_target_identifier == ROOT_LAYER_IDENTIFIER
            assert model.root_item.is_edit_target is True
        finally:
            model.destroy()

    def test_initial_edit_target_name_model_has_suffix(self) -> None:
        # End-to-end: the name value model of the edit-target row must
        # return the suffixed label. This is the plan's verify bullet.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub1")
        adapter._edit_target_id = "sub1"
        model = LayerModel(adapter)
        try:
            sub1 = model._items_by_id["sub1"]
            assert sub1.is_edit_target is True
            vm = model.get_item_value_model(sub1, 0)
            assert vm.get_value_as_string() == "sub1 (Authoring Layer)"
        finally:
            model.destroy()

    def test_event_swaps_is_edit_target_flag(self) -> None:
        # Plan verify bullet: ``adapter.set_edit_target(sub1.identifier)``
        # → ``LayerItem(sub1)._is_edit_target == True`` and name model
        # returns the suffixed label.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub1")
        model = LayerModel(adapter)
        try:
            sub1 = model._items_by_id["sub1"]
            assert model.root_item.is_edit_target is True
            assert sub1.is_edit_target is False

            adapter.set_edit_target("sub1")

            assert model.root_item.is_edit_target is False
            assert sub1.is_edit_target is True
            vm = model.get_item_value_model(sub1, 0)
            assert vm.get_value_as_string() == "sub1 (Authoring Layer)"
        finally:
            model.destroy()

    def test_event_does_not_rebuild_tree(self) -> None:
        # EDIT_TARGET_CHANGED is no longer a structural event — the
        # existing ``LayerItem`` instances must survive the swap so
        # lazily-built value models and selection references stay
        # valid. Previously this event type landed on the structural
        # branch of ``_on_layer_event`` and incinerated the tree.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub1")
        model = LayerModel(adapter)
        try:
            original_root = model.root_item
            original_sub = model._items_by_id["sub1"]
            adapter.set_edit_target("sub1")
            assert model.root_item is original_root
            assert model._items_by_id["sub1"] is original_sub
        finally:
            model.destroy()

    def test_parent_chain_flag_set_for_deep_target(self) -> None:
        # root → mid → deep; when ``deep`` is the edit target, every
        # ancestor up to ``root`` must report ``has_edit_target_descendant``.
        # Step 26 reads this flag to draw the half-green ancestor icon.
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "mid")
        adapter.add_sublayer("mid", "deep")
        model = LayerModel(adapter)
        try:
            deep = model._items_by_id["deep"]
            mid = model._items_by_id["mid"]
            adapter.set_edit_target("deep")
            assert deep.is_edit_target is True
            assert mid.has_edit_target_descendant is True
            assert model.root_item.has_edit_target_descendant is True
        finally:
            model.destroy()

    def test_parent_chain_flag_cleared_when_target_moves_up(self) -> None:
        # Moving the edit target from a deep layer back to the root
        # must clear the ``_has_edit_target_descendant`` flag on every
        # intermediate ancestor — otherwise the Step-26 half-green
        # icon would stay lit on nodes that no longer contain the
        # authoring layer.
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "mid")
        adapter.add_sublayer("mid", "deep")
        model = LayerModel(adapter)
        try:
            adapter.set_edit_target("deep")
            mid = model._items_by_id["mid"]
            assert mid.has_edit_target_descendant is True

            adapter.set_edit_target(ROOT_LAYER_IDENTIFIER)

            assert mid.has_edit_target_descendant is False
            assert model.root_item.is_edit_target is True
            # Root is its own ancestor chain — nothing above it to flag.
            assert model.root_item.has_edit_target_descendant is False
        finally:
            model.destroy()

    def test_swap_between_siblings_moves_flag(self) -> None:
        # Sibling swap: old edit target loses its flag, new one gains
        # it, and the shared ``root`` ancestor flag stays ``True`` the
        # entire time — that is, the clear phase of the transition is
        # immediately undone by the set phase on the same ancestor so
        # the row does not briefly flicker to "no authoring descendant".
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sib_a")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sib_b")
        model = LayerModel(adapter)
        try:
            a = model._items_by_id["sib_a"]
            b = model._items_by_id["sib_b"]
            adapter.set_edit_target("sib_a")
            assert a.is_edit_target is True
            assert model.root_item.has_edit_target_descendant is True

            adapter.set_edit_target("sib_b")

            assert a.is_edit_target is False
            assert b.is_edit_target is True
            assert model.root_item.has_edit_target_descendant is True
        finally:
            model.destroy()

    def test_clones_all_flip_together(self) -> None:
        # A single layer sublayered under two parents appears twice in
        # the tree. Both clones must flip their ``_is_edit_target`` bit
        # in lockstep, otherwise the authoring-layer badge would show
        # on only one of the rows and the other would look stale.
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "A")
        adapter.add_sublayer("A", "B")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "B")
        model = LayerModel(adapter)
        try:
            clones = model._sublayers_cache["B"]
            assert len(clones) == 2
            adapter.set_edit_target("B")
            assert all(clone.is_edit_target for clone in clones)
        finally:
            model.destroy()

    def test_clone_ancestor_chains_all_flagged(self) -> None:
        # Same clone scenario as above — every distinct ancestor of
        # every clone gets ``_has_edit_target_descendant`` set. ``A``
        # sees the flag via the ``root → A → B`` chain; ``root`` sees
        # it via both chains.
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "A")
        adapter.add_sublayer("A", "B")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "B")
        model = LayerModel(adapter)
        try:
            a_item = model._items_by_id["A"]
            adapter.set_edit_target("B")
            assert a_item.has_edit_target_descendant is True
            assert model.root_item.has_edit_target_descendant is True
        finally:
            model.destroy()

    def test_noop_when_identifier_unchanged(self) -> None:
        # If the adapter re-emits ``EDIT_TARGET_CHANGED`` with the same
        # target identifier (happens after a re-join on a live session
        # whose target matched the previous snapshot), the model must
        # not fire spurious notifications. Assert by counting
        # ``item_changed`` notifications: zero after a redundant set.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            notifications: list = []
            sub = model.subscribe_item_changed_fn(
                lambda m, item: notifications.append(item)
            )
            _ = sub
            notifications.clear()
            # Directly call the internal path; ``adapter.set_edit_target``
            # short-circuits upstream on equal target, so fire the
            # event by hand to exercise ``_update_edit_target``.
            model._update_edit_target(ROOT_LAYER_IDENTIFIER)
            assert notifications == []
        finally:
            model.destroy()

    def test_fires_item_changed_on_old_and_new_target(self) -> None:
        # Both the leaving and the arriving row must re-render so the
        # suffix appears / disappears. Ancestors do *not* fire here —
        # their visual cue (half-green icon) lands in Step 26, and we
        # don't want to drag every ancestor through a rebuild until
        # the delegate actually consumes ``_has_edit_target_descendant``.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub1")
        model = LayerModel(adapter)
        try:
            notifications: list = []
            sub = model.subscribe_item_changed_fn(
                lambda m, item: notifications.append(item)
            )
            _ = sub
            notifications.clear()
            adapter.set_edit_target("sub1")
            assert model.root_item in notifications
            assert model._items_by_id["sub1"] in notifications
        finally:
            model.destroy()

    def test_fires_value_changed_on_name_model(self) -> None:
        # Fire-through check: the Step-18 ``LayerNameValueModel`` must
        # get its ``_value_changed`` poked on the edit-target rows so
        # an already-rendered label picks up the new suffix without
        # a full row rebuild.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub1")
        model = LayerModel(adapter)
        try:
            # Materialise the name value models by reading them.
            root_name_vm = model.get_item_value_model(model.root_item, 0)
            sub_name_vm = model.get_item_value_model(
                model._items_by_id["sub1"], 0
            )
            fired: list = []

            def _listener(vm):
                # ``ui.AbstractValueModel.subscribe_value_changed_fn``
                # delivers the model itself; we just record the calls.
                fired.append(vm)

            # Track via direct subscription — every VM exposes the same
            # hook by inheriting from ``ui.AbstractValueModel``.
            root_sub = root_name_vm.subscribe_value_changed_fn(_listener)
            sub_sub = sub_name_vm.subscribe_value_changed_fn(_listener)
            _ = root_sub, sub_sub

            adapter.set_edit_target("sub1")
            assert root_name_vm in fired
            assert sub_name_vm in fired
        finally:
            model.destroy()

    def test_edit_target_survives_sublayers_changed_rebuild(self) -> None:
        # SUBLAYERS_CHANGED rebuilds the tree — every ``LayerItem`` is
        # re-minted. The edit-target flag must be re-applied to the
        # fresh instance that inherits the old identifier, otherwise
        # adding a sublayer would silently drop the authoring-layer
        # indication on the existing edit-target row.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub1")
        adapter.set_edit_target("sub1")
        model = LayerModel(adapter)
        try:
            assert model._items_by_id["sub1"].is_edit_target is True

            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_new")

            sub1_fresh = model._items_by_id["sub1"]
            assert sub1_fresh.is_edit_target is True
            # And root — not the edit target — must not carry the flag
            # accidentally set by the rebuild.
            assert model.root_item.is_edit_target is False
        finally:
            model.destroy()

    def test_unknown_edit_target_is_safe(self) -> None:
        # Adapter returns an identifier the tree doesn't know about
        # (can happen transiently between a ``set_edit_target`` and
        # the follow-up ``SUBLAYERS_CHANGED`` that brings the layer
        # into the tree). The model must not raise.
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter)
        try:
            model._update_edit_target("ghost_layer_id")
            assert model._edit_target_identifier == "ghost_layer_id"
            # Root's flag was cleared by the transition away from it;
            # no row in the tree now carries ``_is_edit_target``.
            assert model.root_item.is_edit_target is False
        finally:
            model.destroy()

    def test_set_adapter_applies_edit_target_to_new_tree(self) -> None:
        # Retargeting at a new adapter must apply that adapter's edit
        # target to its freshly-built tree — the detach / reattach
        # path goes through ``_reset_root`` same as construction.
        adapter_a = MockLayerStackAdapter()
        adapter_b = MockLayerStackAdapter()
        adapter_b.add_sublayer(ROOT_LAYER_IDENTIFIER, "b_sub")
        adapter_b.set_edit_target("b_sub")
        model = LayerModel(adapter_a)
        try:
            model.set_adapter(adapter_b)
            assert model._edit_target_identifier == "b_sub"
            assert model._items_by_id["b_sub"].is_edit_target is True
            assert model.root_item.has_edit_target_descendant is True
        finally:
            model.destroy()


# ─── Ancestor notification propagation (Step 26) ────────────────────────────


class TestStep26AncestorNotifications:
    """LAYERS-PLAN Step 26 — ``_update_edit_target`` now fires
    ``_item_changed(ancestor)`` on every row whose
    ``_has_edit_target_descendant`` flag flipped, so the Step-25
    half-green leading icon re-renders mid-session rather than only
    on first paint."""

    def test_fires_on_intermediate_ancestor_when_deep_target_set(self) -> None:
        # root → mid → deep; moving the edit target onto ``deep`` must
        # fire ``_item_changed`` on ``mid`` so the half-green icon
        # paints on the already-rendered row without waiting for a
        # hover / scroll repaint.
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "mid")
        adapter.add_sublayer("mid", "deep")
        model = LayerModel(adapter)
        try:
            mid = model._items_by_id["mid"]
            notifications: list = []
            sub = model.subscribe_item_changed_fn(
                lambda m, item: notifications.append(item)
            )
            _ = sub
            notifications.clear()

            adapter.set_edit_target("deep")

            assert mid in notifications, (
                "intermediate ancestor must re-render so its half-green "
                "leading icon appears"
            )
            assert model._items_by_id["deep"] in notifications
        finally:
            model.destroy()

    def test_fires_on_ancestor_when_target_clears(self) -> None:
        # Moving the edit target off a deep layer must fire
        # ``_item_changed`` on every intermediate ancestor so its
        # half-green icon drops back to the neutral state.
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "mid")
        adapter.add_sublayer("mid", "deep")
        model = LayerModel(adapter)
        try:
            adapter.set_edit_target("deep")
            mid = model._items_by_id["mid"]
            assert mid.has_edit_target_descendant is True
            notifications: list = []
            sub = model.subscribe_item_changed_fn(
                lambda m, item: notifications.append(item)
            )
            _ = sub
            notifications.clear()

            adapter.set_edit_target(ROOT_LAYER_IDENTIFIER)

            assert mid in notifications, (
                "mid must re-render so its half-green icon clears"
            )
            assert mid.has_edit_target_descendant is False
        finally:
            model.destroy()

    def test_ancestor_notification_deduplicated(self) -> None:
        # Sibling swap: root is the shared ancestor of both ``sib_a`` and
        # ``sib_b``. The clear phase enters root once, the set phase
        # enters root again — the notification pass must dedup so the
        # row fires exactly once.
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sib_a")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sib_b")
        model = LayerModel(adapter)
        try:
            adapter.set_edit_target("sib_a")
            notifications: list = []
            sub = model.subscribe_item_changed_fn(
                lambda m, item: notifications.append(item)
            )
            _ = sub
            notifications.clear()

            adapter.set_edit_target("sib_b")

            root_fires = [i for i in notifications if i is model.root_item]
            assert len(root_fires) == 1, (
                f"expected root to fire exactly once, got {len(root_fires)} "
                f"(notifications={notifications!r})"
            )
        finally:
            model.destroy()

    def test_target_also_ancestor_not_fired_twice(self) -> None:
        # When the old edit target is root and the new one is root's
        # direct child, root sits in both the "touched targets" and
        # "touched ancestors" sets. Step 26 skips the ancestor-phase
        # fire on any row already notified as a target so the row
        # doesn't rebuild twice in one event dispatch.
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub1")
        model = LayerModel(adapter)
        try:
            assert model.root_item.is_edit_target is True
            notifications: list = []
            sub = model.subscribe_item_changed_fn(
                lambda m, item: notifications.append(item)
            )
            _ = sub
            notifications.clear()

            adapter.set_edit_target("sub1")

            root_fires = [i for i in notifications if i is model.root_item]
            assert len(root_fires) == 1
            sub_fires = [
                i for i in notifications if i is model._items_by_id["sub1"]
            ]
            assert len(sub_fires) == 1
        finally:
            model.destroy()

    def test_no_ancestor_fires_when_target_is_top_level(self) -> None:
        # Target is always a top-level row (root has no parent chain to
        # walk). Only the two target clones fire; no ancestor-phase
        # notifications land in the subscriber's list.
        adapter = MockLayerStackAdapter(include_session=True)
        model = LayerModel(adapter)
        try:
            # Session swap: both session and root are top-level
            # so neither walk touches a parent. Total notifications
            # equals the count of target clones (old root + new
            # session = 2).
            notifications: list = []
            sub = model.subscribe_item_changed_fn(
                lambda m, item: notifications.append(item)
            )
            _ = sub
            notifications.clear()

            adapter.set_edit_target(SESSION_LAYER_IDENTIFIER)

            assert model.root_item in notifications
            assert model.session_item in notifications
            # Only the two target rows — no phantom ancestor fire because
            # neither has a parent.
            assert len(notifications) == 2
        finally:
            model.destroy()

    def test_clone_ancestor_chains_both_notified(self) -> None:
        # A layer sublayered under two parents has two clones. Every
        # distinct ancestor along every clone's parent chain must
        # fire exactly once — ``A`` fires from the ``root → A → B``
        # chain, ``root`` fires once even though it is reached via
        # both clone chains.
        adapter = MockLayerStackAdapter(include_session=False)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "A")
        adapter.add_sublayer("A", "B")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "B")
        model = LayerModel(adapter)
        try:
            a_item = model._items_by_id["A"]
            notifications: list = []
            sub = model.subscribe_item_changed_fn(
                lambda m, item: notifications.append(item)
            )
            _ = sub
            notifications.clear()

            adapter.set_edit_target("B")

            assert a_item in notifications
            root_fires = [i for i in notifications if i is model.root_item]
            assert len(root_fires) == 1
        finally:
            model.destroy()


# ─── Step 32 — event batching, auto-heal, cascade, INFO ───────────────────────


class _DeferringApp:
    """Test stand-in for :class:`ovui_widgets.app.application.Application`.

    Collects ``call_later`` callbacks into a manual queue so tests can
    fire multiple adapter events before the flush runs — the real
    flush is per-frame-coalesced, so the deferring app mirrors that
    cadence. The ``tick`` helper drains the queue in one shot, which
    is what the frame loop does between paints.
    """

    def __init__(self) -> None:
        from ovui_widgets.common.selection import SelectionBus
        from ovui_widgets.common.undo import UndoManager

        self.undo_manager = UndoManager()
        self.selection_bus = SelectionBus()
        self._queue: list = []

    def call_later(self, _delay: float, cb) -> None:
        self._queue.append(cb)

    def tick(self) -> int:
        """Fire every queued callback; return the number that fired."""
        fired = 0
        while self._queue:
            cb = self._queue.pop(0)
            cb()
            fired += 1
        return fired

    @property
    def pending(self) -> int:
        return len(self._queue)


class TestStep32EventBatching:
    """LAYERS-PLAN Step 32 — queue events across the frame and flush once."""

    def test_multiple_events_same_frame_coalesce_into_one_flush(self) -> None:
        # 50 dirty flips in a single "frame" schedule exactly one
        # ``_flush_events`` call through ``call_later`` — the batching
        # is what prevents a busy stage from incinerating the UI.
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub")
        model = LayerModel(adapter, services=app)
        try:
            for flag in [True, False] * 25:
                adapter.set_dirty("sub", flag)
            # All 50 events are queued but only one flush is scheduled.
            assert app.pending == 1
            assert len(model._pending_events) == 50
            fired = app.tick()
            assert fired == 1
            assert model._pending_events == []
            # After the flush the flag reflects the adapter's terminal
            # state (alternating True/False 50 times ends on False).
            assert model._items_by_id["sub"].is_dirty is False
        finally:
            model.destroy()

    def test_flush_scheduled_flag_resets_after_flush(self) -> None:
        # After the flush fires, a subsequent event schedules a new
        # flush — the ``_flush_scheduled`` latch is one-shot per
        # frame.
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter, services=app)
        try:
            adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
            assert model._flush_scheduled is True
            app.tick()
            assert model._flush_scheduled is False
            # Second event re-arms the flush.
            adapter.set_dirty(ROOT_LAYER_IDENTIFIER, False)
            assert model._flush_scheduled is True
            assert app.pending == 1
        finally:
            model.destroy()

    def test_late_events_after_destroy_drop_cleanly(self) -> None:
        # A destroyed model must not fire a pending flush — the queue
        # is cleared and the frame callback no-ops.
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter, services=app)
        # Queue an event, then tear down before the flush tick runs.
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert app.pending == 1
        model.destroy()
        # Firing the queued flush on the destroyed model is safe.
        app.tick()  # must not raise
        assert model._pending_events == []


class TestStep32MixedBatch:
    """Structural events in a batch must not discard the non-structural
    events queued alongside them (Logic F1)."""

    def test_sublayers_and_dirty_in_same_batch(self) -> None:
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_a")
        model = LayerModel(adapter, services=app)
        try:
            app.tick()  # drain the constructor's initial queue
            # Queue a structural + a dirty event in the same "frame".
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_b")
            adapter.set_dirty("sub_a", True)
            assert len(model._pending_events) == 2
            app.tick()
            # Structural event reflected — new sublayer is present.
            assert "sub_b" in model._items_by_id
            # Dirty event preserved — sub_a re-read from the adapter
            # returns True despite the structural pass running first.
            assert model._items_by_id["sub_a"].is_dirty is True
        finally:
            model.destroy()

    def test_sublayers_and_mute_in_same_batch(self) -> None:
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_a")
        model = LayerModel(adapter, services=app)
        try:
            app.tick()
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_b")
            adapter.set_mute("sub_a", True)
            app.tick()
            # Both events leave their mark.
            assert "sub_b" in model._items_by_id
            assert model._items_by_id["sub_a"].is_muted is True
        finally:
            model.destroy()

    def test_edit_target_and_sublayers_in_same_batch(self) -> None:
        # The structural pass forces an edit-target re-propagation
        # (Logic U4); an edit-target event in the same batch re-runs
        # the targeted handler — both produce the final state.
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_a")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_b")
        model = LayerModel(adapter, services=app)
        try:
            app.tick()
            adapter.set_edit_target("sub_a")
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_c")
            app.tick()
            assert "sub_c" in model._items_by_id
            assert model._edit_target_identifier == "sub_a"
            assert model._items_by_id["sub_a"].is_edit_target is True
        finally:
            model.destroy()


class TestStep32AutoHealEditTarget:
    """LAYERS-WINDOW-ARCHITECTURE §16.6 / §37.9 #9 — USD silently
    rejects edits on a muted (or UI-locked) layer. Muting the edit
    target must auto-heal back to root so subsequent attribute edits
    are not swallowed."""

    def test_muting_edit_target_falls_back_to_root(self) -> None:
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_a")
        model = LayerModel(adapter, services=app)
        try:
            app.tick()
            adapter.set_edit_target("sub_a")
            app.tick()
            assert model._edit_target_identifier == "sub_a"
            # Mute the current target — the flush must heal the
            # edit target back to the root layer.
            adapter.set_mute("sub_a", True)
            app.tick()
            # The auto-heal push was itself a command → it queued an
            # EDIT_TARGET_CHANGED event. Run another tick so the
            # deferred flush picks up the heal's event.
            app.tick()
            assert model._edit_target_identifier == ROOT_LAYER_IDENTIFIER
            assert model.root_item.is_edit_target is True
            assert model._items_by_id["sub_a"].is_edit_target is False
        finally:
            model.destroy()

    def test_locking_edit_target_falls_back_to_root(self) -> None:
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_a")
        model = LayerModel(adapter, services=app)
        try:
            app.tick()
            adapter.set_edit_target("sub_a")
            app.tick()
            adapter.set_lock("sub_a", True)
            app.tick()
            app.tick()
            assert model._edit_target_identifier == ROOT_LAYER_IDENTIFIER
        finally:
            model.destroy()

    def test_auto_heal_pushes_undoable_command(self) -> None:
        # Step 32 routes the heal through
        # :class:`SetEditTargetCommand` so Ctrl+Z reverses it. The
        # undo stack must then pop back to the pre-heal target.
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_a")
        model = LayerModel(adapter, services=app)
        try:
            app.tick()
            adapter.set_edit_target("sub_a")
            app.tick()
            initial_stack_depth = len(app.undo_manager._undo_stack)
            adapter.set_mute("sub_a", True)
            app.tick()
            app.tick()
            assert len(app.undo_manager._undo_stack) == initial_stack_depth + 1
            assert model._edit_target_identifier == ROOT_LAYER_IDENTIFIER
        finally:
            model.destroy()

    def test_no_heal_when_edit_target_not_muted_or_locked(self) -> None:
        # Muting a *different* layer than the edit target must not
        # trigger the heal path.
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_a")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_b")
        model = LayerModel(adapter, services=app)
        try:
            app.tick()
            adapter.set_edit_target("sub_a")
            app.tick()
            initial_depth = len(app.undo_manager._undo_stack)
            adapter.set_mute("sub_b", True)
            app.tick()
            assert model._edit_target_identifier == "sub_a"
            assert len(app.undo_manager._undo_stack) == initial_depth
        finally:
            model.destroy()

    def test_no_heal_when_root_is_edit_target_and_root_muted(self) -> None:
        # Defensive: root is never unmuted by the heal because there
        # is nothing safer to fall back to. The target stays on root.
        app = _DeferringApp()
        adapter = MockLayerStackAdapter()
        model = LayerModel(adapter, services=app)
        try:
            app.tick()
            assert model._edit_target_identifier == ROOT_LAYER_IDENTIFIER
            adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
            app.tick()
            # Edit target stays on root; no heal command is pushed.
            assert model._edit_target_identifier == ROOT_LAYER_IDENTIFIER
        finally:
            model.destroy()

    def test_headless_auto_heal_bypasses_undo_stack(self) -> None:
        # Without an ``app``, the heal goes straight through the
        # adapter — the model is still headless-testable.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "sub_a")
        model = LayerModel(adapter)  # no app
        try:
            adapter.set_edit_target("sub_a")
            adapter.set_mute("sub_a", True)
            assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER
            assert model._edit_target_identifier == ROOT_LAYER_IDENTIFIER
        finally:
            model.destroy()


class TestStep32MuteLockCascade:
    """Muting a parent must dim every descendant row — the cascade
    travels via ``LayerItem.muted_or_parent_muted``, which the name
    model's ``get_color_role`` reads on every paint."""

    def test_muting_root_dims_every_descendant(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "mid")
        adapter.add_sublayer("mid", "deep")
        model = LayerModel(adapter)
        try:
            mid = model._items_by_id["mid"]
            deep = model._items_by_id["deep"]
            assert mid.muted_or_parent_muted is False
            assert deep.muted_or_parent_muted is False

            adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)

            assert mid.muted_or_parent_muted is True
            assert deep.muted_or_parent_muted is True
            # Own bits are unchanged.
            assert mid.is_muted is False
            assert deep.is_muted is False
        finally:
            model.destroy()

    def test_mute_cascade_fires_name_model_refresh_on_descendants(
        self,
    ) -> None:
        # The cascade must poke every descendant's name model so
        # already-rendered rows repaint with the ``disabled`` color
        # role on the next frame.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "mid")
        adapter.add_sublayer("mid", "deep")
        model = LayerModel(adapter)
        try:
            mid = model._items_by_id["mid"]
            deep = model._items_by_id["deep"]
            # Force name-model construction so it exists to subscribe to.
            mid_vm = model.get_item_value_model(mid, 0)
            deep_vm = model.get_item_value_model(deep, 0)
            hits: list = []
            mid_vm.add_value_changed_fn(lambda m: hits.append(m))
            deep_vm.add_value_changed_fn(lambda m: hits.append(m))

            adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)

            assert mid_vm in hits
            assert deep_vm in hits
        finally:
            model.destroy()

    def test_lock_cascade_fires_name_model_refresh_on_descendants(
        self,
    ) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "mid")
        adapter.add_sublayer("mid", "deep")
        model = LayerModel(adapter)
        try:
            mid = model._items_by_id["mid"]
            deep = model._items_by_id["deep"]
            mid_vm = model.get_item_value_model(mid, 0)
            deep_vm = model.get_item_value_model(deep, 0)
            hits: list = []
            mid_vm.add_value_changed_fn(lambda m: hits.append(m))
            deep_vm.add_value_changed_fn(lambda m: hits.append(m))

            adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)

            assert mid_vm in hits
            assert deep_vm in hits
        finally:
            model.destroy()

    def test_cascade_invalidates_descendant_flag_caches(self) -> None:
        # After warming the descendant's flag cache, a cascade must
        # mark it dirty so the next read re-queries.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "deep")
        model = LayerModel(adapter)
        try:
            deep = model._items_by_id["deep"]
            _ = deep.is_muted  # warm cache
            assert deep._flags_dirty is False

            adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)

            assert deep._flags_dirty is True
        finally:
            model.destroy()

    def test_descendants_color_role_picks_up_mute_cascade(self) -> None:
        # End-to-end: the name model's ``get_color_role`` walks the
        # parent chain and returns ``"disabled"`` when an ancestor is
        # muted, so the Step-18 label delegate paints the row in the
        # gray disabled tint without the descendant's own bit changing.
        from ovui_widgets.layers.models.layer_name_model import COLOR_ROLE_DISABLED

        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "deep")
        model = LayerModel(adapter)
        try:
            deep = model._items_by_id["deep"]
            vm = model.get_item_value_model(deep, 0)
            assert vm.get_color_role() != COLOR_ROLE_DISABLED
            adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
            assert vm.get_color_role() == COLOR_ROLE_DISABLED
        finally:
            model.destroy()


class TestStep32InfoChanged:
    """INFO_CHANGED must flow through ``_flush_events`` and refresh the
    name model so future metadata-backed labels pick up the event."""

    def test_info_changed_fires_name_value_changed(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "target")
        model = LayerModel(adapter)
        try:
            target = model._items_by_id["target"]
            vm = model.get_item_value_model(target, 0)
            hits: list = []
            vm.add_value_changed_fn(lambda m: hits.append(m))
            # The mock's ``set_missing`` fires INFO_CHANGED.
            adapter.set_missing("target", True)
            assert vm in hits
            # ``(Missing)`` suffix is now visible because the flag
            # cache was invalidated and refreshed.
            assert "(Missing)" in vm.get_value_as_string()
        finally:
            model.destroy()

    def test_info_changed_fans_across_clones(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "A")
        adapter.add_sublayer("A", "B")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "B")
        model = LayerModel(adapter)
        try:
            clones = model._sublayers_cache["B"]
            assert len(clones) == 2
            vms = [model.get_item_value_model(c, 0) for c in clones]
            hits: list = []
            for vm in vms:
                vm.add_value_changed_fn(lambda m, h=hits: h.append(m))

            adapter.set_missing("B", True)

            assert {id(m) for m in hits} == {id(vm) for vm in vms}
        finally:
            model.destroy()


class TestStep32DirtyPoll:
    """The per-flush dirty-bit poll catches DIRTY_STATE_CHANGED events
    the adapter forgot to emit (LAYERS-WINDOW-ARCHITECTURE §34.14)."""

    def test_dirty_bit_flip_without_event_is_reconciled(self) -> None:
        # Simulate a missed DIRTY_STATE_CHANGED by flipping the
        # underlying flag directly. A subsequent flush (triggered by
        # any other event) must reconcile the cached bit.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "orphan")
        model = LayerModel(adapter)
        try:
            orphan = model._items_by_id["orphan"]
            _ = orphan.is_dirty  # warm the cache
            assert orphan._is_dirty is False
            # Flip the flag bypassing the mock's event-emitting
            # mutator, as a real USD backend sometimes does.
            adapter._layers["orphan"].dirty = True
            # Any unrelated event wakes the flush, which runs the
            # dirty-poll reconciliation pass.
            adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
            assert orphan._is_dirty is True
        finally:
            model.destroy()

    def test_dirty_poll_fires_save_notification(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "orphan")
        model = LayerModel(adapter)
        try:
            orphan = model._items_by_id["orphan"]
            save_vm = model.get_item_value_model(orphan, 2)
            hits: list = []
            save_vm.add_value_changed_fn(lambda m: hits.append(m))
            _ = orphan.is_dirty  # warm cache
            adapter._layers["orphan"].dirty = True
            # Trigger a flush via an unrelated event.
            adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
            assert save_vm in hits
        finally:
            model.destroy()
