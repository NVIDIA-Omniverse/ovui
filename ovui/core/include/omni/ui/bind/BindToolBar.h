/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindUtils.h"
#include "BindWindow.h"
#include "DocToolBar.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_ToolBar                                                                                     \
    OMNIUI_PYBIND_INIT_Window                                                                                          \
    OMNIUI_PYBIND_INIT_CAST(axis, setAxis, ToolBar::Axis)                                                              \
    OMNIUI_PYBIND_INIT_CALLBACK(axis_changed_fn, setAxisChangedFn, void(ToolBar::Axis))

#define OMNIUI_PYBIND_KWARGS_DOC_ToolBar                                                                               \
    "\n    `axis : ui.Axis`\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_ToolBar_axis                                                                                     \
    "\n    `axis_changed_fn : Callable[[ui.Axis], None]`\n        "                                                    \
    OMNIUI_PYBIND_DOC_ToolBar_axis                                                                                     \
    OMNIUI_PYBIND_KWARGS_DOC_Window
// clang-format on
