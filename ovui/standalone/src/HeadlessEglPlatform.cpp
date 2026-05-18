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

#include "HeadlessEglPlatform.h"

#ifdef OMNIUI_HAS_EGL

#include "StandaloneWindowCallbackManager.h"

#include <EGL/eglext.h>
#include <glad/glad.h>
#include <imgui/imgui.h>
#include <imgui/backends/imgui_impl_opengl3.h>

#include <stb_image_write.h>

#include <algorithm>
#include <cassert>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {

HeadlessEglPlatform::HeadlessEglPlatform()
{
    m_display = EGL_NO_DISPLAY;
    m_context = EGL_NO_CONTEXT;
}

HeadlessEglPlatform::~HeadlessEglPlatform()
{
    eglTeardown();
}

// -- EGL resource management -------------------------------------------------

void HeadlessEglPlatform::eglTeardown() noexcept
{
    if (m_display != EGL_NO_DISPLAY)
    {
        // GL/ImGui teardown must happen while the context is still current.
        if (m_imguiInitialized)
        {
            ImGui_ImplOpenGL3_Shutdown();
            m_imguiInitialized = false;
        }
        if (m_imguiContextCreated)
        {
            ImGui::DestroyContext();
            m_imguiContextCreated = false;
        }
        if (m_fbo) { glDeleteFramebuffers(1, &m_fbo);  m_fbo = 0; }
        if (m_rbo) { glDeleteRenderbuffers(1, &m_rbo); m_rbo = 0; }

        // Release context, then destroy it and terminate display.
        eglMakeCurrent(m_display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
        if (m_context != EGL_NO_CONTEXT)
        {
            eglDestroyContext(m_display, m_context);
            m_context = EGL_NO_CONTEXT;
        }
        eglTerminate(m_display);
        m_display = EGL_NO_DISPLAY;
    }
    m_config = nullptr;
}

// -- FBO + ImGui setup (called from both EGL paths after GLAD load) ----------

bool HeadlessEglPlatform::setupFboAndImGui(int width, int height)
{
    glGenFramebuffers(1, &m_fbo);
    glGenRenderbuffers(1, &m_rbo);
    glBindRenderbuffer(GL_RENDERBUFFER, m_rbo);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_RGBA8, width, height);
    glBindFramebuffer(GL_FRAMEBUFFER, m_fbo);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                              GL_RENDERBUFFER, m_rbo);

    GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
    if (status != GL_FRAMEBUFFER_COMPLETE)
    {
        fprintf(stderr, "HeadlessEglPlatform: FBO incomplete (status 0x%x)\n", status);
        eglTeardown();
        return false;
    }
    fprintf(stderr, "HeadlessEglPlatform: FBO complete (%dx%d RGBA8)\n", width, height);

    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    m_imguiContextCreated = true;
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    io.DisplaySize = ImVec2(static_cast<float>(width), static_cast<float>(height));
    ImGui::StyleColorsDark();
    if (!ImGui_ImplOpenGL3_Init("#version 330 core"))
    {
        fprintf(stderr, "HeadlessEglPlatform: ImGui_ImplOpenGL3_Init failed\n");
        eglTeardown();
        return false;
    }
    m_imguiInitialized = true;
    return true;
}

// -- EGL screenshot API ------------------------------------------------------

void HeadlessEglPlatform::captureScreenshot(const std::string& path)
{
    m_pendingScreenshotPath = path;
    m_screenshotDone        = false;
    m_screenshotError       = false;
}

bool HeadlessEglPlatform::isScreenshotDone() const { return m_screenshotDone; }

bool HeadlessEglPlatform::hadScreenshotError() const { return m_screenshotError; }

// -- Window lifecycle --------------------------------------------------------

WindowId HeadlessEglPlatform::createWindow(const char* /*title*/, int width, int height)
{
    // Step 1: env-var override — surfaceless not yet implemented (E4).
    const char* forceSurfaceless = getenv("OMNIUI_EGL_FORCE_SURFACELESS");
    if (forceSurfaceless &&
        (strcmp(forceSurfaceless, "1") == 0 || strcmp(forceSurfaceless, "true") == 0))
    {
        goto SURFACELESS;
    }

    {
        // Step 2: Load EXT procs — required even on GPU hosts.
        auto pfnQueryDevices =
            (PFNEGLQUERYDEVICESEXTPROC)eglGetProcAddress("eglQueryDevicesEXT");
        auto pfnGetPlatformDisplay =
            (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
        if (!pfnQueryDevices || !pfnGetPlatformDisplay)
        {
            fprintf(stderr, "HeadlessEglPlatform: EGL_EXT_device_base unavailable, "
                            "trying surfaceless\n");
            goto SURFACELESS;
        }

        // Step 3: Query EGL devices.
        EGLDeviceEXT devices[64];
        EGLint numDevices = 0;
        pfnQueryDevices(64, devices, &numDevices);
        if (numDevices == 0)
        {
            fprintf(stderr, "HeadlessEglPlatform: no EGL devices found, "
                            "trying surfaceless\n");
            goto SURFACELESS;
        }

        // Step 4: Get display for the first device.
        m_display = pfnGetPlatformDisplay(EGL_PLATFORM_DEVICE_EXT, devices[0], nullptr);
        if (m_display == EGL_NO_DISPLAY)
        {
            fprintf(stderr, "HeadlessEglPlatform: eglGetPlatformDisplayEXT returned "
                            "EGL_NO_DISPLAY, trying surfaceless\n");
            goto SURFACELESS;
        }

        // Step 5: Initialise the display.
        EGLint major = 0, minor = 0;
        if (!eglInitialize(m_display, &major, &minor))
        {
            fprintf(stderr, "HeadlessEglPlatform: eglInitialize failed (error 0x%x), "
                            "trying surfaceless\n", eglGetError());
            eglTerminate(m_display);
            m_display = EGL_NO_DISPLAY;
            goto SURFACELESS;
        }

        // Step 6: Bind OpenGL (not GLES).
        eglBindAPI(EGL_OPENGL_API);

        // Step 7: Choose a config — RGBA8 + depth24 + core OpenGL.
        // EGL_SURFACE_TYPE=EGL_DONT_CARE: the default is EGL_WINDOW_BIT, but
        // EGL_EXT_platform_device configs are EGL_PBUFFER_BIT only (no window
        // surfaces). Without this override eglChooseConfig returns 0 configs.
        const EGLint configAttribs[] = {
            EGL_RED_SIZE,        8,
            EGL_GREEN_SIZE,      8,
            EGL_BLUE_SIZE,       8,
            EGL_ALPHA_SIZE,      8,
            EGL_DEPTH_SIZE,      24,
            EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
            EGL_SURFACE_TYPE,    EGL_DONT_CARE,
            EGL_NONE
        };
        EGLint numConfigs = 0;
        eglChooseConfig(m_display, configAttribs, &m_config, 1, &numConfigs);
        if (numConfigs == 0)
        {
            fprintf(stderr, "HeadlessEglPlatform: eglChooseConfig returned 0 configs, "
                            "trying surfaceless\n");
            eglTeardown();
            goto SURFACELESS;
        }

        // Step 8: Create a core OpenGL 3.3 context.
        const EGLint contextAttribs[] = {
            EGL_CONTEXT_MAJOR_VERSION,        3,
            EGL_CONTEXT_MINOR_VERSION,        3,
            EGL_CONTEXT_OPENGL_PROFILE_MASK,  EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT,
            EGL_NONE
        };
        m_context = eglCreateContext(m_display, m_config, EGL_NO_CONTEXT, contextAttribs);
        if (m_context == EGL_NO_CONTEXT)
        {
            fprintf(stderr, "HeadlessEglPlatform: eglCreateContext failed (error 0x%x), "
                            "trying surfaceless\n", eglGetError());
            eglTeardown();
            goto SURFACELESS;
        }

        // Step 9: Make context current (surfaceless — no draw/read surface).
        if (!eglMakeCurrent(m_display, EGL_NO_SURFACE, EGL_NO_SURFACE, m_context))
        {
            fprintf(stderr, "HeadlessEglPlatform: eglMakeCurrent failed (error 0x%x), "
                            "trying surfaceless\n", eglGetError());
            eglTeardown();
            goto SURFACELESS;
        }

        // Step 10: Load GL function pointers.
        if (!gladLoadGLLoader((GLADloadproc)eglGetProcAddress))
        {
            fprintf(stderr, "HeadlessEglPlatform: gladLoadGLLoader failed\n");
            eglTeardown();
            return kInvalidWindowId;
        }

        // Step 10a (E5): FBO + ImGui init.
        if (!setupFboAndImGui(width, height))
            return kInvalidWindowId;  // eglTeardown() called inside helper

        // Step 11: Log success.
        fprintf(stderr,
                "HeadlessEglPlatform: EGL_EXT_platform_device active. "
                "GL vendor: %s, version: %s\n",
                (const char*)glGetString(GL_VENDOR),
                (const char*)glGetString(GL_VERSION));

        // Step 12: Store dimensions and return a valid WindowId.
        m_width        = width;
        m_height       = height;
        m_mainWindowId = m_nextWindowId++;
        return m_mainWindowId;
    }

SURFACELESS:
    // Invariant maintained by every failure path in the device-enumerate block above.
    assert(m_display == EGL_NO_DISPLAY);
    assert(m_context == EGL_NO_CONTEXT);

#ifdef EGL_MESA_platform_surfaceless
    {
        // Load proc — required even for the surfaceless platform.
        auto pfnGetPlatformDisplay =
            (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
        if (!pfnGetPlatformDisplay)
        {
            fprintf(stderr, "HeadlessEglPlatform: surfaceless: "
                            "eglGetPlatformDisplayEXT unavailable\n");
            return kInvalidWindowId;
        }

        m_display = pfnGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA,
                                          EGL_DEFAULT_DISPLAY, nullptr);
        if (m_display == EGL_NO_DISPLAY)
        {
            fprintf(stderr, "HeadlessEglPlatform: surfaceless: "
                            "eglGetPlatformDisplayEXT returned EGL_NO_DISPLAY\n");
            return kInvalidWindowId;
        }

        EGLint major = 0, minor = 0;
        if (!eglInitialize(m_display, &major, &minor))
        {
            fprintf(stderr, "HeadlessEglPlatform: surfaceless: "
                            "eglInitialize failed (error 0x%x)\n", eglGetError());
            eglTerminate(m_display);
            m_display = EGL_NO_DISPLAY;
            return kInvalidWindowId;
        }

        eglBindAPI(EGL_OPENGL_API);

        // Same attribs as E3: RGBA8 + depth24 + core OpenGL; EGL_DONT_CARE
        // overrides the default EGL_WINDOW_BIT filter (surfaceless has no window surfaces).
        const EGLint configAttribs[] = {
            EGL_RED_SIZE,        8,
            EGL_GREEN_SIZE,      8,
            EGL_BLUE_SIZE,       8,
            EGL_ALPHA_SIZE,      8,
            EGL_DEPTH_SIZE,      24,
            EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
            EGL_SURFACE_TYPE,    EGL_DONT_CARE,
            EGL_NONE
        };
        EGLint numConfigs = 0;
        eglChooseConfig(m_display, configAttribs, &m_config, 1, &numConfigs);
        if (numConfigs == 0)
        {
            fprintf(stderr, "HeadlessEglPlatform: surfaceless: "
                            "eglChooseConfig returned 0 configs\n");
            eglTeardown();
            return kInvalidWindowId;
        }

        const EGLint contextAttribs[] = {
            EGL_CONTEXT_MAJOR_VERSION,       3,
            EGL_CONTEXT_MINOR_VERSION,       3,
            EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT,
            EGL_NONE
        };
        m_context = eglCreateContext(m_display, m_config, EGL_NO_CONTEXT, contextAttribs);
        if (m_context == EGL_NO_CONTEXT)
        {
            fprintf(stderr, "HeadlessEglPlatform: surfaceless: "
                            "eglCreateContext failed (error 0x%x)\n", eglGetError());
            eglTeardown();
            return kInvalidWindowId;
        }

        if (!eglMakeCurrent(m_display, EGL_NO_SURFACE, EGL_NO_SURFACE, m_context))
        {
            fprintf(stderr, "HeadlessEglPlatform: surfaceless eglMakeCurrent failed "
                            "(error 0x%x)\n", eglGetError());
            eglTeardown();
            return kInvalidWindowId;
        }

        if (!gladLoadGLLoader((GLADloadproc)eglGetProcAddress))
        {
            fprintf(stderr, "HeadlessEglPlatform: surfaceless: gladLoadGLLoader failed\n");
            eglTeardown();
            return kInvalidWindowId;
        }

        // E5: FBO + ImGui init.
        if (!setupFboAndImGui(width, height))
            return kInvalidWindowId;  // eglTeardown() called inside helper

        fprintf(stderr,
                "HeadlessEglPlatform: EGL_MESA_platform_surfaceless active. "
                "GL vendor: %s, version: %s\n",
                (const char*)glGetString(GL_VENDOR),
                (const char*)glGetString(GL_VERSION));

        m_width        = width;
        m_height       = height;
        m_mainWindowId = m_nextWindowId++;
        return m_mainWindowId;
    }
#else
    fprintf(stderr, "HeadlessEglPlatform: EGL_MESA_platform_surfaceless not available "
                    "at compile time\n");
    return kInvalidWindowId;
#endif
}

void HeadlessEglPlatform::destroyWindow(WindowId id)
{
    if (id != m_mainWindowId)
        return;
    eglTeardown();
    m_mainWindowId = kInvalidWindowId;
    m_width        = 0;
    m_height       = 0;
}

WindowId HeadlessEglPlatform::createVirtualWindow(int /*width*/, int /*height*/)
{
    return kInvalidWindowId;
}

void HeadlessEglPlatform::destroyVirtualWindow(WindowId /*id*/) {}

void HeadlessEglPlatform::resizeVirtualWindow(WindowId /*id*/,
                                               int /*width*/, int /*height*/) {}

// -- Window state ------------------------------------------------------------

void HeadlessEglPlatform::getWindowSize(WindowId /*id*/, int* width, int* height)
{
    if (width)  *width  = m_width;
    if (height) *height = m_height;
}

void HeadlessEglPlatform::setWindowSize(WindowId /*id*/, int width, int height)
{
    m_width  = width;
    m_height = height;
}

void HeadlessEglPlatform::getWindowPosition(WindowId /*id*/, int* x, int* y)
{
    if (x) *x = 0;
    if (y) *y = 0;
}

void        HeadlessEglPlatform::setWindowPosition(WindowId /*id*/, int /*x*/, int /*y*/) {}
std::string HeadlessEglPlatform::getWindowTitle(WindowId /*id*/) { return {}; }
void        HeadlessEglPlatform::setWindowTitle(WindowId /*id*/, const char* /*title*/) {}
bool        HeadlessEglPlatform::isFullscreen(WindowId /*id*/) { return false; }
void        HeadlessEglPlatform::setFullscreen(WindowId /*id*/, bool /*fullscreen*/) {}
bool        HeadlessEglPlatform::isMaximized(WindowId /*id*/) { return false; }
void        HeadlessEglPlatform::setMaximized(WindowId /*id*/, bool /*maximized*/) {}
bool        HeadlessEglPlatform::isFocused(WindowId /*id*/) { return false; }
void        HeadlessEglPlatform::setFocused(WindowId /*id*/) {}
bool        HeadlessEglPlatform::isVisible(WindowId /*id*/) { return true; }
void        HeadlessEglPlatform::setVisible(WindowId /*id*/, bool /*visible*/) {}
bool        HeadlessEglPlatform::isFloating(WindowId /*id*/) { return false; }
void        HeadlessEglPlatform::setFloating(WindowId /*id*/, bool /*floating*/) {}

void HeadlessEglPlatform::setWindowIcon(WindowId /*id*/, const uint8_t* /*pixels*/,
                                         int /*width*/, int /*height*/) {}

void HeadlessEglPlatform::requestClose(WindowId /*id*/) {}

// -- DPI and scaling ---------------------------------------------------------

float HeadlessEglPlatform::getDpiScale(WindowId /*id*/)     { return 1.0f; }
float HeadlessEglPlatform::getContentScale(WindowId /*id*/) { return 1.0f; }

// -- Cursor control ----------------------------------------------------------

void HeadlessEglPlatform::setCursorShape(int /*imguiCursorType*/) {}
void HeadlessEglPlatform::setCursorVisible(bool /*visible*/) {}

// -- Monitor info ------------------------------------------------------------

int HeadlessEglPlatform::getMonitorCount() { return 1; }

void HeadlessEglPlatform::getMonitorWorkArea(int /*monitorIndex*/,
                                              int* x, int* y,
                                              int* width, int* height)
{
    if (x)      *x      = 0;
    if (y)      *y      = 0;
    if (width)  *width  = m_width;
    if (height) *height = m_height;
}

// -- Clipboard ---------------------------------------------------------------

std::string HeadlessEglPlatform::getClipboard()                     { return {}; }
void        HeadlessEglPlatform::setClipboard(const char* /*text*/) {}

// -- Input injection ---------------------------------------------------------

void HeadlessEglPlatform::injectMouseMove(WindowId /*id*/, float /*x*/, float /*y*/) {}

void HeadlessEglPlatform::injectMouseButton(WindowId /*id*/,
                                             MouseButton /*button*/,
                                             bool /*pressed*/) {}

void HeadlessEglPlatform::injectMouseScroll(WindowId /*id*/,
                                             float /*dx*/, float /*dy*/) {}

void HeadlessEglPlatform::injectKeyEvent(WindowId /*id*/, int /*imguiKey*/,
                                          bool /*pressed*/,
                                          KeyboardModifierFlags /*modifiers*/) {}

void HeadlessEglPlatform::injectCharEvent(WindowId /*id*/, uint32_t /*codepoint*/) {}
void HeadlessEglPlatform::setInputBlocking(bool /*blocked*/) {}

// -- Deferred operations -----------------------------------------------------

DeferHandle HeadlessEglPlatform::deferToEndOfFrame(std::function<void()> callback,
                                                    int32_t priority)
{
    auto token = std::make_shared<int>(1);
    {
        std::lock_guard<std::mutex> lock(m_deferMutex);
        m_deferredQueue.push_back({token, std::move(callback), priority, false});
    }
    return token;
}

DeferHandle HeadlessEglPlatform::observeEndOfFrame(std::function<void()> callback,
                                                    int32_t priority)
{
    auto token = std::make_shared<int>(1);
    {
        std::lock_guard<std::mutex> lock(m_deferMutex);
        m_deferredQueue.push_back({token, std::move(callback), priority, true});
    }
    return token;
}

void HeadlessEglPlatform::drainDeferredQueue()
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

// -- Run loop ----------------------------------------------------------------

bool HeadlessEglPlatform::tick()
{
    if (!m_imguiInitialized)
        return true;

    // Update display size and advance delta time.
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(static_cast<float>(m_width), static_cast<float>(m_height));

    static auto s_lastTime = std::chrono::steady_clock::now();
    auto now = std::chrono::steady_clock::now();
    float elapsed = std::chrono::duration<float>(now - s_lastTime).count();
    s_lastTime = now;
    io.DeltaTime = elapsed > 0.0f ? elapsed : (1.0f / 60.0f);

    // Start the OpenGL3 ImGui frame; apply any injected input.
    ImGui_ImplOpenGL3_NewFrame();
    applyInjectedInput();
    ImGui::NewFrame();

    // Caller-driven draw slot: draw all registered omni.ui windows.
    {
        StandaloneWindowCallbackManager* wcm = getStandaloneWindowCallbackManager();
        if (wcm)
            wcm->drawAllWindows(elapsed);
    }

    ImGui::Render();

    // Drain deferred/observer callbacks registered for end-of-frame.
    drainDeferredQueue();

    // Render ImGui draw data into the FBO.
    glBindFramebuffer(GL_FRAMEBUFFER, m_fbo);
    glViewport(0, 0, m_width, m_height);
    glClearColor(0.1f, 0.1f, 0.1f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
    glFlush();

    // Screenshot readback: drain any pending capture request into a PNG file.
    if (!m_pendingScreenshotPath.empty())
    {
        glBindFramebuffer(GL_FRAMEBUFFER, m_fbo);
        std::vector<uint8_t> pixels(m_width * m_height * 4);
        glReadPixels(0, 0, m_width, m_height, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
        if (glGetError() != GL_NO_ERROR)
        {
            fprintf(stderr, "HeadlessEglPlatform: glReadPixels failed for %s\n",
                    m_pendingScreenshotPath.c_str());
            m_screenshotError = true;
        }
        else
        {
            // Vertical flip: stb negative-stride trick (GL origin = bottom-left).
            const uint8_t* topRow = pixels.data() + (m_height - 1) * m_width * 4;
            int stride = -(m_width * 4);
            int ok = stbi_write_png(m_pendingScreenshotPath.c_str(),
                                    m_width, m_height, 4, topRow, stride);
            if (!ok)
            {
                fprintf(stderr, "HeadlessEglPlatform: stbi_write_png failed for %s\n",
                        m_pendingScreenshotPath.c_str());
                m_screenshotError = true;
            }
            else
            {
                fprintf(stdout, "HeadlessEglPlatform: screenshot saved to %s\n",
                        m_pendingScreenshotPath.c_str());
            }
        }
        m_pendingScreenshotPath.clear();
        m_screenshotDone = true;  // Always set — unblocks poll loops even on error.
    }

    return true;
}
bool HeadlessEglPlatform::shouldClose() { return false; }

// -- Busy state --------------------------------------------------------------

void HeadlessEglPlatform::setBusy(bool /*busy*/) {}

// -- Framebuffer access ------------------------------------------------------

uint64_t HeadlessEglPlatform::getFramebufferTexture(WindowId /*id*/) { return 0; }

// -- App window management ---------------------------------------------------

AppWindowHandle HeadlessEglPlatform::getDefaultAppWindowHandle() { return nullptr; }

AppWindowHandle HeadlessEglPlatform::createDetachedAppWindow(const char* /*title*/,
                                                              int /*x*/, int /*y*/,
                                                              int /*w*/, int /*h*/)
{
    return nullptr;
}

bool HeadlessEglPlatform::isMultiWindowSupported() { return false; }
bool HeadlessEglPlatform::isAppRunning()           { return true; }
bool HeadlessEglPlatform::isAppWindowVirtual(AppWindowHandle /*window*/) { return false; }

Int2 HeadlessEglPlatform::getAppWindowCursorPosition(AppWindowHandle /*window*/)
{
    return Int2{};
}

Int2 HeadlessEglPlatform::getAppWindowOsPosition(AppWindowHandle /*window*/)
{
    return Int2{};
}

void HeadlessEglPlatform::setAppWindowOsPosition(AppWindowHandle /*window*/,
                                                  int /*x*/, int /*y*/) {}

void HeadlessEglPlatform::resizeAppWindow(AppWindowHandle /*window*/,
                                          int /*w*/, int /*h*/) {}

void HeadlessEglPlatform::getAppWindowSize(AppWindowHandle /*window*/,
                                            int* width, int* height)
{
    if (width)  *width  = m_width;
    if (height) *height = m_height;
}

bool HeadlessEglPlatform::isMouseInputBlocked(AppWindowHandle /*window*/)     { return false; }
bool HeadlessEglPlatform::getAppWindowCursorBlink(AppWindowHandle /*window*/) { return false; }

DeferHandle HeadlessEglPlatform::deferDestroyAppWindow(AppWindowHandle /*window*/)
{
    return nullptr;
}

DeferHandle HeadlessEglPlatform::observeAppWindowClose(AppWindowHandle /*window*/,
                                                        std::function<void()> /*callback*/)
{
    return nullptr;
}

float HeadlessEglPlatform::getAppWindowDpiScale(AppWindowHandle /*window*/) { return 1.0f; }

// -- Window lifetime policy --------------------------------------------------

bool HeadlessEglPlatform::needsStrongWindowRefs() const { return false; }

} // namespace standalone
} // namespace ui
} // namespace omni

#endif // OMNIUI_HAS_EGL
