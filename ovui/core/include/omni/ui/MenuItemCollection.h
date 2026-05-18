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

#include "Menu.h"

#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The MenuItemCollection is the menu that unchecks children when one of
 * them is checked
 */
class OMNIUI_CLASS_API MenuItemCollection : public Menu
{
    OMNIUI_OBJECT(MenuItemCollection)

public:
    OMNIUI_API
    ~MenuItemCollection() override;

    /**
     * @brief Adds the menu. We subscribe to the `checked` changes and uncheck
     * others.
     */
    void addChild(std::shared_ptr<Widget> widget) override;

protected:
    /**
     * @brief Construct MenuItemCollection
     */
    OMNIUI_API
    MenuItemCollection(const std::string& text = "");

    struct MenuItemCollectionData;
    std::unique_ptr<MenuItemCollectionData> m_data;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
