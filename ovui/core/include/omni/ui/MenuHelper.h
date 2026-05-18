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

#include <memory>
#include <string>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

class Widget;
class Frame;
class MenuDelegate;

/**
 * @brief The helper class for the menu that draws the menu line.
 */
class OMNIUI_CLASS_API MenuHelper : private CallbackHelper<MenuHelper>
{
public:
    OMNIUI_API
    virtual ~MenuHelper();

    /**
     * @brief Returns true if the item is in horizontal layout.
     */
    bool isInHorizontalLayout() const;

    /**
     * @brief Sets the function that is called when an action is activated by the user; for example, when the user
     * clicks a menu option, or presses an action's shortcut key combination.
     */
    OMNIUI_CALLBACK(Triggered, void);

    /**
     * @brief This property holds the menu's text.
     */
    OMNIUI_PROPERTY(std::string, text, READ, getText, WRITE, setText, PROTECTED, NOTIFY, _setTextChangedFn);

    /**
     * @brief This property holds the menu's hotkey text.
     */
    OMNIUI_PROPERTY(
        std::string, hotkeyText, READ, getHotkeyText, WRITE, setHotkeyText, PROTECTED, NOTIFY, _setHotkeyTextChangedFn);

    /**
     * @brief This property holds whether this menu item is checkable. A checkable item is one which has an on/off
     * state.
     */
    OMNIUI_PROPERTY(
        bool, checkable, DEFAULT, false, READ, isCheckable, WRITE, setCheckable, PROTECTED, NOTIFY, _setCheckableChangedFn);

    /**
     * @brief The delegate that generates a widget per menu item.
     */
    OMNIUI_PROPERTY(std::shared_ptr<MenuDelegate>,
                    delegate,
                    READ,
                    getDelegate,
                    WRITE,
                    setDelegate,
                    PROTECTED,
                    NOTIFY,
                    _setDelegateChangedFn);

    /**
     * @brief Hide or keep the window when the user clicked this item.
     */
    OMNIUI_PROPERTY(bool, hideOnClick, DEFAULT, true, READ, isHideOnClick, WRITE, setHideOnClick);

    OMNIUI_PROPERTY(bool,
                    compatibility,
                    DEFAULT,
                    false,
                    READ,
                    isMenuCompatibility,
                    WRITE,
                    setMenuCompatibility,
                    PROTECTED,
                    NOTIFY,
                    _setMenuCompatibilityChangedFn);

protected:
    friend class MenuDelegate;

    /**
     * @brief Constructor
     */
    OMNIUI_API
    MenuHelper();

    /**
     * @brief Should be called by the widget in init time.
     */
    void _menuHelperInit(Widget& widget);

    /**
     * @brief Should be called by the widget in destroy time.
     */
    void _menuHelperDestroy();

    /**
     * @brief Eval and return width of the item.
     */
    float _menuHelperEvalWidth(Widget& widget, float proposed);

    /**
     * @brief Eval and return height of the item.
     */
    float _menuHelperEvalHeight(Widget& widget, float proposed);

    /**
     * @brief Should be called by the widget during draw.
     */
    void _menuHelperDraw(Widget& widget, float elapsedTime);

    /**
     * @brief Should be called by the widget during change of the style.
     */
    void _menuHelperCascadeStyle();

    /**
     * @brief Should be called to make the item dirty.
     */
    void _menuHelperInvalidate();

    /**
     * @brief Iterate the parents and find the delegate.
     */
    const std::shared_ptr<MenuDelegate>& _obtainDelegate(Widget& widget);

    /**
     * @brief Convert Widget to MenuHelper if possible.
     */
    static MenuHelper* _getMenuHelper(Widget& widget);

private:
    /**
     * @brief Check if the item is dirty and call the delegate.
     */
    void _verifyFrame(Widget& widget);

    /**
     * @brief Convert MenuHelper to Widget if possible.
     */
    const Widget* _getWidget() const;

    /**
     * @brief List of siblings.
     */
    std::vector<std::shared_ptr<Widget>> _getSiblings() const;

    /**
     * @brief Iterate the parents and find the delegate.
     */
    const std::shared_ptr<MenuDelegate>& _obtainDelegateRecursive(Widget& widget, uint16_t depth = 0);

    struct MenuHelperData;
    std::unique_ptr<MenuHelperData> m_data;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
