# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Capability helpers for Property Inspector affordances."""

from __future__ import annotations

from ovui_data_adapters.common import PropertyAdapter


def adapter_supports_clear_values(adapter: PropertyAdapter) -> bool:
    """Return whether the adapter explicitly supports authored-value clearing."""
    return adapter.get_capabilities().clear_values.is_supported
