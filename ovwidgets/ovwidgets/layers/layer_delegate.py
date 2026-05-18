# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Cell delegate for the Layers ``ui.TreeView`` (LAYERS-PLAN Step 17-22).

:class:`LayerDelegate` is a lifecycle skeleton — it owns per-row cell
construction and, step by step, graduates each column from the blank
placeholder to a real widget. As of Step 22 columns 0 (name), 2 (save /
dirty indicator), 3 (local-mute eye), and 6 (lock padlock) paint real
widgets; columns 1 (Live), 4 (Global Mute), and 5 (Latest) paint
disabled-tint placeholder shapes so the seven-column strip reads as
intentional until Steps 42-44 graduate each to a real value model.

Step 18 swapped the Step-17 ``ui.SimpleStringModel``-backed label for a
:class:`~ovwidgets.layers.models.layer_name_model.LayerNameValueModel` —
the label text includes the state suffix
(``(Authoring Layer)`` / ``(Missing)`` / ``(Anonymous)`` /
``(Read Only)``) and the label's color follows the model's color role
via ``name=<role>`` on ``Layers.NameLabel``.

Step 19 paints column 2 through
:class:`~ovwidgets.layers.models.save_model.SaveValueModel`: a small dot
indicator appears when the layer is dirty *and* saveable (anonymous /
missing layers clamp to clean so the icon never promises a save it
can't deliver). Clicking the indicator calls
:meth:`SaveValueModel.set_value`, which forwards to
:meth:`~ovwidgets.common.adapters.LayerStackAdapter.save_layer`. Phase F
wraps the adapter call in a ``SaveLayerCommand`` for undo support.

Step 20 paints column 3 through
:class:`~ovwidgets.layers.models.mute_model.LocalMuteValueModel`: a filled
eye (ui.Circle, ``name=open``) for unmuted layers and a dimmed
horizontal slit (ui.Rectangle, ``name=muted``) for locally muted ones.
A left-click toggles the bit via
:meth:`LocalMuteValueModel.set_value` → ``adapter.set_mute``; Phase F
replaces the direct adapter call with ``SetLayerMutenessCommand``.

Step 21 paints column 6 through
:class:`~ovwidgets.layers.models.lock_model.LockValueModel`: a small
padlock icon built from two :class:`ui.Rectangle` primitives. When the
layer is locked both the shackle (arch) and body render in the
primary-text tint (``Layers.LockIcon::locked``) — a fully drawn
padlock. When unlocked only the body renders, dimmed to the disabled-
label tint (``Layers.LockIcon::unlocked``), so the row reads as an
open-lock base. A left-click toggles the bit via
:meth:`LockValueModel.set_value` → ``adapter.set_lock``; Phase F
replaces the direct adapter call with ``SetLayerLockCommand``.

Step 22 fills columns 1, 4, 5 with non-interactive placeholder
glyphs so the seven-column layout reads as intentional while the
real Live / Global Mute / Latest backends wait for v2. Every
placeholder paints in the ``Layers.PlaceholderIcon::disabled`` tint
(shared with ``NameLabel::disabled``) and carries a "coming in v2"
tooltip so a hover explains the greyed state. Column 5 is extra
conditional: the reload-style placeholder only renders for rows
whose layer is :attr:`LayerItem.is_missing` — mirroring Kit's
"this file doesn't exist" signal. None of the three attach a
``set_mouse_pressed_fn``; click-through lands on the underlying
TreeView row instead, matching the selection hit target.

Step 23 graduates the `build_branch` skeleton off the
``ui.AbstractItemDelegate`` default. The branch column is now wrapped
in a :class:`ui.ZStack` whose back layer is a
``Layers.TreeView.Row::row_bg`` :class:`ui.Rectangle`. ovui propagates
the TreeView item's ``:hovered`` / ``:selected`` pseudo-states down to
the Rectangle, so hovering or selecting a row paints the
``layers_row_hover`` / ``treeview_selection`` tint across the branch
cell — and because ovui draws ``build_branch`` behind the widget cells,
the strip reads as a full-row highlight rather than a column-only
block. The indent guide + expand chevron sit on top of the Rectangle
inside the ZStack's front layer. Step 25 forks a sibling
``::row_bg_edit_target`` name for the green edit-target overlay without
touching the hover / selected vocabulary (LAYERS-WINDOW-ARCHITECTURE
§20.1 "selection Rectangle around the branch").

Step 27 polishes the three less-common state flags:

- **Missing** rows paint a small red ``Layers.MissingBadge`` glyph in
  the name column between the leading icon and the label. The label
  itself already tints red from Step 18's ``NameLabel::missing`` role
  — the badge gives a second, spatial cue so a quick scan of the
  column strip surfaces unresolved rows without reading every label.
- **Read-only on disk** rows paint a non-interactive
  ``Layers.LockIcon::readonly_overlay`` Rectangle *behind* the col-6
  lock button. The overlay uses a dim tint so it reads as a backdrop
  hint rather than a second toggle: the clickable lock glyph stays on
  top and the overlay signals "this file is not writable on disk"
  regardless of whether the user has also toggled the lock bit.
- **Anonymous** rows render the Step-27 ``[anon]`` suffix (emitted by
  :class:`LayerNameValueModel`) and pick up the
  ``Layers.NameLabel::anonymous`` softened tint via the color role.
"""

from __future__ import annotations

import importlib.resources
from typing import Any, Callable, Optional

import omni.ui as ui
from ovui_data_adapters.common import PrimSpecifier

from ovwidgets.layers.drop_visual_controller import (
    INDICATOR_DROP_ABOVE,
    INDICATOR_DROP_REJECTED,
    INDICATOR_DROP_TARGET,
    INDICATOR_NONE,
)
from ovwidgets.layers.layer_icons import (
    composition_badge,
    instance_badge,
    provider,
    specifier_icon,
)
from ovwidgets.layers.layer_item import LayerItem
from ovwidgets.layers.models.layer_name_model import LayerNameValueModel
from ovwidgets.layers.models.lock_model import LockValueModel
from ovwidgets.layers.models.mute_model import LocalMuteValueModel
from ovwidgets.layers.models.save_model import SaveValueModel
from ovwidgets.layers.prim_spec_item import PrimSpecItem

# Branch chevron PNGs. Mirror ``ovwidgets.stage/widget/stage_delegate.py``
# one-for-one — same files, same on-disk path — so the Stage and Layers
# tree branch arrows render identically. ``ovwidgets/common/icons/`` ships
# ``chevron_right.png`` / ``chevron_down.png`` (32×32 PNG, 3-px-wide
# pure-white stroke) added by commit ``47fcd01`` (the design overhaul
# that replaced ``ui.Triangle`` chevrons across the rest of the app).
_ICON_DIR = str(importlib.resources.files("ovwidgets.common").joinpath("icons"))
_CHEVRON_RIGHT = f"{_ICON_DIR}/chevron_right.png"
_CHEVRON_DOWN = f"{_ICON_DIR}/chevron_down.png"

# Cache providers so the PNG decode happens once per process per glyph
# rather than every frame. Same pattern as
# ``ovwidgets.stage/widget/stage_icons.py::provider``.
_CHEVRON_PROVIDER_CACHE: dict[str, "ui.RasterImageProvider"] = {}


def _chevron_provider(path: str) -> "ui.RasterImageProvider":
    prov = _CHEVRON_PROVIDER_CACHE.get(path)
    if prov is None:
        prov = ui.RasterImageProvider(path)
        _CHEVRON_PROVIDER_CACHE[path] = prov
    return prov


# Step 38: callback signature the delegate invokes on a right-click
# over any non-interactive row area (name column, placeholder icon
# columns). The :class:`LayerWindow` installs a handler that builds a
# :class:`ovwidgets.layers.context_menu.MenuContext` and shows the menu via
# :meth:`ContextMenuBuilder.show_at`. Arguments: the right-clicked
# :class:`LayerItem`, the screen-space ``(x, y)``. Kept as a plain
# callable typedef so the delegate has no import on the context-menu
# module — the window is the single wiring seam.
RightClickCallback = Callable[[LayerItem, float, float], None]


class LayerDelegate(ui.AbstractItemDelegate):
    """Per-cell renderer for the seven-column Layers tree.

    Stateless in Step 17 — no icons cached, no context menu wired.
    Steps 18+ thread per-column build callables through the same
    dispatch so future work remains additive rather than a rewrite.

    Step 38 adds a single wiring seam: :attr:`on_right_click` (set by
    :class:`LayerWindow` at build time) is fired from the per-row
    mouse-pressed handler attached to each row's outer ``ZStack``
    when the user right-clicks anywhere in the row that is not an
    interactive control. The save / mute / lock columns continue to
    consume button 1 for their own gestures (save-as on the save dot),
    so right-clicking those cells does NOT open the context menu — by
    design. Every other cell bubbles the right-click through to the
    callback.
    """

    # Step 38 right-click hook. ``LayerWindow`` assigns a callback
    # during its build pass; left as ``None`` in bare-delegate unit
    # tests so the dispatch path can be exercised without a live
    # context-menu builder. The attribute is read on every
    # ``build_widget`` call, so swapping it at runtime (a test that
    # wants to assert the callback fires) takes effect on the next
    # paint without a frame rebuild.
    on_right_click: Optional[RightClickCallback] = None

    # Column IDs — kept symbolic so the cell dispatch reads as intent.
    # Mirrors LAYERS-WINDOW-ARCHITECTURE §20.5 one-to-one.
    COL_NAME = 0
    COL_LIVE = 1
    COL_SAVE = 2
    COL_LOCAL_MUTE = 3
    COL_GLOBAL_MUTE = 4
    COL_LATEST = 5
    COL_LOCK = 6

    # Branch rendering constants. ``_INDENT_PER_LEVEL`` matches Stage's
    # ``stage_delegate.py:29`` so the indent rhythm reads identically
    # when the two trees are docked together. ``_CHEVRON_SIZE`` matches
    # Stage's ``_CHEVRON_SIZE = 12`` so the chevron PNG renders at the
    # same size in both panels.
    _INDENT_PER_LEVEL = 14
    _CHEVRON_SIZE = 12

    # Leading icon (Step 25) — three stacked horizontal bars drawn with
    # primitives, hinting at a "stack of layers". Dimensions are kept
    # small so the glyph sits inside the name column's leading padding
    # without crowding the label. The outer HStack's 4-px ``spacing``
    # separates the icon from the label so the row reads "<icon> <name>"
    # rather than glued together.
    _LEADING_ICON_WIDTH = 10
    _LEADING_ICON_BAR_HEIGHT = 2
    _LEADING_ICON_BAR_GAP = 1

    # Step 62 — tooltip copy for the interactive column icons. Kept as
    # class-level constants so tests can assert the exact strings
    # without duplicating the message text, and so a single-point
    # rename here propagates to every row. Save / mute / lock all use
    # short action sentences that name the gesture + the row so the
    # tip reads as "what does this do here" rather than a generic
    # column legend.
    SAVE_TOOLTIP = "Save this layer to disk"
    LOCAL_MUTE_TOOLTIP_UNMUTED = "Mute this layer (exclude from composition)"
    LOCAL_MUTE_TOOLTIP_MUTED = "Unmute this layer (include in composition)"
    LOCK_TOOLTIP_UNLOCKED = "Lock this layer against authoring edits"
    LOCK_TOOLTIP_LOCKED = "Unlock this layer to allow authoring edits"
    READONLY_OVERLAY_TOOLTIP = "This layer's backing file is read-only on disk"

    # Missing-layer badge (Step 27) — a small red "X" glyph painted
    # next to the leading icon whenever :attr:`LayerItem.is_missing`.
    # Rendered as an ASCII :class:`ui.Label` ("X") rather than a
    # rotated-primitive hack because omni.ui has no rotation on its
    # shape primitives and the ``X`` letter sits in every system font
    # with no fallback-coverage risk (unlike the Step-19 save dot,
    # where ``●`` would have driven a font dependency). The Step-27
    # SVG pack swaps this Label for an ``Image::layers_missing_x``
    # glyph; the ``Layers.MissingBadge`` selector + fixed 10-px slot
    # stay put so the swap lands with zero delegate edits.
    _MISSING_BADGE_WIDTH = 10

    def _row_bg_name(self, item: Any) -> str:
        """Pick the row-background Rectangle's ``name=`` token (Step 25).

        Returns ``"row_bg_edit_target"`` when the row is the current
        authoring layer so the green
        ``Layers.TreeView.Row::row_bg_edit_target`` rule paints across
        every cell (branch + 7 columns). Every other row — including
        ancestors of the edit target — keeps the neutral ``"row_bg"``
        so the green fill remains a one-row signal.

        Non-:class:`LayerItem` rows (Phase J prim-spec rows) are routed
        through the same helper and fall through to ``"row_bg"`` — they
        are never the edit target themselves.
        """
        if isinstance(item, LayerItem) and item._is_edit_target:
            return "row_bg_edit_target"
        return "row_bg"

    def _leading_icon_state(self, item: Any) -> str:
        """Pick the leading-icon state (Step 25).

        - ``"edit_target"`` — the authoring layer row itself. Full
          ``cl.layers_icon_edit_target`` green.
        - ``"has_descendant"`` — some descendant of this row is the
          edit target (propagated by :meth:`LayerModel._update_edit_target`).
          Half-green ``cl.layers_icon_half_edit`` so collapsed branches
          hint at "edit target lives inside" without stealing the
          full-row signal from the actual authoring layer.
        - ``"normal"`` — dim secondary-text tint; the glyph reads as a
          neutral "layer" badge on every other row.

        Precedence ``edit_target > has_descendant > normal`` matches
        LAYERS-PLAN Step 25 "Name icon selection hierarchy".
        """
        if not isinstance(item, LayerItem):
            return "normal"
        if item._is_edit_target:
            return "edit_target"
        if item._has_edit_target_descendant:
            return "has_descendant"
        return "normal"

    # Step 44 — horizontal between-drop line thickness. 2 px reads as
    # a deliberate insertion cue at every DPI without punching through
    # adjacent row hover backgrounds; anything thinner visually merges
    # with the ``Layers.TreeView`` secondary-colour branch line.
    _DROP_LINE_HEIGHT = 2

    def _drop_indicator_name(self, model: Any, item: Any) -> str:
        """Return the drop-indicator name for ``item`` (Step 44).

        Returns :data:`INDICATOR_NONE` when no indicator should paint
        for this row — that's the common case, so the fast path skips
        the controller lookup when the model has no
        :attr:`drop_visual` attribute (e.g. a test that hands a bare
        :class:`ui.AbstractItemModel` in place of
        :class:`LayerModel`). When the controller has a live target,
        defers to :meth:`DropVisualController.indicator_for` so the
        above/below/onto decision is owned by one module.
        """
        controller = getattr(model, "drop_visual", None)
        if controller is None:
            return INDICATOR_NONE
        return controller.indicator_for(item)

    def _build_focus_ring(self, item: Any) -> None:
        """Paint the Step 62 keyboard-focus ring for the current cell.

        No-op unless ``item`` is a :class:`LayerItem` carrying
        :attr:`LayerItem.is_focused`. When focused, the caller's
        :class:`ui.ZStack` gets a transparent Rectangle with the
        ``Layers.TreeView.Row::row_focus`` style — a 1-px accent
        border that paints above the row background and every column
        widget. The ring is a row-scoped cue; because each cell
        paints its own rectangle, ovui renders the seven cells'
        rectangles as one continuous outline across the row strip
        (matching the row-bg strategy from Step 23).
        """
        if not isinstance(item, LayerItem):
            return
        if not item._is_focused:
            return
        ui.Rectangle(
            style_type_name_override="Layers.TreeView.Row",
            name="row_focus",
        )

    def _build_drop_indicator(self, indicator: str) -> None:
        """Paint the Step 44 drop-indicator overlay for the current cell.

        The indicator name is one of the ``INDICATOR_*`` tokens from
        :mod:`ovwidgets.layers.drop_visual_controller`. Rendering strategy:

        - :data:`INDICATOR_DROP_TARGET` / :data:`INDICATOR_DROP_REJECTED`
          paint a full-cell :class:`ui.Rectangle` with the matching
          ``Layers.DropIndicator::<name>`` style selector — the
          selector picks up green / red outline + fill from the style
          block (the Rectangle itself is transparent by default, the
          style resolves ``border_*`` to the accent colour).
        - :data:`INDICATOR_DROP_ABOVE` / :data:`INDICATOR_DROP_BELOW`
          paint a 2-px horizontal :class:`ui.Rectangle` pinned to the
          top or bottom of the cell via a :class:`ui.VStack` sandwich
          so the stripe reads as a seam between rows without stealing
          vertical space from the row's actual content.

        Callers nest the ``ui.Rectangle`` inside the column's outer
        :class:`ui.ZStack` (top layer) so the indicator paints above
        the row-bg Rectangle + the per-column widget without affecting
        either. For the empty :data:`INDICATOR_NONE` case this method
        is a no-op so the fast path costs only an attribute read.
        """
        if indicator == INDICATOR_NONE:
            return
        if indicator in (INDICATOR_DROP_TARGET, INDICATOR_DROP_REJECTED):
            ui.Rectangle(
                style_type_name_override="Layers.DropIndicator",
                name=indicator,
            )
            return
        # Between-drop — 2-px horizontal line anchored to the top or
        # bottom edge of the cell. ``ui.Rectangle``'s ``alignment`` prop
        # (inherited from :class:`ui.Shape`) positions the shape within
        # its parent's box: setting ``alignment=TOP`` with an explicit
        # ``height`` pins a thin stripe flush with the cell's upper
        # edge; ``BOTTOM`` pins it to the lower edge. Using alignment
        # instead of a VStack + Spacer sandwich keeps the single paint
        # site per cell — one primitive, no risk of a nested layout
        # rendering the stripe at both edges when the container's
        # growth semantics differ from expectations.
        alignment = (
            ui.Alignment.CENTER_TOP
            if indicator == INDICATOR_DROP_ABOVE
            else ui.Alignment.CENTER_BOTTOM
        )
        ui.Rectangle(
            height=ui.Pixel(self._DROP_LINE_HEIGHT),
            alignment=alignment,
            style_type_name_override="Layers.DropIndicator",
            name=indicator,
        )

    def build_branch(
        self,
        model: Any,
        item: Any,
        column_id: int,
        level: int,
        expanded: bool,
    ) -> None:
        """Branch-area renderer — row selection rectangle + chevron (Step 23).

        ovui calls ``build_branch`` once per row for ``column_id == 0``.
        The returned widgets paint **behind** the row's widget cells,
        which is the hook the plan uses to layer a full-row selection
        Rectangle under the per-column content (LAYERS-WINDOW-
        ARCHITECTURE §20.1). The cell is a :class:`ui.ZStack`:

        - Back layer: ``Layers.TreeView.Row::row_bg`` :class:`ui.Rectangle`
          — transparent at rest; paints ``cl.layers_row_hover`` on mouse
          hover and ``cl.treeview_selection`` when the row is selected
          (pseudo-states propagate from the TreeView item).
        - Front layer: an :class:`ui.HStack` holding the indent spacer
          and, for expandable rows, a :class:`ui.Triangle` chevron.

        Non-:class:`LayerItem` rows (future prim-spec rows, Phase J)
        still need the selection background so the row highlight
        stays coherent across mixed stacks; the early-return after the
        Rectangle keeps the paint pass cheap without skipping the
        highlight.
        """
        if column_id != 0:
            return
        with ui.ZStack():
            # Group F — the per-cell row_bg Rectangle that used to live
            # here was removed; selection / hover now paint through the
            # TreeView's native ``:selected`` / ``background_selected_color``
            # mechanism configured on ``Layers.TreeView``. The ZStack is
            # kept so the chevron, drop indicator, and focus ring can
            # still layer cleanly above the column's content — and so
            # any future per-row overlay (e.g. a left-edge accent
            # stripe) has an obvious mounting point.
            # Indent + chevron. ``can_item_have_children`` is
            # the same gate the name model uses to decide whether a
            # row can carry a suffix badge — reusing it keeps the
            # branch chevron state in lockstep with the tree structure.
            # Step 48 — ``PrimSpecItem`` rows also need the chevron so
            # the user can expand into nested prim specs; the
            # ``LayerModel.can_item_have_children`` extension already
            # covers both item types.
            has_children = False
            if isinstance(item, (LayerItem, PrimSpecItem)) and hasattr(
                model, "can_item_have_children"
            ):
                has_children = bool(model.can_item_have_children(item))
            with ui.HStack():
                ui.Spacer(width=ui.Pixel(level * self._INDENT_PER_LEVEL))
                if has_children:
                    # PNG chevron glyph (mirrors
                    # ``ovwidgets.stage/widget/stage_delegate.py:88-99``).
                    # ``chevron_right.png`` for collapsed,
                    # ``chevron_down.png`` for expanded. The PNG carries
                    # its own white pixels so the widget paints without
                    # a colour tint; ``Layers.BranchChevron`` is kept in
                    # the style dict as a no-op for forward-compat with
                    # any future per-state colour override.
                    with ui.VStack(width=ui.Pixel(self._CHEVRON_SIZE)):
                        ui.Spacer()
                        ui.ImageWithProvider(
                            _chevron_provider(
                                _CHEVRON_DOWN if expanded else _CHEVRON_RIGHT
                            ),
                            width=ui.Pixel(self._CHEVRON_SIZE),
                            height=ui.Pixel(self._CHEVRON_SIZE),
                            style_type_name_override="Layers.BranchChevron",
                        )
                        ui.Spacer()
                else:
                    ui.Spacer(width=ui.Pixel(self._CHEVRON_SIZE))
            # Step 44 — paint the drop indicator (if any) as the
            # top-most layer of the branch cell so the green / red
            # outline or the horizontal between-drop line overrides
            # every lower layer. No-op on the common "no drag in
            # progress" case.
            self._build_drop_indicator(self._drop_indicator_name(model, item))
            # Step 62 — keyboard-focus ring. Paints above the drop
            # indicator so the focus cue is never occluded by a
            # concurrent drag hover; a drop-rejected row still shows
            # the red outline underneath because the focus ring uses
            # a different border thickness and colour.
            self._build_focus_ring(item)

    def build_widget(
        self,
        model: Any,
        item: Any,
        column_id: int,
        level: int,
        expanded: bool,
    ) -> None:
        """Dispatch to the per-column builder.

        Step 23 wraps every column's content in a :class:`ui.ZStack`
        whose back layer is a ``Layers.TreeView.Row::row_bg``
        :class:`ui.Rectangle`. ovui propagates the owning TreeView
        item's ``:hovered`` / ``:selected`` pseudo-states down to the
        Rectangle, so hovering or selecting a row paints the
        highlight across every column — combined with the matching
        Rectangle painted by :meth:`build_branch` the full 7-column
        row reads as one continuous selection strip (LAYERS-WINDOW-
        ARCHITECTURE §20.1 "selection Rectangle around the branch").
        The front layer dispatches to the existing per-column
        builder so the graduated widgets (name / save / mute /
        lock) and the Step 22 placeholders render unchanged.

        Step 48 — :class:`PrimSpecItem` rows render their prim name +
        specifier type in column 0 and leave columns 1-6 blank
        (LAYERS-WINDOW-ARCHITECTURE §18.5). The row-bg Rectangle is
        still painted so hover / selection tints span the whole row.
        """
        if isinstance(item, PrimSpecItem):
            self._build_prim_spec_widget(item, column_id)
            return
        if not isinstance(item, LayerItem):
            return
        with ui.ZStack() as cell_stack:
            # Group F — the per-cell ``Layers.TreeView.Row::row_bg``
            # Rectangle used to live here, but ovui's TreeView column
            # layout (column dividers + per-widget margins) splintered
            # the row background into 6 disconnected chunks
            # (``layers-visual-diagnostic.md`` finding #1). The row
            # background is now drawn by the TreeView itself via the
            # native ``:selected`` / ``background_selected_color`` paint
            # configured on ``Layers.TreeView`` in :data:`LAYERS_STYLES`.
            # The cell still uses a ZStack so :meth:`_build_focus_ring`
            # and :meth:`_build_drop_indicator` can layer their overlays
            # above the column content without re-architecting the
            # delegate.
            #
            # Dispatch table matches LAYERS-WINDOW-ARCHITECTURE §20.5
            # column IDs.
            if column_id == self.COL_NAME:
                self._build_name_widget(model, item)
            elif column_id == self.COL_SAVE:
                self._build_save_widget(model, item)
            elif column_id == self.COL_LOCAL_MUTE:
                self._build_local_mute_widget(model, item)
            elif column_id == self.COL_LOCK:
                self._build_lock_widget(model, item)
            elif column_id == self.COL_LIVE:
                self._build_live_placeholder(item)
            elif column_id == self.COL_GLOBAL_MUTE:
                self._build_global_mute_placeholder(item)
            elif column_id == self.COL_LATEST:
                self._build_latest_placeholder(item)
            else:
                # Any column outside 0..6 (e.g. a defensive overflow
                # test) — render nothing; the Rectangle alone keeps
                # the highlight strip coherent.
                ui.Spacer()
            # Step 44 — paint the drop indicator on top of the
            # per-column content. Between-drop lines and drop-target
            # / drop-rejected outlines must be visible over the
            # save / mute / lock icons, so this sits outside the
            # column-dispatch but inside the outer ZStack. For
            # :data:`INDICATOR_NONE` the helper is a no-op.
            indicator = self._drop_indicator_name(model, item)
            self._build_drop_indicator(indicator)
            # Step 62 — paint the keyboard-focus ring on every cell so
            # the 1-px outline reads as one continuous rectangle across
            # the row. No-op when the row is not the focused item.
            self._build_focus_ring(item)
        # Step 44 — when the row is the rejected drop target, surface
        # the rejection reason as a cell tooltip. Attaching on the
        # outer ZStack means hover anywhere on the row reveals the
        # explanation; the tooltip clears naturally on the next
        # ``build_widget`` pass because the cell rebuilds once the
        # controller state resets via :meth:`LayerModel._clear_drop_visual`.
        if indicator == INDICATOR_DROP_REJECTED:
            controller = getattr(model, "drop_visual", None)
            if controller is not None and controller.rejection_reason:
                cell_stack.tooltip = controller.rejection_reason
        # Step 38 — wire the per-cell right-click to the window-level
        # context menu. Attached to the outer ZStack (after the
        # ``with`` block so the handler binding reaches every cell,
        # including cells whose front widget is a bare ``Spacer``).
        # Interactive cells (save / mute / lock) install their own
        # mouse handlers on the inner primitive, which ovui resolves
        # *before* the ZStack-level handler for clicks inside that
        # primitive — so right-clicking a save dot still triggers
        # its save-as gesture and right-clicking the surrounding
        # empty cell area still opens the context menu. The guard on
        # ``on_right_click is None`` keeps the bare-delegate unit
        # tests (no window attached) from paying the binding cost.
        if self.on_right_click is not None:
            cb = self.on_right_click
            cell_stack.set_mouse_pressed_fn(
                lambda x, y, btn, mod, _item=item, _cb=cb: (
                    _cb(_item, x, y) if btn == 1 else None
                )
            )

    # Specifier-code → 3-letter tag shown next to prim-spec rows
    # (Step 48). Kept as a class-level mapping so tests can assert
    # the exact copy without duplicating the strings. Step 49 uses
    # the same tags as the ``name=`` token on the specifier icon's
    # ``Layers.PrimSpecIcon`` selector so the style block can pick up
    # per-kind overrides without the delegate carrying a second table.
    _PRIM_SPEC_TAG_BY_SPECIFIER = {
        PrimSpecifier.DEF: "def",
        PrimSpecifier.OVER: "over",
        PrimSpecifier.CLASS: "class",
    }

    # Height-matched indent contribution for prim-spec rows (Step 48).
    # A prim spec sits one level deeper than the layer that owns it in
    # the widget hierarchy, so the tree-view level already accounts
    # for the offset; this constant exists so the delegate can still
    # draw the prim-spec name column inside the same 14-px grid as the
    # layer-name column.
    _PRIM_SPEC_NAME_SPACING = 4

    # Specifier icon dimensions (Step 49). 16 px matches the layer-name
    # column's leading icon slot so the two icon columns share a single
    # optical grid; the badge overlay is half the edge length so it
    # reads as a corner decoration rather than a second primary glyph.
    _PRIM_SPEC_ICON_SIZE = 16
    _PRIM_SPEC_BADGE_SIZE = 9

    def _build_prim_spec_widget(
        self, item: PrimSpecItem, column_id: int
    ) -> None:
        """Paint a :class:`PrimSpecItem` row — Step 48.

        Column 0 renders the prim name (plus the specifier tag and,
        when non-empty, the USD type name) so the row reads as
        ``<specifier> <name> (<type>)``. Columns 1-6 stay blank
        (``ui.Spacer``) — LAYERS-WINDOW-ARCHITECTURE §18.5 "all columns
        other than the name are blank for prim-spec rows".

        Group F removed the per-cell row_bg Rectangle that used to
        sit at the back of every cell's ZStack. Selection / hover
        tints now paint through ovui's native TreeView mechanism
        (``Layers.TreeView:selected.background_color`` and
        ``Layers.TreeView.background_selected_color``); a
        spec-row's columns inherit the same band as a layer-row's
        because the TreeView paints per node, not per item-type.

        Step 49 graduates the text tag to a provider-backed SVG icon
        (``prim_def.svg`` / ``prim_over.svg`` / ``prim_class.svg``)
        and overlays reference / payload badges. The current text
        render is intentionally the cheapest possible readable cue so
        the UI works end-to-end without new icon assets.
        """
        if column_id == self.COL_NAME:
            self._build_prim_spec_name_widget(item)
        else:
            # Non-name cells stay blank for prim-spec rows but the
            # Spacer ensures ovui still allocates the layout slot —
            # a missing widget would collapse the cell height and
            # jostle the surrounding row strip.
            ui.Spacer()

    def _build_prim_spec_name_widget(self, item: PrimSpecItem) -> None:
        """Render the prim-spec name column (Step 48 + Step 49).

        Layout is a horizontal strip:
        ``<specifier icon + badges> <name> (<type>)``.

        Step 49 graduated the Step-48 text tag into a provider-backed
        PNG glyph chosen by :func:`ovwidgets.layers.layer_icons.specifier_icon`:
        ``DEF`` → solid cube (``prim_def``), ``OVER`` → wireframe
        cube (``prim_over``), ``CLASS`` → dashed "C" (``prim_class``).
        Reference / payload / instance badges are overlaid on the main
        icon via a :class:`ui.ZStack` so a single row reads both
        "what kind of opinion" (main glyph) and "what composition arcs
        are present" (corner badge) at a glance.

        When the icon registry has not been populated (a test harness
        that bypasses :func:`ovwidgets.common.style.urls.register_urls` or a
        mis-configured install) the call falls back to the Step-48
        text tag so the tree stays legible rather than rendering a
        blank slot. The fallback preserves the Step-48 style selector
        (``Layers.PrimSpecTag::<kind>``) so theme rules keep applying.
        """
        type_name = item.type_name
        with ui.HStack(spacing=self._PRIM_SPEC_NAME_SPACING):
            self._build_prim_spec_icon(item)
            ui.Label(
                item.name,
                style_type_name_override="Layers.PrimSpecName",
                alignment=ui.Alignment.LEFT_CENTER,
            )
            if type_name:
                ui.Label(
                    f"({type_name})",
                    style_type_name_override="Layers.PrimSpecType",
                    alignment=ui.Alignment.LEFT_CENTER,
                )
            ui.Spacer()

    def _build_prim_spec_icon(self, item: PrimSpecItem) -> None:
        """Paint the specifier icon + composition / instance badges (Step 49).

        Layout is a :class:`ui.ZStack` sized to the main icon:

        - Back layer — the specifier glyph (DEF / OVER / CLASS).
          Rendered with :class:`ui.ImageWithProvider` backed by a
          cached :class:`ui.RasterImageProvider` because the standalone
          ``omni.ui`` build in this repo rejects SVG through
          :class:`ui.Image`.
        - Front layer, bottom-right — composition badge (reference or
          payload, payload winning when both are set). Painted inside
          a :class:`ui.VStack`/:class:`ui.HStack` sandwich whose
          spacers push the badge to the corner without taking real
          layout space from the icon.
        - Front layer, top-right — instance badge, when the prim spec
          is instanceable. Orthogonal to the composition badge so the
          two can co-exist without overlap.

        When the icon registry has not registered paths for a given
        specifier (e.g. a bare unit-test harness that never calls
        :func:`ovwidgets.common.style.urls.register_urls`) the method falls back
        to the Step-48 text tag so the row still reads as a prim-spec
        kind. The fallback uses the same
        ``Layers.PrimSpecTag::<kind>`` selector so any theme rules
        targeting the text tag remain applicable.
        """
        kind = self._PRIM_SPEC_TAG_BY_SPECIFIER.get(item.specifier, "def")
        icon_path = specifier_icon(item.specifier)
        if icon_path is None:
            # Registry has not been populated — degrade to the Step-48
            # text tag so the row still communicates the specifier.
            ui.Label(
                kind,
                name=kind,
                width=ui.Pixel(36),
                style_type_name_override="Layers.PrimSpecTag",
                alignment=ui.Alignment.CENTER,
            )
            return
        descriptor = item.descriptor
        badge_path = composition_badge(descriptor)
        instance_path = instance_badge(descriptor)
        size = self._PRIM_SPEC_ICON_SIZE
        badge = self._PRIM_SPEC_BADGE_SIZE
        with ui.ZStack(
            width=ui.Pixel(size),
            height=ui.Pixel(size),
        ):
            # Back layer — main specifier glyph. Passing
            # ``fill_policy=PRESERVE_ASPECT_FIT`` keeps the icon
            # centred inside its square slot even when omni.ui picks
            # a slightly different box size for the ZStack than the
            # requested 16 px (e.g. a DPI-scaled build).
            ui.ImageWithProvider(
                provider(icon_path),
                width=ui.Pixel(size),
                height=ui.Pixel(size),
                fill_policy=ui.IwpFillPolicy.IWP_PRESERVE_ASPECT_FIT,
                style_type_name_override="Layers.PrimSpecIcon",
                name=kind,
            )
            # Bottom-right — composition badge (reference / payload).
            if badge_path is not None:
                badge_kind = (
                    "payload" if descriptor.has_payload else "reference"
                )
                with ui.VStack():
                    ui.Spacer()
                    with ui.HStack():
                        ui.Spacer()
                        ui.ImageWithProvider(
                            provider(badge_path),
                            width=ui.Pixel(badge),
                            height=ui.Pixel(badge),
                            fill_policy=ui.IwpFillPolicy.IWP_PRESERVE_ASPECT_FIT,
                            style_type_name_override="Layers.PrimSpecBadge",
                            name=badge_kind,
                        )
            # Top-right — instance badge (orthogonal to composition).
            if instance_path is not None:
                with ui.VStack():
                    with ui.HStack():
                        ui.Spacer()
                        ui.ImageWithProvider(
                            provider(instance_path),
                            width=ui.Pixel(badge),
                            height=ui.Pixel(badge),
                            fill_policy=ui.IwpFillPolicy.IWP_PRESERVE_ASPECT_FIT,
                            style_type_name_override="Layers.PrimSpecBadge",
                            name="instance",
                        )
                    ui.Spacer()

    def _build_name_widget(self, model: Any, item: LayerItem) -> None:
        """Column 0 — leading layer icon + display name + state suffix.

        Step 18 added the state-suffix label; Step 25 prepends a small
        leading layer icon drawn from three thin horizontal bars whose
        tint encodes the edit-target state of the row:

        - Full green on the authoring layer row
          (``Layers.LeadingIcon::edit_target``).
        - Half-green on rows whose descendants include the edit target
          (``Layers.LeadingIcon::has_descendant``), so a user with a
          collapsed ``mid.usda`` still sees a hint that the authoring
          layer sits below.
        - Dim secondary-text tint otherwise (``::normal``).

        The three stacked :class:`ui.Rectangle` bars are drawn inside a
        fixed-width leading slot so adding the icon does not push the
        label. Primitives are used for the same reason the other icon
        columns (Steps 19/20/21) use primitives — NVIDIA Sans lacks a
        dedicated "layers" codepoint and Step 25's SVG pack is not yet
        shipped. The style contract (``name=<state>``) matches the
        future ``Image::layers_edit_target_pin`` selectors so a later
        swap to SVGs needs no delegate edit.
        """
        value_model = model.get_item_value_model(item, self.COL_NAME)
        if isinstance(value_model, LayerNameValueModel):
            text = value_model.get_value_as_string()
            role = value_model.get_color_role()
        elif value_model is not None:
            # Defensive — a test or future path that hands back a plain
            # string model (e.g. the Step-17 placeholder) still renders
            # without crashing; the row just loses the color hint.
            text = value_model.get_value_as_string()
            role = ""
        else:
            text = ""
            role = ""
        icon_state = self._leading_icon_state(item)
        with ui.HStack(spacing=4) as name_stack:
            self._build_leading_icon(icon_state)
            # Step 27 — missing layers get a small red "X" badge slotted
            # between the leading icon and the label. The badge paints
            # inline (fixed-width cell) so present rows keep their
            # existing icon → label spacing: when the badge is absent,
            # the HStack simply collapses that slot to zero width.
            if item.is_missing:
                self._build_missing_badge()
            ui.Label(
                text,
                name=role,
                style_type_name_override="Layers.NameLabel",
                alignment=ui.Alignment.LEFT_CENTER,
            )
        # Step 62 — row-level tooltip surfaces the full layer identifier
        # so users can read the long path (pulled from
        # :attr:`LayerItem.identifier`) even when the display name is
        # truncated by the name column's width. Attaching on the
        # HStack covers hover anywhere along the icon + label strip so
        # the cue fires wherever the user lands in the cell.
        name_stack.tooltip = item.identifier

    def _build_leading_icon(self, state: str) -> None:
        """Paint the name-column leading icon (Step 25).

        Three thin horizontal :class:`ui.Rectangle` bars stacked with a
        1-px gap between them, centred vertically inside the row. The
        outer :class:`ui.VStack` width equals the bar width so no
        horizontal centring is needed — same trick the Step-19 save
        dot uses for its 10-px circle slot.

        Every bar shares the same ``Layers.LeadingIcon`` style-type
        override and the caller-provided ``name=state`` token so the
        style rule resolves to one of the three state-specific colour
        overrides declared in :mod:`ovwidgets.layers.style`.
        """
        with ui.VStack(
            width=ui.Pixel(self._LEADING_ICON_WIDTH),
            spacing=self._LEADING_ICON_BAR_GAP,
        ):
            ui.Spacer()
            for _ in range(3):
                ui.Rectangle(
                    width=ui.Pixel(self._LEADING_ICON_WIDTH),
                    height=ui.Pixel(self._LEADING_ICON_BAR_HEIGHT),
                    style_type_name_override="Layers.LeadingIcon",
                    name=state,
                )
            ui.Spacer()

    def _build_missing_badge(self) -> None:
        """Paint the name-column missing-layer "X" badge (Step 27).

        Drawn only when :attr:`LayerItem.is_missing`. The caller wraps
        this in the same :class:`ui.HStack` that carries the leading
        icon and label, so the badge slots in between the two and the
        row reads "<icon> <X> <name>" when missing, "<icon> <name>"
        otherwise. The ``X`` is an ASCII :class:`ui.Label` — the one
        letter is present in every fallback font (unlike the Step-19
        ``U+25CF`` dot) so a primitive-based X is over-engineered here.

        Style resolution rides on the ``Layers.MissingBadge``
        type-override; tint comes from ``cl.layers_label_missing`` so
        the badge shares the same red hue as the
        ``NameLabel::missing`` role, making the double-cue read as one
        coherent "unresolved" signal rather than two unrelated reds.
        """
        ui.Label(
            "X",
            width=ui.Pixel(self._MISSING_BADGE_WIDTH),
            style_type_name_override="Layers.MissingBadge",
            alignment=ui.Alignment.CENTER,
        )

    def _build_save_widget(self, model: Any, item: LayerItem) -> None:
        """Column 2 — dirty-and-saveable indicator + click-to-save
        (Step 19, extended for save-as in Step 36).

        Renders a centred filled :class:`ui.Circle` whenever
        :meth:`SaveValueModel.get_value_as_bool` returns ``True`` and
        binds the mouse handlers:

        - **Left-click** — call :meth:`SaveValueModel.set_value`,
          which forwards to the model's save flow. Concrete dirty
          layers take the direct save path; anonymous dirty layers
          route into the save-as file picker (Step 36).
        - **Right-click** — unconditionally open the save-as file
          picker for this row (Step 36). This gives the user a "Save
          As…" gesture on concrete layers too, without having to wait
          for the Phase-H context menu (Step 38). The bypass uses
          :meth:`LayerModel._request_save_as` directly because the
          save-as flow applies to clean layers as well — the user
          may legitimately want to clone a clean layer under a new
          path.

        Using :class:`ui.Circle` over a ``●`` glyph avoids a font-
        dependency: NVIDIA Sans — and most sans-serif families shipped
        with Kit — does not carry ``U+25CF``, so a text-based dot would
        render as a fallback "?" box on the first machine that didn't
        have a full-coverage font installed.

        The defensive fallback mirrors :meth:`_build_name_widget`: if
        the model hands back something other than a
        :class:`SaveValueModel` (a test, a Step 20+ refactor in flight,
        or a late call after :meth:`LayerModel.set_adapter` detached),
        the cell renders blank rather than raising so the paint pass
        never faults mid-tree.
        """
        value_model = model.get_item_value_model(item, self.COL_SAVE)
        if not isinstance(value_model, SaveValueModel):
            ui.Spacer()
            return
        if not value_model.get_value_as_bool():
            ui.Spacer()
            return
        # ``set_mouse_pressed_fn`` captures ``value_model`` via a
        # default-arg closure so every row binds to its own model, not
        # whichever one last won the delegate-loop. The outer ZStack
        # centres the 8-px dot inside the 24-px column cell; the plain
        # stack would otherwise stretch the Circle to fill.
        with ui.ZStack() as save_stack:
            ui.Spacer()  # painted background filler so hover tracks the whole cell
            with ui.HStack():
                ui.Spacer()
                with ui.VStack(width=ui.Pixel(10)):
                    ui.Spacer()
                    dot = ui.Circle(
                        width=ui.Pixel(10),
                        height=ui.Pixel(10),
                        alignment=ui.Alignment.CENTER,
                        style_type_name_override="Layers.SaveIcon",
                        name="dirty",
                    )
                    ui.Spacer()
                ui.Spacer()
        # Step 62 — tooltip on the save column. Uses the row's display
        # name so the cue reads "Save <name> to disk" when a hover
        # lands on the dirty dot; falls back to the generic class-
        # level sentence when no display name is resolvable (test
        # harnesses that pass a bare adapter).
        display = ""
        try:
            display = item.display_name
        except Exception:
            display = ""
        save_stack.tooltip = (
            f"Save '{display}' to disk" if display else self.SAVE_TOOLTIP
        )

        def _on_pressed(
            x: float,
            y: float,
            btn: int,
            mod: int,
            vm: SaveValueModel = value_model,
            owner_item: LayerItem = item,
            owner_model: Any = model,
        ) -> None:
            if btn == 0:
                vm.set_value(True)
            elif btn == 1:
                # Right-click — route directly into the save-as
                # file picker regardless of the layer's anonymous /
                # dirty state (clone-clean is a valid gesture). The
                # model-level guard short-circuits on a detached /
                # destroyed model.
                save_as = getattr(owner_model, "_request_save_as", None)
                if save_as is not None:
                    save_as(owner_item)

        dot.set_mouse_pressed_fn(_on_pressed)

    def _build_local_mute_widget(self, model: Any, item: LayerItem) -> None:
        """Column 3 — local-mute eye indicator + click-to-toggle (Step 20).

        Draws a filled :class:`ui.Circle` (``Layers.MuteIcon::open``) for
        unmuted layers and a short horizontal :class:`ui.Rectangle`
        (``Layers.MuteIcon::muted``) for locally muted layers. The two
        primitives live inside a shared centring stack, and a single
        left-click handler on the outer stack toggles the state via
        :meth:`LocalMuteValueModel.set_value`.

        Using primitives rather than a text glyph keeps the cell
        identical across machines that lack full Geometric-Shapes
        coverage in the system fallback font — same rationale as the
        Step-19 save dot. The Step-24 icon pack replaces both
        primitives with provider-backed eye SVGs; the surrounding
        click-plumbing stays put.

        Defensive fallback mirrors :meth:`_build_save_widget`: a model
        that comes back as something other than a
        :class:`LocalMuteValueModel` (tests, a Phase F refactor in
        flight, a late call after :meth:`LayerModel.set_adapter`
        detached) renders a blank cell rather than raising.
        """
        value_model = model.get_item_value_model(item, self.COL_LOCAL_MUTE)
        if not isinstance(value_model, LocalMuteValueModel):
            ui.Spacer()
            return
        muted = value_model.get_value_as_bool()
        # ZStack centres the glyph inside the 24-px cell; the inner
        # HStack/VStack pair pins the primitive to the geometric centre
        # without letting ovui stretch a Circle/Rectangle to fill.
        with ui.ZStack() as stack:
            ui.Spacer()
            with ui.HStack():
                ui.Spacer()
                with ui.VStack(width=ui.Pixel(12)):
                    ui.Spacer()
                    if muted:
                        # Closed eye — a thin horizontal slit. Height
                        # is 2 px so the bar reads as a deliberate
                        # shape rather than a stray pixel row.
                        ui.Rectangle(
                            width=ui.Pixel(12),
                            height=ui.Pixel(2),
                            alignment=ui.Alignment.CENTER,
                            style_type_name_override="Layers.MuteIcon",
                            name="muted",
                        )
                    else:
                        # Open eye — filled dot (iris). 10 px matches
                        # the save indicator so the two columns share a
                        # consistent optical weight when both show.
                        ui.Circle(
                            width=ui.Pixel(10),
                            height=ui.Pixel(10),
                            alignment=ui.Alignment.CENTER,
                            style_type_name_override="Layers.MuteIcon",
                            name="open",
                        )
                    ui.Spacer()
                ui.Spacer()
        # ``set_mouse_pressed_fn`` captures ``value_model`` via a
        # default-arg closure so every row binds to its own model.
        # Binding to the outer stack rather than the inner primitive
        # means the user's 24-px cell — not just the 10-px glyph — is
        # the clickable hit target, which matches the hover-highlight
        # footprint applied by ``Layers.TreeView:hovered``.
        stack.set_mouse_pressed_fn(
            lambda x, y, btn, mod, vm=value_model: (
                vm.set_value(not vm.get_value_as_bool()) if btn == 0 else None
            )
        )
        # Step 62 — tooltip on the mute column. Phrases the gesture
        # around the row's current state so the cue explains what the
        # click will do, not just which column this is.
        stack.tooltip = (
            self.LOCAL_MUTE_TOOLTIP_MUTED
            if muted
            else self.LOCAL_MUTE_TOOLTIP_UNMUTED
        )

    def _build_lock_widget(self, model: Any, item: LayerItem) -> None:
        """Column 6 — padlock indicator + click-to-toggle (Step 21).

        Draws a small padlock glyph from two :class:`ui.Rectangle`
        primitives: a shackle (the arch) stacked above a body (the
        rectangular base). When the layer is locked both rectangles
        paint in the ``Layers.LockIcon::locked`` tint (primary text)
        — a fully drawn padlock. When unlocked only the body paints,
        dimmed to the ``Layers.LockIcon::unlocked`` tint, so the row
        reads as an open-lock base rather than a complete glyph. Both
        states expose the same 24-px click target via the outer stack,
        keeping the hover-highlight footprint aligned with
        ``Layers.TreeView:hovered``.

        Using primitives over a text glyph keeps the cell identical
        across machines that lack a padlock codepoint in the system
        fallback font — same rationale as the Step-19 save dot and
        Step-20 mute eye. The Step-24 icon pack replaces both
        primitives with a provider-backed padlock SVG; the surrounding
        click-plumbing stays put because the ``name=`` state contract
        (``locked`` / ``unlocked``) matches ``Image::layers_lock:*``.

        Step 27 wraps the interactive padlock in an outer
        :class:`ui.ZStack` whose back layer is a
        ``Layers.LockIcon::readonly_overlay`` :class:`ui.Rectangle`
        painted only when :attr:`LayerItem.is_read_only`. The overlay
        is non-interactive — its ``Rectangle`` sits behind the click
        stack and carries no mouse handler, so it reads as a backdrop
        "file is not writable on disk" hint regardless of the
        user-driven lock bit. A read-only *and* locked row shows both
        cues (backdrop + bright padlock) without visual conflict
        because the overlay tint is dim and the padlock still paints
        on top.

        Defensive fallback mirrors :meth:`_build_local_mute_widget`:
        a model that comes back as something other than a
        :class:`LockValueModel` (tests, a Phase F refactor in flight,
        a late call after :meth:`LayerModel.set_adapter` detached)
        renders a blank cell rather than raising.
        """
        value_model = model.get_item_value_model(item, self.COL_LOCK)
        if not isinstance(value_model, LockValueModel):
            ui.Spacer()
            return
        locked = value_model.get_value_as_bool()
        state = "locked" if locked else "unlocked"
        # Outer ZStack (Step 27) — back layer paints the read-only
        # overlay Rectangle when the layer is read-only on disk;
        # front layer holds the existing clickable padlock stack. The
        # overlay is skipped entirely for writable rows so the paint
        # pass stays cheap in the common case.
        with ui.ZStack():
            if item.is_read_only:
                ui.Rectangle(
                    style_type_name_override="Layers.LockIcon",
                    name="readonly_overlay",
                )
            # ZStack centres the glyph inside the 24/26-px cell; the
            # inner HStack/VStack pair pins the primitives to the
            # geometric centre without letting ovui stretch them to
            # fill. This is the interactive layer — the outer overlay
            # above stays behind it.
            with ui.ZStack() as stack:
                ui.Spacer()
                with ui.HStack():
                    ui.Spacer()
                    # Fixed-width inner column so the shackle and body
                    # share a vertical centre line. 10 px matches the
                    # Step-19 save dot and Step-20 mute iris for
                    # consistent optical weight across icon columns.
                    with ui.VStack(width=ui.Pixel(10), spacing=0):
                        ui.Spacer()
                        # Shackle — the arch over the lock body. Only
                        # drawn when locked; its presence is the primary
                        # "closed" signal (padlock with its hoop intact).
                        # 2-px height + 8-px width + 1-px side inset
                        # through the flanking stack gives a readable
                        # arch at 10-px target width without needing a
                        # curved primitive.
                        if locked:
                            with ui.HStack(height=ui.Pixel(3)):
                                ui.Spacer(width=ui.Pixel(1))
                                ui.Rectangle(
                                    width=ui.Pixel(8),
                                    height=ui.Pixel(3),
                                    style_type_name_override="Layers.LockIcon",
                                    name=state,
                                )
                                ui.Spacer(width=ui.Pixel(1))
                        else:
                            # Preserve vertical layout so the body sits
                            # in the same pixel row across both states —
                            # otherwise the unlocked body would rise by
                            # 3 px and the column would bounce on toggle.
                            ui.Spacer(height=ui.Pixel(3))
                        # Body — the rectangular lock base. Drawn in both
                        # states; tint ``::locked`` reads bright, tint
                        # ``::unlocked`` reads dimmed so the open state
                        # stays quiet in the column strip.
                        ui.Rectangle(
                            width=ui.Pixel(10),
                            height=ui.Pixel(7),
                            style_type_name_override="Layers.LockIcon",
                            name=state,
                        )
                        ui.Spacer()
                    ui.Spacer()
            # ``set_mouse_pressed_fn`` captures ``value_model`` via a
            # default-arg closure so every row binds to its own model.
            # Binding to the outer stack makes the full 24-px cell the
            # clickable hit target — identical footprint to the Step-20
            # mute column — so the hover highlight and click target line
            # up across all icon columns.
            stack.set_mouse_pressed_fn(
                lambda x, y, btn, mod, vm=value_model: (
                    vm.set_value(not vm.get_value_as_bool()) if btn == 0 else None
                )
            )
            # Step 62 — tooltip on the lock column. The read-only file
            # overlay surfaces its own message when present (wins over
            # the lock-toggle tip because the user needs to know the
            # file is immutable on disk before the click will matter);
            # otherwise the tip phrases the gesture around the row's
            # current locked / unlocked state.
            if item.is_read_only:
                stack.tooltip = self.READONLY_OVERLAY_TOOLTIP
            elif locked:
                stack.tooltip = self.LOCK_TOOLTIP_LOCKED
            else:
                stack.tooltip = self.LOCK_TOOLTIP_UNLOCKED

    # ── Step 22 placeholder builders ─────────────────────────────────

    # Tooltip strings for the three disabled placeholder columns. Kept
    # as class-level constants so tests can assert the exact text
    # without duplicating the copy — a rename here is the one edit.
    LIVE_PLACEHOLDER_TOOLTIP = "Live sync \u2014 coming in v2"
    GLOBAL_MUTE_PLACEHOLDER_TOOLTIP = "Global mute \u2014 coming in v2"
    LATEST_PLACEHOLDER_TOOLTIP = "Version tracking \u2014 coming in v2"

    def _build_live_placeholder(self, item: LayerItem) -> None:
        """Column 1 — disabled Live-session placeholder (Step 22).

        Draws a small dim filled :class:`ui.Circle` in the
        ``Layers.PlaceholderIcon::disabled`` tint. No click handler is
        bound — the placeholder is non-interactive in v1, so a click
        falls through to the TreeView row (matching the normal row-
        selection hit target). A ``coming in v2`` tooltip on the outer
        stack explains the greyed state on hover.

        Step 42 replaces this with the real ``LiveValueModel`` and a
        click-to-toggle live-sync handler; the style block stays stable
        because the named state contract (``disabled`` → active icon)
        maps cleanly onto ``Layers.PlaceholderIcon``'s successors.
        """
        del item  # state-independent — every row shows the same glyph
        with ui.ZStack() as stack:
            ui.Spacer()
            with ui.HStack():
                ui.Spacer()
                with ui.VStack(width=ui.Pixel(8)):
                    ui.Spacer()
                    ui.Circle(
                        width=ui.Pixel(8),
                        height=ui.Pixel(8),
                        alignment=ui.Alignment.CENTER,
                        style_type_name_override="Layers.PlaceholderIcon",
                        name="disabled",
                    )
                    ui.Spacer()
                ui.Spacer()
        stack.tooltip = self.LIVE_PLACEHOLDER_TOOLTIP

    def _build_global_mute_placeholder(self, item: LayerItem) -> None:
        """Column 4 — disabled Global-Mute placeholder (Step 22).

        Draws a small dim horizontal :class:`ui.Rectangle` in the
        ``Layers.PlaceholderIcon::disabled`` tint — visually distinct
        from the Live dot and the Latest square so the three reserved
        columns read as three separate "reserved for" signals rather
        than one repeated blob. No click handler; the row hit target
        falls through to the TreeView.

        LAYERS-PLAN Step 22 notes that global-mute should be hidden
        (width-0) unless ``settings.muteness_scope_global`` is True —
        v1 never flips that setting, so the column exists but paints
        a placeholder. Step 43's :class:`GlobalMuteValueModel` replaces
        this with the real open/closed eye pair.
        """
        del item  # state-independent — every row shows the same glyph
        with ui.ZStack() as stack:
            ui.Spacer()
            with ui.HStack():
                ui.Spacer()
                with ui.VStack(width=ui.Pixel(10)):
                    ui.Spacer()
                    ui.Rectangle(
                        width=ui.Pixel(10),
                        height=ui.Pixel(2),
                        alignment=ui.Alignment.CENTER,
                        style_type_name_override="Layers.PlaceholderIcon",
                        name="disabled",
                    )
                    ui.Spacer()
                ui.Spacer()
        stack.tooltip = self.GLOBAL_MUTE_PLACEHOLDER_TOOLTIP

    def _build_latest_placeholder(self, item: LayerItem) -> None:
        """Column 5 — disabled Latest / version-tracking placeholder (Step 22).

        Draws a small dim square :class:`ui.Rectangle` in the
        ``Layers.PlaceholderIcon::disabled`` tint — but only for rows
        whose layer is missing (``LayerItem.is_missing``). Non-missing
        rows render a :class:`ui.Spacer` so the column is genuinely
        blank in the common case, mirroring Kit's "reload hint shows
        up only when the file couldn't be resolved" convention
        (LAYERS-PLAN Step 22 detail line).

        The missing-layer glyph stands in for the Step-44
        ``LatestValueModel`` reload icon — the real control will flag
        an out-of-date sublayer the user can click to refetch from
        Nucleus. For now the cell is visual-only: no click handler, no
        adapter write.
        """
        if not item.is_missing:
            ui.Spacer()
            return
        with ui.ZStack() as stack:
            ui.Spacer()
            with ui.HStack():
                ui.Spacer()
                with ui.VStack(width=ui.Pixel(8)):
                    ui.Spacer()
                    ui.Rectangle(
                        width=ui.Pixel(8),
                        height=ui.Pixel(8),
                        alignment=ui.Alignment.CENTER,
                        style_type_name_override="Layers.PlaceholderIcon",
                        name="disabled",
                    )
                    ui.Spacer()
                ui.Spacer()
        stack.tooltip = self.LATEST_PLACEHOLDER_TOOLTIP


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovwidgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_CHEVRON_PROVIDER_CACHE)
