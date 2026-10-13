# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compatibility exports for the migrated mock property adapter."""

from ovui_data_adapters.services.testing.mock_property import (  # noqa: F401
    _is_vector_value,
    _MockPropertySubscription,
    MockPropertyAdapter,
)

__all__ = [
    "MockPropertyAdapter",
    "_MockPropertySubscription",
    "_is_vector_value",
]
