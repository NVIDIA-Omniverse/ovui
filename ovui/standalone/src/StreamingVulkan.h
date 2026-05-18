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

#include <cstdint>
#include <cstdio>
#include <functional>
#include <memory>
#include <string>
#include <vector>

#include <vulkan/vulkan.h>

namespace omni {
namespace ui {
namespace standalone {

class VulkanBackend;

/// Statistics for a single encoded frame.
struct StreamFrameStats
{
    double encodeTimeMs = 0.0;   ///< Time spent encoding this frame
    double totalTimeMs  = 0.0;   ///< Total pipeline latency (readback + encode)
    uint32_t nalSize    = 0;     ///< Size of output NAL unit in bytes
};

/// Codec selection for the streaming encoder.
enum class StreamCodec
{
    eH264,
    eHEVC,
};

/// Configuration for the streaming pipeline.
struct StreamingConfig
{
    int width           = 1280;
    int height          = 720;
    int fps             = 60;
    int bitrateMbps     = 10;
    StreamCodec codec   = StreamCodec::eH264;
    bool useCudaInterop = true;   ///< Attempt CUDA interop for zero-copy (falls back if unavailable)
};

/// Callback invoked with each encoded NAL unit.
/// @param nalData    Pointer to the NAL unit bytes.
/// @param nalSize    Size in bytes.
/// @param pts        Presentation timestamp (frame index).
using NalCallback = std::function<void(const uint8_t* nalData, uint32_t nalSize, uint64_t pts)>;

// ---------------------------------------------------------------------------
// StreamingVulkan — Vulkan-native streaming pipeline:
//   VkImage → (CUDA interop | CPU readback) → NVENC → H.264/HEVC NAL units
// ---------------------------------------------------------------------------
class StreamingVulkan
{
public:
    StreamingVulkan();
    ~StreamingVulkan();

    /// Initialize the streaming pipeline. Must be called after VulkanBackend::init().
    bool init(VulkanBackend* backend, const StreamingConfig& config);

    /// Shut down the encoder and release all resources.
    void shutdown();

    /// Encode the current VkImage from the backend.
    /// Call this after VulkanBackend::endFrame() each frame.
    /// Invokes nalCallback with the encoded NAL unit.
    bool encodeFrame(uint64_t pts, NalCallback nalCallback = nullptr);

    /// Get the stats for the last encoded frame.
    StreamFrameStats getLastFrameStats() const { return m_lastStats; }

    /// Check if hardware (NVENC) encoding is active.
    bool isHardwareEncoder() const { return m_useNvenc; }

    /// Check initialization state.
    bool isInitialized() const { return m_initialized; }

    /// Get the encoder name string (for logging).
    const char* getEncoderName() const;

private:
    // NVENC hardware encoder (ifdef guarded)
    bool initNvenc();
    void shutdownNvenc();
    bool encodeFrameNvenc(const uint8_t* rgba, uint32_t size, uint64_t pts);

    // CUDA-Vulkan interop (ifdef guarded)
    bool initCudaInterop();
    void shutdownCudaInterop();
    bool readbackViaCuda(uint8_t* outPixels);

    // CPU fallback encoder (always available)
    bool initCpuEncoder();
    void shutdownCpuEncoder();
    bool encodeFrameCpu(const uint8_t* rgba, uint32_t size, uint64_t pts);

    // Vulkan semaphore sync between render and encode
    bool createSyncObjects();
    void destroySyncObjects();

    VulkanBackend*  m_backend     = nullptr;
    StreamingConfig m_config;
    bool            m_initialized = false;
    bool            m_useNvenc    = false;
    bool            m_useCuda     = false;

    // Vulkan sync
    VkSemaphore     m_renderDoneSemaphore = VK_NULL_HANDLE;
    VkSemaphore     m_encodeDoneSemaphore = VK_NULL_HANDLE;
    VkFence         m_encodeFence         = VK_NULL_HANDLE;
    VkCommandPool   m_encodeCommandPool   = VK_NULL_HANDLE;
    VkCommandBuffer m_encodeCommandBuffer = VK_NULL_HANDLE;

    // Staging buffer for CPU readback path
    VkBuffer        m_stagingBuffer       = VK_NULL_HANDLE;
    VkDeviceMemory  m_stagingMemory       = VK_NULL_HANDLE;
    VkDeviceSize    m_stagingSize         = 0;

    // Pixel buffer (CPU-side)
    std::vector<uint8_t> m_pixelBuffer;

    // Encoded output buffer
    std::vector<uint8_t> m_encodedBuffer;

    // Stats
    StreamFrameStats m_lastStats;
    NalCallback      m_nalCallback;

    // NVENC opaque handle
    void* m_nvencEncoder  = nullptr;
    void* m_nvencSession  = nullptr;

    // CUDA interop handles
    void* m_cudaExtMemory = nullptr;
    void* m_cudaMappedPtr = nullptr;

    // CPU encoder state
    uint64_t m_cpuFrameCount = 0;
    std::vector<uint8_t> m_cpuPrevFrame;  // For simple delta encoding
};

} // namespace standalone
} // namespace ui
} // namespace omni
