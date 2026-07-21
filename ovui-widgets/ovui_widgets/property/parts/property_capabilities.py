# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Capability helpers for Property Inspector affordances."""

from __future__ import annotations

from ovui_data_adapters.common import PropertyAdapter


def adapter_supports_clear_values(adapter: PropertyAdapter) -> bool:
    """Return whether the adapter explicitly supports authored-value clearing."""
    return adapter.get_capabilities().clear_values.is_supported
