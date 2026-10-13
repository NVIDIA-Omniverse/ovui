# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Reusable frontend-neutral adapter test doubles.

These mocks exercise the public adapter/service contracts without importing
``ovui_widgets``, ``omni.ui``, application runtime glue, or concrete USD/GPU
backends. ``MockRendererAdapter`` keeps its ``numpy`` dependency lazy so the
testing package remains importable in a minimal services install.
"""

from ovui_data_adapters.services.testing.mock_backend import MockBackend
from ovui_data_adapters.services.testing.mock_layer_stack import (
    MockLayer,
    MockLayerStackAdapter,
    ROOT_LAYER_IDENTIFIER,
    SESSION_LAYER_IDENTIFIER,
)
from ovui_data_adapters.services.testing.mock_property import MockPropertyAdapter
from ovui_data_adapters.services.testing.mock_renderer import MockRendererAdapter
from ovui_data_adapters.services.testing.mock_stage import MockStageAdapter
from ovui_data_adapters.services.testing.mock_transform import MockTransformAdapter

__all__ = [
    "MockBackend",
    "MockLayer",
    "MockLayerStackAdapter",
    "MockPropertyAdapter",
    "MockRendererAdapter",
    "MockStageAdapter",
    "MockTransformAdapter",
    "ROOT_LAYER_IDENTIFIER",
    "SESSION_LAYER_IDENTIFIER",
]
