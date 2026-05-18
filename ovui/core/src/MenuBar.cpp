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
#include <omni/ui/Menu.h>
#include <omni/ui/MenuBar.h>
#include <omni/ui/StyleContainer.h>

#include "MenuData.h"

#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE


struct MenuBar::MenuBarData : public Menu::MenuData
{
    MenuBarData(bool mainMenuBar) : m_mainMenuBar(mainMenuBar) {}
    const bool m_mainMenuBar = false;
};


MenuBar::MenuBar(bool mainMenuBar)
    : Menu("", new MenuBarData(mainMenuBar))
{
    this->setDirection(Stack::Direction::eLeftToRight);
}

MenuBar::~MenuBar()
{
    this->destroy();
}

void MenuBar::_drawContent(float elapsedTime)
{
    uint32_t popColorCount = 0, popFloatCount = 0;
    uint32_t color;
    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &color))
    {
        ImGui::PushStyleColor(ImGuiCol_MenuBarBg, color);
        popColorCount += 1;
    }

    if (this->_resolveStyleProperty(StyleColorProperty::eColor, &color))
    {
        ImGui::PushStyleColor(ImGuiCol_Text, color);
        popColorCount += 1;
    }

    if (this->_resolveStyleProperty(StyleColorProperty::eBorderColor, &color))
    {
        ImGui::PushStyleColor(ImGuiCol_Border, color);
        popColorCount += 1;
    }

    if (this->_resolveStyleProperty(StyleColorProperty::eBackgroundSelectedColor, &color))
    {
        ImGui::PushStyleColor(ImGuiCol_HeaderActive, color);
        ImGui::PushStyleColor(ImGuiCol_HeaderHovered, color);
        ImGui::PushStyleColor(ImGuiCol_Header, color);

        popColorCount += 3;
    }

    float dpiScale = this->getDpiScale();

    float value;
    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &value))
    {
        ImGui::PushStyleVar(ImGuiStyleVar_PopupBorderSize, value * dpiScale);
        popFloatCount += 1;
    }

    if (this->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &value))
    {
        ImGui::PushStyleVar(ImGuiStyleVar_PopupRounding, value * dpiScale);
        popFloatCount += 1;
    }

    if (this->_resolveStyleProperty(StyleFloatProperty::ePadding, &value))
    {
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(value * dpiScale, value * dpiScale));
        popFloatCount += 1;
    }

    const bool mainMenuBar = _getData<MenuBarData>().m_mainMenuBar;
    const bool useHostMenuBar =
        mainMenuBar && ImGui::GetCurrentWindow() && (ImGui::GetCurrentWindow()->Flags & ImGuiWindowFlags_MenuBar);
    bool menubarVisible;
    if (mainMenuBar && !useHostMenuBar)
    {
        menubarVisible = ImGui::BeginMainMenuBar();
    }
    else
    {
        menubarVisible = ImGui::BeginMenuBar();
    }

    if (menubarVisible)
    {
        Menu::_drawContent(elapsedTime);

        // BeginMenuBar needs moved cursor. HStack leaves the cursor untouched.
        auto cursor = ImGui::GetCursorScreenPos();
        ImGui::SetCursorScreenPos({ cursor.x + this->getComputedContentWidth(), cursor.y });

        if (mainMenuBar && !useHostMenuBar)
        {
            ImGui::EndMainMenuBar();
        }
        else
        {
            ImGui::EndMenuBar();
        }
    }

    ImGui::PopStyleColor(popColorCount);
    ImGui::PopStyleVar(popFloatCount);
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
