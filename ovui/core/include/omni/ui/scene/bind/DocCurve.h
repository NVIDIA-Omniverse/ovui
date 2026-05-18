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

#define OMNIUI_PYBIND_DOC_Curve                                                                                        \
    "Represents the curve.\n"                                                                                          \
    "\n"


#define OMNIUI_PYBIND_DOC_Curve_getGesturePayload "Contains all the information about the intersection.\n"


#define OMNIUI_PYBIND_DOC_Curve_getGesturePayload01                                                                    \
    "Contains all the information about the intersection at the specific state.\n"


#define OMNIUI_PYBIND_DOC_Curve_getIntersectionDistance                                                                \
    "The distance in pixels from mouse pointer to the shape for the intersection.\n"


#define OMNIUI_PYBIND_DOC_Curve_positions                                                                              \
    "The list of positions which defines the curve. It has at least two positions. The curve has len(positions)-1\n"


#define OMNIUI_PYBIND_DOC_Curve_colors                                                                                 \
    "The list of colors which defines color per vertex. It has the same length as positions.\n"


#define OMNIUI_PYBIND_DOC_Curve_thicknesses                                                                            \
    "The list of thicknesses which defines thickness per vertex. It has the same length as positions.\n"


#define OMNIUI_PYBIND_DOC_Curve_intersectionThickness "The thickness of the line for the intersection.\n"


#define OMNIUI_PYBIND_DOC_Curve_curveType "The curve interpolation type.\n"


#define OMNIUI_PYBIND_DOC_Curve_tessellation "The number of points per curve segment. It can't be less than 2.\n"


#define OMNIUI_PYBIND_DOC_Curve_Curve                                                                                  \
    "Constructs Curve.\n"                                                                                              \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `positions :`\n"                                                                                              \
    "        List of positions\n"
