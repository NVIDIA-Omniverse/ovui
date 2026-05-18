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

#define OMNIUI_PYBIND_DOC_Plot                                                                                         \
    "The Plot widget provides a line/histogram to display.\n"                                                          \
    "\n"


#define OMNIUI_PYBIND_DOC_Plot_Type "This type is used to determine the type of the image.\n"


#define OMNIUI_PYBIND_DOC_Plot_setComputedContentHeight                                                                \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than 1 pixel.\n"


#define OMNIUI_PYBIND_DOC_Plot_setDataProviderFn "Sets the function that will be called when when data required.\n"


#define OMNIUI_PYBIND_DOC_Plot_setData "Sets the image data value.\n"


#define OMNIUI_PYBIND_DOC_Plot_type                                                                                    \
    "This property holds the type of the image, can only be line or histogram. By default, the type is line.\n"


#define OMNIUI_PYBIND_DOC_Plot_scaleMin "This property holds the min scale values. By default, the value is FLT_MAX.\n"


#define OMNIUI_PYBIND_DOC_Plot_scaleMax "This property holds the max scale values. By default, the value is FLT_MAX.\n"


#define OMNIUI_PYBIND_DOC_Plot_valueOffset "This property holds the value offset. By default, the value is 0.\n"


#define OMNIUI_PYBIND_DOC_Plot_valueStride                                                                             \
    "This property holds the stride to get value list. By default, the value is 1.\n"


#define OMNIUI_PYBIND_DOC_Plot_title "This property holds the title of the image.\n"


#define OMNIUI_PYBIND_DOC_Plot_Plot                                                                                    \
    "Construct Plot.\n"                                                                                                \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `type :`\n"                                                                                                   \
    "        The type of the image, can be line or histogram.\n"                                                       \
    "\n"                                                                                                               \
    "    `scaleMin :`\n"                                                                                               \
    "        The minimal scale value.\n"                                                                               \
    "\n"                                                                                                               \
    "    `scaleMax :`\n"                                                                                               \
    "        The maximum scale value.\n"                                                                               \
    "\n"                                                                                                               \
    "    `valueList :`\n"                                                                                              \
    "        The list of values to draw the image.\n"
