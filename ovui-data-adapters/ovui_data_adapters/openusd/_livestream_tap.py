# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Compatibility alias for the provider-neutral livestream implementation."""

from __future__ import annotations

import sys

from ovui_data_adapters.common import _livestream_tap as _implementation


# Preserve the historical module as an actual alias, including private helpers
# patched by downstream tests and integrations.
sys.modules[__name__] = _implementation
