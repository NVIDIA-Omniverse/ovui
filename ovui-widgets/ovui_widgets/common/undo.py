# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

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
