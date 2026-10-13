/*
 * SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#define OMNIUI_PYBIND_DOC_ItemModelHelper                                                                              \
    "The ItemModelHelper class provides the basic functionality for item widget classes.\n"


#define OMNIUI_PYBIND_DOC_ItemModelHelper_onModelUpdated                                                               \
    "Called by the model when the model value is changed. The class should react to the changes.\n"                    \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `item :`\n"                                                                                                   \
    "        The item in the model that is changed. If it's NULL, the root is chaged.\n"


#define OMNIUI_PYBIND_DOC_ItemModelHelper_setModel "Set the current model.\n"


#define OMNIUI_PYBIND_DOC_ItemModelHelper_getModel "Returns the current model.\n"
