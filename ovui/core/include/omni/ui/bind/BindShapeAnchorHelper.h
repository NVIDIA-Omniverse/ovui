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

#include "BindShape.h"
#include "BindUtils.h"
#include "DocShapeAnchorHelper.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_ShapeAnchorHelper                                                                                           \
    OMNIUI_PYBIND_INIT_CAST(anchor_position, setAnchorPosition, float)                                                                 \
    OMNIUI_PYBIND_INIT_CAST(anchor_alignment, setAnchorAlignment, Alignment)                                                           \
    OMNIUI_PYBIND_INIT_CALLBACK(anchor_fn, setAnchorFn, void())


#define OMNIUI_PYBIND_KWARGS_DOC_ShapeAnchorHelper                                                                                     \
    "\n    `anchor_position: `\n        "                                                                                              \
    OMNIUI_PYBIND_DOC_ShapeAnchorHelper_anchorPosition                                                                                 \
    "\n    `anchor_alignment: `\n        "                                                                                             \
    OMNIUI_PYBIND_DOC_ShapeAnchorHelper_anchorAlignment                                                                                \
    "\n    `set_anchor_fn: Callable`\n        "                                                                                        \
    OMNIUI_PYBIND_DOC_ShapeAnchorHelper_Anchor                                                                                         \
    "\n    `invalidate_anchor: `\n        "                                                                                            \
    OMNIUI_PYBIND_DOC_ShapeAnchorHelper_invalidateAnchor                                                                               \
    "\n    `get_closest_parametric_position: `\n        "                                                                              \
    OMNIUI_PYBIND_DOC_ShapeAnchorHelper_closestParamPosition
// clang-format on
