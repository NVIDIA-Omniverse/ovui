# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A scene's stored render settings reach the viewport layer.

Kit stores them in the root layer ``customLayerData['renderSettings']`` and
applies them when it opens the scene. A scene saved with the Iray tone mapper
and ``filmIso = 0`` renders black without them.
"""

from ovui_data_adapters.ovstage import renderer_adapter as renderer_module
from test_renderer_livestream import _FakeScene, _patch_adapter_construction


class _StoredScene(_FakeScene):
    def stored_render_settings(self) -> dict:
        return {
            "rtx:post:tonemap:exposureTime": 0.01,
            "rtx:post:tonemap:filmIso": 0.0,
            "rtx:post:tonemap:fNumber": 16.0,
            "rtx:post:tonemap:op": 7,
            "rtx:post:tonemap:responsivity": 2.0,
        }


def test_stored_render_settings_reach_the_viewport_layer(monkeypatch) -> None:
    build_layer = renderer_module._build_runtime_layer
    _patch_adapter_construction(monkeypatch)
    monkeypatch.setattr(renderer_module, "_build_runtime_layer", build_layer)
    monkeypatch.setattr(renderer_module, "_query_records", lambda _stage: {})
    monkeypatch.setenv("OVGEAR_LIVESTREAM", "0")
    layers = []

    def populate(_population, _stage, usda, *, prefix_path):
        layers.append(usda)
        return object()

    monkeypatch.setattr(renderer_module, "_add_runtime_layer", populate)
    adapter = renderer_module.OvstageRendererAdapter()
    try:
        adapter.load_stage(_StoredScene())
        layer = layers[0]
        camera = layer.split('def Camera "Main"', 1)[1].split("}", 1)[0]
        product = layer.split('def RenderProduct "Viewport"', 1)[1].split("}", 1)[0]
        assert "float exposure:iso = 0.0" in camera
        assert "float exposure:time = 0.01" in camera
        assert "float exposure:fStop = 16.0" in camera
        assert "float exposure:responsivity = 2.0" in camera
        assert 'token omni:rtx:post:tonemap:operator = "iray"' in product
    finally:
        adapter.shutdown()
