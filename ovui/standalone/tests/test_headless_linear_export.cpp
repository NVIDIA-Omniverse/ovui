/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

// test_headless_linear_export.cpp — issue-34 Step 0.7
//
// Validates the cudaArray_t → pitched-linear-CUDA-buffer copy that the
// headless tier-2 path will use (issue-34 Step 2.1's
// `copyHeadlessFrameToLinear` public API).
//
//   1. vk.initHeadless(w, h)        — offscreen Vulkan image, no GLFW, no X11.
//   2. Build an 8×8 checker pattern on the host.
//   3. Upload it into the offscreen VkImage via vkCmdCopyBufferToImage.
//   4. interop.init(vk) + syncVulkanToCuda() — Vulkan→CUDA fence.
//   5. cudaMallocPitch + cudaMemcpy2DFromArray(getArray() → pitched linear).
//   6. cudaMemcpy2D D2H from the pitched buffer.
//   7. Assert the host result matches the original checker byte-for-byte.
//
// Covered API: copyHeadlessFrameToLinear.

#include "VulkanBackend.h"
#include "CudaVulkanInterop.h"
#include "HeadlessVulkanPlatform.h"
#include "StandaloneInit.h"

#include <omni/ui/platform/PlatformRegistry.h>

#include <cuda_runtime.h>
#include <vulkan/vulkan.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

using namespace omni::ui::standalone;

static const int WIDTH  = 256;
static const int HEIGHT = 256;

// Generate a deterministic 8×8 checker pattern of WIDTH×HEIGHT RGBA8 pixels.
static std::vector<uint8_t> makeChecker()
{
    std::vector<uint8_t> img(WIDTH * HEIGHT * 4, 0);
    const int cellW = WIDTH  / 8;
    const int cellH = HEIGHT / 8;
    for (int y = 0; y < HEIGHT; ++y)
    {
        for (int x = 0; x < WIDTH; ++x)
        {
            int i = x / cellW;
            int j = y / cellH;
            uint8_t* p = &img[(y * WIDTH + x) * 4];
            p[0] = (uint8_t)(i * 32);
            p[1] = (uint8_t)(j * 32);
            p[2] = 128;
            p[3] = 255;
        }
    }
    return img;
}

// Find a memory type matching the requested type bits and property flags.
static uint32_t findMemoryType(VkPhysicalDevice phys, uint32_t typeBits, VkMemoryPropertyFlags props)
{
    VkPhysicalDeviceMemoryProperties mem{};
    vkGetPhysicalDeviceMemoryProperties(phys, &mem);
    for (uint32_t i = 0; i < mem.memoryTypeCount; ++i)
    {
        if ((typeBits & (1u << i)) &&
            (mem.memoryTypes[i].propertyFlags & props) == props)
            return i;
    }
    fprintf(stderr, "FATAL: no matching memory type\n");
    std::exit(1);
}

// Upload `src` (size WIDTH*HEIGHT*4) into the offscreen color image of `vk`.
//
// vk.initHeadless leaves the image in TRANSFER_SRC_OPTIMAL after each
// render pass; for the very first frame the image's layout is UNDEFINED.
// We transition UNDEFINED→TRANSFER_DST_OPTIMAL, copy from a host-visible
// staging buffer, then transition back to TRANSFER_SRC_OPTIMAL so
// CudaVulkanInterop's array sees the same layout it would in steady state.
static bool uploadToOffscreen(VulkanBackend& vk, const uint8_t* src)
{
    VkDevice         device = vk.getDevice();
    VkPhysicalDevice phys   = vk.getPhysicalDevice();
    VkQueue          queue  = vk.getQueue();
    VkCommandPool    pool   = vk.getCommandPool();
    VkImage          image  = vk.getColorImage();

    const VkDeviceSize bytes = (VkDeviceSize)WIDTH * HEIGHT * 4;

    // Staging buffer (HOST_VISIBLE | HOST_COHERENT)
    VkBufferCreateInfo bci{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};
    bci.size  = bytes;
    bci.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
    bci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    VkBuffer staging = VK_NULL_HANDLE;
    if (vkCreateBuffer(device, &bci, nullptr, &staging) != VK_SUCCESS)
        return false;

    VkMemoryRequirements mreq{};
    vkGetBufferMemoryRequirements(device, staging, &mreq);

    VkMemoryAllocateInfo mai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};
    mai.allocationSize  = mreq.size;
    mai.memoryTypeIndex = findMemoryType(phys, mreq.memoryTypeBits,
                                         VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                                         VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    VkDeviceMemory stagingMem = VK_NULL_HANDLE;
    if (vkAllocateMemory(device, &mai, nullptr, &stagingMem) != VK_SUCCESS)
    {
        vkDestroyBuffer(device, staging, nullptr);
        return false;
    }
    vkBindBufferMemory(device, staging, stagingMem, 0);

    void* mapped = nullptr;
    vkMapMemory(device, stagingMem, 0, bytes, 0, &mapped);
    std::memcpy(mapped, src, bytes);
    vkUnmapMemory(device, stagingMem);

    // One-shot command buffer: layout transition + copy + layout transition back.
    VkCommandBufferAllocateInfo cai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};
    cai.commandPool        = pool;
    cai.level              = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    cai.commandBufferCount = 1;
    VkCommandBuffer cmd = VK_NULL_HANDLE;
    vkAllocateCommandBuffers(device, &cai, &cmd);

    VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    vkBeginCommandBuffer(cmd, &bi);

    auto barrier = [&](VkImageLayout from, VkImageLayout to,
                       VkAccessFlags srcAccess, VkAccessFlags dstAccess,
                       VkPipelineStageFlags srcStage, VkPipelineStageFlags dstStage)
    {
        VkImageMemoryBarrier mb{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};
        mb.oldLayout                       = from;
        mb.newLayout                       = to;
        mb.srcQueueFamilyIndex             = VK_QUEUE_FAMILY_IGNORED;
        mb.dstQueueFamilyIndex             = VK_QUEUE_FAMILY_IGNORED;
        mb.image                           = image;
        mb.subresourceRange.aspectMask     = VK_IMAGE_ASPECT_COLOR_BIT;
        mb.subresourceRange.levelCount     = 1;
        mb.subresourceRange.layerCount     = 1;
        mb.srcAccessMask                   = srcAccess;
        mb.dstAccessMask                   = dstAccess;
        vkCmdPipelineBarrier(cmd, srcStage, dstStage, 0, 0, nullptr, 0, nullptr, 1, &mb);
    };

    // UNDEFINED → TRANSFER_DST_OPTIMAL
    barrier(VK_IMAGE_LAYOUT_UNDEFINED,            VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
            0,                                    VK_ACCESS_TRANSFER_WRITE_BIT,
            VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,    VK_PIPELINE_STAGE_TRANSFER_BIT);

    VkBufferImageCopy region{};
    region.bufferOffset                    = 0;
    region.bufferRowLength                 = 0; // tightly packed
    region.bufferImageHeight               = 0;
    region.imageSubresource.aspectMask     = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.layerCount     = 1;
    region.imageExtent                     = { (uint32_t)WIDTH, (uint32_t)HEIGHT, 1 };
    vkCmdCopyBufferToImage(cmd, staging, image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                           1, &region);

    // TRANSFER_DST_OPTIMAL → TRANSFER_SRC_OPTIMAL (matches steady-state layout
    // after a normal render pass; this is what CudaVulkanInterop's array sees).
    barrier(VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            VK_ACCESS_TRANSFER_WRITE_BIT,         VK_ACCESS_TRANSFER_READ_BIT,
            VK_PIPELINE_STAGE_TRANSFER_BIT,       VK_PIPELINE_STAGE_TRANSFER_BIT);

    vkEndCommandBuffer(cmd);

    VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};
    si.commandBufferCount = 1;
    si.pCommandBuffers    = &cmd;
    vkQueueSubmit(queue, 1, &si, VK_NULL_HANDLE);
    vkQueueWaitIdle(queue);

    vkFreeCommandBuffers(device, pool, 1, &cmd);
    vkDestroyBuffer(device, staging, nullptr);
    vkFreeMemory(device, stagingMem, nullptr);
    return true;
}

// ---------------------------------------------------------------------------
// Phase 1 (Step 0.7) — raw VulkanBackend + CudaVulkanInterop. Proves the
// underlying primitives produce a byte-for-byte match against the host
// reference checker.
// ---------------------------------------------------------------------------
static int runPhase1()
{
    fprintf(stdout, "=== Phase 1: raw VulkanBackend + CudaVulkanInterop ===\n");

    // 1. Headless Vulkan — no GLFW, no X11.
    VulkanBackend vk;
    if (!vk.initHeadless(WIDTH, HEIGHT))
    {
        fprintf(stderr, "FATAL: VulkanBackend::initHeadless failed\n");
        return 1;
    }

    // 2 & 3. Build the reference pattern and upload it into the offscreen image.
    std::vector<uint8_t> ref = makeChecker();
    if (!uploadToOffscreen(vk, ref.data()))
    {
        fprintf(stderr, "FATAL: uploadToOffscreen failed\n");
        vk.shutdown();
        return 1;
    }

    // 4. Import the VkImage memory into CUDA + Vulkan→CUDA fence.
    CudaVulkanInterop interop;
    if (!interop.init(vk))
    {
        fprintf(stderr, "FATAL: CudaVulkanInterop::init failed\n");
        vk.shutdown();
        return 1;
    }
    if (!interop.syncVulkanToCuda())
    {
        fprintf(stderr, "FATAL: syncVulkanToCuda failed\n");
        interop.shutdown();
        vk.shutdown();
        return 1;
    }

    // 5. Allocate the caller-owned pitched linear destination — exactly the
    //    shape ovstream's VideoFrame.buffer expects.
    void*  dst   = nullptr;
    size_t pitch = 0;
    cudaError_t cerr = cudaMallocPitch(&dst, &pitch, (size_t)WIDTH * 4, (size_t)HEIGHT);
    if (cerr != cudaSuccess)
    {
        fprintf(stderr, "FATAL: cudaMallocPitch failed: %s\n", cudaGetErrorString(cerr));
        interop.shutdown();
        vk.shutdown();
        return 1;
    }
    fprintf(stdout, "cudaMallocPitch: dev=%p pitch=%zu bytes (request %d)\n",
            dst, pitch, WIDTH * 4);

    // 6. cudaArray_t → pitched linear (the call this step is designed around).
    cerr = cudaMemcpy2DFromArray(
        dst, pitch,
        interop.getArray(),
        /*wOffset=*/ 0, /*hOffset=*/ 0,
        (size_t)WIDTH * 4, (size_t)HEIGHT,
        cudaMemcpyDeviceToDevice);
    if (cerr != cudaSuccess)
    {
        fprintf(stderr, "FATAL: cudaMemcpy2DFromArray failed: %s\n",
                cudaGetErrorString(cerr));
        cudaFree(dst);
        interop.shutdown();
        vk.shutdown();
        return 1;
    }

    // 7. D2H from the pitched buffer for verification.
    std::vector<uint8_t> got(WIDTH * HEIGHT * 4, 0);
    cerr = cudaMemcpy2D(
        got.data(), (size_t)WIDTH * 4,
        dst, pitch,
        (size_t)WIDTH * 4, (size_t)HEIGHT,
        cudaMemcpyDeviceToHost);
    if (cerr != cudaSuccess)
    {
        fprintf(stderr, "FATAL: cudaMemcpy2D D2H failed: %s\n",
                cudaGetErrorString(cerr));
        cudaFree(dst);
        interop.shutdown();
        vk.shutdown();
        return 1;
    }

    // Signal back so the next Vulkan frame would be allowed to start.
    interop.syncCudaToVulkan();
    vkDeviceWaitIdle(vk.getDevice());

    // 8. Byte-for-byte comparison against the reference checker.
    size_t total      = (size_t)WIDTH * HEIGHT * 4;
    size_t mismatches = 0;
    int    firstBadX = -1, firstBadY = -1;
    for (size_t i = 0; i < total; ++i)
    {
        if (got[i] != ref[i])
        {
            if (firstBadX < 0)
            {
                firstBadX = (int)((i / 4) % WIDTH);
                firstBadY = (int)((i / 4) / WIDTH);
            }
            ++mismatches;
        }
    }

    bool pass = (mismatches == 0);
    if (pass)
    {
        fprintf(stdout, "PASS: linear-buffer export byte-for-byte match "
                "(%zu bytes, pitch=%zu)\n", total, pitch);
    }
    else
    {
        fprintf(stderr, "FAIL: %zu / %zu byte mismatches; first at "
                "(%d, %d) ref=%02x got=%02x\n",
                mismatches, total, firstBadX, firstBadY,
                ref[((size_t)firstBadY * WIDTH + firstBadX) * 4],
                got[((size_t)firstBadY * WIDTH + firstBadX) * 4]);
    }

    cudaFree(dst);
    interop.shutdown();
    vk.shutdown();

    return pass ? 0 : 1;
}

// ---------------------------------------------------------------------------
// Phase 2 (Step 2.1) — drive the public ovui standalone API:
//   standalone::init() → tick() → upload checker → initHeadlessFrameExport()
//   → waitHeadlessFrameReady() → copyHeadlessFrameToLinear() → D2H
//   → assert byte-for-byte vs reference checker.
// ---------------------------------------------------------------------------
static int runPhase2()
{
    fprintf(stdout, "\n=== Phase 2: public standalone API "
                    "(initHeadlessFrameExport + copyHeadlessFrameToLinear) ===\n");

    // The public API requires these env vars to be set before standalone::init.
#if defined(_WIN32)
    _putenv_s("OMNIUI_HEADLESS", "1");
    _putenv_s("OMNIUI_BACKEND", "vulkan");
#else
    setenv("OMNIUI_HEADLESS", "1", 1);
    setenv("OMNIUI_BACKEND", "vulkan", 1);
#endif

    if (!omni::ui::standalone::init("Phase2", WIDTH, HEIGHT))
    {
        fprintf(stderr, "FATAL: standalone::init failed\n");
        return 1;
    }

    // Render one tick — fills the offscreen image with the (empty) ImGui
    // composite. The checker upload below overwrites this content, but
    // exercising tick() proves the full standalone pipeline is alive.
    if (!omni::ui::standalone::tick())
    {
        fprintf(stderr, "FATAL: standalone::tick failed\n");
        omni::ui::standalone::shutdown();
        return 1;
    }

    // Reach into the active platform to grab the VulkanBackend so we can
    // upload our deterministic reference pattern. This is test-only — the
    // production headless tier-2 path consumes whatever ImGui rendered.
    auto* platform = omni::ui::PlatformRegistry::instance().platform();
    auto* hp = dynamic_cast<HeadlessVulkanPlatform*>(platform);
    if (!hp)
    {
        fprintf(stderr, "FATAL: active platform is not HeadlessVulkanPlatform\n");
        omni::ui::standalone::shutdown();
        return 1;
    }
    VulkanBackend* vk = hp->getVulkanBackend();
    if (!vk || !vk->isInitialized())
    {
        fprintf(stderr, "FATAL: HeadlessVulkanPlatform's VulkanBackend not ready\n");
        omni::ui::standalone::shutdown();
        return 1;
    }

    std::vector<uint8_t> ref = makeChecker();
    if (!uploadToOffscreen(*vk, ref.data()))
    {
        fprintf(stderr, "FATAL: uploadToOffscreen failed\n");
        omni::ui::standalone::shutdown();
        return 1;
    }

    if (!omni::ui::standalone::initHeadlessFrameExport())
    {
        fprintf(stderr, "FATAL: initHeadlessFrameExport failed\n");
        omni::ui::standalone::shutdown();
        return 1;
    }

    int extW = 0, extH = 0;
    if (!omni::ui::standalone::getHeadlessFrameExtent(&extW, &extH) ||
        extW != WIDTH || extH != HEIGHT)
    {
        fprintf(stderr, "FATAL: extent mismatch (got %dx%d, expected %dx%d)\n",
                extW, extH, WIDTH, HEIGHT);
        omni::ui::standalone::shutdownHeadlessFrameExport();
        omni::ui::standalone::shutdown();
        return 1;
    }

    const char* fmt = omni::ui::standalone::getHeadlessFrameFormat();
    if (!fmt || std::strcmp(fmt, "rgba8") != 0)
    {
        fprintf(stderr, "FATAL: format mismatch (got '%s', expected 'rgba8')\n",
                fmt ? fmt : "(null)");
        omni::ui::standalone::shutdownHeadlessFrameExport();
        omni::ui::standalone::shutdown();
        return 1;
    }

    void* dst = nullptr;
    size_t pitch = 0;
    cudaError_t cerr = cudaMallocPitch(&dst, &pitch,
                                       (size_t)WIDTH * 4, (size_t)HEIGHT);
    if (cerr != cudaSuccess)
    {
        fprintf(stderr, "FATAL: cudaMallocPitch failed: %s\n",
                cudaGetErrorString(cerr));
        omni::ui::standalone::shutdownHeadlessFrameExport();
        omni::ui::standalone::shutdown();
        return 1;
    }
    fprintf(stdout, "Phase2 cudaMallocPitch: dev=%p pitch=%zu bytes\n", dst, pitch);

    if (!omni::ui::standalone::waitHeadlessFrameReady(10ull * 1000 * 1000 * 1000))
    {
        fprintf(stderr, "FATAL: waitHeadlessFrameReady failed\n");
        cudaFree(dst);
        omni::ui::standalone::shutdownHeadlessFrameExport();
        omni::ui::standalone::shutdown();
        return 1;
    }

    if (!omni::ui::standalone::copyHeadlessFrameToLinear(
            reinterpret_cast<uintptr_t>(dst), pitch, /*stream=*/0))
    {
        fprintf(stderr, "FATAL: copyHeadlessFrameToLinear failed\n");
        cudaFree(dst);
        omni::ui::standalone::shutdownHeadlessFrameExport();
        omni::ui::standalone::shutdown();
        return 1;
    }

    std::vector<uint8_t> got((size_t)WIDTH * HEIGHT * 4, 0);
    cerr = cudaMemcpy2D(
        got.data(), (size_t)WIDTH * 4,
        dst, pitch,
        (size_t)WIDTH * 4, (size_t)HEIGHT,
        cudaMemcpyDeviceToHost);
    if (cerr != cudaSuccess)
    {
        fprintf(stderr, "FATAL: cudaMemcpy2D D2H failed: %s\n",
                cudaGetErrorString(cerr));
        cudaFree(dst);
        omni::ui::standalone::shutdownHeadlessFrameExport();
        omni::ui::standalone::shutdown();
        return 1;
    }

    omni::ui::standalone::signalHeadlessFrameConsumed();

    // Byte-for-byte against the reference checker.
    size_t total      = (size_t)WIDTH * HEIGHT * 4;
    size_t mismatches = 0;
    int    firstBadX = -1, firstBadY = -1;
    for (size_t i = 0; i < total; ++i)
    {
        if (got[i] != ref[i])
        {
            if (firstBadX < 0)
            {
                firstBadX = (int)((i / 4) % WIDTH);
                firstBadY = (int)((i / 4) / WIDTH);
            }
            ++mismatches;
        }
    }

    cudaFree(dst);
    omni::ui::standalone::shutdownHeadlessFrameExport();
    omni::ui::standalone::shutdown();

    if (mismatches == 0)
    {
        fprintf(stdout, "PASS Phase2: public-API export byte-for-byte match "
                        "(%zu bytes, pitch=%zu)\n", total, pitch);
        return 0;
    }
    fprintf(stderr, "FAIL Phase2: %zu / %zu byte mismatches; first at "
                    "(%d, %d) ref=%02x got=%02x\n",
            mismatches, total, firstBadX, firstBadY,
            ref[((size_t)firstBadY * WIDTH + firstBadX) * 4],
            got[((size_t)firstBadY * WIDTH + firstBadX) * 4]);
    return 1;
}

// ---------------------------------------------------------------------------
// Refusal cases for the public API — exercise the guards we documented.
// ---------------------------------------------------------------------------
static int runPhase3Refusals()
{
    fprintf(stdout, "\n=== Phase 3: refusal guards ===\n");

    // The pipeline must refuse when standalone has not been initialised.
    if (omni::ui::standalone::initHeadlessFrameExport())
    {
        fprintf(stderr, "FAIL: initHeadlessFrameExport succeeded with no platform\n");
        omni::ui::standalone::shutdownHeadlessFrameExport();
        return 1;
    }

    // ...and when the env vars are wrong.
#if defined(_WIN32)
    _putenv_s("OMNIUI_HEADLESS", "0");
#else
    setenv("OMNIUI_HEADLESS", "0", 1);
#endif
    if (omni::ui::standalone::initHeadlessFrameExport())
    {
        fprintf(stderr, "FAIL: initHeadlessFrameExport succeeded with OMNIUI_HEADLESS=0\n");
        omni::ui::standalone::shutdownHeadlessFrameExport();
        return 1;
    }

    fprintf(stdout, "PASS Phase3: refusal guards correctly rejected bad inputs\n");
    return 0;
}

int main()
{
    fprintf(stdout, "=== test_headless_linear_export "
                    "(issue-34 Step 0.7 + Step 2.1) ===\n");

    int rc = runPhase1();
    if (rc != 0)
        return rc;

    rc = runPhase3Refusals();
    if (rc != 0)
        return rc;

    rc = runPhase2();
    if (rc != 0)
        return rc;

    fprintf(stdout, "\n=== ALL PHASES PASSED ===\n");
    return 0;
}
