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

#pragma once

#include <omni/ui/ImageProvider/IByteImageGpu.h>

namespace omni {
namespace ui {
namespace standalone {

/// Standalone IByteImageGpu implementation using OpenGL.
/// Creates GL textures from raw pixel data and returns ImGui-compatible
/// texture references (GLuint cast to void*).
class OpenGLByteImageGpu final : public IByteImageGpu
{
public:
    /// Reads ``OMNIUI_OPENGL_INTEROP_DIRECT`` once at construction; setting
    /// it to ``0`` or ``false`` (case-insensitive) disables direct-image
    /// CUDA-GL interop and forces the PBO fallback. Useful in the field
    /// without a rebuild when a driver/format combo misbehaves on the
    /// direct path.
    OpenGLByteImageGpu();
    ~OpenGLByteImageGpu() override = default;

    Handle createState() override;
    void destroyState(Handle h) override;
    UpdateResult updateImage(Handle h,
                             const uint8_t* const* mipMapBuffers,
                             size_t* mipMapStrides,
                             size_t mipMapCount,
                             UInt2 size,
                             PixelFormat format,
                             bool fromGpu,
                             uint32_t gpuDeviceMask,
                             uint32_t textureUsageFlags,
                             uint32_t resourceUsageFlags) override;
    void releaseImage(Handle h) override;

    /// Reports whether the fromGpu path is usable on this binary AND host.
    /// Compile-time CUDA support is necessary; runtime probe of
    /// ``cudaGetDeviceCount`` decides the answer (cached after first call).
    /// On CUDA-built binaries running without a CUDA driver / device, this
    /// returns false so callers don't dispatch a doomed fromGpu update.
    bool supportsFromGpu() const override;

    /// Choose the CUDA→GL upload path for ``fromGpu`` updates.
    ///
    /// When ``true`` (default), the texture itself is registered with
    /// CUDA via ``cudaGraphicsGLRegisterImage`` and ``cudaMemcpy2DToArray``
    /// writes straight into the texture's ``cudaArray`` — one GPU copy per
    /// frame, no PBO middleman.
    ///
    /// When ``false``, a Pixel Buffer Object is registered with CUDA, the
    /// device pointer is copied into the PBO, and ``glTexSubImage2D``
    /// uploads the PBO into the texture — two GPU copies per frame.
    /// Available as a fallback when direct-image registration misbehaves
    /// against a particular driver / texture format combination.
    void setUseDirectInterop(bool enabled) { m_useDirectInterop = enabled; }
    bool useDirectInterop() const { return m_useDirectInterop; }

private:
    bool m_useDirectInterop = true;
};

} // namespace standalone
} // namespace ui
} // namespace omni
