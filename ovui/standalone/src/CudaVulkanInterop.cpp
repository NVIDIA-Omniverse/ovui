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

#include "CudaVulkanInterop.h"

#if OMNIUI_HAS_CUDA

#include "VulkanBackend.h"

#include <atomic>
#include <cstdio>
#include <cstring>

#if !defined(_WIN32)
#  include <unistd.h> // close()
#endif

// Timeline-semaphore interop enums were added in CUDA 11.2. On older toolkits
// we fall back to binary semaphores regardless of what Vulkan exposes.
#if !defined(CUDART_VERSION) || (CUDART_VERSION < 11020)
#  define OMNIUI_CUDA_HAS_TIMELINE_SEM 0
#else
#  define OMNIUI_CUDA_HAS_TIMELINE_SEM 1
#endif

namespace
{
// Close the platform external-memory handle (FD on Linux, HANDLE on Windows).
// Used on failure paths where cudaImportExternalMemory did NOT consume the
// handle; on success the handle's fate follows CUDA's documented ownership
// rules and we leave it alone.
#if defined(_WIN32)
inline void closeExtMemHandle(HANDLE h) { if (h) ::CloseHandle(h); }
#else
inline void closeExtMemHandle(int fd) { if (fd >= 0) ::close(fd); }
#endif
} // namespace

namespace omni {
namespace ui {
namespace standalone {

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static bool checkCuda(cudaError_t err, const char* msg)
{
    if (err != cudaSuccess)
    {
        fprintf(stderr, "CudaVulkanInterop: %s — %s\n", msg, cudaGetErrorString(err));
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

CudaVulkanInterop::~CudaVulkanInterop()
{
    shutdown();
}

namespace
{
    // Test-only fault injection (see ``setDrainFailureInjection``).
    // ``std::atomic`` because pybind unit tests may flip the flag
    // from a different thread than the resize path; defaulting to
    // ``false`` so production behavior is unchanged.
    std::atomic<bool> s_drainFailureInjection{false};
}

void CudaVulkanInterop::setDrainFailureInjection(bool fail)
{
    s_drainFailureInjection.store(fail, std::memory_order_relaxed);
}

bool CudaVulkanInterop::drainPendingHandoff()
{
    if (!m_initialized)
    {
        // Nothing in flight — caller can proceed safely. Honour the
        // test seam too so a fault-injection round still asserts the
        // "no teardown on failed drain" branch.
        if (s_drainFailureInjection.exchange(false, std::memory_order_relaxed))
        {
            fprintf(stderr,
                    "CudaVulkanInterop::drainPendingHandoff: "
                    "test fault injection requested failure\n");
            return false;
        }
        return true;
    }
    // Test seam — exchange-and-clear so a single trip is consumed.
    if (s_drainFailureInjection.exchange(false, std::memory_order_relaxed))
    {
        fprintf(stderr,
                "CudaVulkanInterop::drainPendingHandoff: "
                "test fault injection requested failure\n");
        return false;
    }
    // 1. Synchronize CUDA stream 0 — that's the stream
    //    ``syncCudaToVulkan`` posted the C->V signal on
    //    (CudaVulkanInterop.cpp:455). Returning from this call
    //    guarantees the CUDA-side signal has been issued and any
    //    subsequent CUDA work referencing ``m_extSemCuDone`` /
    //    ``m_extSemVkDone`` has retired.
    cudaError_t cudaErr = cudaStreamSynchronize(0);
    if (cudaErr != cudaSuccess)
    {
        fprintf(stderr,
                "CudaVulkanInterop::drainPendingHandoff: "
                "cudaStreamSynchronize failed: %s\n",
                cudaGetErrorString(cudaErr));
        return false;
    }
    // 2. Wait for all in-flight Vulkan work on this device to
    //    complete. ovui's previous tick may have submitted a command
    //    buffer that armed a wait on ``m_vkSemCuDone`` or signaled
    //    ``m_vkSemVkDone``; destroying those semaphores while the
    //    submission is still queued is Vulkan UB.
    if (m_vkDevice != VK_NULL_HANDLE)
    {
        VkResult vkErr = vkDeviceWaitIdle(m_vkDevice);
        if (vkErr != VK_SUCCESS)
        {
            fprintf(stderr,
                    "CudaVulkanInterop::drainPendingHandoff: "
                    "vkDeviceWaitIdle returned VkResult=%d\n",
                    int(vkErr));
            return false;
        }
    }
    return true;
}

void CudaVulkanInterop::shutdown()
{
    if (m_cudaArray)
    {
        cudaFreeMipmappedArray(m_mipmapArray);
        m_mipmapArray = nullptr;
        m_cudaArray = nullptr;
    }
    if (m_extMemory)
    {
        cudaDestroyExternalMemory(m_extMemory);
        m_extMemory = nullptr;
    }
    if (m_extSemVkDone)
    {
        cudaDestroyExternalSemaphore(m_extSemVkDone);
        m_extSemVkDone = nullptr;
    }
    if (m_extSemCuDone)
    {
        cudaDestroyExternalSemaphore(m_extSemCuDone);
        m_extSemCuDone = nullptr;
    }
    // Destroy the Vulkan semaphores we created
    if (m_vkDevice != VK_NULL_HANDLE)
    {
        if (m_vkSemVkDone != VK_NULL_HANDLE)
        {
            vkDestroySemaphore(m_vkDevice, m_vkSemVkDone, nullptr);
            m_vkSemVkDone = VK_NULL_HANDLE;
        }
        if (m_vkSemCuDone != VK_NULL_HANDLE)
        {
            vkDestroySemaphore(m_vkDevice, m_vkSemCuDone, nullptr);
            m_vkSemCuDone = VK_NULL_HANDLE;
        }
    }
    m_initialized = false;
}

bool CudaVulkanInterop::init(VulkanBackend& backend)
{
    if (!backend.isInitialized())
    {
        fprintf(stderr, "CudaVulkanInterop: VulkanBackend not initialized\n");
        return false;
    }

    m_vkDevice = backend.getDevice();
    m_vkQueue = backend.getQueue();
    backend.getFramebufferSize(&m_width, &m_height);

    // Initialize CUDA — pick the GPU that matches the Vulkan device UUID
    int cudaDeviceCount = 0;
    cudaGetDeviceCount(&cudaDeviceCount);
    if (cudaDeviceCount == 0)
    {
        fprintf(stderr, "CudaVulkanInterop: no CUDA devices found\n");
        return false;
    }

    // Get Vulkan device UUID
    VkPhysicalDeviceIDProperties idProps = {};
    idProps.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES;
    VkPhysicalDeviceProperties2 props2 = {};
    props2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
    props2.pNext = &idProps;
    vkGetPhysicalDeviceProperties2(backend.getPhysicalDevice(), &props2);

    // Find matching CUDA device
    int selectedCudaDev = 0;
    for (int i = 0; i < cudaDeviceCount; i++)
    {
        cudaDeviceProp prop;
        cudaGetDeviceProperties(&prop, i);
        if (memcmp(prop.uuid.bytes, idProps.deviceUUID, sizeof(prop.uuid.bytes)) == 0)
        {
            selectedCudaDev = i;
            fprintf(stdout, "CudaVulkanInterop: matched CUDA device %d (%s)\n", i, prop.name);
            break;
        }
    }
    if (!checkCuda(cudaSetDevice(selectedCudaDev), "cudaSetDevice"))
        return false;

    if (!importVulkanMemory(backend))
        return false;
    if (!importVulkanSemaphore(backend))
        return false;

    m_initialized = true;
    fprintf(stdout, "CudaVulkanInterop: initialized (%dx%d), zero-copy path ready\n",
            m_width, m_height);
    return true;
}

// ---------------------------------------------------------------------------
// Import Vulkan image memory into CUDA
// ---------------------------------------------------------------------------

bool CudaVulkanInterop::importVulkanMemory(VulkanBackend& backend)
{
    VkDeviceMemory vkMemory = backend.getColorMemory();
    VkDeviceSize memSize = backend.getColorMemorySize();

    // Get a platform-specific external handle for the Vulkan device memory
    cudaExternalMemoryHandleDesc extMemDesc = {};
    extMemDesc.size = memSize;

#if defined(_WIN32)
    VkMemoryGetWin32HandleInfoKHR getHandleInfo = {};
    getHandleInfo.sType = VK_STRUCTURE_TYPE_MEMORY_GET_WIN32_HANDLE_INFO_KHR;
    getHandleInfo.memory = vkMemory;
    getHandleInfo.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;

    auto vkGetMemoryWin32HandleKHR = (PFN_vkGetMemoryWin32HandleKHR)vkGetDeviceProcAddr(
        m_vkDevice, "vkGetMemoryWin32HandleKHR");
    if (!vkGetMemoryWin32HandleKHR)
    {
        fprintf(stderr, "CudaVulkanInterop: vkGetMemoryWin32HandleKHR not available\n");
        return false;
    }

    HANDLE handle = nullptr;
    VkResult vkErr = vkGetMemoryWin32HandleKHR(m_vkDevice, &getHandleInfo, &handle);
    if (vkErr != VK_SUCCESS || handle == nullptr)
    {
        fprintf(stderr, "CudaVulkanInterop: failed to get memory win32 handle (%d)\n", vkErr);
        return false;
    }

    extMemDesc.type = cudaExternalMemoryHandleTypeOpaqueWin32;
    extMemDesc.handle.win32.handle = handle;
    extMemDesc.handle.win32.name = nullptr;
#else
    VkMemoryGetFdInfoKHR getFdInfo = {};
    getFdInfo.sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR;
    getFdInfo.memory = vkMemory;
    getFdInfo.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;

    auto vkGetMemoryFdKHR = (PFN_vkGetMemoryFdKHR)vkGetDeviceProcAddr(
        m_vkDevice, "vkGetMemoryFdKHR");
    if (!vkGetMemoryFdKHR)
    {
        fprintf(stderr, "CudaVulkanInterop: vkGetMemoryFdKHR not available\n");
        return false;
    }

    int fd = -1;
    VkResult vkErr = vkGetMemoryFdKHR(m_vkDevice, &getFdInfo, &fd);
    if (vkErr != VK_SUCCESS || fd < 0)
    {
        fprintf(stderr, "CudaVulkanInterop: failed to get memory fd (%d)\n", vkErr);
        return false;
    }

    extMemDesc.type = cudaExternalMemoryHandleTypeOpaqueFd;
    extMemDesc.handle.fd = fd;
#endif

    if (!checkCuda(cudaImportExternalMemory(&m_extMemory, &extMemDesc),
                   "cudaImportExternalMemory"))
    {
#if defined(_WIN32)
        closeExtMemHandle(handle);
#else
        closeExtMemHandle(fd);
#endif
        return false;
    }
    // Handle/fd is consumed by cudaImportExternalMemory on success — do not close it

    // Map the external memory as a CUDA mipmapped array
    cudaExternalMemoryMipmappedArrayDesc mipmapDesc = {};
    mipmapDesc.offset = 0;
    mipmapDesc.formatDesc = cudaCreateChannelDesc(8, 8, 8, 8, cudaChannelFormatKindUnsigned);
    mipmapDesc.extent = make_cudaExtent(m_width, m_height, 0);
    mipmapDesc.flags = 0;
    mipmapDesc.numLevels = 1;

    if (!checkCuda(cudaExternalMemoryGetMappedMipmappedArray(&m_mipmapArray, m_extMemory, &mipmapDesc),
                   "cudaExternalMemoryGetMappedMipmappedArray"))
        return false;

    // Get the base level array
    if (!checkCuda(cudaGetMipmappedArrayLevel(&m_cudaArray, m_mipmapArray, 0),
                   "cudaGetMipmappedArrayLevel"))
        return false;

    fprintf(stdout, "CudaVulkanInterop: VkImage memory imported into CUDA (size=%zu)\n",
            (size_t)memSize);
    return true;
}

// ---------------------------------------------------------------------------
// Import Vulkan semaphores into CUDA for sync
// ---------------------------------------------------------------------------

bool CudaVulkanInterop::importVulkanSemaphore(VulkanBackend& backend)
{
    // Check for timeline semaphore support
    VkPhysicalDeviceTimelineSemaphoreFeatures timelineFeatures = {};
    timelineFeatures.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TIMELINE_SEMAPHORE_FEATURES;
    VkPhysicalDeviceFeatures2 features2 = {};
    features2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2;
    features2.pNext = &timelineFeatures;
    vkGetPhysicalDeviceFeatures2(backend.getPhysicalDevice(), &features2);
    m_useTimeline = (timelineFeatures.timelineSemaphore == VK_TRUE);
#if !OMNIUI_CUDA_HAS_TIMELINE_SEM
    // CUDA toolkit too old for timeline-semaphore interop — fall back to binary.
    if (m_useTimeline)
        fprintf(stdout, "CudaVulkanInterop: CUDA < 11.2 — forcing binary semaphores\n");
    m_useTimeline = false;
#endif

    if (m_useTimeline)
        fprintf(stdout, "CudaVulkanInterop: timeline semaphores available\n");
    else
        fprintf(stdout, "CudaVulkanInterop: using binary semaphores\n");

    // Create exportable Vulkan semaphores
    VkExportSemaphoreCreateInfo exportInfo = {};
    exportInfo.sType = VK_STRUCTURE_TYPE_EXPORT_SEMAPHORE_CREATE_INFO;
#if defined(_WIN32)
    exportInfo.handleTypes = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_WIN32_BIT;
#else
    exportInfo.handleTypes = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT;
#endif

    VkSemaphoreTypeCreateInfo timelineInfo = {};
    timelineInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO;
    timelineInfo.semaphoreType = m_useTimeline ? VK_SEMAPHORE_TYPE_TIMELINE : VK_SEMAPHORE_TYPE_BINARY;
    timelineInfo.initialValue = 0;
    exportInfo.pNext = &timelineInfo;

    VkSemaphoreCreateInfo semInfo = {};
    semInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
    semInfo.pNext = &exportInfo;

    VkResult err;
    err = vkCreateSemaphore(m_vkDevice, &semInfo, nullptr, &m_vkSemVkDone);
    if (err != VK_SUCCESS)
    {
        fprintf(stderr, "CudaVulkanInterop: failed to create VkDone semaphore (%d)\n", err);
        return false;
    }
    err = vkCreateSemaphore(m_vkDevice, &semInfo, nullptr, &m_vkSemCuDone);
    if (err != VK_SUCCESS)
    {
        fprintf(stderr, "CudaVulkanInterop: failed to create CuDone semaphore (%d)\n", err);
        return false;
    }

    // Get platform handle for each semaphore and import into CUDA
#if defined(_WIN32)
    auto vkGetSemaphoreWin32HandleKHR = (PFN_vkGetSemaphoreWin32HandleKHR)vkGetDeviceProcAddr(
        m_vkDevice, "vkGetSemaphoreWin32HandleKHR");
    if (!vkGetSemaphoreWin32HandleKHR)
    {
        fprintf(stderr, "CudaVulkanInterop: vkGetSemaphoreWin32HandleKHR not available\n");
        return false;
    }
#else
    auto vkGetSemaphoreFdKHR = (PFN_vkGetSemaphoreFdKHR)vkGetDeviceProcAddr(
        m_vkDevice, "vkGetSemaphoreFdKHR");
    if (!vkGetSemaphoreFdKHR)
    {
        fprintf(stderr, "CudaVulkanInterop: vkGetSemaphoreFdKHR not available\n");
        return false;
    }
#endif

    auto importSemaphore = [&](VkSemaphore vkSem, cudaExternalSemaphore_t* outCudaSem) -> bool
    {
        cudaExternalSemaphoreHandleDesc desc = {};

#if defined(_WIN32)
        VkSemaphoreGetWin32HandleInfoKHR getInfo = {};
        getInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_GET_WIN32_HANDLE_INFO_KHR;
        getInfo.semaphore = vkSem;
        getInfo.handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_WIN32_BIT;

        HANDLE handle = nullptr;
        VkResult vkErr = vkGetSemaphoreWin32HandleKHR(m_vkDevice, &getInfo, &handle);
        if (vkErr != VK_SUCCESS || handle == nullptr)
        {
            fprintf(stderr, "CudaVulkanInterop: failed to get semaphore win32 handle (%d)\n", vkErr);
            return false;
        }

#if OMNIUI_CUDA_HAS_TIMELINE_SEM
        if (m_useTimeline)
            desc.type = cudaExternalSemaphoreHandleTypeTimelineSemaphoreWin32;
        else
#endif
            desc.type = cudaExternalSemaphoreHandleTypeOpaqueWin32;
        desc.handle.win32.handle = handle;
        desc.handle.win32.name = nullptr;
#else
        VkSemaphoreGetFdInfoKHR getFdInfo = {};
        getFdInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR;
        getFdInfo.semaphore = vkSem;
        getFdInfo.handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT;

        int fd = -1;
        VkResult vkErr = vkGetSemaphoreFdKHR(m_vkDevice, &getFdInfo, &fd);
        if (vkErr != VK_SUCCESS || fd < 0)
        {
            fprintf(stderr, "CudaVulkanInterop: failed to get semaphore fd (%d)\n", vkErr);
            return false;
        }

#if OMNIUI_CUDA_HAS_TIMELINE_SEM
        if (m_useTimeline)
            desc.type = cudaExternalSemaphoreHandleTypeTimelineSemaphoreFd;
        else
#endif
            desc.type = cudaExternalSemaphoreHandleTypeOpaqueFd;
        desc.handle.fd = fd;
#endif

        if (!checkCuda(cudaImportExternalSemaphore(outCudaSem, &desc),
                       "cudaImportExternalSemaphore"))
        {
            // CUDA did NOT take ownership of the exported handle on failure —
            // close it ourselves to avoid leaking the kernel object (FD on
            // Linux, HANDLE on Windows). Mirrors the pattern used for memory
            // imports above.
#if defined(_WIN32)
            closeExtMemHandle(handle);
#else
            closeExtMemHandle(fd);
#endif
            return false;
        }
        // handle/fd consumed by CUDA
        return true;
    };

    if (!importSemaphore(m_vkSemVkDone, &m_extSemVkDone))
        return false;
    if (!importSemaphore(m_vkSemCuDone, &m_extSemCuDone))
        return false;

    fprintf(stdout, "CudaVulkanInterop: semaphores imported into CUDA\n");
    return true;
}

// ---------------------------------------------------------------------------
// Synchronization
// ---------------------------------------------------------------------------

bool CudaVulkanInterop::syncVulkanToCuda()
{
    if (m_useTimeline)
        m_timelineValue++;

    // Vulkan signals m_vkSemVkDone
    VkSubmitInfo submitInfo = {};
    submitInfo.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submitInfo.signalSemaphoreCount = 1;
    submitInfo.pSignalSemaphores = &m_vkSemVkDone;

    VkTimelineSemaphoreSubmitInfo timelineSubmit = {};
    uint64_t signalValue = m_timelineValue;
    if (m_useTimeline)
    {
        timelineSubmit.sType = VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO;
        timelineSubmit.signalSemaphoreValueCount = 1;
        timelineSubmit.pSignalSemaphoreValues = &signalValue;
        submitInfo.pNext = &timelineSubmit;
    }

    VkResult err = vkQueueSubmit(m_vkQueue, 1, &submitInfo, VK_NULL_HANDLE);
    if (err != VK_SUCCESS)
    {
        fprintf(stderr, "CudaVulkanInterop: vkQueueSubmit (signal) failed (%d)\n", err);
        return false;
    }

    // CUDA waits on m_extSemVkDone
    cudaExternalSemaphoreWaitParams waitParams = {};
    if (m_useTimeline)
        waitParams.params.fence.value = m_timelineValue;

    if (!checkCuda(cudaWaitExternalSemaphoresAsync(&m_extSemVkDone, &waitParams, 1, nullptr),
                   "cudaWaitExternalSemaphoresAsync"))
        return false;

    return true;
}

bool CudaVulkanInterop::syncCudaToVulkan()
{
    if (m_useTimeline)
        m_timelineValue++;

    // CUDA signals m_extSemCuDone
    cudaExternalSemaphoreSignalParams signalParams = {};
    if (m_useTimeline)
        signalParams.params.fence.value = m_timelineValue;

    if (!checkCuda(cudaSignalExternalSemaphoresAsync(&m_extSemCuDone, &signalParams, 1, nullptr),
                   "cudaSignalExternalSemaphoresAsync"))
        return false;

    // Vulkan waits on m_vkSemCuDone before next submit
    VkPipelineStageFlags waitStage = VK_PIPELINE_STAGE_ALL_COMMANDS_BIT;
    VkSubmitInfo submitInfo = {};
    submitInfo.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submitInfo.waitSemaphoreCount = 1;
    submitInfo.pWaitSemaphores = &m_vkSemCuDone;
    submitInfo.pWaitDstStageMask = &waitStage;

    VkTimelineSemaphoreSubmitInfo timelineSubmit = {};
    uint64_t waitValue = m_timelineValue;
    if (m_useTimeline)
    {
        timelineSubmit.sType = VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO;
        timelineSubmit.waitSemaphoreValueCount = 1;
        timelineSubmit.pWaitSemaphoreValues = &waitValue;
        submitInfo.pNext = &timelineSubmit;
    }

    VkResult err = vkQueueSubmit(m_vkQueue, 1, &submitInfo, VK_NULL_HANDLE);
    if (err != VK_SUCCESS)
    {
        fprintf(stderr, "CudaVulkanInterop: vkQueueSubmit (wait) failed (%d)\n", err);
        return false;
    }

    return true;
}

// ---------------------------------------------------------------------------
// Host readback (for verification only — NOT the zero-copy path)
// ---------------------------------------------------------------------------

bool CudaVulkanInterop::copyToHost(uint8_t* outPixels, int width, int height)
{
    if (!m_cudaArray || !outPixels)
        return false;

    size_t rowBytes = (size_t)width * 4;
    if (!checkCuda(cudaMemcpy2DFromArray(outPixels, rowBytes, m_cudaArray,
                                          0, 0, rowBytes, height,
                                          cudaMemcpyDeviceToHost),
                   "cudaMemcpy2DFromArray"))
        return false;

    return true;
}

// ---------------------------------------------------------------------------
// Per-image CUDA importer (used by VulkanByteImageGpu's fromGpu path)
// ---------------------------------------------------------------------------

bool importVkImageMemoryToCuda(VkDevice device,
                               VkPhysicalDevice physicalDevice,
                               VkDeviceMemory memory,
                               VkDeviceSize memorySize,
                               int width,
                               int height,
                               CudaImageImport* outImport)
{
    // Legacy entry point: RGBA8 channel descriptor (4×8-bit unsigned).
    // New callers should prefer ``importVkImageMemoryToCudaWithFormat``
    // so the cudaArray's channel desc matches the VkFormat — passing the
    // wrong descriptor makes ``cudaExternalMemoryGetMappedMipmappedArray``
    // reject the import.
    return importVkImageMemoryToCudaWithFormat(
        device, physicalDevice, memory, memorySize, width, height,
        cudaCreateChannelDesc(8, 8, 8, 8, cudaChannelFormatKindUnsigned),
        outImport);
}

bool importVkImageMemoryToCudaWithFormat(VkDevice device,
                                         VkPhysicalDevice physicalDevice,
                                         VkDeviceMemory memory,
                                         VkDeviceSize memorySize,
                                         int width,
                                         int height,
                                         cudaChannelFormatDesc channelDesc,
                                         CudaImageImport* outImport)
{
    if (!outImport || device == VK_NULL_HANDLE
        || physicalDevice == VK_NULL_HANDLE || memory == VK_NULL_HANDLE
        || memorySize == 0 || width <= 0 || height <= 0)
        return false;

    *outImport = CudaImageImport{};

    // Match CUDA device to the Vulkan physical device by UUID. Mirrors the
    // setup in CudaVulkanInterop::init (CudaVulkanInterop.cpp:115-146): on
    // multi-GPU hosts CUDA's "device 0" and Vulkan's "physical device 0"
    // need not agree, and importing external memory exported by Vulkan GPU
    // A into CUDA context for GPU B silently fails or corrupts.
    int cudaDeviceCount = 0;
    cudaGetDeviceCount(&cudaDeviceCount);
    if (cudaDeviceCount == 0)
    {
        fprintf(stderr, "importVkImageMemoryToCuda: no CUDA devices found\n");
        return false;
    }

    VkPhysicalDeviceIDProperties idProps = {};
    idProps.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ID_PROPERTIES;
    VkPhysicalDeviceProperties2 props2 = {};
    props2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2;
    props2.pNext = &idProps;
    vkGetPhysicalDeviceProperties2(physicalDevice, &props2);

    int matchedCudaDev = -1;
    for (int i = 0; i < cudaDeviceCount; i++)
    {
        cudaDeviceProp prop;
        if (cudaGetDeviceProperties(&prop, i) != cudaSuccess)
            continue;
        if (memcmp(prop.uuid.bytes, idProps.deviceUUID,
                   sizeof(prop.uuid.bytes)) == 0)
        {
            matchedCudaDev = i;
            break;
        }
    }
    if (matchedCudaDev < 0)
    {
        fprintf(stderr,
                "importVkImageMemoryToCuda: no CUDA device matches Vulkan "
                "physical device UUID — refusing to import memory across "
                "mismatched GPUs\n");
        return false;
    }
    if (!checkCuda(cudaSetDevice(matchedCudaDev),
                   "cudaSetDevice (matched-by-UUID)"))
        return false;

    cudaExternalMemoryHandleDesc extMemDesc = {};
    extMemDesc.size = memorySize;

#if defined(_WIN32)
    VkMemoryGetWin32HandleInfoKHR getHandleInfo = {};
    getHandleInfo.sType = VK_STRUCTURE_TYPE_MEMORY_GET_WIN32_HANDLE_INFO_KHR;
    getHandleInfo.memory = memory;
    getHandleInfo.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;

    auto vkGetMemoryWin32HandleKHR = (PFN_vkGetMemoryWin32HandleKHR)vkGetDeviceProcAddr(
        device, "vkGetMemoryWin32HandleKHR");
    if (!vkGetMemoryWin32HandleKHR)
    {
        fprintf(stderr, "importVkImageMemoryToCuda: vkGetMemoryWin32HandleKHR not available\n");
        return false;
    }

    HANDLE handle = nullptr;
    VkResult vkErr = vkGetMemoryWin32HandleKHR(device, &getHandleInfo, &handle);
    if (vkErr != VK_SUCCESS || handle == nullptr)
    {
        fprintf(stderr, "importVkImageMemoryToCuda: failed to get memory win32 handle (%d)\n", vkErr);
        return false;
    }

    extMemDesc.type = cudaExternalMemoryHandleTypeOpaqueWin32;
    extMemDesc.handle.win32.handle = handle;
    extMemDesc.handle.win32.name = nullptr;
#else
    VkMemoryGetFdInfoKHR getFdInfo = {};
    getFdInfo.sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR;
    getFdInfo.memory = memory;
    getFdInfo.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;

    auto vkGetMemoryFdKHR = (PFN_vkGetMemoryFdKHR)vkGetDeviceProcAddr(
        device, "vkGetMemoryFdKHR");
    if (!vkGetMemoryFdKHR)
    {
        fprintf(stderr, "importVkImageMemoryToCuda: vkGetMemoryFdKHR not available\n");
        return false;
    }

    int fd = -1;
    VkResult vkErr = vkGetMemoryFdKHR(device, &getFdInfo, &fd);
    if (vkErr != VK_SUCCESS || fd < 0)
    {
        fprintf(stderr, "importVkImageMemoryToCuda: failed to get memory fd (%d)\n", vkErr);
        return false;
    }

    extMemDesc.type = cudaExternalMemoryHandleTypeOpaqueFd;
    extMemDesc.handle.fd = fd;
#endif

    if (!checkCuda(cudaImportExternalMemory(&outImport->extMemory, &extMemDesc),
                   "cudaImportExternalMemory"))
    {
#if defined(_WIN32)
        closeExtMemHandle(handle);
#else
        closeExtMemHandle(fd);
#endif
        *outImport = CudaImageImport{};
        return false;
    }
    // handle/fd is consumed by cudaImportExternalMemory on success — do not close it.

    cudaExternalMemoryMipmappedArrayDesc mipmapDesc = {};
    mipmapDesc.offset = 0;
    mipmapDesc.formatDesc = channelDesc;
    mipmapDesc.extent = make_cudaExtent(width, height, 0);
    mipmapDesc.flags = 0;
    mipmapDesc.numLevels = 1;

    if (!checkCuda(cudaExternalMemoryGetMappedMipmappedArray(
            &outImport->mipmapArray, outImport->extMemory, &mipmapDesc),
                   "cudaExternalMemoryGetMappedMipmappedArray"))
    {
        destroyCudaImageImport(outImport);
        return false;
    }

    if (!checkCuda(cudaGetMipmappedArrayLevel(&outImport->array, outImport->mipmapArray, 0),
                   "cudaGetMipmappedArrayLevel"))
    {
        destroyCudaImageImport(outImport);
        return false;
    }

    return true;
}

void destroyCudaImageImport(CudaImageImport* imp)
{
    if (!imp)
        return;
    // The level-0 array is a non-owning view into the mipmapped array; we
    // free the mipmapped array (which invalidates `array`) and the external
    // memory.
    if (imp->mipmapArray)
    {
        cudaFreeMipmappedArray(imp->mipmapArray);
        imp->mipmapArray = nullptr;
    }
    imp->array = nullptr;
    if (imp->extMemory)
    {
        cudaDestroyExternalMemory(imp->extMemory);
        imp->extMemory = nullptr;
    }
}

// ---------------------------------------------------------------------------
// External-semaphore pair (free-helper variant of importVulkanSemaphore)
// ---------------------------------------------------------------------------

namespace
{

bool importVkSemaphoreToCuda(VkDevice device,
                             VkSemaphore vkSem,
                             bool useTimeline,
                             cudaExternalSemaphore_t* outCudaSem)
{
    cudaExternalSemaphoreHandleDesc desc = {};

#if defined(_WIN32)
    auto vkGetSemaphoreWin32HandleKHR = (PFN_vkGetSemaphoreWin32HandleKHR)vkGetDeviceProcAddr(
        device, "vkGetSemaphoreWin32HandleKHR");
    if (!vkGetSemaphoreWin32HandleKHR)
    {
        fprintf(stderr, "createCudaInteropSemaphores: vkGetSemaphoreWin32HandleKHR not available\n");
        return false;
    }

    VkSemaphoreGetWin32HandleInfoKHR getInfo = {};
    getInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_GET_WIN32_HANDLE_INFO_KHR;
    getInfo.semaphore = vkSem;
    getInfo.handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_WIN32_BIT;

    HANDLE handle = nullptr;
    VkResult vkErr = vkGetSemaphoreWin32HandleKHR(device, &getInfo, &handle);
    if (vkErr != VK_SUCCESS || handle == nullptr)
    {
        fprintf(stderr, "createCudaInteropSemaphores: failed to get semaphore win32 handle (%d)\n", vkErr);
        return false;
    }

#if OMNIUI_CUDA_HAS_TIMELINE_SEM
    desc.type = useTimeline
        ? cudaExternalSemaphoreHandleTypeTimelineSemaphoreWin32
        : cudaExternalSemaphoreHandleTypeOpaqueWin32;
#else
    (void)useTimeline;
    desc.type = cudaExternalSemaphoreHandleTypeOpaqueWin32;
#endif
    desc.handle.win32.handle = handle;
    desc.handle.win32.name = nullptr;
#else
    auto vkGetSemaphoreFdKHR = (PFN_vkGetSemaphoreFdKHR)vkGetDeviceProcAddr(
        device, "vkGetSemaphoreFdKHR");
    if (!vkGetSemaphoreFdKHR)
    {
        fprintf(stderr, "createCudaInteropSemaphores: vkGetSemaphoreFdKHR not available\n");
        return false;
    }

    VkSemaphoreGetFdInfoKHR getFdInfo = {};
    getFdInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_GET_FD_INFO_KHR;
    getFdInfo.semaphore = vkSem;
    getFdInfo.handleType = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT;

    int fd = -1;
    VkResult vkErr = vkGetSemaphoreFdKHR(device, &getFdInfo, &fd);
    if (vkErr != VK_SUCCESS || fd < 0)
    {
        fprintf(stderr, "createCudaInteropSemaphores: failed to get semaphore fd (%d)\n", vkErr);
        return false;
    }

#if OMNIUI_CUDA_HAS_TIMELINE_SEM
    desc.type = useTimeline
        ? cudaExternalSemaphoreHandleTypeTimelineSemaphoreFd
        : cudaExternalSemaphoreHandleTypeOpaqueFd;
#else
    (void)useTimeline;
    desc.type = cudaExternalSemaphoreHandleTypeOpaqueFd;
#endif
    desc.handle.fd = fd;
#endif

    if (!checkCuda(cudaImportExternalSemaphore(outCudaSem, &desc),
                   "cudaImportExternalSemaphore"))
    {
#if defined(_WIN32)
        if (handle) ::CloseHandle(handle);
#else
        if (fd >= 0) ::close(fd);
#endif
        return false;
    }
    // Handle/fd consumed by CUDA on success.
    return true;
}

} // anonymous namespace

bool createCudaInteropSemaphores(VkDevice device,
                                 VkPhysicalDevice physicalDevice,
                                 CudaInteropSemaphores* outSync)
{
    if (!outSync || device == VK_NULL_HANDLE || physicalDevice == VK_NULL_HANDLE)
        return false;

    *outSync = CudaInteropSemaphores{};

    // Decide timeline vs binary the same way CudaVulkanInterop::importVulkanSemaphore does.
    VkPhysicalDeviceTimelineSemaphoreFeatures timelineFeatures = {};
    timelineFeatures.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TIMELINE_SEMAPHORE_FEATURES;
    VkPhysicalDeviceFeatures2 features2 = {};
    features2.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2;
    features2.pNext = &timelineFeatures;
    vkGetPhysicalDeviceFeatures2(physicalDevice, &features2);
    bool useTimeline = (timelineFeatures.timelineSemaphore == VK_TRUE);
#if !OMNIUI_CUDA_HAS_TIMELINE_SEM
    useTimeline = false;
#endif
    outSync->useTimeline = useTimeline;

    VkExportSemaphoreCreateInfo exportInfo = {};
    exportInfo.sType = VK_STRUCTURE_TYPE_EXPORT_SEMAPHORE_CREATE_INFO;
#if defined(_WIN32)
    exportInfo.handleTypes = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_WIN32_BIT;
#else
    exportInfo.handleTypes = VK_EXTERNAL_SEMAPHORE_HANDLE_TYPE_OPAQUE_FD_BIT;
#endif

    VkSemaphoreTypeCreateInfo typeInfo = {};
    typeInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_TYPE_CREATE_INFO;
    typeInfo.semaphoreType = useTimeline
        ? VK_SEMAPHORE_TYPE_TIMELINE
        : VK_SEMAPHORE_TYPE_BINARY;
    typeInfo.initialValue = 0;
    exportInfo.pNext = &typeInfo;

    VkSemaphoreCreateInfo semInfo = {};
    semInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
    semInfo.pNext = &exportInfo;

    if (vkCreateSemaphore(device, &semInfo, nullptr, &outSync->vkSemVkDone) != VK_SUCCESS
        || vkCreateSemaphore(device, &semInfo, nullptr, &outSync->vkSemCuDone) != VK_SUCCESS)
    {
        // Belt + braces: if the timeline-feature wasn't actually enabled at
        // device-creation time (older path or driver edge case), fall back to
        // binary semaphores rather than failing the whole interop chain.
        if (useTimeline)
        {
            fprintf(stderr,
                    "createCudaInteropSemaphores: timeline vkCreateSemaphore failed; "
                    "falling back to binary\n");
            destroyCudaInteropSemaphores(device, outSync);
            *outSync = CudaInteropSemaphores{};
            useTimeline = false;
            outSync->useTimeline = false;
            typeInfo.semaphoreType = VK_SEMAPHORE_TYPE_BINARY;
            if (vkCreateSemaphore(device, &semInfo, nullptr, &outSync->vkSemVkDone) != VK_SUCCESS
                || vkCreateSemaphore(device, &semInfo, nullptr, &outSync->vkSemCuDone) != VK_SUCCESS)
            {
                fprintf(stderr, "createCudaInteropSemaphores: binary vkCreateSemaphore failed\n");
                destroyCudaInteropSemaphores(device, outSync);
                return false;
            }
        }
        else
        {
            fprintf(stderr, "createCudaInteropSemaphores: vkCreateSemaphore failed\n");
            destroyCudaInteropSemaphores(device, outSync);
            return false;
        }
    }

    if (!importVkSemaphoreToCuda(device, outSync->vkSemVkDone, useTimeline, &outSync->extSemVkDone)
        || !importVkSemaphoreToCuda(device, outSync->vkSemCuDone, useTimeline, &outSync->extSemCuDone))
    {
        destroyCudaInteropSemaphores(device, outSync);
        return false;
    }

    outSync->initialized = true;
    fprintf(stdout, "createCudaInteropSemaphores: %s semaphore pair ready\n",
            useTimeline ? "timeline" : "binary");
    return true;
}

void destroyCudaInteropSemaphores(VkDevice device, CudaInteropSemaphores* sync)
{
    if (!sync)
        return;
    if (sync->extSemVkDone)
    {
        cudaDestroyExternalSemaphore(sync->extSemVkDone);
        sync->extSemVkDone = nullptr;
    }
    if (sync->extSemCuDone)
    {
        cudaDestroyExternalSemaphore(sync->extSemCuDone);
        sync->extSemCuDone = nullptr;
    }
    if (device != VK_NULL_HANDLE)
    {
        if (sync->vkSemVkDone)
        {
            vkDestroySemaphore(device, sync->vkSemVkDone, nullptr);
            sync->vkSemVkDone = VK_NULL_HANDLE;
        }
        if (sync->vkSemCuDone)
        {
            vkDestroySemaphore(device, sync->vkSemCuDone, nullptr);
            sync->vkSemCuDone = VK_NULL_HANDLE;
        }
    }
    sync->useTimeline = false;
    sync->timelineValue = 0;
    sync->initialized = false;
}

} // namespace standalone
} // namespace ui
} // namespace omni

#endif // OMNIUI_HAS_CUDA
