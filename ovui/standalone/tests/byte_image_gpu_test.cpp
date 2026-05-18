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

// Helper-layer round-trip test for the CUDA-Vulkan external-memory plumbing
// that powers VulkanByteImageGpu's fromGpu path.
//
// What this test exercises (directly, NOT through ByteImageProvider):
//   * importVkImageMemoryToCuda — imports an exportable VkDeviceMemory into
//     CUDA as a cudaMipmappedArray.
//   * cudaMemcpy2DToArray (DeviceToDevice) — the actual zero-copy upload.
//
// What this test does NOT cover (see byte_image_gpu_dispatch_test for that):
//   * VulkanByteImageGpu::updateImage(fromGpu=true) — the production caller.
//   * ByteImageProvider::setBytesDataFromGPU — the public API.
//   * The external-semaphore sync chain — bypassed here in favour of
//     vkQueueWaitIdle + cudaDeviceSynchronize.
//
// Strategy: allocate a small VkImage with VK_KHR_external_memory_fd just like
// VulkanByteImageGpu does, import its VkDeviceMemory into CUDA via the
// importVkImageMemoryToCuda helper, write a known checkerboard from a CUDA
// device pointer into the mapped cudaArray, then use a Vulkan staging-buffer
// readback to recover the host-side bytes and compare them. Failure prints
// the mismatch count and exits non-zero.

#include "CudaVulkanInterop.h"
#include "VulkanBackend.h"

#include <cuda_runtime.h>
#include <vulkan/vulkan.h>

#if !defined(_WIN32)
#  define VK_USE_PLATFORM_XCB_KHR
#endif


#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

using namespace omni::ui::standalone;

namespace
{
constexpr int W = 64;
constexpr int H = 64;

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

// Build the host-side reference pattern: a 4x4 checkerboard scaled to (W,H).
void fillReferencePattern(std::vector<uint8_t>& dst)
{
    dst.assign((size_t)W * H * 4, 0);
    for (int y = 0; y < H; ++y)
    {
        for (int x = 0; x < W; ++x)
        {
            const int tile = ((x / 16) + (y / 16)) & 1;
            uint8_t* p = &dst[((size_t)y * W + x) * 4];
            if (tile)
            {
                p[0] = 0xFF; p[1] = 0x00; p[2] = 0x00; p[3] = 0xFF; // red
            }
            else
            {
                p[0] = 0x00; p[1] = 0xFF; p[2] = 0x00; p[3] = 0xFF; // green
            }
        }
    }
}
} // namespace

int main()
{
    fprintf(stdout, "=== VulkanByteImageGpu fromGpu round-trip test ===\n");

    // Headless Vulkan only — no GLFW, no DISPLAY required. The body of this
    // test (CUDA import + memcpy + readback + memcmp) doesn't need a window.
    VulkanBackend vk;
    if (!vk.initHeadless(W, H))
    {
        fprintf(stderr, "FATAL: VulkanBackend::initHeadless failed (no Vulkan ICD?)\n");
        return 1;
    }

    VkDevice device = vk.getDevice();
    VkPhysicalDevice phys = vk.getPhysicalDevice();
    VkQueue queue = vk.getQueue();
    VkCommandPool cmdPool = vk.getCommandPool();

    // --- 1. Create an exportable VkImage (matches VulkanByteImageGpu's create chain).
    VkExternalMemoryImageCreateInfo extImage = {};
    extImage.sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO;
#if defined(_WIN32)
    extImage.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;
#else
    extImage.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;
#endif

    VkImageCreateInfo imageInfo = {};
    imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageInfo.pNext = &extImage;
    imageInfo.imageType = VK_IMAGE_TYPE_2D;
    imageInfo.format = VK_FORMAT_R8G8B8A8_UNORM;
    imageInfo.extent = { (uint32_t)W, (uint32_t)H, 1 };
    imageInfo.mipLevels = 1;
    imageInfo.arrayLayers = 1;
    imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
    imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageInfo.usage = VK_IMAGE_USAGE_SAMPLED_BIT
                    | VK_IMAGE_USAGE_TRANSFER_DST_BIT
                    | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    imageInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

    VkImage image = VK_NULL_HANDLE;
    if (vkCreateImage(device, &imageInfo, nullptr, &image) != VK_SUCCESS)
    {
        fprintf(stderr, "FATAL: vkCreateImage failed\n");
        return 1;
    }

    VkMemoryRequirements memReq;
    vkGetImageMemoryRequirements(device, image, &memReq);

    VkExportMemoryAllocateInfo exportInfo = {};
    exportInfo.sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO;
    exportInfo.handleTypes = extImage.handleTypes;

    VkMemoryAllocateInfo memAlloc = {};
    memAlloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    memAlloc.pNext = &exportInfo;
    memAlloc.allocationSize = memReq.size;
    memAlloc.memoryTypeIndex = findMemoryType(phys, memReq.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);

    VkDeviceMemory memory = VK_NULL_HANDLE;
    if (vkAllocateMemory(device, &memAlloc, nullptr, &memory) != VK_SUCCESS)
    {
        fprintf(stderr, "FATAL: vkAllocateMemory (exportable) failed\n");
        return 1;
    }
    vkBindImageMemory(device, image, memory, 0);

    // --- 2. Import that memory into CUDA via the new helper.
    CudaImageImport imp{};
    if (!importVkImageMemoryToCuda(device, phys, memory, memReq.size, W, H, &imp))
    {
        fprintf(stderr, "FATAL: importVkImageMemoryToCuda failed\n");
        return 1;
    }

    // --- 3. Build a known checkerboard, upload to a CUDA dev buffer.
    std::vector<uint8_t> hostRef;
    fillReferencePattern(hostRef);

    void* dPtr = nullptr;
    cudaError_t cuErr = cudaMalloc(&dPtr, hostRef.size());
    if (cuErr != cudaSuccess)
    {
        fprintf(stderr, "FATAL: cudaMalloc: %s\n", cudaGetErrorString(cuErr));
        return 1;
    }
    cudaMemcpy(dPtr, hostRef.data(), hostRef.size(), cudaMemcpyHostToDevice);

    // --- 4. Transition the VkImage to GENERAL so a CUDA write into the same
    // memory is well-defined on the Vulkan side.
    auto submitBarrier = [&](VkImageLayout oldLayout, VkImageLayout newLayout, VkImage img)
    {
        VkCommandBuffer cmd;
        VkCommandBufferAllocateInfo a = {};
        a.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        a.commandPool = cmdPool;
        a.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        a.commandBufferCount = 1;
        vkAllocateCommandBuffers(device, &a, &cmd);
        VkCommandBufferBeginInfo bi = {};
        bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
        bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
        vkBeginCommandBuffer(cmd, &bi);
        VkImageMemoryBarrier b = {};
        b.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
        b.oldLayout = oldLayout; b.newLayout = newLayout;
        b.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        b.image = img;
        b.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        b.subresourceRange.levelCount = 1;
        b.subresourceRange.layerCount = 1;
        b.srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT | VK_ACCESS_MEMORY_READ_BIT;
        b.dstAccessMask = VK_ACCESS_MEMORY_WRITE_BIT | VK_ACCESS_MEMORY_READ_BIT;
        vkCmdPipelineBarrier(cmd,
            VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
            0, 0, nullptr, 0, nullptr, 1, &b);
        vkEndCommandBuffer(cmd);
        VkSubmitInfo si = {};
        si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        si.commandBufferCount = 1;
        si.pCommandBuffers = &cmd;
        vkQueueSubmit(queue, 1, &si, VK_NULL_HANDLE);
        vkQueueWaitIdle(queue);
        vkFreeCommandBuffers(device, cmdPool, 1, &cmd);
    };
    submitBarrier(VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_GENERAL, image);

    // --- 5. CUDA → mapped array (this is the operation VulkanByteImageGpu::updateImage
    // performs on the fromGpu=true branch).
    cuErr = cudaMemcpy2DToArray(imp.array, 0, 0, dPtr, (size_t)W * 4,
                                (size_t)W * 4, H, cudaMemcpyDeviceToDevice);
    if (cuErr != cudaSuccess)
    {
        fprintf(stderr, "FATAL: cudaMemcpy2DToArray: %s\n", cudaGetErrorString(cuErr));
        return 1;
    }
    cudaDeviceSynchronize();

    // --- 6. Use Vulkan to copy the VkImage to a host-visible staging buffer.
    submitBarrier(VK_IMAGE_LAYOUT_GENERAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, image);

    const VkDeviceSize stagingSize = (VkDeviceSize)W * H * 4;
    VkBufferCreateInfo bufInfo = {};
    bufInfo.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bufInfo.size = stagingSize;
    bufInfo.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    bufInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    VkBuffer staging = VK_NULL_HANDLE;
    vkCreateBuffer(device, &bufInfo, nullptr, &staging);
    VkMemoryRequirements bufReq;
    vkGetBufferMemoryRequirements(device, staging, &bufReq);
    VkMemoryAllocateInfo bufAlloc = {};
    bufAlloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    bufAlloc.allocationSize = bufReq.size;
    bufAlloc.memoryTypeIndex = findMemoryType(phys, bufReq.memoryTypeBits,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    VkDeviceMemory stagingMem = VK_NULL_HANDLE;
    vkAllocateMemory(device, &bufAlloc, nullptr, &stagingMem);
    vkBindBufferMemory(device, staging, stagingMem, 0);

    {
        VkCommandBuffer cmd;
        VkCommandBufferAllocateInfo a = {};
        a.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        a.commandPool = cmdPool;
        a.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        a.commandBufferCount = 1;
        vkAllocateCommandBuffers(device, &a, &cmd);
        VkCommandBufferBeginInfo bi = {};
        bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
        bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
        vkBeginCommandBuffer(cmd, &bi);
        VkBufferImageCopy region = {};
        region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.imageSubresource.layerCount = 1;
        region.imageExtent = { (uint32_t)W, (uint32_t)H, 1 };
        vkCmdCopyImageToBuffer(cmd, image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                               staging, 1, &region);
        vkEndCommandBuffer(cmd);
        VkSubmitInfo si = {};
        si.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        si.commandBufferCount = 1;
        si.pCommandBuffers = &cmd;
        vkQueueSubmit(queue, 1, &si, VK_NULL_HANDLE);
        vkQueueWaitIdle(queue);
        vkFreeCommandBuffers(device, cmdPool, 1, &cmd);
    }

    void* mapped = nullptr;
    vkMapMemory(device, stagingMem, 0, stagingSize, 0, &mapped);
    std::vector<uint8_t> roundtrip(stagingSize);
    std::memcpy(roundtrip.data(), mapped, stagingSize);
    vkUnmapMemory(device, stagingMem);

    // --- 7. Compare host reference to round-trip.
    size_t mismatches = 0;
    for (size_t i = 0; i < hostRef.size(); ++i)
    {
        if (hostRef[i] != roundtrip[i])
            ++mismatches;
    }
    fprintf(stdout, "Mismatches: %zu / %zu bytes\n", mismatches, hostRef.size());
    bool pass = (mismatches == 0);

    // --- Cleanup
    vkDestroyBuffer(device, staging, nullptr);
    vkFreeMemory(device, stagingMem, nullptr);
    cudaFree(dPtr);
    destroyCudaImageImport(&imp);
    vkDestroyImage(device, image, nullptr);
    vkFreeMemory(device, memory, nullptr);
    vk.shutdown();

    fprintf(stdout, "%s\n", pass ? "PASS" : "FAIL");
    return pass ? 0 : 1;
}
