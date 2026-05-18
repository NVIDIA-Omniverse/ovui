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

// E8: Verify OpenGLByteImageGpu texture upload under EGL headless context.
// Uploads a 4x4 RGBA8 quadrant image, reads it back via glGetTexImage,
// and checks each quadrant corner is within tolerance of the expected color.
//
// Usage:
//   OMNIUI_HEADLESS=1 OMNIUI_HEADLESS_GL=1 OMNIUI_EGL_FORCE_SURFACELESS=1 \
//   ./test_egl_texture_upload [--fail-inject]
//
// --fail-inject: intentionally checks wrong colors to verify exit 1 behavior.

#include "StandaloneInit.h"
#include "test_utils.h"

#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/ImageProvider/IByteImageGpu.h>
#include <omni/ui/Types.h>

#include <glad/glad.h>

#include <cstdio>
#include <cstring>
#include <vector>

namespace standalone = omni::ui::standalone;
using omni::ui::IByteImageGpu;
using omni::ui::PlatformRegistry;
using omni::ui::PixelFormat;
using omni::ui::UInt2;

static constexpr int TEX_W = 4;
static constexpr int TEX_H = 4;

// 4x4 RGBA8 quadrant image (row-major, top-down):
// TL=Red, TR=Green, BL=Blue, BR=White
static void buildQuadrantPixels(std::vector<uint8_t>& pix)
{
    pix.resize(TEX_W * TEX_H * 4);
    for (int y = 0; y < TEX_H; ++y)
    {
        for (int x = 0; x < TEX_W; ++x)
        {
            uint8_t r = 0, g = 0, b = 0;
            bool left = (x < TEX_W / 2);
            bool top  = (y < TEX_H / 2);
            if (top  &&  left) { r = 255;                    }  // TL: Red
            if (top  && !left) {           g = 255;          }  // TR: Green
            if (!top &&  left) {                    b = 255; }  // BL: Blue
            if (!top && !left) { r = 255; g = 255; b = 255; }  // BR: White
            int idx = (y * TEX_W + x) * 4;
            pix[idx + 0] = r;
            pix[idx + 1] = g;
            pix[idx + 2] = b;
            pix[idx + 3] = 255;
        }
    }
}

int main(int argc, char* argv[])
{
    bool failInject = (argc > 1 && strcmp(argv[1], "--fail-inject") == 0);

#if defined(_WIN32)
    _putenv_s("OMNIUI_HEADLESS", "1");
    _putenv_s("OMNIUI_HEADLESS_GL", "1");
    _putenv_s("OMNIUI_EGL_FORCE_SURFACELESS", "1");
#else
    setenv("OMNIUI_HEADLESS", "1", 1);
    setenv("OMNIUI_HEADLESS_GL", "1", 1);
    setenv("OMNIUI_EGL_FORCE_SURFACELESS", "1", 1);
#endif

    if (!standalone::init("texture_test", 640, 480))
    {
        fprintf(stderr, "FAIL: standalone::init() failed\n");
        return 1;
    }

    IByteImageGpu* gpu = PlatformRegistry::instance().byteImageGpu();
    if (!gpu)
    {
        fprintf(stderr, "FAIL: byteImageGpu() is null — EGL init did not register OpenGLByteImageGpu\n");
        standalone::shutdown();
        return 1;
    }

    std::vector<uint8_t> pixels;
    buildQuadrantPixels(pixels);

    IByteImageGpu::Handle handle = gpu->createState();
    if (!handle)
    {
        fprintf(stderr, "FAIL: createState() returned null\n");
        standalone::shutdown();
        return 1;
    }

    const uint8_t* mips[1]  = { pixels.data() };
    size_t         strides[1] = { (size_t)(TEX_W * 4) };

    auto result = gpu->updateImage(handle, mips, strides, 1,
                                   UInt2{ (uint32_t)TEX_W, (uint32_t)TEX_H },
                                   PixelFormat::eRGBA8_UNORM,
                                   false, 0, 0, 0);

    if (!result.imGuiReference)
    {
        fprintf(stderr, "FAIL: updateImage() returned null imGuiReference\n");
        gpu->destroyState(handle);
        standalone::shutdown();
        return 1;
    }

    auto texId = (GLuint)(intptr_t)result.imGuiReference;

    for (int i = 0; i < 3; ++i)
        standalone::tick();

    std::vector<uint8_t> readback(TEX_W * TEX_H * 4, 0);
    glBindTexture(GL_TEXTURE_2D, texId);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE, readback.data());
    GLenum err = glGetError();
    if (err != GL_NO_ERROR)
    {
        fprintf(stderr, "FAIL: glGetTexImage error 0x%x\n", err);
        gpu->destroyState(handle);
        standalone::shutdown();
        return 1;
    }

    const int tol = getPixelTolerance();

    struct Check { int x, y; uint8_t r, g, b; const char* name; };

    // In fail-inject mode use wrong colors to verify the checker exits 1.
    Check checks[4];
    if (failInject)
    {
        checks[0] = { 0, 0,   0,   0, 255, "TL" };   // expect Blue, is Red
        checks[1] = { 2, 0, 255,   0,   0, "TR" };   // expect Red,  is Green
        checks[2] = { 0, 2,   0, 255,   0, "BL" };   // expect Green, is Blue
        checks[3] = { 2, 2,   0,   0,   0, "BR" };   // expect Black, is White
    }
    else
    {
        checks[0] = { 0, 0, 255,   0,   0, "TL(Red)"   };
        checks[1] = { 2, 0,   0, 255,   0, "TR(Green)" };
        checks[2] = { 0, 2,   0,   0, 255, "BL(Blue)"  };
        checks[3] = { 2, 2, 255, 255, 255, "BR(White)" };
    }

    int failures = 0;
    for (const auto& c : checks)
    {
        if (!checkPixel(readback, TEX_W, TEX_H, c.x, c.y, c.r, c.g, c.b, tol))
        {
            int idx = (c.y * TEX_W + c.x) * 4;
            fprintf(stderr,
                    "FAIL: quadrant %s at (%d,%d): got [%d,%d,%d] expected [%d,%d,%d]\n",
                    c.name, c.x, c.y,
                    readback[idx], readback[idx + 1], readback[idx + 2],
                    c.r, c.g, c.b);
            ++failures;
        }
    }

    gpu->destroyState(handle);
    standalone::shutdown();

    if (failures > 0)
        return 1;

    fprintf(stdout, "PASS: %d quadrant pixels verified\n", 4);
    return 0;
}
