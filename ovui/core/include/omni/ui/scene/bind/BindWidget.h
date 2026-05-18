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

#include "BindRectangle.h"
#include "DocWidget.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_Widget                                                                                      \
    OMNIUI_PYBIND_INIT_Rectangle                                                                                       \
    OMNIUI_PYBIND_INIT_CAST(fill_policy, setFillPolicy, Widget::FillPolicy)                                            \
    OMNIUI_PYBIND_INIT_CAST(update_policy, setUpdatePolicy, Widget::UpdatePolicy)                                      \
    OMNIUI_PYBIND_INIT_CAST(resolution_scale, setResolutionScale, float)                                               \
    OMNIUI_PYBIND_INIT_CAST(resolution_width, setResolutionWidth, uint32_t)                                            \
    OMNIUI_PYBIND_INIT_CAST(resolution_height, setResolutionHeight, uint32_t)

#define OMNIUI_PYBIND_KWARGS_DOC_Widget                                                                                \
    "\n    `fill_policy : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Widget_fillPolicy                                                                                \
    "\n    `update_policy : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_Widget_updatePolicy                                                                              \
    "\n    `resolution_scale : `\n        "                                                                            \
    OMNIUI_PYBIND_DOC_Widget_resolutionScale                                                                           \
    "\n    `resolution_width : `\n        "                                                                            \
    OMNIUI_PYBIND_DOC_Widget_resolutionWidth                                                                           \
    "\n    `resolution_height : `\n        "                                                                           \
    OMNIUI_PYBIND_DOC_Widget_resolutionHeight                                                                          \
    OMNIUI_PYBIND_KWARGS_DOC_Rectangle

// clang-format on
