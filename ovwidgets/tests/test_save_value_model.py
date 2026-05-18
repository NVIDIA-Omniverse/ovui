# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for :class:`ovwidgets.layers.models.save_model.SaveValueModel`
(LAYERS-PLAN Step 19).

Covers the plan's Verify bullets — dirty-and-saveable boolean read,
lazy per-item caching (Logic F4), click-to-save write surface, and
the :meth:`_value_changed` refresh hook fired from the owning
:class:`LayerModel` when the adapter emits ``DIRTY_STATE_CHANGED``.
"""

from __future__ import annotations

import omni.ui as ui
import pytest
from ovui_data_adapters.common import LayerEvent, LayerEventType

from ovwidgets.app.testing import MockLayerStackAdapter
from ovwidgets.common.testing.mock_layer_stack import ROOT_LAYER_IDENTIFIER
from ovwidgets.layers import LayerModel, SaveValueModel


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
        vm = model.get_item_value_model(model.root_item, 2)
        assert isinstance(vm, SaveValueModel)
        assert isinstance(vm, ui.AbstractValueModel)

    def test_holds_model_and_item_back_references(
        self, model_with_root
    ) -> None:
        # Step 21's targeted-refresh pass + the adapter-command layer
        # (Phase F) both navigate back through these references;
        # pinning them here guards against an accidental rename.
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 2)
        assert vm._model is model
        assert vm._item is model.root_item

    def test_cached_on_layer_item(self, model_with_root) -> None:
        # Logic F4 — the factory caches on ``LayerItem._save_model`` so
        # repeated reads reuse one instance across frame rebuilds.
        _, model = model_with_root
        first = model.get_item_value_model(model.root_item, 2)
        second = model.get_item_value_model(model.root_item, 2)
        assert first is second
        assert model.root_item._save_model is first

    def test_distinct_instances_per_item(self, model_with_root) -> None:
        _, model = model_with_root
        root_vm = model.get_item_value_model(model.root_item, 2)
        session_vm = model.get_item_value_model(model.session_item, 2)
        assert root_vm is not session_vm
        assert root_vm._item is model.root_item
        assert session_vm._item is model.session_item

    def test_item_save_model_slot_starts_none(self, model_with_root) -> None:
        # Logic F4 — the slot is ``None`` until the column is first
        # rendered. An unrendered column never pays the cost of
        # constructing the model or subscribing to refreshes.
        _, model = model_with_root
        assert model.root_item._save_model is None
        # First access materialises the model; the slot transitions
        # from ``None`` to the cached instance exactly once.
        vm = model.get_item_value_model(model.root_item, 2)
        assert model.root_item._save_model is vm


# ─── get_value_as_bool — dirty-and-saveable matrix ───────────────────────────


class TestGetValue:
    def test_clean_layer_returns_false(self, model_with_root) -> None:
        _, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 2)
        assert vm.get_value_as_bool() is False

    def test_dirty_layer_returns_true(self, model_with_root) -> None:
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 2)
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert vm.get_value_as_bool() is True

    def test_anonymous_layer_reports_saveable_when_dirty(
        self, model_with_root
    ) -> None:
        # Step 36 flipped the Step-19 contract: an anonymous dirty
        # layer DOES light the icon because the click routes into the
        # save-as file picker. The icon advertises an actionable
        # gesture — clicking asks the user for a file path and then
        # runs the write + parent-reference swap as a
        # :class:`SaveLayerAsCommand`. Clean anonymous layers still
        # clamp to ``False``.
        adapter, model = model_with_root
        session_id = model.session_item.identifier
        vm = model.get_item_value_model(model.session_item, 2)
        # Clean: no indicator.
        assert vm.get_value_as_bool() is False
        # Dirty anonymous: indicator lit — save-as is available.
        adapter._layers[session_id].dirty = True
        model.session_item.invalidate_flags()
        assert vm.get_value_as_bool() is True

    def test_missing_layer_never_reports_saveable(
        self, model_with_root
    ) -> None:
        # Mutate the record directly — ``set_missing`` fires
        # ``INFO_CHANGED`` which :class:`LayerModel` currently
        # classifies as structural (until Step 21's flag-only path),
        # and the resulting rebuild would orphan the captured model.
        adapter, model = model_with_root
        adapter._layers[ROOT_LAYER_IDENTIFIER].missing = True
        adapter._layers[ROOT_LAYER_IDENTIFIER].dirty = True
        model.root_item.invalidate_flags()
        vm = model.get_item_value_model(model.root_item, 2)
        assert vm.get_value_as_bool() is False

    def test_dirty_toggles_both_directions(self, model_with_root) -> None:
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 2)
        assert vm.get_value_as_bool() is False
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert vm.get_value_as_bool() is True
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, False)
        assert vm.get_value_as_bool() is False


# ─── set_value — click-to-save write surface ─────────────────────────────────


class TestSetValue:
    def test_click_triggers_adapter_save(self, model_with_root) -> None:
        # The stub write path forwards directly to the adapter; Phase
        # F wraps this with a ``SaveLayerCommand`` for undo support.
        adapter, model = model_with_root
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert adapter.is_dirty(adapter.get_root_layer()) is True
        vm = model.get_item_value_model(model.root_item, 2)
        vm.set_value(True)
        # ``MockLayerStackAdapter.save_layer`` clears the dirty bit on
        # success — the round-trip proves the call actually landed.
        assert adapter.is_dirty(adapter.get_root_layer()) is False

    def test_click_on_clean_layer_is_noop(self, model_with_root) -> None:
        # Clean layers never show the icon, but a programmatic call
        # must also be safe — no spurious save events downstream.
        adapter, model = model_with_root
        events: list = []
        adapter.subscribe_events(lambda e: events.append(e))
        vm = model.get_item_value_model(model.root_item, 2)
        vm.set_value(True)
        assert events == []

    def test_click_on_anonymous_layer_is_noop_without_app(
        self, model_with_root
    ) -> None:
        # Step 36 — anonymous click routes through
        # :meth:`_request_save_as`, which opens a file-picker dialog.
        # In this headless / ``app=None`` fixture the model's save-as
        # path short-circuits before opening the dialog (no undo
        # manager to push through), so no ``save_layer`` /
        # ``save_layer_as`` fires on the adapter and the event bus
        # stays silent. With a real app attached the click opens the
        # picker and, on Save, pushes a :class:`SaveLayerAsCommand` —
        # covered by ``tests/test_layers_step36_save_as.py``.
        adapter, model = model_with_root
        session_id = model.session_item.identifier
        adapter._layers[session_id].dirty = True
        model.session_item.invalidate_flags()
        events: list = []
        adapter.subscribe_events(lambda e: events.append(e))
        vm = model.get_item_value_model(model.session_item, 2)
        vm.set_value(True)
        # No ``DIRTY_STATE_CHANGED`` — no save actually ran on the
        # adapter (app-less save-as short-circuits before any write).
        assert not any(
            e.event_type == LayerEventType.DIRTY_STATE_CHANGED for e in events
        )

    def test_click_on_missing_layer_is_noop(self, model_with_root) -> None:
        adapter, model = model_with_root
        adapter._layers[ROOT_LAYER_IDENTIFIER].missing = True
        adapter._layers[ROOT_LAYER_IDENTIFIER].dirty = True
        model.root_item.invalidate_flags()
        events: list = []
        adapter.subscribe_events(lambda e: events.append(e))
        vm = model.get_item_value_model(model.root_item, 2)
        vm.set_value(True)
        assert not any(
            e.event_type == LayerEventType.DIRTY_STATE_CHANGED for e in events
        )

    def test_click_ignores_bool_argument_value(self, model_with_root) -> None:
        # The save icon is a "do it" gesture, not a toggle — the bool
        # payload is discarded. Passing ``False`` should still save.
        adapter, model = model_with_root
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        vm = model.get_item_value_model(model.root_item, 2)
        vm.set_value(False)
        assert adapter.is_dirty(adapter.get_root_layer()) is False

    def test_click_after_detach_is_noop(self, model_with_root) -> None:
        # Late click after :meth:`LayerModel.set_adapter` cleared the
        # reference — the stub write path guards so the paint pass
        # can't fault a torn-down window.
        adapter, model = model_with_root
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        vm = model.get_item_value_model(model.root_item, 2)
        model._adapter = None
        vm.set_value(True)  # must not raise
        # Adapter's dirty state is untouched — the save never ran.
        assert adapter.is_dirty(adapter.get_root_layer()) is True


# ─── Refresh hook — _value_changed on DIRTY_STATE_CHANGED ─────────────────────


class TestRefreshHook:
    def test_dirty_event_fires_value_changed(self, model_with_root) -> None:
        # LayerModel routes ``DIRTY_STATE_CHANGED`` → every cached
        # clone's ``_save_model._value_changed()`` so ovui repaints
        # the cell. Observe via :meth:`add_value_changed_fn` (the hook
        # ``ui.AbstractValueModel`` exposes to subscribers).
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 2)
        hits: list = []
        vm.add_value_changed_fn(lambda m: hits.append(m))
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)
        assert hits and hits[-1] is vm

    def test_dirty_event_skips_when_save_model_not_constructed(
        self, model_with_root
    ) -> None:
        # Logic F4 — if the column has never been rendered the save
        # model is still ``None``. Firing the event must not fault and
        # must not coerce a new model into existence.
        adapter, model = model_with_root
        assert model.root_item._save_model is None
        adapter.set_dirty(ROOT_LAYER_IDENTIFIER, True)  # must not raise
        assert model.root_item._save_model is None

    def test_mute_lock_file_permission_events_fire_save_refresh(
        self, model_with_root
    ) -> None:
        # Step 32: the save column's "can this layer actually save?"
        # answer depends on writability, which mute / lock / read-
        # only toggles all alter. The batched flush therefore pokes
        # the save model on each of those events so the dirty icon's
        # click-to-save gate re-evaluates without waiting for the
        # row to rebuild.
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 2)
        hits: list = []
        vm.add_value_changed_fn(lambda m: hits.append(m))
        adapter.set_mute(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_lock(ROOT_LAYER_IDENTIFIER, True)
        adapter.set_read_only(ROOT_LAYER_IDENTIFIER, True)
        assert len(hits) == 3
        assert all(m is vm for m in hits)

    def test_dirty_event_fans_across_clone_items(
        self, model_with_root
    ) -> None:
        # Same layer under two parents — both cached clones must see
        # their save model refresh so every rendered row repaints.
        adapter, model = model_with_root
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "child_a")
        adapter.add_sublayer("child_a", "leaf")
        # Insert leaf under the root a second time so it has two
        # cached clones. The cycle guard allows this since the parent
        # chains differ (root → child_a → leaf and root → leaf).
        adapter.add_sublayer(ROOT_LAYER_IDENTIFIER, "leaf")
        clones = model._sublayers_cache.get("leaf", [])
        assert len(clones) >= 2, (
            f"expected two cached clones of 'leaf', got {len(clones)}"
        )
        vms = [model.get_item_value_model(c, 2) for c in clones]
        hits: list = []
        for vm in vms:
            vm.add_value_changed_fn(lambda m, h=hits: h.append(m))
        adapter.set_dirty("leaf", True)
        # Every clone's model fired exactly once.
        assert len(hits) == len(vms)
        assert {id(m) for m in hits} == {id(vm) for vm in vms}


# ─── Direct construction — exercise the raw value-model surface ──────────────


class TestDirectConstruction:
    def test_event_dispatch_synthetic(self, model_with_root) -> None:
        # Build a fake event and drive :meth:`LayerModel._on_layer_event`
        # directly so the targeted-refresh path is covered without
        # relying on adapter mutators (Step 21 will exercise this via
        # the real batching pipeline).
        adapter, model = model_with_root
        vm = model.get_item_value_model(model.root_item, 2)
        hits: list = []
        vm.add_value_changed_fn(lambda m: hits.append(m))
        model._on_layer_event(
            LayerEvent(
                event_type=LayerEventType.DIRTY_STATE_CHANGED,
                identifiers=(ROOT_LAYER_IDENTIFIER,),
            )
        )
        assert hits and hits[-1] is vm
