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

#include "Api.h"
#include "Callback.h"
#include "Property.h"
#include "RasterPolicy.h"
#include "WindowHandle.h"
#include "Workspace.h"
#include "windowmanager/WindowManagerUtils.h"

#include "Types.h"

#include <float.h>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <utility>

namespace omni
{
namespace ui
{
namespace windowmanager
{
class IWindowCallback;
}
}
}

OMNIUI_NAMESPACE_OPEN_SCOPE

class Frame;
class MenuBar;

/**
 * @brief The Window class represents a window in the underlying windowing system.
 *
 * This window is a child window of main Kit window. And it can be docked.
 *
 * Rasterization
 *
 * omni.ui generates vertices every frame to render UI elements. One of the
 * features of the framework is the ability to bake a DrawList per window and
 * reuse it if the content has not changed, which can significantly improve
 * performance. However, in some cases, such as the Viewport window and Console
 * window, it may not be possible to detect whether the window content has
 * changed, leading to a frozen window. To address this problem, you can control
 * the rasterization behavior by adjusting RasterPolicy. The RasterPolicy is an
 * enumeration class that defines the rasterization behavior of a window. It has
 * three possible values:
 *
 * NEVER: Do not rasterize the widget at any time.
 * ON_DEMAND: Rasterize the widget as soon as possible and always use the
 * rasterized version. The widget will only be updated when the user calls
 * invalidateRaster.
 * AUTO: Automatically determine whether to rasterize the widget based on
 * performance considerations. If necessary, the widget will be rasterized and
 * updated when its content changes.
 *
 * To resolve the frozen window issue, you can manually set the RasterPolicy of
 * the problematic window to Never. This will force the window to rasterize its
 * content and use the rasterized version until the user explicitly calls
 * invalidateRaster to request an update.
 *
 * window = ui.Window("Test window", raster_policy=ui.RasterPolicy.NEVER)
 */
class OMNIUI_CLASS_API Window : public std::enable_shared_from_this<Window>,
                                public WindowHandle,
                                protected CallbackHelper<Window>
{
public:
    typedef uint32_t Flags;

    static constexpr Flags kWindowFlagNone = 0;
    static constexpr Flags kWindowFlagNoTitleBar = (1 << 0);
    static constexpr Flags kWindowFlagNoResize = (1 << 1);
    static constexpr Flags kWindowFlagNoMove = (1 << 2);
    static constexpr Flags kWindowFlagNoScrollbar = (1 << 3);
    static constexpr Flags kWindowFlagNoScrollWithMouse = (1 << 4);
    static constexpr Flags kWindowFlagNoCollapse = (1 << 5);
    static constexpr Flags kWindowFlagNoBackground = 1 << 7;
    static constexpr Flags kWindowFlagNoSavedSettings = (1 << 8);
    static constexpr Flags kWindowFlagNoMouseInputs = 1 << 9;
    static constexpr Flags kWindowFlagMenuBar = 1 << 10;
    static constexpr Flags kWindowFlagShowHorizontalScrollbar = (1 << 11);
    static constexpr Flags kWindowFlagNoFocusOnAppearing = (1 << 12);
    static constexpr Flags kWindowFlagForceVerticalScrollbar = (1 << 14);
    static constexpr Flags kWindowFlagForceHorizontalScrollbar = (1 << 15);
    static constexpr Flags kWindowFlagNoDocking = (1 << 21);
    static constexpr Flags kWindowFlagPopup = (1 << 26);
    static constexpr Flags kWindowFlagModal = (1 << 27);
    static constexpr Flags kWindowFlagNoClose = (1 << 31);

    static constexpr float kWindowFloatInvalid = FLT_MAX;

    // this will need to be reviewed, it is not clear in the future we can really have known position for docking
    enum class DockPreference : uint8_t
    {
        eDisabled,
        eMain,
        eRight,
        eLeft,
        eRightTop,
        eRightBottom,
        eLeftBottom
    };

    enum class DockPolicy : uint8_t
    {
        eDoNothing,
        eCurrentWindowIsActive,
        eTargetWindowIsActive
    };

    enum class FocusPolicy : uint8_t
    {
        eFocusOnLeftMouseDown, // Focus Window on left mouse down and right-click-up.
        eFocusOnAnyMouseDown,  // Focus Window on any mouse down.
        eFocusOnHover,         // Focus Window when mouse hovered over it.

        // Default to existing behavior: eFocusOnLeftMouseDown
        eDefault = eFocusOnLeftMouseDown,
    };

    virtual ~Window();

    /**
     * @brief Removes all the callbacks and circular references.
     */
    OMNIUI_API
    virtual void destroy();

    // We need it to make sure it's created as a shared pointer.
    template <typename... Args>
    static std::shared_ptr<Window> create(Args&&... args)
    {
        /* make_shared doesn't work because the constructor is protected: */
        /* auto ptr = std::make_shared<This>(std::forward<Args>(args)...); */
        /* TODO: Find the way to use make_shared */
        auto window = std::shared_ptr<Window>{ new Window{ std::forward<Args>(args)... } };
        Workspace::RegisterWindow(window);
        return window;
    }

    /**
     * @brief Notifies the window that window set has changed.
     *
     * \internal
     * TODO: We probably don't need it.
     * \endinternal
     */
    OMNIUI_API
    void notifyAppWindowChange(AppWindowHandle newAppWindow) override;

    /**
     * @brief Returns window set draw callback pointer for the given UI window.
     *
     * \internal
     * TODO: We probably don't need it.
     * \endinternal
     */
    OMNIUI_API
    windowmanager::IWindowCallback* getWindowCallback() const;

    /**
     * @brief Moves the window to the specific OS window.
     */
    OMNIUI_API
    void moveToAppWindow(AppWindowHandle newAppWindow);

    /**
     * @brief Current IAppWindow
     */
    OMNIUI_API
    AppWindowHandle getAppWindow() const;

    /**
     * @brief Brings this window to the top level of modal windows.
     */
    OMNIUI_API
    void setTopModal() const;

    /**
     * @brief Get DPI scale currently associated to the current window's viewport. It's static since currently we can
     * only have one window.
     *
     * \internal
     * TODO: class MainWindow
     * \endinternal
     */
    OMNIUI_API
    static float getDpiScale();

    /**
     * @brief Get the width in points of the current main window.
     *
     * \internal
     * TODO: class MainWindow
     * \endinternal
     */
    OMNIUI_API
    static float getMainWindowWidth();

    /**
     * @brief Get the height in points of the current main window.
     *
     * \internal
     * TODO: class MainWindow
     * \endinternal
     */
    OMNIUI_API
    static float getMainWindowHeight();

    /**
     * @brief Deferred docking. We need it when we want to dock windows before they were actually created. It's helpful
     * when extension initialization, before any window is created.
     *
     * @param[in] targetWindowTitle Dock to window with this title when it appears.
     * @param[in] activeWindow Make target or this window active when docked.
     */
    OMNIUI_API
    virtual void deferredDockIn(const std::string& targetWindowTitle, DockPolicy activeWindow = DockPolicy::eDoNothing);

    /**
     * @brief Indicates if the window was already destroyed.
     */
    OMNIUI_API
    bool isValid() const;

    /**
     * @brief Determine how the content of the window should be rastered.
     */
    OMNIUI_API
    RasterPolicy getRasterPolicy() const;

    /**
     * @brief Determine how the content of the window should be rastered.
     */
    OMNIUI_API
    void setRasterPolicy(RasterPolicy policy);

    /**
     * @brief Sets the function that will be called when the user presses the keyboard key on the focused window.
     */
    OMNIUI_CALLBACK(KeyPressed, void, int32_t, KeyboardModifierFlags, bool);

    /**
     * @brief This property holds the window's title.
     */
    OMNIUI_PROPERTY(std::string, title, READ_VALUE, getTitle, WRITE, setTitle);

    /**
     * @brief This property holds whether the window is visible.
     */
    OMNIUI_PROPERTY(bool, visible, DEFAULT, true, READ_VALUE, isVisible, WRITE, setVisible, NOTIFY, setVisibilityChangedFn);

    /**
     * @brief The main layout of this window.
     */
    OMNIUI_PROPERTY(std::shared_ptr<Frame>, frame, READ, getFrame, PROTECTED, WRITE, setFrame);

    /**
     * @brief The MenuBar for this Window, it is always present but hidden when the MENUBAR Flag is missing
     * you need to use kWindowFlagMenuBar to show it
     */
    OMNIUI_PROPERTY(std::shared_ptr<MenuBar>, menuBar, READ, getMenuBar, PROTECTED, WRITE, setMenuBar);

    /**
     * @brief This property holds the window Width
     */
    OMNIUI_PROPERTY(float, width, DEFAULT, 400, READ_VALUE, getWidth, WRITE, setWidth, NOTIFY, setWidthChangedFn);

    /**
     * @brief This property holds the window Height
     */
    OMNIUI_PROPERTY(float, height, DEFAULT, 600, READ_VALUE, getHeight, WRITE, setHeight, NOTIFY, setHeightChangedFn);

    /**
     * @brief This property set the padding to the frame on the X axis
     */
    OMNIUI_PROPERTY(float, paddingX, DEFAULT, 4.f, READ, getPaddingX, WRITE, setPaddingX);

    /**
     * @brief This property set the padding to the frame on the Y axis
     */
    OMNIUI_PROPERTY(float, paddingY, DEFAULT, 4.f, READ, getPaddingY, WRITE, setPaddingY);

    /**
     * @brief Read only property that is true when the window is focused.
     */
    OMNIUI_PROPERTY(
        bool, focused, DEFAULT, false, READ, getFocused, NOTIFY, setFocusedChangedFn, PROTECTED, WRITE, _setFocused);

    /**
     * @brief This property set/get the position of the window in the X Axis.
     * The default is kWindowFloatInvalid because we send the window position to the underlying system only if the
     * position is explicitly set by the user. Otherwise the underlying system decides the position.
     */
    OMNIUI_PROPERTY(float,
                    positionX,
                    DEFAULT,
                    kWindowFloatInvalid,
                    READ_VALUE,
                    getPositionX,
                    WRITE,
                    setPositionX,
                    NOTIFY,
                    setPositionXChangedFn);

    /**
     * @brief This property set/get the position of the window in the Y Axis.
     * The default is kWindowFloatInvalid because we send the window position to the underlying system only if the
     * position is explicitly set by the user. Otherwise the underlying system decides the position.
     */
    OMNIUI_PROPERTY(float,
                    positionY,
                    DEFAULT,
                    kWindowFloatInvalid,
                    READ_VALUE,
                    getPositionY,
                    WRITE,
                    setPositionY,
                    NOTIFY,
                    setPositionYChangedFn);

    /**
     * @brief This property set/get the position of the window in both axis calling the property
     */
    OMNIUI_API
    void setPosition(float x, float y);

    /**
     * @brief This property set the Flags for the Window
     */
    OMNIUI_PROPERTY(Flags, flags, DEFAULT, kWindowFlagNone, READ, getFlags, WRITE, setFlags, NOTIFY, setFlagsChangedFn);

    /**
     * @brief setup the visibility of the TabBar Handle, this is the small triangle at the corner of the view
     * If it is not shown then it is not possible to undock that window and it need to be closed/moved programatically
     *
     */
    OMNIUI_PROPERTY(bool, noTabBar, DEFAULT, false, READ, getNoTabBar, WRITE, setNoTabBar);

    /**
     * @brief This property holds the tooltip when user hovers over the window's TabBar
     */
    OMNIUI_PROPERTY(std::string, tabBarTooltip, READ_VALUE, getTabBarTooltip, WRITE, setTabBarTooltip);

    /**
     * @brief setup the window to resize automatically based on its content
     *
     */
    OMNIUI_PROPERTY(bool, autoResize, DEFAULT, false, READ, getAutoResize, WRITE, setAutoResize);

    /**
     * @brief Has true if this window is docked. False otherwise. It's a read-only property.
     */
    OMNIUI_PROPERTY(
        bool, docked, DEFAULT, false, READ_VALUE, isDocked, NOTIFY, setDockedChangedFn, PROTECTED, WRITE, setDocked);

    /**
     * @brief Has true if this window is currently selected in the dock. False otherwise. It's a read-only property.
     */
    OMNIUI_PROPERTY(bool,
                    selectedInDock,
                    DEFAULT,
                    false,
                    READ_VALUE,
                    isSelectedInDock,
                    NOTIFY,
                    setSelectedInDockChangedFn,
                    PROTECTED,
                    WRITE,
                    setSelectedInDock);

    /**
     * @brief place the window in a specific docking position based on a target window name.
     * We will find the target window dock node and insert this window in it, either by spliting on ratio or on top
     * if the window is not found false is return, otherwise true
     *
     */
    OMNIUI_API
    bool dockInWindow(const std::string& windowName, const Window::DockPosition& dockPosition, const float& ratio = 0.5);

    /**
     * @brief place a named window in a specific docking position based on a target window name.
     * We will find the target window dock node and insert this named window in it, either by spliting on ratio or on
     * top if the windows is not found false is return, otherwise true
     *
     */
    OMNIUI_API
    static bool dockWindowInWindow(const std::string& windowName,
                                   const std::string& targetWindowName,
                                   const Window::DockPosition& dockPosition,
                                   const float& ratio = 0.5);

    /**
     * @brief Move the Window Callback to a new OS Window
     */
    OMNIUI_API
    bool moveToNewOSWindow();

    /**
     * @brief Bring back the Window callback to the Main Window and destroy the Current OS Window
     */
    OMNIUI_API
    void moveToMainOSWindow();

    /**
     * @brief When true, only the current window will receive keyboard events when it's focused. It's useful to override
     * the global key bindings.
     */
    OMNIUI_PROPERTY(bool, exclusiveKeyboard, DEFAULT, false, READ_VALUE, isExclusiveKeyboard, WRITE, setExclusiveKeyboard);

    /**
     * @brief If the window is able to be separated from the main application window.
     */
    OMNIUI_PROPERTY(bool, detachable, DEFAULT, true, READ_VALUE, isDetachable, WRITE, setDetachable);

    /**
     * @brief Vitrual window is the window that is rendered to internal buffer.
     */
    OMNIUI_PROPERTY(bool, virtual, DEFAULT, false, READ_VALUE, isVirtual, PROTECTED, WRITE, _setVirtual);

    /**
     * @brief How the Window gains focus.
     */
    OMNIUI_PROPERTY(FocusPolicy, focusPolicy, DEFAULT, FocusPolicy::eDefault,
        READ_VALUE, getFocusPolicy, WRITE, setFocusPolicy);

    /**
     * @brief When true, the window automatically fills the entire application
     * window every frame. Position is set to (0, 0) and size is set to the
     * main viewport size. Intended for standalone single-window applications.
     */
    OMNIUI_PROPERTY(bool, fillAppWindow, DEFAULT, false, READ_VALUE, getFillAppWindow, WRITE, setFillAppWindow);


    /**
     * @brief Set the enabvled state of the Window
     */
    OMNIUI_API
    void setActive(bool active);

protected:
    struct WindowData;
    /**
     * @brief Construct the window, add it to the underlying windowing system, and makes it appear.
     *
     * TODO: By default, the window should not be visible, and the user must call setVisible(true), or show() or similar
     * to make it visible because right now it's impossible to create invisible window.
     *
     * @param title The window title. It's also used as an internal window ID.
     * @param dockPrefence In the old Kit determines where the window should be docked. In Kit Next it's unused.
     */
    OMNIUI_API
    Window(const std::string& title, Window::DockPreference dockPrefence = DockPreference::eDisabled,
           WindowData* window = nullptr);

    OMNIUI_API
    Window(const std::string& title, WindowData* window);

    /**
     * @brief Execute the rendering code of the widget.
     *
     * It's in protected section because it can be executed only by this object itself.
     */
    virtual void _draw(const char* windowName, float elapsedTime);

    /**
     * @brief Execute the update code for the window, this is to be called inside some ImGui::Begin* code
     * it is used by modal popup and the main begin window code
     *
     * It's in protected section so object overiding behavior can re-use this logic
     */
    void _updateWindow(const char* windowName, float elapsedTime, bool cachePosition);

    /**
     * @brief this will push the window style, this need to be called within the _draw function to enable styling
     */
    void _pushWindowStyle();

    /**
     * @brief if you have pushed Window StyleContainer you need to pop it before the end of the _draw method
     */
    void _popWindowStyle();

private:
    /**
     * @brief Used as a callback of the underlying windowing system. Calls draw().
     */
    static void _drawWindow(const char* windowName, float elapsedTime, void* window);

    /**
     * @brief Used as a callback when the user call setPosition(X!Y)
     */
    void _positionExplicitlyChanged();

    /**
     * @brief Used as a callback when the user call setPosition(X!Y)
     */
    void _sizeExplicitlyChanged();

    /**
     * @brief Internal function that adds the window to the top level of the stack of modal windows.
     */
    void _addToModalStack() const;

    /**
     * @brief Internal function that removes the window from the stack of modal windows.
     */
    void _removeFromModalStack() const;

    /**
     * @brief Internal function that returns true if it's on the top of the stack of modal windows.
     */
    bool _isTopModal() const;

    /**
     * @brief Force propagate the window state to the backend.
     */
    void _forceWindowState();

    /**
     * @brief Update the Window's focused state, retuns whether it has changed.
     */
    bool _updateFocusState();

    /**
     * @brief draw tooltip
     */
    void _drawTooltip(std::string& tooltip);

protected:
    std::unique_ptr<WindowData> m_data;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
