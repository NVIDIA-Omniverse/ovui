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

#include "BindStack.h"
#include "DocGrid.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_Grid                                                                                        \
    OMNIUI_PYBIND_INIT_Stack                                                                                           \
    OMNIUI_PYBIND_INIT_CAST(column_width, setColumnWidth, float)                                                       \
    OMNIUI_PYBIND_INIT_CAST(row_height, setRowHeight, float)                                                           \
    OMNIUI_PYBIND_INIT_CAST(column_count, setColumnCount, uint32_t)                                                    \
    OMNIUI_PYBIND_INIT_CAST(row_count, setRowCount, uint32_t)                                                          \

#define OMNIUI_PYBIND_KWARGS_DOC_Grid                                                                                  \
    "\n    `column_width : `\n        "                                                                                \
    OMNIUI_PYBIND_DOC_Grid_columnWidth                                                                                 \
    "\n    `row_height : `\n        "                                                                                  \
    OMNIUI_PYBIND_DOC_Grid_rowHeight                                                                                   \
    "\n    `column_count : `\n        "                                                                                \
    OMNIUI_PYBIND_DOC_Grid_columnCount                                                                                 \
    "\n    `row_count : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Grid_rowCount                                                                                    \
    OMNIUI_PYBIND_KWARGS_DOC_Stack
// clang-format on
