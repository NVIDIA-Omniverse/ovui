/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "VulkanByteImageGpu.h"

#include "NativeTiming.h"
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

#include <algorithm>
#include <atomic>
#include <array>
#include <cstdio>
#include <cstring>
#include <vector>

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
    bool            descriptorNeedsUpdate = true;
    uint32_t        width        = 0;
    uint32_t        height       = 0;
    uint32_t        mipLevels    = 0;
    PixelFormat     format       = PixelFormat::eRGBA8_UNORM;
    bool            imageInitialized = false;
    VkBuffer        cpuUploadBuffer = VK_NULL_HANDLE;
    VkDeviceMemory  cpuUploadMemory = VK_NULL_HANDLE;
    VkDeviceSize    cpuUploadSize = 0;
    void*           cpuUploadMapped = nullptr;
    VkCommandBuffer cpuUploadCommand = VK_NULL_HANDLE;
    VkFence         cpuUploadFence = VK_NULL_HANDLE;
    bool            cpuUploadInFlight = false;  // a submitted copy signals cpuUploadFence
    // CPU copies are numbered. The shared CPU upload state keeps the number of
    // the newest copy that was submitted and of the newest one that is proven
    // finished. A slot keeps the number of the copy that wrote its image, or 0
    // when no CPU copy wrote it.
    uint64_t        cpuUploadSubmitted = 0;
    uint64_t        cpuUploadFinished = 0;
    uint64_t        cpuUploadTicket = 0;
    bool            cpuUploadTerminal = false;
    bool            uploadPending = false;
    uint64_t        uploadSerial = 0;
    VkFence         completionFence = VK_NULL_HANDLE;
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
    VkCommandBuffer  cudaUploadCommand = VK_NULL_HANDLE;
    VkFence          cudaUploadFence = VK_NULL_HANDLE;
    CudaInteropSemaphores cudaUploadSync = {};
    bool             cudaUploadTerminal = false;
#endif
};

constexpr uint32_t kPresentationSlotCount = 3;
constexpr uint32_t kInvalidPresentationSlot = UINT32_MAX;

struct VkTripleTextureState
{
    std::array<VkTextureState, kPresentationSlotCount> slots = {};
    uint32_t frontSlot = kInvalidPresentationSlot;
    // The slot that was front before the current one. Draw data recorded
    // before the last publication may still sample it.
    uint32_t retiredSlot = kInvalidPresentationSlot;
    uint64_t nextUploadSerial = 1;
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

void pollCompletedUploads(VkDevice device, VkTripleTextureState* state)
{
    if (!state || device == VK_NULL_HANDLE)
        return;
    uint32_t newestSlot = state->frontSlot;
    uint64_t newestSerial = 0;
    if (newestSlot != kInvalidPresentationSlot)
    {
        newestSerial = state->slots[newestSlot].uploadSerial;
    }
    for (uint32_t i = 0; i < kPresentationSlotCount; ++i)
    {
        VkTextureState& slot = state->slots[i];
        if (slot.uploadPending && slot.completionFence != VK_NULL_HANDLE &&
            vkGetFenceStatus(device, slot.completionFence) == VK_SUCCESS)
        {
            slot.uploadPending = false;
            slot.completionFence = VK_NULL_HANDLE;
        }
        if (!slot.uploadPending && slot.descriptorSet != VK_NULL_HANDLE &&
            slot.uploadSerial >= newestSerial)
        {
            newestSerial = slot.uploadSerial;
            newestSlot = i;
        }
    }
    state->frontSlot = newestSlot;
}

uint32_t acquireUploadSlot(VkDevice device, VkTripleTextureState* state)
{
    pollCompletedUploads(device, state);
    for (uint32_t i = 0; i < kPresentationSlotCount; ++i)
    {
        if (i == state->frontSlot || i == state->retiredSlot)
            continue;
        VkTextureState& slot = state->slots[i];
        if (!slot.uploadPending)
            return i;
    }
    return kInvalidPresentationSlot;
}

IByteImageGpu::UpdateResult publishSubmittedUpload(
    VkDevice device,
    VkTripleTextureState* state,
    uint32_t uploadSlot,
    bool uploadPending,
    VkFence completionFence)
{
    IByteImageGpu::UpdateResult result;
    if (state == nullptr || uploadSlot >= kPresentationSlotCount)
    {
        return result;
    }

    VkTextureState& slot = state->slots[uploadSlot];
    slot.uploadPending = uploadPending;
    slot.completionFence = completionFence;
    slot.uploadSerial = state->nextUploadSerial++;

    if (uploadPending && state->frontSlot == kInvalidPresentationSlot)
    {
        if (completionFence == VK_NULL_HANDLE ||
            vkWaitForFences(device, 1, &completionFence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
        {
            return result;
        }
        slot.uploadPending = false;
        slot.completionFence = VK_NULL_HANDLE;
        state->frontSlot = uploadSlot;
    }
    else
    {
        // The caller records the returned descriptor as the image of this
        // upload, so return this slot even while its copy is pending. The
        // copy's barriers on the shared queue make later draws sample the
        // finished image. Returning an older completed slot instead showed
        // stale content: right after native pacing starts, the transparent
        // placeholder of each frame slot, seen as a gray viewport flash.
        // The previous front stays untouched while it may still be sampled.
        state->retiredSlot = state->frontSlot;
        state->frontSlot = uploadSlot;
    }

    if (state->frontSlot != kInvalidPresentationSlot)
    {
        result.imGuiReference = reinterpret_cast<void*>(state->slots[state->frontSlot].descriptorSet);
    }
    return result;
}

// Fills the checked result of an upload that was submitted. A publish that
// returned no texture reference is a failure.
void reportUpload(UploadResult* checked,
                  const IByteImageGpu::UpdateResult& published,
                  const VkTextureState& slot,
                  bool finished)
{
    if (checked == nullptr)
        return;
    if (published.imGuiReference == nullptr)
    {
        checked->cause = "the upload was submitted, but no texture was published";
        return;
    }
    checked->status = finished ? UploadStatus::eComplete : UploadStatus::eEnqueued;
    checked->uploadId = slot.uploadSerial;
    checked->uploadedDeviceMask = checked->requestedDeviceMask;
}

void destroyTexture(VulkanBackend* backend, VkTextureState* s, bool keepDescriptorSet = false, bool deviceIdle = false)
{
    if (!backend || !s) return;
    VkDevice device = backend->getDevice();
    if (device == VK_NULL_HANDLE) return;
#if OMNIUI_HAS_CUDA
    // Resize and teardown are allowed to drain.  Steady-state publication is
    // fully asynchronous, so finish a CUDA copy/signal that may precede its
    // Vulkan wait before destroying either side of the imported objects.
    if (s->cudaUploadPtr)
    {
        cudaStreamSynchronize(/*stream=*/nullptr);
    }
#endif
    // Only an image or a descriptor set can be in use by the GPU.
    if (!deviceIdle && (s->image != VK_NULL_HANDLE || s->descriptorSet != VK_NULL_HANDLE))
    {
        std::lock_guard<std::mutex> presentLock(backend->getPresentQueueMutex());
        OVUI_DEVELOPMENT_TIME_SCOPE(waitScope, "VulkanByteImageGpu.vkDeviceWaitIdle [ovui debug]");
        vkDeviceWaitIdle(device);
    }
    if (s->descriptorSet != VK_NULL_HANDLE && !keepDescriptorSet)
    {
        ImGui_ImplVulkan_RemoveTexture(s->descriptorSet);
        s->descriptorSet = VK_NULL_HANDLE;
    }
    // A slot only borrows the shared upload objects; it owns none (no memory).
    if (!keepDescriptorSet && s->cpuUploadMemory != VK_NULL_HANDLE)
    {
        if (s->cpuUploadMapped)
        {
            vkUnmapMemory(device, s->cpuUploadMemory);
            s->cpuUploadMapped = nullptr;
        }
        if (s->cpuUploadFence)
        {
            vkDestroyFence(device, s->cpuUploadFence, nullptr);
            s->cpuUploadFence = VK_NULL_HANDLE;
        }
        if (s->cpuUploadCommand)
        {
            vkFreeCommandBuffers(device, backend->getCommandPool(), 1, &s->cpuUploadCommand);
            s->cpuUploadCommand = VK_NULL_HANDLE;
        }
        if (s->cpuUploadBuffer)
        {
            vkDestroyBuffer(device, s->cpuUploadBuffer, nullptr);
            s->cpuUploadBuffer = VK_NULL_HANDLE;
        }
        if (s->cpuUploadMemory)
        {
            vkFreeMemory(device, s->cpuUploadMemory, nullptr);
            s->cpuUploadMemory = VK_NULL_HANDLE;
        }
        s->cpuUploadSize = 0;
        s->cpuUploadTerminal = false;
    }
#if OMNIUI_HAS_CUDA
    if (s->cudaUploadFence)
    {
        vkDestroyFence(device, s->cudaUploadFence, nullptr);
        s->cudaUploadFence = VK_NULL_HANDLE;
    }
    if (s->cudaUploadCommand)
    {
        vkFreeCommandBuffers(device, backend->getCommandPool(), 1, &s->cudaUploadCommand);
        s->cudaUploadCommand = VK_NULL_HANDLE;
    }
    destroyCudaInteropSemaphores(device, &s->cudaUploadSync);
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
    s->cudaUploadTerminal = false;
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
    s->imageInitialized = false;
    s->descriptorNeedsUpdate = true;
    s->uploadPending = false;
    s->uploadSerial = 0;
    s->completionFence = VK_NULL_HANDLE;
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
    s->descriptorNeedsUpdate = false;
    return true;
}

bool ensureCpuUploadResources(VulkanBackend* backend, VkTextureState* s, VkDeviceSize requiredSize,
                              VkTextureState* shared = nullptr)
{
    if (shared)
    {
        // Each upload waits for the previous copy under the queue lock, so all
        // slots can use one staging buffer, command buffer and fence. Creating
        // and destroying these for each image took most of a gallery rebuild.
        // A failed upload can leave the shared fence reset with no copy to
        // signal it. After a whole-GPU wait such a fence is unused: replace it.
        VkDevice device = backend->getDevice();
        if (shared->cpuUploadFence != VK_NULL_HANDLE && !shared->cpuUploadInFlight &&
            vkGetFenceStatus(device, shared->cpuUploadFence) != VK_SUCCESS)
        {
            std::lock_guard<std::mutex> presentLock(backend->getPresentQueueMutex());
            OVUI_DEVELOPMENT_TIME_SCOPE(waitScope, "VulkanByteImageGpu.vkDeviceWaitIdle [ovui debug]");
            if (vkDeviceWaitIdle(device) != VK_SUCCESS)
                shared->cpuUploadTerminal = true;
            else if (vkGetFenceStatus(device, shared->cpuUploadFence) != VK_SUCCESS)
            {
                vkDestroyFence(device, shared->cpuUploadFence, nullptr);
                shared->cpuUploadFence = VK_NULL_HANDLE;
            }
        }
        const bool ready = ensureCpuUploadResources(backend, shared, requiredSize);
        s->cpuUploadBuffer = shared->cpuUploadBuffer;
        s->cpuUploadMapped = shared->cpuUploadMapped;
        s->cpuUploadCommand = shared->cpuUploadCommand;
        s->cpuUploadFence = shared->cpuUploadFence;
        return ready;
    }
    if (!backend || !s || requiredSize == 0 || s->cpuUploadTerminal)
        return false;
    VkDevice device = backend->getDevice();
    if (device == VK_NULL_HANDLE)
        return false;

    if (s->cpuUploadCommand == VK_NULL_HANDLE)
    {
        VkCommandBufferAllocateInfo commandInfo{};
        commandInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        commandInfo.commandPool = backend->getCommandPool();
        commandInfo.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        commandInfo.commandBufferCount = 1;
        if (vkAllocateCommandBuffers(device, &commandInfo, &s->cpuUploadCommand) != VK_SUCCESS)
            return false;
    }
    if (s->cpuUploadFence == VK_NULL_HANDLE)
    {
        VkFenceCreateInfo fenceInfo{};
        fenceInfo.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        fenceInfo.flags = VK_FENCE_CREATE_SIGNALED_BIT;
        if (vkCreateFence(device, &fenceInfo, nullptr, &s->cpuUploadFence) != VK_SUCCESS)
            return false;
    }
    if (s->cpuUploadBuffer != VK_NULL_HANDLE && s->cpuUploadMapped && s->cpuUploadSize >= requiredSize)
        return true;

    if (vkWaitForFences(device, 1, &s->cpuUploadFence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
    {
        s->cpuUploadTerminal = true;
        return false;
    }
    if (s->cpuUploadMapped)
    {
        vkUnmapMemory(device, s->cpuUploadMemory);
        s->cpuUploadMapped = nullptr;
    }
    if (s->cpuUploadBuffer)
    {
        vkDestroyBuffer(device, s->cpuUploadBuffer, nullptr);
        s->cpuUploadBuffer = VK_NULL_HANDLE;
    }
    if (s->cpuUploadMemory)
    {
        vkFreeMemory(device, s->cpuUploadMemory, nullptr);
        s->cpuUploadMemory = VK_NULL_HANDLE;
    }
    s->cpuUploadSize = 0;

    VkBufferCreateInfo bufferInfo{};
    bufferInfo.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bufferInfo.size = requiredSize;
    bufferInfo.usage = VK_BUFFER_USAGE_TRANSFER_SRC_BIT;
    bufferInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
    if (vkCreateBuffer(device, &bufferInfo, nullptr, &s->cpuUploadBuffer) != VK_SUCCESS)
        return false;
    VkMemoryRequirements requirements{};
    vkGetBufferMemoryRequirements(device, s->cpuUploadBuffer, &requirements);
    VkMemoryAllocateInfo allocation{};
    allocation.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocation.allocationSize = requirements.size;
    allocation.memoryTypeIndex = findMemoryType(
        backend->getPhysicalDevice(), requirements.memoryTypeBits,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    if (allocation.memoryTypeIndex == UINT32_MAX ||
        vkAllocateMemory(device, &allocation, nullptr, &s->cpuUploadMemory) != VK_SUCCESS ||
        vkBindBufferMemory(device, s->cpuUploadBuffer, s->cpuUploadMemory, 0) != VK_SUCCESS ||
        vkMapMemory(device, s->cpuUploadMemory, 0, requirements.size, 0, &s->cpuUploadMapped) != VK_SUCCESS)
    {
        if (s->cpuUploadBuffer) vkDestroyBuffer(device, s->cpuUploadBuffer, nullptr);
        if (s->cpuUploadMemory) vkFreeMemory(device, s->cpuUploadMemory, nullptr);
        s->cpuUploadBuffer = VK_NULL_HANDLE;
        s->cpuUploadMemory = VK_NULL_HANDLE;
        s->cpuUploadMapped = nullptr;
        return false;
    }
    s->cpuUploadSize = requirements.size;
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

    PFN_vkGetMemoryWin32HandleKHR vkGetMemoryWin32HandleKHR = reinterpret_cast<PFN_vkGetMemoryWin32HandleKHR>(
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
    // Ownership: CUDA takes ownership of a POSIX fd, but NOT of a Win32 NT
    // handle — cudaImportExternalMemory only references it, so this process
    // keeps its own reference and must release it. Closing from a scope guard
    // covers the success path and every failure return below exactly once;
    // without it each upload-buffer creation leaks a handle, and the buffer is
    // recreated on every resize.
    struct Win32ExportedHandle
    {
        HANDLE value;
        ~Win32ExportedHandle()
        {
            if (value)
                CloseHandle(value);
        }
    } exportedHandle{handle};
#else
    VkMemoryGetFdInfoKHR getFdInfo = {};
    getFdInfo.sType = VK_STRUCTURE_TYPE_MEMORY_GET_FD_INFO_KHR;
    getFdInfo.memory = memory;
    getFdInfo.handleType = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;

    PFN_vkGetMemoryFdKHR vkGetMemoryFdKHR =
        reinterpret_cast<PFN_vkGetMemoryFdKHR>(vkGetDeviceProcAddr(device, "vkGetMemoryFdKHR"));
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
        // CUDA consumes the fd only on success, so a failed import must close
        // it here. The Win32 handle is released by its scope guard instead.
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
                            int cudaDevice,
                            VkTextureState* s,
                            VkDeviceSize requiredSize,
                            bool requireExternalSemaphore = false)
{
    if (!backend || !s || requiredSize == 0 || s->cudaUploadTerminal)
        return false;

    VkDevice device = backend->getDevice();
    VkPhysicalDevice phys = backend->getPhysicalDevice();
    if (device == VK_NULL_HANDLE || phys == VK_NULL_HANDLE)
        return false;

    if (cudaDevice >= 0)
        cudaSetDevice(cudaDevice);

    if (s->cudaUploadCommand == VK_NULL_HANDLE)
    {
        VkCommandBufferAllocateInfo commandInfo{};
        commandInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
        commandInfo.commandPool = backend->getCommandPool();
        commandInfo.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
        commandInfo.commandBufferCount = 1;
        if (vkAllocateCommandBuffers(device, &commandInfo, &s->cudaUploadCommand) != VK_SUCCESS)
            return false;
    }
    if (s->cudaUploadFence == VK_NULL_HANDLE)
    {
        VkFenceCreateInfo fenceInfo{};
        fenceInfo.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
        fenceInfo.flags = VK_FENCE_CREATE_SIGNALED_BIT;
        if (vkCreateFence(device, &fenceInfo, nullptr, &s->cudaUploadFence) != VK_SUCCESS)
            return false;
    }
    if (requireExternalSemaphore && !s->cudaUploadSync.initialized &&
        !createCudaInteropSemaphores(device, phys, &s->cudaUploadSync))
        return false;
    if (s->cudaUploadBuffer != VK_NULL_HANDLE && s->cudaUploadPtr &&
        s->cudaUploadSize >= requiredSize)
        return true;

    // A state is a native pacing slot.  Its fence is normally already
    // signalled by the time slot ownership returns; waiting here is a local
    // lifetime check, never a whole-queue/device drain.
    if (vkWaitForFences(device, 1, &s->cudaUploadFence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
    {
        s->cudaUploadTerminal = true;
        return false;
    }

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
    // Import must happen on the CUDA device that is the same adapter Vulkan
    // exported from; otherwise cudaImportExternalMemory refuses the handle.
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

struct VulkanByteImageGpu::DeferredDestruction
{
    std::mutex mutex;
    std::vector<VkTripleTextureState*> states;
    VkTextureState cpuUpload; // shared by the CPU uploads of all images
};

VulkanByteImageGpu::VulkanByteImageGpu(VulkanBackend* backend)
    : m_backend(backend), m_deferredDestruction(new DeferredDestruction())
{
}

bool VulkanByteImageGpu::supportsFromGpu() const
{
#if OMNIUI_HAS_CUDA
    // call_once gives every concurrent caller the same completed answer: the
    // first arrival performs the real export/import, the rest block until it
    // finishes and then observe the result with the necessary happens-before.
    // No caller can ever see a provisional value.
    std::call_once(m_fromGpuOnce, [this]() {
        m_fromGpuUsable = false;
        m_fromGpuCudaDevice = -1;
        if (!m_backend)
            return;
        VkPhysicalDevice phys = m_backend->getPhysicalDevice();
        if (phys == VK_NULL_HANDLE || !m_backend->hasExternalMemory())
            return;

        int visible = 0;
        if (cudaGetDeviceCount(&visible) != cudaSuccess || visible == 0)
        {
            fprintf(stderr, "VulkanByteImageGpu: no CUDA device is visible; "
                            "GPU-resident upload is unavailable and publication "
                            "uses the host path\n");
            return;
        }
        m_fromGpuCudaDevice = matchCudaDeviceForVulkan(phys);

        // Identity alone decides nothing: a MIG-partitioned adapter reports a
        // UUID to CUDA that never equals the Vulkan device UUID yet imports
        // fine, while a genuinely different adapter reports no match and
        // cannot import. Settle it by performing the real export/import once.
        {
            std::lock_guard<std::mutex> queueLock(m_backend->getQueueMutex());
            VkTextureState probe{};
            if (ensureCudaUploadBuffer(m_backend, m_fromGpuCudaDevice, &probe, 4096))
                m_fromGpuUsable = true;
            destroyTexture(m_backend, &probe);
        }
        if (!m_fromGpuUsable)
            fprintf(stderr, "VulkanByteImageGpu: the CUDA/Vulkan pair cannot import "
                            "exported memory; GPU-resident upload is unavailable and "
                            "publication uses the host path\n");
    });
    return m_fromGpuUsable;
#else
    return false;
#endif
}

VulkanByteImageGpu::~VulkanByteImageGpu()
{
    drainDeferredDestructions();
    destroyTexture(m_backend, &m_deferredDestruction->cpuUpload);
}

IByteImageGpu::Handle VulkanByteImageGpu::createState()
{
    return new VkTripleTextureState();
}

void VulkanByteImageGpu::destroyState(Handle h)
{
    VkTripleTextureState* state = static_cast<VkTripleTextureState*>(h);
    if (state == nullptr)
    {
        return;
    }
    std::lock_guard<std::mutex> lock(m_deferredDestruction->mutex);
    m_deferredDestruction->states.push_back(state);
}

void VulkanByteImageGpu::drainDeferredDestructions()
{
    std::vector<VkTripleTextureState*> states;
    {
        std::lock_guard<std::mutex> lock(m_deferredDestruction->mutex);
        states.swap(m_deferredDestruction->states);
    }
    if (states.empty())
    {
        return;
    }

    std::lock_guard<std::mutex> queueLock(m_backend->getQueueMutex());
    const VkDevice device = m_backend->getDevice();
    if (device != VK_NULL_HANDLE)
    {
        std::lock_guard<std::mutex> presentLock(m_backend->getPresentQueueMutex());
        OVUI_DEVELOPMENT_TIME_SCOPE(waitScope, "VulkanByteImageGpu.vkDeviceWaitIdle [ovui debug]");
        vkDeviceWaitIdle(device);
    }
    for (VkTripleTextureState* state : states)
    {
        for (VkTextureState& slot : state->slots)
        {
            // The wait above covers every slot: the queue lock is still held.
            destroyTexture(m_backend, &slot, false, true);
        }
        delete state;
    }
}

IByteImageGpu::UpdateResult VulkanByteImageGpu::updateImage(
    Handle h,
    const uint8_t* const* mipMapBuffers,
    size_t* mipMapStrides,
    size_t mipMapCount,
    UInt2 size,
    PixelFormat format,
    bool fromGpu,
    uint32_t gpuDeviceMask,
    uint32_t textureUsageFlags,
    uint32_t resourceUsageFlags)
{
    return updateImageImpl(h, mipMapBuffers, mipMapStrides, mipMapCount, size, format,
                           fromGpu, gpuDeviceMask, textureUsageFlags, resourceUsageFlags,
                           false);
}

IByteImageGpu::UpdateResult VulkanByteImageGpu::updateImageFromGpuAsync(
    Handle h,
    const uint8_t* devicePixels,
    size_t rowStride,
    UInt2 size,
    PixelFormat format)
{
    const uint8_t* buffers[] = {devicePixels};
    return updateImageImpl(h, buffers, &rowStride, 1, size, format, true, 0, 0, 0, true);
}

UploadResult VulkanByteImageGpu::updateImageFromGpuAsyncChecked(
    Handle h,
    const uint8_t* devicePixels,
    size_t rowStride,
    UInt2 size,
    PixelFormat format)
{
    UploadResult out;
    const uint8_t* buffers[] = {devicePixels};
    out.update = updateImageImpl(h, buffers, &rowStride, 1, size, format, true, 0, 0, 0, true, &out);
    return out;
}

IByteImageGpu::UpdateResult VulkanByteImageGpu::updateImageImpl(
    Handle h,
    const uint8_t* const* mipMapBuffers,
    size_t* mipMapStrides,
    size_t mipMapCount,
    UInt2 size,
    PixelFormat format,
    bool fromGpu,
    uint32_t /*gpuDeviceMask*/,
    uint32_t /*textureUsageFlags*/,
    uint32_t /*resourceUsageFlags*/,
    bool asynchronousGpuSource,
    UploadResult* checked)
{
    UpdateResult result;
    // A failed upload returns this. The checked result also gets the cause.
    auto refuse = [&](const char* cause) -> UpdateResult {
        if (checked)
            checked->cause = cause;
        return result;
    };
    VkTripleTextureState* state = static_cast<VkTripleTextureState*>(h);
    if (!state || !m_backend || !mipMapBuffers || mipMapCount == 0 || size.x == 0 || size.y == 0)
        return refuse("the upload has no state, no backend, no pixels or a zero size");
    std::lock_guard<std::mutex> queueLock(m_backend->getQueueMutex());
#if !OMNIUI_HAS_CUDA
    if (fromGpu)
    {
        static std::atomic<bool> warned{false};
        if (!warned.exchange(true, std::memory_order_relaxed))
            fprintf(stderr, "VulkanByteImageGpu: fromGpu requires CUDA support (not compiled in)\n");
        return refuse("a GPU source needs CUDA, and this build has no CUDA support");
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
            return refuse("the pixel format is not supported");
    }
    // Most GPUs cannot sample 3-channel float images, so add alpha 1 and
    // upload host pixels as RGBA, like GL_RGB16F and GL_RGB32F on OpenGL.
    std::vector<uint8_t> rgbaPixels;
    const uint8_t* rgbaBuffer = nullptr;
    size_t rgbaStride = 0;
    if (imageChannelCount == 3 && !fromGpu)
    {
        const size_t channelBytes = bytesPerPixel / 3;
        const size_t srcStride = mipMapStrides != nullptr && mipMapStrides[0] != 0 ? mipMapStrides[0] : size.x * bytesPerPixel;
        const uint16_t halfOne = 0x3C00;
        const float floatOne = 1.0f;
        const void* one = channelBytes == 2 ? static_cast<const void*>(&halfOne) : static_cast<const void*>(&floatOne);
        vkFormat = channelBytes == 2 ? VK_FORMAT_R16G16B16A16_SFLOAT : VK_FORMAT_R32G32B32A32_SFLOAT;
        bytesPerPixel = channelBytes * 4;
        rgbaStride = size.x * bytesPerPixel;
        rgbaPixels.resize(rgbaStride * size.y);
        for (uint32_t y = 0; y < size.y; ++y)
        {
            for (uint32_t x = 0; x < size.x; ++x)
            {
                uint8_t* dst = rgbaPixels.data() + y * rgbaStride + x * bytesPerPixel;
                std::memcpy(dst, mipMapBuffers[0] + y * srcStride + x * channelBytes * 3, channelBytes * 3);
                std::memcpy(dst + channelBytes * 3, one, channelBytes);
            }
        }
        rgbaBuffer = rgbaPixels.data();
        mipMapBuffers = &rgbaBuffer;
        mipMapStrides = &rgbaStride;
        mipMapCount = 1;
    }

    VkDevice device = m_backend->getDevice();
    VkPhysicalDevice phys = m_backend->getPhysicalDevice();
    VkQueue queue = m_backend->getQueue();
    VkCommandPool cmdPool = m_backend->getCommandPool();
    if (device == VK_NULL_HANDLE || queue == VK_NULL_HANDLE || cmdPool == VK_NULL_HANDLE) return refuse("the Vulkan device, queue or command pool is missing");
    uint32_t uploadSlot = kInvalidPresentationSlot;
    {
        uploadSlot = acquireUploadSlot(device, state);
    }
    if (uploadSlot == kInvalidPresentationSlot)
    {
        if (state->frontSlot != kInvalidPresentationSlot)
            result.imGuiReference = reinterpret_cast<void*>(state->slots[state->frontSlot].descriptorSet);
        return refuse("all upload slots are busy");
    }
    VkTextureState* s = &state->slots[uploadSlot];
    if (s->cpuUploadTerminal)
    {
        fprintf(stderr, "VulkanByteImageGpu: slot upload state is terminal after a Vulkan synchronization failure\n");
        return refuse("the upload slot stopped after a Vulkan synchronization failure");
    }

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
            return refuse("the Vulkan device cannot sample this format");
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
        return refuse("a GPU source with 3 channels is not supported");
    }

    // Recreate if size, format or mip count changed, or first time. The CPU
    // path uploads the whole mip chain so small icons stay smooth like OpenGL.
    const uint32_t width = size.x;
    const uint32_t height = size.y;
    const uint32_t mipLevels = static_cast<uint32_t>(mipMapCount);
    if (s->image == VK_NULL_HANDLE
        || s->width != width
        || s->height != height
        || s->format != format
        || s->mipLevels != mipLevels)
    {
        const bool keepDescriptorSet = s->descriptorSet != VK_NULL_HANDLE;
        destroyTexture(m_backend, s, keepDescriptorSet);

        VkImageCreateInfo imageInfo = {};
        imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
        imageInfo.imageType = VK_IMAGE_TYPE_2D;
        imageInfo.format = vkFormat;
        imageInfo.extent = { width, height, 1 };
        imageInfo.mipLevels = mipLevels;
        imageInfo.arrayLayers = 1;
        imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
        imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
        imageInfo.usage = VK_IMAGE_USAGE_SAMPLED_BIT
                        | VK_IMAGE_USAGE_TRANSFER_DST_BIT
                        | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
        imageInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
        if (vkCreateImage(device, &imageInfo, nullptr, &s->image) != VK_SUCCESS)
            return refuse("vkCreateImage failed");

        VkMemoryRequirements memReq;
        vkGetImageMemoryRequirements(device, s->image, &memReq);
        VkMemoryAllocateInfo allocInfo = {};
        allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        allocInfo.allocationSize = memReq.size;
        allocInfo.memoryTypeIndex = findMemoryType(phys, memReq.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        if (vkAllocateMemory(device, &allocInfo, nullptr, &s->memory) != VK_SUCCESS)
        {
            destroyTexture(m_backend, s); return refuse("vkAllocateMemory failed for the texture");
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
            // Font texture. The upload stores R in alpha, so (1,1,1,A)
            // matches the OpenGL (1,1,1,R) swizzle path.
            viewInfo.components = { VK_COMPONENT_SWIZZLE_ONE, VK_COMPONENT_SWIZZLE_ONE,
                                    VK_COMPONENT_SWIZZLE_ONE, VK_COMPONENT_SWIZZLE_A };
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
        viewInfo.subresourceRange.levelCount = mipLevels;
        viewInfo.subresourceRange.layerCount = 1;
        if (vkCreateImageView(device, &viewInfo, nullptr, &s->view) != VK_SUCCESS)
        {
            destroyTexture(m_backend, s); return refuse("vkCreateImageView failed");
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
        samplerInfo.maxLod = VK_LOD_CLAMP_NONE;
        samplerInfo.maxAnisotropy = 1.0f;
        // NOTE: ImGui's descriptor set layout has an immutable sampler, so the
        // one passed to AddTexture is ignored — we keep this object alive
        // only to match the interface. The font sampler is what actually
        // ends up bound.
        if (vkCreateSampler(device, &samplerInfo, nullptr, &s->sampler) != VK_SUCCESS)
        {
            destroyTexture(m_backend, s); return refuse("vkCreateSampler failed");
        }

        s->width = width;
        s->height = height;
        s->format = format;
        s->mipLevels = mipLevels;
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
            return refuse("a GPU source with the R8 format is not supported");
        }
        const void* srcDev = static_cast<const void*>(mipMapBuffers[0]);
        size_t srcPitch = static_cast<size_t>(width) * bytesPerPixel;
        if (mipMapStrides != nullptr && mipMapStrides[0] != 0)
        {
            srcPitch = mipMapStrides[0];
        }
        const size_t rowBytes = (size_t)width * bytesPerPixel;
        const VkDeviceSize uploadSize = rowBytes * height;
        bool uploadBufferReady = false;
        {
            uploadBufferReady = ensureCudaUploadBuffer(
                m_backend, m_fromGpuCudaDevice, s, uploadSize, asynchronousGpuSource);
        }
        if (!uploadBufferReady)
        {
            fprintf(stderr, "VulkanByteImageGpu: CUDA upload buffer unavailable; fromGpu disabled\n");
            return refuse("the CUDA upload buffer is not available");
        }

        // Reuse is slot-scoped. The fence proves that Vulkan consumed the
        // preceding CUDA signal and completed the buffer-to-image copy before
        // this slot's resources are overwritten.
        VkResult cudaUploadFenceResult = VK_SUCCESS;
        {
            cudaUploadFenceResult = vkWaitForFences(
                device, 1, &s->cudaUploadFence, VK_TRUE, UINT64_MAX);
        }
        if (cudaUploadFenceResult != VK_SUCCESS ||
            vkResetFences(device, 1, &s->cudaUploadFence) != VK_SUCCESS ||
            vkResetCommandBuffer(s->cudaUploadCommand, 0) != VK_SUCCESS)
        {
            fprintf(stderr, "VulkanByteImageGpu: CUDA upload slot synchronization failed\n");
            s->cudaUploadTerminal = true;
            return refuse("the CUDA upload slot could not be synchronized");
        }

        cudaError_t cuErr = cudaSuccess;
        {
            cuErr = cudaMemcpy2DAsync(
                s->cudaUploadPtr,
                rowBytes,
                srcDev,
                srcPitch,
                rowBytes,
                height,
                cudaMemcpyDeviceToDevice,
                /*stream=*/nullptr);
        }
        if (cuErr != cudaSuccess)
        {
            fprintf(stderr, "VulkanByteImageGpu: cudaMemcpy2DAsync(upload buffer) failed: %s\n",
                    cudaGetErrorString(cuErr));
            // The fence was reset above and no submit will signal it. Signal
            // it with an empty submit, or the next upload of this slot waits
            // for it forever. This failure is not terminal: the caller can
            // fall back, or try again.
            VkSubmitInfo rearm = {};
            rearm.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
            if (vkQueueSubmit(queue, 1, &rearm, s->cudaUploadFence) != VK_SUCCESS)
            {
                // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
                fprintf(stderr, "VulkanByteImageGpu: could not re-arm the CUDA upload fence\n");
                s->cudaUploadTerminal = true;
            }
            return refuse("cudaMemcpy2DAsync to the upload buffer failed");
        }
        uint64_t signalValue = 0;
        if (asynchronousGpuSource)
        {
            cudaExternalSemaphoreSignalParams signalParams = {};
            if (s->cudaUploadSync.useTimeline)
            {
                signalValue = ++s->cudaUploadSync.timelineValue;
            }
            if (s->cudaUploadSync.useTimeline)
            {
                signalParams.params.fence.value = signalValue;
            }
            cuErr = cudaSignalExternalSemaphoresAsync(
                &s->cudaUploadSync.extSemCuDone, &signalParams, 1, /*stream=*/nullptr);
            if (cuErr != cudaSuccess)
            {
                fprintf(stderr, "VulkanByteImageGpu: CUDA upload semaphore signal failed: %s\n",
                        cudaGetErrorString(cuErr));
                s->cudaUploadTerminal = true;
                return refuse("the CUDA upload semaphore could not be signaled");
            }
        }
        else
        {
            {
                cuErr = cudaStreamSynchronize(/*stream=*/nullptr);
            }
            if (cuErr != cudaSuccess)
            {
                fprintf(stderr, "VulkanByteImageGpu: synchronous CUDA upload copy failed\n");
                s->cudaUploadTerminal = true;
                return refuse("the synchronous CUDA upload copy failed");
            }
        }

        VkCommandBuffer cmd = s->cudaUploadCommand;
        {
            VkCommandBufferBeginInfo bi = {};
            bi.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
            bi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
            vkBeginCommandBuffer(cmd, &bi);

            VkImageMemoryBarrier toTransfer = {};
            toTransfer.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
            if (s->imageInitialized)
            {
                toTransfer.oldLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
                toTransfer.srcAccessMask = VK_ACCESS_SHADER_READ_BIT;
            }
            else
            {
                toTransfer.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
                toTransfer.srcAccessMask = 0;
            }
            toTransfer.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
            toTransfer.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
            toTransfer.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
            toTransfer.image = s->image;
            toTransfer.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
            toTransfer.subresourceRange.levelCount = 1;
            toTransfer.subresourceRange.layerCount = 1;
            toTransfer.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
            VkPipelineStageFlags sourceStage = VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT;
            if (s->imageInitialized)
            {
                sourceStage = VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT;
            }
            vkCmdPipelineBarrier(cmd,
                sourceStage,
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

        VkPipelineStageFlags waitStage = VK_PIPELINE_STAGE_TRANSFER_BIT;
        VkSubmitInfo submit = {};
        submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        if (asynchronousGpuSource)
        {
            submit.waitSemaphoreCount = 1;
            submit.pWaitSemaphores = &s->cudaUploadSync.vkSemCuDone;
            submit.pWaitDstStageMask = &waitStage;
        }
        submit.commandBufferCount = 1;
        submit.pCommandBuffers = &cmd;
        VkTimelineSemaphoreSubmitInfo timelineSubmit = {};
        if (asynchronousGpuSource && s->cudaUploadSync.useTimeline)
        {
            timelineSubmit.sType = VK_STRUCTURE_TYPE_TIMELINE_SEMAPHORE_SUBMIT_INFO;
            timelineSubmit.waitSemaphoreValueCount = 1;
            timelineSubmit.pWaitSemaphoreValues = &signalValue;
            submit.pNext = &timelineSubmit;
        }
        VkResult submitResult = VK_SUCCESS;
        {
            submitResult = vkQueueSubmit(queue, 1, &submit, s->cudaUploadFence);
        }
        if (submitResult != VK_SUCCESS)
        {
            fprintf(stderr, "VulkanByteImageGpu: vkQueueSubmit (fromGpu upload) failed\n");
            s->cudaUploadTerminal = true;
            return refuse("vkQueueSubmit of the GPU-source upload failed");
        }
        s->imageInitialized = true;
        if (!asynchronousGpuSource)
        {
            VkResult cudaUploadCompletionResult = VK_SUCCESS;
            {
                cudaUploadCompletionResult = vkWaitForFences(
                    device, 1, &s->cudaUploadFence, VK_TRUE, UINT64_MAX);
            }
            if (cudaUploadCompletionResult != VK_SUCCESS)
            {
                fprintf(stderr, "VulkanByteImageGpu: synchronous Vulkan upload completion wait failed\n");
                s->cudaUploadTerminal = true;
                return refuse("waiting for the GPU-source upload failed");
            }
        }

        {
            if (s->descriptorSet == VK_NULL_HANDLE)
            {
                s->descriptorSet = ImGui_ImplVulkan_AddTexture(
                    s->sampler, s->view, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
                s->descriptorNeedsUpdate = s->descriptorSet == VK_NULL_HANDLE;
            }
            else if (s->descriptorNeedsUpdate)
            {
                // destroyTexture drained the old image before replacement.
                // An ordinary pixel upload must not rewrite a descriptor that
                // can still be referenced by recorded or pending UI draws.
                updateTextureDescriptor(device, s);
            }
        }
        VkFence completionFence = VK_NULL_HANDLE;
        if (asynchronousGpuSource)
        {
            completionFence = s->cudaUploadFence;
        }
        s->cpuUploadTicket = 0;
        result = publishSubmittedUpload(device, state, uploadSlot, asynchronousGpuSource, completionFence);
        reportUpload(checked, result, state->slots[uploadSlot],
                     !(asynchronousGpuSource && state->slots[uploadSlot].uploadPending));
        return result;
    }
#endif // OMNIUI_HAS_CUDA

    // --- Upload pixels (every mip level) via a host-visible staging buffer ---
    size_t sourceBytesPerPixel = bytesPerPixel;
    if (isR8)
    {
        sourceBytesPerPixel = 1;
    }
    // The staging buffer holds every level, so one copy and one submit upload
    // the whole image. An image with one level asks for the bytes it always
    // asked for.
    VkDeviceSize uploadSize = 0;
    for (uint32_t level = 0; level < mipLevels; ++level)
    {
        const uint32_t levelWidth = (std::max)(width >> level, 1u);
        const uint32_t levelHeight = (std::max)(height >> level, 1u);
        uploadSize += (VkDeviceSize)levelWidth * levelHeight * bytesPerPixel;
    }

    bool cpuUploadResourcesReady = false;
    {
        cpuUploadResourcesReady = ensureCpuUploadResources(m_backend, s, uploadSize, &m_deferredDestruction->cpuUpload);
    }
    if (!cpuUploadResourcesReady)
    {
        // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "VulkanByteImageGpu: persistent CPU upload resources unavailable\n");
        return refuse("the CPU upload resources are not available");
    }
    // The previous copy reads the staging buffer until its fence signals:
    // wait for it before any new pixels are written there.
    if (vkWaitForFences(device, 1, &s->cpuUploadFence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
    {
        // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "VulkanByteImageGpu: persistent CPU upload fence wait failed\n");
        s->cpuUploadTerminal = true;
        return refuse("waiting for the previous CPU upload failed");
    }
    m_deferredDestruction->cpuUpload.cpuUploadInFlight = false;
    m_deferredDestruction->cpuUpload.cpuUploadFinished = m_deferredDestruction->cpuUpload.cpuUploadSubmitted;
    // Fill the staging buffer with every level, one after the other.
    std::vector<VkBufferImageCopy> regions;
    regions.reserve(mipLevels);
    VkDeviceSize uploadOffset = 0;
    for (uint32_t mip = 0; mip < mipLevels; ++mip)
    {
        const uint32_t mipWidth = (std::max)(width >> mip, 1u);
        const uint32_t mipHeight = (std::max)(height >> mip, 1u);
        const size_t uploadRowBytes = (size_t)mipWidth * bytesPerPixel;
        size_t srcStride = static_cast<size_t>(mipWidth) * sourceBytesPerPixel;
        if (mipMapStrides != nullptr && mipMapStrides[mip] != 0)
        {
            srcStride = mipMapStrides[mip];
        }
        const uint8_t* srcPixels = mipMapBuffers[mip];
        uint8_t* dst = static_cast<uint8_t*>(s->cpuUploadMapped) + uploadOffset;
        if (isR8)
        {
            // Expand R8 -> RGBA8 (rgb=0, a=R) so the shader's color*texel.a term
            // produces the font glyph. Matches the GL swizzle.
            for (uint32_t y = 0; y < mipHeight; ++y)
            {
                const uint8_t* srcRow = srcPixels + y * srcStride;
                uint8_t* dstRow = dst + (size_t)y * uploadRowBytes;
                for (uint32_t x = 0; x < mipWidth; ++x)
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
            std::memcpy(dst, srcPixels, uploadRowBytes * mipHeight);
        }
        else
        {
            for (uint32_t y = 0; y < mipHeight; ++y)
            {
                std::memcpy(dst + (size_t)y * uploadRowBytes, srcPixels + (size_t)y * srcStride, uploadRowBytes);
            }
        }
        VkBufferImageCopy region = {};
        region.bufferOffset = uploadOffset;
        region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.imageSubresource.mipLevel = mip;
        region.imageSubresource.layerCount = 1;
        region.imageExtent = { mipWidth, mipHeight, 1 };
        regions.push_back(region);
        uploadOffset += uploadRowBytes * mipHeight;
    }

    // Re-record the slot-owned command buffer. No Vulkan object or descriptor
    // is allocated on the steady-state frame path.
    VkCommandBuffer cmd = s->cpuUploadCommand;
    {
        if (vkResetFences(device, 1, &s->cpuUploadFence) != VK_SUCCESS)
        {
            // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
            fprintf(stderr, "VulkanByteImageGpu: persistent CPU upload fence reset failed\n");
            s->cpuUploadTerminal = true;
            return refuse("resetting the CPU upload fence failed");
        }
        if (vkResetCommandBuffer(cmd, 0) != VK_SUCCESS)
        {
            // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
            fprintf(stderr, "VulkanByteImageGpu: persistent CPU upload command reset failed\n");
            s->cpuUploadTerminal = true;
            return refuse("resetting the CPU upload command buffer failed");
        }
        VkCommandBufferBeginInfo beginInfo = {};
        beginInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
        beginInfo.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
        if (vkBeginCommandBuffer(cmd, &beginInfo) != VK_SUCCESS)
        {
            // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
            fprintf(stderr, "VulkanByteImageGpu: persistent CPU upload command begin failed\n");
            s->cpuUploadTerminal = true;
            return refuse("beginning the CPU upload command buffer failed");
        }

        VkImageMemoryBarrier toTransfer = {};
        toTransfer.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
        toTransfer.srcAccessMask = VK_ACCESS_SHADER_READ_BIT;
        toTransfer.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        VkPipelineStageFlags sourceStage = VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT;
        if (s->imageInitialized)
        {
            toTransfer.oldLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
            sourceStage = VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT;
        }
        else
        {
            toTransfer.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
        }
        if (!s->imageInitialized)
        {
            toTransfer.srcAccessMask = 0;
        }
        toTransfer.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        toTransfer.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        toTransfer.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
        toTransfer.image = s->image;
        toTransfer.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        toTransfer.subresourceRange.levelCount = mipLevels;
        toTransfer.subresourceRange.layerCount = 1;
        vkCmdPipelineBarrier(cmd,
            sourceStage,
            VK_PIPELINE_STAGE_TRANSFER_BIT,
            0, 0, nullptr, 0, nullptr, 1, &toTransfer);

        vkCmdCopyBufferToImage(cmd, s->cpuUploadBuffer, s->image,
                               VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                               (uint32_t)regions.size(), regions.data());

        VkImageMemoryBarrier toRead = toTransfer;
        toRead.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
        toRead.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
        toRead.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
        toRead.newLayout = VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL;
        vkCmdPipelineBarrier(cmd,
            VK_PIPELINE_STAGE_TRANSFER_BIT,
            VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT,
            0, 0, nullptr, 0, nullptr, 1, &toRead);

        if (vkEndCommandBuffer(cmd) != VK_SUCCESS)
        {
            // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
            fprintf(stderr, "VulkanByteImageGpu: persistent CPU upload command end failed\n");
            s->cpuUploadTerminal = true;
            return refuse("ending the CPU upload command buffer failed");
        }

        VkSubmitInfo submit = {};
        submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        submit.commandBufferCount = 1;
        submit.pCommandBuffers = &cmd;
        VkResult submitResult = VK_SUCCESS;
        {
            submitResult = vkQueueSubmit(queue, 1, &submit, s->cpuUploadFence);
        }
        if (submitResult != VK_SUCCESS)
        {
            // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
            fprintf(stderr, "VulkanByteImageGpu: persistent CPU upload submit failed\n");
            s->cpuUploadTerminal = true;
            return refuse("vkQueueSubmit of the CPU upload failed");
        }
        // Not waited: later draws that sample the image are submitted on the
        // same queue after this copy and its barrier, and the next upload
        // waits for this fence before it rewrites the staging buffer.
        VkTextureState& shared = m_deferredDestruction->cpuUpload;
        shared.cpuUploadInFlight = true;
        s->cpuUploadTicket = ++shared.cpuUploadSubmitted;
        s->imageInitialized = true;
    }

    // Register (or re-register after resize) with ImGui.
    {
        if (s->descriptorSet == VK_NULL_HANDLE)
        {
            s->descriptorSet = ImGui_ImplVulkan_AddTexture(
                s->sampler, s->view, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL);
            s->descriptorNeedsUpdate = s->descriptorSet == VK_NULL_HANDLE;
        }
        else if (s->descriptorNeedsUpdate)
        {
            updateTextureDescriptor(device, s);
        }
    }

    result = publishSubmittedUpload(device, state, uploadSlot, false, VK_NULL_HANDLE);
    // The copy was submitted and not waited for, so it is only enqueued.
    // getCompletedUploadId() reports its end when its fence has signalled.
    reportUpload(checked, result, state->slots[uploadSlot], false);
    return result;
}

UploadResult VulkanByteImageGpu::updateImageChecked(
    Handle h,
    const uint8_t* const* mipMapBuffers,
    size_t* mipMapStrides,
    size_t mipMapCount,
    UInt2 size,
    PixelFormat format,
    bool fromGpu,
    uint32_t gpuDeviceMask,
    uint32_t textureUsageFlags,
    uint32_t resourceUsageFlags)
{
    UploadResult out;
    out.requestedDeviceMask = gpuDeviceMask;
    if (!isSingleDeviceMaskSupported(gpuDeviceMask))
    {
        // This backend has one device. A request for another device cannot be
        // met, and nothing is uploaded.
        // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "VulkanByteImageGpu: device mask 0x%x asks for devices this backend does not have\n",
                (unsigned)gpuDeviceMask);
        out.cause = "the device mask asks for a device that the Vulkan backend does not have";
        return out;
    }
    out.update = updateImageImpl(h, mipMapBuffers, mipMapStrides, mipMapCount, size, format, fromGpu,
                                 gpuDeviceMask, textureUsageFlags, resourceUsageFlags, false, &out);
    return out;
}

uint64_t VulkanByteImageGpu::getCompletedUploadId(Handle h)
{
    VkTripleTextureState* state = static_cast<VkTripleTextureState*>(h);
    if (!state || !m_backend)
        return 0;
    std::lock_guard<std::mutex> queueLock(m_backend->getQueueMutex());
    VkDevice device = m_backend->getDevice();
    if (device == VK_NULL_HANDLE)
        return 0;
    pollCompletedUploads(device, state);
    VkTextureState& shared = m_deferredDestruction->cpuUpload;
    if (shared.cpuUploadInFlight && shared.cpuUploadFence != VK_NULL_HANDLE &&
        vkGetFenceStatus(device, shared.cpuUploadFence) == VK_SUCCESS)
        shared.cpuUploadFinished = shared.cpuUploadSubmitted;
    uint64_t completed = 0;
    for (const VkTextureState& slot : state->slots)
    {
        // An image that a CPU copy wrote is complete only when that copy has finished.
        if (slot.image != VK_NULL_HANDLE && !slot.uploadPending && slot.cpuUploadTicket <= shared.cpuUploadFinished &&
            slot.uploadSerial > completed)
            completed = slot.uploadSerial;
    }
    return completed;
}

VkImage VulkanByteImageGpu::getVkImageForState(Handle h) const
{
    VkTripleTextureState* state = static_cast<VkTripleTextureState*>(h);
    if (!state || state->frontSlot == kInvalidPresentationSlot)
        return VK_NULL_HANDLE;
    return state->slots[state->frontSlot].image;
}

void VulkanByteImageGpu::releaseImage(Handle h)
{
    VkTripleTextureState* state = static_cast<VkTripleTextureState*>(h);
    if (state == nullptr)
    {
        return;
    }
    std::lock_guard<std::mutex> queueLock(m_backend->getQueueMutex());
    // The caller keeps the state, so hand its Vulkan objects to a copy that
    // is released later, and leave the state empty for the next upload.
    auto* retired = new VkTripleTextureState(*state);
    *state = VkTripleTextureState{};
    if (m_backend->frameReleasesDeferred())
    {
        // Inside a frame, the end-of-frame drain releases all copies after one device wait.
        destroyState(retired);
        return;
    }
    VulkanBackend* backend = m_backend;
    backend->deferRelease([backend, retired]() {
        for (VkTextureState& slot : retired->slots)
        {
            destroyTexture(backend, &slot);
        }
        delete retired;
    });
}

} // namespace standalone
} // namespace ui
} // namespace omni
