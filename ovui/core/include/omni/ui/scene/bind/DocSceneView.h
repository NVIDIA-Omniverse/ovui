/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#define OMNIUI_PYBIND_DOC_SceneView                                                                                    \
    "The widget to render omni.ui.scene.\n"                                                                            \
    "\n"


#define OMNIUI_PYBIND_DOC_SceneView_getProjection                                                                      \
    "The camera projection matrix. It's a shortcut for Matrix44(SceneView.model.get_as_floats(\"projection\"))\n"


#define OMNIUI_PYBIND_DOC_SceneView_getView                                                                            \
    "The camera view matrix. It's a shortcut for Matrix44(SceneView.model.get_as_floats(\"view\"))\n"


#define OMNIUI_PYBIND_DOC_SceneView_onModelUpdated                                                                     \
    "Called by the model when the model value is changed. The class should react to the changes.\n"                    \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `item :`\n"                                                                                                   \
    "        The item in the model that is changed. If it's NULL, the root is changed.\n\n"


#define OMNIUI_PYBIND_DOC_SceneView_scene "The container that holds the shapes, gestures and managers.\n"


#define OMNIUI_PYBIND_DOC_SceneView_screenAspectRatio                                                                  \
    "Aspect ratio of the rendering screen. This screen will be fit to the widget. "                                   \
    "SceneView simulates the behavior of the Kit viewport where the rendered image (screen) fits into the viewport "   \
    "(widget), and the camera has multiple policies that modify the camera projection matrix's aspect ratio to match " \
    "it to the screen aspect ratio. "                                                                                 \
    "When screen_aspect_ratio is 0, Screen size matches the Widget bounds.\n"


#define OMNIUI_PYBIND_DOC_SceneView_childWindowsInput                                                                  \
    "When it's false, the mouse events from other widgets inside the bounds are ignored. We need it to filter out mouse events from mouse events of widgets in `ui.VStack(content_clipping=1)`.\n"


#define OMNIUI_PYBIND_DOC_SceneView_aspectRatioPolicy                                                                  \
    "Define what happens when the aspect ratio of the camera is different from the aspect ratio of the widget.\n"


#define OMNIUI_PYBIND_DOC_SceneView_SceneView "Constructor.\n"


#define OMNIUI_PYBIND_DOC_SceneView_cacheDrawBuffer "When it's true, the caching draw buffer optimization is enabled.\n"
