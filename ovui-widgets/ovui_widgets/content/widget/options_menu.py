# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""OptionsButton — gear-icon toolbar button + options dropdown.

Step 56 (the content browser implementation step L, the content browser behavior). A
compact toolbar button whose click pops a :class:`ui.Menu` surfacing
the user-facing browser preferences:

* **Show hidden files** — checkable. Mirrors
  :meth:`FileBrowserModel.set_show_hidden`.
* **Show detail pane** — checkable. Toggles the right-side detail /
  preview column (wired in Step 56 alongside the splitter preservation
  already wired by Step 42 / 13's layout).
* **Sort by: Name / Date / Size** — three mutually-exclusive items
  feeding :meth:`FileBrowserModel.set_sort_policy`. Kit surfaces
  ascending-only in this dropdown; the column header click remains
  the route for flipping the direction (:class:`FileBrowserDelegate`).

Construction mirrors :class:`FilterButton` (Step 26) — the button is a
28×28 :class:`ui.ZStack` with a :class:`ui.RasterImageProvider`-backed
overlay; the dropdown is built once inside a hidden zero-size
:class:`ui.Frame` and reshown via :meth:`ui.Menu.show_at` on each click
so check-state survives across opens.

The widget itself is stateless about persistence — the caller passes
initial values and receives callbacks for each change. Step 57's
settings wiring lives in :class:`FileBrowserWidget`, which owns the
:class:`Settings` handle.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

import omni.ui as ui

from ovui_widgets.common.menu import create_flat_menu
from ovui_widgets.common.style.urls import get_icon_path
from ovui_widgets.content.widget.file_browser_model import (
    FileBrowserSortPolicy,
)

# Human-readable labels for the three sort policies surfaced in the
# dropdown. Ascending-only by design — descending flips land on the
# column header (:class:`FileBrowserDelegate`). Plain dict so the ordering
# in the menu follows insertion order (Python 3.7+).
_SORT_LABELS: Dict[str, str] = {
    FileBrowserSortPolicy.NAME_ASC: "Name",
    FileBrowserSortPolicy.DATE_ASC: "Date",
    FileBrowserSortPolicy.SIZE_ASC: "Size",
}


# Gear-icon path resolved once at import time — same lookup pattern as
# :mod:`browser_bar` / :mod:`filter_button` / :mod:`zoom_bar`.
_GEAR_ICON_PATH = get_icon_path("content_gear")


# Cached providers keyed by absolute path — single gear-icon asset per
# process, shared across tab-switch rebuilds. Mirrors
# :mod:`filter_button._PROVIDER_CACHE`.
_PROVIDER_CACHE: Dict[str, "ui.RasterImageProvider"] = {}


def _provider(path: str) -> "ui.RasterImageProvider":
    """Return a cached :class:`ui.RasterImageProvider` for ``path``."""
    prov = _PROVIDER_CACHE.get(path)
    if prov is None:
        prov = ui.RasterImageProvider(path)
        _PROVIDER_CACHE[path] = prov
    return prov


# Button + icon sizing. 28×28 matches :class:`FilterButton` and the
# :class:`BrowserBar` nav buttons so the whole toolbar row reads as a
# single strip. Icon is 16 px leaving ~6 px of padding around the glyph.
_BUTTON_WIDTH = 28
_BUTTON_HEIGHT = 28
_BUTTON_ICON_SIZE = 16


class OptionsButton:
    """Gear toolbar button + dropdown of browser preferences.

    Constructor takes the initial state for each option and three
    callback hooks. Every menu toggle fires the corresponding callback
    with the new value (a ``bool`` for the two checkboxes, the matching
    :class:`FileBrowserSortPolicy` constant for the sort radio). The
    widget is a pure view — it does not reach into a model or the
    :class:`Settings` store. Step 57's :class:`FileBrowserWidget` owns
    the persistence.

    Construction builds the button immediately into the surrounding
    ``with`` build block — same contract as :class:`FilterButton`. The
    dropdown :class:`ui.Menu` is built inside a hidden zero-size
    :class:`ui.Frame` so its inline-layout stub stays off-screen.
    """

    def __init__(
        self,
        show_hidden: bool = False,
        show_detail_pane: bool = True,
        sort_policy: str = FileBrowserSortPolicy.NAME_ASC,
        on_show_hidden_changed: Optional[Callable[[bool], None]] = None,
        on_show_detail_pane_changed: Optional[
            Callable[[bool], None]
        ] = None,
        on_sort_policy_changed: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._show_hidden: bool = bool(show_hidden)
        self._show_detail_pane: bool = bool(show_detail_pane)
        # Snap an unknown policy back to NAME_ASC so the radio group
        # always has exactly one item checked. The three items only
        # cover ASC; a Settings round-trip from an earlier session
        # that somehow stored NAME_DESC would otherwise land here.
        self._sort_policy: str = (
            sort_policy
            if sort_policy in _SORT_LABELS
            else FileBrowserSortPolicy.NAME_ASC
        )
        self._on_show_hidden_changed: Optional[
            Callable[[bool], None]
        ] = on_show_hidden_changed
        self._on_show_detail_pane_changed: Optional[
            Callable[[bool], None]
        ] = on_show_detail_pane_changed
        self._on_sort_policy_changed: Optional[
            Callable[[str], None]
        ] = on_sort_policy_changed

        # Widget refs — populated by :meth:`build`, cleared by
        # :meth:`destroy`. ``None`` pre-build / post-destroy so
        # callbacks guard defensively against teardown races.
        self._zstack: Optional[ui.ZStack] = None
        self._button: Optional[ui.Button] = None
        self._icon_image: Optional[ui.ImageWithProvider] = None
        self._menu_host: Optional[ui.Frame] = None
        self._menu: Optional[ui.Menu] = None

        self._show_hidden_item: Optional[ui.MenuItem] = None
        self._show_detail_pane_item: Optional[ui.MenuItem] = None
        self._sort_items: Dict[str, ui.MenuItem] = {}

        self.build()

    # ── Build ────────────────────────────────────────────────────────────

    def build(self) -> None:
        """Build the button into the current context; pre-build the menu."""
        self._zstack = ui.ZStack(
            width=_BUTTON_WIDTH,
            height=_BUTTON_HEIGHT,
        )
        with self._zstack:
            # V1 parks the gear dropdown alongside the filter /
            # bookmark buttons — the three read as a unit, and the
            # filter surface is not ready for users (see
            # :mod:`filter_button` build docstring). Ship the gear
            # disabled for visual consistency with its neighbors so
            # the row reads as a single deferred affordance rather
            # than a mixed working / non-working cluster. The
            # ``:disabled`` styles already wired in the content-
            # browser theme gray the icon and strip the hover tint.
            self._button = ui.Button(
                "",
                clicked_fn=self._on_button_clicked,
                style_type_name_override="Content.ToolBar.Button",
                enabled=False,
                tooltip="Options — not yet implemented",
            )
            with ui.VStack():
                ui.Spacer()
                with ui.HStack(height=_BUTTON_ICON_SIZE):
                    ui.Spacer()
                    self._icon_image = ui.ImageWithProvider(
                        _provider(_GEAR_ICON_PATH),
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
        """Build the dropdown :class:`ui.Menu`.

        Mirrors :meth:`FilterButton._build_menu`: a hidden zero-size
        :class:`ui.Frame` parents the menu so the inline-layout stub
        stays off-screen, and each item uses ``hide_on_click=False``
        so the popup survives multi-toggle visits.
        """
        self._menu_host = ui.Frame(
            visible=False,
            width=ui.Pixel(0),
            height=ui.Pixel(0),
        )
        with self._menu_host:
            self._menu = create_flat_menu(ui_module=ui)
            with self._menu:
                self._show_hidden_item = ui.MenuItem(
                    "Show hidden files",
                    checkable=True,
                    checked=self._show_hidden,
                    hide_on_click=False,
                )
                self._show_hidden_item.set_checked_changed_fn(
                    self._on_show_hidden_toggled,
                )
                self._show_detail_pane_item = ui.MenuItem(
                    "Show detail pane",
                    checkable=True,
                    checked=self._show_detail_pane,
                    hide_on_click=False,
                )
                self._show_detail_pane_item.set_checked_changed_fn(
                    self._on_show_detail_pane_toggled,
                )
                ui.Separator()
                # Sort-by radio group. ``ui.Menu`` has no first-class
                # radio affordance so the mutual exclusion is enforced
                # in :meth:`_on_sort_item_toggled`: a click that lands
                # on a checked item re-checks it (reverting the toggle);
                # a click on an unchecked one unchecks the previously
                # active one and fires the policy-change callback.
                ui.MenuItem("Sort by", enabled=False)
                for policy, label in _SORT_LABELS.items():
                    item = ui.MenuItem(
                        "    " + label,
                        checkable=True,
                        checked=(policy == self._sort_policy),
                        hide_on_click=False,
                    )
                    item.set_checked_changed_fn(
                        lambda checked, p=policy: (
                            self._on_sort_item_toggled(p, checked)
                        )
                    )
                    self._sort_items[policy] = item

    # ── Handlers ─────────────────────────────────────────────────────────

    def _on_button_clicked(self) -> None:
        """Pop the dropdown at the button's screen position."""
        if self._button is None or self._menu is None:
            return
        x = float(self._button.screen_position_x)
        y = float(
            self._button.screen_position_y + self._button.computed_height
        )
        self._menu.show_at(x, y)

    def _on_show_hidden_toggled(self, checked: bool) -> None:
        """Update state + fan out to the caller's callback."""
        if bool(checked) == self._show_hidden:
            return
        self._show_hidden = bool(checked)
        if self._on_show_hidden_changed is not None:
            self._on_show_hidden_changed(self._show_hidden)

    def _on_show_detail_pane_toggled(self, checked: bool) -> None:
        """Update state + fan out to the caller's callback."""
        if bool(checked) == self._show_detail_pane:
            return
        self._show_detail_pane = bool(checked)
        if self._on_show_detail_pane_changed is not None:
            self._on_show_detail_pane_changed(self._show_detail_pane)

    def _on_sort_item_toggled(self, policy: str, checked: bool) -> None:
        """Enforce single-select across the three sort items.

        The menu items are independent :class:`ui.MenuItem` checkables,
        so we emulate a radio group here: clicking an already-checked
        item re-checks it (no-op); clicking an unchecked one unchecks
        the previously-checked one and emits the new policy.
        """
        if checked:
            if policy == self._sort_policy:
                return
            old_item = self._sort_items.get(self._sort_policy)
            if old_item is not None:
                old_item.checked = False
            self._sort_policy = policy
            if self._on_sort_policy_changed is not None:
                self._on_sort_policy_changed(policy)
        else:
            # Unchecking the active item — re-check it so the radio
            # group always has exactly one member selected. Skipping
            # the event dispatch during the re-check avoids a
            # phantom policy-changed fire with the same value.
            if policy == self._sort_policy:
                item = self._sort_items.get(policy)
                if item is not None:
                    item.checked = True

    # ── Public API ───────────────────────────────────────────────────────

    @property
    def show_hidden(self) -> bool:
        """Current "Show hidden files" state (accessor for tests / QA)."""
        return self._show_hidden

    @property
    def show_detail_pane(self) -> bool:
        """Current "Show detail pane" state (accessor for tests / QA)."""
        return self._show_detail_pane

    @property
    def sort_policy(self) -> str:
        """Current sort-policy string (accessor for tests / QA)."""
        return self._sort_policy

    def set_show_hidden(self, value: bool) -> None:
        """Sync the menu state from external sources (e.g. Settings).

        Does not fire the callback — this is a view-sync entry point,
        not a user-initiated toggle. Guarded by an equality check so
        a no-op sync does not bounce through :meth:`ui.MenuItem.checked`
        (which would re-dispatch the internal change).
        """
        new_value = bool(value)
        if new_value == self._show_hidden:
            return
        self._show_hidden = new_value
        if self._show_hidden_item is not None:
            # Guard against the setter's own change-dispatch by
            # temporarily detaching the callback. omni.ui's MenuItem
            # has no "silent set" so we detach/re-attach the handler
            # around the assignment.
            self._show_hidden_item.set_checked_changed_fn(None)
            self._show_hidden_item.checked = new_value
            self._show_hidden_item.set_checked_changed_fn(
                self._on_show_hidden_toggled,
            )

    def set_show_detail_pane(self, value: bool) -> None:
        """Sync the detail-pane menu state from external sources."""
        new_value = bool(value)
        if new_value == self._show_detail_pane:
            return
        self._show_detail_pane = new_value
        if self._show_detail_pane_item is not None:
            self._show_detail_pane_item.set_checked_changed_fn(None)
            self._show_detail_pane_item.checked = new_value
            self._show_detail_pane_item.set_checked_changed_fn(
                self._on_show_detail_pane_toggled,
            )

    def set_sort_policy(self, policy: str) -> None:
        """Sync the sort-radio state from external sources."""
        if policy not in _SORT_LABELS:
            return
        if policy == self._sort_policy:
            return
        old_item = self._sort_items.get(self._sort_policy)
        new_item = self._sort_items.get(policy)
        self._sort_policy = policy
        if old_item is not None:
            old_item.set_checked_changed_fn(None)
            old_item.checked = False
            old_item.set_checked_changed_fn(
                lambda checked, p=self._sort_policy_of(old_item): (
                    self._on_sort_item_toggled(p, checked)
                )
            )
        if new_item is not None:
            new_item.set_checked_changed_fn(None)
            new_item.checked = True
            new_item.set_checked_changed_fn(
                lambda checked, p=policy: (
                    self._on_sort_item_toggled(p, checked)
                )
            )

    def _sort_policy_of(self, item: ui.MenuItem) -> str:
        """Reverse-lookup a menu item back to its policy key."""
        for key, candidate in self._sort_items.items():
            if candidate is item:
                return key
        return FileBrowserSortPolicy.NAME_ASC

    # ── Lifecycle ────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Release widget refs; hide and drop the dropdown menu.

        Idempotent — ``is not None`` guards short-circuit a second call.
        Order matches :class:`FilterButton.destroy`: hide the menu first
        so an in-flight popup animation completes, drop the item refs
        (releases the bound change callbacks on the C++ side), then
        null the widget refs and finally the handler refs so a late
        callback that sneaks past the guards falls through silently.
        """
        if self._menu is not None:
            self._menu.hide()
            self._menu = None
        self._show_hidden_item = None
        self._show_detail_pane_item = None
        self._sort_items = {}
        self._menu_host = None
        self._icon_image = None
        self._button = None
        self._zstack = None
        self._on_show_hidden_changed = None
        self._on_show_detail_pane_changed = None
        self._on_sort_policy_changed = None


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovui_widgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_PROVIDER_CACHE)
