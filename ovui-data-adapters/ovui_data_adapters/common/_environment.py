# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shared process-environment predicates for adapter and application code."""

from __future__ import annotations

import os


def omniui_headless_enabled() -> bool:
    """Return whether the supported ovui headless mode was requested.

    The standalone headless entrypoint and the full-UI livestream exporter
    define the public contract as exactly ``OMNIUI_HEADLESS=1``.  Keeping this
    predicate shared prevents a renderer from suppressing its windowed stream
    for aliases (for example ``true`` or ``yes``) that do not activate the
    full-UI exporter.
    """

    return os.environ.get("OMNIUI_HEADLESS", "").strip() == "1"
