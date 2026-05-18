# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Concrete layer-stack commands (LAYERS-PLAN Step 29).

Three thin :class:`AbstractLayerCommand` subclasses that wrap the
simplest adapter setters so the UI can push them through
:class:`~ovwidgets.common.undo.UndoManager` and pick them up on ``Ctrl+Z``:

- :class:`SetEditTargetCommand` — switch authoring layer. ``do_impl``
  sets the new target; ``undo_impl`` relies on the base class's
  snapshot of the pre-mutation edit target and flips it back.
- :class:`SetLayerMutenessCommand` — toggle local mute on a layer.
  Driven by :class:`~ovwidgets.layers.models.mute_model.LocalMuteValueModel`
  when the user clicks the eye-column icon.
- :class:`SetLayerLockCommand` — toggle the per-layer lock bit.
  Driven by :class:`~ovwidgets.layers.models.lock_model.LockValueModel`
  when the user clicks the padlock column.

Each command stores the identifier plus the target boolean (or, for
:class:`SetEditTargetCommand`, the new layer identifier). The inverse
is derivable — either the stored-negation of the target bit (mute /
lock) or the base class's ``_saved_edit_target`` (edit target). No
other per-command state is needed because the commands represent
idempotent writes that the adapter already no-ops on a matching
value.
"""

from __future__ import annotations

from ovui_data_adapters.common import LayerStackAdapter

from ovwidgets.common.selection import SelectionBus
from ovwidgets.layers.commands.base import AbstractLayerCommand


class SetEditTargetCommand(AbstractLayerCommand):
    """Switch the layer targeted for authoring edits.

    ``do_impl`` calls :meth:`LayerStackAdapter.set_edit_target` with
    the new identifier; ``undo_impl`` calls it with
    :attr:`AbstractLayerCommand._saved_edit_target`, which the base's
    :meth:`~AbstractLayerCommand.do` captured from the adapter on the
    first execution.

    The base class's :meth:`~AbstractLayerCommand._restore_state` also
    restores the edit target after ``undo_impl`` — the second call is
    skipped because ``_restore_state`` first checks
    ``get_edit_target_identifier() != self._saved_edit_target`` and
    we've already reverted it.
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        new_target_identifier: str,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._new_target = new_target_identifier

    def do_impl(self) -> None:
        self._adapter.set_edit_target(self._new_target)

    def undo_impl(self) -> None:
        self._adapter.set_edit_target(self._saved_edit_target)


class SetLayerMutenessCommand(AbstractLayerCommand):
    """Toggle local mute on a single layer.

    ``muted`` is the target state — ``True`` mutes, ``False`` unmutes.
    ``undo_impl`` writes the opposite.

    The adapter's :meth:`~LayerStackAdapter.set_mute` no-ops when the
    bit already matches, so pushing a redundant command is harmless —
    it produces an undo entry with no visible effect. Callers are
    expected to compare before pushing (the value model already does
    this via the click-toggle round-trip).
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        identifier: str,
        muted: bool,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._identifier = identifier
        self._muted = bool(muted)

    def do_impl(self) -> None:
        self._adapter.set_mute(self._identifier, self._muted)

    def undo_impl(self) -> None:
        self._adapter.set_mute(self._identifier, not self._muted)


class SetLayerLockCommand(AbstractLayerCommand):
    """Toggle the per-layer lock bit.

    ``locked`` is the target state — ``True`` locks, ``False`` unlocks.
    ``undo_impl`` writes the opposite.

    Only flips the per-layer bit; the Step 41 recursive-lock gesture
    pushes an undo group of per-descendant commands rather than
    extending this one, so the command stays deliberately narrow.
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        identifier: str,
        locked: bool,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._identifier = identifier
        self._locked = bool(locked)

    def do_impl(self) -> None:
        self._adapter.set_lock(self._identifier, self._locked)

    def undo_impl(self) -> None:
        self._adapter.set_lock(self._identifier, not self._locked)
