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

#define OMNIUI_PYBIND_DOC_HoverGesture                                                                                 \
    "The gesture that provides a way to capture event when mouse enters/leaves the item.\n"                            \
    "\n"


#define OMNIUI_PYBIND_DOC_HoverGesture_preProcess "Called before processing to determine the state of the gesture.\n"


#define OMNIUI_PYBIND_DOC_HoverGesture_process "Process the gesture and call callbacks if necessary.\n"


#define OMNIUI_PYBIND_DOC_HoverGesture_onBegan "Called if the callback is not set and the mouse enters the item.\n"


#define OMNIUI_PYBIND_DOC_HoverGesture_onChanged                                                                       \
    "Called if the callback is not set and the mouse is hovering the item.\n"


#define OMNIUI_PYBIND_DOC_HoverGesture_onEnded "Called if the callback is not set and the mouse leaves the item.\n"


#define OMNIUI_PYBIND_DOC_HoverGesture_mouseButton "The mouse button this gesture is watching.\n"
#define OMNIUI_PYBIND_DOC_HoverGesture_mouseButtons "The mouse buttons this gesture is watching.\n"


#define OMNIUI_PYBIND_DOC_HoverGesture_modifiers "The modifier that should be pressed to trigger this gesture.\n"


#define OMNIUI_PYBIND_DOC_HoverGesture_OnBegan "Called when the mouse enters the item.\n"


#define OMNIUI_PYBIND_DOC_HoverGesture_OnChanged "Called when the mouse is hovering the item.\n"


#define OMNIUI_PYBIND_DOC_HoverGesture_OnEnded "Called when the mouse leaves the item.\n"


#define OMNIUI_PYBIND_DOC_HoverGesture_HoverGesture                                                                    \
    "Constructs an gesture to track when the user clicked the mouse.\n"                                                \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `onEnded :`\n"                                                                                                \
    "        Function that is called when the user clicked the mouse button.\n"
