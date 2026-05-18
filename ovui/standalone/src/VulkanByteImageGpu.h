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

#include "StandaloneInit.h"

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
    explicit VulkanByteImageGpu(VulkanBackend* backend) : m_backend(backend) {}
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
    void releaseImage(Handle h) override;

    bool supportsFromGpu() const override
    {
#if OMNIUI_HAS_CUDA
        return true;
#else
        return false;
#endif
    }

    /// Test hook: return the VkImage backing the given state handle, or
    /// VK_NULL_HANDLE if the handle is null or the state hasn't been
    /// populated yet. Used by byte_image_gpu_dispatch_test to verify the
    /// fromGpu path end-to-end through ByteImageProvider — production
    /// code should not depend on this.
    VkImage getVkImageForState(Handle h) const;

private:
    VulkanBackend* m_backend = nullptr;
#if OMNIUI_HAS_CUDA
    // External-semaphore pair for CUDA↔Vulkan sync on the fromGpu path.
    // Lazy-initialised on first fromGpu call; owned by this instance and
    // shared across all images updated through it.
    CudaInteropSemaphores m_sync = {};
    bool                  m_syncInitTried = false;
#endif
};

} // namespace standalone
} // namespace ui
} // namespace omni
