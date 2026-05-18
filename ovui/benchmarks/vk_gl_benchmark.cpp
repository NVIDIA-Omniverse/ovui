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

// GL vs Vulkan performance benchmark for ovui.
// Measures frame time, CPU time, GPU time (via queries), memory, and readback latency.
//
// Usage:
//   vk_gl_benchmark [--backend gl|vk|both] [--frames N] [--widgets N,N,...]
//                   [--offscreen] [--json path] [--warmup N]

#if defined(_WIN32)
#  ifndef NOMINMAX
#    define NOMINMAX
#  endif
#  ifndef WIN32_LEAN_AND_MEAN
#    define WIN32_LEAN_AND_MEAN
#  endif
#endif

#include "GlfwPlatform.h"
#include "StandaloneInit.h"
#include "OpenGLRenderer.h"

#include <omni/ui/platform/PlatformRegistry.h>

#ifdef OMNIUI_HAS_VULKAN
#include "VulkanBackend.h"
#include <vulkan/vulkan.h>
#endif

#include <imgui/imgui.h>
#include <imgui/backends/imgui_impl_glfw.h>
#include <imgui/backends/imgui_impl_opengl3.h>
#ifdef OMNIUI_HAS_VULKAN
#include <imgui/backends/imgui_impl_vulkan.h>
#endif
#include <glad/glad.h>
#include <GLFW/glfw3.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <numeric>
#include <sstream>
#include <string>
#include <vector>

#ifdef __linux__
#include <unistd.h>
#include <sys/wait.h>
#endif

#ifdef __APPLE__
#include <mach/mach.h>
#endif

using Clock = std::chrono::steady_clock;
using Duration = std::chrono::duration<double, std::milli>; // milliseconds

// ---------------------------------------------------------------------------
// Statistics
// ---------------------------------------------------------------------------

struct Stats
{
    double minVal = 0;
    double maxVal = 0;
    double avg = 0;
    double p99 = 0;
};

static Stats computeStats(std::vector<double>& samples)
{
    if (samples.empty())
        return {};
    std::sort(samples.begin(), samples.end());
    Stats s;
    s.minVal = samples.front();
    s.maxVal = samples.back();
    double sum = 0;
    for (double v : samples)
        sum += v;
    s.avg = sum / (double)samples.size();
    size_t p99Idx = std::min((size_t)(samples.size() * 0.99), samples.size() - 1);
    s.p99 = samples[p99Idx];
    return s;
}

// ---------------------------------------------------------------------------
// Memory measurement
// ---------------------------------------------------------------------------

static double getRSSMegabytes()
{
#ifdef __linux__
    FILE* f = fopen("/proc/self/statm", "r");
    if (!f)
        return 0.0;
    long pages = 0;
    if (fscanf(f, "%*d %ld", &pages) != 1)
        pages = 0;
    fclose(f);
    long pageSize = sysconf(_SC_PAGESIZE);
    return (double)(pages * pageSize) / (1024.0 * 1024.0);
#elif defined(__APPLE__)
    mach_task_basic_info_data_t info;
    mach_msg_type_number_t count = MACH_TASK_BASIC_INFO_COUNT;
    if (task_info(mach_task_self(), MACH_TASK_BASIC_INFO, (task_info_t)&info, &count) == KERN_SUCCESS)
        return (double)info.resident_size / (1024.0 * 1024.0);
    return 0.0;
#else
    return 0.0;
#endif
}

// ---------------------------------------------------------------------------
// GL timer queries (GL_TIME_ELAPSED)
// ---------------------------------------------------------------------------

struct GLTimerQuery
{
    GLuint query = 0;
    bool supported = false;

    void init()
    {
        if (glGenQueries)
        {
            glGenQueries(1, &query);
            supported = (query != 0);
        }
    }

    void destroy()
    {
        if (query)
        {
            glDeleteQueries(1, &query);
            query = 0;
        }
    }

    void begin()
    {
        if (supported)
            glBeginQuery(GL_TIME_ELAPSED, query);
    }

    void end()
    {
        if (supported)
            glEndQuery(GL_TIME_ELAPSED);
    }

    double getElapsedMs()
    {
        if (!supported)
            return 0.0;
        GLuint64 elapsed = 0;
        glGetQueryObjectui64v(query, GL_QUERY_RESULT, &elapsed);
        return (double)elapsed / 1e6; // ns -> ms
    }
};

// ---------------------------------------------------------------------------
// Vulkan timestamp queries (VK_TIMESTAMP)
// ---------------------------------------------------------------------------

#ifdef OMNIUI_HAS_VULKAN
struct VkTimestampQuery
{
    VkQueryPool pool = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    float timestampPeriod = 0.0f;
    bool supported = false;

    void init(VkDevice dev, VkPhysicalDevice physDev)
    {
        device = dev;
        VkPhysicalDeviceProperties props;
        vkGetPhysicalDeviceProperties(physDev, &props);
        timestampPeriod = props.limits.timestampPeriod;

        if (timestampPeriod == 0.0f)
            return;

        VkQueryPoolCreateInfo info = {};
        info.sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO;
        info.queryType = VK_QUERY_TYPE_TIMESTAMP;
        info.queryCount = 2;
        if (vkCreateQueryPool(device, &info, nullptr, &pool) == VK_SUCCESS)
            supported = true;
    }

    void destroy()
    {
        if (pool != VK_NULL_HANDLE && device != VK_NULL_HANDLE)
        {
            vkDestroyQueryPool(device, pool, nullptr);
            pool = VK_NULL_HANDLE;
        }
    }

    void reset(VkCommandBuffer cmd)
    {
        if (supported)
            vkCmdResetQueryPool(cmd, pool, 0, 2);
    }

    void writeBegin(VkCommandBuffer cmd)
    {
        if (supported)
            vkCmdWriteTimestamp(cmd, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, pool, 0);
    }

    void writeEnd(VkCommandBuffer cmd)
    {
        if (supported)
            vkCmdWriteTimestamp(cmd, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, pool, 1);
    }

    double getElapsedMs()
    {
        if (!supported)
            return 0.0;
        uint64_t timestamps[2] = {};
        VkResult res = vkGetQueryPoolResults(
            device, pool, 0, 2, sizeof(timestamps), timestamps,
            sizeof(uint64_t), VK_QUERY_RESULT_64_BIT | VK_QUERY_RESULT_WAIT_BIT);
        if (res != VK_SUCCESS)
            return 0.0;
        double ticks = (double)(timestamps[1] - timestamps[0]);
        return ticks * (double)timestampPeriod / 1e6;
    }
};
#endif

// ---------------------------------------------------------------------------
// Widget scene generation (raw ImGui calls -- same work for both backends)
// ---------------------------------------------------------------------------

static void drawWidgetScene(int widgetCount)
{
    ImGui::SetNextWindowPos(ImVec2(0, 0));
    ImGui::SetNextWindowSize(ImGui::GetIO().DisplaySize);
    ImGui::Begin("##BenchScene", nullptr,
                 ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize |
                     ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoCollapse);

    char buf[64];
    for (int i = 0; i < widgetCount; ++i)
    {
        ImGui::PushID(i);
        switch (i % 6)
        {
        case 0:
            snprintf(buf, sizeof(buf), "Button %d", i);
            ImGui::Button(buf, ImVec2(120, 24));
            break;
        case 1:
            snprintf(buf, sizeof(buf), "Label %d", i);
            ImGui::TextUnformatted(buf);
            break;
        case 2: {
            float v = (float)(i % 100) / 100.0f;
            snprintf(buf, sizeof(buf), "##slider%d", i);
            ImGui::SliderFloat(buf, &v, 0.0f, 1.0f);
            break;
        }
        case 3:
            ImGui::ProgressBar((float)(i % 100) / 100.0f, ImVec2(-1, 0));
            break;
        case 4: {
            bool checked = (i % 2 == 0);
            snprintf(buf, sizeof(buf), "Check %d", i);
            ImGui::Checkbox(buf, &checked);
            break;
        }
        case 5: {
            float v = (float)(i % 50);
            snprintf(buf, sizeof(buf), "##drag%d", i);
            ImGui::DragFloat(buf, &v, 1.0f, 0.0f, 100.0f);
            break;
        }
        }
        ImGui::PopID();
    }

    ImGui::End();
}

// ---------------------------------------------------------------------------
// Result storage
// ---------------------------------------------------------------------------

struct BenchResult
{
    std::string backend;
    int widgetCount = 0;
    bool offscreen = false;
    int frameCount = 0;
    Stats frameTime;
    Stats cpuTime;
    Stats gpuTime;
    double readbackAvgMs = 0.0;
    double rssMB = 0.0;
    bool gpuTimingAvailable = false;
};

// ---------------------------------------------------------------------------
// Terminal table output
// ---------------------------------------------------------------------------

static void printHeader()
{
    printf("\n=== GL vs VK Benchmark Results ===\n\n");
    printf("%-8s %-8s %-7s %-24s %-24s %-24s %-14s %-8s\n",
           "Backend", "Widgets", "Mode",
           "FrameTime(ms)", "CPU(ms)", "GPU(ms)",
           "Readback(ms)", "RSS(MB)");
    printf("%-8s %-8s %-7s %-24s %-24s %-24s %-14s %-8s\n",
           "", "", "",
           "min/avg/max/p99", "min/avg/max/p99", "min/avg/max/p99",
           "avg", "");
    printf("-------  -------  ------  -----------------------  "
           "-----------------------  -----------------------  "
           "-------------  -------\n");
}

static void printResult(const BenchResult& r)
{
    char ft[64], ct[64], gt[64];
    snprintf(ft, sizeof(ft), "%.2f/%.2f/%.2f/%.2f",
             r.frameTime.minVal, r.frameTime.avg, r.frameTime.maxVal, r.frameTime.p99);
    snprintf(ct, sizeof(ct), "%.2f/%.2f/%.2f/%.2f",
             r.cpuTime.minVal, r.cpuTime.avg, r.cpuTime.maxVal, r.cpuTime.p99);
    if (r.gpuTimingAvailable)
        snprintf(gt, sizeof(gt), "%.2f/%.2f/%.2f/%.2f",
                 r.gpuTime.minVal, r.gpuTime.avg, r.gpuTime.maxVal, r.gpuTime.p99);
    else
        snprintf(gt, sizeof(gt), "n/a");

    printf("%-8s %-8d %-7s %-24s %-24s %-24s %-14.2f %-8.1f\n",
           r.backend.c_str(), r.widgetCount,
           r.offscreen ? "offscr" : "window",
           ft, ct, gt,
           r.readbackAvgMs, r.rssMB);
}

// ---------------------------------------------------------------------------
// JSON output
// ---------------------------------------------------------------------------

static std::string statsToJson(const Stats& s, bool available)
{
    if (!available)
        return "null";
    char buf[256];
    snprintf(buf, sizeof(buf),
             "{\"min\":%.4f,\"avg\":%.4f,\"max\":%.4f,\"p99\":%.4f}",
             s.minVal, s.avg, s.maxVal, s.p99);
    return buf;
}

static std::string resultToJson(const BenchResult& r)
{
    std::ostringstream os;
    os << "    {\n"
       << "      \"backend\": \"" << r.backend << "\",\n"
       << "      \"widgets\": " << r.widgetCount << ",\n"
       << "      \"mode\": \"" << (r.offscreen ? "offscreen" : "windowed") << "\",\n"
       << "      \"frames\": " << r.frameCount << ",\n"
       << "      \"frame_time_ms\": " << statsToJson(r.frameTime, true) << ",\n"
       << "      \"cpu_time_ms\": " << statsToJson(r.cpuTime, true) << ",\n"
       << "      \"gpu_time_ms\": " << statsToJson(r.gpuTime, r.gpuTimingAvailable) << ",\n"
       << "      \"readback_avg_ms\": " << r.readbackAvgMs << ",\n"
       << "      \"rss_mb\": " << r.rssMB << "\n"
       << "    }";
    return os.str();
}

static void writeJsonResults(const char* path, const std::vector<BenchResult>& results)
{
    std::ofstream f(path);
    if (!f.is_open())
    {
        fprintf(stderr, "Error: cannot write JSON to %s\n", path);
        return;
    }
    f << "{\n  \"results\": [\n";
    for (size_t i = 0; i < results.size(); ++i)
    {
        f << resultToJson(results[i]);
        if (i + 1 < results.size())
            f << ",";
        f << "\n";
    }
    f << "  ]\n}\n";
    f.close();
    printf("\nJSON results written to %s\n", path);
}

// ---------------------------------------------------------------------------
// Parse comma-separated ints
// ---------------------------------------------------------------------------

static std::vector<int> parseIntList(const char* str)
{
    std::vector<int> out;
    std::istringstream ss(str);
    std::string token;
    while (std::getline(ss, token, ','))
    {
        int v = atoi(token.c_str());
        if (v > 0)
            out.push_back(v);
    }
    return out;
}

// ---------------------------------------------------------------------------
// Render one full frame (replicates GlfwPlatform::tick() render loop)
// ---------------------------------------------------------------------------

struct FrameContext
{
    bool isVulkan = false;
    GLFWwindow* window = nullptr;
#ifdef OMNIUI_HAS_VULKAN
    omni::ui::standalone::VulkanBackend* vkBackend = nullptr;
#endif
};

static void renderFrame(const FrameContext& ctx, int widgetCount)
{
    glfwPollEvents();

#ifdef OMNIUI_HAS_VULKAN
    if (ctx.isVulkan)
        ImGui_ImplVulkan_NewFrame();
    else
#endif
        ImGui_ImplOpenGL3_NewFrame();

    ImGui_ImplGlfw_NewFrame();
    ImGui::NewFrame();
    drawWidgetScene(widgetCount);
    ImGui::Render();

#ifdef OMNIUI_HAS_VULKAN
    if (ctx.isVulkan && ctx.vkBackend)
    {
        int dw, dh;
        glfwGetWindowSize(ctx.window, &dw, &dh);
        if (dw > 0 && dh > 0)
        {
            ctx.vkBackend->beginFrame(dw, dh);
            ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(),
                                             ctx.vkBackend->getCommandBuffer());
            ctx.vkBackend->endFrame();
        }
    }
    else
#endif
    {
        int dw, dh;
        glfwGetFramebufferSize(ctx.window, &dw, &dh);
        glViewport(0, 0, dw, dh);
        glClearColor(0.12f, 0.13f, 0.14f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
        glfwSwapBuffers(ctx.window);
    }
}

// ---------------------------------------------------------------------------
// Forward declaration
// ---------------------------------------------------------------------------

static std::vector<BenchResult> runBenchmarks(
    const char* backend, const std::vector<int>& widgetCounts,
    int numFrames, int warmupFrames, bool offscreen);

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

int main(int argc, char** argv)
{
    std::string backendArg = "both";
    std::vector<int> widgetCounts = {10, 100, 500, 1000};
    int numFrames = 1000;
    int warmupFrames = 100;
    bool offscreen = false;
    std::string jsonPath;

    for (int i = 1; i < argc; ++i)
    {
        if (strcmp(argv[i], "--backend") == 0 && i + 1 < argc)
            backendArg = argv[++i];
        else if (strcmp(argv[i], "--frames") == 0 && i + 1 < argc)
            numFrames = atoi(argv[++i]);
        else if (strcmp(argv[i], "--warmup") == 0 && i + 1 < argc)
            warmupFrames = atoi(argv[++i]);
        else if (strcmp(argv[i], "--widgets") == 0 && i + 1 < argc)
            widgetCounts = parseIntList(argv[++i]);
        else if (strcmp(argv[i], "--offscreen") == 0)
            offscreen = true;
        else if (strcmp(argv[i], "--json") == 0 && i + 1 < argc)
            jsonPath = argv[++i];
        else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0)
        {
            printf("Usage: %s [options]\n"
                   "  --backend gl|vk|both   Backend to benchmark (default: both)\n"
                   "  --frames N             Frames per test (default: 1000)\n"
                   "  --warmup N             Warmup frames (default: 100)\n"
                   "  --widgets N,N,...       Widget counts (default: 10,100,500,1000)\n"
                   "  --offscreen            Hide window\n"
                   "  --json <path>          Write JSON results\n",
                   argv[0]);
            return 0;
        }
    }

    // --backend both: spawn child processes (GL and VK can't coexist in one GLFW window)
    if (backendArg == "both")
    {
        printf("Running GL and VK benchmarks (spawning child processes)...\n\n");

        std::vector<std::string> commonArgs;
        for (int i = 1; i < argc; ++i)
        {
            if (strcmp(argv[i], "--backend") == 0 && i + 1 < argc)
            {
                ++i;
                continue;
            }
            if (strcmp(argv[i], "--json") == 0 && i + 1 < argc)
            {
                ++i;
                continue;
            }
            commonArgs.push_back(argv[i]);
        }

        auto runChild = [&](const char* be, const char* suffix) -> int {
            std::string cmd;
            cmd += "\"";
            cmd += argv[0];
            cmd += "\" --backend ";
            cmd += be;
            for (auto& a : commonArgs)
            {
                cmd += " \"";
                cmd += a;
                cmd += "\"";
            }
            if (!jsonPath.empty())
            {
                cmd += " --json \"";
                cmd += jsonPath + "." + suffix;
                cmd += "\"";
            }
            printf("--- Running: %s ---\n", cmd.c_str());
            return system(cmd.c_str());
        };

        int glRet = runChild("gl", "gl");
        printf("\n");
        int vkRet = runChild("vk", "vk");

        // Merge JSON files if requested
        if (!jsonPath.empty())
        {
            std::string glJsonPath = jsonPath + ".gl";
            std::string vkJsonPath = jsonPath + ".vk";

            std::ofstream merged(jsonPath);
            merged << "{\n  \"results\": [\n";

            auto appendResults = [&](const std::string& path, bool& needComma) {
                std::ifstream f(path);
                if (!f.is_open())
                    return;
                std::string line;
                bool inResults = false;
                while (std::getline(f, line))
                {
                    if (line.find("\"results\"") != std::string::npos)
                    {
                        inResults = true;
                        continue;
                    }
                    if (inResults && line.find("]") != std::string::npos)
                    {
                        inResults = false;
                        continue;
                    }
                    if (inResults && line.find("{") != std::string::npos && needComma)
                        merged << ",\n";
                    if (inResults && !line.empty())
                    {
                        merged << line << "\n";
                        if (line.find("}") != std::string::npos)
                            needComma = true;
                    }
                }
                std::remove(path.c_str());
            };

            bool needComma = false;
            appendResults(glJsonPath, needComma);
            appendResults(vkJsonPath, needComma);

            merged << "  ]\n}\n";
            merged.close();
            printf("\nMerged JSON results written to %s\n", jsonPath.c_str());
        }

        return (glRet != 0 || vkRet != 0) ? 1 : 0;
    }

    // Single-backend mode
    auto results = runBenchmarks(backendArg.c_str(), widgetCounts, numFrames, warmupFrames, offscreen);

    if (results.empty())
    {
        printf("No results collected (backend may not be available).\n");
        return 1;
    }

    printHeader();
    for (auto& r : results)
        printResult(r);
    printf("\n");

    if (!jsonPath.empty())
        writeJsonResults(jsonPath.c_str(), results);

    return 0;
}

// ---------------------------------------------------------------------------
// Core benchmark loop
// ---------------------------------------------------------------------------

static std::vector<BenchResult> runBenchmarks(
    const char* backend, const std::vector<int>& widgetCounts,
    int numFrames, int warmupFrames, bool offscreen)
{
    std::vector<BenchResult> results;

    bool isVulkan = (strcmp(backend, "vk") == 0 || strcmp(backend, "vulkan") == 0);
    bool isGL = !isVulkan;

    if (isVulkan)
    {
#ifndef OMNIUI_HAS_VULKAN
        printf("Vulkan backend not compiled in -- skipping VK benchmarks.\n");
        return results;
#else
#  if defined(_WIN32)
        _putenv_s("OMNIUI_BACKEND", "vulkan");
#  else
        setenv("OMNIUI_BACKEND", "vulkan", 1);
#  endif
#endif
    }
    else
    {
#if defined(_WIN32)
        _putenv_s("OMNIUI_BACKEND", "");
#else
        unsetenv("OMNIUI_BACKEND");
#endif
    }

    if (!omni::ui::standalone::init("Benchmark", 1280, 720))
    {
        printf("Failed to initialize %s backend -- skipping.\n", backend);
        return results;
    }

    auto& reg = omni::ui::PlatformRegistry::instance();
    auto* platform = dynamic_cast<omni::ui::standalone::GlfwPlatform*>(reg.platform());

    if (!platform)
    {
        printf("Failed to get platform reference -- skipping.\n");
        omni::ui::standalone::shutdown();
        return results;
    }

    GLFWwindow* window = platform->getGlfwWindow();

    if (offscreen && window)
        glfwHideWindow(window);

    // Disable vsync for accurate timing
    if (isGL && window)
    {
        glfwMakeContextCurrent(window);
        glfwSwapInterval(0);
    }

    printf("Backend: %s | Frames: %d | Warmup: %d | Mode: %s\n\n",
           isVulkan ? "Vulkan" : "OpenGL", numFrames, warmupFrames,
           offscreen ? "offscreen" : "windowed");

    FrameContext ctx;
    ctx.isVulkan = isVulkan;
    ctx.window = window;

    GLTimerQuery glTimer;
    if (isGL)
        glTimer.init();

#ifdef OMNIUI_HAS_VULKAN
    VkTimestampQuery vkTimer;
    if (isVulkan)
    {
        ctx.vkBackend = platform->getVulkanBackend();
        if (ctx.vkBackend && ctx.vkBackend->isInitialized())
            vkTimer.init(ctx.vkBackend->getDevice(), ctx.vkBackend->getPhysicalDevice());
    }
#endif

    for (int wc : widgetCounts)
    {
        printf("  Testing %d widgets...\n", wc);

        std::vector<double> frameTimes;
        std::vector<double> cpuTimes;
        std::vector<double> gpuTimes;
        bool gpuTimingOk = false;

        frameTimes.reserve(numFrames);
        cpuTimes.reserve(numFrames);
        gpuTimes.reserve(numFrames);

        // Warmup phase
        for (int f = 0; f < warmupFrames; ++f)
        {
            if (window && glfwWindowShouldClose(window))
                break;
            renderFrame(ctx, wc);
        }

        // Measurement phase (manual render loop for precise timing)
        for (int f = 0; f < numFrames; ++f)
        {
            if (window && glfwWindowShouldClose(window))
                break;

            auto frameStart = Clock::now();

            glfwPollEvents();

#ifdef OMNIUI_HAS_VULKAN
            if (isVulkan)
                ImGui_ImplVulkan_NewFrame();
            else
#endif
                ImGui_ImplOpenGL3_NewFrame();

            ImGui_ImplGlfw_NewFrame();
            ImGui::NewFrame();

            // CPU time: widget submission + draw list building
            auto cpuStart = Clock::now();
            drawWidgetScene(wc);
            ImGui::Render();
            auto cpuEnd = Clock::now();

            // Backend render with GPU timing
#ifdef OMNIUI_HAS_VULKAN
            if (isVulkan && ctx.vkBackend)
            {
                int dw, dh;
                glfwGetWindowSize(window, &dw, &dh);
                if (dw > 0 && dh > 0)
                {
                    ctx.vkBackend->beginFrame(dw, dh);
                    VkCommandBuffer cmd = ctx.vkBackend->getCommandBuffer();

                    if (vkTimer.supported)
                    {
                        vkTimer.reset(cmd);
                        vkTimer.writeBegin(cmd);
                    }

                    ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), cmd);

                    if (vkTimer.supported)
                        vkTimer.writeEnd(cmd);

                    ctx.vkBackend->endFrame();

                    if (vkTimer.supported)
                    {
                        vkDeviceWaitIdle(ctx.vkBackend->getDevice());
                        gpuTimes.push_back(vkTimer.getElapsedMs());
                        gpuTimingOk = true;
                    }
                }
            }
            else
#endif
            {
                int dw, dh;
                glfwGetFramebufferSize(window, &dw, &dh);
                glViewport(0, 0, dw, dh);
                glClearColor(0.12f, 0.13f, 0.14f, 1.0f);
                glClear(GL_COLOR_BUFFER_BIT);

                if (glTimer.supported)
                    glTimer.begin();

                ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());

                if (glTimer.supported)
                {
                    glTimer.end();
                    glFinish();
                    gpuTimes.push_back(glTimer.getElapsedMs());
                    gpuTimingOk = true;
                }

                glfwSwapBuffers(window);
            }

            auto frameEnd = Clock::now();
            frameTimes.push_back(Duration(frameEnd - frameStart).count());
            cpuTimes.push_back(Duration(cpuEnd - cpuStart).count());
        }

        // Readback/screenshot latency (10 samples)
        std::vector<double> readbackTimes;
        {
            int dw = 1280, dh = 720;
            if (isGL)
                glfwGetFramebufferSize(window, &dw, &dh);
            else
                glfwGetWindowSize(window, &dw, &dh);

            std::vector<uint8_t> pixels(dw * dh * 4);

            for (int r = 0; r < 10; ++r)
            {
                renderFrame(ctx, wc);

#ifdef OMNIUI_HAS_VULKAN
                if (isVulkan && ctx.vkBackend)
                {
                    auto rbStart = Clock::now();
                    ctx.vkBackend->readbackPixels(pixels.data(), dw, dh);
                    auto rbEnd = Clock::now();
                    readbackTimes.push_back(Duration(rbEnd - rbStart).count());
                }
                else
#endif
                {
                    glFinish();
                    auto rbStart = Clock::now();
                    glReadPixels(0, 0, dw, dh, GL_RGBA, GL_UNSIGNED_BYTE, pixels.data());
                    glFinish();
                    auto rbEnd = Clock::now();
                    readbackTimes.push_back(Duration(rbEnd - rbStart).count());
                }
            }
        }

        BenchResult res;
        res.backend = isVulkan ? "VK" : "GL";
        res.widgetCount = wc;
        res.offscreen = offscreen;
        res.frameCount = numFrames;
        res.frameTime = computeStats(frameTimes);
        res.cpuTime = computeStats(cpuTimes);
        res.gpuTimingAvailable = gpuTimingOk;
        if (gpuTimingOk)
            res.gpuTime = computeStats(gpuTimes);
        if (!readbackTimes.empty())
        {
            double sum = 0;
            for (double v : readbackTimes)
                sum += v;
            res.readbackAvgMs = sum / (double)readbackTimes.size();
        }
        res.rssMB = getRSSMegabytes();
        results.push_back(res);
    }

    if (isGL)
        glTimer.destroy();

#ifdef OMNIUI_HAS_VULKAN
    if (isVulkan)
        vkTimer.destroy();
#endif

    omni::ui::standalone::shutdown();
    return results;
}
