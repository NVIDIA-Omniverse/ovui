# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Native OVStage population coverage for every supported 0.1 Create action."""

from __future__ import annotations

import pytest
from ovui_data_adapters.common import CreateRequest
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
    create_stage_adapter,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.services.undo import UndoManager

pytestmark = pytest.mark.requires_ovstage


_CREATE_CASES = (
    ("create.geometry.mesh.cone", "Mesh", True),
    ("create.geometry.mesh.cube", "Mesh", True),
    ("create.geometry.mesh.cylinder", "Mesh", True),
    ("create.geometry.mesh.disk", "Mesh", True),
    ("create.geometry.mesh.plane", "Mesh", True),
    ("create.geometry.mesh.sphere", "Mesh", True),
    ("create.geometry.mesh.torus", "Mesh", True),
    ("create.geometry.shape.capsule", "Capsule", True),
    ("create.geometry.shape.cone", "Cone", True),
    ("create.geometry.shape.cube", "Cube", True),
    ("create.geometry.shape.cylinder", "Cylinder", True),
    ("create.geometry.shape.sphere", "Sphere", True),
    ("create.light.cylinder", "CylinderLight", True),
    ("create.light.disk", "DiskLight", True),
    ("create.light.distant", "DistantLight", True),
    ("create.light.dome", "DomeLight", True),
    ("create.light.rect", "RectLight", True),
    ("create.light.sphere", "SphereLight", True),
    ("create.camera", "Camera", True),
    ("create.scope", "Scope", False),
    ("create.xform", "Xform", True),
    ("create.material.usd-preview-surface", "Material", False),
)


def _assert_native_prim(
    scene,
    adapter,
    path: str,
    expected_type: str,
    expects_matrix: bool,
) -> None:
    item = adapter.get_item_at_path(path)
    assert item is not None, path
    assert adapter.get_type_name(item) == expected_type
    if expects_matrix:
        raw = scene._stage.read_attribute(
            int(scene.current_ordinal),
            [path],
            "localMatrix",
        )
        assert isinstance(raw, bytes) and len(raw) in (64, 128), (
            path,
            expected_type,
            len(raw) if isinstance(raw, bytes) else type(raw),
        )


def test_all_supported_create_actions_populate_native_topology_on_do_undo_redo(
    ovstage_static_scene_path,
) -> None:
    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )
    session = create_provider_session(runtime=runtime)
    # Durable new-document creation is intentionally unsupported by the
    # native-only provider; creation parity runs against an opened native
    # scene and is verified through the public native surface alone.
    scene = session.open_stage(str(ovstage_static_scene_path))
    try:
        undo = UndoManager()
        adapter = create_stage_adapter(scene, undo)
        created: list[tuple[str, str, bool]] = []

        for index, (action_id, expected_type, expects_matrix) in enumerate(
            _CREATE_CASES
        ):
            result = adapter.create_prim(
                CreateRequest(
                    action_id,
                    requested_name=f"Parity{index:02d}{expected_type}",
                )
            )
            assert result.accepted, (action_id, result.message)
            path = result.primary_path
            _assert_native_prim(
                scene,
                adapter,
                path,
                expected_type,
                expects_matrix,
            )
            created.append((path, expected_type, expects_matrix))

        for path, _expected_type, _expects_matrix in reversed(created):
            assert undo.undo()
            assert adapter.get_item_at_path(path) is None

        for path, expected_type, expects_matrix in created:
            assert undo.redo()
            _assert_native_prim(
                scene,
                adapter,
                path,
                expected_type,
                expects_matrix,
            )
    finally:
        session.shutdown_scene()


def test_atomic_material_create_and_bind_repopulates_existing_native_source(
    ovstage_static_scene_path,
) -> None:
    """Shell preparation must not consume the existing mesh binding notice."""

    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )
    session = create_provider_session(runtime=runtime)
    scene = session.open_stage(str(ovstage_static_scene_path))
    box_path = "/World/Hierarchy/GroupA/BoxA"
    try:
        adapter = create_stage_adapter(scene, UndoManager())
        # The legacy core-materials API fails closed on the native adapter;
        # atomic create-and-bind is a first-class native create action.
        action = adapter.list_create_actions(selection_paths=(box_path,)).action(
            "create.material.usd-preview-surface.bind"
        )
        assert action is not None and action.is_available
        result = adapter.create_prim(
            CreateRequest(
                action.action_id,
                requested_name="NativeBoundPreview",
                selection_paths=(box_path,),
            )
        )

        assert result.accepted, result.message
        assert result.binding_applied is True
        assert scene._stage.read_path_targets(
            int(scene.current_ordinal),
            box_path,
            "material:binding",
        ) == (result.primary_path,)
    finally:
        session.shutdown_scene()
