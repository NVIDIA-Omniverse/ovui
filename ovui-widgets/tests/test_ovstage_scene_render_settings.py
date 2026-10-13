# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A native ovstage scene exposes the render settings it stores."""

from __future__ import annotations

from pathlib import Path

import pytest

from ovui_data_adapters.ovstage._scene import open_scene_from_file
from ovui_data_adapters.ovstage.provider import (
    PROVIDER_ENTRY_POINT_VALUE,
    PROVIDER_NAME,
)
from ovui_data_adapters.ovstage.runtime_preflight import load_required_runtimes

pytestmark = [pytest.mark.requires_ovstage]

_STORED_SCENE = """#usda 1.0
(
    customLayerData = {
        dictionary renderSettings = {
            float "rtx:post:tonemap:exposureTime" = 0.01
            float "rtx:post:tonemap:filmIso" = 0
            float "rtx:post:tonemap:fNumber" = 16
            int "rtx:post:tonemap:op" = 7
            token "rtx:rendermode" = "PathTracing"
        }
    }
    metersPerUnit = 1
    upAxis = "Y"
)

def DomeLight "Dome"
{
    float inputs:intensity = 1
}
"""

_PLAIN_SCENE = """#usda 1.0
(
    metersPerUnit = 1
    upAxis = "Y"
)

def DomeLight "Dome"
{
    float inputs:intensity = 1
}
"""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            _STORED_SCENE,
            {
                "rtx:post:tonemap:exposureTime": pytest.approx(0.01),
                "rtx:post:tonemap:filmIso": 0.0,
                "rtx:post:tonemap:fNumber": 16.0,
                "rtx:post:tonemap:op": 7,
                "rtx:rendermode": "PathTracing",
            },
        ),
        (_PLAIN_SCENE, {}),
    ],
    ids=["stored", "plain"],
)
def test_the_scene_exposes_its_stored_render_settings(
    tmp_path: Path, text: str, expected: dict
) -> None:
    """Defect: a native ovstage scene has no pxr stage to read them from.

    Kit applies ``customLayerData['renderSettings']`` when it opens a scene.
    The native ovstage provider has no backing USD stage, so the settings
    must come from the stage metadata that population puts on ``/``.
    Without them the regression fixture scene opens black.
    """

    path = tmp_path / "scene.usda"
    path.write_text(text, encoding="utf-8")
    runtime = load_required_runtimes(
        module_name=PROVIDER_NAME,
        entry_point_value=PROVIDER_ENTRY_POINT_VALUE,
    )
    scene = open_scene_from_file(runtime=runtime, path=path)
    try:
        assert scene.stored_render_settings() == expected
    finally:
        scene.shutdown()
