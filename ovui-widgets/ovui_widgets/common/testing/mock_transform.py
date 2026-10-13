# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compatibility exports for the migrated mock transform adapter."""

from ovui_data_adapters.services.testing.mock_transform import (  # noqa: F401
    _IDENTITY,
    MockTransformAdapter,
)

__all__ = ["MockTransformAdapter", "_IDENTITY"]
