# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FilterButton — funnel-icon toolbar button + asset-type filter dropdown.

Step 26 (the content browser implementation step F, the content browser behavior). A compact
toolbar button whose click pops a :class:`ui.Menu` containing one
checkable :class:`ui.MenuItem` per :class:`~ovui_widgets.common.asset_types.AssetCategory`
the caller opts into. Checking one or more items fires the caller's
``on_filter_changed`` with the active set; unchecking returns toward the
empty set which by convention means *show all* (the model layer reads
``set()`` as "no filter"). No automatic default-all-on — the menu starts
with every item unchecked so the first toggle represents a deliberate
narrowing by the user.

The :class:`ui.Menu` is built once at construction time and reshown on
every click via :meth:`ui.Menu.show_at`. Rebuilding per click would
recreate the underlying C++ popup (and its subscriptions) on every
invocation; reusing the built menu keeps the toggle state coherent
across successive opens and avoids the subscription-leak pattern that
a rebuild-per-click would require. ``hide_on_click=False`` keeps the
popup open across multi-category toggles — the menu closes on a
click-outside or an explicit :meth:`ui.Menu.hide`.

The widget holds no model reference and does not itself filter anything
— Step 28 will wire ``on_filter_changed`` to
``FileBrowserModel.set_asset_type_whitelist``. The architecture's
three-way click protocol (single/double/middle) is simplified to
single-click-opens-menu for v1; the double-click-toggles-all and
middle-click variants are deferred.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Set

import omni.ui as ui

from ovui_widgets.common.asset_types import AssetCategory
from ovui_widgets.common.menu import create_flat_menu
from ovui_widgets.common.style.urls import get_icon_path

# Short, filter-menu display names — intentionally terser than the
# :attr:`AssetTypeDef.display_name` strings in :mod:`ovui_widgets.common.asset_types`
# (e.g. "USD File" → "USD", "Python Script" → "Script") because the
# toolbar dropdown is a dense affordance where the category name is
# the primary cue. The full display names live in the catalog for
# status-bar / tooltip / type-column use where the extra words help.
_CATEGORY_DISPLAY_NAMES: Dict[AssetCategory, str] = {
    AssetCategory.FOLDER: "Folder",
    AssetCategory.USD: "USD",
    AssetCategory.IMAGE: "Image",
    AssetCategory.MATERIAL: "Material",
    AssetCategory.MODEL: "Model",
    AssetCategory.SOUND: "Audio",
    AssetCategory.SCRIPT: "Script",
    AssetCategory.VOLUME: "Volume",
    AssetCategory.TEXT: "Text",
    AssetCategory.ARCHIVE: "Archive",
    AssetCategory.UNKNOWN: "Other",
}


# Funnel-icon path resolved once at import time — same lookup pattern
# as :mod:`browser_bar` / :mod:`zoom_bar`. The ovui build here routes
# ``ui.Button(image_url=...)`` through the stb_image loader which
# drops draws on retry; the reliable path is a cached
# :class:`ui.RasterImageProvider` pointed at the absolute filesystem
# path returned by :func:`get_icon_path`.
_FILTER_ICON_PATH = get_icon_path("content_filter")


# Cached providers keyed by absolute path. Single filter-icon widget
# per FilterButton, but the cache survives widget destroy so a second
# FilterButton built during the same session (or a tab-switch rebuild)
# shares the same texture. Mirrors :mod:`browser_bar._PROVIDER_CACHE`.
_PROVIDER_CACHE: Dict[str, "ui.RasterImageProvider"] = {}


def _provider(path: str) -> "ui.RasterImageProvider":
    """Return a cached :class:`ui.RasterImageProvider` for ``path``."""
    prov = _PROVIDER_CACHE.get(path)
    if prov is None:
        prov = ui.RasterImageProvider(path)
        _PROVIDER_CACHE[path] = prov
    return prov


# Button sizing. 28x28 matches :class:`BrowserBar`'s nav buttons so the
# FilterButton reads as part of the same toolbar row when Step 28
# places them side-by-side. Icon is 16 px, leaving ~6 px of padding
# around the glyph.
_BUTTON_WIDTH = 28
_BUTTON_HEIGHT = 28
_BUTTON_ICON_SIZE = 16


class FilterButton:
    """Funnel toolbar button + dropdown menu of asset-category toggles.

    Constructor takes the list of :class:`AssetCategory` members to
    expose in the menu (caller controls which subset appears — the
    default the content browser implementation step 26 set is six: USD, Image, Material,
    Audio, Script, Volume). Each category renders as a single
    checkable :class:`ui.MenuItem`. Every toggle fires
    ``on_filter_changed`` with a fresh copy of the active set — the
    empty set means "no filter, show everything" (the
    :class:`FileBrowserModel` whitelist convention Step 28 will wire).

    Construction builds the button immediately into the surrounding
    ``with`` block — same contract as :class:`BrowserBar`, :class:`ZoomBar`,
    :class:`FileCard`. The underlying :class:`ui.Menu` is a top-level
    popup and is constructed out-of-band from the build context; it
    becomes visible only when the user clicks the button.
    """

    def __init__(
        self,
        categories: List[AssetCategory],
        on_filter_changed: Callable[[Set[AssetCategory]], None],
    ) -> None:
        # Snapshot the caller's category list so a post-construction
        # mutation of the caller's own list cannot silently reshape
        # the menu. Order-preserving — the menu items appear in the
        # same order the caller passed them.
        self._categories: List[AssetCategory] = list(categories)
        self._on_filter_changed: Optional[
            Callable[[Set[AssetCategory]], None]
        ] = on_filter_changed

        # Active filter set — the authoritative record of which
        # categories are currently toggled on. The menu items'
        # ``.checked`` attributes mirror this set; we hold the set
        # separately so a post-destroy query (``bar.active_categories``
        # after ``bar.destroy()``) still returns a sensible empty view.
        self._active: Set[AssetCategory] = set()

        # Widget refs — populated by :meth:`build`, cleared by
        # :meth:`destroy`. ``None`` pre-build / post-destroy so
        # callbacks guard defensively against teardown races. The
        # menu is a top-level popup (not a child of ``_zstack``); it
        # lives as long as this widget does.
        self._zstack: Optional[ui.ZStack] = None
        self._button: Optional[ui.Button] = None
        self._icon_image: Optional[ui.ImageWithProvider] = None
        # Hidden zero-size frame that parents :attr:`_menu` — keeps the
        # menu's inline layout stub off-screen in the Step-28 toolbar
        # composition. See :meth:`_build_menu` for the rationale.
        self._menu_host: Optional[ui.Frame] = None
        self._menu: Optional[ui.Menu] = None
        # Menu-item handles kept so tests and a future "reset filter"
        # path can iterate them. Keyed by category for O(1) lookup.
        self._menu_items: Dict[AssetCategory, ui.MenuItem] = {}

        self.build()

    # ── Build ────────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build the button into the current context; pre-build the menu.

        The :class:`ui.ZStack` wrapper matches :class:`BrowserBar`'s
        nav-button pattern — a textless :class:`ui.Button` owns the
        click area, an :class:`ui.ImageWithProvider` paints the funnel
        icon on top via a Spacer sandwich so the 16-px glyph sits
        centred inside the 28-px button.
        """
        self._zstack = ui.ZStack(
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
        )
        with self._zstack:
            # V1 ships without a working filter — the asset-category
            # whitelist is wired through the model but has no visible
            # effect on homogeneous folders (every folder passes the
            # whitelist, and a USD-only folder accepts any USD toggle),
            # so the button reads as "does nothing" to the user.
            # Disable the button and tooltip with a discoverable
            # "coming soon" so the affordance does not promise a
            # behavior the V1 surface cannot honor. The ``:disabled``
            # style variants in :mod:`ovui_widgets.content.style`
            # gray the icon and strip the hover highlight.
            self._button = ui.Button(
                "",
                clicked_fn=self._on_button_clicked,
                style_type_name_override="Content.ToolBar.Button",
                enabled=False,
                tooltip="Filter — not yet implemented",
            )
            # Icon layer — non-interactive overlay, centred inside
            # the button rectangle via a Spacer sandwich.
            with ui.VStack():
                ui.Spacer()
                with ui.HStack(height=_BUTTON_ICON_SIZE):
                    ui.Spacer()
                    self._icon_image = ui.ImageWithProvider(
                        _provider(_FILTER_ICON_PATH),
                        width=_BUTTON_ICON_SIZE,
                        height=_BUTTON_ICON_SIZE,
                        style_type_name_override=(
                            "Content.ToolBar.Button.Image"
                        ),
                    )
                    ui.Spacer()
                ui.Spacer()

        self._build_menu()

    def _build_menu(self) -> None:
        """Build the dropdown :class:`ui.Menu` with one item per category.

        The menu is built inside a hidden zero-size :class:`ui.Frame`
        anchored in the current build context. :class:`ui.Menu` has a
        non-obvious layout-tree side effect: when constructed inside a
        live build context it paints an inline menu-bar stub (either
        the menu's ``text`` title or — if the title is empty — the
        menu's children expanded vertically) next to the surrounding
        widgets. The popup invocation via :meth:`ui.Menu.show_at` is
        independent of that stub. Burying the whole construction inside
        a ``visible=False, width=0, height=0`` frame keeps the stub
        off-screen without affecting popup positioning, which reads
        from the *button*'s screen position in :meth:`_on_button_clicked`
        rather than from the menu's own layout slot.

        ``hide_on_click=False`` on each item keeps the menu open after
        a toggle so the user can flip several categories in one visit;
        a click-outside (or an explicit :meth:`hide` call) closes it.
        The close-on-click-outside is handled by :class:`ui.Menu` itself.
        """
        self._menu_host = ui.Frame(
            visible=False,
            width=ui.Pixel(0),
            height=ui.Pixel(0),
        )
        with self._menu_host:
            self._menu = create_flat_menu(ui_module=ui)
            with self._menu:
                for category in self._categories:
                    display = _CATEGORY_DISPLAY_NAMES.get(
                        category, category.name.title()
                    )
                    item = ui.MenuItem(
                        display,
                        checkable=True,
                        checked=False,
                        hide_on_click=False,
                    )
                    # Bind ``category`` at lambda-creation time — late
                    # binding in a loop would close over the last value.
                    item.set_checked_changed_fn(
                        lambda checked, cat=category: (
                            self._on_item_toggled(cat, checked)
                        )
                    )
                    self._menu_items[category] = item

    # ── Handlers ─────────────────────────────────────────────────────────────

    def _on_button_clicked(self) -> None:
        """Pop the dropdown menu at the button's screen position.

        Uses :attr:`ui.Button.screen_position_x` /
        :attr:`~ui.Button.screen_position_y` — the absolute coords
        :meth:`ui.Menu.show_at` expects. Offsets vertically by the
        button's computed height so the menu's top edge lines up
        flush with the button's bottom edge rather than occluding the
        button itself.

        None-guards on the button and menu cover the post-destroy
        teardown path where a straggling click event might reach here
        after the refs were nulled.
        """
        if self._button is None or self._menu is None:
            return
        x = float(self._button.screen_position_x)
        y = float(
            self._button.screen_position_y + self._button.computed_height
        )
        self._menu.show_at(x, y)

    def _on_item_toggled(
        self, category: AssetCategory, checked: bool
    ) -> None:
        """Update :attr:`_active` and fire the caller's callback.

        No-op short-circuit when the incoming ``checked`` state already
        matches membership in :attr:`_active` — a redundant toggle
        (e.g. a spurious change-event after a state-restore) would
        otherwise emit an unchanged set downstream and wake
        :meth:`FileBrowserModel.set_asset_type_whitelist` for nothing.
        The callback receives a fresh copy of the set so the caller
        cannot mutate the widget's internal record.
        """
        was_active = category in self._active
        if checked == was_active:
            return
        if checked:
            self._active.add(category)
        else:
            self._active.discard(category)
        if self._on_filter_changed is not None:
            self._on_filter_changed(set(self._active))

    # ── Public API ───────────────────────────────────────────────────────────

    @property
    def active_categories(self) -> Set[AssetCategory]:
        """Return a fresh copy of the currently-active category set.

        Empty set == "no filter" per the :class:`FileBrowserModel`
        whitelist convention Step 28 will wire. The returned set is a
        copy so external mutation does not affect the widget's own
        state.
        """
        return set(self._active)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Release widget refs; hide and drop the dropdown menu.

        Idempotent — the ``is not None`` guards short-circuit a
        second call. Order matters: hide the menu first so any
        in-flight popup animation completes, then drop the menu-item
        subscriptions (dropping the item refs releases the
        :meth:`ui.MenuItem.set_checked_changed_fn` bound callbacks on
        the C++ side — same idiom :mod:`zoom_bar` uses for its
        slider subscription), then null the widget refs, then finally
        drop the handler reference so a late callback that sneaks
        through the guards above falls through silently.
        """
        if self._menu is not None:
            self._menu.hide()
            self._menu = None
        self._menu_items = {}
        # Drop the host frame ref AFTER the menu ref so the C++ side
        # tears down the menu while its parent frame is still live —
        # inverted order would strand the menu as a detached child of
        # the already-released frame.
        self._menu_host = None
        self._icon_image = None
        self._button = None
        self._zstack = None
        self._on_filter_changed = None


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovui_widgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_PROVIDER_CACHE)
