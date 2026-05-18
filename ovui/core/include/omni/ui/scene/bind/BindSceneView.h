/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include "DocManipulatorModelHelper.h"
#include "DocSceneView.h"

#include <omni/ui/bind/BindWidget.h>

// clang-format off
#define OMNIUI_PYBIND_INIT_SceneView                                                                                   \
    OMNIUI_PYBIND_INIT_CAST(aspect_ratio_policy, setAspectRatioPolicy, SceneView::AspectRatioPolicy)                   \
    OMNIUI_PYBIND_INIT_CAST(screen_aspect_ratio, setScreenAspectRatio, float)                                          \
    OMNIUI_PYBIND_INIT_CAST(child_windows_input, setChildWindowsInput, bool)                                           \
    OMNIUI_PYBIND_INIT_CAST(scene, setScene, std::shared_ptr<Scene>)                                                   \
    OMNIUI_PYBIND_INIT_CAST(model, setModel, std::shared_ptr<AbstractManipulatorModel>)                                \
    OMNIUI_PYBIND_INIT_CAST(cache_draw_buffer, setCacheDrawBuffer, bool)                                               \
    OMNIUI_PYBIND_INIT_Widget

#define OMNIUI_PYBIND_KWARGS_DOC_SceneView                                                                             \
    "\n    `aspect_ratio_policy : `\n        "                                                                         \
    OMNIUI_PYBIND_DOC_SceneView_aspectRatioPolicy                                                                      \
    "\n    `model : `\n        "                                                                                       \
    OMNIUI_PYBIND_DOC_SceneView_getView                                                                                \
    "\n    `screen_aspect_ratio : `\n        "                                                                         \
    OMNIUI_PYBIND_DOC_SceneView_screenAspectRatio                                                                      \
    "\n    `child_windows_input : `\n        "                                                                         \
    OMNIUI_PYBIND_DOC_SceneView_childWindowsInput                                                                      \
    OMNIUI_PYBIND_KWARGS_DOC_Widget
// clang-format on
