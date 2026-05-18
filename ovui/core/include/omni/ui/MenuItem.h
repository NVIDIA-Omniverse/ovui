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
#include "Widget.h"

#include <functional>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief A MenuItem represents the items the Menu consists of.
 *
 * MenuItem can be inserted only once in the menu.
 *
 * TODO: In addition to a text label, MenuItem should have an optional icon drawn on the very left side, and shortcut
 * key sequence such as "Ctrl+X".
 */
class OMNIUI_CLASS_API MenuItem : public Widget, public MenuHelper
{
    OMNIUI_OBJECT(MenuItem)

public:
    using CallbackHelperBase = Widget;

    OMNIUI_API
    ~MenuItem() override;

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

protected:
    struct MenuItemData;

    /**
     * @brief Construct MenuItem
     */
    OMNIUI_API
    MenuItem(const std::string& text, WidgetData* data = nullptr);

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
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
