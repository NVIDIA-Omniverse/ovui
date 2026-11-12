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

/// What a checked upload achieved. For eFailed, eEnqueued and eComplete the
/// order is meaningful: a larger value means the pixels are further along.
/// eNoBackend is not part of that order.
enum class UploadStatus : uint32_t
{
    /// The new pixels were not accepted. The texture keeps its previous
    /// pixels. A handle that never had a successful upload has no texture.
    eFailed = 0,
    /// The backend accepted the pixels and ordered the copy before later
    /// sampling on its device or queue. The copy can still be running, so this
    /// is not proof that the pixels are visible now. Use the upload id with
    /// IByteImageGpuChecked::getCompletedUploadId to learn when they are.
    eEnqueued = 1,
    /// The copy has finished, and the backend has proof of it (a fence, an
    /// event, or a wait that returned). A draw that starts later samples the
    /// new pixels, and the source can be released. A backend must not report
    /// this when it only submitted the copy.
    eComplete = 2,
    /// No GPU backend is registered, so there is no renderer and nothing was
    /// uploaded. This is not a failure. Only ByteImageProvider reports it; a
    /// backend never does.
    eNoBackend = 3,
};

/// Result of a checked upload.
struct UploadResult
{
    /// Same data as the plain updateImage result. When status is eFailed,
    /// imGuiReference can still hold the previous texture. Do not treat it as
    /// proof of a new upload.
    IByteImageGpu::UpdateResult update;
    UploadStatus status = UploadStatus::eFailed;
    /// Devices the caller asked for. 0 means the default device.
    uint32_t requestedDeviceMask = 0;
    /// Devices that accepted the pixels. The upload counts as accepted only
    /// when every requested device accepted it. A backend that has one device
    /// and no device mask reports 0 in both fields.
    uint32_t uploadedDeviceMask = 0;
    /// Identifies this upload for this handle. It grows with each accepted
    /// upload. It is 0 when status is eFailed.
    uint64_t uploadId = 0;
    /// Why the upload failed, when status is eFailed: a short static text, or
    /// null when the backend gives no reason. It is never freed.
    const char* cause = nullptr;
};

/// Optional second interface of a backend. It reports what each upload really
/// did. It is a separate class, not new virtual functions of IByteImageGpu,
/// so a backend built against an older header keeps the same vtable layout
/// and still loads. A backend that does not implement it is used through
/// IByteImageGpu::updateImage, and then only a missing ImGui reference counts
/// as a failure.
///
/// Register with PlatformRegistry::setByteImageGpuChecked(). Use the same
/// object as the IByteImageGpu that it extends.
class IByteImageGpuChecked
{
public:
    virtual ~IByteImageGpuChecked() = default;

    /// Same arguments as IByteImageGpu::updateImage.
    virtual UploadResult updateImageChecked(IByteImageGpu::Handle h,
                                            const uint8_t* const* mipMapBuffers,
                                            size_t* mipMapStrides,
                                            size_t mipMapCount,
                                            UInt2 size,
                                            PixelFormat format,
                                            bool fromGpu,
                                            uint32_t gpuDeviceMask,
                                            uint32_t textureUsageFlags,
                                            uint32_t resourceUsageFlags) = 0;

    /// The highest upload id of this handle whose copy has finished on every
    /// requested device, or 0 if none. Cheap. It can move the state of
    /// pending copies forward.
    virtual uint64_t getCompletedUploadId(IByteImageGpu::Handle h) = 0;
};

/// For a backend that has one device (device index 0, mask bit 0). A mask of
/// 0 means the default device. Any other bit asks for a device that the
/// backend does not have, and such an upload must fail before it uploads.
inline bool isSingleDeviceMaskSupported(uint32_t requestedMask)
{
    return (requestedMask & ~1u) == 0;
}

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
