# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""SearchField — debounced in-folder substring filter input.

Step 27 (the content browser implementation step F, the content browser behavior). A single-
line search bar: a magnifying-glass glyph on the left, an editable
:class:`ui.StringField` in the middle, and an X clear button on the
right. Every change to the field schedules a 200 ms debounced callback
via :meth:`ovwidgets.app.application.Application.call_later` — typing "dem"
across three frames therefore fires ``on_search("dem")`` once rather
than three times.

Architecture §33.3 notes Kit's content-browser search is server-side
(Nucleus :class:`NGSearch`) and replaces the list view wholesale; the
ovgear widget is simpler — a plain substring filter over the items
already visible in the current folder. The widget owns no model
reference; Step 28 wires ``on_search`` into
:meth:`FileBrowserModel.set_text_filter` when the toolbar composition
lands.

The clear button fires immediately (no debounce) so a user's
intentional "blank the filter" action feels responsive — a 200 ms wait
on an explicit click would register as lag. The internal suppression
latch keeps the :class:`ui.StringField`'s own
``value_changed`` event from double-firing the ``on_search("")``
callback after the clear-induced :meth:`set_value` round-trip.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import omni.ui as ui

from ovwidgets.common.style.urls import get_icon_path

# Debounce window. 200 ms matches the task brief and the generic
# ``editable`` UX budget — long enough to coalesce a burst of
# keystrokes from a fast typist (≈60-80 wpm), short enough that the
# filter feels "live" on pause.
_DEBOUNCE_SECS = 0.2

# Bug 14 — dimensions mirror the stage filter pill in
# :mod:`ovwidgets.stage.widget.stage_widget` so the two fields read as a
# single visual family. ``_BAR_HEIGHT`` is the outer
# ``Content.SearchField.Bar`` strip, ``_FIELD_HEIGHT`` is the inner
# bordered pill, ``_FIELD_FILL_HEIGHT`` is the inner fill rectangle
# inset by the 1 px border spacers, and ``_FIELD_INNER_HEIGHT`` is the
# StringField / placeholder row inside the pill. A 13 px magnifier +
# 12 px clear-X keep the pill feeling compact without clipping either
# glyph against the 1 px border frame.
_BAR_HEIGHT = 32
_FIELD_HEIGHT = 24
_FIELD_FILL_HEIGHT = 22
_FIELD_INNER_HEIGHT = 20
_ICON_SIZE = 13
_CLEAR_BUTTON_SIZE = 12
_CLEAR_CONTAINER_WIDTH = 18

# Side padding inside the outer bar and between icon / field. Matches
# the stage-filter spacers so the glyph sits visually inside the pill
# rather than against either edge.
_SIDE_SPACER = 6
_ICON_LEFT_INSET = 8
_ICON_FIELD_GAP = 6
_CLEAR_RIGHT_INSET = 8


# Cached providers keyed by absolute path. Mirrors the
# :mod:`browser_bar` / :mod:`filter_button` / :mod:`zoom_bar` pattern:
# the ovui build here routes ``ui.Button.image_url`` through an
# stb_image loader that drops draws on retry, so every in-widget glyph
# goes through a cached :class:`ui.RasterImageProvider` pointed at the
# absolute filesystem path.
_PROVIDER_CACHE: Dict[str, "ui.RasterImageProvider"] = {}


def _provider(path: str) -> "ui.RasterImageProvider":
    """Return a cached :class:`ui.RasterImageProvider` for ``path``."""
    prov = _PROVIDER_CACHE.get(path)
    if prov is None:
        prov = ui.RasterImageProvider(path)
        _PROVIDER_CACHE[path] = prov
    return prov


class SearchField:
    """Debounced substring-filter search bar with a clear button.

    Construction builds the widget immediately into the surrounding
    ``with`` build block — same contract as :class:`BrowserBar`,
    :class:`FilterButton`, :class:`ZoomBar`, :class:`FileCard`. After
    construction the caller interacts only through the ``on_search``
    callback it passed in and the :attr:`text` property.

    The single handler:

    * ``on_search(text: str)`` — fired 200 ms after the user stops
      typing, and immediately on a clear-button click. The argument is
      the current field text (empty string after a clear). The
      callback fires on every committed state change, including
      transitions to / from the empty string.

    The callback MUST NOT mutate this widget's field from inside the
    handler. A set-value-from-inside-fire would re-enter
    :meth:`_schedule_debounced_fire` while the outer
    :meth:`Application._on_frame_update` loop is iterating its own
    pending list; the re-scheduled handle is appended mid-iteration
    and the frame loop overwrites the list on exit, silently dropping
    it. Callers that need to reset the field after a filter apply
    should schedule a deferred write via
    :meth:`ovwidgets.app.application.Application.call_later(0.0, ...)`
    themselves so the next frame picks it up cleanly.

    The widget is not wired into the toolbar yet — Step 28 composes it
    with :class:`BrowserBar` / :class:`FilterButton` / :class:`ConfigButton`
    into :class:`FileBrowserWidget`'s top row and routes ``on_search``
    into :meth:`FileBrowserModel.set_text_filter`.
    """

    def __init__(
        self,
        on_search: Callable[[str], None],
    ) -> None:
        self._on_search: Optional[Callable[[str], None]] = on_search

        # Widget refs — populated by :meth:`build`, cleared by
        # :meth:`destroy`. ``None`` pre-build / post-destroy so
        # callbacks guard defensively against teardown races.
        #
        # Bug 14 — layout mirrors the stage filter pill, so we now
        # carry two extra handles: ``_border_rect`` for the outer
        # bordered Rectangle (toggled to ``::focused`` on begin-edit)
        # and ``_placeholder`` for the overlay Label that shows when
        # the field is empty.
        self._frame: Optional[ui.Frame] = None
        self._background: Optional[ui.Rectangle] = None
        self._border_rect: Optional[ui.Rectangle] = None
        self._fill_rect: Optional[ui.Rectangle] = None
        self._hstack: Optional[ui.HStack] = None
        self._search_icon: Optional[ui.ImageWithProvider] = None
        self._field: Optional[ui.StringField] = None
        self._placeholder: Optional[ui.Label] = None
        self._clear_button: Optional[ui.ImageWithProvider] = None
        self._clear_icon: Optional[ui.ImageWithProvider] = None

        # Value-changed subscription handle. Held so the C++ side's
        # bound callback is released on :meth:`destroy` before the
        # field ref is nulled — :mod:`zoom_bar` uses the same idiom
        # for its :meth:`ui.IntSlider.model.add_value_changed_fn`.
        self._value_changed_sub: Any = None

        # Pending debounce handle from :meth:`Application.call_later`.
        # Reset to ``None`` after the callback fires or is cancelled.
        # A fresh keystroke cancels the outstanding handle before
        # scheduling a new one, so at any instant there is at most one
        # **live** (un-cancelled) handle per widget. Already-cancelled
        # handles stay in :class:`Application`'s pending list until the
        # next frame tick drains them — we rely on the frame loop's
        # cancelled-skip check rather than actively removing them.
        self._pending_handle: Any = None

        # Suppression latch for the ``value_changed`` event that fires
        # from inside :meth:`_on_clear`'s programmatic
        # ``model.set_value("")``. Without it, a clear click would
        # enqueue a debounced ``on_search("")`` via the value-changed
        # handler AND fire the direct ``on_search("")`` from the clear
        # handler — double-dispatch with the same value. The latch is
        # a plain bool; ovui is single-threaded and ``set_value`` is a
        # synchronous C++ call, so re-entrant clears are not part of
        # the supported call graph. A future threading model would
        # upgrade this to a counter or a per-call context var.
        self._suppress_change: bool = False

        self.build()

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build the pill-shaped search bar into the current context.

        Bug 14 — layout mirrors the stage filter pill in
        :mod:`ovwidgets.stage.widget.stage_widget` so the two search surfaces
        read as a single visual family. Structure::

            Frame (_BAR_HEIGHT)
            └── ZStack
                ├── Rectangle (Content.SearchField.Bar)
                └── HStack
                    ├── Spacer (_SIDE_SPACER)
                    ├── VStack → ZStack (_FIELD_HEIGHT)
                    │   ├── Rectangle (Content.SearchField.Border)
                    │   ├── VStack → HStack → Rectangle
                    │   │   (Content.SearchField — inset by 1 px
                    │   │    spacers so the border rectangle reads)
                    │   └── HStack
                    │       ├── Spacer (_ICON_LEFT_INSET)
                    │       ├── Image (Content.SearchField.Icon)
                    │       ├── Spacer (_ICON_FIELD_GAP)
                    │       ├── ZStack
                    │       │   ├── StringField
                    │       │   └── Placeholder Label
                    │       ├── ImageWithProvider (clear X, hidden
                    │       │   until text typed)
                    │       └── Spacer (_CLEAR_RIGHT_INSET)
                    └── Spacer (_SIDE_SPACER)

        The double-rectangle pattern (``Content.SearchField.Border``
        behind ``Content.SearchField``) is required because ovui's
        single-Rectangle border render is unreliable — the stage filter
        uses the same trick. The placeholder is a sibling Label set to
        ``visible=False`` once the user has typed anything, and its
        ``mouse_pressed_fn`` focuses the StringField so clicking the
        placeholder text behaves identically to clicking an empty field.
        """
        self._frame = ui.Frame(height=_BAR_HEIGHT)
        with self._frame:
            with ui.ZStack():
                self._background = ui.Rectangle(
                    style_type_name_override="Content.SearchField.Bar",
                )
                self._hstack = ui.HStack()
                with self._hstack:
                    ui.Spacer(width=_SIDE_SPACER)
                    with ui.VStack():
                        ui.Spacer()
                        self._build_pill()
                        ui.Spacer()
                    ui.Spacer(width=_SIDE_SPACER)

    def _build_pill(self) -> None:
        """Build the bordered input pill (matches stage filter)."""
        with ui.ZStack(height=_FIELD_HEIGHT):
            self._border_rect = ui.Rectangle(
                style_type_name_override="Content.SearchField.Border",
            )
            with ui.VStack():
                ui.Spacer(height=1)
                with ui.HStack():
                    ui.Spacer(width=1)
                    self._fill_rect = ui.Rectangle(
                        height=_FIELD_FILL_HEIGHT,
                        style_type_name_override="Content.SearchField",
                    )
                    ui.Spacer(width=1)
                ui.Spacer(height=1)
            with ui.HStack():
                ui.Spacer(width=_ICON_LEFT_INSET)
                self._build_search_icon()
                ui.Spacer(width=_ICON_FIELD_GAP)
                self._build_input_field()
                self._build_clear_button()
                ui.Spacer(width=_CLEAR_RIGHT_INSET)

    def _build_search_icon(self) -> None:
        """Build the left-side magnifying-glass glyph.

        Wrapped in a fixed-width Spacer-sandwich VStack so it vertically
        centres inside the pill without biasing toward either edge.
        """
        icon_path = get_icon_path("content_search")
        with ui.VStack(width=_ICON_SIZE):
            ui.Spacer()
            self._search_icon = ui.ImageWithProvider(
                _provider(icon_path),
                width=_ICON_SIZE,
                height=_ICON_SIZE,
                style_type_name_override="Content.SearchField.Icon",
            )
            ui.Spacer()

    def _build_input_field(self) -> None:
        """Build the :class:`ui.StringField` + placeholder overlay.

        The field and placeholder share a 18 px ZStack. The placeholder
        is a :class:`ui.Label` rendered on top of the field; it's set
        ``visible=False`` once the user has typed anything, and a
        mouse-press on it focuses the underlying field so the whole
        pill reads as a single click target.
        """
        with ui.VStack():
            ui.Spacer()
            with ui.ZStack(height=_FIELD_INNER_HEIGHT):
                self._field = ui.StringField(
                    style_type_name_override="Content.SearchField.Input",
                    height=_FIELD_INNER_HEIGHT,
                )
                self._placeholder = ui.Label(
                    "Search...",
                    style_type_name_override=(
                        "Content.SearchField.Placeholder"
                    ),
                    alignment=ui.Alignment.LEFT_CENTER,
                    height=_FIELD_INNER_HEIGHT,
                )
                self._placeholder.set_mouse_pressed_fn(
                    lambda _x, _y, b, _m: (
                        self._focus_field() if b == 0 else None
                    )
                )
            ui.Spacer()
        self._value_changed_sub = self._field.model.add_value_changed_fn(
            self._on_value_changed,
        )
        # ``:focused`` doesn't fire on a Rectangle, so we mirror the
        # StringField's begin/end-edit model events onto the
        # ``::focused`` name variant imperatively — same pattern the
        # stage filter uses.
        self._field.model.add_begin_edit_fn(self._on_begin_edit)
        self._field.model.add_end_edit_fn(self._on_end_edit)

    def _build_clear_button(self) -> None:
        """Build the right-side X clear glyph.

        In the stage-pattern design the clear is an
        :class:`ui.ImageWithProvider` that handles mouse-press directly
        (no Button wrapper). The glyph is hidden until the user types
        anything — an always-visible X on an empty field reads as
        chrome noise rather than an affordance.
        """
        icon_path = get_icon_path("content_close")
        with ui.VStack(width=_CLEAR_CONTAINER_WIDTH):
            ui.Spacer()
            self._clear_button = ui.ImageWithProvider(
                _provider(icon_path),
                width=_CLEAR_BUTTON_SIZE,
                height=_CLEAR_BUTTON_SIZE,
                style_type_name_override=(
                    "Content.SearchField.Clear.Image"
                ),
                visible=False,
            )
            self._clear_button.set_mouse_pressed_fn(
                lambda _x, _y, b, _m: (
                    self._on_clear() if b == 0 else None
                )
            )
            ui.Spacer()
        # Tests reference ``_clear_icon`` as a separate handle from
        # ``_clear_button``. In the pre-Bug-14 design these were a
        # Button + overlaid Image; the stage-matching design collapses
        # them into a single clickable :class:`ImageWithProvider`, so
        # the two handles point at the same widget. Both refs are
        # cleared by :meth:`destroy`.
        self._clear_icon = self._clear_button

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_value_changed(self, _model: Any) -> None:
        """StringField change — schedule a debounced ``on_search`` fire.

        The ``_suppress_change`` latch is set by :meth:`_on_clear`
        while it programmatically blanks the field; a value-changed
        event dispatched inside that window is an internal side-effect
        of the clear, not a user-driven edit, and the clear path has
        its own direct callback fire. Skipping here prevents the
        double-dispatch that would otherwise emit ``on_search("")``
        twice in rapid succession.
        """
        # Chrome state (clear-X visibility + icon active colour +
        # placeholder visibility) must update on every keystroke,
        # including the programmatic clear, so it runs BEFORE the
        # suppress-latch guard. Skipping the chrome update would leave
        # a stale X visible after a clear.
        self._refresh_chrome()
        if self._suppress_change:
            return
        self._schedule_debounced_fire()

    def _refresh_chrome(self) -> None:
        """Sync clear-X, icon active state, placeholder to current text."""
        has_text = bool(self.text)
        if self._clear_button is not None:
            self._clear_button.visible = has_text
        if self._search_icon is not None:
            # Name variant rather than state — ``:active`` is not a
            # real ovui pseudo-state, and ``name`` is the reliable
            # handle for a user-toggled style.
            self._search_icon.name = "active" if has_text else ""
        if self._placeholder is not None:
            self._placeholder.visible = not has_text

    def _focus_field(self) -> None:
        """Forward a placeholder click into a StringField focus call."""
        if self._field is None:
            return
        focus_keyboard = getattr(self._field, "focus_keyboard", None)
        if focus_keyboard is not None:
            focus_keyboard()

    def _on_begin_edit(self, _model: Any) -> None:
        """StringField gained focus — paint the border as focused."""
        if self._border_rect is not None:
            self._border_rect.name = "focused"
        if self._fill_rect is not None:
            self._fill_rect.name = "focused"

    def _on_end_edit(self, _model: Any) -> None:
        """StringField lost focus — revert the border to the resting name."""
        if self._border_rect is not None:
            self._border_rect.name = ""
        if self._fill_rect is not None:
            self._fill_rect.name = ""

    def _schedule_debounced_fire(self) -> None:
        """Cancel any outstanding handle; schedule a new 200 ms fire.

        When the :class:`ovwidgets.app.application.Application` singleton is
        not available (pure-Python unit tests that do not spin up a
        headless app), we fall back to immediate dispatch — same
        pattern :meth:`FileBrowserModel._schedule_item_changed` uses.
        That keeps the handler path exercisable without the frame
        loop while still honoring the debounce whenever an
        Application is wired up.
        """
        # Cancel any in-flight debounce before enqueuing a fresh one.
        # Without this, rapid typing would enqueue N handles, all of
        # which fire after 200 ms — the whole point of debouncing is to
        # collapse that N down to 1.
        if self._pending_handle is not None:
            self._pending_handle.cancel()
            self._pending_handle = None

        # Late-bind the import so this module does not pull the common
        # scheduler into every static helper call.
        from ovwidgets.common import scheduler as _scheduler

        try:
            self._pending_handle = _scheduler.call_later(
                _DEBOUNCE_SECS, self._fire_callback,
            )
        except RuntimeError:
            # No scheduler registered — dispatch immediately so the
            # handler path stays exercisable in unit tests without a
            # headless fixture. Production code always has a registered
            # scheduler (Application.__init__ does the registration).
            self._fire_callback()
            return

    def _fire_callback(self) -> None:
        """Read the current text and invoke ``on_search``.

        Called from the deferred :meth:`Application.call_later` fire
        (or immediately in the no-Application fallback). The
        ``_pending_handle`` is cleared first so a re-entrant call to
        :meth:`_schedule_debounced_fire` from inside the caller's
        handler cannot try to cancel a handle that ovui's frame loop
        has already consumed.

        Bug 8: a raising ``on_search`` handler would otherwise bubble
        up to :meth:`Application._on_frame_update`, which catches every
        ``call_later`` exception and writes
        ``[ERROR] [Application] call_later callback raised …`` to
        stderr via :class:`ErrorReporter.log_error`. The net effect is
        a Python traceback in the user's terminal on every keystroke
        that hits the failing code path. Catching here routes the
        failure to :meth:`ErrorReporter.show_warning` — surfaced as a
        status-bar message rather than a console traceback — and keeps
        the debounce state machine (``_pending_handle`` already
        cleared) consistent for the next keystroke.
        """
        self._pending_handle = None
        if self._on_search is None:
            return
        self._invoke_on_search(self.text)

    def _invoke_on_search(self, text: str) -> None:
        """Invoke ``on_search`` under a try/except that reports via ErrorReporter.

        Shared by :meth:`_fire_callback` (debounced typing) and
        :meth:`_on_clear` (clear-button click) so neither fire path
        leaks a traceback to stderr when the caller's handler raises.
        The import is deferred so this module does not pull the
        :class:`ErrorReporter` singleton into pure-unit-test imports
        that never build a headless app.
        """
        handler = self._on_search
        if handler is None:
            return
        try:
            handler(text)
        except Exception as exc:  # noqa: BLE001
            from ovwidgets.common.error_reporter import ErrorReporter

            ErrorReporter.show_warning(
                f"Search failed: {type(exc).__name__}: {exc}",
            )

    def _on_clear(self) -> None:
        """Clear button click — blank the field and fire immediately.

        Three ordered effects:

        1. Cancel any outstanding debounce handle — a pending
           ``on_search(partial_text)`` would otherwise fire after the
           clear with a stale value.
        2. Set the field's model to the empty string. The
           ``_suppress_change`` latch is raised around this so the
           ``value_changed`` event emitted by ovui does not enqueue a
           second, debounced ``on_search("")`` — step 3 already fires
           the clear directly.
        3. Invoke ``on_search("")`` immediately so the caller's filter
           pipe reacts without the 200 ms debounce delay (an explicit
           clear is not a typo — there's nothing to coalesce).
        """
        # Order matters: cancel the debounce before mutating the
        # field so a racing value-changed dispatch cannot re-schedule
        # after we've wiped the text.
        if self._pending_handle is not None:
            self._pending_handle.cancel()
            self._pending_handle = None

        if self._field is not None:
            self._suppress_change = True
            try:
                self._field.model.set_value("")
            finally:
                self._suppress_change = False

        # Bug 8: same stderr-leak concern as :meth:`_fire_callback` —
        # a raising handler during an explicit clear would surface as
        # a console traceback because :meth:`_on_clear` is wired to
        # the button's synchronous ``clicked_fn`` (no debounce
        # intermediary to catch it). Route through the shared
        # invocation helper so the error lands in the status bar.
        self._invoke_on_search("")

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def text(self) -> str:
        """Return the current field text, or ``""`` post-destroy.

        Reads directly from the :class:`ui.StringField`'s model so a
        caller that queries right after a programmatic
        :meth:`ui.StringField.model.set_value` sees the fresh value
        rather than a cached copy. After :meth:`destroy` the field
        ref is ``None`` and the property returns the empty string.
        """
        if self._field is None:
            return ""
        return self._field.model.get_value_as_string()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Cancel any pending debounce; release widget refs.

        Idempotent — the ``is not None`` guards short-circuit a second
        call. Order matters: cancel the debounce handle first so a
        late fire from the frame loop cannot reach a half-nulled
        widget, then drop the value-changed subscription handle so
        the C++ side stops dispatching into ``_on_value_changed``,
        then null every widget ref, then finally drop the handler
        reference so a late callback that sneaks through the guards
        above falls through silently.
        """
        if self._pending_handle is not None:
            self._pending_handle.cancel()
            self._pending_handle = None

        # Dropping the subscription handle releases ovui's internal
        # bound callback. There is no explicit removal API in this
        # ovui build (``add_value_changed_fn`` has no ``remove_``
        # counterpart — same pattern :mod:`zoom_bar` uses for its
        # slider subscription).
        self._value_changed_sub = None

        self._clear_icon = None
        self._clear_button = None
        self._placeholder = None
        self._field = None
        self._search_icon = None
        self._hstack = None
        self._fill_rect = None
        self._border_rect = None
        self._background = None
        self._frame = None

        # Drop the handler ref last — a late callback that sneaks
        # through the guards above then falls through silently.
        self._on_search = None


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovwidgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_PROVIDER_CACHE)
