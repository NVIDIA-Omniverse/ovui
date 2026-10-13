/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// The wheel-only `omni.ui._standalone` module: the standalone bridge of the
// shared `_ui` module. Importing it registers the platform hooks, so `_ui`
// gains the standalone entry points under their usual names when it loads.

#include "StandaloneInit.h"
#include "NativeFramePacing.h"
#include "NativeTiming.h"

#include <omni/ui/ImageProvider/ByteImageProvider.h>
#include <omni/ui/bind/PlatformHooks.h>
#include <omni/ui/platform/PlatformRegistry.h>
#include <omni/ui/windowmanager/WindowManagerBindingsPython.h>

#include <imgui/imgui.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <stdexcept>
#include <string>
#include <utility>

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

namespace
{

// Native window handles are plain pointers outside a host application.
pybind11::object appWindowToPython(AppWindowHandle window)
{
    return pybind11::cast(window);
}
AppWindowHandle appWindowFromPython(pybind11::handle window)
{
    return pybind11::cast<AppWindowHandle>(window);
}

} // namespace

// Called at the end of `_ui` initialisation, after every `_ui` type exists.
void registerStandaloneBindings(PyObject* module)
{
    auto m = pybind11::reinterpret_borrow<pybind11::module_>(module);

    // Optional native timing: a package passes a capsule that holds a
    // NativeTimingHooks table, or None to remove the hooks.
    m.def("_set_native_timing_hooks", [](pybind11::object capsule) {
        if (capsule.is_none())
        {
            standalone::setNativeTimingHooks(nullptr);
            return;
        }
        auto* hooks = static_cast<const standalone::NativeTimingHooks*>(
            PyCapsule_GetPointer(capsule.ptr(), standalone::kNativeTimingHooksCapsuleName));
        if (hooks == nullptr)
        {
            throw pybind11::error_already_set();
        }
        standalone::setNativeTimingHooks(hooks);
    });

    auto windowManagerModule = m.def_submodule("_window_manager");
    windowmanager::definePythonModule(
        windowManagerModule,
        [] { return PlatformRegistry::instance().windowCallbackManager(); },
        [](AppWindowHandle window) { return appWindowToPython(window); },
        [](pybind11::handle window) { return appWindowFromPython(window); });
    // Standalone entry points
    m.def("_standalone_init", &standalone::init, "Initialize standalone backend",
          pybind11::arg("title") = "omni.ui", pybind11::arg("width") = 1280, pybind11::arg("height") = 720);
    m.def("_standalone_tick", &standalone::tick, "Process one frame");
    m.def("_standalone_should_close", &standalone::shouldClose, "Check if window should close");
    m.def("_standalone_shutdown", &standalone::shutdown, "Shut down standalone backend");
    m.def("_standalone_set_window_size", &standalone::setWindowSize,
          "Resize the main OS window's default framebuffer",
          pybind11::arg("width"), pybind11::arg("height"));
    m.def("_standalone_set_window_position", &standalone::setWindowPosition,
          "Move the main OS window",
          pybind11::arg("x"), pybind11::arg("y"));
    m.def("_standalone_get_window_size",
          []() {
              int w = 0, h = 0;
              standalone::getWindowSize(&w, &h);
              return std::make_pair(w, h);
          },
          "Return (width, height) of the main OS window framebuffer");
    m.def("_standalone_set_window_title", &standalone::setWindowTitle,
          "Set the main OS window title", pybind11::arg("title"));
    m.def("_standalone_get_window_title", &standalone::getWindowTitle,
          "Return the main OS window title");

    // Native Vulkan frame pacing. The renderer handle is borrowed: the Python
    // adapter remains its sole owner and must stop/join before destruction.
    m.def("_set_present_rate", &standalone::setNativeFramePacingPresentRate,
          "Set the native Vulkan saved-geometry presentation rate (0 disables)",
          pybind11::arg("frames_per_second"));
    m.def("_get_present_rate", &standalone::getNativeFramePacingPresentRate,
          "Return the configured native presentation rate");
    m.def("_native_frame_pacing_start",
          [](uintptr_t rendererPtr,
             const std::string& libraryPath,
             uint32_t renderVarStride,
             uint32_t renderVarNameOffset,
             uint32_t renderVarHandleOffset,
             const std::shared_ptr<ByteImageProvider>& provider,
             const std::string& renderProduct,
             const std::string& cameraPath,
             uint32_t width,
             uint32_t height) {
              pybind11::gil_scoped_release release;
              return standalone::startNativeFramePacing(
                  rendererPtr, libraryPath.c_str(), renderVarStride,
                  renderVarNameOffset, renderVarHandleOffset, provider,
                  renderProduct.c_str(), cameraPath.c_str(), width, height);
          },
          "Start a capability-checked native coordinator borrowing an ovrtx renderer",
          pybind11::arg("renderer_ptr"), pybind11::arg("library_path"),
          pybind11::arg("render_var_stride"), pybind11::arg("render_var_name_offset"),
          pybind11::arg("render_var_handle_offset"),
          pybind11::arg("provider"), pybind11::arg("render_product"),
          pybind11::arg("camera_path"), pybind11::arg("width"), pybind11::arg("height"));
    m.def("_native_frame_pacing_publish",
          [](uint64_t token,
             uint32_t width,
             uint32_t height,
             const pybind11::array_t<double, pybind11::array::c_style | pybind11::array::forcecast>& worldMatrix,
             const pybind11::array_t<double, pybind11::array::c_style | pybind11::array::forcecast>& linearVelocity,
             double timestamp) {
              if (worldMatrix.size() != 16)
              {
                  throw pybind11::value_error("world_matrix must contain exactly 16 doubles");
              }
              if (linearVelocity.size() != 3)
              {
                  throw pybind11::value_error("linear_velocity must contain exactly 3 doubles");
              }
              std::array<double, 16> world{};
              std::array<double, 3> velocity{};
              std::copy_n(worldMatrix.data(), world.size(), world.begin());
              std::copy_n(linearVelocity.data(), velocity.size(), velocity.begin());
              pybind11::gil_scoped_release release;
              return standalone::publishNativeFramePacingState(
                  token, width, height, world, velocity, timestamp);
          },
          "Publish one complete render-visible camera intent. ``timestamp`` must "
          "come from ``time.perf_counter()``, which shares an epoch with the "
          "``std::chrono::steady_clock`` the coordinator differences it against.",
          pybind11::arg("token"), pybind11::arg("width"), pybind11::arg("height"),
          pybind11::arg("world_matrix"),
          pybind11::arg("linear_velocity") = pybind11::make_tuple(0.0, 0.0, 0.0),
          pybind11::arg("timestamp") = 0.0);
    m.def("_native_frame_pacing_stop",
          [](uint64_t token) {
              pybind11::gil_scoped_release release;
              return standalone::stopNativeFramePacing(token);
          },
          "Revoke the renderer borrow, drain, and join native pacing threads",
          pybind11::arg("token"));
    m.def("_native_frame_pacing_pause_render",
          [](uint64_t token) {
              pybind11::gil_scoped_release release;
              return standalone::pauseNativeFramePacingRender(token);
          },
          "Drain the render worker while keeping native presentation active",
          pybind11::arg("token"));
    m.def("_native_frame_pacing_resume_render",
          [](uint64_t token) {
              pybind11::gil_scoped_release release;
              return standalone::resumeNativeFramePacingRender(token);
          },
          "Resume the render worker under the existing presentation token",
          pybind11::arg("token"));
    m.def("_get_native_frame_pacing_status", []() {
        const standalone::NativeFramePacingStats stats = standalone::getNativeFramePacingStats();
        pybind11::dict result;
        result["supported"] = stats.supported;
        result["active"] = stats.active;
        result["status_reason"] = stats.statusReason;
        result["present_rate"] = stats.presentRate;
        result["ovrtx_version"] = pybind11::make_tuple(
            stats.ovrtxVersionMajor, stats.ovrtxVersionMinor, stats.ovrtxVersionPatch);
        result["session_token"] = stats.sessionToken;
        result["ui_geometry_generations"] = stats.uiGeometryGenerations;
        result["real_render_completions"] = stats.realRenderCompletions;
        result["generated_images"] = stats.generatedImages;
        result["selected_viewport_image_changes"] = stats.selectedViewportImageChanges;
        result["selected_viewport_content_changes"] = stats.selectedViewportContentChanges;
        result["metrics_epoch"] = stats.metricsEpoch;
        result["renderer_completions"] = stats.rendererCompletions;
        result["selected_content_changes"] = stats.selectedContentChanges;
        result["selected_renderer_frames"] = stats.selectedRendererFrames;
        result["last_selected_renderer_frame_serial"] = stats.lastSelectedRendererFrameSerial;
        result["presented_renderer_frames"] = stats.presentedRendererFrames;
        result["last_presented_renderer_frame_serial"] = stats.lastPresentedRendererFrameSerial;
        result["renderer_frame_order_violations"] = stats.rendererFrameOrderViolations;
        result["present_submit_calls"] = stats.presentSubmitCalls;
        result["present_submit_successes"] = stats.presentSubmitSuccesses;
        result["present_submit_total_nanoseconds"] = stats.presentSubmitTotalNanoseconds;
        result["present_submit_max_nanoseconds"] = stats.presentSubmitMaxNanoseconds;
        result["successful_present_intervals"] = stats.successfulPresentIntervals;
        result["successful_present_interval_total_nanoseconds"] =
            stats.successfulPresentIntervalTotalNanoseconds;
        result["successful_present_interval_max_nanoseconds"] =
            stats.successfulPresentIntervalMaxNanoseconds;
        result["successful_present_intervals_over_40ms"] =
            stats.successfulPresentIntervalsOver40ms;
        result["successful_present_intervals_over_100ms"] =
            stats.successfulPresentIntervalsOver100ms;
        result["successful_present_intervals_over_1s"] =
            stats.successfulPresentIntervalsOver1s;
        result["total_presents"] = stats.totalPresents;
        result["repeated_presents"] = stats.repeatedPresents;
        result["window_surface_active"] = stats.windowSurfaceActive;
        result["window_presents"] = stats.windowPresents;
        result["window_present_deferrals"] = stats.windowPresentDeferrals;
        result["swapchain_recreations"] = stats.swapchainRecreations;
        result["swapchain_extent"] = pybind11::make_tuple(
            stats.swapchainWidth, stats.swapchainHeight);
        result["backend"] = stats.backend;
        result["present_policy"] = stats.presentPolicy;
        result["active_present_mode"] = stats.activePresentMode;
        result["completed_frame_groups"] = stats.completedFrameGroups;
        result["completed_frame_groups_size_1"] = stats.completedFrameGroupsSize1;
        result["completed_frame_groups_size_2"] = stats.completedFrameGroupsSize2;
        result["completed_frame_groups_size_3"] = stats.completedFrameGroupsSize3;
        result["completed_frame_groups_size_4"] = stats.completedFrameGroupsSize4;
        result["replaced_frame_groups"] = stats.replacedFrameGroups;
        result["dropped_images"] = stats.droppedImages;
        result["presented_generated_images"] = stats.presentedGeneratedImages;
        result["renderer_timestamp_intervals"] = stats.rendererTimestampIntervals;
        result["renderer_timestamp_interval_total_nanoseconds"] =
            stats.rendererTimestampIntervalTotalNanoseconds;
        result["renderer_timestamp_interval_max_nanoseconds"] =
            stats.rendererTimestampIntervalMaxNanoseconds;
        result["renderer_timestamp_order_violations"] =
            stats.rendererTimestampOrderViolations;
        result["presentation_deadline_misses"] = stats.presentationDeadlineMisses;
        result["last_presented_frame_end_time"] = stats.lastPresentedFrameEndTime;
        result["gpu_resident_publications"] = stats.gpuResidentPublications;
        result["host_fallback_publications"] = stats.hostFallbackPublications;
        result["gpu_publication_failures"] = stats.gpuPublicationFailures;
        result["ownership_generation"] = stats.ownershipGeneration;
        result["live_step_results"] = stats.liveStepResults;
        result["live_mappings"] = stats.liveMappings;
        result["borrowed_slots"] = stats.borrowedSlots;
        result["stale_generation_rejections"] = stats.staleGenerationRejections;
        result["camera_publications"] = stats.cameraPublications;
        result["camera_integrations"] = stats.cameraIntegrations;
        result["maximum_prediction_offset"] = stats.maximumPredictionOffset;
        result["render_loop_exited"] = stats.renderLoopExited;
        result["render_loop_fatal"] = stats.renderLoopFatal;
        result["render_paused"] = stats.renderPaused;
        result["fetch_polls"] = stats.fetchPolls;
        result["fetch_bounded_waits"] = stats.fetchBoundedWaits;
        result["errors"] = stats.errors;
        result["last_error"] = stats.lastError;
        result["dlss_generated_frame_activation_supported"] = stats.dlssGeneratedFrameActivationSupported;
        result["dlss_generated_frame_capability"] = stats.dlssGeneratedFrameCapability;
        result["dlss_generated_frame_runtime_supported"] = stats.dlssGeneratedFrameRuntimeSupported;
        result["dlss_generated_frame_x3x4_supported"] = stats.dlssGeneratedFrameX3X4Supported;
        result["dlss_generated_frame_global_enable_opinion_present"] =
            stats.dlssGeneratedFrameGlobalEnableOpinionPresent;
        result["dlss_generated_frame_requested_enabled"] = stats.dlssGeneratedFrameRequestedEnabled;
        result["dlss_generated_frame_requested_count"] = stats.dlssGeneratedFrameRequestedCount;
        result["dlss_generated_frame_effective_active"] = stats.dlssGeneratedFrameEffectiveActive;
        result["dlss_generated_frame_effective_count"] = stats.dlssGeneratedFrameEffectiveCount;
        result["selected_image_is_generated"] = stats.selectedImageIsGenerated;
        result["selected_camera_world"] = stats.hasSelectedCameraWorld
            ? pybind11::cast(stats.selectedCameraWorld) : pybind11::none();
        result["predicted_camera_world"] = stats.hasPredictedCameraWorld
            ? pybind11::cast(stats.predictedCameraWorld) : pybind11::none();
        result["authoritative_camera_world"] = stats.hasAuthoritativeCameraWorld
            ? pybind11::cast(stats.authoritativeCameraWorld) : pybind11::none();
        return result;
    }, "Return native render/presentation counters and lifecycle state");
    m.def("_reset_frame_throughput_metrics",
          &standalone::resetFrameThroughputMetrics);
    m.def("_record_synchronous_renderer_completion",
          &standalone::recordSynchronousRendererCompletion);
    m.def("_record_synchronous_content_selection",
          &standalone::recordSynchronousContentSelection);

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
    m.def("_is_text_input_active", &standalone::isTextInputActive,
          "Return True while a text input owns the keyboard (ImGui io.WantTextInput)");

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

namespace
{
PlatformHooks makeStandaloneHooks()
{
    PlatformHooks hooks;
    hooks.registerPlatformBindings = &registerStandaloneBindings;
    return hooks;
}
const PlatformHooks s_standaloneHooks = makeStandaloneHooks();
} // namespace

} // namespace ui
} // namespace omni

PYBIND11_MODULE(_standalone, m)
{
    m.doc() = "Standalone bridge of omni.ui; import it before omni.ui._ui.";
    omni::ui::setPlatformHooks(&omni::ui::s_standaloneHooks);
}
