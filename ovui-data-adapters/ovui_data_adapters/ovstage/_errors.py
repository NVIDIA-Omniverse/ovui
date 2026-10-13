# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared unavailable-feature signal for the ovstage scaffold."""

from __future__ import annotations

from typing import NoReturn


def raise_not_ready(feature: str) -> NoReturn:
    raise NotImplementedError(
        f"ovstage adapter scaffold: {feature} is not implemented yet"
    )
