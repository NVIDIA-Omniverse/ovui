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

//! @file
//!
//! @brief omni::ui Workspace
#pragma once

#include "Api.h"
#include "Types.h"
#include "WindowHandle.h"

#include <cstdint>
#include <functional>
#include <memory>
#include <stack>
#include <string>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

namespace windowmanager
{
class IWindowCallback;
}

class WindowHandle;
class Window;
class ToolBar;

/**
 * @brief Workspace object provides access to the windows in Kit.
 *
 * TODO: It's more like a namespace because all the methods are static. But the idea is to have it as a singleton, and
 * it will allow using it as the abstract factory for many systems (Kit full and Kit mini for example).
 */
class Workspace
{
public:
    class AppWindowGuard;

    /**
     * @brief Singleton that tracks the current application window.
     */
    class AppWindow
    {
    public:
        OMNIUI_API
        static AppWindow& instance();

        AppWindowHandle getCurrent();

    private:
        friend class AppWindowGuard;

        AppWindow() = default;
        ~AppWindow() = default;
        AppWindow(const AppWindow&) = delete;
        AppWindow& operator=(const AppWindow&) = delete;

        void push(AppWindowHandle window);
        void pop();

        std::stack<AppWindowHandle> m_stack;
    };

    /**
     * @brief Guard that pushes the current application window to class AppWindow when created and pops when destroyed.
     */
    class AppWindowGuard
    {
    public:
        AppWindowGuard(AppWindowHandle window);
        ~AppWindowGuard();
    };

    Workspace() = delete;

    /**
     * @brief Returns current DPI Scale.
     */
    OMNIUI_API
    static float getDpiScale();

    /**
     * @brief Returns the list of windows ordered from back to front.
     *
     * If the window is an ovui window, it can be upcasted.
     */
    OMNIUI_API
    static std::vector<std::shared_ptr<WindowHandle>> getWindows();

    /**
     * @brief Find Window by name.
     */
    OMNIUI_API
    static std::shared_ptr<WindowHandle> getWindow(const std::string& title);

    /**
     * @brief Find Window by window callback.
     */
    OMNIUI_API
    static std::shared_ptr<WindowHandle> getWindowFromCallback(const windowmanager::IWindowCallback* callback);

    /**
     * @brief Get all the windows that docked with the given widow.
     */
    OMNIUI_API
    static std::vector<std::shared_ptr<WindowHandle>> getDockedNeighbours(const std::shared_ptr<WindowHandle>& member);

    /**
     * @brief Get currently selected window inedx from the given dock id.
     */
    OMNIUI_API
    static uint32_t getSelectedWindowIndex(uint32_t dockId);

    /**
     * @brief Undock all.
     */
    OMNIUI_API
    static void clear();

    /**
     * @brief Get the width in points of the current main window. Returns 0 if no main window is found.
     */
    OMNIUI_API
    static float getMainWindowWidth();

    /**
     * @brief Get the height in points of the current main window. Returns 0 if no main window is found.
     */
    OMNIUI_API
    static float getMainWindowHeight();

    /**
     * @brief Get all the windows of the given dock ID
     */
    OMNIUI_API
    static std::vector<std::shared_ptr<WindowHandle>> getDockedWindows(uint32_t dockId);

    /**
     * @brief Return the parent Dock Node ID
     *
     * @param dockId the child Dock Node ID to get parent
     */
    OMNIUI_API
    static uint32_t getParentDockId(uint32_t dockId);

    /**
     * @brief Get two dock children of the given dock ID.
     *
     * @return true if the given dock ID has children
     * @param dockId the given dock ID
     * @param first output. the first child dock ID
     * @param second output. the second child dock ID
     */
    OMNIUI_API
    static bool getDockNodeChildrenId(uint32_t dockId, uint32_t& first, uint32_t& second);

    /**
     * @brief Returns the position of the given dock ID. Left/Right/Top/Bottom
     */
    OMNIUI_API
    static WindowHandle::DockPosition getDockPosition(uint32_t dockId);

    /**
     * @brief Returns the width of the docking node.
     *
     * @param dockId the given dock ID
     */
    OMNIUI_API
    static float getDockIdWidth(uint32_t dockId);

    /**
     * @brief Returns the height of the docking node.
     *
     * It's different from the window height because it considers dock tab bar.
     *
     * @param dockId the given dock ID
     */
    OMNIUI_API
    static float getDockIdHeight(uint32_t dockId);

    /**
     * @brief Set the width of the dock node.
     *
     * It also sets the width of parent nodes if necessary and modifies the
     * width of siblings.
     *
     * @param dockId the given dock ID
     * @param width the given width
     */
    OMNIUI_API
    static void setDockIdWidth(uint32_t dockId, float width);

    /**
     * @brief Set the height of the dock node.
     *
     * It also sets the height of parent nodes if necessary and modifies the
     * height of siblings.
     *
     * @param dockId the given dock ID
     * @param height the given height
     */
    OMNIUI_API
    static void setDockIdHeight(uint32_t dockId, float height);

    /**
     * @brief Makes the window visible or create the window with the callback provided with set_show_window_fn.
     *
     * @return true if the window is already created, otherwise it's necessary to wait one frame
     * @param title the given window title
     * @param show true to show, false to hide
     */
    OMNIUI_API
    static bool showWindow(const std::string& title, bool show = true);

    /**
     * @brief Addd the callback that is triggered when a new window is created
     */
    OMNIUI_API
    static void setWindowCreatedCallback(
        std::function<void(const std::shared_ptr<WindowHandle>& window)> windowCreatedCallbackFn);

    /**
     * @brief Add the callback to create a window with the given title. When the callback's argument is true, it's
     * necessary to create the window. Otherwise remove.
     */
    OMNIUI_API
    static void setShowWindowFn(const std::string& title, std::function<void(bool)> showWindowFn);

    /**
     * @brief Get all window titles that have a show window callback.
     */
    OMNIUI_API
    static std::vector<std::string> getShowWindowTitles();

    /**
     * @brief Add the callback that is triggered when a window's visibility changed
    */
    OMNIUI_API
    static uint32_t setWindowVisibilityChangedCallback(std::function<void(const std::string& title, bool visible)> windowVisibilityChangedCallbackFn);

    /**
     * @brief Remove the callback that is triggered when a window's visibility changed
    */
    OMNIUI_API
    static void removeWindowVisibilityChangedCallback(uint32_t id);
    /**
     * @brief Call it from inside each windows' setVisibilityChangedFn to triggered VisibilityChangedCallback.
     */
    OMNIUI_API
    static void onWindowVisibilityChanged(const std::string& title, bool visible);
private:
    friend class Window;
    friend class ToolBar;

    /**
     * @brief Register Window, so it's possible to return it in getWindows. It's called by Window creator.
     */
    OMNIUI_API
    static void RegisterWindow(const std::shared_ptr<Window>& window);

    /**
     * @brief Deregister window. It's called by Window destructor.
     */
    OMNIUI_API
    static void OmitWindow(const Window* window);

    /**
     * @brief
     *
     */
    static std::vector<std::shared_ptr<WindowHandle>> _getWindows(const void* windowsStorage,
                                                                  bool considerRegistered = false);
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
