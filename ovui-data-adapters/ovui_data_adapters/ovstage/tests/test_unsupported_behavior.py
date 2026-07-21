# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Fail-closed behavior for exact-wheel unsupported OVStage actions."""

from __future__ import annotations

import sys
from unittest.mock import Mock

import pytest

from ovui_data_adapters.common import (
    LayerHandle,
    LayerSnapshot,
)
from ovui_data_adapters.ovstage.layer_stack_adapter import OvstageLayerStackAdapter
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.provider import OvstageProviderSession


_CREATE_STAGE_REASON = (
    "the supplied OVStage 0.1 API can construct an in-memory stage but does "
    "not expose durable new-document creation; select the OpenUSD data adapter "
    "for durable document creation"
)

_EXPORT_STAGE_REASON = (
    "the supplied OVStage 0.1 API does not expose stage export or serialization; "
    "select the OpenUSD data adapter for export"
)

_CLEAR_VALUE_REASON = (
    "the supplied OVStage 0.1 API does not expose the authored-opinion and "
    "default-value resolution required to clear a property value; select the "
    "OpenUSD data adapter to clear authored opinions"
)


def _loaded_modules(prefix: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name in sys.modules
            if name == prefix or name.startswith(f"{prefix}.")
        )
    )


class _ExplodingScene:
    def __init__(self) -> None:
        self.accesses: list[str] = []

    def __getattr__(self, name: str):
        self.accesses.append(name)
        raise AssertionError(f"unsupported layer behavior accessed scene.{name}")


_SNAPSHOT = LayerSnapshot(
    identifier="child.usda",
    parent_identifier="root.usda",
    position_in_parent=0,
    was_edit_target=False,
    anonymous=False,
    content="#usda 1.0",
)


def test_unsupported_provider_file_actions_fail_without_side_effects(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = OvstageProviderSession(runtime=object())
    prior_scene = object()
    session._current_scene = prior_scene
    create_path = tmp_path / "new.usda"
    export_path = tmp_path / "export.usda"
    open_stage = Mock(side_effect=AssertionError("unsupported create opened a stage"))
    require_scene = Mock(
        side_effect=AssertionError("unsupported export inspected scene")
    )
    monkeypatch.setattr(session, "open_stage", open_stage)
    monkeypatch.setattr(session, "_require_authoring_scene", require_scene)
    pxr_before = _loaded_modules("pxr")
    openusd_before = _loaded_modules("ovui_data_adapters.openusd")

    with pytest.raises(NotImplementedError, match=_CREATE_STAGE_REASON):
        session.create_stage(str(create_path))
    with pytest.raises(NotImplementedError, match=_EXPORT_STAGE_REASON):
        session.export_stage(object(), str(export_path))

    assert session.current_scene is prior_scene
    assert not create_path.exists()
    assert not export_path.exists()
    open_stage.assert_not_called()
    require_scene.assert_not_called()
    assert _loaded_modules("pxr") == pxr_before
    assert _loaded_modules("ovui_data_adapters.openusd") == openusd_before
    capabilities = session.get_capabilities().stage
    assert capabilities.create_stage.is_unsupported
    assert capabilities.export_stage.is_unsupported
    assert capabilities.create_prims.is_supported
    assert capabilities.delete_prims.is_supported


def test_unsupported_layer_surface_has_no_hybrid_delegate(
    tmp_path,
) -> None:
    scene = _ExplodingScene()
    pxr_before = _loaded_modules("pxr")
    openusd_before = _loaded_modules("ovui_data_adapters.openusd")
    assert not hasattr(OvstageLayerStackAdapter, "_make_usd_adapter")
    adapter = OvstageLayerStackAdapter(scene=scene)

    assert adapter.get_capabilities().supported_actions() == ()
    handle = LayerHandle("root.usda")
    adapter.attach_stage()
    adapter.detach_stage()
    assert adapter.get_session_layer() is None
    assert adapter.get_sublayer_identifiers(handle) == []
    assert adapter.find_layer(handle.identifier) is None
    assert adapter.get_layer_stack_identifiers() == []
    assert adapter.get_layer_owner(handle) == ""
    assert adapter.is_anonymous(handle) is False
    assert adapter.is_dirty(handle) is False
    assert adapter.is_muted(handle) is False
    assert adapter.is_locked(handle) is True
    assert adapter.is_read_only_on_disk(handle) is True
    assert adapter.is_missing(handle) is True
    assert adapter.is_writable(handle) is False
    assert adapter.get_edit_target_identifier() == ""
    subscription = adapter.subscribe_events(lambda event: None)
    subscription.cancel()
    assert adapter.get_prim_specs(handle.identifier) == []
    assert adapter.has_prim_spec(handle.identifier, "/World") is False
    assert adapter.save_layer(handle.identifier) is False
    save_as_path = tmp_path / "saved.usda"
    assert adapter.save_layer_as(handle.identifier, str(save_as_path), True) is None
    assert adapter.reload_layer(handle.identifier) is False

    explicit_failures = (
        lambda: adapter.get_root_layer(),
        lambda: adapter.get_display_name(handle),
        lambda: adapter.set_edit_target(handle.identifier),
        lambda: adapter.set_mute(handle.identifier, True),
        lambda: adapter.set_lock(handle.identifier, True),
        lambda: adapter.create_sublayer(
            handle.identifier,
            -1,
            str(tmp_path / "child.usda"),
        ),
        lambda: adapter.insert_sublayer(
            handle.identifier,
            -1,
            str(tmp_path / "existing.usda"),
        ),
        lambda: adapter.remove_sublayer(handle.identifier, 0),
        lambda: adapter.move_sublayer(
            handle.identifier,
            0,
            handle.identifier,
            1,
        ),
        lambda: adapter.replace_sublayer(
            handle.identifier,
            0,
            "replacement.usda",
        ),
        lambda: adapter.export_prim_spec(handle.identifier, "/World"),
        lambda: adapter.remove_prim_spec(handle.identifier, "/World"),
        lambda: adapter.import_prim_spec(
            handle.identifier,
            "/World",
            "#usda 1.0",
        ),
        lambda: adapter.snapshot_layer(handle.identifier),
        lambda: adapter.restore_layer_from_snapshot(_SNAPSHOT),
        lambda: adapter.transfer_layer_content(
            "child.usda",
            handle.identifier,
        ),
        lambda: adapter.persist_layer_state_before_save(object()),
    )
    for call in explicit_failures:
        with pytest.raises(NotImplementedError, match="not implemented yet"):
            call()

    assert not save_as_path.exists()
    assert not (tmp_path / "child.usda").exists()
    assert not (tmp_path / "existing.usda").exists()
    assert scene.accesses == []
    assert _loaded_modules("pxr") == pxr_before
    assert _loaded_modules("ovui_data_adapters.openusd") == openusd_before


def test_unsupported_property_clear_has_no_hybrid_delegate() -> None:
    pxr_before = _loaded_modules("pxr")
    openusd_before = _loaded_modules("ovui_data_adapters.openusd")
    assert not hasattr(OvstagePropertyAdapter, "_make_usd_adapter")
    adapter = OvstagePropertyAdapter(scene=object(), paths=["/World/Cube"])

    for attr_name in ("size", "faceVertexIndices", "localMatrix"):
        with pytest.raises(NotImplementedError) as caught:
            adapter.clear_value(attr_name)
        assert str(caught.value) == _CLEAR_VALUE_REASON

    capability = adapter.get_capabilities().clear_values
    assert capability.is_unsupported
    assert capability.reason == _CLEAR_VALUE_REASON
    assert _loaded_modules("pxr") == pxr_before
    assert _loaded_modules("ovui_data_adapters.openusd") == openusd_before
