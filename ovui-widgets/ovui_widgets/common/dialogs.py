# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Modal confirmation dialogs for OvGear (LAYERS-PLAN Step 37).

Two-button "confirm / cancel" and three-button "save+action / action /
cancel" prompts for destructive gestures:

- :func:`confirm_dialog` — generic two-button prompt. Shown before any
  irreversible-but-undoable mutation when the user might want to back
  out (currently powers the dirty-reload guard).
- :func:`confirm_dirty_remove_dialog` — three-button variant used before
  removing a layer with unsaved edits. The third button (**Save &
  Remove**) lets the user rescue the edits without aborting the remove.
- :func:`confirm_reload_dialog` — thin wrapper around
  :func:`confirm_dialog` with Reload/Cancel labels.
- :func:`confirm_unsaved_exit_dialog` — three-button variant used before
  File > Exit closes an application whose layers have unsaved edits.
- :func:`message_dialog` — one-button modal that tells the user about a
  fallback that needs no choice (a settings file that did not load).

All dialogs follow the same async-callback pattern
:mod:`ovui_widgets.common.file_dialogs` introduced in Step 36: ovui does not ship a
true blocking modal, so the dialog opens, the helper returns, and the
user's click fires ``on_confirm`` / ``on_cancel`` / ``on_save_confirm``
in a later tick. Callers that need a blocking semantics (e.g. a command
whose ``do`` must short-circuit on cancel) run the dialog *before*
pushing the command and branch on the callback.

Module-level :data:`_OPEN_DIALOGS` keeps the window wrappers reachable
for the duration of the interaction — without it, ovui's Python
``Window`` object would be garbage-collected as soon as the helper
returned and the dialog would disappear mid-interaction. Each dialog
self-removes from the registry on dismissal so GC can reclaim it once
the user has clicked.
"""

from __future__ import annotations

from typing import Callable, List, Optional

import omni.ui as ui

_OPEN_DIALOGS: List["_ConfirmDialogBase"] = []


def confirm_dialog(
    title: str,
    message: str,
    on_confirm: Callable[[], None],
    on_cancel: Optional[Callable[[], None]] = None,
    confirm_label: str = "OK",
    cancel_label: str = "Cancel",
) -> Optional["_ConfirmDialog"]:
    """Open a two-button modal confirmation dialog.

    Parameters
    ----------
    title:
        Window title. Kept short — a long title overflows ovui's title
        bar on a narrow dock layout.
    message:
        Body text. Rendered as a single :class:`ui.Label`; newlines
        inside ``message`` are honoured by ovui's label rendering.
    on_confirm:
        Invoked with no arguments when the user clicks the confirm
        button. The dialog closes *before* the callback fires so a
        long-running mutation does not freeze window tear-down.
    on_cancel:
        Invoked with no arguments when the user clicks Cancel or
        closes the window via the title-bar close affordance. Optional
        — a no-op default is used when ``None``.
    confirm_label, cancel_label:
        Button labels. Default to generic OK/Cancel; callers supply
        action-specific verbs (e.g. "Reload", "Remove") so the user
        reads what they're committing to instead of an abstract OK.

    Returns
    -------
    The dialog object on success, ``None`` if ovui refused to build
    the window (headless / event-loop-not-initialised). On ``None``
    the ``on_cancel`` callback has already fired so callers can treat
    the return value as a binary "dialog shown?" signal.
    """
    on_cancel_effective = on_cancel or (lambda: None)
    try:
        dialog = _ConfirmDialog(
            title=title,
            message=message,
            on_confirm=on_confirm,
            on_cancel=on_cancel_effective,
            confirm_label=confirm_label,
            cancel_label=cancel_label,
        )
    except Exception:
        on_cancel_effective()
        return None
    _OPEN_DIALOGS.append(dialog)
    return dialog


def confirm_dirty_remove_dialog(
    layer_name: str,
    on_save_and_remove: Callable[[], None],
    on_remove_without_saving: Callable[[], None],
    on_cancel: Optional[Callable[[], None]] = None,
    dirty_layer_names: Optional[List[str]] = None,
) -> Optional["_ConfirmDirtyRemoveDialog"]:
    """Open a three-button modal before removing a dirty layer.

    The three branches mirror the LAYERS-PLAN Step 37 contract:

    - **Save & Remove** → ``on_save_and_remove`` — save the layer to
      disk first, then remove it from the parent stack. The caller
      typically wraps both mutations in an undo group so Undo restores
      the sublayer reference (the save itself is non-undoable).
    - **Remove Without Saving** → ``on_remove_without_saving`` —
      discard the in-memory edits; remove immediately.
    - **Cancel** → ``on_cancel`` — abort; the layer stays dirty and
      remains in the parent stack.

    ``layer_name`` is interpolated into the message text so the user
    sees *which* layer is at risk. ``dirty_layer_names`` lists the
    layers of the removed tree that have unsaved changes; when it
    names a layer other than ``layer_name`` (a nested sublayer), the
    message lists them all.

    The dialog closes before any callback fires so a slow save path
    does not race the window tear-down.
    """
    on_cancel_effective = on_cancel or (lambda: None)
    try:
        dialog = _ConfirmDirtyRemoveDialog(
            layer_name=layer_name,
            on_save_and_remove=on_save_and_remove,
            on_remove_without_saving=on_remove_without_saving,
            on_cancel=on_cancel_effective,
            dirty_layer_names=dirty_layer_names,
        )
    except Exception:
        on_cancel_effective()
        return None
    _OPEN_DIALOGS.append(dialog)
    return dialog


def confirm_reload_dialog(
    layer_name: str,
    on_reload: Callable[[], None],
    on_cancel: Optional[Callable[[], None]] = None,
) -> Optional["_ConfirmDialog"]:
    """Open a two-button modal before reloading a dirty layer.

    Thin wrapper around :func:`confirm_dialog` that pre-fills the
    title and message with the standard "reload discards unsaved
    edits" warning. Kept as a separate helper so call sites stay
    declarative ("I want the reload prompt") rather than duplicating
    the warning text.
    """
    return confirm_dialog(
        title="Reload Layer",
        message=(
            f"Reload will discard unsaved changes to "
            f"{layer_name!r}.\nContinue?"
        ),
        on_confirm=on_reload,
        on_cancel=on_cancel,
        confirm_label="Reload",
        cancel_label="Cancel",
    )


def confirm_unsaved_exit_dialog(
    layer_names: List[str],
    on_save_and_exit: Callable[[], None],
    on_exit_without_saving: Callable[[], None],
    on_cancel: Optional[Callable[[], None]] = None,
) -> Optional["_ConfirmUnsavedExitDialog"]:
    """Open a three-button modal before an exit drops unsaved edits.

    - **Save & Exit** → ``on_save_and_exit`` — save, then exit.
    - **Exit Without Saving** → ``on_exit_without_saving`` — discard the
      in-memory edits and exit.
    - **Cancel** → ``on_cancel`` — the application stays open with its
      edits. A title-bar close of the dialog is also Cancel.

    ``layer_names`` are the modified layers; the message names them so
    the user sees which files are at risk.

    When ovui cannot build the window, the failure is reported and
    ``on_cancel`` fires: the application stays open, so no edit is lost.
    """
    on_cancel_effective = on_cancel or (lambda: None)
    try:
        dialog = _ConfirmUnsavedExitDialog(
            layer_names=layer_names,
            on_save_and_exit=on_save_and_exit,
            on_exit_without_saving=on_exit_without_saving,
            on_cancel=on_cancel_effective,
        )
    except Exception as exc:
        from ovui_widgets.common.error_reporter import ErrorReporter

        ErrorReporter.log_error("Exit", "cannot show the unsaved changes dialog", exc)
        ErrorReporter.show_error(
            f"Cannot show the unsaved changes dialog: {type(exc).__name__}: {exc}"
        )
        on_cancel_effective()
        return None
    _OPEN_DIALOGS.append(dialog)
    return dialog


def message_dialog(title: str, message: str) -> Optional["_MessageDialog"]:
    """Open a one-button modal that tells the user something.

    The **OK** button, Enter, keypad Enter, Escape and a title-bar close all
    close the dialog. A long message scrolls; the OK button stays visible.
    When ovui cannot build the window, the failure and the full message go to
    stderr, and the message goes to the status bar (which shows only its
    start), so the user still sees it.
    """
    try:
        dialog = _MessageDialog(title=title, message=message)
    except Exception as exc:
        from ovui_widgets.common.error_reporter import ErrorReporter

        ErrorReporter.log_error(
            "Dialog", f"cannot show the dialog {title!r}: {message}", exc
        )
        ErrorReporter.show_warning(message, duration_ms=0)
        return None
    _OPEN_DIALOGS.append(dialog)
    return dialog


def confirm_merge_down_dialog(
    source_name: str,
    destination_name: str,
    on_merge: Callable[[], None],
    on_cancel: Optional[Callable[[], None]] = None,
) -> Optional["_ConfirmDialog"]:
    """Open a two-button modal before merging one layer into another.

    LAYERS-PLAN Step 42 — the Merge Down gesture is destructive: the
    source layer is removed from the tree and its opinions are folded
    into the destination. Undo round-trips via the snapshot/restore
    API on the adapter, but the message still warns the user so a
    mis-click doesn't silently rewrite the destination layer.

    Thin wrapper around :func:`confirm_dialog`; keeps the warning text
    in one place so a future style refresh touches a single helper.
    """
    return confirm_dialog(
        title="Merge Down",
        message=(
            f"Merge Down will copy all opinions from {source_name!r} "
            f"into {destination_name!r} and remove the source layer "
            f"from the tree.\n\n"
            f"This can be undone, but the destination layer will be "
            f"overwritten by the merge. Save any in-progress work on "
            f"the destination first."
        ),
        on_confirm=on_merge,
        on_cancel=on_cancel,
        confirm_label="Merge Down",
        cancel_label="Cancel",
    )


def confirm_flatten_dialog(
    parent_name: str,
    sublayer_count: int,
    on_flatten: Callable[[], None],
    on_cancel: Optional[Callable[[], None]] = None,
) -> Optional["_ConfirmDialog"]:
    """Open a two-button modal before flattening a layer's sublayers.

    LAYERS-PLAN Step 42 — Flatten Sublayers is the most destructive
    gesture in the Layers window: every direct sublayer is folded
    into ``parent_name`` and then removed. Undo restores the tree
    via the per-layer snapshot stash kept on the command, but a
    mis-click would require a Ctrl+Z from the user — the dialog
    makes sure that click is intentional.

    Thin wrapper around :func:`confirm_dialog`; the ``sublayer_count``
    is interpolated into the warning so the user reads *how many*
    layers are about to collapse.
    """
    if sublayer_count == 1:
        noun = "1 sublayer"
    else:
        noun = f"{sublayer_count} sublayers"
    return confirm_dialog(
        title="Flatten Sublayers",
        message=(
            f"Flatten will merge {noun} into {parent_name!r} and "
            f"remove the sublayers from the tree.\n\n"
            f"This can be undone, but overlapping opinions on the "
            f"sublayers will collapse into the parent. Save any "
            f"in-progress work on the sublayers first."
        ),
        on_confirm=on_flatten,
        on_cancel=on_cancel,
        confirm_label="Flatten",
        cancel_label="Cancel",
    )


class _ConfirmDialogBase:
    """Shared window-lifetime plumbing for confirm dialogs.

    Owns the :class:`ui.Window`, the visibility-hook that maps a
    title-bar close to a cancel, the ``_closed`` idempotency latch, and
    the registry entry so every concrete dialog body just declares its
    buttons on top. Subclasses build the inner frame in
    :meth:`_build_body` and trigger :meth:`_close_with_callback` from
    their button handlers.
    """

    def __init__(self, title: str, width: int = 460, height: int = 160) -> None:
        self._closed = False
        self._window = ui.Window(
            title,
            width=width,
            height=height,
            flags=ui.WINDOW_FLAGS_MODAL,
            style_type_name_override="Dialog",
        )
        self._visibility_sub = None
        if hasattr(self._window, "set_visibility_changed_fn"):
            self._window.set_visibility_changed_fn(
                self._on_visibility_changed,
            )

    def _on_visibility_changed(self, visible: bool) -> None:
        if visible or self._closed:
            return
        # Title-bar close counts as cancel. Subclasses override
        # :meth:`_on_window_closed` to fire the cancel callback.
        self._closed = True
        self._remove_from_registry()
        self._on_window_closed()

    def _on_window_closed(self) -> None:
        """Hook — subclass overrides to fire the cancel callback."""

    def _close_with_callback(self, callback: Callable[[], None]) -> None:
        """Hide the window, remove from registry, then invoke ``callback``.

        Guard against the re-entry where ``visible = False`` triggers
        :meth:`_on_visibility_changed` which would otherwise re-invoke
        the cancel path. Flipping :attr:`_closed` *before* we touch
        ``visible`` prevents that second invocation.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._window.visible = False
        except Exception:
            # Window may already be torn down — harmless; fall through
            # to the callback so the caller's logic still runs.
            pass
        self._remove_from_registry()
        callback()

    def _remove_from_registry(self) -> None:
        if self in _OPEN_DIALOGS:
            _OPEN_DIALOGS.remove(self)


class _ConfirmDialog(_ConfirmDialogBase):
    """Private helper — two-button ``ui.Window``-backed confirm modal.

    Test helpers :meth:`confirm` and :meth:`cancel` drive the click
    handlers without mouse plumbing.
    """

    def __init__(
        self,
        title: str,
        message: str,
        on_confirm: Callable[[], None],
        on_cancel: Callable[[], None],
        confirm_label: str,
        cancel_label: str,
    ) -> None:
        super().__init__(title=title)
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._message = message
        self._confirm_button = None
        self._cancel_button = None
        self._build_body(confirm_label, cancel_label)

    def _build_body(self, confirm_label: str, cancel_label: str) -> None:
        with self._window.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=4)
                with ui.HStack(height=0):
                    ui.Spacer(width=12)
                    ui.Label(
                        self._message,
                        word_wrap=True,
                        style_type_name_override="Dialog.Message",
                    )
                    ui.Spacer(width=12)
                ui.Spacer()
                with ui.HStack(height=28):
                    ui.Spacer()
                    self._confirm_button = ui.Button(
                        confirm_label,
                        width=112,
                        clicked_fn=self._on_confirm_clicked,
                        style_type_name_override="OKButton",
                    )
                    ui.Spacer(width=6)
                    self._cancel_button = ui.Button(
                        cancel_label,
                        width=96,
                        clicked_fn=self._on_cancel_clicked,
                        style_type_name_override="CancelButton",
                    )
                    ui.Spacer(width=12)
                ui.Spacer(height=8)

    def confirm(self) -> None:
        """Simulate a confirm click (test helper)."""
        self._on_confirm_clicked()

    def cancel(self) -> None:
        """Simulate a cancel click (test helper)."""
        self._on_cancel_clicked()

    def _on_confirm_clicked(self) -> None:
        self._close_with_callback(self._on_confirm)

    def _on_cancel_clicked(self) -> None:
        self._close_with_callback(self._on_cancel)

    def _on_window_closed(self) -> None:
        # Title-bar close fired after the close flipped ``_closed``;
        # re-run the cancel callback directly (registry removal
        # happened in :meth:`_on_visibility_changed`).
        self._on_cancel()


class _ConfirmDirtyRemoveDialog(_ConfirmDialogBase):
    """Private helper — three-button "Save / Discard / Cancel" modal.

    Used before removing a layer with unsaved edits. The message
    interpolates the layer name so the user reads which layer is at
    risk; the three buttons map to the three LAYERS-PLAN Step 37
    branches.
    """

    def __init__(
        self,
        layer_name: str,
        on_save_and_remove: Callable[[], None],
        on_remove_without_saving: Callable[[], None],
        on_cancel: Callable[[], None],
        dirty_layer_names: Optional[List[str]] = None,
    ) -> None:
        super().__init__(title="Remove Layer", width=560, height=180)
        self._on_save_and_remove = on_save_and_remove
        self._on_remove_without_saving = on_remove_without_saving
        self._on_cancel = on_cancel
        self._layer_name = layer_name
        self._dirty_layer_names = list(dirty_layer_names or [])
        self._build_body()

    def _build_body(self) -> None:
        if self._dirty_layer_names in ([], [self._layer_name]):
            unsaved = f"Layer {self._layer_name!r} has unsaved changes."
        else:
            names = ", ".join(repr(name) for name in self._dirty_layer_names)
            unsaved = (
                f"Layer {self._layer_name!r} contains unsaved changes "
                f"in: {names}."
            )
        message = f"{unsaved}\nSave before removing?"
        with self._window.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=4)
                with ui.HStack(height=0):
                    ui.Spacer(width=12)
                    ui.Label(
                        message,
                        word_wrap=True,
                        style_type_name_override="Dialog.Message",
                    )
                    ui.Spacer(width=12)
                ui.Spacer()
                with ui.HStack(height=28):
                    ui.Spacer()
                    ui.Button(
                        "Save & Remove",
                        width=128,
                        clicked_fn=self._on_save_and_remove_clicked,
                        style_type_name_override="OKButton",
                    )
                    ui.Spacer(width=6)
                    ui.Button(
                        "Remove Without Saving",
                        width=168,
                        clicked_fn=self._on_remove_without_saving_clicked,
                        style_type_name_override="DestructiveButton",
                    )
                    ui.Spacer(width=6)
                    ui.Button(
                        "Cancel",
                        width=96,
                        clicked_fn=self._on_cancel_clicked,
                        style_type_name_override="CancelButton",
                    )
                    ui.Spacer(width=12)
                ui.Spacer(height=8)

    def save_and_remove(self) -> None:
        """Simulate a Save & Remove click (test helper)."""
        self._on_save_and_remove_clicked()

    def remove_without_saving(self) -> None:
        """Simulate a Remove Without Saving click (test helper)."""
        self._on_remove_without_saving_clicked()

    def cancel(self) -> None:
        """Simulate a Cancel click (test helper)."""
        self._on_cancel_clicked()

    def _on_save_and_remove_clicked(self) -> None:
        self._close_with_callback(self._on_save_and_remove)

    def _on_remove_without_saving_clicked(self) -> None:
        self._close_with_callback(self._on_remove_without_saving)

    def _on_cancel_clicked(self) -> None:
        self._close_with_callback(self._on_cancel)

    def _on_window_closed(self) -> None:
        # Title-bar close = Cancel, same as the explicit button.
        self._on_cancel()


# Key codes that ovui passes to a window key handler (GLFW key codes).
_KEY_ESCAPE = 256
_KEY_ENTER = 257
_KEY_KEYPAD_ENTER = 335


class _MessageDialog(_ConfirmDialogBase):
    """Private helper — one-button ``ui.Window``-backed message modal.

    The message is in a scrolling area and the OK row is below it, so the
    OK button stays visible for any message length. Enter, keypad Enter and
    Escape act as OK, because OK is the only choice.
    """

    def __init__(self, title: str, message: str) -> None:
        super().__init__(title=title, width=640, height=240)
        self._message = message
        self._build_body()
        if hasattr(self._window, "set_key_pressed_fn"):
            self._window.set_key_pressed_fn(self._on_key_pressed)

    def _build_body(self) -> None:
        with self._window.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=4)
                with ui.HStack():
                    ui.Spacer(width=12)
                    with ui.ScrollingFrame(
                        horizontal_scrollbar_policy=(
                            ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF
                        ),
                        vertical_scrollbar_policy=(
                            ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED
                        ),
                    ):
                        ui.Label(
                            self._message,
                            word_wrap=True,
                            height=0,
                            alignment=ui.Alignment.LEFT_TOP,
                            style_type_name_override="Dialog.Message",
                        )
                    ui.Spacer(width=12)
                with ui.HStack(height=28):
                    ui.Spacer()
                    ui.Button(
                        "OK",
                        width=96,
                        clicked_fn=self._on_ok_clicked,
                        style_type_name_override="OKButton",
                    )
                    ui.Spacer(width=12)
                ui.Spacer(height=8)

    def _on_key_pressed(self, key: int, modifiers: int, pressed: bool) -> None:
        # Act on the key release, as the content browser dialogs do.
        if not pressed and key in (_KEY_ENTER, _KEY_KEYPAD_ENTER, _KEY_ESCAPE):
            self._on_ok_clicked()

    def _on_ok_clicked(self) -> None:
        self._close_with_callback(lambda: None)


# The exit dialog names at most this many layers and counts the rest, so a
# large layer stack cannot push the buttons out of the window.
_EXIT_DIALOG_MAX_NAMES = 4


class _ConfirmUnsavedExitDialog(_ConfirmDialogBase):
    """Private helper — three-button "Save / Discard / Cancel" exit modal.

    Shown by File > Exit when layers have unsaved edits. The message names
    the modified layers; the three buttons map to save-then-exit, exit
    without saving, and stay open.
    """

    def __init__(
        self,
        layer_names: List[str],
        on_save_and_exit: Callable[[], None],
        on_exit_without_saving: Callable[[], None],
        on_cancel: Callable[[], None],
    ) -> None:
        super().__init__(title="Exit", width=560, height=180)
        self._on_save_and_exit = on_save_and_exit
        self._on_exit_without_saving = on_exit_without_saving
        self._on_cancel = on_cancel
        self._layer_names = list(layer_names)
        self._build_body()

    def _message(self) -> str:
        names = ", ".join(
            repr(name) for name in self._layer_names[:_EXIT_DIALOG_MAX_NAMES]
        )
        hidden = len(self._layer_names) - _EXIT_DIALOG_MAX_NAMES
        if hidden > 0:
            names += f" and {hidden} more"
        return (
            f"The stage has unsaved changes in {names}.\n"
            f"Save the changes before you exit?"
        )

    def _build_body(self) -> None:
        with self._window.frame:
            with ui.VStack(spacing=8):
                ui.Spacer(height=4)
                with ui.HStack(height=0):
                    ui.Spacer(width=12)
                    ui.Label(
                        self._message(),
                        word_wrap=True,
                        style_type_name_override="Dialog.Message",
                    )
                    ui.Spacer(width=12)
                ui.Spacer()
                with ui.HStack(height=28):
                    ui.Spacer()
                    ui.Button(
                        "Save & Exit",
                        width=112,
                        clicked_fn=self._on_save_and_exit_clicked,
                        style_type_name_override="OKButton",
                    )
                    ui.Spacer(width=6)
                    ui.Button(
                        "Exit Without Saving",
                        width=152,
                        clicked_fn=self._on_exit_without_saving_clicked,
                        style_type_name_override="DestructiveButton",
                    )
                    ui.Spacer(width=6)
                    ui.Button(
                        "Cancel",
                        width=96,
                        clicked_fn=self._on_cancel_clicked,
                        style_type_name_override="CancelButton",
                    )
                    ui.Spacer(width=12)
                ui.Spacer(height=8)

    def save_and_exit(self) -> None:
        """Simulate a Save & Exit click (test helper)."""
        self._on_save_and_exit_clicked()

    def exit_without_saving(self) -> None:
        """Simulate an Exit Without Saving click (test helper)."""
        self._on_exit_without_saving_clicked()

    def cancel(self) -> None:
        """Simulate a Cancel click (test helper)."""
        self._on_cancel_clicked()

    def _on_save_and_exit_clicked(self) -> None:
        self._close_with_callback(self._on_save_and_exit)

    def _on_exit_without_saving_clicked(self) -> None:
        self._close_with_callback(self._on_exit_without_saving)

    def _on_cancel_clicked(self) -> None:
        self._close_with_callback(self._on_cancel)

    def _on_window_closed(self) -> None:
        # Title-bar close = Cancel, same as the explicit button.
        self._on_cancel()


# ── registry-driven shutdown cleanup ────────────────
# Application.shutdown() invokes icon_caches.clear_all() while ovui's
# standalone backend is still alive. The hook below destroys every
# live ui.Window in _OPEN_DIALOGS and clears the list. Round 6 F2:
# also nulls dlg._window so the destroyed wrapper isn't kept alive
# through the dialog instance's attribute.
def _clear_open_dialogs() -> None:
    """Destroy every dialog in _OPEN_DIALOGS and empty the list.

    Called by ovui_widgets.common.icon_caches.clear_all() from
    Application.shutdown(). Safe to call multiple times — the list is
    consumed each call, and a per-dialog try/except/finally guarantees
    one dialog's destroy failure doesn't skip the rest.
    """
    for dlg in list(_OPEN_DIALOGS):
        w = getattr(dlg, "_window", None)
        if w is None:
            continue
        try:
            w.destroy()
        except Exception:
            pass
        finally:
            try:
                dlg._window = None
            except Exception:
                pass
    _OPEN_DIALOGS.clear()


from ovui_widgets.common.icon_caches import register as _register_for_shutdown

_register_for_shutdown(_clear_open_dialogs)
