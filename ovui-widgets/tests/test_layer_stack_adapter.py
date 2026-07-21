# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Conformance tests for the LayerStackAdapter ABC (LAYERS-PLAN Step 1)."""

from __future__ import annotations

import weakref
from dataclasses import FrozenInstanceError
from typing import Callable, List, Optional

import pytest
from ovui_data_adapters.common import (
    LayerEvent,
    LayerEventType,
    LayerHandle,
    LayerStackAdapter,
    PrimSpecDescriptor,
    PrimSpecifier,
)

from ovui_widgets.common.settings import Subscription

# ─── Test helpers ─────────────────────────────────────────────────────────────


_READ_ONLY_ABSTRACT_METHODS = (
    "get_root_layer",
    "get_session_layer",
    "get_sublayer_identifiers",
    "find_layer",
    "get_layer_stack_identifiers",
    "get_display_name",
    "get_layer_owner",
    "is_anonymous",
    "is_dirty",
    "is_muted",
    "is_locked",
    "is_read_only_on_disk",
    "is_missing",
    "get_edit_target_identifier",
    "subscribe_events",
)


_MUTATION_ABSTRACT_METHODS = (
    "set_edit_target",
    "set_mute",
    "set_lock",
    "create_sublayer",
    "insert_sublayer",
    "remove_sublayer",
    "move_sublayer",
    "save_layer",
    "save_layer_as",
    "reload_layer",
)


_ALL_ABSTRACT_METHODS = _READ_ONLY_ABSTRACT_METHODS + _MUTATION_ABSTRACT_METHODS


def _make_full_adapter_class(
    *,
    is_locked: bool = False,
    is_muted: bool = False,
    is_read_only: bool = False,
):
    """Build a throwaway concrete adapter for behavioural tests."""

    class _FullAdapter(LayerStackAdapter):
        def __init__(self) -> None:
            self._subscribers: List[Callable[[LayerEvent], None]] = []

        def get_root_layer(self) -> LayerHandle:
            return LayerHandle("root.usda")

        def get_session_layer(self) -> Optional[LayerHandle]:
            return None

        def get_sublayer_identifiers(self, parent: LayerHandle) -> List[str]:
            return []

        def find_layer(self, identifier: str) -> Optional[LayerHandle]:
            return None

        def get_layer_stack_identifiers(
            self,
            include_session: bool = False,
            include_anonymous: bool = True,
        ) -> List[str]:
            return ["root.usda"]

        def get_display_name(self, layer: LayerHandle) -> str:
            return layer.identifier

        def get_layer_owner(self, layer: LayerHandle) -> str:
            return ""

        def is_anonymous(self, layer: LayerHandle) -> bool:
            return False

        def is_dirty(self, layer: LayerHandle) -> bool:
            return False

        def is_muted(self, layer: LayerHandle) -> bool:
            return is_muted

        def is_locked(self, layer: LayerHandle) -> bool:
            return is_locked

        def is_read_only_on_disk(self, layer: LayerHandle) -> bool:
            return is_read_only

        def is_missing(self, layer: LayerHandle) -> bool:
            return False

        def get_edit_target_identifier(self) -> str:
            return "root.usda"

        def subscribe_events(
            self, callback: Callable[[LayerEvent], None]
        ) -> Subscription:
            self._subscribers.append(callback)
            return Subscription(weakref.ref(self), "events", callback)

        def _remove_subscriber(self, key: str, callback: Callable) -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        # ── Mutation stubs (Step 6) — inert; behavioural coverage lives
        # in the mock / USD adapter test files.
        def set_edit_target(self, identifier: str) -> None:
            return None

        def set_mute(self, identifier: str, muted: bool) -> None:
            return None

        def set_lock(self, identifier: str, locked: bool) -> None:
            return None

        def create_sublayer(
            self,
            parent_id: str,
            position: int,
            new_layer_path: str,
            transfer_root_content: bool = False,
        ) -> str:
            return new_layer_path or "anon:stub"

        def insert_sublayer(
            self, parent_id: str, position: int, sublayer_path: str
        ) -> None:
            return None

        def remove_sublayer(self, parent_id: str, position: int) -> str:
            return ""

        def move_sublayer(
            self,
            from_parent_id: str,
            from_position: int,
            to_parent_id: str,
            to_position: int,
            remove_source: bool = True,
        ) -> None:
            return None

        def replace_sublayer(
            self, parent_id: str, position: int, new_identifier: str
        ) -> str:
            return ""

        def export_prim_spec(self, layer_id: str, path: str) -> str:
            return ""

        def remove_prim_spec(self, layer_id: str, path: str) -> None:
            return None

        def import_prim_spec(
            self, layer_id: str, path: str, usda: str
        ) -> None:
            return None

        def get_prim_specs(
            self, layer_identifier: str, parent_path: str = "/"
        ) -> List[PrimSpecDescriptor]:
            return []

        def has_prim_spec(
            self, layer_identifier: str, spec_path: str
        ) -> bool:
            return False

        def save_layer(self, identifier: str) -> bool:
            return True

        def save_layer_as(
            self, identifier: str, new_path: str, replace_in_parent: bool
        ) -> Optional[str]:
            return new_path or None

        def reload_layer(self, identifier: str) -> bool:
            return True

        # ── Step 42 merge / flatten support — inert stubs. Concrete
        # behavioural coverage lives on the mock + USD adapter tests.
        def snapshot_layer(self, identifier: str):
            from ovui_data_adapters.common import LayerSnapshot

            return LayerSnapshot(
                identifier=identifier,
                parent_identifier=None,
                position_in_parent=-1,
                was_edit_target=False,
                anonymous=False,
                content="",
            )

        def restore_layer_from_snapshot(self, snapshot) -> str:
            return snapshot.identifier

        def transfer_layer_content(
            self, src_identifier: str, dst_identifier: str
        ) -> None:
            return None

    return _FullAdapter


# ─── LayerEventType enum ──────────────────────────────────────────────────────


class TestLayerEventType:
    def test_has_all_eight_values(self) -> None:
        expected = {
            "EDIT_TARGET_CHANGED",
            "SUBLAYERS_CHANGED",
            "DIRTY_STATE_CHANGED",
            "MUTE_STATE_CHANGED",
            "LOCK_STATE_CHANGED",
            "INFO_CHANGED",
            "FILE_PERMISSION_CHANGED",
            "OUTDATE_STATE_CHANGED",
        }
        assert {m.name for m in LayerEventType} == expected

    def test_values_are_distinct(self) -> None:
        values = [m.value for m in LayerEventType]
        assert len(values) == len(set(values))

    def test_enum_members_are_hashable(self) -> None:
        seen = {member for member in LayerEventType}
        assert len(seen) == 8


# ─── LayerEvent dataclass ─────────────────────────────────────────────────────


class TestLayerEvent:
    def test_default_identifiers_is_empty_tuple(self) -> None:
        ev = LayerEvent(event_type=LayerEventType.EDIT_TARGET_CHANGED)
        assert ev.identifiers == ()
        assert ev.info_fields == {}

    def test_identifiers_field_is_tuple_and_hashable(self) -> None:
        ev = LayerEvent(
            event_type=LayerEventType.DIRTY_STATE_CHANGED,
            identifiers=("layer_a", "layer_b"),
        )
        assert isinstance(ev.identifiers, tuple)
        # The identifiers field alone must be hashable — used for log safety
        # and for set/dict aggregation in the UI. The full LayerEvent is not
        # hashable because info_fields is a Dict by design.
        assert isinstance(hash(ev.identifiers), int)

    def test_equality_by_value(self) -> None:
        a = LayerEvent(
            event_type=LayerEventType.SUBLAYERS_CHANGED,
            identifiers=("l1",),
        )
        b = LayerEvent(
            event_type=LayerEventType.SUBLAYERS_CHANGED,
            identifiers=("l1",),
        )
        assert a == b

    def test_inequality_by_event_type(self) -> None:
        a = LayerEvent(event_type=LayerEventType.DIRTY_STATE_CHANGED)
        b = LayerEvent(event_type=LayerEventType.LOCK_STATE_CHANGED)
        assert a != b

    def test_inequality_by_identifiers(self) -> None:
        a = LayerEvent(
            event_type=LayerEventType.SUBLAYERS_CHANGED, identifiers=("l1",)
        )
        b = LayerEvent(
            event_type=LayerEventType.SUBLAYERS_CHANGED, identifiers=("l2",)
        )
        assert a != b

    def test_is_frozen(self) -> None:
        ev = LayerEvent(event_type=LayerEventType.INFO_CHANGED)
        with pytest.raises(FrozenInstanceError):
            ev.event_type = LayerEventType.DIRTY_STATE_CHANGED  # type: ignore[misc]

    def test_info_fields_default_is_independent_per_instance(self) -> None:
        a = LayerEvent(event_type=LayerEventType.INFO_CHANGED)
        b = LayerEvent(event_type=LayerEventType.INFO_CHANGED)
        assert a.info_fields is not b.info_fields

    def test_info_fields_preserves_tuple_values(self) -> None:
        ev = LayerEvent(
            event_type=LayerEventType.INFO_CHANGED,
            identifiers=("root.usda",),
            info_fields={"root.usda": ("upAxis", "metersPerUnit")},
        )
        assert ev.info_fields["root.usda"] == ("upAxis", "metersPerUnit")

    def test_identifiers_tuple_usable_as_set_member(self) -> None:
        # Deduplicating affected layers across a batch of events relies on
        # the identifiers field being hashable.
        batch = [
            LayerEvent(event_type=LayerEventType.DIRTY_STATE_CHANGED, identifiers=("a",)),
            LayerEvent(event_type=LayerEventType.DIRTY_STATE_CHANGED, identifiers=("a",)),
            LayerEvent(event_type=LayerEventType.DIRTY_STATE_CHANGED, identifiers=("b",)),
        ]
        seen = {ev.identifiers for ev in batch}
        assert seen == {("a",), ("b",)}


# ─── LayerHandle dataclass ────────────────────────────────────────────────────


class TestLayerHandle:
    def test_exposes_identifier(self) -> None:
        h = LayerHandle("root.usda")
        assert h.identifier == "root.usda"

    def test_is_frozen(self) -> None:
        h = LayerHandle("root.usda")
        with pytest.raises(FrozenInstanceError):
            h.identifier = "other.usda"  # type: ignore[misc]

    def test_equality_by_identifier(self) -> None:
        a = LayerHandle("layer.usda")
        b = LayerHandle("layer.usda")
        assert a == b
        assert hash(a) == hash(b)

    def test_inequality_by_identifier(self) -> None:
        assert LayerHandle("a.usda") != LayerHandle("b.usda")

    def test_usable_as_dict_key(self) -> None:
        mapping = {LayerHandle("a.usda"): 1, LayerHandle("b.usda"): 2}
        assert mapping[LayerHandle("a.usda")] == 1
        assert mapping[LayerHandle("b.usda")] == 2

    def test_usable_as_set_member(self) -> None:
        handles = {LayerHandle("a"), LayerHandle("a"), LayerHandle("b")}
        assert len(handles) == 2


# ─── PrimSpecDescriptor / PrimSpecifier ───────────────────────────────────────


class TestPrimSpecTypes:
    def test_prim_specifier_has_three_members(self) -> None:
        assert {m.name for m in PrimSpecifier} == {"DEF", "OVER", "CLASS"}

    def test_prim_spec_descriptor_is_frozen(self) -> None:
        d = PrimSpecDescriptor(
            path="/World/Cube",
            type_name="Cube",
            specifier=PrimSpecifier.DEF,
            has_reference=False,
            has_payload=False,
            is_instanceable=False,
        )
        with pytest.raises(FrozenInstanceError):
            d.path = "/Other"  # type: ignore[misc]

    def test_prim_spec_descriptor_hashable(self) -> None:
        d = PrimSpecDescriptor(
            path="/World/Cube",
            type_name="Cube",
            specifier=PrimSpecifier.OVER,
            has_reference=True,
            has_payload=False,
            is_instanceable=True,
        )
        assert isinstance(hash(d), int)


# ─── ABC conformance ──────────────────────────────────────────────────────────


class TestAbstractContract:
    def test_cannot_instantiate_bare_abc(self) -> None:
        with pytest.raises(TypeError):
            LayerStackAdapter()  # type: ignore[abstract]

    @pytest.mark.parametrize("omitted_method", _ALL_ABSTRACT_METHODS)
    def test_missing_method_prevents_instantiation(self, omitted_method: str) -> None:
        full_cls = _make_full_adapter_class()
        namespace = {
            name: getattr(full_cls, name)
            for name in _ALL_ABSTRACT_METHODS
            if name != omitted_method
        }
        partial_cls = type("PartialAdapter", (LayerStackAdapter,), namespace)
        with pytest.raises(TypeError):
            partial_cls()

    def test_full_subclass_can_be_instantiated(self) -> None:
        adapter = _make_full_adapter_class()()
        assert isinstance(adapter, LayerStackAdapter)

    def test_every_listed_abstract_is_marked_abstract(self) -> None:
        abstracts = LayerStackAdapter.__abstractmethods__
        for name in _ALL_ABSTRACT_METHODS:
            assert name in abstracts, f"{name} is not marked abstract"

    def test_mutation_methods_are_abstract(self) -> None:
        # Step 6 added these; the parametric test above would also catch
        # a missing @abstractmethod decorator, but an explicit per-name
        # assertion is easier to read in regression output.
        abstracts = LayerStackAdapter.__abstractmethods__
        for name in _MUTATION_ABSTRACT_METHODS:
            assert name in abstracts, f"{name} must be @abstractmethod"

    def test_is_writable_is_concrete(self) -> None:
        assert "is_writable" not in LayerStackAdapter.__abstractmethods__


# ─── is_writable default logic ────────────────────────────────────────────────


class TestIsWritableDefault:
    def _handle(self) -> LayerHandle:
        return LayerHandle("root.usda")

    def test_writable_when_none_of_the_flags_are_set(self) -> None:
        adapter = _make_full_adapter_class()()
        assert adapter.is_writable(self._handle()) is True

    @pytest.mark.parametrize(
        "locked,muted,read_only",
        [
            (True, False, False),
            (False, True, False),
            (False, False, True),
            (True, True, False),
            (True, False, True),
            (False, True, True),
            (True, True, True),
        ],
    )
    def test_not_writable_when_any_flag_set(
        self, locked: bool, muted: bool, read_only: bool
    ) -> None:
        cls = _make_full_adapter_class(
            is_locked=locked, is_muted=muted, is_read_only=read_only
        )
        assert cls().is_writable(self._handle()) is False

    def test_subclass_can_override_is_writable(self) -> None:
        cls = _make_full_adapter_class(is_locked=True)

        class Override(cls):  # type: ignore[misc,valid-type]
            def is_writable(self, layer: LayerHandle) -> bool:
                return True

        assert Override().is_writable(self._handle()) is True


# ─── subscribe_events integrates with ovui_widgets.common.settings.Subscription ────────────


class TestSubscribeEvents:
    def test_returns_subscription_instance(self) -> None:
        adapter = _make_full_adapter_class()()
        sub = adapter.subscribe_events(lambda ev: None)
        assert isinstance(sub, Subscription)

    def test_cancel_removes_callback(self) -> None:
        adapter = _make_full_adapter_class()()
        received: List[LayerEvent] = []
        sub = adapter.subscribe_events(received.append)
        assert len(adapter._subscribers) == 1
        sub.cancel()
        assert adapter._subscribers == []

    def test_cancel_is_idempotent(self) -> None:
        adapter = _make_full_adapter_class()()
        sub = adapter.subscribe_events(lambda ev: None)
        sub.cancel()
        sub.cancel()  # must not raise
        assert adapter._subscribers == []
