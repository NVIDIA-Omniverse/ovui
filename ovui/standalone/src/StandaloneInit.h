/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <tuple>
#include <vector>

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

/// Hooks that let a host give up its own lock while this thread waits inside
/// native presentation (glfwSwapBuffers, vkQueuePresentKHR). ``begin`` runs
/// just before the wait and returns a token; ``end`` runs right after it with
/// that token. The hooks apply only to the calling thread, so a native caller
/// that never sets them is not changed. Pass null pointers to clear them.
/// Not every present call is covered: the Vulkan FAST presentation mode
/// presents inside VulkanBackend::endFastFrame() while the frame holds the
/// native queue lock, outside this scope, so the hooks do not run there.
using PresentWaitBeginFn = void* (*)();
using PresentWaitEndFn = void (*)(void* token);
OMNIUI_STANDALONE_API void setPresentWaitHooks(PresentWaitBeginFn begin, PresentWaitEndFn end);

/// Test seam: make every present wait of the process last at least ``ms``
/// milliseconds (0 turns it off). The wait runs inside the present-wait scope,
/// after the hooks ran, so it blocks the same way a slow display does and
/// needs no special display. The window of the last wait is kept, in seconds
/// on the ``steady_clock`` (the epoch of Python's ``time.perf_counter()``).
/// ``end`` is 0 while the wait is still running.
OMNIUI_STANDALONE_API void setPresentWaitTestDelayMs(int ms);
OMNIUI_STANDALONE_API void getPresentWaitTestWindow(double* begin, double* end);

/// Scope that runs the present-wait hooks of the calling thread, if any.
class OMNIUI_STANDALONE_API PresentWaitScope
{
public:
    PresentWaitScope();
    ~PresentWaitScope();
    PresentWaitScope(const PresentWaitScope&) = delete;
    PresentWaitScope& operator=(const PresentWaitScope&) = delete;

private:
    PresentWaitEndFn m_end = nullptr;
    void* m_token = nullptr;
};
OMNIUI_STANDALONE_API bool shouldClose();
OMNIUI_STANDALONE_API void shutdown();

/// Resize the main OS window (and its OpenGL default framebuffer) to the
/// given dimensions.  Used primarily by tests so that each test can render
/// into a framebuffer whose size matches its requested layout.
///
/// Returns true on success, false if the backend is not initialised or
/// the platform does not support resizing (e.g. headless Vulkan).
OMNIUI_STANDALONE_API bool setWindowSize(int width, int height);

/// Move the main OS window. Returns false for headless/uninitialized backends.
OMNIUI_STANDALONE_API bool setWindowPosition(int x, int y);

/// Query the main OS window framebuffer size.  Returns false if the backend
/// is not initialised or the size could not be determined.
OMNIUI_STANDALONE_API bool getWindowSize(int* width, int* height);

/// Update the title of the main OS window. Returns false when the backend is
/// not initialized or the main window is unavailable.
OMNIUI_STANDALONE_API bool setWindowTitle(const char* title);

/// Query the title of the main OS window. Returns an empty string when the
/// backend is not initialized or the main window is unavailable.
OMNIUI_STANDALONE_API std::string getWindowTitle();

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
// SVG rasterizer build state
//
// True when this binary was built with OMNIUI_ENABLE_SVG=ON, so `init`
// registers the SVG rasterizer. It reports the compile-time option, not the
// registry: a build that forgot to register the rasterizer still returns true,
// and a test can tell that apart from a build made without the option.
// ---------------------------------------------------------------------------
OMNIUI_STANDALONE_API bool isSvgRasterizerBuiltIn();

// ---------------------------------------------------------------------------
// Native cursor input for camera navigation (GLFW windows only)
//
// readCursorMotion returns the cursor motion since the previous call, in
// window pixels, and the steady-clock time (seconds, the clock of Python's
// time.perf_counter) of the newest cursor event; false without a window.
// setCursorCapture hides and locks the cursor, with raw motion where
// supported, for a navigation drag, or gives it back.
// ---------------------------------------------------------------------------
OMNIUI_STANDALONE_API bool readCursorMotion(double* dx, double* dy, double* time);
OMNIUI_STANDALONE_API void setCursorCapture(bool captured);

// ---------------------------------------------------------------------------
// Present timing, a diagnostic (OMNIUI_PRESENT_TIMING=1, see
// VulkanBackend::takePresentTimings): the records (tag, submitted, completed)
// finished since the previous call, and the tag of the next presents.
// ---------------------------------------------------------------------------
OMNIUI_STANDALONE_API std::vector<std::tuple<int64_t, double, double>> takePresentTimings();
OMNIUI_STANDALONE_API void setPresentTimingTag(int64_t tag);

// ---------------------------------------------------------------------------
// Text input state
//
// Returns ImGui's `io.WantTextInput`: true while a text input (a StringField,
// or a FloatDrag/IntDrag in keyboard-edit mode) owns the keyboard. App-level
// shortcuts read it so that a key the field edits (Backspace, Delete) does not
// also run a global action.
// ---------------------------------------------------------------------------
OMNIUI_STANDALONE_API bool isTextInputActive();

// Ends the keyboard edit of the text input that owns the keyboard, in the same
// way as a mouse click outside the field: the field keeps the typed text, and
// when it is drawn next it calls its end-edit callbacks as a commit, not as a
// cancel. Returns false and changes nothing when no text input is in typing
// mode (isTextInputActive() is false). A mouse drag of a FloatDrag or IntDrag
// is not typing mode, also when the same field was edited as text before: the
// drag continues.
OMNIUI_STANDALONE_API bool endTextInput();

// ---------------------------------------------------------------------------
// Clipboard isolation
//
// Returns true when the current ImGui context uses the clipboard of this
// process (headless platforms) and not the OS clipboard (GLFW windows).
// ---------------------------------------------------------------------------
OMNIUI_STANDALONE_API bool isClipboardProcessPrivate();

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
// Clear color of the headless Vulkan frame
//
// Each frame of the headless Vulkan backend (OMNIUI_HEADLESS=1, Vulkan) first
// clears its offscreen RGBA8 image to this color. The pixels that no widget
// draws keep it, in the headless frame export (copyHeadlessFrameToLinear) and
// in screenshots. The default is the opaque {0.12, 0.13, 0.14, 1.0}.
//
// The pixels of that image are premultiplied by alpha: a draw of color C with
// alpha A over pixel P gives C * A + P * (1 - A) in red, green and blue, and
// A + P.alpha * (1 - A) in alpha. The clear color uses the same form: red,
// green and blue must each be at most alpha, and all four values must be from
// 0 to 1. {0, 0, 0, 0} gives a transparent background, so that a consumer
// can composite the frame over another image with
// out = frame.rgb + image.rgb * (1 - frame.alpha). The headless frame export
// and the read-back keep these premultiplied pixels. A .png or .bmp screenshot
// file holds straight color instead (each color value of a pixel that is not
// opaque divided by its alpha), as the readers of these formats expect.
//
// setClearColor needs the headless Vulkan backend, so call it after init().
// The color applies from the next frame that starts after the call and stays
// until shutdown(). The call returns false, keeps the current color and
// writes the cause to stderr and to `error` (when not null) when a value is
// not valid, when init() did not run, or when the backend is a different one
// (a window or headless EGL). getClearColor writes the current color and
// returns false when there is no headless Vulkan backend.
// ---------------------------------------------------------------------------
OMNIUI_STANDALONE_API bool setClearColor(float red, float green, float blue, float alpha,
                                         std::string* error = nullptr);
OMNIUI_STANDALONE_API bool getClearColor(float* red, float* green, float* blue, float* alpha);

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

/// Return the pixel format of the exported frame. Always "rgba8" today: four
/// bytes for each pixel, alpha premultiplied (see setClearColor).
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
