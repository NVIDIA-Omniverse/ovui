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

#define OMNIUI_PYBIND_DOC_ComboBox                                                                                     \
    "The ComboBox widget is a combined button and a drop-down list.\n"                                                 \
    "A combo box is a selection widget that displays the current item and can pop up a list of selectable items.\n"    \
    "The ComboBox is implemented using the model-view pattern. The model is the central component of this system. The root of the item model should contain the index of currently selected items, and the children of the root include all the items of the combo box.\n"


#define OMNIUI_PYBIND_DOC_ComboBox_setComputedContentWidth                                                             \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. Currently this widget can't be smaller than the size of the ComboBox square.\n"


#define OMNIUI_PYBIND_DOC_ComboBox_setComputedContentHeight                                                            \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than the size of the ComboBox square.\n"


#define OMNIUI_PYBIND_DOC_ComboBox_onStyleUpdated                                                                      \
    "Reimplemented. Something happened with the style or with the parent style. We need to update the saved font.\n"


#define OMNIUI_PYBIND_DOC_ComboBox_onModelUpdated                                                                      \
    "Reimplemented the method from ItemModelHelper that is called when the model is changed.\n"                        \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `item :`\n"                                                                                                   \
    "        The item in the model that is changed. If it's NULL, the root is chaged.\n"


#define OMNIUI_PYBIND_DOC_ComboBox_arrowOnly "Determines if it's necessary to hide the text of the ComboBox.\n"

#define OMNIUI_PYBIND_DOC_ComboBox_noArrowButton                                                                       \
    "Determines if the built-in ComboBox arrow button is hidden while the preview text remains visible.\n"


#define OMNIUI_PYBIND_DOC_ComboBox_ComboBox                                                                            \
    "Construct ComboBox.\n"                                                                                            \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `model :`\n"                                                                                                  \
    "        The model that determines if the button is checked.\n"
