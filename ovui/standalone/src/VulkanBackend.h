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

#pragma once

#include "StandaloneInit.h"

#if defined(_WIN32) && !defined(VK_USE_PLATFORM_WIN32_KHR)
#  define VK_USE_PLATFORM_WIN32_KHR
#endif
#include <vulkan/vulkan.h>
#include <cstdint>

struct GLFWwindow;

namespace omni {
namespace ui {
namespace standalone {

/// Self-contained Vulkan context for offscreen ImGui rendering.
/// Owns the VkInstance, device, render pass, framebuffer, and command buffer.
/// Designed for headless (offscreen) operation — no swapchain needed.
class OMNIUI_STANDALONE_API VulkanBackend
{
public:
    VulkanBackend() = default;
    ~VulkanBackend();

    /// Initialize the Vulkan instance, device, render pass, and framebuffer.
    /// If glfwWindow is non-null, surface extensions are enabled (but no swapchain is created).
    /// Returns true on success.
    bool init(GLFWwindow* glfwWindow, int width, int height);

    /// Initialize in fully headless mode — no GLFW, no windowing system required.
    /// Works on servers without any display (no X11, no Wayland).
    bool initHeadless(int width, int height);

    /// Tear down all Vulkan resources.
    void shutdown();

    /// Initialize ImGui Vulkan backend and upload font textures.
    bool initImGui();

    /// Begin a new frame: reset + begin command buffer, begin render pass.
    void beginFrame(int width, int height);

    /// End the frame: end render pass, submit, wait idle.
    void endFrame();

    /// Read back the offscreen image pixels into an RGBA8 buffer.
    /// The caller must ensure the buffer is large enough (width * height * 4).
    bool readbackPixels(uint8_t* outPixels, int width, int height);

    /// Get the offscreen framebuffer dimensions.
    void getFramebufferSize(int* width, int* height) const;

    /// Check if the backend was initialized successfully.
    bool isInitialized() const { return m_device != VK_NULL_HANDLE; }
    bool isSoftwareDevice() const { return m_isSoftwareDevice; }

    VkCommandBuffer getCommandBuffer() const { return m_commandBuffer; }

    // Accessors for CUDA-Vulkan interop and NVENC streaming
    VkInstance       getInstance()       const { return m_instance; }
    VkPhysicalDevice getPhysicalDevice() const { return m_physicalDevice; }
    VkDevice         getDevice()         const { return m_device; }
    VkQueue          getQueue()          const { return m_queue; }
    uint32_t         getQueueFamily()    const { return m_queueFamily; }
    VkCommandPool    getCommandPool()    const { return m_commandPool; }
    VkImage          getColorImage()     const { return m_colorImage; }
    VkDeviceMemory   getColorMemory()    const { return m_colorMemory; }
    VkDeviceSize     getColorMemorySize() const { return m_colorMemorySize; }
    VkFence          getFence()          const { return m_fence; }

#if OMNIUI_HAS_CUDA
    /// Whether external memory extensions are enabled (required for CUDA interop).
    bool hasExternalMemory() const { return m_hasExternalMemory; }
#endif

private:
    bool createInstance();
    bool selectPhysicalDevice();
    bool createDevice();
    bool createRenderPass();
    bool createFramebuffer(int width, int height);
    void destroyFramebuffer();
    bool createCommandPool();
    bool createDescriptorPool();

    uint32_t findMemoryType(uint32_t typeBits, VkMemoryPropertyFlags properties);

    VkInstance               m_instance        = VK_NULL_HANDLE;
    VkPhysicalDevice         m_physicalDevice  = VK_NULL_HANDLE;
    VkDevice                 m_device          = VK_NULL_HANDLE;
    VkQueue                  m_queue           = VK_NULL_HANDLE;
    uint32_t                 m_queueFamily     = 0;
    VkRenderPass             m_renderPass      = VK_NULL_HANDLE;
    VkCommandPool            m_commandPool     = VK_NULL_HANDLE;
    VkCommandBuffer          m_commandBuffer   = VK_NULL_HANDLE;
    VkDescriptorPool         m_descriptorPool  = VK_NULL_HANDLE;
    VkFence                  m_fence           = VK_NULL_HANDLE;

    // Offscreen framebuffer
    VkImage                  m_colorImage      = VK_NULL_HANDLE;
    VkDeviceMemory           m_colorMemory     = VK_NULL_HANDLE;
    VkImageView              m_colorView       = VK_NULL_HANDLE;
    VkFramebuffer            m_framebuffer     = VK_NULL_HANDLE;
    VkDeviceSize             m_colorMemorySize = 0;
    int                      m_fbWidth         = 0;
    int                      m_fbHeight        = 0;

    bool                     m_headless           = false;
    bool                     m_imguiInitialized   = false;
    bool                     m_isSoftwareDevice   = false;
#if OMNIUI_HAS_CUDA
    bool                     m_hasExternalMemory = false;
#endif
};

} // namespace standalone
} // namespace ui
} // namespace omni
