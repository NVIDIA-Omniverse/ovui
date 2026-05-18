# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FileCard — single grid card widget (the content browser implementation step 21).

See the content browser behavior (``FileBrowserItemCard``) for the
reference structure this widget mirrors. A :class:`FileCard` renders
one :class:`FileItem` as a thumbnail-plus-label tile for the grid view
:class:`FileGridView` builds in Step 22.

The card is a small, self-contained composition:

* A :class:`ui.Rectangle` hit target carries the ``Content.Card`` style
  and catches mouse events. The :attr:`ui.Rectangle.selected` pseudo-
  state drives the ``Content.Card:selected`` selector so
  :meth:`set_selected` is just a one-line state flip.
* An image area layered as a :class:`ui.ZStack` of two buffers — a
  back buffer rendering the default asset-category icon for
  ``item.icon_key`` (via :class:`ui.ImageWithProvider`), and a front
  buffer that :meth:`set_thumbnail` wakes up when a custom thumbnail
  URL arrives (Step 25). Matches the architecture's back/front split.
* A :class:`ui.Label` below the image, ``word_wrap=False``, with the
  full item name bound to its tooltip. Container width is clipped to
  ``size`` so long names visibly truncate; the tooltip is the escape
  hatch for reading the full string.

No clipboard integration yet: the ``Content.Card.Label::cut`` variant
wires up in Step 38.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

import omni.ui as ui

from ovwidgets.common.style.urls import get_icon_path
from ovwidgets.content.widget import clipboard
from ovwidgets.content.widget.file_item import FileItem
from ovwidgets.content.widget.highlight_label import HighlightLabel

if TYPE_CHECKING:
    from ovwidgets.content.widget.drop_indicator import DropIndicator
    from ovwidgets.content.widget.rename_controller import (
        RenameController,
    )


# Bottom-row label height. Matches the ``+20`` row-height offset
# the content browser implementation step 22 uses for the grid's row_height — keeping the
# label band fixed at 18 px here lets the grid compute its row height
# as ``card_size + _LABEL_HEIGHT`` symmetrically with what the card
# actually renders.
_LABEL_HEIGHT = 18

# Step 36 — style-variant name passed as :class:`ui.Widget.name` to
# paint the dimmed ``::cut`` variant of ``Content.Card.Image`` and
# ``Content.Card.Label`` (see :mod:`ovwidgets.content.style`).
# A fresh card whose URL is in the clipboard **and** the clipboard
# is in Cut mode renders with this variant; Copy mode uses the empty
# variant (no fade) because the source is not being removed.
_CUT_VARIANT = "cut"

# Step 33: GLFW keycode for Escape — cancels a live rename on the
# card's name field. Mirrors the :mod:`file_browser_delegate` value so
# the two rename surfaces share one keycode convention.
_KEY_ESCAPE = 256

# Icon padding inside the image area. Leaves a few pixels of card
# background around the glyph so the icon does not bleed into the
# Card edge on hover / selected tints.
_ICON_PADDING = 4


# Cached providers keyed by absolute path. Mirrors the pattern in
# :mod:`ovwidgets.content.widget.browser_bar` and
# :mod:`ovwidgets.content.widget.file_browser_delegate`: the ovui
# build here drops draws on :class:`ui.Button`'s internal image loader
# and :class:`ui.Image`'s stb_image retry path; a cached
# :class:`ui.RasterImageProvider` pointed at an absolute filesystem
# path is the reliable route for local PNGs. Custom thumbnails still
# go through :class:`ui.Image` — that is the only way to resolve
# ``omniverse://`` URLs in this build (architecture §9.10).
_PROVIDER_CACHE: Dict[str, "ui.RasterImageProvider"] = {}


def _provider(path: str) -> "ui.RasterImageProvider":
    """Return a cached :class:`ui.RasterImageProvider` for ``path``."""
    prov = _PROVIDER_CACHE.get(path)
    if prov is None:
        prov = ui.RasterImageProvider(path)
        _PROVIDER_CACHE[path] = prov
    return prov


def _file_url_to_path(url: str) -> Optional[str]:
    """Return the absolute filesystem path for a ``file://`` URL, else ``None``.

    Bug 10: :class:`ui.Image` silently drops local-file decodes in this
    ovui build; the reliable local-PNG route is
    :class:`ui.ImageWithProvider` + :class:`ui.RasterImageProvider`
    pointed at an absolute path. Callers that receive a URL from
    :class:`FileBrowserModel` need to detect the ``file://`` case and
    feed the raw path to the provider. Remote URLs
    (``omniverse://``, ``http://``, ``s3://`` …) fall through to
    :attr:`ui.Image.source_url` as before.

    Accepts uppercase / non-canonical variants (``FILE://``) and the
    three-slash root form (``file:///Users/x``). Returns ``None`` for
    anything that is not a local-file URL so the caller can fan out to
    the remote-URL branch.

    On Windows the three-slash root form yields ``/C:/Users/...`` after
    stripping the scheme — the leading slash is correct on POSIX but
    wrong on Windows, where the RasterImageProvider treats the slash as
    a UNC share prefix and fails to open the file. Strip the leading
    slash on Windows only when the following characters form a drive-
    letter prefix (``/X:``) so a genuine POSIX-style path does not get
    mangled.
    """
    if not url:
        return None
    lowered = url.lower()
    if not lowered.startswith("file://"):
        return None
    path = url[len("file://"):]
    if (
        sys.platform == "win32"
        and len(path) >= 3
        and path[0] == "/"
        and path[2] == ":"
    ):
        path = path[1:]
    return path


def _build_front_image(
    fs_path: Optional[str],
    remote_url: Optional[str],
    size: int,
    cut_variant: str,
) -> Any:
    """Build the front-buffer image widget inside the current build context.

    ``fs_path`` and ``remote_url`` are mutually exclusive — exactly one
    is non-``None``. ``fs_path`` routes through
    :class:`ui.ImageWithProvider` (the only reliable local-PNG decode
    path in this ovui build); ``remote_url`` keeps the legacy
    :class:`ui.Image` + :attr:`source_url` path for future
    ``omniverse://`` / ``http://`` consumers.

    Must be called inside a live ``with`` block (the front buffer's
    :class:`ui.Frame`). Returns the constructed widget so the card can
    wire progress callbacks against it.
    """
    image_side = size - _ICON_PADDING * 2
    with ui.VStack():
        ui.Spacer(height=_ICON_PADDING)
        with ui.HStack(height=image_side):
            ui.Spacer(width=_ICON_PADDING)
            if fs_path is not None:
                image = ui.ImageWithProvider(
                    _provider(fs_path),
                    width=image_side,
                    height=image_side,
                    style_type_name_override="Content.Card.Image",
                    name=cut_variant,
                )
            else:
                image = ui.Image(
                    width=image_side,
                    height=image_side,
                    style_type_name_override="Content.Card.Image",
                    name=cut_variant,
                )
                if remote_url:
                    image.source_url = remote_url
            ui.Spacer(width=_ICON_PADDING)
        ui.Spacer(height=_ICON_PADDING)
    return image


class FileCard:
    """Single thumbnail-plus-label card rendering one :class:`FileItem`.

    Construction builds the widget immediately into the surrounding
    ``with`` build block — same contract as :class:`PathField` /
    :class:`BrowserBar` / :class:`FileBrowserWidget`. After
    construction the caller may call :meth:`set_selected` /
    :meth:`set_thumbnail` at any time.

    Handlers:

    * ``on_click(button, modifier)`` — fired for every mouse-press
      inside the card. The card does not interpret the button or
      modifier; dispatch logic (Shift-click range, Ctrl-click toggle,
      right-click context) belongs to :class:`FileGridView` in Step 22.
    * ``on_right_click(x_screen, y_screen)`` — fired in addition to
      ``on_click`` when the mouse-press is a right-button event
      (Step 31 — the content browser behavior). The screen coords
      are resolved via :attr:`ui.Rectangle.screen_position_x` plus the
      event's widget-local ``(x, y)`` so the caller can pop a
      :class:`ui.Menu` at the click point without further conversion.
      Optional — absent right-click handler makes the button-1 press
      a plain ``on_click`` forward with no side effect.
    * ``on_double_click()`` — fired on a double-click (left button
      only). A folder card should open the folder; a leaf card should
      open the asset in Step 54's handler. No arguments because the
      grid delegate already knows the card's item via the dispatch
      map.
    """

    def __init__(
        self,
        item: FileItem,
        on_click: Callable[[int, int], None],
        on_double_click: Callable[[], None],
        size: int = 96,
        search_term: str = "",
        on_right_click: Optional[Callable[[float, float], None]] = None,
        rename_controller: Optional["RenameController"] = None,
        on_drag: Optional[Callable[[], str]] = None,
        on_drop: Optional[Callable[[FileItem, str], None]] = None,
        drop_indicator: Optional["DropIndicator"] = None,
    ) -> None:
        self._item = item
        self._on_click = on_click
        self._on_double_click = on_double_click
        self._on_right_click = on_right_click
        self._size = size
        # Step 41 — drop-hover visual feedback coordinator. Supplied by
        # the hosting :class:`FileGridView` / :class:`FileBrowserWidget`;
        # ``None`` means "no indicator wired" and every drop-over call
        # below is a silent no-op. The indicator is owned by the widget
        # (one instance coordinates tints / lines across every card in
        # the grid) — the card only holds a reference.
        self._drop_indicator: Optional["DropIndicator"] = drop_indicator
        # Step 38 — optional drag / drop handlers supplied by the
        # hosting :class:`FileGridView`. ``on_drag`` returns the MIME
        # payload for a drag start (``"\n"``-joined URLs per
        # the content browser behavior); ``on_drop`` receives this
        # card's :class:`FileItem` + the dropped MIME string when ovui
        # fires a drop on the card's hit rect. Both are ``None`` for
        # callers (tests, legacy grid flows) that have not opted into
        # the drag-drop surface — the card's hit rect simply omits
        # ``set_drag_fn`` / ``set_drop_fn`` in that case.
        self._on_drag: Optional[Callable[[], str]] = on_drag
        self._on_drop: Optional[Callable[[FileItem, str], None]] = on_drop
        # Step 29: when the host grid is rendering under an active
        # search filter, the card's label paints a :class:`HighlightLabel`
        # instead of a plain :class:`ui.Label` so matching substrings
        # glow yellow. Empty string = no search active → plain label
        # (the common case, which keeps the label build cheap).
        self._search_term: str = search_term
        # Step 33: the host grid passes its :class:`RenameController` in
        # so the card's build path can swap the label for an inline
        # :class:`ui.StringField` when this item is the controller's
        # active rename target. ``None`` keeps the label path live for
        # every caller that has not yet opted into the rename surface.
        self._rename_controller: Optional["RenameController"] = (
            rename_controller
        )

        # Widget refs — populated by :meth:`build`, cleared by
        # :meth:`destroy`. ``None`` pre-build / post-destroy so
        # straggling callbacks from a teardown race hit the guards
        # cleanly.
        self._root: Optional[ui.ZStack] = None
        self._rect: Optional[ui.Rectangle] = None
        self._back_buffer: Optional[ui.Frame] = None
        self._front_buffer: Optional[ui.Frame] = None
        self._front_image: Optional[ui.Image] = None
        # Bugs 5 + 6: ``_label_frame`` pins the bottom-row label band to
        # the card's width with horizontal clipping so an overlong
        # filename can neither paint past the card edge nor drag the
        # selection :class:`ui.Rectangle` into a neighbouring cell.
        # Populated for every non-rename build (plain label and search-
        # highlight variant alike); ``None`` pre-build / post-destroy /
        # during rename so callers that inspect it get a single,
        # predictable ref to the clip container.
        self._label_frame: Optional[ui.Frame] = None
        self._label: Optional[ui.Label] = None
        # Step 29: populated when ``search_term`` is non-empty. Holds
        # the :class:`HighlightLabel` so :meth:`destroy` can drop its
        # internal refs explicitly (the plain-label path leaves this
        # attribute ``None``).
        self._highlight_label: Optional[HighlightLabel] = None
        # Step 33: the live rename :class:`ui.StringField` when this
        # card is being renamed; ``None`` otherwise. Held so
        # :meth:`destroy` can drop its key-press callback explicitly
        # before the parent :class:`ui.VStack` is released.
        self._rename_field: Optional[ui.StringField] = None

        self.build()

        # Step 25: honour any custom thumbnail the model has already
        # discovered on the item. The card's build finishes first so
        # ``_front_buffer`` / ``_front_image`` are non-``None`` before
        # :meth:`set_thumbnail` runs. A later model populate pass that
        # discovers a thumbnail for this item triggers a grid rebuild
        # (:meth:`FileBrowserModel._schedule_item_changed`) — the fresh
        # card built by that rebuild replays this block with the now-
        # populated URL. See the content browser behavior /
        # §10.2 and the content browser implementation step 25.
        custom = item.custom_thumbnail
        if custom:
            self.set_thumbnail(custom)

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build the card widget into the surrounding build context.

        Layout (architecture §9.10):

        ::

            ZStack (size × size+label)
            ├── Rectangle (Content.Card; hit target)
            └── VStack
                ├── ZStack (image area — size × size)
                │   ├── Frame (back buffer; default icon)
                │   │   └── ImageWithProvider (url.<icon_key>)
                │   └── Frame (front buffer; custom thumbnail; hidden
                │       until :meth:`set_thumbnail` sets a URL)
                │       └── Image
                └── Label (Content.Card.Label; tooltip = full name)
        """
        self._root = ui.ZStack(
            width=self._size,
            height=self._size + _LABEL_HEIGHT,
        )
        with self._root:
            # Rectangle spans the whole ZStack and carries the Card
            # style. It also owns the click handlers — putting them on
            # the back-most layer means clicks anywhere on the card
            # fire regardless of which foreground element the pointer
            # happens to land on.
            self._rect = ui.Rectangle(
                style_type_name_override="Content.Card",
            )
            self._rect.set_mouse_pressed_fn(self._dispatch_mouse_pressed)
            self._rect.set_mouse_double_clicked_fn(
                self._dispatch_mouse_double_clicked,
            )
            # Step 38 — drag + drop surface. Only wire the callbacks
            # when the host actually provided handlers — a card built
            # without drag-drop support (the pre-Step-38 construction
            # paths, plus tests that instantiate a card in isolation)
            # keeps the rect free of these slots so ovui does not paint
            # a drag cursor on mouse-down.
            if self._on_drag is not None:
                self._rect.set_drag_fn(self._dispatch_drag)
            if self._on_drop is not None:
                self._rect.set_accept_drop_fn(self._accept_drop)
                self._rect.set_drop_fn(self._dispatch_drop)

            with ui.VStack():
                self._build_image_area()
                self._build_label()

    def _build_image_area(self) -> None:
        """Build the back-buffer / front-buffer image stack.

        The back buffer is an :class:`ui.ImageWithProvider` rendering
        the default asset-category icon (``url.<item.icon_key>``) via
        the module-level provider cache. The front buffer is an
        :class:`ui.Image` that starts ``visible=False``; calling
        :meth:`set_thumbnail` with a non-``None`` URL points it at the
        custom thumbnail and flips ``visible`` on. When the front
        buffer is visible it paints on top of the back buffer without
        hiding it — matching the architecture's "back remains fallback
        until front loads" contract (§9.10). For Step 21 we do not
        subscribe to :meth:`ui.Image.set_progress_changed_fn`; the
        Step 25 / Step 27 thumbnail pipeline will wire that in.

        Step 36 reads :func:`clipboard.is_path_cut` once per build and
        applies the ``cut`` variant name to both image widgets when the
        card's URL is in a Cut selection. The style selector
        ``Content.Card.Image::cut`` (see :mod:`ovwidgets.content.style`)
        dims the image to ``text_disabled`` so the card reads as
        "pending move".
        """
        image_side = self._size - _ICON_PADDING * 2
        cut_variant = _CUT_VARIANT if clipboard.is_path_cut(
            self._item.url,
        ) else ""

        with ui.ZStack(width=self._size, height=self._size):
            # Back buffer: default asset icon. Wrapped in a Frame so
            # the :meth:`set_thumbnail` path does not need to know the
            # buffer's exact layout to swap it; the Frame also soaks
            # up the padding so the raw ImageWithProvider stays square.
            self._back_buffer = ui.Frame()
            with self._back_buffer:
                with ui.VStack():
                    ui.Spacer(height=_ICON_PADDING)
                    with ui.HStack(height=image_side):
                        ui.Spacer(width=_ICON_PADDING)
                        ui.ImageWithProvider(
                            _provider(get_icon_path(self._item.icon_key)),
                            width=image_side,
                            height=image_side,
                            style_type_name_override="Content.Card.Image",
                            name=cut_variant,
                        )
                        ui.Spacer(width=_ICON_PADDING)
                    ui.Spacer(height=_ICON_PADDING)

            # Front buffer: custom thumbnail. Starts empty — the
            # widget inside depends on the URL scheme (provider-backed
            # :class:`ui.ImageWithProvider` for local files,
            # :class:`ui.Image` for remote URLs — Bug 10). Populated by
            # :meth:`set_thumbnail` when the model reports a discovered
            # thumbnail; pre-populated items get their first
            # :meth:`set_thumbnail` call right after :meth:`build`
            # returns (see the ``custom = item.custom_thumbnail`` block
            # in ``__init__``).
            self._front_buffer = ui.Frame(visible=False)

    def _build_label(self) -> None:
        """Build the card's bottom label — plain or match-highlighted.

        Step 29: when a search filter is active on the hosting grid,
        the card passes that filter to its constructor as
        ``search_term``; this method swaps the plain :class:`ui.Label`
        out for a :class:`HighlightLabel` so matching substrings paint
        warm yellow. Both variants fix the same 20-px label band
        (``_LABEL_HEIGHT``) so the :class:`FileGridView` row height
        computation stays symmetric regardless of which label the
        cards rendered. The full name lands in the tooltip either way
        so hovering still reveals clipped names.

        Step 33: when the :class:`RenameController` flags this item as
        the active rename target, the label band hosts an inline
        :class:`ui.StringField` instead — Enter / end-edit commits,
        Escape cancels. The search-term branch below is skipped so a
        rename during a search filter does not stack a HighlightLabel
        under the field.
        """
        if (
            self._rename_controller is not None
            and self._rename_controller.is_renaming(self._item)
        ):
            self._build_rename_field()
            return
        cut_variant = _CUT_VARIANT if clipboard.is_path_cut(
            self._item.url,
        ) else ""
        # Bugs 5 + 6 — pin the label band to the card's width with
        # horizontal clipping so overlong filenames can neither paint
        # past the card edge nor drag the :class:`ui.Rectangle`
        # selection highlight into the neighbouring grid cell. The
        # frame's height matches :data:`_LABEL_HEIGHT` so the card's
        # total footprint (``size × size+_LABEL_HEIGHT``) stays
        # consistent with the grid's row-height computation.
        self._label_frame = ui.Frame(
            width=self._size,
            height=_LABEL_HEIGHT,
            horizontal_clipping=True,
        )
        with self._label_frame:
            if self._search_term:
                self._highlight_label = HighlightLabel(
                    text=self._item.name,
                    search_term=self._search_term,
                    height=_LABEL_HEIGHT,
                    alignment=ui.Alignment.CENTER,
                )
                return
            # ``elided_text=True`` swaps the hard mid-glyph clip for the
            # familiar ``…`` ellipsis when the name exceeds the frame.
            # The outer frame still clips on top of the elision so a
            # metric mismatch between the ovui text measurer and the
            # clip rect can never leak pixels into the next cell.
            self._label = ui.Label(
                self._item.name,
                word_wrap=False,
                alignment=ui.Alignment.CENTER,
                height=_LABEL_HEIGHT,
                elided_text=True,
                style_type_name_override="Content.Card.Label",
                name=cut_variant,
            )
            # Tooltip always carries the full name so the user can
            # still read names the frame is clipping. Setting the
            # attribute is idempotent — the tooltip repaints lazily on
            # hover.
            self._label.tooltip = self._item.name

    def _build_rename_field(self) -> None:
        """Render the card's label band as an inline :class:`ui.StringField`.

        Step 33 / the content browser behavior Seeded with
        ``item.name``; Enter / end-edit fires
        :meth:`RenameController.commit_rename` with the trimmed field
        value, Escape fires :meth:`RenameController.cancel_rename`. The
        field is pinned to the same 20-px label band so the card's
        overall footprint stays constant between display and edit
        modes — the grid's row-height calculation does not need to
        know about rename state.
        """
        ctrl = self._rename_controller
        if ctrl is None:
            # Defensive: :meth:`_build_label` already guarded on this;
            # a direct caller that missed the guard still gets a label.
            self._label = ui.Label(
                self._item.name,
                word_wrap=False,
                alignment=ui.Alignment.CENTER,
                height=_LABEL_HEIGHT,
                style_type_name_override="Content.Card.Label",
            )
            return
        self._rename_field = ui.StringField(
            height=_LABEL_HEIGHT,
            style_type_name_override="Content.RenameField",
        )
        self._rename_field.model.set_value(self._item.name)
        self._rename_field.model.add_end_edit_fn(
            lambda m, c=ctrl: c.commit_rename(m.get_value_as_string()),
        )
        self._rename_field.set_key_pressed_fn(
            lambda key, mod, pressed, c=ctrl:
            c.cancel_rename() if (pressed and key == _KEY_ESCAPE)
            else None,
        )

    # ── Event dispatch ───────────────────────────────────────────────────────

    def _dispatch_mouse_pressed(
        self, x: Any, y: Any, button: Any, modifier: Any,
    ) -> None:
        """Forward ``(button, modifier)`` to the caller's ``on_click``.

        Drops ``x`` / ``y`` for the plain click path — the grid
        delegate only needs to know which card fired (identity via
        the card instance) and the button / modifier so it can
        dispatch Shift-click range, Ctrl-click toggle, etc.

        Step 31: right-button presses (``button == 1``) also fire
        :attr:`_on_right_click` with the event coordinates so the
        caller can pop a :class:`ui.Menu` at the click point. The
        ovui mouse-pressed callback already delivers ``(x, y)`` in
        DPI-scaled points — the same coordinate system
        :meth:`ui.Menu.show_at` expects (ovui ``Widget.cpp`` divides
        by ``dpiScale`` before dispatch; ``Menu.cpp`` multiplies by
        ``dpiScale`` on show). Adding the hit rect's
        :attr:`screen_position_x` on top double-offsets the menu —
        Bug 4. Forward the event coords verbatim instead. The plain
        ``on_click`` forward still fires alongside so the Step 22
        selection policy (no-op on right-click) stays intact.

        Kept permissive: ``None`` handlers become silent no-ops, so
        tests can instantiate a card without a real handler.
        """
        if self._on_click is not None:
            self._on_click(int(button), int(modifier))
        if int(button) == 1 and self._on_right_click is not None:
            self._on_right_click(float(x), float(y))

    def _dispatch_mouse_double_clicked(
        self, x: Any, y: Any, button: Any, modifier: Any,
    ) -> None:
        """Forward a left-button double-click to ``on_double_click``.

        Right / middle double-clicks are ignored — they do not map to
        a meaningful open action on a content card.
        """
        if int(button) != 0:
            return
        if self._on_double_click is None:
            return
        self._on_double_click()

    def _dispatch_drag(self) -> str:
        """Return the MIME payload for a drag started on this card.

        Step 38. Defers to ``on_drag`` (supplied by the host
        :class:`FileGridView`) which typically builds the
        ``"\\n"``-joined URL payload from the grid's current selection.
        A ``None`` handler or a post-destroy race returns ``""`` which
        ovui reads as "no drag" and suppresses the drag visualization.
        """
        if self._on_drag is None:
            return ""
        try:
            return self._on_drag() or ""
        except Exception:  # noqa: BLE001
            # A crashing drag-payload provider must not leave the
            # card's hit rect in a half-drag state. Return empty so
            # ovui treats the mouse-move as a plain gesture.
            return ""

    def _accept_drop(self, mime: str) -> bool:
        """Return True when this card can accept ``mime`` (folder + non-empty URL).

        Step 38. Matches the FileCard drop rule:
        ``accept_drop_fn(url) → is_folder AND valid_url``. Here we read
        ``mime`` (the dragged payload, not a single URL — it may be
        ``"\\n"``-joined) and accept when the card's item is a folder
        and at least one segment of the payload is non-empty.
        Finer validation (self-drop, ancestor-of-target) runs in
        :meth:`FileBrowserModel.drop`.

        A file-target card always returns ``False`` so the "drop not
        accepted" cursor paints while hovering over a file tile —
        matches the visual affordance the user expects on a target
        that cannot meaningfully accept children.

        Step 41 — when the indicator is wired and the card is a valid
        target, flips the card's hit-rect variant to
        ``Content.Card::drop_hover`` via the shared
        :class:`DropIndicator`. ovui calls ``accept_drop_fn`` on every
        cursor-move frame during a drag so the highlight follows the
        cursor — entering a different card reverts the previous card
        because the indicator permits at most one active card at a
        time.
        """
        if not self._item.is_folder:
            return False
        if not mime:
            return False
        accepts = any(u for u in mime.split("\n"))
        if accepts and self._drop_indicator is not None:
            self._drop_indicator.show_card_highlight(self)
        return accepts

    def _dispatch_drop(self, event: Any) -> None:
        """Forward a drop event to ``on_drop`` with this card's item.

        Step 38. ``event`` is an :class:`omni.ui.WidgetMouseDropEvent`
        carrying the MIME string as ``event.mime_data``. We pass the
        card's own :class:`FileItem` so the host can route into
        :meth:`FileBrowserModel.drop` with the card as the drop target.
        Mid-teardown races fall through silently via the ``None`` guard.

        Step 41 — a drop always clears the indicator regardless of the
        ``on_drop`` outcome: the drag has ended, so any lingering
        highlight would read as a stuck hover to the user. Runs
        before the handler so a crashing handler still releases the
        visual feedback.
        """
        if self._drop_indicator is not None:
            self._drop_indicator.clear()
        if self._on_drop is None:
            return
        mime = getattr(event, "mime_data", "") or ""
        try:
            self._on_drop(self._item, mime)
        except Exception:  # noqa: BLE001
            # A crashing drop handler is a widget-level bug; the card
            # swallows the exception so ovui's event dispatch does not
            # tear down the entire drop pipeline. The real bug surfaces
            # via :class:`ErrorReporter` at the widget layer anyway.
            pass

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def item(self) -> FileItem:
        return self._item

    @property
    def size(self) -> int:
        return self._size

    def set_selected(self, selected: bool) -> None:
        """Toggle the ``Content.Card:selected`` state on the hit rect.

        The grid view owns selection state; it calls this method on
        each card when the selection set changes. A ``None`` rect
        (post-destroy) short-circuits silently so teardown-race
        callbacks don't raise.
        """
        if self._rect is None:
            return
        self._rect.selected = bool(selected)

    def set_thumbnail(self, url: Optional[str]) -> None:
        """Override the default icon with a custom thumbnail URL.

        ``url`` may be:

        * ``None`` / empty — hide the front buffer so the default icon
          (back buffer) paints. Clears any previous custom source and
          restores the back buffer's visibility in case a prior
          progress-complete callback had hidden it.
        * A ``file://`` URL — swap the front buffer to a
          :class:`ui.ImageWithProvider` backed by a cached
          :class:`ui.RasterImageProvider`. This ovui build's
          :class:`ui.Image` / stb_image retry path silently drops
          local-file decodes (same quirk the back buffer avoids by
          using :class:`ui.ImageWithProvider`), so routing local
          thumbnails through the provider is the only way the
          ``.thumbs/256x256/<name>.png`` previews actually appear
          on screen. Back buffer stays visible underneath as a
          fallback so a decode failure still paints the default icon.
        * Any other scheme (``omniverse://``, ``http://``, ``s3://``,
          …) — keep the legacy :class:`ui.Image` path via
          :attr:`ui.Image.source_url`. ovui resolves remote URLs only
          through :class:`ui.Image`, so the provider branch is reserved
          for the local-FS case the LocalFS backend produces today.

        Post-destroy calls short-circuit via the ``None`` guards.
        """
        if self._front_buffer is None:
            return
        if not url:
            self._front_buffer.visible = False
            if self._front_image is not None:
                # ``source_url`` / ``set_progress_changed_fn`` only
                # exist on :class:`ui.Image`; the provider-backed
                # :class:`ui.ImageWithProvider` variant has neither
                # (Bug 10 split). Swallow the AttributeError per
                # branch rather than isinstance-branching so the
                # clear path stays symmetric with :meth:`destroy`.
                try:
                    self._front_image.source_url = ""
                except AttributeError:
                    pass
                try:
                    self._front_image.set_progress_changed_fn(None)
                except AttributeError:
                    pass
            if self._back_buffer is not None:
                self._back_buffer.visible = True
            return

        # Bug 10: local ``file://`` URLs never render through
        # ``ui.Image`` in this ovui build — the back buffer already
        # uses :class:`ui.ImageWithProvider` for the same reason.
        # Rebuild the front buffer with a provider-backed image for
        # local files; keep ``ui.Image`` for anything else (the only
        # known consumer is a future Omniverse / HTTP backend).
        fs_path = _file_url_to_path(url)
        self._front_buffer.clear()
        with self._front_buffer:
            self._front_image = _build_front_image(
                fs_path=fs_path,
                remote_url=None if fs_path is not None else url,
                size=self._size,
                cut_variant=_CUT_VARIANT if clipboard.is_path_cut(
                    self._item.url,
                ) else "",
            )
        self._front_buffer.visible = True
        # Back buffer stays visible underneath — the
        # ``_on_front_image_progress`` callback hides it once the front
        # image finishes loading so the default icon is not repainted
        # over by a transparent-edged custom thumbnail. Provider-backed
        # images never fire ``progress``; we hide the back buffer
        # eagerly because the RasterImageProvider has already decoded
        # the PNG by the time it is attached to the widget.
        if self._back_buffer is not None:
            if fs_path is not None:
                self._back_buffer.visible = False
            else:
                self._back_buffer.visible = True
        if fs_path is None and self._front_image is not None:
            self._front_image.set_progress_changed_fn(
                self._on_front_image_progress,
            )

    def _on_front_image_progress(self, progress: float) -> None:
        """Hide the back buffer once the front image finishes loading.

        ``progress`` is reported by :class:`ui.Image` as a float in
        ``[0.0, 1.0]``; a value ``>= 1.0`` marks the load complete. A
        failed load never reaches ``1.0`` and the back buffer stays
        visible — the default icon is the fallback by construction
        (architecture §9.10: "no retry, back buffer is the fallback").

        Post-destroy calls are absorbed via the ``None`` guard on
        :attr:`_back_buffer`.
        """
        if self._back_buffer is None:
            return
        if float(progress) >= 1.0:
            self._back_buffer.visible = False

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Release widget refs and drop handler references.

        Idempotent — the ``is not None`` guard on each ref short-
        circuits a second call. Mouse callbacks are cleared off the
        hit rect explicitly so a stale ``ui.Rectangle`` reference held
        by the event system cannot dispatch back into a torn-down
        :class:`FileCard`.
        """
        if self._rect is not None:
            self._rect.set_mouse_pressed_fn(None)
            self._rect.set_mouse_double_clicked_fn(None)
            self._rect = None
        if self._front_image is not None:
            # :class:`ui.ImageWithProvider` (Bug 10 local-file path)
            # does not expose ``set_progress_changed_fn`` — only
            # :class:`ui.Image` (remote URL branch) does. Swallow the
            # AttributeError rather than branching on :func:`isinstance`
            # because ovui's Python bindings don't export the
            # widget-type hierarchy stably across versions.
            try:
                self._front_image.set_progress_changed_fn(None)
            except AttributeError:
                pass
        # Step 29: tear down the HighlightLabel's internal ref stack
        # before nulling its Python ref so a stale teardown-race
        # callback finds empty state rather than a half-live widget.
        if self._highlight_label is not None:
            self._highlight_label.destroy()
            self._highlight_label = None
        # Step 33: drop the rename field's key-press callback before
        # nulling the reference so a late teardown-race Escape does
        # not dispatch into a half-destroyed controller.
        if self._rename_field is not None:
            try:
                self._rename_field.set_key_pressed_fn(None)
            except Exception:  # noqa: BLE001
                pass
            self._rename_field = None
        self._back_buffer = None
        self._front_buffer = None
        self._front_image = None
        self._label = None
        self._label_frame = None
        self._root = None
        # Drop handler refs last so a pending callback sneaking through
        # the widget-ref guards above falls through silently rather
        # than hitting a stale closure.
        self._on_click = None  # type: ignore[assignment]
        self._on_double_click = None  # type: ignore[assignment]
        self._on_right_click = None
        self._rename_controller = None
        # Step 38 — drag / drop handlers also dropped so a late ovui
        # dispatch after :meth:`destroy` cannot re-enter a torn-down
        # widget. ``None`` guards on both ``_on_drag`` and ``_on_drop``
        # keep the dispatchers silent.
        self._on_drag = None
        self._on_drop = None
        # Step 41 — drop the indicator ref. The indicator itself is
        # owned by the :class:`FileBrowserWidget` and outlives the card
        # (the widget tears down in a controlled order after all cards
        # are destroyed); nulling the card's handle here is enough to
        # keep a late ovui callback from mutating an already-reverted
        # controller state.
        self._drop_indicator = None


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovwidgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_PROVIDER_CACHE)
