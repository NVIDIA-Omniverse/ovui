# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`MockLayerStackAdapter` (LAYERS-PLAN Step 2)."""

from __future__ import annotations

from typing import List

import pytest
from ovui_data_adapters.common import LayerEvent, LayerEventType, LayerHandle, LayerStackAdapter

from ovui_widgets.app.testing import MockLayer, MockLayerStackAdapter
from ovui_widgets.common.settings import Subscription
from ovui_widgets.common.testing.mock_layer_stack import (
    ROOT_LAYER_IDENTIFIER,
    SESSION_LAYER_IDENTIFIER,
)

# ─── Construction ─────────────────────────────────────────────────────────────


class TestConstruction:
    def test_is_layer_stack_adapter_instance(self) -> None:
        adapter = MockLayerStackAdapter()
        assert isinstance(adapter, LayerStackAdapter)

    def test_root_layer_exists_after_construction(self) -> None:
        adapter = MockLayerStackAdapter()
        root = adapter.get_root_layer()
        assert isinstance(root, LayerHandle)
        assert root.identifier == ROOT_LAYER_IDENTIFIER

    def test_root_display_name_is_root(self) -> None:
        adapter = MockLayerStackAdapter()
        assert adapter.get_display_name(adapter.get_root_layer()) == "root"

    def test_session_layer_exists_by_default(self) -> None:
        adapter = MockLayerStackAdapter()
        session = adapter.get_session_layer()
        assert isinstance(session, LayerHandle)
        assert session.identifier == SESSION_LAYER_IDENTIFIER

    def test_session_layer_is_anonymous(self) -> None:
        adapter = MockLayerStackAdapter()
        assert adapter.is_anonymous(adapter.get_session_layer()) is True

    def test_root_is_not_anonymous(self) -> None:
        adapter = MockLayerStackAdapter()
        assert adapter.is_anonymous(adapter.get_root_layer()) is False

    def test_include_session_false_omits_session(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        assert adapter.get_session_layer() is None

    def test_initial_edit_target_is_root(self) -> None:
        adapter = MockLayerStackAdapter()
        assert adapter.get_edit_target_identifier() == ROOT_LAYER_IDENTIFIER

    def test_root_starts_with_no_sublayers(self) -> None:
        adapter = MockLayerStackAdapter()
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == []

    def test_all_flags_default_false_on_root(self) -> None:
        adapter = MockLayerStackAdapter()
        root = adapter.get_root_layer()
        assert adapter.is_dirty(root) is False
        assert adapter.is_muted(root) is False
        assert adapter.is_locked(root) is False
        assert adapter.is_read_only_on_disk(root) is False
        assert adapter.is_missing(root) is False

    def test_owner_defaults_to_empty_string(self) -> None:
        adapter = MockLayerStackAdapter()
        assert adapter.get_layer_owner(adapter.get_root_layer()) == ""


# ─── find_layer ───────────────────────────────────────────────────────────────


class TestFindLayer:
    def test_find_root_returns_handle(self) -> None:
        adapter = MockLayerStackAdapter()
        handle = adapter.find_layer(ROOT_LAYER_IDENTIFIER)
        assert handle == LayerHandle(ROOT_LAYER_IDENTIFIER)

    def test_find_session_returns_handle(self) -> None:
        adapter = MockLayerStackAdapter()
        handle = adapter.find_layer(SESSION_LAYER_IDENTIFIER)
        assert handle == LayerHandle(SESSION_LAYER_IDENTIFIER)

    def test_find_unknown_returns_none(self) -> None:
        adapter = MockLayerStackAdapter()
        assert adapter.find_layer("nope.usda") is None

    def test_find_after_add_sublayer(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child.usda")
        assert adapter.find_layer("child.usda") == LayerHandle("child.usda")


# ─── add_sublayer ─────────────────────────────────────────────────────────────


class TestAddSublayer:
    def test_add_sublayer_appears_in_parent_sublayer_identifiers(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child.usda")
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == [
            "child.usda"
        ]

    def test_add_sublayer_returns_handle_for_new_layer(self) -> None:
        adapter = MockLayerStackAdapter()
        handle = adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child.usda")
        assert handle == LayerHandle("child.usda")

    def test_add_sublayer_fires_sublayers_changed(self) -> None:
        adapter = MockLayerStackAdapter()
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child.usda")
        assert len(events) == 1
        assert events[0].event_type == LayerEventType.SUBLAYERS_CHANGED
        assert events[0].identifiers == (ROOT_LAYER_IDENTIFIER,)

    def test_add_sublayer_default_display_name_is_identifier(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child.usda")
        assert (
            adapter.get_display_name(LayerHandle("child.usda")) == "child.usda"
        )

    def test_add_sublayer_honors_display_name_argument(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(
            ROOT_LAYER_IDENTIFIER, "child.usda", display_name="Pretty Name"
        )
        assert adapter.get_display_name(LayerHandle("child.usda")) == "Pretty Name"

    def test_add_sublayer_at_position_zero_inserts_at_front(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "b")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a", position=0)
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == ["a", "b"]

    def test_add_sublayer_negative_position_appends(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "b", position=-1)
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == ["a", "b"]

    def test_add_sublayer_position_beyond_length_appends(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "b", position=999)
        # list.insert with an out-of-range index clamps to the end.
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == ["a", "b"]

    def test_add_sublayer_on_unknown_parent_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(KeyError):
            adapter.add_sublayer("unknown", "child")

    def test_duplicate_add_creates_second_reference(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
        # USD permits a layer to appear twice in a parent's sublayer list.
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == [
            "child",
            "child",
        ]

    def test_duplicate_add_does_not_duplicate_mocklayer(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child", display_name="First")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
        # Display name keeps its first value when second call omits display_name.
        assert adapter.get_display_name(LayerHandle("child")) == "First"

    def test_duplicate_add_with_new_display_name_overwrites(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child", display_name="First")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child", display_name="Second")
        assert adapter.get_display_name(LayerHandle("child")) == "Second"

    def test_nested_sublayers(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "mid")
        adapter.add_sublayer("mid", "leaf")
        assert adapter.get_sublayer_identifiers(LayerHandle("mid")) == ["leaf"]

    def test_get_sublayer_identifiers_returns_copy(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
        returned = adapter.get_sublayer_identifiers(adapter.get_root_layer())
        returned.append("bogus")
        # Internal state must not reflect the caller's mutation.
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == ["child"]


# ─── remove_sublayer ──────────────────────────────────────────────────────────


class TestRemoveSublayer:
    def test_remove_sublayer_drops_from_list(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "b")
        adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == ["b"]

    def test_remove_sublayer_returns_identifier(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        removed = adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
        assert removed == "a"

    def test_remove_sublayer_fires_event(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
        assert len(events) == 1
        assert events[0].event_type == LayerEventType.SUBLAYERS_CHANGED
        assert events[0].identifiers == (ROOT_LAYER_IDENTIFIER,)

    def test_remove_from_empty_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(IndexError):
            adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)

    def test_remove_negative_position_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        with pytest.raises(IndexError):
            adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, -1)

    def test_remove_out_of_range_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        with pytest.raises(IndexError):
            adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 99)

    def test_remove_sublayer_on_unknown_parent_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(KeyError):
            adapter.remove_sublayer("unknown", 0)

    def test_remove_does_not_delete_layer_record(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
        # The layer itself remains — another parent could still reference it.
        assert adapter.find_layer("a") == LayerHandle("a")


# ─── State flag mutators ──────────────────────────────────────────────────────


class TestSetDirty:
    def test_set_dirty_flips_flag(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert adapter.is_dirty(adapter.get_root_layer()) is True

    def test_set_dirty_fires_event(self) -> None:
        adapter = MockLayerStackAdapter()
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert len(events) == 1
        assert events[0].event_type == LayerEventType.DIRTY_STATE_CHANGED
        assert events[0].identifiers == (ROOT_LAYER_IDENTIFIER,)

    def test_set_dirty_idempotent_no_event(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert events == []

    def test_set_dirty_unknown_layer_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(KeyError):
            adapter.set_dirty("unknown", True)


class TestSetMute:
    def test_set_mute_flips_flag_and_fires(self) -> None:
        adapter = MockLayerStackAdapter()
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        assert adapter.is_muted(adapter.get_root_layer()) is True
        assert [e.event_type for e in events] == [LayerEventType.MUTE_STATE_CHANGED]

    def test_set_mute_idempotent(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        assert events == []


class TestSetLock:
    def test_set_lock_flips_flag_and_fires(self) -> None:
        adapter = MockLayerStackAdapter()
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
        assert adapter.is_locked(adapter.get_root_layer()) is True
        assert [e.event_type for e in events] == [LayerEventType.LOCK_STATE_CHANGED]


class TestSetReadOnly:
    def test_set_read_only_flips_flag_and_fires(self) -> None:
        adapter = MockLayerStackAdapter()
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.set_read_only(ROOT_LAYER_IDENTIFIER, True)
        assert adapter.is_read_only_on_disk(adapter.get_root_layer()) is True
        assert [e.event_type for e in events] == [
            LayerEventType.FILE_PERMISSION_CHANGED
        ]


class TestSetMissing:
    def test_set_missing_flips_flag(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_missing(ROOT_LAYER_IDENTIFIER, True)
        assert adapter.is_missing(adapter.get_root_layer()) is True

    def test_set_missing_fires_info_changed_with_missing_field(self) -> None:
        adapter = MockLayerStackAdapter()
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.set_missing(ROOT_LAYER_IDENTIFIER, True)
        assert len(events) == 1
        assert events[0].event_type == LayerEventType.INFO_CHANGED
        assert events[0].identifiers == (ROOT_LAYER_IDENTIFIER,)
        assert events[0].info_fields == {ROOT_LAYER_IDENTIFIER: ("missing",)}


# ─── Edit target ──────────────────────────────────────────────────────────────


class TestEditTarget:
    def test_set_edit_target_updates_identifier(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
        adapter.set_edit_target("child")
        assert adapter.get_edit_target_identifier() == "child"

    def test_set_edit_target_fires_event(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.set_edit_target("child")
        assert len(events) == 1
        assert events[0].event_type == LayerEventType.EDIT_TARGET_CHANGED
        assert events[0].identifiers == ("child",)

    def test_set_edit_target_idempotent(self) -> None:
        adapter = MockLayerStackAdapter()
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.set_edit_target(ROOT_LAYER_IDENTIFIER)
        assert events == []

    def test_set_edit_target_unknown_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(KeyError):
            adapter.set_edit_target("unknown")


# ─── get_layer_stack_identifiers ──────────────────────────────────────────────


class TestGetLayerStackIdentifiers:
    def test_empty_stack_returns_root_only(self) -> None:
        adapter = MockLayerStackAdapter()
        assert adapter.get_layer_stack_identifiers() == [ROOT_LAYER_IDENTIFIER]

    def test_include_session_true_adds_session_first(self) -> None:
        adapter = MockLayerStackAdapter()
        ids = adapter.get_layer_stack_identifiers(include_session=True)
        assert ids == [SESSION_LAYER_IDENTIFIER, ROOT_LAYER_IDENTIFIER]

    def test_include_anonymous_false_omits_session(self) -> None:
        adapter = MockLayerStackAdapter()
        ids = adapter.get_layer_stack_identifiers(
            include_session=True, include_anonymous=False
        )
        assert ids == [ROOT_LAYER_IDENTIFIER]

    def test_walks_nested_sublayers(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "mid")
        adapter.add_sublayer("mid", "leaf")
        ids = adapter.get_layer_stack_identifiers()
        assert ids == [ROOT_LAYER_IDENTIFIER, "mid", "leaf"]

    def test_include_anonymous_false_skips_anonymous_sublayer(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "file.usda")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "anon")
        adapter._layers["anon"].anonymous = True
        ids = adapter.get_layer_stack_identifiers(
            include_session=False, include_anonymous=False
        )
        assert ids == [ROOT_LAYER_IDENTIFIER, "file.usda"]

    def test_duplicate_references_walked_once(self) -> None:
        # A layer referenced twice in the same parent should appear once in
        # the composed stack — otherwise the UI would render duplicates.
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
        ids = adapter.get_layer_stack_identifiers()
        assert ids == [ROOT_LAYER_IDENTIFIER, "child"]

    def test_cycle_does_not_recurse_forever(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        # Manually create a cycle: a references root back.
        adapter._layers["a"].sublayer_identifiers.append(ROOT_LAYER_IDENTIFIER)
        ids = adapter.get_layer_stack_identifiers()
        assert ids == [ROOT_LAYER_IDENTIFIER, "a"]

    def test_without_session_ignores_include_session_flag(self) -> None:
        adapter = MockLayerStackAdapter(include_session=False)
        ids = adapter.get_layer_stack_identifiers(include_session=True)
        assert ids == [ROOT_LAYER_IDENTIFIER]


# ─── is_writable (inherited concrete method on ABC) ──────────────────────────


class TestIsWritable:
    def test_writable_when_no_flags_set(self) -> None:
        adapter = MockLayerStackAdapter()
        assert adapter.is_writable(adapter.get_root_layer()) is True

    def test_not_writable_when_locked(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
        assert adapter.is_writable(adapter.get_root_layer()) is False

    def test_not_writable_when_muted(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        assert adapter.is_writable(adapter.get_root_layer()) is False

    def test_not_writable_when_read_only(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_read_only(ROOT_LAYER_IDENTIFIER, True)
        assert adapter.is_writable(adapter.get_root_layer()) is False

    def test_dirty_alone_does_not_block_writability(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert adapter.is_writable(adapter.get_root_layer()) is True


# ─── Subscription semantics ───────────────────────────────────────────────────


class TestSubscribeEvents:
    def test_subscribe_returns_subscription(self) -> None:
        adapter = MockLayerStackAdapter()
        sub = adapter.subscribe_events(lambda ev: None)
        assert isinstance(sub, Subscription)

    def test_callback_receives_events(self) -> None:
        adapter = MockLayerStackAdapter()
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
        assert [e.event_type for e in events] == [
            LayerEventType.DIRTY_STATE_CHANGED,
            LayerEventType.LOCK_STATE_CHANGED,
        ]

    def test_cancel_stops_callback(self) -> None:
        adapter = MockLayerStackAdapter()
        events: List[LayerEvent] = []
        sub = adapter.subscribe_events(events.append)
        sub.cancel()
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert events == []

    def test_cancel_is_idempotent(self) -> None:
        adapter = MockLayerStackAdapter()
        sub = adapter.subscribe_events(lambda ev: None)
        sub.cancel()
        sub.cancel()  # must not raise
        assert adapter._subscribers == []

    def test_multiple_subscribers_all_called(self) -> None:
        adapter = MockLayerStackAdapter()
        a_events: List[LayerEvent] = []
        b_events: List[LayerEvent] = []
        _sa = adapter.subscribe_events(a_events.append)
        _sb = adapter.subscribe_events(b_events.append)
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert len(a_events) == 1
        assert len(b_events) == 1

    def test_cancel_one_subscriber_does_not_affect_others(self) -> None:
        adapter = MockLayerStackAdapter()
        a_events: List[LayerEvent] = []
        b_events: List[LayerEvent] = []
        sa = adapter.subscribe_events(a_events.append)
        _sb = adapter.subscribe_events(b_events.append)
        sa.cancel()
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert a_events == []
        assert len(b_events) == 1

    def test_callback_that_cancels_during_dispatch(self) -> None:
        # Dispatch iterates a snapshot, so a callback cancelling its own
        # subscription mid-dispatch does not crash and still fires for this
        # event.
        adapter = MockLayerStackAdapter()
        received: List[LayerEvent] = []

        def cb(ev: LayerEvent) -> None:
            received.append(ev)
            holder.sub.cancel()

        class _Holder:
            sub: Subscription

        holder = _Holder()
        holder.sub = adapter.subscribe_events(cb)
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
        assert len(received) == 1
        assert adapter._subscribers == []


# ─── MockLayer dataclass ──────────────────────────────────────────────────────


class TestMockLayerDataclass:
    def test_defaults(self) -> None:
        layer = MockLayer(identifier="x")
        assert layer.identifier == "x"
        assert layer.display_name == ""
        assert layer.sublayer_identifiers == []
        assert layer.dirty is False
        assert layer.muted is False
        assert layer.locked is False
        assert layer.read_only is False
        assert layer.anonymous is False
        assert layer.missing is False
        assert layer.owner == ""
        assert layer.info == {}

    def test_sublayer_list_is_independent_per_instance(self) -> None:
        a = MockLayer(identifier="a")
        b = MockLayer(identifier="b")
        a.sublayer_identifiers.append("x")
        assert b.sublayer_identifiers == []

    def test_info_dict_is_independent_per_instance(self) -> None:
        a = MockLayer(identifier="a")
        b = MockLayer(identifier="b")
        a.info["k"] = "v"
        assert b.info == {}


# ─── ABC mutation surface (LAYERS-PLAN Step 6) ────────────────────────────────


class TestCreateSublayer:
    def test_create_anonymous_returns_anon_identifier(self) -> None:
        adapter = MockLayerStackAdapter()
        new_id = adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "")
        assert new_id.startswith("anon:")
        assert adapter.is_anonymous(LayerHandle(new_id)) is True

    def test_create_named_layer_uses_path_as_identifier(self) -> None:
        adapter = MockLayerStackAdapter()
        new_id = adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "child.usda")
        assert new_id == "child.usda"
        assert adapter.is_anonymous(LayerHandle(new_id)) is False

    def test_create_appends_to_parent_sublayer_list(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "existing")
        new_id = adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "new.usda")
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == [
            "existing",
            new_id,
        ]

    def test_create_at_position_zero_inserts_at_front(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "existing")
        new_id = adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, 0, "new.usda")
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == [
            new_id,
            "existing",
        ]

    def test_create_fires_sublayers_changed(self) -> None:
        adapter = MockLayerStackAdapter()
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "new.usda")
        assert [e.event_type for e in events] == [LayerEventType.SUBLAYERS_CHANGED]
        assert events[0].identifiers == (ROOT_LAYER_IDENTIFIER,)

    def test_create_duplicate_path_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "new.usda")
        with pytest.raises(ValueError):
            adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "new.usda")

    def test_create_on_unknown_parent_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(KeyError):
            adapter.create_sublayer("unknown", -1, "new.usda")

    def test_transfer_root_content_tags_the_new_layer(self) -> None:
        adapter = MockLayerStackAdapter()
        new_id = adapter.create_sublayer(
            ROOT_LAYER_IDENTIFIER, -1, "new.usda", transfer_root_content=True
        )
        assert adapter._layers[new_id].info.get("transferred_from_root") == "1"


class TestInsertSublayer:
    def test_insert_existing_layer_updates_parent(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "existing.usda")
        removed = adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 0)
        # Re-insert the removed identifier — simulates an undo roundtrip.
        adapter.insert_sublayer(ROOT_LAYER_IDENTIFIER, 0, removed)
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == [
            removed
        ]

    def test_insert_missing_path_marks_missing(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.insert_sublayer(ROOT_LAYER_IDENTIFIER, 0, "ghost.usda")
        assert adapter.is_missing(LayerHandle("ghost.usda")) is True

    def test_insert_at_negative_position_appends(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "a")
        adapter.insert_sublayer(ROOT_LAYER_IDENTIFIER, -1, "b")
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == [
            "a",
            "b",
        ]

    def test_insert_fires_sublayers_changed(self) -> None:
        adapter = MockLayerStackAdapter()
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.insert_sublayer(ROOT_LAYER_IDENTIFIER, 0, "x.usda")
        assert [e.event_type for e in events] == [LayerEventType.SUBLAYERS_CHANGED]

    def test_insert_on_unknown_parent_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(KeyError):
            adapter.insert_sublayer("unknown", 0, "x.usda")


class TestMoveSublayer:
    def test_same_parent_reorder_forward(self) -> None:
        adapter = MockLayerStackAdapter()
        for name in ("a", "b", "c"):
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, name)
        adapter.move_sublayer(ROOT_LAYER_IDENTIFIER, 0, ROOT_LAYER_IDENTIFIER, 2)
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == [
            "b",
            "a",
            "c",
        ]

    def test_same_parent_reorder_backward(self) -> None:
        adapter = MockLayerStackAdapter()
        for name in ("a", "b", "c"):
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, name)
        adapter.move_sublayer(ROOT_LAYER_IDENTIFIER, 2, ROOT_LAYER_IDENTIFIER, 0)
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == [
            "c",
            "a",
            "b",
        ]

    def test_cross_parent_move_with_remove_source(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "p1")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "p2")
        adapter.add_sublayer("p1", "child")
        adapter.move_sublayer("p1", 0, "p2", 0, remove_source=True)
        assert adapter.get_sublayer_identifiers(LayerHandle("p1")) == []
        assert adapter.get_sublayer_identifiers(LayerHandle("p2")) == ["child"]

    def test_cross_parent_copy_reference_keeps_both(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "p1")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "p2")
        adapter.add_sublayer("p1", "child")
        adapter.move_sublayer("p1", 0, "p2", 0, remove_source=False)
        assert adapter.get_sublayer_identifiers(LayerHandle("p1")) == ["child"]
        assert adapter.get_sublayer_identifiers(LayerHandle("p2")) == ["child"]

    def test_move_fires_event_for_each_parent_touched(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "p1")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "p2")
        adapter.add_sublayer("p1", "child")
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.move_sublayer("p1", 0, "p2", 0, remove_source=True)
        touched = {ev.identifiers[0] for ev in events}
        assert touched == {"p1", "p2"}

    def test_move_copy_reference_fires_only_for_destination(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "p1")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "p2")
        adapter.add_sublayer("p1", "child")
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.move_sublayer("p1", 0, "p2", 0, remove_source=False)
        assert [e.identifiers for e in events] == [("p2",)]

    def test_move_out_of_range_source_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(IndexError):
            adapter.move_sublayer(ROOT_LAYER_IDENTIFIER, 5, ROOT_LAYER_IDENTIFIER, 0)


class TestSaveLayer:
    def test_save_clean_layer_returns_true_and_no_event(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "child.usda")
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        assert adapter.save_layer("child.usda") is True
        assert events == []

    def test_save_dirty_layer_clears_dirty_and_fires_event(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "child.usda")
        adapter.set_dirty("child.usda", True)
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        assert adapter.save_layer("child.usda") is True
        assert adapter.is_dirty(LayerHandle("child.usda")) is False
        assert [e.event_type for e in events] == [
            LayerEventType.DIRTY_STATE_CHANGED
        ]

    def test_save_anonymous_returns_false(self) -> None:
        adapter = MockLayerStackAdapter()
        anon_id = adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "")
        adapter.set_dirty(anon_id, True)
        assert adapter.save_layer(anon_id) is False
        assert adapter.is_dirty(LayerHandle(anon_id)) is True

    def test_save_missing_returns_false(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.insert_sublayer(ROOT_LAYER_IDENTIFIER, 0, "ghost.usda")
        assert adapter.save_layer("ghost.usda") is False

    def test_save_unknown_raises(self) -> None:
        adapter = MockLayerStackAdapter()
        with pytest.raises(KeyError):
            adapter.save_layer("nope.usda")


class TestSaveLayerAs:
    def test_save_as_creates_new_record(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "src.usda")
        new_id = adapter.save_layer_as("src.usda", "dst.usda", replace_in_parent=False)
        assert new_id == "dst.usda"
        assert adapter.find_layer("dst.usda") == LayerHandle("dst.usda")
        # Source stays in place when replace_in_parent is False.
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == [
            "src.usda"
        ]

    def test_save_as_replace_swaps_parent_reference(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "src.usda")
        new_id = adapter.save_layer_as("src.usda", "dst.usda", replace_in_parent=True)
        assert new_id == "dst.usda"
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == [
            "dst.usda"
        ]

    def test_save_as_replace_fires_sublayers_changed(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "src.usda")
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        adapter.save_layer_as("src.usda", "dst.usda", replace_in_parent=True)
        assert any(
            e.event_type == LayerEventType.SUBLAYERS_CHANGED for e in events
        )

    def test_save_as_empty_path_returns_none(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "src.usda")
        assert adapter.save_layer_as("src.usda", "", replace_in_parent=False) is None

    def test_save_as_existing_path_returns_none(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "src.usda")
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "other.usda")
        assert (
            adapter.save_layer_as("src.usda", "other.usda", replace_in_parent=False)
            is None
        )


class TestReloadLayer:
    def test_reload_dirty_layer_clears_and_fires(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "child.usda")
        adapter.set_dirty("child.usda", True)
        events: List[LayerEvent] = []
        _sub = adapter.subscribe_events(events.append)
        assert adapter.reload_layer("child.usda") is True
        assert adapter.is_dirty(LayerHandle("child.usda")) is False
        assert [e.event_type for e in events] == [
            LayerEventType.DIRTY_STATE_CHANGED
        ]

    def test_reload_clean_layer_returns_false(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "child.usda")
        assert adapter.reload_layer("child.usda") is False

    def test_reload_anonymous_returns_false(self) -> None:
        adapter = MockLayerStackAdapter()
        anon_id = adapter.create_sublayer(ROOT_LAYER_IDENTIFIER, -1, "")
        assert adapter.reload_layer(anon_id) is False


class TestSetMuteABC:
    """``set_mute`` is the ABC method name (v. the legacy ``set_muted``)."""

    def test_set_mute_round_trip(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child")
        adapter.set_mute("child", True)
        assert adapter.is_muted(LayerHandle("child")) is True
        adapter.set_mute("child", False)
        assert adapter.is_muted(LayerHandle("child")) is False


class TestSetLockABC:
    def test_set_lock_round_trip(self) -> None:
        adapter = MockLayerStackAdapter()
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
        assert adapter.is_locked(adapter.get_root_layer()) is True
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, False)
        assert adapter.is_locked(adapter.get_root_layer()) is False


class TestRemoveSublayerRoundTrip:
    """remove_sublayer + insert_sublayer → undo pattern used by Phase F."""

    def test_remove_then_insert_restores_ordering(self) -> None:
        adapter = MockLayerStackAdapter()
        for name in ("a", "b", "c"):
            adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, name)
        removed = adapter.remove_sublayer(ROOT_LAYER_IDENTIFIER, 1)
        adapter.insert_sublayer(ROOT_LAYER_IDENTIFIER, 1, removed)
        assert adapter.get_sublayer_identifiers(adapter.get_root_layer()) == [
            "a",
            "b",
            "c",
        ]
