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

// Dispatch-layer pixel-verifying test for the fromGpu path.
//
// Unlike byte_image_gpu_test (which exercises importVkImageMemoryToCuda and
// cudaMemcpy2DToArray directly), this test drives the full production call
// path and verifies the bytes that land in the texture:
//
//   omni::ui::ByteImageProvider::setBytesDataFromGPU(cuda_dptr, size, …)
//      -> ByteImageProvider::_updateImage(.., fromGpu=true)
//      -> PlatformRegistry::byteImageGpu()->updateImage(.., fromGpu=true)
//      -> VulkanByteImageGpu::updateImage  (the code added for ovui#17)
//          -> external-semaphore-synced layout transitions
//          -> cudaMemcpy2DToArrayAsync into the imported cudaArray
//
// To recover the bytes for comparison, we read back the VkImage that
// VulkanByteImageGpu allocated for the provider via a Vulkan staging-buffer
// copy. The VkImage is recovered through a small test-only hook
// (VulkanByteImageGpu::getVkImageForState) plus a capturing subclass that
// stores the Handle returned by createState() — neither of which is used by
// production code.

#include "VulkanBackend.h"
#include "VulkanByteImageGpu.h"

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <cuda_runtime.h>
#include <vulkan/vulkan.h>

#include <imgui/imgui.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>

using omni::ui::ByteImageProvider;
using omni::ui::PixelFormat;
using omni::ui::PlatformRegistry;
using omni::ui::UInt2;
using omni::ui::standalone::VulkanBackend;
using omni::ui::standalone::VulkanByteImageGpu;

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

void fillReferencePattern(std::vector<uint8_t>& dst)
{
    dst.assign((size_t)W * H * 4, 0);
    for (int y = 0; y < H; ++y)
    {
        for (int x = 0; x < W; ++x)
        {
            const int tile = ((x / 8) + (y / 8)) & 1;
            uint8_t* p = &dst[((size_t)y * W + x) * 4];
            if (tile)
            {
                p[0] = 0xAA; p[1] = 0x33; p[2] = 0x77; p[3] = 0xFF;
            }
            else
            {
                p[0] = 0x11; p[1] = 0xCC; p[2] = 0x55; p[3] = 0xFF;
            }
        }
    }
}

// Subclass that records the most recent Handle createState returns. The
// production VulkanByteImageGpu doesn't expose its handles to callers (they
// live inside ByteImageProvider's private m_gpuState); the test only needs
// "the one ByteImageProvider's handle" so capture-on-create is enough.
class CapturingVulkanByteImageGpu : public VulkanByteImageGpu
{
public:
    using VulkanByteImageGpu::VulkanByteImageGpu;

    Handle createState() override
    {
        Handle h = VulkanByteImageGpu::createState();
        m_lastHandle = h;
        return h;
    }

    Handle lastHandle() const { return m_lastHandle; }

private:
    Handle m_lastHandle = nullptr;
};

bool readbackVkImageRGBA8(VulkanBackend& vk, VkImage image,
                          int width, int height,
                          std::vector<uint8_t>& outPixels)
{
    VkDevice device = vk.getDevice();
    VkPhysicalDevice phys = vk.getPhysicalDevice();
    VkQueue queue = vk.getQueue();
    VkCommandPool cmdPool = vk.getCommandPool();

    auto submitBarrier = [&](VkImageLayout oldLayout, VkImageLayout newLayout)
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
        b.oldLayout = oldLayout;
        b.newLayout = newLayout;
        b.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        b.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        b.image = image;
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

    submitBarrier(VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
                  VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL);

    const VkDeviceSize stagingSize = (VkDeviceSize)width * height * 4;
    VkBufferCreateInfo bufInfo = {};
    bufInfo.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bufInfo.size = stagingSize;
    bufInfo.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    bufInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    VkBuffer staging = VK_NULL_HANDLE;
    if (vkCreateBuffer(device, &bufInfo, nullptr, &staging) != VK_SUCCESS)
        return false;

    VkMemoryRequirements req;
    vkGetBufferMemoryRequirements(device, staging, &req);
    VkMemoryAllocateInfo alloc = {};
    alloc.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc.allocationSize = req.size;
    alloc.memoryTypeIndex = findMemoryType(phys, req.memoryTypeBits,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    VkDeviceMemory stagingMem = VK_NULL_HANDLE;
    if (vkAllocateMemory(device, &alloc, nullptr, &stagingMem) != VK_SUCCESS)
    {
        vkDestroyBuffer(device, staging, nullptr);
        return false;
    }
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
        region.imageExtent = { (uint32_t)width, (uint32_t)height, 1 };
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
    outPixels.resize(stagingSize);
    std::memcpy(outPixels.data(), mapped, stagingSize);
    vkUnmapMemory(device, stagingMem);

    vkDestroyBuffer(device, staging, nullptr);
    vkFreeMemory(device, stagingMem, nullptr);

    // Leave the image back in SHADER_READ_ONLY_OPTIMAL the way the
    // production updateImage left it.
    submitBarrier(VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                  VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
    return true;
}
} // namespace

int main()
{
    fprintf(stdout, "=== ByteImageProvider::setBytesDataFromGPU dispatch test ===\n");

    // Headless Vulkan only — no GLFW, no DISPLAY required.
    VulkanBackend vk;
    if (!vk.initHeadless(W, H))
    {
        fprintf(stderr, "FATAL: VulkanBackend::initHeadless failed\n");
        return 1;
    }

    // VulkanByteImageGpu::updateImage finishes by calling
    // ImGui_ImplVulkan_AddTexture to wire the texture into ImGui's descriptor
    // set; that requires the ImGui Vulkan backend to be initialised.
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGui::GetIO().DisplaySize = ImVec2((float)W, (float)H);
    if (!vk.initImGui())
    {
        fprintf(stderr, "FATAL: VulkanBackend::initImGui failed\n");
        ImGui::DestroyContext();
        vk.shutdown();
        return 1;
    }

    // Register our backend BEFORE constructing the provider — its ctor calls
    // PlatformRegistry::instance().byteImageGpu()->createState().
    auto gpu = std::make_shared<CapturingVulkanByteImageGpu>(&vk);
    if (!gpu->supportsFromGpu())
    {
        fprintf(stderr, "FATAL: VulkanByteImageGpu::supportsFromGpu()==false; "
                        "expected true under OMNIUI_HAS_CUDA\n");
        return 1;
    }
    PlatformRegistry::instance().setByteImageGpu(gpu);

    // Sanity-check the public probe — this is the API consumers actually
    // call to decide whether to attempt the zero-copy path.
    if (!PlatformRegistry::instance().byteImageGpu()
        || !PlatformRegistry::instance().byteImageGpu()->supportsFromGpu())
    {
        fprintf(stderr, "FATAL: PlatformRegistry probe disagrees with backend\n");
        return 1;
    }

    // Allocate CUDA buffer with the reference pattern.
    std::vector<uint8_t> hostRef;
    fillReferencePattern(hostRef);

    void* dPtr = nullptr;
    if (cudaMalloc(&dPtr, hostRef.size()) != cudaSuccess || !dPtr)
    {
        fprintf(stderr, "FATAL: cudaMalloc failed\n");
        return 1;
    }
    cudaMemcpy(dPtr, hostRef.data(), hostRef.size(), cudaMemcpyHostToDevice);

    // Drive the public API. This is the path Codex flagged as untested:
    // ByteImageProvider::setBytesDataFromGPU is what the Python binding
    // (bindings/ImageProvider/BindByteImageProvider.h:168-174) lands on.
    {
        ByteImageProvider provider;
        provider.setBytesDataFromGPU(reinterpret_cast<const uint8_t*>(dPtr),
                                     UInt2{ (uint32_t)W, (uint32_t)H },
                                     /*stride=*/ (size_t)W * 4,
                                     PixelFormat::eRGBA8_UNORM);

        VulkanByteImageGpu::Handle h = gpu->lastHandle();
        if (!h)
        {
            fprintf(stderr, "FATAL: VulkanByteImageGpu never received createState()\n");
            cudaFree(dPtr);
            return 1;
        }

        VkImage img = gpu->getVkImageForState(h);
        if (img == VK_NULL_HANDLE)
        {
            fprintf(stderr, "FATAL: VkImage backing the provider state was not allocated "
                            "— updateImage(fromGpu=true) likely returned early\n");
            cudaFree(dPtr);
            return 1;
        }

        std::vector<uint8_t> roundtrip;
        if (!readbackVkImageRGBA8(vk, img, W, H, roundtrip))
        {
            fprintf(stderr, "FATAL: readbackVkImageRGBA8 failed\n");
            cudaFree(dPtr);
            return 1;
        }

        size_t mismatches = 0;
        for (size_t i = 0; i < hostRef.size(); ++i)
            if (hostRef[i] != roundtrip[i])
                ++mismatches;

        fprintf(stdout, "Mismatches: %zu / %zu bytes\n", mismatches, hostRef.size());

        // provider goes out of scope here — destroyState (and via that
        // destroyTexture / destroyCudaImageImport) runs before VulkanBackend
        // shutdown so we don't leak anything.
        if (mismatches != 0)
        {
            cudaFree(dPtr);
            PlatformRegistry::instance().setByteImageGpu(nullptr);
            vk.shutdown();
            ImGui::DestroyContext();
            fprintf(stdout, "FAIL\n");
            return 1;
        }
    }

    cudaFree(dPtr);
    PlatformRegistry::instance().setByteImageGpu(nullptr);
    vk.shutdown();
    ImGui::DestroyContext();

    fprintf(stdout, "PASS\n");
    return 0;
}
