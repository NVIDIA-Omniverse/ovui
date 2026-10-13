/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
