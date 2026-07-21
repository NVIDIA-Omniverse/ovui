# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this software, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovrtx initial scene load from the ovstage provider context."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import numpy as np
import pytest

from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.renderer_adapter import (
    _RENDER_CAMERA_LOCAL_PATH,
    _RENDER_PRODUCT_LOCAL_PATH,
    OvstageRendererAdapter,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes


pytestmark = [
    pytest.mark.requires_ovstage,
    pytest.mark.requires_ovrtx,
]

_ISOLATED_CHILD_ENV = "OVUI_OVSTAGE_RENDERER_INITIAL_LOAD_CHILD"


def test_load_stage_uses_ovstage_scene_context_and_renders_real_frame(
    ovstage_static_scene_path: pathlib.Path,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.environ.get(_ISOLATED_CHILD_ENV) != "1":
        # OVRTX must create its Carbonite framework before any OVStage Stage in
        # the process.  The full adapter suite intentionally opens many native
        # scenes before reaching this file, so validate the real renderer in a
        # fresh process instead of depending on test ordering.
        env = dict(os.environ)
        env[_ISOLATED_CHILD_ENV] = "1"
        test_name = (
            test_load_stage_uses_ovstage_scene_context_and_renders_real_frame.__name__
        )
        test_id = f"{pathlib.Path(__file__).resolve()}::{test_name}"
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", test_id],
            cwd=pathlib.Path(__file__).resolve().parents[3],
            env=env,
            capture_output=True,
            text=True,
            timeout=300.0,
        )
        assert proc.returncode == 0, (
            "isolated OVRTX-before-OVStage renderer validation failed\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
        return

    monkeypatch.setenv("OVUI_WIDGETS_REQUIRE_OVRTX", "1")

    # Kit requires OVRTX to establish the shared framework/schema state before
    # OVStage creates its Stage.  Reversing this order produces two framework
    # instances and a black renderer with no population interface.
    adapter = OvstageRendererAdapter()
    session = None
    try:
        runtime = load_required_runtimes(
            module_name=PROVIDER_NAME,
            entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
        )
        session = create_provider_session(runtime=runtime)
        scene = session.open_stage(str(ovstage_static_scene_path))
        scene._source_path = str(tmp_path / "missing_source.usda")
        adapter.load_stage(scene)

        assert adapter._last_load_from_scene_context is True
        assert adapter._renderer.config.use_vulkan is True
        borrow_mode = getattr(
            getattr(adapter._ovrtx, "AttachMode", None),
            "BORROW",
            None,
        )
        if borrow_mode is None:
            assert not hasattr(adapter._renderer.config, "attach_mode")
        else:
            assert adapter._renderer.config.attach_mode is borrow_mode
        assert adapter._attached_stage is scene._stage
        assert adapter in scene._attached_renderers
        assert adapter._path_dictionary is not None
        assert adapter._camera_path == _RENDER_CAMERA_LOCAL_PATH
        assert adapter._render_product_path == _RENDER_PRODUCT_LOCAL_PATH

        frame = None
        for _ in range(8):
            frame = adapter.render_frame(730, 401, None, None)
        assert isinstance(frame, np.ndarray)
        assert frame.shape == (401, 730, 4)
        assert frame.dtype == np.uint8
        assert frame.flags.c_contiguous
        rgb = frame[:, :, :3]
        unique_colors = int(np.unique(rgb.reshape(-1, 3), axis=0).shape[0])
        nonblack_coverage = float(np.any(rgb > 8, axis=2).mean())
        bright_coverage = float(np.any(rgb > 50, axis=2).mean())
        assert adapter._logged_first_step is True
        assert adapter._borrow_step_count == 8
        assert int(rgb.max()) > 128
        assert unique_colors > 200
        assert nonblack_coverage > 0.95
        assert bright_coverage > 0.02
        assert float(rgb.std()) > 10.0
    finally:
        adapter.shutdown()
        if session is not None:
            session.shutdown_scene()
