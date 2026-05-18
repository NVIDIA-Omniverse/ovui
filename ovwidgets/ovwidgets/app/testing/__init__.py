# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Testing utilities for OvGear — in-memory adapters and helpers.

Step 9/13 split this package: ``MockBackend`` stays here because it
depends on :mod:`ovwidgets.content.backends`; the other five mocks
moved to :mod:`ovwidgets.common.testing` and are re-exported below
for backward compatibility with consumers that still import
``from ovwidgets.app.testing import MockStageAdapter`` etc.
"""

from ovwidgets.app.testing.mock_backend import MockBackend
from ovwidgets.common.testing.mock_layer_stack import MockLayer, MockLayerStackAdapter
from ovwidgets.common.testing.mock_property import MockPropertyAdapter
from ovwidgets.common.testing.mock_renderer import MockRendererAdapter
from ovwidgets.common.testing.mock_stage import MockStageAdapter
from ovwidgets.common.testing.mock_transform import MockTransformAdapter

__all__ = [
    "MockBackend",
    "MockLayer",
    "MockLayerStackAdapter",
    "MockPropertyAdapter",
    "MockRendererAdapter",
    "MockStageAdapter",
    "MockTransformAdapter",
]
