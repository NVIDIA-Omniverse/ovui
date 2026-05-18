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

#define OMNIUI_PYBIND_DOC_Menu                                                                                         \
    "The Menu class provides a menu widget for use in menu bars, context menus, and other popup menus.\n"              \
    "It can be either a pull-down menu in a menu bar or a standalone context menu. Pull-down menus are shown by the menu bar when the user clicks on the respective item. Context menus are usually invoked by some special keyboard key or by right-clicking.\n"


#define OMNIUI_PYBIND_DOC_Menu_addChild "Reimplemented adding a widget to this Menu.\n"


#define OMNIUI_PYBIND_DOC_Menu_clear "Reimplemented removing all the child widgets from this Menu.\n"


#define OMNIUI_PYBIND_DOC_Menu_setComputedContentWidth                                                                 \
    "Reimplemented the method to indicate the width hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_Menu_setComputedContentHeight                                                                \
    "Reimplemented the method to indicate the height hint that represents the preferred size of the widget.\n"


#define OMNIUI_PYBIND_DOC_Menu_cascadeStyle                                                                            \
    "It's called when the style is changed. It should be propagated to children to make the style cached and available to children.\n"


#define OMNIUI_PYBIND_DOC_Menu_show                                                                                    \
    "Create a popup window and show the menu in it. It's usually used for context menus that are typically invoked by some special keyboard key or by right-clicking.\n"


#define OMNIUI_PYBIND_DOC_Menu_showAt                                                                                  \
    "Create a popup window and show the menu in it. This enable to popup the menu at specific position. X and Y are in points to make it easier to the Python users.\n"


#define OMNIUI_PYBIND_DOC_Menu_tearAt                                                                                  \
    "Create a popup window and show the menu in it. This tear the menu at specific position. X and Y are in points to make it easier to the Python users.\n"


#define OMNIUI_PYBIND_DOC_Menu_hide                                                                                    \
    "Close the menu window. It only works for pop-up context menu and for teared off menu.\n"


#define OMNIUI_PYBIND_DOC_Menu_invalidate "Make Menu dirty so onBuild will be executed to replace the children.\n"


#define OMNIUI_PYBIND_DOC_Menu_shown "If the pulldown menu is shown on the screen.\n"


#define OMNIUI_PYBIND_DOC_Menu_tearable "The ability to tear the window off.\n"


#define OMNIUI_PYBIND_DOC_Menu_teared "If the window is teared off.\n"


#define OMNIUI_PYBIND_DOC_Menu_OnBuild "Called to re-create new children.\n"


#define OMNIUI_PYBIND_DOC_Menu_getCurrent "Return the menu that is currently shown.\n"


#define OMNIUI_PYBIND_DOC_Menu_Menu                                                                                    \
    "Construct Menu.\n"                                                                                                \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `text :`\n"                                                                                                   \
    "        The text for the menu.\n"
