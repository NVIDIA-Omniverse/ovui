# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compatibility alias for the provider-neutral CUDA channel-swap kernel."""

from __future__ import annotations

import sys

from ovui_data_adapters.common import _swap_kernel as _implementation

sys.modules[__name__] = _implementation
