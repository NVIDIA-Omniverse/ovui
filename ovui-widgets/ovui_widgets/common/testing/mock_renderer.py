# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Compatibility exports for the migrated mock renderer adapter."""

from ovui_data_adapters.services.testing.mock_renderer import (  # noqa: F401
    FALLBACK_NOTICE_TEXT,
    FALLBACK_NOTICE_TEXT_COLOR,
    _require_numpy,
    _SCENE_SHAPES,
    MockRendererAdapter,
)

__all__ = [
    "FALLBACK_NOTICE_TEXT",
    "FALLBACK_NOTICE_TEXT_COLOR",
    "MockRendererAdapter",
    "_SCENE_SHAPES",
    "_require_numpy",
]
