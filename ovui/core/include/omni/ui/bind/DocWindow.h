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

#define OMNIUI_PYBIND_DOC_Window                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          \
    "The Window class represents a window in the underlying windowing system.\n"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          \
    "This window is a child window of main Kit window. And it can be docked.\n"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           \
    "Rasterization\n"                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     \
    "omni.ui generates vertices every frame to render UI elements. One of the features of the framework is the ability to bake a DrawList per window and reuse it if the content has not changed, which can significantly improve performance. However, in some cases, such as the Viewport window and Console window, it may not be possible to detect whether the window content has changed, leading to a frozen window. To address this problem, you can control the rasterization behavior by adjusting RasterPolicy. The RasterPolicy is an enumeration class that defines the rasterization behavior of a window. It has three possible values:\n" \
    "NEVER: Do not rasterize the widget at any time. ON_DEMAND: Rasterize the widget as soon as possible and always use the rasterized version. The widget will only be updated when the user calls invalidateRaster. AUTO: Automatically determine whether to rasterize the widget based on performance considerations. If necessary, the widget will be rasterized and updated when its content changes.\n"                                                                                                                                                                                                                                             \
    "To resolve the frozen window issue, you can manually set the RasterPolicy of the problematic window to Never. This will force the window to rasterize its content and use the rasterized version until the user explicitly calls invalidateRaster to request an update.\n"                                                                                                                                                                                                                                                                                                                                                                           \
    "window = ui.Window(\"Test window\", raster_policy=ui.RasterPolicy.NEVER)\n"


#define OMNIUI_PYBIND_DOC_Window_destroy "Removes all the callbacks and circular references.\n"


#define OMNIUI_PYBIND_DOC_Window_notifyAppWindowChange "Notifies the window that window set has changed.\n"


#define OMNIUI_PYBIND_DOC_Window_getWindowCallback "Returns window set draw callback pointer for the given UI window.\n"


#define OMNIUI_PYBIND_DOC_Window_moveToAppWindow "Moves the window to the specific OS window.\n"


#define OMNIUI_PYBIND_DOC_Window_getAppWindow "Current IAppWindow.\n"


#define OMNIUI_PYBIND_DOC_Window_setTopModal "Brings this window to the top level of modal windows.\n"


#define OMNIUI_PYBIND_DOC_Window_deferredDockIn                                                                                                                                \
    "Deferred docking. We need it when we want to dock windows before they were actually created. It's helpful when extension initialization, before any window is created.\n" \
    "\n"                                                                                                                                                                       \
    "\n"                                                                                                                                                                       \
    "### Arguments:\n"                                                                                                                                                         \
    "\n"                                                                                                                                                                       \
    "    `targetWindowTitle :`\n"                                                                                                                                              \
    "        Dock to window with this title when it appears.\n"                                                                                                                \
    "\n"                                                                                                                                                                       \
    "    `activeWindow :`\n"                                                                                                                                                   \
    "        Make target or this window active when docked.\n"


#define OMNIUI_PYBIND_DOC_Window_isValid "Indicates if the window was already destroyed.\n"


#define OMNIUI_PYBIND_DOC_Window_getRasterPolicy "Determine how the content of the window should be rastered.\n"


#define OMNIUI_PYBIND_DOC_Window_setRasterPolicy "Determine how the content of the window should be rastered.\n"


#define OMNIUI_PYBIND_DOC_Window_KeyPressed                                                                            \
    "Sets the function that will be called when the user presses the keyboard key on the focused window.\n"


#define OMNIUI_PYBIND_DOC_Window_title "This property holds the window's title.\n"


#define OMNIUI_PYBIND_DOC_Window_visible "This property holds whether the window is visible.\n"


#define OMNIUI_PYBIND_DOC_Window_frame "The main layout of this window.\n"


#define OMNIUI_PYBIND_DOC_Window_menuBar                                                                               \
    "The MenuBar for this Window, it is always present but hidden when the MENUBAR Flag is missing you need to use kWindowFlagMenuBar to show it.\n"


#define OMNIUI_PYBIND_DOC_Window_width "This property holds the window Width.\n"


#define OMNIUI_PYBIND_DOC_Window_heigh "This property holds the window Height.\n"


#define OMNIUI_PYBIND_DOC_Window_paddingX "This property set the padding to the frame on the X axis.\n"


#define OMNIUI_PYBIND_DOC_Window_paddingY "This property set the padding to the frame on the Y axis.\n"


#define OMNIUI_PYBIND_DOC_Window_focused "Read only property that is true when the window is focused.\n"


#define OMNIUI_PYBIND_DOC_Window_positionX                                                                             \
    "This property set/get the position of the window in the X Axis. The default is kWindowFloatInvalid because we send the window position to the underlying system only if the position is explicitly set by the user. Otherwise the underlying system decides the position.\n"


#define OMNIUI_PYBIND_DOC_Window_positionY                                                                             \
    "This property set/get the position of the window in the Y Axis. The default is kWindowFloatInvalid because we send the window position to the underlying system only if the position is explicitly set by the user. Otherwise the underlying system decides the position.\n"


#define OMNIUI_PYBIND_DOC_Window_setPosition                                                                           \
    "This property set/get the position of the window in both axis calling the property.\n"


#define OMNIUI_PYBIND_DOC_Window_flags "This property set the Flags for the Window.\n"


#define OMNIUI_PYBIND_DOC_Window_noTabBar                                                                              \
    "setup the visibility of the TabBar Handle, this is the small triangle at the corner of the view If it is not shown then it is not possible to undock that window and it need to be closed/moved programatically\n"


#define OMNIUI_PYBIND_DOC_Window_tabBarTooltip "This property sets the tooltip when hovering over window's tabbar.\n"  \


#define OMNIUI_PYBIND_DOC_Window_autoResize "setup the window to resize automatically based on its content\n"


#define OMNIUI_PYBIND_DOC_Window_fillAppWindow                                                                         \
    "When true, the window automatically fills the entire application window every frame. "                             \
    "Position is set to (0, 0) and size matches the main viewport. "                                                   \
    "Intended for standalone single-window applications.\n"


#define OMNIUI_PYBIND_DOC_Window_docked                                                                                \
    "Has true if this window is docked. False otherwise. It's a read-only property.\n"


#define OMNIUI_PYBIND_DOC_Window_selectedInDock                                                                        \
    "Has true if this window is currently selected in the dock. False otherwise. It's a read-only property.\n"


#define OMNIUI_PYBIND_DOC_Window_dockInWindow                                                                          \
    "place the window in a specific docking position based on a target window name. We will find the target window dock node and insert this window in it, either by spliting on ratio or on top if the window is not found false is return, otherwise true\n"


#define OMNIUI_PYBIND_DOC_Window_moveToNewOSWindow "Move the Window Callback to a new OS Window.\n"


#define OMNIUI_PYBIND_DOC_Window_moveToMainOSWindow                                                                    \
    "Bring back the Window callback to the Main Window and destroy the Current OS Window.\n"


#define OMNIUI_PYBIND_DOC_Window_exclusiveKeyboard                                                                     \
    "When true, only the current window will receive keyboard events when it's focused. It's useful to override the global key bindings.\n"


#define OMNIUI_PYBIND_DOC_Window_detachable "If the window is able to be separated from the main application window.\n"


#define OMNIUI_PYBIND_DOC_Window_virtual "Vitrual window is the window that is rendered to internal buffer.\n"


#define OMNIUI_PYBIND_DOC_Window_focusPolicy "How the Window gains focus.\n"


#define OMNIUI_PYBIND_DOC_Window_getDpiScale                                                                           \
    "Get DPI scale currently associated to the current window's viewport. It's static since currently we can only have one window.\n"


#define OMNIUI_PYBIND_DOC_Window_getMainWindowWidth "Get the width in points of the current main window.\n"


#define OMNIUI_PYBIND_DOC_Window_getMainWindowHeight "Get the height in points of the current main window.\n"


#define OMNIUI_PYBIND_DOC_Window_dockWindowInWindow                                                                    \
    "place a named window in a specific docking position based on a target window name. We will find the target window dock node and insert this named window in it, either by spliting on ratio or on top if the windows is not found false is return, otherwise true\n"


#define OMNIUI_PYBIND_DOC_Window_Window                                                                                \
    "Construct the window, add it to the underlying windowing system, and makes it appear.\n"                          \
    "\n"                                                                                                               \
    "\n"                                                                                                               \
    "### Arguments:\n"                                                                                                 \
    "\n"                                                                                                               \
    "    `title :`\n"                                                                                                  \
    "        The window title. It's also used as an internal window ID.\n"                                             \
    "\n"                                                                                                               \
    "    `dockPrefence :`\n"                                                                                           \
    "        In the old Kit determines where the window should be docked. In Kit Next it's unused.\n"


#define OMNIUI_PYBIND_DOC_Window__drawWindow "Used as a callback of the underlying windowing system. Calls draw().\n"
