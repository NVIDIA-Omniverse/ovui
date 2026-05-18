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

#define OMNIUI_PYBIND_DOC_Line                                                                                         \
    "The Line widget provides a colored line to display.\n"                                                            \
    "\n"


#define OMNIUI_PYBIND_DOC_Line_setMouseHoveredFn                                                                       \
    "Sets the function that will be called when the user uses mouse enter/leave on the line. It's the override to prevent Widget from the bounding box logic. The function specification is: void onMouseHovered(bool hovered)\n"


#define OMNIUI_PYBIND_DOC_Line_setMousePressedFn                                                                                                                                                                                             \
    "Sets the function that will be called when the user presses the mouse button inside the widget. The function should be like this: void onMousePressed(float x, float y, int32_t button, omni::ui::KeyboardModifierFlags modifier)\n" \
    "It's the override to prevent the bounding box logic.\n"


#define OMNIUI_PYBIND_DOC_Line_setMouseReleasedFn                                                                      \
    "Sets the function that will be called when the user releases the mouse button if this button was pressed inside the widget. void onMouseReleased(float x, float y, int32_t button, omni::ui::KeyboardModifierFlags modifier)\n"


#define OMNIUI_PYBIND_DOC_Line_setMouseDoubleClickedFn                                                                 \
    "Sets the function that will be called when the user presses the mouse button twice inside the widget. The function specification is the same as in setMousePressedFn. void onMouseDoubleClicked(float x, float y, int32_t button, omni::ui::KeyboardModifierFlags modifier)\n"


#define OMNIUI_PYBIND_DOC_Line_setComputedContentWidth                                                                 \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget. Currently this widget can't be smaller than 1 pixel.\n"


#define OMNIUI_PYBIND_DOC_Line_setComputedContentHeight                                                                \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget. Currently this widget can't be smaller than 1 pixel.\n"


#define OMNIUI_PYBIND_DOC_Line_alignment                                                                               \
    "This property that holds the alignment of the Line can only be LEFT, RIGHT, V_CENTER, H_CENTER , BOTTOM, TOP. By default, the Line is H_Center.\n"


#define OMNIUI_PYBIND_DOC_Line_Line "Constructs Line.\n"
