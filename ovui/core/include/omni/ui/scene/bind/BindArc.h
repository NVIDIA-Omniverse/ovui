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
#include "DocArc.h"

// clang-format off

#define OMNIUI_PYBIND_INIT_Arc                                                                                         \
    OMNIUI_PYBIND_INIT_AbstractShape                                                                                   \
    OMNIUI_PYBIND_INIT_CAST(begin, setBegin, Float)                                                                    \
    OMNIUI_PYBIND_INIT_CAST(end, setEnd, Float)                                                                        \
    OMNIUI_PYBIND_INIT_CAST(thickness, setThickness, float)                                                            \
    OMNIUI_PYBIND_INIT_CAST(intersection_thickness, setIntersectionThickness, float)                                   \
    OMNIUI_PYBIND_INIT_CALL(color, setColor, pythonToColor4)                                                           \
    OMNIUI_PYBIND_INIT_CAST(tesselation, setTesselation, uint16_t)                                                     \
    OMNIUI_PYBIND_INIT_CAST(axis, setAxis, uint8_t)                                                                    \
    OMNIUI_PYBIND_INIT_CAST(sector, setSector, bool)                                                                   \
    OMNIUI_PYBIND_INIT_CAST(culling, setCulling, Culling)                                                              \
    OMNIUI_PYBIND_INIT_CAST(wireframe, setWireframe, bool)

#define OMNIUI_PYBIND_KWARGS_DOC_Arc                                                                                   \
    "\n    `begin : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_Arc_begin                                                                                        \
    "\n    `end : `\n        "                                                                                         \
    OMNIUI_PYBIND_DOC_Arc_end                                                                                          \
    "\n    `thickness : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Arc_thickness                                                                                    \
    "\n    `intersection_thickness : `\n        "                                                                      \
    OMNIUI_PYBIND_DOC_Arc_intersectionThickness                                                                        \
    "\n    `color : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_Arc_color                                                                                        \
    "\n    `tesselation : `\n        "                                                                                 \
    OMNIUI_PYBIND_DOC_Arc_tesselation                                                                                  \
    "\n    `axis : `\n        "                                                                                        \
    OMNIUI_PYBIND_DOC_Arc_axis                                                                                         \
    "\n    `sector : `\n        "                                                                                      \
    OMNIUI_PYBIND_DOC_Arc_sector                                                                                       \
    "\n    `culling : `\n        "                                                                                     \
    OMNIUI_PYBIND_DOC_Arc_culling                                                                                      \
    "\n    `wireframe : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_Arc_wireframe                                                                                    \
    OMNIUI_PYBIND_KWARGS_DOC_AbstractShape

// clang-format on
