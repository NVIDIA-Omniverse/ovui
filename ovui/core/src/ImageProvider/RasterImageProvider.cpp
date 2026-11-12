/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
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
    m_loader = PlatformRegistry::instance().sharedRasterImageLoader();
}

RasterImageProvider::~RasterImageProvider()
{
    _shutdown();
}

void RasterImageProvider::_shutdown()
{
    // Only give the reference back. A provider going away says nothing about
    // the file, so the shared entry stays available to whoever still draws it
    // and to the next consumer of the same URL.
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

    auto* loader = m_loader.get();
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
        TextureOptions textureOptions = { 0 };
        if (!mergeTextureOptions(textureOptions))
            return;

        // Release old resources. Setting the same source URL again is how a
        // replaced file is reloaded, so in that case the old entry must also
        // stop being shared: the next load has to read the file rather than
        // return the texture decoded from its previous contents. Moving to a
        // different URL says nothing about the file left behind, so its entry
        // stays shared with the consumers still drawing it, and coming back to
        // it later reuses that texture instead of uploading another copy.
        loader->releaseLoad(this);
        if (!m_cacheKey.empty())
        {
            const bool reload = m_cacheKey == loader->getCacheKey(url);
            loader->releaseGpuResource(m_cacheKey);
            if (reload)
            {
                loader->invalidateCacheEntry(m_cacheKey);
            }
            m_cacheKey.clear();
        }

        auto result = loader->beginLoadWithOptions(this, url, textureOptions);
        if (result.status == IRasterImageLoader::LoadResult::eCached)
        {
            m_cacheKey = result.cacheKey;
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
            // Failed to begin load. The previous image's resources were handed
            // back to the loader above, so stop publishing them: keep reporting
            // the requested URL, but report no image so callers can fall back.
            setImageData(nullptr, { 0, 0 }, PixelFormat::eUnknown);
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
            m_cacheKey = result.cacheKey;
            setImageData(result.imGuiReference, result.imageSize, result.imageFormat, result.managedResource);
            m_assetLoading = false;
            {
                std::lock_guard<std::mutex> lock(m_sourceRasterUrlMutex);
                m_sourceRasterUrlChanged = false;
            }
        }
        else if (result.status == IRasterImageLoader::LoadResult::eFailed)
        {
            // Terminal failure of an asynchronous load. Same contract as the
            // begin-load failure above: the previous image is gone, so report
            // no image rather than the released one.
            setImageData(nullptr, { 0, 0 }, PixelFormat::eUnknown);
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

time_t RasterImageProvider::_getModTime(const std::string& path)
{
    return m_loader ? m_loader->getModTime(path) : 0;
}

std::string RasterImageProvider::_getCacheKey(const std::string& path)
{
    return m_loader ? m_loader->getCacheKey(path) : path;
}

void RasterImageProvider::_loadAsset(const std::string& path)
{
    auto* loader = m_loader.get();
    if (!loader)
        return;
    TextureOptions textureOptions = { 0 };
    if (!mergeTextureOptions(textureOptions))
        return;
    const auto result = loader->beginLoadWithOptions(this, path, textureOptions);
    m_assetLoading = result.status == IRasterImageLoader::LoadResult::eLoading;
    if (result.status == IRasterImageLoader::LoadResult::eCached)
    {
        m_cacheKey = result.cacheKey;
        setImageData(result.imGuiReference, result.imageSize, result.imageFormat, result.managedResource);
        std::lock_guard<std::mutex> lock(m_sourceRasterUrlMutex);
        m_sourceRasterUrlChanged = false;
    }
}

void RasterImageProvider::_pollAsset()
{
    auto* loader = m_loader.get();
    if (!loader || !m_assetLoading)
        return;

    // Waiting completes the CPU load and clears m_assetLoading. Legacy derived
    // callers still poll that completed load to publish its image afterwards.
    TextureOptions textureOptions = { 0 };
    if (!mergeTextureOptions(textureOptions))
        return;
    size_t maxMipLevels;
    {
        std::lock_guard<std::mutex> lock(m_maxMipLevelsMutex);
        maxMipLevels = m_maxMipLevels;
    }
    const auto result = loader->poll(this, textureOptions, maxMipLevels);
    if (result.status == IRasterImageLoader::LoadResult::eReady)
    {
        m_cacheKey = result.cacheKey;
        setImageData(result.imGuiReference, result.imageSize, result.imageFormat, result.managedResource);
    }
    else if (result.status == IRasterImageLoader::LoadResult::eFailed)
        setImageData(nullptr, { 0, 0 }, PixelFormat::eUnknown);
    else
        return;

    m_assetLoading = false;
    std::lock_guard<std::mutex> lock(m_sourceRasterUrlMutex);
    m_sourceRasterUrlChanged = false;
}

void RasterImageProvider::_waitAsset()
{
    if (auto* loader = m_loader.get())
        loader->waitForCompletion(this, m_shutdownIterMax);
}

void RasterImageProvider::_releaseAsset()
{
    if (auto* loader = m_loader.get())
    {
        loader->releaseLoad(this);
        if (!m_cacheKey.empty())
            loader->releaseGpuResource(m_cacheKey);
    }
    m_cacheKey.clear();
}
}
}
