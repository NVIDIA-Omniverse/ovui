# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Attribute row widgets for the Property Inspector (property inspector style behavior).

Each row class wraps a single attribute's label + input widget(s) and
routes user edits through an :class:`AttributeModelBase`.

Step 1.4 of the property inspector implementation replaced the direct
``adapter.begin_edit``/``set_value``/``end_edit`` calls in every row with
an owned :class:`AttributeModelBase` instance. Each
row now:

* constructs a model in ``__init__`` (one initial ``adapter.get_value``
  read to seed ``_value``);
* wires its UI widget's ``begin_edit``/``value_changed``/``end_edit``
  callbacks to the model's lifecycle methods;
* subscribes to ``model.subscribe_value_changed`` so that external USD
  edits — surfaced via ``adapter.subscribe_changes`` →
  ``model._on_backing_changed`` — refresh the displayed value without
  clobbering a concurrent user edit.

The module-level ``build_attribute_row`` function is a deprecated thin
forwarder to :class:`ovwidgets.property.builders.WidgetBuilderTable`. Step 1.3
of the property inspector implementation swapped the live dispatch over to the table; the
forwarder remains so existing tests that import ``build_attribute_row``
directly keep passing.
"""

from typing import Any, Dict, List, Optional

import omni.ui as ui
from omni.ui import color as cl
from ovui_data_adapters.common import AttributeMetadata, PropertyAdapter

from ovwidgets.common.icon_caches import provider
from ovwidgets.property.group_widget import _CHEVRON_DOWN
from ovwidgets.property.models import AttributeModelBase
from ovwidgets.property.parts import ControlStateIndicator, HighlightLabel

# Property-row pixel height. ``ui.HStack(height=…)`` cannot accept a
# ``_ShadeName`` token directly (the omni.ui FloatStore proxy), so the
# numeric value is the source of truth here. ``fl.property_row_height``
# in ``ovwidgets/app/style/constants.py`` mirrors this value for any
# stylesheet consumer that resolves shade tokens at draw time — they
# must be kept equal.
_ATTRIBUTE_ROW_HEIGHT = 24
_VALUE_COLUMN_WIDTH = 160
_VALUE_FIELD_STYLE = "Property.ValueField"
_DROPDOWN_VALUE_FIELD_STYLE = "Property.DropdownValueField"
_DROPDOWN_BORDER_INSET = 1
_FOCUSED_VALUE_FIELD_NAME = "focused"
_COMBOBOX_CHEVRON_SLOT_WIDTH = 18
_COMBOBOX_CHEVRON_SIZE = 9
_COMBOBOX_CHEVRON_RIGHT_PADDING = 5
_CHECKBOX_SIZE = 18
_CHECKBOX_TOP_OFFSET = 3
_COMPONENT_LABEL_WIDTH = 14
_COMPONENT_SEPARATOR_WIDTH = 1
_COMPONENT_SPACING = 2
_CONTROL_STATE_SLOT_WIDTH = 20
_COLOR_SWATCH_WIDTH = 22


def _set_value_field_focused(widget: Any, focused: bool) -> None:
    """Apply the focused named style variant to a value-field widget.

    Inline override mirrors ``Property.ValueField:focused`` /
    ``::focused`` in ``ovwidgets/property/style.py`` — both must paint the
    cell with ``background_value_field_editing`` so a focused property
    cell reads as inset-editing rather than the rest-state field fill.
    """
    if widget is not None:
        widget.name = _FOCUSED_VALUE_FIELD_NAME if focused else ""
        widget.style = (
            {
                "background_color": cl.background_value_field_editing,
                "secondary_color": cl.background_value_field_editing,
                "border_color": cl.border_focused,
                "border_width": 1,
            }
            if focused else {}
        )


def _set_matching_value_field_focused(
    widgets: List[Optional[Any]], widget_model: Any, focused: bool
) -> None:
    for widget in widgets:
        if widget is not None and getattr(widget, "model", None) is widget_model:
            _set_value_field_focused(widget, focused)
            return


def _ignore_mouse_events(widget: Any) -> Any:
    if widget is not None:
        widget.opaque_for_mouse_events = False
    return widget


def _build_combobox_chevron_overlay() -> None:
    """Draw the OVUI chevron above a no-arrow ComboBox."""
    overlay_row = _ignore_mouse_events(ui.HStack())
    with overlay_row:
        ui.Spacer()
        chevron_stack = _ignore_mouse_events(
            ui.ZStack(
                width=_COMBOBOX_CHEVRON_SLOT_WIDTH,
                height=_ATTRIBUTE_ROW_HEIGHT,
            )
        )
        with chevron_stack:
            chevron_column = _ignore_mouse_events(ui.VStack())
            with chevron_column:
                ui.Spacer()
                chevron_row = _ignore_mouse_events(
                    ui.HStack(height=_COMBOBOX_CHEVRON_SIZE)
                )
                with chevron_row:
                    ui.Spacer()
                    _ignore_mouse_events(
                        ui.ImageWithProvider(
                            provider(_CHEVRON_DOWN),
                            width=_COMBOBOX_CHEVRON_SIZE,
                            height=_COMBOBOX_CHEVRON_SIZE,
                            style_type_name_override="Property.ComboBoxChevron",
                        )
                    )
                    ui.Spacer(width=_COMBOBOX_CHEVRON_RIGHT_PADDING)
                ui.Spacer()


def _build_aligned_checkbox() -> ui.CheckBox:
    """Build a reference-sized checkbox centered in a Property row."""
    with ui.VStack(width=_ATTRIBUTE_ROW_HEIGHT, height=_ATTRIBUTE_ROW_HEIGHT):
        ui.Spacer(height=_CHECKBOX_TOP_OFFSET)
        checkbox = ui.CheckBox(width=_CHECKBOX_SIZE, height=_CHECKBOX_SIZE)
        ui.Spacer()
    return checkbox


def _label_kwargs_from_metadata(prop: AttributeMetadata) -> Dict[str, Any]:
    """Assemble label kwargs (style override + state name) for the row's
    attribute label.

    Step 4.2 of the property inspector implementation (property metadata behavior). Always sets
    ``style_type_name_override="Property.LabelColumn"`` so the
    ``::not_authored`` state selector (see :mod:`ovwidgets.property.style`) can
    attach; the ``name`` is ``"not_authored"`` when ``metadata.is_authored``
    is False, empty otherwise. Shared by every row that renders the
    attribute's display name as a single label so the muted colour is
    applied uniformly (property metadata behavior "Default: True" — default-authored
    attributes render at the full ``Property.LabelColumn`` colour).
    """
    return {
        "style_type_name_override": "Property.LabelColumn",
        "name": "" if prop.is_authored else "not_authored",
    }


def _build_attribute_label(
    prop: AttributeMetadata,
    match: str = "",
    *,
    alignment: Any = None,
) -> HighlightLabel:
    """Build a :class:`HighlightLabel` for the row's label slot.

    Step 7.1 of the property inspector implementation (highlight-label behavior / the property inspector behavior). Replaces the raw ``ui.Label(prop.display_name, ...)`` every
    row used to construct — now every row funnels through this helper so
    the filter-match highlighting behaviour is uniform. When ``match`` is
    empty or does not appear in ``prop.display_name``, the resulting
    widget renders a single ``ui.Label`` identical to the pre-7.1 output
    (no wrapper HStack, no extra children — byte-for-byte unchanged).
    Non-empty matches split the label into alternating normal / highlight
    segments styled via ``Property.LabelColumn`` and
    ``Property.LabelColumn::highlight``.

    ``alignment`` is forwarded to every segment label when provided;
    :class:`MatrixAttributeRow` needs ``LEFT_TOP`` so the label aligns to
    the top of its N-row-tall value column. The helper forwards it only
    when non-``None`` so callers that don't care keep the ovui default.
    Width is intentionally left to the caller's clipping slot.
    """
    extra: Dict[str, Any] = {}
    if alignment is not None:
        extra["alignment"] = alignment
    return HighlightLabel(
        prop.display_name,
        match=match,
        **_label_kwargs_from_metadata(prop),
        **extra,
    )


def _build_attribute_label_slot(
    prop: AttributeMetadata,
    match: str = "",
    *,
    alignment: Any = None,
) -> HighlightLabel:
    """Build the row label inside the remaining-width clipping slot."""
    with ui.Frame(width=ui.Fraction(1), horizontal_clipping=True):
        with ui.ZStack():
            return _build_attribute_label(prop, match, alignment=alignment)


def _component_value_width(
    n_components: int,
    *,
    include_channel_labels: bool = False,
    trailing_width: int = 0,
    include_separators: bool = True,
) -> int:
    """Fixed per-component field width within the value column."""
    fixed_width = trailing_width
    child_count = n_components
    if include_channel_labels:
        fixed_width += n_components * _COMPONENT_LABEL_WIDTH
        child_count += n_components
    if include_separators:
        fixed_width += max(0, n_components - 1) * _COMPONENT_SEPARATOR_WIDTH
        child_count += max(0, n_components - 1)
    if trailing_width > 0:
        child_count += 1
    spacing_width = max(0, child_count - 1) * _COMPONENT_SPACING
    available = _VALUE_COLUMN_WIDTH - fixed_width - spacing_width
    return max(1, int(available // max(1, n_components)))


def _wire_row_context_menu(hstack: Any, owner: Any) -> None:
    """Attach the Step-7.2 right-click → context-menu handler to ``hstack``.

    Registers a
    ``mouse_released_fn`` on the row's outer ``ui.HStack`` that filters
    for button 1 (right-click, matching the omni.ui / X11 encoding the
    group-header Step 5.3 handler also uses) and defers to
    :func:`ovwidgets.property.parts.attr_context_menu.show_attr_context_menu`.

    The ``owner`` argument is the row instance; the handler pins the
    returned :class:`ui.Menu` on ``owner._active_context_menu`` so
    omni.ui's reference-count teardown does not drop the popup the
    instant the handler returns. Every row class gets an
    ``_active_context_menu`` slot initialised to ``None`` in its
    ``__init__``; the next right-click overwrites it, which closes any
    still-open menu.

    ``_FallbackAttributeRow`` does NOT use this helper: the fallback
    row has no adapter reference and no :class:`AttributeModelBase`,
    so there is nothing to Copy / Paste / Reset. The menu would offer
    only "Copy Attribute Path", and the path alone is not worth a
    dedicated menu — the user can still select-copy the display text
    from the read-only label.

    Lazy import of :mod:`attr_context_menu` keeps the module boundary
    the same as the Step 5.3 pattern: UI-driver modules inside
    :mod:`ovwidgets.property.parts` are only touched when a user actually
    right-clicks a row, not at module import time.
    """
    def _on_mouse_released(
        x: float, y: float, button: int, modifier: int
    ) -> None:
        if button != 1:
            return
        from ovwidgets.property.parts.attr_context_menu import (
            show_attr_context_menu,
        )
        owner._active_context_menu = show_attr_context_menu(
            owner._adapter, owner._prop, x, y
        )

    hstack.set_mouse_released_fn(_on_mouse_released)


def _build_component_separator() -> ui.Rectangle:
    """Build a 1-pixel vertical ``Property.ComponentSeparator`` rectangle.

    Vector / colour / matrix rows
    insert one of these between adjacent channel drag widgets so the eye
    can parse X|Y|Z as three distinct fields rather than a single blob of
    digits. The style (``cl.border_default`` fill + 2 px horizontal
    margin) lives on :data:`ovwidgets.property.style.PROPERTY_STYLES` —
    subtle enough to stay out of the way but visible against the field
    background in both the dark and light themes.
    """
    return ui.Rectangle(
        width=1,
        style_type_name_override="Property.ComponentSeparator",
    )


def _drag_kwargs_from_metadata(prop: AttributeMetadata) -> Dict[str, Any]:
    """Assemble ``ui.FloatDrag`` / ``ui.IntDrag`` kwargs from ``prop``.

    Step 4.1 of the property inspector implementation (property attribute builder behavior). Surfaces
    ``metadata.soft_range_min`` / ``soft_range_max`` as the widget's
    ``min`` / ``max`` so the drag handle respects the attribute's
    documented soft bounds. Omits a key entirely when the corresponding
    metadata field is ``None`` — otherwise omni.ui would clamp against a
    Python ``None`` and raise on the C++ binding. A widget with neither
    bound set stays unbounded, matching the pre-4.1 default.

    Shared by every row that builds a drag widget: scalar
    (:class:`FloatAttributeRow`, :class:`IntAttributeRow`), vector
    (:class:`_VecFloatRow`, :class:`_VecIntRow`), colour
    (:class:`_ColorFloatRow`), and matrix (:class:`MatrixAttributeRow`).
    The caller passes the returned dict via ``**`` expansion into
    ``ui.FloatDrag(...)`` / ``ui.IntDrag(...)``.
    """
    kwargs: Dict[str, Any] = {}
    if prop.soft_range_min is not None:
        kwargs["min"] = prop.soft_range_min
    if prop.soft_range_max is not None:
        kwargs["max"] = prop.soft_range_max
    return kwargs


class FloatAttributeRow:
    """Label + FloatDrag for a single float attribute."""

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        self._prop = prop
        self._adapter = adapter
        self._match = match
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._widget: Optional[ui.FloatDrag] = None
        self._label: Optional[HighlightLabel] = None
        self._overlay: Optional[ui.Label] = None
        self._indicator: Optional[ControlStateIndicator] = None
        # ``_updating`` breaks the model → widget.set_value → widget
        # value_changed_fn → model.set_value feedback loop that would
        # otherwise recurse indefinitely on external backing changes if
        # ``ui.SimpleFloatModel.set_value`` fires unconditionally.
        self._updating = False
        # Step 7.2: pins the most-recently-shown attr context menu so
        # omni.ui's refcount teardown does not drop it mid-frame.
        self._active_context_menu: Optional[Any] = None
        self._value_sub = self._model.subscribe_value_changed(self._on_model_value_changed)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)
        self._build_ui()

    def _build_ui(self) -> None:
        mixed = self._model.is_ambiguous
        row_hstack = ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=4)
        with row_hstack:
            self._label = _build_attribute_label_slot(self._prop, self._match)
            with ui.ZStack(width=_VALUE_COLUMN_WIDTH):
                self._widget = ui.FloatDrag(
                    style_type_name_override=_VALUE_FIELD_STYLE,
                    **_drag_kwargs_from_metadata(self._prop),
                )
                self._widget.enabled = not self._model.is_readonly
                value = self._model.get_value()
                if value is not None:
                    self._widget.model.set_value(float(value))
                self._widget.model.add_begin_edit_fn(self._on_begin_edit)
                self._widget.model.add_value_changed_fn(self._on_value_changed)
                self._widget.model.add_end_edit_fn(self._on_end_edit)
                self._overlay = ui.Label(
                    "Mixed",
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Property.MixedOverlay",
                    visible=mixed,
                )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _on_begin_edit(self, widget_model: Any) -> None:
        _set_value_field_focused(self._widget, True)
        self._model.begin_edit()

    def _on_value_changed(self, widget_model: Any) -> None:
        if self._updating:
            return
        self._model.set_value(widget_model.get_value_as_float())

    def _on_end_edit(self, widget_model: Any) -> None:
        _set_value_field_focused(self._widget, False)
        self._model.end_edit()

    def _on_model_value_changed(self) -> None:
        if self._widget is None or self._model.editing or self._updating:
            return
        value = self._model.get_value()
        if value is None:
            return
        self._updating = True
        try:
            self._widget.model.set_value(float(value))
        finally:
            self._updating = False


_VEC_CHANNEL_LETTERS = ("X", "Y", "Z", "W")


class _VecFloatRow:
    """Label + N× FloatDrag (X/Y/…/W) for float vector attributes.

    Shared base for ``Vec2FloatAttributeRow`` (n=2), ``Vec3FloatAttributeRow``
    (n=3), and ``Vec4FloatAttributeRow`` (n=4). Channel letters come from
    ``_VEC_CHANNEL_LETTERS[:n]``; each channel label uses
    ``Property.ChannelLabel.{letter}`` style (property attribute builder behavior) with the
    ``::mixed`` state selector driven by per-component ambiguity.

    Introduced in Step 3.1 of the property inspector implementation. The n=3 specialisation was
    called ``Vec3FloatAttributeRow`` prior to 3.1; that name now refers to a
    thin subclass for backwards compatibility with existing callers and
    tests.
    """

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        n_components: int,
        match: str = "",
    ) -> None:
        if not 2 <= n_components <= 4:
            raise ValueError(
                f"_VecFloatRow: n_components must be 2, 3, or 4 — got {n_components}"
            )
        self._prop = prop
        self._adapter = adapter
        self._match = match
        self._n_components = n_components
        self._channel_letters = _VEC_CHANNEL_LETTERS[:n_components]
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._widgets: List[Optional[ui.FloatDrag]] = [None] * n_components
        self._label: Optional[HighlightLabel] = None
        self._channel_labels: List[Optional[ui.Label]] = [None] * n_components
        self._overlay_labels: List[Optional[ui.Label]] = [None] * n_components
        # Step 8.1 — ``Property.ComponentSeparator`` rectangles between
        # adjacent channel drags. ``_VecFloatRow`` produces ``n-1`` of them
        # (one per channel boundary: X|Y, Y|Z, Z|W). The list is populated
        # in :meth:`_build_ui` and pinned by channel-index order so tests
        # can assert both the count and the style identity of each entry.
        # ``Property.ComponentSeparator`` style selectors.
        self._separators: List[Optional[ui.Rectangle]] = []
        self._indicator: Optional[ControlStateIndicator] = None
        self._updating = False
        self._active_context_menu: Optional[Any] = None
        self._value_sub = self._model.subscribe_value_changed(self._on_model_value_changed)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)
        self._build_ui()

    def _build_ui(self) -> None:
        per_component = self._adapter.get_per_component_ambiguity(self._prop.name)
        # Fallback for adapters that return None for vec attrs (test doubles /
        # pre-Step-2.1 adapters): per-channel ambiguity collapses to the
        # whole-attribute ``is_ambiguous`` flag, so every channel shows the
        # "Mixed" overlay when any prim's value differs.
        whole_ambiguous = self._model.is_ambiguous
        readonly = self._model.is_readonly
        value = self._model.get_value()
        self._separators = []
        component_width = _component_value_width(
            self._n_components,
            include_channel_labels=True,
        )
        row_hstack = ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=2)
        with row_hstack:
            self._label = _build_attribute_label_slot(self._prop, self._match)
            with ui.HStack(width=_VALUE_COLUMN_WIDTH, spacing=_COMPONENT_SPACING):
                for i, ch in enumerate(self._channel_letters):
                    if i > 0:
                        self._separators.append(_build_component_separator())
                    if per_component is not None and i < len(per_component):
                        channel_mixed = per_component[i]
                    else:
                        channel_mixed = whole_ambiguous
                    label = ui.Label(
                        ch,
                        width=_COMPONENT_LABEL_WIDTH,
                        style_type_name_override=f"Property.ChannelLabel.{ch}",
                        name="mixed" if channel_mixed else "",
                    )
                    self._channel_labels[i] = label
                    with ui.ZStack(width=component_width):
                        widget = ui.FloatDrag(
                            style_type_name_override=_VALUE_FIELD_STYLE,
                            **_drag_kwargs_from_metadata(self._prop),
                        )
                        widget.enabled = not readonly
                        self._widgets[i] = widget
                        if value is not None and i < len(value):
                            widget.model.set_value(float(value[i]))
                        widget.model.add_begin_edit_fn(self._on_begin_edit)
                        widget.model.add_value_changed_fn(
                            lambda m, idx=i: self._on_component_changed(m, idx)
                        )
                        widget.model.add_end_edit_fn(self._on_end_edit)
                        self._overlay_labels[i] = ui.Label(
                            "Mixed",
                            alignment=ui.Alignment.CENTER,
                            style_type_name_override="Property.MixedOverlay",
                            visible=channel_mixed,
                        )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _on_begin_edit(self, widget_model: Any) -> None:
        _set_matching_value_field_focused(self._widgets, widget_model, True)
        self._model.begin_edit()

    def _on_component_changed(self, widget_model: Any, index: int) -> None:
        if self._updating:
            return
        current = self._model.get_value()
        base = list(current) if current is not None else [0.0] * self._n_components
        base[index] = widget_model.get_value_as_float()
        self._model.set_value(tuple(base))

    def _on_end_edit(self, widget_model: Any) -> None:
        _set_matching_value_field_focused(self._widgets, widget_model, False)
        self._model.end_edit()

    def _on_model_value_changed(self) -> None:
        if self._model.editing or self._updating:
            return
        value = self._model.get_value()
        if value is None:
            return
        self._updating = True
        try:
            for i, widget in enumerate(self._widgets):
                if widget is None or i >= len(value):
                    continue
                widget.model.set_value(float(value[i]))
        finally:
            self._updating = False


class Vec2FloatAttributeRow(_VecFloatRow):
    """Label + 2× FloatDrag (X/Y) for float2/double2/half2 attributes."""

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        super().__init__(prop, adapter, n_components=2, match=match)


class Vec3FloatAttributeRow(_VecFloatRow):
    """Label + 3× FloatDrag (X/Y/Z) for float3/color3f/double3 attributes."""

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        super().__init__(prop, adapter, n_components=3, match=match)


class Vec4FloatAttributeRow(_VecFloatRow):
    """Label + 4× FloatDrag (X/Y/Z/W) for float4/double4/half4 attributes."""

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        super().__init__(prop, adapter, n_components=4, match=match)


class _VecIntRow:
    """Label + N× IntDrag (X/Y/…/W) for integer vector attributes.

    Parallel to :class:`_VecFloatRow` but backed by ``ui.IntDrag`` widgets
    and integer coercion in the model. Shared base for
    ``Vec2IntAttributeRow`` (n=2), ``Vec3IntAttributeRow`` (n=3), and
    ``Vec4IntAttributeRow`` (n=4). Channel letters come from
    ``_VEC_CHANNEL_LETTERS[:n]``; each channel label uses
    ``Property.ChannelLabel.{letter}`` style (property attribute builder behavior) with the
    ``::mixed`` state selector driven by per-component ambiguity.

    Introduced in Step 3.2 of the property inspector implementation.
    """

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        n_components: int,
        match: str = "",
    ) -> None:
        if not 2 <= n_components <= 4:
            raise ValueError(
                f"_VecIntRow: n_components must be 2, 3, or 4 — got {n_components}"
            )
        self._prop = prop
        self._adapter = adapter
        self._match = match
        self._n_components = n_components
        self._channel_letters = _VEC_CHANNEL_LETTERS[:n_components]
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._widgets: List[Optional[ui.IntDrag]] = [None] * n_components
        self._label: Optional[HighlightLabel] = None
        self._channel_labels: List[Optional[ui.Label]] = [None] * n_components
        self._overlay_labels: List[Optional[ui.Label]] = [None] * n_components
        # Step 8.1 — matches ``_VecFloatRow``. See the float row for
        # rationale; the int variant carries the same ``n-1`` separator
        # count.
        self._separators: List[Optional[ui.Rectangle]] = []
        self._indicator: Optional[ControlStateIndicator] = None
        self._updating = False
        self._active_context_menu: Optional[Any] = None
        self._value_sub = self._model.subscribe_value_changed(self._on_model_value_changed)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)
        self._build_ui()

    def _build_ui(self) -> None:
        per_component = self._adapter.get_per_component_ambiguity(self._prop.name)
        whole_ambiguous = self._model.is_ambiguous
        readonly = self._model.is_readonly
        value = self._model.get_value()
        self._separators = []
        component_width = _component_value_width(
            self._n_components,
            include_channel_labels=True,
        )
        row_hstack = ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=2)
        with row_hstack:
            self._label = _build_attribute_label_slot(self._prop, self._match)
            with ui.HStack(width=_VALUE_COLUMN_WIDTH, spacing=_COMPONENT_SPACING):
                for i, ch in enumerate(self._channel_letters):
                    if i > 0:
                        self._separators.append(_build_component_separator())
                    if per_component is not None and i < len(per_component):
                        channel_mixed = per_component[i]
                    else:
                        channel_mixed = whole_ambiguous
                    label = ui.Label(
                        ch,
                        width=_COMPONENT_LABEL_WIDTH,
                        style_type_name_override=f"Property.ChannelLabel.{ch}",
                        name="mixed" if channel_mixed else "",
                    )
                    self._channel_labels[i] = label
                    with ui.ZStack(width=component_width):
                        widget = ui.IntDrag(
                            style_type_name_override=_VALUE_FIELD_STYLE,
                            **_drag_kwargs_from_metadata(self._prop),
                        )
                        widget.enabled = not readonly
                        self._widgets[i] = widget
                        if value is not None and i < len(value):
                            widget.model.set_value(int(value[i]))
                        widget.model.add_begin_edit_fn(self._on_begin_edit)
                        widget.model.add_value_changed_fn(
                            lambda m, idx=i: self._on_component_changed(m, idx)
                        )
                        widget.model.add_end_edit_fn(self._on_end_edit)
                        self._overlay_labels[i] = ui.Label(
                            "Mixed",
                            alignment=ui.Alignment.CENTER,
                            style_type_name_override="Property.MixedOverlay",
                            visible=channel_mixed,
                        )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _on_begin_edit(self, widget_model: Any) -> None:
        _set_matching_value_field_focused(self._widgets, widget_model, True)
        self._model.begin_edit()

    def _on_component_changed(self, widget_model: Any, index: int) -> None:
        if self._updating:
            return
        current = self._model.get_value()
        base = list(current) if current is not None else [0] * self._n_components
        base[index] = widget_model.get_value_as_int()
        self._model.set_value(tuple(base))

    def _on_end_edit(self, widget_model: Any) -> None:
        _set_matching_value_field_focused(self._widgets, widget_model, False)
        self._model.end_edit()

    def _on_model_value_changed(self) -> None:
        if self._model.editing or self._updating:
            return
        value = self._model.get_value()
        if value is None:
            return
        self._updating = True
        try:
            for i, widget in enumerate(self._widgets):
                if widget is None or i >= len(value):
                    continue
                widget.model.set_value(int(value[i]))
        finally:
            self._updating = False


_COLOR3_CHANNEL_LETTERS = ("R", "G", "B")
_COLOR4_CHANNEL_LETTERS = ("R", "G", "B", "A")
# R/G/B/A reuse the X/Y/Z/W axis palette (property attribute builder behavior): R↔X blue, G↔Y green,
# B↔Z orange, A↔W red. Kit established this so UsdGeomXform translate rows
# and UsdLux color attributes share the same per-channel hues.
_COLOR_CHANNEL_STYLE_AXIS = ("X", "Y", "Z", "W")


def _pack_color_abgr(value: Any, n_components: int) -> int:
    """Pack a ``(r, g, b)``/``(r, g, b, a)`` tuple into omni.ui's ABGR int.

    omni.ui's ``ui.Rectangle.style['background_color']`` is a 32-bit integer
    whose byte layout (high → low) is ``A B G R`` — see colour byte-layout note and the
    empirical ``cl(1.0, 0.0, 0.0)`` → ``0xFF0000FF`` check. A ``color3f``
    value carries no alpha, so we default it to fully opaque (``0xFF``).
    Out-of-range components clamp to ``[0.0, 1.0]`` before the 8-bit round.
    """
    if value is None:
        value = (0.0,) * n_components
    r = max(0.0, min(1.0, float(value[0]) if len(value) > 0 else 0.0))
    g = max(0.0, min(1.0, float(value[1]) if len(value) > 1 else 0.0))
    b = max(0.0, min(1.0, float(value[2]) if len(value) > 2 else 0.0))
    a = max(0.0, min(1.0, float(value[3]) if len(value) > 3 else 1.0))
    return (
        (int(round(a * 255)) << 24)
        | (int(round(b * 255)) << 16)
        | (int(round(g * 255)) << 8)
        | int(round(r * 255))
    )


class _ColorFloatRow(_VecFloatRow):
    """Vec row with R/G/B(/A) channel letters plus a live swatch preview.

    Extends :class:`_VecFloatRow` by overriding ``_build_ui`` to add a
    ``ui.Rectangle`` swatch at the end of the HStack whose
    ``style['background_color']`` tracks the current value. Clicking the
    swatch is a no-op in Step 3.4 — the colour picker hook lands in a
    later phase.
    """

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        n_components: int,
        match: str = "",
    ) -> None:
        if n_components not in (3, 4):
            raise ValueError(
                f"_ColorFloatRow: n_components must be 3 or 4 — got {n_components}"
            )
        self._swatch: Optional[ui.Rectangle] = None
        super().__init__(prop, adapter, n_components=n_components, match=match)
        # ``_VecFloatRow.__init__`` seeded ``_channel_letters`` with X/Y/Z(/W)
        # before invoking ``_build_ui``; swap it to R/G/B(/A) post-init so the
        # attribute is correct regardless of whether ``_build_ui`` ran (tests
        # that stub ``_build_ui`` via the ``no_ui`` fixture still pin on the
        # letter list). The per-letter STYLE names inside ``_build_ui`` stay
        # on X/Y/Z/W because property attribute builder behavior has R/G/B/A reuse the axis palette
        # (blue/green/orange/red).
        self._channel_letters = (
            _COLOR3_CHANNEL_LETTERS if n_components == 3
            else _COLOR4_CHANNEL_LETTERS
        )

    def _build_ui(self) -> None:
        # ``_build_ui`` runs from inside ``_VecFloatRow.__init__`` BEFORE the
        # ``_ColorFloatRow.__init__`` tail swaps ``_channel_letters`` to
        # R/G/B(/A); use a local lookup here so the Labels get the correct
        # text even on the first build. The post-hoc ``_channel_letters``
        # reassign in ``__init__`` is what no_ui-style headless tests pin on.
        color_letters = (
            _COLOR3_CHANNEL_LETTERS if self._n_components == 3
            else _COLOR4_CHANNEL_LETTERS
        )
        per_component = self._adapter.get_per_component_ambiguity(self._prop.name)
        whole_ambiguous = self._model.is_ambiguous
        readonly = self._model.is_readonly
        value = self._model.get_value()
        # Step 8.1 — reset the separator list before appending so repeat
        # ``_build_ui`` invocations (e.g. the no_ui fixture's stub swap) do
        # not compound entries across rebuilds.
        self._separators = []
        component_width = _component_value_width(
            self._n_components,
            include_channel_labels=True,
            trailing_width=_COLOR_SWATCH_WIDTH,
        )
        row_hstack = ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=2)
        with row_hstack:
            self._label = _build_attribute_label_slot(self._prop, self._match)
            with ui.HStack(width=_VALUE_COLUMN_WIDTH, spacing=_COMPONENT_SPACING):
                for i in range(self._n_components):
                    if i > 0:
                        self._separators.append(_build_component_separator())
                    if per_component is not None and i < len(per_component):
                        channel_mixed = per_component[i]
                    else:
                        channel_mixed = whole_ambiguous
                    axis = _COLOR_CHANNEL_STYLE_AXIS[i]
                    label = ui.Label(
                        color_letters[i],
                        width=_COMPONENT_LABEL_WIDTH,
                        style_type_name_override=f"Property.ChannelLabel.{axis}",
                        name="mixed" if channel_mixed else "",
                    )
                    self._channel_labels[i] = label
                    with ui.ZStack(width=component_width):
                        widget = ui.FloatDrag(
                            style_type_name_override=_VALUE_FIELD_STYLE,
                            **_drag_kwargs_from_metadata(self._prop),
                        )
                        widget.enabled = not readonly
                        self._widgets[i] = widget
                        if value is not None and i < len(value):
                            widget.model.set_value(float(value[i]))
                        widget.model.add_begin_edit_fn(self._on_begin_edit)
                        widget.model.add_value_changed_fn(
                            lambda m, idx=i: self._on_component_changed(m, idx)
                        )
                        widget.model.add_end_edit_fn(self._on_end_edit)
                        self._overlay_labels[i] = ui.Label(
                            "Mixed",
                            alignment=ui.Alignment.CENTER,
                            style_type_name_override="Property.MixedOverlay",
                            visible=channel_mixed,
                        )
                self._swatch = ui.Rectangle(
                    width=_COLOR_SWATCH_WIDTH,
                    height=18,
                    style_type_name_override="Property.ColorSwatch",
                    style={
                        "background_color": _pack_color_abgr(value, self._n_components),
                    },
                )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _refresh_swatch(self) -> None:
        if self._swatch is None:
            return
        value = self._model.get_value()
        self._swatch.style = {
            "background_color": _pack_color_abgr(value, self._n_components),
        }

    def _on_model_value_changed(self) -> None:
        # The inherited ``_on_model_value_changed`` returns early during an
        # in-flight edit (``self._model.editing is True``) so the base keeps
        # the dragged FloatDrag widgets unclobbered — but the swatch is a
        # display-only preview, so it should always track the current model
        # value. Refreshing after super() covers both:
        # * edits driven by ``_on_component_changed`` → model.set_value →
        #   this callback (base early-returns, swatch still repaints);
        # * external backing changes (base updates all widgets, swatch
        #   repaints once at the end).
        super()._on_model_value_changed()
        if not self._updating:
            self._refresh_swatch()


class Color3fAttributeRow(_ColorFloatRow):
    """Label + 3× FloatDrag (R/G/B) + swatch for ``color3f`` / ``color3d``."""

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        super().__init__(prop, adapter, n_components=3, match=match)


class Color4fAttributeRow(_ColorFloatRow):
    """Label + 4× FloatDrag (R/G/B/A) + swatch for ``color4f`` / ``color4d``."""

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        super().__init__(prop, adapter, n_components=4, match=match)


_MATRIX_SUPPORTED_DIMS = (2, 3, 4)


class MatrixAttributeRow:
    """Label + N×N grid of FloatDrag cells for ``matrix2d`` / ``matrix3d`` /
    ``matrix4d`` attributes.

    Introduced in Step 3.5 of the property inspector implementation (property attribute builder behavior). USD matrix
    types are stored as a flat tuple of ``n_dim * n_dim`` Python floats in
    row-major order — matching USD's ``Gf.Matrix2d`` / ``Gf.Matrix3d`` /
    ``Gf.Matrix4d`` constructor convention (``Gf.Matrix3d(a, b, c, d, e, f,
    g, h, i)`` builds row 0 = ``(a, b, c)``, row 1 = ``(d, e, f)``, …).

    Layout:

    * Outer ``ui.HStack`` — label (``display_name``) on the left occupies
      one fraction, the grid column occupies the other.
    * Inner ``ui.VStack`` — one ``ui.HStack`` per matrix row, each
      containing ``n_dim`` ``ui.FloatDrag`` cells.

    ``_on_component_changed(widget_model, flat_index)`` routes each cell's
    edit through the shared :class:`AttributeModelBase` — the inherited
    ``change_on_edit_end=True`` default defers the write until edit ends
    so typing an N-digit value doesn't spam the adapter mid-keystroke.

    Per-cell ambiguity is not yet surfaced (matrices are NOT in
    ``_VECTOR_VALUE_TYPES``, so ``get_per_component_ambiguity`` returns
    ``None``). The whole-attribute ``is_ambiguous`` flag drives the
    ``Mixed`` overlay visibility uniformly across every cell — a simple
    "mixed everywhere" signal until Phase 8 polish adds per-cell
    granularity if a real scene needs it.
    """

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        n_dim: int,
        match: str = "",
    ) -> None:
        if n_dim not in _MATRIX_SUPPORTED_DIMS:
            raise ValueError(
                f"MatrixAttributeRow: n_dim must be 2, 3, or 4 — got {n_dim}"
            )
        self._prop = prop
        self._adapter = adapter
        self._match = match
        self._n_dim = n_dim
        self._n_cells = n_dim * n_dim
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._widgets: List[Optional[ui.FloatDrag]] = [None] * self._n_cells
        self._label: Optional[HighlightLabel] = None
        self._overlay_labels: List[Optional[ui.Label]] = [None] * self._n_cells
        # Step 8.1 — flat list of component separators laid out in
        # row-major order, matching ``_widgets`` / ``_overlay_labels``.
        # Each matrix row contributes ``n_dim - 1`` separators (between
        # its inline cells), so the total count is
        # ``(n_dim - 1) * n_dim``. There are no separators between
        # matrix rows: the outer ``ui.VStack`` already visually separates
        # them, and adding horizontal row rules would overstate the otherwise
        # blended Property section chrome.
        self._separators: List[Optional[ui.Rectangle]] = []
        self._indicator: Optional[ControlStateIndicator] = None
        self._updating = False
        self._active_context_menu: Optional[Any] = None
        self._value_sub = self._model.subscribe_value_changed(self._on_model_value_changed)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)
        self._build_ui()

    def _build_ui(self) -> None:
        mixed = self._model.is_ambiguous
        readonly = self._model.is_readonly
        value = self._model.get_value()
        self._separators = []
        component_width = _component_value_width(
            self._n_dim,
            include_channel_labels=False,
        )
        row_hstack = ui.HStack(spacing=4)
        with row_hstack:
            self._label = _build_attribute_label_slot(
                self._prop, self._match, alignment=ui.Alignment.LEFT_TOP,
            )
            with ui.VStack(width=_VALUE_COLUMN_WIDTH, spacing=2):
                for row in range(self._n_dim):
                    with ui.HStack(
                        height=_ATTRIBUTE_ROW_HEIGHT,
                        spacing=_COMPONENT_SPACING,
                    ):
                        for col in range(self._n_dim):
                            if col > 0:
                                self._separators.append(
                                    _build_component_separator()
                                )
                            flat = row * self._n_dim + col
                            with ui.ZStack(width=component_width):
                                widget = ui.FloatDrag(
                                    style_type_name_override=_VALUE_FIELD_STYLE,
                                    **_drag_kwargs_from_metadata(self._prop),
                                )
                                widget.enabled = not readonly
                                self._widgets[flat] = widget
                                if value is not None and flat < len(value):
                                    widget.model.set_value(float(value[flat]))
                                widget.model.add_begin_edit_fn(self._on_begin_edit)
                                widget.model.add_value_changed_fn(
                                    lambda m, idx=flat: self._on_component_changed(m, idx)
                                )
                                widget.model.add_end_edit_fn(self._on_end_edit)
                                self._overlay_labels[flat] = ui.Label(
                                    "Mixed",
                                    alignment=ui.Alignment.CENTER,
                                    style_type_name_override="Property.MixedOverlay",
                                    visible=mixed,
                                )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _on_begin_edit(self, widget_model: Any) -> None:
        _set_matching_value_field_focused(self._widgets, widget_model, True)
        self._model.begin_edit()

    def _on_component_changed(self, widget_model: Any, index: int) -> None:
        if self._updating:
            return
        current = self._model.get_value()
        base = list(current) if current is not None else [0.0] * self._n_cells
        base[index] = widget_model.get_value_as_float()
        self._model.set_value(tuple(base))

    def _on_end_edit(self, widget_model: Any) -> None:
        _set_matching_value_field_focused(self._widgets, widget_model, False)
        self._model.end_edit()

    def _on_model_value_changed(self) -> None:
        if self._model.editing or self._updating:
            return
        value = self._model.get_value()
        if value is None:
            return
        self._updating = True
        try:
            for i, widget in enumerate(self._widgets):
                if widget is None or i >= len(value):
                    continue
                widget.model.set_value(float(value[i]))
        finally:
            self._updating = False


class Vec2IntAttributeRow(_VecIntRow):
    """Label + 2× IntDrag (X/Y) for int2 attributes."""

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        super().__init__(prop, adapter, n_components=2, match=match)


class Vec3IntAttributeRow(_VecIntRow):
    """Label + 3× IntDrag (X/Y/Z) for int3 attributes."""

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        super().__init__(prop, adapter, n_components=3, match=match)


class Vec4IntAttributeRow(_VecIntRow):
    """Label + 4× IntDrag (X/Y/Z/W) for int4 attributes."""

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        super().__init__(prop, adapter, n_components=4, match=match)


class IntAttributeRow:
    """Label + IntDrag for a single integer attribute."""

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        self._prop = prop
        self._adapter = adapter
        self._match = match
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._widget: Optional[ui.IntDrag] = None
        self._label: Optional[HighlightLabel] = None
        self._overlay: Optional[ui.Label] = None
        self._indicator: Optional[ControlStateIndicator] = None
        self._updating = False
        self._active_context_menu: Optional[Any] = None
        self._value_sub = self._model.subscribe_value_changed(self._on_model_value_changed)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)
        self._build_ui()

    def _build_ui(self) -> None:
        mixed = self._model.is_ambiguous
        row_hstack = ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=4)
        with row_hstack:
            self._label = _build_attribute_label_slot(self._prop, self._match)
            with ui.ZStack(width=_VALUE_COLUMN_WIDTH):
                self._widget = ui.IntDrag(
                    style_type_name_override=_VALUE_FIELD_STYLE,
                    **_drag_kwargs_from_metadata(self._prop),
                )
                self._widget.enabled = not self._model.is_readonly
                value = self._model.get_value()
                if value is not None:
                    self._widget.model.set_value(int(value))
                self._widget.model.add_begin_edit_fn(self._on_begin_edit)
                self._widget.model.add_value_changed_fn(self._on_value_changed)
                self._widget.model.add_end_edit_fn(self._on_end_edit)
                self._overlay = ui.Label(
                    "Mixed",
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Property.MixedOverlay",
                    visible=mixed,
                )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _on_begin_edit(self, widget_model: Any) -> None:
        _set_value_field_focused(self._widget, True)
        self._model.begin_edit()

    def _on_value_changed(self, widget_model: Any) -> None:
        if self._updating:
            return
        self._model.set_value(widget_model.get_value_as_int())

    def _on_end_edit(self, widget_model: Any) -> None:
        _set_value_field_focused(self._widget, False)
        self._model.end_edit()

    def _on_model_value_changed(self) -> None:
        if self._widget is None or self._model.editing or self._updating:
            return
        value = self._model.get_value()
        if value is None:
            return
        self._updating = True
        try:
            self._widget.model.set_value(int(value))
        finally:
            self._updating = False


class TokenAttributeRow:
    """Label + ComboBox for a token attribute whose metadata defines
    ``allowed_values`` (USD ``allowedTokens`` for token-typed attributes).

    The builder in ``ovwidgets.property/builders/token.py`` dispatches here when
    ``metadata.allowed_values`` is a non-empty list of strings. When
    ``allowed_values`` is missing or empty the builder falls back to
    :class:`StringAttributeRow` — no widget overlap, so that fallback path
    is intentionally NOT handled inside this class.

    Routes edits through an owned :class:`AttributeModelBase` (attribute edit transaction behavior):
    a selection change wraps ``begin_edit`` → ``set_value`` → ``end_edit``
    since the ComboBox commits atomically (no drag). The backing-change
    subscription updates the selected index when an external edit lands.

    Introduced in Step 3.3 of the property inspector implementation (property attribute builder behavior).
    """

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        self._prop = prop
        self._adapter = adapter
        self._match = match
        self._allowed_values: List[str] = [str(v) for v in (prop.allowed_values or [])]
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._widget: Optional[ui.ComboBox] = None
        self._label: Optional[HighlightLabel] = None
        self._overlay: Optional[ui.Label] = None
        self._indicator: Optional[ControlStateIndicator] = None
        self._updating = False
        self._active_context_menu: Optional[Any] = None
        self._value_sub = self._model.subscribe_value_changed(self._on_model_value_changed)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)
        self._build_ui()

    def _current_index(self) -> int:
        """Index of the current adapter value within ``allowed_values``.

        Falls back to 0 (first allowed value) if the current value is
        ``None``, ambiguous, or not in the allowed list. A missing value
        surfacing as "first option" is the same convention Kit's
        ``TfTokenAttributeModel`` uses when the authored token drifts
        outside the schema's ``allowedTokens`` list.
        """
        value = self._model.get_value()
        if value is None:
            return 0
        try:
            return self._allowed_values.index(str(value))
        except ValueError:
            return 0

    def _build_ui(self) -> None:
        mixed = self._model.is_ambiguous
        row_hstack = ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=4)
        with row_hstack:
            self._label = _build_attribute_label_slot(self._prop, self._match)
            with ui.ZStack(width=_VALUE_COLUMN_WIDTH):
                ui.Rectangle(style_type_name_override="Property.DropdownFieldBorder")
                start_idx = self._current_index()
                with ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT):
                    ui.Spacer(width=_DROPDOWN_BORDER_INSET)
                    with ui.VStack(width=_VALUE_COLUMN_WIDTH - 2 * _DROPDOWN_BORDER_INSET):
                        ui.Spacer(height=_DROPDOWN_BORDER_INSET)
                        self._widget = ui.ComboBox(
                            start_idx,
                            *self._allowed_values,
                            width=_VALUE_COLUMN_WIDTH - 2 * _DROPDOWN_BORDER_INSET,
                            height=_ATTRIBUTE_ROW_HEIGHT - 2 * _DROPDOWN_BORDER_INSET,
                            style_type_name_override=_DROPDOWN_VALUE_FIELD_STYLE,
                            no_arrow_button=True,
                        )
                        ui.Spacer(height=_DROPDOWN_BORDER_INSET)
                    ui.Spacer(width=_DROPDOWN_BORDER_INSET)
                self._widget.enabled = not self._model.is_readonly
                self._widget.model.add_item_changed_fn(self._on_item_changed)
                _build_combobox_chevron_overlay()
                self._overlay = ui.Label(
                    "Mixed",
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Property.MixedOverlay",
                    visible=mixed,
                )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _on_item_changed(self, item_model: Any, item: Any) -> None:
        """Handle a ComboBox selection change.

        ``add_item_changed_fn`` fires with ``item=None`` when the root
        index changes (user picked a new option) and with a non-None
        ``item`` handle for per-option string-model edits (which the
        ComboBox itself never triggers — the strings are static). Only
        the root-index path commits a new value.
        """
        if self._updating or item is not None:
            return
        root_model = item_model.get_item_value_model(None)
        idx = root_model.get_value_as_int()
        if not (0 <= idx < len(self._allowed_values)):
            return
        selected = self._allowed_values[idx]
        current = self._model.get_value()
        if current is not None and str(current) == selected:
            return
        self._model.begin_edit()
        self._model.set_value(selected)
        self._model.end_edit()

    def _on_model_value_changed(self) -> None:
        if self._widget is None or self._model.editing or self._updating:
            return
        value = self._model.get_value()
        if value is None:
            return
        try:
            idx = self._allowed_values.index(str(value))
        except ValueError:
            return
        self._updating = True
        try:
            root_model = self._widget.model.get_item_value_model(None)
            if root_model.get_value_as_int() != idx:
                root_model.set_value(idx)
        finally:
            self._updating = False


def is_relative_path(path: str) -> bool:
    """Return ``True`` when ``path`` is a relative filesystem-style asset path.

    Handles the three absolute asset-path shapes used by AttributeModel:

    * POSIX absolute (leading ``/`` — covers ``//`` UNC too);
    * Windows drive-letter absolute (``C:\\foo``, ``c:/foo``, etc.);
    * URL/URI schemes (``omniverse://``, ``http://``, ``file://``, …).

    Everything else — including the empty string — is treated as relative.
    Pure function; no ovui/USD dependencies, so callers may use it from
    the adapter layer or tests without spinning up a UI context.

    The helper is defined NOW because Step 3.6 registers the asset-path
    row; the "Make Absolute" button that consumes ``is_relative_path`` is
    scheduled for a later phase (property attribute builder behavior, the property inspector behavior describes Kit's equivalent).
    """
    if not isinstance(path, str):
        return True
    if not path:
        return True
    if path.startswith("/"):
        return False
    if "://" in path:
        return False
    # Windows drive letter: single letter + ':' + optional separator.
    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        return False
    return True


class AssetPathAttributeRow:
    """Label + ``ui.StringField`` + folder button for a USD ``asset`` attribute.

    Introduced in Step 3.6 of the property inspector implementation (property metadata behavior / §4.3.5).
    USD asset-path attributes carry a filesystem-style or URL path (e.g.
    ``./textures/noise.png``, ``/mnt/project/scene.usd``,
    ``omniverse://server/assets/character.usd``). The row:

    * Renders the authored path inside an editable
      :class:`omni.ui.StringField` (same edit pattern as
      :class:`StringAttributeRow` — commit on ``end_edit``);
    * Shows a small folder button on the right. Clicking it is a no-op
      in Step 3.6 — the
      :mod:`omni.kit.window.file_importer` hook lands in a later phase
      per the property inspector behavior;
    * Surfaces ``adapter.get_resolved_asset_path`` as a tooltip on the
      StringField when the adapter resolves the authored path to an
      absolute filesystem location (Kit's
      :class:`SdfAssetPathAttributeModel` does the same — see
      the property inspector behavior). Adapters that can't resolve
      return ``None`` and no tooltip is set.

    Commits route through an owned :class:`AttributeModelBase`
    (Step 1.4); ``begin_edit`` snapshots the pre-edit value so the undo
    group captures a clean before/after pair.
    """

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        self._prop = prop
        self._adapter = adapter
        self._match = match
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._widget: Optional[ui.StringField] = None
        self._folder_button: Optional[ui.Button] = None
        self._label: Optional[HighlightLabel] = None
        self._overlay: Optional[ui.Label] = None
        self._indicator: Optional[ControlStateIndicator] = None
        self._start_value: str = ""
        self._updating = False
        self._active_context_menu: Optional[Any] = None
        self._value_sub = self._model.subscribe_value_changed(self._on_model_value_changed)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)
        self._build_ui()

    def _resolved_tooltip(self) -> str:
        """Resolved absolute path for the tooltip, or ``""`` when unavailable.

        Delegates to :meth:`PropertyAdapter.get_resolved_asset_path`; the
        ABC default returns ``None``. Returning an empty string keeps
        :attr:`ui.StringField.tooltip` from rendering a "None" glyph
        when no resolver is wired up.
        """
        resolved = self._adapter.get_resolved_asset_path(self._prop.name)
        return "" if resolved is None else str(resolved)

    def _build_ui(self) -> None:
        mixed = self._model.is_ambiguous
        readonly = self._model.is_readonly
        row_hstack = ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=4)
        with row_hstack:
            self._label = _build_attribute_label_slot(self._prop, self._match)
            with ui.ZStack(width=_VALUE_COLUMN_WIDTH):
                with ui.HStack(spacing=2):
                    self._widget = ui.StringField(
                        style_type_name_override=_VALUE_FIELD_STYLE,
                    )
                    self._widget.enabled = not readonly
                    value = self._model.get_value()
                    if value is not None:
                        self._widget.model.set_value(str(value))
                    tooltip = self._resolved_tooltip()
                    if tooltip:
                        self._widget.tooltip = tooltip
                    self._widget.model.add_begin_edit_fn(self._on_begin_edit)
                    self._widget.model.add_end_edit_fn(self._on_end_edit)
                    # Step 3.6: the folder button is a no-op placeholder; the
                    # file-picker hook lands with ``omni.kit.window.file_importer``
                    # integration in a later phase.
                    self._folder_button = ui.Button(
                        "...",
                        width=22,
                        clicked_fn=self._on_folder_clicked,
                        style_type_name_override="Property.AssetPathFolderButton",
                    )
                    self._folder_button.enabled = not readonly
                self._overlay = ui.Label(
                    "Mixed",
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Property.MixedOverlay",
                    visible=mixed,
                )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _on_folder_clicked(self) -> None:
        """No-op in Step 3.6. The file-picker integration (property inspector implementation /
        the property inspector behavior) will wire this to
        :mod:`omni.kit.window.file_importer` in a later phase.
        """
        return None

    def _on_begin_edit(self, widget_model: Any) -> None:
        _set_value_field_focused(self._widget, True)
        self._start_value = widget_model.get_value_as_string()
        self._model.begin_edit()

    def _on_end_edit(self, widget_model: Any) -> None:
        _set_value_field_focused(self._widget, False)
        if self._updating:
            return
        self._model.set_value(widget_model.get_value_as_string())
        self._model.end_edit()

    def _on_model_value_changed(self) -> None:
        if self._widget is None or self._model.editing or self._updating:
            return
        value = self._model.get_value()
        if value is None:
            return
        self._updating = True
        try:
            self._widget.model.set_value(str(value))
            tooltip = self._resolved_tooltip()
            if tooltip:
                self._widget.tooltip = tooltip
        finally:
            self._updating = False


def _format_relationship_targets(targets: Any) -> str:
    """Join a relationship's target paths into a single display string.

    Used by :class:`RelationshipAttributeRow` to render a tuple of target
    prim paths (as returned by :meth:`UsdPropertyAdapter.get_value` for a
    ``relationship``-typed attribute) in a read-only ``ui.StringField``.

    Shape:

    * ``None`` or empty sequence → ``""`` (empty StringField, no
      placeholder text — matches Kit's ``RelationshipAttributeModel``
      behaviour for unauthored relationships).
    * Single target → the path string (no join).
    * Multiple targets → ``", "``-joined string (single-line friendly;
      Kit's §9.8 spec uses the same format).

    Pure function; no ovui/USD dependencies, so callers may use it from
    the adapter layer or tests without spinning up a UI context.
    """
    if not targets:
        return ""
    return ", ".join(str(t) for t in targets)


class RelationshipAttributeRow:
    """Label + read-only ``ui.StringField`` for a USD ``Usd.Relationship``.

    Introduced in Step 3.7 of the property inspector implementation (property metadata behavior / §4.3.5,
    the property inspector behavior). USD relationships carry a list
    of target prim paths (``Usd.Relationship.GetTargets()`` returns a
    ``List[Sdf.Path]``); the adapter surfaces this as a ``tuple[str, ...]``
    through :meth:`PropertyAdapter.get_value`. The row renders that tuple
    as a comma-separated read-only string:

    * 0 targets → empty StringField.
    * 1 target → the path string verbatim.
    * N targets → ``", "``-joined summary.

    The StringField is instantiated with ``read_only=True`` so the user
    can copy target paths but not type new ones. A modal target picker
    (§9.8 ``RelationshipTargetPicker``) lands in a later phase — Step
    3.7 is display-only.

    The row still owns an :class:`AttributeModelBase` for consistency
    with every other Step-1.4 row and so external USD mutations (someone
    edits the relationship in a script, via a command, or through a
    different panel) land through ``adapter.subscribe_changes`` →
    ``model._on_backing_changed`` → ``_on_model_value_changed`` and
    refresh the StringField. No edit callbacks are wired, so the model's
    ``begin_edit`` / ``set_value`` / ``end_edit`` paths are never
    invoked from the UI side.
    """

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        self._prop = prop
        self._adapter = adapter
        self._match = match
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._widget: Optional[ui.StringField] = None
        self._label: Optional[HighlightLabel] = None
        self._overlay: Optional[ui.Label] = None
        self._indicator: Optional[ControlStateIndicator] = None
        self._updating = False
        self._active_context_menu: Optional[Any] = None
        self._value_sub = self._model.subscribe_value_changed(self._on_model_value_changed)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)
        self._build_ui()

    def _build_ui(self) -> None:
        mixed = self._model.is_ambiguous
        row_hstack = ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=4)
        with row_hstack:
            self._label = _build_attribute_label_slot(self._prop, self._match)
            with ui.ZStack(width=_VALUE_COLUMN_WIDTH):
                self._widget = ui.StringField(
                    read_only=True,
                    style_type_name_override=_VALUE_FIELD_STYLE,
                )
                self._widget.model.set_value(
                    _format_relationship_targets(self._model.get_value())
                )
                self._overlay = ui.Label(
                    "Mixed",
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Property.MixedOverlay",
                    visible=mixed,
                )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _on_model_value_changed(self) -> None:
        if self._widget is None or self._model.editing or self._updating:
            return
        self._updating = True
        try:
            self._widget.model.set_value(
                _format_relationship_targets(self._model.get_value())
            )
        finally:
            self._updating = False


class StringAttributeRow:
    """Label + StringField for a single string attribute.

    Commits on end_edit (focus lost / Enter). begin_edit records the
    pre-edit value so callers can implement revert-on-escape if needed.
    """

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        self._prop = prop
        self._adapter = adapter
        self._match = match
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._widget: Optional[ui.StringField] = None
        self._label: Optional[HighlightLabel] = None
        self._overlay: Optional[ui.Label] = None
        self._indicator: Optional[ControlStateIndicator] = None
        self._start_value: str = ""
        self._updating = False
        self._active_context_menu: Optional[Any] = None
        self._value_sub = self._model.subscribe_value_changed(self._on_model_value_changed)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)
        self._build_ui()

    def _build_ui(self) -> None:
        mixed = self._model.is_ambiguous
        row_hstack = ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=4)
        with row_hstack:
            self._label = _build_attribute_label_slot(self._prop, self._match)
            with ui.ZStack(width=_VALUE_COLUMN_WIDTH):
                self._widget = ui.StringField(
                    style_type_name_override=_VALUE_FIELD_STYLE,
                )
                self._widget.enabled = not self._model.is_readonly
                value = self._model.get_value()
                if value is not None:
                    self._widget.model.set_value(str(value))
                self._widget.model.add_begin_edit_fn(self._on_begin_edit)
                self._widget.model.add_end_edit_fn(self._on_end_edit)
                self._overlay = ui.Label(
                    "Mixed",
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Property.MixedOverlay",
                    visible=mixed,
                )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _on_begin_edit(self, widget_model: Any) -> None:
        _set_value_field_focused(self._widget, True)
        self._start_value = widget_model.get_value_as_string()
        self._model.begin_edit()

    def _on_end_edit(self, widget_model: Any) -> None:
        _set_value_field_focused(self._widget, False)
        if self._updating:
            return
        self._model.set_value(widget_model.get_value_as_string())
        self._model.end_edit()

    def _on_model_value_changed(self) -> None:
        if self._widget is None or self._model.editing or self._updating:
            return
        value = self._model.get_value()
        if value is None:
            return
        self._updating = True
        try:
            self._widget.model.set_value(str(value))
        finally:
            self._updating = False


class BoolAttributeRow:
    """Label + CheckBox for a single bool attribute — instant commit."""

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        self._prop = prop
        self._adapter = adapter
        self._match = match
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._widget: Optional[ui.CheckBox] = None
        self._label: Optional[HighlightLabel] = None
        self._overlay: Optional[ui.Label] = None
        self._indicator: Optional[ControlStateIndicator] = None
        self._updating = False
        self._active_context_menu: Optional[Any] = None
        self._value_sub = self._model.subscribe_value_changed(self._on_model_value_changed)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)
        self._build_ui()

    def _build_ui(self) -> None:
        mixed = self._model.is_ambiguous
        row_hstack = ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=4)
        with row_hstack:
            self._label = _build_attribute_label_slot(self._prop, self._match)
            # ZStack spans the value column so the "Mixed" overlay text has
            # room to render; the CheckBox stays pinned on the left inside a
            # 24px row slot so its visible 18px square aligns to label text.
            with ui.ZStack(width=_VALUE_COLUMN_WIDTH):
                with ui.HStack():
                    self._widget = _build_aligned_checkbox()
                    self._widget.enabled = not self._model.is_readonly
                    ui.Spacer()
                value = self._model.get_value()
                if value is not None:
                    self._widget.model.set_value(bool(value))
                self._widget.model.add_value_changed_fn(self._on_value_changed)
                self._overlay = ui.Label(
                    "Mixed",
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Property.MixedOverlay",
                    visible=mixed,
                )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _on_value_changed(self, widget_model: Any) -> None:
        if self._updating:
            return
        self._model.begin_edit()
        self._model.set_value(widget_model.get_value_as_bool())
        self._model.end_edit()

    def _on_model_value_changed(self) -> None:
        if self._widget is None or self._model.editing or self._updating:
            return
        value = self._model.get_value()
        if value is None:
            return
        self._updating = True
        try:
            self._widget.model.set_value(bool(value))
        finally:
            self._updating = False


# Module-level threshold mirroring ``ovui_data_adapters.openusd.property_adapter._BIG_ARRAY_THRESHOLD``.
# Duplicated here (rather than imported) so the formatter stays pure-python
# and importable without a USD dependency — the adapter module imports pxr
# eagerly, which the ovwidgets.property layer must not transitively pull in.
# Both constants must stay in sync; see BUG-D005 in QA-BUGS-DEEP.md.
_BIG_ARRAY_THRESHOLD = 16


def _normalize_array_element(x: Any) -> Any:
    """Coerce a per-element array value to a plain-Python repr-friendly form.

    Used by :func:`_format_array_value`. USD ships composite values as
    ``Gf.Vec3f`` / ``Gf.Vec4d`` / ``Gf.Matrix4d`` wrappers; ``str()`` on
    those types emits the class-prefixed form (``"Gf.Vec3f(1.0, 2.0, 3.0)"``)
    which leaks adapter-layer detail into the Property Inspector
    (BUG-D005). This helper flattens each wrapper to a plain tuple of
    floats/ints so the outer ``str(tuple(...))`` produces
    ``"((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))"`` instead. Scalars (``int``,
    ``float``, ``str``, ``bool``) pass through unchanged.

    Pure Python; duck-types off ``__iter__`` so the formatter never needs
    to import ``pxr.Gf`` (and the ovwidgets.property module stays USD-free).
    """
    if isinstance(x, (int, float, bool, str, bytes, complex)) or x is None:
        return x
    try:
        return tuple(_normalize_array_element(e) for e in x)
    except TypeError:
        return x


def _format_array_value(value: Any, is_big_array: Optional[bool] = None) -> str:
    """Render an array attribute's value as a read-only display string.

    Used by :class:`ArrayAttributeRow`. Shape follows property metadata behavior and
    the property inspector behavior:

    * ``is_big_array=True`` → ``"[N items]"`` where ``N`` is the authored
      length. Never formats the elements — for a 10k-element ``points``
      array, element formatting would stall the panel build.
    * ``is_big_array=False`` → ``str(tuple(value))`` — the full tuple
      repr (e.g. ``"(1.0, 2.0, 3.0)"``).
    * ``is_big_array=None`` (auto-detect) → compute from the value's
      current ``__len__``. This is what the row's live-refresh path uses
      so a USD edit that crosses the threshold (5 elements → 50000)
      re-selects the correct display mode (BUG-D005). Cached metadata
      is frozen at row-build time, so using it here would leave the
      display stuck on the initial mode.
    * ``None`` value → ``""`` (empty field; same shape as the relationship
      formatter handles an unauthored rel).

    Pure function; no ovui/USD dependencies so the formatter is
    importable from the adapter layer or tests without a UI context.
    Introduced in Step 3.8 of the property inspector implementation; auto-detect branch added
    in the BUG-D005 fix.
    """
    if value is None:
        return ""
    # Compute length once; reused by both the auto-detect branch and the
    # "[N items]" formatter so we never double-read the VtArray.
    try:
        length = len(value)
    except TypeError:
        return str(value)
    if is_big_array is None:
        is_big_array = length > _BIG_ARRAY_THRESHOLD
    if is_big_array:
        return f"[{length} items]"
    try:
        # Normalize each element so Gf.Vec* / Gf.Matrix* wrappers flatten
        # to plain tuples — otherwise Extent on a Sphere prints as
        # ``"(Gf.Vec3f(-1.0, -1.0, -1.0), …)"`` (BUG-D005). Scalar
        # elements (int/float/str) fall through unchanged so the tests
        # that pass ``(1, 2, 3)`` still render ``"(1, 2, 3)"``.
        return str(tuple(_normalize_array_element(e) for e in value))
    except TypeError:
        return str(value)


class ArrayAttributeRow:
    """Label + read-only ``ui.StringField`` for an array-typed attribute.

    Introduced in Step 3.8 of the property inspector implementation (property metadata behavior / §4.3.5,
    the property inspector behavior). USD array attributes
    (``float[]``, ``token[]``, ``float3[]``, …) are routed through the
    single ``"array"`` sentinel the USD adapter emits as
    ``metadata.type_name``; the row renders the value as a read-only
    string:

    * ``metadata.is_big_array=True`` (length > 16) → ``"[N items]"``.
      Never expands the full element list — avoids the O(N) format cost
      that would stall the panel build for geometry arrays like
      ``points`` or ``faceVertexIndices``.
    * ``metadata.is_big_array=False`` → ``str(tuple(value))`` — the full
      tuple repr.

    Read-only only. An interactive array editor (e.g. Kit's
    ``SdfAssetPathDelegate`` TreeView from §9.6) lands in a later phase;
    until then the StringField is ``read_only=True``, so the user can
    select/copy the display string but never author a new value.

    The row still owns an :class:`AttributeModelBase` — consistent with
    every Step-1.4+ row — so external USD edits (a script, a command, a
    neighbouring panel) land through ``adapter.subscribe_changes`` →
    ``model._on_backing_changed`` → ``_on_model_value_changed`` and
    refresh the display. No ``_on_begin_edit`` / ``_on_end_edit`` /
    ``_on_value_changed`` callbacks are wired — the row never drives
    ``model.set_value`` from the UI side.
    """

    def __init__(
        self,
        prop: AttributeMetadata,
        adapter: PropertyAdapter,
        match: str = "",
    ) -> None:
        self._prop = prop
        self._adapter = adapter
        self._match = match
        self._model = AttributeModelBase(adapter, prop.name, prop)
        self._widget: Optional[ui.StringField] = None
        self._label: Optional[HighlightLabel] = None
        self._overlay: Optional[ui.Label] = None
        self._indicator: Optional[ControlStateIndicator] = None
        self._updating = False
        self._active_context_menu: Optional[Any] = None
        self._value_sub = self._model.subscribe_value_changed(self._on_model_value_changed)
        self._adapter_sub = adapter.subscribe_changes(self._model._on_backing_changed)
        self._build_ui()

    def _build_ui(self) -> None:
        mixed = self._model.is_ambiguous
        row_hstack = ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=4)
        with row_hstack:
            self._label = _build_attribute_label_slot(self._prop, self._match)
            with ui.ZStack(width=_VALUE_COLUMN_WIDTH):
                self._widget = ui.StringField(
                    read_only=True,
                    style_type_name_override=_VALUE_FIELD_STYLE,
                )
                self._widget.model.set_value(
                    _format_array_value(
                        self._model.get_value(), self._prop.is_big_array
                    )
                )
                self._overlay = ui.Label(
                    "Mixed",
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Property.MixedOverlay",
                    visible=mixed,
                )
            self._indicator = ControlStateIndicator(
                self._model, self._adapter, self._prop.name
            )
        _wire_row_context_menu(row_hstack, self)

    def _on_model_value_changed(self) -> None:
        if self._widget is None or self._model.editing or self._updating:
            return
        self._updating = True
        try:
            # Pass ``is_big_array=None`` so the formatter auto-detects from
            # the current value's length. ``self._prop.is_big_array`` is
            # frozen at row-build time, so a USD edit that crosses the
            # threshold (5 ↔ 50_000 elements) would otherwise keep the row
            # stuck on the initial display mode (BUG-D005).
            self._widget.model.set_value(
                _format_array_value(self._model.get_value())
            )
        finally:
            self._updating = False


class _FallbackAttributeRow:
    """Read-only label shown for unsupported attribute types.

    Step 4.3: the row no longer builds a bare ``ui.Label`` — it now wraps
    the label in an ``ui.HStack`` so a 20 px trailing slot stays
    column-aligned with every supported row's
    :class:`ControlStateIndicator`. The slot is an empty ``ui.Spacer``
    rather than a real indicator: the fallback has no typed model, so
    no metadata-driven predicate (Locked / TimeSampled / NotDefault)
    can fire meaningfully, and constructing an :class:`AttributeModelBase`
    would duplicate work the row already decided not to do (the
    fallback means "we don't know how to render this type"). The
    spacer preserves row alignment without exposing a dead click path.
    """

    def __init__(self, prop: AttributeMetadata, adapter: Any = None) -> None:
        self._prop = prop
        self._build_ui()

    def _build_ui(self) -> None:
        with ui.HStack(height=_ATTRIBUTE_ROW_HEIGHT, spacing=4):
            with ui.Frame(width=ui.Fraction(1), horizontal_clipping=True):
                with ui.ZStack():
                    ui.Label(
                        f"(unsupported {self._prop.type_name})",
                        style_type_name_override="Property.FallbackAttribute",
                    )
            ui.Spacer(width=_VALUE_COLUMN_WIDTH)
            ui.Spacer(width=_CONTROL_STATE_SLOT_WIDTH)


# TODO: remove after phase 3.
def build_attribute_row(
    prop: AttributeMetadata,
    adapter: PropertyAdapter,
) -> Any:
    """Deprecated thin forwarder to :class:`WidgetBuilderTable`.

    Step 1.3 of the property inspector implementation moved the live dispatch into
    :class:`ovwidgets.property.builders.WidgetBuilderTable`. The forwarder
    remains so existing tests (``tests/test_attribute_rows.py``,
    ``tests/test_multi_selection_property.py``,
    ``tests/test_performance.py``) that call this function by name
    continue to pass. New callers should dispatch through the table.
    """
    from ovwidgets.property.builders import WidgetBuilderTable
    return WidgetBuilderTable.build(prop.name, prop, adapter)
