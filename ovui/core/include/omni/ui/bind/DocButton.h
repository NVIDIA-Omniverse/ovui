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

#define OMNIUI_PYBIND_DOC_Button                                                                                       \
    "The Button widget provides a command button.\n"                                                                   \
    "The command button, is perhaps the most commonly used widget in any graphical user interface. Click a button to execute a command. It is rectangular and typically displays a text label describing its action.\n"


#define OMNIUI_PYBIND_DOC_Button_setComputedContentWidth                                                               \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. Currently this widget can't be smaller than the size of the text.\n"


#define OMNIUI_PYBIND_DOC_Button_setComputedContentHeight                                                              \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than the size of the text.\n"


#define OMNIUI_PYBIND_DOC_Button_onStyleUpdated                                                                        \
    "Reimplemented. Something happened with the style or with the parent style. We need to gerenerate the cache.\n"


#define OMNIUI_PYBIND_DOC_Button_cascadeStyle                                                                          \
    "Reimplemented. It's called when the style is changed. It should be propagated to children to make the style cached and available to children.\n"


#define OMNIUI_PYBIND_DOC_Button_text "This property holds the button's text.\n"


#define OMNIUI_PYBIND_DOC_Button_imageUrl "This property holds the button's optional image URL.\n"


#define OMNIUI_PYBIND_DOC_Button_imageWidth                                                                            \
    "This property holds the width of the image widget. Do not use this function to find the width of the image.\n"


#define OMNIUI_PYBIND_DOC_Button_imageHeight                                                                           \
    "This property holds the height of the image widget. Do not use this function to find the height of the image.\n"


#define OMNIUI_PYBIND_DOC_Button_spacing "Sets a non-stretchable space in points between image and text.\n"


#define OMNIUI_PYBIND_DOC_Button_Button                                                                                \
    "Construct a button with a text on it.\n"                                                                          \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `text :`\n"                                                                                                   \
    "        The text for the button to use.\n"
