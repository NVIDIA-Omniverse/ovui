# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
"""RenderVar outputs are discoverable before any product is configured."""

import pytest

pytest.importorskip("pxr")
from ovui_data_adapters.openusd import renderer_adapter as module
from ovui_data_adapters.openusd.renderer_adapter import OvRtxRendererAdapter


def test_every_recognized_output_has_a_canonical_source_name():
    outputs = OvRtxRendererAdapter.supported_render_var_outputs()
    names = [o["source_name"] for o in outputs]
    assert names[0] == "LdrColor" and not outputs[0]["sensor"]
    recognized = {module._source_token_key(n) for n in names[1:]}
    assert recognized == set(module._RENDER_VAR_OUTPUT_SPECS)
    assert {"DistanceToCameraSD", "SemanticSegmentation", "HdrColor"} <= set(names)
    assert all(o["sensor"] for o in outputs[1:])


@pytest.mark.parametrize(
    "name, canonical",
    [("DistanceToCameraSD", "DistanceToCameraSD"), ("distancetocamerasd", "DistanceToCameraSD"),
     ("LdrColor", "LdrColor"), ("DepthLinear", None), ("BogusVar", None)],
)
def test_supported_render_var_lookup(name, canonical):
    assert OvRtxRendererAdapter.supported_render_var_name(name) == canonical
