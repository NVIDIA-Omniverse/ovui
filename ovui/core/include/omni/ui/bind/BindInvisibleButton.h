/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindWidget.h"
#include "DocInvisibleButton.h"

#define OMNIUI_PYBIND_INIT_InvisibleButton                                                                             \
    OMNIUI_PYBIND_INIT_Widget OMNIUI_PYBIND_INIT_CALLBACK(clicked_fn, setClickedFn, void())
// clang-format off
#define OMNIUI_PYBIND_KWARGS_DOC_InvisibleButton                                                                       \
    "\n    `clicked_fn : Callable[[], None]`\n        "                                                                \
    OMNIUI_PYBIND_DOC_InvisibleButton_Clicked                                                                          \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
