/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_ManipulatorGesture                                                                           \
    "The base class for the gestures to provides a way to capture events of the manipulator objects.\n"                \
    "\n"


#define OMNIUI_PYBIND_DOC_ManipulatorGesture_dispatchInput                                                                                  \
    "Called by scene to process the mouse inputs and do intersections with shapes. It can be an entry point to simulate the mouse input.\n" \
    "Todo\n"                                                                                                                                \
    "We probably don't need projection-view here. We can get it from manager.\n"


#define OMNIUI_PYBIND_DOC_ManipulatorGesture_preProcess                                                                \
    "Called before processing to determine the state of the gesture.\n"


#define OMNIUI_PYBIND_DOC_ManipulatorGesture_getSender "Returns the relevant shape driving the gesture.\n"


#define OMNIUI_PYBIND_DOC_ManipulatorGesture_ManipulatorGesture "Constructor.\n"
