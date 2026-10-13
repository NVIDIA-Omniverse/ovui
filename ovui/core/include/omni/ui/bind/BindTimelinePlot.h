/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindUtils.h"
#include "BindWidget.h"
#include "DocTimelinePlot.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_TimelinePlot                                                                                \
    OMNIUI_PYBIND_INIT_Widget                                                                                          \
    OMNIUI_PYBIND_INIT_CAST(lane_height, setLaneHeight, float)

#define OMNIUI_PYBIND_KWARGS_DOC_TimelinePlot                                                                          \
    "\n    `lane_height : float`\n        " OMNIUI_PYBIND_DOC_TimelinePlot_laneHeight                                      \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
