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

#ifdef OMNIUI_HAS_EGL

#include "StandaloneInit.h"
#include <omni/ui/platform/IUiPlatform.h>

#include <EGL/egl.h>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {

/// Headless IUiPlatform implementation backed by EGL surfaceless rendering.
/// No windowing system required. Renders to an offscreen OpenGL FBO.
/// E3: createWindow() implements EGL_EXT_platform_device enumerate strategy.
class OMNIUI_STANDALONE_API HeadlessEglPlatform final : public IUiPlatform
{
public:
    HeadlessEglPlatform();
    ~HeadlessEglPlatform() override;

    // -- EGL screenshot API --------------------------------------------------
    void captureScreenshot(const std::string& path, uint64_t requestId);
    bool isScreenshotDone() const;
    bool hadScreenshotError() const;
    uint64_t screenshotRequestId() const;
    const std::string& screenshotActualFormat() const;
    int screenshotWidth() const;
    int screenshotHeight() const;
    const std::string& screenshotErrorMessage() const;

    // -- Window lifecycle ----------------------------------------------------
    WindowId createWindow(const char* title, int width, int height) override;
    void destroyWindow(WindowId id) override;
    WindowId createVirtualWindow(int width, int height) override;
    void destroyVirtualWindow(WindowId id) override;
    void resizeVirtualWindow(WindowId id, int width, int height) override;

    // -- Window state --------------------------------------------------------
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

    // -- DPI and scaling -----------------------------------------------------
    float getDpiScale(WindowId id) override;
    float getContentScale(WindowId id) override;

    // -- Cursor control ------------------------------------------------------
    void setCursorShape(int imguiCursorType) override;
    void setCursorVisible(bool visible) override;

    // -- Monitor info --------------------------------------------------------
    int getMonitorCount() override;
    void getMonitorWorkArea(int monitorIndex, int* x, int* y,
                            int* width, int* height) override;

    // -- Clipboard -----------------------------------------------------------
    std::string getClipboard() override;
    void setClipboard(const char* text) override;

    // -- Input injection -----------------------------------------------------
    void injectMouseMove(WindowId id, float x, float y) override;
    void injectMouseButton(WindowId id, MouseButton button, bool pressed) override;
    void injectMouseScroll(WindowId id, float dx, float dy) override;
    void injectKeyEvent(WindowId id, int imguiKey, bool pressed,
                        KeyboardModifierFlags modifiers) override;
    void injectCharEvent(WindowId id, uint32_t codepoint) override;
    void setInputBlocking(bool blocked) override;

    // -- Deferred operations -------------------------------------------------
    DeferHandle deferToEndOfFrame(std::function<void()> callback,
                                  int32_t priority) override;
    DeferHandle observeEndOfFrame(std::function<void()> callback,
                                  int32_t priority) override;

    // -- Run loop ------------------------------------------------------------
    bool tick() override;
    bool shouldClose() override;

    // -- Busy state ----------------------------------------------------------
    void setBusy(bool busy) override;

    // -- Framebuffer access --------------------------------------------------
    uint64_t getFramebufferTexture(WindowId id) override;

    // -- App window management -----------------------------------------------
    AppWindowHandle getDefaultAppWindowHandle() override;
    AppWindowHandle createDetachedAppWindow(const char* title,
                                            int x, int y,
                                            int w, int h) override;
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
    DeferHandle observeAppWindowClose(AppWindowHandle window,
                                      std::function<void()> callback) override;
    float getAppWindowDpiScale(AppWindowHandle window) override;

    // -- Window lifetime policy ----------------------------------------------
    bool needsStrongWindowRefs() const override;

private:
    void eglTeardown() noexcept;
    bool setupFboAndImGui(int width, int height);
    void drainDeferredQueue();

    struct DeferredEntry
    {
        std::weak_ptr<void> cancelToken;
        std::function<void()> callback;
        int32_t priority = 0;
        bool persistent  = false;
    };

    EGLDisplay  m_display;              // set to EGL_NO_DISPLAY in constructor
    EGLContext  m_context;              // set to EGL_NO_CONTEXT in constructor
    EGLConfig   m_config             = nullptr;
    uint32_t    m_fbo                = 0;  // GLuint: OpenGL framebuffer object
    uint32_t    m_rbo                = 0;  // GLuint: OpenGL renderbuffer object
    int         m_width              = 0;
    int         m_height             = 0;
    WindowId    m_mainWindowId       = kInvalidWindowId;
    WindowId    m_nextWindowId       = 1;
    std::string m_pendingScreenshotPath;
    uint64_t    m_pendingScreenshotRequestId = 0;
    bool        m_imguiContextCreated = false;  // ImGui::CreateContext() succeeded
    bool        m_imguiInitialized    = false;  // ImGui_ImplOpenGL3_Init() succeeded
    bool        m_screenshotDone      = false;
    bool        m_screenshotError     = false;
    std::string m_screenshotActualFormat;
    int         m_screenshotWidth     = 0;
    int         m_screenshotHeight    = 0;
    std::string m_screenshotErrorMessage;
    std::mutex              m_deferMutex;
    std::vector<DeferredEntry> m_deferredQueue;
};

} // namespace standalone
} // namespace ui
} // namespace omni

#endif // OMNIUI_HAS_EGL
