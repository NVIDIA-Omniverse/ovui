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

#include "StandaloneInit.h"

#include "GlfwPlatform.h"
#include "HeadlessVulkanPlatform.h"
#ifdef OMNIUI_HAS_VULKAN
#include "VulkanBackend.h"
#endif
#include "OpenGLByteImageGpu.h"
#include "OpenGLRenderer.h"
#include "StandaloneFileIO.h"
#include "StandaloneRasterImageLoader.h"
#include "StandaloneSettings.h"
#include "StandaloneLog.h"
#include "StandaloneWindowCallbackManager.h"
#include "ImGuiKeyTranslation.h"
#ifdef OMNIUI_HAS_VULKAN
#include "StreamingVulkan.h"
#endif
#ifdef OMNIUI_HAS_VULKAN
#include "VulkanByteImageGpu.h"
#endif
#if defined(OMNIUI_HAS_VULKAN) && defined(OMNIUI_HAS_CUDA)
#include "CudaVulkanInterop.h"
#endif
#ifdef OMNIUI_HAS_EGL
#include "HeadlessEglPlatform.h"
#endif

#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/Workspace.h>

#include <imgui/imgui.h>
#include <imgui/backends/imgui_impl_opengl3.h>

#ifndef OMNIUI_HEADLESS_ONLY
#include <glad/glad.h>
#include <GLFW/glfw3.h>
#endif

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include <stb_image_write.h>

#ifdef OMNIUI_HAS_CUDA
#include <cuda.h>
#include <cuda_runtime.h>
#include <cuda_gl_interop.h>
#endif

#include <cstdio>
#include <cstring>
#include <memory>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {

// Keep shared_ptrs alive so we can access the concrete types for tick/shouldClose.
static std::shared_ptr<IUiPlatform> s_platform;
static std::shared_ptr<GlfwPlatform> s_glfwPlatform; // Non-null only in non-headless mode
static std::shared_ptr<OpenGLRenderer> s_renderer;
static bool s_headlessMode = false;
static std::shared_ptr<StandaloneFileIO> s_fileIO;
static std::shared_ptr<StandaloneSettings> s_settings;
static std::shared_ptr<IByteImageGpu> s_byteImageGpu;
static std::shared_ptr<StandaloneRasterImageLoader> s_rasterImageLoader;
static std::shared_ptr<StandaloneLog> s_log;
static std::unique_ptr<StandaloneWindowCallbackManager> s_windowCallbackManager;

static bool isExplicitHeadlessMode()
{
    const char* headlessEnv = getenv("OMNIUI_HEADLESS");
    return headlessEnv && (strcmp(headlessEnv, "1") == 0 || strcmp(headlessEnv, "true") == 0);
}

static bool s_shutdownInProgress = false;

static void shutdownPlatformResources()
{
    shutdownVulkanStreaming();
    shutdownHeadlessFrameExport();

    // Release strong references to Windows before tearing down the WCM.
    // In standalone mode, Workspace::RegisterWindow keeps shared_ptrs to
    // prevent premature destruction when Python drops its reference.
    Workspace::clear();

    PlatformRegistry::instance().reset();
    s_platform.reset();
    s_glfwPlatform.reset();
    s_rasterImageLoader.reset();
    s_byteImageGpu.reset();
    s_renderer.reset();
    s_fileIO.reset();
    s_settings.reset();
    s_log.reset();
    setStandaloneWindowCallbackManager(nullptr);
    s_windowCallbackManager.reset();
    s_headlessMode = false;
}

// Scheduled screenshot: path set by scheduleScreenshot(), captured in tick() before swap.
static std::string s_pendingScreenshotPath;
static bool s_screenshotDone = false;

// Vulkan streaming pipeline
#ifdef OMNIUI_HAS_VULKAN
static std::unique_ptr<StreamingVulkan> s_streaming;
static uint64_t s_streamPts = 0;
static StreamNalCallback s_streamNalCallback = nullptr;
#endif

// Headless frame export pipeline (Vulkan offscreen image -> CUDA pitched-linear)
#if defined(OMNIUI_HAS_VULKAN) && defined(OMNIUI_HAS_CUDA)
static std::unique_ptr<CudaVulkanInterop> s_headlessFrameInterop;
#endif

bool init(const char* title, int width, int height)
{
    if (PlatformRegistry::instance().isInitialized())
    {
        fprintf(stderr, "standalone::init: already initialized\n");
        return false;
    }

    // Register log backend first so messages during init are captured.
    s_log = std::make_shared<StandaloneLog>();
    PlatformRegistry::instance().setLog(s_log);

    s_settings = std::make_shared<StandaloneSettings>();
    s_fileIO   = std::make_shared<StandaloneFileIO>();
    s_renderer = std::make_shared<OpenGLRenderer>();

    // Check for headless mode
    s_headlessMode = isExplicitHeadlessMode();

#ifdef OMNIUI_HAS_EGL
    bool useEglHeadless = false;
    {
        const char* headlessGl = getenv("OMNIUI_HEADLESS_GL");
        useEglHeadless = s_headlessMode && headlessGl &&
                         (strcmp(headlessGl, "1") == 0 || strcmp(headlessGl, "true") == 0);
    }
    if (useEglHeadless)
    {
        fprintf(stdout, "standalone::init: EGL headless GL mode enabled\n");
        s_platform = std::make_shared<HeadlessEglPlatform>();
        s_glfwPlatform = nullptr;
    }
    else
#endif
#ifdef OMNIUI_HAS_VULKAN
    if (s_headlessMode)
    {
        fprintf(stdout, "standalone::init: headless Vulkan mode enabled\n");
        auto headlessPlatform = std::make_shared<HeadlessVulkanPlatform>();
        s_platform = headlessPlatform;
        s_glfwPlatform = nullptr;
#ifndef _WIN32
        {
            const char* lavapipe = getenv("OMNIUI_LAVAPIPE");
            if (lavapipe && (strcmp(lavapipe, "1") == 0 || strcmp(lavapipe, "true") == 0))
            {
                if (getenv("VK_DRIVER_FILES"))
                {
                    fprintf(stdout,
                            "standalone::init: OMNIUI_LAVAPIPE=1 set but VK_DRIVER_FILES"
                            " already set — using as-is\n");
                }
                else
                {
                    // Helper: check file existence without requiring <unistd.h>
                    auto fileExists = [](const char* path) -> bool {
                        FILE* f = fopen(path, "r");
                        if (f) { fclose(f); return true; }
                        return false;
                    };

                    const char* icdPath = getenv("OMNIUI_LAVAPIPE_ICD_PATH");
                    if (icdPath)
                    {
                        if (!fileExists(icdPath))
                        {
                            fprintf(stderr,
                                    "standalone::init: OMNIUI_LAVAPIPE_ICD_PATH=%s: file not found\n",
                                    icdPath);
                            s_platform.reset();
                            s_renderer.reset();
                            s_fileIO.reset();
                            s_settings.reset();
                            return false;
                        }
                        setenv("VK_DRIVER_FILES", icdPath, 1);
                        fprintf(stdout, "standalone::init: injecting VK_DRIVER_FILES=%s\n", icdPath);
                    }
                    else
                    {
                        static const char* const kIcdPaths[] = {
                            "/usr/share/vulkan/icd.d/lvp_icd.x86_64.json",
                            "/usr/share/vulkan/icd.d/lvp_icd.aarch64.json",
                            "/usr/share/vulkan/icd.d/lvp_icd.json",
                            nullptr
                        };
                        const char* foundPath = nullptr;
                        for (const char* const* p = kIcdPaths; *p; ++p)
                        {
                            if (fileExists(*p)) { foundPath = *p; break; }
                        }
                        if (!foundPath)
                        {
                            fprintf(stderr,
                                    "standalone::init: OMNIUI_LAVAPIPE=1 but no Lavapipe ICD found at:\n"
                                    "  /usr/share/vulkan/icd.d/lvp_icd.x86_64.json\n"
                                    "  /usr/share/vulkan/icd.d/lvp_icd.aarch64.json\n"
                                    "  /usr/share/vulkan/icd.d/lvp_icd.json\n"
                                    "  Set OMNIUI_LAVAPIPE_ICD_PATH to specify the path.\n");
                            s_platform.reset();
                            s_renderer.reset();
                            s_fileIO.reset();
                            s_settings.reset();
                            return false;
                        }
                        setenv("VK_DRIVER_FILES", foundPath, 1);
                        fprintf(stdout, "standalone::init: injecting VK_DRIVER_FILES=%s\n", foundPath);
                    }
                }
            }
        }
#endif
    }
    else
#endif
    {
        if (s_headlessMode)
        {
            fprintf(stderr, "standalone::init: headless mode requires Vulkan support (OMNIUI_HAS_VULKAN)\n");
            return false;
        }
        s_glfwPlatform = std::make_shared<GlfwPlatform>();
        s_platform = s_glfwPlatform;
    }

    // Create the window (this also initializes the graphics backend and ImGui)
    WindowId wid = s_platform->createWindow(title, width, height);
    if (wid == kInvalidWindowId)
    {
        fprintf(stderr, "standalone::init: failed to create window\n");
        s_platform.reset();
        s_glfwPlatform.reset();
        s_renderer.reset();
        s_fileIO.reset();
        s_settings.reset();
        return false;
    }

    // Create the byte image GPU backend. Which one depends on the active
    // rendering backend — OpenGL texture for GL, Vulkan VkImage for Vulkan
    // (both headless and GLFW+Vulkan).
#ifdef OMNIUI_HAS_EGL
    if (useEglHeadless)
    {
        s_byteImageGpu = std::make_shared<OpenGLByteImageGpu>();
    }
    else
#endif
#ifdef OMNIUI_HAS_VULKAN
    if (s_headlessMode)
    {
        auto* hp = dynamic_cast<HeadlessVulkanPlatform*>(s_platform.get());
        if (hp && hp->getVulkanBackend())
            s_byteImageGpu = std::make_shared<VulkanByteImageGpu>(hp->getVulkanBackend());
    }
    else if (s_glfwPlatform && s_glfwPlatform->getBackendType() == BackendType::eVulkan)
    {
        s_byteImageGpu = std::make_shared<VulkanByteImageGpu>(s_glfwPlatform->getVulkanBackend());
    }
    else
#endif
    if (!s_headlessMode)
    {
        s_byteImageGpu = std::make_shared<OpenGLByteImageGpu>();
    }

    // Create the window callback manager (must be before any Window objects are created)
    s_windowCallbackManager = std::make_unique<StandaloneWindowCallbackManager>();
    setStandaloneWindowCallbackManager(s_windowCallbackManager.get());

    // Register with the global registry
    auto& reg = PlatformRegistry::instance();
    reg.setSettings(s_settings);
    reg.setFileIO(s_fileIO);
    reg.setRenderer(s_renderer);
    reg.setPlatform(s_platform);
    if (s_byteImageGpu)
        reg.setByteImageGpu(s_byteImageGpu);

    // Register the raster image loader (stb_image + registered IByteImageGpu).
    // Depends on IByteImageGpu; only register when byteImageGpu is available.
    if (s_byteImageGpu)
    {
        s_rasterImageLoader = std::make_shared<StandaloneRasterImageLoader>();
        reg.setRasterImageLoader(s_rasterImageLoader);
    }

    fprintf(stdout, "standalone::init: initialized successfully (%dx%d)\n", width, height);

    // Auto-init Vulkan streaming if OMNIUI_STREAM_BACKEND=vulkan is set
    const char* streamBackend = getenv("OMNIUI_STREAM_BACKEND");
    if (streamBackend && strcmp(streamBackend, "vulkan") == 0)
    {
#ifdef OMNIUI_HAS_VULKAN
        if (s_glfwPlatform && s_glfwPlatform->getBackendType() == BackendType::eVulkan)
        {
            fprintf(stdout, "standalone::init: OMNIUI_STREAM_BACKEND=vulkan — auto-initializing streaming\n");
            initVulkanStreaming();
        }
        else
        {
            fprintf(stderr, "standalone::init: OMNIUI_STREAM_BACKEND=vulkan requested but backend is OpenGL or headless\n");
        }
#else
        fprintf(stderr, "standalone::init: OMNIUI_STREAM_BACKEND=vulkan requested but Vulkan not compiled in\n");
#endif
    }

    return true;
}

bool tick()
{
    if (!s_platform)
        return false;
    return s_platform->tick();
}

bool setWindowSize(int width, int height)
{
#ifndef OMNIUI_HEADLESS_ONLY
    if (!s_glfwPlatform || width <= 0 || height <= 0)
        return false;

    GLFWwindow* win = s_glfwPlatform->getGlfwWindow();
    if (!win)
        return false;

    // Ask the window system to resize the OS window. On an Xvnc / headless
    // display this is synchronous; on a real window manager the size change
    // arrives via a ConfigureNotify during the next glfwPollEvents().
    glfwSetWindowSize(win, width, height);

    // Pump the event queue so GLFW's cached framebuffer size updates before
    // any subsequent glfwGetFramebufferSize()/tick() call.
    glfwPollEvents();

    // Verify the size took effect; some window managers clamp to screen size
    // or silently refuse. We report true if we got what we asked for.
    int fbw = 0, fbh = 0;
    glfwGetFramebufferSize(win, &fbw, &fbh);
    return fbw == width && fbh == height;
#else
    (void)width;
    (void)height;
    return false;
#endif
}

bool getWindowSize(int* width, int* height)
{
#ifndef OMNIUI_HEADLESS_ONLY
    if (!s_glfwPlatform)
        return false;
    GLFWwindow* win = s_glfwPlatform->getGlfwWindow();
    if (!win)
        return false;
    int fbw = 0, fbh = 0;
    glfwGetFramebufferSize(win, &fbw, &fbh);
    if (width) *width = fbw;
    if (height) *height = fbh;
    return true;
#else
    (void)width;
    (void)height;
    return false;
#endif
}

bool shouldClose()
{
    if (!s_platform)
        return true;
    return s_platform->shouldClose();
}

void shutdown()
{
    s_shutdownInProgress = true;

    // Shut down streaming pipelines before tearing down the platform
    shutdownStreaming();
    shutdownPlatformResources();

    s_shutdownInProgress = false;
}

// ---------------------------------------------------------------------------
// Input injection -- buffered state
// ---------------------------------------------------------------------------

// We buffer injected input so it can be re-applied *after*
// ImGui_ImplGlfw_NewFrame() which would otherwise overwrite our values
// with the real GLFW cursor position.

static struct InjectedInputState
{
    bool hasMousePos = false;
    float mouseX = 0.0f;
    float mouseY = 0.0f;

    bool hasMouseButton[5] = {};
    bool mouseDown[5] = {};

    float scrollDx = 0.0f;
    float scrollDy = 0.0f;
    bool hasScroll = false;

    // Key state is additive per-frame
    struct KeyEvent { int key; bool pressed; };
    std::vector<KeyEvent> keyEvents;

    // Character input is additive per-frame
    std::vector<unsigned int> charEvents;
    std::string textInput;
} s_injected;

void injectMouseMove(float x, float y)
{
    s_injected.hasMousePos = true;
    s_injected.mouseX = x;
    s_injected.mouseY = y;
}

void injectMouseButton(int button, bool pressed)
{
    if (button < 0 || button >= 5)
        return;
    s_injected.hasMouseButton[button] = true;
    s_injected.mouseDown[button] = pressed;
}

void injectMouseScroll(float dx, float dy)
{
    s_injected.hasScroll = true;
    s_injected.scrollDx += dx;
    s_injected.scrollDy += dy;
}

void injectKeyEvent(int key, bool pressed)
{
    s_injected.keyEvents.push_back({key, pressed});
}

void injectCharEvent(unsigned int ch)
{
    s_injected.charEvents.push_back(ch);
}

void injectTextInput(const char* text)
{
    if (text)
        s_injected.textInput += text;
}

void applyInjectedInput()
{
    ImGuiIO& io = ImGui::GetIO();

    // Use the queued event API (AddMouse*Event) so injected input follows
    // the same pipeline as real GLFW events. Direct writes to io.MousePos /
    // io.MouseDown[] are the deprecated path and do not update
    // io.MouseDownDuration, which causes IsMouseClicked()/IsMouseReleased()
    // to behave differently from the real-input path.
    if (s_injected.hasMousePos)
    {
        // Re-queue each frame: in headless mode ImGui_ImplGlfw_NewFrame()
        // polls glfwGetCursorPos() as a fallback and would otherwise snap
        // the cursor back to (0, 0). Queuing our position last ensures it
        // wins when ImGui::NewFrame() drains the event queue.
        io.AddMousePosEvent(s_injected.mouseX, s_injected.mouseY);
    }

    for (int i = 0; i < 5; ++i)
    {
        if (s_injected.hasMouseButton[i])
        {
            io.AddMouseButtonEvent(i, s_injected.mouseDown[i]);
            s_injected.hasMouseButton[i] = false;
        }
    }

    if (s_injected.hasScroll)
    {
        io.AddMouseWheelEvent(s_injected.scrollDx, s_injected.scrollDy);
        s_injected.scrollDx = 0.0f;
        s_injected.scrollDy = 0.0f;
        s_injected.hasScroll = false;
    }

    for (auto& ev : s_injected.keyEvents)
    {
        const ImGuiKey key = detail::normalizeInjectedImguiKey(ev.key);
        if (key != ImGuiKey_None)
            io.AddKeyEvent(key, ev.pressed);
    }
    s_injected.keyEvents.clear();

    for (unsigned int ch : s_injected.charEvents)
    {
        io.AddInputCharacter(ch);
    }
    s_injected.charEvents.clear();

    if (!s_injected.textInput.empty())
    {
        io.AddInputCharactersUTF8(s_injected.textInput.c_str());
        s_injected.textInput.clear();
    }
}

// ---------------------------------------------------------------------------
// Software cursor toggle
// ---------------------------------------------------------------------------

void setSoftwareCursor(bool enabled)
{
    if (!ImGui::GetCurrentContext())
        return;
    ImGui::GetIO().MouseDrawCursor = enabled;
}

bool isSoftwareCursorEnabled()
{
    if (!ImGui::GetCurrentContext())
        return false;
    return ImGui::GetIO().MouseDrawCursor;
}

// ---------------------------------------------------------------------------
// Screenshot capture
// ---------------------------------------------------------------------------

// Internal: save pixels to file
static bool savePixelsToFile(const char* filepath, const std::vector<unsigned char>& pixels, int width, int height)
{
    // OpenGL reads bottom-to-top; flip vertically for image formats
    int rowBytes = width * 4;
    // Work on a copy to avoid mutating the input
    std::vector<unsigned char> flipped(pixels);
    std::vector<unsigned char> rowBuf(rowBytes);
    for (int y = 0; y < height / 2; ++y)
    {
        unsigned char* top = flipped.data() + y * rowBytes;
        unsigned char* bot = flipped.data() + (height - 1 - y) * rowBytes;
        std::memcpy(rowBuf.data(), top, rowBytes);
        std::memcpy(top, bot, rowBytes);
        std::memcpy(bot, rowBuf.data(), rowBytes);
    }

    const char* ext = strrchr(filepath, '.');
    int result = 0;
    if (ext && (strcmp(ext, ".jpg") == 0 || strcmp(ext, ".jpeg") == 0))
    {
        result = stbi_write_jpg(filepath, width, height, 4, flipped.data(), 95);
    }
    else if (ext && strcmp(ext, ".bmp") == 0)
    {
        result = stbi_write_bmp(filepath, width, height, 4, flipped.data());
    }
    else
    {
        result = stbi_write_png(filepath, width, height, 4, flipped.data(), rowBytes);
    }

    if (!result)
    {
        fprintf(stderr, "captureScreenshot: failed to write %s\n", filepath);
        return false;
    }

    fprintf(stdout, "captureScreenshot: saved %s (%dx%d)\n", filepath, width, height);
    return true;
}

/// Helper: capture Vulkan framebuffer to file (no flip needed — Vulkan is top-down)
#ifdef OMNIUI_HAS_VULKAN
static void captureVulkanScreenshot(VulkanBackend* vkBackend, const std::string& path)
{
    if (!vkBackend) return;
    int width = 0, height = 0;
    vkBackend->getFramebufferSize(&width, &height);
    if (width <= 0 || height <= 0) return;

    std::vector<unsigned char> pixels(width * height * 4);
    if (vkBackend->readbackPixels(pixels.data(), width, height))
    {
        const char* ext = strrchr(path.c_str(), '.');
        int result = 0;
        int rowBytes = width * 4;
        if (ext && (strcmp(ext, ".jpg") == 0 || strcmp(ext, ".jpeg") == 0))
            result = stbi_write_jpg(path.c_str(), width, height, 4, pixels.data(), 95);
        else if (ext && strcmp(ext, ".bmp") == 0)
            result = stbi_write_bmp(path.c_str(), width, height, 4, pixels.data());
        else
            result = stbi_write_png(path.c_str(), width, height, 4, pixels.data(), rowBytes);
        if (result)
            fprintf(stdout, "captureScreenshot(VK): saved %s (%dx%d)\n", path.c_str(), width, height);
        else
            fprintf(stderr, "captureScreenshot(VK): failed to write %s\n", path.c_str());
    }
    s_screenshotDone = true;
}
#endif // OMNIUI_HAS_VULKAN

bool scheduleScreenshot(const char* filepath)
{
    if (!s_platform || !filepath)
        return false;
    s_pendingScreenshotPath = filepath;
    s_screenshotDone = false;

    std::string pathCopy = filepath;

#ifdef OMNIUI_HAS_EGL
    if (auto* ep = dynamic_cast<HeadlessEglPlatform*>(s_platform.get()))
    {
        ep->captureScreenshot(pathCopy);
        return true;
    }
#endif

#ifdef OMNIUI_HAS_VULKAN
    // Headless platform path
    if (s_headlessMode)
    {
        auto* headless = dynamic_cast<HeadlessVulkanPlatform*>(s_platform.get());
        if (headless)
        {
            headless->setPreSwapCallback([pathCopy]() {
                auto* hp = dynamic_cast<HeadlessVulkanPlatform*>(s_platform.get());
                if (hp)
                    captureVulkanScreenshot(hp->getVulkanBackend(), pathCopy);
            });
        }
        return true;
    }
#endif

    // GLFW platform path
    if (!s_glfwPlatform)
        return false;

    s_glfwPlatform->setPreSwapCallback([pathCopy]() {
#ifdef OMNIUI_HAS_VULKAN
        if (s_glfwPlatform && s_glfwPlatform->getBackendType() == BackendType::eVulkan)
        {
            captureVulkanScreenshot(s_glfwPlatform->getVulkanBackend(), pathCopy);
            return;
        }
#endif
#ifndef OMNIUI_HEADLESS_ONLY
        // OpenGL path: Use the GL viewport dimensions for glReadPixels so that on
        // HiDPI / Retina displays (where the GL framebuffer is larger than the
        // logical window size) we capture the full rendered image rather than just
        // the bottom-left quadrant.
        GLint viewport[4] = {};
        glGetIntegerv(GL_VIEWPORT, viewport);
        int width  = viewport[2];
        int height = viewport[3];
        if (width <= 0 || height <= 0)
        {
            // Fallback to logical window size (non-HiDPI platforms)
            if (s_glfwPlatform)
                s_glfwPlatform->getWindowSize(1, &width, &height);
        }
        if (width <= 0 || height <= 0)
            return;

        std::vector<unsigned char> pixels(width * height * 4);
        glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
        savePixelsToFile(pathCopy.c_str(), pixels, width, height);
        s_screenshotDone = true;
#endif
    });

    return true;
}

bool pollScreenshotDone()
{
#ifdef OMNIUI_HAS_EGL
    if (auto* ep = dynamic_cast<HeadlessEglPlatform*>(s_platform.get()))
        return ep->isScreenshotDone();
#endif
    bool done = s_screenshotDone;
    s_screenshotDone = false;
    s_pendingScreenshotPath.clear();
    return done;
}

bool hadLastScreenshotError()
{
#ifdef OMNIUI_HAS_EGL
    if (auto* ep = dynamic_cast<HeadlessEglPlatform*>(s_platform.get()))
        return ep->hadScreenshotError();
#endif
    return false;
}

bool captureScreenshot(const char* filepath)
{
    if (!s_platform || !filepath)
        return false;

    // Use the pre-swap callback mechanism to capture BEFORE glfwSwapBuffers.
    // Reading the framebuffer after swap returns only the clear color because
    // the back buffer has been swapped away. scheduleScreenshot() already does
    // this correctly; delegate to it and spin until the capture completes.
    if (!scheduleScreenshot(filepath))
        return false;

    // The screenshot will be captured during the next tick()'s pre-swap phase.
    // If the caller is synchronous (e.g., Python test code), we need at least
    // one tick to execute. Return true to indicate the capture was scheduled.
    // The caller should use pollScreenshotDone() or wait_frames() to confirm.
    return true;
}

// ===========================================================================
// Streaming (FBO rendering + CUDA-GL interop)
// ===========================================================================
//
// Architecture note (PBO alternative — see critique Item 3):
//   An alternative pipeline uses a PBO: render to FBO → glReadPixels into PBO
//   → cudaGraphicsGLRegisterBuffer → linear device pointer directly. This
//   eliminates the tiled→linear cudaMemcpy2DFromArray because PBO memory is
//   linear. However, glReadPixels into a PBO can stall the GL pipeline, while
//   the current cudaMemcpy2DFromArray is fully asynchronous on the GPU. The
//   current approach is preferred for latency unless profiling shows the
//   tiled-to-linear conversion is a bottleneck.
//
// TODO(V2): EGL + NVENC direct GL input (critique Item 10).
//   On Linux with an EGL context (not GLX), NVENC ≥9.1 supports
//   NV_ENC_INPUT_RESOURCE_OPENGL, which accepts an EGLImage directly. This
//   would eliminate the entire CUDA interop layer (no register, no map/unmap,
//   no cudaMemcpy2DFromArray, no cudaMallocPitch). Pipeline becomes: render to
//   FBO texture → hand texture to NVENC as EGLImage. Zero copies.
//   Requirements: EGL context (GLFW_CONTEXT_CREATION_API = EGL), NVENC ≥9.1,
//   NVIDIA GPU with EGLStream support. Keep the CUDA path as a fallback.

static WindowId s_streamingWindowId = kInvalidWindowId;
static bool s_streamingInitialized = false;
static bool s_streamingOwnsPlatform = false;

#ifdef OMNIUI_HAS_CUDA
static cudaGraphicsResource_t s_cudaGlResource = nullptr;
static void* s_cudaLinearPtr = nullptr;     // Linear CUDA buffer for NVENC
static size_t s_cudaLinearPitch = 0;
static int s_cudaStreamWidth = 0;
static int s_cudaStreamHeight = 0;
static cudaEvent_t s_cudaFrameEvent = nullptr; // Signaled after each tiled→linear copy

static bool setupCudaInterop(unsigned int glTexture, int width, int height)
{
    cudaError_t err;

    // Register the GL texture with CUDA
    err = cudaGraphicsGLRegisterImage(
        &s_cudaGlResource, glTexture, GL_TEXTURE_2D,
        cudaGraphicsRegisterFlagsReadOnly);
    if (err != cudaSuccess)
    {
        fprintf(stderr, "streaming: cudaGraphicsGLRegisterImage failed: %s\n",
                cudaGetErrorString(err));
        s_cudaGlResource = nullptr;
        return false;
    }

    // Allocate a linear CUDA buffer for the tiled→linear copy.
    // NVENC requires a linear (pitched) buffer, not a cudaArray.
    err = cudaMallocPitch(&s_cudaLinearPtr, &s_cudaLinearPitch,
                          static_cast<size_t>(width) * 4, static_cast<size_t>(height));
    if (err != cudaSuccess)
    {
        fprintf(stderr, "streaming: cudaMallocPitch failed: %s\n",
                cudaGetErrorString(err));
        cudaGraphicsUnregisterResource(s_cudaGlResource);
        s_cudaGlResource = nullptr;
        s_cudaLinearPtr = nullptr;
        return false;
    }

    s_cudaStreamWidth = width;
    s_cudaStreamHeight = height;

    // Create a CUDA event for frame-ready synchronization (Item 5: thread safety).
    // NVENC or other consumers on a separate thread should wait on this event
    // (via streamingSync() or getStreamingCudaEvent()) before reading the buffer.
    err = cudaEventCreateWithFlags(&s_cudaFrameEvent, cudaEventDisableTiming);
    if (err != cudaSuccess)
    {
        fprintf(stderr, "streaming: cudaEventCreate failed: %s (continuing without sync)\n",
                cudaGetErrorString(err));
        s_cudaFrameEvent = nullptr;
    }

    fprintf(stdout, "streaming: CUDA-GL interop initialized (%dx%d, pitch=%zu)\n",
            width, height, s_cudaLinearPitch);
    return true;
}

static void teardownCudaInterop()
{
    // If an NVENC thread might be reading, callers MUST ensure it has finished
    // before calling this function (Item 9b: use-after-free on resize).
    if (s_cudaFrameEvent)
    {
        // Wait for any in-flight copy to complete before freeing resources.
        cudaEventSynchronize(s_cudaFrameEvent);
        cudaEventDestroy(s_cudaFrameEvent);
        s_cudaFrameEvent = nullptr;
    }
    if (s_cudaLinearPtr)
    {
        cudaFree(s_cudaLinearPtr);
        s_cudaLinearPtr = nullptr;
        s_cudaLinearPitch = 0;
    }
    if (s_cudaGlResource)
    {
        cudaGraphicsUnregisterResource(s_cudaGlResource);
        s_cudaGlResource = nullptr;
    }
    s_cudaStreamWidth = 0;
    s_cudaStreamHeight = 0;
}

/// Map the GL texture into CUDA and copy from tiled cudaArray → linear buffer.
/// Call this after each frame render (FBO is unbound, texture contents are final).
static bool updateCudaLinearBuffer()
{
    if (!s_cudaGlResource || !s_cudaLinearPtr)
        return false;

    cudaError_t err;

    // Map the GL resource for CUDA access
    err = cudaGraphicsMapResources(1, &s_cudaGlResource, 0);
    if (err != cudaSuccess)
    {
        fprintf(stderr, "streaming: cudaGraphicsMapResources failed: %s\n",
                cudaGetErrorString(err));
        return false;
    }

    // Get the mapped cudaArray (tiled texture memory)
    cudaArray_t texArray = nullptr;
    err = cudaGraphicsSubResourceGetMappedArray(&texArray, s_cudaGlResource, 0, 0);
    if (err != cudaSuccess)
    {
        fprintf(stderr, "streaming: cudaGraphicsSubResourceGetMappedArray failed: %s\n",
                cudaGetErrorString(err));
        cudaGraphicsUnmapResources(1, &s_cudaGlResource, 0);
        return false;
    }

    // Copy tiled → linear (one D→D copy, unavoidable for NVENC)
    err = cudaMemcpy2DFromArray(
        s_cudaLinearPtr, s_cudaLinearPitch,
        texArray,
        0, 0,                                                     // src offset
        static_cast<size_t>(s_cudaStreamWidth) * 4,               // width in bytes
        static_cast<size_t>(s_cudaStreamHeight),                  // height in rows
        cudaMemcpyDeviceToDevice);
    if (err != cudaSuccess)
    {
        fprintf(stderr, "streaming: cudaMemcpy2DFromArray failed: %s\n",
                cudaGetErrorString(err));
        cudaGraphicsUnmapResources(1, &s_cudaGlResource, 0);
        return false;
    }

    // Unmap so GL can use the texture again next frame
    err = cudaGraphicsUnmapResources(1, &s_cudaGlResource, 0);
    if (err != cudaSuccess)
    {
        fprintf(stderr, "streaming: cudaGraphicsUnmapResources failed: %s\n",
                cudaGetErrorString(err));
        return false;
    }

    // Record a CUDA event so consumers (e.g., NVENC on another thread) can
    // synchronize on the copy completing before reading the linear buffer.
    // This is GPU-side only — zero CPU overhead. (Item 5: thread safety)
    if (s_cudaFrameEvent)
    {
        cudaEventRecord(s_cudaFrameEvent, 0);
    }

    return true;
}

#endif // OMNIUI_HAS_CUDA

bool initStreaming(int width, int height)
{
    bool initializedPlatformForStreaming = false;

    if (s_streamingInitialized)
    {
        fprintf(stderr, "streaming: already initialized\n");
        return false;
    }

    // Initialize the platform with a hidden GLFW window (needed for GL context).
    // Use glfwWindowHint(GLFW_VISIBLE, GLFW_FALSE) by calling init() then hiding.
    // Actually, init() creates and shows a window. We init normally, then the
    // render target redirect means nothing goes to the screen.
    if (!s_glfwPlatform && !PlatformRegistry::instance().isInitialized())
    {
        if (isExplicitHeadlessMode())
        {
            fprintf(stderr, "streaming: requires GLFW platform (not available in headless mode)\n");
            return false;
        }

        if (!init("ovls-streaming", width, height))
        {
            fprintf(stderr, "streaming: init() failed\n");
            return false;
        }
        initializedPlatformForStreaming = true;

        // Hide the GLFW window — we're headless.
        if (s_glfwPlatform && s_glfwPlatform->getGlfwWindow())
            glfwHideWindow(s_glfwPlatform->getGlfwWindow());
    }

    if (!s_glfwPlatform)
    {
        fprintf(stderr, "streaming: requires GLFW platform (not available in headless mode)\n");
        return false;
    }

    // Create FBO-backed virtual window
    s_streamingWindowId = s_glfwPlatform->createVirtualWindow(width, height);
    if (s_streamingWindowId == kInvalidWindowId)
    {
        fprintf(stderr, "streaming: createVirtualWindow(%d, %d) failed\n", width, height);
        if (initializedPlatformForStreaming)
            shutdownPlatformResources();
        return false;
    }

    // Set the virtual window as the render target
    s_glfwPlatform->setRenderTarget(s_streamingWindowId);

#ifdef OMNIUI_HAS_CUDA
    {
        unsigned int glTex = static_cast<unsigned int>(
            s_glfwPlatform->getFramebufferTexture(s_streamingWindowId));
        if (glTex == 0)
        {
            fprintf(stderr, "streaming: getFramebufferTexture returned 0\n");
        }
        else if (!setupCudaInterop(glTex, width, height))
        {
            fprintf(stderr, "streaming: CUDA-GL interop setup failed (continuing without CUDA)\n");
        }
    }
#endif

    s_streamingInitialized = true;
    s_streamingOwnsPlatform = initializedPlatformForStreaming;
    fprintf(stdout, "streaming: initialized %dx%d (windowId=%u)\n",
            width, height, s_streamingWindowId);
    return true;
}

void shutdownStreaming()
{
    if (!s_streamingInitialized)
        return;

#ifdef OMNIUI_HAS_CUDA
    teardownCudaInterop();
#endif

    if (s_glfwPlatform && s_streamingWindowId != kInvalidWindowId)
    {
        s_glfwPlatform->setRenderTarget(kInvalidWindowId);
        s_glfwPlatform->destroyVirtualWindow(s_streamingWindowId);
        s_streamingWindowId = kInvalidWindowId;
    }

    s_streamingInitialized = false;

    if (s_streamingOwnsPlatform)
    {
        s_streamingOwnsPlatform = false;
        if (!s_shutdownInProgress)
            shutdownPlatformResources();
    }
    // Note: if standalone was initialized before streaming, the caller owns
    // the platform lifetime.
}

bool streamingTick()
{
    if (!s_streamingInitialized || !s_platform)
        return false;

    bool result = s_platform->tick();

#ifdef OMNIUI_HAS_CUDA
    // After tick() unbinds the FBO, the texture is ready. Copy to linear CUDA buffer.
    updateCudaLinearBuffer();
#endif

    return result;
}

unsigned int getStreamingGLTexture()
{
    if (!s_streamingInitialized || !s_glfwPlatform)
        return 0;
    return static_cast<unsigned int>(
        s_glfwPlatform->getFramebufferTexture(s_streamingWindowId));
}

int getStreamingWidth()
{
    if (!s_streamingInitialized || !s_glfwPlatform)
        return 0;
    int w = 0, h = 0;
    s_glfwPlatform->getWindowSize(s_streamingWindowId, &w, &h);
    return w;
}

int getStreamingHeight()
{
    if (!s_streamingInitialized || !s_glfwPlatform)
        return 0;
    int w = 0, h = 0;
    s_glfwPlatform->getWindowSize(s_streamingWindowId, &w, &h);
    return h;
}

uintptr_t getStreamingCudaPtr()
{
#ifdef OMNIUI_HAS_CUDA
    return reinterpret_cast<uintptr_t>(s_cudaLinearPtr);
#else
    return 0;
#endif
}

size_t getStreamingCudaPitch()
{
#ifdef OMNIUI_HAS_CUDA
    return s_cudaLinearPitch;
#else
    return 0;
#endif
}

const char* getStreamingFormat()
{
    // Currently the only supported format. Provided for future format
    // negotiation (e.g., NV12 for direct NVENC consumption).
    return "rgba8";
}

bool isStreamingCudaAvailable()
{
#ifdef OMNIUI_HAS_CUDA
    return s_streamingInitialized && s_cudaLinearPtr != nullptr;
#else
    return false;
#endif
}

void streamingSync()
{
#ifdef OMNIUI_HAS_CUDA
    if (s_cudaFrameEvent)
    {
        cudaEventSynchronize(s_cudaFrameEvent);
    }
#endif
}

uintptr_t getStreamingCudaEvent()
{
#ifdef OMNIUI_HAS_CUDA
    return reinterpret_cast<uintptr_t>(s_cudaFrameEvent);
#else
    return 0;
#endif
}

bool resizeStreaming(int width, int height)
{
    if (!s_streamingInitialized || !s_glfwPlatform)
        return false;
    if (width <= 0 || height <= 0)
        return false;

#ifdef OMNIUI_HAS_CUDA
    teardownCudaInterop();
#endif

    s_glfwPlatform->resizeVirtualWindow(s_streamingWindowId, width, height);

    // Verify the resize worked
    int actualW = 0, actualH = 0;
    s_glfwPlatform->getWindowSize(s_streamingWindowId, &actualW, &actualH);
    if (actualW != width || actualH != height)
    {
        fprintf(stderr, "streaming: resize to %dx%d failed\n", width, height);
#ifdef OMNIUI_HAS_CUDA
        // Restore CUDA interop on the old (unchanged) texture
        {
            unsigned int oldTex = static_cast<unsigned int>(
                s_glfwPlatform->getFramebufferTexture(s_streamingWindowId));
            if (oldTex != 0)
                setupCudaInterop(oldTex, actualW, actualH);
        }
#endif
        return false;
    }

#ifdef OMNIUI_HAS_CUDA
    {
        unsigned int glTex = static_cast<unsigned int>(
            s_glfwPlatform->getFramebufferTexture(s_streamingWindowId));
        if (glTex != 0)
        {
            if (!setupCudaInterop(glTex, width, height))
            {
                fprintf(stderr, "streaming: CUDA re-setup after resize failed\n");
            }
        }
    }
#endif

    fprintf(stdout, "streaming: resized to %dx%d\n", width, height);
    return true;
}

// ---------------------------------------------------------------------------
// Vulkan streaming pipeline (VkImage → NVENC/CPU → NAL units)
// ---------------------------------------------------------------------------

bool initVulkanStreaming(int fps, int bitrateMbps)
{
#ifdef OMNIUI_HAS_VULKAN
    if (!s_glfwPlatform)
    {
        fprintf(stderr, "initVulkanStreaming: GLFW platform required (not available in headless mode)\n");
        return false;
    }
    if (s_glfwPlatform->getBackendType() != BackendType::eVulkan)
    {
        fprintf(stderr, "initVulkanStreaming: Vulkan backend required (set OMNIUI_BACKEND=vulkan)\n");
        return false;
    }

    VulkanBackend* vkBackend = s_glfwPlatform->getVulkanBackend();
    if (!vkBackend || !vkBackend->isInitialized())
    {
        fprintf(stderr, "initVulkanStreaming: VulkanBackend not ready\n");
        return false;
    }

    if (s_streaming && s_streaming->isInitialized())
    {
        fprintf(stderr, "initVulkanStreaming: already active\n");
        return false;
    }

    s_streaming = std::make_unique<StreamingVulkan>();

    StreamingConfig config;
    vkBackend->getFramebufferSize(&config.width, &config.height);
    config.fps         = fps;
    config.bitrateMbps = bitrateMbps;

    if (!s_streaming->init(vkBackend, config))
    {
        s_streaming.reset();
        return false;
    }

    s_streamPts = 0;
    return true;
#else
    (void)fps;
    (void)bitrateMbps;
    fprintf(stderr, "initVulkanStreaming: Vulkan not compiled in\n");
    return false;
#endif
}

void shutdownVulkanStreaming()
{
#ifdef OMNIUI_HAS_VULKAN
    if (s_streaming)
    {
        s_streaming->shutdown();
        s_streaming.reset();
    }
    s_streamPts = 0;
    s_streamNalCallback = nullptr;
#endif
}

bool encodeStreamFrame()
{
#ifdef OMNIUI_HAS_VULKAN
    if (!s_streaming || !s_streaming->isInitialized())
        return false;

    NalCallback cb = nullptr;
    if (s_streamNalCallback)
    {
        auto rawCb = s_streamNalCallback;
        cb = [rawCb](const uint8_t* data, uint32_t size, uint64_t pts) {
            rawCb(data, size, pts);
        };
    }

    bool ok = s_streaming->encodeFrame(s_streamPts++, cb);
    return ok;
#else
    return false;
#endif
}

bool isStreamingActive()
{
#ifdef OMNIUI_HAS_VULKAN
    return s_streaming && s_streaming->isInitialized();
#else
    return false;
#endif
}

const char* getStreamEncoderName()
{
#ifdef OMNIUI_HAS_VULKAN
    if (s_streaming && s_streaming->isInitialized())
        return s_streaming->getEncoderName();
#endif
    return "none";
}

void setStreamNalCallback(StreamNalCallback callback)
{
#ifdef OMNIUI_HAS_VULKAN
    s_streamNalCallback = callback;
#else
    (void)callback;
#endif
}

// ---------------------------------------------------------------------------
// Headless frame export (issue-34 Step 2.1)
// ---------------------------------------------------------------------------

#if defined(OMNIUI_HAS_VULKAN) && defined(OMNIUI_HAS_CUDA)
namespace
{

bool envMatches(const char* name, std::initializer_list<const char*> allowed)
{
    const char* v = getenv(name);
    if (!v)
        return false;
    for (const char* w : allowed)
    {
        if (strcmp(v, w) == 0)
            return true;
    }
    return false;
}

HeadlessVulkanPlatform* getActiveHeadlessPlatform()
{
    if (s_glfwPlatform)
        return nullptr;
    if (!s_platform)
        return nullptr;
    return dynamic_cast<HeadlessVulkanPlatform*>(s_platform.get());
}

} // namespace
#endif

bool initHeadlessFrameExport()
{
#if defined(OMNIUI_HAS_VULKAN) && defined(OMNIUI_HAS_CUDA)
    if (s_glfwPlatform)
    {
        fprintf(stderr,
                "initHeadlessFrameExport: refusing — GLFW platform is active "
                "(headless export requires OMNIUI_HEADLESS=1)\n");
        return false;
    }
    if (!envMatches("OMNIUI_HEADLESS", {"1", "true"}))
    {
        fprintf(stderr,
                "initHeadlessFrameExport: refusing — OMNIUI_HEADLESS must be 1\n");
        return false;
    }
    if (!envMatches("OMNIUI_BACKEND", {"vulkan", "vk"}))
    {
        fprintf(stderr,
                "initHeadlessFrameExport: refusing — OMNIUI_BACKEND must be vulkan\n");
        return false;
    }

    HeadlessVulkanPlatform* hp = getActiveHeadlessPlatform();
    if (!hp)
    {
        fprintf(stderr,
                "initHeadlessFrameExport: HeadlessVulkanPlatform not active "
                "(call standalone::init() first)\n");
        return false;
    }
    VulkanBackend* vk = hp->getVulkanBackend();
    if (!vk || !vk->isInitialized())
    {
        fprintf(stderr,
                "initHeadlessFrameExport: VulkanBackend not initialised\n");
        return false;
    }
    if (!vk->hasExternalMemory())
    {
        fprintf(stderr,
                "initHeadlessFrameExport: VulkanBackend lacks external memory "
                "support — CUDA interop requires VK_KHR_external_memory_fd\n");
        return false;
    }
    if (s_headlessFrameInterop)
    {
        fprintf(stderr,
                "initHeadlessFrameExport: already initialised\n");
        return false;
    }

    auto interop = std::make_unique<CudaVulkanInterop>();
    if (!interop->init(*vk))
    {
        fprintf(stderr,
                "initHeadlessFrameExport: CudaVulkanInterop::init failed\n");
        return false;
    }
    s_headlessFrameInterop = std::move(interop);
    return true;
#else
    fprintf(stderr,
            "initHeadlessFrameExport: build lacks OMNIUI_HAS_VULKAN and/or "
            "OMNIUI_HAS_CUDA\n");
    return false;
#endif
}

void shutdownHeadlessFrameExport()
{
#if defined(OMNIUI_HAS_VULKAN) && defined(OMNIUI_HAS_CUDA)
    if (s_headlessFrameInterop)
    {
        s_headlessFrameInterop->shutdown();
        s_headlessFrameInterop.reset();
    }
#endif
}

bool getHeadlessFrameExtent(int* width, int* height)
{
#if defined(OMNIUI_HAS_VULKAN) && defined(OMNIUI_HAS_CUDA)
    if (!width || !height)
        return false;
    HeadlessVulkanPlatform* hp = getActiveHeadlessPlatform();
    if (!hp)
        return false;
    VulkanBackend* vk = hp->getVulkanBackend();
    if (!vk || !vk->isInitialized())
        return false;
    vk->getFramebufferSize(width, height);
    return true;
#else
    (void)width;
    (void)height;
    return false;
#endif
}

void setHeadlessDrainFailureInjection(bool fail)
{
#if defined(OMNIUI_HAS_VULKAN) && defined(OMNIUI_HAS_CUDA)
    CudaVulkanInterop::setDrainFailureInjection(fail);
#else
    (void)fail;
#endif
}

bool resizeHeadlessFrame(int width, int height)
{
#if defined(OMNIUI_HAS_VULKAN) && defined(OMNIUI_HAS_CUDA)
    if (width <= 0 || height <= 0)
    {
        fprintf(stderr,
                "resizeHeadlessFrame: invalid dimensions %dx%d\n",
                width, height);
        return false;
    }
    HeadlessVulkanPlatform* hp = getActiveHeadlessPlatform();
    if (!hp)
    {
        fprintf(stderr,
                "resizeHeadlessFrame: no headless platform active\n");
        return false;
    }
    VulkanBackend* vk = hp->getVulkanBackend();
    if (!vk || !vk->isInitialized())
    {
        fprintf(stderr,
                "resizeHeadlessFrame: VulkanBackend not initialised\n");
        return false;
    }

    // The CUDA-Vulkan interop captures the current VkImage / VkMemory
    // by FD. ``VulkanBackend::beginFrame`` calls ``createFramebuffer``
    // when the requested extent differs from ``m_fbWidth/Height``,
    // and ``createFramebuffer`` (now transactional) atomically swaps
    // the old framebuffer for the new one — releasing the underlying
    // VkImage / VkDeviceMemory the previous import was keyed to.
    //
    // Drain any outstanding CUDA/Vulkan work referencing the current
    // semaphores BEFORE shutdown — ``signalHeadlessFrameConsumed``
    // queues an async CUDA signal on stream 0 against the C->V
    // semaphore, and ovui's previous tick may have submitted a
    // Vulkan command buffer that armed a wait on it. Destroying
    // those handles while either side is still in flight is UB.
    //
    // ``drainPendingHandoff`` returns ``true`` only when both
    // ``cudaStreamSynchronize(0)`` and ``vkDeviceWaitIdle`` succeed
    // (CudaVulkanInterop.cpp:63-110). On failure it returns
    // ``false`` — the imports are still potentially in flight, so
    // we MUST abort the resize without calling ``shutdown()`` or
    // resetting ``s_headlessFrameInterop``. Returning ``false`` here
    // surfaces back to the Python wrapper and ultimately to
    // ``Application._do_resize``, which already replies
    // ``changeResolutionConfirmation{result:"error"}`` on the false
    // path (Codex Step 3.7 review correction).
    bool reinit_interop = (s_headlessFrameInterop != nullptr);
    if (reinit_interop)
    {
        if (!s_headlessFrameInterop->drainPendingHandoff())
        {
            fprintf(stderr,
                    "resizeHeadlessFrame: drainPendingHandoff failed; "
                    "aborting resize without teardown to keep the "
                    "current interop intact\n");
            return false;
        }
        s_headlessFrameInterop->shutdown();
        s_headlessFrameInterop.reset();
    }

    // Update the platform's stored dimensions. The next ``tick()``
    // calls ``beginFrame(m_width, m_height)`` which detects the size
    // change and runs ``vkDeviceWaitIdle`` + ``createFramebuffer``.
    hp->setMainWindowSize(width, height);
    hp->tick();

    // Verify the new framebuffer extent matches the request. A
    // mismatch means Vulkan refused (e.g. memory allocation failed
    // or the requested size exceeds device limits).
    int actual_w = 0, actual_h = 0;
    vk->getFramebufferSize(&actual_w, &actual_h);
    if (actual_w != width || actual_h != height)
    {
        fprintf(stderr,
                "resizeHeadlessFrame: framebuffer extent mismatch "
                "after tick: requested %dx%d, got %dx%d\n",
                width, height, actual_w, actual_h);
        // Best-effort restore of the prior interop state. We leave the
        // platform extent at whatever Vulkan settled on rather than
        // attempting another recreate that could compound the failure.
        if (reinit_interop)
        {
            auto restore = std::make_unique<CudaVulkanInterop>();
            if (restore->init(*vk))
                s_headlessFrameInterop = std::move(restore);
        }
        return false;
    }

    // Re-import the new VkImage / semaphores into CUDA so subsequent
    // ``copyHeadlessFrameToLinear`` / ``waitHeadlessFrameReady`` calls
    // see the resized target.
    if (reinit_interop)
    {
        auto interop = std::make_unique<CudaVulkanInterop>();
        if (!interop->init(*vk))
        {
            fprintf(stderr,
                    "resizeHeadlessFrame: CudaVulkanInterop::init failed "
                    "after resize\n");
            return false;
        }
        s_headlessFrameInterop = std::move(interop);
    }
    return true;
#else
    (void)width;
    (void)height;
    return false;
#endif
}

const char* getHeadlessFrameFormat()
{
    return "rgba8";
}

bool waitHeadlessFrameReady(uint64_t timeout_ns)
{
#if defined(OMNIUI_HAS_VULKAN) && defined(OMNIUI_HAS_CUDA)
    // The underlying primitive is an async stream sync — Vulkan submits a
    // signal on the V->C semaphore, CUDA queues a wait on stream 0. The
    // timeout is accepted for forward-compat with a future timeline-based
    // wait but is not enforced today.
    (void)timeout_ns;
    if (!s_headlessFrameInterop)
    {
        fprintf(stderr,
                "waitHeadlessFrameReady: not initialised "
                "(call initHeadlessFrameExport first)\n");
        return false;
    }
    return s_headlessFrameInterop->syncVulkanToCuda();
#else
    (void)timeout_ns;
    return false;
#endif
}

void signalHeadlessFrameConsumed()
{
#if defined(OMNIUI_HAS_VULKAN) && defined(OMNIUI_HAS_CUDA)
    if (!s_headlessFrameInterop)
        return;
    s_headlessFrameInterop->syncCudaToVulkan();
#endif
}

bool copyHeadlessFrameToLinear(uintptr_t dst_dev_ptr,
                               size_t dst_pitch_bytes,
                               uintptr_t cuda_stream_handle)
{
#if defined(OMNIUI_HAS_VULKAN) && defined(OMNIUI_HAS_CUDA)
    if (!s_headlessFrameInterop)
    {
        fprintf(stderr,
                "copyHeadlessFrameToLinear: not initialised\n");
        return false;
    }
    if (dst_dev_ptr == 0)
    {
        fprintf(stderr,
                "copyHeadlessFrameToLinear: null destination device pointer\n");
        return false;
    }

    int w = 0, h = 0;
    if (!getHeadlessFrameExtent(&w, &h) || w <= 0 || h <= 0)
    {
        fprintf(stderr,
                "copyHeadlessFrameToLinear: could not query frame extent\n");
        return false;
    }

    cudaArray_t src = s_headlessFrameInterop->getArray();
    if (!src)
    {
        fprintf(stderr,
                "copyHeadlessFrameToLinear: cudaArray not available\n");
        return false;
    }

    const size_t widthBytes = static_cast<size_t>(w) * 4;
    if (dst_pitch_bytes < widthBytes)
    {
        fprintf(stderr,
                "copyHeadlessFrameToLinear: dst_pitch_bytes (%zu) < required (%zu)\n",
                dst_pitch_bytes, widthBytes);
        return false;
    }

    cudaStream_t stream = reinterpret_cast<cudaStream_t>(cuda_stream_handle);
    cudaError_t err = cudaMemcpy2DFromArrayAsync(
        reinterpret_cast<void*>(dst_dev_ptr),
        dst_pitch_bytes,
        src,
        /*wOffset=*/0, /*hOffset=*/0,
        widthBytes,
        static_cast<size_t>(h),
        cudaMemcpyDeviceToDevice,
        stream);
    if (err != cudaSuccess)
    {
        fprintf(stderr,
                "copyHeadlessFrameToLinear: cudaMemcpy2DFromArrayAsync failed: %s\n",
                cudaGetErrorString(err));
        return false;
    }
    return true;
#else
    (void)dst_dev_ptr;
    (void)dst_pitch_bytes;
    (void)cuda_stream_handle;
    return false;
#endif
}

} // namespace standalone
} // namespace ui
} // namespace omni
