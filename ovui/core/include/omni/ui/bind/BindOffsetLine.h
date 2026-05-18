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

#include "BindFreeShape.h"
#include "BindUtils.h"
#include "DocOffsetLine.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_OffsetLine                                                                                  \
    OMNIUI_PYBIND_INIT_FreeLine                                                                                        \
    OMNIUI_PYBIND_INIT_CAST(offset, setOffset, float)                                                                  \
    OMNIUI_PYBIND_INIT_CAST(bound_offset, setBoundOffset, float)
#define OMNIUI_PYBIND_KWARGS_DOC_OffsetLine                                                                            \
    "\n    `offset : `\n        "                                                                                      \
    OMNIUI_PYBIND_DOC_OffsetLine_offset                                                                                \
    "\n    `bound_offset : `\n        "                                                                                \
    OMNIUI_PYBIND_DOC_OffsetLine_boundOffset                                                                           \
 OMNIUI_PYBIND_KWARGS_DOC_FreeLine
// clang-format on
