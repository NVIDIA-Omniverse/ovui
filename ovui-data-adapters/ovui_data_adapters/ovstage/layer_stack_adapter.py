# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Unavailable layer-stack surface for the OVStage-only provider."""

from __future__ import annotations

from typing import Any, Callable, List, Optional

from ovui_data_adapters.common import (
    AdapterCapability,
    LayerEvent,
    LayerHandle,
    LayerSnapshot,
    LayerStackCapabilities,
    LayerStackAdapter,
    PrimSpecDescriptor,
    SubscriptionProtocol,
)

from ovui_data_adapters.ovstage._errors import raise_not_ready


class _NoopSubscription:
    """Subscription handle for the intentionally inert layer surface."""

    def cancel(self) -> None:
        return None


_OVSTAGE_LAYER_CAPABILITIES = LayerStackCapabilities(
    layer_stack=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose layer-stack enumeration; "
        "select the OpenUSD data adapter for layer workflows"
    ),
    edit_target_read=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose edit-target state; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    edit_target_write=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose edit-target mutation; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    save_layer=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose layer save; select the "
        "OpenUSD data adapter for layer persistence"
    ),
    save_layer_as=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose layer save-as or serialization; "
        "select the OpenUSD data adapter for layer persistence"
    ),
    create_sublayer=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose sublayer creation; select the "
        "OpenUSD data adapter for layer workflows"
    ),
    insert_sublayer=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose sublayer insertion; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    remove_sublayer=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose sublayer removal; select the "
        "OpenUSD data adapter for layer workflows"
    ),
    reload_layer=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose layer reload; select the "
        "OpenUSD data adapter for layer workflows"
    ),
    mute_layer=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose layer muting; select the "
        "OpenUSD data adapter for layer workflows"
    ),
    lock_layer=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose layer lock state or mutation; "
        "select the OpenUSD data adapter for layer workflows"
    ),
    move_sublayer=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose sublayer reordering; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    replace_sublayer=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose sublayer replacement; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    prim_spec_read=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose prim-spec or source-layer "
        "inspection; select the OpenUSD data adapter for composition inspection"
    ),
    prim_spec_edit=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose prim-spec mutation; select "
        "the OpenUSD data adapter for composition authoring"
    ),
    layer_snapshot=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose layer snapshots; select the "
        "OpenUSD data adapter for layer workflows"
    ),
    layer_restore=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose layer restoration; select "
        "the OpenUSD data adapter for layer workflows"
    ),
    transfer_layer_content=AdapterCapability.unsupported(
        "the supplied OVStage 0.1 API does not expose layer-content transfer; select "
        "the OpenUSD data adapter for layer workflows"
    ),
)


class OvstageLayerStackAdapter(LayerStackAdapter):
    """Fail-closed layer surface for APIs absent from OVStage 0.1."""

    def __init__(self, scene: Any | None = None, undo_manager: Any | None = None) -> None:
        self._scene = scene
        self._undo_manager = undo_manager

    def attach_stage(self, call_later: Optional[Callable[[float, Callable], Any]] = None) -> None:
        return None

    def detach_stage(self) -> None:
        return None

    def get_capabilities(self) -> LayerStackCapabilities:
        return _OVSTAGE_LAYER_CAPABILITIES

    def get_root_layer(self) -> LayerHandle:
        raise_not_ready("layer root")

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
        return []

    def get_display_name(self, layer: LayerHandle) -> str:
        raise_not_ready("layer display data")

    def get_layer_owner(self, layer: LayerHandle) -> str:
        return ""

    def is_anonymous(self, layer: LayerHandle) -> bool:
        return False

    def is_dirty(self, layer: LayerHandle) -> bool:
        return False

    def is_muted(self, layer: LayerHandle) -> bool:
        return False

    def is_locked(self, layer: LayerHandle) -> bool:
        return True

    def is_read_only_on_disk(self, layer: LayerHandle) -> bool:
        return True

    def is_missing(self, layer: LayerHandle) -> bool:
        return True

    def get_edit_target_identifier(self) -> str:
        return ""

    def subscribe_events(
        self,
        callback: Callable[[LayerEvent], None],
    ) -> SubscriptionProtocol:
        return _NoopSubscription()

    def set_edit_target(self, identifier: str) -> None:
        raise_not_ready("layer edit target")

    def set_mute(self, identifier: str, muted: bool) -> None:
        raise_not_ready("layer mute")

    def set_lock(self, identifier: str, locked: bool) -> None:
        raise_not_ready("layer lock")

    def create_sublayer(
        self,
        parent_id: str,
        position: int,
        new_layer_path: str,
        transfer_root_content: bool = False,
    ) -> str:
        raise_not_ready("layer creation")

    def insert_sublayer(
        self,
        parent_id: str,
        position: int,
        sublayer_path: str,
    ) -> None:
        raise_not_ready("layer insertion")

    def remove_sublayer(self, parent_id: str, position: int) -> str:
        raise_not_ready("layer removal")

    def move_sublayer(
        self,
        from_parent_id: str,
        from_position: int,
        to_parent_id: str,
        to_position: int,
        remove_source: bool = True,
    ) -> None:
        raise_not_ready("layer move")

    def replace_sublayer(
        self,
        parent_id: str,
        position: int,
        new_identifier: str,
    ) -> str:
        raise_not_ready("layer replacement")

    def export_prim_spec(self, layer_id: str, path: str) -> str:
        raise_not_ready("layer prim-spec export")

    def remove_prim_spec(self, layer_id: str, path: str) -> None:
        raise_not_ready("layer prim-spec removal")

    def import_prim_spec(self, layer_id: str, path: str, usda: str) -> None:
        raise_not_ready("layer prim-spec import")

    def get_prim_specs(
        self, layer_identifier: str, parent_path: str = "/"
    ) -> List[PrimSpecDescriptor]:
        return []

    def has_prim_spec(self, layer_identifier: str, spec_path: str) -> bool:
        return False

    def snapshot_layer(self, identifier: str) -> LayerSnapshot:
        raise_not_ready("layer snapshot")

    def restore_layer_from_snapshot(self, snapshot: LayerSnapshot) -> str:
        raise_not_ready("layer snapshot restore")

    def transfer_layer_content(
        self, src_identifier: str, dst_identifier: str
    ) -> None:
        raise_not_ready("layer content transfer")

    def save_layer(self, identifier: str) -> bool:
        return False

    def save_layer_as(
        self,
        identifier: str,
        new_path: str,
        replace_in_parent: bool,
    ) -> Optional[str]:
        return None

    def reload_layer(self, identifier: str) -> bool:
        return False

    def persist_layer_state_before_save(self, stage: Any) -> None:
        raise_not_ready("layer state persistence")
