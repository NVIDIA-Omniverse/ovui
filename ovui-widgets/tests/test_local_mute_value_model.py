# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ovui_widgets.layers.models.mute_model.LocalMuteValueModel`
(LAYERS-PLAN Step 20).

Covers the plan's Verify bullets — mute boolean read, lazy per-item
caching (Logic F4), click-to-toggle write surface, and the
:meth:`_value_changed` refresh hook fired from the owning
:class:`LayerModel` when the adapter emits ``MUTE_STATE_CHANGED``.
"""

from __future__ import annotations

import omni.ui as ui
import pytest
from ovui_data_adapters.common import LayerEvent, LayerEventType

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovui_widgets.layers import LayerModel, LocalMuteValueModel


@pytest.fixture
def model_with_root() -> "tuple[MockLayerStackAdapter, LayerModel]":
    """Fresh adapter + model pair seeded with the default root/session.

    Every test owns an independent model so flag-cache mutations don't
    leak across cases.
    """
    adapter = MockLayerStackAdapter(include_session=True)
    model = LayerModel(adapter)
    yield adapter, model
    model.destroy()


# ─── Construction / identity ──────────────────────────────────────────────────


class TestConstruction:
    def test_is_abstract_value_model(self, model_with_root) -> None:
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        assert isinstance(vm, LocalMuteValueModel)
        assert isinstance(vm, ui.AbstractValueModel)

    def test_holds_model_and_item_back_references(
        self, model_with_root
    ) -> None:
        # Phase F wraps ``set_value`` in a ``SetLayerMutenessCommand``
        # that navigates back through these references; pinning them
        # here guards against an accidental rename.
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        assert vm._model is model
        assert vm._item is model.root_item

    def test_cached_on_layer_item(self, model_with_root) -> None:
        # Logic F4 — the factory caches on ``LayerItem._local_mute_model``
        # so repeated reads reuse one instance across frame rebuilds.
        _, model = model_with_root
        first = model.get_item_value_model(model.root_item, 3)
        second = model.get_item_value_model(model.root_item, 3)
        assert first is second
        assert model.root_item._local_mute_model is first

    def test_distinct_instances_per_item(self, model_with_root) -> None:
        _, model = model_with_root
        root_vm = model.get_item_value_model(model.root_item, 3)
        session_vm = model.get_item_value_model(model.session_item, 3)
        assert root_vm is not session_vm
        assert root_vm._item is model.root_item
        assert session_vm._item is model.session_item

    def test_item_slot_starts_none(self, model_with_root) -> None:
        # Logic F4 — the slot is ``None`` until the column is first
        # rendered. An unrendered column never pays the cost of
        # constructing the model or subscribing to refreshes.
        _, model = model_with_root
        assert model.root_item._local_mute_model is None
        vm = model.get_item_value_model(model.root_item, 3)
        assert model.root_item._local_mute_model is vm


# ─── get_value_as_bool — mute state read ─────────────────────────────────────


class TestGetValue:
    def test_unmuted_layer_returns_false(self, model_with_root) -> None:
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        assert vm.get_value_as_bool() is False

    def test_muted_layer_returns_true(self, model_with_root) -> None:
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        assert vm.get_value_as_bool() is True

    def test_mute_toggles_both_directions(self, model_with_root) -> None:
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        assert vm.get_value_as_bool() is False
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        assert vm.get_value_as_bool() is True
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, False)
        assert vm.get_value_as_bool() is False

    def test_reads_are_independent_across_layers(self, model_with_root) -> None:
        # Muting one layer must not report mute on another — the read
        # path must route to the item's own identifier, not fall back
        # to a sibling or the root layer.
        adapter, model = model_with_root
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "./child.usda")
        child = model._items_by_id["./child.usda"]
        root_vm = model.get_item_value_model(model.root_item, 3)
        child_vm = model.get_item_value_model(child, 3)
        adapter.set_mute("./child.usda", True)
        assert child_vm.get_value_as_bool() is True
        assert root_vm.get_value_as_bool() is False


# ─── set_value — click-to-toggle write surface ───────────────────────────────


class TestSetValue:
    def test_set_true_mutes_layer(self, model_with_root) -> None:
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        assert adapter.is_muted(adapter.get_root_layer()) is False
        vm.set_value(True)
        assert adapter.is_muted(adapter.get_root_layer()) is True

    def test_set_false_unmutes_layer(self, model_with_root) -> None:
        adapter, model = model_with_root
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        vm = model.get_item_value_model(model.root_item, 3)
        vm.set_value(False)
        assert adapter.is_muted(adapter.get_root_layer()) is False

    def test_delegate_toggle_round_trip(self, model_with_root) -> None:
        # Reproduce the delegate's click handler — ``vm.set_value(not
        # vm.get_value_as_bool())`` — so a regression in either side
        # of the round-trip fails here first.
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        vm.set_value(not vm.get_value_as_bool())
        assert adapter.is_muted(adapter.get_root_layer()) is True
        vm.set_value(not vm.get_value_as_bool())
        assert adapter.is_muted(adapter.get_root_layer()) is False

    def test_set_value_idempotent_when_state_matches(
        self, model_with_root
    ) -> None:
        # Adapter's ``set_mute`` no-ops when the bit already matches —
        # the mock never fires a second ``MUTE_STATE_CHANGED`` and the
        # state stays put.
        adapter, model = model_with_root
        events: list = []
        adapter.subscribe_events(lambda e: events.append(e))
        vm = model.get_item_value_model(model.root_item, 3)
        vm.set_value(False)  # already unmuted
        mute_events = [
            e for e in events
            if e.event_type == LayerEventType.MUTE_STATE_CHANGED
        ]
        assert mute_events == []

    def test_set_value_coerces_argument_to_bool(self, model_with_root) -> None:
        # Truthy non-bool inputs (e.g. a ``1`` from legacy callers)
        # should still land as a mute. The model coerces before calling
        # the adapter so the downstream ``==`` compare in
        # ``MockLayerStackAdapter.set_mute`` lines up correctly.
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        vm.set_value(1)
        assert adapter.is_muted(adapter.get_root_layer()) is True

    def test_click_after_detach_is_noop(self, model_with_root) -> None:
        # Late click after :meth:`LayerModel.set_adapter` cleared the
        # reference — the stub write path guards so the paint pass
        # can't fault a torn-down window.
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        model._adapter = None
        vm.set_value(True)  # must not raise
        # Adapter's mute state is untouched — the write never ran.
        assert adapter.is_muted(adapter.get_root_layer()) is False


# ─── Refresh hook — _value_changed on MUTE_STATE_CHANGED ─────────────────────


class TestRefreshHook:
    def test_mute_event_fires_value_changed(self, model_with_root) -> None:
        # LayerModel routes ``MUTE_STATE_CHANGED`` → every cached
        # clone's ``_local_mute_model._value_changed()`` so ovui
        # repaints the cell.
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        hits: list = []
        vm.add_value_changed_fn(lambda m: hits.append(m))
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        assert hits and hits[-1] is vm

    def test_mute_event_skips_when_model_not_constructed(
        self, model_with_root
    ) -> None:
        # Logic F4 — if the column has never been rendered the mute
        # model is still ``None``. Firing the event must not fault and
        # must not coerce a new model into existence.
        adapter, model = model_with_root
        assert model.root_item._local_mute_model is None
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)  # must not raise
        assert model.root_item._local_mute_model is None

    def test_non_mute_events_do_not_fire_mute_refresh(
        self, model_with_root
    ) -> None:
        # Dirty / lock / file-permission events are handled by their own
        # Step 19/21 value models; the mute refresh must stay narrow to
        # the mute-state channel so we don't wake subscribers that
        # don't need refreshing.
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        hits: list = []
        vm.add_value_changed_fn(lambda m: hits.append(m))
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_read_only(ROOT_LAYER_IDENTIFIER, True)
        assert hits == []

    def test_mute_event_fans_across_clone_items(self, model_with_root) -> None:
        # Same layer under two parents — both cached clones must see
        # their mute model refresh so every rendered row repaints.
        adapter, model = model_with_root
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child_a")
        adapter.add_sublayer("child_a", "leaf")
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "leaf")
        clones = model._sublayers_cache.get("leaf", [])
        assert len(clones) >= 2, (
            f"expected two cached clones of 'leaf', got {len(clones)}"
        )
        vms = [model.get_item_value_model(c, 3) for c in clones]
        hits: list = []
        for vm in vms:
            vm.add_value_changed_fn(lambda m, h=hits: h.append(m))
        adapter.set_mute("leaf", True)
        assert len(hits) == len(vms)
        assert {id(m) for m in hits} == {id(vm) for vm in vms}

    def test_dirty_event_does_not_fire_mute_refresh(
        self, model_with_root
    ) -> None:
        # Symmetric guard for the Step-20 dispatcher extension: only
        # ``MUTE_STATE_CHANGED`` wakes the mute model. The unified
        # dispatch table (``_FLAG_EVENT_REFRESH``) must not cross-
        # fire refreshes across columns.
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        hits: list = []
        vm.add_value_changed_fn(lambda m: hits.append(m))
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert hits == []


# ─── Direct event dispatch — synthetic events ────────────────────────────────


class TestDirectConstruction:
    def test_event_dispatch_synthetic(self, model_with_root) -> None:
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 3)
        hits: list = []
        vm.add_value_changed_fn(lambda m: hits.append(m))
        model._on_layer_event(
            LayerEvent(
                event_type=LayerEventType.MUTE_STATE_CHANGED,
                identifiers=(ROOT_LAYER_IDENTIFIER,),
            )
        )
        assert hits and hits[-1] is vm
