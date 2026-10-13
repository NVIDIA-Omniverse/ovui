/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindShape.h"
#include "BindUtils.h"
#include "DocTriangle.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_Triangle                                                                                    \
    OMNIUI_PYBIND_INIT_Shape                                                                                           \
    OMNIUI_PYBIND_INIT_CAST(alignment, setAlignment, Alignment)                                                        \

#define OMNIUI_PYBIND_KWARGS_DOC_Triangle                                                                              \
    "\n    `alignment : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Triangle_alignment                                                                               \
    OMNIUI_PYBIND_KWARGS_DOC_Shape
// clang-format on
