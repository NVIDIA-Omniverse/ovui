/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindMenuHelper.h"
#include "BindUtils.h"
#include "BindWidget.h"
#include "DocMenuItem.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_MenuItem                                                                                    \
    OMNIUI_PYBIND_INIT_MenuHelper                                                                                      \
    OMNIUI_PYBIND_INIT_Widget

#define OMNIUI_PYBIND_KWARGS_DOC_MenuItem                                                                              \
    OMNIUI_PYBIND_KWARGS_DOC_MenuHelper                                                                                \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
