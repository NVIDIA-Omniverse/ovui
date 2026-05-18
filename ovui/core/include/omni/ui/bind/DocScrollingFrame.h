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

#define OMNIUI_PYBIND_DOC_ScrollingFrame                                                                               \
    "The ScrollingFrame class provides the ability to scroll onto another widget.\n"                                   \
    "ScrollingFrame is used to display the contents of a child widget within a frame. If the widget exceeds the size of the frame, the frame can provide scroll bars so that the entire area of the child widget can be viewed. The child widget must be specified with addChild().\n"


#define OMNIUI_PYBIND_DOC_ScrollingFrame_setComputedContentWidth                                                       \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. Currently this widget can't be smaller than the minimal size of the child widgets.\n"


#define OMNIUI_PYBIND_DOC_ScrollingFrame_setComputedContentHeight                                                      \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than the minimal size of the child widgets.\n"


#define OMNIUI_PYBIND_DOC_ScrollingFrame_scrollX                                                                       \
    "The horizontal position of the scroll bar. When it's changed, the contents will be scrolled accordingly.\n"


#define OMNIUI_PYBIND_DOC_ScrollingFrame_scrollY                                                                       \
    "The vertical position of the scroll bar. When it's changed, the contents will be scrolled accordingly.\n"


#define OMNIUI_PYBIND_DOC_ScrollingFrame_scrollXMax "The max position of the horizontal scroll bar.\n"


#define OMNIUI_PYBIND_DOC_ScrollingFrame_scrollYMax "The max position of the vertical scroll bar.\n"


#define OMNIUI_PYBIND_DOC_ScrollingFrame_horizontalScrollBarPolicy                                                     \
    "This property holds the policy for the horizontal scroll bar.\n"


#define OMNIUI_PYBIND_DOC_ScrollingFrame_verticalScrollBarPolicy                                                       \
    "This property holds the policy for the vertical scroll bar.\n"


#define OMNIUI_PYBIND_DOC_ScrollingFrame_ScrollingFrame "Construct ScrollingFrame.\n"
