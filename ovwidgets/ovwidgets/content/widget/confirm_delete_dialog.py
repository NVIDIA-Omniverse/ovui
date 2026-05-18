# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ConfirmDeleteDialog — destructive-confirmation modal for file deletes.

See the content browser behavior (``delete_items`` surface) and
the content browser implementation step 34. Delete is the first destructive content-browser
operation: it wipes files and folders from disk without an undo stack
(§27.9). A free-standing modal dialog is the standard contract — the
user sees every item that will be destroyed and acknowledges the loss
before the backend fires.

The dialog mirrors :class:`SimpleInputDialog`'s chrome (modal window,
fixed size, OK / Cancel button row) but swaps the single
:class:`ui.StringField` for a scrollable multi-line list of URLs and
retitles the primary button as ``Yes`` / the secondary as ``No``. A
warning label sits above the list: ``"This cannot be undone."`` — the
plan's explicit user-visible contract.

Keybindings: Enter commits (fires ``on_yes``); Escape cancels. Matches
the Create Folder dialog so the keyboard affordance is consistent across
every content-browser modal.

Callers supply the pre-computed list of URLs; the dialog owns no
file-system or backend knowledge. On OK → ``on_yes()`` fires then the
window dismisses. On Cancel / Escape → the window dismisses without
calling ``on_yes``.
"""

from __future__ import annotations

from typing import Callable, List, Optional

import omni.ui as ui

# Popup window title prefix. ovui uses the window title as its registry
# key — suffixing ``id(self)`` at construction time keeps back-to-back
# dialogs from colliding in that registry. Same pattern as
# :class:`SimpleInputDialog`.
_WINDOW_TITLE_PREFIX = "OvGear_ConfirmDeleteDialog_"

# Modal window chrome. ``MODAL`` takes exclusive focus (click-outside is
# consumed, not dismissed); ``NO_RESIZE`` + ``NO_SCROLLBAR`` lock the
# popup to its constructor size — the inner :class:`ui.ScrollingFrame`
# is the only scrolling surface.
_WINDOW_FLAGS = (
    ui.WINDOW_FLAGS_MODAL
    | ui.WINDOW_FLAGS_NO_RESIZE
    | ui.WINDOW_FLAGS_NO_SCROLLBAR
    | ui.WINDOW_FLAGS_NO_DOCKING
)

# Window dimensions. Wider than :class:`SimpleInputDialog` (360 px) so
# longer URL rows don't wrap uselessly in a cramped list. 420×280 fits
# ~10 visible rows at default font size before the :class:`ui.ScrollingFrame`
# takes over, which is generous for typical multi-delete counts.
_WINDOW_WIDTH = 420
_WINDOW_HEIGHT = 280

# Button strip sizing. 80×28 matches :class:`SimpleInputDialog` so the
# two dialogs read identical in the button row.
_BUTTON_WIDTH = 80
_BUTTON_HEIGHT = 28

# Row height for the warning label. 24 px matches the prompt-row
# convention already used by :class:`SimpleInputDialog`.
_WARNING_ROW_HEIGHT = 24

# Path list area — the scrolling frame fills whatever vertical space
# the VStack gives it after the warning label and the button row are
# pinned. 120 px minimum keeps ~4 rows visible at the Content font size
# even in the narrowest usable layout.
_PATH_LIST_MIN_HEIGHT = 120

# Inner margin / gap. 8 px matches :class:`SimpleInputDialog` and the
# Content.ToolBar convention.
_INNER_PADDING = 8

# Per-row height for each listed path. 18 px fits the Content font at
# default DPI without an airy gap between entries — the goal is a
# compact list that still reads clearly.
_PATH_ROW_HEIGHT = 18

# Key codes. Shared with :class:`SimpleInputDialog` so the Enter /
# Escape contract is uniform across every content-browser modal.
_KEY_ESCAPE = 256
_KEY_ENTER = 257
_KEY_KEYPAD_ENTER = 335

# Warning text surfaced above the path list. Module constant so the
# test module can import and assert it verbatim rather than duplicating
# the literal string.
WARNING_MESSAGE = "This cannot be undone."

# Window title + button labels. Module constants for the same verbatim-
# assertion reason as :data:`WARNING_MESSAGE`.
DIALOG_TITLE = "Confirm Delete"
YES_BUTTON_LABEL = "Yes"
NO_BUTTON_LABEL = "No"


class ConfirmDeleteDialog:
    """Modal dialog that lists URLs to be deleted and asks Yes / No.

    Construction is cheap (no ovui side effects); :meth:`show`
    materialises the :class:`ui.Window`. A single instance is
    effectively single-shot — after Yes / No dismisses the popup,
    :meth:`show` would rebuild a fresh window but callers construct a
    new instance per invocation (the
    :class:`~ovwidgets.content.widget.context_menu.FileContextMenu`
    holds the instance just long enough to outlive the ``clicked_fn``
    that spawned it).

    ``on_yes()`` runs once on confirm, *before* the dialog dismisses —
    mirrors :class:`SimpleInputDialog`'s dispatch order so a Yes handler
    that wants to spawn a second modal (e.g. a per-item progress popup
    in a future step) lands on top of a still-live surface.

    ``urls`` is displayed verbatim as the scrollable list body. The
    dialog neither strips, normalises, nor deduplicates the list —
    the caller owns the exact set the user should see (matches the
    selection semantics where the same URL cannot appear twice anyway).
    """

    def __init__(
        self,
        urls: List[str],
        on_yes: Callable[[], None],
    ) -> None:
        self._urls: List[str] = list(urls)
        self._on_yes: Optional[Callable[[], None]] = on_yes

        # Live ovui references — populated by :meth:`show`, nulled by
        # :meth:`_dismiss` / :meth:`destroy`. ``None`` before the first
        # show and post-dismiss so callbacks that sneak through during
        # teardown fall through silently.
        self._window: Optional[ui.Window] = None
        self._scroll_frame: Optional[ui.ScrollingFrame] = None

    # ── Public surface ───────────────────────────────────────────────────

    def show(self) -> None:
        """Materialise and present the modal confirm popup.

        Idempotent on a visible window — a second :meth:`show` while
        the window is live is a no-op (ovui would otherwise stack a
        duplicate modal). After :meth:`_dismiss` destroys the popup,
        :meth:`show` is callable again and rebuilds from scratch.
        """
        if self._window is not None:
            return
        title = f"{_WINDOW_TITLE_PREFIX}{id(self)}"
        self._window = ui.Window(
            title,
            width=_WINDOW_WIDTH,
            height=_WINDOW_HEIGHT,
            flags=_WINDOW_FLAGS,
        )
        # ovui uses the title as the window's visible caption when
        # ``NO_TITLE_BAR`` is not set — override to drop the registry
        # prefix so the user sees the human-readable ``DIALOG_TITLE``.
        try:
            self._window.title = DIALOG_TITLE
        except Exception:  # noqa: BLE001
            # ovui's ``.title`` setter is present on newer builds; if
            # not we fall back to the registry-keyed string. Not fatal
            # — the user still sees a labelled dialog, just with the
            # internal id on older ovui versions.
            pass
        # Bind key handling at the window level so Enter / Escape work
        # regardless of which child widget holds ImGui focus — the
        # dialog has no input field to anchor the handler on, so the
        # window is the only always-live target.
        try:
            self._window.set_key_pressed_fn(self._on_window_key_pressed)
        except Exception:  # noqa: BLE001
            # Older ovui versions may not expose set_key_pressed_fn on
            # windows. The buttons still work; we just lose the keyboard
            # affordance in that build.
            pass
        with self._window.frame:
            self._build_content()

    def destroy(self) -> None:
        """Dismiss without firing ``on_yes`` and drop every reference.

        Idempotent — safe to call from a caller-side teardown path even
        when the dialog was never shown. Leaves the instance in a
        consumed state; further :meth:`show` calls rebuild a fresh
        window, but ``on_yes`` is gone and Yes clicks no-op.
        """
        self._dismiss()
        self._on_yes = None

    # ── Build ────────────────────────────────────────────────────────────

    def _build_content(self) -> None:
        """Lay out warning label, scrollable path list, Yes / No buttons.

        Layout (vertical stack with inner padding)::

            Spacer(_INNER_PADDING)
            HStack(row): Spacer | Label(warning) | Spacer
            Spacer(_INNER_PADDING)
            ScrollingFrame:
                VStack: Label(url_1) | Label(url_2) | ... | Label(url_N)
            Spacer(_INNER_PADDING)
            HStack(button row):
                Spacer | YesButton | Spacer(_INNER_PADDING) | NoButton | Spacer(_INNER_PADDING)
            Spacer(_INNER_PADDING)

        The warning label paints with the ``Content.EmptyState`` selector
        so it reads as secondary text colour — subtle, not a status
        badge. The ScrollingFrame inherits ``Content.ScrollingFrame``
        chrome so its scrollbar matches every other list in the panel.
        """
        with ui.VStack(spacing=0):
            ui.Spacer(height=_INNER_PADDING)

            # Warning row.
            with ui.HStack(height=ui.Pixel(_WARNING_ROW_HEIGHT)):
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))
                ui.Label(
                    WARNING_MESSAGE,
                    style_type_name_override="Content.EmptyState",
                )
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))

            ui.Spacer(height=_INNER_PADDING)

            # Scrollable path list. The ScrollingFrame is the only
            # flex child so it consumes the vertical space between the
            # fixed warning row above and the fixed button row below.
            with ui.HStack():
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))
                self._scroll_frame = ui.ScrollingFrame(
                    horizontal_scrollbar_policy=(
                        ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED
                    ),
                    vertical_scrollbar_policy=(
                        ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED
                    ),
                    style_type_name_override="Content.ScrollingFrame",
                    height=ui.Pixel(_PATH_LIST_MIN_HEIGHT),
                )
                with self._scroll_frame:
                    with ui.VStack(spacing=0):
                        for url in self._urls:
                            ui.Label(
                                url,
                                height=ui.Pixel(_PATH_ROW_HEIGHT),
                                style_type_name_override=(
                                    "Content.Row.Name"
                                ),
                            )
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))

            ui.Spacer(height=_INNER_PADDING)

            # Button row. Yes on the left as the primary affordance (the
            # answer to the window's implicit question "Delete?") with
            # No after it — same ordering as :class:`SimpleInputDialog`'s
            # OK / Cancel so the user's muscle memory lines up.
            with ui.HStack(height=ui.Pixel(_BUTTON_HEIGHT)):
                ui.Spacer()
                ui.Button(
                    YES_BUTTON_LABEL,
                    width=ui.Pixel(_BUTTON_WIDTH),
                    height=ui.Pixel(_BUTTON_HEIGHT),
                    style_type_name_override="OKButton",
                    clicked_fn=self._on_yes_clicked,
                )
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))
                ui.Button(
                    NO_BUTTON_LABEL,
                    width=ui.Pixel(_BUTTON_WIDTH),
                    height=ui.Pixel(_BUTTON_HEIGHT),
                    style_type_name_override="CancelButton",
                    clicked_fn=self._on_no_clicked,
                )
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))

            ui.Spacer(height=ui.Pixel(_INNER_PADDING))

    # ── Handlers ─────────────────────────────────────────────────────────

    def _on_window_key_pressed(
        self, key: int, mod: int, pressed: bool,
    ) -> None:
        """Route Enter / Escape at the window level.

        Window-level dispatch (rather than field-level) because the
        dialog has no :class:`ui.StringField` to anchor the handler on.
        We act on the release edge — same contract as
        :class:`SimpleInputDialog` — so any in-flight ovui click dispatch
        from the buttons completes first.
        """
        if pressed:
            return
        if key == _KEY_ESCAPE:
            self._on_no_clicked()
            return
        if key in (_KEY_ENTER, _KEY_KEYPAD_ENTER):
            self._on_yes_clicked()
            return

    def _on_yes_clicked(self) -> None:
        """Fire ``on_yes`` then dismiss.

        Dispatch order is ``on_yes`` first, dismiss second — a Yes
        handler that wants to spawn a follow-up modal (progress popup,
        error reporter) finds the window still reachable. Matches
        :class:`SimpleInputDialog`'s ordering.
        """
        handler = self._on_yes
        self._dismiss()
        if handler is not None:
            handler()

    def _on_no_clicked(self) -> None:
        """Dismiss without firing ``on_yes``."""
        self._dismiss()

    def _dismiss(self) -> None:
        """Hide + destroy the popup and drop every ovui reference."""
        window = self._window
        self._window = None
        self._scroll_frame = None
        if window is not None:
            try:
                window.set_key_pressed_fn(None)
            except Exception:  # noqa: BLE001
                # Older ovui versions may not expose the setter; the
                # window destroy below still runs.
                pass
            try:
                window.visible = False
            except Exception:  # noqa: BLE001
                # ovui may raise if the window was already hidden by a
                # sibling path; the subsequent destroy() still runs.
                pass
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                # ovui may raise if the window was re-entered during
                # teardown; further destroy() calls are no-ops.
                pass

    # ── Test hooks ───────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        """``True`` while the popup window is live; ``False`` post-dismiss."""
        return self._window is not None

    @property
    def urls(self) -> List[str]:
        """The URL list the dialog is presenting to the user.

        Returned as a fresh copy so callers cannot mutate the dialog's
        internal state through the accessor.
        """
        return list(self._urls)

    def _fire_yes_for_test(self) -> None:
        """Invoke the Yes handler — test-only hook.

        Drives :meth:`_on_yes_clicked` directly so tests can bypass the
        ``ui.Button`` click dispatch (which is opaque to a non-ovui test
        harness). Silent no-op post-dismiss.
        """
        if self._window is None:
            return
        self._on_yes_clicked()

    def _fire_no_for_test(self) -> None:
        """Invoke the No handler — test-only hook."""
        if self._window is None:
            return
        self._on_no_clicked()

    def _fire_key_for_test(self, key: int) -> None:
        """Drive the window's key handler — test-only hook."""
        if self._window is None:
            return
        self._on_window_key_pressed(key, 0, False)
