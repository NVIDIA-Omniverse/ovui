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

#include <omni/ui/platform/Types.h>
#include <omni/ui/ImageProvider/ImageProvider.h>

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

    /// Release a GPU cache entry by key.
    virtual void releaseGpuResource(const std::string& cacheKey) = 0;
};

} // namespace ui
} // namespace omni
