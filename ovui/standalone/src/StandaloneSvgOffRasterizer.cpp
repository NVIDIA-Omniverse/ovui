/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include "StandaloneSvgOffRasterizer.h"

#include "platform/Log.h"

namespace omni {
namespace ui {
namespace standalone {

ISvgRasterizer::RasterResult StandaloneSvgOffRasterizer::rasterize(const std::string& url,
                                                                   float /*widgetWidth*/,
                                                                   float /*widgetHeight*/,
                                                                   size_t /*maxMipLevels*/,
                                                                   const ImageProviderTextureOptions& /*textureOptions*/)
{
    std::lock_guard<std::mutex> lock(m_mutex);
    if (m_loggedUrls.insert(url).second)
    {
        OMNIUI_LOG_ERROR("SVG: cannot draw '%s': this build has no SVG support (it was built with OMNIUI_ENABLE_SVG=OFF)",
                         url.c_str());
    }
    return {};
}

void StandaloneSvgOffRasterizer::releaseGpuResource(const std::string& /*cacheKey*/)
{
    // rasterize() never returns a cache key, so there is nothing to release.
}

} // namespace standalone
} // namespace ui
} // namespace omni
