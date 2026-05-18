# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Abstract command contract for the undo/redo machinery.

Part of ``ovui-data-adapters-common`` — zero-dependency, stdlib-only.

This module hosts the canonical ``Command`` ABC. ``ovwidgets.common.undo``
re-exports the same class object so both
``from ovwidgets.common.undo import Command`` and
``from ovui_data_adapters.common import Command`` resolve to the identical
class. Concrete OpenUSD command implementations in
``ovui_data_adapters.openusd`` will inherit from this class without
importing widget-side modules.
"""

from abc import ABC, abstractmethod


class Command(ABC):
    """Base class for undoable commands."""

    # Subclasses that represent one-way operations (save, reload, etc.)
    # flip this to ``True`` so :meth:`UndoManager.push` executes the
    # command but does not enqueue it on the undo stack — instead the
    # redo stack is cleared. This keeps file-I/O commands in the
    # command pipeline (uniform error reporting, selection snapshot,
    # dialog guards) without producing a user-confusing "Undo Save"
    # entry. See LAYERS-PLAN Step 33.
    non_undoable: bool = False

    @abstractmethod
    def do(self) -> None:
        """Execute the command."""

    @abstractmethod
    def undo(self) -> None:
        """Reverse the command."""

    def redo(self) -> None:
        """Re-execute. Default delegates to do()."""
        self.do()
