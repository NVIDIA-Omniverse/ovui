# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ovwidgets.common.testing — in-memory mock adapters.

Five shared mocks used by both the app's runtime fallback path and
widget-package test suites. ``mock_backend.py`` remains in
:mod:`ovwidgets.app.testing` because it depends on
:mod:`ovwidgets.content.backends`.
"""

from ovwidgets.common.testing.mock_layer_stack import MockLayer, MockLayerStackAdapter
from ovwidgets.common.testing.mock_property import MockPropertyAdapter
from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.common.testing.mock_transform import MockTransformAdapter

__all__ = [
    "MockLayer",
    "MockLayerStackAdapter",
    "MockPropertyAdapter",
    "MockRendererAdapter",
    "MockStageAdapter",
    "MockTransformAdapter",
]
