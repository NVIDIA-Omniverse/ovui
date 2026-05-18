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

// CUDA-Vulkan interop integration test.
// Renders a frame via VulkanBackend, maps the result to CUDA without CPU
// readback, then copies from the CUDA array to host memory and saves a PNG
// to prove the zero-copy path works.

#include "VulkanBackend.h"
#include "CudaVulkanInterop.h"

#include <imgui/imgui.h>
#include <imgui/backends/imgui_impl_vulkan.h>
#include <GLFW/glfw3.h>

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include <stb_image_write.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

using namespace omni::ui::standalone;

static const int WIDTH = 512;
static const int HEIGHT = 512;
static const char* OUTPUT_PNG = "cuda_vk_interop_proof.png";
static const char* READBACK_PNG = "cpu_readback_reference.png";

int main()
{
    fprintf(stdout, "=== CUDA-Vulkan Interop Test ===\n\n");

    // -----------------------------------------------------------------------
    // 1. Initialize GLFW (headless — no window needed but GLFW must init)
    // -----------------------------------------------------------------------
    if (!glfwInit())
    {
        fprintf(stderr, "FATAL: glfwInit failed\n");
        return 1;
    }
    glfwWindowHint(GLFW_CLIENT_API, GLFW_NO_API);
    glfwWindowHint(GLFW_VISIBLE, GLFW_FALSE);
    GLFWwindow* window = glfwCreateWindow(WIDTH, HEIGHT, "cuda_interop_test", nullptr, nullptr);

    // -----------------------------------------------------------------------
    // 2. Initialize Vulkan backend
    // -----------------------------------------------------------------------
    VulkanBackend vkBackend;
    if (!vkBackend.init(window, WIDTH, HEIGHT))
    {
        fprintf(stderr, "FATAL: VulkanBackend::init failed\n");
        glfwDestroyWindow(window);
        glfwTerminate();
        return 1;
    }

    // Create ImGui context and init Vulkan backend for it
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2((float)WIDTH, (float)HEIGHT);
    io.DeltaTime = 1.0f / 60.0f;

    if (!vkBackend.initImGui())
    {
        fprintf(stderr, "FATAL: initImGui failed\n");
        vkBackend.shutdown();
        glfwDestroyWindow(window);
        glfwTerminate();
        return 1;
    }

    // -----------------------------------------------------------------------
    // 3. Render a test frame with some ImGui content
    // -----------------------------------------------------------------------
    fprintf(stdout, "\n--- Rendering test frame via Vulkan ---\n");

    // New frame
    ImGui_ImplVulkan_NewFrame();
    ImGui::NewFrame();

    // Draw some visible content to verify the image is correct
    ImGui::SetNextWindowPos(ImVec2(50, 50));
    ImGui::SetNextWindowSize(ImVec2(400, 400));
    ImGui::Begin("CUDA-Vulkan Interop Test", nullptr,
                 ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoCollapse);
    ImGui::TextColored(ImVec4(0.0f, 1.0f, 0.4f, 1.0f), "Zero-Copy Pipeline Active");
    ImGui::Separator();
    ImGui::Text("VK_EXT_external_memory_fd");
    ImGui::Text("VK_KHR_external_memory");
    ImGui::Text("VK_KHR_external_semaphore_fd");
    ImGui::Spacing();
    ImGui::TextWrapped("This frame was rendered by Vulkan, mapped to CUDA "
                       "via external memory (no CPU readback), then copied "
                       "from the CUDA array to host for verification.");
    ImGui::Spacing();

    // Draw a colored rectangle pattern for visual verification
    ImDrawList* drawList = ImGui::GetWindowDrawList();
    ImVec2 p = ImGui::GetCursorScreenPos();
    for (int i = 0; i < 8; i++)
    {
        for (int j = 0; j < 8; j++)
        {
            ImU32 col = IM_COL32(i * 32, j * 32, 128, 255);
            drawList->AddRectFilled(
                ImVec2(p.x + j * 45, p.y + i * 25),
                ImVec2(p.x + j * 45 + 40, p.y + i * 25 + 20),
                col);
        }
    }

    ImGui::End();
    ImGui::Render();

    vkBackend.beginFrame(WIDTH, HEIGHT);
    ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), vkBackend.getCommandBuffer());
    vkBackend.endFrame();

    // -----------------------------------------------------------------------
    // 4. CPU readback (reference — the OLD path via staging buffer)
    // -----------------------------------------------------------------------
    fprintf(stdout, "\n--- CPU readback (reference) ---\n");
    std::vector<uint8_t> cpuPixels(WIDTH * HEIGHT * 4);
    if (!vkBackend.readbackPixels(cpuPixels.data(), WIDTH, HEIGHT))
    {
        fprintf(stderr, "FATAL: readbackPixels failed\n");
        ImGui::DestroyContext();
        vkBackend.shutdown();
        glfwDestroyWindow(window);
        glfwTerminate();
        return 1;
    }
    stbi_write_png(READBACK_PNG, WIDTH, HEIGHT, 4, cpuPixels.data(), WIDTH * 4);
    fprintf(stdout, "Saved CPU readback reference: %s\n", READBACK_PNG);

    // Need to re-render the frame since readbackPixels used the command buffer
    ImGui_ImplVulkan_NewFrame();
    ImGui::NewFrame();
    ImGui::SetNextWindowPos(ImVec2(50, 50));
    ImGui::SetNextWindowSize(ImVec2(400, 400));
    ImGui::Begin("CUDA-Vulkan Interop Test", nullptr,
                 ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoCollapse);
    ImGui::TextColored(ImVec4(0.0f, 1.0f, 0.4f, 1.0f), "Zero-Copy Pipeline Active");
    ImGui::Separator();
    ImGui::Text("VK_EXT_external_memory_fd");
    ImGui::Text("VK_KHR_external_memory");
    ImGui::Text("VK_KHR_external_semaphore_fd");
    ImGui::Spacing();
    ImGui::TextWrapped("This frame was rendered by Vulkan, mapped to CUDA "
                       "via external memory (no CPU readback), then copied "
                       "from the CUDA array to host for verification.");
    ImGui::Spacing();
    drawList = ImGui::GetWindowDrawList();
    p = ImGui::GetCursorScreenPos();
    for (int i = 0; i < 8; i++)
    {
        for (int j = 0; j < 8; j++)
        {
            ImU32 col = IM_COL32(i * 32, j * 32, 128, 255);
            drawList->AddRectFilled(
                ImVec2(p.x + j * 45, p.y + i * 25),
                ImVec2(p.x + j * 45 + 40, p.y + i * 25 + 20),
                col);
        }
    }
    ImGui::End();
    ImGui::Render();

    vkBackend.beginFrame(WIDTH, HEIGHT);
    ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), vkBackend.getCommandBuffer());
    vkBackend.endFrame();

    // Wait for rendering to complete
    vkDeviceWaitIdle(vkBackend.getDevice());

    // -----------------------------------------------------------------------
    // 5. Initialize CUDA-Vulkan interop (the NEW zero-copy path)
    // -----------------------------------------------------------------------
    fprintf(stdout, "\n--- Initializing CUDA-Vulkan interop ---\n");
    CudaVulkanInterop interop;
    if (!interop.init(vkBackend))
    {
        fprintf(stderr, "FATAL: CudaVulkanInterop::init failed\n");
        ImGui::DestroyContext();
        vkBackend.shutdown();
        glfwDestroyWindow(window);
        glfwTerminate();
        return 1;
    }

    // -----------------------------------------------------------------------
    // 6. Sync Vulkan → CUDA and read from CUDA array
    // -----------------------------------------------------------------------
    fprintf(stdout, "\n--- Zero-copy: Vulkan → CUDA (no CPU staging) ---\n");
    if (!interop.syncVulkanToCuda())
    {
        fprintf(stderr, "FATAL: syncVulkanToCuda failed\n");
        interop.shutdown();
        ImGui::DestroyContext();
        vkBackend.shutdown();
        glfwDestroyWindow(window);
        glfwTerminate();
        return 1;
    }

    // Copy from CUDA array to host (for verification only)
    std::vector<uint8_t> cudaPixels(WIDTH * HEIGHT * 4);
    if (!interop.copyToHost(cudaPixels.data(), WIDTH, HEIGHT))
    {
        fprintf(stderr, "FATAL: copyToHost failed\n");
        interop.shutdown();
        ImGui::DestroyContext();
        vkBackend.shutdown();
        glfwDestroyWindow(window);
        glfwTerminate();
        return 1;
    }

    // Signal back to Vulkan
    interop.syncCudaToVulkan();
    vkDeviceWaitIdle(vkBackend.getDevice());

    // Save the CUDA-path result
    stbi_write_png(OUTPUT_PNG, WIDTH, HEIGHT, 4, cudaPixels.data(), WIDTH * 4);
    fprintf(stdout, "Saved CUDA zero-copy result: %s\n", OUTPUT_PNG);

    // -----------------------------------------------------------------------
    // 7. Verify: compare CUDA path vs CPU readback
    // -----------------------------------------------------------------------
    fprintf(stdout, "\n--- Verification ---\n");
    size_t totalPixels = (size_t)WIDTH * HEIGHT * 4;
    size_t matchCount = 0;
    for (size_t i = 0; i < totalPixels; i++)
    {
        if (cudaPixels[i] == cpuPixels[i])
            matchCount++;
    }

    double matchPct = 100.0 * matchCount / totalPixels;
    fprintf(stdout, "Pixel match: %zu / %zu (%.1f%%)\n", matchCount, totalPixels, matchPct);

    // Check that the image has non-trivial content (not all black/clear)
    size_t nonZero = 0;
    for (size_t i = 0; i < totalPixels; i++)
    {
        if (cudaPixels[i] != 0)
            nonZero++;
    }
    fprintf(stdout, "Non-zero bytes: %zu / %zu\n", nonZero, totalPixels);

    bool pass = (matchPct > 99.0) && (nonZero > totalPixels / 10);
    fprintf(stdout, "\n%s: CUDA-Vulkan zero-copy interop %s\n",
            pass ? "PASS" : "FAIL",
            pass ? "working correctly" : "FAILED verification");

    // -----------------------------------------------------------------------
    // Cleanup
    // -----------------------------------------------------------------------
    interop.shutdown();
    ImGui::DestroyContext();
    vkBackend.shutdown();
    glfwDestroyWindow(window);
    glfwTerminate();

    return pass ? 0 : 1;
}
