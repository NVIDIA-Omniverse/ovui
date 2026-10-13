# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Runtime-free tests of the private viewport's initial quality budget."""

import pytest

from ovui_data_adapters.ovstage import renderer_adapter as renderer_module
from ovui_data_adapters.ovstage.provider import (
    OvstageProviderSession,
    create_renderer_adapter,
)
from test_renderer_livestream import _FakeScene, _patch_adapter_construction


@pytest.mark.parametrize("options, quality", [({}, 0), ({"viewport_quality": 100}, 100)])
@pytest.mark.parametrize("root", ["/_OvuiRuntime", "/_OvuiRuntime_2"])
@pytest.mark.parametrize("factory", ["constructor", "module", "session"])
def test_load_authors_quality_only_on_generated_viewport(
    monkeypatch, options, quality, root, factory,
):
    # Catch a missing constructor -> load -> population handoff, including when
    # an authored prim occupies the usual private root. Keep the builder real.
    build_layer = renderer_module._build_runtime_layer
    _patch_adapter_construction(monkeypatch)
    monkeypatch.setattr(renderer_module, "_build_runtime_layer", build_layer)
    monkeypatch.setattr(renderer_module, "_query_records", lambda _stage: {})
    monkeypatch.setattr(renderer_module, "_select_runtime_root_path", lambda _scene: root)
    monkeypatch.setenv("OVGEAR_LIVESTREAM", "0")
    layers = []

    def populate(_population, _stage, usda, *, prefix_path):
        layers.append((prefix_path, usda))
        return object()

    monkeypatch.setattr(renderer_module, "_add_runtime_layer", populate)
    if factory == "constructor":
        adapter = renderer_module.OvstageRendererAdapter(**options)
    elif factory == "module":
        adapter = create_renderer_adapter(**options)
    else:
        session = OvstageProviderSession(runtime=object())
        adapter = session.create_renderer(**options)
    try:
        adapter.load_stage(_FakeScene())
        assert adapter.get_active_render_product_path() == root + "/Render/Viewport"
        viewport_layer = next(usda for prefix, usda in layers if prefix == root)
        # This emitted USDA is the population API payload, not source text.
        product = viewport_layer.split('def RenderProduct "Viewport"', 1)[1].split("}", 1)[0]
        assert f"custom int omni:rtx:quality = {quality}" in product
        assert sum(usda.count("omni:rtx:quality") for _, usda in layers) == 1
        # The secondary viewport is preserved without inheriting the primary's quality override.
        secondary = viewport_layer.split('def RenderProduct "ViewportSecondary"', 1)[1].split("}", 1)[0]
        assert "omni:rtx:quality" not in secondary
        assert sum(usda.count("def RenderProduct") for _, usda in layers) == 2
        assert not any(name in usda for _, usda in layers for name in (
            "samplesPerPixel", "samplesPerIteration", "minSpp", "ecoMode",
        ))
    finally:
        adapter.shutdown()


@pytest.mark.parametrize("quality", [-1, 101, 0.5, True, "0", None])
def test_invalid_quality_is_rejected_before_native_renderer_creation(monkeypatch, quality):
    def unexpected_import():
        pytest.fail("invalid quality reached native runtime setup")

    monkeypatch.setattr(renderer_module, "import_ovrtx", unexpected_import)
    with pytest.raises(ValueError, match="viewport_quality must be a plain int from 0 to 100"):
        renderer_module.OvstageRendererAdapter(viewport_quality=quality)
