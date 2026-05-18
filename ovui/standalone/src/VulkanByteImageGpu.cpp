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

#include "VulkanByteImageGpu.h"

#include "VulkanBackend.h"

#if OMNIUI_HAS_CUDA
#  include "CudaVulkanInterop.h"
#  include <cuda_runtime.h>
#endif

#include <imgui/imgui.h>
#include <imgui/backends/imgui_impl_vulkan.h>

#include <atomic>
#include <cstdio>
#include <cstring>

namespace omni {
namespace ui {
namespace standalone {

namespace {

struct VkTextureState
{
    VkImage         image        = VK_NULL_HANDLE;
    VkDeviceMemory  memory       = VK_NULL_HANDLE;
    VkImageView     view         = VK_NULL_HANDLE;
    VkSampler       sampler      = VK_NULL_HANDLE;
    VkDescriptorSet descriptorSet = VK_NULL_HANDLE;
    uint32_t        width        = 0;
    uint32_t        height       = 0;
    PixelFormat     format       = PixelFormat::eRGBA8_UNORM;
#if OMNIUI_HAS_CUDA
    bool             externalMemory = false;
    VkDeviceSize     memorySize     = 0;
    CudaImageImport  cudaImport     = {};
    bool             cudaImportTried = false;
#endif
};

uint32_t findMemoryType(VkPhysicalDevice phys, uint32_t typeBits, VkMemoryPropertyFlags props)
{
    VkPhysicalDeviceMemoryProperties memProps;
    vkGetPhysicalDeviceMemoryProperties(phys, &memProps);
    for (uint32_t i = 0; i < memProps.memoryTypeCount; ++i)
    {
        if ((typeBits & (1u << i)) && (memProps.memoryTypes[i].propertyFlags & props) == props)
            return i;
    }
    return UINT32_MAX;
}

void destroyTexture(VulkanBackend* backend, VkTextureState* s)
{
    if (!backend || !s) return;
    VkDevice device = backend->getDevice();
    if (device == VK_NULL_HANDLE) return;
    vkDeviceWaitIdle(device);
    if (s->descriptorSet != VK_NULL_HANDLE)
    {
        ImGui_ImplVulkan_RemoveTexture(s->descriptorSet);
        s->descriptorSet = VK_NULL_HANDLE;
    }
#if OMNIUI_HAS_CUDA
    // CUDA holds a reference to the VkDeviceMemory via the imported handle.
    // Destroy the CUDA-side resources first so the underlying memory can be
    // safely freed below.
    destroyCudaImageImport(&s->cudaImport);
    s->cudaImportTried = false;
    s->externalMemory = false;
    s->memorySize = 0;
#endif
    if (s->view)    { vkDestroyImageView(device, s->view, nullptr);   s->view = VK_NULL_HANDLE; }
    if (s->sampler) { vkDestroySampler(device, s->sampler, nullptr);  s->sampler = VK_NULL_HANDLE; }
    if (s->image)   { vkDestroyImage(device, s->image, nullptr);      s->image = VK_NULL_HANDLE; }
    if (s->memory)  { vkFreeMemory(device, s->memory, nullptr);       s->memory = VK_NULL_HANDLE; }
    s->width = s->height = 0;
    s->format = PixelFormat::eRGBA8_UNORM;
}

} // anonymous namespace

VulkanByteImageGpu::~VulkanByteImageGpu()
{
#if OMNIUI_HAS_CUDA
    if (m_backend && m_sync.initialized)
    {
        VkDevice device = m_backend->getDevice();
        if (device != VK_NULL_HANDLE)
            vkDeviceWaitIdle(device);
        destroyCudaInteropSemaphores(device, &m_sync);
    }
#endif
}

IByteImageGpu::Handle VulkanByteImageGpu::createState()
{
    return new VkTextureState();
}

void VulkanByteImageGpu::destroyState(Handle h)
{
    auto* s = static_cast<VkTextureState*>(h);
    if (!s) return;
    destroyTexture(m_backend, s);
    delete s;
}

IByteImageGpu::UpdateResult VulkanByteImageGpu::updateImage(
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
    UpdateResult result;
    auto* s = static_cast<VkTextureState*>(h);
    if (!s || !m_backend || !mipMapBuffers || mipMapCount == 0 || size.x == 0 || size.y == 0)
        return result;
#if !OMNIUI_HAS_CUDA
    if (fromGpu)
    {
        static std::atomic<bool> warned{false};
        if (!warned.exchange(true, std::memory_order_relaxed))
            fprintf(stderr, "VulkanByteImageGpu: fromGpu requires CUDA support (not compiled in)\n");
        return result;
    }
#endif

    VkFormat vkFormat;
    size_t bytesPerPixel;
    bool isR8 = false;
    // ``imageChannelCount`` is the on-image channel count (1/2/3/4).
    // It distinguishes the "expand R8 into RGBA8 storage" case (R8
    // uploads as RGBA8 with swizzle, so on-image is still 4-channel)
    // from the native single/two/three-channel float formats below.
    int imageChannelCount = 4;
    switch (format)
    {
        case PixelFormat::eRGBA8_UNORM: vkFormat = VK_FORMAT_R8G8B8A8_UNORM;     bytesPerPixel = 4;  break;
        case PixelFormat::eRGBA8_SRGB:  vkFormat = VK_FORMAT_R8G8B8A8_SRGB;      bytesPerPixel = 4;  break;
        case PixelFormat::eBGRA8_UNORM: vkFormat = VK_FORMAT_B8G8R8A8_UNORM;     bytesPerPixel = 4;  break;
        case PixelFormat::eR8_UNORM:    vkFormat = VK_FORMAT_R8G8B8A8_UNORM;     bytesPerPixel = 4;  isR8 = true; break;
        case PixelFormat::eR16_FLOAT:   vkFormat = VK_FORMAT_R16_SFLOAT;         bytesPerPixel = 2;  imageChannelCount = 1; break;
        case PixelFormat::eR32_FLOAT:   vkFormat = VK_FORMAT_R32_SFLOAT;         bytesPerPixel = 4;  imageChannelCount = 1; break;
        case PixelFormat::eRG16_FLOAT:  vkFormat = VK_FORMAT_R16G16_SFLOAT;      bytesPerPixel = 4;  imageChannelCount = 2; break;
        case PixelFormat::eRG32_FLOAT:  vkFormat = VK_FORMAT_R32G32_SFLOAT;      bytesPerPixel = 8;  imageChannelCount = 2; break;
        case PixelFormat::eRGB16_FLOAT: vkFormat = VK_FORMAT_R16G16B16_SFLOAT;   bytesPerPixel = 6;  imageChannelCount = 3; break;
        case PixelFormat::eRGB32_FLOAT: vkFormat = VK_FORMAT_R32G32B32_SFLOAT;   bytesPerPixel = 12; imageChannelCount = 3; break;
        case PixelFormat::eRGBA16_FLOAT:vkFormat = VK_FORMAT_R16G16B16A16_SFLOAT;bytesPerPixel = 8;  break;
        case PixelFormat::eRGBA32_FLOAT:vkFormat = VK_FORMAT_R32G32B32A32_SFLOAT;bytesPerPixel = 16; break;
        default:
            fprintf(stderr, "VulkanByteImageGpu: unsupported pixel format %d\n", (int)format);
            return result;
    }

    VkDevice device = m_backend->getDevice();
    VkPhysicalDevice phys = m_backend->getPhysicalDevice();
    VkQueue queue = m_backend->getQueue();
    VkCommandPool cmdPool = m_backend->getCommandPool();
    if (device == VK_NULL_HANDLE || cmdPool == VK_NULL_HANDLE) return result;

    // Vulkan does not require implementations to support all
    // ``VkFormat`` values with optimal tiling. ``VK_FORMAT_R32G32B32_*``
    // in particular is unsupported on most desktop GPUs — silently
    // failing inside vkCreateImage would produce the same opaque
    // "Failed to create texture GPU data!" log the user is already
    // seeing. Probe the format up front and emit a targeted error so
    // the caller knows to pad 3-channel data to 4 channels.
    {
        VkFormatProperties fp = {};
        vkGetPhysicalDeviceFormatProperties(phys, vkFormat, &fp);
        const VkFormatFeatureFlags needed = VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT
                                          | VK_FORMAT_FEATURE_TRANSFER_DST_BIT;
        if ((fp.optimalTilingFeatures & needed) != needed)
        {
            static std::atomic<bool> warned{false};
            if (!warned.exchange(true, std::memory_order_relaxed))
                fprintf(stderr,
                        "VulkanByteImageGpu: VkFormat %d not supported with "
                        "optimal tiling for sampled/transfer-dst (features=0x%x). "
                        "Pad to a 4-channel format on the producer side.\n",
                        (int)vkFormat, (unsigned)fp.optimalTilingFeatures);
            return result;
        }
    }

    // Reject fromGpu+3-channel before any VkImage is allocated. The
    // CUDA-Vulkan interop path can't represent 3-channel arrays
    // (cudaCreateChannelDesc rejects a zero in any of the first three
    // slots), so producers must pad to RGBA. Doing this check after
    // image allocation would leave a stale VkImage with undefined
    // content behind, which makes the "did the upload happen?" signal
    // ambiguous for tests.
    if (fromGpu && imageChannelCount == 3)
    {
        static std::atomic<bool> warned{false};
        if (!warned.exchange(true, std::memory_order_relaxed))
            fprintf(stderr,
                    "VulkanByteImageGpu: fromGpu=true with 3-channel "
                    "format is not supported (pad to RGBA on the producer side)\n");
        return result;
    }

    // Recreate if size changed or first time (we only use mip 0; mip chain is
    // dropped in this backend because combining mips with arbitrary strides on
    // Vulkan would need per-mip staging copies; the visual difference at
    // tested render sizes is negligible).
    const uint32_t width = size.x;
    const uint32_t height = size.y;
    if (s->image == VK_NULL_HANDLE
        || s->width != width
        || s->height != height
        || s->format != format)
    {
        destroyTexture(m_backend, s);

        VkImageCreateInfo imageInfo = {};
        imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
        imageInfo.imageType = VK_IMAGE_TYPE_2D;
        imageInfo.format = vkFormat;
        imageInfo.extent = { width, height, 1 };
        imageInfo.mipLevels = 1;
        imageInfo.arrayLayers = 1;
        imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
        imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
        imageInfo.usage = VK_IMAGE_USAGE_SAMPLED_BIT
                        | VK_IMAGE_USAGE_TRANSFER_DST_BIT
                        | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
        imageInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
#if OMNIUI_HAS_CUDA
        // Allocate every texture as exportable so the fromGpu=true path can
        // import the same VkDeviceMemory into CUDA later. The cost is one
        // extra VkExternal* struct in the create chain — no runtime overhead
        // when CUDA is not used.
        VkExternalMemoryImageCreateInfo extImageInfo = {};
        extImageInfo.sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO;
#  if defined(_WIN32)
        extImageInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;
#  else
        extImageInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;
#  endif
        imageInfo.pNext = &extImageInfo;
#endif
        if (vkCreateImage(device, &imageInfo, nullptr, &s->image) != VK_SUCCESS)
            return result;

        VkMemoryRequirements memReq;
        vkGetImageMemoryRequirements(device, s->image, &memReq);
        VkMemoryAllocateInfo allocInfo = {};
        allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        allocInfo.allocationSize = memReq.size;
        allocInfo.memoryTypeIndex = findMemoryType(phys, memReq.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
#if OMNIUI_HAS_CUDA
        VkExportMemoryAllocateInfo exportInfo = {};
        exportInfo.sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO;
#  if defined(_WIN32)
        exportInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;
#  else
        exportInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;
#  endif
        allocInfo.pNext = &exportInfo;
#endif
        if (vkAllocateMemory(device, &allocInfo, nullptr, &s->memory) != VK_SUCCESS)
        {
            destroyTexture(m_backend, s); return result;
        }
        vkBindImageMemory(device, s->image, s->memory, 0);
#if OMNIUI_HAS_CUDA
        s->externalMemory = true;
        s->memorySize = memReq.size;
#endif

        VkImageViewCreateInfo viewInfo = {};
        viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
        viewInfo.image = s->image;
        viewInfo.viewType = VK_IMAGE_VIEW_TYPE_2D;
        viewInfo.format = vkFormat;
        if (isR8)
        {
            // Font texture (R channel is alpha). Swizzle so that (1,1,1,R)
            // matches the OpenGL swizzle path.
            viewInfo.components = { VK_COMPONENT_SWIZZLE_ONE, VK_COMPONENT_SWIZZLE_ONE,
                                    VK_COMPONENT_SWIZZLE_ONE, VK_COMPONENT_SWIZZLE_R };
        }
        else if (imageChannelCount == 1)
        {
            // Single-channel float AOV viz: replicate red into RGB, force
            // opaque alpha. Mirrors the GL R16F/R32F swizzle.
            viewInfo.components = { VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_R,
                                    VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_ONE };
        }
        else if (imageChannelCount == 2)
        {
            viewInfo.components = { VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_G,
                                    VK_COMPONENT_SWIZZLE_ZERO, VK_COMPONENT_SWIZZLE_ONE };
        }
        else if (imageChannelCount == 3)
        {
            // 3-channel images have no alpha; force opaque on sample so
            // ImGui's color*texel.a term doesn't multiply by garbage.
            viewInfo.components = { VK_COMPONENT_SWIZZLE_R, VK_COMPONENT_SWIZZLE_G,
                                    VK_COMPONENT_SWIZZLE_B, VK_COMPONENT_SWIZZLE_ONE };
        }
        viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        viewInfo.subresourceRange.levelCount = 1;
        viewInfo.subresourceRange.layerCount = 1;
        if (vkCreateImageView(device, &viewInfo, nullptr, &s->view) != VK_SUCCESS)
        {
            destroyTexture(m_backend, s); return result;
        }

        VkSamplerCreateInfo samplerInfo = {};
        samplerInfo.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO;
        samplerInfo.magFilter = VK_FILTER_LINEAR;
        samplerInfo.minFilter = VK_FILTER_LINEAR;
        samplerInfo.mipmapMode = VK_SAMPLER_MIPMAP_MODE_LINEAR;
        samplerInfo.addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
        samplerInfo.addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
        samplerInfo.addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE;
        samplerInfo.minLod = 0.0f;
        samplerInfo.maxLod = 1.0f;
        samplerInfo.maxAnisotropy = 1.0f;
        // NOTE: ImGui's descriptor set layout has an immutable sampler, so the
        // one passed to AddTexture is ignored — we keep this object alive
        // only to match the interface. The font sampler is what actually
        // ends up bound.
        if (vkCreateSampler(device, &samplerInfo, nullptr, &s->sampler) != VK_SUCCESS)
        {
            destroyTexture(m_backend, s); return result;
        }

        s->width = width;
        s->height = height;
        s->format = format;
    }

#if OMNIUI_HAS_CUDA
    // --- Fast path: source is a CUDA device pointer. Import the
    // VkDeviceMemory as a CUDA mipmapped array (lazy, once per state),
    // then cudaMemcpy2DToArray straight from caller's device buffer.
    if (fromGpu)
    {
        if (isR8)
        {
            static std::atomic<bool> warned{false};
            if (!warned.exchange(true, std::memory_order_relaxed))
                fprintf(stderr, "VulkanByteImageGpu: fromGpu=true with R8 format is not supported (caller must pass RGBA8)\n");
            return result;
        }
        if (!s->externalMemory || s->memory == VK_NULL_HANDLE || s->memorySize == 0)
        {
            fprintf(stderr, "VulkanByteImageGpu: fromGpu requested but image was not allocated as external\n");
            return result;
        }

        // Channel descriptor must match the VkFormat byte-for-byte so
        // ``cudaExternalMemoryGetMappedMipmappedArray`` accepts the
        // import. The legacy importer used a hardcoded RGBA8 desc which
        // worked only for the 8-bit formats.
        cudaChannelFormatDesc channelDesc = cudaCreateChannelDesc(8, 8, 8, 8, cudaChannelFormatKindUnsigned);
        switch (format)
        {
            case PixelFormat::eRGBA8_UNORM:
            case PixelFormat::eRGBA8_SRGB:
            case PixelFormat::eBGRA8_UNORM:
                channelDesc = cudaCreateChannelDesc(8, 8, 8, 8, cudaChannelFormatKindUnsigned);
                break;
            case PixelFormat::eR16_FLOAT:
                channelDesc = cudaCreateChannelDesc(16, 0, 0, 0, cudaChannelFormatKindFloat);
                break;
            case PixelFormat::eR32_FLOAT:
                channelDesc = cudaCreateChannelDesc(32, 0, 0, 0, cudaChannelFormatKindFloat);
                break;
            case PixelFormat::eRG16_FLOAT:
                channelDesc = cudaCreateChannelDesc(16, 16, 0, 0, cudaChannelFormatKindFloat);
                break;
            case PixelFormat::eRG32_FLOAT:
                channelDesc = cudaCreateChannelDesc(32, 32, 0, 0, cudaChannelFormatKindFloat);
                break;
            case PixelFormat::eRGBA16_FLOAT:
                channelDesc = cudaCreateChannelDesc(16, 16, 16, 16, cudaChannelFormatKindFloat);
                break;
            case PixelFormat::eRGBA32_FLOAT:
                channelDesc = cudaCreateChannelDesc(32, 32, 32, 32, cudaChannelFormatKindFloat);
                break;
            default:
                // Should be unreachable — covered by the switch above.
                break;
        }

        // Lazy CUDA import — done once per (image, size). destroyTexture
        // resets cudaImportTried whenever it tears down the image.
        if (!s->cudaImportTried)
        {
            s->cudaImportTried = true;
            if (!importVkImageMemoryToCudaWithFormat(
                    device, phys, s->memory, s->memorySize,
                    (int)width, (int)height, channelDesc, &s->cudaImport))
            {
                static std::atomic<bool> warned{false};
                if (!warned.exchange(true, std::memory_order_relaxed))
                    fprintf(stderr, "VulkanByteImageGpu: importVkImageMemoryToCudaWithFormat failed; fromGpu disabled\n");
                return result;
            }
        }
        if (!s->cudaImport.array)
            return result;

        // Lazy init the V↔C external-semaphore pair (once per backend).
        if (!m_syncInitTried)
        {
            m_syncInitTried = true;
            if (!createCudaInteropSemaphores(device, phys, &m_sync))
            {
                fprintf(stderr, "VulkanByteImageGpu: createCudaInteropSemaphores failed; "
                                "fromGpu disabled\n");
                return result;
            }
        }
        if (!m_sync.initialized)
            return result;

        // Allocate two one-shot command buffers — one for the pre-copy V→C
        // transition (UNDEFINED|SHADER_READ → GENERAL, signals vkSemVkDone),
        // and one for the post-copy C→V transition (GENERAL → SHADER_READ,
        // waits on vkSemCuDone).
        VkCommandBuffer cmds[2] = { VK_NULL_HANDLE, VK_NULL_HANDLE };
        VkCommandBufferAllocateInfo cbAlloc = {};
        cbAlloc.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        cbAlloc.commandPool = cmdPool;
        cbAlloc.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        cbAlloc.commandBufferCount = 2;
        if (vkAllocateCommandBuffers(device, &cbAlloc, cmds) != VK_SUCCESS)
        {
            fprintf(stderr, "VulkanByteImageGpu: vkAllocateCommandBuffers (sync) failed\n");
            return result;
        }

        auto recordTransition = [&](VkCommandBuffer cmd,
                                    VkImageLayout oldLayout, VkImageLayout newLayout)
        {
            VkCommandBufferBeginInfo bi = {};
            bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
            bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
            vkBeginCommandBuffer(cmd, &bi);
            VkImageMemoryBarrier b = {};
            b.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
            b.oldLayout = oldLayout;
            b.newLayout = newLayout;
            b.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
            b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
            b.image = s->image;
            b.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
            b.subresourceRange.levelCount = 1;
            b.subresourceRange.layerCount = 1;
            b.srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT | VK_ACCESS_MEMORY_READ_BIT;
            b.dstAccessMask = VK_ACCESS_MEMORY_WRITE_BIT | VK_ACCESS_MEMORY_READ_BIT;
            vkCmdPipelineBarrier(cmd,
                VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
                VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
                0, 0, nullptr, 0, nullptr, 1, &b);
            vkEndCommandBuffer(cmd);
        };

        const VkImageLayout fromLayout = (s->descriptorSet == VK_NULL_HANDLE)
            ? VK_IMAGE_LAYOUT_UNDEFINED
            : VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
        recordTransition(cmds[0], fromLayout, VK_IMAGE_LAYOUT_GENERAL);
        recordTransition(cmds[1], VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);

        // Step 1 (V→C): submit the pre-copy transition, signalling vkSemVkDone.
        // Mirrors CudaVulkanInterop::syncVulkanToCuda.
        const uint64_t signalVkDone = ++m_sync.timelineValue;
        const uint64_t signalCuDone = ++m_sync.timelineValue;

        VkTimelineSemaphoreSubmitInfo timelineSignal = {};
        timelineSignal.sType = VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO;
        timelineSignal.signalSemaphoreValueCount = 1;
        timelineSignal.pSignalSemaphoreValues = &signalVkDone;

        VkSubmitInfo submitV2C = {};
        submitV2C.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        submitV2C.commandBufferCount = 1;
        submitV2C.pCommandBuffers = &cmds[0];
        submitV2C.signalSemaphoreCount = 1;
        submitV2C.pSignalSemaphores = &m_sync.vkSemVkDone;
        if (m_sync.useTimeline)
            submitV2C.pNext = &timelineSignal;

        if (vkQueueSubmit(queue, 1, &submitV2C, VK_NULL_HANDLE) != VK_SUCCESS)
        {
            fprintf(stderr, "VulkanByteImageGpu: vkQueueSubmit (V→C) failed\n");
            vkFreeCommandBuffers(device, cmdPool, 2, cmds);
            return result;
        }

        // Step 2: CUDA waits on extSemVkDone, does the copy, then signals
        // extSemCuDone — all asynchronously on the default stream. Mirrors
        // CudaVulkanInterop::syncVulkanToCuda's wait + the syncCudaToVulkan
        // signal pattern (CudaVulkanInterop.cpp:432-456).
        cudaExternalSemaphoreWaitParams waitParams = {};
        if (m_sync.useTimeline)
            waitParams.params.fence.value = signalVkDone;
        cudaError_t cuErr = cudaWaitExternalSemaphoresAsync(
            &m_sync.extSemVkDone, &waitParams, 1, /*stream=*/nullptr);
        if (cuErr != cudaSuccess)
        {
            fprintf(stderr, "VulkanByteImageGpu: cudaWaitExternalSemaphoresAsync failed: %s\n",
                    cudaGetErrorString(cuErr));
            vkQueueWaitIdle(queue);
            vkFreeCommandBuffers(device, cmdPool, 2, cmds);
            return result;
        }

        const void* srcDev = static_cast<const void*>(mipMapBuffers[0]);
        const size_t srcPitch = (mipMapStrides && mipMapStrides[0])
            ? mipMapStrides[0]
            : (size_t)width * bytesPerPixel;
        const size_t rowBytes = (size_t)width * bytesPerPixel;
        cuErr = cudaMemcpy2DToArrayAsync(
            s->cudaImport.array,
            /*wOffset=*/0, /*hOffset=*/0,
            srcDev,
            /*spitch=*/srcPitch,
            /*width=*/rowBytes,
            /*height=*/height,
            cudaMemcpyDeviceToDevice,
            /*stream=*/nullptr);
        if (cuErr != cudaSuccess)
        {
            fprintf(stderr, "VulkanByteImageGpu: cudaMemcpy2DToArrayAsync failed: %s\n",
                    cudaGetErrorString(cuErr));
            vkQueueWaitIdle(queue);
            vkFreeCommandBuffers(device, cmdPool, 2, cmds);
            return result;
        }

        cudaExternalSemaphoreSignalParams signalParams = {};
        if (m_sync.useTimeline)
            signalParams.params.fence.value = signalCuDone;
        cuErr = cudaSignalExternalSemaphoresAsync(
            &m_sync.extSemCuDone, &signalParams, 1, /*stream=*/nullptr);
        if (cuErr != cudaSuccess)
        {
            fprintf(stderr, "VulkanByteImageGpu: cudaSignalExternalSemaphoresAsync failed: %s\n",
                    cudaGetErrorString(cuErr));
            vkQueueWaitIdle(queue);
            vkFreeCommandBuffers(device, cmdPool, 2, cmds);
            return result;
        }

        // Step 3 (C→V): submit the post-copy transition, waiting on
        // vkSemCuDone. Mirrors CudaVulkanInterop::syncCudaToVulkan
        // (CudaVulkanInterop.cpp:444-483).
        VkPipelineStageFlags waitStage = VK_PIPELINE_STAGE_ALL_COMMANDS_BIT;
        VkTimelineSemaphoreSubmitInfo timelineWait = {};
        timelineWait.sType = VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO;
        timelineWait.waitSemaphoreValueCount = 1;
        timelineWait.pWaitSemaphoreValues = &signalCuDone;

        VkSubmitInfo submitC2V = {};
        submitC2V.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        submitC2V.commandBufferCount = 1;
        submitC2V.pCommandBuffers = &cmds[1];
        submitC2V.waitSemaphoreCount = 1;
        submitC2V.pWaitSemaphores = &m_sync.vkSemCuDone;
        submitC2V.pWaitDstStageMask = &waitStage;
        if (m_sync.useTimeline)
            submitC2V.pNext = &timelineWait;

        if (vkQueueSubmit(queue, 1, &submitC2V, VK_NULL_HANDLE) != VK_SUCCESS)
        {
            fprintf(stderr, "VulkanByteImageGpu: vkQueueSubmit (C→V) failed\n");
            vkQueueWaitIdle(queue);
            vkFreeCommandBuffers(device, cmdPool, 2, cmds);
            return result;
        }

        // Synchronous-API contract: callers expect the texture to be ready
        // for sampling when updateImage returns. The CUDA→Vulkan semaphore
        // chain replaces the old vkQueueWaitIdle + cudaDeviceSynchronize as
        // the *correctness* mechanism (no more racing the layout transition
        // against an unfinished CUDA copy); the trailing vkQueueWaitIdle
        // here only enforces "finished by return time".
        vkQueueWaitIdle(queue);
        vkFreeCommandBuffers(device, cmdPool, 2, cmds);

        if (s->descriptorSet == VK_NULL_HANDLE)
        {
            s->descriptorSet = ImGui_ImplVulkan_AddTexture(
                s->sampler, s->view, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
        }
        result.imGuiReference = reinterpret_cast<void*>(s->descriptorSet);
        return result;
    }
#endif // OMNIUI_HAS_CUDA

    // --- Upload pixels via a host-visible staging buffer ---
    const uint8_t* srcPixels = mipMapBuffers[0];
    size_t srcStride = (mipMapStrides && mipMapStrides[0]) ? mipMapStrides[0]
                                                           : (size_t)width * (isR8 ? 1 : bytesPerPixel);
    const size_t uploadRowBytes = (size_t)width * bytesPerPixel;
    const VkDeviceSize uploadSize = uploadRowBytes * height;

    VkBuffer stagingBuffer = VK_NULL_HANDLE;
    VkDeviceMemory stagingMem = VK_NULL_HANDLE;
    {
        VkBufferCreateInfo bufInfo = {};
        bufInfo.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
        bufInfo.size = uploadSize;
        bufInfo.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
        bufInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        vkCreateBuffer(device, &bufInfo, nullptr, &stagingBuffer);
        VkMemoryRequirements req;
        vkGetBufferMemoryRequirements(device, stagingBuffer, &req);
        VkMemoryAllocateInfo a = {};
        a.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        a.allocationSize = req.size;
        a.memoryTypeIndex = findMemoryType(phys, req.memoryTypeBits,
                                           VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        vkAllocateMemory(device, &a, nullptr, &stagingMem);
        vkBindBufferMemory(device, stagingBuffer, stagingMem, 0);
    }
    void* mapped = nullptr;
    vkMapMemory(device, stagingMem, 0, uploadSize, 0, &mapped);
    if (isR8)
    {
        // Expand R8 -> RGBA8 (rgb=0, a=R) so the shader's color*texel.a term
        // produces the font glyph. Matches the GL swizzle.
        uint8_t* dst = static_cast<uint8_t*>(mapped);
        for (uint32_t y = 0; y < height; ++y)
        {
            const uint8_t* srcRow = srcPixels + y * srcStride;
            uint8_t* dstRow = dst + (size_t)y * uploadRowBytes;
            for (uint32_t x = 0; x < width; ++x)
            {
                dstRow[x * 4 + 0] = 255;
                dstRow[x * 4 + 1] = 255;
                dstRow[x * 4 + 2] = 255;
                dstRow[x * 4 + 3] = srcRow[x];
            }
        }
    }
    else if (srcStride == uploadRowBytes)
    {
        std::memcpy(mapped, srcPixels, uploadSize);
    }
    else
    {
        uint8_t* dst = static_cast<uint8_t*>(mapped);
        for (uint32_t y = 0; y < height; ++y)
            std::memcpy(dst + (size_t)y * uploadRowBytes, srcPixels + (size_t)y * srcStride, uploadRowBytes);
    }
    vkUnmapMemory(device, stagingMem);

    // One-shot command buffer for upload + layout transition
    VkCommandBuffer cmd = VK_NULL_HANDLE;
    {
        VkCommandBufferAllocateInfo allocInfo = {};
        allocInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        allocInfo.commandPool = cmdPool;
        allocInfo.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        allocInfo.commandBufferCount = 1;
        vkAllocateCommandBuffers(device, &allocInfo, &cmd);
    }
    {
        VkCommandBufferBeginInfo beginInfo = {};
        beginInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
        beginInfo.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
        vkBeginCommandBuffer(cmd, &beginInfo);

        VkImageMemoryBarrier toTransfer = {};
        toTransfer.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
        toTransfer.srcAccessMask = VK_ACCESS_SHADER_READ_BIT;
        toTransfer.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        toTransfer.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
        toTransfer.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        toTransfer.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        toTransfer.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        toTransfer.image = s->image;
        toTransfer.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        toTransfer.subresourceRange.levelCount = 1;
        toTransfer.subresourceRange.layerCount = 1;
        vkCmdPipelineBarrier(cmd,
            VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
            VK_PIPELINE_STAGE_TRANSFER_BIT,
            0, 0, nullptr, 0, nullptr, 1, &toTransfer);

        VkBufferImageCopy region = {};
        region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.imageSubresource.layerCount = 1;
        region.imageExtent = { width, height, 1 };
        vkCmdCopyBufferToImage(cmd, stagingBuffer, s->image,
                               VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);

        VkImageMemoryBarrier toRead = toTransfer;
        toRead.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        toRead.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
        toRead.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        toRead.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
        vkCmdPipelineBarrier(cmd,
            VK_PIPELINE_STAGE_TRANSFER_BIT,
            VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
            0, 0, nullptr, 0, nullptr, 1, &toRead);

        vkEndCommandBuffer(cmd);

        VkSubmitInfo submit = {};
        submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        submit.commandBufferCount = 1;
        submit.pCommandBuffers = &cmd;
        vkQueueSubmit(queue, 1, &submit, VK_NULL_HANDLE);
        vkQueueWaitIdle(queue);
        vkFreeCommandBuffers(device, cmdPool, 1, &cmd);
    }

    vkDestroyBuffer(device, stagingBuffer, nullptr);
    vkFreeMemory(device, stagingMem, nullptr);

    // Register (or re-register after resize) with ImGui.
    if (s->descriptorSet == VK_NULL_HANDLE)
    {
        s->descriptorSet = ImGui_ImplVulkan_AddTexture(
            s->sampler, s->view, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
    }

    result.imGuiReference = reinterpret_cast<void*>(s->descriptorSet);
    return result;
}

VkImage VulkanByteImageGpu::getVkImageForState(Handle h) const
{
    auto* s = static_cast<VkTextureState*>(h);
    return s ? s->image : VK_NULL_HANDLE;
}

void VulkanByteImageGpu::releaseImage(Handle h)
{
    auto* s = static_cast<VkTextureState*>(h);
    destroyTexture(m_backend, s);
}

} // namespace standalone
} // namespace ui
} // namespace omni
