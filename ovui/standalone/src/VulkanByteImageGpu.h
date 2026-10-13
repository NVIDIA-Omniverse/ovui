/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <memory>
#include <mutex>
#include <omni/ui/ImageProvider/IByteImageGpu.h>

#include "StandaloneInit.h"

#if defined(_WIN32) && !defined(VK_USE_PLATFORM_WIN32_KHR)
#  define VK_USE_PLATFORM_WIN32_KHR
#endif
#include <vulkan/vulkan.h>

#if OMNIUI_HAS_CUDA
#  include "CudaVulkanInterop.h"
#endif

namespace omni {
namespace ui {
namespace standalone {

class VulkanBackend;

/// Standalone IByteImageGpu implementation using Vulkan.
///
/// Allocates a VkImage / VkImageView / VkSampler per provider, uploads
/// pixel data via a staging buffer on a one-shot command buffer, and
/// exposes a VkDescriptorSet (via ImGui_ImplVulkan_AddTexture) as the
/// ImGui texture reference.
class OMNIUI_STANDALONE_API VulkanByteImageGpu : public IByteImageGpu
{
public:
    explicit VulkanByteImageGpu(VulkanBackend* backend);
    ~VulkanByteImageGpu() override;

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

    /// Native-pacing-only GPU upload.  The caller must keep the CUDA source
    /// mapping alive on the default stream after this method returns.  The
    /// public IByteImageGpu method remains synchronous because its existing
    /// callers release their source mapping immediately.
    UpdateResult updateImageFromGpuAsync(Handle h,
                                         const uint8_t* devicePixels,
                                         size_t rowStride,
                                         UInt2 size,
                                         PixelFormat format);
    void releaseImage(Handle h) override;

    /// Whether a GPU-resident upload can actually be performed here.
    ///
    /// Compiling CUDA in proves nothing at runtime: a host can have zero
    /// visible CUDA devices, or a CUDA device that is a different physical
    /// adapter from the one Vulkan selected, in which case importing the
    /// exported memory fails ("operation not supported") and any device
    /// pointer we consumed would belong to the wrong device. Answer from the
    /// real adapter pair instead, and cache it — the pair cannot change while
    /// this backend lives. Answered by performing the real export/import once,
    /// because neither compile-time CUDA nor device identity predicts it.
    bool supportsFromGpu() const override;

    /// Test hook: return the VkImage backing the given state handle, or
    /// VK_NULL_HANDLE if the handle is null or the state hasn't been
    /// populated yet. Used by byte_image_gpu_dispatch_test to verify the
    /// fromGpu path end-to-end through ByteImageProvider — production
    /// code should not depend on this.
    VkImage getVkImageForState(Handle h) const;

    /// Destroy states retired during UI construction after the completed frame
    /// can no longer reference their Vulkan descriptors.
    void drainDeferredDestructions();

private:
    struct DeferredDestruction;

    UpdateResult updateImageImpl(Handle h,
                                 const uint8_t* const* mipMapBuffers,
                                 size_t* mipMapStrides,
                                 size_t mipMapCount,
                                 UInt2 size,
                                 PixelFormat format,
                                 bool fromGpu,
                                 uint32_t gpuDeviceMask,
                                 uint32_t textureUsageFlags,
                                 uint32_t resourceUsageFlags,
                                 bool asynchronousGpuSource);
    // The probe runs exactly once per backend and every caller — native render
    // thread, UI thread, legacy bridge — waits for that one completed result.
    // Publishing a "probed" flag before the answer let a concurrent caller read
    // the provisional false and take CPU readback on a capable host, and the
    // unsynchronised accesses were a data race besides.
    mutable std::once_flag m_fromGpuOnce;
    mutable bool m_fromGpuUsable = false;  // written once, inside call_once
    mutable int m_fromGpuCudaDevice = -1;  // CUDA device matching the Vulkan adapter
    VulkanBackend* m_backend = nullptr;
    std::unique_ptr<DeferredDestruction> m_deferredDestruction;
};

} // namespace standalone
} // namespace ui
} // namespace omni
