/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "NativeFramePacing.h"

#include <omni/ui/ImageProvider/ByteImageProvider.h>

namespace omni {
namespace ui {
namespace standalone {

namespace {
NativeFramePacingStats g_stats;
double g_rate = 0.0;
}

bool setNativeFramePacingPresentRate(double rate)
{
    if (rate == 0.0) { g_rate = 0.0; return true; }
    g_stats.statusReason = "backend_unavailable";
    g_stats.lastError = "native frame pacing requires Vulkan";
    return false;
}
double getNativeFramePacingPresentRate() { return g_rate; }
uint64_t startNativeFramePacing(uintptr_t, const char*, uint32_t, uint32_t, uint32_t,
                                std::shared_ptr<ByteImageProvider>, const char*, const char*, uint32_t, uint32_t)
{ return 0; }
bool publishNativeFramePacingState(uint64_t, uint32_t, uint32_t, const std::array<double, 16>&,
                                   const std::array<double, 3>&, double) { return false; }
bool pauseNativeFramePacingRender(uint64_t) { return false; }
bool resumeNativeFramePacingRender(uint64_t, bool) { return false; }
bool setNativeFramePacingRenderPolicy(uint64_t, const char*, uint32_t) { return false; }
bool requestNativeFramePacingRender(uint64_t) { return false; }
bool stopNativeFramePacing(uint64_t) { return false; }
NativeFramePacingStats getNativeFramePacingStats()
{
    g_stats.supported = false;
    g_stats.active = false;
    g_stats.presentRate = g_rate;
    g_stats.statusReason = "backend_unavailable";
    g_stats.dlssGeneratedFrameCapability =
        "ordered results require Vulkan; activation unavailable through a supported public control";
    return g_stats;
}
void resetFrameThroughputMetrics() { g_stats = NativeFramePacingStats{}; }
void recordSynchronousRendererCompletion() {}
void recordSynchronousContentSelection() {}
void beginNativeFramePacingUiUpdate(VulkanBackend*) {}
bool submitNativeFramePacingDrawData(VulkanBackend*, const ImDrawData*, int, int, uint64_t*, bool) { return false; }
bool waitNativeFramePacingPresentation(uint64_t, uint64_t) { return false; }
void registerNativeFramePacingBackend(VulkanBackend*) {}
void shutdownNativeFramePacing() {}

} // namespace standalone
} // namespace ui
} // namespace omni
