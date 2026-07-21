# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Stage browser widget — pure embeddable StageWidget.

See stage browser behavior (Stage Browser) and the stage hierarchy behavior (widget/window
split): this module owns the *widget* side only. It has no knowledge of
``ui.Window``; callers embed it into any ``ui.VStack``/``ui.Frame``
context. The dockable window shell lives in ``ovui_widgets.stage.window`` (Step 8).
"""

from typing import Any, Callable, List, Optional

import omni.ui as ui
from ovui_data_adapters.common import VisibilityState

from ovui_widgets.common.selection import SelectionBus
from ovui_widgets.stage.widget import stage_icons
from ovui_widgets.stage.widget.drop_visual_controller import DropVisualController
from ovui_widgets.stage.widget.hierarchy_model import HierarchyItem, HierarchyModel
from ovui_widgets.stage.widget.rename_controller import RenameController
from ovui_widgets.stage.widget.stage_delegate import _ROW_HEIGHT, StageDelegate

_DEFAULT_VISIBLE_COLUMNS = ["Name", "Type", "Visibility"]

# Retry budget for _restore_expansion. ovui's ``TreeView.set_expanded`` is a
# no-op for items that have not yet been walked during a render, so after a
# rebuild or a set_adapter swap we may need two or three frames before the
# call sticks. Cap retries so a path that never resolves doesn't re-arm
# forever.
_MAX_RESTORE_RETRIES = 5

_COLUMN_HEADER_HEIGHT = 23
_TYPE_COLUMN_WIDTH = 50
_VISIBILITY_COLUMN_WIDTH = 32
_FILTER_BAR_HEIGHT = 30
_FILTER_FIELD_HEIGHT = 22
_FILTER_FIELD_FILL_HEIGHT = 20
_FILTER_FIELD_INNER_HEIGHT = 18
_FILTER_SIDE_MARGIN = 8
_FOOTER_HEIGHT = 20
_FOOTER_SIDE_MARGIN = 6
_FOOTER_PRIM_LABEL_WIDTH = 78
_FOOTER_HIDDEN_LABEL_WIDTH = 112
_MAX_FOCUS_RETRIES = 30
_FOCUS_SETTLE_RETRIES = 2
_FOCUS_CENTER_RATIO = 0.5


class StageWidget:
    """USD stage browser widget backed by a :class:`StageAdapter`.

    Instantiate inside an active ovui layout context — the constructor
    builds the UI immediately into the surrounding ``with`` block::

        with ui.VStack():
            widget = StageWidget(adapter, selection_bus)

    ``selection_bus`` defaults to :meth:`SelectionBus.instance` so the widget
    participates in cross-module selection sync. Pass an explicit bus (or
    ``None`` in a headless pytest that has no singleton) to change that.
    """

    def __init__(
        self,
        adapter: Any = None,
        selection_bus: Optional[SelectionBus] = None,
        config: Any = None,
        visible_columns: Optional[List[str]] = None,
    ) -> None:
        if adapter is None:
            from ovui_widgets.common.testing.mock_stage import MockStageAdapter
            adapter = MockStageAdapter()
        self._adapter = adapter
        self._config = config
        self._visible_columns = list(visible_columns or _DEFAULT_VISIBLE_COLUMNS)
        self._selection_bus: Optional[SelectionBus] = (
            selection_bus if selection_bus is not None else SelectionBus.instance()
        )
        self._model = HierarchyModel(adapter)
        self._delegate = StageDelegate()
        self._delegate.set_expand_toggle_callback(self._on_branch_toggle)
        self._drop_visual = DropVisualController()
        self._rename_controller = RenameController(adapter, self._model, self._delegate)
        self._delegate.set_rename_controller(self._rename_controller)
        self._model.set_rename_controller(self._rename_controller)
        self._model.set_drop_visual_controller(self._drop_visual)
        self._model.set_namespace_selection_remap_callback(self.set_selection)
        self._tree_view: Optional[Any] = None
        self._filter_field: Optional[Any] = None
        self._filter_icon: Optional[Any] = None
        self._filter_clear_button: Optional[Any] = None
        self._filter_clear_container: Optional[Any] = None
        # Design Step 3: the bordered ``Rectangle`` that wraps the search
        # icon, the input, and the clear button. ``name`` is swapped to
        # ``"focused"`` on begin-edit so the ``::focused`` selector fires
        # with the accent-coloured border.
        self._filter_border_rect: Optional[Any] = None
        self._filter_rect: Optional[Any] = None
        self._filter_placeholder: Optional[Any] = None
        self._empty_state_container: Optional[Any] = None
        self._empty_state_label: Optional[Any] = None
        self._footer_prim_label: Optional[Any] = None
        self._footer_hidden_label: Optional[Any] = None
        self._MAX_RESTORE_RETRIES = _MAX_RESTORE_RETRIES
        self._restore_retries: int = _MAX_RESTORE_RETRIES
        self._pending_focus_path: Optional[str] = None
        self._focus_preserve_expanded_paths: set[str] = set()
        self._focus_retries: int = _MAX_FOCUS_RETRIES
        self._focus_settle_retries: int = 0
        self._filter_restore_generation: int = 0
        self._filter_restore_pending: bool = False
        self._model_change_sub: Optional[Any] = None
        self._bus_sub: Optional[Any] = None
        self._footer_adapter_sub: Optional[Any] = None
        # Footer subscriptions whose revocation failed: retained for
        # retry (their callbacks are identity-guarded, so they carry no
        # influence meanwhile).
        self._stale_footer_subs: list = []
        if self._selection_bus is not None:
            self._bus_sub = self._selection_bus.subscribe(self._on_bus_selection_changed)
        self.build()

    # ------------------------------------------------------------------ UI

    def build(self) -> None:
        """Build the widget UI into the current ovui context."""
        with ui.VStack(spacing=0):
            # ── Filter bar (Design Step 3) ────────────────────────────────
            # Two nested ZStacks: the outer one is the panel-width strip
            # with ``Stage.FilterBar`` background; the inner one is the
            # bordered pill (``Stage.FilterField``) that wraps the search
            # icon, a borderless input, and the clear button so the
            # magnifier sits *inside* the field per the reference design.
            with ui.ZStack(height=_FILTER_BAR_HEIGHT):
                ui.Rectangle(style_type_name_override="Stage.FilterBar")
                with ui.HStack():
                    ui.Spacer(width=_FILTER_SIDE_MARGIN)
                    with ui.VStack():
                        ui.Spacer()
                        with ui.ZStack(height=_FILTER_FIELD_HEIGHT):
                            self._filter_border_rect = ui.Rectangle(
                                style_type_name_override="Stage.FilterFieldBorder",
                            )
                            with ui.VStack():
                                ui.Spacer(height=1)
                                with ui.HStack():
                                    ui.Spacer(width=1)
                                    self._filter_rect = ui.Rectangle(
                                        height=_FILTER_FIELD_FILL_HEIGHT,
                                        style_type_name_override="Stage.FilterField",
                                    )
                                    ui.Spacer(width=1)
                                ui.Spacer(height=1)
                            with ui.HStack():
                                ui.Spacer(width=8)
                                with ui.VStack(width=13):
                                    ui.Spacer()
                                    self._filter_icon = ui.ImageWithProvider(
                                        stage_icons.provider(stage_icons.search_icon()),
                                        width=13, height=13,
                                        style_type_name_override="Stage.FilterIcon",
                                    )
                                    ui.Spacer()
                                ui.Spacer(width=6)
                                with ui.VStack():
                                    ui.Spacer()
                                    with ui.ZStack(height=_FILTER_FIELD_INNER_HEIGHT):
                                        self._filter_field = ui.StringField(
                                            style_type_name_override=(
                                                "Stage.FilterFieldInput"
                                            ),
                                            height=_FILTER_FIELD_INNER_HEIGHT,
                                        )
                                        self._filter_placeholder = ui.Label(
                                            "Filter nodes...",
                                            style_type_name_override=(
                                                "Stage.FilterPlaceholder"
                                            ),
                                            alignment=ui.Alignment.LEFT_CENTER,
                                            height=_FILTER_FIELD_INNER_HEIGHT,
                                        )
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
                                # Toggle ``::focused`` on the outer rectangle
                                # as the user edits. ``StringField`` emits
                                # begin/end-edit on its model; the omni.ui
                                # focus selector fires on the input widget,
                                # but the visible border lives on the wrapping
                                # Rectangle, so we mirror the state manually.
                                self._filter_field.model.add_begin_edit_fn(
                                    self._on_filter_begin_edit
                                )
                                self._filter_field.model.add_end_edit_fn(
                                    self._on_filter_end_edit
                                )
                                self._filter_clear_container = ui.VStack(width=18)
                                with self._filter_clear_container:
                                    ui.Spacer()
                                    self._filter_clear_button = ui.ImageWithProvider(
                                        stage_icons.provider(stage_icons.close_icon()),
                                        width=12, height=12,
                                        style_type_name_override=(
                                            "Stage.FilterClearButton.Image"
                                        ),
                                        visible=False,
                                    )
                                    self._filter_clear_button.set_mouse_pressed_fn(
                                        lambda x, y, b, m: (
                                            self._on_filter_clear_clicked()
                                            if b == 0 else None
                                        )
                                    )
                                    ui.Spacer()
                                ui.Spacer(width=8)
                        ui.Spacer()
                    ui.Spacer(width=_FILTER_SIDE_MARGIN)
            ui.Rectangle(height=1, style_type_name_override="Stage.Separator")
            # Column header — built manually above the TreeView. Using the
            # TreeView's built-in ``header_visible=True`` adds an
            # unreachable ~22-px internal gap between the header cell and
            # the first data row. Rendering our own HStack here and
            # keeping ``header_visible=False`` below eliminates that gap;
            # the column widths must mirror ``column_widths`` on the
            # TreeView so the manual header and the auto-laid rows stay
            # aligned.
            # Match Layers' resize contract: the name column stretches to
            # consume all remaining width, while the trailing metadata/icon
            # columns stay fixed and therefore stay anchored to the right edge.
            self._column_widths = [
                ui.Fraction(1),
                ui.Pixel(_TYPE_COLUMN_WIDTH),
                ui.Pixel(_VISIBILITY_COLUMN_WIDTH),
            ]
            self._column_header_height = _COLUMN_HEADER_HEIGHT
            # Keep the manual header in normal layout above the clipped
            # TreeView body. Do not overlay it with a spacer; that steals
            # mouse input from the rows below.
            with ui.VStack(spacing=0):
                with ui.Frame(
                    height=_COLUMN_HEADER_HEIGHT,
                    style={"padding": 0, "margin": 0, "border_width": 0},
                ):
                    self._delegate.build_column_header(self._column_widths)
                with ui.ZStack(height=ui.Fraction(1)):
                    with ui.Frame(
                        height=ui.Fraction(1),
                        clipping=True,
                        style={"padding": 0, "margin": 0, "border_width": 0},
                    ):
                        self._scrolling_frame = ui.ScrollingFrame(
                            style_type_name_override="Stage.ScrollingFrame",
                            horizontal_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_ALWAYS_OFF,
                            vertical_scrollbar_policy=ui.ScrollBarPolicy.SCROLLBAR_AS_NEEDED,
                        )
                        self._scrolling_frame.raster_policy = ui.RasterPolicy.AUTO
                        with self._scrolling_frame:
                            self._tree_view = ui.TreeView(
                                self._model,
                                delegate=self._delegate,
                                root_visible=False,
                                header_visible=False,
                                column_widths=self._column_widths,
                                drop_between_items=True,
                                auto_scroll_selection=False,
                            )
                            # Let the model snapshot expansion from the live
                            # TreeView before each rebuild (see
                            # _snapshot_expansion_from_tree).
                        self._model._tree_view_ref = self._tree_view
                    # Empty-state overlay. Shown when the active filter rejects
                    # every prim or when the stage itself has no children, so
                    # users don't mistake the lone root row for a frozen tree.
                    self._empty_state_container = ui.VStack(visible=False)
                    with self._empty_state_container:
                        ui.Spacer(height=48)
                        self._empty_state_label = ui.Label(
                            "",
                            style_type_name_override="Stage.EmptyState",
                            alignment=ui.Alignment.CENTER_TOP,
                        )
                        ui.Spacer()
            ui.Rectangle(height=1, style_type_name_override="Stage.Footer.Rule")
            with ui.ZStack(height=_FOOTER_HEIGHT):
                ui.Rectangle(style_type_name_override="Stage.Footer")
                with ui.HStack(height=_FOOTER_HEIGHT):
                    ui.Spacer(width=_FOOTER_SIDE_MARGIN)
                    self._footer_prim_label = ui.Label(
                        "",
                        width=ui.Pixel(_FOOTER_PRIM_LABEL_WIDTH),
                        style_type_name_override="Stage.Footer",
                        alignment=ui.Alignment.LEFT_CENTER,
                    )
                    ui.Spacer()
                    self._footer_hidden_label = ui.Label(
                        "",
                        width=ui.Pixel(_FOOTER_HIDDEN_LABEL_WIDTH),
                        style_type_name_override="Stage.Footer",
                        alignment=ui.Alignment.RIGHT_CENTER,
                    )
                    ui.Spacer(width=_FOOTER_SIDE_MARGIN)
            self._tree_view.set_selection_changed_fn(self._on_tree_selection_changed)
            self._model_change_sub = self._model.subscribe_item_changed_fn(
                self._on_model_item_changed
            )
            self._subscribe_footer_counts(self._adapter)
            self._update_empty_state()
            self._refresh_footer_counts()

    # ------------------------------------------------------------ Callbacks

    def _on_filter_changed(self, model: Any) -> None:
        text = model.get_value_as_string()
        preserved_paths = (
            list(self._selection_bus.get_snapshot().paths())
            if self._selection_bus is not None
            else self._model.get_selected_paths()
        )
        self._filter_restore_generation += 1
        generation = self._filter_restore_generation
        self._filter_restore_pending = True
        self._model.set_filter(text)
        has_text = bool(text)
        self._set_filter_chrome_state(has_text)
        self._update_empty_state()
        try:
            from ovui_widgets.common import scheduler as _scheduler

            _scheduler.call_later(
                0.0,
                lambda: self._restore_selection_after_filter(
                    generation,
                    preserved_paths,
                ),
            )
        except RuntimeError:
            self._restore_selection_after_filter(generation, preserved_paths)

    def _restore_selection_after_filter(
        self,
        generation: int,
        preserved_paths: list[str],
    ) -> None:
        if generation != self._filter_restore_generation:
            return
        old_items = list(self._model._selected_items)
        visible_items = [
            item
            for path in preserved_paths
            if (item := self._model.resolve_path(path)) is not None
        ]
        self._model._selection_guard = True
        try:
            self._model._selected_items = visible_items
            if self._tree_view is not None:
                self._tree_view.selection = visible_items
        finally:
            self._model._selection_guard = False
            self._filter_restore_pending = False
        self._refresh_selection_rows(old_items, visible_items)

    def _set_filter_chrome_state(self, has_text: bool) -> None:
        if self._filter_clear_button is not None:
            self._filter_clear_button.visible = has_text
        if self._filter_icon is not None:
            # Swap the provider so the coloured "active" search PNG renders
            # when a filter is set. ``name`` isn't a live-reactive field on
            # ImageWithProvider — the provider swap is the reliable path.
            self._filter_icon.name = "active" if has_text else ""
        if self._filter_placeholder is not None:
            self._filter_placeholder.visible = not has_text

    def _on_filter_clear_clicked(self) -> None:
        if self._filter_field is not None:
            self._filter_field.model.set_value("")

    def _focus_filter_field(self) -> None:
        if self._filter_field is None:
            return
        focus_keyboard = getattr(self._filter_field, "focus_keyboard", None)
        if focus_keyboard is not None:
            focus_keyboard()

    def is_filter_editing(self) -> bool:
        """Return ``True`` while the filter text field owns keyboard input.

        The filter's begin/end-edit callbacks toggle ``_filter_rect.name`` to
        ``"focused"`` for the duration of inline text editing (see
        :meth:`_on_filter_begin_edit` / :meth:`_on_filter_end_edit`). The
        application key dispatcher reads this so a Backspace/Delete that the
        focused filter is already editing does not also fire the destructive
        selection-delete fan-out.
        """
        rect = self._filter_rect
        return rect is not None and rect.name == "focused"

    def _on_filter_begin_edit(self, model: Any) -> None:
        if self._filter_rect is not None:
            self._filter_rect.name = "focused"
        if self._filter_border_rect is not None:
            self._filter_border_rect.name = "focused"

    def _on_filter_end_edit(self, model: Any) -> None:
        if self._filter_rect is not None:
            self._filter_rect.name = ""
        if self._filter_border_rect is not None:
            self._filter_border_rect.name = ""

    def _on_tree_selection_changed(self, items: Any) -> None:
        """Called by TreeView when the user changes the selection."""
        if self._model._selection_guard:
            return
        if self._filter_restore_pending:
            return
        self._rename_controller.cancel_pending_timer()
        old_items = list(self._model._selected_items)
        new_items = [i for i in items if isinstance(i, HierarchyItem)]
        self._model._selected_items = new_items
        paths = self._model.get_selected_paths()
        if self._selection_bus is None:
            self._refresh_selection_rows(old_items, new_items)
            return
        self._model._selection_guard = True
        try:
            self._selection_bus.publish(paths, source="stage")
        finally:
            self._model._selection_guard = False
        self._refresh_selection_rows(old_items, new_items)

    def _on_branch_toggle(self, item: Any, expanded: bool) -> None:
        """Apply a real user chevron gesture without changing selection.

        ovui's implicit TreeView branch handler keeps an ancestor open while a
        selected descendant is visible.  The Stage browser deliberately lets
        users collapse that ancestor while retaining the hidden selection, so
        the rendered chevron owns the gesture and updates both the model's
        path state and the live TreeView explicitly.
        """
        path = self._adapter.get_item_path(item.adapter_item)
        if not path:
            return
        if not expanded:
            pending = self._pending_focus_path
            prefix = f"{path.rstrip('/')}/"
            if pending == path or (pending and pending.startswith(prefix)):
                # A delayed focus retry represents older programmatic intent;
                # the user's collapse must win and must not be reopened on the
                # next frame.
                self._pending_focus_path = None
                self._focus_preserve_expanded_paths.clear()
                self._focus_retries = _MAX_FOCUS_RETRIES
                self._focus_settle_retries = 0
        self._model._set_path_expanded(path, bool(expanded))
        if self._tree_view is not None:
            self._tree_view.set_expanded(item, bool(expanded), False)
        if expanded:
            self._schedule_restore_expansion()

    def _on_bus_selection_changed(self, event: Any) -> None:
        """Called by SelectionBus when selection changes from any source."""
        if event.source == "stage":
            return
        if self._model._selection_guard:
            return
        self._rename_controller.cancel_pending_timer()
        paths = event.snapshot.paths()
        old_items = list(self._model._selected_items)
        items = []
        focus_path: Optional[str] = None
        for p in paths:
            item = self._model.resolve_path(p)
            if item is not None:
                items.append(item)
                self._expand_ancestors(p)
                focus_path = p
        self._model._selection_guard = True
        try:
            self._model._selected_items = items
            if self._tree_view is not None:
                self._tree_view.selection = items
        finally:
            self._model._selection_guard = False
        self._refresh_selection_rows(old_items, items)
        if focus_path is not None:
            self._request_focus_path(focus_path)

    def _refresh_selection_rows(self, old_items: list[Any], new_items: list[Any]) -> None:
        """Rebuild rows whose delegate-only selected chrome changed."""
        seen: set[int] = set()
        for item in [*old_items, *new_items]:
            key = id(item)
            if key in seen:
                continue
            seen.add(key)
            self._model._item_changed(item)

    def _on_model_item_changed(self, model: Any, item: Any) -> None:
        """Fired by the model when items change. Restores expansion on full rebuild.

        The TreeView's ``set_expanded`` is a no-op for items it has not yet
        rendered — the internal expanded set is keyed on object identity
        and only populated once an item has been walked during a render
        pass. Deferring the restore to the next frame lets the TreeView see
        the new items first; the set_expanded calls then land and stick.

        Footer counts are intentionally NOT recomputed here: per-row model
        callbacks must never trigger a stage walk. The footer refreshes
        exactly once per qualifying adapter event through the widget's own
        adapter subscription (see ``_subscribe_footer_counts``), which also
        covers events whose affected prims have no materialized rows.
        """
        if item is None:
            # Whole-tree change (structural rebuild, filter, adapter swap,
            # detach): every surviving row's eye cell rebuilds and
            # re-subscribes on its next build, so the delegate's retained
            # per-row value subscriptions are released here — otherwise
            # rows that never build again (a replaced document's tree,
            # deleted prims) stay owned forever.
            self._delegate.release_visibility_subscriptions()
            self._schedule_restore_expansion()
            self._update_empty_state()

    # ------------------------------------------------- Footer count events

    @staticmethod
    def _is_count_event(event: Any) -> bool:
        """Count-affecting events: topology resyncs and visibility changes."""
        if tuple(getattr(event, "resynced_paths", ()) or ()):
            return True
        if getattr(event, "visibility_delta", None):
            return True
        if getattr(event, "source", None) == "ovstage:visibility":
            return True
        return any(
            str(path).rpartition(".")[2] == "visibility"
            for path in tuple(getattr(event, "changed_paths", ()) or ())
        )

    def _acquire_footer_subscription(self, adapter: Any) -> Any:
        """Acquire (but do not install) a footer subscription for adapter.

        Returns ``(handle, epoch)`` or ``None`` when the adapter exposes
        no subscription surface. The callback stays inert until
        :meth:`_install_footer_subscription` commits its epoch.
        """
        if adapter is None:
            return None
        subscribe = getattr(adapter, "subscribe_changes", None)
        if not callable(subscribe):
            return None
        stale = getattr(self, "_stale_footer_subs", None) or []
        remaining = []
        for handle in stale:
            try:
                handle.cancel()
            except BaseException:  # noqa: BLE001 — retained for retry
                remaining.append(handle)
        self._stale_footer_subs = remaining
        if len(remaining) >= 32:
            raise RuntimeError(
                "stage footer swap refused: too many footer "
                "subscriptions with failed cancellation are retained; "
                "retry after revocation succeeds"
            )
        footer_epoch = object()

        def _on_count_event(event: Any, _epoch: Any = footer_epoch) -> None:
            if getattr(self, "_footer_epoch", None) is not _epoch:
                return
            if not self._is_count_event(event):
                return
            self._refresh_footer_counts()

        return (subscribe(_on_count_event), footer_epoch)

    def _install_footer_subscription(self, acquired: Any) -> None:
        """Commit an acquired footer subscription, revoking the old one."""
        self._subscribe_footer_counts(None)   # cancel/retain the old
        if acquired is None:
            return
        handle, footer_epoch = acquired
        self._footer_adapter_sub = handle
        self._footer_epoch = footer_epoch

    def _release_footer_subscription(self, acquired: Any) -> None:
        """Discard an acquired-but-never-installed footer subscription."""
        if acquired is None:
            return
        handle, _footer_epoch = acquired
        try:
            handle.cancel()
        except BaseException:  # noqa: BLE001 — retained for retry
            stale = getattr(self, "_stale_footer_subs", None)
            if stale is None:
                stale = self._stale_footer_subs = []
            stale.append(handle)

    def _subscribe_footer_counts(self, adapter: Any) -> None:
        old = getattr(self, "_footer_adapter_sub", None)
        if old is not None:
            cancel = getattr(old, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except BaseException:  # noqa: BLE001 — retained for retry
                    # A failed revocation must never abort the swap or
                    # detach; the handle stays owned for later retry (its
                    # callback is identity-guarded, so it has no
                    # influence meanwhile).
                    stale = getattr(self, "_stale_footer_subs", None)
                    if stale is None:
                        stale = self._stale_footer_subs = []
                    stale.append(old)
            self._footer_adapter_sub = None
        remaining = []
        for handle in getattr(self, "_stale_footer_subs", ()):
            try:
                handle.cancel()
            except BaseException:  # noqa: BLE001 — retained for retry
                remaining.append(handle)
        self._stale_footer_subs = remaining
        if adapter is None:
            return
        subscribe = getattr(adapter, "subscribe_changes", None)
        if not callable(subscribe):
            return

        footer_epoch = object()
        self._footer_epoch = footer_epoch

        def _on_count_event(event: Any, _epoch: Any = footer_epoch) -> None:
            # EPOCH guard: a late callback from a replaced subscription
            # must never recompute counts — not even when the same
            # adapter object is installed again later.
            if getattr(self, "_footer_epoch", None) is not _epoch:
                return
            if not self._is_count_event(event):
                return
            self._refresh_footer_counts()

        self._footer_adapter_sub = subscribe(_on_count_event)

    def _refresh_footer_counts(self) -> None:
        """Refresh the pinned footer using live adapter hierarchy data."""
        prim_label = getattr(self, "_footer_prim_label", None)
        hidden_label = getattr(self, "_footer_hidden_label", None)
        if prim_label is None or hidden_label is None:
            return
        prim_count, hidden_count = self._compute_stage_counts()
        prim_label.text = (
            f"{prim_count:,} {'prim' if prim_count == 1 else 'prims'}"
        )
        hidden_label.text = f"USD · {hidden_count:,} hidden"

    def _compute_stage_counts(self) -> tuple[int, int]:
        """Return ``(total_prims, hidden_prims)`` from the current adapter."""
        if self._adapter is None:
            return 0, 0  # explicit no-document state
        total = 0
        hidden = 0
        stack = [self._adapter.get_root()]
        while stack:
            item = stack.pop()
            total += 1
            if self._adapter.compute_visibility(item) is not VisibilityState.VISIBLE:
                hidden += 1
            stack.extend(reversed(self._adapter.get_children(item)))
        return total, hidden

    def _update_empty_state(self) -> None:
        """Show the overlay when the filter rejects everything or the stage is empty.

        The TreeView always paints the model root row (the internal TreeView
        root is hidden with ``root_visible=False``), so a filter that matches
        nothing leaves a lone root row on screen with no explanation. The
        overlay labels that state explicitly.
        """
        # Defensive: ``test_step26_open_file`` builds a StageWidget with
        # ``__new__`` and only installs the attributes it exercises, so
        # ``_empty_state_container`` may be missing entirely.
        container = getattr(self, "_empty_state_container", None)
        label = getattr(self, "_empty_state_label", None)
        if container is None or label is None:
            return
        filter_text = ""
        if self._filter_field is not None:
            filter_text = self._filter_field.model.get_value_as_string()
        root_children = self._model.get_item_children(self._model._root)
        should_show = len(root_children) == 0
        container.visible = should_show
        if should_show:
            if filter_text:
                label.text = f"No prims match '{filter_text}'"
            else:
                label.text = "Stage is empty"

    def _restore_expansion(self) -> None:
        """Re-expand items whose paths are in _expanded_paths after a tree rebuild.

        ``_on_adapter_changed`` clears ``_path_cache`` as part of the full
        rebuild, so we can't look up items by path from the cache here —
        ``HierarchyModel.resolve_path`` walks from the root and populates the
        cache on the way down, which is what lets us reach items that are
        still collapsed after the rebuild.

        The TreeView's ``set_expanded`` is a no-op for items it has not yet
        rendered — if any item still reads as collapsed after this pass
        re-arm for the next frame so the call lands once the TreeView has
        walked the new items. ``set_expanded`` is idempotent, so repeated
        invocations are safe.
        """
        if self._tree_view is None or not self._model._expanded_paths:
            return
        any_not_stuck = False
        # Shallow paths first so ancestors are expanded (and their children
        # loaded) before the resolver tries to walk through them.
        for path in sorted(self._model._expanded_paths, key=lambda p: p.count("/")):
            item = self._model.resolve_path(path)
            if item is None:
                continue
            self._tree_view.set_expanded(item, True, False)
            if not self._tree_view.is_expanded(item):
                any_not_stuck = True
        if any_not_stuck and self._restore_retries > 0:
            self._restore_retries -= 1
            self._schedule_restore_expansion()
        else:
            self._restore_retries = self._MAX_RESTORE_RETRIES
        if self._pending_focus_path is not None:
            self._schedule_focus_path()

    # ----------------------------------------------------------- Public API

    def set_adapter(self, adapter: Any) -> None:
        """Replace the current adapter and rebuild the tree model.

        The model swap runs FIRST and is transactional: if the new
        adapter cannot be subscribed, the widget still points at the old
        adapter with its live hierarchy and footer subscriptions.
        """
        # EVERYTHING fallible is acquired FIRST: the new footer
        # subscription, then the transactional model swap. Any
        # acquisition failure leaves the widget entirely on the old
        # document with complete wiring.
        new_footer = self._acquire_footer_subscription(adapter)
        pending_throwable: BaseException | None = None
        try:
            self._model.set_adapter(adapter)
        except BaseException as exc:
            if getattr(self._model, "_adapter", None) is not adapter:
                # Transactional failure: release the acquired footer
                # subscription (retained on a failed revocation) and
                # change nothing anywhere.
                self._release_footer_subscription(new_footer)
                raise
            # The model COMPLETED its swap and re-raised (retained old
            # handle): complete every remaining widget layer too, so no
            # consumer splits across documents, then re-raise the primary.
            pending_throwable = exc
        self._adapter = adapter
        self._rename_controller = RenameController(adapter, self._model, self._delegate)
        self._delegate.set_rename_controller(self._rename_controller)
        self._model.set_rename_controller(self._rename_controller)
        self._install_footer_subscription(new_footer)
        self._update_empty_state()
        self._refresh_footer_counts()
        if pending_throwable is not None:
            raise pending_throwable

    def detach_document(self) -> None:
        """Converge the widget to the explicit NO-DOCUMENT state.

        Hierarchy and footer subscriptions are revoked (or retained for
        retry), no stale row remains resolvable, and the tree presents
        empty until a new adapter installs.
        """
        self._subscribe_footer_counts(None)
        pending_throwable: BaseException | None = None
        try:
            self._model.detach_document()
        except BaseException as exc:
            if getattr(self._model, "_adapter", None) is not None:
                raise
            # The model COMPLETED its detach and re-raised: complete the
            # widget's detach too — no layer may stay on the old document.
            pending_throwable = exc
        self._adapter = None
        self._update_empty_state()
        self._refresh_footer_counts()
        if pending_throwable is not None:
            raise pending_throwable

    def get_adapter(self) -> Any:
        return self._adapter

    def get_selection(self) -> List[str]:
        """Return the stage paths currently selected in the widget."""
        if self._selection_bus is not None:
            paths = list(self._selection_bus.get_snapshot().paths())
            return [
                path
                for path in paths
                if self._adapter.get_item_at_path(path) is not None
            ]
        return self._model.get_selected_paths()

    def set_selection(self, paths: List[str]) -> None:
        """Replace the widget's selection with the given list of stage paths.

        Expands ancestors of each path so the selection lands on rows the
        user can actually see. Publishes through the SelectionBus (if one is
        attached) so peer widgets stay in sync. Paths that don't resolve in
        the adapter are dropped silently.
        """
        items: List[HierarchyItem] = []
        resolved_paths: List[str] = []
        for p in paths:
            item = self._model.resolve_path(p)
            if item is None:
                continue
            # Auto-expand ancestors so the selection highlight is visible
            # and doesn't hide behind a collapsed branch.
            self._expand_ancestors(p)
            items.append(item)
            resolved_paths.append(self._adapter.get_item_path(item.adapter_item))
        old_items = list(self._model._selected_items)
        self._model._selected_items = items
        if self._tree_view is not None:
            self._tree_view.selection = items
        self._refresh_selection_rows(old_items, items)
        if items:
            self._request_focus_path(
                self._adapter.get_item_path(items[-1].adapter_item)
            )
        if self._selection_bus is not None:
            self._selection_bus.publish(resolved_paths, source="stage")

    def _expand_ancestors(self, path: str) -> None:
        """Expand every ancestor of ``path`` so the row is visually reachable."""
        if not hasattr(self, "_focus_preserve_expanded_paths"):
            self._focus_preserve_expanded_paths = set()
        root_path = self._adapter.get_item_path(self._model._root.adapter_item)
        root_parts = [p for p in root_path.split("/") if p]
        parts = [p for p in path.split("/") if p]
        if parts[: len(root_parts)] != root_parts:
            return
        walk = parts[len(root_parts):]
        if not walk:
            return
        current = root_path
        # Expand the root itself (TreeView keeps it collapsed until asked).
        self._set_expanded(current, True, False)
        self._focus_preserve_expanded_paths.add(current)
        # Stop before the final segment — it is the target, not an ancestor.
        for seg in walk[:-1]:
            current = f"{current.rstrip('/')}/{seg}"
            self._set_expanded(current, True, False)
            self._focus_preserve_expanded_paths.add(current)

    def filter_by_text(self, text: str) -> None:
        """Apply a name-based text filter. Empty string clears the filter."""
        self._model.set_filter(text)
        if self._filter_field is not None:
            self._filter_field.model.set_value(text)

    def set_visible_columns(self, names: List[str]) -> None:
        """Store the set of visible column names.

        Full column wiring lands with the ColumnDelegateRegistry in Step 9;
        until then this call records the preference without rebuilding.
        """
        self._visible_columns = list(names)

    def get_visible_columns(self) -> List[str]:
        return list(self._visible_columns)

    def scroll_to(self, path: str) -> None:
        """Ensure the item at ``path`` is reachable and near the view center."""
        if not path or path == "/":
            return
        self._expand_ancestors(path)
        self._request_focus_path(path)

    def expand(self, path: str, recursive: bool = False) -> None:
        """Expand the tree item at ``path`` (and optionally its descendants)."""
        self._set_expanded(path, expanded=True, recursive=recursive)

    def collapse(self, path: str, recursive: bool = False) -> None:
        """Collapse the tree item at ``path`` (and optionally its descendants)."""
        self._set_expanded(path, expanded=False, recursive=recursive)

    def _set_expanded(self, path: str, expanded: bool, recursive: bool) -> None:
        # resolve_path walks from the root, lazy-loading children so the
        # caller can address a never-rendered path (tree just mounted, or
        # ancestors still collapsed) without first having to scroll it into
        # view. Without that, expand("/World/Geo/Sphere") was a silent no-op
        # until the user manually revealed each ancestor.
        item = self._model.resolve_path(path)
        if item is None:
            return
        self._model._set_path_expanded(path, expanded)
        if self._tree_view is not None:
            self._tree_view.set_expanded(item, expanded, recursive)
        # The TreeView only remembers expansion for items it has already
        # rendered; a set_expanded on a just-resolved item can land on
        # nothing. Re-apply on the next frame so the TreeView has a chance
        # to walk the item first. Cheap and idempotent.
        if expanded:
            self._schedule_restore_expansion()

    def _schedule_restore_expansion(self) -> None:
        try:
            from ovui_widgets.common import scheduler as _scheduler
            _scheduler.call_later(0.0, self._restore_expansion)
        except RuntimeError:
            self._restore_expansion()

    def _request_focus_path(self, path: str) -> None:
        """Focus ``path`` in the Stage tree after external selection changes.

        ``TreeView.selection`` is intentionally not enough here: the C++ tree
        only auto-scrolls on a changed single-selection. Viewport picks can
        publish the same selection repeatedly, and marquee/shift selection
        publishes multiple paths. The Stage window still needs to reveal the
        last selected prim every time.
        """
        if not path or path == "/":
            return
        self._pending_focus_path = path
        self._focus_retries = _MAX_FOCUS_RETRIES
        self._focus_settle_retries = _FOCUS_SETTLE_RETRIES
        self._apply_pending_focus()

    def _schedule_focus_path(self) -> bool:
        try:
            from ovui_widgets.common import scheduler as _scheduler
            _scheduler.call_later(0.0, self._apply_pending_focus)
            return True
        except RuntimeError:
            # Isolated widget tests have no application scheduler. They still
            # get the synchronous focus attempt from _request_focus_path().
            return False

    def _apply_pending_focus(self) -> None:
        path = self._pending_focus_path
        if not path:
            return
        item = self._model.resolve_path(path)
        if item is None:
            self._pending_focus_path = None
            getattr(self, "_focus_preserve_expanded_paths", set()).clear()
            return
        self._expand_ancestors(path)
        if self._tree_view is not None:
            self._model._selection_guard = True
            try:
                self._tree_view.selection = list(self._model._selected_items)
            finally:
                self._model._selection_guard = False
        scroll_stable = self._scroll_path_near_center(path)
        if scroll_stable:
            if self._focus_settle_retries > 0 and self._schedule_focus_path():
                self._focus_settle_retries -= 1
                return
            self._pending_focus_path = None
            getattr(self, "_focus_preserve_expanded_paths", set()).clear()
            self._focus_retries = _MAX_FOCUS_RETRIES
            self._focus_settle_retries = 0
            return
        if self._focus_retries > 0:
            self._focus_retries -= 1
            self._schedule_focus_path()
        else:
            self._pending_focus_path = None
            getattr(self, "_focus_preserve_expanded_paths", set()).clear()
            self._focus_retries = _MAX_FOCUS_RETRIES
            self._focus_settle_retries = 0

    def _scroll_path_near_center(self, path: str) -> bool:
        frame = getattr(self, "_scrolling_frame", None)
        if frame is None:
            return False
        row_info = self._visible_row_position(path)
        if row_info is None:
            return False
        row_index, visible_count = row_info
        row_top = float(row_index * _ROW_HEIGHT)
        row_height = float(_ROW_HEIGHT)
        try:
            viewport_height = float(getattr(frame, "computed_height", 0.0) or 0.0)
        except (TypeError, ValueError):
            viewport_height = 0.0
        try:
            max_scroll = float(getattr(frame, "scroll_y_max", 0.0) or 0.0)
        except (TypeError, ValueError):
            max_scroll = 0.0

        if viewport_height > 0:
            center_offset = max(viewport_height - row_height, 0.0) * _FOCUS_CENTER_RATIO
            target_scroll = row_top - center_offset
            total_height = float(visible_count * _ROW_HEIGHT)
        else:
            target_scroll = row_top
            total_height = 0.0

        target_scroll = max(0.0, target_scroll)
        if max_scroll > 0:
            target_scroll = min(target_scroll, max_scroll)
        elif viewport_height > 0 and total_height <= viewport_height:
            target_scroll = 0.0

        try:
            frame.scroll_y = target_scroll
        except (AttributeError, TypeError, ValueError, RuntimeError):
            return False

        # A zero max while the content is taller than the viewport usually
        # means layout has not published scroll bounds yet; retry next frame.
        if max_scroll <= 0.0 and viewport_height > 0 and total_height > viewport_height:
            return False
        return True

    def _visible_row_position(self, path: str) -> Optional[tuple[int, int]]:
        snapshot = getattr(self._model, "_snapshot_expansion_from_tree", None)
        if callable(snapshot) and path != self._pending_focus_path:
            snapshot()
            # Programmatic focus first expands ancestors in the model, then
            # TreeView catches up over later frames. A live snapshot taken
            # before those rows are rendered can report them as collapsed;
            # preserve the ancestors requested by the focus/scroll operation
            # so public APIs like scroll_to() do not erase their own work.
            self._model._expanded_paths.update(
                getattr(self, "_focus_preserve_expanded_paths", set())
            )

        rows: list[str] = []
        target_index: Optional[int] = None

        def walk(parent: Any) -> None:
            nonlocal target_index
            for child in self._model.get_item_children(parent):
                child_path = self._adapter.get_item_path(child.adapter_item)
                if target_index is None and child_path == path:
                    target_index = len(rows)
                rows.append(child_path)
                if child_path in self._model._expanded_paths:
                    walk(child)

        walk(None)
        if target_index is None:
            return None
        return target_index, len(rows)

    def subscribe_selection_changed(
        self, callback: Callable[[List[str]], None]
    ) -> Any:
        """Subscribe to selection changes emitted by the widget.

        Thin wrapper over :class:`SelectionBus` so callers don't need to
        reach past the widget boundary. Returns ``None`` if the widget is
        running headless without a bus.
        """
        if self._selection_bus is None:
            return None
        return self._selection_bus.subscribe(
            lambda event: callback(list(event.snapshot.paths()))
        )

    # -------------------------------------------------------------- F2 handoff

    def begin_rename_selected(self) -> None:
        """Trigger inline rename on the first selected item (keyboard F2 shortcut)."""
        if not self._model._selected_items:
            return
        item = self._model._selected_items[0]
        if self._rename_controller is not None:
            self._rename_controller.request_rename_f2(item)

    # -------------------------------------------------------------- Lifecycle

    def destroy(self) -> None:
        """Release bus subscription and model references.

        Every revocation is BaseException-safe: a failing cancellation is
        re-raised only AFTER the remaining teardown completed, so a
        destroyed widget can never stay operative.
        """
        pending_throwable: BaseException | None = None
        if self._bus_sub is not None:
            try:
                self._bus_sub.cancel()
            except BaseException as exc:  # noqa: BLE001 — teardown first
                # RETAIN the handle: revocation ownership survives until
                # a retried destroy() confirms the cancellation, so a
                # live bus callback can never be silently dropped.
                pending_throwable = exc
            else:
                self._bus_sub = None
        try:
            self._model.detach_document()
        except BaseException as exc:  # noqa: BLE001 — teardown first
            if pending_throwable is None:
                pending_throwable = exc
        self._adapter = None
        self._subscribe_footer_counts(None)
        self._delegate.release_visibility_subscriptions()
        self._pending_focus_path = None
        getattr(self, "_focus_preserve_expanded_paths", set()).clear()
        self._model_change_sub = None
        self._tree_view = None
        self._scrolling_frame = None
        self._filter_field = None
        self._footer_prim_label = None
        self._footer_hidden_label = None
        if pending_throwable is not None:
            raise pending_throwable
