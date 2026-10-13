/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_ScrollGesture                                                                                \
    "The gesture that provides a way to capture mouse scroll event.\n"                                                 \
    "\n"


#define OMNIUI_PYBIND_DOC_ScrollGesture_preProcess "Called before processing to determine the state of the gesture.\n"


#define OMNIUI_PYBIND_DOC_ScrollGesture_process "Process the gesture and call callbacks if necessary.\n"


#define OMNIUI_PYBIND_DOC_ScrollGesture_onEnded "Called if the callback is not set when the user scrolls.\n"


#define OMNIUI_PYBIND_DOC_ScrollGesture_mouseButton "The mouse button this gesture is watching.\n"
#define OMNIUI_PYBIND_DOC_ScrollGesture_mouseButtons "The mouse buttons this gesture is watching.\n"


#define OMNIUI_PYBIND_DOC_ScrollGesture_modifiers "The modifier that should be pressed to trigger this gesture.\n"


#define OMNIUI_PYBIND_DOC_ScrollGesture_OnEnded "Called when the user scrolls.\n"


#define OMNIUI_PYBIND_DOC_ScrollGesture_getScroll "Returns the current scroll state.\n"


#define OMNIUI_PYBIND_DOC_ScrollGesture_ScrollGesture                                                                  \
    "Constructs an gesture to track when the user clicked the mouse.\n"                                                \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `onEnded :`\n"                                                                                                \
    "        Function that is called when the user clicked the mouse button.\n"
