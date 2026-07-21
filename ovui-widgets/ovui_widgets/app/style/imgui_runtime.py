# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Public-runtime application of OVUI docking tab style tokens.

Most OVUI widgets read ``ui.style.default`` directly. ImGui-owned docking
splitters and document tabs live below omni.ui's widget style selectors, so
Python may only pass resolved token values to a sanctioned omni.ui binding.
This module deliberately does not load native libraries, inspect symbols, or
touch raw addresses from Python.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImGuiSplitterStyle:
    visual_width: float
    hit_target: float
    hover_padding: float
    splitter_handle_color: int
    splitter_handle_hovered_color: int
    tab_height: float
    tab_close_min_width_selected: float
    tab_close_min_width_unselected: float
    tab_rounding: float
    tab_border_size: float
    tab_bar_border_size: float
    tab_bar_overline_size: float
    dock_tab_inactive_separator_inset: float
    dock_tab_use_tab_colors: bool
    dock_tab_single_tab_uses_selected_color: bool
    dock_tab_draw_inactive_separators: bool
    tab_use_rectangular_shape: bool
    dock_tab_text_color: int
    dock_tab_color: int
    dock_tab_hovered_color: int
    dock_tab_selected_color: int
    dock_tab_selected_overline_color: int
    dock_tab_dimmed_color: int
    dock_tab_dimmed_selected_color: int
    dock_tab_dimmed_selected_overline_color: int
    title_bg_color: int
    title_bg_active_color: int
    title_bg_collapsed_color: int
    dpi_scale: float


def apply_imgui_splitter_style() -> bool:
    """Apply OVUI docking tokens through the sanctioned omni.ui binding."""

    import omni.ui as ui

    apply_docking_style = getattr(ui, "apply_imgui_docking_style", None)
    if apply_docking_style is None:
        return False

    style = _read_imgui_splitter_style_for_tests()
    payload = _imgui_docking_style_payload(style)
    try:
        return bool(apply_docking_style(**payload))
    except TypeError:
        # Editable/dev environments can briefly have the previous public
        # binding loaded while Python source is newer. Keep using the public
        # binding only, but retry with prior signatures; rebuilt binaries
        # receive the full token payload above.
        compat_payload = dict(payload)
        selected_close_width = compat_payload.pop("tab_close_min_width_selected")
        compat_payload.pop("tab_close_min_width_unselected")
        compat_payload["tab_close_min_width"] = selected_close_width
        try:
            return bool(apply_docking_style(**compat_payload))
        except TypeError:
            legacy_payload = dict(compat_payload)
            legacy_payload.pop("tab_border_size")
            legacy_payload.pop("tab_bar_border_size")
            legacy_payload.pop("dock_tab_inactive_separator_inset")
            return bool(apply_docking_style(**legacy_payload))


def _imgui_docking_style_payload(style: ImGuiSplitterStyle) -> dict[str, object]:
    return {
        "visual_width": style.visual_width,
        "hover_padding": style.hover_padding,
        "tab_close_min_width_selected": style.tab_close_min_width_selected,
        "tab_close_min_width_unselected": style.tab_close_min_width_unselected,
        "tab_bar_overline_size": style.tab_bar_overline_size,
        "tab_rounding": style.tab_rounding,
        "tab_height": style.tab_height,
        "tab_border_size": style.tab_border_size,
        "tab_bar_border_size": style.tab_bar_border_size,
        "dock_tab_inactive_separator_inset": style.dock_tab_inactive_separator_inset,
        "dock_tab_use_tab_colors": style.dock_tab_use_tab_colors,
        "dock_tab_single_tab_uses_selected_color": (
            style.dock_tab_single_tab_uses_selected_color
        ),
        "dock_tab_draw_inactive_separators": style.dock_tab_draw_inactive_separators,
        "tab_use_rectangular_shape": style.tab_use_rectangular_shape,
        "dock_tab_text_color": style.dock_tab_text_color,
        "splitter_handle_color": style.splitter_handle_color,
        "splitter_handle_hovered_color": style.splitter_handle_hovered_color,
        "dock_tab_hovered_color": style.dock_tab_hovered_color,
        "dock_tab_color": style.dock_tab_color,
        "dock_tab_selected_color": style.dock_tab_selected_color,
        "dock_tab_selected_overline_color": style.dock_tab_selected_overline_color,
        "dock_tab_dimmed_color": style.dock_tab_dimmed_color,
        "dock_tab_dimmed_selected_color": style.dock_tab_dimmed_selected_color,
        "dock_tab_dimmed_selected_overline_color": (
            style.dock_tab_dimmed_selected_overline_color
        ),
    }


def _read_imgui_splitter_style_for_tests() -> ImGuiSplitterStyle:
    """Return the resolved docking style payload that Python sends to omni.ui."""

    import omni.ui as ui
    from omni.ui import constant as fl

    dpi_scale = _resolve_dpi_scale(ui)
    visual_width = float(
        ui.FloatStore.find("splitter_visual_width") or fl.splitter_visual_width
    )
    hit_target = float(
        ui.FloatStore.find("splitter_hit_target") or fl.splitter_hit_target
    )
    hover_padding = max((hit_target - visual_width) * 0.5, 0.0)
    tab_close_width = _float_or_default(
        ui.FloatStore.find("dock_tab_close_min_width"),
        fl.dock_tab_close_min_width,
    )
    tab_close_width_selected = _float_or_default(
        ui.FloatStore.find("dock_tab_close_min_width_selected"),
        getattr(fl, "dock_tab_close_min_width_selected", tab_close_width),
    )
    tab_close_width_unselected = _float_or_default(
        ui.FloatStore.find("dock_tab_close_min_width_unselected"),
        getattr(fl, "dock_tab_close_min_width_unselected", tab_close_width),
    )
    tab_height = _float_or_default(
        ui.FloatStore.find("dock_tab_height"),
        fl.dock_tab_height,
    )
    tab_overline_size = _float_or_default(
        ui.FloatStore.find("dock_tab_overline_size"),
        fl.dock_tab_overline_size,
    )
    tab_rounding = _float_or_default(
        ui.FloatStore.find("dock_tab_rounding"),
        fl.dock_tab_rounding,
    )
    tab_border_size = _float_or_default(
        ui.FloatStore.find("dock_tab_border_size"),
        fl.dock_tab_border_size,
    )
    tab_bar_border_size = _float_or_default(
        ui.FloatStore.find("dock_tab_bar_border_size"),
        fl.dock_tab_bar_border_size,
    )
    inactive_separator_inset = _float_or_default(
        ui.FloatStore.find("dock_tab_inactive_separator_inset"),
        fl.dock_tab_inactive_separator_inset,
    )
    tab_close_min_width_selected = _scale_positive_float(
        tab_close_width_selected,
        dpi_scale,
    )
    tab_close_min_width_unselected = _scale_positive_float(
        tab_close_width_unselected,
        dpi_scale,
    )
    dock_tab_selected = ui.ColorStore.find("dock_tab_selected")

    return ImGuiSplitterStyle(
        visual_width=visual_width,
        hit_target=hit_target,
        hover_padding=hover_padding,
        splitter_handle_color=ui.ColorStore.find("splitter_handle"),
        splitter_handle_hovered_color=ui.ColorStore.find("splitter_handle_hovered"),
        tab_height=_scale_positive_float(tab_height, dpi_scale),
        tab_close_min_width_selected=tab_close_min_width_selected,
        tab_close_min_width_unselected=tab_close_min_width_unselected,
        tab_rounding=tab_rounding,
        tab_border_size=_scale_positive_float(tab_border_size, dpi_scale),
        tab_bar_border_size=_scale_positive_float(tab_bar_border_size, dpi_scale),
        tab_bar_overline_size=tab_overline_size,
        dock_tab_inactive_separator_inset=_scale_positive_float(
            inactive_separator_inset,
            dpi_scale,
        ),
        dock_tab_use_tab_colors=True,
        dock_tab_single_tab_uses_selected_color=True,
        dock_tab_draw_inactive_separators=True,
        tab_use_rectangular_shape=True,
        dock_tab_text_color=ui.ColorStore.find("dock_tab_text"),
        dock_tab_color=ui.ColorStore.find("dock_tab"),
        dock_tab_hovered_color=ui.ColorStore.find("dock_tab_hovered"),
        dock_tab_selected_color=dock_tab_selected,
        dock_tab_selected_overline_color=ui.ColorStore.find(
            "dock_tab_selected_overline"
        ),
        dock_tab_dimmed_color=ui.ColorStore.find("dock_tab_dimmed"),
        dock_tab_dimmed_selected_color=ui.ColorStore.find(
            "dock_tab_dimmed_selected"
        ),
        dock_tab_dimmed_selected_overline_color=ui.ColorStore.find(
            "dock_tab_dimmed_selected_overline"
        ),
        title_bg_color=dock_tab_selected,
        title_bg_active_color=dock_tab_selected,
        title_bg_collapsed_color=dock_tab_selected,
        dpi_scale=dpi_scale,
    )


def _resolve_dpi_scale(ui_module: object | None) -> float:
    """Return the public omni.ui DPI scale for logical docking style values."""

    scale = 1.0
    if ui_module is not None:
        try:
            scale = float(ui_module.Workspace.get_dpi_scale())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            scale = 1.0
    return scale if scale > 0.0 else 1.0


def _scale_positive_float(value: float, scale: float) -> float:
    """Scale positive logical-point values while preserving ImGui sentinels."""

    if value > 0.0:
        return value * scale
    return value


def _float_or_default(value: float | None, default: float) -> float:
    return float(default if value is None else value)
