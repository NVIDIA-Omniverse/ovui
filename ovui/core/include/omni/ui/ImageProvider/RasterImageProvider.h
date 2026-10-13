/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "ImageProvider.h"

#include <ctime>
#include <memory>
#include <mutex>
#include <string>

namespace omni { namespace ui { class IUiSettings; } }

namespace omni
{
namespace ui
{

class IRasterImageLoader;

class OMNIUI_CLASS_API RasterImageProvider : public ImageProvider
{
public:
    OMNIUI_API
    RasterImageProvider(std::string = {});

    OMNIUI_API
    ~RasterImageProvider();

    /**
     * @brief Sets the raster image URL. Asset loading doesn't happen immediately, but rather is started the next time
     * widget is visible, in prepareDraw call.
     */
    OMNIUI_API
    virtual void setSourceUrl(const char* url);

    /**
     * @brief Returns vector image URL.
     */
    OMNIUI_API
    virtual std::string getSourceUrl() const;

    /**
     * @brief This function needs to be called every frame to make sure asset loading is moving forward, and resources
     * are properly allocated.
     */
    OMNIUI_API
    void prepareDraw(float widgetWidth, float widgetHeight) override;

    /**
     * @brief Sets the maximum number of mip map levels allowed.
     */
    OMNIUI_API
    virtual void setMaxMipLevels(size_t maxMipLevels);

    /**
     * @brief Returns the maximum number of mip map levels allowed.
     */
    OMNIUI_API
    virtual size_t getMaxMipLevels() const;

protected:
    void _shutdown();
    OMNIUI_API time_t _getModTime(const std::string& path);
    OMNIUI_API std::string _getCacheKey(const std::string& path);
    OMNIUI_API void _loadAsset(const std::string& path);
    OMNIUI_API void _pollAsset();
    OMNIUI_API void _waitAsset();
    OMNIUI_API void _releaseAsset();

    IUiSettings* m_settings = nullptr;
    // Shared with PlatformRegistry: the provider can outlive the backend shutdown
    // (for example, a Python global released at interpreter exit).
    std::shared_ptr<IRasterImageLoader> m_loader;
    int32_t m_shutdownIterMax = 0;
    std::string m_sourceRasterUrl;
    bool m_sourceRasterUrlChanged = false;
    mutable std::mutex m_sourceRasterUrlMutex;
    bool m_assetLoading = false;
    std::string m_cacheKey;

    size_t m_maxMipLevels = 3;
    mutable std::mutex m_maxMipLevelsMutex;
};

}
}
