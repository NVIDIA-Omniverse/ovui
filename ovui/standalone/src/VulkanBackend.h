/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "StandaloneInit.h"

#if defined(_WIN32) && !defined(VK_USE_PLATFORM_WIN32_KHR)
#  define VK_USE_PLATFORM_WIN32_KHR
#endif
#include <vulkan/vulkan.h>
#include <array>
#include <atomic>
#include <cstdint>
#include <memory>
#include <functional>
#include <deque>
#include <mutex>
#include <thread>
#include <vector>

struct GLFWwindow;

namespace omni {
namespace ui {
namespace standalone {

struct NativeFramePacingCopyRegion
{
    uint32_t x = 0;
    uint32_t y = 0;
    uint32_t width = 0;
    uint32_t height = 0;
};

/// Self-contained Vulkan context for ImGui rendering.  The canonical image is
/// always offscreen so headless capture, streaming, and native replay share one
/// composition path.  A GLFW-backed instance additionally copies that image to
/// a swapchain for real desktop presentation.
class OMNIUI_STANDALONE_API VulkanBackend
{
public:
    enum class WindowPresentResult
    {
        eNotWindowed,
        ePrepared,
        ePresented,
        eDeferred,
        eFailed,
    };

    VulkanBackend();
    ~VulkanBackend();

    /// Initialize the Vulkan instance, device, render pass, and framebuffer.
    /// If glfwWindow is non-null, also create its Vulkan surface and FIFO
    /// swapchain.  Windowed initialization fails closed if WSI is unavailable.
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
    /// Begin one offscreen composition. ``preserve`` uses a compatible LOAD
    /// render pass so native viewport replay can update the UI-tick framebuffer
    /// without erasing external textures that are only safe on the UI thread.
    /// Without ``waitForPrevious``, a frame fence still busy after
    /// ``noWaitTimeoutNs`` defers the frame (returns false).
    bool beginFrame(int width, int height, bool preserve = false, bool waitForPrevious = true,
                    uint64_t noWaitTimeoutNs = 0);

    /// End the frame: end render pass, submit, wait idle.
    bool endFrame();

    /// Acquire a window image and enqueue the offscreen-to-swapchain copy.  The
    /// caller owns getQueueMutex().  On ePrepared, outImageIndex names the
    /// prepared image that must immediately be passed to presentWindowFrame()
    /// after releasing getQueueMutex().
    WindowPresentResult prepareWindowFrame(int width, int height, uint32_t* outImageIndex);

    /// Enqueue the prepared image on the dedicated present queue.  This may
    /// follow FIFO/display cadence without holding the graphics queue mutex, so
    /// render uploads remain independent.  Headless backends return
    /// eNotWindowed; minimized/out-of-date surfaces return eDeferred.
    WindowPresentResult presentWindowFrame(uint32_t imageIndex);

    /// End the open UI-rate frame and copy it into a persistent, transfer-only
    /// image in the same submission, without waiting for it. The caller owns
    /// getQueueMutex().
    bool snapshotNativeFramePacingBase(int width, int height);

    /// End the open composition and, in the same submission, restore the
    /// UI-rate pixels whose external descriptors cannot be retained by the
    /// presenter, without waiting for it. The caller owns getQueueMutex().
    bool restoreNativeFramePacingBase(
        const std::vector<NativeFramePacingCopyRegion>& regions,
        int width,
        int height);

    /// Retire the persistent snapshot after the queue/device has been drained.
    /// The caller owns getQueueMutex().
    void releaseNativeFramePacingBase();

    /// Read back the offscreen image pixels into an RGBA8 buffer.
    /// The caller must ensure the buffer is large enough (width * height * 4).
    bool readbackPixels(uint8_t* outPixels, int width, int height);

    /// The color that beginFrame() clears the offscreen image to: RGBA in
    /// [0, 1], premultiplied by alpha. The pixels that no draw touches keep
    /// it. A change applies from the next beginFrame(). Any thread may call
    /// these; the caller validates the value (standalone::setClearColor).
    static constexpr std::array<float, 4> kDefaultClearColor = { 0.12f, 0.13f, 0.14f, 1.0f };
    void setClearColor(const std::array<float, 4>& rgba);
    std::array<float, 4> getClearColor() const;

    /// FAST direct presentation renders straight into the swapchain image and
    /// keeps no offscreen copy. A capture must therefore be requested before
    /// the frame that should be captured: that frame copies its swapchain image
    /// to a host buffer before it is presented. readbackPixels() then returns
    /// that copy. No effect outside FAST presentation.
    void requestFastCapture();
    /// False when FAST presentation is active but the surface cannot copy
    /// swapchain images (no VK_IMAGE_USAGE_TRANSFER_SRC_BIT).
    bool fastCaptureSupported() const { return m_fastCaptureSupported; }

    /// Get the offscreen framebuffer dimensions.
    void getFramebufferSize(int* width, int* height) const;

    /// Check if the backend was initialized successfully.
    bool isInitialized() const { return m_device != VK_NULL_HANDLE && m_frameHealthy.load(); }
    bool isSoftwareDevice() const { return m_isSoftwareDevice; }
    bool hasWindowSurface() const { return m_windowSurfaceActive.load(); }
    uint64_t getWindowPresentCount() const { return m_windowPresentCount.load(); }
    uint64_t getWindowPresentDeferralCount() const { return m_windowPresentDeferrals.load(); }
    uint64_t getSwapchainRecreationCount() const { return m_swapchainRecreations.load(); }
    uint32_t getSwapchainWidth() const { return m_swapchainWidth.load(); }
    uint32_t getSwapchainHeight() const { return m_swapchainHeight.load(); }
    VkPresentModeKHR getWindowPresentMode() const
    {
        return static_cast<VkPresentModeKHR>(m_windowPresentMode.load());
    }
    bool usesFastPresentationMode() const
    {
        return m_fastPresentationMode && !m_headless;
    }

    VkCommandBuffer getCommandBuffer() const
    {
        if (usesFastPresentationMode())
        {
            return m_fastActiveCommandBuffer;
        }
        return m_commandBuffer;
    }

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

    /// Vulkan exposes one graphics queue here. Upload, composition, readback,
    /// resize, and teardown callers on different native threads must serialize
    /// external access to that queue and its shared command resources.
    std::mutex& getQueueMutex() { return m_queueMutex; }

    /// Release a GPU resource that ImGui draw data can reference. While a
    /// frame is built and submitted, the draw data can still reference a
    /// texture that a widget destroys, and freeing it there can lose the
    /// device, so the release waits until endFrameReleases(). At other times
    /// it runs at once, which keeps peak GPU memory and descriptor use low.
    /// The caller owns getQueueMutex().
    void deferRelease(std::function<void()> release);
    /// Whether deferRelease() now waits until endFrameReleases().
    /// The caller owns getQueueMutex().
    bool frameReleasesDeferred() const { return m_frameReleasesDeferred; }

    /// The platform calls these around building and submitting one frame.
    /// endFrameReleases() runs the releases deferred in that frame. The
    /// caller must not own getQueueMutex().
    void beginFrameReleases();
    void endFrameReleases();

    /// vkQueuePresentKHR uses the second queue under this mutex. A caller of
    /// vkDeviceWaitIdle must also hold it, because that call accesses every
    /// queue of the device.
    std::mutex& getPresentQueueMutex() { return m_presentQueueMutex; }

    /// Present timing, a diagnostic: with OMNIUI_PRESENT_TIMING=1 in the
    /// environment and VK_KHR_present_id and VK_KHR_present_wait on the
    /// device, each paced window present is timed. A record holds the tag
    /// set before it, the time vkQueuePresentKHR returned and the time the
    /// present was seen complete (steady clock seconds, the clock of Python's
    /// time.perf_counter; -1 when it was not seen within half a second).
    struct PresentTiming
    {
        int64_t tag;
        double submitted;
        double completed;
    };
    /// The finished records since the previous call (at most 8192).
    std::vector<PresentTiming> takePresentTimings();
    void setPresentTimingTag(int64_t tag) { m_presentTimingTag = tag; }

#if OMNIUI_HAS_CUDA
    /// Whether external memory extensions are enabled (required for CUDA interop).
    bool hasExternalMemory() const { return m_hasExternalMemory; }
#endif

private:
    struct FastWindowPresentation;

    bool createInstance();
    bool createSurface();
    bool selectPhysicalDevice();
    bool createDevice();
    bool createSwapchain(int width, int height, bool recreation);
    void destroySwapchain();
    bool createRenderPass();
    bool createFramebuffer(int width, int height);
    bool createOrResizeFastWindowPresentation(int width, int height);
    void destroyFastWindowPresentation();
    bool beginFastFrame(int width, int height);
    bool endFastFrame();
    bool recordFastCaptureCopy(VkCommandBuffer commandBuffer, VkImage image,
                               int width, int height, VkBuffer buffer);
    void finishFastCapture(VkBuffer buffer, VkDeviceMemory memory, VkFormat format,
                           int width, int height);
    void destroyFramebuffer();
    void destroyNativeFramePacingBase();
    bool createCommandPool();
    bool createDescriptorPool();
    void runDeferredReleases();

    uint32_t findMemoryType(uint32_t typeBits, VkMemoryPropertyFlags properties);

    VkInstance               m_instance        = VK_NULL_HANDLE;
    GLFWwindow*              m_glfwWindow      = nullptr;
    VkSurfaceKHR             m_surface         = VK_NULL_HANDLE;
    VkPhysicalDevice         m_physicalDevice  = VK_NULL_HANDLE;
    VkDevice                 m_device          = VK_NULL_HANDLE;
    VkQueue                  m_queue           = VK_NULL_HANDLE;
    VkQueue                  m_presentQueue    = VK_NULL_HANDLE;
    uint32_t                 m_queueFamily     = 0;
    uint32_t                 m_queueFamilyQueueCount = 0;
    VkRenderPass             m_renderPass      = VK_NULL_HANDLE;
    VkRenderPass             m_overlayRenderPass = VK_NULL_HANDLE;
    VkCommandPool            m_commandPool     = VK_NULL_HANDLE;
    VkCommandBuffer          m_commandBuffer   = VK_NULL_HANDLE;
    VkDescriptorPool         m_descriptorPool  = VK_NULL_HANDLE;
    VkFence                  m_fence           = VK_NULL_HANDLE;
    // The window copy has its own command buffer and fence, so preparing a
    // window frame never waits for the composition under the queue mutex.
    // beginFrame() waits for both fences.
    VkCommandBuffer          m_windowCommandBuffer = VK_NULL_HANDLE;
    VkFence                  m_windowFence     = VK_NULL_HANDLE;

    // The windowed path retains the offscreen image as its source of truth and
    // uses one serialized acquire/copy/present chain.  Native replay and the UI
    // already serialize this queue through m_queueMutex.
    VkSwapchainKHR           m_swapchain       = VK_NULL_HANDLE;
    VkFormat                 m_swapchainFormat = VK_FORMAT_UNDEFINED;
    VkExtent2D               m_swapchainExtent{};
    std::vector<VkImage>     m_swapchainImages;
    VkSemaphore              m_imageAvailable  = VK_NULL_HANDLE;
    std::vector<VkSemaphore> m_renderFinishedSemaphores;
    bool                     m_swapchainNeedsRecreate = false;
    // The window size that the swapchain was last created for (the framebuffer size
    // given to createSwapchain), not the extent that the driver chose.
    int                      m_swapchainRequestWidth = 0;
    int                      m_swapchainRequestHeight = 0;
    bool                     m_swapchainUsesBlit = false;

    // Offscreen framebuffer
    VkImage                  m_colorImage      = VK_NULL_HANDLE;
    VkDeviceMemory           m_colorMemory     = VK_NULL_HANDLE;
    VkImageView              m_colorView       = VK_NULL_HANDLE;
    VkFramebuffer            m_framebuffer     = VK_NULL_HANDLE;
    VkDeviceSize             m_colorMemorySize = 0;
    int                      m_fbWidth         = 0;
    int                      m_fbHeight        = 0;

    // Frozen full-UI source used to restore only unretainable external-image
    // rectangles after an independently paced viewport redraw.
    VkImage                  m_framePacingBaseImage  = VK_NULL_HANDLE;
    VkDeviceMemory           m_framePacingBaseMemory = VK_NULL_HANDLE;
    int                      m_framePacingBaseWidth  = 0;
    int                      m_framePacingBaseHeight = 0;

    bool                     m_headless           = false;
    bool                     m_fastPresentationMode = false;
    bool                     m_fastFrameReady = false;
    VkCommandBuffer          m_fastActiveCommandBuffer = VK_NULL_HANDLE;
    std::unique_ptr<FastWindowPresentation> m_fastWindowPresentation;
    // FAST capture: set by requestFastCapture(), consumed by endFastFrame().
    std::atomic<bool>        m_fastCaptureRequested{false};
    bool                     m_fastCaptureSupported = false;
    std::vector<uint8_t>     m_fastCapturePixels;  // RGBA, top row first
    int                      m_fastCaptureWidth = 0;
    int                      m_fastCaptureHeight = 0;
    bool                     m_imguiInitialized   = false;
    bool                     m_isSoftwareDevice   = false;
    std::atomic<bool>        m_frameHealthy{false};
    std::atomic<bool>        m_windowSurfaceActive{false};
    std::atomic<uint64_t>    m_windowPresentCount{0};
    std::atomic<uint64_t>    m_windowPresentDeferrals{0};
    std::atomic<uint64_t>    m_swapchainRecreations{0};
    std::atomic<uint32_t>    m_swapchainWidth{0};
    std::atomic<uint32_t>    m_swapchainHeight{0};
    std::atomic<int32_t>     m_windowPresentMode{-1};
#if OMNIUI_HAS_CUDA
    bool                     m_hasExternalMemory = false;
#endif
    std::mutex               m_queueMutex;
    std::mutex               m_presentQueueMutex;
    // The UI thread sets it; beginFrame() reads it on the UI thread or on the
    // native presentation thread.
    mutable std::mutex       m_clearColorMutex;
    std::array<float, 4>     m_clearColor = kDefaultClearColor;
    void presentTimingLoop();
    PFN_vkWaitForPresentKHR  m_vkWaitForPresentKHR = nullptr;
    std::thread              m_presentTimingThread;
    std::atomic<bool>        m_presentTimingStop{false};
    std::atomic<int64_t>     m_presentTimingTag{-1};
    std::mutex               m_presentTimingMutex;
    uint64_t                 m_presentId = 0; // guarded by m_presentQueueMutex
    // Guarded by m_presentTimingMutex: presents not seen complete (with
    // their ids), and finished records.
    std::deque<std::pair<uint64_t, PresentTiming>> m_presentsPending;
    std::vector<PresentTiming> m_presentTimings;
    // Guarded by m_queueMutex.
    bool                     m_frameReleasesDeferred = false;
    std::vector<std::function<void()>> m_deferredReleases;
};

} // namespace standalone
} // namespace ui
} // namespace omni
