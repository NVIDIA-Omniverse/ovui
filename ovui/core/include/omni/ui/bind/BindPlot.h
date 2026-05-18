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
#include "BindWidget.h"
#include "DocPlot.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_Plot                                                                                        \
    OMNIUI_PYBIND_INIT_Widget                                                                                          \
    OMNIUI_PYBIND_INIT_CAST(value_offset, setValueOffset, int)                                                         \
    OMNIUI_PYBIND_INIT_CAST(value_stride, setValueStride, int)                                                         \
    OMNIUI_PYBIND_INIT_CAST(title, setTitle, std::string)

#define OMNIUI_PYBIND_KWARGS_DOC_Plot                                                                                  \
    "\n    `value_offset : int`\n        "                                                                             \
    OMNIUI_PYBIND_DOC_Plot_valueOffset                                                                                 \
    "\n    `value_stride : int`\n        "                                                                             \
    OMNIUI_PYBIND_DOC_Plot_valueStride                                                                                 \
    "\n    `title : str`\n        "                                                                                    \
    OMNIUI_PYBIND_DOC_Plot_title                                                                                       \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
