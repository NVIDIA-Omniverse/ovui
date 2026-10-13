/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindAbstractShape.h"
#include "DocCurve.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_Curve                                                                                       \
    OMNIUI_PYBIND_INIT_AbstractShape                                                                                   \
    OMNIUI_PYBIND_INIT_CALL(positions, setPositions, pythonListToVector3)                                              \
    OMNIUI_PYBIND_INIT_CALL(colors, setColors, pythonListToVector4)                                                    \
    OMNIUI_PYBIND_INIT_CAST(thicknesses, setThicknesses, std::vector<float>)                                           \
    OMNIUI_PYBIND_INIT_CAST(vertex_counts, setVertexCounts, std::vector<uint32_t>)                                     \
    OMNIUI_PYBIND_INIT_CAST(intersection_thickness, setIntersectionThickness, float)                                   \
    OMNIUI_PYBIND_INIT_CAST(curve_type, setCurveType, Curve::CurveType)                                                \
    OMNIUI_PYBIND_INIT_CAST(tessellation, setTessellation, uint16_t)

#define OMNIUI_PYBIND_KWARGS_DOC_Curve                                                                                 \
    "\n    `positions : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Curve_positions                                                                                  \
    "\n    `colors : `\n        "                                                                                      \
    OMNIUI_PYBIND_DOC_Curve_colors                                                                                     \
    "\n    `thicknesses : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Curve_thicknesses                                                                                \
    "\n    `vertex_counts : `\n        Optional independent linear-polyline counts; empty preserves a single curve." \
    "\n    `intersection_thickness : `\n        "                                                                      \
    OMNIUI_PYBIND_DOC_Curve_intersectionThickness                                                                      \
    "\n    `curve_type : `\n        "                                                                                  \
    OMNIUI_PYBIND_DOC_Curve_curveType                                                                                  \
    "\n    `tessellation : `\n        "                                                                                \
    OMNIUI_PYBIND_DOC_Curve_tessellation                                                                               \
    OMNIUI_PYBIND_KWARGS_DOC_AbstractShape

// clang-format on
