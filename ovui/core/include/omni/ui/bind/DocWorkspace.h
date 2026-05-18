/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#define OMNIUI_PYBIND_DOC_Workspace "Workspace object provides access to the windows in Kit.\n"


#define OMNIUI_PYBIND_DOC_Workspace_getDpiScale "Returns current DPI Scale.\n"


#define OMNIUI_PYBIND_DOC_Workspace_getWindows                                                                         \
    "Returns the list of windows ordered from back to front.\n"                                                        \
    "If the window is an ovui window, it can be upcasted.\n"


#define OMNIUI_PYBIND_DOC_Workspace_getWindow "Find Window by name.\n"


#define OMNIUI_PYBIND_DOC_Workspace_getWindowFromCallback "Find Window by window callback.\n"


#define OMNIUI_PYBIND_DOC_Workspace_getDockedNeighbours "Get all the windows that docked with the given widow.\n"


#define OMNIUI_PYBIND_DOC_Workspace_getSelectedWindowIndex                                                             \
    "Get currently selected window inedx from the given dock id.\n"


#define OMNIUI_PYBIND_DOC_Workspace_clear "Undock all.\n"


#define OMNIUI_PYBIND_DOC_Workspace_getMainWindowWidth "Get the width in points of the current main window.\n"


#define OMNIUI_PYBIND_DOC_Workspace_getMainWindowHeight "Get the height in points of the current main window.\n"


#define OMNIUI_PYBIND_DOC_Workspace_getDockedWindows "Get all the windows of the given dock ID.\n"


#define OMNIUI_PYBIND_DOC_Workspace_getParentDockId                                                                    \
    "Return the parent Dock Node ID.\n"                                                                                \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `dockId :`\n"                                                                                                 \
    "        the child Dock Node ID to get parent\n"


#define OMNIUI_PYBIND_DOC_Workspace_getDockNodeChildrenId                                                              \
    "Get two dock children of the given dock ID.\n"                                                                    \
    "true if the given dock ID has children\n"                                                                         \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `dockId :`\n"                                                                                                 \
    "        the given dock ID\n"                                                                                      \
    "\n"                                                                                                               \
    "    `first :`\n"                                                                                                  \
    "        output. the first child dock ID\n"                                                                        \
    "\n"                                                                                                               \
    "    `second :`\n"                                                                                                 \
    "        output. the second child dock ID\n"


#define OMNIUI_PYBIND_DOC_Workspace_getDockPosition                                                                    \
    "Returns the position of the given dock ID. Left/Right/Top/Bottom.\n"


#define OMNIUI_PYBIND_DOC_Workspace_getDockIdWidth                                                                     \
    "Returns the width of the docking node.\n"                                                                         \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `dockId :`\n"                                                                                                 \
    "        the given dock ID\n"


#define OMNIUI_PYBIND_DOC_Workspace_getDockIdHeight                                                                    \
    "Returns the height of the docking node.\n"                                                                        \
    "It's different from the window height because it considers dock tab bar.\n"                                       \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `dockId :`\n"                                                                                                 \
    "        the given dock ID\n"


#define OMNIUI_PYBIND_DOC_Workspace_setDockIdWidth                                                                     \
    "Set the width of the dock node.\n"                                                                                \
    "It also sets the width of parent nodes if necessary and modifies the width of siblings.\n"                        \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `dockId :`\n"                                                                                                 \
    "        the given dock ID\n"                                                                                      \
    "\n"                                                                                                               \
    "    `width :`\n"                                                                                                  \
    "        the given width\n"


#define OMNIUI_PYBIND_DOC_Workspace_setDockIdHeight                                                                    \
    "Set the height of the dock node.\n"                                                                               \
    "It also sets the height of parent nodes if necessary and modifies the height of siblings.\n"                      \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `dockId :`\n"                                                                                                 \
    "        the given dock ID\n"                                                                                      \
    "\n"                                                                                                               \
    "    `height :`\n"                                                                                                 \
    "        the given height\n"


#define OMNIUI_PYBIND_DOC_Workspace_showWindow                                                                         \
    "Makes the window visible or create the window with the callback provided with set_show_window_fn.\n"              \
    "true if the window is already created, otherwise it's necessary to wait one frame\n"                              \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `title :`\n"                                                                                                  \
    "        the given window title\n"                                                                                 \
    "\n"                                                                                                               \
    "    `show :`\n"                                                                                                   \
    "        true to show, false to hide\n"


#define OMNIUI_PYBIND_DOC_Workspace_setWindowCreatedCallback                                                           \
    "Addd the callback that is triggered when a new window is created.\n"

#define OMNIUI_PYBIND_DOC_Workspace_setWindowVisibilityChangedCallback                                                 \
    "Add the callback that is triggered when window's visibility changed.\n"

#define OMNIUI_PYBIND_DOC_Workspace_removeWindowVisibilityChangedCallback                                              \
    "Remove the callback that is triggered when window's visibility changed.\n"

#define OMNIUI_PYBIND_DOC_Workspace_setShowWindowFn                                                                    \
    "Add the callback to create a window with the given title. When the callback's argument is true, it's necessary to create the window. Otherwise remove.\n"

#define OMNIUI_PYBIND_DOC_Workspace_getShowWindowTitles                                                                     \
    "Get all window titles that have a show window callback.\n"

#define OMNIUI_PYBIND_DOC_Workspace_RegisterWindow                                                                     \
    "Register Window, so it's possible to return it in getWindows. It's called by Window creator.\n"


#define OMNIUI_PYBIND_DOC_Workspace_OmitWindow "Deregister window. It's called by Window destructor.\n"
