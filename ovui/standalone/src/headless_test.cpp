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

// Headless Vulkan rendering test for ovui.
// Renders widgets to an offscreen framebuffer and saves a screenshot to PNG.
//
// Usage:
//   DISPLAY= OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan ./headless_test [output.png]
//
// Requires a Vulkan-capable GPU with driver installed (no display needed).

#include "StandaloneInit.h"
#include "HeadlessVulkanPlatform.h"
#include "VulkanBackend.h"

#include <imgui/imgui.h>

#define STB_IMAGE_WRITE_STATIC
#include <stb_image_write.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

using namespace omni::ui::standalone;

/// Render a few frames of demo widgets, then capture screenshot.
int main(int argc, char* argv[])
{
    const char* outputPath = "headless_output.png";
    if (argc > 1)
        outputPath = argv[1];

    // Force headless mode
#if defined(_WIN32)
    _putenv_s("OMNIUI_HEADLESS", "1");
    _putenv_s("OMNIUI_BACKEND", "vulkan");
#else
    setenv("OMNIUI_HEADLESS", "1", 1);
    setenv("OMNIUI_BACKEND", "vulkan", 1);
#endif

    const int width = 800;
    const int height = 600;

    fprintf(stdout, "=== omni.ui headless Vulkan test ===\n");
    fprintf(stdout, "Output: %s (%dx%d)\n", outputPath, width, height);

    if (!init("Headless Test", width, height))
    {
        fprintf(stderr, "FAIL: standalone::init() failed\n");
        return 1;
    }

    // Render a few frames to warm up ImGui and let widgets settle
    const int warmupFrames = 3;
    for (int i = 0; i < warmupFrames; ++i)
    {
        tick();
    }

    // Schedule screenshot capture
    if (!scheduleScreenshot(outputPath))
    {
        fprintf(stderr, "FAIL: scheduleScreenshot() failed\n");
        shutdown();
        return 1;
    }

    // Run one more tick to trigger the screenshot callback
    tick();

    // Verify the screenshot was captured
    if (!pollScreenshotDone())
    {
        fprintf(stderr, "FAIL: screenshot was not captured\n");
        shutdown();
        return 1;
    }

    // Verify the output file exists and has non-zero size
    FILE* f = fopen(outputPath, "rb");
    if (!f)
    {
        fprintf(stderr, "FAIL: output file '%s' does not exist\n", outputPath);
        shutdown();
        return 1;
    }
    fseek(f, 0, SEEK_END);
    long fileSize = ftell(f);
    fclose(f);

    if (fileSize <= 0)
    {
        fprintf(stderr, "FAIL: output file '%s' is empty\n", outputPath);
        shutdown();
        return 1;
    }

    fprintf(stdout, "PASS: headless render saved to '%s' (%ld bytes)\n", outputPath, fileSize);

    shutdown();
    return 0;
}
