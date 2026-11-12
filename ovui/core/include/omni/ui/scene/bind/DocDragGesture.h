/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_DragGesture                                                                                  \
    "The gesture that provides a way to capture click-and-drag mouse event.\n"                                         \
    "\n"                                                                                                               \
    "on_began and on_ended are called once for each drag. on_changed is called in each frame of the drag in which the payload of the shape changed (the item closest point or the ray closest point is not the one of the previous frame), except a frame that only shows the follow of the last call. Pointer movements that are queued before one frame give one call, with the payload of the last of them. A frame in which nothing changed gives no call, also when the pointer is held. The payload changes when the pointer moves, when the camera moves, and when the shape or an item above it is written by any code; every such change is called, also under a still pointer, however small it is. A color, a thickness or a size is not a change of the payload. moved (and the other moved_* values) is the change of the payload values since the last call, so the moved of the calls add up to the change of the payload since the drag began.\n" \
    "\n"                                                                                                               \
    "The follow of the pointer: a consumer that moves the shape, or a Transform above it, by the moved that a call reported, while its callback runs, gets no second call for that movement. The next frame, under the same pointer and camera, has the payload of the new place; it has no call when the writes of the callback are the follow. They are the follow when the consumer declares them with gesture.following(), or when each is exactly what the movement gives (the old translation plus moved, of one Transform; the movement divided equally between several Transforms; both ends of a Line or all positions of a Points moved by it), with only plain translations above and each written once in the callback. Everything else is called, however small: it has the data of a call for an independent edit with the same numbers, and a lost real update is worse than one extra call.\n"


#define OMNIUI_PYBIND_DOC_DragGesture_following "Returns a context manager. The writes to the shape, or to the transforms above it, that are made inside its block are the follow of the pointer: the movement that the last on_changed call reported, applied by the consumer. The frame that follows, which has the payload of the new place under a still pointer, is then not a second on_changed call for the same movement.\n"

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
