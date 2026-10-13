# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Entry-point registration for the OpenUSD data-adapter provider."""

from __future__ import annotations

from typing import Any

from ovui_data_adapters.openusd.provider import build_factories


def register(registry: Any) -> None:
    registry.register_adapter(
        name="openusd",
        priority=0,
        requirements=("openusd",),
        factories=build_factories(),
    )
