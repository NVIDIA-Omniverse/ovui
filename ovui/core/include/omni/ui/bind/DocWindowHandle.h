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

#define OMNIUI_PYBIND_DOC_WindowHandle                                                                                                                                \
    "WindowHandle is a handle object to control any of the windows in Kit. It can be created any time, and if it's destroyed, the source window doesn't disappear.\n" \
    "\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_getTitle "The title of the window.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_getPositionX "The position of the window in points.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_setPositionX "Set the position of the window in points.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_getPositionY "The position of the window in points.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_setPositionY "Set the position of the window in points.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_getWidth "The width of the window in points.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_setWidth "Set the width of the window in points.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_getHeight "The height of the window in points.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_setHeight "Set the height of the window in points.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_isVisible "Returns whether the window is visible.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_setVisible                                                                      \
    "Set the visibility of the windows. It's the way to hide the window.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_isDockTabBarVisible "Checks if the current docking space has the tab bar.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_setDockTabBarVisible                                                            \
    "Sets the visibility of the current docking space tab bar. Unlike disabled, invisible tab bar can be shown with a little triangle in top left corner of the window.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_isDockTabBarEnabled                                                             \
    "Checks if the current docking space is disabled. The disabled docking tab bar can't be shown by the user.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_setDockTabBarEnabled                                                            \
    "Sets the visibility of the current docking space tab bar. The disabled docking tab bar can't be shown by the user.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_undock "Undock the window and make it floating.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_dockIn                                                                          \
    "Dock the window to the existing window. It can split the window to two parts or it can convert the window to a docking tab.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_getDockOrder "The position of the window in the dock.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_setDockOrder "Set the position of the window in the dock.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_isDocked "True if this window is docked. False otherwise.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_getDockId "Returns ID of the dock node this window is docked to.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_focus                                                                           \
    "Brings the window to the top. If it's a docked window, it makes the window currently visible in the dock.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_isSelectedInDock                                                                \
    "Return true is the window is the current window in the docking area.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_notifyAppWindowChange                                                           \
    "Notifies the UI window that the AppWindow it attached to has changed.\n"


#define OMNIUI_PYBIND_DOC_WindowHandle_WindowHandle                                                                    \
    "Create a handle with the given ID.\n"                                                                             \
    "Only Workspace can create this object.\n"
