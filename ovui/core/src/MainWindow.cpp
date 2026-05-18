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

#include "platform/Log.h"
#include "platform/CachedSetting.h"
#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/ContainerScope.h>
#include "platform/PlatformRegistry.h"
#include <omni/ui/Container.h>
#include <omni/ui/Frame.h>
#include <omni/ui/MainWindow.h>
#include <omni/ui/MenuBar.h>
#include <omni/ui/Style.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/windowmanager/IWindowCallbackManager.h>
#include <omni/ui/windowmanager/WindowManagerUtils.h>

#include <algorithm>
#include <functional>

OMNIUI_NAMESPACE_OPEN_SCOPE

static constexpr char kUiHiddeSettingPath[] = "/app/window/hideUi";

struct MainWindowPrivate
{
    // The window callback
    omni::ui::windowmanager::IWindowCallbackPtr windowCallback;

    // The foreground window callback
    omni::ui::windowmanager::IWindowCallbackPtr windowForegroundCallback;

    // The window callback
    std::unique_ptr<CachedBoolSetting> uiHidden;
};

MainWindow::MainWindow(bool showForeground) : m_prv{ std::make_unique<MainWindowPrivate>() }
{
    // Create a frame and don't push created object to any container.
    OMNIKIT_WITH_CONTAINER(nullptr)
    {
        auto frame = Frame::create();
        frame->setStyleTypeNameOverride("StatusBar");
        this->setStatusBarFrame(frame);
        // Without connectToGlobalStyle the frame's _getResolvedStyle()
        // returns null (the frame is created with no parent under
        // OMNIKIT_WITH_CONTAINER(nullptr)), so any application-side
        // ``ui.style.default["StatusBar"]`` rule is silently ignored —
        // _resolveStyleProperty falls through to its caller's hardcoded
        // default. Connect to the global style so the StatusBar
        // background/border/padding rules consumers register actually
        // take effect.
        Style::getInstance().connectToGlobalStyle(frame);

        auto mainFrame = Frame::create();
        mainFrame->setStyleTypeNameOverride("MainFrame");
        this->setMainFrame(mainFrame);
        // Same as above: without this connection the
        // ``_resolveStyleProperty(StyleColorProperty::eBackgroundColor)``
        // lookup at MainWindow::_draw line 207 always falls back to the
        // hardcoded ``0xFF1F2124``, making the host window background
        // unstyleable from the application side.
        Style::getInstance().connectToGlobalStyle(mainFrame);

        auto menuBar = MenuBar::create(true);
        menuBar->setStyleTypeNameOverride("MainMenuBar");
        menuBar->setMenuCompatibility(false);
        this->setMainMenuBar(menuBar);
        Style::getInstance().connectToGlobalStyle(menuBar);

        this->setCppStatusBarEnabled(false);
    }

    m_prv->uiHidden = std::make_unique<CachedBoolSetting>(kUiHiddeSettingPath, false);

    this->_setShowForegroundChangedFn([this](const bool& fg) {
        windowmanager::IWindowCallbackManager* windowCallbackManager =
            PlatformRegistry::instance().windowCallbackManager();
        if (!windowCallbackManager)
        {
            OMNIUI_LOG_ERROR("omni::ui::windowmanager::IWindowCallbackManager is not available");
            return;
        }

        if (fg && !this->m_prv->windowForegroundCallback)
        {
            this->m_prv->windowForegroundCallback = windowmanager::createWindowCallback(
                windowCallbackManager, "MainWindowForeground", 0, 0, omni::ui::windowmanager::DockPreference::eDisabled,
                [this](float elapsedTime) {
                    this->_drawForeground(elapsedTime);
                }
            );
        }
        else if (!fg && this->m_prv->windowForegroundCallback)
        {
            windowCallbackManager->removeWindowCallback(m_prv->windowForegroundCallback.get());
            m_prv->windowForegroundCallback.reset();
        }
    });

    setActive(true, showForeground);
}

MainWindow::~MainWindow()
{
    omni::ui::windowmanager::IWindowCallbackManager* windowCallbackManager =
        PlatformRegistry::instance().windowCallbackManager();
    if (windowCallbackManager)
    {
        if (m_prv->windowCallback)
        {
            windowCallbackManager->removeWindowCallback(m_prv->windowCallback.get());
            m_prv->windowCallback.reset();
        }

        if (m_prv->windowForegroundCallback)
        {
            windowCallbackManager->removeWindowCallback(m_prv->windowForegroundCallback.get());
            m_prv->windowForegroundCallback.reset();
        }
    }
    else
    {
        // If the windowCallbackManager was not valid, then we should manually detach this pointer.
        // Otherwise we get a segfault when its automatically destroyed as the stored pointer is not pointing to
        // valid memory anymore.
        OMNIUI_LOG_ERROR("omni.ui.MainWindow: Window callback not released properly");
        m_prv->windowCallback.reset();
        m_prv->windowForegroundCallback.reset();
    }

    this->destroy();
}

void MainWindow::setActive(bool active, bool showForeground)
{
    ui::windowmanager::IWindowCallbackManager* windowCallbackManager =
        PlatformRegistry::instance().windowCallbackManager();
    if (!windowCallbackManager)
    {
        OMNIUI_LOG_ERROR("omni::ui::windowmanager::IWindowCallbackManager is not available");
        return;
    }

    if (active && !m_prv->windowCallback)
    {
        m_prv->windowCallback = windowmanager::createWindowCallback(
            windowCallbackManager, "MainWindow", 0, 0, omni::ui::windowmanager::DockPreference::eDisabled,
            [this](float elapsedTime) {
                this->_draw(elapsedTime);
            }
        );
        this->setShowForeground(showForeground);
    }
    else if (!active && m_prv->windowCallback)
    {
        windowCallbackManager->removeWindowCallback(m_prv->windowCallback.get());
        m_prv->windowCallback.reset();
        this->setShowForeground(false);
    }
}

void MainWindow::destroy()
{
    this->destroyCallbacks();
}

void MainWindow::_draw(float elapsedTime)
{
    ImGuiViewport* viewport = ImGui::GetMainViewport();

    uint16_t popColorCount = 0;

    float statusBarHeight = 0.f;
    float menuBarHeight = 0.f;

    bool uiHidden = m_prv->uiHidden->get();

    if (!uiHidden && this->getMainMenuBar()->isVisible())
    {
        OMNIUI_PROFILE_ZONE("MainWindow menu layout");
        if (m_viewportSizeX != viewport->Size.x)
        {
            m_viewportSizeX = viewport->Size.x;
            this->getMainMenuBar()->forceWidthDirty(Widget::SizeDirtyReason::eParentDirty);
            this->getMainMenuBar()->forceHeightDirty(Widget::SizeDirtyReason::eParentDirty);
        }

        this->getMainMenuBar()->setComputedWidth(m_viewportSizeX);
        this->getMainMenuBar()->setComputedHeight(0.0f);

        menuBarHeight = this->getMainMenuBar()->getComputedContentHeight();
    }
    else
    {
        menuBarHeight = 0;
    }

    float marginX = 0.f;
    m_mainFrame->_resolveStyleProperty(StyleFloatProperty::eMarginWidth, &marginX);

    float marginY = 0.f;
    m_mainFrame->_resolveStyleProperty(StyleFloatProperty::eMarginHeight, &marginY);

    ImGui::SetNextWindowPos(ImVec2(viewport->Pos.x, viewport->Pos.y));
    ImGui::SetNextWindowSize(ImVec2(viewport->Size.x, viewport->Size.y));
    ImGui::SetNextWindowViewport(viewport->ID);

    ImGuiWindowFlags host_window_flags = 0;
    host_window_flags |=
        ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove;
    host_window_flags |= ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoNavFocus |
                         ImGuiWindowFlags_NoScrollWithMouse | ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_MenuBar;
    // if (dockspace_flags & ImGuiDockNodeFlags_PassthruCentralNode)
    //     host_window_flags |= ImGuiWindowFlags_NoBackground;

    uint32_t background_color = 0xFF1F2124;
    m_mainFrame->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &background_color);
    // Write the resolved MainFrame color into the BASE style for
    // ``ImGuiCol_WindowBg`` BEFORE PushStyleColor so the platform
    // layer's post-render clear (which reads the base, after the
    // PushStyleColor/PopStyleColor cycle has already restored) sees
    // our value rather than whatever ImGui initialised the slot to.
    // Without this, any 1-px gap between widgets (e.g. between the
    // MainMenuBar window and the host ``Begin("DockSpace")`` window)
    // is cleared to the legacy gray-blue, producing a visible band.
    {
        const float r = ((background_color >> 0)  & 0xFF) / 255.0f;
        const float g = ((background_color >> 8)  & 0xFF) / 255.0f;
        const float b = ((background_color >> 16) & 0xFF) / 255.0f;
        const float a = ((background_color >> 24) & 0xFF) / 255.0f;
        ImGui::GetStyle().Colors[ImGuiCol_WindowBg] = ImVec4(r, g, b, a);
    }
    ImGui::PushStyleColor(ImGuiCol_WindowBg, background_color);
    // Empty dock nodes (e.g. the strip immediately below the menu bar
    // before the first child node opens) default to ImGui's
    // ``ImGuiCol_DockingEmptyBg`` palette entry, which doesn't honor
    // the application-side ``MainFrame`` style. Mirror it so the strip
    // matches the host window background.
    ImGui::PushStyleColor(ImGuiCol_DockingEmptyBg, background_color);
    popColorCount += 1;
    popColorCount += 1;

    ImGui::PushStyleColor(ImGuiCol_WindowShadow, 0x00000000);
    popColorCount += 1;

    uint32_t menuBarBgColor = background_color;
    if (this->getMainMenuBar()->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &menuBarBgColor))
    {
        ImGui::PushStyleColor(ImGuiCol_MenuBarBg, menuBarBgColor);
        popColorCount += 1;
    }

    // ImGui::SetNextWindowBgAlpha(0.f);

    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(marginX, marginY));
    ImGuiContext* g = ImGui::GetCurrentContext();
    g->Style.WindowMenuButtonPosition = ImGuiDir_Right;

    const bool dockspaceHostOpen = ImGui::Begin("DockSpace", nullptr, host_window_flags);
    // WindowPadding is only required for the host window's Begin() layout.
    // Leave it off the stack while drawing the menu so File/Edit/etc. popups
    // inherit the same padding they had when the menu lived in its own window.
    ImGui::PopStyleVar();

    if (dockspaceHostOpen)
    {
        if (!uiHidden)
        {
            OMNIUI_PROFILE_ZONE("MainWindow menu draw");
            // draw the main menu bar
            this->getMainMenuBar()->draw(elapsedTime);
        }

        ImVec2 cursor = viewport->Pos;
        float dockSplitterSize = ImGui::GetStyle().DockingSeparatorSize;

        // ImGui 1.92+ checks that any SetCursorPos/SetCursorScreenPos that
        // extends parent boundaries is followed by a submitted item (see
        // ErrorCheckUsingSetCursorPosToExtendParentBoundaries). The patterns
        // below preserve the original layout behavior while keeping every
        // cursor advance backed by a real item submission, which avoids
        // per-frame "Code uses SetCursorPos()/SetCursorScreenPos() to extend
        // window/parent boundaries" errors when the status bar has no
        // children or when the dockspace central node is empty.

        // if visible draw the status frame at the bottom of the window —
        // skip the cursor jump entirely when the frame has no laid-out
        // content, since an empty Frame::draw submits no items and the
        // SetCursorScreenPos to the viewport bottom would otherwise be
        // unclaimed.
        if (!uiHidden && this->getStatusBarFrame()->isVisible())
        {
            this->getStatusBarFrame()->setComputedWidth(viewport->Size.x);
            this->getStatusBarFrame()->setComputedHeight(0); // this will force a compute layout from Omni.ui

            statusBarHeight = (uint16_t)this->getStatusBarFrame()->getComputedHeight();

            const bool hasStatusBarContent = statusBarHeight > 0 || this->getCppStatusBarEnabled();
            if (hasStatusBarContent)
            {
                ImGui::SetCursorScreenPos(ImVec2(0, viewport->Size.y - statusBarHeight));
                this->getStatusBarFrame()->draw(elapsedTime);

                if (statusBarHeight == 0 && this->getCppStatusBarEnabled())
                {
                    statusBarHeight = ImGui::GetFrameHeightWithSpacing() + dockSplitterSize;
                }
            }
        }

        // Restore cursor to the host-window origin and advance by the same
        // amount the legacy ui.DockSpace(None) path used for the separate menu
        // strip: DOCKSPACE_TOP_PADDING (menu height - 1) plus the active ImGui
        // docking separator size. This preserves the old dock content height
        // when the application uses MainWindow's internal docker.
        const float dockspaceTopPadding = menuBarHeight + std::max(dockSplitterSize - 1.0f, 0.0f);
        ImGui::SetCursorScreenPos(cursor);
        ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(0.0f, 0.0f));
        ImGui::Dummy(ImVec2(0.0f, dockspaceTopPadding));
        ImGui::PopStyleVar();

        // draw the dockspace
        // ``PassthruCentralNode`` makes the central (no-children) node
        // transparent so the host window's ``WindowBg`` (i.e. the
        // MainFrame-styled background) shows through any unoccupied
        // strip — e.g. the band below the menu bar before child
        // nodes start. Without this flag, ImGui paints the central
        // node with ``DockingEmptyBg`` which doesn't honor
        // application-side MainFrame style.
        ImGuiDockNodeFlags dockspaceFlags =
            ImGuiDockNodeFlags_NoWindowMenuButton | ImGuiDockNodeFlags_PassthruCentralNode;
        ImGuiID dockspaceId = ImGui::GetID("MyDockspace");

        ImGui::DockSpace(dockspaceId, ImVec2(0.0f, viewport->Size.y - statusBarHeight - dockspaceTopPadding),
                         dockspaceFlags, nullptr);

        uint32_t menuUnderlineColor = 0xFF262626;
        this->getMainMenuBar()->_resolveStyleProperty(StyleColorProperty::eBorderColor, &menuUnderlineColor);
        ImDrawList* foregroundDrawList = ImGui::GetForegroundDrawList();
        const float underlineY0 = viewport->Pos.y + menuBarHeight + 1.0f;
        const float underlineY1 = viewport->Pos.y + menuBarHeight + 3.0f;
        float segmentX0 = viewport->Pos.x + 4.0f;
        const float segmentX1 = viewport->Pos.x + viewport->Size.x - 4.0f;

        ImGui::GetBackgroundDrawList()->AddRectFilled(ImVec2(segmentX0, underlineY0), ImVec2(segmentX1, underlineY1),
                                                      menuUnderlineColor);

        ImGuiContext& popupContext = *ImGui::GetCurrentContext();
        for (const ImGuiPopupData& popupData : popupContext.OpenPopupStack)
        {
            ImGuiWindow* popupWindow = popupData.Window;
            if (!popupWindow)
                continue;
            const ImRect popupRect = popupWindow->Rect();
            if (popupRect.Max.y <= underlineY0 || popupRect.Min.y >= underlineY1 ||
                popupRect.Max.x <= segmentX0 || popupRect.Min.x >= segmentX1)
            {
                continue;
            }
            if (popupRect.Min.x > segmentX0)
            {
                foregroundDrawList->AddRectFilled(ImVec2(segmentX0, underlineY0),
                                                  ImVec2(std::min(popupRect.Min.x, segmentX1), underlineY1),
                                                  menuUnderlineColor);
            }
            segmentX0 = std::max(segmentX0, popupRect.Max.x);
        }
        if (segmentX0 < segmentX1)
        {
            foregroundDrawList->AddRectFilled(ImVec2(segmentX0, underlineY0), ImVec2(segmentX1, underlineY1),
                                              menuUnderlineColor);
        }
    }
    ImGui::End();

    ImGui::PopStyleColor(popColorCount);
    ImGui::PopStyleVar(2);

    // restore the position for the Window
    g->Style.WindowMenuButtonPosition = ImGuiDir_Left;
}

void MainWindow::_drawForeground(float elapsedTime)
{
    // To hide everything, we create a window and make it focused. So it's on
    // the top. The problem is that ImGui puts on tom a newly-created window. So
    // if a window is created after this one, it will be on the top for a frame.
    // We need to make sure that this callback is the latest one to avoid it.

    omni::ui::windowmanager::IWindowCallbackManager* windowCallbackManager =
        PlatformRegistry::instance().windowCallbackManager();

    size_t callbackCount = windowCallbackManager->getWindowCallbackCount();
    omni::ui::windowmanager::IWindowCallback* lastCallback =
        windowCallbackManager->getWindowCallbackAt(callbackCount - 1);

    if (lastCallback != m_prv->windowForegroundCallback.get())
    {
        // It's not the latest calback in the list. We need to move it.

        // Find the id of the current callback
        size_t currentCallbackId;
        for (currentCallbackId = 0; currentCallbackId < callbackCount; ++currentCallbackId)
        {
            omni::ui::windowmanager::IWindowCallback* currentCallback =
                windowCallbackManager->getWindowCallbackAt(currentCallbackId);
            if (currentCallback == m_prv->windowForegroundCallback.get())
            {
                break;
            }
        }

        // Delete the current callback and put it to the end of the list.
        omni::ui::windowmanager::WindowSet* windowSet = m_prv->windowForegroundCallback->getWindowSet();
        windowCallbackManager->removeWindowSetCallback(windowSet, m_prv->windowForegroundCallback.get());
        windowCallbackManager->addWindowSetCallback(windowSet, m_prv->windowForegroundCallback.get());

        // Since the current callback is at the end of the line, the callback
        // that was the next has the id the current one had before. We need to
        // call it, otherwise, it will be skipped.
        omni::ui::windowmanager::IWindowCallback* nextCallback =
            windowCallbackManager->getWindowCallbackAt(currentCallbackId);
        nextCallback->draw(elapsedTime);
    }

    // Create an empty focused window
    ImGuiViewport* viewport = ImGui::GetMainViewport();

    ImGuiWindowFlags foreground_window_flags = ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize |
                                               ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoScrollbar |
                                               ImGuiWindowFlags_NoScrollWithMouse | ImGuiWindowFlags_NoCollapse |
                                               ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoMouseInputs;

    ImGui::SetNextWindowPos(ImVec2(viewport->Pos.x, viewport->Pos.y));
    ImGui::SetNextWindowSize(ImVec2(viewport->Size.x, viewport->Size.y));
    ImGui::SetNextWindowFocus();

    ImGui::Begin("MainWindow Foreground", nullptr, foreground_window_flags);
    ImGui::End();
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
