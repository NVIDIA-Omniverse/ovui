/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "StandaloneInit.h"

#include "NativeTiming.h"
#include "HeadlessClipboard.h"
#include "GlfwPlatform.h"
#ifdef OMNIUI_HAS_VULKAN
#include "HeadlessVulkanPlatform.h"
#include "VulkanBackend.h"
#endif
#include "OpenGLByteImageGpu.h"
#include "NativeFramePacing.h"
#include "OpenGLRenderer.h"
#include "StandaloneFileIO.h"
#include "StandaloneImageBackend.h"
#include "StandaloneRasterImageLoader.h"
#ifdef OMNIUI_HAS_SVG
#include "StandaloneSvgRasterizer.h"
#else
#include "StandaloneSvgOffRasterizer.h"
#endif
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

#include <atomic>
#include <chrono>
#include <thread>
#include <omni/ui/Workspace.h>
#include "WorkspaceLifecycle.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>
#include <imgui/backends/imgui_impl_opengl3.h>

#ifndef OMNIUI_HEADLESS_ONLY
#include <glad/glad.h>
#include <GLFW/glfw3.h>
#endif

// stb_image_write is compiled in PngZlibCompress.cpp, with its PNG compressor.
#include <stb_image_write.h>

#ifdef OMNIUI_HAS_CUDA
#include <cuda.h>
#include <cuda_runtime.h>
#include <cuda_gl_interop.h>
#endif

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <memory>
#include <mutex>
#include <cstdlib>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {

#ifdef OMNIUI_HAS_VULKAN
// Vulkan has no OpenGL functions, so OpenGLRenderer cannot make textures there.
// This renderer uploads Markdown images and emoji through the registered IByteImageGpu.
class ByteImageGpuRenderer final : public IUiRenderer
{
    struct Texture
    {
        IByteImageGpu::Handle state;
        void* imGuiId;
    };

public:
    TextureHandle createTexture(int width, int height, TextureFormat format, const void* data) override
    {
        auto* gpu = PlatformRegistry::instance().byteImageGpu();
        if (!gpu || format != TextureFormat::eRGBA8)
            return kInvalidTexture;
        auto* texture = new Texture{ gpu->createState(), nullptr };
        const auto* pixels = static_cast<const uint8_t*>(data);
        size_t stride = static_cast<size_t>(width) * 4;
        texture->imGuiId = gpu->updateImage(texture->state, &pixels, &stride, 1,
                                            { static_cast<uint32_t>(width), static_cast<uint32_t>(height) },
                                            PixelFormat::eRGBA8_UNORM, false, 0, 0, 0)
                               .imGuiReference;
        return reinterpret_cast<TextureHandle>(texture);
    }
    void updateTexture(TextureHandle, const void*, size_t) override {}
    void destroyTexture(TextureHandle handle) override
    {
        auto* texture = reinterpret_cast<Texture*>(handle);
        if (!texture)
            return;
        if (auto* gpu = PlatformRegistry::instance().byteImageGpu())
            gpu->destroyState(texture->state);
        delete texture;
    }
    void* getImGuiTextureId(TextureHandle handle) override
    {
        return handle ? reinterpret_cast<Texture*>(handle)->imGuiId : nullptr;
    }
    TextureHandle uploadFontAtlas(const unsigned char*, int, int) override { return kInvalidTexture; }
    void beginFrame() override {}
    void endFrame() override {}
};
#endif

// Keep shared_ptrs alive so we can access the concrete types for tick/shouldClose.
static std::shared_ptr<IUiPlatform> s_platform;
static WindowId s_mainWindowId = kInvalidWindowId;
static std::shared_ptr<GlfwPlatform> s_glfwPlatform; // Non-null only in non-headless mode
static std::shared_ptr<IUiRenderer> s_renderer;
static bool s_headlessMode = false;
static std::shared_ptr<StandaloneFileIO> s_fileIO;
static std::shared_ptr<StandaloneSettings> s_settings;
static std::shared_ptr<IByteImageGpu> s_byteImageGpu;
static std::shared_ptr<StandaloneRasterImageLoader> s_rasterImageLoader;
#ifdef OMNIUI_HAS_SVG
static std::shared_ptr<StandaloneSvgRasterizer> s_svgRasterizer;
#endif
static std::shared_ptr<StandaloneImageBackend> s_imageBackend;
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
    // Revoke/join the borrowed renderer before Python-owned renderer or
    // provider objects and before ImGui/Vulkan resources can be destroyed.
    registerNativeFramePacingBackend(nullptr);
    shutdownNativeFramePacing();
    shutdownVulkanStreaming();
    shutdownHeadlessFrameExport();

    // Release callback owners while Python and platform services are still alive.
    detail::endWorkspaceCallbackLifetime();

    // Release strong references to Windows before tearing down the WCM.
    // In standalone mode, Workspace::RegisterWindow keeps shared_ptrs to
    // prevent premature destruction when Python drops its reference.
    Workspace::clear();

    // Providers that Python still holds share the loader and can call it after
    // this point. Free its GPU textures while IByteImageGpu is registered.
    if (s_rasterImageLoader)
        s_rasterImageLoader->shutdown();
#ifdef OMNIUI_HAS_SVG
    if (s_svgRasterizer)
        s_svgRasterizer->shutdown();
#endif

    PlatformRegistry::instance().reset();
    // GPU provider destructors retain a raw backend pointer by design. Retire
    // them while the platform-owned Vulkan/OpenGL backend is still alive.
    s_mainWindowId = kInvalidWindowId;
    s_imageBackend.reset();
    s_rasterImageLoader.reset();
#ifdef OMNIUI_HAS_SVG
    s_svgRasterizer.reset();
#endif
    s_byteImageGpu.reset();
    s_renderer.reset();
    s_platform.reset();
    s_glfwPlatform.reset();
    s_fileIO.reset();
    s_settings.reset();
    s_log.reset();
    setStandaloneWindowCallbackManager(nullptr);
    s_windowCallbackManager.reset();
    s_headlessMode = false;
}

// Scheduled screenshot: path set by scheduleScreenshot(), captured in tick() before swap.
static std::string s_pendingScreenshotPath;
static std::mutex s_screenshotMutex;
static ScreenshotResult s_screenshotResult;
static uint64_t s_nextScreenshotRequestId = 1;
static bool s_screenshotDoneConsumed = false;

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

#if defined(__APPLE__) && defined(OMNIUI_HAS_VULKAN)
// Point the Vulkan loader at MoltenVK when no driver was chosen: the Vulkan
// SDK and Homebrew install its ICD outside the loader's default search.
static void findMoltenVkIcd()
{
    if (getenv("VK_DRIVER_FILES") || getenv("VK_ICD_FILENAMES"))
        return;
    std::vector<std::string> prefixes;
    if (const char* sdk = getenv("VULKAN_SDK"))
        prefixes.push_back(sdk);
    if (const char* brew = getenv("HOMEBREW_PREFIX"))
        prefixes.push_back(brew);
    prefixes.push_back("/opt/homebrew");
    prefixes.push_back("/usr/local");
    for (const std::string& prefix : prefixes)
    {
        for (const char* dir : {"/share/vulkan/icd.d/", "/etc/vulkan/icd.d/"})
        {
            const std::string path = prefix + dir + "MoltenVK_icd.json";
            if (FILE* file = fopen(path.c_str(), "r"))
            {
                fclose(file);
                setenv("VK_DRIVER_FILES", path.c_str(), 1);
                // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
                fprintf(stdout, "standalone::init: Vulkan driver %s\n", path.c_str());
                return;
            }
        }
    }
}
#endif

bool init(const char* title, int width, int height)
{
#if defined(__APPLE__) && defined(OMNIUI_HAS_VULKAN)
    findMoltenVkIcd();
#endif
    if (PlatformRegistry::instance().isInitialized())
    {
        // A backend is already active (for example from init_streaming() or an
        // earlier C++ init()). It is usable, so this is not a failure.
        fprintf(stderr, "standalone::init: already initialized\n");
        return true;
    }

    detail::beginWorkspaceCallbackLifetime();

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
    s_mainWindowId = wid;

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
#ifdef OMNIUI_HAS_VULKAN
    if (dynamic_cast<VulkanByteImageGpu*>(s_byteImageGpu.get()))
        s_renderer = std::make_shared<ByteImageGpuRenderer>();
#endif

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
    {
        reg.setByteImageGpu(s_byteImageGpu);
        // Both standalone backends report upload results.
#ifdef OMNIUI_HAS_VULKAN
        if (auto vulkan = std::dynamic_pointer_cast<VulkanByteImageGpu>(s_byteImageGpu))
            reg.setByteImageGpuChecked(vulkan);
        else
#endif
        if (auto opengl = std::dynamic_pointer_cast<OpenGLByteImageGpu>(s_byteImageGpu))
            reg.setByteImageGpuChecked(opengl);
    }

    // Register the raster image loader (stb_image + registered IByteImageGpu).
    // Depends on IByteImageGpu; only register when byteImageGpu is available.
    if (s_byteImageGpu)
    {
        s_rasterImageLoader = std::make_shared<StandaloneRasterImageLoader>();
        reg.setRasterImageLoader(s_rasterImageLoader);
    }

    std::shared_ptr<ISvgRasterizer> svgRasterizer;
#ifdef OMNIUI_HAS_SVG
    // Register the SVG rasterizer that VectorImageProvider asks for.
    // Register it also without IByteImageGpu, so that an SVG logs an error
    // instead of drawing nothing with no message.
    s_svgRasterizer = std::make_shared<StandaloneSvgRasterizer>();
    svgRasterizer = s_svgRasterizer;
#else
    // Built with OMNIUI_ENABLE_SVG=OFF. Register a rasterizer that draws
    // nothing and logs this cause, so that an .svg image does not stay empty
    // with no message.
    svgRasterizer = std::make_shared<StandaloneSvgOffRasterizer>();
#endif
    reg.setSvgRasterizer(svgRasterizer);

    // Register the ui.Image backend. It loads raster files through the raster
    // loader above and .svg files through the SVG rasterizer above, so that
    // ui.Image and ui.ImageWithProvider show the same picture of a file.
    // Register it also without a loader, so ui.Image logs an error instead of
    // showing an empty area with no message.
    s_imageBackend = std::make_shared<StandaloneImageBackend>(s_rasterImageLoader, svgRasterizer);
    reg.setImageBackend(s_imageBackend);

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

namespace
{
thread_local PresentWaitBeginFn t_presentWaitBegin = nullptr;
thread_local PresentWaitEndFn t_presentWaitEnd = nullptr;
} // namespace

void setPresentWaitHooks(PresentWaitBeginFn begin, PresentWaitEndFn end)
{
    t_presentWaitBegin = begin;
    t_presentWaitEnd = end;
}

static std::atomic<int> g_presentWaitTestDelayMs{0};
static std::atomic<double> g_presentWaitTestBegin{0.0};
static std::atomic<double> g_presentWaitTestEnd{0.0};

static double steadyNowSeconds()
{
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

void setPresentWaitTestDelayMs(int ms)
{
    g_presentWaitTestDelayMs = ms;
}

void getPresentWaitTestWindow(double* begin, double* end)
{
    *end = g_presentWaitTestEnd;
    *begin = g_presentWaitTestBegin;
}

PresentWaitScope::PresentWaitScope()
{
    if (t_presentWaitBegin && t_presentWaitEnd)
    {
        m_end = t_presentWaitEnd;
        m_token = t_presentWaitBegin();
    }
    const int delayMs = g_presentWaitTestDelayMs;
    if (delayMs > 0)
    {
        g_presentWaitTestEnd = 0.0;
        g_presentWaitTestBegin = steadyNowSeconds();
        std::this_thread::sleep_for(std::chrono::milliseconds(delayMs));
        g_presentWaitTestEnd = steadyNowSeconds();
    }
}

PresentWaitScope::~PresentWaitScope()
{
    if (m_end)
        m_end(m_token);
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
    s_glfwPlatform->setWindowSize(s_mainWindowId, width, height);

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

bool setWindowPosition(int x, int y)
{
#ifndef OMNIUI_HEADLESS_ONLY
    if (!s_glfwPlatform || !s_glfwPlatform->getGlfwWindow())
        return false;
    s_glfwPlatform->setWindowPosition(1, x, y);
    return true;
#else
    (void)x;
    (void)y;
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

bool setWindowTitle(const char* title)
{
    if (!s_platform || s_mainWindowId == kInvalidWindowId || !title)
        return false;
    s_platform->setWindowTitle(s_mainWindowId, title);
    return s_platform->getWindowTitle(s_mainWindowId) == title;
}

std::string getWindowTitle()
{
    if (!s_platform || s_mainWindowId == kInvalidWindowId)
        return {};
    return s_platform->getWindowTitle(s_mainWindowId);
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

    {
        std::lock_guard<std::mutex> lock(s_screenshotMutex);
        if (s_screenshotResult.status == ScreenshotStatus::ePending)
        {
            s_screenshotResult.status = ScreenshotStatus::eFailed;
            s_screenshotResult.actualFormat.clear();
            s_screenshotResult.message =
                "screenshot service shut down before the request completed";
            s_screenshotDoneConsumed = false;
        }
        s_pendingScreenshotPath.clear();
    }

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

enum class InjectedInputEventKind
{
    MouseButton,
    Key,
};

struct InjectedInputEvent
{
    InjectedInputEventKind kind;
    int value;
    bool pressed;
};

static struct InjectedInputState
{
    bool hasMousePos = false;
    float mouseX = 0.0f;
    float mouseY = 0.0f;

    // Ordered key/button events. Keeping these in one stream is required for
    // modifier-click: ImGui must see the modifier event before the button event
    // in the same queued-input drain.
    std::vector<InjectedInputEvent> events;

    float scrollDx = 0.0f;
    float scrollDy = 0.0f;
    bool hasScroll = false;

    bool leftCtrlDown = false;
    bool rightCtrlDown = false;
    bool leftShiftDown = false;
    bool rightShiftDown = false;
    bool leftAltDown = false;
    bool rightAltDown = false;
    bool leftSuperDown = false;
    bool rightSuperDown = false;

    // Character input is additive per-frame
    std::vector<unsigned int> charEvents;
    std::string textInput;
} s_injected;

static ImGuiKey modifierForInjectedLRKey(ImGuiKey key)
{
    switch (key)
    {
        case ImGuiKey_LeftCtrl:
        case ImGuiKey_RightCtrl:
            return ImGuiMod_Ctrl;
        case ImGuiKey_LeftShift:
        case ImGuiKey_RightShift:
            return ImGuiMod_Shift;
        case ImGuiKey_LeftAlt:
        case ImGuiKey_RightAlt:
            return ImGuiMod_Alt;
        case ImGuiKey_LeftSuper:
        case ImGuiKey_RightSuper:
            return ImGuiMod_Super;
        default:
            return ImGuiKey_None;
    }
}

static void setInjectedLRKeyDown(ImGuiKey key, bool pressed)
{
    switch (key)
    {
        case ImGuiKey_LeftCtrl:   s_injected.leftCtrlDown = pressed; break;
        case ImGuiKey_RightCtrl:  s_injected.rightCtrlDown = pressed; break;
        case ImGuiKey_LeftShift:  s_injected.leftShiftDown = pressed; break;
        case ImGuiKey_RightShift: s_injected.rightShiftDown = pressed; break;
        case ImGuiKey_LeftAlt:    s_injected.leftAltDown = pressed; break;
        case ImGuiKey_RightAlt:   s_injected.rightAltDown = pressed; break;
        case ImGuiKey_LeftSuper:  s_injected.leftSuperDown = pressed; break;
        case ImGuiKey_RightSuper: s_injected.rightSuperDown = pressed; break;
        default: break;
    }
}

static bool isInjectedModDown(ImGuiKey mod)
{
    switch (mod)
    {
        case ImGuiMod_Ctrl:
            return s_injected.leftCtrlDown || s_injected.rightCtrlDown;
        case ImGuiMod_Shift:
            return s_injected.leftShiftDown || s_injected.rightShiftDown;
        case ImGuiMod_Alt:
            return s_injected.leftAltDown || s_injected.rightAltDown;
        case ImGuiMod_Super:
            return s_injected.leftSuperDown || s_injected.rightSuperDown;
        default:
            return false;
    }
}

static void applyInjectedKeyEvent(ImGuiIO& io, int rawKey, bool pressed)
{
    const ImGuiKey key = detail::normalizeInjectedImguiKey(rawKey);
    if (key == ImGuiKey_None)
        return;

    io.AddKeyEvent(key, pressed);

    const ImGuiKey mod = modifierForInjectedLRKey(key);
    if (mod != ImGuiKey_None)
    {
        setInjectedLRKeyDown(key, pressed);
        io.AddKeyEvent(mod, isInjectedModDown(mod));
    }
}

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
    s_injected.events.push_back({InjectedInputEventKind::MouseButton, button, pressed});
}

void injectMouseScroll(float dx, float dy)
{
    s_injected.hasScroll = true;
    s_injected.scrollDx += dx;
    s_injected.scrollDy += dy;
}

void injectKeyEvent(int key, bool pressed)
{
    s_injected.events.push_back({InjectedInputEventKind::Key, key, pressed});
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

    for (const InjectedInputEvent& ev : s_injected.events)
    {
        if (ev.kind == InjectedInputEventKind::MouseButton)
        {
            io.AddMouseButtonEvent(ev.value, ev.pressed);
            continue;
        }
        applyInjectedKeyEvent(io, ev.value, ev.pressed);
    }
    s_injected.events.clear();

    if (s_injected.hasScroll)
    {
        io.AddMouseWheelEvent(s_injected.scrollDx, s_injected.scrollDy);
        s_injected.scrollDx = 0.0f;
        s_injected.scrollDy = 0.0f;
        s_injected.hasScroll = false;
    }

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

bool isSvgRasterizerBuiltIn()
{
#ifdef OMNIUI_HAS_SVG
    return true;
#else
    return false;
#endif
}

std::vector<std::tuple<int64_t, double, double>> takePresentTimings()
{
    std::vector<std::tuple<int64_t, double, double>> records;
#ifdef OMNIUI_HAS_VULKAN
    if (VulkanBackend* backend = s_glfwPlatform ? s_glfwPlatform->getVulkanBackend() : nullptr)
        for (const VulkanBackend::PresentTiming& timing : backend->takePresentTimings())
            records.emplace_back(timing.tag, timing.submitted, timing.completed);
#endif
    return records;
}

void setPresentTimingTag(int64_t tag)
{
#ifdef OMNIUI_HAS_VULKAN
    if (VulkanBackend* backend = s_glfwPlatform ? s_glfwPlatform->getVulkanBackend() : nullptr)
        backend->setPresentTimingTag(tag);
#endif
}

bool isTextInputActive()
{
    if (!ImGui::GetCurrentContext())
        return false;
    return ImGui::GetIO().WantTextInput;
}

bool endTextInput()
{
    // The context is read through its pointer: GImGui is not exported from the ImGui library.
    ImGuiContext* ctx = ImGui::GetCurrentContext();
    // io.WantTextInput is true only when a text input was in typing mode in the last frame. The
    // ID check alone is not enough: ImGui keeps InputTextState.ID after a text edit ends, and a
    // mouse drag of the same FloatDrag or IntDrag makes the same ID active.
    if (!ctx || !ctx->IO.WantTextInput || ctx->ActiveId == 0 || ctx->InputTextState.ID != ctx->ActiveId)
        return false;
    // The same call that ImGui makes when the user clicks outside an active text input.
    ImGui::ClearActiveID();
    return true;
}

bool isClipboardProcessPrivate()
{
    return isHeadlessClipboardInstalled();
}

// ---------------------------------------------------------------------------
// Screenshot capture
// ---------------------------------------------------------------------------

static bool isScreenshotTerminal(ScreenshotStatus status)
{
    return status != ScreenshotStatus::eIdle && status != ScreenshotStatus::ePending;
}

static std::string screenshotFormatForPath(const std::string& path)
{
    const size_t dot = path.find_last_of('.');
    std::string extension = dot == std::string::npos ? std::string{} : path.substr(dot);
    std::transform(extension.begin(), extension.end(), extension.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    if (extension == ".jpg" || extension == ".jpeg")
        return "jpeg";
    if (extension == ".bmp")
        return "bmp";
    return "png";
}

static uint64_t beginScreenshotResult(const std::string& path)
{
    std::lock_guard<std::mutex> lock(s_screenshotMutex);
    if (s_screenshotResult.status == ScreenshotStatus::ePending)
        return 0;

    const uint64_t requestId = s_nextScreenshotRequestId++;
    if (s_nextScreenshotRequestId == 0)
        s_nextScreenshotRequestId = 1;
    s_screenshotResult = {};
    s_screenshotResult.requestId = requestId;
    s_screenshotResult.status = ScreenshotStatus::ePending;
    s_screenshotResult.path = path;
    s_screenshotDoneConsumed = false;
    return requestId;
}

static bool completeScreenshotResult(
    uint64_t requestId,
    ScreenshotStatus status,
    const std::string& actualFormat,
    int width,
    int height,
    const std::string& message)
{
    std::lock_guard<std::mutex> lock(s_screenshotMutex);
    if (s_screenshotResult.requestId != requestId ||
        s_screenshotResult.status != ScreenshotStatus::ePending)
    {
        return false;
    }
    s_screenshotResult.status = status;
    s_screenshotResult.actualFormat = actualFormat;
    s_screenshotResult.width = width;
    s_screenshotResult.height = height;
    s_screenshotResult.message = message;
    return true;
}

static bool hasNonOpaquePixel(const std::vector<unsigned char>& pixels)
{
    // A reduction lets the compiler check opaque images in parallel. An
    // early exit per pixel makes every ordinary opaque screenshot slower.
    unsigned char alpha = 255;
    for (size_t i = 3; i < pixels.size(); i += 4)
        alpha &= pixels[i];
    return alpha != 255;
}

// Divide the color of each pixel that is not opaque by its alpha: c * 255 /
// alpha, rounded, and 0 where alpha is 0. Opaque pixels keep their bytes.
static void unpremultiplyAlpha(std::vector<unsigned char>& pixels)
{
    for (size_t i = 0; i + 3 < pixels.size(); i += 4)
    {
        const unsigned alpha = pixels[i + 3];
        if (alpha == 255)
            continue;
        for (size_t c = i; c < i + 3; ++c)
        {
            pixels[c] = alpha == 0
                ? 0
                : static_cast<unsigned char>((std::min)(255u, (pixels[c] * 255u + alpha / 2) / alpha));
        }
    }
}

static bool savePixelsToFile(
    const std::string& filepath,
    const std::vector<unsigned char>& pixels,
    int width,
    int height,
    bool flipVertically,
    std::string* error)
{
    const int rowBytes = width * 4;
    const unsigned char* outputPixels = pixels.data();
    std::vector<unsigned char> flipped;
    if (flipVertically)
    {
        flipped = pixels;
        std::vector<unsigned char> rowBuffer(rowBytes);
        for (int y = 0; y < height / 2; ++y)
        {
            unsigned char* top = flipped.data() + y * rowBytes;
            unsigned char* bottom = flipped.data() + (height - 1 - y) * rowBytes;
            std::memcpy(rowBuffer.data(), top, rowBytes);
            std::memcpy(top, bottom, rowBytes);
            std::memcpy(bottom, rowBuffer.data(), rowBytes);
        }
        outputPixels = flipped.data();
    }

    const std::string format = screenshotFormatForPath(filepath);
    // The pixels are premultiplied by alpha (see setClearColor), but PNG
    // defines straight color, and image readers also take the alpha of a
    // 32-bit BMP as straight. These two formats get straight color. JPEG has
    // no alpha and keeps the premultiplied color: the frame over black.
    std::vector<unsigned char> straight;
    if ((format == "png" || format == "bmp") && hasNonOpaquePixel(pixels))
    {
        straight.assign(outputPixels, outputPixels + pixels.size());
        unpremultiplyAlpha(straight);
        outputPixels = straight.data();
    }

    int result = 0;
    if (format == "jpeg")
        result = stbi_write_jpg(filepath.c_str(), width, height, 4, outputPixels, 95);
    else if (format == "bmp")
        result = stbi_write_bmp(filepath.c_str(), width, height, 4, outputPixels);
    else
        result = stbi_write_png(filepath.c_str(), width, height, 4, outputPixels, rowBytes);

    if (!result)
    {
        if (error)
            *error = "image encoder failed to persist screenshot";
        fprintf(stderr, "captureScreenshot: failed to write %s\n", filepath.c_str());
        return false;
    }

    fprintf(stdout, "captureScreenshot: saved %s (%dx%d)\n", filepath.c_str(), width, height);
    return true;
}

#ifdef OMNIUI_HAS_VULKAN
static bool captureVulkanScreenshot(
    VulkanBackend* vkBackend,
    const std::string& path,
    int* resultWidth,
    int* resultHeight,
    std::string* error)
{
    if (!vkBackend)
    {
        if (error)
            *error = "Vulkan screenshot backend is unavailable";
        return false;
    }

    int width = 0;
    int height = 0;
    vkBackend->getFramebufferSize(&width, &height);
    if (resultWidth)
        *resultWidth = width;
    if (resultHeight)
        *resultHeight = height;
    if (width <= 0 || height <= 0)
    {
        if (error)
            *error = "Vulkan framebuffer has an invalid extent";
        return false;
    }

    std::vector<unsigned char> pixels(static_cast<size_t>(width) * height * 4);
    if (!vkBackend->readbackPixels(pixels.data(), width, height))
    {
        if (error)
            *error = (vkBackend->usesFastPresentationMode() && !vkBackend->fastCaptureSupported())
                ? "Vulkan FAST presentation swapchain does not support readback"
                : "Vulkan framebuffer readback failed";
        return false;
    }
    return savePixelsToFile(path, pixels, width, height, false, error);
}
#endif // OMNIUI_HAS_VULKAN

#ifdef OMNIUI_HAS_EGL
static void synchronizeEglScreenshotResult()
{
    auto* ep = dynamic_cast<HeadlessEglPlatform*>(s_platform.get());
    if (!ep || !ep->isScreenshotDone())
        return;

    const uint64_t requestId = ep->screenshotRequestId();
    const bool success = !ep->hadScreenshotError();
    completeScreenshotResult(
        requestId,
        success ? ScreenshotStatus::eSucceeded : ScreenshotStatus::eFailed,
        success ? ep->screenshotActualFormat() : std::string{},
        ep->screenshotWidth(),
        ep->screenshotHeight(),
        ep->screenshotErrorMessage());
}
#endif

bool scheduleScreenshot(const char* filepath)
{
    const std::string pathCopy = filepath ? filepath : "";
    const uint64_t requestId = beginScreenshotResult(pathCopy);
    if (requestId == 0)
        return false;
    if (!s_platform)
    {
        completeScreenshotResult(
            requestId, ScreenshotStatus::eFailed, {}, 0, 0,
            "standalone screenshot service is not initialized");
        return false;
    }
    if (pathCopy.empty())
    {
        completeScreenshotResult(
            requestId, ScreenshotStatus::eFailed, {}, 0, 0,
            "screenshot output path is empty");
        return false;
    }

    s_pendingScreenshotPath = pathCopy;

#ifdef OMNIUI_HAS_EGL
    if (auto* ep = dynamic_cast<HeadlessEglPlatform*>(s_platform.get()))
    {
        ep->captureScreenshot(pathCopy, requestId);
        return true;
    }
#endif

#ifdef OMNIUI_HAS_VULKAN
    if (s_headlessMode)
    {
        auto* headless = dynamic_cast<HeadlessVulkanPlatform*>(s_platform.get());
        if (!headless)
        {
            completeScreenshotResult(
                requestId, ScreenshotStatus::eFailed, {}, 0, 0,
                "headless Vulkan screenshot backend is unavailable");
            return false;
        }
        headless->setPreSwapCallback([pathCopy, requestId]() {
            if (!isScreenshotRequestPending(requestId))
                return;
            auto* platform = dynamic_cast<HeadlessVulkanPlatform*>(s_platform.get());
            int width = 0;
            int height = 0;
            std::string error;
            bool success = false;
            if (!platform)
                error = "headless Vulkan screenshot backend is unavailable";
            else
                success = captureVulkanScreenshot(
                    platform->getVulkanBackend(), pathCopy, &width, &height, &error);
            const bool recorded = completeScreenshotResult(
                requestId,
                success ? ScreenshotStatus::eSucceeded : ScreenshotStatus::eFailed,
                success ? screenshotFormatForPath(pathCopy) : std::string{},
                width,
                height,
                error);
            if (success && !recorded)
                std::remove(pathCopy.c_str());
        });
        return true;
    }
#endif

    if (!s_glfwPlatform)
    {
        completeScreenshotResult(
            requestId, ScreenshotStatus::eFailed, {}, 0, 0,
            "GLFW screenshot backend is unavailable");
        return false;
    }

#ifdef OMNIUI_HAS_VULKAN
    // FAST direct presentation has no offscreen image. Ask the next frame to
    // copy its swapchain image before it is presented.
    if (s_glfwPlatform->getBackendType() == BackendType::eVulkan && s_glfwPlatform->getVulkanBackend())
        s_glfwPlatform->getVulkanBackend()->requestFastCapture();
#endif

    s_glfwPlatform->setPreSwapCallback([pathCopy, requestId]() {
        if (!isScreenshotRequestPending(requestId))
            return;
#ifdef OMNIUI_HAS_VULKAN
        if (s_glfwPlatform && s_glfwPlatform->getBackendType() == BackendType::eVulkan)
        {
            int width = 0;
            int height = 0;
            std::string error;
            const bool success = captureVulkanScreenshot(
                s_glfwPlatform->getVulkanBackend(), pathCopy, &width, &height, &error);
            const bool recorded = completeScreenshotResult(
                requestId,
                success ? ScreenshotStatus::eSucceeded : ScreenshotStatus::eFailed,
                success ? screenshotFormatForPath(pathCopy) : std::string{},
                width,
                height,
                error);
            if (success && !recorded)
                std::remove(pathCopy.c_str());
            return;
        }
#endif
#ifndef OMNIUI_HEADLESS_ONLY
        GLint viewport[4] = {};
        glGetIntegerv(GL_VIEWPORT, viewport);
        int width = viewport[2];
        int height = viewport[3];
        if ((width <= 0 || height <= 0) && s_glfwPlatform)
            s_glfwPlatform->getWindowSize(1, &width, &height);
        if (width <= 0 || height <= 0)
        {
            completeScreenshotResult(
                requestId, ScreenshotStatus::eFailed, {}, width, height,
                "OpenGL framebuffer has an invalid extent");
            return;
        }

        std::vector<unsigned char> pixels(static_cast<size_t>(width) * height * 4);
        while (glGetError() != GL_NO_ERROR)
        {
        }
        glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
        std::string error;
        bool success = glGetError() == GL_NO_ERROR;
        if (!success)
            error = "OpenGL framebuffer readback failed";
        else
            success = savePixelsToFile(pathCopy, pixels, width, height, true, &error);
        const bool recorded = completeScreenshotResult(
            requestId,
            success ? ScreenshotStatus::eSucceeded : ScreenshotStatus::eFailed,
            success ? screenshotFormatForPath(pathCopy) : std::string{},
            width,
            height,
            error);
        if (success && !recorded)
            std::remove(pathCopy.c_str());
#else
        completeScreenshotResult(
            requestId, ScreenshotStatus::eFailed, {}, 0, 0,
            "OpenGL screenshot support is unavailable in this build");
#endif
    });

    return true;
}

ScreenshotResult getLastScreenshotResult()
{
#ifdef OMNIUI_HAS_EGL
    synchronizeEglScreenshotResult();
#endif
    std::lock_guard<std::mutex> lock(s_screenshotMutex);
    return s_screenshotResult;
}

bool cancelScheduledScreenshot(uint64_t requestId)
{
    std::lock_guard<std::mutex> lock(s_screenshotMutex);
    if (requestId == 0 || s_screenshotResult.requestId != requestId ||
        s_screenshotResult.status != ScreenshotStatus::ePending)
    {
        return false;
    }
    s_screenshotResult.status = ScreenshotStatus::eCancelled;
    s_screenshotResult.actualFormat.clear();
    s_screenshotResult.message = "screenshot request was cancelled";
    s_screenshotDoneConsumed = false;
    return true;
}

bool isScreenshotRequestPending(uint64_t requestId)
{
    std::lock_guard<std::mutex> lock(s_screenshotMutex);
    return requestId != 0 && s_screenshotResult.requestId == requestId &&
           s_screenshotResult.status == ScreenshotStatus::ePending;
}

bool pollScreenshotDone()
{
    const ScreenshotResult result = getLastScreenshotResult();
    if (!isScreenshotTerminal(result.status))
        return false;
    std::lock_guard<std::mutex> lock(s_screenshotMutex);
    if (s_screenshotDoneConsumed)
        return false;
    s_screenshotDoneConsumed = true;
    s_pendingScreenshotPath.clear();
    return true;
}

bool hadLastScreenshotError()
{
    const ScreenshotStatus status = getLastScreenshotResult().status;
    return isScreenshotTerminal(status) && status != ScreenshotStatus::eSucceeded;
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
// Clear color of the headless Vulkan frame
// ---------------------------------------------------------------------------

#ifdef OMNIUI_HAS_VULKAN
static VulkanBackend* getHeadlessVulkanBackend()
{
    if (s_glfwPlatform || !s_platform)
        return nullptr;
    auto* platform = dynamic_cast<HeadlessVulkanPlatform*>(s_platform.get());
    return platform ? platform->getVulkanBackend() : nullptr;
}

// Enough digits to read back as the same float, so that a message never
// shows 1 for a value just above 1.
static std::string formatClearValue(float value)
{
    char text[32];
    for (int digits = 6; digits <= 9; ++digits)
    {
        snprintf(text, sizeof(text), "%.*g", digits, value);
        if (strtof(text, nullptr) == value)
            break;
    }
    return text;
}

// The cause when the values are not a valid premultiplied color, or empty.
static std::string clearColorValueError(const float rgba[4])
{
    static const char* const kNames[4] = { "red", "green", "blue", "alpha" };
    for (int i = 0; i < 4; ++i)
    {
        if (!std::isfinite(rgba[i]) || rgba[i] < 0.0f || rgba[i] > 1.0f)
        {
            return std::string(kNames[i]) + " is " + formatClearValue(rgba[i]) +
                   "; each value of the clear color must be from 0 to 1";
        }
    }
    for (int i = 0; i < 3; ++i)
    {
        if (rgba[i] > rgba[3])
        {
            return std::string(kNames[i]) + " " + formatClearValue(rgba[i]) + " is greater than alpha " +
                   formatClearValue(rgba[3]) +
                   "; the clear color is premultiplied by alpha, so red, green and blue must each be at "
                   "most alpha (a transparent clear is 0, 0, 0, 0)";
        }
    }
    return {};
}
#endif

static bool refuseClearColor(const std::string& cause, std::string* error)
{
    // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
    fprintf(stderr, "setClearColor: %s\n", cause.c_str());
    if (error)
        *error = cause;
    return false;
}

bool setClearColor(float red, float green, float blue, float alpha, std::string* error)
{
#ifdef OMNIUI_HAS_VULKAN
    if (VulkanBackend* backend = getHeadlessVulkanBackend())
    {
        const float rgba[4] = { red, green, blue, alpha };
        const std::string cause = clearColorValueError(rgba);
        if (!cause.empty())
            return refuseClearColor(cause, error);
        backend->setClearColor({ red, green, blue, alpha });
        return true;
    }
#endif
    const char* active = !s_platform ? "not started (call init() first)"
                         : s_glfwPlatform ? "a window (GLFW)"
                                          : "headless EGL";
    return refuseClearColor(std::string("the clear color applies only to the headless Vulkan backend "
                                        "(OMNIUI_HEADLESS=1 with Vulkan); the backend is ") + active,
                            error);
}

bool getClearColor(float* red, float* green, float* blue, float* alpha)
{
#ifdef OMNIUI_HAS_VULKAN
    if (VulkanBackend* backend = getHeadlessVulkanBackend())
    {
        const std::array<float, 4> rgba = backend->getClearColor();
        *red = rgba[0];
        *green = rgba[1];
        *blue = rgba[2];
        *alpha = rgba[3];
        return true;
    }
#endif
    (void)red;
    (void)green;
    (void)blue;
    (void)alpha;
    return false;
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
