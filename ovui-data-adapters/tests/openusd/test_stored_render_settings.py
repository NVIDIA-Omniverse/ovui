# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A scene's stored render settings reach the session sent to ovrtx.

Kit stores them in the root layer ``customLayerData['renderSettings']`` and
applies them when it opens the scene. A scene saved with the Iray tone mapper
and ``filmIso = 0`` renders black without them.
"""

from __future__ import annotations

import pytest
from pxr import Sdf, Usd

from ovui_data_adapters.openusd.renderer_adapter import (
    _CAMERA_PATH,
    _RENDER_PRODUCT_PATH,
    OvRtxRendererAdapter,
)

_STORED = """(
    customLayerData = {
        dictionary renderSettings = {
            float "rtx:post:tonemap:exposureTime" = 0.01
            float "rtx:post:tonemap:filmIso" = 0
            float "rtx:post:tonemap:fNumber" = 16
            int "rtx:post:tonemap:op" = 7
            float "rtx:post:tonemap:responsivity" = 2
        }
    }
)
"""

_SCENE = """
def Xform "World"
{
    def Sphere "Sphere"
    {
    }
}
"""


def _session_usda(stage) -> str:
    """Open ``stage`` and return the session layer the adapter sends to ovrtx."""

    sent: list[str] = []
    adapter = object.__new__(OvRtxRendererAdapter)
    adapter._renderer = None
    adapter._stage = None
    adapter._usd_handle = None
    adapter._session_handle = None
    adapter._live_resync_handles = []
    adapter._owned_tmp_path = None
    adapter._last_resolution = (64, 64)
    adapter._pending_resolution = (64, 64)
    adapter._render_product_path = _RENDER_PRODUCT_PATH
    adapter._default_camera_path = _CAMERA_PATH
    adapter._release_retained_output = lambda: None
    adapter._dispatch_pending_pick_misses = lambda: None
    adapter._mark_selection_outline_state_stale = lambda **kwargs: None
    adapter._uses_owned_render_product = lambda: True
    adapter._author_owned_session_render_product_resolution = lambda res: None
    adapter._remove_ovrtx_layers = lambda: None
    adapter._reset_render_timing_state = lambda: None
    adapter._open_ovrtx_root = lambda path, root_layer_content=None: object()
    adapter._add_ovrtx_session_layer = lambda usda: sent.append(usda) or object()
    adapter.load_stage(stage)
    return sent[-1]


def _stage(text: str):
    stage = Usd.Stage.CreateInMemory()
    stage.GetRootLayer().ImportFromString("#usda 1.0\n" + text)
    return stage


def test_stored_render_settings_reach_the_session() -> None:
    session = _session_usda(_stage(_STORED + _SCENE))

    assert 'token omni:rtx:post:tonemap:operator = "iray"' in session
    assert "float exposure:iso = 0.0" in session
    assert "float exposure:time = 0.009999999776482582" in session
    assert "float exposure:fStop = 16.0" in session
    assert "float exposure:responsivity = 2.0" in session


def _parsed(session: str) -> Sdf.Layer:
    """The session layer ovrtx receives, read back by the USD parser."""

    layer = Sdf.Layer.CreateAnonymous()
    assert layer.ImportFromString(session), "the session does not parse"
    return layer


# ``totalSpp`` maps to the uint ``omni:rtx:pt:samplesPerPixel``. A scene can
# store any number under the key, and a number no uint holds would refuse the
# whole session, taking the valid settings of the scene with it.
_TOO_WIDE = """(
    customLayerData = {
        dictionary renderSettings = {
            int64 "rtx:pathtracing:totalSpp" = VALUE
            int "rtx:post:tonemap:op" = 7
            float "rtx:post:tonemap:fNumber" = 16
        }
    }
)
"""


@pytest.mark.parametrize("value", [-1, 4294967296])
def test_a_too_wide_stored_integer_leaves_the_session_readable(value) -> None:
    session = _session_usda(_stage(_TOO_WIDE.replace("VALUE", str(value)) + _SCENE))

    _parsed(session)
    assert "omni:rtx:pt:samplesPerPixel" not in session
    assert 'token omni:rtx:post:tonemap:operator = "iray"' in session
    assert "float exposure:fStop = 16.0" in session


# ``customLayerData`` is free-form, so a scene can hold anything under the
# key. None of it may stop the scene from opening.
_NOT_A_DICTIONARY = """(
    customLayerData = {
        ENTRY
    }
)
"""


@pytest.mark.parametrize(
    "entry",
    [
        'string renderSettings = "on"',
        "int renderSettings = 3",
        "int[] renderSettings = [1, 2]",
    ],
)
def test_a_scene_opens_when_its_stored_render_settings_are_not_a_dictionary(
    entry, capsys
) -> None:
    scene = _NOT_A_DICTIONARY.replace("ENTRY", entry)

    session = _session_usda(_stage(scene + _SCENE))

    _parsed(session)
    assert "renderSettings" in capsys.readouterr().err

