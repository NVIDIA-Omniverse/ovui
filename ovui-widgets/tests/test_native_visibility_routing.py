# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Native OVStage visibility events route to per-item invalidation.

The Stage Browser hierarchy model must classify every proven native
visibility publication as visibility-only — regardless of provenance
(adapter toggle ``ovstage:visibility`` or Property Inspector
``property:set``) — so it never falls back to a structural rebuild for a
pure visibility edit. The canonical classification travels in the
event's adapter-owned ``visibility_delta``; the provenance ``source``
stays untouched.
"""

from __future__ import annotations

from types import SimpleNamespace

from ovui_data_adapters.common import ChangeEvent, ChangeEventType
from ovui_data_adapters.ovstage.change_stream import OvstageChangeStream

from ovui_widgets.stage.widget.hierarchy_model import HierarchyModel


class _Subscription:
    def cancel(self) -> None:
        pass


class _Adapter:
    """Minimal StageAdapter surface for HierarchyModel construction."""

    def get_root(self):
        return object()

    def subscribe_changes(self, _callback):
        return _Subscription()


def _model() -> HierarchyModel:
    return HierarchyModel(_Adapter())


def _native_event(provenance: str | None) -> ChangeEvent:
    """Capture a genuine native-stream visibility publication."""
    stream = OvstageChangeStream(SimpleNamespace(_stage=None, is_open=True))
    events: list = []
    stream.subscribe_stage(events.append)
    stream.publish_visibility_change(["/World/Parent/MeshA"], source=provenance)
    assert len(events) == 1
    return events[0]


def test_adapter_toggle_event_is_visibility_only() -> None:
    event = _native_event(None)
    assert event.source == "ovstage:visibility"
    assert _model()._is_visibility_only_event(event) is True


def test_property_inspector_event_is_visibility_only() -> None:
    # The regression: property provenance must not displace the canonical
    # visibility classification into the structural-rebuild path.
    event = _native_event("property:set")
    assert event.source == "property:set"
    assert _model()._is_visibility_only_event(event) is True


def test_native_attribute_publication_stays_structural() -> None:
    # A lookalike property edit (e.g. a custom token named "visibility"
    # on a non-Imageable prim) publishes through the ATTRIBUTE channel:
    # no proven delta, so the model keeps the structural rebuild path.
    stream = OvstageChangeStream(SimpleNamespace(_stage=None, is_open=True))
    events: list = []
    stream.subscribe_stage(events.append)
    stream.publish_attribute_change(
        ["/World/Lookalike"], source="property:set"
    )
    assert len(events) == 1
    assert events[0].visibility_delta is None
    assert _model()._is_visibility_only_event(events[0]) is False


def test_deltaless_property_provenance_event_stays_structural() -> None:
    # Control: a bare INFO event with property provenance and NO proven
    # delta keeps the conservative structural classification.
    event = ChangeEvent(
        changed_paths=("/World/Parent/MeshA",),
        resynced_paths=(),
        event_type=ChangeEventType.INFO_CHANGE,
        source="property:set",
    )
    assert _model()._is_visibility_only_event(event) is False
