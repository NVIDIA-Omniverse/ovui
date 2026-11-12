/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// Presentation-key mode drawn by the real headless renderer.
//
// It starts the standalone platform (EGL OpenGL or Vulkan, chosen by the
// environment like in the other headless tests), puts a fake renderer in the
// platform registry, and draws four image widgets. The fake renderer keeps the
// global present setting on, as a second live feed does, and tells which keys
// have a drawable. The result is a PNG and a check of the pixels of each widget.
//
//   W1 dead feed + fallback: the feeder retired the key, then bytes were uploaded
//      -> expected: the uploaded green image.
//   W2 never-notified key: setup worked, the renderer never got a frame for the key
//      -> expected: the texture of the resource (blue) when the renderer reports the key
//         as unmapped; nothing when the renderer has no key state (--shipped). Never the raw key.
//   W3 key retired after the widget asked for it, before the draw
//      -> expected: nothing is drawn (the window color stays), never the raw key.
//   W4 feed stopped: it entered a key, then gave no new frame while another feed stayed live
//      -> expected: its last texture (blue). No retire call and no key state is used. The test
//         opts in to a 200 ms lease for this widget, because the library has no lease by default.
//   Another provider holds a live key and is not drawn. With the global present
//   setting on, it is the second live feed of the same process.
//
// The window fits its content, and the test fails (exit 2) when an image is not fully inside the
// window or the window is not inside the picture. So a sample never reads the background by layout.
//
// With --shipped the fake renderer has no key table, like the renderer of this
// repository. Then no key may reach the back end; W1 still shows the fallback.
//
// Usage:
//   OMNIUI_HEADLESS=1 OMNIUI_HEADLESS_GL=1 OMNIUI_EGL_FORCE_SURFACELESS=1 ./presentation_key_render_test out.png
//   OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan ./presentation_key_render_test out.png

#include "StandaloneInit.h"

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#if __has_include(<omni/ui/ImageProvider/PresentationKeyGuard.h>)
#    define HAS_RETIRE 1
#else
#    define HAS_RETIRE 0
#endif
#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/windowmanager/IWindowCallbackManager.h>

#include "platform/IImageProviderRenderer.h"

#define STB_IMAGE_IMPLEMENTATION
#define STB_IMAGE_STATIC
#include <stb_image.h>

#include <imgui.h>

#include <cstdio>
#include <cstdlib>
#include <chrono>
#include <memory>
#include <thread>
#include <set>
#include <string>
#include <vector>

namespace rtx { namespace resourcemanager { class RpResource; } }

using namespace omni::ui;
using namespace omni::ui::standalone;
using omni::ui::windowmanager::DockPreference;
using omni::ui::windowmanager::IEventListener;
using omni::ui::windowmanager::IWindowCallback;
using omni::ui::windowmanager::IWindowCallbackManager;
using RpResource = rtx::resourcemanager::RpResource;

namespace
{

constexpr uint64_t kKeyDead = 0xFFFFFFF1ull;
constexpr uint64_t kKeyNever = 0xFFFFFFFDull;
constexpr uint64_t kKeyLate = 0xFFFFFFF3ull;
constexpr uint64_t kKeyLive = 0xFFFFFFF4ull;
constexpr uint64_t kKeyStopped = 0xFFFFFFF5ull;

struct FakeRenderer : IImageProviderRenderer
{
    std::set<uint64_t> mapped;
    void* handle = nullptr; // texture reference given to every resource
    char dummy[4] = {};

    void* acquireRenderer() override { return this; }
    bool isPresentThreadEnabled(void*) override { return true; } // another feed keeps it on
    EnsureResourceResult ensureResourceWithTextureInfo(void*, void* rsrc, uint32_t) override
    {
        EnsureResourceResult r;
        r.resource = rsrc;
        r.textureHandlePtr = handle;
        r.width = 4;
        r.height = 4;
        r.format = PixelFormat::eRGBA8_UNORM;
        return r;
    }
    void* ensureResourceSimple(void*, void* rsrc, uint32_t) override { return rsrc; }
    void releaseResource(void*, void*) override {}
};

// A renderer that maps keys itself. Not marked override: the old interface has no such function.
struct MappingRenderer : FakeRenderer
{
#if HAS_RETIRE
    PresentationKeyState presentationKeyState(void*, uint64_t key)
    {
        return mapped.count(key) ? PresentationKeyState::eMapped : PresentationKeyState::eUnmapped;
    }
#endif
};

std::vector<uint8_t> solid(uint8_t r, uint8_t g, uint8_t b)
{
    std::vector<uint8_t> px(4 * 4 * 4);
    for (size_t i = 0; i < px.size(); i += 4)
    {
        px[i] = r;
        px[i + 1] = g;
        px[i + 2] = b;
        px[i + 3] = 255;
    }
    return px;
}

struct Rect
{
    float x0 = 0, y0 = 0, x1 = 0, y1 = 0;
};

struct Scene : IEventListener
{
    std::shared_ptr<FakeRenderer> renderer;
    std::unique_ptr<ByteImageProvider> source, dead, never, late, live, stopped;
    alignas(8) char res[6][8] = {};
    Rect rect[4];
    Rect windowRect;

    void image(const char* label, ByteImageProvider& p, Rect& out)
    {
        ImGui::TextUnformatted(label);
        void* ref = p.getImGuiReference();
        ImGui::Image(ImTextureRef(static_cast<ImTextureID>(reinterpret_cast<uintptr_t>(ref))), ImVec2(64, 64));
        const ImVec2 a = ImGui::GetItemRectMin(), b = ImGui::GetItemRectMax();
        out = { a.x, a.y, b.x, b.y };
    }

    void onDraw(float) override
    {
        // The window fits its content. The font of each platform has another height, so a fixed
        // size can clip the last image. main() also checks that every image is inside the window.
        ImGui::SetNextWindowPos(ImVec2(10, 10));
        ImGui::PushStyleColor(ImGuiCol_WindowBg, ImVec4(0.55f, 0.55f, 0.60f, 1.0f));
        ImGui::Begin("Presentation keys", nullptr,
                     ImGuiWindowFlags_NoMove | ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoScrollbar |
                         ImGuiWindowFlags_NoSavedSettings);
        const ImVec2 wp = ImGui::GetWindowPos(), ws = ImGui::GetWindowSize();
        windowRect = { wp.x, wp.y, wp.x + ws.x, wp.y + ws.y };
        image("W1 dead feed, then bytes", *dead, rect[0]);
        image("W2 never-notified key", *never, rect[1]);
        // W3: the key has a drawable while the widget is built, and is retired before the draw.
        renderer->mapped.insert(kKeyLate);
        image("W3 key retired before draw", *late, rect[2]);
        renderer->mapped.erase(kKeyLate);
        image("W4 feed stopped, no retire call", *stopped, rect[3]);
        ImGui::End();
        ImGui::PopStyleColor();
    }
};

bool near(const uint8_t* px, int r, int g, int b, int tol = 12)
{
    auto d = [](int a, int b2) { return a > b2 ? a - b2 : b2 - a; };
    return d(px[0], r) <= tol && d(px[1], g) <= tol && d(px[2], b) <= tol;
}

const uint8_t* at(const std::vector<uint8_t>& pixels, int w, float x, float y)
{
    return &pixels[(static_cast<size_t>(y) * w + static_cast<size_t>(x)) * 4];
}

} // namespace

int main(int argc, char* argv[])
{
    const char* out = "/tmp/presentation_key_render.png";
    bool shipped = false;
    for (int i = 1; i < argc; ++i)
    {
        if (std::string(argv[i]) == "--shipped")
            shipped = true;
        else
            out = argv[i];
    }
    if (!getenv("OMNIUI_HEADLESS"))
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "ERROR: set OMNIUI_HEADLESS=1 and the backend variables first.\n");
        return 2;
    }
    if (!init("Presentation key render test", 400, 640))
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "FAIL: standalone::init() failed\n");
        return 2;
    }

    auto scene = std::make_unique<Scene>();
    // Real textures come from the real byte-image back end of the platform.
    scene->source.reset(new ByteImageProvider());
    auto blue = solid(0, 0, 255);
    scene->source->setBytesData(blue.data(), { 4, 4 }, 16, PixelFormat::eRGBA8_UNORM);
    if (!scene->source->isReferenceValid())
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "FAIL: the source texture could not be uploaded\n");
        shutdown();
        return 2;
    }

    std::shared_ptr<FakeRenderer> renderer;
    if (shipped)
        renderer = std::make_shared<FakeRenderer>();
    else
        renderer = std::make_shared<MappingRenderer>();
    renderer->handle = scene->source->getImGuiReference();
    scene->renderer = renderer;
    PlatformRegistry::instance().setImageProviderRenderer(renderer);

    scene->dead.reset(new ByteImageProvider());
    scene->never.reset(new ByteImageProvider());
    scene->late.reset(new ByteImageProvider());
    scene->live.reset(new ByteImageProvider());
    scene->stopped.reset(new ByteImageProvider());

    auto resource = [&](int i) -> RpResource& { return *reinterpret_cast<RpResource*>(scene->res[i]); };
    renderer->mapped = { kKeyDead, kKeyLive }; // W4 is never mapped: its state is unmapped (mapping renderer) or unknown (--shipped)
    bool ok = true;
    ok &= scene->live->setImageData(resource(0), kKeyLive);   // the other live feed
    ok &= scene->dead->setImageData(resource(1), kKeyDead);   // W1 enters key mode
    ok &= scene->never->setImageData(resource(2), kKeyNever); // W2: never notified
    ok &= scene->late->setImageData(resource(3), kKeyLate);   // W3
    ok &= scene->stopped->setImageData(resource(4), kKeyStopped); // W4 enters, then delivers no more frames
    renderer->mapped.erase(kKeyDead);                          // W1's feed dies; the other feed stays live
#if HAS_RETIRE
    ImageProvider::retirePresentationKey(kKeyDead);
#endif
    auto green = solid(0, 255, 0);
    scene->dead->setBytesData(green.data(), { 4, 4 }, 16, PixelFormat::eRGBA8_UNORM); // fallback upload
    if (!ok)
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "FAIL: key entry failed in the setup\n");
        shutdown();
        return 2;
    }

    // Real time: the stopped feed is silent for longer than the lease; the other feed delivers a frame now.
#if HAS_RETIRE
    ImageProvider::setPresentationKeyLeaseMs(200);
#endif
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    ok = scene->live->setImageData(resource(0), kKeyLive);
    ok &= scene->never->setImageData(resource(2), kKeyNever); // these feeds still deliver frames
    ok &= scene->late->setImageData(resource(3), kKeyLate);
    if (!ok)
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "FAIL: the live feed could not deliver a frame\n");
        shutdown();
        return 2;
    }

    IWindowCallbackManager* wcm = PlatformRegistry::instance().windowCallbackManager();
    IWindowCallback* cb = wcm->createWindowCallbackPtr("Keys", 10, 10, DockPreference::eDisabled, scene.get());
    for (int i = 0; i < 5; ++i)
        tick();
    if (!scheduleScreenshot(out))
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "FAIL: scheduleScreenshot() failed\n");
        shutdown();
        return 2;
    }
    tick();
    const bool captured = pollScreenshotDone() && !hadLastScreenshotError();
    const Rect rects[4] = { scene->rect[0], scene->rect[1], scene->rect[2], scene->rect[3] };
    const Rect windowRect = scene->windowRect;
    wcm->removeWindowCallback(cb);
    delete cb;
    PlatformRegistry::instance().setImageProviderRenderer(nullptr);
    scene.reset();
    shutdown();
    if (!captured)
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "FAIL: the screenshot was not captured\n");
        return 2;
    }

    int w = 0, h = 0, ch = 0;
    stbi_uc* data = stbi_load(out, &w, &h, &ch, 4);
    if (!data)
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "FAIL: could not read %s\n", out);
        return 2;
    }
    std::vector<uint8_t> px(data, data + static_cast<size_t>(w) * h * 4);
    stbi_image_free(data);

    int failures = 0;

    // The proof is valid only when each image is fully visible: inside the window, and the window
    // inside the picture. Otherwise a sample reads the background, and a pass means nothing.
    auto inside = [](const Rect& inner, const Rect& outer) {
        return inner.x0 >= outer.x0 && inner.y0 >= outer.y0 && inner.x1 <= outer.x1 && inner.y1 <= outer.y1;
    };
    const Rect picture = { 0, 0, static_cast<float>(w), static_cast<float>(h) };
    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    printf("window (%d,%d)-(%d,%d) in picture %dx%d\n", static_cast<int>(windowRect.x0), static_cast<int>(windowRect.y0),
           static_cast<int>(windowRect.x1), static_cast<int>(windowRect.y1), w, h);
    if (!inside(windowRect, picture))
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        printf("FAIL layout: the window is not inside the picture\n");
        return 2;
    }
    for (int i = 0; i < 4; ++i)
    {
        const bool visible = inside(rects[i], windowRect);
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        printf("%s layout: image W%d (%d,%d)-(%d,%d) is %s the window\n", visible ? "PASS" : "FAIL", i + 1,
               static_cast<int>(rects[i].x0), static_cast<int>(rects[i].y0), static_cast<int>(rects[i].x1),
               static_cast<int>(rects[i].y1), visible ? "inside" : "NOT inside");
        if (!visible)
            ++failures;
    }
    if (failures)
        return 2;

    auto check = [&](const char* name, const Rect& r, int er, int eg, int eb) {
        const float cx = (r.x0 + r.x1) * 0.5f, cy = (r.y0 + r.y1) * 0.5f;
        const uint8_t* p = at(px, w, cx, cy);
        const bool good = near(p, er, eg, eb);
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        printf("%s %s: pixel at (%d,%d) rgb=(%d,%d,%d), expected (%d,%d,%d)\n", good ? "PASS" : "FAIL", name,
               static_cast<int>(cx), static_cast<int>(cy), p[0], p[1], p[2], er, eg, eb);
        if (!good)
            ++failures;
    };
    check("W1 dead feed then bytes shows the uploaded green image", rects[0], 0, 255, 0);
    if (shipped)
        check("W2 never-notified key draws nothing (no key state: key kept, draw guard removes it)", rects[1], 140, 140, 153);
    else
        check("W2 never-notified key shows the resource texture (renderer reports it unmapped)", rects[1], 0, 0, 255);
    check("W3 key retired before draw draws nothing", rects[2], 140, 140, 153);
    check("W4 feed stopped (no retire, key state not used) shows its last texture, not the dead key", rects[3], 0, 0, 255);
    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    printf("image %dx%d written to %s\n", w, h, out);
    return failures == 0 ? 0 : 1;
}
