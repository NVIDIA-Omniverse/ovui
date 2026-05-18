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

// Standalone test: Vulkan streaming pipeline (VkImage → encode → .h264 file)
//
// Renders 60 frames via VulkanBackend, encodes each via the streaming
// pipeline, writes output to a .h264 file, and prints FPS/latency stats.
//
// Build:
//   The test is built by CMake as test_vulkan_streaming when Vulkan is found.
//
// Usage:
//   OMNIUI_BACKEND=vulkan ./test_vulkan_streaming [output.h264] [frame_count]
//
// Environment:
//   OMNIUI_BACKEND=vulkan        — required (selects Vulkan backend)
//   OMNIUI_STREAM_BACKEND=vulkan — optional (auto-init streaming in init())
//   Video_Codec_SDK_DIR=...      — optional (enables NVENC hardware encoder)

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <chrono>
#include <string>
#include <vector>
#include <algorithm>
#include <numeric>

// Force Vulkan backend via env
static void ensureVulkanBackend()
{
#ifdef _WIN32
    _putenv_s("OMNIUI_BACKEND", "vulkan");
#else
    setenv("OMNIUI_BACKEND", "vulkan", 1);
#endif
}

// We include the standalone headers directly
#include "StandaloneInit.h"
#include "StreamingVulkan.h"
#include "VulkanBackend.h"
#include "GlfwPlatform.h"

using Clock = std::chrono::high_resolution_clock;

// ---------------------------------------------------------------------------
// NAL file writer
// ---------------------------------------------------------------------------
struct NalFileWriter
{
    FILE* fp = nullptr;
    size_t totalBytes = 0;
    uint32_t nalCount = 0;

    bool open(const char* path)
    {
        fp = fopen(path, "wb");
        if (!fp)
        {
            fprintf(stderr, "ERROR: cannot open %s for writing\n", path);
            return false;
        }
        return true;
    }

    void write(const uint8_t* data, uint32_t size, uint64_t /*pts*/)
    {
        if (!fp) return;
        fwrite(data, 1, size, fp);
        totalBytes += size;
        nalCount++;
    }

    void close()
    {
        if (fp) { fclose(fp); fp = nullptr; }
    }
};

static NalFileWriter g_writer;

static void nalCallback(const uint8_t* data, uint32_t size, uint64_t pts)
{
    g_writer.write(data, size, pts);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
int main(int argc, char** argv)
{
    const char* outputPath = "test_output.h264";
    int frameCount = 60;

    if (argc >= 2) outputPath = argv[1];
    if (argc >= 3) frameCount = atoi(argv[2]);
    if (frameCount <= 0) frameCount = 60;

    fprintf(stdout, "=== Vulkan Streaming Pipeline Test ===\n");
    fprintf(stdout, "Output:  %s\n", outputPath);
    fprintf(stdout, "Frames:  %d\n", frameCount);

    // Force Vulkan backend
    ensureVulkanBackend();

    // Initialize the standalone platform
    namespace sa = omni::ui::standalone;

    if (!sa::init("Vulkan Streaming Test", 1280, 720))
    {
        fprintf(stderr, "FAIL: standalone::init() failed\n");
        return 1;
    }

    // Initialize streaming pipeline
    if (!sa::initStreaming(60, 10))
    {
        fprintf(stderr, "FAIL: initStreaming() failed\n");
        sa::shutdown();
        return 1;
    }

    fprintf(stdout, "Encoder: %s\n", sa::getStreamEncoderName());
    fprintf(stdout, "Active:  %s\n", sa::isStreamingActive() ? "yes" : "no");

    // Open output file
    if (!g_writer.open(outputPath))
    {
        sa::shutdownStreaming();
        sa::shutdown();
        return 1;
    }
    sa::setStreamNalCallback(nalCallback);

    // Collect per-frame stats
    struct FrameInfo {
        double tickMs;
        double encodeMs;
        double totalMs;
        uint32_t nalSize;
    };
    std::vector<FrameInfo> stats;
    stats.reserve(frameCount);

    auto testStart = Clock::now();

    // Render + encode loop
    for (int i = 0; i < frameCount; i++)
    {
        auto frameStart = Clock::now();

        // Tick the platform (renders one frame)
        if (!sa::tick())
        {
            fprintf(stderr, "WARNING: tick() returned false at frame %d\n", i);
            break;
        }

        auto tickEnd = Clock::now();
        double tickMs = std::chrono::duration<double, std::milli>(tickEnd - frameStart).count();

        // Encode the rendered frame
        bool encOk = sa::encodeStreamFrame();
        if (!encOk)
        {
            fprintf(stderr, "WARNING: encodeStreamFrame() failed at frame %d\n", i);
            continue;
        }

        auto encEnd = Clock::now();
        double encodeMs = std::chrono::duration<double, std::milli>(encEnd - tickEnd).count();
        double totalMs  = std::chrono::duration<double, std::milli>(encEnd - frameStart).count();

        stats.push_back({tickMs, encodeMs, totalMs, g_writer.nalCount > 0 ? 1u : 0u});

        // Progress indicator
        if ((i + 1) % 10 == 0 || i == frameCount - 1)
            fprintf(stdout, "  frame %d/%d  (tick=%.1fms encode=%.1fms)\n",
                    i + 1, frameCount, tickMs, encodeMs);
    }

    auto testEnd = Clock::now();
    double totalTestMs = std::chrono::duration<double, std::milli>(testEnd - testStart).count();

    // Close output file
    g_writer.close();

    // Print stats
    fprintf(stdout, "\n=== Results ===\n");
    fprintf(stdout, "Frames encoded:  %d\n", (int)stats.size());
    fprintf(stdout, "NAL units:       %u\n", g_writer.nalCount);
    fprintf(stdout, "Output size:     %.1f KB\n", g_writer.totalBytes / 1024.0);
    fprintf(stdout, "Total time:      %.1f ms\n", totalTestMs);

    if (!stats.empty())
    {
        double avgTick = 0, avgEncode = 0, avgTotal = 0;
        double minTotal = 1e9, maxTotal = 0;
        for (auto& s : stats)
        {
            avgTick   += s.tickMs;
            avgEncode += s.encodeMs;
            avgTotal  += s.totalMs;
            minTotal = std::min(minTotal, s.totalMs);
            maxTotal = std::max(maxTotal, s.totalMs);
        }
        int n = (int)stats.size();
        avgTick   /= n;
        avgEncode /= n;
        avgTotal  /= n;

        double fps = (totalTestMs > 0) ? (n * 1000.0 / totalTestMs) : 0;

        // Compute p50/p99 latency
        std::vector<double> latencies;
        latencies.reserve(n);
        for (auto& s : stats) latencies.push_back(s.totalMs);
        std::sort(latencies.begin(), latencies.end());
        double p50 = latencies[n / 2];
        double p99 = latencies[std::min(n - 1, (int)(n * 0.99))];

        fprintf(stdout, "\nFPS:             %.1f\n", fps);
        fprintf(stdout, "Avg tick:        %.2f ms\n", avgTick);
        fprintf(stdout, "Avg encode:      %.2f ms\n", avgEncode);
        fprintf(stdout, "Avg total:       %.2f ms\n", avgTotal);
        fprintf(stdout, "Min latency:     %.2f ms\n", minTotal);
        fprintf(stdout, "Max latency:     %.2f ms\n", maxTotal);
        fprintf(stdout, "P50 latency:     %.2f ms\n", p50);
        fprintf(stdout, "P99 latency:     %.2f ms\n", p99);
    }

    // Cleanup
    sa::shutdownStreaming();
    sa::shutdown();

    fprintf(stdout, "\n=== %s ===\n",
            (stats.size() == (size_t)frameCount) ? "PASS" : "PARTIAL");
    return (stats.size() == (size_t)frameCount) ? 0 : 1;
}
