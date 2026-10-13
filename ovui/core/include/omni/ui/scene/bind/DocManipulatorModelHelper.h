/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_ManipulatorModelHelper                                                                       \
    "The ManipulatorModelHelper class provides the basic model functionality.\n"


#define OMNIUI_PYBIND_DOC_ManipulatorModelHelper_onModelUpdated                                                        \
    "Called by the model when the model value is changed. The class should react to the changes.\n"                    \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `item :`\n"                                                                                                   \
    "        The item in the model that is changed. If it's NULL, the root is changed.\n"


#define OMNIUI_PYBIND_DOC_ManipulatorModelHelper_getRayFromNdc "Convert NDC 2D [-1..1] coordinates to 3D ray.\n"


#define OMNIUI_PYBIND_DOC_ManipulatorModelHelper_setModel "Set the current model.\n"


#define OMNIUI_PYBIND_DOC_ManipulatorModelHelper_getModel "Returns the current model.\n"
