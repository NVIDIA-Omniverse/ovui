# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A typed value outside the 32-bit float range, with the ovstage provider.

Regression: a typed number that a 32-bit float attribute cannot hold must
be refused with a message, not stored as infinity. While the user types
key by key, the field writes each number at once, so the refusal must also
put back the value from before the edit. Here a camera clipping range
(float2) of a real ovstage scene is typed 2, 20, 2e+38, then 2e+39.
"""

from __future__ import annotations

import pathlib
import struct
from typing import Any, Iterator

import omni.ui as ui
import pytest

from ovui_data_adapters.ovstage._scene import OvstageScene
from ovui_data_adapters.ovstage.property_adapter import OvstagePropertyAdapter
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
    create_provider_session,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes
from ovui_data_adapters.services.undo import UndoManager
from ovui_widgets.common.error_reporter import ErrorReporter
from ovui_widgets.property.attribute_row import Vec2FloatAttributeRow


pytestmark = [
    pytest.mark.requires_ovstage,
]

_CAMERA = "/World/CameraA"
_CAMERA_USDA = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Camera "CameraA"
    {
        float2 clippingRange = (1, 1000)
    }
}
"""


@pytest.fixture()
def camera_scene(tmp_path: pathlib.Path) -> Iterator[OvstageScene]:
    scene_path = tmp_path / "camera.usda"
    scene_path.write_text(_CAMERA_USDA)
    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )
    session = create_provider_session(runtime=runtime)
    scene = session.open_stage(str(scene_path))
    try:
        yield scene
    finally:
        session.shutdown_scene()


def _clipping_range(scene: OvstageScene) -> tuple[float, ...]:
    stage = scene._stage
    raw = bytes(stage.read_attribute(int(stage.current_ordinal), [_CAMERA], "clippingRange"))
    return struct.unpack("<2f", raw)


def test_value_outside_the_float_range_is_refused_and_the_start_value_comes_back(
    camera_scene: OvstageScene, monkeypatch: Any
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        ErrorReporter, "show_warning", lambda message, *_a, **_k: shown.append(message)
    )
    undo = UndoManager()
    adapter = OvstagePropertyAdapter(camera_scene, [_CAMERA], undo_manager=undo)
    window = ui.Window("test_739_ovstage", width=400, height=60)
    with window.frame:
        row = Vec2FloatAttributeRow(adapter.get_attribute_metadata("clippingRange"), adapter)

    model = row._widgets[0].model
    row._on_begin_edit(model)
    for value in (2.0, 20.0, 2e38, 2e39):
        model.set_value(value)
    row._on_end_edit(model)

    assert _clipping_range(camera_scene) == (1.0, 1000.0)
    assert model.get_value_as_float() == 1.0
    assert undo.can_undo() is False
    assert shown and shown[-1].startswith("Clipping Range X: 2e+39 ")
    assert "32-bit float" in shown[-1]
