# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""FileBar — filename field + extension selector + Apply / Cancel row.

See the content browser behavior (``FileBar``) and the content browser implementation step 48. :class:`FileBar` is the bottom row of :class:`FilePickerDialog`
— a label, a :class:`ui.StringField` for the filename, an optional
themed selector for the file-extension filter, and an
Apply / Cancel button pair. The bar owns the filename input and the
extension selection; the enclosing dialog owns the directory and the
result-callback contract (``(filename, dirname)`` per §12.7).

Step 48 ships the widget shell and the apply-disabled-until-typed
affordance. Step 49 wires the selector's selected extension into the
browser model's glob filter. Step 50 wires the FileBar's Apply button
to the dialog's ``on_apply(filename, dirname)`` result contract. The
public surface (``filename`` r/w, ``selected_extension`` r, ``build`` /
``destroy``) stays stable across those later steps.

**Callback contract.** ``on_apply(filename)`` fires on Apply click
with the current field value; ``on_cancel()`` fires on Cancel click
without arguments (cancel means "dismiss" — the caller already knows
what's in the field if it needs it). The enclosing :class:`FilePickerDialog`
wraps these callbacks to build the architecture §12.7
``(filename, dirname)`` payloads.

**Apply-disabled gate.** The Apply button is disabled while the
filename field is empty. This is the filepicker-standard affordance
for "there's nothing to open / save yet" — it reads clearly and
prevents the user from firing an Apply that would no-op through the
caller's validation anyway. As soon as the user types a character
(or :meth:`set_filename` pushes a non-empty value in), the button
re-enables.

**Identifiers.** The two buttons carry ``identifier="filepicker_apply_button"``
and ``"filepicker_cancel_button"`` per architecture §15.1 so the
dialog's QA harness / test locators can find them without reaching
through ovui's widget tree.
"""

from __future__ import annotations

import asyncio
import importlib.resources
from typing import Any, Callable, List, Optional, Tuple

import omni.ui as ui

from ovui_widgets.common.icon_caches import provider

_ICON_DIR = str(importlib.resources.files("ovui_widgets.common").joinpath("icons"))
_CHEVRON_DOWN = f"{_ICON_DIR}/chevron_down.png"
_DROPDOWN_WINDOW_TITLE_PREFIX = "OvGear_FileBar_ExtensionDropdown_"

# Row height. 32 px matches the Step 47 inline filename row the
# :class:`FileBar` replaces, so the dialog's overall layout reads the
# same post-swap.
_ROW_HEIGHT = 32

# The field, combo, and buttons sit inside the 32 px row as a compact
# 24 px control band. This mirrors the Content search/path fields and
# keeps the footer from inheriting the taller default input geometry.
_CONTROL_HEIGHT = 24

# Inner gap between adjacent widgets in the HStack. 4 px is tight enough
# to group the label + field + combo + buttons as a single logical row
# without the widgets touching.
_INNER_GAP = 4

# Outer padding on the left / right edges of the row. 8 px matches the
# :class:`Content.ToolBar` + :class:`ConfirmDeleteDialog` +
# :class:`SimpleInputDialog` convention for dialog inner padding.
_OUTER_PADDING = 8

# Label width. 72 px fits "File name:" / "Folder name:" at the Content
# font without wrapping and leaves the remaining horizontal space to
# the field + combo + buttons. Kept in sync with the Step 47 inline-
# row label width so the post-Step-48 swap keeps the dialog's column
# alignment unchanged.
_LABEL_WIDTH = 72

# File-extension combo width. Architecture §15.1 specifies 300 px for
# Kit's real FileBar; the narrower 240 px here reads well at the
# dialog's 1000 px default width without crowding the filename field
# (which flexes). A future persistent-setting-driven width can land on
# this constant.
_COMBO_WIDTH = 240
_COMBO_CHEVRON_SLOT_WIDTH = 18
_COMBO_CHEVRON_SIZE = 9
_COMBO_CHEVRON_RIGHT_PADDING = 5
_COMBO_BORDER_INSET = 1
_DROPDOWN_ROW_HEIGHT = 22
_DROPDOWN_POPUP_OPEN_DELAY_FRAMES = 8
_DROPDOWN_POPUP_FLAGS = (
    ui.WINDOW_FLAGS_NO_TITLE_BAR
    | ui.WINDOW_FLAGS_NO_MOVE
    | ui.WINDOW_FLAGS_NO_RESIZE
    | ui.WINDOW_FLAGS_NO_SCROLLBAR
    | ui.WINDOW_FLAGS_NO_DOCKING
    | ui.WINDOW_FLAGS_POPUP
)

# Apply / Cancel button dimensions — both buttons use the same compact
# height as the field and combo so the row aligns as one control strip.
_BUTTON_WIDTH = 80
_BUTTON_HEIGHT = _CONTROL_HEIGHT

# Identifiers for the Apply / Cancel buttons. Architecture §15.1 fixes
# these strings so the dialog's QA harness / any integration test that
# wants to drive the picker through ovui's widget tree can locate the
# buttons without reaching through private attributes.
APPLY_BUTTON_IDENTIFIER = "filepicker_apply_button"
CANCEL_BUTTON_IDENTIFIER = "filepicker_cancel_button"

# Default extension when ``file_extension_types`` is empty / unset.
# :meth:`FileBar.selected_extension` returns this tuple so the property
# never surfaces ``None`` or raises — callers (Step 49's glob-filter
# wiring, Step 50's apply-handler) always receive a valid
# ``(pattern, description)`` pair.
_DEFAULT_EXTENSION: Tuple[str, str] = ("*.*", "All files")


def _ignore_mouse_events(widget: Any) -> Any:
    if widget is not None:
        widget.opaque_for_mouse_events = False
    return widget


class FileBar:
    """Bottom bar of the file picker — filename + extension combo + Apply / Cancel.

    Construction is cheap (no ovui side effects); :meth:`build` is the
    method that lays out the :class:`ui.HStack` inside the caller's
    active frame / stack context. :meth:`destroy` tears down every
    ovui reference and nulls the live-widget slots so a subsequent
    :meth:`build` can materialise a fresh surface on the same instance
    (or a caller-side teardown can drop the instance entirely).

    The ``on_apply(filename)`` callback fires synchronously from the
    Apply button's :attr:`ui.Button.clicked_fn` with the current field
    value. ``on_cancel()`` fires from the Cancel button's
    :attr:`clicked_fn` without arguments. The :class:`FilePickerDialog`
    wraps these callbacks to build the architecture §12.7
    ``(filename, dirname)`` payloads it hands to the caller's
    result-handler contract.
    """

    def __init__(
        self,
        apply_label: str = "Open",
        cancel_label: str = "Cancel",
        file_extension_types: Optional[List[Tuple[str, str]]] = None,
        initial_filename: str = "",
        on_apply: Optional[Callable[[str], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        on_extension_changed: Optional[
            Callable[[Tuple[str, str]], None]
        ] = None,
        label_text: str = "File name:",
    ) -> None:
        self._apply_label: str = apply_label
        self._cancel_label: str = cancel_label
        # ``list(...)`` defensive-copies the caller's list so a later
        # mutation on the caller side does not drift the bar's view of
        # the extensions. ``or []`` normalises ``None`` into an empty
        # list; the combo is only rendered when the list is non-empty.
        self._file_extension_types: List[Tuple[str, str]] = list(
            file_extension_types or [],
        )
        # Cached filename — held here so :attr:`filename` works before
        # :meth:`build` (no field yet) and after :meth:`destroy` (field
        # is gone). During the live-window phase the field is the
        # authoritative source; the cache is refreshed on destroy.
        self._cached_filename: str = initial_filename or ""
        self._on_apply: Optional[Callable[[str], None]] = on_apply
        self._on_cancel: Optional[Callable[[], None]] = on_cancel
        # Step 49 — fires with the new ``(pattern, description)`` tuple
        # whenever the extension combo's selection changes. The
        # enclosing :class:`FilePickerDialog` parses the ``pattern``
        # string ("``*.usd, *.usda``") into a list of globs and forwards
        # it to :meth:`FileBrowserModel.set_glob_filter`.
        self._on_extension_changed: Optional[
            Callable[[Tuple[str, str]], None]
        ] = on_extension_changed
        self._label_text: str = label_text

        # Live ovui references — populated by :meth:`build`, nulled by
        # :meth:`destroy`. Every accessor short-circuits when they are
        # ``None`` so a pre-build / post-destroy read is safe.
        self._field: Optional[ui.StringField] = None
        self._combo: Optional[ui.Button] = None
        self._extension_popup: Optional[ui.Window] = None
        self._extension_menu_task: Optional[asyncio.Task[Any]] = None
        self._apply_button: Optional[ui.Button] = None
        self._cancel_button: Optional[ui.Button] = None

        # Subscription handles on the filename field's model — kept so
        # :meth:`destroy` can tear them down. ovui's ``add_value_changed_fn``
        # returns a subscription object; dropping it without cleanup
        # has been observed to leave dangling callbacks in the
        # :class:`FileBrowserWidget` tests.
        self._field_value_sub: Optional[Any] = None

        # Cached selected extension index — kept so :attr:`selected_extension`
        # works before :meth:`build` (no combo yet). Defaults to 0 so the
        # first entry in ``file_extension_types`` is "selected" by
        # default; same convention Kit's FileBar uses.
        self._selected_extension_index: int = 0

    # ── Build ───────────────────────────────────────────────────────────

    def build(self) -> None:
        """Lay out the HStack inside the caller's active frame context.

        Layout (left-to-right):

        * Outer padding (8 px).
        * Label — "File name:" by default.
        * Gap (4 px).
        * Filename :class:`ui.StringField` (flexible).
        * Gap (4 px).
        * Extension selector (240 px, only when
          ``file_extension_types`` is non-empty).
        * Gap (4 px).
        * Apply :class:`ui.Button` (``identifier="filepicker_apply_button"``).
        * Gap (4 px).
        * Cancel :class:`ui.Button` (``identifier="filepicker_cancel_button"``).
        * Outer padding (8 px).

        The Apply button starts disabled when ``initial_filename`` is
        empty; a ``value_changed_fn`` on the field's model refreshes
        the enabled flag on every keystroke so the affordance tracks
        the user's input in real time.
        """
        with ui.ZStack(height=ui.Pixel(_ROW_HEIGHT)):
            ui.Rectangle(style_type_name_override="Content.FileBar")
            with ui.HStack(
                height=ui.Pixel(_ROW_HEIGHT),
                spacing=_INNER_GAP,
            ):
                ui.Spacer(width=ui.Pixel(_OUTER_PADDING))

                with ui.VStack(
                    width=ui.Pixel(_LABEL_WIDTH),
                    height=ui.Pixel(_ROW_HEIGHT),
                ):
                    ui.Spacer()
                    ui.Label(
                        self._label_text,
                        height=ui.Pixel(_CONTROL_HEIGHT),
                        alignment=ui.Alignment.LEFT_CENTER,
                        style_type_name_override="Content.FileBar.Label",
                    )
                    ui.Spacer()

                with ui.VStack(height=ui.Pixel(_ROW_HEIGHT)):
                    ui.Spacer()
                    self._field = ui.StringField(
                        height=ui.Pixel(_CONTROL_HEIGHT),
                        style_type_name_override="Content.FileBar.Field",
                    )
                    ui.Spacer()
                self._field.model.set_value(self._cached_filename)
                # Keep the Apply button in lock-step with the field's
                # content — empty field → disabled; non-empty → enabled.
                # The closure captures ``self`` rather than the individual
                # refs so a destroy() that nulls ``_apply_button`` makes
                # the handler a no-op rather than a NullPointerException.
                try:
                    self._field_value_sub = (
                        self._field.model.add_value_changed_fn(
                            self._on_field_value_changed,
                        )
                    )
                except Exception:  # noqa: BLE001
                    # Defensive: older ovui builds may not expose
                    # ``add_value_changed_fn`` on :class:`SimpleStringModel`.
                    # The Apply button is still clickable; it just does not
                    # gate on emptiness in that case.
                    self._field_value_sub = None

                if self._file_extension_types:
                    # Build a flat list of display strings for the
                    # selector — Kit's FileBar renders a two-column row
                    # ``(glob, description)`` but a flat string keeps the
                    # Step 48 surface compact and compatible with the
                    # FileBar's public selected-extension contract.
                    entries = [
                        f"{desc} ({glob})"
                        for (glob, desc) in self._file_extension_types
                    ]
                    with ui.VStack(
                        width=ui.Pixel(_COMBO_WIDTH),
                        height=ui.Pixel(_ROW_HEIGHT),
                    ):
                        ui.Spacer()
                        with ui.ZStack(
                            width=ui.Pixel(_COMBO_WIDTH),
                            height=ui.Pixel(_CONTROL_HEIGHT),
                        ):
                            ui.Rectangle(
                                style_type_name_override=(
                                    "Content.FileBar.ComboBoxBorder"
                                ),
                            )
                            with ui.HStack(height=ui.Pixel(_CONTROL_HEIGHT)):
                                ui.Spacer(width=ui.Pixel(_COMBO_BORDER_INSET))
                                with ui.VStack(
                                    width=ui.Pixel(
                                        _COMBO_WIDTH
                                        - 2 * _COMBO_BORDER_INSET
                                    ),
                                ):
                                    ui.Spacer(
                                        height=ui.Pixel(_COMBO_BORDER_INSET),
                                    )
                                    self._combo = ui.Button(
                                        entries[
                                            self._current_extension_index()
                                        ],
                                        width=ui.Pixel(
                                            _COMBO_WIDTH
                                            - 2 * _COMBO_BORDER_INSET
                                        ),
                                        height=ui.Pixel(
                                            _CONTROL_HEIGHT
                                            - 2 * _COMBO_BORDER_INSET
                                        ),
                                        alignment=ui.Alignment.LEFT_CENTER,
                                        style_type_name_override=(
                                            "Content.FileBar.ComboBox"
                                        ),
                                    )
                                    self._combo.set_mouse_pressed_fn(
                                        self._on_combo_mouse_pressed,
                                    )
                                    ui.Spacer(
                                        height=ui.Pixel(_COMBO_BORDER_INSET),
                                    )
                                ui.Spacer(width=ui.Pixel(_COMBO_BORDER_INSET))
                            self._build_combo_chevron_overlay()
                        ui.Spacer()

                with ui.VStack(
                    width=ui.Pixel(_BUTTON_WIDTH),
                    height=ui.Pixel(_ROW_HEIGHT),
                ):
                    ui.Spacer()
                    self._apply_button = ui.Button(
                        self._apply_label,
                        width=ui.Pixel(_BUTTON_WIDTH),
                        height=ui.Pixel(_BUTTON_HEIGHT),
                        name="ok",
                        identifier=APPLY_BUTTON_IDENTIFIER,
                        clicked_fn=self._on_apply_clicked,
                    )
                    ui.Spacer()
                self._apply_button.enabled = bool(self._cached_filename)

                with ui.VStack(
                    width=ui.Pixel(_BUTTON_WIDTH),
                    height=ui.Pixel(_ROW_HEIGHT),
                ):
                    ui.Spacer()
                    self._cancel_button = ui.Button(
                        self._cancel_label,
                        width=ui.Pixel(_BUTTON_WIDTH),
                        height=ui.Pixel(_BUTTON_HEIGHT),
                        name="cancel",
                        identifier=CANCEL_BUTTON_IDENTIFIER,
                        clicked_fn=self._on_cancel_clicked,
                    )
                    ui.Spacer()

                ui.Spacer(width=ui.Pixel(_OUTER_PADDING))

    def _build_combo_chevron_overlay(self) -> None:
        """Draw the shared chevron glyph over the selector control."""
        overlay_row = _ignore_mouse_events(
            ui.HStack(height=ui.Pixel(_CONTROL_HEIGHT)),
        )
        with overlay_row:
            ui.Spacer()
            chevron_stack = _ignore_mouse_events(
                ui.ZStack(
                    width=ui.Pixel(_COMBO_CHEVRON_SLOT_WIDTH),
                    height=ui.Pixel(_CONTROL_HEIGHT),
                ),
            )
            with chevron_stack:
                chevron_column = _ignore_mouse_events(ui.VStack())
                with chevron_column:
                    ui.Spacer()
                    chevron_row = _ignore_mouse_events(
                        ui.HStack(height=ui.Pixel(_COMBO_CHEVRON_SIZE)),
                    )
                    with chevron_row:
                        ui.Spacer()
                        _ignore_mouse_events(
                            ui.ImageWithProvider(
                                provider(_CHEVRON_DOWN),
                                width=ui.Pixel(_COMBO_CHEVRON_SIZE),
                                height=ui.Pixel(_COMBO_CHEVRON_SIZE),
                                style_type_name_override=(
                                    "Content.FileBar.ComboBoxChevron"
                                ),
                            ),
                        )
                        ui.Spacer(
                            width=ui.Pixel(_COMBO_CHEVRON_RIGHT_PADDING),
                        )
                    ui.Spacer()

    def _on_combo_mouse_pressed(
        self, _x: float, _y: float, button: int, _modifier: int,
    ) -> None:
        """Schedule opening the file-extension popup under the control."""
        if button != 0:
            return
        if self._combo is None:
            return
        x = float(self._combo.screen_position_x)
        y = float(
            self._combo.screen_position_y
            + self._combo.computed_height
        )
        self._extension_menu_task = asyncio.ensure_future(
            self._show_extension_menu_after_click(x, y),
        )

    async def _show_extension_menu_after_click(
        self, x: float, y: float,
    ) -> None:
        """Open the extension menu after the click release has completed."""
        for _ in range(_DROPDOWN_POPUP_OPEN_DELAY_FRAMES):
            await ui.next_frame()
        if self._combo is None:
            return
        self._show_extension_menu(x, y)

    def _show_extension_menu(self, x: float, y: float) -> Optional[ui.Window]:
        """Open the file-extension popup using OVUI menu selection shades."""
        if not self._file_extension_types:
            return None
        self._destroy_extension_popup()

        popup = ui.Window(
            f"{_DROPDOWN_WINDOW_TITLE_PREFIX}{id(self)}",
            width=_COMBO_WIDTH,
            height=len(self._file_extension_types) * _DROPDOWN_ROW_HEIGHT,
            flags=_DROPDOWN_POPUP_FLAGS,
        )
        popup.setPosition(float(x), float(y))
        popup.focus()
        popup.set_visibility_changed_fn(
            self._on_extension_popup_visibility_changed,
        )
        with popup.frame:
            with ui.ZStack():
                ui.Rectangle(
                    style_type_name_override="Content.FileBar.DropdownPopup",
                )
                with ui.VStack(spacing=0):
                    current_idx = self._current_extension_index()
                    for idx, (glob, desc) in enumerate(
                        self._file_extension_types,
                    ):
                        style = (
                            "Content.FileBar.DropdownItemBackgroundSelected"
                            if idx == current_idx
                            else "Content.FileBar.DropdownItemBackground"
                        )
                        with ui.ZStack(height=ui.Pixel(_DROPDOWN_ROW_HEIGHT)):
                            background = ui.Rectangle(
                                height=ui.Pixel(_DROPDOWN_ROW_HEIGHT),
                                style_type_name_override=style,
                            )
                            background.set_mouse_pressed_fn(
                                lambda _x, _y, button, _modifier,
                                selected_idx=idx: (
                                    self._on_extension_popup_item_clicked(
                                        selected_idx,
                                    )
                                    if button == 0
                                    else None
                                )
                            )
                            label = ui.Label(
                                f"{desc} ({glob})",
                                height=ui.Pixel(_DROPDOWN_ROW_HEIGHT),
                                alignment=ui.Alignment.LEFT_CENTER,
                                style_type_name_override=(
                                    "Content.FileBar.DropdownItemLabel"
                                ),
                            )
                            label.opaque_for_mouse_events = False
        self._extension_popup = popup
        return popup

    def _on_extension_popup_visibility_changed(self, visible: bool) -> None:
        """Clean up when ovui dismisses the popup on click-outside."""
        if visible:
            return
        popup = self._extension_popup
        self._extension_popup = None
        if popup is None:
            return
        try:
            popup.set_visibility_changed_fn(None)
        except Exception:  # noqa: BLE001
            pass
        try:
            popup.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _destroy_extension_popup(self) -> None:
        """Destroy the transient extension popup if it is currently live."""
        popup = self._extension_popup
        self._extension_popup = None
        if popup is None:
            return
        try:
            popup.set_visibility_changed_fn(None)
        except Exception:  # noqa: BLE001
            pass
        try:
            popup.visible = False
        except Exception:  # noqa: BLE001
            pass
        try:
            popup.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _on_extension_popup_item_clicked(self, idx: int) -> None:
        """Apply a popup selection and close the transient popup."""
        self._select_extension_index(idx)
        self._destroy_extension_popup()

    def destroy(self) -> None:
        """Tear down every ovui reference and drop callbacks.

        Idempotent — safe to call on a bar that was never :meth:`build`'d
        or has already been destroyed. Snapshots the current field value
        into :attr:`_cached_filename` before nulling the field so a
        post-destroy :attr:`filename` read keeps returning the last
        typed value. The ``on_apply`` / ``on_cancel`` callbacks are
        cleared so the instance can fall out of scope without leaking
        callback chains into the caller.
        """
        # Snapshot the field value before the reference goes away.
        if self._field is not None:
            try:
                self._cached_filename = (
                    self._field.model.get_value_as_string()
                )
            except Exception:  # noqa: BLE001
                # ovui may raise if the field was torn down under us —
                # fall back to the cache.
                pass
        # Snapshot the combo index so :attr:`selected_extension` keeps
        # returning the user-selected option post-destroy.
        if self._combo is not None:
            try:
                self._selected_extension_index = self._current_extension_index()
            except Exception:  # noqa: BLE001
                pass
        self._destroy_extension_popup()
        if self._extension_menu_task is not None:
            self._extension_menu_task.cancel()
            self._extension_menu_task = None

        self._field = None
        self._combo = None
        self._extension_popup = None
        self._extension_menu_task = None
        self._apply_button = None
        self._cancel_button = None
        self._field_value_sub = None
        self._on_apply = None
        self._on_cancel = None
        self._on_extension_changed = None

    # ── Public accessors ─────────────────────────────────────────────────

    @property
    def filename(self) -> str:
        """Current filename — live field value when built, cache otherwise."""
        if self._field is not None:
            try:
                return self._field.model.get_value_as_string()
            except Exception:  # noqa: BLE001
                return self._cached_filename
        return self._cached_filename

    @filename.setter
    def filename(self, name: str) -> None:
        """Write ``name`` into the field (if live) and the cache.

        ``None`` normalises to the empty string so a programmatic
        ``bar.filename = None`` does not crash ovui's ``set_value``
        contract (which only accepts strings).
        """
        self._cached_filename = name or ""
        if self._field is not None:
            try:
                self._field.model.set_value(self._cached_filename)
            except Exception:  # noqa: BLE001
                # ovui may raise if the field was torn down between the
                # caller's check and this call — fall back silently.
                pass
        # Refresh the Apply button's enabled state immediately — the
        # field's ``value_changed_fn`` also fires from ``set_value``,
        # but a redundant refresh here keeps the contract tight when
        # the subscription was dropped or never bound.
        self._refresh_apply_enabled()

    @property
    def selected_extension(self) -> Tuple[str, str]:
        """Return the currently-selected ``(pattern, description)`` tuple.

        When ``file_extension_types`` is empty / unset, returns the
        default ``("*.*", "All files")`` so the property never surfaces
        ``None`` or raises — callers (Step 49's glob-filter wiring,
        Step 50's apply-handler) can always destructure the return.

        The index is read from the live combo when built and falls back
        to the cached index (updated on :meth:`destroy`) otherwise. The
        index is clamped to ``[0, len(extensions) - 1]`` so an out-of-
        range value from a drifted setting does not crash the bar.
        """
        if not self._file_extension_types:
            return _DEFAULT_EXTENSION
        idx = self._current_extension_index()
        return self._file_extension_types[idx]

    def _current_extension_index(self) -> int:
        """Return the clamped selected extension index."""
        if not self._file_extension_types:
            return 0
        idx = self._selected_extension_index
        return max(0, min(idx, len(self._file_extension_types) - 1))

    def _select_extension_index(self, idx: int) -> None:
        """Select extension ``idx`` and fire the extension-changed callback."""
        if not self._file_extension_types:
            return
        idx = max(0, min(idx, len(self._file_extension_types) - 1))
        self._selected_extension_index = idx
        if self._combo is not None:
            try:
                glob, desc = self._file_extension_types[idx]
                self._combo.text = f"{desc} ({glob})"
            except Exception:  # noqa: BLE001
                pass
        if self._on_extension_changed is not None:
            self._on_extension_changed(self.selected_extension)

    # ── Handlers ─────────────────────────────────────────────────────────

    def _on_field_value_changed(self, model: Any) -> None:  # noqa: ANN401
        """Refresh the Apply button's enabled flag on every keystroke.

        ovui's ``add_value_changed_fn`` fires synchronously on every
        model mutation — user typing, ``set_value`` from :attr:`filename`
        setter, and paste events all route through here. The handler
        reads the current value and toggles the button's enabled flag;
        it does not cache the value (the model is authoritative).
        """
        self._refresh_apply_enabled()

    def _refresh_apply_enabled(self) -> None:
        """Toggle the Apply button's enabled flag against field emptiness."""
        if self._apply_button is None:
            return
        value = ""
        if self._field is not None:
            try:
                value = self._field.model.get_value_as_string()
            except Exception:  # noqa: BLE001
                value = self._cached_filename
        try:
            self._apply_button.enabled = bool(value)
        except Exception:  # noqa: BLE001
            # Defensive against ovui tear-down races — if the button
            # was nulled on another thread between the check and the
            # assignment, silent no-op.
            pass

    def _on_apply_clicked(self) -> None:
        """Fire ``on_apply(filename)`` with the current field value."""
        if self._on_apply is None:
            return
        # Read directly from the field so the callback sees the live
        # value, not a potentially-stale cache. Falls back to the cache
        # when the field is gone (e.g. a destroy that races with a
        # double-click).
        filename = self.filename
        self._on_apply(filename)

    def _on_cancel_clicked(self) -> None:
        """Fire ``on_cancel()`` — no arguments.

        Cancel is a "dismiss" notification; the caller (the enclosing
        :class:`FilePickerDialog`) knows where to read the filename and
        directory from when it needs them for the architecture §12.7
        ``(filename, dirname)`` callback payload.
        """
        if self._on_cancel is None:
            return
        self._on_cancel()

    # ── Test hooks ───────────────────────────────────────────────────────

    @property
    def is_built(self) -> bool:
        """``True`` once :meth:`build` has materialised the ovui widgets."""
        return self._field is not None

    @property
    def apply_enabled(self) -> bool:
        """Current enabled flag on the Apply button.

        Returns ``False`` when the bar is not built yet; tests use this
        to assert the apply-disabled-until-typed behaviour without
        reaching into the private button reference.
        """
        if self._apply_button is None:
            return False
        try:
            return bool(self._apply_button.enabled)
        except Exception:  # noqa: BLE001
            return False

    def _fire_apply_for_test(self) -> None:
        """Drive :meth:`_on_apply_clicked` directly — test-only hook."""
        if self._apply_button is None:
            return
        self._on_apply_clicked()

    def _fire_cancel_for_test(self) -> None:
        """Drive :meth:`_on_cancel_clicked` directly — test-only hook."""
        if self._cancel_button is None:
            return
        self._on_cancel_clicked()

    def _set_combo_index_for_test(self, idx: int) -> None:
        """Force the selector to ``idx`` and fire callback — test hook.

        Drives the selected-extension state directly so tests can
        exercise dialog-level glob-filter wiring without simulating a
        real popup item pick through ovui.
        """
        if not self._file_extension_types:
            return
        self._select_extension_index(idx)
