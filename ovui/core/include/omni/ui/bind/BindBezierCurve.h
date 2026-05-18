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

#include "BindArrowHelper.h"
#include "BindShapeAnchorHelper.h"
#include "BindShape.h"
#include "BindUtils.h"
#include "DocBezierCurve.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_BezierCurve                                                                                 \
    OMNIUI_PYBIND_INIT_CALL(start_tangent_width, setStartTangentWidth, toLength)                                       \
    OMNIUI_PYBIND_INIT_CALL(start_tangent_height, setStartTangentHeight, toLength)                                     \
    OMNIUI_PYBIND_INIT_CALL(end_tangent_width, setEndTangentWidth, toLength)                                           \
    OMNIUI_PYBIND_INIT_CALL(end_tangent_height, setEndTangentHeight, toLength)                                         \
    OMNIUI_PYBIND_INIT_CALLBACK(mouse_hovered_fn, setMouseHoveredFn, void(bool))                                       \
    OMNIUI_PYBIND_INIT_Shape                                                                                           \
    OMNIUI_PYBIND_INIT_ArrowHelper                                                                                     \
    OMNIUI_PYBIND_INIT_ShapeAnchorHelper

#define OMNIUI_PYBIND_KWARGS_DOC_BezierCurve                                                                           \
    "\n`start_tangent_width: `    \n"                                                                                  \
    OMNIUI_PYBIND_DOC_BezierCurve_startTangentWidth                                                                    \
    "\n`start_tangent_height: `    \n"                                                                                 \
    OMNIUI_PYBIND_DOC_BezierCurve_startTangentHeight                                                                   \
    "\n`end_tangent_width: `    \n"                                                                                    \
    OMNIUI_PYBIND_DOC_BezierCurve_endTangentWidth                                                                      \
    "\n`end_tangent_height: `    \n"                                                                                   \
    OMNIUI_PYBIND_DOC_BezierCurve_endTangentHeight                                                                     \
    "\n`set_mouse_hovered_fn: `    \n"                                                                                 \
    OMNIUI_PYBIND_DOC_BezierCurve_setMouseHoveredFn                                                                    \
    OMNIUI_PYBIND_KWARGS_DOC_Shape                                                                                     \
    OMNIUI_PYBIND_KWARGS_DOC_ShapeAnchorHelper

// clang-format on

#define OMNIUI_PYBIND_DOC_BezierCurve_MouseHovered OMNIUI_PYBIND_DOC_BezierCurve_setMouseHoveredFn
