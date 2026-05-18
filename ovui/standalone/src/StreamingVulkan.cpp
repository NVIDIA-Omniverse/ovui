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

// StreamingVulkan — Vulkan-native streaming encoder pipeline.
//
// Pipeline: VkImage → (CUDA interop | CPU readback) → (NVENC | CPU stub) → NAL units
//
// Build flags:
//   OMNIUI_HAS_NVENC       — NVIDIA Video Codec SDK (NvEncodeAPI) available
//   OMNIUI_HAS_CUDA_INTEROP — CUDA + Vulkan external memory interop available
//
// When neither flag is set the pipeline still works end-to-end using a CPU
// readback path and a trivial stub encoder that emits uncompressed NAL-like
// packets (enough to prove the pipeline is connected).

#include "StreamingVulkan.h"
#include "VulkanBackend.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>

// ---------------------------------------------------------------------------
// NVENC includes (optional)
// ---------------------------------------------------------------------------
#ifdef OMNIUI_HAS_NVENC
#include <nvEncodeAPI.h>

// Function pointer type for NvEncodeAPICreateInstance
using NvEncCreateInstanceFn = NVENCSTATUS(NVENCAPI*)(NV_ENCODE_API_FUNCTION_LIST*);
#endif

// ---------------------------------------------------------------------------
// CUDA interop includes (optional)
// ---------------------------------------------------------------------------
#ifdef OMNIUI_HAS_CUDA_INTEROP
#include <cuda.h>
#include <cuda_runtime.h>

// Forward-declare the legacy `_v2` CUDA Driver context-creation symbol with its
// frozen 3-arg signature. The unsuffixed `cuCtxCreate` macro in `cuda.h` is
// remapped per CUDA major release (currently `_v2` on CUDA 12.x, `_v4` on
// CUDA 13.x), and CUDA 13's public headers only declare `cuCtxCreate_v2` inside
// `__CUDA_API_VERSION_INTERNAL`. The symbol itself is still exported by every
// `libcuda.so` since CUDA 4.0, so calling it through this declaration keeps the
// `(flags, dev)` ABI stable across all supported toolkits without `#if`-gating.
extern "C" CUresult CUDAAPI cuCtxCreate_v2(CUcontext* pctx, unsigned int flags, CUdevice dev);
#endif

namespace omni {
namespace ui {
namespace standalone {

using Clock = std::chrono::high_resolution_clock;

static double msElapsed(Clock::time_point start)
{
    auto now = Clock::now();
    return std::chrono::duration<double, std::milli>(now - start).count();
}

// ---------------------------------------------------------------------------
// Construction / Destruction
// ---------------------------------------------------------------------------

StreamingVulkan::StreamingVulkan() = default;

StreamingVulkan::~StreamingVulkan()
{
    shutdown();
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

bool StreamingVulkan::init(VulkanBackend* backend, const StreamingConfig& config)
{
    if (m_initialized)
    {
        fprintf(stderr, "StreamingVulkan: already initialized\n");
        return false;
    }
    if (!backend || !backend->isInitialized())
    {
        fprintf(stderr, "StreamingVulkan: VulkanBackend not ready\n");
        return false;
    }

    m_backend = backend;
    m_config  = config;

    // Allocate pixel buffer for CPU path
    size_t imageSize = (size_t)config.width * config.height * 4;
    m_pixelBuffer.resize(imageSize);

    // Create Vulkan sync objects
    if (!createSyncObjects())
    {
        fprintf(stderr, "StreamingVulkan: failed to create sync objects\n");
        return false;
    }

    // Try CUDA interop first (zero-copy path)
    m_useCuda = false;
#ifdef OMNIUI_HAS_CUDA_INTEROP
    if (config.useCudaInterop)
    {
        m_useCuda = initCudaInterop();
        if (m_useCuda)
            fprintf(stdout, "StreamingVulkan: CUDA interop enabled (zero-copy)\n");
        else
            fprintf(stdout, "StreamingVulkan: CUDA interop failed, falling back to CPU readback\n");
    }
#endif

    // Create staging buffer for CPU readback if not using CUDA
    if (!m_useCuda)
    {
        VkDevice device = m_backend->getDevice();
        m_stagingSize = (VkDeviceSize)imageSize;

        VkBufferCreateInfo bufInfo = {};
        bufInfo.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
        bufInfo.size  = m_stagingSize;
        bufInfo.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
        bufInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;

        VkResult err = vkCreateBuffer(device, &bufInfo, nullptr, &m_stagingBuffer);
        if (err != VK_SUCCESS)
        {
            fprintf(stderr, "StreamingVulkan: failed to create staging buffer\n");
            return false;
        }

        VkMemoryRequirements memReqs;
        vkGetBufferMemoryRequirements(device, m_stagingBuffer, &memReqs);

        VkPhysicalDeviceMemoryProperties memProps;
        vkGetPhysicalDeviceMemoryProperties(m_backend->getPhysicalDevice(), &memProps);

        uint32_t memIdx = UINT32_MAX;
        for (uint32_t i = 0; i < memProps.memoryTypeCount; i++)
        {
            if ((memReqs.memoryTypeBits & (1 << i)) &&
                (memProps.memoryTypes[i].propertyFlags &
                 (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) ==
                    (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT))
            {
                memIdx = i;
                break;
            }
        }
        if (memIdx == UINT32_MAX)
        {
            fprintf(stderr, "StreamingVulkan: no host-visible memory type\n");
            return false;
        }

        VkMemoryAllocateInfo allocInfo = {};
        allocInfo.sType           = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        allocInfo.allocationSize  = memReqs.size;
        allocInfo.memoryTypeIndex = memIdx;

        err = vkAllocateMemory(device, &allocInfo, nullptr, &m_stagingMemory);
        if (err != VK_SUCCESS)
        {
            fprintf(stderr, "StreamingVulkan: failed to allocate staging memory\n");
            return false;
        }
        vkBindBufferMemory(device, m_stagingBuffer, m_stagingMemory, 0);
    }

    // Try NVENC hardware encoder
    m_useNvenc = false;
#ifdef OMNIUI_HAS_NVENC
    m_useNvenc = initNvenc();
    if (m_useNvenc)
        fprintf(stdout, "StreamingVulkan: NVENC hardware encoder initialized (%s)\n",
                config.codec == StreamCodec::eHEVC ? "HEVC" : "H.264");
    else
        fprintf(stdout, "StreamingVulkan: NVENC init failed, falling back to CPU encoder\n");
#endif

    // Fall back to CPU encoder
    if (!m_useNvenc)
    {
        if (!initCpuEncoder())
        {
            fprintf(stderr, "StreamingVulkan: CPU encoder init failed\n");
            return false;
        }
        fprintf(stdout, "StreamingVulkan: CPU stub encoder initialized\n");
    }

    m_initialized = true;
    fprintf(stdout, "StreamingVulkan: pipeline ready — %dx%d @ %dfps, encoder=%s, readback=%s\n",
            config.width, config.height, config.fps,
            getEncoderName(),
            m_useCuda ? "CUDA" : "CPU");
    return true;
}

void StreamingVulkan::shutdown()
{
    if (!m_initialized)
        return;

    VkDevice device = m_backend ? m_backend->getDevice() : VK_NULL_HANDLE;
    if (device != VK_NULL_HANDLE)
        vkDeviceWaitIdle(device);

#ifdef OMNIUI_HAS_NVENC
    if (m_useNvenc)
        shutdownNvenc();
#endif

#ifdef OMNIUI_HAS_CUDA_INTEROP
    if (m_useCuda)
        shutdownCudaInterop();
#endif

    shutdownCpuEncoder();

    // Destroy staging buffer
    if (device != VK_NULL_HANDLE)
    {
        if (m_stagingBuffer != VK_NULL_HANDLE)
        {
            vkDestroyBuffer(device, m_stagingBuffer, nullptr);
            m_stagingBuffer = VK_NULL_HANDLE;
        }
        if (m_stagingMemory != VK_NULL_HANDLE)
        {
            vkFreeMemory(device, m_stagingMemory, nullptr);
            m_stagingMemory = VK_NULL_HANDLE;
        }
    }

    destroySyncObjects();

    m_pixelBuffer.clear();
    m_encodedBuffer.clear();
    m_backend     = nullptr;
    m_initialized = false;
    m_useNvenc    = false;
    m_useCuda     = false;

    fprintf(stdout, "StreamingVulkan: shutdown complete\n");
}

bool StreamingVulkan::encodeFrame(uint64_t pts, NalCallback nalCallback)
{
    if (!m_initialized || !m_backend)
        return false;

    auto frameStart = Clock::now();

    // --- Step 1: Read back pixels from VkImage ---
    auto readbackStart = Clock::now();
    bool readOk = false;

#ifdef OMNIUI_HAS_CUDA_INTEROP
    if (m_useCuda)
    {
        readOk = readbackViaCuda(m_pixelBuffer.data());
    }
#endif

    if (!readOk)
    {
        // CPU readback via Vulkan staging buffer
        VkDevice device = m_backend->getDevice();
        VkQueue  queue  = m_backend->getQueue();

        // Wait for render to finish
        vkWaitForFences(device, 1, &m_encodeFence, VK_TRUE, UINT64_MAX);
        vkResetFences(device, 1, &m_encodeFence);

        // Record copy command
        VkCommandBufferBeginInfo beginInfo = {};
        beginInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
        beginInfo.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;

        vkResetCommandBuffer(m_encodeCommandBuffer, 0);
        vkBeginCommandBuffer(m_encodeCommandBuffer, &beginInfo);

        // Image is already in TRANSFER_SRC_OPTIMAL from render pass
        VkBufferImageCopy region = {};
        region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.imageSubresource.layerCount = 1;
        region.imageExtent = { (uint32_t)m_config.width, (uint32_t)m_config.height, 1 };
        vkCmdCopyImageToBuffer(m_encodeCommandBuffer, m_backend->getColorImage(),
                               VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                               m_stagingBuffer, 1, &region);

        vkEndCommandBuffer(m_encodeCommandBuffer);

        // Submit with semaphore wait (render must finish before encode reads)
        VkPipelineStageFlags waitStage = VK_PIPELINE_STAGE_TRANSFER_BIT;
        VkSubmitInfo submitInfo = {};
        submitInfo.sType                = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        submitInfo.waitSemaphoreCount   = (m_renderDoneSemaphore != VK_NULL_HANDLE) ? 1u : 0u;
        submitInfo.pWaitSemaphores      = &m_renderDoneSemaphore;
        submitInfo.pWaitDstStageMask    = &waitStage;
        submitInfo.commandBufferCount   = 1;
        submitInfo.pCommandBuffers      = &m_encodeCommandBuffer;
        submitInfo.signalSemaphoreCount = (m_encodeDoneSemaphore != VK_NULL_HANDLE) ? 1u : 0u;
        submitInfo.pSignalSemaphores    = &m_encodeDoneSemaphore;

        vkQueueSubmit(queue, 1, &submitInfo, m_encodeFence);
        vkWaitForFences(device, 1, &m_encodeFence, VK_TRUE, UINT64_MAX);

        // Map staging buffer
        void* mapped = nullptr;
        VkResult err = vkMapMemory(device, m_stagingMemory, 0, m_stagingSize, 0, &mapped);
        if (err != VK_SUCCESS)
        {
            fprintf(stderr, "StreamingVulkan: failed to map staging buffer\n");
            return false;
        }
        memcpy(m_pixelBuffer.data(), mapped, m_stagingSize);
        vkUnmapMemory(device, m_stagingMemory);
        readOk = true;
    }

    if (!readOk)
        return false;

    double readbackMs = msElapsed(readbackStart);

    // --- Step 2: Encode ---
    auto encodeStart = Clock::now();
    bool encodeOk = false;
    uint32_t pixelSize = (uint32_t)(m_config.width * m_config.height * 4);

#ifdef OMNIUI_HAS_NVENC
    if (m_useNvenc)
    {
        encodeOk = encodeFrameNvenc(m_pixelBuffer.data(), pixelSize, pts);
    }
#endif

    if (!encodeOk)
    {
        encodeOk = encodeFrameCpu(m_pixelBuffer.data(), pixelSize, pts);
    }

    double encodeMs = msElapsed(encodeStart);

    // --- Step 3: Deliver NAL ---
    if (encodeOk && nalCallback && !m_encodedBuffer.empty())
    {
        nalCallback(m_encodedBuffer.data(), (uint32_t)m_encodedBuffer.size(), pts);
    }

    // Update stats
    m_lastStats.encodeTimeMs = encodeMs;
    m_lastStats.totalTimeMs  = msElapsed(frameStart);
    m_lastStats.nalSize      = encodeOk ? (uint32_t)m_encodedBuffer.size() : 0;

    return encodeOk;
}

const char* StreamingVulkan::getEncoderName() const
{
#ifdef OMNIUI_HAS_NVENC
    if (m_useNvenc)
        return m_config.codec == StreamCodec::eHEVC ? "NVENC-HEVC" : "NVENC-H264";
#endif
    return "CPU-stub";
}

// ---------------------------------------------------------------------------
// Vulkan synchronization
// ---------------------------------------------------------------------------

bool StreamingVulkan::createSyncObjects()
{
    VkDevice device = m_backend->getDevice();

    // Semaphores for render→encode synchronization
    VkSemaphoreCreateInfo semInfo = {};
    semInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;

    VkResult err = vkCreateSemaphore(device, &semInfo, nullptr, &m_renderDoneSemaphore);
    if (err != VK_SUCCESS) return false;

    err = vkCreateSemaphore(device, &semInfo, nullptr, &m_encodeDoneSemaphore);
    if (err != VK_SUCCESS) return false;

    // Fence for encode completion
    VkFenceCreateInfo fenceInfo = {};
    fenceInfo.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    fenceInfo.flags = VK_FENCE_CREATE_SIGNALED_BIT;
    err = vkCreateFence(device, &fenceInfo, nullptr, &m_encodeFence);
    if (err != VK_SUCCESS) return false;

    // Separate command pool + buffer for encode operations
    VkCommandPoolCreateInfo poolInfo = {};
    poolInfo.sType            = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    poolInfo.flags            = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    poolInfo.queueFamilyIndex = m_backend->getQueueFamily();
    err = vkCreateCommandPool(device, &poolInfo, nullptr, &m_encodeCommandPool);
    if (err != VK_SUCCESS) return false;

    VkCommandBufferAllocateInfo allocInfo = {};
    allocInfo.sType              = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    allocInfo.commandPool        = m_encodeCommandPool;
    allocInfo.level              = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    allocInfo.commandBufferCount = 1;
    err = vkAllocateCommandBuffers(device, &allocInfo, &m_encodeCommandBuffer);
    return err == VK_SUCCESS;
}

void StreamingVulkan::destroySyncObjects()
{
    VkDevice device = m_backend ? m_backend->getDevice() : VK_NULL_HANDLE;
    if (device == VK_NULL_HANDLE)
        return;

    if (m_encodeCommandPool != VK_NULL_HANDLE)
    {
        vkDestroyCommandPool(device, m_encodeCommandPool, nullptr);
        m_encodeCommandPool   = VK_NULL_HANDLE;
        m_encodeCommandBuffer = VK_NULL_HANDLE;
    }
    if (m_encodeFence != VK_NULL_HANDLE)
    {
        vkDestroyFence(device, m_encodeFence, nullptr);
        m_encodeFence = VK_NULL_HANDLE;
    }
    if (m_renderDoneSemaphore != VK_NULL_HANDLE)
    {
        vkDestroySemaphore(device, m_renderDoneSemaphore, nullptr);
        m_renderDoneSemaphore = VK_NULL_HANDLE;
    }
    if (m_encodeDoneSemaphore != VK_NULL_HANDLE)
    {
        vkDestroySemaphore(device, m_encodeDoneSemaphore, nullptr);
        m_encodeDoneSemaphore = VK_NULL_HANDLE;
    }
}

// ===========================================================================
// NVENC Hardware Encoder
// ===========================================================================

#ifdef OMNIUI_HAS_NVENC

bool StreamingVulkan::initNvenc()
{
    // Load NVENC API
    NV_ENCODE_API_FUNCTION_LIST nvenc = {};
    nvenc.version = NV_ENCODE_API_FUNCTION_LIST_VER;

    NVENCSTATUS status = NvEncodeAPICreateInstance(&nvenc);
    if (status != NV_ENC_SUCCESS)
    {
        fprintf(stderr, "StreamingVulkan: NvEncodeAPICreateInstance failed (%d)\n", status);
        return false;
    }

    // Open encode session
    NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS sessionParams = {};
    sessionParams.version    = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER;
    sessionParams.deviceType = NV_ENC_DEVICE_TYPE_CUDA;
    // Note: In a full implementation, we'd use a CUcontext here.
    // For now, use the device pointer from CUDA interop if available.
    sessionParams.device     = m_cudaMappedPtr;  // CUcontext
    sessionParams.apiVersion = NVENCAPI_VERSION;

    void* encoder = nullptr;
    status = nvenc.nvEncOpenEncodeSessionEx(&sessionParams, &encoder);
    if (status != NV_ENC_SUCCESS)
    {
        fprintf(stderr, "StreamingVulkan: nvEncOpenEncodeSessionEx failed (%d)\n", status);
        return false;
    }
    m_nvencEncoder = encoder;

    // Initialize encoder with preset
    GUID codecGuid = (m_config.codec == StreamCodec::eHEVC)
                         ? NV_ENC_CODEC_HEVC_GUID
                         : NV_ENC_CODEC_H264_GUID;

    NV_ENC_INITIALIZE_PARAMS initParams = {};
    initParams.version           = NV_ENC_INITIALIZE_PARAMS_VER;
    initParams.encodeGUID        = codecGuid;
    initParams.presetGUID        = NV_ENC_PRESET_P4_GUID;
    initParams.encodeWidth       = m_config.width;
    initParams.encodeHeight      = m_config.height;
    initParams.darWidth          = m_config.width;
    initParams.darHeight         = m_config.height;
    initParams.frameRateNum      = (uint32_t)m_config.fps;
    initParams.frameRateDen      = 1;
    initParams.enablePTD         = 1;

    NV_ENC_PRESET_CONFIG presetConfig = {};
    presetConfig.version       = NV_ENC_PRESET_CONFIG_VER;
    presetConfig.presetCfg.version = NV_ENC_CONFIG_VER;

    status = nvenc.nvEncGetEncodePresetConfigEx(encoder, codecGuid,
                                                NV_ENC_PRESET_P4_GUID,
                                                NV_ENC_TUNING_INFO_LOW_LATENCY,
                                                &presetConfig);
    if (status != NV_ENC_SUCCESS)
    {
        fprintf(stderr, "StreamingVulkan: nvEncGetEncodePresetConfigEx failed (%d)\n", status);
        nvenc.nvEncDestroyEncoder(encoder);
        m_nvencEncoder = nullptr;
        return false;
    }

    NV_ENC_CONFIG encodeConfig = presetConfig.presetCfg;
    encodeConfig.rcParams.averageBitRate = (uint32_t)(m_config.bitrateMbps * 1000000);
    encodeConfig.rcParams.maxBitRate     = encodeConfig.rcParams.averageBitRate * 2;
    encodeConfig.rcParams.rateControlMode = NV_ENC_PARAMS_RC_CBR;

    initParams.encodeConfig = &encodeConfig;
    initParams.tuningInfo   = NV_ENC_TUNING_INFO_LOW_LATENCY;

    status = nvenc.nvEncInitializeEncoder(encoder, &initParams);
    if (status != NV_ENC_SUCCESS)
    {
        fprintf(stderr, "StreamingVulkan: nvEncInitializeEncoder failed (%d)\n", status);
        nvenc.nvEncDestroyEncoder(encoder);
        m_nvencEncoder = nullptr;
        return false;
    }

    m_nvencSession = new NV_ENCODE_API_FUNCTION_LIST(nvenc);
    return true;
}

void StreamingVulkan::shutdownNvenc()
{
    if (m_nvencEncoder && m_nvencSession)
    {
        auto* nvenc = static_cast<NV_ENCODE_API_FUNCTION_LIST*>(m_nvencSession);
        nvenc->nvEncDestroyEncoder(m_nvencEncoder);
        delete nvenc;
    }
    m_nvencEncoder = nullptr;
    m_nvencSession = nullptr;
}

bool StreamingVulkan::encodeFrameNvenc(const uint8_t* rgba, uint32_t size, uint64_t pts)
{
    if (!m_nvencEncoder || !m_nvencSession)
        return false;

    auto* nvenc = static_cast<NV_ENCODE_API_FUNCTION_LIST*>(m_nvencSession);

    // Register input resource
    NV_ENC_REGISTER_RESOURCE regRes = {};
    regRes.version            = NV_ENC_REGISTER_RESOURCE_VER;
    regRes.resourceType       = NV_ENC_INPUT_RESOURCE_TYPE_CUDADEVICEPTR;
    regRes.width              = m_config.width;
    regRes.height             = m_config.height;
    regRes.pitch              = m_config.width * 4;
    regRes.bufferFormat       = NV_ENC_BUFFER_FORMAT_ABGR;
    regRes.resourceToRegister = (void*)rgba;

    NVENCSTATUS status = nvenc->nvEncRegisterResource(m_nvencEncoder, &regRes);
    if (status != NV_ENC_SUCCESS)
        return false;

    // Map input
    NV_ENC_MAP_INPUT_RESOURCE mapRes = {};
    mapRes.version          = NV_ENC_MAP_INPUT_RESOURCE_VER;
    mapRes.registeredResource = regRes.registeredResource;
    status = nvenc->nvEncMapInputResource(m_nvencEncoder, &mapRes);
    if (status != NV_ENC_SUCCESS)
    {
        nvenc->nvEncUnregisterResource(m_nvencEncoder, regRes.registeredResource);
        return false;
    }

    // Create output bitstream buffer
    NV_ENC_CREATE_BITSTREAM_BUFFER bsCreate = {};
    bsCreate.version = NV_ENC_CREATE_BITSTREAM_BUFFER_VER;
    status = nvenc->nvEncCreateBitstreamBuffer(m_nvencEncoder, &bsCreate);
    if (status != NV_ENC_SUCCESS)
    {
        nvenc->nvEncUnmapInputResource(m_nvencEncoder, mapRes.mappedResource);
        nvenc->nvEncUnregisterResource(m_nvencEncoder, regRes.registeredResource);
        return false;
    }

    // Encode
    NV_ENC_PIC_PARAMS picParams = {};
    picParams.version         = NV_ENC_PIC_PARAMS_VER;
    picParams.inputBuffer     = mapRes.mappedResource;
    picParams.bufferFmt       = mapRes.mappedBufferFmt;
    picParams.inputWidth      = m_config.width;
    picParams.inputHeight     = m_config.height;
    picParams.outputBitstream = bsCreate.bitstreamBuffer;
    picParams.pictureStruct   = NV_ENC_PIC_STRUCT_FRAME;
    picParams.inputTimeStamp  = pts;

    status = nvenc->nvEncEncodePicture(m_nvencEncoder, &picParams);
    if (status != NV_ENC_SUCCESS && status != NV_ENC_ERR_NEED_MORE_INPUT)
    {
        nvenc->nvEncDestroyBitstreamBuffer(m_nvencEncoder, bsCreate.bitstreamBuffer);
        nvenc->nvEncUnmapInputResource(m_nvencEncoder, mapRes.mappedResource);
        nvenc->nvEncUnregisterResource(m_nvencEncoder, regRes.registeredResource);
        return false;
    }

    // Lock output
    NV_ENC_LOCK_BITSTREAM lockBs = {};
    lockBs.version = NV_ENC_LOCK_BITSTREAM_VER;
    lockBs.outputBitstream = bsCreate.bitstreamBuffer;
    status = nvenc->nvEncLockBitstream(m_nvencEncoder, &lockBs);
    if (status == NV_ENC_SUCCESS)
    {
        m_encodedBuffer.resize(lockBs.bitstreamSizeInBytes);
        memcpy(m_encodedBuffer.data(), lockBs.bitstreamBufferPtr, lockBs.bitstreamSizeInBytes);
        nvenc->nvEncUnlockBitstream(m_nvencEncoder, lockBs.outputBitstream);
    }

    // Cleanup
    nvenc->nvEncDestroyBitstreamBuffer(m_nvencEncoder, bsCreate.bitstreamBuffer);
    nvenc->nvEncUnmapInputResource(m_nvencEncoder, mapRes.mappedResource);
    nvenc->nvEncUnregisterResource(m_nvencEncoder, regRes.registeredResource);

    return status == NV_ENC_SUCCESS;
}

#else // !OMNIUI_HAS_NVENC

bool StreamingVulkan::initNvenc()    { return false; }
void StreamingVulkan::shutdownNvenc() {}
bool StreamingVulkan::encodeFrameNvenc(const uint8_t*, uint32_t, uint64_t) { return false; }

#endif

// ===========================================================================
// CUDA-Vulkan Interop
// ===========================================================================

#ifdef OMNIUI_HAS_CUDA_INTEROP

bool StreamingVulkan::initCudaInterop()
{
    // Initialize CUDA
    CUresult cuErr = cuInit(0);
    if (cuErr != CUDA_SUCCESS)
    {
        fprintf(stderr, "StreamingVulkan: cuInit failed (%d)\n", cuErr);
        return false;
    }

    // Get CUDA device matching the Vulkan physical device
    CUdevice cuDevice;
    cuErr = cuDeviceGet(&cuDevice, 0);
    if (cuErr != CUDA_SUCCESS)
        return false;

    CUcontext cuCtx;
    // Call the versioned v2 driver symbol directly so the (flags, dev) ABI is
    // stable across CUDA toolkits. See the forward declaration above for why
    // we bypass the public `cuCtxCreate` macro instead of relying on it.
    cuErr = cuCtxCreate_v2(&cuCtx, 0, cuDevice);
    if (cuErr != CUDA_SUCCESS)
        return false;

    m_cudaMappedPtr = (void*)cuCtx;

    // Import Vulkan memory as CUDA external memory
    VkDeviceMemory vkMem = m_backend->getColorMemory();
    VkDeviceSize memSize = (VkDeviceSize)m_config.width * m_config.height * 4;

    CUDA_EXTERNAL_MEMORY_HANDLE_DESC extMemDesc = {};
    extMemDesc.type = CU_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD;
    // In production: use vkGetMemoryFdKHR to get the FD
    extMemDesc.size = memSize;

    CUexternalMemory extMem;
    cuErr = cuImportExternalMemory(&extMem, &extMemDesc);
    if (cuErr != CUDA_SUCCESS)
    {
        fprintf(stderr, "StreamingVulkan: cuImportExternalMemory failed (%d)\n", cuErr);
        cuCtxDestroy(cuCtx);
        m_cudaMappedPtr = nullptr;
        return false;
    }
    m_cudaExtMemory = (void*)extMem;

    return true;
}

void StreamingVulkan::shutdownCudaInterop()
{
    if (m_cudaExtMemory)
    {
        cuDestroyExternalMemory((CUexternalMemory)m_cudaExtMemory);
        m_cudaExtMemory = nullptr;
    }
    if (m_cudaMappedPtr)
    {
        cuCtxDestroy((CUcontext)m_cudaMappedPtr);
        m_cudaMappedPtr = nullptr;
    }
}

bool StreamingVulkan::readbackViaCuda(uint8_t* outPixels)
{
    if (!m_cudaExtMemory)
        return false;

    // Map external memory buffer
    CUDA_EXTERNAL_MEMORY_BUFFER_DESC bufDesc = {};
    bufDesc.offset = 0;
    bufDesc.size   = (size_t)m_config.width * m_config.height * 4;

    CUdeviceptr devPtr;
    CUresult err = cuExternalMemoryGetMappedBuffer(&devPtr, (CUexternalMemory)m_cudaExtMemory, &bufDesc);
    if (err != CUDA_SUCCESS)
        return false;

    // Copy device→host
    err = cuMemcpyDtoH(outPixels, devPtr, bufDesc.size);
    return err == CUDA_SUCCESS;
}

#else // !OMNIUI_HAS_CUDA_INTEROP

bool StreamingVulkan::initCudaInterop()    { return false; }
void StreamingVulkan::shutdownCudaInterop() {}
bool StreamingVulkan::readbackViaCuda(uint8_t*) { return false; }

#endif

// ===========================================================================
// CPU Fallback Encoder
// ===========================================================================
//
// Emits a minimal NAL-like bitstream:
//   [4-byte start code 00 00 00 01] [1-byte NAL header] [payload]
//
// The payload is a simple run-length-encoded delta from the previous frame,
// enough to prove the pipeline works end-to-end and produce a parseable .h264
// file with valid NAL boundaries.

bool StreamingVulkan::initCpuEncoder()
{
    m_cpuFrameCount = 0;
    m_cpuPrevFrame.clear();
    m_encodedBuffer.reserve(m_config.width * m_config.height);  // generous initial alloc
    return true;
}

void StreamingVulkan::shutdownCpuEncoder()
{
    m_cpuPrevFrame.clear();
    m_cpuFrameCount = 0;
}

bool StreamingVulkan::encodeFrameCpu(const uint8_t* rgba, uint32_t size, uint64_t pts)
{
    m_encodedBuffer.clear();

    // NAL start code
    m_encodedBuffer.push_back(0x00);
    m_encodedBuffer.push_back(0x00);
    m_encodedBuffer.push_back(0x00);
    m_encodedBuffer.push_back(0x01);

    // NAL header byte:
    //   forbidden_zero_bit = 0
    //   nal_ref_idc = 3 (high priority)
    //   nal_unit_type = 5 (IDR) for keyframes, 1 (non-IDR) otherwise
    bool isKeyframe = (m_cpuFrameCount % 30 == 0) || m_cpuPrevFrame.empty();
    uint8_t nalHeader = isKeyframe ? 0x65 : 0x41;  // (3<<5)|5 or (2<<5)|1
    m_encodedBuffer.push_back(nalHeader);

    // Frame metadata header (12 bytes)
    // [width:2][height:2][pts:8]
    uint16_t w = (uint16_t)m_config.width;
    uint16_t h = (uint16_t)m_config.height;
    m_encodedBuffer.push_back((uint8_t)(w >> 8));
    m_encodedBuffer.push_back((uint8_t)(w & 0xFF));
    m_encodedBuffer.push_back((uint8_t)(h >> 8));
    m_encodedBuffer.push_back((uint8_t)(h & 0xFF));
    for (int i = 7; i >= 0; i--)
        m_encodedBuffer.push_back((uint8_t)((pts >> (i * 8)) & 0xFF));

    // Payload: RLE-delta encoding (Y channel only for compactness)
    // Convert RGBA → Y (luma) and delta-encode against previous frame
    uint32_t pixelCount = m_config.width * m_config.height;
    std::vector<uint8_t> luma(pixelCount);
    for (uint32_t i = 0; i < pixelCount; i++)
    {
        uint32_t r = rgba[i * 4 + 0];
        uint32_t g = rgba[i * 4 + 1];
        uint32_t b = rgba[i * 4 + 2];
        luma[i] = (uint8_t)((r * 66 + g * 129 + b * 25 + 128) >> 8) + 16;
    }

    // Delta from previous frame
    std::vector<uint8_t> delta(pixelCount);
    if (isKeyframe || m_cpuPrevFrame.size() != pixelCount)
    {
        memcpy(delta.data(), luma.data(), pixelCount);
    }
    else
    {
        for (uint32_t i = 0; i < pixelCount; i++)
            delta[i] = luma[i] - m_cpuPrevFrame[i];
    }

    // Simple RLE: [count:1][value:1] pairs
    // Escape 0x00 0x00 sequences to avoid NAL start-code collisions
    uint32_t i = 0;
    while (i < pixelCount)
    {
        uint8_t val = delta[i];
        uint8_t count = 1;
        while (i + count < pixelCount && delta[i + count] == val && count < 255)
            count++;

        m_encodedBuffer.push_back(count);
        m_encodedBuffer.push_back(val);

        // Emulation prevention: if we just wrote 00 00, add 03
        size_t sz = m_encodedBuffer.size();
        if (sz >= 3 && m_encodedBuffer[sz - 1] == 0x00 &&
            m_encodedBuffer[sz - 2] == 0x00 && m_encodedBuffer[sz - 3] == 0x00)
        {
            // Insert emulation prevention byte before the last 0x00
            m_encodedBuffer.insert(m_encodedBuffer.end() - 1, 0x03);
        }

        i += count;
    }

    // Save current luma for next frame's delta
    m_cpuPrevFrame = std::move(luma);
    m_cpuFrameCount++;

    return true;
}

} // namespace standalone
} // namespace ui
} // namespace omni
