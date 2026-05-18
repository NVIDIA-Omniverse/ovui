# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Undoable layer-stack mutation commands (LAYERS-PLAN Phase F).

Step 28 lands :class:`AbstractLayerCommand`, the common base every
concrete layer command inherits. Step 29 adds the three simplest
concrete commands:

- :class:`SetEditTargetCommand` — switch authoring layer.
- :class:`SetLayerMutenessCommand` — toggle local mute.
- :class:`SetLayerLockCommand` — toggle the per-layer lock bit.

Step 30 adds the sublayer-manipulation commands:

- :class:`CreateSublayerCommand` — mint a new sublayer.
- :class:`InsertSublayerCommand` — insert an existing layer.
- :class:`RemoveSublayerCommand` — remove a sublayer, with state
  round-trip for mute / lock / edit-target.

Step 31 adds:

- :class:`MoveSublayerCommand` — reorder a sublayer within a parent
  or relocate it across parents, undoable.

Step 31a adds:

- :class:`ReplaceSublayerCommand` — atomically swap a sublayer entry
  at ``(parent, position)`` for a different identifier; used by the
  Save-As-with-replace flow.
- :class:`RemovePrimSpecsCommand` — batch-delete prim specs across
  one or more layers with full snapshot-based undo; used by the
  Del hotkey in the Layers window.

Step 33 adds two non-undoable file-I/O commands:

- :class:`SaveLayerCommand` — persist a layer to disk; clears the
  redo stack but never lands on the undo stack.
- :class:`ReloadLayerCommand` — reload a layer from disk, discarding
  unsaved edits; same non-undoable semantics as Save.

Step 36 adds one partially-undoable save-as command:

- :class:`SaveLayerAsCommand` — export a layer to a new path and
  (optionally) swap every parent's sublayer reference. The file
  write is irreversible but the parent-reference swap is undoable
  — undo restores each captured ``(parent, position)`` to its
  pre-save identifier, while the written file stays on disk.

See LAYERS-WINDOW-ARCHITECTURE §13 for the design rationale and
LAYERS-PLAN Step 28 / 29 / 30 / 31 / 31a / 33 / 36 for the
implementation contract.
"""

from ovwidgets.layers.commands.base import (
    LAYERS_COMMAND_SOURCE,
    LAYERS_UNDO_SOURCE,
    AbstractLayerCommand,
)
from ovwidgets.layers.commands.file_io_commands import (
    ReloadLayerCommand,
    SaveLayerAsCommand,
    SaveLayerCommand,
)
from ovwidgets.layers.commands.layer_commands import (
    SetEditTargetCommand,
    SetLayerLockCommand,
    SetLayerMutenessCommand,
)
from ovwidgets.layers.commands.merge_flatten_commands import (
    FlattenSublayersCommand,
    MergeDownCommand,
)
from ovwidgets.layers.commands.sublayer_commands import (
    CreateSublayerCommand,
    InsertSublayerCommand,
    MoveSublayerCommand,
    RemovePrimSpecsCommand,
    RemoveSublayerCommand,
    ReplaceSublayerCommand,
)

__all__ = [
    "AbstractLayerCommand",
    "CreateSublayerCommand",
    "FlattenSublayersCommand",
    "InsertSublayerCommand",
    "LAYERS_COMMAND_SOURCE",
    "LAYERS_UNDO_SOURCE",
    "MergeDownCommand",
    "MoveSublayerCommand",
    "ReloadLayerCommand",
    "RemovePrimSpecsCommand",
    "RemoveSublayerCommand",
    "ReplaceSublayerCommand",
    "SaveLayerAsCommand",
    "SaveLayerCommand",
    "SetEditTargetCommand",
    "SetLayerLockCommand",
    "SetLayerMutenessCommand",
]
