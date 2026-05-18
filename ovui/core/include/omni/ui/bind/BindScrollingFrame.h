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

#include "BindFrame.h"
#include "BindUtils.h"
#include "DocScrollingFrame.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_ScrollingFrame                                                                              \
    OMNIUI_PYBIND_INIT_Frame                                                                                           \
    OMNIUI_PYBIND_INIT_CAST(scroll_x, setScrollX, float)                                                               \
    OMNIUI_PYBIND_INIT_CALLBACK(scroll_x_changed_fn, setScrollXChangedFn, void(float))                                 \
    OMNIUI_PYBIND_INIT_CAST(scroll_y, setScrollY, float)                                                               \
    OMNIUI_PYBIND_INIT_CALLBACK(scroll_y_changed_fn, setScrollYChangedFn, void(float))                                 \
    OMNIUI_PYBIND_INIT_CAST(horizontal_scrollbar_policy, setHorizontalScrollBarPolicy, ScrollBarPolicy)                \
    OMNIUI_PYBIND_INIT_CAST(vertical_scrollbar_policy, setVerticalScrollBarPolicy, ScrollBarPolicy)
#define OMNIUI_PYBIND_KWARGS_DOC_ScrollingFrame                                                                        \
    "\n    `scroll_x : float`\n        "                                                                               \
    OMNIUI_PYBIND_DOC_ScrollingFrame_scrollX                                                                           \
    "\n    `scroll_x_max : float`\n        "                                                                           \
    OMNIUI_PYBIND_DOC_ScrollingFrame_scrollXMax                                                                        \
    "\n    `scroll_x_changed_fn : Callable[[float], None]`\n        "                                                  \
    OMNIUI_PYBIND_DOC_ScrollingFrame_scrollX                                                                           \
    "\n    `scroll_y : float`\n        "                                                                               \
    OMNIUI_PYBIND_DOC_ScrollingFrame_scrollY                                                                           \
    "\n    `scroll_y_max : float`\n        "                                                                           \
    OMNIUI_PYBIND_DOC_ScrollingFrame_scrollYMax                                                                        \
    "\n    `scroll_y_changed_fn : Callable[[float], None]`\n        "                                                  \
    OMNIUI_PYBIND_DOC_ScrollingFrame_scrollY                                                                           \
    "\n    `horizontal_scrollbar_policy : ui.ScrollBarPolicy`\n        "                                               \
    OMNIUI_PYBIND_DOC_ScrollingFrame_horizontalScrollBarPolicy                                                         \
    "\n    `vertical_scrollbar_policy : ui.ScrollBarPolicy`\n        "                                                 \
    OMNIUI_PYBIND_DOC_ScrollingFrame_verticalScrollBarPolicy                                                           \
    OMNIUI_PYBIND_KWARGS_DOC_Frame
// clang-format on
