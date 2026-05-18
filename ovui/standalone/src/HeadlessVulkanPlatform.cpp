/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include "HeadlessVulkanPlatform.h"
#include "VulkanBackend.h"
#include "StandaloneGlyphManager.h"
#include "StandaloneInit.h"
#include "StandaloneWindowCallbackManager.h"
#include "ImGuiKeyTranslation.h"

#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/Font.h>

#include <imgui/imgui.h>
#include <imgui/backends/imgui_impl_vulkan.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#elif defined(__linux__) || defined(__APPLE__)
#include <dlfcn.h>
#endif

namespace omni {
namespace ui {
namespace standalone {

// ---------------------------------------------------------------------------
// Font loading helper (same strategy as GlfwPlatform)
// ---------------------------------------------------------------------------

static std::string findFontPath(const char* fontFile)
{
    namespace fs = std::filesystem;

#ifdef _WIN32
    {
        HMODULE hModule = nullptr;
        if (GetModuleHandleExW(
                GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                reinterpret_cast<LPCWSTR>(&findFontPath), &hModule))
        {
            wchar_t modulePath[MAX_PATH];
            if (GetModuleFileNameW(hModule, modulePath, MAX_PATH))
            {
                fs::path libDir = fs::path(modulePath).parent_path();
                fs::path candidate = libDir / "resources" / "fonts" / fontFile;
                if (fs::exists(candidate))
                    return candidate.string();
            }
        }
    }
#elif defined(__linux__) || defined(__APPLE__)
    {
        Dl_info info;
        if (dladdr(reinterpret_cast<void*>(&findFontPath), &info) && info.dli_fname)
        {
            fs::path dir = fs::path(info.dli_fname).parent_path();
            for (int up = 0; up < 8 && !dir.empty(); ++up, dir = dir.parent_path())
            {
                fs::path candidate = dir / "resources" / "fonts" / fontFile;
                if (fs::exists(candidate))
                    return candidate.string();
            }
        }
    }
#endif

    {
        fs::path candidate = fs::path("resources") / "fonts" / fontFile;
        if (fs::exists(candidate))
            return candidate.string();
    }

    {
        std::error_code ec;
        fs::path cwd = fs::current_path(ec);
        for (int i = 0; i < 6 && !cwd.empty(); ++i)
        {
            fs::path candidate = cwd / "resources" / "fonts" / fontFile;
            if (fs::exists(candidate))
                return candidate.string();
            cwd = cwd.parent_path();
        }
    }

    return {};
}

// ---------------------------------------------------------------------------
// Destructor
// ---------------------------------------------------------------------------

HeadlessVulkanPlatform::~HeadlessVulkanPlatform()
{
    if (m_vulkanBackend)
    {
        m_vulkanBackend.reset();
        ImGui::DestroyContext();
    }
}

// ---------------------------------------------------------------------------
// Window lifecycle
// ---------------------------------------------------------------------------

WindowId HeadlessVulkanPlatform::createWindow(const char* title, int width, int height)
{
    if (m_mainWindowId != kInvalidWindowId)
    {
        fprintf(stderr, "HeadlessVulkanPlatform::createWindow: already initialized\n");
        return m_mainWindowId;
    }

    m_title = title ? title : "omni.ui (headless)";
    m_width = width;
    m_height = height;

    // Initialize Vulkan in headless mode (no GLFW, no display)
    m_vulkanBackend = std::make_unique<VulkanBackend>();
    if (!m_vulkanBackend->initHeadless(width, height))
    {
        fprintf(stderr, "HeadlessVulkanPlatform::createWindow: Vulkan headless init failed\n");
        m_vulkanBackend.reset();
        return kInvalidWindowId;
    }

    // Initialize ImGui
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    io.ConfigFlags |= ImGuiConfigFlags_DockingEnable;

    // Headless has no OS cursor — ImGui must draw a software cursor so
    // injected mouse positions are visible in captured/streamed frames.
    io.MouseDrawCursor = true;

    // Set display size for headless rendering
    io.DisplaySize = ImVec2(static_cast<float>(width), static_cast<float>(height));
    io.DisplayFramebufferScale = ImVec2(1.0f, 1.0f);

    // Apply NVIDIA Dark theme (same as GlfwPlatform)
    {
        ImGuiStyle& s = ImGui::GetStyle();
        s.WindowPadding     = ImVec2(8.0f, 8.0f);
        s.PopupRounding     = 4.0f;
        s.FramePadding      = ImVec2(8.0f, 4.0f);
        s.ItemSpacing       = ImVec2(6.0f, 6.0f);
        s.ItemInnerSpacing  = ImVec2(4.0f, 4.0f);
        s.TouchExtraPadding = ImVec2(0.0f, 0.0f);
        s.IndentSpacing     = 21.0f;
        s.ScrollbarSize     = 16.0f;
        s.GrabMinSize       = 8.0f;
        s.WindowBorderSize  = 1.0f;
        s.ChildBorderSize   = 1.0f;
        s.PopupBorderSize   = 1.0f;
        s.FrameBorderSize   = 0.0f;
        s.TabBorderSize     = 0.0f;
        s.WindowRounding    = 2.0f;
        s.ChildRounding     = 0.0f;
        s.FrameRounding     = 4.0f;
        s.ScrollbarRounding = 4.0f;
        s.GrabRounding      = 4.0f;
        s.TabRounding       = 4.0f;
        s.WindowTitleAlign  = ImVec2(0.5f, 0.5f);
        s.ButtonTextAlign   = ImVec2(0.48f, 0.5f);
        s.DisplaySafeAreaPadding = ImVec2(3.0f, 3.0f);

        s.Colors[ImGuiCol_Text]                  = ImVec4(0.80f, 0.80f, 0.80f, 1.00f);
        s.Colors[ImGuiCol_TextDisabled]          = ImVec4(0.43f, 0.43f, 0.43f, 1.00f);
        s.Colors[ImGuiCol_WindowBg]              = ImVec4(0.27f, 0.27f, 0.27f, 1.00f);
        s.Colors[ImGuiCol_ChildBg]               = ImVec4(0.27f, 0.27f, 0.27f, 1.00f);
        s.Colors[ImGuiCol_PopupBg]               = ImVec4(0.22f, 0.23f, 0.24f, 1.00f);
        s.Colors[ImGuiCol_Border]                = ImVec4(0.27f, 0.27f, 0.27f, 1.00f);
        s.Colors[ImGuiCol_BorderShadow]          = ImVec4(0.27f, 0.27f, 0.27f, 1.00f);
        s.Colors[ImGuiCol_FrameBg]               = ImVec4(0.12f, 0.13f, 0.14f, 1.00f);
        s.Colors[ImGuiCol_FrameBgHovered]        = ImVec4(0.12f, 0.13f, 0.14f, 1.00f);
        s.Colors[ImGuiCol_FrameBgActive]         = ImVec4(0.22f, 0.22f, 0.22f, 1.00f);
        s.Colors[ImGuiCol_TitleBg]               = ImVec4(0.12f, 0.13f, 0.14f, 1.00f);
        s.Colors[ImGuiCol_TitleBgActive]         = ImVec4(0.12f, 0.13f, 0.14f, 1.00f);
        s.Colors[ImGuiCol_TitleBgCollapsed]      = ImVec4(0.12f, 0.13f, 0.14f, 1.00f);
        s.Colors[ImGuiCol_MenuBarBg]             = ImVec4(0.27f, 0.27f, 0.27f, 1.00f);
        s.Colors[ImGuiCol_ScrollbarBg]           = ImVec4(0.12f, 0.13f, 0.14f, 1.00f);
        s.Colors[ImGuiCol_ScrollbarGrab]         = ImVec4(0.62f, 0.62f, 0.62f, 1.00f);
        s.Colors[ImGuiCol_ScrollbarGrabHovered]  = ImVec4(1.00f, 0.99f, 0.99f, 0.58f);
        s.Colors[ImGuiCol_ScrollbarGrabActive]   = ImVec4(0.47f, 0.53f, 0.54f, 0.76f);
        s.Colors[ImGuiCol_CheckMark]             = ImVec4(0.80f, 0.80f, 0.80f, 1.00f);
        s.Colors[ImGuiCol_SliderGrab]            = ImVec4(0.62f, 0.62f, 0.62f, 1.00f);
        s.Colors[ImGuiCol_SliderGrabActive]      = ImVec4(0.47f, 0.53f, 0.54f, 0.76f);
        s.Colors[ImGuiCol_Button]                = ImVec4(0.16f, 0.16f, 0.16f, 1.00f);
        s.Colors[ImGuiCol_ButtonHovered]         = ImVec4(0.62f, 0.62f, 0.62f, 1.00f);
        s.Colors[ImGuiCol_ButtonActive]          = ImVec4(0.47f, 0.53f, 0.54f, 0.76f);
        s.Colors[ImGuiCol_Header]                = ImVec4(0.20f, 0.20f, 0.20f, 1.00f);
        s.Colors[ImGuiCol_HeaderHovered]         = ImVec4(0.22f, 0.22f, 0.22f, 1.00f);
        s.Colors[ImGuiCol_HeaderActive]          = ImVec4(0.30f, 0.30f, 0.30f, 1.00f);
        s.Colors[ImGuiCol_Separator]             = ImVec4(0.12f, 0.13f, 0.14f, 1.00f);
        s.Colors[ImGuiCol_SeparatorHovered]      = ImVec4(0.23f, 0.44f, 0.69f, 1.00f);
        s.Colors[ImGuiCol_SeparatorActive]       = ImVec4(0.26f, 0.59f, 0.98f, 1.00f);
        s.Colors[ImGuiCol_ResizeGrip]            = ImVec4(0.47f, 0.53f, 0.54f, 0.76f);
        s.Colors[ImGuiCol_ResizeGripHovered]     = ImVec4(0.23f, 0.44f, 0.69f, 1.00f);
        s.Colors[ImGuiCol_ResizeGripActive]      = ImVec4(0.26f, 0.59f, 0.98f, 1.00f);
        s.Colors[ImGuiCol_Tab]                   = ImVec4(0.192f, 0.192f, 0.192f, 1.00f);
        s.Colors[ImGuiCol_TabHovered]            = ImVec4(0.20f, 0.20f, 0.20f, 1.00f);
        // ImGui 1.90.9 renamed these; the obsolete aliases are compiled out by
        // IMGUI_DISABLE_OBSOLETE_FUNCTIONS (imconfig.h).
        s.Colors[ImGuiCol_TabSelected]           = ImVec4(0.27f, 0.27f, 0.27f, 1.00f);
        s.Colors[ImGuiCol_TabDimmed]             = ImVec4(0.192f, 0.192f, 0.192f, 1.00f);
        s.Colors[ImGuiCol_TabDimmedSelected]     = ImVec4(0.27f, 0.27f, 0.27f, 1.00f);
        s.Colors[ImGuiCol_DockingPreview]        = ImVec4(0.26f, 0.59f, 0.98f, 0.70f);
        s.Colors[ImGuiCol_DockingEmptyBg]        = ImVec4(0.25f, 0.25f, 0.25f, 1.00f);
        s.Colors[ImGuiCol_PlotLines]             = ImVec4(0.12f, 0.13f, 0.14f, 1.00f);
        s.Colors[ImGuiCol_PlotLinesHovered]      = ImVec4(0.22f, 0.23f, 0.24f, 1.00f);
        s.Colors[ImGuiCol_PlotHistogram]         = ImVec4(0.90f, 0.70f, 0.00f, 1.00f);
        s.Colors[ImGuiCol_PlotHistogramHovered]  = ImVec4(1.00f, 0.60f, 0.00f, 1.00f);
        s.Colors[ImGuiCol_TextSelectedBg]        = ImVec4(0.97f, 0.97f, 0.97f, 0.19f);
        s.Colors[ImGuiCol_DragDropTarget]        = ImVec4(0.38f, 0.62f, 0.80f, 1.00f);
        // ImGuiCol_NavHighlight was renamed to ImGuiCol_NavCursor in 1.91.4 and
        // the obsolete alias is compiled out by IMGUI_DISABLE_OBSOLETE_FUNCTIONS.
        s.Colors[ImGuiCol_NavCursor]             = ImVec4(0.26f, 0.59f, 0.98f, 1.00f);
        s.Colors[ImGuiCol_NavWindowingHighlight] = ImVec4(1.00f, 1.00f, 1.00f, 0.70f);
        s.Colors[ImGuiCol_NavWindowingDimBg]     = ImVec4(1.00f, 1.00f, 1.00f, 0.70f);
        s.Colors[ImGuiCol_ModalWindowDimBg]      = ImVec4(0.80f, 0.80f, 0.80f, 0.35f);
        s.Colors[ImGuiCol_WindowShadow]          = ImVec4(0.0f, 0.0f, 0.0f, 0.0f);
    }

    // Load fonts (cascade kept in sync with GlfwPlatform body cascade).
    {
        std::string fontPath = findFontPath("NotoSans-Regular.ttf");
        if (fontPath.empty())
            fontPath = findFontPath("roboto_medium.ttf");

        auto glyphManager = std::make_shared<StandaloneGlyphManager>();
        if (!fontPath.empty() && glyphManager->loadFonts(fontPath, 1.0f))
        {
            fprintf(stdout, "HeadlessVulkanPlatform: loaded font %s\n", fontPath.c_str());
            auto* normalFont = reinterpret_cast<ImFont*>(
                glyphManager->getFont(FontStyle::eLarge));
            if (normalFont)
                io.FontDefault = normalFont;

            PlatformRegistry::instance().setGlyphManager(glyphManager);
        }
        else
        {
            fprintf(stdout, "HeadlessVulkanPlatform: using ImGui default font\n");
        }
    }

    // Initialize ImGui Vulkan backend
    m_vulkanBackend->initImGui();

    m_mainWindowId = m_nextWindowId++;
    fprintf(stdout, "HeadlessVulkanPlatform: initialized (%dx%d)\n", width, height);
    return m_mainWindowId;
}

void HeadlessVulkanPlatform::destroyWindow(WindowId id)
{
    if (id != m_mainWindowId)
        return;
    m_vulkanBackend.reset();
    ImGui::DestroyContext();
    m_mainWindowId = kInvalidWindowId;
}

WindowId HeadlessVulkanPlatform::createVirtualWindow(int /*width*/, int /*height*/)
{
    return kInvalidWindowId;
}

void HeadlessVulkanPlatform::destroyVirtualWindow(WindowId /*id*/) {}
void HeadlessVulkanPlatform::resizeVirtualWindow(WindowId /*id*/, int /*width*/, int /*height*/) {}

// ---------------------------------------------------------------------------
// Window state — headless stubs with stored dimensions
// ---------------------------------------------------------------------------

void HeadlessVulkanPlatform::getWindowSize(WindowId id, int* width, int* height)
{
    if (id == m_mainWindowId)
    {
        if (width) *width = m_width;
        if (height) *height = m_height;
    }
    else
    {
        if (width) *width = 0;
        if (height) *height = 0;
    }
}

void HeadlessVulkanPlatform::setWindowSize(WindowId id, int width, int height)
{
    if (id == m_mainWindowId)
    {
        m_width = width;
        m_height = height;
    }
}

void HeadlessVulkanPlatform::setMainWindowSize(int width, int height)
{
    if (width <= 0 || height <= 0)
        return;
    m_width = width;
    m_height = height;
    // The VulkanBackend's beginFrame() picks up the new dimensions on
    // the next tick and recreates the framebuffer (VulkanBackend.cpp
    // :566-573 — vkDeviceWaitIdle + createFramebuffer when extents
    // differ). Callers that need the new framebuffer to be the source
    // of truth must drive one tick afterward.
}

void HeadlessVulkanPlatform::getWindowPosition(WindowId /*id*/, int* x, int* y)
{
    if (x) *x = 0;
    if (y) *y = 0;
}

void HeadlessVulkanPlatform::setWindowPosition(WindowId /*id*/, int /*x*/, int /*y*/) {}

std::string HeadlessVulkanPlatform::getWindowTitle(WindowId id)
{
    if (id == m_mainWindowId)
        return m_title;
    return {};
}

void HeadlessVulkanPlatform::setWindowTitle(WindowId id, const char* title)
{
    if (id == m_mainWindowId && title)
        m_title = title;
}

bool HeadlessVulkanPlatform::isFullscreen(WindowId /*id*/) { return false; }
void HeadlessVulkanPlatform::setFullscreen(WindowId /*id*/, bool /*fullscreen*/) {}
bool HeadlessVulkanPlatform::isMaximized(WindowId /*id*/) { return false; }
void HeadlessVulkanPlatform::setMaximized(WindowId /*id*/, bool /*maximized*/) {}
bool HeadlessVulkanPlatform::isFocused(WindowId /*id*/) { return true; }
void HeadlessVulkanPlatform::setFocused(WindowId /*id*/) {}
bool HeadlessVulkanPlatform::isVisible(WindowId /*id*/) { return false; }
void HeadlessVulkanPlatform::setVisible(WindowId /*id*/, bool /*visible*/) {}
bool HeadlessVulkanPlatform::isFloating(WindowId /*id*/) { return false; }
void HeadlessVulkanPlatform::setFloating(WindowId /*id*/, bool /*floating*/) {}
void HeadlessVulkanPlatform::setWindowIcon(WindowId /*id*/, const uint8_t* /*pixels*/, int /*width*/, int /*height*/) {}

void HeadlessVulkanPlatform::requestClose(WindowId id)
{
    if (id == m_mainWindowId)
        m_shouldClose = true;
}

// -- DPI and scaling --
float HeadlessVulkanPlatform::getDpiScale(WindowId /*id*/) { return 1.0f; }
float HeadlessVulkanPlatform::getContentScale(WindowId /*id*/) { return 1.0f; }

// -- Cursor control --
void HeadlessVulkanPlatform::setCursorShape(int /*imguiCursorType*/) {}
void HeadlessVulkanPlatform::setCursorVisible(bool /*visible*/) {}

// -- Monitor info --
int HeadlessVulkanPlatform::getMonitorCount() { return 0; }
void HeadlessVulkanPlatform::getMonitorWorkArea(int /*monitorIndex*/, int* x, int* y, int* width, int* height)
{
    if (x) *x = 0;
    if (y) *y = 0;
    if (width) *width = m_width;
    if (height) *height = m_height;
}

// -- Clipboard --
std::string HeadlessVulkanPlatform::getClipboard() { return {}; }
void HeadlessVulkanPlatform::setClipboard(const char* /*text*/) {}

// -- Input injection --
void HeadlessVulkanPlatform::injectMouseMove(WindowId /*id*/, float x, float y)
{
    ImGuiIO& io = ImGui::GetIO();
    io.MousePos = ImVec2(x, y);
}

void HeadlessVulkanPlatform::injectMouseButton(WindowId /*id*/, MouseButton button, bool pressed)
{
    int idx = static_cast<int>(button);
    if (idx >= 0 && idx < 5)
    {
        ImGuiIO& io = ImGui::GetIO();
        io.MouseDown[idx] = pressed;
    }
}

void HeadlessVulkanPlatform::injectMouseScroll(WindowId /*id*/, float dx, float dy)
{
    ImGuiIO& io = ImGui::GetIO();
    io.MouseWheelH += dx;
    io.MouseWheel += dy;
}

void HeadlessVulkanPlatform::injectKeyEvent(WindowId /*id*/, int imguiKey, bool pressed,
                                             KeyboardModifierFlags modifiers)
{
    ImGuiIO& io = ImGui::GetIO();
    const ImGuiKey key = detail::normalizeInjectedImguiKey(imguiKey);
    if (key != ImGuiKey_None)
        io.AddKeyEvent(key, pressed);

    io.AddKeyEvent(ImGuiMod_Ctrl,  (modifiers & kKeyModCtrl)  != 0);
    io.AddKeyEvent(ImGuiMod_Shift, (modifiers & kKeyModShift) != 0);
    io.AddKeyEvent(ImGuiMod_Alt,   (modifiers & kKeyModAlt)   != 0);
    io.AddKeyEvent(ImGuiMod_Super, (modifiers & kKeyModSuper) != 0);
}

void HeadlessVulkanPlatform::injectCharEvent(WindowId /*id*/, uint32_t codepoint)
{
    ImGuiIO& io = ImGui::GetIO();
    io.AddInputCharacter(codepoint);
}

void HeadlessVulkanPlatform::setInputBlocking(bool /*blocked*/) {}

// ---------------------------------------------------------------------------
// Deferred operations
// ---------------------------------------------------------------------------

DeferHandle HeadlessVulkanPlatform::deferToEndOfFrame(std::function<void()> callback, int32_t priority)
{
    auto token = std::make_shared<int>(1);
    {
        std::lock_guard<std::mutex> lock(m_deferMutex);
        m_deferredQueue.push_back({token, std::move(callback), priority, false});
    }
    return token;
}

DeferHandle HeadlessVulkanPlatform::observeEndOfFrame(std::function<void()> callback, int32_t priority)
{
    auto token = std::make_shared<int>(1);
    {
        std::lock_guard<std::mutex> lock(m_deferMutex);
        m_deferredQueue.push_back({token, std::move(callback), priority, true});
    }
    return token;
}

void HeadlessVulkanPlatform::drainDeferredQueue()
{
    std::vector<DeferredEntry> snapshot;
    {
        std::lock_guard<std::mutex> lock(m_deferMutex);
        snapshot = m_deferredQueue;
        m_deferredQueue.erase(
            std::remove_if(m_deferredQueue.begin(), m_deferredQueue.end(),
                           [](const DeferredEntry& e) { return !e.persistent; }),
            m_deferredQueue.end());
        m_deferredQueue.erase(
            std::remove_if(m_deferredQueue.begin(), m_deferredQueue.end(),
                           [](const DeferredEntry& e) { return e.cancelToken.expired(); }),
            m_deferredQueue.end());
    }

    std::sort(snapshot.begin(), snapshot.end(),
              [](const DeferredEntry& a, const DeferredEntry& b) {
                  return a.priority < b.priority;
              });

    for (auto& entry : snapshot)
    {
        if (!entry.cancelToken.expired() && entry.callback)
            entry.callback();
    }
}

// ---------------------------------------------------------------------------
// Run loop
// ---------------------------------------------------------------------------

bool HeadlessVulkanPlatform::tick()
{
    if (!m_vulkanBackend || !m_vulkanBackend->isInitialized())
        return false;

    // Update ImGui display size (in case it changed)
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(static_cast<float>(m_width), static_cast<float>(m_height));

    // Advance delta time
    static auto s_lastTime = std::chrono::steady_clock::now();
    auto now = std::chrono::steady_clock::now();
    float elapsed = std::chrono::duration<float>(now - s_lastTime).count();
    s_lastTime = now;
    io.DeltaTime = elapsed > 0.0f ? elapsed : (1.0f / 60.0f);

    // Start ImGui frame
    ImGui_ImplVulkan_NewFrame();

    // In headless mode, we skip ImGui_ImplGlfw_NewFrame() — set IO directly
    applyInjectedInput();

    ImGui::NewFrame();

    // Draw all omni.ui windows
    {
        StandaloneWindowCallbackManager* wcm = getStandaloneWindowCallbackManager();
        if (wcm)
            wcm->drawAllWindows(elapsed);
    }

    // Render ImGui
    ImGui::Render();

    // Drain deferred queue
    drainDeferredQueue();

    // Render to offscreen framebuffer
    if (m_width > 0 && m_height > 0)
    {
        m_vulkanBackend->beginFrame(m_width, m_height);
        ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), m_vulkanBackend->getCommandBuffer());
        m_vulkanBackend->endFrame();
    }

    // Pre-swap callback (screenshot capture)
    if (m_preSwapCallback)
    {
        auto cb = std::move(m_preSwapCallback);
        m_preSwapCallback = nullptr;
        cb();
    }

    return !m_shouldClose;
}

bool HeadlessVulkanPlatform::shouldClose()
{
    return m_shouldClose;
}

// -- Busy state --
void HeadlessVulkanPlatform::setBusy(bool busy) { m_busy = busy; }

// -- Framebuffer access --
uint64_t HeadlessVulkanPlatform::getFramebufferTexture(WindowId /*id*/) { return 0; }

// ---------------------------------------------------------------------------
// App window management — headless stubs
// ---------------------------------------------------------------------------

AppWindowHandle HeadlessVulkanPlatform::getDefaultAppWindowHandle() { return reinterpret_cast<AppWindowHandle>(1); }
AppWindowHandle HeadlessVulkanPlatform::createDetachedAppWindow(const char*, int, int, int, int) { return nullptr; }
bool HeadlessVulkanPlatform::isMultiWindowSupported() { return false; }
bool HeadlessVulkanPlatform::isAppRunning() { return !m_shouldClose; }
bool HeadlessVulkanPlatform::isAppWindowVirtual(AppWindowHandle) { return false; }

Int2 HeadlessVulkanPlatform::getAppWindowCursorPosition(AppWindowHandle)
{
    return {};
}

Int2 HeadlessVulkanPlatform::getAppWindowOsPosition(AppWindowHandle)
{
    return {};
}

void HeadlessVulkanPlatform::setAppWindowOsPosition(AppWindowHandle, int, int) {}
void HeadlessVulkanPlatform::resizeAppWindow(AppWindowHandle, int w, int h)
{
    m_width = w;
    m_height = h;
}

void HeadlessVulkanPlatform::getAppWindowSize(AppWindowHandle, int* width, int* height)
{
    getWindowSize(m_mainWindowId, width, height);
}

bool HeadlessVulkanPlatform::isMouseInputBlocked(AppWindowHandle) { return false; }
bool HeadlessVulkanPlatform::getAppWindowCursorBlink(AppWindowHandle) { return true; }
DeferHandle HeadlessVulkanPlatform::deferDestroyAppWindow(AppWindowHandle) { return {}; }
DeferHandle HeadlessVulkanPlatform::observeAppWindowClose(AppWindowHandle, std::function<void()>) { return {}; }
float HeadlessVulkanPlatform::getAppWindowDpiScale(AppWindowHandle) { return 1.0f; }

bool HeadlessVulkanPlatform::needsStrongWindowRefs() const { return true; }

} // namespace standalone
} // namespace ui
} // namespace omni
