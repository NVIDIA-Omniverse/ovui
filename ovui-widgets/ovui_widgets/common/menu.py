# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Shared menu construction helpers for OvGear UI surfaces."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_FLAT_MENU_DELEGATE: Any | None = None
_BASE_MENU_DELEGATE: Any | None = None
_MENU_CONTROL_CALLBACKS: dict[str, Callable[..., Any]] = {}
CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER = "__ovui_custom_resolution_editor__"
RENDER_SCALE_COMBO_HOTKEY_MARKER = "__ovui_render_scale_combo__"
FILL_VIEWPORT_CHECKBOX_HOTKEY_MARKER = "__ovui_fill_viewport_checkbox__"
SAVED_CUSTOM_DELETE_HOTKEY_MARKER = "__ovui_saved_custom_delete__"
_MENU_ITEM_HOTKEY_WIDTH = 180.0
_MENU_ITEM_DELETE_WIDTH = 24.0
_MENU_ITEM_DELETE_GAP = 6.0
_CUSTOM_RESOLUTION_WIDTH = 60.0
_CUSTOM_RESOLUTION_LINK_WIDTH = 28.0
_CUSTOM_RESOLUTION_RATIO_WIDTH = 76.0
_CUSTOM_RESOLUTION_SAVE_WIDTH = 24.0
_CUSTOM_RESOLUTION_GAP = 8.0
_CUSTOM_RESOLUTION_LABEL_HEIGHT = 16.0
_CUSTOM_RESOLUTION_CONTROL_HEIGHT = 24.0
_CUSTOM_RESOLUTION_ERROR_HEIGHT = 16.0
_CUSTOM_RESOLUTION_ROW_HEIGHT = 78.0
_CUSTOM_RESOLUTION_DEFAULT_RATIOS = ("16:9", "4:3", "1:1", "21:9", "32:9")
_KEY_ESCAPE = 256
_MENU_CONTROL_ROW_HEIGHT = 28.0
_MENU_CONTROL_GAP = 8.0
_RENDER_SCALE_ROW_HEIGHT = 32.0
_RENDER_SCALE_COMBO_HEIGHT = 22.0
_RENDER_SCALE_COMBO_TOP_INSET = 4.0
_RENDER_SCALE_COMBO_BOTTOM_INSET = (
    _RENDER_SCALE_ROW_HEIGHT
    - _RENDER_SCALE_COMBO_HEIGHT
    - _RENDER_SCALE_COMBO_TOP_INSET
)
_RENDER_SCALE_COMBO_WIDTH = 104.0
_FILL_VIEWPORT_ROW_HEIGHT = 32.0
_FILL_VIEWPORT_CHECKBOX_SLOT_WIDTH = 24.0
_FILL_VIEWPORT_CHECKBOX_SIZE = 18.0
_FILL_VIEWPORT_CHECKBOX_TOP_INSET = (
    _FILL_VIEWPORT_ROW_HEIGHT - _FILL_VIEWPORT_CHECKBOX_SIZE
) / 2.0
_FILL_VIEWPORT_DEFAULT_DISABLED_TOOLTIP = "Disabled while Render Resolution is Viewport"


def _identifier_suffix(value: Any) -> str:
    """Return a stable, inspector-safe suffix for visible menu text."""

    suffix = "".join(
        character.lower() if character.isalnum() else "_"
        for character in str(value or "")
    ).strip("_")
    while "__" in suffix:
        suffix = suffix.replace("__", "_")
    return suffix or "item"


def _item_identifier(item: Any, attribute: str, default_prefix: str) -> str:
    explicit = str(getattr(item, attribute, "") or "").strip()
    if explicit:
        return explicit
    return f"{default_prefix}_{_identifier_suffix(getattr(item, 'text', ''))}"


def register_menu_control_callback(callback: Callable[..., Any] | None) -> str:
    """Register a menu control callback and return a marker-payload token."""

    if not callable(callback):
        return ""
    token = str(id(callback))
    _MENU_CONTROL_CALLBACKS[token] = callback
    return token


def unregister_menu_control_callback(token: str) -> None:
    """Forget a previously registered menu control callback token."""

    if token:
        _MENU_CONTROL_CALLBACKS.pop(token, None)


def _lookup_menu_control_callback(token: str) -> Callable[..., Any] | None:
    if not token:
        return None
    return _MENU_CONTROL_CALLBACKS.get(token)


def _build_no_title(_: Any) -> None:
    """Suppress omni.ui's detachable-menu title/status strip."""


def _get_base_menu_delegate() -> Any:
    """Return omni.ui's stock menu delegate for non-overridden rows."""
    global _BASE_MENU_DELEGATE
    if _BASE_MENU_DELEGATE is None:
        import omni.ui as ui

        _BASE_MENU_DELEGATE = ui.MenuDelegate()
    return _BASE_MENU_DELEGATE


def _set_numeric_field_value(field: Any, value: int) -> None:
    """Best-effort field initialization for presentation-only menu controls."""

    try:
        field.model.set_value(int(value))
    except (AttributeError, TypeError, ValueError):
        return


def _numeric_field_value_as_text(field: Any) -> str | None:
    model = getattr(field, "model", None)
    if model is None:
        return None
    get_value_as_string = getattr(model, "get_value_as_string", None)
    if callable(get_value_as_string):
        try:
            return str(get_value_as_string())
        except (AttributeError, TypeError, ValueError):
            pass
    get_value_as_int = getattr(model, "get_value_as_int", None)
    if callable(get_value_as_int):
        try:
            return str(get_value_as_int())
        except (AttributeError, TypeError, ValueError):
            return None
    return None


def _parse_positive_dimension_field_value(field: Any) -> int | None:
    text = _numeric_field_value_as_text(field)
    if text is not None:
        stripped = text.strip()
        if not stripped:
            return None
        try:
            value = int(stripped)
        except (TypeError, ValueError):
            return None
    else:
        model = getattr(field, "model", None)
        if model is None:
            return None
        try:
            value = int(model.get_value_as_int())
        except (AttributeError, TypeError, ValueError):
            return None
    return value if value > 0 else None


def _read_positive_numeric_field_value(field: Any) -> int | None:
    return _parse_positive_dimension_field_value(field)


def _normalize_custom_resolution_bounds(
    bounds: Any,
) -> tuple[int, int, int, int] | None:
    try:
        min_width, min_height, max_width, max_height = bounds
    except (TypeError, ValueError):
        return None
    try:
        normalized = (
            int(min_width),
            int(min_height),
            int(max_width),
            int(max_height),
        )
    except (TypeError, ValueError):
        return None
    if normalized[0] <= 0 or normalized[1] <= 0:
        return None
    if normalized[2] < normalized[0] or normalized[3] < normalized[1]:
        return None
    return normalized


def _ratio_value_from_label(label: Any) -> float | None:
    try:
        numerator_text, denominator_text = str(label).split(":", 1)
        numerator = float(numerator_text)
        denominator = float(denominator_text)
    except (TypeError, ValueError):
        return None
    if numerator <= 0.0 or denominator <= 0.0:
        return None
    return numerator / denominator


def _ratio_label_for_dimensions(width: Any, height: Any) -> str | None:
    """Return the Area-2 ratio label for editor field dimensions."""

    from ovui_widgets.viewport.resolution_catalog import resolution_badge_metadata

    try:
        normalized_width = int(width)
        normalized_height = int(height)
    except (TypeError, ValueError):
        return None
    return resolution_badge_metadata(
        normalized_width,
        normalized_height,
    ).ratio_badge_label


def _root_combo_value_model(model: Any) -> Any:
    try:
        return model.get_item_value_model(None, 0)
    except TypeError:
        pass
    try:
        return model.get_item_value_model(None)
    except TypeError:
        return model.get_item_value_model()


def _combo_item_value_model(model: Any, item: Any) -> Any:
    try:
        return model.get_item_value_model(item, 0)
    except TypeError:
        return model.get_item_value_model(item)


def _combo_item_text(model: Any, item: Any) -> str:
    value_model = _combo_item_value_model(model, item)
    try:
        return str(value_model.get_value_as_string())
    except (AttributeError, TypeError, ValueError):
        return str(value_model)


def _set_combo_selected_index(model: Any, index: int) -> None:
    try:
        _root_combo_value_model(model).set_value(int(index))
    except (AttributeError, TypeError, ValueError):
        return


def _append_combo_string_item(model: Any, label: str) -> Any:
    append_child_item = getattr(model, "append_child_item", None)
    if not callable(append_child_item):
        return None
    try:
        import omni.ui as ui

        return append_child_item(None, ui.SimpleStringModel(str(label)))
    except TypeError:
        return append_child_item(None, str(label))


def _remove_combo_item(model: Any, item: Any) -> None:
    remove_item = getattr(model, "remove_item", None)
    if not callable(remove_item):
        return
    try:
        remove_item(item)
    except (AttributeError, TypeError, ValueError):
        return


def _set_button_selected(button: Any, selected: bool) -> None:
    try:
        button.selected = bool(selected)
    except (AttributeError, TypeError):
        return


class _CustomResolutionEditRecovery:
    """Begin-edit recovery controller for the inline custom resolution fields."""

    def __init__(
        self,
        width_field: Any,
        height_field: Any,
        default_width: int,
        default_height: int,
        *,
        ratio_options: tuple[str, ...] = _CUSTOM_RESOLUTION_DEFAULT_RATIOS,
        linked: bool = False,
        bounds: tuple[int, int, int, int] | None = None,
        save_enabled_callback: Callable[[int, int], Any] | None = None,
    ) -> None:
        self._width_field = width_field
        self._height_field = height_field
        self._snapshot = (
            max(1, int(default_width)),
            max(1, int(default_height)),
        )
        self._ratio_options = tuple(ratio_options) or _CUSTOM_RESOLUTION_DEFAULT_RATIOS
        self._ratio = (
            _ratio_value_from_label(self._ratio_options[0])
            or _ratio_value_from_label("16:9")
            or 1.0
        )
        self._linked = bool(linked)
        self._active_field: str | None = None
        self._updating_paired_field = False
        self._ratio_combo_model: Any | None = None
        self._syncing_ratio_combo = False
        self._error_label: Any | None = None
        self._save_button: Any | None = None
        self._save_button_default_enabled = True
        self._save_button_enabled = True
        self._save_enabled_callback = (
            save_enabled_callback if callable(save_enabled_callback) else None
        )
        self._validation_error = ""
        self._cancelled = False
        self._bounds = _normalize_custom_resolution_bounds(bounds)

    @property
    def snapshot(self) -> tuple[int, int]:
        return self._snapshot

    @property
    def linked(self) -> bool:
        return self._linked

    @property
    def ratio(self) -> float:
        return self._ratio

    @property
    def validation_error(self) -> str:
        return self._validation_error

    @property
    def bounds(self) -> tuple[int, int, int, int] | None:
        return self._bounds

    @property
    def save_enabled(self) -> bool:
        return self._save_button_enabled

    def invoke_save_handoff(self, save_callback: Callable[[], Any] | None) -> bool:
        if not self.save_enabled or not callable(save_callback):
            return False
        return bool(save_callback())

    def attach_feedback(
        self,
        *,
        error_label: Any | None = None,
        save_button: Any | None = None,
    ) -> None:
        if error_label is not None:
            self._error_label = error_label
        if save_button is not None:
            self._save_button = save_button
            self._save_button_default_enabled = bool(
                getattr(save_button, "enabled", True)
            )
        self._sync_validation_feedback()

    def _current_pair_is_save_enabled(self) -> bool:
        pair = self._read_positive_pair()
        if pair is None:
            return False
        _bounded, bounds_message = self._clamp_pair_to_bounds(pair)
        if bounds_message:
            return False
        if self._save_enabled_callback is None:
            return True
        try:
            return bool(self._save_enabled_callback(*pair))
        except Exception:
            return False

    def _sync_validation_feedback(self) -> None:
        if self._error_label is not None:
            try:
                self._error_label.text = self._validation_error
            except (AttributeError, TypeError):
                pass
        self._save_button_enabled = (
            self._save_button_default_enabled
            and not bool(self._validation_error)
            and self._current_pair_is_save_enabled()
        )
        if self._save_button is not None:
            try:
                self._save_button.enabled = self._save_button_enabled
            except (AttributeError, TypeError):
                pass

    def _set_validation_error(self, message: str) -> None:
        self._validation_error = str(message)
        self._sync_validation_feedback()

    def _clear_validation_error(self) -> None:
        if self._validation_error:
            self._validation_error = ""
        self._sync_validation_feedback()

    def _dimension_error_message(self, active_field: str | None) -> str:
        label = "Width" if active_field != "height" else "Height"
        return f"{label} must be a positive integer."

    def _clamp_pair_to_bounds(
        self,
        pair: tuple[int, int],
    ) -> tuple[tuple[int, int], str]:
        if self._bounds is None:
            return pair, ""
        min_width, min_height, max_width, max_height = self._bounds
        width, height = pair
        bounded = (
            max(min_width, min(max_width, width)),
            max(min_height, min(max_height, height)),
        )
        if bounded == pair:
            return pair, ""
        below_min = width < min_width or height < min_height
        above_max = width > max_width or height > max_height
        if below_min and above_max:
            message = (
                f"Clamped to bounds {min_width}x{min_height}-"
                f"{max_width}x{max_height}."
            )
        elif below_min:
            message = f"Clamped to minimum {min_width}x{min_height}."
        else:
            message = f"Clamped to maximum {max_width}x{max_height}."
        return bounded, message

    def _sync_bounds_feedback_for_pair(self, pair: tuple[int, int] | None) -> None:
        if pair is None:
            return
        _bounded, message = self._clamp_pair_to_bounds(pair)
        if message:
            self._set_validation_error(message)
        else:
            self._clear_validation_error()

    def _set_field_pair_value(self, pair: tuple[int, int]) -> None:
        width, height = pair
        self._updating_paired_field = True
        try:
            _set_numeric_field_value(self._width_field, width)
            _set_numeric_field_value(self._height_field, height)
        finally:
            self._updating_paired_field = False

    def _read_positive_pair(self) -> tuple[int, int] | None:
        width = _read_positive_numeric_field_value(self._width_field)
        height = _read_positive_numeric_field_value(self._height_field)
        if width is None or height is None:
            return None
        return width, height

    def _read_positive_pair_or_error(
        self,
        active_field: str | None = None,
        *,
        show_error: bool = False,
    ) -> tuple[int, int] | None:
        width = _read_positive_numeric_field_value(self._width_field)
        height = _read_positive_numeric_field_value(self._height_field)
        invalid_field = None
        if active_field == "height" and height is None:
            invalid_field = "height"
        elif active_field == "width" and width is None:
            invalid_field = "width"
        elif width is None:
            invalid_field = "width"
        elif height is None:
            invalid_field = "height"
        if invalid_field is not None:
            if show_error:
                self._set_validation_error(
                    self._dimension_error_message(invalid_field)
                )
            return None
        if show_error:
            self._clear_validation_error()
        return width, height

    def set_linked(self, linked: bool) -> None:
        self._linked = bool(linked)

    def toggle_linked(self) -> bool:
        self._linked = not self._linked
        return self._linked

    def set_ratio_by_index(self, index: int) -> None:
        try:
            selected_index = int(index)
        except (IndexError, TypeError, ValueError):
            return
        label: str | None = None
        if 0 <= selected_index < len(self._ratio_options):
            label = self._ratio_options[selected_index]
        elif self._ratio_combo_model is not None:
            children = self._ratio_combo_children()
            if 0 <= selected_index < len(children):
                label = _combo_item_text(
                    self._ratio_combo_model,
                    children[selected_index],
                )
        if label is None:
            return
        ratio = _ratio_value_from_label(label)
        if ratio is not None:
            self._ratio = ratio

    def attach_ratio_combo_model(self, model: Any) -> None:
        self._ratio_combo_model = model
        self._sync_ratio_combo_to_current_fields()

    def ratio_choice_labels(self) -> tuple[str, ...]:
        return self._ratio_options

    def _ratio_combo_children(self) -> list[Any]:
        if self._ratio_combo_model is None:
            return []
        try:
            return list(self._ratio_combo_model.get_item_children(None))
        except (AttributeError, TypeError):
            return []

    def _set_ratio_combo_index(self, index: int) -> None:
        if self._ratio_combo_model is None:
            return
        self._syncing_ratio_combo = True
        try:
            _set_combo_selected_index(self._ratio_combo_model, index)
        finally:
            self._syncing_ratio_combo = False

    def _remove_temporary_custom_ratio_items(self) -> None:
        if self._ratio_combo_model is None:
            return
        children = self._ratio_combo_children()
        for item in reversed(children[len(self._ratio_options) :]):
            _remove_combo_item(self._ratio_combo_model, item)

    def _sync_ratio_combo_to_pair(self, pair: tuple[int, int] | None) -> None:
        if self._ratio_combo_model is None or pair is None:
            return
        label = _ratio_label_for_dimensions(*pair)
        if not label:
            return
        try:
            listed_index = self._ratio_options.index(label)
        except ValueError:
            listed_index = -1
        if listed_index >= 0:
            self._remove_temporary_custom_ratio_items()
            self._set_ratio_combo_index(listed_index)
            ratio = _ratio_value_from_label(label)
            if ratio is not None:
                self._ratio = ratio
            return

        self._remove_temporary_custom_ratio_items()
        appended = _append_combo_string_item(self._ratio_combo_model, label)
        if appended is None:
            return
        custom_index = len(self._ratio_options)
        self._set_ratio_combo_index(custom_index)
        ratio = _ratio_value_from_label(label)
        if ratio is not None:
            self._ratio = ratio

    def _sync_ratio_combo_to_current_fields(self) -> None:
        self._sync_ratio_combo_to_pair(self._read_positive_pair())

    def _linked_pair_for_active_field(
        self,
        active_field: str | None,
        *,
        show_error: bool = False,
    ) -> tuple[int, int] | None:
        if not self._linked:
            return self._read_positive_pair_or_error(
                active_field,
                show_error=show_error,
            )
        if active_field == "width":
            width = _read_positive_numeric_field_value(self._width_field)
            if width is None:
                if show_error:
                    self._set_validation_error(
                        self._dimension_error_message("width")
                    )
                return None
            height = int(width / self._ratio)
            if height <= 0:
                if show_error:
                    self._set_validation_error(
                        self._dimension_error_message("height")
                    )
                return None
            self._set_paired_field_value(self._height_field, height)
            if show_error:
                self._clear_validation_error()
            return width, height
        if active_field == "height":
            height = _read_positive_numeric_field_value(self._height_field)
            if height is None:
                if show_error:
                    self._set_validation_error(
                        self._dimension_error_message("height")
                    )
                return None
            width = int(height * self._ratio)
            if width <= 0:
                if show_error:
                    self._set_validation_error(
                        self._dimension_error_message("width")
                    )
                return None
            self._set_paired_field_value(self._width_field, width)
            if show_error:
                self._clear_validation_error()
            return width, height
        return self._read_positive_pair_or_error(
            active_field,
            show_error=show_error,
        )

    def _set_paired_field_value(self, field: Any, value: int) -> None:
        self._updating_paired_field = True
        try:
            _set_numeric_field_value(field, value)
        finally:
            self._updating_paired_field = False

    def update_linked_pair(self, active_field: str) -> tuple[int, int] | None:
        """Update the non-edited field while typing when ratio linking is on."""

        if self._updating_paired_field:
            return None
        if active_field not in {"width", "height"}:
            return None
        self._active_field = active_field
        if not self._linked:
            pair = self._read_positive_pair_or_error(
                active_field,
                show_error=True,
            )
            self._sync_bounds_feedback_for_pair(pair)
            self._sync_ratio_combo_to_pair(pair)
            return pair
        pair = self._linked_pair_for_active_field(active_field, show_error=True)
        self._sync_bounds_feedback_for_pair(pair)
        self._sync_ratio_combo_to_pair(pair)
        return pair

    def restore_snapshot(self) -> None:
        width, height = self._snapshot
        self._updating_paired_field = True
        try:
            _set_numeric_field_value(self._width_field, width)
            _set_numeric_field_value(self._height_field, height)
        finally:
            self._updating_paired_field = False

    def begin_edit(self, _model: Any = None, active_field: str | None = None) -> None:
        pair = self._read_positive_pair()
        if pair is not None:
            self._snapshot = pair
        if active_field in {"width", "height"}:
            self._active_field = active_field
        self._cancelled = False
        self._clear_validation_error()

    def cancel_edit(self) -> None:
        self._cancelled = True
        self.restore_snapshot()
        self._clear_validation_error()

    def end_edit(
        self,
        apply_callback: Callable[[int, int], Any] | None,
        _model: Any = None,
        active_field: str | None = None,
    ) -> None:
        if self._cancelled:
            self.restore_snapshot()
            self._cancelled = False
            return
        if active_field in {"width", "height"}:
            self._active_field = active_field
        pair = self._linked_pair_for_active_field(
            self._active_field,
            show_error=True,
        )
        if pair is None:
            self.restore_snapshot()
            self._sync_ratio_combo_to_pair(self._snapshot)
            return
        bounded_pair, bounds_message = self._clamp_pair_to_bounds(pair)
        if bounds_message:
            self._set_field_pair_value(bounded_pair)
            pair = bounded_pair
        self._sync_ratio_combo_to_pair(pair)
        if callable(apply_callback) and bool(apply_callback(*pair)):
            self._snapshot = pair
            if bounds_message:
                self._set_validation_error(bounds_message)
            else:
                self._clear_validation_error()
            return
        self._set_validation_error("Custom resolution was not accepted.")
        self.restore_snapshot()
        self._sync_ratio_combo_to_pair(self._snapshot)


def _parse_custom_resolution_editor_payload(text: str) -> str:
    payload = _payload_after_marker(text, CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER)
    if not payload:
        return ""
    parts = payload.split("|")
    return parts[0] if parts else ""


def _parse_custom_resolution_editor_apply_payload(text: str) -> str:
    payload = _payload_after_marker(text, CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER)
    if not payload:
        return ""
    parts = payload.split("|")
    if len(parts) < 2:
        return ""
    return parts[1]


def _parse_custom_resolution_editor_default_size_payload(
    text: str,
) -> tuple[int, int] | None:
    payload = _payload_after_marker(text, CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER)
    if not payload:
        return None
    parts = payload.split("|")
    if len(parts) < 4:
        return None
    try:
        width, height = int(parts[2]), int(parts[3])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _parse_custom_resolution_editor_bounds_payload(
    text: str,
) -> tuple[int, int, int, int] | None:
    payload = _payload_after_marker(text, CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER)
    if not payload:
        return None
    parts = payload.split("|")
    if len(parts) < 8:
        return None
    return _normalize_custom_resolution_bounds(parts[4:8])


def _parse_custom_resolution_editor_save_enabled_payload(text: str) -> str:
    payload = _payload_after_marker(text, CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER)
    if not payload:
        return ""
    parts = payload.split("|")
    if len(parts) < 9:
        return ""
    return parts[8]


def _build_custom_resolution_editor_item(item: Any) -> None:
    """Build the embedded non-hiding Custom Resolution row."""

    import omni.ui as ui

    label_text = str(getattr(item, "text", "Custom Resolution"))
    hotkey_text = str(getattr(item, "hotkey_text", ""))
    save_callback = _lookup_menu_control_callback(
        _parse_custom_resolution_editor_payload(hotkey_text)
    )
    apply_callback = _lookup_menu_control_callback(
        _parse_custom_resolution_editor_apply_payload(hotkey_text)
    )
    save_enabled_callback = _lookup_menu_control_callback(
        _parse_custom_resolution_editor_save_enabled_payload(hotkey_text)
    )
    payload_default_size = _parse_custom_resolution_editor_default_size_payload(
        hotkey_text
    )
    if payload_default_size is None:
        default_width = int(getattr(item, "custom_resolution_default_width", 1920))
        default_height = int(getattr(item, "custom_resolution_default_height", 1080))
    else:
        default_width, default_height = payload_default_size
    payload_bounds = _parse_custom_resolution_editor_bounds_payload(hotkey_text)
    item_bounds = _normalize_custom_resolution_bounds(
        (
            getattr(item, "custom_resolution_min_width", 0),
            getattr(item, "custom_resolution_min_height", 0),
            getattr(item, "custom_resolution_max_width", 0),
            getattr(item, "custom_resolution_max_height", 0),
        )
    )
    bounds = payload_bounds or item_bounds
    ratio_options = tuple(
        getattr(
            item,
            "custom_resolution_ratio_options",
            _CUSTOM_RESOLUTION_DEFAULT_RATIOS,
        )
    ) or _CUSTOM_RESOLUTION_DEFAULT_RATIOS
    enabled = bool(getattr(item, "enabled", True))
    disabled_reason = str(
        getattr(item, "custom_resolution_disabled_reason", "")
        or getattr(item, "disabled_reason", "")
        or getattr(item, "tooltip", "")
        or ""
    )

    with ui.VStack(height=_CUSTOM_RESOLUTION_ROW_HEIGHT, spacing=2):
        with ui.HStack(height=_CUSTOM_RESOLUTION_LABEL_HEIGHT, spacing=0):
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)
            title = ui.Label(
                label_text,
                alignment=ui.Alignment.LEFT_CENTER,
                identifier=str(
                    getattr(
                        item,
                        "custom_resolution_title_identifier",
                        "viewport_custom_resolution_title",
                    )
                ),
                style_type_name_override="Menu.Item",
            )
            title.enabled = enabled
            if not enabled and disabled_reason:
                try:
                    title.tooltip = disabled_reason
                except (AttributeError, TypeError):
                    pass
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)

        with ui.HStack(height=_CUSTOM_RESOLUTION_CONTROL_HEIGHT, spacing=0):
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)
            width_field_kwargs: dict[str, Any] = {
                "width": _CUSTOM_RESOLUTION_WIDTH,
                "height": _CUSTOM_RESOLUTION_CONTROL_HEIGHT,
                "identifier": str(
                    getattr(
                        item,
                        "custom_resolution_width_identifier",
                        "viewport_custom_resolution_width_field",
                    )
                ),
            }
            if not enabled and disabled_reason:
                width_field_kwargs["tooltip"] = disabled_reason
            width_field = ui.IntField(**width_field_kwargs)
            _set_numeric_field_value(width_field, default_width)
            try:
                width_field.enabled = enabled
            except (AttributeError, TypeError):
                pass
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)
            link_button_ref: dict[str, Any] = {}

            def _on_custom_resolution_begin_edit(
                _model: Any = None,
                *,
                active_field: str,
            ) -> None:
                recovery.begin_edit(_model, active_field=active_field)

            def _on_custom_resolution_end_edit(
                _model: Any = None,
                *,
                active_field: str,
            ) -> None:
                recovery.end_edit(apply_callback, _model, active_field=active_field)

            def _sync_link_button_state() -> None:
                button = link_button_ref.get("button")
                if button is not None:
                    _set_button_selected(button, recovery.linked)

            def _on_link_toggle_clicked() -> None:
                recovery.toggle_linked()
                _sync_link_button_state()

            def _on_custom_resolution_key_pressed(
                key: int,
                _modifier: int,
                pressed: bool,
            ) -> None:
                try:
                    key_code = int(key)
                except (TypeError, ValueError):
                    return
                if pressed and key_code == _KEY_ESCAPE:
                    recovery.cancel_edit()

            link_button_kwargs: dict[str, Any] = {
                "width": _CUSTOM_RESOLUTION_LINK_WIDTH,
                "height": _CUSTOM_RESOLUTION_CONTROL_HEIGHT,
                "identifier": str(
                    getattr(
                        item,
                        "custom_resolution_link_identifier",
                        "viewport_custom_resolution_link_toggle",
                    )
                ),
                "style_type_name_override": "Menu.ControlButton",
            }
            if not enabled and disabled_reason:
                link_button_kwargs["tooltip"] = disabled_reason
            if enabled:
                link_button_kwargs["clicked_fn"] = _on_link_toggle_clicked
            link_button = ui.Button("L", **link_button_kwargs)
            try:
                link_button.enabled = enabled
            except (AttributeError, TypeError):
                pass
            link_button_ref["button"] = link_button
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)
            height_field_kwargs: dict[str, Any] = {
                "width": _CUSTOM_RESOLUTION_WIDTH,
                "height": _CUSTOM_RESOLUTION_CONTROL_HEIGHT,
                "identifier": str(
                    getattr(
                        item,
                        "custom_resolution_height_identifier",
                        "viewport_custom_resolution_height_field",
                    )
                ),
            }
            if not enabled and disabled_reason:
                height_field_kwargs["tooltip"] = disabled_reason
            height_field = ui.IntField(**height_field_kwargs)
            _set_numeric_field_value(height_field, default_height)
            try:
                height_field.enabled = enabled
            except (AttributeError, TypeError):
                pass
            recovery = _CustomResolutionEditRecovery(
                width_field,
                height_field,
                default_width,
                default_height,
                ratio_options=tuple(str(option) for option in ratio_options),
                linked=False,
                bounds=bounds,
                save_enabled_callback=save_enabled_callback,
            )
            _sync_link_button_state()
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)

            for active_field, field in (
                ("width", width_field),
                ("height", height_field),
            ):
                model = getattr(field, "model", None)
                add_begin_edit_fn = getattr(model, "add_begin_edit_fn", None)
                if enabled and callable(add_begin_edit_fn):
                    def _begin_edit_callback(
                        _model: Any = None,
                        field_name: str = active_field,
                    ) -> None:
                        _on_custom_resolution_begin_edit(
                            _model,
                            active_field=field_name,
                        )

                    add_begin_edit_fn(_begin_edit_callback)
                add_end_edit_fn = getattr(model, "add_end_edit_fn", None)
                if enabled and callable(add_end_edit_fn):
                    def _end_edit_callback(
                        _model: Any = None,
                        field_name: str = active_field,
                    ) -> None:
                        _on_custom_resolution_end_edit(
                            _model,
                            active_field=field_name,
                        )

                    add_end_edit_fn(_end_edit_callback)
                add_value_changed_fn = getattr(model, "add_value_changed_fn", None)
                if enabled and callable(add_value_changed_fn):
                    def _value_changed_callback(
                        _model: Any = None,
                        field_name: str = active_field,
                    ) -> None:
                        recovery.update_linked_pair(field_name)

                    add_value_changed_fn(_value_changed_callback)
                set_key_pressed_fn = getattr(field, "set_key_pressed_fn", None)
                if enabled and callable(set_key_pressed_fn):
                    set_key_pressed_fn(_on_custom_resolution_key_pressed)
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)
            ratio_model = ui.SimpleListModel(list(ratio_options), 0)
            combo = ui.ComboBox(
                ratio_model,
                width=_CUSTOM_RESOLUTION_RATIO_WIDTH,
                height=_CUSTOM_RESOLUTION_CONTROL_HEIGHT,
                style_type_name_override="Menu.ControlComboBox",
                identifier=str(
                    getattr(
                        item,
                        "custom_resolution_ratio_identifier",
                        "viewport_custom_resolution_ratio_combo",
                    )
                ),
            )
            try:
                combo.enabled = enabled
            except (AttributeError, TypeError):
                pass
            if not enabled and disabled_reason:
                try:
                    combo.tooltip = disabled_reason
                except (AttributeError, TypeError):
                    pass
            combo_model = getattr(combo, "model", None)
            recovery.attach_ratio_combo_model(combo_model)
            add_item_changed_fn = getattr(combo_model, "add_item_changed_fn", None)
            if enabled and callable(add_item_changed_fn):

                def _on_ratio_changed(model: Any, changed_item: Any) -> None:
                    if changed_item is not None:
                        return
                    if recovery._syncing_ratio_combo:
                        return
                    try:
                        selected_index = int(
                            _root_combo_value_model(model).get_value_as_int()
                        )
                    except (AttributeError, TypeError, ValueError):
                        return
                    recovery.set_ratio_by_index(selected_index)

                add_item_changed_fn(_on_ratio_changed)
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)
            save_kwargs: dict[str, Any] = {
                "width": _CUSTOM_RESOLUTION_SAVE_WIDTH,
                "height": _CUSTOM_RESOLUTION_CONTROL_HEIGHT,
                "identifier": str(
                    getattr(
                        item,
                        "custom_resolution_save_identifier",
                        "viewport_custom_resolution_save_button",
                    )
                ),
                "style_type_name_override": "Menu.ControlButton",
            }
            if not enabled and disabled_reason:
                save_kwargs["tooltip"] = disabled_reason
            if enabled and callable(save_callback):
                save_kwargs["clicked_fn"] = (
                    lambda: recovery.invoke_save_handoff(save_callback)
                )
            save_button = ui.Button("S", **save_kwargs)
            try:
                save_button.enabled = enabled
            except (AttributeError, TypeError):
                pass
            recovery.attach_feedback(save_button=save_button)
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)

        with ui.HStack(height=_CUSTOM_RESOLUTION_LABEL_HEIGHT, spacing=0):
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)
            width_label = ui.Label(
                "Width",
                width=_CUSTOM_RESOLUTION_WIDTH,
                alignment=ui.Alignment.CENTER,
                identifier=str(
                    getattr(
                        item,
                        "custom_resolution_width_label_identifier",
                        "viewport_custom_resolution_width_label",
                    )
                ),
                style_type_name_override="Menu.Item.Hotkey",
            )
            width_label.enabled = enabled
            ui.Spacer(
                width=(
                    _CUSTOM_RESOLUTION_GAP
                    + _CUSTOM_RESOLUTION_LINK_WIDTH
                    + _CUSTOM_RESOLUTION_GAP
                )
            )
            height_label = ui.Label(
                "Height",
                width=_CUSTOM_RESOLUTION_WIDTH,
                alignment=ui.Alignment.CENTER,
                identifier=str(
                    getattr(
                        item,
                        "custom_resolution_height_label_identifier",
                        "viewport_custom_resolution_height_label",
                    )
                ),
                style_type_name_override="Menu.Item.Hotkey",
            )
            height_label.enabled = enabled
            ui.Spacer()

        with ui.HStack(height=_CUSTOM_RESOLUTION_ERROR_HEIGHT, spacing=0):
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)
            error_label = ui.Label(
                "",
                alignment=ui.Alignment.LEFT_CENTER,
                identifier="viewport_custom_resolution_error_label",
                style_type_name_override="Menu.Item.Hotkey",
            )
            error_label.enabled = enabled
            recovery.attach_feedback(error_label=error_label)
            if not enabled and disabled_reason:
                recovery._set_validation_error(disabled_reason)
            ui.Spacer(width=_CUSTOM_RESOLUTION_GAP)


def _payload_after_marker(text: str, marker: str) -> str:
    if text.startswith(f"{marker}|"):
        return text[len(marker) + 1 :]
    return ""


def _parse_render_scale_payload(text: str) -> tuple[int, tuple[str, ...], str]:
    payload = _payload_after_marker(text, RENDER_SCALE_COMBO_HOTKEY_MARKER)
    if not payload:
        return 0, ("100%",), ""
    try:
        parts = payload.split("|", 2)
        if len(parts) == 2:
            raw_index, raw_options = parts
            callback_token = ""
        else:
            raw_index, callback_token, raw_options = parts
        labels = tuple(label for label in raw_options.split(",") if label)
        index = int(raw_index)
    except (TypeError, ValueError):
        return 0, ("100%",), ""
    if not labels:
        return 0, ("100%",), ""
    if index < 0 or index >= len(labels):
        index = 0
    return index, labels, callback_token


def _parse_fill_viewport_payload(text: str) -> tuple[bool, bool, str]:
    payload = _payload_after_marker(text, FILL_VIEWPORT_CHECKBOX_HOTKEY_MARKER)
    if not payload:
        return True, False, ""
    parts = payload.split("|", 2)
    if len(parts) == 2:
        return parts[0] == "1", parts[1] == "1", ""
    if len(parts) != 3:
        return True, False, ""
    return parts[0] == "1", parts[1] == "1", parts[2]


def _parse_saved_custom_delete_payload(text: str) -> tuple[str, str]:
    payload = _payload_after_marker(text, SAVED_CUSTOM_DELETE_HOTKEY_MARKER)
    if not payload:
        return text, ""
    parts = payload.split("|", 1)
    if len(parts) != 2:
        return "", ""
    callback_token, detail_text = parts
    return detail_text, callback_token


def _build_render_scale_combo_item(item: Any) -> None:
    """Build the Render Scale combo row."""

    import omni.ui as ui

    label_text = str(getattr(item, "text", "Render Scale"))
    hotkey_text = str(getattr(item, "hotkey_text", ""))
    current_index, option_labels, callback_token = _parse_render_scale_payload(
        hotkey_text
    )
    callback = _lookup_menu_control_callback(callback_token)
    enabled = bool(getattr(item, "enabled", True))
    disabled_reason = str(
        getattr(item, "disabled_reason", "")
        or getattr(item, "tooltip", "")
        or ""
    )

    with ui.HStack(height=_RENDER_SCALE_ROW_HEIGHT, spacing=0):
        ui.Spacer(width=_MENU_CONTROL_GAP)
        label = ui.Label(
            label_text,
            alignment=ui.Alignment.LEFT_CENTER,
            identifier=str(
                getattr(
                    item,
                    "render_scale_label_identifier",
                    "viewport_render_scale_label",
                )
            ),
            style_type_name_override="Menu.Item",
        )
        label.enabled = enabled
        if not enabled and disabled_reason:
            try:
                label.tooltip = disabled_reason
            except (AttributeError, TypeError):
                pass
        ui.Spacer(width=_MENU_CONTROL_GAP)
        with ui.VStack(
            width=_RENDER_SCALE_COMBO_WIDTH,
            height=_RENDER_SCALE_ROW_HEIGHT,
            spacing=0,
        ):
            ui.Spacer(height=_RENDER_SCALE_COMBO_TOP_INSET)
            combo = ui.ComboBox(
                current_index,
                *option_labels,
                width=_RENDER_SCALE_COMBO_WIDTH,
                height=_RENDER_SCALE_COMBO_HEIGHT,
                style_type_name_override="Menu.ControlComboBox",
                identifier=str(
                    getattr(
                        item,
                        "render_scale_identifier",
                        "viewport_render_scale_combo",
                    )
                ),
            )
            ui.Spacer(height=_RENDER_SCALE_COMBO_BOTTOM_INSET)
        combo.enabled = enabled
        if not enabled and disabled_reason:
            try:
                combo.tooltip = disabled_reason
            except (AttributeError, TypeError):
                pass
        if enabled and callable(callback):
            rolling_back = {"active": False}

            def _root_model(model: Any) -> Any:
                try:
                    return model.get_item_value_model(None)
                except TypeError:
                    return model.get_item_value_model()

            def _on_item_changed(model: Any, changed_item: Any) -> None:
                if rolling_back["active"] or changed_item is not None:
                    return
                root = _root_model(model)
                selected_index = int(root.get_value_as_int())
                if selected_index == current_index:
                    return
                accepted = bool(callback(selected_index))
                if accepted:
                    return
                rolling_back["active"] = True
                try:
                    root.set_value(int(current_index))
                finally:
                    rolling_back["active"] = False

            combo.model.add_item_changed_fn(_on_item_changed)
        ui.Spacer(width=_MENU_CONTROL_GAP)


def _build_fill_viewport_checkbox_item(item: Any) -> None:
    """Build the Fill Viewport checkbox row."""

    import omni.ui as ui

    label_text = str(getattr(item, "text", "Fill Viewport"))
    hotkey_text = str(getattr(item, "hotkey_text", ""))
    enabled, checked, callback_token = _parse_fill_viewport_payload(hotkey_text)
    tooltip = str(
        getattr(
            item,
            "fill_viewport_disabled_reason",
            _FILL_VIEWPORT_DEFAULT_DISABLED_TOOLTIP,
        )
    )

    with ui.HStack(height=_FILL_VIEWPORT_ROW_HEIGHT, spacing=0):
        ui.Spacer(width=_MENU_CONTROL_GAP)
        label = ui.Label(
            label_text,
            alignment=ui.Alignment.LEFT_CENTER,
            identifier=str(
                getattr(
                    item,
                    "fill_viewport_label_identifier",
                    "viewport_fill_viewport_label",
                )
            ),
            style_type_name_override="Menu.Item",
        )
        label.enabled = enabled
        if not enabled and tooltip:
            try:
                label.tooltip = tooltip
            except (AttributeError, TypeError):
                pass
        ui.Spacer(width=_MENU_CONTROL_GAP)
        with ui.VStack(
            width=_FILL_VIEWPORT_CHECKBOX_SLOT_WIDTH,
            height=_FILL_VIEWPORT_ROW_HEIGHT,
            spacing=0,
        ):
            ui.Spacer(height=_FILL_VIEWPORT_CHECKBOX_TOP_INSET)
            checkbox = ui.CheckBox(
                width=_FILL_VIEWPORT_CHECKBOX_SIZE,
                height=_FILL_VIEWPORT_CHECKBOX_SIZE,
                identifier=str(
                    getattr(
                        item,
                        "fill_viewport_identifier",
                        "viewport_fill_viewport_checkbox",
                    )
                ),
                tooltip="" if enabled else tooltip,
            )
            try:
                checkbox.model.set_value(bool(checked))
            except (AttributeError, TypeError, ValueError):
                pass
            checkbox.enabled = enabled
            ui.Spacer(height=_FILL_VIEWPORT_CHECKBOX_TOP_INSET)
        ui.Spacer(width=_MENU_CONTROL_GAP)


def _is_menu_bar_root(item: Any) -> bool:
    return str(getattr(item, "style_type_name_override", "") or "") == "MenuBar.Menu"


def _build_menu_item(item: Any) -> None:
    """Build menu rows, only overriding shortcut text alignment."""
    import omni.ui as ui

    is_item = isinstance(item, ui.MenuItem)
    is_submenu = isinstance(item, ui.Menu)
    if not (is_item or is_submenu) or isinstance(item, ui.Separator):
        _get_base_menu_delegate().build_item(item)
        return
    if is_submenu and _is_menu_bar_root(item):
        _get_base_menu_delegate().build_item(item)
        return

    hotkey_text = str(getattr(item, "hotkey_text", "") or "")
    if hotkey_text.startswith(CUSTOM_RESOLUTION_EDITOR_HOTKEY_MARKER) or bool(
        getattr(item, "custom_resolution_editor", False)
    ):
        _build_custom_resolution_editor_item(item)
        return
    if hotkey_text.startswith(RENDER_SCALE_COMBO_HOTKEY_MARKER) or bool(
        getattr(item, "render_scale_combo", False)
    ):
        _build_render_scale_combo_item(item)
        return
    if hotkey_text.startswith(FILL_VIEWPORT_CHECKBOX_HOTKEY_MARKER) or bool(
        getattr(item, "fill_viewport_checkbox", False)
    ):
        _build_fill_viewport_checkbox_item(item)
        return

    if is_submenu and not hotkey_text:
        _get_base_menu_delegate().build_item(item)
        return

    if not hotkey_text:
        _get_base_menu_delegate().build_item(item)
        return

    icon_width = 20.0
    enabled = bool(getattr(item, "enabled", True))
    disabled_reason = str(
        getattr(item, "disabled_reason", "")
        or getattr(item, "tooltip", "")
        or ""
    )
    delete_detail_text, delete_payload_token = _parse_saved_custom_delete_payload(
        hotkey_text
    )
    delete_affordance = bool(getattr(item, "delete_affordance", False)) or bool(
        delete_payload_token
    )
    row_callback = getattr(item, "row_handoff_fn", None)
    if not callable(row_callback):
        row_callback = _lookup_menu_control_callback(
            str(getattr(item, "row_callback_token", "") or "")
        )
    delete_callback = getattr(item, "delete_handoff_fn", None)
    if not callable(delete_callback):
        delete_callback = _lookup_menu_control_callback(
            str(getattr(item, "delete_callback_token", "") or delete_payload_token)
        )
    hotkey_display_text = str(delete_detail_text if delete_affordance else hotkey_text)
    if delete_affordance and hotkey_display_text.endswith("  x"):
        hotkey_display_text = hotkey_display_text[:-3]
    hotkey_width = _MENU_ITEM_HOTKEY_WIDTH
    if delete_affordance:
        hotkey_width = max(
            40.0,
            _MENU_ITEM_HOTKEY_WIDTH - _MENU_ITEM_DELETE_WIDTH - _MENU_ITEM_DELETE_GAP,
        )
    row_identifier = _item_identifier(item, "inspector_target", "viewport_menu_item")
    delete_identifier = str(
        getattr(item, "delete_inspector_target", "") or f"{row_identifier}_delete"
    )

    def _build_row_text() -> None:
        row_is_checked = bool(getattr(item, "checked", False))
        if bool(getattr(item, "checkable", False)) or row_is_checked:
            if row_is_checked:
                check = ui.ImageWithProvider(
                    width=icon_width,
                    style_type_name_override="Menu.Item.CheckMark",
                )
                check.enabled = enabled
            else:
                ui.Spacer(width=icon_width)
        else:
            ui.Spacer(width=icon_width / 3.0)

        label = ui.Label(
            getattr(item, "text", ""),
            identifier=f"{row_identifier}_label",
            style_type_name_override="Menu.Item",
        )
        label.enabled = enabled
        if not enabled and disabled_reason:
            try:
                label.tooltip = disabled_reason
            except (AttributeError, TypeError):
                pass
        hotkey = ui.Label(
            hotkey_display_text,
            width=hotkey_width,
            alignment=ui.Alignment.RIGHT_CENTER,
            identifier=f"{row_identifier}_detail",
            style_type_name_override="Menu.Item.Hotkey",
        )
        hotkey.enabled = enabled
        if not enabled and disabled_reason:
            try:
                hotkey.tooltip = disabled_reason
            except (AttributeError, TypeError):
                pass

    with ui.HStack():
        if delete_affordance and callable(row_callback):
            row_click_width = (
                _MENU_ITEM_HOTKEY_WIDTH
                + icon_width
                + _MENU_ITEM_DELETE_WIDTH
                + _MENU_ITEM_DELETE_GAP
            )
            with ui.ZStack(width=row_click_width, height=_MENU_CONTROL_ROW_HEIGHT):
                with ui.HStack():
                    _build_row_text()
                row_button = ui.InvisibleButton(
                    width=row_click_width,
                    height=_MENU_CONTROL_ROW_HEIGHT,
                    identifier=row_identifier,
                    tooltip=(
                        disabled_reason
                        if not enabled and disabled_reason
                        else str(getattr(item, "text", ""))
                    ),
                )
                row_button.enabled = enabled
                if enabled:
                    row_button.set_clicked_fn(lambda: bool(row_callback()))
        else:
            _build_row_text()
        if delete_affordance:
            ui.Spacer(width=_MENU_ITEM_DELETE_GAP)
            with ui.ZStack(
                width=_MENU_ITEM_DELETE_WIDTH,
                height=_MENU_CONTROL_ROW_HEIGHT - 6.0,
                identifier=f"{delete_identifier}_frame",
            ):
                delete_background = ui.Rectangle(style_type_name_override="Button")
                delete_background.enabled = enabled
                delete_label = ui.Label(
                    "x",
                    alignment=ui.Alignment.CENTER,
                    style_type_name_override="Button",
                )
                delete_label.enabled = enabled
                delete_button = ui.InvisibleButton(
                    width=_MENU_ITEM_DELETE_WIDTH,
                    height=_MENU_CONTROL_ROW_HEIGHT - 6.0,
                    identifier=delete_identifier,
                    tooltip=(
                        disabled_reason
                        if not enabled and disabled_reason
                        else str(getattr(item, "delete_tooltip", "Delete"))
                    ),
                )
                delete_button.enabled = enabled
                if enabled and callable(delete_callback):
                    delete_button.set_clicked_fn(lambda: bool(delete_callback()))
        if is_submenu:
            chevron = ui.ImageWithProvider(
                width=icon_width,
                style_type_name_override="Menu.Item.ExpandMark",
            )
            chevron.enabled = enabled


def get_flat_menu_delegate() -> Any:
    """Return the shared delegate used by popup menus without title chrome."""
    global _FLAT_MENU_DELEGATE
    if _FLAT_MENU_DELEGATE is None:
        import omni.ui as ui

        _FLAT_MENU_DELEGATE = ui.MenuDelegate(
            on_build_item=_build_menu_item,
            on_build_title=_build_no_title,
            on_build_status=_build_no_title,
            propagate=True,
        )
    return _FLAT_MENU_DELEGATE


def create_flat_menu(
    text: str = "",
    *,
    ui_module: Any | None = None,
    **kwargs: Any,
) -> Any:
    """Create a menu using the shared no-title popup delegate."""
    if ui_module is None:
        import omni.ui as ui
    else:
        ui = ui_module

    if hasattr(ui, "MenuDelegate"):
        kwargs.setdefault("delegate", get_flat_menu_delegate())
    return ui.Menu(text, **kwargs)
