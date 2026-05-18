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

#include <omni/ui/Container.h>
#include <omni/ui/Frame.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/ToolBar.h>

#include "WindowData.h"

#include <functional>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct ToolBar::ToolBarData : public Window::WindowData
{
    using WindowData::WindowData;
    ~ToolBarData() override = default;

    float m_prevContentRegionWidth = 0.0f;
    float m_prevContentRegionHeight = 0.0f;
};

ToolBar::ToolBar(const std::string& title)
    : Window::Window(title, new ToolBarData(DockPreference::eDisabled))
{
}

ToolBar::~ToolBar()
{
}

void ToolBar::_draw(const char* windowName, float elapsedTime)
{
    if (!this->isVisible())
    {
        return;
    }

    // we push the various window styling into the stack
    this->_pushWindowStyle();

    /// Experimental branch `docking_toolbar` support from Omar

    // [Option] Automatically update axis based on parent split (inside of doing it via right-click on the toolbar)
    // Pros:
    // - Less user intervention.
    // - Avoid for need for saving the toolbar direction, since it's automatic.
    // Cons:
    // - This is currently leading to some glitches.
    // - Some docking setup won't return the axis the user would expect.
    const bool kToolbarAutoDirWhenDocked = true;

    ::ImGuiAxis toolbarAxis = this->getAxis() == Axis::eX ? ImGuiAxis_X : ImGuiAxis_Y;

    // 1. We request auto-sizing on one axis
    // Note however this will only affect the toolbar when NOT docked.
    ::ImVec2 requestedSize = (toolbarAxis == ImGuiAxis_X) ? ImVec2(-1.0f, 0.0f) : ImVec2(0.0f, -1.0f);
    ::ImGui::SetNextWindowSize(requestedSize);

    // 2. Specific docking options for toolbars.
    ImGuiWindowClass windowClass;
    windowClass.DockingAllowUnclassed = true;
    windowClass.DockNodeFlagsOverrideSet |= ImGuiDockNodeFlags_NoCloseButton;
    windowClass.DockNodeFlagsOverrideSet |= ImGuiDockNodeFlags_HiddenTabBar;
    windowClass.DockNodeFlagsOverrideSet |= ImGuiDockNodeFlags_NoDockingSplit;
    windowClass.DockNodeFlagsOverrideSet |= ImGuiDockNodeFlags_NoDockingOverMe;
    windowClass.DockNodeFlagsOverrideSet |= ImGuiDockNodeFlags_NoDockingOverOther;
    if (toolbarAxis == ImGuiAxis_X)
        windowClass.DockNodeFlagsOverrideSet |= ImGuiDockNodeFlags_NoResizeY;
    else
        windowClass.DockNodeFlagsOverrideSet |= ImGuiDockNodeFlags_NoResizeX;

    if (this->getNoTabBar())
    {
        windowClass.DockNodeFlagsOverrideSet |= ImGuiDockNodeFlags_NoTabBar;
    }

    ::ImGui::SetNextWindowClass(&windowClass);

    // calcualte mininum size for the Frame
    this->getFrame()->setComputedHeight(0);
    this->getFrame()->setComputedWidth(0);

    // here is strange that mean we are setting up the window even if we are not gonna draw it ?
    // TODO: FIXME
    bool visible = this->isVisible();

    // adjusting the tear off button color styling
    uint8_t pushedColor = 3;
    ImGui::PushStyleColor(ImGuiCol_Button, 0x0);
    ImGui::PushStyleColor(ImGuiCol_ButtonActive, 0x0);
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, 0x88888888);

    if (ImGui::Begin(windowName, &visible,
                     ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoScrollbar))
    {

        auto* ctx = ImGui::GetCurrentContext();
        ImGuiWindow* window = ctx->CurrentWindow;
        m_windowId = window->ID;

        // now we can reset the color for buttons
        ImGui::PopStyleColor(pushedColor);
        pushedColor = 0;

        // 4. Overwrite node size
        ::ImGuiDockNode* node = window->DockNode;
        if (node != NULL)
        {
            // Overwrite size of the node
            const ::ImGuiAxis toolbarAxisPerp = (::ImGuiAxis)(toolbarAxis ^ 1);
            float toolbarSizeWhenDocked;
            // force computation of Minimum size in the ToolBar Axisfor the Frame
            if (toolbarAxisPerp == ImGuiAxis_X)
            {
                toolbarSizeWhenDocked = this->getPaddingX() * 2.0f + this->getFrame()->getComputedWidth();
            }
            else
            {
                toolbarSizeWhenDocked = this->getPaddingY() * 2.0f + this->getFrame()->getComputedHeight();
            }

            node->WantLockSizeOnce = true;
            node->Size[toolbarAxisPerp] = node->SizeRef[toolbarAxisPerp] = toolbarSizeWhenDocked;

            if (kToolbarAutoDirWhenDocked)
            {
                if (node->ParentNode && node->ParentNode->SplitAxis != ImGuiAxis_None)
                {
                    toolbarAxis = (::ImGuiAxis)(node->ParentNode->SplitAxis ^ 1);
                    if ((Axis)toolbarAxis != this->getAxis())
                    {
                        this->setAxis((Axis)toolbarAxis);
                    }
                }
            }
        }

        // Use GetContentRegionAvail() to get content region dimensions.
        auto contentRegionAvail = ImGui::GetContentRegionAvail();

        auto& data = static_cast<ToolBarData&>(*m_data);

        // update the content of the Frame to fit the window
        if (this->getAxis() == Axis::eX)
        {
            float contentRegionWidth = contentRegionAvail.x;
            if (contentRegionWidth != m_data->m_prevContentRegionWidth)
            {
                m_data->m_prevContentRegionWidth = contentRegionWidth;
                this->getFrame()->forceWidthDirty(Widget::SizeDirtyReason::eParentDirty);
                this->getFrame()->forceRasterDirty(Widget::BakeDirtyReason::eContentChanged);
            }
            this->getFrame()->setComputedWidth(contentRegionWidth);
        }
        else
        {
            float contentRegionHeight = contentRegionAvail.y;
            if (contentRegionHeight != m_data->m_prevContentRegionHeight)
            {
                m_data->m_prevContentRegionHeight = contentRegionHeight;
                this->getFrame()->forceHeightDirty(Widget::SizeDirtyReason::eParentDirty);
                this->getFrame()->forceRasterDirty(Widget::BakeDirtyReason::eContentChanged);
            }
            this->getFrame()->setComputedHeight(contentRegionHeight);
        }

        this->getFrame()->draw(elapsedTime);

        // Update the size/position properties
        float uiScale_inv = 1.f / ImGui::GetWindowDpiScale();
        ImVec2 windowPos = ImGui::GetWindowPos();
        ImVec2 windowSize = ImGui::GetWindowSize();
        this->setPositionX(windowPos.x * uiScale_inv);
        this->setPositionY(windowPos.y * uiScale_inv);
        this->setWidth(windowSize.x * uiScale_inv);
        this->setHeight(windowSize.y * uiScale_inv);
    }
    ImGui::End();

    // we pushed out of those button color, as the ToolBar didn't show
    ImGui::PopStyleColor(pushedColor);

    // pop styling
    this->_popWindowStyle();

    this->setVisible(visible && this->isVisible());
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
