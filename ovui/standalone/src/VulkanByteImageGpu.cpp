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
#  if !defined(_WIN32)
#    include <unistd.h>
#  endif
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
    VkBuffer         cudaUploadBuffer = VK_NULL_HANDLE;
    VkDeviceMemory   cudaUploadMemory = VK_NULL_HANDLE;
    VkDeviceSize     cudaUploadSize = 0;
    cudaExternalMemory_t cudaUploadExternalMemory = nullptr;
    void*            cudaUploadPtr = nullptr;
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

void destroyTexture(VulkanBackend* backend, VkTextureState* s, bool keepDescriptorSet = false)
{
    if (!backend || !s) return;
    VkDevice device = backend->getDevice();
    if (device == VK_NULL_HANDLE) return;
    vkDeviceWaitIdle(device);
    if (s->descriptorSet != VK_NULL_HANDLE && !keepDescriptorSet)
    {
        ImGui_ImplVulkan_RemoveTexture(s->descriptorSet);
        s->descriptorSet = VK_NULL_HANDLE;
    }
#if OMNIUI_HAS_CUDA
    if (s->cudaUploadPtr)
    {
        cudaFree(s->cudaUploadPtr);
        s->cudaUploadPtr = nullptr;
    }
    if (s->cudaUploadExternalMemory)
    {
        cudaDestroyExternalMemory(s->cudaUploadExternalMemory);
        s->cudaUploadExternalMemory = nullptr;
    }
    if (s->cudaUploadBuffer)
    {
        vkDestroyBuffer(device, s->cudaUploadBuffer, nullptr);
        s->cudaUploadBuffer = VK_NULL_HANDLE;
    }
    if (s->cudaUploadMemory)
    {
        vkFreeMemory(device, s->cudaUploadMemory, nullptr);
        s->cudaUploadMemory = VK_NULL_HANDLE;
    }
    s->cudaUploadSize = 0;
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

bool updateTextureDescriptor(VkDevice device, VkTextureState* s)
{
    if (!s || device == VK_NULL_HANDLE || s->descriptorSet == VK_NULL_HANDLE ||
        s->view == VK_NULL_HANDLE || s->sampler == VK_NULL_HANDLE)
    {
        return false;
    }

    VkDescriptorImageInfo imageInfo = {};
    imageInfo.sampler = s->sampler;
    imageInfo.imageView = s->view;
    imageInfo.imageLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;

    VkWriteDescriptorSet write = {};
    write.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET;
    write.dstSet = s->descriptorSet;
    write.dstBinding = 0;
    write.dstArrayElement = 0;
    write.descriptorCount = 1;
    write.descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER;
    write.pImageInfo = &imageInfo;
    vkUpdateDescriptorSets(device, 1, &write, 0, nullptr);
    return true;
}

#if OMNIUI_HAS_CUDA
bool importVkBufferMemoryToCuda(VkDevice device,
                                VkDeviceMemory memory,
                                VkDeviceSize memorySize,
                                cudaExternalMemory_t* outExternalMemory,
                                void** outPtr)
{
    if (!outExternalMemory || !outPtr || device == VK_NULL_HANDLE || memory == VK_NULL_HANDLE || memorySize == 0)
        return false;

    *outExternalMemory = nullptr;
    *outPtr = nullptr;

    cudaExternalMemoryHandleDesc extMemDesc = {};
    extMemDesc.size = memorySize;

#if defined(_WIN32)
    VkMemoryGetWin32HandleInfoKHR getHandleInfo = {};
    getHandleInfo.sType = VK_STRUCTURE_TYPE_MEMORY_GET_WIN32_HANDLE_INFO_KHR;
    getHandleInfo.memory = memory;
    getHandleInfo.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;

    auto vkGetMemoryWin32HandleKHR = reinterpret_cast<PFN_vkGetMemoryWin32HandleKHR>(
        vkGetDeviceProcAddr(device, "vkGetMemoryWin32HandleKHR"));
    if (!vkGetMemoryWin32HandleKHR)
    {
        fprintf(stderr, "VulkanByteImageGpu: vkGetMemoryWin32HandleKHR not available for CUDA upload buffer\n");
        return false;
    }
    HANDLE handle = nullptr;
    VkResult vkErr = vkGetMemoryWin32HandleKHR(device, &getHandleInfo, &handle);
    if (vkErr != VK_SUCCESS || !handle)
    {
        fprintf(stderr, "VulkanByteImageGpu: failed to export CUDA upload buffer memory handle (%d)\n", vkErr);
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

    auto vkGetMemoryFdKHR = reinterpret_cast<PFN_vkGetMemoryFdKHR>(vkGetDeviceProcAddr(device, "vkGetMemoryFdKHR"));
    if (!vkGetMemoryFdKHR)
    {
        fprintf(stderr, "VulkanByteImageGpu: vkGetMemoryFdKHR not available for CUDA upload buffer\n");
        return false;
    }
    int fd = -1;
    VkResult vkErr = vkGetMemoryFdKHR(device, &getFdInfo, &fd);
    if (vkErr != VK_SUCCESS || fd < 0)
    {
        fprintf(stderr, "VulkanByteImageGpu: failed to export CUDA upload buffer memory fd (%d)\n", vkErr);
        return false;
    }
    extMemDesc.type = cudaExternalMemoryHandleTypeOpaqueFd;
    extMemDesc.handle.fd = fd;
#endif

    cudaExternalMemory_t externalMemory = nullptr;
    cudaError_t err = cudaImportExternalMemory(&externalMemory, &extMemDesc);
    if (err != cudaSuccess)
    {
        fprintf(stderr, "VulkanByteImageGpu: cudaImportExternalMemory(upload buffer) failed: %s\n",
                cudaGetErrorString(err));
#if !defined(_WIN32)
        if (extMemDesc.handle.fd >= 0)
            close(extMemDesc.handle.fd);
#endif
        return false;
    }

    cudaExternalMemoryBufferDesc bufferDesc = {};
    bufferDesc.offset = 0;
    bufferDesc.size = memorySize;
    void* ptr = nullptr;
    err = cudaExternalMemoryGetMappedBuffer(&ptr, externalMemory, &bufferDesc);
    if (err != cudaSuccess || !ptr)
    {
        fprintf(stderr, "VulkanByteImageGpu: cudaExternalMemoryGetMappedBuffer failed: %s\n",
                cudaGetErrorString(err));
        cudaDestroyExternalMemory(externalMemory);
        return false;
    }

    *outExternalMemory = externalMemory;
    *outPtr = ptr;
    return true;
}

bool ensureCudaUploadBuffer(VulkanBackend* backend,
                            VkTextureState* s,
                            VkDeviceSize requiredSize)
{
    if (!backend || !s || requiredSize == 0)
        return false;
    if (s->cudaUploadBuffer != VK_NULL_HANDLE && s->cudaUploadPtr && s->cudaUploadSize >= requiredSize)
        return true;

    VkDevice device = backend->getDevice();
    VkPhysicalDevice phys = backend->getPhysicalDevice();
    if (device == VK_NULL_HANDLE || phys == VK_NULL_HANDLE)
        return false;

    if (s->cudaUploadPtr)
    {
        cudaFree(s->cudaUploadPtr);
        s->cudaUploadPtr = nullptr;
    }
    if (s->cudaUploadExternalMemory)
    {
        cudaDestroyExternalMemory(s->cudaUploadExternalMemory);
        s->cudaUploadExternalMemory = nullptr;
    }
    if (s->cudaUploadBuffer)
    {
        vkDestroyBuffer(device, s->cudaUploadBuffer, nullptr);
        s->cudaUploadBuffer = VK_NULL_HANDLE;
    }
    if (s->cudaUploadMemory)
    {
        vkFreeMemory(device, s->cudaUploadMemory, nullptr);
        s->cudaUploadMemory = VK_NULL_HANDLE;
    }
    s->cudaUploadSize = 0;

    VkExternalMemoryBufferCreateInfo extBufferInfo = {};
    extBufferInfo.sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_BUFFER_CREATE_INFO;
#if defined(_WIN32)
    extBufferInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;
#else
    extBufferInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;
#endif

    VkBufferCreateInfo bufferInfo = {};
    bufferInfo.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bufferInfo.pNext = &extBufferInfo;
    bufferInfo.size = requiredSize;
    bufferInfo.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
    bufferInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    if (vkCreateBuffer(device, &bufferInfo, nullptr, &s->cudaUploadBuffer) != VK_SUCCESS)
    {
        fprintf(stderr, "VulkanByteImageGpu: vkCreateBuffer(CUDA upload) failed\n");
        return false;
    }

    VkMemoryRequirements req = {};
    vkGetBufferMemoryRequirements(device, s->cudaUploadBuffer, &req);
    VkExportMemoryAllocateInfo exportInfo = {};
    exportInfo.sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO;
#if defined(_WIN32)
    exportInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;
#else
    exportInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;
#endif
    VkMemoryAllocateInfo allocInfo = {};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.pNext = &exportInfo;
    allocInfo.allocationSize = req.size;
    allocInfo.memoryTypeIndex = findMemoryType(phys, req.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    if (allocInfo.memoryTypeIndex == UINT32_MAX ||
        vkAllocateMemory(device, &allocInfo, nullptr, &s->cudaUploadMemory) != VK_SUCCESS)
    {
        fprintf(stderr, "VulkanByteImageGpu: vkAllocateMemory(CUDA upload) failed\n");
        destroyTexture(backend, s);
        return false;
    }
    if (vkBindBufferMemory(device, s->cudaUploadBuffer, s->cudaUploadMemory, 0) != VK_SUCCESS)
    {
        fprintf(stderr, "VulkanByteImageGpu: vkBindBufferMemory(CUDA upload) failed\n");
        destroyTexture(backend, s);
        return false;
    }

    s->cudaUploadSize = req.size;
    if (!importVkBufferMemoryToCuda(device, s->cudaUploadMemory, s->cudaUploadSize,
                                    &s->cudaUploadExternalMemory, &s->cudaUploadPtr))
    {
        destroyTexture(backend, s);
        return false;
    }
    return true;
}
#endif

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
        const bool keepDescriptorSet = s->descriptorSet != VK_NULL_HANDLE;
        destroyTexture(m_backend, s, keepDescriptorSet);

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
        if (vkCreateImage(device, &imageInfo, nullptr, &s->image) != VK_SUCCESS)
            return result;

        VkMemoryRequirements memReq;
        vkGetImageMemoryRequirements(device, s->image, &memReq);
        VkMemoryAllocateInfo allocInfo = {};
        allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        allocInfo.allocationSize = memReq.size;
        allocInfo.memoryTypeIndex = findMemoryType(phys, memReq.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        if (vkAllocateMemory(device, &allocInfo, nullptr, &s->memory) != VK_SUCCESS)
        {
            destroyTexture(m_backend, s); return result;
        }
        vkBindImageMemory(device, s->image, s->memory, 0);
#if OMNIUI_HAS_CUDA
        s->externalMemory = false;
        s->memorySize = 0;
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
    // --- Fast path: source is a CUDA device pointer. Import an exportable
    // Vulkan transfer buffer into CUDA, copy device-to-device into that
    // buffer, then publish into a normal sampled VkImage with a Vulkan
    // buffer-to-image copy. Sampling a CUDA-imported external VkImage hit
    // driver faults in the headless ImGui pass; this keeps the sampled image
    // on the ordinary Vulkan path while keeping pixel data on the GPU.
    if (fromGpu)
    {
        if (isR8)
        {
            static std::atomic<bool> warned{false};
            if (!warned.exchange(true, std::memory_order_relaxed))
                fprintf(stderr, "VulkanByteImageGpu: fromGpu=true with R8 format is not supported (caller must pass RGBA8)\n");
            return result;
        }
        const void* srcDev = static_cast<const void*>(mipMapBuffers[0]);
        const size_t srcPitch = (mipMapStrides && mipMapStrides[0])
            ? mipMapStrides[0]
            : (size_t)width * bytesPerPixel;
        const size_t rowBytes = (size_t)width * bytesPerPixel;
        const VkDeviceSize uploadSize = rowBytes * height;
        if (!ensureCudaUploadBuffer(m_backend, s, uploadSize))
        {
            fprintf(stderr, "VulkanByteImageGpu: CUDA upload buffer unavailable; fromGpu disabled\n");
            return result;
        }

        cudaError_t cuErr = cudaMemcpy2DAsync(
            s->cudaUploadPtr,
            rowBytes,
            srcDev,
            srcPitch,
            rowBytes,
            height,
            cudaMemcpyDeviceToDevice,
            /*stream=*/nullptr);
        if (cuErr != cudaSuccess)
        {
            fprintf(stderr, "VulkanByteImageGpu: cudaMemcpy2DAsync(upload buffer) failed: %s\n",
                    cudaGetErrorString(cuErr));
            return result;
        }
        cuErr = cudaStreamSynchronize(/*stream=*/nullptr);
        if (cuErr != cudaSuccess)
        {
            fprintf(stderr, "VulkanByteImageGpu: cudaStreamSynchronize(upload buffer) failed: %s\n",
                    cudaGetErrorString(cuErr));
            return result;
        }

        VkCommandBuffer cmd = VK_NULL_HANDLE;
        VkCommandBufferAllocateInfo cbAlloc = {};
        cbAlloc.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        cbAlloc.commandPool = cmdPool;
        cbAlloc.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        cbAlloc.commandBufferCount = 1;
        if (vkAllocateCommandBuffers(device, &cbAlloc, &cmd) != VK_SUCCESS)
        {
            fprintf(stderr, "VulkanByteImageGpu: vkAllocateCommandBuffers (fromGpu upload) failed\n");
            return result;
        }
        {
            VkCommandBufferBeginInfo bi = {};
            bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
            bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
            vkBeginCommandBuffer(cmd, &bi);

            VkImageMemoryBarrier toTransfer = {};
            toTransfer.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
            toTransfer.oldLayout = (s->descriptorSet == VK_NULL_HANDLE)
                ? VK_IMAGE_LAYOUT_UNDEFINED
                : VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
            toTransfer.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
            toTransfer.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
            toTransfer.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
            toTransfer.image = s->image;
            toTransfer.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
            toTransfer.subresourceRange.levelCount = 1;
            toTransfer.subresourceRange.layerCount = 1;
            toTransfer.srcAccessMask = (toTransfer.oldLayout == VK_IMAGE_LAYOUT_UNDEFINED)
                ? 0
                : VK_ACCESS_SHADER_READ_BIT;
            toTransfer.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
            vkCmdPipelineBarrier(cmd,
                (toTransfer.oldLayout == VK_IMAGE_LAYOUT_UNDEFINED)
                    ? VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT
                    : VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
                VK_PIPELINE_STAGE_TRANSFER_BIT,
                0, 0, nullptr, 0, nullptr, 1, &toTransfer);

            VkBufferImageCopy region = {};
            region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
            region.imageSubresource.layerCount = 1;
            region.imageExtent = { width, height, 1 };
            vkCmdCopyBufferToImage(cmd, s->cudaUploadBuffer, s->image,
                                   VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &region);

            VkImageMemoryBarrier toRead = toTransfer;
            toRead.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
            toRead.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
            toRead.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
            toRead.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
            vkCmdPipelineBarrier(cmd,
                VK_PIPELINE_STAGE_TRANSFER_BIT,
                VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
                0, 0, nullptr, 0, nullptr, 1, &toRead);

            vkEndCommandBuffer(cmd);
        }

        VkSubmitInfo submit = {};
        submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        submit.commandBufferCount = 1;
        submit.pCommandBuffers = &cmd;
        if (vkQueueSubmit(queue, 1, &submit, VK_NULL_HANDLE) != VK_SUCCESS)
        {
            fprintf(stderr, "VulkanByteImageGpu: vkQueueSubmit (fromGpu upload) failed\n");
            vkQueueWaitIdle(queue);
            vkFreeCommandBuffers(device, cmdPool, 1, &cmd);
            return result;
        }
        vkQueueWaitIdle(queue);
        vkFreeCommandBuffers(device, cmdPool, 1, &cmd);

        if (s->descriptorSet == VK_NULL_HANDLE)
        {
            s->descriptorSet = ImGui_ImplVulkan_AddTexture(
                s->sampler, s->view, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
        }
        else
        {
            updateTextureDescriptor(device, s);
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
    else
    {
        updateTextureDescriptor(device, s);
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
