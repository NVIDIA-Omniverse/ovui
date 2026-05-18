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

#define OMNIUI_PYBIND_DOC_Stack                                                                                        \
    "The Stack class lines up child widgets horizontally, vertically or sorted in a Z-order.\n"                        \
    "\n"


#define OMNIUI_PYBIND_DOC_Stack_Direction                                                                              \
    "This type is used to determine the direction of the layout. If the Stack's orientation is eLeftToRight the widgets are placed in a horizontal row, from left to right. If the Stack's orientation is eRightToLeft the widgets are placed in a horizontal row, from right to left. If the Stack's orientation is eTopToBottom, the widgets are placed in a vertical column, from top to bottom. If the Stack's orientation is eBottomToTop, the widgets are placed in a vertical column, from bottom to top. If the Stack's orientation is eBackToFront, the widgets are placed sorted in a Z-order in top right corner. If the Stack's orientation is eFrontToBack, the widgets are placed sorted in a Z-order in top right corner, the first widget goes to front.\n"


#define OMNIUI_PYBIND_DOC_Stack_addChild                                                                               \
    "Reimplemented adding a widget to this Stack. The Stack class can contain multiple widgets.\n"


#define OMNIUI_PYBIND_DOC_Stack_clear "Reimplemented removing all the child widgets from this Stack.\n"


#define OMNIUI_PYBIND_DOC_Stack_setComputedContentWidth                                                                \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. Currently this widget can't be smaller than the minimal size of the child widgets.\n"


#define OMNIUI_PYBIND_DOC_Stack_setComputedContentHeight                                                               \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than the minimal size of the child widgets.\n"


#define OMNIUI_PYBIND_DOC_Stack_cascadeStyle                                                                           \
    "It's called when the style is changed. It should be propagated to children to make the style cached and available to children.\n"


#define OMNIUI_PYBIND_DOC_Stack_setVisiblePreviousFrame "Change dirty bits when the visibility is changed.\n"


#define OMNIUI_PYBIND_DOC_Stack_contentClipping                                                                        \
    "Determines if the child widgets should be clipped by the rectangle of this Stack.\n"


#define OMNIUI_PYBIND_DOC_Stack_spacing "Sets a non-stretchable space in pixels between child items of this layout.\n"


#define OMNIUI_PYBIND_DOC_Stack_direction                                                                              \
    "Determines the type of the layout. It can be vertical, horizontal and front-to-back.\n"


#define OMNIUI_PYBIND_DOC_Stack_sendMouseEventsToBack                                                                  \
    "When children of a Z-based stack overlap mouse events are normally sent to the topmost one. Setting this property true will invert that behavior, sending mouse events to the bottom-most child.\n"


#define OMNIUI_PYBIND_DOC_Stack_Stack                                                                                  \
    "Constructor.\n"                                                                                                   \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `direction :`\n"                                                                                              \
    "        Determines the orientation of the Stack.\n"
