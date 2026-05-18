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

#define OMNIUI_PYBIND_DOC_ClickGesture                                                                                 \
    "The gesture that provides a way to capture click mouse event.\n"                                                  \
    "\n"


#define OMNIUI_PYBIND_DOC_ClickGesture_preProcess "Called before processing to determine the state of the gesture.\n"


#define OMNIUI_PYBIND_DOC_ClickGesture_process "Process the gesture and call callbacks if necessary.\n"


#define OMNIUI_PYBIND_DOC_ClickGesture_onEnded                                                                         \
    "Called if the callback is not set when the user releases the mouse button.\n"


#define OMNIUI_PYBIND_DOC_ClickGesture_mouseButton "The mouse button this gesture is watching.\n"
#define OMNIUI_PYBIND_DOC_ClickGesture_mouseButtons "The mouse buttons this gesture is watching.\n"


#define OMNIUI_PYBIND_DOC_ClickGesture_modifiers "The modifier that should be pressed to trigger this gesture.\n"


#define OMNIUI_PYBIND_DOC_ClickGesture_OnEnded "Called when the user releases the button.\n"


#define OMNIUI_PYBIND_DOC_ClickGesture_ClickGesture                                                                    \
    "Constructs an gesture to track when the user clicked the mouse.\n"                                                \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `onEnded :`\n"                                                                                                \
    "        Function that is called when the user clicked the mouse button.\n"
