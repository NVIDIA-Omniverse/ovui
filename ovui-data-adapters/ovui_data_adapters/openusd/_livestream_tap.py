# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compatibility alias for the provider-neutral livestream implementation."""

from __future__ import annotations

import sys

from ovui_data_adapters.common import _livestream_tap as _implementation


# Preserve the historical module as an actual alias, including private helpers
# patched by downstream tests and integrations.
sys.modules[__name__] = _implementation
