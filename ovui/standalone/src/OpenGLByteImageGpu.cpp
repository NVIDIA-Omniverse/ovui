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

#include "OpenGLByteImageGpu.h"

#include <glad/glad.h>

#include <atomic>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#if OMNIUI_HAS_CUDA
#  include <cuda_runtime.h>
#  include <cuda_gl_interop.h>
#endif

namespace omni {
namespace ui {
namespace standalone {

/// Per-provider GPU state: holds the current GL texture name plus the
/// CUDA-GL interop scratch buffer used by the fromGpu path.
struct GpuState
{
    GLuint texture = 0;
    int width = 0;
    int height = 0;
    PixelFormat format = PixelFormat::eRGBA8_UNORM;
    /// Whether the current texture's swizzle was configured for the
    /// direct-interop path. The BGRA8 case needs a swizzle on the direct
    /// path (CUDA writes raw bytes) but not on the PBO path (GL handles
    /// the swap). When this flips relative to ``m_useDirectInterop`` for a
    /// BGRA texture, the texture must be recreated.
    bool textureForDirectInterop = true;

#if OMNIUI_HAS_CUDA
    // Either a registered PBO (PBO path) or the registered texture itself
    // (direct interop path). ``cudaResIsTexture`` distinguishes which one.
    GLuint pbo = 0;
    cudaGraphicsResource_t cudaRes = nullptr;
    bool cudaResIsTexture = false;
    size_t pboBytes = 0;
#endif
};

#if OMNIUI_HAS_CUDA
namespace {

// Whitelist of pixel formats the GL fromGpu path knows how to upload.
// Float AOV formats (R/RG/RGB/RGBA × 16/32-bit float) are accepted in
// addition to the 8-bit baseline so renderers can surface NormalSD,
// CameraposSD, DepthSD, etc. without quantising on the producer side.
static bool isSupportedFromGpuFormat(PixelFormat format)
{
    switch (format)
    {
        case PixelFormat::eRGBA8_UNORM:
        case PixelFormat::eRGBA8_SRGB:
        case PixelFormat::eBGRA8_UNORM:
        case PixelFormat::eR8_UNORM:
        case PixelFormat::eR16_FLOAT:
        case PixelFormat::eR32_FLOAT:
        case PixelFormat::eRG16_FLOAT:
        case PixelFormat::eRG32_FLOAT:
        case PixelFormat::eRGB16_FLOAT:
        case PixelFormat::eRGB32_FLOAT:
        case PixelFormat::eRGBA16_FLOAT:
        case PixelFormat::eRGBA32_FLOAT:
            return true;
        default:
            return false;
    }
}

// CUDA-GL direct interop (``cudaGraphicsGLRegisterImage`` +
// ``cudaMemcpy2DToArrayAsync``) supports 1, 2, and 4-channel formats.
// 3-channel textures (``GL_RGB16F``/``GL_RGB32F``) are NOT listed in
// CUDA's supported-formats table — registering one returns
// ``cudaErrorUnknown`` on current drivers. Force those through the PBO
// path even when ``m_useDirectInterop`` is enabled.
static bool isDirectInteropCompatibleFormat(PixelFormat format)
{
    switch (format)
    {
        case PixelFormat::eRGB16_FLOAT:
        case PixelFormat::eRGB32_FLOAT:
            return false;
        default:
            return true;
    }
}

// Resolve a PixelFormat into the (internalFormat, format, type) triple
// the GL upload calls consume. Returns false when no mapping exists;
// callers bail with an empty UpdateResult.
static bool resolveGlFormat(PixelFormat pixelFormat,
                            GLenum& glInternalFormat,
                            GLenum& glFormat,
                            GLenum& glType)
{
    switch (pixelFormat)
    {
        case PixelFormat::eRGBA8_UNORM:
            glInternalFormat = GL_RGBA8;        glFormat = GL_RGBA; glType = GL_UNSIGNED_BYTE; return true;
        case PixelFormat::eRGBA8_SRGB:
            glInternalFormat = GL_SRGB8_ALPHA8; glFormat = GL_RGBA; glType = GL_UNSIGNED_BYTE; return true;
        case PixelFormat::eBGRA8_UNORM:
            glInternalFormat = GL_RGBA8;        glFormat = GL_BGRA; glType = GL_UNSIGNED_BYTE; return true;
        case PixelFormat::eR8_UNORM:
            glInternalFormat = GL_R8;           glFormat = GL_RED;  glType = GL_UNSIGNED_BYTE; return true;
        case PixelFormat::eR16_FLOAT:
            glInternalFormat = GL_R16F;         glFormat = GL_RED;  glType = GL_HALF_FLOAT;    return true;
        case PixelFormat::eR32_FLOAT:
            glInternalFormat = GL_R32F;         glFormat = GL_RED;  glType = GL_FLOAT;         return true;
        case PixelFormat::eRG16_FLOAT:
            glInternalFormat = GL_RG16F;        glFormat = GL_RG;   glType = GL_HALF_FLOAT;    return true;
        case PixelFormat::eRG32_FLOAT:
            glInternalFormat = GL_RG32F;        glFormat = GL_RG;   glType = GL_FLOAT;         return true;
        case PixelFormat::eRGB16_FLOAT:
            glInternalFormat = GL_RGB16F;       glFormat = GL_RGB;  glType = GL_HALF_FLOAT;    return true;
        case PixelFormat::eRGB32_FLOAT:
            glInternalFormat = GL_RGB32F;       glFormat = GL_RGB;  glType = GL_FLOAT;         return true;
        case PixelFormat::eRGBA16_FLOAT:
            glInternalFormat = GL_RGBA16F;      glFormat = GL_RGBA; glType = GL_HALF_FLOAT;    return true;
        case PixelFormat::eRGBA32_FLOAT:
            glInternalFormat = GL_RGBA32F;      glFormat = GL_RGBA; glType = GL_FLOAT;         return true;
        default:
            return false;
    }
}

// Lazy runtime probe — returns true once a CUDA driver + device is
// confirmed to be present. Cached after the first call so we never re-pay
// the driver init cost. The result is racy on the first call across
// threads, but each thread either sees the cached value or computes the
// same answer; the cached store is monotonic.
static bool cudaRuntimeAvailable()
{
    static std::atomic<int> cached{-1}; // -1 unknown, 0 absent, 1 present
    int v = cached.load(std::memory_order_relaxed);
    if (v >= 0)
        return v == 1;
    int count = 0;
    cudaError_t err = cudaGetDeviceCount(&count);
    const bool ok = (err == cudaSuccess && count > 0);
    cached.store(ok ? 1 : 0, std::memory_order_relaxed);
    return ok;
}

// Drop any CUDA-GL registration the state currently holds. Whether the
// resource points at the PBO or directly at the texture, the unregister
// call is identical; the trailing ``GpuState`` fields just need to be
// cleared accordingly.
static void releaseCudaInterop(GpuState* state)
{
    if (!state)
        return;
    if (state->cudaRes)
    {
        cudaGraphicsUnregisterResource(state->cudaRes);
        state->cudaRes = nullptr;
    }
    state->cudaResIsTexture = false;
    if (state->pbo)
    {
        glDeleteBuffers(1, &state->pbo);
        state->pbo = 0;
    }
    state->pboBytes = 0;
}

// Allocate / resize the PBO and (re)register it with CUDA. Returns true
// when the PBO is ready to map. Idempotent — only does work when size or
// the registration is missing.
static bool ensureCudaPbo(GpuState* state, size_t byteSize)
{
    if (state->pbo && state->cudaRes && !state->cudaResIsTexture
        && state->pboBytes == byteSize)
        return true;

    releaseCudaInterop(state);

    glGenBuffers(1, &state->pbo);
    if (!state->pbo)
    {
        fprintf(stderr, "OpenGLByteImageGpu: glGenBuffers (PBO) failed\n");
        return false;
    }
    glBindBuffer(GL_PIXEL_UNPACK_BUFFER, state->pbo);
    glBufferData(GL_PIXEL_UNPACK_BUFFER, (GLsizeiptr)byteSize, nullptr, GL_STREAM_DRAW);
    glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0);

    cudaError_t err = cudaGraphicsGLRegisterBuffer(
        &state->cudaRes, state->pbo, cudaGraphicsRegisterFlagsWriteDiscard);
    if (err != cudaSuccess)
    {
        fprintf(stderr,
                "OpenGLByteImageGpu: cudaGraphicsGLRegisterBuffer failed: %s\n",
                cudaGetErrorString(err));
        glDeleteBuffers(1, &state->pbo);
        state->pbo = 0;
        return false;
    }
    state->cudaResIsTexture = false;
    state->pboBytes = byteSize;
    return true;
}

// Copy the caller's CUDA device pointer (possibly pitched) into the
// registered PBO. The PBO is laid out tightly at ``rowBytes`` per row,
// so we always use ``cudaMemcpy2DAsync`` to translate any source pitch
// into the tight destination layout that ``glTexSubImage2D`` expects.
// CUDA's GL interop inserts the cross-API barriers via map/unmap on
// stream 0 — no explicit glFinish/glFlush needed.
static bool copyDeviceToPbo(GpuState* state, const void* srcDptr,
                            size_t srcPitch, size_t rowBytes, size_t height)
{
    cudaError_t err = cudaGraphicsMapResources(1, &state->cudaRes, 0);
    if (err != cudaSuccess)
    {
        fprintf(stderr, "OpenGLByteImageGpu: cudaGraphicsMapResources failed: %s\n",
                cudaGetErrorString(err));
        return false;
    }
    void* dst = nullptr;
    size_t mappedSize = 0;
    err = cudaGraphicsResourceGetMappedPointer(&dst, &mappedSize, state->cudaRes);
    const size_t needed = rowBytes * height;
    if (err == cudaSuccess && needed <= mappedSize && dst != nullptr)
    {
        err = cudaMemcpy2DAsync(dst, /*dpitch=*/rowBytes,
                                srcDptr, /*spitch=*/srcPitch,
                                /*width=*/rowBytes, /*height=*/height,
                                cudaMemcpyDeviceToDevice, /*stream=*/0);
    }
    cudaError_t unmapErr = cudaGraphicsUnmapResources(1, &state->cudaRes, 0);
    if (err != cudaSuccess)
    {
        fprintf(stderr, "OpenGLByteImageGpu: cudaMemcpy2DAsync(D2D) failed: %s\n",
                cudaGetErrorString(err));
        return false;
    }
    if (unmapErr != cudaSuccess)
    {
        fprintf(stderr, "OpenGLByteImageGpu: cudaGraphicsUnmapResources failed: %s\n",
                cudaGetErrorString(unmapErr));
        return false;
    }
    return true;
}

// Register the GL texture itself with CUDA. The texture must already
// exist with the right size + internal format (callers handle that).
// Idempotent: returns early when the registration already targets this
// texture handle. Re-register on resize/format-change is the caller's
// responsibility (they recreate the texture, which invalidates ``cudaRes``).
static bool ensureCudaTextureInterop(GpuState* state)
{
    if (state->cudaRes && state->cudaResIsTexture)
        return true;

    releaseCudaInterop(state);

    if (!state->texture)
    {
        fprintf(stderr,
                "OpenGLByteImageGpu: ensureCudaTextureInterop without a texture\n");
        return false;
    }
    cudaError_t err = cudaGraphicsGLRegisterImage(
        &state->cudaRes,
        state->texture,
        GL_TEXTURE_2D,
        cudaGraphicsRegisterFlagsWriteDiscard);
    if (err != cudaSuccess)
    {
        fprintf(stderr,
                "OpenGLByteImageGpu: cudaGraphicsGLRegisterImage failed: %s\n",
                cudaGetErrorString(err));
        state->cudaRes = nullptr;
        return false;
    }
    state->cudaResIsTexture = true;
    return true;
}

// Copy the caller's (possibly pitched) device pointer straight into the
// texture's ``cudaArray`` — single GPU→GPU copy, no PBO middleman, no
// ``glTexSubImage2D``. The cudaArray is in the driver's preferred
// (typically block-linear) layout; ``cudaMemcpy2DToArrayAsync`` performs
// the linear→tiled conversion inline on the GPU.
//
// ``srcPitch`` is the byte stride between source rows (may be larger
// than ``rowBytes`` when the source came from ``cudaMallocPitch`` or an
// NVENC output buffer). ``rowBytes`` is the actual number of bytes per
// row to transfer.
static bool copyDeviceToTextureViaInterop(
    GpuState* state, const void* srcDptr,
    size_t srcPitch, size_t rowBytes, int height)
{
    cudaError_t err = cudaGraphicsMapResources(1, &state->cudaRes, 0);
    if (err != cudaSuccess)
    {
        fprintf(stderr, "OpenGLByteImageGpu: cudaGraphicsMapResources (tex) failed: %s\n",
                cudaGetErrorString(err));
        return false;
    }
    cudaArray_t array = nullptr;
    err = cudaGraphicsSubResourceGetMappedArray(&array, state->cudaRes, 0, 0);
    if (err == cudaSuccess && array != nullptr)
    {
        err = cudaMemcpy2DToArrayAsync(
            array,
            /*wOffset=*/0,
            /*hOffset=*/0,
            srcDptr,
            /*spitch=*/srcPitch,
            /*width=*/rowBytes,
            (size_t)height,
            cudaMemcpyDeviceToDevice,
            /*stream=*/0);
    }
    cudaError_t unmapErr = cudaGraphicsUnmapResources(1, &state->cudaRes, 0);
    if (err != cudaSuccess)
    {
        fprintf(stderr, "OpenGLByteImageGpu: cudaMemcpy2DToArrayAsync failed: %s\n",
                cudaGetErrorString(err));
        return false;
    }
    if (unmapErr != cudaSuccess)
    {
        fprintf(stderr, "OpenGLByteImageGpu: cudaGraphicsUnmapResources (tex) failed: %s\n",
                cudaGetErrorString(unmapErr));
        return false;
    }
    return true;
}

} // namespace
#endif // OMNIUI_HAS_CUDA

IByteImageGpu::Handle OpenGLByteImageGpu::createState()
{
    return new GpuState();
}

void OpenGLByteImageGpu::destroyState(Handle h)
{
    auto* state = static_cast<GpuState*>(h);
    if (!state)
        return;
#if OMNIUI_HAS_CUDA
    releaseCudaInterop(state);
#endif
    if (state->texture)
    {
        glDeleteTextures(1, &state->texture);
    }
    delete state;
}

IByteImageGpu::UpdateResult OpenGLByteImageGpu::updateImage(
    Handle h,
    const uint8_t* const* mipMapBuffers,
    size_t* mipMapStrides,
    size_t mipMapCount,
    UInt2 size,
    PixelFormat format,
    bool fromGpu,
    uint32_t /*gpuDeviceMask*/,
    uint32_t /*textureUsageFlags*/,
    uint32_t /*resourceUsageFlags*/)
{
    auto* state = static_cast<GpuState*>(h);
    if (!state || !mipMapBuffers || mipMapCount == 0 || size.x == 0 || size.y == 0)
        return {};

    // fromGpu (CUDA device pointer) — CUDA-GL interop. Two paths:
    //
    //   * Direct (default): the texture itself is registered with CUDA via
    //     ``cudaGraphicsGLRegisterImage``; ``cudaMemcpy2DToArrayAsync``
    //     writes straight into its ``cudaArray``. One GPU→GPU copy.
    //
    //   * PBO fallback (``setUseDirectInterop(false)``): copy device
    //     pointer → registered PBO via ``cudaMemcpyAsync``, then
    //     ``glTexSubImage2D`` into the texture. Two GPU→GPU copies.
    //     Available for drivers / formats where the direct path
    //     misbehaves.
    //
    // Compiled out when CUDA isn't available.
    if (fromGpu)
    {
#if OMNIUI_HAS_CUDA
        if (!isSupportedFromGpuFormat(format))
        {
            static std::atomic<bool> warned{false};
            if (!warned.exchange(true, std::memory_order_relaxed))
                fprintf(stderr,
                        "OpenGLByteImageGpu: fromGpu unsupported pixel format %d\n",
                        (int)format);
            return {};
        }
        const size_t bpp = getPixelFormatSize(format);
        if (!mipMapBuffers[0])
        {
            fprintf(stderr, "OpenGLByteImageGpu: fromGpu called with null device pointer\n");
            return {};
        }
        // Mip > 1 on the fromGpu path is not implemented — only mip 0
        // would be uploaded. Latched warning so the caller hears about it
        // without per-frame log spam.
        if (mipMapCount > 1)
        {
            static std::atomic<bool> warned{false};
            if (!warned.exchange(true, std::memory_order_relaxed))
                fprintf(stderr,
                        "OpenGLByteImageGpu: fromGpu with mipMapCount=%zu — only mip 0 will be uploaded\n",
                        mipMapCount);
        }

        const size_t rowBytes = (size_t)size.x * bpp;
        const size_t srcPitch = (mipMapStrides && mipMapStrides[0])
            ? mipMapStrides[0]
            : rowBytes;
        const size_t byteSize = rowBytes * (size_t)size.y;

        // 1. Ensure GL texture exists at the right size/format.
        // sRGB needs ``GL_SRGB8_ALPHA8`` so sampling de-gammas; the
        // baseline conflated this with ``GL_RGBA8``. ``glType`` carries
        // the data-type of the source bytes (GL_UNSIGNED_BYTE for 8-bit,
        // GL_HALF_FLOAT / GL_FLOAT for the float AOV formats); the PBO
        // path threads it back into ``glTexSubImage2D`` so the driver
        // doesn't reinterpret float bits as unsigned bytes.
        GLenum glInternalFormat = GL_RGBA8;
        GLenum glFormat = GL_RGBA;
        GLenum glType = GL_UNSIGNED_BYTE;
        if (!resolveGlFormat(format, glInternalFormat, glFormat, glType))
            return {};

        // 3-channel float textures cannot be registered with
        // ``cudaGraphicsGLRegisterImage`` (CUDA's supported-formats
        // table excludes GL_RGB*); transparently fall through to the
        // PBO path. Other formats follow the configured interop mode.
        const bool useDirectThisCall = m_useDirectInterop &&
                                       isDirectInteropCompatibleFormat(format);
        // The BGRA direct path stores raw BGRA bytes in a GL_RGBA8 texture
        // and asks GL to swizzle on sample (CUDA does no channel reorder).
        // The PBO path lets ``glTexSubImage2D(... GL_BGRA, ...)`` do the
        // swap and uses identity swizzle. That means the texture's swizzle
        // depends on which path is active — track it so a runtime toggle
        // of ``setUseDirectInterop`` against an existing BGRA texture
        // forces a recreate.
        const bool needCreateTex = (state->texture == 0 ||
                                    state->width != (int)size.x ||
                                    state->height != (int)size.y ||
                                    state->format != format ||
                                    (format == PixelFormat::eBGRA8_UNORM &&
                                     state->textureForDirectInterop != useDirectThisCall));
        if (needCreateTex)
        {
            // Drop the CUDA registration before deleting the texture
            // (the registration is bound to the GL handle).
            releaseCudaInterop(state);
            if (state->texture)
                glDeleteTextures(1, &state->texture);
            glGenTextures(1, &state->texture);
            if (state->texture == 0)
            {
                fprintf(stderr, "OpenGLByteImageGpu: glGenTextures (fromGpu) failed\n");
                return {};
            }
            glBindTexture(GL_TEXTURE_2D, state->texture);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
            // Pick swizzle by (format, interop mode):
            //   * R8: replicate red into RGB, alpha = red (for font glyphs).
            //   * R16F / R32F: replicate red into RGB, alpha = 1
            //     (grayscale single-channel viz: depth, scalar AOVs).
            //   * RG16F / RG32F: red+green, blue = 0, alpha = 1.
            //   * RGB16F / RGB32F: RGB identity, alpha = 1 (no native
            //     alpha channel exists, so force opaque on sample).
            //   * BGRA + direct: re-order stored BGRA bytes to logical RGBA
            //     on sample.
            //   * everything else: identity.
            GLint swizzle[4] = {GL_RED, GL_GREEN, GL_BLUE, GL_ALPHA};
            if (format == PixelFormat::eR8_UNORM)
            {
                swizzle[0] = GL_ONE;
                swizzle[1] = GL_ONE;
                swizzle[2] = GL_ONE;
                swizzle[3] = GL_RED;
            }
            else if (format == PixelFormat::eR16_FLOAT ||
                     format == PixelFormat::eR32_FLOAT)
            {
                swizzle[0] = GL_RED;
                swizzle[1] = GL_RED;
                swizzle[2] = GL_RED;
                swizzle[3] = GL_ONE;
            }
            else if (format == PixelFormat::eRG16_FLOAT ||
                     format == PixelFormat::eRG32_FLOAT)
            {
                swizzle[0] = GL_RED;
                swizzle[1] = GL_GREEN;
                swizzle[2] = GL_ZERO;
                swizzle[3] = GL_ONE;
            }
            else if (format == PixelFormat::eRGB16_FLOAT ||
                     format == PixelFormat::eRGB32_FLOAT)
            {
                swizzle[0] = GL_RED;
                swizzle[1] = GL_GREEN;
                swizzle[2] = GL_BLUE;
                swizzle[3] = GL_ONE;
            }
            else if (format == PixelFormat::eBGRA8_UNORM && useDirectThisCall)
            {
                swizzle[0] = GL_BLUE;
                swizzle[1] = GL_GREEN;
                swizzle[2] = GL_RED;
                swizzle[3] = GL_ALPHA;
            }
            glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_SWIZZLE_RGBA, swizzle);
            glTexImage2D(GL_TEXTURE_2D, 0, glInternalFormat,
                         (GLsizei)size.x, (GLsizei)size.y, 0,
                         glFormat, glType, nullptr);
            glBindTexture(GL_TEXTURE_2D, 0);
            state->width = (int)size.x;
            state->height = (int)size.y;
            state->format = format;
            state->textureForDirectInterop = useDirectThisCall;
        }

        if (useDirectThisCall)
        {
            // 2a. Register the texture with CUDA (idempotent across
            //     frames; recreate above already dropped any prior
            //     registration).
            if (!ensureCudaTextureInterop(state))
                return {};
            // 3a. CUDA device ptr → texture cudaArray. Single copy;
            //     ``glTexSubImage2D`` is not needed. ``srcPitch`` honors
            //     pitched CUDA allocations (cudaMallocPitch / NVENC).
            if (!copyDeviceToTextureViaInterop(
                    state, mipMapBuffers[0], srcPitch, rowBytes, (int)size.y))
                return {};
            // Leave GL_TEXTURE_2D unbound (matches CPU path's contract).
            glBindTexture(GL_TEXTURE_2D, 0);
        }
        else
        {
            // 2b. Ensure the PBO is allocated + registered with CUDA at
            //     the correct size. Resize releases and re-registers.
            if (!ensureCudaPbo(state, byteSize))
                return {};
            // 3b. CUDA → PBO (GPU→GPU memcpy via mapped pointer). The
            //     PBO is tightly packed; ``copyDeviceToPbo`` translates
            //     the source's ``srcPitch`` to the tight dst pitch.
            if (!copyDeviceToPbo(state, mipMapBuffers[0],
                                 srcPitch, rowBytes, (size_t)size.y))
                return {};
            // 4b. PBO → texture (driver-internal upload, stays on GPU).
            //     R8 packed at 1 byte/pixel breaks GL's default
            //     ``GL_UNPACK_ALIGNMENT=4`` for odd widths — set 1 to be
            //     safe for all formats and restore after.
            glBindTexture(GL_TEXTURE_2D, state->texture);
            glBindBuffer(GL_PIXEL_UNPACK_BUFFER, state->pbo);
            GLint prevAlign = 4;
            glGetIntegerv(GL_UNPACK_ALIGNMENT, &prevAlign);
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
            glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0,
                            (GLsizei)size.x, (GLsizei)size.y,
                            glFormat, glType, nullptr);
            glPixelStorei(GL_UNPACK_ALIGNMENT, prevAlign);
            glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0);
            glBindTexture(GL_TEXTURE_2D, 0);
        }

        UpdateResult resGpu;
        resGpu.imGuiReference = reinterpret_cast<void*>(static_cast<intptr_t>(state->texture));
        return resGpu;
#else
        static std::atomic<bool> warned{false};
        if (!warned.exchange(true, std::memory_order_relaxed))
            fprintf(stderr, "OpenGLByteImageGpu: fromGpu requires CUDA support "
                            "(not compiled in)\n");
        return {};
#endif
    }

    // Determine GL format from PixelFormat. ``GL_SRGB8_ALPHA8`` is the
    // de-gamma'ing internal format; the baseline used GL_RGBA8 for both
    // eRGBA8_UNORM and eRGBA8_SRGB which silently linearised sRGB inputs.
    GLenum glInternalFormat = GL_RGBA8;
    GLenum glFormat = GL_RGBA;
    GLenum glType = GL_UNSIGNED_BYTE;
#if OMNIUI_HAS_CUDA
    if (!resolveGlFormat(format, glInternalFormat, glFormat, glType))
    {
        fprintf(stderr, "OpenGLByteImageGpu: unsupported pixel format %d\n", (int)format);
        return {};
    }
#else
    // Inline the mapping when CUDA is compiled out so the helper above
    // (gated by OMNIUI_HAS_CUDA) is not required.
    switch (format)
    {
        case PixelFormat::eRGBA8_UNORM:
            glInternalFormat = GL_RGBA8;        glFormat = GL_RGBA; glType = GL_UNSIGNED_BYTE; break;
        case PixelFormat::eRGBA8_SRGB:
            glInternalFormat = GL_SRGB8_ALPHA8; glFormat = GL_RGBA; glType = GL_UNSIGNED_BYTE; break;
        case PixelFormat::eBGRA8_UNORM:
            glInternalFormat = GL_RGBA8;        glFormat = GL_BGRA; glType = GL_UNSIGNED_BYTE; break;
        case PixelFormat::eR8_UNORM:
            glInternalFormat = GL_R8;           glFormat = GL_RED;  glType = GL_UNSIGNED_BYTE; break;
        case PixelFormat::eR16_FLOAT:
            glInternalFormat = GL_R16F;         glFormat = GL_RED;  glType = GL_HALF_FLOAT;    break;
        case PixelFormat::eR32_FLOAT:
            glInternalFormat = GL_R32F;         glFormat = GL_RED;  glType = GL_FLOAT;         break;
        case PixelFormat::eRG16_FLOAT:
            glInternalFormat = GL_RG16F;        glFormat = GL_RG;   glType = GL_HALF_FLOAT;    break;
        case PixelFormat::eRG32_FLOAT:
            glInternalFormat = GL_RG32F;        glFormat = GL_RG;   glType = GL_FLOAT;         break;
        case PixelFormat::eRGB16_FLOAT:
            glInternalFormat = GL_RGB16F;       glFormat = GL_RGB;  glType = GL_HALF_FLOAT;    break;
        case PixelFormat::eRGB32_FLOAT:
            glInternalFormat = GL_RGB32F;       glFormat = GL_RGB;  glType = GL_FLOAT;         break;
        case PixelFormat::eRGBA16_FLOAT:
            glInternalFormat = GL_RGBA16F;      glFormat = GL_RGBA; glType = GL_HALF_FLOAT;    break;
        case PixelFormat::eRGBA32_FLOAT:
            glInternalFormat = GL_RGBA32F;      glFormat = GL_RGBA; glType = GL_FLOAT;         break;
        default:
            fprintf(stderr, "OpenGLByteImageGpu: unsupported pixel format %d\n", (int)format);
            return {};
    }
#endif

    // Reuse existing texture if size + format match, otherwise recreate.
    bool needCreate = (state->texture == 0 ||
                       state->width != (int)size.x ||
                       state->height != (int)size.y ||
                       state->format != format);

    if (needCreate)
    {
#if OMNIUI_HAS_CUDA
        // Drop any CUDA-GL registration before deleting the texture so a
        // subsequent fromGpu call re-registers cleanly.
        releaseCudaInterop(state);
#endif
        if (state->texture)
        {
            glDeleteTextures(1, &state->texture);
            state->texture = 0;
        }

        glGenTextures(1, &state->texture);
        if (state->texture == 0)
        {
            fprintf(stderr, "OpenGLByteImageGpu: glGenTextures failed\n");
            return {};
        }

        glBindTexture(GL_TEXTURE_2D, state->texture);

        // Set filtering based on mip count
        if (mipMapCount > 1)
        {
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
        }
        else
        {
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        }
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

        if (format == PixelFormat::eR8_UNORM)
        {
            // Swizzle R8 so alpha gets the red channel (for font rendering)
            GLint swizzle[] = {GL_ONE, GL_ONE, GL_ONE, GL_RED};
            glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_SWIZZLE_RGBA, swizzle);
        }
        else if (format == PixelFormat::eR16_FLOAT ||
                 format == PixelFormat::eR32_FLOAT)
        {
            // Grayscale single-channel float: replicate red, opaque alpha.
            GLint swizzle[] = {GL_RED, GL_RED, GL_RED, GL_ONE};
            glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_SWIZZLE_RGBA, swizzle);
        }
        else if (format == PixelFormat::eRG16_FLOAT ||
                 format == PixelFormat::eRG32_FLOAT)
        {
            GLint swizzle[] = {GL_RED, GL_GREEN, GL_ZERO, GL_ONE};
            glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_SWIZZLE_RGBA, swizzle);
        }
        else if (format == PixelFormat::eRGB16_FLOAT ||
                 format == PixelFormat::eRGB32_FLOAT)
        {
            GLint swizzle[] = {GL_RED, GL_GREEN, GL_BLUE, GL_ONE};
            glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_SWIZZLE_RGBA, swizzle);
        }

        // Allocate storage for all mip levels
        if (mipMapCount > 1)
        {
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, (GLint)(mipMapCount - 1));
        }

        // Float formats and R8 break GL's default unpack alignment of 4
        // when the row pitch isn't a multiple of 4 bytes (e.g. R8 odd-
        // width, RGB16F any width). Use a tight alignment for the upload
        // and restore the caller's previous value after.
        GLint prevAlignCreate = 4;
        glGetIntegerv(GL_UNPACK_ALIGNMENT, &prevAlignCreate);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);

        uint32_t mipW = size.x;
        uint32_t mipH = size.y;
        for (size_t mip = 0; mip < mipMapCount; ++mip)
        {
            glTexImage2D(GL_TEXTURE_2D, (GLint)mip, glInternalFormat,
                         (GLsizei)mipW, (GLsizei)mipH, 0,
                         glFormat, glType, mipMapBuffers[mip]);
            if (mipW > 1) mipW /= 2;
            if (mipH > 1) mipH /= 2;
        }

        glPixelStorei(GL_UNPACK_ALIGNMENT, prevAlignCreate);

        state->width = (int)size.x;
        state->height = (int)size.y;
        state->format = format;
        // Texture was created with identity (or R8) swizzle, not the
        // BGRA-direct {B,G,R,A} swizzle. Mark accordingly so a later
        // fromGpu+BGRA update sees the mismatch and forces a recreate.
        state->textureForDirectInterop = false;
    }
    else
    {
        // Update existing texture data.
#if OMNIUI_HAS_CUDA
        // If the previous frame was a fromGpu update on the direct path,
        // the texture is still registered with CUDA via
        // cudaGraphicsGLRegisterImage. Writing to a CUDA-registered
        // resource (especially WriteDiscard) from GL outside of map/unmap
        // is undefined per the CUDA-GL interop spec — drop the
        // registration first so the upcoming glTexSubImage2D is legal.
        if (state->cudaResIsTexture)
            releaseCudaInterop(state);
#endif
        glBindTexture(GL_TEXTURE_2D, state->texture);
        // The texture may have been created by a previous fromGpu+direct
        // BGRA call with a {B,G,R,A} sample swizzle. ``glTexSubImage2D``
        // with GL_BGRA writes correctly-ordered RGBA into storage, so
        // the stale direct swizzle would re-swap red/blue on sample.
        // Reset to identity for the CPU-path BGRA case.
        if (format == PixelFormat::eBGRA8_UNORM && state->textureForDirectInterop)
        {
            GLint swizzle[] = {GL_RED, GL_GREEN, GL_BLUE, GL_ALPHA};
            glTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_SWIZZLE_RGBA, swizzle);
            state->textureForDirectInterop = false;
        }
        GLint prevAlignUpdate = 4;
        glGetIntegerv(GL_UNPACK_ALIGNMENT, &prevAlignUpdate);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);

        uint32_t mipW = size.x;
        uint32_t mipH = size.y;
        for (size_t mip = 0; mip < mipMapCount; ++mip)
        {
            glTexSubImage2D(GL_TEXTURE_2D, (GLint)mip, 0, 0,
                            (GLsizei)mipW, (GLsizei)mipH,
                            glFormat, glType, mipMapBuffers[mip]);
            if (mipW > 1) mipW /= 2;
            if (mipH > 1) mipH /= 2;
        }

        glPixelStorei(GL_UNPACK_ALIGNMENT, prevAlignUpdate);
    }

    glBindTexture(GL_TEXTURE_2D, 0);

    UpdateResult result;
    result.imGuiReference = reinterpret_cast<void*>(static_cast<intptr_t>(state->texture));
    return result;
}

void OpenGLByteImageGpu::releaseImage(Handle h)
{
    auto* state = static_cast<GpuState*>(h);
    if (!state)
        return;
#if OMNIUI_HAS_CUDA
    releaseCudaInterop(state);
#endif
    if (state->texture)
    {
        glDeleteTextures(1, &state->texture);
        state->texture = 0;
        state->width = 0;
        state->height = 0;
        state->format = PixelFormat::eRGBA8_UNORM;
        state->textureForDirectInterop = true;
    }
}

namespace {

// Recognise truthy-falsy strings for OMNIUI_OPENGL_INTEROP_DIRECT.
// Spec is intentionally narrow: only "0" or case-insensitive "false"
// disable the direct path.
static bool envIsFalse(const char* s)
{
    if (!s || !*s)
        return false;
    char buf[8] = {};
    size_t i = 0;
    for (; i < sizeof(buf) - 1 && s[i]; ++i)
        buf[i] = (char)std::tolower((unsigned char)s[i]);
    if (s[i] != '\0')
        return false; // value too long to be "0" or "false"
    buf[i] = '\0';
    return std::strcmp(buf, "0") == 0 || std::strcmp(buf, "false") == 0;
}

} // namespace

OpenGLByteImageGpu::OpenGLByteImageGpu()
{
    // Field override: OMNIUI_OPENGL_INTEROP_DIRECT=0 (or "false") forces
    // the PBO fallback without a rebuild. Anything else (including unset)
    // keeps the default direct-interop path.
    if (envIsFalse(std::getenv("OMNIUI_OPENGL_INTEROP_DIRECT")))
    {
        m_useDirectInterop = false;
    }
}

bool OpenGLByteImageGpu::supportsFromGpu() const
{
#if OMNIUI_HAS_CUDA
    return cudaRuntimeAvailable();
#else
    return false;
#endif
}

} // namespace standalone
} // namespace ui
} // namespace omni
