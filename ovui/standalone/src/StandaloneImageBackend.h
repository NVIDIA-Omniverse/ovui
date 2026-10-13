/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "platform/IImageBackend.h"

#include <memory>
#include <mutex>
#include <string>
#include <unordered_set>

namespace omni {
namespace ui {
namespace standalone {

class StandaloneRasterImageLoader;

/// Standalone IImageBackend implementation for the ui.Image widget.
///
/// Loads local raster files (PNG/JPG/BMP/TGA/etc.) through the registered
/// StandaloneRasterImageLoader, so ui.Image and RasterImageProvider share one
/// decoder and one GPU texture cache. Accepts plain paths and file:// URLs.
/// Logs an error once per URL when the image cannot be loaded.
class StandaloneImageBackend final : public IImageBackend
{
public:
    /// @param loader The raster loader, or nullptr when no GPU texture upload is
    ///               available. Held weakly: the loader is released at shutdown
    ///               before Python drops its last Image.
    explicit StandaloneImageBackend(std::shared_ptr<StandaloneRasterImageLoader> loader);

    LoadResult loadTexture(const std::string& sourceUrl,
                           float contentWidth,
                           float contentHeight,
                           SetTextureDataFn setTextureData,
                           NotifyProgressFn notifyProgress) override;

    void* getImGuiTextureId(const TextureHandle& handle) const override;

    /// Convert a file:// URL to a local path. Other strings are returned as is.
    static std::string urlToLocalPath(const std::string& sourceUrl);

private:
    void _logFailure(const std::string& sourceUrl, const char* reason);

    std::weak_ptr<StandaloneRasterImageLoader> m_loader;
    std::mutex m_loggedMutex;
    std::unordered_set<std::string> m_loggedUrls;
};

} // namespace standalone
} // namespace ui
} // namespace omni
