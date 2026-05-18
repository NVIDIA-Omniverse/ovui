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
#include "platform/IUiPlatform.h"
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Profile.h>
#include <omni/ui/Window.h>
#include <omni/ui/WindowHandle.h>
#include <omni/ui/Workspace.h>
#include <omni/ui/windowmanager/IWindowCallbackManager.h>

#include <algorithm>
#include <functional>
#include <iterator>
#include <map>


OMNIUI_NAMESPACE_OPEN_SCOPE

// All the alive ovui windows.
// TODO: Workspace should be a singleton and g_windows should go there.
static std::vector<std::weak_ptr<Window>> g_windows;

// Strong references to keep windows alive when the platform requires it
// (see IUiPlatform::needsStrongWindowRefs). In Kit the framework keeps Window
// shared_ptrs alive, but in standalone the only reference may be a Python
// temporary which can be dropped before the draw loop runs.
// OmitWindow removes from both lists, so there are no leaks.
static std::vector<std::shared_ptr<Window>> g_windowStrongRefs;

/// Check if the platform needs strong window refs (cached after first call).
static bool platformNeedsStrongRefs()
{
    auto* platform = PlatformRegistry::instance().platform();
    return platform && platform->needsStrongWindowRefs();
}

// Callbacks to show window by name
static std::map<std::string, std::function<void(bool)>> g_showWindowFns;

// Callback for new windows
static std::function<void(const std::shared_ptr<WindowHandle>& window)> g_newWindowCallbackFn;

// Callback for window visiblity change
static std::vector<std::function<void(const std::string& title, bool visible)>> g_windowVisiblityChangedCallbackFn;

/**
 * @brief Looking for a window in g_windows. It's very close to std::find if with a small weak_ptr improvement. It
 * removes deleted windows and it locks weak_ptr before calling the callback.
 */
template <class UnaryPredicate>
const std::vector<std::weak_ptr<Window>>::iterator _findInWindows(std::vector<std::weak_ptr<Window>>& windows,
                                                                  UnaryPredicate condition)
{
    auto iterator = windows.begin();
    for (; iterator != windows.end();)
    {
        auto current = iterator->lock();

        if (!current)
        {
            iterator = windows.erase(iterator);
        }
        else
        {
            if (condition(current))
            {
                return iterator;
            }

            iterator++;
        }
    }

    return windows.end();
}

Workspace::AppWindow& Workspace::AppWindow::instance()
{
    static Workspace::AppWindow instance;
    return instance;
}

AppWindowHandle Workspace::AppWindow::getCurrent()
{
    if (m_stack.empty())
    {
        auto* platform = PlatformRegistry::instance().platform();
        return platform ? platform->getDefaultAppWindowHandle() : nullptr;
    }

    return m_stack.top();
}

void Workspace::AppWindow::push(AppWindowHandle window)
{
    m_stack.push(window);
}

void Workspace::AppWindow::pop()
{
    m_stack.pop();
}

Workspace::AppWindowGuard::AppWindowGuard(AppWindowHandle window)
{
    AppWindow::instance().push(window);
}

Workspace::AppWindowGuard::~AppWindowGuard()
{
    AppWindow::instance().pop();
}

float Workspace::getDpiScale()
{
    auto* platform = PlatformRegistry::instance().platform();
    if (!platform)
    {
        return 1.0f;
    }

    AppWindowHandle appWindow = platform->getDefaultAppWindowHandle();
    if (!appWindow)
    {
        return 1.0f;
    }

    return platform->getAppWindowDpiScale(appWindow);
}

std::vector<std::shared_ptr<WindowHandle>> Workspace::getWindows()
{
    std::vector<std::shared_ptr<WindowHandle>> result;

    auto* ctx = ImGui::GetCurrentContext();
    if (!ctx)
    {
        return {};
    }

    return Workspace::_getWindows(&ctx->Windows, true);
}

std::shared_ptr<WindowHandle> Workspace::getWindow(const std::string& title)
{
    // If it's an ovui window, return the actual Window object, not handle.
    auto foundInOmniUi = _findInWindows(
        g_windows, [&title](const std::shared_ptr<Window>& it) { return it->isValid() && it->getTitle() == title; });

    if (foundInOmniUi != g_windows.end())
    {
        return foundInOmniUi->lock();
    }

    // Try to find it through ImGui windows.
    auto* ctx = ImGui::GetCurrentContext();
    if (!ctx)
    {
        return {};
    }
    const auto& windows = ctx->Windows;

    auto found = std::find_if(windows.begin(), windows.end(),
                              [&title](const ImGuiWindow* it)
                              { return it && (it->Flags & ImGuiWindowFlags_NoSavedSettings) == 0 && title == it->Name; });

    if (found == windows.end())
    {
        return {};
    }

    ImGuiID windowId = (*found)->ID;
    // Every time create a handle.
    return std::shared_ptr<WindowHandle>{ new WindowHandle{ windowId } };
}

std::shared_ptr<WindowHandle> Workspace::getWindowFromCallback(const windowmanager::IWindowCallback* callback)
{
    // If it's an ovui window, return the actual Window object, not handle.
    auto foundInOmniUi = _findInWindows(
        g_windows, [&callback](const std::shared_ptr<Window>& it) { return it->getWindowCallback() == callback; });

    if (foundInOmniUi != g_windows.end())
    {
        return foundInOmniUi->lock();
    }

    return {};
}

static ImGuiDockNode* getImguiDockNode(uint32_t dockId)
{
    return ImGui::GetCurrentContext() ? ImGui::DockBuilderGetNode(dockId) : nullptr;
}

std::vector<std::shared_ptr<WindowHandle>> Workspace::getDockedNeighbours(const std::shared_ptr<WindowHandle>& member)
{
    auto* ctx = ImGui::GetCurrentContext();
    if (!ctx)
    {
        return {};
    }

    const auto& windows = ctx->Windows;

    ImGuiID windowId = member->m_windowId;
    auto found = std::find_if(
        windows.begin(), windows.end(), [windowId](const ImGuiWindow* it) { return it && it->ID == windowId; });

    if (found == windows.end())
    {
        return {};
    }

    ImGuiID dockId;
    if (strcmp((*found)->Name, "DockSpace") == 0)
    {
        // Special case for the root docking node. "DockSpace" window doesn't have any docking ID, we need to find it
        // manually. We use ImHashStr because ImGetID returns different result deppending on the window it's called
        // into. "MyDockspace" is the name of the root docking node and it's defined in EditorWindow.cpp.
        dockId = ImHashStr("MyDockspace", 0, (*found)->ID);
        OMNIUI_ASSERT(getImguiDockNode(dockId));
    }
    else
    {
        dockId = (*found)->DockId;
    }

    return Workspace::getDockedWindows(dockId);
}

uint32_t Workspace::getSelectedWindowIndex(uint32_t dockId)
{
    ImGuiDockNode* dockNode = getImguiDockNode(dockId);
    if (dockNode)
    {
        return dockNode->TabBar->SelectedTabId;
    }

    return 0;
}

void Workspace::clear()
{
    // Check for a valid context first
    auto* ctx = ImGui::GetCurrentContext();
    if (ctx)
    {
        ImGuiWindow* dockWindow = ImGui::FindWindowByName("DockSpace");
        if (dockWindow)
        {
            ImGuiID dockId = dockWindow->DockId;
            if (dockId)
            {
                // Remove content from the docking node. We can't use window->undock because we need to clear everything,
                // including empty docking spaces, because ImGui crashes when there is docking space with no window.
                ImGui::DockContextClearNodes(ctx, dockId, true);
            }
        }
    }

    // This is a little odd to run outside thie block above, but assumption is the functions below can handle the
    // no context case properly and still do work if needed.
    for (const auto& window : Workspace::getWindows())
    {
        if (window->getTitle() == "DockSpace")
        {
            continue;
        }

        window->undock();
    }

    // Release strong references to windows (used to keep windows alive when
    // the platform requires it, e.g. standalone mode where Python may drop
    // its temporary reference).
    g_windowStrongRefs.clear();
}

float Workspace::getMainWindowWidth()
{
    auto* platform = PlatformRegistry::instance().platform();
    if (!platform)
    {
        return 0;
    }
    AppWindowHandle appWindow = platform->getDefaultAppWindowHandle();
    OMNIUI_ASSERT(appWindow);
    if (appWindow)
    {
        int w = 0, h = 0;
        platform->getWindowSize(1 /* default window */, &w, &h);
        return static_cast<float>(w) / Workspace::getDpiScale();
    }
    return 0;
}

float Workspace::getMainWindowHeight()
{
    auto* platform = PlatformRegistry::instance().platform();
    if (!platform)
    {
        return 0;
    }
    AppWindowHandle appWindow = platform->getDefaultAppWindowHandle();
    OMNIUI_ASSERT(appWindow);
    if (appWindow)
    {
        int w = 0, h = 0;
        platform->getWindowSize(1 /* default window */, &w, &h);
        return static_cast<float>(h) / Workspace::getDpiScale();
    }
    return 0;
}

std::vector<std::shared_ptr<WindowHandle>> Workspace::getDockedWindows(uint32_t dockId)
{
    ImGuiDockNode* dockNode = getImguiDockNode(dockId);
    if (!dockNode)
    {
        return {};
    }

    if (!dockNode->TabBar)
    {
        // This happens when the tab bar is not displayed. It's not ordered but the order is not important in this case.
        return Workspace::_getWindows(&dockNode->Windows);
    }

    auto& tabs = dockNode->TabBar->Tabs;

    ImVector<ImGuiWindow*> result;
    result.reserve(tabs.size());
    std::transform(
        tabs.begin(), tabs.end(), std::back_inserter(result), [](const ImGuiTabItem& tab) { return tab.Window; });
    return Workspace::_getWindows(&result);
}

uint32_t Workspace::getParentDockId(uint32_t dockId)
{
    ImGuiDockNode* dockNode = getImguiDockNode(dockId);
    if (!dockNode || !dockNode->ParentNode)
    {
        return 0;
    }

    return dockNode->ParentNode->ID;
}

bool Workspace::getDockNodeChildrenId(uint32_t dockId, uint32_t& first, uint32_t& second)
{
    ImGuiDockNode* dockNode = getImguiDockNode(dockId);
    if (!dockNode || !dockNode->ChildNodes[0] || !dockNode->ChildNodes[1])
    {
        return false;
    }

    first = dockNode->ChildNodes[0]->ID;
    second = dockNode->ChildNodes[1]->ID;

    return true;
}

WindowHandle::DockPosition Workspace::getDockPosition(uint32_t dockId)
{
    ImGuiDockNode* dockNode = getImguiDockNode(dockId);
    if (!dockNode)
    {
        return WindowHandle::DockPosition::eSame;
    }

    auto parentDockNode = dockNode->ParentNode;
    if (!parentDockNode)
    {
        return WindowHandle::DockPosition::eSame;
    }

    if (parentDockNode->SplitAxis == ImGuiAxis_X)
    {
        if (parentDockNode->ChildNodes[0] == dockNode)
        {
            return WindowHandle::DockPosition::eLeft;
        }
        if (parentDockNode->ChildNodes[1] == dockNode)
        {
            return WindowHandle::DockPosition::eRight;
        }
    }
    else if (parentDockNode->SplitAxis == ImGuiAxis_Y)
    {
        if (parentDockNode->ChildNodes[0] == dockNode)
        {
            return WindowHandle::DockPosition::eTop;
        }
        if (parentDockNode->ChildNodes[1] == dockNode)
        {
            return WindowHandle::DockPosition::eBottom;
        }
    }

    return WindowHandle::DockPosition::eSame;
}

float Workspace::getDockIdWidth(uint32_t dockId)
{
    ImGuiDockNode* dockNode = getImguiDockNode(dockId);
    if (!dockNode)
    {
        return 0.0f;
    }

    return dockNode->Size.x / Workspace::getDpiScale();
}

float Workspace::getDockIdHeight(uint32_t dockId)
{
    ImGuiDockNode* dockNode = getImguiDockNode(dockId);
    if (!dockNode)
    {
        return 0.0f;
    }

    return dockNode->Size.y / Workspace::getDpiScale();
}

void Workspace::setDockIdWidth(uint32_t dockId, float width)
{
    ImGuiDockNode* dockNode = getImguiDockNode(dockId);
    if (!dockNode)
    {
        return;
    }

    // Iterate the parents and find the docking nodes that located vertically
    ImGuiDockNode* parent = dockNode;
    ImGuiDockNode* sibling = nullptr;
    while (true)
    {
        dockNode = parent;
        parent = dockNode->ParentNode;

        if (!parent || !parent->ChildNodes[0] || !parent->ChildNodes[1])
        {
            return;
        }

        sibling = parent->ChildNodes[0] == dockNode ? parent->ChildNodes[1] : parent->ChildNodes[0];

        if (parent->SplitAxis != ImGuiAxis_Y)
        {
            break;
        }
    }

    // Desired size
    float size = width * Workspace::getDpiScale();

    // The current size and sibling size
    float total = dockNode->Size.x + sibling->Size.x;

    // Modify the current size
    dockNode->Size.x = dockNode->SizeRef.x = std::min(size, total);
    // Decrease the size of the sibling so the total size is the same
    sibling->Size.x = sibling->SizeRef.x = std::max(total - size, 0.0f);
}

void Workspace::setDockIdHeight(uint32_t dockId, float height)
{
    ImGuiDockNode* dockNode = getImguiDockNode(dockId);
    if (!dockNode)
    {
        return;
    }

    // Iterate the parents and find the docking nodes that located vertically
    ImGuiDockNode* parent = dockNode;
    ImGuiDockNode* sibling = nullptr;
    while (true)
    {
        dockNode = parent;
        parent = dockNode->ParentNode;

        if (!parent || !parent->ChildNodes[0] || !parent->ChildNodes[1])
        {
            return;
        }

        sibling = parent->ChildNodes[0] == dockNode ? parent->ChildNodes[1] : parent->ChildNodes[0];

        if (parent->SplitAxis != ImGuiAxis_X)
        {
            break;
        }
    }

    // Desired size
    float size = height * Workspace::getDpiScale();

    // The current size and sibling size
    float total = dockNode->Size.y + sibling->Size.y;

    // Modify the current size
    dockNode->Size.y = dockNode->SizeRef.y = std::min(size, total);
    // Decrease the size of the sibling so the total size is the same
    sibling->Size.y = sibling->SizeRef.y = std::max(total - size, 0.0f);
}

bool Workspace::showWindow(const std::string& title, bool show)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;
    // Check if the window is already exists
    std::shared_ptr<WindowHandle> alreadyCreated;
    for (const auto& window : Workspace::getWindows())
    {
        if (window && window->getTitle() == title)
        {
            alreadyCreated = window;
            break;
        }
    }

    if (alreadyCreated)
    {
        std::shared_ptr<Window> window = std::dynamic_pointer_cast<Window>(alreadyCreated);
        if (window)
        {
            // If the window is the omni::ui window, just make it visible.
            window->setVisible(show);
            return true;
        }
    }

    auto foundShowWindowFn = g_showWindowFns.find(title);
    if (foundShowWindowFn != g_showWindowFns.end())
    {
        // We have the callback to make the window visible.
        const auto& showWindowFn = foundShowWindowFn->second;
        showWindowFn(show);
        return false;
    }

    return true;
}

void Workspace::setShowWindowFn(const std::string& title, std::function<void(bool)> showWindowFn)
{
    if (!showWindowFn)
    {
        auto found = g_showWindowFns.find(title);
        if (found != g_showWindowFns.end())
        {
            g_showWindowFns.erase(found);
        }
    }
    else
    {
        g_showWindowFns[title] = std::move(showWindowFn);
    }
}

std::vector<std::string> Workspace::getShowWindowTitles()
{
    std::vector<std::string> titles;
    for (const auto& [title, _] : g_showWindowFns)
    {
        titles.push_back(title);
    }
    return titles;
}

void Workspace::setWindowCreatedCallback(
    std::function<void(const std::shared_ptr<WindowHandle>& window)> windowCreatedCallbackFn)
{
    g_newWindowCallbackFn = windowCreatedCallbackFn;
}

void Workspace::RegisterWindow(const std::shared_ptr<Window>& window)
{
    g_windows.emplace_back(window);
    if (platformNeedsStrongRefs())
    {
        g_windowStrongRefs.emplace_back(window);
    }
    if (g_newWindowCallbackFn)
        g_newWindowCallbackFn(window);
    // new window also is a window visiblity change event
    onWindowVisibilityChanged(window->getTitle(), window->isVisible());
}

void Workspace::OmitWindow(const Window* window)
{
    //omit window also is a window visiblity change event
    onWindowVisibilityChanged(window->getTitle(), false);
    auto found = _findInWindows(g_windows, [window](const std::shared_ptr<Window>& it) { return it.get() == window; });
    if (found != g_windows.end())
    {
        g_windows.erase(found);
    }
    // Remove from strong-ref list (breaks the prevent-premature-destruction ref)
    auto it = std::find_if(g_windowStrongRefs.begin(), g_windowStrongRefs.end(),
                           [window](const std::shared_ptr<Window>& w) { return w.get() == window; });
    if (it != g_windowStrongRefs.end())
    {
        g_windowStrongRefs.erase(it);
    }
}

std::vector<std::shared_ptr<WindowHandle>> Workspace::_getWindows(const void* windowsStorage, bool considerRegistered)
{
    const ImVector<ImGuiWindow*>* windows = reinterpret_cast<const ImVector<ImGuiWindow*>*>(windowsStorage);

    auto registeredWindows = g_windows;

    std::vector<std::shared_ptr<WindowHandle>> result;

    for (auto* window : *windows)
    {
        if (!window)
        {
            continue;
        }

        if (window->Flags & ImGuiWindowFlags_NoSavedSettings)
        {
            // Most likely it's a frame
            continue;
        }

        // If it's an ovui window (and has a window_ID from imGUI) return the actual Window object, not handle.
        ImGuiID windowId = window->ID;
        auto found = _findInWindows(
            registeredWindows, [windowId](const std::shared_ptr<Window>& it) { return it->m_windowId == windowId; });

        if (found != registeredWindows.end())
        {
            auto _win = found->lock();
            if (_win->isValid())
            {
                result.push_back(_win);
            }
            else
            {
                // the window has been destroyed, let's create a new handle for it.
                result.push_back(std::shared_ptr<WindowHandle>{ new WindowHandle{ windowId} });
            }
            registeredWindows.erase(found);
        }
        else
        {
            // It's not an ovui window - create a handle.
            result.push_back(std::shared_ptr<WindowHandle>{ new WindowHandle{ window->ID } });
        }
    }

    // This should just be any invisible windows left over
    if (considerRegistered)
    {
        for (auto& it : registeredWindows)
        {
            if (auto window = it.lock())
            {
                if (!window->isVirtual())
                {
                    result.push_back(window);
                }
            }
        }
    }

    return result;
}

uint32_t Workspace::setWindowVisibilityChangedCallback(std::function<void(const std::string& title, bool visible)> windowVisibilityChangedCallbackFn)
{
    //This prevents the vector size from growing indefinitely.
    for (uint32_t id = 0; id < g_windowVisiblityChangedCallbackFn.size(); id++)
    {
        if (g_windowVisiblityChangedCallbackFn[id] == nullptr)
        {
            g_windowVisiblityChangedCallbackFn[id] = windowVisibilityChangedCallbackFn;
            return id;
        }
    }
    uint32_t id = static_cast<uint32_t>(g_windowVisiblityChangedCallbackFn.size());
    g_windowVisiblityChangedCallbackFn.push_back(std::move(windowVisibilityChangedCallbackFn));
    return id;
}

void Workspace::removeWindowVisibilityChangedCallback(uint32_t id)
{
    if (id < g_windowVisiblityChangedCallbackFn.size())
    {
        // We don't remove it to keep the ids that we already returned. Instead, we make this function NULL, so it will be
        // skipped.
        g_windowVisiblityChangedCallbackFn[id] = nullptr;
    }
    else
    {
        OMNIUI_LOG_ERROR("Workspace::removeWindowVisibilityChangedCallback subscription was invalid");
    }
}

void Workspace::onWindowVisibilityChanged(const std::string& title, bool visible)
{
    OMNIUI_PROFILE_VERBOSE_FUNCTION;

    // Use an index based for-loop so any re-allocation from callback reaching setWindowVisibilityChangedCallback will not corrupt
    // iteration.  This relies on removeWindowVisibilityChangedCallback not shrinking the vector and callback not being used after
    // it has returned.
    for (size_t i = 0; i < g_windowVisiblityChangedCallbackFn.size(); ++i)
    {
        if (auto&& callback = g_windowVisiblityChangedCallbackFn[i])
        {
            callback(title, visible);
        }
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
