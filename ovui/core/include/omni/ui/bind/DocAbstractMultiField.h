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

#define OMNIUI_PYBIND_DOC_AbstractMultiField                                                                           \
    "AbstractMultiField is the abstract class that has everything to create a custom widget per model item.\n"         \
    "The class that wants to create multiple widgets per item needs to reimplement the method _createField.\n"


#define OMNIUI_PYBIND_DOC_AbstractMultiField_setComputedContentWidth                                                   \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. Currently this widget can't be smaller than the size of the text.\n"


#define OMNIUI_PYBIND_DOC_AbstractMultiField_setComputedContentHeight                                                  \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than the size of the text.\n"


#define OMNIUI_PYBIND_DOC_AbstractMultiField_onStyleUpdated                                                            \
    "Reimplemented. Something happened with the style or with the parent style. We need to gerenerate the cache.\n"


#define OMNIUI_PYBIND_DOC_AbstractMultiField_onModelUpdated                                                            \
    "Reimplemented. Called by the model when the model value is changed.\n"                                            \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `item :`\n"                                                                                                   \
    "        The item in the model that is changed. If it's NULL, the root is chaged.\n"


#define OMNIUI_PYBIND_DOC_AbstractMultiField_columnCount "The max number of fields in a line.\n"


#define OMNIUI_PYBIND_DOC_AbstractMultiField_hSpacing                                                                  \
    "Sets a non-stretchable horizontal space in pixels between child fields.\n"


#define OMNIUI_PYBIND_DOC_AbstractMultiField_vSpacing                                                                  \
    "Sets a non-stretchable vertical space in pixels between child fields.\n"


#define OMNIUI_PYBIND_DOC_AbstractMultiField_AbstractMultiField "Constructor.\n"
