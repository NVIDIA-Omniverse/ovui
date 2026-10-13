# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Compatibility exports for undo / command / history behavior.

The canonical undo stack implementation lives in
``ovui_data_adapters.services.undo``. This module preserves the historical
``ovui_widgets.common.undo`` import path.

``BatchTransformCommand`` is part of the transform operation command service
and is re-exported here to preserve the historical import path.
"""

from __future__ import annotations

from ovui_data_adapters.services.undo import (
    Command,
    CommandCancelled,
    UndoGroup,
    UndoManager,
    UndoManagerProtocol,
)
from ovui_data_adapters.services.transforms import BatchTransformCommand


__all__ = [
    "BatchTransformCommand",
    "Command",
    "CommandCancelled",
    "UndoGroup",
    "UndoManager",
    "UndoManagerProtocol",
]
