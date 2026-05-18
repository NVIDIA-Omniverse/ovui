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

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/MenuItem.h>
#include <omni/ui/StyleContainer.h>

#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

MenuItem::MenuItem(const std::string& text, Widget::WidgetData* dataPtr)
    : Widget(dataPtr)
{
    this->setText(text);

    MenuHelper::_menuHelperInit(*this);
}

MenuItem::~MenuItem() = default;

std::string MenuItem::getIdentifier()
{
    std::string identifier = Widget::getIdentifier();
    if (identifier.empty())
    {
        identifier = this->getText();
        if (!identifier.empty())
        {
            identifier = normalizeIdentifier(identifier);
        }
    }
    return identifier;
}

void MenuItem::setComputedContentWidth(float width)
{
    Widget::setComputedContentWidth(this->_menuHelperEvalWidth(*this, width));
}

void MenuItem::setComputedContentHeight(float height)
{
    Widget::setComputedContentHeight(this->_menuHelperEvalHeight(*this, height));
}

void MenuItem::cascadeStyle()
{
    this->useMarginFromStyle(false);
    Widget::cascadeStyle();
    this->_menuHelperCascadeStyle();
}

void MenuItem::_drawContent(float elapsedTime)
{
    this->_menuHelperDraw(*this, elapsedTime);
}


OMNIUI_NAMESPACE_CLOSE_SCOPE
