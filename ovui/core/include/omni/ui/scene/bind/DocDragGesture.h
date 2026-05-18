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

#define OMNIUI_PYBIND_DOC_DragGesture                                                                                  \
    "The gesture that provides a way to capture click-and-drag mouse event.\n"                                         \
    "\n"


#define OMNIUI_PYBIND_DOC_DragGesture_preProcess "Called before processing to determine the state of the gesture.\n"


#define OMNIUI_PYBIND_DOC_DragGesture_process "Process the gesture and call callbacks if necessary.\n"


#define OMNIUI_PYBIND_DOC_DragGesture_onBegan                                                                          \
    "Called if the callback is not set when the user clicks the mouse button.\n"


#define OMNIUI_PYBIND_DOC_DragGesture_onChanged                                                                        \
    "Called if the callback is not set when the user moves the clicked button.\n"


#define OMNIUI_PYBIND_DOC_DragGesture_onEnded                                                                          \
    "Called if the callback is not set when the user releases the mouse button.\n"


#define OMNIUI_PYBIND_DOC_DragGesture_mouseButton "Mouse button that should be active to start the gesture.\n"
#define OMNIUI_PYBIND_DOC_DragGesture_mouseButtons "Mouse buttons that should be active to start the gesture.\n"

#define OMNIUI_PYBIND_DOC_DragGesture_modifiers "The keyboard modifier that should be active ti start the gesture.\n"


#define OMNIUI_PYBIND_DOC_DragGesture_checkMouseMoved                                                                                                                                                                                                                                                                                                                                                                  \
    "The check_mouse_moved property is a boolean flag that determines whether the DragGesture should verify if the 2D screen position of the mouse has changed before invoking the on_changed method. This property is essential in a 3D environment, as changes in the camera position can result in the mouse pointing to different locations in the 3D world even when the 2D screen position remains unchanged.\n\n" \
    "Usage\n"                                                                                                                                                                                                                                                                                                                                                                                                          \
    "When check_mouse_moved is set to True, the DragGesture will only call the on_changed method if the actual 2D screen position of the mouse has changed. This can be useful when you want to ensure that the on_changed method is only triggered when there is a genuine change in the mouse's 2D screen position.\n"                                                                                               \
    "If check_mouse_moved is set to False, the DragGesture will not check for changes in the mouse's 2D screen position before calling the on_changed method. This can be useful when you want the on_changed method to be invoked even if the mouse's 2D screen position hasn't changed, such as when the camera position is altered, and the mouse now points to a different location in the 3D world.\n"


#define OMNIUI_PYBIND_DOC_DragGesture_OnBegan "Called when the user starts drag.\n"


#define OMNIUI_PYBIND_DOC_DragGesture_OnChanged "Called when the user is dragging.\n"


#define OMNIUI_PYBIND_DOC_DragGesture_OnEnded "Called when the user releases the mouse and finishes the drag.\n"


#define OMNIUI_PYBIND_DOC_DragGesture_DragGesture "Construct the gesture to track mouse drags.\n"
