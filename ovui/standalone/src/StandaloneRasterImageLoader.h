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

#include "platform/IRasterImageLoader.h"

#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>

namespace omni {
namespace ui {
namespace standalone {

/// Standalone IRasterImageLoader implementation.
///
/// Decodes PNG/JPG/BMP/TGA/etc. from local filesystem paths using stb_image
/// and uploads the decoded RGBA pixels through the registered IByteImageGpu
/// (OpenGL or Vulkan). Textures are cached per-URL; multiple providers that
/// reference the same URL share one GPU texture.
class StandaloneRasterImageLoader final : public IRasterImageLoader
{
public:
    StandaloneRasterImageLoader() = default;
    ~StandaloneRasterImageLoader() override;

    LoadResult beginLoad(void* instanceKey, const std::string& url) override;
    LoadResult poll(void* instanceKey,
                    const ImageProviderTextureOptions& textureOptions,
                    size_t maxMipLevels) override;
    void waitForCompletion(void* instanceKey, int32_t maxIterations) override;
    void releaseLoad(void* instanceKey) override;
    void releaseGpuResource(const std::string& cacheKey) override;

private:
    struct CacheEntry
    {
        void* gpuState = nullptr;          ///< IByteImageGpu::Handle
        void* imGuiReference = nullptr;
        UInt2 size = {};
        PixelFormat format = PixelFormat::eRGBA8_UNORM;
        int refCount = 0;
        bool failed = false;
    };

    struct InstanceState
    {
        std::string cacheKey;
        LoadResult::Status status = LoadResult::eFailed;
    };

    std::shared_ptr<CacheEntry> _loadOrGetCached(const std::string& url, size_t maxMipLevels);

    std::mutex m_mutex;
    std::unordered_map<std::string, std::shared_ptr<CacheEntry>> m_cache;
    std::unordered_map<void*, InstanceState> m_instances;
};

} // namespace standalone
} // namespace ui
} // namespace omni
