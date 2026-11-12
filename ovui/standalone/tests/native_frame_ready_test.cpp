/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// A frame source gives each paced image a completion event (rule 34.7). Here
// the image is written late, on a stream that the legacy default stream does
// not wait for. ovui's copy, queued on the legacy default stream after
// waitForPacedImage(), must still see the finished image.

#include "NativeFrameReady.h"

#include <cuda_runtime.h>

#include <chrono>
#include <cstdio>
#include <thread>
#include <vector>

using omni::ui::standalone::waitForPacedImage;

namespace
{
constexpr size_t kBytes = 64 * 64 * 4;

int g_failures = 0;

void check(bool condition, const char* what)
{
    if (!condition)
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        std::fprintf(stderr, "FAIL: %s\n", what);
        ++g_failures;
    }
}

void CUDART_CB holdTheStream(void*)
{
    // The renderer is still working on the frame.
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
}
} // namespace

int main()
{
    int devices = 0;
    if (cudaGetDeviceCount(&devices) != cudaSuccess || devices == 0)
    {
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        std::fprintf(stderr, "FAIL: no CUDA device\n");
        return 1;
    }

    cudaStream_t rendererStream = nullptr;
    cudaEvent_t ready = nullptr;
    void* image = nullptr;
    void* copy = nullptr;
    check(cudaStreamCreateWithFlags(&rendererStream, cudaStreamNonBlocking) == cudaSuccess, "create stream");
    check(cudaEventCreateWithFlags(&ready, cudaEventDisableTiming) == cudaSuccess, "create event");
    check(cudaMalloc(&image, kBytes) == cudaSuccess && cudaMalloc(&copy, kBytes) == cudaSuccess, "allocate");
    check(cudaMemset(image, 0, kBytes) == cudaSuccess && cudaMemset(copy, 0, kBytes) == cudaSuccess, "clear");
    check(cudaDeviceSynchronize() == cudaSuccess, "initial sync");

    // The frame is written after a delay, then its completion event is recorded.
    check(cudaLaunchHostFunc(rendererStream, holdTheStream, nullptr) == cudaSuccess, "delay the frame");
    check(cudaMemsetAsync(image, 0xAB, kBytes, rendererStream) == cudaSuccess, "write the frame");
    check(cudaEventRecord(ready, rendererStream) == cudaSuccess, "record the completion event");

    // ovui's side: wait for the event, then copy on the legacy default stream.
    check(waitForPacedImage(0, reinterpret_cast<uint64_t>(ready)), "wait accepts the event");
    check(cudaMemcpyAsync(copy, image, kBytes, cudaMemcpyDeviceToDevice, cudaStreamLegacy) == cudaSuccess, "copy");
    check(cudaStreamSynchronize(cudaStreamLegacy) == cudaSuccess, "copy finished");

    std::vector<unsigned char> pixels(kBytes, 0);
    check(cudaMemcpy(pixels.data(), copy, kBytes, cudaMemcpyDeviceToHost) == cudaSuccess, "read back");
    size_t finished = 0;
    for (unsigned char value : pixels)
        finished += value == 0xAB ? 1 : 0;
    if (finished != kBytes)
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        std::fprintf(stderr, "copied %zu of %zu finished bytes\n", finished, kBytes);
    check(finished == kBytes, "the copy read the finished frame, not an earlier state");

    // Without an event, ovui can only follow an image that is already
    // complete or that is on the legacy default stream.
    check(waitForPacedImage(0, 0), "complete image without an event");
    check(waitForPacedImage(1, 0), "legacy default stream without an event");
    check(!waitForPacedImage(5, 0), "another stream without an event is refused");

    cudaDeviceSynchronize();
    cudaFree(image);
    cudaFree(copy);
    cudaEventDestroy(ready);
    cudaStreamDestroy(rendererStream);
    if (g_failures == 0)
        // logging: allow printf - carb-free test program; no OMNI_LOG/Carbonite channel is available here
        std::printf("native_frame_ready_test: PASS\n");
    return g_failures == 0 ? 0 : 1;
}
