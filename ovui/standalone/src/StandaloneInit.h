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

#include <cstddef>
#include <cstdint>
#include <string>

#ifdef _WIN32
#  ifdef OMNIUI_STANDALONE_EXPORTS
#    define OMNIUI_STANDALONE_API __declspec(dllexport)
#  else
#    define OMNIUI_STANDALONE_API __declspec(dllimport)
#  endif
#else
#  define OMNIUI_STANDALONE_API __attribute__((visibility("default")))
#endif

namespace omni {
namespace ui {
namespace standalone {

OMNIUI_STANDALONE_API bool init(const char* title = "omni.ui", int width = 1280, int height = 720);
OMNIUI_STANDALONE_API bool tick();
OMNIUI_STANDALONE_API bool shouldClose();
OMNIUI_STANDALONE_API void shutdown();

/// Resize the main OS window (and its OpenGL default framebuffer) to the
/// given dimensions.  Used primarily by tests so that each test can render
/// into a framebuffer whose size matches its requested layout.
///
/// Returns true on success, false if the backend is not initialised or
/// the platform does not support resizing (e.g. headless Vulkan).
OMNIUI_STANDALONE_API bool setWindowSize(int width, int height);

/// Query the main OS window framebuffer size.  Returns false if the backend
/// is not initialised or the size could not be determined.
OMNIUI_STANDALONE_API bool getWindowSize(int* width, int* height);

// ---------------------------------------------------------------------------
// Input injection (bypasses GLFW -- writes directly to ImGui IO)
// ---------------------------------------------------------------------------
OMNIUI_STANDALONE_API void injectMouseMove(float x, float y);
OMNIUI_STANDALONE_API void injectMouseButton(int button, bool pressed);
OMNIUI_STANDALONE_API void injectMouseScroll(float dx, float dy);
OMNIUI_STANDALONE_API void injectKeyEvent(int key, bool pressed);
OMNIUI_STANDALONE_API void injectCharEvent(unsigned int ch);
OMNIUI_STANDALONE_API void injectTextInput(const char* text);

// ---------------------------------------------------------------------------
// Apply pending injected input (called by GlfwPlatform::tick after NewFrame setup)
// ---------------------------------------------------------------------------
OMNIUI_STANDALONE_API void applyInjectedInput();

// ---------------------------------------------------------------------------
// Software cursor toggle
//
// Controls ImGui's `io.MouseDrawCursor`. Headless mode enables this by
// default (no OS cursor exists, so the cursor must be rendered into the
// frame). The setter is idempotent — calling it twice with the same
// value leaves the IO flag in the same state.
// ---------------------------------------------------------------------------
OMNIUI_STANDALONE_API void setSoftwareCursor(bool enabled);
OMNIUI_STANDALONE_API bool isSoftwareCursorEnabled();

// ---------------------------------------------------------------------------
// Screenshot capture
// ---------------------------------------------------------------------------
enum class ScreenshotStatus : uint8_t
{
    eIdle,
    ePending,
    eSucceeded,
    eFailed,
    eCancelled,
};

/// Stable snapshot of the most recently scheduled screenshot request.
struct OMNIUI_STANDALONE_API ScreenshotResult
{
    uint64_t requestId = 0;
    ScreenshotStatus status = ScreenshotStatus::eIdle;
    std::string path;
    std::string actualFormat;
    int width = 0;
    int height = 0;
    std::string message;
};

OMNIUI_STANDALONE_API bool captureScreenshot(const char* filepath);

// Schedule a screenshot to be captured before the next buffer swap.
// Returns true if scheduling succeeded. The actual capture happens in tick().
OMNIUI_STANDALONE_API bool scheduleScreenshot(const char* filepath);

// Check whether a scheduled screenshot has been captured (and clear the flag).
OMNIUI_STANDALONE_API bool pollScreenshotDone();

/// Return a non-consuming snapshot of the latest screenshot request.
OMNIUI_STANDALONE_API ScreenshotResult getLastScreenshotResult();

/// Cancel a pending request by ID. Returns false for stale or terminal IDs.
OMNIUI_STANDALONE_API bool cancelScheduledScreenshot(uint64_t requestId);

/// Return whether requestId still names the pending screenshot request.
OMNIUI_STANDALONE_API bool isScreenshotRequestPending(uint64_t requestId);

// Return true if the most recent screenshot capture encountered an error.
OMNIUI_STANDALONE_API bool hadLastScreenshotError();

// ---------------------------------------------------------------------------
// Streaming (FBO rendering + CUDA-GL interop for zero-copy to NVENC)
// ---------------------------------------------------------------------------

/// Initialize the streaming backend. Creates a hidden GLFW window for the GL
/// context, an FBO-backed virtual window at the given resolution, and (if CUDA
/// is available) registers the GL texture for zero-copy GPU access.
/// Returns true on success.
OMNIUI_STANDALONE_API bool initStreaming(int width, int height);

/// Shut down the streaming backend and release all resources (CUDA, FBO, GL).
OMNIUI_STANDALONE_API void shutdownStreaming();

/// Perform one frame: poll events, draw widgets, render to FBO.
/// Does NOT swap buffers (there is no on-screen window).
/// Returns false if the application should exit.
OMNIUI_STANDALONE_API bool streamingTick();

/// Return the GL texture ID of the streaming framebuffer.
/// Valid after initStreaming() and each streamingTick().
OMNIUI_STANDALONE_API unsigned int getStreamingGLTexture();

/// Return the width of the streaming framebuffer.
OMNIUI_STANDALONE_API int getStreamingWidth();

/// Return the height of the streaming framebuffer.
OMNIUI_STANDALONE_API int getStreamingHeight();

/// Return a CUDA device pointer (CUdeviceptr / void*) to a linear RGBA8 buffer
/// containing the most recently rendered frame. Returns 0 if CUDA interop is
/// not available or initStreaming() was not called.
///
/// CONTRACT: The returned pointer is stable across frames (same allocation,
/// contents updated each streamingTick()). The buffer contents are only valid
/// after streamingSync() returns (or after the CUDA event from
/// getStreamingCudaEvent() is satisfied). The pointer is invalidated by
/// resizeStreaming() or shutdownStreaming() — callers must NOT hold the pointer
/// across those calls.
OMNIUI_STANDALONE_API uintptr_t getStreamingCudaPtr();

/// Return the pitch (bytes per row) of the linear CUDA buffer.
/// Useful for NVENC, which needs pitch for NV_ENC_INPUT_PTR.
OMNIUI_STANDALONE_API size_t getStreamingCudaPitch();

/// Return the pixel format of the streaming buffer as a string.
/// Currently always "rgba8". Provided for future format negotiation.
OMNIUI_STANDALONE_API const char* getStreamingFormat();

/// Return true if CUDA interop is available and active.
/// Separate from initStreaming() return value — streaming can succeed
/// without CUDA (degraded mode, GL texture only).
OMNIUI_STANDALONE_API bool isStreamingCudaAvailable();

/// Wait for the most recent frame's CUDA copy to complete.
/// Call this (or wait on getStreamingCudaEvent()) before reading from the
/// CUDA linear buffer on another thread. No-op if CUDA is not active.
OMNIUI_STANDALONE_API void streamingSync();

/// Return a CUDA event (cudaEvent_t cast to uintptr_t) that is recorded
/// after each frame's tiled→linear copy completes. Callers who want
/// asynchronous synchronization can pass this to cudaStreamWaitEvent()
/// instead of calling streamingSync(). Returns 0 if CUDA is not active.
OMNIUI_STANDALONE_API uintptr_t getStreamingCudaEvent();

/// Resize the streaming framebuffer. Recreates the FBO and CUDA resources.
/// WARNING: Must NOT be called while another thread is reading from the CUDA
/// buffer (the resize frees and reallocates the buffer). Callers must ensure
/// all NVENC reads have completed before calling this function.
/// Returns true on success.
OMNIUI_STANDALONE_API bool resizeStreaming(int width, int height);

// ---------------------------------------------------------------------------
// Streaming (VkImage → NVENC/CPU → NAL units)
// ---------------------------------------------------------------------------

/// Initialize the Vulkan streaming pipeline.
/// Set OMNIUI_STREAM_BACKEND=vulkan to enable at init() time, or call manually.
/// Returns true if the streaming encoder was created successfully.
OMNIUI_STANDALONE_API bool initVulkanStreaming(int fps = 60, int bitrateMbps = 10);

/// Shut down the Vulkan streaming pipeline.
OMNIUI_STANDALONE_API void shutdownVulkanStreaming();

/// Encode the current frame. Call after tick().
/// Returns true if encoding succeeded; NAL data is delivered to the registered callback.
OMNIUI_STANDALONE_API bool encodeStreamFrame();

/// Check if the streaming pipeline is active.
OMNIUI_STANDALONE_API bool isStreamingActive();

/// Get the name of the active encoder ("NVENC-H264", "CPU-stub", etc.)
OMNIUI_STANDALONE_API const char* getStreamEncoderName();

/// Register a callback to receive encoded NAL units.
/// Signature: void(const uint8_t* nalData, uint32_t nalSize, uint64_t pts)
using StreamNalCallback = void (*)(const uint8_t*, uint32_t, uint64_t);
OMNIUI_STANDALONE_API void setStreamNalCallback(StreamNalCallback callback);

// ---------------------------------------------------------------------------
// Headless frame export — Vulkan offscreen image -> CUDA pitched-linear buffer
//
// Enables zero-host-bounce export of the headless Vulkan composite image to a
// caller-owned `cudaMallocPitch` device buffer (the shape consumed by the
// ovstream SDK's VideoFrame.buffer). Requires:
//   - standalone::init() already called with OMNIUI_HEADLESS=1 and
//     OMNIUI_BACKEND=vulkan (no GLFW platform may be active)
//   - libomniui_standalone built with both OMNIUI_HAS_VULKAN and
//     OMNIUI_HAS_CUDA
//
// Designed for the issue-34 tier-2 path; see the initHeadlessFrameExport and
// copyHeadlessFrameToLinear comments for per-frame ordering.
// ---------------------------------------------------------------------------

/// Initialise the headless frame export pipeline. Imports the headless
/// platform's offscreen VkImage memory into CUDA and creates the V<->C
/// external semaphore pair. Returns true on success.
///
/// Refuses (and returns false) if standalone is in GLFW mode, if the
/// OMNIUI_HEADLESS / OMNIUI_BACKEND env vars are not set to vulkan-headless,
/// or if the build was not compiled with CUDA + Vulkan support.
OMNIUI_STANDALONE_API bool initHeadlessFrameExport();

/// Tear down the headless frame export pipeline. Safe to call when not
/// initialised.
OMNIUI_STANDALONE_API void shutdownHeadlessFrameExport();

/// Query the current offscreen frame extent. Returns false if the export
/// pipeline (or the underlying Vulkan backend) is not available.
OMNIUI_STANDALONE_API bool getHeadlessFrameExtent(int* width, int* height);

/// TEST-ONLY: arm the next ``CudaVulkanInterop::drainPendingHandoff``
/// invocation to return false without touching CUDA / Vulkan,
/// simulating a synchronization failure. Cleared automatically after
/// one trip. Returns silently when the build lacks CUDA support
/// (no-op).
///
/// Used by `tests/test_ovui_headless_resize_safety.py` to prove that
/// ``resizeHeadlessFrame`` aborts before tearing the interop down on
/// drain failure.
OMNIUI_STANDALONE_API void setHeadlessDrainFailureInjection(bool fail);

/// Resize the active headless offscreen render target.
///
/// Tears down the CUDA-Vulkan interop (the imported VkImage handles
/// become invalid the moment the Vulkan framebuffer is recreated),
/// updates the headless platform's main window size, drives one tick
/// to make ``VulkanBackend::beginFrame`` recreate the framebuffer at
/// the new dimensions, verifies the framebuffer extent matches the
/// request, and re-imports the new image into CUDA.
///
/// Returns false on any of: invalid dimensions, no headless platform
/// active, framebuffer recreation produced a mismatched extent, or
/// re-import of the new image into CUDA failed. On false return the
/// previous interop state is best-effort restored.
///
/// Caller must ensure no consumer (e.g. NVENC encoder) is mid-flight
/// against the current frame when calling. The downstream
/// ovgear ``LivestreamTap`` rebuilds its scratch ring on the next
/// frame because ``getHeadlessFrameExtent`` then reports the new size.
OMNIUI_STANDALONE_API bool resizeHeadlessFrame(int width, int height);

/// Return the pixel format of the exported frame. Always "rgba8" today.
OMNIUI_STANDALONE_API const char* getHeadlessFrameFormat();

/// Wait for the most recent Vulkan render to finish before the next CUDA
/// access. Internally submits a Vulkan signal on the V->C semaphore and
/// queues a CUDA wait on stream 0; subsequent CUDA work issued on stream 0
/// (e.g. copyHeadlessFrameToLinear) will see the signalled state.
///
/// `timeout_ns` is accepted for API symmetry with future timeline-based
/// waits but is not enforced today; the underlying primitive is an
/// async stream sync.
OMNIUI_STANDALONE_API bool waitHeadlessFrameReady(uint64_t timeout_ns);

/// Tell ovui that the consumer has finished reading the current frame.
/// Posts the C->V semaphore so the next Vulkan render is allowed to proceed.
OMNIUI_STANDALONE_API void signalHeadlessFrameConsumed();

/// Copy the current offscreen frame into a caller-owned pitched-linear CUDA
/// buffer (allocated via cudaMallocPitch). The destination must be at least
/// `width*4` bytes per row and `height` rows. `cuda_stream_handle` is a
/// `cudaStream_t` cast to `uintptr_t`; pass 0 for the default stream.
///
/// Issues an asynchronous `cudaMemcpy2DFromArrayAsync` from the imported
/// cudaArray into the pitched destination. The copy is sequenced on the
/// supplied stream — callers must ensure waitHeadlessFrameReady was issued
/// on the same stream (or stream 0) before the copy.
///
/// Returns false on any sanity or CUDA error; the destination contents are
/// unspecified in that case.
OMNIUI_STANDALONE_API bool copyHeadlessFrameToLinear(uintptr_t dst_dev_ptr,
                                                     size_t dst_pitch_bytes,
                                                     uintptr_t cuda_stream_handle);

} // namespace standalone
} // namespace ui
} // namespace omni
