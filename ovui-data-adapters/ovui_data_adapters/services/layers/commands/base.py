# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Common base class for undoable layer-stack mutations (LAYERS-PLAN Step 28).

:class:`AbstractLayerCommand` owns the parts of the layer-command
contract that every concrete command in :mod:`ovui_widgets.layers.commands`
shares:

- Snapshot the edit target + :class:`~ovui_widgets.common.selection.SelectionBus`
  selection **on the first ``do``** so the next ``undo`` can restore
  them. The snapshot is taken exactly once per command instance — see
  :meth:`AbstractLayerCommand.redo`.
- Restore the edit target and selection on ``undo`` **in the correct
  order**: edit target first, selection second. Downstream subscribers
  (Layers tree expand, Property panel) that react to the selection
  event then see the restored authoring layer when they look at the
  adapter (LAYERS-WINDOW-ARCHITECTURE §13.1).
- Publish the undo-phase bus event with a namespaced ``source`` string
  (:data:`LAYERS_UNDO_SOURCE`) so subscribers can tell an undo-driven
  update apart from a user-driven one and short-circuit (Step 57's
  ``LayerSelectionWatch`` is the first such subscriber).
- Defer per-command state restoration to the undo-group wrapper
  (Step 28.5) via :attr:`_suppress_state_restore` so an N-command group
  fires one restore rather than N.

Concrete commands (SetEditTargetCommand, CreateSublayerCommand, ...)
subclass this type and override :meth:`do_impl` / :meth:`undo_impl`
for the actual adapter calls. Step 29 onwards lands the first batch.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Tuple

from ovui_data_adapters.common import LayerStackAdapter

from ovui_data_adapters.services.selection import SelectionBus, SelectionBusError
from ovui_data_adapters.services.undo import Command

LAYERS_COMMAND_SOURCE = "ovui_widgets.layers:command"
"""Namespace for :class:`SelectionBus` events published during a
layer command's do-phase.

Available to subclasses that publish during :meth:`~AbstractLayerCommand.do_impl`
(none do so today; the constant is exported up front because several
of the concrete commands in Steps 29-33 will adopt it).
"""

LAYERS_UNDO_SOURCE = "ovui_widgets.layers:undo"
"""Namespace for :class:`SelectionBus` events published during the
undo-phase selection restore.

Listed as an explicit constant (rather than an ad-hoc ``"undo"`` string)
so :class:`~ovui_widgets.layers.window.LayerSelectionWatch` (Step 57) can
identify bus events originating from a layer undo and short-circuit
its own repaint without ambiguity against the generic ``"undo"``
sources used elsewhere.
"""


class AbstractLayerCommand(Command):
    """Base class for every undoable layer-stack mutation.

    Subclasses implement :meth:`do_impl` / :meth:`undo_impl`; this base
    class owns pre-mutation state capture, restoration ordering, the
    namespaced undo source string, and undo-group awareness.
    """

    # Flipped to ``True`` by the undo-group wrapper (Step 28.5) for
    # every command pushed while a group is open. The group's own
    # ``undo`` calls :meth:`_restore_state` exactly once after every
    # inner ``undo_impl`` has run, so an N-command group produces a
    # single edit-target + selection restore instead of N.
    #
    # Declared at the class level so mypy and subclass overrides see
    # the attribute; concrete instances receive their own value via
    # ``cmd._suppress_state_restore = True`` at the group seam.
    _suppress_state_restore: bool = False

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
    ) -> None:
        self._adapter = adapter
        self._bus = selection_bus
        self._saved_edit_target: str = ""
        self._saved_selection: Tuple[str, ...] = ()
        self._state_snapshotted: bool = False

    # ── Command ABC overrides ────────────────────────────────────────

    def do(self) -> None:
        """Snapshot pre-mutation state on the first call, then mutate.

        The snapshot is gated on :attr:`_state_snapshotted` so a
        subsequent ``redo`` (which routes through :meth:`redo`, not
        back through ``do``) keeps the original "before" state — the
        next ``undo`` must still restore to the state from *before* the
        very first execution, not the post-undo state that a naive
        ``redo = do`` would capture.
        """
        if not self._state_snapshotted:
            self._saved_edit_target = (
                self._adapter.get_edit_target_identifier()
            )
            self._saved_selection = tuple(self._bus.get_snapshot().paths())
            self._state_snapshotted = True
        self.do_impl()

    def redo(self) -> None:
        """Re-execute without re-snapshotting.

        Overrides :meth:`Command.redo` (default delegates to ``do``)
        because re-snapshotting after an undo would capture the
        post-undo state as the new "before" — the following ``undo``
        would then restore to that wrong snapshot.
        """
        self.do_impl()

    def undo(self) -> None:
        """Reverse the mutation, then restore pre-mutation state.

        When the command is part of an undo group
        (:attr:`_suppress_state_restore` set by the group wrapper), the
        per-command restore is skipped — the group runs a single
        :meth:`_restore_state` after the whole batch has undone.
        """
        self.undo_impl()
        if self._suppress_state_restore:
            return
        self._restore_state()

    # ── Hooks for subclasses ─────────────────────────────────────────

    @abstractmethod
    def do_impl(self) -> None:
        """Perform the mutation. Called by :meth:`do` and :meth:`redo`."""

    @abstractmethod
    def undo_impl(self) -> None:
        """Reverse the mutation. Called by :meth:`undo` before state restore."""

    # ── State restoration ────────────────────────────────────────────

    def _restore_state(self) -> None:
        """Restore edit target + selection to the pre-mutation snapshot.

        Ordering is load-bearing: edit target **first**, selection
        **second**. Downstream subscribers to the selection event
        (LayersTreeExpand, Property panel) read the adapter's edit
        target when they react to the event — doing it the other way
        round leaves them looking at stale authoring-layer state for
        one event cycle.

        The edit-target restore is skipped when the saved layer no
        longer exists or is no longer writable (an earlier command in
        a mixed sequence may have removed or locked it). The selection
        restore is skipped when the current selection already matches
        the snapshot — a redundant publish would wake every subscriber
        for nothing.

        A :class:`~ovui_widgets.common.selection.SelectionBusError` on publish means
        the bus is currently mid-dispatch; see the commented rationale
        inside — losing one restore is acceptable because the next
        user-driven event re-queries adapter state anyway.
        """
        target_handle = self._adapter.find_layer(self._saved_edit_target)
        if (
            target_handle is not None
            and self._adapter.is_writable(target_handle)
            and self._adapter.get_edit_target_identifier()
            != self._saved_edit_target
        ):
            self._adapter.set_edit_target(self._saved_edit_target)

        current = tuple(self._bus.get_snapshot().paths())
        if current != self._saved_selection:
            try:
                self._bus.publish(
                    list(self._saved_selection),
                    source=LAYERS_UNDO_SOURCE,
                )
            except SelectionBusError:
                # Bus is currently mid-publish — re-entering would
                # violate the bus's reentrancy guard. Dropping one
                # restore is acceptable because the next user-driven
                # event causes subscribers to re-query adapter state.
                pass
