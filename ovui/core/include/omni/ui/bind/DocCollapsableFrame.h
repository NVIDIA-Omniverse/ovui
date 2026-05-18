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

#define OMNIUI_PYBIND_DOC_CollapsableFrame                                                                                                                                                                                                                                                                                                  \
    "CollapsableFrame is a frame widget that can hide or show its content. It has two states expanded and collapsed. When it's collapsed, it looks like a button. If it's expanded, it looks like a button and a frame with the content. It's handy to group properties, and temporarily hide them to get more space for something else.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_CollapsableFrame_addChild "Reimplemented. It adds a widget to m_body.\n"


#define OMNIUI_PYBIND_DOC_CollapsableFrame_setComputedContentWidth                                                     \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. Currently this widget can't be smaller than the minimal size of the child widgets.\n"


#define OMNIUI_PYBIND_DOC_CollapsableFrame_setComputedContentHeight                                                    \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than the minimal size of the child widgets.\n"


#define OMNIUI_PYBIND_DOC_CollapsableFrame_BuildHeader                                                                 \
    "Set dynamic header that will be created dynamiclly when it is needed. The function is called inside a ui.Frame scope that the widget will be parented correctly.\n"


#define OMNIUI_PYBIND_DOC_CollapsableFrame_collapsed "The state of the CollapsableFrame.\n"


#define OMNIUI_PYBIND_DOC_CollapsableFrame_title "The header text.\n"


#define OMNIUI_PYBIND_DOC_CollapsableFrame_alignment                                                                   \
    "This property holds the alignment of the label in the default header. By default, the contents of the label are left-aligned and vertically-centered.\n"


#define OMNIUI_PYBIND_DOC_CollapsableFrame_CollapsableFrame                                                            \
    "Constructs CollapsableFrame.\n"                                                                                   \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `text :`\n"                                                                                                   \
    "        The text for the caption of the frame.\n"
