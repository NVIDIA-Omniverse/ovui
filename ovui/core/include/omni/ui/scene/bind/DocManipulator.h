/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_Manipulator                                                                                  \
    "The base object for the custom manipulators.\n"                                                                   \
    "\n"


#define OMNIUI_PYBIND_DOC_Manipulator_onBuild "Called when Manipulator is dirty to build the content.\n"


#define OMNIUI_PYBIND_DOC_Manipulator_invalidate                                                                       \
    "Make Manipulator dirty so onBuild will be executed in _preDrawContent.\n"


#define OMNIUI_PYBIND_DOC_Manipulator_onModelUpdated                                                                   \
    "Called by the model when the model value is changed. The class should react to the changes.\n"                    \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `item :`\n"                                                                                                   \
    "        The item in the model that is changed. If it's NULL, the root is changed.\n"


#define OMNIUI_PYBIND_DOC_Manipulator_getGestures "All the gestures assigned to this manipulator.\n"


#define OMNIUI_PYBIND_DOC_Manipulator_setGestures "Replace the gestures of the manipulator.\n"


#define OMNIUI_PYBIND_DOC_Manipulator_addGesture "Add a single gesture to the manipulator.\n"


#define OMNIUI_PYBIND_DOC_Manipulator_OnBuild                                                                          \
    "Called when Manipulator is dirty to build the content. It's another way to build the manipulator's content on the case the user doesn't want to reimplement the class.\n"


#define OMNIUI_PYBIND_DOC_Manipulator_Manipulator "Constructor.\n"
