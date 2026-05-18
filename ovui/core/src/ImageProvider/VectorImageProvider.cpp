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

#include <omni/ui/ImageProvider/VectorImageProvider.h>
#include "../platform/Log.h"
#include "../platform/PlatformRegistry.h"
#include "../platform/ISvgRasterizer.h"
#include "../platform/IUiSettings.h"
#include <omni/ui/Profile.h>

namespace omni
{
namespace ui
{

namespace
{
constexpr char kEnableCpuMipGenSettingsPath[] = "/exts/omni.ui/VectorImageProvider/enableCpuMipGen";
constexpr char kEnableCpuRasterMipGenSettingsPath[] = "/exts/omni.ui/VectorImageProvider/enableCpuRasterMipGen";
constexpr char kDebugOutputSettingsPath[] = "/exts/omni.ui/VectorImageProvider/debugOutput";
constexpr char kDebugColorizeMipsSettingsPath[] = "/exts/omni.ui/VectorImageProvider/debugColorizeMips";
} // anonymous namespace

VectorImageProvider::VectorImageProvider(std::string url)
    : m_sourceVectorUrl(std::move(url))
    , m_sourceVectorUrlChanged(!m_sourceVectorUrl.empty())
{
    auto* settings = omni::ui::PlatformRegistry::instance().settings();
    if (settings)
    {
        settings->setDefaultBool(kEnableCpuMipGenSettingsPath, true);
        settings->setDefaultBool(kEnableCpuRasterMipGenSettingsPath, false);
        settings->setDefaultBool(kDebugOutputSettingsPath, false);
        settings->setDefaultBool(kDebugColorizeMipsSettingsPath, false);
    }
}

VectorImageProvider::~VectorImageProvider()
{
    std::string cacheKey(std::move(m_cacheKey));
    if (!cacheKey.empty())
    {
        auto* rasterizer = PlatformRegistry::instance().svgRasterizer();
        if (rasterizer)
        {
            rasterizer->releaseGpuResource(cacheKey);
        }
    }
}

void VectorImageProvider::prepareDraw(float widgetWidth, float widgetHeight)
{
    if (widgetWidth == 0.0f || widgetHeight == 0.0f)
    {
        return;
    }

    OMNIUI_PROFILE_VERBOSE_ZONE("VectorImageProvider::prepareDraw");

    auto* rasterizer = PlatformRegistry::instance().svgRasterizer();
    if (!rasterizer)
    {
        return;
    }

    std::string url;
    bool urlChanged = false;
    {
        std::lock_guard<std::mutex> lock(m_sourceVectorUrlMutex);
        url = m_sourceVectorUrl;
        urlChanged = m_sourceVectorUrlChanged;
    }

    if (urlChanged)
    {
        // Release old cache entry
        if (!m_cacheKey.empty())
        {
            rasterizer->releaseGpuResource(m_cacheKey);
            m_cacheKey.clear();
        }

        TextureOptions textureOptions = { 0 };
        if (!mergeTextureOptions(textureOptions))
        {
            OMNIUI_LOG_ERROR("Failed to get texture options");
            return;
        }

        size_t maxMipLevels;
        {
            std::lock_guard<std::mutex> lock(m_maxMipLevelsMutex);
            maxMipLevels = m_maxMipLevels;
        }

        auto result = rasterizer->rasterize(url, widgetWidth, widgetHeight, maxMipLevels, textureOptions);
        if (result.success)
        {
            m_cacheKey = std::move(result.cacheKey);
            setImageData(result.imGuiReference, result.imageSize, result.imageFormat);
        }

        std::lock_guard<std::mutex> lock(m_sourceVectorUrlMutex);
        m_sourceVectorUrlChanged = false;
    }
}

void VectorImageProvider::setSourceUrl(const char* url)
{
    std::lock_guard<std::mutex> lock(m_sourceVectorUrlMutex);
    m_sourceVectorUrl = url;
    m_sourceVectorUrlChanged = true;
}

std::string VectorImageProvider::getSourceUrl() const
{
    std::lock_guard<std::mutex> lock(m_sourceVectorUrlMutex);
    return m_sourceVectorUrl;
}

void VectorImageProvider::setMaxMipLevels(size_t maxMipLevels)
{
    std::lock_guard<std::mutex> lock(m_maxMipLevelsMutex);
    m_maxMipLevels = maxMipLevels;
}

size_t VectorImageProvider::getMaxMipLevels() const
{
    std::lock_guard<std::mutex> lock(m_maxMipLevelsMutex);
    return m_maxMipLevels;
}

}
}
