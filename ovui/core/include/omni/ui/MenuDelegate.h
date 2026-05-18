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

OMNIUI_NAMESPACE_OPEN_SCOPE

class MenuHelper;

/**
 * @brief MenuDelegate is used to generate widgets that represent the menu item.
 */
class OMNIUI_CLASS_API MenuDelegate : CallbackHelper<MenuDelegate>
{
public:
    /**
     * @brief Constructor
     */
    OMNIUI_API
    MenuDelegate();

    OMNIUI_API
    virtual ~MenuDelegate();

    /**
     * @brief This method must be reimplemented to generate custom item.
     */
    OMNIUI_API
    virtual void buildItem(const MenuHelper* item);

    /**
     * @brief This method must be reimplemented to generate custom title.
     */
    OMNIUI_API
    virtual void buildTitle(const MenuHelper* item);

    /**
     * @brief This method must be reimplemented to generate custom widgets on
     * the bottom of the window.
     */
    OMNIUI_API
    virtual void buildStatus(const MenuHelper* item);

    /**
     * @brief Get the default delegate that is used when the menu doesn't have
     * anything.
     */
    OMNIUI_API
    static const std::shared_ptr<MenuDelegate>& getDefaultDelegate();

    /**
     * @brief Set the default delegate to use it when the item doesn't have a
     * delegate.
     */
    OMNIUI_API
    static void setDefaultDelegate(std::shared_ptr<MenuDelegate> delegate);

    /**
     * @brief Called to create a new item
     */
    OMNIUI_CALLBACK(OnBuildItem, void, MenuHelper const*);

    /**
     * @brief Called to create a new title
     */
    OMNIUI_CALLBACK(OnBuildTitle, void, MenuHelper const*);

    /**
     * @brief Called to create a new widget on the bottom of the window
     */
    OMNIUI_CALLBACK(OnBuildStatus, void, MenuHelper const*);

    /**
     * @brief Determine if Menu children should use this delegate when they
     * don't have the own one.
     */
    OMNIUI_PROPERTY(bool, propagate, DEFAULT, true, READ_VALUE, isPropagate, WRITE, setPropagate);

private:
    /**
     * @brief Return true if at least one of the siblings have the hotkey text.
     */
    static bool _siblingsHaveHotkeyText(const MenuHelper* item);

    /**
     * @brief Return true if at least one of the siblings is checkable.
     */
    static bool _siblingsHaveCheckable(const MenuHelper* item);

    struct MenuDelegateData;
    std::unique_ptr<MenuDelegateData> m_data;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
