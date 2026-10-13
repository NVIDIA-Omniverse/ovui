# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

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
