# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""File-I/O layer commands (LAYERS-PLAN Step 33, Step 36).

Save-to-disk and reload-from-disk gestures that run through the
command pipeline so they inherit injected error reporting,
selection-snapshot capture, and confirmation guards.

- :class:`SaveLayerCommand` — non-undoable. Persist a layer to disk
  via :meth:`~ovui_data_adapters.common.LayerStackAdapter.save_layer`. On
  :class:`IOError` / :class:`PermissionError` the exception is
  surfaced through an injected reporter and swallowed — the adapter
  keeps the layer's dirty bit set so the row still offers a retry
  affordance.
- :class:`ReloadLayerCommand` — non-undoable. Reload a layer from
  disk, discarding unsaved edits. Callers are expected to have
  already confirmed with the user (Step 37 dirty-reload prompt)
  before pushing this command.
- :class:`SaveLayerAsCommand` (Step 36) — **partially** undoable. The
  file write itself is irreversible (undo does not delete the saved
  file), but when ``replace_in_parent=True`` the parent-sublayer
  reference swap **is** reversible: undo walks the captured parent
  entries and restores each one to the pre-save identifier. Redo
  re-applies the parent swap without rewriting the file — a second
  :meth:`~ovui_data_adapters.common.LayerStackAdapter.save_layer_as` would
  fail because the path already exists on disk.

:class:`SaveLayerCommand` and :class:`ReloadLayerCommand` set
:attr:`~ovui_data_adapters.services.undo.Command.non_undoable` to ``True``.
:meth:`~ovui_data_adapters.services.undo.UndoManager.push` honours this marker by
executing :meth:`~ovui_data_adapters.services.undo.Command.do`, clearing the redo stack,
and skipping the undo-stack append. Matches the standard DCC
convention: after Save or Reload the user never sees an "Undo Save"
entry in the history menu.

See LAYERS-PLAN Step 33 / Step 36 for the full design contract and
LAYERS-WINDOW-ARCHITECTURE §13 for the command-pipeline rationale.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

from ovui_data_adapters.common import LayerStackAdapter

from ovui_data_adapters.services.layers.commands.base import AbstractLayerCommand
from ovui_data_adapters.services.selection import SelectionBus
from ovui_data_adapters.services.undo import CommandCancelled


class SaveLayerCommand(AbstractLayerCommand):
    """Save ``identifier`` to disk; non-undoable.

    ``do_impl`` forwards to
    :meth:`~ovui_data_adapters.common.LayerStackAdapter.save_layer`. A
    :class:`IOError` / :class:`PermissionError` raised by the adapter
    (disk full, read-only filesystem, nucleus auth failure) is caught,
    reported via ``error_reporter.show_error(...)``, and swallowed —
    the layer's dirty bit stays set and the row's floppy affordance
    continues to invite a retry. An adapter returning ``False``
    (anonymous or missing layer) surfaces the same error path.

    Because :attr:`non_undoable` is ``True``, the base class's
    :meth:`~AbstractLayerCommand.undo_impl` is never called in
    practice; it is defined as a no-op to satisfy the ABC and guard
    against a caller that invokes ``undo`` directly without routing
    through :class:`~ovui_data_adapters.services.undo.UndoManager`.
    """

    non_undoable = True

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        identifier: str,
        error_reporter: Optional[Any] = None,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._identifier = identifier
        self._reporter = error_reporter

    def do_impl(self) -> None:
        try:
            ok = self._adapter.save_layer(self._identifier)
        except (IOError, PermissionError) as exc:
            self._report_error(
                f"Save of {self._identifier} failed: {exc}"
            )
            return
        if not ok:
            self._report_error(
                f"Save of {self._identifier} failed."
            )

    def undo_impl(self) -> None:
        # ``non_undoable = True`` — UndoManager.push never pushes this
        # onto the undo stack, so undo is effectively unreachable.
        # Defined as a no-op so a direct ``cmd.undo()`` call from a
        # test or misuse does not blow up with ``NotImplementedError``.
        return

    def _report_error(self, message: str) -> None:
        reporter = self._resolve_reporter()
        if reporter is None:
            return
        try:
            reporter.show_error(message)
        except Exception:
            # The reporter is a visual nicety; never let a UI failure
            # mask the underlying save-failure signal the caller may
            # be watching for.
            pass

    def _resolve_reporter(self) -> Any:
        if self._reporter is not None:
            return self._reporter
        return None


class ReloadLayerCommand(AbstractLayerCommand):
    """Reload ``identifier`` from disk; non-undoable.

    ``do_impl`` forwards to
    :meth:`~ovui_widgets.common.adapters.LayerStackAdapter.reload_layer`, which
    discards the in-memory edits for the layer and replays the disk
    contents. A :class:`IOError` / :class:`PermissionError` from the
    adapter is caught and reported via ``error_reporter.show_error(...)``.

    Reload throws away user work by design, so callers are expected
    to have already prompted the user (LAYERS-PLAN Step 37's
    dirty-reload confirm dialog) before pushing this command. The
    dialog lives upstream of the push so the command body stays
    focused on the adapter call.

    As with :class:`SaveLayerCommand`, :attr:`non_undoable` is
    ``True`` and :meth:`undo_impl` is a no-op.
    """

    non_undoable = True

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        identifier: str,
        error_reporter: Optional[Any] = None,
        confirm_callback: Optional[Callable[[str], bool]] = None,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._identifier = identifier
        self._reporter = error_reporter
        # LAYERS-PLAN Step 37 guard hook. Mirrors
        # :class:`RemoveSublayerCommand`: a ``False`` return from
        # ``confirm_callback(identifier)`` short-circuits the push
        # via :class:`~ovui_data_adapters.services.undo.CommandCancelled`. A reload on a
        # dirty layer throws away in-memory edits, so the prompt is
        # the same "about to lose work" gate the remove-dirty flow
        # uses. Left ``None`` for callers that have already confirmed
        # upstream (e.g. headless tests, toolbar flows that gate
        # themselves).
        self._confirm_callback = confirm_callback

    def do_impl(self) -> None:
        if self._confirm_callback is not None:
            if not self._confirm_callback(self._identifier):
                raise CommandCancelled()
        try:
            self._adapter.reload_layer(self._identifier)
        except (IOError, PermissionError) as exc:
            self._report_error(
                f"Reload of {self._identifier} failed: {exc}"
            )

    def undo_impl(self) -> None:
        # ``non_undoable = True`` — see SaveLayerCommand.undo_impl.
        return

    def _report_error(self, message: str) -> None:
        reporter = self._resolve_reporter()
        if reporter is None:
            return
        try:
            reporter.show_error(message)
        except Exception:
            pass

    def _resolve_reporter(self) -> Any:
        if self._reporter is not None:
            return self._reporter
        return None


class SaveLayerAsCommand(AbstractLayerCommand):
    """Save ``source_identifier`` to ``new_path``; optionally swap parents.

    Step 36 — opened from the save-as file-picker flow for anonymous
    layers (and, in a future step, from a "Save As…" context-menu
    entry on concrete layers). The command bundles two operations:

    1. **File write** via
       :meth:`~ovui_data_adapters.common.LayerStackAdapter.save_layer_as`
       with ``replace_in_parent=False`` so the adapter writes the
       file but does not touch parent sublayer paths. The write
       happens exactly once (first :meth:`do`); a redo re-applies
       only the parent-reference swaps so it does not collide with
       the file the first ``do`` already created on disk.
    2. **Parent-reference swap** (only when
       :attr:`_replace_in_parent` is ``True``): every parent that
       currently references ``source_identifier`` is rewritten to
       point at the newly-exported identifier via
       :meth:`~ovui_data_adapters.common.LayerStackAdapter.replace_sublayer`.
       The ``(parent_id, position, old_identifier)`` triples are
       captured on first do so undo can restore them.

    Undo semantics
    --------------

    The file on disk **is not removed** — undo restores every captured
    parent reference back to the pre-save identifier (typically the
    anonymous source) but the saved file stays where the user asked
    for it. This matches LAYERS-PLAN finding M5: undoing a save is
    surprising precisely because the file is real data the user
    probably wants to keep. If the user wants the file gone, they
    delete it through the filesystem.

    Failure handling
    ----------------

    If :meth:`~ovui_data_adapters.common.LayerStackAdapter.save_layer_as`
    returns ``None`` (write failed — bad path, permission denied, or
    the path already resolves to an existing layer), the command
    leaves ``_new_identifier`` unset, skips the parent-swap pass, and
    reports the failure through an injected reporter. A subsequent
    ``undo`` is therefore a no-op (``_parent_swaps`` stays empty);
    the user sees the error and re-runs the save-as with a different
    path.
    """

    def __init__(
        self,
        adapter: LayerStackAdapter,
        selection_bus: SelectionBus,
        source_identifier: str,
        new_path: str,
        replace_in_parent: bool = True,
        error_reporter: Optional[Any] = None,
    ) -> None:
        super().__init__(adapter, selection_bus)
        self._source_identifier = source_identifier
        self._new_path = new_path
        self._replace_in_parent = replace_in_parent
        self._reporter = error_reporter

        # Populated on first ``do``: the identifier the adapter minted
        # for the exported layer (``new_path`` in USD, or the
        # ``new_path`` argument directly for mock adapters).
        self._new_identifier: Optional[str] = None

        # Captured on first ``do`` — every parent that referenced
        # ``source_identifier`` before the swap, as
        # ``(parent_id, position, old_identifier)``. Redo replays the
        # swaps in order; undo restores the old identifier in reverse
        # order so a same-parent duplicate sublayer (USD allows this)
        # reverts cleanly.
        self._parent_swaps: List[Tuple[str, int, str]] = []

        # Guards against a redo re-invoking ``save_layer_as`` (the
        # adapter would fail because the path now resolves to an
        # existing layer). First-do flips this to ``True``.
        self._file_written: bool = False

    def do_impl(self) -> None:
        if not self._file_written:
            try:
                minted = self._adapter.save_layer_as(
                    self._source_identifier,
                    self._new_path,
                    replace_in_parent=False,
                )
            except (IOError, PermissionError) as exc:
                self._report_error(
                    f"Save-As of {self._source_identifier} failed: {exc}"
                )
                return
            if minted is None:
                self._report_error(
                    f"Save-As of {self._source_identifier} to "
                    f"{self._new_path!r} failed."
                )
                return
            self._new_identifier = minted
            self._file_written = True
            if self._replace_in_parent:
                self._collect_parent_swaps()

        if not self._replace_in_parent or self._new_identifier is None:
            return
        for parent_id, position, _old in self._parent_swaps:
            self._adapter.replace_sublayer(
                parent_id, position, self._new_identifier,
            )

    def undo_impl(self) -> None:
        if not self._replace_in_parent:
            return
        # Reverse order so a parent that referenced the source layer
        # twice (legal in USD) rewinds cleanly — the last swap
        # overwrote the earliest, and undoing last-first puts them
        # back in original order.
        for parent_id, position, old_identifier in reversed(
            self._parent_swaps
        ):
            self._adapter.replace_sublayer(
                parent_id, position, old_identifier,
            )

    def _collect_parent_swaps(self) -> None:
        """Capture every ``(parent, position)`` pointing at the source.

        Walks every resident layer (session included, anonymous
        included — an anonymous parent can still hold sublayer
        references in USD) and records each index whose sublayer
        identifier equals :attr:`_source_identifier`. The list is then
        replayed by :meth:`do_impl` and reversed by :meth:`undo_impl`.
        """
        identifiers = self._adapter.get_layer_stack_identifiers(
            include_session=True,
            include_anonymous=True,
        )
        for ident in identifiers:
            handle = self._adapter.find_layer(ident)
            if handle is None:
                continue
            sublayer_ids = self._adapter.get_sublayer_identifiers(handle)
            for idx, child_id in enumerate(sublayer_ids):
                if child_id == self._source_identifier:
                    self._parent_swaps.append(
                        (ident, idx, self._source_identifier)
                    )

    def _report_error(self, message: str) -> None:
        reporter = self._resolve_reporter()
        if reporter is None:
            return
        try:
            reporter.show_error(message)
        except Exception:
            pass

    def _resolve_reporter(self) -> Any:
        if self._reporter is not None:
            return self._reporter
        return None
