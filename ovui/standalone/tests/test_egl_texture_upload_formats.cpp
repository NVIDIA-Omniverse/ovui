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

// All-format pixel round-trip test for the OpenGL fromGpu path.
//
// Drives ``IByteImageGpu::updateImage(.., fromGpu=true)`` with a 128x128
// CUDA device pointer for every PixelFormat the OpenGL backend supports,
// then reads the GL texture back via ``glGetTexImage`` and compares bytes.
//
// Exercises BOTH the direct CUDA-GL interop path
// (``cudaGraphicsGLRegisterImage`` + ``cudaMemcpy2DToArrayAsync``) AND
// the PBO fallback path (``cudaGraphicsGLRegisterBuffer`` +
// ``glTexSubImage2D``) by toggling ``setUseDirectInterop`` on each
// run.
//
// For 3-channel float formats the direct path can't register a 3-channel
// GL texture with CUDA, so the production code silently falls back to PBO.
// We verify that fallback rather than expecting a failure.
//
// Usage:
//   OMNIUI_HEADLESS=1 OMNIUI_HEADLESS_GL=1 OMNIUI_EGL_FORCE_SURFACELESS=1 \
//   ./test_egl_texture_upload_formats

#include "OpenGLByteImageGpu.h"
#include "StandaloneInit.h"

#include <omni/ui/ImageProvider/IByteImageGpu.h>
#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/Types.h>

#include <cuda_runtime.h>
#include <glad/glad.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

using omni::ui::getPixelFormatSize;
using omni::ui::IByteImageGpu;
using omni::ui::PixelFormat;
using omni::ui::PlatformRegistry;
using omni::ui::UInt2;
namespace standalone = omni::ui::standalone;

namespace
{
constexpr int W = 128;
constexpr int H = 128;

// `glFormat` + `glType` are how the test reads the texture back via
// glGetTexImage. They must match what ``OpenGLByteImageGpu`` uses
// internally for the same PixelFormat — see ``resolveGlFormat``.
struct FormatCase
{
    const char* name;
    PixelFormat format;
    GLenum glFormat;
    GLenum glType;
};

constexpr FormatCase kCases[] = {
    { "RGBA8_UNORM",  PixelFormat::eRGBA8_UNORM,  GL_RGBA, GL_UNSIGNED_BYTE },
    { "RGBA8_SRGB",   PixelFormat::eRGBA8_SRGB,   GL_RGBA, GL_UNSIGNED_BYTE },
    { "BGRA8_UNORM",  PixelFormat::eBGRA8_UNORM,  GL_BGRA, GL_UNSIGNED_BYTE },
    { "R8_UNORM",     PixelFormat::eR8_UNORM,     GL_RED,  GL_UNSIGNED_BYTE },
    { "R16_FLOAT",    PixelFormat::eR16_FLOAT,    GL_RED,  GL_HALF_FLOAT    },
    { "R32_FLOAT",    PixelFormat::eR32_FLOAT,    GL_RED,  GL_FLOAT         },
    { "RG16_FLOAT",   PixelFormat::eRG16_FLOAT,   GL_RG,   GL_HALF_FLOAT    },
    { "RG32_FLOAT",   PixelFormat::eRG32_FLOAT,   GL_RG,   GL_FLOAT         },
    { "RGB16_FLOAT",  PixelFormat::eRGB16_FLOAT,  GL_RGB,  GL_HALF_FLOAT    },
    { "RGB32_FLOAT",  PixelFormat::eRGB32_FLOAT,  GL_RGB,  GL_FLOAT         },
    { "RGBA16_FLOAT", PixelFormat::eRGBA16_FLOAT, GL_RGBA, GL_HALF_FLOAT    },
    { "RGBA32_FLOAT", PixelFormat::eRGBA32_FLOAT, GL_RGBA, GL_FLOAT         },
};

void fillBytePattern(std::vector<uint8_t>& dst, size_t pitch)
{
    dst.assign(pitch * H, 0);
    for (int y = 0; y < H; ++y)
    {
        for (size_t i = 0; i < pitch; ++i)
        {
            dst[y * pitch + i] = (uint8_t)((y * 31u + i * 17u + 41u) & 0xFFu);
        }
    }
}

bool isHalfFloatFormat(PixelFormat format)
{
    return format == PixelFormat::eR16_FLOAT ||
           format == PixelFormat::eRG16_FLOAT ||
           format == PixelFormat::eRGB16_FLOAT ||
           format == PixelFormat::eRGBA16_FLOAT;
}

bool isFloat32Format(PixelFormat format)
{
    return format == PixelFormat::eR32_FLOAT ||
           format == PixelFormat::eRG32_FLOAT ||
           format == PixelFormat::eRGB32_FLOAT ||
           format == PixelFormat::eRGBA32_FLOAT;
}

size_t channelCount(PixelFormat format)
{
    switch (format)
    {
        case PixelFormat::eR16_FLOAT:
        case PixelFormat::eR32_FLOAT:
            return 1;
        case PixelFormat::eRG16_FLOAT:
        case PixelFormat::eRG32_FLOAT:
            return 2;
        case PixelFormat::eRGB16_FLOAT:
        case PixelFormat::eRGB32_FLOAT:
            return 3;
        case PixelFormat::eRGBA16_FLOAT:
        case PixelFormat::eRGBA32_FLOAT:
            return 4;
        default:
            return 0;
    }
}

void fillHalfFloatPattern(std::vector<uint8_t>& dst, size_t pitch, PixelFormat format)
{
    static constexpr uint16_t kValues[] = {
        0x0000u, //  0.0
        0x3800u, //  0.5
        0xb800u, // -0.5
        0x3c00u, //  1.0
        0xbc00u, // -1.0
        0x4000u, //  2.0
        0xc000u, // -2.0
        0x4200u, //  3.0
        0xc200u, // -3.0
    };
    const size_t channels = channelCount(format);
    dst.assign(pitch * H, 0);
    for (int y = 0; y < H; ++y)
    {
        for (int x = 0; x < W; ++x)
        {
            for (size_t ch = 0; ch < channels; ++ch)
            {
                const size_t element = ((size_t)y * W + (size_t)x) * channels + ch;
                const uint16_t bits = kValues[(element * 7u + (size_t)y + ch) %
                                              (sizeof(kValues) / sizeof(kValues[0]))];
                const size_t offset = (size_t)y * pitch + ((size_t)x * channels + ch) * sizeof(bits);
                std::memcpy(dst.data() + offset, &bits, sizeof(bits));
            }
        }
    }
}

void fillFloat32Pattern(std::vector<uint8_t>& dst, size_t pitch, PixelFormat format)
{
    const size_t channels = channelCount(format);
    dst.assign(pitch * H, 0);
    for (int y = 0; y < H; ++y)
    {
        for (int x = 0; x < W; ++x)
        {
            for (size_t ch = 0; ch < channels; ++ch)
            {
                const int bucket = (int)(((size_t)y * 5u + (size_t)x * 3u + ch * 11u) % 17u);
                const float value = (float)(bucket - 8) * 0.25f;
                const size_t offset = (size_t)y * pitch + ((size_t)x * channels + ch) * sizeof(value);
                std::memcpy(dst.data() + offset, &value, sizeof(value));
            }
        }
    }
}

void fillReferencePattern(std::vector<uint8_t>& dst, size_t pitch, PixelFormat format)
{
    if (isHalfFloatFormat(format))
        fillHalfFloatPattern(dst, pitch, format);
    else if (isFloat32Format(format))
        fillFloat32Pattern(dst, pitch, format);
    else
        fillBytePattern(dst, pitch);
}

bool runCase(IByteImageGpu* gpu, const FormatCase& c, bool useDirect)
{
    const size_t bpp = getPixelFormatSize(c.format);
    if (bpp == 0)
    {
        fprintf(stderr, "[%s][%s] FAIL: getPixelFormatSize returned 0\n",
                c.name, useDirect ? "direct" : "pbo");
        return false;
    }
    const size_t pitch = (size_t)W * bpp;
    const size_t byteCount = pitch * H;

    std::vector<uint8_t> ref;
    fillReferencePattern(ref, pitch, c.format);

    void* dPtr = nullptr;
    if (cudaMalloc(&dPtr, byteCount) != cudaSuccess || !dPtr)
    {
        fprintf(stderr, "[%s][%s] FAIL: cudaMalloc failed\n",
                c.name, useDirect ? "direct" : "pbo");
        return false;
    }
    if (cudaMemcpy(dPtr, ref.data(), byteCount, cudaMemcpyHostToDevice) != cudaSuccess)
    {
        fprintf(stderr, "[%s][%s] FAIL: cudaMemcpy H2D failed\n",
                c.name, useDirect ? "direct" : "pbo");
        cudaFree(dPtr);
        return false;
    }

    // ``standalone::init`` always registers an OpenGLByteImageGpu when
    // OMNIUI_HEADLESS_GL is on, so static_cast is safe here and avoids
    // a hard dependency on RTTI being enabled in the build.
    auto* glGpu = static_cast<omni::ui::standalone::OpenGLByteImageGpu*>(gpu);
    glGpu->setUseDirectInterop(useDirect);

    IByteImageGpu::Handle handle = gpu->createState();
    if (!handle)
    {
        fprintf(stderr, "[%s][%s] FAIL: createState returned null\n",
                c.name, useDirect ? "direct" : "pbo");
        cudaFree(dPtr);
        return false;
    }

    const uint8_t* mips[1] = { reinterpret_cast<const uint8_t*>(dPtr) };
    size_t strides[1] = { pitch };
    auto result = gpu->updateImage(handle, mips, strides, 1,
                                   UInt2{ (uint32_t)W, (uint32_t)H },
                                   c.format,
                                   /*fromGpu=*/true,
                                   0, 0, 0);

    bool ok = false;
    if (!result.imGuiReference)
    {
        fprintf(stderr,
                "[%s][%s] FAIL: updateImage returned no imGuiReference\n",
                c.name, useDirect ? "direct" : "pbo");
    }
    else
    {
        GLuint tex = (GLuint)(intptr_t)result.imGuiReference;
        std::vector<uint8_t> roundtrip(byteCount, 0);

        glBindTexture(GL_TEXTURE_2D, tex);
        GLint prevAlign = 4;
        glGetIntegerv(GL_PACK_ALIGNMENT, &prevAlign);
        glPixelStorei(GL_PACK_ALIGNMENT, 1);
        // BGRA direct interop stores raw BGRA bytes in RGBA storage and
        // relies on texture swizzle for logical sampling. Reading as GL_RGBA
        // checks the stored byte copy; reading as GL_BGRA would ask GL to
        // swap red/blue again and fail a correct direct upload.
        const GLenum readFormat = (c.format == PixelFormat::eBGRA8_UNORM && useDirect)
            ? GL_RGBA
            : c.glFormat;
        glGetTexImage(GL_TEXTURE_2D, 0, readFormat, c.glType, roundtrip.data());
        glPixelStorei(GL_PACK_ALIGNMENT, prevAlign);
        glBindTexture(GL_TEXTURE_2D, 0);

        GLenum err = glGetError();
        if (err != GL_NO_ERROR)
        {
            fprintf(stderr,
                    "[%s][%s] FAIL: glGetTexImage error 0x%x\n",
                    c.name, useDirect ? "direct" : "pbo", err);
        }
        else
        {
            size_t mismatches = 0;
            for (size_t i = 0; i < ref.size(); ++i)
                if (ref[i] != roundtrip[i]) ++mismatches;
            if (mismatches == 0)
            {
                fprintf(stdout, "[%s][%s] PASS (%zu bytes round-trip)\n",
                        c.name, useDirect ? "direct" : "pbo", ref.size());
                ok = true;
            }
            else
            {
                fprintf(stderr,
                        "[%s][%s] FAIL: %zu / %zu bytes mismatched\n",
                        c.name, useDirect ? "direct" : "pbo",
                        mismatches, ref.size());
            }
        }
    }

    gpu->destroyState(handle);
    cudaFree(dPtr);
    return ok;
}
} // namespace

int main()
{
    fprintf(stdout, "=== OpenGL byteImageGpu all-format fromGpu test (128x128) ===\n");

#if defined(_WIN32)
    _putenv_s("OMNIUI_HEADLESS", "1");
    _putenv_s("OMNIUI_HEADLESS_GL", "1");
    _putenv_s("OMNIUI_EGL_FORCE_SURFACELESS", "1");
#else
    setenv("OMNIUI_HEADLESS", "1", 1);
    setenv("OMNIUI_HEADLESS_GL", "1", 1);
    setenv("OMNIUI_EGL_FORCE_SURFACELESS", "1", 1);
#endif

    if (!standalone::init("texture_format_test", 256, 256))
    {
        fprintf(stderr, "FATAL: standalone::init failed\n");
        return 1;
    }

    IByteImageGpu* gpu = PlatformRegistry::instance().byteImageGpu();
    if (!gpu)
    {
        fprintf(stderr, "FATAL: byteImageGpu() is null — EGL init did not register OpenGLByteImageGpu\n");
        standalone::shutdown();
        return 1;
    }

    if (!gpu->supportsFromGpu())
    {
        fprintf(stdout, "SKIP: OpenGLByteImageGpu::supportsFromGpu()==false "
                        "(CUDA driver/runtime not present); nothing to test.\n");
        standalone::shutdown();
        return 0;
    }

    int failures = 0;
    int caseCount = 0;
    for (const auto& c : kCases)
    {
        for (bool useDirect : { true, false })
        {
            ++caseCount;
            if (!runCase(gpu, c, useDirect)) ++failures;
        }
    }

    standalone::shutdown();

    fprintf(stdout, "=== %d / %d cases passed ===\n", caseCount - failures, caseCount);
    if (failures > 0)
    {
        fprintf(stdout, "FAIL\n");
        return 1;
    }
    fprintf(stdout, "PASS\n");
    return 0;
}
