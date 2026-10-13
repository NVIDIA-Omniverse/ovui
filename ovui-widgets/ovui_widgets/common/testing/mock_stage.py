# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compatibility exports for the migrated mock stage adapter."""

from ovui_data_adapters.services.testing.mock_stage import (  # noqa: F401
    _MockItem,
    MockStageAdapter,
)

__all__ = ["MockStageAdapter", "_MockItem"]
