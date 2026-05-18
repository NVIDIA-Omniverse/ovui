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

#define OMNIUI_PYBIND_DOC_MultiDragField                                                                                                          \
    "The base class for MultiFloatDragField and MultiIntDragField. We need it because there classes are very similar, so we can template them.\n" \
    "\n"                                                                                                                                          \
    "\n"                                                                                                                                          \
    "### Arguments:\n"                                                                                                                            \
    "\n"                                                                                                                                          \
    "    `T :`\n"                                                                                                                                 \
    "        FloatDrag or IntDrag\n"                                                                                                              \
    "\n"                                                                                                                                          \
    "    `U :`\n"                                                                                                                                 \
    "        float or Int\n"


#define OMNIUI_PYBIND_DOC_MultiDragField_onModelUpdated                                                                \
    "Reimplemented. Called by the model when the model value is changed.\n"


#define OMNIUI_PYBIND_DOC_MultiDragField_min "This property holds the drag's minimum value.\n"


#define OMNIUI_PYBIND_DOC_MultiDragField_max "This property holds the drag's maximum value.\n"


#define OMNIUI_PYBIND_DOC_MultiDragField_step "This property controls the steping speed on the drag.\n"


#define OMNIUI_PYBIND_DOC_MultiDragField_MultiDragField                                                                \
    "Constructs MultiDragField.\n"                                                                                     \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `model :`\n"                                                                                                  \
    "        The widget's model. If the model is not assigned, the default model is created.\n"
