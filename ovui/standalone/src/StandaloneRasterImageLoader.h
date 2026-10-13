/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
/// (OpenGL or Vulkan). Textures are cached per-URL; consumers that reference
/// the same URL share one GPU texture.
///
/// invalidateCacheEntry() unpublishes a URL so the next load decodes the file
/// again. That is how a provider reloads a replaced file. Consumers that still
/// draw the unpublished texture keep it alive and unchanged until they release
/// it, so one consumer's reload cannot pull a texture out from under another.
///
/// releaseGpuResource() and releaseLoad() only give a consumer's reference
/// back. They leave a slot other consumers still hold published, so closing one
/// preview of a file never makes the next preview of that same file decode and
/// upload a second copy.
///
/// Only successful loads are cached. A failed load is reported to its caller
/// but never remembered, so a file that appears or becomes readable later is
/// picked up by the next load of that URL.
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
    void invalidateCacheEntry(const std::string& cacheKey) override;

    /// Destroy every cached GPU state while IByteImageGpu is still registered,
    /// and refuse new loads after that. Providers can keep this loader after
    /// the backend shuts down; their later calls then do nothing.
    void shutdown();

private:
    struct CacheEntry
    {
        void* gpuState = nullptr;          ///< IByteImageGpu::Handle
        void* imGuiReference = nullptr;
        UInt2 size = {};
        PixelFormat format = PixelFormat::eRGBA8_UNORM;
        int refCount = 0;
        bool failed = false;

        /// Destroy the GPU state. An entry can outlive its m_cache slot while a
        /// consumer still draws it, so it owns its own texture lifetime.
        ~CacheEntry();
    };

    struct InstanceState
    {
        std::string cacheKey;
        /// Keeps the entry (and its texture) alive for this consumer even after
        /// the entry has been unpublished from m_cache by a reload.
        std::shared_ptr<CacheEntry> entry;
        LoadResult::Status status = LoadResult::eFailed;
    };

    std::shared_ptr<CacheEntry> _loadOrGetCached(const std::string& url, size_t maxMipLevels);

    /// Drop one consumer's reference. Caller holds m_mutex. Erases the m_cache
    /// slot when the last reference goes and the slot still holds this entry.
    void _releaseInstance(std::unordered_map<void*, InstanceState>::iterator it);

    std::mutex m_mutex;
    std::unordered_map<std::string, std::shared_ptr<CacheEntry>> m_cache;
    std::unordered_map<void*, InstanceState> m_instances;
    bool m_shutdown = false;
};

} // namespace standalone
} // namespace ui
} // namespace omni
