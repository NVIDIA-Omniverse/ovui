/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindShape.h"
#include "BindUtils.h"
#include "DocArrowHelper.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_ArrowHelper                                                                                       \
    OMNIUI_PYBIND_INIT_CAST(begin_arrow_width, setBeginArrowWidth, float)                                              \
    OMNIUI_PYBIND_INIT_CAST(begin_arrow_height, setBeginArrowHeight, float)                                            \
    OMNIUI_PYBIND_INIT_CAST(begin_arrow_type, setBeginArrowType, ArrowHelper::ArrowType)                                     \
    OMNIUI_PYBIND_INIT_CAST(end_arrow_width, setEndArrowWidth, float)                                                  \
    OMNIUI_PYBIND_INIT_CAST(end_arrow_height, setEndArrowHeight, float)                                                \
    OMNIUI_PYBIND_INIT_CAST(end_arrow_type, setEndArrowType, ArrowHelper::ArrowType)                                 

#define OMNIUI_PYBIND_KWARGS_DOC_ArrowHelper                                                                                  \
    "\n    `arrow : `\n        "                                                                                        \
    OMNIUI_PYBIND_DOC_ArrowHelper_beginArrowWidth                                                                             \
    OMNIUI_PYBIND_DOC_ArrowHelper_beginArrowHeight                                                                            \
    OMNIUI_PYBIND_DOC_ArrowHelper_beginArrowType                                                                              \
    OMNIUI_PYBIND_DOC_ArrowHelper_endArrowWidth                                                                               \
    OMNIUI_PYBIND_DOC_ArrowHelper_endArrowHeight                                                                              \
    OMNIUI_PYBIND_DOC_ArrowHelper_endArrowType
// clang-format on
