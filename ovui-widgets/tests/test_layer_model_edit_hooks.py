# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression coverage for native TreeView edit-transaction hooks."""

from __future__ import annotations

from ovui_widgets.app.testing import MockLayerStackAdapter
from ovui_widgets.layers import LayerModel


def test_layer_model_terminates_native_begin_end_edit_virtual_fallback() -> None:
    assert "begin_edit" in LayerModel.__dict__
    assert "end_edit" in LayerModel.__dict__

    model = LayerModel(MockLayerStackAdapter())
    try:
        assert model.begin_edit(model.root_item) is None
        assert model.end_edit(model.root_item) is None
    finally:
        model.destroy()
