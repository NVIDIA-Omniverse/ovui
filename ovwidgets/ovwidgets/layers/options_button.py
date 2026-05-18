# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Options-dropdown button for the Layers toolbar (LAYERS-PLAN Step 53).

Small gear-glyph button that sits on the left of the Save-All strip
(:meth:`LayerWindow._build_toolbar`). A click opens a :class:`ui.Menu`
of checkbox items, one per :class:`~ovwidgets.layers.layer_settings.LayerSettings`
toggle Kit exposes in its own Options button
(LAYERS-WINDOW-ARCHITECTURE §15).

The widget is intentionally thin: it owns the glyph + the menu handle
and forwards every checkbox write straight to the corresponding
:class:`LayerSettings` setter. The setter routes the value through the
backing :class:`ovwidgets.common.settings.Settings` store, which

1. persists it to the JSON config on next save, and
2. notifies every subscriber synchronously.

:class:`LayerModel` (Step 52) already subscribes to the tree-shape
keys, so flipping ``show_session_layer`` on the checkbox fires
``_item_changed(None)`` and the tree reshapes on the next paint
without any extra wiring here.

Glyph rationale
---------------
The standalone :mod:`omni.ui` build in this repo routes
``ui.Image(source_url)`` through the ``stb_image`` loader, which does
not recognise SVG; ``ovwidgets.app/resources/icons/settings.svg`` is therefore
not directly usable. Rather than ship a new PNG raster just for this
button, the glyph is drawn with the same shape-primitive vocabulary
the Step 19–23 delegate uses (:class:`ui.Rectangle` + :class:`ui.VStack`):
three stacked horizontal bars that read unambiguously as an "options /
sliders" icon at the 24 px toolbar size, and inherit the theme tint
through the shared ``Layers.OptionsGlyph`` style entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Tuple

import omni.ui as ui

from ovwidgets.common.menu import create_flat_menu

if TYPE_CHECKING:  # pragma: no cover — import guard
    from ovwidgets.layers.layer_model import DefaultLayerSettings
    from ovwidgets.layers.layer_settings import LayerSettings


# Ordered ``(property name, menu label)`` pairs — the six toggles the
# Layer-window dropdown exposes, matching LAYERS-PLAN Step 53's list
# verbatim. Order is fixed so the dropdown reads the same on every
# open (Kit's Options button presents the same entries in the same
# order). Properties outside this list still persist on
# :class:`LayerSettings` but are not surfaced in the v1 dropdown —
# ``enable_auto_authoring_mode`` / ``enable_spec_linking_mode`` are
# unwired today, and ``show_metricsassembler_layer`` /
# ``file_dialog_show_root_layer_location`` are advanced flags the
# plan defers to a later step.
MENU_ITEMS: Tuple[Tuple[str, str], ...] = (
    ("show_layer_contents", "Show Layer Contents"),
    ("show_session_layer", "Show Session Layer"),
    ("show_missing_reference", "Show Missing References"),
    ("show_merge_or_flatten_warning", "Show Merge/Flatten Warnings"),
    ("show_layer_file_extension", "Show File Extensions in Name"),
    ("show_info_notification", "Info Notifications"),
)


class OptionsButton:
    """Gear-glyph toolbar button + persistent-settings checkbox menu.

    Holds a live :class:`LayerSettings` reference (or the dataclass
    stand-in :class:`DefaultLayerSettings` for unit-test paths) and
    wires each :attr:`MENU_ITEMS` entry to its getter/setter pair.
    The checkbox ``checked`` state is read at menu-build time so the
    dropdown always paints the current value, including values that
    were flipped from somewhere else in the app (e.g. a settings
    dialog) since the last open.

    Instances are built once per :meth:`LayerWindow._build_ui` pass
    via :meth:`build` — a frame rebuild drops the previous widget
    handles along with the rest of the toolbar, so the button follows
    the toolbar's lifecycle. :meth:`destroy` cancels the pinned
    :class:`ui.Menu` handle so ovui can reclaim the popup when the
    window goes away.
    """

    def __init__(
        self,
        settings: "DefaultLayerSettings | LayerSettings",
    ) -> None:
        self._settings = settings
        # Cached :class:`ui.Menu` handle — destroyed + rebuilt on every
        # :meth:`show_at` so the checkbox state is always read from
        # the live settings. Pinning the last-built menu here lets the
        # next open tear down the previous popup, matching the
        # :class:`ContextMenuBuilder` convention (context_menu.py:608).
        self._menu: Any = None
        # Widget handles populated by :meth:`build`. Kept on ``self``
        # so tests can introspect ``_hit_rectangle`` / ``_container``
        # without driving a live paint loop.
        self._container: Any = None
        self._hit_rectangle: Any = None

    # ── Public surface ──────────────────────────────────────────────

    @property
    def settings(self) -> "DefaultLayerSettings | LayerSettings":
        """Return the bound :class:`LayerSettings` (or dataclass fallback)."""
        return self._settings

    @property
    def menu(self) -> Any:
        """Return the last-built :class:`ui.Menu`, or ``None`` pre-open."""
        return self._menu

    def build(self) -> None:
        """Paint the button inside the current container.

        Must be called inside a :class:`ui.HStack` / :class:`ui.VStack`
        context — the caller sits on :class:`LayerWindow._build_toolbar`
        and owns the strip geometry. Produces a 24 × 24 clickable
        :class:`ui.ZStack` with three stacked :class:`ui.Rectangle`
        bars as the glyph. A left-click on the hit rectangle opens
        the dropdown at the cursor; non-left clicks are ignored so
        the button cannot accidentally open on a right-click that was
        meant for the context-menu path.
        """
        self._container = ui.ZStack(
            width=ui.Pixel(24),
            height=ui.Pixel(24),
            tooltip="Layer options",
        )
        with self._container:
            # Hit rectangle carries the hover / pressed styling and
            # the mouse handler. Painted first so the glyph primitives
            # sit on top in z-order — the ZStack renders children in
            # paint order, last-on-top.
            self._hit_rectangle = ui.Rectangle(
                style_type_name_override="Layers.OptionsButton",
            )
            self._hit_rectangle.set_mouse_pressed_fn(self._on_mouse_pressed)
            # Glyph — three horizontal bars, centred in the 24 × 24
            # slot. The HStack/VStack sandwich pins the bars to the
            # geometric centre without letting ovui stretch them to
            # the hit rectangle's full footprint.
            with ui.HStack():
                ui.Spacer()
                with ui.VStack(width=ui.Pixel(12), spacing=ui.Pixel(2)):
                    ui.Spacer()
                    ui.Rectangle(
                        height=ui.Pixel(2),
                        style_type_name_override="Layers.OptionsGlyph",
                    )
                    ui.Rectangle(
                        height=ui.Pixel(2),
                        style_type_name_override="Layers.OptionsGlyph",
                    )
                    ui.Rectangle(
                        height=ui.Pixel(2),
                        style_type_name_override="Layers.OptionsGlyph",
                    )
                    ui.Spacer()
                ui.Spacer()

    def show_at(self, x: float, y: float) -> Any:
        """Build and show the checkbox dropdown at ``(x, y)``.

        Destroys the previously-pinned :class:`ui.Menu` first so the
        popup life-cycle stays one-at-a-time (a double-click that
        landed two ``show_at`` calls before the first popup closed
        would otherwise leak the first menu's subscription list).
        Returns the new :class:`ui.Menu` so callers — tests most
        notably — can poke at the dropdown directly.
        """
        if self._menu is not None:
            try:
                self._menu.destroy()
            except Exception:
                # Freed handles raise on some ovui builds; a broad
                # except keeps the hot path robust (same guard
                # :class:`ContextMenuBuilder.show_at` uses).
                pass
            self._menu = None
        menu = create_flat_menu(ui_module=ui)
        self._menu = menu
        with menu:
            for prop_name, label in MENU_ITEMS:
                current = bool(getattr(self._settings, prop_name))
                ui.MenuItem(
                    label,
                    checkable=True,
                    checked=current,
                    # Default-argument capture pins ``prop_name`` at
                    # build time — the classic closure-over-loop-var
                    # fix. Without it every rebuilt MenuItem would
                    # fire with the last loop iteration's property.
                    triggered_fn=lambda n=prop_name: self._toggle(n),
                )
        menu.show_at(float(x), float(y))
        return menu

    def toggle(self, prop_name: str) -> None:
        """Flip ``prop_name`` through the public setter.

        Exposed so tests and future keyboard shortcuts can drive a
        toggle without reaching into the menu-item triggered_fn.
        """
        self._toggle(prop_name)

    def menu_item_labels(self) -> List[str]:
        """Return the ordered label list the menu paints.

        Mirrors :data:`MENU_ITEMS` — kept as an instance method so
        tests have a stable introspection surface without importing
        the module-level constant.
        """
        return [label for _name, label in MENU_ITEMS]

    def destroy(self) -> None:
        """Drop the pinned menu handle so the owning window can tear down.

        Idempotent — a second destroy is a no-op so
        :meth:`LayerWindow.destroy` can re-enter the method without a
        guard at the call site.
        """
        if self._menu is not None:
            try:
                self._menu.destroy()
            except Exception:
                pass
            self._menu = None
        self._container = None
        self._hit_rectangle = None

    # ── Internal helpers ────────────────────────────────────────────

    def _on_mouse_pressed(
        self, x: float, y: float, button: int, _modifiers: int
    ) -> None:
        """Left-click handler wired onto the hit rectangle.

        Non-left buttons are ignored so a stray right-click on the
        button does not open the options dropdown instead of falling
        through to whatever right-click the user intended.
        """
        if button != 0:
            return
        self.show_at(x, y)

    def _toggle(self, prop_name: str) -> None:
        """Flip the ``prop_name`` setting and write it back.

        Reads the current value through the getter, inverts it, and
        writes through the setter. For :class:`LayerSettings` the
        setter persists the value and notifies every subscriber
        (the model's tree-rebuild hook catches the tree-shape keys);
        for :class:`DefaultLayerSettings` the dataclass attribute is
        set in place, matching the test-path expectation.
        """
        current = bool(getattr(self._settings, prop_name))
        setattr(self._settings, prop_name, not current)
