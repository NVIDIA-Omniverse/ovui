# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Native regressions for repeated USD create/delete population transitions."""

from __future__ import annotations

import struct

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


def _native_matrix(scene, path: str) -> tuple[float, ...]:
    raw = scene._stage.read_attribute(
        int(scene.current_ordinal),
        [path],
        "localMatrix",
    )
    assert isinstance(raw, bytes) and len(raw) in (64, 128)
    code = "f" if len(raw) == 64 else "d"
    return tuple(float(value) for value in struct.unpack(f"<16{code}", raw))


def test_mesh_redo_repopulates_authored_transform_after_native_shell_creation(
    ovstage_static_scene_path,
) -> None:
    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )
    session = create_provider_session(runtime=runtime)
    # Durable new-document creation is unsupported natively; redo parity
    # runs against an opened native scene.
    scene = session.open_stage(str(ovstage_static_scene_path))
    try:
        undo = UndoManager()
        adapter = create_stage_adapter(scene, undo)
        result = adapter.create_prim(
            CreateRequest("create.geometry.mesh.cube", requested_name="Cube")
        )
        assert result.accepted
        path = result.primary_path

        # Native creation authors the mesh shell's exact local matrix; redo
        # must repopulate that authored transform byte-for-byte rather than
        # recreating a bare shell. (The old +Y spawn offset belonged to the
        # removed OpenUSD-delegated creation path.)
        initial = _native_matrix(scene, path)
        assert len(initial) == 16

        assert undo.undo()
        assert adapter.get_item_at_path(path) is None
        assert undo.redo()
        assert adapter.get_item_at_path(path) is not None
        restored = _native_matrix(scene, path)
        assert restored == pytest.approx(initial)
    finally:
        session.shutdown_scene()
