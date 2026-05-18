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
