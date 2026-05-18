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

#define OMNIUI_PYBIND_DOC_BezierCurve                                                                                  \
    "Smooth curve that can be scaled infinitely.\n"                                                                    \
    "\n"


#define OMNIUI_PYBIND_DOC_BezierCurve_setMouseHoveredFn                                                                \
    "Sets the function that will be called when the user use mouse enter/leave on the line. It's the override to prevent Widget from the bounding box logic. The function specification is: void onMouseHovered(bool hovered)\n"


#define OMNIUI_PYBIND_DOC_BezierCurve_setMousePressedFn                                                                                                                                                                                      \
    "Sets the function that will be called when the user presses the mouse button inside the widget. The function should be like this: void onMousePressed(float x, float y, int32_t button, omni::ui::KeyboardModifierFlags modifier)\n" \
    "It's the override to prevent the bounding box logic.\n"                                                                                                                                                                                 \
    "Where button is the number of the mouse button pressed modifier is the flag for the keyboard modifier key\n"


#define OMNIUI_PYBIND_DOC_BezierCurve_setMouseReleasedFn                                                               \
    "Sets the function that will be called when the user releases the mouse button if this button was pressed inside the widget. void onMouseReleased(float x, float y, int32_t button, omni::ui::KeyboardModifierFlags modifier)\n"


#define OMNIUI_PYBIND_DOC_BezierCurve_setMouseDoubleClickedFn                                                          \
    "Sets the function that will be called when the user presses the mouse button twice inside the widget. The function specification is the same as in setMousePressedFn. void onMouseDoubleClicked(float x, float y, int32_t button, omni::ui::KeyboardModifierFlags modifier)\n"


#define OMNIUI_PYBIND_DOC_BezierCurve_startTangentWidth                                                                \
    "This property holds the X coordinate of the start of the curve relative to the width bound of the curve.\n"


#define OMNIUI_PYBIND_DOC_BezierCurve_startTangentHeight                                                               \
    "This property holds the Y coordinate of the start of the curve relative to the width bound of the curve.\n"


#define OMNIUI_PYBIND_DOC_BezierCurve_endTangentWidth                                                                  \
    "This property holds the X coordinate of the end of the curve relative to the width bound of the curve.\n"


#define OMNIUI_PYBIND_DOC_BezierCurve_endTangentHeight                                                                 \
    "This property holds the Y coordinate of the end of the curve relative to the width bound of the curve.\n"


#define OMNIUI_PYBIND_DOC_BezierCurve_BezierCurve "Initialize the curve.\n"
