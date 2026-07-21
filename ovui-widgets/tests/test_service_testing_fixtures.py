# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for reusable adapter fixtures in ``ovui_data_adapters.services``."""

from __future__ import annotations

import os
import subprocess
import sys

from ovui_data_adapters.services.content.backends import BackendResult
from ovui_data_adapters.services.testing import (
    MockBackend,
    MockLayerStackAdapter,
    MockPropertyAdapter,
    MockRendererAdapter,
    MockStageAdapter,
    MockTransformAdapter,
)


def test_old_fixture_paths_reexport_canonical_objects() -> None:
    from ovui_widgets.app.testing import MockBackend as AppTestingBackend
    from ovui_widgets.app.testing.mock_backend import MockBackend as BackendModuleMock
    from ovui_widgets.common.testing import MockStageAdapter as CommonTestingStage
    from ovui_widgets.common.testing.mock_layer_stack import (
        MockLayerStackAdapter as LayerStackModuleMock,
    )
    from ovui_widgets.common.testing.mock_property import (
        MockPropertyAdapter as PropertyModuleMock,
    )
    from ovui_widgets.common.testing.mock_renderer import (
        MockRendererAdapter as RendererModuleMock,
    )
    from ovui_widgets.common.testing.mock_stage import MockStageAdapter as StageModuleMock
    from ovui_widgets.common.testing.mock_transform import (
        MockTransformAdapter as TransformModuleMock,
    )

    assert AppTestingBackend is MockBackend
    assert BackendModuleMock is MockBackend
    assert CommonTestingStage is MockStageAdapter
    assert StageModuleMock is MockStageAdapter
    assert LayerStackModuleMock is MockLayerStackAdapter
    assert PropertyModuleMock is MockPropertyAdapter
    assert RendererModuleMock is MockRendererAdapter
    assert TransformModuleMock is MockTransformAdapter


def test_service_mocks_exercise_adapter_contracts() -> None:
    stage = MockStageAdapter()
    root = stage.get_root()
    assert stage.get_display_name(root) == "World"
    assert stage.get_item_at_path("/World/Geometry/Cube") is not None

    layer_stack = MockLayerStackAdapter()
    child = layer_stack.create_sublayer("@root@", -1, "child.usda")
    assert child == "child.usda"
    assert layer_stack.get_sublayer_identifiers(layer_stack.get_root_layer()) == [
        "child.usda"
    ]

    props = MockPropertyAdapter(paths=["/World/Cube"])
    assert props.get_paths() == ["/World/Cube"]

    transform = MockTransformAdapter(blocked={"/World/Locked"})
    assert transform.can_transform("/World/Cube") is True
    assert transform.can_transform("/World/Locked") is False

    backend = MockBackend()
    result = backend.copy(
        "mock://Home/Documents/Projects/demo.usda",
        "mock://Home/Documents/Projects/demo Copy.usda",
    )
    assert result is BackendResult.OK
    stat_result, entry = backend.stat("mock://Home/Documents/Projects/demo Copy.usd")
    assert stat_result is BackendResult.ERROR_NOT_FOUND
    stat_result, entry = backend.stat("mock://Home/Documents/Projects/demo Copy.usda")
    assert stat_result is BackendResult.OK
    assert entry is not None and entry.name == "demo Copy.usda"


def test_services_testing_imports_without_ui_runtime_or_numpy() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = "ovui-data-adapters"
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from ovui_data_adapters.services.testing import "
                "MockBackend, MockRendererAdapter, MockStageAdapter; "
                "loaded = sorted(name for name in sys.modules "
                "if name == 'ovui_widgets' or name.startswith('ovui_widgets.') "
                "or name == 'omni' or name.startswith('omni.') "
                "or name == 'numpy' or name.startswith('numpy.')); "
                "print(MockBackend().supports_url('mock://Home'), "
                "MockStageAdapter().get_display_name(MockStageAdapter().get_root()), "
                "MockRendererAdapter.__name__, loaded); "
                "raise SystemExit(1 if loaded else 0)"
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        "services testing import loaded forbidden/optional runtime modules.\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
    assert "True World MockRendererAdapter []" in proc.stdout
