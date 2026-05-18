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

#define OMNIUI_PYBIND_DOC_AbstractGesture                                                                              \
    "The base class for the gestures to provides a way to capture mouse events in 3d scene.\n"                         \
    "\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_setManager "Set the Manager that controld this gesture.\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_getManager "The Manager that controld this gesture.\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_dispatchInput                                                                                     \
    "Called by scene to process the mouse inputs and do intersections with shapes. It can be an entry point to simulate the mouse input.\n" \
    "Todo\n"                                                                                                                                \
    "We probably don't need projection-view here. We can get it from manager.\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_preProcess                                                                   \
    "Called before the processing to determine the state of the gesture.\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_process "Process the gesture and call callbacks if necessary.\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_postProcess "Gestures are finished. Clean-up.\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_getState "Get the internal state of the gesture.\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_setState                                                                     \
    "Set the internal state of the gesture. It's the way to cancel, prevent, or restore the gesture.\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_isStateChanged                                                               \
    "Returns true if the gesture is just changed at the current frame. If the state is not changed,\n"                 \
    "process()\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_getSender "Returns the relevant shape driving the gesture.\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_getGesturePayload                                                            \
    "Shortcut for sender.get_gesturePayload.\n"                                                                        \
    "OMNIUI_SCENE_API const*\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_getGesturePayload01                                                          \
    "Shortcut for sender.get_gesturePayload.\n"                                                                        \
    "OMNIUI_SCENE_API const*\n"


#define OMNIUI_PYBIND_DOC_AbstractGesture_name "The name of the object. It's used for debugging.\n"
