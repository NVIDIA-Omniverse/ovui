# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

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
