# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Structural protocol for undo managers consumed by data adapters.

Part of ``ovui-data-adapters-common`` — zero-dependency, stdlib-only.

Concrete OpenUSD adapters (added in later refactor steps) need to type
their ``undo_manager`` parameter without importing the concrete
``ovwidgets.common.undo.UndoManager`` class — that import would create
the forbidden ``ovui-data-adapters-openusd -> ovwidgets-common`` edge.

Any object exposing the three group/push methods below satisfies this
protocol. The concrete ``UndoManager`` and ``_NullUndoManager`` classes
in ``ovwidgets.common.undo`` satisfy it structurally; future non-widget
undo backends can satisfy it without importing widget code.
"""

from typing import Protocol, runtime_checkable

from ovui_data_adapters.common._command import Command


@runtime_checkable
class UndoManagerProtocol(Protocol):
    """Structural protocol for undo managers consumed by data adapters."""

    def begin_group(self, label: str) -> None: ...
    def end_group(self) -> None: ...
    def push(self, command: Command) -> None: ...
