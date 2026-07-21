# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Control state indicator for an attribute row.

property control-state behavior and the property inspector behavior The control state system
places a small icon to the right of each property value widget,
signalling the attribute's current state — mixed values across the
selection, a locked layer, a time-sampled (animated) attribute, a value
that differs from the schema default, and so on.

Step 4.3 lands the registry infrastructure and the four built-in
handlers; Step 4.4 lands production SVG assets and wires them to the
handlers via :mod:`ovui_widgets.common.style.urls`. Rendering is dual-mode: when
running under Kit (``omni.ui._IN_KIT`` True), the indicator builds a
``ui.Image(source_url=state.icon_path)`` so the SVG glyph renders. In
the standalone omni.ui build (used by ovgear's headless tests and dev
VM) SVG rendering through ``ui.Image`` is not supported — a small
probe at import time (``_SVG_RENDERING_AVAILABLE``) falls back to the
Step-4.3 ``ui.Rectangle`` + per-state style selector. Both paths share
the ``Property.ControlState`` style type and the same ``::mixed /
::locked / ::timesampled / ::notdefault`` state selectors, so the
per-state colour comes from the theme in either mode.

Architecture
------------

:class:`ControlStateManager` — process-wide singleton that owns a
priority-ordered list of :class:`ControlStateHandler` entries. Lower
priority number wins: an attribute that is simultaneously ambiguous AND
authored shows the Mixed icon (priority 0), not NotDefault (priority 40).
Third-party extensions can register their own state via
:meth:`ControlStateManager.register_state`; the returned subscription
cancels the registration.

:class:`ControlStateIndicator` — one compact dot inside a
20 px-wide ``ui.HStack`` slot on the right edge of an attribute row. At
build time and on every model value change it calls
:meth:`ControlStateManager.get_active_state` and updates its style name
/ click handler / tooltip. When no handler matches, the square is
hidden while the slot's width is preserved so rows stay column-aligned.

Defaults
--------

* ``Mixed`` (priority 0) — fires when ``model.is_ambiguous`` is True
  (per-selection value disagreement, from Phase 2). Informational
  (``on_click=None``).
* ``Locked`` (priority 20) — fires on ``metadata.is_locked``.
  Informational.
* ``TimeSampled`` (priority 30) — fires on ``metadata.is_time_sampled``.
  Informational.
* ``NotDefault`` (priority 40) — fires on ``metadata.is_authored`` AND
  when the adapter's explicit property capabilities include
  ``clear_values``. ``on_click`` clears the authored opinion and reverts
  the row to the schema default.

Per the "Icon hidden when ``on_click`` is None or not callable" rule in
the property inspector implementation §4.3: NotDefault's predicate folds the
adapter-capability check in, so an adapter without a functional
``clear_value`` never reaches the click path. If a future handler wants
a runtime callable-check, the indicator still guards the click path
with ``callable(state.on_click)`` before attaching ``set_mouse_pressed_fn``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

import omni.ui as ui
from ovui_data_adapters.common import PropertyAdapter

from ovui_widgets.common.style.urls import get_icon_path
from ovui_widgets.property.parts.property_capabilities import (
    adapter_supports_clear_values,
)

# ``omni.ui._IN_KIT`` is a module constant the omni.ui build sets to True
# when running under the Kit runtime (full SVG/Image pipeline) and False
# for the standalone GLFW/Vulkan build used by ovgear's dev VM. ``getattr``
# with a False default keeps the probe safe against future omni.ui builds
# that might remove the constant. Standalone builds have historically failed
# to render SVG files from absolute paths, which motivates this split.
_SVG_RENDERING_AVAILABLE: bool = bool(getattr(ui, "_IN_KIT", False))


# ---------------------------------------------------------------------------
# Handler descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ControlStateHandler:
    """Descriptor for one registered control-state handler.

    Stored inside :class:`ControlStateManager` and returned by
    :meth:`ControlStateManager.get_active_state`. Instances are frozen so
    a handler returned to a caller cannot be mutated out from under the
    manager's internal list; re-registration under the same name is
    rejected at :meth:`register_state` time.

    Fields:

    * ``name`` — unique identifier, also the key for unregister.
    * ``predicate`` — callable taking an ``AttributeModelBase`` and
      returning ``True`` when this state applies to that model.
    * ``icon_path`` — filesystem path to the icon image (SVG or PNG).
      The four built-in handlers point at the per-state SVGs under
      ``ovui_widgets.app/style/icons/`` (Step 4.4); third-party handlers should
      pass an absolute path so the Kit-side ``ui.Image`` can load it
      without a resource base URL.
    * ``priority`` — float; lower wins. 0 = highest visual precedence.
    * ``on_click`` — optional ``(adapter, attr_name) -> None`` callable
      invoked on left-click. ``None`` for informational states. The
      indicator still shows the icon when ``on_click`` is ``None`` —
      only states whose *predicate* returns False are hidden.
    * ``tooltip`` — optional tooltip string shown on hover.
    """

    name: str
    predicate: Callable[[Any], bool]
    icon_path: str
    priority: float
    on_click: Optional[Callable[[PropertyAdapter, str], None]] = None
    tooltip: Optional[str] = None


# ---------------------------------------------------------------------------
# Subscription handle
# ---------------------------------------------------------------------------


class _HandlerSubscription:
    """RAII handle returned by :meth:`ControlStateManager.register_state`.

    Mirrors the ``_ValueChangeSubscription`` / ``_BuilderSubscription``
    pattern elsewhere in ovui_widgets.property: callers hold the handle to keep
    the registration live, then call ``cancel()`` to remove it. No
    ``__del__`` auto-cancel — anonymous-subscription lifetimes would
    otherwise cancel before the first event.

    A second ``cancel()`` is a no-op. ``cancel()`` only removes the
    registration if the manager still has a handler under the same
    name; it never evicts a replacement registered after this handle
    was issued.
    """

    def __init__(self, manager: "ControlStateManager", name: str) -> None:
        self._manager: Optional["ControlStateManager"] = manager
        self._name: Optional[str] = name

    def cancel(self) -> None:
        if self._manager is None or self._name is None:
            return
        self._manager._remove_state(self._name)
        self._manager = None
        self._name = None


# ---------------------------------------------------------------------------
# Manager singleton
# ---------------------------------------------------------------------------


class ControlStateManager:
    """Priority-ordered registry of control-state handlers.

    The singleton is populated at first ``get_instance()`` call with the
    four built-in handlers (Mixed, Locked, TimeSampled, NotDefault).
    Third-party registrations slot in by priority: a priority between
    two built-ins inserts between them on :meth:`get_active_state` walks.
    """

    _instance: Optional["ControlStateManager"] = None

    def __init__(self) -> None:
        self._handlers: List[ControlStateHandler] = []

    @classmethod
    def get_instance(cls) -> "ControlStateManager":
        """Return the process-wide singleton, creating it on first call.

        Defaults are registered in ``_register_defaults`` immediately
        after construction so every caller that touches the singleton
        sees the four built-in states regardless of import order.
        """
        if cls._instance is None:
            cls._instance = cls()
            _register_defaults(cls._instance)
        return cls._instance

    @classmethod
    def _reset_for_tests(cls) -> None:
        """Drop the singleton so tests start with a fresh registry.

        Internal; not part of the public API. Tests that exercise
        registration / priority ordering call this in setup/teardown so
        a stale handler from a prior test can't bleed into assertion
        state. Production callers must not use this.
        """
        cls._instance = None

    def register_state(
        self,
        name: str,
        predicate: Callable[[Any], bool],
        icon_path: str,
        priority: float,
        on_click: Optional[Callable[[PropertyAdapter, str], None]] = None,
        tooltip: Optional[str] = None,
    ) -> _HandlerSubscription:
        """Register a handler. Raises ``ValueError`` on duplicate ``name``.

        The handler list is re-sorted by ``priority`` after every
        registration so :meth:`get_active_state` can walk in sorted
        order without re-sorting per call. Returns a subscription whose
        :meth:`cancel` removes the handler — matches the
        ``WidgetBuilderTable.register`` / ``AttributeModelBase.subscribe_value_changed``
        RAII pattern used across the property subsystem.
        """
        if any(h.name == name for h in self._handlers):
            raise ValueError(
                f"ControlStateManager: state {name!r} already registered"
            )
        self._handlers.append(
            ControlStateHandler(
                name=name,
                predicate=predicate,
                icon_path=icon_path,
                priority=priority,
                on_click=on_click,
                tooltip=tooltip,
            )
        )
        self._handlers.sort(key=lambda h: h.priority)
        return _HandlerSubscription(self, name)

    def _remove_state(self, name: str) -> None:
        self._handlers = [h for h in self._handlers if h.name != name]

    def get_active_state(self, model: Any) -> Optional[ControlStateHandler]:
        """Return the highest-priority handler whose predicate matches.

        Walks the (already priority-sorted) handler list and returns the
        first entry whose ``predicate(model)`` returns truthy. Returns
        ``None`` when no predicate matches.

        Predicate exceptions are swallowed per-handler: a buggy
        third-party predicate must not break neighbouring state
        resolution for the row. The error is silent by design — the
        indicator's job is to render what it can, not to crash the
        panel build.
        """
        for handler in self._handlers:
            try:
                if handler.predicate(model):
                    return handler
            except Exception:
                continue
        return None

    def list_states(self) -> List[ControlStateHandler]:
        """Return a priority-sorted copy of the registered handlers.

        Used by tests and the indicator's refresh path. Returning a
        copy stops callers from mutating the internal list.
        """
        return list(self._handlers)


# ---------------------------------------------------------------------------
# Built-in predicates
# ---------------------------------------------------------------------------


def _mixed_predicate(model: Any) -> bool:
    return bool(model.is_ambiguous)


def _locked_predicate(model: Any) -> bool:
    return bool(model.metadata.is_locked)


def _time_sampled_predicate(model: Any) -> bool:
    return bool(model.metadata.is_time_sampled)


def _not_default_predicate(model: Any) -> bool:
    """NotDefault fires when an attribute is authored *and* the adapter
    explicitly declares authored-value clearing support. The capability
    check folds the "icon hidden when ``on_click`` is None or not callable"
    rule into the predicate, so an unsupported adapter does not expose a
    click handler that would raise ``NotImplementedError``.
    """
    metadata = model.metadata
    if not metadata.is_authored:
        return False
    return adapter_supports_clear_values(model.adapter)


def _not_default_on_click(adapter: PropertyAdapter, attr_name: str) -> None:
    """Reset-to-default click handler for the NotDefault state.

    Wraps :meth:`PropertyAdapter.clear_value`. The indicator's click
    path additionally swallows ``NotImplementedError`` defensively —
    if a third-party handler registers against an adapter whose
    capability changes at runtime, clicking still can't crash the
    panel.
    """
    adapter.clear_value(attr_name)


# ---------------------------------------------------------------------------
# Built-in registrations
# ---------------------------------------------------------------------------


def _register_defaults(manager: "ControlStateManager") -> None:
    """Register the four built-in control states.

    Icon paths resolve through :mod:`ovui_widgets.common.style.urls` — the four
    per-state SVGs (``mixed.svg``, ``locked.svg``, ``timesample.svg``,
    ``not_default.svg``) live in ``ovui_widgets.app/style/icons/`` and are
    registered on ``omni.ui.url`` as ``control_state_*`` at style-module
    import time. Paths are resolved at registration time because the URL
    values are stable for the lifetime of the process.

    Icon semantics match the property inspector behavior / property control-state behavior:
    split circle for Mixed (warning amber), padlock for Locked (grey),
    keyframe diamond for TimeSampled (status-info blue), rounded square
    for NotDefault (authored blue).
    """
    manager.register_state(
        name="Mixed",
        predicate=_mixed_predicate,
        icon_path=get_icon_path("control_state_mixed"),
        priority=0.0,
        on_click=None,
        tooltip="Mixed values across selection",
    )
    manager.register_state(
        name="Locked",
        predicate=_locked_predicate,
        icon_path=get_icon_path("control_state_locked"),
        priority=20.0,
        on_click=None,
        tooltip="Locked",
    )
    manager.register_state(
        name="TimeSampled",
        predicate=_time_sampled_predicate,
        icon_path=get_icon_path("control_state_timesample"),
        priority=30.0,
        on_click=None,
        tooltip="Animated (time sampled)",
    )
    manager.register_state(
        name="NotDefault",
        predicate=_not_default_predicate,
        icon_path=get_icon_path("control_state_not_default"),
        priority=40.0,
        on_click=_not_default_on_click,
        tooltip="Value differs from default — click to reset",
    )


# ---------------------------------------------------------------------------
# Indicator widget
# ---------------------------------------------------------------------------

_SLOT_WIDTH = 20
_ICON_SIZE = 8
_CONTROL_STATE_STYLE_TYPE = "Property.ControlState"


def _style_state_name(handler_name: str) -> str:
    """Map a handler's ``name`` to the omni.ui style ``name`` selector.

    omni.ui's ``::foo`` state selectors match the widget's ``name``
    attribute; state names here are lowercased single-word tokens
    (``mixed`` / ``locked`` / ``timesampled`` / ``notdefault``) so the
    style entries in ``ovui_widgets.property/style.py`` stay terse. Third-party
    handlers follow the same convention — register with a ``CamelCase``
    name; the indicator lowercases.
    """
    return handler_name.lower()


class ControlStateIndicator:
    """Right-side state indicator glyph for a single attribute row.

    Builds a 20 px-wide ``ui.HStack`` slot holding one 8 × 8 widget
    styled as ``Property.ControlState`` with a per-state ``name``
    selector (``::mixed``, ``::locked``, …). At init and on every model
    value change the indicator queries :class:`ControlStateManager` for
    the row's active state and swaps the widget's ``name`` / tooltip /
    click handler accordingly.

    Rendering is dual-mode (Step 4.4):

    * **Kit** (``ui._IN_KIT`` True) — the widget is a ``ui.Image`` with
      ``source_url`` pointing at the state's SVG. The SVG file carries
      the glyph (padlock, diamond, dot, split circle); the style
      selector's colour tints the glyph when the SVG uses
      ``currentColor``.
    * **Standalone** (``ui._IN_KIT`` False) — the standalone omni.ui
      build's ``ui.Image`` does not render SVG from an absolute
      filesystem path. The widget falls back to a ``ui.Rectangle`` whose
      per-state fill comes from the ``Property.ControlState::*`` selectors in
      ``ovui_widgets.property/style.py``.

    When no handler matches the widget is made invisible while the
    HStack keeps its 20 px slot — row-to-row column alignment is
    preserved across rows with and without an active state.
    """

    def __init__(
        self,
        model: Any,
        adapter: PropertyAdapter,
        attr_name: str,
    ) -> None:
        self._model = model
        self._adapter = adapter
        self._attr_name = attr_name
        # The visual widget — ``ui.Image`` under Kit, ``ui.Rectangle``
        # standalone. Both expose the ``visible`` / ``name`` / ``tooltip``
        # attributes and ``set_mouse_pressed_fn`` method that the
        # refresh path drives, so the call sites don't branch on type.
        self._widget: Optional[ui.Widget] = None
        self._active_state: Optional[ControlStateHandler] = None
        # Subscribe before ``_build_ui`` so the reverse order (build →
        # subscribe) can't race with a model ``_on_backing_changed``
        # firing between the two calls and missing the refresh hook.
        self._value_sub = model.subscribe_value_changed(self._refresh)
        self._build_ui()

    @property
    def widget(self) -> Optional[ui.Widget]:
        """The underlying visual widget, or ``None`` before build.

        ``ui.Image`` under Kit (``_SVG_RENDERING_AVAILABLE`` True),
        ``ui.Rectangle`` standalone. Tests and callers that need to
        inspect the type at runtime do ``isinstance(indicator.widget,
        ui.Image)``.
        """
        return self._widget

    @property
    def rect(self) -> Optional[ui.Widget]:
        """Alias for :attr:`widget` retained for pre-4.4 call sites.

        Previous callers (Step 4.3) accessed the rectangle via ``.rect``;
        the Kit/standalone split under Step 4.4 widens the type, so
        ``widget`` is the canonical accessor.
        """
        return self._widget

    @property
    def active_state(self) -> Optional[ControlStateHandler]:
        """The currently-matched :class:`ControlStateHandler`, or ``None``."""
        return self._active_state

    def _resolve_state(self) -> Optional[ControlStateHandler]:
        manager = ControlStateManager.get_instance()
        return manager.get_active_state(self._model)

    def _build_widget_for_state(
        self, state: Optional[ControlStateHandler]
    ) -> ui.Widget:
        """Construct the per-state Image (Kit) or Rectangle (standalone).

        ``state`` is ``None`` when no handler matches the row; in that
        case the widget is built invisible so the 20 px slot stays
        column-aligned but the glyph doesn't show. The kwargs applied
        here match what :meth:`_refresh` later rewrites, so a state
        transition doesn't need to rebuild the widget tree.
        """
        name = _style_state_name(state.name) if state is not None else ""
        tooltip = state.tooltip if (state and state.tooltip) else ""
        visible = state is not None
        if _SVG_RENDERING_AVAILABLE:
            source_url = state.icon_path if state is not None else ""
            return ui.Image(
                source_url=source_url,
                width=_ICON_SIZE,
                height=_ICON_SIZE,
                style_type_name_override=_CONTROL_STATE_STYLE_TYPE,
                name=name,
                tooltip=tooltip,
                visible=visible,
            )
        return ui.Rectangle(
            width=_ICON_SIZE,
            height=_ICON_SIZE,
            style_type_name_override=_CONTROL_STATE_STYLE_TYPE,
            name=name,
            tooltip=tooltip,
            visible=visible,
        )

    def _build_ui(self) -> None:
        state = self._resolve_state()
        self._active_state = state
        # The row's HStack sits at 22 px while the icon is 16 px tall.
        # Without an inner VStack the 16 px widget anchors to the top
        # of the slot; wrapping it between two stretchy Spacers mirrors
        # the centring pattern used for the Stage filter-bar icon and
        # every widget in ``stage_delegate._build_column_header``.
        with ui.HStack(width=_SLOT_WIDTH):
            ui.Spacer(width=(_SLOT_WIDTH - _ICON_SIZE) // 2)
            with ui.VStack(width=_ICON_SIZE):
                ui.Spacer()
                self._widget = self._build_widget_for_state(state)
                ui.Spacer()
            if state is not None and callable(state.on_click):
                self._widget.set_mouse_pressed_fn(self._on_click)

    def _on_click(self, x: float, y: float, button: int, modifier: int) -> None:
        """Left-click only; swallow ``NotImplementedError`` defensively.

        The NotDefault predicate already folds the adapter-capability
        check in so ``on_click`` should only be reachable when the
        adapter declares ``clear_values`` support, but a runtime swap of
        the adapter (Phase 6 scheme delegates can do this) must not
        crash the panel — hence the catch.
        """
        if self._active_state is None or self._active_state.on_click is None:
            return
        if button != 0:
            return
        try:
            self._active_state.on_click(self._adapter, self._attr_name)
        except NotImplementedError:
            pass

    def _refresh(self) -> None:
        if self._widget is None:
            return
        state = self._resolve_state()
        self._active_state = state
        if state is None:
            self._widget.visible = False
            # Clear any stale click handler the previous state installed
            # so the now-hidden widget doesn't respond to hit-testing.
            self._widget.set_mouse_pressed_fn(lambda x, y, b, m: None)
            return
        self._widget.name = _style_state_name(state.name)
        self._widget.tooltip = state.tooltip or ""
        self._widget.visible = True
        if _SVG_RENDERING_AVAILABLE and isinstance(self._widget, ui.Image):
            # ``source_url`` is mutable post-construction — swap the SVG
            # in place rather than rebuilding the widget tree.
            self._widget.source_url = state.icon_path
        if callable(state.on_click):
            self._widget.set_mouse_pressed_fn(self._on_click)
        else:
            self._widget.set_mouse_pressed_fn(lambda x, y, b, m: None)
