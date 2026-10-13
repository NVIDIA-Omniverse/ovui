/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/platform/Types.h>

#include <cstddef>
#include <cstdint>

namespace omni
{
namespace ui
{

/// Abstract interface for ByteImageProvider GPU operations.
///
/// In Kit mode, KitByteImageGpu implements this using Kit's IRenderer and
/// IImGuiRenderer. In standalone mode, no implementation is registered
/// (ByteImageProvider methods become no-ops when the interface is absent).
///
/// Registered via PlatformRegistry::setByteImageGpu().
class IByteImageGpu
{
public:
    virtual ~IByteImageGpu() = default;

    /// Opaque handle to per-provider GPU state.
    using Handle = void*;

    /// Result of an updateImage call.
    struct UpdateResult
    {
        void* imGuiReference = nullptr;   ///< ImGui texture ID for rendering.
        void* managedResource = nullptr;  ///< Opaque GpuResource* for resource management.
    };


    /// Create GPU state for a new ByteImageProvider instance.
    virtual Handle createState() = 0;

    /// Destroy GPU state and release all associated resources.
    virtual void destroyState(Handle h) = 0;

    /// Create or update a mip-mapped texture.
    ///
    /// @param h             GPU state handle from createState().
    /// @param mipMapBuffers Array of pointers to mip-level pixel data.
    /// @param mipMapStrides Array of byte strides for each mip level.
    /// @param mipMapCount   Number of mip levels.
    /// @param size          Width and height of the base (mip 0) level.
    /// @param format        Pixel format.
    /// @param fromGpu       True if the data is a GPU/CUDA pointer.
    /// @param gpuDeviceMask       Stored texture option: GPU device mask.
    /// @param textureUsageFlags   Stored texture option: texture usage flags.
    /// @param resourceUsageFlags  Stored texture option: resource usage flags.
    /// @return UpdateResult with the ImGui reference and managed resource.
    virtual UpdateResult updateImage(Handle h,
                                     const uint8_t* const* mipMapBuffers,
                                     size_t* mipMapStrides,
                                     size_t mipMapCount,
                                     UInt2 size,
                                     PixelFormat format,
                                     bool fromGpu,
                                     uint32_t gpuDeviceMask,
                                     uint32_t textureUsageFlags,
                                     uint32_t resourceUsageFlags) = 0;

    /// Release the texture data but keep the state handle alive.
    /// Called when the image is being replaced or the provider is being reset.
    virtual void releaseImage(Handle h) = 0;

    /// Whether this backend's updateImage implements the fromGpu=true branch.
    /// When false, updateImage(..., fromGpu=true, ...) is a no-op (the call
    /// returns an empty UpdateResult and the texture is left unchanged).
    /// Drives `omni.ui.has_gpu_byte_image()` so consumers don't need to
    /// scrape stderr to detect the silent-no-op path.
    virtual bool supportsFromGpu() const { return false; }
    virtual size_t getFormatSize(PixelFormat) const { return 0; }
};

/// Get the byte size per pixel for a given PixelFormat.
OMNIUI_API size_t getPixelFormatSize(PixelFormat format);

/// Check if mipmap generation is supported for a given format.
inline bool isMipGenFormatSupported(PixelFormat format)
{
    return format == PixelFormat::eRGBA8_UNORM || format == PixelFormat::eBGRA8_UNORM ||
           format == PixelFormat::eRGBA8_SRGB;
}

} // namespace ui
} // namespace omni
