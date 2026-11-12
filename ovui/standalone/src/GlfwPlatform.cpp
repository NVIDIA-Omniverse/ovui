/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "GlfwPlatform.h"
#include "NativeFramePacing.h"
#ifdef _WIN32
#include "Win32WindowTitle.h"
#endif
#ifdef OMNIUI_HAS_VULKAN
#include "VulkanBackend.h"
#include "VulkanByteImageGpu.h"
#endif
#include "StandaloneGlyphManager.h"
#include "StandaloneInit.h"
#include "StandaloneWindowCallbackManager.h"
#include "ImGuiKeyTranslation.h"
#include "NativeTiming.h"

#include <omni/ui/ImageProvider/ImageProvider.h>
#include <omni/ui/ImageProvider/PresentationKeyGuard.h>
#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/Font.h>

#include <glad/glad.h>
#include <GLFW/glfw3.h>
#ifdef _WIN32
#define GLFW_EXPOSE_NATIVE_WIN32
#include <GLFW/glfw3native.h>
#endif
#include <imgui/imgui.h>
#include <imgui/backends/imgui_impl_glfw.h>
#include <imgui/backends/imgui_impl_opengl3.h>

#ifdef OMNIUI_HAS_VULKAN
#include <imgui/backends/imgui_impl_vulkan.h>
#endif

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#elif defined(__linux__) || defined(__APPLE__)
#include <dlfcn.h>
#endif

namespace omni {
namespace ui {
namespace standalone {

// Resize through GLFW so its framebuffer callbacks also observe the change.
static void resizeGlfwWindow(GLFWwindow* window, int width, int height)
{
#ifdef _WIN32
    // GLFW_DONT_CARE leaves Win32's desktop-sized maximum tracking bounds in
    // place. Those bounds also clamp programmatic resizes.
    // Supply explicit bounds for this operation, then restore normal dragging
    // and maximizing limits. Keep the current size within the temporary bounds
    // because changing GLFW limits itself asks Windows to revalidate the size.
    int currentWidth = 0, currentHeight = 0;
    glfwGetWindowSize(window, &currentWidth, &currentHeight);
    glfwSetWindowSizeLimits(window, GLFW_DONT_CARE, GLFW_DONT_CARE,
                            (std::max)(width, currentWidth), (std::max)(height, currentHeight));
#endif
    glfwSetWindowSize(window, width, height);
#ifdef _WIN32
    // On Win32, clearing all limits does not resize the window again.
    glfwSetWindowSizeLimits(window, GLFW_DONT_CARE, GLFW_DONT_CARE,
                            GLFW_DONT_CARE, GLFW_DONT_CARE);
#endif
}

// Cursor motion for camera navigation, taken from GLFW's own callback (chained
// before ImGui's), with the time each event arrives on the steady clock, which
// is the clock of Python's time.perf_counter.
struct CursorMotion
{
    GLFWwindow* window = nullptr;
    GLFWcursorposfun next = nullptr;
    bool haveLast = false;
    double x = 0.0, y = 0.0, dx = 0.0, dy = 0.0, time = 0.0;
};
static CursorMotion s_cursor;

static void onCursorPos(GLFWwindow* window, double x, double y)
{
    if (s_cursor.haveLast)
    {
        s_cursor.dx += x - s_cursor.x;
        s_cursor.dy += y - s_cursor.y;
    }
    s_cursor.x = x;
    s_cursor.y = y;
    s_cursor.haveLast = true;
    s_cursor.time = std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
    if (s_cursor.next)
        s_cursor.next(window, x, y);
}

bool readCursorMotion(double* dx, double* dy, double* time)
{
    if (!s_cursor.window)
        return false;
    *dx = s_cursor.dx;
    *dy = s_cursor.dy;
    *time = s_cursor.time;
    s_cursor.dx = s_cursor.dy = 0.0;
    return true;
}

void setCursorCapture(bool captured)
{
    if (!s_cursor.window)
        return;
    if (glfwRawMouseMotionSupported())
        glfwSetInputMode(s_cursor.window, GLFW_RAW_MOUSE_MOTION, captured ? GLFW_TRUE : GLFW_FALSE);
    glfwSetInputMode(s_cursor.window, GLFW_CURSOR, captured ? GLFW_CURSOR_DISABLED : GLFW_CURSOR_NORMAL);
}

// ---------------------------------------------------------------------------
// Font loading helper
// ---------------------------------------------------------------------------

/// Try to find the resources/fonts directory relative to the shared library
/// location (for wheel installs) or the current working directory (for dev).
static std::string findFontPath(const char* fontFile)
{
    namespace fs = std::filesystem;

    // Strategy 1: Relative to this shared library (works in pip wheel installs
    // AND in dev/editable builds, where the fonts live several parents up
    // from the DLL location — mirrors the Linux branch below).
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
                fs::path dir = fs::path(modulePath).parent_path();
                // Walk up from library location: works for both wheel installs
                // (omni/ui/resources/fonts/) and dev/editable builds (where the
                // DLL is staged into python/omni/ui/ but the fonts live at
                // <repo_root>/resources/fonts/, three parents up).
                for (int up = 0; up < 8 && !dir.empty(); ++up, dir = dir.parent_path())
                {
                    fs::path candidate = dir / "resources" / "fonts" / fontFile;
                    if (fs::exists(candidate))
                        return candidate.string();
                }
            }
        }
    }
#elif defined(__linux__) || defined(__APPLE__)
    {
        Dl_info info;
        if (dladdr(reinterpret_cast<void*>(&findFontPath), &info) && info.dli_fname)
        {
            fs::path dir = fs::path(info.dli_fname).parent_path();
            // Walk up from library location: works for both wheel installs
            // (omni/ui/resources/fonts/) and dev builds (build/pip/standalone/
            // → ... → project_root/resources/fonts/)
            for (int up = 0; up < 8 && !dir.empty(); ++up, dir = dir.parent_path())
            {
                fs::path candidate = dir / "resources" / "fonts" / fontFile;
                if (fs::exists(candidate))
                    return candidate.string();
            }
        }
    }
#endif

    // Strategy 2: Relative to current working directory (dev builds)
    {
        fs::path candidate = fs::path("resources") / "fonts" / fontFile;
        if (fs::exists(candidate))
            return candidate.string();
    }

    // Strategy 3: Check parent directories walking up from cwd
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

GlfwPlatform::~GlfwPlatform()
{
    if (m_backendType == BackendType::eVulkan)
    {
        registerNativeFramePacingBackend(nullptr);
        shutdownNativeFramePacing();
    }
    // Destroy all virtual windows before tearing down the GL context.
    for (auto& [id, vw] : m_virtualWindows)
        deleteFboAttachments(vw);
    m_virtualWindows.clear();

    if (m_window)
    {
#ifdef OMNIUI_HAS_VULKAN
        if (m_backendType == BackendType::eVulkan)
        {
            m_vulkanBackend.reset();
            ImGui_ImplGlfw_Shutdown();
            ImGui::DestroyContext();
        }
        else
#endif
        {
            ImGui_ImplOpenGL3_Shutdown();
            ImGui_ImplGlfw_Shutdown();
            ImGui::DestroyContext();
        }
        glfwDestroyWindow(m_window);
        m_window = nullptr;
    }
    glfwTerminate();
}

// ---------------------------------------------------------------------------
// Window lifecycle
// ---------------------------------------------------------------------------

WindowId GlfwPlatform::createWindow(const char* title, int width, int height)
{
    if (m_window)
    {
        fprintf(stderr, "GlfwPlatform::createWindow: only one OS window is supported in V1\n");
        return m_mainWindowId;
    }

    {
        OVUI_PERFORMANCE_PHASE_SCOPE(glfwInitPhase, kGlfwInitPhaseName);
#if defined(__APPLE__) && defined(VK_VERSION_1_0) && (GLFW_VERSION_MAJOR > 3 || GLFW_VERSION_MINOR >= 4)
        // GLFW uses the Vulkan loader ovui links: its own search misses a
        // Homebrew or SDK loader outside the default dyld paths, and the
        // window then falls back to OpenGL.
        glfwInitVulkanLoader(vkGetInstanceProcAddr);
#endif
        if (!glfwInit())
        {
            fprintf(stderr, "GlfwPlatform::createWindow: glfwInit failed\n");
            return kInvalidWindowId;
        }
    }

    // Prefer Vulkan when available.  OpenGL remains available explicitly and
    // as a fallback when the default Vulkan backend cannot initialize.
    m_backendType = BackendType::eOpenGL;
#ifdef OMNIUI_HAS_VULKAN
    bool explicitVulkan = false;
    {
        const char* env = getenv("OMNIUI_BACKEND");
        m_backendType = BackendType::eVulkan;
        if (env && (strcmp(env, "opengl") == 0 || strcmp(env, "OpenGL") == 0 || strcmp(env, "gl") == 0))
        {
            m_backendType = BackendType::eOpenGL;
            fprintf(stdout, "GlfwPlatform: OpenGL backend selected via OMNIUI_BACKEND\n");
        }
        else if (env && (strcmp(env, "vulkan") == 0 || strcmp(env, "Vulkan") == 0 || strcmp(env, "vk") == 0))
        {
            explicitVulkan = true;
            fprintf(stdout, "GlfwPlatform: Vulkan backend selected via OMNIUI_BACKEND\n");
        }
        else if (!env || !*env)
        {
            fprintf(stdout, "GlfwPlatform: Vulkan backend selected by default\n");
        }
    }
#endif

    if (m_backendType == BackendType::eVulkan)
    {
#ifdef OMNIUI_HAS_VULKAN
        glfwWindowHint(GLFW_CLIENT_API, GLFW_NO_API);
#endif
    }
    else
    {
        // Request OpenGL 3.3 core profile
        glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
        glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
        glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
#ifdef __APPLE__
        glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GL_TRUE);
#endif
    }

    // Scale the initial window size by the primary monitor's content scale so
    // that a caller asking for "1280x720" gets a usable window on a Hi-DPI
    // display (e.g. 2240x1260 on a 175% Windows display). glfw on Windows /
    // Linux treats glfwCreateWindow's width/height as physical pixels, so
    // without this a 1280x720 request produces a tiny window on Hi-DPI. On
    // macOS glfw uses logical (points) already, so skip the pre-scale.
    int createW = width;
    int createH = height;
#ifndef __APPLE__
    if (GLFWmonitor* primary = glfwGetPrimaryMonitor())
    {
        float mxscale = 1.0f, myscale = 1.0f;
        glfwGetMonitorContentScale(primary, &mxscale, &myscale);
        if (mxscale > 0.0f && myscale > 0.0f)
        {
            createW = static_cast<int>(width * mxscale + 0.5f);
            createH = static_cast<int>(height * myscale + 0.5f);
        }
    }
#endif

    m_window = glfwCreateWindow(createW, createH, title ? title : "omni.ui", nullptr, nullptr);
    if (!m_window)
    {
        fprintf(stderr, "GlfwPlatform::createWindow: glfwCreateWindow failed\n");
        glfwTerminate();
        return kInvalidWindowId;
    }

    m_title = title ? title : "omni.ui";

#ifdef _WIN32
    // Creation is subject to the same desktop clamp. Correct it before the
    // renderer allocates its framebuffer/swapchain, preserving the DPI scale.
    resizeGlfwWindow(m_window, createW, createH);
#endif

    if (m_backendType == BackendType::eVulkan)
    {
#ifdef OMNIUI_HAS_VULKAN
        OVUI_PERFORMANCE_PHASE_SCOPE(vulkanInitPhase, kVulkanInitPhaseName);
        m_vulkanBackend = std::make_unique<VulkanBackend>();
        int framebufferWidth = 0;
        int framebufferHeight = 0;
        glfwGetFramebufferSize(m_window, &framebufferWidth, &framebufferHeight);
        if (!m_vulkanBackend->init(m_window, framebufferWidth, framebufferHeight))
        {
            fprintf(stderr, "GlfwPlatform::createWindow: Vulkan init failed\n");
            m_vulkanBackend.reset();
            glfwDestroyWindow(m_window);
            m_window = nullptr;
            if (explicitVulkan)
            {
                glfwTerminate();
                return kInvalidWindowId;
            }

            fprintf(stderr, "GlfwPlatform::createWindow: falling back to OpenGL\n");
            m_backendType = BackendType::eOpenGL;
            glfwDefaultWindowHints();
            glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
            glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
            glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
#ifdef __APPLE__
            // macOS creates a 3.2+ core context only with forward compatibility.
            glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE);
#endif
            m_window = glfwCreateWindow(createW, createH, title ? title : "omni.ui", nullptr, nullptr);
            if (!m_window)
            {
                fprintf(stderr, "GlfwPlatform::createWindow: OpenGL fallback window creation failed\n");
                glfwTerminate();
                return kInvalidWindowId;
            }
#ifdef _WIN32
            resizeGlfwWindow(m_window, createW, createH);
#endif
        }
#endif
    }
    if (m_backendType == BackendType::eOpenGL)
    {
        OVUI_PERFORMANCE_PHASE_SCOPE(openGlInitPhase, kOpenGlInitPhaseName);
        glfwMakeContextCurrent(m_window);

        // Load OpenGL via glad
        if (!gladLoadGLLoader((GLADloadproc)glfwGetProcAddress))
        {
            fprintf(stderr, "GlfwPlatform::createWindow: gladLoadGLLoader failed\n");
            glfwDestroyWindow(m_window);
            m_window = nullptr;
            glfwTerminate();
            return kInvalidWindowId;
        }

        // Keep presentation non-blocking. The standalone run loop applies the
        // app.runLoops.main.rateLimitFrequency cap (120 FPS by default), so a
        // swap interval of one would incorrectly pin GlfwPlatform::tick to a
        // 60 Hz display and block here for roughly 16 ms.
        glfwSwapInterval(0);
    }

    // Initialize ImGui
    OVUI_PERFORMANCE_PHASE_SCOPE(imGuiInitPhase, kImGuiInitPhaseName);
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    io.ConfigFlags |= ImGuiConfigFlags_DockingEnable;

    // ---------------------------------------------------------------
    // Apply Kit's NVIDIA Dark theme (eNvidiaDark from carb.imgui)
    // ---------------------------------------------------------------
    {
        ImGuiStyle& s = ImGui::GetStyle();

        // Size attributes (setStyleSize)
        s.WindowPadding     = ImVec2(8.0f, 8.0f);
        s.PopupRounding     = 4.0f;
        s.FramePadding      = ImVec2(8.0f, 4.0f);
        s.ItemSpacing       = ImVec2(6.0f, 6.0f);
        s.ItemInnerSpacing  = ImVec2(4.0f, 4.0f);
        s.TouchExtraPadding = ImVec2(0.0f, 0.0f);
        s.IndentSpacing     = 21.0f;
        s.ScrollbarSize     = 16.0f;
        s.GrabMinSize       = 8.0f;

        // Border sizes
        s.WindowBorderSize  = 1.0f;
        s.ChildBorderSize   = 1.0f;
        s.PopupBorderSize   = 1.0f;
        s.FrameBorderSize   = 0.0f;
        s.TabBorderSize     = 0.0f;

        // Rounding
        s.WindowRounding    = 2.0f;
        s.ChildRounding     = 0.0f;
        s.FrameRounding     = 4.0f;
        s.ScrollbarRounding = 4.0f;
        s.GrabRounding      = 4.0f;
        s.TabRounding       = 4.0f;

        // Alignment
        s.WindowTitleAlign  = ImVec2(0.5f, 0.5f);
        s.ButtonTextAlign   = ImVec2(0.48f, 0.5f);

        s.DisplaySafeAreaPadding = ImVec2(3.0f, 3.0f);

        // NVIDIA Dark colors
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
        s.Colors[ImGuiCol_NavCursor]             = ImVec4(0.26f, 0.59f, 0.98f, 1.00f);
        s.Colors[ImGuiCol_NavWindowingHighlight] = ImVec4(1.00f, 1.00f, 1.00f, 0.70f);
        s.Colors[ImGuiCol_NavWindowingDimBg]     = ImVec4(1.00f, 1.00f, 1.00f, 0.70f);
        s.Colors[ImGuiCol_ModalWindowDimBg]      = ImVec4(0.80f, 0.80f, 0.80f, 0.35f);
        s.Colors[ImGuiCol_WindowShadow]          = ImVec4(0.0f, 0.0f, 0.0f, 0.0f);

        // DPI-scale the style so padding, borders, frame heights etc. grow
        // with the display scale. Without this the menu bar, scrollbars,
        // and button hitboxes stay fixed in physical pixels while the fonts
        // scale up, producing cropped/tiny UI on Hi-DPI (e.g. 175%) displays.
        // ScaleAllSizes multiplies every ImVec2/float size field in place;
        // colors and alignment ratios are untouched.
#ifndef __APPLE__
        if (m_window)
        {
            float dxscale = 1.0f;
            glfwGetWindowContentScale(m_window, &dxscale, nullptr);
            if (dxscale > 0.0f && dxscale != 1.0f)
                s.ScaleAllSizes(dxscale);
        }
#endif
    }

    if (m_backendType == BackendType::eVulkan)
        ImGui_ImplGlfw_InitForVulkan(m_window, true);
    else
        ImGui_ImplGlfw_InitForOpenGL(m_window, true);
    s_cursor = CursorMotion{m_window, glfwSetCursorPosCallback(m_window, onCursorPos)};

    // Load a body font at all standard sizes so omni.ui font_size works at any value.
    // Noto Sans is the primary UI font; Roboto is a last-resort fallback.
    // IMPORTANT: Fonts must be loaded BEFORE initializing the renderer backend,
    // because the backend builds the font atlas texture from whatever fonts are
    // registered at that point.
    {
        float dpiScale = 1.0f;
#ifndef __APPLE__
        glfwGetWindowContentScale(m_window, &dpiScale, nullptr);
#endif
        std::string fontPath = findFontPath("NotoSans-Regular.ttf");
        if (fontPath.empty())
            fontPath = findFontPath("roboto_medium.ttf");

        auto glyphManager = std::make_shared<StandaloneGlyphManager>();
        if (!fontPath.empty() && glyphManager->loadFonts(fontPath, dpiScale))
        {
            fprintf(stdout, "GlfwPlatform: loaded font %s at all sizes (dpiScale=%.2f)\n",
                    fontPath.c_str(), dpiScale);
            // Make the "normal" (14px) font the ImGui default so stock ImGui
            // widgets also render with the body font.
            auto* normalFont = reinterpret_cast<ImFont*>(
                glyphManager->getFont(FontStyle::eLarge));  // eLarge=16px is closest to ImGui default
            if (normalFont)
                io.FontDefault = normalFont;

            PlatformRegistry::instance().setGlyphManager(glyphManager);
        }
        else
        {
            fprintf(stdout, "GlfwPlatform: No custom font found, using ImGui default\n");
        }
    }

    // Initialize the renderer backend AFTER fonts are loaded
    if (m_backendType == BackendType::eVulkan)
    {
#ifdef OMNIUI_HAS_VULKAN
        m_vulkanBackend->initImGui();
        OVUI_PERFORMANCE_PHASE_STOP(imGuiInitPhase);
        {
            OVUI_PERFORMANCE_PHASE_SCOPE(framePacingInitPhase, kFramePacingInitPhaseName);
            registerNativeFramePacingBackend(m_vulkanBackend.get());
        }
#endif
    }
    else
    {
        // macOS Core Profile requires GLSL 1.50+; other platforms are fine with 1.30
#ifdef __APPLE__
        ImGui_ImplOpenGL3_Init("#version 150");
#else
        ImGui_ImplOpenGL3_Init("#version 130");
#endif
    }
    OVUI_PERFORMANCE_PHASE_STOP(imGuiInitPhase);

    m_mainWindowId = m_nextWindowId++;
    return m_mainWindowId;
}

void GlfwPlatform::destroyWindow(WindowId id)
{
    if (id != m_mainWindowId || !m_window)
        return;

#ifdef OMNIUI_HAS_VULKAN
    if (m_backendType == BackendType::eVulkan)
    {
        registerNativeFramePacingBackend(nullptr);
        shutdownNativeFramePacing();
        m_vulkanBackend.reset();
        ImGui_ImplGlfw_Shutdown();
        ImGui::DestroyContext();
    }
    else
#endif
    {
        ImGui_ImplOpenGL3_Shutdown();
        ImGui_ImplGlfw_Shutdown();
        ImGui::DestroyContext();
    }
    s_cursor = CursorMotion{};
    glfwDestroyWindow(m_window);
    m_window = nullptr;
    m_mainWindowId = kInvalidWindowId;
}

// ---------------------------------------------------------------------------
// FBO helpers for virtual windows
// ---------------------------------------------------------------------------

bool GlfwPlatform::createFboAttachments(VirtualWindowInfo& vw)
{
    // Color texture (RGBA8)
    glGenTextures(1, &vw.colorTex);
    glBindTexture(GL_TEXTURE_2D, vw.colorTex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, vw.width, vw.height, 0,
                 GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glBindTexture(GL_TEXTURE_2D, 0);

    // Depth/stencil renderbuffer
    glGenRenderbuffers(1, &vw.depthRbo);
    glBindRenderbuffer(GL_RENDERBUFFER, vw.depthRbo);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, vw.width, vw.height);
    glBindRenderbuffer(GL_RENDERBUFFER, 0);

    // Framebuffer object
    glGenFramebuffers(1, &vw.fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, vw.fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, vw.colorTex, 0);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, vw.depthRbo);

    GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);

    if (status != GL_FRAMEBUFFER_COMPLETE)
    {
        fprintf(stderr, "GlfwPlatform: FBO incomplete (status=0x%x) for %dx%d\n",
                status, vw.width, vw.height);
        deleteFboAttachments(vw);
        return false;
    }

    return true;
}

void GlfwPlatform::deleteFboAttachments(VirtualWindowInfo& vw)
{
    if (vw.fbo)       { glDeleteFramebuffers(1, &vw.fbo);       vw.fbo = 0; }
    if (vw.colorTex)  { glDeleteTextures(1, &vw.colorTex);      vw.colorTex = 0; }
    if (vw.depthRbo)  { glDeleteRenderbuffers(1, &vw.depthRbo); vw.depthRbo = 0; }
}

WindowId GlfwPlatform::createVirtualWindow(int width, int height)
{
    if (width <= 0 || height <= 0)
    {
        fprintf(stderr, "GlfwPlatform::createVirtualWindow: invalid size %dx%d\n", width, height);
        return kInvalidWindowId;
    }

    VirtualWindowInfo vw;
    vw.width = width;
    vw.height = height;

    if (!createFboAttachments(vw))
        return kInvalidWindowId;

    WindowId id = m_nextWindowId++;
    m_virtualWindows[id] = vw;

    fprintf(stdout, "GlfwPlatform::createVirtualWindow: id=%u, %dx%d, fbo=%u, tex=%u\n",
            id, width, height, vw.fbo, vw.colorTex);
    return id;
}

void GlfwPlatform::destroyVirtualWindow(WindowId id)
{
    auto it = m_virtualWindows.find(id);
    if (it == m_virtualWindows.end())
        return;

    // If this was the active render target, clear it.
    if (m_renderTargetId == id)
        m_renderTargetId = kInvalidWindowId;

    deleteFboAttachments(it->second);
    m_virtualWindows.erase(it);
}

void GlfwPlatform::resizeVirtualWindow(WindowId id, int width, int height)
{
    auto it = m_virtualWindows.find(id);
    if (it == m_virtualWindows.end())
        return;
    if (width <= 0 || height <= 0)
        return;

    auto& vw = it->second;
    if (vw.width == width && vw.height == height)
        return;

    deleteFboAttachments(vw);
    vw.width = width;
    vw.height = height;

    if (!createFboAttachments(vw))
    {
        fprintf(stderr, "GlfwPlatform::resizeVirtualWindow: failed to recreate FBO %dx%d\n",
                width, height);
        m_virtualWindows.erase(it);
    }
}

// ---------------------------------------------------------------------------
// Window state
// ---------------------------------------------------------------------------

void GlfwPlatform::getWindowSize(WindowId id, int* width, int* height)
{
    if (id == m_mainWindowId && m_window)
    {
        glfwGetWindowSize(m_window, width, height);
        return;
    }

    // Check virtual windows
    auto it = m_virtualWindows.find(id);
    if (it != m_virtualWindows.end())
    {
        if (width)  *width  = it->second.width;
        if (height) *height = it->second.height;
        return;
    }

    if (width) *width = 0;
    if (height) *height = 0;
}

void GlfwPlatform::setWindowSize(WindowId id, int width, int height)
{
    if (id == m_mainWindowId && m_window)
        resizeGlfwWindow(m_window, width, height);
}

void GlfwPlatform::getWindowPosition(WindowId id, int* x, int* y)
{
    if (id == m_mainWindowId && m_window)
        glfwGetWindowPos(m_window, x, y);
    else
    {
        if (x) *x = 0;
        if (y) *y = 0;
    }
}

void GlfwPlatform::setWindowPosition(WindowId id, int x, int y)
{
    if (id == m_mainWindowId && m_window)
        glfwSetWindowPos(m_window, x, y);
}

std::string GlfwPlatform::getWindowTitle(WindowId id)
{
    if (id == m_mainWindowId && m_window)
#ifdef _WIN32
        return getWin32WindowTitle(glfwGetWin32Window(m_window));
#else
        return m_title;
#endif
    return {};
}

void GlfwPlatform::setWindowTitle(WindowId id, const char* title)
{
    if (id == m_mainWindowId && m_window && title)
    {
        // Keep GLFW's own title state synchronized on every platform.
        glfwSetWindowTitle(m_window, title);
#ifdef _WIN32
        // The standalone API must describe the real Win32 caption, not the
        // requested-value cache.  Apply the UTF-16 title to the HWND and force
        // a non-client repaint so visible desktop chrome changes immediately.
        if (setWin32WindowTitle(glfwGetWin32Window(m_window), title))
            m_title = title;
#else
        m_title = title;
#endif
    }
}

bool GlfwPlatform::isFullscreen(WindowId id)
{
    if (id == m_mainWindowId && m_window)
        return glfwGetWindowMonitor(m_window) != nullptr;
    return false;
}

void GlfwPlatform::setFullscreen(WindowId id, bool fullscreen)
{
    if (id != m_mainWindowId || !m_window)
        return;

    if (fullscreen)
    {
        GLFWmonitor* monitor = glfwGetPrimaryMonitor();
        const GLFWvidmode* mode = glfwGetVideoMode(monitor);
        glfwSetWindowMonitor(m_window, monitor, 0, 0, mode->width, mode->height, mode->refreshRate);
    }
    else
    {
        glfwSetWindowMonitor(m_window, nullptr, 100, 100, 1280, 720, 0);
    }
}

bool GlfwPlatform::isMaximized(WindowId id)
{
    if (id == m_mainWindowId && m_window)
        return glfwGetWindowAttrib(m_window, GLFW_MAXIMIZED) != 0;
    return false;
}

void GlfwPlatform::setMaximized(WindowId id, bool maximized)
{
    if (id != m_mainWindowId || !m_window)
        return;
    if (maximized)
        glfwMaximizeWindow(m_window);
    else
        glfwRestoreWindow(m_window);
}

bool GlfwPlatform::isFocused(WindowId id)
{
    if (id == m_mainWindowId && m_window)
        return glfwGetWindowAttrib(m_window, GLFW_FOCUSED) != 0;
    return false;
}

void GlfwPlatform::setFocused(WindowId id)
{
    if (id == m_mainWindowId && m_window)
        glfwFocusWindow(m_window);
}

bool GlfwPlatform::isVisible(WindowId id)
{
    if (id == m_mainWindowId && m_window)
        return glfwGetWindowAttrib(m_window, GLFW_VISIBLE) != 0;
    return false;
}

void GlfwPlatform::setVisible(WindowId id, bool visible)
{
    if (id != m_mainWindowId || !m_window)
        return;
    if (visible)
        glfwShowWindow(m_window);
    else
        glfwHideWindow(m_window);
}

bool GlfwPlatform::isFloating(WindowId id)
{
    if (id == m_mainWindowId && m_window)
        return glfwGetWindowAttrib(m_window, GLFW_FLOATING) != 0;
    return false;
}

void GlfwPlatform::setFloating(WindowId id, bool floating)
{
    if (id == m_mainWindowId && m_window)
        glfwSetWindowAttrib(m_window, GLFW_FLOATING, floating ? GLFW_TRUE : GLFW_FALSE);
}

void GlfwPlatform::setWindowIcon(WindowId id, const uint8_t* pixels, int width, int height)
{
    if (id != m_mainWindowId || !m_window || !pixels)
        return;

    GLFWimage image;
    image.width = width;
    image.height = height;
    image.pixels = const_cast<unsigned char*>(pixels);
    glfwSetWindowIcon(m_window, 1, &image);
}

void GlfwPlatform::requestClose(WindowId id)
{
    if (id == m_mainWindowId && m_window)
        glfwSetWindowShouldClose(m_window, GLFW_TRUE);
}

// ---------------------------------------------------------------------------
// DPI and scaling
// ---------------------------------------------------------------------------

float GlfwPlatform::getDpiScale(WindowId id)
{
    return getContentScale(id);
}

float GlfwPlatform::getContentScale(WindowId id)
{
#ifdef __APPLE__
    // On macOS, GLFW window coordinates are in logical pixels (points).
    // ImGui's DisplayFramebufferScale handles the Retina 2x rendering automatically.
    // The omni.ui widget system uses this scale to size margins and widget dimensions,
    // so returning 2.0 would double all layout values — we return 1.0 instead.
    return 1.0f;
#else
    if (id == m_mainWindowId && m_window)
    {
        float xscale = 1.0f, yscale = 1.0f;
        glfwGetWindowContentScale(m_window, &xscale, &yscale);
        return xscale; // Use horizontal scale as the primary DPI factor
    }
    return 1.0f;
#endif
}

// ---------------------------------------------------------------------------
// Cursor control
// ---------------------------------------------------------------------------

void GlfwPlatform::setCursorShape(int imguiCursorType)
{
    // ImGui handles cursor shape changes internally via the GLFW backend.
    // This is a manual override point if needed.
    (void)imguiCursorType;
}

void GlfwPlatform::setCursorVisible(bool visible)
{
    if (m_window)
    {
        glfwSetInputMode(m_window, GLFW_CURSOR,
                         visible ? GLFW_CURSOR_NORMAL : GLFW_CURSOR_HIDDEN);
    }
}

// ---------------------------------------------------------------------------
// Monitor info
// ---------------------------------------------------------------------------

int GlfwPlatform::getMonitorCount()
{
    int count = 0;
    glfwGetMonitors(&count);
    return count;
}

void GlfwPlatform::getMonitorWorkArea(int monitorIndex, int* x, int* y,
                                       int* width, int* height)
{
    int count = 0;
    GLFWmonitor** monitors = glfwGetMonitors(&count);
    if (monitorIndex >= 0 && monitorIndex < count)
    {
        glfwGetMonitorWorkarea(monitors[monitorIndex], x, y, width, height);
    }
    else
    {
        if (x) *x = 0;
        if (y) *y = 0;
        if (width) *width = 0;
        if (height) *height = 0;
    }
}

// ---------------------------------------------------------------------------
// Clipboard
// ---------------------------------------------------------------------------

std::string GlfwPlatform::getClipboard()
{
    if (m_window)
    {
        const char* text = glfwGetClipboardString(m_window);
        return text ? text : "";
    }
    return {};
}

void GlfwPlatform::setClipboard(const char* text)
{
    if (m_window && text)
        glfwSetClipboardString(m_window, text);
}

// ---------------------------------------------------------------------------
// Input injection
// ---------------------------------------------------------------------------

void GlfwPlatform::injectMouseMove(WindowId id, float x, float y)
{
    (void)id;
    ImGuiIO& io = ImGui::GetIO();
    io.MousePos = ImVec2(x, y);
}

void GlfwPlatform::injectMouseButton(WindowId id, MouseButton button, bool pressed)
{
    (void)id;
    int idx = static_cast<int>(button);
    if (idx >= 0 && idx < 5)
    {
        ImGuiIO& io = ImGui::GetIO();
        io.MouseDown[idx] = pressed;
    }
}

void GlfwPlatform::injectMouseScroll(WindowId id, float dx, float dy)
{
    (void)id;
    ImGuiIO& io = ImGui::GetIO();
    io.MouseWheelH += dx;
    io.MouseWheel += dy;
}

void GlfwPlatform::injectKeyEvent(WindowId id, int imguiKey, bool pressed,
                                   KeyboardModifierFlags modifiers)
{
    (void)id;
    ImGuiIO& io = ImGui::GetIO();
    const ImGuiKey key = detail::normalizeInjectedImguiKey(imguiKey);
    if (key != ImGuiKey_None)
        io.AddKeyEvent(key, pressed);

    io.AddKeyEvent(ImGuiMod_Ctrl,  (modifiers & kKeyModCtrl) != 0);
    io.AddKeyEvent(ImGuiMod_Shift, (modifiers & kKeyModShift) != 0);
    io.AddKeyEvent(ImGuiMod_Alt,   (modifiers & kKeyModAlt) != 0);
    io.AddKeyEvent(ImGuiMod_Super, (modifiers & kKeyModSuper) != 0);
}

void GlfwPlatform::injectCharEvent(WindowId id, uint32_t codepoint)
{
    (void)id;
    ImGuiIO& io = ImGui::GetIO();
    io.AddInputCharacter(codepoint);
}

void GlfwPlatform::setInputBlocking(bool blocked)
{
    m_inputBlocked = blocked;
}

// ---------------------------------------------------------------------------
// Deferred operations
// ---------------------------------------------------------------------------

DeferHandle GlfwPlatform::deferToEndOfFrame(std::function<void()> callback, int32_t priority)
{
    auto token = std::make_shared<int>(1); // arbitrary non-null shared_ptr
    {
        std::lock_guard<std::mutex> lock(m_deferMutex);
        m_deferredQueue.push_back({token, std::move(callback), priority, false});
    }
    return token;
}

DeferHandle GlfwPlatform::observeEndOfFrame(std::function<void()> callback, int32_t priority)
{
    auto token = std::make_shared<int>(1);
    {
        std::lock_guard<std::mutex> lock(m_deferMutex);
        m_deferredQueue.push_back({token, std::move(callback), priority, true});
    }
    return token;
}

void GlfwPlatform::drainDeferredQueue()
{
    // Snapshot the queue under lock, then execute outside the lock.
    std::vector<DeferredEntry> snapshot;
    {
        std::lock_guard<std::mutex> lock(m_deferMutex);
        snapshot = m_deferredQueue;
        // Remove one-shot entries; keep persistent observers
        m_deferredQueue.erase(
            std::remove_if(m_deferredQueue.begin(), m_deferredQueue.end(),
                           [](const DeferredEntry& e) { return !e.persistent; }),
            m_deferredQueue.end());
        // Remove cancelled entries (expired tokens)
        m_deferredQueue.erase(
            std::remove_if(m_deferredQueue.begin(), m_deferredQueue.end(),
                           [](const DeferredEntry& e) { return e.cancelToken.expired(); }),
            m_deferredQueue.end());
    }

    // Sort by priority (lower first)
    std::sort(snapshot.begin(), snapshot.end(),
              [](const DeferredEntry& a, const DeferredEntry& b) {
                  return a.priority < b.priority;
              });

    // Execute
    for (auto& entry : snapshot)
    {
        if (!entry.cancelToken.expired() && entry.callback)
        {
            entry.callback();
        }
    }
}

// ---------------------------------------------------------------------------
// Run loop
// ---------------------------------------------------------------------------

bool GlfwPlatform::tick()
{
    // The standalone pump executes this native UI frame synchronously on the UI thread.
    OVUI_DEVELOPMENT_TIME_SCOPE(frameScope, "GlfwPlatform.tick [ovui debug]");
    if (!m_window)
        return false;

#ifdef OMNIUI_HAS_VULKAN
    if (m_backendType == BackendType::eVulkan)
    {
        beginNativeFramePacingUiUpdate(m_vulkanBackend.get());
        // Until this frame's draw data is submitted, it can reference textures
        // that are released while it is built, so those releases wait.
        m_vulkanBackend->beginFrameReleases();
    }
#endif

    // Determine if we are rendering to a virtual window's FBO.
    VirtualWindowInfo* vwTarget = nullptr;
    if (m_renderTargetId != kInvalidWindowId)
    {
        auto it = m_virtualWindows.find(m_renderTargetId);
        if (it != m_virtualWindows.end())
            vwTarget = &it->second;
    }

    // 1. Poll events (still needed even in headless mode for GL context pump)
    {
        OVUI_DEVELOPMENT_TIME_SCOPE(pollEventsScope, "GlfwPlatform.pollEvents [ovui debug]");
        // On X11 the poll reads the connection only while Xlib's queue is
        // empty. A round trip later in the previous tick (a window size or
        // focus query) can leave older events queued, and the newest input
        // then waits a whole tick. A round trip here (XQueryPointer) queues
        // every event the server has sent, so this poll handles all of them.
        double cursorX = 0.0, cursorY = 0.0;
        glfwGetCursorPos(m_window, &cursorX, &cursorY);
        glfwPollEvents();
    }

    // 2. Start new ImGui frame
    {
        OVUI_DEVELOPMENT_TIME_SCOPE(backendNewFrameScope, "GlfwPlatform.backendNewFrame [ovui debug]");
#ifdef OMNIUI_HAS_VULKAN
        if (m_backendType == BackendType::eVulkan)
        {
            ImGui_ImplVulkan_NewFrame();
        }
        else
#endif
        {
            ImGui_ImplOpenGL3_NewFrame();
        }
        ImGui_ImplGlfw_NewFrame();
    }

    // Apply any programmatically injected input AFTER the GLFW backend
    // has set IO from real events, so our injected values take precedence.
    {
        applyInjectedInput();
    }

    // When rendering to a virtual window, override the display size so ImGui
    // lays out to the FBO dimensions rather than the GLFW window dimensions.
    if (vwTarget)
    {
        ImGuiIO& io = ImGui::GetIO();
        io.DisplaySize = ImVec2(static_cast<float>(vwTarget->width),
                                static_cast<float>(vwTarget->height));
        io.DisplayFramebufferScale = ImVec2(1.0f, 1.0f);
    }

    {
        ImGui::NewFrame();
    }

    // 3. Draw all omni.ui windows
    {
        // Image changes given from other threads run on this thread before the draw.
        omni::ui::ImageProvider::applyPublishedUpdates();

        // Compute elapsed time since last frame
        static auto s_lastTime = std::chrono::steady_clock::now();
        auto now = std::chrono::steady_clock::now();
        float elapsed = std::chrono::duration<float>(now - s_lastTime).count();
        s_lastTime = now;

        StandaloneWindowCallbackManager* wcm = getStandaloneWindowCallbackManager();
        if (wcm)
        {
            OVUI_DEVELOPMENT_TIME_SCOPE(drawWindowsScope, "GlfwPlatform.drawAllWindows [ovui debug]");
            wcm->drawAllWindows(elapsed);
        }
    }

    // 4. Render ImGui
    {
        ImGui::Render();
        // A presentation key without a drawable must not reach the renderer back end.
        omni::ui::dropUnmappedPresentationKeys(ImGui::GetDrawData());
    }

    // 5. Render backend-specific
#ifdef OMNIUI_HAS_VULKAN
    if (m_backendType == BackendType::eVulkan)
    {
        int display_w, display_h;
        glfwGetFramebufferSize(m_window, &display_w, &display_h);
        uint64_t pacingGeneration = 0;
        bool paced = false;
        if (!m_vulkanBackend->usesFastPresentationMode())
        {
            paced = submitNativeFramePacingDrawData(
                m_vulkanBackend.get(), ImGui::GetDrawData(), display_w, display_h,
                &pacingGeneration, static_cast<bool>(m_preSwapCallback));
        }
        if (!paced && display_w > 0 && display_h > 0)
        {
            VulkanBackend::WindowPresentResult prepared =
                VulkanBackend::WindowPresentResult::eDeferred;
            uint32_t swapchainImage = 0;
            {
                std::lock_guard<std::mutex> queueLock(m_vulkanBackend->getQueueMutex());
                if (m_vulkanBackend->beginFrame(display_w, display_h))
                {
                    ImGui_ImplVulkan_RenderDrawData(
                        ImGui::GetDrawData(), m_vulkanBackend->getCommandBuffer());
                    if (m_vulkanBackend->endFrame())
                    {
                        prepared = m_vulkanBackend->prepareWindowFrame(
                            display_w, display_h, &swapchainImage);
                    }
                }
            }
            VulkanBackend::WindowPresentResult presented = VulkanBackend::WindowPresentResult::eDeferred;
            if (prepared == VulkanBackend::WindowPresentResult::ePrepared)
            {
                // Presentation can block on vsync or a slow display. It touches
                // no Python state, so a host may let other threads run.
                PresentWaitScope presentWait;
                presented = m_vulkanBackend->presentWindowFrame(swapchainImage);
            }
            if (prepared == VulkanBackend::WindowPresentResult::ePrepared &&
                presented == VulkanBackend::WindowPresentResult::eFailed)
            {
                fprintf(stderr, "GlfwPlatform: Vulkan window presentation failed\n");
            }
            else if (prepared == VulkanBackend::WindowPresentResult::eFailed)
            {
                fprintf(stderr, "GlfwPlatform: Vulkan window preparation failed\n");
            }
        }

        IByteImageGpu* byteImageGpu = PlatformRegistry::instance().byteImageGpu();
        if (byteImageGpu != nullptr)
        {
            VulkanByteImageGpu* vulkanByteImageGpu = static_cast<VulkanByteImageGpu*>(byteImageGpu);
            vulkanByteImageGpu->drainDeferredDestructions();
        }

        // Drain deferred queue
        {
            drainDeferredQueue();
        }

        m_vulkanBackend->endFrameReleases();

        // Pre-swap callback (used by screenshot capture)
        if (m_preSwapCallback)
        {
            if (paced)
            {
                waitNativeFramePacingPresentation(pacingGeneration, 500'000'000);
            }
            auto cb = std::move(m_preSwapCallback);
            m_preSwapCallback = nullptr;
            cb();
        }
    }
    else
#endif
    {
        // Bind FBO if rendering to virtual window
        {
            if (vwTarget)
            {
                glBindFramebuffer(GL_FRAMEBUFFER, vwTarget->fbo);
                glViewport(0, 0, vwTarget->width, vwTarget->height);
            }
            else
            {
                int display_w, display_h;
                glfwGetFramebufferSize(m_window, &display_w, &display_h);
                glViewport(0, 0, display_w, display_h);
            }
        }

        // Read the cleared-viewport color from ImGui's BASE
        // ``ImGuiCol_WindowBg``. Apps that style ``MainFrame`` write
        // their preferred dark shade into this base (see
        // MainWindow::_draw); apps that don't get the legacy default.
        // Without sourcing the clear color from the style, any tiny
        // gap between widgets (e.g. between the MainMenuBar's
        // auto-sized BeginMainMenuBar window and the host
        // ``Begin("DockSpace")`` window) shows a constant gray-blue
        // that doesn't blend with the application's chrome.
        {
            ImVec4 wbg = ImGui::GetStyleColorVec4(ImGuiCol_WindowBg);
            if (wbg.w <= 0.0f) {
                wbg = ImVec4(0.12f, 0.13f, 0.14f, 1.0f);
            }
            glClearColor(wbg.x, wbg.y, wbg.z, wbg.w);
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        }
        {
            ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
        }

        // Drain deferred queue (while FBO is still bound for virtual windows)
        {
            drainDeferredQueue();
        }

        // Pre-swap callback (used by screenshot capture)
        if (m_preSwapCallback)
        {
            auto cb = std::move(m_preSwapCallback);
            m_preSwapCallback = nullptr;
            cb();
        }

        if (vwTarget)
        {
            // Unbind FBO — rendering is complete, texture is ready for consumption.
            glBindFramebuffer(GL_FRAMEBUFFER, 0);
            // No swap — there is no on-screen window for virtual targets.
        }
        else
        {
            // The swap can block for a long time on vsync or a slow display.
            // It touches no Python state, so a host may let other threads run.
            PresentWaitScope presentWait;
            glfwSwapBuffers(m_window);
        }
    }

    return !glfwWindowShouldClose(m_window);
}

bool GlfwPlatform::shouldClose()
{
    if (!m_window)
        return true;
    return glfwWindowShouldClose(m_window) != 0;
}

// ---------------------------------------------------------------------------
// Busy state
// ---------------------------------------------------------------------------

void GlfwPlatform::setBusy(bool busy)
{
    m_busy = busy;
    // Could set a wait cursor here in the future
}

// ---------------------------------------------------------------------------
// Framebuffer access
// ---------------------------------------------------------------------------

uint64_t GlfwPlatform::getFramebufferTexture(WindowId id)
{
    auto it = m_virtualWindows.find(id);
    if (it != m_virtualWindows.end())
        return static_cast<uint64_t>(it->second.colorTex);
    return 0;
}

// ---------------------------------------------------------------------------
// App window management (multi-window support)
// ---------------------------------------------------------------------------

AppWindowHandle GlfwPlatform::getDefaultAppWindowHandle()
{
    return static_cast<AppWindowHandle>(m_window);
}

AppWindowHandle GlfwPlatform::createDetachedAppWindow(const char* /*title*/, int /*x*/, int /*y*/, int /*w*/, int /*h*/)
{
    // Standalone does not support detached OS windows.
    return nullptr;
}

bool GlfwPlatform::isMultiWindowSupported()
{
    return false;
}

bool GlfwPlatform::isAppRunning()
{
    return !shouldClose();
}

bool GlfwPlatform::isAppWindowVirtual(AppWindowHandle window)
{
    // Virtual windows don't have an AppWindowHandle (they have no OS window).
    // If the handle doesn't match the GLFW window, it could be virtual.
    (void)window;
    return false;
}

Int2 GlfwPlatform::getAppWindowCursorPosition(AppWindowHandle /*window*/)
{
    Int2 result = {};
    if (m_window)
    {
        double xpos = 0.0, ypos = 0.0;
        glfwGetCursorPos(m_window, &xpos, &ypos);
        result.x = static_cast<int>(xpos);
        result.y = static_cast<int>(ypos);
    }
    return result;
}

Int2 GlfwPlatform::getAppWindowOsPosition(AppWindowHandle /*window*/)
{
    Int2 result = {};
    if (m_window)
    {
        glfwGetWindowPos(m_window, &result.x, &result.y);
    }
    return result;
}

void GlfwPlatform::setAppWindowOsPosition(AppWindowHandle /*window*/, int x, int y)
{
    if (m_window)
    {
        glfwSetWindowPos(m_window, x, y);
    }
}

void GlfwPlatform::resizeAppWindow(AppWindowHandle /*window*/, int w, int h)
{
    setWindowSize(m_mainWindowId, w, h);
}

void GlfwPlatform::getAppWindowSize(AppWindowHandle /*window*/, int* width, int* height)
{
    getWindowSize(m_mainWindowId, width, height);
}

bool GlfwPlatform::isMouseInputBlocked(AppWindowHandle /*window*/)
{
    return false;
}

bool GlfwPlatform::getAppWindowCursorBlink(AppWindowHandle /*window*/)
{
    return true;
}

DeferHandle GlfwPlatform::deferDestroyAppWindow(AppWindowHandle /*window*/)
{
    // No-op: standalone has a single window, deferred destruction not needed.
    return {};
}

DeferHandle GlfwPlatform::observeAppWindowClose(AppWindowHandle /*window*/, std::function<void()> /*callback*/)
{
    // No-op: standalone has a single window; close is handled via shouldClose().
    return {};
}

float GlfwPlatform::getAppWindowDpiScale(AppWindowHandle /*window*/)
{
    return getDpiScale(m_mainWindowId);
}

bool GlfwPlatform::needsStrongWindowRefs() const
{
    return true;
}

} // namespace standalone
} // namespace ui
} // namespace omni

#include "ImGuiKeyTranslation.h"
int omni::ui::standalone::GlfwPlatform::nativeKeyCode(int key) const
{
    return detail::imguiKeyToGlfwKey(static_cast<ImGuiKey>(key));
}
