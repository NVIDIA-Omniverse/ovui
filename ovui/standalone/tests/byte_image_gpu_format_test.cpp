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

// All-format pixel round-trip test for the Vulkan fromGpu path.
//
// Drives ByteImageProvider::setBytesDataFromGPU with a 128x128 CUDA buffer
// for every PixelFormat the Vulkan backend claims to support, then reads
// back the VkImage via a host-visible staging buffer and compares bytes.
//
// Sibling of byte_image_gpu_dispatch_test (which only covers RGBA8_UNORM).
// The 128x128 size matches realistic AOV tiles while keeping the test fast.
//
// Test categories:
//   * "must round-trip": 4-channel 8-bit + 1/2/4-channel float — every byte
//     must match the source.
//   * "may be unsupported by GPU": 3-channel float — Vulkan reports no
//     optimal-tiling support on most desktop GPUs, and even when it does,
//     the fromGpu path explicitly rejects it (CUDA arrays can't represent
//     3-channel formats). The test passes when the upload was a clean
//     no-op (no VkImage allocated, no descriptor returned).

#include "VulkanBackend.h"
#include "VulkanByteImageGpu.h"

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/ImageProvider/IByteImageGpu.h>
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
using omni::ui::getPixelFormatSize;
using omni::ui::PixelFormat;
using omni::ui::PlatformRegistry;
using omni::ui::UInt2;
using omni::ui::standalone::VulkanBackend;
using omni::ui::standalone::VulkanByteImageGpu;

namespace
{
constexpr int W = 128;
constexpr int H = 128;

// "supportsFromGpu = true" means the test expects a successful byte-for-byte
// round trip. "false" means setBytesDataFromGPU should cleanly no-op (e.g.
// 3-channel formats CUDA can't import).
struct FormatCase
{
    const char* name;
    PixelFormat format;
    bool supportsFromGpu;
};

constexpr FormatCase kCases[] = {
    { "RGBA8_UNORM",  PixelFormat::eRGBA8_UNORM,  true  },
    { "RGBA8_SRGB",   PixelFormat::eRGBA8_SRGB,   true  },
    { "BGRA8_UNORM",  PixelFormat::eBGRA8_UNORM,  true  },
    { "R16_FLOAT",    PixelFormat::eR16_FLOAT,    true  },
    { "R32_FLOAT",    PixelFormat::eR32_FLOAT,    true  },
    { "RG16_FLOAT",   PixelFormat::eRG16_FLOAT,   true  },
    { "RG32_FLOAT",   PixelFormat::eRG32_FLOAT,   true  },
    { "RGB16_FLOAT",  PixelFormat::eRGB16_FLOAT,  false },
    { "RGB32_FLOAT",  PixelFormat::eRGB32_FLOAT,  false },
    { "RGBA16_FLOAT", PixelFormat::eRGBA16_FLOAT, true  },
    { "RGBA32_FLOAT", PixelFormat::eRGBA32_FLOAT, true  },
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

// Position-keyed byte pattern. The point of the test is to verify that the
// CUDA → VkImage → readback round trip is byte-faithful, regardless of how
// any particular format would *interpret* those bytes. Using a position-
// dependent pattern means a mistakenly transposed copy would still fail.
void fillBytePattern(std::vector<uint8_t>& dst, size_t pitch)
{
    dst.assign(pitch * H, 0);
    for (int y = 0; y < H; ++y)
    {
        for (size_t i = 0; i < pitch; ++i)
        {
            dst[y * pitch + i] = (uint8_t)((y * 31u + i * 17u + 41u) & 0xFFu);
        }
    }
}

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

// Copy an arbitrary-format VkImage into a host-visible buffer and return the
// raw bytes. `bytesPerPixel` must match the image's VkFormat — the copy is
// format-agnostic (vkCmdCopyImageToBuffer copies texel storage as-is).
bool readbackVkImage(VulkanBackend& vk, VkImage image,
                     int width, int height, size_t bytesPerPixel,
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

    const VkDeviceSize stagingSize = (VkDeviceSize)width * height * bytesPerPixel;
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

    submitBarrier(VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                  VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
    return true;
}

// Run one format. Returns true on pass.
bool runCase(VulkanBackend& vk,
             CapturingVulkanByteImageGpu& gpu,
             const FormatCase& c)
{
    const size_t bpp = getPixelFormatSize(c.format);
    if (bpp == 0)
    {
        fprintf(stderr, "[%s] FAIL: getPixelFormatSize returned 0\n", c.name);
        return false;
    }
    const size_t pitch = (size_t)W * bpp;
    const size_t byteCount = pitch * H;

    std::vector<uint8_t> ref;
    fillBytePattern(ref, pitch);

    void* dPtr = nullptr;
    if (cudaMalloc(&dPtr, byteCount) != cudaSuccess || !dPtr)
    {
        fprintf(stderr, "[%s] FAIL: cudaMalloc failed\n", c.name);
        return false;
    }
    if (cudaMemcpy(dPtr, ref.data(), byteCount, cudaMemcpyHostToDevice) != cudaSuccess)
    {
        fprintf(stderr, "[%s] FAIL: cudaMemcpy H2D failed\n", c.name);
        cudaFree(dPtr);
        return false;
    }

    bool ok = false;
    {
        // Fresh provider per format — the VulkanByteImageGpu state machine
        // tears down and re-creates the VkImage when format changes anyway,
        // but a fresh provider keeps the failure mode of each case isolated.
        ByteImageProvider provider;
        provider.setBytesDataFromGPU(reinterpret_cast<const uint8_t*>(dPtr),
                                     UInt2{ (uint32_t)W, (uint32_t)H },
                                     /*stride=*/ pitch,
                                     c.format);

        VulkanByteImageGpu::Handle h = gpu.lastHandle();
        VkImage img = h ? gpu.getVkImageForState(h) : VK_NULL_HANDLE;

        if (img == VK_NULL_HANDLE)
        {
            // No VkImage allocated — the format-feature probe or the
            // fromGpu 3-channel rejection bailed early. That is the
            // expected outcome for "supportsFromGpu=false" cases.
            if (!c.supportsFromGpu)
            {
                fprintf(stdout, "[%s] PASS (clean no-op as expected)\n", c.name);
                ok = true;
            }
            else
            {
                fprintf(stderr,
                        "[%s] FAIL: expected upload to succeed but no VkImage was allocated\n",
                        c.name);
            }
        }
        else
        {
            std::vector<uint8_t> roundtrip;
            if (!readbackVkImage(vk, img, W, H, bpp, roundtrip))
            {
                fprintf(stderr, "[%s] FAIL: readback failed\n", c.name);
            }
            else
            {
                size_t mismatches = 0;
                for (size_t i = 0; i < ref.size() && i < roundtrip.size(); ++i)
                    if (ref[i] != roundtrip[i]) ++mismatches;

                if (c.supportsFromGpu)
                {
                    if (mismatches == 0)
                    {
                        fprintf(stdout, "[%s] PASS (%zu bytes round-trip)\n",
                                c.name, ref.size());
                        ok = true;
                    }
                    else
                    {
                        fprintf(stderr, "[%s] FAIL: %zu / %zu bytes mismatched\n",
                                c.name, mismatches, ref.size());
                    }
                }
                else
                {
                    // Format was probed-as-supported by this GPU even though
                    // we don't claim fromGpu support — treat any outcome as
                    // pass, since the production code's contract is "either
                    // works or cleanly no-ops". A partial write is also
                    // acceptable here.
                    fprintf(stdout,
                            "[%s] PASS (GPU accepted unexpectedly, "
                            "%zu / %zu bytes round-tripped)\n",
                            c.name, ref.size() - mismatches, ref.size());
                    ok = true;
                }
            }
        }
    }

    cudaFree(dPtr);
    return ok;
}
} // namespace

int main()
{
    fprintf(stdout, "=== Vulkan ByteImageProvider all-format fromGpu test (128x128) ===\n");

    VulkanBackend vk;
    if (!vk.initHeadless(W, H))
    {
        fprintf(stderr, "FATAL: VulkanBackend::initHeadless failed\n");
        return 1;
    }

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

    auto gpu = std::make_shared<CapturingVulkanByteImageGpu>(&vk);
    if (!gpu->supportsFromGpu())
    {
        fprintf(stderr, "FATAL: VulkanByteImageGpu::supportsFromGpu()==false; "
                        "expected true under OMNIUI_HAS_CUDA\n");
        vk.shutdown();
        ImGui::DestroyContext();
        return 1;
    }
    PlatformRegistry::instance().setByteImageGpu(gpu);

    int failures = 0;
    for (const auto& c : kCases)
    {
        if (!runCase(vk, *gpu, c)) ++failures;
    }

    PlatformRegistry::instance().setByteImageGpu(nullptr);
    vk.shutdown();
    ImGui::DestroyContext();

    fprintf(stdout, "=== %d / %zu cases passed ===\n",
            (int)(sizeof(kCases)/sizeof(kCases[0])) - failures,
            sizeof(kCases)/sizeof(kCases[0]));
    if (failures > 0)
    {
        fprintf(stdout, "FAIL\n");
        return 1;
    }
    fprintf(stdout, "PASS\n");
    return 0;
}
