# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION is strictly
# prohibited.

"""Held-drag preview writes obey the CURRENT transform edit policy, cheaply.

Two contracts, pinned together because each previously broke the other:

1. Policy truth: every preview write re-derives the full transform edit
   policy.  No verdict survives any change in the conditions that produced
   it — body mode flips, control-target availability, controls replacement,
   playback transitions, prim deletion, transform-column removal, and native
   write failure must all fail closed mid-sequence, exactly as a fresh
   ``get_transform_edit_policy`` call decides.
2. Performance: the policy's matrix-column probe is a narrow single-path
   native read.  Repeated preview writes must never rebuild the ordinal-keyed
   full-stage bridge cache (one rebuild per pointer move was the Outcome 1
   frame-rate collapse).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

from ovui_data_adapters.ovstage import _scene as scene_module
from ovui_data_adapters.ovstage._constants import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage._stage_write import StageWriteBatch
from ovui_data_adapters.ovstage.provider import (
    create_provider_session,
    create_transform_adapter,
)
from ovui_data_adapters.ovstage.renderer_adapter import OvstageRendererAdapter
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes


_SCENE = '''#usda 1.0
(
    upAxis = "Z"
)

def Xform "World"
{
    def Cube "First"
    {
        double size = 2
        double3 xformOp:translate = (-2, 0, 1)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }

    def Sphere "Second"
    {
        double radius = 1
        double3 xformOp:translate = (3, 1, -1)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
}
'''

FIRST = "/World/First"
SECOND = "/World/Second"


@pytest.fixture(scope="module")
def ovstage_runtime() -> Any:
    package_parent = Path(__file__).resolve().parents[2]
    previous_paths = list(sys.path)
    loaded = sys.modules.get("ovstage")
    if loaded is not None and not callable(getattr(loaded, "Stage", None)):
        sys.modules.pop("ovstage", None)
    sys.path[:] = [
        entry
        for entry in sys.path
        if not entry or Path(entry).resolve() != package_parent
    ]
    try:
        return load_required_runtimes(
            module_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        )
    finally:
        sys.path[:] = previous_paths


@pytest.fixture()
def opened_scene(
    tmp_path: Path,
    ovstage_runtime: Any,
) -> Iterator[tuple[Any, Any, Any]]:
    scene_path = tmp_path / "live-preview-policy-truth.usda"
    scene_path.write_text(_SCENE, encoding="utf-8")
    session = create_provider_session(runtime=ovstage_runtime)
    scene = session.open_stage(str(scene_path))
    transform = create_transform_adapter(scene)
    try:
        yield session, scene, transform
    finally:
        session.shutdown_scene()


def _renderer_shell(scene: Any) -> OvstageRendererAdapter:
    adapter = object.__new__(OvstageRendererAdapter)
    adapter._scene = scene
    adapter._attached_stage = scene._stage
    adapter._renderer = object()
    adapter._runtime_root_path = "/_OvuiRuntime"
    adapter._live_preview_write_count = 0
    adapter._live_preview_clear_count = 0
    adapter._live_preview_paths = set()
    adapter._last_live_preview_path = None
    adapter._last_live_preview_matrix = None
    adapter._live_transform_adapter = create_transform_adapter(scene)
    return adapter


def _translated(x: float) -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [float(x), 0.0, 0.0, 1.0],
    ]


class MutablePhysics:
    """Physics controls whose every policy input can mutate mid-sequence."""

    def __init__(self, mode: str = "static", playing: bool = True) -> None:
        self.playing = playing
        self.modes: dict[str, str] = {}
        self.default_mode = mode
        self.explicit_target = False
        self.can_route = False

    def get_body_mode(self, path: str) -> str:
        return self.modes.get(path, self.default_mode)

    def has_control_target_mode(self, path: str) -> bool:
        return self.explicit_target

    def can_apply_control_target(self, path: str) -> bool:
        return self.can_route


def test_repeated_previews_never_rebuild_full_stage_bridge_cache(
    opened_scene: tuple[Any, Any, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session, scene, transform = opened_scene
    adapter = _renderer_shell(scene)

    rebuilds = {"count": 0}
    real_build = scene_module._build_kit_stage_cache

    def counted_build(stage: Any, ordinal: int) -> Any:
        rebuilds["count"] += 1
        return real_build(stage, ordinal)

    monkeypatch.setattr(scene_module, "_build_kit_stage_cache", counted_build)

    assert adapter.set_live_local_transform(FIRST, _translated(1.0)) is True
    after_first = rebuilds["count"]
    for step in range(2, 42):
        assert adapter.set_live_local_transform(
            FIRST, _translated(float(step))
        ) is True

    assert adapter._live_preview_write_count == 41
    assert rebuilds["count"] == after_first, (
        "held-drag preview writes must not rebuild the ordinal-keyed "
        "full-stage bridge cache (the policy probe must stay narrow)"
    )
    assert transform.get_local_transform(FIRST)[3][0] == pytest.approx(41.0)


def test_policy_is_rederived_on_every_write_not_cached(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    _session, scene, _transform = opened_scene
    adapter = _renderer_shell(scene)
    transform = adapter._live_transform_adapter
    calls = {"count": 0}
    real_policy = transform.get_transform_edit_policy

    def counted(path: str) -> Any:
        calls["count"] += 1
        return real_policy(path)

    transform.get_transform_edit_policy = counted  # type: ignore[method-assign]

    for step in range(1, 11):
        assert adapter.set_live_local_transform(
            FIRST, _translated(float(step))
        ) is True
    assert calls["count"] == 10, "one full policy decision per preview write"
    # Diagnostic record only — reflects the latest verdict, grants nothing.
    assert adapter._live_preview_policy_cache == {FIRST: True}
    adapter.clear_live_local_transforms([FIRST])
    assert adapter._live_preview_policy_cache == {}


def test_body_mode_flip_mid_sequence_blocks_next_write(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    _session, scene, transform = opened_scene
    adapter = _renderer_shell(scene)
    controls = MutablePhysics("static")
    scene.attach_physics_controls(controls)
    try:
        assert adapter.set_live_local_transform(FIRST, _translated(1.0)) is True
        controls.default_mode = "dynamic"
        assert transform.get_transform_edit_policy(FIRST).direct_write_allowed is False
        assert adapter.set_live_local_transform(FIRST, _translated(2.0)) is False, (
            "a body mode change to dynamic must block the very next preview "
            "write while playback stays active"
        )
        assert transform.get_local_transform(FIRST)[3][0] == pytest.approx(1.0)
        assert adapter._live_preview_policy_cache[FIRST] is False
    finally:
        scene.attach_physics_controls(None)


def test_control_target_unavailability_mid_sequence_blocks_next_write(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    _session, scene, transform = opened_scene
    adapter = _renderer_shell(scene)
    controls = MutablePhysics("static")
    scene.attach_physics_controls(controls)
    try:
        assert adapter.set_live_local_transform(FIRST, _translated(1.0)) is True
        controls.explicit_target = True
        controls.can_route = False
        assert transform.get_transform_edit_policy(FIRST).direct_write_allowed is False
        assert adapter.set_live_local_transform(FIRST, _translated(2.0)) is False, (
            "an explicit control target without a routable ovphysx target "
            "must block the very next preview write"
        )
        assert transform.get_local_transform(FIRST)[3][0] == pytest.approx(1.0)
    finally:
        scene.attach_physics_controls(None)


def test_controls_replacement_mid_sequence_blocks_next_write(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    _session, scene, transform = opened_scene
    adapter = _renderer_shell(scene)
    scene.attach_physics_controls(MutablePhysics("static"))
    try:
        assert adapter.set_live_local_transform(FIRST, _translated(1.0)) is True
        scene.attach_physics_controls(MutablePhysics("dynamic"))
        assert transform.get_transform_edit_policy(FIRST).direct_write_allowed is False
        assert adapter.set_live_local_transform(FIRST, _translated(2.0)) is False, (
            "replacing the controls object with one reporting a dynamic body "
            "must block the very next preview write"
        )
        assert transform.get_local_transform(FIRST)[3][0] == pytest.approx(1.0)
    finally:
        scene.attach_physics_controls(None)


def test_playback_transitions_block_and_unblock_mid_sequence(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    _session, scene, transform = opened_scene
    adapter = _renderer_shell(scene)
    controls = MutablePhysics("dynamic", playing=False)
    scene.attach_physics_controls(controls)
    try:
        assert adapter.set_live_local_transform(FIRST, _translated(1.0)) is True
        controls.playing = True
        assert adapter.set_live_local_transform(FIRST, _translated(2.0)) is False
        controls.playing = False
        assert adapter.set_live_local_transform(FIRST, _translated(3.0)) is True
        assert transform.get_local_transform(FIRST)[3][0] == pytest.approx(3.0)
    finally:
        scene.attach_physics_controls(None)


def test_multi_selection_policy_is_per_path_and_current(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    _session, scene, transform = opened_scene
    adapter = _renderer_shell(scene)
    controls = MutablePhysics("static")
    scene.attach_physics_controls(controls)
    try:
        assert adapter.set_live_local_transform(FIRST, _translated(1.0)) is True
        assert adapter.set_live_local_transform(SECOND, _translated(-1.0)) is True
        controls.modes[SECOND] = "dynamic"
        assert adapter.set_live_local_transform(FIRST, _translated(2.0)) is True
        assert adapter.set_live_local_transform(SECOND, _translated(-2.0)) is False, (
            "per-path body mode changes must block exactly the affected path"
        )
        assert transform.get_local_transform(FIRST)[3][0] == pytest.approx(2.0)
        assert transform.get_local_transform(SECOND)[3][0] == pytest.approx(-1.0)
    finally:
        scene.attach_physics_controls(None)


def test_prim_deletion_mid_sequence_blocks_next_write(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    _session, scene, _transform = opened_scene
    adapter = _renderer_shell(scene)
    assert adapter.set_live_local_transform(SECOND, _translated(1.0)) is True
    with StageWriteBatch(scene._stage, [SECOND]) as batch:
        batch.delete_prims()
    before_ordinal = int(scene.current_ordinal)
    assert adapter.set_live_local_transform(SECOND, _translated(2.0)) is False, (
        "a deleted prim must fail closed on the very next preview write"
    )
    assert int(scene.current_ordinal) == before_ordinal, (
        "a refused preview write must not commit a native ordinal"
    )


def test_transform_column_removal_mid_sequence_blocks_next_write(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    from importlib import import_module

    _session, scene, _transform = opened_scene
    adapter = _renderer_shell(scene)
    stage = scene._stage
    assert adapter.set_live_local_transform(FIRST, _translated(1.0)) is True

    ovstage = import_module("ovstage")
    with ovstage.PathDictionary(stage) as paths:
        tokens = [
            paths.intern_token("omni:fabric:localMatrix"),
            paths.intern_token("omni:fabric:worldMatrix"),
            paths.intern_token("omni:xform"),
        ]
        path_list = paths.create_path_list_from_strings([FIRST])
        try:
            with stage.query_from_path_list(path_list) as query:
                query.wait()
                ordinal = int(stage.begin_frame())
                operation = stage.delete_attributes(query, tokens, ordinal)
                wait = getattr(operation, "wait", None)
                if callable(wait):
                    wait()
                stage.end_frame(ordinal)
        finally:
            paths.destroy_path_list(path_list)

    assert adapter.set_live_local_transform(FIRST, _translated(2.0)) is False, (
        "removing the runtime transform columns must fail closed on the very "
        "next preview write"
    )


def test_native_write_failure_returns_false_without_success_bookkeeping(
    opened_scene: tuple[Any, Any, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session, scene, transform = opened_scene
    adapter = _renderer_shell(scene)
    assert adapter.set_live_local_transform(FIRST, _translated(1.0)) is True
    writes_before = adapter._live_preview_write_count

    def failing_write(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("injected native write failure")

    monkeypatch.setattr(scene._stage, "write_attribute", failing_write)
    assert adapter.set_live_local_transform(FIRST, _translated(2.0)) is False, (
        "a native write failure must surface as False, never fake success"
    )
    assert adapter._live_preview_write_count == writes_before
    monkeypatch.undo()
    assert transform.get_local_transform(FIRST)[3][0] == pytest.approx(1.0)


def test_detach_clears_diagnostic_record_and_disables_previews(
    opened_scene: tuple[Any, Any, Any],
) -> None:
    _session, scene, _transform = opened_scene
    adapter = _renderer_shell(scene)
    assert adapter.set_live_local_transform(FIRST, _translated(1.0)) is True
    assert adapter._live_preview_policy_cache == {FIRST: True}
    adapter._attached_stage = None
    adapter._remove_scene()
    assert adapter._live_preview_policy_cache == {}
    assert adapter.supports_live_local_transform is False
    assert adapter.set_live_local_transform(FIRST, _translated(2.0)) is False
