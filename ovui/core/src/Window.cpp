/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "platform/Assert.h"
#include "platform/CachedSetting.h"
#include "platform/Log.h"
#include "platform/PlatformRegistry.h"
#include "platform/IUiPlatform.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <omni/ui/Container.h>
#include <omni/ui/Frame.h>
#include <omni/ui/MenuBar.h>
#include <omni/ui/Profile.h>
#include <omni/ui/Style.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/Window.h>
#include <omni/ui/windowmanager/IWindowCallbackManager.h>
#include <omni/ui/windowmanager/WindowManagerUtils.h>

#include "WindowData.h"
#include "platform/IUiPlatform.h"

#include <functional>

OMNIUI_NAMESPACE_OPEN_SCOPE

constexpr char kWindowEnableDetachSettingsPath[] = "/exts/omni.ui/Window/enableDetach";
constexpr char kWindowDetachedDecorationsPath[] = "/exts/omni.ui/Window/detachedDecorations";
static constexpr char kDefaultRasterSettingsPath[] = "/exts/omni.ui/raster/default_rasterpolicy_enabled";

// The sorted list of modal windows from bottom to top. Only the top one is using BeginPopupModal.
static std::vector<const Window*> g_modals;

Window::WindowData::~WindowData()
{
    // Release deferred handles (cancels any pending deferred operations)
    m_deferredDestroyHandle.reset();
    m_windowCloseObserverHandle.reset();
}

// Height an ImGui title bar occupies for this window, whether or not it currently has one. The
// same as ImGuiWindow::TitleBarHeight, can't use it because of linking error.
float WindowTitleBarHeightUnconditional(ImGuiWindow* window)
{
    ImGuiContext* g = ImGui::GetCurrentContext();

    float scale = g->FontSize * window->FontWindowScale;
    if (window->ParentWindow)
    {
        scale *= window->ParentWindow->FontWindowScale;
    }

    return scale + g->Style.FramePadding.y * 2.0f;
}

// Height of the window title as currently drawn, so zero when the window has no title bar.
float WindowTitleBarHeight(ImGuiWindow* window)
{
    return (window->Flags & ImGuiWindowFlags_NoTitleBar) ? 0.0f : WindowTitleBarHeightUnconditional(window);
}

/**
 * @brief Whether detached windows should be created with window manager decorations.
 *
 * Off by default, which keeps the borderless window omni.ui has always created and moves and
 * resizes it from the ImGui title bar. On, the window manager owns move and resize, which is the
 * only thing that can work where a client cannot position itself -- notably Wayland -- at the cost
 * of showing the WM title bar above the ImGui one, which is kept either way because it carries the
 * menu that docks the window back.
 */
static bool _useDetachedDecorations()
{
    auto* settings = PlatformRegistry::instance().settings();
    if (!settings)
        return false;
    settings->setDefaultBool(kWindowDetachedDecorationsPath, false);
    return settings->getBool(kWindowDetachedDecorationsPath, false);
}

static AppWindowHandle _newOsWindow(const char* title, uint64_t x, uint64_t y, uint64_t width, uint64_t height)
{
    auto* platform = PlatformRegistry::instance().platform();
    if (!platform)
    {
        return nullptr;
    }

    return platform->createDetachedAppWindow(title, static_cast<int>(x), static_cast<int>(y),
                                              static_cast<int>(width), static_cast<int>(height));
}

static bool _isRasterByDefault()
{
    static omni::ui::CachedBoolSetting rasterByDefault(kDefaultRasterSettingsPath, false);
    return rasterByDefault.get();
}

Window::Window(const std::string& title, Window::DockPreference dockPrefence, WindowData* dataPtr)
    : WindowHandle{ 0 }
    , m_title{ title }
    , m_data(dataPtr ? dataPtr : new WindowData(dockPrefence))
{
    auto* settings = PlatformRegistry::instance().settings();
    if (settings)
    {
        settings->setDefaultBool(kWindowEnableDetachSettingsPath, true);
        m_data->m_enableWindowDetach = settings->getBool(kWindowEnableDetachSettingsPath, true);
    }

    this->setPositionXChangedFn(std::bind(&Window::_positionExplicitlyChanged, this));
    this->setPositionYChangedFn(std::bind(&Window::_positionExplicitlyChanged, this));
    this->setWidthChangedFn(std::bind(&Window::_sizeExplicitlyChanged, this));
    this->setHeightChangedFn(std::bind(&Window::_sizeExplicitlyChanged, this));
    this->setFlagsChangedFn(std::bind(&Window::setTopModal, this));
    this->setVisibilityChangedFn(
        [this](const auto& visible)
        {
            this->_removeFromModalStack();

            Workspace::onWindowVisibilityChanged(m_title, visible);

            bool isPopupOrModal = this->getFlags() & (kWindowFlagModal | kWindowFlagPopup);

            auto* platform = PlatformRegistry::instance().platform();
            AppWindowHandle defaultWindow = platform ? platform->getDefaultAppWindowHandle() : nullptr;

            if (visible)
            {
                this->_addToModalStack();

                // When the window is invisible, it's in the default application window. When it becomes visible, we
                // need to check from which window it's called, and if it's called from a separated window, we also need
                // to create a detached one.
                if (Workspace::AppWindow::instance().getCurrent() != defaultWindow && !isPopupOrModal)
                {
                    this->moveToNewOSWindow();
                }
            }
            else
            {
                // If it's a detached window, we need to destroy the application window.
                if (m_data->m_appWindow != defaultWindow && !isPopupOrModal)
                {
                    this->moveToMainOSWindow();
                }
            }
        });

    // Create a frame and don't push created object to any container.
    OMNIKIT_WITH_CONTAINER(nullptr)
    {
        auto frame = Frame::create();
        frame->setStyleTypeNameOverride("Window");
        this->setFrame(frame);

        auto menuBar = MenuBar::create(false);
        menuBar->setStyleTypeNameOverride("MenuBar");
        this->setMenuBar(menuBar);
    }

    // Set default style to the child layout.
    Style::getInstance().connectToGlobalStyle(this->getFrame());

    auto* platform = PlatformRegistry::instance().platform();
    if (platform && platform->isMultiWindowSupported())
    {
        m_data->m_multiOSWindowSupport = true;
    }

    m_data->m_appWindow = Workspace::AppWindow::instance().getCurrent();

    // Legacy behavior of createAppWindowCallback at 800x600 but auto-resize via m_width, m_height equal to 0,0 on first draw.
    //
    {
        float width, height;
        std::tie(width, height) = std::make_tuple(m_width, m_height);
        std::tie(m_width, m_height) = std::make_tuple(800.f, 600.f);

        setActive(true);

        // Restore to incoming value currently locker to (0, 0)
        //
        std::tie(m_width, m_height) = std::make_tuple(width, height);
    }

    if (_isRasterByDefault())
    {
        this->setRasterPolicy(RasterPolicy::eAuto);
    }
}

Window::Window(const std::string& title, WindowData* dataPtr) : Window(title, dataPtr->m_dockingPreference, dataPtr)
{
}

Window::~Window()
{
    ui::windowmanager::IWindowCallbackManager* uiWindowManager =
        PlatformRegistry::instance().windowCallbackManager();

    auto* platform = PlatformRegistry::instance().platform();
    AppWindowHandle defaultWindow = platform ? platform->getDefaultAppWindowHandle() : nullptr;

    // If it's a detached window, we need to destroy the application window.
    bool isPopupOrModal = this->getFlags() & (kWindowFlagModal | kWindowFlagPopup);
    if (m_data->m_appWindow != defaultWindow && !isPopupOrModal && uiWindowManager)
    {
        this->moveToMainOSWindow();
    }

    this->_removeFromModalStack();

    // Release deferred handles
    m_data->m_deferredDestroyHandle.reset();
    m_data->m_windowCloseObserverHandle.reset();

    if (uiWindowManager && m_data->m_uiWindow)
    {
        uiWindowManager->removeAppWindowCallback(m_data->m_appWindow, m_data->m_uiWindow.get());
        m_data->m_uiWindow.reset();
    }

    Workspace::OmitWindow(this);

    this->destroy();
}

void Window::setOwnerModule(const std::string& moduleName)
{
    m_data->m_ownerModule = moduleName;
}

const std::string& Window::getOwnerModule() const
{
    return m_data->m_ownerModule;
}

void Window::_detectFirstInteraction()
{
    if (m_data->m_firstInteractionReported)
    {
        return;
    }

    // Only count clicks landing inside this Window's content area (including its child windows).
    if (!ImGui::IsWindowHovered(ImGuiHoveredFlags_ChildWindows))
    {
        return;
    }

    // IsWindowHovered alone is also true over the title bar and near the resize borders of a
    // decorated window, so restrict to the inner (content) rect: moving or resizing a window
    // is not "using" the extension's UI. InnerRect excludes the title bar, menu bar, and
    // scrollbars. We are between ImGui::Begin/End for this window, so CurrentWindow is it.
    ImGuiWindow* imGuiWindow = ImGui::GetCurrentContext()->CurrentWindow;
    if (!imGuiWindow || !imGuiWindow->InnerRect.Contains(ImGui::GetMousePos()))
    {
        return;
    }

    if (!(ImGui::IsMouseClicked(ImGuiMouseButton_Left) ||
          ImGui::IsMouseClicked(ImGuiMouseButton_Right) ||
          ImGui::IsMouseClicked(ImGuiMouseButton_Middle)))
    {
        return;
    }

    m_data->m_firstInteractionReported = true;
    Workspace::onWindowFirstInteraction(m_title, m_data->m_ownerModule);
}

void Window::setActive(bool active)
{
    ui::windowmanager::IWindowCallbackManager* windowCallbackManager =
        PlatformRegistry::instance().windowCallbackManager();
    if (!windowCallbackManager)
    {
        OMNIUI_LOG_ERROR("omni::ui::windowmanager::IWindowCallbackManager is not available");
        return;
    }

    if (active && !m_data->m_uiWindow)
    {
        m_data->m_wasVisiblePreviousFrame = false;
        m_data->m_uiWindow = ui::windowmanager::createAppWindowCallback(m_data->m_appWindow, windowCallbackManager,
            this->getTitle().c_str(), (uint32_t) m_width, (uint32_t) m_height, (omni::ui::windowmanager::DockPreference) m_data->m_dockingPreference,
            [this](float elapsedTime) {
                this->_draw(m_title.c_str(), elapsedTime);
            }
        );
    }
    else if (!active && m_data->m_uiWindow)
    {
        windowCallbackManager->removeAppWindowCallback(m_data->m_appWindow, m_data->m_uiWindow.get());
        m_data->m_uiWindow.reset();
        m_data->m_wasVisiblePreviousFrame = false;
    }
}

void Window::destroy()
{
    m_frame->destroy();
    this->destroyCallbacks();
    m_data->m_destroyed = true;
}

void Window::notifyAppWindowChange(AppWindowHandle newAppWindow)
{
    m_data->m_appWindow = newAppWindow;

    // Only moveToNewOSWindow() knows whether the window it just created is decorated, and it sets
    // this again right after. Any other route -- back to the main window, or onto an app window
    // created elsewhere -- leaves omni.ui driving the frame itself, which is the default.
    m_data->m_osWindowDecorated = false;

    // Drop any drag in flight as well: the OS window it was moving is no longer ours, and a stale
    // grab offset would make the next detach jump if the button is still held.
    m_data->m_osWindowMoving = false;

    if (m_data->m_appWindow)
    {
        auto* platform = PlatformRegistry::instance().platform();
        bool isVirtual = platform ? platform->isAppWindowVirtual(m_data->m_appWindow) : false;
        this->_setVirtual(isVirtual);
        if (!isVirtual)
        {
            // Set up window close observer for OS windows
            if (platform)
            {
                m_data->m_windowCloseObserverHandle = platform->observeAppWindowClose(
                    newAppWindow,
                    [this]() {
                        // Kill both handles
                        m_data->m_windowCloseObserverHandle.reset();
                        m_data->m_deferredDestroyHandle.reset();
                        if (auto* platform = PlatformRegistry::instance().platform())
                        {
                            auto mainAppWindow = platform->getDefaultAppWindowHandle();
                            if (mainAppWindow && this->getAppWindow() != mainAppWindow)
                                this->moveToAppWindow(mainAppWindow);
                        }
                        this->setVisible(false);
                    });
            }
        }
    }
    _forceWindowState();
}

windowmanager::IWindowCallback* Window::getWindowCallback() const
{
    return m_data->m_uiWindow.get();
}


void Window::_forceWindowState()
{
    m_data->m_sizeExplicitlyChanged = true;
}

void Window::moveToAppWindow(AppWindowHandle newAppWindow)
{
    ui::windowmanager::IWindowCallbackManager* uiWindowManager =
        PlatformRegistry::instance().windowCallbackManager();

    uiWindowManager->moveCallbackToAppWindow(m_data->m_uiWindow.get(), newAppWindow);
    // A missing destination leaves the callback in its current set. Keep the
    // window's draw/input destination consistent with that actual owner.
    if (m_data->m_uiWindow && m_data->m_uiWindow->getWindowSet() &&
        m_data->m_uiWindow->getWindowSet() == uiWindowManager->getWindowSetByAppWindow(newAppWindow))
        this->notifyAppWindowChange(newAppWindow);
}

AppWindowHandle Window::getAppWindow() const
{
    return m_data->m_appWindow;
}

void Window::setTopModal() const
{
    if (this->_isTopModal())
    {
        return;
    }

    this->_removeFromModalStack();
    this->_addToModalStack();
}

float Window::getDpiScale()
{
    OMNIUI_LOG_ERROR_ONCE("[DEPRECATED] Window::getDpiScale is deprecated. Consider using Workspace::getDpiScale");

    return ImGui::GetWindowDpiScale();
}

float Window::getMainWindowWidth()
{
    OMNIUI_LOG_ERROR(
        "[DEPRECATED] Window::getMainWindowWidth is deprecated. Consider using Workspace::getMainWindowWidth");

    return 1.0f;
}

float Window::getMainWindowHeight()
{
    OMNIUI_LOG_ERROR(
        "[DEPRECATED] Window::getMainWindowHeight is deprecated. Consider using Workspace::getMainWindowHeight");

    return 1.0f;
}

void Window::deferredDockIn(const std::string& targetWindowTitle, Window::DockPolicy activeWindow)
{
    m_data->m_deferredDocking = targetWindowTitle;
    m_data->m_deferredDockingMakeTargetActive = activeWindow;
}

bool Window::isValid() const
{
    return !m_data->m_destroyed;
}

RasterPolicy Window::getRasterPolicy() const
{
    return this->getFrame()->getRasterPolicy();
}

void Window::setRasterPolicy(RasterPolicy policy)
{
    this->getFrame()->setRasterPolicy(policy);
}

bool Window::dockInWindow(const std::string& windowName, const Window::DockPosition& dockPosition, const float& ratio)
{
    OMNIUI_LOG_ERROR_ONCE("[DEPRECATED] Window::dockInWindow is deprecated. Consider using Window::dockIn");

    // first we find the window and its DockId
    ImGuiWindow* targetWindow = ImGui::FindWindowByName(windowName.c_str());
    if (!targetWindow)
    {
        return false;
    }
    ImGuiID targetNodeId = targetWindow->DockId;

    if (dockPosition == Window::DockPosition::eSame)
    {
        ImGui::DockBuilderDockWindow(this->getTitle().c_str(), targetNodeId);
    }
    else
    {
        // then we split using the Ratio
        ImGuiID out_id_at_dir, out_id_at_opposite_dir;
        ImGuiID node_id = ImGui::DockBuilderSplitNode(
            targetNodeId, (ImGuiDir)(dockPosition), ratio, &out_id_at_dir, &out_id_at_opposite_dir);

        // we insert the window into the new Dock Nodes
        ImGui::DockBuilderDockWindow(this->getTitle().c_str(), out_id_at_dir);
        ImGui::DockBuilderDockWindow(windowName.c_str(), out_id_at_opposite_dir);

        // when its done you have to finalize the building for the parent node
        ImGui::DockBuilderFinish(node_id);
    }
    return true;
}

bool Window::dockWindowInWindow(const std::string& windowName,
                                const std::string& targetWindowName,
                                const WindowHandle::DockPosition& dockPosition,
                                const float& ratio)
{
    OMNIUI_LOG_ERROR_ONCE("[DEPRECATED] Window::dockWindowInWindow is deprecated. Consider using Window::dockIn");

    // second we find the target window and its DockId
    ImGuiWindow* targetWindow = ImGui::FindWindowByName(targetWindowName.c_str());
    if (!targetWindow)
    {
        return false;
    }
    ImGuiID targetNodeId = targetWindow->DockId;

    if (dockPosition == WindowHandle::DockPosition::eSame)
    {
        ImGui::DockBuilderDockWindow(windowName.c_str(), targetNodeId);
    }
    else
    {
        // then we split using the Ratio
        ImGuiID out_id_at_dir, out_id_at_opposite_dir;
        ImGuiID node_id = ImGui::DockBuilderSplitNode(
            targetNodeId, (ImGuiDir)(dockPosition), ratio, &out_id_at_dir, &out_id_at_opposite_dir);

        // we insert the window into the new Dock Nodes
        ImGui::DockBuilderDockWindow(windowName.c_str(), out_id_at_dir);
        ImGui::DockBuilderDockWindow(targetWindowName.c_str(), out_id_at_opposite_dir);

        // when its done you have to finalize the building for the parent node
        ImGui::DockBuilderFinish(node_id);
    }
    return true;
}

void Window::setPosition(float x, float y)
{
    this->setPositionX(x);
    this->setPositionY(y);
}

void Window::_positionExplicitlyChanged()
{
    m_data->m_positionExplicitlyChanged = true;
}

void Window::_sizeExplicitlyChanged()
{
    m_data->m_sizeExplicitlyChanged = true;
}

void Window::_pushWindowStyle()
{
    OMNIUI_PROFILE_VERBOSE_ZONE("Window::_pushWindowStyle '%s'", getTitle().c_str());
    float uiScale = ImGui::GetWindowDpiScale();
    auto flags = this->getFlags();
    bool isModal = flags & kWindowFlagModal;
    bool isPopup = !isModal && flags & kWindowFlagPopup;

    m_data->m_pushedColorCount = m_data->m_pushedFloatCount = 0;

    float paddingX = this->getPaddingX() * uiScale;
    float paddingY = this->getPaddingY() * uiScale;
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(paddingX, paddingY));
    m_data->m_pushedFloatCount++;

    uint32_t backgroundColor;
    bool backgroundColorResolved = m_frame->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &backgroundColor);
    if (backgroundColorResolved)
    {
        if (!isPopup)
        {
            ImGui::PushStyleColor(ImGuiCol_WindowBg, backgroundColor);
            // we also need to ajust the color when we are docked
            ImGui::PushStyleColor(ImGuiCol_ChildBg, backgroundColor);
            m_data->m_pushedColorCount++;
            m_data->m_pushedColorCount++;
        }
        else
        {
            ImGui::PushStyleColor(ImGuiCol_PopupBg, backgroundColor);
            m_data->m_pushedColorCount++;
        }
    }

    uint32_t color;
    if (m_frame->_resolveStyleProperty(StyleColorProperty::eBorderColor, &color))
    {
        ImGui::PushStyleColor(ImGuiCol_Border, color);
        m_data->m_pushedColorCount++;
    }

    float boderWidth = 0.0f;
    m_frame->_resolveStyleProperty(StyleFloatProperty::eBorderWidth, &boderWidth);
    if (!isPopup)
    {
        ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, boderWidth);
    }
    else
    {
        ImGui::PushStyleVar(ImGuiStyleVar_PopupBorderSize, boderWidth);
    }
    m_data->m_pushedFloatCount++;

    float cornerRadius;
    if (m_frame->_resolveStyleProperty(StyleFloatProperty::eBorderRadius, &cornerRadius))
    {
        if (!isPopup)
        {
            ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, cornerRadius);
        }
        else
        {
            ImGui::PushStyleVar(ImGuiStyleVar_PopupRounding, cornerRadius);
        }
        m_data->m_pushedFloatCount++;
    }

    // If MenuBar doesn't have a background color, we need to use the window background color because the menu is a part
    // of the window.
    if (this->getMenuBar() && this->getMenuBar()->_resolveStyleProperty(StyleColorProperty::eBackgroundColor, &color))
    {
        ImGui::PushStyleColor(ImGuiCol_MenuBarBg, color);
        m_data->m_pushedColorCount++;
    }
    else if (backgroundColorResolved)
    {
        ImGui::PushStyleColor(ImGuiCol_MenuBarBg, backgroundColor);
        m_data->m_pushedColorCount++;
    }

    if (isModal)
    {
        uint32_t modalBackgroundColor;
        bool modalBackgroundColorResolved =
            m_frame->_resolveStyleProperty(StyleColorProperty::eSecondaryBackgroundColor, &modalBackgroundColor);
        if (modalBackgroundColorResolved)
        {
            ImGui::PushStyleColor(ImGuiCol_ModalWindowDimBg, modalBackgroundColor);
            m_data->m_pushedColorCount++;
        }
    }

    if (isPopup)
    {
        uint32_t shadowColor;
        if (m_frame->_resolveStyleProperty(StyleColorProperty::eShadowColor, &shadowColor))
        {
            ImGui::PushStyleColor(ImGuiCol_WindowShadow, shadowColor);
            m_data->m_pushedColorCount++;
        }
    }
}

void Window::_popWindowStyle()
{
    ImGui::PopStyleVar(m_data->m_pushedFloatCount);
    ImGui::PopStyleColor(m_data->m_pushedColorCount);
}

void Window::_drawTooltip(std::string& tooltip)
{
    // This is a hackery way to override unnecessary ImGui tooltip which is out of our control.
    if (tooltip.empty())
    {
        ImGui::PushStyleColor(ImGuiCol_Border, 0x0);
        ImGui::PushStyleColor(ImGuiCol_PopupBg, 0x0);
        ImGui::PushStyleColor(ImGuiCol_WindowShadow, 0x0);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2{ 0.0f, 0.0f });
        ImGui::SetTooltip(" "); // some compiler doesn't like 0 length string for SetTooltip
        ImGui::PopStyleVar(1);
        ImGui::PopStyleColor(3);
    }
    else
    {
        ImGui::PushStyleColor(ImGuiCol_PopupBg, 0xFFD8D8D8);
        ImGui::PushStyleColor(ImGuiCol_Text, 0xFF202020);
        ImGui::PushStyleColor(ImGuiCol_WindowShadow, 0x0);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 3.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_PopupBorderSize, 1.0f);
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2{ 6.0f, 2.0f });
        ImGui::SetTooltip("%s", tooltip.c_str());
        ImGui::PopStyleVar(3);
        ImGui::PopStyleColor(3);
    }
}

bool Window::moveToNewOSWindow()
{
    auto* platform = PlatformRegistry::instance().platform();
    if (!platform)
    {
        OMNIUI_LOG_WARN("Could not create new OS window - no platform");
        return false;
    }

    float dpiScale = Workspace::getDpiScale();
    Int2 position = {};
    if (m_data->m_appWindow)
    {
        position = platform->getAppWindowOsPosition(m_data->m_appWindow);
    }

    uint64_t minSize = 64;
    uint64_t width = static_cast<uint64_t>(this->getWidth());
    uint64_t height = static_cast<uint64_t>(this->getHeight());

    // Unconditional: _draw() clears kWindowFlagNoTitleBar for a detached window, so the window we
    // are about to create always has a title bar even when the docked one being measured here does
    // not. Asking for the height as currently drawn would return 0 for exactly those windows and
    // make both the size below and titleBarOffsetY one title bar short.
    float tbHeight = 0.0f;
    ImGuiContext* ctx = ImGui::GetCurrentContext();
    if (ctx)
    {
        ImGuiWindow* imGuiWindow = ctx->CurrentWindow;
        if (imGuiWindow)
            tbHeight = WindowTitleBarHeightUnconditional(imGuiWindow);
    }

    if (m_frame && m_frame->getComputedWidth() > 0.0f)
        width = static_cast<uint64_t>(m_frame->getComputedWidth());

    const bool decorated = _useDetachedDecorations();

    // The requested position is the client area origin, and a decorated window's WM title bar is
    // drawn above it. Start one title bar lower so that bar lands inside the old window rather than
    // over whatever was above it, or off the top of the display.
    const float titleBarOffsetY = decorated ? tbHeight : 0.0f;

    if (m_frame && m_frame->getComputedHeight() > 0.0f)
        height = static_cast<uint64_t>(m_frame->getComputedHeight() + tbHeight);

    AppWindowHandle newOsWindow =
        _newOsWindow(this->getTitle().c_str(), static_cast<uint64_t>(position.x + m_positionX * dpiScale),
                     static_cast<uint64_t>(position.y + m_positionY * dpiScale + titleBarOffsetY),
                     std::max(width, minSize), std::max(height, minSize));

    if (!newOsWindow)
    {
        // WARN, not ERROR for headless mode where this call will fail.
        //
        OMNIUI_LOG_WARN("Could not create new OS window");
        return false;
    }

    this->moveToAppWindow(newOsWindow);

    // After moveToAppWindow(), which goes through notifyAppWindowChange() and clears this.
    m_data->m_osWindowDecorated = decorated;
    return true;
}

void Window::moveToMainOSWindow()
{
    OMNIUI_PROFILE_VERBOSE_ZONE("Window::moveToMainOSWindow '%s'", getTitle().c_str());
    ui::windowmanager::IWindowCallbackManager* uiWindowManager =
        PlatformRegistry::instance().windowCallbackManager();

    auto* platform = PlatformRegistry::instance().platform();
    AppWindowHandle mainAppWindow = platform ? platform->getDefaultAppWindowHandle() : nullptr;

    uiWindowManager->moveCallbackToAppWindow(m_data->m_uiWindow.get(), mainAppWindow);

    if (!m_data->m_uiWindow || !m_data->m_uiWindow->getWindowSet() ||
        m_data->m_uiWindow->getWindowSet() != uiWindowManager->getWindowSetByAppWindow(mainAppWindow))
        return;

    AppWindowHandle currentAppWindow = m_data->m_appWindow;

    // We cannot destroy window and its resources immediately, as we're right in the middle of
    // rendering loop here in ImGUI draw/callback. Thus, we schedule a one-time deferred callback
    // which will destroy window, cleanup resoures and unsubscribe itself.
    // If we're shutting down, the app may be destroyed already.
    if (platform && platform->isAppRunning())
    {
        // Cancel any previous close observer
        m_data->m_windowCloseObserverHandle.reset();

        // Schedule deferred destruction of the current app window
        m_data->m_deferredDestroyHandle = platform->deferDestroyAppWindow(currentAppWindow);
    }

    this->notifyAppWindowChange(mainAppWindow);
}

void Window::_updateOSWindowDrag(bool canStartDrag)
{
    if (!ImGui::IsMouseDown(ImGuiMouseButton_Left))
    {
        m_data->m_osWindowMoving = false;
        return;
    }

    const bool startDrag = canStartDrag && ImGui::IsMouseClicked(ImGuiMouseButton_Left);
    if (!startDrag && !m_data->m_osWindowMoving)
    {
        return;
    }

    auto* platform = PlatformRegistry::instance().platform();
    if (!platform || !m_data->m_appWindow || platform->isAppWindowVirtual(m_data->m_appWindow))
        return;

    // getCursorPosition() is window-relative, so a frame-to-frame delta taken from it cancels out
    // as the window follows the cursor. Anchor on the grab offset and re-derive an absolute target
    // instead. That is idempotent -- once the window has caught up the target equals its current
    // position -- so a stale getWindowPosition(), routine on X11 where the window manager applies
    // moves asynchronously, recomputes the same target and self-corrects instead of compounding.
    const Int2 cursorInWindow = platform->getAppWindowCursorPosition(m_data->m_appWindow);

    if (!m_data->m_osWindowMoving)
    {
        m_data->m_osWindowGrabOffset = cursorInWindow;
        m_data->m_osWindowMoving = true;
        return;
    }

    const Int2 windowPosition = platform->getAppWindowOsPosition(m_data->m_appWindow);
    const Int2 target = { windowPosition.x + cursorInWindow.x - m_data->m_osWindowGrabOffset.x,
                                windowPosition.y + cursorInWindow.y - m_data->m_osWindowGrabOffset.y };

    if (target.x != windowPosition.x || target.y != windowPosition.y)
    {
        platform->setAppWindowOsPosition(m_data->m_appWindow, target.x, target.y);
    }
}

bool Window::_updateFocusState()
{
    // ImGui handles focus on left click by default.
    if (m_focusPolicy == FocusPolicy::eFocusOnLeftMouseDown)
    {
        return false;
    }

    // If Window is already focused, then do nothing (moving focus to new Window will disable previously focused Window)
    if (ImGui::IsWindowFocused(ImGuiFocusedFlags_ChildWindows))
    {
        return false;
    }

    // eFocusOnHover and eFocusOnAnyMouseDown should only focus when mouse over Window.
    if (!ImGui::IsWindowHovered(ImGuiFocusedFlags_ChildWindows))
    {
        return false;
    }

    // If the focus policy is to focus on hover, then Window should be focused now.
    if (m_focusPolicy == FocusPolicy::eFocusOnHover)
    {
        return true;
    }

    // If the focus policy is to focus on mouse down, then check for any button down.
    if (m_focusPolicy == FocusPolicy::eFocusOnAnyMouseDown)
    {
        return ImGui::IsMouseDown(0) || ImGui::IsMouseDown(1) || ImGui::IsMouseDown(2);
    }

    OMNIUI_ASSERT(0, "Unknown focus policy");
    return false;
}

void Window::_draw(const char* windowName, float elapsedTime)
{
    // A common use pattern is to destroy the window in its visibility_changed_fn callback function.
    // However, the callback is invoked during `_draw` call, and the destruction of window within will result in
    // heap-use-after-free error for the rest of function. Here we increase the ref count to this Window to prevent
    // itself being released, and delay it until selfRef goes out of scope at the end of `_draw`.
    const auto selfRef = shared_from_this();

    // Imgui asserts when windowName is nullptr or string of zero length
    if (windowName == nullptr)
    {
        windowName = "omni::ui::Window::__NO_NULL_WINDOW_NAME_TO_IMGUI__";
    }
    else if (windowName[0] == 0)
    {
        windowName = "omni::ui::Window::__NO_EMPTY_WINDOW_NAME_TO_IMGUI__";
    }

    if (!this->isValid())
    {
        return;
    }

    if (!this->isVisible())
    {
        if (m_data->m_wasVisiblePreviousFrame)
        {
            m_data->m_wasVisiblePreviousFrame = false;
        }

        return;
    }

    OMNIUI_PROFILE_VERBOSE_ZONE("Window::_draw '%s'", windowName);

    auto* platform = PlatformRegistry::instance().platform();
    AppWindowHandle defaultWindow = platform ? platform->getDefaultAppWindowHandle() : nullptr;

    bool appWindowIsMainWindow = m_data->m_appWindow == defaultWindow;
    bool windowDrivesAppWindow = !appWindowIsMainWindow && !(this->getFlags() & (kWindowFlagModal | kWindowFlagPopup));

    // Whether that app window is a real OS window, i.e. this Window was detached with
    // moveToNewOSWindow() -- _newOsWindow() gives up unless it gets a window with a
    // carb::windowing::Window behind it, so a detached window is always this.
    //
    // Not every app window that is not the main one is an OS window: omni.ui.scene hosts each
    // ui.scene.Widget in a ui::Window moved onto a *virtual* app window that renders to an
    // offscreen texture. Such a window has no window manager, no title bar to drag and nowhere to
    // move back to, and its pixels are the widget the user sees, so none of the detached-window
    // handling below applies to it.
    bool windowDrivesOsWindow = windowDrivesAppWindow && !this->isVirtual();

    if (windowDrivesAppWindow)
    {
        // Check if this is an ImGui window in the detached application window.
        // We can only have one window per detached application window. If it's
        // the second one, we need to detach it.
        ui::windowmanager::IWindowCallbackManager* uiWindowManager =
            PlatformRegistry::instance().windowCallbackManager();
        omni::ui::windowmanager::WindowSet* currentWindowSet = uiWindowManager->getWindowSetByAppWindow(m_data->m_appWindow);
        if (!currentWindowSet)
        {
            OMNIUI_LOG_WARN("Window '%s' lost its app-window association; restoring its callback owner's destination",
                            getTitle().c_str());
            this->notifyAppWindowChange(m_data->m_uiWindow->getAppWindow());
            return;
        }

        // Get the first callback in current application window.
        omni::ui::windowmanager::IWindowCallback* callback = uiWindowManager->getWindowSetCallbackAt(currentWindowSet, 0);
        if (callback != m_data->m_uiWindow.get())
        {
            // We are here because it's not the first window in the detached application window.
            this->moveToNewOSWindow();
            return;
        }
    }

    // Save the current application window, so the window created in the draw loop will know which one it belongs to.
    Workspace::AppWindowGuard appWindowGuard{ m_data->m_appWindow };

    if (this->getWidth() == 0 && this->getHeight() == 0)
    {
        this->setAutoResize(true);
    }

    // we push the various window styling into the stack
    this->_pushWindowStyle();

    // Check if the window has been ever shown.
    bool windowExists = m_windowId != 0;

    // ImGui doesn't support multiple modal windows. It displays the first defined modal window only. To work around it,
    // we make only the top-level window modal. The other windows are regular, even if they flagged as modal. The
    // problem of this approach is ImGui tracks regular windows and modal windows at different structures, and the
    // properties such as position, size, etc. are not transfered when the regular window becomes modal. So we keep the
    // position and pass it at a specific time when the window becomes modal.
    bool isModal = ((this->getFlags() & kWindowFlagModal) == kWindowFlagModal) && this->_isTopModal();
    bool isPopup = !isModal && this->getFlags() & kWindowFlagPopup;

    if (isModal)
    {
        // Check if ImGui already have a modal window. ImGui doesn't support two modal windows at the same time. Kit may
        // create a modal window with ImGui directly. For example, it's the save as window. If it happened, we don't
        // want to create a modal window here because it will freeze whole Kit.
        // TODO: It's actually not a good idea and we need either to create all the windows with ovui or fix it in
        // ImGui. But for now, it's not that bad. It's executed only once a frame and it's doing a search through about
        // 60 windows, also we don't compare strings during the search.
        auto* ctx = ImGui::GetCurrentContext();
        const auto& windows = ctx->Windows;

        auto id = m_windowId;
        // Find modal window in window list.
        auto found =
            std::find_if(windows.begin(), windows.end(),
                         [id](const ImGuiWindow* it)
                         { return it && it->WasActive && (it->ID != id) && (it->Flags & ImGuiWindowFlags_Modal); });
        if (found != windows.end())
        {
            // Kit already has a modal window. If this window is modal, Kit will be frozen.
            isModal = false;
        }
    }

    bool justBecameModal = !m_data->m_wasModalPreviousFrame && isModal;

    float uiScale = ImGui::GetWindowDpiScale();
    if (m_data->m_positionExplicitlyChanged)
    {
        float posX = this->getPositionX() * uiScale;
        float posY = this->getPositionY() * uiScale;

        ::ImGui::SetNextWindowPos(ImFloor(ImVec2(posX, posY)), ImGuiCond_Always);
        m_data->m_positionExplicitlyChanged = false;
    }
    else if (isModal)
    {
        // We need to set the position of the modal window for the case it's converted from the regular one to modal. In
        // this case, ImGui doesn't know that it's the same window and puts it to the center of the screen. Also, we
        // don't need to set the position of the very new modal window because ImGui puts it to the center of the
        // screen, and we would like to keep it in the center. Once the user moves it, we save the position and
        // explicitly set it.

        float posX = this->getPositionX();
        float posY = this->getPositionY();

        if (posX != kWindowFloatInvalid && posY != kWindowFloatInvalid)
        {
            ::ImGui::SetNextWindowPos(ImFloor(ImVec2(posX * uiScale, posY * uiScale)), ImGuiCond_Appearing);
        }
    }
    else if (m_data->m_dockingPreference == DockPreference::eDisabled)
    {
        ImVec2 viewportSize = ImGui::GetMainViewport()->Size;
        viewportSize.x *= 0.5f;
        viewportSize.y *= 0.5f;

        ::ImGui::SetNextWindowPos(viewportSize, ImGuiCond_Once, ImVec2(0.5f, 0.5f));
    }

    if (windowDrivesAppWindow)
    {
        ::ImGui::SetNextWindowPos(ImVec2(0, 0), ImGuiCond_Once);
        // The window moves when resizing from the left side, which causes
        // problems with ImGui. Disable it.
        ImGuiContext* ctx = ImGui::GetCurrentContext();
        ctx->IO.ConfigWindowsResizeFromEdges = false;
    }
    else
    {
        // Allow all edges resize.
        ImGuiContext* ctx = ImGui::GetCurrentContext();
        ctx->IO.ConfigWindowsResizeFromEdges = true;
    }

    const auto windowFlags = this->getFlags();
    ImGuiWindowFlags flags = static_cast<ImGuiWindowFlags>(windowFlags & ~kWindowFlagNoDocking);
    if (windowFlags & kWindowFlagNoDocking)
        flags |= ImGuiWindowFlags_NoDocking;
    flags &= ~(kWindowFlagModal | kWindowFlagPopup);

    if (this->getRasterPolicy() != RasterPolicy::eNever)
    {
        // Scroll bar aalways appear when drawing rasterized window and it looks
        // like a double scrollbar.
        flags |= kWindowFlagNoScrollbar | kWindowFlagNoScrollWithMouse;
    }

    // Captured before the branch below clears it: the OS window sync further down needs to know
    // whether an explicit width/height assignment landed this frame.
    const bool sizeExplicitlyChanged = m_data->m_sizeExplicitlyChanged;

    if (!this->getAutoResize())
    {
        if (m_data->m_sizeExplicitlyChanged)
        {
            float width = this->getWidth();
            float height = this->getHeight();

            // On the case it's docked.
            WindowHandle::setWidth(width);
            WindowHandle::setHeight(height);

            ImGui::SetNextWindowSize(ImFloor(ImVec2{ width * uiScale, height * uiScale }), ImGuiCond_Always);

            m_data->m_sizeExplicitlyChanged = false;
        }

    }
    else
    {
        flags |= ImGuiWindowFlags_AlwaysAutoResize;
    }

    if (windowDrivesAppWindow && platform)
    {
        // A decorated OS window is resized by the window manager, so it is the authoritative size
        // and the ui.Window has to follow it. An auto-resize window is still driven by its content,
        // and an explicit width/height assignment is still a request to resize the OS window, so
        // both of those keep pushing even when decorated.
        const bool pullFromOSWindow =
            m_data->m_osWindowDecorated && !this->getAutoResize() && !sizeExplicitlyChanged;

        // Pushing the size of an auto-resize window is part of the detached-window fix and is
        // deliberately limited to OS windows. A virtual app window is sized by whoever created it
        // -- omni.ui.scene drives its own from the widget resolution -- and an auto-resize window
        // on one was never pushed to from here, so leave that path exactly as it was.
        const bool pushToOSWindow = windowDrivesOsWindow || !this->getAutoResize();

        if (pullFromOSWindow)
        {
            // The window manager sizes this window, so take the ImGui resize grip out of play.
            // ConfigWindowsResizeFromEdges above only covers the edges, and a grip drag would be
            // overridden by the SetNextWindowSize below on the very next frame anyway.
            flags |= ImGuiWindowFlags_NoResize;

            int width = 0;
            int height = 0;
            platform->getAppWindowSize(m_data->m_appWindow, &width, &height);
            const float appWidth = float(width);
            const float appHeight = float(height);

            if (appWidth > 0.0f && appHeight > 0.0f)
            {
                // Fill the app window. Overrides the ImGuiCond_Once position set further up, which
                // only covers the first frame.
                ImGui::SetNextWindowPos(ImVec2(0.0f, 0.0f), ImGuiCond_Always);
                ImGui::SetNextWindowSize(ImVec2(appWidth, appHeight), ImGuiCond_Always);
            }
        }
        else if (pushToOSWindow)
        {
            // Keep the OS window in sync with the ImGui window. _updateWindow() writes the real
            // ImGui::GetWindowSize() back into getWidth()/getHeight() every frame, so this is the
            // authoritative size for auto-resize windows too. This used to sit inside the
            // !getAutoResize() branch above, which meant a detached auto-resize window never
            // resized its borderless OS window and so could not be resized at all.
            const uint32_t osWidth = uint32_t(this->getWidth() * uiScale);
            const uint32_t osHeight = uint32_t(this->getHeight() * uiScale);

            // Guard the first frames, where the size has not been computed yet: resizing the OS
            // window to zero leaves it unrecoverable.
            if (osWidth > 0 && osHeight > 0)
            {
                platform->resizeAppWindow(m_data->m_appWindow, static_cast<int>(osWidth), static_cast<int>(osHeight));
            }
        }
    }

    bool useClose = ((this->getFlags() & kWindowFlagNoClose) == kWindowFlagNoClose);
    bool visible = true;

    if (windowDrivesAppWindow)
    {
        flags |= ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoCollapse;
    }

    if (windowDrivesOsWindow)
    {
        // The ImGui title bar carries the "Move to Main Window" context menu, which is the only
        // route back to the docked state that every detached window has -- an app window menu only
        // covers windows the application registered there. So it is forced on, even for a window
        // that asked for kWindowFlagNoTitleBar while docked, which would otherwise detach into
        // something that cannot be recovered.
        //
        // Borderless, it is also the only chrome the OS window has and carries the drag region
        // that moves it. Under /exts/omni.ui/Window/detachedDecorations it sits below the window
        // manager's own title bar, so such a window shows two; that is the price of the setting,
        // and why it is off by default.
        //
        // Only for a real OS window: forcing a title bar onto a virtual app window would draw one
        // into the offscreen texture an omni.ui.scene widget is made of.
        flags &= ~ImGuiWindowFlags_NoTitleBar;
    }

    // if the menuBar is not visible turn off the MenuBar Flag
    if (!this->getMenuBar()->isVisible())
    {
        flags &= ~kWindowFlagMenuBar;
    }

    if (platform && m_data->m_appWindow && platform->isMouseInputBlocked(m_data->m_appWindow))
    {
        flags |= ImGuiWindowFlags_NoMouseInputs;
    }

    if (isModal || isPopup)
    {
        flags |= ImGuiWindowFlags_NoSavedSettings;

        // open popup. the popup can also be closed by app
        if (!ImGui::IsPopupOpen(windowName))
        {
            if (isModal || !m_data->m_wasVisiblePreviousFrame)
                ImGui::OpenPopup(windowName);
        }

        bool windowOpen;
        if (isModal)
        {
            windowOpen = ImGui::BeginPopupModal(windowName, useClose ? nullptr : &visible, flags);
        }
        else // isPopup
        {
            // From ImGui::BeginPopup.
            ImGuiContext* ctx = ImGui::GetCurrentContext();
            OMNIUI_ASSERT(ctx);
            ImGuiWindow* window = ctx->CurrentWindow;
            OMNIUI_ASSERT(window);

            // We don't use BeginPopup because it sets a lot of windows flags.
            windowOpen = ImGui::BeginPopupEx(window->GetID(windowName), flags);
        }

        if (windowOpen)
        {
            if (isPopup)
            {
                // Close popup window when the user scrolled outside of it.
                // ImGui::IsWindowHovered doesn't work for pupups
                if (ImGui::IsWindowFocused())
                {
                    ImVec2 min = ImGui::GetWindowPos();
                    ImVec2 max{ min.x + ImGui::GetWindowWidth(), min.y + ImGui::GetWindowHeight() };

                    const ImGuiIO& io = ImGui::GetIO();
                    if (!ImGui::IsMouseHoveringRect(min, max) && io.MouseWheel != 0.0f)
                    {
                        ImGui::CloseCurrentPopup();
                    }
                }
            }

            // Don't save the window position if it's the first frame from the window became modal because ImGui puts it
            // to the position (60, 60) and st the scecond frame the position is correct.
            this->_updateWindow(windowName, elapsedTime, !justBecameModal);
            ImGui::EndPopup();
        }

        if (isPopup)
        {
            // Popup window doesn't support flag is_open, and it's only possible to know if it was closed is get this
            // information the next frame it's closed.
            visible = windowOpen;
        }

        if (m_focusPolicy != FocusPolicy::eDefault)
        {
            OMNIUI_LOG_WARN("Ignoring FocusPolicy (%d) for Window '%s'", int(m_focusPolicy), getTitle().c_str());
        }
    }
    else
    {
        // If fill_app_window is enabled, override position and size to fill the
        // main viewport every frame (same pattern as MainWindow::_draw).
        if (m_fillAppWindow)
        {
            ImGuiViewport* viewport = ImGui::GetMainViewport();
            ImGui::SetNextWindowPos(viewport->Pos, ImGuiCond_Always);
            ImGui::SetNextWindowSize(viewport->Size, ImGuiCond_Always);
        }

        ImGuiContext* ctx = ImGui::GetCurrentContext();
        OMNIUI_ASSERT(ctx);

        bool showItems = ImGui::Begin(windowName, useClose ? nullptr : &visible, flags);

        // We only can get it between ImGui::Begin and ImGui::End
        ImGuiWindow* imGuiWindow = ctx->CurrentWindow;

        // hide unnecessary default ImGui TabBar tooltip. This tooltip is hardcoded in ImGui and the only way to disable
        // it is to override with something else. And since only one tooltip is allowed, it works.
        ImGuiDockNode* node = ImGui::DockBuilderGetNode(imGuiWindow->DockId);
        if (node && node->TabBar && ImGui::IsItemHovered())
        {
            std::string tooltip = this->getTabBarTooltip();
            _drawTooltip(tooltip);
        }

        if (showItems)
        {
            if (_updateFocusState())
            {
                ImGui::SetFocusID(ctx->CurrentWindow->ID, ctx->CurrentWindow);
            }

            _detectFirstInteraction();

            if (m_data->m_multiOSWindowSupport)
            {
                // we need to move that to a Settings so we can hide it while it dev
                // Also this being here mean we need to do the same for the kit.ui,window and cpp Window
                // might be better to move that Logic into some utility in window_manager ?
                // TitleBarHeight to be sure the mouse is ot top of the title. Purely geometric --
                // whether the title bar is allowed to *act* is the separate test below.
                const bool overTitleBar =
                    ImGui::GetMousePos().y < ImGui::GetWindowPos().y + WindowTitleBarHeight(imGuiWindow);

                // Detaching needs permission; docking back never does. moveToNewOSWindow() is
                // callable from Python without consulting isDetachable() -- omni.kit.window.file_*
                // and omni.kit.capture.viewport all do exactly that -- and a window detached that
                // way must still be able to get home.
                const bool canUseTitleMenu =
                    windowDrivesOsWindow || (m_data->m_enableWindowDetach && this->isDetachable());

                if ((overTitleBar && canUseTitleMenu) || m_data->m_titleMenuOpened)
                {
                    m_data->m_titleMenuOpened = ImGui::BeginPopupContextItem("OS Window");
                    if (m_data->m_titleMenuOpened)
                    {
                        if (windowDrivesAppWindow)
                        {
                            if (ImGui::MenuItem("Move to Main Window"))
                            {
                                this->moveToMainOSWindow();
                            }
                        }
                        else
                        {
                            if (ImGui::MenuItem("Move to External Window"))
                            {
                                this->moveToNewOSWindow();
                            }

                            if (Workspace::getDockedNeighbours(this->shared_from_this()).size() == 1)
                            {
                                ImGui::Separator();

                                if (ImGui::MenuItem("Hide Tab"))
                                {
                                    this->setDockTabBarVisible(false);
                                }
                            }
                        }
                        ImGui::EndPopup();
                    }
                }

                // Deliberately outside the title bar test above: only *starting* a drag needs the
                // cursor over the title bar, an in-flight one has to keep running wherever the
                // cursor goes. Nesting it meant dragging downwards left the band on the first
                // frame, which stopped the move and skipped the release handling, latching the
                // drag state on. Skipped when decorated: the window manager moves the window and
                // setWindowPosition() from here would fight it.
                if (windowDrivesOsWindow && !m_data->m_osWindowDecorated)
                {
                    _updateOSWindowDrag(overTitleBar && !m_data->m_titleMenuOpened);
                }
            }
            this->_updateWindow(windowName, elapsedTime, true);
            m_data->m_wasPreviousShowItems = true;
        }
        else if (m_data->m_firstAppearance)
        {
            ImGuiContext* ctx = ImGui::GetCurrentContext();
            OMNIUI_ASSERT(ctx);
            ImGuiWindow* window = ctx->CurrentWindow;
            OMNIUI_ASSERT(window);

            if (window->Hidden)
            {
                // It's possible that the window was closed by ImGui and the
                // user deleted ui.Window and created it again. This way ImGui
                // remembers this flag and when we recreate the window we need
                // to make sure it's not hidden.
                window->Hidden = false;
                window->HiddenFramesCanSkipItems = 0;
            }
        }
        // update the docked status. When a window is created and docked in, it could become invisible, so we need to
        // also check the status if previous frame was shown
        if (showItems|| m_data->m_wasPreviousShowItems)
        {
            bool docked = ImGui::IsWindowDocked();
            if (this->isDocked() != docked)
            {
                this->setDocked(docked);
            }
            if (!showItems)
                m_data->m_wasPreviousShowItems = false;
        }

        ImGui::End();

        // Deferred docking
        if (!m_data->m_deferredDocking.empty())
        {
            // Getting the tagret window
            auto targetWindow = Workspace::getWindow(m_data->m_deferredDocking);
            if (targetWindow)
            {
                this->dockIn(targetWindow, DockPosition::eSame);
                if (WindowHandle::isDocked())
                {
                    // Make the current tab or target tab as active depending on the state.
                    if (m_data->m_deferredDockingMakeTargetActive == DockPolicy::eTargetWindowIsActive)
                    {
                        targetWindow->focus();
                    }
                    else if (m_data->m_deferredDockingMakeTargetActive == DockPolicy::eCurrentWindowIsActive)
                    {
                        this->focus();
                    }

                    m_data->m_deferredDocking.clear();
                }
            }
        }
        // Check if the window is the current window in the dock. If there is no
        // imGuiWindow, it means the window is hidden and thus it can't be in the
        // dock. We don't check modals and popup because they cannot be docked.
        // We set the selection here instead of _updateWindow which is only called
        // if the window is visible on the screen, so it won't be called if the window
        // is unselected in that case.
        this->setSelectedInDock(imGuiWindow && WindowHandle::_isWindowSelectedInDock(imGuiWindow));
    }

    this->_popWindowStyle();

    // Check isVisible() again because it's possible that some widget changed it during draw.
    this->setVisible(visible && this->isVisible());

    // Skip the modal logic for the first frame to let ImGui center the modal window. ImGui centers the new window when
    // it's fully created, so we don't need to save window position and explicitly set it when the window is not created
    // and on the first frame after.
    m_data->m_wasModalPreviousFrame = windowExists && isModal;

    // We need it for popups
    m_data->m_wasVisiblePreviousFrame = true;

    // We need it to detect the first frame of this window
    m_data->m_firstAppearance = false;

}

void Window::_updateWindow(const char* windowName, float elapsedTime, bool cachePosition)
{
    OMNIUI_PROFILE_VERBOSE_ZONE("Window::_updateWindow '%s'", windowName);
    // GetCurrentWindowRead() doesn't work here because we use ImGui DLL and GImGui is not exported.
    ImGuiContext* ctx = ImGui::GetCurrentContext();
    OMNIUI_ASSERT(ctx);
    ImGuiWindow* window = ctx->CurrentWindow;
    OMNIUI_ASSERT(window);

    OMNIUI_ASSERT(m_data->m_appWindow);

    auto* platform = PlatformRegistry::instance().platform();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigInputTextCursorBlink = platform ? platform->getAppWindowCursorBlink(m_data->m_appWindow) : true;

    bool focused = ImGui::IsWindowFocused(ImGuiFocusedFlags_ChildWindows);
    this->_setFocused(focused);

    if (focused && this->hasKeyPressedFn())
    {
        // Callback on key pressed.
        // ImGui 1.87+ named keys live in [ImGuiKey_NamedKey_BEGIN, _END);
        // iterating 0..256 (the legacy native range) never fires because
        // IsKeyPressed((ImGuiKey)0..255) matches nothing with
        // IMGUI_DISABLE_OBSOLETE_FUNCTIONS. The platform bridge maps named keys to the
        // native code space expected by host callbacks.
        KeyboardModifierFlags modifiers =
            (io.KeyAlt ? kKeyModAlt : 0) |
            (io.KeyShift ? kKeyModShift : 0) |
            (io.KeyCtrl ? kKeyModCtrl : 0) |
            (io.KeySuper ? kKeyModSuper : 0) |
            (io.WantCaptureKeyboard ? Widget::kModifierFlagWantCaptureKeyboard : 0);

        for (int k = ImGuiKey_NamedKey_BEGIN; k < ImGuiKey_NamedKey_END; ++k)
        {
            ImGuiKey key = static_cast<ImGuiKey>(k);
            if (ImGui::IsKeyPressed(key, false))
            {
                auto* inputPlatform = PlatformRegistry::instance().platform();
                const int nativeKey = inputPlatform ? inputPlatform->nativeKeyCode(key) : 0;
                if (nativeKey != 0)
                    this->callKeyPressedFn(nativeKey, modifiers, true);
            }
        }
        for (int k = ImGuiKey_NamedKey_BEGIN; k < ImGuiKey_NamedKey_END; ++k)
        {
            ImGuiKey key = static_cast<ImGuiKey>(k);
            if (ImGui::IsKeyReleased(key))
            {
                auto* inputPlatform = PlatformRegistry::instance().platform();
                const int nativeKey = inputPlatform ? inputPlatform->nativeKeyCode(key) : 0;
                if (nativeKey != 0)
                    this->callKeyPressedFn(nativeKey, modifiers, false);
            }
        }
    }

    if (focused && this->isExclusiveKeyboard())
    {
        // Only the current window will receive keyboard events.
        ImGui::SetNextFrameWantCaptureKeyboard(true);
    }

    // Save ID for the base class.
    m_windowId = window->ID;

    float uiScale_inv = 1.f / ImGui::GetWindowDpiScale();

    if (cachePosition)
    {
        ImVec2 windowPos = ImGui::GetWindowPos();

        // We don't want to explicitly change window position. But we want to trigger notification in the case the user
        // is watching the position.
        bool positionExplicitlyChanged = m_data->m_positionExplicitlyChanged;

        this->setPositionX(windowPos.x * uiScale_inv);
        this->setPositionY(windowPos.y * uiScale_inv);

        m_data->m_positionExplicitlyChanged = positionExplicitlyChanged;
    }

    // Set the cursor position to the begin of the window. It gives the ability to do window overlay and for example
    // draw on top of the viewport.
    ImGui::SetCursorPos(ImGui::GetCursorStartPos());

    // Use GetContentRegionAvail() to get content region dimensions.
    const ImVec2 contentRegionAvail = window->ContentRegionRect.GetSize();

    float contentRegionWidth = contentRegionAvail.x;
    float contentRegionHeight = contentRegionAvail.y;

    {
        OMNIUI_PROFILE_ZONE("'%s' layout", windowName);
        if (contentRegionWidth != m_data->m_prevContentRegionWidth)
        {
            m_data->m_prevContentRegionWidth = contentRegionWidth;
            this->getMenuBar()->forceWidthDirty(Widget::SizeDirtyReason::eParentDirty);
            this->getFrame()->forceWidthDirty(Widget::SizeDirtyReason::eParentDirty);
            this->getFrame()->forceRasterDirty(Widget::BakeDirtyReason::eContentChanged);
        }
        if (contentRegionHeight != m_data->m_prevContentRegionHeight)
        {
            m_data->m_prevContentRegionHeight = contentRegionHeight;
            this->getFrame()->forceHeightDirty(Widget::SizeDirtyReason::eParentDirty);
            this->getFrame()->forceRasterDirty(Widget::BakeDirtyReason::eContentChanged);
        }

        this->getMenuBar()->setComputedWidth(contentRegionWidth);
        this->getMenuBar()->setComputedHeight(0.0f);

        this->getFrame()->setComputedWidth(contentRegionWidth);
        this->getFrame()->setComputedHeight(contentRegionHeight);
    }

    {
        OMNIUI_PROFILE_ZONE("'%s' draw", windowName);
        this->getMenuBar()->draw(elapsedTime);
        this->getFrame()->draw(elapsedTime);
    }

    if (!m_data->m_sizeExplicitlyChanged)
    {
        ImVec2 windowSize = ::ImGui::GetWindowSize();
        this->setWidth(windowSize.x * uiScale_inv);
        this->setHeight(windowSize.y * uiScale_inv);
        m_data->m_sizeExplicitlyChanged = false;
    }
}

void Window::_drawWindow(const char* windowName, float elapsedTime, void* window)
{
    reinterpret_cast<Window*>(window)->_draw(windowName, elapsedTime);
}

void Window::_addToModalStack() const
{
    if ((this->getFlags() & kWindowFlagModal) == 0)
    {
        return;
    }

    g_modals.push_back(this);
}

void Window::_removeFromModalStack() const
{
    auto found = std::find(g_modals.begin(), g_modals.end(), this);
    if (found != g_modals.end())
    {
        g_modals.erase(found);
    }
}

bool Window::_isTopModal() const
{
    return !g_modals.empty() && g_modals.back() == this;
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
