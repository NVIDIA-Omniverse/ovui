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

#include "BindFrame.h"
#include "BindUtils.h"
#include "DocCanvasFrame.h"

// clang-format off
#define OMNIUI_PYBIND_INIT_CanvasFrame                                                                                 \
    OMNIUI_PYBIND_INIT_Frame                                                                                           \
    OMNIUI_PYBIND_INIT_CAST(pan_x, setPanX, float)                                                                     \
    OMNIUI_PYBIND_INIT_CAST(pan_y, setPanY, float)                                                                     \
    OMNIUI_PYBIND_INIT_CAST(zoom, setZoom, float)                                                                      \
    OMNIUI_PYBIND_INIT_CAST(zoom_min, setZoomMin, float)                                                               \
    OMNIUI_PYBIND_INIT_CAST(zoom_max, setZoomMax, float)                                                               \
    OMNIUI_PYBIND_INIT_CAST(compatibility, setCompatibility, bool)                                                     \
    OMNIUI_PYBIND_INIT_CALLBACK(pan_x_changed_fn, setPanXChangedFn, void(float))                                       \
    OMNIUI_PYBIND_INIT_CALLBACK(pan_y_changed_fn, setPanYChangedFn, void(float))                                       \
    OMNIUI_PYBIND_INIT_CALLBACK(zoom_changed_fn, setZoomChangedFn, void(float))                                        \
    OMNIUI_PYBIND_INIT_CAST(smooth_zoom, setSmoothZoom, bool)                                                          \
    OMNIUI_PYBIND_INIT_CAST(draggable, setDraggable, bool)

#define OMNIUI_PYBIND_KWARGS_DOC_CanvasFrame                                                                           \
    "\n    `pan_x : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_CanvasFrame_panX                                                                                 \
    "\n    `pan_y : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_CanvasFrame_panY                                                                                 \
    "\n    `zoom : `\n        "                                                                                        \
    OMNIUI_PYBIND_DOC_CanvasFrame_zoomMin                                                                              \
    "\n    `zoom_min : `\n        "                                                                                    \
    OMNIUI_PYBIND_DOC_CanvasFrame_zoomMax                                                                              \
    "\n    `zoom_max : `\n        "                                                                                    \
    OMNIUI_PYBIND_DOC_CanvasFrame_zoom                                                                                 \
    "\n    `compatibility : `\n        "                                                                               \
    OMNIUI_PYBIND_DOC_CanvasFrame_compatibility                                                                        \
    "\n    `pan_x_changed_fn : `\n        "                                                                            \
    OMNIUI_PYBIND_DOC_CanvasFrame_panX                                                                                 \
    "\n    `pan_y_changed_fn : `\n        "                                                                            \
    OMNIUI_PYBIND_DOC_CanvasFrame_panY                                                                                 \
    "\n    `zoom_changed_fn : `\n        "                                                                             \
    OMNIUI_PYBIND_DOC_CanvasFrame_zoom                                                                                 \
    "\n    `draggable : `\n        "                                                                                   \
    OMNIUI_PYBIND_DOC_CanvasFrame_draggable                                                                            \
    OMNIUI_PYBIND_KWARGS_DOC_Frame
// clang-format on
