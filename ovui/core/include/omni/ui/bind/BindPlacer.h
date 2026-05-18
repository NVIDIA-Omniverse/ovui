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

#include "BindContainer.h"
#include "BindUtils.h"
#include "DocPlacer.h"
#include "DocRasterHelper.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_Placer                                                                                      \
    OMNIUI_PYBIND_INIT_Container                                                                                       \
    OMNIUI_PYBIND_INIT_CALL(offset_x, setOffsetX, toLength)                                                            \
    OMNIUI_PYBIND_INIT_CALL(offset_y, setOffsetY, toLength)                                                            \
    OMNIUI_PYBIND_INIT_CAST(draggable, setDraggable, bool)                                                             \
    OMNIUI_PYBIND_INIT_CAST(drag_axis, setDragAxis, Axis)                                                              \
    OMNIUI_PYBIND_INIT_CAST(stable_size, setStableSize, bool)                                                          \
    OMNIUI_PYBIND_INIT_CAST(frames_to_start_drag, setFramesToStartDrag, int)                                           \
    OMNIUI_PYBIND_INIT_CAST(raster_policy, setRasterPolicy, RasterPolicy)                                              \
    OMNIUI_PYBIND_INIT_CALLBACK(offset_x_changed_fn, setOffsetXChangedFn, void(const Length &))                        \
    OMNIUI_PYBIND_INIT_CALLBACK(offset_y_changed_fn, setOffsetYChangedFn, void(const Length &))

#define OMNIUI_PYBIND_KWARGS_DOC_Placer                                                                                \
    "\n    `offset_x : toLength`\n        "                                                                            \
    OMNIUI_PYBIND_DOC_Placer_offsetX                                                                                   \
    "\n    `offset_y : toLength`\n        "                                                                            \
    OMNIUI_PYBIND_DOC_Placer_offsetY                                                                                   \
    "\n    `draggable : bool`\n        "                                                                               \
    OMNIUI_PYBIND_DOC_Placer_draggable                                                                                 \
    "\n    `drag_axis : Axis`\n        "                                                                               \
    OMNIUI_PYBIND_DOC_Placer_dragAxis                                                                                  \
    "\n    `stable_size : bool`\n        "                                                                             \
    OMNIUI_PYBIND_DOC_Placer_stableSize                                                                                \
    "\n    `raster_policy : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_RasterHelper_rasterPolicy                                                                        \
    "\n    `offset_x_changed_fn : Callable[[ui.Length], None]`\n        "                                              \
    OMNIUI_PYBIND_DOC_Placer_offsetX                                                                                   \
    "\n    `offset_y_changed_fn : Callable[[ui.Length], None]`\n        "                                              \
    OMNIUI_PYBIND_DOC_Placer_offsetY                                                                                   \
    OMNIUI_PYBIND_KWARGS_DOC_Container
// clang-format on
