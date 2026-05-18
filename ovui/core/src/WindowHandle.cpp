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
#include "platform/Log.h"
#include "platform/PlatformRegistry.h"
#include "platform/IUiRenderer.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/WindowHandle.h>
#include <omni/ui/Workspace.h>
#include <omni/ui/windowmanager/IWindowCallbackManager.h>

#include <algorithm>
#include <functional>

OMNIUI_NAMESPACE_OPEN_SCOPE

#define _GET_WINDOW(WINDOW, ID, RESULT)                                                                                \
    if (ID == 0)                                                                                                       \
    {                                                                                                                  \
        return RESULT;                                                                                                 \
    }                                                                                                                  \
    ImGuiWindow* WINDOW = ImGui::FindWindowByID(ID);                                                                   \
    if (!WINDOW)                                                                                                       \
    {                                                                                                                  \
        return RESULT;                                                                                                 \
    }

/**
 * @brief Move the selected window in the docking space to the begin of the
 * window list.
 */
static void _moveVisibleOnFront(ImGuiDockNode* node)
{
    auto found = std::find(node->Windows.begin(), node->Windows.end(), node->VisibleWindow);
    if (found != node->Windows.end())
    {
        auto window = *found;
        node->Windows.erase(found);
        node->Windows.push_front(window);
    }
}

WindowHandle::WindowHandle(uint32_t windowId) : m_windowId{ windowId }
{
    IUiRenderer* renderer = PlatformRegistry::instance().renderer();
    if (renderer)
    {
        renderer->waitForInit();
    }
}

WindowHandle::~WindowHandle() = default;

std::string WindowHandle::getTitle() const
{
    _GET_WINDOW(window, m_windowId, {});

    return window->Name;
}

float WindowHandle::getPositionX() const
{
    _GET_WINDOW(window, m_windowId, {});

    return window->Pos.x / Workspace::getDpiScale();
}

void WindowHandle::setPositionX(const float& positionX)
{
    _GET_WINDOW(window, m_windowId, );

    ImGui::SetWindowPos(window, { positionX * Workspace::getDpiScale(), window->Pos.y }, ImGuiCond_Always);
}

float WindowHandle::getPositionY() const
{
    _GET_WINDOW(window, m_windowId, {});

    return window->Pos.y / Workspace::getDpiScale();
}

void WindowHandle::setPositionY(const float& positionY)
{
    _GET_WINDOW(window, m_windowId, );

    ImGui::SetWindowPos(window, { window->Pos.x, positionY * Workspace::getDpiScale() }, ImGuiCond_Always);
}

float WindowHandle::getWidth() const
{
    _GET_WINDOW(window, m_windowId, {});

    return window->Size.x / Workspace::getDpiScale();
}

void WindowHandle::setWidth(const float& width)
{
    _GET_WINDOW(window, m_windowId, );

    ImVec2 size = ImFloor(ImVec2{ width * Workspace::getDpiScale(), window->Size.y });

    ImGui::SetWindowSize(window, size, ImGuiCond_Always);

    // If it's docked we need to set the dock size. DockBuilderSetNodeSize dosn't work.
    ImGuiDockNode* node = ImGui::DockBuilderGetNode(window->DockId);
    if (!node)
    {
        return;
    }

    node->Size.x = node->SizeRef.x = size.x;
    ImGuiDockNode* parent = node->ParentNode;
    if (!parent)
    {
        return;
    }

    if (parent->SplitAxis != ImGuiAxis_X)
    {
        return;
    }

    // Set the size of the sibling if possible
    ImGuiDockNode* sibling = nullptr;
    if (parent->ChildNodes[0] == node)
    {
        sibling = parent->ChildNodes[1];
    }
    else
    {
        sibling = parent->ChildNodes[0];
    }

    if (!sibling)
    {
        return;
    }

    sibling->Size.x = sibling->SizeRef.x = parent->Size.x - size.x;
}

float WindowHandle::getHeight() const
{
    _GET_WINDOW(window, m_windowId, {});

    return window->Size.y / Workspace::getDpiScale();
}

void WindowHandle::setHeight(const float& height)
{
    _GET_WINDOW(window, m_windowId, );

    ImVec2 size = ImFloor(ImVec2{ window->Size.x, height * Workspace::getDpiScale() });

    ImGui::SetWindowSize(window, size, ImGuiCond_Always);

    // If it's docked we need to set the dock size. DockBuilderSetNodeSize dosn't work.
    ImGuiDockNode* node = ImGui::DockBuilderGetNode(window->DockId);
    if (!node)
    {
        return;
    }

    node->Size.y = node->SizeRef.y = size.y;
    ImGuiDockNode* parent = node->ParentNode;
    if (!parent)
    {
        return;
    }

    if (parent->SplitAxis != ImGuiAxis_Y)
    {
        return;
    }

    // Set the size of the sibling if possible
    ImGuiDockNode* sibling = nullptr;
    if (parent->ChildNodes[0] == node)
    {
        sibling = parent->ChildNodes[1];
    }
    else
    {
        sibling = parent->ChildNodes[0];
    }

    if (!sibling)
    {
        return;
    }

    sibling->Size.y = sibling->SizeRef.y = parent->Size.y - size.y;
}

void WindowHandle::undock()
{
    _GET_WINDOW(window, m_windowId, );

    ImGui::DockBuilderDockWindow(window->Name, 0);
}

void WindowHandle::dockIn(const std::shared_ptr<WindowHandle>& targetWindow, const DockPosition& dockPosition, float ratio)
{
    if (!targetWindow)
    {
        return;
    }

    _GET_WINDOW(window, m_windowId, );

    // First we find the target window and its DockId
    _GET_WINDOW(target, targetWindow->m_windowId, );

    // True if it's a root docking space
    bool isRoot = false;

    ImGuiID targetDockId;
    if (strcmp(target->Name, "DockSpace") == 0)
    {
        // Special case for the root docking node. "DockSpace" window doesn't have any docking ID, we need to find it
        // manually. We use ImHashStr because ImGetID returns different result deppending on the window it's called
        // into. "MyDockspace" is the name of the root docking node and it's defined in EditorWindow.cpp.
        targetDockId = ImHashStr("MyDockspace", 0, target->ID);
        OMNIUI_ASSERT(ImGui::DockBuilderGetNode(targetDockId));
        isRoot = true;
    }
    else
    {
        targetDockId = target->DockId;
    }

    if (targetDockId == 0)
    {
        return;
    }

    if (dockPosition == DockPosition::eSame)
    {
        ImGuiDockNode* node = ImGui::DockBuilderGetNode(window->DockId);
        ImGuiDockNode* targetNode = ImGui::DockBuilderGetNode(target->DockId);

        if (node && targetNode && node->ParentNode && targetNode->ParentNode &&
            node->ParentNode->ID == targetNode->ParentNode->ID)
        {
            // The windows was already docked together like Left-Right, and now we want to merge them together. We
            // do it twice because at the first time ImGui rebuilds the docking tree and the docking node ID we want
            // will become different.
            ImGui::DockBuilderDockWindow(window->Name, targetDockId);
            targetDockId = target->DockId;
        }

        ImGui::DockBuilderDockWindow(window->Name, targetDockId);

        if (isRoot && !ImGui::DockBuilderGetNode(window->DockId))
        {
            // It happened when the user closed the only window in the docking space. In this way, the docking space is
            // broken, and ImGui will crash when we try to change it. Normally ImGui will rebuild the docking space as
            // soon as the user docks another window anywhere. But we need to dock the window right now. So we remove
            // everything and try to dock again.
            auto* ctx = ImGui::GetCurrentContext();
            ImGui::DockContextClearNodes(ctx, targetDockId, true);
            ImGui::DockBuilderDockWindow(window->Name, targetDockId);
        }
    }
    else
    {
        // then we split using the Ratio
        ImGuiID outIdAtDir;
        ImGuiID outIdAtOppositeDir;
        ImGuiID nodeId =
            ImGui::DockBuilderSplitNode(targetDockId, (ImGuiDir)(dockPosition), ratio, &outIdAtDir, &outIdAtOppositeDir);

        // we insert the window into the new Dock Nodes
        ImGui::DockBuilderDockWindow(window->Name, outIdAtDir);
        ImGui::DockBuilderDockWindow(target->Name, outIdAtOppositeDir);

        // We don't need to inherit the flags of the old docking node. If the user wants, he can set the flags
        // explicitly.
        ImGuiDockNode* windowDockNode = ImGui::DockBuilderGetNode(window->DockId);
        ImGuiDockNode* targetDockNode = ImGui::DockBuilderGetNode(target->DockId);
        if (windowDockNode)
        {
            windowDockNode->LocalFlags = 0;
        }
        else
        {
            // Skip docking DockSpace node.
            window->DockId = 0;
        }
        if (targetDockNode)
        {
            targetDockNode->LocalFlags = 0;
        }
        else
        {
            // Skip docking DockSpace node.
            target->DockId = 0;
        }

        // when its done you have to finalize the building for the parent node
        ImGui::DockBuilderFinish(nodeId);
    }
}

int32_t WindowHandle::getDockOrder() const
{
    _GET_WINDOW(window, m_windowId, -1);
    return static_cast<int32_t>(window->DockOrder);
}

void WindowHandle::setDockOrder(const int32_t& dockOrder)
{
    _GET_WINDOW(window, m_windowId, );
    ImGuiDockNode* node = ImGui::DockBuilderGetNode(window->DockId);
    if (!node || !node->TabBar)
    {
        return;
    }
    // Get the list of all the tabs in the current dock node
    auto& tabs = node->TabBar->Tabs;

    // Erase the window from the tabs.
    auto found = std::find_if(tabs.begin(), tabs.end(), [window](const ImGuiTabItem& it) { return it.Window == window; });
    if (found == tabs.end())
    {
        return;
    }

    // Keep the copy of the current item
    auto item = *found;
    tabs.erase(found);

    // Insert the item to the new position according to the order
    int32_t newPosition = std::max(std::min(dockOrder, tabs.size()), 0);
    tabs.insert(tabs.begin() + newPosition, item);

    // Save the position in window so it's possible to query it
    window->DockOrder = newPosition;
    // We can't use `ImGui::GetCurrentWindow()` because we use ImGui dso and ImGuiContext is not exported.
    // GetCurrentWindow sets this flag.
    window->WriteAccessed = true;
}

bool WindowHandle::isDocked() const
{
    _GET_WINDOW(window, m_windowId, false);
    return window->DockIsActive;
}

uint32_t WindowHandle::getDockId() const
{
    _GET_WINDOW(window, m_windowId, 0);

    if (strcmp(window->Name, "DockSpace") == 0)
    {
        // Special case for the root docking node. "DockSpace" window doesn't have any docking ID, we need to find it
        // manually. We use ImHashStr because ImGetID returns different result deppending on the window it's called
        // into. "MyDockspace" is the name of the root docking node and it's defined in EditorWindow.cpp.
        ImGuiID dockId = ImHashStr("MyDockspace", 0, window->ID);
        OMNIUI_ASSERT(ImGui::DockBuilderGetNode(dockId));

        return dockId;
    }

    if (!window->DockNode)
    {
        return 0;
    }

    return window->DockId;
}

bool WindowHandle::isVisible() const
{
    // if it is a ui.Window. it will call ui.Window's isVisible() method
    // while we are here, the window is destroyed
    // we should really remove this API. However, we have many tests depends on this API.
    // Let's keep it for now. But return false for now.
    // return none in python binding.
    OMNIUI_LOG_WARN("Calling isVisible to WindowHandle in c++ will be deprecated. Use isVisible to Window instead!");
    return false;
}

void WindowHandle::setVisible(const bool& visible)
{
    OMNIUI_LOG_WARN("Calling setVisible to WindowHandle will be deprecated. Use setVisible to Window instead!");
}

bool WindowHandle::isDockTabBarVisible() const
{
    _GET_WINDOW(window, m_windowId, false);

    ImGuiDockNode* node = ImGui::DockBuilderGetNode(window->DockId);
    if (!node)
    {
        return false;
    }

    return !(node->LocalFlags & ImGuiDockNodeFlags_HiddenTabBar);
}

void WindowHandle::setDockTabBarVisible(const bool& visible)
{
    _GET_WINDOW(window, m_windowId, );

    ImGuiDockNode* node = ImGui::DockBuilderGetNode(window->DockId);
    if (!node)
    {
        return;
    }

    if (visible)
    {
        node->LocalFlags &= ~ImGuiDockNodeFlags_HiddenTabBar;
    }
    else
    {
        node->LocalFlags |= ImGuiDockNodeFlags_HiddenTabBar;

        // ImGui bug: When ImGuiDockNodeFlags_HiddenTabBar is set, the node
        // shows the first window in the list instead of the one specified in
        // VisibleWindow.
        _moveVisibleOnFront(node);
    }
}

bool WindowHandle::isDockTabBarEnabled() const
{
    _GET_WINDOW(window, m_windowId, false);

    ImGuiDockNode* node = ImGui::DockBuilderGetNode(window->DockId);
    if (!node)
    {
        return false;
    }

    return !(node->LocalFlags & ImGuiDockNodeFlags_NoTabBar);
}

void WindowHandle::setDockTabBarEnabled(const bool& enabled)
{
    _GET_WINDOW(window, m_windowId, );

    ImGuiDockNode* node = ImGui::DockBuilderGetNode(window->DockId);
    if (!node)
    {
        return;
    }

    if (enabled)
    {
        node->LocalFlags &= ~ImGuiDockNodeFlags_NoTabBar;
    }
    else
    {
        node->LocalFlags |= ImGuiDockNodeFlags_NoTabBar;

        // ImGui bug: When ImGuiDockNodeFlags_NoTabBar is set, the node shows
        // the first window in the list instead of the one specified in
        // VisibleWindow.
        _moveVisibleOnFront(node);
    }
}

void WindowHandle::focus()
{
    _GET_WINDOW(window, m_windowId, );
    ImGui::FocusWindow(window);

    if (this->isDocked())
    {
        ImGuiDockNode* node = ImGui::DockBuilderGetNode(window->DockId);

        if (!node)
        {
            return;
        }

        // ImGui 1.92.7 commented out the tab selection code in FocusWindow()
        // (for #2304). We need to explicitly select the tab when focusing a docked window.
        node->SelectedTabId = window->TabId;
        if (node->TabBar)
        {
            node->TabBar->SelectedTabId = node->TabBar->NextSelectedTabId = window->TabId;
        }

        if (node->LocalFlags & ImGuiDockNodeFlags_NoTabBar)
        {
            // ImGui bug: When ImGuiDockNodeFlags_NoTabBar is set, the node shows the first window in the list instead
            // of the one specified in VisibleWindow.
            auto found = std::find(node->Windows.begin(), node->Windows.end(), window);
            if (found != node->Windows.begin() && found != node->Windows.end())
            {
                node->Windows.erase(found);
                node->Windows.push_front(window);
            }
        }
    }
}

bool WindowHandle::isSelectedInDock()
{
    _GET_WINDOW(window, m_windowId, false);

    if (!this->isDocked())
    {
        return false;
    }

    return _isWindowSelectedInDock(window);
}

bool WindowHandle::_isWindowSelectedInDock(void* window)
{
    ImGuiWindow* imguiWindow = reinterpret_cast<ImGuiWindow*>(window);
    ImGuiDockNode* node = ImGui::DockBuilderGetNode(imguiWindow->DockId);
    // ImGui 1.92.7 stores window->TabId (window->GetID("#TAB")) in SelectedTabId,
    // whereas older ImGui stored window->ID directly.
    return node && node->SelectedTabId == imguiWindow->TabId;
}

void WindowHandle::notifyAppWindowChange(AppWindowHandle newAppWindow)
{
}

#undef _GET_WINDOW

OMNIUI_NAMESPACE_CLOSE_SCOPE
