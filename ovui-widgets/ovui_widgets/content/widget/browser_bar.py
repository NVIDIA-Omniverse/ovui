# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""BrowserBar — back/forward + :class:`PathField` + visited-history.

Step 19 (the content browser implementation step D, the content browser behavior). Wraps a
:class:`PathField` with two navigation buttons on the left (back /
forward) bound to a linear :class:`VisitedHistory` cursor. The widget
is the top-of-pane navigation row that Step 20 will drop into
:class:`FileBrowserWidget`'s layout.

The bar owns no backend reference and does not validate paths. The
caller's ``apply_path_handler`` remains authoritative: back/forward
clicks decide which URL the user wants, the bar echoes that URL into
its :class:`PathField` and fires the caller's apply handler. The
caller is then free to navigate the actual backend; when navigation
succeeds and the caller re-calls :meth:`BrowserBar.set_path`, the
history's ``_is_navigating`` latch consumes the resulting ``insert``
so the back/forward roundtrip does not re-enter its own trail.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

import omni.ui as ui

from ovui_widgets.common.style.urls import get_icon_path
from ovui_widgets.content.widget.path_field import _PATH_FIELD_HEIGHT, PathField

# Resolve the chevron navigation-icon URLs to absolute filesystem paths at import
# time. The ovui build in use has two known image-loading pitfalls:
# ``ui.StringStore.find`` does not resolve registered shade names, and
# ``ui.Button(image_url=path)``'s internal image loader drops draws on
# stb_image retry. The reliable path is
# :class:`ui.ImageWithProvider` with a cached
# :class:`ui.RasterImageProvider`, layered in a :class:`ui.ZStack`
# behind a textless :class:`ui.Button` that owns the click area.
_ARROW_LEFT_PATH = get_icon_path("content_arrow_left")
_ARROW_RIGHT_PATH = get_icon_path("content_arrow_right")

# Cached providers keyed by absolute path. Mirrors the pattern in
# :mod:`ovui_widgets.content.widget.file_browser_delegate` so the
# two callsites share the same cache keying — a future extraction of
# the helper into ``ovui_widgets.app.style`` or ``ovui_widgets.app.ui_utils`` would fold
# them together. Two nav buttons means at most two providers resident.
_PROVIDER_CACHE: Dict[str, "ui.RasterImageProvider"] = {}


def _provider(path: str) -> "ui.RasterImageProvider":
    """Return a cached :class:`ui.RasterImageProvider` for ``path``.

    Duplicate of the private ``_provider`` in
    :mod:`ovui_widgets.content.widget.file_browser_delegate`;
    kept local here so the nav-button icon rendering does not reach
    across the delegate's module boundary. See that module's
    ``_PROVIDER_CACHE`` comment block for the rationale.
    """
    prov = _PROVIDER_CACHE.get(path)
    if prov is None:
        prov = ui.RasterImageProvider(path)
        _PROVIDER_CACHE[path] = prov
    return prov


# Navigation button sizing. 28x28 mirrors the Step 15 retry button's
# height (``_RETRY_BUTTON_HEIGHT = 28``) so the toolbar row reads as a
# single row regardless of which chrome block is visible. Icon is
# shrunk inside the frame to leave ~4 px of padding around the glyph —
# matches the Stage Browser's toolbar button metric.
_NAV_BUTTON_WIDTH = 28
_NAV_BUTTON_HEIGHT = 28
_NAV_BUTTON_ICON_SIZE = 16
_PATH_FIELD_CENTERING_HEIGHT = 32
_PATH_FIELD_TOP_SPACER = 3
_PATH_FIELD_BOTTOM_SPACER = (
    _PATH_FIELD_CENTERING_HEIGHT - _PATH_FIELD_TOP_SPACER - _PATH_FIELD_HEIGHT
)

# Horizontal gap between the back / forward / path-field children of
# the outer HStack. Matches the Stage Browser toolbar's 4-px gutter.
_TOOLBAR_SPACING = 4


class VisitedHistory:
    """Linear visited-URL log with a cursor for back/forward navigation.

    Model matches the content browser behavior: the most recent
    entry sits at index 0 (:meth:`insert` prepends). :attr:`_cursor`
    is the index currently displayed to the user — ``0`` right after
    an insert, or ``+1`` after a back click. :meth:`go_back` advances
    the cursor toward older entries; :meth:`go_forward` rewinds toward
    newer entries.

    :meth:`insert` skips only **consecutive** duplicates — the same
    URL re-entering after a different URL produces a fresh entry. The
    task-brief canonical sequence ``["/A", "/B", "/A", "/B", "/A"]``
    yields five entries because the head never matches the incoming
    URL at the moment of insertion.

    The :attr:`_is_navigating` latch is set by :meth:`go_back` /
    :meth:`go_forward` and consumed by the next :meth:`insert` call —
    the caller's apply-handler round-trip (``apply_path`` ->
    ``BrowserBar.set_path`` -> ``history.insert``) would otherwise
    re-record the back-navigation target, polluting the trail. The
    flag self-clears on consumption so a subsequent user-driven
    navigation inserts normally.
    """

    def __init__(self, max_size: int = 100) -> None:
        if max_size < 1:
            raise ValueError(
                f"VisitedHistory.max_size must be >= 1, got {max_size}"
            )
        self._max_size = max_size
        # History is stored newest-first: index 0 is the most recently
        # inserted URL, higher indices are older. Choosing prepend over
        # append matches §15.4's ``_selected_index = 0`` contract and
        # keeps :meth:`go_back` / :meth:`go_forward` arithmetic
        # symmetric (both step the cursor by one, opposite signs).
        self._history: List[str] = []
        # Cursor into :attr:`_history`. ``-1`` when empty; otherwise
        # always a valid index. After :meth:`insert` the cursor lands
        # at ``0`` (the freshly-prepended URL).
        self._cursor: int = -1
        # Suppression latch for the insert that immediately follows a
        # back/forward navigation. Set True by go_back / go_forward,
        # cleared (and consumed) by the next insert.
        self._is_navigating: bool = False

    # ── Public API ───────────────────────────────────────────────────────────

    def insert(self, value: str) -> None:
        """Prepend ``value`` to the history; no-op if suppressed or dup.

        Four short-circuit guards, in order:

        1. ``_is_navigating`` — set by :meth:`go_back` /
           :meth:`go_forward`; consumed here so the back-navigation's
           own re-apply round-trip does not re-insert the URL. The flag
           clears after consumption.
        2. Empty / falsy input — silently dropped. Mirrors
           :meth:`PathField.set_path`'s empty-input policy and keeps
           the trail clean of invariant-breaking entries.
        3. Consecutive duplicate at the current cursor position
           (``value == _history[_cursor]``) — dropped. After a back
           navigation the cursor points into the middle of the trail,
           so checking index 0 would miss the correct neighbour.
        4. Forward-history truncation — when the cursor is mid-trail
           (``_cursor > 0``), drop everything newer than the cursor
           before prepending. A user navigating to a *new* location
           after a back click abandons the old forward path; leaving
           it in place would corrupt later back clicks, sending the
           user into a branch they explicitly left.
        """
        if self._is_navigating:
            self._is_navigating = False
            return
        if not value:
            return
        if (
            self._history
            and 0 <= self._cursor < len(self._history)
            and self._history[self._cursor] == value
        ):
            # Re-insert of the current cursor position — no-op. Covers
            # the plain "same folder re-applied" case as well as the
            # mid-history "apply round-trip after a back click" case
            # where the target equals the cursor's URL.
            return
        # Forward-history truncation. When ``_cursor > 0`` the entries
        # at indices ``[0, _cursor)`` are the forward trail the user
        # just abandoned by choosing a new destination. Drop them so
        # the next back click returns to the pre-insert cursor position
        # rather than stepping into the stale branch.
        if self._cursor > 0:
            self._history = self._history[self._cursor:]
        self._history.insert(0, value)
        self._cursor = 0
        # Trim to ``max_size`` by dropping the tail (oldest entries).
        # Slice-replace rather than pop in a loop — the truncation is
        # a one-shot bound, not a repeated amortisation, and slicing
        # keeps the invariant visible at a glance.
        if len(self._history) > self._max_size:
            self._history = self._history[: self._max_size]

    def go_back(self) -> Optional[str]:
        """Advance the cursor toward older entries; return the URL or ``None``.

        Sets :attr:`_is_navigating` before returning so the caller's
        apply-path round-trip does not re-insert the URL. No-op and
        returns ``None`` when :attr:`can_go_back` is false.
        """
        if not self.can_go_back:
            return None
        self._cursor += 1
        self._is_navigating = True
        return self._history[self._cursor]

    def go_forward(self) -> Optional[str]:
        """Rewind the cursor toward newer entries; return the URL or ``None``.

        Mirrors :meth:`go_back`. Sets :attr:`_is_navigating` to
        suppress the caller's apply round-trip re-insert. No-op and
        returns ``None`` when :attr:`can_go_forward` is false.
        """
        if not self.can_go_forward:
            return None
        self._cursor -= 1
        self._is_navigating = True
        return self._history[self._cursor]

    @property
    def can_go_back(self) -> bool:
        """True when at least one older entry exists past :attr:`_cursor`."""
        return self._cursor + 1 < len(self._history)

    @property
    def can_go_forward(self) -> bool:
        """True when :attr:`_cursor` is not already at the newest entry."""
        return self._cursor > 0

    def size(self) -> int:
        """Current number of entries in the history."""
        return len(self._history)


class BrowserBar:
    """Back/forward buttons + :class:`PathField` in a single HStack.

    Construction builds the widget immediately into the surrounding
    ``with`` build block — same contract as :class:`PathField` and
    :class:`FileBrowserWidget`. After construction the caller may call
    :meth:`set_path` at any time to update the path field and record
    the navigation in the history.

    Handlers (passed through to the inner :class:`PathField`):

    * ``apply_path_handler(path)`` — fired by :class:`PathField` on
      Enter / breadcrumb click, and by this widget on back / forward
      button click. The caller should validate / navigate.
    * ``autocomplete_handler(prefix, callback)`` — optional. Proxied
      straight through to the :class:`PathField` popup (Step 18).
    * ``begin_edit_handler()`` — optional. Proxied to the
      :class:`PathField` popup open event (Step 17).
    """

    def __init__(
        self,
        apply_path_handler: Callable[[str], None],
        autocomplete_handler: Optional[
            Callable[[str, Callable[[List[str]], None]], None]
        ] = None,
        begin_edit_handler: Optional[Callable[[], None]] = None,
        visited_history_max: int = 100,
    ) -> None:
        self._apply_path_handler = apply_path_handler
        self._autocomplete_handler = autocomplete_handler
        self._begin_edit_handler = begin_edit_handler

        # Visited-URL trail drives back/forward. Created before
        # :meth:`build` so :meth:`_update_nav_buttons` can read it
        # while building the initial disabled state.
        self._history = VisitedHistory(max_size=visited_history_max)

        # Widget refs — populated by :meth:`build`, cleared by
        # :meth:`destroy`. ``None`` pre-build / post-destroy so
        # callbacks guard defensively against teardown races.
        self._hstack: Optional[ui.HStack] = None
        self._back_button: Optional[ui.Button] = None
        self._forward_button: Optional[ui.Button] = None
        self._path_field_centering_stack: Optional[ui.VStack] = None
        self._path_field: Optional[PathField] = None

        self.build()

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build the back/forward + path-field row into the build context.

        Layout is a single :class:`ui.HStack` whose first two children
        are navigation :class:`ui.Button` s with chevron icons, followed
        by the :class:`PathField` which consumes the remaining width.
        The HStack carries the ``Content.ToolBar`` style name so the
        theme layer paints it with the toolbar background tint.
        """
        self._hstack = ui.HStack(
            spacing=_TOOLBAR_SPACING,
            style_type_name_override="Content.ToolBar",
        )
        with self._hstack:
            # Back / forward buttons. ``enabled=False`` at build time —
            # :meth:`_update_nav_buttons` flips them on as soon as the
            # history has entries. Each button is a :class:`ui.ZStack`
            # of [``ui.Button`` click target, ``ui.ImageWithProvider``
            # glyph] because :class:`ui.Button`'s own ``image_url``
            # slot drops draws on the PNG-retry path in this ovui
            # build (see comment at module top). The button carries a
            # single-space label so it takes a glyph-row's worth of
            # height — see :meth:`_build_nav_button` for the rationale.
            # The ``Content.ToolBar.Button`` style + ``.Image`` selector
            # paint the hover / pressed / disabled states without this
            # module hardcoding colours; the image layer is
            # non-interactive and inherits its tint from the same
            # style block.
            self._back_button = self._build_nav_button(
                icon_path=_ARROW_LEFT_PATH,
                on_click=self.go_back,
            )
            self._forward_button = self._build_nav_button(
                icon_path=_ARROW_RIGHT_PATH,
                on_click=self.go_forward,
            )
            # PathField consumes the remaining horizontal space. Pass
            # handlers through verbatim — this widget is a composition
            # layer, not a mediator. The caller's apply-path handler
            # sees breadcrumb clicks and Enter applies as the same
            # events a bare :class:`PathField` would dispatch.
            self._path_field_centering_stack = ui.VStack(
                height=_PATH_FIELD_CENTERING_HEIGHT,
            )
            with self._path_field_centering_stack:
                ui.Spacer(height=_PATH_FIELD_TOP_SPACER)
                self._path_field = PathField(
                    apply_path_handler=self._apply_path_handler,
                    autocomplete_handler=self._autocomplete_handler,
                    begin_edit_handler=self._begin_edit_handler,
                )
                ui.Spacer(height=_PATH_FIELD_BOTTOM_SPACER)

    def _build_nav_button(
        self, icon_path: str, on_click: Callable[[], None],
    ) -> ui.Button:
        """Build a single nav button (click area + icon layer in a ZStack).

        The click area is a :class:`ui.Button` with a single-space label
        (see the paragraph further down for why a space rather than
        ``""``) and no image. The icon is a :class:`ui.ImageWithProvider`
        layered on top via a :class:`ui.ZStack` so the image does not
        need to traverse ovui's :meth:`ui.Button.image_url` loader —
        that path drops draws on stb_image retry in this ovui build
        (same issue worked around in :mod:`file_browser_delegate`'s
        chevron rendering).

        Returns the :class:`ui.Button` because the outer caller only
        needs to mutate :attr:`ui.Button.enabled` — the image layer
        reacts to the ``Content.ToolBar.Button:disabled`` style
        variant via the :attr:`name`-less selector chain.

        The button text is a single space rather than the empty string.
        A ``ui.Button("")`` in this ovui build has no glyph-row baseline
        to size against and collapses to ~8 px high regardless of the
        surrounding :class:`ui.ZStack`'s declared ``height``, leaving
        the hit rect well below the centred 16-px icon the overlay
        paints near y≈14 inside the 28-px frame. Hovers over the icon
        would then miss the button entirely. A single-space label gives
        the button a font-sized intrinsic height that stretches to fill
        the 28-px frame, keeping the hit rect flush with the painted
        icon region. The space is not visible because the ``Image``
        overlay sits on top and the button carries no ``color`` style
        for its own label glyph.
        """
        with ui.ZStack(
            width=_NAV_BUTTON_WIDTH,
            height=_NAV_BUTTON_HEIGHT,
        ):
            button = ui.Button(
                " ",
                enabled=False,
                clicked_fn=on_click,
                style_type_name_override="Content.ToolBar.Button",
            )
            # Image layer — non-interactive overlay. Centred by
            # wrapping the fixed-size image inside a VStack+HStack
            # spacer sandwich so the 16-px glyph sits in the middle
            # of the 28-px button rather than anchoring to the top-
            # left corner the ZStack would otherwise imply.
            with ui.VStack():
                ui.Spacer()
                with ui.HStack(height=_NAV_BUTTON_ICON_SIZE):
                    ui.Spacer()
                    ui.ImageWithProvider(
                        _provider(icon_path),
                        width=_NAV_BUTTON_ICON_SIZE,
                        height=_NAV_BUTTON_ICON_SIZE,
                        style_type_name_override=(
                            "Content.ToolBar.Button.Image"
                        ),
                    )
                    ui.Spacer()
                ui.Spacer()
        return button

    # ── Public API ───────────────────────────────────────────────────────────

    def set_path(self, path: str) -> None:
        """Record ``path`` in history and update the :class:`PathField`.

        Call this from the caller's apply-path round-trip whenever the
        backend has actually navigated (or from any other authoritative
        state-change point). The insert is suppressed when it happens
        inside a back/forward round-trip — see
        :attr:`VisitedHistory._is_navigating`.

        Order: insert into history first, then update the path field,
        then refresh the nav button enabled states. Swapping the first
        two would not matter (both are passive data updates) but
        keeping :meth:`_update_nav_buttons` after the insert is
        required — the ``enabled`` flags read from the history's
        post-insert state.
        """
        self._history.insert(path)
        if self._path_field is not None:
            self._path_field.set_path(path)
        self._update_nav_buttons()

    def go_back(self) -> None:
        """Step the history cursor back and echo the target URL.

        Three-step dispatch: (1) pull the back-target URL from the
        history (which sets the ``_is_navigating`` latch so the
        following apply round-trip does not re-insert the URL); (2)
        update the :class:`PathField` so the bar visually reflects the
        back click immediately, not after the async apply; (3) fire
        the caller's ``apply_path_handler`` which should validate and
        navigate the backend. ``_update_nav_buttons`` runs last so
        toggling reflects the post-cursor-move state.
        """
        target = self._history.go_back()
        if target is None:
            return
        if self._path_field is not None:
            self._path_field.set_path(target)
        if self._apply_path_handler is not None:
            self._apply_path_handler(target)
        self._update_nav_buttons()

    def go_forward(self) -> None:
        """Step the history cursor forward and echo the target URL.

        Mirror of :meth:`go_back`. Same three-step dispatch against
        :meth:`VisitedHistory.go_forward`.
        """
        target = self._history.go_forward()
        if target is None:
            return
        if self._path_field is not None:
            self._path_field.set_path(target)
        if self._apply_path_handler is not None:
            self._apply_path_handler(target)
        self._update_nav_buttons()

    # ── Nav button state ─────────────────────────────────────────────────────

    def _update_nav_buttons(self) -> None:
        """Sync the back / forward button ``enabled`` flags to the history.

        Called after every mutation of :attr:`_history`'s cursor (from
        :meth:`set_path`, :meth:`go_back`, :meth:`go_forward`). The
        ``None`` guards cover the post-destroy teardown path where a
        straggling callback might reach here after the widget refs
        have been nulled.
        """
        if self._back_button is not None:
            self._back_button.enabled = self._history.can_go_back
        if self._forward_button is not None:
            self._forward_button.enabled = self._history.can_go_forward

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Release widget refs; tear down the inner :class:`PathField`.

        Idempotent — the ``is not None`` guards short-circuit a second
        call. The :class:`PathField`'s own :meth:`destroy` handles its
        popup / subscription cleanup; this method only nulls the
        references held on ``self`` so the outer HStack and button
        handles are collectable.
        """
        if self._path_field is not None:
            self._path_field.destroy()
            self._path_field = None
        self._back_button = None
        self._forward_button = None
        self._path_field_centering_stack = None
        self._hstack = None
        # Drop handler refs last — a pending callback sneaking through
        # the guards above then falls through silently.
        self._apply_path_handler = None  # type: ignore[assignment]
        self._autocomplete_handler = None
        self._begin_edit_handler = None


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovui_widgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_PROVIDER_CACHE)
