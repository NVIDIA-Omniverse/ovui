/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "platform/ISvgRasterizer.h"

#include <mutex>
#include <string>
#include <unordered_set>

namespace omni {
namespace ui {
namespace standalone {

/// The ISvgRasterizer that `init` registers when the library was built with
/// OMNIUI_ENABLE_SVG=OFF. It draws nothing. It logs the cause once for each
/// URL, so that an .svg image that stays empty has a message that says why.
class StandaloneSvgOffRasterizer final : public ISvgRasterizer
{
public:
    RasterResult rasterize(const std::string& url,
                           float widgetWidth,
                           float widgetHeight,
                           size_t maxMipLevels,
                           const ImageProviderTextureOptions& textureOptions) override;
    void releaseGpuResource(const std::string& cacheKey) override;

private:
    std::mutex m_mutex;
    std::unordered_set<std::string> m_loggedUrls;
};

} // namespace standalone
} // namespace ui
} // namespace omni
