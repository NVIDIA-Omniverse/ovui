/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindArrowHelper.h"
#include "BindShapeAnchorHelper.h"
#include "BindShape.h"
#include "BindUtils.h"
#include "DocLine.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_Line                                                                                        \
    OMNIUI_PYBIND_INIT_Shape                                                                                           \
    OMNIUI_PYBIND_INIT_ArrowHelper                                                                                     \
    OMNIUI_PYBIND_INIT_CAST(alignment, setAlignment, Alignment)                                                        \
    OMNIUI_PYBIND_INIT_ShapeAnchorHelper

#define OMNIUI_PYBIND_KWARGS_DOC_Line                                                                                  \
    "\n    `alignment : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Line_alignment                                                                                   \
    OMNIUI_PYBIND_KWARGS_DOC_Shape                                                                                     \
    OMNIUI_PYBIND_KWARGS_DOC_ShapeAnchorHelper
// clang-format on
