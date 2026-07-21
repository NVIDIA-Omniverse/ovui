# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""StageDelegate — renders rows in the Stage Browser TreeView.

StageDelegate renders StageWidget columns for the stage implementation steps 13–16
(SVG prim icons, overlay badges, eye-checkbox visibility, inactive/default/
class styling).
"""

import importlib.resources
from typing import Any

import omni.ui as ui

from ovui_widgets.stage.widget import stage_icons
from ovui_widgets.stage.widget.hierarchy_model import HierarchyItem, HierarchyModel

_ICON_DIR = str(importlib.resources.files("ovui_widgets.common").joinpath("icons"))
_CHEVRON_RIGHT = f"{_ICON_DIR}/chevron_right.png"
_CHEVRON_DOWN = f"{_ICON_DIR}/chevron_down.png"

# GLFW key code for Escape — cancels the active inline rename.
_KEY_ESCAPE = 256

# Row geometry. Keep this in sync with ``fl.treeview_row_height``.
_ROW_HEIGHT = 18
_INDENT_PER_LEVEL = 14
_CHEVRON_SIZE = 12
_TYPE_ICON_SIZE = 10
_BADGE_SIZE = 8
_VISIBILITY_ICON_SIZE = 14
_DEFAULT_PILL_LABEL = "DEF"
_DEFAULT_PILL_WIDTH = 24
_DEFAULT_PILL_HEIGHT = 12
_DEFAULT_PILL_HORIZONTAL_PADDING = 4


class StageDelegate(ui.AbstractItemDelegate):
    """Three-column delegate: Name | Type | Visibility."""

    INDENT = _INDENT_PER_LEVEL

    def __init__(self) -> None:
        super().__init__()
        self._rename_controller = None
        self._expand_toggle_callback = None
        self._rename_items: set = set()
        self._rename_fields: dict[Any, Any] = {}
        self._visibility_subscriptions: dict[int, Any] = {}

    def set_rename_controller(self, controller: Any) -> None:
        self._rename_controller = controller

    def set_expand_toggle_callback(self, callback: Any) -> None:
        """Route explicit chevron presses through the owning StageWidget."""
        self._expand_toggle_callback = callback

    def set_rename_mode(self, item: HierarchyItem, active: bool) -> None:
        if active:
            self._rename_items.add(item)
        else:
            self._rename_items.discard(item)
            self._rename_fields.pop(item, None)

    def release_visibility_subscriptions(self) -> None:
        """Drop every retained eye-cell value subscription.

        The owning StageWidget calls this whenever the whole tree is about
        to rebuild (adapter replacement, structural rebuild, filter change,
        document detach) and on destroy. Every surviving row re-subscribes
        when its cell next builds; without this release, subscriptions of
        rows that never build again — a replaced document's entire tree,
        or deleted prims after a resync — retain their value models,
        items, and through them the replaced document's adapter forever.
        """
        subscriptions = self._visibility_subscriptions
        self._visibility_subscriptions = {}
        for subscription in subscriptions.values():
            try:
                unsubscribe = getattr(subscription, "unsubscribe", None)
                if callable(unsubscribe):
                    unsubscribe()
            except BaseException:  # noqa: BLE001 — release every owner
                # Dropping the reference already releases ownership; a
                # hostile unsubscribe must not keep the rest retained.
                continue

    # ── Branch arrow ─────────────────────────────────────────────────────────

    def build_branch(self, model: Any, item: Any, column_id: Any, level: Any, expanded: Any) -> None:
        if column_id != 0:
            return
        # NB: intentionally do NOT write ``expanded`` back into
        # ``model._expanded_paths`` here. build_branch fires on every
        # render, including the first render after a tree rebuild when
        # every new HierarchyItem starts out collapsed in the TreeView's
        # internal set. Using that as the source of truth would erase the
        # authoritative expansion state the StageWidget just restored.
        # User chevron clicks flow through HierarchyModel's notice-driven
        # snapshot instead; see StageWidget._snapshot_expansion.
        has_children = model.can_item_have_children(item)
        total_w = _INDENT_PER_LEVEL * level + _INDENT_PER_LEVEL
        is_selected = item in getattr(model, "_selected_items", [])
        with ui.ZStack(width=total_w, height=_ROW_HEIGHT):
            if is_selected:
                with ui.HStack(width=total_w, height=_ROW_HEIGHT):
                    # The reference keeps selected rows calm; the strip is
                    # retained for selection geometry but toned by style.
                    ui.Rectangle(
                        width=3,
                        height=_ROW_HEIGHT,
                        style_type_name_override="Stage.SelectionAccent",
                    )
                    ui.Spacer()
            with ui.HStack(width=total_w, height=_ROW_HEIGHT):
                if level > 0:
                    ui.Spacer(width=_INDENT_PER_LEVEL * level)
                if has_children:
                    with ui.VStack(width=_INDENT_PER_LEVEL):
                        ui.Spacer()
                        chevron = ui.ImageWithProvider(
                            stage_icons.provider(
                                _CHEVRON_DOWN if expanded else _CHEVRON_RIGHT
                            ),
                            width=_CHEVRON_SIZE,
                            height=_CHEVRON_SIZE,
                            style_type_name_override="Stage.TreeChevron",
                        )
                        if self._expand_toggle_callback is not None:
                            toggle = self._expand_toggle_callback
                            chevron.set_mouse_pressed_fn(
                                lambda x, y, btn, mod, _item=item,
                                _expanded=expanded, _toggle=toggle: (
                                    _toggle(_item, not _expanded)
                                    if btn == 0
                                    else None
                                )
                            )
                        ui.Spacer()
                else:
                    ui.Spacer(width=_INDENT_PER_LEVEL)

    # ── Column headers ───────────────────────────────────────────────────────

    def build_header(self, column_id: Any) -> None:
        # No-op: the Stage widget builds a manual HStack header above the
        # TreeView (see ``StageWidget.build``). The TreeView's internal root
        # node is hidden with ``root_visible=False`` so the model root is the
        # first visible row, while the built-in header remains disabled to
        # keep scroll/hover paints clipped below this manual band.
        return None

    def build_column_header(self, column_widths: Any) -> None:
        """Render the Stage column header as a single flush row.

        ``column_widths`` must mirror the ``column_widths`` passed to the
        TreeView so every header cell aligns with its column body. The
        whole band sits inside a ``ZStack`` + full-bleed ``Rectangle`` bg
        so the chrome reads as one continuous stratum, with a 1-px bottom
        rule right before the first data row.
        """
        with ui.ZStack(height=23):
            ui.Rectangle(style_type_name_override="Stage.ColumnHeader.Bg")
            with ui.VStack(spacing=0):
                with ui.HStack(height=22):
                    # Column 0 — "NAME"
                    with ui.HStack(width=column_widths[0]):
                        ui.Spacer(width=8)
                        ui.Label(
                            "NAME",
                            style_type_name_override="Stage.ColumnHeader",
                            alignment=ui.Alignment.LEFT_CENTER,
                        )
                    # Column 1 — "TYPE"
                    with ui.HStack(width=column_widths[1]):
                        ui.Spacer(width=2)
                        ui.Label(
                            "TYPE",
                            style_type_name_override="Stage.ColumnHeader",
                            alignment=ui.Alignment.LEFT_CENTER,
                        )
                    # Column 2 — eye glyph
                    with ui.HStack(width=column_widths[2]):
                        ui.Spacer()
                        with ui.VStack(width=16):
                            ui.Spacer()
                            ui.ImageWithProvider(
                                stage_icons.provider(stage_icons.eye_on_icon()),
                                width=12, height=12,
                                style_type_name_override="Stage.ColumnHeader.Icon",
                            )
                            ui.Spacer()
                        ui.Spacer(width=4)
                ui.Rectangle(height=1, style_type_name_override="Stage.ColumnHeader.Rule")

    # ── Dispatch ─────────────────────────────────────────────────────────────

    def build_widget(self, model: Any, item: Any, column_id: Any, level: Any, expanded: Any) -> None:
        if item is None:
            return
        if column_id == 0:
            self._build_name_column(model, item)
        elif column_id == 1:
            self._build_type_column(model, item)
        elif column_id == 2:
            self._build_visibility_column(model, item)

    # ── Name column ──────────────────────────────────────────────────────────

    def _build_name_column(self, model: Any, item: Any) -> None:
        if item in self._rename_items and self._rename_controller is not None:
            self._build_rename_field(model, item)
            return

        adapter = model._adapter if isinstance(model, HierarchyModel) else None
        hitem = item if isinstance(item, HierarchyItem) else None

        is_inactive = bool(hitem and adapter and hitem.is_inactive(adapter))
        is_class = bool(hitem and adapter and hitem.is_class_item(adapter))
        is_abstract = bool(hitem and adapter and hitem.is_abstract(adapter))
        is_default = bool(hitem and adapter and hitem.is_default(adapter))
        is_italic = is_class or is_abstract

        category = ""
        if hitem and adapter:
            category = adapter.get_type_category(hitem.adapter_item)

        badge_paths: list[str] = []
        if hitem and adapter and not hitem.is_instance_proxy(adapter):
            badge_paths = stage_icons.badge_icons(hitem.badge_flags(adapter))

        value_model = model.get_item_value_model(item, 0)
        name_text = value_model.as_string if value_model else ""

        label_style = "Stage.Name"
        if is_inactive:
            label_style = "Stage.Name::inactive"
        elif is_italic:
            label_style = "Stage.Name::abstract"

        with ui.HStack(height=_ROW_HEIGHT):
            ui.Spacer(width=2)
            # Icon stack: type icon + optional badges + optional inactive overlay
            with ui.ZStack(width=_TYPE_ICON_SIZE + 2):
                with ui.VStack(width=_TYPE_ICON_SIZE):
                    ui.Spacer()
                    ui.ImageWithProvider(
                        stage_icons.provider(
                            stage_icons.prim_type_icon(category, is_class=is_class)
                        ),
                        width=_TYPE_ICON_SIZE, height=_TYPE_ICON_SIZE,
                        style_type_name_override="Stage.PrimIcon",
                    )
                    ui.Spacer()
                # Badges: bottom-right corner overlay stack
                if badge_paths:
                    with ui.VStack():
                        ui.Spacer()
                        with ui.HStack(height=_BADGE_SIZE):
                            ui.Spacer()
                            for bp in badge_paths:
                                ui.ImageWithProvider(
                                    stage_icons.provider(bp),
                                    width=_BADGE_SIZE, height=_BADGE_SIZE,
                                    style_type_name_override="Stage.Badge",
                                )
                # Inactive overlay: bottom-left, small
                if is_inactive:
                    with ui.VStack():
                        ui.Spacer()
                        with ui.HStack(height=_BADGE_SIZE):
                            ui.ImageWithProvider(
                                stage_icons.provider(stage_icons.active_off_icon()),
                                width=_BADGE_SIZE, height=_BADGE_SIZE,
                                style_type_name_override="Stage.Badge",
                            )
                            ui.Spacer()
            ui.Spacer(width=6)
            label = ui.Label(
                name_text,
                style_type_name_override=label_style,
                alignment=ui.Alignment.LEFT_CENTER,
                width=0,
            )
            if self._rename_controller is not None:
                label.set_mouse_pressed_fn(
                    lambda x, y, btn, mod, i=item, m=model:
                    self._on_name_click(m, i) if btn == 0 else None
                )
            if is_default:
                ui.Spacer(width=6)
                with ui.VStack(width=_DEFAULT_PILL_WIDTH):
                    ui.Spacer()
                    with ui.ZStack(
                        width=_DEFAULT_PILL_WIDTH,
                        height=_DEFAULT_PILL_HEIGHT,
                    ):
                        ui.Rectangle(
                            style_type_name_override="Stage.DefaultPrimPill",
                        )
                        with ui.HStack(height=_DEFAULT_PILL_HEIGHT):
                            ui.Spacer(width=_DEFAULT_PILL_HORIZONTAL_PADDING)
                            ui.Label(
                                _DEFAULT_PILL_LABEL,
                                style_type_name_override="Stage.DefaultPrimPill.Label",
                                alignment=ui.Alignment.CENTER,
                                width=0,
                            )
                            ui.Spacer(width=_DEFAULT_PILL_HORIZONTAL_PADDING)
                    ui.Spacer()
            ui.Spacer()

    def _on_name_click(self, model: Any, item: Any) -> None:
        if self._rename_controller is None:
            return
        if item in model._selected_items:
            self._rename_controller.request_rename_on_click(item)

    def _build_rename_field(self, model: Any, item: Any) -> None:
        value_model = model.get_item_value_model(item, 0)
        current_name = value_model.as_string if value_model else ""
        ctrl = self._rename_controller
        with ui.HStack(height=_ROW_HEIGHT):
            ui.Spacer(width=6)
            field = ui.StringField(style_type_name_override="Stage.RenameField")
            field.model.set_value(current_name)
            self._rename_fields[item] = field

            def on_end_edit(m: Any) -> None:
                if ctrl is not None:
                    ctrl.commit_rename(m.get_value_as_string())

            field.model.add_end_edit_fn(on_end_edit)

            def on_key_pressed(key: int, mod: int, pressed: bool) -> None:
                if pressed and key == _KEY_ESCAPE and ctrl is not None:
                    ctrl.cancel_rename()

            field.set_key_pressed_fn(on_key_pressed)
            focus_keyboard = getattr(field, "focus_keyboard", None)
            if callable(focus_keyboard):
                focus_keyboard()

    # ── Type column ──────────────────────────────────────────────────────────

    def _build_type_column(self, model: Any, item: Any) -> None:
        type_model = model.get_item_value_model(item, 1)
        type_name = (type_model.as_string if type_model else "").lower()
        with ui.HStack(height=_ROW_HEIGHT):
            ui.Spacer(width=2)
            ui.Label(
                type_name,
                style_type_name_override="Stage.TypeLabel",
                alignment=ui.Alignment.LEFT_CENTER,
            )

    # ── Visibility column ────────────────────────────────────────────────────

    def _build_visibility_column(self, model: Any, item: Any) -> None:
        vis_model = model.get_item_value_model(item, 2)
        if vis_model is None:
            return

        adapter = model._adapter if isinstance(model, HierarchyModel) else None
        hitem = item if isinstance(item, HierarchyItem) else None
        sub_key = id(vis_model)
        old_sub = self._visibility_subscriptions.pop(sub_key, None)
        if old_sub is not None:
            unsubscribe = getattr(old_sub, "unsubscribe", None)
            if callable(unsubscribe):
                unsubscribe()

        def can_toggle_now() -> bool:
            is_inactive = bool(hitem and adapter and hitem.is_inactive(adapter))
            return bool(not is_inactive and vis_model.is_enabled())

        def toggle_visibility() -> None:
            if can_toggle_now():
                vis_model.set_value(not vis_model.get_value_as_bool())

        with ui.HStack(height=_ROW_HEIGHT):
            ui.Spacer()
            with ui.VStack(width=20):
                ui.Spacer()
                frame = ui.Frame(
                    width=_VISIBILITY_ICON_SIZE,
                    height=_VISIBILITY_ICON_SIZE,
                )
                if can_toggle_now():
                    frame.opaque_for_mouse_events = True
                    frame.set_mouse_pressed_fn(
                        lambda x, y, btn, mod: toggle_visibility() if btn == 0 else None
                    )

                def build_eye_icon() -> None:
                    is_hidden = vis_model.get_value_as_bool()
                    enabled = can_toggle_now()
                    icon = (
                        stage_icons.eye_off_icon()
                        if is_hidden
                        else stage_icons.eye_on_icon()
                    )
                    name = "hidden" if is_hidden else "visible"
                    if not enabled:
                        name = "disabled"
                    ui.ImageWithProvider(
                        stage_icons.provider(icon),
                        width=_VISIBILITY_ICON_SIZE,
                        height=_VISIBILITY_ICON_SIZE,
                        style_type_name_override="Stage.VisibilityIcon",
                        name=name,
                    )

                frame.set_build_fn(build_eye_icon)

                def rebuild_visibility_icon(_value_model: Any = None) -> None:
                    frame.rebuild()

                self._visibility_subscriptions[sub_key] = (
                    vis_model.subscribe_value_changed_fn(rebuild_visibility_icon)
                )
                ui.Spacer()
            ui.Spacer(width=4)
