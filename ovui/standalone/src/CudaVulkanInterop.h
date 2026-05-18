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

#if OMNIUI_HAS_CUDA

#if defined(_WIN32) && !defined(VK_USE_PLATFORM_WIN32_KHR)
#  define VK_USE_PLATFORM_WIN32_KHR
#endif
#include "StandaloneInit.h"

#include <vulkan/vulkan.h>
#include <cuda.h>
#include <cuda_runtime.h>

#include <cstdint>

namespace omni {
namespace ui {
namespace standalone {

class VulkanBackend;

/// Zero-copy CUDA-Vulkan interop via VK_EXT_external_memory.
/// Exports the VulkanBackend's offscreen VkImage as a CUDA external memory
/// object, providing a direct GPU→GPU pathway without CPU readback.
class OMNIUI_STANDALONE_API CudaVulkanInterop
{
public:
    CudaVulkanInterop() = default;
    ~CudaVulkanInterop();

    /// Initialize interop: import VkImage memory into CUDA, set up sync.
    /// The VulkanBackend must already be initialized with external memory enabled.
    bool init(VulkanBackend& backend);

    /// Release all CUDA and Vulkan interop resources.
    void shutdown();

    /// Drain any outstanding CUDA/Vulkan work that referenced the
    /// imported semaphores or memory before they get destroyed.
    ///
    /// ``syncCudaToVulkan`` (called from
    /// ``standalone::signalHeadlessFrameConsumed``) queues an async
    /// CUDA signal on stream 0 against ``m_extSemCuDone`` and arms
    /// the matching Vulkan wait on the next render's submit. Calling
    /// :func:`shutdown` (which destroys the external semaphores and
    /// the imported VkImage) before that signal/wait pair has fully
    /// completed is undefined behaviour.
    ///
    /// Returns ``true`` once both ``cudaStreamSynchronize(0)`` and
    /// ``vkDeviceWaitIdle`` have completed successfully — at that
    /// point it is safe to destroy the underlying handles. Returns
    /// ``false`` if either synchronization call reported an error;
    /// the caller MUST treat the imports as still in-flight and
    /// abort any teardown / framebuffer-recreate that would invalidate
    /// them. Returns ``true`` immediately when the interop is
    /// uninitialised (nothing to drain).
    bool drainPendingHandoff();

    /// Test-only fault injection. When set to ``true``, the next
    /// ``drainPendingHandoff`` call returns ``false`` without
    /// touching CUDA or Vulkan, simulating a synchronization
    /// failure. Cleared automatically after one trip; the test
    /// toggles the flag, exercises the resize path, then asserts
    /// resources were preserved. Defaults to ``false``.
    ///
    /// Implemented as a process-wide flag rather than a per-instance
    /// hook because the production teardown path holds the only
    /// reference to the active ``CudaVulkanInterop`` and the test is
    /// asserting on observable side-effects (interop pointer, extent)
    /// after the failed drain returns control. No threading concerns
    /// because the resize path is main-loop-only.
    static void setDrainFailureInjection(bool fail);

    /// Signal the Vulkan semaphore (call after Vulkan rendering is done)
    /// and wait on the CUDA side before accessing the mapped array.
    bool syncVulkanToCuda();

    /// Signal from CUDA side and wait on Vulkan side (call before next Vulkan frame).
    bool syncCudaToVulkan();

    /// Get the CUDA mipmapped array mapped from the Vulkan image.
    cudaMipmappedArray_t getMipmappedArray() const { return m_mipmapArray; }

    /// Get the base-level CUDA array (convenience for single-mip images).
    cudaArray_t getArray() const { return m_cudaArray; }

    /// Copy the CUDA array contents to a host buffer (for verification only).
    /// This does touch the CPU but proves the zero-copy path works.
    bool copyToHost(uint8_t* outPixels, int width, int height);

    bool isInitialized() const { return m_initialized; }

private:
    bool importVulkanMemory(VulkanBackend& backend);
    bool importVulkanSemaphore(VulkanBackend& backend);

    // CUDA external memory
    cudaExternalMemory_t     m_extMemory     = nullptr;
    cudaMipmappedArray_t     m_mipmapArray   = nullptr;
    cudaArray_t              m_cudaArray     = nullptr;

    // CUDA external semaphores for Vulkan↔CUDA sync
    cudaExternalSemaphore_t  m_extSemVkDone  = nullptr;  // Vulkan signals, CUDA waits
    cudaExternalSemaphore_t  m_extSemCuDone  = nullptr;  // CUDA signals, Vulkan waits

    // Timeline semaphore support
    bool                     m_useTimeline   = false;
    uint64_t                 m_timelineValue = 0;

    // Vulkan handles (not owned — belong to VulkanBackend)
    VkDevice                 m_vkDevice      = VK_NULL_HANDLE;
    VkSemaphore              m_vkSemVkDone   = VK_NULL_HANDLE;
    VkSemaphore              m_vkSemCuDone   = VK_NULL_HANDLE;
    VkQueue                  m_vkQueue       = VK_NULL_HANDLE;

    int                      m_width         = 0;
    int                      m_height        = 0;
    bool                     m_initialized   = false;
};

// ---------------------------------------------------------------------------
// Per-image CUDA import helper (used by VulkanByteImageGpu's fromGpu path).
//
// Imports a single VkDeviceMemory backing an RGBA8 VkImage into CUDA as a
// cudaMipmappedArray (level 0 extracted). The Vulkan side must allocate the
// memory with VkExportMemoryAllocateInfo (OPAQUE_FD on Linux,
// OPAQUE_WIN32 on Windows) so the platform handle can be exported.
// ---------------------------------------------------------------------------

struct CudaImageImport
{
    cudaExternalMemory_t extMemory   = nullptr;
    cudaMipmappedArray_t mipmapArray = nullptr;
    cudaArray_t          array       = nullptr; // level 0
};

/// Import the given VkDeviceMemory into CUDA and map it as an RGBA8
/// cudaMipmappedArray. Returns true on success; outImport's fields are
/// populated. On failure, outImport is left zeroed.
///
/// `physicalDevice` is required so the helper can match the Vulkan
/// device's UUID (VkPhysicalDeviceIDProperties::deviceUUID) against
/// CUDA's enumerated devices and cudaSetDevice on the matching one
/// before importing memory. Without this the import targets whatever
/// CUDA device happens to be current — which is wrong on multi-GPU
/// hosts where Vulkan and CUDA may not agree on "device 0".
OMNIUI_STANDALONE_API bool importVkImageMemoryToCuda(VkDevice device,
                                                     VkPhysicalDevice physicalDevice,
                                                     VkDeviceMemory memory,
                                                     VkDeviceSize memorySize,
                                                     int width,
                                                     int height,
                                                     CudaImageImport* outImport);

/// Same as ``importVkImageMemoryToCuda`` but lets the caller supply an
/// explicit ``cudaChannelFormatDesc`` so the imported cudaArray matches
/// the underlying ``VkFormat`` (RGBA16/32 float, R32_FLOAT, …). Required
/// when the Vulkan image is anything other than the default RGBA8.
OMNIUI_STANDALONE_API bool importVkImageMemoryToCudaWithFormat(VkDevice device,
                                                               VkPhysicalDevice physicalDevice,
                                                               VkDeviceMemory memory,
                                                               VkDeviceSize memorySize,
                                                               int width,
                                                               int height,
                                                               cudaChannelFormatDesc channelDesc,
                                                               CudaImageImport* outImport);

/// Release the CUDA resources held by a CudaImageImport. Safe to call on
/// a default-constructed (zeroed) struct.
OMNIUI_STANDALONE_API void destroyCudaImageImport(CudaImageImport* imp);

// ---------------------------------------------------------------------------
// External-semaphore pair for cross-API sync between Vulkan and CUDA.
//
// Mirrors the offscreen-render pair created by
// CudaVulkanInterop::importVulkanSemaphore, but is reusable across multiple
// images: vkSemVkDone is signalled by Vulkan and waited by CUDA (V→C);
// vkSemCuDone is signalled by CUDA and waited by Vulkan (C→V). Timeline
// semaphores are used when both the Vulkan device and the CUDA toolkit
// support them; otherwise the helpers fall back to binary semaphores.
// ---------------------------------------------------------------------------

struct CudaInteropSemaphores
{
    VkSemaphore             vkSemVkDone   = VK_NULL_HANDLE;
    VkSemaphore             vkSemCuDone   = VK_NULL_HANDLE;
    cudaExternalSemaphore_t extSemVkDone  = nullptr;
    cudaExternalSemaphore_t extSemCuDone  = nullptr;
    bool                    useTimeline   = false;
    uint64_t                timelineValue = 0;
    bool                    initialized   = false;
};

/// Create the V→C / C→V semaphore pair and import both sides into CUDA.
/// On success the struct is fully populated and `initialized` is set to true.
/// On failure any already-created Vulkan/CUDA handles inside the struct are
/// released and the struct is reset.
OMNIUI_STANDALONE_API bool createCudaInteropSemaphores(VkDevice device,
                                                       VkPhysicalDevice physicalDevice,
                                                       CudaInteropSemaphores* outSync);

/// Release all CUDA and Vulkan handles owned by `sync`. Safe to call on a
/// default-constructed (zeroed) struct.
OMNIUI_STANDALONE_API void destroyCudaInteropSemaphores(VkDevice device,
                                                        CudaInteropSemaphores* sync);

} // namespace standalone
} // namespace ui
} // namespace omni

#endif // OMNIUI_HAS_CUDA
