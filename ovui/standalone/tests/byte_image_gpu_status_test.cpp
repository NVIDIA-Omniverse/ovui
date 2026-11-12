/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// Upload results on the real Vulkan + CUDA backend (issue 230).
//
// Drives ByteImageProvider on a real device through VulkanByteImageGpu, with
// the checked interface registered, and verifies that:
//   - accepted uploads report an id and finish (getCompletedUploadId);
//   - uploads that the backend really refuses (a GPU source with a format that
//     cannot be imported, a bad CUDA pointer, an empty size) are reported as
//     failures, count in getUploadFailureCount(), and leave the previous
//     pixels in the texture byte for byte;
//   - the provider recovers with the next good upload;
//   - injectUploadFailures() fails an upload before the backend is called;
//   - a burst of asynchronous GPU uploads gives consistent ids and completion.
// The pixels are read back from the VkImage after every step.

#include "VulkanBackend.h"
#include "VulkanByteImageGpu.h"

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include <cuda_runtime.h>
#include <vulkan/vulkan.h>

#include <imgui/imgui.h>

#include <chrono>
#include <cstdint>
#include <cstdio>
#include <future>
#include <thread>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <vector>

using omni::ui::ByteImageProvider;
using omni::ui::ByteImageUploadResult;
using omni::ui::PixelFormat;
using omni::ui::PlatformRegistry;
using omni::ui::UInt2;
using omni::ui::UploadStatus;
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

namespace
{
int g_failures = 0;
void check(bool ok, const char* what)
{
    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    fprintf(stdout, "  %s %s\n", ok ? "ok  " : "FAIL", what);
    if (!ok)
        ++g_failures;
}

void fillSolid(std::vector<uint8_t>& dst, uint8_t r, uint8_t g, uint8_t b)
{
    dst.assign((size_t)W * H * 4, 0);
    for (size_t i = 0; i < dst.size(); i += 4)
    {
        dst[i] = r; dst[i + 1] = g; dst[i + 2] = b; dst[i + 3] = 0xFF;
    }
}

// Polls the completed upload id until it reaches `id`, with a time limit.
bool completesWithin10s(ByteImageProvider& p, uint64_t id)
{
    const auto start = std::chrono::steady_clock::now();
    while (p.getCompletedUploadId() < id)
    {
        if (std::chrono::steady_clock::now() - start > std::chrono::seconds(10))
            return false;
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
    return p.getCompletedUploadId() == id;
}

bool sameAsTexture(VulkanBackend& vk, const CapturingVulkanByteImageGpu& gpu, const std::vector<uint8_t>& expected)
{
    VkImage img = gpu.getVkImageForState(gpu.lastHandle());
    std::vector<uint8_t> got;
    return img != VK_NULL_HANDLE && readbackVkImageRGBA8(vk, img, W, H, got) && got == expected;
}

void* uploadToDevice(const std::vector<uint8_t>& host)
{
    void* d = nullptr;
    if (cudaMalloc(&d, host.size()) != cudaSuccess)
        return nullptr;
    cudaMemcpy(d, host.data(), host.size(), cudaMemcpyHostToDevice);
    return d;
}
} // namespace

int main()
{
    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    fprintf(stdout, "=== ByteImageProvider upload results on Vulkan + CUDA ===\n");
    VulkanBackend vk;
    if (!vk.initHeadless(W, H))
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "FATAL: VulkanBackend::initHeadless failed\n");
        return 1;
    }
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGui::GetIO().DisplaySize = ImVec2((float)W, (float)H);
    if (!vk.initImGui())
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "FATAL: VulkanBackend::initImGui failed\n");
        return 1;
    }
    auto gpu = std::make_shared<CapturingVulkanByteImageGpu>(&vk);
    PlatformRegistry::instance().setByteImageGpu(gpu);
    PlatformRegistry::instance().setByteImageGpuChecked(gpu);

    std::vector<uint8_t> red, green, blue;
    fillSolid(red, 0xF0, 0x10, 0x10);
    fillSolid(green, 0x10, 0xF0, 0x10);
    fillSolid(blue, 0x10, 0x10, 0xF0);
    void* dGreen = uploadToDevice(green);
    void* dBlue = uploadToDevice(blue);
    const UInt2 size{ (uint32_t)W, (uint32_t)H };
    const size_t stride = (size_t)W * 4;
    {
        ByteImageProvider p;

        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stdout, "[1] CPU uploads\n");
        ByteImageUploadResult r1 = p.uploadBytesData(red.data(), size, stride, PixelFormat::eRGBA8_UNORM);
        check(r1.accepted() && r1.uploadId > 0, "first CPU upload accepted with an id");
        // The CPU copy is submitted and not waited for, so it is only enqueued.
        // Its id completes when the copy's fence has signalled.
        check(r1.status == UploadStatus::eEnqueued, "CPU upload is enqueued on return, not complete");
        check(completesWithin10s(p, r1.uploadId), "completed id reaches the upload id within 10 seconds");
        check(sameAsTexture(vk, *gpu, red), "texture holds the red pixels");

        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stdout, "[2] GPU upload from CUDA memory\n");
        ByteImageUploadResult r2 = p.uploadBytesDataFromGPU(
            static_cast<const uint8_t*>(dGreen), size, stride, PixelFormat::eRGBA8_UNORM);
        check(r2.accepted() && r2.uploadId > r1.uploadId, "GPU upload accepted, id grows");
        check(p.getCompletedUploadId() == r2.uploadId, "GPU upload completed");
        check(sameAsTexture(vk, *gpu, green), "texture holds the green pixels");

        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stdout, "[3] uploads the backend refuses keep the green pixels\n");
        const uint64_t failuresBefore = p.getUploadFailureCount();
        // A pitch smaller than a row: cudaMemcpy2DAsync fails with cudaErrorInvalidPitchValue.
        ByteImageUploadResult bad = p.uploadBytesDataFromGPU(
            static_cast<const uint8_t*>(dGreen), size, stride / 2, PixelFormat::eRGBA8_UNORM);
        check(!bad.accepted(), "bad pitch (real cudaMemcpy2DAsync error) is a failure");
        cudaGetLastError();
        ByteImageUploadResult r8 = p.uploadBytesDataFromGPU(static_cast<const uint8_t*>(dGreen), size, (size_t)W,
                                                           PixelFormat::eR8_UNORM);
        check(!r8.accepted(), "GPU source with R8 is a failure");
        ByteImageUploadResult rgb = p.uploadBytesDataFromGPU(static_cast<const uint8_t*>(dGreen), size,
                                                            (size_t)W * 12, PixelFormat::eRGB32_FLOAT);
        check(!rgb.accepted(), "GPU source with 3 float channels is a failure");
        ByteImageUploadResult empty = p.uploadBytesData(red.data(), UInt2{ 0, 0 }, stride,
                                                        PixelFormat::eRGBA8_UNORM);
        check(!empty.accepted(), "empty size is a failure");
        check(p.getUploadFailureCount() == failuresBefore + 4, "four failures are counted");
        check(!p.getLastUploadResult().accepted(), "last result is the failure");
        check(p.isReferenceValid(), "reference is still valid (old image kept)");
        check(sameAsTexture(vk, *gpu, green), "texture still holds the green pixels, byte for byte");
        check(p.getImGuiReference() != nullptr, "reference is not null");

        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stdout, "[4] recovery\n");
        ByteImageUploadResult r3 = p.uploadBytesDataFromGPU(
            static_cast<const uint8_t*>(dBlue), size, stride, PixelFormat::eRGBA8_UNORM);
        check(r3.accepted() && r3.uploadId > r2.uploadId, "next good upload is accepted");
        check(sameAsTexture(vk, *gpu, blue), "texture holds the blue pixels");

        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stdout, "[5] failure hook on the real backend\n");
        p.injectUploadFailures(1);
        ByteImageUploadResult inj = p.uploadBytesData(red.data(), size, stride, PixelFormat::eRGBA8_UNORM);
        check(!inj.accepted(), "injected failure is reported");
        check(sameAsTexture(vk, *gpu, blue), "blue pixels stay after the injected failure");
        check(p.uploadBytesData(red.data(), size, stride, PixelFormat::eRGBA8_UNORM).accepted(),
              "upload after the hook is accepted");
        check(sameAsTexture(vk, *gpu, red), "texture holds the red pixels again");

        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stdout, "[6] events\n");
        int enqueued = 0, completed = 0, failed = 0;
        uint64_t lastCompleted = 0;
        p.subscribeUploadEvents([&](const omni::ui::ByteImageUploadEvent& e) {
            using K = omni::ui::ByteImageUploadEvent::Kind;
            enqueued += e.kind == K::eEnqueued;
            failed += e.kind == K::eFailed;
            if (e.kind == K::eCompleted) { ++completed; lastCompleted = e.uploadId; }
        });
        ByteImageUploadResult e1 = p.uploadBytesDataFromGPU(static_cast<const uint8_t*>(dGreen), size, stride,
                                                           PixelFormat::eRGBA8_UNORM);
        p.uploadBytesDataFromGPU(static_cast<const uint8_t*>(dGreen), size, stride / 2,
                                 PixelFormat::eRGBA8_UNORM);
        cudaGetLastError();
        p.prepareDraw(1.f, 1.f);
        check(enqueued == 1 && failed == 1 && completed == 1 && lastCompleted == e1.uploadId,
              "one enqueued, one failed, one completed event for the right id");
    }

    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    fprintf(stdout, "[7] burst of asynchronous GPU uploads\n");
    {
        ByteImageProvider p;
        p.uploadBytesData(red.data(), size, stride, PixelFormat::eRGBA8_UNORM);
        uint64_t lastId = 0;
        int accepted = 0, refused = 0;
        bool idsGrow = true;
        for (int i = 0; i < 64; ++i)
        {
            omni::ui::UploadResult r = gpu->updateImageFromGpuAsyncChecked(
                gpu->lastHandle(), static_cast<const uint8_t*>(i % 2 ? dGreen : dBlue), stride, size,
                PixelFormat::eRGBA8_UNORM);
            if (r.status != UploadStatus::eFailed)
            {
                ++accepted;
                idsGrow = idsGrow && r.uploadId > lastId;
                lastId = r.uploadId;
            }
            else
            {
                ++refused;
            }
        }
        cudaDeviceSynchronize();
        // The Vulkan copies can still run after the CUDA work: wait for their
        // completion, with a time limit.
        uint64_t done = 0;
        const auto waitStart = std::chrono::steady_clock::now();
        const auto waitLimit = std::chrono::seconds(10);
        while (true)
        {
            done = gpu->getCompletedUploadId(gpu->lastHandle());
            if (done == lastId || std::chrono::steady_clock::now() - waitStart > waitLimit)
                break;
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        const auto waitedMs =
            std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - waitStart).count();
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        fprintf(stdout, "  accepted=%d refused=%d lastId=%llu completed=%llu after %lld ms (limit 10 s)\n", accepted,
                refused, (unsigned long long)lastId, (unsigned long long)done, (long long)waitedMs);
        check(accepted > 0, "some asynchronous uploads accepted");
        check(accepted + refused == 64, "every upload got an answer");
        check(idsGrow, "accepted ids grow");
        check(done == lastId, "completion reaches the last accepted id within 10 seconds");
    }

    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    fprintf(stdout, "[8] repeated CUDA failures return every time (they hung before)\n");
    {
        ByteImageProvider p;
        p.uploadBytesData(red.data(), size, stride, PixelFormat::eRGBA8_UNORM);
        std::promise<int> done;
        auto finished = done.get_future();
        std::thread worker([&] {
            int refused = 0;
            for (int i = 0; i < 5; ++i)
            {
                // Pitch 1 is smaller than a row: cudaMemcpy2DAsync fails each time.
                omni::ui::UploadResult r = gpu->updateImageFromGpuAsyncChecked(
                    gpu->lastHandle(), static_cast<const uint8_t*>(dGreen), 1, size, PixelFormat::eRGBA8_UNORM);
                refused += r.status == UploadStatus::eFailed;
            }
            // Then a good upload still works: the failures were not terminal.
            omni::ui::UploadResult good = gpu->updateImageFromGpuAsyncChecked(
                gpu->lastHandle(), static_cast<const uint8_t*>(dGreen), stride, size, PixelFormat::eRGBA8_UNORM);
            done.set_value(refused * 10 + (good.status != UploadStatus::eFailed ? 1 : 0));
        });
        const bool returned = finished.wait_for(std::chrono::seconds(10)) == std::future_status::ready;
        check(returned, "five failed uploads and one good upload return within 10 seconds");
        if (!returned)
        {
            // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
            fprintf(stdout, "FAIL (hang)\n");
            fflush(stdout);
            std::_Exit(1);
        }
        worker.join();
        check(finished.get() == 51, "all five failures reported, the next good upload accepted");
        cudaGetLastError();
    }

    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    fprintf(stdout, "[9] device masks\n");
    {
        ByteImageProvider p;
        auto up = [&](uint32_t mask) {
            const uint8_t* b[] = { red.data() };
            size_t st = stride;
            return gpu->updateImageChecked(gpu->lastHandle(), b, &st, 1, size, PixelFormat::eRGBA8_UNORM, false, mask,
                                           0, 0);
        };
        omni::ui::UploadResult m3 = up(3u);
        check(m3.status == UploadStatus::eFailed, "a request for devices 0 and 1 fails: there is one device");
        check(m3.requestedDeviceMask == 3u && m3.uploadedDeviceMask == 0u, "requested 3, uploaded 0");
        omni::ui::UploadResult m1 = up(1u);
        check(m1.status != UploadStatus::eFailed && m1.uploadedDeviceMask == 1u, "device 0 alone is accepted");
        omni::ui::UploadResult m0 = up(0u);
        check(m0.status != UploadStatus::eFailed, "the default device is accepted");
    }

    cudaFree(dGreen);
    cudaFree(dBlue);
    PlatformRegistry::instance().setByteImageGpu(nullptr);
    PlatformRegistry::instance().setByteImageGpuChecked(nullptr);
    vk.shutdown();
    ImGui::DestroyContext();
    // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
    fprintf(stdout, g_failures == 0 ? "PASS\n" : "FAIL (%d)\n", g_failures);
    return g_failures == 0 ? 0 : 1;
}
