/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "VulkanBackend.h"


#include <imgui/imgui.h>
#include <imgui/backends/imgui_impl_vulkan.h>

#ifndef OMNIUI_HEADLESS_ONLY
#include <GLFW/glfw3.h>
#endif

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <algorithm>
#include <limits>

namespace omni {
namespace ui {
namespace standalone {

namespace {

constexpr uint32_t kPreferredSwapchainImageCount = 3;
constexpr uint32_t kDescriptorCapacity = 1024;
constexpr VkDeviceSize kMinImGuiAllocationSize = 1024 * 1024;
constexpr char kRenderFlowModeEnvironment[] = "OMNIUI_RENDER_FLOW_MODE";
constexpr char kFastRenderFlowMode[] = "fast";

} // namespace

struct VulkanBackend::FastWindowPresentation
{
    ImGui_ImplVulkanH_Window window = {};
    uint32_t minImageCount = 2;
    bool needsRebuild = false;
};

static void vkCheckResult(VkResult err)
{
    if (err != VK_SUCCESS)
        fprintf(stderr, "VulkanBackend: VkResult = %d\n", err);
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

VulkanBackend::VulkanBackend() = default;

VulkanBackend::~VulkanBackend()
{
    shutdown();
}

void VulkanBackend::deferRelease(std::function<void()> release)
{
    if (m_frameReleasesDeferred)
        m_deferredReleases.push_back(std::move(release));
    else
        release();
}

void VulkanBackend::beginFrameReleases()
{
    std::lock_guard<std::mutex> queueLock(m_queueMutex);
    m_frameReleasesDeferred = true;
}

void VulkanBackend::endFrameReleases()
{
    runDeferredReleases();
}

void VulkanBackend::runDeferredReleases()
{
    std::lock_guard<std::mutex> queueLock(m_queueMutex);
    m_frameReleasesDeferred = false;
    std::vector<std::function<void()>> releases;
    releases.swap(m_deferredReleases);
    for (auto& release : releases)
        release();
}

void VulkanBackend::shutdown()
{
    runDeferredReleases();
    m_frameHealthy = false;
    m_windowSurfaceActive = false;
    if (m_device != VK_NULL_HANDLE)
    {
        vkDeviceWaitIdle(m_device);
    }

    if (m_imguiInitialized)
    {
        ImGui_ImplVulkan_Shutdown();
        m_imguiInitialized = false;
    }

    destroyNativeFramePacingBase();
    destroyFastWindowPresentation();
    destroyFramebuffer();
    destroySwapchain();

    if (m_imageAvailable != VK_NULL_HANDLE)
    {
        vkDestroySemaphore(m_device, m_imageAvailable, nullptr);
        m_imageAvailable = VK_NULL_HANDLE;
    }
    for (VkSemaphore semaphore : m_renderFinishedSemaphores)
        if (semaphore != VK_NULL_HANDLE)
            vkDestroySemaphore(m_device, semaphore, nullptr);
    m_renderFinishedSemaphores.clear();

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
    if (m_overlayRenderPass != VK_NULL_HANDLE)
    {
        vkDestroyRenderPass(m_device, m_overlayRenderPass, nullptr);
        m_overlayRenderPass = VK_NULL_HANDLE;
    }
    if (m_device != VK_NULL_HANDLE)
    {
        vkDestroyDevice(m_device, nullptr);
        m_device = VK_NULL_HANDLE;
    }
    if (m_surface != VK_NULL_HANDLE)
    {
        vkDestroySurfaceKHR(m_instance, m_surface, nullptr);
        m_surface = VK_NULL_HANDLE;
    }
    if (m_instance != VK_NULL_HANDLE)
    {
        vkDestroyInstance(m_instance, nullptr);
        m_instance = VK_NULL_HANDLE;
    }
    m_glfwWindow = nullptr;
}

bool VulkanBackend::initHeadless(int width, int height)
{
    m_headless = true;
    return init(nullptr, width, height);
}

bool VulkanBackend::init(GLFWwindow* glfwWindow, int width, int height)
{
    m_headless = glfwWindow == nullptr;
    m_glfwWindow = glfwWindow;
    const char* renderFlowMode = std::getenv(kRenderFlowModeEnvironment);
    m_fastPresentationMode = false;
    if (renderFlowMode != nullptr && std::strcmp(renderFlowMode, kFastRenderFlowMode) == 0)
    {
        m_fastPresentationMode = true;
    }
    if (!createInstance())       return false;
    if (!m_headless && !createSurface()) return false;
    if (!selectPhysicalDevice()) return false;
    if (!createDevice())         return false;
    if (!createCommandPool())    return false;
    if (!createDescriptorPool()) return false;

    if (usesFastPresentationMode())
    {
        if (!createOrResizeFastWindowPresentation(width, height))
        {
            return false;
        }
        m_frameHealthy = true;
        m_windowSurfaceActive = true;
        fprintf(stdout, "VulkanBackend: initialized fast direct presentation (%dx%d)\n", width, height);
        return true;
    }

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

    if (!m_headless)
    {
        VkSemaphoreCreateInfo semaphoreInfo = {};
        semaphoreInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
        if (vkCreateSemaphore(m_device, &semaphoreInfo, nullptr, &m_imageAvailable) != VK_SUCCESS)
        {
            fprintf(stderr, "VulkanBackend: failed to create window presentation semaphores\n");
            return false;
        }
        if (!createSwapchain(width, height, false))
        {
            fprintf(stderr, "VulkanBackend: failed to create the GLFW Vulkan swapchain\n");
            return false;
        }
        m_windowSurfaceActive = true;
    }

    m_frameHealthy = true;
    const char* presentationMode = "windowed swapchain";
    if (m_headless)
    {
        presentationMode = "offscreen";
    }
    fprintf(stdout, "VulkanBackend: initialized successfully (%dx%d, %s)\n",
            width, height, presentationMode);
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

bool VulkanBackend::createSurface()
{
#ifdef OMNIUI_HEADLESS_ONLY
    fprintf(stderr, "VulkanBackend: GLFW Vulkan surfaces are unavailable in a headless-only build\n");
    return false;
#else
    if (!m_glfwWindow || m_instance == VK_NULL_HANDLE)
        return false;
    const VkResult result = glfwCreateWindowSurface(m_instance, m_glfwWindow, nullptr, &m_surface);
    if (result != VK_SUCCESS || m_surface == VK_NULL_HANDLE)
    {
        fprintf(stderr, "VulkanBackend: glfwCreateWindowSurface failed (%d)\n", result);
        m_surface = VK_NULL_HANDLE;
        return false;
    }
    fprintf(stdout, "VulkanBackend: created GLFW Vulkan window surface\n");
    return true;
#endif
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

    // Prefer a discrete GPU, but a windowed backend must choose a graphics
    // queue that can also present to this exact GLFW surface.  One shared queue
    // preserves the backend's existing external-serialization contract.
    m_physicalDevice = VK_NULL_HANDLE;
    m_queueFamily = UINT32_MAX;
    int bestScore = (std::numeric_limits<int>::min)();
    for (VkPhysicalDevice dev : devices)
    {
        VkPhysicalDeviceProperties props;
        vkGetPhysicalDeviceProperties(dev, &props);

        uint32_t qfCount = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(dev, &qfCount, nullptr);
        std::vector<VkQueueFamilyProperties> qfProps(qfCount);
        vkGetPhysicalDeviceQueueFamilyProperties(dev, &qfCount, qfProps.data());
        uint32_t compatibleFamily = UINT32_MAX;
        for (uint32_t i = 0; i < qfCount; ++i)
        {
            if (!(qfProps[i].queueFlags & VK_QUEUE_GRAPHICS_BIT))
                continue;
            VkBool32 canPresent = VK_TRUE;
            if (m_surface != VK_NULL_HANDLE &&
                vkGetPhysicalDeviceSurfaceSupportKHR(dev, i, m_surface, &canPresent) != VK_SUCCESS)
                canPresent = VK_FALSE;
            if (canPresent)
            {
                compatibleFamily = i;
                break;
            }
        }
        if (compatibleFamily == UINT32_MAX)
            continue;

        const int score = props.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU ? 100 :
                          props.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU ? 50 : 0;
        if (score > bestScore)
        {
            bestScore = score;
            m_physicalDevice = dev;
            m_queueFamily = compatibleFamily;
            m_queueFamilyQueueCount = qfProps[compatibleFamily].queueCount;
        }
    }

    if (m_physicalDevice == VK_NULL_HANDLE || m_queueFamily == UINT32_MAX)
    {
        fprintf(stderr, "VulkanBackend: no graphics queue can present to the GLFW surface\n");
        return false;
    }
    if (!m_headless && m_queueFamilyQueueCount < 2)
    {
        fprintf(stderr,
                "VulkanBackend: windowed native output requires independent graphics and present queues\n");
        return false;
    }

    VkPhysicalDeviceProperties selectedProps;
    vkGetPhysicalDeviceProperties(m_physicalDevice, &selectedProps);
    m_isSoftwareDevice = (selectedProps.deviceType == VK_PHYSICAL_DEVICE_TYPE_CPU);
    fprintf(stdout, "VulkanBackend: selected device: \"%s\" (vendorID=0x%04X, type=%s)\n",
            selectedProps.deviceName, selectedProps.vendorID, deviceTypeStr(selectedProps.deviceType));

    return true;
}

// ---------------------------------------------------------------------------
// Logical device
// ---------------------------------------------------------------------------

bool VulkanBackend::createDevice()
{
    const float queuePriorities[] = {1.0f, 1.0f};
    VkDeviceQueueCreateInfo queueInfo = {};
    queueInfo.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    queueInfo.queueFamilyIndex = m_queueFamily;
    queueInfo.queueCount = m_headless ? 1u : 2u;
    queueInfo.pQueuePriorities = queuePriorities;

    std::vector<const char*> deviceExtensions;

    if (!m_headless)
        deviceExtensions.push_back(VK_KHR_SWAPCHAIN_EXTENSION_NAME);

#if OMNIUI_HAS_CUDA
    // External memory extensions for CUDA interop. Software devices such as
    // Lavapipe may not advertise all of them; requesting a missing one makes
    // vkCreateDevice fail, so interop is only enabled when every one is present.
    const char* const interopExtensions[] = {
        VK_KHR_EXTERNAL_MEMORY_EXTENSION_NAME,
        VK_KHR_EXTERNAL_SEMAPHORE_EXTENSION_NAME,
#if defined(_WIN32)
        VK_KHR_EXTERNAL_MEMORY_WIN32_EXTENSION_NAME,
        VK_KHR_EXTERNAL_SEMAPHORE_WIN32_EXTENSION_NAME,
#else
        VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME,
        VK_KHR_EXTERNAL_SEMAPHORE_FD_EXTENSION_NAME,
#endif
        // Timeline semaphore support (optional, checked at runtime)
        VK_KHR_TIMELINE_SEMAPHORE_EXTENSION_NAME,
    };
    uint32_t availableCount = 0;
    vkEnumerateDeviceExtensionProperties(m_physicalDevice, nullptr, &availableCount, nullptr);
    std::vector<VkExtensionProperties> available(availableCount);
    vkEnumerateDeviceExtensionProperties(m_physicalDevice, nullptr, &availableCount, available.data());
    const char* missingExtension = nullptr;
    for (const char* name : interopExtensions)
    {
        bool found = false;
        for (const VkExtensionProperties& ext : available)
        {
            if (strcmp(ext.extensionName, name) == 0)
            {
                found = true;
                break;
            }
        }
        if (!found)
        {
            missingExtension = name;
            break;
        }
    }
    m_hasExternalMemory = (missingExtension == nullptr);
    if (m_hasExternalMemory)
    {
        deviceExtensions.insert(deviceExtensions.end(), std::begin(interopExtensions), std::end(interopExtensions));
        // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
        fprintf(stdout, "VulkanBackend: enabling external memory/semaphore extensions for CUDA interop\n");
    }
    else if (!m_headless)
    {
        // Windowed mode keeps the previous behaviour: fail here so the default
        // backend policy falls back to OpenGL, which still supports OpenGL
        // scene views. Running windowed Vulkan without interop would not.
        // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
        fprintf(stderr, "VulkanBackend: device does not support %s, required for CUDA interop in windowed mode\n",
                missingExtension);
        return false;
    }
    else
    {
        // logging: allow printf - standalone backend is carb-free; no OMNI_LOG/Carbonite channel is available here
        fprintf(stdout, "VulkanBackend: device does not support %s, CUDA interop disabled\n", missingExtension);
    }
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
    if (m_hasExternalMemory && timelineFeatures.timelineSemaphore == VK_TRUE)
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
    if (!m_headless)
        vkGetDeviceQueue(m_device, m_queueFamily, 1, &m_presentQueue);

    return true;
}

// ---------------------------------------------------------------------------
// Window surface / swapchain
// ---------------------------------------------------------------------------

bool VulkanBackend::createSwapchain(int width, int height, bool recreation)
{
    if (m_headless || m_surface == VK_NULL_HANDLE || m_device == VK_NULL_HANDLE ||
        width <= 0 || height <= 0)
        return false;

    VkSurfaceCapabilitiesKHR capabilities{};
    if (vkGetPhysicalDeviceSurfaceCapabilitiesKHR(
            m_physicalDevice, m_surface, &capabilities) != VK_SUCCESS)
        return false;
    if (!(capabilities.supportedUsageFlags & VK_IMAGE_USAGE_TRANSFER_DST_BIT))
    {
        fprintf(stderr, "VulkanBackend: window surface cannot receive a transfer image\n");
        return false;
    }

    uint32_t formatCount = 0;
    if (vkGetPhysicalDeviceSurfaceFormatsKHR(
            m_physicalDevice, m_surface, &formatCount, nullptr) != VK_SUCCESS || !formatCount)
        return false;
    std::vector<VkSurfaceFormatKHR> formats(formatCount);
    if (vkGetPhysicalDeviceSurfaceFormatsKHR(
            m_physicalDevice, m_surface, &formatCount, formats.data()) != VK_SUCCESS)
        return false;

    VkSurfaceFormatKHR selectedFormat = formats[0];
    const VkFormat preferredFormats[] = {
        VK_FORMAT_R8G8B8A8_UNORM,
        VK_FORMAT_B8G8R8A8_UNORM,
        VK_FORMAT_R8G8B8A8_SRGB,
        VK_FORMAT_B8G8R8A8_SRGB,
    };
    for (VkFormat preferred : preferredFormats)
    {
        const auto it = std::find_if(formats.begin(), formats.end(), [preferred](const VkSurfaceFormatKHR& value) {
            return value.format == preferred;
        });
        if (it != formats.end())
        {
            selectedFormat = *it;
            break;
        }
    }

    uint32_t presentModeCount = 0;
    if (vkGetPhysicalDeviceSurfacePresentModesKHR(
            m_physicalDevice, m_surface, &presentModeCount, nullptr) != VK_SUCCESS || !presentModeCount)
        return false;
    std::vector<VkPresentModeKHR> presentModes(presentModeCount);
    if (vkGetPhysicalDeviceSurfacePresentModesKHR(
            m_physicalDevice, m_surface, &presentModeCount, presentModes.data()) != VK_SUCCESS)
        return false;
    VkPresentModeKHR presentMode = VK_PRESENT_MODE_FIFO_KHR;
    if (std::find(presentModes.begin(), presentModes.end(), VK_PRESENT_MODE_IMMEDIATE_KHR) != presentModes.end())
        presentMode = VK_PRESENT_MODE_IMMEDIATE_KHR;
    else if (std::find(presentModes.begin(), presentModes.end(), VK_PRESENT_MODE_MAILBOX_KHR) != presentModes.end())
        presentMode = VK_PRESENT_MODE_MAILBOX_KHR;

    VkExtent2D extent{};
    if (capabilities.currentExtent.width != (std::numeric_limits<uint32_t>::max)())
        extent = capabilities.currentExtent;
    else
    {
        extent.width = std::clamp(
            static_cast<uint32_t>(width), capabilities.minImageExtent.width, capabilities.maxImageExtent.width);
        extent.height = std::clamp(
            static_cast<uint32_t>(height), capabilities.minImageExtent.height, capabilities.maxImageExtent.height);
    }
    if (!extent.width || !extent.height)
        return false;

    uint32_t imageCount = capabilities.minImageCount + 1;
    if (capabilities.maxImageCount && imageCount > capabilities.maxImageCount)
        imageCount = capabilities.maxImageCount;

    VkCompositeAlphaFlagBitsKHR compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    if (!(capabilities.supportedCompositeAlpha & compositeAlpha))
    {
        const VkCompositeAlphaFlagBitsKHR candidates[] = {
            VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR,
            VK_COMPOSITE_ALPHA_POST_MULTIPLIED_BIT_KHR,
            VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR,
        };
        for (VkCompositeAlphaFlagBitsKHR candidate : candidates)
        {
            if (capabilities.supportedCompositeAlpha & candidate)
            {
                compositeAlpha = candidate;
                break;
            }
        }
    }

    VkSwapchainCreateInfoKHR createInfo{};
    createInfo.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR;
    createInfo.surface = m_surface;
    createInfo.minImageCount = imageCount;
    createInfo.imageFormat = selectedFormat.format;
    createInfo.imageColorSpace = selectedFormat.colorSpace;
    createInfo.imageExtent = extent;
    createInfo.imageArrayLayers = 1;
    createInfo.imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT;
    createInfo.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
    createInfo.preTransform = capabilities.currentTransform;
    createInfo.compositeAlpha = compositeAlpha;
    createInfo.presentMode = presentMode;
    createInfo.clipped = VK_TRUE;
    createInfo.oldSwapchain = m_swapchain;

    VkSwapchainKHR newSwapchain = VK_NULL_HANDLE;
    VkResult result = vkCreateSwapchainKHR(m_device, &createInfo, nullptr, &newSwapchain);
    if (result != VK_SUCCESS)
    {
        fprintf(stderr, "VulkanBackend: vkCreateSwapchainKHR failed (%d)\n", result);
        return false;
    }

    uint32_t actualImageCount = 0;
    result = vkGetSwapchainImagesKHR(m_device, newSwapchain, &actualImageCount, nullptr);
    std::vector<VkImage> newImages(actualImageCount);
    if (result != VK_SUCCESS || !actualImageCount ||
        vkGetSwapchainImagesKHR(m_device, newSwapchain, &actualImageCount, newImages.data()) != VK_SUCCESS)
    {
        vkDestroySwapchainKHR(m_device, newSwapchain, nullptr);
        return false;
    }

    bool useBlit = selectedFormat.format != VK_FORMAT_R8G8B8A8_UNORM ||
                   extent.width != static_cast<uint32_t>(m_fbWidth) ||
                   extent.height != static_cast<uint32_t>(m_fbHeight);
    if (useBlit)
    {
        VkFormatProperties sourceProperties{};
        VkFormatProperties destinationProperties{};
        vkGetPhysicalDeviceFormatProperties(
            m_physicalDevice, VK_FORMAT_R8G8B8A8_UNORM, &sourceProperties);
        vkGetPhysicalDeviceFormatProperties(
            m_physicalDevice, selectedFormat.format, &destinationProperties);
        if (!(sourceProperties.optimalTilingFeatures & VK_FORMAT_FEATURE_BLIT_SRC_BIT) ||
            !(destinationProperties.optimalTilingFeatures & VK_FORMAT_FEATURE_BLIT_DST_BIT))
        {
            fprintf(stderr, "VulkanBackend: swapchain format %d cannot receive the offscreen image\n",
                    selectedFormat.format);
            vkDestroySwapchainKHR(m_device, newSwapchain, nullptr);
            return false;
        }
    }

    std::vector<VkSemaphore> newRenderFinished(actualImageCount, VK_NULL_HANDLE);
    VkSemaphoreCreateInfo semaphoreInfo{};
    semaphoreInfo.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
    for (VkSemaphore& semaphore : newRenderFinished)
    {
        if (vkCreateSemaphore(m_device, &semaphoreInfo, nullptr, &semaphore) != VK_SUCCESS)
        {
            for (VkSemaphore created : newRenderFinished)
                if (created != VK_NULL_HANDLE)
                    vkDestroySemaphore(m_device, created, nullptr);
            vkDestroySwapchainKHR(m_device, newSwapchain, nullptr);
            return false;
        }
    }

    if (m_swapchain != VK_NULL_HANDLE)
        vkDestroySwapchainKHR(m_device, m_swapchain, nullptr);
    for (VkSemaphore semaphore : m_renderFinishedSemaphores)
        if (semaphore != VK_NULL_HANDLE)
            vkDestroySemaphore(m_device, semaphore, nullptr);
    m_swapchain = newSwapchain;
    m_swapchainImages = std::move(newImages);
    m_renderFinishedSemaphores = std::move(newRenderFinished);
    m_swapchainFormat = selectedFormat.format;
    m_swapchainExtent = extent;
    m_swapchainUsesBlit = useBlit;
    m_swapchainNeedsRecreate = false;
    m_swapchainWidth = extent.width;
    m_swapchainHeight = extent.height;
    m_windowPresentMode = static_cast<int32_t>(presentMode);
    if (recreation)
        ++m_swapchainRecreations;
    fprintf(stdout,
            "VulkanBackend: %s GLFW swapchain (%ux%u, images=%u, format=%d, present=%s)\n",
            recreation ? "recreated" : "created", extent.width, extent.height,
            actualImageCount, selectedFormat.format,
            presentMode == VK_PRESENT_MODE_IMMEDIATE_KHR ? "IMMEDIATE" :
            presentMode == VK_PRESENT_MODE_MAILBOX_KHR ? "MAILBOX" : "FIFO");
    return true;
}

void VulkanBackend::destroySwapchain()
{
    if (m_device != VK_NULL_HANDLE && m_swapchain != VK_NULL_HANDLE)
        vkDestroySwapchainKHR(m_device, m_swapchain, nullptr);
    m_swapchain = VK_NULL_HANDLE;
    m_swapchainImages.clear();
    m_swapchainFormat = VK_FORMAT_UNDEFINED;
    m_swapchainExtent = {};
    m_swapchainNeedsRecreate = false;
    m_swapchainUsesBlit = false;
    m_swapchainWidth = 0;
    m_swapchainHeight = 0;
    m_windowPresentMode = -1;
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
        { VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, kDescriptorCapacity },
    };
    VkDescriptorPoolCreateInfo poolInfo = {};
    poolInfo.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO;
    poolInfo.flags = VK_DESCRIPTOR_POOL_CREATE_FREE_DESCRIPTOR_SET_BIT;
    poolInfo.maxSets = kDescriptorCapacity;
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

    VkSubpassDependency dependencies[2] = {};
    dependencies[0].srcSubpass = VK_SUBPASS_EXTERNAL;
    dependencies[0].dstSubpass = 0;
    dependencies[0].srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dependencies[0].dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dependencies[0].srcAccessMask = 0;
    dependencies[0].dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    dependencies[1].srcSubpass = 0;
    dependencies[1].dstSubpass = VK_SUBPASS_EXTERNAL;
    dependencies[1].srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dependencies[1].dstStageMask = VK_PIPELINE_STAGE_TRANSFER_BIT;
    dependencies[1].srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    dependencies[1].dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;

    VkRenderPassCreateInfo rpInfo = {};
    rpInfo.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    rpInfo.attachmentCount = 1;
    rpInfo.pAttachments = &colorAttachment;
    rpInfo.subpassCount = 1;
    rpInfo.pSubpasses = &subpass;
    rpInfo.dependencyCount = 2;
    rpInfo.pDependencies = dependencies;

    VkResult err = vkCreateRenderPass(m_device, &rpInfo, nullptr, &m_renderPass);
    if (err != VK_SUCCESS)
        return false;

    // Compatible pass for presenter overlays. The UI thread periodically
    // redraws the complete interface with every live descriptor. Between those
    // ticks the native presenter LOADs that image and replaces only the paced
    // viewport/safe saved commands, preserving external icon/image pixels whose
    // providers cannot be retained across Python generations.
    colorAttachment.loadOp = VK_ATTACHMENT_LOAD_OP_LOAD;
    colorAttachment.initialLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    rpInfo.pAttachments = &colorAttachment;
    dependencies[0].srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT |
                                   VK_PIPELINE_STAGE_TRANSFER_BIT;
    dependencies[0].dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dependencies[0].srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT |
                                    VK_ACCESS_TRANSFER_READ_BIT |
                                    VK_ACCESS_TRANSFER_WRITE_BIT;
    dependencies[0].dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_READ_BIT |
                                    VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    err = vkCreateRenderPass(m_device, &rpInfo, nullptr, &m_overlayRenderPass);
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
    imageInfo.usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT |
                      VK_IMAGE_USAGE_TRANSFER_SRC_BIT |
                      VK_IMAGE_USAGE_TRANSFER_DST_BIT;
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
    if (m_hasExternalMemory)
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
    if (m_hasExternalMemory)
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

void VulkanBackend::destroyNativeFramePacingBase()
{
    if (m_device == VK_NULL_HANDLE)
        return;
    if (m_framePacingBaseImage)
    {
        vkDestroyImage(m_device, m_framePacingBaseImage, nullptr);
        m_framePacingBaseImage = VK_NULL_HANDLE;
    }
    if (m_framePacingBaseMemory)
    {
        vkFreeMemory(m_device, m_framePacingBaseMemory, nullptr);
        m_framePacingBaseMemory = VK_NULL_HANDLE;
    }
    m_framePacingBaseWidth = 0;
    m_framePacingBaseHeight = 0;
}

void VulkanBackend::releaseNativeFramePacingBase()
{
    destroyNativeFramePacingBase();
}

bool VulkanBackend::createOrResizeFastWindowPresentation(int width, int height)
{
    if (width <= 0 || height <= 0 || m_surface == VK_NULL_HANDLE)
    {
        return false;
    }

    if (!m_fastWindowPresentation)
    {
        m_fastWindowPresentation = std::make_unique<FastWindowPresentation>();
        ImGui_ImplVulkanH_Window& window = m_fastWindowPresentation->window;
        window.Surface = m_surface;

        const VkFormat requestedFormats[] = {
            VK_FORMAT_B8G8R8A8_UNORM,
            VK_FORMAT_R8G8B8A8_UNORM,
        };
        window.SurfaceFormat = ImGui_ImplVulkanH_SelectSurfaceFormat(
            m_physicalDevice,
            m_surface,
            requestedFormats,
            static_cast<int>(sizeof(requestedFormats) / sizeof(requestedFormats[0])),
            VK_COLOR_SPACE_SRGB_NONLINEAR_KHR);

        const VkPresentModeKHR requestedPresentModes[] = {
            VK_PRESENT_MODE_MAILBOX_KHR,
            VK_PRESENT_MODE_FIFO_KHR,
        };
        window.PresentMode = ImGui_ImplVulkanH_SelectPresentMode(
            m_physicalDevice,
            m_surface,
            requestedPresentModes,
            static_cast<int>(sizeof(requestedPresentModes) / sizeof(requestedPresentModes[0])));
        window.ClearValue.color = { { 0.12f, 0.13f, 0.14f, 1.0f } };
    }

    ImGui_ImplVulkanH_Window& window = m_fastWindowPresentation->window;
    ImGui_ImplVulkanH_CreateOrResizeWindow(
        m_instance,
        m_physicalDevice,
        m_device,
        &window,
        m_queueFamily,
        nullptr,
        width,
        height,
        kPreferredSwapchainImageCount,
        VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT);

    if (window.Swapchain == VK_NULL_HANDLE || window.ImageCount == 0)
    {
        return false;
    }

    m_fastWindowPresentation->minImageCount = window.ImageCount;
    if (m_fastWindowPresentation->minImageCount > kPreferredSwapchainImageCount)
    {
        m_fastWindowPresentation->minImageCount = kPreferredSwapchainImageCount;
    }
    if (m_fastWindowPresentation->minImageCount < 2)
    {
        m_fastWindowPresentation->minImageCount = 2;
    }
    m_fastWindowPresentation->needsRebuild = false;
    m_fbWidth = window.Width;
    m_fbHeight = window.Height;
    m_swapchainWidth = static_cast<uint32_t>(window.Width);
    m_swapchainHeight = static_cast<uint32_t>(window.Height);
    m_windowPresentMode = static_cast<int32_t>(window.PresentMode);
    return true;
}

void VulkanBackend::destroyFastWindowPresentation()
{
    if (!m_fastWindowPresentation)
    {
        return;
    }
    if (m_device != VK_NULL_HANDLE)
    {
        ImGui_ImplVulkanH_DestroyWindow(
            m_instance,
            m_device,
            &m_fastWindowPresentation->window,
            nullptr);
    }
    m_fastWindowPresentation.reset();
    m_fastActiveCommandBuffer = VK_NULL_HANDLE;
    m_fastFrameReady = false;
}

// ---------------------------------------------------------------------------
// ImGui integration
// ---------------------------------------------------------------------------

bool VulkanBackend::initImGui()
{
    uint32_t minImageCount = 2;
    uint32_t imageCount = 2;
    VkRenderPass renderPass = m_renderPass;
    if (usesFastPresentationMode())
    {
        if (!m_fastWindowPresentation)
        {
            return false;
        }
        renderPass = m_fastWindowPresentation->window.RenderPass;
        minImageCount = m_fastWindowPresentation->minImageCount;
        imageCount = m_fastWindowPresentation->window.ImageCount;
    }
    ImGui_ImplVulkan_InitInfo initInfo = {};
    initInfo.Instance = m_instance;
    initInfo.PhysicalDevice = m_physicalDevice;
    initInfo.Device = m_device;
    initInfo.QueueFamily = m_queueFamily;
    initInfo.Queue = m_queue;
    initInfo.PipelineCache = VK_NULL_HANDLE;
    initInfo.DescriptorPool = m_descriptorPool;
    initInfo.MinImageCount = minImageCount;
    initInfo.ImageCount = imageCount;
    initInfo.PipelineInfoMain.MSAASamples = VK_SAMPLE_COUNT_1_BIT;
    initInfo.PipelineInfoMain.RenderPass = renderPass;
    initInfo.Allocator = nullptr;
    initInfo.CheckVkResultFn = vkCheckResult;
    initInfo.MinAllocationSize = kMinImGuiAllocationSize;

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

bool VulkanBackend::beginFastFrame(int width, int height)
{
    m_fastFrameReady = false;
    m_fastActiveCommandBuffer = VK_NULL_HANDLE;
    if (width <= 0 || height <= 0 || !m_fastWindowPresentation)
    {
        return false;
    }

    ImGui_ImplVulkanH_Window& window = m_fastWindowPresentation->window;
    if (
        m_fastWindowPresentation->needsRebuild
        || width != window.Width
        || height != window.Height
    )
    {
        if (!createOrResizeFastWindowPresentation(width, height))
        {
            return false;
        }
    }

    ImGui_ImplVulkanH_FrameSemaphores& semaphores =
        window.FrameSemaphores[window.SemaphoreIndex];
    VkResult acquireResult = vkAcquireNextImageKHR(
        m_device,
        window.Swapchain,
        UINT64_MAX,
        semaphores.ImageAcquiredSemaphore,
        VK_NULL_HANDLE,
        &window.FrameIndex);
    if (acquireResult == VK_ERROR_OUT_OF_DATE_KHR)
    {
        m_fastWindowPresentation->needsRebuild = true;
        return false;
    }
    if (acquireResult == VK_SUBOPTIMAL_KHR)
    {
        m_fastWindowPresentation->needsRebuild = true;
    }
    else if (acquireResult != VK_SUCCESS)
    {
        vkCheckResult(acquireResult);
        return false;
    }

    ImGui_ImplVulkanH_Frame& frame = window.Frames[window.FrameIndex];
    if (vkWaitForFences(m_device, 1, &frame.Fence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
    {
        return false;
    }
    if (vkResetCommandPool(m_device, frame.CommandPool, 0) != VK_SUCCESS)
    {
        return false;
    }

    VkCommandBufferBeginInfo beginInfo = {};
    beginInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    beginInfo.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    if (vkBeginCommandBuffer(frame.CommandBuffer, &beginInfo) != VK_SUCCESS)
    {
        return false;
    }

    ImVec4 background = ImGui::GetStyleColorVec4(ImGuiCol_WindowBg);
    window.ClearValue.color = {
        { background.x, background.y, background.z, background.w }
    };

    VkRenderPassBeginInfo renderPassBegin = {};
    renderPassBegin.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
    renderPassBegin.renderPass = window.RenderPass;
    renderPassBegin.framebuffer = frame.Framebuffer;
    renderPassBegin.renderArea.extent = {
        static_cast<uint32_t>(window.Width),
        static_cast<uint32_t>(window.Height),
    };
    renderPassBegin.clearValueCount = 1;
    renderPassBegin.pClearValues = &window.ClearValue;
    vkCmdBeginRenderPass(
        frame.CommandBuffer,
        &renderPassBegin,
        VK_SUBPASS_CONTENTS_INLINE);

    m_fastActiveCommandBuffer = frame.CommandBuffer;
    m_fastFrameReady = true;
    return true;
}

bool VulkanBackend::endFastFrame()
{
    if (!m_fastFrameReady || !m_fastWindowPresentation)
    {
        return false;
    }

    ImGui_ImplVulkanH_Window& window = m_fastWindowPresentation->window;
    ImGui_ImplVulkanH_Frame& frame = window.Frames[window.FrameIndex];
    ImGui_ImplVulkanH_FrameSemaphores& semaphores =
        window.FrameSemaphores[window.SemaphoreIndex];

    vkCmdEndRenderPass(frame.CommandBuffer);
    if (vkEndCommandBuffer(frame.CommandBuffer) != VK_SUCCESS)
    {
        m_fastFrameReady = false;
        m_fastActiveCommandBuffer = VK_NULL_HANDLE;
        return false;
    }

    const VkPipelineStageFlags waitStage =
        VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    VkSubmitInfo submitInfo = {};
    submitInfo.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submitInfo.waitSemaphoreCount = 1;
    submitInfo.pWaitSemaphores = &semaphores.ImageAcquiredSemaphore;
    submitInfo.pWaitDstStageMask = &waitStage;
    submitInfo.commandBufferCount = 1;
    submitInfo.pCommandBuffers = &frame.CommandBuffer;
    submitInfo.signalSemaphoreCount = 1;
    submitInfo.pSignalSemaphores = &semaphores.RenderCompleteSemaphore;

    if (vkResetFences(m_device, 1, &frame.Fence) != VK_SUCCESS)
    {
        m_fastFrameReady = false;
        m_fastActiveCommandBuffer = VK_NULL_HANDLE;
        return false;
    }
    if (vkQueueSubmit(m_queue, 1, &submitInfo, frame.Fence) != VK_SUCCESS)
    {
        m_fastFrameReady = false;
        m_fastActiveCommandBuffer = VK_NULL_HANDLE;
        return false;
    }

    VkPresentInfoKHR presentInfo = {};
    presentInfo.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
    presentInfo.waitSemaphoreCount = 1;
    presentInfo.pWaitSemaphores = &semaphores.RenderCompleteSemaphore;
    presentInfo.swapchainCount = 1;
    presentInfo.pSwapchains = &window.Swapchain;
    presentInfo.pImageIndices = &window.FrameIndex;

    VkResult presentResult = vkQueuePresentKHR(m_queue, &presentInfo);
    if (
        presentResult == VK_ERROR_OUT_OF_DATE_KHR
        || presentResult == VK_SUBOPTIMAL_KHR
    )
    {
        m_fastWindowPresentation->needsRebuild = true;
    }
    else if (presentResult != VK_SUCCESS)
    {
        vkCheckResult(presentResult);
        m_fastFrameReady = false;
        m_fastActiveCommandBuffer = VK_NULL_HANDLE;
        return false;
    }

    window.SemaphoreIndex =
        (window.SemaphoreIndex + 1) % window.SemaphoreCount;
    ++m_windowPresentCount;
    m_fastFrameReady = false;
    m_fastActiveCommandBuffer = VK_NULL_HANDLE;
    return true;
}

bool VulkanBackend::beginFrame(int width, int height, bool preserve, bool waitForPrevious)
{
    if (usesFastPresentationMode())
    {
        return beginFastFrame(width, height);
    }
    if (!m_frameHealthy || m_device == VK_NULL_HANDLE || m_fence == VK_NULL_HANDLE ||
        m_commandBuffer == VK_NULL_HANDLE || m_framebuffer == VK_NULL_HANDLE)
    {
        return false;
    }
    if (width <= 0 || height <= 0)
    {
        return false;
    }

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

    uint64_t fenceTimeout = 0;
    if (waitForPrevious)
    {
        fenceTimeout = UINT64_MAX;
    }
    VkResult fenceResult = VK_SUCCESS;
    {
        fenceResult = vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, fenceTimeout);
    }
    if (!waitForPrevious && fenceResult == VK_TIMEOUT)
    {
        ++m_windowPresentDeferrals;
        return false;
    }
    if (fenceResult != VK_SUCCESS || vkResetFences(m_device, 1, &m_fence) != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return false;
    }

    if (vkResetCommandBuffer(m_commandBuffer, 0) != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return false;
    }

    VkCommandBufferBeginInfo beginInfo = {};
    beginInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    beginInfo.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    if (vkBeginCommandBuffer(m_commandBuffer, &beginInfo) != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return false;
    }

    VkClearValue clearValue = {};
    clearValue.color = { { 0.12f, 0.13f, 0.14f, 1.0f } };

    VkRenderPassBeginInfo rpBegin = {};
    rpBegin.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
    if (preserve)
    {
        rpBegin.renderPass = m_overlayRenderPass;
        rpBegin.clearValueCount = 0;
        rpBegin.pClearValues = nullptr;
    }
    else
    {
        rpBegin.renderPass = m_renderPass;
        rpBegin.clearValueCount = 1;
        rpBegin.pClearValues = &clearValue;
    }
    rpBegin.framebuffer = m_framebuffer;
    rpBegin.renderArea.extent = { static_cast<uint32_t>(m_fbWidth), static_cast<uint32_t>(m_fbHeight) };
    vkCmdBeginRenderPass(m_commandBuffer, &rpBegin, VK_SUBPASS_CONTENTS_INLINE);
    return true;
}

bool VulkanBackend::endFrame()
{
    if (usesFastPresentationMode())
    {
        return endFastFrame();
    }
    if (!m_frameHealthy)
    {
        return false;
    }
    vkCmdEndRenderPass(m_commandBuffer);
    if (vkEndCommandBuffer(m_commandBuffer) != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return false;
    }

    VkSubmitInfo submitInfo = {};
    submitInfo.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submitInfo.commandBufferCount = 1;
    submitInfo.pCommandBuffers = &m_commandBuffer;
    VkResult submitResult = VK_SUCCESS;
    {
        submitResult = vkQueueSubmit(m_queue, 1, &submitInfo, m_fence);
    }
    if (submitResult != VK_SUCCESS)
    {
        // The fence was reset but no successful submission owns it. Retire
        // this backend from further frame use instead of waiting on or
        // recycling an unsignalled binary fence.
        m_frameHealthy = false;
        return false;
    }
    return true;
}

VulkanBackend::WindowPresentResult VulkanBackend::prepareWindowFrame(
    int width, int height, uint32_t* outImageIndex)
{
    if (usesFastPresentationMode())
    {
        return WindowPresentResult::ePresented;
    }
    if (outImageIndex)
        *outImageIndex = 0;
    if (m_headless || m_surface == VK_NULL_HANDLE)
        return WindowPresentResult::eNotWindowed;
    if (!m_frameHealthy || m_device == VK_NULL_HANDLE || m_swapchain == VK_NULL_HANDLE ||
        m_imageAvailable == VK_NULL_HANDLE || m_presentQueue == VK_NULL_HANDLE)
        return WindowPresentResult::eFailed;
    if (width <= 0 || height <= 0)
    {
        ++m_windowPresentDeferrals;
        return WindowPresentResult::eDeferred;
    }

    // All offscreen composition/copy work uses this same fence and queue.  The
    // public contract requires the caller to own m_queueMutex, so waiting here
    // also establishes the offscreen TRANSFER_SRC visibility needed below.
    VkResult offscreenFenceResult = VK_SUCCESS;
    {
        offscreenFenceResult = vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX);
    }
    if (offscreenFenceResult != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return WindowPresentResult::eFailed;
    }

    if (m_swapchainNeedsRecreate)
    {
        if (vkDeviceWaitIdle(m_device) != VK_SUCCESS || !createSwapchain(width, height, true))
        {
            ++m_windowPresentDeferrals;
            return WindowPresentResult::eDeferred;
        }
    }

    uint32_t imageIndex = 0;
    VkResult result = vkAcquireNextImageKHR(
        m_device, m_swapchain, 0, m_imageAvailable, VK_NULL_HANDLE, &imageIndex);
    if (result == VK_NOT_READY || result == VK_TIMEOUT)
    {
        // FIFO owns display cadence.  Never wait for a WSI image while holding
        // the backend queue mutex: render-slot uploads share that queue and must
        // remain independent of a slow/composited/VRR output.
        ++m_windowPresentDeferrals;
        return WindowPresentResult::eDeferred;
    }
    if (result == VK_ERROR_OUT_OF_DATE_KHR)
    {
        m_swapchainNeedsRecreate = true;
        if (vkDeviceWaitIdle(m_device) == VK_SUCCESS)
            (void)createSwapchain(width, height, true);
        ++m_windowPresentDeferrals;
        return WindowPresentResult::eDeferred;
    }
    if (result != VK_SUCCESS && result != VK_SUBOPTIMAL_KHR)
    {
        fprintf(stderr, "VulkanBackend: vkAcquireNextImageKHR failed (%d)\n", result);
        m_frameHealthy = false;
        return WindowPresentResult::eFailed;
    }
    if (result == VK_SUBOPTIMAL_KHR)
        m_swapchainNeedsRecreate = true;

    if (imageIndex >= m_swapchainImages.size() ||
        imageIndex >= m_renderFinishedSemaphores.size() ||
        vkResetFences(m_device, 1, &m_fence) != VK_SUCCESS ||
        vkResetCommandBuffer(m_commandBuffer, 0) != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return WindowPresentResult::eFailed;
    }

    VkCommandBufferBeginInfo beginInfo{};
    beginInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    beginInfo.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    if (vkBeginCommandBuffer(m_commandBuffer, &beginInfo) != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return WindowPresentResult::eFailed;
    }

    VkImageMemoryBarrier toTransfer{};
    toTransfer.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    toTransfer.srcAccessMask = 0;
    toTransfer.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    // The acquired image's old contents are discarded, so UNDEFINED is valid
    // for both first use and reuse after PRESENT_SRC_KHR.
    toTransfer.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    toTransfer.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    toTransfer.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    toTransfer.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    toTransfer.image = m_swapchainImages[imageIndex];
    toTransfer.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    toTransfer.subresourceRange.levelCount = 1;
    toTransfer.subresourceRange.layerCount = 1;
    vkCmdPipelineBarrier(m_commandBuffer,
                         VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &toTransfer);

    const bool useBlit = m_swapchainUsesBlit ||
        m_swapchainExtent.width != static_cast<uint32_t>(m_fbWidth) ||
        m_swapchainExtent.height != static_cast<uint32_t>(m_fbHeight);
    if (useBlit)
    {
        VkImageBlit region{};
        region.srcSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.srcSubresource.layerCount = 1;
        region.srcOffsets[1] = {m_fbWidth, m_fbHeight, 1};
        region.dstSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.dstSubresource.layerCount = 1;
        region.dstOffsets[1] = {
            static_cast<int32_t>(m_swapchainExtent.width),
            static_cast<int32_t>(m_swapchainExtent.height), 1};
        vkCmdBlitImage(m_commandBuffer,
                       m_colorImage, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                       m_swapchainImages[imageIndex], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                       1, &region, VK_FILTER_NEAREST);
    }
    else
    {
        VkImageCopy region{};
        region.srcSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.srcSubresource.layerCount = 1;
        region.dstSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        region.dstSubresource.layerCount = 1;
        region.extent = {m_swapchainExtent.width, m_swapchainExtent.height, 1};
        vkCmdCopyImage(m_commandBuffer,
                       m_colorImage, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                       m_swapchainImages[imageIndex], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
                       1, &region);
    }

    VkImageMemoryBarrier toPresent{};
    toPresent.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    toPresent.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    toPresent.dstAccessMask = 0;
    toPresent.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    toPresent.newLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
    toPresent.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    toPresent.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    toPresent.image = m_swapchainImages[imageIndex];
    toPresent.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    toPresent.subresourceRange.levelCount = 1;
    toPresent.subresourceRange.layerCount = 1;
    vkCmdPipelineBarrier(m_commandBuffer,
                         VK_PIPELINE_STAGE_TRANSFER_BIT,
                         VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,
                         0, 0, nullptr, 0, nullptr, 1, &toPresent);

    if (vkEndCommandBuffer(m_commandBuffer) != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return WindowPresentResult::eFailed;
    }

    const VkPipelineStageFlags waitStage = VK_PIPELINE_STAGE_TRANSFER_BIT;
    VkSubmitInfo submitInfo{};
    submitInfo.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submitInfo.waitSemaphoreCount = 1;
    submitInfo.pWaitSemaphores = &m_imageAvailable;
    submitInfo.pWaitDstStageMask = &waitStage;
    submitInfo.commandBufferCount = 1;
    submitInfo.pCommandBuffers = &m_commandBuffer;
    submitInfo.signalSemaphoreCount = 1;
    submitInfo.pSignalSemaphores = &m_renderFinishedSemaphores[imageIndex];
    if (vkQueueSubmit(m_queue, 1, &submitInfo, m_fence) != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return WindowPresentResult::eFailed;
    }

    if (outImageIndex)
        *outImageIndex = imageIndex;
    return WindowPresentResult::ePrepared;
}

VulkanBackend::WindowPresentResult VulkanBackend::presentWindowFrame(uint32_t imageIndex)
{
    if (m_headless || m_surface == VK_NULL_HANDLE)
        return WindowPresentResult::eNotWindowed;
    if (!m_frameHealthy || m_swapchain == VK_NULL_HANDLE ||
        m_presentQueue == VK_NULL_HANDLE || imageIndex >= m_renderFinishedSemaphores.size())
        return WindowPresentResult::eFailed;

    VkPresentInfoKHR presentInfo{};
    presentInfo.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
    presentInfo.waitSemaphoreCount = 1;
    presentInfo.pWaitSemaphores = &m_renderFinishedSemaphores[imageIndex];
    presentInfo.swapchainCount = 1;
    presentInfo.pSwapchains = &m_swapchain;
    presentInfo.pImageIndices = &imageIndex;
    VkResult result = VK_SUCCESS;
    {
        std::lock_guard<std::mutex> presentLock(m_presentQueueMutex);
        result = vkQueuePresentKHR(m_presentQueue, &presentInfo);
    }
    if (result != VK_SUCCESS && result != VK_SUBOPTIMAL_KHR && result != VK_ERROR_OUT_OF_DATE_KHR)
    {
        fprintf(stderr, "VulkanBackend: vkQueuePresentKHR failed (%d)\n", result);
        m_frameHealthy = false;
        return WindowPresentResult::eFailed;
    }
    if (result == VK_ERROR_OUT_OF_DATE_KHR)
    {
        m_swapchainNeedsRecreate = true;
        ++m_windowPresentDeferrals;
        return WindowPresentResult::eDeferred;
    }

    ++m_windowPresentCount;
    if (result == VK_SUBOPTIMAL_KHR)
        m_swapchainNeedsRecreate = true;
    return WindowPresentResult::ePresented;
}

bool VulkanBackend::waitForFrameCompletion()
{
    if (!m_frameHealthy || m_device == VK_NULL_HANDLE || m_fence == VK_NULL_HANDLE)
        return false;
    if (vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return false;
    }
    return true;
}

bool VulkanBackend::snapshotNativeFramePacingBase(int width, int height)
{
    if (!m_frameHealthy || m_device == VK_NULL_HANDLE || m_fence == VK_NULL_HANDLE ||
        m_commandBuffer == VK_NULL_HANDLE || m_colorImage == VK_NULL_HANDLE ||
        width <= 0 || height <= 0 || width != m_fbWidth || height != m_fbHeight)
        return false;

    const bool replacing = m_framePacingBaseImage == VK_NULL_HANDLE ||
        width != m_framePacingBaseWidth || height != m_framePacingBaseHeight;
    VkImage targetImage = m_framePacingBaseImage;
    VkDeviceMemory targetMemory = m_framePacingBaseMemory;

    auto destroyTarget = [&]() {
        if (!replacing)
            return;
        if (targetImage)
            vkDestroyImage(m_device, targetImage, nullptr);
        if (targetMemory)
            vkFreeMemory(m_device, targetMemory, nullptr);
        targetImage = VK_NULL_HANDLE;
        targetMemory = VK_NULL_HANDLE;
    };

    if (replacing)
    {
        targetImage = VK_NULL_HANDLE;
        targetMemory = VK_NULL_HANDLE;
        VkImageCreateInfo imageInfo = {};
        imageInfo.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO;
        imageInfo.imageType = VK_IMAGE_TYPE_2D;
        imageInfo.format = VK_FORMAT_R8G8B8A8_UNORM;
        imageInfo.extent = { static_cast<uint32_t>(width), static_cast<uint32_t>(height), 1 };
        imageInfo.mipLevels = 1;
        imageInfo.arrayLayers = 1;
        imageInfo.samples = VK_SAMPLE_COUNT_1_BIT;
        imageInfo.tiling = VK_IMAGE_TILING_OPTIMAL;
        imageInfo.usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT;
        imageInfo.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
        if (vkCreateImage(m_device, &imageInfo, nullptr, &targetImage) != VK_SUCCESS)
            return false;

        VkMemoryRequirements requirements = {};
        vkGetImageMemoryRequirements(m_device, targetImage, &requirements);
        VkMemoryAllocateInfo allocation = {};
        allocation.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
        allocation.allocationSize = requirements.size;
        allocation.memoryTypeIndex = findMemoryType(
            requirements.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        if (allocation.memoryTypeIndex == UINT32_MAX ||
            vkAllocateMemory(m_device, &allocation, nullptr, &targetMemory) != VK_SUCCESS ||
            vkBindImageMemory(m_device, targetImage, targetMemory, 0) != VK_SUCCESS)
        {
            destroyTarget();
            return false;
        }
    }

    if (vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
    {
        destroyTarget();
        m_frameHealthy = false;
        return false;
    }

    const auto terminalFailure = [&]() {
        m_frameHealthy = false;
        // A failed submit or wait can leave command-owned resources in an
        // unknown state. Drain before freeing a transactional replacement and
        // never recycle the reset binary fence.
        vkDeviceWaitIdle(m_device);
        destroyTarget();
        return false;
    };
    if (vkResetFences(m_device, 1, &m_fence) != VK_SUCCESS ||
        vkResetCommandBuffer(m_commandBuffer, 0) != VK_SUCCESS)
        return terminalFailure();

    VkCommandBufferBeginInfo begin = {};
    begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    if (vkBeginCommandBuffer(m_commandBuffer, &begin) != VK_SUCCESS)
        return terminalFailure();

    VkImageMemoryBarrier toDestination = {};
    toDestination.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    toDestination.oldLayout = replacing ? VK_IMAGE_LAYOUT_UNDEFINED : VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    toDestination.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    toDestination.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    toDestination.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    toDestination.image = targetImage;
    toDestination.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    toDestination.subresourceRange.levelCount = 1;
    toDestination.subresourceRange.layerCount = 1;
    toDestination.srcAccessMask = replacing ? 0 : VK_ACCESS_TRANSFER_READ_BIT;
    toDestination.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    vkCmdPipelineBarrier(
        m_commandBuffer,
        replacing ? VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT : VK_PIPELINE_STAGE_TRANSFER_BIT,
        VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1, &toDestination);

    VkImageMemoryBarrier sourceVisible = {};
    sourceVisible.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    sourceVisible.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    sourceVisible.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    sourceVisible.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    sourceVisible.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    sourceVisible.image = m_colorImage;
    sourceVisible.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    sourceVisible.subresourceRange.levelCount = 1;
    sourceVisible.subresourceRange.layerCount = 1;
    sourceVisible.srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    sourceVisible.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    vkCmdPipelineBarrier(m_commandBuffer, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1, &sourceVisible);

    VkImageCopy copy = {};
    copy.srcSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    copy.srcSubresource.layerCount = 1;
    copy.dstSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    copy.dstSubresource.layerCount = 1;
    copy.extent = { static_cast<uint32_t>(width), static_cast<uint32_t>(height), 1 };
    vkCmdCopyImage(m_commandBuffer, m_colorImage, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                   targetImage, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &copy);

    VkImageMemoryBarrier toSource = toDestination;
    toSource.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    toSource.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    toSource.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    toSource.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    vkCmdPipelineBarrier(m_commandBuffer, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1, &toSource);
    if (vkEndCommandBuffer(m_commandBuffer) != VK_SUCCESS)
        return terminalFailure();

    VkSubmitInfo submit = {};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &m_commandBuffer;
    if (vkQueueSubmit(m_queue, 1, &submit, m_fence) != VK_SUCCESS ||
        vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
        return terminalFailure();

    if (replacing)
    {
        destroyNativeFramePacingBase();
        m_framePacingBaseImage = targetImage;
        m_framePacingBaseMemory = targetMemory;
        m_framePacingBaseWidth = width;
        m_framePacingBaseHeight = height;
    }
    return true;
}

bool VulkanBackend::restoreNativeFramePacingBase(
    const std::vector<NativeFramePacingCopyRegion>& regions,
    int width,
    int height)
{
    if (!m_frameHealthy || m_device == VK_NULL_HANDLE || m_fence == VK_NULL_HANDLE ||
        m_commandBuffer == VK_NULL_HANDLE || m_colorImage == VK_NULL_HANDLE ||
        m_framePacingBaseImage == VK_NULL_HANDLE || width != m_fbWidth || height != m_fbHeight ||
        width != m_framePacingBaseWidth || height != m_framePacingBaseHeight)
        return false;
    if (regions.empty())
        return waitForFrameCompletion();
    if (vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return false;
    }
    const auto terminalFailure = [&]() {
        m_frameHealthy = false;
        vkDeviceWaitIdle(m_device);
        return false;
    };
    if (vkResetFences(m_device, 1, &m_fence) != VK_SUCCESS ||
        vkResetCommandBuffer(m_commandBuffer, 0) != VK_SUCCESS)
        return terminalFailure();
    VkCommandBufferBeginInfo begin = {};
    begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    if (vkBeginCommandBuffer(m_commandBuffer, &begin) != VK_SUCCESS)
        return terminalFailure();

    VkImageMemoryBarrier toDestination = {};
    toDestination.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
    toDestination.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    toDestination.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    toDestination.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    toDestination.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
    toDestination.image = m_colorImage;
    toDestination.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    toDestination.subresourceRange.levelCount = 1;
    toDestination.subresourceRange.layerCount = 1;
    toDestination.srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;
    toDestination.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    vkCmdPipelineBarrier(m_commandBuffer, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1, &toDestination);

    for (const NativeFramePacingCopyRegion& region : regions)
    {
        if (!region.width || !region.height || region.x >= static_cast<uint32_t>(width) ||
            region.y >= static_cast<uint32_t>(height) || region.width > static_cast<uint32_t>(width) - region.x ||
            region.height > static_cast<uint32_t>(height) - region.y)
            return terminalFailure();
        VkImageCopy copy = {};
        copy.srcSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        copy.srcSubresource.layerCount = 1;
        copy.srcOffset = { static_cast<int32_t>(region.x), static_cast<int32_t>(region.y), 0 };
        copy.dstSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        copy.dstSubresource.layerCount = 1;
        copy.dstOffset = copy.srcOffset;
        copy.extent = { region.width, region.height, 1 };
        vkCmdCopyImage(m_commandBuffer, m_framePacingBaseImage, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
                       m_colorImage, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &copy);
    }

    VkImageMemoryBarrier toSource = toDestination;
    toSource.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    toSource.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    toSource.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    toSource.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    vkCmdPipelineBarrier(m_commandBuffer, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, nullptr, 0, nullptr, 1, &toSource);
    if (vkEndCommandBuffer(m_commandBuffer) != VK_SUCCESS)
        return terminalFailure();
    VkSubmitInfo submit = {};
    submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submit.commandBufferCount = 1;
    submit.pCommandBuffers = &m_commandBuffer;
    if (vkQueueSubmit(m_queue, 1, &submit, m_fence) != VK_SUCCESS ||
        vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
        return terminalFailure();
    return true;
}

// ---------------------------------------------------------------------------
// Readback
// ---------------------------------------------------------------------------

bool VulkanBackend::readbackPixels(uint8_t* outPixels, int width, int height)
{
    std::lock_guard<std::mutex> queueLock(m_queueMutex);
    if (!m_frameHealthy || !m_device || !m_colorImage || !outPixels ||
        width <= 0 || height <= 0 || width != m_fbWidth || height != m_fbHeight)
        return false;

    if (vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
    {
        m_frameHealthy = false;
        return false;
    }

    // Create a host-visible staging buffer
    VkDeviceSize bufferSize = (VkDeviceSize)width * height * 4;

    VkBufferCreateInfo bufInfo = {};
    bufInfo.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    bufInfo.size = bufferSize;
    bufInfo.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
    bufInfo.sharingMode = VK_SHARING_MODE_EXCLUSIVE;

    VkBuffer stagingBuffer = VK_NULL_HANDLE;
    VkResult err = vkCreateBuffer(m_device, &bufInfo, nullptr, &stagingBuffer);
    if (err != VK_SUCCESS) return false;

    VkMemoryRequirements memReqs;
    vkGetBufferMemoryRequirements(m_device, stagingBuffer, &memReqs);

    VkMemoryAllocateInfo allocInfo = {};
    allocInfo.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    allocInfo.allocationSize = memReqs.size;
    allocInfo.memoryTypeIndex = findMemoryType(memReqs.memoryTypeBits,
        VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);

    VkDeviceMemory stagingMemory = VK_NULL_HANDLE;
    err = vkAllocateMemory(m_device, &allocInfo, nullptr, &stagingMemory);
    if (err != VK_SUCCESS) { vkDestroyBuffer(m_device, stagingBuffer, nullptr); return false; }
    if (vkBindBufferMemory(m_device, stagingBuffer, stagingMemory, 0) != VK_SUCCESS)
    {
        vkDestroyBuffer(m_device, stagingBuffer, nullptr);
        vkFreeMemory(m_device, stagingMemory, nullptr);
        return false;
    }

    const auto failAfterFenceReset = [&]() {
        m_frameHealthy = false;
        // A successful submit may still own the staging buffer even if its
        // fence wait failed. Drain the device before retiring resources; the
        // terminal backend will never reuse the abandoned binary fence.
        vkDeviceWaitIdle(m_device);
        vkDestroyBuffer(m_device, stagingBuffer, nullptr);
        vkFreeMemory(m_device, stagingMemory, nullptr);
        return false;
    };

    // Record copy command
    VkCommandBufferBeginInfo beginInfo = {};
    beginInfo.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
    beginInfo.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;

    if (vkResetFences(m_device, 1, &m_fence) != VK_SUCCESS ||
        vkResetCommandBuffer(m_commandBuffer, 0) != VK_SUCCESS ||
        vkBeginCommandBuffer(m_commandBuffer, &beginInfo) != VK_SUCCESS)
        return failAfterFenceReset();

    // The image is already in TRANSFER_SRC_OPTIMAL from the render pass final layout
    VkBufferImageCopy region = {};
    region.imageSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
    region.imageSubresource.layerCount = 1;
    region.imageExtent = { (uint32_t)width, (uint32_t)height, 1 };
    vkCmdCopyImageToBuffer(m_commandBuffer, m_colorImage, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, stagingBuffer, 1, &region);

    if (vkEndCommandBuffer(m_commandBuffer) != VK_SUCCESS)
        return failAfterFenceReset();

    VkSubmitInfo submitInfo = {};
    submitInfo.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
    submitInfo.commandBufferCount = 1;
    submitInfo.pCommandBuffers = &m_commandBuffer;
    if (vkQueueSubmit(m_queue, 1, &submitInfo, m_fence) != VK_SUCCESS ||
        vkWaitForFences(m_device, 1, &m_fence, VK_TRUE, UINT64_MAX) != VK_SUCCESS)
        return failAfterFenceReset();

    // Map and copy
    void* mapped = nullptr;
    {
        err = vkMapMemory(m_device, stagingMemory, 0, bufferSize, 0, &mapped);
    }
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
