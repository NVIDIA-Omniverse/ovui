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

/// Abstract interface for SVG rasterization.
/// Each backend provides its own implementation; if no rasterizer is
/// registered, VectorImageProvider becomes a graceful no-op.
class ISvgRasterizer
{
public:
    virtual ~ISvgRasterizer() = default;

    struct RasterResult
    {
        bool success = false;
        void* imGuiReference = nullptr;
        UInt2 imageSize = { 0, 0 };
        PixelFormat imageFormat = PixelFormat::eUnknown;
        std::string cacheKey;
    };

    /// Resolve the source URL to an asset path, check the GPU cache, and
    /// rasterize the SVG if it is not already cached.  Returns the texture
    /// handle, size, format, and cache key on success.
    virtual RasterResult rasterize(
        const std::string& url,
        float widgetWidth,
        float widgetHeight,
        size_t maxMipLevels,
        const ImageProviderTextureOptions& textureOptions) = 0;

    /// Release a previously acquired GPU cache entry.
    virtual void releaseGpuResource(const std::string& cacheKey) = 0;
};

} // namespace ui
} // namespace omni
