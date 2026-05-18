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
//! @brief omni::ui WindowHandle
#pragma once

#include "Api.h"
#include "Types.h"

#include <cstdint>
#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief WindowHandle is a handle object to control any of the windows in Kit. It can be created any time, and if it's
 * destroyed, the source window doesn't disappear.
 */
class OMNIUI_CLASS_API WindowHandle
{
public:
    // This is the DockPosition relative to a Split in a DockNode, Same reflect that the position is not Splitted but
    // over the other window in the same dockNode
    enum class DockPosition : uint8_t
    {
        eLeft = 0,
        eRight = 1,
        eTop = 2,
        eBottom = 3,
        eSame = 4
    };

    virtual ~WindowHandle();

    /**
     * @brief The title of the window.
     */
    OMNIUI_API
    virtual std::string getTitle() const;

    /**
     * @brief The position of the window in points.
     */
    OMNIUI_API
    virtual float getPositionX() const;

    /**
     * @brief Set the position of the window in points.
     */
    OMNIUI_API
    virtual void setPositionX(const float& positionX);

    /**
     * @brief The position of the window in points.
     */
    OMNIUI_API
    virtual float getPositionY() const;

    /**
     * @brief Set the position of the window in points.
     */
    OMNIUI_API
    virtual void setPositionY(const float& positionY);

    /**
     * @brief The width of the window in points.
     */
    OMNIUI_API
    virtual float getWidth() const;

    /**
     * @brief Set the width of the window in points.
     */
    OMNIUI_API
    virtual void setWidth(const float& width);

    /**
     * @brief The height of the window in points.
     */
    OMNIUI_API
    virtual float getHeight() const;

    /**
     * @brief Set the height of the window in points.
     */
    OMNIUI_API
    virtual void setHeight(const float& height);

    /**
     * @brief Returns whether the window is visible.
     */
    [[deprecated("Calling isVisible to WindowHandle in c++ will be deprecated. Use isVisible to Window instead!")]]
    OMNIUI_API
    virtual bool isVisible() const;

    /**
     * @deprecated Calling setVisible to WindowHandle will be deprecated. Use setVisible to Window instead!
     */
    [[deprecated("Calling setVisible to WindowHandle will be deprecated. Use setVisible to Window instead!")]]
    OMNIUI_API
    virtual void setVisible(const bool& visible);

    /**
     * @brief Checks if the current docking space has the tab bar.
     */
    OMNIUI_API
    virtual bool isDockTabBarVisible() const;

    /**
     * @brief Sets the visibility of the current docking space tab bar. Unlike
     * disabled, invisible tab bar can be shown with a little triangle in top
     * left corner of the window.
     */
    OMNIUI_API
    virtual void setDockTabBarVisible(const bool& visible);

    /**
     * @brief Checks if the current docking space is disabled. The disabled
     * docking tab bar can't be shown by the user.
     */
    OMNIUI_API
    virtual bool isDockTabBarEnabled() const;

    /**
     * @brief Sets the visibility of the current docking space tab bar. The disabled
     * docking tab bar can't be shown by the user.
     */
    OMNIUI_API
    virtual void setDockTabBarEnabled(const bool& disabled);

    /**
     * @brief Undock the window and make it floating.
     */
    OMNIUI_API
    virtual void undock();

    /**
     * @brief Dock the window to the existing window. It can split the window to two parts or it can convert the window
     * to a docking tab.
     */
    OMNIUI_API
    virtual void dockIn(const std::shared_ptr<WindowHandle>& window, const DockPosition& dockPosition, float ratio = 0.5);

    /**
     * @brief The position of the window in the dock.
     */
    OMNIUI_API
    virtual int32_t getDockOrder() const;

    /**
     * @brief Set the position of the window in the dock.
     */
    OMNIUI_API
    virtual void setDockOrder(const int32_t& dockOrder);

    /**
     * @brief True if this window is docked. False otherwise.
     */
    OMNIUI_API
    virtual bool isDocked() const;

    /**
     * @brief Returns ID of the dock node this window is docked to.
     */
    OMNIUI_API
    virtual uint32_t getDockId() const;

    /**
     * @brief Brings the window to the top. If it's a docked window, it makes the window currently visible in the dock.
     */
    OMNIUI_API
    virtual void focus();

    /**
     * @brief Return true is the window is the current window in the docking area.
     */
    OMNIUI_API
    virtual bool isSelectedInDock();

    /**
     * @brief Notifies the UI window that the AppWindow it attached to has changed.
     */
    OMNIUI_API
    virtual void notifyAppWindowChange(AppWindowHandle newAppWindow);

protected:
    friend class Workspace;

    /**
     * @brief Create a handle with the given ID.
     *
     * Only Workspace can create this object.
     */
    OMNIUI_API
    WindowHandle(uint32_t windowId);

    /**
     * @brief Given an input window, check if it is the current window in the docking area.
     * @details This is to give the API to check if the current window is selected when we
     * already have the window, saving us running the slow `_GET_WINDOW`.
     */
    OMNIUI_API
    bool _isWindowSelectedInDock(void *window);

    // Underlying ID of the window.
    uint32_t m_windowId = 0;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
