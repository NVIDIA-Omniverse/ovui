/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#pragma once

#include "BindUtils.h"
#include "DocWidget.h"

#include <omni/ui/Length.h>
#include <omni/ui/Types.h>
#include <omni/ui/bind/Pybind.h>

#define OMNIUI_PYBIND_INIT_Widget                                                                                        \
    OMNIUI_PYBIND_INIT_STYLES                                                                                            \
    OMNIUI_PYBIND_INIT_CALL(width, setWidth, toLength)                                                                   \
    OMNIUI_PYBIND_INIT_CALL(height, setHeight, toLength)                                                                 \
    OMNIUI_PYBIND_INIT_CAST(name, setName, std::string)                                                                  \
    OMNIUI_PYBIND_INIT_CAST(style_type_name_override, setStyleTypeNameOverride, std::string)                             \
    OMNIUI_PYBIND_INIT_CAST(visible, setVisible, bool)                                                                   \
    OMNIUI_PYBIND_INIT_CAST(visible_min, setVisibleMin, float)                                                           \
    OMNIUI_PYBIND_INIT_CAST(visible_max, setVisibleMax, float)                                                           \
    OMNIUI_PYBIND_INIT_CAST(tooltip, setTooltip, std::string)                                                            \
    OMNIUI_PYBIND_INIT_CALLBACK(tooltip_fn, setTooltipFn, void())                                                        \
    OMNIUI_PYBIND_INIT_CAST(tooltip_offset_x, setTooltipOffsetX, float)                                                  \
    OMNIUI_PYBIND_INIT_CAST(tooltip_offset_y, setTooltipOffsetY, float)                                                  \
    OMNIUI_PYBIND_INIT_CAST(enabled, setEnabled, bool)                                                                   \
    OMNIUI_PYBIND_INIT_CAST(selected, setSelected, bool)                                                                 \
    OMNIUI_PYBIND_INIT_CAST(checked, setChecked, bool)                                                                   \
    OMNIUI_PYBIND_INIT_CAST(dragging, setDragging, bool)                                                                 \
    OMNIUI_PYBIND_INIT_CAST(opaque_for_mouse_events, setOpaqueForMouseEvents, bool)                                      \
    OMNIUI_PYBIND_INIT_CAST(explicit_hover, setExplicitHover, bool)                                                      \
    OMNIUI_PYBIND_INIT_CAST(skip_draw_when_clipped, setSkipDrawWhenClipped, bool)                                        \
    OMNIUI_PYBIND_INIT_CAST(scroll_only_window_hovered, setScrollOnlyWindowHovered, bool)                                \
    OMNIUI_PYBIND_INIT_CAST(identifier, setIdentifier, std::string)                                                      \
    OMNIUI_PYBIND_INIT_CALLBACK(                                                                                         \
        mouse_moved_fn, setMouseMovedFn, void(float, float, omni::ui::KeyboardModifierFlags, bool[3]))                \
    OMNIUI_PYBIND_INIT_CALLBACK(                                                                                         \
        mouse_pressed_fn, setMousePressedFn, void(float, float, int32_t, omni::ui::KeyboardModifierFlags))            \
    OMNIUI_PYBIND_INIT_CALLBACK(                                                                                         \
        mouse_released_fn, setMouseReleasedFn, void(float, float, int32_t, omni::ui::KeyboardModifierFlags))          \
    OMNIUI_PYBIND_INIT_CALLBACK(mouse_double_clicked_fn, setMouseDoubleClickedFn,                                        \
                                void(float, float, int32_t, omni::ui::KeyboardModifierFlags))                         \
    OMNIUI_PYBIND_INIT_CALLBACK(mouse_wheel_fn, setMouseWheelFn, void(float, float, omni::ui::KeyboardModifierFlags)) \
    OMNIUI_PYBIND_INIT_CALLBACK(mouse_hovered_fn, setMouseHoveredFn, void(bool))                                         \
    OMNIUI_PYBIND_INIT_CALLBACK(                                                                                         \
        key_pressed_fn, setKeyPressedFn, void(int32_t, omni::ui::KeyboardModifierFlags, bool))                        \
    OMNIUI_PYBIND_INIT_CALLBACK(drag_fn, setDragFn, std::string())                                                       \
    OMNIUI_PYBIND_INIT_CALLBACK(accept_drop_fn, setAcceptDropFn, bool(const std::string&))                               \
    OMNIUI_PYBIND_INIT_CALLBACK(drop_fn, setDropFn, void(const Widget::MouseDropEvent&))                                 \
    OMNIUI_PYBIND_INIT_CALLBACK(computed_content_size_changed_fn, setComputedContentSizeChangedFn, void())               \
    OMNIUI_PYBIND_INIT_CALLBACK(checked_changed_fn, setCheckedChangedFn, void(bool))

// clang-format off
#define OMNIUI_PYBIND_KWARGS_DOC_Widget                                                                                \
    "\n    `width : ui.Length`\n        "                                                                              \
    OMNIUI_PYBIND_DOC_Widget_width                                                                                     \
    "\n    `height : ui.Length`\n        "                                                                             \
    OMNIUI_PYBIND_DOC_Widget_height                                                                                    \
    "\n    `name : str`\n        "                                                                                     \
    OMNIUI_PYBIND_DOC_Widget_name                                                                                      \
    "\n    `style_type_name_override : str`\n        "                                                                 \
    OMNIUI_PYBIND_DOC_Widget_styleTypeNameOverride                                                                     \
     "\n    `identifier : str`\n        "                                                                              \
    OMNIUI_PYBIND_DOC_Widget_identifier                                                                                \
    "\n    `visible : bool`\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Widget_visible                                                                                   \
    "\n    `visibleMin : float`\n        "                                                                             \
    OMNIUI_PYBIND_DOC_Widget_visibleMin                                                                                \
    "\n    `visibleMax : float`\n        "                                                                             \
    OMNIUI_PYBIND_DOC_Widget_visibleMax                                                                                \
    "\n    `tooltip : str`\n        "                                                                                  \
    OMNIUI_PYBIND_DOC_Widget_tooltip                                                                                   \
    "\n    `tooltip_fn : Callable`\n        "                                                                          \
    OMNIUI_PYBIND_DOC_Widget_Tooltip                                                                                   \
    "\n    `tooltip_offset_x : float`\n        "                                                                       \
    OMNIUI_PYBIND_DOC_Widget_tooltipOffsetX                                                                            \
    "\n    `tooltip_offset_y : float`\n        "                                                                       \
    OMNIUI_PYBIND_DOC_Widget_tooltipOffsetY                                                                            \
    "\n    `enabled : bool`\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Widget_enabled                                                                                   \
    "\n    `selected : bool`\n        "                                                                                \
    OMNIUI_PYBIND_DOC_Widget_selected                                                                                  \
    "\n    `checked : bool`\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Widget_checked                                                                                   \
    "\n    `dragging : bool`\n        "                                                                                \
    OMNIUI_PYBIND_DOC_Widget_dragging                                                                                  \
    "\n    `opaque_for_mouse_events : bool`\n        "                                                                 \
    OMNIUI_PYBIND_DOC_Widget_opaqueForMouseEvents                                                                      \
    "\n    `explicit_hover : bool`\n        "                                                                          \
    OMNIUI_PYBIND_DOC_Widget_explicitHover                                                                             \
    "\n    `skip_draw_when_clipped : bool`\n        "                                                                  \
    OMNIUI_PYBIND_DOC_Widget_skipDrawWhenClipped                                                                       \
    "\n    `mouse_moved_fn : Callable`\n        "                                                                      \
    OMNIUI_PYBIND_DOC_Widget_MouseMoved                                                                                \
    "\n    `mouse_pressed_fn : Callable`\n        "                                                                    \
    OMNIUI_PYBIND_DOC_Widget_MousePressed                                                                              \
    "\n    `mouse_released_fn : Callable`\n        "                                                                   \
    OMNIUI_PYBIND_DOC_Widget_MouseReleased                                                                             \
    "\n    `mouse_double_clicked_fn : Callable`\n        "                                                             \
    OMNIUI_PYBIND_DOC_Widget_MouseDoubleClicked                                                                        \
    "\n    `mouse_wheel_fn : Callable`\n        "                                                                      \
    OMNIUI_PYBIND_DOC_Widget_MouseWheel                                                                                \
    "\n    `mouse_hovered_fn : Callable`\n        "                                                                    \
    OMNIUI_PYBIND_DOC_Widget_MouseHovered                                                                              \
    "\n    `drag_fn : Callable`\n        "                                                                             \
    OMNIUI_PYBIND_DOC_Widget_Drag                                                                                      \
    "\n    `accept_drop_fn : Callable`\n        "                                                                      \
    OMNIUI_PYBIND_DOC_Widget_AcceptDrop                                                                                \
    "\n    `drop_fn : Callable`\n        "                                                                             \
    OMNIUI_PYBIND_DOC_Widget_Drop                                                                                      \
    "\n    `computed_content_size_changed_fn : Callable`\n        "                                                    \
    OMNIUI_PYBIND_DOC_Widget_ComputedContentSizeChanged                                                                \
// clang-format on

OMNIUI_NAMESPACE_OPEN_SCOPE

inline Length toLength(pybind11::handle obj)
{
    using namespace pybind11;

    // Implicitly cast numbers into Pixel Length values:
    if (isinstance<int_>(obj) || isinstance<float_>(obj))
    {
        return Pixel(obj.cast<float>());
    }
    return obj.cast<Length>();
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
