# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Dockable shell for the Layers panel (LAYERS-PLAN Step 8 → Step 16).

Mirrors :class:`ovwidgets.stage.window.StageWindow` in structure: the window
owns docking, title, module styles, and lifecycle; the tree-model +
delegate machinery lands in Phase C. The window is late-bound to a
:class:`ovwidgets.common.adapters.LayerStackAdapter` — :meth:`set_adapter`
stores it and triggers a frame rebuild; ``_build_ui`` materialises a
:class:`LayerModel` and the ``ui.TreeView`` that renders it.

Step 16 wires row selection: ``set_selection_changed_fn`` forwards the
TreeView's selected item list into :meth:`LayerModel.set_selected_items`
so downstream consumers (context menu, Step 55 ``LayerSelectionWatch``)
read a single authoritative snapshot. Selection visuals come from the
``Layers.TreeView:selected`` / ``:hovered`` style rules.
"""

from typing import TYPE_CHECKING, Any, Dict, List, Optional

import omni.ui as ui
from ovui_data_adapters.common import LayerStackAdapter

from ovwidgets.common.managed_window import ManagedWindow
from ovwidgets.common.settings import Settings
from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
from ovwidgets.layers.commands.sublayer_commands import (
    CreateSublayerCommand,
    InsertSublayerCommand,
)
from ovwidgets.layers.context_menu import ContextMenuBuilder, MenuContext
from ovwidgets.layers.layer_delegate import LayerDelegate
from ovwidgets.layers.layer_item import LayerItem
from ovwidgets.layers.layer_model import DefaultLayerSettings, LayerModel
from ovwidgets.layers.layer_settings import LayerSettings
from ovwidgets.layers.models.save_all_model import SaveAllValueModel
from ovwidgets.layers.options_button import OptionsButton
from ovwidgets.layers.selection_watch import LayerSelectionWatch
from ovwidgets.layers.style import LAYERS_STYLES

# Step 51 — filter-bar icon providers, cached per process. The standalone
# ``omni.ui`` build routes ``ui.Image(source_url)`` through ``stb_image``
# (no SVG support), so we reuse the raster PNGs ``ovwidgets.common.style.urls``
# already ships under semantic names (``stage_search`` and
# ``stage_close_x`` — the names are registered against the search.png /
# close_x.png files and the same PNGs are shared across Stage, Property,
# and now the Layers filter bar for pixel-identical chrome).
_LAYERS_FILTER_ICON_CACHE: Dict[str, Any] = {}
_FOOTER_TREE_GAP = 6
_FOOTER_BUTTON_GAP = 5
_TOOLBAR_BUTTON_GAP = _FOOTER_BUTTON_GAP
_TOOLBAR_HEIGHT = 32
_OPTIONS_BUTTON_SIZE = 24
_SAVE_ALL_BUTTON_WIDTH = 92
_SAVE_ALL_BUTTON_HEIGHT = 22


def _layers_filter_icon_provider(name: str) -> Any:
    """Return a cached :class:`ui.RasterImageProvider` for ``name``.

    Same pattern as :func:`ovwidgets.property.window._filter_icon_provider` —
    the raster provider is expensive to instantiate and its image data
    never changes per-process, so one cached instance is shared across
    every :class:`LayerWindow` that needs the same icon.
    """
    provider = _LAYERS_FILTER_ICON_CACHE.get(name)
    if provider is None:
        provider = ui.RasterImageProvider(_STYLE_ICON_PATHS[name])
        _LAYERS_FILTER_ICON_CACHE[name] = provider
    return provider

if TYPE_CHECKING:  # pragma: no cover — import guard
    from ovwidgets.common.services import WidgetServices


class LayerWindow(ManagedWindow):
    """Dockable Layers panel shell.

    Step 8 shipped the scaffold; Step 11 added the ``LAYERS_STYLES``
    palette; Step 13 (this revision) wires the model and the single-
    column ``ui.TreeView`` into :meth:`_build_ui`. Phase D adds the
    multi-column delegate, the header toolbar, and the context menu.
    """

    TITLE = "Layers"

    # Step 62 — user-visible copy surfaced in the polish pass. Kept as
    # class-level constants so tests can assert the exact strings
    # without duplicating the message text and so a rename propagates
    # from one edit.
    EMPTY_STAGE_MESSAGE = "Open a USD stage to see layers"
    FILTER_PLACEHOLDER_TEXT = "Filter layers..."

    # Column-width contract (LAYERS-PLAN Step 17, LAYERS-WINDOW-ARCHITECTURE
    # §20.5). Name column stretches; the six flag columns are fixed px so
    # every icon row lines up regardless of panel width. Lock (col 6) is
    # 26 px to give the larger padlock glyph breathing room. This list is
    # consumed by ``ui.TreeView``'s ctor and cannot be mutated after the
    # widget is built.
    _COLUMN_WIDTHS = [
        ui.Fraction(1),  # 0 · name (flex)
        ui.Pixel(24),    # 1 · live / live-session
        ui.Pixel(24),    # 2 · save / dirty
        ui.Pixel(24),    # 3 · local mute
        ui.Pixel(24),    # 4 · global mute
        ui.Pixel(24),    # 5 · latest / outdated
        ui.Pixel(26),    # 6 · lock
    ]

    def __init__(
        self,
        services: "Optional[WidgetServices]" = None,
        adapter: Optional[LayerStackAdapter] = None,
        settings: "Optional[DefaultLayerSettings | LayerSettings]" = None,
    ) -> None:
        self._services = services
        self._adapter = adapter
        # Step 52 — resolve the :class:`LayerSettings` wrapper once at
        # construction time. Explicit ``settings`` arg wins (tests pass
        # ``DefaultLayerSettings`` for isolation); otherwise probe
        # ``services.settings`` for a real :class:`Settings` store and wrap
        # it in :class:`LayerSettings`. Headless / MagicMock ``app``
        # values where ``services.settings`` is missing or not a
        # :class:`Settings` fall back to :class:`DefaultLayerSettings`
        # so the window stays buildable in unit tests that do not need
        # persistence.
        if settings is not None:
            self._settings: "DefaultLayerSettings | LayerSettings" = settings
        else:
            # Step 11.2: prefer a Settings exposed on the services
            # object (legacy test fakes that still attach
            # ``.settings`` for FakeApp convenience), then fall back
            # to the common-side ``Settings.instance()`` singleton
            # wired by ``Application.__init__`` in Step 10. Headless
            # paths with neither register fall through to the
            # unit-test :class:`DefaultLayerSettings`.
            app_settings = getattr(services, "settings", None)
            if not isinstance(app_settings, Settings):
                # Only honour an *explicitly registered* Settings
                # singleton (Application.__init__ Step 10), not a
                # lazy-default one. Tests that pass a MagicMock
                # ``services`` and expect ``DefaultLayerSettings``
                # rely on this distinction.
                app_settings = Settings._instance
            if isinstance(app_settings, Settings):
                self._settings = LayerSettings(app_settings)
            else:
                self._settings = DefaultLayerSettings()
        # Phase C slots — ``_model`` + ``_tree_view`` + ``_delegate`` are
        # populated by :meth:`_build_ui` when an adapter is present. The
        # delegate (Step 17) is stateless enough to survive ``ui.Frame``
        # rebuilds, so we cache it alongside the model to avoid thrashing
        # allocations every dock restore.
        self._model: Optional[LayerModel] = None
        self._tree_view: Any = None
        self._tree_scrolling_frame: Any = None
        self._delegate: Optional[LayerDelegate] = None

        # Step 35 — toolbar widgets wired by :meth:`_build_toolbar`
        # during the next ``_build_ui`` pass. Handles cached so the
        # badge / enabled-state watchers can toggle without rebuilding
        # the frame. ``_save_all_sub`` is the value-model subscription
        # that re-renders the button when any layer's dirty state flips.
        self._save_all_button: Any = None
        self._save_all_label: Any = None
        self._save_all_badge: Any = None
        self._save_all_sub: Any = None
        # Step 38 — right-click context-menu builder. Constructed
        # lazily in :meth:`_build_ui` when a model first exists so
        # the builder and the model share a lifecycle; swapped on
        # every :meth:`set_adapter` so the builder always references
        # the current stack. Held here (rather than re-created per
        # right-click) so the menu-destroy-on-reshow path has a
        # stable handle to release.
        self._context_menu_builder: Optional[ContextMenuBuilder] = None

        # Step 51 — name-search filter chrome. ``_filter_field`` is the
        # :class:`ui.StringField` the user types into; the matching /
        # clear icon widgets live alongside so the active-state toggle
        # and the clear gesture can flip their ``visible`` / ``name``
        # synchronously in :meth:`_on_filter_changed`. The debounce
        # timer handle sits next to them because cancel / reschedule
        # reaches back into it on every keystroke.
        self._filter_field: Any = None
        self._filter_icon: Any = None
        self._filter_clear_button: Any = None
        # Group B — outer (border) and inner (fill) Rectangles wrapping
        # the filter StringField. ``_on_filter_begin_edit`` / ``_end_edit``
        # flip ``.name = "focused"`` on both so the ``::focused`` named
        # variants in :data:`LAYERS_STYLES` paint the accent ring.
        self._filter_rect: Any = None
        self._filter_border_rect: Any = None
        self._pending_filter_handle: Any = None
        self._empty_state_container: Any = None
        self._empty_state_label: Any = None
        # Step 62 — placeholder label painted over the empty filter
        # field. The standalone ``ui.StringField`` in this repo has no
        # native placeholder prop, so the hint rides on an overlay
        # :class:`ui.Label` whose ``visible`` flag flips alongside the
        # field's text in :meth:`_on_filter_changed`.
        self._filter_placeholder: Any = None

        # Step 53 — Options dropdown button. Sits on the left of the
        # Save-All strip and opens a ``ui.Menu`` of checkboxes bound
        # to every :class:`LayerSettings` toggle. Held here (rather
        # than rebuilt per-frame) so a toolbar rebuild can reuse the
        # same widget + menu handle without thrashing allocations;
        # :meth:`_build_toolbar` calls :meth:`OptionsButton.build` on
        # each pass to repaint the button into the fresh frame.
        self._options_button: Optional[OptionsButton] = OptionsButton(
            self._settings
        )

        # Step 54 — footer toolbar buttons (Insert / Create / Delete).
        # Owned by the frame the :meth:`_build_footer_bar` pass builds
        # into, so each rebuild drops the stale handles; cached on
        # ``self`` so :meth:`_refresh_footer_state` can flip the
        # ``enabled`` flag in response to tree-selection changes
        # without rebuilding the frame.
        self._insert_button: Any = None
        self._insert_label: Any = None
        self._create_button: Any = None
        self._create_label: Any = None
        self._delete_button: Any = None
        self._delete_label: Any = None
        # Step 55 — :class:`LayerSelectionWatch` owns the tree view's
        # ``set_selection_changed_fn`` slot. Constructed in
        # :meth:`_build_ui` once the model + tree exist and destroyed
        # here on frame rebuild / window destroy so a stale watch
        # can't dispatch into a dead tree view. Step 55a will move
        # the lifecycle to ``_visibility_changed_fn`` so the
        # per-frame sync stops while the panel is hidden.
        self._selection_watch: Optional[LayerSelectionWatch] = None
        super().__init__(self.TITLE, width=380, height=600)

    def _get_module_styles(self) -> dict:
        return LAYERS_STYLES

    @property
    def settings(self) -> "DefaultLayerSettings | LayerSettings":
        """Return the :class:`LayerSettings` (or dataclass fallback) in use.

        Step 53's Options button reads this to bind its checkbox
        dropdown to the live settings object so toggles round-trip to
        the persistent store on click.
        """
        return self._settings

    def _build_ui(self) -> None:
        # Drop the stale ``ui.TreeView`` handle from the previous build —
        # the widget is owned by the ``ui.Frame`` that's about to be
        # rewritten, so holding on would stall GC of the old paint tree.
        self._tree_view = None
        self._tree_scrolling_frame = None
        # Toolbar widgets are owned by the same frame — drop the old
        # handles so a rebuild does not leak stale button / badge refs.
        # The Save-All subscription is released explicitly: ovui does
        # not tear down bound callbacks when a widget's frame is
        # rewritten, so the old subscription would keep firing
        # ``_refresh_save_all_button`` against a dead widget handle.
        self._save_all_button = None
        self._save_all_label = None
        self._save_all_badge = None
        # Step 51 — filter-bar chrome is owned by the outgoing frame;
        # drop the handles and cancel any in-flight debounce timer so a
        # rebuild does not leak widget refs or keep a dead callback
        # pinned on ``Application.call_later``. The filter *text*
        # survives on :attr:`LayerModel.filter_text` and is applied to
        # the new field below.
        self._filter_field = None
        self._filter_icon = None
        self._filter_clear_button = None
        self._filter_placeholder = None
        self._filter_rect = None
        self._filter_border_rect = None
        self._empty_state_container = None
        self._empty_state_label = None
        # Step 54 — footer-button handles are owned by the outgoing
        # frame; drop them so a rebuild does not leak a live
        # ``ui.Button`` reference into the next pass. The buttons are
        # repainted in :meth:`_build_footer_bar` at the end of this
        # method.
        self._insert_button = None
        self._insert_label = None
        self._create_button = None
        self._create_label = None
        self._delete_button = None
        self._delete_label = None
        if self._pending_filter_handle is not None:
            self._pending_filter_handle.cancel()
            self._pending_filter_handle = None
        if self._save_all_sub is not None:
            # ovui's Subscription exposes ``unsubscribe`` (not the
            # ``cancel`` used by ovwidgets.common.settings.Subscription). Call
            # it explicitly so the model's callback list releases
            # the bound method before the widget it paints into is
            # collected.
            self._save_all_sub.unsubscribe()
            self._save_all_sub = None

        if self._adapter is None:
            # No stage is loaded yet (pre-open) or the stage was closed
            # (Step 15). Step 62 replaces the terse Step 8 placeholder
            # with an actionable hint ("Open a USD stage to see layers")
            # painted in the disabled-text tint so the empty panel
            # reads as an intentional waiting-state rather than a
            # broken panel. ``Layers.EmptyStageLabel`` picks up the
            # theme-aware disabled-text palette on both shades.
            with ui.VStack():
                ui.Spacer()
                ui.Label(
                    self.EMPTY_STAGE_MESSAGE,
                    style_type_name_override="Layers.EmptyStageLabel",
                    alignment=ui.Alignment.CENTER,
                )
                ui.Spacer()
            return

        # Reuse an existing model across frame rebuilds and adapter swaps
        # so the ``ui.TreeView`` keeps a stable model identity — Step 15
        # lets :meth:`LayerModel.set_adapter` re-target it in place.
        if self._model is None:
            self._model = LayerModel(
                self._adapter, services=self._services, settings=self._settings
            )
        # Step 17 — a single :class:`LayerDelegate` instance survives
        # frame rebuilds; re-using it matches the model's lifecycle and
        # keeps ``ui.TreeView`` bookkeeping stable across dock restores.
        if self._delegate is None:
            self._delegate = LayerDelegate()
        # Step 38 — one context-menu builder per window / model pair.
        # Construct lazily on first build so a bare-model headless
        # test path (no window) can still exercise the menu builder
        # in isolation. Rebound on :meth:`set_adapter` via
        # :meth:`_ensure_context_menu_builder` so the builder's
        # ``_model`` reference always tracks the live model.
        self._ensure_context_menu_builder()
        # Wire the delegate → builder bridge. Re-assigning
        # ``on_right_click`` on every build is cheap (attribute set)
        # and keeps the closure pointed at the live builder, even if
        # :meth:`set_adapter` swapped it mid-session.
        self._delegate.on_right_click = self._on_row_right_click
        with ui.VStack(spacing=0):
            # Step 51 — filter bar above the Save-All toolbar. Mirrors
            # the Stage / Property filter-bar chrome (search icon,
            # centred StringField, trailing clear-X) so the three
            # panels read as one family when docked side by side.
            self._build_filter_bar()
            # 1-px divider between the filter bar and the Save-All
            # strip so the two same-tinted rows read as distinct
            # zones, mirroring the ``Stage.Separator`` /
            # ``Property.Separator`` convention.
            ui.Rectangle(
                height=ui.Pixel(1),
                style_type_name_override="Layers.FilterSeparator",
            )
            ui.Rectangle(
                height=ui.Pixel(_TOOLBAR_BUTTON_GAP),
                style_type_name_override="Layers.ToolbarButtonGap",
            )
            # Step 35 — header toolbar with the Save-All button and
            # its dirty badge. Sits above the tree so the full-width
            # separator below it visually divides "controls" from
            # "layers list".
            self._build_toolbar()
            # Step 38 — wrap the TreeView in a ZStack so an
            # invisible background Rectangle below the tree can
            # catch right-clicks on the empty scroll area. The
            # TreeView consumes row-level clicks via the delegate's
            # per-row handler; any click that doesn't land on a row
            # falls through to the Rectangle and opens the reduced
            # empty-area menu. A plain ``ui.Rectangle`` suffices —
            # it renders transparent (no style on the plain name)
            # and only exists to carry the mouse handler.
            self._tree_scrolling_frame = ui.ScrollingFrame(
                horizontal_scrollbar_policy=(
                    ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF
                ),
                vertical_scrollbar_policy=(
                    ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED
                ),
                style_type_name_override="Layers.TreeScrollingFrame",
            )
            with self._tree_scrolling_frame:
                with ui.ZStack():
                    self._empty_area_hit = ui.Rectangle(
                        style_type_name_override="Layers.EmptyAreaHit",
                    )
                    self._empty_area_hit.set_mouse_pressed_fn(
                        self._on_empty_area_pressed
                    )
                    # Step 45 — external file drops that land in the
                    # TreeView's empty scroll area route through the
                    # underlying hit rectangle. ovui's ``set_accept_drop_fn``
                    # gates the visual feedback (the Rectangle only shows a
                    # "ready to accept" hover when the predicate returns
                    # True), and ``set_drop_fn`` fires on release with the
                    # path string. The model's helper validates extensions
                    # and pushes the :class:`InsertSublayerCommand` batch.
                    self._empty_area_hit.set_accept_drop_fn(
                        self._on_empty_area_accept_drop
                    )
                    self._empty_area_hit.set_drop_fn(
                        self._on_empty_area_dropped
                    )
                    self._tree_view = ui.TreeView(
                        self._model,
                        delegate=self._delegate,
                        column_widths=self._COLUMN_WIDTHS,
                        header_visible=False,
                        root_visible=True,
                        drop_between_items=True,
                        style_type_name_override="Layers.TreeView",
                    )
                    # Step 55 — hand the tree's selection slot to a fresh
                    # :class:`LayerSelectionWatch`. The watch's
                    # ``on_change`` hook runs :meth:`_on_tree_selection_changed`
                    # so the Step-16 model sync and the Step-54 footer
                    # refresh still fire on every click; the watch's own
                    # focus-listener fan-out serves the §24.5 Property
                    # panel protocol. A rebuild drops the previous watch
                    # first so it can't dispatch into the dead tree.
                    if self._selection_watch is not None:
                        self._selection_watch.destroy()
                        self._selection_watch = None
                    # Headless / mock ``services`` fixtures may omit the
                    # selection bus entirely (``services=None`` /
                    # ``FakeServices`` without the slot). The bus is held
                    # for Step 56+ forwarding; Step 55 itself never calls
                    # it, so ``getattr(..., None)`` is safe. Test fakes
                    # that pass a ``services`` object lacking
                    # ``selection_bus`` get ``None`` here.
                    selection_bus = getattr(
                        self._services, "selection_bus", None
                    )
                    # Step 56 — thread :meth:`Application.call_later` into
                    # the watch so a reentrant :class:`SelectionBusError`
                    # hit during prim-spec forwarding can defer the retry
                    # to the next frame. Headless / mock harnesses without
                    # a scheduler fall through silently.
                    # Same lenient ``getattr`` -- partial-fake test paths
                    # without ``call_later`` get ``None``.
                    call_later = getattr(self._services, "call_later", None)
                    self._selection_watch = LayerSelectionWatch(
                        self._tree_view,
                        self._model,
                        selection_bus,
                        on_change=self._on_tree_selection_changed,
                        call_later=call_later,
                    )
                    # Step 51 — empty-state overlay painted when the active
                    # filter leaves the tree with zero visible rows. Sits
                    # on top of the TreeView (ZStack) and flips
                    # ``visible`` in :meth:`_update_empty_state`. Kept
                    # pointer-transparent by default; no click handler
                    # means right-clicks on empty space still reach the
                    # underlying hit rectangle.
                    self._empty_state_container = ui.VStack(visible=False)
                    with self._empty_state_container:
                        ui.Spacer(height=ui.Pixel(48))
                        self._empty_state_label = ui.Label(
                            "No matching layers",
                            style_type_name_override="Layers.EmptyState",
                            alignment=ui.Alignment.CENTER_TOP,
                        )
                        ui.Spacer()
            ui.Rectangle(
                height=ui.Pixel(_FOOTER_TREE_GAP),
                style_type_name_override="Layers.FooterGap",
            )
            # Step 54 — 1-px divider between the tree body and the
            # footer strip. Mirrors ``Layers.FilterSeparator`` above
            # the Save-All toolbar so the top and bottom chrome rows
            # read as symmetrical bookends on the tree.
            ui.Rectangle(
                height=ui.Pixel(1),
                style_type_name_override="Layers.FooterSeparator",
            )
            ui.Rectangle(
                height=ui.Pixel(_FOOTER_BUTTON_GAP),
                style_type_name_override="Layers.FooterButtonGap",
            )
            # Step 54 — footer bar with Insert / Create / Delete
            # buttons. Mirrors the context-menu trio and operates on
            # the single-selected :class:`LayerItem` (or the root
            # layer when no single layer is selected).
            self._build_footer_bar()
        # Restore any pre-existing filter text so a frame rebuild (e.g.
        # after ``set_adapter``) doesn't visually clear the search
        # input — the model holds the authoritative filter state.
        if self._model is not None and self._model.filter_text:
            self._filter_field.model.set_value(self._model.filter_text)
        elif self._filter_placeholder is not None:
            # Step 62 — on a fresh build with no pre-existing filter
            # text, the value-changed callback does not fire, so the
            # placeholder visibility would stay at its widget default
            # (``True``) which is what we want. Keep this branch
            # explicit so a future default flip doesn't silently hide
            # the hint.
            self._filter_placeholder.visible = True
        self._update_empty_state()
        self._refresh_footer_state()

    def _build_filter_bar(self) -> None:
        """Paint the name-search filter bar (LAYERS-PLAN Step 51).

        30-px horizontal strip above the Save-All toolbar. Mirrors
        ``StageWidget.build`` (``ovwidgets.stage/widget/stage_widget.py:107-204``)
        one-for-one so the two filter bars render pixel-identically
        when the panels are docked side-by-side: same outer 6-px
        margins, same 22-px bordered pill, same 8-px / 13-px / 6-px /
        18-px / 8-px column rhythm inside the pill, same 18-px field
        + placeholder height, same icon glyphs (search + close-x),
        same focus-ring toggle path.

        The structural rule the previous implementation broke: the
        magnifier icon and the clear-x button must sit **inside** the
        bordered pill (alongside the StringField), not outside as
        separate columns. The user noticed Layers' filter bar didn't
        match Stage's; restoring that structural invariant is what
        this rewrite fixes.

        ``_filter_field`` value-changed → :meth:`_on_filter_changed`;
        begin/end-edit → :meth:`_on_filter_begin_edit` /
        :meth:`_on_filter_end_edit`. Clear-button mouse-press →
        :meth:`_clear_filter`. Debounce / chrome flips live on the
        callbacks so this builder stays a pure layout function.
        """
        with ui.ZStack(height=ui.Pixel(30)):
            ui.Rectangle(style_type_name_override="Layers.FilterBackground")
            with ui.HStack():
                ui.Spacer(width=ui.Pixel(6))
                with ui.VStack():
                    ui.Spacer()
                    with ui.ZStack(height=ui.Pixel(22)):
                        # Outer border Rectangle — paints
                        # ``cl.border_default`` as a solid fill behind
                        # the inner fill Rectangle so a reliable 1-px
                        # ring renders even on standalone ovui builds
                        # whose ``border_width`` path is unreliable.
                        self._filter_border_rect = ui.Rectangle(
                            style_type_name_override="Layers.FilterFieldBorder",
                        )
                        # Inner fill Rectangle — 1 px inside on every
                        # edge so the outer fill reads as the border.
                        with ui.VStack():
                            ui.Spacer(height=ui.Pixel(1))
                            with ui.HStack():
                                ui.Spacer(width=ui.Pixel(1))
                                self._filter_rect = ui.Rectangle(
                                    height=ui.Pixel(20),
                                    style_type_name_override="Layers.FilterField",
                                )
                                ui.Spacer(width=ui.Pixel(1))
                            ui.Spacer(height=ui.Pixel(1))
                        # Contents inside the pill: 8-px gutter, then
                        # search-icon column, 6-px gap, StringField +
                        # placeholder, clear-x column, 8-px gutter.
                        with ui.HStack():
                            ui.Spacer(width=ui.Pixel(8))
                            with ui.VStack(width=ui.Pixel(13)):
                                ui.Spacer()
                                self._filter_icon = ui.ImageWithProvider(
                                    _layers_filter_icon_provider("stage_search"),
                                    width=13, height=13,
                                    style_type_name_override="Layers.FilterIcon",
                                )
                                ui.Spacer()
                            ui.Spacer(width=ui.Pixel(6))
                            with ui.VStack():
                                ui.Spacer()
                                with ui.ZStack(height=ui.Pixel(18)):
                                    self._filter_field = ui.StringField(
                                        style_type_name_override=(
                                            "Layers.FilterFieldInput"
                                        ),
                                        height=ui.Pixel(18),
                                        tooltip=(
                                            "Filter layers by name — the "
                                            "tree shows only layers whose "
                                            "display name contains the "
                                            "text (case-insensitive)."
                                        ),
                                    )
                                    self._filter_placeholder = ui.Label(
                                        self.FILTER_PLACEHOLDER_TEXT,
                                        style_type_name_override=(
                                            "Layers.FilterPlaceholder"
                                        ),
                                        alignment=ui.Alignment.LEFT_CENTER,
                                        height=ui.Pixel(18),
                                    )
                                    # Placeholder eats left-clicks before
                                    # they reach the StringField below
                                    # (z-order); forward to focus_keyboard
                                    # so the click still focuses the
                                    # input. Mirrors Stage's pattern at
                                    # ``stage_widget.py:162-167``.
                                    self._filter_placeholder.set_mouse_pressed_fn(
                                        lambda x, y, b, m: (
                                            self._focus_filter_field()
                                            if b == 0 else None
                                        )
                                    )
                                ui.Spacer()
                            self._filter_field.model.add_value_changed_fn(
                                self._on_filter_changed
                            )
                            # Toggle ``::focused`` on both rectangles
                            # when the StringField gains / loses
                            # keyboard focus. omni.ui's ``:focused``
                            # pseudo-state does not fire reliably on a
                            # ``ui.Rectangle``, so the focus ring is
                            # driven imperatively (mirrors Stage's
                            # ``_on_filter_begin_edit`` /
                            # ``_on_filter_end_edit``).
                            self._filter_field.model.add_begin_edit_fn(
                                self._on_filter_begin_edit
                            )
                            self._filter_field.model.add_end_edit_fn(
                                self._on_filter_end_edit
                            )
                            with ui.VStack(width=ui.Pixel(18)):
                                ui.Spacer()
                                self._filter_clear_button = ui.ImageWithProvider(
                                    _layers_filter_icon_provider(
                                        "stage_close_x"
                                    ),
                                    width=12, height=12,
                                    style_type_name_override=(
                                        "Layers.FilterClearButton.Image"
                                    ),
                                    visible=False,
                                )
                                self._filter_clear_button.set_mouse_pressed_fn(
                                    lambda x, y, b, m: (
                                        self._clear_filter()
                                        if b == 0 else None
                                    )
                                )
                                ui.Spacer()
                            ui.Spacer(width=ui.Pixel(8))
                    ui.Spacer()
                ui.Spacer(width=ui.Pixel(6))

    def _on_filter_changed(self, model: Any) -> None:
        """Handle a StringField value change — debounce the model filter.

        Chrome (clear button + icon active state) flips immediately so
        the user gets instant feedback on every keystroke. The filter
        itself is deferred by 150ms via :meth:`Application.call_later`
        so a rapid burst of input ("basel" → "basel ") produces one
        :meth:`LayerModel.filter_by_text` call, not five — same
        pattern ``ovwidgets.property.PropertyWindow`` uses.

        Tests that construct a bare window without an ``Application``
        fall back to applying the filter synchronously (no real frame
        loop to defer into) so headless assertions still see the
        post-filter tree.
        """
        text = model.get_value_as_string()
        has_text = bool(text)
        if self._filter_clear_button is not None:
            self._filter_clear_button.visible = has_text
        if self._filter_icon is not None:
            self._filter_icon.name = "active" if has_text else ""
        # Step 62 — hide the "Filter layers..." placeholder once the
        # user starts typing; re-reveal it when the field empties
        # again (the clear-X button drives the same code path).
        if self._filter_placeholder is not None:
            self._filter_placeholder.visible = not has_text
        if self._pending_filter_handle is not None:
            self._pending_filter_handle.cancel()
            self._pending_filter_handle = None
        try:
            from ovwidgets.common import scheduler as _scheduler
            self._pending_filter_handle = _scheduler.call_later(
                0.15, lambda: self._apply_filter(text)
            )
        except RuntimeError:
            # No scheduler registered — headless / unit-test path.
            # Apply synchronously so tests don't have to pump a frame
            # loop to see the filter take effect.
            self._apply_filter(text)
            return

    def _apply_filter(self, text: str) -> None:
        """Push the debounced search text into the model and repaint.

        Fired by the :meth:`Application.call_later` timer that
        :meth:`_on_filter_changed` schedules 150ms after the last
        keystroke. Updates the empty-state overlay alongside the model
        filter so "No matching layers" appears / disappears in the
        same tick as the tree rebuild.
        """
        self._pending_filter_handle = None
        if self._model is not None:
            self._model.filter_by_text(text)
        self._update_empty_state()

    def _focus_filter_field(self) -> None:
        """Programmatically grab keyboard focus on the filter StringField.

        Mirrors ``StageWidget._focus_filter_field``. Used by the
        placeholder Label's mouse-pressed handler so a left-click on the
        "Filter layers..." hint forwards the focus to the underlying
        ``ui.StringField`` (the Label is on top in z-order and would
        otherwise consume the click without reaching the field).
        """
        if self._filter_field is None:
            return
        focus_keyboard = getattr(self._filter_field, "focus_keyboard", None)
        if focus_keyboard is not None:
            focus_keyboard()

    def _on_filter_begin_edit(self, model: Any) -> None:
        """Paint the focus ring on the filter pill.

        Mirrors ``StageWidget._on_filter_begin_edit``
        (``ovwidgets.stage/widget/stage_widget.py:322-326``). omni.ui's
        ``:focused`` pseudo-state does not fire on a ``ui.Rectangle``,
        so the visible focus border is driven manually by flipping
        ``name = "focused"`` on both the inner fill rectangle and the
        outer border rectangle. The ``::focused`` named variants in
        :data:`LAYERS_STYLES` then paint the accent-tinted ring on the
        next frame.
        """
        if self._filter_rect is not None:
            self._filter_rect.name = "focused"
        if self._filter_border_rect is not None:
            self._filter_border_rect.name = "focused"

    def _on_filter_end_edit(self, model: Any) -> None:
        """Clear the focus ring when the StringField loses focus."""
        if self._filter_rect is not None:
            self._filter_rect.name = ""
        if self._filter_border_rect is not None:
            self._filter_border_rect.name = ""

    def _clear_filter(self) -> None:
        """Reset the search field — driven by the trailing X button.

        Writing an empty string into the field's model triggers
        :meth:`_on_filter_changed`, which in turn clears the chrome
        and debounces the model call. Keeping the single code path
        through the value-changed callback means the field, model,
        and overlay all reach the "no filter" state by the same
        route — no divergent reset logic to drift.
        """
        if self._filter_field is not None:
            self._filter_field.model.set_value("")

    def _update_empty_state(self) -> None:
        """Show / hide the "No matching layers" overlay (Step 51).

        Called after every filter change and after :meth:`_build_ui`
        so the overlay state tracks the model's current match set.
        The overlay is gated on both the filter being active *and* the
        model reporting zero matches — a cleared filter always hides
        the overlay so a previously-empty search leaves no ghost
        message when the user erases their query.
        """
        container = self._empty_state_container
        if container is None:
            return
        if self._model is None:
            container.visible = False
            return
        active = bool(self._model.filter_text)
        container.visible = active and not self._model.has_any_filter_match()

    def _build_toolbar(self) -> None:
        """Paint the Save-All toolbar strip (LAYERS-PLAN Step 35).

        Builds a ``height=32`` horizontal strip above the tree. The
        strip carries a single Save-All button at the right edge;
        the button's :class:`ui.ZStack` envelope nests a 6-px amber
        badge dot in the top-right corner that is visible only when
        :meth:`SaveAllValueModel.get_value_as_bool` returns ``True``.
        The button is disabled (and dimmed through the
        ``:disabled`` pseudo-state) whenever the aggregate is clean
        so the user cannot fire an empty undo group.

        A :meth:`SaveAllValueModel.subscribe_value_changed_fn`
        subscription keeps the badge and the ``enabled`` flag in sync
        with the model; the :class:`LayerModel` repaint-poke in
        :meth:`LayerModel._flush_events` (fired on every adapter
        event) is what drives the refresh. The subscription is
        cached on ``self`` so :meth:`_build_ui` can cancel it on
        rebuild / :meth:`destroy` and avoid leaking a live callback
        into a dead widget.
        """
        if self._model is None:
            return
        save_all_model = self._model.get_save_all_model()
        with ui.HStack(
            height=ui.Pixel(_TOOLBAR_HEIGHT),
            style_type_name_override="Layers.Toolbar",
        ):
            # Step 53 — Options dropdown (gear glyph) sits on the
            # left of the toolbar strip. A 4-px leading spacer keeps
            # the button clear of the panel's left edge; a trailing
            # flex Spacer pushes the Save-All button to the right
            # following the Kit Layers convention
            # (LAYERS-WINDOW-ARCHITECTURE §20.2).
            ui.Spacer(width=ui.Pixel(4))
            with ui.VStack(width=ui.Pixel(_OPTIONS_BUTTON_SIZE)):
                ui.Spacer()
                if self._options_button is not None:
                    self._options_button.build()
                ui.Spacer()
            ui.Spacer()
            with ui.VStack(width=ui.Pixel(_SAVE_ALL_BUTTON_WIDTH)):
                ui.Spacer()
                with ui.ZStack(
                    width=ui.Pixel(_SAVE_ALL_BUTTON_WIDTH),
                    height=ui.Pixel(_SAVE_ALL_BUTTON_HEIGHT),
                ):
                    self._save_all_button = ui.Button(
                        " ",
                        width=ui.Pixel(_SAVE_ALL_BUTTON_WIDTH),
                        height=ui.Pixel(_SAVE_ALL_BUTTON_HEIGHT),
                        clicked_fn=self._on_save_all_clicked,
                        style_type_name_override="Layers.SaveAllButton",
                        tooltip=(
                            "Save every dirty layer (one undo entry per "
                            "click). Disabled when nothing is dirty."
                        ),
                    )
                    self._save_all_label = ui.Label(
                        "Save All",
                        width=ui.Pixel(_SAVE_ALL_BUTTON_WIDTH),
                        height=ui.Pixel(_SAVE_ALL_BUTTON_HEIGHT),
                        alignment=ui.Alignment.CENTER,
                        style_type_name_override="Layers.SaveAllButtonLabel",
                    )
                    self._save_all_label.opaque_for_mouse_events = False
                    # Badge dot — a tiny filled :class:`ui.Circle` nested
                    # in the top-right corner of the button. The HStack /
                    # VStack pair pins it without stretching; the left
                    # and bottom spacers push it to the top-right.
                    with ui.HStack():
                        ui.Spacer()
                        with ui.VStack(width=ui.Pixel(10)):
                            ui.Spacer(height=ui.Pixel(2))
                            self._save_all_badge = ui.Circle(
                                width=ui.Pixel(8),
                                height=ui.Pixel(8),
                                alignment=ui.Alignment.CENTER,
                                style_type_name_override="Layers.SaveAllBadge",
                            )
                            ui.Spacer()
                        ui.Spacer(width=ui.Pixel(4))
                ui.Spacer()
            # Right margin so the button does not touch the scroll
            # bar when the tree overflows.
            ui.Spacer(width=ui.Pixel(4))

        self._refresh_save_all_state(save_all_model)
        self._save_all_sub = save_all_model.subscribe_value_changed_fn(
            lambda _m, _sm=save_all_model: self._refresh_save_all_state(_sm)
        )

    def _refresh_save_all_state(
        self,
        save_all_model: SaveAllValueModel,
    ) -> None:
        """Sync the Save-All button's enabled + badge state to the model.

        Called once on build and again from the model's
        ``value_changed`` subscription on every adapter event that
        could flip a dirty bit. Quietly no-ops when either widget
        handle has been torn down (a late callback after
        :meth:`_build_ui` rebuilt the frame).
        """
        if self._save_all_button is None or self._save_all_badge is None:
            return
        has_dirty = save_all_model.get_value_as_bool()
        # ovui ``ui.Button`` dims through the ``:disabled`` pseudo-
        # state — the ``Layers.SaveAllButton:disabled`` style entry
        # carries the low-salience palette (text_disabled, interactive
        # _disabled) so users read "nothing to save" at a glance.
        self._save_all_button.enabled = has_dirty
        if self._save_all_label is not None:
            self._save_all_label.name = "enabled" if has_dirty else "disabled"
        # The badge paints in amber only when ``name == "dirty"`` —
        # the base ``Layers.SaveAllBadge`` entry is transparent so
        # the Circle disappears when clean without us toggling
        # ``visible``. Swapping the ``name`` is the idiomatic ovui
        # re-paint hook and avoids a layout-reflow that ``visible``
        # would trigger on every dirty-bit flip.
        self._save_all_badge.name = "dirty" if has_dirty else ""

    def _build_footer_bar(self) -> None:
        """Paint the bottom Insert / Create / Delete toolbar (Step 54).

        28-px horizontal strip anchored at the bottom of the Layers
        window that mirrors the context-menu trio (Insert Sublayer /
        Create Sublayer / Remove Layer) as always-visible icon
        buttons. Matches LAYERS-WINDOW-ARCHITECTURE §25.5 — three
        buttons in the strip, each routing through the same command
        pipeline the right-click menu uses so every gesture joins the
        undo stack on equal footing.

        Buttons carry short text labels (``Insert`` / ``New`` /
        ``Delete``) rather than SVG icons because the standalone
        :mod:`omni.ui` build in this repo routes
        ``ui.Image(source_url)`` through ``stb_image``, which does not
        recognise SVG (same constraint the Step 53
        :class:`OptionsButton` works around with primitive glyphs).
        Short-text labels also sidestep the "glyph missing from
        NVIDIA Sans" trap that non-ASCII Unicode icons (``✱``,
        ``⊕``, …) would hit on the headless font pack. The tooltip
        on each button carries the verbose action sentence so
        discoverability stays intact.

        All three buttons are disabled when the model is missing or
        the current tree-selection context cannot support the action
        (e.g. Delete on the root layer). :meth:`_refresh_footer_state`
        recomputes the ``enabled`` flags from ``selected_items`` on
        every selection change — callers do not need to rebuild the
        footer to toggle a button's disabled state.
        """
        with ui.HStack(
            height=ui.Pixel(28),
            style_type_name_override="Layers.Footer",
        ):
            # Leading flex spacer centres the three-button trio on the
            # strip so the footer does not drift left when the panel
            # widens. Fixed 4-px inter-button spacers keep adjacent
            # buttons from touching on sub-pixel layouts.
            ui.Spacer(width=ui.Pixel(4))
            ui.Spacer()
            with ui.ZStack(width=ui.Pixel(64), height=ui.Pixel(22)):
                self._insert_button = ui.Button(
                    " ",
                    width=ui.Pixel(64),
                    height=ui.Pixel(22),
                    clicked_fn=self._on_footer_insert_clicked,
                    style_type_name_override="Layers.FooterButton",
                    tooltip=(
                        "Insert Sublayer — add an existing USD file as a "
                        "sublayer under the selected layer (or root when "
                        "no layer is selected)."
                    ),
                )
                self._insert_label = ui.Label(
                    "Insert",
                    width=ui.Pixel(64),
                    height=ui.Pixel(22),
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Layers.FooterButtonLabel",
                )
                self._insert_label.opaque_for_mouse_events = False
            ui.Spacer(width=ui.Pixel(6))
            with ui.ZStack(width=ui.Pixel(64), height=ui.Pixel(22)):
                self._create_button = ui.Button(
                    " ",
                    width=ui.Pixel(64),
                    height=ui.Pixel(22),
                    clicked_fn=self._on_footer_create_clicked,
                    style_type_name_override="Layers.FooterButton",
                    tooltip=(
                        "Create Sublayer — mint a new anonymous sublayer "
                        "under the selected layer (or root when no layer "
                        "is selected)."
                    ),
                )
                self._create_label = ui.Label(
                    "New",
                    width=ui.Pixel(64),
                    height=ui.Pixel(22),
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Layers.FooterButtonLabel",
                )
                self._create_label.opaque_for_mouse_events = False
            ui.Spacer(width=ui.Pixel(6))
            with ui.ZStack(width=ui.Pixel(64), height=ui.Pixel(22)):
                self._delete_button = ui.Button(
                    " ",
                    width=ui.Pixel(64),
                    height=ui.Pixel(22),
                    clicked_fn=self._on_footer_delete_clicked,
                    style_type_name_override="Layers.FooterButton",
                    tooltip=(
                        "Remove Layer — detach the selected sublayer from "
                        "its parent (disabled when the root is selected or "
                        "no single layer is selected)."
                    ),
                )
                self._delete_label = ui.Label(
                    "Delete",
                    width=ui.Pixel(64),
                    height=ui.Pixel(22),
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Layers.FooterButtonLabel",
                )
                self._delete_label.opaque_for_mouse_events = False
            ui.Spacer()
            ui.Spacer(width=ui.Pixel(4))

    def _footer_target_and_delete_spec(
        self,
    ) -> "tuple[Optional[LayerItem], Optional[tuple[str, int]]]":
        """Resolve the footer's target layer and the Delete (parent, pos).

        Returns a ``(target, delete_spec)`` pair:

        - ``target`` is the :class:`LayerItem` the Insert / Create
          gestures operate on. A single-layer tree selection wins;
          otherwise the root item is used (mirroring the context menu
          "no-selection" gesture trio from Step 39).
        - ``delete_spec`` is the ``(parent_identifier, position)``
          tuple Delete routes into ``LayerModel._request_remove_sublayer``
          on. It's ``None`` whenever Delete is not applicable — no
          single LayerItem selected, the selected item is root, or
          the parent/position cannot be resolved from the adapter.

        Splitting the selection-read logic out of the click handlers
        keeps :meth:`_refresh_footer_state` and the three click
        handlers reading the same canonical snapshot of "what would
        each button do right now".
        """
        if self._model is None:
            return None, None
        root = self._model.root_item
        layer_selection = [
            i for i in self._model.selected_items if isinstance(i, LayerItem)
        ]
        single = layer_selection[0] if len(layer_selection) == 1 else None
        # Insert / Create target: single selection or root fallback.
        target = single if single is not None else root
        # Delete target: needs a non-root single selection *and* an
        # adapter-visible parent so we can compute the slot index.
        delete_spec: Optional[tuple[str, int]] = None
        if (
            single is not None
            and root is not None
            and single.identifier != root.identifier
        ):
            parent = single._parent
            adapter = self._model._adapter
            if parent is not None and adapter is not None:
                parent_handle = adapter.find_layer(parent.identifier)
                if parent_handle is not None:
                    children = adapter.get_sublayer_identifiers(parent_handle)
                    if single.identifier in children:
                        delete_spec = (
                            parent.identifier,
                            children.index(single.identifier),
                        )
        return target, delete_spec

    def _refresh_footer_state(self) -> None:
        """Sync the footer buttons' ``enabled`` flags to the live selection.

        Called on every :meth:`_build_ui` pass and from
        :meth:`_on_tree_selection_changed` so the buttons visibly
        reflect whether each action is applicable right now. Guards
        against late callbacks that land after a rebuild has nulled
        the widget handles (same pattern the Save-All refresh uses).
        """
        if (
            self._insert_button is None
            or self._create_button is None
            or self._delete_button is None
        ):
            return
        target, delete_spec = self._footer_target_and_delete_spec()
        # Insert / Create need a target to operate on (root or single
        # selection). With no target (pre-adapter state) the footer
        # reads as inert.
        has_target = target is not None
        self._insert_button.enabled = has_target
        self._create_button.enabled = has_target
        if self._insert_label is not None:
            self._insert_label.name = "enabled" if has_target else "disabled"
        if self._create_label is not None:
            self._create_label.name = "enabled" if has_target else "disabled"
        # Delete is stricter — only enabled when a non-root sublayer
        # is the lone selection and we resolved its slot in the
        # parent's sublayer list. ``delete_spec is None`` covers "no
        # selection", "root selected", and "stale selection whose
        # parent is gone" in one check.
        can_delete = delete_spec is not None
        self._delete_button.enabled = can_delete
        if self._delete_label is not None:
            self._delete_label.name = "enabled" if can_delete else "disabled"

    def _on_footer_insert_clicked(self) -> None:
        """Insert an existing sublayer under the footer target (Step 54).

        Opens the shared Step-36 file picker and, on confirm, pushes
        an :class:`InsertSublayerCommand` onto the undo manager —
        mirrors the context-menu "Insert Sublayer…" flow verbatim so
        users get one consistent behaviour regardless of entry point.
        No-op when the model, app, or adapter is unavailable (headless
        test / pre-open window paths).
        """
        target, _delete_spec = self._footer_target_and_delete_spec()
        if target is None or self._model is None:
            return
        services = self._services
        adapter = self._model._adapter
        if services is None or adapter is None:
            return
        parent_id = target.identifier
        # Lazy import mirrors the context-menu handlers — keeps pure
        # predicate / button-construction tests ovui-free.
        from ovwidgets.common.file_dialogs import save_file_dialog

        def _on_selected(chosen_path: str) -> None:
            cmd = InsertSublayerCommand(
                adapter,
                services.selection_bus,
                parent_id,
                -1,
                chosen_path,
            )
            services.undo_manager.push(cmd)

        save_file_dialog(
            title=f"Insert Sublayer into '{parent_id}'",
            default_name="",
            on_selected=_on_selected,
        )

    def _on_footer_create_clicked(self) -> None:
        """Create a new anonymous sublayer under the footer target (Step 54).

        Pushes a :class:`CreateSublayerCommand` with an empty
        ``new_layer_path`` so the adapter mints a fresh anonymous
        layer — no file picker involved, same path the "New Anonymous
        Sublayer" context-menu entry uses. No-op when the model, app,
        or adapter is unavailable.
        """
        target, _delete_spec = self._footer_target_and_delete_spec()
        if target is None or self._model is None:
            return
        services = self._services
        adapter = self._model._adapter
        if services is None or adapter is None:
            return
        cmd = CreateSublayerCommand(
            adapter,
            services.selection_bus,
            target.identifier,
            -1,
            "",
            transfer_root_content=False,
        )
        services.undo_manager.push(cmd)

    def _on_footer_delete_clicked(self) -> None:
        """Remove the selected sublayer via the dirty-safe model helper.

        Routes through :meth:`LayerModel._request_remove_sublayer`,
        which handles the dirty-layer confirmation dialog (Step 37)
        and pushes a :class:`RemoveSublayerCommand` onto the undo
        stack. Identical path to the context-menu "Remove" entry so
        the two gestures share a single code surface — no divergent
        edge cases to audit.
        """
        _target, delete_spec = self._footer_target_and_delete_spec()
        if delete_spec is None or self._model is None:
            return
        parent_id, position = delete_spec
        self._model._request_remove_sublayer(parent_id, position)

    def _on_save_all_clicked(self) -> None:
        """Click handler for the Save-All toolbar button (Step 35).

        Routes through :meth:`LayerModel._request_save_all`, which
        groups every dirty layer's :class:`SaveLayerCommand` under a
        single ``"Save All"`` undo group. Because each command is
        ``non_undoable``, the group ends empty and
        :meth:`UndoManager.end_group` auto-discards it — the save-all
        click runs the saves but never appears in the user's undo
        history, matching the per-row save contract from Step 34.

        No-op when the model is missing (pre-open / post-destroy)
        or when there is nothing to save — the value-model guard
        short-circuits internally, so the button should be disabled
        in that case anyway.
        """
        if self._model is None:
            return
        self._model._request_save_all()

    def set_adapter(self, adapter: Optional[LayerStackAdapter]) -> None:
        """Replace the backing :class:`LayerStackAdapter` (Step 15).

        Called by :class:`ovwidgets.app.application.Application` after a stage
        is opened or closed. If the model already exists it is re-
        targeted in place via :meth:`LayerModel.set_adapter` so the tree
        identity is preserved; otherwise the first non-``None`` adapter
        constructs the model so a later frame build can render the tree
        immediately. Triggers a frame rebuild when the window is visible
        so the next painted body reflects the new tree — invisible
        windows rebuild on the ``visible = True`` transition.
        """
        self._adapter = adapter
        if self._model is not None:
            self._model.set_adapter(adapter)
        elif adapter is not None:
            self._model = LayerModel(
                adapter, services=self._services, settings=self._settings
            )
        # Step 38 — keep the context-menu builder in lockstep with
        # the current model so its predicates read fresh state
        # without waiting for a window rebuild.
        self._ensure_context_menu_builder()
        if self._window is not None and self._window.visible:
            self._window.frame.rebuild()

    def refresh_layer_contents(self) -> None:
        """Refresh layer prim-spec rows after a stage hierarchy resync."""
        if self._model is None:
            return
        self._model.refresh_layer_contents()
        if self._window is not None and self._window.visible:
            self._window.frame.rebuild()

    # ── Step 38 context-menu wiring ───────────────────────────────

    def _ensure_context_menu_builder(self) -> None:
        """Create or re-target the :class:`ContextMenuBuilder`.

        Step 38 holds a single builder across adapter swaps so the
        registered entries (Steps 39-42 append to them) survive a
        stage open / close round-trip. When the model changes the
        builder's ``_model`` reference is updated in place so the
        predicates read the current tree state.
        """
        if self._model is None:
            return
        if self._context_menu_builder is None:
            self._context_menu_builder = ContextMenuBuilder(
                model=self._model, services=self._services
            )
        else:
            # Re-target on adapter swap — the registered entry list
            # stays put, but every predicate must read through the
            # current model's state.
            self._context_menu_builder._model = self._model

    def _build_menu_context(
        self, item: Optional[LayerItem]
    ) -> MenuContext:
        """Snapshot the right-click context for predicate evaluation.

        Captures a defensive copy of
        :attr:`LayerModel.selected_items` so a selection-change
        mid-menu (e.g. an external subscriber clearing selection in
        response to the click) can't mutate the list a predicate is
        iterating. A ``None`` model falls back to an empty context —
        callers should gate on ``_model is not None`` before reaching
        this method, but the guard keeps a late callback safe.
        """
        model = self._model
        if model is None:
            raise RuntimeError(
                "LayerWindow._build_menu_context called before the model exists"
            )
        # Step 50 widened ``selected_items`` to include ``PrimSpecItem``;
        # the context-menu predicates were written against ``LayerItem``
        # only (layer-specific actions like Mute / Lock / Save), so strip
        # prim-spec rows here before they reach the predicate list.
        return MenuContext(
            item=item,
            tree_selection=[
                i for i in model.selected_items if isinstance(i, LayerItem)
            ],
            model=model,
            services=self._services,
        )

    def _on_row_right_click(
        self, item: LayerItem, x: float, y: float
    ) -> None:
        """Delegate → builder bridge for per-row right-clicks.

        Wired onto :attr:`LayerDelegate.on_right_click` in
        :meth:`_build_ui`. Builds a fresh :class:`MenuContext` tied
        to the clicked row and asks the builder to show the menu at
        the cursor position. No-ops on a pre-build / destroyed
        state.
        """
        if self._context_menu_builder is None or self._model is None:
            return
        ctx = self._build_menu_context(item)
        self._context_menu_builder.show_at(x, y, ctx)

    def _on_empty_area_pressed(
        self, x: float, y: float, btn: int, mod: int
    ) -> None:
        """Handle right-clicks on the empty scroll area below the tree.

        Fires when the user right-clicks in the TreeView's padding
        (below the last row). Builds an empty-area
        :class:`MenuContext` (``item=None``) and shows the reduced
        menu. Left-clicks (``btn == 0``) are ignored — we don't want
        the empty area to consume the user's tree-deselection click.
        """
        if btn != 1:
            return
        if self._context_menu_builder is None or self._model is None:
            return
        ctx = self._build_menu_context(item=None)
        self._context_menu_builder.show_at(x, y, ctx)

    # ── Step 45 empty-area external file drop ───────────────────────

    @staticmethod
    def _extract_drop_payload(payload: Any) -> Any:
        """Normalise ovui's drop callback payload to a path string / list.

        ovui passes either the mime string directly or an event-like
        object with a ``.mime_data`` attribute, depending on the host.
        The model's ``_extract_file_paths`` helper expects the
        payload in its final ``str`` / ``list`` form, so centralise the
        unwrap here rather than duplicating it in both callbacks.
        """
        if hasattr(payload, "mime_data"):
            return payload.mime_data
        return payload

    def _on_empty_area_accept_drop(self, payload: Any) -> bool:
        """Accept predicate for the empty-area drop rectangle.

        Returns ``True`` when the dragged payload names at least one
        ``.usd`` / ``.usda`` / ``.usdc`` file so ovui paints the
        "ready" hover cue. Falls back to the "unsupported" rejection
        when the model is detached — the callback fires before
        ``_build_ui`` has wired a live adapter on a cold start.
        """
        if self._model is None:
            return False
        raw = self._extract_drop_payload(payload)
        from ovwidgets.layers.layer_model import (
            _extract_file_paths,
            _is_valid_usd_path,
        )
        paths = _extract_file_paths(raw)
        if not paths:
            return False
        return all(_is_valid_usd_path(p) for p in paths)

    def _on_empty_area_dropped(self, payload: Any) -> None:
        """Route an empty-area file drop into the model (Step 45).

        The TreeView consumes row / between-row drops via the model
        directly; drops onto the scroll padding below the last row
        fall through to this rectangle. Forward the payload to the
        model's :meth:`LayerModel.request_insert_file_sublayers_at_root`
        so a dropped ``.usda`` becomes a sublayer of the root layer.
        No-op when the model has been torn down.
        """
        if self._model is None:
            return
        raw = self._extract_drop_payload(payload)
        self._model.request_insert_file_sublayers_at_root(raw)

    def _on_tree_selection_changed(self, items: List[Any]) -> None:
        """Route ``ui.TreeView`` selection into the model (Step 16 / Step 50).

        Invoked by :class:`LayerSelectionWatch` as its ``on_change``
        hook on every selection change. The model accepts both
        :class:`LayerItem` and :class:`PrimSpecItem` since Phase J
        mixes prim-spec rows into the same tree — the Del hotkey
        (Step 50) reads prim-spec entries out of ``selected_items``.

        Step 54 — refresh the footer buttons after the model swallows
        the new selection so the Insert / Create / Delete enabled
        flags track the user's intent on every click.

        Step 62 — collapse the selection down to a single
        :class:`LayerItem` and mark it as the keyboard-focus target.
        A multi-select (Ctrl+click) clears every focus flag because
        there is no single "next arrow target" in that state; a
        selection that includes only prim-spec rows is treated the
        same way (focus ring is layer-scoped in v1).
        """
        if self._model is None:
            return
        self._model.set_selected_items(list(items))
        self._update_focused_item()
        self._refresh_footer_state()

    def _update_focused_item(self) -> None:
        """Synchronise :attr:`LayerItem.is_focused` with the current selection.

        Clears the flag on every layer row in the tree (cheap — the
        model caches the top-level layer list and the recursive walk
        re-uses :attr:`LayerItem.sublayers`) and sets it on the single
        currently-selected :class:`LayerItem` when the selection
        contains exactly one layer. Tree-model Step 62 runtime: O(N)
        in the total layer count per selection change, which is
        negligible compared to the existing per-event
        ``_item_changed`` fan-out.
        """
        if self._model is None:
            return
        layer_selection = [
            i for i in self._model.selected_items if isinstance(i, LayerItem)
        ]
        target = layer_selection[0] if len(layer_selection) == 1 else None
        # Walk every loaded LayerItem. ``root_item`` can be ``None`` on
        # a fresh model before :meth:`_load_sublayers` runs; the helper
        # handles that by early-returning.
        root = self._model.root_item
        if root is None:
            return

        def _walk(node: LayerItem) -> None:
            node.is_focused = node is target
            for child in node._sublayers:
                _walk(child)

        _walk(root)
        session = self._model.session_item
        if session is not None:
            _walk(session)

    def get_selected_items(self) -> List[Any]:
        """Return the current tree selection (Step 50).

        Exposes :attr:`LayerModel.selected_items` to the application-
        level keyboard dispatcher so the Del hotkey can filter the
        selection for :class:`PrimSpecItem` entries without reaching
        into the model from :class:`~ovwidgets.app.application.Application`.
        Empty list when no model is bound (window built before
        ``set_adapter``).
        """
        if self._model is None:
            return []
        return self._model.selected_items

    def destroy(self) -> None:
        """Destroy the window and release every adapter resource."""
        # Step 51 — cancel any in-flight debounce timer so a
        # ``call_later`` callback doesn't fire into a nulled model
        # after the window goes away.
        if self._pending_filter_handle is not None:
            self._pending_filter_handle.cancel()
            self._pending_filter_handle = None
        self._filter_field = None
        self._filter_icon = None
        self._filter_clear_button = None
        self._filter_placeholder = None
        self._filter_rect = None
        self._filter_border_rect = None
        self._empty_state_container = None
        self._empty_state_label = None
        # Cancel the Save-All subscription before the model is
        # destroyed — otherwise the torn-down SaveAllValueModel's
        # ``_value_changed`` would still reach a live callback that
        # dereferences a nulled ``_save_all_button``.
        if self._save_all_sub is not None:
            # ovui's Subscription exposes ``unsubscribe`` (not the
            # ``cancel`` used by ovwidgets.common.settings.Subscription). Call
            # it explicitly so the model's callback list releases
            # the bound method before the widget it paints into is
            # collected.
            self._save_all_sub.unsubscribe()
            self._save_all_sub = None
        self._save_all_button = None
        self._save_all_label = None
        self._save_all_badge = None
        # Step 54 — drop the footer-button handles alongside the
        # toolbar widgets so a late callback can't reach into them
        # after the frame is gone. The buttons are owned by the same
        # frame the rest of the body paints into, so nulling the
        # references is enough — no subscription to cancel.
        self._insert_button = None
        self._insert_label = None
        self._create_button = None
        self._create_label = None
        self._delete_button = None
        self._delete_label = None
        # Step 53 — release the options-button menu handle before
        # the settings wrapper (and the backing Settings store)
        # falls out of scope. Drops the button itself afterwards so
        # the widget / dropdown lifetime both end with the window.
        if self._options_button is not None:
            self._options_button.destroy()
            self._options_button = None
        # Step 38 — drop the builder's pinned menu reference before
        # the model graph disappears so ovui can reclaim the popup.
        if self._context_menu_builder is not None:
            self._context_menu_builder.destroy()
            self._context_menu_builder = None
        # Step 55 — release the selection watch before the tree view
        # and model go away so its ``on_change`` hook can't fire
        # into a nulled window during teardown.
        if self._selection_watch is not None:
            self._selection_watch.destroy()
            self._selection_watch = None
        if self._model is not None:
            self._model.destroy()
            self._model = None
        self._tree_view = None
        self._tree_scrolling_frame = None
        self._delegate = None
        super().destroy()


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovwidgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_LAYERS_FILTER_ICON_CACHE)
