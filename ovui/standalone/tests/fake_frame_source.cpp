/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// A fake renderer slot for native frame pacing, for tests.
//
// It fills the function table of NativeFramePacingHooks. Its worker produces
// one image for every camera publication: a GPU-resident image from a CUDA
// buffer, or a host copy when ovui says GPU mapping is off. Built without the
// CUDA toolkit (OMNIUI_FAKE_FRAME_SOURCE_CUDA undefined), it offers host copies
// only, so the tests of the pacing logic also run on a computer without a GPU. A test loads this
// library with ctypes, installs the table, and starts a pacing session with
// omni.ui._ui._native_frame_pacing_start. The library needs no link to ovui:
// everything goes through the table.

#include "NativeFramePacingHooks.h"

#ifdef OMNIUI_FAKE_FRAME_SOURCE_CUDA
#    include <cuda_runtime.h>
#endif

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>

using namespace omni::ui::standalone;

namespace
{
constexpr uint32_t kSide = 64;

const NativeFramePacingHost* g_host = nullptr;
uint64_t g_token = 0;
std::thread g_worker;
std::atomic<bool> g_workerDone{ true };
std::atomic<uint64_t> g_frames{ 0 };
// A paused worker parks until ovui resumes or closes the session.
std::mutex g_parkMutex;
std::condition_variable g_parkCv;
bool g_resumeRequested = false;
bool g_closeRequested = false;
void* g_device = nullptr;
std::vector<uint8_t> g_hostPixels(kSide * kSide * 4, 0x55);

void ensureDeviceBuffer()
{
#ifdef OMNIUI_FAKE_FRAME_SOURCE_CUDA
    if (g_device)
        return;
    std::vector<uint8_t> pixels(kSide * kSide * 4, 0x99);
    if (cudaMalloc(&g_device, pixels.size()) == cudaSuccess)
        cudaMemcpy(g_device, pixels.data(), pixels.size(), cudaMemcpyHostToDevice);
    else
        g_device = nullptr;
#endif
}

void renderLoop(double& endTime)
{
    double world[16];
    while (g_host->waitForWork(g_host->context, g_token, world))
    {
        NativeFramePacingStepDesc desc{};
        desc.structSize = sizeof(desc);
        g_host->beginStep(g_host->context, g_token, world, &desc);

        NativeFramePacingImage image{};
        image.width = kSide;
        image.height = kSide;
        image.pixelFormat = eNativeFramePacingRgba8Unorm;
        if (desc.allowGpuMapping && g_device)
        {
            image.gpuResident = 1;
            image.devicePtr = g_device;
            image.deviceRowStride = kSide * 4;
        }
        else
        {
            image.pixels = g_hostPixels.data();
            image.pixelsSize = g_hostPixels.size();
        }
        endTime += 0.016;
        NativeFramePacingStepOutput out{};
        out.structSize = sizeof(out);
        out.status = eNativeFramePacingGroupReady;
        out.groupValid = 1;
        out.group.images = &image;
        out.group.frameEndTimes = &endTime;
        out.group.imageCount = 1;
        for (int i = 0; i < 16; i += 5)
            out.group.cameraWorld[i] = 1.0;
        uint64_t stream = 0;
        g_host->publishGroup(g_host->context, g_token, &out, &stream);
        ++g_frames;
    }
}

void workerMain()
{
    double endTime = 0.0;
    while (true)
    {
        renderLoop(endTime);
        if (g_host->renderLoopEnded(g_host->context, g_token) != eNativeFramePacingLoopParked)
            break;
        {
            std::unique_lock<std::mutex> lock(g_parkMutex);
            g_parkCv.wait(lock, []() { return g_resumeRequested || g_closeRequested; });
            g_resumeRequested = false;
        }
        // ovui decides: a resume runs the loop again, a stop ends it.
        if (!g_host->renderResumed(g_host->context, g_token))
            break;
    }
    g_workerDone = true;
}

uint32_t openRenderer(uint64_t token, const NativeFramePacingOpenDesc* desc)
{
    if (g_worker.joinable())
        g_worker.join();
    ensureDeviceBuffer();
    g_host = desc->host;
    g_token = token;
    {
        std::lock_guard<std::mutex> lock(g_parkMutex);
        g_resumeRequested = false;
        g_closeRequested = false;
    }
    g_workerDone = false;
    g_worker = std::thread(workerMain);
    return eNativeFramePacingOk;
}
bool pauseRenderWorker(uint64_t) { return true; }
bool resumeRenderWorker(uint64_t)
{
    {
        std::lock_guard<std::mutex> lock(g_parkMutex);
        g_resumeRequested = true;
    }
    g_parkCv.notify_all();
    return !g_workerDone;
}
bool closeRenderer(uint64_t)
{
    {
        std::lock_guard<std::mutex> lock(g_parkMutex);
        g_closeRequested = true;
    }
    g_parkCv.notify_all();
    for (int i = 0; i < 500 && !g_workerDone; ++i)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    if (g_workerDone && g_worker.joinable())
        g_worker.join();
    return g_workerDone;
}
void shutdownWorker()
{
    if (g_worker.joinable())
        g_worker.join();
}
void readRendererInfo(uint64_t, NativeFramePacingRendererInfo* info)
{
    std::memset(info, 0, sizeof(*info));
    info->structSize = sizeof(*info);
}
size_t lastError(char*, size_t) { return 0; }
void queryCapabilities(NativeFramePacingCapabilities* caps)
{
    caps->operatesOffUiThread = 1;
    caps->usesOwnQueue = 1;
    caps->presentReadsImages = 1;
}
void cancel(uint64_t) {}

// A std::thread that is still joinable at exit ends the process.
struct WorkerGuard
{
    ~WorkerGuard()
    {
        if (g_worker.joinable())
            g_worker.join();
    }
} g_guard;

NativeFramePacingHooks g_hooks = {
    sizeof(NativeFramePacingHooks), kNativeFramePacingHooksVersion, openRenderer, pauseRenderWorker,
    resumeRenderWorker, closeRenderer, shutdownWorker, readRendererInfo, lastError, queryCapabilities, cancel,
};
} // namespace

extern "C"
{
/// The table to install with omni.ui._ui._set_native_frame_pacing_hooks.
const void* omniui_fake_frame_source_hooks()
{
    return &g_hooks;
}

/// Frames that the fake worker has handed to ovui.
uint64_t omniui_fake_frame_source_frames()
{
    return g_frames.load();
}

/// True when the fake source has a CUDA buffer, so it can offer GPU images.
int omniui_fake_frame_source_has_device_buffer()
{
    ensureDeviceBuffer();
    return g_device != nullptr;
}
}
