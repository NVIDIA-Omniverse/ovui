/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include "WebPlatform.h"

#include "../../standalone/src/StandaloneGlyphManager.h"
#include "../../standalone/src/StandaloneLog.h"
#include "../../standalone/src/StandaloneSettings.h"
#include "../../standalone/src/StandaloneWindowCallbackManager.h"

#include <omni/ui/Workspace.h>
#include <omni/ui/platform/IUiFileIO.h>
#include <omni/ui/platform/IUiPlatform.h>
#include <omni/ui/platform/IUiRenderer.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>
#include <emscripten/html5.h>
#include <imgui.h>
#include <imgui_internal.h>
#include <backends/imgui_impl_opengl3.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace omni {
namespace ui {
namespace web {
namespace {

constexpr WindowId kMainWindowId = 1;
constexpr const char* kFontPath = "/assets/fonts/NotoSans-Regular.ttf";

class WebFileIO final : public IUiFileIO
{
public:
    std::vector<uint8_t> readFile(const char* path) override
    {
        std::string resolved = resolvePath(path);
        std::ifstream file(resolved, std::ios::binary | std::ios::ate);
        if (!file.is_open())
            return {};

        std::streamsize size = file.tellg();
        if (size <= 0)
            return {};

        file.seekg(0, std::ios::beg);
        std::vector<uint8_t> data(static_cast<size_t>(size));
        if (!file.read(reinterpret_cast<char*>(data.data()), size))
            return {};
        return data;
    }

    bool fileExists(const char* path) override
    {
        std::ifstream file(resolvePath(path), std::ios::binary);
        return file.good();
    }

    uint64_t getModTime(const char* /*path*/) override
    {
        return 0;
    }

    std::string resolvePath(const char* tokenPath) override
    {
        if (!tokenPath)
            return {};

        std::string path(tokenPath);
        replaceAll(path, "${fonts}", "/assets/fonts/");
        replaceAll(path, "${glyphs}", "/assets/glyphs/");
        replaceAll(path, "${icons}", "/assets/icons/");
        replaceAll(path, "${styles}", "/assets/styles/");
        return path;
    }

    void readFileAsync(const char* path, ReadFileCallback callback) override
    {
        if (callback)
            callback(readFile(path));
    }

    ImageData decodeImage(const uint8_t* /*data*/, size_t /*size*/) override
    {
        return {};
    }

private:
    static void replaceAll(std::string& text, const std::string& needle, const std::string& replacement)
    {
        size_t pos = 0;
        while ((pos = text.find(needle, pos)) != std::string::npos)
        {
            text.replace(pos, needle.size(), replacement);
            pos += replacement.size();
        }
    }
};

class WebRenderer final : public IUiRenderer
{
public:
    ~WebRenderer() override
    {
        for (auto& item : m_textures)
        {
            GLuint texture = static_cast<GLuint>(item.first);
            glDeleteTextures(1, &texture);
        }
    }

    TextureHandle createTexture(int width, int height, TextureFormat format, const void* data) override
    {
        GLuint texture = 0;
        glGenTextures(1, &texture);
        if (!texture)
            return kInvalidTexture;

        glBindTexture(GL_TEXTURE_2D, texture);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

        GLenum internalFormat = GL_RGBA;
        GLenum uploadFormat = GL_RGBA;
        if (format == TextureFormat::eR8)
        {
            internalFormat = GL_LUMINANCE;
            uploadFormat = GL_LUMINANCE;
        }

        glTexImage2D(GL_TEXTURE_2D, 0, internalFormat, width, height, 0, uploadFormat, GL_UNSIGNED_BYTE, data);
        glBindTexture(GL_TEXTURE_2D, 0);

        TextureHandle handle = static_cast<TextureHandle>(texture);
        m_textures[handle] = { width, height, format };
        return handle;
    }

    void updateTexture(TextureHandle handle, const void* data, size_t /*size*/) override
    {
        if (handle == kInvalidTexture || !data)
            return;

        auto it = m_textures.find(handle);
        if (it == m_textures.end())
            return;

        const TextureInfo& info = it->second;
        GLenum uploadFormat = info.format == TextureFormat::eR8 ? GL_LUMINANCE : GL_RGBA;
        glBindTexture(GL_TEXTURE_2D, static_cast<GLuint>(handle));
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, info.width, info.height, uploadFormat, GL_UNSIGNED_BYTE, data);
        glBindTexture(GL_TEXTURE_2D, 0);
    }

    void destroyTexture(TextureHandle handle) override
    {
        if (handle == kInvalidTexture)
            return;

        m_textures.erase(handle);
        GLuint texture = static_cast<GLuint>(handle);
        glDeleteTextures(1, &texture);
    }

    void* getImGuiTextureId(TextureHandle handle) override
    {
        return reinterpret_cast<void*>(static_cast<intptr_t>(handle));
    }

    TextureHandle uploadFontAtlas(const unsigned char* pixels, int width, int height) override
    {
        if (m_fontAtlas != kInvalidTexture)
            destroyTexture(m_fontAtlas);
        m_fontAtlas = createTexture(width, height, TextureFormat::eRGBA8, pixels);
        return m_fontAtlas;
    }

    void beginFrame() override {}
    void endFrame() override {}

private:
    struct TextureInfo
    {
        int width = 0;
        int height = 0;
        TextureFormat format = TextureFormat::eRGBA8;
    };

    std::unordered_map<TextureHandle, TextureInfo> m_textures;
    TextureHandle m_fontAtlas = kInvalidTexture;
};

standalone::StandaloneWindowCallbackManager* windowCallbackManager();

class WebPlatform final : public IUiPlatform
{
public:
    explicit WebPlatform(std::string canvasSelector)
        : m_canvasSelector(std::move(canvasSelector))
        , m_appWindowHandle(static_cast<AppWindowHandle>(this))
    {
    }

    ~WebPlatform() override
    {
        destroyWindow(kMainWindowId);
    }

    WindowId createWindow(const char* title, int width, int height) override
    {
        if (m_context)
            return kMainWindowId;

        m_title = title ? title : "omni.ui";
        setCanvasSize(width, height, m_devicePixelRatio);

        EmscriptenWebGLContextAttributes attrs;
        emscripten_webgl_init_context_attributes(&attrs);
        attrs.alpha = EM_FALSE;
        attrs.depth = EM_TRUE;
        attrs.stencil = EM_TRUE;
        attrs.antialias = EM_TRUE;
        attrs.majorVersion = 1;
        attrs.minorVersion = 0;
        attrs.enableExtensionsByDefault = EM_TRUE;

        m_context = emscripten_webgl_create_context(m_canvasSelector.c_str(), &attrs);
        if (m_context <= 0)
        {
            fprintf(stderr, "ovui web: failed to create WebGL context for %s\n", m_canvasSelector.c_str());
            m_context = 0;
            return kInvalidWindowId;
        }

        emscripten_webgl_make_context_current(m_context);

        IMGUI_CHECKVERSION();
        ImGui::CreateContext();
        ImGuiIO& io = ImGui::GetIO();
        io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
        io.ConfigFlags |= ImGuiConfigFlags_DockingEnable;
        io.BackendPlatformName = "ovui_web_cpython";

        installEventCallbacks();
        loadFonts();

        ImGui::StyleColorsDark();
        ImGuiStyle& style = ImGui::GetStyle();
        style.WindowPadding = ImVec2(10.0f, 10.0f);
        style.FramePadding = ImVec2(8.0f, 5.0f);
        style.ItemSpacing = ImVec2(8.0f, 8.0f);
        style.WindowRounding = 4.0f;
        style.FrameRounding = 4.0f;
        style.GrabRounding = 4.0f;
        style.WindowBorderSize = 1.0f;

        ImGui_ImplOpenGL3_Init("#version 100");
        m_lastFrameTime = std::chrono::steady_clock::now();
        return kMainWindowId;
    }

    void destroyWindow(WindowId id) override
    {
        if (id != kMainWindowId || !m_context)
            return;

        ImGui_ImplOpenGL3_Shutdown();
        if (ImGui::GetCurrentContext())
            ImGui::DestroyContext();
        emscripten_webgl_destroy_context(m_context);
        m_context = 0;
    }

    WindowId createVirtualWindow(int /*width*/, int /*height*/) override { return kInvalidWindowId; }
    void destroyVirtualWindow(WindowId /*id*/) override {}
    void resizeVirtualWindow(WindowId /*id*/, int /*width*/, int /*height*/) override {}

    void getWindowSize(WindowId id, int* width, int* height) override
    {
        if (id == kMainWindowId)
        {
            if (width) *width = m_logicalWidth;
            if (height) *height = m_logicalHeight;
            return;
        }
        if (width) *width = 0;
        if (height) *height = 0;
    }

    void setWindowSize(WindowId id, int width, int height) override
    {
        if (id != kMainWindowId)
            return;
        setCanvasSize(width, height, m_devicePixelRatio);
    }

    void getWindowPosition(WindowId /*id*/, int* x, int* y) override
    {
        if (x) *x = 0;
        if (y) *y = 0;
    }

    void setWindowPosition(WindowId /*id*/, int /*x*/, int /*y*/) override {}
    std::string getWindowTitle(WindowId /*id*/) override { return m_title; }
    void setWindowTitle(WindowId /*id*/, const char* title) override { m_title = title ? title : ""; }
    bool isFullscreen(WindowId /*id*/) override { return false; }
    void setFullscreen(WindowId /*id*/, bool /*fullscreen*/) override {}
    bool isMaximized(WindowId /*id*/) override { return false; }
    void setMaximized(WindowId /*id*/, bool /*maximized*/) override {}
    bool isFocused(WindowId /*id*/) override { return true; }
    void setFocused(WindowId /*id*/) override {}
    bool isVisible(WindowId /*id*/) override { return true; }
    void setVisible(WindowId /*id*/, bool /*visible*/) override {}
    bool isFloating(WindowId /*id*/) override { return false; }
    void setFloating(WindowId /*id*/, bool /*floating*/) override {}
    void setWindowIcon(WindowId /*id*/, const uint8_t* /*pixels*/, int /*width*/, int /*height*/) override {}
    void requestClose(WindowId /*id*/) override { m_closeRequested = true; }
    float getDpiScale(WindowId /*id*/) override { return 1.0f; }
    float getContentScale(WindowId /*id*/) override { return m_devicePixelRatio; }
    void setCursorShape(int /*imguiCursorType*/) override {}
    void setCursorVisible(bool /*visible*/) override {}
    int getMonitorCount() override { return 1; }
    void getMonitorWorkArea(int /*monitorIndex*/, int* x, int* y, int* width, int* height) override
    {
        if (x) *x = 0;
        if (y) *y = 0;
        if (width) *width = m_logicalWidth;
        if (height) *height = m_logicalHeight;
    }

    std::string getClipboard() override { return m_clipboard; }
    void setClipboard(const char* text) override { m_clipboard = text ? text : ""; }

    void injectMouseMove(WindowId /*id*/, float x, float y) override
    {
        if (ImGui::GetCurrentContext())
            ImGui::GetIO().AddMousePosEvent(x, y);
    }

    void injectMouseButton(WindowId /*id*/, MouseButton button, bool pressed) override
    {
        if (ImGui::GetCurrentContext())
            ImGui::GetIO().AddMouseButtonEvent(static_cast<int>(button), pressed);
    }

    void injectMouseScroll(WindowId /*id*/, float dx, float dy) override
    {
        if (ImGui::GetCurrentContext())
            ImGui::GetIO().AddMouseWheelEvent(dx, dy);
    }

    void injectKeyEvent(WindowId /*id*/, int imguiKey, bool pressed, KeyboardModifierFlags modifiers) override
    {
        if (!ImGui::GetCurrentContext())
            return;
        ImGuiIO& io = ImGui::GetIO();
        if (imguiKey > ImGuiKey_None && imguiKey < ImGuiKey_NamedKey_END)
            io.AddKeyEvent(static_cast<ImGuiKey>(imguiKey), pressed);
        applyModifiers(io, modifiers);
    }

    void injectCharEvent(WindowId /*id*/, uint32_t codepoint) override
    {
        if (ImGui::GetCurrentContext())
            ImGui::GetIO().AddInputCharacter(codepoint);
    }

    void setInputBlocking(bool blocked) override { m_inputBlocked = blocked; }

    DeferHandle deferToEndOfFrame(std::function<void()> callback, int32_t priority) override
    {
        return addDeferred(std::move(callback), priority, false);
    }

    DeferHandle observeEndOfFrame(std::function<void()> callback, int32_t priority) override
    {
        return addDeferred(std::move(callback), priority, true);
    }

    bool tick() override
    {
        if (!m_context || !ImGui::GetCurrentContext())
            return false;

        emscripten_webgl_make_context_current(m_context);
        emscripten_get_canvas_element_size(m_canvasSelector.c_str(), &m_framebufferWidth, &m_framebufferHeight);
        m_framebufferWidth = std::max(1, m_framebufferWidth);
        m_framebufferHeight = std::max(1, m_framebufferHeight);

        auto now = std::chrono::steady_clock::now();
        float elapsed = std::chrono::duration<float>(now - m_lastFrameTime).count();
        if (elapsed <= 0.0f)
            elapsed = 1.0f / 60.0f;
        m_lastFrameTime = now;

        ImGuiIO& io = ImGui::GetIO();
        io.DisplaySize = ImVec2(static_cast<float>(m_logicalWidth), static_cast<float>(m_logicalHeight));
        io.DisplayFramebufferScale = ImVec2(static_cast<float>(m_framebufferWidth) / static_cast<float>(m_logicalWidth),
                                            static_cast<float>(m_framebufferHeight) / static_cast<float>(m_logicalHeight));
        if (ImGuiViewport* viewport = ImGui::GetMainViewport())
            viewport->FramebufferScale = io.DisplayFramebufferScale;
        io.DeltaTime = elapsed;

        ImGui_ImplOpenGL3_NewFrame();
        ImGui::NewFrame();

        if (auto* wcm = windowCallbackManager())
            wcm->drawAllWindows(elapsed);

        ImGui::Render();
        glViewport(0, 0, m_framebufferWidth, m_framebufferHeight);
        ImVec4 bg = ImGui::GetStyleColorVec4(ImGuiCol_WindowBg);
        glClearColor(bg.x, bg.y, bg.z, bg.w);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
        drainDeferred();
        return !m_closeRequested;
    }

    bool shouldClose() override { return m_closeRequested; }
    void setBusy(bool /*busy*/) override {}
    uint64_t getFramebufferTexture(WindowId /*id*/) override { return kInvalidTexture; }
    AppWindowHandle getDefaultAppWindowHandle() override { return m_appWindowHandle; }
    AppWindowHandle createDetachedAppWindow(const char* /*title*/, int /*x*/, int /*y*/, int /*w*/, int /*h*/) override { return nullptr; }
    bool isMultiWindowSupported() override { return false; }
    bool isAppRunning() override { return !m_closeRequested; }
    bool isAppWindowVirtual(AppWindowHandle /*window*/) override { return false; }
    Int2 getAppWindowCursorPosition(AppWindowHandle /*window*/) override { return { m_mouseX, m_mouseY }; }
    Int2 getAppWindowOsPosition(AppWindowHandle /*window*/) override { return {}; }
    void setAppWindowOsPosition(AppWindowHandle /*window*/, int /*x*/, int /*y*/) override {}
    void resizeAppWindow(AppWindowHandle /*window*/, int w, int h) override { setCanvasSize(w, h, m_devicePixelRatio); }
    void getAppWindowSize(AppWindowHandle /*window*/, int* width, int* height) override { getWindowSize(kMainWindowId, width, height); }
    bool isMouseInputBlocked(AppWindowHandle /*window*/) override { return m_inputBlocked; }
    bool getAppWindowCursorBlink(AppWindowHandle /*window*/) override { return true; }
    DeferHandle deferDestroyAppWindow(AppWindowHandle /*window*/) override { return {}; }
    DeferHandle observeAppWindowClose(AppWindowHandle /*window*/, std::function<void()> /*callback*/) override { return {}; }
    float getAppWindowDpiScale(AppWindowHandle /*window*/) override { return 1.0f; }
    bool needsStrongWindowRefs() const override { return true; }

    bool setCanvasSize(int width, int height, float devicePixelRatio)
    {
        m_logicalWidth = std::max(1, width);
        m_logicalHeight = std::max(1, height);
        m_devicePixelRatio = std::max(1.0f, devicePixelRatio);
        m_framebufferWidth = std::max(1, static_cast<int>(std::lround(static_cast<float>(m_logicalWidth) * m_devicePixelRatio)));
        m_framebufferHeight = std::max(1, static_cast<int>(std::lround(static_cast<float>(m_logicalHeight) * m_devicePixelRatio)));
        return emscripten_set_canvas_element_size(m_canvasSelector.c_str(), m_framebufferWidth, m_framebufferHeight) ==
               EMSCRIPTEN_RESULT_SUCCESS;
    }

    const std::string& fontInfo() const { return m_fontInfo; }

    std::string dpiInfo() const
    {
        if (!ImGui::GetCurrentContext())
            return "dpi: backend not initialized";

        const ImGuiIO& io = ImGui::GetIO();
        const ImGuiContext& context = *ImGui::GetCurrentContext();
        const ImFont* font = io.FontDefault ? io.FontDefault : context.Font;
        float fontDensity = font ? font->CurrentRasterizerDensity : 0.0f;
        float bakedSize = 0.0f;
        float bakedDensity = 0.0f;
        if (font && context.FontSize > 0.0f)
        {
            ImFontBaked* baked = const_cast<ImFont*>(font)->GetFontBaked(context.FontSize);
            if (baked)
            {
                bakedSize = baked->Size;
                bakedDensity = baked->RasterizerDensity;
            }
        }

        char buffer[512];
        std::snprintf(buffer, sizeof(buffer),
                      "dpi: logical=%dx%d framebuffer=%dx%d device_pixel_ratio=%.3f "
                      "display_framebuffer_scale=%.3fx%.3f content_scale=%.3f workspace_dpi_scale=1.000 "
                      "font_rasterizer_density=%.3f current_font_density=%.3f baked_size=%.3f baked_density=%.3f",
                      m_logicalWidth, m_logicalHeight, m_framebufferWidth, m_framebufferHeight, m_devicePixelRatio,
                      io.DisplayFramebufferScale.x, io.DisplayFramebufferScale.y, m_devicePixelRatio,
                      context.FontRasterizerDensity, fontDensity, bakedSize, bakedDensity);
        return buffer;
    }

    EM_BOOL onMouse(int eventType, const EmscriptenMouseEvent* event)
    {
        if (!event || !ImGui::GetCurrentContext())
            return EM_FALSE;

        ImGuiIO& io = ImGui::GetIO();
        m_mouseX = event->targetX;
        m_mouseY = event->targetY;
        io.AddMousePosEvent(static_cast<float>(m_mouseX), static_cast<float>(m_mouseY));

        if (eventType == EMSCRIPTEN_EVENT_MOUSEDOWN || eventType == EMSCRIPTEN_EVENT_MOUSEUP)
        {
            int button = mapMouseButton(event->button);
            if (button >= 0)
                io.AddMouseButtonEvent(button, eventType == EMSCRIPTEN_EVENT_MOUSEDOWN);
        }

        return io.WantCaptureMouse ? EM_TRUE : EM_FALSE;
    }

    EM_BOOL onWheel(const EmscriptenWheelEvent* event)
    {
        if (!event || !ImGui::GetCurrentContext())
            return EM_FALSE;
        ImGui::GetIO().AddMouseWheelEvent(0.0f, static_cast<float>(-event->deltaY / 100.0));
        return ImGui::GetIO().WantCaptureMouse ? EM_TRUE : EM_FALSE;
    }

    EM_BOOL onKey(int eventType, const EmscriptenKeyboardEvent* event)
    {
        if (!event || !ImGui::GetCurrentContext())
            return EM_FALSE;

        ImGuiIO& io = ImGui::GetIO();
        applyModifiers(io, event);
        ImGuiKey key = mapKey(event->key);
        if (key != ImGuiKey_None)
            io.AddKeyEvent(key, eventType == EMSCRIPTEN_EVENT_KEYDOWN);

        if (eventType == EMSCRIPTEN_EVENT_KEYDOWN && isPrintableInput(event))
            io.AddInputCharactersUTF8(event->key);

        return io.WantCaptureKeyboard ? EM_TRUE : EM_FALSE;
    }

private:
    struct DeferredEntry
    {
        std::weak_ptr<void> cancelToken;
        std::function<void()> callback;
        int32_t priority = 0;
        bool persistent = false;
    };

    static int mapMouseButton(int button)
    {
        if (button == 0)
            return ImGuiMouseButton_Left;
        if (button == 1)
            return ImGuiMouseButton_Middle;
        if (button == 2)
            return ImGuiMouseButton_Right;
        return -1;
    }

    static void applyModifiers(ImGuiIO& io, KeyboardModifierFlags modifiers)
    {
        io.AddKeyEvent(ImGuiMod_Ctrl, (modifiers & kKeyModCtrl) != 0);
        io.AddKeyEvent(ImGuiMod_Shift, (modifiers & kKeyModShift) != 0);
        io.AddKeyEvent(ImGuiMod_Alt, (modifiers & kKeyModAlt) != 0);
        io.AddKeyEvent(ImGuiMod_Super, (modifiers & kKeyModSuper) != 0);
    }

    static void applyModifiers(ImGuiIO& io, const EmscriptenKeyboardEvent* event)
    {
        io.AddKeyEvent(ImGuiMod_Ctrl, event->ctrlKey);
        io.AddKeyEvent(ImGuiMod_Shift, event->shiftKey);
        io.AddKeyEvent(ImGuiMod_Alt, event->altKey);
        io.AddKeyEvent(ImGuiMod_Super, event->metaKey);
    }

    static ImGuiKey mapKey(const char* key)
    {
        if (!key)
            return ImGuiKey_None;
        const std::string value(key);
        if (value == "Tab") return ImGuiKey_Tab;
        if (value == "ArrowLeft") return ImGuiKey_LeftArrow;
        if (value == "ArrowRight") return ImGuiKey_RightArrow;
        if (value == "ArrowUp") return ImGuiKey_UpArrow;
        if (value == "ArrowDown") return ImGuiKey_DownArrow;
        if (value == "PageUp") return ImGuiKey_PageUp;
        if (value == "PageDown") return ImGuiKey_PageDown;
        if (value == "Home") return ImGuiKey_Home;
        if (value == "End") return ImGuiKey_End;
        if (value == "Insert") return ImGuiKey_Insert;
        if (value == "Delete") return ImGuiKey_Delete;
        if (value == "Backspace") return ImGuiKey_Backspace;
        if (value == " ") return ImGuiKey_Space;
        if (value == "Enter") return ImGuiKey_Enter;
        if (value == "Escape") return ImGuiKey_Escape;
        if (value == "a" || value == "A") return ImGuiKey_A;
        if (value == "c" || value == "C") return ImGuiKey_C;
        if (value == "v" || value == "V") return ImGuiKey_V;
        if (value == "x" || value == "X") return ImGuiKey_X;
        if (value == "y" || value == "Y") return ImGuiKey_Y;
        if (value == "z" || value == "Z") return ImGuiKey_Z;
        return ImGuiKey_None;
    }

    static bool isPrintableInput(const EmscriptenKeyboardEvent* event)
    {
        if (!event || !event->key[0] || event->ctrlKey || event->altKey || event->metaKey)
            return false;

        const std::string value(event->key);
        if (value == "Tab" || value == "Enter" || value == "Escape" || value == "Backspace" || value == "Delete" ||
            value == "Insert" || value == "Home" || value == "End" || value == "PageUp" || value == "PageDown" ||
            value == "Shift" || value == "Control" || value == "Alt" || value == "Meta")
            return false;
        bool functionKey = value.size() >= 2 && value[0] == 'F' &&
                           std::all_of(value.begin() + 1, value.end(), [](char ch) { return ch >= '0' && ch <= '9'; });
        if (value.rfind("Arrow", 0) == 0 || functionKey)
            return false;
        return true;
    }

    void installEventCallbacks()
    {
        emscripten_set_mousedown_callback(m_canvasSelector.c_str(), this, EM_TRUE, mouseCallback);
        emscripten_set_mouseup_callback(m_canvasSelector.c_str(), this, EM_TRUE, mouseCallback);
        emscripten_set_mousemove_callback(m_canvasSelector.c_str(), this, EM_TRUE, mouseCallback);
        emscripten_set_wheel_callback(m_canvasSelector.c_str(), this, EM_TRUE, wheelCallback);
        emscripten_set_keydown_callback(m_canvasSelector.c_str(), this, EM_FALSE, keyCallback);
        emscripten_set_keyup_callback(m_canvasSelector.c_str(), this, EM_FALSE, keyCallback);
    }

    void loadFonts()
    {
        auto glyphManager = std::make_shared<standalone::StandaloneGlyphManager>();
        // Keep font sizes in browser/CSS logical pixels. Dear ImGui 1.92 uses
        // DisplayFramebufferScale as the current rasterizer density, so the
        // same Noto Sans source is baked at DPR density without inflating ovui
        // layout dimensions.
        if (glyphManager->loadFonts(kFontPath, 1.0f))
        {
            auto* normalFont = reinterpret_cast<ImFont*>(glyphManager->getFont(FontStyle::eLarge));
            if (normalFont)
                ImGui::GetIO().FontDefault = normalFont;
            PlatformRegistry::instance().setGlyphManager(glyphManager);
            m_fontInfo = "font: packaged Noto Sans loaded from /assets/fonts/NotoSans-Regular.ttf";
        }
        else
        {
            ImGui::GetIO().Fonts->AddFontDefault();
            m_fontInfo = "font: packaged Noto Sans failed; using ImGui fallback";
        }
    }

    DeferHandle addDeferred(std::function<void()> callback, int32_t priority, bool persistent)
    {
        auto token = std::make_shared<int>(1);
        std::lock_guard<std::mutex> lock(m_deferMutex);
        m_deferred.push_back({ token, std::move(callback), priority, persistent });
        return token;
    }

    void drainDeferred()
    {
        std::vector<DeferredEntry> snapshot;
        {
            std::lock_guard<std::mutex> lock(m_deferMutex);
            snapshot = m_deferred;
            m_deferred.erase(std::remove_if(m_deferred.begin(), m_deferred.end(),
                                            [](const DeferredEntry& entry) {
                                                return !entry.persistent || entry.cancelToken.expired();
                                            }),
                             m_deferred.end());
        }

        std::sort(snapshot.begin(), snapshot.end(),
                  [](const DeferredEntry& a, const DeferredEntry& b) { return a.priority < b.priority; });
        for (auto& entry : snapshot)
        {
            if (!entry.cancelToken.expired() && entry.callback)
                entry.callback();
        }
    }

    static EM_BOOL mouseCallback(int eventType, const EmscriptenMouseEvent* event, void* userData)
    {
        return static_cast<WebPlatform*>(userData)->onMouse(eventType, event);
    }

    static EM_BOOL wheelCallback(int /*eventType*/, const EmscriptenWheelEvent* event, void* userData)
    {
        return static_cast<WebPlatform*>(userData)->onWheel(event);
    }

    static EM_BOOL keyCallback(int eventType, const EmscriptenKeyboardEvent* event, void* userData)
    {
        return static_cast<WebPlatform*>(userData)->onKey(eventType, event);
    }

    std::string m_canvasSelector;
    std::string m_title = "omni.ui";
    std::string m_clipboard;
    std::string m_fontInfo = "font: not initialized";
    EMSCRIPTEN_WEBGL_CONTEXT_HANDLE m_context = 0;
    AppWindowHandle m_appWindowHandle = nullptr;
    int m_logicalWidth = 1280;
    int m_logicalHeight = 640;
    int m_framebufferWidth = 1280;
    int m_framebufferHeight = 640;
    float m_devicePixelRatio = 1.0f;
    int m_mouseX = 0;
    int m_mouseY = 0;
    bool m_closeRequested = false;
    bool m_inputBlocked = false;
    std::chrono::steady_clock::time_point m_lastFrameTime = std::chrono::steady_clock::now();
    std::mutex m_deferMutex;
    std::vector<DeferredEntry> m_deferred;
};

std::shared_ptr<WebPlatform> s_platform;
std::shared_ptr<WebRenderer> s_renderer;
std::shared_ptr<WebFileIO> s_fileIO;
std::shared_ptr<standalone::StandaloneSettings> s_settings;
std::shared_ptr<StandaloneLog> s_log;
std::unique_ptr<standalone::StandaloneWindowCallbackManager> s_windowCallbackManager;

standalone::StandaloneWindowCallbackManager* windowCallbackManager()
{
    return s_windowCallbackManager.get();
}

void clearGlobals()
{
    s_windowCallbackManager.reset();
    s_platform.reset();
    s_renderer.reset();
    s_fileIO.reset();
    s_settings.reset();
    s_log.reset();
}

} // namespace

bool init(const char* canvasSelector, int width, int height, float devicePixelRatio)
{
    if (s_platform && PlatformRegistry::instance().isInitialized())
        return true;

    const char* selector = canvasSelector && canvasSelector[0] ? canvasSelector : "#canvas";
    s_log = std::make_shared<StandaloneLog>();
    s_settings = std::make_shared<standalone::StandaloneSettings>();
    s_fileIO = std::make_shared<WebFileIO>();
    s_renderer = std::make_shared<WebRenderer>();
    s_platform = std::make_shared<WebPlatform>(selector);
    s_windowCallbackManager = std::make_unique<standalone::StandaloneWindowCallbackManager>();

    PlatformRegistry::instance().setLog(s_log);
    PlatformRegistry::instance().setWindowCallbackManager(s_windowCallbackManager.get());

    s_platform->setCanvasSize(width, height, devicePixelRatio);
    WindowId id = s_platform->createWindow("ovui WebAssembly", width, height);
    if (id == kInvalidWindowId)
    {
        shutdown();
        return false;
    }

    auto& reg = PlatformRegistry::instance();
    reg.setSettings(s_settings);
    reg.setFileIO(s_fileIO);
    reg.setRenderer(s_renderer);
    reg.setPlatform(s_platform);
    return true;
}

bool tick()
{
    return s_platform ? s_platform->tick() : false;
}

void resetWorkspace()
{
    if (s_windowCallbackManager)
        s_windowCallbackManager->clearCallbacks();
    if (ImGui::GetCurrentContext())
    {
        ImGui::ClearActiveID();
        ImGui::GetIO().ClearInputKeys();
    }
    Workspace::clear();
}

bool setCanvasSize(int width, int height, float devicePixelRatio)
{
    return s_platform && s_platform->setCanvasSize(width, height, devicePixelRatio);
}

size_t windowCallbackCount()
{
    return s_windowCallbackManager ? s_windowCallbackManager->callbackCount() : 0;
}

void shutdown()
{
    if (ImGui::GetCurrentContext())
        Workspace::clear();
    if (s_platform)
        s_platform->destroyWindow(kMainWindowId);
    PlatformRegistry::instance().reset();
    clearGlobals();
}

std::string backendInfo()
{
    return "embedded CPython + built-in pybind11 _ui module + C++ ovui core + Dear ImGui + WebGL";
}

std::string fontInfo()
{
    return s_platform ? s_platform->fontInfo() : "font: backend not initialized";
}

std::string dpiInfo()
{
    return s_platform ? s_platform->dpiInfo() : "dpi: backend not initialized";
}

} // namespace web
} // namespace ui
} // namespace omni
