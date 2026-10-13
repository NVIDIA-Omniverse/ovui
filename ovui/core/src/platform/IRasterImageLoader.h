/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/platform/Types.h>
#include <omni/ui/ImageProvider/ImageProvider.h>

#include <ctime>
#include <string>

namespace omni {
namespace ui {

/// Abstract interface for raster image loading.
/// Each backend provides its own implementation (asset pipeline, imaging, etc.);
/// standalone may provide its own implementation or leave it unregistered
/// (RasterImageProvider becomes a graceful no-op when no loader is available).
class IRasterImageLoader
{
public:
    virtual ~IRasterImageLoader() = default;

    using GpuResource = rtx::resourcemanager::RpResource;

    struct LoadResult
    {
        enum Status { eCached, eLoading, eReady, eFailed };
        Status status = Status::eFailed;
        void* imGuiReference = nullptr;
        UInt2 imageSize = { 0, 0 };
        PixelFormat imageFormat = PixelFormat::eUnknown;
        GpuResource* managedResource = nullptr;
        std::string cacheKey;
    };

    /// Begin loading a raster image from a URL.
    /// instanceKey is an opaque pointer identifying the caller instance
    /// (used to track per-instance async loading state).
    /// If the image is in the GPU cache, returns eCached with image data.
    /// Otherwise starts async loading and returns eLoading.
    virtual LoadResult beginLoad(
        void* instanceKey,
        const std::string& url) = 0;

    /// Poll an in-progress async load.
    /// Returns eReady with image data when complete, eLoading while pending,
    /// or eFailed on error.
    virtual LoadResult poll(
        void* instanceKey,
        const ImageProviderTextureOptions& textureOptions,
        size_t maxMipLevels) = 0;

    /// Block until the async load completes or maxIterations is reached.
    virtual void waitForCompletion(void* instanceKey, int32_t maxIterations) = 0;

    /// Release all resources associated with a load instance.
    virtual void releaseLoad(void* instanceKey) = 0;

    /// Give one consumer's reference to a GPU cache entry back by key. The
    /// entry is freed once nothing references it any more; consumers that
    /// still hold the same key keep their image.
    virtual void releaseGpuResource(const std::string& cacheKey) = 0;

    /// Drop the cached entry for a key from the shared lookup, so the next
    /// load of that URL reads the file again instead of sharing the entry
    /// decoded earlier. Consumers still drawing that entry keep it, unchanged,
    /// until they release it. This is how a provider reloads a replaced file;
    /// it is deliberately not part of releasing a reference, because losing a
    /// consumer says nothing about the file having changed.
    virtual void invalidateCacheEntry(const std::string& /*cacheKey*/)
    {
    }
    virtual time_t getModTime(const std::string&) { return 0; }
    virtual std::string getCacheKey(const std::string& path) { return path; }

    /// Allocation requirements must be available before consulting a GPU cache.
    /// Keep the original entrypoint for existing backend implementations.
    virtual LoadResult beginLoadWithOptions(void* instanceKey, const std::string& url,
                                           const ImageProviderTextureOptions& textureOptions)
    {
        return beginLoad(instanceKey, url);
    }
};

} // namespace ui
} // namespace omni
