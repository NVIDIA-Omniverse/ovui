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

#define OMNIUI_PYBIND_DOC_CheckBox                                                                                                                                                                                           \
    "A CheckBox is an option button that can be switched on (checked) or off (unchecked). Checkboxes are typically used to represent features in an application that can be enabled or disabled without affecting others.\n" \
    "The checkbox is implemented using the model-view pattern. The model is the central component of this system. It is the application's dynamic data structure independent of the widget. It directly manages the data, logic, and rules of the checkbox. If the model is not specified, the simple one is created automatically when the object is constructed.\n"


#define OMNIUI_PYBIND_DOC_CheckBox_setComputedContentWidth                                                             \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. Currently this widget can't be smaller than the size of the checkbox square.\n"


#define OMNIUI_PYBIND_DOC_CheckBox_setComputedContentHeight                                                            \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than the size of the checkbox square.\n"


#define OMNIUI_PYBIND_DOC_CheckBox_onModelUpdated                                                                      \
    "Reimplemented the method from ValueModelHelper that is called when the model is changed.\n"


#define OMNIUI_PYBIND_DOC_CheckBox_onStyleUpdated                                                                      \
    "Reimplemented. Something happened with the style or with the parent style. We need to gerenerate the cache.\n"


#define OMNIUI_PYBIND_DOC_CheckBox_CheckBox                                                                            \
    "CheckBox with specified model. If model is not specified, it's using the default one.\n"
