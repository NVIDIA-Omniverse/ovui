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

#define OMNIUI_PYBIND_DOC_CanvasFrame                                                                                                                              \
    "CanvasFrame is the widget that allows the user to pan and zoom its children with a mouse. It has the layout that can be infinitely moved in any direction.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_setComputedContentWidth                                                          \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_setComputedContentHeight                                                         \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_screenToCanvasX "Transforms screen-space X to canvas-space X.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_screenToCanvasY "Transforms screen-space Y to canvas-space Y.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_setPanKeyShortcut "Specify the mouse button and key to pan the canvas.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_setZoomKeyShortcut "Specify the mouse button and key to zoom the canvas.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_panX "The horizontal offset of the child item.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_panY "The vertical offset of the child item.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_zoom "The zoom level of the child item.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_zoomMin "The zoom minimum of the child item.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_zoomMax "The zoom maximum of the child item.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_smoothZoom                                                                       \
    "When true, zoom is smooth like in Bifrost even if the user is using mouse wheen that doesn't provide smooth scrolling.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_draggable                                                                        \
    "Provides a convenient way to make the content draggable and zoomable.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_compatibility                                                                    \
    "This boolean property controls the behavior of CanvasFrame. When set to true, the widget will function in the old way. When set to false, the widget will use a newer and faster implementation. This variable is included as a transition period to ensure that the update does not break any existing functionality. Please be aware that the old behavior may be deprecated in the future, so it is recommended to set this variable to false once you have thoroughly tested the new implementation.\n"


#define OMNIUI_PYBIND_DOC_CanvasFrame_CanvasFrame "Constructs CanvasFrame.\n"
