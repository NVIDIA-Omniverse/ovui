/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#define OMNIUI_PYBIND_DOC_Shape                                                                                                                                                                                      \
    "The Shape widget provides a base class for all the Shape Widget. Currently implemented are Rectangle, Circle, Triangle, Line, Ellipse and BezierCurve.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_Shape_backgroundColorProperty                                                                \
    "Determines which style entry the shape should use for the background. It's very useful when we need to use a custom color. For example, when we draw the triangle for a collapsable frame, we use \"color\" instead of \"background_color\".\n"


#define OMNIUI_PYBIND_DOC_Shape_borderColorProperty                                                                    \
    "Determines which style entry the shape should use for the border color.\n"


#define OMNIUI_PYBIND_DOC_Shape__intersects                                                                            \
    "Segment-circle intersection. Follows closely\n"                                                                   \
    "https://stackoverflow.com/questions/1073336/circle-line-segment-collision-detection-algorithm\n"                  \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `p1 :`\n"                                                                                                     \
    "        start of line\n"                                                                                          \
    "\n"                                                                                                               \
    "    `p2 :`\n"                                                                                                     \
    "        end of line\n"                                                                                            \
    "\n"                                                                                                               \
    "    `center :`\n"                                                                                                 \
    "        center of circle\n"                                                                                       \
    "\n"                                                                                                               \
    "    `r :`\n"                                                                                                      \
    "        radius\n"                                                                                                 \
    "true intersects\n"                                                                                                \
    "false doesn't intersect\n"
