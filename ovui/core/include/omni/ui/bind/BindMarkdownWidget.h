/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindUtils.h"
#include "BindWidget.h"
#include "DocMarkdownWidget.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_MarkdownWidget                                                                              \
    OMNIUI_PYBIND_INIT_Widget

#define OMNIUI_PYBIND_KWARGS_DOC_MarkdownWidget                                                                        \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
