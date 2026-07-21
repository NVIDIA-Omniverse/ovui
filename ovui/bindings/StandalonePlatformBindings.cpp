/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include "PlatformBindings.h"
#include "StandaloneInit.h"

#include <imgui/imgui.h>

#include <string>

namespace omni
{
namespace ui
{
namespace
{

std::string g_testClipboard;

const char* getTestClipboard(ImGuiContext*)
{
    return g_testClipboard.c_str();
}

void setTestClipboard(ImGuiContext*, const char* text)
{
    g_testClipboard = text ? text : "";
}

void installTestClipboard()
{
    ImGuiPlatformIO& platformIO = ImGui::GetPlatformIO();
    platformIO.Platform_GetClipboardTextFn = getTestClipboard;
    platformIO.Platform_SetClipboardTextFn = setTestClipboard;
}

} // namespace

void registerPlatformBindings(pybind11::module_& m)
{
    // Standalone entry points
    m.def("_standalone_init", &standalone::init, "Initialize standalone backend",
          pybind11::arg("title") = "omni.ui", pybind11::arg("width") = 1280, pybind11::arg("height") = 720);
    m.def("_standalone_tick", &standalone::tick, "Process one frame");
    m.def("_standalone_should_close", &standalone::shouldClose, "Check if window should close");
    m.def("_standalone_shutdown", &standalone::shutdown, "Shut down standalone backend");
    m.def("_standalone_set_window_size", &standalone::setWindowSize,
          "Resize the main OS window's default framebuffer",
          pybind11::arg("width"), pybind11::arg("height"));
    m.def("_standalone_get_window_size",
          []() {
              int w = 0, h = 0;
              standalone::getWindowSize(&w, &h);
              return std::make_pair(w, h);
          },
          "Return (width, height) of the main OS window framebuffer");

    // Input injection
    m.def("_inject_mouse_move", &standalone::injectMouseMove,
          "Inject mouse move event", pybind11::arg("x"), pybind11::arg("y"));
    m.def("_inject_mouse_button", &standalone::injectMouseButton,
          "Inject mouse button event", pybind11::arg("button"), pybind11::arg("pressed"));
    m.def("_inject_mouse_scroll", &standalone::injectMouseScroll,
          "Inject mouse scroll event", pybind11::arg("dx"), pybind11::arg("dy"));
    m.def("_inject_key_event", &standalone::injectKeyEvent,
          "Inject key event", pybind11::arg("key"), pybind11::arg("pressed"));
    m.def("_inject_char_event", &standalone::injectCharEvent,
          "Inject character input event", pybind11::arg("ch"));
    m.def("_inject_text_input", &standalone::injectTextInput,
          "Inject text input (UTF-8 string)", pybind11::arg("text"));

    // Software cursor toggle (ImGui io.MouseDrawCursor). Headless enables
    // this by default so injected mouse positions render into captures.
    m.def("_set_software_cursor", &standalone::setSoftwareCursor,
          "Enable or disable ImGui's software-rendered mouse cursor",
          pybind11::arg("enabled"));
    m.def("_is_software_cursor_enabled", &standalone::isSoftwareCursorEnabled,
          "Return True when ImGui is rendering a software mouse cursor");

    // Clipboard helpers for standalone interaction tests.
    m.def("_get_clipboard_text", []() {
        installTestClipboard();
        return g_testClipboard;
    }, "Return current standalone clipboard text");
    m.def("_set_clipboard_text", [](const char* text) {
        installTestClipboard();
        g_testClipboard = text ? text : "";
    }, "Set standalone clipboard text", pybind11::arg("text"));

    // Screenshot capture
    m.def("_capture_screenshot", &standalone::captureScreenshot,
          "Capture the current framebuffer to an image file", pybind11::arg("filepath"));
    m.def("_schedule_screenshot", &standalone::scheduleScreenshot,
          "Schedule a screenshot to be captured before the next buffer swap", pybind11::arg("filepath"));
    m.def("_poll_screenshot_done", &standalone::pollScreenshotDone,
          "Check whether a scheduled screenshot has been captured");
    m.def("_get_screenshot_result", []() {
        const standalone::ScreenshotResult result = standalone::getLastScreenshotResult();
        const char* status = "idle";
        switch (result.status)
        {
            case standalone::ScreenshotStatus::ePending: status = "pending"; break;
            case standalone::ScreenshotStatus::eSucceeded: status = "succeeded"; break;
            case standalone::ScreenshotStatus::eFailed: status = "failed"; break;
            case standalone::ScreenshotStatus::eCancelled: status = "cancelled"; break;
            case standalone::ScreenshotStatus::eIdle: break;
        }
        pybind11::dict snapshot;
        snapshot["request_id"] = result.requestId;
        snapshot["status"] = status;
        snapshot["done"] = result.status != standalone::ScreenshotStatus::eIdle &&
                           result.status != standalone::ScreenshotStatus::ePending;
        snapshot["success"] = result.status == standalone::ScreenshotStatus::eSucceeded;
        snapshot["path"] = result.path;
        snapshot["actual_format"] = result.actualFormat;
        snapshot["width"] = result.width;
        snapshot["height"] = result.height;
        snapshot["message"] = result.message;
        return snapshot;
    }, "Return the request-scoped result of the latest screenshot");
    m.def("_cancel_screenshot", &standalone::cancelScheduledScreenshot,
          "Cancel a pending screenshot request by ID", pybind11::arg("request_id"));
    m.def("_had_last_screenshot_error", &standalone::hadLastScreenshotError,
          "Return whether the latest screenshot reached a failure status");

    // Streaming (FBO rendering + CUDA-GL interop)
    m.def("_init_streaming", &standalone::initStreaming,
          "Initialize streaming backend with FBO at given resolution",
          pybind11::arg("width"), pybind11::arg("height"));
    m.def("_shutdown_streaming", &standalone::shutdownStreaming,
          "Shut down the streaming backend");
    m.def("_streaming_tick", &standalone::streamingTick,
          "Render one frame to the streaming FBO");
    m.def("_get_streaming_gl_texture", &standalone::getStreamingGLTexture,
          "Get the GL texture ID of the streaming framebuffer");
    m.def("_get_streaming_width", &standalone::getStreamingWidth,
          "Get the width of the streaming framebuffer");
    m.def("_get_streaming_height", &standalone::getStreamingHeight,
          "Get the height of the streaming framebuffer");
    m.def("_get_streaming_cuda_ptr", &standalone::getStreamingCudaPtr,
          "Get CUDA device pointer to linear RGBA8 buffer of last frame");
    m.def("_get_streaming_cuda_pitch", &standalone::getStreamingCudaPitch,
          "Get pitch (bytes per row) of the linear CUDA buffer");
    m.def("_get_streaming_format", &standalone::getStreamingFormat,
          "Get the pixel format of the streaming buffer (e.g. 'rgba8')");
    m.def("_is_streaming_cuda_available", &standalone::isStreamingCudaAvailable,
          "Check if CUDA interop is active (separate from init success)");
    m.def("_streaming_sync", &standalone::streamingSync,
          "Wait for the most recent frame's CUDA copy to complete");
    m.def("_get_streaming_cuda_event", &standalone::getStreamingCudaEvent,
          "Get CUDA event (cudaEvent_t as int) recorded after each frame copy");
    m.def("_resize_streaming", &standalone::resizeStreaming,
          "Resize the streaming framebuffer",
          pybind11::arg("width"), pybind11::arg("height"));

    // Headless frame export (Vulkan offscreen image -> CUDA pitched-linear)
    // Requires standalone::init() with OMNIUI_HEADLESS=1 OMNIUI_BACKEND=vulkan.
    m.def("_headless_frame_init", &standalone::initHeadlessFrameExport,
          "Initialise the headless frame export pipeline (CUDA-Vulkan interop)");
    m.def("_headless_frame_shutdown", &standalone::shutdownHeadlessFrameExport,
          "Tear down the headless frame export pipeline");
    m.def("_headless_frame_extent",
          []() {
              int w = 0, h = 0;
              bool ok = standalone::getHeadlessFrameExtent(&w, &h);
              if (!ok)
                  return std::make_pair(0, 0);
              return std::make_pair(w, h);
          },
          "Return (width, height) of the exported frame, or (0,0) if not available");
    m.def("_headless_frame_format", &standalone::getHeadlessFrameFormat,
          "Return the pixel format of the exported frame ('rgba8')");
    m.def("_headless_frame_resize", &standalone::resizeHeadlessFrame,
          "Resize the active headless offscreen render target. Tears "
          "down the CUDA-Vulkan interop, updates the platform extent, "
          "drives one tick to recreate the Vulkan framebuffer, and "
          "re-imports the new image into CUDA. Returns true on success.",
          pybind11::arg("width"), pybind11::arg("height"));
    // Test seam — see standalone::setHeadlessDrainFailureInjection.
    // Toggling this from a test forces the next
    // ``resizeHeadlessFrame`` call's drain phase to fail, so the
    // test can assert that the resize aborts before tearing the
    // interop down. Always defined; no-op when the build lacks
    // OMNIUI_HAS_CUDA.
    m.def("_headless_frame_test_inject_drain_failure",
          &standalone::setHeadlessDrainFailureInjection,
          "TEST-ONLY: arm the next drainPendingHandoff() call to "
          "return false without touching CUDA/Vulkan, simulating a "
          "synchronization failure. Cleared automatically after one "
          "trip.",
          pybind11::arg("fail"));
    m.def("_headless_frame_wait_ready", &standalone::waitHeadlessFrameReady,
          "Wait for the most recent Vulkan render to finish (V->C semaphore)",
          pybind11::arg("timeout_ns"));
    m.def("_headless_frame_signal_consumed", &standalone::signalHeadlessFrameConsumed,
          "Notify ovui that the consumer has finished reading the frame "
          "(C->V semaphore)");
    m.def("_headless_frame_copy_to_linear", &standalone::copyHeadlessFrameToLinear,
          "Copy the offscreen frame into a pitched-linear CUDA buffer "
          "(cudaMemcpy2DFromArrayAsync)",
          pybind11::arg("dst_dev_ptr"),
          pybind11::arg("dst_pitch_bytes"),
          pybind11::arg("cuda_stream_handle") = 0);
}

} // namespace ui
} // namespace omni
