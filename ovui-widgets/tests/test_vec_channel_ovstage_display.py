# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""What a vector row shows after one channel is typed for objects of ovstage.

Regression, ovstage provider: select three cameras with the clipping ranges
(1, 1000), (5, 2000) and (8, 3000), type X = 3. After the edit, and after
Undo and Redo, the Property Inspector builds the row again. X must show
the typed value 3.0, and Y must show "Mixed".
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
from ovui_widgets.property.attribute_row import Vec2FloatAttributeRow
from ovui_widgets.property.parts.attr_context_menu import (
    clear_clipboard,
    copy_value,
)
from ovui_widgets.property.parts.display_group import UiDisplayGroup
from ovui_widgets.property.parts.group_context_menu import (
    clear_clipboard as clear_group_clipboard,
    copy_group,
)


pytestmark = [
    pytest.mark.requires_ovstage,
]

_CAMERAS = ["/World/CameraA", "/World/CameraB", "/World/CameraC"]
_THREE_CAMERAS_USDA = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Camera "CameraA"
    {
        float2 clippingRange = (1, 1000)
    }

    def Camera "CameraB"
    {
        float2 clippingRange = (5, 2000)
    }

    def Camera "CameraC"
    {
        float2 clippingRange = (8, 3000)
    }
}
"""


@pytest.fixture()
def three_cameras(tmp_path: pathlib.Path) -> Iterator[OvstageScene]:
    scene_path = tmp_path / "three_cameras.usda"
    scene_path.write_text(_THREE_CAMERAS_USDA)
    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )
    session = create_provider_session(runtime=runtime)
    scene = session.open_stage(str(scene_path))
    try:
        yield scene
    finally:
        clear_clipboard()
        clear_group_clipboard()
        session.shutdown_scene()


def _clipping_range(scene: OvstageScene, path: str) -> tuple[float, ...]:
    stage = scene._stage
    raw = bytes(stage.read_attribute(int(stage.current_ordinal), [path], "clippingRange"))
    return struct.unpack("<2f", raw)


def _build_row(adapter: OvstagePropertyAdapter, window_name: str) -> tuple[Any, Any]:
    """Build the row as the Property Inspector does after each change."""
    window = ui.Window(window_name, width=400, height=60)
    with window.frame:
        row = Vec2FloatAttributeRow(adapter.get_attribute_metadata("clippingRange"), adapter)
    return row, window


def _shown(adapter: OvstagePropertyAdapter, window_name: str) -> list[Any]:
    """Each channel of a new row as the user sees it: "Mixed", or the value."""
    row, _window = _build_row(adapter, window_name)
    return [
        "Mixed" if overlay.visible else widget.model.get_value_as_float()
        for widget, overlay in zip(row._widgets, row._overlay_labels)
    ]


def test_typed_channel_shows_the_typed_value_after_edit_undo_and_redo(
    three_cameras: OvstageScene,
) -> None:
    undo = UndoManager()
    adapter = OvstagePropertyAdapter(three_cameras, _CAMERAS, undo_manager=undo)
    assert _shown(adapter, "test_539_ovstage_before") == ["Mixed", "Mixed"]

    row, _window = _build_row(adapter, "test_539_ovstage_edit")
    model = row._widgets[0].model
    row._on_begin_edit(model)
    model.set_value(3.0)
    row._on_end_edit(model)

    assert [_clipping_range(three_cameras, path) for path in _CAMERAS] == [
        pytest.approx((3.0, 1000.0)),
        pytest.approx((3.0, 2000.0)),
        pytest.approx((3.0, 3000.0)),
    ]
    assert _shown(adapter, "test_539_ovstage_after_edit") == [3.0, "Mixed"]

    assert undo.undo() is True
    assert _shown(adapter, "test_539_ovstage_after_undo") == ["Mixed", "Mixed"]

    assert undo.redo() is True
    assert _shown(adapter, "test_539_ovstage_after_redo") == [3.0, "Mixed"]


def test_copy_of_a_mixed_vector_stores_no_value(three_cameras: OvstageScene) -> None:
    # Paste must not write the vector of one camera into the others.
    adapter = OvstagePropertyAdapter(three_cameras, _CAMERAS)
    group = UiDisplayGroup(name="Camera")
    group.add_prop(adapter.get_attribute_metadata("clippingRange"), ())

    assert copy_value(adapter, "clippingRange")["value"] is None
    assert copy_group(adapter, group) == {"clippingRange": None}
