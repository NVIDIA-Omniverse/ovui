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
#include "DocAbstractMultiField.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_AbstractMultiField                                                                          \
    OMNIUI_PYBIND_INIT_Widget                                                                                          \
    OMNIUI_PYBIND_INIT_CAST(column_count, setColumnCount, uint8_t)                                                     \
    OMNIUI_PYBIND_INIT_CAST(h_spacing, setHSpacing, float)                                                             \
    OMNIUI_PYBIND_INIT_CAST(v_spacing, setVSpacing, float)

#define OMNIUI_PYBIND_KWARGS_DOC_AbstractMultiField                                                                    \
    "\n    `column_count : `\n        "                                                                                \
    OMNIUI_PYBIND_DOC_AbstractMultiField_columnCount                                                                   \
    "\n    `h_spacing : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_AbstractMultiField_hSpacing                                                                      \
    "\n    `v_spacing : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_AbstractMultiField_vSpacing                                                                      \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
