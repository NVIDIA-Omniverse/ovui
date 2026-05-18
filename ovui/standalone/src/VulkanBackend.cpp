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

#include "VulkanBackend.h"

#include <imgui/imgui.h>
#include <imgui/backends/imgui_impl_vulkan.h>

#ifndef OMNIUI_HEADLESS_ONLY
#include <GLFW/glfw3.h>
#endif

#include <cstdio>
#include <cstring>
#include <vector>
#include <algorithm>

namespace omni {
namespace ui {
namespace standalone {

static void vkCheckResult(VkResult err)
{
    if (err != VK_SUCCESS)
        fprintf(stderr, "VulkanBackend: VkResult = %d\n", err);
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

VulkanBackend::~VulkanBackend()
{
    shutdown();
}

void VulkanBackend::shutdown()
{
    if (m_device != VK_NULL_HANDLE)
        vkDeviceWaitIdle(m_device);

    if (m_imguiInitialized)
    {
        ImGui_ImplVulkan_Shutdown();
        m_imguiInitialized = false;
    }

    destroyFramebuffer();

    if (m_fence != VK_NULL_HANDLE)
    {
        vkDestroyFence(m_device, m_fence, nullptr);
        m_fence = VK_NULL_HANDLE;
    }
    if (m_commandPool != VK_NULL_HANDLE)
    {
        vkDestroyCommandPool(m_device, m_commandPool, nullptr);
        m_commandPool = VK_NULL_HANDLE;
    }
    if (m_descriptorPool != VK_NULL_HANDLE)
    {
        vkDestroyDescriptorPool(m_device, m_descriptorPool, nullptr);
        m_descriptorPool = VK_NULL_HANDLE;
    }
    if (m_renderPass != VK_NULL_HANDLE)
    {
        vkDestroyRenderPass(m_device, m_renderPass, nullptr);
        m_renderPass = VK_NULL_HANDLE;
    }
    if (m_device != VK_NULL_HANDLE)
    {
        vkDestroyDevice(m_device, nullptr);
        m_device = VK_NULL_HANDLE;
    }
    if (m_instance != VK_NULL_HANDLE)
    {
        vkDestroyInstance(m_instance, nullptr);
        m_instance = VK_NULL_HANDLE;
    }
}

bool VulkanBackend::initHeadless(int width, int height)
{
    m_headless = true;
    return init(nullptr, width, height);
}

bool VulkanBackend::init(GLFWwindow* /*glfwWindow*/, int width, int height)
{
    if (!createInstance())       return false;
    if (!selectPhysicalDevice()) return false;
    if (!createDevice())         return false;
    if (!createCommandPool())    return false;
    if (!createDescriptorPool()) return false;
    if (!createRenderPass())     return false;
    if (!createFramebuffer(width, height)) return false;

    // Create fence for synchronization
    VkFenceCreateInfo fenceInfo = {};
    fenceInfo.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    fenceInfo.flags = VK_FENCE_CREATE_SIGNALED_BIT;
    VkResult err = vkCreateFence(m_device, &fenceInfo, nullptr, &m_fence);
    if (err != VK_SUCCESS)
    {
        fprintf(stderr, "VulkanBackend: failed to create fence\n");
        return false;
    }

    fprintf(stdout, "VulkanBackend: initialized successfully (%dx%d)\n", width, height);
    return true;
}

// ---------------------------------------------------------------------------
// Instance
// ---------------------------------------------------------------------------

bool VulkanBackend::createInstance()
{
    VkApplicationInfo appInfo = {};
    appInfo.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    appInfo.pApplicationName = "omni.ui";
    appInfo.applicationVersion = VK_MAKE_VERSION(1, 0, 0);
    appInfo.pEngineName = "omni.ui";
    appInfo.engineVersion = VK_MAKE_VERSION(1, 0, 0);
    appInfo.apiVersion = VK_API_VERSION_1_1;

    std::vector<const char*> extensions;
#ifndef OMNIUI_HEADLESS_ONLY
    if (!m_headless)
    {
        // Get required GLFW extensions (if GLFW is initialized)
        uint32_t glfwExtCount = 0;
        const char** glfwExts = glfwGetRequiredInstanceExtensions(&glfwExtCount);
        if (glfwExts)
        {
            for (uint32_t i = 0; i < glfwExtCount; i++)
                extensions.push_back(glfwExts[i]);
        }
    }
#endif
    // Headless mode needs no surface/display extensions

#if OMNIUI_HAS_CUDA
    // Required for CUDA interop: need physical device properties2 for UUID matching
    extensions.push_back(VK_KHR_GET_PHYSICAL_DEVICE_PROPERTIES_2_EXTENSION_NAME);
    extensions.push_back(VK_KHR_EXTERNAL_MEMORY_CAPABILITIES_EXTENSION_NAME);
    extensions.push_back(VK_KHR_EXTERNAL_SEMAPHORE_CAPABILITIES_EXTENSION_NAME);
#endif

    VkInstanceCreateInfo createInfo = {};
    createInfo.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    createInfo.pApplicationInfo = &appInfo;
    createInfo.enabledExtensionCount = (uint32_t)extensions.size();
    createInfo.ppEnabledExtensionNames = extensions.empty() ? nullptr : extensions.data();

    // Try to enable validation layers in debug
#ifndef NDEBUG
    const char* validationLayers[] = { "VK_LAYER_KHRONOS_validation" };
    uint32_t layerCount = 0;
    vkEnumerateInstanceLayerProperties(&layerCount, nullptr);
    std::vector<VkLayerProperties> availableLayers(layerCount);
    if (layerCount > 0)
        vkEnumerateInstanceLayerProperties(&layerCount, availableLayers.data());

    bool hasValidation = false;
    for (auto& layer : availableLayers)
    {
        if (strcmp(layer.layerName, "VK_LAYER_KHRONOS_validation") == 0)
        {
            hasValidation = true;
            break;
        }
    }
    if (hasValidation)
    {
        createInfo.enabledLayerCount = 1;
        createInfo.ppEnabledLayerNames = validationLayers;
        fprintf(stdout, "VulkanBackend: enabling validation layers\n");
    }
#endif

    VkResult err = vkCreateInstance(&createInfo, nullptr, &m_instance);
    if (err != VK_SUCCESS)
    {
        fprintf(stderr, "VulkanBackend: vkCreateInstance failed (%d)\n", err);
        return false;
    }
    return true;
}

// ---------------------------------------------------------------------------
// Physical device
// ---------------------------------------------------------------------------

static const char* deviceTypeStr(VkPhysicalDeviceType t)
{
    switch (t)
    {
    case VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU:   return "Discrete GPU";
    case VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU: return "Integrated GPU";
    case VK_PHYSICAL_DEVICE_TYPE_VIRTUAL_GPU:    return "Virtual GPU";
    case VK_PHYSICAL_DEVICE_TYPE_CPU:            return "CPU (software renderer)";
    default:                                      return "Other";
    }
}

bool VulkanBackend::selectPhysicalDevice()
{
    uint32_t count = 0;
    vkEnumeratePhysicalDevices(m_instance, &count, nullptr);
    if (count == 0)
    {
        fprintf(stderr, "VulkanBackend: no Vulkan-capable GPU found\n");
        return false;
    }

    std::vector<VkPhysicalDevice> devices(count);
    vkEnumeratePhysicalDevices(m_instance, &count, devices.data());

    // Prefer discrete GPU
    m_physicalDevice = devices[0];
    for (auto& dev : devices)
    {
        VkPhysicalDeviceProperties props;
        vkGetPhysicalDeviceProperties(dev, &props);
        if (props.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU)
        {
            m_physicalDevice = dev;
            break;
        }
    }

    VkPhysicalDeviceProperties selectedProps;
    vkGetPhysicalDeviceProperties(m_physicalDevice, &selectedProps);
    m_isSoftwareDevice = (selectedProps.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU);
    fprintf(stdout, "VulkanBackend: selected device: \"%s\" (vendorID=0x%04X, type=%s)\n",
            selectedProps.deviceName, selectedProps.vendorID, deviceTypeStr(selectedProps.deviceType));

    // Find graphics queue family
    uint32_t qfCount = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(m_physicalDevice, &qfCount, nullptr);
    std::vector<VkQueueFamilyProperties> qfProps(qfCount);
    vkGetPhysicalDeviceQueueFamilyProperties(m_physicalDevice, &qfCount, qfProps.data());

    m_queueFamily = UINT32_MAX;
    for (uint32_t i = 0; i < qfCount; i++)
    {
        if (qfProps[i].queueFlags & VK_QUEUE_GRAPHICS_BIT)
        {
            m_queueFamily = i;
            break;
        }
    }
    if (m_queueFamily == UINT32_MAX)
    {
        fprintf(stderr, "VulkanBackend: no graphics queue family found\n");
        return false;
    }

    return true;
}

// ---------------------------------------------------------------------------
// Logical device
// ---------------------------------------------------------------------------

bool VulkanBackend::createDevice()
{
    float queuePriority = 1.0f;
    VkDeviceQueueCreateInfo queueInfo = {};
    queueInfo.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    queueInfo.queueFamilyIndex = m_queueFamily;
    queueInfo.queueCount = 1;
    queueInfo.pQueuePriorities = &queuePriority;

    std::vector<const char*> deviceExtensions;

#if OMNIUI_HAS_CUDA
    // External memory extensions for CUDA interop
    deviceExtensions.push_back(VK_KHR_EXTERNAL_MEMORY_EXTENSION_NAME);
    deviceExtensions.push_back(VK_KHR_EXTERNAL_SEMAPHORE_EXTENSION_NAME);
#if defined(_WIN32)
    deviceExtensions.push_back(VK_KHR_EXTERNAL_MEMORY_WIN32_EXTENSION_NAME);
    deviceExtensions.push_back(VK_KHR_EXTERNAL_SEMAPHORE_WIN32_EXTENSION_NAME);
#else
    deviceExtensions.push_back(VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME);
    deviceExtensions.push_back(VK_KHR_EXTERNAL_SEMAPHORE_FD_EXTENSION_NAME);
#endif
    // Timeline semaphore support (optional, checked at runtime)
    deviceExtensions.push_back(VK_KHR_TIMELINE_SEMAPHORE_EXTENSION_NAME);
    fprintf(stdout, "VulkanBackend: enabling external memory/semaphore extensions for CUDA interop\n");
#endif

    VkDeviceCreateInfo createInfo = {};
    createInfo.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    createInfo.queueCreateInfoCount = 1;
    createInfo.pQueueCreateInfos = &queueInfo;
    createInfo.enabledExtensionCount = (uint32_t)deviceExtensions.size();
    createInfo.ppEnabledExtensionNames = deviceExtensions.empty() ? nullptr : deviceExtensions.data();

#if OMNIUI_HAS_CUDA
    // Probe timelineSemaphore support and chain the feature struct onto pNext
    // so vkCreateDevice actually enables it. createCudaInteropSemaphores picks
    // timeline mode from this same query — without enabling the feature here,
    // creating a VkSemaphore with VK_SEMAPHORE_TYPE_TIMELINE fails on
    // timeline-capable devices.
    VkPhysicalDeviceTimelineSemaphoreFeatures timelineFeatures = {};
    timelineFeatures.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TIMELINE_SEMAPHORE_FEATURES;
    VkPhysicalDeviceFeatures2 features2Probe = {};
    features2Probe.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2;
    features2Probe.pNext = &timelineFeatures;
    vkGetPhysicalDeviceFeatures2(m_physicalDevice, &features2Probe);
    if (timelineFeatures.timelineSemaphore == VK_TRUE)
    {
        timelineFeatures.pNext = nullptr;
        createInfo.pNext = &timelineFeatures;
    }
#endif

    VkResult err = vkCreateDevice(m_physicalDevice, &createInfo, nullptr, &m_device);
    if (err != VK_SUCCESS)
    {
        fprintf(stderr, "VulkanBackend: vkCreateDevice failed (%d)\n", err);
        return false;
    }

    vkGetDeviceQueue(m_device, m_queueFamily, 0, &m_queue);

#if OMNIUI_HAS_CUDA
    m_hasExternalMemory = true;
#endif

    return true;
}

// ---------------------------------------------------------------------------
// Command pool
// ---------------------------------------------------------------------------

bool VulkanBackend::createCommandPool()
{
    VkCommandPoolCreateInfo poolInfo = {};
    poolInfo.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    poolInfo.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
    poolInfo.queueFamilyIndex = m_queueFamily;
    VkResult err = vkCreateCommandPool(m_device, &poolInfo, nullptr, &m_commandPool);
    if (err != VK_SUCCESS) return false;

    VkCommandBufferAllocateInfo allocInfo = {};
    allocInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    allocInfo.commandPool = m_commandPool;
    allocInfo.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    allocInfo.commandBufferCount = 1;
    err = vkAllocateCommandBuffers(m_device, &allocInfo, &m_commandBuffer);
    return err == VK_SUCCESS;
}

// ---------------------------------------------------------------------------
// Descriptor pool
// ---------------------------------------------------------------------------

bool VulkanBackend::createDescriptorPool()
{
    VkDescriptorPoolSize poolSizes[] = {
        { VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 100 },
    };
    VkDescriptorPoolCreateInfo poolInfo = {};
    poolInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    poolInfo.flags = VK_DESCRIPTOR_POOL_CREATE_FREE_DESCRIPTOR_SET_BIT;
    poolInfo.maxSets = 100;
    poolInfo.poolSizeCount = 1;
    poolInfo.pPoolSizes = poolSizes;
    VkResult err = vkCreateDescriptorPool(m_device, &poolInfo, nullptr, &m_descriptorPool);
    return err == VK_SUCCESS;
}

// ---------------------------------------------------------------------------
// Render pass
// ---------------------------------------------------------------------------

bool VulkanBackend::createRenderPass()
{
    VkAttachmentDescription colorAttachment = {};
    colorAttachment.format = VK_FORMAT_R8G8B8A8_UNORM;
    colorAttachment.samples = VK_SAMPLE_COUNT_1_BIT;
    colorAttachment.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    colorAttachment.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    colorAttachment.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    colorAttachment.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    colorAttachment.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    colorAttachment.finalLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;

    VkAttachmentReference colorRef = {};
    colorRef.attachment = 0;
    colorRef.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;

    VkSubpassDescription subpass = {};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 1;
    subpass.pColorAttachments = &colorRef;

    VkSubpassDependency dependency = {};
    dependency.srcSubpass = VK_SUBPASS_EXTERNAL;
    dependency.dstSubpass = 0;
    dependency.srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dependency.dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dependency.srcAccessMask = 0;
    dependency.dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;

    VkRenderPassCreateInfo rpInfo = {};
    rpInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    rpInfo.attachmentCount = 1;
    rpInfo.pAttachments = &colorAttachment;
    rpInfo.subpassCount = 1;
    rpInfo.pSubpasses = &subpass;
    rpInfo.dependencyCount = 1;
    rpInfo.pDependencies = &dependency;

    VkResult err = vkCreateRenderPass(m_device, &rpInfo, nullptr, &m_renderPass);
    return err == VK_SUCCESS;
}

// ---------------------------------------------------------------------------
// Offscreen framebuffer
// ---------------------------------------------------------------------------

uint32_t VulkanBackend::findMemoryType(uint32_t typeBits, VkMemoryPropertyFlags properties)
{
    VkPhysicalDeviceMemoryProperties memProps;
    vkGetPhysicalDeviceMemoryProperties(m_physicalDevice, &memProps);
    for (uint32_t i = 0; i < memProps.memoryTypeCount; i++)
    {
        if ((typeBits & (1 << i)) && (memProps.memoryTypes[i].propertyFlags & properties) == properties)
            return i;
    }
    return UINT32_MAX;
}

bool VulkanBackend::createFramebuffer(int width, int height)
{
    if (width <= 0 || height <= 0)
        return false;

    // Build the new framebuffer into local handles first. Only on full
    // success do we destroy the old one and swap. If any step fails we
    // free what we built and leave ``m_colorImage`` / ``m_colorMemory``
    // / ``m_colorView`` / ``m_framebuffer`` / ``m_fbWidth`` /
    // ``m_fbHeight`` untouched, so the backend continues running on
    // the prior valid framebuffer (Codex Step 3.7 review #2 fix —
    // pre-fix code committed the new dimensions and destroyed the old
    // resources before any new resource was created).
    VkImage         newImage      = VK_NULL_HANDLE;
    VkDeviceMemory  newMemory     = VK_NULL_HANDLE;
    VkDeviceSize    newMemorySize = 0;
    VkImageView     newView       = VK_NULL_HANDLE;
    VkFramebuffer   newFramebuffer = VK_NULL_HANDLE;

    auto cleanup_partial = [&]() {
        if (newFramebuffer != VK_NULL_HANDLE)
            vkDestroyFramebuffer(m_device, newFramebuffer, nullptr);
        if (newView != VK_NULL_HANDLE)
            vkDestroyImageView(m_device, newView, nullptr);
        if (newImage != VK_NULL_HANDLE)
            vkDestroyImage(m_device, newImage, nullptr);
        if (newMemory != VK_NULL_HANDLE)
            vkFreeMemory(m_device, newMemory, nullptr);
    };

    // Create color image
    VkImageCreateInfo imageInfo = {};
    imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
    imageInfo.imageType = VK_IMAGE_TYPE_2D;
    imageInfo.format = VK_FORMAT_R8G8B8A8_UNORM;
    imageInfo.extent = { (uint32_t)width, (uint32_t)height, 1 };
    imageInfo.mipLevels = 1;
    imageInfo.arrayLayers = 1;
    imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
    imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
    imageInfo.usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT;
    imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;

#if OMNIUI_HAS_CUDA
    // Mark image memory as exportable for CUDA interop
    VkExternalMemoryImageCreateInfo extMemImageInfo = {};
    extMemImageInfo.sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO;
#if defined(_WIN32)
    extMemImageInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;
#else
    extMemImageInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;
#endif
    imageInfo.pNext = &extMemImageInfo;
#endif

    VkResult err = vkCreateImage(m_device, &imageInfo, nullptr, &newImage);
    if (err != VK_SUCCESS) { cleanup_partial(); return false; }

    VkMemoryRequirements memReqs;
    vkGetImageMemoryRequirements(m_device, newImage, &memReqs);

    VkMemoryAllocateInfo allocInfo = {};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.allocationSize = memReqs.size;
    allocInfo.memoryTypeIndex = findMemoryType(memReqs.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
    if (allocInfo.memoryTypeIndex == UINT32_MAX) { cleanup_partial(); return false; }

#if OMNIUI_HAS_CUDA
    // Enable memory export for CUDA interop
    VkExportMemoryAllocateInfo exportAllocInfo = {};
    exportAllocInfo.sType = VK_STRUCTURE_TYPE_EXPORT_MEMORY_ALLOCATE_INFO;
#if defined(_WIN32)
    exportAllocInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_WIN32_BIT;
#else
    exportAllocInfo.handleTypes = VK_EXTERNAL_MEMORY_HANDLE_TYPE_OPAQUE_FD_BIT;
#endif
    allocInfo.pNext = &exportAllocInfo;
#endif

    err = vkAllocateMemory(m_device, &allocInfo, nullptr, &newMemory);
    if (err != VK_SUCCESS) { cleanup_partial(); return false; }
    newMemorySize = memReqs.size;

    err = vkBindImageMemory(m_device, newImage, newMemory, 0);
    if (err != VK_SUCCESS) { cleanup_partial(); return false; }

    // Image view
    VkImageViewCreateInfo viewInfo = {};
    viewInfo.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
    viewInfo.image = newImage;
    viewInfo.viewType = VK_IMAGE_VIEW_TYPE_2D;
    viewInfo.format = VK_FORMAT_R8G8B8A8_UNORM;
    viewInfo.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    viewInfo.subresourceRange.levelCount = 1;
    viewInfo.subresourceRange.layerCount = 1;
    err = vkCreateImageView(m_device, &viewInfo, nullptr, &newView);
    if (err != VK_SUCCESS) { cleanup_partial(); return false; }

    // Framebuffer
    VkFramebufferCreateInfo fbInfo = {};
    fbInfo.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO;
    fbInfo.renderPass = m_renderPass;
    fbInfo.attachmentCount = 1;
    fbInfo.pAttachments = &newView;
    fbInfo.width = width;
    fbInfo.height = height;
    fbInfo.layers = 1;
    err = vkCreateFramebuffer(m_device, &fbInfo, nullptr, &newFramebuffer);
    if (err != VK_SUCCESS) { cleanup_partial(); return false; }

    // Everything succeeded — destroy the old framebuffer and commit
    // the new one atomically. Order matches ``destroyFramebuffer``'s
    // top-down dependency teardown.
    destroyFramebuffer();
    m_colorImage      = newImage;
    m_colorMemory     = newMemory;
    m_colorMemorySize = newMemorySize;
    m_colorView       = newView;
    m_framebuffer     = newFramebuffer;
    m_fbWidth         = width;
    m_fbHeight        = height;
    return true;
}

void VulkanBackend::destroyFramebuffer()
{
    if (m_device == VK_NULL_HANDLE) return;
    if (m_framebuffer) { vkDestroyFramebuffer(m_device, m_framebuffer, nullptr); m_framebuffer = VK_NULL_HANDLE; }
    if (m_colorView)   { vkDestroyImageView(m_device, m_colorView, nullptr);     m_colorView = VK_NULL_HANDLE; }
    if (m_colorImage)  { vkDestroyImage(m_device, m_colorImage, nullptr);        m_colorImage = VK_NULL_HANDLE; }
    if (m_colorMemory) { vkFreeMemory(m_device, m_colorMemory, nullptr);         m_colorMemory = VK_NULL_HANDLE; }
}

// ---------------------------------------------------------------------------
// ImGui integration
// ---------------------------------------------------------------------------

bool VulkanBackend::initImGui()
{
    ImGui_ImplVulkan_InitInfo initInfo = {};
    initInfo.Instance = m_instance;
    initInfo.PhysicalDevice = m_physicalDevice;
    initInfo.Device = m_device;
    initInfo.QueueFamily = m_queueFamily;
    initInfo.Queue = m_queue;
    initInfo.PipelineCache = VK_NULL_HANDLE;
    initInfo.DescriptorPool = m_descriptorPool;
    initInfo.MinImageCount = 2;
    initInfo.ImageCount = 2;
    initInfo.PipelineInfoMain.MSAASamples = VK_SAMPLE_COUNT_1_BIT;
    initInfo.PipelineInfoMain.RenderPass = m_renderPass;
    initInfo.Allocator = nullptr;
    initInfo.CheckVkResultFn = vkCheckResult;

    // ImGui 1.92 moved RenderPass/MSAASamples into PipelineInfoMain and
    // removed the second render_pass parameter from ImGui_ImplVulkan_Init.
    if (!ImGui_ImplVulkan_Init(&initInfo))
    {
        fprintf(stderr, "VulkanBackend: ImGui_ImplVulkan_Init failed\n");
        return false;
    }

    // ImGui 1.92+: fonts are uploaded automatically the first time NewFrame() is
    // called; the old explicit CreateFontsTexture(cmdBuffer) + DestroyFontUploadObjects
    // helpers were removed. Nothing to do here now.

    m_imguiInitialized = true;
    fprintf(stdout, "VulkanBackend: ImGui Vulkan backend initialized\n");
    return true;
}

// ---------------------------------------------------------------------------
// Frame rendering
// ---------------------------------------------------------------------------

void VulkanBackend::beginFrame(int width, int height)
{
    // Recreate framebuffer if size changed. ``createFramebuffer`` is
    // transactional (Codex Step 3.7 review #2 fix): on failure the
    // existing framebuffer is left intact, so falling through to
    // submit at the prior extent is safe and avoids null-handle
    // rendering.
    if (width != m_fbWidth || height != m_fbHeight)
    {
        vkDeviceWaitIdle(m_device);
        if (!createFramebuffer(width, height))
        {
            fprintf(stderr,
                    "VulkanBackend::beginFrame: createFramebuffer(%d, %d) "
                    "failed; continuing at prior extent %dx%d\n",
                    width, height, m_fbWidth, m_fbHeight);
        }
    }

    vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX);
    vkResetFences(m_device, 1, &m_fence);

    vkResetCommandBuffer(m_commandBuffer, 0);

    VkCommandBufferBeginInfo beginInfo = {};
    beginInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    beginInfo.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    vkBeginCommandBuffer(m_commandBuffer, &beginInfo);

    VkClearValue clearValue = {};
    clearValue.color = {{0.12f, 0.13f, 0.14f, 1.0f}};

    VkRenderPassBeginInfo rpBegin = {};
    rpBegin.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
    rpBegin.renderPass = m_renderPass;
    rpBegin.framebuffer = m_framebuffer;
    rpBegin.renderArea.extent = { (uint32_t)m_fbWidth, (uint32_t)m_fbHeight };
    rpBegin.clearValueCount = 1;
    rpBegin.pClearValues = &clearValue;
    vkCmdBeginRenderPass(m_commandBuffer, &rpBegin, VK_SUBPASS_CONTENTS_INLINE);
}

void VulkanBackend::endFrame()
{
    vkCmdEndRenderPass(m_commandBuffer);
    vkEndCommandBuffer(m_commandBuffer);

    VkSubmitInfo submitInfo = {};
    submitInfo.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submitInfo.commandBufferCount = 1;
    submitInfo.pCommandBuffers = &m_commandBuffer;
    vkQueueSubmit(m_queue, 1, &submitInfo, m_fence);
}

// ---------------------------------------------------------------------------
// Readback
// ---------------------------------------------------------------------------

bool VulkanBackend::readbackPixels(uint8_t* outPixels, int width, int height)
{
    if (!m_device || !m_colorImage || !outPixels)
        return false;

    vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX);

    // Create a host-visible staging buffer
    VkDeviceSize bufferSize = (VkDeviceSize)width * height * 4;

    VkBufferCreateInfo bufInfo = {};
    bufInfo.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bufInfo.size = bufferSize;
    bufInfo.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    bufInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;

    VkBuffer stagingBuffer;
    VkResult err = vkCreateBuffer(m_device, &bufInfo, nullptr, &stagingBuffer);
    if (err != VK_SUCCESS) return false;

    VkMemoryRequirements memReqs;
    vkGetBufferMemoryRequirements(m_device, stagingBuffer, &memReqs);

    VkMemoryAllocateInfo allocInfo = {};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.allocationSize = memReqs.size;
    allocInfo.memoryTypeIndex = findMemoryType(memReqs.memoryTypeBits,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);

    VkDeviceMemory stagingMemory;
    err = vkAllocateMemory(m_device, &allocInfo, nullptr, &stagingMemory);
    if (err != VK_SUCCESS) { vkDestroyBuffer(m_device, stagingBuffer, nullptr); return false; }
    vkBindBufferMemory(m_device, stagingBuffer, stagingMemory, 0);

    // Record copy command
    VkCommandBufferBeginInfo beginInfo = {};
    beginInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    beginInfo.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;

    vkResetFences(m_device, 1, &m_fence);
    vkResetCommandBuffer(m_commandBuffer, 0);
    vkBeginCommandBuffer(m_commandBuffer, &beginInfo);

    // The image is already in TRANSFER_SRC_OPTIMAL from the render pass final layout
    VkBufferImageCopy region = {};
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.layerCount = 1;
    region.imageExtent = { (uint32_t)width, (uint32_t)height, 1 };
    vkCmdCopyImageToBuffer(m_commandBuffer, m_colorImage, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, stagingBuffer, 1, &region);

    vkEndCommandBuffer(m_commandBuffer);

    VkSubmitInfo submitInfo = {};
    submitInfo.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submitInfo.commandBufferCount = 1;
    submitInfo.pCommandBuffers = &m_commandBuffer;
    vkQueueSubmit(m_queue, 1, &submitInfo, m_fence);
    vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX);

    // Map and copy
    void* mapped = nullptr;
    err = vkMapMemory(m_device, stagingMemory, 0, bufferSize, 0, &mapped);
    if (err == VK_SUCCESS)
    {
        memcpy(outPixels, mapped, bufferSize);
        vkUnmapMemory(m_device, stagingMemory);
    }

    vkDestroyBuffer(m_device, stagingBuffer, nullptr);
    vkFreeMemory(m_device, stagingMemory, nullptr);

    return err == VK_SUCCESS;
}

void VulkanBackend::getFramebufferSize(int* width, int* height) const
{
    if (width)  *width = m_fbWidth;
    if (height) *height = m_fbHeight;
}

} // namespace standalone
} // namespace ui
} // namespace omni
