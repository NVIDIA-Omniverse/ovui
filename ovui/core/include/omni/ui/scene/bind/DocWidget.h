/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_Widget                                                                                                                                                                                                                                                                          \
    "The shape that contains the omni.ui widgets. It automatically creates IAppWindow and transfers its content to the texture of the rectangle. It interacts with the mouse and sends the mouse events to the underlying window, so interacting with the UI on this rectangle is smooth for the user.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_Widget_getFrame "Return the main frame of the widget.\n"


#define OMNIUI_PYBIND_DOC_Widget_invalidate                                                                            \
    "Rebuild and recapture the widgets at the next frame. If\n"                                                        \
    "frame\n"                                                                                                          \
    "build_fn\n"


#define OMNIUI_PYBIND_DOC_Widget_fillPolicy                                                                            \
    "Define what happens when the source image has a different size than the item.\n"


#define OMNIUI_PYBIND_DOC_Widget_updatePolicy "Define when to redraw the widget.\n"


#define OMNIUI_PYBIND_DOC_Widget_resolutionScale "The resolution scale of the widget.\n"


#define OMNIUI_PYBIND_DOC_Widget_resolutionWidth "The resolution of the widget framebuffer.\n"


#define OMNIUI_PYBIND_DOC_Widget_resolutionHeight "The resolution of the widget framebuffer.\n"


#define OMNIUI_PYBIND_DOC_Widget_Widget "Created an empty image.\n"
