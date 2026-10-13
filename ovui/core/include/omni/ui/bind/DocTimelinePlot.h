/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_TimelinePlot                                                                                \
    "A batched native timeline for process-relative duration samples.\n"

#define OMNIUI_PYBIND_DOC_TimelinePlot_TimelinePlot "Construct an empty timeline plot.\n"
#define OMNIUI_PYBIND_DOC_TimelinePlot_laneHeight "Height of one group or metric lane in logical pixels.\n"
#define OMNIUI_PYBIND_DOC_TimelinePlot_setData                                                                       \
    "Replace labels, group separator rows, and `(lane, start_seconds, duration_ms, color_index)` intervals.\n"
#define OMNIUI_PYBIND_DOC_TimelinePlot_setTimeRange "Set the visible process-relative range in seconds.\n"
