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

// C1: EGL headless integration test — full pipeline with real widget rendering.
//
// Registers a TestWidgetListener that draws a label, a colored rectangle, and
// a button each frame through the standard IWindowCallbackManager callback
// path (tick() -> drawAllWindows() -> onDraw()).  Captures a PNG screenshot
// and verifies that at least one pixel has a channel value >= 100.
//
// The gray clear color [25,25,25] is always below threshold=100.
// ImGui white text [200,200,200] and the orange rect [255,80,0] exceed it.
//
// Usage (manual — no-GPU surfaceless host):
//   OMNIUI_HEADLESS=1 OMNIUI_HEADLESS_GL=1 OMNIUI_EGL_FORCE_SURFACELESS=1 \
//   ./headless_egl_test [output.png] [--blank-inject]
//
// Usage (manual — GPU host, device-enumerate path, no FORCE_SURFACELESS):
//   OMNIUI_HEADLESS=1 OMNIUI_HEADLESS_GL=1 ./headless_egl_test [output.png]
//
// OMNIUI_HEADLESS and OMNIUI_HEADLESS_GL must be set by the caller.
// OMNIUI_EGL_FORCE_SURFACELESS is optional: absent = device-enumerate path.
// The binary never forces any env var; CTest ENVIRONMENT is the mechanism.
//
// --blank-inject: runs the real pipeline without any widget callbacks.
//   The clear-only [25,25,25] render fails the threshold check, proving
//   the blank-detection logic works.  Always exits 1.

#include "StandaloneInit.h"

#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/windowmanager/IWindowCallbackManager.h>

#define STB_IMAGE_IMPLEMENTATION
#define STB_IMAGE_STATIC
#include <stb_image.h>

#include <imgui.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

using namespace omni::ui::standalone;
using omni::ui::PlatformRegistry;
using omni::ui::windowmanager::DockPreference;
using omni::ui::windowmanager::IEventListener;
using omni::ui::windowmanager::IWindowCallback;
using omni::ui::windowmanager::IWindowCallbackManager;

// ---------------------------------------------------------------------------
// TestWidgetListener: draws a label, a colored rectangle, and a button.
// These pixels have at least one RGB channel >= 100, well above the gray
// clear colour [25,25,25], so the PNG threshold check passes.
// ---------------------------------------------------------------------------
class TestWidgetListener : public IEventListener
{
public:
    void onDraw(float /*elapsedTime*/) override
    {
        ImGui::Begin("EGL Test Window");
        ImGui::Text("omni.ui EGL headless integration test");

        // Orange filled rectangle drawn directly into the window draw list.
        ImVec2 pos = ImGui::GetCursorScreenPos();
        ImGui::GetWindowDrawList()->AddRectFilled(
            pos, ImVec2(pos.x + 80.0f, pos.y + 24.0f),
            IM_COL32(255, 80, 0, 255));
        ImGui::Dummy(ImVec2(80.0f, 24.0f));

        ImGui::Button("Click me");
        ImGui::End();
    }
};

// ---------------------------------------------------------------------------
// PNG helpers
// ---------------------------------------------------------------------------

static bool loadPng(const char* path, std::vector<uint8_t>& out, int* w, int* h)
{
    int ch;
    stbi_uc* data = stbi_load(path, w, h, &ch, 4);
    if (!data)
        return false;
    out.assign(data, data + static_cast<size_t>(*w) * *h * 4);
    stbi_image_free(data);
    return true;
}

// Returns true if any pixel has at least one RGB channel >= threshold.
static bool hasAboveThreshold(const std::vector<uint8_t>& pixels, int threshold)
{
    for (size_t i = 0; i + 2 < pixels.size(); i += 4)
    {
        if (pixels[i]     >= (uint8_t)threshold ||
            pixels[i + 1] >= (uint8_t)threshold ||
            pixels[i + 2] >= (uint8_t)threshold)
            return true;
    }
    return false;
}

// ---------------------------------------------------------------------------
// runPipeline: init -> (optionally register widgets) -> render -> screenshot
//              -> shutdown -> validate written PNG.
//
// registerWidgets=true:  registers TestWidgetListener via IWindowCallbackManager.
// registerWidgets=false: clear-only render (no widgets) for blank-detect test.
//
// Returns 0 if the PNG has at least one above-threshold pixel, 1 otherwise.
// ---------------------------------------------------------------------------
static int runPipeline(const char* outputPath, bool registerWidgets)
{
    if (!init("EGL Integration Test", 640, 480))
    {
        fprintf(stderr, "FAIL: standalone::init() failed\n");
        return 1;
    }

    IWindowCallbackManager* wcm = PlatformRegistry::instance().windowCallbackManager();
    IWindowCallback* cb = nullptr;

    if (registerWidgets)
    {
        if (!wcm)
        {
            fprintf(stderr, "FAIL: windowCallbackManager() is null after init\n");
            shutdown();
            return 1;
        }
        auto* listener = new TestWidgetListener();
        cb = wcm->createWindowCallbackPtr(
            "EGL Test", 300, 200, DockPreference::eDisabled, listener);
        if (!cb)
        {
            fprintf(stderr, "FAIL: createWindowCallbackPtr returned null\n");
            delete listener;
            shutdown();
            return 1;
        }
    }

    // Render 5 frames through tick() -> drawAllWindows() -> onDraw().
    for (int i = 0; i < 5; ++i)
        tick();

    if (!scheduleScreenshot(outputPath))
    {
        fprintf(stderr, "FAIL: scheduleScreenshot() failed\n");
        if (cb) { wcm->removeWindowCallback(cb); delete cb; }
        shutdown();
        return 1;
    }
    tick();  // triggers glReadPixels + stbi_write_png inside HeadlessEglPlatform::tick()

    // Capture flags before shutdown.
    bool captured = pollScreenshotDone();
    bool hasError = hadLastScreenshotError();

    if (cb) { wcm->removeWindowCallback(cb); delete cb; }
    shutdown();

    if (!captured)
    {
        fprintf(stderr, "FAIL: screenshot was not captured\n");
        return 1;
    }
    if (hasError)
    {
        fprintf(stderr, "FAIL: screenshot capture reported an error\n");
        return 1;
    }

    // Validate the PNG written to outputPath.
    std::vector<uint8_t> pixels;
    int pngW = 0, pngH = 0;
    if (!loadPng(outputPath, pixels, &pngW, &pngH))
    {
        fprintf(stderr, "FAIL: could not load PNG at %s: %s\n", outputPath, stbi_failure_reason());
        return 1;
    }

    if (!hasAboveThreshold(pixels, 100))
        return 1;

    fprintf(stdout, "PASS: EGL headless render is non-blank (%dx%d), screenshot: %s\n",
            pngW, pngH, outputPath);
    return 0;
}

int main(int argc, char* argv[])
{
    const char* outputPath = "/tmp/headless_egl_output.png";
    bool blankInject = false;

    for (int i = 1; i < argc; ++i)
    {
        if (strcmp(argv[i], "--blank-inject") == 0)
            blankInject = true;
        else
            outputPath = argv[i];
    }

    // Require the caller (CTest ENVIRONMENT or manual export) to supply the
    // headless mode vars.  This binary deliberately never forces any env var —
    // OMNIUI_EGL_FORCE_SURFACELESS in particular must be controlled externally
    // so that the GPU-host / device-enumerate path (no FORCE_SURFACELESS) can
    // be exercised honestly.
    if (!getenv("OMNIUI_HEADLESS") || !getenv("OMNIUI_HEADLESS_GL"))
    {
        fprintf(stderr,
                "ERROR: OMNIUI_HEADLESS and OMNIUI_HEADLESS_GL must be set before "
                "running this test.\n"
                "Usage: OMNIUI_HEADLESS=1 OMNIUI_HEADLESS_GL=1 "
                "[OMNIUI_EGL_FORCE_SURFACELESS=1] %s [output.png] [--blank-inject]\n",
                argv[0]);
        return 1;
    }

    fprintf(stdout, "=== omni.ui EGL headless integration test ===\n");
    fprintf(stdout, "Output: %s%s\n", outputPath, blankInject ? " [blank-inject]" : "");

    if (blankInject)
    {
        // Run the real pipeline without widget callbacks. The gray [25,25,25]
        // render must fail the threshold check (return 1). If it passes
        // (return 0) the blank-detection logic is broken.
        int result = runPipeline(outputPath, false);
        if (result == 0)
        {
            fprintf(stderr,
                    "FAIL: blank-inject: threshold check accepted gray-only render\n");
            return 1;
        }
        fprintf(stderr, "FAIL: screenshot is blank\n");
        return 1;
    }

    return runPipeline(outputPath, true);
}
