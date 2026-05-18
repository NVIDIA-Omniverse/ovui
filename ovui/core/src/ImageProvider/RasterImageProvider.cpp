/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include <omni/ui/ImageProvider/RasterImageProvider.h>
#include "../platform/PlatformRegistry.h"
#include "../platform/IRasterImageLoader.h"
#include "../platform/IUiSettings.h"
#include "../platform/Log.h"
#include <omni/ui/Profile.h>

namespace omni
{
namespace ui
{

namespace
{
constexpr char kEnableCpuMipGenSettingsPath[] = "/exts/omni.ui/RasterImageProvider/enableCpuMipGen";
constexpr char kEnableOmniGpuCacheSettingsPath[] = "/exts/omni.ui/RasterImageProvider/enableOmniGpuCache";
constexpr char kShutdownIterMaxSettingsPath[] = "/exts/omni.ui/RasterImageProvider/shutdownIterMax";
} // anonymous namespace

RasterImageProvider::RasterImageProvider(std::string url)
    : m_sourceRasterUrl(std::move(url))
    , m_sourceRasterUrlChanged(!m_sourceRasterUrl.empty())
{
    m_settings = omni::ui::PlatformRegistry::instance().settings();
    if (m_settings)
    {
        m_settings->setDefaultBool(kEnableCpuMipGenSettingsPath, true);
        m_settings->setDefaultBool(kEnableOmniGpuCacheSettingsPath, false);
        m_settings->setDefaultInt(kShutdownIterMaxSettingsPath, 4000);
        m_shutdownIterMax = m_settings->getInt(kShutdownIterMaxSettingsPath, 4000);
    }
    m_loader = PlatformRegistry::instance().rasterImageLoader();
}

RasterImageProvider::~RasterImageProvider()
{
    _shutdown();
}

void RasterImageProvider::_shutdown()
{
    if (m_loader)
    {
        m_loader->waitForCompletion(this, m_shutdownIterMax);
        m_loader->releaseLoad(this);
    }
    if (!m_cacheKey.empty() && m_loader)
    {
        m_loader->releaseGpuResource(m_cacheKey);
        m_cacheKey.clear();
    }
    m_assetLoading = false;
}

void RasterImageProvider::prepareDraw(float widgetWidth, float widgetHeight)
{
    OMNIUI_PROFILE_VERBOSE_ZONE("RasterImageProvider::prepareDraw");

    auto* loader = m_loader;
    if (!loader)
    {
        return;
    }

    std::string url;
    bool urlChanged = false;
    {
        std::lock_guard<std::mutex> lock(m_sourceRasterUrlMutex);
        url = m_sourceRasterUrl;
        urlChanged = m_sourceRasterUrlChanged;
    }

    if (urlChanged && !m_assetLoading)
    {
        // Release old resources
        loader->releaseLoad(this);
        if (!m_cacheKey.empty())
        {
            loader->releaseGpuResource(m_cacheKey);
            m_cacheKey.clear();
        }

        auto result = loader->beginLoad(this, url);
        m_cacheKey = result.cacheKey;

        if (result.status == IRasterImageLoader::LoadResult::eCached)
        {
            setImageData(result.imGuiReference, result.imageSize, result.imageFormat, result.managedResource);
            {
                std::lock_guard<std::mutex> lock(m_sourceRasterUrlMutex);
                m_sourceRasterUrlChanged = false;
            }
        }
        else if (result.status == IRasterImageLoader::LoadResult::eLoading)
        {
            m_assetLoading = true;
        }
        else
        {
            // Failed to begin load
            {
                std::lock_guard<std::mutex> lock(m_sourceRasterUrlMutex);
                m_sourceRasterUrlChanged = false;
            }
        }
    }

    if (m_assetLoading)
    {
        TextureOptions textureOptions = { 0 };
        if (!mergeTextureOptions(textureOptions))
        {
            OMNIUI_LOG_ERROR("Failed to get texture options for asset '%s'", m_cacheKey.c_str());
            return;
        }

        size_t maxMipLevels;
        {
            std::lock_guard<std::mutex> lock(m_maxMipLevelsMutex);
            maxMipLevels = m_maxMipLevels;
        }

        auto result = loader->poll(this, textureOptions, maxMipLevels);
        if (result.status == IRasterImageLoader::LoadResult::eReady)
        {
            setImageData(result.imGuiReference, result.imageSize, result.imageFormat, result.managedResource);
            m_assetLoading = false;
            {
                std::lock_guard<std::mutex> lock(m_sourceRasterUrlMutex);
                m_sourceRasterUrlChanged = false;
            }
        }
        else if (result.status == IRasterImageLoader::LoadResult::eFailed)
        {
            m_assetLoading = false;
            {
                std::lock_guard<std::mutex> lock(m_sourceRasterUrlMutex);
                m_sourceRasterUrlChanged = false;
            }
        }
    }
}

void RasterImageProvider::setSourceUrl(const char* url)
{
    std::lock_guard<std::mutex> lock(m_sourceRasterUrlMutex);
    if (m_sourceRasterUrlChanged)
    {
        OMNIUI_LOG_ERROR("Cannot change URL mid-transition");
        return;
    }
    m_sourceRasterUrl = url;
    m_sourceRasterUrlChanged = true;
}

std::string RasterImageProvider::getSourceUrl() const
{
    std::lock_guard<std::mutex> lock(m_sourceRasterUrlMutex);
    return m_sourceRasterUrl;
}

void RasterImageProvider::setMaxMipLevels(size_t maxMipLevels)
{
    std::lock_guard<std::mutex> lock(m_maxMipLevelsMutex);
    m_maxMipLevels = maxMipLevels;
}

size_t RasterImageProvider::getMaxMipLevels() const
{
    std::lock_guard<std::mutex> lock(m_maxMipLevelsMutex);
    return m_maxMipLevels;
}

}
}
