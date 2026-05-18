# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""PathField — dual-mode breadcrumb / inline text-edit navigation widget.

Step 17 (the content browser implementation step D, the content browser behavior§15.11)
plus the Bug-Fix refactor that replaced the popup edit window with an
inline :class:`ui.StringField`. Renders the current directory URL as a
horizontal strip of clickable breadcrumb buttons in BREADCRUMB mode;
double-click on the strip swaps the breadcrumbs out for a visible,
focused :class:`ui.StringField` carrying the current full path. Enter
applies the typed path, Escape / focus-loss reverts without applying.

The widget owns no backend reference and does not validate paths —
that contract lives with the caller's ``apply_path_handler`` per
the content browser behavior The widget is pure layout +
tokenization + click dispatch + mode state.

Not wired into the browser bar or content-window toolbar yet —
Step 19 / 20 compose this widget with back/forward/combo / import /
filter chrome. Autocomplete dropdown rendering is co-located in a
small anchor :class:`ui.Window` opened during EDIT mode.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Tuple

import omni.ui as ui

# Mode state tokens. BREADCRUMB is the default render (segments +
# separators); EDIT shows the inline :class:`ui.StringField`. Kept as
# module-level string constants so the values read as named intent at
# callsites and so a future move to an ``enum.Enum`` only touches the
# tokens here and the ``_mode`` attribute itself.
MODE_BREADCRUMB = "BREADCRUMB"
MODE_EDIT = "EDIT"

# Autocomplete popup window identifier. ovui keys windows by title —
# the string itself is hidden behind :data:`WINDOW_FLAGS_NO_TITLE_BAR`
# but still needs to be unique per widget instance, so it is suffixed
# with ``id(self)`` at construction time.
_AUTOCOMPLETE_WINDOW_TITLE_PREFIX = "OvGear_PathField_Autocomplete_"

# Autocomplete window chrome flags. ``POPUP`` means clicking outside
# dismisses it (ImGui/ovui contract). ``NO_TITLE_BAR`` / ``NO_MOVE``
# strip chrome so the dropdown reads as an overlay rather than a
# floating dialog. The window keeps its default ImGui background so
# the dropdown has an opaque backing; the interior styling is painted
# by the :class:`ui.Rectangle` backdrop plus the per-row
# :class:`ui.Button` fills — see :meth:`_open_autocomplete_anchor`.
_AUTOCOMPLETE_POPUP_FLAGS = (
    ui.WINDOW_FLAGS_NO_TITLE_BAR
    | ui.WINDOW_FLAGS_NO_MOVE
    | ui.WINDOW_FLAGS_NO_RESIZE
    | ui.WINDOW_FLAGS_NO_SCROLLBAR
    | ui.WINDOW_FLAGS_NO_DOCKING
    | ui.WINDOW_FLAGS_POPUP
)

# Autocomplete dropdown sizing. Width matches the stage filter's
# autocomplete; the dropdown window is allocated with enough height
# for a fully-populated list so ovui does not need to re-layout on
# row-count changes.
_AUTOCOMPLETE_WIDTH = 480

# Breadcrumb separator label. A unicode forward-slash surrounded by
# thin spaces reads as a real visual separator between segments
# rather than a clickable segment itself. Styled
# :class:`Content.Breadcrumb.Separator` — colour + font_size come
# from the theme rather than being hardcoded here.
_BREADCRUMB_SEPARATOR = " / "

# Keyboard codes. omni.ui's :meth:`ui.StringField.set_key_pressed_fn`
# passes raw ImGui key codes — these literals match the Stage Browser
# rename field's use of ``27`` for Escape / ``257`` and ``335`` for
# Enter (main + keypad). Kept as module constants so the values read
# as named intent at the callsite and so a future move to an
# ``ImGuiKey`` enum only touches this block.
_KEY_ESCAPE = 256
_KEY_ENTER = 257
_KEY_TAB = 258
_KEY_KEYPAD_ENTER = 335
_KEY_DOWN = 264
_KEY_UP = 265
# GLFW reports printable keys as their uppercase ASCII code regardless
# of shift state (glfw3.h). ovui passes the value through verbatim.
_KEY_V = ord("V")

# Modifier bitmask values — identical across the ovui key-pressed
# callback, :class:`carb.input.KEYBOARD_MODIFIER_FLAG_*`, and
# :class:`omni.ui.kKeyMod*` (see ``ovui/core/include/omni/ui/Types.h``).
_KEY_MOD_CTRL = 1 << 1

# Autocomplete tuning. ``_AUTOCOMPLETE_MAX_VISIBLE`` caps the dropdown
# at 10 entries — matches the content browser behavior's
# ``tooltips_max_visible`` default. ``_AUTOCOMPLETE_ROW_HEIGHT`` sizes
# one dropdown row; the popup window is allocated with enough height
# for a fully-populated dropdown so ovui does not need to re-layout on
# row-count changes.
_AUTOCOMPLETE_MAX_VISIBLE = 10
_AUTOCOMPLETE_ROW_HEIGHT = 22

# Extra vertical slack around the dropdown rows. Covers the outer
# Rectangle's border + a small visual margin so the bottom row does
# not kiss the window edge.
_AUTOCOMPLETE_WINDOW_PADDING = 8

# Address/path field height. Matches ``SearchField._FIELD_HEIGHT`` so the
# address bar and search pill read as the same control family in the Content
# toolbar.
_PATH_FIELD_HEIGHT = 24
_PATH_FIELD_FILL_HEIGHT = 22

# Inline edit-field height. Sized to match the address pill so the path bar's
# overall footprint does not jump between BREADCRUMB and EDIT mode.
_EDIT_FIELD_HEIGHT = _PATH_FIELD_HEIGHT


class PathField:
    """Breadcrumb / inline text-edit dual-mode field for a directory URL.

    Construction builds the widget immediately into the surrounding
    ``with`` build block — same contract as
    :class:`FileBrowserWidget` and the Stage Browser's widgets. After
    construction the caller may call :meth:`set_path` at any time to
    update the breadcrumb labels; the current path is always readable
    via the :attr:`path` property.

    The three handlers (all called from the main ovui thread):

    * ``apply_path_handler(path)`` — fired on Enter in edit mode, on
      click of a breadcrumb segment, and on paste-dismiss. The caller
      should validate and/or navigate to ``path``.
    * ``autocomplete_handler(prefix, callback)`` — optional. Step 18
      wires this to a backend listing; Step 17 defines the parameter
      but does not invoke the callback.
    * ``begin_edit_handler()`` — optional. Fired once per edit-mode
      entry so the toolbar can cancel in-flight navigation tasks that
      would conflict with user editing.

    Mode state:

    * :data:`MODE_BREADCRUMB` — breadcrumb segments visible, edit
      field hidden, overlay rectangle catches double-clicks.
    * :data:`MODE_EDIT` — breadcrumb hidden, edit field visible and
      focused, overlay rectangle hidden so the field receives typing.
    """

    def __init__(
        self,
        apply_path_handler: Callable[[str], None],
        autocomplete_handler: Optional[
            Callable[[str, Callable[[List[str]], None]], None]
        ] = None,
        begin_edit_handler: Optional[Callable[[], None]] = None,
        prefix_separator: str = "file://",
    ) -> None:
        self._apply_path_handler = apply_path_handler
        self._autocomplete_handler = autocomplete_handler
        self._begin_edit_handler = begin_edit_handler
        # ``prefix_separator`` may be empty — in which case tokenization
        # never strips a URL-scheme prefix, and the widget shows raw
        # path segments. Empty is a valid caller choice for plain-POSIX
        # style content browsers.
        self._prefix_separator = prefix_separator or ""

        # Current path, always the most recent value passed to
        # :meth:`set_path` (or the empty string before the first call).
        # The breadcrumb HStack is re-materialised on every update
        # rather than mutated in place — keeps the update path simple
        # at the cost of O(n) breadcrumb rebuilds, which is fine for
        # typical depths (≤10 segments).
        self._path = ""

        # Previous tokenized path — used by :meth:`_rebuild_breadcrumbs`
        # to decide whether the new path is deeper (auto-scroll to tail
        # so the current folder is visible) or shorter/parent (reset
        # scroll to 0 so ancestor segments remain clickable rather than
        # being pinned off-screen to the left).
        self._previous_tokens: List[str] = []

        # Latched in :meth:`set_path` *before* the deferred frame
        # rebuild fires, then consumed by :meth:`_rebuild_breadcrumbs`
        # to decide scroll direction. We cannot recompute this from
        # ``_previous_tokens`` inside the build callback: by then
        # ``_previous_tokens`` has been replaced with the new token
        # list, so the comparison would always short-circuit to "same".
        self._went_up: bool = False

        # Mode state. :data:`MODE_BREADCRUMB` is the default; flipped
        # to :data:`MODE_EDIT` by :meth:`_enter_edit_mode` and back by
        # :meth:`_exit_edit_mode`. Read by tests and by the external
        # QA harness (``tests/qa_addressbar_repro.py``) to verify the
        # inline edit swap actually happened.
        self._mode: str = MODE_BREADCRUMB

        # Widget refs — populated by :meth:`build`, cleared by
        # :meth:`destroy`. Each is ``None`` pre-build / post-destroy so
        # callbacks guard defensively against races where a pending
        # callback fires after ``destroy``.
        self._scrolling_frame: Optional[ui.ScrollingFrame] = None
        self._zstack: Optional[ui.ZStack] = None
        self._border_rect: Optional[ui.Rectangle] = None
        self._fill_rect: Optional[ui.Rectangle] = None
        # Bug 3 — the breadcrumb container is a :class:`ui.Frame` with a
        # ``set_build_fn``, not a bare :class:`ui.HStack`. This matters
        # because breadcrumb button clicks fire their ``clicked_fn``
        # during ovui's draw dispatch, and ``HStack.clear()`` +
        # ``with HStack:`` inside a draw callback emits
        # ``Container::clear was called during an event or draw``
        # warnings and leaves the new children at zero size. Using
        # :meth:`ui.Frame.rebuild` tells ovui to re-run the build
        # function at a safe time (the next paint pass), so the
        # breadcrumb row re-materialises correctly after a click.
        self._breadcrumb_frame: Optional[ui.Frame] = None
        # Inner HStack built each rebuild. Kept as an attribute so
        # diagnostic tooling (the QA harness, tests) can inspect the
        # current stack ref — the reference is replaced on every
        # :meth:`_rebuild_breadcrumbs` pass.
        self._breadcrumb_stack: Optional[ui.HStack] = None
        # Inline edit field — visible only in :data:`MODE_EDIT`. Carries
        # the editable URL text and owns the Enter/Escape/Tab key
        # handler. Swapped in on double-click of the overlay rectangle;
        # swapped out on Enter / Escape / focus-loss.
        self._edit_field: Optional[ui.StringField] = None
        # Transparent hit target — sits on top of the breadcrumb layer
        # and catches double-clicks that toggle into edit mode. Hidden
        # while in :data:`MODE_EDIT` so keyboard events reach
        # :attr:`_edit_field`. Single clicks fall through to the
        # breadcrumb buttons via ovui's button-priority hit-testing —
        # same mechanism the prior popup design relied on.
        self._overlay_rect: Optional[ui.Rectangle] = None

        # Latch to break a re-entrancy cycle during EDIT → BREADCRUMB
        # transition: :meth:`ui.StringField.model.add_end_edit_fn`
        # fires on every transition away from editing (Enter, Escape,
        # focus-loss), including the programmatic ``focus_keyboard(False)``
        # we issue inside :meth:`_exit_edit_mode`. Without the latch,
        # exit would re-enter via the end_edit callback.
        self._is_exiting: bool = False

        # One-shot latch consumed by the next :meth:`_on_edit_end_edit`.
        # Set by :meth:`_commit_autocomplete_selection` because committing
        # an autocomplete row rewrites the field value (triggering ovui's
        # end_edit for Tab) but the user has NOT signalled "apply" — the
        # commit extends the path in place so the user can keep typing.
        # Without the latch, end_edit's apply would exit edit mode and
        # navigate prematurely.
        self._suppress_end_edit: bool = False

        # Subscription handles held on ``self`` so the C++ side does
        # not keep the widget alive via the callback slot. Released in
        # :meth:`destroy`.
        self._edit_value_changed_sub: Optional[Any] = None
        self._edit_end_edit_sub: Optional[Any] = None

        # Autocomplete state. The container lives in its own transient
        # ui.Window anchored below the edit field, opened on
        # :meth:`_enter_edit_mode` and destroyed on :meth:`_exit_edit_mode`.
        # Keeps the dropdown floating above the toolbar without needing
        # the ScrollingFrame to make room for it.
        self._autocomplete_window: Optional[ui.Window] = None
        self._autocomplete_container: Optional[ui.VStack] = None

        # Step 18 — paste short-circuit (OM-75838). Latched on Ctrl+V
        # key press in the edit field; consumed on the next value-
        # changed dispatch which then skips the autocomplete handler
        # (a full URL paste never wants a listing of some partial
        # intermediate prefix). See the content browser behavior
        self._is_paste: bool = False

        # Step 18 — autocomplete dropdown state. ``_autocomplete_matches``
        # holds the current list of candidate names (already filtered
        # by ``match_str`` and truncated to ``_AUTOCOMPLETE_MAX_VISIBLE``);
        # ``_autocomplete_selected`` indexes into it, ``-1`` when
        # nothing is highlighted (Down will then select the first
        # entry, Up the last). ``_autocomplete_match_str`` is the
        # suffix-after-last-slash of the current input — kept as state
        # so the async callback path can re-filter the handler's
        # response without re-parsing the field.
        self._autocomplete_matches: List[str] = []
        self._autocomplete_selected: int = -1
        self._autocomplete_match_str: str = ""

        self.build()

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build the path-bar UI into the current ovui build context.

        Layout is::

            ZStack (border + fill + horizontal-only ScrollingFrame)
              └── ScrollingFrame (style=Content.PathBar.ScrollingFrame)
                    └── ZStack
                          ├── Frame (breadcrumbs — visible in BREADCRUMB mode)
                          ├── StringField (inline editor — visible in EDIT mode)
                          └── Rectangle (transparent overlay; catches double-
                                         click; visible in BREADCRUMB mode)

        The overlay rectangle sits on top so a double-click anywhere on
        the empty path-bar pixels triggers :meth:`_enter_edit_mode`.
        ovui's hit-testing prefers the explicit click area of a
        :class:`ui.Button` inside its occupied pixels, so breadcrumb
        buttons underneath still receive their single-click navigation
        events — same mechanism the pre-refactor hidden StringField
        overlay relied on.
        """
        with ui.ZStack(height=_PATH_FIELD_HEIGHT):
            self._border_rect = ui.Rectangle(
                style_type_name_override="Content.PathBar.Border",
            )
            with ui.VStack():
                ui.Spacer(height=1)
                with ui.HStack():
                    ui.Spacer(width=1)
                    self._fill_rect = ui.Rectangle(
                        height=_PATH_FIELD_FILL_HEIGHT,
                        style_type_name_override="Content.PathBar",
                    )
                    ui.Spacer(width=1)
                ui.Spacer(height=1)
            self._scrolling_frame = ui.ScrollingFrame(
                horizontal_scrollbar_policy=(
                    ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED
                ),
                vertical_scrollbar_policy=(
                    ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF
                ),
                style_type_name_override="Content.PathBar.ScrollingFrame",
            )
            with self._scrolling_frame:
                self._zstack = ui.ZStack(height=_PATH_FIELD_HEIGHT)
                with self._zstack:
                    # Breadcrumb Frame — underneath the overlay rectangle.
                    # The build callback is driven by
                    # :meth:`ui.Frame.rebuild` rather than a sync rebuild,
                    # so clicks on a breadcrumb button (which dispatch
                    # during ovui's draw) can safely mutate the breadcrumb
                    # tree. See the ``_breadcrumb_frame`` note in
                    # :meth:`__init__` for the full reasoning.
                    self._breadcrumb_frame = ui.Frame()
                    self._breadcrumb_frame.set_build_fn(
                        self._rebuild_breadcrumbs,
                    )

                    # Inline edit field — same Z-slot as the breadcrumb
                    # frame, visibility-toggled between the two. The
                    # ``Content.PathBar.EditField`` style paints an opaque
                    # background + focused border so the typed path is
                    # clearly legible; the breadcrumb frame is hidden
                    # during EDIT so there is no stacked text underneath.
                    self._edit_field = ui.StringField(
                        visible=False,
                        height=_EDIT_FIELD_HEIGHT,
                        style_type_name_override="Content.PathBar.EditField",
                    )
                    self._edit_field.set_key_pressed_fn(
                        self._on_edit_key_pressed,
                    )
                    self._edit_value_changed_sub = (
                        self._edit_field.model.add_value_changed_fn(
                            self._on_edit_value_changed,
                        )
                    )
                    self._edit_end_edit_sub = (
                        self._edit_field.model.add_end_edit_fn(
                            self._on_edit_end_edit,
                        )
                    )

                    # Transparent overlay — on top of the ZStack, catches
                    # double-clicks that flip into edit mode. Its fill is
                    # transparent (``Content.PathBar.Overlay`` uses the
                    # shared transparent token palette);
                    # breadcrumb single-clicks reach the button layer
                    # underneath because ovui routes explicit ``Button``
                    # hit areas before falling through to a bare Rectangle.
                    self._overlay_rect = ui.Rectangle(
                        style_type_name_override="Content.PathBar.Overlay",
                    )
                    self._overlay_rect.set_mouse_double_clicked_fn(
                        self._on_overlay_double_clicked,
                    )

    def _rebuild_breadcrumbs(self) -> None:
        """Build the breadcrumb row inside :attr:`_breadcrumb_frame`.

        Registered as the frame's ``build_fn`` via
        :meth:`ui.Frame.set_build_fn`, which means ovui invokes this
        during a safe paint-time pass — not synchronously from
        :meth:`set_path`. Callers that want the row to re-materialise
        trigger :meth:`ui.Frame.rebuild` on :attr:`_breadcrumb_frame`
        instead of calling this method directly.

        Emits a fresh :class:`ui.HStack` holding alternating clickable
        breadcrumb labels and styled separator labels (``Label, Label, Label,
        Label, Label``). An empty path yields an empty stack (no
        breadcrumbs, no separators) — matches the widget's constructor
        initial state.

        Scroll direction comes from :attr:`_went_up`, latched by
        :meth:`set_path` *before* the rebuild fires.
        """
        tokens = self._tokenize(self._path)
        # Always re-seat the HStack reference so external inspectors
        # (QA harness, tests) see the currently-rendered stack rather
        # than a stale ref from the previous rebuild.
        self._breadcrumb_stack = ui.HStack(spacing=0)
        with self._breadcrumb_stack:
            for idx, label in enumerate(tokens):
                if idx > 0:
                    ui.Label(
                        _BREADCRUMB_SEPARATOR,
                        width=0,
                        style_type_name_override="Content.Breadcrumb.Separator",
                    )
                # Each label captures its index via default-arg
                # binding rather than closure-over-loop-variable. The
                # accumulated path is computed on click from the
                # current ``_path`` state, so the cached index stays
                # valid across subsequent ``set_path`` calls that
                # happen before the click.
                breadcrumb = ui.Label(
                    label,
                    width=0,
                    style_type_name_override="Content.Breadcrumb",
                )
                breadcrumb.set_mouse_pressed_fn(
                    lambda _x, _y, button, _mod, i=idx: (
                        self._on_breadcrumb_clicked(i) if button == 0 else None
                    )
                )
        # Bug 3: only pin the view to the trailing breadcrumb when the
        # user navigates deeper or into a sibling/unrelated path. When
        # the new path is a prefix of the previous one (parent
        # navigation), reset scroll to 0 so the ancestor segments
        # remain visible and clickable rather than being hidden off
        # the left edge. The initial build (no prior ``set_path``) has
        # ``_went_up=False`` so a freshly-opened deep path lands pinned
        # to the tail, matching the content browser behavior
        frame = self._scrolling_frame
        if frame is not None and hasattr(frame, "scroll_x_max"):
            try:
                frame.scroll_x = 0 if self._went_up else frame.scroll_x_max
            except Exception:  # pragma: no cover  (ovui runtime quirks)
                # ovui's scroll-position setter can fault during the
                # first build pass before layout is measured. The tail
                # remains out of view until the user scrolls manually;
                # the call is a UX nicety, not a correctness hook.
                pass

    # ── Public API ───────────────────────────────────────────────────────────

    def set_path(self, path: str) -> None:
        """Update the current path and re-render the breadcrumbs.

        Does not fire :attr:`_apply_path_handler` — the caller is the
        one driving the state here, and re-firing would cause a loop.
        Also does not validate the path; validation is the caller's
        job (the content browser behavior). Whitespace / empty
        input is rendered as zero breadcrumbs.

        Bug 3 — the rebuild is *deferred* via :meth:`ui.Frame.rebuild`
        rather than invoked synchronously, so this method is safe to
        call from a breadcrumb button's ``clicked_fn`` (which dispatches
        during ovui's draw pass). Token bookkeeping — ``_path``,
        ``_previous_tokens``, ``_went_up`` — updates synchronously so
        any caller that immediately reads those attributes (tests, the
        accumulated-path click handler) sees the new state without
        waiting for the deferred build to paint.
        """
        new_path = path or ""
        new_tokens = self._tokenize(new_path)
        self._went_up = (
            len(new_tokens) < len(self._previous_tokens)
            and self._previous_tokens[: len(new_tokens)] == new_tokens
        )
        self._path = new_path
        self._previous_tokens = list(new_tokens)
        frame = self._breadcrumb_frame
        if frame is not None:
            frame.rebuild()

    @property
    def path(self) -> str:
        """Read the current path string — last value passed to :meth:`set_path`."""
        return self._path

    # ── Tokenization ─────────────────────────────────────────────────────────

    def _tokenize(self, full_path: str) -> List[str]:
        """Split a path into visible breadcrumb labels.

        Behaviour:

        * Strip :attr:`_prefix_separator` if the path starts with it;
          the prefix itself is kept as the first token.
        * Split the remainder on ``/``.
        * Drop empty segments (produced by a leading ``/`` on Linux
          absolute paths, or a repeated ``//``).
        * Preserve Windows drive letters (``C:``) as a first segment
          rather than eating the colon.

        Examples::

            /home/user/docs       → ["home", "user", "docs"]
            file:///home/user     → ["file://", "home", "user"]
            C:/Users/jack         → ["C:", "Users", "jack"]
            mock://Home/Docs      → ["mock://", "Home", "Docs"]  (with prefix="mock://")
            ""                    → []
        """
        prefix, segments, _ = self._parse_path(full_path)
        if prefix:
            return [prefix] + segments
        return segments

    def _parse_path(
        self, full_path: str,
    ) -> Tuple[str, List[str], bool]:
        """Split ``full_path`` into (prefix, non-empty segments, is_absolute).

        The third element is a bit that remembers whether the original
        path had a leading ``/`` after the prefix — needed to
        reconstruct absolute URLs like ``file:///home`` from the
        segment list ``["home"]`` in :meth:`_accumulated_path`.
        """
        if not full_path:
            return "", [], False
        prefix = ""
        rest = full_path
        if (
            self._prefix_separator
            and full_path.startswith(self._prefix_separator)
        ):
            prefix = self._prefix_separator
            rest = full_path[len(prefix):]
        is_absolute = rest.startswith("/")
        segments = [seg for seg in rest.split("/") if seg]
        return prefix, segments, is_absolute

    def _accumulated_path(self, index: int) -> str:
        """Reconstruct the navigate-to path up to breadcrumb ``index``.

        ``index`` addresses the visible breadcrumb list produced by
        :meth:`_tokenize` — i.e., ``index=0`` for the URL prefix (if
        present) else the first directory segment.

        Invariants:

        * Clicking the prefix token (e.g. ``file://``) navigates to
          just the prefix — the caller's navigate handler is
          expected to interpret that as "the URL-scheme root".
        * Clicking a Linux-absolute path segment preserves the
          leading ``/``.
        * Clicking a Windows drive-letter segment produces
          ``"C:/"`` (with trailing slash) so the caller can treat it
          as a directory URL rather than a file reference. Matches
          the content browser behavior's "clicking 'C:' navigates
          to ``file:///C:/``" rule, minus the ``file://`` prefix when
          the caller didn't set one.
        """
        prefix, segments, is_absolute = self._parse_path(self._path)
        if prefix and index == 0:
            return prefix
        segment_index = (index - 1) if prefix else index
        if segment_index < 0 or segment_index >= len(segments):
            return self._path
        joined = "/".join(segments[:segment_index + 1])
        if prefix:
            # Preserve the ``file:///home`` vs ``mock://Home`` distinction:
            # an absolute original path had its leading ``/`` eaten when
            # we filtered empty segments, so we re-insert one.
            if is_absolute:
                return prefix + "/" + joined
            return prefix + joined
        # No prefix. Windows drive letter is the only case where the
        # first segment ends with ``:`` — reconstruct as ``C:/rest``
        # with a trailing slash when clicked alone.
        if is_absolute:
            joined = "/" + joined
        if segment_index == 0 and segments[0].endswith(":"):
            return joined + "/"
        return joined

    # ── Breadcrumb click ─────────────────────────────────────────────────────

    def _on_breadcrumb_clicked(self, index: int) -> None:
        """Fire :attr:`_apply_path_handler` with the accumulated path.

        The handler itself updates :attr:`_path` (via the caller's
        navigate-to → :meth:`set_path` round-trip), so this method
        does **not** call :meth:`set_path` directly — the caller is
        authoritative on which path actually got navigated to (a
        permission error might veto the click).
        """
        target = self._accumulated_path(index)
        if self._apply_path_handler is not None:
            self._apply_path_handler(target)

    # ── Overlay double-click → enter edit mode ──────────────────────────────

    def _on_overlay_double_clicked(
        self,
        _x: Any,
        _y: Any,
        button: Any,
        _mod: Any,
    ) -> None:
        """Dispatch a left-button double-click as an edit-mode entry.

        ovui's ``set_mouse_double_clicked_fn`` fires for any mouse
        button; only the left button (``0``) is a meaningful trigger
        for text entry. Right / middle double-clicks are ignored so
        the context menu / middle-click behaviors the grid layer
        installs on neighbouring widgets are not accidentally
        shadowed here.
        """
        if int(button) != 0:
            return
        self._enter_edit_mode()

    # ── Edit mode transitions ───────────────────────────────────────────────

    def _enter_edit_mode(self) -> None:
        """Swap the breadcrumb strip for the inline editable field.

        Idempotent on re-entry — a second call while already in
        :data:`MODE_EDIT` short-circuits. Pre-populates the field with
        the current :attr:`_path`, focuses it, hides the breadcrumb
        frame + overlay so the field owns the visual strip, and opens
        the autocomplete dropdown anchor window so the Step 18
        autocomplete pipeline has somewhere to render.

        Fires :attr:`_begin_edit_handler` once per successful entry so
        the outer toolbar can cancel any in-flight navigation that
        would conflict with the user's keystrokes.
        """
        if self._mode == MODE_EDIT:
            return
        if self._edit_field is None:
            return
        self._mode = MODE_EDIT

        if self._breadcrumb_frame is not None:
            self._breadcrumb_frame.visible = False
        if self._overlay_rect is not None:
            self._overlay_rect.visible = False
        self._edit_field.visible = True

        # Seed the field value with the current path. Any synchronous
        # value-change dispatch this kicks is handled in
        # :meth:`_on_edit_value_changed` — it compares the fresh value
        # against :attr:`_path` and short-circuits when they match,
        # so opening the edit surface never fires an autocomplete
        # roundtrip for the already-committed path.
        self._edit_field.model.set_value(self._path)

        focus_keyboard = getattr(self._edit_field, "focus_keyboard", None)
        if focus_keyboard is not None:
            focus_keyboard(True)

        self._open_autocomplete_anchor()

        if self._begin_edit_handler is not None:
            self._begin_edit_handler()

    def _exit_edit_mode(self, apply: bool) -> None:
        """Swap the inline field out and return to breadcrumb rendering.

        ``apply=True`` reads the field's current value and dispatches
        it to the caller's apply handler; the caller is responsible
        for validating the path and calling :meth:`set_path` if the
        navigation succeeds. ``apply=False`` drops the user's draft
        silently — no breadcrumb change, no navigate.

        Idempotent — a second call while already in
        :data:`MODE_BREADCRUMB` short-circuits. The ``_is_exiting``
        latch additionally breaks the re-entry cycle that arises when
        ``focus_keyboard(False)`` triggers the end-edit subscription
        which in turn calls back here.
        """
        if self._mode != MODE_EDIT:
            return
        if self._is_exiting:
            return
        self._is_exiting = True
        try:
            typed_value = ""
            field = self._edit_field
            if field is not None:
                try:
                    typed_value = field.model.get_value_as_string()
                except Exception:  # pragma: no cover — defensive
                    typed_value = ""
                field.visible = False
                blur = getattr(field, "focus_keyboard", None)
                if blur is not None:
                    blur(False)

            if self._breadcrumb_frame is not None:
                self._breadcrumb_frame.visible = True
            if self._overlay_rect is not None:
                self._overlay_rect.visible = True

            self._close_autocomplete_anchor()
            self._hide_autocomplete()
            self._is_paste = False
            self._mode = MODE_BREADCRUMB

            if (
                apply
                and typed_value
                and self._apply_path_handler is not None
            ):
                self._apply_path_handler(typed_value)
        finally:
            self._is_exiting = False

    # ── Keyboard + value-change on the inline edit field ─────────────────────

    def _on_edit_key_pressed(
        self, key: int, mod: int, pressed: bool,
    ) -> None:
        """Handle keyboard input inside the inline edit field.

        Mirrors the rename-field pattern used by :mod:`file_browser_delegate`:

        * **Escape on press** — pre-empts ovui's ``end_edit`` by flipping
          mode to ``BREADCRUMB`` first. The subsequent end_edit fires
          but short-circuits on the mode check in :meth:`_exit_edit_mode`.
          Processing on press is load-bearing: if we waited for release,
          ovui's synchronous end_edit (between press and release for
          Enter) would reach :meth:`_on_edit_end_edit` first and apply
          the draft as a committed path, which is not what the user
          meant by pressing Escape.
        * **Enter on press AND release** — either commits the highlighted
          autocomplete row into the field or applies the typed path.
          Handling both edges gives robustness against ovui event
          ordering — the second call short-circuits on the mode check.
        * **Tab on press AND release** — only commits an autocomplete
          selection if one is highlighted; stays in edit mode so the
          user can keep drilling. The commit latches
          :attr:`_suppress_end_edit` so the ovui end_edit that follows
          Tab does not re-interpret the commit as an apply.
        * **Ctrl+V on press** — latches :attr:`_is_paste` so the next
          value-change dispatch (fired by ovui's paste) skips the
          autocomplete round-trip. See §15.7 OM-75838.
        * **Down / Up on release** — autocomplete selection cycling;
          release-only so key autorepeat does not tear through the list.
        """
        if pressed and key == _KEY_V and (mod & _KEY_MOD_CTRL):
            self._is_paste = True
            return
        if key == _KEY_ESCAPE:
            self._exit_edit_mode(apply=False)
            return
        if key in (_KEY_ENTER, _KEY_KEYPAD_ENTER):
            if self._autocomplete_selected >= 0:
                self._commit_autocomplete_selection()
                return
            self._exit_edit_mode(apply=True)
            return
        if key == _KEY_TAB:
            if self._autocomplete_selected >= 0:
                self._commit_autocomplete_selection()
            return
        if pressed:
            return
        if key == _KEY_DOWN:
            self._cycle_autocomplete(+1)
            return
        if key == _KEY_UP:
            self._cycle_autocomplete(-1)
            return

    def _on_edit_end_edit(self, _model: Any) -> None:
        """Apply the typed value — primary commit path.

        ``end_edit`` fires on Enter, Tab, and plain focus-loss
        (clicking outside the field). Ovui's rename-field pattern
        (:mod:`file_browser_delegate`) uses end_edit as the commit
        signal; this widget follows the same contract so Enter → apply
        works regardless of whether ovui dispatches end_edit before or
        after our key-pressed handler.

        * Escape pre-empts by flipping mode to ``BREADCRUMB`` via the
          key-pressed handler; the :meth:`_exit_edit_mode` mode-check
          short-circuits this call.
        * Autocomplete commit (Tab + selection, or the Enter path
          before exit) latches :attr:`_suppress_end_edit`; we consume
          and return so the committed-but-not-exited edit continues.
        """
        if self._suppress_end_edit:
            self._suppress_end_edit = False
            return
        self._exit_edit_mode(apply=True)

    # ── Autocomplete (Step 18) ───────────────────────────────────────────────

    def _on_edit_value_changed(self, model: Any) -> None:
        """Route typing into the autocomplete handler.

        Short-circuits when :attr:`_is_paste` is set: §15.7 (OM-75838)
        says a Ctrl+V just happened, so a full URL is about to live in
        the field. Firing the autocomplete handler would trigger a
        remote listing for some partial prefix of that URL — wasted
        work. We simply drop the dropdown and let the user commit
        with Enter.

        For normal typing, we split the current input on the last
        separator into ``(committed_prefix, match_str)``, call the
        handler with the committed prefix, and filter the handler's
        response against ``match_str`` in :meth:`_on_autocomplete_results`.
        """
        if self._mode != MODE_EDIT:
            return
        value = model.get_value_as_string()
        # Seed-value short-circuit: :meth:`_enter_edit_mode` calls
        # ``model.set_value(self._path)`` to pre-populate the field.
        # ovui may fire a synchronous value-change for that seed; we
        # drop it here so opening the edit surface does not kick an
        # autocomplete roundtrip on the already-committed path. A
        # user who pastes the same path back also gets no roundtrip —
        # an acceptable edge case since there is nothing to advance.
        if value == self._path:
            return
        if self._is_paste:
            self._is_paste = False
            self._hide_autocomplete()
            return
        if self._autocomplete_handler is None:
            return
        if self._autocomplete_container is None:
            return
        prefix, match_str = self._split_for_autocomplete(value)
        self._autocomplete_match_str = match_str
        self._autocomplete_handler(prefix, self._on_autocomplete_results)

    @staticmethod
    def _split_for_autocomplete(value: str) -> Tuple[str, str]:
        """Return ``(committed_prefix, match_str)`` for autocomplete.

        Split on the last ``/`` per the content browser behavior
        Input with no separator leaves ``committed_prefix=""`` and the
        whole string as ``match_str`` — the handler will typically
        return no matches for an empty prefix, which is the correct
        behaviour for an in-progress URL-scheme (``file:``) where no
        directory listing is available yet.
        """
        idx = value.rfind("/")
        if idx < 0:
            return "", value
        return value[: idx + 1], value[idx + 1 :]

    def _on_autocomplete_results(self, entries: List[str]) -> None:
        """Filter handler results and rebuild the dropdown.

        ``entries`` is the raw name list returned by the caller's
        handler (e.g., every sub-folder of the committed prefix). We
        filter to names that case-insensitively start with the current
        match_str, truncate to :data:`_AUTOCOMPLETE_MAX_VISIBLE`, reset
        the selection cursor, and re-render.

        No-op post-destroy — :attr:`_autocomplete_container` is
        ``None`` and the short-circuit keeps a late-arriving callback
        from raising on a dead widget.
        """
        if self._autocomplete_container is None:
            return
        match = self._autocomplete_match_str.lower()
        filtered = [name for name in entries if name.lower().startswith(match)]
        self._autocomplete_matches = filtered[:_AUTOCOMPLETE_MAX_VISIBLE]
        self._autocomplete_selected = -1
        self._rebuild_autocomplete()

    def _open_autocomplete_anchor(self) -> None:
        """Open the floating :class:`ui.Window` that hosts the dropdown.

        Created lazily on entry to EDIT mode so the window does not
        linger over the toolbar when the user is simply browsing.
        Sized to hold a fully-populated dropdown so ovui does not need
        to re-layout when the match count changes.

        Layout inside the window is ``ZStack(backdrop Rectangle + VStack)``
        so the dropdown reads as a proper popup menu with a solid
        opaque background — prior to this the window carried
        ``NO_BACKGROUND`` and the VStack rendered bare labels over
        whatever pixels sat under the path bar. The Rectangle carries
        the ``Content.PathBar.Autocomplete`` style which supplies the
        background colour, border, and radius from the theme palette.
        """
        if self._autocomplete_window is not None:
            return
        title = f"{_AUTOCOMPLETE_WINDOW_TITLE_PREFIX}{id(self)}"
        height = _AUTOCOMPLETE_MAX_VISIBLE * _AUTOCOMPLETE_ROW_HEIGHT
        self._autocomplete_window = ui.Window(
            title,
            width=_AUTOCOMPLETE_WIDTH,
            height=height,
            flags=_AUTOCOMPLETE_POPUP_FLAGS,
        )
        with self._autocomplete_window.frame:
            with ui.ZStack():
                ui.Rectangle(
                    style_type_name_override="Content.PathBar.Autocomplete",
                )
                self._autocomplete_container = ui.VStack(visible=False)

    def _close_autocomplete_anchor(self) -> None:
        """Tear down the autocomplete anchor window built by :meth:`_open_autocomplete_anchor`.

        Symmetric with :meth:`_open_autocomplete_anchor`; drops the
        :attr:`_autocomplete_container` ref first so a late
        value-change dispatch during teardown falls through the
        ``None`` guard in :meth:`_on_edit_value_changed`.
        """
        self._autocomplete_container = None
        window = self._autocomplete_window
        self._autocomplete_window = None
        if window is not None:
            try:
                window.visible = False
            except Exception:  # pragma: no cover — ovui may raise if already hidden
                pass
            try:
                window.destroy()
            except Exception:  # pragma: no cover — ovui may raise if re-entered
                pass

    def _rebuild_autocomplete(self) -> None:
        """Re-materialise the dropdown VStack from ``_autocomplete_matches``.

        Each entry becomes a clickable :class:`ui.Button` row so mouse
        clicks commit the selection and apply-navigate to it (Bug C —
        Victor's "clicking a suggestion should change directory").
        The currently keyboard-highlighted row carries the
        ``Content.PathBar.Autocomplete.Item::selected`` variant so the
        theme paints it with the accent colour; the others use
        ``Content.PathBar.Autocomplete.Item``. An empty match list
        hides the container — no empty dropdown frame, no wasted
        screen real estate.
        """
        container = self._autocomplete_container
        if container is None:
            return
        container.clear()
        if not self._autocomplete_matches:
            container.visible = False
            return
        with container:
            for idx, name in enumerate(self._autocomplete_matches):
                style = (
                    "Content.PathBar.Autocomplete.Item::selected"
                    if idx == self._autocomplete_selected
                    else "Content.PathBar.Autocomplete.Item"
                )
                ui.Button(
                    name,
                    height=_AUTOCOMPLETE_ROW_HEIGHT,
                    alignment=ui.Alignment.LEFT_CENTER,
                    style_type_name_override=style,
                    clicked_fn=lambda i=idx: self._on_autocomplete_row_clicked(i),
                )
        container.visible = True
        # Shrink the popup window to match the actual row count so the
        # dropdown does not leave an empty backdrop strip below the
        # last match when the list is shorter than
        # :data:`_AUTOCOMPLETE_MAX_VISIBLE`.
        window = self._autocomplete_window
        if window is not None:
            try:
                window.height = (
                    len(self._autocomplete_matches) * _AUTOCOMPLETE_ROW_HEIGHT
                    + _AUTOCOMPLETE_WINDOW_PADDING
                )
            except Exception:  # pragma: no cover — ovui window may refuse resize
                pass

    def _on_autocomplete_row_clicked(self, idx: int) -> None:
        """Click on a dropdown row — commit the selection and navigate.

        Same contract as pressing Enter while ``idx`` is keyboard-
        highlighted: the committed row's path replaces the ``match_str``
        suffix, and the resulting extended URL is dispatched to the
        caller's apply handler. Unlike the keyboard path, a click ends
        edit mode immediately — the user made an explicit pick, the
        usual "Tab to drill, Enter to apply" two-step does not apply
        to pointer input.
        """
        if idx < 0 or idx >= len(self._autocomplete_matches):
            return
        self._autocomplete_selected = idx
        self._commit_autocomplete_selection()
        self._exit_edit_mode(apply=True)

    def _hide_autocomplete(self) -> None:
        """Clear the dropdown state and hide its container.

        Used by the paste short-circuit and by edit-mode exit.
        Separate from :meth:`_rebuild_autocomplete` so the empty-state
        path (no matches yet) and the clear-everything path (close
        dropdown outright) don't get conflated.
        """
        self._autocomplete_matches = []
        self._autocomplete_selected = -1
        self._autocomplete_match_str = ""
        if self._autocomplete_container is not None:
            self._autocomplete_container.clear()
            self._autocomplete_container.visible = False

    def _cycle_autocomplete(self, direction: int) -> None:
        """Advance the dropdown selection by ``direction`` (±1).

        Wraps at both ends. Moving Down from no selection lands on the
        first entry; Up from no selection lands on the last.
        Re-renders the dropdown so the new selection highlights.
        """
        n = len(self._autocomplete_matches)
        if n == 0:
            return
        if self._autocomplete_selected < 0:
            self._autocomplete_selected = 0 if direction > 0 else n - 1
        else:
            self._autocomplete_selected = (
                self._autocomplete_selected + direction
            ) % n
        self._rebuild_autocomplete()

    def _commit_autocomplete_selection(self) -> None:
        """Replace the match_str tail with the selected dropdown entry.

        The edit field currently holds ``<committed_prefix><match_str>``;
        we swap ``match_str`` for the highlighted entry (which already
        carries its trailing ``/`` per the ``_path_autocomplete``
        contract). The dropdown then hides — the next value-change
        dispatch will re-fire the handler for the newly-committed
        directory, so the user can continue typing to drill deeper.

        Latches :attr:`_suppress_end_edit` so the ovui ``end_edit`` that
        Tab (and clipboard-driven value mutations) dispatch synchronously
        does not re-read the just-committed field value as a user apply.
        Callers that want the commit to *also* apply (mouse click on a
        suggestion, Enter with a selection) consume the latch by calling
        :meth:`_exit_edit_mode(apply=True)` directly — that path bypasses
        :meth:`_on_edit_end_edit` and always applies.
        """
        if self._autocomplete_selected < 0:
            return
        if self._edit_field is None:
            return
        selected = self._autocomplete_matches[self._autocomplete_selected]
        current = self._edit_field.model.get_value_as_string()
        idx = current.rfind("/")
        new_value = (
            current[: idx + 1] + selected if idx >= 0 else selected
        )
        self._suppress_end_edit = True
        self._edit_field.model.set_value(new_value)
        self._hide_autocomplete()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Release widget refs and drop every subscription handle.

        Idempotent — the ``is not None`` guards short-circuit a second
        call. Order matters: drop callback subscriptions first so the
        C++ side does not call back into a half-nulled widget during
        teardown, then exit edit mode (if any), then null every
        widget ref.
        """
        # Drop the value-changed / end-edit subscriptions BEFORE we
        # flip the ``visible`` flag in ``_exit_edit_mode`` — an ovui
        # draw pass might fire end_edit while we tear down otherwise.
        self._edit_value_changed_sub = None
        self._edit_end_edit_sub = None

        # Exit any live edit mode. Call before nulling other refs
        # because :meth:`_exit_edit_mode` itself reads
        # ``self._edit_field`` and ``self._autocomplete_container``.
        if self._mode == MODE_EDIT:
            self._exit_edit_mode(apply=False)

        self._close_autocomplete_anchor()

        if self._edit_field is not None:
            self._edit_field.set_key_pressed_fn(None)

        self._scrolling_frame = None
        self._zstack = None
        self._border_rect = None
        self._fill_rect = None
        self._breadcrumb_frame = None
        self._breadcrumb_stack = None
        self._edit_field = None
        self._overlay_rect = None
        # Step 18: the autocomplete container is nulled inside
        # ``_close_autocomplete_anchor``; belt-and-braces here for the
        # teardown path.
        self._autocomplete_container = None
        self._autocomplete_window = None
        self._autocomplete_matches = []
        self._autocomplete_selected = -1
        self._autocomplete_match_str = ""
        self._is_paste = False
        self._is_exiting = False
        self._suppress_end_edit = False
        self._previous_tokens = []
        self._went_up = False
        self._mode = MODE_BREADCRUMB
        # Drop handler refs last — a pending callback that sneaks
        # through the guards above falls through silently rather than
        # re-entering a teardown-in-progress widget.
        self._apply_path_handler = None  # type: ignore[assignment]
        self._autocomplete_handler = None
        self._begin_edit_handler = None
