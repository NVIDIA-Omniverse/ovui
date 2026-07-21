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

#include "StandaloneInit.h"

#include <omni/ui/platform/IUiPlatform.h>

#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

struct GLFWwindow;

namespace omni {
namespace ui {
namespace standalone {

class VulkanBackend;

/// Rendering backend selection
enum class BackendType
{
    eOpenGL,
    eVulkan,
};

/// Standalone IUiPlatform implementation using GLFW for windowing and input.
/// Supports a single OS window (V1) and a deferred callback queue sorted by
/// priority that is drained after ImGui::Render() each frame.
class OMNIUI_STANDALONE_API GlfwPlatform final : public IUiPlatform
{
public:
    GlfwPlatform() = default;
    ~GlfwPlatform() override;

    // -- Window lifecycle --
    WindowId createWindow(const char* title, int width, int height) override;
    void destroyWindow(WindowId id) override;
    WindowId createVirtualWindow(int width, int height) override;
    void destroyVirtualWindow(WindowId id) override;
    void resizeVirtualWindow(WindowId id, int width, int height) override;

    // -- Window state --
    void getWindowSize(WindowId id, int* width, int* height) override;
    void setWindowSize(WindowId id, int width, int height) override;
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

    // -- App window management (multi-window support) --
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

    /// Access the raw GLFW window pointer (for ImGui backend init, etc.)
    GLFWwindow* getGlfwWindow() const { return m_window; }

    /// Set a one-shot callback invoked after ImGui render but before buffer swap.
    /// The callback is cleared after being called.
    using PreSwapCallback = std::function<void()>;
    void setPreSwapCallback(PreSwapCallback cb) { m_preSwapCallback = std::move(cb); }

    /// Set the active render target. When set to a virtual window ID, tick()
    /// renders to that window's FBO instead of the default framebuffer and
    /// skips glfwSwapBuffers. Set to kInvalidWindowId to restore normal rendering.
    void setRenderTarget(WindowId id) { m_renderTargetId = id; }

    /// Get the current render target (kInvalidWindowId = default framebuffer).
    WindowId getRenderTarget() const { return m_renderTargetId; }

    /// Get the backend type being used.
    BackendType getBackendType() const { return m_backendType; }

    /// Access the Vulkan backend (only valid when backendType == eVulkan).
#ifdef OMNIUI_HAS_VULKAN
    VulkanBackend* getVulkanBackend() const { return m_vulkanBackend.get(); }
#endif

private:
    void drainDeferredQueue();

    /// Create (or recreate) GL FBO attachments for a virtual window entry.
    /// The VirtualWindowInfo must already have width/height set.
    struct VirtualWindowInfo;
    bool createFboAttachments(VirtualWindowInfo& vw);

    /// Delete GL objects owned by a VirtualWindowInfo (FBO, texture, renderbuffer).
    void deleteFboAttachments(VirtualWindowInfo& vw);

    GLFWwindow* m_window = nullptr;
    WindowId m_mainWindowId = kInvalidWindowId;
    WindowId m_nextWindowId = 1;
    WindowId m_renderTargetId = kInvalidWindowId;
    std::string m_title;
    bool m_inputBlocked = false;
    bool m_busy = false;
    BackendType m_backendType = BackendType::eOpenGL;
#ifdef OMNIUI_HAS_VULKAN
    std::unique_ptr<VulkanBackend> m_vulkanBackend;
#endif

    /// State for a single FBO-backed virtual window.
    struct VirtualWindowInfo
    {
        uint32_t fbo = 0;          ///< GL framebuffer object
        uint32_t colorTex = 0;     ///< GL RGBA8 color attachment (texture)
        uint32_t depthRbo = 0;     ///< GL depth/stencil renderbuffer
        int width = 0;
        int height = 0;
    };

    std::unordered_map<WindowId, VirtualWindowInfo> m_virtualWindows;

    struct DeferredEntry
    {
        std::weak_ptr<void> cancelToken;
        std::function<void()> callback;
        int32_t priority = 0;
        bool persistent = false; // true for observeEndOfFrame
    };

    std::mutex m_deferMutex;
    std::vector<DeferredEntry> m_deferredQueue;

    PreSwapCallback m_preSwapCallback;
};

} // namespace standalone
} // namespace ui
} // namespace omni
