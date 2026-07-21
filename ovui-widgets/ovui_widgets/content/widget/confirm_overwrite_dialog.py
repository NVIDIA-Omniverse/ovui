# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ConfirmOverwriteDialog — collision-confirmation modal.

See the content browser behavior (specialized menus — overwrite
pattern mirrors :class:`ConfirmDeleteDialog`), §23.9 (save-as
``_show_file_existed_prompt``) and the content browser implementation steps 36 + 52. Two
complementary surfaces live on this one class:

**Paste surface (Step 36).** Paste raises
:attr:`BackendResult.ERROR_ALREADY_EXISTS` when the destination URL is
occupied; the dialog asks the user how to resolve each collision with
four choices:

* **Yes** — overwrite this one item.
* **No** — skip this one item.
* **Yes to All** — overwrite the remaining collisions without asking
  again (only meaningful on a multi-item paste).
* **No to All** — skip the remaining collisions without asking again.

The four choices are delivered to ``on_response`` as the
:class:`OverwriteChoice` enum; the caller owns the iteration / retry
logic. The Yes-to-All / No-to-All buttons only render when
``multi=True``.

**Save surface (Step 52).** Save-as hits the same "file already exists"
state but the contract is simpler: Yes proceeds with the save, No
returns the user to the file picker. Callers pass ``on_yes`` instead
of ``on_response``; the dialog renders Yes / No only, uses the
save-specific prompt :data:`WARNING_MESSAGE_SAVE`, and fires ``on_yes``
on Yes while No / Escape dismiss silently. Matches Kit's
:func:`_show_file_existed_prompt` from ``omni.kit.window.file`` —
architecture §23.9.

Chrome is shared: modal window, fixed size, warning label above the
URL / filename row, button row below.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Callable, List, Optional

import omni.ui as ui

# Popup window title prefix. ovui uses the window title as its registry
# key — suffixing ``id(self)`` at construction time keeps back-to-back
# dialogs from colliding in that registry. Same pattern as
# :class:`ConfirmDeleteDialog` / :class:`SimpleInputDialog`.
_WINDOW_TITLE_PREFIX = "OvGear_ConfirmOverwriteDialog_"

# Modal window chrome — matches :class:`ConfirmDeleteDialog` so the two
# confirmation modals read as a visually consistent pair.
_WINDOW_FLAGS = (
    ui.WINDOW_FLAGS_MODAL
    | ui.WINDOW_FLAGS_NO_RESIZE
    | ui.WINDOW_FLAGS_NO_SCROLLBAR
    | ui.WINDOW_FLAGS_NO_DOCKING
)

# Window dimensions. Wider than :class:`ConfirmDeleteDialog` (420 px)
# because the button row has up to four buttons side-by-side on a
# multi-paste collision; 520 px fits them without crowding.
_WINDOW_WIDTH = 520
_WINDOW_HEIGHT = 200

# Button strip sizing. 100 px wide (vs. 80 px for Yes/No in the delete
# dialog) so the longer "Yes to All" / "No to All" labels fit without
# truncation. Height matches the delete dialog's 28 px so the two
# dialogs' button strips land on the same optical baseline when they
# sit next to each other across a multi-step paste flow.
_BUTTON_WIDTH = 100
_BUTTON_HEIGHT = 28

# Row height for the warning label. 24 px matches the prompt-row
# convention already used by :class:`ConfirmDeleteDialog`.
_WARNING_ROW_HEIGHT = 24

# URL row height — 18 px fits Content.Row.Name at default DPI.
_PATH_ROW_HEIGHT = 18

# Inner margin / gap. 8 px matches :class:`ConfirmDeleteDialog` and the
# Content.ToolBar convention.
_INNER_PADDING = 8

# Key codes. Shared with :class:`ConfirmDeleteDialog` so the Enter /
# Escape contract is uniform across every content-browser modal.
_KEY_ESCAPE = 256
_KEY_ENTER = 257
_KEY_KEYPAD_ENTER = 335


# Issue #35 Step 4 — module-scope tracking of every dialog whose
# ui.Window is currently materialised. ``show()`` appends ``self``
# AFTER ``ui.Window(...)`` succeeds (Round 4 / Round 5 F5: register on
# show, not in __init__ — only dialogs that actually own a live
# ``ui.Window`` should be tracked); ``_dismiss()`` removes ``self``.
# A module-level ``_clear_open_dialogs()`` (registered with
# :mod:`ovui_widgets.common.icon_caches`) tears down everything left in the list at
# ``Application.shutdown()``.
_OPEN_DIALOGS: List["ConfirmOverwriteDialog"] = []


# User-facing strings. Module constants so the test module can import
# and assert against them verbatim rather than duplicating the literals.
DIALOG_TITLE = "Confirm Overwrite"
WARNING_MESSAGE = "An item with that name already exists:"
# Save-mode (Step 52) prompt. Kit's ``_show_file_existed_prompt`` uses a
# near-identical wording — architecture §23.9.
WARNING_MESSAGE_SAVE = "File already exists. Overwrite?"
YES_BUTTON_LABEL = "Yes"
NO_BUTTON_LABEL = "No"
YES_ALL_BUTTON_LABEL = "Yes to All"
NO_ALL_BUTTON_LABEL = "No to All"


class OverwriteChoice(Enum):
    """User's response to a single overwrite prompt.

    ``YES`` / ``NO`` apply to the current collision only. ``YES_TO_ALL``
    / ``NO_TO_ALL`` instruct the caller to stop prompting and apply the
    same answer to every remaining collision in the current paste batch.
    """

    YES = auto()
    NO = auto()
    YES_TO_ALL = auto()
    NO_TO_ALL = auto()


class ConfirmOverwriteDialog:
    """Modal dialog asking the user how to resolve an overwrite collision.

    Construction is cheap; :meth:`show` materialises the
    :class:`ui.Window`. A single instance is effectively single-shot —
    callers spawn a fresh instance per collision / per save attempt.

    Two callback shapes, one class:

    * **Paste mode** (``on_response``) — fires exactly once on Yes / No /
      Yes-to-All / No-to-All with an :class:`OverwriteChoice` argument.
      The Yes-to-All / No-to-All buttons render only when ``multi=True``.
    * **Save mode** (``on_yes``) — fires ``on_yes()`` on Yes only. No /
      Escape dismiss the dialog silently (returns the user to the file
      picker). ``multi`` is forced to ``False`` in save mode, and the
      default warning message swaps to :data:`WARNING_MESSAGE_SAVE`.

    Exactly one of ``on_response`` / ``on_yes`` must be provided;
    supplying both or neither raises :class:`ValueError`. Escape is
    treated as No (matches :class:`ConfirmDeleteDialog`'s cancel path);
    Enter is treated as Yes (primary affordance).
    """

    def __init__(
        self,
        url: str,
        on_response: Optional[Callable[[OverwriteChoice], None]] = None,
        multi: bool = False,
        *,
        on_yes: Optional[Callable[[], None]] = None,
        message: Optional[str] = None,
    ) -> None:
        # Mode contract: exactly one of on_response / on_yes. The two
        # shapes are deliberately kept as separate kwargs rather than a
        # polymorphic single callback because the paste surface uses
        # every OverwriteChoice value and the save surface has no
        # meaningful response beyond "Yes" — collapsing them would force
        # save-mode callers to write a YES-only branch + ignore NO.
        if on_response is None and on_yes is None:
            raise ValueError(
                "ConfirmOverwriteDialog requires on_response (paste mode) "
                "or on_yes (save mode)"
            )
        if on_response is not None and on_yes is not None:
            raise ValueError(
                "ConfirmOverwriteDialog accepts on_response XOR on_yes, "
                "not both"
            )

        self._url: str = url
        self._on_response: Optional[Callable[[OverwriteChoice], None]] = (
            on_response
        )
        self._on_yes: Optional[Callable[[], None]] = on_yes
        # Save mode forces multi=False — Yes-to-All / No-to-All have no
        # meaning for a single-file save collision (§23.9).
        self._multi: bool = bool(multi) if on_yes is None else False
        # Default warning message differs by mode. Explicit ``message``
        # overrides take precedence either way so callers with an
        # unusual prompt (localised builds, plugin-specific phrasing)
        # can supply their own literal.
        if message is not None:
            self._message: str = message
        elif on_yes is not None:
            self._message = WARNING_MESSAGE_SAVE
        else:
            self._message = WARNING_MESSAGE

        # Live ovui refs — populated by :meth:`show`, nulled by
        # :meth:`_dismiss` / :meth:`destroy`.
        self._window: Optional[ui.Window] = None

    # ── Public surface ───────────────────────────────────────────────────

    def show(self) -> None:
        """Materialise and present the modal confirm popup.

        Idempotent on a visible window — a second :meth:`show` while
        the window is live is a no-op (matches :class:`ConfirmDeleteDialog`).
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
        # Issue #35 Step 4 / Round 4-5 F5: track only dialogs that
        # actually own a live ui.Window. Guard with `not in` so a
        # re-show (idempotent path above this branch) doesn't double-
        # register.
        if self not in _OPEN_DIALOGS:
            _OPEN_DIALOGS.append(self)
        try:
            self._window.title = DIALOG_TITLE
        except Exception:  # noqa: BLE001
            # Older ovui versions may not expose the ``.title`` setter —
            # the user still sees a labelled dialog, just with the
            # internal id on those builds. Matches
            # :class:`ConfirmDeleteDialog`'s fallback.
            pass
        try:
            self._window.set_key_pressed_fn(self._on_window_key_pressed)
        except Exception:  # noqa: BLE001
            # ovui builds without window-level key handlers keep the
            # button-click affordance — the keyboard shortcut is the
            # only thing that falls through on those builds.
            pass
        with self._window.frame:
            self._build_content()

    def destroy(self) -> None:
        """Dismiss without firing any callback and drop every reference.

        Idempotent — safe to call from a caller-side teardown path even
        when the dialog was never shown. Clears both the paste-mode and
        save-mode callback slots so a post-destroy fire hook becomes a
        silent no-op.
        """
        self._dismiss()
        self._on_response = None
        self._on_yes = None

    # ── Build ────────────────────────────────────────────────────────────

    def _build_content(self) -> None:
        """Lay out warning label, URL row, and Yes / No (/ all) buttons.

        The button row adapts to ``_multi``: single-item paste shows
        Yes / No only; multi-item paste shows Yes / Yes to All / No /
        No to All. Ordering keeps Yes / No grouped on the left (the
        "single item" answer) with the "to All" buttons trailing them
        so the user reads Y/N first before escalating.
        """
        with ui.VStack(spacing=0):
            ui.Spacer(height=_INNER_PADDING)

            # Warning row. Paste mode uses :data:`WARNING_MESSAGE`;
            # save mode (on_yes) defaults to :data:`WARNING_MESSAGE_SAVE`.
            with ui.HStack(height=ui.Pixel(_WARNING_ROW_HEIGHT)):
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))
                ui.Label(
                    self._message,
                    style_type_name_override="Content.EmptyState",
                )
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))

            ui.Spacer(height=_INNER_PADDING)

            # URL row. Single-line; the caller passes one URL per
            # dialog invocation (the per-collision contract).
            with ui.HStack(height=ui.Pixel(_PATH_ROW_HEIGHT)):
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))
                ui.Label(
                    self._url,
                    style_type_name_override="Content.Row.Name",
                )
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))

            ui.Spacer()  # flex to push buttons to the bottom

            # Button row.
            with ui.HStack(height=ui.Pixel(_BUTTON_HEIGHT)):
                ui.Spacer()
                ui.Button(
                    YES_BUTTON_LABEL,
                    width=ui.Pixel(_BUTTON_WIDTH),
                    height=ui.Pixel(_BUTTON_HEIGHT),
                    style_type_name_override="OKButton",
                    clicked_fn=self._on_yes_clicked,
                )
                if self._multi:
                    ui.Spacer(width=ui.Pixel(_INNER_PADDING))
                    ui.Button(
                        YES_ALL_BUTTON_LABEL,
                        width=ui.Pixel(_BUTTON_WIDTH),
                        height=ui.Pixel(_BUTTON_HEIGHT),
                        style_type_name_override="OKButton",
                        clicked_fn=self._on_yes_all_clicked,
                    )
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))
                ui.Button(
                    NO_BUTTON_LABEL,
                    width=ui.Pixel(_BUTTON_WIDTH),
                    height=ui.Pixel(_BUTTON_HEIGHT),
                    style_type_name_override="CancelButton",
                    clicked_fn=self._on_no_clicked,
                )
                if self._multi:
                    ui.Spacer(width=ui.Pixel(_INNER_PADDING))
                    ui.Button(
                        NO_ALL_BUTTON_LABEL,
                        width=ui.Pixel(_BUTTON_WIDTH),
                        height=ui.Pixel(_BUTTON_HEIGHT),
                        style_type_name_override="CancelButton",
                        clicked_fn=self._on_no_all_clicked,
                    )
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))

            ui.Spacer(height=ui.Pixel(_INNER_PADDING))

    # ── Handlers ─────────────────────────────────────────────────────────

    def _on_window_key_pressed(
        self, key: int, mod: int, pressed: bool,
    ) -> None:
        """Route Enter / Escape at the window level.

        Enter maps to Yes (the primary affordance, same as
        :class:`ConfirmDeleteDialog`); Escape maps to No. Per-batch
        Yes-to-All / No-to-All have no keyboard equivalent — they
        require a deliberate button click so the user does not flip
        the whole batch by mashing the keyboard.
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
        self._fire(OverwriteChoice.YES)

    def _on_no_clicked(self) -> None:
        self._fire(OverwriteChoice.NO)

    def _on_yes_all_clicked(self) -> None:
        self._fire(OverwriteChoice.YES_TO_ALL)

    def _on_no_all_clicked(self) -> None:
        self._fire(OverwriteChoice.NO_TO_ALL)

    def _fire(self, choice: OverwriteChoice) -> None:
        """Dispatch ``choice`` then dismiss.

        Paste mode: forwards every :class:`OverwriteChoice` to
        ``on_response``. Save mode: fires ``on_yes()`` on YES only;
        NO / YES_TO_ALL / NO_TO_ALL dismiss silently (save-mode renders
        only Yes / No so the latter two can't be produced by the UI,
        but the test hooks can synthesise them — the silent-skip branch
        keeps the contract explicit).

        Dispatch order is response-first, dismiss-second — mirrors
        :class:`ConfirmDeleteDialog`'s ordering so a response handler
        that wants to spawn a follow-up modal finds the current window
        still reachable.
        """
        response_handler = self._on_response
        yes_handler = self._on_yes
        self._dismiss()
        if response_handler is not None:
            response_handler(choice)
            return
        if yes_handler is not None and choice == OverwriteChoice.YES:
            yes_handler()

    def _dismiss(self) -> None:
        """Hide + destroy the popup and drop every ovui reference."""
        # Issue #35 Step 4: deregister BEFORE we touch the window so
        # _clear_open_dialogs() (called from Application.shutdown())
        # doesn't see a half-torn-down entry.
        try:
            _OPEN_DIALOGS.remove(self)
        except ValueError:
            # Not in the list — happens when destroy() is called on a
            # never-shown dialog, or after _clear_open_dialogs has
            # already drained the list at shutdown.
            pass
        window = self._window
        self._window = None
        if window is not None:
            try:
                window.set_key_pressed_fn(None)
            except Exception:  # noqa: BLE001
                # Older ovui versions may not expose the setter.
                pass
            try:
                window.visible = False
            except Exception:  # noqa: BLE001
                # ovui may raise if the window was already hidden.
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
    def url(self) -> str:
        """The URL the dialog is prompting about."""
        return self._url

    @property
    def multi(self) -> bool:
        """Whether the Yes-to-All / No-to-All buttons are rendered.

        Always ``False`` in save mode (on_yes surface).
        """
        return self._multi

    @property
    def message(self) -> str:
        """The warning label the dialog is painting above the URL row."""
        return self._message

    def _fire_choice_for_test(self, choice: OverwriteChoice) -> None:
        """Fire ``choice`` directly — test-only hook that skips the
        ``ui.Button`` click dispatch (opaque in a non-ovui harness)."""
        if self._window is None:
            return
        self._fire(choice)

    def _fire_key_for_test(self, key: int) -> None:
        """Drive the window's key handler — test-only hook."""
        if self._window is None:
            return
        self._on_window_key_pressed(key, 0, False)


# ── Issue #35 Step 4: registry-driven shutdown cleanup ────────────────
# Same pattern as ovui_widgets.app/dialogs.py and ovui_widgets.app/file_dialogs.py. The
# _OPEN_DIALOGS list is populated by show() (NOT __init__) so only
# dialogs that actually own a live ui.Window are tracked
# (Round 4 / 5 F5).
def _clear_open_dialogs() -> None:
    """Destroy every dialog in _OPEN_DIALOGS and empty the list.

    Called by ovui_widgets.common.icon_caches.clear_all() from
    Application.shutdown(). Round 6 F2: also nulls dlg._window so the
    destroyed wrapper isn't kept alive through the dialog instance's
    attribute.
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
