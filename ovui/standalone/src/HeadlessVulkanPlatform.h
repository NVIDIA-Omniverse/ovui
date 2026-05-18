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

#pragma once

#include "StandaloneInit.h" // OMNIUI_STANDALONE_API
#include <omni/ui/platform/IUiPlatform.h>

#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {

class VulkanBackend;

/// Headless IUiPlatform implementation for server-side Vulkan rendering.
/// No windowing system required — no GLFW, no X11, no Wayland.
/// Renders to an offscreen VkImage with CPU readback support.
class OMNIUI_STANDALONE_API HeadlessVulkanPlatform final : public IUiPlatform
{
public:
    HeadlessVulkanPlatform() = default;
    ~HeadlessVulkanPlatform() override;

    // -- Window lifecycle --
    WindowId createWindow(const char* title, int width, int height) override;
    void destroyWindow(WindowId id) override;
    WindowId createVirtualWindow(int width, int height) override;
    void destroyVirtualWindow(WindowId id) override;
    void resizeVirtualWindow(WindowId id, int width, int height) override;

    // -- Window state --
    void getWindowSize(WindowId id, int* width, int* height) override;
    void setWindowSize(WindowId id, int width, int height) override;

    /// Resize the main window without needing the WindowId. Used by
    /// the runtime resize path (``standalone::resizeHeadlessFrame`` →
    /// ``_headless_frame_resize`` Python binding) so the caller does
    /// not have to track the platform's internal sequence ids.
    void setMainWindowSize(int width, int height);
    void getWindowPosition(WindowId id, int* x, int* y) override;
    void setWindowPosition(WindowId id, int x, int y) override;
    std::string getWindowTitle(WindowId id) override;
    void setWindowTitle(WindowId id, const char* title) override;
    bool isFullscreen(WindowId id) override;
    void setFullscreen(WindowId id, bool fullscreen) override;
    bool isMaximized(WindowId id) override;
    void setMaximized(WindowId id, bool maximized) override;
    bool isFocused(WindowId id) override;
    void setFocused(WindowId id) override;
    bool isVisible(WindowId id) override;
    void setVisible(WindowId id, bool visible) override;
    bool isFloating(WindowId id) override;
    void setFloating(WindowId id, bool floating) override;
    void setWindowIcon(WindowId id, const uint8_t* pixels, int width, int height) override;
    void requestClose(WindowId id) override;

    // -- DPI and scaling --
    float getDpiScale(WindowId id) override;
    float getContentScale(WindowId id) override;

    // -- Cursor control --
    void setCursorShape(int imguiCursorType) override;
    void setCursorVisible(bool visible) override;

    // -- Monitor info --
    int getMonitorCount() override;
    void getMonitorWorkArea(int monitorIndex, int* x, int* y, int* width, int* height) override;

    // -- Clipboard --
    std::string getClipboard() override;
    void setClipboard(const char* text) override;

    // -- Input injection --
    void injectMouseMove(WindowId id, float x, float y) override;
    void injectMouseButton(WindowId id, MouseButton button, bool pressed) override;
    void injectMouseScroll(WindowId id, float dx, float dy) override;
    void injectKeyEvent(WindowId id, int imguiKey, bool pressed,
                        KeyboardModifierFlags modifiers) override;
    void injectCharEvent(WindowId id, uint32_t codepoint) override;
    void setInputBlocking(bool blocked) override;

    // -- Deferred operations --
    DeferHandle deferToEndOfFrame(std::function<void()> callback, int32_t priority) override;
    DeferHandle observeEndOfFrame(std::function<void()> callback, int32_t priority) override;

    // -- Run loop --
    bool tick() override;
    bool shouldClose() override;

    // -- Busy state --
    void setBusy(bool busy) override;

    // -- Framebuffer access --
    uint64_t getFramebufferTexture(WindowId id) override;

    // -- App window management --
    AppWindowHandle getDefaultAppWindowHandle() override;
    AppWindowHandle createDetachedAppWindow(const char* title, int x, int y, int w, int h) override;
    bool isMultiWindowSupported() override;
    bool isAppRunning() override;
    bool isAppWindowVirtual(AppWindowHandle window) override;
    Int2 getAppWindowCursorPosition(AppWindowHandle window) override;
    Int2 getAppWindowOsPosition(AppWindowHandle window) override;
    void setAppWindowOsPosition(AppWindowHandle window, int x, int y) override;
    void resizeAppWindow(AppWindowHandle window, int w, int h) override;
    void getAppWindowSize(AppWindowHandle window, int* width, int* height) override;
    bool isMouseInputBlocked(AppWindowHandle window) override;
    bool getAppWindowCursorBlink(AppWindowHandle window) override;
    DeferHandle deferDestroyAppWindow(AppWindowHandle window) override;
    DeferHandle observeAppWindowClose(AppWindowHandle window, std::function<void()> callback) override;
    float getAppWindowDpiScale(AppWindowHandle window) override;

    // -- Window lifetime policy --
    bool needsStrongWindowRefs() const override;

    /// Set a one-shot callback invoked after ImGui render (for screenshot capture).
    using PreSwapCallback = std::function<void()>;
    void setPreSwapCallback(PreSwapCallback cb) { m_preSwapCallback = std::move(cb); }

    /// Access the Vulkan backend.
    VulkanBackend* getVulkanBackend() const { return m_vulkanBackend.get(); }

    /// Request the headless loop to stop.
    void requestShutdown() { m_shouldClose = true; }

private:
    void drainDeferredQueue();

    WindowId m_mainWindowId = kInvalidWindowId;
    WindowId m_nextWindowId = 1;
    std::string m_title;
    int m_width = 0;
    int m_height = 0;
    bool m_shouldClose = false;
    bool m_busy = false;

    std::unique_ptr<VulkanBackend> m_vulkanBackend;

    struct DeferredEntry
    {
        std::weak_ptr<void> cancelToken;
        std::function<void()> callback;
        int32_t priority = 0;
        bool persistent = false;
    };

    std::mutex m_deferMutex;
    std::vector<DeferredEntry> m_deferredQueue;

    PreSwapCallback m_preSwapCallback;
};

} // namespace standalone
} // namespace ui
} // namespace omni
