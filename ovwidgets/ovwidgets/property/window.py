# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Property inspector window.

Dockable window that hosts a stack of
:class:`ovwidgets.property.widget.PropertyWidget` sections. The window owns the
filter bar and the scrollable container; each widget returned by
:class:`~ovwidgets.property.widget.PropertySchemeRegistry` for the current
payload's scheme contributes its own content via
:meth:`PropertyWidget.build_items`.

Renamed from ``property_widget.py`` in the property inspector step 6.1: the
class formerly known as ``PropertyWidget`` is now :class:`PropertyWindow`.
A DEPRECATED ``PropertyWidget`` alias is re-exported from
:mod:`ovwidgets.property` for one release cycle so existing callers (notably
:class:`ovwidgets.app.application.Application`) keep working. The new abstract
:class:`ovwidgets.property.widget.PropertyWidget` base is the class Step 6.2 +
onwards subclasses.

Step 6.2 of the property inspector implementation moved the group-tree build + row dispatch
into :class:`~ovwidgets.property.widget.AttributesWidget`. Step 6.5 hoisted
widget registration out of the window and into the process-wide
:class:`PropertySchemeRegistry`; :meth:`_rebuild_content` now asks the
registry for the widget list matching the payload's scheme (merged
with the ``"default"`` scheme's catch-all entries) on every rebuild.
The window keeps :attr:`_default_attributes` as an instance attribute
for the five thin delegates below (``_compute_display_group`` /
``_build_groups`` / ``_build_group_children`` / ``_build_attribute_row``
/ ``_show_group_context_menu``) — those delegates are preserved for
existing callers (principally ``tests/test_property_filter.py`` and
``tests/test_group_context_menu.py`` which exercise the group build
through the window surface) and will be removed once the test
harnesses migrate to the widget API. The registry-produced widgets
are ephemeral: a fresh :class:`AttributesWidget` is constructed per
rebuild, bound to ``self`` via :meth:`AttributesWidget.set_window`,
and discarded after ``build_items``. Shared state (adapter, filter,
group-collapse map) lives on the window so the ephemerality is harmless.
"""

from typing import Any, Dict, List, NamedTuple, Optional

import omni.ui as ui
from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovwidgets.common.managed_window import ManagedWindow
from ovwidgets.common.selection import SelectionBus
from ovwidgets.common.style.urls import _STYLE_ICON_PATHS
from ovwidgets.property.group_widget import FIT_CONTENT_HEIGHT, GROUP_STACK_SPACING
from ovwidgets.property.parts import UiDisplayGroup
from ovwidgets.property.payload import PropertyPayload
from ovwidgets.property.style import PROPERTY_STYLES
from ovwidgets.property.widget import (
    AttributesWidget,
    PropertySchemeRegistry,
    PropertyWidget,
    ScrollPreserver,
)

# Filter-bar chrome icon providers. The standalone ``omni.ui`` build routes
# ``ui.Image(source_url)`` through ``stb_image`` which rejects SVG, so the
# raster ``.png`` variants that ``ovwidgets.stage`` already ships are re-used
# through a tiny module-scoped cache. See ``ovwidgets.stage.widget.stage_icons``
# for the original pattern — duplicated here rather than cross-imported
# to keep Property → Stage direction dependency-free.
_FILTER_ICON_CACHE: Dict[str, Any] = {}


def _filter_icon_provider(name: str) -> Any:
    prov = _FILTER_ICON_CACHE.get(name)
    if prov is None:
        prov = ui.RasterImageProvider(_STYLE_ICON_PATHS[name])
        _FILTER_ICON_CACHE[name] = prov
    return prov


class _SelectionHeaderInfo(NamedTuple):
    prim_type: str
    name: str
    path: str


_SELECTION_HEADER_HEIGHT = 76
_SELECTION_HEADER_SIDE_PADDING = 10
_SELECTION_HEADER_TOP_PADDING = 8
_SELECTION_HEADER_BOTTOM_PADDING = 12
_SELECTION_HEADER_LINE_GAP = 2
_SELECTION_HEADER_SMALL_LINE_HEIGHT = 14
_SELECTION_HEADER_TITLE_LINE_HEIGHT = 24
_FILTER_TO_FIRST_GROUP_SPACING = 6


class PropertyWindow(ManagedWindow):
    """USD property inspector panel with filter bar and scrollable content."""

    # Step 7.4: default threshold at which the selection is "large" and
    # the full attribute build is suppressed in favour of a banner +
    # override button. Matches :meth:`PropertyPayload.is_large_selection`
    # default. Exposed as a class-level attribute so bypass-``__init__``
    # tests and future per-instance overrides can read it without
    # requiring the ``__init__`` to run.
    _large_selection_threshold: int = 100
    # Step 7.4: "ignore threshold" flag. Starts False; flipped by
    # :meth:`_on_ignore_threshold_clicked` when the user clicks the
    # banner's "Load Anyway" button; reset back to False in
    # :meth:`set_selection` whenever the selection actually changes
    # (new payload), so the next large selection hits the gate again
    # rather than silently inheriting the prior override. Class-level
    # default keeps headless bypass-``__init__`` tests compatible.
    _large_selection_override: bool = False
    # Bug 12: deferred-rebuild handle for bus-driven selection changes.
    # Class-level default keeps headless bypass-``__init__`` tests (which
    # reach ``_on_bus_selection_changed`` via ``set_selection`` only)
    # compatible without every factory having to seed the attribute.
    _pending_selection_rebuild_handle: Optional[Any] = None
    # Bug 12: set to ``True`` for the duration of
    # :meth:`_on_bus_selection_changed` so :meth:`set_selection` knows
    # to defer the content rebuild out of the synchronous bus publish
    # instead of tearing down every row inline. Direct callers of
    # :meth:`set_selection` never flip this, so they keep the
    # pre-Bug-12 synchronous-rebuild contract.
    _in_bus_callback: bool = False

    def __init__(self) -> None:
        self._adapter: Optional[PropertyAdapter] = None
        self._selection: List[str] = []
        self._filter_text = ""
        self._pending_filter_handle: Optional[Any] = None
        self._filter_field: Optional[Any] = None
        # Filter-bar chrome (Step QA-polish). Mirrors the Stage filter
        # bar: ``_filter_icon`` is the vertically-centred magnifier
        # glyph, ``_filter_clear_button`` is the "x" inside a 20-px
        # trailing slot, and ``_filter_clear_container`` is the VStack
        # that holds the button between two Spacers so the icon hits
        # the row's centreline.
        self._filter_icon: Optional[Any] = None
        self._filter_clear_container: Optional[Any] = None
        self._filter_clear_button: Optional[Any] = None
        # Design Step 3: the bordered ``Rectangle`` that wraps the
        # icon + input + clear button. ``name`` is swapped to ``"focused"``
        # on begin-edit so the ``::focused`` named variant's border-colour
        # fires, mirroring ``StageWidget._filter_rect``.
        self._filter_border_rect: Optional[Any] = None
        self._filter_rect: Optional[Any] = None
        self._filter_placeholder: Optional[Any] = None
        self._content: Optional[Any] = None
        # Step 7.3: the outer ``ui.ScrollingFrame`` that wraps
        # ``_content``. Captured in :meth:`_build_ui` so the
        # :class:`ScrollPreserver` can read/write ``scroll_y`` across
        # rebuilds. ``None`` until the UI is built.
        self._scroll_frame: Optional[Any] = None
        self._group_collapse_state: Dict[str, bool] = {}
        # Step 5.3: keep the most recently shown group-header context menu
        # alive until the next one pops. ``ui.Menu`` is destroyed when its
        # last Python reference drops, so dropping the handle here would
        # close the popup mid-frame.
        self._active_context_menu: Optional[Any] = None
        self._bus_sub: Optional[Any] = None
        self._stage_adapter: Optional[Any] = None
        self._stage_change_sub: Optional[Any] = None
        self._undo_manager_ref: Optional[Any] = None
        self._adapter_factory: Optional[Any] = None
        # Step 6.1: local widget list for ad-hoc per-window
        # registrations via :meth:`register_widget`. Step 6.5 moved
        # the default :class:`AttributesWidget` registration out of
        # this list and into the process-wide
        # :class:`PropertySchemeRegistry` (scheme ``"default"``) — so
        # ``_widgets`` starts empty and is NOT iterated during rebuild.
        # The field exists for back-compat with
        # :meth:`register_widget` / :meth:`unregister_widget` callers
        # (e.g. third-party code that wants a window-scoped widget
        # without taking a slot in the global registry).
        self._widgets: List[PropertyWidget] = []
        # Step 6.2: the default catch-all attributes widget is still
        # constructed here so the five thin delegate methods below
        # (``_compute_display_group`` etc. — preserved for tests in
        # ``test_property_filter.py`` and ``test_group_context_menu.py``)
        # have a bound instance to forward to. This instance is
        # completely separate from the registry-produced ones that
        # actually render in :meth:`_build_registered_widgets`.
        self._default_attributes: Optional[AttributesWidget] = None
        # Step 7.3: preserve scroll position across rebuilds when the
        # new selection's scheme matches the prior one's. Instantiated
        # before :meth:`super().__init__` triggers the first build so
        # the very first :meth:`_rebuild_content` call can safely
        # invoke save/restore (both are no-ops on the first pass —
        # ``_scroll_frame`` is ``None`` until ``_build_ui`` runs, and
        # the preserver handles that gracefully).
        self._scroll_preserver: Optional[ScrollPreserver] = None
        # Step 7.4: per-instance copy of the override flag so mutations
        # from :meth:`_on_ignore_threshold_clicked` do not accidentally
        # shadow the class-level default in a way a reader would find
        # surprising. The class-level attribute still backs lookups for
        # bypass-``__init__`` instances; the instance copy here is the
        # canonical state for a running window.
        self._large_selection_override = False
        # Bug 12: same shadow-the-class-default pattern as the override
        # flag above. Concrete instance attribute so cancels in
        # :meth:`destroy` and reschedules in :meth:`_schedule_deferred_rebuild`
        # never accidentally create a write that only lives on the class.
        self._pending_selection_rebuild_handle = None
        super().__init__("Property Inspector", width=350, height=600)
        self._bus_sub = SelectionBus.instance().subscribe(self._on_bus_selection_changed)
        self._default_attributes = AttributesWidget(self)

    def _get_module_styles(self) -> dict:
        return PROPERTY_STYLES

    def _build_ui(self) -> None:
        with ui.VStack(spacing=0):
            self._scroll_frame = ui.ScrollingFrame(
                style_type_name_override="Property.Scroll"
            )
            with self._scroll_frame:
                self._content = ui.VStack(
                    spacing=0,
                    height=FIT_CONTENT_HEIGHT,
                )
        # Step 7.3: wire the scroll preserver now that ``_scroll_frame``
        # exists. DI ``common.scheduler.call_later`` so tests that bypass
        # :meth:`_build_ui` can inject a synchronous stub. The first
        # ``_rebuild_content`` below will exercise save/restore once.
        from ovwidgets.common import scheduler as _scheduler
        self._scroll_preserver = ScrollPreserver(
            frame_getter=lambda: self._scroll_frame,
            call_later=_scheduler.call_later,
        )
        self._rebuild_content()

    def _on_filter_changed(self, model: Any) -> None:
        text = model.get_value_as_string()
        # Toggle the clear-button + icon active-state synchronously so
        # the chrome responds immediately — the filter itself is still
        # debounced through ``common.scheduler.call_later`` to avoid a
        # rebuild per keystroke.
        has_text = bool(text)
        self._set_filter_chrome_state(has_text)
        if self._pending_filter_handle is not None:
            self._pending_filter_handle.cancel()
            self._pending_filter_handle = None
        from ovwidgets.common import scheduler as _scheduler
        self._pending_filter_handle = _scheduler.call_later(
            0.15, lambda: self._apply_filter(text)
        )

    def _set_filter_chrome_state(self, has_text: bool) -> None:
        clear_btn = getattr(self, "_filter_clear_button", None)
        if clear_btn is not None:
            clear_btn.visible = has_text
        filter_icon = getattr(self, "_filter_icon", None)
        if filter_icon is not None:
            filter_icon.name = "active" if has_text else ""
        placeholder = getattr(self, "_filter_placeholder", None)
        if placeholder is not None:
            placeholder.visible = not has_text

    def _build_filter_bar(self) -> None:
        """Build the Property filter pill below the selected-object header."""
        # Mirrors the previous filter chrome while placing it in the scroll
        # content flow so the selected object remains the first visual group.
        with ui.ZStack(height=30):
            ui.Rectangle(style_type_name_override="Property.FilterBackground")
            with ui.HStack():
                ui.Spacer(width=6)
                with ui.VStack():
                    ui.Spacer()
                    with ui.ZStack(height=22):
                        self._filter_border_rect = ui.Rectangle(
                            style_type_name_override="Property.SearchFieldBorder",
                        )
                        with ui.VStack():
                            ui.Spacer(height=1)
                            with ui.HStack():
                                ui.Spacer(width=1)
                                self._filter_rect = ui.Rectangle(
                                    height=20,
                                    style_type_name_override="Property.SearchField",
                                )
                                ui.Spacer(width=1)
                            ui.Spacer(height=1)
                        with ui.HStack():
                            ui.Spacer(width=8)
                            with ui.VStack(width=13):
                                ui.Spacer()
                                self._filter_icon = ui.ImageWithProvider(
                                    _filter_icon_provider("stage_search"),
                                    width=13,
                                    height=13,
                                    style_type_name_override="Property.FilterIcon",
                                )
                                ui.Spacer()
                            ui.Spacer(width=6)
                            with ui.VStack():
                                ui.Spacer()
                                with ui.ZStack(height=18):
                                    self._filter_field = ui.StringField(
                                        style_type_name_override=(
                                            "Property.SearchFieldInput"
                                        ),
                                        height=18,
                                    )
                                    if self._filter_text:
                                        self._filter_field.model.set_value(
                                            self._filter_text
                                        )
                                    self._filter_placeholder = ui.Label(
                                        "Filter properties...",
                                        style_type_name_override=(
                                            "Property.SearchFieldPlaceholder"
                                        ),
                                        alignment=ui.Alignment.LEFT_CENTER,
                                        height=18,
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
                            # Focus-state mirroring: omni.ui doesn't fire
                            # ``:focused`` on a Rectangle, so the named
                            # variant ``::focused`` on the outer pill is
                            # toggled imperatively.
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
                                    _filter_icon_provider("stage_close_x"),
                                    width=12,
                                    height=12,
                                    style_type_name_override=(
                                        "Property.FilterClearButton.Image"
                                    ),
                                    visible=False,
                                )
                                self._filter_clear_button.set_mouse_pressed_fn(
                                    lambda x, y, b, m: (
                                        self._clear_filter() if b == 0 else None
                                    )
                                )
                                ui.Spacer()
                            ui.Spacer(width=8)
                    ui.Spacer()
                ui.Spacer(width=6)
        self._set_filter_chrome_state(bool(self._filter_text))

    def _apply_filter(self, text: str) -> None:
        self._filter_text = text
        self._pending_filter_handle = None
        self._rebuild_content()

    def _clear_filter(self) -> None:
        if self._filter_field is not None:
            self._filter_field.model.set_value("")

    def _focus_filter_field(self) -> None:
        if self._filter_field is None:
            return
        focus_keyboard = getattr(self._filter_field, "focus_keyboard", None)
        if focus_keyboard is not None:
            focus_keyboard()

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

    def set_adapter(self, adapter: Optional[PropertyAdapter]) -> None:
        """Hot-swap the PropertyAdapter and rebuild content."""
        self._adapter = adapter
        self._rebuild_content()

    def set_property_adapter_factory(self, factory: Any) -> None:
        """Register a callable ``factory(paths) -> PropertyAdapter`` used to
        build a fresh adapter for every selection change.

        Step 10 inverts control: ``PropertyWindow`` no longer imports any
        concrete adapter. ``Application`` (the composition root) installs
        the factory before :meth:`set_stage_adapter`; if no factory is
        registered, :meth:`_create_adapter_for_paths` returns ``None`` and
        the panel renders empty.
        """
        self._adapter_factory = factory

    def set_stage_adapter(self, stage_adapter: Any, undo_manager: Any = None) -> None:
        """Wire a live USD stage to this window. Subscribes to stage change events.

        Step 10: the old ``prop_adapter`` positional argument is gone — the
        adapter is built lazily inside :meth:`_create_adapter_for_paths`
        from the factory installed via :meth:`set_property_adapter_factory`.
        """
        if self._stage_change_sub is not None:
            self._stage_change_sub.cancel()
            self._stage_change_sub = None
        self._stage_adapter = stage_adapter
        self._undo_manager_ref = undo_manager
        if stage_adapter is not None:
            self._stage_change_sub = stage_adapter.subscribe_changes(self._on_stage_changed)
        self._rebuild_content()

    def _on_stage_changed(self, event: Any) -> None:
        selected_set = set(self._selection)
        if not selected_set:
            return
        affected = any(
            changed.startswith(sel)
            for changed in list(event.changed_paths) + list(event.resynced_paths)
            for sel in selected_set
        )
        if affected:
            self._rebuild_content()

    def set_selection(self, paths: List[str]) -> None:
        """Update selected prim paths and rebuild content.

        Bug 12: when the bus-publish callback
        (:meth:`_on_bus_selection_changed`) routes through here, the
        content rebuild is deferred one frame to avoid the viewport
        resize flicker that used to happen when every property row was
        torn down inline during a synchronous publish. Direct
        programmatic callers (and tests) still get a synchronous
        rebuild — the deferral only kicks in when the bus-callback flag
        :attr:`_in_bus_callback` is set.
        """
        new_paths = list(paths)
        if new_paths == self._selection:
            return
        self._selection = new_paths
        # Step 7.4: a real selection change resets the large-selection
        # override so the next payload hits the gate again. The earlier
        # equality short-circuit keeps a same-selection re-publish from
        # clobbering an in-progress override.
        self._large_selection_override = False
        if getattr(self, "_stage_adapter", None) is not None:
            self._adapter = self._create_adapter_for_paths(new_paths)
        if getattr(self, "_in_bus_callback", False):
            self._schedule_deferred_rebuild()
        else:
            self._cancel_pending_selection_rebuild()
            self._rebuild_content()

    def _create_adapter_for_paths(self, paths: Any) -> Any:
        if self._adapter_factory is None:
            return None
        try:
            return self._adapter_factory(paths)
        except Exception:
            return self._adapter

    def _on_bus_selection_changed(self, event: Any) -> None:
        # Bug 12: flag the bus-callback call context so ``set_selection``
        # routes through :meth:`_schedule_deferred_rebuild` instead of a
        # synchronous :meth:`_rebuild_content`. Running the full rebuild
        # inline during a bus publish used to make omni.ui reflow the
        # whole dock space mid-event, briefly shifting the viewport's
        # ``computed_width`` / ``computed_height`` and forcing the
        # renderer to re-resolve at the wrong resolution for a frame
        # (the visible flicker). Direct programmatic callers
        # (``set_stage_adapter`` path, tests) keep the synchronous
        # behaviour so their post-call assertions stay valid.
        paths = event.snapshot.paths()
        self._in_bus_callback = True
        try:
            self.set_selection(paths)
        finally:
            self._in_bus_callback = False

    def _schedule_deferred_rebuild(self) -> None:
        """Queue :meth:`_rebuild_content` for the next application frame.

        Cancels any still-pending handle so rapid selection changes
        coalesce (click Cube → Sphere → Pyramid across three frames →
        only the final Pyramid selection's content actually builds).
        Falls back to a synchronous :meth:`_rebuild_content` when no
        :class:`~ovwidgets.app.application.Application` singleton is live so
        bus-driven headless tests still see the rebuild happen during
        the publish call.
        """
        self._cancel_pending_selection_rebuild()
        try:
            from ovwidgets.common import scheduler as _scheduler
            self._pending_selection_rebuild_handle = _scheduler.call_later(
                0.0, self._fire_deferred_selection_rebuild
            )
        except RuntimeError:
            self._rebuild_content()
            return

    def _fire_deferred_selection_rebuild(self) -> None:
        """Fire the deferred rebuild — drops the handle, then rebuilds."""
        self._pending_selection_rebuild_handle = None
        self._rebuild_content()

    def _cancel_pending_selection_rebuild(self) -> None:
        handle = self._pending_selection_rebuild_handle
        if handle is not None:
            handle.cancel()
            self._pending_selection_rebuild_handle = None

    def register_widget(self, widget: PropertyWidget) -> None:
        """Append ``widget`` to the stack and request a rebuild."""
        self._widgets.append(widget)
        self._rebuild_content()

    def unregister_widget(self, widget: PropertyWidget) -> None:
        """Remove ``widget`` from the stack and release its resources.

        Silently no-ops when the widget is not registered, mirroring
        Kit's ``PropertyWindow.unregister_widget`` semantics
        (the property inspector behavior).
        """
        if widget in self._widgets:
            self._widgets.remove(widget)
            widget.destroy()
            self._rebuild_content()

    def destroy(self) -> None:
        if self._stage_change_sub is not None:
            self._stage_change_sub.cancel()
            self._stage_change_sub = None
        if self._bus_sub is not None:
            self._bus_sub.cancel()
            self._bus_sub = None
        # Bug 12: a deferred-rebuild handle that fires after destroy would
        # call :meth:`_rebuild_content` on a torn-down window.
        self._cancel_pending_selection_rebuild()
        for widget in self._widgets:
            widget.destroy()
        self._widgets.clear()
        # Step 6.5: the thin-delegate-only AttributesWidget is not in
        # ``self._widgets`` (the registry owns rendering registration,
        # not this list) so tear it down explicitly; otherwise its
        # ``SimplePropertyWidget`` pending-rebuild handle / filter
        # subscription would leak past window teardown.
        if self._default_attributes is not None:
            self._default_attributes.destroy()
        self._default_attributes = None
        # Step 7.3: cancel any still-pending scroll-restore handles so
        # the deferred callbacks don't fire after the window is gone.
        if self._scroll_preserver is not None:
            self._scroll_preserver.destroy()
        self._scroll_preserver = None
        super().destroy()

    def _rebuild_content(self) -> None:
        if self._content is None:
            return
        # Step 7.3: snapshot the current scroll position before we blow
        # away the content stack. The preserver reads ``scroll_y`` off
        # the outer scrolling frame now; the matching restore call below
        # schedules a two-frame deferred write so omni.ui has a chance to
        # recompute layout + ``scroll_y_max`` before the write lands.
        if self._scroll_preserver is not None:
            self._scroll_preserver.save_position()
        self._content.clear()
        if not self._adapter or not self._selection:
            # QA BUG-002: show an explicit placeholder so the panel never
            # reads as "broken" when the user has nothing selected. The
            # dedicated helper keeps this branch independently testable
            # (see :meth:`_build_empty_selection_placeholder`).
            self._build_empty_selection_placeholder()
            # Empty panel: reset scroll by forcing the preserver's prior
            # scheme into a sentinel so the next selection does not
            # preserve against it. The restore call fires here too so
            # the empty state explicitly targets scroll_y=0 (new_scheme
            # will not match the prior scheme, which drives the reset
            # branch inside :meth:`ScrollPreserver.restore_position`).
            if self._scroll_preserver is not None:
                self._scroll_preserver.restore_position("__empty__")
            return
        # Step 7.4: build the payload once so the large-selection gate
        # and the scroll-preserver restore share a single construction.
        payload = PropertyPayload(paths=self._selection)
        with self._content:
            self._build_selection_header()
            self._build_filter_bar()
            if (
                payload.is_large_selection(self._large_selection_threshold)
                and not self._large_selection_override
            ):
                # Gate fires at the 100+ prim default threshold: skip the
                # full attribute build, render the banner + override button
                # instead.
                self._build_large_selection_banner(len(payload))
            else:
                self._build_group_stack()
        # Step 7.3: schedule the restore. The preserver decides whether
        # the new payload's scheme matches the prior one and either
        # writes the saved ``scroll_y`` back (preserve) or snaps to 0
        # (reset). The write fires two frames later via call_later.
        if self._scroll_preserver is not None:
            self._scroll_preserver.restore_position(payload.get_scheme())

    def _build_registered_widgets(self) -> None:
        """Dispatch :class:`PropertyWidget` sections for the current payload.

        Step 6.5: asks
        :class:`~ovwidgets.property.widget.PropertySchemeRegistry` for the
        ordered widget list keyed on the payload's scheme (which
        carries the ``"default"`` catch-all entries plus any
        scheme-specific registrations), *then* iterates any widgets
        stored in :attr:`_widgets` by the per-window
        :meth:`register_widget` compat path. Each widget is asked
        whether it wants to show for the payload
        (:meth:`PropertyWidget.on_new_payload`); only widgets that
        return ``True`` get :meth:`PropertyWidget.build_items` called.

        Widgets exposing :meth:`set_window` (duck-typed —
        :class:`AttributesWidget` is the only built-in today) receive
        the host window back-reference before
        :meth:`on_new_payload` so adapter / selection / filter state
        is available during the subsequent build.

        The registry path is the new canonical surface — the Step 6.1
        local list is preserved to keep
        :meth:`register_widget` / :meth:`unregister_widget` callers
        working while third-party code migrates. Default registrations
        (:class:`AttributesWidget` for ``"default"``) live in the
        registry only; nothing mirrors them into :attr:`_widgets`, so
        the same widget class cannot double-render.
        """
        payload = PropertyPayload(paths=self._selection)
        registry_widgets = PropertySchemeRegistry.instance().get_widgets_for_payload(
            payload.get_scheme(), payload
        )
        for widget in list(registry_widgets) + list(self._widgets):
            if hasattr(widget, "set_window"):
                widget.set_window(self)
            if widget.on_new_payload(payload):
                widget.build_items()

    def _build_group_stack(self) -> None:
        ui.Spacer(height=_FILTER_TO_FIRST_GROUP_SPACING)
        with ui.VStack(spacing=GROUP_STACK_SPACING, height=FIT_CONTENT_HEIGHT):
            self._build_registered_widgets()

    # ------------------------------------------------------------------
    # Selection header (Design Step 12).
    # ------------------------------------------------------------------

    def _get_selection_header_info(self) -> Optional[_SelectionHeaderInfo]:
        """Return display data for the single selected prim, if available."""
        paths = list(getattr(self, "_selection", []))
        if len(paths) != 1:
            return None
        path = str(paths[0])
        if not path:
            return None

        stage_adapter = getattr(self, "_stage_adapter", None)
        if stage_adapter is None:
            return None

        item = stage_adapter.get_item_at_path(path)
        if item is None:
            return None

        name = str(stage_adapter.get_display_name(item))
        if not name:
            name = self._display_name_from_path(path)

        prim_type = str(stage_adapter.get_type_name(item))
        prim_type = prim_type.strip() or "Prim"

        return _SelectionHeaderInfo(
            prim_type=prim_type.upper(),
            name=name,
            path=path,
        )

    @staticmethod
    def _display_name_from_path(path: str) -> str:
        trimmed = path.rstrip("/")
        if not trimmed:
            return "/"
        return trimmed.rsplit("/", 1)[-1] or "/"

    def _build_selection_header(self) -> None:
        """Render selected prim type/name/path above the first property group."""
        info = self._get_selection_header_info()
        if info is None:
            return

        with ui.VStack(height=_SELECTION_HEADER_HEIGHT, spacing=0):
            ui.Spacer(height=_SELECTION_HEADER_TOP_PADDING)
            self._build_selection_header_label(
                info.prim_type,
                "Property.SelectionHeader",
                _SELECTION_HEADER_SMALL_LINE_HEIGHT,
            )
            ui.Spacer(height=_SELECTION_HEADER_LINE_GAP)
            self._build_selection_header_label(
                info.name,
                "Property.SelectionHeader.Title",
                _SELECTION_HEADER_TITLE_LINE_HEIGHT,
            )
            ui.Spacer(height=_SELECTION_HEADER_LINE_GAP)
            self._build_selection_header_label(
                info.path,
                "Property.SelectionHeader.Path",
                _SELECTION_HEADER_SMALL_LINE_HEIGHT,
            )
            ui.Spacer(height=_SELECTION_HEADER_BOTTOM_PADDING)

    def _build_selection_header_label(
        self,
        text: str,
        style_type_name_override: str,
        height: int,
    ) -> None:
        with ui.HStack(height=height):
            ui.Spacer(width=_SELECTION_HEADER_SIDE_PADDING)
            label = ui.Label(
                text,
                style_type_name_override=style_type_name_override,
                alignment=ui.Alignment.LEFT_CENTER,
                height=height,
            )
            label.tooltip = text
            ui.Spacer(width=_SELECTION_HEADER_SIDE_PADDING)

    # ------------------------------------------------------------------
    # Large-selection gate (Step 7.4).
    #
    # When the current payload's :meth:`PropertyPayload.is_large_selection`
    # returns True and the user has not explicitly overridden the gate
    # via the banner button, :meth:`_rebuild_content` suppresses the
    # full attribute build and renders a small banner instead. Clicking
    # the banner's "Load Anyway" button flips the override flag and
    # forces a rebuild that takes the full-attributes branch. The flag
    # resets in :meth:`set_selection` so a fresh selection gets the
    # gate again.
    # ------------------------------------------------------------------

    def _build_empty_selection_placeholder(self) -> None:
        """Render a "No selection" label into the current content stack.

        QA BUG-002. Called from :meth:`_rebuild_content` when the window
        has no adapter or an empty selection. Uses the same
        ``Property.EmptyLabel`` style the filter's "No properties"
        message uses so the two empty-state messages look identical.
        ``self._content`` is guaranteed non-``None`` by the caller.
        """
        with self._content:
            ui.Label(
                "No selection",
                style_type_name_override="Property.EmptyLabel",
                alignment=ui.Alignment.CENTER,
            )

    def _build_large_selection_banner(self, count: int) -> None:
        """Render the large-selection banner into the current content stack.

        Called from inside a ``with self._content:`` block by
        :meth:`_rebuild_content` when the gate fires. Renders a single
        labeled message and a "Load Anyway" button wired to
        :meth:`_on_ignore_threshold_clicked`.
        """
        with ui.VStack(spacing=8, style_type_name_override="Property.LargeSelectionBanner"):
            ui.Label(
                f"{count} items selected — property display suppressed. "
                "Click to load anyway.",
                style_type_name_override="Property.LargeSelectionBanner",
                word_wrap=True,
                height=0,
            )
            ui.Button(
                "Load Anyway",
                width=ui.Percent(60),
                height=28,
                clicked_fn=self._on_ignore_threshold_clicked,
            )
            # Trailing spacer so the label + button stick to the top of
            # the inspector panel rather than distributing across the
            # full scrolling-frame height (the default VStack layout
            # behaviour for non-``height=0`` children).
            ui.Spacer()

    def _on_ignore_threshold_clicked(self) -> None:
        """Flip the large-selection override flag and rebuild.

        The rebuild re-enters :meth:`_rebuild_content` with
        ``_large_selection_override`` set; the gate sees the override
        and the full attribute build runs in place of the banner.
        """
        self._large_selection_override = True
        self._rebuild_content()

    # ------------------------------------------------------------------
    # Thin delegates to the default :class:`AttributesWidget` (Step 6.2).
    #
    # The actual implementation lives in
    # :mod:`ovwidgets.property.widget.attributes_widget`; these one-liners are
    # kept so existing callers and tests that inspect the window API
    # (``test_property_filter.py::test_has_compute_display_group_method``
    # and friends) keep resolving. They will be removed when the test
    # harnesses migrate to the widget API directly.
    # ------------------------------------------------------------------

    def _compute_display_group(self) -> UiDisplayGroup:
        if self._default_attributes is None:
            return UiDisplayGroup(name="")
        return self._default_attributes._compute_display_group()

    def _build_groups(self) -> None:
        if self._default_attributes is None:
            return
        self._default_attributes._build_groups()

    def _build_group_children(
        self, group: UiDisplayGroup, path: str
    ) -> None:
        if self._default_attributes is None:
            return
        self._default_attributes._build_group_children(group, path)

    def _build_attribute_row(self, prop: AttributeMetadata) -> None:
        if self._default_attributes is None:
            return
        self._default_attributes._build_attribute_row(prop)

    def _show_group_context_menu(
        self, group: UiDisplayGroup, x: float, y: float
    ) -> None:
        if self._default_attributes is None:
            return
        self._default_attributes._show_group_context_menu(group, x, y)


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovwidgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_FILTER_ICON_CACHE)
