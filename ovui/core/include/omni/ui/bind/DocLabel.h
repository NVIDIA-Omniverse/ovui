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

#define OMNIUI_PYBIND_DOC_Label                                                                                        \
    "The Label widget provides a text to display.\n"                                                                   \
    "Label is used for displaying text. No additional to Widget user interaction functionality is provided.\n"


#define OMNIUI_PYBIND_DOC_Label_setComputedContentWidth                                                                \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. Currently this widget can't be smaller than the size of the text.\n"


#define OMNIUI_PYBIND_DOC_Label_setComputedContentHeight                                                               \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than the size of the text.\n"


#define OMNIUI_PYBIND_DOC_Label_onStyleUpdated                                                                         \
    "Reimplemented. Something happened with the style or with the parent style. We need to update the saved font.\n"


#define OMNIUI_PYBIND_DOC_Label_exactContentWidth                                                                      \
    "Return the exact width of the content of this label. Computed content width is a size hint and may be bigger than the text in the label.\n"


#define OMNIUI_PYBIND_DOC_Label_exactContentHeight                                                                     \
    "Return the exact height of the content of this label. Computed content height is a size hint and may be bigger than the text in the label.\n"


#define OMNIUI_PYBIND_DOC_Label_text "This property holds the label's text.\n"


#define OMNIUI_PYBIND_DOC_Label_wordWrap                                                                               \
    "This property holds the label's word-wrapping policy If this property is true then label text is wrapped where necessary at word-breaks; otherwise it is not wrapped at all. By default, word wrap is disabled.\n"


#define OMNIUI_PYBIND_DOC_Label_elidedText                                                                             \
    "When the text of a big length has to be displayed in a small area, it can be useful to give the user a visual hint that not all text is visible. Label can elide text that doesn't fit in the area. When this property is true, Label elides the middle of the last visible line and replaces it with \"...\".\n"

#define OMNIUI_PYBIND_DOC_Label_elidedTextStr                                                                          \
    "Customized elidedText string when elidedText is True, default is ...."                                            \

#define OMNIUI_PYBIND_DOC_Label_hideTextAfterHash                                                                      \
    "Hide anything after a '##' string or not"                                                                         \

#define OMNIUI_PYBIND_DOC_Label_alignment                                                                              \
    "This property holds the alignment of the label's contents. By default, the contents of the label are left-aligned and vertically-centered.\n"


#define OMNIUI_PYBIND_DOC_Label_Label                                                                                  \
    "Create a label with the given text.\n"                                                                            \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `text :`\n"                                                                                                   \
    "        The text for the label.\n"
