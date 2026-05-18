# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""ZoomBar — thumbnail size slider + grid/list view toggle.

Step 23 (the content browser implementation step D, the content browser behavior).

The bar sits below the grid / list view and wires two user controls:

* A six-step :class:`ui.IntSlider` (values 0-5) mapped through
  :data:`SCALE_MAP` to six discrete card-scale multipliers.
* A single-icon toggle button flipping between grid and list view.

Semantics match §25.4's Kit reference with one ovgear-specific
refinement: the *scale* itself implicitly drives view mode — any
scale ``< 0.75`` (slider index 0, scale 0.5) means the grid view is
not useful at that density, so the bar flips to list view
automatically; ``>= 0.75`` (slider index 1+, scale 0.75+) stays in
grid mode. The toggle button still offers an explicit switch —
clicking it on grid snaps the slider to 0 (→ list); clicking on
list restores the slider to the last-known grid index.

The widget owns only the controls and the scale <-> mode
reconciliation. Settings persistence (``/persistent/ui.content.*``)
wires in Step 57; the view-swap itself wires in Step 24.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import omni.ui as ui

from ovwidgets.common.style.urls import get_icon_path

# Six-step zoom scale map. Slider value → thumbnail-size multiplier.
# Index 0 = 0.5 is below the 0.75 grid threshold so slider=0
# implicitly means "show list view". Index 2 = 1.0 is the default,
# preserving the stored card size from Step 21 / 22.
# the content browser behavior uses a slightly different scale
# ladder (0.25-2.0); ovgear's ladder starts at 0.5 because the grid
# card's minimum readable thumbnail size drops off sharply below that.
SCALE_MAP: Dict[int, float] = {
    0: 0.5,
    1: 0.75,
    2: 1.0,
    3: 1.25,
    4: 1.5,
    5: 2.0,
}

# Slider index → scale threshold at which grid view becomes useful.
# Scale values at or above this threshold paint grid; below it, the
# bar flips to list. Expressed as a scale (not an index) so a later
# change to :data:`SCALE_MAP` only needs to keep the sub-0.75 range
# for list mode.
_GRID_SCALE_THRESHOLD = 0.75

# Default slider index at build time. Corresponds to scale 1.0 — the
# canonical card scale Step 21 defined.
_DEFAULT_SLIDER_INDEX = 2

# Slider index snapped to on a grid → list toggle. Index 0
# (scale 0.5) is the only sub-threshold position, so this is forced.
_LIST_SLIDER_INDEX = 0

# Button + icon sizing. ``_BUTTON_SIZE`` = 24 keeps the zoom bar's
# row tight; ``_BUTTON_ICON_SIZE`` = 12 leaves ~5 px padding around
# the glyph. Slightly smaller than :class:`BrowserBar`'s 28/16 pair
# because the zoom bar lives at the bottom of the detail pane where
# vertical space is scarcer than the top toolbar row.
_BUTTON_SIZE = 22
_BUTTON_ICON_SIZE = 12

# Horizontal gap between the toggle button, slider, and percent
# label. A 3-px gutter keeps the bottom control compact.
_SPACING = 3

# Width reserved for the percent label. The widest value in
# :data:`SCALE_MAP` renders as ``"200%"`` — four chars fit
# comfortably in 40 px at ``fl.font_size_small``.
_PERCENT_LABEL_WIDTH = 36

# Row height. 22 px keeps the zoom bar from inflating the bottom of the
# browser pane.
_BAR_HEIGHT = 22

# Slider draw height. Kept smaller than :data:`_BAR_HEIGHT` so the
# Spacer-sandwich in :meth:`ZoomBar._build_slider` can vertically
# center the track + handle inside the 22-px row — ovui's
# :class:`ui.IntSlider` anchors its drawn track to the top of the
# allocated height, so without a smaller explicit height plus the
# sandwich the slider's midpoint sits above the row's center,
# visually mis-aligned with the flanking toggle icon (Spacer-sandwich
# centered inside a 22-px ZStack) and percent label (RIGHT_CENTER
# text alignment centers vertically).
_SLIDER_HEIGHT = 10


# Cached providers keyed by absolute path. Same decouple-by-duplicate
# pattern as :mod:`browser_bar` / :mod:`file_browser_delegate` /
# :mod:`file_card` — the ovui build here drops draws on
# :class:`ui.Button`'s internal image loader, so a cached
# :class:`ui.RasterImageProvider` pointed at an absolute filesystem
# path is the reliable route for local PNGs. Two toggle icons means
# at most two providers resident per process.
_PROVIDER_CACHE: Dict[str, "ui.RasterImageProvider"] = {}


def _provider(path: str) -> "ui.RasterImageProvider":
    """Return a cached :class:`ui.RasterImageProvider` for ``path``."""
    prov = _PROVIDER_CACHE.get(path)
    if prov is None:
        prov = ui.RasterImageProvider(path)
        _PROVIDER_CACHE[path] = prov
    return prov


class ZoomBar:
    """Thumbnail-size slider + grid/list view toggle button.

    Construction builds the widget immediately into the surrounding
    ``with`` build block — same contract as :class:`PathField`,
    :class:`BrowserBar`, :class:`FileCard`. After construction the
    caller only interacts via the two handler callbacks it passed in.

    Handlers:

    * ``on_scale(scale: float)`` — fired on every slider value
      change. The caller should forward ``scale`` to the grid view's
      :meth:`FileGridView.set_scale`. This callback fires for every
      slider movement, even when the move does not cross the
      grid/list threshold.
    * ``on_toggle_grid(is_grid: bool)`` — fired whenever the current
      view mode flips, either from an explicit toggle-button click
      or from a slider move that crosses the 0.75 threshold. The
      caller should forward ``is_grid`` to a view-visibility swap.

    The bar owns no :class:`FileBrowserWidget` reference; Step 24
    wires the handlers to the widget's view-swap logic.
    """

    def __init__(
        self,
        on_scale: Callable[[float], None],
        on_toggle_grid: Callable[[bool], None],
    ) -> None:
        self._on_scale: Optional[Callable[[float], None]] = on_scale
        self._on_toggle_grid: Optional[Callable[[bool], None]] = (
            on_toggle_grid
        )

        # Current view mode. Starts True — default slider index 2
        # (scale 1.0) falls above the 0.75 threshold, so grid view is
        # the natural initial state.
        self._is_grid: bool = True

        # Last slider index while in grid mode. Used to restore the
        # slider position on a list → grid toggle (§25.4 round-trip
        # preservation). Initialised to the default so the very first
        # list → grid toggle lands on scale 1.0 rather than snapping
        # to 0 (a list-side position).
        self._last_grid_slider_index: int = _DEFAULT_SLIDER_INDEX

        # Widget refs — populated by :meth:`build`, cleared by
        # :meth:`destroy`. ``None`` pre-build / post-destroy so
        # callbacks guard defensively against teardown races.
        self._hstack: Optional[ui.HStack] = None
        self._toggle_button: Optional[ui.Button] = None
        self._grid_icon_image: Optional[ui.ImageWithProvider] = None
        self._list_icon_image: Optional[ui.ImageWithProvider] = None
        self._slider: Optional[ui.IntSlider] = None
        self._percent_label: Optional[ui.Label] = None

        # Slider value-changed subscription handle. Held so the C++
        # side's callback is released on :meth:`destroy` before any
        # other widget ref is nulled.
        self._slider_value_changed_sub: Any = None

        self.build()

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build the toggle-button + slider + percent-label row.

        Layout (single :class:`ui.HStack`):

        ::

            HStack (Content.ZoomBar)
            ├── Toggle button (Content.ZoomBar.Button)
            │   ├── Grid-view icon (visible when _is_grid=False)
            │   └── List-view icon (visible when _is_grid=True)
            ├── IntSlider (Content.ZoomBar.Slider)
            └── Label "NNN%" (Content.ZoomBar.Label)
        """
        self._hstack = ui.HStack(
            spacing=_SPACING,
            height=_BAR_HEIGHT,
            style_type_name_override="Content.ZoomBar",
        )
        with self._hstack:
            self._build_toggle_button()
            self._build_slider()
            self._build_percent_label()

    def _build_toggle_button(self) -> None:
        """Build the view-mode toggle button with swappable icon.

        Two :class:`ui.ImageWithProvider` widgets sit inside a
        :class:`ui.ZStack` behind the button click area. Only one
        image is visible at a time — :meth:`_update_toggle_icon`
        flips ``visible`` on the pair. Using two pre-instantiated
        images (versus reassigning a single image's provider) keeps
        the icon-swap a pure visibility flip rather than a texture
        re-upload; the provider cache keeps the texture memory cost
        resident and bounded.
        """
        grid_icon_path = get_icon_path("content_grid_view")
        list_icon_path = get_icon_path("content_list_view")

        with ui.ZStack(width=_BUTTON_SIZE, height=_BUTTON_SIZE):
            self._toggle_button = ui.Button(
                "",
                clicked_fn=self._on_toggle_click,
                style_type_name_override="Content.ZoomBar.Button",
            )
            # Icon layer — non-interactive overlay, centred inside
            # the button rectangle via a Spacer sandwich (same
            # approach BrowserBar uses for the nav-button icons).
            with ui.VStack():
                ui.Spacer()
                with ui.HStack(height=_BUTTON_ICON_SIZE):
                    ui.Spacer()
                    # list_icon visible when is_grid=True (click to
                    # switch to list). grid_icon visible when
                    # is_grid=False (click to switch to grid).
                    # Mirrors Kit's §25.4 convention where the icon
                    # displays the *destination* mode, not the
                    # current one.
                    self._list_icon_image = ui.ImageWithProvider(
                        _provider(list_icon_path),
                        width=_BUTTON_ICON_SIZE,
                        height=_BUTTON_ICON_SIZE,
                        visible=self._is_grid,
                        style_type_name_override=(
                            "Content.ZoomBar.Button.Image"
                        ),
                    )
                    self._grid_icon_image = ui.ImageWithProvider(
                        _provider(grid_icon_path),
                        width=_BUTTON_ICON_SIZE,
                        height=_BUTTON_ICON_SIZE,
                        visible=not self._is_grid,
                        style_type_name_override=(
                            "Content.ZoomBar.Button.Image"
                        ),
                    )
                    ui.Spacer()
                ui.Spacer()

    def _build_slider(self) -> None:
        """Build the IntSlider and hook its value-changed subscription.

        The slider is wrapped in a :class:`ui.VStack` with a Spacer
        sandwich so the :data:`_SLIDER_HEIGHT`-tall track sits at the
        row's vertical midpoint — matching the toggle button's icon
        (Spacer-sandwich centered inside a 22-px ZStack) and the
        percent label (``RIGHT_CENTER`` text alignment centers text
        vertically in its 36-px-wide slot). Without the sandwich the
        slider anchors to the top of the 22-px HStack row, visually
        misaligned with the flanking icon and label.

        Subscribe AFTER ``set_value`` so the initial default does
        not round-trip through ``on_scale`` at build time. The
        caller hasn't plumbed the grid view yet during construction;
        firing ``on_scale`` before Step 24 wires the handler would
        wire-order-sensitive-ly double every scale at startup.
        """
        with ui.VStack():
            ui.Spacer()
            self._slider = ui.IntSlider(
                min=0,
                max=5,
                height=_SLIDER_HEIGHT,
                style_type_name_override="Content.ZoomBar.Slider",
            )
            ui.Spacer()
        self._slider.model.set_value(_DEFAULT_SLIDER_INDEX)
        self._slider_value_changed_sub = (
            self._slider.model.add_value_changed_fn(
                self._on_slider_value_changed,
            )
        )

    def _build_percent_label(self) -> None:
        """Build the percent-display label and set the initial text."""
        self._percent_label = ui.Label(
            self._format_percent(SCALE_MAP[_DEFAULT_SLIDER_INDEX]),
            width=_PERCENT_LABEL_WIDTH,
            alignment=ui.Alignment.RIGHT_CENTER,
            style_type_name_override="Content.ZoomBar.Label",
        )

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_slider_value_changed(self, model: Any) -> None:
        """Slider dispatch: update label, emit on_scale, maybe flip mode.

        Four ordered effects:

        1. Read and clamp the slider index. Out-of-range values are
           a defensive no-op — :data:`SCALE_MAP` only holds 0-5.
        2. Update the percent label text so the display always
           mirrors the slider's current position.
        3. Fire ``on_scale`` with the mapped float scale.
        4. Threshold check — if the new scale flips the grid/list
           mode, update the internal flag, swap the toggle icon, and
           fire ``on_toggle_grid``. Ordered AFTER ``on_scale`` so
           the caller's ``set_scale`` has already run by the time
           ``on_toggle_grid`` flips the visibility; the grid view
           is thus sized correctly the instant it becomes visible.
        """
        value = int(model.get_value_as_int())
        if value not in SCALE_MAP:
            return
        scale = SCALE_MAP[value]
        self._update_percent_label(scale)
        # Preserve last grid slider index for round-trip restore.
        if scale >= _GRID_SCALE_THRESHOLD:
            self._last_grid_slider_index = value
        if self._on_scale is not None:
            self._on_scale(scale)
        new_is_grid = scale >= _GRID_SCALE_THRESHOLD
        if new_is_grid != self._is_grid:
            self._is_grid = new_is_grid
            self._update_toggle_icon()
            if self._on_toggle_grid is not None:
                self._on_toggle_grid(new_is_grid)

    def _on_toggle_click(self) -> None:
        """Explicit toggle: flip mode, swap icon, move slider, fire.

        Order matters:

        1. Flip the internal ``_is_grid`` flag FIRST so the slider's
           value-changed handler sees the already-updated mode and
           does not re-fire ``on_toggle_grid``.
        2. Update the toggle icon + fire ``on_toggle_grid`` for the
           user-initiated mode change.
        3. Snap the slider to the new position. This fires the
           value-changed handler, which emits ``on_scale`` with the
           new scale. The handler's threshold check is a no-op
           because ``_is_grid`` already matches the new scale.
        """
        new_is_grid = not self._is_grid
        target_slider_index = (
            self._last_grid_slider_index
            if new_is_grid
            else _LIST_SLIDER_INDEX
        )
        self._is_grid = new_is_grid
        self._update_toggle_icon()
        if self._on_toggle_grid is not None:
            self._on_toggle_grid(new_is_grid)
        if self._slider is not None:
            self._slider.model.set_value(target_slider_index)

    # ── View updates ─────────────────────────────────────────────────────────

    def _update_toggle_icon(self) -> None:
        """Swap icon visibility to match ``_is_grid``.

        ``is_grid=True`` → show the list-view icon (clicking takes
        the user TO list). ``is_grid=False`` → show the grid-view
        icon. Mirrors §25.4's convention where the button icon
        displays the destination mode, not the current one.
        """
        if self._list_icon_image is not None:
            self._list_icon_image.visible = self._is_grid
        if self._grid_icon_image is not None:
            self._grid_icon_image.visible = not self._is_grid

    def _update_percent_label(self, scale: float) -> None:
        """Set the percent-label text to ``NN%`` for ``scale``."""
        if self._percent_label is not None:
            self._percent_label.text = self._format_percent(scale)

    @staticmethod
    def _format_percent(scale: float) -> str:
        """Return e.g. ``"100%"`` for ``scale=1.0``."""
        return f"{int(round(scale * 100))}%"

    # ── Public API ───────────────────────────────────────────────────────────

    def set_slider_index(self, index: int) -> None:
        """Drive the slider to ``index`` programmatically (Step 57).

        Used by :class:`FileBrowserWidget` to restore the grid-view
        scale from persistent :class:`Settings` on window re-open.
        Fires the usual ``on_scale`` / ``on_toggle_grid`` callbacks
        so the grid view rescales and any threshold-crossing flips
        the view mode — the settings-restore path wants the same
        visual result as a user slider drag.

        Out-of-range or non-int values are a silent no-op. The guard
        against a pre-build / post-destroy call keeps the restore
        path safe even if the widget was never fully built (test
        harnesses occasionally construct without a build context).
        """
        try:
            idx = int(index)
        except (TypeError, ValueError):
            return
        if idx not in SCALE_MAP:
            return
        if self._slider is None:
            return
        self._slider.model.set_value(idx)

    @property
    def current_slider_index(self) -> int:
        """Current slider index, or the default when the slider is gone."""
        if self._slider is None:
            return _DEFAULT_SLIDER_INDEX
        return int(self._slider.model.get_value_as_int())

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Release widget refs; drop the slider subscription handle.

        Idempotent — the ``is not None`` guards short-circuit a
        second call. Order matters: drop the subscription first so
        the C++ side does not call back into a half-nulled widget
        during teardown, then null every widget ref, then finally
        drop the two handler refs.
        """
        # Dropping the handle reference releases ovui's internal
        # bound callback. There is no explicit removal API in this
        # ovui build (``add_value_changed_fn`` has no ``remove_``
        # counterpart — same pattern :mod:`path_field` uses for its
        # popup subscription).
        self._slider_value_changed_sub = None
        self._toggle_button = None
        self._grid_icon_image = None
        self._list_icon_image = None
        self._slider = None
        self._percent_label = None
        self._hstack = None
        # Drop handler refs last — a pending callback that sneaks
        # through the guards above then falls through silently.
        self._on_scale = None
        self._on_toggle_grid = None


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovwidgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_PROVIDER_CACHE)
