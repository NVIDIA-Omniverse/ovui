/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
#include "BindWidget.h"
#include "DocComboBox.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_ComboBox                                                                                    \
    OMNIUI_PYBIND_INIT_Widget                                                                                          \
    OMNIUI_PYBIND_INIT_CAST(arrow_only, setArrowOnly, bool)                                                            \
    OMNIUI_PYBIND_INIT_CAST(no_arrow_button, setNoArrowButton, bool)
#define OMNIUI_PYBIND_KWARGS_DOC_ComboBox                                                                              \
    "\n    `arrow_only : bool`\n        "                                                                              \
    OMNIUI_PYBIND_DOC_ComboBox_arrowOnly                                                                               \
    "\n    `no_arrow_button : bool`\n        "                                                                         \
    OMNIUI_PYBIND_DOC_ComboBox_noArrowButton                                                                           \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
