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

#include "platform/Assert.h"
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Frame.h>
#include <omni/ui/HStack.h>
#include <omni/ui/Inspector.h>
#include <omni/ui/Label.h>
#include <omni/ui/Menu.h>
#include <omni/ui/MenuBar.h>
#include <omni/ui/MenuDelegate.h>
#include <omni/ui/MenuHelper.h>
#include <omni/ui/MenuItem.h>

OMNIUI_NAMESPACE_OPEN_SCOPE


struct MenuHelper::MenuHelperData
{
    // All the widgets of the item
    std::shared_ptr<Frame> m_frame;
    // Dirty flag
    bool m_dirty = true;
};


class MenuItemContainer : public Frame
{
    OMNIUI_OBJECT(MenuItemContainer)

public:
    OMNIUI_API
    ~MenuItemContainer() override = default;

protected:
    OMNIUI_API
    MenuItemContainer(Widget& widget) : Frame{}
    {
        this->setParent(&widget);
    }
};

MenuHelper::MenuHelper() : m_data(new MenuHelperData)
{
    this->_setTextChangedFn(std::bind(&MenuHelper::_menuHelperInvalidate, this));
    this->_setHotkeyTextChangedFn(std::bind(&MenuHelper::_menuHelperInvalidate, this));
    this->_setCheckableChangedFn(std::bind(&MenuHelper::_menuHelperInvalidate, this));
}

MenuHelper::~MenuHelper() = default;

bool MenuHelper::isInHorizontalLayout() const
{
    if (const auto widget = this->_getWidget())
    {
        if (auto parent = widget->getParent())
        {
            if (auto menu = dynamic_cast<Menu*>(parent))
            {
                Stack::Direction parentDirection = menu->getDirection();
                if (parentDirection == Stack::Direction::eLeftToRight || parentDirection == Stack::Direction::eRightToLeft)
                {
                    return true;
                }
            }
        }
    }

    return false;
}

void MenuHelper::_menuHelperInit(Widget& widget)
{
    // Don't push created object to any container
    OMNIKIT_WITH_CONTAINER(nullptr)
    {
        auto& frame = m_data->m_frame;
        frame = MenuItemContainer::create(widget);
        frame->setHeight(Pixel{ 0.0f });
    }

    widget.setCheckedChangedFn(std::bind(&MenuHelper::_menuHelperInvalidate, this));
    widget.setEnabledChangedFn(std::bind(&MenuHelper::_menuHelperInvalidate, this));
}

void MenuHelper::_menuHelperDestroy()
{
    this->destroyCallbacks();
}

float MenuHelper::_menuHelperEvalWidth(Widget& widget, float proposed)
{
    this->_verifyFrame(widget);

    auto& frame = m_data->m_frame;
    frame->setComputedWidth(proposed);
    return frame->getComputedContentWidth();
}

float MenuHelper::_menuHelperEvalHeight(Widget& widget, float proposed)
{
    this->_verifyFrame(widget);

    auto& frame = m_data->m_frame;
    frame->setComputedHeight(proposed);
    return frame->getComputedContentHeight();
}

void MenuHelper::_menuHelperDraw(Widget& widget, float elapsedTime)
{
    this->_verifyFrame(widget);

    if (widget.isEnabled() && widget.isHovered())
    {
        // Selection color
        uint32_t color;
        if (!widget._resolveStyleProperty(StyleColorProperty::eBackgroundSelectedColor, &color))
        {
            // Check in ImGui
            color = ImGui::GetColorU32(ImGui::GetStyleColorVec4(ImGuiCol_Header));
        }

        // Selection border
        float border = 0.0f;
        widget._resolveStyleProperty(StyleFloatProperty::eSecondaryPadding, &border);
        uint32_t borderColor = 0x0;
        widget._resolveStyleProperty(StyleColorProperty::eSecondarySelectedColor, &borderColor);

        // Selection rectangle
        auto cursor = ImGui::GetCursorScreenPos();
        ImVec2 rectBegin = cursor;
        ImVec2 rectEnd = { cursor.x + widget.getComputedWidth(), cursor.y + widget.getComputedHeight() };
        if (this->isInHorizontalLayout())
        {
            rectBegin.y += 1.0f;
        }
        if (color != 0x0)
        {
            ImGui::GetWindowDrawList()->AddRectFilled(rectBegin, rectEnd, color);
        }
        // Selection border rectangle
        if (border > 0.0f && borderColor != 0x0)
        {
            float dpiScale = widget.getDpiScale();
            border *= dpiScale;

            float halfBorder = border * 0.5f;
            rectBegin.x += halfBorder;
            rectBegin.y += halfBorder;
            rectEnd.x -= halfBorder;
            rectEnd.y -= halfBorder;

            ImGui::GetWindowDrawList()->AddRect(rectBegin, rectEnd, borderColor, 0.0f, 15, border);
        }

        bool wantClose = false;
        if (ImGui::IsMouseClicked(0) && ImGui::IsWindowHovered(0))
        {
            if (this->hasTriggeredFn())
            {
                this->callTriggeredFn();
                wantClose = true;
            }

            if (this->isCheckable())
            {
                widget.setChecked(!widget.isChecked());
                wantClose = true;
            }
        }

        if (wantClose && this->isHideOnClick())
        {
            auto ctx = ImGui::GetCurrentContext();
            OMNIUI_ASSERT(ctx);
            ImGuiWindow* window = ctx->CurrentWindow;
            OMNIUI_ASSERT(window);

            // Close this popup. If it's a separate window it will not be closed.
            if (window->Flags & ImGuiWindowFlags_Popup)
            {
                // ImGui::CloseCurrentPopup();
                ImGui::ClosePopupToLevel(0, true);
            }
        }
    }

    uint32_t color;
    bool customColor = widget._resolveStyleProperty(StyleColorProperty::eSecondaryColor, &color);
    if (customColor)
    {
        // If StyleColorProperty::eSecondaryColor defined, enable custom char and use it for glyph chars
        ImGui::PushStyleColor(ImGuiCol_CustomChar, color);
        widget._enableCustomChar(true);
    }

    m_data->m_frame->draw(elapsedTime);

    if (customColor)
    {
        widget._enableCustomChar(false);
        ImGui::PopStyleColor();
    }
}

void MenuHelper::_verifyFrame(Widget& widget)
{
    auto& dirty = m_data->m_dirty;
    if (!dirty)
    {
        return;
    }
    dirty = false;

    auto& frame = m_data->m_frame;
    frame->setEnabled(widget.isEnabled());
    frame->setSelected(widget.isSelected());
    frame->setChecked(widget.isChecked());

    OMNIKIT_WITH_CONTAINER(frame)
    {
        auto delegate = this->_obtainDelegate(widget);
        delegate->buildItem(MenuHelper::_getMenuHelper(widget));
    }
}

const std::shared_ptr<MenuDelegate>& MenuHelper::_obtainDelegate(Widget& widget)
{
    return this->_obtainDelegateRecursive(widget);
}

void MenuHelper::_menuHelperCascadeStyle()
{
    m_data->m_frame->cascadeStyle();
}

void MenuHelper::_menuHelperInvalidate()
{
    m_data->m_dirty = true;
}

const Widget* MenuHelper::_getWidget() const
{
    // TODO: Template it
    if (const auto menu = dynamic_cast<const Menu*>(this))
    {
        return menu;
    }
    if (const auto menuItem = dynamic_cast<const MenuItem*>(this))
    {
        return menuItem;
    }

    return nullptr;
}

MenuHelper* MenuHelper::_getMenuHelper(Widget& widget)
{
    // TODO: Template it
    if (auto menu = dynamic_cast<Menu*>(&widget))
    {
        return menu;
    }
    if (auto menuItem = dynamic_cast<MenuItem*>(&widget))
    {
        return menuItem;
    }

    return nullptr;
}

std::vector<std::shared_ptr<Widget>> MenuHelper::_getSiblings() const
{
    if (const auto widget = this->_getWidget())
    {
        if (auto parent = widget->getParent())
        {
            if (auto container = dynamic_cast<Container*>(parent))
            {
                return Inspector::getChildren(container->shared_from_this());
            }
        }
    }

    return {};
}

const std::shared_ptr<MenuDelegate>& MenuHelper::_obtainDelegateRecursive(Widget& widget, uint16_t depth)
{
    if (auto& current = this->getDelegate())
    {
        // Skip if the delegate doesn't want to be propagated
        if (depth == 0 || current->isPropagate())
        {
            return current;
        }
    }

    if (auto parent = widget.getParent())
    {
        if (auto menu = dynamic_cast<Menu*>(parent))
        {
            return menu->_obtainDelegateRecursive(*menu, depth + 1);
        }
    }

    // Can't find anything. Use the default one.
    return MenuDelegate::getDefaultDelegate();
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
