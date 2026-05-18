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

#include "BindAbstractShape.h"
#include "DocLine.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_Line                                                                                        \
    OMNIUI_PYBIND_INIT_AbstractShape                                                                                   \
    OMNIUI_PYBIND_INIT_CALL(start, setStart, pythonToVector3)                                                          \
    OMNIUI_PYBIND_INIT_CALL(end, setEnd, pythonToVector3)                                                              \
    OMNIUI_PYBIND_INIT_CALL(color, setColor, pythonToColor4)                                                           \
    OMNIUI_PYBIND_INIT_CAST(thickness, setThickness, float)                                                            \
    OMNIUI_PYBIND_INIT_CAST(intersection_thickness, setIntersectionThickness, float)

#define OMNIUI_PYBIND_KWARGS_DOC_Line                                                                                  \
    "\n    `start : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_Line_start                                                                                       \
    "\n    `end : `\n        "                                                                                         \
    OMNIUI_PYBIND_DOC_Line_end                                                                                         \
    "\n    `color : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_Line_color                                                                                       \
    "\n    `thickness : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Line_thickness                                                                                   \
    "\n    `intersection_thickness : `\n        "                                                                      \
    OMNIUI_PYBIND_DOC_Line_intersectionThickness                                                                       \
    OMNIUI_PYBIND_KWARGS_DOC_AbstractShape

// clang-format on
