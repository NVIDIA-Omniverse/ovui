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
#include "DocWindow.h"

#include <omni/ui/bind/Pybind.h>

#define OMNIUI_PYBIND_INIT_Window                                                                                      \
    OMNIUI_PYBIND_INIT_CAST(flags, setFlags, Window::Flags)                                                            \
    OMNIUI_PYBIND_INIT_CAST(visible, setVisible, bool)                                                                 \
    OMNIUI_PYBIND_INIT_CAST(title, setTitle, std::string)                                                              \
    OMNIUI_PYBIND_INIT_CAST(padding_x, setPaddingX, float)                                                             \
    OMNIUI_PYBIND_INIT_CAST(padding_y, setPaddingY, float)                                                             \
    OMNIUI_PYBIND_INIT_CAST(width, setWidth, float)                                                                    \
    OMNIUI_PYBIND_INIT_CAST(height, setHeight, float)                                                                  \
    OMNIUI_PYBIND_INIT_CAST(position_x, setPositionX, float)                                                           \
    OMNIUI_PYBIND_INIT_CAST(position_y, setPositionY, float)                                                           \
    OMNIUI_PYBIND_INIT_CAST(auto_resize, setAutoResize, bool)                                                          \
    OMNIUI_PYBIND_INIT_CAST(noTabBar, setNoTabBar, bool)                                                               \
    OMNIUI_PYBIND_INIT_CAST(tabBarTooltip, setTabBarTooltip, std::string)                                              \
    OMNIUI_PYBIND_INIT_CAST(exclusive_keyboard, setExclusiveKeyboard, bool)                                            \
    OMNIUI_PYBIND_INIT_CAST(detachable, setDetachable, bool)                                                           \
    OMNIUI_PYBIND_INIT_CAST(raster_policy, setRasterPolicy, RasterPolicy)                                              \
    OMNIUI_PYBIND_INIT_CAST(fill_app_window, setFillAppWindow, bool)                                                   \
    OMNIUI_PYBIND_INIT_CALLBACK(width_changed_fn, setWidthChangedFn, void(const float&))                               \
    OMNIUI_PYBIND_INIT_CALLBACK(height_changed_fn, setHeightChangedFn, void(const float&))                             \
    OMNIUI_PYBIND_INIT_CALLBACK(visibility_changed_fn, setVisibilityChangedFn, void(bool))

// clang-format off
#define OMNIUI_PYBIND_KWARGS_DOC_Window                                                                                \
    "\n    `flags : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_Window_flags                                                                                     \
    "\n    `visible : `\n        "                                                                                     \
    OMNIUI_PYBIND_DOC_Window_visible                                                                                   \
    "\n    `title : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_Window_title                                                                                     \
    "\n    `padding_x : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Window_paddingX                                                                                  \
    "\n    `padding_y : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Window_paddingY                                                                                  \
    "\n    `width : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_Window_width                                                                                     \
    "\n    `height : `\n        "                                                                                      \
    OMNIUI_PYBIND_DOC_Window_heigh                                                                                     \
    "\n    `position_x : `\n        "                                                                                  \
    OMNIUI_PYBIND_DOC_Window_positionX                                                                                 \
    "\n    `position_y : `\n        "                                                                                  \
    OMNIUI_PYBIND_DOC_Window_positionY                                                                                 \
    "\n    `auto_resize : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Window_autoResize                                                                                \
    "\n    `noTabBar : `\n        "                                                                                    \
    OMNIUI_PYBIND_DOC_Window_noTabBar                                                                                  \
    "\n    `tabBarTooltip : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_Window_tabBarTooltip                                                                             \
    "\n    `raster_policy : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_Window_getRasterPolicy                                                                           \
    "\n    `fill_app_window : `\n        "                                                                             \
    OMNIUI_PYBIND_DOC_Window_fillAppWindow                                                                             \
    "\n    `width_changed_fn : `\n        "                                                                            \
    OMNIUI_PYBIND_DOC_Window_width                                                                                     \
    "\n    `height_changed_fn : `\n        "                                                                           \
    OMNIUI_PYBIND_DOC_Window_heigh                                                                                     \
    "\n    `visibility_changed_fn : `\n        "                                                                       \
    OMNIUI_PYBIND_DOC_Window_visible
// clang-format on
