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

#include "MenuHelper.h"
#include "Stack.h"

#include <omni/ui/windowmanager/IWindowCallbackManager.h>

#include <memory>
#include <string>

namespace omni
{
namespace kit
{
struct Window;
}
}

OMNIUI_NAMESPACE_OPEN_SCOPE

class Frame;

/**
 * @brief The Menu class provides a menu widget for use in menu bars, context menus, and other popup menus.
 *
 * It can be either a pull-down menu in a menu bar or a standalone context menu. Pull-down menus are shown by the menu
 * bar when the user clicks on the respective item. Context menus are usually invoked by some special keyboard key or by
 * right-clicking.
 *
 * TODO: Add the ability to add any widget. ATM if a random widget is added to Menu, the behaviour is undefined.
 */
class OMNIUI_CLASS_API Menu : public Stack, public MenuHelper
{
    OMNIUI_OBJECT(Menu)

public:
    using CallbackHelperBase = Widget;

    OMNIUI_API
    ~Menu() override;

    OMNIUI_API
    void destroy() override;

    /**
     * @brief Reimplemented adding a widget to this Menu.
     *
     * @see Container::addChild
     */
    OMNIUI_API
    void addChild(std::shared_ptr<Widget> widget) override;

    /**
     * @brief Reimplemented removing all the child widgets from this Menu.
     *
     * @see Container::clear
     */
    OMNIUI_API
    void clear() override;

    /**
     * @brief Reimplemented the method to indicate the width hint that represents the preferred size of the widget.
     *
     * @see Widget::setComputedContentWidth
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief It's called when the style is changed. It should be propagated to children to make the style cached and
     * available to children.
     */
    OMNIUI_API
    void cascadeStyle() override;

    /**
     * @brief Create a popup window and show the menu in it. It's usually used for context menus that are typically
     * invoked by some special keyboard key or by right-clicking.
     */
    OMNIUI_API
    void show();

    /**
     * @brief Create a popup window and show the menu in it. This enable to popup the menu at specific position. X and Y
     * are in points to make it easier to the Python users.
     */
    OMNIUI_API
    void showAt(float x, float y);

    /**
     * @brief Close the menu window. It only works for pop-up context menu and
     * for teared off menu.
     */
    OMNIUI_API
    void hide();

    /**
     * @brief Make Menu dirty so onBuild will be executed to replace the
     * children.
     */
    OMNIUI_API
    void invalidate();

    /**
     * @brief Return the menu that is currently shown.
     */
    OMNIUI_API
    static std::shared_ptr<Menu> getCurrent();

    /**
     * @brief It's true when the menu is shown on the screen.
     */
    OMNIUI_PROPERTY(bool, shown, DEFAULT, false, READ, isShown, NOTIFY, setShownChangedFn, PROTECTED, WRITE, _setShown);

    /**
     * @brief The ability to tear the window off.
     */
    OMNIUI_PROPERTY(
        bool, tearable, DEFAULT, true, READ, isTearable, WRITE, setTearable, PROTECTED, NOTIFY, _setTearableChangedFn);

    /**
     * @brief If the window is teared off.
     */
    OMNIUI_PROPERTY(bool, teared, DEFAULT, false, READ, isTeared, NOTIFY, setTearedChangedFn, PROTECTED, WRITE, _setTeared);

    /**
     * @brief Called to re-create new children
     */
    OMNIUI_CALLBACK(OnBuild, void);

    /**
     * @brief Create a popup window and tear the menu in it. This enable to popup the menu at specific position. X and Y
     * are in points to make it easier to the Python users.
     */
    OMNIUI_API
    void tearAt(float x, float y);

protected:
    struct MenuData;

    /**
     * @brief Construct Menu
     *
     * @param text The text for the menu.
     */
    OMNIUI_API
    Menu(const std::string& text, MenuData* data = nullptr);

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * Draw the content.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

    /**
     * @brief Reimplement the getIdentifier method to account for .text property.
     *
     */
    OMNIUI_API std::string getIdentifier() override;

private:

    void _drawMenu(float elapsedTime, bool isInSeparateWindow, bool isPopupWindow);

    void _showMenuWindow(float x, float y);

    /**
     * @brief Creates a popup window to put the menu to using the underlying windowing system.
     */
    void _createMenuWindow(bool isPopupWindow);

    /**
     * @brief Removes previously created popup window using the underlying windowing system. If window wasn't created,
     * it does nothing.
     */
    void _removeMenuWindow(bool removeCurrent);

    /**
     * @brief We cannot destroy window when we are right in the middle of
     * rendering loop. Thus, we schedule a one-time deferred callback which will
     * destroy the window.
     */
    void _removeMenuWindowDeferred(bool removeCurrent);

    /**
     * @brief Check if the title is dirty and call the delegate to build the
     * window title.
     */
    void _verifyTitleFrame();

    /**
     * @brief Check if the  is dirty and call the delegate to build the
     * window title.
     */
    void _verifyChildren();

    /**
     * @brief set setStyleTypeNameOverride to "Menu.Window" when style name is empty
     * @return true when style name is empty
     */
     bool _setEmptyStyleTypeNameOverride();

};

OMNIUI_NAMESPACE_CLOSE_SCOPE
