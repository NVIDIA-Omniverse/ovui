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
#include <omni/ui/ContainerScope.h>
#include "platform/PlatformRegistry.h"
#include <omni/ui/Container.h>
#include <omni/ui/DockSpace.h>
#include <omni/ui/Frame.h>
#include <omni/ui/MenuBar.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/Workspace.h>
#include <omni/ui/windowmanager/IWindowCallbackManager.h>
#include <omni/ui/windowmanager/WindowManagerUtils.h>

#include <functional>

OMNIUI_NAMESPACE_OPEN_SCOPE

DockSpace::DockSpace(windowmanager::WindowSet* windowSet) : m_windowSet(windowSet)
{
    // Create a frame and don't push created object to any container.
    OMNIKIT_WITH_CONTAINER(nullptr)
    {
        auto dockFrame = Frame::create();
        dockFrame->setStyleTypeNameOverride("DockFrame");
        this->setDockFrame(dockFrame);
    }

    auto drawLambda = [this](float elapsedTime) { this->_draw(elapsedTime); };

    omni::ui::windowmanager::IWindowCallbackManager* windowCallbackManager =
        PlatformRegistry::instance().windowCallbackManager();
    if (!m_windowSet)
    {
        m_windowSet = windowCallbackManager->getDefaultWindowSet();
    }

    static uint32_t internalIndex = 0;
    m_name = "DockSpace" + std::to_string(internalIndex);
    internalIndex++;

    m_windowCallback =
        windowmanager::createWindowSetCallback(m_windowSet, windowCallbackManager, m_name.c_str(), 0, 0,
                                               omni::ui::windowmanager::DockPreference::eDisabled, drawLambda);
}

DockSpace::~DockSpace()
{
    omni::ui::windowmanager::IWindowCallbackManager* windowCallbackManager =
        PlatformRegistry::instance().windowCallbackManager();
    windowCallbackManager->removeWindowSetCallback(m_windowSet, m_windowCallback.get());
}

void DockSpace::_draw(float elapsedTime)
{
    ImGuiViewport* viewport = ImGui::GetMainViewport();

    uint16_t popColorCount = 0;
    uint16_t popFloatCount = 0;

    ImGui::SetNextWindowPos(ImVec2(viewport->Pos.x, viewport->Pos.y));
    ImGui::SetNextWindowSize(ImVec2(viewport->Size.x, viewport->Size.y));
    ImGui::SetNextWindowViewport(viewport->ID);

    ImGuiWindowFlags host_window_flags = 0;
    host_window_flags |=
        ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove;
    host_window_flags |= ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoNavFocus;

    uint32_t background_color = 0xFF1F2124;
    m_dockFrame->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &background_color);
    ImGui::PushStyleColor(ImGuiCol_WindowBg, background_color);
    popColorCount += 1;

    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0.0f, 0.0f));
    ImGuiContext* g = ImGui::GetCurrentContext();
    g->Style.WindowMenuButtonPosition = ImGuiDir_Right;

    if (ImGui::Begin(m_name.c_str(), nullptr, host_window_flags))
    {
        float dockSplitterSize = ImGui::GetStyle().DockingSeparatorSize;

        // Read top padding from the dock frame style (set by the host app to reserve
        // space for a menu bar or toolbar rendered in a separate window above the DockSpace).
        // Style values are in logical pixels; the DockSpace window lives in the
        // framebuffer (physical) coordinate system — without this DPI multiplier the
        // dock area starts too close to the top and covers a menu bar above it.
        float topPadding = 0.0f;
        m_dockFrame->_resolveStyleProperty(StyleFloatProperty::ePadding, &topPadding);
        const float dpiScale = Workspace::getDpiScale();
        topPadding *= dpiScale;

        // Use Dummy() instead of SetCursorScreenPos so the cursor advance is
        // itself a submitted item — required by ImGui 1.92+'s strict cursor
        // boundary check (ErrorCheckUsingSetCursorPosToExtendParentBoundaries).
        // ImGui::DockSpace below doesn't always satisfy that check on its own
        // when the central node has no children. Zero ItemSpacing around the
        // Dummy so ItemSize() advances by exactly the spacer height — the
        // default ItemSpacing.y would otherwise add an extra gap before the
        // dockspace.
        ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(0.0f, 0.0f));
        ImGui::Dummy(ImVec2(0.0f, dockSplitterSize + topPadding));
        ImGui::PopStyleVar();

        // draw the dockspace
        ImGuiDockNodeFlags dockspaceFlags =
            ImGuiDockNodeFlags_NoWindowMenuButton | ImGuiDockNodeFlags_NoCloseButton;
        ImGuiID dockspaceId = ImGui::GetID("MyDockspace");

        ImGui::DockSpace(dockspaceId, ImVec2(0.0f, viewport->Size.y - dockSplitterSize - topPadding), dockspaceFlags, nullptr);

        ImGui::PopStyleColor(popColorCount);
    }

    ImGui::End();

    ImGui::PopStyleVar(3);

    // restore the position for the Window
    g->Style.WindowMenuButtonPosition = ImGuiDir_Left;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
