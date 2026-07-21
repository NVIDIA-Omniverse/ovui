# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""SimpleInputDialog — single-field modal prompt for a short string value.

See the content browser behavior (rename / create-folder dialog
surfaces) and the content browser implementation step 32. The dialog is the first writable
surface in the content browser: the user clicks
``Create Folder`` → a modal pops → they type a name → Enter / OK
commits, Escape / Cancel discards. Step 33 (rename) reuses the same
dialog by constructing a fresh instance with a different ``title`` /
``prompt`` / ``initial_value``.

The dialog is deliberately generic — it owns no knowledge of the
backend, of :class:`FileItem`, or of any file-system concept. Validation
(empty / duplicate / illegal characters) is the **caller's** contract:
the constructor takes an ``on_ok(value)`` callback, and the caller
inspects the value, runs whatever backend op it needs, and surfaces
status via :class:`ovui_widgets.common.error_reporter.ErrorReporter`. The dialog
dismisses itself after invoking ``on_ok`` regardless of success /
failure — a validation-rejected value still closes the popup; the
user re-invokes the menu to try again. This mirrors Kit's
``InputDialog`` surface, minus the kwargs we do not need (no ``cancel_fn``
callback because callers haven't needed one yet, no ``middle_fn`` for a
tri-state "Apply / Cancel / Default" surface).

Window chrome: ``WINDOW_FLAGS_MODAL`` grabs focus exclusively so a
mis-click outside the popup doesn't silently dismiss the surface
(unlike ``WINDOW_FLAGS_POPUP`` which dismisses on click-outside).
``NO_RESIZE`` + ``NO_SCROLLBAR`` lock the popup to its constructor
size — the field takes a bounded string, there's nothing to scroll.

Keybindings on the :class:`ui.StringField`: Enter / keypad-Enter fires
``on_ok``; Escape dismisses without firing. Same key codes
(:data:`_KEY_ENTER` / :data:`_KEY_ESCAPE`) the
:class:`~ovui_widgets.content.widget.path_field.PathField` popup
already uses — ImGui-native values passed through by
:meth:`omni.ui.StringField.set_key_pressed_fn`.
"""

from __future__ import annotations

from typing import Callable, Optional

import omni.ui as ui

# Popup window title prefix. ovui uses the window title as its registry
# key — suffixing ``id(self)`` at construction time keeps back-to-back
# dialogs (rename + create + rename) from colliding in that registry.
_WINDOW_TITLE_PREFIX = "OvGear_SimpleInputDialog_"

# Modal window chrome. ``MODAL`` takes exclusive focus (click-outside
# is consumed by the modal, not dismissed); ``NO_RESIZE`` +
# ``NO_SCROLLBAR`` lock the popup to its constructor size.
_WINDOW_FLAGS = (
    ui.WINDOW_FLAGS_MODAL
    | ui.WINDOW_FLAGS_NO_RESIZE
    | ui.WINDOW_FLAGS_NO_SCROLLBAR
    | ui.WINDOW_FLAGS_NO_DOCKING
)

# Window dimensions. Wide enough for a typical folder name plus padding;
# tall enough for the prompt label, the field, and the OK / Cancel row
# with vertical slack. Kept as named constants so a future step can
# stamp a ``Content.Dialog`` selector family and pull sizes from the
# theme layer without hunting through magic numbers.
_WINDOW_WIDTH = 360
_WINDOW_HEIGHT = 140

# Button strip sizing. 80×28 matches the retry button in
# :class:`FileBrowserWidget`'s empty-state overlay so OK / Cancel read
# as the same-sized primary affordance the user has seen before.
_BUTTON_WIDTH = 80
_BUTTON_HEIGHT = 28

# Row height for the prompt label + field. 24 px matches the
# :class:`SettingsDialog` rows and the toolbar height conventions used
# elsewhere in the content browser — consistent optical rhythm across
# every dialog surface.
_ROW_HEIGHT = 24

# Inner margin / gap. 8 px is the :class:`SettingsDialog` convention
# and reads as "comfortable" without the popup feeling spaced-out.
_INNER_PADDING = 8

# Key codes. omni.ui's :meth:`ui.StringField.set_key_pressed_fn` passes
# raw ImGui key codes. ``_KEY_ENTER`` (257) is the main keyboard Enter,
# ``_KEY_KEYPAD_ENTER`` (335) is the numpad Enter, ``_KEY_ESCAPE`` (256)
# is Escape. Values match the :class:`PathField` popup's key handling
# so future consolidation into a shared keycode module is straight-
# forward.
_KEY_ESCAPE = 256
_KEY_ENTER = 257
_KEY_KEYPAD_ENTER = 335


class SimpleInputDialog:
    """Single-field modal dialog that prompts the user for a short string.

    Construction is cheap (no ovui side effects); :meth:`show` is the
    method that materialises the :class:`ui.Window` and renders the
    popup. The dialog is single-shot — after the user clicks OK /
    Cancel or presses Enter / Escape, :meth:`_dismiss` destroys the
    window and drops every ovui reference. A second :meth:`show` on the
    same instance rebuilds the window from scratch; in practice callers
    construct a fresh dialog per invocation.

    The ``on_ok(value)`` callback runs once per successful commit with
    the trimmed field value. The dialog does **not** inspect the value —
    validation belongs to the caller:
    empty / duplicate / separator-containing names are rejected with an
    :class:`ErrorReporter` warning, but all of that logic lives in the
    caller, not here).
    """

    def __init__(
        self,
        title: str,
        prompt: str,
        initial_value: str,
        on_ok: Callable[[str], None],
    ) -> None:
        self._title = title
        self._prompt = prompt
        self._initial_value = initial_value or ""
        self._on_ok: Optional[Callable[[str], None]] = on_ok

        # Live ovui references — populated by :meth:`show`, nulled by
        # :meth:`_dismiss` / :meth:`destroy`. ``None`` before the first
        # show and post-dismiss so callbacks that sneak through during
        # teardown fall through silently.
        self._window: Optional[ui.Window] = None
        self._field: Optional[ui.StringField] = None

    # ── Public surface ───────────────────────────────────────────────────

    def show(self) -> None:
        """Materialise and present the modal input popup.

        Idempotent on a visible window — a second :meth:`show` call
        while the window is live is a no-op (ovui would otherwise stack
        a duplicate modal). After :meth:`_dismiss` destroys the popup,
        :meth:`show` is callable again and rebuilds from scratch; a
        caller that wanted to re-prompt on validation failure could
        re-construct instead, which matches the Step-32 contract of
        "dialog closes after on_ok regardless of outcome".
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
        # ``NO_TITLE_BAR`` is not set (we deliberately leave the title
        # bar visible so the user sees "New Folder" as the popup's
        # context). Override via ``title`` attribute to drop the
        # ``_WINDOW_TITLE_PREFIX`` + id suffix — the prefix is a
        # registry-unique key, not a user-facing string.
        try:
            self._window.title = self._title
        except Exception:  # noqa: BLE001
            # ovui's ``.title`` setter is present on newer builds; if
            # not we fall back to the registry-keyed string. Not fatal
            # — the user still sees a labelled dialog, just with the
            # internal id on older ovui versions.
            pass
        with self._window.frame:
            self._build_content()

    def destroy(self) -> None:
        """Dismiss without firing ``on_ok`` and drop every reference.

        Idempotent — safe to call from a caller-side teardown path even
        when the dialog was never shown. Leaves the instance in a
        consumed state; further :meth:`show` calls rebuild a fresh
        window, but ``on_ok`` is gone and OK clicks no-op.
        """
        self._dismiss(fire_ok=False)
        self._on_ok = None

    # ── Build ────────────────────────────────────────────────────────────

    def _build_content(self) -> None:
        """Lay out prompt label, StringField, OK / Cancel row.

        Layout (vertical stack with inner padding)::

            Spacer(_INNER_PADDING)
            HStack(row): Spacer | Label(prompt) | Spacer
            HStack(row): Spacer | StringField   | Spacer
            Spacer(flex)
            HStack(button row):
                Spacer | OKButton | Spacer(_INNER_PADDING) | CancelButton | Spacer(_INNER_PADDING)
            Spacer(_INNER_PADDING)

        The OK button gets ``style_type_name_override="OKButton"`` and
        Cancel gets ``CancelButton``. Both types are defined in
        :mod:`ovui_widgets.app.style.styles` and carry the accent / neutral colour
        language the rest of the app uses for primary / secondary
        dialog actions (style naming rules).
        """
        with ui.VStack(spacing=0):
            ui.Spacer(height=_INNER_PADDING)

            # Prompt row.
            with ui.HStack(height=ui.Pixel(_ROW_HEIGHT)):
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))
                ui.Label(self._prompt)
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))

            # Field row. Height matches the prompt row so the two read
            # as a tight two-line stack rather than a breathing form.
            with ui.HStack(height=ui.Pixel(_ROW_HEIGHT)):
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))
                self._field = ui.StringField()
                self._field.model.set_value(self._initial_value)
                self._field.set_key_pressed_fn(self._on_field_key_pressed)
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))

            # Flex spacer pushes the button row to the bottom of the
            # modal without pinning a pixel gap — the window is
            # fixed-size, so any leftover vertical space lands here.
            ui.Spacer()

            # Button row. OK on the left (conventional for primary
            # action on Linux-like DEs + ovui's Settings dialog) with
            # Cancel after it. A trailing ``_INNER_PADDING`` spacer
            # keeps the pair off the right edge.
            with ui.HStack(height=ui.Pixel(_BUTTON_HEIGHT)):
                ui.Spacer()
                ui.Button(
                    "OK",
                    width=ui.Pixel(_BUTTON_WIDTH),
                    height=ui.Pixel(_BUTTON_HEIGHT),
                    style_type_name_override="OKButton",
                    clicked_fn=self._on_ok_clicked,
                )
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))
                ui.Button(
                    "Cancel",
                    width=ui.Pixel(_BUTTON_WIDTH),
                    height=ui.Pixel(_BUTTON_HEIGHT),
                    style_type_name_override="CancelButton",
                    clicked_fn=self._on_cancel_clicked,
                )
                ui.Spacer(width=ui.Pixel(_INNER_PADDING))

            ui.Spacer(height=ui.Pixel(_INNER_PADDING))

    # ── Handlers ─────────────────────────────────────────────────────────

    def _on_field_key_pressed(
        self, key: int, mod: int, pressed: bool,
    ) -> None:
        """Route Enter / Escape while the field has focus.

        omni.ui dispatches ``key_pressed`` on both press and release;
        we act on the release edge so the field's internal edit pipeline
        (commit-on-enter, clear-on-escape) has finished by the time we
        read the value. The ``mod`` bitmask is ignored — Enter / Escape
        with any modifier still dismisses; the alternative (requiring
        plain Enter) makes the dialog fiddly when a shift or alt sneaks
        in from an IME.
        """
        if pressed:
            return
        if key == _KEY_ESCAPE:
            self._on_cancel_clicked()
            return
        if key in (_KEY_ENTER, _KEY_KEYPAD_ENTER):
            self._on_ok_clicked()
            return

    def _on_ok_clicked(self) -> None:
        """Read the field value, fire ``on_ok``, dismiss.

        The value is stripped by the caller, not here — dialog stays
        neutral to every validation rule (the caller might legitimately
        want leading / trailing whitespace for a different prompt
        context; e.g. a future "Enter tag:" reuse). Dispatch order is
        ``on_ok`` first, dismiss second, so an ``on_ok`` handler that
        wants to inspect the still-live window (e.g. to measure its
        frame for a follow-up popup anchor) can still reach it. In
        practice no caller does this; the ordering is a cheap
        guarantee for future flexibility.
        """
        value = ""
        if self._field is not None:
            try:
                value = self._field.model.get_value_as_string()
            except Exception:  # noqa: BLE001
                # Defensive: ovui may raise if the field was torn down
                # under us between the click and the value read (e.g.
                # a destroy() racing with the clicked_fn dispatch).
                value = ""
        handler = self._on_ok
        self._dismiss(fire_ok=False)
        if handler is not None:
            handler(value)

    def _on_cancel_clicked(self) -> None:
        """Dismiss without firing ``on_ok``."""
        self._dismiss(fire_ok=False)

    def _dismiss(self, fire_ok: bool) -> None:
        """Hide + destroy the popup and drop every ovui reference.

        ``fire_ok`` is retained as a parameter for symmetry with
        :meth:`_on_ok_clicked` (which reads the value and fires on_ok
        *before* calling :meth:`_dismiss`) — passing ``True`` would be
        an alternative flow where the caller hands the value straight
        to this method. Kept as ``False`` at every current call site;
        the hook exists for the eventual Step-33 rename dialog if its
        dispatch order needs to invert.
        """
        field = self._field
        window = self._window
        self._field = None
        self._window = None
        if field is not None:
            try:
                field.set_key_pressed_fn(None)
            except Exception:  # noqa: BLE001
                # Already torn down by ovui — drop silently.
                pass
        if window is not None:
            try:
                window.visible = False
            except Exception:  # noqa: BLE001
                # ovui may raise if the window was already hidden by
                # a sibling path (e.g. ``WINDOW_FLAGS_POPUP`` auto-
                # dismiss); the subsequent destroy() still runs.
                pass
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                # ovui may raise if the window was re-entered during
                # teardown; further destroy() calls are no-ops.
                pass
        if fire_ok and self._on_ok is not None:
            # Currently unreachable from any caller — see docstring.
            self._on_ok("")

    # ── Test hooks ───────────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        """``True`` while the popup window is live; ``False`` post-dismiss."""
        return self._window is not None

    def _set_value_for_test(self, value: str) -> None:
        """Overwrite the StringField value — test-only hook.

        Exposed so tests can drive the OK path without simulating a
        real text-entry sequence through ovui. Silent no-op if the
        field does not exist (pre-show / post-dismiss).
        """
        if self._field is None:
            return
        try:
            self._field.model.set_value(value)
        except Exception:  # noqa: BLE001
            pass

    def _fire_ok_for_test(self) -> None:
        """Invoke the OK handler — test-only hook.

        Drives :meth:`_on_ok_clicked` directly so tests can bypass the
        ``ui.Button`` click dispatch (which is opaque to a non-ovui
        test harness). Silent no-op post-dismiss.
        """
        if self._window is None:
            return
        self._on_ok_clicked()

    def _fire_cancel_for_test(self) -> None:
        """Invoke the Cancel handler — test-only hook."""
        if self._window is None:
            return
        self._on_cancel_clicked()

    def _fire_key_for_test(self, key: int) -> None:
        """Drive the field's key handler — test-only hook."""
        if self._window is None:
            return
        self._on_field_key_pressed(key, 0, False)
